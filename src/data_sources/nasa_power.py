"""
NASA POWER — Prediction Of Worldwide Energy Resources.

Free REST API, no authentication. Specifically calibrated for agricultural
applications (community=AG). Provides daily solar irradiance, humidity, dew
point, and corrected precipitation going back to 1981 (~45 years), which is
significantly longer than Open-Meteo archive's ERA5-based coverage at this
location.

Primary use in CropGuard
------------------------
1. SPI climatology depth: the drought index (src/drought.py) needs ≥20 years
   of monthly rainfall. NASA POWER gives 45 years of corrected precipitation
   for the Sayariy parcel — more robust gamma-distribution fitting.

2. Solar irradiance validation: the Open-Meteo ET₀ is pre-computed from ERA5
   radiation. NASA POWER's ALLSKY_SFC_SW_DWN (surface downward shortwave
   radiation) is the same physical signal at agricultural grade. Cross-checking
   the two provides a sanity check on the ET₀ values driving our crop demand
   model.

3. Relative humidity ground-truth: RH2M from NASA POWER is independent of
   ERA5 and can be used to validate / supplement Open-Meteo humidity data,
   especially for disease-risk thresholds in maracuyá (Colletotrichum onset
   at sustained RH > 85%).

Key parameters
--------------
ALLSKY_SFC_SW_DWN  — all-sky surface shortwave radiation (MJ/m²/day)
RH2M               — relative humidity at 2 m (%)
T2MDEW             — dew point temperature at 2 m (°C)
PRECTOTCORR        — bias-corrected precipitation (mm/day)
T2M_MAX / T2M_MIN  — daily max/min temperature at 2 m (°C)

API docs: https://power.larc.nasa.gov/docs/services/api/
"""
from __future__ import annotations

import datetime as dt

import requests
import pandas as pd

from ._cache import ttl_cache

POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
COMMUNITY  = "AG"   # agricultural community — correct ET/radiation units

# Parameters to fetch. Add/remove from this list only — the parser is generic.
DEFAULT_PARAMETERS = [
    "ALLSKY_SFC_SW_DWN",   # solar irradiance (MJ/m²/day)
    "RH2M",                 # relative humidity at 2 m (%)
    "T2MDEW",               # dew point (°C)
    "PRECTOTCORR",          # bias-corrected precipitation (mm/day)
    "T2M_MAX",              # max temperature (°C)
    "T2M_MIN",              # min temperature (°C)
]

# NASA POWER data is reprocessed infrequently — 12 h cache is conservative.
_CACHE_TTL_S = 12 * 60 * 60


@ttl_cache(_CACHE_TTL_S)
def fetch_historical(
    lat: float,
    lon: float,
    start: dt.date,
    end: dt.date,
    parameters: tuple[str, ...] = tuple(DEFAULT_PARAMETERS),
) -> pd.DataFrame:
    """Daily NASA POWER data for [start, end] at (lat, lon).

    Returns a DataFrame with a `date` column plus one column per requested
    parameter, named in lowercase (e.g. allsky_sfc_sw_dwn, rh2m, …).
    Missing values (-999 sentinel) are replaced with NaN.

    Parameters are passed as a tuple (not list) so the TTL cache can hash them.
    """
    params = {
        "parameters": ",".join(parameters),
        "community":  COMMUNITY,
        "longitude":  lon,
        "latitude":   lat,
        "start":      start.strftime("%Y%m%d"),
        "end":        end.strftime("%Y%m%d"),
        "format":     "JSON",
    }
    r = requests.get(POWER_URL, params=params, timeout=60)
    r.raise_for_status()
    return _parse_response(r.json())


def _parse_response(payload: dict) -> pd.DataFrame:
    param_data: dict[str, dict] = payload["properties"]["parameter"]
    dates = None
    columns: dict[str, list] = {}
    for raw_name, daily_dict in param_data.items():
        col_name = raw_name.lower()
        if dates is None:
            dates = list(daily_dict.keys())
        values = [
            float(v) if v not in (-999, -999.0, "-999") else float("nan")
            for v in daily_dict.values()
        ]
        columns[col_name] = values

    if dates is None:
        return pd.DataFrame()

    df = pd.DataFrame({"date": pd.to_datetime(dates, format="%Y%m%d").date, **columns})
    return df.sort_values("date").reset_index(drop=True)


def fetch_spi_climatology(lat: float, lon: float) -> pd.DataFrame:
    """Fetch the longest available POWER series for SPI climatology.

    Retrieves corrected precipitation from 1981-01-01 to yesterday.
    Returned DataFrame has columns: date, precip_mm.
    Use this instead of Open-Meteo archive for drought.compute_spi() to get
    the full 45-year climatology baseline.
    """
    start = dt.date(1981, 1, 1)
    end   = dt.date.today() - dt.timedelta(days=1)
    df = fetch_historical(lat, lon, start, end, parameters=("PRECTOTCORR",))
    return df.rename(columns={"prectotcorr": "precip_mm"})[["date", "precip_mm"]]


def fetch_humidity_solar(lat: float, lon: float, days_back: int = 90) -> pd.DataFrame:
    """Recent humidity + solar irradiance for disease-risk and ET₀ validation.

    Returns: date, rh2m (%), t2mdew (°C), allsky_sfc_sw_dwn (MJ/m²/day).
    """
    end   = dt.date.today() - dt.timedelta(days=1)
    start = end - dt.timedelta(days=days_back)
    df = fetch_historical(
        lat, lon, start, end,
        parameters=("RH2M", "T2MDEW", "ALLSKY_SFC_SW_DWN"),
    )
    # Humidity disease-risk flag: maracuyá Colletotrichum onset sustained RH > 85%
    if "rh2m" in df.columns:
        df["high_humidity_risk"] = df["rh2m"] > 85.0
    return df


if __name__ == "__main__":
    from config import SAYARIY_LAT, SAYARIY_LON
    print("NASA POWER — last 30 days at Sayariy parcel:")
    df = fetch_humidity_solar(SAYARIY_LAT, SAYARIY_LON, days_back=30)
    print(df.tail(10).to_string(index=False))
    print(f"\nHigh-humidity-risk days: {df['high_humidity_risk'].sum()} of {len(df)}")
