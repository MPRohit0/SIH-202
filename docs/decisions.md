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
