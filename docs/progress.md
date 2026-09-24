# Progress log

## 2026-09-24 — backend/shared: site config loader + canonical grids
- `backend/shared/site_config.py`: Pydantic v2 model of the `sites/*.yaml` v1 format. Every value must carry
  `unit`/`source`/`status`; typed values check units, bbox/point ranges, UTM EPSG, enums, ISO dates; cross-checks ids,
  cascade `triggered_by`, inflow sources, near-inside-far and cell-size divisibility. `load_site_config()` emits one loud
  `PlaceholderWarning` (+ log) listing every placeholder path; `SiteConfig.placeholder_fields` / `has_placeholders`.
- `backend/shared/grid.py`: `CanonicalGrid` (= `grid.json`, contract §1.4), far/near grid builders (outward snapping,
  near nests on far-field corners), `lonlat_to_rowcol` / `rowcol_to_lonlat`, `resample_to_grid` (nearest for ints,
  bilinear for floats), `write_grid_raster` (tiled LZW GeoTIFF).
- Tests: `tests/shared/` on synthetic site `tests/fixtures/shared/synth.yaml` — 67 passing.
- Env: `environment.yml` (canonical), `requirements.txt` + local `.venv` (conda not installed on this machine).
- Teesta (all placeholders, 48 fields): far-field 2534 x 5016 @ 30 m (12.7 M cells, ~51 MB per float32 raster),
  near-field 906 x 1011 @ 10 m.
- Open: schema drift vs contract §3.1 logged in docs/decisions.md (pending team decision).

## 2026-09-24 — frontend: strip the Sentriq prototype to a UI shell (in progress)
Executing the approved plan from `frontend/STYLE_GUIDE.md` + `frontend/API_USAGE.md`'s review: strip the inherited
"Sentriq" prototype (Tehri-only, its own toy solver, Cloudflare D1/R2 + ChatGPT auth) down to a UI shell that keeps
every screen/component/style, with all data routed through one seam (`frontend/src/data/source.ts`) that returns
"awaiting" until the real M0 API exists. Branch `frontend-ui-shell`, commits reviewed by screenshot diff after each
group (`docs/strip_check/<group>/`, Playwright harness in `frontend/visual/`, kept out of the app's own deps).

- **Baseline** (`39fb6fa`): snapshot of the prototype as received. **Note:** a bare `data/` rule in the repo root's
  `.gitignore` (meant for the backend's gitignored `data/`) also matched `frontend/public/data/` and
  `frontend/src/data/` (no leading slash → matches any depth), so those never actually landed in `39fb6fa` — caught
  and fixed in `24f24b1` with `!/public/data/**` / `!/src/data/**` negations in `frontend/.gitignore`, before either
  path was deleted for real. Watch for this pattern if any other `frontend/**/data/` directory shows up later.
- **Group 1 — build swap** (`517b992`): replaced vinext/Next.js/Cloudflare Workers with a plain Vite + React SPA
  (`index.html`, `src/main.tsx`, minimal `vite.config.ts`). No data/content changes. Screens are pixel-identical to
  baseline except a 0.07% diff on the library screen's saved-runs badge (401 → unreachable fetch), expected and
  since resolved by Group 2 removing that endpoint entirely.
- **Group 2 — solver/data/cloud/offline removal** (`00011cc`): added `src/data/source.ts`; removed the Fast
  Screening solver, the Tehri scenario library and terrain, synthetic exposure, the GEE script generator,
  `/api/records` + D1/R2 + ChatGPT auth, IndexedDB/service-worker offline caching, and the Python toolkit. All 9
  upload buttons and the two offline buttons stay on screen, now `disabled`. `tsc`/`vite build` clean, 0 console
  errors on all 12 screens. Deferred to Group 3 (wording, not mechanical): the map's "Loading prepared terrain /
  The Tehri scenario library is loading." placeholder, sidebar's permanent "Loading…" label, the dataset registry's
  hardcoded "LOADED" badge and Tehri/THDC row text, and the methodology dialog's solver narrative — all visible
  in `docs/strip_check/02-data-solver-cloud-removed/`, not regressions.
- **Group 3 — remaining literals + stale awaiting-state text** (`0d3e9b9`): fixed the Group 2 deferred items above,
  plus every other Tehri/§10 literal found by a fresh repo-wide grep — `terrain-map.tsx`'s `grid.name.startsWith
  ('Tehri')` branches (inflow-pin label, 4 hardcoded map-place labels) and its Mapzen attribution, `landing.tsx`'s
  "4 cached runs" (now `nf(cache.length,0)` — `cache` was already an unused prop), "25–100% of 240 m", the
  hardcoded coordinate/grid-dimension captions, the "RUNS IN BROWSER · ready" badge on a solver that no longer
  runs anywhere, and the methodology dialog's description of "four real local-inertial screening runs over
  downloaded Tehri terrain" (rewritten to state what's connected and what each section will show once something
  is, rather than inventing new claims about the real M5 emulator's behaviour). Found and fixed a real bug while
  here: `landing.tsx`'s "Interpolating between X% and Y%" message compared `bracket?.lower?.severity ===
  bracket?.upper?.severity`, which is `undefined === undefined` → `true` whenever `bracket` is `null` — so it
  always read "Exact cached scenario" even with zero scenarios connected, in every build back to the original
  prototype. Layout unchanged (0% diff on 6 screens, ≤0.5% text-only on 5, +21px on `data` for two longer
  sentences).
- **Group 4 — map colours through `getStyles()`** (`54534a7`): `terrain-map.tsx`'s depth/velocity/arrival class
  breaks were hardcoded arrays; they now read an optional `styles` prop shaped like contract §6
  (`contracts/styles.json`), fetched once via `source.getStyles()` alongside terrain/scenarios. The CSS colour
  ramp stays; the numeric legend labels show "Awaiting style classes" until `styles` arrives. Verified by direct
  checks of the extracted band/label logic (fallback reproduces the original hardcoded values exactly; a
  contract-shaped example converts and dedupes correctly) rather than a screenshot, since the map component isn't
  reachable anywhere while `grid` stays `null` (confirmed: 0% diff on every screen).
- **Group 5 — SPH lab relabelled** (`069b52d`): kept per the approved decision (self-contained, already
  disclaims itself). Labelled "Educational Explainer" in the nav, page title, a new panel badge
  (`app/sph-lab.tsx`), and the two internal references to its old name, so the page doesn't call itself two
  different things.
- **Group 6 — guard script + docs**: added `npm run check:shell` (`scripts/check-shell.mjs`) —
  `tsc --noEmit` + `vite build` + a grep across `app/`, `lib/`, `src/`, `components/`, `hooks/` for six strings
  that name pieces Groups 1–5 removed (`tehri`, the hardcoded source-cell index `4510`, `model-worker`,
  `/api/records`, `oai-authenticated`, `240 m`) — verified it actually fails when one is reintroduced, then
  reverted the test. Removed the now-dead `db:generate` script (drizzle is gone) and the stale
  `"site-creator-vinext-starter"` package name (vinext is gone). Rewrote `README.md` for the shell's current
  state (dropped every demonstration step that named removed functionality). Refreshed `STYLE_GUIDE.md` (build/
  stack/routing sections only — the CSS/component documentation was untouched by the strip and stays accurate)
  and rewrote `API_USAGE.md` around the `source.ts` seam, what's disabled and why, and what still computes
  client-side and might belong in a backend `Estimate` instead.

## Where this leaves the frontend
A UI shell: every screen, layout, component and style unchanged, reading through one seam
(`frontend/src/data/source.ts`) that today always answers "awaiting" — honestly, not by hiding the fact. Two
`source.ts` functions (`listScenarios`, `listSavedRuns`/`saveRun`) have no matching endpoint in
`docs/handoff_contract.md` yet; four more (`getSite`, `getImpact`, `getCompare`, `getObserved`, `getJob`) are
defined but not called from anywhere — the impact and compare views still compute/import client-side and haven't
been rewired. Connecting the real backend should mean filling in `source.ts`'s function bodies with `fetch()`
calls and, for the disabled upload buttons (§3 of `frontend/API_USAGE.md`), deciding where each one's parsed
result should live now that there's no local solver or cache to hand it to.
