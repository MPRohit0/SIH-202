"""Tests for backend.m5_emulator.synthetic — the fake-physics test world
(docs/m5_specs.md §7). Checks the qualitative behaviour listed in §7.2/§7.3,
not exact numeric values (there is no "truth" to match; the function IS the
truth for this test world)."""

from __future__ import annotations

import numpy as np
import pytest
import rasterio

from backend.m5_emulator import synthetic as sw
from backend.shared.grid import FLOAT_NODATA

REFERENCE = dict(water_volume_m3=1.0e7, breach_width_m=50.0, failure_time_s=1800.0)


def _maps(grid, **overrides):
    params = {**REFERENCE, **overrides}
    return sw.synthetic_flood_maps(grid, **params)


def _col_for_chainage(grid, chainage_m: float) -> int:
    return int(chainage_m / grid.cell_size_m)


def _row_for_offset(grid, offset_m: float) -> int:
    return int(grid.height / 2 + offset_m / grid.cell_size_m)


# --------------------------------------------------------------------------- grids


def test_small_grid_is_much_smaller_than_large_grid():
    small, large = sw.small_grid(), sw.large_grid()
    assert small.width * small.height == 500_000
    assert large.width * large.height == 2_000_000
    assert small.width * small.height < large.width * large.height


def test_both_grids_cover_the_same_physical_valley():
    small, large = sw.small_grid(), sw.large_grid()
    assert small.width * small.cell_size_m == large.width * large.cell_size_m == sw.VALLEY_LENGTH_M
    assert small.height * small.cell_size_m == large.height * large.cell_size_m


# --------------------------------------------------------------------------- basic shape / output contract


def test_output_shapes_and_dtypes():
    g = sw.small_grid()
    maps = _maps(g)
    for arr in (maps.max_depth_m, maps.max_velocity_ms, maps.arrival_time_s):
        assert arr.shape == g.shape
        assert arr.dtype == np.float32


def test_dry_cells_are_zero_not_nodata():
    g = sw.small_grid()
    maps = _maps(g)
    dry = maps.max_depth_m <= sw.ARRIVAL_THRESHOLD_M
    assert dry.any()
    assert np.all(maps.max_depth_m[dry] >= 0.0)
    assert np.all(maps.max_velocity_ms[dry] >= 0.0)


def test_arrival_is_nodata_where_never_wet():
    g = sw.small_grid()
    maps = _maps(g)
    dry = maps.max_depth_m <= sw.ARRIVAL_THRESHOLD_M
    assert np.all(maps.arrival_time_s[dry] == FLOAT_NODATA)
    wet = ~dry
    assert np.all(maps.arrival_time_s[wet] != FLOAT_NODATA)
    assert np.all(maps.arrival_time_s[wet] >= 0.0)


def test_far_bank_is_dry():
    """Cells far from the centreline, on the fan, should be dry (no flood
    stretches to the grid edge for a moderate reference scenario)."""
    g = sw.small_grid()
    maps = _maps(g)
    col = _col_for_chainage(g, 38_000)
    row = _row_for_offset(g, 1_580)  # near the top edge of the grid
    assert maps.max_depth_m[row, col] == 0.0


def test_rejects_non_positive_inputs():
    g = sw.small_grid()
    with pytest.raises(ValueError):
        _maps(g, water_volume_m3=0.0)
    with pytest.raises(ValueError):
        _maps(g, breach_width_m=-1.0)
    with pytest.raises(ValueError):
        _maps(g, failure_time_s=0.0)


# --------------------------------------------------------------------------- determinism (§7.3)


def test_deterministic_without_noise():
    g = sw.small_grid()
    a = _maps(g)
    b = _maps(g)
    np.testing.assert_array_equal(a.max_depth_m, b.max_depth_m)
    np.testing.assert_array_equal(a.max_velocity_ms, b.max_velocity_ms)
    np.testing.assert_array_equal(a.arrival_time_s, b.arrival_time_s)


def test_deterministic_given_seed_with_noise():
    g = sw.small_grid()
    a = _maps(g, noise_std_m=0.05, seed=7)
    b = _maps(g, noise_std_m=0.05, seed=7)
    np.testing.assert_array_equal(a.max_depth_m, b.max_depth_m)
    # a different seed should (almost certainly) perturb the result differently
    c = _maps(g, noise_std_m=0.05, seed=8)
    assert not np.array_equal(a.max_depth_m, c.max_depth_m)


def test_zero_noise_std_matches_noiseless_baseline():
    g = sw.small_grid()
    baseline = _maps(g)
    zero_noise = _maps(g, noise_std_m=0.0, seed=123)
    np.testing.assert_array_equal(baseline.max_depth_m, zero_noise.max_depth_m)


# --------------------------------------------------------------------------- monotonic response (§7.2, acceptance test A3)


@pytest.mark.parametrize("chainage_m", [5_000, 10_000, 22_000, 35_000])
def test_depth_and_velocity_rise_with_volume(chainage_m):
    g = sw.small_grid()
    col = _col_for_chainage(g, chainage_m)
    row = g.height // 2
    volumes = [1e6, 1e7, 1e8]
    depths = [_maps(g, water_volume_m3=v).max_depth_m[row, col] for v in volumes]
    velocities = [_maps(g, water_volume_m3=v).max_velocity_ms[row, col] for v in volumes]
    assert depths[0] <= depths[1] <= depths[2]
    assert depths[0] < depths[2]
    assert velocities[0] <= velocities[1] <= velocities[2]


def test_arrival_falls_with_volume():
    g = sw.small_grid()
    col = _col_for_chainage(g, 30_000)
    row = g.height // 2
    volumes = [1e6, 1e7, 1e8]
    arrivals = [_maps(g, water_volume_m3=v).arrival_time_s[row, col] for v in volumes]
    assert all(a > 0 for a in arrivals)
    assert arrivals[0] >= arrivals[1] >= arrivals[2]
    assert arrivals[0] > arrivals[2]


def test_arrival_increases_with_distance_downstream():
    g = sw.small_grid()
    row = g.height // 2
    maps = _maps(g)
    chainages = [2_000, 10_000, 20_000, 35_000]
    arrivals = [maps.arrival_time_s[row, _col_for_chainage(g, s)] for s in chainages]
    assert all(a != FLOAT_NODATA for a in arrivals)
    assert arrivals == sorted(arrivals)


def test_arrival_rises_with_failure_time_near_dam():
    """Near the dam, a longer failure time delays arrival (docs/m5_specs.md §7.2)."""
    g = sw.small_grid()
    col = _col_for_chainage(g, 3_000)
    row = g.height // 2
    fast = _maps(g, failure_time_s=300.0).arrival_time_s[row, col]
    slow = _maps(g, failure_time_s=7200.0).arrival_time_s[row, col]
    assert slow > fast


def test_velocity_higher_in_gorge_than_on_plain():
    g = sw.small_grid()
    row = g.height // 2
    maps = _maps(g)
    v_gorge = maps.max_velocity_ms[row, _col_for_chainage(g, 5_000)]
    v_plain = maps.max_velocity_ms[row, _col_for_chainage(g, 38_000)]
    assert v_gorge > v_plain


# --------------------------------------------------------------------------- constriction backup (§7.2)


def test_depth_spikes_at_constriction():
    g = sw.small_grid()
    row = g.height // 2
    maps = _maps(g)
    d_constriction = maps.max_depth_m[row, _col_for_chainage(g, sw.CONSTRICTION_CENTER_M)]
    d_upstream = maps.max_depth_m[row, _col_for_chainage(g, 4_000)]
    d_downstream_gorge = maps.max_depth_m[row, _col_for_chainage(g, 14_000)]
    assert d_constriction > d_upstream
    assert d_constriction > d_downstream_gorge


# --------------------------------------------------------------------------- extent capped in gorge, wide on plain (§7.2)


def _wet_half_width_m(g, maps, chainage_m: float) -> float:
    col = _col_for_chainage(g, chainage_m)
    wet_rows = np.where(maps.extent_mask()[:, col])[0]
    if wet_rows.size == 0:
        return 0.0
    centre = g.height / 2.0
    return float(max(abs(r - centre) for r in wet_rows) * g.cell_size_m)


def test_gorge_extent_barely_changes_with_volume_but_plain_extent_grows_a_lot():
    g = sw.small_grid()
    small = _maps(g, water_volume_m3=1e6)
    big = _maps(g, water_volume_m3=1e8)

    gorge_small = _wet_half_width_m(g, small, 5_000)
    gorge_big = _wet_half_width_m(g, big, 5_000)
    plain_small = _wet_half_width_m(g, plain_maps := small, 38_000)
    plain_big = _wet_half_width_m(g, big, 38_000)

    gorge_growth = gorge_big - gorge_small
    plain_growth = plain_big - plain_small
    assert plain_growth > gorge_growth
    assert gorge_growth < 50.0  # capped by the valley walls (well under one grid cell x a few)


# --------------------------------------------------------------------------- terrace threshold (§7.2, acceptance test A4)


def _terrace_cell(g):
    col = _col_for_chainage(g, sw.TERRACE_CENTER_M)
    row = _row_for_offset(g, (sw.TERRACE_INNER_OFFSET_M + sw.TERRACE_OUTER_OFFSET_M) / 2.0)
    return row, col


def test_terrace_stays_dry_below_the_overtopping_flow():
    g = sw.small_grid()
    row, col = _terrace_cell(g)
    maps = _maps(g, water_volume_m3=1e6)  # well below the reference flow used in the docstring example
    assert maps.max_depth_m[row, col] <= sw.EXTENT_THRESHOLD_M


def test_terrace_floods_quickly_once_overtopped():
    g = sw.small_grid()
    row, col = _terrace_cell(g)
    maps = _maps(g, water_volume_m3=1e8)
    depth = maps.max_depth_m[row, col]
    assert depth > sw.EXTENT_THRESHOLD_M
    assert sw.TERRACE_MIN_DEPTH_M - 0.05 <= depth <= sw.TERRACE_MAX_DEPTH_M + 0.05


def test_terrace_classification_is_monotonic_in_volume():
    g = sw.small_grid()
    row, col = _terrace_cell(g)
    depths = [_maps(g, water_volume_m3=v).max_depth_m[row, col] for v in (1e5, 1e6, 1e7, 1e8)]
    assert depths == sorted(depths)


# --------------------------------------------------------------------------- GeoTIFF writer, M3 schema (docs/handoff_contract.md §4.4)


def test_write_synthetic_run_produces_m3_schema_geotiffs(tmp_path):
    g = sw.small_grid()
    paths = sw.write_synthetic_run(tmp_path, g, **REFERENCE)

    assert set(paths) == {"max_depth", "max_velocity", "arrival_time"}
    assert paths["max_depth"] == tmp_path / "summary" / "max_depth.tif"
    assert paths["max_velocity"] == tmp_path / "summary" / "max_velocity.tif"
    assert paths["arrival_time"] == tmp_path / "summary" / "arrival_time.tif"

    expected = sw.synthetic_flood_maps(g, **REFERENCE)
    for key, arr in (("max_depth", expected.max_depth_m),
                      ("max_velocity", expected.max_velocity_ms),
                      ("arrival_time", expected.arrival_time_s)):
        with rasterio.open(paths[key]) as ds:
            assert ds.crs.to_epsg() == g.crs_epsg
            assert ds.transform == g.transform
            assert (ds.height, ds.width) == g.shape
            assert ds.nodata == FLOAT_NODATA
            np.testing.assert_array_equal(ds.read(1), arr)
