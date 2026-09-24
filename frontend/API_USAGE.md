# Frontend data and API usage (as built)

This lists every place the frontend fetches, stores, generates, mocks or hard-codes data. File
references are relative to `frontend/`.

> **Line numbers.** Most files are minified, so one physical line can hold a whole component.
> `app/sentriq/app.tsx:48` is the entire dashboard/simulation view, for example. Search for the
> quoted identifier or string on that line.

## 0. Summary

- The frontend **does not call the project backend at all**. None of the 22 endpoints in
  `docs/handoff_contract.md` §5 (`http://localhost:8000/api/v1/...`) is used anywhere.
- All results come from three places: (a) **static JSON files in `public/data/`**, pre-computed
  by a browser toy solver; (b) **that same solver running in a Web Worker** (`public/model-worker.js`);
  and (c) **linear interpolation** between the cached runs.
- The only server endpoint is **`/api/records`**, a Cloudflare Worker route backed by D1 (SQLite) and
  R2 (object storage). It requires ChatGPT-hosted-app auth headers. Its only job is to save and load runs.
- Exposure (people, buildings) is **synthetic by default**, generated in code.
- There is **one site only: Tehri / Bhagirathi**. Neither project demo site (Teesta, Rishi Ganga) appears.

---

## 1. Core data types (`lib/model.ts:1-4`, `lib/sentriq.ts:2-3`)

```ts
type Grid = {                       // lib/model.ts:1
  name: string; source: string;
  nx: number; ny: number;           // columns, rows
  west: number; east: number; north: number; south: number;   // degrees, EPSG:4326
  dx: number; dy: number;           // metres per cell (flat-earth approximation)
  z: number[];                      // nx*ny elevations (m), row-major from the NORTH-west corner
  sourceIndex: number;              // flat cell index of the inflow / dam cell
  hillshade?: string;               // URL of a relief image
};
type Params = {                     // lib/model.ts:2
  head: number;        // m
  width: number;       // m   breach width
  formation: number;   // MINUTES
  duration: number;    // MINUTES simulated
  roughness: number;   // Manning's n
  mode: 'breach' | 'release';
  release: number;     // m³/s per gate
  volume: number;      // MCM (10^6 m³) cap
  sourceIndex: number;
  gates?: number; ramp?: number /* MINUTES */;
  hydrograph?: { time: number /* MINUTES */; flow: number /* m³/s */ }[];
};
type Frame = { time /* min */; depth: number[]; velocity?: number[]; area /* km² */;
               maxDepth /* m */; volume /* m³ */; inflow /* m³/s */ };
type Result = {                     // lib/model.ts:4
  frames: Frame[];                  // always 25 (t = 0 … duration, step duration/24)
  maxDepth: number[];               // m, nx*ny
  maxVelocity?: number[];           // m/s, nx*ny
  arrival: number[];                // MINUTES, -1 = never ≥ 0.3 m
  hydrograph: { time /* min */; flow /* m³/s */ }[];
  massError: number;                // %
  inflowVolume: number; outflowVolume: number;   // m³
  params: Params; grid: Grid; runtime: number /* s */; peakFlow?: number /* m³/s */;
  engine?: string; createdAt?: string; name?: string; severity?: number; interpolated?: boolean;
};
type Scenario = Result & { id: string; severity: number; engine: string; createdAt: string;
                           validation: string; interpolated?: boolean };   // lib/sentriq.ts:2
type Exposure = { name: string; lon: number; lat: number; population: number; type: string;
                  buildings?: number; area_ha?: number };                  // lib/sentriq.ts:3
```

---

## 2. Fetched data

| # | Where | Request | What it is | Response shape |
|---|---|---|---|---|
| F1 | `app/sentriq/app.tsx:26` | `GET /data/tehri-grid.json` | The only DEM: Tehri/Bhagirathi, 128×128 cells, ~264 m | `Grid`. Values: `name "Tehri · Bhagirathi"`, `source "Mapzen Terrain Tiles / AWS Open Data; SRTM-derived regional terrain"`, bounds W 78.3984375, E 78.75, S 30.145127, N 30.448674, `dx 263.991`, `dy 263.991`, `z` 16 384 values (489.01–2631.37 m), `sourceIndex 4510` (col 30, row 35 ≈ 78.482 E, 30.364 N), `hillshade "/data/tehri-relief.webp"` |
| F2 | `app/sentriq/app.tsx:26` | `GET /data/scenario-library.json` | The "scenario library": 4 pre-computed toy-solver runs | `{ site, version: 1, parameter: "breach width = severity × 2.4 m; all other parameters fixed", scenarios: CompactScenario[] }` (see below) |
| F3 | `app/sentriq/app.tsx:28` | `GET /api/records` | List of the user's saved runs and sites | `{ records: [{ id, kind: 'run'\|'site', name, created_at, site, engine, severity, params, validation }] }`. On `401` the badge shows "Sign-in required", on another error "Storage unavailable", and on a network failure "Offline". |
| F4 | `app/sentriq/app.tsx:39` | `GET /api/records?id=<uuid>` | One saved record's full payload | The raw object that was POSTed as `data`. For a run that is `Result & {severity}`, and for a site it is `{ grid: Grid, params: Params }`. |
| F5 | `lib/sentriq.ts:13` (`saveRecord`) | `POST /api/records` body `{kind, name, data}` | Save a run (`app.tsx:38`) or a new site (`app.tsx:42`) | `201 { id, kind, name, created_at, site, engine, severity, params, validation: 'Unvalidated' }`, or `{ error }` with 400/401/403/413/503 |
| F6 | `app/sentriq/app.tsx:34` | `new Worker('/model-worker.js')` | Toy hydraulic solver (§4) | messages `{type:'progress', value 0–100}`, `{type:'result', result: Result}`, `{type:'error', message}` |
| F7 | `app/sentriq/app.tsx:41` | Service worker `/offline-sw.js` + `postMessage({type:'CACHE_URLS', urls})` | Offline cache of `/`, F1, F2, `/data/tehri-relief.webp`, `/model-worker.js` and loaded JS/CSS | reply `{ ok: true }` or `{ ok: false, error }` |
| F8 | `terrain-map.tsx:15`, `landing.tsx:15` | `<img src={grid.hillshade}>` | Hillshade image `/data/tehri-relief.webp` | image |
| F9 | `app.tsx:55`, `app.tsx:56` | `<a href download>` | `/data/modelling-toolkit.zip` (Python helpers) and `/data/provenance.json` | provenance: `{ terrain_url, catalog, attribution, processing, retrieved: "2026-09-22", bounds[4], cellsize_m[2], source_index: 4510 }` |

**CompactScenario** (F2, expanded by `unpack()` in `lib/sentriq.ts:5`). Only cells with depth > 0.0001 m are stored:

```jsonc
{
  "id": "TEH-LI-25",  "name": "Tehri · 25% breach width",  "severity": 25,
  "engine": "Local-inertial screening",  "createdAt": "2026-09-22T12:54:30.620Z",
  "validation": "Unvalidated",
  "params": { "head": 40, "width": 60, "formation": 15, "duration": 60, "roughness": 0.045,
              "mode": "breach", "release": 1800, "volume": 100, "sourceIndex": 4510 },
  "runtime": 2.726, "massError": 3.12e-14, "peakFlow": 25804.19,
  "inflowVolume": 47715622.29, "outflowVolume": 0,
  "indices":     [/* 17 flat cell indices */],
  "maxDepth":    [/* 17 values, m */],
  "maxVelocity": [/* 17 values, m/s */],
  "arrival":     [/* 17 values, minutes */],
  "hydrograph":  [{ "time": 0, "flow": 0 }, { "time": 2.5, "flow": 4272.03 }, /* 25 rows */],
  "frames":      [{ "time": 0, "depth": [/*17*/], "velocity": [/*17*/], "area": 0,
                    "maxDepth": 0, "volume": 0, "inflow": 0 }, /* 25 frames */]
}
```

Generated by `scripts/build-scenario-cache.cjs` with base params `{head 40, width 120, formation 15,
duration 60, roughness .045, volume 100}` and `width = severity × 2.4`.

**Unused data file:** `public/data/baseline.json` (1.9 MB, the full 50% run) is written by
`scripts/build-scenario-cache.cjs` and `scripts/check-model.cjs`, but the app never reads it.
`public/data/terrain-source.png` is read only by `scripts/prepare-terrain.py`.

---

## 3. Server route `/api/records` (`app/api/records/route.ts`)

- It runs on Cloudflare Workers (`env.DB` = D1, `env.BUCKET` = R2; bindings are declared in `.openai/hosting.json`
  and `vite.config.ts`).
- Auth: `getChatGPTUser()` (`app/chatgpt-auth.ts:21`) reads the headers `oai-authenticated-user-id`,
  `oai-authenticated-user-email` and `oai-authenticated-user-full-name`. In local dev,
  `build/sites-vite-plugin.ts:32` (`mockAuth`) injects fake headers.
- **GET** returns up to 100 rows `ORDER BY created_at DESC`, or `?id=` streams the R2 object.
- **POST** validates `kind ∈ {run, site}`, `name` 1–120 chars and a body ≤ 10 MB. A run needs
  `data.params`, `data.grid` and `data.maxDepth[]`. A site needs `data.grid` and `data.params`. It writes R2
  key `<userId>/<uuid>.json`, then a D1 row.
- D1 table (`db/schema.ts`, `drizzle/0000_silky_zemo.sql`):
  `records(id PK, owner, kind, name, metadata JSON-text, object_key, created_at)`.
  The metadata is `{ site: data.grid.name, engine: data.engine ?? 'Local-inertial screening',
  severity: data.severity ?? null, params: data.params, validation: 'Unvalidated' }` (hard-coded).
- `examples/d1/…` is starter-template code and is not wired in.

---

## 4. In-browser solver (`public/model-worker.js`)

Input `{ grid: Grid, params: Params }`. Output `Result` without `engine/createdAt/name`. The app adds
`engine: 'Fast Screening'` and `name: grid.name + ' · custom scenario'` (`app.tsx:34`).

Hard-coded physics constants:

| Line | Constant | Meaning |
|---|---|---|
| 5 | `g = 9.81` | gravity |
| 8 | `dtMax = 2` s, `snap = total/24` | max timestep, 25 output frames |
| 11 | `0.22·min(dx,dy)/√(g·maxH)` | CFL-type timestep |
| 12 | `1.7 · width · head^1.5` | breach discharge (broad-crested weir form). It is **not taken from `docs/equations.md`**. |
| 12 | linear rise over `max(60 s, formation)`, recession `exp(−(t−formation)/max(300 s, 2·formation))` | illustrative hydrograph shape |
| 17–18 | `H > 0.001` m | face flow depth threshold |
| 19 | south row: `qy = √g · h^1.5` | free-outflow boundary. The other three sides are closed. |
| 23 | `0.3` m | wet threshold for velocity and **arrival** |
| 13 | CSV hydrograph | replaces the formula. Past the last sample the flow **holds at the last value**. |

---

## 5. Browser storage

| Where | Store | Key | Shape |
|---|---|---|---|
| `lib/sentriq.ts:14` (`localStore`) | IndexedDB `sentriq-offline` v1, object store `data` | `'prepared'` | `{ grid: Grid, cache: Scenario[] (already expanded), assets: Exposure[] }`. It is written by `prepareOffline` (`app.tsx:41`) and read as the fallback when F1/F2 fail (`app.tsx:26`). |
| `public/offline-sw.js:1` | Cache Storage `sentriq-offline-v1` | request URLs | Network-first. Falls back to cache, and to `/` for navigations. Skips `/api/`, `signin`, `signout`, `callback`. |

There is no `localStorage` or `sessionStorage`.

---

## 6. User uploads (`app.tsx:36-37`, hidden `<input accept=".asc,.csv,.json,.geojson">`)

| Kind | Parser | Accepted shape | Limits |
|---|---|---|---|
| `dem` | `parseASC` (`lib/model.ts:9`) | ESRI ASCII grid **in WGS84 degrees** (`ncols nrows xllcorner/xllcenter yllcorner/yllcenter cellsize [nodata_value]` + values) | 3 ≤ cells ≤ 60 000, cellsize ≤ 0.1°, no NoData values, file ≤ 25 MB. `source` is set to `'User-uploaded DEM · WGS84'`. `sourceIndex` is the centre cell until the dam lat/lon is applied. |
| `hydro` | `parseHydrograph` (`lib/sentriq.ts:9`) | CSV header exactly `time_min,flow_m3s` | 2–10 000 rows, first time = 0, strictly increasing, non-negative |
| `exposure` | inline (`app.tsx:37`) | GeoJSON FeatureCollection of `Point`s with `properties.name` (string), `population` ≥ 0, optional `buildings`, `area_ha` ≥ 0, `type` (default `'Settlement'`) | 1–20 000 features, all inside the DEM |
| `SPH` / `Delft3D` | `parseResult` (`lib/model.ts:11`) | GeoJSON FeatureCollection of single-ring `Polygon`s with numeric `properties.depth_m` ≥ 0, inside the DEM bounds | ≤ 100 000 features. Returns `{ fc, area (km², for depth ≥ 0.3), max, count }`. |
| `observed` | `parseResult` with `depth_m` forced to 1 | polygons as above | 1–20 000 features |

---

## 7. Generated / mocked data

| Where | What | Details |
|---|---|---|
| `lib/sentriq.ts:8` `demoExposure(r)` | **Synthetic exposure inventory**, called with the 100% scenario (`app.tsx:26`, `setAssets(demoExposure(list[3]))`) | Six points placed on the wet cells at fractions `[.12,.3,.45,.6,.77,.9]` of the wet-cell list. Names `Demo settlement A`, `Demo settlement B`, `Demo health centre`, `Demo cropland A`, `Demo school`, `Demo settlement C`. **population `[240,480,65,0,180,550]`**, **buildings `[32,58,1,0,1,64]`**, **area_ha 8** (cropland only). The UI labels these "demo people". |
| `lib/sentriq.ts:6` `interpolate(cache, severity)` | "Rapid query" result | Linear blend of the two neighbouring cached scenarios for `maxDepth`, `maxVelocity`, per-frame depth, velocity, volume and inflow, `hydrograph.flow`, `peakFlow`, the volumes and `params.width`. `arrival` is blended only where both neighbours are wet, and is `-1` otherwise. The id is `QUERY-<severity>`. |
| `app.tsx:29` `rapid()` | "Query compute time" (ms) | `performance.now()` around `interpolate()` only, then shown as `queryMs` |
| `lib/sentriq.ts:7` `stats(r)` | Headline metrics | `area` = (#cells with maxDepth ≥ 0.3) × dx × dy / 1e6 km². `depth` = max of maxDepth. `velocity` = max of maxVelocity. `peak` = `peakFlow`. |
| `app.tsx:31` `impacts` | Per-asset impact | Depth and arrival at the asset's cell. ETA range = min–max of the lower and upper neighbour arrival. Risk: **≥3 m High, ≥1 m Moderate, ≥0.3 m Low**, else Outside. |
| `app.tsx:42` `generateSite()` | New-site "library" | 4 worker runs at `width = severity/100 × params.width` for severities 25/50/75/100. The ids are `LOCAL-<uuid>`. |
| `lib/sentriq.ts:10` `metadata(r)` | Export metadata | `{ product:'Sentriq', scenario, engine ?? 'Fast Screening', created_at, parameters, confidence:'Unvalidated; no calibrated probability', method, provenance: grid.source, crs:'EPSG:4326', wet_threshold_m:.3, grid_resolution_m:[dx,dy], operational_use:false }` |
| `lib/gee.ts:2` `geeScript()` | Generated Earth Engine JS (download) | Sentinel-1 `COPERNICUS/S1_GRD`, IW, VV, **DESCENDING only**, 14-day windows, most common relative orbit, 30 m focal median. Flood = `ratio > threshold AND afterPower < 0.0631 (≈ −12 dB) AND slope < 5° AND NOT JRC GSW seasonality ≥ 10`, connected pixels ≥ 8. Exports `Sentriq_observed_flood` GeoJSON to Drive. |
| `app/sph-lab.tsx:5-10` | SPH toy | 17×12 = 204 particles, h = 0.11, dt = 0.0008, 28 substeps/frame, stiffness 400, ρ₀ = 1000, 3.4 × 1.1 m tank, stops at t = 5 s. It is not connected to any result. |

---

## 8. Hard-coded values by file

### `lib/model.ts`
- `:5` `defaults = { head 40, width 120, formation 15, duration 60, roughness 0.045, mode 'breach', release 1800, volume 100, sourceIndex 0 }`
- `:7` export wet threshold `0.3` m. Features carry `model:'local-inertial prototype'`.
- `:9` DEM limit 60 000 cells. `111320` m/degree flat-earth conversion (also `:11`).

### `app/sentriq/app.tsx`
- `:20` nav items (9). `:21` page titles.
- `:23` initial state: `severity 50`, `frame 24`, `mapMode '3d'`, `siteLat 30.37`, `siteLon 78.48`,
  `before '2026-08-01'`, `after '2026-09-01'`, backscatter `ratio 1.25`.
- `:26` the initial result is the scenario with `severity === 50`. The offline fallback uses `cache[1]`.
- `:27` playback: 24 steps at 260 ms.
- `:37` upload limits: 25 MB, 20 000 features.
- `:42` severities `[25,50,75,100]`.
- `:48` input ranges: head 5–120 m, width 5–500 m, formation 1–60 min, release 0–30 000 m³/s, gates 1–20,
  ramp 0–60 min, duration 10–180 min, n 0.015–0.15, volume 1–500 MCM. Fallback `duration ?? 60`.
  Time label `T + duration × frame / 24`.
- `:49` library matrix nodes fixed at `[25,50,75,100]`. The library table "Engine" column is the **literal `'Fast Screening'`**.
- `:50` comparison metrics "Arrival-time MAE" and "Velocity MAE" are the literal `'—'`.
- `:55` site onboarding: width 10–500 m. Hydrograph template CSV `0,0 / 10,1800 / 30,1200 / 60,0`.
- `:56` dataset registry (six rows): URLs for AWS terrain tiles, THDC Tehri page and GEE S1 catalogue. States `LOADED / REFERENCE / DEMO / EXTERNAL / MISSING`.
- `:57` six-step architecture text. `:58` methodology dialog text (states "four real local-inertial screening runs").
- Sidebar "SIH 2026", "PS 26161 · NTRO", "Research prototype". Top-bar avatar text `SQ`.

### `app/sentriq/landing.tsx`
- `:9` "The prepared Tehri domain uses a 128 × 128 terrain grid."
- `:12` hero label "Tehri · Bhagirathi catchment / Uttarakhand, India". Query tile **`'4'` "cached runs"** (literal).
  "Illustrative breach width · 25–100% of 240 m".
- `:13` mission strip "SIH 2026 / PROBLEM STATEMENT 26161", "NTRO / DISASTER MANAGEMENT", "HADR".
- `:15` "78.398° E — 78.750° E / 30.145° N — 30.449° N" and "128 × 128 cells / ~264 m" (literals, shown for any grid).
- `:17` cached nodes `[25,50,75,100]`, "Four breach-width scenarios", "Under 2 seconds is the interaction target".
  Bracket fallback `?? 25` / `?? 50`.
- `:18` demo assets list (from `demoExposure`), "{population} demo people".

### `app/terrain-map.tsx`
- `:7` initial zoom 2 and pan `{x:.48, y:.1}` when a hillshade exists.
- `:9` colour classes: depth `[20,10,3,1]` m, velocity `[5,2,1,.5]` m/s, arrival `[60,30,15,5]` min. Wet threshold 0.3.
- `:18` inflow pin label: `'Tehri Dam reach'` when `grid.name` starts with `Tehri`.
- `:19` **place labels at fixed screen percentages**, not coordinates: `NEW TEHRI` (11%, 25%), `Bhagirathi River` (28%, 45%),
  `KOTESHWAR REACH` (18%, 62%), `UTTARAKHAND`.
- `:27` legend labels `0.3 / 1 / 3 / 10 / 20+ m`, `0 / .5 / 1 / 2 / 5+ m/s`, `0 / 5 / 15 / 30 / 60+ min`.
- `:28` attribution text `'Mapzen / AWS Open Data'`.

### `app/sentriq/terrain-3d.tsx` and `terrain-canvas.tsx`
- The crop window is `sourceIndex − 25 … + 35` columns and `− 19 … + 55` rows around **`grid.sourceIndex`**.
- Vertical exaggeration: relief is scaled to 3.1 world units. **Water is drawn at `z + depth + 8` m.**
- Contour darkening every 120 m (3D) or 130 m (canvas).
- Camera `(9, 11.5, 11)`, FOV 39, distance 8–25.

### `app/api/records/route.ts`
- 10 MB body limit, name ≤ 120 chars, `LIMIT 100`, `validation: 'Unvalidated'`, and engine default `'Local-inertial screening'`.

---

## 9. Exports (`lib/sentriq.ts:12`, triggered from `app.tsx:40` and `:54`)

| Format | File | Content |
|---|---|---|
| `shp` | `sentriq-shapefile.zip` | `@mapbox/shp-write` polygons (`inundation`) + `scenario-metadata.json` |
| `kml` | `sentriq-inundation.kml` | Document `ExtendedData` = metadata, one Placemark per wet cell with `depth_m` and `arrival_min` |
| `geojson` | `sentriq-inundation.geojson` | FeatureCollection, one square Polygon per cell with maxDepth ≥ 0.3 m. Properties: `depth_m` (3 dp), `arrival_min` (2 dp or null), `model`, `source`, `scenario`, `timestamp`, `confidence:'Unvalidated'`. Top-level `metadata`. |
| `report` | `sentriq-simulation-report.html` | Area (km²), max depth, peak cell velocity, audit metadata, interpretation text |
| `hydrograph` | `sentriq-hydrograph.csv` | `time_min,flow_m3s` |
| `json` | `sentriq-scenario.json` | the whole `Result` + `metadata` |
| `raster` | `sentriq-depth.asc` | Implemented but **not offered in the UI**. See issues. |
| (monitoring) | `sentriq-earth-engine.js` | `geeScript()` output |
| (data) | `exposure-template.geojson` | current `assets` as Point features |
| (sites) | `hydrograph-template.csv` | four-row template |

---

## 10. ⚠️ Hard-coded numbers that look like real results

Every number below is either a literal or comes from the in-browser toy solver running **hypothetical**
parameters (head 40 m, breach 60–240 m, 100 MCM cap). The UI shows them next to the name "Tehri". None comes
from Tehri dam specifications, observations, Delft3D or DualSPHysics.

| Value | Where | Why it could mislead |
|---|---|---|
| Flood extent **1.19 / 2.37 / 3.28 / 3.90 km²** (25/50/75/100%). **2.37 km²** is the default shown. | computed from F2, displayed on landing `:12`, `:17` and dashboard `:48` | Looks like a Tehri inundation area. In fact 17–56 cells pond next to the source, with `outflowVolume = 0` in every run, and water never reaches the domain edge. |
| Max depth **71.8 / 87.5 / 90.8 / 93.2 m** | F2, dashboard, report | Deep "local ponding" artefacts of a ~264 m grid (the README acknowledges them). |
| Peak cell velocity **19.2 / 21.8 / 30.2 / 37.6 m/s** | F2 | Physically extreme values from a coarse-grid approximation. |
| Peak flow **25 804 / 51 608 / 77 413 / 103 217 m³/s** | F2 `peakFlow`, hydrograph CSV | Presented alongside "Tehri Dam". It comes from the illustrative weir formula with invented inputs. |
| Inflow volume **47.7 / 95.4 / 100 / 100 MCM** | F2 | The cap of 100 MCM is an arbitrary default (`lib/model.ts:5`). |
| Arrival times **0.33–59.7 min** (cached runs), shown as "First wetting a–b min" ranges | F2 → impact list, dashboard | They look like warning lead times. The UI does say "not an evacuation deadline". |
| Mass-balance error **~1e-13 %** | dialog `app.tsx:58` | This is a numerical check only. The dialog says so. |
| Runtime **2.2–2.7 s** | F2 `runtime` | Stored from one machine at build time. |
| Populations **240, 480, 65, 0, 180, 550** and buildings **32, 58, 1, 0, 1, 64**, cropland **8 ha** | `lib/sentriq.ts:8` | Realistic-looking counts. They are labelled "demo" but still sum into "Population exposed" and "Buildings affected". |
| **"4 cached runs"** | `landing.tsx:12` | A literal, not `cache.length`. It is wrong after a user site is loaded or a saved run is opened. |
| **"Query compute time N ms"** | `app.tsx:29` | It measures interpolation only (the text says so), but reads like an end-to-end latency. |
| **"25–100% of 240 m"**, **"128 × 128 cells / ~264 m"**, the lat/lon ranges | `landing.tsx:12`, `:9`, `:15` | Correct for the Tehri grid only, and shown whatever grid is active. |
| Default dam location **30.37 N, 78.48 E** | `app.tsx:23` | Pre-filled for new sites. Actual source cell centre is 30.364 N, 78.482 E. |
| Backscatter ratio **1.25**, dark-water **0.0631**, **8** connected pixels, **slope < 5°**, **GSW ≥ 10** | `app.tsx:23`, `lib/gee.ts:27-28` | Thresholds with no cited source. |

---

## 11. Broken or inconsistent

### A. Conflicts with the project contract (`CLAUDE.md`, `docs/handoff_contract.md`)
1. **No backend integration.** Contract §5 endpoints (`/api/v1/sites`, `/flood/query`, `/jobs`, `/impact`, `/compare`,
   `/validation`, `/export`, `/gee`, `/scene3d`, `/styles`) are never called. The frontend computes everything itself.
2. **Cloud + auth, against rule 11 (localhost only, no cloud, no auth).** `/api/records` needs Cloudflare D1/R2 and
   ChatGPT auth headers. `.openai/hosting.json` holds a hosting project id. The UI has no sign-in link, so outside
   the mock-auth dev plugin the saved-runs panel just reads "Sign-in required".
3. **Wrong sites.** Only Tehri/Bhagirathi exists. Teesta (South Lhonak → Teesta III) and Rishi Ganga are absent, and
   `sites/*.yaml` is never read.
4. **Units (§1.1–1.2).** Time is in **minutes** (`formation`, `duration`, `ramp`, `arrival`, `frames.time`,
   `hydrograph.time`, CSV `time_min`, export `arrival_min`), volume in **MCM**, area in **km²**. The contract requires
   seconds (`_s`), m³ and m². The CSV header should be `t_s,q_m3s`.
5. **CRS (§1.3).** Computation runs on an EPSG:4326 grid with a flat-earth `111320 m/°` conversion, not in UTM
   (32645/32644). DEM upload rejects projected grids outright.
6. **No Estimate / Confidence / Caveat / Provenance objects (§2.2–2.5).** Results are bare numbers with no low/high,
   `kind` or confidence level. Confidence is the free-text string `'Unvalidated'`.
7. **Nodata and thresholds (§1.5).** Arrival uses a `-1` sentinel instead of nodata. There is no `domain_mask`. The
   arrival threshold is 0.3 m, where the contract default `arrival_m` is 0.1. The `.asc` export declares `NODATA_value -9999`
   but writes `0.000` for dry cells.
8. **Styles (§6).** The contract's depth breaks are `[0.3, 0.5, 2, 5]` m and arrival breaks `[900, 1800, 3600, 7200]` s. The map uses
   `[0.3, 1, 3, 10, 20]` m and `[5, 15, 30, 60]` min. `contracts/` (and so `styles.json`) does not exist.
9. **Equation source (rule 4).** The breach discharge `1.7·b·H^1.5` is hard-coded in `public/model-worker.js:12`.
   `docs/equations.md` does not exist in `docs/`.
10. **Stack mismatch.** CLAUDE.md says React + Vite + Leaflet + Recharts + Playwright with `npm run test:visual`.
    The actual stack is Next.js 16 on vinext/Cloudflare, with no Leaflet (a custom canvas map), Recharts installed but unused,
    no Playwright and no `test:visual` script. `frontend/CLAUDE.md` (referenced by the root CLAUDE.md) and
    `frontend/src/content/ui_text.json` (referenced by contract §2.3) do not exist.

### B. Functional bugs
11. **Interpolated arrival paints unreached cells as earliest arrival.** `interpolate()` sets `arrival = -1` where only
    one neighbour is wet, but depth there is still ≥ 0.3 m. In `terrain-map.tsx:9` a `wetMask` bypasses the
    `d < 0` check, so those cells fall through to the 0–5 min colour. The impact list then shows
    "First wetting **Not reached**" next to a non-zero depth.
12. **3D view never shows maximum depth.** `Terrain3D` receives `frame` (default 24, the last frame) and draws
    `frames[frame].depth`, which is final-time depth. For 75% this is 81.0 m against a true max of 90.8 m. The
    2D "Depth" layer uses `maxDepth`, so the two views disagree.
13. **3D ignores a user-picked inflow cell.** The crop window and marker use `grid.sourceIndex`, not
    `params.sourceIndex` (`terrain-3d.tsx:13`, `terrain-canvas.tsx:7`).
14. **"100% severity" means different widths.** Tehri's library uses `severity × 2.4 m` (240 m at 100%).
    `generateSite()` uses `severity/100 × params.width`, and `params.width` is 120 m after the default load, so
    100% becomes 120 m.
15. **Raster export can never succeed for Tehri.** Its cells are 0.002747° × 0.002371°, so the equal-spacing check
    throws. It is also not listed in the export options (`app.tsx:54`), so it is dead code today.
16. **Three different depth colour schemes.** 2D uses 5 classes (`#9df5df…#4456ee`, breaks 1/3/10/20 m). 3D uses 3
    classes (`#72f2d7 / #3dd7e7 / #279ce4`, breaks 3/20 m). The software fallback uses another 3 (`#8cedd6 / #50dce4 / #39a7df`).
    The impact risk uses yet another set (0.3/1/3 m). No single legend is valid across views.
17. **Water is lifted 8 m in 3D** (`z + d + 8`), an undocumented visual offset.
18. **Engine naming.** The same runs are called `'Local-inertial screening'` (F2, API default), `'Fast Screening'` (live
    runs, library table literal, metadata default) and `'local-inertial prototype'` (GeoJSON features). The workspace
    badge tests `result.engine === 'SPH' | 'Delft3D'`, which can never be true because imported outputs never become `result`.
19. **Tehri-only literals on the landing page** (`landing.tsx:9, 12, 15`). Coordinates, grid size, "4 cached runs" and
    "Tehri · Bhagirathi catchment" stay the same after a user site is generated.
20. **Map place labels are not georeferenced.** `NEW TEHRI`, `Bhagirathi River` and `KOTESHWAR REACH` are placed at fixed
    percentages of the map box (`terrain-map.tsx:19`), so their positions are unverified.
21. **Hydrograph CSV that ends above zero** keeps discharging at the last value until the volume cap is reached
    (`model-worker.js:13`).
22. `scripts/check-sentriq.cjs` writes to a hard-coded `/workspace/scratch/91a69a7f16ca/` path and fails on any other
    machine. No package script runs `check-model.cjs` or `check-sentriq.cjs`.
23. The offline fallback assumes at least two cached scenarios (`stored.cache[1]`, `app.tsx:26`).
24. React list keys use `a.name` for exposure rows (`app.tsx:48, 52`, `landing.tsx:18`), so an imported inventory with
    duplicate names will mis-render.

### C. Styling defects
25. `--panel` is used (`.concept-compare>div`, `.architecture-flow svg`) but never defined, so those backgrounds are transparent.
26. `.onboarding-steps button.complete` is applied (`app.tsx:55`) but has no CSS, so completed steps look like pending ones.
27. `.pick-message` still uses the light-theme `#fffdf0f5` / `#5d6745` in the dark UI. It was missed by the dark re-skin.
28. Many 4–7 px font sizes remain (`.scene-caption`, `.brand-s small`, `.map-bottom`, `.dam-pin b`, several `.s-badge`
    overrides). They are unreadable on projectors.
29. Dead light-theme `:root` block (`globals.css:4`) and first-pass light map chrome (`globals.css:12`) that is overridden later on the same line.
30. `Logo` (`app.tsx:60`) and `Brand` (`landing.tsx:22`) are near-duplicate SVGs. The app's `Badge` and `Empty` share names with
    the unused shadcn `badge.tsx` and `empty.tsx`.

### D. Housekeeping and documentation drift
31. The README's exposure schema requires `value_inr` and describes a loss proxy (`value × min(depth/5, 0.8)`). The app
    ignores `value_inr` and says "no monetary loss is claimed".
32. The README example uses `jaldrishti-inundation.geojson`, but the app exports `sentriq-inundation.geojson`.
    `package.json` is named `site-creator-vinext-starter`.
33. The organisation attribution "NTRO" (sidebar and landing mission strip) has no source anywhere in the repo. Verify it.
34. Locale formatting is mixed: numbers use `en-IN`, dates `en-GB`, and the monitoring import time uses the browser default.
35. Repo clutter: a `*:Zone.Identifier` file beside almost every file (Windows download artefacts), `tsconfig.tsbuildinfo`,
    `toolkit/__pycache__/`, and the `examples/d1` starter.
36. Unused code and assets: `exportKML` (`lib/model.ts:8`), `baseline.json`, `next-themes`, `recharts`, most of `components/ui/`,
    and the unused `Landing` props `cache`, `playing`, `pop`.
