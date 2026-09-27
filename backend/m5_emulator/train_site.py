"""Train a real-site Delft3D emulator from the M5 run cache and run LOOCV."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rasterio

from backend.m0_api import schemas
from backend.m5_emulator.emulator import EmulatorSettings, FloodEmulator
from backend.m5_emulator.inputs import DEFAULT_SCALING, InputSpec
from backend.m5_emulator.loocv import build_report, run_acceptance, run_loocv
from backend.m5_emulator.run_cache import load_run_cache
from backend.shared.grid import CanonicalGrid
from backend.shared.probes import load_probes


def train_site(site_id: str, data_dir: str | Path, *, demo: bool = False) -> dict:
    """Fit the emulator from postprocessed runs; never synthesize solver maps."""
    root = Path(data_dir)
    design = json.loads((root / site_id / "design" / "scenario_design.json").read_text())
    records = load_run_cache(root, site_id)["runs"]
    design_by_scenario = {}
    for scenario in design["scenarios"]:
        design_by_scenario[scenario["scenario_id"]] = scenario
        if "__s" in scenario["scenario_id"]:
            design_by_scenario[scenario["scenario_id"].replace("__s", "__demo_s", 1)] = scenario
    records = [r for r in records if r["scenario_id"] in design_by_scenario]
    if len(records) < 4:
        raise ValueError(f"M5 training and LOOCV require at least 4 postprocessed design runs; found {len(records)}")

    ranged = {item["name"]: item for item in design["inputs"]}
    names = [name for name in DEFAULT_SCALING if name in ranged]
    if not names:
        raise ValueError("M5 design has no varying inputs")
    specs = [InputSpec(name=name, scaling=DEFAULT_SCALING[name],
                       low=float(ranged[name]["low"]), high=float(ranged[name]["high"]))
             for name in names]
    params_by_run = [design_by_scenario[r["scenario_id"]]["params"] for r in records]
    X_raw = np.asarray([[float(p[name]) for name in names] for p in params_by_run], dtype=float)
    if np.any(np.ptp(X_raw, axis=0) <= 0):
        constant = [names[i] for i, span in enumerate(np.ptp(X_raw, axis=0)) if span <= 0]
        raise ValueError(f"M5 cannot fit constant training inputs: {constant}")

    grid = CanonicalGrid.from_json(root / site_id / "terrain" / "grid.json")
    map_arrays: dict[str, list[np.ndarray]] = {"max_depth": [], "max_velocity": [], "arrival_time": []}
    t_end_values = []
    run_ids = []
    for record in records:
        site_root = root / site_id
        meta = json.loads((site_root / record["run_meta"]).read_text())
        t_end_values.append(float(meta["sim_duration_s"]))
        run_ids.append(record["run_id"])
        for name in map_arrays:
            with rasterio.open(site_root / record["summary"][name]) as dataset:
                array = dataset.read(1).astype(np.float32)
            if array.shape != grid.shape:
                raise ValueError(f"{record['run_id']} {name} shape {array.shape} does not match canonical grid {grid.shape}")
            map_arrays[name].append(array.reshape(-1))
    if len(set(t_end_values)) != 1:
        raise ValueError(f"M5 training runs have different simulation durations: {sorted(set(t_end_values))}")
    maps = {name: np.stack(arrays) for name, arrays in map_arrays.items()}

    pois = {}
    for probe in load_probes(root / site_id / "terrain"):
        row = int(np.floor((grid.origin_y - probe.y_m) / grid.cell_size_m))
        col = int(np.floor((probe.x_m - grid.origin_x) / grid.cell_size_m))
        if 0 <= row < grid.height and 0 <= col < grid.width:
            pois[probe.name] = row * grid.width + col

    settings = EmulatorSettings(n_restarts=1 if demo else EmulatorSettings().n_restarts)
    result = run_loocv(site_id, "delft3d", X_raw, maps, grid, specs, run_ids,
                       t_end_values[0], settings=settings, pois=pois)
    report = build_report(result)
    report["acceptance"] = run_acceptance(result, report)
    report["events"] = []
    schemas.validate("validation.schema.json", report)

    emulator = FloodEmulator.fit(site_id, "delft3d", X_raw, maps, grid, specs, run_ids,
                                 t_end_values[0], settings=settings)
    output = root / site_id / "emulator" / "delft3d"
    emulator.save(output)
    report_path = output / "validation" / "loocv.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update({"demo_mode": bool(demo), "display_label": "DEMO MODE" if demo else None,
                     "confidence": "LOW" if demo else None,
                     "fixed_inputs": {"water_volume_m3": float(params_by_run[0]["water_volume_m3"])}}
                    )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {"manifest": manifest_path, "validation": report_path, "n_runs": len(run_ids)}
