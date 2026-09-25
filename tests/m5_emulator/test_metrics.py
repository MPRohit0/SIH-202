"""Unit tests for backend.m5_emulator.metrics — hand-built arrays with known
answers, plus edge cases (empty extent, no shared arrival cells)."""

from __future__ import annotations

import numpy as np
import pytest

from backend.m5_emulator import metrics as m
from backend.shared.grid import FLOAT_NODATA


def test_wet_mask_is_union_of_truth_and_pred():
    truth = np.array([0.0, 0.05, 0.0, 0.0])
    pred = np.array([0.0, 0.0, 0.05, 0.0])
    mask = m.wet_mask(truth, pred, wet_m=0.03)
    np.testing.assert_array_equal(mask, [False, True, True, False])


def test_extent_iou_known_value():
    # truth flooded: {0,1,2}; pred flooded: {1,2,3} -> intersection 2, union 4
    truth = np.array([1.0, 1.0, 1.0, 0.0])
    pred = np.array([0.0, 1.0, 1.0, 1.0])
    assert m.extent_iou(truth, pred, extent_m=0.3) == pytest.approx(0.5)


def test_extent_iou_both_empty_is_one():
    truth = np.zeros(5)
    pred = np.zeros(5)
    assert m.extent_iou(truth, pred, extent_m=0.3) == 1.0


def test_extent_iou_one_empty_is_zero():
    truth = np.array([1.0, 0.0])
    pred = np.array([0.0, 0.0])
    assert m.extent_iou(truth, pred, extent_m=0.3) == 0.0


def test_f1_perfect_match():
    truth = np.array([1.0, 1.0, 0.0, 0.0])
    pred = np.array([1.0, 1.0, 0.0, 0.0])
    assert m.f1_at(truth, pred, threshold_m=0.3) == 1.0


def test_f1_known_value():
    # tp=1 (idx0), fp=1 (idx2), fn=1 (idx1) -> F1 = 2*1/(2*1+1+1) = 0.5
    truth = np.array([1.0, 1.0, 0.0])
    pred = np.array([1.0, 0.0, 1.0])
    assert m.f1_at(truth, pred, threshold_m=0.3) == pytest.approx(0.5)


def test_f1_both_empty_is_one():
    truth = np.zeros(3)
    pred = np.zeros(3)
    assert m.f1_at(truth, pred, threshold_m=0.3) == 1.0


def test_depth_rmse_wet_known_value():
    truth = np.array([1.0, 2.0, 0.0])  # cell 2 dry in both
    pred = np.array([2.0, 2.0, 0.0])
    # Omega = {0, 1}; diffs = [1, 0] -> rmse = sqrt((1+0)/2) = sqrt(0.5)
    assert m.depth_rmse_wet(truth, pred, wet_m=0.03) == pytest.approx(np.sqrt(0.5))


def test_depth_rmse_wet_nan_when_omega_empty():
    truth = np.zeros(3)
    pred = np.zeros(3)
    assert np.isnan(m.depth_rmse_wet(truth, pred, wet_m=0.03))


def test_velocity_mae_uses_depth_derived_omega():
    depth_truth = np.array([1.0, 0.0])
    depth_pred = np.array([1.0, 0.0])
    v_truth = np.array([2.0, 5.0])  # cell 1 dry, must be excluded despite large diff
    v_pred = np.array([3.0, 100.0])
    assert m.velocity_mae(v_truth, v_pred, depth_truth, depth_pred, wet_m=0.03) == pytest.approx(1.0)


def test_arrival_mae_only_over_both_defined():
    truth = np.array([10.0, FLOAT_NODATA, 30.0])
    pred = np.array([15.0, 20.0, FLOAT_NODATA])
    # only cell 0 has both defined -> |15-10| = 5
    assert m.arrival_mae(truth, pred) == pytest.approx(5.0)


def test_arrival_mae_nan_when_no_shared_cell():
    truth = np.array([FLOAT_NODATA, 10.0])
    pred = np.array([5.0, FLOAT_NODATA])
    assert np.isnan(m.arrival_mae(truth, pred))


def test_arrival_rmse_known_value():
    truth = np.array([10.0, 20.0])
    pred = np.array([13.0, 16.0])
    # diffs 3, -4 -> rmse = sqrt((9+16)/2) = sqrt(12.5)
    assert m.arrival_rmse(truth, pred) == pytest.approx(np.sqrt(12.5))


def test_area_error_pct_known_value():
    truth = np.array([1.0, 1.0, 0.0, 0.0])  # 2 flooded cells
    pred = np.array([1.0, 1.0, 1.0, 0.0])   # 3 flooded cells
    # area_true = 2*100=200, area_pred=300 -> (300-200)/200*100 = 50%
    assert m.area_error_pct(truth, pred, extent_m=0.3, cell_area_m2=100.0) == pytest.approx(50.0)


def test_area_error_pct_nan_when_truth_area_zero():
    truth = np.zeros(3)
    pred = np.array([1.0, 0.0, 0.0])
    assert np.isnan(m.area_error_pct(truth, pred, extent_m=0.3, cell_area_m2=100.0))


def test_coverage_90_known_fraction():
    truth = np.array([1.0, 2.0, 3.0, 4.0])
    low = np.array([0.5, 0.5, 0.5, 3.9])
    high = np.array([1.5, 1.5, 3.5, 4.1])  # cell 1: truth 2 not in [0.5,1.5]
    assert m.coverage_90(truth, low, high) == pytest.approx(0.75)


def test_coverage_90_nan_when_empty():
    assert np.isnan(m.coverage_90(np.array([]), np.array([]), np.array([])))


def test_coverage_90_applies_mask():
    truth = np.array([1.0, 100.0])
    low = np.array([0.5, 0.5])
    high = np.array([1.5, 1.5])
    mask = np.array([True, False])
    assert m.coverage_90(truth, low, high, mask=mask) == 1.0


def test_pca_projection_rmse_known_value():
    truth = np.array([1.0, 2.0, 3.0])
    proj = np.array([1.0, 3.0, 3.0])
    assert m.pca_projection_rmse(truth, proj) == pytest.approx(np.sqrt(1 / 3))


def test_terrace_correct_true_when_both_flooded():
    terrace = np.array([True, True, True, False])
    depth_truth = np.array([1.0, 1.0, 0.0, 0.0])
    depth_pred = np.array([0.5, 0.5, 0.5, 0.0])
    assert m.terrace_correct(depth_truth, depth_pred, terrace, extent_m=0.3) is True


def test_terrace_correct_false_when_disagree():
    terrace = np.array([True, True, True])
    depth_truth = np.array([1.0, 1.0, 1.0])  # flooded
    depth_pred = np.array([0.0, 0.0, 0.0])   # dry
    assert m.terrace_correct(depth_truth, depth_pred, terrace, extent_m=0.3) is False


def test_terrace_correct_raises_on_empty_mask():
    with pytest.raises(ValueError):
        m.terrace_correct(np.zeros(3), np.zeros(3), np.zeros(3, dtype=bool), extent_m=0.3)
