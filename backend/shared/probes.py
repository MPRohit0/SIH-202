"""Probe points shared between M3 (Delft3D) and M4 (SPH), so `timeseries.csv` (contract §4.4,
keyed by `poi_id`) means the same physical points for both models. Source: M1's `pois.gpkg`
(§4.1), POIs from the site config snapped to the far-field grid."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd


@dataclass(frozen=True)
class Probe:
    poi_id: str
    name: str
    kind: str
    x_m: float
    y_m: float


def load_probes(terrain_dir: str | Path) -> list[Probe]:
    """Read `<terrain_dir>/pois.gpkg` (far-field UTM points) into `Probe`s. Empty list if the
    site config has no points of interest (the file is only written when there are POIs to
    snap -- `backend/m1_terrain/pipeline.py`)."""
    path = Path(terrain_dir) / "pois.gpkg"
    if not path.is_file():
        return []
    gdf = gpd.read_file(path)
    return [
        Probe(poi_id=row.poi_id, name=row.name, kind=row.kind, x_m=row.geometry.x, y_m=row.geometry.y)
        for row in gdf.itertuples()
    ]
