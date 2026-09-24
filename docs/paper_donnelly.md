# Donnelly et al. (2022) — GP emulation of spatio-temporal 2D flood-model outputs

Source: Donnelly J., Abolfathi S., Pearson J., Chatrabgoun O., Daneshkhah A. (2022), "Gaussian process emulation of spatio-temporal outputs of a 2D inland flood model", *Water Research* 225:119100, doi:10.1016/j.watres.2022.119100 (CC BY 4.0).

## What the paper does

- Emulates LISFLOOD-FP water depths for Tadcaster, UK (River Wharfe): 3.6 km² domain, 2 m DEM, 876,204 cells, Manning's n varying with land use.
- Training data: 14 synthetic hydrographs at 15-min steps. Peaks were sampled from a Pareto fit to peaks-over-threshold data, oversampling the upper tail. Depths < 0.03 m were set to 0.
- The emulator works **per timestep**. Input x_t = upstream discharge at t, t−1, …, t−8 (D = 9, standardised to zero mean and unit variance). Output = the full depth map at t.
- Stacked over the 14 runs: X ∈ R^(2624×9), Y ∈ R^(2624×876204).
- Benchmarked against a CNN emulator (Kabir et al. 2020).

## Method: PCA + independent GPs (SOGP)

1. Flatten each H×W depth map into a vector of length HW and stack the rows → Y (N × HW).
2. Run PCA via randomised SVD (Halko et al. 2009) → latent Z (N × D*). **D* = 6** components explained 99% of the variance. Reconstruction RMSE was 0.018 m, and 10-fold CV of the PCA gave consistent results.
3. Fit **one independent single-output GP per component**, f_j: R^D → R for j = 1..D*. The paper justifies independence by PCA components being orthogonal. Cost is O(D*·N³), versus O((D*·N)³) for a coupled multi-output GP (LMC).
4. To predict: new x → GP mean and variance for each component → PCA decoder → depth map.

### Kernel (Eq. 15)

Zero mean function. Matérn 3/2 kernel plus a noise term:

```
k(x, x') = σ² · (1 + √3·‖x − x'‖₂ / l) · exp(−√3·‖x − x'‖₂ / l) + σ_n² · δ(x, x')
```

- One isotropic length-scale l (no ARD), applied to the standardised inputs.
- Chosen over the squared-exponential kernel after preliminary tests (SE assumes too much smoothness).

### Hyperparameter fitting (Eqs. 12–13, 16–17)

- θ = (σ², l, σ_n²) is fitted separately for each GP by maximising the log marginal likelihood: `log p(y|X,θ) = −½ yᵀ K_y⁻¹ y − ½ log|K_y| − (n/2) log 2π`, where `K_y = K + σ_n² I`. Eq. 17 gives the gradient. Cost is O(N³).
- Posterior mean `μ* = K*ᵀ K_y⁻¹ y`; posterior covariance `Σ* = K** − K*ᵀ K_y⁻¹ K*`.
- Not reported: optimiser, restarts, bounds or priors, and whether PCA scores were scaled.

## Validation metrics

**Regression is scored on wet cells only.** Ω is the set of cells where either LISFLOOD-FP or the emulator predicts depth > 0 at any timestep of that simulation.

```
RMSLE = sqrt( Σ_Ω (log y − log ŷ)² / |Ω| )      (Eq. 18)
RMSE  = sqrt( Σ_Ω (y − ŷ)²         / |Ω| )      (Eq. 19)
```

- Why wet cells: most cells never flood and would dilute the error. RMSLE weights relative error, so errors on the shallow floodplain count.
- The paper doesn't say how log(0) is handled when a cell in Ω is dry in one of the two maps. **We use log1p** and say so in reports.

**Classification:** a cell is wet if depth > c, for c ∈ {0.05, 0.1, 0.3} m. The paper recommends 0.3 m, the depth at which Aldridge et al. (2016) count a property as flooded.

```
TPR = TP / (TP + FN)     FPR = FP / (FP + TN)     F1 = TP / (TP + ½(FP + FN))
```

- The paper defines TPR, FPR and F1, but its tables report F1, Recall (= TPR) and a column labelled "FNR". Those values (~0.005) are not 1 − recall (~0.03–0.06), so the column is probably FPR mislabelled. **Report TPR, FPR and FNR explicitly**, each named.

## LOOCV

- Leave one hydrograph out: train on 13, test on the 14th, and repeat 14 times. The folds are whole runs, never random timesteps.
- Mean RMSLE 0.11, RMSE 0.21 m. The text names hydrograph 8 as the outlier; in Fig. 12 the peak (RMSE ≈ 0.6 m) is labelled 9, probably an indexing mismatch.
- The paper doesn't say whether the PCA was refitted inside each fold.
- The first 3 components are predicted well; components 4–6 have much wider intervals.
- The largest cell errors are in complex urban topography next to the river.

| LOOCV mean | RMSLE | RMSE (m) |
|---|---|---|
| GP | 0.112 | 0.209 |
| CNN | 0.122 | 0.232 |

| c (m) | Model | F1 | Recall | "FNR" (likely FPR) |
|---|---|---|---|---|
| 0.05 | GP / CNN | 0.940 / 0.940 | 0.967 / 0.960 | 0.0046 / 0.0051 |
| 0.10 | GP / CNN | 0.941 / 0.940 | 0.958 / 0.955 | 0.0058 / 0.0061 |
| 0.30 | GP / CNN | 0.937 / 0.935 | 0.936 / 0.935 | 0.0078 / 0.0081 |

(Values from Table 3. Table 1 gives GP recall as 0.968 and 0.937 at c = 0.05 and 0.3.)

Runtimes (Table 4, one 250-step simulation): LISFLOOD-FP 9,900 s; CNN 600 s to train, 80 s to run; GP 226 s to train, 1 s to run. That is ≈ 10,000× faster than the simulator and 80× faster than the CNN.

## Uncertainty (±2σ)

- CI = μ(x*) ± 2σ(x*) for each latent component (Eq. 24, about 95%).
- The upper and lower latent bounds are decoded to maps. Their difference is mostly < 0.5 m, but > 1 m in the river channel.
- A 1000-year hydrograph (peak 750 m³/s, against 480 m³/s in the 2015 flood) gave much wider intervals even for components 1–3, because it is outside the training range.
- Caution (ours): decoding μ ± 2σ component by component does **not** give a per-cell 95% interval, because the loadings have mixed signs. With independent GPs the per-cell variance is `Var(y_i) = Σ_j W_ij² σ_j²`, plus the PCA truncation error.
- σ covers **emulator** error only. It says nothing about input or simulator uncertainty.

## Limitations the authors state

- Each emulator is case-specific: a new site needs new simulations and a new emulator.
- Quality depends heavily on the training design, which must cover the scenario range.
- Development cost (data, simulations, validation) is high, so check an emulator is needed at all.
- Data is available only on request.

## How SIH26 differs

We emulate **scenario parameters → summary maps**, from about 30 runs, **not per timestep**.

| | Donnelly 2022 | SIH26 |
|---|---|---|
| One training row | one timestep of one run | one full run (scenario) |
| Inputs x | 9 lagged discharges | scenario parameters (breach outputs/inputs from `docs/paper_azmi.md`, etc.) |
| Outputs | depth map at each timestep | one set of summary maps per run: max depth, arrival time, … |
| N | 2,624 | ~30 |
| LOOCV folds | 14 hydrographs | ~30 runs |

Consequences for the implementation:

1. **Design matters most.** With N ≈ 30, pick inputs with a space-filling design (LHS or Sobol) over the parameter ranges, with the Azmi pair's low/high values inside those ranges.
2. **PCA:** at most N − 1 useful components. Choose D* at 99% variance as the paper did, then confirm with reconstruction RMSE on wet cells. **Refit the PCA inside every LOOCV fold** so the held-out run doesn't leak into it.
3. **Kernel:** keep Matérn 3/2 + noise. Our inputs have mixed units, so standardise them and consider ARD length-scales, with bounds or priors on l because N is small. Keep a small noise floor for numerical stability, since the simulator is deterministic.
4. **Fitting:** maximise the marginal likelihood with several random restarts, because with N ≈ 30 the likelihood surface is multimodal. Log the chosen θ for each GP.
5. **Map transforms:** depth ≥ 0, so emulate log1p(depth) or clip negatives and report how many were clipped. Arrival time is undefined in dry cells: give them a fill value (e.g. simulation end) and take the wet/dry mask from the depth emulator.
6. **Separate emulators** for each map type and each domain (far-field, near-field).
7. **Metrics:** RMSE and RMSLE on Ω, plus F1/TPR/FPR at c = 0.05, 0.1 and 0.3 m, all on the max-depth map. Also report arrival-time error at points of interest (our addition).
8. **Uncertainty:** propagate per-cell variance through the PCA loadings, as above. For breach-parameter uncertainty, sample inputs (Monte Carlo) through the emulator — the cheap runs are the reason to have one.
9. **Extrapolation:** flag any query outside the training input range (the paper's 1000-year case).
10. With no lag features and no per-timestep outputs, the problem is far smaller. Emulating hydrographs at points of interest would need its own design.
