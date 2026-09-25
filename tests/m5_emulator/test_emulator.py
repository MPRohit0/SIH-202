"""Integration tests for backend.m5_emulator.emulator, trained on the
synthetic library (docs/m5_specs.md §7-§8; not the full A1-A8 acceptance
suite — see backend/m5_emulator/__init__.py for what's out of scope).

Trains once (module-scoped fixture) on N = 30 synthetic runs and reuses the
fitted emulator across tests, since fitting is the expensive part.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.m5_emulator import library as lib
from backend.m5_emulator import synthetic as sw
from backend.m5_emulator.emulator import EmulatorSettings, FloodEmulator, OUTPUT_KEYS
from backend.shared.grid import FLOAT_NODATA

N_TRAIN = 30
SEED = 42


@pytest.fixture(scope="module")
def library():
    return lib.build_synthetic_library(sw.small_grid(), n=N_TRAIN, seed=SEED)


@pytest.fixture(scope="module")
def trained(library):
    from backend.m5_emulator.inputs import make_input_specs

    ranges = {
        name: (float(library.X_raw[:, i].min()), float(library.X_raw[:, i].max()))
        for i, name in enumerate(lib.INPUT_ORDER)
    }
    specs = make_input_specs(ranges)
    return FloodEmulator.fit(
        site_id="m5synth", model="synthetic",
        X_raw=library.X_raw,
        maps={"max_depth": library.max_depth, "max_velocity": library.max_velocity,
              "arrival_time": library.arrival_time},
        grid=library.grid, input_specs=specs, run_ids=library.run_ids,
        t_end_s=library.t_end_s, settings=EmulatorSettings(seed=SEED),
    )


@pytest.fixture(scope="module")
def held_out(library):
    """6 held-out scenarios, inside the training's raw input range (not the
    LHS design points themselves)."""
    rng = np.random.default_rng(999)
    n = 6
    lo, hi = library.X_raw.min(axis=0), library.X_raw.max(axis=0)
    X = np.column_stack([
        10 ** rng.uniform(np.log10(lo[0]), np.log10(hi[0]), n),
        rng.uniform(lo[1], hi[1], n),
        rng.uniform(lo[2], hi[2], n),
    ])
    truths = [
        sw.synthetic_flood_maps(library.grid, water_volume_m3=float(x[0]),
                                 breach_width_m=float(x[1]), failure_time_s=float(x[2]))
        for x in X
    ]
    return X, truths


# --------------------------------------------------------------------------- fit: PCA / reconstruction


def test_variance_explained_reaches_target_or_is_capped(trained):
    n_cap = N_TRAIN - 2
    for oe in trained.outputs.values():
        assert oe.pca.n_components <= n_cap
        if oe.pca.n_components < n_cap:
            assert oe.pca.explained_variance_ratio.sum() >= trained.settings.variance - 1e-9


def test_reconstruction_rmse_is_reported_for_all_outputs(trained):
    for raw_name in OUTPUT_KEYS:
        oe = trained.outputs[raw_name]
        assert oe.reconstruction_rmse_transformed >= 0.0
        assert oe.reconstruction_rmse_physical >= 0.0
        assert oe.physical_rmse_unit
        assert oe.physical_rmse_basis


# --------------------------------------------------------------------------- predict: shape / physical constraints


def test_predict_output_shapes_match_grid(trained, library):
    maps = trained.predict(library.X_raw[0])
    for raw_name in OUTPUT_KEYS:
        assert maps.central[raw_name].shape == library.grid.shape
        assert maps.low[raw_name].shape == library.grid.shape
        assert maps.high[raw_name].shape == library.grid.shape


def test_depth_and_velocity_are_clipped_nonnegative(trained, library):
    maps = trained.predict(library.X_raw[0])
    for raw_name in ("max_depth", "max_velocity"):
        assert (maps.central[raw_name] >= 0.0).all()
        assert (maps.low[raw_name] >= 0.0).all()
        assert (maps.high[raw_name] >= 0.0).all()


def test_band_is_ordered_low_le_central_le_high(trained, library):
    maps = trained.predict(library.X_raw[0])
    for raw_name in OUTPUT_KEYS:
        c, lo, hi = maps.central[raw_name], maps.low[raw_name], maps.high[raw_name]
        assert (lo <= c + 1e-6).all()
        assert (c <= hi + 1e-6).all()


def test_arrival_is_nodata_exactly_where_predicted_dry(trained, library):
    maps = trained.predict(library.X_raw[0])
    wet = maps.central["max_depth"] > trained.settings.arrival_m
    arrival = maps.central["arrival_time"]
    assert np.all(arrival[~wet] == FLOAT_NODATA)
    assert np.all(arrival[wet] != FLOAT_NODATA)
    assert np.all(arrival[wet] >= 0.0)
    assert np.all(arrival[wet] <= trained.t_end_s)


def test_arrival_outside_corridor_is_nodata(trained, library):
    maps = trained.predict(library.X_raw[0])
    outside = ~trained.corridor_mask
    assert np.all(maps.central["arrival_time"][outside] == FLOAT_NODATA)


# --------------------------------------------------------------------------- accuracy on held-out scenarios


def _omega(true_depth, pred_depth, wet_m):
    return (true_depth > wet_m) | (pred_depth > wet_m)


def test_depth_beats_the_training_mean_baseline_on_held_out_scenarios(trained, library, held_out):
    X, truths = held_out
    baseline_map = library.max_depth.mean(axis=0).reshape(library.grid.shape)

    emu_sq, base_sq, count = 0.0, 0.0, 0
    for x, truth in zip(X, truths):
        pred = trained.predict(x).central["max_depth"]
        true_depth = truth.max_depth_m
        omega = _omega(true_depth, pred, trained.settings.wet_m)
        if not omega.any():
            continue
        emu_sq += np.sum((pred[omega] - true_depth[omega]) ** 2)
        base_sq += np.sum((baseline_map[omega] - true_depth[omega]) ** 2)
        count += omega.sum()

    rmse_emulator = np.sqrt(emu_sq / count)
    rmse_baseline = np.sqrt(base_sq / count)
    assert rmse_emulator <= 0.5 * rmse_baseline


def test_extent_f1_at_0_3m_on_held_out_scenarios(trained, held_out):
    X, truths = held_out
    tp = fp = fn = 0
    for x, truth in zip(X, truths):
        pred = trained.predict(x).central["max_depth"]
        pred_wet = pred > 0.3
        true_wet = truth.max_depth_m > 0.3
        tp += int(np.sum(pred_wet & true_wet))
        fp += int(np.sum(pred_wet & ~true_wet))
        fn += int(np.sum(~pred_wet & true_wet))
    f1 = tp / (tp + 0.5 * (fp + fn))
    assert f1 >= 0.8


def test_predicted_depth_rises_with_volume_along_a_sweep(trained, library):
    """Light A3 sanity check (docs/m5_specs.md §8 A3), not the full 95%-of-pairs
    acceptance test."""
    lo, hi = library.X_raw[:, 0].min(), library.X_raw[:, 0].max()
    volumes = np.geomspace(lo * 1.1, hi * 0.9, 5)
    breach_width = float(np.median(library.X_raw[:, 1]))
    failure_time = float(np.median(library.X_raw[:, 2]))

    grid = library.grid
    row = grid.height // 2
    cols = [int(c / grid.cell_size_m) for c in (5_000, 15_000, 30_000)]

    for col in cols:
        depths = [
            trained.predict(np.array([v, breach_width, failure_time])).central["max_depth"][row, col]
            for v in volumes
        ]
        assert depths[0] <= depths[-1]


# --------------------------------------------------------------------------- save / load


def test_save_load_predict_round_trip(trained, library, tmp_path):
    trained.save(tmp_path)
    reloaded = FloodEmulator.load(tmp_path)

    x = library.X_raw[0]
    before = trained.predict(x)
    after = reloaded.predict(x)
    for raw_name in OUTPUT_KEYS:
        np.testing.assert_allclose(before.central[raw_name], after.central[raw_name], atol=1e-4)
        np.testing.assert_allclose(before.low[raw_name], after.low[raw_name], atol=1e-4)
        np.testing.assert_allclose(before.high[raw_name], after.high[raw_name], atol=1e-4)


def test_save_writes_the_contract_file_layout(trained, tmp_path):
    trained.save(tmp_path)
    names = {p.name for p in tmp_path.iterdir()}
    assert "manifest.json" in names
    for short in ("depth", "velocity", "arrival"):
        assert f"pca_{short}.npz" in names
        assert f"gp_{short}.joblib" in names


def test_manifest_has_every_contract_key(trained, tmp_path):
    import json
    trained.save(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    for key in ("site_id", "model", "run_ids", "inputs", "outputs", "kernel",
                "length_scales", "trained_at", "code_version"):
        assert key in manifest
    for short in ("depth", "velocity", "arrival"):
        assert short in manifest["outputs"]
        assert short in manifest["length_scales"]
        for field in ("transform", "n_components", "variance_explained", "reconstruction_rmse"):
            assert field in manifest["outputs"][short]


# --------------------------------------------------------------------------- sensitivity table


def test_sensitivity_table_has_every_output_and_input(trained):
    input_names = [s.name for s in trained.input_scaler.specs]
    table = trained.sensitivity_table()
    assert set(table) == {"depth", "velocity", "arrival"}
    for entry in table.values():
        assert set(entry["relative_sensitivity"]) == set(input_names)
        assert entry["components"]
        for c in entry["components"]:
            assert set(c["length_scales"]) == set(input_names)


def test_water_volume_is_the_most_sensitive_input_for_depth(trained):
    """The synthetic world is built with V_w dominant (`V_EXP = 0.55` >
    `B_EXP`/`T_EXP`), so the fitted depth GPs should reflect that."""
    table = trained.sensitivity_table()
    rel = table["depth"]["relative_sensitivity"]
    assert rel["water_volume_m3"] == max(rel.values())


def test_format_sensitivity_table_is_nonempty_text(trained):
    text = trained.format_sensitivity_table()
    assert isinstance(text, str)
    assert "depth" in text and "velocity" in text and "arrival" in text
    assert "water_volume_m3" in text
