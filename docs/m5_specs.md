# M5 — Flood emulator specification (DRAFT)

Status: draft for team review. Every default below has a **Why** line so it can be argued
with and changed. Numbers marked *(tune)* are expected to move after the first real runs.

Related docs: `docs/paper_donnelly.md` (method source), `docs/paper_azmi.md` and
`docs/equations.md` (M2 breach parameters that feed M5), `sites/<site_id>.yaml` (site config).

---

## 1. What M5 does

M5 replaces the 2D hydraulic model at query time. It learns

```
scenario parameters x  →  summary maps for one run
```

from about 30 pre-computed runs, then answers queries in seconds.

- **Inputs x (default):** `log10(V_w)`, `B_ave`, `T_f`, all standardised to zero mean and unit variance.
  *Why:* these are the three breach outputs that shape the hydrograph (M2 produces them). V_w spans
  orders of magnitude, so log space keeps the design and length-scales sensible.
- **Outputs (one emulator per map type per domain):**
  - `max_depth` [m]
  - `arrival_time` [min after breach start]
  - `max_velocity` [m/s]
  - `extent` is **not** emulated separately. It is `max_depth > extent threshold`.
  *Why:* a separate extent emulator could disagree with the depth emulator. Deriving extent from
  depth keeps them consistent.
- **Method:** PCA on each map stack, then one independent Matérn-3/2 GP per retained component
  (Donnelly et al. 2022, adapted to per-scenario maps, not per timestep).
- **Machine:** one 16 GB RAM laptop. No GPU assumed.

---

## 2. Training design

| Setting | Default | Why |
|---|---|---|
| Number of runs | 30 | ≈10 runs per input dimension, the usual rule of thumb for GP emulators; fits the compute budget for 2D runs |
| Design | maximin Latin hypercube over the 3 inputs | spreads points evenly; maximin avoids clumps that LHS alone can produce |
| Input ranges | M2 pair bounds (low/high of the Azmi pair) widened by 20% on each side | queries near the edge of the M2 range should still land inside the training box, not in extrapolation |
| Extra held-out runs | 5 (optional, if compute allows) | LOOCV on 30 runs is slightly optimistic; a few truly unseen runs make an honest final check |
| Seed | fixed and logged | the design must be reproducible |

---

## 3. Emulator settings

| Setting | Default | Why |
|---|---|---|
| Cell mask | union of cells wet (depth > 0.03 m) in any training run, plus a 3-cell buffer | far-field grids can have millions of cells that never flood; dropping them cuts memory and PCA time a lot. The buffer leaves room for slightly larger floods |
| Depth transform | `log1p(depth)` before PCA; back-transform after | stops negative depths and gives shallow floodplain cells fair weight (same reason Donnelly use RMSLE) |
| Velocity transform | `log1p(velocity)` | same reasons as depth |
| Arrival in dry cells | fill with simulation end time `T_end` before PCA | PCA can't take NaN. `T_end` means "didn't arrive within the run" and is masked out afterwards using the depth-derived extent |
| PCA components | smallest D* reaching 99% variance, capped at N − 2 | 99% is Donnelly's choice; with N = 30 the cap stops the PCA from memorising individual runs |
| PCA refit | inside every LOOCV fold | otherwise the held-out run leaks into the basis and the scores look too good |
| Kernel | Matérn 3/2 + white noise, **ARD** (one length-scale per input) | Matérn 3/2 per Donnelly. ARD because our inputs matter unequally (V_w usually dominates) |
| Length-scale bounds | [0.1, 10] in standardised units | with 30 points an unbounded optimiser can pick absurd length-scales |
| Noise floor | σ_n² ≥ 1e−6 × component variance | the simulator is deterministic; the floor only keeps the matrix well conditioned |
| Optimiser | L-BFGS-B, 10 random restarts, keep the best marginal likelihood | the likelihood surface is multimodal at small N |
| Storage | PCA loadings as float32 | halves memory; float32 precision is far below model error |

---

## 4. Thresholds

| Threshold | Default | Why |
|---|---|---|
| Extent ("flooded") | depth > **0.30 m** | the flood-risk threshold Donnelly adopt (Aldridge et al. 2016: properties at 0.3 m count as flooded). It is also roughly where walking and small vehicles become unsafe |
| Arrival | first time depth > **0.10 m** | earlier than the extent threshold on purpose: for evacuation, a slightly early warning is safer than a late one. Still well above wetting-front and numerical noise (~0.03 m) |
| Wet cell for metrics (Ω) | depth > 0.03 m in truth or prediction | matches Donnelly's zero-depth cut-off so metrics compare |
| Classification report | also at 0.05 and 0.10 m | Donnelly report three thresholds; it shows whether skill depends on the cut-off |

All thresholds live in config, not code.

---

## 5. Query modes

### 5.1 Scenario mode (known breach)

The user gives one scenario: `V_w`, `B_ave`, `T_f`, or the breach inputs, in which case M2 runs first
and **each member of the Azmi pair** becomes its own scenario.

- Output: mean maps, a per-cell 90% band, and values at each point of interest.
- Uncertainty is **emulator uncertainty only**. The per-cell variance is `Σ_j W_ij² σ_j²` in transformed space, and the band is back-transformed at its end points.
- No Monte Carlo is needed, so it should be fast.

*Why:* this answers "what if this exact breach happens?", which covers planning and the historical
validation event.

### 5.2 Unknown-breach mode

The user gives a dam or lake from the site config, and the breach is uncertain.

- Inputs are sampled from distributions:
  - `V_w`: log-uniform over its sourced range (a single sourced value gets ±20%).
  - `B_ave`, `T_f`: uniform between the low and high Azmi pair values, widened by 20%.
- Each sample is pushed through the emulator. The GP draw per sample is `z_j ~ N(μ_j, σ_j²)`, so
  emulator and breach uncertainty are combined.
- Output:
  - per-cell **exceedance probability** P(depth > 0.3 m);
  - per-cell median and 5th/95th percentile depth;
  - arrival-time percentiles at points of interest;
  - probability that each point of interest floods.

*Why uniform and log-uniform:* M2 gives bounds, not a distribution. Uniform says "anywhere in
the range" without inventing a peak we can't defend. The team can switch to triangular if M2
starts giving a best estimate.

### 5.3 Monte Carlo settings

| Setting | Default | Why |
|---|---|---|
| Samples | **2,000** | the Monte Carlo error on an exceedance probability is ≤ 0.5/√N ≈ 1.1 percentage points; each 5%/95% tail keeps 100 samples, enough for stable percentiles |
| Chunk size | `floor(2 GB / (n_cells × 4 B × n_maps))`, clamped to [16, 500] | a 2 GB working block stays far below 16 GB alongside the OS, the PCA basis and the UI. Example: 1M masked cells × 3 maps → 166 samples per chunk |
| Accumulation | running counts (exceedance), running sums (mean/variance), per-cell 64-bin histograms (percentiles) | percentiles without storing all 2,000 maps. The histograms cost 64 × 2 B × cells ≈ 128 MB per map per million cells |
| Points of interest | store every sample | only a few dozen points, so exact percentiles are cheap |
| Seed | fixed per query and logged | the same query gives the same answer, which matters in a demo |

Target runtime *(tune)*: under 60 s for 2,000 samples on 1M cells.

---

## 6. Confidence rule (draft)

Every answer carries **High / Medium / Low** confidence per output and per point of interest.
The rule is **weakest link**: the lowest of the three checks wins.

*Why weakest link:* it's easy to explain to an operator ("low because this breach is bigger than
anything we trained on"), and a weighted score could hide one bad signal behind two good ones.

| Check | What it measures | High | Medium | Low |
|---|---|---|---|---|
| **S — LOOCV skill** | how well the emulator did on held-out runs, for this output | extent F1 ≥ 0.85; arrival RMSE ≤ 10% of mean arrival | F1 0.70–0.85; arrival RMSE 10–20% | below that |
| **C — query coverage** | how far the query is from the training runs: r = distance to nearest training point ÷ median nearest-neighbour distance within the design (standardised inputs) | r ≤ 1 | 1 < r ≤ 2 | r > 2, **or any input outside the training box** (extrapolation) |
| **U — prediction spread** | width of the 90% interval at the location | depth width ≤ 0.5 m or ≤ 50% of the mean; arrival width ≤ 15 min or ≤ 20% | depth ≤ 1.0 m / 100%; arrival ≤ 30 min / 40% | wider |

- The skill check S uses the stored LOOCV result for that map type and domain, split into zones if
  the team adds them. It doesn't change per query.
- In unknown-breach mode, check C uses the fraction of Monte Carlo samples inside the training box:
  ≥ 95% → High, ≥ 80% → Medium, else Low.
- All cut-offs are *(tune)* and live in config. Recalibrate them after the first LOOCV on real runs.
- The label text always states the reason, e.g. `Low (C: query outside trained V_w range)`.
- If any input has `status: placeholder`, confidence is capped at **Medium** and the output is
  labelled "placeholder inputs".

---

## 7. Synthetic test world

A cheap stand-in for the 2D model, used to test M5 end to end before real runs exist. It is a
function, not a simulation: given (V_w, B_ave, T_f), it returns the four summary maps in
milliseconds. Its behaviour is known, so we can check that the emulator recovers it.

### 7.1 Valley shape (plain words)

- A single valley **40 km long**, running from the dam at the top to an open plain at the bottom.
- **Upper 15 km — steep gorge.** Narrow V-shaped section, bed slope about 2%, floor about 50 m wide,
  steep walls. Water gets deep and fast here but can't spread out.
- **One constriction at about 10 km.** The floor narrows to half its width for 500 m. Water backs
  up behind it, so depth rises sharply just upstream.
- **Middle 15 km — trapezoidal valley.** Floor about 300 m wide, slope about 0.8%.
- **One raised terrace (the "town").** It sits on one bank at about 22 km, 3 m above the valley floor.
  It stays completely dry until the flow tops the terrace edge, then floods quickly. This threshold
  is deliberate: a linear method can't reproduce it.
- **Lower 10 km — fan/plain.** Slope about 0.3%, floor widening to 2 km. Water spreads out, becomes
  shallow and slows down.
- **Grids:** a *small* version (400 × 100 cells at 100 m × 50 m, 40k cells) for quick tests, and a
  *large* version of about 1M cells for the memory and runtime tests.

### 7.2 How the outputs respond (plain words)

First compute a peak-flow proxy. Peak flow grows with volume and with breach width, and shrinks
as failure time gets longer (a slower breach releases the same water over more time). Peak flow
then shrinks gradually with distance downstream (attenuation), faster where the valley is wide.

- **Extent**
  - grows with volume, but less than proportionally: doubling V_w should widen the flood noticeably, not double it;
  - grows a little with breach width and a little as failure time gets shorter;
  - is capped by the valley walls in the gorge, so it barely changes there;
  - jumps when the flow tops the terrace edge;
  - spreads widely on the plain.
- **Depth**
  - rises with peak flow;
  - highest in the gorge and just upstream of the constriction;
  - drops steadily across the plain;
  - zero on the terrace until it is overtopped, then quickly 0.5–1.5 m.
- **Arrival time**
  - increases with distance;
  - comes earlier for larger volume and wider breach (deeper water travels faster);
  - comes later for longer failure time: near the dam, arrival is shifted by roughly a fraction of T_f, and far downstream the effect fades as attenuation dominates;
  - cells that never reach the arrival threshold get "no arrival".
- **Velocity**
  - rises with peak flow;
  - highest in the gorge and at the constriction;
  - low on the terrace and the plain.

### 7.3 Rules for the test world

- Deterministic, with no random noise, like the real model. An optional small noise switch lets us
  test the noise floor.
- All responses are **monotonic** in the directions above, so the tests in §8 can check direction as
  well as size.
- It lives in `m5/testworld.py` and has its own unit tests (e.g. the terrace stays dry below the
  overtopping flow).

---

## 8. Acceptance tests

Each test must pass on the synthetic world (30-run LHS, same settings) and, once available, on the
real 30 runs.

| # | Test | Pass condition | Why |
|---|---|---|---|
| A1 | **GP beats linear blending** | LOOCV RMSE on Ω at least **10% lower** than both baselines, for max depth and arrival; extent F1 not lower than either baseline | if a GP can't beat simple methods, the simple method is easier to defend to judges |
| A2 | **Interval calibration** | the nominal **90%** interval covers **80–95%** of held-out true values, over wet cells and separately over points of interest | < 80% means overconfident (dangerous for warnings); > 95% means too wide to be useful |
| A3 | Monotonic response | on the synthetic world, extent and depth at points of interest rise with V_w, and arrival falls with V_w, in ≥ 95% of paired queries | catches sign errors and bad transforms |
| A4 | Terrace threshold | the terrace is classified correctly (flooded or dry) in ≥ 90% of held-out runs | the non-linear feature linear blending should miss |
| A5 | PCA not the bottleneck | PCA reconstruction RMSE ≤ ½ of the emulator LOOCV RMSE | if reconstruction dominates, add components before tuning GPs |
| A6 | Extrapolation flag | queries 10% outside the training box are labelled confidence C = Low | the confidence rule must fire when it should |
| A7 | Performance | scenario query < 2 s; unknown-breach 2,000 samples < 60 s; peak memory < 8 GB, all on the large test world on a 16 GB machine | the tool has to run live in a demo |
| A8 | Placeholder propagation | any placeholder input caps confidence at Medium and labels the output | keeps unverified numbers from looking authoritative |

**Baselines for A1** (both use the same inputs and LOOCV folds):

1. **Linear-in-scores:** the same PCA basis, with each component score fitted by ordinary linear
   regression on the standardised inputs.
2. **Nearest-run blending:** an inverse-distance-weighted average of the 3 nearest training maps in
   input space.

*Why two baselines:* the first isolates whether the GP adds anything over a linear fit in the same
basis. The second is the method a sceptical reviewer would propose first.

**If A2 fails:** calibrate one scale factor k on σ via LOOCV, so the coverage hits 90%. Record k,
apply it to all queries, and rerun A2 on the held-out runs.

---

## 9. Open decisions for the team

1. Should `Q_p` become a fourth input? Adding it makes the input space 4D with only 30 runs;
   leaving it out assumes the hydrograph shape comes from V_w, B_ave and T_f alone.
2. Far-field and near-field: two independent emulator sets (default), or near-field conditioned on
   far-field output?
3. Confidence cut-offs (§6): who signs off, and against which real validation event?
4. Distribution choice for unknown-breach mode once M2 can give a best estimate.
5. Whether the 5 extra held-out runs are affordable.