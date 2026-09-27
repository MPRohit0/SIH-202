"""Flags two known artifact classes in a registered direct solver run's headline numbers
(`docs/progress.md` 2026-09-27 "Teesta MVP dashboard stabilization" D-Flow headline investigation):
unconditioned DEM depressions that pond water instead of draining (the M1 far-field DEM was never
hydrologically conditioned), and clear-water Manning flow on steep gorge reaches. Both are real
solver output, not a bug in the run; this only classifies *why* a cell is extreme so the dashboard
can caveat it honestly instead of hiding or re-tuning it.

Reuses `backend.m1_terrain.hydro.route` (the project's own priority-flood implementation) rather
than adding a richdem dependency to the query path. `route()` is O(cells log cells) and takes
tens of seconds on the full far-field DEM, so callers must cache its result
(`ensure_cached_diagnostics`) rather than recomputing it per query.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, replace
from pathlib import Path

import numpy as np
import rasterio
import yaml
from rasterio.warp import Resampling, reproject

from backend.m1_terrain import hydro
from backend.shared.grid import FLOAT_NODATA

DEFAULT_SETTINGS_PATH = Path(__file__).resolve().parents[2] / "config" / "m0_direct_query.yaml"


@dataclass(frozen=True)
class DiagnosticsSettings:
    dem_depression_depth_threshold_m: float = 2.0
    steep_reach_slope_threshold: float = 0.1
    poi_snap_search_radius_m: float = 300.0


def load_settings(path: str | Path | None = None, **overrides) -> DiagnosticsSettings:
    raw = yaml.safe_load(Path(path or DEFAULT_SETTINGS_PATH).read_text(encoding="utf-8")) or {}
    valid = {f.name for f in fields(DiagnosticsSettings)}
    settings = DiagnosticsSettings(**{k: v for k, v in raw.items() if k in valid})
    return replace(settings, **overrides)


def compute_diagnostics(dem: np.ndarray, cell_size_m: float) -> tuple[np.ndarray, np.ndarray]:
    """`(depression_depth, slope)`, both `(H, W)` float32 on `dem`'s own grid. `depression_depth`
    is the priority-flood fill raise at each cell (0 where the DEM already drains). `slope` is the
    magnitude of the central-difference gradient over one cell spacing. Nodata cells are 0 in both
    (never flagged as an artifact)."""
    valid = dem != FLOAT_NODATA
    network = hydro.route(dem.astype(np.float32))
    depression_depth = np.where(valid, network.filled - dem, 0.0).astype(np.float32)
    depression_depth[depression_depth < 0] = 0.0  # filled is never below the source DEM
    safe = np.where(valid, dem, 0.0).astype(np.float64)
    gy, gx = np.gradient(safe, cell_size_m)
    slope = np.where(valid, np.hypot(gx, gy), 0.0).astype(np.float32)
    return depression_depth, slope


def ensure_cached_diagnostics(dem_path: Path, cache_dir: Path) -> tuple[Path, Path]:
    """Depression-depth and slope GeoTIFFs on `dem_path`'s own grid, computed once and reused
    while `dem_path` is unchanged (matched by size and mtime, the same staleness test used for
    other derived caches in this project)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    depression_path = cache_dir / "dem_depression_depth.tif"
    slope_path = cache_dir / "dem_slope.tif"
    stat = dem_path.stat()
    stamp_path = cache_dir / "dem_diagnostics.stamp"
    stamp = f"{stat.st_size}:{stat.st_mtime_ns}"
    if (depression_path.is_file() and slope_path.is_file() and stamp_path.is_file()
            and stamp_path.read_text(encoding="utf-8") == stamp):
        return depression_path, slope_path
    with rasterio.open(dem_path) as ds:
        dem = ds.read(1).astype(np.float32)
        nodata = ds.nodata if ds.nodata is not None else FLOAT_NODATA
        dem = np.where(dem == nodata, FLOAT_NODATA, dem)
        cell_size_m = abs(ds.transform.a)
        profile = ds.profile.copy()
    depression_depth, slope = compute_diagnostics(dem, cell_size_m)
    profile.update(dtype="float32", nodata=FLOAT_NODATA, count=1)
    profile.pop("blockxsize", None)
    profile.pop("blockysize", None)
    with rasterio.open(depression_path, "w", **profile) as ds:
        ds.write(depression_depth, 1)
    with rasterio.open(slope_path, "w", **profile) as ds:
        ds.write(slope, 1)
    stamp_path.write_text(stamp, encoding="utf-8")
    return depression_path, slope_path


def resample_to(source_path: Path, *, like_transform, like_crs, like_shape) -> np.ndarray:
    """Resamples a source GeoTIFF onto another raster's exact grid with `max` resampling, so a
    destination cell is flagged whenever any source cell within it is flagged -- the conservative
    direction for an artifact-detection mask."""
    destination = np.zeros(like_shape, dtype=np.float32)
    with rasterio.open(source_path) as ds:
        reproject(source=rasterio.band(ds, 1), destination=destination, src_transform=ds.transform,
                  src_crs=ds.crs, dst_transform=like_transform, dst_crs=like_crs,
                  resampling=Resampling.max)
    return destination
