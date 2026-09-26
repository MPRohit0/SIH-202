"""Library-outdated re-check (contract §4.8 `recheck.json`, `docs/decisions.md`
"outdated_lake_area_change"). Pure logic over already-fetched numbers -- no Earth Engine calls.

`reference_area_m2` is "the lake area when the library was trained" (contract §4.8): the latest
`lake_area.csv` row dated on or before the emulator's `manifest.json` `trained_at`
(`backend/m5_emulator/emulator.py`), so the comparison is against what the emulator actually saw,
not today's area against some other arbitrary baseline.
"""

from __future__ import annotations

from datetime import date, datetime, timezone


def _as_date(d: str | date) -> date:
    return d if isinstance(d, date) else datetime.fromisoformat(d).date()


def reference_area(series: list[dict], trained_at: str) -> float | None:
    """The latest `lake_area.csv` row's `area_m2` dated on or before `trained_at` (any ISO 8601
    date/datetime). `None` if the series has no row that old (e.g. the library predates the fetch
    history, or every candidate row was a skipped month)."""
    cutoff = _as_date(trained_at)
    candidates = [r for r in series if r.get("area_m2") is not None and _as_date(r["date"]) <= cutoff]
    if not candidates:
        return None
    return float(max(candidates, key=lambda r: _as_date(r["date"]))["area_m2"])


def compute_recheck(
    site_id: str,
    latest_area_m2: float | None,
    reference_area_m2: float | None,
    threshold_pct: float,
    checked_at: str | None = None,
) -> dict:
    """Build the `recheck.json` payload (contract §4.8 fields exactly)."""
    checked_at = checked_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if latest_area_m2 is None:
        return {"site_id": site_id, "checked_at": checked_at, "latest_area_m2": None,
                "reference_area_m2": reference_area_m2, "change_pct": None,
                "threshold_pct": threshold_pct, "outdated": False, "reason": "no_lake_area_data"}
    if reference_area_m2 is None:
        return {"site_id": site_id, "checked_at": checked_at, "latest_area_m2": latest_area_m2,
                "reference_area_m2": None, "change_pct": None, "threshold_pct": threshold_pct,
                "outdated": False, "reason": "no_trained_library"}

    change_pct = 100.0 * (latest_area_m2 - reference_area_m2) / reference_area_m2
    outdated = abs(change_pct) >= threshold_pct
    return {"site_id": site_id, "checked_at": checked_at, "latest_area_m2": latest_area_m2,
            "reference_area_m2": reference_area_m2, "change_pct": change_pct,
            "threshold_pct": threshold_pct, "outdated": outdated,
            "reason": "outdated_lake_area_change" if outdated else "within_threshold"}
