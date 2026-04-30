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
    forecast_ensemble,
    forecast_with_uncertainty,
)
from src.drought import compute_spi, spi_band_es, spi_emoji
from src.seasonal import build_seasonal_extension


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


def _run_ensemble_forecast(h0_m: float, oni_anom: float,
                           params: WaterBalanceParams) -> pd.DataFrame:
    """Build 35-day ensemble forecast: real GFS-GEFS members through the
    water-balance model, returning P10/P50/P90 trajectories.
    """
    precip_df, et0_df = open_meteo.fetch_ensemble_forecast(-6.91, -79.51, days=35)
    andes_pr = andes_rainfall.fetch_upper_basin_ensemble_forecast(days=35)

    precip_members = sorted(c for c in precip_df.columns if c.startswith("member_"))
    et0_members = sorted(c for c in et0_df.columns if c.startswith("member_"))
    andes_members = sorted(c for c in andes_pr.columns if c.startswith("andes_member_"))

    # Coerce all member columns to numeric (ensemble can return None at horizon edge)
    for c in precip_members:
        precip_df[c] = pd.to_numeric(precip_df[c], errors="coerce").fillna(0)
    for c in et0_members:
        et0_df[c] = pd.to_numeric(et0_df[c], errors="coerce").fillna(4.5)
    for c in andes_members:
        andes_pr[c] = pd.to_numeric(andes_pr[c], errors="coerce").fillna(0)

    n = min(len(precip_members), len(et0_members), len(andes_members))
    drivers_list = []
    for i in range(n):
        df = pd.DataFrame({
            "date": precip_df["date"],
            "recharge_proxy_mm": andes_pr[andes_members[i]]
                .rolling(60, min_periods=1).sum().shift(14)
                .fillna(0).values[:len(precip_df)],
            "local_rainfall_mm": precip_df[precip_members[i]].values,
            "et0_mm": et0_df[et0_members[i]].values,
            "extraction_l": 45000,
            "oni_anom": oni_anom,
        })
        drivers_list.append(df)

    return forecast_ensemble(h0_m=h0_m, drivers_per_member=drivers_list, params=params)


def _run_seasonal_extension(h0_after_ensemble: float, start_date: date,
                            params: WaterBalanceParams,
                            oni_anom: float) -> pd.DataFrame | None:
    """Extend the forecast another 55 days using ENSO-conditional climatology
    on Andes recharge and local rainfall + ET₀.
    """
    try:
        end = date.today() - timedelta(days=2)
        start = date(2000, 1, 1)
        local_archive = open_meteo.fetch_historical(-6.91, -79.51, start, end)
        andes_archive = andes_rainfall.fetch_upper_basin_history(
            start, end, multipoint=False
        ).rename(columns={
            "andes_precip_mm": "precip_mm",
            "andes_et0_mm": "et0_mm",
        })

        local_seas = build_seasonal_extension(
            local_archive, start_date=start_date, days=55,
            current_oni=oni_anom,
        )
        andes_seas = build_seasonal_extension(
            andes_archive, start_date=start_date, days=55,
            current_oni=oni_anom,
        )

        # Build three trajectories (P10/P50/P90 driver  → P10/P50/P90 of H)
        traj = {}
        for tag, l_col, a_col in [
            ("p10", "p90_precip_mm", "p90_precip_mm"),  # wet driver = wet H
            ("p50", "p50_precip_mm", "p50_precip_mm"),
            ("p90", "p10_precip_mm", "p10_precip_mm"),  # dry driver = dry H
        ]:
            df = pd.DataFrame({
                "date": local_seas.df["date"],
                "local_rainfall_mm": local_seas.df[l_col].values,
                "et0_mm": local_seas.df[f"{tag}_et0_mm"].values
                    if f"{tag}_et0_mm" in local_seas.df.columns
                    else local_seas.df["p50_et0_mm"].values,
                "recharge_proxy_mm": andes_seas.df[a_col].rolling(60, min_periods=1)
                    .sum().shift(14).fillna(0).values,
                "extraction_l": 45000,
                "oni_anom": oni_anom,
            })
            from src.water_balance import forecast as _fc
            fc = _fc(h0_m=h0_after_ensemble, drivers=df, params=params)
            traj[tag] = fc.set_index("date")["nivel_predicho_m"]

        out = pd.DataFrame({
            "date": traj["p50"].index,
            "nivel_p10_m": traj["p10"].values,
            "nivel_p50_m": traj["p50"].values,
            "nivel_p90_m": traj["p90"].values,
        }).reset_index(drop=True)
        return out
    except Exception:
        return None


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

    # 35-day ensemble forecast from the last observation, extended to 90 days
    # via ENSO-conditional climatology
    if not pozo1.empty:
        last = pozo1.iloc[-1]
        h0 = float(last["nivel_estatico_m"])

        try:
            ensemble_df = _run_ensemble_forecast(h0, oni_anom, params)
            ensemble_df["date"] = pd.to_datetime(ensemble_df["date"])
            days_to_critical = days_until_critical(ensemble_df, threshold_m=2.0,
                                                    column="nivel_p50_m")

            # Median (P50) trajectory
            fig.add_trace(go.Scatter(
                x=ensemble_df["date"],
                y=ensemble_df["nivel_p50_m"],
                mode="lines",
                name="Pronóstico ensemble (mediana, GFS-GEFS 30 miembros)",
                line=dict(color="#00897B", width=3),
            ))

            # P10–P90 band (real ensemble spread)
            fig.add_trace(go.Scatter(
                x=ensemble_df["date"].tolist() + ensemble_df["date"].tolist()[::-1],
                y=ensemble_df["nivel_p90_m"].tolist()
                + ensemble_df["nivel_p10_m"].tolist()[::-1],
                fill="toself",
                fillcolor="rgba(0, 137, 123, 0.18)",
                line=dict(color="rgba(255,255,255,0)"),
                name="Banda P10–P90 (ensemble)",
                hoverinfo="skip",
            ))

            # Optional 90-day seasonal extension (climatology + ENSO)
            seasonal_ext = _run_seasonal_extension(
                h0_after_ensemble=float(ensemble_df.iloc[-1]["nivel_p50_m"]),
                start_date=ensemble_df.iloc[-1]["date"].date() + timedelta(days=1),
                params=params,
                oni_anom=oni_anom,
            )
            if seasonal_ext is not None and not seasonal_ext.empty:
                seasonal_ext["date"] = pd.to_datetime(seasonal_ext["date"])
                fig.add_trace(go.Scatter(
                    x=seasonal_ext["date"],
                    y=seasonal_ext["nivel_p50_m"],
                    mode="lines",
                    name="Extensión 90d (climatología + ENSO)",
                    line=dict(color="#7F8C8D", width=2, dash="dot"),
                ))
                fig.add_trace(go.Scatter(
                    x=seasonal_ext["date"].tolist() + seasonal_ext["date"].tolist()[::-1],
                    y=seasonal_ext["nivel_p90_m"].tolist()
                    + seasonal_ext["nivel_p10_m"].tolist()[::-1],
                    fill="toself",
                    fillcolor="rgba(127, 140, 141, 0.10)",
                    line=dict(color="rgba(255,255,255,0)"),
                    name="Banda estacional P10–P90",
                    hoverinfo="skip",
                ))

            # Critical-threshold reference line
            fig.add_hline(
                y=2.0, line_dash="dash", line_color="#E74C3C",
                line_width=1,
                annotation_text="umbral 2,0 m",
                annotation_position="bottom right",
                annotation_font_size=10,
                annotation_font_color="#E74C3C",
            )
        except Exception as e:  # noqa: BLE001
            fig.add_annotation(
                text=f"Pronóstico no disponible ({type(e).__name__}: {e})",
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


def _compute_drought_state() -> dict | None:
    """Live SPI-3 over the upper Zaña basin. Returns None on failure."""
    try:
        end = date.today() - timedelta(days=2)
        start = date(2000, 1, 1)
        df = andes_rainfall.fetch_upper_basin_history(start, end, multipoint=False)
        df = df.rename(columns={"andes_precip_mm": "precip_mm"})
        spi = compute_spi(df, end_date=end, window_months=3)
        return {
            "spi": spi.spi,
            "band": spi.band,
            "band_es": spi_band_es(spi.band),
            "emoji": spi_emoji(spi.spi),
            "accum_mm": spi.accumulation_mm,
            "climatology_mean_mm": spi.climatology_mean_mm,
            "n_years": spi.n_climatology_years,
        }
    except Exception:
        return None


def _build_ai_summary(
    oni_anom: float,
    enso_state: str,
    last_static_m: float,
    last_date: pd.Timestamp,
    days_to_critical: int | None,
    cal_meta: dict,
    drought: dict | None = None,
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
            f"Modelo calibrado por LOO-CV (n=5): RMSE "
            f"{cal_meta.get('loo_rmse_m', 0):.2f} m. "
            f"Pronóstico ensemble GFS-GEFS (~30 miembros, 35d) + extensión "
            f"climatológica condicionada por ENSO (días 36–90)."
        )
    else:
        cal_line = "Modelo aún no calibrado — usando valores placeholder de Phase 1."

    drought_line = None
    if drought is not None and drought.get("spi") is not None:
        spi_v = drought["spi"]
        if spi_v == spi_v:  # not NaN
            drought_line = (
                f"{drought['emoji']}  Cuenca alta del Zaña: SPI-3 = {spi_v:+.2f} "
                f"({drought['band_es']}). "
                f"Acumulado 3 meses: {drought['accum_mm']:.0f} mm vs. "
                f"climatología {drought['climatology_mean_mm']:.0f} mm "
                f"(n = {drought['n_years']} años)."
            )

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
            drought_line,
            style={"fontSize": "0.78rem", "color": "#1A2744",
                   "fontWeight": "600", "marginBottom": "4px"},
        ) if drought_line else html.Div(),
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

        drought = _compute_drought_state()
        ai_summary = _build_ai_summary(
            anom, state, last_static, last_date, days_to_critical, cal_meta,
            drought=drought,
        )

        return (map_fig, forecast_fig,
                state_label, f"ONI {anom:+.2f}",
                distribution_panel, ai_summary)
