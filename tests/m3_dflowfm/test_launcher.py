from __future__ import annotations

from backend.m3_dflowfm.launcher import check_success, read_progress


def test_rule_one_ignores_exit_code_and_requires_both_outputs(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    (output / "case.dia").write_text("** INFO   : completed\n")
    (output / "case_map.nc").touch()
    assert not check_success(tmp_path, "case")["success"]
    (output / "case_his.nc").touch()
    assert check_success(tmp_path, "case")["success"]
    (output / "case.dia").write_text("** INFO : started\n** ERROR : kernel error\n")
    assert not check_success(tmp_path, "case")["success"]


def test_progress_reads_simulation_period_from_dia(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    (output / "case.dia").write_text("** INFO   : simulation period      (s)  : 1200.0\n")
    progress = read_progress(tmp_path, "case", total_s=2400)
    assert progress.steps_done == 1200
    assert progress.steps_total == 2400
    assert not progress.finished
