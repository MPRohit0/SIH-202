"""M4: DualSPHysics near-field case generation (`docs/handoff_contract.md` §4.4).

`pilot_case_spec()` reproduces `m4_pilot`'s calibration run (the stock DualSPHysics 5.4.3 example
`examples/main/01_DamBreak/CaseDambreakVal2D_Def.xml`) as a `case_xml.CaseSpec`, to check the
writer against a real, GenCase-validated file (`tests/m4_sph/test_pilot_regen.py`) before it is
used to build real near-field cases.
"""

from __future__ import annotations

import json
import math
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pyproj
import rasterio

from backend.m2_breach.hydrograph import hydrograph as m2_hydrograph
from backend.m4_pilot import vram_estimator
from backend.shared.grid import FLOAT_NODATA, CanonicalGrid, lonlat_to_rowcol
from backend.shared.probes import Probe, load_probes
from backend.shared.site_config import SiteConfig, load_site_config

from .case_xml import CaseSpec, E, InOutZone, SwlGauge, TimeValue, VelocityGauge, write_case_xml
from .settings import SphSettings, load_sph_settings

CONTRACT_VERSION = "0.2.0"
DATA_DIR = Path(__file__).resolve().parents[2] / "data"


class InflowUnavailable(Exception):
    """Raised when a scenario's near-field inflow can't be evaluated yet (e.g. `inflow.from:
    far_field` needs a far-field discharge series that only M3 can produce)."""


class OverVramBudget(Exception):
    """Raised when a case's predicted particle count would exceed the configured VRAM budget."""


def hydrograph_to_velocity(
    t_s: np.ndarray, q_m3s: np.ndarray, area_m2: float, t_start_s: float, t_end_s: float | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Convert a discharge hydrograph `Q(t)` (contract §4.2, seconds since t0) to a uniform inlet
    velocity `v(tau) = Q(t_start_s + tau) / area_m2` over a fixed inlet cross-section (m/s), for
    DualSPHysics `imposevelocity mode="1"` (`velocitytimes`, `time`-tagged in solver time `tau`,
    which starts at 0 at `t_start_s`).

    `t_s` must be sorted and span `[t_start_s, t_end_s]` (or the hydrograph's own end, if
    `t_end_s` is None); the window is clipped with linear interpolation at both ends.
    """
    if area_m2 <= 0:
        raise ValueError(f"area_m2 must be positive, got {area_m2}")
    t_s = np.asarray(t_s, dtype=float)
    q_m3s = np.asarray(q_m3s, dtype=float)
    if t_s.ndim != 1 or t_s.shape != q_m3s.shape or len(t_s) < 2:
        raise ValueError("t_s and q_m3s must be 1-D, equal-length, and have at least 2 samples")
    if np.any(np.diff(t_s) <= 0):
        raise ValueError("t_s must be strictly increasing")

    end = t_end_s if t_end_s is not None else float(t_s[-1])
    if end <= t_start_s:
        raise ValueError(f"t_end_s ({end}) must be greater than t_start_s ({t_start_s})")
    if t_start_s < t_s[0] or end > t_s[-1]:
        raise ValueError(
            f"window [{t_start_s}, {end}] s falls outside the hydrograph's range [{t_s[0]}, {t_s[-1]}] s"
        )

    mask = (t_s > t_start_s) & (t_s < end)
    window_t = np.concatenate(([t_start_s], t_s[mask], [end]))
    window_q = np.interp(window_t, t_s, q_m3s)

    tau_s = window_t - t_start_s
    v_ms = window_q / area_m2
    return tau_s, v_ms


@dataclass(frozen=True)
class InletGeometry:
    """A vertical rectangular inlet, `width_m` x `height_m`, centred on the inflow point (SPH
    frame, §1.3), bottom at bed elevation. `direction_xyz`/`rotate_deg` orient it perpendicular
    to the local channel tangent (unverified against a real GenCase run -- check `rotateaxis`'s
    sign convention with the `DSPH_BIN_DIR` smoke test before trusting the flow direction)."""

    x_utm_m: float
    y_utm_m: float
    point_xyz: tuple[float, float, float]
    size_xyz: tuple[float, float, float]
    direction_xyz: tuple[float, float, float]
    rotate_deg: float
    area_m2: float
    bed_z_m: float
    zsurf_m: float


def _tangent_at_point(centreline, x_m: float, y_m: float, ds: float = 1.0) -> tuple[float, float]:
    """Unit downstream tangent `(dx, dy)` of a shapely `LineString` (site UTM) nearest `(x_m, y_m)`."""
    from shapely.geometry import Point

    s = centreline.project(Point(x_m, y_m))
    s0, s1 = max(0.0, s - ds), min(centreline.length, s + ds)
    if s1 <= s0:
        raise ValueError("centreline is too short to estimate a tangent near this point")
    p0, p1 = centreline.interpolate(s0), centreline.interpolate(s1)
    dx, dy = p1.x - p0.x, p1.y - p0.y
    norm = math.hypot(dx, dy)
    if norm == 0:
        raise ValueError("degenerate centreline tangent (coincident points)")
    return dx / norm, dy / norm


def inlet_geometry(
    inflow_lon_lat: tuple[float, float],
    grid_near: CanonicalGrid,
    dem_near: np.ndarray,
    frame: dict,
    centreline,
    width_m: float,
    height_m: float,
) -> InletGeometry:
    """Place the inlet at `inflow_lon_lat` (site config `domains.near_field.inflow.location`)."""
    lon, lat = inflow_lon_lat
    x_utm, y_utm = pyproj.Transformer.from_crs(4326, grid_near.crs_epsg, always_xy=True).transform(lon, lat)

    row, col = lonlat_to_rowcol(grid_near, lon, lat)
    bed_z = float(dem_near[row, col])
    if bed_z == FLOAT_NODATA:
        raise ValueError(f"inflow location ({lon}, {lat}) is nodata in dem_nearfield.tif")

    tx, ty = _tangent_at_point(centreline, x_utm, y_utm)
    # Unrotated zone flow direction is (0,-1,0) (case_xml.InOutZone); rotating by theta about z maps
    # it to (sin theta, -cos theta) -- solve for theta so that maps onto the channel tangent (tx, ty).
    rotate_deg = math.degrees(math.atan2(tx, -ty))

    x_local = x_utm - frame["origin_x"]
    y_local = y_utm - frame["origin_y"]
    area_m2 = width_m * height_m
    return InletGeometry(
        x_utm_m=x_utm, y_utm_m=y_utm,
        point_xyz=(x_local - width_m / 2, y_local, bed_z),
        size_xyz=(width_m, 0.0, height_m),
        direction_xyz=(0.0, -1.0, 0.0),
        rotate_deg=rotate_deg,
        area_m2=area_m2,
        bed_z_m=bed_z,
        zsurf_m=bed_z + height_m,
    )


@dataclass(frozen=True)
class NearfieldProbe:
    probe: Probe
    x_m: float  # SPH frame
    y_m: float
    z_bed_m: float


def probes_in_nearfield(
    probes: list[Probe], frame: dict, grid_near: CanonicalGrid, dem_near: np.ndarray,
) -> tuple[list[NearfieldProbe], list[str]]:
    """Split `probes` (site-wide, from `pois.gpkg`) into the ones that fall inside the near-field
    grid (kept, with SPH-frame coordinates and bed elevation) and the `poi_id`s of the rest."""
    kept: list[NearfieldProbe] = []
    skipped: list[str] = []
    left, bottom, right, top = grid_near.bounds
    for p in probes:
        if not (left <= p.x_m <= right and bottom <= p.y_m <= top):
            skipped.append(p.poi_id)
            continue
        # p.x_m/p.y_m are already UTM; convert to near-field row/col directly (`lonlat_to_rowcol`
        # takes lon/lat, not UTM metres).
        col_i = int((p.x_m - grid_near.origin_x) / grid_near.cell_size_m)
        row_i = int((grid_near.origin_y - p.y_m) / grid_near.cell_size_m)
        row_i = min(max(row_i, 0), grid_near.height - 1)
        col_i = min(max(col_i, 0), grid_near.width - 1)
        z_bed = float(dem_near[row_i, col_i])
        if z_bed == FLOAT_NODATA:
            skipped.append(p.poi_id)
            continue
        kept.append(NearfieldProbe(
            probe=p, x_m=p.x_m - frame["origin_x"], y_m=p.y_m - frame["origin_y"], z_bed_m=z_bed,
        ))
    return kept, skipped


def check_vram(
    dp_m: float, domain_x_m: float, domain_y_m: float, fluid_depth_m: float,
    settings: SphSettings, *, allow_over_budget: bool = False,
) -> dict:
    """Estimate the particle count/VRAM for a case at `dp_m` (`backend/m4_pilot/vram_estimator.py`,
    calibrated from the pilot run) and raise `OverVramBudget` unless it fits `settings`'s budget."""
    cal = vram_estimator.calibrate()
    counts = vram_estimator.estimate_particle_count(
        domain_x_m, domain_y_m, fluid_depth_m, dp_m, boundary_layers=settings.boundary_layers,
    )
    vram_mib = vram_estimator.estimate_vram_mib(counts["total_particles"], cal)
    usable_mib = settings.vram_budget_mib * (1 - settings.vram_margin)
    result = {**counts, "vram_mib": vram_mib, "budget_mib": usable_mib, "dp_m": dp_m}
    if vram_mib > usable_mib and not allow_over_budget:
        raise OverVramBudget(
            f"dp={dp_m} m -> {counts['total_particles']:,.0f} particles, {vram_mib:,.0f} MiB "
            f"predicted, exceeds the {usable_mib:,.0f} MiB budget "
            f"({settings.vram_budget_mib} MiB * (1 - {settings.vram_margin}))"
        )
    return result


def build_nearfield_case(
    site_id: str, scenario_id: str, params: dict, settings: SphSettings | None = None,
    data_dir: str | Path | None = None, sites_dir: str | Path | None = None,
) -> tuple[CaseSpec, dict]:
    """Build the near-field GenCase spec for `scenario_id` on `site_id`, from M1 terrain
    (`data/<site_id>/terrain/`) and an M2 hydrograph for `params`. Returns `(spec, case_meta)`.

    `params` is a scenario's breach parameters (contract §4.3): `water_volume_m3`,
    `breach_width_m`, `failure_time_s`, plus whatever `hydrograph()` needs for the triggering dam.
    `sites_dir` overrides where `<site_id>.yaml` is loaded from (default `sites/`), for tests.
    """
    settings = settings or load_sph_settings()
    data_dir = Path(data_dir) if data_dir is not None else DATA_DIR
    cfg = load_site_config(site_id, sites_dir=sites_dir)
    terrain_dir = data_dir / site_id / "terrain"

    grid_near = CanonicalGrid.from_json(terrain_dir / "grid_nearfield.json")
    frame = json.loads((terrain_dir / "nearfield_frame.json").read_text(encoding="utf-8"))
    with rasterio.open(terrain_dir / "dem_nearfield.tif") as ds:
        dem_near = ds.read(1)
    centreline = gpd.read_file(terrain_dir / "centreline.gpkg").geometry.iloc[0]

    nf = cfg.domains.near_field
    dam_id = nf.inflow.from_
    if dam_id == "far_field":
        raise InflowUnavailable(
            f"{site_id}: near_field.inflow.from is 'far_field' -- the SPH inlet needs a routed "
            f"far-field discharge series, which only M3 (Delft3D) can produce; not available yet."
        )

    hydro = m2_hydrograph(site_id, dam_id, params, sites_dir=sites_dir)
    t_start_s = settings.t_start_s
    t_end_s = settings.t_end_s if settings.t_end_s is not None else float(hydro.t_s[-1])

    inflow_location = nf.inflow.location.value
    inlet = inlet_geometry(
        tuple(inflow_location), grid_near, dem_near, frame, centreline,
        settings.inlet_width_m, settings.inlet_height_m,
    )

    tau_s, v_ms = hydrograph_to_velocity(hydro.t_s, hydro.q_m3s, inlet.area_m2, t_start_s, t_end_s)
    velocity_times = [TimeValue(float(t), float(v)) for t, v in zip(tau_s, v_ms)]
    inout_zone = InOutZone(
        point_xyz=inlet.point_xyz, size_xyz=inlet.size_xyz, direction_xyz=inlet.direction_xyz,
        velocity_times=velocity_times, zsurf_m=inlet.zsurf_m, layers=settings.inlet_layers,
        rotate_deg=inlet.rotate_deg,
        rotate_center_xy=(inlet.point_xyz[0] + inlet.size_xyz[0] / 2, inlet.point_xyz[1]),
    )

    probes = load_probes(terrain_dir)
    kept_probes, skipped_probes = probes_in_nearfield(probes, frame, grid_near, dem_near)

    dp_setting = settings.dp_m
    left, bottom, right, top = grid_near.bounds
    domain_x_m, domain_y_m = right - left, top - bottom
    fluid_depth_m = settings.inlet_height_m
    if dp_setting == "auto":
        auto = vram_estimator.smallest_dp_within_budget(
            domain_x_m, domain_y_m, fluid_depth_m,
            vram_estimator.calibrate(), vram_budget_mib=settings.vram_budget_mib,
            margin=settings.vram_margin, boundary_layers=settings.boundary_layers,
        )
        if not auto["feasible"]:
            raise OverVramBudget(f"{site_id}/{scenario_id}: {auto.get('reason', 'no feasible dp found')}")
        dp_m = auto["dp_m"]
        vram_info = {"dp_m": dp_m, "total_particles": auto["total_particles"], "vram_mib": auto["predicted_vram_mib"], "budget_mib": auto["budget_mib"]}
    else:
        dp_m = float(dp_setting)
        vram_info = check_vram(dp_m, domain_x_m, domain_y_m, fluid_depth_m, settings)

    dem_valid = dem_near[dem_near != FLOAT_NODATA]
    z_min = float(dem_valid.min()) if dem_valid.size else 0.0
    z_max = max(float(dem_valid.max()) if dem_valid.size else 0.0, inlet.zsurf_m)

    draw_commands = [
        E("setmkfluid", {"mk": 0}),
        E("setmkbound", {"mk": 10}),
    ]
    for layer in range(settings.boundary_layers):
        draw_commands.append(E("drawfilestl", {"file": "nearfield.stl"}, children=[
            E("drawmove", {"x": 0, "y": 0, "z": -layer * dp_m}),
        ]))

    vel_gauges = [
        VelocityGauge(f"vel_{p.probe.poi_id}", (p.x_m, p.y_m, p.z_bed_m + settings.probe_velocity_height_m))
        for p in kept_probes
    ]
    swl_gauges = [
        SwlGauge(
            f"swl_{p.probe.poi_id}",
            point0_xyz=(p.x_m, p.y_m, p.z_bed_m - dp_m),
            point2_xyz=(p.x_m, p.y_m, p.z_bed_m + settings.inlet_height_m),
        )
        for p in kept_probes
    ]

    spec = CaseSpec(
        dp_m=dp_m,
        pointref_xyz=(0.0, 0.0, 0.0),
        pointmin_xyz=(0.0, 0.0, z_min - settings.inlet_height_m),
        pointmax_xyz=(grid_near.width * grid_near.cell_size_m, grid_near.height * grid_near.cell_size_m, z_max),
        constants=[
            ("gravity", {"x": 0, "y": 0, "z": -9.81, "comment": "Gravitational acceleration", "units_comment": "m/s^2"}),
            ("rhop0", {"value": 1000, "comment": "Reference density of the fluid (clear water -- caveat clear_water)", "units_comment": "kg/m^3"}),
            ("gamma", {"value": 7, "comment": "Polytropic constant for water used in the state equation"}),
            ("coefh", {"value": 1.0, "comment": "Coefficient to calculate the smoothing length"}),
            ("cflnumber", {"value": 0.2, "comment": "Coefficient to multiply dt"}),
        ],
        mk_boundcount=1,
        mk_fluidcount=1,
        draw_commands=draw_commands,
        parameters=[
            ("StepAlgorithm", 1, "Step Algorithm 1:Verlet, 2:Symplectic (default=1) -- DualSPHysics 01_DamBreak default"),
            ("VerletSteps", 40, "Verlet only: Number of steps to apply Euler timestepping -- DualSPHysics 01_DamBreak default"),
            ("Kernel", 2, "Interaction Kernel 1:Cubic Spline, 2:Wendland -- DualSPHysics 01_DamBreak default"),
            ("ViscoTreatment", 1, "Viscosity formulation 1:Artificial, 2:Laminar+SPS, 3:Laminar -- DualSPHysics 01_DamBreak default"),
            ("Visco", 0.02, "Viscosity value -- DualSPHysics 01_DamBreak default"),
            ("DensityDT", 2, "Density Diffusion Term 0:None, 1:Molteni, 2:Fourtakas, 3:Fourtakas(full) -- DualSPHysics 01_DamBreak default"),
            ("DensityDTvalue", 0.1, "DDT value -- DualSPHysics 01_DamBreak default"),
            ("RigidAlgorithm", 1, "Rigid Algorithm 0:collision-free, 1:SPH, 2:DEM, 3:Chrono -- DualSPHysics 01_DamBreak default"),
            ("TimeMax", tau_s[-1], "Time of simulation"),
            ("TimeOut", settings.time_out_s, "Time out data"),
            ("RhopOutMin", 700, "Minimum rhop valid -- DualSPHysics 01_DamBreak default"),
            ("RhopOutMax", 1300, "Maximum rhop valid -- DualSPHysics 01_DamBreak default"),
        ],
        inout_zones=[inout_zone],
        swl_gauges=swl_gauges,
        vel_gauges=vel_gauges,
    )

    caveats = ["clear_water", "fixed_area_inlet"]
    case_meta = {
        "contract_version": CONTRACT_VERSION,
        "site_id": site_id, "scenario_id": scenario_id, "model": "sph",
        "t_start_s": t_start_s, "t_end_s": t_end_s,
        "dp_m": dp_m, **{f"vram_{k}": v for k, v in vram_info.items() if k != "dp_m"},
        "inlet": {
            "x_utm_m": inlet.x_utm_m, "y_utm_m": inlet.y_utm_m,
            "area_m2": inlet.area_m2, "bed_z_m": inlet.bed_z_m, "zsurf_m": inlet.zsurf_m,
            "rotate_deg": inlet.rotate_deg,
        },
        "probes_used": [p.probe.poi_id for p in kept_probes],
        "probes_skipped": skipped_probes,
        "has_placeholders": cfg.has_placeholders,
        "placeholder_fields": cfg.placeholder_fields,
        "caveats": caveats,
        "provenance": {"method": "m4_sph.generator.build_nearfield_case", "hydrograph_method": hydro.method},
    }
    return spec, case_meta


def write_case(spec: CaseSpec, case_meta: dict, run_dir: str | Path, terrain_dir: str | Path) -> Path:
    """Write `runs/<scenario_id>__sph/case/` (contract §4.4): the GenCase `_Def.xml`, a copy of
    `nearfield.stl`, `probes.csv` and `case_meta.json`. Never launches GenCase or the solver."""
    case_dir = Path(run_dir) / "case"
    case_dir.mkdir(parents=True, exist_ok=True)
    name = f"{case_meta['scenario_id']}__sph"
    write_case_xml(spec, case_dir / f"{name}_Def.xml")
    shutil.copyfile(Path(terrain_dir) / "nearfield.stl", case_dir / "nearfield.stl")
    (case_dir / "case_meta.json").write_text(json.dumps(case_meta, indent=2) + "\n", encoding="utf-8")
    return case_dir


def pilot_case_spec() -> CaseSpec:
    """`CaseDambreakVal2D` (Koshizuka & Oka 1996 dam-break validation), as shipped with
    DualSPHysics 5.4.3. 2D (`y` fixed at 0), no boundary STL, no inlet — used only to validate
    `case_xml`'s writer against a real GenCase file."""
    constants = [
        ("gravity", {"x": 0, "y": 0, "z": -9.81, "comment": "Gravitational acceleration", "units_comment": "m/s^2"}),
        ("rhop0", {"value": 1000, "comment": "Reference density of the fluid", "units_comment": "kg/m^3"}),
        ("rhopgradient", {"value": 2, "comment": "Initial density gradient 1:Rhop0, 2:Water column, 3:Max. water height (default=2)"}),
        ("hswl", {"value": 0, "auto": True, "comment": "Maximum still water level to calculate speedofsound using coefsound", "units_comment": "metres (m)"}),
        ("gamma", {"value": 7, "comment": "Polytropic constant for water used in the state equation"}),
        ("speedsystem", {"value": 0, "auto": True, "comment": "Maximum system speed (by default the dam-break propagation is used)"}),
        ("coefsound", {"value": 20, "comment": "Coefficient to multiply speedsystem"}),
        ("speedsound", {"value": 0, "auto": True, "comment": "Speed of sound to use in the simulation (by default speedofsound=coefsound*speedsystem)"}),
        ("coefh", {"value": 1.0, "comment": "Coefficient to calculate the smoothing length (h=coefh*sqrt(3*dp^2) in 3D)"}),
        ("_hdp", {"value": 2, "comment": "Alternative option to calculate the smoothing length (h=hdp*dp)"}),
        ("cflnumber", {"value": 0.2, "comment": "Coefficient to multiply dt"}),
    ]

    draw_commands = [
        E("setdrawmode", {"mode": "full"}),
        E("setmkfluid", {"mk": 0}),
        E("drawbox", children=[
            _text_el("boxfill", "solid"),
            E("point", {"x": 0, "y": -1, "z": 0}),
            E("size", {"x": 1, "y": 2, "z": 2}),
        ]),
        E("setmkbound", {"mk": 0}),
        E("drawbox", children=[
            _text_el("boxfill", "bottom | left | right | front | back"),
            E("point", {"x": 0, "y": -1, "z": 0}),
            E("size", {"x": 4, "y": 2, "z": 3}),
        ]),
    ]

    gauges_default = E("default", children=[
        E("savevtkpart", {"value": True, "comment": "Creates VTK files for each PART (default=false)"}),
        E("_computedt", {"value": 0.001, "comment": "Time between measurements. 0:all steps (default=TimeOut)", "units_comment": "s"}),
        E("_computetime", {"start": 0.1, "end": 0.2, "comment": "Start and end of measures. (default=simulation time)", "units_comment": "s"}),
        E("output", {"value": True, "comment": "Creates CSV files of measurements (default=false)"}),
        E("_outputdt", {"value": 0, "comment": "Time between output measurements. 0:all steps (default=TimeOut)", "units_comment": "s"}),
        E("_outputtime", {"start": 0, "end": 10, "comment": "Start and end of output measures. (default=simulation time)", "units_comment": "s"}),
    ])

    swl_gauge_1 = SwlGauge("Swl_x02", point0_xyz=(0.2, 0, -0.05), point2_xyz=(0.2, 0, 2.1))
    swl_gauge_2 = SwlGauge(
        "Swl_z003", point0_xyz=(-0.05, 0, 0.03), point2_xyz=(4.05, 0, 0.03),
        compute_dt_s=0.005, output_dt_s=0.005,
    )

    parameters = [
        ("SavePosDouble", 0, "Saves particle position using double precision (default=0)"),
        ("StepAlgorithm", 1, "Step Algorithm 1:Verlet, 2:Symplectic (default=1)"),
        ("VerletSteps", 40, "Verlet only: Number of steps to apply Euler timestepping (default=40)"),
        ("Kernel", 2, "Interaction Kernel 1:Cubic Spline, 2:Wendland (default=2)"),
        ("ViscoTreatment", 1, "Viscosity formulation 1:Artificial, 2:Laminar+SPS, 3:Laminar (default=1)"),
        ("Visco", 0.02, "Viscosity value. Typically 0.01 for Artificial and 1e-6 m^2/s (water kinematic viscosity) for Laminar"),
        ("ViscoBoundFactor", 1, "Multiply viscosity value with boundary (default=1)"),
        ("DensityDT", 2, "Density Diffusion Term 0:None, 1:Molteni, 2:Fourtakas, 3:Fourtakas(full) (default=0)"),
        ("DensityDTvalue", 0.1, "DDT value (default=0.1)"),
        ("Shifting", 0, "Shifting mode 0:None, 1:Ignore bound, 2:Ignore fixed, 3:Full (default=0)"),
        ("ShiftCoef", -2, "Coefficient for shifting computation (default=-2)"),
        ("ShiftTFS", 0, "Threshold to detect free surface. Typically 1.5 for 2D and 2.75 for 3D (default=0)"),
        ("RigidAlgorithm", 1, "Rigid Algorithm 0:collision-free, 1:SPH, 2:DEM, 3:Chrono (default=1)"),
        ("FtPause", 0.0, "Time to freeze the floatings at simulation start (warmup) (default=0)"),
        ("CoefDtMin", 0.05, "Coefficient to calculate minimum time step dtmin=coefdtmin*h/speedsound (default=0.05)"),
        ("DtIni", 0, "Initial time step. Use 0 to default use (default=h/speedsound)"),
        ("DtMin", 0, "Minimum time step. Use 0 to default use (default=coefdtmin*h/speedsound)"),
        ("DtFixed", 0, "Fixed Dt value. Use 0 to disable (default=disabled)"),
        ("DtFixedFile", "NONE", "Dt values are loaded from file. Use NONE to disable (default=disabled)"),
        ("DtAllParticles", 0, "Velocity of particles used to calculate DT. 1:All, 0:Only fluid/floating (default=0)"),
        ("TimeMax", 2.0, "Time of simulation"),
        ("TimeOut", 0.01, "Time out data"),
        ("PartsOutMax", 1, "%/100 of fluid particles allowed to be excluded from domain (default=1)"),
        ("RhopOutMin", 700, "Minimum rhop valid (default=700)"),
        ("RhopOutMax", 1300, "Maximum rhop valid (default=1300)"),
    ]

    return CaseSpec(
        dp_m=0.01,
        pointref_xyz=(0, 0, 0),
        pointmin_xyz=(-1, 0, -1),
        pointmax_xyz=(4.5, 0, 3.5),
        constants=constants,
        mk_boundcount=240,
        mk_fluidcount=9,
        draw_commands=draw_commands,
        parameters=parameters,
        gauges_default=gauges_default,
        swl_gauges=[swl_gauge_1, swl_gauge_2],
        simdomain_posmax=("default", "default", "default + 50%"),
    )


def _text_el(tag: str, text: str) -> ET.Element:
    el = ET.Element(tag)
    el.text = text
    return el


def main(argv: list[str] | None = None) -> None:
    """Write a near-field case's GenCase input files. Never launches GenCase or the solver
    (docs/decisions.md rule 14 -- long solver runs are the job system's job, not this CLI's)."""
    import argparse

    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("--site", required=True)
    parser.add_argument("--scenario-id", required=True)
    parser.add_argument("--params-json", required=True, help="JSON object: breach_width_m, failure_time_s, water_volume_m3, ...")
    parser.add_argument("--dp-m", type=float, default=None, help="override settings.dp_m (skips the VRAM search)")
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--run-dir", default=None, help="default: <data-dir>/<site>/runs/<scenario-id>__sph")
    args = parser.parse_args(argv)

    params = json.loads(args.params_json)
    overrides = {"dp_m": args.dp_m} if args.dp_m is not None else {}
    settings = load_sph_settings(**overrides)
    data_dir = Path(args.data_dir) if args.data_dir else DATA_DIR

    spec, case_meta = build_nearfield_case(args.site, args.scenario_id, params, settings, data_dir)
    run_dir = Path(args.run_dir) if args.run_dir else data_dir / args.site / "runs" / f"{args.scenario_id}__sph"
    terrain_dir = data_dir / args.site / "terrain"
    case_dir = write_case(spec, case_meta, run_dir, terrain_dir)
    print(f"wrote {case_dir}")


if __name__ == "__main__":
    main()
