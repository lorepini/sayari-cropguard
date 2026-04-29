"""
One-time bootstrap of data/processed/wells_history.parquet from the NGO's
Chequeo.xlsx file.

Source: NGO Provided Info/Chequeo.xlsx — yearly well measurements 2022-2026.

Run once:
  python scripts/bootstrap_wells_history.py
"""
from pathlib import Path
import pandas as pd

# Hardcoded from Chequeo.xlsx (5 yearly rows). Date convention: end of year
# since the Excel only gives a year. Refine if NGO provides exact dates.
ROWS = [
    {"date": "2022-12-31", "nivel_estatico_m": 3.5, "nivel_dinamico_m": 2.2,
     "extraction_l_per_day": 0,
     "notes": "Sin siembra ni consumo (baseline)"},
    {"date": "2023-12-31", "nivel_estatico_m": 3.0, "nivel_dinamico_m": 2.2,
     "extraction_l_per_day": 500,
     "notes": "10 huertos pequenos (<10 plantas c/u)"},
    {"date": "2024-12-31", "nivel_estatico_m": 2.8, "nivel_dinamico_m": 2.2,
     "extraction_l_per_day": 17500,
     "notes": "1300 maracuya + 17 huertos (10k L/dia + 15k L interdiario)"},
    {"date": "2025-12-31", "nivel_estatico_m": 2.8, "nivel_dinamico_m": 2.0,
     "extraction_l_per_day": 45000,
     "notes": "3500 maracuya + 20 huertos (30k L/dia + 30k L interdiario)"},
    {"date": "2026-04-29", "nivel_estatico_m": 2.5, "nivel_dinamico_m": 1.8,
     "extraction_l_per_day": 45000,
     "notes": "Mantenimiento 2026-01-07; misma produccion que 2025"},
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
        "is_forecast",
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
