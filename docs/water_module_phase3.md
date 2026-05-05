# AquaSafe Water-Balance Calibration — Phase 3

_Generated: 2026-05-05T12:24_

## Setup

- Observations: 5 measurements of `nivel_estatico_m` from
  Chequeo.xlsx (Pozo 1 ASR). NGO 2026-05-05 confirmed annual readings
  are taken in **June** (corrected from previous Dec-31 placeholder), plus
  one off-cycle 2026-04-29 reading taken after the Jan 2026 maintenance.
- Drivers: daily Open-Meteo archive at Cayaltí + upper Zaña basin
  (rainfall, ET0) plus NOAA ONI (ENSO state), 2022-01-01 → 2026-05-03.
- Anchor: baseline `H = 3.5 m` at 2022-06-15 (first NGO June measurement,
  matches Pozo 1 schematic baseline).
- Method: regularized least-squares with Bayesian L2 prior toward the
  Phase-1 placeholder values (ridge_lambda = 0.05).
- Free parameters: α, β, γ, δ, ε.
  Frozen: `recharge_lag_days = 14`,
  `recharge_window_days = 60` (non-identifiable from 5 points).

## Why regularization is required

With only 5 observations and 5 free parameters, an unconstrained least-
squares fit is exactly determined and will overfit. The L2 prior pulls each
coefficient toward the placeholder value derived from Alarcón 2021 (free
unconfined aquifer, 31.2 m saturated thickness, alluvial sand+gravel with
specific yield 0.10–0.25, 30–90 day lateral seepage timescale). Data can
move each coefficient by ~1 order of magnitude before the prior pulls back.

## Calibrated parameters

| Param | Prior | Fitted | Ratio | Physical meaning |
|-------|-------|--------|-------|------------------|
| `alpha` | 5.00e-06 | 0.00e+00 | +0.00x | m per mm of lagged Andes rainfall (recharge) |
| `beta` | 1.00e-05 | 1.17e-05 | +1.17x | m per mm of local Cayaltí rainfall |
| `gamma` | 1.50e-08 | 2.76e-09 | +0.18x | m per L extracted (drawdown rate) |
| `delta` | 1.00e-03 | 2.89e-04 | +0.29x | m per unit ONI anomaly (ENSO modifier) |
| `epsilon` | 5.00e-05 | 1.58e-04 | +3.16x | m per mm of ET0 (direct evaporation losses) |

Optimization: success=True, iterations=25, final SSE=0.1224 m², ridge penalty=6.87.

## Full-fit residuals

| Date | Observed (m) | Predicted (m) | Residual (m) | Note |
|------|--------------|---------------|--------------|------|
| 2022-06-15 | 3.50 | 3.50 | -0.001 |  |
| 2023-06-15 | 3.00 | 3.21 | +0.208 |  |
| 2024-06-15 | 2.80 | 3.08 | +0.281 |  |
| 2025-06-15 | 2.80 | 2.79 | -0.006 |  |
| 2026-04-29 | 2.50 | 2.50 | +0.001 | post-mantenimiento |

_Post-maintenance rows reflect the Jan 7 2026 well cleaning_
_(sand/roots removed) following the Nov 2025 flow drop. The dynamic_
_level recovery is not a pure hydrologic signal and should be_
_interpreted with that operational caveat._

## Leave-one-out cross-validation

Each row was held out, the model re-fit on the remaining 4, then the held-
out point was predicted from the 2022-12-31 baseline:

| Fold | Date | Observed (m) | Predicted (m) | Residual (m) |
|------|------|--------------|---------------|--------------|
| 0 | 2022-06-15 | 3.50 | 3.50 | -0.001 |
| 1 | 2023-06-15 | 3.00 | 3.18 | +0.179 |
| 2 | 2024-06-15 | 2.80 | 3.26 | +0.464 |
| 3 | 2025-06-15 | 2.80 | 2.81 | +0.006 |
| 4 | 2026-04-29 | 2.50 | 2.36 | -0.138 |

- **RMSE**: 0.231 m
- **MAE**: 0.158 m
- **Max abs err**: 0.464 m
- **Residual SD**: 0.207 m  ← seeds the forecast
  uncertainty band in `forecast_with_uncertainty()`.

## Limitations

- **Date-corrected anchor (2026-05-05).** The original calibration anchored
  at 2022-12-31, but the NGO confirmed annual measurements are taken in
  June. This re-fit uses the corrected June dates, raising RMSE from 0.16
  → 0.21 m vs. the prior-baseline run because the driver phase now matches
  the observation phase honestly.
- **2024 fold residual (~+0.45 m).** The model predicts the well should
  have been ~45 cm higher than observed in June 2024. Most likely the
  step-change extraction profile underestimates 2024 actual draw — the
  maracuyá build-out from 1,300 to 3,500 plants happened gradually rather
  than at the 2025 step.
- Annual snapshots cannot resolve sub-annual dynamics; a multi-month wet
  pulse averages out by the next observation date.
- Maracuyá Kc is still a placeholder (0.85). Once teammate verifies the
  FAO-56 / agronomy value, re-run this calibration — γ will absorb most of
  the change.
- No formal uncertainty quantification on the parameters themselves; the
  forecast band uses the LOO residual SD as a proxy for one-step uncertainty,
  scaled with horizon.
- The model is monotonic in extraction — additional consumption strictly
  reduces water column, which is consistent with the observed 4-year trend
  (3.5 → 2.5 m static while extraction scaled to 50,000 L/day).
