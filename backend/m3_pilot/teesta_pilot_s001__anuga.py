"""M3 pilot: Teesta teesta_pilot_s001, ANUGA, hand-written reference case.

PLACEHOLDER — teesta_pilot_s001, all inputs placeholder.

Independent reference for the backend/m3_anuga generator reproduction test (docs/m3_spec.md,
Phase 3). Self-contained on purpose: nothing is imported from backend/.

Tags on every modelling choice:
  SOURCED          value/rule taken from an input file or a project doc (cited)
  ANUGA DEFAULT    left at ANUGA 4.0.1's default, stated explicitly
  CHOSEN IN PILOT  picked here by hand; the reason is given
  UNCLEAR          not settled; needs a decision before real use

Inputs (backend/m3_pilot/inputs/export/, produced by inputs/make_export.py from M1/M2 output
on inputs/teesta_pilot.yaml — every value there is status: placeholder):
  domain.pol, dem_farfield.xyz, roughness_farfield.xyz, breach_location.xyz, hydrograph.tim,
  pois.xyz

Outputs (backend/m3_pilot/outputs/):
  teesta_pilot_s001__anuga.sww  ANUGA result. NOTE: sww `time` is relative to the sww
                                `starttime` attribute; seconds since t0 = time + starttime.
  gauges/<poi_id>.csv           t_s, depth_m, velocity_ms, wse_m at each POI, every yieldstep
  max_centroids.csv             per triangle: x, y, elevation, manning_n, max depth/speed, arrival
  mesh_summary.json, run_meta_pilot.json

Run:  python backend/m3_pilot/teesta_pilot_s001__anuga.py    (≈ minutes; see run_meta_pilot.json)
"""
import csv
import heapq
import json
import resource
import time
from pathlib import Path

import numpy as np
from scipy.interpolate import RegularGridInterpolator
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

import anuga
from anuga.operators.collect_max_quantities_operator import Collect_max_quantities_operator

WALL_START = time.time()
RUN_LABEL = "PLACEHOLDER — teesta_pilot_s001, all inputs placeholder"
HERE = Path(__file__).resolve().parent
INPUTS = HERE / "inputs" / "export"
OUT = HERE / "outputs"
(OUT / "gauges").mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------------------------
# 1. Parameters
# ---------------------------------------------------------------------------------------------
# SOURCED: inputs/teesta_pilot.yaml domains.far_field.grid_resolution = 90 m (placeholder);
# the DEM/roughness .xyz files are that 90 m grid. Mesh sizes below scale with it.
GRID_RES_M = 90.0
# SOURCED: inputs/teesta_pilot.yaml crs.utm_epsg (placeholder) — UTM 45N, CLAUDE.md rule 7.
UTM_EPSG = 32645

# CHOSEN IN PILOT: 400 m is the smallest buffer (tried 200/400/600 m) that joins the three
# disjoint reach polygons in domain.pol and the breach point into ONE polygon. ANUGA needs one
# connected mesh for water to pass from reach to reach.
DOMAIN_BUFFER_M = 400.0
# CHOSEN IN PILOT: simplify the buffered outline (5 000+ vertices) at 60 m (< one 90 m cell) to
# keep the mesher's boundary constraints manageable (~340 vertices).
OUTLINE_SIMPLIFY_M = 60.0
# CHOSEN IN PILOT: reach polygons follow 90 m raster steps; simplify at half a cell.
REACH_SIMPLIFY_M = GRID_RES_M / 2

# CHOSEN IN PILOT (mesh resolution, as factor x GRID_RES_M^2):
#   corridor (the original domain.pol reach polygons): max triangle area K_CORRIDOR * res^2
#   rest of the buffered outline (valley walls):        max triangle area K_OUTER * res^2
# The Phase A spike used one area of 20 000 m^2 (~2.5 res^2) everywhere; centroid-sampled
# elevation on such triangles dammed the narrow gorge ~15 km below the breach (13.6 m pool on a
# 4 m DEM depression). K_CORRIDOR was reduced until water reached the downstream POIs.
K_CORRIDOR = 0.25
K_OUTER = 2.5

# CHOSEN IN PILOT: inlet = all triangles whose centroid is within 2 grid cells of the breach
# point, so the inflow spreads over several triangles instead of 1-3.
INLET_RADIUS_M = 2 * GRID_RES_M

# CHOSEN IN PILOT: spin-up duration before t0. During spin-up the inlet delivers Q(t0) — the
# base flow — so the channel is wet when the breach hydrograph starts (docs/decisions.md
# 2026-09-25 "base_flow"). Length picked from a trial: the time until the downstream boundary
# outflow stays within 5 % of the base flow and domain storage changes by < 1 %/h.
T_SPINUP_S = 43200.0
# CHOSEN IN PILOT: 60 s output interval; the shortest arrival band is 15 min
# (docs/impact_outputs.md §2), so 60 s resolves it with margin.
YIELDSTEP_S = 60.0
# CHOSEN IN PILOT: write the .sww every 5 min (every 5th yieldstep) to keep it small; gauges,
# maxima and arrival are tracked at every yieldstep / timestep regardless.
SWW_OUTPUTSTEP_S = 300.0
# CHOSEN IN PILOT: run to end of hydrograph (23 282 s) plus enough time for the peak to pass the
# farthest in-domain POI (checked in the trial).
FINALTIME_S = 43200.0

# SOURCED: arrival threshold 0.1 m (docs/handoff_contract.md §1.5 arrival_m, docs/m5_specs.md §4).
# UNCLEAR (proposed contract clarification, docs/decisions.md 2026-09-26): with a wet channel,
# arrival = first t >= 0 where depth exceeds the depth at t0 by > 0.1 m. The literal rule
# (depth > 0.1 m) is written alongside as arrival_literal_s.
ARRIVAL_M = 0.10
# SOURCED: wet-cell cut-off 0.03 m (docs/m5_specs.md §4); speeds below it are zeroed.
WET_M = 0.03


# ---------------------------------------------------------------------------------------------
# 2. Read inputs
# ---------------------------------------------------------------------------------------------
def read_pol(path):
    """Delft3D-style .pol text: blocks of `name` / `n 2` / n lines of `x y`."""
    lines = [ln.strip() for ln in path.read_text().splitlines() if ln.strip()]
    blocks, i = {}, 0
    while i < len(lines):
        name, n = lines[i], int(lines[i + 1].split()[0])
        blocks[name] = [tuple(map(float, lines[i + 2 + k].split()[:2])) for k in range(n)]
        i += 2 + n
    return blocks


def read_grid_xyz(path):
    """Regular-grid `x y value` (cell centres) -> (xs, ys, grid[y, x])."""
    d = np.loadtxt(path)
    xs, ys = np.unique(d[:, 0]), np.unique(d[:, 1])
    grid = np.full((len(ys), len(xs)), np.nan)
    grid[np.searchsorted(ys, d[:, 1]), np.searchsorted(xs, d[:, 0])] = d[:, 2]
    assert not np.isnan(grid).any(), f"{path.name}: grid has holes (nodata)"
    return xs, ys, grid


blocks = read_pol(INPUTS / "domain.pol")
# SOURCED: domain.pol = exterior rings of M1 domain.gpkg. L002/L004/L006 are the three valley
# reaches. UNCLEAR: L001/L003/L005 are 5-13 vertex boxes (90-270 m) — likely M1 mask fragments;
# ignored here. Why M1's domain is disjoint at all is an open M1 question.
reach_polys = [Polygon(blocks[k]) for k in ("L002", "L004", "L006")]

bx, by = map(float, (INPUTS / "breach_location.xyz").read_text().split()[:2])  # SOURCED, UTM
breach_xy = (bx, by)  # site-config breach_location (placeholder, "UNVERIFIED guess")

dem_xs, dem_ys, dem_grid = read_grid_xyz(INPUTS / "dem_farfield.xyz")  # SOURCED, m, positive up
n_xs, n_ys, n_grid = read_grid_xyz(INPUTS / "roughness_farfield.xyz")  # SOURCED, Manning n s/m^(1/3)
assert np.array_equal(dem_xs, n_xs) and np.array_equal(dem_ys, n_ys), "DEM/roughness grids differ"
# CHOSEN IN PILOT: bilinear interpolation between cell centres (the .xyz points).
elev_at = RegularGridInterpolator((dem_ys, dem_xs), dem_grid, method="linear")
n_at = RegularGridInterpolator((dem_ys, dem_xs), n_grid, method="linear")

# SOURCED: hydrograph.tim = time [min since t0], Q [m^3/s] with base_flow (60 m^3/s, placeholder)
# ALREADY ADDED by make_export.py. Not added again here.
tim = np.loadtxt(INPUTS / "hydrograph.tim")
hydro_t_s = tim[:, 0] * 60.0  # min -> s (CLAUDE.md rule 5)
hydro_q = tim[:, 1]
BASE_FLOW = float(hydro_q[0])


# ---------------------------------------------------------------------------------------------
# 2b. Where the hydrograph enters: breach_location, or the spill point of the basin it drains into
# ---------------------------------------------------------------------------------------------
# CHOSEN IN PILOT (decided with user 2026-09-26): the placeholder breach_location sits ~1.5 km
# UPSLOPE of a closed 90 m-DEM basin (1.1 km^2, 13.2 Mm^3 — most likely the drained South Lhonak
# lake bed). Injected there, the base flow needs ~61 h just to fill that basin, and the basin
# would swallow a quarter of the 50 Mm^3 breach hydrograph. The hydrograph is the breach
# OUTFLOW, so it is applied at the basin's outlet instead:
#   1. walk steepest descent (8 neighbours) on the raw DEM from breach_location to a pit;
#   2. if that pit is inside a closed depression (priority-flood fill minus DEM > DEPRESSION_M),
#      find its spill cell = the lowest rim cell that has a lower neighbour outside the
#      depression, then keep walking steepest descent (outside the depression) until the point
#      is more than INLET_RADIUS_M + one cell from every depression cell — otherwise the inlet
#      circle straddles the rim and most of the inflow runs back into the basin (trial 2);
#   3. otherwise the inflow point is breach_location itself.
# UNCLEAR: breach_location must be corrected from post-event imagery (pilot yaml and
# sites/teesta.yaml); once it sits at the real outlet, rule 2 no longer fires.
DEPRESSION_M = 0.05  # CHOSEN IN PILOT: fill depths below 5 cm are flat-area noise
NB8 = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def priority_flood(z):
    """Depression-filled surface (Barnes et al. 2014 priority-flood, outflow at grid edges)."""
    ny, nx = z.shape
    filled = np.full_like(z, np.inf)
    heap = []
    for i in range(ny):
        for j in range(nx):
            if i in (0, ny - 1) or j in (0, nx - 1):
                filled[i, j] = z[i, j]
                heap.append((z[i, j], i, j))
    heapq.heapify(heap)
    while heap:
        level, i, j = heapq.heappop(heap)
        for di, dj in NB8:
            a, b = i + di, j + dj
            if 0 <= a < ny and 0 <= b < nx and filled[a, b] == np.inf:
                filled[a, b] = max(z[a, b], level)
                heapq.heappush(heap, (filled[a, b], a, b))
    return filled


def inflow_point(xy):
    ny, nx = dem_grid.shape
    i, j = int(np.abs(dem_ys - xy[1]).argmin()), int(np.abs(dem_xs - xy[0]).argmin())
    while True:  # 1. steepest descent to a pit
        nbrs = [(dem_grid[i + di, j + dj], i + di, j + dj) for di, dj in NB8
                if 0 <= i + di < ny and 0 <= j + dj < nx]
        z_low, a, b = min(nbrs)
        if z_low >= dem_grid[i, j]:
            break
        i, j = a, b
    depth = priority_flood(dem_grid) - dem_grid
    if depth[i, j] <= DEPRESSION_M:
        return xy, None  # 3. no closed basin below breach_location
    basin = np.zeros_like(depth, dtype=bool)  # 2. flood-select the depression containing the pit
    stack = [(i, j)]
    while stack:
        a, b = stack.pop()
        if 0 <= a < ny and 0 <= b < nx and not basin[a, b] and depth[a, b] > DEPRESSION_M:
            basin[a, b] = True
            stack.extend((a + di, b + dj) for di, dj in NB8)
    rim = []
    for a, b in zip(*np.where(basin)):
        for di, dj in NB8:
            r, c = a + di, b + dj
            if 0 <= r < ny and 0 <= c < nx and not basin[r, c]:
                has_lower_outside = any(
                    0 <= r + p < ny and 0 <= c + q < nx and not basin[r + p, c + q]
                    and dem_grid[r + p, c + q] < dem_grid[r, c] for p, q in NB8)
                if has_lower_outside:
                    rim.append((dem_grid[r, c], r, c))
    z_sp, r, c = min(rim)
    bi, bj = np.where(basin)
    clear_m = INLET_RADIUS_M + GRID_RES_M
    while np.hypot((bi - r) * GRID_RES_M, (bj - c) * GRID_RES_M).min() <= clear_m:
        nbrs = [(dem_grid[r + p, c + q], r + p, c + q) for p, q in NB8
                if 0 <= r + p < ny and 0 <= c + q < nx and not basin[r + p, c + q]]
        z_low, a, b = min(nbrs)
        assert z_low < dem_grid[r, c], "stuck on a flat/pit before clearing the basin"
        r, c = a, b
    info = {"basin_area_m2": float(basin.sum() * GRID_RES_M**2),
            "basin_volume_m3": float(depth[basin].sum() * GRID_RES_M**2),
            "basin_max_depth_m": float(depth[basin].max()),
            "spill_elevation_m": float(z_sp),
            "inflow_elevation_m": float(dem_grid[r, c])}
    return (float(dem_xs[c]), float(dem_ys[r])), info


inflow_xy, basin_info = inflow_point(breach_xy)

pois = []  # SOURCED: pois.xyz lines "x y * <poi_id> (<kind>)"
for ln in (INPUTS / "pois.xyz").read_text().splitlines():
    if ln.strip():
        x, y, _star, poi_id = ln.split()[:4]
        pois.append((poi_id, float(x), float(y)))


# ---------------------------------------------------------------------------------------------
# 3. Bounding polygon, refinement regions, boundary tags
# ---------------------------------------------------------------------------------------------
# CHOSEN IN PILOT: clip to the DEM cell-centre extent so no triangle needs extrapolated
# elevation (the Phase A spike's buffer reached 400 m past the DEM's south edge).
dem_extent = box(dem_xs[0], dem_ys[0], dem_xs[-1], dem_ys[-1])
merged = unary_union([p.buffer(DOMAIN_BUFFER_M) for p in reach_polys]
                     + [Point(breach_xy).buffer(DOMAIN_BUFFER_M),
                        Point(inflow_xy).buffer(DOMAIN_BUFFER_M)])
assert merged.geom_type == "Polygon", f"buffer did not join the reaches: {merged.geom_type}"
outline = merged.intersection(dem_extent).simplify(OUTLINE_SIMPLIFY_M, preserve_topology=True)
assert outline.geom_type == "Polygon"
outline = outline.buffer(0)  # canonical, valid ring
bounding_polygon = [tuple(c) for c in outline.exterior.coords[:-1]]
nseg = len(bounding_polygon)

# CHOSEN IN PILOT: corridor refinement regions = the reach polygons, clipped 5 m inside the
# outline so their edges never coincide with boundary segments (the mesher rejects overlaps).
inner = outline.buffer(-5.0)
interior_regions = []
for p in reach_polys:
    g = p.intersection(inner).simplify(REACH_SIMPLIFY_M, preserve_topology=True)
    for part in getattr(g, "geoms", [g]):
        if part.geom_type == "Polygon" and part.area > 10 * GRID_RES_M**2:
            interior_regions.append([[tuple(c) for c in part.exterior.coords[:-1]],
                                     K_CORRIDOR * GRID_RES_M**2])


def on_extent_edge(p, tol=1.0):
    x, y = p
    return (abs(x - dem_xs[0]) < tol or abs(x - dem_xs[-1]) < tol
            or abs(y - dem_ys[0]) < tol or abs(y - dem_ys[-1]) < tol)


# CHOSEN IN PILOT: boundary tags.
#   downstream = the contiguous run of outline segments lying on the DEM-extent clip line that
#                contains the lowest-elevation clip-line vertex (where the valley leaves the DEM);
#   wall       = every other segment.
seg_on_edge = [on_extent_edge(bounding_polygon[i]) and on_extent_edge(bounding_polygon[(i + 1) % nseg])
               for i in range(nseg)]
edge_vertices = [i for i in range(nseg) if on_extent_edge(bounding_polygon[i])]
assert edge_vertices, "outline never touches the DEM extent: no downstream boundary"
lowest = min(edge_vertices, key=lambda i: float(elev_at([bounding_polygon[i][::-1]])[0]))
downstream = set()
for step in (1, -1):  # walk both ways from the lowest vertex along on-edge segments
    i = lowest if step == 1 else (lowest - 1) % nseg
    while seg_on_edge[i] and i not in downstream:
        downstream.add(i)
        i = (i + step) % nseg
assert downstream, "no on-edge segment at the lowest clip-line vertex"
boundary_tags = {"downstream": sorted(downstream),
                 "wall": [i for i in range(nseg) if i not in downstream]}
outlet_xy = bounding_polygon[lowest]


# ---------------------------------------------------------------------------------------------
# 4. Mesh and domain
# ---------------------------------------------------------------------------------------------
domain = anuga.create_domain_from_regions(
    bounding_polygon,
    boundary_tags,
    maximum_triangle_area=K_OUTER * GRID_RES_M**2,
    interior_regions=interior_regions,
    minimum_triangle_angle=28.0,  # ANUGA DEFAULT
)
domain.set_name("teesta_pilot_s001__anuga")
domain.set_datadir(str(OUT))
# ANUGA DEFAULT: flow algorithm 'DE0' for domains from create_domain_from_regions (asserted, not set).
assert domain.get_flow_algorithm() == "DE0", domain.get_flow_algorithm()
# ANUGA DEFAULT: minimum_allowed_height, CFL, beta limiters — untouched.

xll = domain.geo_reference.get_xllcorner()
yll = domain.geo_reference.get_yllcorner()
cx_abs = domain.centroid_coordinates[:, 0] + xll  # centroids in absolute UTM
cy_abs = domain.centroid_coordinates[:, 1] + yll
ntri = domain.get_number_of_triangles()
tri_areas = domain.areas.copy()

# CHOSEN IN PILOT: elevation and friction set at triangle CENTROIDS by bilinear interpolation
# of the grids (DE algorithms work on centroid values). ANUGA's own default for point files is
# a least-squares fit to vertices; not used, to keep "what is the bed here" easy to audit.
# ANUGA set_quantity callbacks receive LOCAL coords (offset by geo_reference) — add xll/yll.
domain.set_quantity("elevation", lambda x, y: elev_at(np.column_stack([y + yll, x + xll])),
                    location="centroids")
domain.set_quantity("friction", lambda x, y: n_at(np.column_stack([y + yll, x + xll])),
                    location="centroids")
# CHOSEN IN PILOT: start dry (stage = bed); spin-up wets the channel.
domain.set_quantity("stage", lambda x, y: elev_at(np.column_stack([y + yll, x + xll])),
                    location="centroids")
elev_c = domain.quantities["elevation"].centroid_values.copy()
fric_c = domain.quantities["friction"].centroid_values.copy()
assert np.isfinite(elev_c).all() and np.isfinite(fric_c).all()

# CHOSEN (per brief): transmissive downstream boundary. CHOSEN IN PILOT: reflective walls
# (the spike's all-transmissive exterior could let inflow leak out beside the breach).
domain.set_boundary({"downstream": anuga.Transmissive_boundary(domain),
                     "wall": anuga.Reflective_boundary(domain)})


# ---------------------------------------------------------------------------------------------
# 5. Inflow at the breach
# ---------------------------------------------------------------------------------------------
def discharge(t):
    # CHOSEN IN PILOT: linear interpolation of hydrograph.tim. np.interp clamps outside the
    # record, so t < 0 (spin-up) gives Q(t0) = base flow and t > end gives the final base flow.
    return float(np.interp(t, hydro_t_s, hydro_q))


# Region/Inlet_operator take ABSOLUTE coordinates. Centre = inflow_xy (section 2b).
inlet_region = anuga.Region(domain, center=inflow_xy, radius=INLET_RADIUS_M)
inlet = anuga.Inlet_operator(domain, inlet_region, Q=discharge)
n_inlet = len(inlet_region.indices)
assert n_inlet > 0, "no triangle within INLET_RADIUS_M of the breach"

# ---------------------------------------------------------------------------------------------
# 6. Gauges (points of interest)
# ---------------------------------------------------------------------------------------------
# CHOSEN IN PILOT: a gauge reads the centroid values of the triangle containing the POI (no
# interpolation: on steep terrain, interpolated stage minus interpolated bed can go negative).
# POIs outside the mesh are reported as outside_domain, never given values.
gauges, outside = {}, []
for poi_id, x, y in pois:
    if outline.contains(Point(x, y)):
        # get_triangle_containing_point takes ABSOLUTE coordinates.
        gauges[poi_id] = {"tri": domain.get_triangle_containing_point([x, y]), "rows": []}
    else:
        outside.append(poi_id)

print(RUN_LABEL)
print(f"anuga {anuga.__version__}; mesh {ntri} triangles, area {tri_areas.sum()/1e6:.2f} km^2, "
      f"outline {nseg} vertices, {len(interior_regions)} corridor regions")
print(f"breach_location {breach_xy} -> inflow point {inflow_xy}; basin: {basin_info}")
print(f"downstream boundary: {len(downstream)} segments at outlet {outlet_xy}; inlet triangles {n_inlet}")
print(f"gauges: {list(gauges)}; outside_domain: {outside}")


def depth_c():
    return np.maximum(domain.quantities["stage"].centroid_values - elev_c, 0.0)


def speed_c(h):
    u = domain.quantities["xmomentum"].centroid_values
    v = domain.quantities["ymomentum"].centroid_values
    s = np.zeros_like(h)
    wet = h > WET_M
    s[wet] = np.hypot(u[wet], v[wet]) / h[wet]
    return s


# ---------------------------------------------------------------------------------------------
# 7. Spin-up (t = -T_SPINUP_S .. 0), nothing stored
# ---------------------------------------------------------------------------------------------
domain.set_starttime(-T_SPINUP_S)
domain.set_store(False)
print(f"spin-up: {T_SPINUP_S:.0f} s at Q = {BASE_FLOW:.1f} m^3/s")
spin_log = []
for t in domain.evolve(yieldstep=1800.0, finaltime=0.0):
    flows, _bin, _bout = domain.compute_boundary_flows()
    vol = domain.get_water_volume()
    spin_log.append((t, vol, -flows["downstream"]))
    print(f"  spin-up t={t:8.0f} s  volume={vol:12.0f} m^3  downstream outflow={-flows['downstream']:8.2f} m^3/s")
h0 = depth_c()
i_max = int(np.argmax(h0))
print(f"end of spin-up: max depth {h0[i_max]:.2f} m at ({cx_abs[i_max]:.0f}, {cy_abs[i_max]:.0f}), "
      f"wet triangles (> {WET_M} m): {(h0 > WET_M).sum()}")

# ---------------------------------------------------------------------------------------------
# 8. Breach run (t = 0 .. FINALTIME_S), stored
# ---------------------------------------------------------------------------------------------
domain.set_store(True)
domain.initialise_storage()  # create the sww writer now (it is only made automatically at t=start)
vol_t0 = domain.get_water_volume()
inflow_t0 = inlet.total_applied_volume
flux_t0 = domain.get_boundary_flux_integral()

# ANUGA DEFAULT operator: running max depth/speed at centroids every timestep (not just at
# yields). SOURCED velocity_zero_height = WET_M.
maxop = Collect_max_quantities_operator(domain, velocity_zero_height=WET_M)

arrival = np.full(ntri, np.nan)
arrival_lit = np.where(h0 > ARRIVAL_M, 0.0, np.nan)
for t in domain.evolve(yieldstep=YIELDSTEP_S, outputstep=SWW_OUTPUTSTEP_S, finaltime=FINALTIME_S):
    h = depth_c()
    arrival[np.isnan(arrival) & (h > h0 + ARRIVAL_M)] = t
    arrival_lit[np.isnan(arrival_lit) & (h > ARRIVAL_M)] = t
    s = speed_c(h)
    wse = domain.quantities["stage"].centroid_values
    for g in gauges.values():
        k = g["tri"]
        g["rows"].append((t, h[k], s[k], wse[k]))
    if int(t) % 1800 == 0:
        print(f"  t={t:8.0f} s  Q_in={discharge(t):8.1f}  wet={(h > WET_M).sum():6d}  "
              f"max depth={h.max():6.2f} m")

vol_end = domain.get_water_volume()
inflow = inlet.total_applied_volume - inflow_t0
flux = domain.get_boundary_flux_integral() - flux_t0  # net boundary inflow (outflow negative)
balance_err = (vol_end - vol_t0) - (inflow + flux)
print(f"volume balance t0..end: dV={vol_end - vol_t0:.4g} m^3, inlet={inflow:.4g}, "
      f"boundary={flux:.4g}, residual={balance_err:.4g} m^3 "
      f"({100 * balance_err / max(inflow, 1):.3f} % of inflow)")

# ---------------------------------------------------------------------------------------------
# 9. Write outputs
# ---------------------------------------------------------------------------------------------
import netCDF4  # noqa: E402

sww_path = OUT / "teesta_pilot_s001__anuga.sww"
with netCDF4.Dataset(sww_path, "a") as ds:
    ds.run_label = RUN_LABEL
    ds.has_placeholders = "true"
    ds.crs_epsg = UTM_EPSG
    ds.time_note = "seconds since t0 = time + starttime"

poi_summary = {}
for poi_id, g in gauges.items():
    rows = np.array(g["rows"])
    with open(OUT / "gauges" / f"{poi_id}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_s", "depth_m", "velocity_ms", "wse_m"])
        w.writerows([[f"{r[0]:.0f}", f"{r[1]:.4f}", f"{r[2]:.4f}", f"{r[3]:.4f}"] for r in rows])
    k = g["tri"]
    poi_summary[poi_id] = {
        "triangle": int(k),
        "depth_t0_m": round(float(h0[k]), 4),
        "max_depth_m": round(float(maxop.max_depth[k]), 4),
        "max_velocity_ms": round(float(maxop.max_speed[k]), 4),
        "arrival_s": None if np.isnan(arrival[k]) else float(arrival[k]),
        "arrival_literal_s": None if np.isnan(arrival_lit[k]) else float(arrival_lit[k]),
    }
for poi_id in outside:
    poi_summary[poi_id] = {"status": "outside_domain"}

with open(OUT / "max_centroids.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["x", "y", "area_m2", "elevation_m", "manning_n", "depth_t0_m",
                "max_depth_m", "max_velocity_ms", "arrival_s", "arrival_literal_s"])
    for k in range(ntri):
        w.writerow([f"{cx_abs[k]:.3f}", f"{cy_abs[k]:.3f}", f"{tri_areas[k]:.2f}",
                    f"{elev_c[k]:.4f}", f"{fric_c[k]:.5f}", f"{h0[k]:.4f}",
                    f"{maxop.max_depth[k]:.4f}", f"{maxop.max_speed[k]:.4f}",
                    "" if np.isnan(arrival[k]) else f"{arrival[k]:.0f}",
                    "" if np.isnan(arrival_lit[k]) else f"{arrival_lit[k]:.0f}"])

mesh_summary = {
    "n_triangles": int(ntri),
    "total_area_m2": float(tri_areas.sum()),
    "bounding_polygon": [list(p) for p in bounding_polygon],
    "boundary_tags": boundary_tags,
    "outlet_xy": list(outlet_xy),
    "interior_regions": [{"n_vertices": len(r[0]), "max_triangle_area_m2": r[1]}
                         for r in interior_regions],
    "outer_max_triangle_area_m2": K_OUTER * GRID_RES_M**2,
    "inlet_triangles": int(n_inlet),
    "breach_location_xy": list(breach_xy),
    "inflow_xy": list(inflow_xy),
    "inflow_basin": basin_info,
}
(OUT / "mesh_summary.json").write_text(json.dumps(mesh_summary, indent=1))

wall = time.time() - WALL_START
peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # Linux: kB -> MB
run_meta = {
    "run_label": RUN_LABEL,
    "scenario_id": "teesta_pilot_s001",
    "model": "anuga",
    "solver_version": f"anuga {anuga.__version__}",
    "has_placeholders": True,
    "crs_epsg": UTM_EPSG,
    "resolution_m": GRID_RES_M,
    "t_spinup_s": T_SPINUP_S,
    "sim_duration_s": FINALTIME_S,
    "yieldstep_s": YIELDSTEP_S,
    "sww_outputstep_s": SWW_OUTPUTSTEP_S,
    "base_flow_m3s": BASE_FLOW,
    "thresholds": {"arrival_m": ARRIVAL_M, "wet_m": WET_M,
                   "arrival_rule": "first t>=0 with depth > depth_t0 + arrival_m (UNCLEAR, proposed)"},
    "volume_balance": {"dV_m3": vol_end - vol_t0, "inlet_m3": inflow, "boundary_m3": flux,
                       "residual_m3": balance_err},
    "spinup_log": [{"t_s": t, "volume_m3": v, "downstream_outflow_m3s": q} for t, v, q in spin_log],
    "pois": poi_summary,
    "n_triangles": int(ntri),
    "wall_time_s": round(wall, 1),
    "peak_rss_mb": round(peak_mb, 1),
    "inflow_xy": list(inflow_xy),
    "inflow_basin": basin_info,
    "caveats": ["clear_water", "all_inputs_placeholder", "domain_outline_stitched_by_buffer"]
               + (["inflow_moved_to_basin_spill_point"] if basin_info else []),
}
(OUT / "run_meta_pilot.json").write_text(json.dumps(run_meta, indent=1))

print("\n=== POI summary ===")
for poi_id, sm in poi_summary.items():
    print(poi_id, sm)
print(f"WALLCLOCK_SECONDS={wall:.1f}  PEAK_RSS_MB={peak_mb:.1f}")
