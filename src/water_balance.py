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


# FAO-56 reference Kc values. ALL VALUES UNVERIFIED — must be cross-checked
# against FAO Irrigation & Drainage Paper 56 (Allen et al. 1998), Tables 12 &
# 17, before being cited in any deliverable. Course rule: every academic
# citation must be manually verified or it counts as fraud.
#
# `canopy_m2` represents the *wetted area* per unit under drip irrigation
# (NGO confirmed 2026-05-05: all crops drip-irrigated), not full planted area.
# This is why Kc * ET0 * canopy * count yields demand close to the NGO-reported
# 30,000 L/day for crops, despite 13 ha of total planted area.
CROP_KC_DEFAULT: dict[str, float] = {
    "maracuya": 0.85,        # passion fruit, mid-season — verify
    "maiz": 1.20,            # corn, mid-season — verify
    "frijol": 1.15,          # bean, mid-season — verify (rotates with maíz Q3)
    "huertos_mixed": 0.85,   # rough mixed-vegetable average — verify
    "naranja": 0.70,         # orange (mature, no ground cover) — verify
    "mandarina": 0.70,       # mandarin — verify
    "limon": 0.70,           # lime/lemon — verify
    "mango": 0.85,           # mango (mature) — verify
    "palta": 0.85,           # avocado (mature) — verify
    "papaya": 1.05,          # papaya (mid-season) — verify
    "coco": 0.95,            # coconut palm — verify
    "tuna": 0.50,            # prickly pear / cactus — verify
    "algodon": 1.15,         # cotton, mid-season — verify
    "rice": 1.20,            # FAO-56 mid-season — verify (not currently planted)
    "sugarcane": 1.25,       # FAO-56 mid-season — verify (not currently planted)
}

# Wetted-area per unit under drip. The huertos figure is calibrated so that
# DEFAULT_CROP_MIX yields ~30k L/day at typical ET0=4.5 mm/day, matching the
# NGO's reported normal-season crop draw of 30,000 L/day.
CROP_CANOPY_M2: dict[str, float] = {
    "maracuya": 2.0,         # per plant (trellised, 3 ha / 3,500 plants ≈ 8.6 m² planted, ~2 m² wetted)
    "maiz": 0.5,             # per plant
    "frijol": 0.3,           # per plant
    "huertos_mixed": 40.0,   # per huerto wetted; the 10 ha / 20 huertos hold the
                             # orchard species below — calibrated to NGO 30k/day baseline.
    "naranja": 12.0,         # per mature tree (reference; usually counted in huertos_mixed)
    "mandarina": 10.0,       # per mature tree
    "limon": 8.0,            # per mature tree
    "mango": 25.0,           # per mature tree
    "palta": 20.0,           # per mature tree
    "papaya": 4.0,           # per plant
    "coco": 15.0,            # per palm
    "tuna": 1.0,             # per plant (cactus, low wetted)
    "algodon": 0.5,          # per plant
}

# NGO-confirmed crop inventory (meeting 2026-05-05):
# - Maracuyá: 3 ha, 3,500 plants
# - 20 huertos = 10 ha total, holding the orchard mix listed in CROP_KC_DEFAULT
#   (mango, palta, naranja, mandarina, limón, papaya, coco, tuna, algodón —
#   planted Jan 2023, still in production). Counted as `huertos_mixed` to avoid
#   double-counting until NGO confirms per-chacra species/plant counts.
# - Frijol/maíz rotated every 3 months for soil nutrition — only one in ground
#   at a time. Conservative default uses maíz (higher Kc).
DEFAULT_CROP_MIX: dict[str, int] = {
    "maracuya": 3500,
    "huertos_mixed": 20,
    "maiz": 100,
}


# Pump capacity ceiling — Pozo 1 only. NGO confirmed 2026-05-05 that the
# operational pump is currently a 2-inch solar pump (less powerful than the
# Pedrollo 4SR45Gm/30 spec'd in the schematic) and fills 50,000 L in 4 hours
# on a 28-30 °C day. Pozo 2 is backup-only and contributes 0 by default.
# The schematic's 52,500 L/day Pedrollo sustainable yield remains in
# wells.geojson for reference if/when the Pedrollo is re-activated.
PUMP_CAPACITY_L_PER_DAY = 50_000

# Household demand on the same system (NGO confirmed 2026-05-05): the houses
# connected to the storage tank consume ~20,000 L/day year-round. This is added
# on top of crop_demand_l_per_day to get total well extraction.
HOUSEHOLD_DEMAND_L_PER_DAY = 20_000

# Seasonal crop-demand multiplier. NGO confirmed 2026-05-05:
# - Oct-Apr (hot, days >30 °C): 40-45k L/day for crops
# - May-Sep (cooler): ~30k L/day for crops
# Apply to crop_demand_l_per_day() output before summing with household demand.
HIGH_DEMAND_MONTHS = {1, 2, 3, 4, 10, 11, 12}
HIGH_DEMAND_MULTIPLIER = 1.45  # 30k -> 43.5k matches NGO's 40-45k range


def seasonal_demand_multiplier(month: int) -> float:
    """Return the NGO-confirmed seasonal multiplier for a given month (1-12)."""
    return HIGH_DEMAND_MULTIPLIER if month in HIGH_DEMAND_MONTHS else 1.0


def crop_demand_l_per_day(
    et0_mm_per_day: float,
    crop_mix: dict[str, int] | None = None,
    kc_overrides: dict[str, float] | None = None,
    canopy_overrides: dict[str, float] | None = None,
    pump_capacity_l_per_day: float = PUMP_CAPACITY_L_PER_DAY,
) -> float:
    """Daily crop water demand for the Sayariy parcel.

    Per-crop demand = Kc * ET0 * canopy_m2 * count, summed across the mix.
    Capped at `pump_capacity_l_per_day` — the well cannot deliver more even if
    the crops want it (deficit irrigation reality).

    Parameters
    ----------
    et0_mm_per_day : reference evapotranspiration (FAO Penman-Monteith)
    crop_mix : {crop_name: count_of_plants_or_huertos}.
        Defaults to DEFAULT_CROP_MIX (hypothetical, pending NGO confirmation).
    kc_overrides : per-crop Kc overrides; falls back to CROP_KC_DEFAULT
    canopy_overrides : per-crop canopy area overrides; falls back to CROP_CANOPY_M2
    """
    mix = crop_mix if crop_mix is not None else DEFAULT_CROP_MIX
    kc_table = {**CROP_KC_DEFAULT, **(kc_overrides or {})}
    canopy_table = {**CROP_CANOPY_M2, **(canopy_overrides or {})}

    raw_demand = 0.0
    for crop, count in mix.items():
        if count <= 0:
            continue
        kc = kc_table.get(crop)
        canopy = canopy_table.get(crop)
        if kc is None or canopy is None:
            raise KeyError(
                f"Crop {crop!r} missing Kc or canopy area. "
                f"Add to CROP_KC_DEFAULT / CROP_CANOPY_M2 or pass overrides."
            )
        # mm/day * m² * count = L/day  (since 1 mm over 1 m² = 1 L)
        raw_demand += kc * et0_mm_per_day * canopy * count

    return min(raw_demand, pump_capacity_l_per_day)


def total_extraction_l_per_day(
    et0_mm_per_day: float,
    month: int,
    crop_mix: dict[str, int] | None = None,
    kc_overrides: dict[str, float] | None = None,
    canopy_overrides: dict[str, float] | None = None,
    pump_capacity_l_per_day: float = PUMP_CAPACITY_L_PER_DAY,
    household_l_per_day: float = HOUSEHOLD_DEMAND_L_PER_DAY,
) -> float:
    """Total daily well extraction = seasonal crop demand + household demand,
    capped at pump capacity. NGO confirmed (2026-05-05) the houses on the
    system draw a roughly constant 20,000 L/day year-round; crop demand swings
    by month per `seasonal_demand_multiplier()`.
    """
    crops = crop_demand_l_per_day(
        et0_mm_per_day=et0_mm_per_day,
        crop_mix=crop_mix,
        kc_overrides=kc_overrides,
        canopy_overrides=canopy_overrides,
        pump_capacity_l_per_day=pump_capacity_l_per_day,
    )
    crops *= seasonal_demand_multiplier(month)
    return min(crops + household_l_per_day, pump_capacity_l_per_day)


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


def forecast_ensemble(
    h0_m: float,
    drivers_per_member: list[pd.DataFrame],
    params: WaterBalanceParams = WaterBalanceParams(),
    percentiles: tuple[float, ...] = (10, 50, 90),
    return_matrix: bool = False,
) -> pd.DataFrame | tuple[pd.DataFrame, pd.DataFrame]:
    """Run the model forward under each ensemble driver trajectory.

    drivers_per_member : list of DataFrames, one per ensemble member, each
        with the standard driver columns (date, recharge_proxy_mm,
        local_rainfall_mm, extraction_l, oni_anom, et0_mm).

    Returns a DataFrame indexed by date with `nivel_p10_m`, `nivel_p50_m`,
    `nivel_p90_m` columns (or whatever percentiles you pass), plus
    `nivel_mean_m` and `nivel_std_m`. This is a true probabilistic forecast
    derived from ensemble physics, not a synthetic uncertainty assumption.
    """
    if not drivers_per_member:
        raise ValueError("forecast_ensemble: empty ensemble")

    trajectories = []
    for drivers in drivers_per_member:
        fc = forecast(h0_m=h0_m, drivers=drivers, params=params)
        trajectories.append(fc[["date", "nivel_predicho_m"]].set_index("date")["nivel_predicho_m"])

    matrix = pd.concat(trajectories, axis=1)
    out = pd.DataFrame({"date": matrix.index})
    for p in percentiles:
        out[f"nivel_p{int(p):02d}_m"] = matrix.quantile(p / 100.0, axis=1).values
    out["nivel_mean_m"] = matrix.mean(axis=1).values
    out["nivel_std_m"] = matrix.std(axis=1).values
    out["n_members"] = matrix.shape[1]
    out = out.reset_index(drop=True)
    if return_matrix:
        return out, matrix
    return out


def cross_probability(
    ensemble_matrix: pd.DataFrame,
    threshold_m: float,
    horizon_days: int,
) -> float:
    """Fraction of ensemble members whose trajectory drops below `threshold_m`
    at any point within the first `horizon_days` of the forecast.

    `ensemble_matrix` is the (date × member) DataFrame returned by
    `forecast_ensemble(..., return_matrix=True)`.
    """
    if ensemble_matrix.empty or horizon_days <= 0:
        return 0.0
    sub = ensemble_matrix.iloc[:horizon_days]
    crossed = (sub < threshold_m).any(axis=0)
    return float(crossed.mean())


def forecast_with_uncertainty(
    h0_m: float,
    drivers: pd.DataFrame,
    params: WaterBalanceParams = WaterBalanceParams(),
    residual_std_m: float = 0.15,
    z: float = 1.96,
    reference_horizon_days: int = 365,
) -> pd.DataFrame:
    """Forecast with a horizon-scaled uncertainty band.

    The band widens as `z * residual_std_m * sqrt(t / reference_horizon_days)` —
    random-walk-style growth normalized so that the band reaches `z * residual_std_m`
    at the reference horizon. `residual_std_m` is the LOO-CV residual SD from
    calibration, which is itself measured at ~annual horizons (the spacing of the
    NGO observations), hence the 365-day default.
    """
    fc = forecast(h0_m=h0_m, drivers=drivers, params=params).copy()
    horizon_days = pd.Series(range(1, len(fc) + 1), index=fc.index, dtype=float)
    band = z * residual_std_m * (horizon_days / reference_horizon_days) ** 0.5
    fc["nivel_predicho_low_m"] = fc["nivel_predicho_m"] - band
    fc["nivel_predicho_high_m"] = fc["nivel_predicho_m"] + band
    return fc


def days_until_critical(
    forecast_df: pd.DataFrame,
    threshold_m: float,
    column: str = "nivel_predicho_m",
) -> int | None:
    """Days from the start of the forecast until `column` first drops below
    `threshold_m`. Returns None if the threshold is never crossed inside the
    forecast horizon.
    """
    below = forecast_df[forecast_df[column] < threshold_m]
    if below.empty:
        return None
    start = pd.to_datetime(forecast_df.iloc[0]["date"])
    cross = pd.to_datetime(below.iloc[0]["date"])
    return int((cross - start).days)
