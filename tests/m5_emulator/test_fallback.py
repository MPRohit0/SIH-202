"""Tests for backend.m5_emulator.fallback (docs/m5_specs.md's "sites without
a trained emulator fall back to empirical breach + HAND flow routing";
docs/handoff_contract.md §4.6).

All tests run on `synthetic_fallback_terrain(sw.small_grid())` -- the same
40 km synthetic valley `docs/m5_specs.md` §7.1 names for quick tests, with a
HAND/roughness/bed-elevation stand-in built independently of
`synthetic_flood_maps` (see fallback.py's module docstring: the fallback must
be tested against terrain alone, not against the emulator's own "true"
answer).
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.m0_api.schemas import validate
from backend.m5_emulator import fallback as fb
from backend.m5_emulator import synthetic as sw
from backend.shared.grid import FLOAT_NODATA

GRID = sw.small_grid()


@pytest.fixture(scope="module")
def terrain():
    return fb.synthetic_fallback_terrain(GRID)


# --------------------------------------------------------------------------- individual equations


def test_route_discharge_is_constant_with_chainage(terrain):
    q = fb.route_discharge(terrain.chainage_m, 500.0)
    assert q.shape == terrain.chainage_m.shape
    assert np.all(q == 500.0)


def test_route_discharge_rejects_non_positive():
    with pytest.raises(ValueError, match="> 0"):
        fb.route_discharge(np.array([1.0, 2.0]), 0.0)
    with pytest.raises(ValueError, match="> 0"):
        fb.route_discharge(np.array([1.0, 2.0]), -5.0)


def test_channel_top_width_is_widest_on_the_plain(terrain):
    width = fb.channel_top_width_m(terrain.hand_m, terrain.domain_mask, GRID.cell_size_m)
    gorge_col = int(5_000.0 / GRID.cell_size_m)
    plain_col = int(36_000.0 / GRID.cell_size_m)
    assert width[plain_col] > width[gorge_col]
    assert np.all(width > 0)


def test_channel_roughness_matches_uniform_synthetic_n(terrain):
    n = fb.channel_roughness(terrain.roughness_n, terrain.domain_mask, terrain.hand_m)
    np.testing.assert_allclose(n, sw.MANNING_N, rtol=1e-6)  # float32 raster round-trip


def test_bed_slope_is_positive_and_matches_gorge_vs_plain(terrain):
    slope = fb.bed_slope(terrain.bed_elev_m, terrain.chainage_m)
    assert np.all(slope > 0)
    gorge_col = int(5_000.0 / GRID.cell_size_m)
    plain_col = int(36_000.0 / GRID.cell_size_m)
    # gorge slope (2%) is steeper than the plain (0.3%) -- docs/m5_specs.md §7.1
    assert slope[gorge_col] > slope[plain_col]


def test_manning_normal_depth_grows_with_discharge_shrinks_with_slope():
    n = np.array([0.04, 0.04])
    slope = np.array([0.01, 0.01])
    d_small = fb.manning_normal_depth(np.array([1.0, 1.0]), n, slope)
    d_big = fb.manning_normal_depth(np.array([10.0, 10.0]), n, slope)
    assert np.all(d_big > d_small)

    d_gentle = fb.manning_normal_depth(np.array([5.0]), np.array([0.04]), np.array([0.001]))
    d_steep = fb.manning_normal_depth(np.array([5.0]), np.array([0.04]), np.array([0.05]))
    assert d_gentle[0] > d_steep[0]


def test_manning_velocity_matches_hand_computation():
    d, n, s = np.array([1.5]), np.array([0.04]), np.array([0.01])
    v = fb.manning_velocity(d, n, s)
    expected = (1.0 / 0.04) * (1.5 ** (2.0 / 3.0)) * np.sqrt(0.01)
    assert v[0] == pytest.approx(expected)


def test_kinematic_wave_celerity_floors_at_minimum():
    c = fb.kinematic_wave_celerity(np.array([0.0, 1.0, 10.0]))
    assert c[0] == fb.CELERITY_MIN_MS
    np.testing.assert_allclose(c[1:], fb.KINEMATIC_CELERITY_FACTOR * np.array([1.0, 10.0]))


def test_cumulative_arrival_time_is_monotonic_and_offset(terrain):
    celerity = np.full_like(terrain.chainage_m, 2.0)
    arrival = fb.cumulative_arrival_time_s(terrain.chainage_m, celerity)
    assert np.all(np.diff(arrival) >= 0)
    arrival_offset = fb.cumulative_arrival_time_s(terrain.chainage_m, celerity, t_offset_s=100.0)
    np.testing.assert_allclose(arrival_offset - arrival, 100.0)


# --------------------------------------------------------------------------- run_empirical_fallback


def test_run_empirical_fallback_confidence_is_always_low(terrain):
    result = fb.run_empirical_fallback(terrain, peak_discharge_m3s=2_000.0)
    for key in ("overall", "extent", "depth", "arrival", "velocity"):
        assert result.confidence[key]["level"] == "LOW"
        assert result.confidence[key]["reason_key"] == "conf_empirical_fallback"


def test_run_empirical_fallback_floods_the_channel_and_stays_dry_far_off_it(terrain):
    result = fb.run_empirical_fallback(terrain, peak_discharge_m3s=5_000.0)
    centre_row = GRID.height // 2
    col = int(5_000.0 / GRID.cell_size_m)
    assert result.max_depth_m[centre_row, col] > 0.0
    assert result.extent_class[centre_row, col] == 2

    edge_row = 0  # far bank, well outside the gorge's ~25 m half-width
    assert result.max_depth_m[edge_row, col] == pytest.approx(0.0)
    assert result.extent_class[edge_row, col] == 0


def test_run_empirical_fallback_bigger_discharge_floods_more(terrain):
    small = fb.run_empirical_fallback(terrain, peak_discharge_m3s=200.0)
    big = fb.run_empirical_fallback(terrain, peak_discharge_m3s=20_000.0)
    assert (big.extent_class == 2).sum() >= (small.extent_class == 2).sum()
    assert float(big.max_depth_m.max()) > float(small.max_depth_m.max())


def test_run_empirical_fallback_arrival_increases_downstream_along_the_channel(terrain):
    result = fb.run_empirical_fallback(terrain, peak_discharge_m3s=5_000.0)
    centre_row = GRID.height // 2
    near_col = int(5_000.0 / GRID.cell_size_m)
    far_col = int(30_000.0 / GRID.cell_size_m)
    near_arrival = result.arrival_time_s[centre_row, near_col]
    far_arrival = result.arrival_time_s[centre_row, far_col]
    assert near_arrival != FLOAT_NODATA
    assert far_arrival != FLOAT_NODATA
    assert far_arrival > near_arrival


def test_run_empirical_fallback_dry_cells_have_nodata_arrival(terrain):
    result = fb.run_empirical_fallback(terrain, peak_discharge_m3s=5_000.0)
    dry = result.max_depth_m <= fb.ARRIVAL_THRESHOLD_M
    assert np.all(result.arrival_time_s[dry] == FLOAT_NODATA)
    assert np.all(result.max_velocity_ms[dry] == 0.0)


def test_run_empirical_fallback_rejects_non_positive_discharge(terrain):
    with pytest.raises(ValueError, match="> 0"):
        fb.run_empirical_fallback(terrain, peak_discharge_m3s=0.0)


def test_t_offset_shifts_all_arrival_times(terrain):
    base = fb.run_empirical_fallback(terrain, peak_discharge_m3s=5_000.0)
    delayed = fb.run_empirical_fallback(terrain, peak_discharge_m3s=5_000.0, t_offset_s=60.0)
    wet = base.arrival_time_s != FLOAT_NODATA
    np.testing.assert_allclose(delayed.arrival_time_s[wet] - base.arrival_time_s[wet], 60.0, atol=1e-3)


# --------------------------------------------------------------------------- contract response


@pytest.fixture(scope="module")
def pois():
    return {name: sw.poi_cell_index(GRID, chainage) for name, chainage in sw.SYNTHETIC_POIS.items()}


def test_to_contract_response_validates(terrain, pois):
    result = fb.run_empirical_fallback(terrain, peak_discharge_m3s=5_000.0)
    payload = fb.to_contract_response(result, GRID, query_id="q_20260925T000000Z_abc123", pois=pois)
    validate("flood_query_response.schema.json", payload)  # raises ContractViolation on failure
    assert payload["method"] == "empirical_fallback"
    assert payload["confidence"]["overall"]["level"] == "LOW"
    assert any(c["id"] == "empirical_fallback" for c in payload["caveats"])
    assert payload["summary"]["first_arrival"]["name"] is not None


def test_to_contract_response_peak_discharge_is_reported_not_placeholder(terrain, pois):
    result = fb.run_empirical_fallback(terrain, peak_discharge_m3s=1_234.0)
    payload = fb.to_contract_response(result, GRID, query_id="q_20260925T000000Z_def456", pois=pois)
    assert payload["summary"]["peak_discharge_m3s"]["value"] == pytest.approx(1_234.0)
    assert "summary.peak_discharge_m3s" not in payload["placeholder_fields"]
