"""Confidence rule (`docs/handoff_contract.md` §2.3; cutoffs from
`docs/m5_specs.md` §6, all still marked "(tune)" there).

Every `FloodQueryResponse` output (extent, depth, arrival, velocity) gets one
`Confidence`: three named checks -- `validation_skill` (S, from LOOCV),
`query_coverage` (C, query vs. training design) and `spread` (U, P10-P90
width vs. the central value) -- combined **by count**, not a weighted score
(contract §2.3): all three good -> HIGH; one weak -> MODERATE; two or more
weak, `OUTSIDE`, empirical fallback or demo mode -> LOW. `overall()` is the
lowest of the four outputs' levels (contract §5.4).

`docs/m5_specs.md` §6 only defines the spread (U) cutoffs for depth and
arrival explicitly:

- Velocity reuses depth's *relative* cutoffs -- the spec gives no separate
  absolute-unit rule for velocity.
- Extent has no P10-P90 number of its own (it's a threshold on depth, not a
  map with its own band). Its spread here is read off the fraction of the
  flooded area (HIGH + POSSIBLE) that is only POSSIBLE -- a wide POSSIBLE
  fringe means an uncertain boundary. Those two cutoffs are a draft of this
  module, same status as the rest of this file's "(tune)" numbers, not a
  value sourced from the spec.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product

import numpy as np

from backend.m5_emulator.gp import predict_components
from backend.m5_emulator.inputs import InputSpec

Level = str  # "HIGH" | "MODERATE" | "LOW"


@dataclass(frozen=True)
class ConfidenceThresholds:
    """docs/m5_specs.md §6, all marked "(tune)" there."""

    coverage_edge_r: float = 1.0
    coverage_outside_r: float = 2.0
    coverage_mc_inside_high: float = 0.95
    coverage_mc_inside_medium: float = 0.80
    depth_narrow_abs_m: float = 0.5
    depth_narrow_frac: float = 0.5
    depth_medium_abs_m: float = 1.0
    depth_medium_frac: float = 1.0
    arrival_narrow_abs_s: float = 15 * 60.0
    arrival_narrow_frac: float = 0.20
    arrival_medium_abs_s: float = 30 * 60.0
    arrival_medium_frac: float = 0.40
    extent_narrow_possible_frac: float = 0.20
    extent_medium_possible_frac: float = 0.40


DEFAULTS = ConfidenceThresholds()


# ============================================================================
# C -- query coverage
# ============================================================================


def query_coverage_scenario(
    x_std: np.ndarray, x_std_train: np.ndarray, inside_box: bool, t: ConfidenceThresholds = DEFAULTS,
) -> str:
    """C check, scenario mode (docs/m5_specs.md §6): r = distance to the
    nearest training point, divided by the training design's own median
    nearest-neighbour distance, both in standardised input space.
    `inside_box` (whether every raw input is within [spec.low, spec.high])
    forces `OUTSIDE` regardless of r (spec: "any input outside the training
    box" = extrapolation)."""
    if not inside_box:
        return "OUTSIDE"
    dists_to_train = np.linalg.norm(x_std_train - x_std, axis=1)
    nearest = float(dists_to_train.min())
    n = x_std_train.shape[0]
    if n <= 1:
        return "INSIDE"
    pair_d = np.linalg.norm(x_std_train[:, None, :] - x_std_train[None, :, :], axis=-1)
    np.fill_diagonal(pair_d, np.inf)
    median_nn = float(np.median(pair_d.min(axis=1)))
    if median_nn <= 0:
        return "INSIDE"
    r = nearest / median_nn
    if r <= t.coverage_edge_r:
        return "INSIDE"
    if r <= t.coverage_outside_r:
        return "EDGE"
    return "OUTSIDE"


def query_coverage_mc(fraction_inside_box: float, t: ConfidenceThresholds = DEFAULTS) -> str:
    """C check, unknown-breach mode (docs/m5_specs.md §6): "the fraction of
    Monte Carlo samples inside the training box: >= 95% -> High, >= 80% ->
    Medium, else Low"."""
    if fraction_inside_box >= t.coverage_mc_inside_high:
        return "INSIDE"
    if fraction_inside_box >= t.coverage_mc_inside_medium:
        return "EDGE"
    return "OUTSIDE"


# ============================================================================
# U -- prediction spread
# ============================================================================


def _spread_from_width(
    width: float, central: float, narrow_abs: float, narrow_frac: float, medium_abs: float, medium_frac: float,
) -> str:
    central_mag = abs(central)
    if width <= narrow_abs or (central_mag > 0 and width <= narrow_frac * central_mag):
        return "NARROW"
    if width <= medium_abs or (central_mag > 0 and width <= medium_frac * central_mag):
        return "MEDIUM"
    return "WIDE"


def spread_depth_or_velocity(low: float, central: float, high: float, t: ConfidenceThresholds = DEFAULTS) -> str:
    """U check for depth (docs/m5_specs.md §6: "depth width <= 0.5 m or <=
    50% of the mean ... <= 1.0 m / 100% ... wider") and, by the same relative
    cutoffs, velocity (the spec has no separate velocity rule)."""
    return _spread_from_width(
        high - low, central, t.depth_narrow_abs_m, t.depth_narrow_frac, t.depth_medium_abs_m, t.depth_medium_frac,
    )


def spread_arrival(low: float, central: float, high: float, t: ConfidenceThresholds = DEFAULTS) -> str:
    """U check for arrival (docs/m5_specs.md §6: "arrival width <= 15 min or
    <= 20% ... <= 30 min / 40% ... wider")."""
    return _spread_from_width(
        high - low, central, t.arrival_narrow_abs_s, t.arrival_narrow_frac, t.arrival_medium_abs_s, t.arrival_medium_frac,
    )


def spread_extent(possible_fraction_of_flooded: float, t: ConfidenceThresholds = DEFAULTS) -> str:
    """Draft U check for extent -- see module docstring. `nan` (nothing
    flooded at all) reads as NARROW: an empty, unambiguous extent isn't an
    uncertain one."""
    if not np.isfinite(possible_fraction_of_flooded):
        return "NARROW"
    if possible_fraction_of_flooded <= t.extent_narrow_possible_frac:
        return "NARROW"
    if possible_fraction_of_flooded <= t.extent_medium_possible_frac:
        return "MEDIUM"
    return "WIDE"


# ============================================================================
# Combine (contract §2.3) and overall (contract §5.4)
# ============================================================================

_WEAK = {
    "validation_skill": {"FAIR", "POOR", "UNKNOWN"},
    "query_coverage": {"EDGE", "OUTSIDE"},
    "spread": {"MEDIUM", "WIDE"},
}


def combine(
    validation_skill: str, query_coverage: str, spread: str, *,
    has_placeholder_inputs: bool = False, empirical_fallback: bool = False, demo_mode: bool = False,
) -> dict:
    """docs/handoff_contract.md §2.3: "all three good -> HIGH; one weak ->
    MODERATE; two or more weak, OUTSIDE, empirical fallback, or demo mode ->
    LOW." `has_placeholder_inputs` additionally caps at MODERATE
    (docs/m5_specs.md §6: "If any input has status: placeholder, confidence
    is capped at Medium")."""
    components = {"validation_skill": validation_skill, "query_coverage": query_coverage, "spread": spread}
    weak = [k for k, v in components.items() if v in _WEAK[k]]

    if query_coverage == "OUTSIDE":
        level, reason = "LOW", "conf_extrapolation"
    elif empirical_fallback:
        level, reason = "LOW", "conf_empirical_fallback"
    elif demo_mode:
        level, reason = "LOW", "conf_demo_mode"
    elif len(weak) >= 2:
        level, reason = "LOW", f"conf_low_{'_'.join(sorted(weak))}"
    elif len(weak) == 1:
        level, reason = "MODERATE", f"conf_edge_{weak[0]}"
    else:
        level, reason = "HIGH", None

    if has_placeholder_inputs and level == "HIGH":
        level, reason = "MODERATE", "conf_placeholder_inputs"

    return {"level": level, "components": components, "reason_key": reason}


def overall(per_output: dict[str, dict]) -> dict:
    """`overall` = the lowest of the given outputs' levels (contract §5.4:
    "overall confidence = the lowest of the four output levels")."""
    order = {"LOW": 0, "MODERATE": 1, "HIGH": 2}
    worst_name = min(per_output, key=lambda k: order[per_output[k]["level"]])
    worst = per_output[worst_name]
    reason = worst["reason_key"] or f"conf_limited_by_{worst_name}"
    return {"level": worst["level"], "components": worst["components"], "reason_key": reason}


# ============================================================================
# Training-box corners, used by both confidence (S is external) and
# monte_carlo (per-cell histogram bounds) -- a query-independent, generic
# (doesn't assume which corner is "worst") bound on the GP's response over
# the whole trained input box.
# ============================================================================


def training_box_corners(specs: list[InputSpec]) -> np.ndarray:
    """Every corner of the raw-unit training box `[spec.low, spec.high]`
    (2^len(specs) rows) -- used to bound the GP's response over the whole
    trained domain without assuming which direction (e.g. "bigger volume ->
    bigger flood") holds for an arbitrary site."""
    return np.array(list(product(*[(s.low, s.high) for s in specs])))


def per_cell_upper_bound(emulator, raw_name: str, z: float = 4.0, safety: float = 1.5) -> np.ndarray:
    """A conservative, per-corridor-cell upper bound on `raw_name`'s physical
    value anywhere in the trained input box: the GP mean + `z` std at every
    training-box corner, decoded to physical units, maxed over corners, times
    `safety`. Used to size `monte_carlo.py`'s per-cell histogram bins without
    a per-sample pre-pass."""
    corners_std = emulator.input_scaler.transform(training_box_corners(emulator.input_scaler.specs))
    oe = emulator.outputs[raw_name]
    mu, sigma = predict_components(oe.gps, corners_std)
    upper = np.zeros(oe.pca.mean.shape[0])
    for c in range(mu.shape[0]):
        mu_z = oe.pca.decode(mu[c : c + 1])[0]
        sigma_z = oe.pca.decode_std(sigma[c : c + 1])[0]
        phys = oe.transform.inverse(mu_z + z * sigma_z)
        upper = np.maximum(upper, phys)
    return np.maximum(upper * safety, 1e-3)
