"""
Per-crop water-stress forecast — combines:
  - Open-Meteo tmax + ET₀ forecast (next 21 days)
  - The lumped water-balance model's well-level P50 forecast
  - Per-crop Kc + wetted-area + plant count from src.water_balance

Physics, not ML — no agronomist input required for the baseline (the user has
agronomist interviews coming separately for the *recommendation* layer).

A "stress day" for crop C on date d is flagged when EITHER:
  (a) **Heat stress**: tmax(d) > HEAT_HARMFUL_C (35 °C by default) — direct
      damage to fruit setting / flowering for sensitive species, regardless of
      water availability.
  (b) **Supply stress**: the day's total crop demand exceeds the pump-cap
      crop budget (PUMP_CAPACITY - HOUSEHOLD_DEMAND), so every crop is
      proportionally short-watered.
  (c) **Heat-amplified demand stress**: tmax(d) > HEAT_THRESHOLD_C (30 °C —
      NGO meeting 2026-05-05) AND the seasonal multiplier pushes demand into
      shortfall.

Output shape lets the dashboard render either a per-crop summary or a per-day
trace.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.water_balance import (
    CROP_KC_DEFAULT,
    CROP_CANOPY_M2,
    DEFAULT_CROP_MIX,
    HOUSEHOLD_DEMAND_L_PER_DAY,
    PUMP_CAPACITY_L_PER_DAY,
    seasonal_demand_multiplier,
)


# Thresholds — keep adjacent to the function that uses them so they're
# easy to tune from the dashboard layer.
HEAT_THRESHOLD_C = 30.0      # NGO 2026-05-05: días > 30 °C exigen riego reforzado
HEAT_HARMFUL_C = 35.0        # above this, direct foliar / flowering damage
DEFICIT_FRACTION_THRESHOLD = 0.20  # 20% short = stress flagged


@dataclass(frozen=True)
class CropStressSummary:
    crop: str
    avg_daily_demand_l: float
    total_demand_l: float
    total_supplied_l: float
    deficit_l: float
    stress_days: int
    peak_stress_date: pd.Timestamp | None
    peak_stress_reason: str  # "heat_harmful" | "heat_amplified_supply" | "supply" | None


def _crop_demand_per_day(
    et0_series: pd.Series,
    crop_mix: dict[str, int],
    seasonal_multipliers: pd.Series,
) -> pd.DataFrame:
    """Returns wide DataFrame: index=date, columns=crops, values=L/day demand."""
    rows = {}
    for crop, count in crop_mix.items():
        kc = CROP_KC_DEFAULT.get(crop)
        canopy = CROP_CANOPY_M2.get(crop)
        if kc is None or canopy is None or count <= 0:
            continue
        # demand_d = Kc * ET0_d * canopy * count * seasonal_multiplier
        rows[crop] = (kc * canopy * count) * et0_series.values * seasonal_multipliers.values
    return pd.DataFrame(rows, index=et0_series.index)


def crop_stress_forecast(
    forecast_df: pd.DataFrame,
    crop_mix: dict[str, int] | None = None,
    pump_capacity_l_per_day: float = PUMP_CAPACITY_L_PER_DAY,
    household_l_per_day: float = HOUSEHOLD_DEMAND_L_PER_DAY,
) -> tuple[pd.DataFrame, list[CropStressSummary]]:
    """Per-crop stress forecast.

    forecast_df must have columns: date, tmax_c, et0_mm.
    (Optionally well_p50_m for narrative use; not consumed by stress logic.)

    Returns (per_day_df, summaries):
      - per_day_df: date | tmax_c | et0_mm | total_demand_l | crop_supply_cap_l |
                    supplied_l | deficit_l | heat_day | heat_harmful | stress_day
      - summaries: one CropStressSummary per crop in mix.
    """
    mix = crop_mix or DEFAULT_CROP_MIX
    df = forecast_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()

    months = df.index.month
    seasonal = pd.Series([seasonal_demand_multiplier(m) for m in months],
                         index=df.index)

    demand_wide = _crop_demand_per_day(df["et0_mm"], mix, seasonal)
    crop_total = demand_wide.sum(axis=1)
    crop_cap = pump_capacity_l_per_day - household_l_per_day  # L/day for crops

    # Proportional allocation when crop_total > cap
    allocation = (crop_cap / crop_total).clip(upper=1.0)
    supplied_wide = demand_wide.multiply(allocation, axis=0)
    deficit_wide = demand_wide - supplied_wide

    df["total_demand_l"] = crop_total
    df["crop_supply_cap_l"] = crop_cap
    df["supplied_l"] = supplied_wide.sum(axis=1)
    df["deficit_l"] = deficit_wide.sum(axis=1)
    df["heat_day"] = df["tmax_c"] > HEAT_THRESHOLD_C
    df["heat_harmful"] = df["tmax_c"] > HEAT_HARMFUL_C
    df["supply_stress"] = df["deficit_l"] > 0
    df["stress_day"] = df["heat_harmful"] | df["supply_stress"]

    summaries: list[CropStressSummary] = []
    for crop in demand_wide.columns:
        d = demand_wide[crop]
        s = supplied_wide[crop]
        defc = deficit_wide[crop]
        # Per-crop stress = its own supply gap > threshold OR system-wide harmful heat
        per_crop_stress = (defc / d.replace(0, pd.NA)).fillna(0) > DEFICIT_FRACTION_THRESHOLD
        per_crop_stress = per_crop_stress | df["heat_harmful"]
        n_stress = int(per_crop_stress.sum())
        if n_stress:
            # Peak = the day with the worst combined stress
            score = defc / d.replace(0, pd.NA).fillna(1) + (df["tmax_c"] > HEAT_THRESHOLD_C) * 0.2
            peak = score.idxmax()
            if df.loc[peak, "heat_harmful"]:
                reason = "heat_harmful"
            elif df.loc[peak, "heat_day"] and df.loc[peak, "supply_stress"]:
                reason = "heat_amplified_supply"
            elif df.loc[peak, "supply_stress"]:
                reason = "supply"
            else:
                reason = "marginal"
        else:
            peak = None
            reason = "none"
        summaries.append(CropStressSummary(
            crop=crop,
            avg_daily_demand_l=float(d.mean()),
            total_demand_l=float(d.sum()),
            total_supplied_l=float(s.sum()),
            deficit_l=float(defc.sum()),
            stress_days=n_stress,
            peak_stress_date=peak,
            peak_stress_reason=reason,
        ))

    summaries.sort(key=lambda s: (-s.stress_days, -s.deficit_l))
    return df.reset_index(), summaries


def crop_label_es(crop: str) -> str:
    return {
        "maracuya": "Maracuyá",
        "huertos_mixed": "Huertos (mango, palta, naranja…)",
        "maiz": "Maíz",
        "frijol": "Frijol",
        "naranja": "Naranja",
        "mandarina": "Mandarina",
        "limon": "Limón",
        "mango": "Mango",
        "palta": "Palta",
        "papaya": "Papaya",
        "coco": "Coco",
        "tuna": "Tuna",
        "algodon": "Algodón",
    }.get(crop, crop.capitalize())


def reason_label_es(reason: str) -> str:
    return {
        "heat_harmful": "calor extremo (>35 °C)",
        "heat_amplified_supply": "calor + demanda excede bombeo",
        "supply": "demanda excede bombeo",
        "marginal": "estrés marginal",
        "none": "—",
    }.get(reason, reason)
