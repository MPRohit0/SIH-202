"""The registry: `data/registry.sqlite` (contract §1.8, §4.5).

Shared by the API process and the worker process, so it runs in WAL mode with a
busy timeout: each process can read while the other writes. The four tables
use exactly the §4.5 columns. Anything the worker needs that §4.5 has no column
for is kept in `jobs.payload_json` or `runs.meta_json`, so the contract stays
unchanged.

`SIH26_DATA_DIR` overrides the data folder (tests point it at a temp dir).
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS scenarios (
    scenario_id TEXT PRIMARY KEY,
    site_id     TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('design', 'historical', 'demo', 'named')),
    params_json TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL,
    model       TEXT NOT NULL CHECK (model IN ('delft3d', 'sph')),
    status      TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'postprocessed', 'failed')),
    run_dir     TEXT NOT NULL,
    meta_json   TEXT,
    started_at  TEXT,
    finished_at TEXT,
    error       TEXT
);
CREATE TABLE IF NOT EXISTS jobs (
    job_id           TEXT PRIMARY KEY,
    kind             TEXT NOT NULL CHECK (kind IN ('onboarding', 'campaign', 'recheck', 'rerun')),
    site_id          TEXT NOT NULL,
    stage            TEXT NOT NULL,
    progress_current INTEGER,
    progress_total   INTEGER,
    progress_unit    TEXT,
    eta_s            REAL,
    payload_json     TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    error            TEXT
);
CREATE TABLE IF NOT EXISTS queries (
    query_id     TEXT PRIMARY KEY,
    site_id      TEXT NOT NULL,
    request_json TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('partial', 'complete', 'failed')),
    result_path  TEXT,
    created_at   TEXT NOT NULL
);
"""

_initialised: set[Path] = set()


def data_dir() -> Path:
    return Path(os.environ.get("SIH26_DATA_DIR", REPO_ROOT / "data"))


def db_path() -> Path:
    return data_dir() / "registry.sqlite"


def utc_now() -> str:
    """ISO 8601 UTC timestamp with `Z`, to the second (contract §1.2)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect() -> sqlite3.Connection:
    """Open the registry, creating the file and tables on first use."""
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    if path not in _initialised:
        conn.executescript(SCHEMA_SQL)
        _initialised.add(path)
    return conn


def init_db() -> None:
    """Create the registry tables if they don't exist yet."""
    path = db_path()
    _initialised.discard(path)
    connect().close()
