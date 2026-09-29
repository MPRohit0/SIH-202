# SIH26 PS-26161 — GLOF / Dam-Break Decision-Support Tool

A fast, low-data flood decision-support tool for glacial lake outburst floods (GLOFs) and
dam-break scenarios in Himalayan India. It is built for DDMA/SDMA/NDMA/CWC officials — people who
read GIS layers and warning tables, not hydraulic modellers — and it favours speed and honest
uncertainty over third-decimal physical accuracy.

**Core idea:** run expensive physics (Delft3D FM / D-Flow FM, DualSPHysics) offline over a
designed set of breach scenarios, then answer live "what if this dam breaches like *this*"
queries in seconds with a PCA + Gaussian Process emulator (Donnelly et al. 2022). Breach
parameters come from empirical/data-fusion equations (Azmi 2026). A site with no trained emulator
yet falls back to empirical breach parameters + HAND-based flow routing, clearly labelled as
lower-confidence.

**Demo site:** Teesta basin — the South Lhonak GLOF (October 2023) cascading into the Teesta III
(Chungthang) dam. This is the only site with a working end-to-end MVP path today (`sites/teesta.yaml`,
`backend/m0_api/mocks.KNOWN_SITE_IDS`). Rishi Ganga (Chamoli, Feb 2021) is documented as a second
demo case in the project brief but has no `sites/rishiganga.yaml` yet — it was a rock-ice avalanche
/ mass flow, not a dam breach, and needs its own scenario approach before it can be onboarded.

Every number this tool shows is either a **sourced fact** (with a citation and a `sourced` /
`placeholder` status) or a **predicted estimate** (with a low/high range, a confidence level, and
caveats) — see `docs/handoff_contract.md` §2 for the exact shapes. Inputs still marked
`placeholder` propagate a `has_placeholders: true` flag all the way to the API response and the
UI; nothing is silently filled in with a guess.

## Where things live (start here)

This README is an entry point, not the source of truth. Before changing anything, read:

| File | What it is |
|---|---|
| [`docs/handoff_contract.md`](docs/handoff_contract.md) | Every data format, ID, unit, file path and API endpoint — the contract everything else is checked against |
| [`docs/ideation.md`](docs/ideation.md) | What we're building and why |
| [`docs/decisions.md`](docs/decisions.md) | Team decisions (thresholds, cascade approach, run budget, tool choices) |
| [`docs/data_sources.md`](docs/data_sources.md) | Every external data source, cited as `src_NNN` from site configs |
| [`docs/Equations.md`](docs/Equations.md), [`docs/paper_azmi.md`](docs/paper_azmi.md) | Breach equations and their source paper |
| [`docs/paper_donnelly.md`](docs/paper_donnelly.md), [`docs/m5_specs.md`](docs/m5_specs.md) | Emulator method and spec |
| [`docs/impact_outputs.md`](docs/impact_outputs.md) | Depth classes, isochrones, population/asset impact outputs |
| [`docs/events/*.md`](docs/events) | Historical event reconstructions used for validation |
| [`sites/*.yaml`](sites) | Site configs (`template.yaml` is the annotated copy-me starting point) |
| [`CLAUDE.md`](CLAUDE.md) | Full project rules (units, CRS, non-negotiables) |
| [`frontend/CLAUDE.md`](frontend/CLAUDE.md) | Extra rules for frontend work (preserve existing UI, no new UI libraries) |

If a file this README or `CLAUDE.md` points at doesn't exist yet, that's a gap to flag, not
something to guess the contents of.

## Architecture

```
                         ┌────────────────────────────────────────────┐
                         │            frontend/ (React + Vite)         │
                         │  Leaflet map · Three.js 3D · Recharts       │
                         │  http://localhost:5173                     │
                         └───────────────────┬──────────────────────---┘
                                              │ REST, /api/v1/* (JSON)
                                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  M0  backend/m0_api   FastAPI orchestrator + job queue + worker          │
│      http://localhost:8000  ·  contracts validated on every response    │
└───┬──────────┬───────────┬────────────┬────────────┬───────────┬────────┘
    │          │           │            │             │           │
    ▼          ▼           ▼            ▼             ▼           ▼
┌───────┐  ┌────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌────────┐
│  M1   │  │  M2    │  │   M3    │  │   M4    │  │   M5    │  │   M6   │
│terrain│─▶│ breach │─▶│ Delft3D │  │DualSPH  │─▶│emulator │─▶│ impact │
│DEM,   │  │params, │  │  FM     │  │  ysics  │  │PCA+GP,  │  │exposure│
│HAND,  │  │hydro-  │  │far-field│  │near-    │  │LOOCV,   │  │overlay,│
│Manning│  │graphs, │  │offline  │  │field    │  │Monte    │  │warning │
│n, POIs│  │cascades│  │runs     │  │offline  │  │Carlo,   │  │table,  │
│       │  │        │  │(offline)│  │runs     │  │fallback │  │exports │
└───────┘  └────────┘  └─────────┘  └─────────┘  └─────────┘  └────────┘
                              │            │
                              └─────┬──────┘
                                    ▼
                       backend/campaign.py runs the whole
                       designed scenario set through M3/M4
                       to build the M5 training cache

                       ┌─────────┐
                       │   M7    │  backend/m7_gee — offline Earth Engine fetch
                       │  GEE    │  (lake area, rainfall, event imagery),
                       │         │  cached to data/<site>/gee/, screenshot fallback
                       └─────────┘
```

M3 (Delft3D FM) and M4 (DualSPHysics) write results to the **identical schema**
(`docs/handoff_contract.md` §4.4) so a Delft3D-vs-SPH comparison is a straight diff, not a
translation. M1–M7 talk to each other only through the files/functions/endpoints the contract
defines — never by reaching into another module's internals (CLAUDE.md rule 1).

Everything runs on `localhost`. No cloud services, no managed database, no auth (CLAUDE.md rule
11) — Earth Engine (M7) is the one external service, and only for offline data prep, with a local
cache and screenshot fallback if it's unreachable.

## Stack

- **Backend:** Python 3.11+, FastAPI, Pydantic v2, SQLite, numpy/scipy/scikit-learn, GDAL,
  rasterio, rioxarray, geopandas, shapely, richdem, simplekml, pytest.
- **M3** (D-Flow FM case generation): hydrolib-core 1.4.0 + meshkernel 8.3.0, read back with
  dfm_tools 0.47.0 / xugrid.
- **Frontend:** React + Vite, Leaflet, Three.js, Recharts, Playwright for visual tests.
- **Simulators** (not part of this repo, installed separately — see `docs/dflowfm_kernel_build.md`):
  Delft3D FM / D-Flow FM 1.2.184 (DIMRset 2026.01), run from WSL; DualSPHysics v5.4.3.

## Setup

### 1. Backend environment

```bash
conda env create -f environment.yml && conda activate sih26
```

If conda isn't available, `requirements.txt` is a pip-only subset covering `backend/shared`, the
mocked API, M5, and M3's pinned Delft3D toolchain (no GDAL/geopandas/richdem — those need conda
or system packages):

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 2. Frontend

```bash
cd frontend && npm install
```

(`frontend/package.json` names `pnpm` as its package manager and also ships a
`package-lock.json`; either `npm install` or `pnpm install` works — the scripts below use `npm`.)

### 3. Secrets

```bash
cp .env.example .env
```

Then fill in only what you actually need — see the comments in `.env.example`. Nothing in `.env`
is required to run the mocked API + frontend demo; `OPENTOPOGRAPHY_API_KEY` is only needed to
fetch new DEM candidates (M1), and the `GEE_*` variables only for live Earth Engine
lake-area/rainfall/imagery fetches (M7) — `earthengine authenticate` (personal OAuth) plus
`GEE_PROJECT` is the path that's actually been exercised so far; see the note in the file. `.env`
is gitignored — never commit it (CLAUDE.md rule 12).

### 4. Simulators (optional — only for real M3/M4 runs)

Real Delft3D FM and DualSPHysics runs need their solvers installed separately (not in this repo,
not needed for the mocked API/frontend demo): see `docs/dflowfm_kernel_build.md` for D-Flow FM
(built in WSL) and CLAUDE.md "Simulation tools" for DualSPHysics binary locations and the
`DSPH_BIN_DIR` environment variable.

## Running it

### One command (starts API + worker + frontend)

```bash
# Linux/WSL
./scripts/start.sh

# Windows PowerShell
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
```

This starts, all backgrounded with logs under `logs/`:
- the API (`uvicorn backend.m0_api.main:app --reload --port 8000`)
- the job worker (`python -m backend.m0_api.worker`) — a separate process that advances
  onboarding/campaign/recheck jobs (CLAUDE.md rule 14: long-running work is never done inline in
  the API request)
- the frontend dev server (`npm run dev`, Vite, default `http://localhost:5173`)

It auto-detects a `conda activate sih26` environment or a local `.venv`, copies `.env.example` to
`.env` on first run if missing, and installs `frontend/node_modules` on first run if missing.
Ctrl+C stops all three. Any detached solver run the worker had already launched keeps running in
the background and is picked back up the next time the worker starts (CLAUDE.md rule 14).

### Manually, one at a time

```bash
uvicorn backend.m0_api.main:app --reload --port 8000   # API
python -m backend.m0_api.worker                        # job worker (separate terminal)
cd frontend && npm run dev                              # frontend (separate terminal)
```

### Tests

```bash
pytest -q                    # backend, mirrors backend/ under tests/
cd frontend && npm run test:visual   # Playwright visual regression suite
```

## How to run the demo

Open `http://localhost:5173` after `./scripts/start.sh` and pick the **Teesta** site — it's the
only site currently wired end to end. From there:

- The 3D view is built from a real D-Flow FM run's output (not a mock), including a breach
  location marker placed from the real terrain.
- The Monitoring page pulls real (cached, or live if you've set up Earth Engine) South Lhonak
  lake-area and rainfall time series and the latest observed lake outline.
- Most other endpoints (`/flood/query`, `/impact/{query_id}`, exports, validation, compare) are
  still mocked — they serve the example JSON in `contracts/examples/` so the UI and downstream
  consumers can be built and tested against a stable shape before the real M1–M6 pipeline is
  wired end to end (`backend/m0_api/main.py`'s own docstring is the up-to-date source of truth for
  what's real vs mocked at any given time). Set `VITE_USE_MOCKS=true` in `frontend/.env.local` to
  force the frontend's own mock layer instead of hitting the API at all.

## Preview mode (design/target-state-preview branch only)

`design/target-state-preview` is a separate, never-merged-to-main branch that shows what every
frontend screen looks like once the ten open workstreams (real pipeline data, automated D-Flow
FM/DualSPHysics, the emulator wired in, real GEE, historical validation, finished impact/loss
numbers, and the frontend actually connected to that data) are done. It does this without any of
that being real yet, by adding a third frontend data source next to the live API and
`VITE_USE_MOCKS`: set `VITE_DATA_MODE=preview` and every screen reads schema-valid fixture JSON
from `frontend/src/data/preview/*.json` instead.

This is illustrative, not a forecast of real numbers, and the UI says so everywhere:

- A persistent banner reads "TARGET-STATE PREVIEW — illustrative values, not model output" on
  every screen.
- Every map, chart and 3D view carries a diagonal "PREVIEW" watermark.
- Every fixture's `provenance.source` (or `x_preview_provenance.source` where the schema has no
  provenance field) is `"fixture:preview"`, and every fixture carries a `preview_illustrative`
  caveat.
- The few real numbers used (e.g. the frozen `teesta_pilot_s001` POI results from
  `docs/m3_spec.md`, or the real `docs/data_sources.md` source citations on Teesta III's existing
  dam) are labelled "frozen pilot" or cite their real `src_NNN`, and are never presented as a
  validated live result.
- Exports are stamped `..._PREVIEW.<ext>` in both filename and file metadata.

Fixtures still have to be real contract payloads — `tests/frontend/test_preview_fixtures.py`
validates every one of them against its `contracts/schemas/*.schema.json` with the same validator
the backend uses on live responses (`backend/m0_api/schemas.validate`), and checks the honesty
stamps above. A few screens need fields the current contract doesn't define yet (terrain vertical
datum/resolution, run mesh-cell-count/disk-usage, population split by arrival band); those are
marked `x_preview_*` as proposed contract additions, not silent contract changes — `contracts/` on
this branch is unmodified.

Components never hard-code preview data themselves; they read it through the same
`frontend/src/data/source.ts` seam as the live API, so turning this off (or eventually pointing it
at a real backend) is a config change, not a code change.

### Onboarding a new site

1. Copy `sites/template.yaml` to `sites/<site_id>.yaml` and fill in every `{value, unit, source,
   status}` field, citing a `src_NNN` entry from `docs/data_sources.md` (add a new entry there
   first if the source isn't listed yet). Leave anything you don't have real data for as
   `status: placeholder` — don't guess (CLAUDE.md rule 3).
2. `backend.shared.site_config.load_site_config(site_id)` validates the file (schema in
   `docs/handoff_contract.md` §3) and rejects unknown/missing fields.
3. `POST /api/v1/sites` with the config as JSON (`docs/handoff_contract.md` §5.2) queues an
   onboarding job; `GET /api/v1/jobs/{job_id}` polls its progress. Today only the job bookkeeping
   and parts of the M1/M2 stages are real — see `backend/m0_api/main.py`'s module docstring for
   the current real-vs-mocked line, and `backend/m0_api/mocks.KNOWN_SITE_IDS` for which sites the
   mocked read endpoints will actually recognise.
4. To train a real emulator for the site you also need a designed scenario set run through M3/M4
   (`backend/campaign.py`) — a real solver install, and it's a genuinely long offline job, not
   something to run casually from a Claude session (CLAUDE.md rule 14).

## Known limitations

State these honestly wherever results are shown, not just here:

- Breach equations are calibrated on man-made embankment dams; moraine dams (like South Lhonak)
  are an extrapolation, and the equations are not recommended for concrete dams at all — those use
  imposed ranges from the site config instead.
- Failure time is poorly predicted by every method; it's treated as a scenario variable with a
  deliberately wide range, not a single number.
- The hydraulic models are clear-water; real Himalayan GLOF/dam-break events are debris- and
  sediment-laden, which this tool does not simulate.
- Rishi Ganga 2021 was a rock-ice avalanche / mass flow, not a dam breach — it needs its own
  scenario approach and has no site config yet.
- Most API endpoints beyond the Teesta 3D view and monitoring page still serve mocked
  `contracts/examples/` data, not a real computed result — see "How to run the demo" above.
- OSM building/road coverage is sparse in parts of the demo valleys; impact/loss numbers inherit
  that sparsity and should be read as order-of-magnitude, not a precise count.

## Data sources and licences

Every fact used in a site config or exposure input cites a `src_NNN` entry in
[`docs/data_sources.md`](docs/data_sources.md) — that file is the authoritative list, with full
citations, DOIs, and what each source feeds. The main datasets and their licences:

| Data | Source | Licence |
|---|---|---|
| Terrain (DEM) | SRTM GL1 (NASA JPL) or Copernicus DEM GLO-30 (ESA/Airbus), via OpenTopography | Public domain (SRTM) / open, attribution requested (Copernicus DEM) — see `docs/data_sources.md` src_033/src_034 |
| Land cover (Manning's n) | ESA WorldCover 10 m v200 | CC BY 4.0 |
| Population | WorldPop 2020 India, 1 km, UN-adjusted | CC BY 4.0 |
| Buildings, roads, facilities | OpenStreetMap extract | Open Database License (ODbL) — attribution required, see [openstreetmap.org/copyright](https://www.openstreetmap.org/copyright) |
| Damage curves & asset values | JRC global flood depth-damage functions (Huizinga et al. 2017) | See the JRC data catalogue entry (doi: 10.2760/16510) |
| Satellite imagery, lake area, rainfall | Sentinel-1/2, CHIRPS, GPM IMERG via Google Earth Engine | Per-dataset Earth Engine catalogue licence; access requires an Earth Engine account |
| River network | HydroBASINS level 12 (HydroSHEDS/WWF) | See HydroSHEDS terms of use |

This project's own code has no LICENSE file yet — it's an SIH26 hackathon submission; treat it as
all-rights-reserved to the team until the team adds one.

## Non-negotiable project rules (summary)

The full list is in `CLAUDE.md`. The ones that matter most when contributing:

1. `docs/handoff_contract.md` + `contracts/` define all data — never change the contract silently.
2. Every module runs end-to-end on synthetic data with pytest tests before real data exists.
3. Never invent site data, dam specs, event facts, coefficients, or confidence numbers — missing
   facts stay `status: placeholder` and propagate `has_placeholders: true`.
4. Breach equations come only from `docs/Equations.md`.
5. SI units everywhere in the backend and API; formatting is the frontend's job.
6. t0 = start of the most upstream breach; every time is seconds since t0.
7. Compute in the site's UTM zone; everything sent to the frontend is EPSG:4326, lon/lat.
8. Localhost only — no cloud services, no managed DB, no auth. Secrets live in `.env`, gitignored,
   never logged or committed.
