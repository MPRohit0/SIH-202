"""Unit tests for backend.m5_emulator.baselines — no GP/PCA involved, just
the regression/blending math each baseline does over synthetic latent or
physical data with a known answer."""

from __future__ import annotations

import numpy as np
import pytest

from backend.m5_emulator.baselines import LinearScoresBaseline, NearestRunBaseline
from backend.m5_emulator.emulator import OUTPUT_KEYS
from backend.shared.grid import FLOAT_NODATA


def test_linear_scores_baseline_recovers_exact_linear_function():
    rng = np.random.default_rng(0)
    X_std = rng.normal(size=(20, 3))
    true_coeffs = np.array([2.0, -1.0, 0.5])
    intercept = 3.0
    scores = (X_std @ true_coeffs + intercept).reshape(-1, 1)  # single component

    baseline = LinearScoresBaseline.fit(X_std, {"max_depth": scores})
    query = np.array([1.0, 2.0, -0.5])
    pred = baseline.predict_latent(query)["max_depth"]
    expected = query @ true_coeffs + intercept
    assert pred[0] == pytest.approx(expected, abs=1e-8)


def test_linear_scores_baseline_handles_multiple_components_and_outputs():
    rng = np.random.default_rng(1)
    X_std = rng.normal(size=(15, 2))
    coeffs_a = np.array([[1.0, 0.0], [0.0, 1.0]])  # 2 components
    scores_depth = X_std @ coeffs_a.T
    scores_arrival = X_std @ np.array([[2.0, 2.0]]).T  # 1 component

    baseline = LinearScoresBaseline.fit(X_std, {"max_depth": scores_depth, "arrival_time": scores_arrival})
    query = np.array([1.0, -1.0])
    pred_depth = baseline.predict_latent(query)["max_depth"]
    pred_arrival = baseline.predict_latent(query)["arrival_time"]
    np.testing.assert_allclose(pred_depth, [1.0, -1.0], atol=1e-8)
    np.testing.assert_allclose(pred_arrival, [0.0], atol=1e-8)


def test_nearest_run_returns_training_map_at_exact_training_point():
    X_std = np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]])
    maps = {name: np.array([[float(i)] * 4 for i in range(3)]) for name in OUTPUT_KEYS}
    baseline = NearestRunBaseline.fit(X_std, maps, t_end_s=1000.0, k=3)
    pred = baseline.predict_corridor(np.array([1.0, 1.0]))
    np.testing.assert_allclose(pred["max_depth"], [1.0, 1.0, 1.0, 1.0])


def test_nearest_run_blends_weighted_mix_between_points():
    # two training points at (-1,0) and (1,0), query at (0,0): equidistant -> average
    X_std = np.array([[-1.0, 0.0], [1.0, 0.0]])
    maps = {name: np.array([[0.0, 0.0], [10.0, 10.0]]) for name in OUTPUT_KEYS}
    baseline = NearestRunBaseline.fit(X_std, maps, t_end_s=1000.0, k=2)
    pred = baseline.predict_corridor(np.array([0.0, 0.0]))
    np.testing.assert_allclose(pred["max_depth"], [5.0, 5.0])


def test_nearest_run_weights_closer_point_more():
    X_std = np.array([[0.0], [1.0], [4.0]])
    maps = {name: np.array([[0.0], [10.0], [100.0]]) for name in OUTPUT_KEYS}
    baseline = NearestRunBaseline.fit(X_std, maps, t_end_s=1000.0, k=3)
    pred = baseline.predict_corridor(np.array([0.0]))
    # weights ~ 1/d^2: d=0 exact match -> returns training run 0 exactly
    assert pred["max_depth"][0] == pytest.approx(0.0)


def test_nearest_run_fills_arrival_before_blending():
    X_std = np.array([[0.0], [1.0]])
    maps = {name: np.array([[1.0, 2.0], [3.0, 4.0]]) for name in OUTPUT_KEYS}
    maps["arrival_time"] = np.array([[FLOAT_NODATA, 50.0], [30.0, FLOAT_NODATA]])
    baseline = NearestRunBaseline.fit(X_std, maps, t_end_s=100.0, k=2)
    # after filling: run0 arrival = [100, 50], run1 = [30, 100]; query at 0.5 -> equal weights -> mean
    pred = baseline.predict_corridor(np.array([0.5]))
    np.testing.assert_allclose(pred["arrival_time"], [65.0, 75.0])
