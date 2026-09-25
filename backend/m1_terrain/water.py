"""M1: lake/reservoir extent, so `dem.py`'s DEM is masked instead of sink-filled at water bodies
and `burn.py` can flatten reservoirs (`docs/handoff_contract.md` §4.1 `dem.tif` "lake masked (not
filled)"). Decided this session (`docs/decisions.md` 2026-09-25 "M1 water extent"): water comes
from ESA WorldCover's permanent-water class, restricted to the component touching each dam's
`location` within `TerrainSettings.snap_radius_m` — a moraine-dammed lake or a dam's reservoir
both sit immediately against the dam point by construction, so this needs no flow-direction pass.
An optional vector polygon (e.g. M7's future `lake_latest.geojson`) overrides WorldCover entirely
when supplied."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy import ndimage

from backend.shared.grid import CanonicalGrid, lonlat_to_rowcol
from backend.shared.site_config import Dam
from backend.shared.site_config import SiteConfig

from .settings import TerrainSettings

LAND, LAKE, RESERVOIR = np.uint8(0), np.uint8(1), np.uint8(2)

#: `Dam.kind` -> water_mask label. A landslide dam behaves like a moraine dam (a natural lake
#: impounded behind debris); embankment/concrete dams have an engineered reservoir.
_KIND_TO_LABEL = {
    "moraine_dammed_lake": LAKE,
    "landslide_dam": LAKE,
    "embankment_dam": RESERVOIR,
    "concrete_dam": RESERVOIR,
}


def _dam_row_col(dam: Dam, grid: CanonicalGrid) -> tuple[int, int] | None:
    loc = dam.location.value
    if loc is None:
        return None
    row, col = lonlat_to_rowcol(grid, loc[0], loc[1], strict=False)
    if row < 0:
        return None
    return row, col


def water_mask(
    landcover: np.ndarray,
    cfg: SiteConfig,
    grid: CanonicalGrid,
    settings: TerrainSettings,
    *,
    polygon_mask: np.ndarray | None = None,
) -> tuple[np.ndarray, dict]:
    """`(mask, info)`. `mask` is uint8 on `grid`: 0 land, 1 lake, 2 reservoir. `info` lists, per
    dam id, whether a water component was found and its cell count, for `provenance.json`.

    `polygon_mask` (optional): a boolean array already rasterized onto `grid` (e.g. from a vector
    override) marking every water cell regardless of source; when given, WorldCover's water class
    is ignored and every dam within range of a connected polygon component claims it."""
    if polygon_mask is not None:
        water_bool = polygon_mask.astype(bool)
        source = "polygon_override"
    else:
        water_bool = landcover == settings.lake_class_code
        source = "worldcover"

    labelled, n_components = ndimage.label(water_bool, structure=np.ones((3, 3), dtype=bool))
    radius_cells = settings.snap_radius_m / grid.cell_size_m

    out = np.zeros(grid.shape, dtype=np.uint8)
    info: dict[str, dict] = {}
    claimed_components: set[int] = set()

    for dam in cfg.dams:
        rc = _dam_row_col(dam, grid)
        dam_id = dam.id
        if rc is None:
            info[dam_id] = {"found": False, "reason": "dam location is a placeholder"}
            continue
        row, col = rc
        r0, r1 = max(0, row - int(np.ceil(radius_cells))), min(grid.height, row + int(np.ceil(radius_cells)) + 1)
        c0, c1 = max(0, col - int(np.ceil(radius_cells))), min(grid.width, col + int(np.ceil(radius_cells)) + 1)
        window = labelled[r0:r1, c0:c1]
        window_ids = set(np.unique(window)) - {0}
        if not window_ids:
            info[dam_id] = {"found": False, "reason": f"no water component within {settings.snap_radius_m} m"}
            continue

        # pick the closest component (by nearest cell) if more than one is in range
        best_id, best_dist2 = None, None
        for comp_id in window_ids:
            comp_cells = window == comp_id
            rr, cc = np.nonzero(comp_cells)
            if rr.size == 0:
                continue
            d2 = ((rr + r0 - row) ** 2 + (cc + c0 - col) ** 2).min()
            if best_dist2 is None or d2 < best_dist2:
                best_dist2, best_id = d2, comp_id

        label = _KIND_TO_LABEL[dam.kind]
        component_bool = labelled == best_id
        out[component_bool] = label
        claimed_components.add(best_id)
        info[dam_id] = {
            "found": True, "label": "lake" if label == LAKE else "reservoir",
            "cell_count": int(component_bool.sum()), "source": source,
        }

    return out, {"source": source, "n_components_total": int(n_components), "dams": info}
