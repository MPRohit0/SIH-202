"""Runs whole scenario sets through M3/M4 (CLAUDE.md architecture table).

This session only builds the M4 (SPH) path: `run_sph_campaign` builds and
registers a near-field GenCase case (`backend.m4_sph.generator`) for every
scenario_id listed in a site's `simulation.sph.scenarios` (contract §4.4),
under one shared `campaign` job (`backend.m0_api.jobs`, contract §4.5).

It does NOT launch GenCase or the DualSPHysics solver -- no launcher exists
yet anywhere in the codebase (`docs/progress.md`, this session), and
`backend.m0_api.worker`'s `simulating` stage is explicitly fake today ("M1,
M2 and M5 plug in here later"). A case that builds successfully is written
to disk and its `runs` row set to `status: "queued"`; it stays queued until
a real launcher exists. There is also no M3 (Delft3D) path yet --
`backend/m3_delft3d` doesn't exist (only `backend/m3_pilot/`, a working case
directory, not a module) -- so `model="delft3d"` is out of scope here too.

VRAM gating is NOT reimplemented here: `generator.build_nearfield_case`
already estimates particle count/VRAM for the case (`vram_estimator.py`,
calibrated from the pilot run) and raises `OverVramBudget` if no feasible
`dp_m` fits the configured budget (`config/m4_sph.yaml`'s `vram_budget_mib`/
`vram_margin`, CLAUDE.md rule 13's 8 GB RTX 4060 budget). This module just
catches that and reports the case as refused instead of queued.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from backend.m0_api import jobs, registry
from backend.shared.site_config import load_site_config

CONTRACT_VERSION = "0.2.0"


@dataclass(frozen=True)
class CampaignCaseResult:
    scenario_id: str
    run_id: str
    status: str  # "queued" | "refused"
    reason: str | None = None


def _scenario_params(design: dict, scenario_id: str) -> dict | None:
    for entry in design["scenarios"] + design["extra"]:
        if entry["scenario_id"] == scenario_id:
            return entry["params"]
    return None


def _load_design(data_dir: Path, site_id: str) -> dict | None:
    path = data_dir / site_id / "design" / "scenario_design.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def run_sph_campaign(
    site_id: str,
    conn: sqlite3.Connection,
    data_dir: Path | None = None,
    sites_dir: str | Path | None = None,
) -> tuple[str | None, list[CampaignCaseResult]]:
    """Build and register every scenario in `site_id`'s `simulation.sph.scenarios`
    as a near-field SPH case, under one shared `campaign` job.

    Returns `(job_id, results)`. `job_id` is `None` if there is nothing to do
    (`simulation.sph.scenarios` is empty) -- no phantom job is created.
    A scenario missing from `design/scenario_design.json`, or whose case
    exceeds the VRAM budget (`generator.OverVramBudget`) or has no usable
    inflow yet (`generator.InflowUnavailable`), is reported as `"refused"`
    rather than silently dropped or guessed at.
    """
    from backend.m4_sph import generator  # local import: keep this module importable without geopandas

    data_dir = Path(data_dir) if data_dir is not None else registry.data_dir()
    cfg = load_site_config(site_id, sites_dir=sites_dir)
    scenario_ids = cfg.simulation.sph.scenarios
    if not scenario_ids:
        return None, []

    design = _load_design(data_dir, site_id)

    job_id = jobs.create_job(conn, "campaign", site_id,
                              payload={"model": "sph", "scenario_ids": list(scenario_ids)})

    results: list[CampaignCaseResult] = []
    for scenario_id in scenario_ids:
        run_id = f"{scenario_id}__sph"
        params = _scenario_params(design, scenario_id) if design is not None else None
        if params is None:
            reason = (f"no 'design/scenario_design.json' for site '{site_id}'" if design is None
                      else f"scenario '{scenario_id}' not found in design/scenario_design.json")
            results.append(CampaignCaseResult(scenario_id, run_id, "refused", reason))
            jobs.log_event(conn, job_id, f"refused {run_id}: {reason}")
            continue

        try:
            spec, case_meta = generator.build_nearfield_case(
                site_id, scenario_id, params, data_dir=data_dir, sites_dir=sites_dir,
            )
        except (generator.OverVramBudget, generator.InflowUnavailable) as e:
            results.append(CampaignCaseResult(scenario_id, run_id, "refused", str(e)))
            jobs.log_event(conn, job_id, f"refused {run_id}: {e}")
            continue

        run_directory = jobs.run_dir(site_id, run_id)
        terrain_dir = data_dir / site_id / "terrain"
        generator.write_case(spec, case_meta, run_directory, terrain_dir)

        conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
        conn.execute(
            "INSERT INTO runs (run_id, scenario_id, model, status, run_dir, meta_json)"
            " VALUES (?, ?, 'sph', 'queued', ?, ?)",
            (run_id, scenario_id, str(run_directory), json.dumps(case_meta)),
        )
        conn.commit()
        results.append(CampaignCaseResult(scenario_id, run_id, "queued"))
        jobs.log_event(conn, job_id, f"queued {run_id} (dp={case_meta['dp_m']} m)")

    return job_id, results


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site_id")
    parser.add_argument("--model", choices=["sph"], default="sph",
                         help="only 'sph' is implemented this session (see module docstring)")
    args = parser.parse_args(argv)

    registry.init_db()
    conn = registry.connect()
    try:
        job_id, results = run_sph_campaign(args.site_id, conn)
    finally:
        conn.close()

    if job_id is None:
        print(f"{args.site_id}: simulation.sph.scenarios is empty, nothing to queue")
        return 0
    print(f"{args.site_id}: campaign job {job_id}")
    for r in results:
        print(f"  {r.status:8s} {r.run_id}" + (f" -- {r.reason}" if r.reason else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
