"""
Peru Coastal ENSO Index — ICEN (Índice Costero El Niño).

The ICEN is Peru's official coastal ENSO indicator, published by ENFEN
(Estudio Nacional del Fenómeno El Niño), the inter-agency ENSO advisory
group of SENAMHI, IMARPE, IGP, ANA, DHN, and INDECI.

Why ICEN instead of the global ONI
------------------------------------
The global ONI measures SST anomalies in the Niño 3.4 region (5°N-5°S,
170°W-120°W), far west of Peru. The ICEN measures Niño 1+2 (0-10°S,
80-90°W) — the Peruvian coast itself. The two indices regularly diverge:

  • 2017 "El Niño Costero": ICEN peaked at +2.6 °C (intense), while
    global ONI stayed near 0 (neutral). Lambayeque suffered catastrophic
    flooding and crop losses.
  • 1997-98 El Niño: both ICEN and ONI extreme — consistent.

For the Sayariy parcel in Cayaltí, ICEN is the correct risk index.
The NGO confirmed no global El Niño events were "felt locally" even during
years of elevated ONI — exactly what the ICEN divergence explains.

Data source
-----------
NOAA CPC publishes the Niño 1+2 SST and anomaly series in the same
plain-text infrastructure as the ONI file. No auth required.

ENFEN classification thresholds (lower than global ONI):
  Anomaly ≥ +2.0 °C  → Extraordinario
  Anomaly ≥ +1.0 °C  → Fuerte
  Anomaly ≥ +0.4 °C  → El Niño Costero (débil / moderado)
  |Anomaly| < 0.4 °C → Neutral
  Anomaly ≤ -0.4 °C  → La Niña Costera

Reference: ENFEN (2012). "Definición operacional de los eventos El Niño y
La Niña y sus magnitudes en la costa del Perú." Nota Técnica ENFEN.
Verify citation at senamhi.gob.pe/main.php?dp=enfen before any deliverable.
"""
from __future__ import annotations

import io
from typing import Literal

import requests
import pandas as pd

from ._cache import ttl_cache

NINO12_URL = "https://www.cpc.ncep.noaa.gov/data/indices/sstoi.indices"

IcenState = Literal[
    "el_nino_extraordinario",
    "el_nino_fuerte",
    "el_nino_costero",
    "neutral",
    "la_nina_costera",
]


# Same source as ONI — update monthly, 6 h cache is plenty.
@ttl_cache(6 * 60 * 60)
def fetch_nino12() -> pd.DataFrame:
    """Fetch the full Niño 1+2 SST + anomaly series (1950-present).

    Columns: date (mid-month), year, month, nino12_sst_c, nino12_anom_c.
    """
    r = requests.get(NINO12_URL, timeout=30)
    r.raise_for_status()
    return _parse_nino12(r.text)


def _parse_nino12(text: str) -> pd.DataFrame:
    # File has 10 columns, 4 pairs of (SST, ANOM) for regions 1+2, 3, 4, 3.4
    # Header: YR  MON  NINO1+2  ANOM  NINO3  ANOM  NINO4  ANOM  NINO3.4  ANOM
    # Rename explicitly because "ANOM" appears 4 times.
    col_names = [
        "year", "month",
        "nino12_sst_c", "nino12_anom_c",
        "nino3_sst_c",  "nino3_anom_c",
        "nino4_sst_c",  "nino4_anom_c",
        "nino34_sst_c", "nino34_anom_c",
    ]
    df = pd.read_csv(io.StringIO(text), sep=r"\s+", skiprows=1, names=col_names)
    df = df.dropna(subset=["year", "month", "nino12_anom_c"])
    df["year"]  = df["year"].astype(int)
    df["month"] = df["month"].astype(int)
    df["date"]  = pd.to_datetime(dict(year=df["year"], month=df["month"], day=15))
    return df[["date", "year", "month", "nino12_sst_c", "nino12_anom_c"]].reset_index(drop=True)


def classify_icen(anom_c: float) -> IcenState:
    """Single-value ICEN classification using ENFEN thresholds."""
    if anom_c >= 2.0:
        return "el_nino_extraordinario"
    if anom_c >= 1.0:
        return "el_nino_fuerte"
    if anom_c >= 0.4:
        return "el_nino_costero"
    if anom_c <= -0.4:
        return "la_nina_costera"
    return "neutral"


def latest_icen() -> tuple[pd.Timestamp, float, IcenState]:
    """Return (date, nino12_anom_c, icen_state) for the most recent month."""
    df = fetch_nino12()
    last = df.iloc[-1]
    anom = float(last["nino12_anom_c"])
    return last["date"], anom, classify_icen(anom)


def icen_label_es(state: IcenState) -> str:
    return {
        "el_nino_extraordinario": "El Niño Costero Extraordinario",
        "el_nino_fuerte":         "El Niño Costero Fuerte",
        "el_nino_costero":        "El Niño Costero",
        "neutral":                "Neutro",
        "la_nina_costera":        "La Niña Costera",
    }.get(state, state)


def icen_risk_es(state: IcenState) -> str:
    """Plain-Spanish risk explanation for Vista Sencilla."""
    return {
        "el_nino_extraordinario": (
            "Riesgo muy alto de lluvias intensas y huaicos en la cuenca alta. "
            "El pozo podría recibir mucha recarga, pero también riesgo de inundación."
        ),
        "el_nino_fuerte": (
            "Riesgo alto de lluvias fuertes en enero-febrero. "
            "Monitoree el nivel del pozo con frecuencia."
        ),
        "el_nino_costero": (
            "Condiciones cálidas en la costa. Posibles lluvias por encima de lo normal. "
            "Buena recarga esperada."
        ),
        "neutral": (
            "Condiciones normales. Sin anomalía costera significativa."
        ),
        "la_nina_costera": (
            "Costa más fría de lo normal. Posible sequía en los Andes. "
            "Menor recarga al acuífero — vigile el nivel del pozo."
        ),
    }.get(state, "Estado desconocido.")


if __name__ == "__main__":
    df = fetch_nino12()
    print(f"Rows: {len(df)}, range: {df['date'].min().date()} → {df['date'].max().date()}")
    print("\nLast 6 months:")
    print(df.tail(6).to_string(index=False))
    date, anom, state = latest_icen()
    print(f"\nLatest ICEN: {date.date()}  Niño1+2 ANOM={anom:+.2f} °C  → {icen_label_es(state)}")
