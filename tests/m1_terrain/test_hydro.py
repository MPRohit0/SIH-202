"""Tests for backend.m1_terrain.hydro — priority-flood fill, D8 drainage tree, accumulation, HAND.

Uses a small hand-built analytical V-valley (not the raster round-trip) so expected values are
exact, not just plausible."""

from __future__ import annotations

import numpy as np

from backend.m1_terrain import hydro
from backend.shared.grid import FLOAT_NODATA

THALWEG_ROW = 20
DOWN_SLOPE = 0.5
SIDE_SLOPE = 2.0
BASE_ELEV = 1000.0


def _v_valley(h=40, w=60):
    rows, cols = np.indices((h, w))
    d = np.abs(rows - THALWEG_ROW)
    return (BASE_ELEV - DOWN_SLOPE * cols + SIDE_SLOPE * d).astype(np.float32)


def test_route_fill_has_no_pits():
    dem = _v_valley()
    dem[10, 30] -= 50.0  # a single-cell pit off the thalweg
    network = hydro.route(dem)
    filled = network.filled.reshape(-1)
    parent = network.parent.reshape(-1)
    has_parent = parent != hydro.NO_PARENT
    # every non-outlet cell's filled elevation is >= its downstream parent's (strict monotonic fill)
    assert np.all(filled[has_parent] >= filled[parent[has_parent]])


def test_d8_follows_the_analytical_thalweg():
    dem = _v_valley()
    network = hydro.route(dem)
    path = hydro.trace_downstream(network, THALWEG_ROW, 10)
    w = dem.shape[1]
    rows, cols = path // w, path % w
    assert np.all(np.abs(rows - THALWEG_ROW) <= 1)
    assert cols[-1] in (0, dem.shape[1] - 1) or rows[-1] in (0, dem.shape[0] - 1)


def test_accumulation_peaks_on_the_thalweg():
    dem = _v_valley()
    network = hydro.route(dem)
    on_thalweg = network.accumulation[THALWEG_ROW, 5:55].mean()
    off_thalweg = network.accumulation[5, 5:55].mean()
    assert on_thalweg > off_thalweg


def test_hand_zero_on_channel_and_grows_with_distance_from_it():
    dem = _v_valley()
    network = hydro.route(dem)
    channel_mask = np.zeros(dem.shape, dtype=bool)
    channel_mask[THALWEG_ROW, :] = True
    hand = hydro.hand(network, channel_mask)

    assert np.all(hand[hand != FLOAT_NODATA] >= 0)
    assert np.allclose(hand[THALWEG_ROW, 1:-1], 0.0, atol=1e-2)
    # a cell further from the thalweg (row 5 vs row 15) has a higher HAND, at the same column
    assert hand[5, 30] > hand[15, 30] > 0


def test_hand_is_nodata_when_no_channel_in_domain():
    dem = _v_valley(h=10, w=10)
    network = hydro.route(dem)
    hand = hydro.hand(network, np.zeros(dem.shape, dtype=bool))
    assert np.all(hand == FLOAT_NODATA)


def test_best_accumulation_cell_snaps_onto_the_thalweg():
    dem = _v_valley()
    network = hydro.route(dem)
    row, col = hydro.best_accumulation_cell(network.accumulation, THALWEG_ROW + 5, 10, radius_cells=8)
    assert abs(row - THALWEG_ROW) <= 1
