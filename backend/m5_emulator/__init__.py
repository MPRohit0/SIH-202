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
  (§6), and the A1-A8 acceptance checks (§8; A6/A8 need the confidence rule
  and A7 needs Monte Carlo, neither built yet, so they report
  `NOT_EVALUATED`). CLI: `python -m backend.m5_emulator.loocv --synthetic`.
- `validation_plots.py` — the `validation/*.png` charts.

Not yet implemented: Monte Carlo / unknown-breach mode, the confidence rule,
`get_flood()`, the empirical fallback, and the real
`design/scenario_design.json` (`library.py`/`loocv.py --synthetic` only
exercise the synthetic test world).
"""
