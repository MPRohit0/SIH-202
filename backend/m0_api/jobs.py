"""Job state machine and `jobs` table access (contract §4.5, §5.3).

Stages are the ones frozen in contract §5.3. `STAGES` is the only place they
are listed; `docs/decisions.md` Part 2 proposes different names, and adopting
that proposal would mean editing this table (after the contract change in §9).

A job moves only to the next stage in its list, or to `failed` from any stage
that is not terminal. Every write checks the stage it expects to replace
(`WHERE stage = ?`), so a stale writer cannot overwrite a newer stage.

Worker bookkeeping that §4.5 has no column for lives in `payload_json`:
`started_at`, `demo_mode`, `run_ids` and `events` (the recent messages shown
as `log_tail`).
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.m0_api import registry, runner

STAGES: dict[str, list[str]] = {
    "onboarding": ["queued", "terrain", "breach", "design", "simulating", "training", "validating", "ready"],
    "campaign": ["queued", "simulating", "postprocessing", "done"],
    "recheck": ["queued", "checking", "done"],
    # "rerun": contract §5.3 lists no stages for it yet (open gap, docs/progress.md).
}
TERMINAL = {"ready", "done", "failed"}
MAX_EVENTS = 20
LOG_TAIL_RUN_LINES = 5


class IllegalTransition(ValueError):
    """The requested stage change is not allowed by contract §5.3."""


class StaleStage(RuntimeError):
    """The job is no longer in the stage the caller expected."""


# --- pure rules --------------------------------------------------------------
def check_transition(kind: str, old: str, new: str) -> None:
    stages = STAGES.get(kind)
    if stages is None:
        raise IllegalTransition(f"job kind {kind!r} has no stages defined in contract §5.3")
    if old in TERMINAL:
        raise IllegalTransition(f"{kind} job is already {old!r}; it cannot move to {new!r}")
    if old not in stages:
        raise IllegalTransition(f"{old!r} is not a {kind} stage")
    if new == "failed":
        return
    i = stages.index(old)
    if i + 1 >= len(stages) or stages[i + 1] != new:
        raise IllegalTransition(f"{kind} job cannot go from {old!r} to {new!r}")


def next_stage(kind: str, stage: str) -> str:
    stages = STAGES[kind]
    return stages[stages.index(stage) + 1]


def new_job_id() -> str:
    """`job_<YYYYMMDDTHHMMSSZ>_<6 hex>` (contract §1.7)."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"job_{stamp}_{secrets.token_hex(3)}"


# --- database ----------------------------------------------------------------
def create_job(
    conn: sqlite3.Connection,
    kind: str,
    site_id: str,
    demo_mode: bool = False,
    payload: dict | None = None,
) -> str:
    """Insert a `queued` job and return its ID. Retries on the rare ID clash."""
    body = dict(payload or {})
    body.update({"demo_mode": demo_mode, "started_at": None, "run_ids": [], "events": []})
    now = registry.utc_now()
    for _ in range(10):
        job_id = new_job_id()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO jobs (job_id, kind, site_id, stage, payload_json, created_at, updated_at)"
                    " VALUES (?, ?, ?, 'queued', ?, ?, ?)",
                    (job_id, kind, site_id, json.dumps(body), now, now),
                )
            return job_id
        except sqlite3.IntegrityError:
            continue
    raise RuntimeError("could not generate a unique job_id after 10 tries")


def get_job(conn: sqlite3.Connection, job_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()


def payload(row: sqlite3.Row) -> dict:
    return json.loads(row["payload_json"])


def update_payload(conn: sqlite3.Connection, job_id: str, **fields: Any) -> None:
    with conn:
        row = get_job(conn, job_id)
        body = payload(row)
        body.update(fields)
        conn.execute(
            "UPDATE jobs SET payload_json = ?, updated_at = ? WHERE job_id = ?",
            (json.dumps(body), registry.utc_now(), job_id),
        )


def log_event(conn: sqlite3.Connection, job_id: str, message: str) -> None:
    body = payload(get_job(conn, job_id))
    events = (body.get("events", []) + [f"{registry.utc_now()} {message}"])[-MAX_EVENTS:]
    update_payload(conn, job_id, events=events)


def _write_stage(conn: sqlite3.Connection, job_id: str, old: str, new: str, error: dict | None) -> None:
    row = get_job(conn, job_id)
    if row is None:
        raise KeyError(job_id)
    check_transition(row["kind"], old, new)
    with conn:
        cur = conn.execute(
            "UPDATE jobs SET stage = ?, error = ?, updated_at = ? WHERE job_id = ? AND stage = ?",
            (new, json.dumps(error) if error else None, registry.utc_now(), job_id, old),
        )
    if cur.rowcount != 1:
        raise StaleStage(f"job {job_id} is not in stage {old!r}")


def set_stage(conn: sqlite3.Connection, job_id: str, old: str, new: str) -> None:
    """Move a job from `old` to `new`; raises IllegalTransition or StaleStage."""
    _write_stage(conn, job_id, old, new, None)
    log_event(conn, job_id, f"stage {old} -> {new}")


def fail(
    conn: sqlite3.Connection,
    job_id: str,
    old: str,
    code: str,
    message: str,
    details: dict | None = None,
) -> None:
    """Move a job to `failed` with a §2.7 error object. Progress stays frozen."""
    error = {"error": {"code": code, "message": message, "details": details or {}}}
    _write_stage(conn, job_id, old, "failed", error)
    log_event(conn, job_id, f"failed at {old}: {code}")


def set_progress(conn: sqlite3.Connection, job_id: str, current: int | None, total: int | None, unit: str | None) -> None:
    with conn:
        conn.execute(
            "UPDATE jobs SET progress_current = ?, progress_total = ?, progress_unit = ?, updated_at = ?"
            " WHERE job_id = ?",
            (current, total, unit, registry.utc_now(), job_id),
        )


def find_active_job(conn: sqlite3.Connection, site_id: str) -> str | None:
    """The oldest non-terminal job for a site, if any."""
    row = conn.execute(
        f"SELECT job_id FROM jobs WHERE site_id = ? AND stage NOT IN ({','.join('?' * len(TERMINAL))})"
        " ORDER BY created_at, job_id LIMIT 1",
        (site_id, *sorted(TERMINAL)),
    ).fetchone()
    return row["job_id"] if row else None


def job_runs(conn: sqlite3.Connection, row: sqlite3.Row) -> list[sqlite3.Row]:
    """The job's runs, in launch order (`run_ids` in the payload)."""
    run_ids = payload(row).get("run_ids", [])
    if not run_ids:
        return []
    by_id = {
        r["run_id"]: r
        for r in conn.execute(f"SELECT * FROM runs WHERE run_id IN ({','.join('?' * len(run_ids))})", run_ids)
    }
    return [by_id[r] for r in run_ids if r in by_id]


def _eta_s(stage: str, runs: list[sqlite3.Row]) -> float | None:
    """Mean wall time of finished runs × runs still to finish.

    `None` until at least one run has finished: there is no basis for an
    estimate before that, and the UI says so instead of showing a guess.
    """
    if stage != "simulating":
        return None
    walls = [json.loads(r["meta_json"] or "{}").get("wall_time_s") for r in runs if r["status"] == "completed"]
    walls = [w for w in walls if w is not None]
    if not walls:
        return None
    remaining = sum(r["status"] != "completed" for r in runs)
    return round(sum(walls) / len(walls) * remaining, 1)


def job_status(conn: sqlite3.Connection, job_id: str) -> dict | None:
    """The contract §5.3 `JobStatus` for a job, or None if it doesn't exist."""
    row = get_job(conn, job_id)
    if row is None:
        return None
    body = payload(row)
    runs = job_runs(conn, row)
    log_tail = list(body.get("events", []))
    running = [r for r in runs if r["status"] == "running"]
    if running:
        log_tail += runner.tail(runner.log_path(running[0]["run_dir"]), LOG_TAIL_RUN_LINES)
    return {
        "job_id": row["job_id"],
        "kind": row["kind"],
        "site_id": row["site_id"],
        "stage": row["stage"],
        "stage_label_key": f"job_stage_{row['stage']}",
        "progress": {
            "current": row["progress_current"],
            "total": row["progress_total"],
            "unit": row["progress_unit"],
        },
        "eta_s": _eta_s(row["stage"], runs),
        "demo_mode": bool(body.get("demo_mode", False)),
        "started_at": body.get("started_at"),
        "updated_at": row["updated_at"],
        "log_tail": log_tail,
        "error": json.loads(row["error"]) if row["error"] else None,
    }


def run_dir(site_id: str, run_id: str) -> Path:
    """`data/<site_id>/runs/<run_id>/` (contract §1.8)."""
    return registry.data_dir() / site_id / "runs" / run_id
