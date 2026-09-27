"""Unit tests for `backend.m0_api.dem_diagnostics` -- the depression/slope classifier that flags
known artifact classes in a direct run's headline numbers (docs/progress.md 2026-09-27 "Teesta
MVP dashboard stabilization" D-Flow headline investigation)."""
from __future__ import annotations

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from backend.m0_api import dem_diagnostics
from backend.shared.grid import FLOAT_NODATA


def test_compute_diagnostics_flags_interior_pit_not_boundary():
    dem = np.full((9, 9), 100.0, dtype=np.float32)
    dem[4, 4] = 90.0  # a 10 m deep interior pit, well inside the grid boundary
    depression_depth, slope = dem_diagnostics.compute_diagnostics(dem, cell_size_m=10.0)
    # route()'s epsilon variant enforces a strict downhill gradient, so a flooded flat area picks
    # up tiny (~1e-5 per step) fill; well below any real threshold, so an absolute tolerance is used.
    assert depression_depth[4, 4] == pytest.approx(10.0, abs=0.01)
    # the grid boundary is a drainage outlet by construction (backend.m1_terrain.hydro.route), so
    # it is never flagged even though it is the same elevation as everywhere but the pit
    assert depression_depth[0, 0] < 0.01
    assert (depression_depth[[0, -1], :] < 0.01).all()
    assert (depression_depth[:, [0, -1]] < 0.01).all()


def test_compute_diagnostics_flat_dem_has_no_depression_or_slope():
    dem = np.full((9, 9), 100.0, dtype=np.float32)
    depression_depth, slope = dem_diagnostics.compute_diagnostics(dem, cell_size_m=10.0)
    assert (depression_depth < 0.01).all()
    assert (slope == 0.0).all()


def test_compute_diagnostics_slope_step():
    dem = np.zeros((9, 9), dtype=np.float32)
    dem[:, 5:] = 50.0  # a sharp step: 50 m rise over 10 m cells
    _, slope = dem_diagnostics.compute_diagnostics(dem, cell_size_m=10.0)
    assert slope[4, 4] > slope[4, 1]  # near the step is steeper than the flat side
    assert slope[4, 4] > 1.0


def test_compute_diagnostics_ignores_nodata():
    dem = np.full((9, 9), 100.0, dtype=np.float32)
    dem[4, 4] = 90.0
    dem[0:2, 0:2] = FLOAT_NODATA
    depression_depth, slope = dem_diagnostics.compute_diagnostics(dem, cell_size_m=10.0)
    assert (depression_depth[0:2, 0:2] == 0.0).all()
    assert (slope[0:2, 0:2] == 0.0).all()


def test_ensure_cached_diagnostics_reuses_cache_until_dem_changes(tmp_path):
    dem_path = tmp_path / "dem.tif"
    cache_dir = tmp_path / "_diagnostics"
    profile = {"driver": "GTiff", "height": 9, "width": 9, "count": 1, "dtype": "float32",
               "crs": "EPSG:32645", "transform": from_origin(0, 90, 10, 10), "nodata": FLOAT_NODATA}
    dem = np.full((9, 9), 100.0, dtype=np.float32)
    dem[4, 4] = 90.0
    with rasterio.open(dem_path, "w", **profile) as ds:
        ds.write(dem, 1)

    depression_path, slope_path = dem_diagnostics.ensure_cached_diagnostics(dem_path, cache_dir)
    with rasterio.open(depression_path) as ds:
        first = ds.read(1)
    assert first[4, 4] == pytest.approx(10.0, abs=0.01)

    stamp_before = (cache_dir / "dem_diagnostics.stamp").read_text()
    depression_path2, _ = dem_diagnostics.ensure_cached_diagnostics(dem_path, cache_dir)
    assert (cache_dir / "dem_diagnostics.stamp").read_text() == stamp_before
    assert depression_path2 == depression_path

    dem[4, 4] = 80.0
    with rasterio.open(dem_path, "w", **profile) as ds:
        ds.write(dem, 1)
    dem_diagnostics.ensure_cached_diagnostics(dem_path, cache_dir)
    with rasterio.open(depression_path) as ds:
        updated = ds.read(1)
    assert updated[4, 4] == pytest.approx(20.0, abs=0.01)


def test_resample_to_uses_max_within_destination_cell():
    source_path_dir = None
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        from pathlib import Path
        source_path = Path(tmp) / "fine.tif"
        # two 10 m source cells inside one 20 m destination cell; the destination should pick
        # the larger of the two (the conservative direction for an artifact mask)
        profile = {"driver": "GTiff", "height": 1, "width": 2, "count": 1, "dtype": "float32",
                   "crs": "EPSG:32645", "transform": from_origin(0, 10, 10, 10), "nodata": FLOAT_NODATA}
        with rasterio.open(source_path, "w", **profile) as ds:
            ds.write(np.array([[1.0, 5.0]], dtype=np.float32), 1)
        dest_transform = from_origin(0, 10, 20, 10)
        result = dem_diagnostics.resample_to(source_path, like_transform=dest_transform,
                                              like_crs="EPSG:32645", like_shape=(1, 1))
        assert result[0, 0] == 5.0


def test_load_settings_defaults_and_overrides():
    settings = dem_diagnostics.load_settings()
    assert settings.dem_depression_depth_threshold_m == 2.0
    overridden = dem_diagnostics.load_settings(steep_reach_slope_threshold=0.5)
    assert overridden.steep_reach_slope_threshold == 0.5
    assert overridden.dem_depression_depth_threshold_m == 2.0
