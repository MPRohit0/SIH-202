"""Deterministic, explicitly synthetic artifacts for the I-1 plumbing path.

This module creates small file-contract artifacts. It is not a hydraulic model.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin

CONTRACT_VERSION = "0.3.0"
NODATA = -9999.0
WIDTH = HEIGHT = 48
CELL_M = 100.0
EPSG = 32645
WEST, SOUTH, EAST, NORTH = 88.45, 27.45, 88.55, 27.55
ORIGIN_X, ORIGIN_Y = Transformer.from_crs(4326, EPSG, always_xy=True).transform(WEST, NORTH)
_TO_WGS84 = Transformer.from_crs(EPSG, 4326, always_xy=True)
_EAST_LON, _SOUTH_LAT = _TO_WGS84.transform(ORIGIN_X + WIDTH * CELL_M, ORIGIN_Y - HEIGHT * CELL_M)
BOUNDS = [[_SOUTH_LAT, WEST], [NORTH, _EAST_LON]]
SYNTHETIC_CAVEAT = {"id": "synthetic_demo", "severity": "warning", "text_key": "caveat_synthetic_demo"}


def _write_tif(path: Path, array: np.ndarray, dtype: str = "float32", nodata: float = NODATA) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", width=WIDTH, height=HEIGHT, count=1,
                       dtype=dtype, crs=f"EPSG:{EPSG}",
                       transform=from_origin(ORIGIN_X, ORIGIN_Y, CELL_M, CELL_M),
                       nodata=nodata, compress="LZW", tiled=True) as dst:
        dst.write(array.astype(dtype), 1)


def create_site_artifacts(site_id: str, data_dir: Path) -> None:
    """Create deterministic terrain + representative synthetic run artifacts."""
    root = data_dir / site_id
    rr, cc = np.mgrid[:HEIGHT, :WIDTH]
    valley = np.abs(cc - (WIDTH * .52 + (rr - HEIGHT / 2) * .12))
    terrain = (2200 - rr * 2.2 + valley * 7).astype(np.float32)
    domain = np.ones((HEIGHT, WIDTH), np.uint8)
    depth = np.maximum(0, 5.2 - valley * .48 - np.maximum(0, rr - 34) * .04).astype(np.float32)
    depth[depth < .3] = 0
    velocity = np.where(depth > 0, .7 + depth * .42, 0).astype(np.float32)
    arrival = np.where(depth > .1, 120 + rr * 42 + valley * 30, NODATA).astype(np.float32)
    for name, arr in (("dem.tif", terrain), ("domain_mask.tif", domain),
                      ("depth.tif", depth), ("max_depth.tif", depth),
                      ("max_velocity.tif", velocity), ("arrival_time.tif", arrival)):
        _write_tif(root / ("terrain" if name in {"dem.tif", "domain_mask.tif"} else "runs/demo_valley_demo_s001__synthetic/summary") / name,
                   arr, "uint8" if name == "domain_mask.tif" else "float32", 255 if name == "domain_mask.tif" else NODATA)
    grid = {"contract_version": CONTRACT_VERSION, "site_id": site_id, "grid_id": "farfield", "crs_epsg": EPSG,
            "origin_x": ORIGIN_X, "origin_y": ORIGIN_Y, "cell_size_m": CELL_M, "width": WIDTH,
            "height": HEIGHT, "nodata": NODATA, "pixel_is": "area"}
    (root / "terrain/grid.json").write_text(json.dumps(grid, indent=2) + "\n")
    run = root / "runs/demo_valley_demo_s001__synthetic"
    run.mkdir(parents=True, exist_ok=True)
    (run / "run_meta.json").write_text(json.dumps({"contract_version": CONTRACT_VERSION,
        "run_id": "demo_valley_demo_s001__synthetic", "scenario_id": "demo_valley_demo_s001", "model": "synthetic",
        "status": "completed", "solver_version": None, "resolution_m": CELL_M, "dp_m": None, "particle_count": None,
        "peak_vram_mb": None, "sim_duration_s": 2400, "wall_time_s": 0.0, "mass_balance_error_pct": None,
        "thresholds": {"extent_m":.3,"arrival_m":.1}, "hydrographs":["synthetic timeline fixture"],
        "resampling":"none; generated directly on the synthetic canonical grid", "warnings":[],
        "caveats":["synthetic_demo: integration fixture only; no solver or hydraulic model was run"],
        "has_placeholders":False,"placeholder_fields":[],"started_at":"2026-09-27T00:00:00Z","finished_at":"2026-09-27T00:00:00Z",
        "provenance": {"source": "I-1 deterministic synthetic fixture", "synthetic": True}}, indent=2) + "\n")
    _write_extent(root / "runs/demo_valley_demo_s001__synthetic/summary/extent.geojson", site_id, depth)


def _write_extent(path: Path, site_id: str, depth: np.ndarray) -> None:
    # Compact bbox polygons in frontend CRS; synthetic geometry is clearly labeled.
    features = []
    for zone, mask in (("high", depth >= 2.0), ("possible", (depth >= .3) & (depth < 2.0))):
        ys, xs = np.where(mask)
        if len(xs):
            west, south = _TO_WGS84.transform(ORIGIN_X + xs.min()*CELL_M, ORIGIN_Y - (ys.max()+1)*CELL_M)
            east, north = _TO_WGS84.transform(ORIGIN_X + (xs.max()+1)*CELL_M, ORIGIN_Y - ys.min()*CELL_M)
            features.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[west,south],[east,south],[east,north],[west,north],[west,south]]]},
                             "properties": {"site_id": site_id, "zone": zone, "synthetic": True}})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}, indent=2) + "\n")


def create_query(site_id: str, query_id: str, request: dict, data_dir: Path, placeholder_fields: list[str] | None = None) -> dict:
    """Write query layers and derive response summary from the written arrays."""
    root = data_dir / site_id / "queries" / query_id
    root.mkdir(parents=True, exist_ok=True)
    run_summary = data_dir / site_id / "runs/demo_valley_demo_s001__synthetic/summary"
    with rasterio.open(run_summary / "max_depth.tif") as ds: depth = ds.read(1)
    with rasterio.open(run_summary / "max_velocity.tif") as ds: velocity = ds.read(1)
    with rasterio.open(run_summary / "arrival_time.tif") as ds: arrival = ds.read(1)
    rr, cc = np.mgrid[:HEIGHT, :WIDTH]
    probability = np.where(depth >= .3, .96, np.where(depth > 0, .24, 0)).astype(np.float32)
    extent = np.where(depth >= 2, 2, np.where(depth >= .3, 1, 0)).astype(np.uint8)
    layers_dir = root / "layers"
    for name, arr in (("depth_p50", depth), ("velocity_p50", velocity), ("arrival_p50", arrival),
                      ("p_inundation", probability), ("extent_class", extent),
                      ("depth_p10", depth*.85), ("depth_p90", depth*1.15),
                      ("arrival_p10", np.where(arrival != NODATA, arrival*.9, NODATA)),
                      ("arrival_p90", np.where(arrival != NODATA, arrival*1.1, NODATA)),
                      ("velocity_p90", velocity*1.15)):
        _write_tif(layers_dir / f"{name}.tif", arr, "uint8" if name == "extent_class" else "float32", 255 if name == "extent_class" else NODATA)
    _write_extent(root / "extent.geojson", site_id, depth)
    _write_extent(layers_dir / "extent.geojson", site_id, depth)
    tdir = root / "timeline"; tdir.mkdir(parents=True, exist_ok=True)
    for band, mult in (("p10", .9), ("p50", 1.0), ("p90", 1.1)):
        _write_tif(tdir / f"arrival_{band}.tif", np.where(arrival != NODATA, arrival*mult, NODATA))
    _write_tif(tdir / "extent_class.tif", extent, "uint8", 255)
    chain_cols = np.rint(WIDTH * .52 + (np.arange(10) * 4 - HEIGHT / 2) * .12).astype(int)
    profile = []
    for i, col in enumerate(chain_cols):
        sample = float(arrival[min(i*4, HEIGHT-1), np.clip(col,0,WIDTH-1)])
        if sample == NODATA: continue
        profile.append({"chainage_m":float(i*CELL_M),"arrival_p10_s":sample*.9,"arrival_p50_s":sample,"arrival_p90_s":sample*1.1})
    meta = {"t_end_s": 2400, "bounds_latlng": BOUNDS, "hydrographs": [{"dam_id": f"{site_id}__synth_lake", "t_offset_s": 0,
            "points": [{"t_s":0,"q_m3s":0},{"t_s":300,"q_m3s":100},{"t_s":1200,"q_m3s":30},{"t_s":2400,"q_m3s":0}]}],
            "arrival_profile": profile,
            "pois_on_profile": [{"poi_id":f"{site_id}__poi__town","name":"Demo Town","chainage_m":2400}], "caveats":[SYNTHETIC_CAVEAT],
            "provenance":{"method":"empirical_fallback","contract_version":CONTRACT_VERSION,"synthetic":True,"source":"I-1 deterministic synthetic fixture"}}
    (tdir / "timeline_data.json").write_text(json.dumps(meta, indent=2)+"\n")
    wet = depth >= .3
    max_depth = float(depth.max()); max_vel = float(velocity.max()); area = float(wet.sum()*CELL_M*CELL_M)
    sample_r, sample_c = 24, int(chain_cols[6]); sample_depth=float(depth[sample_r,sample_c]); sample_arrival=float(arrival[sample_r,sample_c]); sample_vel=float(velocity[sample_r,sample_c])
    response = _base_response(site_id, query_id, request, max_depth, max_vel, area, placeholder_fields or [], sample_arrival)
    (root / "result.json").write_text(json.dumps(response, indent=2)+"\n")
    impact = {"contract_version":CONTRACT_VERSION,"query_id":query_id,"site_id":site_id,
        "population_persons":_est(int(wet.sum()*12),"persons","zone_range"),
        "assets":{"buildings":{"high":int((extent==2).sum()//15),"possible":int((extent==1).sum()//20)},"roads_m":{"high":float((extent==2).sum()*5),"possible":float((extent==1).sum()*3)},"bridges":{"high":1,"possible":0},"hospitals":{"high":0,"possible":0},"schools":{"high":0,"possible":1},"cropland_m2":{"high":0,"possible":0},"hydropower":[]},
        "loss_inr":_est(None,"INR","P10-P90"),"warning_table":[{"poi_id":f"{site_id}__poi__town","name":"Demo Town","kind":"village","chainage_m":2400,"zone":"high","p_inundation":float(probability[sample_r,sample_c]),"arrival_s":_est(sample_arrival,"s","P10-P90"),"depth_m":_est(sample_depth,"m","P10-P90"),"velocity_ms":_est(sample_vel,"ms","P10-P90")}],
        "not_affected_poi_count":0,"data_coverage_notes":["Synthetic demo exposure counts; not population or asset observations."],"has_placeholders":False,"placeholder_fields":[],"caveats":[SYNTHETIC_CAVEAT],"provenance":{"method":"empirical_fallback","contract_version":CONTRACT_VERSION,"synthetic":True,"artifact":"result.json layers"}}
    (root / "impact.json").write_text(json.dumps(impact,indent=2)+"\n")
    return response


def _est(v, unit, interval="P10-P90"):
    return {"value":v,"low":v if v is not None else None,"high":v if v is not None else None,"unit":unit,"interval":interval,"kind":"predicted","confidence":"LOW"}


def _base_response(site_id, query_id, request, max_depth, max_vel, area, placeholder_fields, first_arrival):
    common = {"contract_version":CONTRACT_VERSION,"query_id":query_id,"site_id":site_id,"status":"complete","method":"empirical_fallback","mode":request["mode"],
      "resolved_inputs":{},"summary":{"inundated_area_m2":_est(area,"m2"),"max_depth_m":_est(max_depth,"m"),"max_velocity_ms":_est(max_vel,"ms"),"peak_discharge_m3s":_est(None,"m3s"),
      "first_arrival":{"poi_id":f"{site_id}__poi__town","name":"Demo Town","arrival_s":_est(first_arrival,"s")}},
      "confidence":{k:{"level":"LOW","components":{"synthetic_demo":"NOT_SCIENTIFIC"},"reason_key":"conf_empirical_fallback"} for k in ("overall","extent","depth","arrival","velocity")},
      "layers":[],"vectors":{"extent_url":f"/api/v1/flood/{query_id}/extent.geojson"},"flags":{"outside_trained_range":False,"demo_mode":True,"library_outdated":False,"has_placeholders":bool(placeholder_fields)},"placeholder_fields":placeholder_fields,"caveats":[SYNTHETIC_CAVEAT],
      "provenance":{"method":"empirical_fallback","synthetic":True,"contract_version":CONTRACT_VERSION,"run_ids":[f"{site_id}_demo_s001__synthetic"],"source":"I-1 deterministic synthetic fixture","created_at":"2026-09-27T00:00:00Z"},"timing_ms":{"median_phase":0,"full_phase":0}}
    for layer, style, unit in (("depth_p50","depth_p50","m"),("velocity_p50","velocity_p50","ms"),("arrival_p50","arrival_p50","s"),("extent_class","extent_class",None),("p_inundation","p_inundation",None)):
        common["layers"].append({"layer_id":layer,"type":"raster_png","url":f"/api/v1/flood/{query_id}/layers/{layer}.png","bounds_latlng":BOUNDS,"style_id":style,"unit":unit,"available":True})
    return common
