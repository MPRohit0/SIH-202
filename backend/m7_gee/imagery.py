"""M7 GEE event imagery (contract §4.8 `imagery/<event_id>_<pre|post>_<date>.png`).

Converts the pre-/post-event RGB GeoTIFFs an operator has already staged (referenced by
`sites/<site_id>.yaml` `events[].imagery_pre_event/imagery_post_event.source`, a repo-root-relative
path such as `cache/gee/teesta/teesta_pre_event.tif` -> its `..._rgb.tif` sibling) into
`data/<site_id>/gee/imagery/`: a full-resolution PNG, a small fallback PNG (<= `FALLBACK_MAX_PX` on
the long side, for slow connections), and a `manifest.json` recording each PNG's EPSG:4326 bounds
so the frontend can place it on the Leaflet map without re-reading the GeoTIFF.
`cache.load_layers()` reads the manifest to fill `GeeLayers.imagery` (contract §5.8).

Also supports a live refresh: `refresh(site_id)` tries to re-render the same pre-/post-event
composites from Earth Engine (needs `GEE_SERVICE_ACCOUNT_EMAIL` / `GEE_SERVICE_ACCOUNT_KEY_PATH`
in `.env`, or `earthengine authenticate`), overwriting the staged `_rgb.tif` files before
reconverting. Any failure (no credentials, no network, no scene near the date) is caught and the
existing on-disk PNGs are kept -- contract §4.8 "fallback/*.png ... if live and cache both fail".

`convert()` optionally takes the scene IDs the staged GeoTIFFs were exported from (there is nowhere
in `sites/<site_id>.yaml`'s `Event` to record them -- `imagery_pre_event`/`imagery_post_event` only
carry a date + file path, and `additionalProperties: false` on that schema object means adding a
field there is a contract change, not a code one). When given, they are merged into `gee_meta.json`
under an `"imagery"` entry, alongside the `lake_area`/`lake_latest`/`rainfall` entries `fetch.py`
already writes there (contract §4.8: `gee_meta.json` is "per product: dataset, scene_ids,
acquisition_dates, cloud_pct, fetched_at, source").

CLI: `python -m backend.m7_gee.imagery <site_id> [--data-dir DIR] [--refresh] [--ee-project PROJECT]
[--pre-scene-id ID ...] [--post-scene-id ID ...]`
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import transform_bounds

from backend.shared.site_config import Event, SiteConfig, load_site_config

from . import cache

log = logging.getLogger("m7.imagery")

REPO_ROOT = Path(__file__).resolve().parents[2]
FALLBACK_MAX_PX = 512
PHASES = ("pre", "post")
MANIFEST_NAME = "imagery/manifest.json"


@dataclass
class ImageryResult:
    site_id: str
    manifest_path: Path | None = None
    source: str = "cache"  # "live" | "cache"
    errors: list[str] = field(default_factory=list)


def _event_for_imagery(cfg: SiteConfig) -> Event:
    """The first event with both `imagery_pre_event` and `imagery_post_event` set. Raises if
    none has both -- CLAUDE.md rule 3: no invented event facts."""
    for ev in cfg.events:
        if ev.imagery_pre_event.value and ev.imagery_post_event.value:
            return ev
    raise ValueError(
        f"site '{cfg.site.id}' has no event with both imagery_pre_event and imagery_post_event set"
    )


def raw_rgb_path(source: str | None, repo_root: Path = REPO_ROOT) -> Path:
    """The `..._rgb.tif` sibling of the analysis GeoTIFF an event's `imagery_pre_event`/
    `imagery_post_event.source` points at (e.g. `cache/gee/teesta/teesta_pre_event.tif` ->
    `cache/gee/teesta/teesta_pre_event_rgb.tif`), resolved under `repo_root`."""
    if not source:
        raise ValueError("imagery source is not set (SourcedValue.source is empty)")
    src_path = Path(source)
    rgb_name = f"{src_path.stem}_rgb{src_path.suffix}"
    return repo_root / src_path.with_name(rgb_name)


def _fallback_shape(width: int, height: int, max_px: int = FALLBACK_MAX_PX) -> tuple[int, int]:
    if max(width, height) <= max_px:
        return height, width
    scale = max_px / max(width, height)
    return max(1, round(height * scale)), max(1, round(width * scale))


def _write_png(arr: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with rasterio.open(tmp, "w", driver="PNG", width=arr.shape[2], height=arr.shape[1],
                        count=arr.shape[0], dtype=np.uint8) as dst:
        dst.write(arr)
    tmp.replace(path)
    sidecar = tmp.with_suffix(tmp.suffix + ".aux.xml")  # GDAL PNG driver may write one alongside
    if sidecar.is_file():
        sidecar.unlink()


def _convert_one(raw_tif: Path, stem: str, imagery_dir: Path) -> dict:
    if not raw_tif.is_file():
        raise FileNotFoundError(
            f"missing RGB GeoTIFF: expected '{raw_tif}' but it does not exist"
        )
    with rasterio.open(raw_tif) as ds:
        if ds.count < 3:
            raise ValueError(f"'{raw_tif}' has {ds.count} band(s); need at least 3 (RGB)")
        full = np.clip(ds.read([1, 2, 3]), 0, 255).astype(np.uint8)
        fh, fw = _fallback_shape(ds.width, ds.height)
        small = np.clip(
            ds.read([1, 2, 3], out_shape=(3, fh, fw), resampling=Resampling.average), 0, 255
        ).astype(np.uint8)
        west, south, east, north = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds, densify_pts=21)

    png_path = imagery_dir / f"{stem}.png"
    fallback_path = imagery_dir / f"{stem}_fallback.png"
    _write_png(full, png_path)
    _write_png(small, fallback_path)

    return {
        "png": f"imagery/{png_path.name}",
        "fallback_png": f"imagery/{fallback_path.name}",
        "bounds_latlng": [[south, west], [north, east]],
        "width": int(full.shape[2]), "height": int(full.shape[1]),
    }


def _merge_gee_meta_imagery(
    site_id: str, entries: list[dict], scene_ids: dict[str, list[str]], source: str, data_dir: Path,
) -> None:
    """Merges an `"imagery"` product entry into `gee_meta.json` (contract §4.8), keeping whatever
    `fetch.py` already wrote for `lake_area`/`lake_latest`/`rainfall` untouched."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    all_scene_ids = sorted({sid for ids in scene_ids.values() for sid in ids})
    meta = cache.read_json(site_id, "gee_meta.json", data_dir) or {"site_id": site_id}
    meta["imagery"] = {
        "dataset": "sentinel-2", "scene_ids": all_scene_ids,
        "acquisition_dates": sorted({e["date"] for e in entries}),
        "cloud_pct": None, "fetched_at": now, "source": source,
    }
    cache.write_json(site_id, "gee_meta.json", meta, data_dir)


def convert(
    site_id: str, cfg: SiteConfig | None = None, data_dir: str | Path = cache.DATA_DIR,
    repo_root: str | Path = REPO_ROOT, scene_ids: dict[str, list[str]] | None = None,
    source: str = "cache",
) -> Path:
    """Converts the site's staged pre-/post-event RGB GeoTIFFs into `data/<site_id>/gee/imagery/`
    PNGs + a `manifest.json`; returns the manifest's path. Raises `FileNotFoundError` naming the
    exact missing GeoTIFF, or `ValueError` if no event has imagery dates set -- never silently
    skips a phase.

    `scene_ids`, if given, is `{"pre": [...], "post": [...]}` -- the satellite scene(s) the staged
    GeoTIFFs were exported from -- and gets merged into `gee_meta.json`'s `"imagery"` entry
    (`source` labels where the *imagery* itself came from: `"cache"` for an operator-staged export,
    `"live"` when called from `refresh()` after a real re-render)."""
    cfg = cfg or load_site_config(site_id)
    data_dir = Path(data_dir)
    repo_root = Path(repo_root)
    event = _event_for_imagery(cfg)
    imagery_dir = cache.gee_dir(site_id, data_dir) / "imagery"

    entries = []
    for phase in PHASES:
        sv = event.imagery_pre_event if phase == "pre" else event.imagery_post_event
        raw_tif = raw_rgb_path(sv.source, repo_root)
        date_str = str(sv.value)[:10]
        stem = f"{event.id}_{phase}_{date_str.replace('-', '')}"
        entry = _convert_one(raw_tif, stem, imagery_dir)
        entries.append({"event_id": event.id, "phase": phase, "date": date_str, **entry})

    manifest = {"site_id": site_id, "event_id": event.id, "imagery": entries}
    manifest_path = cache.write_json(site_id, MANIFEST_NAME, manifest, data_dir)

    if scene_ids:
        _merge_gee_meta_imagery(site_id, entries, scene_ids, source, data_dir)

    return manifest_path


def refresh(
    site_id: str, cfg: SiteConfig | None = None, data_dir: str | Path = cache.DATA_DIR,
    repo_root: str | Path = REPO_ROOT, ee_project: str | None = None,
) -> ImageryResult:
    """Tries to re-render the event's pre-/post-event RGB composites live from Earth Engine,
    overwriting the staged `_rgb.tif` files, then reconverts. Falls back to whatever is already
    on disk on any failure -- missing credentials, no network, or no usable scene near the date."""
    cfg = cfg or load_site_config(site_id)
    result = ImageryResult(site_id=site_id)

    try:
        from .live_render import render_event_rgb  # deferred: only needed for a live attempt

        event = _event_for_imagery(cfg)
        render_event_rgb(cfg, event, repo_root=Path(repo_root), ee_project=ee_project)
        result.source = "live"
    except Exception as e:
        log.warning("live imagery refresh failed for '%s', keeping cached RGB tifs: %s", site_id, e)
        result.errors.append(f"imagery: {e}")
        result.source = "cache"

    result.manifest_path = convert(site_id, cfg=cfg, data_dir=data_dir, repo_root=repo_root)
    return result


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("site_id")
    parser.add_argument("--data-dir", type=Path, default=cache.DATA_DIR)
    parser.add_argument("--refresh", action="store_true", help="try a live Earth Engine re-render first")
    parser.add_argument("--ee-project", default=None)
    parser.add_argument("--pre-scene-id", action="append", default=[],
                         help="scene ID the staged pre-event GeoTIFF was exported from (repeatable)")
    parser.add_argument("--post-scene-id", action="append", default=[],
                         help="scene ID the staged post-event GeoTIFF was exported from (repeatable)")
    args = parser.parse_args(argv)
    scene_ids = {"pre": args.pre_scene_id, "post": args.post_scene_id}
    scene_ids = scene_ids if (scene_ids["pre"] or scene_ids["post"]) else None

    try:
        if args.refresh:
            result = refresh(args.site_id, data_dir=args.data_dir, ee_project=args.ee_project)
            print(f"source: {result.source}")
            for e in result.errors:
                log.warning("%s", e)
            print(f"wrote {result.manifest_path}")
        else:
            manifest_path = convert(args.site_id, data_dir=args.data_dir, scene_ids=scene_ids)
            print(f"wrote {manifest_path}")
    except (FileNotFoundError, ValueError) as e:
        log.error(str(e))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
