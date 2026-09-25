"""Tests for backend.m1_terrain.centreline."""

from __future__ import annotations

import copy

import numpy as np
import pytest

from backend.m1_terrain import centreline, hydro
from backend.m1_terrain.settings import TerrainSettings
from backend.shared.grid import build_site_grids, lonlat_to_rowcol

from . import synthetic_valley as sv


def _dem_and_network(grid, geom):
    rows, cols = np.indices(grid.shape)
    x = grid.origin_x + (cols + 0.5) * grid.cell_size_m
    y = grid.origin_y - (rows + 0.5) * grid.cell_size_m
    dem = sv.elevation(x, y, geom).astype(np.float32)
    return dem, hydro.route(dem)


def test_find_breach_cell_snaps_near_the_breach_location(synth_config, valley_geometry):
    grid = build_site_grids(synth_config)["farfield"]
    dem, network = _dem_and_network(grid, valley_geometry)
    dam = synth_config.dams[0]

    cell = centreline.find_breach_cell(dam, network, grid, TerrainSettings())
    assert cell is not None
    exp_row, exp_col = lonlat_to_rowcol(grid, *dam.breach_location.value)
    radius_cells = TerrainSettings().snap_radius_m / grid.cell_size_m
    assert abs(cell[0] - exp_row) <= radius_cells
    assert abs(cell[1] - exp_col) <= radius_cells


def test_find_breach_cell_none_for_placeholder_location(synth_config, valley_geometry):
    grid = build_site_grids(synth_config)["farfield"]
    dem, network = _dem_and_network(grid, valley_geometry)
    cfg2 = copy.deepcopy(synth_config)
    dam = cfg2.dams[0]
    dam.breach_location.value = None
    dam.breach_location.status = "placeholder"
    assert centreline.find_breach_cell(dam, network, grid, TerrainSettings()) is None


def test_chainage_monotonic_and_sampled_every_cell_size(synth_config, valley_geometry):
    grid = build_site_grids(synth_config)["farfield"]
    dem, network = _dem_and_network(grid, valley_geometry)
    dam = synth_config.dams[0]
    breach_cell = centreline.find_breach_cell(dam, network, grid, TerrainSettings())

    path = centreline.trace_centreline(network, *breach_cell, grid)
    assert path["chainage_m"].iloc[0] == 0.0
    assert path["chainage_m"].is_monotonic_increasing

    samples = centreline.resample_chainage(path, dem, grid.cell_size_m)
    assert np.allclose(np.diff(samples["chainage_m"]), grid.cell_size_m)
    # bed elevation decreases downstream (down-valley slope), apart from float noise
    assert samples["bed_elev_m"].iloc[-1] < samples["bed_elev_m"].iloc[0]


def test_channel_mask_marks_traced_cells(synth_config, valley_geometry):
    grid = build_site_grids(synth_config)["farfield"]
    dem, network = _dem_and_network(grid, valley_geometry)
    dam = synth_config.dams[0]
    breach_cell = centreline.find_breach_cell(dam, network, grid, TerrainSettings())
    path = centreline.trace_centreline(network, *breach_cell, grid)

    mask = centreline.channel_mask_from_path(path, grid)
    assert mask.sum() == len(path)
    assert mask[path["row"].iloc[0], path["col"].iloc[0]]


def test_snap_pois_finds_town_a_and_skips_null_location(synth_config, valley_geometry):
    grid = build_site_grids(synth_config)["farfield"]
    dem, network = _dem_and_network(grid, valley_geometry)
    dam = synth_config.dams[0]
    breach_cell = centreline.find_breach_cell(dam, network, grid, TerrainSettings())
    path = centreline.trace_centreline(network, *breach_cell, grid)

    # bridge_b's location is status: placeholder but still has a guessed [lon, lat] value in
    # synth.yaml, so it snaps normally; snap_pois only skips a *null* location (SourcedValue
    # allows null only for placeholders, but a placeholder need not be null).
    pois_df, skipped = centreline.snap_pois(synth_config.site.id, synth_config.points_of_interest, path, grid)
    assert skipped == []
    assert len(pois_df) == 2
    town_a = pois_df.loc[pois_df["poi_id"] == "synth__poi__town_a"].iloc[0]
    assert town_a["kind"] == "village"
    # town_a sits on the analytical thalweg by construction (conftest.DOWNSTREAM_LONLAT)
    assert town_a["dist_to_channel_m"] < 2 * grid.cell_size_m


def test_snap_pois_skips_null_location(synth_config, valley_geometry):
    grid = build_site_grids(synth_config)["farfield"]
    dem, network = _dem_and_network(grid, valley_geometry)
    dam = synth_config.dams[0]
    breach_cell = centreline.find_breach_cell(dam, network, grid, TerrainSettings())
    path = centreline.trace_centreline(network, *breach_cell, grid)

    cfg2 = copy.deepcopy(synth_config)
    cfg2.points_of_interest[1].location.value = None
    pois_df, skipped = centreline.snap_pois(cfg2.site.id, cfg2.points_of_interest, path, grid)
    assert skipped == ["bridge_b"]
    assert len(pois_df) == 1
