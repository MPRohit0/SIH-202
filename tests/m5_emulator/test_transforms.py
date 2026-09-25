"""Tests for backend.m5_emulator.transforms (docs/m5_specs.md §3)."""

from __future__ import annotations

import numpy as np
import pytest

from backend.m5_emulator import transforms as tf
from backend.shared.grid import FLOAT_NODATA


def test_log1p_round_trips_on_nonnegative_values():
    x = np.array([0.0, 0.01, 0.5, 3.2, 100.0])
    z = tf.LOG1P.forward(x)
    np.testing.assert_allclose(tf.LOG1P.inverse(z), x, atol=1e-10)


def test_log1p_inverse_clips_negative_to_zero():
    # a GP mean/band endpoint can dip below log1p(0) = 0 under extrapolation
    z = np.array([-5.0, -0.1, 0.0, 1.0])
    out = tf.LOG1P.inverse(z)
    assert np.all(out >= 0.0)
    assert out[0] == 0.0 and out[1] == 0.0


def test_log1p_forward_treats_negative_input_as_zero():
    assert tf.LOG1P.forward(np.array([-1.0]))[0] == 0.0


def test_identity_is_a_no_op():
    x = np.array([-3.0, 0.0, 42.0])
    np.testing.assert_array_equal(tf.IDENTITY.forward(x), x)
    np.testing.assert_array_equal(tf.IDENTITY.inverse(x), x)


def test_default_transforms_assign_log1p_to_depth_and_velocity_identity_to_arrival():
    assert tf.DEFAULT_TRANSFORMS["max_depth"] is tf.LOG1P
    assert tf.DEFAULT_TRANSFORMS["max_velocity"] is tf.LOG1P
    assert tf.DEFAULT_TRANSFORMS["arrival_time"] is tf.IDENTITY


def test_fill_arrival_replaces_nodata_with_t_end():
    arrival = np.array([10.0, FLOAT_NODATA, 200.0, FLOAT_NODATA])
    filled = tf.fill_arrival(arrival, t_end_s=3600.0)
    np.testing.assert_array_equal(filled, [10.0, 3600.0, 200.0, 3600.0])


def test_fill_arrival_replaces_nan():
    arrival = np.array([5.0, np.nan])
    filled = tf.fill_arrival(arrival, t_end_s=100.0)
    np.testing.assert_array_equal(filled, [5.0, 100.0])


def test_fill_arrival_clips_to_t_end_range():
    arrival = np.array([-5.0, 50.0, 999.0])
    filled = tf.fill_arrival(arrival, t_end_s=100.0)
    np.testing.assert_array_equal(filled, [0.0, 50.0, 100.0])


def test_fill_arrival_rejects_non_positive_t_end():
    with pytest.raises(ValueError):
        tf.fill_arrival(np.array([1.0]), t_end_s=0.0)
    with pytest.raises(ValueError):
        tf.fill_arrival(np.array([1.0]), t_end_s=-5.0)
