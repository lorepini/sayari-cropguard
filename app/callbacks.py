"""
All Dash callbacks for CropGuard.
Data loading and chart generation live here.
"""
import sys
from datetime import date
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Input, Output, State, callback, html
import dash_bootstrap_components as dbc

sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from src.model import load_history

# ── Shared data loaders ───────────────────────────────────────────────────────

def load_communities() -> gpd.GeoDataFrame:
    gdf = gpd.read_file(config.COMMUNITIES_GEOJSON)
    return gdf


def get_latest_scores() -> gpd.GeoDataFrame:
    """
    Return the most recent scored GeoDataFrame.
    Merges community polygons with the latest history record.
    Falls back to demo data if no pipeline has been run yet.
    """
    communities = load_communities()
    history = load_history()

    if history.empty:
        return _demo_scores(communities)

    latest_date = history["date"].max()
    latest = history[history["date"] == latest_date]
    merged = communities.merge(
        latest[["community", "NDVI", "NDWI", "stress_prob", "status"]],
        left_on="name", right_on="community", how="left"
    )
    merged["status"] = merged["status"].fillna("no_data")
    return merged


def _demo_scores(communities: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Synthetic scores so the dashboard always renders without real data."""
    rng = np.random.default_rng(seed=42)
    gdf = communities.copy()
    gdf["NDVI"]       = rng.uniform(0.25, 0.72, len(gdf)).round(3)
    gdf["NDWI"]       = rng.uniform(-0.25, 0.15, len(gdf)).round(3)
    gdf["stress_prob"]= rng.uniform(0.05, 0.85, len(gdf)).round(3)

    def _status(row):
        if row["NDVI"] >= config.NDVI_HEALTHY:   return "healthy"
        if row["NDVI"] >= config.NDVI_WATCH:      return "watch"
        return "alert"

    gdf["status"] = gdf.apply(_status, axis=1)
    return gdf


def _demo_history() -> pd.DataFrame:
    """Synthetic 6-month NDVI time series for all communities."""
    communities = load_communities()["name"].tolist()
    rng = np.random.default_rng(seed=7)
    dates = pd.date_range(
        end=date.today(), periods=36, freq="5D"
    )
    rows = []
    for c in communities:
        base = rng.uniform(0.35, 0.65)
        for d in dates:
            noise = rng.normal(0, 0.03)
            trend = -0.003 * (dates.get_loc(d) / len(dates))  # slow decline
            ndvi  = float(np.clip(base + noise + trend, 0.1, 0.85))
            rows.append({"community": c, "date": d, "NDVI": round(ndvi, 3)})
    return pd.DataFrame(rows)


# ── Map figure builder ────────────────────────────────────────────────────────

def build_map(gdf: gpd.GeoDataFrame, index_col: str = "NDVI") -> go.Figure:
    STATUS_COLOR_MAP = config.STATUS_COLORS

    gdf = gdf.copy()
    gdf["color"] = gdf["status"].map(STATUS_COLOR_MAP).fillna("#95A5A6")
    gdf["hover_text"] = gdf.apply(
        lambda r: (
            f"<b>{r['name']}</b><br>"
            f"NDVI: {r.get('NDVI', 'N/D'):.3f}<br>"
            f"NDWI: {r.get('NDWI', 'N/D'):.3f}<br>"
            f"Estrés: {r.get('stress_prob', 0) * 100:.0f}%<br>"
            f"Estado: {r.get('status', 'N/D').upper()}"
        ),
        axis=1,
    )

    # Choropleth value to display
    if index_col not in gdf.columns:
        index_col = "NDVI"

    fig = px.choropleth_mapbox(
        gdf,
        geojson=gdf.__geo_interface__,
        locations=gdf.index,
        color=index_col,
        color_continuous_scale=(
            ["#E74C3C", "#F39C12", "#27AE60"]
            if index_col == "NDVI"
            else "RdYlGn"
        ),
        range_color=(0.1, 0.8) if index_col == "NDVI" else (0, 1),
        mapbox_style=config.MAP_STYLE,
        zoom=config.MAP_ZOOM,
        center=config.MAP_CENTER,
        opacity=0.65,
        hover_name="name",
        hover_data={
            "NDVI": ":.3f",
            "stress_prob": ":.0%",
            "status": True,
        },
        labels={
            "NDVI": "NDVI",
            "stress_prob": "Estrés",
            "status": "Estado",
        },
    )

    fig.update_layout(
        margin={"r": 0, "t": 0, "l": 0, "b": 0},
        coloraxis_colorbar=dict(
            title=index_col,
            thickness=12,
            len=0.6,
            x=1.0,
        ),
        paper_bgcolor="white",
    )
    return fig


# ── Callbacks ─────────────────────────────────────────────────────────────────

def register_callbacks(app):

    @app.callback(
        Output("community-map", "figure"),
        Output("alert-feed", "children"),
        Output("alert-count", "children"),
        Output("watch-count", "children"),
        Output("healthy-count", "children"),
        Output("last-update-label", "children"),
        Output("community-selector", "options"),
        Input("auto-refresh", "n_intervals"),
        Input("index-selector", "value"),
    )
    def refresh_dashboard(_, index_col):
        from src.alerts import generate_all_alerts

        gdf = get_latest_scores()

        # Counts
        counts = gdf["status"].value_counts().to_dict()
        n_alert   = counts.get("alert", 0)
        n_watch   = counts.get("watch", 0)
        n_healthy = counts.get("healthy", 0)

        # Map
        fig = build_map(gdf, index_col=index_col)

        # Alerts feed — only alert/watch rows, sorted by stress
        alert_rows = gdf[gdf["status"].isin(["alert", "watch"])].copy()
        alert_rows = alert_rows.sort_values("stress_prob", ascending=False)

        alerts_text = generate_all_alerts(alert_rows) if not alert_rows.empty else {}

        feed_items = []
        for _, row in alert_rows.iterrows():
            name   = row["name"]
            status = row["status"]
            color  = "#E74C3C" if status == "alert" else "#F39C12"
            text   = alerts_text.get(name, "Sin información disponible.")
            feed_items.append(
                dbc.Alert(
                    [
                        html.Strong(name, style={"display": "block",
                                                 "marginBottom": "2px"}),
                        html.Small(text, style={"lineHeight": "1.4"}),
                    ],
                    color="danger" if status == "alert" else "warning",
                    style={"padding": "8px 12px", "marginBottom": "4px",
                           "fontSize": "0.82rem", "borderLeft": f"4px solid {color}"},
                )
            )

        if not feed_items:
            feed_items = [
                html.P("✅ Ninguna comunidad en alerta esta semana.",
                       style={"color": "#27AE60", "textAlign": "center",
                              "padding": "12px", "fontSize": "0.9rem"})
            ]

        last_update = f"Última actualización: {date.today().strftime('%d/%m/%Y')}"
        community_options = [{"label": n, "value": n}
                             for n in sorted(gdf["name"].tolist())]

        return (fig, feed_items, str(n_alert), str(n_watch), str(n_healthy),
                last_update, community_options)

    @app.callback(
        Output("selected-community", "data"),
        Input("community-map", "clickData"),
        Input("community-selector", "value"),
    )
    def store_selected_community(click_data, dropdown_value):
        if dropdown_value:
            return dropdown_value
        if click_data:
            return click_data["points"][0].get("hovertext") or \
                   click_data["points"][0].get("customdata", [None])[0]
        return None

    @app.callback(
        Output("community-detail", "children"),
        Input("selected-community", "data"),
    )
    def update_community_detail(community_name):
        if not community_name:
            return html.P("Haz clic en una comunidad en el mapa.",
                          style={"color": "#7F8C8D", "fontSize": "0.85rem"})

        gdf = get_latest_scores()
        row = gdf[gdf["name"] == community_name]
        if row.empty:
            return html.P(f"No se encontró: {community_name}")

        row = row.iloc[0]
        ndvi  = row.get("NDVI", float("nan"))
        ndwi  = row.get("NDWI", float("nan"))
        sp    = row.get("stress_prob", float("nan"))
        status = row.get("status", "no_data")

        status_color = config.STATUS_COLORS.get(status, "#95A5A6")
        status_label = {
            "healthy": "✅ Saludable",
            "watch":   "🟡 Vigilancia",
            "alert":   "⚠️ Alerta",
            "no_data": "⚪ Sin datos",
        }.get(status, "?")

        from src.alerts import generate_alert
        alert_text = generate_alert(
            community=community_name,
            ndvi=ndvi,
            stress_prob=sp,
            status=status,
            ndwi=ndwi,
        )

        return [
            html.H6(community_name,
                    style={"fontWeight": "700", "color": "#1A2744",
                           "marginBottom": "6px"}),
            dbc.Badge(status_label,
                      style={"backgroundColor": status_color,
                             "fontSize": "0.8rem", "marginBottom": "8px"}),
            dbc.Row([
                _metric("NDVI",   f"{ndvi:.3f}"  if not np.isnan(ndvi) else "N/D"),
                _metric("NDWI",   f"{ndwi:.3f}"  if not np.isnan(ndwi) else "N/D"),
                _metric("Estrés", f"{sp*100:.0f}%" if not np.isnan(sp)  else "N/D"),
            ], className="g-1", style={"marginBottom": "8px"}),
            html.Hr(style={"margin": "6px 0"}),
            html.P(alert_text,
                   style={"fontSize": "0.82rem", "lineHeight": "1.5",
                          "color": "#2C3E50", "marginBottom": "0"}),
        ]

    @app.callback(
        Output("timeseries-chart", "figure"),
        Output("timeseries-title", "children"),
        Input("selected-community", "data"),
        Input("index-selector", "value"),
    )
    def update_timeseries(community_name, index_col):
        history = load_history()
        if history.empty:
            history = _demo_history()

        if index_col not in history.columns:
            index_col = "NDVI"

        title_base = f"Serie temporal de {index_col}"

        if community_name:
            filtered = history[history["community"] == community_name]
            title = f"{title_base} — {community_name}"
        else:
            filtered = history
            title = f"{title_base} — todas las comunidades"

        if filtered.empty:
            fig = go.Figure()
            fig.update_layout(
                annotations=[{"text": "Sin datos históricos",
                              "showarrow": False, "font": {"size": 14}}],
                paper_bgcolor="white", plot_bgcolor="white",
            )
            return fig, title

        fig = px.line(
            filtered,
            x="date",
            y=index_col,
            color="community" if community_name is None else None,
            color_discrete_sequence=["#1A2744", "#00897B", "#F39C12",
                                     "#E74C3C", "#8E44AD"],
            markers=True,
        )

        # Threshold reference lines for NDVI
        if index_col == "NDVI":
            fig.add_hline(y=config.NDVI_HEALTHY, line_dash="dot",
                          line_color="#27AE60", annotation_text="Saludable",
                          annotation_position="bottom right")
            fig.add_hline(y=config.NDVI_WATCH, line_dash="dot",
                          line_color="#E74C3C", annotation_text="Alerta",
                          annotation_position="bottom right")

        fig.update_layout(
            margin={"r": 10, "t": 10, "l": 50, "b": 30},
            paper_bgcolor="white",
            plot_bgcolor="white",
            legend={"orientation": "h", "y": 1.1, "x": 0},
            xaxis={"showgrid": True, "gridcolor": "#EAECEE"},
            yaxis={"showgrid": True, "gridcolor": "#EAECEE",
                   "range": [-0.1, 1.0] if index_col in ("NDVI", "NDWI") else None},
            font={"family": "Inter, sans-serif", "size": 11},
            hovermode="x unified",
        )
        fig.update_traces(line_width=2, marker_size=5)

        return fig, title


# ── Tiny helper ───────────────────────────────────────────────────────────────

def _metric(label: str, value: str) -> dbc.Col:
    return dbc.Col(
        html.Div(
            [
                html.Div(value, style={"fontWeight": "700", "fontSize": "1.1rem",
                                       "color": "#1A2744"}),
                html.Div(label, style={"fontSize": "0.72rem", "color": "#566D7E"}),
            ],
            style={"textAlign": "center", "backgroundColor": "#F4F6F7",
                   "padding": "6px", "borderRadius": "4px"},
        ),
    )
