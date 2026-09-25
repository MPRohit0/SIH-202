"""Unit tests for backend.m5_emulator.confidence (docs/handoff_contract.md
§2.3 combine rule; docs/m5_specs.md §6 check cutoffs)."""

from __future__ import annotations

import numpy as np
import pytest

from backend.m5_emulator import confidence as conf


# --------------------------------------------------------------------------- combine (contract §2.3)


def test_combine_all_good_is_high():
    c = conf.combine("GOOD", "INSIDE", "NARROW")
    assert c["level"] == "HIGH"
    assert c["reason_key"] is None


def test_combine_one_weak_is_moderate():
    c = conf.combine("FAIR", "INSIDE", "NARROW")
    assert c["level"] == "MODERATE"
    c = conf.combine("GOOD", "EDGE", "NARROW")
    assert c["level"] == "MODERATE"
    c = conf.combine("GOOD", "INSIDE", "MEDIUM")
    assert c["level"] == "MODERATE"


def test_combine_two_weak_is_low():
    c = conf.combine("POOR", "EDGE", "NARROW")
    assert c["level"] == "LOW"


def test_combine_outside_forces_low_even_if_others_good():
    c = conf.combine("GOOD", "OUTSIDE", "NARROW")
    assert c["level"] == "LOW"
    assert c["reason_key"] == "conf_extrapolation"


def test_combine_empirical_fallback_and_demo_mode_force_low():
    assert conf.combine("GOOD", "INSIDE", "NARROW", empirical_fallback=True)["level"] == "LOW"
    assert conf.combine("GOOD", "INSIDE", "NARROW", demo_mode=True)["level"] == "LOW"


def test_combine_placeholder_caps_high_at_moderate():
    c = conf.combine("GOOD", "INSIDE", "NARROW", has_placeholder_inputs=True)
    assert c["level"] == "MODERATE"
    assert c["reason_key"] == "conf_placeholder_inputs"
    # doesn't raise an already-low level
    c = conf.combine("POOR", "OUTSIDE", "WIDE", has_placeholder_inputs=True)
    assert c["level"] == "LOW"


def test_overall_is_the_worst_output():
    per_output = {
        "extent": conf.combine("GOOD", "INSIDE", "NARROW"),
        "depth": conf.combine("POOR", "EDGE", "WIDE"),
        "arrival": conf.combine("GOOD", "INSIDE", "NARROW"),
        "velocity": conf.combine("GOOD", "INSIDE", "NARROW"),
    }
    o = conf.overall(per_output)
    assert o["level"] == "LOW"


# --------------------------------------------------------------------------- C: query coverage


def test_query_coverage_scenario_inside_design():
    x_std_train = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
    assert conf.query_coverage_scenario(np.array([0.5, 0.5]), x_std_train, inside_box=True) == "INSIDE"


def test_query_coverage_scenario_outside_box_overrides_r():
    x_std_train = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
    # even a point right at a training location is OUTSIDE if the raw input left the training box
    assert conf.query_coverage_scenario(np.array([0.0, 0.0]), x_std_train, inside_box=False) == "OUTSIDE"


def test_query_coverage_scenario_far_point_is_outside():
    x_std_train = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
    assert conf.query_coverage_scenario(np.array([50.0, 50.0]), x_std_train, inside_box=True) == "OUTSIDE"


@pytest.mark.parametrize("frac,expected", [(1.0, "INSIDE"), (0.95, "INSIDE"), (0.85, "EDGE"), (0.5, "OUTSIDE")])
def test_query_coverage_mc(frac, expected):
    assert conf.query_coverage_mc(frac) == expected


# --------------------------------------------------------------------------- U: spread


def test_spread_depth_narrow_medium_wide():
    assert conf.spread_depth_or_velocity(1.9, 2.0, 2.1) == "NARROW"   # width 0.2 m
    assert conf.spread_depth_or_velocity(1.5, 2.0, 2.9) == "MEDIUM"   # width 1.4 m, 70% of central
    assert conf.spread_depth_or_velocity(0.0, 2.0, 6.0) == "WIDE"     # width 6 m, 300% of central


def test_spread_arrival_narrow_medium_wide():
    assert conf.spread_arrival(590.0, 600.0, 610.0) == "NARROW"     # width 20 s
    assert conf.spread_arrival(0.0, 600.0, 1200.0) == "MEDIUM"      # width 1200 s: > 15 min abs, <= 30 min abs
    assert conf.spread_arrival(0.0, 600.0, 5000.0) == "WIDE"        # width 5000 s: > 30 min abs and > 40% of central


def test_spread_extent_uses_possible_fraction():
    assert conf.spread_extent(float("nan")) == "NARROW"  # nothing flooded
    assert conf.spread_extent(0.1) == "NARROW"
    assert conf.spread_extent(0.3) == "MEDIUM"
    assert conf.spread_extent(0.9) == "WIDE"


# --------------------------------------------------------------------------- per_cell_upper_bound


def test_per_cell_upper_bound_is_positive_and_finite(trained_small):
    upper = conf.per_cell_upper_bound(trained_small, "max_depth")
    assert np.all(np.isfinite(upper))
    assert np.all(upper > 0)
