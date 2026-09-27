"""Controlled contract tests for direct-run timeline and impact adapters.

The fixtures here validate plumbing only; they are not scientific test data.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString, Point, Polygon

from backend.m0_api import timeline
from backend.m0_api.real_impact import build_impact
from backend.m0_api.schemas import validate


def _write_raster(path: Path, array: np.ndarray, *, crs="EPSG:32645", transform=None, nodata=-9999):
    path.parent.mkdir(parents=True, exist_ok=True)
    transform = transform or from_origin(0, 30, 10, 10)
    with rasterio.open(path, "w", driver="GTiff", width=array.shape[1], height=array.shape[0],
                       count=1, dtype=array.dtype, crs=crs, transform=transform, nodata=nodata) as dst:
        dst.write(array, 1)


def test_direct_timeline_renders_real_snapshot_artifact(tmp_path):
    timeline_dir = tmp_path / "timeline"
    _write_raster(timeline_dir / "depth_t120.tif", np.array([[0, 1], [0, 2]], dtype=np.float32),
                  transform=from_origin(0, 20, 10, 10))
    sidecar = {"mode": "delft3d_snapshots", "t_end_s": 120.0, "frames": [
        {"t_s": 120, "file": "depth_t120.tif", "wet_cells": 2, "max_depth_m": 2.0}],
        "bounds_latlng": [[88.0, 27.0], [88.1, 27.1]], "hydrographs": [],
        "arrival_profile": [], "pois_on_profile": [], "caveats": [],
        "provenance": {"method": "delft3d_direct", "contract_version": "0.3.0"}}
    (timeline_dir / "timeline_data.json").write_text(json.dumps(sidecar))
    response = timeline.build_response("teesta", timeline_dir, "q_20260927T000000Z_000001", 300)
    validate("timeline.schema.json", response)
    frame = response["frames"][0]
    assert frame["t_s"] == 120
    assert frame["bounds_latlng"] == sidecar["bounds_latlng"]
    png = timeline.render_frame(timeline_dir, "median", 120)
    assert png.startswith(b"\x89PNG\r\n\x1a\n") and len(png) > 50
    assert timeline.render_frame(timeline_dir, "high", 120) == png
    assert timeline.render_frame(timeline_dir, "possible", 120) == png


def test_direct_impact_uses_registered_depth_and_exposure(tmp_path):
    site = tmp_path / "teesta"
    query = site / "queries" / "q_20260927T000000Z_000002"
    run = site / "runs" / "teesta_2023_mvp__delft3d"
    exposure = site / "exposure"
    depth = np.array([[0, 0, 0], [0, 1, 0], [0, 0, 0]], dtype=np.float32)
    transform = from_origin(0, 30, 10, 10)
    _write_raster(query / "layers" / "depth_p50.tif", depth, transform=transform)
    _write_raster(exposure / "population.tif", np.full((3, 3), 2, dtype=np.float32), transform=transform)
    run.mkdir(parents=True)
    (run / "run_meta.json").write_text(json.dumps({"thresholds": {"extent_m": 0.3},
        "input_forcing_status": "MVP_RECONSTRUCTED", "scientific_claim": "NOT_OBSERVED_HYDROGRAPH"}))
    with (run / "timeseries.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["poi_id", "t_s", "depth_m", "velocity_ms", "arrival_s_since_t0"])
        writer.writeheader()
    (query / "result.json").write_text(json.dumps({"method": "delft3d_direct",
        "provenance": {"run_ids": ["teesta_2023_mvp__delft3d"]}}))

    # Transform the wet-cell centre to the source exposure CRS and place one
    # building centroid, road segment, and bridge on that actual wet cell.
    projected = gpd.GeoSeries([Point(15, 15)], crs="EPSG:32645").to_crs("EPSG:4326").iloc[0]
    gpd.GeoDataFrame({"osm_id": ["b1"], "kind": ["residential"], "name": ["test"]},
                     geometry=[Polygon([(projected.x - .00001, projected.y - .00001),
                                        (projected.x + .00001, projected.y - .00001),
                                        (projected.x + .00001, projected.y + .00001),
                                        (projected.x - .00001, projected.y + .00001)])],
                     crs="EPSG:4326").to_file(exposure / "buildings.gpkg", driver="GPKG")
    road = gpd.GeoSeries([LineString([(14, 10), (16, 20)])], crs="EPSG:32645").to_crs("EPSG:4326").iloc[0]
    gpd.GeoDataFrame({"osm_id": ["r1"], "kind": ["road"], "name": ["test"]},
                     geometry=[road], crs="EPSG:4326").to_file(exposure / "roads.gpkg", driver="GPKG")
    gpd.GeoDataFrame({"osm_id": ["f1"], "kind": ["bridge"], "name": ["test"]},
                     geometry=[projected], crs="EPSG:4326").to_file(exposure / "facilities.gpkg", driver="GPKG")

    result = build_impact(site, query)
    validate("impact.schema.json", result)
    assert result["population_persons"]["value"] == 2
    assert result["population_persons"]["low"] is None
    assert result["assets"]["buildings"]["possible"] == 1
    assert result["assets"]["bridges"]["possible"] == 1
    assert result["loss_inr"]["value"] is None
    assert "src_049" in result["provenance"]["data_sources"]
