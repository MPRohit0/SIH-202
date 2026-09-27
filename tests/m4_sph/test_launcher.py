from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from backend.m4_sph.launcher import launch_case, read_result, run_case_sync


def _fake_binaries(tmp_path: Path) -> Path:
    path = tmp_path / "bin"
    path.mkdir()
    gen = path / "GenCase_linux64"
    gen.write_text(
        "#!/bin/sh\nset -eu\nprintf '<case/>\\n' > \"$2.xml\"\nprintf 'initial-particles' > \"$2.bi4\"\necho 'Finished execution (code=0).'\n",
        encoding="utf-8",
    )
    gen.chmod(0o755)
    solver = path / "DualSPHysics5.4_linux64"
    solver.write_text(
        "#!/bin/sh\nset -eu\nmkdir -p \"$5/data\"\nprintf 'solver output' > \"$5/Run.out\"\nprintf 'PART' > \"$5/data/Part_0000.bi4\"\necho 'Finished execution (code=0).'\n",
        encoding="utf-8",
    )
    solver.chmod(0o755)
    return path


def _case(tmp_path: Path) -> tuple[Path, Path]:
    run_dir = tmp_path / "data" / "synth" / "runs" / "synth__s001__sph"
    case_dir = run_dir / "case"
    case_dir.mkdir(parents=True)
    (case_dir / "synth__s001__sph_Def.xml").write_text("<case/>", encoding="utf-8")
    (case_dir / "case_meta.json").write_text("{}", encoding="utf-8")
    return case_dir, run_dir


def test_run_case_sync_keeps_logs_exit_codes_vram_and_nonempty_artifacts(tmp_path, monkeypatch):
    bin_dir = _fake_binaries(tmp_path)
    case_dir, run_dir = _case(tmp_path)
    # A private nvidia-smi fixture proves the sampler parser without depending on a GPU.
    nvidia = tmp_path / "nvidia-smi"
    nvidia.write_text("#!/bin/sh\nprintf '2026/09/27 12:00:00.000, 123\\n'\n", encoding="utf-8")
    nvidia.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")

    result = run_case_sync(case_dir, run_dir / "attempts" / "a00", bin_dir, sample_interval_s=0.01)

    assert result["success"] is True
    assert result["gencase_returncode"] == 0
    assert result["solver_returncode"] == 0
    assert result["peak_vram_mb"] == 123
    assert (run_dir / "raw" / "Run.out").stat().st_size > 0
    assert (run_dir / "raw" / "data" / "Part_0000.bi4").stat().st_size > 0
    assert (run_dir / "raw" / "log.txt").is_file()
    saved = json.loads((run_dir / "attempts" / "a00" / "execution.json").read_text())
    assert saved == result


def test_run_case_sync_rejects_nonzero_solver_and_keeps_failure_record(tmp_path):
    bin_dir = _fake_binaries(tmp_path)
    solver = bin_dir / "DualSPHysics5.4_linux64"
    solver.write_text("#!/bin/sh\necho 'failed'\nexit 7\n", encoding="utf-8")
    solver.chmod(0o755)
    case_dir, run_dir = _case(tmp_path)

    result = run_case_sync(case_dir, run_dir / "attempts" / "a00", bin_dir)

    assert result["success"] is False
    assert result["solver_returncode"] == 7
    assert "status 7" in result["error"]
    assert (run_dir / "attempts" / "a00" / "solver.log").is_file()
    assert (run_dir / "raw").is_dir()


def test_detached_launcher_records_result_and_outputs(tmp_path, monkeypatch):
    bin_dir = _fake_binaries(tmp_path)
    case_dir, run_dir = _case(tmp_path)
    monkeypatch.setenv("DSPH_BIN_DIR", str(bin_dir))
    process = launch_case(case_dir, run_dir, str(bin_dir))
    assert process.wait(timeout=15) == 0
    result = read_result(run_dir, 0)
    assert result and result["success"]
    assert (run_dir / "raw" / "Run.out").is_file()


@pytest.mark.skipif(not os.environ.get("DSPH_BIN_DIR"), reason="set DSPH_BIN_DIR for the controlled DualSPHysics pilot")
def test_stock_3d_dambreak_executes_through_m4_launcher(tmp_path):
    """Controlled stock benchmark only; it is not a target-site or terrain validation."""
    source = Path(__file__).resolve().parents[2] / "backend/m4_pilot/dambreak3d_dp0p0200/CaseDambreak_Def.xml"
    case_dir = tmp_path / "run" / "case"
    case_dir.mkdir(parents=True)
    (case_dir / source.name).write_bytes(source.read_bytes())

    result = run_case_sync(case_dir, tmp_path / "run" / "attempts" / "a00", os.environ["DSPH_BIN_DIR"])

    assert result["success"], result
    assert result["gencase_returncode"] == 0
    assert result["solver_returncode"] == 0
    assert result["solver_wall_time_s"] is not None
    assert (tmp_path / "run/raw/Run.out").stat().st_size > 0
    assert list((tmp_path / "run/raw/data").glob("Part_*.bi4"))
