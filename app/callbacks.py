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
    Falls back to demo data if no pipeline has been run yet or columns are missing.
    """
    communities = load_communities()
    history = load_history()

    REQUIRED = {"NDVI", "NDWI", "stress_prob", "status"}
    if history.empty or not REQUIRED.issubset(set(history.columns)):
        return _demo_scores(communities)

    # Use latest date that has real status values; fall back to latest overall
    has_status = history[history["status"].notna() & (history["status"] != "None")]
    source = has_status if not has_status.empty else history
    latest_date = source["date"].max()
    latest = history[history["date"] == latest_date].copy()

    # Derive status from stress_prob if missing
    def _derive_status(row):
        if row["status"] and row["status"] not in (None, "None", "nan"):
            return row["status"]
        sp = row.get("stress_prob", 0)
        if sp >= 0.60:
            return "alert"
        if sp >= 0.40:
            return "watch"
        return "healthy"

    latest["status"] = latest.apply(_derive_status, axis=1)

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
    """Synthetic 6-month time series for all communities (NDVI, NDWI, stress_prob)."""
    communities = load_communities()["name"].tolist()
    rng = np.random.default_rng(seed=7)
    dates = pd.date_range(end=date.today(), periods=36, freq="5D")
    rows = []
    for c in communities:
        ndvi_base = rng.uniform(0.35, 0.65)
        ndwi_base = rng.uniform(-0.20, 0.10)
        for i, d in enumerate(dates):
            trend = -0.003 * (i / len(dates))
            ndvi = float(np.clip(ndvi_base + rng.normal(0, 0.03) + trend, 0.1, 0.85))
            ndwi = float(np.clip(ndwi_base + rng.normal(0, 0.02) + trend * 0.5, -0.3, 0.3))
            # stress increases as NDVI drops
            stress_prob = float(np.clip(1.0 - ndvi + rng.normal(0, 0.05), 0.0, 1.0))
            rows.append({
                "community": c,
                "date": d,
                "NDVI": round(ndvi, 3),
                "NDWI": round(ndwi, 3),
                "stress_prob": round(stress_prob, 3),
            })
    return pd.DataFrame(rows)


# ── Map figure builder ────────────────────────────────────────────────────────

def build_map(gdf: gpd.GeoDataFrame, index_col: str = "NDVI") -> go.Figure:
    import json

    gdf = gdf.copy()

    if index_col not in gdf.columns:
        index_col = "NDVI"

    # Build GeoJSON with feature IDs = community name so locations can match
    # Keep only geometry + essential columns to avoid ndarray serialisation issues
    cols_to_keep = [c for c in ["name", "NDVI", "NDWI", "stress_prob", "status"]
                    if c in gdf.columns]
    geojson = json.loads(gdf[cols_to_keep + ["geometry"]].to_json())
    for feature in geojson["features"]:
        feature["id"] = feature["properties"]["name"]

    # Colour scale and range per index
    if index_col == "NDVI":
        colorscale = [[0, "#E74C3C"], [0.5, "#F39C12"], [1, "#27AE60"]]
        zmin, zmax = 0.1, 0.8
    elif index_col == "NDWI":
        colorscale = [[0, "#E74C3C"], [0.5, "#F39C12"], [1, "#27AE60"]]
        zmin, zmax = -0.3, 0.3
    else:  # stress_prob — higher = worse
        colorscale = [[0, "#27AE60"], [0.5, "#F39C12"], [1, "#E74C3C"]]
        zmin, zmax = 0.0, 1.0

    # Hover labels
    hover_texts = []
    for _, row in gdf.iterrows():
        ndvi = row.get("NDVI", float("nan"))
        ndwi = row.get("NDWI", float("nan"))
        sp   = row.get("stress_prob", float("nan"))
        stat = str(row.get("status", "N/D")).upper()
        lines = [f"<b>{row['name']}</b>"]
        if not (isinstance(ndvi, float) and np.isnan(ndvi)):
            lines.append(f"NDVI: {ndvi:.3f}")
        if not (isinstance(ndwi, float) and np.isnan(ndwi)):
            lines.append(f"NDWI: {ndwi:.3f}")
        if not (isinstance(sp, float) and np.isnan(sp)):
            lines.append(f"Estrés: {sp*100:.0f}%")
        lines.append(f"Estado: {stat}")
        hover_texts.append("<br>".join(lines))

    fig = go.Figure(go.Choroplethmap(
        geojson=geojson,
        locations=gdf["name"].tolist(),
        z=gdf[index_col].tolist(),
        colorscale=colorscale,
        zmin=zmin,
        zmax=zmax,
        marker_opacity=0.70,
        marker_line_width=1.5,
        marker_line_color="white",
        hovertext=hover_texts,
        hoverinfo="text",
        colorbar=dict(
            title=dict(text=index_col, side="right"),
            thickness=12,
            len=0.6,
            x=1.0,
        ),
    ))

    fig.update_layout(
        map_style=config.MAP_STYLE,
        map_zoom=config.MAP_ZOOM,
        map_center=config.MAP_CENTER,
        margin={"r": 0, "t": 0, "l": 0, "b": 0},
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
            pt = click_data["points"][0]
            # go.Choroplethmapbox puts the feature id in "location"
            return pt.get("location") or pt.get("hovertext")
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
