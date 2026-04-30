"""
Vista Sencilla callbacks — translate the technical model output into plain-
language, emoji-driven status for non-technical users.

Reads the same live sources as Pozos (Open-Meteo + NOAA ONI + calibrated
water-balance) but reduces everything to:
  - one of three traffic-light states
  - a fill percentage
  - rain/sun emoji per day
  - a simple "Sí / No / Espere lluvia" recommendation
"""
import json
import sys
from pathlib import Path

import pandas as pd
from dash import Input, Output, html
import dash_bootstrap_components as dbc

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.data_sources import open_meteo, noaa_oni, andes_rainfall
from src.water_balance import (
    WaterBalanceParams,
    days_until_critical,
    forecast_with_uncertainty,
)


ROOT = Path(__file__).resolve().parent.parent
WELLS_HISTORY = ROOT / "data" / "processed" / "wells_history.parquet"
PARAMS_JSON = ROOT / "data" / "processed" / "water_balance_params.json"

# Pozo 1 baseline depth from schematic — used to convert water-column m -> %fill
EFFECTIVE_BOTTOM_DEPTH_M = 19.25  # PVC 20 m casing, 0.95 m internal gravel
HISTORICAL_MAX_STATIC_M = 3.5     # 2022 baseline static column

# Traffic-light thresholds on water column (m static)
THRESHOLD_GREEN_M = 2.4   # >= 2.4 m → verde
THRESHOLD_AMBER_M = 2.0   # 2.0-2.4 m → amarillo;  < 2.0 m → rojo


def _load_params():
    if not PARAMS_JSON.exists():
        return WaterBalanceParams(), 0.15, False
    payload = json.load(open(PARAMS_JSON))
    p = WaterBalanceParams(**payload["params"])
    sigma = float(payload["metadata"].get("loo_residual_std_m", 0.15))
    return p, sigma, True


def _load_history() -> pd.DataFrame:
    if not WELLS_HISTORY.exists():
        return pd.DataFrame()
    df = pd.read_parquet(WELLS_HISTORY)
    df["date"] = pd.to_datetime(df["date"])
    return df[df["well_id"] == "pozo1_asr"].sort_values("date").reset_index(drop=True)


def _traffic_light(static_m: float) -> tuple[str, str, str, str]:
    """Returns (color, emoji, headline, subline) for the current water level."""
    if static_m >= THRESHOLD_GREEN_M:
        return (
            "#27AE60",
            "🟢",
            "Hay agua suficiente",
            "Riegue normalmente. El pozo está en buen estado.",
        )
    if static_m >= THRESHOLD_AMBER_M:
        return (
            "#F39C12",
            "🟡",
            "Cuide el agua",
            "Riegue lo justo. Evite desperdicios. Vigile el pozo cada semana.",
        )
    return (
        "#E74C3C",
        "🔴",
        "Poca agua — racionar",
        "Reduzca el riego. Priorice las plantas más importantes.",
    )


def _build_status_hero(static_m: float, last_date: pd.Timestamp) -> html.Div:
    color, emoji, headline, subline = _traffic_light(static_m)
    return html.Div(
        style={"display": "flex", "alignItems": "center", "gap": "24px",
               "flexWrap": "wrap"},
        children=[
            html.Div(
                emoji,
                style={"fontSize": "5rem", "lineHeight": "1",
                       "filter": "drop-shadow(0 2px 4px rgba(0,0,0,0.15))"},
            ),
            html.Div(
                style={"flex": "1", "minWidth": "280px"},
                children=[
                    html.H2(
                        headline,
                        style={"color": color, "fontWeight": "800",
                               "fontSize": "2rem", "marginBottom": "6px"},
                    ),
                    html.P(
                        subline,
                        style={"color": "#2C3E50", "fontSize": "1.1rem",
                               "lineHeight": "1.4", "marginBottom": "0"},
                    ),
                    html.Small(
                        f"Última medición: {last_date.strftime('%d de %B de %Y')}",
                        style={"color": "#7F8C8D", "fontSize": "0.85rem"},
                    ),
                ],
            ),
        ],
    )


def _build_tank_gauge(static_m: float) -> html.Div:
    """Visual fill gauge — % full relative to the historical maximum."""
    pct = max(0, min(100, int(round(100 * static_m / HISTORICAL_MAX_STATIC_M))))
    color, _, _, _ = _traffic_light(static_m)

    # Quartile dots for plain-language interpretation
    if pct >= 75:
        word = "casi lleno"
    elif pct >= 50:
        word = "medio lleno"
    elif pct >= 25:
        word = "poco lleno"
    else:
        word = "casi vacío"

    return html.Div(
        children=[
            html.Div(
                style={"display": "flex", "alignItems": "baseline",
                       "gap": "8px", "marginBottom": "12px"},
                children=[
                    html.Span(f"{pct}%",
                              style={"fontSize": "3.5rem", "fontWeight": "800",
                                     "color": color, "lineHeight": "1"}),
                    html.Span(f"({word})",
                              style={"fontSize": "1.1rem", "color": "#7F8C8D"}),
                ],
            ),
            # Progress bar — big & visual
            html.Div(
                style={"width": "100%", "height": "32px",
                       "backgroundColor": "#ECF0F1",
                       "borderRadius": "16px", "overflow": "hidden",
                       "marginBottom": "12px"},
                children=html.Div(
                    style={"width": f"{pct}%", "height": "100%",
                           "backgroundColor": color,
                           "transition": "width 0.6s",
                           "borderRadius": "16px"},
                ),
            ),
            html.P(
                f"Comparando con la mejor medición histórica ({HISTORICAL_MAX_STATIC_M:.1f} m de agua).",
                style={"color": "#566D7E", "fontSize": "0.85rem",
                       "marginBottom": "0"},
            ),
        ],
    )


def _build_riego_rec(rain_next_3d_mm: float, static_m: float) -> html.Div:
    """Simple decision rule: rain coming OR water tight → don't water; else water."""
    if rain_next_3d_mm >= 5:
        emoji = "🌧️"
        headline = "No hace falta regar"
        sub = (f"Se esperan ~{rain_next_3d_mm:.0f} mm de lluvia en los próximos 3 días. "
               "Espere a que llueva.")
        color = "#2980B9"
    elif static_m < THRESHOLD_AMBER_M:
        emoji = "⚠️"
        headline = "Riegue solo lo necesario"
        sub = ("Hay poca agua en el pozo. Riegue las plantas más importantes "
               "(maracuyá adulta, plantas con frutos).")
        color = "#E74C3C"
    else:
        emoji = "💧"
        headline = "Sí, riegue hoy"
        sub = ("No se espera lluvia. Riegue temprano por la mañana o al atardecer "
               "para no perder agua.")
        color = "#27AE60"

    return html.Div(
        style={"display": "flex", "alignItems": "center", "gap": "16px"},
        children=[
            html.Div(emoji, style={"fontSize": "4rem", "lineHeight": "1"}),
            html.Div(
                children=[
                    html.H3(headline,
                            style={"color": color, "fontWeight": "800",
                                   "fontSize": "1.6rem", "marginBottom": "8px"}),
                    html.P(sub,
                           style={"color": "#2C3E50", "fontSize": "1rem",
                                  "lineHeight": "1.4", "marginBottom": "0"}),
                ],
            ),
        ],
    )


def _rain_emoji(precip_mm: float) -> str:
    if precip_mm >= 10:
        return "🌧️"
    if precip_mm >= 2:
        return "🌦️"
    if precip_mm >= 0.5:
        return "⛅"
    return "☀️"


SPANISH_DAYS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def _build_weather_strip(forecast_df: pd.DataFrame) -> html.Div:
    """7-day strip of emoji + day-of-week + mm rain."""
    df = forecast_df.head(7).copy()
    cells = []
    for _, row in df.iterrows():
        d = pd.to_datetime(row["date"])
        precip = float(row.get("precip_mm", 0))
        emoji = _rain_emoji(precip)
        dow = SPANISH_DAYS[d.weekday()]
        cells.append(
            html.Div(
                style={"flex": "1", "textAlign": "center", "padding": "8px",
                       "minWidth": "70px"},
                children=[
                    html.Div(dow.upper(),
                             style={"fontSize": "0.8rem", "fontWeight": "700",
                                    "color": "#7F8C8D",
                                    "marginBottom": "2px"}),
                    html.Div(d.strftime("%d/%m"),
                             style={"fontSize": "0.75rem", "color": "#95A5A6",
                                    "marginBottom": "4px"}),
                    html.Div(emoji,
                             style={"fontSize": "2.2rem", "lineHeight": "1"}),
                    html.Div(f"{precip:.0f} mm" if precip >= 0.5 else "—",
                             style={"fontSize": "0.85rem",
                                    "color": "#2980B9" if precip >= 0.5 else "#BDC3C7",
                                    "fontWeight": "600",
                                    "marginTop": "4px"}),
                ],
            )
        )
    return html.Div(
        style={"display": "flex", "justifyContent": "space-between",
               "flexWrap": "wrap", "gap": "4px"},
        children=cells,
    )


def _build_alerts(static_m: float, days_to_critical: int | None,
                  rain_next_7d_mm: float, enso_state: str) -> html.Div:
    items = []

    if static_m < THRESHOLD_AMBER_M:
        items.append(("🔴", "Nivel del pozo bajo",
                     f"Sólo {static_m:.1f} m de agua. Reduzca el riego."))

    if days_to_critical is not None and days_to_critical <= 14:
        items.append(("⚠️", "Aviso temprano",
                     f"Si sigue así, en {days_to_critical} días el pozo "
                     "estará en nivel crítico."))

    if enso_state == "el_nino":
        items.append(("🌧️", "El Niño activo",
                     "Pueden venir lluvias fuertes. El pozo se llenará, "
                     "pero cuide los cultivos del exceso de agua."))
    elif enso_state == "la_nina":
        items.append(("🌵", "La Niña activa",
                     "Puede haber sequía. Ahorre agua y vigile el pozo "
                     "más seguido."))

    if rain_next_7d_mm < 1 and static_m < THRESHOLD_GREEN_M:
        items.append(("☀️", "Semana sin lluvia",
                     "No se espera lluvia esta semana. Use el agua del "
                     "pozo con cuidado."))

    if not items:
        return html.Div(
            style={"display": "flex", "alignItems": "center", "gap": "12px",
                   "padding": "12px"},
            children=[
                html.Div("✅", style={"fontSize": "2.5rem"}),
                html.Div(
                    children=[
                        html.Strong("Todo en orden",
                                    style={"fontSize": "1.1rem",
                                           "color": "#27AE60"}),
                        html.P("No hay avisos importantes hoy.",
                               style={"color": "#566D7E", "marginBottom": "0",
                                      "fontSize": "0.95rem"}),
                    ],
                ),
            ],
        )

    rendered = []
    for emoji, title, body in items:
        rendered.append(
            html.Div(
                style={"display": "flex", "alignItems": "flex-start",
                       "gap": "12px", "padding": "10px 0",
                       "borderBottom": "1px solid #ECF0F1"},
                children=[
                    html.Div(emoji, style={"fontSize": "2rem", "lineHeight": "1"}),
                    html.Div(
                        children=[
                            html.Strong(title, style={"fontSize": "1rem",
                                                       "color": "#1A2744"}),
                            html.P(body, style={"color": "#2C3E50",
                                                "marginBottom": "0",
                                                "fontSize": "0.9rem",
                                                "lineHeight": "1.4"}),
                        ],
                    ),
                ],
            )
        )
    return html.Div(rendered)


def register_sencilla_callbacks(app):
    @app.callback(
        Output("sencilla-status-hero", "children"),
        Output("sencilla-tank-gauge", "children"),
        Output("sencilla-riego-rec", "children"),
        Output("sencilla-weather-strip", "children"),
        Output("sencilla-alerts", "children"),
        Input("auto-refresh", "n_intervals"),
    )
    def refresh_sencilla(_n):
        history = _load_history()
        params, sigma, _ = _load_params()

        if history.empty:
            return _empty_state()

        last = history.iloc[-1]
        static_m = float(last["nivel_estatico_m"])
        last_date = last["date"]

        # ENSO
        try:
            _, _, enso_state = noaa_oni.latest_state()
        except Exception:
            enso_state = "neutral"

        # 7-day local forecast
        rain_next_3d_mm = 0.0
        rain_next_7d_mm = 0.0
        weather_df = pd.DataFrame()
        try:
            weather_df = open_meteo.fetch_forecast(-6.91, -79.51, days=7)
            rain_next_3d_mm = float(weather_df.head(3)["precip_mm"].sum())
            rain_next_7d_mm = float(weather_df["precip_mm"].sum())
        except Exception:
            pass

        # Days until critical (from technical forecast)
        days_to_critical: int | None = None
        try:
            local = open_meteo.fetch_forecast(-6.91, -79.51, days=14)
            up = andes_rainfall.fetch_upper_basin_forecast(days=14)
            up["recharge_proxy_mm"] = andes_rainfall.recharge_proxy(up["andes_precip_mm"])
            try:
                _, anom, _ = noaa_oni.latest_state()
            except Exception:
                anom = 0.0
            df = local.merge(up[["date", "recharge_proxy_mm"]], on="date", how="left")
            df["recharge_proxy_mm"] = df["recharge_proxy_mm"].fillna(0)
            df["local_rainfall_mm"] = df["precip_mm"]
            df["extraction_l"] = 45000
            df["oni_anom"] = anom
            df = df[["date", "recharge_proxy_mm", "local_rainfall_mm",
                     "extraction_l", "oni_anom", "et0_mm"]]
            fc = forecast_with_uncertainty(h0_m=static_m, drivers=df,
                                           params=params, residual_std_m=sigma)
            fc["date"] = pd.to_datetime(fc["date"])
            days_to_critical = days_until_critical(fc, threshold_m=THRESHOLD_AMBER_M)
        except Exception:
            pass

        return (
            _build_status_hero(static_m, last_date),
            _build_tank_gauge(static_m),
            _build_riego_rec(rain_next_3d_mm, static_m),
            _build_weather_strip(weather_df),
            _build_alerts(static_m, days_to_critical, rain_next_7d_mm, enso_state),
        )


def _empty_state():
    msg = html.Div(
        style={"textAlign": "center", "padding": "32px"},
        children=[
            html.Div("📭", style={"fontSize": "3rem"}),
            html.P("Cargando datos...",
                   style={"color": "#7F8C8D", "fontSize": "1rem"}),
        ],
    )
    return msg, msg, msg, msg, msg
