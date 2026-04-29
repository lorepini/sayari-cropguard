"""
Andes upper-Zana rainfall = recharge proxy for the Cayalti aquifer.

Original plan was CHIRPS via Google Earth Engine, but Open-Meteo's archive
endpoint serves the same physical signal (gridded daily precipitation, ERA5
plus station data, going back to 1940) without a GEE account. We sample one
representative point in the upper Zana basin.

The aquifer at SEV-02 is fed laterally from Rio Zana, which is fed by Andes
rainfall. We integrate rainfall over a multi-day window with a lag to model
the slow lateral seepage through the alluvial fan (~30-90 day characteristic).

Refine with a true basin-mean (multi-point average) once we have the ANA
basin polygon. For now, a single point near Niepos / Oyotun captures the
seasonal signal cleanly.
"""
from __future__ import annotations

import datetime as dt
import pandas as pd

from src.data_sources import open_meteo

# Representative Andes point in the upper Zana headwaters
# (Niepos area, Cajamarca side, ~2500 m elevation)
UPPER_BASIN_LAT = -6.72
UPPER_BASIN_LON = -79.05


def fetch_upper_basin_history(start: dt.date, end: dt.date) -> pd.DataFrame:
    """Daily rainfall + ET0 at the upper Zana representative point.

    Returns DataFrame with columns: date, andes_precip_mm, andes_et0_mm.
    """
    df = open_meteo.fetch_historical(UPPER_BASIN_LAT, UPPER_BASIN_LON, start, end)
    return df.rename(columns={"precip_mm": "andes_precip_mm", "et0_mm": "andes_et0_mm"})


def fetch_upper_basin_forecast(days: int = 14) -> pd.DataFrame:
    df = open_meteo.fetch_forecast(UPPER_BASIN_LAT, UPPER_BASIN_LON, days=days)
    return df.rename(columns={"precip_mm": "andes_precip_mm", "et0_mm": "andes_et0_mm"})


def recharge_proxy(rainfall: pd.Series, window_days: int = 60, lag_days: int = 14) -> pd.Series:
    """Lagged rolling sum of upstream rainfall — proxy for Rio Zana discharge / recharge.

    Default 60-day window with 14-day lag captures the typical lateral seepage
    timescale through alluvial deposits. Tune `window_days` and `lag_days` during
    Phase-3 calibration against the 5 NGO measurements.
    """
    return rainfall.shift(lag_days).rolling(window=window_days, min_periods=1).sum()


if __name__ == "__main__":
    end = dt.date.today() - dt.timedelta(days=2)
    start = end - dt.timedelta(days=180)
    df = fetch_upper_basin_history(start, end)
    df["recharge_proxy_mm"] = recharge_proxy(df["andes_precip_mm"])
    print(f"Andes rainfall last 180 days at ({UPPER_BASIN_LAT}, {UPPER_BASIN_LON}):")
    print(f"  total: {df['andes_precip_mm'].sum():.0f} mm")
    print(f"  monthly mean: {df['andes_precip_mm'].sum() / 6:.0f} mm/month")
    print()
    print("Last 10 days:")
    print(df.tail(10).to_string(index=False))
