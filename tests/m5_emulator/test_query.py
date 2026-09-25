"""Tests for backend.m5_emulator.query.get_flood() / to_contract_response()
(docs/m5_specs.md §5; docs/handoff_contract.md §5.4).

Correctness tests use the tiny (4,000-cell) fixture from conftest.py for
speed. The timing test uses `synthetic.small_grid()` -- the actual grid
`docs/m5_specs.md` §7.1 names for "quick tests" -- since that's what "one
query under 3 seconds on the synthetic site" means.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from backend.m0_api.schemas import ContractViolation, validate
from backend.m5_emulator import library as lib
from backend.m5_emulator import synthetic as sw
from backend.m5_emulator.emulator import EmulatorSettings, FloodEmulator
from backend.m5_emulator.inputs import make_input_specs
from backend.m5_emulator.query import get_flood, to_contract_response
from backend.shared.grid import FLOAT_NODATA


def _mid_inputs(emulator: FloodEmulator) -> dict:
    return {s.name: (s.low + s.high) / 2.0 for s in emulator.input_scaler.specs}


# --------------------------------------------------------------------------- scenario mode


def test_scenario_mode_needs_every_input(trained_small, tiny_pois):
    with pytest.raises(ValueError, match="missing"):
        get_flood(trained_small, "scenario", {}, tiny_pois)


def test_scenario_mode_matches_predict_band(trained_small, tiny_pois):
    inputs = _mid_inputs(trained_small)
    x_raw = np.array([inputs[s.name] for s in trained_small.input_scaler.specs])
    predicted = trained_small.predict(x_raw)

    result = get_flood(trained_small, "scenario", inputs, tiny_pois)

    assert result.n_samples is None
    np.testing.assert_allclose(result.median["max_depth"], predicted.central["max_depth"])
    np.testing.assert_allclose(result.median["max_velocity"], predicted.central["max_velocity"])
    # scenario mode's own P10/P90 band must straddle the median it was built from
    assert np.all(result.p10["max_depth"] <= result.median["max_depth"] + 1e-6)
    assert np.all(result.p90["max_depth"] >= result.median["max_depth"] - 1e-6)


def test_scenario_mode_p_inundation_is_in_zero_one(trained_small, tiny_pois):
    inputs = _mid_inputs(trained_small)
    result = get_flood(trained_small, "scenario", inputs, tiny_pois)
    finite = np.isfinite(result.p_inundation)
    assert np.all((result.p_inundation[finite] >= 0) & (result.p_inundation[finite] <= 1))
    assert set(np.unique(result.extent_class)).issubset({0, 1, 2})


def test_scenario_mode_bigger_volume_gives_more_inundation(trained_small, tiny_pois):
    """Acceptance-style monotonicity check (docs/m5_specs.md §8 A3), at the
    get_flood level rather than the raw synthetic world."""
    specs = trained_small.input_scaler.specs
    base = _mid_inputs(trained_small)
    vol_spec = next(s for s in specs if s.name == "water_volume_m3")
    small = {**base, "water_volume_m3": vol_spec.low}
    big = {**base, "water_volume_m3": vol_spec.high}

    r_small = get_flood(trained_small, "scenario", small, tiny_pois)
    r_big = get_flood(trained_small, "scenario", big, tiny_pois)
    assert r_big.max_depth_site[0] >= r_small.max_depth_site[0]
    assert (r_big.p_inundation >= 0.3).sum() >= (r_small.p_inundation >= 0.3).sum()


# --------------------------------------------------------------------------- unknown_breach mode


def test_unknown_breach_mode_runs_and_flags_range(trained_small, tiny_pois):
    result = get_flood(trained_small, "unknown_breach", {}, tiny_pois, n_samples=150, seed=3)
    assert result.n_samples == 150
    assert isinstance(result.outside_trained_range, bool)
    for name in tiny_pois:
        assert result.poi_p_inundation[name] >= 0.0


def test_unknown_breach_mode_can_fix_a_subset_of_inputs(trained_small, tiny_pois):
    specs = trained_small.input_scaler.specs
    fixed_name = specs[0].name
    fixed_value = (specs[0].low + specs[0].high) / 2.0
    result = get_flood(trained_small, "unknown_breach", {fixed_name: fixed_value}, tiny_pois, n_samples=100, seed=4)
    value, low, high = result.resolved_inputs[fixed_name]
    assert value == low == high == pytest.approx(fixed_value)


def test_unknown_breach_mode_rejects_bad_mode(trained_small, tiny_pois):
    with pytest.raises(ValueError, match="mode must be one of"):
        get_flood(trained_small, "bogus", {}, tiny_pois)


# --------------------------------------------------------------------------- contract validation


@pytest.mark.parametrize("mode,kwargs", [("scenario", {}), ("unknown_breach", {"n_samples": 100, "seed": 5})])
def test_to_contract_response_validates(trained_small, tiny_pois, mode, kwargs):
    inputs = _mid_inputs(trained_small) if mode == "scenario" else {}
    result = get_flood(trained_small, mode, inputs, tiny_pois, **kwargs)
    payload = to_contract_response(result, trained_small)
    validate("flood_query_response.schema.json", payload)  # raises ContractViolation on failure
    assert payload["mode"] == mode
    assert payload["method"] == "gp_emulator"
    assert payload["flags"]["has_placeholders"] is True  # peak_discharge_m3s is always a placeholder here
    assert "summary.peak_discharge_m3s" in payload["placeholder_fields"]


def test_to_contract_response_first_arrival_is_the_earliest_poi(trained_small, tiny_pois):
    inputs = _mid_inputs(trained_small)
    result = get_flood(trained_small, "scenario", inputs, tiny_pois)
    payload = to_contract_response(result, trained_small)
    arrived = {n: v for n, v in result.poi_arrival.items() if v is not None}
    if arrived:
        earliest = min(arrived.values(), key=lambda t: t[0])[0]
        assert payload["summary"]["first_arrival"]["arrival_s"]["value"] == pytest.approx(earliest)


# --------------------------------------------------------------------------- performance (your ask)


def test_scenario_query_under_3_seconds_on_synthetic_site():
    """"one query under 3 seconds on the synthetic site" -- the synthetic
    site's own quick-test grid (`synthetic.small_grid()`, docs/m5_specs.md
    §7.1), scenario mode (a single GP prediction, no Monte Carlo)."""
    grid = sw.small_grid()
    library = lib.build_synthetic_library(grid, n=30, seed=42)
    ranges = {name: (float(library.X_raw[:, i].min()), float(library.X_raw[:, i].max()))
              for i, name in enumerate(lib.INPUT_ORDER)}
    specs = make_input_specs(ranges)
    emulator = FloodEmulator.fit(
        site_id="m5synth", model="synthetic", X_raw=library.X_raw,
        maps={"max_depth": library.max_depth, "max_velocity": library.max_velocity, "arrival_time": library.arrival_time},
        grid=grid, input_specs=specs, run_ids=library.run_ids, t_end_s=library.t_end_s,
        settings=EmulatorSettings(seed=42),
    )
    pois = {name: sw.poi_cell_index(grid, chainage) for name, chainage in sw.SYNTHETIC_POIS.items()}
    inputs = {s.name: (s.low + s.high) / 2.0 for s in specs}

    t0 = time.perf_counter()
    result = get_flood(emulator, "scenario", inputs, pois)
    to_contract_response(result, emulator)
    elapsed = time.perf_counter() - t0

    assert elapsed < 3.0, f"scenario get_flood + response assembly took {elapsed:.2f}s, want < 3s"


def test_unknown_breach_2000_samples_under_60_seconds_on_synthetic_site():
    """docs/m5_specs.md §8 A7's actual unknown-breach budget ("2,000 samples
    < 60 s") -- a full per-cell histogram over the small grid's corridor is
    real work an analytic single-point scenario query doesn't have to do, so
    this is checked against the spec's own number, not the 3 s ask above
    (which is for a single deterministic scenario prediction)."""
    grid = sw.small_grid()
    library = lib.build_synthetic_library(grid, n=30, seed=42)
    ranges = {name: (float(library.X_raw[:, i].min()), float(library.X_raw[:, i].max()))
              for i, name in enumerate(lib.INPUT_ORDER)}
    specs = make_input_specs(ranges)
    emulator = FloodEmulator.fit(
        site_id="m5synth", model="synthetic", X_raw=library.X_raw,
        maps={"max_depth": library.max_depth, "max_velocity": library.max_velocity, "arrival_time": library.arrival_time},
        grid=grid, input_specs=specs, run_ids=library.run_ids, t_end_s=library.t_end_s,
        settings=EmulatorSettings(seed=42),
    )
    pois = {name: sw.poi_cell_index(grid, chainage) for name, chainage in sw.SYNTHETIC_POIS.items()}

    t0 = time.perf_counter()
    result = get_flood(emulator, "unknown_breach", {}, pois, n_samples=2000, seed=7)
    to_contract_response(result, emulator)
    elapsed = time.perf_counter() - t0

    assert elapsed < 60.0, f"unknown_breach get_flood (2000 samples) took {elapsed:.2f}s, want < 60s"
