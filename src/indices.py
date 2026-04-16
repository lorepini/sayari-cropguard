"""
Compute vegetation indices from Sentinel-2 bands and aggregate
them to community polygons (zonal statistics).

Input:  dict of {band_name: Path to GeoTIFF}
Output: GeoDataFrame with per-community index values
"""
import warnings
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.mask import mask as rio_mask
from shapely.geometry import mapping

warnings.filterwarnings("ignore", category=rasterio.errors.NotGeoreferencedWarning)


def _read_band(path: Path, aoi_geom=None) -> tuple[np.ndarray, dict]:
    """Read a single-band GeoTIFF, optionally clipping to AOI."""
    with rasterio.open(path) as src:
        if aoi_geom is not None:
            geom = [mapping(aoi_geom)] if not isinstance(aoi_geom, list) else aoi_geom
            data, transform = rio_mask(src, geom, crop=True, nodata=np.nan)
            meta = src.meta.copy()
            meta.update({"transform": transform,
                         "width": data.shape[2], "height": data.shape[1]})
        else:
            data = src.read().astype(float)
            meta = src.meta.copy()
        data = data.astype(float)
        data[data == src.nodata] = np.nan
    return data[0], meta


def compute_indices(band_paths: dict[str, Path]) -> dict[str, np.ndarray]:
    """
    Compute NDVI, NDWI, EVI from band paths.
    All output arrays share the shape of the B04 band.

    Returns dict of {index_name: 2D array}.
    """
    required = {"B04", "B08"}
    missing = required - set(band_paths.keys())
    if missing:
        raise ValueError(f"Missing required bands: {missing}")

    red,  _ = _read_band(band_paths["B04"])
    nir,  _ = _read_band(band_paths["B08"])

    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi = (nir - red) / (nir + red)
        ndvi = np.clip(ndvi, -1.0, 1.0)

    indices = {"NDVI": ndvi}

    # NDWI (vegetation water content): requires green + nir
    if "B03" in band_paths:
        green, _ = _read_band(band_paths["B03"])
        with np.errstate(divide="ignore", invalid="ignore"):
            ndwi = (green - nir) / (green + nir)
            ndwi = np.clip(ndwi, -1.0, 1.0)
        indices["NDWI"] = ndwi

    # EVI: requires blue + red + nir
    if "B02" in band_paths:
        blue, _ = _read_band(band_paths["B02"])
        with np.errstate(divide="ignore", invalid="ignore"):
            evi = 2.5 * (nir - red) / (nir + 6 * red - 7.5 * blue + 1)
            evi = np.clip(evi, -1.0, 1.0)
        indices["EVI"] = evi

    return indices


def apply_cloud_mask(
    indices: dict[str, np.ndarray],
    scl_path: Path,
) -> dict[str, np.ndarray]:
    """
    Zero-out pixels flagged as cloud/shadow in the SCL band.
    SCL values to mask: 0 (no data), 1 (saturated), 3 (shadow),
                        8 (cloud medium prob), 9 (cloud high prob), 10 (cirrus)
    """
    scl, _ = _read_band(scl_path)
    cloud_mask = np.isin(scl, [0, 1, 3, 8, 9, 10])
    masked = {}
    for name, arr in indices.items():
        a = arr.copy()
        a[cloud_mask] = np.nan
        masked[name] = a
    return masked


def zonal_stats(
    indices: dict[str, np.ndarray],
    band_meta: dict,
    communities: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """
    Compute mean index value per community polygon.
    Returns a copy of communities with new columns for each index.
    """
    import rasterio.transform as rt

    transform = band_meta["transform"]
    crs       = band_meta["crs"]
    communities = communities.to_crs(crs)
    result = communities.copy()

    for idx_name, arr in indices.items():
        means = []
        for _, row in communities.iterrows():
            geom = [mapping(row.geometry)]
            # Create an in-memory raster to mask
            h, w = arr.shape
            from rasterio.io import MemoryFile
            with MemoryFile() as memfile:
                with memfile.open(
                    driver="GTiff", height=h, width=w,
                    count=1, dtype="float32",
                    crs=crs, transform=transform, nodata=np.nan
                ) as dataset:
                    dataset.write(arr.astype("float32"), 1)
                with memfile.open() as dataset:
                    try:
                        masked, _ = rio_mask(dataset, geom, crop=True,
                                             nodata=np.nan, all_touched=True)
                        vals = masked[0]
                        vals = vals[~np.isnan(vals)]
                        means.append(float(np.mean(vals)) if len(vals) > 0 else np.nan)
                    except Exception:
                        means.append(np.nan)

        result[idx_name] = means

    return result.to_crs("EPSG:4326")


def classify_stress(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Add a 'status' column based on NDVI thresholds:
      healthy | watch | alert | no_data
    """
    import config as cfg

    def _status(row):
        if np.isnan(row.get("NDVI", np.nan)):
            return "no_data"
        if row["NDVI"] >= cfg.NDVI_HEALTHY:
            return "healthy"
        if row["NDVI"] >= cfg.NDVI_WATCH:
            return "watch"
        return "alert"

    gdf = gdf.copy()
    gdf["status"] = gdf.apply(_status, axis=1)
    return gdf
