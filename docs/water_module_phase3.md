# AquaSafe Water-Balance Calibration — Phase 3

_Generated: 2026-04-30T14:56_

## Setup

- Observations: 5 annual measurements of `nivel_estatico_m` from
  Chequeo.xlsx (Pozo 1 ASR, 2022-12-31 to 2026-04-29).
- Drivers: daily Open-Meteo archive at Cayaltí + upper Zaña basin
  (rainfall, ET0) plus NOAA ONI (ENSO state), 2022-01-01 → 2026-04-28.
- Anchor: baseline `H = 3.5 m` at 2022-12-31 (Pozo 1 schematic baseline).
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
| `beta` | 1.00e-05 | 4.32e-06 | +0.43x | m per mm of local Cayaltí rainfall |
| `gamma` | 1.50e-08 | 1.08e-08 | +0.72x | m per L extracted (drawdown rate) |
| `delta` | 1.00e-03 | 3.42e-04 | +0.34x | m per unit ONI anomaly (ENSO modifier) |
| `epsilon` | 5.00e-05 | 1.64e-04 | +3.28x | m per mm of ET0 (direct evaporation losses) |

Optimization: success=True, iterations=21, final SSE=0.2223 m², ridge penalty=7.04.

## Full-fit residuals

| Date | Observed (m) | Predicted (m) | Residual (m) |
|------|--------------|---------------|--------------|
| 2022-12-31 | 3.50 | 3.50 | -0.001 |
| 2023-12-31 | 3.00 | 3.33 | +0.333 |
| 2024-12-31 | 2.80 | 3.12 | +0.318 |
| 2025-12-31 | 2.80 | 2.75 | -0.049 |
| 2026-04-29 | 2.50 | 2.59 | +0.092 |

## Leave-one-out cross-validation

Each row was held out, the model re-fit on the remaining 4, then the held-
out point was predicted from the 2022-12-31 baseline:

| Fold | Date | Observed (m) | Predicted (m) | Residual (m) |
|------|------|--------------|---------------|--------------|
| 0 | 2022-12-31 | 3.50 | 3.50 | -0.000 |
| 1 | 2023-12-31 | 3.00 | 3.20 | +0.201 |
| 2 | 2024-12-31 | 2.80 | 2.99 | +0.187 |
| 3 | 2025-12-31 | 2.80 | 2.58 | -0.220 |
| 4 | 2026-04-29 | 2.50 | 2.60 | +0.097 |

- **RMSE**: 0.163 m
- **MAE**: 0.141 m
- **Max abs err**: 0.220 m
- **Residual SD**: 0.154 m  ← seeds the forecast
  uncertainty band in `forecast_with_uncertainty()`.

## Limitations

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
  (3.5 → 2.5 m static while extraction tripled).
