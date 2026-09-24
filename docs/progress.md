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
- Still to do: Group 3 (remove remaining §10 literals, fix the above placeholders), Group 4 (map colours through
  `getStyles()`), Group 5 (SPH lab → "educational explainer" label), Group 6 (guard script + rewritten README).
