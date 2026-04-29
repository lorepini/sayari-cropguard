"""
Pozos tab — groundwater monitoring + forecast for Sayariy wells.
Visual structure only; logic lives in pozos_callbacks.py.
"""
import dash_bootstrap_components as dbc
from dash import dcc, html


def build_pozos_layout() -> html.Div:
    return html.Div(
        style={"padding": "12px"},
        children=[
            # ── Top stats row ─────────────────────────────────────────────────
            dbc.Row(
                [
                    _stat_card_pozo("pozos-capacity-used", "Capacidad usada",
                                    "47%", "#00897B", "45.000 / 95.500 L/día"),
                    _stat_card_pozo("pozos-active",        "Pozos activos",
                                    "2",   "#1A2744", "Pozo 1 + Pozo 2"),
                    _stat_card_pozo("pozos-storage",       "Almacenamiento",
                                    "50.000 L", "#27AE60",
                                    "4×2.500 + 1×40.000 L (HDPE)"),
                    _stat_card_pozo("pozos-enso",          "Estado ENSO",
                                    "—",   "#566D7E", "Cargando..."),
                ],
                className="g-2",
                style={"marginBottom": "12px"},
            ),

            # ── Map + history/forecast ────────────────────────────────────────
            dbc.Row(
                [
                    # Left: well map
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader(
                                    html.Span("🗺️ Pozos Sayariy en Cayaltí",
                                              style={"fontWeight": "600",
                                                     "color": "#1A2744"}),
                                    style={"backgroundColor": "white",
                                           "borderBottom": "2px solid #00897B"},
                                ),
                                dbc.CardBody(
                                    dcc.Graph(
                                        id="pozos-map",
                                        config={"scrollZoom": True,
                                                "displayModeBar": False},
                                        style={"height": "50vh"},
                                    ),
                                    style={"padding": "0"},
                                ),
                            ],
                            style={"border": "none",
                                   "boxShadow": "0 2px 8px rgba(0,0,0,.08)"},
                        ),
                        md=6,
                        style={"padding": "0 6px 0 0"},
                    ),

                    # Right: forecast chart
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader(
                                    dbc.Row(
                                        [
                                            dbc.Col(
                                                html.Span("💧 Nivel del Pozo 1 — historia + pronóstico 30 días",
                                                          style={"fontWeight": "600",
                                                                 "color": "#1A2744"}),
                                            ),
                                            dbc.Col(
                                                dbc.Badge(
                                                    "MODELO EN CALIBRACIÓN",
                                                    color="warning",
                                                    style={"fontSize": "0.7rem"},
                                                ),
                                                width="auto",
                                            ),
                                        ],
                                        align="center",
                                        justify="between",
                                    ),
                                    style={"backgroundColor": "white",
                                           "borderBottom": "2px solid #00897B"},
                                ),
                                dbc.CardBody(
                                    dcc.Graph(
                                        id="pozos-forecast-chart",
                                        config={"displayModeBar": False},
                                        style={"height": "50vh"},
                                    ),
                                    style={"padding": "8px"},
                                ),
                            ],
                            style={"border": "none",
                                   "boxShadow": "0 2px 8px rgba(0,0,0,.08)"},
                        ),
                        md=6,
                        style={"padding": "0 0 0 6px"},
                    ),
                ],
                className="g-0",
                style={"marginBottom": "12px"},
            ),

            # ── Bottom row: distribution system + AI summary placeholder ─────
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader(
                                    html.Span("⚙️ Sistema de distribución",
                                              style={"fontWeight": "600",
                                                     "color": "#1A2744"}),
                                    style={"backgroundColor": "white",
                                           "borderBottom": "2px solid #1A2744"},
                                ),
                                dbc.CardBody(
                                    html.Div(id="pozos-distribution-info"),
                                    style={"padding": "12px"},
                                ),
                            ],
                            style={"border": "none",
                                   "boxShadow": "0 2px 8px rgba(0,0,0,.08)"},
                        ),
                        md=7,
                    ),
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader(
                                    dbc.Row(
                                        [
                                            dbc.Col(
                                                html.Span("🤖 Resumen IA",
                                                          style={"fontWeight": "600",
                                                                 "color": "#1A2744"}),
                                            ),
                                            dbc.Col(
                                                dbc.Badge("Phase 4",
                                                          color="secondary",
                                                          style={"fontSize": "0.7rem"}),
                                                width="auto",
                                            ),
                                        ],
                                        align="center",
                                        justify="between",
                                    ),
                                    style={"backgroundColor": "white",
                                           "borderBottom": "2px solid #00897B"},
                                ),
                                dbc.CardBody(
                                    html.Div(id="pozos-ai-summary"),
                                    style={"padding": "12px"},
                                ),
                            ],
                            style={"border": "none",
                                   "boxShadow": "0 2px 8px rgba(0,0,0,.08)"},
                        ),
                        md=5,
                    ),
                ],
                className="g-2",
            ),
        ],
    )


def _stat_card_pozo(stat_id: str, label: str, default_value: str,
                    color: str, subtitle: str) -> dbc.Col:
    return dbc.Col(
        dbc.Card(
            dbc.CardBody(
                [
                    html.H3(default_value, id=stat_id,
                            style={"color": color, "margin": "0",
                                   "fontWeight": "700", "fontSize": "1.6rem"}),
                    html.P(label,
                           style={"margin": "0", "fontSize": "0.8rem",
                                  "color": "#1A2744", "fontWeight": "600"}),
                    html.P(subtitle, id=f"{stat_id}-subtitle",
                           style={"margin": "2px 0 0 0", "fontSize": "0.7rem",
                                  "color": "#7F8C8D"}),
                ],
                style={"padding": "12px"},
            ),
            style={"border": "none",
                   "boxShadow": "0 2px 6px rgba(0,0,0,.08)",
                   "textAlign": "center"},
        ),
    )
