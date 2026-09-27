"""Common-footprint comparison of the real Teesta MVP D-Flow and SPH artifacts."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import rasterio
import xarray as xr
from rasterio.features import rasterize

from backend.m0_api import registry, rendering
from backend.shared.grid import FLOAT_NODATA, CanonicalGrid, write_grid_raster

from .teesta_mvp import M3_RUN_ID, M4_RUN_ID, SCENARIO_ID, SITE_ID


def build_comparison(data_dir: str | Path, *, m3_run_dir: str | Path, m4_run_dir: str | Path,
                     terrain_dir: str | Path, routed_manifest: str | Path) -> Path:
    """Rasterize the actual D-Flow time window onto the SPH crop and compare actual M4 maps."""
    root, m3, m4, terrain = map(Path, (data_dir, m3_run_dir, m4_run_dir, terrain_dir))
    m3_meta = json.loads((m3 / "run_meta.json").read_text())
    m4_meta = json.loads((m4 / "run_meta.json").read_text())
    route = json.loads(Path(routed_manifest).read_text())
    if m3_meta.get("solver_status") != "REAL_SOLVER_OUTPUT" or m4_meta.get("status") != "postprocessed":
        raise ValueError("comparison requires registered real D-Flow and postprocessed SPH outputs")
    if route.get("source_m3_run_id") != M3_RUN_ID:
        raise ValueError("routed artifact source does not match Teesta MVP D-Flow run")
    grid = CanonicalGrid.from_json(terrain / "grid_nearfield.json")
    meta_case = json.loads((m4 / "case" / "case_meta.json").read_text())
    t0, t1 = route["provenance"]["time_window_source_s"]
    map_path = m3 / m3_meta["case_dir"] / "output" / "teesta_pilot_s001__dflowfm_map.nc"
    with xr.open_dataset(map_path) as ds:
        t = (ds.time.values - ds.time.values[0]) / np.timedelta64(1, "s")
        choose = (t >= t0) & (t <= t1)
        if choose.sum() < 2:
            raise ValueError("D-Flow map has fewer than two records in the comparison window")
        depth_values = np.nanmax(ds.mesh2d_waterdepth.values[choose], axis=0)
        speed_values = np.nanmax(ds.mesh2d_ucmag.values[choose], axis=0)
        nodes = np.column_stack((ds.mesh2d_node_x.values, ds.mesh2d_node_y.values))
        geoms_depth, geoms_speed = [], []
        for row, depth, speed in zip(ds.mesh2d_face_nodes.values, depth_values, speed_values):
            ids = row[np.isfinite(row)].astype(int) - 1
            coords = nodes[ids]
            if len(coords) < 3:
                continue
            from shapely.geometry import Polygon
            poly = Polygon(coords)
            if poly.is_valid and not poly.is_empty:
                geoms_depth.append((poly, float(max(depth, 0.0))))
                geoms_speed.append((poly, float(max(speed, 0.0))))
        dmask = rasterize(((g, 1) for g, _ in geoms_depth), out_shape=grid.shape,
                          transform=grid.transform, fill=0, dtype="uint8") > 0
        ddepth = rasterize(geoms_depth, out_shape=grid.shape, transform=grid.transform,
                           fill=FLOAT_NODATA, dtype="float32")
        dvel = rasterize(geoms_speed, out_shape=grid.shape, transform=grid.transform,
                         fill=FLOAT_NODATA, dtype="float32")
    sph_dir = m4 / "summary_nearfield"
    with rasterio.open(sph_dir / "max_depth.tif") as ds:
        sph_depth = ds.read(1)
        if ds.crs != grid.crs or ds.transform != grid.transform or sph_depth.shape != grid.shape:
            raise ValueError("SPH depth raster is not on the declared MVP near-field grid")
    with rasterio.open(sph_dir / "max_velocity.tif") as ds:
        sph_vel = ds.read(1)
    valid = dmask & (ddepth != FLOAT_NODATA) & (sph_depth != FLOAT_NODATA)
    if not valid.any():
        raise ValueError("D-Flow and SPH artifacts have no common valid cells")
    diff = np.full(grid.shape, FLOAT_NODATA, dtype=np.float32)
    diff[valid] = sph_depth[valid] - ddepth[valid]
    out = root / SITE_ID / "compare" / SCENARIO_ID
    out.mkdir(parents=True, exist_ok=True)
    write_grid_raster(out / "delft3d_depth_window.tif", np.where(valid, ddepth, FLOAT_NODATA), grid)
    write_grid_raster(out / "sph_depth_window.tif", np.where(valid, sph_depth, FLOAT_NODATA), grid)
    write_grid_raster(out / "depth_diff.tif", diff, grid)

    wet_d, wet_s = valid & (ddepth >= 0.3), valid & (sph_depth >= 0.3)
    union = wet_d | wet_s
    intersection = wet_d & wet_s
    iou = float(intersection.sum() / union.sum()) if union.any() else 1.0
    f1 = float(2 * intersection.sum() / (wet_d.sum() + wet_s.sum())) if (wet_d.sum() + wet_s.sum()) else 1.0
    wet_union = valid & union
    depth_rmse = float(np.sqrt(np.mean((sph_depth[wet_union] - ddepth[wet_union]) ** 2))) if wet_union.any() else None
    vel_valid = wet_union & (sph_vel != FLOAT_NODATA) & (dvel != FLOAT_NODATA)
    vel_mae = float(np.mean(np.abs(sph_vel[vel_valid] - dvel[vel_valid]))) if vel_valid.any() else None
    pixel_area = grid.cell_size_m ** 2
    darea, sarea = float(wet_d.sum() * pixel_area), float(wet_s.sum() * pixel_area)

    # Preserve the Compare component's supported arrival probe fields when both files have data.
    probes = []
    m4_series = m4 / "timeseries.csv"
    m3_his = m3 / m3_meta["case_dir"] / "output" / "teesta_pilot_s001__dflowfm_his.nc"
    if m4_series.is_file() and m3_his.is_file():
        with xr.open_dataset(m3_his) as his:
            names = [x.decode(errors="replace") if isinstance(x, bytes) else str(x) for x in his.station_name.values]
            ix = next((i for i, n in enumerate(names) if "poi__chungthang" in n), None)
            if ix is not None:
                ht = (his.time.values - his.time.values[0]) / np.timedelta64(1, "s")
                hd = his.waterdepth[:, ix].values
                hsel = (ht >= t0) & (ht <= t1)
                d_arrival = next((float(ht[j] - t0) for j in np.where(hsel)[0] if hd[j] > 0.1), None)
            else:
                d_arrival = None
        rows = list(csv.DictReader(m4_series.open(newline="", encoding="utf-8")))
        sr = [r for r in rows if r["poi_id"] == "teesta__poi__chungthang" and
              float(r["t_s"]) <= float(meta_case["t_end_s"])]
        s_arrival = next((float(r["t_s"]) for r in sr if float(r["depth_m"]) > 0.1), None)
        if d_arrival is not None and s_arrival is not None:
            probes.append({"poi_id": "teesta__poi__chungthang", "arrival_delft3d_s": d_arrival,
                           "arrival_sph_s": s_arrival, "diff_s": s_arrival - d_arrival})

    result = {
        "site_id": SITE_ID, "scenario_id": SCENARIO_ID,
        "sph_vs_delft3d": {"available": True, "domain": "MVP_NEAR_FIELD",
            "time_window_s": float(t1 - t0), "metrics": {
                "iou": iou, "f1_0_3": f1, "depth_rmse_wet_m": depth_rmse,
                "velocity_mae_ms": vel_mae, "flooded_area_delft3d_m2": darea,
                "flooded_area_sph_m2": sarea, "flooded_area_difference_m2": sarea - darea,
                "common_valid_cell_count": int(valid.sum())},
            "probes": probes,
            "layers": [{"layer_id": "depth_diff_nearfield", "type": "raster_png",
                "url": f"/api/v1/files/{SITE_ID}/compare/{SCENARIO_ID}/depth_diff.png",
                "bounds_latlng": grid.bounds_latlng, "style_id": "depth_diff", "unit": "m", "available": True}],
            "run_ids": [M3_RUN_ID, M4_RUN_ID]},
        "emulator_vs_physics": {"available": False, "held_out_run_id": None, "metrics": {}, "layers": []},
        "gp_vs_linear": {}, "when_to_use_key": "when_to_use_sph_delft3d",
        "caveats": [{"id": "direct_solver_output", "severity": "warning", "text_key": "direct_solver_output"},
                    {"id": "mvp_reconstructed_forcing", "severity": "warning", "text_key": "mvp_reconstructed_forcing"}],
        "provenance": {"domain_status": "MVP_NEAR_FIELD", "m3_run_id": M3_RUN_ID,
                       "m4_run_id": M4_RUN_ID, "comparison_grid": str(terrain / "grid_nearfield.json"),
                       "m3_source_window_s": [t0, t1], "comparison_method": "M3 UGRID window maxima rasterized onto M4 10m crop; valid-footprint intersection",
                       "solver_warnings": m4_meta.get("warnings", []),
                       "sph_caveats": m4_meta.get("caveats", [])},
    }
    sidecar = out / "compare.json"
    sidecar.write_text(json.dumps(result, indent=2) + "\n")
    return sidecar


def render_mvp_depth_diff(data_dir: str | Path, scenario_id: str) -> bytes:
    tif = Path(data_dir) / SITE_ID / "compare" / scenario_id / "depth_diff.tif"
    return rendering.render_and_cache(tif, "depth_diff")
