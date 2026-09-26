"""ANUGA Phase-A spike: minimal Teesta flood-routing test.

Inputs (from backend/m3_pilot/inputs/export/, all status: placeholder):
  - domain.pol            Delft3D enclosure export -- 3 disjoint valley-reach
                           polygons (L002, L004, L006) plus small marker boxes.
                           SIMPLIFICATION (spike only, see report): meshed as
                           the convex hull of those 3 polygons' vertices plus
                           breach_location.xyz, so the mesh is one connected
                           piece the whole way down the valley. The true
                           disjoint-polygon domain needs proper reach-stitching
                           (a generator.py concern for Phase B, not this spike).
  - dem_farfield.xyz       611x623 regular grid, 90 m spacing -> elevation
  - roughness_farfield.xyz same grid -> Manning's n
  - breach_location.xyz    single point, South Lhonak breach
  - hydrograph.tim         time (minutes) vs discharge (m^3/s), base_flow
                           included; injected at the breach via Inlet_operator
  - pois.xyz               4 gauge points (lachen, chungthang,
                           sangkalang_bridge, mangan_district_hospital)

Boundary conditions: Transmissive_boundary on the whole exterior (walls are
mostly dry high ground in this coarse hull, so this only matters at the
downstream end, per the brief).
"""
import time
import numpy as np
from scipy.interpolate import RegularGridInterpolator
from shapely.geometry import Polygon, Point
from shapely.ops import unary_union

import anuga

t_wall_start = time.time()
EXPORT_DIR = "."


def read_pol_blocks(path):
    blocks = {}
    with open(path) as f:
        lines = [l.strip() for l in f if l.strip()]
    i = 0
    while i < len(lines):
        name = lines[i]
        n, _ncol = map(int, lines[i + 1].split())
        coords = [tuple(map(float, lines[i + 2 + j].split()[:2])) for j in range(n)]
        blocks[name] = coords
        i += 2 + n
    return blocks


def grid_interpolator(xyz_path):
    d = np.loadtxt(xyz_path)
    xs = np.unique(d[:, 0])
    ys = np.unique(d[:, 1])
    grid = np.full((len(ys), len(xs)), np.nan)
    xi = np.searchsorted(xs, d[:, 0])
    yi = np.searchsorted(ys, d[:, 1])
    grid[yi, xi] = d[:, 2]
    # RegularGridInterpolator wants strictly increasing axes; grid is (y, x)
    return RegularGridInterpolator((ys, xs), grid, bounds_error=False, fill_value=None)


print("Loading domain.pol, DEM, roughness ...")
blocks = read_pol_blocks(f"{EXPORT_DIR}/domain.pol")
reach_polys = [Polygon(blocks[k]) for k in ("L002", "L004", "L006")]

breach_line = open(f"{EXPORT_DIR}/breach_location.xyz").read().split()
breach_xy = (float(breach_line[0]), float(breach_line[1]))

# The 3 reach polygons in domain.pol are disjoint (separate curvilinear grid
# blocks). Buffer + union to stitch them (and the breach point) into one
# connected mesh footprint, then simplify to keep the vertex count sane.
# This is a coarse spike approximation -- see module docstring.
BUFFER_M = 400.0
merged = unary_union([p.buffer(BUFFER_M) for p in reach_polys]
                      + [Point(breach_xy).buffer(BUFFER_M)])
assert merged.geom_type == "Polygon", (
    f"expected a single connected polygon, got {merged.geom_type}: "
    "increase BUFFER_M"
)
domain_poly = merged.simplify(60.0, preserve_topology=True)
boundary_polygon = list(domain_poly.exterior.coords)[:-1]  # drop closing dup
print(f"Boundary polygon: {len(boundary_polygon)} vertices, "
      f"area = {domain_poly.area / 1e6:.1f} km^2")

elev_interp = grid_interpolator(f"{EXPORT_DIR}/dem_farfield.xyz")
rough_interp = grid_interpolator(f"{EXPORT_DIR}/roughness_farfield.xyz")

pois = []
for line in open(f"{EXPORT_DIR}/pois.xyz"):
    parts = line.split(None, 3)
    x, y = float(parts[0]), float(parts[1])
    label = parts[3].lstrip("* ").strip() if len(parts) > 3 else f"poi_{len(pois)}"
    pois.append((label, x, y))

hydro = np.loadtxt(f"{EXPORT_DIR}/hydrograph.tim")
hydro_t_sec = hydro[:, 0] * 60.0
hydro_q = hydro[:, 1]
print(f"Hydrograph: {len(hydro)} points, t in [0, {hydro_t_sec[-1]:.0f}] s, "
      f"Q in [{hydro_q.min():.1f}, {hydro_q.max():.1f}] m^3/s")


def discharge(t):
    return float(np.interp(t, hydro_t_sec, hydro_q))


print("Building mesh ...")
domain = anuga.create_domain_from_regions(
    boundary_polygon,
    boundary_tags={"exterior": list(range(len(boundary_polygon)))},
    maximum_triangle_area=20000.0,  # ~140 m equivalent cell -- coarse spike mesh
)
domain.set_name("teesta_pilot_spike")
domain.set_flow_algorithm("DE0")
print(f"Mesh built: {domain.get_number_of_triangles()} triangles")

xll = domain.geo_reference.get_xllcorner()
yll = domain.geo_reference.get_yllcorner()


def elevation_fn(x, y):
    pts = np.column_stack([y + yll, x + xll])  # interpolator is (y, x)
    return elev_interp(pts)


def friction_fn(x, y):
    pts = np.column_stack([y + yll, x + xll])
    return rough_interp(pts)


domain.set_quantity("elevation", function=elevation_fn, location="centroids")
domain.set_quantity("friction", function=friction_fn, location="centroids")
domain.set_quantity("stage", function=elevation_fn, location="centroids")  # dry bed

domain.set_boundary({"exterior": anuga.Transmissive_boundary(domain)})

inlet_region = anuga.Region(domain, center=breach_xy, radius=150.0)
inlet = anuga.Inlet_operator(domain, inlet_region, Q=discharge)
print(f"Inlet at {breach_xy}, enclosed triangles: {len(inlet_region.indices)}")

FINALTIME = 30000.0  # s (~8.3 h; hydrograph itself runs to ~6.5 h)
YIELDSTEP = 300.0  # s

gauge_records = {label: {"t": [], "depth": [], "speed": []} for label, _, _ in pois}
poi_xy_abs = [(x, y) for _, x, y in pois]  # get_values(interpolation_points=..) wants absolute coords

print(f"Evolving to finaltime={FINALTIME:.0f} s, yieldstep={YIELDSTEP:.0f} s ...")
peak_mem_mb = 0.0
for t in domain.evolve(yieldstep=YIELDSTEP, finaltime=FINALTIME):
    domain.print_timestepping_statistics()
    stage_q = domain.get_quantity("stage")
    elev_q = domain.get_quantity("elevation")
    xmom_q = domain.get_quantity("xmomentum")
    ymom_q = domain.get_quantity("ymomentum")
    for (label, _, _), (lx, ly) in zip(pois, poi_xy_abs):
        pt = [[lx, ly]]
        stage_v = stage_q.get_values(interpolation_points=pt)[0]
        elev_v = elev_q.get_values(interpolation_points=pt)[0]
        depth = max(stage_v - elev_v, 0.0)
        if depth > 1e-6:
            u = xmom_q.get_values(interpolation_points=pt)[0] / depth
            v = ymom_q.get_values(interpolation_points=pt)[0] / depth
            speed = float(np.hypot(u, v))
        else:
            speed = 0.0
        gauge_records[label]["t"].append(t)
        gauge_records[label]["depth"].append(float(depth))
        gauge_records[label]["speed"].append(speed)

wallclock = time.time() - t_wall_start
print(f"WALLCLOCK_SECONDS={wallclock:.1f}")

DEPTH_ARRIVAL_THRESHOLD = 0.1  # m
print("\n=== POI summary ===")
for label, _, _ in pois:
    rec = gauge_records[label]
    depths = np.array(rec["depth"])
    speeds = np.array(rec["speed"])
    ts = np.array(rec["t"])
    max_depth = float(depths.max())
    max_speed = float(speeds.max())
    arrivals = ts[depths > DEPTH_ARRIVAL_THRESHOLD]
    arrival = float(arrivals[0]) if len(arrivals) else None
    print(f"{label}: max_depth={max_depth:.2f} m, max_speed={max_speed:.2f} m/s, "
          f"arrival_time(>{DEPTH_ARRIVAL_THRESHOLD}m)="
          f"{arrival if arrival is not None else 'never'}"
          f"{'' if arrival is None else ' s'}")

np.savez("teesta_pilot_gauges.npz",
          **{f"{label}_{k}": np.array(v) for label, rec in gauge_records.items()
             for k, v in rec.items()})
print("Saved gauge arrays to teesta_pilot_gauges.npz")
