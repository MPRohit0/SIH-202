# Frontend data and API usage (as built)

This describes the frontend **as it exists today**: a UI shell with its data source
removed (see `README.md` and `../docs/progress.md` for how it got here and why). File
references are relative to `frontend/`. Most source files are minified — one physical
line can hold a whole component — so line numbers point at very long lines; search for
the quoted identifier.

## 0. Summary

- **Every data need routes through one file, [`src/data/source.ts`](src/data/source.ts).**
  No component calls `fetch()` directly and no component imports a data file. Every
  function in `source.ts` today resolves to `{status: 'awaiting', reason, ...emptyData}`
  — there is no backend to call yet.
- **There is no bundled site data, no in-browser solver, and no cloud/auth backend.**
  The Tehri/Bhagirathi prototype site, its scenario library, `public/model-worker.js`,
  `/api/records` (Cloudflare D1/R2 + ChatGPT auth) and the GEE script generator were all
  removed. See `../docs/progress.md` for the full list, by commit.
- **Every screen is reachable and renders a real, honest empty state**: `<Empty>` panels,
  `nf()` → "—" for unknown numbers, zero counts where zero is correct, and a persistent
  "No site is connected yet" banner. This is not a bug.
- **9 upload/import buttons and 2 offline-caching buttons are visibly present but
  `disabled`**, because the code that would give their result somewhere to go was
  removed along with them. See §3.
- **The SPH particle tank is the one fully working, unmodified piece** of the original
  prototype — it's self-contained and needs no data. It's labelled "Educational
  Explainer" everywhere (nav, title, a panel badge) so it can't be mistaken for project
  output.

---

## 1. Core data types ([`lib/model.ts`](lib/model.ts), [`lib/sentriq.ts`](lib/sentriq.ts))

Unchanged in shape from the original prototype (components still expect these), minus
every function that only the removed solver/exports/cloud code called:

```ts
type Grid = {                       // lib/model.ts
  name: string; source: string;
  nx: number; ny: number;           // columns, rows
  west: number; east: number; north: number; south: number;   // degrees, EPSG:4326
  dx: number; dy: number;           // metres per cell (flat-earth approximation)
  z: number[];                      // nx*ny elevations (m)
  sourceIndex: number;              // flat cell index of the inflow / dam cell
  hillshade?: string;                // URL of a relief image
};
type Params = { head, width, formation, duration, roughness, mode, release, volume,
                sourceIndex, gates?, ramp?, hydrograph? };   // form state; see §4
type Result = { frames, maxDepth, maxVelocity?, arrival, hydrograph, massError,
                 inflowVolume, outflowVolume, params, grid, runtime, peakFlow?,
                 engine?, createdAt?, name?, severity?, interpolated? };
type Scenario = Result & { id, severity, engine, createdAt, validation, interpolated? };
type Exposure = { name, lon, lat, population, type, buildings?, area_ha? };
```

`lib/model.ts` now exports only the types, `defaults: Params` (generic form defaults for
the disabled Physics-run form — not real data) and `pointIndex(grid, lon, lat)` (still
used by `impacts` and, once reachable, site onboarding). `lib/sentriq.ts` exports only
the types, `nf()` (number formatter, `'—'` for non-finite) and `stats(result)` (area/
depth/velocity/peak summary; returns `NaN` for every field when `result` is `null`, so
`nf()` renders `'—'`).

Removed from these two files (each function's only remaining callers were also removed):
`download`, `featureCollection`, `exportKML`, `parseASC`, `parseResult` (`lib/model.ts`);
`unpack`, `interpolate`, `demoExposure`, `parseHydrograph`, `metadata`, `exportResult`,
`saveRecord`, `localStore` (`lib/sentriq.ts`). `lib/gee.ts` was deleted outright.

---

## 2. The data seam — `src/data/source.ts`

| Function | Stands in for (contract §5) | Called from | Wired to a real call site? |
|---|---|---|---|
| `getSite()` | `GET /sites`, `/sites/{id}` | — | Not yet called anywhere |
| `getTerrain()` | site detail / `GET /scene3d/{id}` | `app.tsx` mount effect | Yes — sets `grid` |
| `queryFlood({site_id?, severity?, params?})` | `POST /flood/query`, `GET /flood/{id}` | `rapid()`, `run()` | Yes, but both are gated by preconditions that can't be met yet (`cache.length`, `grid`) |
| `listScenarios()` | *(no contract endpoint — flagged in `source.ts`)* | `app.tsx` mount effect | Yes — sets `cache` |
| `getImpact()` | `GET /impact/{id}` | — | **No.** Impact metrics are still computed client-side from `assets` + `result` (§4) |
| `getCompare(model)` | `GET /compare/{site}` | — | **No.** Compare view still expects client-side GeoJSON import (now disabled, §3) |
| `getObserved()` | `GET /gee/{site}` | — | Not called; `observed` state only ever changed via the now-removed import handler |
| `getStyles()` | `GET /styles` (`contracts/styles.json`) | `app.tsx` mount effect | Yes — passed to `TerrainMap` as `styles` |
| `exportUrl(format)` | `GET /export/{id}?format=` | `exportNow()` | Yes, but gated by `!result` |
| `createSite({name, grid, params})` | `POST /sites` | `generateSite()` | Yes, but gated by `!siteGrid` (DEM upload is disabled) |
| `getJob(jobId)` | `GET /jobs/{id}` | — | Not called; no code currently produces a `jobId` to poll |
| `listSavedRuns()` | *(no contract endpoint — flagged in `source.ts`)* | `loadHistory()` (mount effect) | Yes — sets `saved` |
| `saveRun(kind, name, data)` | *(no contract endpoint)* | `saveRun()` | Yes, but gated by `!result` |

Every function is `async` and currently synchronous-resolves (`Promise.resolve`-equivalent)
to `{status: 'awaiting', reason: '<human-readable reason>', ...}` plus whatever empty
value(s) its caller destructures (`grid: null`, `scenarios: []`, `result: null`, etc.).
**To connect a real backend, replace each function body with a `fetch()` call that
returns the same shape** (or a discriminated union your consuming code switches on) —
nothing outside `source.ts` should need to change.

`getSite`, `getImpact`, `getCompare`, `getObserved` and `getJob` are defined but not yet
called from anywhere — they document the intended integration points named in the plan
this strip followed, not code paths that run today.

---

## 3. What's disabled, and why

Every button below is rendered exactly where it was before, with `disabled` and no
`onClick` (or, for site onboarding's "Generate prepared scenarios", a new
`disabled={!siteGrid}` it didn't have before). None of their underlying parsers or
handlers exist anymore — re-enabling one means deciding where its result should live
(almost certainly a new `source.ts` function), not just restoring the old code.

| Button | View(s) | Why it's disabled |
|---|---|---|
| "Choose a prepared DEM" | Physics-run form; sites onboarding step 2; Data layers | Fed `lib/model.ts`'s `parseASC()` (removed), which only ever fed the removed solver |
| "Import discharge CSV" / "Import discharge time series" (×3) | Physics-run form; sites onboarding step 4; Data layers | Fed `lib/sentriq.ts`'s `parseHydrograph()` (removed); only ever fed the removed solver |
| "Download CSV template" | Sites onboarding step 4 | Companion to the hydrograph import above |
| "Import inventory" / "Import exposure GeoJSON" (×2) | Impact analysis; Data layers | Needs `pointIndex(grid, …)` against a real `grid`, which is always `null` |
| "Import observed polygons" / "Import observed extent" (×2) | Satellite monitoring; Data layers | Needs `lib/model.ts`'s `parseResult(text, grid)` (removed), which dereferences `grid` |
| "Import SPH output" / "Import Delft3D output" | Compare Models | Same as above — needs a real `grid` to validate bounds against |
| "Export current exposure template" | Data layers | Exported the current (always empty) `assets` array via the removed `download()` helper |
| "Download for offline" (Scenario library) / "Prepare offline workspace" (Settings) | Library; Settings | Drove `prepareOffline()` (removed): IndexedDB caching + `public/offline-sw.js`, both deleted |
| "Generate prepared scenarios" | Sites onboarding step 5 | Its only path to a non-null `siteGrid` (DEM upload) is disabled above |

Buttons **not** disabled, because they were pure navigation or local form state with no
removed dependency: "Add new site" / "Import a new DEM / site" (both just `go('sites')`),
the site-name/lat/lon/breach-parameter inputs on the onboarding wizard, and "Export Earth
Engine script"'s replacement — see next paragraph.

**The GEE script generator is gone**, not disabled: `lib/gee.ts` and the monitoring
view's date-range/backscatter-ratio controls and "Export Earth Engine script" button were
deleted outright (the button called `download()` + `geeScript()`, both removed). The
monitoring view's aside now shows an `<Empty>` panel in their place; "Open Earth Engine"
(a plain external link) and the now-disabled "Import observed polygons" button stay.

---

## 4. What still computes client-side (candidates for moving server-side)

These are pure functions over already-fetched data (not fetches themselves), so they
weren't touched — `source.ts`'s job is to gate *data acquisition*, not necessarily to
own every downstream calculation. They're listed here because, per
`docs/handoff_contract.md`, some of this arguably belongs in the backend's `Estimate`
objects (pre-computed, with `low`/`high`/`confidence`) rather than being recomputed from
raw arrays in the browser:

| Computation | Where | Hardcoded constant |
|---|---|---|
| Wet-cell threshold for area/legend | `lib/sentriq.ts` `stats()`, `terrain-map.tsx` canvas paint | `0.3` m |
| Flat-earth cell area (`dx * dy`) | `lib/sentriq.ts` `stats()` | — (should be `dx`/`dy` from a real UTM-projected grid, not degrees) |
| Impact risk class | `app.tsx` `impacts` `useMemo` | `≥3` High, `≥1` Moderate, `≥0.3` Low, else Outside |
| Map colour class breaks | `terrain-map.tsx` `bandsFor()` | Fallback only, used until `styles` (§2) arrives — see `STYLE_GUIDE.md` §2.6 |
| Form defaults | `lib/model.ts` `defaults: Params` | Generic (head 40 m, width 120 m, …) — pre-fills the disabled Physics-run form, not a result |

None of these run today with real data (every code path that could produce a non-null
`Result` is gated, §2-§3), so they're dormant, not wrong — but whoever wires up
`queryFlood()`/`getImpact()` for real should decide whether to keep them or replace them
with values read straight from the backend's `Estimate` objects.

---

## 5. Browser storage

**None.** The IndexedDB store (`sentriq-offline`) and the Cache Storage-backed service
worker (`public/offline-sw.js`) were both removed with the rest of the offline-caching
code (§3). There is no `localStorage`, `sessionStorage` or IndexedDB usage anywhere in
the app.

---

## 6. Exports

The Exports view's format picker and manifest panel are unchanged, but "Export selected
format" is `disabled={!result || exporting}` and `result` is always `null` (§2), so it
can never be clicked in this build. Its handler (`exportNow()`) now calls
`source.exportUrl(format)` and shows the "awaiting" reason as a toast — it no longer
generates SHP/KML/GeoJSON/CSV/HTML/JSON files client-side (that was `lib/sentriq.ts`'s
`exportResult()`, removed along with its `@mapbox/shp-write`/`jszip` dependencies).

---

## 7. Remaining hardcoded UI copy (not data, not a bug)

A few strings are still literal because they describe the product or a generic default,
not a specific dataset: "SIH 2026", "NTRO", "HADR", the mission-strip taglines, "THE
TERRAIN IS REAL." (an approach-level claim, not a per-instance one — see
`STYLE_GUIDE.md`), and `lib/model.ts`'s `defaults: Params`. None of these name a
specific site, and none claim data is loaded when it isn't.

---

## 8. Broken or inconsistent

1. **Two `source.ts` functions have no matching contract endpoint**: `listScenarios()`
   and `listSavedRuns()`/`saveRun()` (flagged in the file itself). Ask whoever owns
   `docs/handoff_contract.md` before wiring these to real routes — the contract may want
   them folded into an existing endpoint instead.
2. **`getImpact()`, `getCompare()`, `getObserved()` and `getJob()` are unwired** (§2).
   The impact and compare views still expect local computation / client-side import,
   which no longer has a way to bring in data. Whoever reconnects these views should
   decide whether to route them through these functions or remove them from `source.ts`.
3. **`Landing`'s `playing` and `pop` props are still unused** (pre-existing, not
   introduced by the strip). `cache` was unused before Group 3 and is now used (the
   hero's "N cached runs" figure).
4. **SPA fallback needed for production.** `vite build` produces a static `dist/`;
   whoever serves it (eventually M0) needs to fall back to `index.html` for every
   `/{view}` path, or deep links 404. `vite preview` and `vite dev` already do this.
5. **`npm run check:shell`** (`scripts/check-shell.mjs`) type-checks, builds, and greps
   the source for six strings that name pieces this strip removed (`tehri`, the source
   cell index `4510`, `model-worker`, `/api/records`, `oai-authenticated`, `240 m`). If
   it fails, something removed by Groups 1-5 came back, or new code is bypassing
   `source.ts` — see `../docs/progress.md` for what each match means.
