"""Tests for backend.m5_emulator.timeline (docs/handoff_contract.md §5.5).

Uses the tiny fixture from conftest.py, like test_query.py.
"""

from __future__ import annotations

import dataclasses
import json

import numpy as np
import pytest

from backend.m0_api.schemas import validate
from backend.m2_breach.hydrograph import triangular
from backend.m5_emulator import synthetic as sw
from backend.m5_emulator import timeline as tl
from backend.m5_emulator.query import get_flood
from backend.shared.grid import FLOAT_NODATA


def _mid_inputs(emulator):
    return {s.name: (s.low + s.high) / 2.0 for s in emulator.input_scaler.specs}


# --------------------------------------------------------------------------- frame_times


def test_frame_times_default_interval_and_cap(trained_small):
    t_end = trained_small.t_end_s
    arrival_p10 = np.array([0.0, t_end * 0.5, FLOAT_NODATA])
    times = tl.frame_times(arrival_p10, t_end)
    assert times[0] == tl.DEFAULT_INTERVAL_S
    assert all(b > a for a, b in zip(times, times[1:]))  # strictly increasing
    assert times[-1] <= t_end
    assert times[-1] >= t_end * 0.5


def test_frame_times_all_dry_is_one_frame(trained_small):
    t_end = trained_small.t_end_s
    arrival_p10 = np.full(4, FLOAT_NODATA)
    times = tl.frame_times(arrival_p10, t_end)
    assert times == [min(tl.DEFAULT_INTERVAL_S, t_end)]


def test_frame_times_rejects_bad_interval(trained_small):
    with pytest.raises(ValueError):
        tl.frame_times(np.array([0.0]), trained_small.t_end_s, interval_s=0)


# --------------------------------------------------------------------------- frame_arrays


def test_frame_arrays_monotonic_and_reproduces_extent_class_at_t_end(trained_small, tiny_pois):
    inputs = _mid_inputs(trained_small)
    result = get_flood(trained_small, "scenario", inputs, tiny_pois)
    t_end = trained_small.t_end_s

    lit_prev = None
    for t in tl.frame_times(result.p10["arrival_time"], t_end, interval_s=t_end / 20):
        median, high, possible = tl.frame_arrays(
            result.p10["arrival_time"], result.median["arrival_time"], result.p90["arrival_time"],
            result.extent_class, t,
        )
        assert set(np.unique(high)).issubset({0, 2})
        assert set(np.unique(possible)).issubset({0, 1})
        # a cell can be in high or possible, never both, at the same frame
        assert not np.any((high == 2) & (possible == 1))
        lit = (high == 2) | (possible == 1)
        if lit_prev is not None:
            assert np.all(lit[lit_prev])  # once lit, stays lit
        lit_prev = lit

    # at t_end, high + possible reproduce the final extent_class exactly
    median, high, possible = tl.frame_arrays(
        result.p10["arrival_time"], result.median["arrival_time"], result.p90["arrival_time"],
        result.extent_class, t_end,
    )
    reconstructed = np.where(high == 2, 2, np.where(possible == 1, 1, 0)).astype(np.uint8)
    np.testing.assert_array_equal(reconstructed, result.extent_class)


def test_frame_arrays_median_only_shows_arrived_cells(trained_small, tiny_pois):
    inputs = _mid_inputs(trained_small)
    result = get_flood(trained_small, "scenario", inputs, tiny_pois)
    t = trained_small.t_end_s * 0.5
    median, _, _ = tl.frame_arrays(
        result.p10["arrival_time"], result.median["arrival_time"], result.p90["arrival_time"],
        result.extent_class, t,
    )
    valid = result.median["arrival_time"] != FLOAT_NODATA
    should_be_lit = valid & (result.median["arrival_time"] <= t)
    assert np.all((median != FLOAT_NODATA) == should_be_lit)


# --------------------------------------------------------------------------- arrival_profile


def test_arrival_profile_ordering_and_monotone_bounds(trained_small):
    grid = trained_small.grid
    inputs = _mid_inputs(trained_small)
    chainage_m, cell_index = sw.centreline_samples(grid)
    pois = {name: sw.poi_cell_index(grid, c) for name, c in sw.SYNTHETIC_POIS.items()}
    result = get_flood(trained_small, "scenario", inputs, pois)

    rows = tl.arrival_profile(
        result.median["arrival_time"], result.p10["arrival_time"], result.p90["arrival_time"],
        chainage_m, cell_index,
    )
    assert rows, "expected at least one chainage sample to arrive in the synthetic scenario"
    chainages = [r["chainage_m"] for r in rows]
    assert chainages == sorted(chainages)  # centreline samples come out downstream-ordered
    for r in rows:
        if r["arrival_p10_s"] is not None:
            assert r["arrival_p10_s"] <= r["arrival_p50_s"] + 1e-6
        if r["arrival_p90_s"] is not None:
            assert r["arrival_p90_s"] >= r["arrival_p50_s"] - 1e-6
    # the synthetic world floods monotonically downstream (docs/m5_specs.md §7.3):
    # an earlier chainage's median arrival should not be later than a much further one's.
    assert rows[0]["arrival_p50_s"] <= rows[-1]["arrival_p50_s"]


def test_arrival_profile_omits_rows_where_median_never_arrives():
    chainage_m = np.array([0.0, 100.0])
    cell_index = np.array([0, 1])
    median = np.array([[5.0, FLOAT_NODATA]])
    p10 = np.array([[3.0, FLOAT_NODATA]])
    p90 = np.array([[8.0, FLOAT_NODATA]])
    rows = tl.arrival_profile(median, p10, p90, chainage_m, cell_index)
    assert len(rows) == 1
    assert rows[0]["chainage_m"] == 0.0


def test_arrival_profile_null_p10_p90_when_never_arrived():
    chainage_m = np.array([0.0])
    cell_index = np.array([0])
    median = np.array([[5.0]])
    p10 = np.array([[FLOAT_NODATA]])
    p90 = np.array([[FLOAT_NODATA]])
    rows = tl.arrival_profile(median, p10, p90, chainage_m, cell_index)
    assert rows[0]["arrival_p10_s"] is None
    assert rows[0]["arrival_p90_s"] is None


# --------------------------------------------------------------------------- pois_on_profile / hydrograph_series


def test_pois_on_profile_matches_poi_cell_index_chainage(trained_small):
    grid = trained_small.grid
    pois = {name: sw.poi_cell_index(grid, c) for name, c in sw.SYNTHETIC_POIS.items()}
    rows = tl.pois_on_profile(pois, grid, "m5synth_tiny")
    by_name = {r["name"]: r for r in rows}
    for name, chainage in sw.SYNTHETIC_POIS.items():
        assert by_name[name]["poi_id"] == f"m5synth_tiny__poi__{name}"
        # snapped to the nearest cell centre, so within one cell size
        assert abs(by_name[name]["chainage_m"] - chainage) <= grid.cell_size_m


def test_hydrograph_series_round_trips_t_s_and_q_m3s():
    hg = triangular(Q_p=500.0, V=2_000_000.0, T_f=600.0)
    hg = dataclasses.replace(hg, dam_id="synth_dam")
    series = tl.hydrograph_series([hg])
    assert len(series) == 1
    assert series[0]["dam_id"] == "synth_dam"
    assert series[0]["t_offset_s"] == hg.t_offset_s
    assert len(series[0]["points"]) == len(hg.t_s)
    np.testing.assert_allclose([p["t_s"] for p in series[0]["points"]], hg.t_s)
    np.testing.assert_allclose([p["q_m3s"] for p in series[0]["points"]], hg.q_m3s)


# --------------------------------------------------------------------------- write_timeline_inputs (I/O + full contract shape)


def _build_timeline_response(query_dir, interval_s=300.0):
    """Assembles a full Timeline dict the way M0's route would, from what
    write_timeline_inputs wrote -- enough to validate against the schema
    without pulling in the FastAPI layer."""
    data = json.loads((query_dir / "timeline" / "timeline_data.json").read_text())
    import rasterio

    with rasterio.open(query_dir / "timeline" / "arrival_p10.tif") as ds:
        arrival_p10 = ds.read(1)
    frames = []
    for t in tl.frame_times(arrival_p10, data["t_end_s"], interval_s):
        frames.append({
            "t_s": t,
            "median_url": f".../median_t{int(t)}.png",
            "high_url": f".../high_t{int(t)}.png",
            "possible_url": f".../possible_t{int(t)}.png",
            "bounds_latlng": data["bounds_latlng"],
        })
    return {
        "query_id": "q_20260924T101500Z_3fa9c1", "interval_s": interval_s, "t_end_s": data["t_end_s"],
        "frames": frames, "hydrographs": data["hydrographs"], "arrival_profile": data["arrival_profile"],
        "pois_on_profile": data["pois_on_profile"], "caveats": data["caveats"], "provenance": data["provenance"],
    }


@pytest.mark.parametrize("mode", ["scenario", "unknown_breach"])
def test_write_timeline_inputs_produces_a_contract_valid_timeline(trained_small, tmp_path, mode):
    grid = trained_small.grid
    chainage_m, cell_index = sw.centreline_samples(grid)
    pois = {name: sw.poi_cell_index(grid, c) for name, c in sw.SYNTHETIC_POIS.items()}
    inputs = _mid_inputs(trained_small)
    if mode == "scenario":
        result = get_flood(trained_small, "scenario", inputs, pois)
    else:
        result = get_flood(trained_small, "unknown_breach", {}, pois, n_samples=120, seed=1)

    hg = dataclasses.replace(triangular(Q_p=500.0, V=2_000_000.0, T_f=600.0), dam_id="synth_dam")

    query_dir = tmp_path / "queries" / "q_test"
    tl.write_timeline_inputs(
        result, grid, query_dir, hydrographs=[hg], chainage_m=chainage_m, cell_index=cell_index,
        pois=pois, t_end_s=trained_small.t_end_s, contract_version="0.2.0", created_at="2026-09-24T10:15:00Z",
    )

    for name in ("arrival_p10", "arrival_p50", "arrival_p90", "extent_class"):
        assert (query_dir / "timeline" / f"{name}.tif").is_file()

    response = _build_timeline_response(query_dir)
    validate("timeline.schema.json", response)
    assert response["frames"], "expected at least one frame"
    assert any(c["id"] == "arrival_depth_not_joint" for c in response["caveats"])
