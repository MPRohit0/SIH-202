"""M1: flow routing — priority-flood pit filling, an implicit D8 drainage tree, flow accumulation
and HAND (height above nearest drainage), all built with plain numpy/heapq instead of richdem
(not installed for this Python/numpy combination; `docs/decisions.md` 2026-09-25 "M1 flow
routing").

Method: Barnes, Lehman & Mulla (2014) priority-flood, "epsilon" variant, so the filled DEM has a
strict downhill gradient everywhere (breaks flat/plateau ties that would otherwise stall D8). The
flood also builds the drainage tree for free: it floods *inward* from the grid boundary and any
nodata cell (both valid places for water to leave the modelled domain) in ascending elevation
order, so a newly-visited cell's *parent* is the already-visited neighbour that reached it first —
always a step closer to an outlet, i.e. downstream. `flow_accumulation` and `hand` are then single
linear passes over cells in visit order, since a parent is always visited before its children."""

from __future__ import annotations

import heapq
from dataclasses import dataclass

import numpy as np

from backend.shared.grid import FLOAT_NODATA

_NEIGHBOR_OFFSETS = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))

NO_PARENT = -1


@dataclass
class FlowNetwork:
    """`route()`'s output. All arrays are `(height, width)` except `visit_order`, which is flat
    row-major indices in the order cells were flooded (outlets first)."""

    filled: np.ndarray        # float32, pit-filled DEM (nodata cells keep FLOAT_NODATA)
    parent: np.ndarray        # int64, flat index of the downstream neighbour; NO_PARENT at outlets
    visit_order: np.ndarray   # (n_visited,) int64
    accumulation: np.ndarray  # int64, >=1 — number of cells (including itself) draining through it


def route(dem: np.ndarray, *, epsilon: float = 1e-5) -> FlowNetwork:
    """Priority-flood fill + drainage tree + flow accumulation on `dem` (float32, nodata
    `backend.shared.grid.FLOAT_NODATA`)."""
    h, w = dem.shape
    n = h * w
    flat = dem.reshape(-1).astype(np.float64, copy=False)
    nodata_mask = flat == FLOAT_NODATA

    filled = np.empty(n, dtype=np.float64)
    parent = np.full(n, NO_PARENT, dtype=np.int64)
    visited = np.zeros(n, dtype=bool)
    visit_order = np.empty(n, dtype=np.int64)
    visit_count = 0

    boundary = np.zeros((h, w), dtype=bool)
    boundary[0, :] = boundary[-1, :] = True
    boundary[:, 0] = boundary[:, -1] = True
    seed_mask = boundary.reshape(-1) | nodata_mask

    heap: list[tuple[float, int]] = []
    for i in np.nonzero(seed_mask)[0]:
        elev = -np.inf if nodata_mask[i] else flat[i]
        filled[i] = elev
        visited[i] = True
        heapq.heappush(heap, (elev, int(i)))

    while heap:
        elev, i = heapq.heappop(heap)
        visit_order[visit_count] = i
        visit_count += 1
        r, c = divmod(i, w)
        for dr, dc in _NEIGHBOR_OFFSETS:
            rr, cc = r + dr, c + dc
            if rr < 0 or rr >= h or cc < 0 or cc >= w:
                continue
            j = rr * w + cc
            if visited[j]:
                continue
            visited[j] = True
            parent[j] = i
            new_elev = elev if nodata_mask[j] else max(flat[j], elev + epsilon)
            filled[j] = new_elev
            heapq.heappush(heap, (new_elev, j))

    visit_order = visit_order[:visit_count]
    filled[nodata_mask] = FLOAT_NODATA  # don't leak the -inf seed value into the output raster

    accumulation = np.ones(n, dtype=np.int64)
    for i in visit_order[::-1]:
        p = parent[i]
        if p != NO_PARENT:
            accumulation[p] += accumulation[i]

    return FlowNetwork(
        filled=filled.reshape(h, w).astype(np.float32),
        parent=parent.reshape(h, w),
        visit_order=visit_order,
        accumulation=accumulation.reshape(h, w),
    )


def hand(network: FlowNetwork, channel_mask: np.ndarray) -> np.ndarray:
    """Height above nearest drainage: for each cell, the elevation of the nearest channel cell
    (`channel_mask` True) on its downstream path (via `network.parent`), subtracted from its own
    filled elevation. A cell whose downstream path reaches an outlet without ever crossing a
    channel cell — a real drainage divide with no channel inside the modelled domain — gets
    nodata, never a guessed value (CLAUDE.md rule 3 extends to derived rasters)."""
    h, w = network.filled.shape
    n = h * w
    flat_elev = network.filled.reshape(-1).astype(np.float64)
    flat_channel = channel_mask.reshape(-1)
    flat_parent = network.parent.reshape(-1)

    target = np.full(n, NO_PARENT, dtype=np.int64)
    for i in network.visit_order:  # parent already resolved before its children, by construction
        if flat_channel[i]:
            target[i] = i
        else:
            p = flat_parent[i]
            target[i] = target[p] if p != NO_PARENT else NO_PARENT

    found = target != NO_PARENT
    out = np.full(n, FLOAT_NODATA, dtype=np.float32)
    out[found] = (flat_elev[found] - flat_elev[target[found]]).astype(np.float32)
    out[flat_elev == FLOAT_NODATA] = FLOAT_NODATA
    return out.reshape(h, w)


def trace_downstream(network: FlowNetwork, start_row: int, start_col: int) -> np.ndarray:
    """Flat row-major indices from `(start_row, start_col)` to its outlet, following
    `network.parent` (inclusive of the start cell, ending at the outlet)."""
    w = network.parent.shape[1]
    path = [start_row * w + start_col]
    parent_flat = network.parent.reshape(-1)
    while True:
        p = parent_flat[path[-1]]
        if p == NO_PARENT:
            break
        path.append(int(p))
    return np.array(path, dtype=np.int64)


def best_accumulation_cell(
    accumulation: np.ndarray, row: int, col: int, radius_cells: float
) -> tuple[int, int]:
    """The `(row, col)` of the highest-accumulation cell within `radius_cells` of `(row, col)` —
    used to snap an approximate point (a dam's `breach_location`, a POI) onto the drainage
    network."""
    h, w = accumulation.shape
    r = int(np.ceil(radius_cells))
    r0, r1 = max(0, row - r), min(h, row + r + 1)
    c0, c1 = max(0, col - r), min(w, col + r + 1)
    window = accumulation[r0:r1, c0:c1]
    rr, cc = np.unravel_index(np.argmax(window), window.shape)
    return r0 + int(rr), c0 + int(cc)
