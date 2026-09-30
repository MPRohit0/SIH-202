"""Generate frontend/public/preview/teesta_real_gee_* (design/target-state-preview).

Teesta's "GEE-ready Monitoring" page in preview mode painted a single dry Point
(no lake outline at all), two empty imagery URLs (placeholder boxes), a
5-row synthetic lake-area series, and a single rainfall day -- instead of the
real M7 GEE cache this site already has on disk under data/teesta/gee/ (the
same cache main's live backend reads). This script takes a one-time static
snapshot of that real cache so preview mode can show it without depending on
a live backend at runtime (CLAUDE.md rule 11), the same pattern as
gen_real_teesta_preview_assets.py.

Run from the repo root with the project's own Python env (needs Pillow):
    .venv/bin/python frontend/scripts/gen_real_teesta_gee_preview_assets.py

Re-run whenever data/teesta/gee/ is refreshed. Outputs (checked into git):
    frontend/public/preview/teesta_real_lake_latest.geojson
    frontend/public/preview/teesta_real_gee_pre.png
    frontend/public/preview/teesta_real_gee_post.png
    frontend/public/preview/teesta_real_gee_series.json
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
GEE_DIR = REPO_ROOT / "data/teesta/gee"
OUT_DIR = REPO_ROOT / "frontend/public/preview"
THUMB_MAX_WIDTH = 480  # keeps these git-friendly (real satellite PNGs are 400 KB+ at full/fallback size)


def _read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _num(v: str | None) -> float | None:
    return float(v) if v not in (None, "") else None


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Real lake outline (MultiPolygon) -- minified, still ~100 KB of real geometry.
    lake_latest = json.loads((GEE_DIR / "lake_latest.geojson").read_text())
    (OUT_DIR / "teesta_real_lake_latest.geojson").write_text(json.dumps(lake_latest, separators=(",", ":")))

    # 2. Real pre/post imagery -- downscaled fallback screenshots (real satellite
    #    crops, not the oval placeholder the orphaned gee_teesta_*.png fixtures were).
    manifest = json.loads((GEE_DIR / "imagery/manifest.json").read_text())
    imagery_out = []
    for item in manifest["imagery"]:
        src = GEE_DIR / item["fallback_png"]
        with Image.open(src) as im:
            w, h = im.size
            if w > THUMB_MAX_WIDTH:
                scale = THUMB_MAX_WIDTH / w
                im = im.resize((THUMB_MAX_WIDTH, round(h * scale)), Image.LANCZOS)
            # JPEG, not PNG: this is photographic satellite content, where PNG's
            # lossless compression stays large (~400 KB at this size) but JPEG
            # at quality 78 is a fraction of that with no visible loss for a
            # thumbnail-sized preview.
            out_name = f"teesta_real_gee_{item['phase']}.jpg"
            im.convert("RGB").save(OUT_DIR / out_name, "JPEG", quality=78, optimize=True)
        imagery_out.append({"phase": item["phase"], "date": item["date"], "url": f"/preview/{out_name}",
                             "bounds_latlng": item["bounds_latlng"]})

    # 3. Real monthly lake-area + rainfall series (the same M7 cache main's
    #    /gee/{site_id} reads). No `source` field on any monthly row -- these
    #    are algorithmic per-scene readings, not a cited reference. Two extra
    #    rows are blended in at the exact dates of the separately-cited
    #    ISRO/NRSC figures (docs/data_sources.md src_072; also shown verbatim
    #    in app.tsx's hardcoded ISRO_SOUTH_LHONAK_REFERENCE panel) so those
    #    two points keep their real citation inside this table too, the way
    #    the previous 5-point demo series already (correctly) did.
    lake_area_series = [{"date": row["date"], "area_m2": _num(row["area_m2"]), "method": row["method"] or None,
                          "cloud_pct": _num(row["cloud_pct"]), "source": None} for row in _read_csv(GEE_DIR / "lake_area.csv")]
    isro_rows = [
        {"date": "2023-09-28", "area_m2": 1_674_000.0, "method": "isro_nrsc", "cloud_pct": None, "source": "src_072"},
        {"date": "2023-10-04", "area_m2": 603_000.0, "method": "isro_nrsc", "cloud_pct": None, "source": "src_072"},
    ]
    lake_area_series = sorted(lake_area_series + isro_rows, key=lambda r: r["date"])
    rainfall = [{"date": row["date"], "precip_mm": _num(row["precip_mm"]), "dataset": row["dataset"]}
                for row in _read_csv(GEE_DIR / "rainfall.csv")]
    gee_meta = json.loads((GEE_DIR / "gee_meta.json").read_text())

    (OUT_DIR / "teesta_real_gee_series.json").write_text(json.dumps({
        "source_cache": "data/teesta/gee (real M7 GEE cache)",
        "fetched_at": gee_meta["fetched_at"],
        "lake_area_series": lake_area_series,
        "rainfall": rainfall,
        "imagery": imagery_out,
    }, indent=2))
    print(f"wrote {OUT_DIR}: {len(lake_area_series)} lake-area points, {len(rainfall)} rainfall days, "
          f"{len(imagery_out)} imagery items")


if __name__ == "__main__":
    main()
