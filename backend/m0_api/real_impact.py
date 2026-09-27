"""Minimal direct-run impact summary from solver rasters and stored exposure.

This reports deterministic spatial intersections only. It does not interpret a
single FM run as an ensemble, price assets with placeholder factors, or fill
missing exposure layers with estimates.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import shapes
from rasterio.warp import reproject, transform_bounds
from rasterio.enums import Resampling
from shapely.geometry import shape
from shapely.ops import unary_union

CONTRACT_VERSION = "0.3.0"


def _estimate(value, unit: str, basis: str, source: str, *, confidence="LOW") -> dict:
    return {"value": value, "low": None, "high": None, "unit": unit,
            "interval": "none", "kind": "predicted", "confidence": confidence,
            "basis": basis, "source": source}


def _direct_rows(run_dir: Path) -> dict[str, list[dict]]:
    rows: dict[str, list[dict]] = {}
    with (run_dir / "timeseries.csv").open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            rows.setdefault(row["poi_id"], []).append(row)
    return rows


def build_impact(site_dir: Path, query_dir: Path) -> dict:
    result = json.loads((query_dir / "result.json").read_text(encoding="utf-8"))
    run_id = result["provenance"]["run_ids"][0]
    run_dir = site_dir / "runs" / run_id
    meta = json.loads((run_dir / "run_meta.json").read_text(encoding="utf-8"))
    exposure_dir = site_dir / "exposure"
    exposure_meta_path = exposure_dir / "provenance.json"
    exposure_meta = json.loads(exposure_meta_path.read_text()) if exposure_meta_path.is_file() else {}
    depth_path = query_dir / "layers" / "depth_p50.tif"
    if not depth_path.is_file() or not depth_path.stat().st_size:
        raise FileNotFoundError(f"real query depth layer is missing: {depth_path}")

    with rasterio.open(depth_path) as ds:
        depth = ds.read(1)
        nodata = ds.nodata if ds.nodata is not None else -9999.0
        valid = np.isfinite(depth) & (depth != nodata)
        threshold = float(meta["thresholds"]["extent_m"])
        wet = valid & (depth >= threshold)
        if not wet.any():
            flood = None
        else:
            polygons = [shape(geom) for geom, value in shapes(wet.astype(np.uint8), mask=wet,
                        transform=ds.transform) if value == 1]
            flood = unary_union(polygons)
        bounds = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds, densify_pts=21)
        profile = ds.profile.copy()
        depth_crs = ds.crs
        depth_transform = ds.transform
        depth_shape = ds.shape

    def read_exposure(name: str) -> gpd.GeoDataFrame:
        path = exposure_dir / name
        if not path.is_file():
            return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
        return gpd.read_file(path, bbox=tuple(bounds)).to_crs(depth_crs)

    buildings = read_exposure("buildings.gpkg")
    if flood is not None and not buildings.empty:
        affected_buildings = int(buildings.geometry.centroid.intersects(flood).sum())
    else:
        affected_buildings = 0

    roads = read_exposure("roads.gpkg")
    roads_m = 0.0
    if flood is not None and not roads.empty:
        roads_m = float(roads.geometry.intersection(flood).length.sum())

    facilities = read_exposure("facilities.gpkg")
    facility_counts = {"bridges": 0, "hospitals": 0, "schools": 0}
    if flood is not None and not facilities.empty:
        affected = facilities.geometry.intersects(flood)
        for idx, row in facilities.loc[affected].iterrows():
            kind = str(row.get("kind", "")).lower()
            if kind == "bridge": facility_counts["bridges"] += 1
            elif kind == "hospital": facility_counts["hospitals"] += 1
            elif kind == "school": facility_counts["schools"] += 1

    population_path = exposure_dir / "population.tif"
    population = None
    if population_path.is_file():
        population = np.full(depth_shape, -9999.0, dtype=np.float32)
        with rasterio.open(population_path) as src:
            reproject(source=rasterio.band(src, 1), destination=population,
                      src_transform=src.transform, src_crs=src.crs, src_nodata=src.nodata,
                      dst_transform=depth_transform, dst_crs=depth_crs, dst_nodata=-9999.0,
                      resampling=Resampling.sum)
    population_total = None
    if population is not None:
        pop_valid = np.isfinite(population) & (population != -9999.0)
        population_total = float(population[wet & pop_valid].sum()) if wet.any() else 0.0

    # Warning rows use only actual M3 history station values. The 0/1 field
    # denotes inundation in this one run, not a probability estimate.
    poi_rows = _direct_rows(run_dir)
    poi_path = (site_dir.parent / "teesta_pilot" / "terrain" / "pois.gpkg"
                if site_dir.name == "teesta" and run_id == "teesta_2023_mvp__delft3d"
                else site_dir / "terrain" / "pois.gpkg")
    warning_table, not_affected = [], 0
    if poi_path.is_file():
        pois = gpd.read_file(poi_path).to_crs(depth_crs)
        for poi in pois.to_dict("records"):
            samples = poi_rows.get(poi["poi_id"], [])
            if not samples:
                not_affected += 1
                continue
            max_depth = max(float(r["depth_m"]) for r in samples)
            max_velocity = max(float(r["velocity_ms"]) for r in samples)
            arrival = next((float(r["arrival_s_since_t0"]) for r in samples if r.get("arrival_s_since_t0")), None)
            if max_depth < threshold or arrival is None:
                not_affected += 1
                continue
            warning_table.append({"poi_id": poi["poi_id"], "name": poi["name"], "kind": poi["kind"],
                "chainage_m": float(poi["chainage_m"]), "zone": "possible", "p_inundation": 1.0,
                "arrival_s": _estimate(arrival, "s", "first threshold crossing in direct M3 history", run_id),
                "depth_m": _estimate(max_depth, "m", "maximum direct M3 history depth at station", run_id),
                "velocity_ms": _estimate(max_velocity, "m/s", "maximum direct M3 history velocity at station", run_id)})
    warning_table.sort(key=lambda row: row["arrival_s"]["value"])

    loss = {"value": None, "low": None, "high": None, "unit": "INR", "interval": "P10-P90",
            "kind": "predicted", "confidence": "LOW",
            "basis": "not computed: direct run has no P10/P50/P90 ensemble; required conversion factors remain placeholders",
            "source": run_id, "by_asset_class": {},
            "assumptions": ["economic loss unavailable for a single deterministic run",
                            "EUR-to-INR and price-index factors are placeholders",
                            "road width is a placeholder", "facilities and agriculture are not priced"]}
    caveats = [
        {"id": "direct_solver_output", "severity": "warning", "text_key": "caveat_direct_solver_output"},
        {"id": "mvp_reconstructed_forcing", "severity": "warning", "text_key": "mvp_reconstructed_forcing"},
        {"id": "single_run_impact", "severity": "warning", "text_key": "single_run_impact"},
        {"id": "impact_exposure_coverage", "severity": "warning", "text_key": "impact_exposure_coverage"},
        {"id": "placeholder_data", "severity": "warning", "text_key": "placeholder_data"},
    ]
    placeholders = ["loss_inr.eur_to_inr_2010", "loss_inr.price_index_2010_to_current",
                    "loss_inr.default_road_width_m"]
    coverage = ["Population uses WorldPop 2020 UN-adjusted counts at native ~1 km resolution, redistributed uniformly by the stored sum-preserving 30 m resampling; it is not building-level or current census data.",
                "Building, road and facility counts use the existing OpenStreetMap extract; its fetch timestamp is absent from provenance, so completeness and currency are unknown.",
                "The stored exposure extract was queried using the site's then-configured bbox; site configuration coordinates are marked as placeholders. Counts are only the spatial intersection with this georeferenced MVP pilot domain.",
                "The one deterministic FM extent is placed in the POSSIBLE bucket; this is not a probability or uncertainty classification.",
                "No cropland or hydropower exposure layer is present; these values are not assessed."]
    source_files = [f"{site_dir.name}/runs/{run_id}/run_meta.json",
                    f"{site_dir.name}/runs/{run_id}/timeseries.csv",
                    f"{site_dir.name}/queries/{query_dir.name}/layers/depth_p50.tif"]
    if exposure_meta_path.is_file():
        source_files.append(f"{site_dir.name}/exposure/provenance.json")
    for filename in ("population.tif", "buildings.gpkg", "roads.gpkg", "facilities.gpkg"):
        if (exposure_dir / filename).is_file(): source_files.append(f"{site_dir.name}/exposure/{filename}")
    return {"contract_version": CONTRACT_VERSION, "query_id": query_dir.name, "site_id": site_dir.name,
        "population_persons": _estimate(population_total, "persons",
             "sum of stored WorldPop cell counts in direct M3 cells at or above run extent threshold", "population.tif") if population_total is not None else
             {"value": None,"low": None,"high": None,"unit":"persons","interval":"none","kind":"predicted","confidence":"LOW","basis":"population raster missing","source":""},
        "assets": {"buildings": {"high": 0,"possible": affected_buildings},
                   "roads_m": {"high": 0.0,"possible": roads_m},
                   "bridges": {"high": 0,"possible": facility_counts["bridges"]},
                   "hospitals": {"high": 0,"possible": facility_counts["hospitals"]},
                   "schools": {"high": 0,"possible": facility_counts["schools"]},
                   "cropland_m2": {"high": 0.0,"possible": 0.0}, "hydropower": []},
        "loss_inr": loss, "warning_table": warning_table,
        "not_affected_poi_count": not_affected, "data_coverage_notes": coverage,
        "has_placeholders": True, "placeholder_fields": placeholders, "caveats": caveats,
        "provenance": {"method": "delft3d_direct", "contract_version": CONTRACT_VERSION,
                       "impact_method": "direct_solver_exposure_intersection",
                       "run_ids": [run_id], "output_classification": "REAL_SIMULATION_ARTIFACT",
                       "input_forcing_status": meta.get("input_forcing_status"),
                       "scientific_claim": meta.get("scientific_claim"),
                       "data_sources": ["src_048", "src_049"],
                       "exposure_sources": {"population": exposure_meta.get("population", {}),
                                            "osm": {"dataset": "OpenStreetMap contributors", "source_id": "src_048",
                                                    "fetch_timestamp": None,
                                                    "coverage_status": "unknown; pre-existing extract"},
                                            "population_source_id": "src_049"},
                       "source_files": source_files}}
