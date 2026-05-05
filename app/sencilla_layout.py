"""
Vista Sencilla — landing dashboard for NGO field workers.

Designed for users with limited formal education and no technical background:
- Big traffic-light status (verde / amarillo / rojo)
- Visual tank gauge (fill bar)
- 7-day forecast as weather emoji
- Clear riego recommendation
- Active alerts in plain Spanish

No technical jargon, no chart axes, no numbers below the surface.
"""
import dash_bootstrap_components as dbc
from dash import dcc, html

from pozos_callbacks import info_tooltip


def build_sencilla_layout() -> html.Div:
    return html.Div(
        style={"padding": "16px",
               "backgroundColor": "#F8F9FA",
               "minHeight": "85vh"},
        children=[
            # ── Big traffic-light status (top hero) ──────────────────────────
            dbc.Card(
                dbc.CardBody(
                    html.Div(id="sencilla-status-hero"),
                    style={"padding": "24px"},
                ),
                style={"border": "none",
                       "boxShadow": "0 4px 12px rgba(0,0,0,.10)",
                       "marginBottom": "16px"},
            ),

            # ── Tank gauge + Today's irrigation recommendation ──────────────
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader(
                                    html.Span(
                                        "💧 Cuánta agua hay en el pozo",
                                        style={"fontWeight": "700",
                                               "fontSize": "1.1rem",
                                               "color": "#1A2744"},
                                    ),
                                    style={"backgroundColor": "white",
                                           "borderBottom": "3px solid #00897B"},
                                ),
                                dbc.CardBody(
                                    html.Div(id="sencilla-tank-gauge"),
                                    style={"padding": "20px"},
                                ),
                            ],
                            style={"border": "none",
                                   "boxShadow": "0 2px 8px rgba(0,0,0,.08)",
                                   "height": "100%"},
                        ),
                        md=6,
                        style={"marginBottom": "16px"},
                    ),
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader(
                                    html.Span([
                                        "🌱 ¿Hay que regar hoy?",
                                        *info_tooltip(
                                            "tip-riego",
                                            "Recomendación de riego",
                                            "Decisión simple sobre si conviene regar hoy o esperar.",
                                            "Regla: (1) si en los próximos 3 días caen ≥5 mm de lluvia → no riegue, espere; (2) si el pozo está por debajo de 2,0 m → riegue solo lo esencial (priorizar maracuyá adulta); (3) en cualquier otro caso → riegue temprano por la mañana o al atardecer.",
                                            "Lluvia: pronóstico Open-Meteo 7 días. Nivel del pozo: última medición NGO en wells_history.parquet.",
                                        ),
                                    ], style={"fontWeight": "700",
                                              "fontSize": "1.1rem",
                                              "color": "#1A2744"}),
                                    style={"backgroundColor": "white",
                                           "borderBottom": "3px solid #00897B"},
                                ),
                                dbc.CardBody(
                                    html.Div(id="sencilla-riego-rec"),
                                    style={"padding": "20px"},
                                ),
                            ],
                            style={"border": "none",
                                   "boxShadow": "0 2px 8px rgba(0,0,0,.08)",
                                   "height": "100%"},
                        ),
                        md=6,
                        style={"marginBottom": "16px"},
                    ),
                ],
                className="g-2",
            ),

            # ── 7-day weather strip ──────────────────────────────────────────
            dbc.Card(
                [
                    dbc.CardHeader(
                        html.Span(
                            "☀️ El tiempo en los próximos 7 días",
                            style={"fontWeight": "700",
                                   "fontSize": "1.1rem",
                                   "color": "#1A2744"},
                        ),
                        style={"backgroundColor": "white",
                               "borderBottom": "3px solid #00897B"},
                    ),
                    dbc.CardBody(
                        html.Div(id="sencilla-weather-strip"),
                        style={"padding": "16px"},
                    ),
                ],
                style={"border": "none",
                       "boxShadow": "0 2px 8px rgba(0,0,0,.08)",
                       "marginBottom": "16px"},
            ),

            # ── Active alerts ────────────────────────────────────────────────
            dbc.Card(
                [
                    dbc.CardHeader(
                        html.Span([
                            "🔔 Avisos importantes",
                            *info_tooltip(
                                "tip-alerts",
                                "Avisos importantes",
                                "Alertas accionables sobre el sistema (pozo bajo, lluvia fuerte esperada, sequía en la cuenca, ENSO activo, etc.) en lenguaje claro.",
                                "Generadas con reglas: nivel <2,0 m → 'pozo bajo'; lluvia 7 días >50 mm → 'esté listo'; SPI-3 cuenca alta <-1 → 'sequía'; ONI >+0,5 → 'El Niño activo'. La sección Pozos tiene la versión técnica con probabilidades del ensemble.",
                                "Cálculos del modelo + Open-Meteo + NOAA ONI.",
                            ),
                        ], style={"fontWeight": "700",
                                  "fontSize": "1.1rem",
                                  "color": "#1A2744"}),
                        style={"backgroundColor": "white",
                               "borderBottom": "3px solid #00897B"},
                    ),
                    dbc.CardBody(
                        html.Div(id="sencilla-alerts"),
                        style={"padding": "16px"},
                    ),
                ],
                style={"border": "none",
                       "boxShadow": "0 2px 8px rgba(0,0,0,.08)",
                       "marginBottom": "16px"},
            ),

            # ── Footer help ─────────────────────────────────────────────────
            html.Div(
                [
                    html.Span("¿Necesita más detalle? ",
                              style={"color": "#7F8C8D", "fontSize": "0.9rem"}),
                    html.Span(
                        "Pulse las pestañas 🌱 Cultivos o 💧 Pozos arriba.",
                        style={"color": "#566D7E", "fontSize": "0.9rem",
                               "fontStyle": "italic"},
                    ),
                ],
                style={"textAlign": "center", "padding": "12px"},
            ),
        ],
    )
