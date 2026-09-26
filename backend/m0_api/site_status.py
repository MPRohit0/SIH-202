"""Per-site re-check schedule and `outdated` flag: `data/<site_id>/site_status.json`.

Not a registry table: contract §4.5 freezes the registry's table list at
`scenarios`/`runs`/`jobs`/`queries`, so this stays a plain per-site JSON file,
the same pattern as `manifest.json`/`recheck.json`/`gee_meta.json` elsewhere.

`status` itself (`onboarding` | `demo_mode` | `ready` | `failed`) is derived
from a site's jobs, not stored here (docs/decisions.md 2.1: "site status is
never set by hand"). This file only carries what a re-check can add on top of
that: whether the published library is flagged `outdated`, why, and the
re-check schedule (contract §5.1 `SiteSummary.recheck`).

A lapsed schedule alone (`next_check_at` in the past) does NOT set `outdated`
-- docs/decisions.md open question #4, resolved this session as "banner only,
stays ready". `DEFAULT_MAX_LIBRARY_AGE_DAYS` is therefore deliberately much
larger than any sane `frequency_days`: only an actual stale-library finding
(lake area moved, or the library is older than the max age) sets `outdated`,
never just a missed check-in.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from backend.m0_api import registry

#: contract §5.1's own `SiteSummary` example uses 90 days; kept as the default
#: here since no other team decision overrides it (docs/decisions.md).
DEFAULT_RECHECK_FREQUENCY_DAYS = 90

#: Engineering knob, not a fact (CLAUDE.md rule 3 is about physical facts):
#: a trained library this old is flagged `outdated_library_age` even if the
#: lake area hasn't moved. Deliberately well above any typical
#: `frequency_days` so a merely-overdue check never looks like this trigger.
DEFAULT_MAX_LIBRARY_AGE_DAYS = 365

#: contract §5's `PUT /sites/{id}/recheck` `lake_area_change_threshold_pct`
#: default, matching `GeeSettings.recheck_threshold_pct` (backend/m7_gee/settings.py).
DEFAULT_LAKE_AREA_CHANGE_THRESHOLD_PCT = 10.0


def _path(site_id: str, data_dir: Path | None = None) -> Path:
    return (data_dir or registry.data_dir()) / site_id / "site_status.json"


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _default(site_id: str) -> dict[str, Any]:
    return {
        "site_id": site_id,
        "outdated": False,
        "status_reason_key": None,
        "status_detail": None,
        "frequency_days": DEFAULT_RECHECK_FREQUENCY_DAYS,
        "lake_area_change_threshold_pct": DEFAULT_LAKE_AREA_CHANGE_THRESHOLD_PCT,
        "last_checked_at": None,
        "next_check_at": None,
    }


def load(site_id: str, data_dir: Path | None = None) -> dict[str, Any]:
    """This site's re-check state, or contract-default values if it has never been checked."""
    path = _path(site_id, data_dir)
    if not path.is_file():
        return _default(site_id)
    stored = json.loads(path.read_text())
    return {**_default(site_id), **stored}


def save(site_id: str, state: dict[str, Any], data_dir: Path | None = None) -> None:
    path = _path(site_id, data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))


def is_due(state: dict[str, Any]) -> bool:
    """No re-check yet, or the schedule has lapsed (docs/decisions.md: this alone never sets
    `outdated`; it only makes a `recheck` job eligible to be queued)."""
    if state["next_check_at"] is None:
        return True
    return registry.utc_now_dt() >= _parse(state["next_check_at"])


def set_frequency(
    site_id: str,
    frequency_days: int,
    lake_area_change_threshold_pct: float | None = None,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    """`PUT /sites/{id}/recheck`: change the schedule, recomputing `next_check_at` from the last
    check (or now, if there hasn't been one) + the new `frequency_days`."""
    state = load(site_id, data_dir)
    state["frequency_days"] = frequency_days
    if lake_area_change_threshold_pct is not None:
        state["lake_area_change_threshold_pct"] = lake_area_change_threshold_pct
    anchor = _parse(state["last_checked_at"]) if state["last_checked_at"] else registry.utc_now_dt()
    state["next_check_at"] = (anchor + timedelta(days=frequency_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    save(site_id, state, data_dir)
    return state


def record_check(
    site_id: str,
    outdated: bool,
    status_reason_key: str | None,
    status_detail: dict | None,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    """A `recheck` job's `checking` stage calls this with its result. Always advances the
    schedule from now, regardless of outcome."""
    state = load(site_id, data_dir)
    now = registry.utc_now_dt()
    state["outdated"] = outdated
    state["status_reason_key"] = status_reason_key
    state["status_detail"] = status_detail
    state["last_checked_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    state["next_check_at"] = (now + timedelta(days=state["frequency_days"])).strftime("%Y-%m-%dT%H:%M:%SZ")
    save(site_id, state, data_dir)
    return state


def overlay(site_id: str, summary: dict[str, Any], data_dir: Path | None = None) -> dict[str, Any]:
    """Patch a mocked `SiteSummary`/list entry with this site's real re-check state."""
    state = load(site_id, data_dir)
    summary = dict(summary)
    summary["recheck"] = {
        "frequency_days": state["frequency_days"],
        "last_checked_at": state["last_checked_at"],
        "next_check_at": state["next_check_at"],
    }
    if state["outdated"]:
        summary["status"] = "outdated"
        summary["status_reason_key"] = state["status_reason_key"]
        summary["status_detail"] = state["status_detail"]
    return summary
