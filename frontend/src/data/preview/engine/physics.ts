// The demo engine's physics (design/target-state-preview). Simple, explicit
// formulas chosen for plausible, monotonic, internally-consistent behaviour
// across every screen -- not a real hydraulic solver. Every function is pure:
// same inputs -> same outputs, so the whole demo stays deterministic.
import {mulberry32, hashSeed, seedKeyFrom, weylPoints} from './rng';
import {type World, type Poi, widthAt} from './world';

export type EngineInputs = {water_volume_m3: number; breach_width_m: number; failure_time_s: number};

const VELOCITY_K = 1.6; // v = k * sqrt(depth), same shape used throughout the app

/** Peak depth (m) right at the breach (chainage 0) for a single source. */
function sourcePeakDepth(vw: number, bave: number, tf: number): number {
  return 2.2 * Math.cbrt(vw / 1.0e7) * Math.sqrt(bave / 120.0) * Math.pow(3600.0 / Math.max(tf, 1), 0.25);
}

function velocityOf(depthM: number): number {
  return VELOCITY_K * Math.sqrt(Math.max(depthM, 0));
}

/** Depth (m) at a chainage downstream of a single source (breach or
 * secondary/cascade breach), attenuating with distance and with local valley
 * width -- a gorge (narrow) attenuates slowly, a wide reach attenuates fast. */
function attenuatedDepth(world: World, sourceChainageM: number, chainageM: number, peakDepth0: number): number {
  const dx = chainageM - sourceChainageM;
  if (dx < 0) return 0;
  const width0 = widthAt(world, sourceChainageM);
  const widthHere = widthAt(world, chainageM);
  const lengthScale = world.length_m * 0.9;
  const spreadFactor = width0 / widthHere; // narrower-than-source widens => less than 1, thins the flow
  const decay = Math.exp(-dx / lengthScale);
  return Math.max(peakDepth0 * spreadFactor * decay, 0);
}

/** Local discharge (m3/s) at a chainage via continuity: Q = v * d * width. */
function dischargeAt(world: World, chainageM: number, depthM: number): number {
  return velocityOf(depthM) * depthM * widthAt(world, chainageM);
}

export type ProfilePoint = {chainage_m: number; depth_m: number; velocity_ms: number; arrival_s: number; discharge_m3s: number};

/** One deterministic single-run profile (scenario mode / one Monte Carlo
 * draw): depth/velocity/arrival/discharge at an arbitrary chainage, with the
 * Teesta cascade folded in when it fires. */
export function computeProfile(
  world: World, inputs: EngineInputs, scenarioType: string, chainageM: number,
): ProfilePoint & {cascadeTriggered: boolean} {
  const peak0 = sourcePeakDepth(inputs.water_volume_m3, inputs.breach_width_m, inputs.failure_time_s);
  let depth = attenuatedDepth(world, 0, chainageM, peak0);
  let cascadeTriggered = false;

  if (scenarioType === 'cascade' && world.cascadeDam) {
    const dam = world.cascadeDam;
    const depthAtDam = attenuatedDepth(world, 0, dam.chainage_m, peak0);
    const dischargeAtDam = dischargeAt(world, dam.chainage_m, depthAtDam);
    if (dischargeAtDam >= dam.trigger_discharge_m3s) {
      cascadeTriggered = true;
      // Secondary breach: the dam's own reservoir released over a short
      // overtopping failure, source at the dam's own chainage.
      const secondaryPeak0 = sourcePeakDepth(5_080_000 /* Teesta III gross storage, sources/teesta.yaml */, 80, 1800);
      const secondaryDepth = attenuatedDepth(world, dam.chainage_m, chainageM, secondaryPeak0);
      if (chainageM >= dam.chainage_m) depth = depth + secondaryDepth;
    }
  }

  const velocity = velocityOf(depth);
  const arrival = velocity > 0 ? chainageM / velocity : Number.POSITIVE_INFINITY;
  const discharge = dischargeAt(world, chainageM, depth);
  return {chainage_m: chainageM, depth_m: depth, velocity_ms: velocity, arrival_s: arrival, discharge_m3s: discharge, cascadeTriggered};
}

export type ConfidenceLevel = 'HIGH' | 'MODERATE' | 'LOW';
export type ConfidenceBlock = {level: ConfidenceLevel; components: Record<string, string>; reason_key: string | null};

/** Confidence follows how far the current inputs sit from each input's
 * declared [low, high] range: comfortably inside -> HIGH, near an edge ->
 * MODERATE, past the declared range (the UI lets sliders travel slightly
 * beyond it) -> LOW, naming the offending input. */
export function computeConfidence(world: World, inputs: EngineInputs): ConfidenceBlock {
  let worst: ConfidenceLevel = 'HIGH';
  let offending: string | null = null;
  const components: Record<string, string> = {};
  for (const r of world.emulatorInputs) {
    const v = inputs[r.name];
    const frac = (v - r.low) / (r.high - r.low);
    let level: ConfidenceLevel;
    if (frac < 0 || frac > 1) { level = 'LOW'; if (!offending) offending = r.name; }
    else if (frac < 0.05 || frac > 0.95) level = 'MODERATE';
    else level = 'HIGH';
    components[r.name] = level === 'HIGH' ? 'INSIDE' : level === 'MODERATE' ? 'EDGE' : 'OUTSIDE';
    if (level === 'LOW') worst = 'LOW';
    else if (level === 'MODERATE' && worst !== 'LOW') worst = 'MODERATE';
  }
  const reason_key = worst === 'LOW' ? `Low (C: query outside trained ${(offending ?? '').replace('water_volume_m3', 'lake volume').replace('breach_width_m', 'breach width').replace('failure_time_s', 'failure time')} range)`
    : worst === 'MODERATE' ? 'Moderate (an input is near the edge of its trained range)'
    : null;
  return {level: worst, components, reason_key};
}

export type EnsemblePoiResult = {
  poi: Poi; p_floods: number; median_depth_m: number; p5_depth_m: number; p95_depth_m: number;
  median_velocity_ms: number; p5_velocity_ms: number; p95_velocity_ms: number;
  median_arrival_s: number; fast_arrival_s: number; slow_arrival_s: number;
  zone: 'HIGH' | 'POSSIBLE' | 'DRY';
};

const WET_THRESHOLD_M = 0.3;
const ZONE_HIGH_P = 0.5;
const ZONE_POSSIBLE_P = 0.1;
const N_ENSEMBLE = 96;

/** Draws the fixed Monte Carlo ensemble of input points for a seed -- shared
 * by computeEnsemble() and the live probability/zone raster, so both read
 * the exact same sample set instead of drawing twice. */
export function sampleEnsembleDraws(world: World, seedKey: string): EngineInputs[] {
  const rand = mulberry32(hashSeed(seedKey));
  const points = weylPoints(N_ENSEMBLE, 3, Math.floor(rand() * 1000));
  const ranges = world.emulatorInputs;
  return points.map(p => ({
    water_volume_m3: ranges[0].low + p[0] * (ranges[0].high - ranges[0].low),
    breach_width_m: ranges[1].low + p[1] * (ranges[1].high - ranges[1].low),
    failure_time_s: ranges[2].low + p[2] * (ranges[2].high - ranges[2].low),
  }));
}

/** P(depth > 0.3m) and median depth at one chainage, from a fixed draw set. */
export function pWetAndMedianAt(world: World, scenarioType: string, draws: EngineInputs[], chainageM: number): {pWet: number; median: number} {
  const depths = draws.map(d => computeProfile(world, d, scenarioType, chainageM).depth_m).sort((a, b) => a - b);
  const pWet = depths.filter(d => d >= WET_THRESHOLD_M).length / depths.length;
  const median = depths[Math.floor(depths.length / 2)];
  return {pWet, median};
}

/** Monte Carlo ensemble over the world's declared input ranges (unknown-breach
 * mode): per-POI P(depth>0.3m), P5/median/P95 depth+velocity+arrival, and the
 * resulting HIGH/POSSIBLE zone (docs/impact_outputs.md's zone rule, ported). */
export function computeEnsemble(world: World, scenarioType: string, seedKey: string): {
  pois: EnsemblePoiResult[]; extentAreaHighM2: number; extentAreaHighPossibleM2: number; draws: EngineInputs[];
} {
  const draws = sampleEnsembleDraws(world, seedKey);
  const pois = world.pois;
  const results: EnsemblePoiResult[] = pois.map(poi => {
    const depths: number[] = []; const vels: number[] = []; const arrivals: number[] = [];
    for (const d of draws) {
      const pt = computeProfile(world, d, scenarioType, poi.chainage_m);
      depths.push(pt.depth_m); vels.push(pt.velocity_ms); arrivals.push(Number.isFinite(pt.arrival_s) ? pt.arrival_s : 1e9);
    }
    depths.sort((a, b) => a - b); vels.sort((a, b) => a - b); arrivals.sort((a, b) => a - b);
    const pct = (arr: number[], p: number) => arr[Math.min(arr.length - 1, Math.max(0, Math.round(p * (arr.length - 1))))];
    const pFloods = depths.filter(d => d >= WET_THRESHOLD_M).length / depths.length;
    const zone: 'HIGH' | 'POSSIBLE' | 'DRY' = pFloods >= ZONE_HIGH_P ? 'HIGH' : pFloods >= ZONE_POSSIBLE_P ? 'POSSIBLE' : 'DRY';
    return {
      poi, p_floods: pFloods,
      median_depth_m: pct(depths, 0.5), p5_depth_m: pct(depths, 0.05), p95_depth_m: pct(depths, 0.95),
      median_velocity_ms: pct(vels, 0.5), p5_velocity_ms: pct(vels, 0.05), p95_velocity_ms: pct(vels, 0.95),
      median_arrival_s: pct(arrivals, 0.5), fast_arrival_s: pct(arrivals, 0.05), slow_arrival_s: pct(arrivals, 0.95),
      zone,
    };
  });

  // Extent area: sample chainage every 200 m along the centreline and treat
  // the local wet width (channel width where P(wet) crosses the zone
  // threshold) as the flooded cross-section for that step.
  const step = 200;
  let areaHigh = 0, areaHighPossible = 0;
  for (let c = 0; c <= world.length_m; c += step) {
    const depths: number[] = [];
    for (const d of draws) depths.push(computeProfile(world, d, scenarioType, c).depth_m);
    depths.sort((a, b) => a - b);
    const pWet = depths.filter(d => d >= WET_THRESHOLD_M).length / depths.length;
    const w = widthAt(world, c);
    if (pWet >= ZONE_HIGH_P) areaHigh += step * w;
    if (pWet >= ZONE_POSSIBLE_P) areaHighPossible += step * w;
  }
  return {pois: results, extentAreaHighM2: areaHigh, extentAreaHighPossibleM2: areaHighPossible, draws};
}

export function seedForInputs(siteId: string, scenarioType: string, mode: string, inputs: EngineInputs, extra?: string): string {
  return seedKeyFrom({site: siteId, scenarioType, mode, ...inputs, extra});
}
