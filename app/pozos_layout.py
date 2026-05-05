"""
Pozos tab — groundwater monitoring + forecast for Sayariy wells.
Visual structure only; logic lives in pozos_callbacks.py.
"""
import dash_bootstrap_components as dbc
from dash import dcc, html

# Tooltip helper (lives in callbacks for now to keep the import surface small)
from pozos_callbacks import info_tooltip


def build_pozos_layout() -> html.Div:
    return html.Div(
        style={"padding": "12px"},
        children=[
            # ── Top stats row ─────────────────────────────────────────────────
            dbc.Row(
                [
                    _stat_card_pozo(
                        "pozos-well-level", "Nivel del Pozo 1",
                        "—", "#00897B", "Cargando...",
                        tip=(
                            "Porcentaje de capacidad útil del pozo (100% = columna estática histórica máxima 3,5 m, 0% = umbral crítico 2,0 m).",
                            "(columna_actual - 2,0) / (3,5 - 2,0) × 100. Pedido explícito de la NGO en reunión 2026-05-05.",
                            "Mediciones manuales NGO (Chequeo.xlsx + formulario abajo). Schematic Alarcón 2021 da el baseline 3,5 m.",
                        ),
                    ),
                    _stat_card_pozo(
                        "pozos-pump-utilization", "Bombeo Pozo 1",
                        "100%", "#E67E22", "50.000 / 50.000 L/día",
                        tip=(
                            "Cuánto del techo físico de bombeo se está usando hoy. 100% = al límite.",
                            "extracción_actual / capacidad_sostenible. La capacidad actual son ~50.000 L/día de la bomba solar 2\" (NGO 2026-05-05: 'llenan 50 mil litros en 4 horas a 28-30 °C'). El cap previo 52.500 L era de la Pedrollo 4SR45Gm/30.",
                            "NGO Sayariy reunión 2026-05-05 + ficha Pedrollo (Alarcón 2021).",
                        ),
                    ),
                    _stat_card_pozo(
                        "pozos-storage",       "Almacenamiento",
                        "50.000 L", "#27AE60",
                        "4×2.500 + 1×40.000 L (HDPE)",
                        tip=(
                            "Capacidad total de los tanques que reciben el agua bombeada (no es lo que hay AHORA, es el tope físico).",
                            "Suma de tanques: 4 de 2.500 L (huertos+vivienda) + 1 geomembrana HDPE de 40.000 L (parcela maracuyá).",
                            "NGO Sayariy / Agua.docx (esquema de distribución).",
                        ),
                    ),
                    _stat_card_pozo(
                        "pozos-enso",          "Estado ENSO",
                        "—",   "#566D7E", "Cargando...",
                        tip=(
                            "Estado del fenómeno El Niño / La Niña medido por el Oceanic Niño Index (ONI). Valores >+0,5 = El Niño, <-0,5 = La Niña, entre = Neutral.",
                            "ONI = anomalía media de 3 meses de la temperatura superficial del Pacífico ecuatorial (región Niño 3.4). Actualizado mensualmente por NOAA.",
                            "NOAA Climate Prediction Center: psl.noaa.gov/data/correlation/oni.data",
                        ),
                    ),
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
                                    html.Span([
                                        "🗺️ Pozos Sayariy en Cayaltí",
                                        *info_tooltip(
                                            "tip-wells-map",
                                            "Mapa de pozos",
                                            "Ubicación física de los pozos de la asociación Sayariy y la dirección del aporte hídrico desde la cuenca alta del Río Zaña.",
                                            "Verde = operativo (Pozo 1). Naranja = respaldo (Pozo 2, no opera continuamente). Línea azul = recarga lateral del Río Zaña con desfase 14-60 días.",
                                            "Coords Pozo 1 = schematic Alarcón 2021 UTM 663913E,9235271N (zona 17S). Pozo 2 = link de Maps de la NGO 2026-05-05.",
                                        ),
                                    ], style={"fontWeight": "600",
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
                                                html.Span([
                                                    "💧 Nivel del Pozo 1 — historia + pronóstico 30 días",
                                                    *info_tooltip(
                                                        "tip-forecast-chart",
                                                        "Pronóstico del nivel del pozo",
                                                        "Cuánta agua tiene el pozo hoy y proyección de los próximos 35 días + extensión climatológica hasta 90 días. La banda P10-P90 muestra incertidumbre real del modelo.",
                                                        "Modelo físico de balance hídrico (recarga lateral del Río Zaña + lluvia local + ET₀ - extracción) calibrado contra 5 mediciones NGO (LOO-CV RMSE 0,21 m). El pronóstico corre 30 trayectorias del ensemble GFS-GEFS y reporta la mediana + banda 10-90 percentil.",
                                                        "NGO Chequeo.xlsx (5 mediciones 2022-2026) + Open-Meteo (lluvia/ET₀) + NOAA ONI (ENSO).",
                                                    ),
                                                ], style={"fontWeight": "600",
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
                                                html.Span([
                                                    "🌤️ Pronóstico del tiempo (14 días)",
                                                    *info_tooltip(
                                                        "tip-weather",
                                                        "Pronóstico del tiempo",
                                                        "Temperatura máx/mín, lluvia y viento por día para los próximos 14 días sobre la parcela Sayariy.",
                                                        "Modelo numérico GFS-GEFS de NOAA, post-procesado por Open-Meteo. Se actualiza cada 5 min en el dashboard.",
                                                        "api.open-meteo.com (gratis, sin auth) — coordenadas: Pozo 1 ASR (-6.916, -79.516)",
                                                    ),
                                                ], style={"fontWeight": "600",
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
                                                html.Span([
                                                    "📰 Fenómeno El Niño en medios",
                                                    *info_tooltip(
                                                        "tip-news",
                                                        "Noticias El Niño / La Niña",
                                                        "Las últimas noticias de medios peruanos sobre El Niño Costero, La Niña y avisos de ENFEN — para que el equipo NGO sepa qué dice la prensa oficial sobre lo que viene.",
                                                        "Búsqueda automática de Google News con el query \"fenómeno del niño OR fenómeno la niña OR ENFEN Perú\". Se filtran items mayores de 60 días y se muestran los 3 más recientes con fuente, fecha y fragmento.",
                                                        "Google News RSS (gratis, sin auth). Cubre El Comercio, La República, RPP, La Industria, Expreso, Infobae, Andina, etc.",
                                                    ),
                                                ], style={"fontWeight": "600",
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
                                                html.Span([
                                                    "🌱 Pronóstico de estrés por cultivo (próximos 16 días)",
                                                    *info_tooltip(
                                                        "tip-crop-stress",
                                                        "Pronóstico de estrés por cultivo",
                                                        "Cuántos días de los próximos 16 cada cultivo va a sufrir estrés hídrico o térmico — combina temperatura, demanda evapotranspirativa y capacidad de bombeo del Pozo 1.",
                                                        "Por cada día y cultivo: demanda = Kc(FAO-56) × ET₀ × área-mojada × N° plantas, ajustada por multiplicador estacional NGO (Oct-Abr ×1,45). Si la demanda total supera 30.000 L/día (cap del bombeo menos consumo doméstico), cada cultivo recibe proporcionalmente menos. Estrés = déficit >20% O calor >35 °C.",
                                                        "Open-Meteo (tmax, ET₀) + parámetros NGO confirmados 2026-05-05 (3 ha maracuyá + 10 ha huertos + 50.000 L/día bombeo)",
                                                    ),
                                                ], style={"fontWeight": "600",
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
                                    html.Span([
                                        "⚙️ Sistema de distribución",
                                        *info_tooltip(
                                            "tip-distribution",
                                            "Sistema de distribución",
                                            "Cómo se reparte el agua bombeada del Pozo 1 hacia los almacenamientos, las viviendas y los cultivos.",
                                            "Bombeo solar 2\" → 4 tanques de 2.500 L (huertos+vivienda) + 1 geomembrana HDPE 40.000 L (parcela maracuyá) → red HDPE 500 m × 3\" → riego por goteo. Reparto NGO 2026-05-05: 20 mil L/día viviendas + 30-45 mil L/día cultivos según temporada.",
                                            "NGO Sayariy Agua.docx (esquema) + reunión 2026-05-05 (cifras).",
                                        ),
                                    ], style={"fontWeight": "600",
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
                                                html.Span([
                                                    "🤖 Resumen IA",
                                                    *info_tooltip(
                                                        "tip-ai-summary",
                                                        "Resumen IA",
                                                        "Síntesis en lenguaje natural del estado del pozo, las probabilidades de riesgo (1/2/4 sem) y los datos meteo-climáticos relevantes.",
                                                        "Hoy se compone con plantilla determinística + métricas calculadas (probabilidades del ensemble, SPI-3, ENSO). Phase 4 reemplazará la plantilla por una llamada a Claude Haiku con los mismos inputs para narrativa más fluida.",
                                                        "Cálculos del modelo + Open-Meteo + NOAA ONI. Plantilla pendiente de migrar a LLM.",
                                                    ),
                                                ], style={"fontWeight": "600",
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
                                                html.Span([
                                                    "📝 Registrar medición manual",
                                                    *info_tooltip(
                                                        "tip-form",
                                                        "Formulario de medición",
                                                        "Permite al responsable de campo introducir la medición trimestral del pozo (estático, dinámico, opcionalmente caudal y notas) sin pasar por código.",
                                                        "Al guardar: la fila se añade a wells_history.parquet y se dispara una recalibración del modelo en segundo plano (~30 s). Recargue la página para ver los nuevos parámetros.",
                                                        "Pedido explícito de la NGO en reunión 2026-05-05: \"eso sería súper\".",
                                                    ),
                                                ], style={"fontWeight": "600",
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
                    color: str, subtitle: str,
                    tip: tuple[str, str, str] | None = None) -> dbc.Col:
    """tip = (what, how, source) — adds an ℹ️ tooltip next to the label."""
    label_children = [label]
    extras: list = []
    if tip is not None:
        what, how, source = tip
        label_children.extend(info_tooltip(
            f"tip-{stat_id}", label, what, how, source))
    return dbc.Col(
        dbc.Card(
            dbc.CardBody(
                [
                    html.H3(default_value, id=stat_id,
                            style={"color": color, "margin": "0",
                                   "fontWeight": "700", "fontSize": "1.6rem"}),
                    html.P(label_children,
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
