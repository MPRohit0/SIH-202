"""Tests for backend.m5_emulator.inputs (docs/m5_specs.md §1, §6 check C)."""

from __future__ import annotations

import numpy as np
import pytest

from backend.m5_emulator.inputs import InputScaler, InputSpec, make_input_specs

RANGES = {
    "water_volume_m3": (1.0e5, 1.0e8),
    "breach_width_m": (20.0, 150.0),
    "failure_time_s": (300.0, 10_800.0),
}


def test_make_input_specs_uses_default_scaling():
    specs = make_input_specs(RANGES)
    scaling = {s.name: s.scaling for s in specs}
    assert scaling == {"water_volume_m3": "log10", "breach_width_m": "linear", "failure_time_s": "linear"}


def test_input_spec_rejects_nonpositive_log10_low():
    with pytest.raises(ValueError):
        InputSpec(name="water_volume_m3", scaling="log10", low=0.0, high=1e8)


def test_input_spec_rejects_high_not_above_low():
    with pytest.raises(ValueError):
        InputSpec(name="breach_width_m", scaling="linear", low=100.0, high=100.0)


def _sample(specs, n=30, seed=0):
    rng = np.random.default_rng(seed)
    cols = []
    for s in specs:
        if s.scaling == "log10":
            cols.append(10 ** rng.uniform(np.log10(s.low), np.log10(s.high), n))
        else:
            cols.append(rng.uniform(s.low, s.high, n))
    return np.column_stack(cols)


def test_scaler_standardises_to_zero_mean_unit_std():
    specs = make_input_specs(RANGES)
    X = _sample(specs)
    scaler = InputScaler.fit(X, specs)
    X_std = scaler.transform(X)
    np.testing.assert_allclose(X_std.mean(axis=0), 0.0, atol=1e-10)
    np.testing.assert_allclose(X_std.std(axis=0), 1.0, atol=1e-10)


def test_scaler_uses_log10_for_volume_only():
    specs = make_input_specs(RANGES)
    X = _sample(specs)
    scaler = InputScaler.fit(X, specs)
    # doubling breach_width (linear) and squaring volume (log10) should move
    # the standardised volume column by a much larger multiple of its scale
    # than a naive linear standardisation would, confirming log-space fit
    x_row = X[0].copy()
    x_row_big_volume = x_row.copy()
    x_row_big_volume[0] = x_row[0] * 10  # one order of magnitude
    std_before = scaler.transform(x_row)
    std_after = scaler.transform(x_row_big_volume)
    delta = std_after[0] - std_before[0]
    expected_delta = 1.0 / scaler.std[0]  # one unit of log10 divided by the fitted std
    assert delta == pytest.approx(expected_delta, rel=1e-8)


def test_scaler_transform_scalar_row_in_scalar_row_out():
    specs = make_input_specs(RANGES)
    X = _sample(specs)
    scaler = InputScaler.fit(X, specs)
    row = X[0]
    out = scaler.transform(row)
    assert out.shape == (3,)


def test_scaler_rejects_zero_variance_input():
    specs = make_input_specs(RANGES)
    X = _sample(specs)
    X[:, 1] = 50.0  # constant breach_width
    with pytest.raises(ValueError):
        InputScaler.fit(X, specs)


def test_scaler_dict_round_trip():
    specs = make_input_specs(RANGES)
    X = _sample(specs)
    scaler = InputScaler.fit(X, specs)
    restored = InputScaler.from_dict(scaler.to_dict())
    np.testing.assert_array_equal(scaler.transform(X), restored.transform(X))
    assert [s.to_dict() for s in restored.specs] == [s.to_dict() for s in specs]


def test_inside_training_box_flags_extrapolation():
    specs = make_input_specs(RANGES)
    X = _sample(specs)
    scaler = InputScaler.fit(X, specs)

    inside_point = np.array([1e6, 80.0, 1800.0])
    assert scaler.inside_training_box(inside_point).all()

    outside_point = np.array([1e9, 80.0, 1800.0])  # volume far above the training range
    flags = scaler.inside_training_box(outside_point)
    assert not flags[0]
    assert flags[1] and flags[2]
