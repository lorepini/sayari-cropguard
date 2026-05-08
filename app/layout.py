"""
CropGuard dashboard layout.
All visual structure is defined here; logic lives in callbacks.py.
"""
import dash_bootstrap_components as dbc
from dash import dcc, html

from pozos_callbacks import info_tooltip
from pozos_layout import build_pozos_layout
from sencilla_layout import build_sencilla_layout


def build_layout() -> dbc.Container:
    return dbc.Container(
        fluid=True,
        style={"backgroundColor": "#F8F9FA", "minHeight": "100vh", "padding": "0"},
        children=[
            # ── Header ───────────────────────────────────────────────────────
            dbc.Navbar(
                dbc.Container(
                    fluid=True,
                    children=[
                        dbc.NavbarBrand(
                            [
                                html.Span("🌿 ", style={"fontSize": "1.4rem"}),
                                html.Strong("CropGuard", style={"fontSize": "1.3rem",
                                                                 "color": "white"}),
                                html.Span("  ·  Sayariy-Resurgiendo  ·  Lambayeque, Perú",
                                          style={"color": "#A9CCE3",
                                                 "fontSize": "0.9rem",
                                                 "marginLeft": "8px"}),
                            ]
                        ),
                        dbc.Nav(
                            [
                                dbc.NavItem(
                                    html.Span(
                                        id="last-update-label",
                                        style={"color": "#AED6F1",
                                               "fontSize": "0.85rem",
                                               "lineHeight": "2.5rem"},
                                    )
                                ),
                            ],
                            className="ms-auto",
                        ),
                    ],
                ),
                color="#1A2744",
                dark=True,
                style={"padding": "0.5rem 1rem"},
            ),

            # ── Tabs (Sencilla | Pozos | Cultivos) ────────────────────────────
            dbc.Tabs(
                [
                    dbc.Tab(
                        build_sencilla_layout(),
                        label="🏠 Vista Sencilla",
                        tab_id="tab-sencilla",
                        active_label_style={"color": "#00897B",
                                            "fontWeight": "700"},
                        label_style={"fontSize": "0.95rem"},
                    ),
                    dbc.Tab(
                        build_pozos_layout(),
                        label="💧 Pozos",
                        tab_id="tab-pozos",
                        active_label_style={"color": "#00897B",
                                            "fontWeight": "700"},
                        label_style={"fontSize": "0.95rem"},
                    ),
                    dbc.Tab(
                        _build_crop_content(),
                        label="🌱 Cultivos",
                        tab_id="tab-cultivos",
                        active_label_style={"color": "#00897B",
                                            "fontWeight": "700"},
                        label_style={"fontSize": "0.95rem"},
                    ),
                ],
                id="main-tabs",
                active_tab="tab-sencilla",
                style={"backgroundColor": "white",
                       "padding": "0 12px",
                       "borderBottom": "1px solid #E5E7E9"},
            ),

            # Hidden store + interval (shared across tabs)
            dcc.Store(id="selected-community", data=None),
            # 15-minute refresh — data sources (Open-Meteo, NOAA ONI) update
            # at most hourly, and Open-Meteo's free tier rate-limits per IP.
            dcc.Interval(id="auto-refresh", interval=15 * 60 * 1000, n_intervals=0),
        ],
    )


def _build_crop_content() -> html.Div:
    return html.Div(
        style={"padding": "0"},
        children=[
            dbc.Row(
                [
                    # Left: map
                    dbc.Col(
                        [
                            dbc.Card(
                                [
                                    dbc.CardHeader(
                                        dbc.Row(
                                            [
                                                dbc.Col(
                                                    html.Span([
                                                        "Mapa de Salud de Cultivos",
                                                        *info_tooltip(
                                                            "tip-crop-map",
                                                            "Mapa de salud de cultivos",
                                                            "Estado de la vegetación en cada polígono monitorizado, basado en imágenes satelitales recientes.",
                                                            "Color = índice elegido (NDVI / NDWI / Stress %). NDVI mide salud de la vegetación (0-1, alto = verde sano). NDWI mide humedad foliar (alto = bien hidratado). Stress % combina ambos vs umbrales de Quintanilla 2024 para arroz/caña en Lambayeque. Un polígono con datos rojos sugiere visita de campo.",
                                                            "Sentinel-2 L2A (10 m, cada 5 días). El cap de cobertura nubosa es 25%. La parcela Sayariy (azul claro) es la AOI primaria; las otras 5 son contexto regional con polígonos placeholder de 2,8 km — pendientes de polígonos reales por chacra de la NGO.",
                                                        ),
                                                    ], style={"fontWeight": "600",
                                                              "color": "#1A2744"}),
                                                    width="auto",
                                                ),
                                                dbc.Col(
                                                    [
                                                        _legend_dot("#27AE60", "Saludable"),
                                                        _legend_dot("#F39C12", "Vigilancia"),
                                                        _legend_dot("#E74C3C", "Alerta"),
                                                        _legend_dot("#95A5A6", "Sin datos"),
                                                    ],
                                                    className="d-flex align-items-center gap-3",
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
                                            id="community-map",
                                            config={"scrollZoom": True,
                                                    "displayModeBar": False},
                                            style={"height": "55vh"},
                                        ),
                                        style={"padding": "0"},
                                    ),
                                ],
                                style={"border": "none",
                                       "boxShadow": "0 2px 8px rgba(0,0,0,.08)"},
                            ),

                            # Index selector
                            dbc.Card(
                                dbc.CardBody(
                                    dbc.Row(
                                        [
                                            dbc.Col(
                                                html.Label("Índice mostrado:",
                                                           style={"fontWeight": "600",
                                                                  "fontSize": "0.85rem",
                                                                  "color": "#1A2744"}),
                                                width="auto",
                                                className="d-flex align-items-center",
                                            ),
                                            dbc.Col(
                                                dcc.RadioItems(
                                                    id="index-selector",
                                                    options=[
                                                        {"label": " NDVI", "value": "NDVI"},
                                                        {"label": " NDWI", "value": "NDWI"},
                                                        {"label": " Stress %", "value": "stress_prob"},
                                                    ],
                                                    value="NDVI",
                                                    inline=True,
                                                    inputStyle={"marginRight": "4px",
                                                                "marginLeft": "12px"},
                                                    style={"fontSize": "0.9rem"},
                                                ),
                                            ),
                                        ],
                                        align="center",
                                    ),
                                    style={"padding": "0.6rem 1rem"},
                                ),
                                style={"border": "none", "marginTop": "8px",
                                       "boxShadow": "0 2px 8px rgba(0,0,0,.06)"},
                            ),
                        ],
                        md=8,
                        style={"padding": "12px 6px 12px 12px"},
                    ),

                    # Right: alerts + info panel
                    dbc.Col(
                        [
                            # Summary stats row
                            dbc.Row(
                                [
                                    _stat_card("alert-count",   "Alertas activas", "#E74C3C"),
                                    _stat_card("watch-count",   "En vigilancia",   "#F39C12"),
                                    _stat_card("healthy-count", "Saludables",      "#27AE60"),
                                ],
                                className="g-2",
                                style={"marginBottom": "8px"},
                            ),

                            # Alert feed
                            dbc.Card(
                                [
                                    dbc.CardHeader(
                                        html.Span([
                                            "📡 Alertas activas",
                                            *info_tooltip(
                                                "tip-crop-alerts",
                                                "Alertas activas (cultivos)",
                                                "Comunidades con vegetación en estado de vigilancia (amarillo) o alerta (rojo) en la imagen satelital más reciente.",
                                                "Para cada comunidad: status = 'alert' si NDVI < 0.35 o stress_prob ≥ 60%; 'watch' si NDVI < 0.55 o stress_prob ≥ 40%; 'healthy' en otro caso. El texto en español lo genera Claude Haiku con los valores reales (cae a plantilla determinística si no hay API key).",
                                                "Imagen Sentinel-2 más reciente (ver fecha en cabecera). Umbrales de Quintanilla et al. 2024 (estudio de arroz en Lambayeque).",
                                            ),
                                        ], style={"fontWeight": "600",
                                                  "color": "#1A2744"}),
                                        style={"backgroundColor": "white",
                                               "borderBottom": "2px solid #00897B"},
                                    ),
                                    dbc.CardBody(
                                        html.Div(id="alert-feed",
                                                 style={"overflowY": "auto",
                                                        "maxHeight": "28vh"}),
                                        style={"padding": "8px"},
                                    ),
                                ],
                                style={"border": "none",
                                       "boxShadow": "0 2px 8px rgba(0,0,0,.08)",
                                       "marginBottom": "8px"},
                            ),

                            # Community detail (shown on map click)
                            dbc.Card(
                                [
                                    dbc.CardHeader(
                                        html.Span("📍 Comunidad seleccionada",
                                                  style={"fontWeight": "600",
                                                         "color": "#1A2744"}),
                                        style={"backgroundColor": "white",
                                               "borderBottom": "2px solid #1A2744"},
                                    ),
                                    dbc.CardBody(
                                        html.Div(id="community-detail",
                                                 children=html.P(
                                                     "Haz clic en una comunidad en el mapa.",
                                                     style={"color": "#7F8C8D",
                                                            "fontSize": "0.85rem"},
                                                 )),
                                        style={"padding": "10px"},
                                    ),
                                ],
                                style={"border": "none",
                                       "boxShadow": "0 2px 8px rgba(0,0,0,.08)"},
                            ),
                        ],
                        md=4,
                        style={"padding": "12px 12px 12px 6px"},
                    ),
                ],
                style={"margin": "0"},
            ),

            # ── Time series chart ─────────────────────────────────────────────
            dbc.Row(
                dbc.Col(
                    dbc.Card(
                        [
                            dbc.CardHeader(
                                dbc.Row(
                                    [
                                        dbc.Col(
                                            html.Span(id="timeseries-title",
                                                      children="Serie temporal de NDVI — todas las comunidades",
                                                      style={"fontWeight": "600",
                                                             "color": "#1A2744"}),
                                        ),
                                        dbc.Col(
                                            dbc.Button(
                                                "📥 Exportar índices (CSV)",
                                                id="crop-download-btn",
                                                color="outline-primary",
                                                size="sm",
                                            ),
                                            width="auto",
                                        ),
                                        dbc.Col(
                                            dcc.Dropdown(
                                                id="community-selector",
                                                placeholder="Filtrar comunidad...",
                                                clearable=True,
                                                style={"fontSize": "0.85rem",
                                                       "minWidth": "200px"},
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
                                [
                                    dcc.Graph(
                                        id="timeseries-chart",
                                        config={"displayModeBar": False},
                                        style={"height": "38vh"},
                                    ),
                                    dcc.Download(id="crop-download"),
                                ],
                                style={"padding": "8px"},
                            ),
                        ],
                        style={"border": "none",
                               "boxShadow": "0 2px 8px rgba(0,0,0,.08)"},
                    ),
                    style={"padding": "0 12px 12px 12px"},
                ),
            ),

        ],
    )


# ── Small helper components ──────────────────────────────────────────────────

def _legend_dot(color: str, label: str) -> html.Span:
    return html.Span(
        [
            html.Span("●", style={"color": color, "marginRight": "3px",
                                  "fontSize": "1rem"}),
            html.Span(label, style={"fontSize": "0.8rem", "color": "#566D7E"}),
        ],
        style={"display": "inline-flex", "alignItems": "center"},
    )


def _stat_card(stat_id: str, label: str, color: str) -> dbc.Col:
    return dbc.Col(
        dbc.Card(
            dbc.CardBody(
                [
                    html.H3("—", id=stat_id,
                            style={"color": color, "margin": "0",
                                   "fontWeight": "700", "fontSize": "1.8rem"}),
                    html.P(label, style={"margin": "0", "fontSize": "0.75rem",
                                        "color": "#566D7E"}),
                ],
                style={"padding": "10px 12px"},
            ),
            style={"border": "none",
                   "boxShadow": "0 2px 6px rgba(0,0,0,.08)",
                   "textAlign": "center"},
        ),
    )
