# SIH26 PS-26161 — GLOF / Dam-Break Decision-Support Tool

## What this project is
A fast, low-data flood decision-support tool for glacial lake outburst floods (GLOFs) and
dam-break scenarios in Himalayan India. Users are DDMA/SDMA/NDMA/CWC officials who consume
GIS layers, not hydraulic modellers. Speed and honest uncertainty matter more than
third-decimal physical accuracy.

Core idea: run expensive physics (Delft3D FM, DualSPHysics) OFFLINE over a designed scenario
set, then answer live queries in seconds with a PCA + Gaussian Process emulator
(Donnelly et al. 2022). Breach parameters come from empirical / data-fusion equations
(Azmi 2026). Sites without a trained emulator fall back to empirical breach + HAND flow routing.

Demo sites:
- Teesta: South Lhonak GLOF (Oct 2023) cascading to Teesta III (Chungthang) dam
- Rishi Ganga (Chamoli, Feb 2021): validation case + post-event Raunthi Gad landslide-lake scenario

## Read these before designing anything
| File | What it is |
|---|---|
| `docs/handoff_contract.md` | **Every data format, ID, unit, file path and API endpoint.** Source of truth with `contracts/` |
| `docs/ideation.md` | What we're building and why |
| `docs/decisions.md` | Team decisions (thresholds, cascade approach, run budget...) |
| `docs/data_sources.md` | Every source, with IDs like `src_014` used in site configs |
| `docs/paper_azmi.md`, `docs/paper_donnelly.md` | Method summaries |
| `docs/equations.md` | Verified breach equations — the ONLY place to take equations from |
| `docs/m5_spec.md` | Emulator spec, synthetic world, confidence rule, acceptance tests |
| `docs/events/*.md` | Historical event reconstructions |
| `sites/*.yaml` | Site configs |
| `frontend/CLAUDE.md` | Extra rules when working in the frontend |

If a file above doesn't exist yet, say so instead of guessing its contents.

## Architecture (backend modules)
| Module | Folder | Job |
|---|---|---|
| M0 | backend/m0_api | FastAPI orchestrator (`/api/v1`), job queue + worker, rendering, serves frontend |
| M1 | backend/m1_terrain | DEM, land cover → Manning's n, HAND, domain, centreline, POIs, near-field STL |
| M2 | backend/m2_breach | Breach parameters, dual-method ranges, hydrographs, cascades |
| M3 | backend/m3_delft3d | Delft3D FM case generation, launch, post-processing to summary maps |
| M4 | backend/m4_sph | DualSPHysics near-field cases, launch, post-processing (same schema as M3) |
| M5 | backend/m5_emulator | Scenario design, cache, PCA+GP emulator, LOOCV, Monte Carlo, confidence, fallback |
| M6 | backend/m6_impact | Exposure overlay, warning table, loss, exports (.shp/.kml/.geojson/.pdf) |
| M7 | backend/m7_gee | Offline GEE fetch (lake area, rainfall, event imagery), cache, fallback |
| — | backend/campaign.py | Runs whole scenario sets through M3/M4 |
| — | backend/shared | Site config loader, canonical grids, common helpers |

M3 and M4 MUST produce outputs in the identical schema so SPH-vs-Delft3D comparison is trivial.

## Non-negotiable rules
1. `docs/handoff_contract.md` + `contracts/` define all data. Every input/output validates
   against a schema. If the contract seems wrong, STOP and ask; never change it silently.
2. Every module runs end-to-end on SYNTHETIC data with pytest tests before real data exists.
3. NEVER invent site data, dam specs, event facts, coefficients, validation metrics or
   confidence numbers. Facts come from `sites/*.yaml` (SourcedValue with source + status).
   Missing facts stay `status: placeholder`; results then set `has_placeholders: true`.
4. Equations come only from `docs/equations.md`. One function per equation; docstring gives
   source, equation number, input/output units and valid range; warn outside the range.
5. SI units everywhere, including the API. Failure time is stored in seconds even if an
   equation returns hours — convert at the function boundary. Formatting is the frontend's job.
6. Time zero (t0) = start of the most upstream breach. All times are seconds since t0.
7. CRS: compute in the site's UTM zone (Teesta EPSG:32645, Rishi Ganga EPSG:32644).
   GeoJSON/KML/frontend in EPSG:4326 (lon, lat). Leaflet bounds are `bounds_latlng`
   (lat first). Every raster aligns exactly to the site's canonical grid.
8. Nodata = -9999.0 for floats; use `domain_mask.tif` to tell "outside domain" from "dry".
9. Every result number is an Estimate: value + low/high + unit + interval + kind
   (predicted | observed | input) + confidence. Never mix predicted and observed.
10. Every result carries `caveats` and `provenance`. IDs follow the contract patterns.
11. Localhost only. No cloud services, no managed DB, no auth. GEE only for offline prep,
    with cache + screenshot fallback.
12. Secrets live in `.env` (gitignored). Never print, log, commit or hardcode keys.
13. Hardware budget: RTX 4060 8 GB VRAM, 16 GB RAM. Never hold full timestep × cell stacks
    in memory; emulate per-scenario summary maps; process Monte Carlo samples in chunks.
14. Long solver runs launch as detached background jobs through the job system — never
    block a Claude session or the API waiting for them.

## Stack
Python 3.11+, FastAPI, Pydantic v2, SQLite, numpy, scipy, scikit-learn (GP + PCA),
rasterio, rioxarray, GDAL, geopandas, shapely, richdem, simplekml, hydrolib-core,
meshkernel, dfm_tools, pytest.
Frontend (in `frontend/`): React + Vite, Leaflet, Three.js, Recharts, Playwright.

## Simulation tools
<!-- Fill in once installed -->
- Delft3D FM: version <...>, executable <path>
- DualSPHysics: version <...>, GenCase <path>, GPU solver <path>
- Working pilot cases: `m3_pilot/`, `m4_pilot/`, `m3_cascade_pilot/`

## Commands
- Env: `conda env create -f environment.yml && conda activate sih26`
- Tests: `pytest -q`
- API: `uvicorn backend.m0_api.main:app --reload --port 8000`
- Frontend: `cd frontend && npm run dev` · visual tests: `npm run test:visual`

## Directory layout
```
sites/       site configs (YAML)
contracts/   JSON Schemas + examples + styles.json
docs/        contract, ideation, decisions, sources, specs, events, progress
backend/     m0_api ... m7_gee, campaign.py, shared/
tests/       mirrors backend/; fixtures in tests/fixtures/<module>/
data/        gitignored — layout defined in docs/handoff_contract.md §1.8
frontend/    React app (has its own CLAUDE.md)
```

## How to work in this repo
- Plan before coding for anything touching more than one file; wait for approval.
- One module per session. Small, testable steps; suggest a git commit after each.
- Write tests first where possible; run `pytest -q` and fix until green before finishing.
- Prefer simple, readable code; judges will ask how every number was produced.
- When unsure about hydrology, data or a team decision, ask instead of guessing.
- At the end of a session, append a short summary to `docs/progress.md`.

## Known limitations (state these honestly in outputs and docs)
- Breach equations are calibrated on man-made embankment dams; moraine dams are an extrapolation.
- They are not recommended for concrete dams; such dams use imposed ranges from the site config.
- Failure time is poorly predicted by all methods; it is a scenario variable with a wide range.
- Models are clear-water; Himalayan events were debris/sediment-laden.
- Rishi Ganga 2021 was a rock-ice avalanche / mass flow, not a dam breach.