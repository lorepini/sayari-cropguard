"""
Calibration of the Sayariy water-balance model — Phase 3.

Strategy
--------
We have only 5 annual observations (2022-2026 from Chequeo.xlsx, Pozo 1) and
5 free parameters in src.water_balance.WaterBalanceParams. Fitting 5 params
to 5 points with no constraint = exact interpolation, not science.

So we frame this as **regularized least-squares with Bayesian priors** —
defensible under data scarcity and consistent with the "physics-based, not ML"
choice logged in the project notes:

    minimize  SSE(theta) + lambda * sum_j ((theta_j - prior_j) / sigma_j)^2

where prior_j are the placeholder values from WaterBalanceParams (informed by
Alarcon 2021: 0.10-0.25 specific yield, 31.2 m saturated thickness, free
unconfined aquifer with 30-90 day lateral seepage timescale) and sigma_j is
a prior scale that allows the data to move each parameter by ~1 order of
magnitude before the prior pulls back hard.

Recharge_lag_days and recharge_window_days are FROZEN at their priors — fitting
them turns the optimization non-convex without enough data to identify them.

Validation: leave-one-out CV — fit on 4 points, predict the 5th, repeat.
Report mean RMSE and per-fold predicted vs observed.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from src.data_sources import andes_rainfall, noaa_oni, open_meteo
from src.water_balance import WaterBalanceParams, forecast


# Cayaltí coordinates — single source of truth in config.SAYARIY_LAT/LON,
# derived from Alarcón 2021 UTM (663913E, 9235271N, zone 17S) → WGS84.
import config as _cfg  # noqa: E402
LOCAL_LAT = _cfg.SAYARIY_LAT
LOCAL_LON = _cfg.SAYARIY_LON

# Parameter prior scales: how far the data can move each param before the
# regularizer pushes back. Set so the placeholder values can move ~1 order
# of magnitude with mild penalty.
PRIOR_SCALES: dict[str, float] = {
    "alpha": 5e-6,
    "beta": 1e-5,
    "gamma": 1.5e-8,
    "delta": 0.001,
    "epsilon": 5e-5,
}

# Free parameters (the rest are frozen)
FREE_PARAMS: tuple[str, ...] = ("alpha", "beta", "gamma", "delta", "epsilon")


# ---------------------------------------------------------------------------
# Driver assembly
# ---------------------------------------------------------------------------

def build_drivers(start: dt.date, end: dt.date) -> pd.DataFrame:
    """Daily driver DataFrame for the calibration window.

    Columns: date, recharge_proxy_mm, local_rainfall_mm, et0_mm, oni_anom.

    `extraction_l` is filled separately by `attach_extraction_profile()`
    because it depends on the NGO history.
    """
    local = open_meteo.fetch_historical(LOCAL_LAT, LOCAL_LON, start, end)
    upper = andes_rainfall.fetch_upper_basin_history(start, end)
    df = local.merge(upper[["date", "andes_precip_mm"]], on="date", how="left")
    df["recharge_proxy_mm"] = (
        andes_rainfall.recharge_proxy(df["andes_precip_mm"]).fillna(0.0)
    )
    df["local_rainfall_mm"] = df["precip_mm"].fillna(0.0)
    df["et0_mm"] = df["et0_mm"].fillna(0.0)

    # ONI is monthly; forward-fill to daily
    oni = noaa_oni.fetch_oni()[["date", "anom_c"]]
    oni["date"] = pd.to_datetime(oni["date"]).dt.date
    oni = oni.rename(columns={"anom_c": "oni_anom"})
    df = df.merge(oni, on="date", how="left")
    df["oni_anom"] = df["oni_anom"].ffill().bfill().fillna(0.0)

    return df[["date", "recharge_proxy_mm", "local_rainfall_mm", "et0_mm", "oni_anom"]]


def attach_extraction_profile(drivers: pd.DataFrame, history: pd.DataFrame) -> pd.DataFrame:
    """Build a daily extraction series from the annual NGO snapshot values.

    Step-change profile: each annual `extraction_l_per_day` value applies
    from its date until the next observation. Days before the first record
    (2022-12-31) inherit the baseline 0 L/day.
    """
    out = drivers.copy()
    history_sorted = history.sort_values("date").reset_index(drop=True)
    extraction = pd.Series(0.0, index=range(len(out)))
    out_dates = pd.to_datetime(out["date"])
    for _, row in history_sorted.iterrows():
        cutoff = pd.Timestamp(row["date"])
        mask = out_dates >= cutoff
        extraction.loc[mask] = float(row["extraction_l_per_day"])
    out["extraction_l"] = extraction.values
    return out


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

def _params_from_vector(theta: np.ndarray, base: WaterBalanceParams) -> WaterBalanceParams:
    return replace(base, **{name: float(v) for name, v in zip(FREE_PARAMS, theta)})


def _vector_from_params(p: WaterBalanceParams) -> np.ndarray:
    return np.array([getattr(p, name) for name in FREE_PARAMS], dtype=float)


def _simulate_at_dates(
    drivers: pd.DataFrame,
    params: WaterBalanceParams,
    baseline_date: pd.Timestamp,
    baseline_h_m: float,
    target_dates: Iterable[pd.Timestamp],
) -> np.ndarray:
    """Simulate forward from baseline and return predicted h at each target date."""
    df = drivers.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["date"] >= baseline_date].sort_values("date").reset_index(drop=True)
    fc = forecast(h0_m=baseline_h_m, drivers=df, params=params)
    fc["date"] = pd.to_datetime(fc["date"])
    fc_indexed = fc.set_index("date")["nivel_predicho_m"]

    out = []
    for d in target_dates:
        d = pd.Timestamp(d)
        if d in fc_indexed.index:
            out.append(float(fc_indexed.loc[d]))
        else:
            # Use last available value on or before d
            sub = fc_indexed[fc_indexed.index <= d]
            out.append(float(sub.iloc[-1]) if len(sub) else baseline_h_m)
    return np.array(out)


def calibrate(
    history: pd.DataFrame,
    drivers: pd.DataFrame,
    baseline_date: pd.Timestamp,
    baseline_h_m: float,
    prior: WaterBalanceParams = WaterBalanceParams(),
    ridge_lambda: float = 1.0,
    held_out_idx: int | None = None,
) -> tuple[WaterBalanceParams, dict]:
    """Fit free params by regularized least-squares against nivel_estatico_m.

    Parameters
    ----------
    history : 5-row DataFrame with `date` and `nivel_estatico_m`
    drivers : daily DataFrame with extraction attached
    baseline_date / baseline_h_m : anchor (typically 2022-12-31, 3.5 m)
    ridge_lambda : strength of L2 pull toward prior (1.0 = balanced)
    held_out_idx : if not None, exclude that observation row from the fit

    Returns
    -------
    (calibrated WaterBalanceParams, info dict with sse, ridge_penalty, success)
    """
    fit_history = history.reset_index(drop=True).copy()
    if held_out_idx is not None:
        fit_history = fit_history.drop(index=held_out_idx).reset_index(drop=True)

    target_dates = pd.to_datetime(fit_history["date"]).tolist()
    target_h = fit_history["nivel_estatico_m"].to_numpy(dtype=float)

    theta0 = _vector_from_params(prior)
    prior_scale = np.array([PRIOR_SCALES[n] for n in FREE_PARAMS])

    def objective(theta: np.ndarray) -> float:
        params = _params_from_vector(theta, prior)
        h_pred = _simulate_at_dates(drivers, params, baseline_date, baseline_h_m, target_dates)
        sse = float(np.sum((h_pred - target_h) ** 2))
        # Ridge penalty in dimensionless units (delta / prior_scale)
        ridge = float(np.sum(((theta - theta0) / prior_scale) ** 2))
        return sse + ridge_lambda * ridge

    # Bounds: most coefficients should be positive; delta (ENSO) can be either sign
    bounds = [
        (0.0, 1e-3),    # alpha
        (0.0, 1e-3),    # beta
        (0.0, 1e-5),    # gamma
        (-0.05, 0.05),  # delta (ENSO can be either sign in principle)
        (0.0, 1e-2),    # epsilon
    ]

    result = minimize(
        objective,
        theta0,
        method="L-BFGS-B",
        bounds=bounds,
        options={"maxiter": 200, "ftol": 1e-12},
    )

    fitted = _params_from_vector(result.x, prior)
    h_pred_final = _simulate_at_dates(drivers, fitted, baseline_date, baseline_h_m, target_dates)
    info = {
        "success": bool(result.success),
        "n_iter": int(result.nit),
        "sse": float(np.sum((h_pred_final - target_h) ** 2)),
        "ridge_penalty": float(np.sum(((result.x - theta0) / prior_scale) ** 2)),
        "fitted_h_pred": h_pred_final.tolist(),
        "target_h": target_h.tolist(),
    }
    return fitted, info


# ---------------------------------------------------------------------------
# Leave-one-out cross-validation
# ---------------------------------------------------------------------------

def leave_one_out_cv(
    history: pd.DataFrame,
    drivers: pd.DataFrame,
    baseline_date: pd.Timestamp,
    baseline_h_m: float,
    prior: WaterBalanceParams = WaterBalanceParams(),
    ridge_lambda: float = 1.0,
) -> dict:
    """Leave-one-out CV: fit on N-1, predict held-out, repeat.

    Returns a dict with:
      - per_fold: DataFrame (date, observed, predicted, residual)
      - rmse: float (sqrt mean squared residual across folds)
      - mae: float (mean abs residual)
      - max_abs_err: float
      - residual_std: float (used as forecast uncertainty seed)
    """
    history = history.reset_index(drop=True)
    rows = []
    for i in range(len(history)):
        fitted, _ = calibrate(
            history=history,
            drivers=drivers,
            baseline_date=baseline_date,
            baseline_h_m=baseline_h_m,
            prior=prior,
            ridge_lambda=ridge_lambda,
            held_out_idx=i,
        )
        held = history.iloc[i]
        target_date = pd.Timestamp(held["date"])
        h_pred = _simulate_at_dates(
            drivers, fitted, baseline_date, baseline_h_m, [target_date]
        )[0]
        rows.append({
            "fold": i,
            "date": target_date.date(),
            "observed_m": float(held["nivel_estatico_m"]),
            "predicted_m": float(h_pred),
            "residual_m": float(h_pred - float(held["nivel_estatico_m"])),
        })
    per_fold = pd.DataFrame(rows)
    residuals = per_fold["residual_m"].to_numpy()
    return {
        "per_fold": per_fold,
        "rmse": float(np.sqrt(np.mean(residuals ** 2))),
        "mae": float(np.mean(np.abs(residuals))),
        "max_abs_err": float(np.max(np.abs(residuals))),
        "residual_std": float(np.std(residuals, ddof=0)),
    }


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_params(params: WaterBalanceParams, path: Path, metadata: dict | None = None) -> None:
    payload = {
        "params": asdict(params),
        "metadata": metadata or {},
        "saved_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def load_params(path: Path) -> WaterBalanceParams:
    payload = json.loads(path.read_text())
    return WaterBalanceParams(**payload["params"])
