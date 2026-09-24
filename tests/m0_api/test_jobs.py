"""Job state machine (contract §5.3 stages, §4.5 `jobs` table)."""

from __future__ import annotations

import re

import pytest

from backend.m0_api import jobs, schemas

JOB_ID_RE = re.compile(r"^job_\d{8}T\d{6}Z_[0-9a-f]{6}$")  # contract §1.7


# --- transitions -------------------------------------------------------------
@pytest.mark.parametrize("kind", sorted(jobs.STAGES))
def test_every_forward_step_is_legal(kind):
    stages = jobs.STAGES[kind]
    for old, new in zip(stages, stages[1:]):
        jobs.check_transition(kind, old, new)


@pytest.mark.parametrize("kind", sorted(jobs.STAGES))
def test_any_non_terminal_stage_can_fail(kind):
    for stage in jobs.STAGES[kind]:
        if stage not in jobs.TERMINAL:
            jobs.check_transition(kind, stage, "failed")


def test_onboarding_stages_match_contract():
    assert jobs.STAGES["onboarding"] == [
        "queued", "terrain", "breach", "design", "simulating", "training", "validating", "ready",
    ]
    assert jobs.STAGES["campaign"] == ["queued", "simulating", "postprocessing", "done"]
    assert jobs.STAGES["recheck"] == ["queued", "checking", "done"]


@pytest.mark.parametrize(
    "kind,old,new",
    [
        ("onboarding", "queued", "breach"),        # skip
        ("onboarding", "training", "simulating"),  # backwards
        ("onboarding", "queued", "queued"),        # no-op
        ("onboarding", "ready", "failed"),         # leave terminal
        ("onboarding", "failed", "queued"),        # leave terminal
        ("onboarding", "terrain", "checking"),     # other kind's stage
        ("campaign", "done", "failed"),
        ("recheck", "queued", "done"),
    ],
)
def test_illegal_transitions_raise(kind, old, new):
    with pytest.raises(jobs.IllegalTransition):
        jobs.check_transition(kind, old, new)


def test_rerun_kind_has_no_stages_yet():
    with pytest.raises(jobs.IllegalTransition):
        jobs.check_transition("rerun", "queued", "terrain")


# --- IDs ---------------------------------------------------------------------
def test_job_id_matches_contract_pattern():
    assert JOB_ID_RE.match(jobs.new_job_id())


def test_create_job_retries_on_id_clash(conn, monkeypatch):
    ids = iter(["job_20260924T101500Z_aaaaaa", "job_20260924T101500Z_aaaaaa", "job_20260924T101500Z_bbbbbb"])
    monkeypatch.setattr(jobs, "new_job_id", lambda: next(ids))
    first = jobs.create_job(conn, "onboarding", "kosi")
    second = jobs.create_job(conn, "onboarding", "other")
    assert (first, second) == ("job_20260924T101500Z_aaaaaa", "job_20260924T101500Z_bbbbbb")


# --- database writes ---------------------------------------------------------
def test_new_job_is_queued_and_valid(conn):
    job_id = jobs.create_job(conn, "onboarding", "kosi", demo_mode=True)
    status = jobs.job_status(conn, job_id)
    schemas.validate("job_status.schema.json", status)
    assert status["stage"] == "queued"
    assert status["stage_label_key"] == "job_stage_queued"
    assert status["started_at"] is None
    assert status["demo_mode"] is True
    assert status["eta_s"] is None
    assert status["error"] is None


def test_set_stage_walks_forward_and_rejects_skips(conn):
    job_id = jobs.create_job(conn, "onboarding", "kosi")
    jobs.set_stage(conn, job_id, "queued", "terrain")
    assert jobs.job_status(conn, job_id)["stage"] == "terrain"
    with pytest.raises(jobs.IllegalTransition):
        jobs.set_stage(conn, job_id, "terrain", "simulating")
    assert jobs.job_status(conn, job_id)["stage"] == "terrain"


def test_stale_writer_is_rejected(conn):
    job_id = jobs.create_job(conn, "onboarding", "kosi")
    jobs.set_stage(conn, job_id, "queued", "terrain")
    # A second writer still believes the job is `queued`.
    with pytest.raises(jobs.StaleStage):
        jobs.set_stage(conn, job_id, "queued", "terrain")


def test_fail_records_error_object(conn):
    job_id = jobs.create_job(conn, "onboarding", "kosi")
    jobs.set_stage(conn, job_id, "queued", "terrain")
    jobs.fail(conn, job_id, "terrain", "run_failed", "boom", {"x": 1})
    status = jobs.job_status(conn, job_id)
    schemas.validate("job_status.schema.json", status)
    assert status["stage"] == "failed"
    assert status["error"] == {"error": {"code": "run_failed", "message": "boom", "details": {"x": 1}}}
    with pytest.raises(jobs.IllegalTransition):
        jobs.set_stage(conn, job_id, "failed", "breach")


def test_progress_and_events_show_in_status(conn):
    job_id = jobs.create_job(conn, "onboarding", "kosi")
    jobs.set_progress(conn, job_id, 1, 3, "runs")
    for i in range(30):
        jobs.log_event(conn, job_id, f"event {i}")
    status = jobs.job_status(conn, job_id)
    assert status["progress"] == {"current": 1, "total": 3, "unit": "runs"}
    assert status["log_tail"][-1].endswith(" event 29")  # events carry a UTC timestamp
    assert len(status["log_tail"]) <= jobs.MAX_EVENTS


def test_find_active_job(conn):
    assert jobs.find_active_job(conn, "kosi") is None
    job_id = jobs.create_job(conn, "onboarding", "kosi")
    assert jobs.find_active_job(conn, "kosi") == job_id
    jobs.fail(conn, job_id, "queued", "cancelled", "test")
    assert jobs.find_active_job(conn, "kosi") is None


def test_unknown_job_status_is_none(conn):
    assert jobs.job_status(conn, "job_20260924T101500Z_000000") is None
