"""
Sub-seasonal forecast extension via ENSO-conditional climatology.

Open-Meteo's GFS ensemble caps at 35 days. To extend the forecast horizon for
the NGO-relevant question "what does the next planting season look like?" we
build days 36-90 from the historical ERA5 record, conditioned on the current
ENSO state.

Method
------
For each calendar day in the extension window:

    1. Look up the same day-of-year in every prior year of the archive.
    2. Filter to years where the contemporaneous ONI anomaly was in the same
       band as today (El Niño / Neutral / La Niña).
    3. Compute distribution percentiles (P10/P50/P90) of daily rainfall and
       ET₀ across that filtered sample.

This gives a probabilistic outlook that is honest about long-horizon
uncertainty (the bands are wide) and incorporates the dominant climate
modulator for Lambayeque (ENSO).

Caveats
-------
- Lambayeque is highly ENSO-sensitive (Bourrel et al. 2015 — verify before
  citing); conditioning on ONI alone misses local variability.
- The 36–90 day band is informative for *trend* (will the dry season be
  drier than usual?) but not for daily-precision irrigation planning.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.data_sources import noaa_oni


def classify_oni(anom: float) -> str:
    if anom > 0.5:
        return "el_nino"
    if anom < -0.5:
        return "la_nina"
    return "neutral"


@dataclass(frozen=True)
class SeasonalForecast:
    """Daily DataFrame with date, p10_precip_mm, p50_precip_mm, p90_precip_mm,
    p10_et0_mm, p50_et0_mm, p90_et0_mm columns."""
    df: pd.DataFrame
    enso_state: str
    n_analog_years: int
    horizon_days: int


def build_seasonal_extension(
    archive_daily: pd.DataFrame,
    start_date: dt.date,
    days: int,
    current_oni: float | None = None,
) -> SeasonalForecast:
    """Build a percentile-band forecast for `days` days starting at `start_date`.

    archive_daily : long daily DataFrame with `date`, `precip_mm`, `et0_mm`.
        Must cover at least 20 prior years for stable bands.
    start_date : first day of the extension window (typically end of the
        ensemble forecast horizon, ~35 days from today).
    days : how many days to extend (we cap at 90 — beyond, the conditional
        climatology becomes too noisy).
    current_oni : current ONI anomaly. If None, the latest NOAA ONI value
        is fetched live.
    """
    if current_oni is None:
        try:
            _, current_oni, _ = noaa_oni.latest_state()
        except Exception:
            current_oni = 0.0

    enso_state = classify_oni(current_oni)
    horizon = min(days, 90)

    df = archive_daily.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["doy"] = df["date"].dt.dayofyear
    df["year"] = df["date"].dt.year

    # Attach ONI anomaly to each day
    oni = noaa_oni.fetch_oni()[["date", "anom_c"]]
    oni = oni.rename(columns={"anom_c": "oni_anom"})
    oni["date"] = pd.to_datetime(oni["date"])
    df = pd.merge_asof(df.sort_values("date"),
                       oni.sort_values("date"),
                       on="date",
                       direction="backward")
    df["enso_state"] = df["oni_anom"].apply(
        lambda x: classify_oni(x) if pd.notna(x) else "neutral"
    )

    # Filter to analog ENSO years; if too few, fall back to all years
    analog = df[df["enso_state"] == enso_state]
    n_analog = analog["year"].nunique()
    if n_analog < 5:
        analog = df  # fallback: use full climatology

    # Build the extension window
    bands_rows = []
    for i in range(horizon):
        target = pd.Timestamp(start_date) + pd.Timedelta(days=i)
        doy = target.dayofyear
        # Use a 7-day window around the target DOY for sample size
        window = analog[(analog["doy"] >= doy - 3) & (analog["doy"] <= doy + 3)]
        if len(window) < 5:
            window = df[(df["doy"] >= doy - 3) & (df["doy"] <= doy + 3)]
        precip = window["precip_mm"].to_numpy(dtype=float)
        et0 = window["et0_mm"].to_numpy(dtype=float)
        bands_rows.append({
            "date": target.date(),
            "p10_precip_mm": float(np.percentile(precip, 10)) if len(precip) else 0.0,
            "p50_precip_mm": float(np.percentile(precip, 50)) if len(precip) else 0.0,
            "p90_precip_mm": float(np.percentile(precip, 90)) if len(precip) else 0.0,
            "p10_et0_mm": float(np.percentile(et0, 10)) if len(et0) else 0.0,
            "p50_et0_mm": float(np.percentile(et0, 50)) if len(et0) else 0.0,
            "p90_et0_mm": float(np.percentile(et0, 90)) if len(et0) else 0.0,
            "n_samples": int(len(window)),
        })

    out_df = pd.DataFrame(bands_rows)
    return SeasonalForecast(
        df=out_df,
        enso_state=enso_state,
        n_analog_years=n_analog,
        horizon_days=horizon,
    )


def seasonal_outlook_es(seasonal: SeasonalForecast,
                        normal_precip_mm_per_month: float = 30.0) -> str:
    """One-sentence Spanish outlook for the simple dashboard."""
    if seasonal.df.empty:
        return "Sin pronóstico estacional disponible."
    monthly_p50 = seasonal.df["p50_precip_mm"].sum() * (30 / max(1, len(seasonal.df)))
    label = {
        "el_nino": "con lluvias más fuertes de lo normal por El Niño",
        "la_nina": "más seca de lo normal por La Niña",
        "neutral": "cerca de lo normal",
    }.get(seasonal.enso_state, "sin tendencia clara")
    return (
        f"Próximas semanas: {label}. "
        f"Lluvia media estimada {monthly_p50:.0f} mm/mes "
        f"(rango P10–P90 según años análogos)."
    )
