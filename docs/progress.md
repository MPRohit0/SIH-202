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
