"""M0 job worker: a separate process that moves jobs through their stages.

    python -m backend.m0_api.worker            # alongside `uvicorn backend.m0_api.main:app`

The API only creates jobs and reads their status from `data/registry.sqlite`.
This process does the work, one job at a time (oldest first):

- **In-process stages** (`terrain`, `breach`, `design`, `training`,
  `validating`, `postprocessing`) are FAKE for now. Each sleeps
  `SIH26_FAKE_STAGE_S` seconds and then advances. M1, M2 and M5 plug in here later.
- **`simulating`** registers the job's runs, then launches them ONE AT A TIME
  (CLAUDE.md rule 13) as detached processes (rule 14). Each tick reads the
  running run's `log.txt`. The solver is currently `backend.m0_api.fake_solver`;
  the number of runs (`SIH26_FAKE_N_RUNS`) and its timings are fake settings,
  not design choices.
- **`recheck`'s `checking` stage is real**: it runs M7's lake-area check
  (`backend.m7_gee.fetch.run`) plus a library-age check against
  `site_status.DEFAULT_MAX_LIBRARY_AGE_DAYS`, and records the result in
  `data/<site_id>/site_status.json` (`_run_recheck`). Every tick, `_schedule_rechecks()`
  queues a `recheck` job for any known site whose `site_status` schedule is due and has
  no active job -- there is no separate timer/cron.

`tick()` does one short, non-blocking step. A long run is never waited on; it
is polled on the next tick. Because all state lives in SQLite and the run
logs, the API and the worker can each be restarted independently.
`recover()` runs at start-up and reconciles runs that were `running` when the
previous worker stopped. There are no retries yet: `max_run_retries` is still
unset in docs/decisions.md.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime

from backend.m0_api import jobs, registry, runner, site_status
from backend.m7_gee import fetch as gee_fetch

log = logging.getLogger("m0.worker")

SIM_STAGES = {"simulating"}

#: Sites the scheduler considers for re-checks. Matches `mocks.KNOWN_SITE_IDS` -- kept as a
#: separate constant so the worker doesn't import the API's mock layer for a list of site ids.
KNOWN_SITE_IDS = ("teesta", "rishiganga")


class WorkerAlreadyRunning(RuntimeError):
    """Another worker holds `data/worker.lock`."""


def _env_float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


class Worker:
    def __init__(self) -> None:
        self.conn: sqlite3.Connection = registry.connect()
        self._lock_file = None
        self._procs: dict[str, subprocess.Popen] = {}  # runs this worker launched, so it can reap them

    # --- lifecycle -----------------------------------------------------------
    def acquire_lock(self) -> None:
        path = registry.data_dir() / "worker.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        f = open(path, "w")
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            f.close()
            raise WorkerAlreadyRunning(f"another worker holds {path}") from None
        f.write(str(os.getpid()))
        f.flush()
        self._lock_file = f

    def close(self) -> None:
        """Stop tracking everything. Detached runs keep going."""
        if self._lock_file is not None:
            fcntl.flock(self._lock_file, fcntl.LOCK_UN)
            self._lock_file.close()
            self._lock_file = None
        self.conn.close()

    def recover(self) -> None:
        """Reconcile state left behind by a previous worker.

        - A job in an in-process stage needs nothing: the next tick re-runs
          that stage from the start. The fake tasks are idempotent.
        - A run marked `running`: if its log says DONE, record the outcome.
          If the process is still alive, re-attach (later ticks keep polling).
          Otherwise it died unobserved, so the job fails with `worker_lost_run`.
        """
        for row in self._active_jobs():
            if row["stage"] == "queued":
                continue
            jobs.log_event(self.conn, row["job_id"], f"worker restarted; resuming at {row['stage']}")
            for run in jobs.job_runs(self.conn, row):
                if run["status"] != "running":
                    continue
                pid = json.loads(run["meta_json"] or "{}").get("pid")
                alive = pid is not None and runner.is_alive(pid, run["run_id"])
                progress = runner.read_progress(runner.log_path(run["run_dir"]))
                if progress.finished:
                    self._finish_run(row, run, progress.ok)
                elif alive:
                    jobs.log_event(self.conn, row["job_id"], f"re-attached to run {run['run_id']} (pid {pid})")
                else:
                    self._mark_run(run["run_id"], "failed", error="process gone without DONE line")
                    jobs.fail(
                        self.conn, row["job_id"], row["stage"], "worker_lost_run",
                        f"Run {run['run_id']} stopped while no worker was watching it.",
                        {"run_id": run["run_id"], "pid": pid},
                    )

    def run_forever(self, poll_s: float = 1.0) -> None:
        self.acquire_lock()
        self.recover()
        log.info("worker started (pid %s), registry %s", os.getpid(), registry.db_path())
        while True:
            if not self.tick():
                time.sleep(poll_s)

    # --- one step ------------------------------------------------------------
    def tick(self) -> bool:
        """Advance the oldest active job by one step. Returns False when there
        was nothing to do (idle, or only waiting on a running solver)."""
        self._reap()
        scheduled = self._schedule_rechecks()
        active = self._active_jobs()
        if not active:
            return scheduled
        row = active[0]
        kind, stage, job_id = row["kind"], row["stage"], row["job_id"]
        if kind not in jobs.STAGES:
            jobs.fail(self.conn, job_id, stage, "unsupported_job_kind",
                      f"Job kind {kind!r} has no stages in contract §5.3 yet.")
            return True

        if stage == "queued":
            jobs.update_payload(self.conn, job_id, started_at=registry.utc_now())
            self._advance(row)
            return True
        if stage in SIM_STAGES:
            return self._tick_simulating(row)
        if kind == "recheck" and stage == "checking":
            self._run_recheck(row)
            self._advance(row)
            return True

        time.sleep(_env_float("SIH26_FAKE_STAGE_S", 3.0))  # FAKE stage work
        self._advance(row)
        return True

    # --- scheduled re-checks ---------------------------------------------------
    def _has_published_library(self, site_id: str) -> bool:
        """A re-check only makes sense once there is a library to go stale (docs/decisions.md
        2.1/2.3: `outdated` applies to a site whose job already reached `ready`)."""
        data_dir = registry.data_dir()
        return any((data_dir / site_id / "emulator" / model / "manifest.json").is_file()
                   for model in ("delft3d", "sph"))

    def _schedule_rechecks(self) -> bool:
        """Queue a `recheck` job for every known site whose schedule is due (or has never been
        checked) and that has no active job already. Runs every tick; cheap (a handful of file
        stats), so no separate timer is needed."""
        queued_any = False
        for site_id in KNOWN_SITE_IDS:
            if jobs.find_active_job(self.conn, site_id) is not None:
                continue
            if not self._has_published_library(site_id):
                continue
            if not site_status.is_due(site_status.load(site_id)):
                continue
            job_id = jobs.create_job(self.conn, "recheck", site_id)
            jobs.log_event(self.conn, job_id, f"scheduled re-check for '{site_id}'")
            queued_any = True
        return queued_any

    def _run_recheck(self, row: sqlite3.Row) -> None:
        """The `checking` stage's real work: M7's lake-area check plus a library-age check.
        Never raises -- a re-check that can't complete this tick (e.g. Earth Engine and cache both
        unavailable) just leaves the site's outdated flag as it was and tries again next schedule."""
        site_id, job_id = row["site_id"], row["job_id"]
        data_dir = registry.data_dir()
        outdated, reason_key, detail = False, None, None

        try:
            provider = gee_fetch.best_effort_provider()
            gee_fetch.run(site_id, provider=provider, data_dir=data_dir)
            recheck = json.loads((data_dir / site_id / "gee" / "recheck.json").read_text())
            if recheck.get("outdated"):
                outdated, reason_key = True, "outdated_lake_area_change"
                detail = {"change_pct": recheck["change_pct"], "threshold_pct": recheck["threshold_pct"],
                          "checked_at": recheck["checked_at"]}
        except Exception as e:
            jobs.log_event(self.conn, job_id, f"lake-area check failed, skipping: {e}")

        if not outdated:
            for model in ("delft3d", "sph"):
                manifest_path = data_dir / site_id / "emulator" / model / "manifest.json"
                if not manifest_path.is_file():
                    continue
                trained_at = datetime.fromisoformat(
                    json.loads(manifest_path.read_text())["trained_at"].replace("Z", "+00:00")
                )
                age_days = (registry.utc_now_dt() - trained_at).total_seconds() / 86400.0
                if age_days > site_status.DEFAULT_MAX_LIBRARY_AGE_DAYS:
                    outdated, reason_key = True, "outdated_library_age"
                    detail = {"trained_at": json.loads(manifest_path.read_text())["trained_at"],
                              "age_days": round(age_days, 1),
                              "max_age_days": site_status.DEFAULT_MAX_LIBRARY_AGE_DAYS}
                    break

        site_status.record_check(site_id, outdated, reason_key, detail, data_dir=data_dir)
        jobs.log_event(self.conn, job_id, f"re-check done: outdated={outdated} reason={reason_key}")

    # --- simulating ----------------------------------------------------------
    def _tick_simulating(self, row: sqlite3.Row) -> bool:
        job_id = row["job_id"]
        if not jobs.payload(row).get("run_ids"):
            self._register_runs(row)
            return True
        row = jobs.get_job(self.conn, job_id)
        runs = jobs.job_runs(self.conn, row)

        running = [r for r in runs if r["status"] == "running"]
        if running:
            return self._poll_run(row, running[0])

        queued = [r for r in runs if r["status"] == "queued"]
        if queued:
            self._launch(row, queued[0])
            return True

        self._advance(row)  # every run completed (a failed run already failed the job)
        return True

    def _register_runs(self, row: sqlite3.Row) -> None:
        """Create the job's scenarios + runs in the registry (FAKE design: no params)."""
        site_id, job_id = row["site_id"], row["job_id"]
        demo = bool(jobs.payload(row).get("demo_mode"))
        kind, prefix = ("demo", f"{site_id}_demo_s") if demo else ("design", f"{site_id}_s")
        n_existing = self.conn.execute(
            "SELECT COUNT(*) FROM scenarios WHERE site_id = ? AND kind = ?", (site_id, kind)
        ).fetchone()[0]
        n = _env_int("SIH26_FAKE_N_RUNS", 3)
        now = registry.utc_now()
        run_ids = []
        with self.conn:
            for i in range(n_existing + 1, n_existing + n + 1):
                scenario_id = f"{prefix}{i:03d}"  # contract §1.7; numbers are never reused
                run_id = f"{scenario_id}__delft3d"
                self.conn.execute(
                    "INSERT INTO scenarios (scenario_id, site_id, kind, params_json, created_at) VALUES (?, ?, ?, ?, ?)",
                    (scenario_id, site_id, kind, json.dumps({"fake": True}), now),
                )
                self.conn.execute(
                    "INSERT INTO runs (run_id, scenario_id, model, status, run_dir) VALUES (?, ?, 'delft3d', 'queued', ?)",
                    (run_id, scenario_id, str(jobs.run_dir(site_id, run_id))),
                )
                run_ids.append(run_id)
        jobs.update_payload(self.conn, job_id, run_ids=run_ids)
        jobs.set_progress(self.conn, job_id, 0, n, "runs")
        jobs.log_event(self.conn, job_id, f"registered {n} runs")

    def _launch(self, row: sqlite3.Row, run: sqlite3.Row) -> None:
        run_id = run["run_id"]
        index = jobs.payload(row)["run_ids"].index(run_id) + 1
        cmd = [
            sys.executable, "-m", "backend.m0_api.fake_solver",
            "--run-id", run_id,
            "--steps", str(_env_int("SIH26_FAKE_RUN_STEPS", 5)),
            "--step-s", str(_env_float("SIH26_FAKE_RUN_STEP_S", 2.0)),
        ]
        if os.environ.get("SIH26_FAKE_FAIL_RUN") == str(index):  # test hook: make run N fail
            cmd += ["--fail-at", "1"]
        env = dict(os.environ, PYTHONPATH=os.pathsep.join(filter(None, [str(registry.REPO_ROOT), os.environ.get("PYTHONPATH")])))
        proc = runner.launch_detached(cmd, run["run_dir"], env=env)
        self._procs[run_id] = proc
        started = time.time()
        self._mark_run(run_id, "running", meta={"pid": proc.pid, "started_epoch_s": started}, started_at=registry.utc_now())
        jobs.log_event(self.conn, row["job_id"], f"run {run_id} started (pid {proc.pid})")

    def _poll_run(self, row: sqlite3.Row, run: sqlite3.Row) -> bool:
        pid = json.loads(run["meta_json"] or "{}").get("pid")
        alive = pid is not None and runner.is_alive(pid, run["run_id"])  # check before reading the log (no race)
        progress = runner.read_progress(runner.log_path(run["run_dir"]))
        if progress.finished:
            self._finish_run(row, run, progress.ok)
            return True
        if not alive:
            self._mark_run(run["run_id"], "failed", error="process exited without DONE line")
            jobs.fail(self.conn, row["job_id"], row["stage"], "run_failed",
                      f"Run {run['run_id']} exited without finishing.", {"run_id": run["run_id"]})
            return True
        return False  # still running; nothing changed

    def _finish_run(self, row: sqlite3.Row, run: sqlite3.Row, ok: bool) -> None:
        meta = json.loads(run["meta_json"] or "{}")
        if "started_epoch_s" in meta:
            meta["wall_time_s"] = round(time.time() - meta["started_epoch_s"], 3)
        job_id = row["job_id"]
        if ok:
            self._mark_run(run["run_id"], "completed", meta=meta, finished_at=registry.utc_now())
            completed = sum(r["status"] == "completed" for r in jobs.job_runs(self.conn, jobs.get_job(self.conn, job_id)))
            jobs.set_progress(self.conn, job_id, completed, row["progress_total"], "runs")
            jobs.log_event(self.conn, job_id, f"run {run['run_id']} completed")
        else:
            self._mark_run(run["run_id"], "failed", meta=meta, finished_at=registry.utc_now(), error="solver reported failure")
            jobs.fail(self.conn, job_id, row["stage"], "run_failed",
                      f"Run {run['run_id']} reported failure.", {"run_id": run["run_id"]})

    # --- helpers -------------------------------------------------------------
    def _active_jobs(self) -> list[sqlite3.Row]:
        terminal = sorted(jobs.TERMINAL)
        return self.conn.execute(
            f"SELECT * FROM jobs WHERE stage NOT IN ({','.join('?' * len(terminal))}) ORDER BY created_at, job_id",
            terminal,
        ).fetchall()

    def _advance(self, row: sqlite3.Row) -> None:
        new = jobs.next_stage(row["kind"], row["stage"])
        jobs.set_stage(self.conn, row["job_id"], row["stage"], new)
        if row["stage"] in SIM_STAGES:  # run counts describe `simulating` only
            jobs.set_progress(self.conn, row["job_id"], None, None, None)
        if new in SIM_STAGES:  # so `simulating` never shows without its 0/N
            self._register_runs(jobs.get_job(self.conn, row["job_id"]))
        log.info("job %s: %s -> %s", row["job_id"], row["stage"], new)

    def _mark_run(self, run_id: str, status: str, meta: dict | None = None, started_at: str | None = None,
                  finished_at: str | None = None, error: str | None = None) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE runs SET status = ?,"
                " meta_json = COALESCE(?, meta_json), started_at = COALESCE(?, started_at),"
                " finished_at = COALESCE(?, finished_at), error = COALESCE(?, error)"
                " WHERE run_id = ?",
                (status, json.dumps(meta) if meta is not None else None, started_at, finished_at, error, run_id),
            )

    def _reap(self) -> None:
        """Collect exit codes of runs this worker launched, so they don't linger as zombies."""
        for run_id, proc in list(self._procs.items()):
            if proc.poll() is not None:
                del self._procs[run_id]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M0 job worker")
    parser.add_argument("--poll-s", type=float, default=1.0, help="sleep between idle ticks")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    try:
        Worker().run_forever(args.poll_s)
    except WorkerAlreadyRunning as exc:
        log.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        log.info("worker stopped; detached runs keep going and will be picked up on restart")
    return 0


if __name__ == "__main__":
    sys.exit(main())
