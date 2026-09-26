"""Provenance record: how `backend/m3_pilot/inputs/export/*` were produced for the M3 pilot
(`backend/m3_pilot/teesta_pilot_s001__anuga.py`). Not re-run; the exports are frozen.

Reads `data/teesta_pilot/terrain/` (M1 output on `backend/m3_pilot/inputs/teesta_pilot.yaml`) and
`data/teesta_pilot/breach/hydrographs/teesta_pilot_s001__south_lhonak.csv`. Writes to
`backend/m3_pilot/inputs/export/` (plain text; .pol/.tim layouts are Delft3D-style but solver-neutral):

    dem_farfield.xyz        DEM samples (UTM x, y, elevation_m), far-field grid cell centres
    roughness_farfield.xyz  Manning's n samples, same points
    domain.pol              far-field domain polygon (Delft3D .pol/.ldb text format)
    pois.xyz                POI locations in UTM, one per line, id as a 4th column comment
    breach_location.xyz     south_lhonak breach_location (M3 upstream boundary), UTM
    hydrograph.tim           south_lhonak triangular hydrograph, minutes since Tstart, m^3/s,
                             base_flow added as a constant offset
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio

REPO_ROOT = Path(__file__).resolve().parents[3]
TERRAIN_DIR = REPO_ROOT / "data" / "teesta_pilot" / "terrain"
HYDRO_CSV = REPO_ROOT / "data" / "teesta_pilot" / "breach" / "hydrographs" / "teesta_pilot_s001__south_lhonak.csv"
OUT_DIR = REPO_ROOT / "backend" / "m3_pilot" / "inputs" / "export"

BASE_FLOW_M3S = 60.0  # m3_pilot/inputs/teesta_pilot.yaml domains.far_field.inflow.base_flow
BREACH_LOCATION_LONLAT = (88.200, 27.905)  # south_lhonak.breach_location (teesta_pilot.yaml)
UTM_EPSG = 32645


def _raster_to_xyz(path: Path, nodata: float = -9999.0) -> np.ndarray:
    """Cell-centre (x, y, value) triples for every non-nodata pixel, in the raster's own CRS."""
    with rasterio.open(path) as ds:
        band = ds.read(1)
        transform = ds.transform
    rows, cols = np.where(band != nodata)
    xs, ys = rasterio.transform.xy(transform, rows, cols, offset="center")
    return np.column_stack([xs, ys, band[rows, cols]])


def write_xyz(path: Path, points: np.ndarray, fmt: str = "%.3f %.3f %.4f") -> None:
    np.savetxt(path, points, fmt=fmt)


def write_dem_and_roughness() -> None:
    write_xyz(OUT_DIR / "dem_farfield.xyz", _raster_to_xyz(TERRAIN_DIR / "dem.tif"))
    write_xyz(OUT_DIR / "roughness_farfield.xyz", _raster_to_xyz(TERRAIN_DIR / "roughness.tif"), fmt="%.3f %.3f %.5f")


def write_domain_pol() -> None:
    gdf = gpd.read_file(TERRAIN_DIR / "domain.gpkg")
    geom = gdf.geometry.iloc[0]
    polys = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
    lines = []
    for i, poly in enumerate(polys):
        coords = list(poly.exterior.coords)
        lines.append(f"L{i + 1:03d}")
        lines.append(f"{len(coords)} 2")
        lines += [f"{x:.3f} {y:.3f}" for x, y in coords]
    (OUT_DIR / "domain.pol").write_text("\n".join(lines) + "\n")


def write_pois() -> None:
    gdf = gpd.read_file(TERRAIN_DIR / "pois.gpkg")
    lines = [f"{geom.x:.3f} {geom.y:.3f} * {poi_id} ({kind})"
             for geom, poi_id, kind in zip(gdf.geometry, gdf["poi_id"], gdf["kind"])]
    (OUT_DIR / "pois.xyz").write_text("\n".join(lines) + "\n")


def write_breach_location() -> None:
    import pyproj

    transformer = pyproj.Transformer.from_crs("EPSG:4326", f"EPSG:{UTM_EPSG}", always_xy=True)
    x, y = transformer.transform(*BREACH_LOCATION_LONLAT)
    (OUT_DIR / "breach_location.xyz").write_text(
        f"{x:.3f} {y:.3f} * south_lhonak breach_location ({BREACH_LOCATION_LONLAT[0]}, {BREACH_LOCATION_LONLAT[1]} deg)\n"
    )


def write_hydrograph_tim() -> None:
    """Delft3D `.tim`: time in minutes since Tstart, one value column (discharge, m^3/s), with
    `base_flow` added as a constant offset (docs/decisions.md 2026-09-25 base_flow placement)."""
    t_s, q_m3s = [], []
    lines = HYDRO_CSV.read_text().splitlines()[1:]  # skip "t_s,q_m3s" header
    for line in lines:
        t, q = line.split(",")
        t_s.append(float(t))
        q_m3s.append(float(q))
    t_min = np.array(t_s) / 60.0
    q_total = np.array(q_m3s) + BASE_FLOW_M3S
    out_lines = [f"{t:.4f} {q:.3f}" for t, q in zip(t_min, q_total)]
    (OUT_DIR / "hydrograph.tim").write_text("\n".join(out_lines) + "\n")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_dem_and_roughness()
    write_domain_pol()
    write_pois()
    write_breach_location()
    write_hydrograph_tim()
    print(f"wrote export files to {OUT_DIR}")


if __name__ == "__main__":
    main()
