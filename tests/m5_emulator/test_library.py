"""Tests for backend.m5_emulator.library (docs/m5_specs.md §2)."""

from __future__ import annotations

import numpy as np

from backend.m5_emulator import library as lib
from backend.m5_emulator import synthetic as sw
from backend.shared.grid import FLOAT_NODATA


# --------------------------------------------------------------------------- maximin_lhs


def test_maximin_lhs_is_stratified_one_point_per_bin_per_dimension():
    n, d = 12, 3
    sample = lib.maximin_lhs(n, d, seed=0, n_candidates=5)
    assert sample.shape == (n, d)
    assert (sample >= 0).all() and (sample < 1).all()
    for col in range(d):
        bins = np.floor(sample[:, col] * n).astype(int)
        assert sorted(bins) == list(range(n))  # exactly one sample per stratum


def test_maximin_lhs_is_deterministic_given_seed():
    a = lib.maximin_lhs(10, 3, seed=7, n_candidates=10)
    b = lib.maximin_lhs(10, 3, seed=7, n_candidates=10)
    np.testing.assert_array_equal(a, b)


def test_maximin_lhs_beats_or_matches_a_single_plain_lhs_draw():
    rng = np.random.default_rng(0)
    from scipy.stats import qmc
    plain = qmc.LatinHypercube(d=3, seed=rng).random(10)
    plain_dists = np.linalg.norm(plain[:, None, :] - plain[None, :, :], axis=-1)
    np.fill_diagonal(plain_dists, np.inf)

    best = lib.maximin_lhs(10, 3, seed=1, n_candidates=50)
    best_dists = np.linalg.norm(best[:, None, :] - best[None, :, :], axis=-1)
    np.fill_diagonal(best_dists, np.inf)

    assert best_dists.min() >= plain_dists.min() - 1e-9


# --------------------------------------------------------------------------- build_synthetic_library


def test_library_shapes_and_run_ids():
    grid = sw.small_grid()
    n = 8
    built = lib.build_synthetic_library(grid, n=n, seed=0)
    n_cells = grid.width * grid.height

    assert built.X_raw.shape == (n, 3)
    for stack in (built.max_depth, built.max_velocity, built.arrival_time):
        assert stack.shape == (n, n_cells)
    assert built.run_ids == [f"m5synth_s{i + 1:03d}__synthetic" for i in range(n)]
    assert built.grid is grid


def test_library_inputs_inside_widened_ranges():
    grid = sw.small_grid()
    built = lib.build_synthetic_library(grid, n=8, seed=0)
    widened_volume = lib._widen(*sw.DEFAULT_INPUT_RANGES["water_volume_m3"], "log10")
    widened_width = lib._widen(*sw.DEFAULT_INPUT_RANGES["breach_width_m"], "linear")
    widened_time = lib._widen(*sw.DEFAULT_INPUT_RANGES["failure_time_s"], "linear")

    assert (built.X_raw[:, 0] >= widened_volume[0]).all() and (built.X_raw[:, 0] <= widened_volume[1]).all()
    assert (built.X_raw[:, 1] >= widened_width[0]).all() and (built.X_raw[:, 1] <= widened_width[1]).all()
    assert (built.X_raw[:, 2] >= widened_time[0]).all() and (built.X_raw[:, 2] <= widened_time[1]).all()


def test_widen_log10_never_produces_a_nonpositive_bound():
    lo, hi = lib._widen(1.0e5, 1.0e8, "log10", fraction=0.2)
    assert lo > 0.0
    assert lo < 1.0e5 < 1.0e8 < hi


def test_library_is_deterministic_given_seed():
    grid = sw.small_grid()
    a = lib.build_synthetic_library(grid, n=6, seed=3)
    b = lib.build_synthetic_library(grid, n=6, seed=3)
    np.testing.assert_array_equal(a.X_raw, b.X_raw)
    np.testing.assert_array_equal(a.max_depth, b.max_depth)


def test_library_t_end_covers_the_max_finite_arrival_and_is_hour_aligned():
    grid = sw.small_grid()
    built = lib.build_synthetic_library(grid, n=8, seed=0)
    finite = built.arrival_time[built.arrival_time != FLOAT_NODATA]
    assert finite.max() <= built.t_end_s
    assert built.t_end_s % 3600.0 == 0.0
