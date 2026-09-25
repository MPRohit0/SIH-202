"""Unit tests for backend.m5_emulator.monte_carlo (docs/m5_specs.md
§5.2-§5.3: sampling distributions, chunk sizing, the per-cell histogram
accumulator, and a full chunked run)."""

from __future__ import annotations

import numpy as np
import pytest

from backend.m5_emulator import monte_carlo as mc
from backend.m5_emulator.inputs import InputSpec


# --------------------------------------------------------------------------- sample_inputs (spec §5.2)


def test_sample_inputs_log_uniform_for_log10_spec():
    spec = InputSpec(name="water_volume_m3", scaling="log10", low=1e5, high=1e8)
    rng = np.random.default_rng(0)
    x = mc.sample_inputs([spec], 5000, rng)
    assert x.shape == (5000, 1)
    assert x.min() >= 1e5 and x.max() <= 1e8
    # log-uniform: log10(x) should be ~uniform, so its mean sits near the midpoint of [5, 8]
    assert 6.0 < np.log10(x[:, 0]).mean() < 7.0


def test_sample_inputs_uniform_for_linear_spec():
    spec = InputSpec(name="breach_width_m", scaling="linear", low=20.0, high=150.0)
    rng = np.random.default_rng(0)
    x = mc.sample_inputs([spec], 5000, rng)
    assert x.min() >= 20.0 and x.max() <= 150.0
    assert abs(x.mean() - 85.0) < 5.0


def test_sample_inputs_respects_ranges_override():
    spec = InputSpec(name="failure_time_s", scaling="linear", low=300.0, high=10_800.0)
    rng = np.random.default_rng(0)
    x = mc.sample_inputs([spec], 1000, rng, ranges={"failure_time_s": (1000.0, 2000.0)})
    assert x.min() >= 1000.0 and x.max() <= 2000.0


def test_sample_inputs_fixed_pins_a_column():
    specs = [InputSpec(name="a", scaling="linear", low=0.0, high=1.0), InputSpec(name="b", scaling="linear", low=0.0, high=1.0)]
    rng = np.random.default_rng(0)
    x = mc.sample_inputs(specs, 100, rng, fixed={"a": 0.5})
    assert np.all(x[:, 0] == 0.5)
    assert x[:, 1].std() > 0  # b still sampled


# --------------------------------------------------------------------------- chunk_size_for (spec §5.3)


def test_chunk_size_is_clamped():
    assert mc.chunk_size_for(0) == 500
    assert mc.chunk_size_for(10**12) == 16  # huge grid -> floor
    assert mc.chunk_size_for(1) == 500       # tiny grid -> ceiling


def test_chunk_size_matches_spec_example():
    # docs/m5_specs.md §5.3: "1M masked cells x 3 maps -> 166 samples per chunk"
    n = mc.chunk_size_for(1_000_000, n_maps=3)
    assert n == 166


# --------------------------------------------------------------------------- CellHistogram


def test_histogram_percentile_recovers_a_known_distribution():
    rng = np.random.default_rng(1)
    n_corridor, n_samples = 3, 20_000
    true_scale = np.array([1.0, 5.0, 10.0])
    values = rng.exponential(scale=true_scale, size=(n_samples, n_corridor))
    hist = mc.CellHistogram(bin_max=true_scale * 8.0)
    chunk = 500
    for start in range(0, n_samples, chunk):
        hist.add(values[start : start + chunk])
    for pct, tol_frac in ((0.5, 0.15), (0.1, 0.25), (0.9, 0.1)):
        expected = -true_scale * np.log(1 - pct)  # exponential quantile
        got = hist.percentile(pct)
        assert np.allclose(got, expected, rtol=tol_frac), (pct, got, expected)


def test_histogram_empty_percentile_is_zero():
    hist = mc.CellHistogram(bin_max=np.array([1.0, 2.0]))
    assert np.all(hist.percentile(0.5) == 0.0)


# --------------------------------------------------------------------------- run_monte_carlo (integration)


def test_run_monte_carlo_rejects_poi_outside_corridor(trained_small):
    with pytest.raises(ValueError, match="outside the trained corridor"):
        mc.run_monte_carlo(trained_small, 50, 0, pois={"corner": 0})


def test_run_monte_carlo_smoke(trained_small, tiny_pois):
    result = mc.run_monte_carlo(trained_small, 200, seed=1, pois=tiny_pois)
    assert result.n_samples == 200
    assert 0 <= result.fraction_inside_box() <= 1.0
    p = result.p_inundation()
    assert p.shape == (trained_small.corridor_mask.sum(),)
    assert np.all((p >= 0) & (p <= 1))
    for name in tiny_pois:
        assert result.poi_depth_samples[name].shape == (200,)
        assert result.poi_velocity_samples[name].shape == (200,)
        # arrival samples only recorded where that sample actually arrived
        assert result.poi_arrival_samples[name].shape[0] <= 200


def test_run_monte_carlo_exceedance_matches_histogram_direction(trained_small, tiny_pois):
    """A cell that's wetter more often should have a higher median in the
    depth histogram than a cell that's wetter less often (sanity check that
    exceedance counting and the histogram are looking at the same samples)."""
    result = mc.run_monte_carlo(trained_small, 300, seed=2, pois=tiny_pois)
    p = result.p_inundation()
    median = result.histograms["max_depth"].percentile(0.5)
    wet_cells = p > 0.5
    dry_cells = p < 0.1
    if wet_cells.any() and dry_cells.any():
        assert median[wet_cells].mean() > median[dry_cells].mean()
