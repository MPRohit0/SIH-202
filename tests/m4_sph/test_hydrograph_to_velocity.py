import numpy as np
import pytest

from backend.m4_sph.generator import hydrograph_to_velocity


def test_mass_flux_is_conserved_over_the_window():
    t_s = np.array([0.0, 10.0, 20.0, 30.0, 40.0])
    q_m3s = np.array([0.0, 100.0, 200.0, 100.0, 0.0])
    area_m2 = 50.0

    tau_s, v_ms = hydrograph_to_velocity(t_s, q_m3s, area_m2, t_start_s=5.0, t_end_s=35.0)

    expected_volume = np.trapezoid(np.interp(np.linspace(5, 35, 1000), t_s, q_m3s), np.linspace(5, 35, 1000))
    got_volume = np.trapezoid(v_ms * area_m2, tau_s)
    assert got_volume == pytest.approx(expected_volume, rel=1e-3)


def test_time_is_shifted_to_start_at_zero():
    t_s = np.array([0.0, 10.0, 20.0])
    q_m3s = np.array([0.0, 10.0, 0.0])
    tau_s, v_ms = hydrograph_to_velocity(t_s, q_m3s, area_m2=10.0, t_start_s=5.0, t_end_s=20.0)
    assert tau_s[0] == 0.0
    assert tau_s[-1] == pytest.approx(15.0)
    assert v_ms[0] == pytest.approx(np.interp(5.0, t_s, q_m3s) / 10.0)


def test_default_end_is_the_hydrograph_end():
    t_s = np.array([0.0, 10.0, 20.0])
    q_m3s = np.array([0.0, 10.0, 5.0])
    tau_s, v_ms = hydrograph_to_velocity(t_s, q_m3s, area_m2=1.0, t_start_s=0.0)
    assert tau_s[-1] == pytest.approx(20.0)
    assert v_ms[-1] == pytest.approx(5.0)


@pytest.mark.parametrize("kwargs", [
    {"area_m2": 0.0},
    {"area_m2": -1.0},
])
def test_non_positive_area_raises(kwargs):
    t_s = np.array([0.0, 10.0])
    q_m3s = np.array([0.0, 10.0])
    with pytest.raises(ValueError, match="area_m2"):
        hydrograph_to_velocity(t_s, q_m3s, t_start_s=0.0, **kwargs)


def test_window_outside_hydrograph_range_raises():
    t_s = np.array([0.0, 10.0])
    q_m3s = np.array([0.0, 10.0])
    with pytest.raises(ValueError, match="outside"):
        hydrograph_to_velocity(t_s, q_m3s, area_m2=1.0, t_start_s=0.0, t_end_s=20.0)


def test_end_before_start_raises():
    t_s = np.array([0.0, 10.0])
    q_m3s = np.array([0.0, 10.0])
    with pytest.raises(ValueError, match="t_end_s"):
        hydrograph_to_velocity(t_s, q_m3s, area_m2=1.0, t_start_s=5.0, t_end_s=5.0)


def test_non_increasing_time_raises():
    t_s = np.array([0.0, 10.0, 10.0])
    q_m3s = np.array([0.0, 10.0, 5.0])
    with pytest.raises(ValueError, match="strictly increasing"):
        hydrograph_to_velocity(t_s, q_m3s, area_m2=1.0, t_start_s=0.0)
