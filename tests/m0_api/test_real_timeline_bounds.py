"""Regression for docs/progress.md 2026-09-28 "STEP 2": real_timeline.create_timeline (the
"MVP path" -- it serves the Teesta MVP demo's timeline snapshots) used to emit `bounds_latlng`
axis-swapped, the same bug as real_query.py's direct-solver path. Both now delegate to the same
`backend.shared.grid.raster_bounds_latlng`; this proves the MVP path's own call site."""
from __future__ import annotations

import json

import numpy as np
import rasterio
import xarray as xr
from rasterio.transform import from_origin

from backend.m0_api import real_timeline


def test_mvp_timeline_bounds_latlng_is_lat_first(tmp_path):
    site_dir = tmp_path / "teesta"
    run_id = "s004__delft3d"
    run_dir = site_dir / "runs" / run_id
    case_dir = run_dir / "case"
    output_dir = case_dir / "output"
    output_dir.mkdir(parents=True)
    summary_dir = run_dir / "summary"
    summary_dir.mkdir(parents=True)

    # A Teesta-realistic UTM 45N summary raster (~28N, ~87E -- a magnitude check can't tell
    # these apart), matching the exact bug real_query.py's regression test also covers.
    profile = {"driver": "GTiff", "height": 1, "width": 1, "count": 1, "dtype": "float32",
               "crs": "EPSG:32645", "transform": from_origin(500000, 3100000, 30, 30),
               "nodata": -9999.0}
    with rasterio.open(summary_dir / "max_depth.tif", "w", **profile) as ds:
        ds.write(np.array([[1.0]], dtype="float32"), 1)

    # Minimal single-triangle FM map file: one face, one wet timestep.
    ds = xr.Dataset(
        data_vars={
            "mesh2d_face_nodes": (("mesh2d_nFaces", "mesh2d_nMax_face_nodes"),
                                   np.array([[0, 1, 2]], dtype=float)),
            "mesh2d_waterdepth": (("time", "mesh2d_nFaces"), np.array([[1.0]], dtype="float32")),
        },
        coords={
            "mesh2d_node_x": ("mesh2d_nNodes", np.array([500000.0, 500030.0, 500000.0])),
            "mesh2d_node_y": ("mesh2d_nNodes", np.array([3100000.0, 3100000.0, 3099970.0])),
            "time": np.array([0.0]),
        },
    )
    ds["mesh2d_face_nodes"].attrs["start_index"] = 0
    ds.to_netcdf(output_dir / "run_map.nc")

    (run_dir / "run_meta.json").write_text(json.dumps({"case_dir": "case", "thresholds": {"extent_m": 0.3}}))

    timeline_dir = real_timeline.create_timeline(site_dir, tmp_path / "query", run_id)
    payload = json.loads((timeline_dir / "timeline_data.json").read_text())

    (south, west), (north, east) = payload["bounds_latlng"]
    assert 27.0 < south < north < 29.0, f"expected latitudes ~27-29N, got south={south}, north={north}"
    assert 86.0 < west < east < 88.0, f"expected longitudes ~86-88E, got west={west}, east={east}"
