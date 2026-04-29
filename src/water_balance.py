"""
Lumped-parameter water balance for the Sayariy well (Pozo 1 ASR).

Physics
-------
H(t) = H(t-1) + dH(t)

dH(t) = alpha * recharge_proxy(t)        # lagged Andes rainfall
       + beta  * local_rainfall(t)        # Open-Meteo Cayalti
       - gamma * crop_extraction(t)       # Sum of FAO Kc * ET0 * area + manual extraction
       + delta * enso_modifier(t)         # ONI > +0.5 wet bonus, < -0.5 dry penalty
       - epsilon * et0(t)                 # direct evaporation losses

Where H is the level metric the NGO records (water column height inside the
well casing, per the working assumption — to be confirmed in the Apr 29 NGO
meeting; if Option A is true, flip the sign).

Calibration
-----------
Parameters fit by least squares against the 5 NGO measurements
(2022-2026 from Chequeo.xlsx). With only 5 points we use weak Bayesian
priors derived from the geophysical study (Alarcon 2021):
- 31.2 m saturated thickness, alluvial sands+gravels -> high specific yield (0.10-0.25)
- Free unconfined aquifer -> rapid response to recharge
- Lateral seepage from Rio Zana -> 30-90 day characteristic timescale

The fit is loose by design — the NGO operator can override coefficients via
the dashboard slider when their ground-truth measurement disagrees.

Forecasting
-----------
14-day Open-Meteo forecast for both Cayalti (local) and the upper Zana basin
representative point (Andes), plus current ENSO state, produce a 14-day
deterministic projection. Beyond 14 days (up to 90), we assume seasonal
climatology + the current ENSO modifier. Uncertainty band widens with horizon.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd


@dataclass(frozen=True)
class WaterBalanceParams:
    """Coefficients of the lumped-parameter model.

    Defaults are PLACEHOLDERS for Phase 1 — they let the pipeline run end-to-end
    with sensible-looking output, but they are NOT calibrated. Phase 3 fits them
    to the 5 NGO measurements.

    Scale intuition (uncalibrated): well varied 2.5-3.5 m over 4 years => annual
    swing ~0.5 m, daily variation on the order of a few mm. The defaults here
    target sub-cm daily change at typical driver values.
    """
    alpha: float = 5e-6        # m per mm of lagged Andes rainfall
    beta: float = 1e-5         # m per mm of local rainfall
    gamma: float = 1.5e-8      # m per L extracted (assumes ~1 ha effective recharge area, sy ~0.15)
    delta: float = 0.001       # m per unit ONI anomaly
    epsilon: float = 5e-5      # m per mm of ET0 (direct losses)
    recharge_lag_days: int = 14
    recharge_window_days: int = 60


# FAO-56 Kc placeholders. Maracuya value to be confirmed by teammate research.
CROP_KC_DEFAULT: dict[str, float] = {
    "maracuya": 0.85,    # PLACEHOLDER — verify with FAO-56 / agronomy paper
    "rice": 1.20,        # FAO-56 mid-season
    "sugarcane": 1.25,   # FAO-56 mid-season
    "huertos_mixed": 0.80,  # rough average for mixed kitchen gardens
}


# Combined pump capacity ceiling: Pozo 1 (52,500 L/day) + Pozo 2 (43,000 L/day),
# both 8 h/day operation at sustainable yield. From the 2021 schematic test data
# extrapolated to the operational Pedrollo pumps. Crop demand cannot exceed this
# because the pumps physically cannot deliver more in a day.
PUMP_CAPACITY_L_PER_DAY = 95500


def crop_demand_l_per_day(
    et0_mm_per_day: float,
    n_plants_maracuya: int = 3500,
    n_huertos: int = 20,
    kc_maracuya: float | None = None,
    pump_capacity_l_per_day: float = PUMP_CAPACITY_L_PER_DAY,
) -> float:
    """Daily crop water demand for the Sayariy parcel.

    Coarse model: per-plant demand = Kc * ET0 * effective canopy area.
    Capped at the combined pump capacity — the wells cannot deliver more
    even if the crops want it (deficit irrigation reality).
    Refined in Phase 3 once teammate provides verified maracuya Kc.
    """
    kc_m = kc_maracuya if kc_maracuya is not None else CROP_KC_DEFAULT["maracuya"]
    canopy_m2_maracuya = n_plants_maracuya * 2.0
    demand_maracuya_l = kc_m * et0_mm_per_day * canopy_m2_maracuya  # mm * m^2 = L
    canopy_m2_huertos = n_huertos * 30.0
    demand_huertos_l = CROP_KC_DEFAULT["huertos_mixed"] * et0_mm_per_day * canopy_m2_huertos
    raw_demand = demand_maracuya_l + demand_huertos_l
    return min(raw_demand, pump_capacity_l_per_day)


def step(
    h_prev_m: float,
    recharge_proxy_mm: float,
    local_rainfall_mm: float,
    extraction_l: float,
    oni_anom: float,
    et0_mm: float,
    params: WaterBalanceParams = WaterBalanceParams(),
) -> float:
    """One day forward integration of the water balance."""
    enso_modifier = oni_anom  # raw anomaly, multiplied by delta below
    dh = (
        params.alpha * recharge_proxy_mm
        + params.beta * local_rainfall_mm
        - params.gamma * extraction_l
        + params.delta * enso_modifier
        - params.epsilon * et0_mm
    )
    return h_prev_m + dh


def forecast(
    h0_m: float,
    drivers: pd.DataFrame,
    params: WaterBalanceParams = WaterBalanceParams(),
) -> pd.DataFrame:
    """Run the model forward over a DataFrame of daily drivers.

    `drivers` must have columns:
      date, recharge_proxy_mm, local_rainfall_mm, extraction_l, oni_anom, et0_mm

    Returns the input DataFrame with an added `nivel_predicho_m` column.
    """
    out = drivers.copy()
    h = h0_m
    levels = []
    for row in out.itertuples(index=False):
        h = step(
            h_prev_m=h,
            recharge_proxy_mm=row.recharge_proxy_mm,
            local_rainfall_mm=row.local_rainfall_mm,
            extraction_l=row.extraction_l,
            oni_anom=row.oni_anom,
            et0_mm=row.et0_mm,
            params=params,
        )
        levels.append(h)
    out["nivel_predicho_m"] = levels
    return out


# ---------- Phase 3 will add: ----------
# def calibrate(history: pd.DataFrame, drivers: pd.DataFrame) -> WaterBalanceParams: ...
# def forecast_with_uncertainty(...) -> pd.DataFrame:    # adds low/high bands
# def days_until_critical(history, threshold_m, ...) -> int:
