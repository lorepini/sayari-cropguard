# 🌿 CropGuard

**Agricultural Vulnerability & Food Security Monitor for Lambayeque, Peru**  
Built in partnership with [Sayariy-Resurgiendo NGO](https://sayariyperu.org)

CropGuard uses free Sentinel-2 satellite imagery to monitor crop health across smallholder farming communities in northern Peru. It detects vegetation stress 3–4 weeks before visible damage appears and delivers plain-Spanish alerts to NGO field teams.

---

## Features

- **Live NDVI/NDWI/EVI monitoring** — Sentinel-2 imagery every 5 days at 10m resolution
- **AI stress scoring** — Random Forest model predicts crop stress probability per community
- **Spanish-language alerts** — LLM-generated summaries for non-technical NGO staff
- **Interactive Dash dashboard** — map, time series, alert feed, community detail view
- **Zero data cost** — all satellite data from ESA Copernicus (free, open access)

---

## Quick start

```bash
# 1. Clone and install dependencies
git clone https://github.com/lorepini/sayari-cropguard.git
cd sayari-cropguard
pip install -r requirements.txt

# 2. Set up credentials
cp .env.example .env
# Edit .env with your Anthropic API key (optional) and Copernicus credentials

# 3a. Run with demo data (no download needed — works immediately)
python pipeline.py --demo

# 3b. OR fetch real satellite data
python pipeline.py --scenes 3

# 4. Launch the dashboard
python app/app.py
# Open http://localhost:8050
```

---

## Project structure

```
sayari-cropguard/
├── app/
│   ├── app.py           # Dash entry point
│   ├── layout.py        # Dashboard UI layout
│   ├── callbacks.py     # Interactivity & data loading
│   └── assets/
│       └── style.css
├── src/
│   ├── download.py      # Sentinel-2 search & download (CDSE / Element84)
│   ├── indices.py       # NDVI, NDWI, EVI computation + zonal statistics
│   ├── model.py         # Stress scoring + Random Forest model
│   └── alerts.py        # LLM alert generation (Anthropic Claude)
├── data/
│   └── communities/
│       └── lambayeque_communities.geojson   # AOI polygons
├── pipeline.py          # End-to-end pipeline runner
├── config.py            # Central configuration
└── requirements.txt
```

---

## Data sources

| Source | Data | Cost |
|--------|------|------|
| ESA Copernicus | Sentinel-2 L2A (NDVI/NDWI/EVI) | Free |
| Anthropic | Claude Haiku (Spanish alerts) | ~€0.10/year |
| OpenStreetMap | Map tiles | Free |

---

## Communities monitored

- **Cayaltí** — Chiclayo Province, Lambayeque
- **Nueva Libertad** — Chiclayo Province, Lambayeque
- **Víctor Raúl** — Chiclayo Province, Lambayeque
- **Reque** — Chiclayo Province, Lambayeque
- **Monsefú** — Chiclayo Province, Lambayeque

---

## Academic foundation

This project replicates and extends:
> Quintanilla et al. (2024). *Multiseasonal analysis of rice crop yield prediction with Sentinel-2 time series and UAV imagery in Lambayeque (Peru)*. ISPRS Archives, XLVIII-3-2024.

⚠️ **Citation note:** Verify this reference at isprs-archives.copernicus.org before citing in submitted academic work.

---

## SDG alignment

- **SDG 2** — Zero Hunger
- **SDG 1** — No Poverty  
- **SDG 13** — Climate Action

---

*ESADE BAIB · Perspectives on AI, Business and Sustainability · 2026*
