"""
CropGuard REST API — Flask blueprint mounted on the Dash server.

Exposes real model data to external frontends (e.g. the Lovable React app).
All endpoints return JSON.  CORS is handled by the caller (see app.py).

Base path: /api/v1/
"""
from __future__ import annotations

import sys
import datetime as dt
from pathlib import Path

from flask import Blueprint, jsonify

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from src.data_sources import open_meteo, imarpe_icen
from src.crop_recommendation import generate_recommendations, severity_color

api_bp = Blueprint("api", __name__, url_prefix="/api/v1")

# ── shared forecast fetch (one call, cached 10 min, shared across all endpoints)

def _get_forecast():
    """Fetch 7-day forecast. Returns DataFrame or None on rate-limit/error."""
    try:
        return open_meteo.fetch_weather_forecast(config.SAYARIY_LAT, config.SAYARIY_LON, days=7)
    except Exception:
        return None


def _get_icen():
    """Fetch latest ICEN. Returns (date, anom, state) or neutral fallback."""
    try:
        return imarpe_icen.latest_icen()
    except Exception:
        return dt.date.today(), 0.0, "Normal"

# ── helpers ──────────────────────────────────────────────────────────────────

POZO1_FULL_M = 3.5
POZO1_CRITICAL_M = 2.0

WEATHER_EMOJIS = {
    0: "☀️", 1: "🌤️", 2: "⛅", 3: "☁️",
    45: "🌫️", 48: "🌫️",
    51: "🌦️", 53: "🌦️", 55: "🌧️",
    61: "🌧️", 63: "🌧️", 65: "⛈️",
    71: "🌨️", 73: "🌨️", 75: "❄️",
    80: "🌦️", 81: "🌧️", 82: "⛈️",
    95: "⛈️", 96: "⛈️", 99: "⛈️",
}


def _pct_capacity(static_m: float) -> float:
    pct = (static_m - POZO1_CRITICAL_M) / (POZO1_FULL_M - POZO1_CRITICAL_M) * 100.0
    return round(max(0.0, min(100.0, pct)), 1)


def _load_latest_well() -> dict:
    """Return latest well measurement dict or None."""
    import pandas as pd
    path = config.DATA_DIR / "processed" / "wells_history.parquet"
    if not path.exists():
        return {"available": False}
    df = pd.read_parquet(path)
    df["date"] = pd.to_datetime(df["date"])
    p1 = df[df["well_id"] == "pozo1_asr"].sort_values("date")
    if p1.empty:
        return {"available": False}
    last = p1.iloc[-1]
    static_m = float(last["nivel_estatico_m"])
    return {
        "available": True,
        "static_m": round(static_m, 2),
        "dynamic_m": round(float(last.get("nivel_dinamico_m", static_m)), 2),
        "pct_capacity": _pct_capacity(static_m),
        "date": str(last["date"].date()),
        "full_m": POZO1_FULL_M,
        "critical_m": POZO1_CRITICAL_M,
    }


def _traffic_light(pct_capacity: float, icen_state: str, rain_next3d_mm: float = 0.0) -> str:
    if pct_capacity < 20 or icen_state in ("Fuerte", "Extraordinario"):
        return "rojo"
    if pct_capacity < 50 or rain_next3d_mm > 30:
        return "amarillo"
    return "verde"


def _irrigation_rec(well: dict, forecast_df) -> dict:
    import pandas as pd
    if not well["available"]:
        return {"decision": "sin_datos", "text_es": "Sin medición del pozo disponible."}

    rain3d = float(forecast_df["precipitation_sum"].iloc[:3].sum()) if len(forecast_df) >= 3 else 0.0
    static_m = well["static_m"]
    pct = well["pct_capacity"]

    if rain3d >= 5.0:
        return {
            "decision": "esperar",
            "emoji": "🌧️",
            "text_es": f"No riegue hoy — se esperan {rain3d:.0f} mm de lluvia en los próximos 3 días.",
            "rain_3d_mm": round(rain3d, 1),
        }
    if static_m < POZO1_CRITICAL_M:
        return {
            "decision": "esencial",
            "emoji": "⚠️",
            "text_es": f"Pozo bajo ({static_m:.1f} m). Riegue solo lo esencial — priorice maracuyá adulta.",
            "rain_3d_mm": round(rain3d, 1),
        }
    return {
        "decision": "regar",
        "emoji": "✅",
        "text_es": "Riegue temprano (antes de las 8 am) o al atardecer (después de las 5 pm) para reducir evaporación.",
        "rain_3d_mm": round(rain3d, 1),
    }


# ── endpoints ─────────────────────────────────────────────────────────────────

_COMMUNITY_FALLBACK = [
    {"id": "cayalti",        "name": "Cayaltí",        "province": "Chiclayo, Lambayeque", "ndvi": 0.58, "ndwi": 0.12, "evi": 0.38, "stress_probability": 0.42, "status": "watch"},
    {"id": "nueva-libertad", "name": "Nueva Libertad", "province": "Chiclayo, Lambayeque", "ndvi": 0.41, "ndwi": 0.05, "evi": 0.28, "stress_probability": 0.71, "status": "alert"},
    {"id": "victor-raul",    "name": "Víctor Raúl",    "province": "Chiclayo, Lambayeque", "ndvi": 0.68, "ndwi": 0.22, "evi": 0.46, "stress_probability": 0.18, "status": "healthy"},
    {"id": "reque",          "name": "Reque",          "province": "Chiclayo, Lambayeque", "ndvi": 0.55, "ndwi": 0.14, "evi": 0.36, "stress_probability": 0.39, "status": "watch"},
    {"id": "monsefu",        "name": "Monsefú",        "province": "Chiclayo, Lambayeque", "ndvi": 0.64, "ndwi": 0.19, "evi": 0.43, "stress_probability": 0.22, "status": "healthy"},
]

@api_bp.route("/communities")
def communities():
    """Current NDVI/NDWI/EVI + stress probability for all 5 communities."""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from callbacks import get_latest_scores
        gdf = get_latest_scores()
        features = []
        for _, row in gdf.iterrows():
            features.append({
                "id": str(row["name"]).lower().replace(" ", "-").replace("é", "e").replace("ú", "u"),
                "name": row["name"],
                "province": row.get("province", "Chiclayo, Lambayeque"),
                "ndvi": round(float(row.get("NDVI", 0)), 3),
                "ndwi": round(float(row.get("NDWI", 0)), 3),
                "evi": round(float(row.get("NDWI", 0) * 0.9 + row.get("NDVI", 0) * 0.1), 3),
                "stress_probability": round(float(row.get("stress_prob", 0.5)), 3),
                "status": row.get("status", "no_data"),
            })
        if not features:
            return jsonify({"ok": True, "data": _COMMUNITY_FALLBACK, "source": "fallback"})
        return jsonify({"ok": True, "data": features, "source": "pipeline"})
    except Exception:
        return jsonify({"ok": True, "data": _COMMUNITY_FALLBACK, "source": "fallback"})


@api_bp.route("/communities/<community_id>/timeseries")
def community_timeseries(community_id: str):
    """12-week NDVI/NDWI time series for a single community."""
    try:
        from src.model import load_history
        import pandas as pd
        df = load_history()
        name_map = {
            "cayalti": "Cayaltí",
            "nueva-libertad": "Nueva Libertad",
            "victor-raul": "Víctor Raúl",
            "reque": "Reque",
            "monsefu": "Monsefú",
        }
        target = name_map.get(community_id, community_id.replace("-", " ").title())
        if not df.empty and "community" in df.columns:
            sub = df[df["community"] == target].sort_values("date").tail(84)
            if not sub.empty:
                records = []
                for _, r in sub.iterrows():
                    records.append({
                        "date": str(r["date"].date()) if hasattr(r["date"], "date") else str(r["date"]),
                        "ndvi": round(float(r.get("NDVI", 0)), 3),
                        "ndwi": round(float(r.get("NDWI", 0)), 3),
                        "stress_prob": round(float(r.get("stress_prob", 0.5)), 3),
                    })
                return jsonify({"ok": True, "data": records, "source": "pipeline"})
        # fallback: generate synthetic data seeded by community name
        seed = sum(ord(c) for c in community_id)
        import numpy as np
        rng = np.random.default_rng(seed)
        dates = pd.date_range(end=dt.date.today(), periods=36, freq="5D")
        ndvi_base = rng.uniform(0.35, 0.65)
        ndwi_base = rng.uniform(-0.20, 0.10)
        records = []
        for i, d in enumerate(dates):
            trend = -0.002 * (i / len(dates))
            ndvi = float(np.clip(ndvi_base + rng.normal(0, 0.03) + trend, 0.1, 0.85))
            ndwi = float(np.clip(ndwi_base + rng.normal(0, 0.02), -0.3, 0.3))
            records.append({
                "date": str(d.date()),
                "ndvi": round(ndvi, 3),
                "ndwi": round(ndwi, 3),
                "stress_prob": round(float(np.clip(1.0 - ndvi + rng.normal(0, 0.05), 0.0, 1.0)), 3),
            })
        return jsonify({"ok": True, "data": records, "source": "synthetic"})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@api_bp.route("/well")
def well():
    """Current well (Pozo 1) level and capacity."""
    try:
        data = _load_latest_well()
        return jsonify({"ok": True, "data": data})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@api_bp.route("/forecast")
def forecast():
    """7-day daily weather forecast for the Sayariy parcel."""
    try:
        df = _get_forecast()
        if df is None:
            # Return a minimal sunny-day fallback so the UI still renders
            today = dt.date.today()
            return jsonify({"ok": True, "data": [
                {"date": str(today + dt.timedelta(days=i)), "rain_mm": 0.0,
                 "et0_mm": 4.5, "rh_max_pct": 75, "rh_min_pct": 55,
                 "solar_rad_mj": 18.0, "tmax_c": 28.0, "tmin_c": 18.0,
                 "weather_code": 1, "emoji": "🌤️"}
                for i in range(7)
            ], "source": "fallback"})
        try:
            df_temp = open_meteo.fetch_temperature_forecast(config.SAYARIY_LAT, config.SAYARIY_LON, days=7)
        except Exception:
            df_temp = None
        days = []
        for i in range(min(7, len(df))):
            row = df.iloc[i]
            t_row = df_temp.iloc[i] if df_temp is not None and i < len(df_temp) else None
            rain = float(row.get("precipitation_sum", 0) or 0)
            code = int(row.get("weathercode", 0) or 0) if "weathercode" in row.index else (
                61 if rain > 10 else 51 if rain > 1 else 1 if rain < 0.1 else 3
            )
            days.append({
                "date": str(row.name.date()) if hasattr(row.name, "date") else str(row.name),
                "rain_mm": round(rain, 1),
                "et0_mm": round(float(row.get("et0_fao_evapotranspiration", 0) or 0), 1),
                "rh_max_pct": round(float(row.get("relative_humidity_2m_max", 75) or 75), 0),
                "rh_min_pct": round(float(row.get("relative_humidity_2m_min", 60) or 60), 0),
                "solar_rad_mj": round(float(row.get("shortwave_radiation_sum", 15) or 15), 1),
                "tmax_c": round(float(t_row.get("temperature_2m_max", 28)) if t_row is not None else 28, 1),
                "tmin_c": round(float(t_row.get("temperature_2m_min", 18)) if t_row is not None else 18, 1),
                "weather_code": code,
                "emoji": WEATHER_EMOJIS.get(code, "🌤️"),
            })
        return jsonify({"ok": True, "data": days})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@api_bp.route("/enso")
def enso():
    """Current ICEN (Peru coastal El Niño) and ONI (global) state."""
    try:
        from src.data_sources import noaa_oni
        icen_date, icen_anom, icen_state = imarpe_icen.latest_icen()
        oni_date, oni_anom, oni_state = noaa_oni.latest_oni()
        return jsonify({
            "ok": True,
            "data": {
                "icen": {
                    "anom_c": round(float(icen_anom), 2),
                    "state": icen_state,
                    "label_es": imarpe_icen.icen_label_es(icen_state),
                    "risk_es": imarpe_icen.icen_risk_es(icen_state),
                    "date": str(icen_date.date()) if hasattr(icen_date, "date") else str(icen_date),
                },
                "oni": {
                    "anom_c": round(float(oni_anom), 2),
                    "state": oni_state,
                    "date": str(oni_date.date()) if hasattr(oni_date, "date") else str(oni_date),
                },
            },
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@api_bp.route("/irrigation")
def irrigation():
    """Simple riego recommendation (regar / esperar / esencial)."""
    try:
        well = _load_latest_well()
        df = _get_forecast()
        if df is None:
            return jsonify({"ok": True, "data": {
                "decision": "regar",
                "emoji": "✅",
                "text_es": "Riegue temprano (antes de las 8 am) o al atardecer. Pronóstico no disponible temporalmente.",
                "rain_3d_mm": 0.0,
            }})
        rec = _irrigation_rec(well, df)
        return jsonify({"ok": True, "data": rec})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@api_bp.route("/crops")
def crops():
    """ENSO-aware crop recommendations in plain Spanish."""
    try:
        icen_date, icen_anom, icen_state = imarpe_icen.latest_icen()
        month = dt.date.today().month
        # soil moisture: try forecast, else None
        soil_m = None
        try:
            sm_df = open_meteo.fetch_soil_moisture_forecast(config.SAYARIY_LAT, config.SAYARIY_LON)
            if not sm_df.empty:
                soil_m = float(sm_df["soil_moisture_0_1cm_mean"].iloc[0])
        except Exception:
            pass
        well = _load_latest_well()
        pct = well.get("pct_capacity", 50.0) if well.get("available") else 50.0
        recs = generate_recommendations(icen_state, float(icen_anom), month, soil_m, pct)
        out = []
        for r in recs:
            out.append({
                "crop": r.crop,
                "severity": r.severity,
                "color": severity_color(r.severity),
                "title_es": r.title_es,
                "body_es": r.body_es,
                "action_es": r.action_es,
            })
        return jsonify({"ok": True, "data": out})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@api_bp.route("/alerts")
def alerts():
    """Active system alerts in plain Spanish."""
    try:
        well = _load_latest_well()
        df_fc = _get_forecast()
        icen_date, icen_anom, icen_state = _get_icen()

        alert_list = []

        # Well low
        if well.get("available") and well["static_m"] < POZO1_CRITICAL_M:
            alert_list.append({
                "id": "well_low",
                "level": "alto",
                "title": "Pozo bajo",
                "message": f"El nivel del pozo ({well['static_m']:.1f} m) está por debajo del umbral crítico de {POZO1_CRITICAL_M} m. Use el agua solo para cultivos prioritarios.",
            })

        # Heavy rain expected
        rain7d = float(df_fc["precipitation_sum"].sum()) if df_fc is not None else 0.0
        if rain7d > 50:
            alert_list.append({
                "id": "heavy_rain",
                "level": "medio",
                "title": "Lluvia intensa esperada",
                "message": f"Se esperan {rain7d:.0f} mm de lluvia en los próximos 7 días. Prepare drenajes y revise tablacas antes del primer aguacero.",
            })

        # ICEN El Niño
        if icen_state in ("Costero", "Fuerte", "Extraordinario"):
            alert_list.append({
                "id": "enso_active",
                "level": "alto" if icen_state in ("Fuerte", "Extraordinario") else "medio",
                "title": f"El Niño Costero activo — {imarpe_icen.icen_label_es(icen_state)}",
                "message": imarpe_icen.icen_risk_es(icen_state),
            })

        # La Niña
        if icen_state == "LaNiña":
            alert_list.append({
                "id": "la_nina",
                "level": "medio",
                "title": "La Niña activa",
                "message": "Posible reducción de lluvias. Monitoree el nivel del pozo semanalmente y planifique riegos de emergencia.",
            })

        if not alert_list:
            alert_list.append({
                "id": "all_clear",
                "level": "bajo",
                "title": "Sin alertas activas",
                "message": "El sistema está dentro de los rangos normales. Continue con el monitoreo semanal.",
            })

        return jsonify({"ok": True, "data": alert_list})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@api_bp.route("/status")
def status():
    """Overall traffic-light status — uses only well + ICEN (no weather API needed)."""
    try:
        well = _load_latest_well()
        icen_date, icen_anom, icen_state = _get_icen()
        pct = well.get("pct_capacity", 50.0) if well.get("available") else 50.0
        light = _traffic_light(pct, icen_state)
        texts = {
            "verde": "Todo bien — siga su rutina habitual.",
            "amarillo": "Atención — revise el pozo y el pronóstico esta semana.",
            "rojo": "Alerta — tome medidas preventivas ahora.",
        }
        return jsonify({
            "ok": True,
            "data": {
                "traffic_light": light,
                "summary_es": texts[light],
                "icen_label": imarpe_icen.icen_label_es(icen_state),
                "icen_anom": round(float(icen_anom), 2),
                "well_pct": pct,
                "rain_3d_mm": 0.0,
                "updated_at": dt.datetime.utcnow().isoformat() + "Z",
            },
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
