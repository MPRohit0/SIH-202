"""M1: DEM/landcover loading onto a canonical grid, and void filling
(`docs/handoff_contract.md` §4.1 `dem.tif`, `dem_nearfield.tif`, `landcover.tif`)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from rasterio.fill import fillnodata

from backend.shared.grid import FLOAT_NODATA, UINT8_NODATA, CanonicalGrid, resample_to_grid


@dataclass
class LoadStats:
    """Stats recorded in `provenance.json` for a resampled/filled raster."""

    void_cells_before: int
    void_cells_after: int
    total_cells: int

    @property
    def void_pct_before(self) -> float:
        return 100.0 * self.void_cells_before / self.total_cells

    @property
    def void_pct_after(self) -> float:
        return 100.0 * self.void_cells_after / self.total_cells

    def to_dict(self) -> dict:
        return {
            "void_cells_before": self.void_cells_before,
            "void_cells_after": self.void_cells_after,
            "total_cells": self.total_cells,
            "void_pct_before": round(self.void_pct_before, 4),
            "void_pct_after": round(self.void_pct_after, 4),
        }


def load_dem(raw_path: str | Path, grid: CanonicalGrid) -> np.ndarray:
    """Resample band 1 of the DEM at `raw_path` onto `grid` (bilinear, float32, nodata -9999)."""
    return resample_to_grid(raw_path, grid, method="bilinear")


def load_landcover(raw_path: str | Path, grid: CanonicalGrid) -> np.ndarray:
    """Resample band 1 of the landcover raster at `raw_path` onto `grid` (nearest, uint8,
    nodata 255) — categorical, so bilinear/cubic would invent class codes that don't exist."""
    with rasterio.open(raw_path) as ds:
        arr = resample_to_grid(ds, grid, method="nearest")
    if arr.dtype != np.uint8:
        raise ValueError(f"landcover raster at {raw_path} is not uint8 after resampling (got {arr.dtype})")
    return arr


def fill_voids(dem: np.ndarray, *, max_search_distance: float = 100.0) -> tuple[np.ndarray, LoadStats]:
    """Fill nodata voids in `dem` (float32, nodata -9999) by inverse-distance-weighted
    interpolation from the void's edge (`rasterio.fill.fillnodata`), so DEM voids don't become
    false sinks/pits that stop the flow-routing pass (`hydro.py`). Returns the filled array and
    void-cell stats for `provenance.json`.

    `max_search_distance` (pixels) is rasterio's search window; voids wider than that keep any
    unreached cells as nodata (still flagged in the returned stats — a real gap in the DEM, not
    silently invented terrain, CLAUDE.md rule 3)."""
    mask_valid = dem != FLOAT_NODATA
    void_before = int((~mask_valid).sum())
    # rasterio.fill.fillnodata mutates its `image` argument in place; copy so callers keep `dem` untouched.
    filled = fillnodata(dem.copy(), mask=mask_valid, max_search_distance=max_search_distance)
    void_after = int((filled == FLOAT_NODATA).sum())
    stats = LoadStats(void_cells_before=void_before, void_cells_after=void_after, total_cells=dem.size)
    return filled.astype(np.float32), stats


def landcover_legend() -> dict[int, str]:
    """ESA WorldCover 10 m v200 class legend (`docs/data_sources.md` src_036), for
    `provenance.json` so `landcover.tif`'s codes are self-describing."""
    return {
        10: "Tree cover", 20: "Shrubland", 30: "Grassland", 40: "Cropland", 50: "Built-up",
        60: "Bare / sparse vegetation", 70: "Snow and ice", 80: "Permanent water bodies",
        90: "Herbaceous wetland", 95: "Mangroves", 100: "Moss and lichen",
        UINT8_NODATA: "nodata",
    }
