"""Tests for backend.m2_breach.weir — trapezoidal broad-crested weir discharge."""

from __future__ import annotations

import pytest

from backend.m2_breach.weir import weir_discharge


def test_zero_head_gives_zero_flow():
    assert weir_discharge(b=10.0, z=0.5, H=0.0, C_r=1.7, C_s=1.3) == 0.0


def test_negative_head_gives_zero_flow():
    assert weir_discharge(b=10.0, z=0.5, H=-5.0, C_r=1.7, C_s=1.3) == 0.0


def test_rectangular_only_scales_linearly_with_width():
    q1 = weir_discharge(b=5.0, z=0.0, H=2.0, C_r=1.7, C_s=1.3)
    q2 = weir_discharge(b=10.0, z=0.0, H=2.0, C_r=1.7, C_s=1.3)
    assert q2 == pytest.approx(2 * q1)


def test_rectangular_only_scales_with_head_to_the_1_5():
    q1 = weir_discharge(b=10.0, z=0.0, H=1.0, C_r=1.7, C_s=1.3)
    q2 = weir_discharge(b=10.0, z=0.0, H=4.0, C_r=1.7, C_s=1.3)
    assert q2 == pytest.approx(q1 * 4.0**1.5)


def test_side_slope_adds_a_positive_triangular_term():
    rect_only = weir_discharge(b=10.0, z=0.0, H=2.0, C_r=1.7, C_s=1.3)
    with_sides = weir_discharge(b=10.0, z=0.5, H=2.0, C_r=1.7, C_s=1.3)
    assert with_sides > rect_only
    assert with_sides == pytest.approx(rect_only + 1.3 * 0.5 * 2.0**2.5)


@pytest.mark.parametrize("bad_kwargs", [
    {"b": -1.0, "z": 0.0, "H": 1.0, "C_r": 1.7, "C_s": 1.3},
    {"b": 1.0, "z": -0.1, "H": 1.0, "C_r": 1.7, "C_s": 1.3},
    {"b": 1.0, "z": 0.0, "H": 1.0, "C_r": 0.0, "C_s": 1.3},
    {"b": 1.0, "z": 0.0, "H": 1.0, "C_r": 1.7, "C_s": -1.0},
])
def test_invalid_inputs_raise(bad_kwargs):
    with pytest.raises(ValueError):
        weir_discharge(**bad_kwargs)
