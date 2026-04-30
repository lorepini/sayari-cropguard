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

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
TIMEZONE = "America/Lima"
DAILY_VARS = "precipitation_sum,et0_fao_evapotranspiration"

# Ensemble model specs:
#   gfs_seamless    — 30 members, up to 35 days, NOAA NCEP GFS ensemble (GEFS).
#   icon_seamless   — 39 members, up to 14 days, DWD ICON-D2/EU.
#   ecmwf_ifs025    — 50 members, up to 15 days, ECMWF IFS ensemble.
#   gem_global      — 20 members, up to 16 days, ECCC GEM.
ENSEMBLE_DEFAULT_MODEL = "gfs_seamless"
ENSEMBLE_MAX_DAYS = 35


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


def _to_dataframe(payload: dict) -> pd.DataFrame:
    daily = payload["daily"]
    df = pd.DataFrame({
        "date": pd.to_datetime(daily["time"]).date,
        "precip_mm": daily["precipitation_sum"],
        "et0_mm": daily["et0_fao_evapotranspiration"],
    })
    return df


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
