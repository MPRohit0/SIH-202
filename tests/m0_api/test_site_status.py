"""Tests for backend.m0_api.site_status."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.m0_api import registry, site_status


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch):
    """A simple fake clock: `advance(days)` moves `registry.utc_now_dt()` forward."""
    state = {"now": datetime(2026, 1, 1, tzinfo=timezone.utc)}
    monkeypatch.setattr(registry, "utc_now_dt", lambda: state["now"])

    def advance(days: float) -> None:
        from datetime import timedelta
        state["now"] += timedelta(days=days)

    return advance


def test_load_defaults_when_never_checked(data_dir):
    state = site_status.load("teesta")
    assert state["frequency_days"] == site_status.DEFAULT_RECHECK_FREQUENCY_DAYS
    assert state["outdated"] is False
    assert state["last_checked_at"] is None
    assert state["next_check_at"] is None


def test_is_due_when_never_checked(data_dir):
    assert site_status.is_due(site_status.load("teesta")) is True


def test_set_frequency_persists_and_computes_next_check(data_dir):
    state = site_status.set_frequency("teesta", 30)
    assert state["frequency_days"] == 30
    assert state["next_check_at"] == "2026-01-31T00:00:00Z"
    assert site_status.load("teesta")["frequency_days"] == 30


def test_set_frequency_recomputes_from_last_checked_at(data_dir, _fixed_clock):
    site_status.record_check("teesta", outdated=False, status_reason_key=None, status_detail=None)
    _fixed_clock(5)  # now 5 days after the check
    state = site_status.set_frequency("teesta", 10)
    assert state["next_check_at"] == "2026-01-11T00:00:00Z"  # 10 days after last_checked_at, not now


def test_record_check_outdated_sets_reason_and_advances_schedule(data_dir):
    state = site_status.record_check(
        "teesta", outdated=True, status_reason_key="outdated_lake_area_change",
        status_detail={"change_pct": 12.0, "threshold_pct": 10.0},
    )
    assert state["outdated"] is True
    assert state["status_reason_key"] == "outdated_lake_area_change"
    assert state["last_checked_at"] == "2026-01-01T00:00:00Z"
    assert state["next_check_at"] == "2026-04-01T00:00:00Z"  # + default 90 days
    assert site_status.is_due(state) is False


def test_is_due_after_frequency_elapses(data_dir, _fixed_clock):
    state = site_status.set_frequency("teesta", 7)
    assert site_status.is_due(state) is False
    _fixed_clock(7)
    assert site_status.is_due(site_status.load("teesta")) is True


def test_overlay_marks_outdated(data_dir):
    site_status.record_check("teesta", outdated=True, status_reason_key="outdated_library_age",
                              status_detail={"age_days": 400.0})
    summary = site_status.overlay("teesta", {"site_id": "teesta", "status": "ready", "status_reason_key": None})
    assert summary["status"] == "outdated"
    assert summary["status_reason_key"] == "outdated_library_age"
    assert summary["status_detail"] == {"age_days": 400.0}
    assert summary["recheck"]["last_checked_at"] == "2026-01-01T00:00:00Z"


def test_overlay_leaves_status_alone_when_not_outdated(data_dir):
    summary = site_status.overlay("teesta", {"site_id": "teesta", "status": "ready", "status_reason_key": None})
    assert summary["status"] == "ready"
    assert summary["recheck"]["frequency_days"] == site_status.DEFAULT_RECHECK_FREQUENCY_DAYS


def test_overlay_corrects_fictitious_emulator_ready_for_a_real_ready_site(data_dir):
    """A `status: "ready"` site with no `emulator/<model>/manifest.json` on disk (e.g. Teesta,
    served by one direct D-Flow FM run) must not claim a trained emulator just because the mocked
    contract example it started from said so."""
    summary = site_status.overlay(
        "teesta", {"site_id": "teesta", "status": "ready", "status_reason_key": None,
                   "emulator_ready": True, "models_available": ["delft3d", "sph"]},
    )
    assert summary["emulator_ready"] is False
    assert summary["models_available"] == []
    assert summary["status_reason_key"] == "real_run_no_trained_emulator"
    assert summary["status"] == "ready"  # the site itself is still usable -- only the claim changes


def test_overlay_reports_a_real_trained_emulator_when_the_manifest_exists(data_dir):
    manifest_dir = data_dir / "teesta" / "emulator" / "delft3d"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "manifest.json").write_text("{}")
    summary = site_status.overlay(
        "teesta", {"site_id": "teesta", "status": "ready", "status_reason_key": None,
                   "emulator_ready": False, "models_available": []},
    )
    assert summary["emulator_ready"] is True
    assert summary["models_available"] == ["delft3d"]
    assert summary["status_reason_key"] is None


def test_overlay_does_not_touch_emulator_fields_for_a_non_ready_status(data_dir):
    """`onboarding`/`demo_mode` sites already set an accurate `status_reason_key` at
    construction (main.py) -- overlay must not stomp it."""
    summary = site_status.overlay(
        "demo_valley", {"site_id": "demo_valley", "status": "onboarding",
                         "status_reason_key": "synthetic_demo", "emulator_ready": False,
                         "models_available": ["delft3d"]},
    )
    assert summary["status_reason_key"] == "synthetic_demo"
    assert summary["models_available"] == ["delft3d"]  # left exactly as passed in
