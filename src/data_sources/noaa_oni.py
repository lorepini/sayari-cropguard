"""
NOAA Oceanic Nino Index (ONI) client.

The ONI is the rolling 3-month average of SST anomalies in the Nino 3.4 region.
- ANOM > +0.5 sustained 5+ months -> El Nino
- ANOM < -0.5 sustained 5+ months -> La Nina
- otherwise neutral

Source: NOAA CPC, public plain-text file, no auth.

Lambayeque coast is highly ENSO-sensitive: El Nino brings heavy rainfall and
flooding to the upper Zana basin, increasing aquifer recharge.
"""
from __future__ import annotations

import io
from typing import Literal

import requests
import pandas as pd

ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"

# DJF -> first of December of the prior year (mid = January)
SEASON_TO_MONTH = {
    "DJF": 1, "JFM": 2, "FMA": 3, "MAM": 4, "AMJ": 5, "MJJ": 6,
    "JJA": 7, "JAS": 8, "ASO": 9, "SON": 10, "OND": 11, "NDJ": 12,
}

EnsoState = Literal["el_nino", "la_nina", "neutral"]


def fetch_oni() -> pd.DataFrame:
    """Fetch the full ONI history (1950-present) as a DataFrame.

    Columns: date (mid-month of the 3-month season), seas, year, sst_c, anom_c.
    """
    r = requests.get(ONI_URL, timeout=30)
    r.raise_for_status()
    return parse_oni_text(r.text)


def parse_oni_text(text: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(text), sep=r"\s+")
    df.columns = [c.upper() for c in df.columns]
    df = df.rename(columns={"YR": "year", "TOTAL": "sst_c", "ANOM": "anom_c", "SEAS": "seas"})
    df["month"] = df["seas"].map(SEASON_TO_MONTH)
    df["date"] = pd.to_datetime(dict(year=df["year"], month=df["month"], day=15))
    return df[["date", "seas", "year", "sst_c", "anom_c"]].reset_index(drop=True)


def classify_state(anom_c: float, threshold: float = 0.5) -> EnsoState:
    """Single-value classification (instantaneous, not the official 5-month rule)."""
    if anom_c > threshold:
        return "el_nino"
    if anom_c < -threshold:
        return "la_nina"
    return "neutral"


def latest_state() -> tuple[pd.Timestamp, float, EnsoState]:
    df = fetch_oni()
    last = df.iloc[-1]
    return last["date"], float(last["anom_c"]), classify_state(float(last["anom_c"]))


if __name__ == "__main__":
    df = fetch_oni()
    print(f"Rows: {len(df)}, range: {df['date'].min().date()} -> {df['date'].max().date()}")
    print()
    print("Last 6 months:")
    print(df.tail(6).to_string(index=False))
    print()
    date, anom, state = latest_state()
    print(f"Latest: {date.date()}  ANOM={anom:+.2f}  -> {state.upper()}")
