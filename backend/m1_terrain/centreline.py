"""M1: main-channel centreline with chainage, and POIs snapped onto it
(`docs/handoff_contract.md` §4.1 `centreline.gpkg`, `chainage_samples.csv`, `pois.gpkg`).

t0 (CLAUDE.md rule 6) is the most-upstream breach, so chainage starts at 0 there: the centreline
is `hydro.trace_downstream` from the most-upstream dam's `breach_location` (snapped onto the
drainage network by flow accumulation) all the way to the grid's outlet."""

from __future__ import annotations

import numpy as np
import pandas as pd

from backend.shared.grid import CanonicalGrid, lonlat_to_rowcol
from backend.shared.site_config import Dam, PointOfInterest, SiteConfig

from .hydro import FlowNetwork, best_accumulation_cell, trace_downstream
from .settings import TerrainSettings

CONTRACT_VERSION = "0.3.0"


def find_breach_cell(
    dam: Dam, network: FlowNetwork, grid: CanonicalGrid, settings: TerrainSettings
) -> tuple[int, int] | None:
    """Snap `dam.breach_location` onto the highest-accumulation (most channel-like) cell within
    `settings.snap_radius_m`. `None` if the location is a placeholder or falls outside the grid."""
    loc = dam.breach_location.value
    if loc is None:
        return None
    row, col = lonlat_to_rowcol(grid, loc[0], loc[1], strict=False)
    if row < 0:
        return None
    radius_cells = settings.snap_radius_m / grid.cell_size_m
    return best_accumulation_cell(network.accumulation, row, col, radius_cells)


def trace_centreline(network: FlowNetwork, start_row: int, start_col: int, grid: CanonicalGrid) -> pd.DataFrame:
    """Every cell on the D8 path from `(start_row, start_col)` to its outlet, downstream order,
    with raw (uneven, D8-step) chainage. Columns: `row, col, x_m, y_m, chainage_m`."""
    path = trace_downstream(network, start_row, start_col)
    w = grid.width
    rows, cols = path // w, path % w
    x = grid.origin_x + (cols + 0.5) * grid.cell_size_m
    y = grid.origin_y - (rows + 0.5) * grid.cell_size_m
    step_dist = np.hypot(np.diff(x), np.diff(y))
    chainage = np.concatenate(([0.0], np.cumsum(step_dist)))
    return pd.DataFrame({"row": rows, "col": cols, "x_m": x, "y_m": y, "chainage_m": chainage})


def resample_chainage(path: pd.DataFrame, dem: np.ndarray, cell_size_m: float) -> pd.DataFrame:
    """`path` (from `trace_centreline`) resampled onto a regular chainage grid every
    `cell_size_m`, with bed elevation from `dem`. Contract §4.1 `chainage_samples.csv`
    (`chainage_m,x_m,y_m,bed_elev_m`)."""
    total = path["chainage_m"].iloc[-1]
    n_samples = int(total // cell_size_m) + 1
    chainage_m = np.arange(n_samples) * cell_size_m
    x_m = np.interp(chainage_m, path["chainage_m"], path["x_m"])
    y_m = np.interp(chainage_m, path["chainage_m"], path["y_m"])
    raw_rows = np.interp(chainage_m, path["chainage_m"], path["row"]).round().astype(int)
    raw_cols = np.interp(chainage_m, path["chainage_m"], path["col"]).round().astype(int)
    bed_elev_m = dem[np.clip(raw_rows, 0, dem.shape[0] - 1), np.clip(raw_cols, 0, dem.shape[1] - 1)]
    return pd.DataFrame({"chainage_m": chainage_m, "x_m": x_m, "y_m": y_m, "bed_elev_m": bed_elev_m})


def channel_mask_from_path(path: pd.DataFrame, grid: CanonicalGrid) -> np.ndarray:
    """Boolean raster on `grid`, True on the traced centreline cells — the "main channel" used by
    `roughness.py` (class 999) and `hydro.hand` (the reference for height-above-drainage)."""
    mask = np.zeros(grid.shape, dtype=bool)
    mask[path["row"].to_numpy(), path["col"].to_numpy()] = True
    return mask


def snap_pois(
    site_id: str,
    pois: list[PointOfInterest],
    path: pd.DataFrame,
    grid: CanonicalGrid,
) -> pd.DataFrame:
    """Each POI snapped to its nearest centreline cell. Columns match contract §4.1 `pois.gpkg`:
    `poi_id, name, kind, chainage_m, dist_to_channel_m, row, col`. A POI with a placeholder
    location is skipped (not written) and returned separately as a list of skipped ids."""
    path_x, path_y = path["x_m"].to_numpy(), path["y_m"].to_numpy()
    rows = []
    skipped = []
    for poi in pois:
        loc = poi.location.value
        if loc is None:
            skipped.append(poi.id)
            continue
        row, col = lonlat_to_rowcol(grid, loc[0], loc[1], strict=False)
        if row < 0:
            skipped.append(poi.id)
            continue
        x = grid.origin_x + (col + 0.5) * grid.cell_size_m
        y = grid.origin_y - (row + 0.5) * grid.cell_size_m
        d2 = (path_x - x) ** 2 + (path_y - y) ** 2
        nearest = int(np.argmin(d2))
        rows.append({
            "poi_id": f"{site_id}__poi__{poi.id}", "name": poi.name, "kind": poi.category,
            "chainage_m": float(path["chainage_m"].iloc[nearest]),
            "dist_to_channel_m": float(np.sqrt(d2[nearest])),
            "row": row, "col": col,
        })
    return pd.DataFrame(rows), skipped
