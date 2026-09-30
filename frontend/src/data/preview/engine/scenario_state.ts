// Scenario state (design/target-state-preview): the ONE function every
// on-screen number on the Dashboard and Simulation pages reads from, so the
// four KPI tiles, the downstream-impact arrival/depth readouts and the map
// legend range all move together with the timeline slider and the scenario
// controls (previously several of these were computed once per query --
// or, for the Rapid query "Water head"/"Manning's n"/"Duration"/"Released
// volume cap" fields, never read at all -- and never revisited on slider
// drag; see docs/progress.md for the trace).
//
// Not a physics solver: simple, explicit, monotonic formulas chosen so a
// bigger head/width/severity/volume raises the flood, a longer formation
// time and a rougher channel (higher Manning's n) delay and dampen it, and
// every POI stays dry until the front's travel time reaches it, then fills
// on a smooth S-curve. Every invented constant is commented at its use.
import {getWorld, widthAt} from './world';

export type ScenarioStateInputs = {
  site: string;
  t_min: number;
  severity: number; // 0-100, "how bad": a rapid-query-only knob with no direct physical control equivalent
  water_head_m: number;
  breach_width_m: number;
  formation_min: number;
  duration_min: number;
  manning_n: number;
  volume_cap_mcm: number;
};

export type Ranged = {value: number; low: number; high: number; unit: string};
export type PoiState = {poi_id: string; name: string; reached: boolean; arrival_min: Ranged; depth_m: Ranged};
export type ScenarioState = {
  flood_extent_km2: Ranged; max_depth_m: Ranged; peak_velocity_ms: Ranged;
  peak_discharge_m3s: Ranged; exposed_population: Ranged;
  pois: PoiState[];
};

// --- invented constants (kept in one place, each commented) ---
const REF_HEAD_M = 40; // = Params.defaults.head (lib/model.ts): headFactor is 1 at the on-load default, so the page doesn't jump
const REF_FORMATION_MIN = 15; // = Params.defaults.formation, same reason, used by the arrival-timing model below
const REF_MANNING_N = 0.045; // = Params.defaults.roughness, same reason
const VELOCITY_K = 1.6; // depth->velocity shape reused from engine/physics.ts's single-source relation
// Tuned (not derived) so severity=50/head=40/width=120/formation=15min/volume=100 MCM -- the
// Params.defaults the Physics-run form and Rapid query start with -- land close to the ~2 m
// depth / ~800-1000 m3/s discharge this panel already showed before this fix.
const PEAK_DEPTH_SCALE = 0.75;
// Arrival timing is deliberately decoupled from the depth-derived local velocity above: a
// literal chainage/velocity arrival time for a 32 km reach runs into hours, far past any
// sensible "Duration" slider range. Instead the front is modelled as crossing the WHOLE
// modelled reach in this many minutes at the reference formation time/Manning's n, scaled
// linearly by chainage fraction -- so "distance downstream" still monotonically delays
// arrival, formation/roughness still delay it further, and the near/mid POIs (Lachen,
// Chungthang) comfortably arrive within a default 60 min duration while the farthest ones
// only do once Duration is opened up, which is the demo-useful behaviour.
const DOMAIN_TRAVERSAL_MIN_AT_REF = 90;
const RISE_FRAC_OF_DURATION = 0.35; // local rise-to-peak takes 35% of the scenario duration once the front arrives
const RECEDE_START_FRAC = 0.75; // recession begins at 75% of the duration
const RECEDE_FLOOR_FRAC = 0.85; // and settles at 85% of peak, never fully dry within the displayed window
const SAMPLE_STEP_M = 500; // chainage sampling step for the extent/peak scan

function smoothstep(x: number): number {
  const c = Math.max(0, Math.min(1, x));
  return c * c * (3 - 2 * c);
}

/** Exported so the 3D terrain's flood animation (app/sentriq/terrain-3d.tsx)
 * reads the identical rise/recede curve the KPI tiles and POI arrivals use --
 * "the 2D map, the 3D view and the KPI tiles all read the same engine frame
 * for the same t" (docs/progress.md). */
export function timeFactor(tMin: number, arrivalMin: number, durationMin: number): number {
  if (!Number.isFinite(arrivalMin) || tMin < arrivalMin) return 0;
  const riseMin = Math.max(5, durationMin * RISE_FRAC_OF_DURATION);
  const rise = smoothstep((tMin - arrivalMin) / riseMin);
  const recedeStart = arrivalMin + durationMin * RECEDE_START_FRAC;
  if (tMin <= recedeStart) return rise;
  const recede = smoothstep((tMin - recedeStart) / Math.max(1, durationMin - recedeStart));
  return rise * (1 - recede * (1 - RECEDE_FLOOR_FRAC));
}

function ranged(value: number, spreadFrac: number, unit: string): Ranged {
  const lo = value * (1 - spreadFrac), hi = value * (1 + spreadFrac);
  return {value, low: Math.min(lo, hi), high: Math.max(lo, hi), unit};
}

type ControlInputs = Omit<ScenarioStateInputs, 'site' | 't_min'>;

/** The single driving-magnitude number every depth/discharge figure in this
 * module scales from. Factored out (from what used to be inline in
 * computeScenarioState) so the 3D flood animation can derive a plain
 * multiplier against it (severityMultiplier(), below) without duplicating
 * the formula -- "same engine, same numbers" for the KPI tiles and the 3D
 * view alike. */
export function computePeak0(inputs: ControlInputs): number {
  const severity = Math.max(0, Math.min(100, inputs.severity));
  // Fold head/volume/severity into one effective driving volume: keeps every
  // control individually monotonic without inventing a second, unrelated
  // "head" state on top of engine/physics.ts's volume-driven model.
  const severityFrac = 0.4 + 0.6 * (severity / 100); // 0.4-1.0: severity=0 still shows a small flood, not zero
  const headFactor = Math.sqrt(Math.max(inputs.water_head_m, 1) / REF_HEAD_M);
  const effectiveVolumeM3 = Math.max(inputs.volume_cap_mcm, 0.1) * 1e6 * severityFrac;
  const formationS = Math.max(inputs.formation_min, 1) * 60;
  return PEAK_DEPTH_SCALE * Math.cbrt(effectiveVolumeM3 / 1.0e7)
    * Math.sqrt(Math.max(inputs.breach_width_m, 1) / 120.0)
    * Math.pow(3600.0 / Math.max(formationS, 60), 0.25)
    * headFactor;
}

const DEFAULT_CONTROLS: ControlInputs = {
  severity: 50, water_head_m: REF_HEAD_M, breach_width_m: 120,
  formation_min: REF_FORMATION_MIN, duration_min: 60, manning_n: REF_MANNING_N, volume_cap_mcm: 100,
};

/** Dimensionless, 1.0 at Params.defaults (lib/model.ts) -- the 3D flood
 * animation multiplies the real Teesta peak-depth field by this instead of
 * recomputing a synthetic peak of its own, so at the on-load default
 * controls the 3D water sits exactly at the real depth, and it scales up/
 * down in the same direction and proportion as the KPI tiles' max_depth_m
 * when severity/head/width/volume/formation/Manning's n change. */
export function severityMultiplier(inputs: ControlInputs): number {
  const reference = computePeak0(DEFAULT_CONTROLS);
  return reference > 0 ? computePeak0(inputs) / reference : 1;
}

/** Minutes for the flood front to cross the whole modelled reach -- see its
 * use in computeScenarioState below. Exported so the 3D animation's
 * distance-from-breach front timing matches the KPI/POI arrival model
 * exactly (same formation/Manning's-n delay, same reference minutes). */
export function domainTraversalMinutes(inputs: Pick<ControlInputs, 'formation_min' | 'manning_n'>): number {
  const manningN = Math.max(inputs.manning_n, 0.005);
  const formationDelayFactor = inputs.formation_min / REF_FORMATION_MIN;
  const manningDelayFactor = manningN / REF_MANNING_N;
  return DOMAIN_TRAVERSAL_MIN_AT_REF * formationDelayFactor * manningDelayFactor;
}

export function computeScenarioState(inputs: ScenarioStateInputs): ScenarioState {
  const world = getWorld(inputs.site);
  const durationMin = Math.max(10, inputs.duration_min);
  const manningN = Math.max(inputs.manning_n, 0.005);
  const peak0 = computePeak0(inputs);
  const manningVelocityFactor = Math.pow(REF_MANNING_N / manningN, 0.5);
  const manningDepthFactor = Math.pow(manningN / REF_MANNING_N, 0.15);

  // Arrival-timing model (see DOMAIN_TRAVERSAL_MIN_AT_REF's comment above).
  const domainTraversalMin = domainTraversalMinutes(inputs);
  function arrivalMinAt(chainageM: number): number {
    return (Math.max(chainageM, 0) / world.length_m) * domainTraversalMin;
  }

  const width0 = widthAt(world, 0);
  const lengthScale = world.length_m * 0.9;
  function peakDepthAt(chainageM: number): number {
    const widthHere = widthAt(world, chainageM);
    const spreadFactor = width0 / widthHere;
    const decay = Math.exp(-chainageM / lengthScale);
    return Math.max(peak0 * spreadFactor * decay, 0) * manningDepthFactor;
  }

  let maxDepth = 0, maxVelocity = 0, maxDischarge = 0, wetAreaM2 = 0;
  for (let c = 0; c <= world.length_m; c += SAMPLE_STEP_M) {
    const depthPeak = peakDepthAt(c);
    const velocityPeak = VELOCITY_K * Math.sqrt(depthPeak) * manningVelocityFactor;
    const f = timeFactor(inputs.t_min, arrivalMinAt(c), durationMin);
    const depthNow = depthPeak * f, velocityNow = velocityPeak * f;
    const dischargeNow = velocityNow * depthNow * widthAt(world, c);
    maxDepth = Math.max(maxDepth, depthNow);
    maxVelocity = Math.max(maxVelocity, velocityNow);
    maxDischarge = Math.max(maxDischarge, dischargeNow);
    if (depthNow >= 0.3) wetAreaM2 += SAMPLE_STEP_M * widthAt(world, c);
  }

  const pois: PoiState[] = world.pois.map(poi => {
    const arrivalMin = arrivalMinAt(poi.chainage_m);
    const f = timeFactor(inputs.t_min, arrivalMin, durationMin);
    const reached = f > 0;
    const depthNow = peakDepthAt(poi.chainage_m) * f;
    // Wider range for a later arrival: proxy for compounding travel-time
    // uncertainty over distance (invented, not a real uncertainty model).
    const arrivalSpread = Math.min(0.35, 0.1 + arrivalMin / 300);
    return {
      poi_id: poi.poi_id, name: poi.name, reached,
      arrival_min: ranged(arrivalMin, arrivalSpread, 'min'),
      depth_m: ranged(depthNow, 0.15, 'm'),
    };
  });

  const exposedPopulation = pois.reduce((sum, p, i) => {
    const poi = world.pois[i];
    if (!p.reached || !poi.population) return sum;
    // Partial wetting => partial population count until the local depth
    // catches up to the domain peak (invented, monotonic in depth/time).
    const wetFrac = maxDepth > 0 ? Math.max(0, Math.min(1, p.depth_m.value / maxDepth)) : 0;
    return sum + poi.population * wetFrac;
  }, 0);

  return {
    flood_extent_km2: ranged(wetAreaM2 / 1e6, 0.12, 'km2'),
    max_depth_m: ranged(maxDepth, 0.15, 'm'),
    peak_velocity_ms: ranged(maxVelocity, 0.15, 'm/s'),
    peak_discharge_m3s: ranged(maxDischarge, 0.2, 'm3/s'),
    exposed_population: ranged(exposedPopulation, 0.2, 'people'),
    pois,
  };
}
