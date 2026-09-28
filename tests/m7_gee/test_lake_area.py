"""Tests for backend.m7_gee.lake_area -- pure numpy/shapely logic, no Earth Engine involved."""

from __future__ import annotations

import math

import numpy as np
import pytest

from backend.m7_gee import lake_area as la
from backend.m7_gee.settings import GeeSettings


@pytest.fixture
def settings():
    return GeeSettings()


class TestOtsuThreshold:
    def test_separates_a_bimodal_histogram(self):
        rng = np.random.default_rng(0)
        low = rng.normal(-0.3, 0.05, 2000)
        high = rng.normal(0.5, 0.05, 2000)
        values = np.concatenate([low, high])
        threshold = la.otsu_threshold(values, clamp=(-1.0, 1.0))
        assert -0.1 < threshold < 0.2

    def test_clamps_to_the_given_range(self):
        # a histogram whose natural split sits well outside the clamp range
        values = np.array([10.0] * 100 + [20.0] * 100)
        threshold = la.otsu_threshold(values, clamp=(-0.2, 0.4))
        assert threshold == pytest.approx(0.4)

    def test_uniform_input_falls_back_to_clamp_midpoint(self):
        values = np.full(100, 0.1)
        threshold = la.otsu_threshold(values, clamp=(-0.2, 0.4))
        assert threshold == pytest.approx(0.1)

    def test_too_few_finite_values_falls_back_to_clamp_midpoint(self):
        values = np.array([np.nan, np.nan, 0.3])
        threshold = la.otsu_threshold(values, clamp=(-0.2, 0.4))
        assert threshold == pytest.approx(0.1)


def _disc_grid(radius_px=30, size=200, blob_offset=(-80, -80), blob_radius=8):
    grid = la.AoiGrid(epsg=32645, origin_x=0.0, origin_y=size * 10.0, cell_size_m=10.0, width=size, height=size)
    yy, xx = np.mgrid[0:size, 0:size]
    center = size // 2
    disc = (yy - center) ** 2 + (xx - center) ** 2 <= radius_px ** 2

    by, bx = center + blob_offset[0], center + blob_offset[1]
    blob = (yy - by) ** 2 + (xx - bx) ** 2 <= blob_radius ** 2

    index = np.full((size, size), -0.5)  # dry land
    index[disc] = 0.6
    index[blob] = 0.6  # a disconnected water-like patch (e.g. SAR shadow)
    return grid, index, disc, blob, (center, center)


class TestWaterMaskAndSeedComponent:
    def test_water_mask_above_threshold(self):
        index = np.array([-0.3, 0.0, 0.5])
        mask = la.water_mask(index, threshold=0.1)
        assert list(mask) == [False, False, True]

    def test_water_mask_below_threshold_for_sar(self):
        index = np.array([-25.0, -15.0, -5.0])
        mask = la.water_mask(index, threshold=-18.0, below=True)
        assert list(mask) == [True, False, False]

    def test_nan_pixels_are_never_water(self):
        index = np.array([np.nan, 0.5])
        assert list(la.water_mask(index, threshold=0.0)) == [False, True]

    def test_seed_component_keeps_only_the_lake_drops_disconnected_blob(self):
        grid, index, disc, blob, seed_rc = _disc_grid()
        mask = la.water_mask(index, threshold=0.1)
        component = la.seed_component(mask, seed_rc)
        assert np.array_equal(component, disc)
        assert not np.array_equal(component, mask)  # the blob was in `mask` but dropped

    def test_seed_off_water_snaps_to_nearest_component(self):
        grid, index, disc, blob, seed_rc = _disc_grid()
        mask = la.water_mask(index, threshold=0.1)
        # seed one pixel outside the disc edge, still on dry land
        off_seed = (seed_rc[0] - 35, seed_rc[1])
        component = la.seed_component(mask, off_seed)
        assert np.array_equal(component, disc)

    def test_no_water_at_all_gives_empty_component(self):
        mask = np.zeros((10, 10), dtype=bool)
        component = la.seed_component(mask, (5, 5))
        assert not component.any()


class TestNirFiltersSnow:
    def test_bright_nir_pixel_is_excluded_even_if_ndwi_passes(self):
        index = np.array([0.6, 0.6])  # both pass the NDWI threshold
        nir = np.array([0.05, 0.6])  # water, then snow
        mask = la.water_mask(index, threshold=0.1, nir=nir, nir_max=0.15)
        assert list(mask) == [True, False]

    def test_without_nir_args_snow_pixel_still_passes(self):
        # documents the pre-fix behaviour this test class guards against
        index = np.array([0.6, 0.6])
        mask = la.water_mask(index, threshold=0.1)
        assert list(mask) == [True, True]

    def test_nan_nir_pixel_is_excluded(self):
        index = np.array([0.6])
        nir = np.array([np.nan])
        mask = la.water_mask(index, threshold=0.1, nir=nir, nir_max=0.15)
        assert list(mask) == [False]

    def test_snow_bridge_no_longer_merges_two_lakes_once_nir_filtered(self):
        """Regression for the South Lhonak overestimate (docs/decisions.md 2026-09-28): a bright
        NIR ("snow") corridor connects the seeded lake to a second, separate lake-sized disc. Without
        the NIR test, `seed_component` follows the corridor and reports one inflated blob; with it,
        the corridor breaks and only the seeded lake remains."""
        size = 200
        grid = la.AoiGrid(epsg=32645, origin_x=0.0, origin_y=size * 10.0, cell_size_m=10.0, width=size, height=size)
        yy, xx = np.mgrid[0:size, 0:size]
        cy, cx = size // 2, size // 2
        lake_radius = 20
        lake = (yy - cy) ** 2 + (xx - cx) ** 2 <= lake_radius ** 2
        second_cx = cx + 3 * lake_radius
        second_lake = (yy - cy) ** 2 + (xx - second_cx) ** 2 <= lake_radius ** 2
        bridge = np.zeros((size, size), dtype=bool)
        bridge[cy - 2:cy + 2, cx:second_cx] = True

        index = np.where(lake | bridge | second_lake, 0.6, -0.4)
        nir = np.where(lake, 0.05, np.where(bridge, 0.6, np.where(second_lake, 0.05, 0.3)))
        seed_rc = (cy, cx)

        mask_no_nir = la.water_mask(index, threshold=0.1)
        merged = la.seed_component(mask_no_nir, seed_rc)
        assert merged.sum() > lake.sum() * 1.5  # the un-fixed mask picks up the bridge + second lake

        mask_with_nir = la.water_mask(index, threshold=0.1, nir=nir, nir_max=0.15)
        fixed = la.seed_component(mask_with_nir, seed_rc)
        assert np.array_equal(fixed, lake)


class TestSlopeMasking:
    def test_flat_surface_has_zero_slope(self):
        dem = np.full((20, 20), 100.0)
        slope = la.slope_deg_from_elevation(dem, cell_size_m=10.0)
        assert np.allclose(slope, 0.0)

    def test_uniform_tilt_gives_the_known_angle(self):
        # 1 m rise per 10 m run along rows -> arctan(1/10) ~ 5.71 deg, constant everywhere
        rows = np.arange(20).reshape(-1, 1) * np.ones((1, 20))
        dem = rows * 1.0  # 1 m elevation step per row, rows are 10 m apart
        slope = la.slope_deg_from_elevation(dem, cell_size_m=10.0)
        expected = math.degrees(math.atan(1.0 / 10.0))
        # edges use a one-sided difference (np.gradient), so only the interior is exact
        assert np.allclose(slope[2:-2, 2:-2], expected, atol=0.01)

    def test_steeper_tilt_gives_a_larger_angle(self):
        rows = np.arange(20).reshape(-1, 1) * np.ones((1, 20))
        gentle = la.slope_deg_from_elevation(rows * 1.0, cell_size_m=10.0)
        steep = la.slope_deg_from_elevation(rows * 5.0, cell_size_m=10.0)
        assert steep[5, 5] > gentle[5, 5]

    def test_water_mask_excludes_steep_pixels_even_if_backscatter_passes(self):
        index = np.array([-20.0, -20.0])  # both pass a below=True VV threshold
        slope_deg = np.array([2.0, 15.0])  # flat lake, then a steep radar-shadow slope
        mask = la.water_mask(index, threshold=-15.0, below=True,
                              slope_deg=slope_deg, max_slope_deg=6.0)
        assert list(mask) == [True, False]

    def test_nan_slope_pixel_is_excluded(self):
        index = np.array([-20.0])
        slope_deg = np.array([np.nan])
        mask = la.water_mask(index, threshold=-15.0, below=True,
                              slope_deg=slope_deg, max_slope_deg=6.0)
        assert list(mask) == [False]

    def test_without_slope_args_steep_pixel_still_passes(self):
        # documents the pre-fix behaviour this class guards against
        index = np.array([-20.0, -20.0])
        mask = la.water_mask(index, threshold=-15.0, below=True)
        assert list(mask) == [True, True]

    def test_dem_slope_deg_reprojects_and_resamples_onto_the_aoi_grid(self, tmp_path):
        """`dem_slope_deg` reads a DEM file at its own resolution/CRS and produces slope on the
        target `AoiGrid` -- a real rasterio round trip, not just the pure numpy gradient math."""
        import rasterio
        from rasterio.transform import from_origin

        dem_path = tmp_path / "dem.tif"
        size = 40
        rows = np.arange(size, dtype=np.float32).reshape(-1, 1) * np.ones((1, size), dtype=np.float32)
        dem = (rows * 2.0 + 1000.0).astype(np.float32)  # 2 m rise per 30 m row -> flat-ish slope
        with rasterio.open(
            dem_path, "w", driver="GTiff", width=size, height=size, count=1, dtype="float32",
            crs="EPSG:32645", transform=from_origin(500000.0, 3100000.0, 30.0, 30.0), nodata=-9999.0,
        ) as dst:
            dst.write(dem, 1)

        grid = la.AoiGrid(epsg=32645, origin_x=500100.0, origin_y=3099900.0, cell_size_m=10.0, width=30, height=30)
        slope = la.dem_slope_deg(dem_path, grid)
        assert slope.shape == grid.shape
        assert np.isfinite(slope).any()  # the AOI grid sits inside the DEM's coverage
        assert np.all(slope[np.isfinite(slope)] >= 0.0)


class TestAreaAndPolygon:
    def test_component_area_matches_pixel_count_times_cell_area(self):
        grid, index, disc, blob, seed_rc = _disc_grid()
        area = la.component_area_m2(disc, grid)
        assert area == pytest.approx(disc.sum() * grid.cell_size_m ** 2)

    def test_disc_area_is_close_to_pi_r_squared(self):
        radius_px, cell = 30, 10.0
        grid, index, disc, blob, seed_rc = _disc_grid(radius_px=radius_px)
        area = la.component_area_m2(disc, grid)
        expected = math.pi * (radius_px * cell) ** 2
        assert area == pytest.approx(expected, rel=0.05)

    def test_polygonize_lonlat_returns_a_polygon_covering_the_disc(self):
        grid, index, disc, blob, seed_rc = _disc_grid()
        geojson = la.polygonize_lonlat(disc, grid)
        assert geojson["type"] in ("Polygon", "MultiPolygon")

    def test_polygonize_empty_component_gives_empty_geometry(self):
        grid, index, disc, blob, seed_rc = _disc_grid()
        empty = np.zeros_like(disc)
        geojson = la.polygonize_lonlat(empty, grid)
        assert geojson["coordinates"] == []


class TestChooseMethod:
    def test_ice_skips_regardless_of_cloud(self, settings):
        method, reason = la.choose_method(
            s2_cloud_pct=0.0, s2_snow_ice_pct=90.0, s1_available=True, s1_valid_pct=100.0, settings=settings)
        assert (method, reason) == ("skip", "snow_ice")

    def test_clear_s2_is_preferred(self, settings):
        method, reason = la.choose_method(
            s2_cloud_pct=5.0, s2_snow_ice_pct=0.0, s1_available=True, s1_valid_pct=100.0, settings=settings)
        assert (method, reason) == ("s2_water_index", None)

    def test_cloudy_s2_falls_back_to_s1(self, settings):
        method, reason = la.choose_method(
            s2_cloud_pct=80.0, s2_snow_ice_pct=0.0, s1_available=True, s1_valid_pct=100.0, settings=settings)
        assert (method, reason) == ("s1_threshold", None)

    def test_no_s2_scene_and_no_s1_scene_skips(self, settings):
        method, reason = la.choose_method(
            s2_cloud_pct=None, s2_snow_ice_pct=None, s1_available=False, s1_valid_pct=None, settings=settings)
        assert (method, reason) == ("skip", "no_usable_scene")

    def test_s1_coverage_too_sparse_skips(self, settings):
        method, reason = la.choose_method(
            s2_cloud_pct=90.0, s2_snow_ice_pct=0.0, s1_available=True, s1_valid_pct=10.0, settings=settings)
        assert (method, reason) == ("skip", "no_usable_scene")
