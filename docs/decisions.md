# Team decisions

## 2026-09-24 — Site config schema: YAML v1 vs contract §3.1 (PENDING team decision)

**Status:** pending — needs agreement from all module owners (contract §9) before the contract is changed.

`backend/shared/site_config.py` validates the format actually used in `sites/template.yaml` and
`sites/teesta.yaml` (`schema_version: 1`), **not** `docs/handoff_contract.md` §3.1. The contract has not
been edited. Differences to resolve:

| Topic | sites/*.yaml (v1, what the loader accepts) | contract §3.1 |
|---|---|---|
| Version key | `schema_version: 1` | `contract_version: 0.1.0` |
| Site id / name | `site: {id, name, region, river}` | top-level `site_id`, `name`, `state` |
| CRS | `crs.utm_epsg` as a SourcedValue | `crs_epsg` plain int |
| Domain keys | `far_field` / `near_field` | `farfield` / `nearfield` |
| Extent | `bbox` (SourcedValue) | `bbox_lonlat` (SourcedValue) |
| Resolution | `grid_resolution` (SourcedValue, m) | `cell_size_m` plain setting ⚙️ |
| Inflow point | `inflow: {from, location}` per domain | not in §3.1 |
| Dam id | bare slug (`south_lhonak`) | `<site_id>__<slug>` (§1.7) |
| POI id / type key | `id`, `category` (village, dam, bridge, hospital) | `poi_id` `<site>__poi__<slug>`, `kind` (adds town, school, …) |
| Dam kinds | moraine_dammed_lake, embankment_dam, concrete_dam, landslide_dam | natural_moraine, natural_landslide, embankment, cfrd, concrete, barrage |
| Breach input names | `breach_inputs.water_volume_above_invert`, … (no unit suffix) | `water_volume_above_breach_invert_m3`, … (flat, suffixed) |
| Enum values | `O/P`, `H/M/L` | `overtopping/piping`, `high/medium/low` |
| Units | `m^3` | `m3` (§1.1 suffix style) |
| `source` | free-text citation | `src_NNN` ID from docs/data_sources.md |
| `status` | `sourced` \| `placeholder` | adds `assumed` |
| Missing in v1 | — | `dem`, `landcover`, `cascade`, `thresholds`, `simulation`, `recheck`, `demo_mode`, `emulator_inputs`, `crest_elevation_m`, `reservoir_storage_m3`, `lake_area_m2`, `volume_elevation`, `equations_applicable`, `imposed_ranges` |
| Events | full `events` objects in the site file | list of event ids; details in docs/events/ |

Also found:
- `sites/teesta.yaml` refers to `sites/_template.yaml`; the file is `sites/template.yaml`.
- The repo has an empty `contract/` folder; CLAUDE.md and the contract say `contracts/`.

**Decide:** either migrate the YAML to §3.1 (and update the loader), or amend §3.1 to v1 (bump `contract_version`).

## 2026-09-24 — ID naming scheme and onboarding job state machine (PROPOSAL, pending review)

**Status:** proposal — not yet in `docs/handoff_contract.md`. Part 1 changes §1.7 and Part 2 changes
§5.3 / §5.1, so adopting either needs module-owner agreement and a `contract_version` bump (§9).
⚙️ marks settings the team still has to choose; no numbers below are measured values.

### Part 1 — ID naming scheme

**Rule: `__` (double underscore) separates hierarchy levels; `_` joins words inside a level.**
Any ID can be split on `__` into its parents without looking anything up:
`teesta__s007__delft3d` → site `teesta`, scenario `s007`, model `delft3d`.

Why change §1.7: today `scenario_id = <site_id>_s<NNN>` cannot be parsed reliably. A site named
`foo_demo` gives `foo_demo_s001`, which also reads as demo scenario 1 of site `foo`. `dam_id` and
`poi_id` already use `__`; this extends the same rule to scenarios and runs.

| ID | Pattern | Example | Scope / uniqueness |
|---|---|---|---|
| slug (building block) | `^[a-z0-9]+(_[a-z0-9]+)*$` | `south_lhonak` | lowercase ASCII, no `__`, no leading/trailing `_` |
| `site_id` | `^[a-z][a-z0-9]*(_[a-z0-9]+)*$`, 3–32 chars | `teesta`, `rishiganga` | global; never reused, never renamed |
| `dam_id` | `<site_id>__<slug>` | `teesta__south_lhonak` | per site (unchanged) |
| `poi_id` | `<site_id>__poi__<slug>` | `teesta__poi__chungthang` | per site (unchanged) |
| `event_id` | `<place_slug>_<YYYY>` | `teesta_2023`, `chamoli_2021` | global (unchanged) |
| `scenario_id` — design | `<site_id>__s<NNN>` | `teesta__s007` | per site, 001–999, **never reused** |
| `scenario_id` — demo mode | `<site_id>__demo_s<NNN>` | `new_site__demo_s003` | per site |
| `scenario_id` — historical | `<site_id>__hist_<event_id>` | `rishiganga__hist_chamoli_2021` | full `event_id`, so the event is traceable |
| `scenario_id` — named extra | `<site_id>__n_<slug>` | `teesta__n_full_volume` | per site |
| `run_id` | `<scenario_id>__<model>`, model `delft3d` \| `sph` | `teesta__s007__delft3d` | one per scenario × model |
| `query_id` | `q_<YYYYMMDDTHHMMSSZ>_<6 hex>` | `q_20260924T101500Z_3fa9c1` | global (unchanged) |
| `job_id` | `job_<YYYYMMDDTHHMMSSZ>_<6 hex>` | `job_20260924T101500Z_b17e02` | global (unchanged) |

Supporting rules:
- **Timestamps in IDs** are the UTC creation time, to the second, with `Z`. The hex part comes from
  `secrets.token_hex(3)`. The registry enforces a unique `job_id` / `query_id` (it retries on the
  one-in-16-million clash).
- **`query_id` and `job_id` stay site-free.** The registry stores `site_id`, so no change is needed.
- **Scenario numbers are never reused.** A re-run after `outdated` continues the numbering (for
  example `s031` onward). The registry stores which library each scenario belongs to in a new
  integer column, `scenarios.library_version`. The emulator `manifest.json` records its
  `library_version` and `run_ids`.
- **Retrying a failed run keeps the same `run_id`.** The registry counts attempts in a new
  `runs.attempt` column. The failed attempt's folder moves to `runs/_failed/<run_id>__a<N>/` for
  provenance.
- **Onboarding picks `site_id` explicitly.** The UI suggests a slug from the site name, and the
  user can edit it. If the ID is taken, the server returns `409 site_id_taken`; it does not
  auto-suffix, so IDs stay predictable.
- **File names follow the IDs, so they carry the same `__`.** For example
  `runs/teesta__s007__delft3d/` and `breach/hydrographs/teesta__s007__south_lhonak.csv`.

Impact if adopted: §1.7 examples, §4.2 hydrograph file names, §4.3 / §4.6 examples, and every
`scenario_id` / `run_id` in the site YAMLs and fixtures change. Nothing has been generated with
the old pattern yet, so there is no data to migrate.

### Part 2 — Onboarding job state machine

#### 2.1 Two separate things: job stage vs site status

- **Job `stage`** describes one onboarding or re-run job. It moves forward through milestones and
  ends in `ready` or `failed`.
- **Site `status`** (`SiteSummary.status`) is what the site can do right now. It is *derived* from
  the site's jobs and re-checks, and is never set by hand.
- **`outdated` is a site status, not a job stage.** It applies to a site whose job already
  finished `ready`, and is set later by a re-check or a config change.

#### 2.2 Job stages

Each stage names the **last milestone reached**. The step running "now" follows from the stage,
so the UI needs one field only.

```
 queued ──► dem_ready ──► breach_ready ──► simulating (k/N) ──► training ──► validated ──► ready
   │            │              │                  │                 │            │
   └────────────┴──────────────┴──────────────────┴─────────────────┴────────────┴──► failed
```

| Stage | Entered when | Running now | `progress` |
|---|---|---|---|
| `queued` | `POST /sites` accepted and config valid | nothing (`started_at` null) → then M1 terrain (`started_at` set) | none |
| `dem_ready` | M1 outputs (§4.1) written and pass raster checks (CRS, grid, nodata) | M2 breach ranges, then scenario design | none |
| `breach_ready` | `breach_params.json` and `scenario_design.json` written | launching the first solver run | `0 / N runs` |
| `simulating` | first run launched | Delft3D runs, one at a time (rule 13 RAM budget) | `k / N runs`, with `k` = runs `postprocessed` |
| `training` | all runs finished, or retries exhausted, and ≥ `min_runs_for_training` ⚙️ succeeded | PCA + GP fit, then LOOCV | `j / N folds` (LOOCV) |
| `validated` | `validation/loocv.json` written | publishing the emulator (swapped in atomically) | none |
| `ready` | manifest published; the site answers queries with `gp_emulator` | — (terminal) | none |
| `failed` | any unrecoverable error, or the user cancels | — (terminal) | frozen at last value |

Details:
- **`N` counts Delft3D design runs only.** SPH runs are comparison-only and take hours on the GPU,
  so they go into a separate `campaign` job after `ready` and do not hold up onboarding.
- **A failed solver run is retried `max_run_retries` ⚙️ times and then skipped.** `JobStatus`
  gains `runs: {completed, failed, running, pending}` so the UI can show skipped runs honestly.
  If fewer than `min_runs_for_training` ⚙️ succeed, the job fails with `too_few_runs`.
- **Poor validation does not block `ready`.** Poor LOOCV grades flow into the confidence rule
  (`validation_skill: POOR`). Being honest about confidence is the gate, not a hidden threshold.
- **`eta_s` stays `null` until the first run finishes.** After that it is the mean wall time of
  finished runs × remaining runs. The UI shows "estimate available after the first run", never a
  guessed number.
- **Cancelling is a `failed` job with `error.code: cancelled`.** This keeps the stage list short.
  It needs a new endpoint, `POST /jobs/{job_id}/cancel`.
- **A failed job can resume from its last milestone** via a new endpoint,
  `POST /jobs/{job_id}/resume`. For example, a job that failed during `simulating` keeps its
  finished runs. `JobStatus` gains `failed_at_stage`.
- **Demo mode uses the same stages** with `demo_mode: true`, `demo_mode.n_scenarios` runs at
  `demo_mode.cell_size_m`, and `__demo_sNNN` scenario IDs. It ends in site status `demo_mode`.
- **A re-run job (`kind: rerun`)** reuses the terrain, so it starts at `dem_ready`. It then follows
  the same path. The old library keeps serving until the new one is published at `ready`.

#### 2.3 Site status (derived)

| Site status | Condition | What queries return |
|---|---|---|
| `onboarding` | No published library yet, and the job is not `failed` | Nothing before `breach_ready`. From `breach_ready`: `empirical_fallback`, confidence LOW, caveat `empirical_fallback` |
| `demo_mode` | Published library came from a demo-mode job | `gp_emulator`, confidence LOW (contract §2.3), caveat `demo_mode` |
| `ready` | Published full library and not outdated | `gp_emulator`, computed confidence |
| `outdated` | Published library, plus one of the reasons below | the existing library + caveat `library_outdated` + `flags.library_outdated: true` |
| `failed` | No published library, and the latest job is `failed` | `empirical_fallback` if breach ranges exist, otherwise `409 site_not_ready` |

`outdated` reasons go in `status_reason_key`, with details in a new `status_detail` object:

| `status_reason_key` | Trigger | `status_detail` |
|---|---|---|
| `outdated_lake_area_change` | `recheck.json` has `change_pct` ≥ `recheck.lake_area_change_threshold_pct` | `{change_pct, threshold_pct, checked_at}` |
| `outdated_config_changed` | A fact in `sites/<id>.yaml` used in training has changed | `{changed_fields: [...]}` |

For the second trigger, the manifest stores a hash of the config fields used in training.

A site that is still `ready` but whose `recheck.next_check_at` has passed stays `ready` with a
"re-check overdue" banner. The lake may well be unchanged, so it is not marked `outdated`.

#### 2.4 What the UI shows at each stage

Every screen shows the same checklist in the style of `docs/ideation.md` ("DEM loaded ✓, breach
ranges computed ✓, Delft3D run 3/30 running…"). Text comes from `ui_text.json` keys
`job_stage_<stage>`. The API sends seconds; the frontend formats times.

| Stage | Headline | Checklist / progress | Map and panels | Actions |
|---|---|---|---|---|
| `queued` (not started) | "Waiting for the worker" | all steps pending | site bbox only | Cancel |
| `queued` (started) | "Preparing terrain" | Terrain ⟳ | site bbox only | Cancel |
| `dem_ready` | "Computing breach ranges" | Terrain ✓ · Breach ⟳ | domain, centreline, POIs; DEM source + vertical datum | Cancel |
| `breach_ready` | "Breach ranges ready — starting physics runs" | Terrain ✓ · Breach ✓ · Runs 0/N | the above + breach-range table (method pair per parameter, placeholders flagged); **fallback queries enabled, labelled "LOW CONFIDENCE — physics runs pending"** | Cancel · Try a fallback query |
| `simulating` | "Delft3D run k of N" | … · Runs k/N bar · failed/skipped count · ETA or "estimate after first run" | run table (scenario, status, wall time, mass-balance error); fallback queries still available | Cancel |
| `training` | "Training emulator" | … · Runs ✓ (k of N used) · Training ⟳ (LOOCV j/N) | run table frozen | Cancel |
| `validated` | "Validation complete — publishing" | … · Validation ✓ | LOOCV grades per output (extent / depth / arrival / velocity) | — |
| `ready` | "Site ready" (or "Demo-mode site ready") | all ✓ | grades, `last_trained_at`, next re-check date | Open site · Run SPH comparison |
| `failed` | "Onboarding failed at `<failed_at_stage>`" | ✓ up to the failed step, ✗ on it | error message; finished outputs stay visible | Resume · Edit config and restart |
| site `outdated` | "Library outdated: `<reason>`" (banner on every view of that site) | — | `status_detail` (e.g. lake area +X % vs threshold) | Re-run library |

Every stage also shows `has_placeholders` / `placeholder_fields` as a warning chip whenever they
are set (contract §0.5).

#### 2.5 Differences from the current contract

| Contract today | Proposed |
|---|---|
| §5.3 stages `queued → terrain → breach → design → simulating → training → validating → ready \| failed` (work in progress) | milestones `queued → dem_ready → breach_ready → simulating → training → validated → ready \| failed` |
| no cancel or resume | `POST /jobs/{id}/cancel`, `POST /jobs/{id}/resume`; `JobStatus.failed_at_stage`, `JobStatus.runs{…}` |
| `rerun` job kind has no stages | reuses the onboarding stages, starting at `dem_ready` |
| `SiteSummary.status_reason_key` only | adds `status_detail`; `outdated` gets two defined triggers |
| registry `scenarios`, `runs` | adds `scenarios.library_version`, `runs.attempt` |

### Open questions for the reviewer

1. Adopt the `__` separator for `scenario_id` / `run_id` (Part 1), or keep §1.7 as written and
   instead forbid site IDs containing `_demo`, `_hist` or `_s<digits>`?
2. Values for `min_runs_for_training` ⚙️ and `max_run_retries` ⚙️. Suggest setting them after the
   pilot gate, once real run times are known.
3. Confidence for an `outdated` site: keep the computed level plus a critical caveat, or cap it
   (for example at LOW)?
4. Should a lapsed re-check date make a site `outdated`, or only show the "re-check overdue"
   banner (as proposed)?
5. Accept the two new job endpoints (cancel, resume)?

## 2026-09-24 — M2 breach engine: XZ9/h_r blocker, Z20 dam-type mapping, breach_params.json additions (DECIDED with user this session)

**Status:** implemented in `backend/m2_breach/`. Two things are blocked pending real sources, not
worked around; one contract addition was made.

### XZ9 blocked (`backend/m2_breach/xz9.py`)

`docs/Equations.md` §1.2/§2.3 marks Xu & Zhang (2009)'s reference height `h_r` "NOT STATED —
UNCLEAR", and §7's checklist says: "Block XZ9 (both Q_p and B_ave) until h_r is sourced; don't
hard-code a guess." Both `peak_discharge_xz9()` and `breach_width_xz9()` raise
`BlockedEquationError` unconditionally; the coefficient tables are transcribed in the docstring
so implementation is a one-line change once h_r has a source.

**Consequence for the recommended method pairs** (`docs/paper_azmi.md`): XZ9 feeds the updated
DFM for Q_p and B_ave, and DFM 2024 for Q_p (`Q_p(DFM2024) = 1.23·F16 − 0.84·H14 + 0.26·XZ9`). So:

| Output | Recommended pair | Status today |
|---|---|---|
| Q_p | DFM_updated + DFM_2024 | **blocked** (both members need XZ9) — F16, Z20 still reported individually |
| B_ave | DFM_updated + XZ9 | **blocked** (both members need XZ9) — F95, F8 still reported individually |
| T_f | DFM_updated + F8 | **computable** — neither needs XZ9 |

Only T_f gets a real dual-method range until h_r is sourced. Confirmed with the user before
building rather than guessing a value for h_r.

### Z20 blocked outside HD/CD (`backend/m2_breach/z20.py`)

`docs/Equations.md` §1.3 gives only HD and CD branches for Zhong et al. (2020); FD/ZD mapping is
NOT STATED, and §7 says to raise for any other dam type. Teesta III (`sites/teesta.yaml`) is FD,
so its Q_p output has Z20 blocked with warning `z20_dam_type_unmapped` — F16 is still reported.

### `breach_params.json` additions (agreed with user; additive, not a change to existing fields)

Contract §4.2's example shows every method as `{value, in_valid_range}`. A blocked method (or a
blocked dual-method range) instead writes `{value: null, status: "blocked", reason: "<why>"}`
with `low`/`high`/`in_valid_range` also null on a blocked range. `contracts/schemas/
breach_params.schema.json` (new) encodes both shapes; `contracts/examples/
breach_params.example.json` (new, generated from `sites/teesta.yaml`) shows a real blocked case.
`in_valid_range` is `null` everywhere in practice — `docs/Equations.md` states "Valid range: NOT
AVAILABLE" for every base equation, so no calibration-range check is invented.

Also: the §4.2 example has no top-level `caveats` field, only per-dam `warnings`. This
implementation follows the example as given — `moraine_extrapolation`, `placeholder_data`,
`failure_time_uncertain`, `clear_water` etc. are folded into `warnings`, not a separate list, to
avoid adding an unshown field.

**Decide:** whether to fold this shape back into `docs/handoff_contract.md` §4.2 once XZ9/Z20 are
unblocked, or keep it as a permanent "blocked equation" convention other modules may need too.

## 2026-09-24 — M2 breach hydrographs: coefficients, storage curve, Q_p-range check (DECIDED with user this session)

**Status:** implemented in `backend/m2_breach/{weir,storage,hydrograph}.py`. Contract §4.2's
hydrograph part (`hydrograph(site_id, dam_id, params)`, `hydrographs/*.csv` + sidecar) had not
been built yet (`docs/progress.md`, "out of scope this session, left for next").

### No built-in weir/side-slope/storage coefficients (CLAUDE.md rule 3)

`backend/m2_breach/weir.py`'s broad-crested weir equation and `storage.py`'s area-volume
relation are standard hydraulics, **not** from `docs/Equations.md` (that document's scope is the
Azmi 2026 breach-parameter equations). No source in this repo gives a weir coefficient, breach
side slope or area-volume exponent, so the code has **no default value** for any of them —
inventing one would violate rule 3. They are additive, optional fields on `Dam`
(`backend/shared/site_config.py`): `volume_elevation` (mirrors contract §3.1's block already
drafted there but missing from the v1 loader — see the pending site-config-schema decision above)
and a new `breach_hydrograph` block (`weir_coefficient_rect`, `weir_coefficient_side`,
`side_slope_z`, all SourcedValues). A `Dam` without both blocks fully sourced cannot use
`breach_growth_weir`; `hydrograph_for_dam` falls back to the volume-conserving `triangular`
method (needs `params["peak_discharge_m3s"]`), or raises `HydrographBlocked` if neither is
available — the same "block, don't guess" pattern as XZ9.

### Storage curve when bathymetry is missing

`storage.from_area_volume_relation(V_w, h_w, b)` derives `V(h) = V_w * (h/h_w)^(b/(b-1))` from
the site's area-volume exponent `b` (`V = a*A^b`) and the one calibration point M2 already has —
this is an SIH26-derived shape assumption (self-similar basin), not a published formula; every
hydrograph built from it carries caveat `storage_from_area_volume_relation`. When bathymetry
exists, `storage.from_surveyed_curve(points, invert_elevation_m)` interpolates it directly with
no caveat.

### `peak_within_m2_range` when the Q_p range is blocked

The M2 Q_p range (`DFM_updated`+`DFM_2024`) is blocked for every dam today (XZ9 pending h_r — see
the XZ9 decision above), so the synthetic test dam's weir-routed peak (~1500 m³/s at
V_w=1e6, B_ave=40m) can't be checked against it. Agreed: `peak_within_m2_range` is `null` (not
`False`) with caveat `m2_qp_range_blocked` when the range is blocked, and tests check the flag is
correctly `null`/`true`/`false` rather than picking inputs to force `true`.

### Breach growth: width and invert depth together

Per Fread/HEC-RAS-style breach growth, the invert drops linearly from the initial water surface
to the final invert over `failure_time_s` while the bottom width grows from 0 to
`B_ave - z*h_b` (B_ave being the mean of top and bottom width, `docs/Equations.md` §0). This keeps
`Q=0` at breach start for any side slope `z`, avoiding the discontinuity a width-only growth model
would have.

### New contract files

`contracts/schemas/hydrograph_sidecar.schema.json` (new) encodes contract §4.2's sidecar shape
plus additive fields `peak_within_m2_range`, `has_placeholders`, `caveats`, `provenance` (same
pattern as the `breach_params.json` additions above). `contracts/examples/
hydrograph_sidecar.example.json` (new) is generated by actually running `breach_growth_weir()`,
not hand-written.

## 2026-09-24 — M2 cascade engine: two-stage imposed hydrograph (DECIDED with user this session)

**Status:** implemented in `backend/m2_breach/cascade.py`, `backend/shared/site_config.py`. This
finally resolves `docs/handoff_contract.md` §3.1's `cascade.approach: null ⚙️` for the case M2
needs today (Teesta: South Lhonak GLOF → Teesta III), though the contract doc itself is not
edited — see "Site-config schema" decision at the top of this file for why the v1 loader keeps
diverging from §3.1 until that migration happens.

### Approach chosen: `two_stage_imposed`, not `dambreak_structure`

Confirmed with the user (both options were live in §3.1 and in `docs/ideation.md`'s "model its
failure as an imposed scenario" note): M2 does **not** route the flood itself. A downstream dam's
own breach hydrograph is triggered once **routed inflow** at that dam — an input time series
produced by the stage-1 Delft3D run's observation cross-section (M3), or M5's HAND fallback —
first reaches a threshold. `backend/m2_breach/cascade.py`'s `cascade_plan()` raises
`UnsupportedCascadeApproach` if it sees `cascade.approach: dambreak_structure`; that approach
(breaching modelled dynamically inside a Delft3D structure) belongs to M3, and is out of scope
for this module. No celerity/attenuation value is invented to do the routing in M2 (CLAUDE.md
rule 3) — see `trigger_time()`'s docstring.

### Per-dam trigger threshold, not the single site-level `cascade.trigger` in §3.1 (PENDING team agreement)

Contract §3.1 sketches one site-level `cascade.trigger.value_m3s`. With a chain of dams (or more
sites onboarded later), different dams have different capacities, so this deviates: `Dam.trigger`
(`{type: inflow_threshold, value: SourcedValue m^3/s}`) is per dam, required on every dam with
`triggered_by` set when `cascade.approach == two_stage_imposed`
(`SiteConfig._cross_checks`). **This is additive and PENDING team agreement** — the contract's
single site-level `trigger` block is not removed from the doc, and could still be adopted as a
site-wide default with per-dam overrides if the team prefers. `sites/teesta.yaml`'s
`teesta_iii.trigger.value` is `status: placeholder` — not sourced yet (needs the spillway/outlet
capacity or the 2023 failure timeline).

### Superposition, not routed-inflow-through-storage

The triggered dam's hydrograph (`cascade.triggered_hydrograph`) releases only **its own** stored
volume (`hydrograph_for_dam`, unchanged) — it does not level-pool route the incoming upstream
flood through the reservoir during the breach. The routed upstream flood keeps flowing through
the stage-2 hydraulic model and is added there (superposition), not by M2. This was the simpler
of two options discussed; the alternative (inflow term in the storage ODE) would need M3 to know
not to also inject the upstream flood at that point, adding coupling for a physical effect
(reservoir filling before breach) that is already a known limitation. Caveat
`cascade_superposition` records this on every triggered hydrograph.

### `equations_applicable` / `imposed_ranges` now enforced by the loader, not `compute_dam`

`docs/Equations.md` §7 says to refuse `kind: concrete_dam`. Previously `breach_params.compute_dam`
raised `DamKindRefused` for it outright — but §4.2 says such a dam should report `imposed_ranges`
from the config instead, flagged `concrete_dam_imposed` (this was simply not built yet). Now:

- `SiteConfig._cross_checks` requires `equations_applicable: false` whenever `kind: concrete_dam`,
  and requires `imposed_ranges` whenever `equations_applicable: false`. `DamKindRefused` is
  deleted; a bad config is now a loader error instead of a `compute_dam` exception.
- `compute_dam` for `equations_applicable: false` builds each output range straight from
  `imposed_ranges` (`interval: "imposed"`, `selected_pair: null`, `source` from the config's
  `SourcedValue`), or `status: "blocked"` if that range is itself a placeholder — same
  "block, don't guess" pattern as XZ9.
- `breach_params.schema.json`'s `OutputRange.interval` gains `"imposed"`; `selected_pair` may be
  `null` for it. `hydrograph_sidecar.schema.json` gains an optional `trigger` object.

`sites/teesta.yaml`'s `teesta_iii` stays `kind: embankment_dam` / `dam_type: FD` — its true dam
type is still unverified (`docs/ideation.md`: "Verify Teesta III dam type before applying
embankment equations"). If it turns out to be concrete, flip `equations_applicable: false` and
fill `imposed_ranges` from a source; no code change needed.

### Tests

`tests/fixtures/m2_breach/synth_cascade.yaml` (new): a synthetic two-dam site (`synth_lake` →
`synth_dam2`, concrete, imposed ranges, per-dam trigger), fully sourced so cascade tests aren't
tangled with placeholder-detection tests. Loader cross-checks are tested in
`tests/shared/test_site_config.py`; `cascade_plan`/`trigger_time`/`triggered_hydrograph` (including
a three-dam chain, an end-to-end lagged-hydrograph scenario, and the placeholder-threshold block)
are tested in `tests/m2_breach/test_cascade.py`.

## 2026-09-25 — M5 LOOCV: additive validation-report fields (NEEDS TEAM SIGN-OFF)

**Status:** implemented, additive-only, not yet confirmed by the team.

`docs/m5_specs.md` §8 (acceptance test A1) requires the GP be checked against **two** baselines
("Linear-in-scores" and "Nearest-run blending"), but `docs/handoff_contract.md` §4.6's
`validation/loocv.json` shape only has one baseline key, `baseline_linear`. Per user instruction
this session, resolved by keeping `baseline_linear` exactly as contracted (linear-in-scores) and
adding a sibling `baseline_nearest` key with the same shape (`extent.iou_median`,
`depth.rmse_wet_m_median`, `arrival.mae_s_median`), extended with `extent.f1_0_3_median` and
`arrival.rmse_s_median` since A1/A4 need those too. `contracts/schemas/validation.schema.json`
does not `additionalProperties: false` on the top level, so this validates without a schema change.
Also additive, for the same reason (not in the contract's `loocv.json` sketch, needed for an honest
A1-A8 report): `per_run[].extra` (arrival RMSE, POI/by-output coverage, terrace flag, PCA
projection RMSE, both baselines' per-run metrics), `acceptance` (the A1-A8 table),
`settings`/`caveats`/`provenance`/`notes`.

Grades: spec §6's skill-check cut-offs are only defined for extent (F1 >= 0.85/0.70) and arrival
(RMSE <= 10%/20% of mean true arrival). Depth and velocity have no cut-off in the spec, so their
`summary.*.grade` stays `"UNKNOWN"` rather than inventing thresholds — flagged for the team to set
in a future session (`backend/m5_emulator/loocv.py`'s `GradeThresholds`).

The synthetic-world report (`reports/m5_synthetic/validation/loocv.json`, gitignored, **not**
under `data/`) uses `model: "synthetic"`, outside the contract's `delft3d | sph` enum — same
reasoning as `library.py`'s existing "never write synthetic run_ids into data/". The CLI validates
the report against `validation.schema.json` with `model` substituted to `"delft3d"` for the check
only, and records this as a `notes` entry in the report itself so it's never silently passed off as
real.
