"""Tests for backend.m5_emulator.pca (docs/m5_specs.md §3)."""

from __future__ import annotations

import numpy as np
import pytest

from backend.m5_emulator.pca import corridor_mask, fit_pca


# --------------------------------------------------------------------------- corridor_mask


def test_corridor_mask_is_union_of_wet_cells_across_runs():
    shape = (5, 5)
    depth_stack = np.zeros((3, 25), dtype=np.float32)
    depth_stack[0, 0] = 0.1   # run 0 wets cell (0,0)
    depth_stack[1, 24] = 0.5  # run 1 wets cell (4,4)
    mask = corridor_mask(depth_stack, shape, wet_m=0.03, buffer_cells=0)
    assert mask[0, 0] and mask[4, 4]
    assert mask.sum() == 2


def test_corridor_mask_ignores_cells_below_wet_threshold():
    shape = (3, 3)
    depth_stack = np.full((2, 9), 0.02, dtype=np.float32)  # below wet_m everywhere
    mask = corridor_mask(depth_stack, shape, wet_m=0.03, buffer_cells=0)
    assert not mask.any()


def test_corridor_mask_buffer_dilates_by_n_cells():
    shape = (7, 7)
    depth_stack = np.zeros((1, 49), dtype=np.float32)
    depth_stack[0, 3 * 7 + 3] = 1.0  # centre cell (3,3) wet
    mask = corridor_mask(depth_stack, shape, wet_m=0.03, buffer_cells=2)
    # a 4-connected dilation by 2 reaches Manhattan distance 2 from centre
    assert mask[3, 3]
    assert mask[3, 5] and mask[5, 3]  # exactly 2 cells away, axis-aligned
    assert not mask[5, 5]  # Manhattan distance 4, outside a 2-cell 4-connected dilation
    assert not mask[0, 0]


# --------------------------------------------------------------------------- fit_pca


def _known_rank_matrix(n=10, n_cells=40, rank=3, seed=0):
    rng = np.random.default_rng(seed)
    scores = rng.normal(size=(n, rank))
    basis = rng.normal(size=(rank, n_cells))
    return scores @ basis  # exact rank `rank` (before centring)


def test_fit_pca_reaches_target_variance():
    Z = _known_rank_matrix(n=10, n_cells=40, rank=3)
    basis = fit_pca(Z, variance=0.99, max_components=8)
    assert basis.explained_variance_ratio.sum() >= 0.99 - 1e-9
    assert basis.n_components <= 8


def test_fit_pca_caps_at_max_components():
    Z = _known_rank_matrix(n=10, n_cells=40, rank=8)  # needs many components for 99%
    basis = fit_pca(Z, variance=0.99, max_components=3)
    assert basis.n_components == 3


def test_fit_pca_picks_smallest_d_star():
    # rank-2 signal: 2 components should already reach ~100% variance
    Z = _known_rank_matrix(n=10, n_cells=40, rank=2)
    basis = fit_pca(Z, variance=0.99, max_components=8)
    assert basis.n_components <= 2


def test_full_rank_decode_is_exact():
    rng = np.random.default_rng(1)
    Z = rng.normal(size=(6, 15))
    basis = fit_pca(Z, variance=0.999999, max_components=5)  # N-1 = 5 max useful components
    scores = basis.encode(Z)
    recon = basis.decode(scores)
    # components are stored float32 (docs/m5_specs.md §3), so exactness is bounded
    # by float32 precision (~1e-7 relative), not float64 machine epsilon
    np.testing.assert_allclose(recon, Z, atol=1e-6, rtol=1e-5)


def test_reconstruction_rmse_is_reported_and_shrinks_with_more_components():
    Z = _known_rank_matrix(n=12, n_cells=50, rank=5, seed=2)
    basis_few = fit_pca(Z, variance=0.5, max_components=1)
    basis_many = fit_pca(Z, variance=0.999999, max_components=10)
    rmse_few = basis_few.reconstruction_rmse(Z)
    rmse_many = basis_many.reconstruction_rmse(Z)
    assert rmse_many < rmse_few
    assert rmse_many < 1e-6  # near-exact with enough components for an exact-rank matrix


def test_decode_std_matches_brute_force_variance_propagation():
    rng = np.random.default_rng(3)
    Z = rng.normal(size=(8, 20))
    basis = fit_pca(Z, variance=0.99, max_components=5)
    sigma = rng.uniform(0.1, 2.0, size=(4, basis.n_components))

    got = basis.decode_std(sigma)

    W = basis.components.astype(np.float64)  # (n_components, n_cells)
    expected = np.sqrt((sigma ** 2) @ (W ** 2))
    np.testing.assert_allclose(got, expected)


def test_fit_pca_rejects_too_few_runs():
    with pytest.raises(ValueError):
        fit_pca(np.zeros((1, 10)))


def test_components_stored_as_float32():
    Z = _known_rank_matrix(n=8, n_cells=20, rank=3)
    basis = fit_pca(Z, variance=0.99, max_components=5)
    assert basis.components.dtype == np.float32
