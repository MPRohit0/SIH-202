"""Tests for backend.m5_emulator.compare (docs/handoff_contract.md §5.6,
Compare's "emulator vs physics" / "GP vs linear" sections).

Small local fixtures (N=8 on a coarse grid, n_restarts=1), same style as
tests/m5_emulator/test_loocv.py, kept module-local rather than shared so
this file stays fast and independent.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from backend.m0_api.schemas import validate
from backend.m5_emulator import compare, library as lib, loocv
from backend.m5_emulator.emulator import EmulatorSettings, FloodEmulator
from backend.m5_emulator.inputs import make_input_specs
from backend.shared.grid import CanonicalGrid

N_TRAIN = 8
SEED = 11


def _grid() -> CanonicalGrid:
    return CanonicalGrid(
        site_id="m5synth", grid_id="farfield", crs_epsg=32645,
        origin_x=500_000.0, origin_y=3_100_000.0, cell_size_m=250.0, width=160, height=12,
    )


@pytest.fixture(scope="module")
def library():
    return lib.build_synthetic_library(_grid(), n=N_TRAIN, seed=SEED)


@pytest.fixture(scope="module")
def specs(library):
    ranges = {
        name: (float(library.X_raw[:, i].min()), float(library.X_raw[:, i].max()))
        for i, name in enumerate(lib.INPUT_ORDER)
    }
    return make_input_specs(ranges)


@pytest.fixture(scope="module")
def settings():
    return EmulatorSettings(seed=SEED, n_restarts=1)


@pytest.fixture(scope="module")
def maps(library):
    return {"max_depth": library.max_depth, "max_velocity": library.max_velocity, "arrival_time": library.arrival_time}


@pytest.fixture(scope="module")
def result(library, specs, settings, maps):
    return loocv.run_loocv(
        site_id="m5synth", model="synthetic", X_raw=library.X_raw, maps=maps, grid=library.grid,
        input_specs=specs, run_ids=library.run_ids, t_end_s=library.t_end_s, settings=settings, progress=False,
    )


@pytest.fixture(scope="module")
def report(result):
    return loocv.build_report(result)


# --------------------------------------------------------------------------- emulator_vs_physics_metrics


def test_emulator_vs_physics_metrics_matches_the_right_run(library, report):
    held_out = library.run_ids[3]
    row = next(r for r in report["per_run"] if r["run_id"] == held_out)

    metrics = compare.emulator_vs_physics_metrics(report, held_out)

    assert metrics == {"iou": row["iou"], "depth_rmse_wet_m": row["depth_rmse_wet_m"], "arrival_mae_s": row["arrival_mae_s"]}


def test_emulator_vs_physics_metrics_unknown_run_id_is_none(report):
    assert compare.emulator_vs_physics_metrics(report, "no_such_run__delft3d") is None


# --------------------------------------------------------------------------- gp_vs_linear_summary


def test_gp_vs_linear_summary_shape(report):
    summary = compare.gp_vs_linear_summary(report)

    assert set(summary) == {"iou_median_gp", "iou_median_linear", "arrival_mae_s_gp", "arrival_mae_s_linear"}
    assert summary["iou_median_gp"] == report["summary"]["extent"]["iou_median"]
    assert summary["iou_median_linear"] == report["baseline_linear"]["extent"]["iou_median"]
    assert summary["arrival_mae_s_gp"] == report["summary"]["arrival"]["mae_s_median"]
    assert summary["arrival_mae_s_linear"] == report["baseline_linear"]["arrival"]["mae_s_median"]


# --------------------------------------------------------------------------- fit_and_diff_held_out


def test_fit_and_diff_held_out_excludes_the_held_out_run(library, specs, settings, maps, monkeypatch):
    held_out = library.run_ids[2]
    seen_run_ids: list[list[str]] = []
    real_fit = FloodEmulator.fit

    def spy_fit(cls, *args, **kwargs):
        seen_run_ids.append(list(kwargs["run_ids"]))
        return real_fit(*args, **kwargs)

    monkeypatch.setattr(FloodEmulator, "fit", classmethod(spy_fit))

    compare.fit_and_diff_held_out(
        library.X_raw, maps, library.grid, specs, library.run_ids, library.t_end_s, settings, held_out,
    )

    assert len(seen_run_ids) == 1
    assert held_out not in seen_run_ids[0]
    assert len(seen_run_ids[0]) == len(library.run_ids) - 1


def test_fit_and_diff_held_out_shape_and_sign(library, specs, settings, maps):
    held_out = library.run_ids[0]
    diff = compare.fit_and_diff_held_out(
        library.X_raw, maps, library.grid, specs, library.run_ids, library.t_end_s, settings, held_out,
    )
    assert diff.shape == library.grid.shape
    assert diff.dtype == np.float32
    # sanity: refitting without one run and re-predicting it should not diverge wildly
    # from the truth on this smooth synthetic world (loose bound -- not a precision test).
    truth = maps["max_depth"][library.run_ids.index(held_out)]
    assert np.abs(diff).max() <= truth.max() + 5.0


def test_fit_and_diff_held_out_unknown_run_id_raises(library, specs, settings, maps):
    with pytest.raises(ValueError, match="not one of"):
        compare.fit_and_diff_held_out(
            library.X_raw, maps, library.grid, specs, library.run_ids, library.t_end_s, settings, "nope",
        )


# --------------------------------------------------------------------------- write_compare_inputs


def test_write_compare_inputs_writes_tif_and_contract_valid_sidecar(library, specs, settings, maps, report, tmp_path):
    held_out = library.run_ids[4]

    compare_dir = compare.write_compare_inputs(
        report, library.X_raw, maps, library.grid, specs, library.run_ids, library.t_end_s, settings,
        held_out, tmp_path, contract_version="0.2.0", created_at="2026-09-25T00:00:00Z",
    )

    assert (compare_dir / f"{held_out}__depth_diff.tif").is_file()
    sidecar = json.loads((compare_dir / f"{held_out}.json").read_text())
    assert sidecar["held_out_run_id"] == held_out
    assert sidecar["metrics"] == compare.emulator_vs_physics_metrics(report, held_out)
    assert sidecar["gp_vs_linear"] == compare.gp_vs_linear_summary(report)
    assert any(c["id"] == "synthetic_world_not_real_physics" for c in sidecar["caveats"])

    payload = {
        "site_id": "m5synth", "scenario_id": held_out,
        "sph_vs_delft3d": {
            "available": False, "domain": "farfield", "time_window_s": 0,
            "metrics": {}, "probes": [], "layers": [], "run_ids": [],
        },
        "emulator_vs_physics": {
            "available": True, "held_out_run_id": sidecar["held_out_run_id"], "metrics": sidecar["metrics"], "layers": [],
        },
        "gp_vs_linear": sidecar["gp_vs_linear"],
        "when_to_use_key": "when_to_use_sph_delft3d",
        "caveats": sidecar["caveats"],
    }
    validate("compare.schema.json", payload)


def test_write_compare_inputs_unknown_run_id_raises(library, specs, settings, maps, report, tmp_path):
    with pytest.raises(ValueError, match="no per_run entry"):
        compare.write_compare_inputs(
            report, library.X_raw, maps, library.grid, specs, library.run_ids, library.t_end_s, settings,
            "nope", tmp_path, contract_version="0.2.0",
        )
