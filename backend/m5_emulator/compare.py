"""M5's half of Compare's "emulator vs physics" / "GP vs linear" sections
(`docs/handoff_contract.md` §5.6, route #15).

`loocv.build_report()` already scores every held-out run's GP prediction and
both A1 baselines (`baselines.py`) and keeps their aggregate medians
(`report["summary"]`, `report["baseline_linear"]`) -- `emulator_vs_physics_metrics`
and `gp_vs_linear_summary` just read those back out in the Compare contract's
shape. What LOOCV does *not* keep is any fold's full-grid prediction array
(discarded per fold, CLAUDE.md rule 13); `fit_and_diff_held_out` recomputes
exactly one fold -- refit on every run but the chosen one, predict it -- to
get a depth-difference raster for that one scenario, on demand rather than
for every fold.

No real Delft3D/SPH run data exists yet (M3/M4 haven't produced any), so
this reads its "held-out physics" truth from the same synthetic test world
every other M5 module uses before real data exists (CLAUDE.md rule 2) --
`write_compare_inputs` records that honestly as a caveat, the way
`loocv.py`'s own report does.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from backend.m5_emulator.emulator import EmulatorSettings, FloodEmulator
from backend.m5_emulator.inputs import InputSpec
from backend.shared.grid import CanonicalGrid, write_grid_raster

SYNTHETIC_WORLD_CAVEAT = {
    "id": "synthetic_world_not_real_physics", "severity": "info",
    "text_key": "caveat_synthetic_world_not_real_physics",
}


def emulator_vs_physics_metrics(report: dict, held_out_run_id: str) -> dict | None:
    """`{iou, depth_rmse_wet_m, arrival_mae_s}` for `held_out_run_id`'s GP
    fold in `report["per_run"]` (`loocv.build_report()`'s shape), or `None`
    if that run wasn't part of this LOOCV report."""
    for row in report["per_run"]:
        if row["run_id"] == held_out_run_id:
            return {
                "iou": row["iou"], "depth_rmse_wet_m": row["depth_rmse_wet_m"],
                "arrival_mae_s": row["arrival_mae_s"],
            }
    return None


def gp_vs_linear_summary(report: dict) -> dict:
    """`{iou_median_gp, iou_median_linear, arrival_mae_s_gp, arrival_mae_s_linear}`,
    the Compare contract's `gp_vs_linear` shape, from `report["summary"]`/
    `report["baseline_linear"]` (`loocv.build_report()`)."""
    return {
        "iou_median_gp": report["summary"]["extent"]["iou_median"],
        "iou_median_linear": report["baseline_linear"]["extent"]["iou_median"],
        "arrival_mae_s_gp": report["summary"]["arrival"]["mae_s_median"],
        "arrival_mae_s_linear": report["baseline_linear"]["arrival"]["mae_s_median"],
    }


def fit_and_diff_held_out(
    X_raw: np.ndarray, maps: dict[str, np.ndarray], grid: CanonicalGrid,
    input_specs: list[InputSpec], run_ids: list[str], t_end_s: float,
    settings: EmulatorSettings, held_out_run_id: str,
) -> np.ndarray:
    """Refits on every run except `held_out_run_id` (same "leave it out"
    rule as `loocv._run_one_fold`, via the public `FloodEmulator` API since
    this needs only the GP prediction, not `loocv.py`'s full metric sweep),
    predicts it, and returns `predicted_max_depth - true_max_depth` (full
    grid, float32) -- positive where the emulator over-predicts depth."""
    if held_out_run_id not in run_ids:
        raise ValueError(f"'{held_out_run_id}' is not one of this library's run_ids")
    i = run_ids.index(held_out_run_id)
    train_idx = [j for j in range(len(run_ids)) if j != i]

    fold_emulator = FloodEmulator.fit(
        site_id="compare_fold", model="synthetic", X_raw=X_raw[train_idx],
        maps={k: v[train_idx] for k, v in maps.items()}, grid=grid, input_specs=input_specs,
        run_ids=[run_ids[j] for j in train_idx], t_end_s=t_end_s, settings=settings,
    )
    predicted = fold_emulator.predict(X_raw[i])
    truth_depth = maps["max_depth"][i].reshape(grid.shape)
    return (predicted.central["max_depth"] - truth_depth).astype(np.float32)


def write_compare_inputs(
    report: dict, X_raw: np.ndarray, maps: dict[str, np.ndarray], grid: CanonicalGrid,
    input_specs: list[InputSpec], run_ids: list[str], t_end_s: float, settings: EmulatorSettings,
    held_out_run_id: str, out_dir: str | Path, *, contract_version: str, created_at: str | None = None,
) -> Path:
    """Writes `<out_dir>/compare/<held_out_run_id>__depth_diff.tif` and
    `.../<held_out_run_id>.json` (metrics + `gp_vs_linear` + everything else
    a Compare response needs except frame URLs, which are M0's job --
    same split as `backend.m5_emulator.timeline.write_timeline_inputs`).
    Returns the `compare/` directory."""
    metrics = emulator_vs_physics_metrics(report, held_out_run_id)
    if metrics is None:
        raise ValueError(f"'{held_out_run_id}' has no per_run entry in this LOOCV report")

    depth_diff = fit_and_diff_held_out(X_raw, maps, grid, input_specs, run_ids, t_end_s, settings, held_out_run_id)

    compare_dir = Path(out_dir) / "compare"
    compare_dir.mkdir(parents=True, exist_ok=True)
    write_grid_raster(compare_dir / f"{held_out_run_id}__depth_diff.tif", depth_diff, grid)

    sidecar = {
        "held_out_run_id": held_out_run_id,
        "metrics": metrics,
        "gp_vs_linear": gp_vs_linear_summary(report),
        "bounds_latlng": grid.bounds_latlng,
        "caveats": [SYNTHETIC_WORLD_CAVEAT],
        "provenance": {
            "method": "gp_emulator", "contract_version": contract_version,
            "created_at": created_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    }
    (compare_dir / f"{held_out_run_id}.json").write_text(json.dumps(sidecar))
    return compare_dir
