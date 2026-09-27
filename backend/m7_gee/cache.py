"""`data/<site_id>/gee/` cache helpers (contract §4.8): atomic writes, merging new `lake_area.csv`
rows with what is already on disk (so a re-run doesn't refetch finished past months), and reading
everything back as a `GeeLayers` payload (contract §5.8) for M0 to serve.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

CONTRACT_VERSION = "0.3.0"
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"

LAKE_AREA_FIELDS = ["date", "area_m2", "method", "cloud_pct", "scene_ids"]
RAINFALL_FIELDS = ["date", "precip_mm", "dataset", "aggregation"]


def gee_dir(site_id: str, data_dir: str | Path = DATA_DIR) -> Path:
    return Path(data_dir) / site_id / "gee"


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    lines = [",".join(fields)]
    for row in rows:
        lines.append(",".join("" if row.get(f) is None else str(row[f]) for f in fields))
    _atomic_write_text(path, "\n".join(lines) + "\n")


def _read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def read_lake_area(site_id: str, data_dir: str | Path = DATA_DIR) -> list[dict]:
    rows = _read_csv(gee_dir(site_id, data_dir) / "lake_area.csv")
    for r in rows:
        r["area_m2"] = float(r["area_m2"]) if r.get("area_m2") not in (None, "") else None
        r["cloud_pct"] = float(r["cloud_pct"]) if r.get("cloud_pct") not in (None, "") else None
        r["method"] = r["method"] or None
    return rows


def merge_lake_rows(cached: list[dict], fresh: list[dict]) -> list[dict]:
    """Fresh rows replace cached rows for the same `date`; everything else in the cache is kept.
    A caller only needs to fetch the months it doesn't already have plus the current/latest month
    (which can still change), and this still produces the full series."""
    by_date = {r["date"]: r for r in cached}
    for r in fresh:
        by_date[r["date"]] = r
    return sorted(by_date.values(), key=lambda r: r["date"])


def write_lake_area(site_id: str, rows: list[dict], data_dir: str | Path = DATA_DIR) -> Path:
    path = gee_dir(site_id, data_dir) / "lake_area.csv"
    _write_csv(path, rows, LAKE_AREA_FIELDS)
    return path


def write_rainfall(site_id: str, rows: list[dict], data_dir: str | Path = DATA_DIR) -> Path:
    path = gee_dir(site_id, data_dir) / "rainfall.csv"
    _write_csv(path, rows, RAINFALL_FIELDS)
    return path


def read_rainfall(site_id: str, data_dir: str | Path = DATA_DIR) -> list[dict]:
    rows = _read_csv(gee_dir(site_id, data_dir) / "rainfall.csv")
    for r in rows:
        r["precip_mm"] = float(r["precip_mm"]) if r.get("precip_mm") not in (None, "") else None
    return rows


def write_lake_latest(site_id: str, feature: dict, data_dir: str | Path = DATA_DIR) -> Path:
    path = gee_dir(site_id, data_dir) / "lake_latest.geojson"
    fc = {"type": "FeatureCollection", "features": [feature] if feature else []}
    _atomic_write_text(path, json.dumps(fc, indent=2) + "\n")
    return path


def read_lake_latest(site_id: str, data_dir: str | Path = DATA_DIR) -> dict:
    path = gee_dir(site_id, data_dir) / "lake_latest.geojson"
    if not path.is_file():
        return {"type": "FeatureCollection", "features": []}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(site_id: str, name: str, payload: dict, data_dir: str | Path = DATA_DIR) -> Path:
    path = gee_dir(site_id, data_dir) / name
    _atomic_write_text(path, json.dumps(payload, indent=2) + "\n")
    return path


def read_json(site_id: str, name: str, data_dir: str | Path = DATA_DIR) -> dict | None:
    path = gee_dir(site_id, data_dir) / name
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def fallback_screenshots(site_id: str, data_dir: str | Path = DATA_DIR) -> list[str]:
    fallback_dir = gee_dir(site_id, data_dir) / "fallback"
    if not fallback_dir.is_dir():
        return []
    return sorted(str(p) for p in fallback_dir.glob("*.png"))


def read_imagery(site_id: str, data_dir: str | Path = DATA_DIR) -> list[dict]:
    """`GeeLayers.imagery` entries (contract §5.8) built from `imagery.py`'s
    `gee/imagery/manifest.json`, or `[]` if imagery hasn't been converted for this site yet."""
    manifest = read_json(site_id, "imagery/manifest.json", data_dir)
    if not manifest:
        return []
    return [
        {
            "event_id": e["event_id"], "phase": e["phase"], "date": e["date"],
            "url": f"/api/v1/files/{site_id}/gee/{e['png']}",
            "fallback_url": f"/api/v1/files/{site_id}/gee/{e['fallback_png']}",
            "bounds_latlng": e["bounds_latlng"],
        }
        for e in manifest.get("imagery", [])
    ]


def read_observed_extents(site_id: str, data_dir: str | Path = DATA_DIR) -> list[dict]:
    """`GeeLayers.observed_extents` entries (contract §5.8) built from every
    `gee/observed/<event_id>_observed.geojson` file (`observed.convert`), or `[]` if none has been
    digitized for this site yet."""
    observed_dir = gee_dir(site_id, data_dir) / "observed"
    if not observed_dir.is_dir():
        return []
    out = []
    for path in sorted(observed_dir.glob("*_observed.geojson")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        features = payload.get("features", [])
        if not features:
            continue
        props = features[0].get("properties", {})
        out.append({
            "event_id": props.get("event_id"),
            "url": f"/api/v1/files/{site_id}/gee/observed/{path.name}",
            "method": props.get("method"),
        })
    return out


def load_layers(site_id: str, data_dir: str | Path = DATA_DIR) -> dict:
    """Everything on disk assembled into a `GeeLayers` payload (contract §5.8), for M0 to serve
    from `GET /gee/{site_id}`. `source` is `cache` unless only screenshot fallbacks exist and no
    real lake-area data was ever fetched, in which case it is `screenshot_fallback` (contract §4.8
    `fallback/*.png`, "screenshots used if live and cache both fail")."""
    meta = read_json(site_id, "gee_meta.json", data_dir) or {}
    lake_area_rows = read_lake_area(site_id, data_dir)
    rainfall_rows = read_rainfall(site_id, data_dir)
    recheck = read_json(site_id, "recheck.json", data_dir) or {"outdated": False, "change_pct": None,
                                                                 "threshold_pct": None}

    source = "cache" if lake_area_rows else ("screenshot_fallback" if fallback_screenshots(site_id, data_dir) else "cache")

    return {
        "site_id": site_id,
        "source": source,
        "fetched_at": meta.get("fetched_at"),
        "lake_area_series": [
            {"date": r["date"], "area_m2": r["area_m2"], "method": r["method"], "cloud_pct": r["cloud_pct"]}
            for r in lake_area_rows
        ],
        "lake_latest": read_lake_latest(site_id, data_dir),
        "rainfall": [
            {"date": r["date"], "precip_mm": r["precip_mm"], "dataset": r["dataset"]} for r in rainfall_rows
        ],
        "imagery": read_imagery(site_id, data_dir),
        "observed_extents": read_observed_extents(site_id, data_dir),
        "recheck": {"outdated": recheck.get("outdated", False), "change_pct": recheck.get("change_pct"),
                     "threshold_pct": recheck.get("threshold_pct")},
    }
