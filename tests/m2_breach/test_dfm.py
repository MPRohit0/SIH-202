"""Tests for the DFM fusion (`docs/Equations.md` §4-5)."""

from __future__ import annotations

import pytest

from backend.m2_breach.dfm import (
    breach_width_dfm_updated,
    failure_time_dfm_updated,
    peak_discharge_dfm_2024,
    peak_discharge_dfm_updated,
)
from backend.m2_breach.f8 import breach_width_f8, failure_time_f8
from backend.m2_breach.f16 import peak_discharge_f16
from backend.m2_breach.f95 import breach_width_f95, failure_time_f95
from backend.m2_breach.h14 import peak_discharge_h14
from backend.m2_breach.mclm import failure_time_mclm
from backend.m2_breach.result import MethodResult
from backend.m2_breach.xz9 import xz9_result
from backend.m2_breach.z20 import peak_discharge_z20


def test_peak_discharge_dfm_updated_blocked_by_xz9():
    f16 = peak_discharge_f16(V_w=1e6, h_w=10, h_b=5, W_ave=50, failure_mode="O")
    z20 = peak_discharge_z20(V_w=1e6, h_w=10, h_b=5, h_d=15, dam_type="HD")
    xz9 = xz9_result("peak_discharge_m3s")

    r = peak_discharge_dfm_updated(f16, xz9, z20)
    assert r.is_blocked
    assert r.value is None
    assert "XZ9" in r.reason


def test_peak_discharge_dfm_2024_blocked_by_xz9():
    f16 = peak_discharge_f16(V_w=1e6, h_w=10, h_b=5, W_ave=50, failure_mode="O")
    h14 = peak_discharge_h14(V_w=1e6, h_w=10)
    xz9 = xz9_result("peak_discharge_m3s")

    r = peak_discharge_dfm_2024(f16, h14, xz9)
    assert r.is_blocked


def test_breach_width_dfm_updated_blocked_by_xz9():
    f95 = breach_width_f95(V_w=1e6, h_b=5, failure_mode="O")
    f8 = breach_width_f8(V_w=1e6, h_b=5, failure_mode="O")
    xz9 = xz9_result("breach_width_m")

    r = breach_width_dfm_updated(f95, f8, xz9)
    assert r.is_blocked


def test_failure_time_dfm_updated_equals_weighted_sum_in_hours():
    f95 = failure_time_f95(V_w=1e6, h_b=5)
    f8 = failure_time_f8(V_w=1e6, h_b=5)
    mclm = failure_time_mclm(V_w=1e6, h_w=10)

    r = failure_time_dfm_updated(f95, f8, mclm)
    assert not r.is_blocked
    assert r.unit == "s"

    expected_hours = (-1.0648 * (f95.value / 3600) + 1.5875 * (f8.value / 3600)
                       + 0.6189 * (mclm.value / 3600))
    assert r.value == pytest.approx(expected_hours * 3600)


def test_failure_time_dfm_updated_blocked_when_component_blocked():
    blocked_f95 = MethodResult.blocked("F95", "s", "missing input")
    f8 = failure_time_f8(V_w=1e6, h_b=5)
    mclm = failure_time_mclm(V_w=1e6, h_w=10)

    r = failure_time_dfm_updated(blocked_f95, f8, mclm)
    assert r.is_blocked


def test_negative_dfm_value_is_flagged_not_clipped():
    """B_ave's a coefficient (-0.8220) can push the fused value negative for
    unusual inputs. Verify it's returned as-is (not raised, not clipped to
    zero) with the dfm_nonpositive note (docs/Equations.md §4, §6)."""
    # A tiny F95/F8 (from a very small h_b) combined with a large synthetic
    # XZ9 stand-in makes -0.8220*F95 dominate less relevantly; instead force
    # a negative fusion directly through the private coefficient contract by
    # using a deliberately small F8 and large F95 (a*F95 is the negative term).
    f95 = MethodResult(code="F95", value=1000.0, unit="m")
    f8 = MethodResult(code="F8", value=1.0, unit="m")
    xz9 = MethodResult(code="XZ9", value=1.0, unit="m")

    r = breach_width_dfm_updated(f95, f8, xz9)
    assert not r.is_blocked
    assert r.value < 0
    assert "dfm_nonpositive" in r.branch


def test_peak_discharge_dfm_updated_equals_weighted_sum_when_not_blocked():
    f16 = MethodResult(code="F16", value=100.0, unit="m3s")
    xz9 = MethodResult(code="XZ9", value=50.0, unit="m3s")
    z20 = MethodResult(code="Z20", value=200.0, unit="m3s")

    r = peak_discharge_dfm_updated(f16, xz9, z20)
    assert not r.is_blocked
    assert r.value == pytest.approx(0.3048 * 100 + 0.4804 * 50 + 0.1674 * 200)
