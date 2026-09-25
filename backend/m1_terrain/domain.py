"""M1: the valley-corridor model domain (`docs/handoff_contract.md` §4.1 `domain_mask.tif`,
`domain.gpkg`) — every cell within `TerrainSettings.domain_max_hand_m` of the main channel (by
HAND) and connected to it, so Delft3D's mesh covers the corridor a flood can plausibly reach
without ballooning out to the whole DEM extent. Cells "downhill enough" but on the far side of a
ridge from the channel (a disconnected patch of low HAND in a neighbouring valley) are excluded by
requiring connectivity to the channel, not just a HAND threshold."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import rasterio.features
from scipy import ndimage
from shapely.geometry import shape
from shapely.ops import unary_union

from backend.shared.grid import FLOAT_NODATA, CanonicalGrid


def domain_mask(hand_m: np.ndarray, channel_mask: np.ndarray, max_hand_m: float) -> np.ndarray:
    """uint8 (1 = in the model domain, 0 = outside): the connected component(s) of
    `hand_m <= max_hand_m` that touch a channel cell."""
    candidate = (hand_m != FLOAT_NODATA) & (hand_m <= max_hand_m)
    labelled, _ = ndimage.label(candidate, structure=np.ones((3, 3), dtype=bool))
    touched = set(np.unique(labelled[channel_mask])) - {0}
    mask = np.isin(labelled, sorted(touched)) if touched else np.zeros_like(candidate)
    return mask.astype(np.uint8)


def domain_polygon(mask: np.ndarray, grid: CanonicalGrid) -> gpd.GeoDataFrame:
    """The domain mask polygonised into a single-row GeoDataFrame (one, possibly multi-part,
    polygon) in the grid's CRS."""
    shapes = rasterio.features.shapes(mask, mask=mask.astype(bool), transform=grid.transform)
    geoms = [shape(geom) for geom, value in shapes if value == 1]
    if not geoms:
        raise ValueError("domain mask is empty; cannot build domain.gpkg")
    return gpd.GeoDataFrame({"site_id": [grid.site_id]}, geometry=[unary_union(geoms)], crs=grid.crs.to_epsg())
