"""`backend.m4_sph.compare_mvp` gates on the SPH particle-exclusion warning
(docs/progress.md 2026-09-27 "Demo stabilization pass, item 2": the Teesta a02 run's known-
anomalous depth/velocity fields must never be shown as a paired comparison metric)."""
from __future__ import annotations

import json
from pathlib import Path

from backend.m4_sph.compare_mvp import M3_RUN_ID, M4_RUN_ID, SCENARIO_ID, SITE_ID, build_comparison
from backend.m0_api.schemas import validate


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def test_build_comparison_refuses_paired_metrics_when_sph_excluded_particles(tmp_path):
    m3_dir, m4_dir, terrain_dir = tmp_path / "m3", tmp_path / "m4", tmp_path / "terrain"
    _write(m3_dir / "run_meta.json", {"run_id": M3_RUN_ID, "solver_status": "REAL_SOLVER_OUTPUT",
                                       "case_dir": "case"})
    _write(m4_dir / "run_meta.json", {"status": "postprocessed",
        "caveats": ["clear_water", "sph_particle_exclusion_warning"],
        "warnings": ["DualSPHysics reported more than 100% of current fluid particles excluded"]})
    manifest = tmp_path / "routed_discharge.json"
    _write(manifest, {"source_m3_run_id": M3_RUN_ID})

    sidecar = build_comparison(tmp_path, m3_run_dir=m3_dir, m4_run_dir=m4_dir,
                               terrain_dir=terrain_dir, routed_manifest=manifest)

    result = json.loads(sidecar.read_text())
    validate("compare.schema.json", result)
    assert result["site_id"] == SITE_ID and result["scenario_id"] == SCENARIO_ID
    assert result["sph_vs_delft3d"]["available"] is False
    assert result["sph_vs_delft3d"]["run_ids"] == [M3_RUN_ID]
    assert result["sph_vs_delft3d"]["metrics"] == {}
    assert "comparison_unavailable" in {c["id"] for c in result["caveats"]}
    assert result["provenance"]["m4_run_id"] == M4_RUN_ID
    assert result["provenance"]["reason"] == "sph_particle_exclusion_warning present in the SPH run's caveats"


def test_build_comparison_raises_without_excluded_particles_but_missing_grid(tmp_path):
    """Confirms the gate is what short-circuits: without the exclusion caveat, the (unpatched)
    comparison path still requires the real grid/mesh artifacts this fixture doesn't provide."""
    m3_dir, m4_dir, terrain_dir = tmp_path / "m3", tmp_path / "m4", tmp_path / "terrain"
    _write(m3_dir / "run_meta.json", {"run_id": M3_RUN_ID, "solver_status": "REAL_SOLVER_OUTPUT",
                                       "case_dir": "case"})
    _write(m4_dir / "run_meta.json", {"status": "postprocessed", "caveats": ["clear_water"]})
    manifest = tmp_path / "routed_discharge.json"
    _write(manifest, {"source_m3_run_id": M3_RUN_ID})

    try:
        build_comparison(tmp_path, m3_run_dir=m3_dir, m4_run_dir=m4_dir,
                          terrain_dir=terrain_dir, routed_manifest=manifest)
        assert False, "expected a failure without the SPH exclusion caveat and no grid fixture"
    except (FileNotFoundError, KeyError):
        pass
