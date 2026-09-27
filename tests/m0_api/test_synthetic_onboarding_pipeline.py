"""Synthetic onboarding from the existing site contract through M3/M4 handoff."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from backend.m0_api import schemas
from backend.m0_api.main import app
from backend.m0_api.worker import Worker
from backend.m3_dflowfm.generator import KERNEL
from backend.m2_breach.breach_params import compute_dam
from backend.m4_sph.generator import build_nearfield_case
from backend.m5_emulator.scenario_design import ScenarioDesignBlockedError
from backend.shared.site_config import SiteConfig
from tests.m0_api.conftest import wait_until
from tests.m1_terrain import synthetic_valley as valley


REPO = Path(__file__).resolve().parents[2]
SITE_PATH = REPO / "sites" / "synth_engdam.yaml"


def _seed_synthetic_raw(data_dir: Path, site_raw: dict) -> None:
    raw_dir = data_dir / site_raw["site"]["id"] / "raw"
    dam = site_raw["dams"][0]
    valley.write_raw_rasters(
        raw_dir, tuple(site_raw["domains"]["far_field"]["bbox"]["value"]),
        tuple(dam["breach_location"]["value"]),
        tuple(site_raw["points_of_interest"][0]["location"]["value"]),
        tuple(dam["location"]["value"]),
    )
    valley.write_raw_provenance(raw_dir, "srtm_gl1")


def test_json_onboarding_runs_m1_m2_m5_design_and_m3_m4_handoffs(data_dir):
    site_raw = yaml.safe_load(SITE_PATH.read_text(encoding="utf-8"))
    site_id = site_raw["site"]["id"]
    _seed_synthetic_raw(data_dir, site_raw)

    client = TestClient(app)
    accepted = client.post("/api/v1/sites", json={"site_config": site_raw, "demo_mode": True})
    assert accepted.status_code == 202, accepted.text
    job_id = accepted.json()["job_id"]

    worker = Worker()
    worker.acquire_lock()
    try:
        wait_until(lambda: client.get(f"/api/v1/jobs/{job_id}").json()["stage"] in {"simulating", "failed"}, worker.tick)
    finally:
        worker.close()

    status = client.get(f"/api/v1/jobs/{job_id}").json()
    schemas.validate("job_status.schema.json", status)
    assert status["stage"] == "simulating", status.get("error")
    assert (data_dir / site_id / "terrain" / "provenance.json").is_file()  # M0 -> M1
    assert (data_dir / site_id / "breach" / "breach_params.json").is_file()  # M0 -> M2

    design_path = data_dir / site_id / "design" / "scenario_design.json"
    design = json.loads(design_path.read_text())
    schemas.validate("scenario_design.schema.json", design)
    scenarios = design["scenarios"]
    assert len(scenarios) == 4
    assert len({(s["params"]["breach_width_m"], s["params"]["failure_time_s"]) for s in scenarios}) == 4
    assert design["has_placeholders"] is False
    for scenario in scenarios:
        params = scenario["params"]
        assert params["water_volume_m3"] > 0
        for item in design["inputs"]:
            assert item["low"] <= params[item["name"]] <= item["high"]

    # Campaign preparation creates actual D-Flow FM case files, but this test
    # stops before launching the solver process.
    from backend.m0_api import registry
    conn = registry.connect()
    try:
        rows = conn.execute("SELECT run_id, meta_json FROM runs WHERE run_id LIKE ? ORDER BY run_id",
                            (f"{site_id}__demo_s%__delft3d",)).fetchall()
        assert len(rows) == 4
        for row in rows:
            case_dir = Path(json.loads(row["meta_json"])["case_dir"])
            assert (case_dir / "model.mdu").is_file()
    finally:
        conn.close()

    # M4 consumes the same M2 scenario params and canonical M1 terrain.
    for scenario in scenarios:
        spec, meta = build_nearfield_case(site_id, scenario["scenario_id"], scenario["params"],
                                          data_dir=data_dir, sites_dir=REPO / "sites")
        assert spec is not None
        assert meta["scenario_id"] == scenario["scenario_id"]


@pytest.mark.skipif(not KERNEL.is_file(), reason="D-Flow FM installation is not available")
def test_synthetic_demo_runs_solver_postprocessing_and_m5_loocv(data_dir):
    site_raw = yaml.safe_load(SITE_PATH.read_text(encoding="utf-8"))
    site_id = site_raw["site"]["id"]
    _seed_synthetic_raw(data_dir, site_raw)
    client = TestClient(app)
    response = client.post("/api/v1/sites", json={"site_config": site_raw, "demo_mode": True})
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]

    worker = Worker()
    worker.acquire_lock()
    stages = []
    try:
        wait_until(
            lambda: client.get(f"/api/v1/jobs/{job_id}").json()["stage"] in {"ready", "failed"},
            lambda: (worker.tick(), stages.append(client.get(f"/api/v1/jobs/{job_id}").json()["stage"])),
            timeout_s=90.0,
        )
    finally:
        worker.close()

    job = client.get(f"/api/v1/jobs/{job_id}").json()
    assert job["stage"] == "ready", job.get("error")
    assert {"terrain", "breach", "design", "simulating", "training", "validating", "ready"} <= set(stages)
    emulator_dir = data_dir / site_id / "emulator" / "delft3d"
    manifest = json.loads((emulator_dir / "manifest.json").read_text())
    validation = json.loads((emulator_dir / "validation" / "loocv.json").read_text())
    assert len(manifest["run_ids"]) == 4
    assert manifest["demo_mode"] is True
    assert manifest["display_label"] == "DEMO MODE"
    assert manifest["confidence"] == "LOW"
    assert validation["n_runs"] == 4


def test_missing_synthetic_volume_blocks_m2_and_m5_without_zero_fallback(tmp_path):
    raw = yaml.safe_load(SITE_PATH.read_text(encoding="utf-8"))
    bad = copy.deepcopy(raw)
    bad["dams"][0]["breach_inputs"]["water_volume_above_invert"].update(
        value=None, status="placeholder")
    cfg = SiteConfig.model_validate(bad)
    entry = compute_dam(cfg.dams[0])
    width = entry["parameters"]["breach_width_m"]
    assert width["status"] == "blocked"
    assert width["low"] is None and width["high"] is None
    with pytest.raises(ScenarioDesignBlockedError, match="water_volume_m3"):
        from backend.m5_emulator.scenario_design import build_scenario_design
        build_scenario_design(cfg, "synth_lake")
