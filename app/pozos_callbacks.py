"""
Callbacks for the Pozos tab.

For v0 we fetch live ENSO/weather data on the auto-refresh tick (every 5 min).
The forecast uses placeholder coefficients in src.water_balance until Phase 3
calibrates them against the 5 NGO measurements.
"""
import json
import logging
import sys
import traceback
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, dcc, html, no_update
import dash_bootstrap_components as dbc
from flask import session

sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from src.crop_stress import (
    crop_label_es,
    crop_stress_forecast,
    reason_label_es,
)
from src.data_sources import open_meteo, noaa_oni, andes_rainfall, news_enso, imarpe_icen
from src.water_balance import (
    PUMP_CAPACITY_L_PER_DAY,
    WaterBalanceParams,
    cross_probability,
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
    backup_lats, backup_lons, backup_names, backup_hover = [], [], [], []

    for f in wells["features"]:
        coords = f["geometry"]["coordinates"]
        p = f["properties"]
        status = p.get("status")
        is_backup = status == "respaldo"
        lon, lat = coords[0], coords[1]
        sustainable = p.get("sustainable_yield_l_per_day", "—")
        depth = p.get("drilled_depth_m", "—")
        pump = p.get("operational_pump_model", "—")
        status_note = (
            "<br><b style='color:#E67E22'>🟠 RESPALDO (no operativo)</b>"
            if is_backup else ""
        )
        hover_text = (
            f"<b>{p['name']}</b>{status_note}<br>"
            f"Profundidad: {depth} m<br>"
            f"Bomba: {pump}<br>"
            f"Yield sostenible: {sustainable:,} L/día"
            if isinstance(sustainable, int)
            else f"<b>{p['name']}</b>{status_note}<br>"
                 f"Profundidad: {depth} m<br>Bomba: {pump}"
        )

        if is_backup:
            backup_lats.append(lat); backup_lons.append(lon)
            backup_names.append(p["name"] + " (respaldo)")
            backup_hover.append(hover_text)
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

    if backup_lats:
        fig.add_trace(go.Scattermap(
            lon=backup_lons, lat=backup_lats,
            mode="markers+text",
            marker=dict(size=24, color="#E67E22", opacity=0.85,
                        symbol="circle"),
            text=backup_names, textposition="top right",
            textfont=dict(size=11, color="#1A2744"),
            hoverinfo="text", hovertext=backup_hover, showlegend=False,
        ))

    fig.update_layout(
        map_style="open-street-map",
        map_zoom=10.5,
        map_center={"lat": -6.85, "lon": -79.40},
        margin={"r": 0, "t": 0, "l": 0, "b": 0},
        paper_bgcolor="white",
    )
    return fig


def _run_ensemble_forecast(
    h0_m: float, oni_anom: float, params: WaterBalanceParams
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build 35-day ensemble forecast: real GFS-GEFS members through the
    water-balance model. Returns (percentile_df, matrix) where matrix is the
    raw (date × member) trajectories — needed for `cross_probability`.
    """
    precip_df, et0_df = open_meteo.fetch_ensemble_forecast(config.SAYARIY_LAT, config.SAYARIY_LON, days=35)
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
            "extraction_l": 50000,
            "oni_anom": oni_anom,
        })
        drivers_list.append(df)

    return forecast_ensemble(h0_m=h0_m, drivers_per_member=drivers_list,
                             params=params, return_matrix=True)


def _run_seasonal_extension(h0_after_ensemble: float, start_date: date,
                            params: WaterBalanceParams,
                            oni_anom: float) -> pd.DataFrame | None:
    """Extend the forecast another 55 days using ENSO-conditional climatology
    on Andes recharge and local rainfall + ET₀.
    """
    try:
        end = date.today() - timedelta(days=2)
        start = date(2000, 1, 1)
        local_archive = open_meteo.fetch_historical(config.SAYARIY_LAT, config.SAYARIY_LON, start, end)
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
                "extraction_l": 50000,
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
) -> tuple[go.Figure, int | None, dict[int, float]]:
    """Returns (figure, days_until_critical, crossing_probabilities).

    crossing_probabilities: {horizon_days: probability} for 7, 14, 28 days,
    computed from the raw 30-member ensemble (not the median).
    """
    pozo1 = history[history["well_id"] == "pozo1_asr"].sort_values("date")

    fig = go.Figure()
    days_to_critical: int | None = None
    crossing_probs: dict[int, float] = {}

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
            ensemble_df, ensemble_matrix = _run_ensemble_forecast(h0, oni_anom, params)
            ensemble_df["date"] = pd.to_datetime(ensemble_df["date"])
            days_to_critical = days_until_critical(ensemble_df, threshold_m=2.0,
                                                    column="nivel_p50_m")
            for horizon in (7, 14, 28):
                crossing_probs[horizon] = cross_probability(
                    ensemble_matrix, threshold_m=2.0, horizon_days=horizon)

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
    return fig, days_to_critical, crossing_probs


def _build_distribution_panel(d: dict) -> html.Div:
    op_yield = d.get("operational_sustainable_yield_l_per_day", 0)
    extraction = d["current_total_extraction_l_per_day"]
    household = d.get("current_household_l_per_day", 0)
    crop_normal = d.get("current_crop_l_per_day_normal_season", 0)
    crop_high = d.get("current_crop_l_per_day_high_season", 0)
    backup_combined = d.get("combined_sustainable_yield_l_per_day_if_pozo2_active", 0)
    return html.Div([
        dbc.Row([
            _info_pill("⚡ Bombeo", "Solar 2\""),
            _info_pill("📦 Almacenamiento", f"{d['storage']['total_storage_l']:,} L"),
            _info_pill("🚰 Tubería principal",
                      f"{d['distribution']['main_pipe_length_m']} m × {d['distribution']['main_pipe_diameter_in']}\" HDPE"),
            _info_pill("💧 Riego", "Tecnificado (goteo)"),
        ], className="g-2", style={"marginBottom": "8px"}),

        html.Hr(style={"margin": "8px 0"}),

        html.Div([
            html.Span("Servicio: ", style={"fontWeight": "600", "fontSize": "0.85rem"}),
            html.Span(
                f"{d['irrigation']['served_units']['huertos']} huertos (10 ha) + "
                f"{d['irrigation']['served_units']['maracuya_plants']:,} plantas de maracuyá (3 ha) + viviendas",
                style={"fontSize": "0.85rem", "color": "#2C3E50"}
            ),
        ], style={"marginBottom": "4px"}),
        html.Div([
            html.Span("Bombeo Pozo 1: ",
                      style={"fontWeight": "600", "fontSize": "0.85rem"}),
            html.Span(
                f"{extraction:,} L/día (~4 h, solar). Tope físico ≈ {op_yield:,} L/día.",
                style={"fontSize": "0.85rem", "color": "#2C3E50"}
            ),
        ], style={"marginBottom": "4px"}),
        html.Div([
            html.Span("Reparto: ",
                      style={"fontWeight": "600", "fontSize": "0.85rem"}),
            html.Span(
                f"viviendas {household:,} L/día · cultivos {crop_normal:,} L/día (May-Sep) → {crop_high:,} L/día (Oct-Abr)",
                style={"fontSize": "0.85rem", "color": "#2C3E50"}
            ),
        ], style={"marginBottom": "4px"}),
        html.Div([
            html.Span(
                f"🟠 Pozo 2 en respaldo — la NGO lo activa si el Pozo 1 falla. "
                f"Capacidad combinada con Pozo 2 activo ≈ {backup_combined:,} L/día.",
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
    pct: float | None = None,
    drought: dict | None = None,
    freshness_label: str | None = None,
    freshness_color: str | None = None,
    crossing_probs: dict[int, float] | None = None,
    icen_anom: float = 0.0,
    icen_state: str = "neutral",
) -> html.Div:
    state_label = {
        "el_nino": "El Niño activo",
        "la_nina": "La Niña activa",
        "neutral": "Neutral",
    }.get(enso_state, "—")

    # Prefer the ensemble probability framing when available — more honest
    # than a single median-line "X days" answer for the NGO.
    if crossing_probs:
        p14 = crossing_probs.get(14, 0.0) * 100
        if p14 < 10:
            risk_text = f"probabilidad baja de cruzar 2,0 m en 2 semanas ({p14:.0f}%)."
            risk_color = "#27AE60"
        elif p14 < 40:
            risk_text = f"probabilidad moderada de cruzar 2,0 m en 2 semanas ({p14:.0f}%)."
            risk_color = "#E67E22"
        else:
            risk_text = f"⚠ probabilidad alta de cruzar 2,0 m en 2 semanas ({p14:.0f}%)."
            risk_color = "#E74C3C"
    elif days_to_critical is None:
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

    pct_segment = (
        f" Capacidad del pozo: {pct:.0f}% ({last_static_m:.1f} m de 3,5 m). "
        if pct is not None else
        f" Columna estática: {last_static_m:.1f} m. "
    )
    return html.Div([
        html.P(
            html.Span([
                "Estado actual: ",
                html.Strong(risk_text, style={"color": risk_color}),
                f" Última medición {last_date.strftime('%b %Y')}.",
                pct_segment,
                "ENSO costero: ",
                html.Strong(imarpe_icen.icen_label_es(icen_state)),
                f" (ICEN {icen_anom:+.2f} · ONI global {oni_anom:+.2f}). ",
                imarpe_icen.icen_risk_es(icen_state) + " ",
                "Pozo 1 al 100% de capacidad de bombeo (~50.000 L/día); Pozo 2 en respaldo.",
            ]),
            style={"fontSize": "0.85rem", "lineHeight": "1.5",
                   "color": "#2C3E50", "marginBottom": "8px"},
        ),
        html.P([
            html.Span("📉 Probabilidad de cruzar 2,0 m: ",
                      style={"fontSize": "0.78rem", "color": "#5D6D7E",
                             "fontWeight": "600"}),
            html.Span(
                " · ".join(f"{h//7} sem {(crossing_probs.get(h, 0)*100):.0f}%"
                           for h in (7, 14, 28)) + " (ensemble GFS-GEFS)",
                style={"fontSize": "0.78rem", "color": "#1A2744"},
            ),
        ], style={"marginBottom": "4px"}) if crossing_probs else html.Div(),
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
        html.P([
            html.Span("🛰️ Última actualización satelital: ",
                      style={"fontSize": "0.75rem", "color": "#7F8C8D"}),
            html.Strong(freshness_label or "—",
                        style={"fontSize": "0.78rem",
                               "color": freshness_color or "#7F8C8D"}),
        ], style={"marginBottom": "4px"}) if freshness_label else html.Div(),
        html.P(
            html.Em("Narrativa generada con LLM (Claude Haiku) — pendiente Phase 4."),
            style={"fontSize": "0.72rem", "color": "#7F8C8D",
                   "marginBottom": "0"},
        ),
    ])


# Pozo 1 reference levels for the % capacity computation. NGO 2026-05-05
# explicitly asked to see the well as "% de capacidad disponible" instead of
# raw meters. We anchor 100% to the schematic baseline static column (3.5 m,
# matches Alarcón 2021 + the first June 2022 NGO measurement) and 0% to the
# bottom of the operational range (the 2.0 m critical threshold used by
# `days_until_critical`).
POZO1_FULL_M = 3.5
POZO1_CRITICAL_M = 2.0


def _pct_capacity(static_m: float, full_m: float = POZO1_FULL_M,
                  critical_m: float = POZO1_CRITICAL_M) -> float:
    """Map a water-column height (m) to a 0-100 % capacity scale."""
    if full_m <= critical_m:
        return 0.0
    pct = (static_m - critical_m) / (full_m - critical_m) * 100.0
    return max(0.0, min(100.0, pct))


def _level_card_color(pct: float) -> str:
    if pct >= 60:
        return "#27AE60"
    if pct >= 30:
        return "#E67E22"
    return "#E74C3C"


PIPELINE_MARKER = ROOT / "data" / "processed" / ".last_pipeline_run.txt"


def pipeline_freshness() -> tuple[str, str]:
    """Return (label, color) describing how stale the data pipeline is.

    Reads the marker file written by the GitHub Action on each scheduled run.
    Falls back to the index_history.parquet mtime if the marker is missing
    (e.g. local dev where the action hasn't run).
    """
    try:
        if PIPELINE_MARKER.exists():
            ts = pd.Timestamp(PIPELINE_MARKER.read_text().strip())
        elif WELLS_HISTORY.with_name("index_history.parquet").exists():
            mtime = WELLS_HISTORY.with_name("index_history.parquet").stat().st_mtime
            ts = pd.Timestamp(mtime, unit="s", tz="UTC")
        else:
            return "sin datos", "#95A5A6"
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        age_hours = (pd.Timestamp.now(tz="UTC") - ts).total_seconds() / 3600
        if age_hours < 36:
            return f"hace {int(age_hours)} h", "#27AE60"
        days = int(age_hours / 24)
        if days < 7:
            return f"hace {days} d", "#E67E22"
        return f"hace {days} d", "#E74C3C"
    except Exception:
        return "desconocido", "#95A5A6"


# Heat-wave threshold confirmed by NGO 2026-05-05: "días que superan los 30 grados"
# require additional irrigation (40-45k L/day vs 30k baseline).
HEAT_THRESHOLD_C = 30.0
HEAT_HARMFUL_C = 35.0


def info_tooltip(target_id: str, title: str, what: str, how: str,
                 source: str) -> list:
    """Return [info-icon span, Tooltip] pair to be unpacked into a card header.

    Renders a small ℹ️ next to a card title. On hover, a Bootstrap tooltip
    explains: what the metric is, how it is computed, and the data source.
    """
    icon = html.Span(
        " ℹ️",
        id=target_id,
        style={"fontSize": "0.85rem", "cursor": "help",
               "color": "#7F8C8D", "marginLeft": "4px"},
    )
    tip = dbc.Tooltip(
        [
            html.Strong(title), html.Br(),
            html.Span("Qué mide: ", style={"fontWeight": "600"}),
            html.Span(what), html.Br(),
            html.Span("Cómo: ", style={"fontWeight": "600"}),
            html.Span(how), html.Br(),
            html.Span("Fuente: ", style={"fontWeight": "600"}),
            html.Span(source),
        ],
        target=target_id, placement="bottom",
        style={"maxWidth": "360px", "fontSize": "0.78rem",
               "textAlign": "left"},
    )
    return [icon, tip]


def _weather_emoji(precip_mm: float, prob_pct: float | None) -> str:
    p = prob_pct if prob_pct is not None else (50 if precip_mm > 0 else 0)
    if precip_mm >= 10 or p >= 70:
        return "🌧️"
    if precip_mm >= 2 or p >= 40:
        return "🌦️"
    if precip_mm >= 0.5 or p >= 20:
        return "⛅"
    return "☀️"


def _build_weather_card(local_lat: float = config.SAYARIY_LAT,
                        local_lon: float = config.SAYARIY_LON,
                        days: int = 14) -> tuple[html.Div, str, str]:
    """Unified weather forecast card — temperatura + lluvia + viento por día.
    Returns (body, badge_text, badge_color).
    """
    try:
        df = open_meteo.fetch_weather_forecast(local_lat, local_lon, days=days)
    except Exception as e:  # noqa: BLE001
        logger.error("weather card fetch failed: %s\n%s", e, traceback.format_exc())
        body = html.Div([
            html.P(
                f"Pronóstico de tiempo no disponible ahora mismo.",
                style={"fontSize": "0.85rem", "color": "#E67E22",
                       "fontWeight": "600", "marginBottom": "4px"},
            ),
            html.P(
                f"Detalle técnico: {type(e).__name__}: {str(e)[:140]}",
                style={"fontSize": "0.72rem", "color": "#7F8C8D",
                       "fontStyle": "italic", "marginBottom": "0"},
            ),
        ])
        return body, "Sin datos", "secondary"

    hot_days = int((df["tmax_c"] > HEAT_THRESHOLD_C).sum())
    harmful_days = int((df["tmax_c"] > HEAT_HARMFUL_C).sum())
    rainy_days = int((df["precip_mm"] >= 2).sum())
    rain_total = float(df["precip_mm"].sum())
    tmax_peak = float(df["tmax_c"].max())
    tmax_peak_date = df.loc[df["tmax_c"].idxmax(), "date"]

    if harmful_days > 0:
        badge_text, badge_color = f"⚠️ {harmful_days}d >35°C", "danger"
    elif hot_days >= 4:
        badge_text, badge_color = f"{hot_days} días calor", "warning"
    elif rain_total >= 20:
        badge_text, badge_color = f"💧 {rain_total:.0f} mm", "info"
    else:
        badge_text, badge_color = "Estable", "success"

    # Build a per-day stripe with rain emoji + tmax
    cells = []
    for _, row in df.iterrows():
        d = pd.to_datetime(row["date"])
        t = float(row["tmax_c"])
        precip = float(row["precip_mm"])
        prob = row.get("precip_prob_max_pct")
        emoji = _weather_emoji(precip, prob)
        if t > HEAT_HARMFUL_C:    bg = "#C0392B"; fg = "white"
        elif t > HEAT_THRESHOLD_C: bg = "#E67E22"; fg = "white"
        elif t > 28:               bg = "#F8C471"; fg = "#1A2744"
        else:                      bg = "#D5F5E3"; fg = "#1A2744"
        cells.append(html.Div(
            [
                html.Div(d.strftime("%a")[:3].upper(),
                         style={"fontSize": "0.65rem", "fontWeight": "700",
                                "color": fg, "marginBottom": "1px"}),
                html.Div(d.strftime("%d/%m"),
                         style={"fontSize": "0.65rem", "color": fg,
                                "opacity": "0.8", "marginBottom": "2px"}),
                html.Div(emoji,
                         style={"fontSize": "1.4rem", "lineHeight": "1",
                                "marginBottom": "2px"}),
                html.Div(f"{t:.0f}°",
                         style={"fontSize": "0.85rem", "fontWeight": "700",
                                "color": fg}),
                html.Div(
                    f"{precip:.0f} mm" if precip >= 0.5 else "—",
                    style={"fontSize": "0.65rem", "color": fg,
                           "opacity": "0.8"},
                ),
            ],
            title=(
                f"{d.strftime('%A %d/%m')}\n"
                f"tmax {t:.1f} °C, tmin {row['tmin_c']:.1f} °C\n"
                f"lluvia {precip:.1f} mm "
                f"({prob:.0f}% prob)" if prob is not None else
                f"{d.strftime('%A %d/%m')}\n"
                f"tmax {t:.1f} °C, tmin {row['tmin_c']:.1f} °C\n"
                f"lluvia {precip:.1f} mm"
            ),
            style={"backgroundColor": bg, "padding": "6px 4px",
                   "textAlign": "center", "flex": "1",
                   "borderRight": "1px solid white", "minWidth": "44px"},
        ))

    summary_pieces = []
    if harmful_days > 0:
        summary_pieces.append(
            html.Span(f"🔥 {harmful_days} d >35 °C — riesgo de daño foliar.  ",
                      style={"color": "#C0392B", "fontWeight": "600"}))
    if hot_days > 0:
        summary_pieces.append(
            html.Span(f"🌡️ {hot_days} d >30 °C — riego reforzado.  ",
                      style={"color": "#E67E22", "fontWeight": "600"}))
    if rainy_days > 0:
        summary_pieces.append(
            html.Span(
                f"💧 {rainy_days} d con lluvia (~{rain_total:.0f} mm acum.).",
                style={"color": "#2874A6", "fontWeight": "600"}))
    if not summary_pieces:
        summary_pieces.append(
            html.Span("Tiempo estable, sin lluvia ni calor extremo previstos.",
                      style={"color": "#27AE60", "fontWeight": "600"}))

    body = html.Div([
        html.P(summary_pieces,
               style={"fontSize": "0.85rem", "marginBottom": "6px"}),
        html.P(
            f"Pico de calor previsto: {tmax_peak:.1f} °C el {tmax_peak_date.strftime('%d/%m')}. "
            f"Total de lluvia 14 d: ~{rain_total:.0f} mm.",
            style={"fontSize": "0.78rem", "color": "#5D6D7E",
                   "marginBottom": "8px"},
        ),
        html.Div(cells,
                 style={"display": "flex", "borderRadius": "4px",
                        "overflow": "hidden", "marginBottom": "4px",
                        "border": "1px solid #ECF0F1"}),
        html.P("tmax °C + lluvia diaria (Open-Meteo, GFS-GEFS para los siguientes 14 días)",
               style={"fontSize": "0.7rem", "color": "#95A5A6",
                      "fontStyle": "italic", "marginBottom": "0"}),
    ])
    return body, badge_text, badge_color


# Backwards-compatible alias — the layout still calls _build_heat_card.
_build_heat_card = _build_weather_card


def _build_crop_stress_card(days: int = 16) -> tuple[html.Div, str, str]:
    """Per-crop stress forecast for the next 16 days (Open-Meteo cap).
    Returns (body, badge_text, badge_color).
    """
    try:
        temp = open_meteo.fetch_temperature_forecast(
            config.SAYARIY_LAT, config.SAYARIY_LON, days=days)
        weather = open_meteo.fetch_forecast(
            config.SAYARIY_LAT, config.SAYARIY_LON, days=days)
        fc = temp.merge(weather[["date", "et0_mm"]], on="date", how="inner")
        per_day, summaries = crop_stress_forecast(fc)
    except Exception as e:  # noqa: BLE001
        body = html.Div(
            f"Pronóstico de estrés no disponible ({type(e).__name__}).",
            style={"fontSize": "0.85rem", "color": "#7F8C8D",
                   "fontStyle": "italic"},
        )
        return body, "—", "secondary"

    n_supply = int(per_day["supply_stress"].sum())
    n_heat = int(per_day["heat_day"].sum())
    n_harmful = int(per_day["heat_harmful"].sum())
    n_total = int(per_day["stress_day"].sum())
    avg_demand = float(per_day["total_demand_l"].mean())
    cap = float(per_day["crop_supply_cap_l"].iloc[0])
    util_pct = min(100, avg_demand / cap * 100)

    if n_harmful > 0 or n_total >= 5:
        badge_text, badge_color, headline_color = f"{n_total} días estrés", "danger", "#E74C3C"
    elif n_total > 0:
        badge_text, badge_color, headline_color = f"{n_total} días", "warning", "#E67E22"
    else:
        badge_text, badge_color, headline_color = "Sin alerta", "success", "#27AE60"

    headline_bits = []
    if n_total == 0:
        headline_bits.append(f"Sin estrés esperado en los próximos {days} días.")
    else:
        headline_bits.append(f"{n_total} día(s) con riesgo en los próximos {days}.")
    headline_bits.append(
        f"Bombeo cubre {util_pct:.0f}% de la demanda media de cultivos."
    )

    table_rows = [html.Tr([
        html.Th("Cultivo", style={"fontSize": "0.78rem", "color": "#7F8C8D",
                                  "fontWeight": "600", "padding": "4px 8px"}),
        html.Th("L/día", style={"fontSize": "0.78rem", "color": "#7F8C8D",
                                "fontWeight": "600", "padding": "4px 8px",
                                "textAlign": "right"}),
        html.Th("Días estrés", style={"fontSize": "0.78rem", "color": "#7F8C8D",
                                      "fontWeight": "600", "padding": "4px 8px",
                                      "textAlign": "right"}),
        html.Th("Pico", style={"fontSize": "0.78rem", "color": "#7F8C8D",
                               "fontWeight": "600", "padding": "4px 8px"}),
    ])]
    for s in summaries[:8]:
        if s.avg_daily_demand_l < 50:  # skip negligible crops
            continue
        peak_text = (
            f"{s.peak_stress_date.strftime('%d/%m')} · {reason_label_es(s.peak_stress_reason)}"
            if s.peak_stress_date is not None else "—"
        )
        stress_color = "#E74C3C" if s.stress_days > 0 else "#5D6D7E"
        table_rows.append(html.Tr([
            html.Td(crop_label_es(s.crop),
                    style={"fontSize": "0.82rem", "color": "#1A2744",
                           "padding": "4px 8px", "fontWeight": "500"}),
            html.Td(f"{s.avg_daily_demand_l:,.0f}",
                    style={"fontSize": "0.82rem", "color": "#5D6D7E",
                           "padding": "4px 8px", "textAlign": "right"}),
            html.Td(str(s.stress_days),
                    style={"fontSize": "0.82rem", "color": stress_color,
                           "padding": "4px 8px", "textAlign": "right",
                           "fontWeight": "600"}),
            html.Td(peak_text,
                    style={"fontSize": "0.78rem", "color": "#5D6D7E",
                           "padding": "4px 8px"}),
        ]))

    body = html.Div([
        html.P(" ".join(headline_bits),
               style={"fontSize": "0.85rem", "color": headline_color,
                      "fontWeight": "600", "marginBottom": "8px"}),
        html.Div([
            html.Span(f"🌡️ {n_heat} días >30°C  ",
                      style={"fontSize": "0.78rem", "color": "#E67E22"}),
            html.Span(f"🔥 {n_harmful} días >35°C  ",
                      style={"fontSize": "0.78rem", "color": "#C0392B"}),
            html.Span(f"💧 {n_supply} días tope de bombeo",
                      style={"fontSize": "0.78rem", "color": "#2874A6"}),
        ], style={"marginBottom": "8px"}),
        html.Table(
            table_rows,
            style={"width": "100%", "borderCollapse": "collapse",
                   "marginBottom": "4px"},
        ),
        html.P(
            "Demanda = Kc × ET₀ × área-mojada × plantas, con multiplicador estacional NGO. "
            "Estrés = déficit >20% O calor >35°C.",
            style={"fontSize": "0.7rem", "color": "#95A5A6",
                   "fontStyle": "italic", "marginBottom": "0"},
        ),
    ])
    return body, badge_text, badge_color


def _build_news_card(max_items: int = 3) -> html.Div:
    items = news_enso.fetch_enso_news(max_items=max_items)
    if not items:
        return html.Div(
            "No hay noticias recientes disponibles (red o RSS sin respuesta).",
            style={"fontSize": "0.85rem", "color": "#7F8C8D",
                   "fontStyle": "italic", "padding": "8px 0"},
        )
    rows = []
    for it in items:
        rows.append(html.Div(
            [
                html.Div([
                    html.Span(it.source,
                              style={"fontWeight": "700", "fontSize": "0.78rem",
                                     "color": "#2874A6"}),
                    html.Span(f" · {it.published_es()}",
                              style={"fontSize": "0.75rem", "color": "#7F8C8D"}),
                ], style={"marginBottom": "2px"}),
                html.A(
                    it.title,
                    href=it.url, target="_blank", rel="noopener",
                    style={"fontSize": "0.88rem", "color": "#1A2744",
                           "fontWeight": "600", "textDecoration": "none",
                           "display": "block", "marginBottom": "2px"},
                ),
                html.Div(
                    it.snippet,
                    style={"fontSize": "0.78rem", "color": "#566D7E",
                           "lineHeight": "1.35"},
                ) if it.snippet else html.Div(),
            ],
            style={"padding": "8px 0", "borderBottom": "1px solid #ECF0F1"},
        ))
    rows[-1].style["borderBottom"] = "none"
    return html.Div(rows)


def _validate_measurement(well_id, date_str, static_m, dynamic_m,
                          flow_lpm, notes) -> dict:
    if not well_id:
        raise ValueError("Seleccione un pozo.")
    if not date_str:
        raise ValueError("Seleccione la fecha de la medición.")
    if static_m is None or dynamic_m is None:
        raise ValueError("Ingrese ambos niveles (estático y dinámico).")
    static_m = float(static_m)
    dynamic_m = float(dynamic_m)
    if not (0 <= static_m <= 20):
        raise ValueError("Nivel estático fuera de rango razonable (0-20 m).")
    if not (0 <= dynamic_m <= 20):
        raise ValueError("Nivel dinámico fuera de rango razonable (0-20 m).")
    if dynamic_m > static_m:
        raise ValueError("El nivel dinámico no puede superar al estático.")
    return {
        "date": pd.to_datetime(date_str).date(),
        "well_id": well_id,
        "nivel_estatico_m": static_m,
        "nivel_dinamico_m": dynamic_m,
        "caudal_lpm": float(flow_lpm) if flow_lpm is not None else None,
        "notes": (notes or "").strip(),
    }


def _append_measurement(row: dict) -> None:
    """Append a manual measurement to wells_history.parquet.
    Persistence is local-only — on Render the container disk is ephemeral, so
    the row survives until the next deploy. NGO acknowledged this is fine for
    the demo; production would push to a managed store.
    """
    cols_full = [
        "date", "well_id",
        "nivel_estatico_m", "nivel_dinamico_m",
        "nivel_predicho_m", "nivel_predicho_low_m", "nivel_predicho_high_m",
        "is_forecast", "is_post_maintenance",
        "extraction_l_per_day", "crop_demand_l_per_day",
        "recharge_proxy_mm", "local_rainfall_mm", "et0_mm",
        "oni_anom", "enso_state",
        "model_version", "source", "notes",
    ]
    new_row = {c: pd.NA for c in cols_full}
    new_row.update({
        "date": row["date"],
        "well_id": row["well_id"],
        "nivel_estatico_m": row["nivel_estatico_m"],
        "nivel_dinamico_m": row["nivel_dinamico_m"],
        "is_forecast": False,
        "is_post_maintenance": False,
        "source": "dashboard_manual_entry",
        "notes": row["notes"] or None,
    })
    new_df = pd.DataFrame([new_row])[cols_full]
    if WELLS_HISTORY.exists():
        existing = pd.read_parquet(WELLS_HISTORY)
        out = pd.concat([existing, new_df], ignore_index=True)
    else:
        out = new_df
    out = out.sort_values(["well_id", "date"]).reset_index(drop=True)
    WELLS_HISTORY.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(WELLS_HISTORY, index=False)


def _feedback(msg: str, ok: bool) -> html.Span:
    color = "#27AE60" if ok else "#E74C3C"
    icon = "✅" if ok else "⚠️"
    return html.Span(f"{icon} {msg}", style={"color": color, "fontWeight": "600"})


def _trigger_recalibration() -> bool:
    """Fire-and-forget recalibration in a background subprocess.

    Uses --no-fetch so it runs against the cached drivers parquet (no CDSE/
    Open-Meteo network calls). Typical runtime ~30s. Output goes to a log
    file so we can debug post-hoc without blocking the dashboard.
    Returns True if the subprocess was spawned successfully.
    """
    import subprocess
    log_path = ROOT / "data" / "processed" / ".last_recalibration.log"
    lock_path = ROOT / "data" / "processed" / ".recalibration.lock"
    if lock_path.exists():
        # Don't pile up concurrent runs. Stale lock is auto-cleared after 5 min.
        age = pd.Timestamp.now().timestamp() - lock_path.stat().st_mtime
        if age < 300:
            return False
    try:
        lock_path.touch()
        log_f = open(log_path, "w")
        proc = subprocess.Popen(
            [sys.executable, str(ROOT / "scripts" / "calibrate_water_balance.py"),
             "--no-fetch"],
            stdout=log_f, stderr=subprocess.STDOUT,
            cwd=str(ROOT),
            start_new_session=True,
        )
        # Schedule lock cleanup. Daemon thread so it doesn't block shutdown.
        import threading

        def _cleanup():
            proc.wait()
            try:
                lock_path.unlink(missing_ok=True)
            except Exception:
                pass

        threading.Thread(target=_cleanup, daemon=True).start()
        return True
    except Exception:
        try:
            lock_path.unlink(missing_ok=True)
        except Exception:
            pass
        return False


def register_pozos_callbacks(app):

    @app.callback(
        Output("pozos-map", "figure"),
        Output("pozos-forecast-chart", "figure"),
        Output("pozos-enso", "children"),
        Output("pozos-enso-subtitle", "children"),
        Output("pozos-well-level", "children"),
        Output("pozos-well-level-subtitle", "children"),
        Output("pozos-well-level", "style"),
        Output("heat-card-body", "children"),
        Output("heat-badge", "children"),
        Output("heat-badge", "color"),
        Output("news-card-body", "children"),
        Output("crop-stress-card-body", "children"),
        Output("crop-stress-badge", "children"),
        Output("crop-stress-badge", "color"),
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

        # ENSO state — fetch global ONI and Peru coastal ICEN
        try:
            _, anom, state = noaa_oni.latest_state()
        except Exception:
            anom, state = 0.0, "neutral"
        try:
            _, icen_anom, icen_state = imarpe_icen.latest_icen()
        except Exception:
            icen_anom, icen_state = 0.0, "neutral"
        # ICEN card: show coastal label prominently; ONI as reference in subtitle
        state_label = imarpe_icen.icen_label_es(icen_state)

        # Map + forecast
        map_fig = _build_well_map(wells)
        forecast_fig, days_to_critical, crossing_probs = _build_forecast_chart(
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

        # Well level as % capacity (NGO ask, 2026-05-05)
        pct = _pct_capacity(last_static)
        level_color = _level_card_color(pct)
        level_value = f"{pct:.0f}%"
        level_subtitle = f"{last_static:.1f} m de {POZO1_FULL_M:.1f} m"
        level_style = {"color": level_color, "margin": "0",
                       "fontWeight": "700", "fontSize": "1.6rem"}

        drought = _compute_drought_state()
        freshness_label, freshness_color = pipeline_freshness()
        ai_summary = _build_ai_summary(
            anom, state, last_static, last_date, days_to_critical, cal_meta,
            pct=pct, drought=drought,
            freshness_label=freshness_label, freshness_color=freshness_color,
            crossing_probs=crossing_probs,
            icen_anom=icen_anom, icen_state=icen_state,
        )

        heat_body, heat_badge, heat_color = _build_heat_card()
        news_body = _build_news_card()
        crop_body, crop_badge, crop_color = _build_crop_stress_card()

        return (map_fig, forecast_fig,
                state_label, f"ICEN {icen_anom:+.2f} · ONI {anom:+.2f}",
                level_value, level_subtitle, level_style,
                heat_body, heat_badge, heat_color,
                news_body,
                crop_body, crop_badge, crop_color,
                distribution_panel, ai_summary)

    @app.callback(
        Output("measurement-feedback", "children"),
        Output("measurement-static-m", "value"),
        Output("measurement-dynamic-m", "value"),
        Output("measurement-flow-lpm", "value"),
        Output("measurement-notes", "value"),
        Input("measurement-submit", "n_clicks"),
        State("measurement-well", "value"),
        State("measurement-date", "date"),
        State("measurement-static-m", "value"),
        State("measurement-dynamic-m", "value"),
        State("measurement-flow-lpm", "value"),
        State("measurement-notes", "value"),
        prevent_initial_call=True,
    )
    def submit_measurement(n_clicks, well_id, date_str, static_m, dynamic_m,
                           flow_lpm, notes):
        if not n_clicks:
            return no_update, no_update, no_update, no_update, no_update
        if not session.get("can_write"):
            return (
                _feedback("Inicie sesión con la contraseña NGO para registrar.",
                          ok=False),
                no_update, no_update, no_update, no_update,
            )
        try:
            row = _validate_measurement(well_id, date_str, static_m, dynamic_m,
                                        flow_lpm, notes)
        except ValueError as e:
            return _feedback(str(e), ok=False), no_update, no_update, no_update, no_update
        try:
            _append_measurement(row)
        except Exception as e:  # noqa: BLE001
            return _feedback(f"Error al guardar: {e}", ok=False), no_update, no_update, no_update, no_update
        recal_ok = _trigger_recalibration()
        recal_note = (
            "Recalibración del modelo en segundo plano (~30 s — recargue para ver los nuevos parámetros)."
            if recal_ok else
            "Recalibración omitida (otra ya en curso). Reintente en 1 minuto si necesita actualizar el modelo."
        )
        msg = (
            f"Guardado · {row['well_id']} · {row['date']}: "
            f"estático {row['nivel_estatico_m']:.2f} m, "
            f"dinámico {row['nivel_dinamico_m']:.2f} m. {recal_note}"
        )
        return _feedback(msg, ok=True), None, None, None, None

    @app.callback(
        Output("pozo-download", "data"),
        Input("pozo-download-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def download_pozo_history(_n_clicks):
        df = pd.read_parquet(WELLS_HISTORY)
        df = df[df["well_id"] == "pozo1_asr"]
        return dcc.send_data_frame(
            df.to_csv,
            filename=f"pozo1_historial_{date.today().strftime('%Y%m%d')}.csv",
            index=False,
        )
