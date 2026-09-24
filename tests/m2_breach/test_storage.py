"""Tests for backend.m2_breach.storage — storage curves above the breach invert."""

from __future__ import annotations

import pytest

from backend.m2_breach.storage import (
    STORAGE_FROM_AREA_VOLUME_RELATION_CAVEAT,
    from_area_volume_relation,
    from_surveyed_curve,
)


def test_area_volume_relation_passes_through_calibration_point():
    curve = from_area_volume_relation(V_w=1_000_000.0, h_w=15.0, b=1.5)
    assert curve.volume(15.0) == pytest.approx(1_000_000.0, rel=1e-6)
    assert curve.volume(0.0) == 0.0


def test_area_volume_relation_head_inverts_volume():
    curve = from_area_volume_relation(V_w=1_000_000.0, h_w=15.0, b=1.5)
    for h in (1.0, 5.0, 10.0, 15.0):
        v = curve.volume(h)
        assert curve.head(v) == pytest.approx(h, rel=1e-3)


def test_area_volume_relation_is_monotone_increasing():
    curve = from_area_volume_relation(V_w=1_000_000.0, h_w=15.0, b=1.5)
    hs = [0.0, 3.0, 6.0, 9.0, 12.0, 15.0]
    volumes = [curve.volume(h) for h in hs]
    assert volumes == sorted(volumes)
    assert volumes[0] == 0.0


def test_area_volume_relation_carries_caveat():
    curve = from_area_volume_relation(V_w=1_000_000.0, h_w=15.0, b=1.5)
    assert STORAGE_FROM_AREA_VOLUME_RELATION_CAVEAT in curve.caveats


@pytest.mark.parametrize("kwargs", [
    {"V_w": 0.0, "h_w": 15.0, "b": 1.5},
    {"V_w": 1_000_000.0, "h_w": -1.0, "b": 1.5},
    {"V_w": 1_000_000.0, "h_w": 15.0, "b": 1.0},
    {"V_w": 1_000_000.0, "h_w": 15.0, "b": 0.5},
])
def test_area_volume_relation_invalid_inputs_raise(kwargs):
    with pytest.raises(ValueError):
        from_area_volume_relation(**kwargs)


SURVEYED_POINTS = [[2870.0, 0.0], [2875.0, 1_500_000.0], [2880.0, 4_000_000.0], [2890.0, 12_000_000.0]]


def test_surveyed_curve_shifts_to_invert_elevation():
    curve = from_surveyed_curve(SURVEYED_POINTS, invert_elevation_m=2870.0)
    assert curve.volume(0.0) == 0.0
    assert curve.volume(5.0) == pytest.approx(1_500_000.0)
    assert curve.volume(20.0) == pytest.approx(12_000_000.0)


def test_surveyed_curve_head_inverts_volume():
    curve = from_surveyed_curve(SURVEYED_POINTS, invert_elevation_m=2870.0)
    for h in (2.0, 5.0, 10.0, 18.0):
        v = curve.volume(h)
        assert curve.head(v) == pytest.approx(h, rel=1e-6)


def test_surveyed_curve_no_caveat():
    curve = from_surveyed_curve(SURVEYED_POINTS, invert_elevation_m=2870.0)
    assert curve.caveats == ()


def test_surveyed_curve_invert_outside_range_raises():
    with pytest.raises(ValueError):
        from_surveyed_curve(SURVEYED_POINTS, invert_elevation_m=2900.0)


def test_surveyed_curve_invert_above_first_point():
    """invert_elevation_m need not be the first surveyed point."""
    curve = from_surveyed_curve(SURVEYED_POINTS, invert_elevation_m=2875.0)
    assert curve.volume(0.0) == 0.0
    assert curve.volume(5.0) == pytest.approx(4_000_000.0 - 1_500_000.0)
