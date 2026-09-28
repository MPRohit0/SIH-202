"""Pure numpy/shapely logic for the monthly lake-area classification (contract §4.8
`lake_area.csv` / `lake_latest.geojson`). No Earth Engine calls live here -- `provider.py` fetches
the raster arrays, this module turns them into a water mask, an area and a polygon, so the whole
chain is testable on synthetic arrays (CLAUDE.md rule 2).

Method choice (`docs/decisions.md` "M7 GEE fetch"): Otsu's threshold (Otsu 1979) computed fresh on
each month's composite, clamped to a physically sensible range (`settings.GeeSettings`). This
avoids picking one fixed NDWI/backscatter cutoff that would have to be justified for every site and
season; the threshold actually used is recorded per month in `gee_meta.json`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pyproj
import shapely
from affine import Affine
from rasterio.features import shapes as raster_shapes
from scipy import ndimage
from shapely.geometry import shape as shapely_shape
from shapely.ops import transform as shapely_transform, unary_union

from .settings import GeeSettings


@dataclass(frozen=True)
class AoiGrid:
    """A small local UTM grid around one lake seed point -- the AOI classification is done on,
    distinct from the site's canonical modelling grid (`backend/shared/grid.py`): this one is
    sized to the lake, not the flood domain, and does not need a trained emulator/terrain run to
    exist first."""

    epsg: int
    origin_x: float  # upper-left corner, m (UTM)
    origin_y: float
    cell_size_m: float
    width: int
    height: int

    @property
    def transform(self) -> Affine:
        return Affine(self.cell_size_m, 0.0, self.origin_x, 0.0, -self.cell_size_m, self.origin_y)

    @property
    def shape(self) -> tuple[int, int]:
        return (self.height, self.width)


def build_aoi_grid(seed_x: float, seed_y: float, epsg: int, settings: GeeSettings) -> AoiGrid:
    """A square grid of `settings.pixel_size_m` cells centred on (seed_x, seed_y) in UTM metres,
    `settings.lake_buffer_m` out to each side."""
    cs = settings.pixel_size_m
    half = settings.lake_buffer_m
    n = int(np.ceil(2 * half / cs))
    origin_x = seed_x - (n * cs) / 2
    origin_y = seed_y + (n * cs) / 2
    return AoiGrid(epsg=epsg, origin_x=origin_x, origin_y=origin_y, cell_size_m=cs, width=n, height=n)


def seed_rowcol(grid: AoiGrid, seed_x: float, seed_y: float) -> tuple[int, int]:
    col = int((seed_x - grid.origin_x) / grid.cell_size_m)
    row = int((grid.origin_y - seed_y) / grid.cell_size_m)
    return row, col


def otsu_threshold(values: np.ndarray, clamp: tuple[float, float], bins: int = 256) -> float:
    """Otsu's method: the threshold maximising between-class variance, clamped to `clamp`.

    Falls back to the midpoint of `clamp` if there are too few finite values to form a histogram
    (e.g. a fully masked/cloudy composite).
    """
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size < 2 or np.ptp(finite) == 0:
        return float(np.mean(clamp))

    hist, edges = np.histogram(finite, bins=bins)
    hist = hist.astype(float)
    centers = (edges[:-1] + edges[1:]) / 2.0

    w1 = np.cumsum(hist)
    w2 = np.cumsum(hist[::-1])[::-1]
    # weighted running means, guarding the div-by-zero at the empty ends of the histogram
    m1 = np.cumsum(hist * centers) / np.where(w1 == 0, 1.0, w1)
    m2 = (np.cumsum((hist * centers)[::-1])[::-1]) / np.where(w2 == 0, 1.0, w2)

    between = w1[:-1] * w2[1:] * (m1[:-1] - m2[1:]) ** 2
    if not between.size:
        return float(np.mean(clamp))
    # ties happen whenever the two classes are separated by empty bins (any threshold in the gap
    # gives the same between-class variance); the middle of the tied run sits in the gap, not at
    # its edge, so it is the more representative pick.
    tied = np.flatnonzero(between == between.max())
    idx = int(tied[len(tied) // 2])
    threshold = float(centers[idx])
    return float(np.clip(threshold, clamp[0], clamp[1]))


def slope_deg_from_elevation(dem: np.ndarray, cell_size_m: float) -> np.ndarray:
    """Terrain slope in degrees from an elevation array on a uniform square grid, via a
    central-difference gradient (`numpy.gradient`) -- no DEM-conditioning or flow-routing needed,
    just the rise-over-run angle at each cell. NaN propagates from NaN elevation cells."""
    dz_dy, dz_dx = np.gradient(dem, cell_size_m)
    return np.degrees(np.arctan(np.hypot(dz_dx, dz_dy)))


def dem_slope_deg(dem_path, grid: AoiGrid):
    """`slope_deg_from_elevation` computed from a DEM file, reprojected/resampled (bilinear) onto
    `grid`. NaN where the DEM has no coverage of `grid`."""
    import rasterio
    from rasterio.warp import Resampling, reproject

    with rasterio.open(dem_path) as src:
        dem = np.full(grid.shape, np.nan, dtype=np.float32)
        reproject(
            source=rasterio.band(src, 1), destination=dem,
            src_transform=src.transform, src_crs=src.crs, src_nodata=src.nodata,
            dst_transform=grid.transform, dst_crs=f"EPSG:{grid.epsg}",
            dst_nodata=np.nan, resampling=Resampling.bilinear,
        )
    return slope_deg_from_elevation(dem, grid.cell_size_m)


def water_mask(
    index: np.ndarray, threshold: float, below: bool = False,
    nir: np.ndarray | None = None, nir_max: float | None = None,
    slope_deg: np.ndarray | None = None, max_slope_deg: float | None = None,
) -> np.ndarray:
    """Boolean water mask: `index >= threshold` (e.g. NDWI, water is high), or `index <= threshold`
    when `below` (e.g. SAR VV backscatter in dB, water is low/smooth).

    `nir`/`nir_max`: an optional extra requirement that NIR (B8) surface reflectance be at or below
    `nir_max`. Snow and ice are bright in the NIR even when their NDWI happens to clear the Otsu
    threshold; without this, a snow patch next to the lake can pass the NDWI mask and bridge into
    the seeded connected component, inflating the reported area (`docs/decisions.md` 2026-09-28).
    Only meaningful for the NDWI mask -- pass `nir=None` for a SAR mask, which has no NIR band.

    `slope_deg`/`max_slope_deg`: an optional extra requirement that terrain slope be at or below
    `max_slope_deg`. A lake surface is flat; SAR radar shadow on a steep Himalayan slope reads as
    smooth/low-backscatter (indistinguishable from open water in the `below=True` mask) but sits on
    ground far from level, so a slope ceiling excludes it while keeping the true, flat lake surface
    (`docs/decisions.md` 2026-09-28 "mask slopes steeper than ~6 degrees"). Meaningful for either
    method -- pass `slope_deg=None` where no DEM coverage is available.
    """
    finite = np.isfinite(index)
    mask = (index <= threshold) if below else (index >= threshold)
    mask = finite & mask
    if nir is not None and nir_max is not None:
        mask &= np.isfinite(nir) & (nir <= nir_max)
    if slope_deg is not None and max_slope_deg is not None:
        mask &= np.isfinite(slope_deg) & (slope_deg <= max_slope_deg)
    return mask


def seed_component(mask: np.ndarray, seed_rc: tuple[int, int]) -> np.ndarray:
    """The connected component of `mask` that contains (or is nearest to) `seed_rc`.

    Keeps the lake and drops everything else the threshold also picked up (SAR radar shadow,
    unrelated water bodies at the edge of the AOI buffer) -- both are common false positives for a
    global threshold and are not the lake we seeded on.
    """
    labels, n = ndimage.label(mask, structure=np.ones((3, 3), dtype=bool))
    if n == 0:
        return np.zeros_like(mask, dtype=bool)

    row, col = seed_rc
    in_bounds = 0 <= row < mask.shape[0] and 0 <= col < mask.shape[1]
    seed_label = labels[row, col] if in_bounds else 0

    if seed_label == 0:
        # seed isn't on a water pixel (or is off-grid): snap to the component whose nearest pixel
        # is closest to the seed, using the exact distance to each labelled pixel.
        rows, cols = np.nonzero(labels)
        if rows.size == 0:
            return np.zeros_like(mask, dtype=bool)
        dist2 = (rows - row) ** 2 + (cols - col) ** 2
        seed_label = labels[rows[int(np.argmin(dist2))], cols[int(np.argmin(dist2))]]

    return labels == seed_label


def component_area_m2(component: np.ndarray, grid: AoiGrid) -> float:
    return float(component.sum()) * grid.cell_size_m ** 2


def polygonize_lonlat(component: np.ndarray, grid: AoiGrid) -> dict:
    """The component as a single EPSG:4326 GeoJSON geometry (dict). An empty component gives an
    empty MultiPolygon's `__geo_interface__`."""
    if not component.any():
        return shapely.MultiPolygon().__geo_interface__

    geoms = [shapely_shape(geom) for geom, value in
             raster_shapes(component.astype(np.uint8), mask=component, transform=grid.transform)
             if value == 1]
    utm_geom = unary_union(geoms)

    project = pyproj.Transformer.from_crs(grid.epsg, 4326, always_xy=True).transform
    lonlat_geom = shapely_transform(project, utm_geom)
    return lonlat_geom.__geo_interface__


def choose_method(
    s2_cloud_pct: float | None,
    s2_snow_ice_pct: float | None,
    s1_available: bool,
    s1_valid_pct: float | None,
    settings: GeeSettings,
) -> tuple[str, str | None]:
    """Which product a month's `lake_area.csv` row should come from.

    Returns (method, skip_reason) where method is `"s2_water_index"`, `"s1_threshold"` or
    `"skip"` (skip_reason is `None` unless method is `"skip"`). Ice checked first because it
    degrades both products the same way (`docs/decisions.md` "M7 GEE fetch").
    """
    if s2_snow_ice_pct is not None and s2_snow_ice_pct > settings.max_snow_ice_pct:
        return "skip", "snow_ice"
    if s2_cloud_pct is not None and s2_cloud_pct <= settings.max_cloud_pct:
        return "s2_water_index", None
    if s1_available and (s1_valid_pct is None or s1_valid_pct >= settings.min_valid_pct):
        return "s1_threshold", None
    return "skip", "no_usable_scene"
