"""Load the frozen, solver-neutral M3 pilot exports.

These readers deliberately preserve source units and values. Spatial interpolation is done by
the caller at the solver's actual mesh locations.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class PilotInputs:
    domain: dict[str, np.ndarray]
    dem_xyv: np.ndarray
    roughness_xyv: np.ndarray
    breach_xy: tuple[float, float]
    hydrograph_min_q: np.ndarray
    pois: tuple[tuple[str, float, float], ...]


def load_pilot_inputs(directory: str | Path) -> PilotInputs:
    """Read domain.pol and companion XYZ/TIM exports from ``directory``."""
    root = Path(directory)
    domain: dict[str, np.ndarray] = {}
    lines = [line.strip() for line in (root / "domain.pol").read_text().splitlines() if line.strip()]
    cursor = 0
    while cursor < len(lines):
        name = lines[cursor]
        count = int(lines[cursor + 1].split()[0])
        domain[name] = np.asarray(
            [[float(v) for v in lines[cursor + 2 + j].split()[:2]] for j in range(count)],
            dtype=float,
        )
        cursor += count + 2

    dem = np.loadtxt(root / "dem_farfield.xyz", ndmin=2)
    roughness = np.loadtxt(root / "roughness_farfield.xyz", ndmin=2)
    if dem.shape != roughness.shape or not np.allclose(dem[:, :2], roughness[:, :2]):
        raise ValueError("DEM and Manning XYZ grids must have identical coordinates")
    breach_values = (root / "breach_location.xyz").read_text().split("*")[0].split()
    breach = (float(breach_values[0]), float(breach_values[1]))
    hydro = np.loadtxt(root / "hydrograph.tim", ndmin=2)
    points = []
    for line in (root / "pois.xyz").read_text().splitlines():
        if not line.strip():
            continue
        x, y, _, label, *_ = line.split()
        points.append((label, float(x), float(y)))
    return PilotInputs(domain, dem, roughness, breach, hydro, tuple(points))


def interpolate_xy(samples: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Bilinear interpolation on the complete regular XYZ grid, rejecting extrapolation."""
    from scipy.interpolate import RegularGridInterpolator

    xs = np.unique(samples[:, 0])
    ys = np.unique(samples[:, 1])
    values = np.full((len(ys), len(xs)), np.nan, dtype=float)
    cols = np.searchsorted(xs, samples[:, 0])
    rows = np.searchsorted(ys, samples[:, 1])
    values[rows, cols] = samples[:, 2]
    if np.isnan(values).any():
        raise ValueError("XYZ field is not a complete regular grid")
    interpolator = RegularGridInterpolator((ys, xs), values, bounds_error=True)
    return interpolator(np.column_stack((y, x)))


def pilot_mesh_geometry(inputs: PilotInputs, buffer_m: float = 400.0):
    """Return a MeshKernel polygon and explicit clipped inflow/outlet edge coordinates.

    The M1 export contains disconnected rasterized reach polygons. The buffer and bridge to the
    exported breach point are pilot choices; they make one connected mesh for this pilot only.
    """
    from shapely.geometry import LineString, Point, Polygon, box
    from shapely.ops import nearest_points, unary_union
    from meshkernel import GeometryList

    reaches = [Polygon(inputs.domain[key]) for key in ("L002", "L004", "L006")]
    original = unary_union(reaches)
    breach = Point(inputs.breach_xy)
    _, nearest = nearest_points(breach, original)
    bridge = LineString([breach, nearest])
    poi_buffers = [Point(x, y).buffer(90.0) for _, x, y in inputs.pois]
    # CHOSEN IN PILOT: bridge only a 90 m corridor from breach to nearest exported reach;
    # the broader 400 m buffer joins disconnected downstream reach polygons.
    min_x, min_y, max_x, max_y = original.bounds
    reach_buffer = original.buffer(buffer_m).intersection(
        box(min_x, min_y - buffer_m, max_x + buffer_m, max_y + buffer_m)
    )
    connected = unary_union([reach_buffer, bridge.buffer(90.0), *poi_buffers]).buffer(0)

    # CHOSEN IN PILOT: the upstream boundary is 90 m upstream of the breach point; the downstream
    # outlet is clipped at the original rasterized reach's lowest edge (before the 400 m buffer).
    upstream_x = inputs.breach_xy[0] - 75.0
    # Keep the clipped outlet inside the DEM's cell-centre interpolation domain.
    outlet_y = max(min(poly.bounds[1] for poly in reaches), float(inputs.dem_xyv[:, 1].min()))
    # CHOSEN IN PILOT: remove sub-grid-scale buffer/union vertices before clipping and meshing;
    # this is below the 90 m source grid and avoids near-zero-length boundary constraints.
    connected = connected.simplify(30.0, preserve_topology=True).buffer(0)
    clip = box(upstream_x, outlet_y, connected.bounds[2] + 10.0, connected.bounds[3] + 10.0)
    connected = connected.intersection(clip).buffer(0)
    if connected.geom_type != "Polygon":
        raise ValueError(f"pilot clip must yield one connected polygon; got {connected.geom_type}")

    def edge_at(axis: str, value: float) -> list[tuple[float, float]]:
        boundary = connected.boundary
        from shapely.geometry import LineString as LS
        if axis == "x":
            cut = LS([(value, connected.bounds[1] - 1), (value, connected.bounds[3] + 1)])
        else:
            cut = LS([(connected.bounds[0] - 1, value), (connected.bounds[2] + 1, value)])
        parts = [g for g in boundary.intersection(cut).geoms if g.geom_type == "LineString"] if boundary.intersection(cut).geom_type == "MultiLineString" else [boundary.intersection(cut)]
        parts = [g for g in parts if g.geom_type == "LineString" and g.length > 0]
        if not parts:
            raise ValueError(f"no mesh-boundary edge found at {axis}={value}")
        chosen = max(parts, key=lambda item: item.length)
        coords = list(chosen.coords)
        dense = [coords[0]]
        for (x0, y0), (x1, y1) in zip(coords, coords[1:]):
            length = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
            segments = max(1, int(np.ceil(length / 90.0)))
            dense.extend((x0 + (x1 - x0) * i / segments, y0 + (y1 - y0) * i / segments)
                         for i in range(1, segments + 1))
        return [(float(x), float(y)) for x, y in dense]

    raw_exterior = list(connected.exterior.coords)
    exterior = [raw_exterior[0]]
    for (x0, y0), (x1, y1) in zip(raw_exterior, raw_exterior[1:]):
        length = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        segments = max(1, int(np.ceil(length / 90.0)))
        exterior.extend((x0 + (x1 - x0) * i / segments, y0 + (y1 - y0) * i / segments)
                        for i in range(1, segments + 1))
    geometry = GeometryList(
        x_coordinates=[float(x) for x, _ in exterior],
        y_coordinates=[float(y) for _, y in exterior],
    )
    return geometry, edge_at("x", upstream_x), edge_at("y", outlet_y), connected.area


def summarize_dflowfm_pilot(
    case_dir: str | Path, output_dir: str | Path, spinup_s: float, stop_s: float
) -> dict:
    """Extract POI metrics and write a quick maximum-depth mesh map from D-Flow FM NetCDF."""
    import csv
    import json

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import xarray as xr
    from matplotlib.collections import PolyCollection

    case_dir, output_dir = Path(case_dir), Path(output_dir)
    his_path = next(output_dir.glob("*_his.nc"))
    map_path = next(output_dir.glob("*_map.nc"))

    his = xr.open_dataset(his_path)
    time_s = ((his.time.values - his.time.values[0]) / np.timedelta64(1, "s")).astype(float)
    start = int(np.searchsorted(time_s, spinup_s))
    station_names = [value.decode(errors="replace").strip() for value in his.station_id.values]
    poi_rows = []
    for index, name in enumerate(station_names):
        depth = np.asarray(his.waterdepth.values[:, index], dtype=float)
        velocity = np.asarray(his.velocity_magnitude.values[:, index], dtype=float)
        if np.all(np.isnan(depth)):
            poi_rows.append({"poi_id": name, "status": "outside_or_unsampled", "max_depth_m": None,
                             "max_velocity_ms": None, "arrival_s_since_t0": None})
            continue
        baseline = float(depth[start])
        after = np.arange(start, len(time_s))
        wet = after[np.isfinite(depth[after]) & (depth[after] > baseline + 0.1)]
        poi_rows.append({
            "poi_id": name,
            "status": "sampled",
            "max_depth_m": float(np.nanmax(depth[start:])),
            "max_velocity_ms": float(np.nanmax(velocity[start:])),
            "t0_depth_m": baseline,
            "arrival_s_since_t0": None if not len(wet) else float(time_s[wet[0]] - spinup_s),
            "arrival_rule": "first t >= 0 with depth > t0 depth + 0.1 m; UNCLEAR proposal in decisions.md",
        })
    (output_dir / "poi_metrics.json").write_text(json.dumps(poi_rows, indent=2) + "\n")

    ds = xr.open_dataset(map_path)
    elapsed_s = ((ds.time.values - ds.time.values[0]) / np.timedelta64(1, "s")).astype(float)
    maps_after_t0 = np.flatnonzero(elapsed_s >= spinup_s)
    depths = np.asarray(ds.mesh2d_waterdepth.values[maps_after_t0], dtype=float)
    speeds = np.asarray(ds.mesh2d_ucmag.values[maps_after_t0], dtype=float)
    max_depth = np.nanmax(depths, axis=0)
    max_speed = np.nanmax(speeds, axis=0)
    # Arrival is the first post-t0 120 s map sample exceeding the t0 depth by 0.1 m.
    t0_index = int(np.searchsorted(elapsed_s, spinup_s))
    t0_depth = np.asarray(ds.mesh2d_waterdepth.values[t0_index], dtype=float)
    wet = np.isfinite(depths) & (depths > t0_depth[np.newaxis, :] + 0.1)
    arrived = wet.any(axis=0)
    first_arrival_index = np.argmax(wet, axis=0)
    arrival_s = np.full(max_depth.shape, np.nan, dtype=float)
    arrival_s[arrived] = elapsed_s[maps_after_t0[first_arrival_index[arrived]]] - spinup_s
    valid = np.isfinite(max_depth)

    # The kernel reorders mesh faces in map output; use map-file connectivity and coordinates
    # together instead of pairing map values with the pre-run net file's face order.
    face_node_values = np.asarray(ds.mesh2d_face_nodes.values, dtype=float)
    nodes_x = np.asarray(ds.mesh2d_node_x.values)
    nodes_y = np.asarray(ds.mesh2d_node_y.values)
    face_nodes = np.where(np.isfinite(face_node_values), face_node_values - 1, -1).astype(int)
    polygons, polygon_depths = [], []
    for row, depth in zip(face_nodes, max_depth):
        row = row[row >= 0]
        if len(row) >= 3:
            polygons.append(np.column_stack((nodes_x[row], nodes_y[row])))
            polygon_depths.append(depth)
    fig, ax = plt.subplots(figsize=(10, 8), constrained_layout=True)
    collection = PolyCollection(polygons, array=np.asarray(polygon_depths), cmap="viridis", edgecolors="none")
    ax.add_collection(collection)
    ax.autoscale_view()
    ax.set_aspect("equal", adjustable="box")
    ax.set_title("Teesta pilot: maximum water depth after t0\nPLACEHOLDER — all inputs placeholder")
    ax.set_xlabel("UTM easting (m), EPSG:32645")
    ax.set_ylabel("UTM northing (m), EPSG:32645")
    fig.colorbar(collection, ax=ax, label="Maximum depth (m)")
    fig.savefig(output_dir / "quick_max_depth.png", dpi=150)
    plt.close(fig)

    with (output_dir / "max_face_summary.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["face_id", "x_m", "y_m", "max_depth_m", "max_velocity_ms", "arrival_s_since_t0"])
        for i, (x, y, d, v, arrival) in enumerate(zip(ds.mesh2d_face_x.values, ds.mesh2d_face_y.values,
                                                       max_depth, max_speed, arrival_s)):
            writer.writerow([i, float(x), float(y), float(d), float(v), "" if not np.isfinite(arrival) else float(arrival)])

    metrics = {
        "poi_metrics": poi_rows,
        "max_depth_m": float(np.nanmax(max_depth[valid])),
        "max_velocity_ms": float(np.nanmax(max_speed)),
        "arrival_s_since_t0": {"reached_face_count": int(arrived.sum()),
                               "unreached_face_count": int((~arrived).sum()),
                               "minimum_s": None if not arrived.any() else float(np.nanmin(arrival_s))},
        "arrival_map_interval_s": float(np.median(np.diff(elapsed_s[maps_after_t0]))) if len(maps_after_t0) > 1 else None,
        "max_depth_map": "quick_max_depth.png",
    }
    (output_dir / "summary_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    return metrics
