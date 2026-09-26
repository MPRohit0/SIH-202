"""`postprocess.py` tests. `build_run_meta`/`_parse_solver_log` are pure Python (no binary
needed). `compute_summary_rasters`/`postprocess_run` run the real `MeasureTool_linux64`/
`IsoSurface_linux64` against the shipped pilot dam-break particle data (gated on `DSPH_BIN_DIR`,
like every other real-binary check in this project) -- a hand-built 7-cell near-field grid, not
the full synthetic-valley terrain fixture, keeps the run fast: one cell sits exactly at
`x=0.2, y=0` (the same point verified wet-then-draining in `test_measuretool.py`), two sit past
the dam-break box's own `x=4.5` wall (always dry, but still inside the near-field "domain"), and
one is marked outside the near-field domain entirely (`dem_near` nodata)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest

from backend.m0_api import schemas
from backend.m4_sph import postprocess as pp
from backend.m4_sph.settings import SphSettings
from backend.shared.grid import FLOAT_NODATA, CanonicalGrid, write_grid_raster

DSPH_BIN_DIR = os.environ.get("DSPH_BIN_DIR")
PILOT_DATA = Path(DSPH_BIN_DIR).parents[1] / "examples" / "main" / "01_DamBreak" / "CaseDambreakVal2D_out" / "data" if DSPH_BIN_DIR else None
requires_dsph = pytest.mark.skipif(not DSPH_BIN_DIR, reason="set DSPH_BIN_DIR to a DualSPHysics bin/ directory to run")

# Column x's: 0.2 (known wet, matches test_measuretool.py's manual checks), 1.4, 2.6, 3.8 (inside
# the dam-break box, mixed wet/dry over time), 5.0, 6.2 (past the box's x=4.5 wall -- always
# dry), 7.4 (marked outside the near-field domain via dem_near nodata, never sampled at all).
_GRID_KWARGS = dict(site_id="synth", grid_id="nearfield", crs_epsg=32645, origin_x=-0.4, origin_y=0.6, cell_size_m=1.2, width=7, height=1)
_FRAME = {"crs_epsg": 32645, "origin_x": 0.0, "origin_y": 0.0, "units": "m"}


def _make_grid_and_dem():
    grid_near = CanonicalGrid(**_GRID_KWARGS)
    dem_near = np.array([[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, FLOAT_NODATA]], dtype=np.float32)
    return grid_near, dem_near


@requires_dsph
def test_compute_summary_rasters_against_real_pilot_data(tmp_path):
    grid_near, dem_near = _make_grid_and_dem()
    settings = SphSettings(inlet_height_m=2.5, velocity_levels=3, postprocess_row_chunk=10)
    # dp_m=0.04 (not a claim about the real pilot run's actual dp) * the default 0.5 fraction ->
    # an elevation step of 0.02 m, verified below the pilot data's real smoothing length (~0.028 m,
    # from its own dp=0.01 m) -- a coarser step silently breaks MeasureTool's column collapsing
    # (docs/decisions.md, today's session).
    dp_m = 0.04

    result = pp.compute_summary_rasters(PILOT_DATA, grid_near, dem_near, _FRAME, dp_m, settings, tmp_path / "work", DSPH_BIN_DIR)

    for key in ("max_depth", "max_velocity", "arrival_time"):
        assert result[key].shape == (1, 7)

    # column 6 is outside the near-field domain (dem_near nodata) -- untouched, stays nodata
    assert result["max_depth"][0, 6] == FLOAT_NODATA
    assert result["max_velocity"][0, 6] == FLOAT_NODATA
    assert result["arrival_time"][0, 6] == FLOAT_NODATA

    # column 0 (x=0.2) starts inside the initial 2 m water column -> wet from t=0, nonzero velocity
    assert result["max_depth"][0, 0] > 1.0
    assert result["arrival_time"][0, 0] == pytest.approx(0.0, abs=0.02)
    assert result["max_velocity"][0, 0] > 0.01

    # columns 4, 5 (x=5.0, 6.2) are past the dam-break box's own x=4.5 wall -- in-domain, never wet
    for col in (4, 5):
        assert result["max_depth"][0, col] == pytest.approx(0.0, abs=1e-6)
        assert result["max_velocity"][0, col] == pytest.approx(0.0, abs=1e-6)
        assert result["arrival_time"][0, col] == FLOAT_NODATA

    assert result["tau_s"][0] == pytest.approx(0.0)
    assert result["tau_s"][-1] > 1.5  # the pilot run covers ~2 s
    # column 3 (x=3.8, near the box's x=4.5 wall) sees a real run-up wave that comes within
    # 1.5 steps of the 2.5 m ceiling -- depth_capped correctly catches it
    assert result["depth_capped"] is True


@requires_dsph
def test_postprocess_run_writes_the_full_contract_output(tmp_path):
    site_dir = tmp_path / "data" / "synth"
    terrain_dir = site_dir / "terrain"
    terrain_dir.mkdir(parents=True)
    run_dir = site_dir / "runs" / "synth_s001__sph"
    (run_dir / "case").mkdir(parents=True)

    grid_near, dem_near = _make_grid_and_dem()
    grid_near.to_json(terrain_dir / "grid_nearfield.json")
    write_grid_raster(terrain_dir / "dem_nearfield.tif", dem_near, grid_near)
    (terrain_dir / "nearfield_frame.json").write_text(json.dumps(_FRAME), encoding="utf-8")
    # no pois.gpkg -- load_probes returns [] (no site POIs to snap), so timeseries.csv is header-only

    case_meta = {
        "contract_version": "0.2.0", "site_id": "synth", "scenario_id": "synth_s001", "model": "sph",
        "t_start_s": 1000.0, "t_end_s": 1002.0, "dp_m": 0.3,  # realistic near-field dp -- > 0.1 m,
        # so `sph_arrival_below_resolution` should fire below
        "caveats": ["clear_water", "fixed_area_inlet"],
        "has_placeholders": False, "placeholder_fields": [],
        "vram_total_particles": 21001,
    }
    (run_dir / "case" / "case_meta.json").write_text(json.dumps(case_meta), encoding="utf-8")

    # elevation_dz_dp_fraction overridden well below the 0.5 default: case_meta's dp_m=0.3 is
    # realistic for a near-field case, but this test's *particle data* is the pilot dam-break's
    # (real dp=0.01 m, smoothing length ~0.028 m) -- 0.5 * 0.3 = 0.15 m would break MeasureTool's
    # column collapsing against that data, so a smaller fraction (0.05 * 0.3 = 0.015 m) is used
    # here to keep the elevation step valid for this specific test's data, not as a claim about a
    # more realistic case's own step.
    settings = SphSettings(inlet_height_m=2.5, elevation_dz_dp_fraction=0.05, velocity_levels=3, postprocess_row_chunk=10, surface_interval_s=1.0)
    run_meta = pp.postprocess_run(run_dir, terrain_dir, PILOT_DATA, settings, DSPH_BIN_DIR)
    schemas.validate("run_meta.schema.json", run_meta)

    for name in ("max_depth", "max_velocity", "arrival_time"):
        assert (run_dir / "summary_nearfield" / f"{name}.tif").is_file()
    assert (run_dir / "timeseries.csv").read_text(encoding="utf-8").splitlines() == ["poi_id,t_s,depth_m,velocity_ms,wse_m"]
    surface_files = list((run_dir / "surfaces").glob("t*.glb"))
    assert surface_files
    assert all(f.stat().st_size > 0 for f in surface_files)
    # site time = t_start_s (1000) + solver time, matching case_meta's t_start_s
    assert all(int(f.stem[1:]) >= 1000 for f in surface_files)

    written_meta = json.loads((run_dir / "run_meta.json").read_text(encoding="utf-8"))
    assert written_meta == run_meta
    assert run_meta["run_id"] == "synth_s001__sph"
    assert run_meta["status"] == "postprocessed"
    assert run_meta["dp_m"] == 0.3
    assert run_meta["resolution_m"] == 1.2
    assert run_meta["sim_duration_s"] > 1.5
    assert "sph_arrival_below_resolution" in run_meta["caveats"]
    assert "clear_water" in run_meta["caveats"]
    assert run_meta["particle_count"] == 21001  # falls back to the pre-run VRAM estimate
    assert any("particle_count is the pre-run VRAM estimate" in w for w in run_meta["warnings"])


def test_build_run_meta_flags_caveats_and_estimate_fallback():
    case_meta = {
        "scenario_id": "s1", "dp_m": 0.5, "caveats": ["clear_water"],
        "has_placeholders": True, "placeholder_fields": ["dams[0].breach_inputs"],
        "vram_total_particles": 12345,
    }
    grid_near = CanonicalGrid(**_GRID_KWARGS)

    run_meta = pp.build_run_meta(case_meta, grid_near, sim_duration_s=120.0, depth_capped=True)
    schemas.validate("run_meta.schema.json", run_meta)

    assert run_meta["run_id"] == "s1__sph"
    assert run_meta["model"] == "sph"
    assert run_meta["particle_count"] == 12345
    assert run_meta["peak_vram_mb"] is None
    assert run_meta["sim_duration_s"] == 120.0
    assert set(run_meta["caveats"]) == {"clear_water", "sph_arrival_below_resolution", "sph_depth_search_capped"}
    assert run_meta["has_placeholders"] is True
    assert any("no solver log captured" in w for w in run_meta["warnings"])


def test_build_run_meta_uses_real_log_when_available():
    case_meta = {"scenario_id": "s1", "dp_m": 0.02, "caveats": [], "has_placeholders": False, "placeholder_fields": []}
    grid_near = CanonicalGrid(**_GRID_KWARGS)
    log_text = "DualSPHysics5.4 v5.4.355 (01-01-2026)\n...\nTotal particles: 21,001\n"

    run_meta = pp.build_run_meta(case_meta, grid_near, sim_duration_s=1.0, depth_capped=False, log_text=log_text)

    assert run_meta["solver_version"] == "5.4.355"
    assert run_meta["particle_count"] == 21001
    assert "sph_arrival_below_resolution" not in run_meta["caveats"]  # dp_m=0.02 is finer than 0.1 m
    assert not any("pre-run VRAM estimate" in w for w in run_meta["warnings"])
    assert not any("solver_version NOT STATED" in w for w in run_meta["warnings"])
