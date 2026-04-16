"""
Crop stress prediction model.

Phase 1 (now):   Rule-based scoring from NDVI/NDWI thresholds.
Phase 2 (later): Random Forest trained on historical Lambayeque data.

Saves/loads the trained model to data/processed/model.joblib.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import joblib
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import classification_report
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

import config


MODEL_PATH = config.PROCESSED_DIR / "model.joblib"
HISTORY_PATH = config.PROCESSED_DIR / "index_history.parquet"


# ── Rule-based scorer (Phase 1 — no training data needed) ────────────────────

def rule_based_stress_score(
    ndvi: float,
    ndwi: float | None = None,
    ndvi_trend: float | None = None,
) -> float:
    """
    Returns a stress probability in [0, 1] using thresholds.

    ndvi_trend: difference between current NDVI and 30-day mean
                negative trend = worsening
    """
    score = 0.0

    # NDVI component (weight 0.6)
    if np.isnan(ndvi):
        return np.nan
    if ndvi < config.NDVI_ALERT:
        ndvi_score = 1.0
    elif ndvi < config.NDVI_HEALTHY:
        ndvi_score = (config.NDVI_HEALTHY - ndvi) / (config.NDVI_HEALTHY - config.NDVI_ALERT)
    else:
        ndvi_score = 0.0
    score += 0.6 * ndvi_score

    # NDWI component (weight 0.25) — low NDWI = water stressed
    if ndwi is not None and not np.isnan(ndwi):
        if ndwi < config.NDWI_DRY:
            ndwi_score = min(1.0, abs(ndwi - config.NDWI_DRY) / 0.3)
        else:
            ndwi_score = 0.0
        score += 0.25 * ndwi_score

    # Trend component (weight 0.15) — declining NDVI adds risk
    if ndvi_trend is not None and not np.isnan(ndvi_trend):
        trend_score = max(0.0, min(1.0, -ndvi_trend / 0.2))
        score += 0.15 * trend_score
    elif ndwi is None:
        # Redistribute weight if NDWI/trend not available
        score = min(1.0, score / 0.6)

    return round(min(1.0, score), 3)


def score_communities(gdf) -> "pd.DataFrame | gpd.GeoDataFrame":
    """
    Given a GeoDataFrame with NDVI (and optionally NDWI) columns,
    add a 'stress_prob' column and return.
    """
    import geopandas as gpd

    gdf = gdf.copy()

    scores = []
    for _, row in gdf.iterrows():
        ndvi  = row.get("NDVI", np.nan)
        ndwi  = row.get("NDWI", None)
        trend = row.get("NDVI_trend", None)
        scores.append(rule_based_stress_score(ndvi, ndwi, trend))

    gdf["stress_prob"] = scores
    gdf["alert"] = gdf["stress_prob"] >= config.STRESS_PROB_THRESHOLD
    return gdf


# ── Random Forest (Phase 2 — call train_model() when you have history) ────────

def build_features(history_df: pd.DataFrame) -> pd.DataFrame:
    """
    Build ML features from a time series DataFrame.

    Expected columns: community_id, date, NDVI, NDWI, EVI
    Returns feature matrix ready for scikit-learn.
    """
    history_df = history_df.sort_values(["community_id", "date"])
    features = []

    for community_id, grp in history_df.groupby("community_id"):
        grp = grp.set_index("date").sort_index()
        for i in range(2, len(grp)):
            row = grp.iloc[i]
            prev = grp.iloc[i - 1]
            mean30 = grp.iloc[max(0, i - 6):i]["NDVI"].mean()  # ~30d (5d cadence)
            std30  = grp.iloc[max(0, i - 6):i]["NDVI"].std()

            features.append({
                "community_id":  community_id,
                "date":          grp.index[i],
                "NDVI":          row.get("NDVI", np.nan),
                "NDWI":          row.get("NDWI", np.nan),
                "EVI":           row.get("EVI",  np.nan),
                "dNDVI":         row.get("NDVI", np.nan) - prev.get("NDVI", np.nan),
                "NDVI_mean30":   mean30,
                "NDVI_std30":    std30,
                "NDVI_z":        (row.get("NDVI", np.nan) - mean30) / (std30 + 1e-6),
                "DOY":           pd.Timestamp(grp.index[i]).dayofyear,
            })

    return pd.DataFrame(features)


def train_model(
    history_df: pd.DataFrame,
    label_col: str = "stressed",
) -> "RandomForestClassifier":
    """
    Train a Random Forest on historical index time series.

    history_df must contain a binary 'stressed' column (1 = stressed, 0 = healthy).
    Saves the model to data/processed/model.joblib.
    """
    if not SKLEARN_AVAILABLE:
        raise ImportError("scikit-learn is required for model training.")

    feat_df = build_features(history_df)
    feat_df = feat_df.dropna(subset=["NDVI", label_col])

    X = feat_df[["NDVI", "NDWI", "EVI", "dNDVI", "NDVI_mean30", "NDVI_std30",
                  "NDVI_z", "DOY"]].fillna(0)
    y = feat_df[label_col].astype(int)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    clf = RandomForestClassifier(
        n_estimators=200, max_depth=12,
        min_samples_leaf=5, random_state=42, n_jobs=-1
    )
    clf.fit(X_train, y_train)

    print(classification_report(y_test, clf.predict(X_test)))
    joblib.dump(clf, MODEL_PATH)
    print(f"Model saved → {MODEL_PATH}")
    return clf


def load_model() -> "RandomForestClassifier | None":
    """Load trained RF model if it exists, else return None."""
    if not SKLEARN_AVAILABLE:
        return None
    if MODEL_PATH.exists():
        return joblib.load(MODEL_PATH)
    return None


def save_index_record(date: str, community_stats: "gpd.GeoDataFrame") -> None:
    """Append a dated snapshot to the history parquet file."""
    record = community_stats[["name", "NDVI", "NDWI", "stress_prob", "status"]].copy()
    record["date"] = pd.to_datetime(date)
    record = record.rename(columns={"name": "community"})

    if HISTORY_PATH.exists():
        existing = pd.read_parquet(HISTORY_PATH)
        # Avoid duplicate dates
        existing = existing[existing["date"] != record["date"].iloc[0]]
        combined = pd.concat([existing, record], ignore_index=True)
    else:
        combined = record
        HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)

    combined.to_parquet(HISTORY_PATH, index=False)


def load_history() -> pd.DataFrame:
    """Load the full index time series. Returns empty DataFrame if none exists."""
    if HISTORY_PATH.exists():
        return pd.read_parquet(HISTORY_PATH).sort_values(["community", "date"])
    return pd.DataFrame(
        columns=["community", "date", "NDVI", "NDWI", "stress_prob", "status"]
    )
