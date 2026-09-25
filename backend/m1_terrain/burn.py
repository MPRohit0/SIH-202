"""M1: burn dams and reservoirs into the DEM (`docs/handoff_contract.md` §4.1 `dem.tif`
"conditioned DEM with dams/reservoirs burned in, lake masked (not filled)").

- **Dam crest**: a DEM built from a coarse public DEM doesn't resolve a dam's crest as a ridge —
  `burn_dam_crest` raises a strip across the valley, centred on `dam.location`, so the flow-routing
  pass in `hydro.py` sees a barrier there instead of routing straight through it. The strip runs
  perpendicular to the *pre-burn* local flow direction (from a first `route()` pass on the raw
  DEM, before any dam exists) and is `average_embankment_width` thick along the flow direction.
- **Reservoir**: `burn_reservoir` flattens the reservoir footprint (`water.py`'s `RESERVOIR` label)
  to a single water-surface elevation — an engineered reservoir is routed through normally after
  breach, so (unlike a moraine lake, which `pipeline.py` masks out of routing instead) it belongs
  in the DEM, not excluded from it. The true bathymetry is unknown from a surface DEM; this is
  recorded as a caveat, never presented as surveyed.
"""

from __future__ import annotations

import numpy as np

from backend.shared.grid import FLOAT_NODATA, CanonicalGrid, lonlat_to_rowcol
from backend.shared.site_config import Dam

from .hydro import NO_PARENT, FlowNetwork
from .settings import TerrainSettings


def _flow_direction_unit(network: FlowNetwork, row: int, col: int) -> tuple[float, float] | None:
    """Unit vector (d_row, d_col) from `(row, col)` toward its downstream parent cell, or `None`
    if the cell is itself an outlet (no local flow direction to orient a crest against)."""
    w = network.parent.shape[1]
    p = network.parent[row, col]
    if p == NO_PARENT:
        return None
    pr, pc = divmod(int(p), w)
    dr, dc = pr - row, pc - col
    norm = np.hypot(dr, dc)
    if norm == 0:
        return None
    return dr / norm, dc / norm


def burn_dam_crest(
    dem: np.ndarray,
    dam: Dam,
    flow_network: FlowNetwork,
    grid: CanonicalGrid,
    settings: TerrainSettings,
) -> tuple[np.ndarray, dict]:
    """Raise a crest strip across `dem` at `dam.location`, perpendicular to the local pre-burn
    flow direction. Returns the (possibly unchanged) DEM and an info dict for `provenance.json`.
    Only ever raises terrain (`dem = max(dem, crest_elev)`) — never lowers it."""
    dam_id = dam.id
    loc = dam.location.value
    height = dam.breach_inputs.dam_height.value
    width = dam.breach_inputs.average_embankment_width.value

    if loc is None or height is None or width is None:
        missing = [n for n, v in (("location", loc), ("dam_height", height), ("average_embankment_width", width)) if v is None]
        return dem, {"dam_id": dam_id, "burned": False, "reason": f"placeholder input(s): {', '.join(missing)}"}

    row, col = lonlat_to_rowcol(grid, loc[0], loc[1], strict=False)
    if row < 0:
        return dem, {"dam_id": dam_id, "burned": False, "reason": "location is outside the grid"}

    direction = _flow_direction_unit(flow_network, row, col)
    if direction is None:
        return dem, {"dam_id": dam_id, "burned": False, "reason": "no local flow direction at the dam location (grid edge/outlet)"}
    perp = (-direction[1], direction[0])  # rotate 90 deg in (row, col) space

    radius_cells = max(1, int(round(settings.snap_radius_m / grid.cell_size_m)))
    r0, r1 = max(0, row - radius_cells), min(grid.height, row + radius_cells + 1)
    c0, c1 = max(0, col - radius_cells), min(grid.width, col + radius_cells + 1)
    window = dem[r0:r1, c0:c1]
    valid = window != FLOAT_NODATA
    if not valid.any():
        return dem, {"dam_id": dam_id, "burned": False, "reason": "no valid DEM cells near the dam location"}
    bed_elev = float(window[valid].min())
    crest_elev = bed_elev + height

    max_steps = int(settings.crest_search_max_m / grid.cell_size_m)
    width_cells = max(1, int(round(width / grid.cell_size_m)))
    half_width = width_cells // 2

    out = dem.copy()
    cells_raised = 0
    crest_len_cells = 0
    for sign in (1, -1):
        for step in range(0, max_steps + 1):
            r = row + round(perp[0] * step * sign)
            c = col + round(perp[1] * step * sign)
            if not (0 <= r < grid.height and 0 <= c < grid.width):
                break
            if step > 0:
                crest_len_cells += 1
            terrain_here = dem[r, c]
            if step > 0 and terrain_here != FLOAT_NODATA and terrain_here >= crest_elev:
                break  # reached the natural valley wall
            for k in range(-half_width, half_width + 1):
                rr = r + round(direction[0] * k)
                cc = c + round(direction[1] * k)
                if not (0 <= rr < grid.height and 0 <= cc < grid.width):
                    continue
                if out[rr, cc] == FLOAT_NODATA:
                    continue
                if out[rr, cc] < crest_elev:
                    out[rr, cc] = crest_elev
                    cells_raised += 1

    info = {
        "dam_id": dam_id, "burned": True, "crest_elevation_m": crest_elev, "bed_elevation_m": bed_elev,
        "crest_length_cells": crest_len_cells, "crest_width_cells": width_cells, "cells_raised": cells_raised,
        "inputs_status": {
            "location": dam.location.status, "dam_height": dam.breach_inputs.dam_height.status,
            "average_embankment_width": dam.breach_inputs.average_embankment_width.status,
        },
    }
    return out, info


def burn_reservoir(dem: np.ndarray, water_mask: np.ndarray, reservoir_label: int) -> tuple[np.ndarray, dict]:
    """Flatten every cell labelled `reservoir_label` in `water_mask` to a single water-surface
    elevation (the median valid DEM value over those cells — a public surface DEM already returns
    roughly the water surface over a reservoir, so this mainly smooths noise, not bathymetry we
    don't have)."""
    cells = (water_mask == reservoir_label) & (dem != FLOAT_NODATA)
    if not cells.any():
        return dem, {"burned": False, "reason": "no reservoir cells in water_mask"}
    surface_elev = float(np.median(dem[cells]))
    out = dem.copy()
    out[cells] = surface_elev
    return out, {
        "burned": True, "cell_count": int(cells.sum()), "surface_elevation_m": surface_elev,
        "caveat": "bathymetry unknown from a surface DEM; the reservoir is flattened to a single water-surface elevation",
    }
