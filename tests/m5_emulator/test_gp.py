"""Tests for backend.m5_emulator.gp (docs/m5_specs.md §3)."""

from __future__ import annotations

import numpy as np
import pytest

from backend.m5_emulator.gp import (
    LENGTH_SCALE_BOUNDS,
    describe_fitted_gp,
    fit_component_gps,
    predict_components,
)

INPUT_NAMES = ["driver", "irrelevant_a", "irrelevant_b"]


def _training_set(n=25, seed=0):
    rng = np.random.default_rng(seed)
    X_std = rng.uniform(-2.0, 2.0, size=(n, 3))
    # y depends only on the first (standardised) input; the other two are pure noise inputs
    y = np.sin(X_std[:, 0] * 1.2)
    return X_std, y.reshape(-1, 1)  # one "component" column


def test_gp_recovers_a_smooth_single_input_function():
    X_std, scores = _training_set()
    results = fit_component_gps(X_std, scores, INPUT_NAMES, n_restarts=5, seed=0)
    (result,) = results

    X_test = np.linspace(-1.8, 1.8, 20).reshape(-1, 1)
    X_test = np.column_stack([X_test, np.zeros(20), np.zeros(20)])
    mu, sigma = predict_components(results, X_test)
    y_true = np.sin(X_test[:, 0] * 1.2)

    assert np.sqrt(np.mean((mu[:, 0] - y_true) ** 2)) < 0.1
    assert np.all(sigma >= 0)


def test_driving_input_gets_shorter_length_scale_than_irrelevant_inputs():
    X_std, scores = _training_set()
    (result,) = fit_component_gps(X_std, scores, INPUT_NAMES, n_restarts=5, seed=0)
    assert result.length_scales["driver"] < result.length_scales["irrelevant_a"]
    assert result.length_scales["driver"] < result.length_scales["irrelevant_b"]


def test_length_scales_stay_within_configured_bounds():
    X_std, scores = _training_set()
    (result,) = fit_component_gps(X_std, scores, INPUT_NAMES, n_restarts=5, seed=0)
    for name, l in result.length_scales.items():
        assert LENGTH_SCALE_BOUNDS[0] - 1e-6 <= l <= LENGTH_SCALE_BOUNDS[1] + 1e-6


def test_fit_component_gps_rejects_input_name_mismatch():
    X_std, scores = _training_set()
    with pytest.raises(ValueError):
        fit_component_gps(X_std, scores, ["only_one_name"], n_restarts=2, seed=0)


def test_predict_components_shapes_for_multiple_components():
    rng = np.random.default_rng(1)
    X_std = rng.uniform(-1, 1, size=(15, 3))
    scores = rng.normal(size=(15, 4))  # 4 components
    results = fit_component_gps(X_std, scores, INPUT_NAMES, n_restarts=2, seed=1)
    assert len(results) == 4

    X_query = rng.uniform(-1, 1, size=(5, 3))
    mu, sigma = predict_components(results, X_query)
    assert mu.shape == (5, 4)
    assert sigma.shape == (5, 4)


def test_describe_fitted_gp_matches_original_after_refit_same_kernel():
    """`describe_fitted_gp` (used again after loading GPs from disk) must
    read the same length scales / noise level as the ones recorded right
    after fitting."""
    X_std, scores = _training_set()
    (result,) = fit_component_gps(X_std, scores, INPUT_NAMES, n_restarts=5, seed=0)
    redescribed = describe_fitted_gp(result.gp, INPUT_NAMES)
    assert redescribed.length_scales == pytest.approx(result.length_scales)
    assert redescribed.noise_level == pytest.approx(result.noise_level)
