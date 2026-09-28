"""Where the raster/vector data for the M7 fetch pipeline (`fetch.py`) comes from.

`Provider` is a `typing.Protocol` so `fetch.py` never imports `ee` directly and the whole pipeline
runs end to end on synthetic data (CLAUDE.md rule 2, `tests/m7_gee/test_fetch.py`).
`EarthEngineProvider` is the real implementation; its raster methods use
`ee.data.computePixels` (NUMPY_NDARRAY) on a small local AOI grid (`lake_area.AoiGrid`) chosen by
the caller, not GEE's native pixel grid, so results align exactly with `lake_area.py`'s
classification logic and stay small enough for one `computePixels` call (the docstring on each
method gives the REST param shapes this relies on: `PixelGrid` --
https://developers.google.com/earth-engine/reference/rest/v1/PixelGrid). `EarthEngineProvider`
needs a live Earth Engine session and is exercised end to end only by the manual smoke test in
`docs/decisions.md` "M7 GEE fetch" / the plan's verification steps -- the unit tests only check
the request it builds, against `tests/m7_gee/fake_ee.py`.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Protocol

import numpy as np

from .lake_area import AoiGrid

logger = logging.getLogger(__name__)

S2_COLLECTION = "COPERNICUS/S2_SR_HARMONIZED"
S1_COLLECTION = "COPERNICUS/S1_GRD"
CHIRPS_COLLECTION = "UCSB-CHG/CHIRPS/DAILY"
GPM_COLLECTION = "NASA/GPM_L3/IMERG_V07"
HYDROBASINS_COLLECTION_TEMPLATE = "WWF/HydroSHEDS/v1/Basins/hybas_{level}"

# SCL (Scene Classification Layer) codes, same as scene_search.py.
S2_SCL_CLOUD_CLASSES = [3, 8, 9, 10]  # cloud shadow, cloud medium/high prob, thin cirrus
S2_SCL_SNOW_ICE_CLASS = 11

# COPERNICUS/S2_SR_HARMONIZED stores reflectance bands as 0-10000 DN; this converts to 0-1.
S2_HARMONIZE_REFLECTANCE_SCALE = 0.0001

MAX_UPSTREAM_HOPS = 25  # generous for a small Himalayan headwater catchment; guards a runaway walk


def walk_upstream_basin_ids(seed_id, next_upstream) -> list:
    """The seed basin plus every basin upstream of it, found by repeatedly asking
    `next_upstream(frontier_ids) -> [basin_id, ...]` for the basins whose `NEXT_DOWN` is in the
    current frontier (HydroBASINS' standard "walk the drainage network" pattern). Stops when a
    call returns nothing new, or after `MAX_UPSTREAM_HOPS` hops. Pure/side-effect-free so it is
    testable without Earth Engine (`tests/m7_gee/test_provider.py`)."""
    basin_ids = [seed_id]
    frontier = [seed_id]
    for _ in range(MAX_UPSTREAM_HOPS):
        if not frontier:
            break
        new_ids = list(dict.fromkeys(i for i in next_upstream(frontier) if i not in basin_ids))
        if not new_ids:
            break
        basin_ids.extend(new_ids)
        frontier = new_ids
    return basin_ids


class MonthlyRaster(Protocol):
    index: np.ndarray  # NDWI (S2) or VV dB (S1), NaN where masked
    valid_pct: float  # % of the AOI buffer with any clear observation this month
    snow_ice_pct: float | None  # S2 only
    nir: np.ndarray | None  # S2 only: B8 surface reflectance (0-1), NaN where masked
    scene_ids: list[str]
    acquisition_dates: list[str]


class Provider(Protocol):
    """Everything `fetch.py` needs from a data source -- Earth Engine, or a synthetic stand-in."""

    def s2_month(self, grid: AoiGrid, month_start: date, month_end: date) -> MonthlyRaster | None:
        """`None` if no Sentinel-2 scene covers the AOI in [month_start, month_end)."""
        ...

    def s1_month(self, grid: AoiGrid, month_start: date, month_end: date) -> MonthlyRaster | None:
        """`None` if no Sentinel-1 scene covers the AOI in [month_start, month_end)."""
        ...

    def catchment(self, lake_lon: float, lake_lat: float, level: int) -> dict:
        """`{"geojson": <EPSG:4326 geometry dict>, "basin_ids": [...]}` for the basin containing
        the lake plus every basin upstream of it."""
        ...

    def rainfall_daily(self, catchment_geojson: dict, start: date, end: date, dataset: str) -> list[dict]:
        """`[{"date": "YYYY-MM-DD", "precip_mm": float}, ...]`, the catchment-mean daily total."""
        ...


# =============================================================================
# Earth Engine
# =============================================================================


class EarthEngineProvider:
    """Needs `ee.Initialize()` already called (`scene_search._ee_initialize`)."""

    def _pixel_grid(self, grid: AoiGrid) -> dict:
        """The REST `PixelGrid` object for `ee.data.computePixels` matching `grid` exactly."""
        return {
            "dimensions": {"width": grid.width, "height": grid.height},
            "affineTransform": {
                "scaleX": grid.cell_size_m, "shearX": 0.0, "translateX": grid.origin_x,
                "shearY": 0.0, "scaleY": -grid.cell_size_m, "translateY": grid.origin_y,
            },
            "crsCode": f"EPSG:{grid.epsg}",
        }

    def _compute_pixels(self, image, grid: AoiGrid):
        import ee.data

        result = ee.data.computePixels({
            "expression": image, "fileFormat": "NUMPY_NDARRAY", "grid": self._pixel_grid(grid),
        })
        return result  # structured numpy array, one field per band

    def _aoi_rectangle(self, grid: AoiGrid):
        import ee

        left, top = grid.origin_x, grid.origin_y
        right, bottom = left + grid.width * grid.cell_size_m, top - grid.height * grid.cell_size_m
        return ee.Geometry.Rectangle([left, bottom, right, top], proj=f"EPSG:{grid.epsg}", geodesic=False)

    def s2_month(self, grid: AoiGrid, month_start: date, month_end: date) -> MonthlyRaster | None:
        import ee

        aoi = self._aoi_rectangle(grid)
        coll = (ee.ImageCollection(S2_COLLECTION).filterBounds(aoi)
                .filterDate(month_start.isoformat(), month_end.isoformat()))
        ids = coll.aggregate_array("system:index").getInfo()
        if not ids:
            return None
        times = coll.aggregate_array("system:time_start").getInfo()
        dates = [datetime.fromtimestamp(t / 1000, tz=timezone.utc).strftime("%Y-%m-%d") for t in times]

        def _mask_and_index(img):
            scl = img.select("SCL")
            cloud = scl.remap(S2_SCL_CLOUD_CLASSES, [1] * len(S2_SCL_CLOUD_CLASSES), 0)
            valid = cloud.eq(0).rename("valid")
            ndwi = img.normalizedDifference(["B3", "B8"]).rename("ndwi").updateMask(valid)
            # B8 is stored as a 0-10000 DN; S2_HARMONIZE_REFLECTANCE_SCALE converts to 0-1
            # reflectance so `settings.nir_reflectance_max` (a physical reflectance) applies directly.
            nir = img.select("B8").multiply(S2_HARMONIZE_REFLECTANCE_SCALE).rename("nir").updateMask(valid)
            ice = scl.eq(S2_SCL_SNOW_ICE_CLASS).rename("ice")
            return ndwi.addBands(valid).addBands(nir).addBands(ice)

        composite = coll.map(_mask_and_index)
        image = ee.Image.cat([
            composite.select("ndwi").median().rename("ndwi"),
            composite.select("valid").mean().rename("valid_frac"),
            composite.select("nir").median().rename("nir"),
            composite.select("ice").mean().rename("ice_frac"),
        ]).clip(aoi)

        arr = self._compute_pixels(image, grid)
        ndwi = np.asarray(arr["ndwi"], dtype=float)
        valid_frac = np.asarray(arr["valid_frac"], dtype=float)
        nir = np.asarray(arr["nir"], dtype=float)
        ice_frac = np.asarray(arr["ice_frac"], dtype=float)
        ndwi[valid_frac <= 0] = np.nan
        nir[valid_frac <= 0] = np.nan

        return _Raster(
            index=ndwi, valid_pct=float(100.0 * np.nanmean(valid_frac)),
            snow_ice_pct=float(100.0 * np.nanmean(ice_frac)), nir=nir,
            scene_ids=ids, acquisition_dates=dates,
        )

    def s1_month(self, grid: AoiGrid, month_start: date, month_end: date) -> MonthlyRaster | None:
        import ee

        aoi = self._aoi_rectangle(grid)
        coll = (ee.ImageCollection(S1_COLLECTION).filterBounds(aoi)
                .filterDate(month_start.isoformat(), month_end.isoformat())
                .filter(ee.Filter.eq("instrumentMode", "IW")).select("VV"))
        ids = coll.aggregate_array("system:index").getInfo()
        if not ids:
            return None
        times = coll.aggregate_array("system:time_start").getInfo()
        dates = [datetime.fromtimestamp(t / 1000, tz=timezone.utc).strftime("%Y-%m-%d") for t in times]

        image = ee.Image.cat([
            coll.median().rename("vv"), coll.count().rename("count"),
        ]).clip(aoi)

        arr = self._compute_pixels(image, grid)
        vv = np.asarray(arr["vv"], dtype=float)
        count = np.asarray(arr["count"], dtype=float)
        vv[count <= 0] = np.nan

        return _Raster(
            index=vv, valid_pct=float(100.0 * np.mean(count > 0)), snow_ice_pct=None, nir=None,
            scene_ids=ids, acquisition_dates=dates,
        )

    def catchment(self, lake_lon: float, lake_lat: float, level: int) -> dict:
        import ee

        fc = ee.FeatureCollection(HYDROBASINS_COLLECTION_TEMPLATE.format(level=level))
        seed = fc.filterBounds(ee.Geometry.Point([lake_lon, lake_lat])).first()
        seed_id = seed.get("HYBAS_ID").getInfo()
        if seed_id is None:
            raise ValueError(f"no HydroBASINS level {level} polygon contains ({lake_lon}, {lake_lat})")

        def _next_upstream(frontier: list) -> list:
            return fc.filter(ee.Filter.inList("NEXT_DOWN", frontier)).aggregate_array("HYBAS_ID").getInfo()

        basin_ids = walk_upstream_basin_ids(seed_id, _next_upstream)

        dissolved = fc.filter(ee.Filter.inList("HYBAS_ID", basin_ids)).geometry().dissolve()
        return {"geojson": dissolved.getInfo(), "basin_ids": basin_ids}

    def rainfall_daily(self, catchment_geojson: dict, start: date, end: date, dataset: str) -> list[dict]:
        import ee

        aoi = ee.Geometry(catchment_geojson)

        if dataset == "chirps":
            coll = (ee.ImageCollection(CHIRPS_COLLECTION).filterBounds(aoi)
                    .filterDate(start.isoformat(), end.isoformat()))
            band = "precipitation"
        elif dataset == "gpm_imerg":
            # half-hourly precip rate (mm/hr) -> daily mm: sum(rate) * 0.5 h, summed per day below
            coll = (ee.ImageCollection(GPM_COLLECTION).filterBounds(aoi)
                    .filterDate(start.isoformat(), end.isoformat()))
            band = "precipitation"
        else:
            raise ValueError(f"unknown rainfall dataset '{dataset}'")

        def _daily_mean(img):
            stat = img.select(band).reduceRegion(
                reducer=ee.Reducer.mean(), geometry=aoi, scale=5000, maxPixels=1e10, bestEffort=True)
            return ee.Feature(None, {
                "date": img.date().format("YYYY-MM-dd"),
                "value": stat.get(band),
            })

        rows = coll.map(_daily_mean).getInfo()["features"]
        daily: dict[str, float] = {}
        for r in rows:
            props = r["properties"]
            if props.get("value") is None:
                continue
            value = float(props["value"]) * (0.5 if dataset == "gpm_imerg" else 1.0)
            daily[props["date"]] = daily.get(props["date"], 0.0) + value

        return [{"date": d, "precip_mm": v} for d, v in sorted(daily.items())]


class _Raster:
    """A concrete `MonthlyRaster` -- `Protocol` classes can't be instantiated directly."""

    def __init__(self, index, valid_pct, snow_ice_pct, scene_ids, acquisition_dates, nir=None):
        self.index = index
        self.valid_pct = valid_pct
        self.snow_ice_pct = snow_ice_pct
        self.nir = nir
        self.scene_ids = scene_ids
        self.acquisition_dates = acquisition_dates


# =============================================================================
# Synthetic (tests, CLAUDE.md rule 2)
# =============================================================================


class SyntheticProvider:
    """A small in-memory world for `tests/m7_gee/test_fetch.py`: a disc lake that shrinks after a
    given month (an "event"), a couple of cloudy/icy months, and a flat rainfall series. No network,
    no `ee`.
    """

    def __init__(
        self,
        lake_radius_px: int = 30,
        shrink_after: str | None = None,
        shrink_radius_px: int = 18,
        cloudy_months: tuple[str, ...] = (),
        icy_months: tuple[str, ...] = (),
        missing_months: tuple[str, ...] = (),
        rain_mm_per_day: float = 2.0,
        snow_bridge_months: tuple[str, ...] = (),
    ):
        self.lake_radius_px = lake_radius_px
        self.shrink_after = shrink_after
        self.shrink_radius_px = shrink_radius_px
        self.cloudy_months = set(cloudy_months)
        self.icy_months = set(icy_months)
        self.missing_months = set(missing_months)
        self.rain_mm_per_day = rain_mm_per_day
        #: months where a bright-NIR ("snow") corridor of NDWI-passing pixels connects the seeded
        #: lake disc to a second, separate lake-sized disc elsewhere in the AOI (regression fixture
        #: for `docs/decisions.md` 2026-09-28 "M7 GEE fetch: NIR test excludes snow from S2 water
        #: mask" -- without the NIR test, `seed_component` would merge the two into one blob).
        self.snow_bridge_months = set(snow_bridge_months)

    def _disc(self, grid: AoiGrid, radius_px: int, center: tuple[int, int] | None = None) -> np.ndarray:
        yy, xx = np.mgrid[0:grid.height, 0:grid.width]
        cy, cx = center if center is not None else (grid.height // 2, grid.width // 2)
        return (yy - cy) ** 2 + (xx - cx) ** 2 <= radius_px ** 2

    def _radius_for(self, month_key: str) -> int:
        if self.shrink_after is not None and month_key > self.shrink_after:
            return self.shrink_radius_px
        return self.lake_radius_px

    def s2_month(self, grid: AoiGrid, month_start: date, month_end: date) -> MonthlyRaster | None:
        key = month_start.strftime("%Y-%m")
        if key in self.missing_months:
            return None
        disc = self._disc(grid, self._radius_for(key))
        index = np.where(disc, 0.6, -0.4)
        nir = np.where(disc, 0.05, 0.3)  # open water is dark in the NIR; background is mid-grey
        if key in self.snow_bridge_months:
            cy, cx = grid.height // 2, grid.width // 2
            second_lake = self._disc(grid, self.lake_radius_px, center=(cy, min(grid.width - 1, cx + 3 * self.lake_radius_px)))
            bridge = np.zeros_like(disc)
            bridge[max(cy - 2, 0):cy + 2, cx:min(grid.width, cx + 3 * self.lake_radius_px)] = True
            snow = bridge | second_lake
            index = np.where(disc | snow, 0.6, -0.4)  # snow's NDWI still clears the Otsu threshold
            nir = np.where(disc, 0.05, np.where(bridge, 0.6, np.where(second_lake, 0.05, 0.3)))
        cloud_pct = 90.0 if key in self.cloudy_months else 2.0
        snow_ice_pct = 80.0 if key in self.icy_months else 1.0
        return _Raster(index=index, valid_pct=100.0 - cloud_pct, snow_ice_pct=snow_ice_pct, nir=nir,
                        scene_ids=[f"S2_{key}"], acquisition_dates=[month_start.isoformat()])

    def s1_month(self, grid: AoiGrid, month_start: date, month_end: date) -> MonthlyRaster | None:
        key = month_start.strftime("%Y-%m")
        if key in self.missing_months:
            return None
        disc = self._disc(grid, self._radius_for(key))
        index = np.where(disc, -20.0, -12.0)
        return _Raster(index=index, valid_pct=95.0, snow_ice_pct=None,
                        scene_ids=[f"S1_{key}"], acquisition_dates=[month_start.isoformat()])

    def catchment(self, lake_lon: float, lake_lat: float, level: int) -> dict:
        d = 0.05
        poly = {"type": "Polygon", "coordinates": [[
            [lake_lon - d, lake_lat - d], [lake_lon + d, lake_lat - d],
            [lake_lon + d, lake_lat + d], [lake_lon - d, lake_lat + d], [lake_lon - d, lake_lat - d],
        ]]}
        return {"geojson": poly, "basin_ids": ["synth_0001"]}

    def rainfall_daily(self, catchment_geojson: dict, start: date, end: date, dataset: str) -> list[dict]:
        rows = []
        d = start
        while d < end:
            rows.append({"date": d.isoformat(), "precip_mm": self.rain_mm_per_day})
            d += timedelta(days=1)
        return rows
