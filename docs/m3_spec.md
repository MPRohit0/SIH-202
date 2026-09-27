# M3 D-Flow FM specification

## Status and scope

[CHOSEN IN PILOT] This Phase 1 specification records the `teesta_pilot_s001` D-Flow FM case in `backend/m3_pilot/dflowfm/case/`, built by `backend/m3_pilot/dflowfm/build_teesta_pilot_s001__dflowfm.py` from the placeholder exports in `backend/m3_pilot/inputs/export/`. It is the reference for M3 case-generation and reproduction work.

[SOURCED] Every input in this pilot is placeholder data. Preserve the case label exactly: `PLACEHOLDER — teesta_pilot_s001, all inputs placeholder`.

[CHOSEN IN PILOT] The completed 30-hour point-source case in `backend/m3_pilot/dflowfm/case/` is the reference run. Earlier trials are retained in `backend/m3_pilot/dflowfm/attempts/`; their outputs are diagnostic history, not the reference result.

[UNCLEAR] The pilot is a hand-reviewed engineering reference, not a calibrated or physically validated Teesta model. The 30-hour run wets Chungthang but leaves Lachen, Sangkalang Bridge, and Mangan District Hospital dry. It reports a global maximum depth of 65.23 m and speed of 29.44 m/s. These outputs and the choice of the point-source fallback remain unresolved for production use.

## Six M3 rules

[SOURCED] Copy from `docs/decisions.md`, “2026-09-26 — M3: back to Delft3D FM”:

1. **Run success** = the `.dia` has no line starting `** ERROR` AND the expected `*_map.nc` and `*_his.nc` exist in the output dir. Never trust the exit code alone: `run_dflowfm.sh` exited 0 in three separate runs where the kernel actually rejected its input.
2. **`.ext` version:** any `.ext` file written by hydrolib-core must have `fileVersion = 2.01` (`ExtModel.general.fileversion = "2.01"`). hydrolib-core 1.4.0 writes 3.00, and this kernel then logs `Unsupported format … Ignoring this file` and silently runs with no boundaries.
3. **Net-file writer:** hydrolib-core's net writer failed on an old (2015) real-world net (meshkernel dropped 1 of 8916 nodes on read; the writer then tried to write `node_z`'s original 8916 values against the reduced node count and raised a shape mismatch). Before trusting the writer for real cases, M3-1 must show on our own meshkernel-built meshes that a written net re-reads with identical node/edge/face counts and that the kernel runs it.
4. **Paths:** case files reference each other with relative paths so cases are relocatable.
5. **Output size:** D-Flow FM tutorial06 wrote an 805 MB `_map.nc` for a 10-day run at default map settings (8355 cells, 1200 s map interval, default `Wrimap_*` variables). M3-1 sets `MapInterval` and the `Wrimap_*` switches to only what post-processing needs (summary maps: max depth, max velocity, arrival time, …), and `docs/run_budget.md` must list **disk per run**, not just wall time and RAM.
6. **Running the kernel:** strip `/mnt/*` from `PATH` before running it (the Windows dirs WSL adds otherwise make cmake — and presumably other tools — pick up Windows-side packages instead of the Linux ones; use `run_dflowfm.sh` for plain MDUs and `run_dimr.sh -m dimr_config.xml` for DIMR configs). Runs launch as detached jobs (CLAUDE.md rule 14).

## Mesh

[SOURCED] The pilot reads domain polygons `L002`, `L004`, and `L006` from `domain.pol`; the DEM and Manning grids have 90 m spacing, and the Teesta CRS is EPSG:32645.

[CHOSEN IN PILOT] The mesh is a MeshKernel triangular 2D mesh. The three exported reach polygons are buffered by 400 m to join disconnected reach components. A 90 m breach corridor joins the breach coordinate to the nearest reach; a 90 m buffer around each POI keeps the observation coordinates in the mesh. The boundary is simplified by 30 m before clipping, below the 90 m source-grid scale. The upstream mesh clip is 75 m west of the breach point. The outlet is clipped at the lowest source-reach edge, limited to the DEM interpolation extent.

[CHOSEN IN PILOT] The inflow boundary geometry is retained in the mesh, but the complete reference case uses a point source at `breach_location.xyz`. Direct discharge-boundary trials on the clipped upstream edge produced 794–1,735 m/s local velocity maxima and dry POIs; the source fallback was used and the reason is recorded in `case_meta.json`.

[CHOSEN IN PILOT] MeshKernel small-flow-edge cleanup is run with length threshold 0.1 m and small-triangle fraction 0.0. The simplified mesh has 18,034 nodes, 51,051 edges, 33,018 faces, and minimum face area about 1,110 m² in the mesh-quality inspection. Record the face count as the pilot cell count: 33,018.

[SOURCED] Before launch, the written `_net.nc` is re-read and checked for equal node, edge, and face counts and node coordinates. The reference run's counts are 18,034 / 51,051 / 33,018 on both sides; maximum coordinate difference is 0 m. The successful kernel run is the run-writer compatibility check required by rule 3.

## Initial fields

[SOURCED] `dem_farfield.xyz` contains elevations in metres, positive upward; `roughness_farfield.xyz` contains Manning's n in s/m^(1/3). D-Flow FM bed levels are positive upward, matching the DEM convention (Deltares D-Flow FM User Manual, “Bed level”).

[CHOSEN IN PILOT] DEM values are bilinearly interpolated from the regular XYZ grid to mesh nodes and written to `bedlevel_samples.xyz`. The ini field uses `quantity=bedlevel`, sample data, triangulation interpolation, and `locationType=all`; MDU `BedlevType=3` reads node bed levels and forms face levels from the node values. The pilot's sampled range is 634.31–5,482.13 m positive up.

[CHOSEN IN PILOT] Manning's n is bilinearly sampled at mesh-face centres and written to `manning_samples.xyz`. The ini field uses `quantity=frictioncoefficient`, sample data, triangulation interpolation, and `locationType=all`; `uniffricttype=2` selects Manning friction. The pilot sample range is 0.02737–0.1 s/m^(1/3).

[CHOSEN IN PILOT] No spatially varying initial water-level field is supplied. `WaterLevIni` and `BedlevUni` are both set to the minimum sampled bed level (634.31 m); this keeps the uniform initial level consistent with the positive-up terrain range. Other initial-water-level behavior is left to FM defaults.

## Inflow, downstream boundary, and spin-up

[SOURCED] `hydrograph.tim` is in minutes since t0 and already includes the 60 m³/s base flow. Do not add base flow again.

[CHOSEN IN PILOT] Flat base flow is applied at the breach point for 120 minutes of spin-up. The hydrograph is shifted by 120 minutes in model time; the source time series is written as `breach_source.tim` and referenced from the `.ext` file. This uses D-Flow FM's point source/sink forcing format after the clipped discharge-boundary trial proved numerically impractical.

[CHOSEN IN PILOT] The canonical site schema exposes optional `domains.far_field.inflow.base_flow` in `backend/shared/site_config.py`, now documented as a field in `sites/template.yaml`. A production case requires a non-null value. M2 hydrographs are breach-only; M3 adds the configured base flow exactly once. This differs from the pilot export `hydrograph.tim`, which already includes base flow and must never have it added again.

[CHOSEN IN PILOT] The downstream outlet is an open `neumannbnd` boundary with zero gradient. All other mesh boundaries use the FM default closed/full-slip treatment.

[CHOSEN IN PILOT] The initial 10-hour run was extended to 20 hours because POI histories were dry; the 20-hour run first registered arrival at Chungthang. The reference stop time is 30 hours total (28 hours after the 2-hour spin-up), which captures the breach wave at Chungthang. The other three POIs remain dry at that stop time.

## Numerics

[FM DEFAULT] `CFLMax=0.7` is the kernel default. A diagnostic run at 10 caused implausible velocities; the reference run returns to 0.7.

[CHOSEN IN PILOT] `DtUser=30 s`, `DtMax=30 s`, and `DtInit=0.5 s` are used for the steep terrain and source ramp. The selected friction type is Manning (`uniffricttype=2`).

[CHOSEN IN PILOT] `Cosphiutrsh=0.99` is set because the mesh's maximum cos(phi) is 0.968 and the kernel's default geometry gate rejected the initial mesh. `Removesmalllinkstrsh=0.0` disables kernel auto-discard: default thresholds 0.1 and 0.3 produced `** ERROR`; mesh cleanup is performed before writing instead.

[FM DEFAULT] Unlisted numerical, physical, and solver settings remain at the D-Flow FM kernel defaults. The pilot's changed settings above must be carried forward unchanged in M3 generation unless a later reviewed decision revises this specification.

## Recorded changes from defaults

[CHOSEN IN PILOT] The case metadata records each change with its default, selected value, and reason. The settings changed from the MDU defaults are summarized here:

| Tag | Setting | Default | Pilot value | Reason |
|---|---|---:|---:|---|
| CHOSEN IN PILOT | `PathsRelativeToParent` | 0 | 1 | Relocatable case paths, M3 rule 4 |
| CHOSEN IN PILOT | `OutputDir` | Empty | `output` | Keep outputs under the case |
| CHOSEN IN PILOT | `RefDate` | 20200101 | 20010101 | Hydrograph reference date |
| CHOSEN IN PILOT | `BedLevUni` | -5 m | 634.31 m | Match positive-up DEM minimum as uniform fallback |
| CHOSEN IN PILOT | `WaterLevIni` | 0 m | 634.31 m | Start at the lowest domain elevation before flat-flow spin-up |
| CHOSEN IN PILOT | `TStop` | 86,400 s | 108,000 s | 30-hour run after 20-hour output left three POIs dry |
| CHOSEN IN PILOT | `DtUser` | 300 s | 30 s | Forcing and output update cadence |
| CHOSEN IN PILOT | `DtInit` | 1 s | 0.5 s | Initial timestep for base-flow spin-up |
| SOURCED | `uniffricttype` | 1 | 2 | Manning n is sourced from the roughness export |
| CHOSEN IN PILOT | `MapInterval` | 1,200 s | 120 s | Arrival resolution and lean map output |
| CHOSEN IN PILOT | `HisInterval` | 300 s | 60 s | POI arrival and peak resolution |
| CHOSEN IN PILOT | `WriMap_*` | Per-field defaults; see `case_meta.json` | Enable water depth and velocity magnitude; disable the rest | Limit map size to post-processing needs |
| CHOSEN IN PILOT | `WriHis_*` | Per-field defaults; see `case_meta.json` | Enable water depth, velocity, and water level; disable the rest | Keep POI histories lean |
| CHOSEN IN PILOT | `Cosphiutrsh` | 0.5 | 0.99 | Permit the generated mesh, whose maximum cos(phi) is 0.968 |
| UNCLEAR | `Removesmalllinkstrsh` | 0.1 | 0.0 | Kernel auto-discard at 0.1 and 0.3 produced errors; mesh cleanup is applied before writing |

[FM DEFAULT] `tUnit=S`, `tStart=0`, `DtMax=30 s`, `BedLevType=3`, and `CFLMax=0.7` match their defaults. They are stated in the case but are not changes from default.

## Output

[CHOSEN IN PILOT] Maps are written every 120 s and history every 60 s. Map variables are limited to water depth and velocity magnitude (`mesh2d_waterdepth`, `mesh2d_ucmag`). History output includes water depth, velocity magnitude, and water level at the four observation points. POI names are the IDs from `pois.xyz`.

[CHOSEN IN PILOT] Arrival is post-processed from 120 s map samples as the first time after t0 when depth exceeds the t0 depth by 0.1 m. This is an UNCLEAR proposed interpretation of the arrival rule; record that proposal alongside results until the contract decision is settled.

[SOURCED] The completed reference run took 475.09 s, peaked at 234,048 KB RAM, wrote a 481,977,476-byte map file, and used 492,784,953 bytes across the case tree. Its success record is `backend/m3_pilot/dflowfm/case/output/run_meta_pilot.json`.

[SOURCED] POI results from the reference history are:

| POI ID | Maximum depth (m) | Maximum speed (m/s) | Arrival after t0 |
|---|---:|---:|---:|
| `teesta_pilot__poi__lachen` | 0.00 | 0.00 | Not reached |
| `teesta_pilot__poi__chungthang` | 11.13 | 5.16 | 55,860 s |
| `teesta_pilot__poi__sangkalang_bridge` | 0.00 | 0.00 | Not reached |
| `teesta_pilot__poi__mangan_district_hospital` | 0.00 | 0.00 | Not reached |

[SOURCED] Global maximum depth is 65.23 m and maximum face-centre speed is 29.44 m/s. The 120-second map samples show arrival in 4,033 faces and no arrival in 28,985 faces. The quick maximum-depth map is `backend/m3_pilot/dflowfm/case/output/quick_max_depth.png`.

## CRS, software, and file formats

[SOURCED] Teesta pilot CRS: EPSG:32645. Chamoli CRS: EPSG:32644.

[SOURCED] Kernel: D-Flow FM 1.2.184 / DIMR 2.00, build package 2026.01. The launch script is `~/delft3d/dflowfm-2026.01/lnx64/bin/run_dflowfm.sh`.

[CHOSEN IN PILOT — 2026-09-27] Runs on this machine use the serial D-Flow FM kernel only. The
reference `.dia` reports `MPI : no` and `OpenMP : unavailable`; the installed kernel bundle has
no MPI launcher or mesh partitioning executable, and its `generate_parallel_mdu.sh` requires
pre-partitioned `_0000_net.nc`-style inputs. Therefore a partitioned MPI run cannot be started
with the installed tools, so no MPI timing comparison is available. Do not enable MPI for this
machine unless an MPI-enabled kernel, partitioner, and partitioned network are installed and
verified together.

[SOURCED] Case-writing libraries: hydrolib-core 1.4.0 and meshkernel 8.3.0, from the project `.venv`.

[SOURCED] File versions observed in the pilot: MDU 1.09; `.ext` 2.01; ini-field `.ini` 2.00; hydrolib boundary `.bc` 1.01; source `.tim` is the legacy unversioned ASCII series format; netCDF is CF-1.8 / UGRID-1.0. `.pli` and `.xyn` are plain-text support-point files with no embedded version field.

## Reproduction tolerances

[CHOSEN IN PILOT] Phase 3 should compare generated text inputs after normalizing comments and timestamps; compare mesh coordinates and geometry numerically; and compare POI history and maximum-depth results.

[UNCLEAR] Provisional tolerances are: mesh coordinates absolute error ≤ 1e-6 m; categorical/text settings exact after normalization; POI water depth and water level absolute error ≤ 0.05 m; POI velocity absolute error ≤ 0.1 m/s; POI arrival difference ≤ 120 s; global maximum-depth absolute error ≤ 0.1 m. These thresholds are proposals for reproduction, not claims about physical accuracy. Record any mismatch and do not accept partial reproduction.

[SOURCED] Phase 3 results and the mismatch decision are recorded in `docs/m3_reproduction.md`. The generator's outputs failed the reproduction checks, so the generated case is not accepted as a reproduction of the frozen pilot.
