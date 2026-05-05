"""
Central configuration for CropGuard.
All AOI definitions, thresholds, and constants live here.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT        = Path(__file__).parent
DATA_DIR    = ROOT / "data"
RAW_DIR     = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
COMMUNITIES_GEOJSON = DATA_DIR / "communities" / "lambayeque_communities.geojson"

# ── Credentials ───────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CDSE_USER         = os.getenv("CDSE_USER", "")
CDSE_PASSWORD     = os.getenv("CDSE_PASSWORD", "")
MAPBOX_TOKEN      = os.getenv("MAPBOX_TOKEN", "")

# ── Sentinel-2 search parameters ──────────────────────────────────────────────
# Bounding box covering all Sayariy communities (lon_min, lat_min, lon_max, lat_max)
AOI_BBOX = (-79.70, -7.05, -79.35, -6.65)

# Max cloud cover % to accept a scene
MAX_CLOUD_COVER = 25

# How many months of history to fetch
HISTORY_MONTHS = 6

# Sentinel-2 bands needed
BANDS = {
    "B02": "blue",       # 490 nm
    "B03": "green",      # 560 nm
    "B04": "red",        # 665 nm
    "B08": "nir",        # 842 nm
    "B8A": "nir_narrow", # 865 nm
    "B11": "swir",       # 1610 nm
    "SCL": "scene_class" # cloud mask
}

# ── Vegetation index thresholds (Lambayeque rice/sugarcane calibrated) ─────────
# Based on: Quintanilla et al. 2024, Lambayeque Sentinel-2 rice study
NDVI_HEALTHY   = 0.55   # NDVI > this = healthy crop
NDVI_WATCH     = 0.35   # NDVI between watch and healthy = monitor
NDVI_ALERT     = 0.35   # NDVI < this = stress alert

NDWI_DRY       = -0.10  # NDWI < this = water-stressed vegetation

# Stress probability threshold to trigger an alert
STRESS_PROB_THRESHOLD = 0.60

# ── Alert configuration ────────────────────────────────────────────────────────
LLM_MODEL      = "claude-haiku-4-5-20251001"   # fast + cheap for alerts
MAX_ALERT_TOKENS = 200

# ── Communities ───────────────────────────────────────────────────────────────
# Used as fallback if GeoJSON is missing
# Coordinates are (lon, lat) polygon corners [approximately 2.5km × 2.5km]
COMMUNITY_CENTERS = {
    "Cayaltí":        (-79.517, -6.883),
    "Nueva Libertad": (-79.548, -6.915),
    "Víctor Raúl":    (-79.490, -6.860),
    "Reque":          (-79.828, -6.875),
    "Monsefú":        (-79.887, -6.889),
}

# ── Sayariy parcel anchor (Pozo 1) ─────────────────────────────────────────────
# Derived from Alarcón 2021 schematic UTM 663913E, 9235271N (zone 17S) →
# WGS84. This is THE coord used by every Open-Meteo / archive call so the
# weather grid samples the actual parcel, not a 1-km-NE placeholder.
SAYARIY_LAT = -6.9161
SAYARIY_LON = -79.5164

# ── Dashboard ─────────────────────────────────────────────────────────────────
MAP_CENTER = {"lat": -6.88, "lon": -79.57}
MAP_ZOOM   = 10
MAP_STYLE  = "open-street-map"  # free, no token needed

STATUS_COLORS = {
    "healthy": "#27AE60",
    "watch":   "#F39C12",
    "alert":   "#E74C3C",
    "no_data": "#95A5A6",
}
