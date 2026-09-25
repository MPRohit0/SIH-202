"""M5 — flood emulator.

Scenario design, run cache, PCA + Gaussian Process emulator, LOOCV, Monte
Carlo, confidence and empirical fallback (`docs/m5_specs.md`).

- `synthetic.py` — the fake-physics test world used to develop and test the
  rest of M5 before real Delft3D/DualSPHysics runs exist (§7).
- `transforms.py` — per-output transforms (log1p depth/velocity, arrival
  fill) applied before PCA and undone after decoding (§3).
- `inputs.py` — emulator input scaling: log10(V_w)/B_ave/T_f, standardised
  (§1).
- `pca.py` — corridor cell masking and PCA on a training-run map stack (§3).
- `gp.py` — one Matern-3/2 + White, ARD Gaussian Process per PCA component
  (§3).
- `emulator.py` — `FloodEmulator`: ties the above together — fit, predict,
  save/load (`docs/handoff_contract.md` §4.6), and a length-scale
  sensitivity table.
- `library.py` — a synthetic maximin-LHS training library (§2), for testing
  `emulator.py` before real runs exist.
- `metrics.py` — one function per LOOCV metric (extent IoU/F1, wet-cell depth
  RMSE, arrival MAE/RMSE, velocity MAE, flooded-area % error, 90% interval
  coverage, PCA projection RMSE, terrace classification) (§4, §6, §8).
- `baselines.py` — the two A1 baselines: linear-in-PCA-scores and
  nearest-run IDW blending (§8).
- `loocv.py` — leave-one-out cross-validation (refits PCA + GPs per fold,
  §3), the GP-vs-baselines comparison, `validation/loocv.json` assembly
  (`docs/handoff_contract.md` §4.6, plus additive fields — see
  `docs/decisions.md` "M5 LOOCV: additive validation-report fields"), grading
  (§6), and the A1-A8 acceptance checks (§8; A6/A8 need the confidence rule,
  built below but not yet wired into `run_acceptance`, and A7's own large-grid
  Monte Carlo check is still `NOT_EVALUATED`). CLI:
  `python -m backend.m5_emulator.loocv --synthetic`.
- `validation_plots.py` — the `validation/*.png` charts.
- `confidence.py` — the S/C/U confidence checks and their weakest-link-by-count
  combination (`docs/handoff_contract.md` §2.3, `docs/m5_specs.md` §6).
- `monte_carlo.py` — unknown-breach-mode sampling (§5.2) and the chunked,
  memory-bounded per-cell accumulators (exceedance counts, 64-bin histograms
  for depth/velocity/arrival, exact point-of-interest samples — §5.3).
  Arrival's histogram reserves its top bin for "never arrived within
  `t_end_s`", so both modes now produce a full-grid arrival map.
- `query.py` — `get_flood()`: one query in either `scenario` (§5.1, GP
  uncertainty only, analytic) or `unknown_breach` (§5.2, Monte Carlo) mode,
  plus `to_contract_response()`, which assembles a `FloodQueryResponse`
  (`docs/handoff_contract.md` §5.4). Rendering PNG layers and persisting
  `data/<site_id>/queries/<query_id>/` are still M0's job — see the module
  docstring for the exact boundary.
- `timeline.py` — the Timeline (`docs/handoff_contract.md` §5.5, route #13):
  flood-front frame arrays at a given time t ("extent at time t = cells
  whose arrival <= t", median/HIGH/POSSIBLE), the arrival-vs-chainage
  profile with P10/P50/P90 bounds, and the M2 inflow hydrograph(s) it rides
  along with. Writes `timeline/*.tif` + `timeline_data.json`; rendering the
  PNGs and serving the per-`interval_s` frame list is M0's job
  (`backend/m0_api/timeline.py`).
- `fallback.py` — the empirical fallback for a site with no trained emulator
  (contract §4.6: `method: "empirical_fallback"`, confidence always LOW): M2's
  peak discharge routed along the centreline, Manning's-equation stage per
  cross-section from the roughness raster, HAND-based flooding, arrival from a
  kinematic-wave-celerity assumption, plus its own `to_contract_response()`.
  Needs M1's `hand.tif`/`roughness.tif`/`chainage_samples.csv`, which don't
  exist yet; its tests use `synthetic_fallback_terrain()`, a HAND/roughness/
  bed-elevation stand-in built independently of `synthetic_flood_maps` on the
  same §7.1 valley.
- `compare.py` — Compare's "emulator vs physics" / "GP vs linear" sections
  (`docs/handoff_contract.md` §5.6, route #15): `emulator_vs_physics_metrics`/
  `gp_vs_linear_summary` read `loocv.build_report()`'s per-run GP metrics and
  baseline aggregates back out in the Compare contract's shape;
  `fit_and_diff_held_out` refits one chosen held-out fold on demand (LOOCV
  itself discards per-fold arrays, CLAUDE.md rule 13) to get a depth
  difference raster. `write_compare_inputs` persists both under
  `emulator/<model>/validation/compare/`; rendering the diff PNG and serving
  the Compare response is M0's job (`backend/m0_api/compare.py`).

`GET /flood/{query_id}/timeline` is wired for real (`backend/m0_api/timeline.py`
+ `main.py`'s route #13 and the `/files/{path}` frame-PNG path) once
`timeline/timeline_data.json` exists under a query's directory; nothing yet
writes that directory from a live `POST /flood/query` (see below). Same for
`GET /compare/{site}` (`backend/m0_api/compare.py` + route #15) once a
`validation/compare/<held_out_run_id>.json` sidecar exists — nothing yet
calls `compare.write_compare_inputs()` from a live LOOCV run either.

Not yet implemented: wiring `get_flood()`/`fallback.py` (including calling
`timeline.write_timeline_inputs()`) into a real `POST /flood/query` handler
(still mocked), calling `compare.write_compare_inputs()` after a real/synthetic
LOOCV run, resolving the request contract's `{type: exact | slider}` input
wrappers, and the real `design/scenario_design.json` and `chainage_samples.csv`
(`library.py`/`loocv.py --synthetic`, `query.py`'s, `timeline.py`'s,
`compare.py`'s and `fallback.py`'s own tests all still exercise the synthetic
test world only, via `synthetic.centreline_samples`).
"""
