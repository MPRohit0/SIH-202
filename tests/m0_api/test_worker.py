"""Worker: runs job stages, launches detached (fake) solver runs, reads their
progress from `log.txt`, and recovers after a restart.

Every stage is a fake task for now: in-process stages sleep, and `simulating`
launches `backend.m0_api.fake_solver` as a real detached subprocess, so the
detach / log-reading / restart paths are exercised for real.
"""

from __future__ import annotations

import json
import os
import signal

import pytest

from backend.m0_api import jobs, runner, schemas
from backend.m0_api.worker import Worker, WorkerAlreadyRunning
from tests.m0_api.conftest import wait_until


def _stage(conn, job_id):
    return jobs.job_status(conn, job_id)["stage"]


def _runs(conn, job_id):
    run_ids = json.loads(conn.execute("SELECT payload_json FROM jobs WHERE job_id=?", (job_id,)).fetchone()[0]).get("run_ids", [])
    rows = {r["run_id"]: r for r in conn.execute("SELECT * FROM runs")}
    return [rows[r] for r in run_ids]


def _running_run(conn, job_id):
    running = [r for r in _runs(conn, job_id) if r["status"] == "running"]
    return running[0] if running else None


@pytest.fixture
def worker():
    w = Worker()
    w.acquire_lock()
    w.recover()
    yield w
    w.close()


def test_full_onboarding_job_reaches_ready(conn, worker):
    job_id = jobs.create_job(conn, "onboarding", "kosi")
    seen_stages, seen_progress, max_running = [], [], 0

    def step():
        nonlocal max_running
        worker.tick()
        status = jobs.job_status(conn, job_id)
        schemas.validate("job_status.schema.json", status)
        if not seen_stages or seen_stages[-1] != status["stage"]:
            seen_stages.append(status["stage"])
        if status["stage"] == "simulating":
            seen_progress.append(status["progress"]["current"])
        max_running = max(max_running, sum(r["status"] == "running" for r in _runs(conn, job_id)))

    wait_until(lambda: _stage(conn, job_id) == "ready", step)

    assert seen_stages == ["terrain", "breach", "design", "simulating", "training", "validating", "ready"]
    assert seen_progress[0] == 0 and seen_progress == sorted(seen_progress)
    assert max_running == 1  # rule 13: one solver run at a time
    final = jobs.job_status(conn, job_id)
    assert final["started_at"] is not None
    assert [r["status"] for r in _runs(conn, job_id)] == ["completed"] * 3


def test_runs_have_contract_ids_and_run_dirs(conn, worker, data_dir):
    job_id = jobs.create_job(conn, "onboarding", "kosi", demo_mode=True)
    wait_until(lambda: _stage(conn, job_id) == "ready", worker.tick)
    runs = _runs(conn, job_id)
    assert [r["run_id"] for r in runs] == [f"kosi_demo_s00{i}__delft3d" for i in (1, 2, 3)]
    for r in runs:
        log = data_dir / "kosi" / "runs" / r["run_id"] / "log.txt"
        assert r["run_dir"] == str(log.parent)
        assert runner.read_progress(log).ok


def test_simulating_progress_is_read_from_log(conn, worker):
    job_id = jobs.create_job(conn, "onboarding", "kosi")
    wait_until(lambda: _running_run(conn, job_id) is not None, worker.tick)
    wait_until(lambda: any("PROGRESS" in line for line in jobs.job_status(conn, job_id)["log_tail"]))
    status = jobs.job_status(conn, job_id)
    assert status["progress"]["unit"] == "runs"
    assert status["progress"]["total"] == 3
    assert status["eta_s"] is None  # no run finished yet → no estimate


def test_eta_appears_after_first_run(conn, worker):
    job_id = jobs.create_job(conn, "onboarding", "kosi")
    wait_until(lambda: (jobs.job_status(conn, job_id)["progress"]["current"] or 0) >= 1, worker.tick)
    status = jobs.job_status(conn, job_id)
    if status["stage"] == "simulating":
        assert status["eta_s"] is not None and status["eta_s"] > 0


def test_failed_run_fails_job(conn, worker, monkeypatch):
    monkeypatch.setenv("SIH26_FAKE_FAIL_RUN", "2")
    job_id = jobs.create_job(conn, "onboarding", "kosi")
    wait_until(lambda: _stage(conn, job_id) == "failed", worker.tick)
    status = jobs.job_status(conn, job_id)
    schemas.validate("job_status.schema.json", status)
    assert status["error"]["error"]["code"] == "run_failed"
    assert [r["status"] for r in _runs(conn, job_id)] == ["completed", "failed", "queued"]


# --- restart recovery --------------------------------------------------------
def test_recovery_run_finished_while_worker_was_down(conn, worker):
    job_id = jobs.create_job(conn, "onboarding", "kosi")
    wait_until(lambda: _running_run(conn, job_id) is not None, worker.tick)
    run = _running_run(conn, job_id)
    worker.close()  # the worker "dies"; the detached solver keeps going

    log = runner.log_path(run["run_dir"])
    wait_until(lambda: runner.read_progress(log).finished)

    w2 = Worker()
    w2.acquire_lock()
    w2.recover()
    try:
        row = conn.execute("SELECT status FROM runs WHERE run_id=?", (run["run_id"],)).fetchone()
        assert row["status"] == "completed"
        wait_until(lambda: _stage(conn, job_id) == "ready", w2.tick)
    finally:
        w2.close()


def test_recovery_reattaches_to_live_run(conn, worker, monkeypatch):
    monkeypatch.setenv("SIH26_FAKE_RUN_STEP_S", "0.5")  # keep the run alive across the restart
    job_id = jobs.create_job(conn, "onboarding", "kosi")
    wait_until(lambda: _running_run(conn, job_id) is not None, worker.tick)
    run = _running_run(conn, job_id)
    worker.close()

    w2 = Worker()
    w2.acquire_lock()
    w2.recover()
    try:
        assert _running_run(conn, job_id)["run_id"] == run["run_id"]
        assert _stage(conn, job_id) == "simulating"
        monkeypatch.setenv("SIH26_FAKE_RUN_STEP_S", "0.05")
        wait_until(lambda: _stage(conn, job_id) == "ready", w2.tick, timeout_s=30)
    finally:
        w2.close()


def test_recovery_run_died_without_done_fails_job(conn, worker, monkeypatch):
    monkeypatch.setenv("SIH26_FAKE_RUN_STEP_S", "0.5")
    job_id = jobs.create_job(conn, "onboarding", "kosi")
    wait_until(lambda: _running_run(conn, job_id) is not None, worker.tick)
    run = _running_run(conn, job_id)
    pid = json.loads(run["meta_json"])["pid"]
    worker.close()

    os.killpg(pid, signal.SIGKILL)  # the solver dies while nobody is watching
    wait_until(lambda: not runner.is_alive(pid, run["run_id"]))

    w2 = Worker()
    w2.acquire_lock()
    w2.recover()
    try:
        status = jobs.job_status(conn, job_id)
        assert status["stage"] == "failed"
        assert status["error"]["error"]["code"] == "worker_lost_run"
    finally:
        w2.close()


def test_recovery_reruns_interrupted_in_process_stage(conn, worker):
    job_id = jobs.create_job(conn, "onboarding", "kosi")
    jobs.set_stage(conn, job_id, "queued", "terrain")
    jobs.set_stage(conn, job_id, "terrain", "breach")  # worker died during `breach`
    worker.recover()
    wait_until(lambda: _stage(conn, job_id) == "ready", worker.tick)


def test_second_worker_cannot_start(worker):
    w2 = Worker()
    with pytest.raises(WorkerAlreadyRunning):
        w2.acquire_lock()
    w2.close()


def test_idle_worker_tick_does_nothing(worker):
    assert worker.tick() is False
