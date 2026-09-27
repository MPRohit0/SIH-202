# Phase 3: Teesta pilot reproduction

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
