"""Tests for backend.m1_terrain.dem — DEM/landcover loading onto the canonical grid, void fill."""

from __future__ import annotations

import numpy as np

from backend.m1_terrain import dem as dem_mod
from backend.shared.grid import FLOAT_NODATA, UINT8_NODATA, build_site_grids

from . import synthetic_valley as sv


def _write_synth_raw(tmp_path, cfg):
    bbox = cfg.domains.far_field.bbox.value
    return sv.write_raw_rasters(tmp_path, bbox, (88.46, 27.54), (88.49, 27.49), (88.46, 27.545))


def test_load_dem_and_landcover_match_grid(tmp_path, synth_config):
    grids = build_site_grids(synth_config)
    farfield = grids["farfield"]
    _write_synth_raw(tmp_path, synth_config)

    dem = dem_mod.load_dem(tmp_path / "dem_srtm_gl1.tif", farfield)
    assert dem.shape == farfield.shape
    assert dem.dtype == np.float32

    lc = dem_mod.load_landcover(tmp_path / "landcover_esa_worldcover.tif", farfield)
    assert lc.shape == farfield.shape
    assert lc.dtype == np.uint8
    assert set(np.unique(lc)) <= {10, 30, 60, 80, UINT8_NODATA}


def test_load_dem_on_nearfield_grid(tmp_path, synth_config):
    grids = build_site_grids(synth_config)
    nearfield = grids["nearfield"]
    _write_synth_raw(tmp_path, synth_config)

    dem = dem_mod.load_dem(tmp_path / "dem_srtm_gl1.tif", nearfield)
    assert dem.shape == nearfield.shape
    assert dem.dtype == np.float32
    # the near-field bbox is fully inside the raw raster's extent, so it should be fully covered
    assert (dem == FLOAT_NODATA).sum() == 0


def test_fill_voids_removes_nodata_and_stays_in_range(tmp_path, synth_config):
    grids = build_site_grids(synth_config)
    farfield = grids["farfield"]
    _write_synth_raw(tmp_path, synth_config)

    raw = dem_mod.load_dem(tmp_path / "dem_srtm_gl1.tif", farfield)
    assert (raw == FLOAT_NODATA).sum() > 0, "the synthetic void patch should survive resampling onto the far-field grid"

    filled, stats = dem_mod.fill_voids(raw, max_search_distance=200)
    assert stats.void_cells_before > 0
    assert stats.total_cells == farfield.shape[0] * farfield.shape[1]
    assert stats.void_cells_after == 0  # a generous search distance should close the whole patch

    valid = raw != FLOAT_NODATA
    lo, hi = raw[valid].min(), raw[valid].max()
    was_void = raw == FLOAT_NODATA
    assert filled[was_void].min() >= lo - 5.0
    assert filled[was_void].max() <= hi + 5.0


def test_landcover_legend_covers_synthetic_codes():
    legend = dem_mod.landcover_legend()
    for code in (10, 30, 60, 80):
        assert code in legend
