"""
CropGuard full pipeline — run this to fetch new satellite data,
compute indices, score communities, and update the dashboard data.

Usage:
  python pipeline.py              # fetch latest 1 scene
  python pipeline.py --scenes 3   # fetch latest 3 scenes
  python pipeline.py --demo       # generate demo data (no satellite download)
"""
import argparse
import sys
from datetime import date
from pathlib import Path

import geopandas as gpd

import config
from src.download import fetch_latest_scenes, search_scenes
from src.indices  import compute_indices, apply_cloud_mask, zonal_stats, classify_stress
from src.model    import score_communities, save_index_record
from src.alerts   import generate_all_alerts


def run_demo():
    """Populate history with synthetic data so the dashboard works immediately."""
    from app.callbacks import _demo_history
    import pandas as pd

    print("Generating demo data...")
    history = _demo_history()
    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out = config.PROCESSED_DIR / "index_history.parquet"
    history.to_parquet(out, index=False)
    print(f"Demo history saved → {out}  ({len(history)} rows)")
    print("Run: python app/app.py  to launch the dashboard.")


def run_pipeline(n_scenes: int = 1):
    print(f"\n{'='*60}")
    print(f"  CropGuard Pipeline  |  {date.today()}")
    print(f"{'='*60}\n")

    # 1. Load communities
    print("[1/4] Loading community polygons...")
    communities = gpd.read_file(config.COMMUNITIES_GEOJSON)
    print(f"      {len(communities)} communities loaded")

    # 2. Download scenes
    print(f"\n[2/4] Fetching {n_scenes} Sentinel-2 scene(s)...")
    scene_paths = fetch_latest_scenes(n=n_scenes)
    if not scene_paths:
        print("      No scenes downloaded. Run with --demo to use synthetic data.")
        return

    # 3. Process each scene
    print(f"\n[3/4] Computing indices & scoring...")
    for i, band_paths in enumerate(scene_paths):
        folder_name = list(band_paths.values())[0].parent.name
        raw_date = folder_name.split("_")[2][:8]  # e.g. "20260420"
        scene_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
        print(f"\n  Scene {i+1}/{len(scene_paths)}  |  {scene_date}")

        # Compute indices
        indices = compute_indices(band_paths)

        # Apply cloud mask if SCL available
        if "SCL" in band_paths:
            indices = apply_cloud_mask(indices, band_paths["SCL"])

        # Zonal statistics per community
        import rasterio
        with rasterio.open(band_paths["B04"]) as src:
            meta = src.meta.copy()

        community_stats = zonal_stats(indices, meta, communities)
        community_stats = score_communities(community_stats)
        community_stats = classify_stress(community_stats)

        # Save to history
        save_index_record(scene_date, community_stats)
        print(f"  Saved index record for {scene_date}")

    # 4. Print summary
    print(f"\n[4/4] Summary — {date.today()}")
    from src.model import load_history
    history = load_history()
    if not history.empty:
        latest = history[history["date"] == history["date"].max()]
        alerts = generate_all_alerts(latest)
        print()
        for name, alert_text in alerts.items():
            print(f"  {name}:")
            print(f"    {alert_text}\n")

    print(f"\nDone. Launch dashboard: python app/app.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CropGuard data pipeline")
    parser.add_argument("--scenes", type=int, default=1,
                        help="Number of Sentinel-2 scenes to download")
    parser.add_argument("--demo", action="store_true",
                        help="Generate synthetic demo data (no download)")
    args = parser.parse_args()

    if args.demo:
        run_demo()
    else:
        run_pipeline(n_scenes=args.scenes)
