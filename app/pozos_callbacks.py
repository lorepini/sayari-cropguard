"""
Callbacks for the Pozos tab.

For v0 we fetch live ENSO/weather data on the auto-refresh tick (every 5 min).
The forecast uses placeholder coefficients in src.water_balance until Phase 3
calibrates them against the 5 NGO measurements.
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, html
import dash_bootstrap_components as dbc

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.data_sources import open_meteo, noaa_oni, andes_rainfall
from src.water_balance import (
    PUMP_CAPACITY_L_PER_DAY,
    WaterBalanceParams,
    days_until_critical,
    forecast_with_uncertainty,
)


ROOT = Path(__file__).resolve().parent.parent
WELLS_GEOJSON = ROOT / "data" / "wells" / "wells.geojson"
DISTRIBUTION_JSON = ROOT / "data" / "wells" / "distribution_system.json"
WELLS_HISTORY = ROOT / "data" / "processed" / "wells_history.parquet"
PARAMS_JSON = ROOT / "data" / "processed" / "water_balance_params.json"


def _load_calibrated_params() -> tuple[WaterBalanceParams, dict]:
    """Load calibrated params + metadata. Falls back to defaults if not yet calibrated."""
    if not PARAMS_JSON.exists():
        return WaterBalanceParams(), {"calibrated": False}
    payload = json.load(open(PARAMS_JSON))
    return WaterBalanceParams(**payload["params"]), {"calibrated": True, **payload["metadata"]}


def _load_wells():
    return json.load(open(WELLS_GEOJSON))


def _load_distribution():
    return json.load(open(DISTRIBUTION_JSON))


def _load_history() -> pd.DataFrame:
    if not WELLS_HISTORY.exists():
        return pd.DataFrame()
    df = pd.read_parquet(WELLS_HISTORY)
    df["date"] = pd.to_datetime(df["date"])
    return df


def _build_well_map(wells: dict) -> go.Figure:
    op_lats, op_lons, op_names, op_hover = [], [], [], []
    oos_lats, oos_lons, oos_names, oos_hover = [], [], [], []

    for f in wells["features"]:
        coords = f["geometry"]["coordinates"]
        p = f["properties"]
        is_pozo2 = p["well_id"] == "pozo2_asr"
        is_oos = p.get("status") == "out_of_service"
        # Pozo 2 has placeholder coords (same as Pozo 1) — nudge so both render
        lon = coords[0] + (0.003 if is_pozo2 else 0)
        lat = coords[1] + (0.002 if is_pozo2 else 0)
        sustainable = p.get("sustainable_yield_l_per_day", "—")
        depth = p.get("drilled_depth_m", "—")
        pump = p.get("operational_pump_model", "—")
        coord_note = "" if not is_pozo2 else "<br><i>(coords aprox - pendientes)</i>"
        status_note = (
            "<br><b style='color:#E74C3C'>⚠ FUERA DE SERVICIO</b>"
            if is_oos else ""
        )
        hover_text = (
            f"<b>{p['name']}</b>{status_note}{coord_note}<br>"
            f"Profundidad: {depth} m<br>"
            f"Bomba: {pump}<br>"
            f"Yield sostenible: {sustainable:,} L/día"
            if isinstance(sustainable, int)
            else f"<b>{p['name']}</b>{status_note}{coord_note}<br>"
                 f"Profundidad: {depth} m<br>Bomba: {pump}"
        )

        if is_oos:
            oos_lats.append(lat); oos_lons.append(lon)
            oos_names.append(p["name"] + " (fuera de servicio)")
            oos_hover.append(hover_text)
        else:
            op_lats.append(lat); op_lons.append(lon)
            op_names.append(p["name"])
            op_hover.append(hover_text)

    fig = go.Figure()

    # Recharge direction arrow (Río Zaña) — simple visual hint
    fig.add_trace(go.Scattermap(
        lon=[-79.20, -79.46],
        lat=[-6.78, -6.89],
        mode="lines+markers",
        line=dict(width=3, color="rgba(40, 116, 166, 0.6)"),
        marker=dict(size=[6, 14], color="#2874A6", symbol="circle"),
        hoverinfo="text",
        hovertext=["Río Zaña<br>(cuenca alta - Andes)", "Aporte hídrico<br>al acuífero"],
        showlegend=False,
    ))

    if op_lats:
        fig.add_trace(go.Scattermap(
            lon=op_lons, lat=op_lats,
            mode="markers+text",
            marker=dict(size=28, color="#00897B", opacity=0.95),
            text=op_names, textposition="top right",
            textfont=dict(size=12, color="#1A2744"),
            hoverinfo="text", hovertext=op_hover, showlegend=False,
        ))

    if oos_lats:
        fig.add_trace(go.Scattermap(
            lon=oos_lons, lat=oos_lats,
            mode="markers+text",
            marker=dict(size=22, color="#95A5A6", opacity=0.55,
                        symbol="circle"),
            text=oos_names, textposition="top right",
            textfont=dict(size=11, color="#7F8C8D"),
            hoverinfo="text", hovertext=oos_hover, showlegend=False,
        ))

    fig.update_layout(
        map_style="open-street-map",
        map_zoom=10.5,
        map_center={"lat": -6.85, "lon": -79.40},
        margin={"r": 0, "t": 0, "l": 0, "b": 0},
        paper_bgcolor="white",
    )
    return fig


def _build_forecast_chart(
    history: pd.DataFrame,
    oni_anom: float,
    params: WaterBalanceParams,
    residual_std_m: float,
    calibrated: bool,
) -> tuple[go.Figure, int | None]:
    """Returns (figure, days_until_critical) where the threshold is 2.0 m static column."""
    pozo1 = history[history["well_id"] == "pozo1_asr"].sort_values("date")

    fig = go.Figure()
    days_to_critical: int | None = None

    # Historical observed values (5 points from Chequeo)
    fig.add_trace(go.Scatter(
        x=pozo1["date"],
        y=pozo1["nivel_estatico_m"],
        mode="lines+markers",
        name="N. Estático observado",
        line=dict(color="#1A2744", width=3),
        marker=dict(size=10, symbol="circle"),
    ))
    fig.add_trace(go.Scatter(
        x=pozo1["date"],
        y=pozo1["nivel_dinamico_m"],
        mode="lines+markers",
        name="N. Dinámico observado",
        line=dict(color="#E67E22", width=2, dash="dot"),
        marker=dict(size=8, symbol="diamond"),
    ))

    # 30-day forecast from the last observation
    if not pozo1.empty:
        last = pozo1.iloc[-1]
        h0 = float(last["nivel_estatico_m"])

        try:
            local = open_meteo.fetch_forecast(-6.91, -79.51, days=14)
            up = andes_rainfall.fetch_upper_basin_forecast(days=14)
            up["recharge_proxy_mm"] = andes_rainfall.recharge_proxy(
                up["andes_precip_mm"]
            )
            df = local.merge(up[["date", "recharge_proxy_mm"]], on="date", how="left")
            df["recharge_proxy_mm"] = df["recharge_proxy_mm"].fillna(0)
            df["local_rainfall_mm"] = df["precip_mm"]
            df["extraction_l"] = 45000
            df["oni_anom"] = oni_anom
            df = df[["date", "recharge_proxy_mm", "local_rainfall_mm",
                     "extraction_l", "oni_anom", "et0_mm"]]

            fc = forecast_with_uncertainty(
                h0_m=h0,
                drivers=df,
                params=params,
                residual_std_m=residual_std_m,
            )
            fc["date"] = pd.to_datetime(fc["date"])
            days_to_critical = days_until_critical(fc, threshold_m=2.0)

            forecast_label = (
                "Pronóstico 14d (modelo calibrado)"
                if calibrated
                else "Pronóstico 14d (modelo sin calibrar)"
            )
            fig.add_trace(go.Scatter(
                x=fc["date"],
                y=fc["nivel_predicho_m"],
                mode="lines",
                name=forecast_label,
                line=dict(color="#00897B", width=3, dash="dash"),
            ))

            band_label = "Banda 95% (LOO-CV)" if calibrated else "Banda de incertidumbre"
            fig.add_trace(go.Scatter(
                x=fc["date"].tolist() + fc["date"].tolist()[::-1],
                y=fc["nivel_predicho_high_m"].tolist()
                + fc["nivel_predicho_low_m"].tolist()[::-1],
                fill="toself",
                fillcolor="rgba(0, 137, 123, 0.15)",
                line=dict(color="rgba(255,255,255,0)"),
                name=band_label,
                hoverinfo="skip",
            ))
        except Exception as e:  # noqa: BLE001
            fig.add_annotation(
                text=f"Pronóstico no disponible ({type(e).__name__})",
                xref="paper", yref="paper", x=0.5, y=0.5,
                showarrow=False, font=dict(size=12, color="#E74C3C"),
            )

    fig.update_layout(
        margin={"r": 10, "t": 10, "l": 50, "b": 30},
        paper_bgcolor="white",
        plot_bgcolor="white",
        legend={"orientation": "h", "y": 1.12, "x": 0},
        xaxis={"showgrid": True, "gridcolor": "#EAECEE", "title": ""},
        yaxis={"showgrid": True, "gridcolor": "#EAECEE",
               "title": "Columna de agua (m)"},
        font={"family": "Inter, sans-serif", "size": 11},
        hovermode="x unified",
    )
    return fig, days_to_critical


def _build_distribution_panel(d: dict) -> html.Div:
    op_yield = d.get("operational_sustainable_yield_l_per_day",
                     d.get("combined_sustainable_yield_l_per_day", 0))
    op_headroom = d.get("operational_headroom_pct", d.get("headroom_pct", 0))
    extraction = d["current_total_extraction_l_per_day"]
    return html.Div([
        dbc.Row([
            _info_pill("⚡ Bombeo", "Solar"),
            _info_pill("📦 Almacenamiento", f"{d['storage']['total_storage_l']:,} L"),
            _info_pill("🚰 Tubería principal",
                      f"{d['distribution']['main_pipe_length_m']} m × {d['distribution']['main_pipe_diameter_in']}\" HDPE"),
            _info_pill("💧 Riego", "Tecnificado (goteo)"),
        ], className="g-2", style={"marginBottom": "8px"}),

        html.Hr(style={"margin": "8px 0"}),

        html.Div([
            html.Span("Servicio: ", style={"fontWeight": "600", "fontSize": "0.85rem"}),
            html.Span(
                f"{d['irrigation']['served_units']['huertos']} huertos + "
                f"{d['irrigation']['served_units']['maracuya_plants']:,} plantas de maracuyá + vivienda",
                style={"fontSize": "0.85rem", "color": "#2C3E50"}
            ),
        ], style={"marginBottom": "4px"}),
        html.Div([
            html.Span("Capacidad operativa (sólo Pozo 1): ",
                      style={"fontWeight": "600", "fontSize": "0.85rem"}),
            html.Span(
                f"{op_yield:,} L/día — uso actual "
                f"{extraction:,} L/día "
                f"({max(0, 100 - op_headroom)}% utilización, {op_headroom}% headroom)",
                style={"fontSize": "0.85rem", "color": "#2C3E50"}
            ),
        ], style={"marginBottom": "4px"}),
        html.Div([
            html.Span(
                "⚠ Pozo 2 fuera de servicio — capacidad combinada subiría a "
                f"{d.get('combined_sustainable_yield_l_per_day_if_pozo2_repaired', 0):,} L/día tras reparación.",
                style={"fontSize": "0.78rem", "color": "#E67E22",
                       "fontStyle": "italic"},
            ),
        ]),
    ])


def _info_pill(label: str, value: str) -> dbc.Col:
    return dbc.Col(
        html.Div(
            [
                html.Div(label, style={"fontSize": "0.72rem",
                                       "color": "#7F8C8D"}),
                html.Div(value, style={"fontSize": "0.92rem",
                                       "fontWeight": "600",
                                       "color": "#1A2744"}),
            ],
            style={"backgroundColor": "#F4F6F7",
                   "padding": "8px 10px",
                   "borderRadius": "6px",
                   "borderLeft": "3px solid #00897B"},
        ),
        md=6,
        lg=3,
    )


def _build_ai_summary(
    oni_anom: float,
    enso_state: str,
    last_static_m: float,
    last_date: pd.Timestamp,
    days_to_critical: int | None,
    cal_meta: dict,
) -> html.Div:
    state_label = {
        "el_nino": "El Niño activo",
        "la_nina": "La Niña activa",
        "neutral": "Neutral",
    }.get(enso_state, "—")

    if days_to_critical is None:
        risk_text = "sin alerta de cruce de umbral en 14 días."
        risk_color = "#27AE60"
    elif days_to_critical >= 7:
        risk_text = f"cruce previsto del umbral 2.0 m en {days_to_critical} días."
        risk_color = "#E67E22"
    else:
        risk_text = f"⚠ cruce inminente del umbral 2.0 m en {days_to_critical} días."
        risk_color = "#E74C3C"

    if cal_meta.get("calibrated"):
        cal_line = (
            f"Modelo calibrado por LOO-CV (n=5): "
            f"RMSE {cal_meta.get('loo_rmse_m', 0):.2f} m, "
            f"banda 95% basada en σ residual {cal_meta.get('loo_residual_std_m', 0):.2f} m."
        )
    else:
        cal_line = "Modelo aún no calibrado — usando valores placeholder de Phase 1."

    return html.Div([
        html.P(
            html.Span([
                "Estado actual: ",
                html.Strong(risk_text, style={"color": risk_color}),
                f" Última medición {last_date.strftime('%b %Y')}: columna estática "
                f"{last_static_m:.1f} m. ENSO en estado ",
                html.Strong(state_label),
                f" (ONI {oni_anom:+.2f}). ",
                "Capacidad de bombas usada al 47%.",
            ]),
            style={"fontSize": "0.85rem", "lineHeight": "1.5",
                   "color": "#2C3E50", "marginBottom": "8px"},
        ),
        html.P(
            cal_line,
            style={"fontSize": "0.75rem", "color": "#5D6D7E",
                   "marginBottom": "4px", "fontStyle": "italic"},
        ),
        html.P(
            html.Em("Narrativa generada con LLM (Claude Haiku) — pendiente Phase 4."),
            style={"fontSize": "0.72rem", "color": "#7F8C8D",
                   "marginBottom": "0"},
        ),
    ])


def register_pozos_callbacks(app):

    @app.callback(
        Output("pozos-map", "figure"),
        Output("pozos-forecast-chart", "figure"),
        Output("pozos-enso", "children"),
        Output("pozos-enso-subtitle", "children"),
        Output("pozos-distribution-info", "children"),
        Output("pozos-ai-summary", "children"),
        Input("auto-refresh", "n_intervals"),
    )
    def refresh_pozos(_n):
        wells = _load_wells()
        distribution = _load_distribution()
        history = _load_history()
        params, cal_meta = _load_calibrated_params()
        residual_std_m = float(cal_meta.get("loo_residual_std_m", 0.15))

        # ENSO state
        try:
            _, anom, state = noaa_oni.latest_state()
        except Exception:
            anom, state = 0.0, "neutral"
        state_label = {
            "el_nino": "El Niño",
            "la_nina": "La Niña",
            "neutral": "Neutral",
        }.get(state, "—")

        # Map + forecast
        map_fig = _build_well_map(wells)
        forecast_fig, days_to_critical = _build_forecast_chart(
            history,
            oni_anom=anom,
            params=params,
            residual_std_m=residual_std_m,
            calibrated=cal_meta.get("calibrated", False),
        )

        # Cards
        distribution_panel = _build_distribution_panel(distribution)

        last_row = (
            history[history["well_id"] == "pozo1_asr"]
            .sort_values("date").iloc[-1]
        ) if not history.empty else None
        last_static = float(last_row["nivel_estatico_m"]) if last_row is not None else 0.0
        last_date = last_row["date"] if last_row is not None else pd.Timestamp.now()

        ai_summary = _build_ai_summary(
            anom, state, last_static, last_date, days_to_critical, cal_meta,
        )

        return (map_fig, forecast_fig,
                state_label, f"ONI {anom:+.2f}",
                distribution_panel, ai_summary)
