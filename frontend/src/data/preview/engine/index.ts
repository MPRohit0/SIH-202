// The demo engine's public surface (design/target-state-preview): assembles
// full contract-shaped responses (FloodQueryResponse, ImpactResponse, ...)
// from world.ts + physics.ts + raster.ts, so preview/index.ts's exported
// functions can delegate to a single place instead of holding this assembly
// logic themselves.
import type {Estimate, FloodQueryRequest, FloodQueryResponse, ImpactResponse, CompareResponse, GeeLayers, HistoricalValidationResponse, Timeline} from './types';
import {getWorld, widthAt, type ScenarioType, type World} from './world';
import {computeProfile, computeConfidence, computeEnsemble, pWetAndMedianAt, seedForInputs, type EngineInputs} from './physics';
import {renderRaster} from './raster';
import {store} from './store';
import {buildCompareResponse, buildCompareWorkbench, type CompareOpts, type CompareWorkbench} from './compare';
import {REAL_TEESTA_DEPTH_RASTER} from './real_teesta';

function est(value: number | null, low: number | null, high: number | null, unit: string | null,
  opts: {kind?: Estimate['kind']; interval?: Estimate['interval']; confidence?: Estimate['confidence']; basis?: string} = {}): Estimate {
  return {value, low, high, unit, interval: opts.interval ?? 'P10-P90', kind: opts.kind ?? 'predicted', confidence: opts.confidence ?? null, basis: opts.basis};
}

const DEPTH_CLASS_EDGES = [0.1, 0.3, 1.0, 2.0, 5.0];
const DV_EDGES = [0.5, 1.0, 3.0];
export function depthClass(depthM: number): string {
  const labels = ['wet', 'low', 'moderate', 'high', 'extreme'];
  if (depthM < DEPTH_CLASS_EDGES[0]) return 'dry';
  for (let i = 1; i < DEPTH_CLASS_EDGES.length; i++) if (depthM < DEPTH_CLASS_EDGES[i]) return labels[i - 1];
  return labels[labels.length - 1];
}
export function dvClass(dv: number): string {
  const labels = ['lower_hazard', 'unsafe_adults', 'unsafe_most', 'structural_damage'];
  for (let i = 0; i < DV_EDGES.length; i++) if (dv < DV_EDGES[i]) return labels[i];
  return labels[labels.length - 1];
}

function inputEstimate(v: number, unit: string): Estimate {
  return est(v, v, v, unit, {kind: 'input', interval: 'none'});
}

/** Runs the engine for one query (scenario or unknown_breach) and returns a
 * full FloodQueryResponse, caching enough state under its query_id for
 * getImpact/getCompare/getScene3d/exports to look the same run back up. */
export function runFloodQuery(request: FloodQueryRequest, scenarioType: ScenarioType): FloodQueryResponse {
  const world = getWorld(request.site_id);
  const inputs = resolveInputs(world, request);
  const queryId = store.newQueryId();
  store.saveQuery({query_id: queryId, site_id: world.site_id, scenario_type: scenarioType, mode: request.mode, inputs, created_at: Date.now(), datasetPerturbation: 1});

  const confidence = computeConfidence(world, inputs);
  const confidenceBlock = {overall: confidence, extent: confidence, depth: confidence, arrival: confidence, velocity: confidence};

  if (request.mode === 'scenario') {
    return buildScenarioResponse(world, queryId, scenarioType, inputs, request.model, confidenceBlock);
  }
  return buildUnknownBreachResponse(world, queryId, scenarioType, inputs, request.model, confidenceBlock);
}

function resolveInputs(world: World, request: FloodQueryRequest): EngineInputs {
  const byName = Object.fromEntries(world.emulatorInputs.map(r => [r.name, r.default]));
  for (const [name, spec] of Object.entries(request.inputs || {})) {
    const range = world.emulatorInputs.find(r => r.name === name);
    if (!range) continue;
    if (spec.type === 'exact') byName[name] = spec.value;
    else {
      const positions = range.slider.positions;
      const t = spec.position / (positions.length - 1);
      byName[name] = range.slider.mapping === 'log' ? range.low * Math.pow(range.high / range.low, t) : range.low + t * (range.high - range.low);
    }
  }
  return byName as unknown as EngineInputs;
}

function buildScenarioResponse(world: World, queryId: string, scenarioType: ScenarioType, inputs: EngineInputs, model: 'delft3d' | 'sph', confidence: FloodQueryResponse['confidence']): FloodQueryResponse {
  const samples = 40;
  let maxDepth = 0, maxVel = 0, maxDischarge = 0, wetArea = 0;
  for (let i = 0; i <= samples; i++) {
    const c = (i / samples) * world.length_m;
    const pt = computeProfile(world, inputs, scenarioType, c);
    maxDepth = Math.max(maxDepth, pt.depth_m);
    maxVel = Math.max(maxVel, pt.velocity_ms);
    maxDischarge = Math.max(maxDischarge, pt.discharge_m3s);
    if (pt.depth_m >= 0.3) wetArea += (world.length_m / samples) * widthAt(world, c);
  }
  const firstWetPoi = world.pois.map(p => ({p, pt: computeProfile(world, inputs, scenarioType, p.chainage_m)}))
    .filter(x => x.pt.depth_m >= 0.3).sort((a, b) => a.pt.arrival_s - b.pt.arrival_s)[0];

  // Teesta scenario mode shows the real registered D-Flow FM depth raster
  // (see real_teesta.ts) instead of the synthetic gorge-channel paint every
  // other site/mode uses -- the numeric summary above is still the engine's
  // own computed profile, unaffected by which raster is displayed.
  const raster = world.site_id === 'teesta'
    ? {dataUrl: REAL_TEESTA_DEPTH_RASTER.url, bounds_latlng: REAL_TEESTA_DEPTH_RASTER.bounds_latlng}
    : renderRaster(world, 'depth', c => computeProfile(world, inputs, scenarioType, c).depth_m);

  return {
    contract_version: '0.3.0', query_id: queryId, site_id: world.site_id,
    status: 'complete', method: model === 'sph' ? 'sph_direct' : 'gp_emulator', mode: 'scenario',
    resolved_inputs: {
      water_volume_m3: inputEstimate(inputs.water_volume_m3, 'm3'),
      breach_width_m: inputEstimate(inputs.breach_width_m, 'm'),
      failure_time_s: inputEstimate(inputs.failure_time_s, 's'),
    },
    summary: {
      inundated_area_m2: est(wetArea, wetArea * 0.9, wetArea * 1.1, 'm2'),
      max_depth_m: est(maxDepth, maxDepth * 0.85, maxDepth * 1.15, 'm'),
      max_velocity_ms: est(maxVel, maxVel * 0.85, maxVel * 1.15, 'm/s'),
      peak_discharge_m3s: est(maxDischarge, maxDischarge * 0.85, maxDischarge * 1.15, 'm3/s'),
      first_arrival: firstWetPoi
        ? {poi_id: firstWetPoi.p.poi_id, name: firstWetPoi.p.name, arrival_s: est(firstWetPoi.pt.arrival_s, firstWetPoi.pt.arrival_s * 0.85, firstWetPoi.pt.arrival_s * 1.2, 's')}
        : {poi_id: world.pois[0].poi_id, name: world.pois[0].name, arrival_s: est(null, null, null, 's', {interval: 'none'})},
    },
    confidence,
    layers: [
      {layer_id: 'depth_p50', type: 'raster_png', url: raster.dataUrl, bounds_latlng: raster.bounds_latlng, style_id: 'depth_p50', unit: 'm', available: true},
    ],
    vectors: {extent_url: ''},
    flags: {outside_trained_range: confidence.overall.level === 'LOW', demo_mode: false, library_outdated: false, has_placeholders: false},
    placeholder_fields: [],
    caveats: [],
    provenance: {method: 'gp_emulator', contract_version: '0.3.0', source: 'fixture:preview', code_version: 'demo-engine-1.0'},
    timing_ms: {median_phase: 40, full_phase: 40},
  };
}

function buildUnknownBreachResponse(world: World, queryId: string, scenarioType: ScenarioType, inputs: EngineInputs, model: 'delft3d' | 'sph', confidence: FloodQueryResponse['confidence']): FloodQueryResponse {
  const seedKey = seedForInputs(world.site_id, scenarioType, 'unknown_breach', inputs);
  const ensemble = computeEnsemble(world, scenarioType, seedKey);
  const raster = renderRaster(world, 'p_inundation', c => pWetAndMedianAt(world, scenarioType, ensemble.draws, c).pWet);
  const firstWet = [...ensemble.pois].filter(p => p.zone !== 'DRY').sort((a, b) => a.median_arrival_s - b.median_arrival_s)[0];
  const maxMedianDepth = Math.max(...ensemble.pois.map(p => p.median_depth_m), 0.01);
  const maxMedianVel = Math.max(...ensemble.pois.map(p => p.median_velocity_ms), 0.01);

  return {
    contract_version: '0.3.0', query_id: queryId, site_id: world.site_id,
    status: 'complete', method: 'gp_emulator', mode: 'unknown_breach',
    resolved_inputs: {
      water_volume_m3: est(inputs.water_volume_m3, inputs.water_volume_m3 * 0.8, inputs.water_volume_m3 * 1.2, 'm3', {kind: 'input', interval: 'none'}),
      breach_width_m: inputEstimate(inputs.breach_width_m, 'm'),
      failure_time_s: inputEstimate(inputs.failure_time_s, 's'),
    },
    summary: {
      inundated_area_m2: est(ensemble.extentAreaHighM2, ensemble.extentAreaHighM2, ensemble.extentAreaHighPossibleM2, 'm2', {interval: 'zone_range'}),
      max_depth_m: est(maxMedianDepth, maxMedianDepth * 0.75, maxMedianDepth * 1.4, 'm'),
      max_velocity_ms: est(maxMedianVel, maxMedianVel * 0.75, maxMedianVel * 1.3, 'm/s'),
      peak_discharge_m3s: est(computeProfile(world, inputs, scenarioType, 0).discharge_m3s, computeProfile(world, inputs, scenarioType, 0).discharge_m3s * 0.75, computeProfile(world, inputs, scenarioType, 0).discharge_m3s * 1.3, 'm3/s'),
      first_arrival: firstWet
        ? {poi_id: firstWet.poi.poi_id, name: firstWet.poi.name, arrival_s: est(firstWet.median_arrival_s, firstWet.fast_arrival_s, firstWet.slow_arrival_s, 's')}
        : {poi_id: world.pois[0].poi_id, name: world.pois[0].name, arrival_s: est(null, null, null, 's', {interval: 'none'})},
    },
    confidence,
    layers: [
      {layer_id: 'p_inundation', type: 'raster_png', url: raster.dataUrl, bounds_latlng: raster.bounds_latlng, style_id: 'p_inundation', unit: null, available: true},
    ],
    vectors: {extent_url: ''},
    flags: {outside_trained_range: confidence.overall.level === 'LOW', demo_mode: false, library_outdated: false, has_placeholders: false},
    placeholder_fields: [],
    caveats: [],
    provenance: {method: 'gp_emulator', contract_version: '0.3.0', source: 'fixture:preview', code_version: 'demo-engine-1.0'},
    timing_ms: {median_phase: 180, full_phase: 180},
  };
}

/** Rebuilds the impact response for an already-run query_id. */
export function buildImpact(queryId: string): ImpactResponse {
  const stored = store.getQuery(queryId);
  if (!stored) throw new Error(`No demo-engine query cached for query_id ${queryId}`);
  const world = getWorld(stored.site_id);
  const seedKey = seedForInputs(world.site_id, stored.scenario_type, 'impact', stored.inputs);
  const ensemble = stored.mode === 'unknown_breach'
    ? computeEnsemble(world, stored.scenario_type, seedKey)
    : computeEnsemble(world, stored.scenario_type, seedKey); // impact always reasons over the exceedance ensemble, even from a scenario-mode query

  const DENSITY_PERSONS_PER_M2 = 150 / 1.0e6;
  const popLow = round2sf(ensemble.extentAreaHighM2 * DENSITY_PERSONS_PER_M2, 50);
  const popHigh = Math.max(popLow, round2sf(ensemble.extentAreaHighPossibleM2 * DENSITY_PERSONS_PER_M2, 50));

  const villagePois = ensemble.pois.filter(p => p.poi.kind === 'village' && p.zone !== 'DRY');
  const facilityPois = ensemble.pois.filter(p => p.poi.kind !== 'village' && p.zone !== 'DRY');

  const warningTable = ensemble.pois.filter(p => p.zone !== 'DRY').map(p => ({
    poi_id: p.poi.poi_id, name: p.poi.name, kind: p.poi.kind, chainage_m: p.poi.chainage_m,
    zone: (p.zone === 'HIGH' ? 'high' : 'possible') as 'high' | 'possible', p_inundation: p.p_floods,
    arrival_s: est(p.median_arrival_s, p.fast_arrival_s, p.slow_arrival_s, 's', {basis: 'demo-engine'}),
    depth_m: est(p.median_depth_m, p.p5_depth_m, p.p95_depth_m, 'm', {basis: 'demo-engine'}),
    velocity_ms: est(p.median_velocity_ms, p.p5_velocity_ms, p.p95_velocity_ms, 'm/s', {basis: 'demo-engine'}),
    x_preview_depth_class: depthClass(p.median_depth_m), x_preview_dv_class: dvClass(p.median_depth_m * p.median_velocity_ms), x_preview_dv_m2s: p.median_depth_m * p.median_velocity_ms,
  }));

  const buildingsPerVillage = 90;
  const buildingsHigh = villagePois.filter(p => p.zone === 'HIGH').length * buildingsPerVillage;
  const buildingsPossible = villagePois.filter(p => p.zone === 'POSSIBLE').length * buildingsPerVillage;

  // Real JRC damage-curve shape (docs/data_sources.md src_031/src_032), same
  // functional form used by backend/m6_impact/loss.py -- values here are a
  // faithful re-implementation, not the literal CSV (kept dependency-free for
  // the browser bundle).
  const residentialValuePerM2 = 28025.42; // INR/m2, src_032
  const residentialFrac = (d: number) => Math.min(1, 0.33 * Math.pow(Math.min(d, 6), 0.55));
  const buildingFootprintM2 = 60;
  let lossMedian = 0, lossLow = 0, lossHigh = 0;
  for (const p of villagePois) {
    const count = p.zone === 'HIGH' ? buildingsPerVillage : Math.round(buildingsPerVillage * 0.4);
    lossMedian += residentialFrac(p.median_depth_m) * buildingFootprintM2 * count * residentialValuePerM2;
    lossLow += residentialFrac(p.p5_depth_m) * buildingFootprintM2 * count * residentialValuePerM2;
    lossHigh += residentialFrac(p.p95_depth_m) * buildingFootprintM2 * count * residentialValuePerM2;
  }

  const arrivalBands = [15, 30, 60, 120, 180, 360];
  const bandLabel = (min: number) => {
    for (let i = 0; i < arrivalBands.length; i++) if (min <= arrivalBands[i]) return `${i === 0 ? 0 : arrivalBands[i - 1]}-${arrivalBands[i]}`;
    return `>${arrivalBands[arrivalBands.length - 1]}`;
  };
  const bandMap = new Map<string, {low: number; high: number}>();
  for (const p of ensemble.pois) {
    if (p.zone === 'DRY' || p.poi.kind !== 'village') continue;
    const band = bandLabel(p.median_arrival_s / 60);
    const entry = bandMap.get(band) ?? {low: 0, high: 0};
    const pop = p.poi.population ?? 0;
    entry.low += p.zone === 'HIGH' ? pop : 0;
    entry.high += pop;
    bandMap.set(band, entry);
  }

  return {
    contract_version: '0.3.0', query_id: queryId, site_id: world.site_id,
    population_persons: est(popLow, popLow, popHigh, 'persons', {interval: 'zone_range', confidence: 'MODERATE', basis: 'value = sum(p x pop); low = HIGH zone; high = HIGH + POSSIBLE'}),
    assets: {
      buildings: {high: buildingsHigh, possible: buildingsPossible},
      roads_m: {high: villagePois.length * 800, possible: 0},
      bridges: {high: facilityPois.filter(p => p.poi.kind === 'bridge').length, possible: 0},
      hospitals: {high: facilityPois.filter(p => p.poi.kind === 'hospital').length, possible: 0},
      schools: {high: 0, possible: 0},
      cropland_m2: {high: 0, possible: 0},
      hydropower: facilityPois.filter(p => p.poi.kind === 'dam').map(p => ({
        name: p.poi.name, zone: (p.zone === 'HIGH' ? 'high' : 'possible') as 'high' | 'possible',
        depth_m: est(p.median_depth_m, p.p5_depth_m, p.p95_depth_m, 'm', {confidence: 'MODERATE'}),
      })),
    },
    loss_inr: {
      ...est(lossMedian, Math.min(lossLow, lossMedian), Math.max(lossHigh, lossMedian), 'INR', {confidence: 'MODERATE', basis: 'JRC-style depth-damage curve (src_031/src_032 shape) x illustrative exposed building area'}),
      by_asset_class: {residential: est(lossMedian, Math.min(lossLow, lossMedian), Math.max(lossHigh, lossMedian), 'INR', {confidence: 'MODERATE'})},
      assumptions: [
        'Damage curve shape follows the JRC ASIA depth-damage function (src_031); asset value follows JRC India residential Building-based Total (src_032).',
        'Only named villages are priced as residential structures; the dam, bridge and hospital are reported in the critical-facilities list with zone/arrival only.',
        'Roads and agriculture are not priced in this demo.',
      ],
    },
    warning_table: warningTable,
    not_affected_poi_count: ensemble.pois.filter(p => p.zone === 'DRY').length,
    data_coverage_notes: [],
    has_placeholders: false, placeholder_fields: [],
    caveats: [],
    provenance: {method: 'gp_emulator', contract_version: '0.3.0', source: 'fixture:preview'},
    x_preview_population_by_arrival_band: Array.from(bandMap.entries()).map(([band, v]) => ({
      arrival_band_min: band, low_persons: round2sf(v.low, 50), high_persons: Math.max(round2sf(v.low, 50), round2sf(v.high, 50)),
    })),
    x_preview_population_by_arrival_band_note: 'Split by the same arrival-band edges used for isochrones.',
    x_preview_critical_facilities_note: 'The dam, bridge and hospital are reported here (zone + arrival only) and excluded from population_persons and assets.buildings.',
  };
}

function round2sf(value: number, floor: number): number {
  if (value <= 0) return 0;
  if (value < floor) return floor;
  const magnitude = Math.pow(10, Math.floor(Math.log10(value)) - 1);
  return Math.round(value / magnitude) * magnitude;
}

/** SPH vs D-Flow FM comparison, real 2D grids computed by engine/compare.ts:
 * two synthetic "solvers" evaluated over a domain grid, plus a LOOCV +
 * held-out-run emulator-vs-physics harness (m5_specs.md §6/§8). See
 * compare.ts's module doc for what is invented and why. */
export function buildCompare(siteId: string, scenarioType: ScenarioType, inputs: EngineInputs, opts?: CompareOpts): CompareResponse {
  return buildCompareResponse(siteId, scenarioType, inputs, opts);
}

/** Preview-only accessor for the raw grids/scenes/POI pairs behind buildCompare
 * (Float32Arrays, Scene3DResponse objects, the run dropdown list) -- the
 * CompareResponse above only carries what compare.schema.json can hold
 * (PNG layer URLs, scalar metrics), not the data CompareView needs to drive
 * TerrainMap/Terrain3D directly. Same pattern as getScenarioPair(). */
export function getCompareWorkbench(siteId: string, scenarioType: ScenarioType, inputs: EngineInputs, opts?: CompareOpts): CompareWorkbench {
  return buildCompareWorkbench(siteId, scenarioType, inputs, opts);
}

/** A plausible hydrograph shape: rises linearly to the peak at failure_time_s,
 * then recedes to 15% of peak by t_end -- not a routed time-stepped solve,
 * just a believable envelope so the timeline has something to animate. */
function envelopeAt(tS: number, failureTimeS: number, tEndS: number): number {
  if (tS <= failureTimeS) return tS / failureTimeS;
  const recedeFrac = (tS - failureTimeS) / Math.max(tEndS - failureTimeS, 1);
  return Math.max(0.15, 1 - 0.85 * recedeFrac);
}

const TIMELINE_FRAME_COUNT = 10;

/** Builds the playback timeline (hydrograph + arrival profile + per-frame
 * depth rasters) for an already-run query_id. */
export function buildTimeline(queryId: string): Timeline {
  const stored = store.getQuery(queryId);
  if (!stored) throw new Error(`No demo-engine query cached for query_id ${queryId}`);
  const world = getWorld(stored.site_id);
  const {inputs, scenario_type: scenarioType} = stored;
  const tEndS = inputs.failure_time_s * 6;
  const peakAtSource = computeProfile(world, inputs, scenarioType, 0).discharge_m3s;

  const hydrographs: Timeline['hydrographs'] = [{
    dam_id: world.emulatorInputs.length ? `${world.site_id}__source` : world.site_id, t_offset_s: 0,
    points: Array.from({length: 12}, (_, i) => {
      const t = (i / 11) * tEndS;
      return {t_s: Math.round(t), q_m3s: Math.round(peakAtSource * envelopeAt(t, inputs.failure_time_s, tEndS))};
    }),
  }];
  if (scenarioType === 'cascade' && world.cascadeDam) {
    const dam = world.cascadeDam;
    const arrivalAtDam = computeProfile(world, inputs, scenarioType, dam.chainage_m).arrival_s;
    const peakAtDamOnward = computeProfile(world, inputs, scenarioType, dam.chainage_m + 100).discharge_m3s;
    if (Number.isFinite(arrivalAtDam)) {
      hydrographs.push({
        dam_id: dam.dam_id, t_offset_s: Math.round(arrivalAtDam),
        points: Array.from({length: 8}, (_, i) => {
          const t = (i / 7) * (tEndS - arrivalAtDam);
          return {t_s: Math.round(arrivalAtDam + t), q_m3s: Math.round(peakAtDamOnward * envelopeAt(t, inputs.failure_time_s * 0.5, tEndS - arrivalAtDam))};
        }),
      });
    }
  }

  const arrivalProfile: Timeline['arrival_profile'] = [];
  for (let c = 0; c <= world.length_m; c += world.length_m / 16) {
    const pt = computeProfile(world, inputs, scenarioType, c);
    const isEnsemble = stored.mode === 'unknown_breach';
    let p10: number | null = null, p90: number | null = null;
    if (isEnsemble) {
      const seedKey = seedForInputs(world.site_id, scenarioType, 'timeline', inputs, String(c));
      const draws = computeEnsemble(world, scenarioType, seedKey).draws;
      const arrivals = draws.map(d => computeProfile(world, d, scenarioType, c).arrival_s).filter(Number.isFinite).sort((a, b) => a - b);
      if (arrivals.length) { p10 = arrivals[Math.floor(arrivals.length * 0.1)]; p90 = arrivals[Math.floor(arrivals.length * 0.9)]; }
    }
    arrivalProfile.push({chainage_m: Math.round(c), arrival_p50_s: Number.isFinite(pt.arrival_s) ? Math.round(pt.arrival_s) : 0, arrival_p10_s: p10, arrival_p90_s: p90});
  }

  const frames: Timeline['frames'] = Array.from({length: TIMELINE_FRAME_COUNT}, (_, i) => {
    const t = (i / (TIMELINE_FRAME_COUNT - 1)) * tEndS;
    const env = envelopeAt(t, inputs.failure_time_s, tEndS);
    const raster = renderRaster(world, 'depth', c => computeProfile(world, inputs, scenarioType, c).depth_m * env);
    return {t_s: Math.round(t), median_url: raster.dataUrl, high_url: raster.dataUrl, possible_url: raster.dataUrl, bounds_latlng: raster.bounds_latlng};
  });

  return {
    query_id: queryId, interval_s: Math.round(tEndS / (TIMELINE_FRAME_COUNT - 1)), t_end_s: Math.round(tEndS),
    frames, hydrographs, arrival_profile: arrivalProfile,
    pois_on_profile: world.pois.map(p => ({poi_id: p.poi_id, name: p.name, chainage_m: p.chainage_m})),
    caveats: [], provenance: {method: 'gp_emulator', source: 'fixture:preview'},
  };
}

/** One representative run per site, for the Node-side fixture dump script
 * (frontend/scripts/dump_preview_fixtures.mjs) to write into generated/*.json
 * -- what pytest validates against contracts/schemas/*.schema.json as a
 * shape regression, now that results are computed live instead of read from
 * static JSON. Not used by the running app itself. */
export function defaultSnapshot(siteId: string) {
  const world = getWorld(siteId);
  const scenarioType = world.defaultScenarioType;
  const scenario = runFloodQuery({site_id: siteId, model: 'delft3d', mode: 'scenario', inputs: {}}, scenarioType);
  const unknownBreach = runFloodQuery({site_id: siteId, model: 'delft3d', mode: 'unknown_breach', inputs: {}}, scenarioType);
  const impact = buildImpact(unknownBreach.query_id);
  const inputs = Object.fromEntries(world.emulatorInputs.map(r => [r.name, r.default])) as unknown as EngineInputs;
  const compare = buildCompare(siteId, scenarioType, inputs);
  return {flood_query_scenario: scenario, flood_query_unknown_breach: unknownBreach, impact, compare};
}

export {store};
