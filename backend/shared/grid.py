"""Canonical site grids (docs/handoff_contract.md §1.4) and helpers to align data to them.

A site has two grids in its UTM CRS, derived from the site config:

- farfield:  the far-field lon/lat bbox is projected to UTM (edges densified) and
  snapped OUTWARD to whole multiples of the far-field cell size, so the grid
  covers the whole bbox with less than one extra cell per side.
- nearfield: the near-field bbox, projected the same way and snapped outward to
  far-field cell corners; its cell size divides the far-field cell size exactly,
  so near-field cells nest inside far-field cells.

Every raster in the project must have the CRS, transform and shape of one of
these grids. `resample_to_grid` puts any raster onto a grid and
`write_grid_raster` writes it in the contract's GeoTIFF format (§1.6).
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Literal

import numpy as np
import rasterio
from affine import Affine
from pydantic import BaseModel, ConfigDict, Field
from pyproj import Transformer
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.warp import reproject

from .site_config import SiteConfig, SourcedValue

CONTRACT_VERSION = "0.1.0"
FLOAT_NODATA = -9999.0
UINT8_NODATA = 255
DENSIFY_PTS = 21  # points added along each bbox edge when projecting, so curved edges are covered

RESAMPLING_METHODS = {
    name: getattr(Resampling, name)
    for name in ("nearest", "bilinear", "cubic", "average", "mode", "min", "max", "sum")
    if hasattr(Resampling, name)
}
_CATEGORICAL_METHODS = {"nearest", "mode"}


class CanonicalGrid(BaseModel):
    """A site grid exactly as stored in `grid.json` / `grid_nearfield.json` (contract §1.4)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: str = CONTRACT_VERSION
    site_id: str
    grid_id: Literal["farfield", "nearfield"]
    crs_epsg: int
    origin_x: float  # upper-left corner, m
    origin_y: float
    cell_size_m: float = Field(gt=0)
    width: int = Field(gt=0)  # columns
    height: int = Field(gt=0)  # rows
    nodata: float = FLOAT_NODATA
    pixel_is: Literal["area"] = "area"

    @property
    def transform(self) -> Affine:
        return Affine(self.cell_size_m, 0.0, self.origin_x, 0.0, -self.cell_size_m, self.origin_y)

    @property
    def crs(self) -> CRS:
        return CRS.from_epsg(self.crs_epsg)

    @property
    def shape(self) -> tuple[int, int]:
        """(rows, cols) — numpy / rasterio order."""
        return (self.height, self.width)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """(left, bottom, right, top) in UTM metres."""
        return (self.origin_x,
                self.origin_y - self.height * self.cell_size_m,
                self.origin_x + self.width * self.cell_size_m,
                self.origin_y)

    @property
    def bounds_latlng(self) -> list[list[float]]:
        """Leaflet bounds [[south_lat, west_lon], [north_lat, east_lon]] enclosing the grid."""
        west, south, east, north = _transformer(self.crs_epsg, 4326).transform_bounds(
            *self.bounds, densify_pts=DENSIFY_PTS)
        return [[south, west], [north, east]]

    def to_json(self, path: str | Path) -> Path:
        path = Path(path)
        path.write_text(json.dumps(self.model_dump(), indent=2) + "\n", encoding="utf-8")
        return path

    @classmethod
    def from_json(cls, path: str | Path) -> CanonicalGrid:
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))


@lru_cache(maxsize=32)
def _transformer(src_epsg: int, dst_epsg: int) -> Transformer:
    return Transformer.from_crs(src_epsg, dst_epsg, always_xy=True)


def _require(sv: SourcedValue, name: str):
    if sv.value is None:
        raise ValueError(f"{name} is null (status: {sv.status}); cannot build the grid until it is filled in")
    return sv.value


def _projected_bbox(bbox: list[float], epsg: int) -> tuple[float, float, float, float]:
    return _transformer(4326, epsg).transform_bounds(*bbox, densify_pts=DENSIFY_PTS)


# =============================================================================
# Grid construction
# =============================================================================


def build_farfield_grid(cfg: SiteConfig) -> CanonicalGrid:
    """Far-field grid: projected bbox snapped outward to multiples of the cell size."""
    ff = cfg.domains.far_field
    epsg = _require(cfg.crs.utm_epsg, "crs.utm_epsg")
    bbox = _require(ff.bbox, "domains.far_field.bbox")
    cs = float(_require(ff.grid_resolution, "domains.far_field.grid_resolution"))

    minx, miny, maxx, maxy = _projected_bbox(bbox, epsg)
    origin_x = math.floor(minx / cs) * cs
    origin_y = math.ceil(maxy / cs) * cs
    return CanonicalGrid(
        site_id=cfg.site.id, grid_id="farfield", crs_epsg=epsg,
        origin_x=origin_x, origin_y=origin_y, cell_size_m=cs,
        width=math.ceil((maxx - origin_x) / cs),
        height=math.ceil((origin_y - miny) / cs),
    )


def build_nearfield_grid(cfg: SiteConfig, farfield: CanonicalGrid) -> CanonicalGrid:
    """Near-field grid: projected bbox snapped outward to far-field cell corners."""
    nf = cfg.domains.near_field
    bbox = _require(nf.bbox, "domains.near_field.bbox")
    cs = float(_require(nf.grid_resolution, "domains.near_field.grid_resolution"))
    fcs = farfield.cell_size_m
    ratio = fcs / cs
    if cs > fcs or not math.isclose(ratio, round(ratio), abs_tol=1e-9):
        raise ValueError(f"near-field cell size ({cs} m) must divide the far-field cell size ({fcs} m) exactly")

    minx, miny, maxx, maxy = _projected_bbox(bbox, farfield.crs_epsg)
    fx0, fy0 = farfield.origin_x, farfield.origin_y
    left = fx0 + math.floor((minx - fx0) / fcs) * fcs
    right = fx0 + math.ceil((maxx - fx0) / fcs) * fcs
    top = fy0 - math.floor((fy0 - maxy) / fcs) * fcs
    bottom = fy0 - math.ceil((fy0 - miny) / fcs) * fcs

    fl, fb, fr, ft = farfield.bounds
    if left < fl or bottom < fb or right > fr or top > ft:
        raise ValueError("near-field grid extends outside the far-field grid")

    return CanonicalGrid(
        site_id=cfg.site.id, grid_id="nearfield", crs_epsg=farfield.crs_epsg,
        origin_x=left, origin_y=top, cell_size_m=cs,
        width=round((right - left) / cs),
        height=round((top - bottom) / cs),
    )


def build_site_grids(cfg: SiteConfig) -> dict[str, CanonicalGrid]:
    far = build_farfield_grid(cfg)
    return {"farfield": far, "nearfield": build_nearfield_grid(cfg, far)}


# =============================================================================
# Coordinates <-> grid indices
# =============================================================================


def lonlat_to_rowcol(grid: CanonicalGrid, lon, lat, strict: bool = True):
    """Grid (row, col) of the cell containing each lon/lat (EPSG:4326) point.

    Scalars in -> Python ints out; arrays in -> int arrays out. Points outside the
    grid raise ValueError when `strict`, otherwise get row = col = -1.
    """
    scalar = np.ndim(lon) == 0 and np.ndim(lat) == 0
    x, y = _transformer(4326, grid.crs_epsg).transform(np.asarray(lon, dtype=float), np.asarray(lat, dtype=float))
    col = np.atleast_1d(np.floor((np.asarray(x) - grid.origin_x) / grid.cell_size_m).astype(np.int64))
    row = np.atleast_1d(np.floor((grid.origin_y - np.asarray(y)) / grid.cell_size_m).astype(np.int64))

    inside = (row >= 0) & (row < grid.height) & (col >= 0) & (col < grid.width)
    if not inside.all():
        if strict:
            raise ValueError(f"{int((~inside).sum())} point(s) outside the {grid.grid_id} grid of site '{grid.site_id}'")
        row[~inside] = -1
        col[~inside] = -1

    if scalar:
        return int(row[0]), int(col[0])
    return row.reshape(np.shape(lon)), col.reshape(np.shape(lon))


def rowcol_to_lonlat(grid: CanonicalGrid, row, col):
    """lon/lat (EPSG:4326) of the centre of each (row, col) cell."""
    scalar = np.ndim(row) == 0 and np.ndim(col) == 0
    x = grid.origin_x + (np.asarray(col, dtype=float) + 0.5) * grid.cell_size_m
    y = grid.origin_y - (np.asarray(row, dtype=float) + 0.5) * grid.cell_size_m
    lon, lat = _transformer(grid.crs_epsg, 4326).transform(x, y)
    if scalar:
        return float(lon), float(lat)
    return np.asarray(lon), np.asarray(lat)


# =============================================================================
# Rasters
# =============================================================================


def resample_to_grid(src, grid: CanonicalGrid, method: str | None = None, src_nodata: float | None = None) -> np.ndarray:
    """Resample band 1 of a raster (path or open rasterio dataset) onto `grid`.

    Default method (contract §1.4): nearest for integer rasters, bilinear for floats.
    Output: uint8 with nodata 255 for a uint8 source resampled by nearest/mode
    (categories); otherwise float32 with nodata -9999.0. Cells the source does
    not cover are nodata. `src_nodata` overrides the source file's nodata.
    """
    if isinstance(src, (str, Path)):
        with rasterio.open(src) as ds:
            return resample_to_grid(ds, grid, method=method, src_nodata=src_nodata)

    src_dtype = np.dtype(src.dtypes[0])
    if method is None:
        method = "nearest" if np.issubdtype(src_dtype, np.integer) else "bilinear"
    if method not in RESAMPLING_METHODS:
        raise ValueError(f"unknown resampling method '{method}'; choose from {sorted(RESAMPLING_METHODS)}")

    if src_dtype == np.uint8 and method in _CATEGORICAL_METHODS:
        dtype, nodata = np.uint8, UINT8_NODATA
    else:
        dtype, nodata = np.float32, grid.nodata

    dst = np.full(grid.shape, nodata, dtype=dtype)
    reproject(
        source=rasterio.band(src, 1),
        destination=dst,
        src_transform=src.transform,
        src_crs=src.crs,
        src_nodata=src.nodata if src_nodata is None else src_nodata,
        dst_transform=grid.transform,
        dst_crs=grid.crs,
        dst_nodata=nodata,
        resampling=RESAMPLING_METHODS[method],
    )
    return dst


def write_grid_raster(path: str | Path, array: np.ndarray, grid: CanonicalGrid) -> Path:
    """Write a single-band array on `grid` as a tiled, LZW-compressed GeoTIFF.

    uint8 arrays are written as categories (nodata 255); anything else as float32
    (nodata -9999.0).
    """
    if array.shape != grid.shape:
        raise ValueError(f"array shape {array.shape} does not match {grid.grid_id} grid shape {grid.shape}")
    if array.dtype == np.uint8:
        nodata = UINT8_NODATA
    else:
        array, nodata = array.astype(np.float32), grid.nodata

    path = Path(path)
    with rasterio.open(
        path, "w", driver="GTiff", width=grid.width, height=grid.height, count=1,
        dtype=array.dtype, crs=grid.crs, transform=grid.transform, nodata=nodata,
        tiled=True, blockxsize=256, blockysize=256, compress="lzw",
    ) as dst:
        dst.write(array, 1)
    return path
