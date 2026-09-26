"""M7 scene search: list Sentinel-1/2 scenes over a site AOI and save quick-look PNGs.

This is a human-in-the-loop browsing tool, not the final §4.8 fetch pipeline: it lets an
operator see what's available and pick the pre-/post-event scene dates. Those dates then get
written into `sites/<site_id>.yaml` `events[].imagery_pre_event`/`imagery_post_event`
(`backend/shared/site_config.py`), and a later, separate fetch step is what writes the
contract's `data/<site_id>/gee/imagery/<event_id>_<pre|post>_<date>.png` (§4.8). To keep that
distinction clear, this module writes its own manifest + thumbnails under
`data/<site_id>/gee/scene_search/`, never under `gee/imagery/`.

AOI comes from the site config's `domains.far_field` (or `--domain near_field`) bbox — the same
EPSG:4326 [min_lon, min_lat, max_lon, max_lat] used throughout the contract (CLAUDE.md rule 7).

Collections used:
- Sentinel-2: `COPERNICUS/S2_SR_HARMONIZED`. `cloud_pct_scene` is the standard whole-tile
  `CLOUDY_PIXEL_PERCENTAGE` metadata property; `cloud_pct_aoi` is computed from the per-pixel
  Scene Classification Layer (SCL) clipped to the AOI (classes 3, 8, 9, 10 = cloud shadow/medium
  cloud/high cloud/thin cirrus), which is what actually matters for picking a usable scene.
- Sentinel-1: `COPERNICUS/S1_GRD`, IW mode. SAR has no clouds, so `cloud_pct_scene` and
  `cloud_pct_aoi` are always null, matching `gee_layers.example.json` (§5.8).

Needs Earth Engine credentials already set up (`earthengine authenticate`, or a service account)
and, for most modern EE accounts, a Cloud project (`--ee-project`). Nothing secret is read,
logged or written by this module (CLAUDE.md rule 12).

CLI: `python -m backend.m7_gee.scene_search <site_id> --start YYYY-MM-DD --end YYYY-MM-DD
[--domain far_field|near_field] [--satellites s2,s1] [--max-cloud-pct 60]
[--max-scenes-per-satellite 20] [--out-dir DIR] [--ee-project PROJECT] [--no-thumbnails]`
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx

from backend.shared.site_config import SiteConfig, load_site_config

logger = logging.getLogger(__name__)

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
GEE_SA_EMAIL_ENV = "GEE_SERVICE_ACCOUNT_EMAIL"
GEE_SA_KEY_PATH_ENV = "GEE_SERVICE_ACCOUNT_KEY_PATH"

S2_COLLECTION = "COPERNICUS/S2_SR_HARMONIZED"
S1_COLLECTION = "COPERNICUS/S1_GRD"

# SCL (Scene Classification Layer) codes counted as "cloud" for the AOI cloud fraction.
S2_SCL_CLOUD_CLASSES = [3, 8, 9, 10]  # cloud shadow, cloud medium prob, cloud high prob, thin cirrus

THUMB_DIMENSIONS = 512
S2_VIS = {"bands": ["B4", "B3", "B2"], "min": 0, "max": 3000, "gamma": 1.4}
S1_VIS = {"bands": ["VV"], "min": -25, "max": 0}


@dataclass
class SceneInfo:
    satellite: str  # "sentinel-2" | "sentinel-1"
    scene_id: str
    date: str  # YYYY-MM-DD
    cloud_pct_scene: float | None
    cloud_pct_aoi: float | None
    product: str
    thumbnail_path: str | None


def _aoi_geometry(site_config: SiteConfig, domain: str):
    import ee  # deferred: only needed once EE is actually used

    bbox = getattr(site_config.domains, domain).bbox.value
    if bbox is None:
        raise ValueError(f"site config has no bbox value for domains.{domain} "
                          f"(status is placeholder with a null value)")
    min_lon, min_lat, max_lon, max_lat = bbox
    return ee.Geometry.Rectangle([min_lon, min_lat, max_lon, max_lat])


def _env_value(name: str) -> str | None:
    """`name` from the environment, else parsed from the repo `.env` (same lookup as
    `backend.m1_terrain.download.opentopography_api_key`). Never logs the value."""
    value = os.environ.get(name)
    if value:
        return value
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            if key.strip() == name:
                val = val.strip().strip('"').strip("'")
                if val:
                    return val
    return None


def gee_service_account_credentials() -> tuple[str, str] | None:
    """`(email, key_path)` from `GEE_SERVICE_ACCOUNT_EMAIL` / `GEE_SERVICE_ACCOUNT_KEY_PATH`
    (environment or repo `.env`), or `None` if either is unset. Only the key file's *path* is
    ever read here, never its contents (CLAUDE.md rule 12)."""
    email = _env_value(GEE_SA_EMAIL_ENV)
    key_path = _env_value(GEE_SA_KEY_PATH_ENV)
    return (email, key_path) if email and key_path else None


def _ee_initialize(project: str | None) -> None:
    import ee

    creds = gee_service_account_credentials()
    try:
        if creds is not None:
            email, key_path = creds
            if not Path(key_path).is_file():
                raise RuntimeError(f"{GEE_SA_KEY_PATH_ENV} points at '{key_path}', which does not exist")
            credentials = ee.ServiceAccountCredentials(email, key_path)
            ee.Initialize(credentials, project=project) if project else ee.Initialize(credentials)
        else:
            ee.Initialize(project=project) if project else ee.Initialize()
    except Exception as e:  # pragma: no cover - depends on local EE auth state
        raise RuntimeError(
            "Earth Engine initialisation failed. Either run `earthengine authenticate` once (and "
            "pass --ee-project <your-cloud-project> if your account requires one), or set "
            f"{GEE_SA_EMAIL_ENV} / {GEE_SA_KEY_PATH_ENV} in .env for a service account."
        ) from e


def _download_thumbnail(url: str, dest: Path) -> bool:
    try:
        resp = httpx.get(url, timeout=60.0, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("thumbnail download failed for %s: %s", dest.name, e)
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    return True


def search_sentinel2(aoi, start: str, end: str, max_cloud_pct: float | None,
                      max_scenes: int) -> list[dict]:
    """Query Sentinel-2 scenes over `aoi` between `start`/`end` (YYYY-MM-DD), newest first.

    Returns raw per-scene dicts (id, date, cloud_pct_scene, cloud_pct_aoi) — no network I/O
    beyond the EE server-side query and one `getInfo()`/scene for the AOI cloud fraction.
    """
    import ee

    coll = (ee.ImageCollection(S2_COLLECTION)
            .filterBounds(aoi)
            .filterDate(start, end)
            .sort("system:time_start", False))
    if max_cloud_pct is not None:
        coll = coll.filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", max_cloud_pct))

    ids = coll.limit(max_scenes).aggregate_array("system:index").getInfo()
    results = []
    for scene_id in ids:
        img = ee.Image(f"{S2_COLLECTION}/{scene_id}")
        props = img.toDictionary(["system:time_start", "CLOUDY_PIXEL_PERCENTAGE"]).getInfo()
        date = ee.Date(props["system:time_start"]).format("YYYY-MM-dd").getInfo()

        scl = img.select("SCL").clip(aoi)
        is_cloud = scl.remap(S2_SCL_CLOUD_CLASSES, [1] * len(S2_SCL_CLOUD_CLASSES), 0)
        stats = is_cloud.reduceRegion(
            reducer=ee.Reducer.mean(), geometry=aoi, scale=20, maxPixels=1e9, bestEffort=True,
        ).getInfo()
        cloud_pct_aoi = None
        if stats.get("SCL") is not None:
            cloud_pct_aoi = round(100.0 * stats["SCL"], 1)

        results.append({
            "satellite": "sentinel-2",
            "scene_id": scene_id,
            "date": date,
            "cloud_pct_scene": round(props.get("CLOUDY_PIXEL_PERCENTAGE", 0.0), 1),
            "cloud_pct_aoi": cloud_pct_aoi,
            "product": S2_COLLECTION,
        })
    return results


def search_sentinel1(aoi, start: str, end: str, max_scenes: int) -> list[dict]:
    """Query Sentinel-1 IW scenes over `aoi` between `start`/`end` (YYYY-MM-DD), newest first.

    SAR has no cloud cover, so `cloud_pct_scene`/`cloud_pct_aoi` are always None
    (`gee_layers.example.json` §5.8 does the same for `s1_threshold`).
    """
    import ee

    coll = (ee.ImageCollection(S1_COLLECTION)
            .filterBounds(aoi)
            .filterDate(start, end)
            .filter(ee.Filter.eq("instrumentMode", "IW"))
            .sort("system:time_start", False))

    ids = coll.limit(max_scenes).aggregate_array("system:index").getInfo()
    results = []
    for scene_id in ids:
        img = ee.Image(f"{S1_COLLECTION}/{scene_id}")
        props = img.toDictionary(["system:time_start", "orbitProperties_pass"]).getInfo()
        date = ee.Date(props["system:time_start"]).format("YYYY-MM-dd").getInfo()
        results.append({
            "satellite": "sentinel-1",
            "scene_id": scene_id,
            "date": date,
            "cloud_pct_scene": None,
            "cloud_pct_aoi": None,
            "product": f"{S1_COLLECTION} ({props.get('orbitProperties_pass', '?')})",
        })
    return results


def save_thumbnail(satellite: str, scene_id: str, aoi, out_dir: Path) -> str | None:
    import ee

    collection = S2_COLLECTION if satellite == "sentinel-2" else S1_COLLECTION
    vis = S2_VIS if satellite == "sentinel-2" else S1_VIS
    img = ee.Image(f"{collection}/{scene_id}").clip(aoi)
    try:
        url = img.getThumbURL({**vis, "region": aoi, "dimensions": THUMB_DIMENSIONS, "format": "png"})
    except Exception as e:  # pragma: no cover - depends on EE server state
        logger.warning("could not build thumbnail URL for %s: %s", scene_id, e)
        return None

    dest = out_dir / "thumbnails" / f"{scene_id}.png"
    if not _download_thumbnail(url, dest):
        return None
    return str(dest)


def write_manifest(scenes: list[SceneInfo], out_dir: Path) -> Path:
    path = out_dir / "scenes.csv"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "satellite", "scene_id", "cloud_pct_scene", "cloud_pct_aoi",
                          "product", "thumbnail_path"])
        for s in scenes:
            writer.writerow([s.date, s.satellite, s.scene_id,
                              "" if s.cloud_pct_scene is None else s.cloud_pct_scene,
                              "" if s.cloud_pct_aoi is None else s.cloud_pct_aoi,
                              s.product, s.thumbnail_path or ""])
    return path


def run(site_id: str, start: str, end: str, domain: str, satellites: list[str],
        max_cloud_pct: float | None, max_scenes_per_satellite: int, out_dir: Path,
        ee_project: str | None, save_thumbnails: bool) -> list[SceneInfo]:
    site_config = load_site_config(site_id)
    _ee_initialize(ee_project)
    aoi = _aoi_geometry(site_config, domain)

    raw: list[dict] = []
    if "s2" in satellites:
        raw += search_sentinel2(aoi, start, end, max_cloud_pct, max_scenes_per_satellite)
    if "s1" in satellites:
        raw += search_sentinel1(aoi, start, end, max_scenes_per_satellite)
    raw.sort(key=lambda r: r["date"], reverse=True)

    scenes = []
    for r in raw:
        thumb = None
        if save_thumbnails:
            thumb = save_thumbnail(r["satellite"], r["scene_id"], aoi, out_dir)
        scenes.append(SceneInfo(thumbnail_path=thumb, **r))

    manifest_path = write_manifest(scenes, out_dir)
    logger.info("%d scene(s) found; manifest at %s", len(scenes), manifest_path)
    return scenes


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("site_id")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD, inclusive")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD, exclusive")
    parser.add_argument("--domain", choices=["far_field", "near_field"], default="far_field")
    parser.add_argument("--satellites", default="s2,s1", help="comma-separated: s2,s1")
    parser.add_argument("--max-cloud-pct", type=float, default=None,
                         help="Sentinel-2 only, filters on the whole-tile metadata value")
    parser.add_argument("--max-scenes-per-satellite", type=int, default=20)
    parser.add_argument("--out-dir", type=Path, default=None,
                         help="default: data/<site_id>/gee/scene_search/<start>_<end>")
    parser.add_argument("--ee-project", default=None, help="Cloud project for ee.Initialize()")
    parser.add_argument("--no-thumbnails", action="store_true", help="list scenes only, skip PNGs")
    args = parser.parse_args(argv)

    satellites = [s.strip() for s in args.satellites.split(",") if s.strip()]
    unknown = set(satellites) - {"s2", "s1"}
    if unknown:
        parser.error(f"unknown satellite(s) {sorted(unknown)}; choose from s2, s1")

    out_dir = args.out_dir or Path("data") / args.site_id / "gee" / "scene_search" / f"{args.start}_{args.end}"

    try:
        scenes = run(args.site_id, args.start, args.end, args.domain, satellites,
                     args.max_cloud_pct, args.max_scenes_per_satellite, out_dir,
                     args.ee_project, save_thumbnails=not args.no_thumbnails)
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        logger.error(str(e))
        return 1

    for s in scenes:
        cloud = "-" if s.cloud_pct_aoi is None else f"{s.cloud_pct_aoi:.1f}%"
        print(f"{s.date}  {s.satellite:<11}  cloud(aoi)={cloud:<7}  {s.scene_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
