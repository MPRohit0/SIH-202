"""Tests for the worker's scheduled re-checks (backend.m0_api.worker `_schedule_rechecks`,
`_run_recheck`): a fake clock drives `site_status.is_due`, and `gee_fetch.run` is monkeypatched so
the checking stage never touches the network."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from backend.m0_api import jobs, registry, site_status
from backend.m0_api.worker import Worker
from backend.m7_gee import cache as gee_cache
from backend.m7_gee import fetch as gee_fetch
from tests.m0_api.conftest import wait_until

SITE = "teesta"


@pytest.fixture
def clock(monkeypatch):
    state = {"now": datetime(2026, 1, 1, tzinfo=timezone.utc)}
    monkeypatch.setattr(registry, "utc_now_dt", lambda: state["now"])

    def advance(days: float) -> None:
        state["now"] += timedelta(days=days)

    return advance


@pytest.fixture
def worker():
    w = Worker()
    w.acquire_lock()
    w.recover()
    yield w
    w.close()


def _write_manifest(data_dir, site_id=SITE, model="delft3d", trained_at="2026-01-01T00:00:00Z"):
    path = data_dir / site_id / "emulator" / model / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"site_id": site_id, "model": model, "trained_at": trained_at}))


def _stub_lake_area_result(monkeypatch, data_dir, *, outdated: bool, change_pct=0.0, threshold_pct=10.0):
    """Replaces the real M7 fetch with a write of `gee/recheck.json` only -- `_run_recheck` reads
    that file back, exactly like a real `gee_fetch.run` call would leave it."""
    def fake_run(site_id, provider=None, data_dir=None, **kw):
        gee_cache.write_json(site_id, "recheck.json", {
            "site_id": site_id, "checked_at": registry.utc_now(),
            "latest_area_m2": 1.0, "reference_area_m2": 1.0,
            "change_pct": change_pct, "threshold_pct": threshold_pct, "outdated": outdated,
            "reason": "outdated_lake_area_change" if outdated else "within_threshold",
        }, data_dir)
        return gee_fetch.FetchResult(site_id=site_id)
    monkeypatch.setattr(gee_fetch, "run", fake_run)
    monkeypatch.setattr(gee_fetch, "best_effort_provider", lambda *a, **k: None)


def test_no_recheck_job_without_a_published_library(conn, worker, data_dir):
    assert worker.tick() is False
    assert jobs.find_active_job(conn, SITE) is None


def test_recheck_job_queued_when_due(conn, worker, data_dir, monkeypatch):
    _write_manifest(data_dir)
    _stub_lake_area_result(monkeypatch, data_dir, outdated=False)
    assert worker.tick() is True
    job_id = jobs.find_active_job(conn, SITE)
    assert job_id is not None
    row = jobs.get_job(conn, job_id)
    assert row["kind"] == "recheck"


def test_no_recheck_job_when_not_yet_due(conn, worker, data_dir, clock):
    _write_manifest(data_dir)
    site_status.set_frequency(SITE, 90)  # just checked, not due for 90 days
    site_status.record_check(SITE, outdated=False, status_reason_key=None, status_detail=None)
    clock(1)  # only a day later
    assert worker.tick() is False
    assert jobs.find_active_job(conn, SITE) is None


def _recheck_job_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM jobs WHERE site_id = ? AND kind = 'recheck'", (SITE,)).fetchone()[0]


def test_no_second_recheck_job_while_one_is_active(conn, worker, data_dir, monkeypatch):
    _write_manifest(data_dir)
    _stub_lake_area_result(monkeypatch, data_dir, outdated=False)
    for _ in range(5):  # would create a duplicate on every tick if the active-job check were missing
        worker.tick()
    assert _recheck_job_count(conn) == 1


def test_lake_area_outdated_flags_site(conn, worker, data_dir, monkeypatch):
    _write_manifest(data_dir)
    _stub_lake_area_result(monkeypatch, data_dir, outdated=True, change_pct=15.0, threshold_pct=10.0)
    job_id = wait_until_job_created(worker, conn)
    wait_until(lambda: jobs.job_status(conn, job_id)["stage"] == "done", worker.tick)

    state = site_status.load(SITE, data_dir=data_dir)
    assert state["outdated"] is True
    assert state["status_reason_key"] == "outdated_lake_area_change"
    assert state["status_detail"]["change_pct"] == 15.0


def test_library_age_flags_site_when_lake_area_is_fine(conn, worker, data_dir, monkeypatch, clock):
    _write_manifest(data_dir, trained_at="2026-01-01T00:00:00Z")
    _stub_lake_area_result(monkeypatch, data_dir, outdated=False)
    clock(site_status.DEFAULT_MAX_LIBRARY_AGE_DAYS + 1)  # library is now older than the max age

    job_id = wait_until_job_created(worker, conn)
    wait_until(lambda: jobs.job_status(conn, job_id)["stage"] == "done", worker.tick)

    state = site_status.load(SITE, data_dir=data_dir)
    assert state["outdated"] is True
    assert state["status_reason_key"] == "outdated_library_age"


def test_lake_area_check_wins_over_library_age(conn, worker, data_dir, monkeypatch, clock):
    _write_manifest(data_dir, trained_at="2026-01-01T00:00:00Z")
    _stub_lake_area_result(monkeypatch, data_dir, outdated=True, change_pct=20.0, threshold_pct=10.0)
    clock(site_status.DEFAULT_MAX_LIBRARY_AGE_DAYS + 1)  # both would trigger

    job_id = wait_until_job_created(worker, conn)
    wait_until(lambda: jobs.job_status(conn, job_id)["stage"] == "done", worker.tick)

    assert site_status.load(SITE, data_dir=data_dir)["status_reason_key"] == "outdated_lake_area_change"


def test_lapsed_schedule_alone_does_not_flag_outdated(conn, worker, data_dir, monkeypatch, clock):
    """docs/decisions.md open question #4, resolved: a merely-overdue check must never look like
    `outdated_library_age` -- only DEFAULT_MAX_LIBRARY_AGE_DAYS (well beyond any sane
    frequency_days) can."""
    _write_manifest(data_dir, trained_at="2026-01-01T00:00:00Z")
    _stub_lake_area_result(monkeypatch, data_dir, outdated=False)
    clock(site_status.DEFAULT_RECHECK_FREQUENCY_DAYS + 1)  # schedule lapsed, library still young

    job_id = wait_until_job_created(worker, conn)
    wait_until(lambda: jobs.job_status(conn, job_id)["stage"] == "done", worker.tick)

    assert site_status.load(SITE, data_dir=data_dir)["outdated"] is False


def wait_until_job_created(worker, conn):
    wait_until(lambda: jobs.find_active_job(conn, SITE) is not None, worker.tick)
    return jobs.find_active_job(conn, SITE)
