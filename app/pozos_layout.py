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
                    _stat_card_pozo("pozos-well-level", "Nivel del Pozo 1",
                                    "—", "#00897B", "Cargando..."),
                    _stat_card_pozo("pozos-pump-utilization", "Bombeo Pozo 1",
                                    "100%", "#E67E22", "50.000 / 50.000 L/día"),
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
                                                    "CALIBRADO · LOO-CV",
                                                    color="success",
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

            # ── Weather + news alerts row ──────────────────────────────────
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader(
                                    dbc.Row(
                                        [
                                            dbc.Col(
                                                html.Span("🌡️ Golpe de calor (próximos 14 días)",
                                                          style={"fontWeight": "600",
                                                                 "color": "#1A2744"}),
                                            ),
                                            dbc.Col(
                                                dbc.Badge(id="heat-badge",
                                                          children="—",
                                                          color="secondary",
                                                          style={"fontSize": "0.7rem"}),
                                                width="auto",
                                            ),
                                        ],
                                        align="center", justify="between",
                                    ),
                                    style={"backgroundColor": "white",
                                           "borderBottom": "2px solid #E67E22"},
                                ),
                                dbc.CardBody(
                                    html.Div(id="heat-card-body"),
                                    style={"padding": "12px"},
                                ),
                            ],
                            style={"border": "none",
                                   "boxShadow": "0 2px 8px rgba(0,0,0,.08)"},
                        ),
                        md=5,
                    ),
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader(
                                    dbc.Row(
                                        [
                                            dbc.Col(
                                                html.Span("📰 Fenómeno El Niño en medios",
                                                          style={"fontWeight": "600",
                                                                 "color": "#1A2744"}),
                                            ),
                                            dbc.Col(
                                                dbc.Badge("Google News · ENFEN",
                                                          color="info",
                                                          style={"fontSize": "0.7rem"}),
                                                width="auto",
                                            ),
                                        ],
                                        align="center", justify="between",
                                    ),
                                    style={"backgroundColor": "white",
                                           "borderBottom": "2px solid #2874A6"},
                                ),
                                dbc.CardBody(
                                    html.Div(id="news-card-body"),
                                    style={"padding": "8px 12px"},
                                ),
                            ],
                            style={"border": "none",
                                   "boxShadow": "0 2px 8px rgba(0,0,0,.08)"},
                        ),
                        md=7,
                    ),
                ],
                className="g-2",
                style={"marginBottom": "12px"},
            ),

            # ── Per-crop stress forecast (predictive AI) ───────────────────
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader(
                                    dbc.Row(
                                        [
                                            dbc.Col(
                                                html.Span("🌱 Pronóstico de estrés por cultivo (próximos 16 días)",
                                                          style={"fontWeight": "600",
                                                                 "color": "#1A2744"}),
                                            ),
                                            dbc.Col(
                                                dbc.Badge(id="crop-stress-badge",
                                                          children="—",
                                                          color="secondary",
                                                          style={"fontSize": "0.7rem"}),
                                                width="auto",
                                            ),
                                        ],
                                        align="center", justify="between",
                                    ),
                                    style={"backgroundColor": "white",
                                           "borderBottom": "2px solid #00897B"},
                                ),
                                dbc.CardBody(
                                    html.Div(id="crop-stress-card-body"),
                                    style={"padding": "12px"},
                                ),
                            ],
                            style={"border": "none",
                                   "boxShadow": "0 2px 8px rgba(0,0,0,.08)"},
                        ),
                        md=12,
                    ),
                ],
                className="g-2",
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
                style={"marginBottom": "12px"},
            ),

            # ── NGO manual measurement form (asked for in 2026-05-05 meeting) ─
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader(
                                    dbc.Row(
                                        [
                                            dbc.Col(
                                                html.Span("📝 Registrar medición manual",
                                                          style={"fontWeight": "600",
                                                                 "color": "#1A2744"}),
                                            ),
                                            dbc.Col(
                                                dbc.Badge("NGO 2026-05-05",
                                                          color="info",
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
                                dbc.CardBody(_build_measurement_form(),
                                             style={"padding": "12px"}),
                            ],
                            style={"border": "none",
                                   "boxShadow": "0 2px 8px rgba(0,0,0,.08)"},
                        ),
                        md=12,
                    ),
                ],
                className="g-2",
            ),
        ],
    )


def _build_measurement_form() -> html.Div:
    return html.Div([
        html.P(
            "Ingrese la medición trimestral del pozo. El modelo se actualiza "
            "automáticamente al guardar.",
            style={"fontSize": "0.8rem", "color": "#5D6D7E", "marginBottom": "10px"},
        ),
        dbc.Row([
            dbc.Col([
                html.Label("Pozo", style={"fontSize": "0.78rem",
                                          "fontWeight": "600",
                                          "color": "#1A2744"}),
                dcc.Dropdown(
                    id="measurement-well",
                    options=[
                        {"label": "Pozo 1 ASR", "value": "pozo1_asr"},
                        {"label": "Pozo 2 ASR (respaldo)", "value": "pozo2_asr"},
                    ],
                    value="pozo1_asr",
                    clearable=False,
                    style={"fontSize": "0.85rem"},
                ),
            ], md=2),
            dbc.Col([
                html.Label("Fecha", style={"fontSize": "0.78rem",
                                           "fontWeight": "600",
                                           "color": "#1A2744"}),
                dcc.DatePickerSingle(
                    id="measurement-date",
                    display_format="DD/MM/YYYY",
                    style={"width": "100%"},
                ),
            ], md=2),
            dbc.Col([
                html.Label("N. estático (m)",
                           style={"fontSize": "0.78rem",
                                  "fontWeight": "600", "color": "#1A2744"}),
                dbc.Input(id="measurement-static-m", type="number",
                          min=0, max=20, step=0.01, placeholder="2.50"),
            ], md=2),
            dbc.Col([
                html.Label("N. dinámico (m)",
                           style={"fontSize": "0.78rem",
                                  "fontWeight": "600", "color": "#1A2744"}),
                dbc.Input(id="measurement-dynamic-m", type="number",
                          min=0, max=20, step=0.01, placeholder="1.80"),
            ], md=2),
            dbc.Col([
                html.Label("Caudal (L/min, opcional)",
                           style={"fontSize": "0.78rem",
                                  "fontWeight": "600", "color": "#1A2744"}),
                dbc.Input(id="measurement-flow-lpm", type="number",
                          min=0, max=2000, step=1, placeholder="222"),
            ], md=2),
            dbc.Col([
                html.Label(" ", style={"fontSize": "0.78rem",
                                       "color": "transparent"}),
                dbc.Button("Guardar",
                           id="measurement-submit",
                           color="success", n_clicks=0,
                           style={"width": "100%", "fontWeight": "600"}),
            ], md=2),
        ], className="g-2", style={"marginBottom": "8px"}),
        dbc.Row([
            dbc.Col([
                html.Label("Notas (opcional)",
                           style={"fontSize": "0.78rem",
                                  "fontWeight": "600", "color": "#1A2744"}),
                dbc.Textarea(id="measurement-notes", rows=1,
                             placeholder="Ej: agua turbia, mantenimiento en marcha, etc.",
                             style={"fontSize": "0.85rem"}),
            ], md=12),
        ], className="g-2", style={"marginBottom": "8px"}),
        html.Div(id="measurement-feedback",
                 style={"fontSize": "0.8rem", "marginTop": "6px",
                        "minHeight": "1.2rem"}),
    ])


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
