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

## 2026-09-24 — contracts/ generated; M0 mock API serving every endpoint

Generated `contracts/` (JSON Schemas + one example per payload, plus `styles.json`)
from `docs/handoff_contract.md` §2, §4-§6 — this didn't exist before this session.
Built `backend/m0_api` (FastAPI) serving all 22 endpoints from contract §5 as mocks
backed by those examples; every response is validated against its schema before
being sent (and again independently in tests). Raster layers serve as PNG, vectors
as GeoJSON, exports as real zip/KML/PDF bytes with correct media types.

No job queue or `data/registry.sqlite` behind this yet — every well-formed ID
returns the same mock payload; only `site_id` is checked against a short known-sites
list (`teesta`, `rishiganga`) so 404 handling has a real path to test. Wiring real
M1-M7 outputs, the registry and job queue is future work.

`environment.yml` / `requirements.txt` gained `jsonschema`, `httpx`, `fastapi`,
`uvicorn`. `pytest -q`: 131 passed (64 new in `tests/m0_api/`).

Known gaps carried over from the earlier contract-conflicts review, still pending
the user's decisions: the site-config YAML-vs-§3.1 mismatch, and the frontend
`API_USAGE.md` conflicts list. Neither blocks this mock API, which only implements
what §5 already specifies.

## 2026-09-24 — M0 job system: registry, worker, detached runs, restart recovery

Replaced the mock `POST /sites` and `GET /jobs/{job_id}` with a real job system. All other
endpoints are still mocks.

- `backend/m0_api/registry.py`: `data/registry.sqlite` with the four §4.5 tables, using exactly the
  contract columns. WAL mode, so the API and the worker can share it. `SIH26_DATA_DIR` overrides
  `data/`.
- `backend/m0_api/jobs.py`: the state machine, using the **contract §5.3 stages as frozen**, not the
  pending decisions.md Part 2 proposal (user's choice this session). The worker bookkeeping §4.5 has
  no column for (`started_at`, `demo_mode`, `run_ids`, recent events) lives in `payload_json`, so
  the contract is unchanged. Writes check the expected current stage, so a stale writer is
  rejected.
- `backend/m0_api/worker.py` (`python -m backend.m0_api.worker`) is a separate process holding a
  single-worker lock.
  - In-process stages are FAKE (they sleep).
  - `simulating` launches runs one at a time as detached processes (`backend/m0_api/fake_solver.py`)
    and reads progress from each run's `log.txt`.
  - `recover()` at start-up re-attaches to live runs, records runs that finished while it was down,
    and fails the job with `worker_lost_run` if a run died unobserved.
- `eta_s` stays null until one run has finished; after that it is the mean wall time × runs
  remaining.

`pytest -q`: 174 passed (43 new). Also checked by hand with real uvicorn and worker processes:
killing and restarting the API mid-`simulating` loses nothing; killing the worker leaves the solver
running, and the restarted worker re-attaches and finishes the job.

Open gaps, all needing a team or contract decision:
- `POST /sites/{id}/rerun` is still a mock: contract §5.3 lists no stages for `rerun`.
- No retries and no minimum-run rule: `max_run_retries` / `min_runs_for_training` ⚙️ are unset.
  One failed run fails the job (`run_failed`).
- Contract §1.8 has no location for a job-level log; `log_tail` is built from `payload_json`
  events plus the tail of the active run's log.
- `POST /sites` now rejects a missing or invalid `site_config.site_id` (422) and a site that
  already has an active job (409 `site_onboarding_in_progress`); there is no uniqueness check
  against configured sites yet.
- `runner.is_alive` reads `/proc`, so it works on Linux/WSL only.

## 2026-09-24 — M0-5: render raster layers to PNG overlays (`rendering.py`)

`backend/m0_api/rendering.py`: colours a single-band raster (a canonical-grid array, e.g.
from a `queries/<query_id>/layers/*.tif`) into an RGBA PNG, driven entirely by
`contracts/styles.json` (§6) — no colour is hardcoded, so the frontend legend, this
renderer and M6's future KML export (M6-6) all read the same file. Handles every
`styles.json` shape: `continuous` (linear stops), `classes` (breaks + colour bands),
`diverging` (signed range about zero) and `extent_class` (HIGH/POSSIBLE fill + opacity).
Nodata and non-positive cells (dry ground / zero probability) are fully transparent.
PNG encoding uses GDAL's PNG driver via `rasterio.io.MemoryFile` (no Pillow — it isn't
in the project's stack). `render_and_cache` writes the PNG next to its source `.tif`
and reuses it on repeat requests, matching the §1.8 `queries/<query_id>/layers/` layout.

Bounds come from `CanonicalGrid.bounds_latlng` (`backend/shared/grid.py`, unchanged) —
the PNG's pixel grid stays in the site's UTM canonical grid and is stretched onto those
EPSG:4326 bounds by the Leaflet image overlay, rather than reprojected pixel-by-pixel;
noted as a simplifying assumption in the module docstring.

Wired into endpoint 11 (`GET /flood/{query_id}/layers/{layer_id}.png`, `main.py`): if a
real `.tif` exists on disk at the contract path it's rendered for real; otherwise the
endpoint keeps returning the 1x1 mock PNG, since M5 doesn't write real layer GeoTIFFs
yet (CLAUDE.md rule 2).

Contract check: §2.6 `LayerRef` has no per-layer `legend` field — §6 already states
`styles.json` is the one file driving overlays, KML styling *and* legends, i.e. the
frontend is meant to resolve `style_id` against `GET /styles` itself. Flagged this
against a literal reading of an initial task description ("include legend data in each
layer response") and the user confirmed: follow the contract as written, no `legend`
field added to any response.

Tests: `tests/m0_api/test_rendering.py` (9, synthetic grid + arrays — bounds, dry/nodata
transparency, classes/continuous colours checked pixel-for-pixel against
`styles.json`, extent_class fill+opacity, unknown layer_id raises, cache writes once
and is reused) + one new endpoint test wiring a real GeoTIFF through `GET /flood/.../
layers/*.png`. `pytest -q`: 184 passed (10 new).

Note: this machine's `.venv` is missing `jsonschema`/`fastapi`/`httpx`/`pip` itself;
`/usr/bin/python3` has the full stack instead and is what ran all tests this session.

## 2026-09-24 — M2 breach engine

Built `backend/m2_breach/` from scratch (it was an empty directory): one module per base
equation (`f16.py`, `xz9.py`, `z20.py`, `f95.py`, `f8.py`, `mclm.py`, `h14.py`), the Table 5/DFM
2024 fusion (`dfm.py`), the dual-method range logic (`ranges.py`) and the per-site orchestrator
(`breach_params.py`) that writes `data/<site_id>/breach/breach_params.json`.

**Blocker surfaced and confirmed with the user before writing any code:** `docs/Equations.md`
itself says to block Xu & Zhang (2009) (code XZ9) until its reference height `h_r` is sourced
from the original paper — Azmi's reproduction never defines it. XZ9 feeds the updated-DFM fusion
for both Q_p and B_ave, and DFM 2024 for Q_p, so today **only the failure-time (T_f) dual-method
range is computable**; Q_p and B_ave report their individually-computable base methods (F16, Z20;
F95, F8) but their recommended-pair range is `status: "blocked"`. Z20 is also blocked outside
HD/CD dam types (Teesta III is FD) — the FD/ZD mapping isn't in Azmi's reproduction either.
Full writeup: `docs/decisions.md` "M2 breach engine: XZ9/h_r blocker...".

Added `contracts/schemas/breach_params.schema.json` and `contracts/examples/
breach_params.example.json` (generated from `sites/teesta.yaml`, so it shows a real blocked-XZ9
case), wired into `tests/m0_api/test_schemas.py`'s example/schema pairing.

Tests: `tests/m2_breach/` (46 tests) — hand-computed values per equation and branch (F16 O/P,
k_h continuity at h_b=6.1m, a length-scaling dimension check; Z20 HD/CD plus FD/ZD blocked; F8
T_f unit derivation; DFM equals its weighted sum; a blocked component propagates through DFM;
a negative DFM value is flagged (`dfm_nonpositive`), never clipped); `breach_params.py`
end-to-end on both a synthetic config and the real `sites/teesta.yaml` (concrete-dam refusal,
moraine caveat, placeholder propagation, schema validation); and `test_breach_cases.py`, which
reproduces `docs/paper_azmi.md` Table 7's median % error over `tests/data/breach_cases.csv` for
every method that isn't blocked (F16/Z20 for Q_p, F95/F8 for B_ave, F95/F8/MCLM for T_f) — all 7
land within the paper's own reported MAD of its median, with no tuning:

```
F16_Qp:   n=29  our=-11.6%  paper=-10.1%  MAD=31.9
Z20_Qp:   n=41  our= -9.7%  paper=-26.2%  MAD=34.0
F95_Bave: n=128 our= -9.4%  paper= -5.2%  MAD=23.2
F8_Bave:  n=128 our= -6.5%  paper= -1.8%  MAD=29.8
F95_Tf:   n=68  our=  4.2%  paper=-11.3%  MAD=36.6
F8_Tf:    n=68  our=  5.0%  paper= -7.3%  MAD=35.3
MCLM_Tf:  n=68  our= 14.3%  paper=  3.4%  MAD=59.4
```

`pytest -q`: 231 passed (46 new). Ran with `/usr/bin/python3` (this machine's `.venv` is still
missing several packages, per the last session's note).

**Out of scope this session, left for next:** hydrographs (`hydrograph()`, contract §4.2's
`hydrographs/*.csv` + sidecar) and cascades. Also open: sourcing h_r for XZ9, and the FD/ZD
mapping for Z20 — both block real Q_p/B_ave ranges for Teesta until resolved.

## 2026-09-24 — M2 breach hydrographs

Built contract §4.2's hydrograph part, left open at the end of the last session:

- `backend/m2_breach/weir.py`: trapezoidal broad-crested weir discharge (standard hydraulics, not
  from `docs/Equations.md`) — no built-in coefficients, read from config (`docs/decisions.md`).
- `backend/m2_breach/storage.py`: `StorageCurve` above the final breach invert, from a surveyed
  elevation-volume curve or an area-volume-relation derivation (documented, not from a paper).
- `backend/m2_breach/hydrograph.py`: `breach_growth_weir()` (level-pool routed, ODE via
  `scipy.integrate.solve_ivp`, breach width+depth grow together over `failure_time_s`),
  `triangular()` fallback (volume-exact), `hydrograph_for_dam()`/`hydrograph()` (method selection,
  `peak_within_m2_range` against the M2 Q_p range, caveats), `write_hydrograph()`.
- `backend/shared/site_config.py`: additive optional `Dam.volume_elevation` and
  `Dam.breach_hydrograph` blocks.
- `contracts/schemas/hydrograph_sidecar.schema.json` + generated example; registered in
  `tests/m0_api/test_schemas.py`.
- New tests: `tests/m2_breach/{test_weir,test_storage,test_hydrograph}.py` — mass conservation
  (weir and triangular), zero flow before breach start/offset, `peak_within_m2_range` correctness
  (not tuned to force `true` — the M2 Q_p range is blocked for the synthetic dam, so the flag is
  `None`), method fallback/blocking, sidecar schema validation.

`pytest -q`: 280 passed (49 new). Ran with `/usr/bin/python3` (installed `scipy` there via
`pip install --user --break-system-packages`; this machine's `.venv` still has no `pip`).

**Out of scope this session, left for next:** cascades (downstream dam `t_offset_s`), and the
pending site-config-schema decision (`volume_elevation`/`breach_hydrograph` are additive so this
doesn't block, but the wider v1-vs-contract migration is still open).

## 2026-09-24 — M2 cascade engine (multi-dam sites)

Extended M2 for sites with several dams in sequence (Teesta: South Lhonak → Teesta III), left open
at the end of the last session. Contract §3.1's `cascade.approach: null ⚙️` was genuinely
undecided (nothing about it was in this file before today) — confirmed the choice with the user
before building: **`two_stage_imposed`**, not `dambreak_structure`. Full reasoning in
`docs/decisions.md` ("M2 cascade engine: two-stage imposed hydrograph").

- `backend/shared/site_config.py`: additive `Dam.equations_applicable` (default `true`),
  `Dam.imposed_ranges` (`{peak_discharge_m3s, breach_width_m, failure_time_s}`, each a
  `[low, high]` `RangeValue`), `Dam.trigger` (`{type: inflow_threshold, value: DischargeValue}`),
  and top-level `SiteConfig.cascade` (`{approach: two_stage_imposed | dambreak_structure}`). New
  cross-checks: `kind: concrete_dam` ⇒ `equations_applicable: false` ⇒ `imposed_ranges` required;
  `triggered_by` ⇒ site needs a `cascade` block; `two_stage_imposed` ⇒ every triggered dam needs
  its own `trigger`.
- `backend/m2_breach/breach_params.py`: `compute_dam` now branches on `equations_applicable` —
  `false` builds the output ranges from `imposed_ranges` (`interval: "imposed"`, caveat
  `concrete_dam_imposed`) instead of running the Azmi equations. Deleted `DamKindRefused`: a
  concrete dam without `equations_applicable: false` is now rejected by the loader, not by
  `compute_dam`.
- `backend/m2_breach/cascade.py` (new): `cascade_plan()` (ordered stages, raises
  `UnsupportedCascadeApproach` for `dambreak_structure`), `trigger_time()` (linear-interpolated
  threshold crossing on a routed-inflow time series — no routing/celerity invented, the series is
  always an input), `triggered_hydrograph()` (sets `t_offset_s` to the trigger time, or returns
  `None` if the threshold is never reached in that scenario; releases only the dam's own storage —
  superposition, caveat `cascade_superposition`; raises `HydrographBlocked` if the threshold is a
  placeholder).
- `backend/m2_breach/hydrograph.py`: `Hydrograph.trigger` (optional dict), included in the sidecar
  only when set.
- Contracts: `breach_params.schema.json`'s `OutputRange.interval` gains `"imposed"` (nullable
  `selected_pair`, optional `source`); `hydrograph_sidecar.schema.json` gains an optional
  `trigger` object. `contracts/examples/breach_params.example.json` regenerated from
  `sites/teesta.yaml` — no diff (teesta_iii stays an embankment dam today).
- `sites/teesta.yaml`: added `cascade: {approach: two_stage_imposed}` and `teesta_iii.trigger`
  (placeholder — not sourced). `sites/template.yaml`: documented the new fields.
- New tests: `tests/fixtures/m2_breach/synth_cascade.yaml` (synthetic two-dam site: moraine lake →
  concrete dam with imposed ranges and a trigger), `tests/m2_breach/test_cascade.py` (plan
  ordering incl. a three-dam chain, `trigger_time` interpolation, triggered/not-triggered/blocked
  hydrographs, superposition volume check, sidecar schema validation, an end-to-end
  lagged-hydrograph scenario), plus loader cross-check tests in `tests/shared/test_site_config.py`
  and imposed-range tests in `tests/m2_breach/test_breach_params.py`.

`pytest -q`: 307 passed (27 new). Ran with `/usr/bin/python3`.

**Out of scope this session, left for next:** Teesta III's dam type is still unverified
(`docs/ideation.md`) — if it turns out to be concrete rather than embankment, its
`equations_applicable`/`imposed_ranges` need filling from a real source. The per-dam `trigger`
deviation from contract §3.1 is PENDING team agreement (see decisions.md); h_r (XZ9) and the
Z20 FD/ZD mapping are still blocked from earlier sessions.

## 2026-09-25 — M5: synthetic test world (`backend/m5_emulator/synthetic.py`)

`backend/m5_emulator/` was completely empty before this session (no files at all). Built
`docs/m5_specs.md` §7's synthetic test world — the fake-physics stand-in for Delft3D/SPH used to
develop and test the rest of M5 before real runs exist.

- `synthetic_flood_maps(grid, water_volume_m3, breach_width_m, failure_time_s, ...)`: pure,
  deterministic function returning max depth [m] / max velocity [m/s] / arrival time [s since t0]
  numpy arrays on a `CanonicalGrid`, reproducing every qualitative behaviour in §7.2 (gorge depth
  cap, constriction backup with an upstream-biased backwater shoulder, terrace threshold overtop
  with 0.5–1.5 m post-overtop depth, plain attenuation/spreading, arrival delay from failure time
  fading with distance) via smoothstep-blended piecewise geometry — no discontinuities except the
  terrace's deliberately steep (but continuous) sigmoid threshold. `write_synthetic_run()` writes
  the same maps as GeoTIFFs at `summary/{max_depth,max_velocity,arrival_time}.tif`, matching the
  M3/M4 run-result schema (`docs/handoff_contract.md` §4.4) exactly, via `backend.shared.grid.write_grid_raster`.
- **Flagged, not silently changed:** §7.1 sketches non-square cells (e.g. "100 m x 50 m") sized to
  resolve the ~50 m gorge across a valley whose fan is ~2 km wide. `CanonicalGrid` — the grid every
  raster in this project must align to (§1.4) — only supports square cells, and no single square
  size both resolves the narrowest feature (the 12.5 m constriction half-width) and keeps the
  "~40k cells" small-grid target at this valley's full cross width. Resolved by keeping the spec's
  40 km length and picking square-cell grids sized to actually resolve the constriction instead:
  `small_grid()` = 16 m, 2500x200 (500k cells), `large_grid()` = 8 m, 5000x400 (2M cells, same
  order of magnitude as "about 1M" and as the real far-field grids in §1.4's own example).
- Verified monotonicity (acceptance test A3) beyond the unit tests: a 300-sample random sweep
  across the full `DEFAULT_INPUT_RANGES` design space (V_w log-uniform 1e5–1e8, B_ave/T_f uniform
  in their ranges) found **0% non-monotonic pairs** (target: ≤5%) for depth/velocity rising with
  V_w, arrival falling with V_w, and arrival rising with downstream distance, over ~28M wet-cell
  comparisons each. Large grid: 2M cells, one scenario in 0.087 s (A7 target: <2 s).
- Tests: `tests/m5_emulator/test_synthetic.py` (24 tests) — grid presets, output shape/dtype/nodata
  contract, determinism (with and without the noise switch), input validation, monotonic response
  at several points, constriction backup, gorge-capped/plain-wide extent, terrace dry-then-flooded
  threshold, and a GeoTIFF round-trip through `write_synthetic_run` (CRS/transform/nodata/values
  match the in-memory arrays exactly).

`pytest -q`: 331 passed (24 new). Ran with `/usr/bin/python3`.

**Out of scope this session, left for next:** everything else in `docs/m5_specs.md` — scenario
design (LHS over M2's ranges), the run cache, PCA + GP emulator itself, LOOCV, Monte Carlo,
confidence rule, and the empirical fallback. `synthetic.py` only provides the test world those
pieces will be built and tested against.

## 2026-09-25 — m5_emulator: PCA + GP emulator core (fit / predict / save-load / sensitivity)
- `transforms.py`: `log1p` for depth and velocity (docs/m5_specs.md §3 — the pasted task description
  said "log/sqrt"; confirmed with the user to follow the spec's log1p-for-both instead), `identity`
  for arrival; `fill_arrival` replaces dry-cell nodata with `t_end_s` and clips to `[0, t_end_s]`.
- `inputs.py`: `InputScaler` — log10 for `water_volume_m3`, linear for `breach_width_m`/
  `failure_time_s`, standardised to zero mean/unit std on the training design; flags per-input
  extrapolation against the training box (§6 check C, not wired to a confidence rule yet).
- `pca.py`: `corridor_mask` (union of cells wet >0.03 m in any training run, 3-cell 4-connected
  dilation buffer); `fit_pca` — centred thin SVD, smallest D* reaching 99% variance capped at N−2,
  `PCABasis.decode_std` (per-cell `sqrt(sum W_ij^2 sigma_j^2)`, emulator uncertainty only, documented
  as excluding PCA truncation error); components stored float32 per spec.
- `gp.py`: one `GaussianProcessRegressor` per component, `ConstantKernel * Matern(nu=1.5, ARD) +
  WhiteKernel`, length-scale bounds [0.1, 10], `normalize_y=True` (so the spec's noise floor
  "1e-6 x component variance" is the constant 1e-6 in the normalized-target space the optimiser
  actually fits in — documented since it's easy to get backwards), 10 restarts.
- `library.py`: a synthetic-only maximin-LHS training library (§2) — **not** the contract's
  `design/scenario_design.json`; `run_ids` use `model: "synthetic"`, outside the contract's model
  enum, and are only ever written under `tmp_path`. **Bug caught before it shipped:** widening
  `failure_time_s` (300-10800 s) and `breach_width_m` (20-150 m) linearly by 20% of their span drove
  the lower bound negative (`failure_time_s` -> -1800 s), since the synthetic world's illustrative
  ranges span almost an order of magnitude unlike real M2 pair bounds; `water_volume_m3` needed the
  same fix in log space. Fixed: log-space widening for the log10 input, and a positivity clamp
  (`low * 0.5`) for the linear ones.
- `emulator.py` — `FloodEmulator`: `fit` (per output: transform -> corridor-mask -> PCA -> per-
  component GPs, with reconstruction RMSE reported both in transformed space and in physical units
  over Omega/"had a real arrival"); `predict` (GP mean/std -> PCA decode -> inverse-transform,
  depth/velocity clipped >= 0, **arrival explicitly clipped to `[0, t_end_s]`** — caught in testing
  that GP extrapolation can otherwise predict arrivals past `t_end_s`, since `fill_arrival`'s own
  clip only bounds the *training* targets — then arrival masked to nodata outside the predicted wet
  extent, `central depth > arrival_m`); `save`/`load` in the contract §4.6 layout (`manifest.json`,
  `pca_<output>.npz`, `gp_<output>.joblib`, short names `depth`/`velocity`/`arrival`); manifest
  carries extra fields beyond the contract list (`t_end_s`, `grid`, `settings`,
  `reconstruction_rmse.transformed`, `fit_warnings`) needed to reconstruct predictions — flagged as
  additive, nothing renamed/dropped; `sensitivity_table()`/`format_sensitivity_table()` — fitted
  length scales per (output, component) plus a variance-weighted relative-sensitivity summary.
- Verified on the synthetic library (N=30, small grid, 500k cells, seed 42): corridor 117,954 cells
  (23.6%); depth/velocity D*=1 (var. explained 0.996/0.995), arrival D*=10 (0.990); reconstruction
  RMSE (physical) 0.092 m depth, 0.088 m/s velocity, 384 s arrival; fit 3.9 s, single-scenario
  predict 27 ms (spec A7 target < 2 s), save/load round-trip matches to 1e-4. Sensitivity table:
  `water_volume_m3` is the most sensitive input for all three outputs (relative 0.49/0.44/0.63),
  matching the synthetic world's `V_EXP=0.55` > `B_EXP`/`T_EXP` construction.
- Tests: `tests/m5_emulator/{test_transforms,test_inputs,test_pca,test_gp,test_library,
  test_emulator}.py` — 59 new (transforms round-trip/clip/fill; input scaling + extrapolation
  flagging; PCA variance target/cap/reconstruction/decode_std against a brute-force check; GP
  recovers a known function and gives the driving input a shorter length scale than irrelevant
  ones; LHS stratification/maximin/determinism; full fit-predict-save-load-sensitivity integration
  on N=30, including depth beating a training-mean baseline and extent F1 >= 0.8 on 6 held-out
  scenarios). `pytest -q`: 390 passed (59 new).
- Setup: `scikit-learn`/`joblib` installed into the `/usr/bin/python3` user site (conda unavailable
  on this machine, same as the existing `.local` setup); added to `requirements.txt`.

**Out of scope this session, left for next:** LOOCV + `validation/loocv.json`, the full A1-A8
acceptance suite (today's tests check a light subset — a training-mean baseline and one F1
threshold, not the paper's two required baselines or the 90% CI coverage test), Monte Carlo /
unknown-breach mode, the confidence rule, `get_flood()`, the empirical fallback, and the real
`design/scenario_design.json` (today's `library.py` is synthetic-only test scaffolding).

## 2026-09-25 — M5: LOOCV, A1 baselines, validation report, acceptance check

Built the LOOCV pipeline `docs/m5_specs.md` §8 needed and everything before it was still missing:
metrics, both A1 baselines, `validation/loocv.json` (`docs/handoff_contract.md` §4.6) and an honest
A1-A8 check.

- `metrics.py`: one function per metric — extent IoU/F1@{0.05,0.1,0.3}, wet-cell (Omega = depth >
  `wet_m` in truth OR prediction) depth RMSE and velocity MAE, arrival MAE/RMSE (cells where both
  truth and prediction have a real arrival), signed flooded-area % error, 90% interval coverage,
  PCA-projection RMSE (the honest per-fold A5 number, not the in-sample one `pca.py` reports at fit
  time), and terrace majority-vote classification (A4, synthetic-world only).
- `baselines.py`: `LinearScoresBaseline` (OLS per PCA component on standardised inputs, same basis
  as the fold's GP) and `NearestRunBaseline` (IDW power-2 blend of the 3 nearest training runs'
  physical maps, arrival filled before blending). Neither reports an uncertainty interval.
- `emulator.py` refactor (behaviour-preserving, guarded by the existing `test_emulator.py`):
  extracted `FloodEmulator.maps_from_latent()` (PCA-decode -> inverse-transform -> embed -> clip ->
  arrival-mask, used by `predict()` and the linear baseline) and
  `maps_from_corridor_physical()` (embed -> clip -> arrival-mask only, used by the nearest-run
  baseline, which never touches PCA) so every method — GP, both baselines — goes through the exact
  same post-processing pipeline before scoring.
- `synthetic.py`: added `terrace_cells()` (boolean terrace mask for A4) and `SYNTHETIC_POIS` /
  `poi_cell_index()` (5 declared points spanning gorge/constriction/terrace/middle/plain, for A2's
  POI coverage and A3's monotonicity check).
- `loocv.py`: `run_loocv()` — one fold at a time (refits scaler, corridor mask, PCA **and** GPs on
  the other N-1 runs per spec §3; only one fold's maps held in memory at once, CLAUDE.md rule 13),
  scoring the GP and both baselines identically. `build_report()` assembles the contract's
  `loocv.json` shape plus additive fields (**flagged, not silently added** — see
  `docs/decisions.md` "M5 LOOCV: additive validation-report fields", pending team sign-off):
  `baseline_nearest` (contract only has `baseline_linear`), `per_run[].extra`, `acceptance`,
  `settings`/`caveats`/`provenance`/`notes`. `run_acceptance()` checks A1 (GP >=10% better RMSE
  than both baselines, F1 not lower), A2 (90% coverage in [80,95]%, k-factor reported-not-applied
  on failure), A4 (terrace), A5 (PCA projection vs emulator RMSE) from the LOOCV folds;
  `check_monotonicity()` checks A3 separately on the synthetic world directly (300 random V_w
  pairs). A6/A8 (confidence rule) and A7 (Monte Carlo/large-grid performance) are **not
  implemented** this session and report `NOT_EVALUATED`, not a fake pass.
- `validation_plots.py`: 4 PNG charts (`metrics_by_run`, `summary_vs_baselines`,
  `coverage`, `poi_coverage`) — Okabe-Ito colorblind-safe 3-way categorical palette (GP/linear/
  nearest), fixed order, no dual axes, target-band shading for the 80-95% coverage checks. Installed
  `matplotlib` (pip --user --break-system-packages, same constrained setup as scikit-learn last
  session); added to `requirements.txt`.
- CLI: `python -m backend.m5_emulator.loocv --synthetic [--n --seed --grid --out]`. Writes to
  `reports/m5_synthetic/validation/` (new, **gitignored** — not `data/`, since `model: "synthetic"`
  and `m5synth_*` run_ids are outside the contract's ID/model patterns, matching `library.py`'s
  existing rule). `--site <id>` raises `NotImplementedError` (real-run loading is future work).
- Tests: `tests/m5_emulator/{test_metrics,test_baselines,test_loocv}.py` — 55 new (hand-built
  arrays with known metric values incl. edge cases; baselines recover an exact linear function /
  return the exact training map at a training point; a coarse-grid N=10 LOOCV integration suite
  checking fold isolation via a `FloodEmulator.fit` spy, schema validation, grading, acceptance
  table shape, and chart files being written). `pytest -q`: **435 passed** (55 new; `test_emulator.py`
  unchanged and still green, confirming the `predict()` refactor is behaviour-preserving).

**Full run on the synthetic library** (N=30, small grid, seed 42, default settings — 30 folds,
~8 s/fold): `reports/m5_synthetic/validation/loocv.json`, `schema_valid: true` (model substituted
to `delft3d` for the check; the substitution is recorded in the report's own `notes`).

| Test | Result | Detail |
|---|---|---|
| A1 (GP beats both baselines) | **PASS** | depth RMSE 0.067 m (GP) vs 0.139 m (linear) vs 0.243 m (nearest); arrival RMSE 815 s vs 1622 s vs 1466 s; F1@0.3 0.993 vs 0.981 vs 0.976 |
| A2 (90% interval calibration) | **PASS** | wet-cell coverage 87.0%, POI coverage 85.3%, both inside [80,95]% |
| A3 (monotonic response) | **PASS** | 300/300 pairs monotonic on extent, POI depth, and POI arrival |
| A4 (terrace threshold) | **PASS** | 27/30 folds (90.0%) classified the terrace correctly — exactly at the spec's threshold |
| A5 (PCA not the bottleneck) | **FAIL** | median PCA-projection RMSE is NOT <= half the emulator RMSE: depth 0.047 m vs half-of-0.067=0.034 m; arrival 598 s vs half-of-815=407 s — the GP/PCA-decode step is adding more error than the PCA truncation itself, the opposite of what A5 wants |
| A6, A8 (confidence rule) | NOT_EVALUATED | confidence rule (§6) not implemented yet |
| A7 (performance) | NOT_EVALUATED | Monte Carlo / large-grid performance out of scope this session |

**Honest bottom line:** A1-A4 pass; **A5 fails** — reported as-is, no threshold tuning. This says
the GP+kernel/optimizer settings are contributing meaningfully more per-fold error than PCA
truncation does, which is worth the team's attention before real runs (candidates: more GP restarts,
loosening/retuning the Matern length-scale bounds, or accepting current settings and revisiting A5's
threshold). A6-A8 stay unevaluated rather than guessed at.

**Out of scope this session, left for next:** Monte Carlo / unknown-breach mode, the confidence
rule (needed for A6/A8), `get_flood()`, the empirical fallback, the real `design/scenario_design.json`,
and loading real Delft3D/SPH runs for `loocv.py --site`.

## 2026-09-25 — m5_emulator: get_flood(), Monte Carlo, confidence rule
- `backend/m5_emulator/confidence.py`: the S (LOOCV skill) / C (query coverage) / U (prediction
  spread) checks (`docs/m5_specs.md` §6), combined by the count rule in `docs/handoff_contract.md`
  §2.3 (all good → HIGH; one weak → MODERATE; two+ weak, OUTSIDE, empirical fallback, or demo mode →
  LOW), plus the placeholder-input cap. Spec only defines U for depth/arrival and doesn't define
  extent's spread at all; documented deviations: velocity reuses depth's *relative* cutoffs, extent's
  spread reads off the POSSIBLE-vs-HIGH fraction of the flooded area (a draft threshold, flagged as
  such, not sourced). `per_cell_upper_bound()` bounds a GP's response over the whole trained input
  box (via all `2^n_inputs` box corners) without assuming which direction the response grows in —
  used by `monte_carlo.py` to size histogram bins.
- `backend/m5_emulator/monte_carlo.py`: `sample_inputs()` (log-uniform/uniform per input scaling,
  §5.2), `chunk_size_for()` (§5.3's formula — reproduces the spec's own "166 samples/chunk" worked
  example once the 2 GB budget is read as decimal, not `2*1024**3`), and `run_monte_carlo()`: chunked
  GP sampling (`z_j ~ N(mu_j, sigma_j^2)` per component per sample) into fixed-size accumulators —
  exceedance counts, per-cell 64-bin histograms (one `np.bincount` per chunk, not a 64-iteration
  Python loop — the loop was the dominant cost at real corridor sizes) for depth/velocity, and exact
  stored samples for site-wide max depth/velocity, inundated area, and every point of interest
  (depth/velocity/arrival). Full-grid arrival maps are explicitly out of scope (POIs only) — see the
  module docstring for why.
- `backend/m5_emulator/query.py`: `get_flood(emulator, mode, inputs, pois, ...)` — `scenario` mode is
  one GP prediction with an *analytic* P10/P90 band and P(inundation) (`1 - Phi`, no resampling);
  `unknown_breach` mode runs `monte_carlo.run_monte_carlo`. Both produce `p_inundation`,
  HIGH/POSSIBLE `extent_class` (site config `high_p`/`possible_p` thresholds), depth/velocity
  median+P10/P90 maps, arrival median+range at every POI, and per-output confidence.
  `to_contract_response()` assembles a `FloodQueryResponse` dict (`docs/handoff_contract.md` §5.4).
  `peak_discharge_m3s` is honestly reported as a null-valued placeholder Estimate — it's an M2
  output, not one this emulator predicts, and CLAUDE.md rule 3 forbids inventing it.
- Scope decisions made without asking further (all previously flagged to the user before coding):
  `get_flood()` takes an already-fitted `FloodEmulator`, not a `site_id` (no on-disk site→emulator
  loading convention exists yet); unknown-breach mode's default sampling ranges are the emulator's
  own trained design box (`InputSpec.low/high`, already the widened M2 pair bounds per §2), with an
  optional `ranges=` override for a caller that has the real unwidened M2 range; resolving the
  request contract's `{type: exact | slider}` wrappers is left to a future M0/site-config session.
- Found and fixed a pre-existing bug while running the full suite: `test_loocv.py`'s
  `FloodEmulator.fit` monkeypatch restored the *bare* function instead of `classmethod(...)`,
  breaking every `FloodEmulator.fit()` call in test modules that ran after it in the same session.
- Tests: `tests/m5_emulator/{test_confidence,test_monte_carlo,test_query}.py` — 65 new, plus a shared
  `conftest.py` fixture (fits on `synthetic.small_grid()`, matching `test_emulator.py`'s existing
  convention — a coarser custom grid was tried first and rejected because `poi_cell_index`'s
  centreline convention falls outside the corridor mask at coarse resolution in the gorge). Every
  `to_contract_response()` output validates against `flood_query_response.schema.json`. Timing:
  scenario mode on `synthetic.small_grid()` (500k cells) — **~0.03 s**, well under the 3 s ask;
  unknown_breach mode, 2000 samples on the same grid — **~13 s**, under spec's own 60 s target (A7) —
  the 3 s ask is only realistic for a single analytic scenario prediction, not a full per-cell Monte
  Carlo histogram over a ~118k-cell corridor. `pytest -q`: **476 passed** (65 new + 1 pre-existing
  bug fixed; full project suite, no regressions).

**Out of scope this session, left for next:** wiring `get_flood()`/`fallback.py` into
`backend.m0_api` (still fully mocked), A6/A8 acceptance-test wiring in `loocv.py` (the confidence
rule now exists but isn't plugged into `run_acceptance()` yet), and the real
`design/scenario_design.json`.

## Session: M5 empirical fallback (`backend/m5_emulator/fallback.py`)

- Implemented the fallback for sites without a trained emulator (`docs/handoff_contract.md` §4.6:
  `method: "empirical_fallback"`, confidence always LOW): `route_discharge` takes M2's
  `peak_q_m3s` and routes it along the centreline with **no attenuation** (a deliberate,
  documented simplification — conservative rather than an invented decay coefficient);
  `channel_top_width_m`/`channel_roughness` read a per-cross-section active-channel width and
  Manning's n off the HAND/roughness rasters (HAND ≤ 2 m = "in channel", a fallback-only method
  parameter, not a sourced fact); `manning_normal_depth`/`manning_velocity` solve Manning's
  equation for a wide rectangular channel; cells flood where HAND < that station's depth
  (`run_empirical_fallback`); arrival comes from a kinematic-wave celerity `c = (5/3) v`
  (standard open-channel hydraulics, not one of `docs/Equations.md`'s breach equations — cited
  in the docstring instead, per CLAUDE.md rule 4's spirit). `to_contract_response()` mirrors
  `query.py`'s shape with `method: "empirical_fallback"` and the `empirical_fallback` +
  `clear_water` caveats.
- M1 (`backend/m1_terrain`) doesn't exist yet, so `hand.tif`/`roughness.tif`/`chainage_samples.csv`
  don't either (CLAUDE.md rule 2: every module needs synthetic-data tests before real data
  exists). Added `synthetic_fallback_terrain()`: a HAND/roughness/bed-elevation stand-in built
  from the same 40 km valley geometry as `synthetic.py` (§7.1) but **not** through
  `synthetic_flood_maps` — the fallback is tested against terrain alone, never against the
  emulator's own "true" answer for the same scenario.
- Confidence: always LOW with `reason_key: "conf_empirical_fallback"`, via
  `confidence.combine(..., empirical_fallback=True)` — had to pass `query_coverage="INSIDE"`
  (not `"OUTSIDE"`) as the dummy placeholder, since `combine` checks literal `"OUTSIDE"` before
  the `empirical_fallback` flag and would otherwise report the wrong reason (`conf_extrapolation`).
- Contract note: `flood_query_response.schema.json`'s `summary.first_arrival.poi_id`/`.name` are
  non-nullable strings, so `to_contract_response()` needs at least one POI to validate on a wet
  result — added an optional `pois=` param (same `name -> flattened cell index` convention as
  `query.get_flood`). `query.py`'s own `to_contract_response()` has the same latent gap (returns
  `None` when no POI ever arrives); not fixed here, out of scope for this session.
- Tests: `tests/m5_emulator/test_fallback.py` — 18 new, covering each equation in isolation
  (routing is constant with chainage, Manning depth grows with discharge/shrinks with slope,
  celerity floors at a minimum, arrival is monotonic downstream and offsets correctly),
  `run_empirical_fallback`'s flood/dry boundary and discharge monotonicity on the synthetic
  valley, and `to_contract_response()` validating against the schema. `pytest -q`: **494 passed**
  (full project suite, no regressions).

## 2026-09-25 — Timeline (`GET /flood/{query_id}/timeline`, contract §5.5, route #13)

- Contract amendment (user-approved): `timeline.schema.json`/`docs/handoff_contract.md` §5.5
  gained `t_end_s`, `caveats`, `provenance` (required, matching `hydrograph_sidecar.schema.json`'s
  pattern via `common.schema.json`'s `Caveat`/`Provenance` defs); `arrival_profile[].arrival_p10_s`/
  `.arrival_p90_s` may now be `null` ("that percentile never arrives within `t_end_s`"); a chainage
  row is omitted entirely if even the median never arrives. `contracts/examples/timeline.example.json`
  updated to match.
- `monte_carlo.py`: `HISTOGRAM_OUTPUTS` now includes `"arrival_time"` (was POI-only), so
  `unknown_breach` mode gets a full-grid arrival map too. Its bin edges run `[0, t_end_s*64/63)`,
  reserving the top bin for "never arrived" (a sample whose depth never exceeds `arrival_m` is
  recorded as exactly `t_end_s`) — trades that bin's resolution (`t_end_s/63`) for telling "arrives
  very late" from "doesn't arrive" without a second accumulator.
- `query.py`: both modes now gate each arrival band (median/P10/P90) by *that band's own* depth
  (previously scenario mode gated all three arrival bands by the median depth only, hiding arrival
  at POSSIBLE cells outside the median-wet area). `unknown_breach` mode reads arrival percentiles
  off the new histogram, treating a percentile near the top ("never arrived") bin as nodata via a
  half-bin-width tolerance (floating-point-safe, not an exact `== t_end_s` check).
  `to_contract_response()` no longer skips the `arrival_p*` layers for `unknown_breach`.
- New `backend/m5_emulator/timeline.py` (pure numpy + one file-writing entry point):
  `frame_times()` (default 5 min interval, capped at `t_end_s`), `frame_arrays()` (median/HIGH/
  POSSIBLE per contract §5.5's "extent at time t = cells whose arrival <= t"; HIGH gates on P90
  arrival, POSSIBLE on P10 arrival and not-already-HIGH — the two partition the final `extent_class`
  exactly at `t = t_end_s`), `arrival_profile()`, `pois_on_profile()`, `hydrograph_series()` (from
  `m2_breach.Hydrograph`), and `write_timeline_inputs()` (writes `timeline/{arrival_p10,arrival_p50,
  arrival_p90,extent_class}.tif` + `timeline_data.json`, everything a `Timeline` needs except the
  `interval_s`-dependent frame list, which M0 builds per request since the rasters don't change
  with it). `synthetic.py` gained `centreline_samples()` (public wrapper on `_chainage_and_offset`,
  same convention as `poi_cell_index`) standing in for the real, not-yet-built `chainage_samples.csv`.
- New `backend/m0_api/timeline.py`: `find_query_timeline_dir()`, `build_response()` (assembles the
  `Timeline` dict with frame URLs), `render_frame()` (renders one band at one `t_s` via
  `rendering.render_layer_png`, cached beside the source rasters like `render_and_cache`). Wired
  into `main.py`'s route #13 (`interval_s` query param, default 300 s, range [60, 86400], 422 above
  500 frames) and route #22 (`/files/{path}`) via a strict anchored regex
  (`TIMELINE_FRAME_PATH_RE`) matching only `<site>/queries/<query_id>/timeline/{band}_t<t>.png` —
  falls through to the existing mock behaviour for every other path or when no query has been
  written yet.
- Known gap (out of scope this session, flagged in `backend/m5_emulator/__init__.py`): nothing yet
  calls `write_timeline_inputs()` from a live `POST /flood/query` handler (still mocked); real M1
  `centreline.gpkg`/`chainage_samples.csv` don't exist, so real sites still need `synthetic.py`'s
  stand-in replaced once M1 lands.
- Tests: `tests/m5_emulator/test_timeline.py` (12 new — frame monotonicity, HIGH+POSSIBLE
  reproducing `extent_class` at `t_end_s`, arrival-profile ordering/null-handling, hydrograph
  round-trip, both modes' `write_timeline_inputs()` output validating against the schema) and
  `tests/m0_api/test_endpoints.py` (9 new — real timeline route with synthetic inputs written into
  `data_dir`, `interval_s` changing frame count, the 422s, frame PNG rendering/caching, mock
  fallback when nothing's written, and that a malformed `/files/...` path can't escape the regex).
  `pytest -q`: **514 passed** (full project suite, no regressions).

## 2026-09-25 — Compare "emulator vs physics" / "GP vs linear" (contract §5.6, route #15)

- No contract change needed this session: `compare.schema.json`/`.example.json` already had
  `emulator_vs_physics` (held-out LOOCV prediction vs physics, `iou`/`depth_rmse_wet_m`/
  `arrival_mae_s` + diff-map `layers`) and `gp_vs_linear` (aggregate GP-vs-linear-baseline medians)
  fully specified — `backend/m0_api/main.py`'s route just never read real data for them.
  User-confirmed scope: build against the synthetic test world (no real Delft3D/SPH run data
  exists yet, same as every other M5 module so far); precompute the one requested held-out fold's
  diff raster and write it to disk rather than refitting live on every request.
- New `backend/m5_emulator/compare.py`: `emulator_vs_physics_metrics()`/`gp_vs_linear_summary()`
  read `loocv.build_report()`'s per-run GP metrics and baseline aggregate medians back out in the
  Compare contract's shape (no new computation — LOOCV already scores every held-out run against
  both A1 baselines). `fit_and_diff_held_out()` fills the one real gap: LOOCV discards each fold's
  full-grid prediction array after scoring (CLAUDE.md rule 13), so it refits `FloodEmulator` on
  every run but the chosen one via the public `.fit()`/`.predict()` API (not `loocv.py`'s private
  fold internals) and returns `predicted_max_depth - true_max_depth`, reusing the existing
  `depth_diff` diverging style (`contracts/styles.json`) already used by `sph_vs_delft3d.layers` —
  no style/contract change needed for the diff map either. `write_compare_inputs()` writes
  `emulator/<model>/validation/compare/<held_out_run_id>__depth_diff.tif` +
  `<held_out_run_id>.json` (metrics, `gp_vs_linear`, `bounds_latlng`, a `synthetic_world_not_real_physics`
  caveat — same honesty pattern as `loocv.py`'s own report caveat).
- New `backend/m0_api/compare.py`: `find_compare_sidecar()` tries `f"{scenario_id}__{model}"` for
  `model in (delft3d, sph)` under `data/<site>/emulator/<model>/validation/compare/`; `build_response()`
  starts from the mock example (keeping `sph_vs_delft3d`/`when_to_use_key` mocked — no real SPH/
  Delft3D data, out of scope) and overwrites `emulator_vs_physics`/`gp_vs_linear` plus appends the
  sidecar's caveat; `render_diff_layer()` reuses `rendering.render_and_cache`. Wired into `main.py`'s
  route #15 (falls back to the existing full mock when no `scenario_id` is given or no sidecar has
  been written) and route #22 (`/files/{path}`) via a second strict anchored regex
  (`COMPARE_DIFF_PATH_RE`, run_id restricted to id-safe characters), alongside the Timeline one.
- Known gap (flagged in `backend/m5_emulator/__init__.py`, same shape as Timeline's): nothing yet
  calls `compare.write_compare_inputs()` from a live LOOCV run; real M3/M4 run data and a real
  `loocv.json` for an actual site don't exist yet either.
- Tests: `tests/m5_emulator/test_compare.py` (8 new — metrics extraction matches the right
  `per_run` row and returns `None` for an unknown run_id, `gp_vs_linear_summary` shape,
  `fit_and_diff_held_out` provably excludes the held-out run from training (`FloodEmulator.fit`
  spy) and returns a sane-shaped/signed diff array, `write_compare_inputs` output validating
  against `compare.schema.json` once merged into a full Compare-shaped dict) and
  `tests/m0_api/test_endpoints.py` (7 new — real compare route with a small synthetic LOOCV fold
  written into `data_dir`, `sph_vs_delft3d` staying mocked, mock fallback with no `scenario_id` and
  with an unwritten scenario, diff PNG rendering/caching, mock fallback for an unwritten diff PNG).
  `pytest -q`: **527 passed** (full project suite, no regressions).

## 2026-09-25 — M6: exposure download scripts (OSM + WorldPop)

`backend/m6_impact` was completely empty before this session (no files at all). Scope today was
narrow: the `exposure/` *inputs* the contract lists in §4.7 that come from public data (not
`impact.json`, warning tables, loss or exports — those need real M5 output first and are separate
work).

- Dev environment gap found and fixed: `.venv` had no `pip` at all and was missing `httpx`,
  `geopandas`, `shapely`, `fiona`, `scipy`, `scikit-learn`, `fastapi`, `jsonschema` and more,
  despite all being declared in `environment.yml`/`requirements.txt`. Bootstrapped pip
  (`get-pip.py`) and installed the missing packages so `pytest -q` runs clean again.
- New `backend/m6_impact/exposure_osm.py`: queries the public Overpass API for a site's
  `domains.far_field.bbox` and writes `buildings.gpkg` (`building=*`), `roads.gpkg` (`highway=*`),
  `facilities.gpkg` (`amenity=hospital|school` + bridges, one file with a `kind` column per the
  contract's `facilities.gpkg` schema) and `places.gpkg` (`place=city|town|village|hamlet`), each
  with `osm_id`, `kind`, `name` in EPSG:4326. Uses Overpass's `out geom;` so no separate node
  resolution is needed; OSM relations (multipolygon buildings) are NOT fetched — documented
  limitation. `overpass-api.de` returns 406 without a descriptive `User-Agent` and 504 under load
  for large Himalayan-valley bboxes — added a UA header and a retry-with-backoff (5 attempts) for
  502/503/504. Idempotent: an existing layer file is never re-queried.
- New `backend/m6_impact/exposure_worldpop.py`: WorldPop "Global 2000-2020, 1km, UN-adjusted"
  population counts for India (CC BY 4.0). Deliberately NOT the 100m "constrained" product
  (~530 MB and its server ignores HTTP Range requests, so no windowed/partial read is possible)
  — the 1km mosaic is ~18 MB and downloads whole in seconds; population is disaggregated uniformly
  within each ~1km source cell rather than by building footprint, an honest coarse approximation
  noted in `provenance.json`. National raster is cached once under `data/_cache/worldpop/` (shared
  across sites); each site clips it to its bbox into `data/<site_id>/raw/`, then
  `backend/shared/grid.build_farfield_grid` + `resample_to_grid(method="sum")` produce
  `exposure/population.tif` on the far-field grid, sum-preserving by construction (GDAL's `sum`
  resampling area-weights source-to-destination overlap). Idempotent on `population.tif`.
  Both scripts merge their results into one shared `exposure/provenance.json` (dataset, URL/query,
  license, fetched-at, feature/pixel counts) rather than overwriting each other's entries.
- Verified end-to-end for real against `sites/teesta.yaml` (far-field bbox, still all-placeholder
  coordinates per the file's own header — fine for exercising the pipeline, not for real results):
  292,504 buildings, 41,205 roads, 2,387 facilities (2,180 bridges, 140 schools, 67 hospitals),
  279 places, and population resampling that preserved the total exactly (3,099,432.5 persons
  before and after, on the real WorldPop raster). Reran both scripts a second time to confirm every
  file is skipped (no re-download) once present.
- Tests (`tests/m6_impact/`, 23 new, all offline/mocked — no real network calls in CI): Overpass
  element-to-row parsing (buildings/roads/facilities/places tag filtering, relations dropped, short
  ways dropped), `fetch_category` GPKG output shape + skip-existing, provenance merging (including
  that a skip-existing rerun must not clobber the richer provenance entry from the original fetch —
  found and fixed while writing this test); WorldPop URL construction, bbox clipping, sum-preserving
  resample onto a synthetic far-field grid (reusing `tests/fixtures/shared/synth.yaml`), `fetch()`
  skip-existing and placeholder-bbox rejection. `pytest -q`: **550 passed** (full project suite, no
  regressions).
- Not done yet (left for a future M6 session): `hydropower.gpkg` (hand-made, needs a `source`),
  `damage_curves.csv`/`asset_values.csv`, and all of `impact.json` computation / warning table /
  loss / exports — none of today's scripts touch those.

## 2026-09-25 — M6: loss estimation from JRC depth-damage functions

`loss_inr` (`docs/handoff_contract.md` §4.7), scoped to buildings and roads. New:
- `config/impact.yaml`: loss defaults — JRC region/country, depth cap, OSM building→JRC class
  map, and three `SourcedValue`-shaped placeholders (EUR→INR rate, 2010→current price index,
  default road width) that must be filled in before real INR numbers appear.
- `backend/m6_impact/jrc_damage.py`: extracts `damage_curves.csv` (ASIA depth-damage fractions)
  and `asset_values.csv` (India max-damage values, cited by exact sheet/cell) from the JRC
  workbook the user provided (`data/copy_of_global_flood_depth-damage_functions__30102017.xlsx`,
  gitignored — Huizinga et al. 2017, `docs/data_sources.md` src_031/src_032). Verified end to end
  against the real workbook and against `sites/teesta.yaml`'s real OSM exposure data (292,504
  buildings): CSVs generate correctly, cite real cells (e.g. residential India = 212.78 €/m² at
  `'MaxDamage-Residential'!D90`), and `estimate_loss` on the full far-field grid (5016x2534
  cells) completes in ~22s.
- `backend/m6_impact/loss.py`: `damage_fraction` (interpolated JRC curve, capped at 6 m),
  `building_losses`/`road_losses` (footprint-centroid / densified-line depth sampling),
  `estimate_loss` (the top-level `loss_inr` Estimate + `by_asset_class` + `assumptions`). Every
  number that depends on the FX rate, price index or road width comes back as a null Estimate
  while those stay `status: placeholder` — never an invented conversion (CLAUDE.md rule 3).
  Hospitals/schools/bridges (points, no footprint) and agriculture (no cropland layer) are
  explicitly not priced, named in `assumptions` every time.
- Contract change, logged in `docs/decisions.md`: `asset_values.csv` gains additive
  `value_eur2010`/`jrc_cell` columns so every INR figure is re-derivable, not opaque.
- Tests (`tests/m6_impact/test_jrc_damage.py`, `test_loss.py`, 47 new): extraction against a
  mini workbook replicating the real layout plus one test (skipped when the gitignored real
  workbook is absent) that checks the cited cell against the actual JRC figures; damage-fraction
  interpolation/capping; building/road loss pricing (hand-computed expected values, dry/excluded
  buildings, unmapped-kind fallback, placeholder FX/width → null); a stale-CSV staleness check;
  `estimate_loss` P10≤P50≤P90 ordering; and a schema-validation test that splices a real
  `loss_inr` into `contracts/examples/impact.example.json` and validates it against
  `impact.schema.json`. `pytest -q`: **574 passed** (full project suite, no regressions).
- Docs: `docs/impact_outputs.md` §5 "Loss estimation" (every default with its Why, new
  acceptance checks I6-I9); `docs/data_sources.md` (previously empty) now has src_031/src_032;
  `docs/decisions.md` dated entry.
- Not done yet: the EUR→INR rate and price index need a team decision (RBI reference rate;
  CPWD cost index or WPI) before `loss_inr` reports real numbers; road widths by highway class;
  `hydropower.gpkg`; the rest of `impact.json` (`population_persons`, `assets`, `warning_table`,
  exports) — this session only added `loss_inr`.

## 2026-09-25 — M1 kickoff: site config vs contract resolved (0.2.0), M1-1 download.py

Session started to work on `backend/m1_terrain` (found empty, no code, no tests) and found no DEM
files anywhere in the repo or the sites config. Before writing anything DEM-related, resolved the
long-pending `docs/decisions.md` (2026-09-24) "site config schema: YAML v1 vs contract §3.1" split,
per user instruction, then built M1-1.

**Contract 0.2.0** (`docs/decisions.md` 2026-09-25 has the full list): `sites/*.yaml` +
`backend/shared/site_config.py` kept as canonical; `docs/handoff_contract.md` §1.7/§3/§4.1/§4.2/
§5.1/§5.2 rewritten to match, `contract_version` bumped everywhere (doc, `contracts/examples/*`,
`CONTRACT_VERSION` constants in 7 backend modules, FastAPI app version). New `Dam.initial_water_level`
field (was in the 0.1.0 draft, had no home in code). `sites/teesta.yaml`: `crs.utm_epsg` flipped to
`sourced` (it's a derivation from the bbox, not a DEM-dependent lookup); both dams got explicit
`equations_applicable: true` and a `volume_elevation` placeholder block; `teesta_iii` got
`initial_water_level` (placeholder). Generated `contracts/schemas/site_config.schema.json` straight
from `SiteConfig.model_json_schema()` and wired it into `site_create_request.schema.json` — this
caught and fixed a real bug in `backend/m0_api/main.py`'s `create_site` (`site_config.get("site_id")`,
the never-valid 0.1.0-draft key; now reads `site_config["site"]["id"]`). Two known bugs logged but
*not* fixed this session (out of scope): M2 writes a bare `dam_id` instead of the derived
`<site_id>__<slug>` form; M5 builds `poi_id` from a POI's `name` instead of its `id`.
`pytest -q` (excluding `tests/m6_impact`, which needs `geopandas`/`shapely` not installed in this
sandbox — pre-existing environment gap, unrelated): **555 passed**.

**M1-1** (`backend/m1_terrain/download.py`, new module): fetches DEM/landcover *candidates* for a
site's far-field bbox into `data/<site_id>/raw/` — SRTM GL1 and Copernicus GLO-30 via the
OpenTopography Global DEM API (`OPENTOPOGRAPHY_API_KEY` from `.env`), ESA WorldCover 10 m v200
mosaicked from its public S3 COG tiles (no key), and CartoDEM mosaicked from a folder of manually
downloaded tiles (no public bulk API). Deliberately does **not** choose a DEM — that's the M1-2
comparison report, still to come, and the site config has no `dem.source` field for the same
reason. Per-product `provenance.json` (dataset, source id, request bbox, native CRS/resolution/
vertical datum, licence, sha256, fetch time); the API key is never written to provenance or
included in a raised error. 23 new tests (`tests/m1_terrain/test_download.py`), all synthetic —
OpenTopography via `httpx.MockTransport`, WorldCover/CartoDEM mosaicked from small local GeoTIFFs —
no real network calls, no API key spent. Added `docs/data_sources.md` src_033–src_037; **the DOIs
for src_033/src_034/src_036 were written from memory this session and need verifying** before
anything cites them as `status: sourced`.

**Not done yet:** the actual download hasn't been run (no API key spent, per user instruction — the
user runs it). M1-2 (reproject each downloaded DEM onto the canonical grid, build the comparison
report: void % per DEM, pairwise difference maps, valley-centreline elevation profiles, summary
stats) is next, once real DEMs exist in `data/teesta/raw/`. The rest of M1 (`landcover.tif` →
Manning's n, `hand.tif`, `domain_mask.tif`/`domain.gpkg`, `centreline.gpkg`, `chainage_samples.csv`,
`pois.gpkg`, near-field STL) hasn't been started.

## 2026-09-25 — M1 terrain pipeline built end to end

Implemented the rest of `backend/m1_terrain` (M1-1 `download.py` already existed): DEM/landcover
loading + void fill, lake/reservoir extent, dam-crest + reservoir burn-in, flow routing, centreline
+ chainage + POIs, roughness, valley-corridor domain, near-field STL, and the `pipeline.py` that
wires them into `data/<site_id>/terrain/` (`docs/handoff_contract.md` §4.1). Decisions made with
the user before coding, logged in `docs/decisions.md` 2026-09-25 "M1 terrain pipeline: settings,
Manning table path, water extent, flow routing":

- **Manning table**: `config/manning_n.csv` (real column names), not the contract's originally
  documented `data/manning_table.csv` — contract updated to match. Every row is
  `status: placeholder` (Chow 1959 proxies), so `roughness.tif` always sets `has_placeholders`.
- **Lake/reservoir extent**: ESA WorldCover's water class, restricted to the component within
  `snap_radius_m` of each dam's `location`. New output `water_mask.tif`, added to the contract.
- **Flow routing**: our own numpy/heapq priority-flood (Barnes et al. 2014) + an implicit D8
  drainage tree + flow accumulation — `richdem` (CLAUDE.md's Stack) has no wheel for this
  environment's Python 3.12/numpy 2.5. `hydro.py`'s docstring explains the method; HAND is a
  single linear pass over the flood's visit order.
- **Domain**: `TerrainSettings.domain_max_hand_m = 50` (m) default, a CLI-overridable setting, not
  a site fact.
- **DEM product**: `pipeline.py --dem` is required, no default — still the M1-2 comparison
  report's job to choose.

New modules: `settings.py`, `dem.py`, `water.py`, `burn.py`, `hydro.py`, `centreline.py`,
`roughness.py`, `domain.py`, `stl.py` (hand-written binary STL, no `numpy-stl` dependency),
`pipeline.py` (the orchestrator + CLI). `contracts/schemas/` was **not** extended with new schemas
for `grid.json`/`nearfield_frame.json`/`provenance.json` as the original plan suggested —
`contracts/README.md` scopes that directory to API request/response payloads generated from §4/§5,
and these are internal pipeline files documented in §4.1 prose instead; `backend/shared/grid.py`'s
`CanonicalGrid` pydantic model already validates `grid.json`'s shape.

Tests: `tests/m1_terrain/synthetic_valley.py` builds a raw synthetic DEM/landcover pair from
closed-form V-valley geometry (known down-valley/side slopes, a lake and a reservoir bowl of known
radius/depth, a nodata void patch) over `tests/fixtures/shared/synth.yaml`'s bbox; `conftest.py`
adds a second (embankment) dam fixture for reservoir tests. 61 new tests across 9 files (dem,
water+burn, hydro, centreline, roughness, domain, stl, pipeline end-to-end) — all synthetic, no
real DEM needed. Found and fixed one real bug while writing `test_dem.py`:
`rasterio.fill.fillnodata` mutates its `image` argument in place, so `dem.fill_voids` now copies
before calling it. `pytest -q` (full project): **640 passed**, no regressions.

Smoke-tested on real Teesta data (`data/teesta/raw/`, already downloaded): far-field grid is
5016x2534 (30 m), near-field 1011x906 (10 m) — run in the background, see the next session's notes
for runtime/memory and whether the centreline/HAND/domain look sane on the real DEM.

Not done yet: M1-2 (the DEM comparison report that should choose SRTM vs Copernicus vs CartoDEM)
is still unwritten — this session's pipeline just takes `--dem <product>` as given. `sites/
teesta.yaml`'s placeholder dam locations/heights (illustrative, not surveyed) mean a real Teesta
terrain run has `has_placeholders: true` and shouldn't be treated as final.

**Teesta smoke-test results** (real DEM, `--dem copernicus_glo30`): 1m41s wall clock, 1.6 GB peak
RSS, single-threaded — well inside the RTX 4060/16 GB RAM budget, and fine for an offline M1 run.
The centreline (6506 cells, ~239 km total chainage to the grid edge) snapped all 14 POIs in the
**correct real-world downstream order** — Chungthang → Mangan → Teesta V/Dikchu → Singtam → Rangpo
→ Teesta Bazaar → Teesta Low Dam IV → Coronation Bridge → Teesta Barrage — with most
`dist_to_channel_m` in the tens-to-hundreds-of-metres range, a strong sanity check that the D8
routing tracks the real Teesta channel, not just the synthetic valley. South Lhonak's crest burned
in (193 cells raised, 33 cells long); `teesta_iii`'s reservoir wasn't found by the WorldCover
water-mask search (`teesta.yaml`'s dam locations are illustrative placeholders, not surveyed) and
its crest search found no cells needing raising — both expected given placeholder inputs, and both
recorded in `provenance.json` rather than silently skipped.

## 2026-09-25 — M7 GEE fetch built end to end (contract §4.8)

Built `backend/m7_gee/{settings,lake_area,provider,rainfall,recheck,cache,fetch}.py` on top of the
existing `scene_search.py`. Real files now land at `data/<site_id>/gee/`: `lake_area.csv`,
`lake_latest.geojson`, `rainfall.csv`, `gee_meta.json`, `recheck.json`. Out of scope this session:
event imagery PNG/TIF, `observed/*.geojson` (manual digitising), and wiring M0's `GET/POST
/gee/{site_id}` (still mocks) to this cache. Full reasoning in `docs/decisions.md` "M7 GEE fetch".

- Method: Otsu threshold per monthly Sentinel-2 NDWI composite (clamped to a sane range), falling
  back to Sentinel-1 VV when too cloudy, skipped outright when the SCL snow/ice class says the lake
  is frozen. A connected-components labelling seeded at the dam's `location` keeps only the lake's
  own component, dropping SAR shadow and unrelated water in the AOI buffer.
  `lake_area.otsu_threshold`'s tie-break (middle of a run of equal-variance thresholds, not the
  first) matters in practice: a well-separated bimodal histogram has many empty bins between the
  clusters, and picking the first tied index put the threshold at the edge of the gap instead of
  its centre.
- Rainfall catchment: HydroBASINS level 12 (`WWF/HydroSHEDS/v1/Basins/hybas_12`), walked upstream
  via `NEXT_DOWN` (`provider.walk_upstream_basin_ids`) — no basin polygon exists anywhere else in
  the repo. Its own unit test (`tests/m7_gee/test_provider.py`) caught a real bug: a diamond-shaped
  drainage graph (two basins both draining into a third further upstream) produced a duplicate ID
  in the walk, because only cross-batch de-duplication was checked, not within-batch. Fixed with
  `dict.fromkeys`.
- `recheck.json`'s reference area comes from the trained emulator's `manifest.json` `trained_at`
  (`backend/m5_emulator/emulator.py`), not an arbitrary baseline; an untrained site reports
  `outdated: false, reason: "no_trained_library"` rather than guessing.
- Widened `contracts/schemas/gee_layers.schema.json`'s `recheck.change_pct` to allow `null`
  (additive, documented in decisions.md) so `cache.load_layers()` can represent "no trained library
  yet" honestly instead of inventing a 0.
- Added `docs/data_sources.md` src_038–041 (Sentinel-2 SR, Sentinel-1 GRD, CHIRPS, HydroBASINS),
  DOIs verified by web search this session (CHIRPS: Funk et al. 2015, doi 10.1038/sdata.2015.66;
  HydroBASINS: Lehner & Grill 2013, doi 10.1002/hyp.9740), same "verify before `status: sourced`"
  caveat as src_033/034 for the ones with a real DOI.
- Tests: 73 in `tests/m7_gee/` (up from 8), all synthetic (CLAUDE.md rule 2) — a
  `provider.SyntheticProvider` (shrinking disc lake, cloudy/icy/missing months, flat rainfall)
  drives `fetch.run()` end to end. `EarthEngineProvider`'s actual `computePixels`/HydroBASINS/CHIRPS
  calls are untested beyond request-shape checks; **not yet run against live Earth Engine** — the
  next session (or whoever has EE credentials) should run `python -m backend.m7_gee.fetch teesta
  --months 24 --ee-project <proj>` and sanity-check the output against the known Oct 2023 South
  Lhonak drainage (lake area should drop sharply across that month).
- Full `pytest -q`: 713 passed (640 before this session), nothing else broken.

## 2026-09-25 — M7 GEE event imagery + wiring the real `/gee` endpoints

Picked up the "out of scope" leftovers named at the top of the previous M7 session: event
imagery, `observed/*.geojson`, and wiring `backend/m0_api/main.py`'s real `GET/POST /gee`. Dropped
observed-extent work this session (`data/teesta/observed/flood_extent_2023.geojson` doesn't exist
yet — confirmed with the user, revisit once the digitized file exists).

- **New `backend/m7_gee/imagery.py`**: converts the pre-/post-event RGB GeoTIFFs an operator has
  already staged (`sites/<site_id>.yaml` `events[].imagery_pre_event/imagery_post_event.source`,
  e.g. `cache/gee/teesta/teesta_pre_event.tif` → its `..._rgb.tif` sibling) into
  `data/<site_id>/gee/imagery/`: full-res PNG, a ≤512px fallback PNG (`_fallback.png`, for slow
  connections — a *different* concept from contract §4.8's `fallback/*.png` "screenshots when live
  and cache both fail", deliberately kept in a separate location/naming so it doesn't trip
  `cache.fallback_screenshots()`'s `source: screenshot_fallback` logic), and a `manifest.json`
  recording each PNG's EPSG:4326 bounds. `cache.read_imagery()`/`load_layers()` read the manifest
  into `GeeLayers.imagery` (contract §5.8; `fallback_url` added per entry — the schema doesn't
  constrain `imagery`'s item shape, so this is additive, not a contract change).
  - Ran it for real against `cache/gee/teesta/*_rgb.tif`: wrote
    `data/teesta/gee/imagery/sikkim_glof_2023_{pre,post}_2023{0928,1006}{,_fallback}.png` +
    manifest (event id/dates from `sites/teesta.yaml` — `sikkim_glof_2023`, not the
    `teesta_2023` placeholder still in `contracts/examples/gee_layers.example.json`).
- **New `backend/m7_gee/live_render.py`**: best-effort live re-render of the same pre-/post-event
  composite from Sentinel-2 (least-cloudy scene within ±15 days of the event date, near-field AOI),
  overwriting the staged `_rgb.tif`. Called by `imagery.refresh()`; any failure (no credentials, no
  network, no usable scene) is caught and the existing cached PNGs are kept — same fallback
  contract as `fetch.run()`. **Untested against real Earth Engine** — no service-account key exists
  yet (see below); like `provider.EarthEngineProvider`, only its request-shape is implicitly
  exercised via the type signature, not a real `computePixels` call.
- **`scene_search._ee_initialize`** now also accepts a service account: `GEE_SERVICE_ACCOUNT_EMAIL`
  / `GEE_SERVICE_ACCOUNT_KEY_PATH` from the environment or repo `.env` (same lookup pattern as
  `m1_terrain.download.opentopography_api_key` — never logs the key file's contents, only its
  path). Falls back to the existing `ee.Initialize(project=...)` flow when neither is set. Neither
  var is in `.env` yet — wired up ahead of the key existing, per user decision this session.
- **`backend/m0_api/main.py`**: `GET /gee/{site_id}` now serves `gee_cache.load_layers()` once
  `gee_meta.json` exists for the site (i.e., `fetch.run` has actually run at least once);
  otherwise still falls back to the contract mock, same as every other not-yet-real endpoint.
  `POST /gee/{site_id}/refresh` tries `_ee_initialize` + `EarthEngineProvider`, falls back to
  `gee_fetch._CacheOnlyProvider` on any init failure, runs `gee_fetch.run` + `gee_imagery.refresh`,
  and reports `source: live` only if both actually succeeded live — never 500s over a live-fetch
  problem (only over `site_id` not being configured). Added `GEE_IMAGERY_PATH_RE` to `GET
  /files/{path}` to serve the new `gee/imagery/*.png` files for real, 404ing by name if a specific
  file is missing (never silently falling through to a mock PNG for a path that matches this
  pattern).
  - Ran `fetch.run("teesta")` once for real (no live EE — fell back to cache as designed) so
    `gee_meta.json` exists and `GET /gee/teesta` now serves the real imagery end to end; verified
    over HTTP with `uvicorn` (`curl .../api/v1/gee/teesta`, `curl .../files/teesta/gee/imagery/....png`
    → 200 image/png; a nonexistent filename → 404 naming the exact path).
- Treated the pasted `?refresh=true` request as the contract's existing `POST
  /gee/{site_id}/refresh` (§5 row 20) rather than adding a query param to `GET` — same behaviour,
  already on record; flagged to the user rather than silently deviating either way.
- Tests: new `tests/m7_gee/test_imagery.py` (9 tests, synthetic GeoTIFFs, no EE), plus
  `TestEeInitialize` in `test_scene_search.py` (3 tests for the service-account credential path,
  `fake_ee.FakeEE` extended with `ServiceAccountCredentials`/`Initialize(credentials=...)`), plus
  `cache.py` imagery-wiring tests. Full `pytest -q`: 727 passed (713 before this session).

## 2026-09-25 — M7: real Teesta imagery re-export, scene IDs, observed-extent loader

User exported real pre-/post-event Sentinel-2 GeoTIFFs for Teesta from Earth Engine into
`cache/gee/teesta/` (`COPERNICUS/S2_SR_HARMONIZED/20230926T.../20231026T...`, near-field AOI,
EPSG:32645, 10 m) and asked to wire them through, plus load a hand-digitized flood outline as the
observed-extent layer. See `docs/decisions.md` "M7: recording scene IDs, observed-extent loader"
for the scene-ID-placement decision and the observed-extent scope decision, both made with the
user before coding.

- **`sites/teesta.yaml`**: `events[0].imagery_pre_event/post_event.value` corrected to the real
  scene acquisition dates (`2023-09-26`/`2023-10-26`; were `2023-09-28`/`2023-10-06`, an earlier
  arbitrary pick). `source` unchanged (already pointed at the right `cache/gee/teesta/
  teesta_{pre,post}_event.tif` files).
- **`backend/m7_gee/imagery.py`**: `convert()` now takes optional `scene_ids={"pre": [...],
  "post": [...]}` and merges an `"imagery"` entry into `gee_meta.json` (dataset, scene_ids,
  acquisition_dates, source) — the contract's per-product meta entry for imagery had never
  actually been written before (only `lake_area`/`lake_latest`/`rainfall` were, both this session
  and last). New CLI flags `--pre-scene-id`/`--post-scene-id` (repeatable).
  - Ran for real: `python -m backend.m7_gee.imagery teesta --pre-scene-id
    COPERNICUS/S2_SR_HARMONIZED/20230926T043709_20230926T045046_T45RXL --post-scene-id
    COPERNICUS/S2_SR_HARMONIZED/20231026T043849_20231026T044734_T45RXL`. Wrote
    `sikkim_glof_2023_{pre,post}_202309{26},202310{26}{,_fallback}.png` + manifest +
    `gee_meta.json` `imagery` entry; deleted the now-orphaned `_20230928`/`_20231006` PNGs from the
    earlier arbitrary dates. Verified `cache.load_layers("teesta")` end to end (source: cache,
    imagery URLs point at the new files, validates against `gee_layers.schema.json`).
- **New `backend/m7_gee/observed.py`**: `convert(site_id, event_id, source_geojson,
  digitized_by, method=..., imagery_ref=..., date=...)` stamps contract §4.8's required properties
  (`event_id, method, imagery_ref, digitized_by, date, kind: observed`) onto an operator-supplied
  GeoJSON and writes `data/<site_id>/gee/observed/<event_id>_observed.geojson`.
  `cache.read_observed_extents()` (new) reads every file in `gee/observed/` into
  `GeeLayers.observed_extents` (was hardcoded `[]` in `load_layers()`). `backend/m0_api/main.py`
  `GET /files/{path}` now serves `gee/observed/*_observed.geojson` for real
  (`GEE_OBSERVED_PATH_RE`, same anchored-regex pattern as the imagery PNG route).
  - **Not run against real data**: `data/teesta/observed/flood_extent_2023.geojson` (the
    hand-digitized outline described this session) does not exist on disk yet — same blocker as
    last session. Built and tested against a synthetic GeoJSON fixture only, per the user's
    explicit choice. Once the file exists: `python -m backend.m7_gee.observed teesta
    sikkim_glof_2023 data/teesta/observed/flood_extent_2023.geojson --digitized-by <name>`.
- Tests: new `tests/m7_gee/test_observed.py` (9 tests), 3 new cases in `test_imagery.py`
  (scene-ID → `gee_meta.json` merge), 2 new cases in `test_cache.py`
  (`read_observed_extents`/`load_layers` wiring). **Could not run the full `pytest -q`** — this
  session's shell has no active conda env; system `python3` lacks `shapely`, so `lake_area.py`
  (imported by `fetch.py`, imported by `m0_api.main`) fails to import, breaking collection of
  `test_fetch.py`, `test_lake_area.py`, `test_provider.py`, and all of `tests/m0_api`. Ran what
  could run: `tests/m7_gee/test_imagery.py`, `test_observed.py`, `test_cache.py` — all pass (34
  tests). Manually verified `GeeLayers` schema validation and the `GET /gee/teesta` code path by
  calling `cache.load_layers()` directly. **Next session (with the real `sih26` env): run full
  `pytest -q` to confirm nothing broke.**

## 2026-09-25 — M0: scheduled site re-checks (lake-area + library-age)

Summarised existing `backend/m0_api` state first: the job system (`registry`/`jobs`/`worker`) is
real, but `GET /sites`, `PUT /sites/{id}/recheck` and `POST /sites/{id}/rerun` were pure mocks —
no persistence, and nothing ever created a `recheck` job even though `jobs.STAGES["recheck"]`
already existed. Found three real, unresolved design questions before writing anything (registry
§4.5's frozen table list has no `sites` table; docs/decisions.md open question #4 about a lapsed
re-check; `rerun` has no job stages defined) and got the user's decisions on all three — logged in
`docs/decisions.md` ("M0 scheduled site re-checks" this session).

Implemented:
- **`backend/m0_api/registry.py`**: `utc_now_dt()` — the one "now" the whole module now goes
  through (`utc_now()` formats it), so a fake-clock test only needs to monkeypatch one function.
- **New `backend/m0_api/site_status.py`**: `data/<site_id>/site_status.json` — `frequency_days`
  (default 90, contract §5.1's own example), `lake_area_change_threshold_pct` (default 10, matches
  `GeeSettings.recheck_threshold_pct`), `last_checked_at`/`next_check_at`, `outdated`,
  `status_reason_key`, `status_detail`. `set_frequency()` (recomputes `next_check_at` from the
  last check, not from now), `record_check()` (a completed re-check's result), `is_due()`,
  `overlay()` (patches a mocked `SiteSummary` with the real state).
- **`backend/m7_gee/fetch.py`**: extracted `best_effort_provider()` — try live Earth Engine, fall
  back to `_CacheOnlyProvider` — from what `POST /gee/{id}/refresh` did inline; now shared with
  the worker.
- **`backend/m0_api/worker.py`**: every `tick()`, `_schedule_rechecks()` queues a `recheck` job for
  any known site with a published library (`emulator/<model>/manifest.json` exists) and no active
  job, once its `site_status.json` schedule is due (or has never run) — no separate timer. The
  `checking` stage is now real for `kind == "recheck"` (`_run_recheck`): M7's lake-area check via
  `gee_fetch.run()`, reading back `gee/recheck.json`; if that's not outdated, a library-age check
  against `site_status.DEFAULT_MAX_LIBRARY_AGE_DAYS` (365 days, new engineering knob). Either
  outcome calls `site_status.record_check(...)`, which always advances the schedule.
- **`backend/m0_api/main.py`**: `GET /sites`/`GET /sites/{id}` overlay `site_status.overlay()` onto
  the mocked base response (same pattern as `_gee_layers_or_mock`); `PUT /sites/{id}/recheck` now
  really persists via `site_status.set_frequency()`; `POST /sites/{id}/rerun` now really queues a
  job — but an `onboarding`-kind one, honestly documented as not yet reusing terrain (that needs
  the still-undecided `rerun` stage list).
- Tests: new `tests/m0_api/test_site_status.py` (9 cases, fake clock via monkeypatching
  `registry.utc_now_dt`), new `tests/m0_api/test_recheck_scheduling.py` (9 cases: no job without a
  library, job queued when due, none when not due, no duplicate while one is active, lake-area vs.
  library-age triggers and their priority, and the "lapsed schedule alone never flags outdated"
  case from open question #4), plus new/extended cases in `tests/m0_api/test_endpoints.py` for the
  real `GET /sites`, `PUT /sites/{id}/recheck` and `POST /sites/{id}/rerun` behaviour.
- **Test environment**: installed `shapely` via `pip install --user --break-system-packages` (no
  `sih26` conda env available in this shell) so `tests/m0_api` and `tests/m7_gee` could collect at
  all. Ran the full `pytest -q` (minus `tests/m1_terrain`/`tests/m6_impact`, which need
  `geopandas`, not installed here — pre-existing gap, unrelated). 652 passed, 1 pre-existing
  failure: `tests/m0_api/test_endpoints.py::test_get_file_geojson` — confirmed via `git stash`
  that it already failed before this session's changes (the file it requests,
  `data/teesta/gee/observed/teesta_2023_observed.geojson`, was never written to disk; last
  session's own notes already flag `data/teesta/observed/flood_extent_2023.geojson` as missing).
  Left untouched — out of scope for this session, not introduced by it.

**Next session**: decide and implement real `rerun` job stages if "re-run reuses terrain" needs to
actually skip terrain; write `data/teesta/observed/flood_extent_2023.geojson` (or accept the
mismatch and fix `test_get_file_geojson`'s fixture) to clear the one remaining failing test.

## 2026-09-25 — M4: DualSPHysics near-field case generator (`backend/m4_sph/`)

Found `backend/m4_pilot/` holds only calibration logs (`vram_estimator.py` + three log files),
not a template case as the session brief assumed — the logs turned out to be from DualSPHysics
5.4.3's own stock `01_DamBreak/CaseDambreakVal2D` example, and the real install (with Linux
binaries) is at `/mnt/d/APPS/DualSPHysics_v5.4/` on this machine, not in the repo. Decisions
(inlet flow source, settings location, inlet geometry) recorded in `docs/decisions.md`
"M4 pilot case", 2026-09-25.

Built, in order (one commit each):
- `backend/m4_sph/case_xml.py`: a GenCase `_Def.xml` writer (constants, geometry, draw commands,
  inlet/outlet zones, gauges, parameters) plus `canonicalize()`/`diff_trees()` for comparing
  against a reference file. `generator.pilot_case_spec()` reproduces the pilot's calibration case
  and regenerating it matches the real `CaseDambreakVal2D_Def.xml` exactly
  (`tests/m4_sph/test_pilot_regen.py`).
- `backend/m4_sph/settings.py` + `config/m4_sph.yaml`: SPH numerical/solver settings
  (dp, time window, inlet size, VRAM budget), project-maintained, not a site fact.
- `generator.hydrograph_to_velocity()`: converts an M2 discharge hydrograph to a uniform inlet
  velocity over a fixed cross-section, mass-flux conserving.
- `backend/shared/probes.py` + `generator.build_nearfield_case()`/`write_case()`: ties together
  M1 terrain (`nearfield.stl`, `dem_nearfield.tif`, `centreline.gpkg`, `pois.gpkg`) and an M2
  hydrograph into a near-field GenCase, with the inlet placed at
  `domains.near_field.inflow.location` and oriented along the local channel tangent. Verified
  end-to-end against a synthetic V-shaped valley (real M1 pipeline output). `far_field` inflow
  (Teesta today) raises `InflowUnavailable` until M3 exists.
- `tests/m4_sph/test_gencase_smoke.py` (skipped unless `DSPH_BIN_DIR` is set): actually runs the
  real GenCase binary on both the pilot case and a generated 3D near-field case. This caught two
  bugs schema validation alone wouldn't have — `hswl` must be set explicitly (not `auto`) because
  the case starts with zero fluid particles, and boundary `mk` values must stay inside
  `mkconfig`'s declared `boundcount` — both fixed.

**Known gap, not yet verified**: whether the inlet's `rotateaxis` angle sign convention actually
points the imposed flow downstream (vs. upstream) needs visual inspection of a generated case in
a VTK viewer — out of scope this session; flagged in `InletGeometry`'s docstring and
`docs/decisions.md`.

**Out of scope this session** (per the approved plan): launching the solver as a job, post-
processing to `summary_nearfield/*.tif`/`timeseries.csv`/`surfaces/*.glb`, `run_meta.json`,
initial reservoir water, far-field inflow from M3, and `snap_pois`'s wrong return type
annotation.

**Next session**: visually verify the inlet rotation direction in a VTK viewer against a real
GenCase output; then M3 (Delft3D 4 FLOW) or M4 post-processing/job wiring.

## 2026-09-26 — D-Flow FM kernel built in WSL (M3 prep, before M3-B housekeeping)

- **Kernel works:** D-Flow FM 1.2.184 + DIMR 2.00 from the Deltares DIMRset 2026.01 source tarball,
  built unmodified with Intel oneAPI 2024.2 (ifort) + Intel MPI 2021.13. netcdf-fortran 4.6.1 and
  PETSc 3.21.3 were built from source with Intel. Install tree: `~/delft3d/dflowfm-2026.01/lnx64`.
  Full record, every command, and problems/fixes: `docs/dflowfm_kernel_build.md`.
- **Verified runs:** release example `01_dflowfm_sequential` (via `run_dimr.sh`) and D-Flow FM
  tutorial06 (Western Scheldt, 10 days, 3.5 min, 0 errors, `_map.nc` + `_his.nc`). The 2015 tutorial input
  needed 3 run-copy-only fixes (obsolete MDU keywords; `Discharge.bc` not covering t0..TStop).
- **Python tools:** hydrolib-core 1.4.0 / meshkernel 8.3.0 / dfm_tools 0.47.0 in a separate venv
  (`~/delft3d/fm-py-venv`). A hydrolib-written case ran on the kernel and dfm_tools read its output.
  For M3: hydrolib writes `.ext` v3.00, which the kernel ignores, so set `fileversion = "2.01"`. The run
  scripts exit 0 even when the kernel rejects the input, so M0/M3 must check the `.dia` and outputs.
- **Tried and dropped:** GNU (gfortran 13 + OpenMPI). ≥28 errors from Intel Fortran extensions; no
  patched Deltares source was kept.
- **Not done, on purpose:** `CLAUDE.md`, `docs/decisions.md` and `environment.yml` are unchanged
  (M3-B housekeeping). flow2d3d wasn't built (estimate in the build doc). `.wslconfig` is only
  proposed. No repo code changed and no tests added this session, so `pytest` wasn't rerun.

## 2026-09-25 — M4: post-processing (`summary_nearfield/`, `surfaces/`, `timeseries.csv`, `run_meta.json`)

Before starting: the user moved `backend/m4_pilot/`'s `vram_estimator.py` and its three
calibration logs straight into `backend/m4_sph/` (consolidating the pilot-calibration-only
folder into the real module). Fixed the fallout — `generator.py`'s import, `tests/m4_pilot/` ->
`tests/m4_sph/test_vram_estimator.py`, `CLAUDE.md` — all green before starting new work
(`docs/decisions.md` today's entry has the detail).

Added the rest of contract §4.4's M4 outputs, turning a completed near-field run into the same
schema a Delft3D run would produce:

- `backend/m4_sph/measuretool.py`: wraps `MeasureTool_linux64` for `summary_nearfield/`'s three
  rasters — column-collapsing `-elevation` search for depth/arrival, explicit multi-level points
  for depth-averaged velocity (`docs/decisions.md` "SPH velocity: depth-average, not a
  fixed-height point"). Every format detail (points-file syntax, CSV layout, the `-elevation`
  column-collapse threshold, `-kcdummy`'s actual no-op behaviour) was checked against the real
  binary on real pilot particle data, not assumed from `-h` text.
- `backend/m4_sph/gauges.py`: `timeseries.csv` from the solver's own `GaugesSWL_*.csv`/
  `GaugesVel_*.csv` (real-time gauges `generator.py` already places per probe) — no MeasureTool
  involved. Fixed a real bug this surfaced: `case_xml.py`'s `VelocityGauge` wrote `<vel>` instead
  of the real `<velocity>` tag, which would have silently produced no gauge output at all.
- `backend/m4_sph/vtk_polydata.py` + `gltf_writer.py`: a from-scratch legacy-VTK-binary reader and
  minimal `.glb` writer (no new dependency) for `surfaces/t<seconds>.glb`, converting
  `IsoSurface_linux64 -saveiso` output at `settings.surface_interval_s` (default 300 s) cadence.
- `backend/m4_sph/postprocess.py`: orchestrates all of the above into `run_meta.json` too, chunked
  by near-field grid row (`settings.postprocess_row_chunk`, CLAUDE.md rule 13). New caveats
  `sph_arrival_below_resolution` (always, since SPH particle spacing is far coarser than the
  0.1 m arrival threshold) and `sph_depth_search_capped` (if a cell's depth nears the search
  ceiling); added both plus `fixed_area_inlet` to the contract's standard caveat list (§2.4).
  `contracts/schemas/run_meta.schema.json` + example added (didn't exist before).
- Settings: `config/m4_sph.yaml` gained `elevation_dz_dp_fraction`, `velocity_levels`,
  `surface_interval_s`, `postprocess_row_chunk`. `elevation_dz_dp_fraction` (not a fixed metre
  value) exists because of a real bug caught mid-session: a flat `elevation_dz_m` silently broke
  MeasureTool's column collapsing on a coarser case (one output column per candidate instead of
  one per cell) — scaling the step with the case's own `dp_m` fixed it for any case, not just this
  one (`docs/decisions.md` has the full story).
- Every new module has offline unit tests (literal CSV/VTK fixtures) plus a real-binary
  integration test gated on `DSPH_BIN_DIR`, run against the shipped pilot dam-break particle data
  (already on disk — no solver run needed). All pass both with and without `DSPH_BIN_DIR` set.
- **Approved by the user this session, not yet implemented**: `/compare`'s `sph_vs_delft3d`
  section (still the all-zero mock), `velocity_diff`/`arrival_diff` styles, and making the mock's
  `available: true` become `available: false` when no run exists yet.

Full `m4_sph` suite: 70 passed with `DSPH_BIN_DIR` set (real binaries), 64 passed / 6 skipped
without it. Full repo suite green.
