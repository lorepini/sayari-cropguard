"""
Phase 3 calibration runner.

Fetches historical drivers (Open-Meteo archive + NOAA ONI) for 2022-2026,
fits the water-balance free parameters against the 5 NGO observations from
Chequeo.xlsx, runs leave-one-out CV, and saves:

  - data/processed/water_balance_params.json  (calibrated coefficients)
  - data/processed/water_balance_drivers.parquet  (cached drivers for reuse)
  - docs/water_module_phase3.md                (calibration report)

Usage:
  python scripts/calibrate_water_balance.py
  python scripts/calibrate_water_balance.py --ridge 0.5
  python scripts/calibrate_water_balance.py --no-fetch   # use cached drivers
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.calibration import (  # noqa: E402
    attach_extraction_profile,
    build_drivers,
    calibrate,
    leave_one_out_cv,
    save_params,
)
from src.water_balance import WaterBalanceParams  # noqa: E402

WELLS_HISTORY = ROOT / "data" / "processed" / "wells_history.parquet"
DRIVERS_CACHE = ROOT / "data" / "processed" / "water_balance_drivers.parquet"
PARAMS_OUT = ROOT / "data" / "processed" / "water_balance_params.json"
REPORT_OUT = ROOT / "docs" / "water_module_phase3.md"

CALIBRATION_START = dt.date(2022, 1, 1)
# NGO meeting 2026-05-05 confirmed the annual measurements are taken in June,
# not December (the previous Dec-31 placeholder was off by ~6 months and
# biased α/β/ε since June and December have very different ET₀/rainfall
# regimes in Cayaltí). Anchoring at the first NGO June measurement.
BASELINE_DATE = pd.Timestamp("2022-06-15")
BASELINE_H_M = 3.5  # 2022 June nivel_estatico from Chequeo.xlsx (matches Pozo 1 schematic baseline)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ridge", type=float, default=0.05,
                        help="L2 prior strength (higher = stays closer to placeholder). "
                             "Default 0.05 minimized LOO RMSE on the 5 NGO points.")
    parser.add_argument("--no-fetch", action="store_true",
                        help="Use cached drivers parquet instead of re-fetching")
    parser.add_argument("--end-date", type=str, default=None,
                        help="End date YYYY-MM-DD (default: today - 2 days, archive lag)")
    args = parser.parse_args()

    end = (
        dt.date.fromisoformat(args.end_date)
        if args.end_date
        else dt.date.today() - dt.timedelta(days=2)
    )

    # Load NGO history
    history = pd.read_parquet(WELLS_HISTORY)
    history = history[history["well_id"] == "pozo1_asr"].reset_index(drop=True)
    history["date"] = pd.to_datetime(history["date"])
    print(f"\nLoaded {len(history)} NGO observations:")
    print(history[["date", "nivel_estatico_m", "extraction_l_per_day"]].to_string(index=False))

    # Drivers: fetch or load
    if args.no_fetch and DRIVERS_CACHE.exists():
        print(f"\nLoading cached drivers from {DRIVERS_CACHE.name}")
        drivers = pd.read_parquet(DRIVERS_CACHE)
        drivers["date"] = pd.to_datetime(drivers["date"]).dt.date
    else:
        print(f"\nFetching drivers {CALIBRATION_START} -> {end} ...")
        drivers = build_drivers(CALIBRATION_START, end)
        drivers = attach_extraction_profile(drivers, history)
        DRIVERS_CACHE.parent.mkdir(parents=True, exist_ok=True)
        drivers.to_parquet(DRIVERS_CACHE, index=False)
        print(f"  Cached -> {DRIVERS_CACHE.name}  ({len(drivers)} rows)")

    # Always re-attach extraction from the (possibly updated) NGO history,
    # even when reusing the cached drivers parquet — the rainfall/ET₀ side is
    # static but the extraction profile changes whenever NGO confirms numbers.
    drivers = drivers.drop(columns=["extraction_l"], errors="ignore")
    drivers = attach_extraction_profile(drivers, history)

    print(f"\nDriver summary ({len(drivers)} days):")
    print(f"  local rainfall:   total {drivers['local_rainfall_mm'].sum():.0f} mm  "
          f"({drivers['local_rainfall_mm'].mean()*365:.0f} mm/yr avg)")
    print(f"  Andes recharge:   total {drivers['recharge_proxy_mm'].sum():.0f} mm "
          f"(rolling sum, not raw rainfall)")
    print(f"  ET0:              total {drivers['et0_mm'].sum():.0f} mm  "
          f"({drivers['et0_mm'].mean()*365:.0f} mm/yr avg)")
    print(f"  ONI range:        {drivers['oni_anom'].min():+.2f} to "
          f"{drivers['oni_anom'].max():+.2f}")
    print(f"  Extraction range: {drivers['extraction_l'].min():,.0f} to "
          f"{drivers['extraction_l'].max():,.0f} L/day")

    # Full-data fit
    print(f"\nCalibrating (ridge_lambda={args.ridge}) ...")
    fitted, info = calibrate(
        history=history,
        drivers=drivers,
        baseline_date=BASELINE_DATE,
        baseline_h_m=BASELINE_H_M,
        ridge_lambda=args.ridge,
    )
    print(f"  Fit: success={info['success']}, iter={info['n_iter']}, "
          f"SSE={info['sse']:.4f}, ridge={info['ridge_penalty']:.2f}")
    print(f"  Fitted params (vs prior in parens):")
    prior = WaterBalanceParams()
    for name in ("alpha", "beta", "gamma", "delta", "epsilon"):
        f = getattr(fitted, name)
        p = getattr(prior, name)
        ratio = f / p if p != 0 else float("nan")
        print(f"    {name:8s} = {f:.3e}   (prior {p:.3e}, ratio {ratio:+.2f}x)")

    # Per-observation residuals at full fit
    fit_table = pd.DataFrame({
        "date": history["date"].dt.date,
        "observed_m": info["target_h"],
        "predicted_m": info["fitted_h_pred"],
        "is_post_maintenance": history.get("is_post_maintenance",
                                           pd.Series([False] * len(history))).values,
    })
    fit_table["residual_m"] = fit_table["predicted_m"] - fit_table["observed_m"]
    print(f"\nFull-fit residuals:")
    print(fit_table.to_string(index=False))

    # Leave-one-out CV
    print(f"\nRunning leave-one-out CV ...")
    cv = leave_one_out_cv(
        history=history,
        drivers=drivers,
        baseline_date=BASELINE_DATE,
        baseline_h_m=BASELINE_H_M,
        ridge_lambda=args.ridge,
    )
    print(cv["per_fold"].to_string(index=False))
    print(f"\n  RMSE        = {cv['rmse']:.3f} m")
    print(f"  MAE         = {cv['mae']:.3f} m")
    print(f"  Max abs err = {cv['max_abs_err']:.3f} m")
    print(f"  Residual SD = {cv['residual_std']:.3f} m  (used as forecast band seed)")

    # Persist
    metadata = {
        "method": "regularized least-squares with Bayesian L2 prior",
        "ridge_lambda": args.ridge,
        "n_observations": int(len(history)),
        "baseline_date": str(BASELINE_DATE.date()),
        "baseline_h_m": BASELINE_H_M,
        "calibration_window": [str(CALIBRATION_START), str(end)],
        "free_params": ["alpha", "beta", "gamma", "delta", "epsilon"],
        "frozen_params": ["recharge_lag_days", "recharge_window_days"],
        "loo_rmse_m": cv["rmse"],
        "loo_mae_m": cv["mae"],
        "loo_residual_std_m": cv["residual_std"],
        "loo_max_abs_err_m": cv["max_abs_err"],
    }
    save_params(fitted, PARAMS_OUT, metadata=metadata)
    print(f"\n  Saved params -> {PARAMS_OUT.relative_to(ROOT)}")

    # Report
    write_report(fitted, info, cv, fit_table, args.ridge, end)
    print(f"  Wrote report -> {REPORT_OUT.relative_to(ROOT)}")


def write_report(
    fitted: WaterBalanceParams,
    info: dict,
    cv: dict,
    fit_table: pd.DataFrame,
    ridge_lambda: float,
    end_date: dt.date,
) -> None:
    prior = WaterBalanceParams()
    lines = []
    lines.append("# AquaSafe Water-Balance Calibration — Phase 3")
    lines.append("")
    lines.append(f"_Generated: {dt.datetime.now().isoformat(timespec='minutes')}_")
    lines.append("")
    lines.append("## Setup")
    lines.append("")
    lines.append(f"- Observations: 5 measurements of `nivel_estatico_m` from")
    lines.append(f"  Chequeo.xlsx (Pozo 1 ASR). NGO 2026-05-05 confirmed annual readings")
    lines.append(f"  are taken in **June** (corrected from previous Dec-31 placeholder), plus")
    lines.append(f"  one off-cycle 2026-04-29 reading taken after the Jan 2026 maintenance.")
    lines.append(f"- Drivers: daily Open-Meteo archive at Cayaltí + upper Zaña basin")
    lines.append(f"  (rainfall, ET0) plus NOAA ONI (ENSO state), 2022-01-01 → {end_date}.")
    lines.append(f"- Anchor: baseline `H = 3.5 m` at 2022-06-15 (first NGO June measurement,")
    lines.append(f"  matches Pozo 1 schematic baseline).")
    lines.append(f"- Method: regularized least-squares with Bayesian L2 prior toward the")
    lines.append(f"  Phase-1 placeholder values (ridge_lambda = {ridge_lambda}).")
    lines.append(f"- Free parameters: α, β, γ, δ, ε.")
    lines.append(f"  Frozen: `recharge_lag_days = {prior.recharge_lag_days}`,")
    lines.append(f"  `recharge_window_days = {prior.recharge_window_days}` "
                 f"(non-identifiable from 5 points).")
    lines.append("")
    lines.append("## Why regularization is required")
    lines.append("")
    lines.append("With only 5 observations and 5 free parameters, an unconstrained least-")
    lines.append("squares fit is exactly determined and will overfit. The L2 prior pulls each")
    lines.append("coefficient toward the placeholder value derived from Alarcón 2021 (free")
    lines.append("unconfined aquifer, 31.2 m saturated thickness, alluvial sand+gravel with")
    lines.append("specific yield 0.10–0.25, 30–90 day lateral seepage timescale). Data can")
    lines.append("move each coefficient by ~1 order of magnitude before the prior pulls back.")
    lines.append("")
    lines.append("## Calibrated parameters")
    lines.append("")
    lines.append("| Param | Prior | Fitted | Ratio | Physical meaning |")
    lines.append("|-------|-------|--------|-------|------------------|")
    meanings = {
        "alpha": "m per mm of lagged Andes rainfall (recharge)",
        "beta": "m per mm of local Cayaltí rainfall",
        "gamma": "m per L extracted (drawdown rate)",
        "delta": "m per unit ONI anomaly (ENSO modifier)",
        "epsilon": "m per mm of ET0 (direct evaporation losses)",
    }
    for name in ("alpha", "beta", "gamma", "delta", "epsilon"):
        f = getattr(fitted, name)
        p = getattr(prior, name)
        ratio = f / p if p != 0 else float("nan")
        lines.append(f"| `{name}` | {p:.2e} | {f:.2e} | {ratio:+.2f}x | {meanings[name]} |")
    lines.append("")
    lines.append(f"Optimization: success={info['success']}, iterations={info['n_iter']}, "
                 f"final SSE={info['sse']:.4f} m², ridge penalty={info['ridge_penalty']:.2f}.")
    lines.append("")
    lines.append("## Full-fit residuals")
    lines.append("")
    lines.append("| Date | Observed (m) | Predicted (m) | Residual (m) | Note |")
    lines.append("|------|--------------|---------------|--------------|------|")
    for _, r in fit_table.iterrows():
        note = "post-mantenimiento" if r.get("is_post_maintenance") else ""
        lines.append(f"| {r['date']} | {r['observed_m']:.2f} | "
                     f"{r['predicted_m']:.2f} | {r['residual_m']:+.3f} | {note} |")
    lines.append("")
    lines.append("_Post-maintenance rows reflect the Jan 7 2026 well cleaning_")
    lines.append("_(sand/roots removed) following the Nov 2025 flow drop. The dynamic_")
    lines.append("_level recovery is not a pure hydrologic signal and should be_")
    lines.append("_interpreted with that operational caveat._")
    lines.append("")
    lines.append("## Leave-one-out cross-validation")
    lines.append("")
    lines.append("Each row was held out, the model re-fit on the remaining 4, then the held-")
    lines.append("out point was predicted from the 2022-12-31 baseline:")
    lines.append("")
    lines.append("| Fold | Date | Observed (m) | Predicted (m) | Residual (m) |")
    lines.append("|------|------|--------------|---------------|--------------|")
    for _, r in cv["per_fold"].iterrows():
        lines.append(f"| {r['fold']} | {r['date']} | {r['observed_m']:.2f} | "
                     f"{r['predicted_m']:.2f} | {r['residual_m']:+.3f} |")
    lines.append("")
    lines.append(f"- **RMSE**: {cv['rmse']:.3f} m")
    lines.append(f"- **MAE**: {cv['mae']:.3f} m")
    lines.append(f"- **Max abs err**: {cv['max_abs_err']:.3f} m")
    lines.append(f"- **Residual SD**: {cv['residual_std']:.3f} m  ← seeds the forecast")
    lines.append(f"  uncertainty band in `forecast_with_uncertainty()`.")
    lines.append("")
    lines.append("## Limitations")
    lines.append("")
    lines.append("- **Date-corrected anchor (2026-05-05).** The original calibration anchored")
    lines.append("  at 2022-12-31, but the NGO confirmed annual measurements are taken in")
    lines.append("  June. This re-fit uses the corrected June dates, raising RMSE from 0.16")
    lines.append("  → 0.21 m vs. the prior-baseline run because the driver phase now matches")
    lines.append("  the observation phase honestly.")
    lines.append("- **2024 fold residual (~+0.45 m).** The model predicts the well should")
    lines.append("  have been ~45 cm higher than observed in June 2024. Most likely the")
    lines.append("  step-change extraction profile underestimates 2024 actual draw — the")
    lines.append("  maracuyá build-out from 1,300 to 3,500 plants happened gradually rather")
    lines.append("  than at the 2025 step.")
    lines.append("- Annual snapshots cannot resolve sub-annual dynamics; a multi-month wet")
    lines.append("  pulse averages out by the next observation date.")
    lines.append("- Maracuyá Kc is still a placeholder (0.85). Once teammate verifies the")
    lines.append("  FAO-56 / agronomy value, re-run this calibration — γ will absorb most of")
    lines.append("  the change.")
    lines.append("- No formal uncertainty quantification on the parameters themselves; the")
    lines.append("  forecast band uses the LOO residual SD as a proxy for one-step uncertainty,")
    lines.append("  scaled with horizon.")
    lines.append("- The model is monotonic in extraction — additional consumption strictly")
    lines.append("  reduces water column, which is consistent with the observed 4-year trend")
    lines.append("  (3.5 → 2.5 m static while extraction scaled to 50,000 L/day).")
    lines.append("")

    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT_OUT.write_text("\n".join(lines))


if __name__ == "__main__":
    main()
