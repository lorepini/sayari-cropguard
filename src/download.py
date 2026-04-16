"""
Sentinel-2 data acquisition via Copernicus Data Space STAC API.
Searches for scenes, downloads COG bands, saves to data/raw/.

No authentication required for search.
Free CDSE account required for download (dataspace.copernicus.eu).
"""
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

# Copernicus Data Space STAC endpoint
CDSE_STAC = "https://catalogue.dataspace.copernicus.eu/stac"
CDSE_ODATA = "https://catalogue.dataspace.copernicus.eu/odata/v1"
CDSE_TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"

# Element84 Earth Search (AWS-hosted Sentinel-2 COGs, no auth needed for search)
E84_STAC = "https://earth-search.aws.element84.com/v1"


def get_cdse_token(user: str, password: str) -> str:
    """Get a short-lived access token from Copernicus Data Space."""
    resp = requests.post(
        CDSE_TOKEN_URL,
        data={
            "client_id": "cdse-public",
            "username": user,
            "password": password,
            "grant_type": "password",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def search_scenes(
    bbox: tuple = config.AOI_BBOX,
    start_date: str | None = None,
    end_date: str | None = None,
    max_cloud: int = config.MAX_CLOUD_COVER,
    max_results: int = 20,
) -> list[dict]:
    """
    Search Sentinel-2 L2A scenes via Element84 STAC (no auth required).

    Returns a list of STAC item dicts ordered by date descending.
    Each item contains 'id', 'datetime', 'cloud_cover', and 'assets' (band URLs).
    """
    if end_date is None:
        end_date = datetime.utcnow().strftime("%Y-%m-%d")
    if start_date is None:
        start_date = (
            datetime.utcnow() - timedelta(days=config.HISTORY_MONTHS * 30)
        ).strftime("%Y-%m-%d")

    params = {
        "collections": "sentinel-2-l2a",
        "bbox": ",".join(str(c) for c in bbox),
        "datetime": f"{start_date}T00:00:00Z/{end_date}T23:59:59Z",
        "query": json.dumps({"eo:cloud_cover": {"lte": max_cloud}}),
        "limit": max_results,
        "sortby": "-datetime",
    }

    url = f"{E84_STAC}/search"
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()

    items = resp.json().get("features", [])
    print(f"[search] Found {len(items)} scenes between {start_date} and {end_date}")
    return items


def download_band(asset_url: str, out_path: Path, token: str | None = None) -> Path:
    """Download a single COG asset to out_path."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        return out_path

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with requests.get(asset_url, headers=headers, stream=True, timeout=120) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        with open(out_path, "wb") as f, tqdm(
            total=total, unit="B", unit_scale=True,
            desc=out_path.name, leave=False
        ) as bar:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
                bar.update(len(chunk))
    return out_path


def download_scene(
    item: dict,
    bands: list[str] | None = None,
    out_dir: Path = config.RAW_DIR,
    token: str | None = None,
) -> dict[str, Path]:
    """
    Download specific bands for one STAC item.
    Returns {band_name: local_path}.
    """
    if bands is None:
        bands = list(config.BANDS.keys())

    scene_id = item["id"]
    date_str = item["properties"]["datetime"][:10]
    scene_dir = out_dir / f"{date_str}_{scene_id}"
    scene_dir.mkdir(parents=True, exist_ok=True)

    assets = item.get("assets", {})
    paths = {}

    for band in bands:
        key = band.lower()
        if key not in assets:
            print(f"  [warn] Band {band} not in scene {scene_id}")
            continue
        url = assets[key]["href"]
        out_path = scene_dir / f"{band}.tif"
        print(f"  Downloading {band} → {out_path.name}")
        download_band(url, out_path, token=token)
        paths[band] = out_path

    # Save scene metadata
    meta_path = scene_dir / "metadata.json"
    with open(meta_path, "w") as f:
        json.dump({
            "id": scene_id,
            "date": date_str,
            "cloud_cover": item["properties"].get("eo:cloud_cover"),
            "bbox": item.get("bbox"),
        }, f, indent=2)

    return paths


def fetch_latest_scenes(
    n: int = 5,
    bands: list[str] | None = None,
) -> list[dict[str, Path]]:
    """
    High-level: search + download the latest n cloud-free scenes.
    Returns list of {band: path} dicts.
    """
    if bands is None:
        bands = ["B04", "B08", "B03", "B11", "SCL"]

    token = None
    if config.CDSE_USER and config.CDSE_PASSWORD:
        try:
            token = get_cdse_token(config.CDSE_USER, config.CDSE_PASSWORD)
        except Exception as e:
            print(f"[warn] Could not get CDSE token: {e}. Trying without auth.")

    items = search_scenes(max_results=n * 2)  # fetch extra in case some fail
    results = []
    for item in items[:n]:
        print(f"\nScene: {item['id']}  |  date: {item['properties']['datetime'][:10]}")
        paths = download_scene(item, bands=bands, token=token)
        if paths:
            results.append(paths)

    return results


if __name__ == "__main__":
    # Quick test: search without downloading
    items = search_scenes(max_results=5)
    for it in items:
        print(
            it["id"],
            it["properties"]["datetime"][:10],
            f"cloud: {it['properties'].get('eo:cloud_cover', '?')}%",
        )
