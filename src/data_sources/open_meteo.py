"""
Open-Meteo client — daily precipitation + ET0 (FAO).
Free, no auth, no rate-limit relevant for daily polls.

Forecast endpoint: api.open-meteo.com/v1/forecast (up to 16 days ahead)
Archive endpoint:  archive-api.open-meteo.com/v1/archive (1940-present)
"""
from __future__ import annotations

import datetime as dt
import requests
import pandas as pd

from ._cache import ttl_cache

# Forecast values change hourly upstream; refreshing every 10 min is plenty
# for the dashboard. Historical archives are static — cache 6 h.
_FORECAST_TTL_S = 10 * 60
_ARCHIVE_TTL_S = 6 * 60 * 60
_ENSEMBLE_TTL_S = 30 * 60

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
TIMEZONE = "America/Lima"
# Used for multi-point basin calls — keep minimal to avoid rate limits (10 pts × call)
DAILY_VARS = "precipitation_sum,et0_fao_evapotranspiration"
# Extended single-site variables for the Sayariy parcel (forecast)
# Note: vapour_pressure_deficit is hourly-only in Open-Meteo — we derive VPD
# from tmax + rh_min using the FAO-56 Magnus formula (more accurate anyway).
EXTENDED_FORECAST_VARS = [
    "precipitation_sum",
    "et0_fao_evapotranspiration",
    "relative_humidity_2m_max",
    "relative_humidity_2m_min",
    "shortwave_radiation_sum",
]
# Extended single-site variables for the ERA5 archive
# Note: soil moisture is only available as hourly forecast, not in the daily
# ERA5 archive — use fetch_soil_moisture_forecast() for that signal.
EXTENDED_ARCHIVE_VARS = [
    "precipitation_sum",
    "et0_fao_evapotranspiration",
    "relative_humidity_2m_max",
    "relative_humidity_2m_min",
    "shortwave_radiation_sum",
]


def _compute_vpd(tmax_c: "pd.Series", rh_min_pct: "pd.Series") -> "pd.Series":
    """Vapour pressure deficit at peak stress (kPa) — FAO-56 Magnus formula.

    VPD = es(Tmax) × (1 - RH_min/100)
    es(T) = 0.6108 × exp(17.27 × T / (T + 237.3))  [kPa]

    Using Tmax × RH_min gives the *highest* daily VPD (worst-case stress),
    which is the agronomically relevant value for maracuyá stomatal closure.
    """
    import numpy as np
    es = 0.6108 * np.exp(17.27 * tmax_c / (tmax_c + 237.3))
    return es * (1.0 - rh_min_pct / 100.0)

# Ensemble model specs:
#   gfs_seamless    — 30 members, up to 35 days, NOAA NCEP GFS ensemble (GEFS).
#   icon_seamless   — 39 members, up to 14 days, DWD ICON-D2/EU.
#   ecmwf_ifs025    — 50 members, up to 15 days, ECMWF IFS ensemble.
#   gem_global      — 20 members, up to 16 days, ECCC GEM.
ENSEMBLE_DEFAULT_MODEL = "gfs_seamless"
ENSEMBLE_MAX_DAYS = 35


@ttl_cache(_FORECAST_TTL_S)
def fetch_forecast(lat: float, lon: float, days: int = 14) -> pd.DataFrame:
    """Daily precipitation + ET0 forecast for the next `days` days."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": DAILY_VARS,
        "forecast_days": days,
        "timezone": TIMEZONE,
    }
    r = requests.get(FORECAST_URL, params=params, timeout=30)
    r.raise_for_status()
    return _to_dataframe(r.json())


@ttl_cache(_FORECAST_TTL_S)
def fetch_weather_forecast(lat: float, lon: float, days: int = 14) -> pd.DataFrame:
    """Unified daily weather forecast (Open-Meteo, no auth, free).

    Returns columns: date, tmax_c, tmin_c, precip_mm, wind_max_kmh,
    precip_prob_max_pct, et0_mm, rh_max_pct, rh_min_pct,
    solar_rad_mj_m2, vpd_max_kpa.

    Open-Meteo free forecast caps at 16 days — caller should clamp.
    New columns (humidity, solar, VPD) enable crop disease-risk scoring and
    more accurate heat-stress detection for maracuyá.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": ",".join(EXTENDED_FORECAST_VARS + [
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_probability_max",
            "wind_speed_10m_max",
        ]),
        "forecast_days": min(days, 16),
        "timezone": TIMEZONE,
    }
    r = requests.get(FORECAST_URL, params=params, timeout=30)
    r.raise_for_status()
    d = r.json()["daily"]
    n = len(d["time"])
    df = pd.DataFrame({
        "date":               pd.to_datetime(d["time"]).date,
        "tmax_c":             d["temperature_2m_max"],
        "tmin_c":             d["temperature_2m_min"],
        "precip_mm":          d.get("precipitation_sum",             [0]    * n),
        "precip_prob_max_pct":d.get("precipitation_probability_max", [None] * n),
        "wind_max_kmh":       d.get("wind_speed_10m_max",            [None] * n),
        "et0_mm":             d.get("et0_fao_evapotranspiration",    [None] * n),
        "rh_max_pct":         d.get("relative_humidity_2m_max",      [None] * n),
        "rh_min_pct":         d.get("relative_humidity_2m_min",      [None] * n),
        "solar_rad_mj_m2":    d.get("shortwave_radiation_sum",       [None] * n),
    })
    # Derive VPD from tmax + rh_min (FAO-56 Magnus formula)
    df["vpd_max_kpa"] = _compute_vpd(df["tmax_c"], df["rh_min_pct"].fillna(50.0))
    return df


def fetch_temperature_forecast(lat: float, lon: float, days: int = 14) -> pd.DataFrame:
    """Daily max + min air temperature only — kept for backwards compatibility
    with `_build_heat_card` etc. Prefer `fetch_weather_forecast` for new code.
    """
    df = fetch_weather_forecast(lat, lon, days=days)
    return df[["date", "tmax_c", "tmin_c"]]


@ttl_cache(_ARCHIVE_TTL_S)
def fetch_historical(lat: float, lon: float, start: dt.date, end: dt.date) -> pd.DataFrame:
    """Daily precipitation + ET0 archive for the date range [start, end]."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": DAILY_VARS,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "timezone": TIMEZONE,
    }
    r = requests.get(ARCHIVE_URL, params=params, timeout=60)
    r.raise_for_status()
    return _to_dataframe(r.json())


@ttl_cache(_ARCHIVE_TTL_S)
def fetch_extended_historical(
    lat: float, lon: float, start: dt.date, end: dt.date
) -> pd.DataFrame:
    """Extended ERA5 archive for a single site — full meteorological set.

    Use for the Sayariy parcel (not the 10-point basin grid — that stays
    minimal to avoid rate-limit fan-out). Returns:

      date, precip_mm, et0_mm, rh_max_pct, rh_min_pct,
      solar_rad_mj_m2, vpd_max_kpa,
      soil_moisture_0_7cm_m3m3, soil_moisture_7_28cm_m3m3

    soil_moisture columns are ERA5-Land volumetric water content (m³/m³).
    Typical field-capacity range for alluvial sandy loam: 0.25–0.35 m³/m³.
    Values below ~0.15 m³/m³ indicate water stress in the root zone.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": ",".join(EXTENDED_ARCHIVE_VARS),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "timezone": TIMEZONE,
    }
    r = requests.get(ARCHIVE_URL, params=params, timeout=60)
    r.raise_for_status()
    d = r.json()["daily"]
    n = len(d["time"])
    return pd.DataFrame({
        "date":             pd.to_datetime(d["time"]).date,
        "precip_mm":        d.get("precipitation_sum",          [None] * n),
        "et0_mm":           d.get("et0_fao_evapotranspiration", [None] * n),
        "rh_max_pct":       d.get("relative_humidity_2m_max",   [None] * n),
        "rh_min_pct":       d.get("relative_humidity_2m_min",   [None] * n),
        "solar_rad_mj_m2":  d.get("shortwave_radiation_sum",    [None] * n),
    })


@ttl_cache(_FORECAST_TTL_S)
def fetch_soil_moisture_forecast(
    lat: float, lon: float, days: int = 7
) -> pd.DataFrame:
    """Daily mean soil moisture from hourly forecast (Open-Meteo, free).

    Returns columns: date, soil_moisture_0_1cm_m3m3, soil_moisture_1_3cm_m3m3,
    soil_moisture_3_9cm_m3m3.

    Interpretation for Cayaltí alluvial sandy loam:
      > 0.25 m³/m³  — adequate (field capacity ~0.30)
      0.15–0.25     — monitor; root zone drying
      < 0.15        — stress threshold for most crops

    Note: soil moisture is forecast-only in Open-Meteo (not in ERA5 archive).
    Use NASA POWER or Sentinel-1 SAR for historical soil moisture.
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "soil_moisture_0_to_1cm,soil_moisture_1_to_3cm,soil_moisture_3_to_9cm",
        "forecast_days": min(days, 16),
        "timezone": TIMEZONE,
    }
    r = requests.get(FORECAST_URL, params=params, timeout=30)
    r.raise_for_status()
    h = r.json()["hourly"]
    hourly = pd.DataFrame({
        "dt":  pd.to_datetime(h["time"]),
        "sm0": h["soil_moisture_0_to_1cm"],
        "sm1": h["soil_moisture_1_to_3cm"],
        "sm3": h["soil_moisture_3_to_9cm"],
    })
    hourly["date"] = hourly["dt"].dt.date
    daily = hourly.groupby("date", as_index=False).agg(
        soil_moisture_0_1cm_m3m3=("sm0", "mean"),
        soil_moisture_1_3cm_m3m3=("sm1", "mean"),
        soil_moisture_3_9cm_m3m3=("sm3", "mean"),
    )
    return daily


def _to_dataframe(payload: dict) -> pd.DataFrame:
    daily = payload["daily"]
    df = pd.DataFrame({
        "date": pd.to_datetime(daily["time"]).date,
        "precip_mm": daily["precipitation_sum"],
        "et0_mm": daily["et0_fao_evapotranspiration"],
    })
    return df


@ttl_cache(_ENSEMBLE_TTL_S)
def fetch_ensemble_forecast(
    lat: float,
    lon: float,
    days: int = ENSEMBLE_MAX_DAYS,
    model: str = ENSEMBLE_DEFAULT_MODEL,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Probabilistic daily forecast — full ensemble for precipitation and ET0.

    Returns (precip_df, et0_df) where each has columns:
      date | member_00 | member_01 | ... | member_NN
    Each `member_NN` column is one ensemble trajectory (mm/day for precip,
    mm/day for et0). The deterministic control run is `member_00`.

    Use these to compute real percentile bands (P10/P50/P90) on any downstream
    quantity, instead of synthetic uncertainty assumptions.
    """
    days = min(days, ENSEMBLE_MAX_DAYS)
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": DAILY_VARS,
        "forecast_days": days,
        "models": model,
        "timezone": TIMEZONE,
    }
    r = requests.get(ENSEMBLE_URL, params=params, timeout=45)
    r.raise_for_status()
    daily = r.json()["daily"]
    dates = pd.to_datetime(daily["time"]).date

    def _stack(prefix: str) -> pd.DataFrame:
        # The deterministic control run uses the bare key, then memberNN keys
        cols: dict[str, list] = {}
        if prefix in daily:
            cols["member_00"] = daily[prefix]
        member_keys = sorted(k for k in daily if k.startswith(prefix + "_member"))
        for k in member_keys:
            n = int(k.split("_member")[1])
            cols[f"member_{n:02d}"] = daily[k]
        df = pd.DataFrame({"date": dates, **cols})
        # Replace nulls with 0 (precip) / climatology (et0) after the fact
        return df

    precip_df = _stack("precipitation_sum")
    et0_df = _stack("et0_fao_evapotranspiration")
    return precip_df, et0_df


if __name__ == "__main__":
    # Smoke test against Cayalti
    print("Forecast (Cayalti, next 7 days):")
    print(fetch_forecast(-6.91, -79.51, days=7))
    print()
    print("Historical (Cayalti, last 10 days):")
    end = dt.date.today() - dt.timedelta(days=2)
    start = end - dt.timedelta(days=10)
    print(fetch_historical(-6.91, -79.51, start, end))
