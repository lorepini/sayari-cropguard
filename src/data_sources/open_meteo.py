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
TIMEZONE = "America/Lima"
DAILY_VARS = "precipitation_sum,et0_fao_evapotranspiration"


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


if __name__ == "__main__":
    # Smoke test against Cayalti
    print("Forecast (Cayalti, next 7 days):")
    print(fetch_forecast(-6.91, -79.51, days=7))
    print()
    print("Historical (Cayalti, last 10 days):")
    end = dt.date.today() - dt.timedelta(days=2)
    start = end - dt.timedelta(days=10)
    print(fetch_historical(-6.91, -79.51, start, end))
