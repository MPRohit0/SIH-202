"""M5's half of the Timeline (`docs/handoff_contract.md` §5.5, route #13):
flood-front frames ("extent at time t = cells whose arrival <= t") for
median/HIGH/POSSIBLE, the arrival-vs-chainage profile with P10/P50/P90
bounds, and the M2 inflow hydrograph(s) that ride along with them.

This module is pure numpy plus one file-writing entry point
(`write_timeline_inputs`) -- it never renders a PNG (that's M0-5,
`backend/m0_api/rendering.py`) or serves the `Timeline` JSON (that's M0's
`/flood/{query_id}/timeline` route). It writes four GeoTIFFs (the arrival
P10/P50/P90 bands plus the final `extent_class`) and one small JSON sidecar
(`timeline_data.json`) that M0 turns into per-`interval_s` frame lists on
request -- the rasters don't depend on `interval_s`, so they're written once
per query, not once per timeline request.

Frame semantics (contract §5.5): a cell lights up in `median_url` once its
P50 arrival <= t; in `high_url` once it's a HIGH cell (`extent_class == 2`)
whose P90 arrival <= t; in `possible_url` once it's a POSSIBLE-or-HIGH cell
(`extent_class >= 1`) whose P10 arrival <= t and it isn't already in
`high_url`. At `t = t_end_s`, `high_url` + `possible_url` together reproduce
`extent_class`; every frame is monotone (a lit cell never unlights).

A cell's arrival at a given band is only meaningful where `query.py` has
already gated that band's arrival array against its own depth (nodata
elsewhere) -- this module just thresholds on `t`, it doesn't re-derive
gating.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from backend.m5_emulator.query import FloodResult
from backend.shared.grid import CanonicalGrid, FLOAT_NODATA, write_grid_raster

DEFAULT_INTERVAL_S = 300.0


def _valid(arrival: np.ndarray) -> np.ndarray:
    return (arrival != FLOAT_NODATA) & np.isfinite(arrival)


def frame_times(arrival_p10: np.ndarray, t_end_s: float, interval_s: float = DEFAULT_INTERVAL_S) -> list[float]:
    """`[interval_s, 2*interval_s, ...]` up to the first multiple that covers
    every cell's P10 (leading-edge) arrival, capped at `t_end_s`. If nothing
    ever arrives, a single frame at `min(interval_s, t_end_s)` is still
    returned (an all-dry timeline, not an empty one)."""
    if interval_s <= 0:
        raise ValueError(f"interval_s must be > 0, got {interval_s!r}")
    if t_end_s <= 0:
        raise ValueError(f"t_end_s must be > 0, got {t_end_s!r}")
    valid = _valid(arrival_p10)
    last_t = float(arrival_p10[valid].max()) if valid.any() else 0.0
    last_t = min(max(last_t, 0.0), t_end_s)
    n = max(1, math.ceil(last_t / interval_s))
    return [min(t_end_s, k * interval_s) for k in range(1, n + 1)]


def frame_arrays(
    arrival_p10: np.ndarray, arrival_p50: np.ndarray, arrival_p90: np.ndarray, extent_class: np.ndarray, t_s: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """One frame's `(median, high, possible)` arrays at time `t_s` -- `median`
    float32 (arrival value where lit, else nodata), `high`/`possible` uint8
    (`extent_class`-style 0/1/2 codes, contract §4.6)."""
    valid10, valid50, valid90 = _valid(arrival_p10), _valid(arrival_p50), _valid(arrival_p90)

    median = np.where(valid50 & (arrival_p50 <= t_s), arrival_p50, FLOAT_NODATA).astype(np.float32)

    high_mask = (extent_class == 2) & valid90 & (arrival_p90 <= t_s)
    high = np.where(high_mask, np.uint8(2), np.uint8(0))

    possible_mask = (extent_class >= 1) & valid10 & (arrival_p10 <= t_s) & ~high_mask
    possible = np.where(possible_mask, np.uint8(1), np.uint8(0))

    return median, high, possible


def arrival_profile(
    median_arrival: np.ndarray, p10_arrival: np.ndarray, p90_arrival: np.ndarray,
    chainage_m: np.ndarray, cell_index: np.ndarray,
) -> list[dict]:
    """One row per `chainage_m`/`cell_index` sample (`synthetic.centreline_samples`
    or a real `chainage_samples.csv`, contract §4.1). A row is omitted where
    even the median never arrives; P10/P90 are `null` there instead."""
    flat_50 = median_arrival.ravel()[cell_index]
    flat_10 = p10_arrival.ravel()[cell_index]
    flat_90 = p90_arrival.ravel()[cell_index]
    rows = []
    for chainage, a50, a10, a90 in zip(chainage_m, flat_50, flat_10, flat_90):
        if not _valid(np.array([a50]))[0]:
            continue
        rows.append({
            "chainage_m": float(chainage),
            "arrival_p10_s": float(a10) if _valid(np.array([a10]))[0] else None,
            "arrival_p50_s": float(a50),
            "arrival_p90_s": float(a90) if _valid(np.array([a90]))[0] else None,
        })
    return rows


def pois_on_profile(pois: dict[str, int], grid: CanonicalGrid, site_id: str) -> list[dict]:
    """`pois`: name -> flattened full-grid cell index (as `get_flood` takes
    them) -> chainage from the column, same convention as
    `synthetic.centreline_samples`/`poi_cell_index`."""
    out = []
    for name, idx in pois.items():
        col = int(idx) % grid.width
        out.append({
            "poi_id": f"{site_id}__poi__{name}", "name": name,
            "chainage_m": float((col + 0.5) * grid.cell_size_m),
        })
    return out


def hydrograph_series(hydrographs) -> list[dict]:
    """`hydrographs`: `backend.m2_breach.hydrograph.Hydrograph` instances ->
    the contract's `hydrographs[]` (`t_s`/`q_m3s` are already SI, CLAUDE.md
    rule 5, so no conversion needed)."""
    out = []
    for hg in hydrographs:
        points = [{"t_s": float(t), "q_m3s": float(q)} for t, q in zip(hg.t_s, hg.q_m3s)]
        out.append({"dam_id": hg.dam_id, "t_offset_s": float(hg.t_offset_s), "points": points})
    return out


def write_timeline_inputs(
    result: FloodResult, grid: CanonicalGrid, query_dir: str | Path, *,
    hydrographs, chainage_m: np.ndarray, cell_index: np.ndarray, pois: dict[str, int],
    t_end_s: float, contract_version: str, created_at: str, caveats: list[dict] | None = None,
) -> Path:
    """Write `timeline/{arrival_p10,arrival_p50,arrival_p90,extent_class}.tif`
    and `timeline/timeline_data.json` (everything a `Timeline` response needs
    except the per-`interval_s` frame list and PNG URLs, which are M0's job).
    Returns the `timeline/` directory."""
    timeline_dir = Path(query_dir) / "timeline"
    timeline_dir.mkdir(parents=True, exist_ok=True)

    write_grid_raster(timeline_dir / "arrival_p10.tif", result.p10["arrival_time"], grid)
    write_grid_raster(timeline_dir / "arrival_p50.tif", result.median["arrival_time"], grid)
    write_grid_raster(timeline_dir / "arrival_p90.tif", result.p90["arrival_time"], grid)
    write_grid_raster(timeline_dir / "extent_class.tif", result.extent_class, grid)

    caveats = list(caveats or [])
    caveats.append({
        "id": "arrival_depth_not_joint", "severity": "info",
        "text_key": "caveat_arrival_depth_not_joint",
    })

    data = {
        "t_end_s": float(t_end_s),
        "hydrographs": hydrograph_series(hydrographs),
        "arrival_profile": arrival_profile(
            result.median["arrival_time"], result.p10["arrival_time"], result.p90["arrival_time"],
            chainage_m, cell_index,
        ),
        "pois_on_profile": pois_on_profile(pois, grid, result.site_id),
        "bounds_latlng": grid.bounds_latlng,
        "caveats": caveats,
        "provenance": {
            "method": "gp_emulator", "contract_version": contract_version, "created_at": created_at,
        },
    }
    (timeline_dir / "timeline_data.json").write_text(json.dumps(data))
    return timeline_dir
