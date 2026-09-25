"""Tests for backend.m1_terrain.water (lake/reservoir extent) and backend.m1_terrain.burn
(dam crest + reservoir burn-in)."""

from __future__ import annotations

import copy

import numpy as np

from backend.m1_terrain import burn, hydro, water
from backend.m1_terrain.settings import TerrainSettings
from backend.shared.grid import build_site_grids, lonlat_to_rowcol

from . import synthetic_valley as sv


def _farfield_grid(cfg):
    return build_site_grids(cfg)["farfield"]


def _grid_dem(grid, geom, lake_center=None, reservoir_center=None):
    rows, cols = np.indices(grid.shape)
    x = grid.origin_x + (cols + 0.5) * grid.cell_size_m
    y = grid.origin_y - (rows + 0.5) * grid.cell_size_m
    return sv.elevation(x, y, geom, lake_center=lake_center, reservoir_center=reservoir_center).astype(np.float32)


def test_water_mask_finds_lake_for_moraine_dam(synth_config):
    grid = _farfield_grid(synth_config)
    dam = synth_config.dams[0]
    row, col = lonlat_to_rowcol(grid, *dam.location.value)
    rr, cc = np.indices(grid.shape)
    lake_cells = (rr - row) ** 2 + (cc - col) ** 2 <= 9
    landcover = np.full(grid.shape, 30, dtype=np.uint8)
    landcover[lake_cells] = 80

    mask, info = water.water_mask(landcover, synth_config, grid, TerrainSettings())
    assert info["dams"][dam.id]["found"] is True
    assert info["dams"][dam.id]["label"] == "lake"
    assert np.array_equal(mask == water.LAKE, lake_cells)


def test_water_mask_reports_not_found_when_nothing_in_range(synth_config):
    grid = _farfield_grid(synth_config)
    landcover = np.full(grid.shape, 30, dtype=np.uint8)  # no water anywhere
    mask, info = water.water_mask(landcover, synth_config, grid, TerrainSettings())
    dam = synth_config.dams[0]
    assert info["dams"][dam.id]["found"] is False
    assert (mask == water.LAND).all()


def test_burn_dam_crest_raises_terrain_and_never_lowers_it(synth_config, valley_geometry):
    grid = _farfield_grid(synth_config)
    # synth.yaml's dam.location isn't on this test module's analytical thalweg (it's a real
    # site-config value, not derived from the geometry tests/m1_terrain/synthetic_valley.py
    # invents); move it onto the thalweg so "local bed" search finds genuinely low terrain.
    cfg2 = copy.deepcopy(synth_config)
    dam = cfg2.dams[0]
    lon, lat = sv.utm_to_lonlat(*valley_geometry.point_at(-100.0))
    dam.location.value = [lon, lat]
    dem = _grid_dem(grid, valley_geometry)
    network = hydro.route(dem)

    burned, info = burn.burn_dam_crest(dem, dam, network, grid, TerrainSettings())
    assert info["burned"] is True
    row, col = lonlat_to_rowcol(grid, *dam.location.value)
    assert burned[row, col] >= info["crest_elevation_m"] - 1e-3
    assert np.all(burned >= dem)
    assert info["cells_raised"] > 0


def test_burn_dam_crest_skips_placeholder_dam_height(synth_config, valley_geometry):
    grid = _farfield_grid(synth_config)
    cfg2 = copy.deepcopy(synth_config)
    dam = cfg2.dams[0]
    dam.breach_inputs.dam_height.value = None
    dam.breach_inputs.dam_height.status = "placeholder"

    dem = _grid_dem(grid, valley_geometry)
    network = hydro.route(dem)
    burned, info = burn.burn_dam_crest(dem, dam, network, grid, TerrainSettings())
    assert info["burned"] is False
    assert "dam_height" in info["reason"]
    assert np.array_equal(burned, dem)


def test_burn_dam_crest_skips_placeholder_location(synth_config, valley_geometry):
    grid = _farfield_grid(synth_config)
    cfg2 = copy.deepcopy(synth_config)
    dam = cfg2.dams[0]
    dam.location.value = None
    dam.location.status = "placeholder"

    dem = _grid_dem(grid, valley_geometry)
    network = hydro.route(dem)
    burned, info = burn.burn_dam_crest(dem, dam, network, grid, TerrainSettings())
    assert info["burned"] is False
    assert np.array_equal(burned, dem)


def test_burn_reservoir_flattens_footprint_to_one_elevation(synth_config_two_dams, valley_geometry, second_dam_lonlat):
    grid = _farfield_grid(synth_config_two_dams)
    dam2 = synth_config_two_dams.dams[1]
    reservoir_center = sv.lonlat_to_utm(*second_dam_lonlat)
    dem = _grid_dem(grid, valley_geometry, reservoir_center=reservoir_center)

    row, col = lonlat_to_rowcol(grid, *dam2.location.value)
    rr, cc = np.indices(grid.shape)
    reservoir_cells = (rr - row) ** 2 + (cc - col) ** 2 <= 25
    mask = np.zeros(grid.shape, dtype=np.uint8)
    mask[reservoir_cells] = water.RESERVOIR

    burned, info = burn.burn_reservoir(dem, mask, water.RESERVOIR)
    assert info["burned"] is True
    values = burned[reservoir_cells]
    assert np.allclose(values, values[0])
    assert np.allclose(values[0], info["surface_elevation_m"])
    assert np.array_equal(burned[~reservoir_cells], dem[~reservoir_cells])  # unaffected cells untouched
