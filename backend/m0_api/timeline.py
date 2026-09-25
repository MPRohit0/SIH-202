"""M0's half of the Timeline route (`docs/handoff_contract.md` §5.5, route
#13): turns what `backend.m5_emulator.timeline.write_timeline_inputs` wrote
under `data/<site_id>/queries/<query_id>/timeline/` into the `Timeline` JSON
response, and renders/caches its frame PNGs with M0-5
(`backend/m0_api/rendering.py`) -- the `interval_s`-dependent frame list is
built here, per request, from the interval-independent rasters M5 writes
once per query.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rasterio

from backend.m0_api import mocks, registry, rendering
from backend.m5_emulator import timeline as m5_timeline
from backend.shared.grid import FLOAT_NODATA, UINT8_NODATA

#: frame band -> the styles.json entry it renders with (contract §6).
FRAME_LAYER_ID = {"median": "arrival_p50", "high": "extent_class", "possible": "extent_class"}
MAX_FRAMES = 500


def find_query_timeline_dir(query_id: str) -> tuple[str, Path] | None:
    """`(site_id, timeline_dir)` for whichever known site actually has this
    query's timeline inputs written, or `None`."""
    for site_id in mocks.KNOWN_SITE_IDS:
        timeline_dir = registry.data_dir() / site_id / "queries" / query_id / "timeline"
        if (timeline_dir / "timeline_data.json").is_file():
            return site_id, timeline_dir
    return None


def _read_json(timeline_dir: Path) -> dict:
    return json.loads((timeline_dir / "timeline_data.json").read_text())


def _read_band(timeline_dir: Path, band: str) -> np.ndarray:
    with rasterio.open(timeline_dir / f"arrival_{band}.tif") as ds:
        return ds.read(1)


def build_response(site_id: str, timeline_dir: Path, query_id: str, interval_s: float) -> dict:
    """The `Timeline` dict (`contracts/schemas/timeline.schema.json`), frame
    URLs included, for `interval_s`."""
    data = _read_json(timeline_dir)
    arrival_p10 = _read_band(timeline_dir, "p10")

    frames = []
    for t_s in m5_timeline.frame_times(arrival_p10, data["t_end_s"], interval_s):
        t_int = int(t_s)
        base = f"/api/v1/files/{site_id}/queries/{query_id}/timeline"
        frames.append({
            "t_s": t_s,
            "median_url": f"{base}/median_t{t_int}.png",
            "high_url": f"{base}/high_t{t_int}.png",
            "possible_url": f"{base}/possible_t{t_int}.png",
            "bounds_latlng": data["bounds_latlng"],
        })

    return {
        "query_id": query_id, "interval_s": interval_s, "t_end_s": data["t_end_s"], "frames": frames,
        "hydrographs": data["hydrographs"], "arrival_profile": data["arrival_profile"],
        "pois_on_profile": data["pois_on_profile"], "caveats": data["caveats"], "provenance": data["provenance"],
    }


def render_frame(timeline_dir: Path, band: str, t_s: int) -> bytes:
    """One frame's PNG (`band`: `"median"|"high"|"possible"`), cached beside
    the source rasters -- same one-render-per-(query, frame) rule as
    `rendering.render_and_cache`."""
    if band not in FRAME_LAYER_ID:
        raise ValueError(f"unknown timeline band '{band}'")
    png_path = timeline_dir / f"{band}_t{t_s}.png"
    if png_path.is_file():
        return png_path.read_bytes()

    data = _read_json(timeline_dir)
    arrival_p10 = _read_band(timeline_dir, "p10")
    arrival_p50 = _read_band(timeline_dir, "p50")
    arrival_p90 = _read_band(timeline_dir, "p90")
    with rasterio.open(timeline_dir / "extent_class.tif") as ds:
        extent_class = ds.read(1)

    t_s = min(float(t_s), data["t_end_s"])
    median, high, possible = m5_timeline.frame_arrays(arrival_p10, arrival_p50, arrival_p90, extent_class, t_s)
    array, nodata = {"median": (median, FLOAT_NODATA), "high": (high, UINT8_NODATA), "possible": (possible, UINT8_NODATA)}[band]

    png_bytes = rendering.render_layer_png(array, nodata, FRAME_LAYER_ID[band])
    png_path.write_bytes(png_bytes)
    return png_bytes
