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
# Approximate canopy footprint (m^2 per plant or per huerto) is used to convert
# Kc * ET0 (mm = L/m²) into a daily water demand in litres.
CROP_KC_DEFAULT: dict[str, float] = {
    "maracuya": 0.85,        # passion fruit, mid-season — verify
    "maiz": 1.20,            # corn, mid-season — verify
    "cebolla": 1.05,         # onion, mid-season — verify
    "cilantro": 1.00,        # cilantro/coriander, mid-season — verify
    "naranja": 0.70,         # orange (mature, no ground cover) — verify
    "huertos_mixed": 0.85,   # rough mixed-vegetable average — verify
    "rice": 1.20,            # FAO-56 mid-season — verify
    "sugarcane": 1.25,       # FAO-56 mid-season — verify
}

# Approximate canopy footprint per unit. Educated estimates — refine when NGO
# confirms actual planting density per chacra.
CROP_CANOPY_M2: dict[str, float] = {
    "maracuya": 2.0,         # per plant (trellised)
    "maiz": 0.5,             # per plant
    "cebolla": 0.05,         # per plant (very small footprint)
    "cilantro": 0.04,        # per plant
    "naranja": 12.0,         # per mature tree
    "huertos_mixed": 30.0,   # per huerto (kitchen garden)
}

# Default hypothetical crop mix — pending NGO confirmation of the actual mix.
# 3,500 maracuyá is the only hard number from the meeting. The 20 huertos are
# split with the smaller ones holding orange trees (per NGO Apr 30 note).
DEFAULT_CROP_MIX: dict[str, int] = {
    "maracuya": 3500,
    "naranja": 5,    # the smaller chacras
    "maiz": 6,
    "cebolla": 5,
    "cilantro": 4,
}


# Pump capacity ceiling — Pozo 1 only, since Pozo 2 was reported out of service
# in the NGO meeting on 2026-04-30. 52,500 L/day = Pedrollo 4SR45Gm/30 at 8 h/day
# sustainable yield (from 2021 schematic test data). Crop demand cannot exceed
# this because the pump physically cannot deliver more in a day.
# Restore to 95,500 L/day (combined Pozo 1 + Pozo 2) once Pozo 2 returns to service.
PUMP_CAPACITY_L_PER_DAY = 52500


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
) -> pd.DataFrame:
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
    return out.reset_index(drop=True)


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
