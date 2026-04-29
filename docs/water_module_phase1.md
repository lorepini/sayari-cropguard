# Water Module — Phase 1 Summary
**Date:** 2026-04-29
**Status:** Phase 1 complete. Ready for Phase 2 (data fetchers).

---

## 1. What changed since the kick-off plan

Originally we planned to scrape **ANA Peru SNIRH** for Río Zaña gauge data. After verifying:

- ANA SNIRH portal exists but has **no public API**, web requests time out, no stable CSV endpoint.
- SENAMHI has the same limitation.

**Decision:** drop direct gauge scraping. Use **CHIRPS satellite rainfall** over the upper Zaña basin as a **recharge proxy** (Andes rainfall → Río Zaña discharge → lateral seepage → well). This is academically standard, free, public-domain, and avoids dependency on a flaky government portal. Same physical signal, more reliable.

---

## 2. Confirmed free data sources (Phase 1 deliverable)

| Source | What it gives us | Endpoint / Method | Auth | Status |
|---|---|---|---|---|
| **Open-Meteo** | Daily precipitation + ET₀ (FAO) for Cayaltí, 14-day forecast | `https://api.open-meteo.com/v1/forecast?latitude=-6.91&longitude=-79.51&daily=precipitation_sum,et0_fao_evapotranspiration&forecast_days=14&timezone=America/Lima` | None | ✅ Tested |
| **NOAA ONI** | ENSO state (3-month rolling), 1950-present | `https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt` (plain text, fixed-width) | None | ✅ Tested. Current state (JFM 2026): ANOM = -0.16 → **neutral** |
| **CHIRPS v2** | Daily 0.05° satellite rainfall over upper Zaña basin (recharge proxy) | Google Earth Engine: `UCSB-CHG/CHIRPS/DAILY` | GEE account (free) | ✅ Confirmed |
| **Sentinel-2** | NDVI/NDWI/EVI per parcel (already wired) | Copernicus CDSE | Already configured | ✅ Working |
| **Anthropic Claude Haiku** | Spanish-language explanations of well status | Anthropic API | Existing key (currently blank, to enable) | ✅ |

**Cost: €0** for all data sources. Anthropic usage estimated ~€0.10/year.

---

## 3. Schema decisions

### 3.1 New parquet: `data/processed/wells_history.parquet`

Time-indexed history of well measurements + model predictions, one row per (well_id × date).

| Column | Type | Source | Notes |
|---|---|---|---|
| `date` | date | n/a | Primary key part 1 |
| `well_id` | string | manual | Primary key part 2. Initial value: `"pozo1_asr"` |
| `nivel_estatico_m` | float | NGO measurement | Manual quarterly entry from NGO Excel |
| `nivel_dinamico_m` | float | NGO measurement | Manual quarterly entry from NGO Excel |
| `nivel_predicho_m` | float | water balance model | Predicted N. Estático |
| `nivel_predicho_low_m` | float | model uncertainty band | 5th percentile |
| `nivel_predicho_high_m` | float | model uncertainty band | 95th percentile |
| `is_forecast` | bool | derived | True for future-dated rows |
| `extraction_l_per_day` | float | NGO data | Daily water extraction |
| `crop_demand_l_per_day` | float | FAO Kc × ET₀ × area | Computed |
| `recharge_proxy_mm` | float | CHIRPS upper basin | Lagged rainfall integral |
| `local_rainfall_mm` | float | Open-Meteo | Daily local rain |
| `et0_mm` | float | Open-Meteo | Daily reference ET |
| `oni_anom` | float | NOAA ONI | Current 3-mo ENSO anomaly |
| `enso_state` | string | derived | `el_nino` / `la_nina` / `neutral` |
| `model_version` | string | n/a | For reproducibility |

### 3.2 New static config: `data/wells/wells.geojson`

Well metadata (one feature per well — for now just `pozo1_asr`):

```json
{
  "type": "FeatureCollection",
  "features": [{
    "type": "Feature",
    "geometry": {"type": "Point", "coordinates": [-79.51, -6.91]},
    "properties": {
      "well_id": "pozo1_asr",
      "name": "Pozo 1 ASR",
      "association": "Sayariy-Resurgiendo",
      "district": "Cayaltí",
      "drilled_depth_m": null,
      "recommended_depth_m": 48,
      "water_table_depth_m": 12,
      "aquifer_thickness_m": 31.2,
      "aquifer_base_m": 43.2,
      "aquifer_type": "free_unconfined",
      "primary_recharge": "rio_zaña_lateral_seepage",
      "primary_crop": "maracuya",
      "n_plants_maracuya": 3500,
      "n_huertos": 20,
      "current_extraction_l_per_day": 45000,
      "last_maintenance": "2026-01-07",
      "study_reference": "Alarcón 2021"
    }
  }]
}
```

> Open question for the Apr 29 NGO meeting: `drilled_depth_m`, `caudal_l_per_s` (pumping test result), and the measurement convention (column-height vs depth-to-water).

### 3.3 Upper Zaña basin polygon

For CHIRPS spatial integration. Approximate (refine if NGO has a better polygon):
- Bounding box: lon [-79.4, -78.7], lat [-6.95, -6.5] — covers headwaters east of Cayaltí into the Andes
- Will save as `data/wells/upper_zana_basin.geojson` in Phase 2

---

## 4. New code structure (to be created in Phase 2 — NOT YET WRITTEN)

```
sayari-cropguard/
├── src/
│   ├── data_sources/                  ← NEW
│   │   ├── __init__.py
│   │   ├── open_meteo.py              ← rainfall + ET₀
│   │   ├── noaa_oni.py                ← ENSO state
│   │   └── chirps.py                  ← upper basin rainfall via GEE
│   ├── water_balance.py               ← NEW: lumped-parameter model
│   └── (existing files unchanged)
├── data/
│   ├── wells/                         ← NEW
│   │   ├── wells.geojson
│   │   └── upper_zana_basin.geojson
│   └── processed/
│       └── wells_history.parquet      ← NEW (created on first pipeline run)
├── app/
│   ├── pozos_layout.py                ← NEW: Dash tab for wells
│   └── (existing files unchanged)
└── pipeline.py                        ← extended with --fetch-water
```

**Principle:** zero changes to existing crop-stress code. The water module is additive.

---

## 5. Hydrological model (to be built in Phase 3 — NOT YET WRITTEN)

Lumped-parameter water balance, calibrated to the 5-year NGO measurement series:

```
ΔH(t) = α · CHIRPS_recharge(t - τ)         ← Andes rainfall driver, lagged
       + β · local_rainfall(t)              ← Open-Meteo
       − γ · crop_extraction(t)             ← Σ Kc × ET₀ × area + manual extraction
       + δ · ENSO_modifier(ONI(t))          ← climate state
       − ε · ET₀(t)                         ← evaporation losses

H(t) = H(t-1) + ΔH(t)         where H = water column inside well
```

Parameters α, β, γ, δ, ε fit by least squares against the 5 NGO measurements (very few points → use Bayesian priors based on the geophysical study to constrain).

**Forecast horizon:** 90 days, with uncertainty band from parameter posterior + Open-Meteo forecast spread.

---

## 6. Open questions (after NGO docs received Apr 29)

Most original questions were resolved by the new docs (`Pozo - Esquema...xlsx`, `Pozo 2 - Esquema...xlsx`, `Agua.docx`). Remaining:

| # | Question | Affects | Status |
|---|---|---|---|
| 1 | Measurement convention | Sign of model output | ✅ CLOSED — Option B confirmed (Pozo 1 2021 schematic baseline 3.5/2.2 m matches Chequeo.xlsx 2022 baseline) |
| 2 | Actual drilled depth | Capacity ceiling | ✅ CLOSED — Pozo 1: 20.20 m, Pozo 2: 19.20 m (much shallower than recommended 48 m, but operational) |
| 3 | Caudal sostenible from pumping test | Specific yield, days-of-supply | ⚠️ Test pump data only (6.57 m³/h Pozo 1, 5.4 m³/h Pozo 2). Confirm if current Pedrollo pumps were tested separately |
| 4 | **NEW: Pozo 2 coordinates** | Map placement | ⚠️ TBD — not in any document, ask in meeting |
| 5 | Crop layout per parcel | Extraction term γ | ⚠️ Approx values from Agua.docx (3500 maracuyá + 20 huertos) — confirm hectares |

## 6b. KEY NEW FINDING — TWO wells, not one

The NGO operates **Pozo 1** (history-tracked in Chequeo.xlsx) and **Pozo 2** (no history file). Both drilled Nov 2021. Combined sustainable yield ~95,500 L/day vs. ~45,000 L/day current consumption → **53% headroom** = strong "future capacity" story for the demo.

Updated artifacts:
- `data/wells/wells.geojson` now contains both features with full pump + drilling specs
- `data/wells/distribution_system.json` — solar pumping, 50,000 L storage, gravity-fed drip
- `src/water_balance.py` — added `PUMP_CAPACITY_L_PER_DAY = 95500` ceiling on `crop_demand_l_per_day()`

---

## 7. Phase 2 plan (May 1-3)

- [ ] Implement `src/data_sources/open_meteo.py` + integration test
- [ ] Implement `src/data_sources/noaa_oni.py` + parser for fixed-width text
- [ ] Implement `src/data_sources/chirps.py` (Google Earth Engine setup + integration over basin polygon)
- [ ] Create `data/wells/wells.geojson` and `upper_zana_basin.geojson`
- [ ] Bootstrap `wells_history.parquet` from `Chequeo.xlsx` (5 historical rows for `pozo1_asr`)
- [ ] Extend `pipeline.py` with `--fetch-water` flag

---

## 8. Phase 1 done — what unblocks Phase 2

✅ NGO study findings + 5-year history saved to memory
✅ All free data sources verified reachable
✅ Pivot decision logged (CHIRPS over ANA SNIRH)
✅ Schema drafted (parquet + geojson)
✅ Code structure planned (zero impact on existing crop-stress code)

**Blocker for Phase 2 from Phase 1:** None. Phase 2 can start tomorrow.
**Blocker from outside:** Maracuyá Kc value (teammate task #2) and NGO meeting answers — both expected within 24-48 h. Phase 2 can begin without them; Phase 3 (model) cannot.
