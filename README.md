# CropGuard / AquaSafe

**Agricultural Vulnerability & Water Security Monitor for Lambayeque, Peru**  
Built in partnership with [Sayariy-Resurgiendo NGO](https://sayariyperu.org)

CropGuard combines free Sentinel-2 satellite imagery, groundwater monitoring, and Peru's coastal El Niño index (ICEN) to protect smallholder farming communities in Lambayeque. It detects crop stress 3–4 weeks before visible damage appears and delivers plain-Spanish recommendations to NGO field teams — including a mobile-first view designed for workers with limited technical background.

**Live dashboard:** https://cropguard-0k17.onrender.com  
**Field-worker app:** https://sayariy-water-watch-3a7b70a1.pages.dev (React frontend)

---

## What was built and why

### Original system
The project started as a Sentinel-2 crop stress monitor: download satellite imagery every 5 days, compute NDVI/NDWI/EVI vegetation indices per community, run a Random Forest stress classifier, and generate Spanish-language alerts via Claude Haiku.

### Updates made (May 2026)

#### 1. Groundwater monitoring tab (`app/pozos_callbacks.py`, `app/pozos_layout.py`)
**Why:** The NGO's primary concern in Cayaltí is not just crop stress but whether the solar-powered well (Pozo 1) has enough water to irrigate. Added a full water monitoring tab showing:
- Well level gauge and history (Pozo 1 ASR, Pozo 2 backup)
- Water balance forecast model (`src/water_balance.py`): lumped-parameter H(t) = α·recharge + β·rain − γ·extraction + δ·ENSO − ε·ET₀, calibrated with LOO-CV against 5 NGO field measurements (RMSE 0.231 m)
- 30-member ensemble forecast (GFS-GEFS via Open-Meteo) with uncertainty bands
- Days until critical level warning
- Manual measurement form for field staff

#### 2. Peru coastal El Niño index — ICEN (`src/data_sources/imarpe_icen.py`)
**Why:** The global ONI index (Niño 3.4 region) showed neutral in April 2026 (+0.11°C) while Peru's coastal ICEN (Niño 1+2 region, ENFEN thresholds) showed El Niño Fuerte (+1.52°C). This is the exact divergence that caused the catastrophic 2017 floods in Lambayeque — if you only watch ONI, you miss the real coastal risk entirely.

ICEN is sourced from NOAA Niño 1+2 SST data and classified using ENFEN thresholds (≥+0.4°C = Costero, ≥+1.0°C = Fuerte, ≥+2.0°C = Extraordinario). The ENSO card in the dashboard now shows ICEN as the primary index with ONI as secondary context.

#### 3. Extended meteorological data (`src/data_sources/open_meteo.py`)
**Why:** The original implementation only fetched daily precipitation and ET₀. Added:
- Relative humidity (max/min) — needed for disease risk assessment (RH > 85% triggers fungal warnings for maracuyá and mango)
- Solar radiation — direct input for the water balance model
- VPD (vapour pressure deficit) — computed from Tmax + RH_min via FAO-56 Magnus formula (the Open-Meteo API does not expose VPD as a daily variable; computing it client-side from tmax × rh_min is actually more accurate for peak daily crop stress)
- Soil moisture forecast (hourly Open-Meteo → daily aggregated, 3 depths: 0–1 cm, 1–3 cm, 3–9 cm) — used as input for crop recommendations

#### 4. NASA POWER API (`src/data_sources/nasa_power.py`)
**Why:** Added NASA's free agricultural-grade meteorological archive (1981–present, no auth required) as a long-term climate baseline. Used for computing SPI-3 (Standardized Precipitation Index) drought monitoring using gamma distribution fitting via scipy. The 40-year climatology lets us contextualise whether a dry spell is unusual or normal for Lambayeque.

#### 5. FAO-56 crop water coefficients corrected (`src/water_balance.py`)
**Why:** The original Kc values were rough placeholders. Corrected against FAO Irrigation Paper 56 (Allen et al. 1998) for the actual crops grown in Cayaltí-Zaña:

| Crop | Old Kc | Corrected Kc | Impact |
|---|---|---|---|
| Maracuyá | 0.85 | 1.05 | +23% water demand |
| Mango | 0.85 | 1.05 | +23% water demand |
| Palta (avocado) | 0.85 | 1.00 | +18% water demand |
| Tuna (cactus) | 0.50 | 0.35 | −30% (much more drought-tolerant) |
| Papaya | 1.05 | 1.10 | +5% water demand |

These corrections materially change the water balance model's extraction estimates and therefore the days-until-critical forecasts.

#### 6. ENSO-aware crop recommendation engine (`src/crop_recommendation.py`)
**Why:** With ICEN at +1.52°C (El Niño Fuerte), the risk profile for different crops changes dramatically — based on French et al. (2023, PLOS ONE) analysis of the 2017 El Niño impact on Lambayeque agriculture. The engine generates plain-Spanish recommendations based on:
- Current ICEN state and anomaly
- Season (flood season Jan–Apr, dry season May–Sep, approach season Oct–Dec)
- Soil moisture and well level
- Crop-specific El Niño vulnerability (rice/sugarcane high-risk; mango/avocado resilient)
- Cayaltí-Zaña salinization risk (INIA/Concytec documented)

#### 7. Vista Sencilla tab (`app/sencilla_callbacks.py`, `app/sencilla_layout.py`)
**Why:** NGO field workers have limited formal education and use smartphones in the field. The technical Dash dashboard is too complex for them. Built a simplified view with:
- Traffic-light status (verde / amarillo / rojo) — no numbers needed
- Visual tank gauge (fill bar)
- 7-day forecast as weather emoji strip
- Plain-Spanish irrigation recommendation
- Active alerts without technical jargon
- Crop recommendations

#### 8. REST API for the React frontend (`app/api.py`)
**Why:** Built a second React-based frontend (Lovable, hosted on Cloudflare Pages) with better mobile UX. The Dash app's Flask server now exposes a REST API (`/api/v1/*`) so the React app can fetch real model data without duplicating any logic.

Endpoints:
- `GET /api/v1/status` — traffic-light + ICEN summary
- `GET /api/v1/well` — well depth and percent capacity
- `GET /api/v1/forecast` — 7-day weather with emoji codes
- `GET /api/v1/enso` — ICEN + ONI state
- `GET /api/v1/irrigation` — riego yes/no/esencial recommendation
- `GET /api/v1/crops` — ENSO-aware crop recommendations
- `GET /api/v1/alerts` — active alerts in plain Spanish
- `GET /api/v1/communities` — NDVI/NDWI/EVI + stress probability per community
- `GET /api/v1/communities/<id>/timeseries` — historical index series

CORS is enabled for all `/api/*` routes (`flask-cors`).

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│              Render (Python backend)                │
│                                                     │
│  app/app.py  ─── Dash dashboard (technical UI)      │
│             └─── /api/v1/* REST endpoints           │
│                        │                            │
│  src/                  │                            │
│  ├── water_balance.py  │  ← lumped-parameter model  │
│  ├── crop_recommendation.py  ← ICEN + FAO-56        │
│  ├── model.py          │  ← Random Forest           │
│  └── data_sources/     │                            │
│      ├── open_meteo.py │  ← forecast + ERA5         │
│      ├── imarpe_icen.py│  ← Peru coastal ENSO       │
│      ├── noaa_oni.py   │  ← global ONI              │
│      └── nasa_power.py │  ← 40-yr climate archive   │
└───────────────────────┬─────────────────────────────┘
                        │ JSON via fetch
┌───────────────────────▼─────────────────────────────┐
│       Cloudflare Pages (React frontend)             │
│                                                     │
│  /campo     ← field-worker view (simple, mobile)   │
│  /pozos     ← well level + rain forecast            │
│  /cultivos  ← community health + crop recs         │
│  /dashboard ← technical panel (NDVI table)         │
└─────────────────────────────────────────────────────┘
```

---

## Quick start

```bash
# 1. Clone and install dashboard dependencies
git clone https://github.com/lorepini/sayari-cropguard.git
cd sayari-cropguard
pip install -r requirements.txt

# 2. Set up credentials
cp .env.example .env
# Edit .env — only ANTHROPIC_API_KEY is required for alerts
# CDSE_USER / CDSE_PASSWORD only needed if running the Sentinel-2 pipeline

# 3. Launch the dashboard (works immediately with demo data)
python app/app.py
# Open http://localhost:8051

# 4. (Optional) Run the Sentinel-2 pipeline to fetch real imagery
pip install -r requirements-pipeline.txt   # adds rasterio + sentinelsat
python pipeline.py --scenes 3
```

> **Note:** `requirements.txt` contains only dashboard runtime dependencies. `requirements-pipeline.txt` adds rasterio and sentinelsat for Sentinel-2 data ingestion — only needed locally, not on Render.

---

## Project structure

```
sayari-cropguard/
├── app/
│   ├── app.py                  # Dash entry point + Flask REST API mount
│   ├── api.py                  # REST blueprint (/api/v1/*)
│   ├── layout.py               # Main dashboard layout (3 tabs)
│   ├── callbacks.py            # Cultivos tab callbacks
│   ├── pozos_callbacks.py      # Pozos tab callbacks + water balance
│   ├── pozos_layout.py         # Pozos tab layout
│   ├── sencilla_callbacks.py   # Vista Sencilla tab callbacks
│   └── sencilla_layout.py      # Vista Sencilla tab layout
├── src/
│   ├── water_balance.py        # Lumped-parameter groundwater model
│   ├── crop_recommendation.py  # ENSO-aware crop recommendation engine
│   ├── model.py                # Random Forest stress scorer
│   ├── alerts.py               # Claude Haiku alert generation
│   ├── auth.py                 # Flask session auth (write protection)
│   ├── download.py             # Sentinel-2 download (pipeline only)
│   ├── indices.py              # NDVI/NDWI/EVI computation (pipeline only)
│   └── data_sources/
│       ├── open_meteo.py       # Forecast + ERA5 + ensemble + soil moisture
│       ├── imarpe_icen.py      # Peru coastal El Niño index (ICEN/ENFEN)
│       ├── noaa_oni.py         # Global ONI index
│       ├── nasa_power.py       # 40-year climate archive (SPI baseline)
│       └── andes_rainfall.py   # Andes basin recharge data
├── data/
│   ├── communities/
│   │   └── lambayeque_communities.geojson
│   ├── raw/                    # Sentinel-2 scenes (gitignored)
│   └── processed/
│       ├── wells_history.parquet   # NGO well measurements
│       ├── index_history.parquet   # NDVI/NDWI/EVI history
│       └── water_balance_params.json
├── pipeline.py                 # End-to-end Sentinel-2 pipeline
├── config.py                   # Central configuration + thresholds
├── requirements.txt            # Dashboard runtime deps
├── requirements-pipeline.txt   # Pipeline-only deps (rasterio etc.)
├── render.yaml                 # Render deployment config
└── Dockerfile                  # Docker image (python:3.11-slim)
```

---

## Data sources

| Source | Data | Cost |
|---|---|---|
| ESA Copernicus (CDSE) | Sentinel-2 L2A imagery | Free |
| Open-Meteo | Forecast, ERA5 archive, ensemble (GFS-GEFS 30 members) | Free |
| NOAA CPC | Niño 1+2 and Niño 3.4 SST anomalies (ICEN + ONI) | Free |
| NASA POWER | Agricultural meteorology 1981–present | Free |
| Anthropic Claude Haiku | Spanish-language alert generation | ~€0.10/year |

---

## Communities monitored

| Community | Province | Primary crops |
|---|---|---|
| Cayaltí | Chiclayo, Lambayeque | Maracuyá, caña de azúcar, arroz |
| Nueva Libertad | Chiclayo, Lambayeque | Agricultura familiar mixta |
| Víctor Raúl | Chiclayo, Lambayeque | Maracuyá, hortalizas |
| Reque | Chiclayo, Lambayeque | Hortalizas periurbanas |
| Monsefú | Chiclayo, Lambayeque | Agricultura tradicional |

---

## Key scientific references

- **French et al. (2023)**. *El Niño impacts on smallholder agriculture in Lambayeque, Peru.* PLOS ONE. — Crop-specific El Niño vulnerability data used in recommendations.
- **Allen et al. (1998)**. *Crop evapotranspiration — FAO Irrigation Paper 56.* FAO. — Source for all Kc crop water coefficient values.
- **Quintanilla et al. (2024)**. *Multiseasonal analysis of rice crop yield prediction with Sentinel-2 in Lambayeque.* ISPRS Archives XLVIII-3-2024. — Basis for NDVI/NDWI stress thresholds.
- **ENFEN/IMARPE**. *Índice Costero El Niño (ICEN).* — Peru-specific coastal El Niño classification (diverges significantly from global ONI in years like 2017 and 2026).

---

## SDG alignment

- **SDG 2** — Zero Hunger: early warning for crop stress
- **SDG 1** — No Poverty: protecting smallholder livelihoods
- **SDG 13** — Climate Action: ENSO-adaptive agricultural guidance

---

*ESADE BAIB · Perspectives on AI, Business and Sustainability · Demo May 14, 2026*
