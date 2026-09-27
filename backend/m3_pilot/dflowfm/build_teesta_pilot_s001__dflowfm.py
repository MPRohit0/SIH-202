"""Build and run the hand-reviewed Teesta D-Flow FM pilot.

Run from the repository root with ``.venv/bin/python backend/m3_pilot/dflowfm/build_teesta_pilot_s001__dflowfm.py``.
Every modelling choice is tagged SOURCED, FM DEFAULT, CHOSEN IN PILOT, or UNCLEAR.
"""
from __future__ import annotations

import json
import os
import re
import sys
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from backend.m3_common.loaders import (
    interpolate_xy,
    load_pilot_inputs,
    pilot_mesh_geometry,
    summarize_dflowfm_pilot,
)
from hydrolib.core.base.models import DiskOnlyFileModel
from hydrolib.core.dflowfm import ExtModel, FMModel, NetworkModel, XYNModel
from hydrolib.core.dflowfm.bc.models import ForcingModel, QuantityUnitPair, TimeSeries
from hydrolib.core.dflowfm.ext.models import Boundary, SourceSink
from hydrolib.core.dflowfm.inifield.models import IniFieldModel, InitialField, ParameterField
from hydrolib.core.dflowfm.mdu.models import ExternalForcing, General, Geometry, Numerics, Output, Physics, Time
from hydrolib.core.dflowfm.net.models import Network
from hydrolib.core.dflowfm.xyn.models import XYNPoint


INPUTS = ROOT / "backend" / "m3_pilot" / "inputs" / "export"
PILOT = ROOT / "backend" / "m3_pilot" / "dflowfm"
CASE = PILOT / "case"
CASE_INPUTS = CASE / "inputs"
OUTPUT = CASE / "output"
RUN_ID = "teesta_pilot_s001__dflowfm"
LABEL = "PLACEHOLDER — teesta_pilot_s001, all inputs placeholder"
REFDATE = "20010101"


def main() -> None:
    # SOURCED: all case inputs are the frozen M1/M2 exports from backend/m3_pilot/inputs/export;
    # their pilot-only site config marks every site fact as placeholder.
    CASE_INPUTS.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    inputs = load_pilot_inputs(INPUTS)
    geometry, inflow_edge, outlet_edge, domain_area_m2 = pilot_mesh_geometry(inputs)

    # CHOSEN IN PILOT: meshkernel constrained triangulation uses the 90 m rasterized polygon
    # edges as its scale cue. The 400 m union buffer connects the disjoint M1 reach polygons;
    # the 90 m breach corridor follows the breach-to-domain nearest-point segment. Resolution is therefore
    # consistent with, but not asserted to be exactly equal to, the 90 m source grid. The
    # 30 m polygon simplification removes sub-grid boundary slivers before mesh generation.
    model = NetworkModel()
    model.network.mesh2d_create_triangular_within_polygon(geometry)
    # CHOSEN IN PILOT: remove sub-0.1 m circumcenter flow links and their degenerate faces in
    # meshkernel before writing. The uncleaned net forced D-Flow FM to sub-0.1 s timesteps.
    model.network.meshkernel.mesh2d_delete_small_flow_edges_and_small_triangles(0.1, 0.0)
    mesh = model.network._mesh2d.get_mesh2d()
    node_x, node_y = mesh.node_x.copy(), mesh.node_y.copy()
    face_x, face_y = mesh.face_x.copy(), mesh.face_y.copy()
    bed = interpolate_xy(inputs.dem_xyv, node_x, node_y)
    manning = interpolate_xy(inputs.roughness_xyv, face_x, face_y)
    if min(bed) < -100 or max(bed) > 9000:
        raise ValueError("DEM elevations are outside plausible source-data bounds")
    if min(manning) <= 0:
        raise ValueError("Manning samples must be positive")
    # SOURCED: DEM exports are metres elevation, positive up; net node_z and bedlevel use the
    # same positive-up convention. Manning values are dimensionless s/m^(1/3).
    model.network._mesh2d.mesh2d_node_z = bed
    netfile = CASE_INPUTS / f"{RUN_ID}_net.nc"
    model.network.to_file(netfile)

    # M3 RULE 3: re-read our own hydrolib-written net and compare node/edge/face counts and node
    # coordinates before any solver launch. Coordinates are compared at writer precision.
    reread = Network.from_file(netfile)._mesh2d.get_mesh2d()
    roundtrip = {
        "node_count": [len(node_x), len(reread.node_x)],
        "edge_count": [len(mesh.edge_x), len(reread.edge_x)],
        "face_count": [len(face_x), len(reread.face_x)],
        "node_coordinates_max_abs_error_m": max(
            max(abs(node_x - reread.node_x)), max(abs(node_y - reread.node_y))
        ),
    }
    if roundtrip["node_count"][0] != roundtrip["node_count"][1] or \
       roundtrip["edge_count"][0] != roundtrip["edge_count"][1] or \
       roundtrip["face_count"][0] != roundtrip["face_count"][1] or \
       roundtrip["node_coordinates_max_abs_error_m"] > 1e-6:
        raise RuntimeError(f"mesh round-trip failed: {roundtrip}")

    # CHOSEN IN PILOT: write actual mesh-located XYZ samples and let D-Flow FM's initial-field
    # triangulation interpolate them. This avoids pretending cell-centred roughness is a net node
    # property. Bed samples are also supplied via the kernel's bedlevel initial-field quantity.
    bed_xyz = CASE_INPUTS / "bedlevel_samples.xyz"
    with bed_xyz.open("w") as stream:
        for x, y, z in zip(node_x, node_y, bed):
            stream.write(f"{x:.6f} {y:.6f} {z:.6f}\n")
    friction_xyz = CASE_INPUTS / "manning_samples.xyz"
    with friction_xyz.open("w") as stream:
        for x, y, n in zip(face_x, face_y, manning):
            stream.write(f"{x:.6f} {y:.6f} {n:.8f}\n")
    inifield = IniFieldModel(initial=[
        InitialField(quantity="bedlevel", datafile=DiskOnlyFileModel(filepath=Path("bedlevel_samples.xyz")),
                     datafiletype="sample", interpolationmethod="triangulation", locationtype="all"),
    ], parameter=[
        ParameterField(quantity="frictioncoefficient", datafile=DiskOnlyFileModel(filepath=Path("manning_samples.xyz")),
                       datafiletype="sample", interpolationmethod="triangulation", locationtype="all"),
    ])
    inifield.save(filepath=CASE_INPUTS / "pilot_initial_fields.ini")
    inifield = IniFieldModel(filepath=CASE_INPUTS / "pilot_initial_fields.ini")

    # SOURCED: hydrograph.tim is in minutes since t0 and already includes base_flow. Never add
    # base_flow a second time. CHOSEN IN PILOT: shift it by the 120-minute flat-flow spin-up.
    hydro = inputs.hydrograph_min_q
    base_flow = float(hydro[0, 1])
    spinup_min = 120.0
    stop_min = 1800.0  # CHOSEN IN PILOT: extended to 30 h total; three POIs remained dry at 20 h.
    q_rows = [[0.0, base_flow], [spinup_min, base_flow]]
    q_rows.extend([[float(t + spinup_min), float(q)] for t, q in hydro[1:]])
    if q_rows[-1][0] < stop_min:
        q_rows.append([stop_min, float(hydro[-1, 1])])
    # CHOSEN IN PILOT: use a point source at breach_location after the upstream discharge
    # boundary produced persistent 794-1,735 m/s spikes next to its clipped cells and failed to
    # wet downstream POIs. D-Flow FM source/sink `.bc` input accepts discharge in m3/s.
    source_tim = CASE_INPUTS / "breach_source.tim"
    source_tim.write_text("\n".join(f"{t:.4f} {q:.4f}" for t, q in q_rows) + "\n")
    outlet_series = TimeSeries(
        name="downstream_outlet_0001", function="timeseries", timeinterpolation="linear",
        quantityunitpair=[QuantityUnitPair(quantity="time", unit="minutes since 2001-01-01 00:00:00"),
                          QuantityUnitPair(quantity="neumannbnd", unit="-")],
        datablock=[[0.0, 0.0], [stop_min, 0.0]],
    )
    outlet_bc = ForcingModel(forcing=[outlet_series])
    outlet_bc.save(filepath=CASE_INPUTS / "downstream_neumann.bc")

    def write_pli(name: str, coords: list[tuple[float, float]]) -> Path:
        path = CASE_INPUTS / f"{name}.pli"
        path.write_text(name + f"\n{len(coords)} 2\n" + "\n".join(f"{x:.3f} {y:.3f}" for x, y in coords) + "\n")
        return path

    write_pli("downstream_outlet", outlet_edge)
    ext = ExtModel(
        boundary=[
            Boundary(quantity="neumannbnd", locationfile=DiskOnlyFileModel(filepath=Path("downstream_outlet.pli")), forcingfile=DiskOnlyFileModel(filepath=Path("downstream_neumann.bc"))),
        ],
        sourcesink=[SourceSink(
            id="breach_source_0001", name="breach_source_0001", numcoordinates=1,
            xcoordinates=[inputs.breach_xy[0]], ycoordinates=[inputs.breach_xy[1]],
            discharge=DiskOnlyFileModel(filepath=Path("inputs/breach_source.tim")),
        )],
    )
    # M3 RULE 2: hydrolib-core defaults to unsupported 3.00; this kernel requires 2.01.
    ext.general.fileversion = "2.01"
    ext.save(filepath=CASE_INPUTS / "pilot_forcing.ext")

    observation_points = XYNModel(
        points=[XYNPoint(x=x, y=y, n=name) for name, x, y in inputs.pois],
    )
    observation_points.save(filepath=CASE_INPUTS / "pilot_observations.xyn")

    # FM DEFAULT: all numerics and physics not explicitly set below remain D-Flow FM defaults.
    # CHOSEN IN PILOT: Manning friction type; 30 s user timestep, 0.5 s initial timestep,
    # 120 s map interval, 60 s history interval, and lean map/history field selections.
    # UNCLEAR: whether 30 s is stable at this mesh and this inflow; any instability requires a
    # recorded change before treating the pilot as frozen.
    # FM DEFAULT: CFLmax=0.7; restore the kernel default after the CFL=10 diagnostic produced
    # implausible velocities (581.8 m/s).
    # M3 RULE 4 / CHOSEN IN PILOT: all paths are relative to the MDU or their parent file.
    mdu = FMModel(
        general=General(pathsrelativetoparent=True),
        geometry=Geometry(
            netfile=DiskOnlyFileModel(filepath=Path(f"inputs/{RUN_ID}_net.nc")),
            inifieldfile=inifield,
            bedlevtype=3,
            bedlevuni=float(min(bed)),
            waterlevini=float(min(bed)),
        ),
        time=Time(refdate=REFDATE, tstart=0.0, tstop=stop_min * 60.0, tunit="S", dtuser=30.0,
                  dtmax=30.0, dtinit=0.5),
        physics=Physics(uniffricttype=2),
        numerics=Numerics(cflmax=0.7),
        external_forcing=ExternalForcing(extforcefilenew=DiskOnlyFileModel(filepath=Path("inputs/pilot_forcing.ext"))),
        output=Output(
            outputdir=Path("output"),
            obsfile=[DiskOnlyFileModel(filepath=Path("inputs/pilot_observations.xyn"))],
            mapinterval=[120.0],
            hisinterval=[60.0],
            **{
                **{key: False for key in Output.model_fields
                   if key.startswith("wrimap_") or key.startswith("wrihis_")},
                "wrimap_waterdepth": True,
                "wrimap_velocity_magnitude": True,
                "wrihis_waterdepth": True,
                "wrihis_velocity": True,
                "wrihis_waterlevel_s1": True,
            },
        ),
    )
    mdu.general.comments = mdu.general.comments.model_copy(update={"program": LABEL})
    mdu.save(filepath=CASE / f"{RUN_ID}.mdu", recurse=False, path_style="unix")
    # hydrolib-core preserves an absolute filepath for a loaded nested IniFieldModel. Normalize
    # that one reference after serialization so the case remains relocatable.
    mdu_path = CASE / f"{RUN_ID}.mdu"
    mdu_text = mdu_path.read_text().replace(
        str(CASE_INPUTS / "pilot_initial_fields.ini"), "inputs/pilot_initial_fields.ini"
    )
    mdu_text = mdu_text.replace(
        "bedLevType                     = 3",
        "bedLevType                     = 3\ncosphiutrsh                    = 0.99\nremovesmalllinkstrsh           = 0.0",
    )
    mdu_path.write_text(mdu_text)

    map_default_enabled = sorted(
        field.alias for key, field in Output.model_fields.items()
        if key.startswith("wrimap_") and field.default is True
    )
    his_default_enabled = sorted(
        field.alias for key, field in Output.model_fields.items()
        if key.startswith("wrihis_") and field.default is True
    )
    map_enabled = ["wrimap_waterdepth", "wrimap_velocity_magnitude"]
    his_enabled = ["wrihis_waterdepth", "wrihis_velocity", "wrihis_waterlevel_s1"]
    case_meta = {
        "label": LABEL,
        "solver": "D-Flow FM 1.2.184 / DIMR 2.00",
        "crs": "EPSG:32645",
        "cell_count": int(len(face_x)),
        "mesh_roundtrip": roundtrip,
        "domain_area_m2": domain_area_m2,
        "inflow_method": "point source at breach_location",
        "inflow_boundary_fallback_reason": "discharge boundary produced 794-1,735 m/s spikes next to clipped cells and downstream POIs remained dry",
        "breach_corridor_width_m": 180,
        "mesh_clip_offset_from_breach_m": 75,
        "manning_range": [float(min(manning)), float(max(manning))],
        "bed_elevation_range_m_positive_up": [float(min(bed)), float(max(bed))],
        "base_flow_m3s_already_in_hydrograph": base_flow,
        "spinup_s": spinup_min * 60,
        "stop_s_since_simulation_start": stop_min * 60,
        "map_interval_s": 120,
        "changes_from_fm_defaults": [
            {"setting": "PathsRelativeToParent", "default": 0, "new_value": 1, "reason": "M3 RULE 4 relocatable relative paths"},
            {"setting": "RefDate", "default": 20200101, "new_value": int(REFDATE), "reason": "CHOSEN IN PILOT reference date for hydrograph and source time series"},
            {"setting": "BedLevUni", "default": -5.0, "new_value": float(min(bed)), "reason": "CHOSEN IN PILOT uniform bed fallback matches positive-up DEM minimum"},
            {"setting": "WaterLevIni", "default": 0.0, "new_value": float(min(bed)), "reason": "CHOSEN IN PILOT start from the lowest domain elevation; flat base-flow spin-up wets the domain"},
            {"setting": "TStop", "default": 86400.0, "new_value": stop_min * 60, "reason": "CHOSEN IN PILOT 30 h total after 20 h run still had three dry POIs"},
            {"setting": "DtUser", "default": 300.0, "new_value": 30.0, "reason": "CHOSEN IN PILOT forcing and output cadence for steep terrain"},
            {"setting": "DtInit", "default": 1.0, "new_value": 0.5, "reason": "CHOSEN IN PILOT small initial step during base-flow spin-up"},
            {"setting": "uniffricttype", "default": 1, "new_value": 2, "reason": "SOURCED Manning n samples require Manning friction convention"},
            {"setting": "MapInterval", "default": 1200.0, "new_value": 120.0, "reason": "CHOSEN IN PILOT arrival-time resolution and lean output"},
            {"setting": "HisInterval", "default": 300.0, "new_value": 60.0, "reason": "CHOSEN IN PILOT POI arrival and peak resolution"},
            {"setting": "OutputDir", "default": "", "new_value": "output", "reason": "CHOSEN IN PILOT keep output products together in the case"},
            {"setting": "WriMap_*", "default_enabled": map_default_enabled, "new_enabled": map_enabled, "reason": "CHOSEN IN PILOT disable all other default map variables to control map size"},
            {"setting": "WriHis_*", "default_enabled": his_default_enabled, "new_enabled": his_enabled, "reason": "CHOSEN IN PILOT disable default history variables except POI water level, depth, and velocity"},
            {"setting": "Cosphiutrsh", "default": 0.5, "new_value": 0.99, "reason": "CHOSEN IN PILOT kernel geometry gate; mesh max cos(phi)=0.968"},
            {"setting": "Removesmalllinkstrsh", "default": 0.1, "new_value": 0.0, "reason": "CHOSEN IN PILOT kernel auto-discard thresholds 0.1 and 0.3 triggered an error; mesh cleanup is done before writing; numerical implications remain UNCLEAR"},
            {"setting": "CFLmax", "default": 0.7, "new_value": 0.7, "reason": "FM DEFAULT restored after diagnostic run produced implausible speeds"},
        ],
    }
    (CASE / "case_meta.json").write_text(json.dumps(case_meta, indent=2) + "\n")

    # CHOSEN IN PILOT: clear this script's prior output products so an earlier run cannot satisfy
    # the rule-1 output existence check.
    for artifact in OUTPUT.iterdir():
        if artifact.is_file():
            artifact.unlink()

    # M3 RULE 6 and CLAUDE.md kernel command: remove all /mnt/* entries from PATH. Launch as a
    # detached process, then poll it; the process exit status is recorded but never used for success.
    kernel = Path.home() / "delft3d/dflowfm-2026.01/lnx64/bin/run_dflowfm.sh"
    filtered_path = ":".join(part for part in os.environ.get("PATH", "").split(":") if not part.startswith("/mnt/"))
    env = dict(os.environ, PATH=filtered_path)
    log_path = CASE / "kernel_runtime.log"
    start = time.monotonic()
    with log_path.open("w") as log:
        process = subprocess.Popen(
            ["/usr/bin/time", "-v", str(kernel), f"{RUN_ID}.mdu"],
            cwd=CASE, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
        )
        (CASE / "kernel.pid").write_text(str(process.pid) + "\n")
        while process.poll() is None:
            time.sleep(20)
            print(f"D-Flow FM running: elapsed_s={int(time.monotonic() - start)} pid={process.pid}", flush=True)
    runtime_s = time.monotonic() - start

    dia_files = list(OUTPUT.glob("*.dia")) + list(CASE.glob("*.dia"))
    errors = [line for path in dia_files for line in path.read_text(errors="replace").splitlines()
              if line.startswith("** ERROR")]
    map_files = list(OUTPUT.glob("*_map.nc"))
    his_files = list(OUTPUT.glob("*_his.nc"))
    finished_marker = any("Computation finished at:" in path.read_text(errors="replace") for path in dia_files)
    success = not errors and bool(map_files) and bool(his_files) and finished_marker
    if not success:
        raise RuntimeError(
            f"M3 success rule/completion failed: no ** ERROR={not errors}, map={bool(map_files)}, "
            f"his={bool(his_files)}, completed={finished_marker}; "
            f"exit={process.returncode}; inspect {log_path} and *.dia"
        )

    # CHOSEN IN PILOT: evaluate arrival relative to the spun-up t0 depth + 0.1 m, matching the
    # UNCLEAR wet-channel clarification proposed in docs/decisions.md. Map output is sampled 120 s.
    summary = summarize_dflowfm_pilot(CASE, OUTPUT, spinup_min * 60, stop_min * 60)
    runtime_log = log_path.read_text(errors="replace")
    elapsed_match = re.search(r"Elapsed \(wall clock\) time \(h:mm:ss or m:ss\): ([0-9:]+(?:\.[0-9]+)?)", runtime_log)
    if elapsed_match:
        parts = [float(piece) for piece in elapsed_match.group(1).split(":")]
        runtime_s = sum(value * (60 ** (len(parts) - i - 1)) for i, value in enumerate(parts))
    ram_match = re.search(r"Maximum resident set size \(kbytes\): (\d+)", runtime_log)
    peak_ram_kb = int(ram_match.group(1)) if ram_match else None

    # Output metadata always carries the placeholder label, independently of MDU comments.
    meta = {
        **case_meta,
        "run_label": LABEL,
        "kernel_exit_code_not_success_signal": process.returncode,
        "runtime_s": runtime_s,
        "peak_ram_kb": peak_ram_kb,
        "map_file_bytes": sum(path.stat().st_size for path in map_files),
        "his_file_bytes": sum(path.stat().st_size for path in his_files),
        "case_disk_bytes": sum(path.stat().st_size for path in CASE.rglob("*") if path.is_file()),
        "summary_metrics": summary,
        "success_rule": {"dia_has_no_line_starting_error": True, "map_exists": True, "his_exists": True,
                         "computation_finished_marker": finished_marker},
    }
    (OUTPUT / "run_meta_pilot.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
