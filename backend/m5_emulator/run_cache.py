"""Small durable index of contract-valid runs available to M5.

The expensive raster products stay in ``runs/<run_id>/summary``; this cache
records their input vector and paths so M5 can discover completed runs without
scanning incomplete campaign folders.
"""
from __future__ import annotations

import json
from pathlib import Path


def register_run(data_dir: str | Path, site_id: str, run_id: str,
                 params: dict, run_meta: dict) -> Path:
    if run_meta.get("status") != "postprocessed":
        raise ValueError("only postprocessed runs may enter the M5 cache")
    run_dir = Path(data_dir) / site_id / "runs" / run_id
    required = [run_dir / "summary" / f"{name}.tif"
                for name in ("max_depth", "max_velocity", "arrival_time")]
    missing = [str(p) for p in required if not p.is_file()]
    if missing:
        raise FileNotFoundError("M5 cache requires summary rasters: " + ", ".join(missing))
    cache_dir = Path(data_dir) / site_id / "emulator" / "delft3d"
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / "run_cache.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        payload = {"site_id": site_id, "model": "delft3d", "runs": []}
    record = {"run_id": run_id, "scenario_id": run_meta["scenario_id"],
              "params": params, "run_meta": f"runs/{run_id}/run_meta.json",
              "summary": {name: f"runs/{run_id}/summary/{name}.tif"
                          for name in ("max_depth", "max_velocity", "arrival_time")}}
    payload["runs"] = [r for r in payload["runs"] if r["run_id"] != run_id] + [record]
    payload["runs"].sort(key=lambda r: r["run_id"])
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)
    return path


def load_run_cache(data_dir: str | Path, site_id: str) -> dict:
    """Load the M5 run index and discard any entries whose required files vanished."""
    root = Path(data_dir) / site_id
    path = root / "emulator" / "delft3d" / "run_cache.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    available = []
    for record in payload.get("runs", []):
        paths = [root / record["run_meta"], *(root / p for p in record["summary"].values())]
        if all(item.is_file() for item in paths):
            available.append(record)
    return {**payload, "runs": available}
