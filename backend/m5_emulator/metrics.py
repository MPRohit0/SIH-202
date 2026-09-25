"""LOOCV metrics — one function per metric (`docs/m5_specs.md` §4, §6, §8).

Every function takes flat (n_cells,) arrays of truth and prediction (plus,
for arrival, a `FLOAT_NODATA`-flagged "no arrival" cell) and returns a plain
float, so `loocv.py` can call the same functions for the GP emulator and for
both baselines. Docstrings give the cell set each metric is computed over,
since that's the part most likely to be gotten wrong (Ω vs the full corridor
vs "cells with a real arrival").
"""

from __future__ import annotations

import numpy as np

from backend.shared.grid import FLOAT_NODATA


def wet_mask(depth_truth: np.ndarray, depth_pred: np.ndarray, wet_m: float) -> np.ndarray:
    """Omega (docs/m5_specs.md §4): cells wet (depth > `wet_m`) in truth OR
    prediction. Shared cell set for `depth_rmse_wet`/`velocity_mae`."""
    return (depth_truth > wet_m) | (depth_pred > wet_m)


def extent_iou(depth_truth: np.ndarray, depth_pred: np.ndarray, extent_m: float) -> float:
    """Intersection-over-union of the flooded masks (depth > `extent_m`).
    1.0 if both masks are empty (nothing to disagree on); 0.0 if exactly one
    is empty."""
    truth = depth_truth > extent_m
    pred = depth_pred > extent_m
    union = (truth | pred).sum()
    if union == 0:
        return 1.0
    return float((truth & pred).sum() / union)


def f1_at(depth_truth: np.ndarray, depth_pred: np.ndarray, threshold_m: float) -> float:
    """F1 of the flooded classification (depth > `threshold_m`) against
    truth. 1.0 if both masks are empty."""
    truth = depth_truth > threshold_m
    pred = depth_pred > threshold_m
    tp = int((truth & pred).sum())
    fp = int((pred & ~truth).sum())
    fn = int((truth & ~pred).sum())
    if tp == 0 and fp == 0 and fn == 0:
        return 1.0
    denom = 2 * tp + fp + fn
    if denom == 0:
        return 0.0
    return float(2 * tp / denom)


def depth_rmse_wet(depth_truth: np.ndarray, depth_pred: np.ndarray, wet_m: float) -> float:
    """RMSE [m] over Omega (`wet_mask`). `nan` if Omega is empty (nothing
    wet in either truth or prediction — nothing to score)."""
    mask = wet_mask(depth_truth, depth_pred, wet_m)
    if not mask.any():
        return float("nan")
    diff = depth_pred[mask] - depth_truth[mask]
    return float(np.sqrt(np.mean(diff ** 2)))


def velocity_mae(velocity_truth: np.ndarray, velocity_pred: np.ndarray,
                  depth_truth: np.ndarray, depth_pred: np.ndarray, wet_m: float) -> float:
    """MAE [m/s] over Omega (depth-derived wet mask, docs/m5_specs.md §4 —
    velocity has no wet threshold of its own, it reuses depth's Omega)."""
    mask = wet_mask(depth_truth, depth_pred, wet_m)
    if not mask.any():
        return float("nan")
    diff = velocity_pred[mask] - velocity_truth[mask]
    return float(np.mean(np.abs(diff)))


def _arrival_both_defined(arrival_truth: np.ndarray, arrival_pred: np.ndarray) -> np.ndarray:
    return (arrival_truth != FLOAT_NODATA) & (arrival_pred != FLOAT_NODATA)


def arrival_mae(arrival_truth: np.ndarray, arrival_pred: np.ndarray) -> float:
    """MAE [s] over cells where truth AND prediction both have a real
    arrival (neither is `FLOAT_NODATA`, i.e. "never arrived"). `nan` if no
    such cell exists."""
    mask = _arrival_both_defined(arrival_truth, arrival_pred)
    if not mask.any():
        return float("nan")
    diff = arrival_pred[mask] - arrival_truth[mask]
    return float(np.mean(np.abs(diff)))


def arrival_rmse(arrival_truth: np.ndarray, arrival_pred: np.ndarray) -> float:
    """RMSE [s] over the same cell set as `arrival_mae` (spec §6/A1 state
    the skill check and A1 baseline comparison in RMSE, not MAE)."""
    mask = _arrival_both_defined(arrival_truth, arrival_pred)
    if not mask.any():
        return float("nan")
    diff = arrival_pred[mask] - arrival_truth[mask]
    return float(np.sqrt(np.mean(diff ** 2)))


def area_error_pct(depth_truth: np.ndarray, depth_pred: np.ndarray, extent_m: float,
                    cell_area_m2: float) -> float:
    """Signed 100*(A_pred - A_true)/A_true at `extent_m` [%]. `nan` if the
    true flooded area is zero (nothing to compare a percentage against)."""
    area_true = float((depth_truth > extent_m).sum()) * cell_area_m2
    area_pred = float((depth_pred > extent_m).sum()) * cell_area_m2
    if area_true == 0:
        return float("nan")
    return float(100.0 * (area_pred - area_true) / area_true)


def coverage_90(truth: np.ndarray, low: np.ndarray, high: np.ndarray, mask: np.ndarray | None = None) -> float:
    """Fraction of `truth` inside `[low, high]` (the nominal 90% band,
    P5-P95, spec §5.1), optionally restricted to `mask`. `nan` if the cell
    set is empty. Used for depth/velocity (over Omega) and arrival (over
    cells where both truth and the band are defined)."""
    if mask is not None:
        truth, low, high = truth[mask], low[mask], high[mask]
    if truth.size == 0:
        return float("nan")
    inside = (truth >= low) & (truth <= high)
    return float(np.mean(inside))


def pca_projection_rmse(truth_physical: np.ndarray, projected_physical: np.ndarray,
                         mask: np.ndarray | None = None) -> float:
    """RMSE [physical units] of projecting held-out truth onto a PCA basis
    it was NOT part of fitting, then decoding back — the honest per-fold A5
    number (as opposed to the in-sample reconstruction RMSE `pca.py` reports
    at fit time)."""
    if mask is not None:
        truth_physical, projected_physical = truth_physical[mask], projected_physical[mask]
    if truth_physical.size == 0:
        return float("nan")
    diff = projected_physical - truth_physical
    return float(np.sqrt(np.mean(diff ** 2)))


def terrace_correct(depth_truth: np.ndarray, depth_pred: np.ndarray, terrace_mask: np.ndarray,
                     extent_m: float) -> bool:
    """A4 (docs/m5_specs.md §8): classify the terrace flooded/dry by
    majority vote of its cells at `extent_m`, for truth and prediction
    separately, and report whether the two classes agree."""
    if not terrace_mask.any():
        raise ValueError("terrace_mask has no cells")
    truth_flooded = float((depth_truth[terrace_mask] > extent_m).mean()) >= 0.5
    pred_flooded = float((depth_pred[terrace_mask] > extent_m).mean()) >= 0.5
    return truth_flooded == pred_flooded
