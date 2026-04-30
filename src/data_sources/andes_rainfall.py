"""
Andes upper-Zana rainfall = recharge proxy for the Cayalti aquifer.

Open-Meteo's ERA5 archive serves the same physical signal as CHIRPS
(gridded daily precipitation, station+satellite blended, 1940-present)
without a GEE account.

The aquifer at SEV-02 is fed laterally from Rio Zana, which is fed by Andes
rainfall. We integrate rainfall over a multi-day window with a lag to model
the slow lateral seepage through the alluvial fan (~30-90 day characteristic).

We now sample MULTIPLE points across the upper Zaña basin polygon (3x3 grid
plus 1 representative headwater point) and average them — a basin-mean is a
more accurate recharge proxy than a single point, especially in mountainous
terrain where rainfall varies steeply with elevation. Single-point fetch is
kept as a fallback for backwards compatibility.
"""
from __future__ import annotations

import datetime as dt
import pandas as pd

from src.data_sources import open_meteo

# Representative Andes point in the upper Zana headwaters
# (Niepos area, Cajamarca side, ~2500 m elevation) — kept as fallback.
UPPER_BASIN_LAT = -6.72
UPPER_BASIN_LON = -79.05

# Multi-point sampling grid across the upper Zaña basin polygon
# (-79.40 → -78.70 lon, -6.95 → -6.50 lat). 3x3 evenly spaced grid +
# Niepos headwater point = 10 samples. Tradeoff: more points = better basin
# mean, but each point is one Open-Meteo call. 10 is a sensible balance.
BASIN_GRID: tuple[tuple[float, float], ...] = (
    (-6.95, -79.40), (-6.95, -79.05), (-6.95, -78.70),
    (-6.725, -79.40), (-6.725, -79.05), (-6.725, -78.70),
    (-6.50, -79.40), (-6.50, -79.05), (-6.50, -78.70),
    (UPPER_BASIN_LAT, UPPER_BASIN_LON),  # Niepos headwater
)


def fetch_upper_basin_history(start: dt.date, end: dt.date,
                              multipoint: bool = True) -> pd.DataFrame:
    """Daily basin-mean rainfall + ET0 over the upper Zaña basin.

    multipoint=True: average BASIN_GRID samples (10 points). Recommended.
    multipoint=False: single Niepos headwater point (legacy behaviour).

    Returns DataFrame with columns: date, andes_precip_mm, andes_et0_mm,
    plus 'andes_precip_mm_std' giving the across-basin standard deviation
    (a rough orographic-variability indicator) when multipoint is on.
    """
    if not multipoint:
        df = open_meteo.fetch_historical(UPPER_BASIN_LAT, UPPER_BASIN_LON, start, end)
        return df.rename(columns={"precip_mm": "andes_precip_mm",
                                  "et0_mm": "andes_et0_mm"})

    frames: list[pd.DataFrame] = []
    for lat, lon in BASIN_GRID:
        df = open_meteo.fetch_historical(lat, lon, start, end)
        df = df.assign(_pt=f"{lat:.3f},{lon:.3f}")
        frames.append(df)
    stacked = pd.concat(frames, ignore_index=True)
    grouped = stacked.groupby("date", as_index=False).agg(
        andes_precip_mm=("precip_mm", "mean"),
        andes_precip_mm_std=("precip_mm", "std"),
        andes_et0_mm=("et0_mm", "mean"),
    )
    return grouped


def fetch_upper_basin_forecast(days: int = 14,
                               multipoint: bool = True) -> pd.DataFrame:
    if not multipoint:
        df = open_meteo.fetch_forecast(UPPER_BASIN_LAT, UPPER_BASIN_LON, days=days)
        return df.rename(columns={"precip_mm": "andes_precip_mm",
                                  "et0_mm": "andes_et0_mm"})

    frames: list[pd.DataFrame] = []
    for lat, lon in BASIN_GRID:
        df = open_meteo.fetch_forecast(lat, lon, days=days)
        frames.append(df)
    stacked = pd.concat(frames, ignore_index=True)
    return stacked.groupby("date", as_index=False).agg(
        andes_precip_mm=("precip_mm", "mean"),
        andes_precip_mm_std=("precip_mm", "std"),
        andes_et0_mm=("et0_mm", "mean"),
    )


def fetch_upper_basin_ensemble_forecast(days: int = 35) -> pd.DataFrame:
    """Ensemble forecast at the headwater point (Niepos).

    Returns the per-member precipitation DataFrame from Open-Meteo's GFS
    ensemble. Used to propagate Andes rainfall uncertainty into the
    water-balance forecast. We sample the headwater point only — running 30
    members × 10 grid points = 300 trajectories is overkill and slow.
    """
    precip_df, _ = open_meteo.fetch_ensemble_forecast(
        UPPER_BASIN_LAT, UPPER_BASIN_LON, days=days,
    )
    member_cols = [c for c in precip_df.columns if c.startswith("member_")]
    return precip_df.rename(columns={c: f"andes_{c}" for c in member_cols})


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
