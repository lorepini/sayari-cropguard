"""
Standardized Precipitation Index (SPI) — drought monitoring.

SPI is a single-number drought indicator (McKee et al. 1993, widely adopted
by WMO and Peru's SENAMHI). For a given accumulation window (e.g. 3 months):

    1. Compute the historical distribution of N-month rainfall sums at the
       same calendar window (e.g. all April-May-June periods 1990–2025).
    2. Fit a gamma distribution to that empirical sample.
    3. Transform the gamma distribution into a standard normal via
       SPI = Phi^{-1}( F_gamma(x) ),
       so SPI ~ N(0, 1) under climatology.

Interpretation (WMO):
    SPI ≥ +2.0   extremely wet
    SPI ≥ +1.0   moderately wet
    |SPI| < 1.0  near normal
    SPI ≤ -1.0   moderate drought
    SPI ≤ -1.5   severe drought
    SPI ≤ -2.0   extreme drought

Reference: McKee, T.B., Doesken, N.J., Kleist, J. (1993). The relationship
of drought frequency and duration to time scales. 8th Conf. Applied
Climatology, Anaheim. (Verify the citation against the original paper before
using in any deliverable.)
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats


# WMO interpretation bands
SPI_BANDS = (
    (2.0, "extremely wet"),
    (1.5, "very wet"),
    (1.0, "moderately wet"),
    (-1.0, "near normal"),
    (-1.5, "moderate drought"),
    (-2.0, "severe drought"),
    (-99.0, "extreme drought"),
)


@dataclass(frozen=True)
class SpiResult:
    spi: float
    band: str
    accumulation_mm: float
    climatology_mean_mm: float
    climatology_std_mm: float
    window_months: int
    end_date: dt.date
    n_climatology_years: int


def _classify(spi_value: float) -> str:
    if not np.isfinite(spi_value):
        return "no data"
    for threshold, label in SPI_BANDS[:3]:
        if spi_value >= threshold:
            return label
    if spi_value >= SPI_BANDS[3][0]:
        return SPI_BANDS[3][1]
    for threshold, label in SPI_BANDS[4:]:
        if spi_value >= threshold:
            return label
    return SPI_BANDS[-1][1]


def compute_spi(
    daily_rainfall: pd.DataFrame,
    end_date: dt.date,
    window_months: int = 3,
    min_climatology_years: int = 20,
) -> SpiResult:
    """Compute SPI-N at `end_date` from a long daily-rainfall series.

    Parameters
    ----------
    daily_rainfall : DataFrame with `date` and `precip_mm` columns covering
        a long period (≥20 years strongly recommended) up to `end_date`.
    end_date : reference date (the SPI ends here, looking back `window_months`).
    window_months : 3 (sub-seasonal) is standard for agricultural drought;
        6 for hydrological; 12 for long-term water resources.
    """
    df = daily_rainfall.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df["year_month"] = df["date"].dt.to_period("M")

    monthly = df.groupby("year_month")["precip_mm"].sum().to_frame("precip_mm")
    monthly = monthly.sort_index()

    # Rolling N-month accumulation
    monthly["accum_mm"] = monthly["precip_mm"].rolling(window=window_months,
                                                        min_periods=window_months).sum()

    # Latest accumulation up to end_date
    end_period = pd.Period(end_date, freq="M")
    if end_period not in monthly.index:
        raise ValueError(f"end_date {end_date} not in input series")
    current_accum = float(monthly.loc[end_period, "accum_mm"])

    if not np.isfinite(current_accum):
        return SpiResult(
            spi=float("nan"), band="insufficient data",
            accumulation_mm=current_accum,
            climatology_mean_mm=float("nan"),
            climatology_std_mm=float("nan"),
            window_months=window_months,
            end_date=end_date,
            n_climatology_years=0,
        )

    # Climatology: same calendar month, all prior years
    target_month = end_period.month
    climatology = monthly[
        (monthly.index.month == target_month)
        & (monthly.index < end_period)
        & monthly["accum_mm"].notna()
    ]["accum_mm"].to_numpy(dtype=float)

    if len(climatology) < min_climatology_years:
        # Fall back to a normal-distribution z-score with what we have
        if len(climatology) >= 5:
            mean = float(np.mean(climatology))
            sd = float(np.std(climatology, ddof=1))
            spi = (current_accum - mean) / sd if sd > 0 else 0.0
            band = _classify(spi)
            return SpiResult(spi, band, current_accum, mean, sd,
                              window_months, end_date, len(climatology))
        return SpiResult(
            spi=float("nan"), band="insufficient climatology",
            accumulation_mm=current_accum,
            climatology_mean_mm=float("nan"),
            climatology_std_mm=float("nan"),
            window_months=window_months,
            end_date=end_date,
            n_climatology_years=len(climatology),
        )

    # Gamma fit (drop zeros — gamma is undefined at 0; SPI handles this via
    # the standard "split distribution" approach: prob_zero from frequency,
    # gamma fit on the positive tail)
    positives = climatology[climatology > 0]
    prob_zero = 1.0 - len(positives) / len(climatology)
    if len(positives) < 5:
        # Fall back to normal z-score
        mean = float(np.mean(climatology))
        sd = float(np.std(climatology, ddof=1))
        spi = (current_accum - mean) / sd if sd > 0 else 0.0
        band = _classify(spi)
        return SpiResult(spi, band, current_accum, mean, sd,
                          window_months, end_date, len(climatology))

    # MLE for gamma
    shape, loc, scale = stats.gamma.fit(positives, floc=0)
    if current_accum <= 0:
        cdf = prob_zero / 2.0
    else:
        cdf = prob_zero + (1 - prob_zero) * stats.gamma.cdf(
            current_accum, shape, loc=loc, scale=scale
        )

    cdf = float(np.clip(cdf, 1e-6, 1 - 1e-6))
    spi = float(stats.norm.ppf(cdf))
    band = _classify(spi)

    return SpiResult(
        spi=spi, band=band,
        accumulation_mm=current_accum,
        climatology_mean_mm=float(np.mean(climatology)),
        climatology_std_mm=float(np.std(climatology, ddof=1)),
        window_months=window_months,
        end_date=end_date,
        n_climatology_years=len(climatology),
    )


def spi_emoji(spi_value: float) -> str:
    """Plain-Spanish-friendly emoji for the simple dashboard."""
    if not np.isfinite(spi_value):
        return "❓"
    if spi_value >= 1.5:
        return "🌧️"
    if spi_value >= 1.0:
        return "🌦️"
    if spi_value >= -1.0:
        return "🌤️"
    if spi_value >= -1.5:
        return "🌵"
    return "🔥"


def spi_band_es(band: str) -> str:
    """Spanish translation of WMO drought bands (for Vista Sencilla)."""
    return {
        "extremely wet": "extremadamente húmedo",
        "very wet": "muy húmedo",
        "moderately wet": "moderadamente húmedo",
        "near normal": "cerca de lo normal",
        "moderate drought": "sequía moderada",
        "severe drought": "sequía severa",
        "extreme drought": "sequía extrema",
        "no data": "sin datos",
        "insufficient data": "datos insuficientes",
        "insufficient climatology": "climatología insuficiente",
    }.get(band, band)
