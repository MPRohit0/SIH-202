"""Integration tests for backend.m5_emulator.loocv, on a coarse synthetic
grid (200 m cells, 3200 cells) with N=10 and n_restarts=1 to stay fast
(docs/m5_specs.md §2, §8; loocv.json shape from docs/handoff_contract.md
§4.6)."""

from __future__ import annotations

import json

import numpy as np
import pytest

from backend.m0_api.schemas import validate
from backend.m5_emulator import library as lib
from backend.m5_emulator import loocv
from backend.m5_emulator import synthetic as sw
from backend.m5_emulator.emulator import EmulatorSettings
from backend.m5_emulator.inputs import make_input_specs
from backend.shared.grid import CanonicalGrid

N_TRAIN = 10
SEED = 7


def coarse_grid() -> CanonicalGrid:
    return CanonicalGrid(
        site_id="m5synth", grid_id="farfield", crs_epsg=32645,
        origin_x=500_000.0, origin_y=3_100_000.0, cell_size_m=200.0, width=200, height=16,
    )


def test_four_run_loocv_fits_three_run_training_folds():
    """Four is the library minimum; each held-out fold has three fit rows."""
    grid = sw.small_grid()
    training = lib.build_synthetic_library(grid, n=4, seed=21)
    ranges = {
        name: (float(training.X_raw[:, i].min()), float(training.X_raw[:, i].max()))
        for i, name in enumerate(lib.INPUT_ORDER)
    }
    result = loocv.run_loocv(
        "m5synth", "synthetic", training.X_raw,
        {"max_depth": training.max_depth, "max_velocity": training.max_velocity,
         "arrival_time": training.arrival_time},
        grid, make_input_specs(ranges), training.run_ids, training.t_end_s,
        settings=EmulatorSettings(seed=21, n_restarts=1), progress=False,
    )
    assert len(result.folds) == 4


@pytest.fixture(scope="module")
def library():
    return lib.build_synthetic_library(coarse_grid(), n=N_TRAIN, seed=SEED)


@pytest.fixture(scope="module")
def specs(library):
    ranges = {
        name: (float(library.X_raw[:, i].min()), float(library.X_raw[:, i].max()))
        for i, name in enumerate(lib.INPUT_ORDER)
    }
    return make_input_specs(ranges)


@pytest.fixture(scope="module")
def pois(library):
    return {name: sw.poi_cell_index(library.grid, chainage) for name, chainage in sw.SYNTHETIC_POIS.items()}


@pytest.fixture(scope="module")
def terrace(library):
    return sw.terrace_cells(library.grid)


@pytest.fixture(scope="module")
def result(library, specs, pois, terrace):
    settings = EmulatorSettings(seed=SEED, n_restarts=1)
    return loocv.run_loocv(
        site_id="m5synth", model="synthetic", X_raw=library.X_raw,
        maps={"max_depth": library.max_depth, "max_velocity": library.max_velocity,
              "arrival_time": library.arrival_time},
        grid=library.grid, input_specs=specs, run_ids=library.run_ids, t_end_s=library.t_end_s,
        settings=settings, pois=pois, terrace_mask=terrace, progress=False,
    )


@pytest.fixture(scope="module")
def report(result):
    return loocv.build_report(result)


# --------------------------------------------------------------------------- fold correctness


def test_one_fold_per_run(result, library):
    assert len(result.folds) == N_TRAIN
    assert [f.run_id for f in result.folds] == library.run_ids


def test_held_out_run_excluded_from_its_own_fold(library, specs):
    """Spy on FloodEmulator.fit to confirm the held-out run's X row never
    appears in the training data passed to fit()."""
    from backend.m5_emulator.emulator import FloodEmulator

    seen_X = []
    original_fit = FloodEmulator.fit.__func__

    def spy_fit(cls, *args, **kwargs):
        seen_X.append(np.asarray(kwargs.get("X_raw", args[2] if len(args) > 2 else None)).copy())
        return original_fit(cls, *args, **kwargs)

    FloodEmulator.fit = classmethod(spy_fit)
    try:
        settings = EmulatorSettings(seed=SEED, n_restarts=1)
        loocv.run_loocv(
            site_id="m5synth", model="synthetic", X_raw=library.X_raw,
            maps={"max_depth": library.max_depth, "max_velocity": library.max_velocity,
                  "arrival_time": library.arrival_time},
            grid=library.grid, input_specs=specs, run_ids=library.run_ids, t_end_s=library.t_end_s,
            settings=settings, progress=False,
        )
    finally:
        # classmethod(...), not the bare function: assigning the unwrapped
        # function back left FloodEmulator.fit needing an explicit `cls`
        # argument for every later test in the session (it's no longer bound
        # automatically), which broke any test module that ran after this one.
        FloodEmulator.fit = classmethod(original_fit)

    assert len(seen_X) == N_TRAIN
    for i, X_train in enumerate(seen_X):
        assert X_train.shape[0] == N_TRAIN - 1
        held_out_row = library.X_raw[i]
        assert not any(np.allclose(row, held_out_row) for row in X_train)


def test_per_run_metrics_are_finite_and_reasonable(result):
    for f in result.folds:
        gp = f.metrics["gp"]
        assert 0.0 <= gp["iou"] <= 1.0
        for f1 in gp["f1"].values():
            assert 0.0 <= f1 <= 1.0
        assert gp["depth_rmse_wet_m"] >= 0.0
        assert gp["velocity_mae_ms"] >= 0.0


def test_gp_coverage_90_between_zero_and_one(result):
    for f in result.folds:
        cov = f.metrics["gp"]["coverage_90"]
        assert cov is None or 0.0 <= cov <= 1.0


def test_baselines_have_no_coverage(result):
    for f in result.folds:
        assert f.metrics["baseline_linear"]["coverage_90"] is None
        assert f.metrics["baseline_nearest"]["coverage_90"] is None


# --------------------------------------------------------------------------- report shape / grades


def test_report_matches_contract_schema(report):
    payload = {**report, "model": "delft3d", "events": []}  # model swap: see loocv.py's CLI note
    validate("validation.schema.json", payload)


def test_report_has_baseline_nearest_additive_key(report):
    assert "baseline_nearest" in report
    assert "iou_median" in report["baseline_nearest"]["extent"]


def test_report_json_round_trips(report):
    text = json.dumps(report, default=str)
    round_tripped = json.loads(text)
    assert round_tripped["site_id"] == report["site_id"]
    assert len(round_tripped["per_run"]) == N_TRAIN


def test_grades_derive_from_thresholds(report):
    thresholds = loocv.GradeThresholds()
    f1 = report["summary"]["extent"]["f1_0_3_median"]
    expected_extent_grade = loocv.grade_extent(f1, thresholds)
    assert report["summary"]["extent"]["grade"] == expected_extent_grade
    # depth/velocity have no defined cut-off (docs/decisions.md) -> UNKNOWN
    assert report["summary"]["depth"]["grade"] == "UNKNOWN"
    assert report["summary"]["velocity"]["grade"] == "UNKNOWN"


def test_grade_extent_boundaries():
    t = loocv.GradeThresholds()
    assert loocv.grade_extent(0.9, t) == "GOOD"
    assert loocv.grade_extent(0.75, t) == "FAIR"
    assert loocv.grade_extent(0.5, t) == "POOR"
    assert loocv.grade_extent(float("nan"), t) == "UNKNOWN"


def test_grade_arrival_boundaries():
    t = loocv.GradeThresholds()
    assert loocv.grade_arrival(5.0, 100.0, t) == "GOOD"       # 5%
    assert loocv.grade_arrival(15.0, 100.0, t) == "FAIR"      # 15%
    assert loocv.grade_arrival(30.0, 100.0, t) == "POOR"      # 30%
    assert loocv.grade_arrival(5.0, 0.0, t) == "UNKNOWN"


# --------------------------------------------------------------------------- acceptance tests


def test_acceptance_returns_all_eight_tests(result, report):
    acceptance = loocv.run_acceptance(result, report)
    assert set(acceptance) == {f"A{i}" for i in range(1, 9)}
    for entry in acceptance.values():
        assert entry["status"] in ("PASS", "FAIL", "NOT_EVALUATED")


def test_acceptance_a3_requires_separate_call(result, report):
    acceptance = loocv.run_acceptance(result, report)
    assert acceptance["A3"]["status"] == "NOT_EVALUATED"


def test_acceptance_a4_evaluated_when_terrace_mask_given(result, report):
    acceptance = loocv.run_acceptance(result, report)
    assert acceptance["A4"]["status"] in ("PASS", "FAIL")


def test_acceptance_a6_a8_not_evaluated(result, report):
    acceptance = loocv.run_acceptance(result, report)
    assert acceptance["A6"]["status"] == "NOT_EVALUATED"
    assert acceptance["A8"]["status"] == "NOT_EVALUATED"


def test_check_monotonicity_runs_on_small_grid(library):
    pois = {name: sw.poi_cell_index(library.grid, ch) for name, ch in sw.SYNTHETIC_POIS.items()}
    out = loocv.check_monotonicity(library.grid, sw.DEFAULT_INPUT_RANGES, pois, n_pairs=20, seed=1)
    assert out["status"] in ("PASS", "FAIL")
    assert 0.0 <= out["detail"]["fraction_extent_monotonic"] <= 1.0


# --------------------------------------------------------------------------- charts


def test_charts_written(result, report, tmp_path):
    pytest.importorskip("matplotlib")
    from backend.m5_emulator.validation_plots import write_all_charts

    out_dir = tmp_path / "validation"
    paths = write_all_charts(result, report, out_dir)
    assert paths
    for p in paths:
        assert p.exists()
        assert p.stat().st_size > 0
