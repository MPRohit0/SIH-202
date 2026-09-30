// Compare page engine (design/target-state-preview): two synthetic "solvers"
// (FM and SPH) evaluated on real 2D grids, plus a small LOOCV + held-out-run
// emulator-vs-physics harness, so the /compare page has live grid-computed
// cards instead of a 1-D profile with noise sprinkled on top.
//
// Everything here is invented and documented as such (see the plan/report):
// there is no real SPH or D-Flow FM run behind these numbers. The point is
// internal consistency (deterministic, seeded, monotonic where it matters)
// and a believable range for every metric in m5_specs.md §6/§8.
import {mulberry32, hashSeed, weylPoints} from './rng';
import {getWorld, widthAt, chainageToLonLat, type World, type ScenarioType, type Poi} from './world';
import {computeProfile, seedForInputs, type EngineInputs} from './physics';
import {renderGrid} from './raster';
import {buildGorgeTerrain, packScene3d} from './scene3d';
import type {CompareResponse, Scene3DResponse} from './types';

export type Domain = 'nf1' | 'far';
export const GRID_NX = 80;
export const GRID_NY = 60;
const CELL_M: Record<Domain, number> = {nf1: 15, far: 150};
export const TIME_FRAME_COUNT = 13;
export const THRESHOLDS_M = [0.05, 0.1, 0.3];
export const DEFAULT_THRESHOLD_M = 0.3;

export type SolverParams = {halfWidth: number; peak: number; decay: number; vk: number; frontDelayFrac?: number};
// Ported from the pre-engine generator's gen_nearfield_pair() shape parameters
// (docs/progress.md / the plan for this page): half_width controls how quickly
// depth tapers from the centreline to the bank (bigger = broader wet channel);
// peak is the solver's own reference depth (m) at chainage 0 in a "canonical"
// scenario (see CANONICAL_PEAK_DEPTH_M below); decay is the exponential
// downstream attenuation rate over the domain; vk is the v = vk*sqrt(depth)
// coefficient used to turn local depth into a wetting-front celerity.
export const FM_PARAMS: SolverParams = {halfWidth: 0.19, peak: 3.0, decay: 1.1, vk: 1.7};
export const SPH_PARAMS: SolverParams = {halfWidth: 0.14, peak: 3.6, decay: 1.5, vk: 2.0, frontDelayFrac: 0.05};
// The reference peak depth (m) that FM_PARAMS.peak/SPH_PARAMS.peak assume.
// Grids are scaled by (actual sourcePeakDepth at this site/inputs) / this
// constant, so bigger sites/inputs produce deeper synthetic grids.
const CANONICAL_PEAK_DEPTH_M = 3.0;
const WET_THRESHOLD_M = 0.03; // m5_specs.md §4 "Ω" wet-cell mask for RMSE/RMSLE

function clamp01(x: number): number { return Math.max(0, Math.min(1, x)); }

/** Smooth, bounded (~[-1,1]) pseudo-random spatial pattern: a sum of three
 * out-of-phase sinusoids over (row, col), phase/frequency seeded per run so
 * different folds/held-out runs get visually different but still smooth
 * (spatially correlated) bias fields -- not per-cell independent noise. */
function smoothPattern(seedKey: string): (row: number, col: number) => number {
  const rand = mulberry32(hashSeed(seedKey));
  const fa = 0.08 + rand() * 0.12, fb = 0.1 + rand() * 0.15, fc = 0.05 + rand() * 0.1;
  const pa = rand() * Math.PI * 2, pb = rand() * Math.PI * 2, pc = rand() * Math.PI * 2;
  return (row: number, col: number) => 0.5 * Math.sin(fa * row + pa) + 0.35 * Math.sin(fb * col + pb) + 0.15 * Math.sin(fc * (row + col) + pc);
}

export type SolvedGrid = {
  nx: number; ny: number; cellM: number;
  depthBase: Float32Array; // fully-developed local depth (m), ignoring travel time
  arrivalS: Float32Array; // per-cell wetting-front arrival (s); Infinity where never wet
  maxArrivalS: number;
};

/** Evaluates one synthetic solver over the domain grid: a smooth downstream
 * decay (function of chainage) times a Gaussian-ish cross-channel taper
 * (function of distance from the centreline, clipped at the local valley
 * width), plus a travelling-front arrival time derived from v = vk*sqrt(depth). */
export function solveGrid(world: World, inputs: EngineInputs, scenarioType: ScenarioType, domain: Domain, params: SolverParams): SolvedGrid {
  const cellM = CELL_M[domain];
  const nx = GRID_NX, ny = GRID_NY;
  const domainLengthM = ny * cellM;
  const peak0 = computeProfile(world, inputs, scenarioType, 0).depth_m;
  const scale = Math.max(peak0, 0.01) / CANONICAL_PEAK_DEPTH_M;
  const depthBase = new Float32Array(nx * ny);
  const arrivalS = new Float32Array(nx * ny);
  let maxArrivalS = 0;
  for (let row = 0; row < ny; row++) {
    const chainageM = row * cellM;
    const chainageFrac = chainageM / Math.max(domainLengthM, 1);
    const halfWidthCells = Math.min(nx / 2 - 2, (widthAt(world, chainageM) / cellM) / 2);
    const localDepthFull = params.peak * scale * Math.exp(-params.decay * chainageFrac);
    const celerity = Math.max(0.3, params.vk * Math.sqrt(Math.max(localDepthFull, 0.05)));
    const frontDelayS = (params.frontDelayFrac ?? 0) * Math.max(inputs.failure_time_s, 1);
    const rowArrival = chainageM / celerity + frontDelayS;
    for (let col = 0; col < nx; col++) {
      const idx = row * nx + col;
      const distCells = Math.abs(col - nx / 2);
      const colFrac = distCells / Math.max(halfWidthCells, 1);
      const shape = colFrac <= 1.5 ? Math.exp(-(colFrac * colFrac) / (params.halfWidth * params.halfWidth)) : 0;
      if (shape < 0.02) { depthBase[idx] = 0; arrivalS[idx] = Number.POSITIVE_INFINITY; continue; }
      const d = localDepthFull * shape;
      depthBase[idx] = d;
      arrivalS[idx] = rowArrival;
      if (Number.isFinite(rowArrival) && rowArrival > maxArrivalS) maxArrivalS = rowArrival;
    }
  }
  return {nx, ny, cellM, depthBase, arrivalS, maxArrivalS};
}

/** Depth at the given time: 0 before the wetting front arrives at that cell,
 * ramping to the fully-developed depth over a fraction of the time window
 * after arrival -- "depth(t) is a travelling front" (the plan). */
function depthAtTime(grid: SolvedGrid, idx: number, tS: number, riseTimeS: number): number {
  const arrival = grid.arrivalS[idx];
  if (!Number.isFinite(arrival) || tS < arrival) return 0;
  return grid.depthBase[idx] * clamp01((tS - arrival) / Math.max(riseTimeS, 1));
}

/** Running-maximum depth reached by time tS (i.e. max over [0, tS], not just
 * the instantaneous frame) -- so the time slider moves the stats, per the plan. */
function maxDepthByTime(grid: SolvedGrid, tS: number, riseTimeS: number): Float32Array {
  const out = new Float32Array(grid.nx * grid.ny);
  for (let i = 0; i < out.length; i++) out[i] = depthAtTime(grid, i, tS, riseTimeS);
  return out;
}

export function timeFrames(timeWindowS: number): number[] {
  return Array.from({length: TIME_FRAME_COUNT}, (_, i) => (i / (TIME_FRAME_COUNT - 1)) * timeWindowS);
}

export type GridStats = {
  iou: number; f1_0_3: number; tpr: number; fpr: number;
  depth_rmse_wet_m: number; depth_rmsle: number; peak_depth_bias_m: number; arrival_mae_s: number; velocity_mae_ms: number;
};

/** All metrics defined by the plan for the SPH-vs-FM card, computed from two
 * already-time-sliced depth grids (FM is the reference/"truth" side). */
export function gridStats(sphDepth: Float32Array, fmDepth: Float32Array, sphGrid: SolvedGrid, fmGrid: SolvedGrid, thresholdM: number): GridStats {
  let tp = 0, fp = 0, fn = 0, tn = 0;
  let sqDepthDiff = 0, logSqDiff = 0, wetBothCount = 0, absArrivalDiff = 0, arrivalCount = 0, absVelDiff = 0;
  let maxSph = 0, maxFm = 0;
  for (let i = 0; i < fmDepth.length; i++) {
    const sphWet = sphDepth[i] > thresholdM, fmWet = fmDepth[i] > thresholdM;
    if (sphWet && fmWet) tp++; else if (sphWet && !fmWet) fp++; else if (!sphWet && fmWet) fn++; else tn++;
    if (sphDepth[i] > WET_THRESHOLD_M || fmDepth[i] > WET_THRESHOLD_M) {
      const diff = sphDepth[i] - fmDepth[i];
      sqDepthDiff += diff * diff;
      logSqDiff += (Math.log1p(sphDepth[i]) - Math.log1p(fmDepth[i])) ** 2;
      wetBothCount++;
      const sphV = sphGrid.depthBase[i] > 0 ? 1.7 * Math.sqrt(sphDepth[i]) : 0;
      const fmV = fmGrid.depthBase[i] > 0 ? 1.7 * Math.sqrt(fmDepth[i]) : 0;
      absVelDiff += Math.abs(sphV - fmV);
    }
    if (sphWet && fmWet && Number.isFinite(sphGrid.arrivalS[i]) && Number.isFinite(fmGrid.arrivalS[i])) {
      absArrivalDiff += Math.abs(sphGrid.arrivalS[i] - fmGrid.arrivalS[i]);
      arrivalCount++;
    }
    if (sphDepth[i] > maxSph) maxSph = sphDepth[i];
    if (fmDepth[i] > maxFm) maxFm = fmDepth[i];
  }
  const union = tp + fp + fn;
  return {
    iou: union > 0 ? tp / union : 1,
    f1_0_3: (2 * tp + fp + fn) > 0 ? (2 * tp) / (2 * tp + fp + fn) : 1,
    tpr: (tp + fn) > 0 ? tp / (tp + fn) : 1,
    fpr: (fp + tn) > 0 ? fp / (fp + tn) : 0,
    depth_rmse_wet_m: wetBothCount ? Math.sqrt(sqDepthDiff / wetBothCount) : 0,
    depth_rmsle: wetBothCount ? Math.sqrt(logSqDiff / wetBothCount) : 0,
    peak_depth_bias_m: maxSph - maxFm,
    arrival_mae_s: arrivalCount ? absArrivalDiff / arrivalCount : 0,
    velocity_mae_ms: wetBothCount ? absVelDiff / wetBothCount : 0,
  };
}

function gridBounds(world: World, ny: number, cellM: number): [[number, number], [number, number]] {
  const domainLengthM = ny * cellM;
  const [lonA, latA] = chainageToLonLat(world, 0);
  const [lonB, latB] = chainageToLonLat(world, domainLengthM);
  const maxW = Math.max(...world.reaches.map(r => r.width_m));
  const padDeg = maxW / 2 / 111320;
  return [[Math.min(latA, latB) - padDeg, Math.min(lonA, lonB) - padDeg], [Math.max(latA, latB) + padDeg, Math.max(lonA, lonB) + padDeg]];
}

function layerRef(layerId: string, dataUrl: string, bounds: [[number, number], [number, number]], styleId: string, unit: string | null) {
  return {layer_id: layerId, type: 'raster_png', url: dataUrl, bounds_latlng: bounds, style_id: styleId, unit, available: true};
}

function poisInDomain(world: World, ny: number, cellM: number): Poi[] {
  return world.pois.filter(p => p.chainage_m <= ny * cellM);
}

// --- Emulator-vs-physics (LOOCV + held-out runs) ------------------------

export type EmulatorRunKind = 'loocv' | 'holdout';
export type EmulatorRunSummary = {run_id: string; kind: EmulatorRunKind; label: string};

const N_LOOCV = 30;
const N_HOLDOUT = 5;
// Prediction bias / reported-uncertainty model (all invented, documented in
// the report): the "prediction" is truth times (1 + smooth pattern * bias
// fraction); the reported sigma is a separate, smaller fraction of the local
// depth so the nominal 90% interval (±1.645·sigma) covers roughly 90% of
// wet cells when the run is inside the trained design (A2, m5_specs §8) --
// and covers less than that for a run forced outside the training box
// (HO-4), where the true error is inflated by EXTRAPOLATION_ERROR_MULT but
// the reported sigma is not (a GP is overconfident when extrapolating).
const BIAS_FRAC_DEPTH = 0.14;
// sigma = SIGMA_FRAC_DEPTH * local depth. Chosen empirically (see the report)
// so that Z90*sigma sits at the bias pattern's own 90th percentile magnitude,
// landing aggregate 90% interval coverage on real wet cells close to 90%
// (m5_specs.md §8 A2's 80-95% band) when the query is inside the trained
// design -- HO-4 (below) is the deliberate exception.
const SIGMA_FRAC_DEPTH = 0.062;
const BIAS_FRAC_ARRIVAL = 0.1;
const SIGMA_FRAC_ARRIVAL = 0.045;
const LINEAR_BIAS_MULT = 5.5; // gp_vs_linear: the linear baseline's bias is this much bigger
const EXTRAPOLATION_ERROR_MULT = 3.0;
const Z90 = 1.645;

function inputRanges(world: World): Array<[number, number]> {
  return world.emulatorInputs.map(r => [r.low, r.high]);
}

function standardize(world: World, inputs: EngineInputs): number[] {
  const ranges = inputRanges(world);
  const names = world.emulatorInputs.map(r => r.name);
  return names.map((n, i) => {
    const [lo, hi] = ranges[i];
    return hi > lo ? ((inputs as any)[n] - lo) / (hi - lo) : 0;
  });
}

function euclidean(a: number[], b: number[]): number {
  return Math.sqrt(a.reduce((s, v, i) => s + (v - b[i]) ** 2, 0));
}

/** The 30-run LHS design (Weyl low-discrepancy points over the site's
 * declared input ranges, m5_specs §7/§8: "30-run LHS"), fixed per site so
 * the same site always trains on the same 30 points. */
export function trainingDesign(world: World): EngineInputs[] {
  const ranges = inputRanges(world);
  const points = weylPoints(N_LOOCV, 3, hashSeed(`${world.site_id}|loocv_design`) % 997);
  return points.map(p => Object.fromEntries(world.emulatorInputs.map((r, i) => [r.name, ranges[i][0] + p[i] * (ranges[i][1] - ranges[i][0])])) as unknown as EngineInputs);
}

/** Five held-out runs (HO-1..HO-5), distinct from the training design. HO-4
 * is deliberately placed 10% beyond the trained V_w max (m5_specs §7 A6 /
 * the plan), so it exercises the "outside the training box" confidence path. */
export function heldOutRuns(world: World): EngineInputs[] {
  const ranges = inputRanges(world);
  const points = weylPoints(N_HOLDOUT, 3, (hashSeed(`${world.site_id}|holdout`) % 997) + 500);
  const runs = points.map(p => Object.fromEntries(world.emulatorInputs.map((r, i) => [r.name, ranges[i][0] + p[i] * (ranges[i][1] - ranges[i][0])])) as unknown as EngineInputs);
  const vwRange = ranges[0];
  (runs[3] as any).water_volume_m3 = vwRange[1] * 1.1; // HO-4 (index 3): 10% above the trained max
  return runs;
}

function coverageRatio(world: World, design: EngineInputs[], query: EngineInputs): number {
  const std = design.map(d => standardize(world, d));
  const q = standardize(world, query);
  // Outside the [0,1] box on any input -> extrapolation, r forced > 2 (Low).
  if (q.some(v => v < 0 || v > 1)) return 3;
  const nnDistances = std.map((p, i) => Math.min(...std.filter((_, j) => j !== i).map(o => euclidean(p, o))));
  nnDistances.sort((a, b) => a - b);
  const medianNn = nnDistances[Math.floor(nnDistances.length / 2)] || 1e-6;
  const dQuery = Math.min(...std.map(o => euclidean(q, o)));
  return dQuery / Math.max(medianNn, 1e-6);
}

export type FoldGrids = {
  truth: SolvedGrid; predGp: Float32Array; predLinear: Float32Array; sigmaDepth: Float32Array;
  predArrivalGp: Float32Array; sigmaArrival: Float32Array;
};

function buildFold(world: World, scenarioType: ScenarioType, domain: Domain, inputs: EngineInputs, seedKey: string, extrapolationMult: number): FoldGrids {
  const truth = solveGrid(world, inputs, scenarioType, domain, FM_PARAMS);
  const n = truth.nx * truth.ny;
  const pattern = smoothPattern(seedKey);
  const linearPattern = smoothPattern(`${seedKey}|linear`);
  const predGp = new Float32Array(n), predLinear = new Float32Array(n), sigmaDepth = new Float32Array(n);
  const predArrivalGp = new Float32Array(n), sigmaArrival = new Float32Array(n);
  for (let row = 0; row < truth.ny; row++) {
    for (let col = 0; col < truth.nx; col++) {
      const idx = row * truth.nx + col;
      const d = truth.depthBase[idx];
      const pGp = pattern(row, col);
      const pLin = linearPattern(row, col);
      predGp[idx] = Math.max(0, d * (1 + pGp * BIAS_FRAC_DEPTH * extrapolationMult));
      predLinear[idx] = Math.max(0, d * (1 + pLin * BIAS_FRAC_DEPTH * LINEAR_BIAS_MULT));
      sigmaDepth[idx] = SIGMA_FRAC_DEPTH * d;
      const a = truth.arrivalS[idx];
      if (Number.isFinite(a)) {
        predArrivalGp[idx] = Math.max(0, a * (1 + pGp * BIAS_FRAC_ARRIVAL * extrapolationMult));
        sigmaArrival[idx] = SIGMA_FRAC_ARRIVAL * a;
      } else { predArrivalGp[idx] = a; sigmaArrival[idx] = 0; }
    }
  }
  return {truth, predGp, predLinear, sigmaDepth, predArrivalGp, sigmaArrival};
}

export type FoldMetrics = {rmse_m: number; f1: number; iou: number; arrival_rmse_s: number; coverage_90: number};

function foldMetrics(fold: FoldGrids, thresholdM: number, useLinear: boolean): FoldMetrics {
  const pred = useLinear ? fold.predLinear : fold.predGp;
  let tp = 0, fp = 0, fn = 0, sqDiff = 0, wetCount = 0, sqArrival = 0, arrivalCount = 0, covered = 0, coverCount = 0;
  for (let i = 0; i < pred.length; i++) {
    const truthWet = fold.truth.depthBase[i] > thresholdM, predWet = pred[i] > thresholdM;
    if (truthWet && predWet) tp++; else if (predWet && !truthWet) fp++; else if (truthWet && !predWet) fn++;
    if (fold.truth.depthBase[i] > WET_THRESHOLD_M || pred[i] > WET_THRESHOLD_M) {
      sqDiff += (pred[i] - fold.truth.depthBase[i]) ** 2; wetCount++;
      if (!useLinear) {
        const width = Z90 * fold.sigmaDepth[i];
        if (Math.abs(fold.truth.depthBase[i] - pred[i]) <= width) covered++;
        coverCount++;
      }
    }
    if (Number.isFinite(fold.truth.arrivalS[i]) && Number.isFinite(fold.predArrivalGp[i]) && (truthWet || predWet)) {
      sqArrival += (fold.predArrivalGp[i] - fold.truth.arrivalS[i]) ** 2; arrivalCount++;
    }
  }
  const union = tp + fp + fn;
  return {
    rmse_m: wetCount ? Math.sqrt(sqDiff / wetCount) : 0,
    f1: (2 * tp + fp + fn) > 0 ? (2 * tp) / (2 * tp + fp + fn) : 1,
    iou: union > 0 ? tp / union : 1,
    arrival_rmse_s: arrivalCount ? Math.sqrt(sqArrival / arrivalCount) : 0,
    coverage_90: coverCount ? covered / coverCount : 1,
  };
}

export type ConfidenceComponents = {validation_skill: 'GOOD' | 'FAIR' | 'POOR'; query_coverage: 'INSIDE' | 'EDGE' | 'OUTSIDE'; spread: 'NARROW' | 'MEDIUM' | 'WIDE'};
export type ConfidenceResult = {level: 'HIGH' | 'MODERATE' | 'LOW'; components: ConfidenceComponents; reason_key: string};

const LEVEL_RANK = {HIGH: 0, MODERATE: 1, LOW: 2} as const;
function worstLevel(...levels: Array<'HIGH' | 'MODERATE' | 'LOW'>): 'HIGH' | 'MODERATE' | 'LOW' {
  return levels.reduce((a, b) => (LEVEL_RANK[b] > LEVEL_RANK[a] ? b : a), 'HIGH' as const);
}

/** m5_specs.md §6 weakest-link confidence rule: S (LOOCV skill, from the fold
 * summary across the whole 30-run design -- doesn't vary per query), C (query
 * coverage, this run's distance from the training design), U (this run's
 * reported 90% interval width, as a fraction of the local mean). */
export function computeCompareConfidence(
  loocvSummary: {medianF1: number; medianArrivalRmseFracOfMean: number},
  coverageR: number, meanDepthWidthFrac: number, meanArrivalWidthFrac: number,
): ConfidenceResult {
  const sLevel: 'HIGH' | 'MODERATE' | 'LOW' = (loocvSummary.medianF1 >= 0.85 && loocvSummary.medianArrivalRmseFracOfMean <= 0.1) ? 'HIGH'
    : (loocvSummary.medianF1 >= 0.7 && loocvSummary.medianArrivalRmseFracOfMean <= 0.2) ? 'MODERATE' : 'LOW';
  const cLevel: 'HIGH' | 'MODERATE' | 'LOW' = coverageR <= 1 ? 'HIGH' : coverageR <= 2 ? 'MODERATE' : 'LOW';
  const uLevel: 'HIGH' | 'MODERATE' | 'LOW' = (meanDepthWidthFrac <= 0.5 && meanArrivalWidthFrac <= 0.2) ? 'HIGH'
    : (meanDepthWidthFrac <= 1.0 && meanArrivalWidthFrac <= 0.4) ? 'MODERATE' : 'LOW';
  const level = worstLevel(sLevel, cLevel, uLevel);
  const components: ConfidenceComponents = {
    validation_skill: sLevel === 'HIGH' ? 'GOOD' : sLevel === 'MODERATE' ? 'FAIR' : 'POOR',
    query_coverage: cLevel === 'HIGH' ? 'INSIDE' : cLevel === 'MODERATE' ? 'EDGE' : 'OUTSIDE',
    spread: uLevel === 'HIGH' ? 'NARROW' : uLevel === 'MODERATE' ? 'MEDIUM' : 'WIDE',
  };
  const worst = level === sLevel ? 'S' : level === cLevel ? 'C' : 'U';
  const reasonDetail = worst === 'S' ? `LOOCV skill F1=${loocvSummary.medianF1.toFixed(2)}, arrival RMSE ${(loocvSummary.medianArrivalRmseFracOfMean * 100).toFixed(0)}% of mean arrival`
    : worst === 'C' ? (coverageR > 2 ? 'query outside trained V_w range' : `query coverage r=${coverageR.toFixed(2)}`)
    : `90% interval spans ${(meanDepthWidthFrac * 100).toFixed(0)}% of mean depth`;
  const levelLabel = level === 'HIGH' ? 'High' : level === 'MODERATE' ? 'Moderate' : 'Low';
  return {level, components, reason_key: `${levelLabel} (${worst}: ${reasonDetail})`};
}

// --- Top-level entry points ----------------------------------------------

export type CompareOpts = {domain?: Domain; threshold?: number; tIndex?: number; runId?: string};

export type WorkbenchRun = {
  run_id: string; kind: EmulatorRunKind; label: string; inputs: EngineInputs;
  truthScene: Scene3DResponse; predScene: Scene3DResponse;
  truthLayerUrl: string; predLayerUrl: string; diffLayerUrl: string;
  metrics: FoldMetrics & {rmse_arrival_pct_of_mean: number};
  confidence: ConfidenceResult;
  poiPairs: Array<{poi_id: string; name: string; truth_m: number; pred_m: number}>;
};

export type CompareWorkbench = {
  site_id: string; domain: Domain; cellM: number; nx: number; ny: number;
  timeWindowS: number; frameTimesS: number[]; tIndex: number; threshold: number;
  bounds: [[number, number], [number, number]];
  sphDepthNow: Float32Array; fmDepthNow: Float32Array;
  sphScene: Scene3DResponse; fmScene: Scene3DResponse;
  sphLayerUrl: string; fmLayerUrl: string; diffLayerUrl: string;
  stats: GridStats & {threshold_m: number};
  probes: Array<{poi_id: string; name: string; arrival_delft3d_s: number; arrival_sph_s: number; diff_s: number}>;
  runs: EmulatorRunSummary[];
  selectedRun: WorkbenchRun;
  gpVsLinear: {iou_median_gp: number; iou_median_linear: number; arrival_mae_s_gp: number; arrival_mae_s_linear: number};
};

const RISE_TIME_FRAC = 0.15;

function buildScenePair(world: World, domain: Domain, cellM: number, depthA: Float32Array, depthB: Float32Array, queryIdA: string, queryIdB: string) {
  const terrain = buildGorgeTerrain(world, GRID_NX, GRID_NY, cellM);
  const floodA = new Float32Array(terrain.bed.length), floodB = new Float32Array(terrain.bed.length);
  for (let i = 0; i < terrain.bed.length; i++) { floodA[i] = terrain.bed[i] + depthA[i]; floodB[i] = terrain.bed[i] + depthB[i]; }
  return {
    sceneA: packScene3d(GRID_NX, GRID_NY, cellM, terrain.bed, floodA, terrain.minElevM, terrain.maxElevM, queryIdA),
    sceneB: packScene3d(GRID_NX, GRID_NY, cellM, terrain.bed, floodB, terrain.minElevM, terrain.maxElevM, queryIdB),
  };
}

function loocvSummary(world: World, scenarioType: ScenarioType, domain: Domain, thresholdM: number) {
  const design = trainingDesign(world);
  const f1s: number[] = []; const arrivalFracs: number[] = [];
  for (let i = 0; i < design.length; i++) {
    const fold = buildFold(world, scenarioType, domain, design[i], `${world.site_id}|loocv|${i}`, 1);
    const m = foldMetrics(fold, thresholdM, false);
    f1s.push(m.f1);
    const meanArrival = mean(Array.from(fold.truth.arrivalS).filter(Number.isFinite));
    arrivalFracs.push(meanArrival > 0 ? m.arrival_rmse_s / meanArrival : 0);
  }
  f1s.sort((a, b) => a - b); arrivalFracs.sort((a, b) => a - b);
  return {medianF1: f1s[Math.floor(f1s.length / 2)], medianArrivalRmseFracOfMean: arrivalFracs[Math.floor(arrivalFracs.length / 2)], design};
}

function mean(xs: number[]): number { return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0; }

function gpVsLinearSummary(world: World, scenarioType: ScenarioType, domain: Domain, thresholdM: number, design: EngineInputs[]) {
  const gpIous: number[] = [], linIous: number[] = [], gpArrivals: number[] = [], linArrivals: number[] = [];
  for (let i = 0; i < design.length; i++) {
    const fold = buildFold(world, scenarioType, domain, design[i], `${world.site_id}|loocv|${i}`, 1);
    gpIous.push(foldMetrics(fold, thresholdM, false).iou);
    linIous.push(foldMetrics(fold, thresholdM, true).iou);
    gpArrivals.push(foldMetrics(fold, thresholdM, false).arrival_rmse_s);
    // Linear baseline's arrival error uses the same bias-amplification idea as depth (LINEAR_BIAS_MULT).
    linArrivals.push(foldMetrics(fold, thresholdM, false).arrival_rmse_s * LINEAR_BIAS_MULT);
  }
  const median = (xs: number[]) => { const s = [...xs].sort((a, b) => a - b); return s[Math.floor(s.length / 2)]; };
  return {iou_median_gp: median(gpIous), iou_median_linear: median(linIous), arrival_mae_s_gp: median(gpArrivals), arrival_mae_s_linear: median(linArrivals)};
}

/** Builds every grid, scene, metric and confidence value the Compare page
 * needs, for one site/scenario/inputs/opts combination. buildCompareResponse
 * (below) extracts the CompareResponse subset of this for the contract; the
 * full workbench (grids, scenes, POI pairs, run list) is exposed separately
 * through source.getCompareWorkbench (preview-only, like getScenarioPair). */
export function buildCompareWorkbench(siteId: string, scenarioType: ScenarioType, inputs: EngineInputs, opts: CompareOpts = {}): CompareWorkbench {
  const world = getWorld(siteId);
  const domain: Domain = opts.domain ?? 'nf1';
  const threshold = opts.threshold ?? DEFAULT_THRESHOLD_M;
  const cellM = CELL_M[domain];
  const seed = seedForInputs(siteId, scenarioType, 'compare', inputs);

  const fmGrid = solveGrid(world, inputs, scenarioType, domain, FM_PARAMS);
  const sphGrid = solveGrid(world, inputs, scenarioType, domain, SPH_PARAMS);
  const timeWindowS = Math.max(fmGrid.maxArrivalS, sphGrid.maxArrivalS, 60) * 1.25;
  const frameTimesS = timeFrames(timeWindowS);
  const tIndex = Math.max(0, Math.min(TIME_FRAME_COUNT - 1, opts.tIndex ?? TIME_FRAME_COUNT - 1));
  const tS = frameTimesS[tIndex];
  const riseTimeS = RISE_TIME_FRAC * timeWindowS;

  const fmDepthNow = maxDepthByTime(fmGrid, tS, riseTimeS);
  const sphDepthNow = maxDepthByTime(sphGrid, tS, riseTimeS);
  const stats = gridStats(sphDepthNow, fmDepthNow, sphGrid, fmGrid, threshold);
  const bounds = gridBounds(world, GRID_NY, cellM);

  const {sceneA: fmScene, sceneB: sphScene} = buildScenePair(world, domain, cellM, fmDepthNow, sphDepthNow, `${siteId}__compare__${seed}__fm`, `${siteId}__compare__${seed}__sph`);
  const diffGrid = new Float32Array(fmDepthNow.length);
  for (let i = 0; i < diffGrid.length; i++) diffGrid[i] = sphDepthNow[i] - fmDepthNow[i];
  const fmLayerUrl = renderGrid(fmDepthNow, GRID_NX, GRID_NY, 'depth_p50');
  const sphLayerUrl = renderGrid(sphDepthNow, GRID_NX, GRID_NY, 'depth_p50');
  const diffLayerUrl = renderGrid(diffGrid, GRID_NX, GRID_NY, 'depth_diff');

  const probes = poisInDomain(world, GRID_NY, cellM).map(poi => {
    const rowFrom = (chainageM: number) => Math.min(GRID_NY - 1, Math.round(chainageM / cellM));
    const row = rowFrom(poi.chainage_m);
    const centreCol = Math.round(GRID_NX / 2);
    const idx = row * GRID_NX + centreCol;
    return {poi_id: poi.poi_id, name: poi.name, arrival_delft3d_s: fmGrid.arrivalS[idx], arrival_sph_s: sphGrid.arrivalS[idx], diff_s: sphGrid.arrivalS[idx] - fmGrid.arrivalS[idx]};
  });

  // --- Emulator vs physics (Card B) ---
  const {medianF1, medianArrivalRmseFracOfMean, design} = loocvSummary(world, scenarioType, domain, threshold);
  const heldOut = heldOutRuns(world);
  const runs: EmulatorRunSummary[] = [
    ...heldOut.map((_, i) => ({run_id: `HO-${i + 1}`, kind: 'holdout' as const, label: `Held-out run ${i + 1}`})),
    ...design.map((_, i) => ({run_id: `LOOCV-${i + 1}`, kind: 'loocv' as const, label: `LOOCV fold ${i + 1}`})),
  ];
  const requestedRunId = opts.runId ?? 'HO-1';
  const isHoldout = requestedRunId.startsWith('HO-');
  const runIndex = Math.max(0, parseInt(requestedRunId.split('-')[1], 10) - 1);
  const runInputs = isHoldout ? heldOut[Math.min(runIndex, heldOut.length - 1)] : design[Math.min(runIndex, design.length - 1)];
  const runKind: EmulatorRunKind = isHoldout ? 'holdout' : 'loocv';
  const extrapolationMult = (isHoldout && runIndex === 3) ? EXTRAPOLATION_ERROR_MULT : 1; // HO-4
  const fold = buildFold(world, scenarioType, domain, runInputs, `${siteId}|${requestedRunId}`, extrapolationMult);
  const foldStats = foldMetrics(fold, threshold, false);
  const meanArrival = mean(Array.from(fold.truth.arrivalS).filter(Number.isFinite));
  const r = coverageRatio(world, design, runInputs);
  const meanDepthWidthFrac = mean(Array.from(fold.truth.depthBase).filter(d => d > threshold).map((d, i) => (2 * Z90 * fold.sigmaDepth[i]) / Math.max(d, 0.01)));
  const meanArrivalWidthFrac = meanArrival > 0 ? (2 * Z90 * SIGMA_FRAC_ARRIVAL * meanArrival) / meanArrival : 0;
  const confidence = computeCompareConfidence({medianF1, medianArrivalRmseFracOfMean}, r, meanDepthWidthFrac || 0, meanArrivalWidthFrac);

  const {sceneA: truthScene, sceneB: predScene} = buildScenePair(world, domain, cellM, fold.truth.depthBase, fold.predGp, `${siteId}__${requestedRunId}__truth`, `${siteId}__${requestedRunId}__pred`);
  const foldDiff = new Float32Array(fold.predGp.length);
  for (let i = 0; i < foldDiff.length; i++) foldDiff[i] = fold.predGp[i] - fold.truth.depthBase[i];
  const truthLayerUrl = renderGrid(fold.truth.depthBase, GRID_NX, GRID_NY, 'depth_p50');
  const predLayerUrl = renderGrid(fold.predGp, GRID_NX, GRID_NY, 'depth_p50');
  const foldDiffLayerUrl = renderGrid(foldDiff, GRID_NX, GRID_NY, 'depth_diff');
  const poiPairs = poisInDomain(world, GRID_NY, cellM).map(poi => {
    const row = Math.min(GRID_NY - 1, Math.round(poi.chainage_m / cellM));
    const idx = row * GRID_NX + Math.round(GRID_NX / 2);
    return {poi_id: poi.poi_id, name: poi.name, truth_m: fold.truth.depthBase[idx], pred_m: fold.predGp[idx]};
  });

  const gpVsLinear = gpVsLinearSummary(world, scenarioType, domain, threshold, design);

  return {
    site_id: siteId, domain, cellM, nx: GRID_NX, ny: GRID_NY, timeWindowS, frameTimesS, tIndex, threshold, bounds,
    sphDepthNow, fmDepthNow, sphScene, fmScene, sphLayerUrl, fmLayerUrl, diffLayerUrl,
    stats: {...stats, threshold_m: threshold}, probes, runs,
    selectedRun: {
      run_id: requestedRunId, kind: runKind, label: runs.find(r2 => r2.run_id === requestedRunId)?.label ?? requestedRunId, inputs: runInputs,
      truthScene, predScene, truthLayerUrl, predLayerUrl, diffLayerUrl: foldDiffLayerUrl,
      metrics: {...foldStats, rmse_arrival_pct_of_mean: meanArrival > 0 ? (foldStats.arrival_rmse_s / meanArrival) * 100 : 0},
      confidence, poiPairs,
    },
    gpVsLinear,
  };
}

const DOMAIN_LABEL: Record<Domain, string> = {nf1: 'Near-field reach (NF-1)', far: 'Far-field reach'};

export function buildCompareResponse(siteId: string, scenarioType: ScenarioType, inputs: EngineInputs, opts: CompareOpts = {}): CompareResponse {
  const wb = buildCompareWorkbench(siteId, scenarioType, inputs, opts);
  const domainLengthM = wb.ny * wb.cellM;
  const caveats: CompareResponse['caveats'] = [
    {id: 'preview_simulated', severity: 'info', text_key: 'preview_simulated'},
    {id: 'arrival_proxy', severity: 'info', text_key: 'arrival_proxy'},
  ];
  if (wb.domain === 'far') caveats.push({id: 'sph_far_field_illustrative', severity: 'warning', text_key: 'sph_far_field_illustrative'});
  return {
    site_id: siteId, scenario_id: `${scenarioType}_current`,
    sph_vs_delft3d: {
      available: true, domain: `${DOMAIN_LABEL[wb.domain]}: 0-${Math.round(domainLengthM)} m`, time_window_s: Math.round(wb.timeWindowS),
      metrics: {iou: wb.stats.iou, f1_0_3: wb.stats.f1_0_3, tpr: wb.stats.tpr, fpr: wb.stats.fpr,
        depth_rmse_wet_m: wb.stats.depth_rmse_wet_m, depth_rmsle: wb.stats.depth_rmsle, peak_depth_bias_m: wb.stats.peak_depth_bias_m,
        arrival_mae_s: wb.stats.arrival_mae_s, velocity_mae_ms: wb.stats.velocity_mae_ms, threshold_m: wb.stats.threshold_m},
      probes: wb.probes,
      layers: [
        layerRef('depth_sph', wb.sphLayerUrl, wb.bounds, 'depth_p50', 'm'),
        layerRef('depth_fm', wb.fmLayerUrl, wb.bounds, 'depth_p50', 'm'),
        layerRef('depth_diff_nearfield', wb.diffLayerUrl, wb.bounds, 'depth_diff', 'm'),
      ],
      run_ids: [`${siteId}__demo__delft3d`, `${siteId}__demo__sph`],
    },
    emulator_vs_physics: {
      available: true, held_out_run_id: wb.selectedRun.run_id,
      metrics: {
        depth_rmse_wet_m: wb.selectedRun.metrics.rmse_m, f1_0_3: wb.selectedRun.metrics.f1, arrival_rmse_s: wb.selectedRun.metrics.arrival_rmse_s,
        coverage_90: wb.selectedRun.metrics.coverage_90, confidence: wb.selectedRun.confidence,
      },
      layers: [
        layerRef('depth_pred', wb.selectedRun.predLayerUrl, wb.bounds, 'depth_p50', 'm'),
        layerRef('depth_true', wb.selectedRun.truthLayerUrl, wb.bounds, 'depth_p50', 'm'),
        layerRef('depth_diff_emulator', wb.selectedRun.diffLayerUrl, wb.bounds, 'depth_diff', 'm'),
      ],
    },
    gp_vs_linear: wb.gpVsLinear,
    when_to_use_key: 'compare_when_to_use',
    caveats,
  };
}
