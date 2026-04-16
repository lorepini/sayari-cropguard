"""
Sentinel-2 L2A data acquisition via Copernicus Data Space Ecosystem (CDSE).

Two modes:
  LIVE  — searches CDSE OData API, downloads product, extracts bands
  MANUAL — you place a .SAFE folder in data/raw/ yourself (from browser.dataspace.copernicus.eu)

Registration (free): https://dataspace.copernicus.eu
"""
import json
import os
import sys
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

# ── CDSE endpoints ─────────────────────────────────────────────────────────────
CDSE_ODATA   = "https://catalogue.dataspace.copernicus.eu/odata/v1"
CDSE_TOKEN   = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
CDSE_DOWNLOAD= "https://download.dataspace.copernicus.eu/odata/v1"

# Sentinel-2 MGRS tile that covers Lambayeque / Chiclayo area
# Verify at: https://maps.esa.int/s2-grid/
LAMBAYEQUE_TILES = ["17MPM", "17MPN", "17MPL"]


# ── Authentication ─────────────────────────────────────────────────────────────

def get_access_token(user: str = "", password: str = "") -> Optional[str]:
    """
    Obtain a short-lived CDSE access token.
    Returns None if credentials are not set.
    """
    user     = user     or config.CDSE_USER
    password = password or config.CDSE_PASSWORD

    if not user or not password:
        return None

    resp = requests.post(
        CDSE_TOKEN,
        data={
            "client_id":  "cdse-public",
            "username":   user,
            "password":   password,
            "grant_type": "password",
        },
        timeout=30,
    )
    if not resp.ok:
        print(f"[auth] Login failed ({resp.status_code}): {resp.text[:200]}")
        return None

    print("[auth] CDSE token obtained ✓")
    return resp.json()["access_token"]


# ── Search ─────────────────────────────────────────────────────────────────────

def search_scenes(
    bbox: tuple = config.AOI_BBOX,
    start_date: Optional[str] = None,
    end_date:   Optional[str] = None,
    max_cloud:  int  = config.MAX_CLOUD_COVER,
    max_results: int = 10,
) -> list[dict]:
    """
    Search Sentinel-2 L2A scenes over our AOI using CDSE OData API.
    No authentication required for search.

    Returns list of product dicts sorted by date descending.
    """
    if end_date is None:
        end_date = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
    if start_date is None:
        start_date = (
            datetime.utcnow() - timedelta(days=config.HISTORY_MONTHS * 30)
        ).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    lon_min, lat_min, lon_max, lat_max = bbox
    polygon = (
        f"POLYGON(({lon_min} {lat_min},{lon_max} {lat_min},"
        f"{lon_max} {lat_max},{lon_min} {lat_max},{lon_min} {lat_min}))"
    )

    filter_str = (
        "Collection/Name eq 'SENTINEL-2' and "
        "Attributes/OData.CSC.StringAttribute/any(att:"
        "att/Name eq 'productType' and "
        "att/OData.CSC.StringAttribute/Value eq 'S2MSI2A') and "
        f"OData.CSC.Intersects(area=geography'SRID=4326;{polygon}') and "
        f"ContentDate/Start gt {start_date} and "
        f"ContentDate/Start lt {end_date}"
    )

    params = {
        "$filter":  filter_str,
        "$orderby": "ContentDate/Start desc",
        "$top":     max_results * 3,   # overfetch; we filter by cloud below
        "$expand":  "Attributes",
    }

    resp = requests.get(f"{CDSE_ODATA}/Products", params=params, timeout=30)
    resp.raise_for_status()

    products = resp.json().get("value", [])

    # Filter by cloud cover (attribute may be missing for some products)
    filtered = []
    for p in products:
        cloud = next(
            (float(a["Value"]) for a in p.get("Attributes", [])
             if a["Name"] == "cloudCover"),
            None,
        )
        p["_cloud"] = cloud
        if cloud is None or cloud <= max_cloud:
            filtered.append(p)
        if len(filtered) >= max_results:
            break

    print(f"[search] {len(filtered)} scenes ≤{max_cloud}% cloud  "
          f"({start_date[:10]} → {end_date[:10]})")

    for p in filtered:
        print(f"  {p['Name'][:55]}  "
              f"date={p['ContentDate']['Start'][:10]}  "
              f"cloud={p['_cloud']:.1f}%" if p['_cloud'] is not None
              else f"  {p['Name'][:55]}  date={p['ContentDate']['Start'][:10]}")

    return filtered


# ── Download ───────────────────────────────────────────────────────────────────

def download_product(
    product: dict,
    out_dir: Path = config.RAW_DIR,
    token: Optional[str] = None,
) -> Optional[Path]:
    """
    Download a full Sentinel-2 product as a .zip and extract to out_dir.
    Requires a valid CDSE access token.

    Returns the path to the extracted .SAFE directory, or None on failure.
    """
    if token is None:
        token = get_access_token()
    if token is None:
        print("[download] No CDSE credentials — see instructions below.")
        print_setup_instructions()
        return None

    product_id   = product["Id"]
    product_name = product["Name"]
    zip_path     = out_dir / f"{product_name}.zip"
    safe_path    = out_dir / f"{product_name}.SAFE"

    if safe_path.exists():
        print(f"[download] Already downloaded: {safe_path.name}")
        return safe_path

    out_dir.mkdir(parents=True, exist_ok=True)
    url = f"{CDSE_DOWNLOAD}/Products({product_id})/$value"
    headers = {"Authorization": f"Bearer {token}"}

    print(f"[download] {product_name}")
    with requests.get(url, headers=headers, stream=True, timeout=300) as resp:
        if resp.status_code == 401:
            print("[download] Token expired — refreshing...")
            token = get_access_token()
            if token is None:
                return None
            headers = {"Authorization": f"Bearer {token}"}
            resp = requests.get(url, headers=headers, stream=True, timeout=300)

        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))

        with open(zip_path, "wb") as f, tqdm(
            total=total, unit="B", unit_scale=True,
            desc=f"  {product_name[:40]}"
        ) as bar:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)
                bar.update(len(chunk))

    print(f"[download] Extracting...")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(out_dir)
    zip_path.unlink()
    print(f"[download] Done → {safe_path}")
    return safe_path


# ── Band extraction from .SAFE ─────────────────────────────────────────────────

def extract_bands(
    safe_dir: Path,
    bands: list[str] = None,
    out_dir: Path = None,
) -> dict[str, Path]:
    """
    Extract specific band GeoTIFFs from a .SAFE directory structure.
    Returns {band_name: path_to_geotiff}.

    Sentinel-2 L2A .SAFE structure:
      GRANULE/<tile>/IMG_DATA/R10m/  — 10m bands (B02, B03, B04, B08, TCI)
      GRANULE/<tile>/IMG_DATA/R20m/  — 20m bands (B8A, B11, B12, SCL)
    """
    if bands is None:
        bands = ["B04", "B08", "B03", "B11", "B8A", "SCL"]

    # Find the GRANULE subdirectory
    granule_dirs = list((safe_dir / "GRANULE").iterdir())
    if not granule_dirs:
        raise FileNotFoundError(f"No GRANULE found in {safe_dir}")
    granule = granule_dirs[0]

    img_data = granule / "IMG_DATA"
    band_paths = {}

    resolution_map = {
        "B02": "R10m", "B03": "R10m", "B04": "R10m", "B08": "R10m",
        "B8A": "R20m", "B11": "R20m", "B12": "R20m", "SCL": "R20m",
    }

    if out_dir is None:
        out_dir = config.PROCESSED_DIR / safe_dir.stem

    out_dir.mkdir(parents=True, exist_ok=True)

    for band in bands:
        res = resolution_map.get(band, "R10m")
        res_dir = img_data / res

        # Find the file matching the band name
        candidates = list(res_dir.glob(f"*_{band}_*.jp2")) + \
                     list(res_dir.glob(f"*_{band}.jp2"))

        if not candidates:
            print(f"  [warn] Band {band} not found in {res_dir}")
            continue

        src_path = candidates[0]
        dst_path = out_dir / f"{band}.tif"

        # Convert JP2 → GeoTIFF using rasterio (preserves CRS, transform)
        if not dst_path.exists():
            import rasterio
            from rasterio.enums import Resampling
            with rasterio.open(src_path) as src:
                profile = src.profile.copy()
                profile.update(driver="GTiff", compress="lzw")
                with rasterio.open(dst_path, "w", **profile) as dst:
                    dst.write(src.read())
            print(f"  {band} → {dst_path.name}")
        else:
            print(f"  {band} already extracted")

        band_paths[band] = dst_path

    return band_paths


# ── Manual mode ────────────────────────────────────────────────────────────────

def find_local_scenes(raw_dir: Path = config.RAW_DIR) -> list[Path]:
    """
    Return list of .SAFE directories already downloaded manually.
    Useful when you downloaded via browser.dataspace.copernicus.eu.
    """
    safe_dirs = list(raw_dir.glob("*.SAFE"))
    if safe_dirs:
        print(f"[local] Found {len(safe_dirs)} .SAFE directories:")
        for d in safe_dirs:
            print(f"  {d.name}")
    else:
        print("[local] No .SAFE directories in data/raw/")
        print("  Download manually from: https://browser.dataspace.copernicus.eu")
    return safe_dirs


# ── High-level entry point ─────────────────────────────────────────────────────

def fetch_latest_scenes(
    n: int = 1,
    bands: list[str] = None,
    manual_fallback: bool = True,
) -> list[dict[str, Path]]:
    """
    Search → download → extract bands for the latest n cloud-free scenes.
    Falls back to locally available .SAFE directories if download fails.

    Returns list of {band_name: path} dicts, one per scene.
    """
    if bands is None:
        bands = ["B04", "B08", "B03", "B11", "SCL"]

    results = []

    # First check for locally available scenes
    local = find_local_scenes()
    if local:
        print(f"\n[pipeline] Using {len(local)} local scene(s)")
        for safe_dir in local[:n]:
            try:
                paths = extract_bands(safe_dir, bands=bands)
                if paths:
                    results.append(paths)
            except Exception as e:
                print(f"  [error] {safe_dir.name}: {e}")
        if results:
            return results

    # Otherwise try live download
    print("\n[pipeline] Searching for scenes to download...")
    products = search_scenes(max_results=n * 2)

    if not products:
        print("[pipeline] No scenes found for AOI/date range.")
        return []

    token = get_access_token()

    for product in products[:n]:
        safe_dir = download_product(product, token=token)
        if safe_dir is None:
            break
        try:
            paths = extract_bands(safe_dir, bands=bands)
            if paths:
                results.append(paths)
        except Exception as e:
            print(f"  [error] extract_bands: {e}")

    return results


# ── Instructions ───────────────────────────────────────────────────────────────

def print_setup_instructions():
    print("""
╔══════════════════════════════════════════════════════════════════╗
║         HOW TO CONNECT TO SENTINEL-2 SATELLITE DATA             ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  OPTION 1 — Automated download (recommended)                    ║
║  ─────────────────────────────────────────────                   ║
║  1. Register FREE at: https://dataspace.copernicus.eu           ║
║     (takes 2 minutes, just email + password)                    ║
║                                                                  ║
║  2. Add credentials to your .env file:                          ║
║     CDSE_USER=your_email@example.com                            ║
║     CDSE_PASSWORD=your_password                                 ║
║                                                                  ║
║  3. Run:  python3 pipeline.py --scenes 1                        ║
║                                                                  ║
║  OPTION 2 — Manual download (no code needed)                    ║
║  ────────────────────────────────────────────                    ║
║  1. Go to: https://browser.dataspace.copernicus.eu              ║
║  2. Draw a rectangle over Lambayeque, Peru                      ║
║  3. Filter: Sentinel-2 L2A, cloud < 20%, any recent date       ║
║  4. Download as .zip, extract into data/raw/                    ║
║     (the folder should be named *.SAFE)                         ║
║  5. Run:  python3 pipeline.py                                   ║
║                                                                  ║
║  OPTION 3 — Demo mode (works right now, no account needed)      ║
║  ──────────────────────────────────────────────────────          ║
║     python3 pipeline.py --demo                                  ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
""")


if __name__ == "__main__":
    # Quick test — search works without any credentials
    print("Testing CDSE search (no credentials needed)...\n")
    products = search_scenes(max_results=5)
    if products:
        print(f"\nBest scene to use: {products[0]['Name']}")
        print(f"  → cloud cover: {products[0]['_cloud']:.1f}%")
        print(f"  → date:        {products[0]['ContentDate']['Start'][:10]}")
        print("\nTo download, add CDSE credentials to .env and run pipeline.py")
    else:
        print("No scenes found (check internet connection)")
