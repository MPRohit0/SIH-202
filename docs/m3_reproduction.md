# Phase 3: Teesta pilot reproduction

## 2026-09-27 — frozen-pilot reference-path reproduction (controlled; not production)

This controlled run checks the existing generated-case writer against the retained frozen pilot
using the pilot's own exported geometry, terrain/Manning samples, source series and POIs. It is
separate from the earlier generated production-domain attempts below. It does not make the
placeholder pilot inputs suitable for production.

| Item | Frozen pilot | Generated reference case | Result / root cause |
|---|---|---|---|
| CRS | EPSG:32645 | EPSG:32645 | exact |
| Mesh | 18,034 nodes / 51,051 edges / 33,018 faces | same counts; net writer round-trip exact | exact geometry path reused |
| Terrain/Manning samples | 18,034 node elevations / 33,018 face n values | bitwise numeric equality | previous generated production case sampled a different full M1 domain/mesh |
| Domain/outlet | pilot reach polygons L002/L004/L006, buffered/clipped; retained 14-point outlet | same pilot geometry helper and outlet coordinates | exact; prior production used all-component M1 domain and perimeter-derived outlet |
| POIs | four pilot XYN points | byte-identical four points | exact |
| Breach/source | point source at exported breach location; frozen source series includes 60 m³/s base flow | same location and byte-identical `breach_source.tim` | exact; previous production run used M2 hydrograph plus configured base flow on another geometry |
| Solver window / outputs | 108,000 s, map 120 s, history 60 s, 30 s user step | same | exact output cadence and duration |
| MDU diagnostic | mass-balance output disabled | enabled for generated metadata | additive diagnostic only; original common outputs remain equal |
| Solver results | 901 map / 1,801 history records | same dimensions; all 14 common map variables and 11 common history variables exactly equal | numerical reproduction PASS |
| Maxima | 65.23152497 m depth; 29.44025086 m/s speed | same | exact |
| Runtime/resources | retained historic run | 468.5 s elapsed; peak RAM 228.1 MiB | controlled host/run only |
| Outputs | map 481,977,476 B; history 236,980 B | map 481,977,476 B; history 762,940 B | generated history is larger because it records water-balance variables |

The earlier generated case reconstructed an unrelated M1 domain (3,234 faces before boundary
segmentization; 77,415 after), connected all components/POIs, and derived a different outlet, while
the frozen pilot uses a deliberately clipped three-reach geometry and explicit outlet. The
3,234-face case also predates boundary segmentization. Historical `sourcesink_discharge` `** ERROR`
attempts were separate rejected boundary-input experiments; the accepted frozen pilot and this
reproduction use a point source and have no `.dia` error markers.

Added `build_pilot_reproduction_case()` as a controlled reference mode in the existing M3 generator
module. It consumes only retained pilot exports and the pilot-only config; it does not alter the
default `build_case()` path or `sites/teesta.yaml`. The production Teesta case remains blocked until
its real domain and fields are sourced/approved and cascade inputs are resolved. This PASS
establishes generator/solver equivalence for the frozen pilot setup, not scientific validity or
production readiness.

## Decision

[SOURCED] The generated case ran to its configured 30-hour stop. Its `.dia` contains no line starting `** ERROR`, and both `model_map.nc` and `model_his.nc` exist. This satisfies M3 rule 1 for that run.

[SOURCED] **Reproduction failed. Do not accept the generated case as a reproduction.** Mesh, sampled fields, and outputs do not meet the Phase 3 comparison tolerances in `docs/m3_spec.md`.

## Inputs and run

[SOURCED] Generator inputs were the pilot-only `teesta_pilot` config, the M1 products under `data/teesta_pilot/terrain/`, and the M2 hydrograph parameters from `data/teesta_pilot/breach/hydrographs/teesta_pilot_s001__south_lhonak.json`. The generator independently rebuilt the mesh from M1 `domain.gpkg`; it did not read the frozen pilot's staged `domain.pol`/XYZ export files. That source-geometry difference is recorded as a reproduction limitation and is itself part of the mismatch.

[SOURCED] The generated case is at `data/teesta_pilot/runs/teesta_pilot_s001/dflowfm_reproduction/case/`. It carries `PLACEHOLDER — teesta_pilot_s001, all inputs placeholder`. The run used D-Flow FM 1.2.184, 30-hour stop time, 2-hour spin-up, and 120-second maps. The `.ext` is version 2.01 and case-file references are relative.

[SOURCED] Kernel time reported in `.dia` was 1.86 s. The map file is 47,254,256 bytes, history is 236,980 bytes, and case-tree size is 48,900,244 bytes. Peak RAM was not captured for this reproduction run.

## Mesh comparison

[SOURCED] The frozen pilot has 18,034 nodes, 51,051 edges, and 33,018 faces. The generated case has 2,216 nodes, 5,450 edges, and 3,234 faces. Each generated `_net.nc` passed its own pre-run hydrolib round-trip count and coordinate checks; cross-case mesh comparison did not pass.

[SOURCED] In nearest-node comparisons between the two meshes, generated-to-pilot distances were 35.03 m median, 55.63 m at p90, 1,945.56 m at p99, and 7,218.41 m maximum. Pilot-to-generated distances were 149.10 m median, 394.34 m at p90, 659.38 m at p99, and 1,042.88 m maximum. Counts, spatial coverage, and the node-sample files therefore differ materially.

## Normalized text comparisons

[SOURCED] Comments (text after `#`) and blank lines were removed, and whitespace was collapsed before comparing ordered lines. The table reports normalized `SequenceMatcher` similarity; exactness is still required by the spec.

| File | Normalized similarity | Result |
|---|---:|---|
| `.mdu` | 98.36% | Fail: settings/paths and mesh-derived values differ |
| `.ext` | 64.29% | Fail: generated forcing topology differs from pilot |
| downstream `.bc` | 100.00% | Pass for this file only |
| downstream `.pli` | 10.00% | Fail: generated outlet segment differs |
| observation `.xyn` | 100.00% | Pass for this file only |
| initial fields `.ini` | 89.47% | Fail: generated sample references differ |
| breach source `.tim` | 2,333 / 2,333 rows | Fail: time coordinates differ slightly from formatting/resampling; discharge values differ by at most 0.0063 m³/s on pilot timestamps |
| bed sample XYZ | 0.00% | Fail: 18,034 pilot nodes vs 2,216 generated nodes |
| Manning sample XYZ | 0.00% | Fail: 33,018 pilot faces vs 3,234 generated faces |

[SOURCED] The pilot has an upstream boundary trial retained alongside its breach point-source fallback. The generator uses only the point source and downstream Neumann boundary, so the `.ext` and geometry files do not match. The observation coordinates match exactly after normalization.

[CHOSEN IN PILOT] The generator now drops M2's t=0 row when shifting the breach series to spin-up, avoiding a duplicate timestamp at 120 minutes. Its base-flow addition remains exactly once because M2 emits breach-only discharge.

## Result comparison

[SOURCED] Results use identical post-processing: 0.1 m depth increase above t0 for arrival; map interval 120 s.

| Metric | Frozen pilot | Generated | Difference / outcome |
|---|---:|---:|---|
| Global maximum depth | 65.2315 m | 1,841.4446 m | +1,776.2131 m; fail (0.1 m tolerance) |
| Global maximum speed | 29.4403 m/s | 0.0293 m/s | −29.4110 m/s; fail |
| Chungthang maximum depth | 11.1348 m | 0.0000 m | Fail (0.05 m tolerance) |
| Chungthang maximum speed | 5.1631 m/s | 0.0000 m/s | Fail (0.1 m/s tolerance) |
| Chungthang arrival | 55,860 s | Not reached | Fail (120 s tolerance) |
| Reached map faces | 4,033 / 33,018 | 2 / 3,234 | Different wet extent |

[SOURCED] Lachen, Sangkalang Bridge, and Mangan District Hospital remained dry in both runs. The generated case's extreme depth and near-zero velocity indicate that a successful kernel completion alone does not validate the generated solution.

## Mismatches still open

[UNCLEAR] Phase 3 remains incomplete and unaccepted until the generator can consume equivalent pilot M1 geometry and source fields, reproduce the pilot mesh to the specified tolerance, and meet the `.mdu`/`.ext`/boundary/initial-field and output tolerances. The current generator's independently built mesh and results do not satisfy those requirements.

## 2026-09-27 map-interval follow-up

[SOURCED] The generator now sets `MapInterval=60 s`, matching `HisInterval`, to sample the proposed 0.1 m arrival threshold at 60-second resolution. A fresh case was generated under `data/teesta_pilot/runs/teesta_pilot_s001/dflowfm_reproduction_map60/case/`; the frozen pilot and original Phase 3 case were not modified. D-Flow FM completed the 30-hour run with no `.dia` error and both output files present. The map contains 1,801 samples at 60-second spacing.

[SOURCED] Reproduction still fails: the generated mesh remains 3,234 faces, POIs remain dry, global maximum depth is 1,841.44 m, and global maximum speed is 0.4383 m/s. The interval change improves only the time sampling and does not address the recorded geometry/input/solution mismatch.

## 2026-09-27 mesh-spacing fix attempt

[SOURCED] Inspection of the generated map showed that the configured 90 m spacing was not
constraining the mesh: the 3,234-face mesh had a median face-edge length of 185 m, p90 504 m,
and maximum 8,296 m. The frozen pilot's 33,018-face mesh had median 90.4 m, p90 122.7 m, and
maximum 156.2 m. `backend/m3_dflowfm/generator.py` now densifies polygon boundary segments to at
most the requested spacing before MeshKernel triangulates them.

[SOURCED] A generated 90 m pilot case (`data/teesta_pilot/runs/teesta_pilot_s001__delft3d_seg90/`)
ran for 30 simulated hours with D-Flow FM 1.2.184. The `.dia` has no `** ERROR`; both expected
NetCDF outputs exist. The net has 77,415 faces and passed writer round-trip checks. Runtime was
994.7 s (16 min 35 s); the raw map is about 1.13 GB. Contract post-processing passed
`run_meta.schema.json` validation and wrote 623 x 611 summary rasters aligned to the pilot's
canonical grid. Maximum depth was 67.38 m and maximum velocity 33.14 m/s; 1,878 in-domain cells
were wet.

[SOURCED] The behavioral gate still fails: all four generated POIs remained dry, including
Chungthang (depth 0 m, no arrival), while the frozen pilot reaches Chungthang (11.13 m, 5.16 m/s,
arrival 55,860 s). The nearest generated wet face was 3.70 km from Chungthang. The generated case
contains only the South Lhonak source; the configured Teesta III cascade cannot be triggered
because `sites/teesta.yaml` has no trigger threshold and `backend/m2_breach/cascade.py` correctly
blocks a null threshold. The pilot also uses different domain and terrain samples, so the missing
stage-2 hydrograph is a concrete mismatch but is not yet proven to be the only cause. Keep Phase 3
reproduction unaccepted and do not begin the 2–3 scenario smoke campaign.

## 2026-09-27 implementation audit — pilot vs generated geometry

This audit compares retained pilot and generated artifacts; it is not a new solver run. The pilot remains a placeholder engineering reference, not a physically validated Teesta model.

| Item | Frozen pilot | Generated case | Finding |
|---|---|---|---|
| CRS | EPSG:32645 | EPSG:32645 | Match |
| Domain source | `domain.pol` reaches L002/L004/L006; 400 m reach buffer; 90 m breach and POI corridors; 30 m simplify; clipped at x = breach − 75 m and the chosen downstream reach edge | Full M1 `domain.gpkg` MultiPolygon; connectors to every component and POI; simplify by half mesh spacing; no equivalent pilot clip | **Root cause:** different computational domains and boundary geometry |
| Mesh | 18,034 nodes / 51,051 edges / 33,018 faces | Original reproduction: 3,234 faces; retained segmented 90 m follow-up: 77,415 faces | Neither matches. The 3,234-face case predates boundary segmentization; segmentization fixed long unconstrained edges but produces a denser mesh on the unsmoothed full M1 geometry |
| Source | Point source at UTM (618095.227, 3087257.641), pilot `.tim` hydrograph | Same point-source coordinates; M2-derived `.tim` with configured 60 m³/s base flow added once | Coordinates and early forcing rows match to text precision; the current point-source format runs. Rejected `sourcesink_discharge` `.bc` attempts are separate historical failures |
| POIs | Four pilot locations in EPSG:32645 | Same four coordinates and IDs | Match |
| Terrain fields | M1 `dem.tif` and `roughness.tif`, interpolated at pilot mesh nodes/faces | Same source rasters, sampled at a different mesh | Source products match; discrete samples differ with mesh locations |
| Outlet | Pilot's chosen downstream reach edge and pilot `.pli` | Outlet derived from the full M1 centreline endpoint and nearest perimeter segment | **Root cause:** open-boundary geometry differs |
| Solver setup | 30 h; 2 h spin-up; 30 s timestep; 60 s history; 120 s map | Same duration, spin-up and timesteps; 120 s map in original and 60 s in later sampling trial | Substantially matches; output cadence alone did not fix behavior |
| Results | Global max 65.2315 m / 29.4403 m/s; Chungthang 11.1348 m, 5.1631 m/s, arrival 55,860 s | Original coarse case: 1,841.4446 m / 0.0293 m/s; retained segmented case: 67.38 m / 33.14 m/s; all four POIs dry, nearest wet face 3.70 km from Chungthang | Segmentation brought global maxima near the pilot, but wetting and POI behavior still fail |

The supported implementation diagnosis is **domain/mesh/outlet non-equivalence**, not a proven bad scientific parameter. The pilot selects and smooths/clips a reduced reach; the production generator uses the full M1 domain with different connector and outlet algorithms. The pilot's 400 m buffer, 90 m corridors and clipping rules are documented pilot choices. They can be reused only in a clearly scoped pilot-reproduction path; they are not real-site measurements. The absent cascade stage is not itself a pilot-reproduction mismatch: the frozen reference also uses only the South Lhonak source. It remains a separate production-input blocker for the real two-dam scenario.

**Code/config change in this audit:** none. Boundary segmentization and 60 s map sampling are prior changes; the retained segmented run results above are their post-change evidence. Reproduction remains **FAILED**. No production campaign is authorized by this report.
