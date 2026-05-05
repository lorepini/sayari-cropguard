"""
One-time bootstrap of data/processed/wells_history.parquet from the NGO's
Chequeo.xlsx file.

Source: NGO Provided Info/Chequeo.xlsx — yearly well measurements 2022-2026.

Run once:
  python scripts/bootstrap_wells_history.py
"""
from pathlib import Path
import pandas as pd

# Hardcoded from Chequeo.xlsx (5 measurements). Dates corrected per NGO meeting
# 2026-05-05: "Las medidas se hacen en Junio de cada año" — the previous Dec-31
# placeholders were off by ~6 months. Using mid-June (06-15) for the 4 annual
# rows; the 2026-04-29 row is the off-cycle post-maintenance check.
#
# Extraction profile (NGO 2026-05-05): currently 50,000 L/day total
# (~30k crops + 20k household in normal months). Earlier years scaled with the
# planting build-out — kept as estimates. is_post_maintenance flags the Jan-7
# 2026 well cleaning (sand/roots removed) which restored dynamic level after
# Nov 2025 flow drop, so the residual at that observation should be flagged.
ROWS = [
    {"date": "2022-06-15", "nivel_estatico_m": 3.5, "nivel_dinamico_m": 2.2,
     "extraction_l_per_day": 0, "is_post_maintenance": False,
     "notes": "Primera medición NGO (sin siembra ni consumo, equivalente al baseline 2021)"},
    {"date": "2023-06-15", "nivel_estatico_m": 3.0, "nivel_dinamico_m": 2.2,
     "extraction_l_per_day": 500, "is_post_maintenance": False,
     "notes": "10 huertos pequeños (<10 plantas c/u); frutales sembrados Ene 2023"},
    {"date": "2024-06-15", "nivel_estatico_m": 2.8, "nivel_dinamico_m": 2.2,
     "extraction_l_per_day": 17500, "is_post_maintenance": False,
     "notes": "1300 maracuya + 17 huertos (10k L/día + 15k L interdiario)"},
    {"date": "2025-06-15", "nivel_estatico_m": 2.8, "nivel_dinamico_m": 2.0,
     "extraction_l_per_day": 50000, "is_post_maintenance": False,
     "notes": "3500 maracuya + 20 huertos; ~50k L/día total (30k crops + 20k viviendas)"},
    {"date": "2026-04-29", "nivel_estatico_m": 2.5, "nivel_dinamico_m": 1.8,
     "extraction_l_per_day": 50000, "is_post_maintenance": True,
     "notes": "Post-mantenimiento 2026-01-07 (extracción de arena/raíces que tapaban entradas tras caída de caudal Nov-2025); dinámico aún recuperándose"},
]

WELL_ID = "pozo1_asr"


def main():
    out = Path(__file__).resolve().parent.parent / "data" / "processed" / "wells_history.parquet"
    df = pd.DataFrame(ROWS)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["well_id"] = WELL_ID
    df["nivel_predicho_m"] = pd.NA
    df["nivel_predicho_low_m"] = pd.NA
    df["nivel_predicho_high_m"] = pd.NA
    df["is_forecast"] = False
    df["crop_demand_l_per_day"] = pd.NA
    df["recharge_proxy_mm"] = pd.NA
    df["local_rainfall_mm"] = pd.NA
    df["et0_mm"] = pd.NA
    df["oni_anom"] = pd.NA
    df["enso_state"] = pd.NA
    df["model_version"] = pd.NA
    df["source"] = "ngo_excel_chequeo"

    df = df[[
        "date", "well_id",
        "nivel_estatico_m", "nivel_dinamico_m",
        "nivel_predicho_m", "nivel_predicho_low_m", "nivel_predicho_high_m",
        "is_forecast", "is_post_maintenance",
        "extraction_l_per_day", "crop_demand_l_per_day",
        "recharge_proxy_mm", "local_rainfall_mm", "et0_mm",
        "oni_anom", "enso_state",
        "model_version", "source", "notes",
    ]]

    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    print(f"Wrote {len(df)} rows -> {out}")
    print(df[["date", "nivel_estatico_m", "nivel_dinamico_m", "extraction_l_per_day"]])


if __name__ == "__main__":
    main()
