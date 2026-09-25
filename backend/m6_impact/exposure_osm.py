"""Download and clip OSM exposure layers for a site's far-field bbox
(docs/handoff_contract.md §4.7 "Exposure inputs" table):

    buildings.gpkg    building=* ways/relations           -> polygons
    roads.gpkg        highway=* ways                      -> lines
    facilities.gpkg   amenity=hospital|school, bridges     -> points
    places.gpkg       place=city|town|village|hamlet nodes -> points

Each layer's `osm_id`, `kind`, `name` columns match the contract. Data is
pulled from the public Overpass API (OpenStreetMap contributors, ODbL) with
`out geom;` so way/node coordinates come back inline and no separate node
resolution pass is needed. OSM relations (e.g. multipolygon buildings) are
NOT fetched — a documented limitation, noted in `provenance.json`.

Idempotent: a layer already present in `data/<site_id>/exposure/` is left
alone and not re-fetched.

CLI: `python -m backend.m6_impact.exposure_osm <site_id>`
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx
from shapely.geometry import LineString, Point, Polygon

from backend.shared.site_config import SiteConfig, load_site_config

log = logging.getLogger("m6.exposure_osm")

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_TIMEOUT_S = 300  # QL [timeout:...]; large far-field bboxes over Himalayan valleys are slow
OSM_LICENSE = "Open Database License (ODbL) - (c) OpenStreetMap contributors, https://www.openstreetmap.org/copyright"
# overpass-api.de returns 406 Not Acceptable to requests with no/default User-Agent.
USER_AGENT = "SIH26-GLOF-tool/0.1 (offline data prep, no auth; see docs/handoff_contract.md)"

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

GeomKind = str  # "polygon" | "line" | "point"


class Category:
    """One exposure layer: an Overpass QL statement list and a geometry kind."""

    def __init__(self, filename: str, statements: list[str], geom_kind: GeomKind,
                 kind_of: Callable[[dict], str | None]):
        self.filename = filename
        self.statements = statements
        self.geom_kind = geom_kind
        self.kind_of = kind_of  # tags -> the row's `kind` value, or None to drop the element


def _bbox_south_west_north_east(bbox: list[float]) -> str:
    """Overpass wants `(south,west,north,east)`; the contract's bbox is `[min_lon, min_lat, max_lon, max_lat]`."""
    min_lon, min_lat, max_lon, max_lat = bbox
    return f"({min_lat},{min_lon},{max_lat},{max_lon})"


def _building_kind(tags: dict) -> str | None:
    v = tags.get("building")
    return v if v and v != "yes" else "building"


def _road_kind(tags: dict) -> str | None:
    return tags.get("highway")


def _facility_kind(tags: dict) -> str | None:
    amenity = tags.get("amenity")
    if amenity in ("hospital", "school"):
        return amenity
    if tags.get("bridge") == "yes" or tags.get("man_made") == "bridge":
        return "bridge"
    return None


def _place_kind(tags: dict) -> str | None:
    v = tags.get("place")
    return v if v in ("city", "town", "village", "hamlet") else None


def categories(bbox: list[float]) -> dict[str, Category]:
    box = _bbox_south_west_north_east(bbox)
    return {
        "buildings": Category(
            "buildings.gpkg",
            [f'way["building"]{box};'],
            "polygon", _building_kind,
        ),
        "roads": Category(
            "roads.gpkg",
            [f'way["highway"]{box};'],
            "line", _road_kind,
        ),
        "facilities": Category(
            "facilities.gpkg",
            [
                f'node["amenity"~"^(hospital|school)$"]{box};',
                f'way["amenity"~"^(hospital|school)$"]{box};',
                f'way["bridge"="yes"]{box};',
                f'node["man_made"="bridge"]{box};',
                f'way["man_made"="bridge"]{box};',
            ],
            "point", _facility_kind,
        ),
        "places": Category(
            "places.gpkg",
            [f'node["place"~"^(city|town|village|hamlet)$"]{box};'],
            "point", _place_kind,
        ),
    }


def build_query(category: Category) -> str:
    body = "\n  ".join(category.statements)
    return f"[out:json][timeout:{OVERPASS_TIMEOUT_S}];\n(\n  {body}\n);\nout geom;"


RETRYABLE_STATUS_CODES = {502, 503, 504}  # overpass-api.de: transient overload/gateway errors
MAX_ATTEMPTS = 5
RETRY_BACKOFF_S = 30.0


def run_overpass_query(query: str, endpoint: str = OVERPASS_URL, client: httpx.Client | None = None) -> dict:
    """POST an Overpass QL query and return the parsed JSON response.

    Retries a few times on 502/503/504 (the public overpass-api.de instance returns these
    under load, especially for the large bboxes real far-field domains need) before giving up."""
    owns_client = client is None
    client = client or httpx.Client(timeout=OVERPASS_TIMEOUT_S + 30, headers={"User-Agent": USER_AGENT})
    try:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            resp = client.post(endpoint, data={"data": query}, headers={"User-Agent": USER_AGENT})
            if resp.status_code in RETRYABLE_STATUS_CODES and attempt < MAX_ATTEMPTS:
                wait_s = RETRY_BACKOFF_S * attempt
                log.warning("Overpass returned %d (attempt %d/%d), retrying in %.0fs",
                            resp.status_code, attempt, MAX_ATTEMPTS, wait_s)
                time.sleep(wait_s)
                continue
            resp.raise_for_status()
            return resp.json()
    finally:
        if owns_client:
            client.close()


def _way_geometry(element: dict, geom_kind: GeomKind):
    coords = [(pt["lon"], pt["lat"]) for pt in (element.get("geometry") or []) if pt is not None]
    if len(coords) < 2:
        return None
    if geom_kind == "polygon":
        if coords[0] != coords[-1]:
            coords = [*coords, coords[0]]
        if len(coords) < 4:
            return None
        return Polygon(coords)
    line = LineString(coords)
    if geom_kind == "point":
        return line.interpolate(0.5, normalized=True)  # representative point of a way
    return line


def elements_to_rows(elements: list[dict], category: Category) -> list[dict[str, Any]]:
    """Turn Overpass elements into `{osm_id, kind, name, geometry}` rows, dropping
    elements the category doesn't want (wrong tag value) or with no geometry."""
    rows = []
    for el in elements:
        tags = el.get("tags") or {}
        kind = category.kind_of(tags)
        if kind is None:
            continue

        el_type = el["type"]
        if el_type == "node":
            geometry = Point(el["lon"], el["lat"])
            if category.geom_kind != "point":
                continue  # a node can't satisfy a polygon/line category
        elif el_type == "way":
            geometry = _way_geometry(el, category.geom_kind)
        else:
            continue  # relations: not fetched, see module docstring

        if geometry is None:
            continue
        rows.append({
            "osm_id": f"{el_type}/{el['id']}",
            "kind": kind,
            "name": tags.get("name"),
            "geometry": geometry,
        })
    return rows


def _write_gpkg(rows: list[dict[str, Any]], geom_kind: GeomKind, path: Path) -> int:
    import geopandas as gpd

    geom_type = {"polygon": "Polygon", "line": "LineString", "point": "Point"}[geom_kind]
    gdf = gpd.GeoDataFrame(rows, geometry="geometry" if rows else [], crs="EPSG:4326")
    if rows:
        gdf = gdf[["osm_id", "kind", "name", "geometry"]]
    else:
        gdf = gpd.GeoDataFrame(columns=["osm_id", "kind", "name", "geometry"], geometry="geometry", crs="EPSG:4326")
    path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(path, driver="GPKG", layer=path.stem, geometry_type=geom_type)
    return len(gdf)


def fetch_category(name: str, category: Category, bbox: list[float], out_path: Path,
                    endpoint: str = OVERPASS_URL, client: httpx.Client | None = None) -> dict:
    """Fetch, clip and write one category. Returns its provenance entry.
    Skips the query entirely (and returns a `skipped` entry) if `out_path` already exists."""
    if out_path.exists():
        log.info("%s: %s already exists, skipping", name, out_path)
        return {"file": out_path.name, "status": "skipped_existing"}

    query = build_query(category)
    log.info("%s: querying Overpass (%d statement(s))", name, len(category.statements))
    response = run_overpass_query(query, endpoint=endpoint, client=client)
    elements = response.get("elements", [])
    rows = elements_to_rows(elements, category)
    n_written = _write_gpkg(rows, category.geom_kind, out_path)
    log.info("%s: wrote %d feature(s) to %s", name, n_written, out_path)
    return {
        "file": out_path.name,
        "status": "fetched",
        "source": "OpenStreetMap via Overpass API",
        "endpoint": endpoint,
        "query": query,
        "license": OSM_LICENSE,
        "bbox_deg": bbox,
        "feature_count": n_written,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def _merge_provenance(exposure_dir: Path, entries: dict[str, dict]) -> None:
    path = exposure_dir / "provenance.json"
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    existing.update(entries)
    path.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fetch_all(cfg: SiteConfig, data_dir: Path = DATA_DIR, endpoint: str = OVERPASS_URL) -> dict[str, dict]:
    bbox = cfg.domains.far_field.bbox.value
    if bbox is None:
        raise ValueError(f"site '{cfg.site.id}': domains.far_field.bbox is a placeholder (null) — "
                          "fill it in before fetching exposure data")

    exposure_dir = data_dir / cfg.site.id / "exposure"
    results: dict[str, dict] = {}
    with httpx.Client(timeout=OVERPASS_TIMEOUT_S + 30, headers={"User-Agent": USER_AGENT}) as client:
        for name, category in categories(bbox).items():
            out_path = exposure_dir / category.filename
            results[name] = fetch_category(name, category, bbox, out_path, endpoint=endpoint, client=client)

    # Don't let a skip-existing rerun clobber the richer provenance entry from the original fetch.
    fresh = {f"osm_{name}": entry for name, entry in results.items() if entry["status"] != "skipped_existing"}
    if fresh:
        _merge_provenance(exposure_dir, fresh)
    return results


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("site_id", help="site id (a sites/<site_id>.yaml must exist)")
    parser.add_argument("--endpoint", default=OVERPASS_URL, help="Overpass API endpoint")
    parser.add_argument("--data-dir", default=str(DATA_DIR), help="override the data/ root")
    args = parser.parse_args(argv)

    cfg = load_site_config(args.site_id)
    fetch_all(cfg, data_dir=Path(args.data_dir), endpoint=args.endpoint)
    return 0


if __name__ == "__main__":
    sys.exit(main())
