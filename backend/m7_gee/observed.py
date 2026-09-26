"""M7 observed flood extent (contract §4.8 `observed/<event_id>_observed.geojson`) -- a
hand-digitized (or change-detection) flood outline an operator supplies, not something fetched
from Earth Engine.

Stamps the operator's GeoJSON (already in EPSG:4326, per contract §1.7/§4.8) with the required
properties (`event_id, method, imagery_ref, digitized_by, date, kind: observed`) and writes it to
`data/<site_id>/gee/observed/<event_id>_observed.geojson`. `cache.read_observed_extents()`/
`load_layers()` read every file in that directory into `GeeLayers.observed_extents` (contract
§5.8: `{event_id, url, method}`). This layer is for validation only (`docs/handoff_contract.md`
§5.7 `GET /validation/{site_id}?event=`) -- it is never used as a model input.

CLI: `python -m backend.m7_gee.observed <site_id> <event_id> <source_geojson> --digitized-by NAME
[--method manual_digitized|change_detection] [--imagery-ref REF] [--date YYYY-MM-DD]
[--data-dir DIR]`
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Literal

from backend.shared.site_config import SiteConfig, load_site_config

from . import cache

log = logging.getLogger("m7.observed")

Method = Literal["manual_digitized", "change_detection"]


def _event(cfg: SiteConfig, event_id: str):
    for ev in cfg.events:
        if ev.id == event_id:
            return ev
    raise ValueError(f"site '{cfg.site.id}' has no event '{event_id}'")


def convert(
    site_id: str,
    event_id: str,
    source_path: str | Path,
    digitized_by: str,
    method: Method = "manual_digitized",
    imagery_ref: str | None = None,
    date: str | None = None,
    cfg: SiteConfig | None = None,
    data_dir: str | Path = cache.DATA_DIR,
) -> Path:
    """Reads the operator's GeoJSON at `source_path`, stamps contract properties onto every
    feature, and writes `data/<site_id>/gee/observed/<event_id>_observed.geojson`. Raises
    `FileNotFoundError` if `source_path` doesn't exist, `ValueError` if it isn't a GeoJSON
    Feature/FeatureCollection or the site has no event `event_id`. `date` defaults to the event's
    `onset` date; `imagery_ref` defaults to `<event_id>_post` (the post-event imagery it was
    digitized against, per contract §4.8's `imagery_ref` field)."""
    cfg = cfg or load_site_config(site_id)
    event = _event(cfg, event_id)
    source_path = Path(source_path)
    if not source_path.is_file():
        raise FileNotFoundError(f"missing observed-extent GeoJSON: '{source_path}'")

    raw = json.loads(source_path.read_text(encoding="utf-8"))
    if raw.get("type") not in ("Feature", "FeatureCollection"):
        raise ValueError(f"'{source_path}' is not a GeoJSON Feature or FeatureCollection")
    features = raw["features"] if raw["type"] == "FeatureCollection" else [raw]
    if not features:
        raise ValueError(f"'{source_path}' has no features")

    date_str = date or str(event.onset.value)[:10]
    props = {
        "event_id": event_id, "method": method,
        "imagery_ref": imagery_ref or f"{event_id}_post",
        "digitized_by": digitized_by, "date": date_str, "kind": "observed",
    }
    for feature in features:
        feature.setdefault("properties", {})
        feature["properties"].update(props)

    out = {"type": "FeatureCollection", "features": features}
    return cache.write_json(site_id, f"observed/{event_id}_observed.geojson", out, data_dir)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("site_id")
    parser.add_argument("event_id")
    parser.add_argument("source_geojson", type=Path)
    parser.add_argument("--digitized-by", required=True)
    parser.add_argument("--method", choices=["manual_digitized", "change_detection"],
                         default="manual_digitized")
    parser.add_argument("--imagery-ref", default=None)
    parser.add_argument("--date", default=None)
    parser.add_argument("--data-dir", type=Path, default=cache.DATA_DIR)
    args = parser.parse_args(argv)

    try:
        out_path = convert(
            args.site_id, args.event_id, args.source_geojson, args.digitized_by,
            method=args.method, imagery_ref=args.imagery_ref, date=args.date, data_dir=args.data_dir,
        )
    except (FileNotFoundError, ValueError) as e:
        log.error(str(e))
        return 1
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
