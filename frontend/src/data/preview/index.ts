// Preview data mode router (design/target-state-preview only) -- now backed
// by the live demo engine (engine/index.ts) instead of static fixture JSON.
// Every function below keeps its old signature (source.ts's branching does
// not change) but computes its answer from the current engine/store state,
// so results respond to whatever the user just did.
import siteDetailTeesta from './site_detail.teesta.json';
import siteDetailRishiGanga from './site_detail.rishi_ganga.json';
import type {
  SiteSummary, SiteDetail, SiteCreateAccepted, JobStatus, FloodQueryRequest, FloodQueryResponse,
  Scene3DResponse, CompareResponse, GeeLayers, ValidationResponse, HistoricalValidationResponse, ImpactResponse,
} from '../api';
import {getWorld, type ScenarioType} from './engine/world';
import {computeProfile, seedForInputs, type EngineInputs} from './engine/physics';
import {widthAt} from './engine/world';
import {mulberry32, hashSeed} from './engine/rng';
import {runFloodQuery, buildImpact, buildCompare, buildTimeline, depthClass, dvClass} from './engine/index';
import {store} from './engine/store';
import {renderScene3d} from './engine/scene3d';
import {renderTerrainImage, renderRaster} from './engine/raster';

const siteDetailTemplates: Record<string, SiteDetail> = {
  teesta: siteDetailTeesta as unknown as SiteDetail,
  rishi_ganga: siteDetailRishiGanga as unknown as SiteDetail,
};

export async function listSites(): Promise<SiteSummary[]> {
  return structuredClone(store.sites);
}

export async function getSite(): Promise<SiteSummary | null> {
  return store.sites[0] ?? null;
}

export async function getSiteDetail(siteId: string): Promise<SiteDetail> {
  const summary = store.sites.find(s => s.site_id === siteId);
  if (!summary) throw new Error(`No preview demo site for site_id ${JSON.stringify(siteId)}`);
  const template = siteDetailTemplates[siteId] ?? buildClonedSiteDetail(siteId);
  return structuredClone({...template, status: summary.status, name: summary.name, bbox_lonlat: summary.bbox_lonlat, has_placeholders: false});
}

function buildClonedSiteDetail(siteId: string): SiteDetail {
  const world = getWorld(siteId);
  const base = structuredClone(siteDetailTeesta) as unknown as SiteDetail;
  return {
    ...base, site_id: siteId, name: world.name, bbox_lonlat: world.bbox_lonlat,
    dams: base.dams.map(d => ({...d, dam_id: d.dam_id.replace('teesta__', `${siteId}__`)})),
    emulator_inputs: world.emulatorInputs.map(r => ({
      name: r.name, dam_id: `${siteId}__source`, label_key: r.label_key, unit: r.unit, low: r.low, high: r.high,
      slider: r.slider, default: r.default,
    })),
  };
}

// --- Onboarding job (screen 2 / Add-a-Dam, deliverable v) ---------------

const JOB_DURATION_MS = 6000;
const JOB_STAGES = ['queued', 'terrain', 'breach', 'design', 'simulating', 'training', 'validating', 'ready'] as const;

export async function createSite(): Promise<SiteCreateAccepted> {
  const jobId = store.newJobId('onboarding');
  const siteId = `pending_${jobId}`;
  store.startJob({job_id: jobId, site_id: siteId, kind: 'onboarding', started_at: Date.now(), duration_ms: JOB_DURATION_MS});
  return {job_id: jobId, site_id: siteId};
}

/** Add-a-Dam with a chosen real dam/river (deliverable v's searchable list). */
export async function createSiteFromDam(name: string, lon: number, lat: number): Promise<SiteCreateAccepted> {
  const summary = store.addSiteFromDam(name, lon, lat);
  const jobId = store.newJobId('onboarding');
  store.startJob({job_id: jobId, site_id: summary.site_id, kind: 'onboarding', started_at: Date.now(), duration_ms: JOB_DURATION_MS, result_site_id: summary.site_id});
  return {job_id: jobId, site_id: summary.site_id};
}

export async function getJob(jobId: string): Promise<JobStatus> {
  const rec = store.getJob(jobId);
  if (!rec) throw new Error(`No preview demo job for job_id ${JSON.stringify(jobId)}`);
  const elapsed = Date.now() - rec.started_at;
  const stageIndex = Math.min(JOB_STAGES.length - 1, Math.floor((elapsed / rec.duration_ms) * JOB_STAGES.length));
  const stage = JOB_STAGES[stageIndex];
  if (stage === 'ready' && rec.result_site_id) store.markSiteReady(rec.result_site_id);
  const pct = Math.min(100, Math.round((elapsed / rec.duration_ms) * 100));
  return {
    job_id: jobId, kind: rec.kind, site_id: rec.site_id, stage, stage_label_key: `job_stage_${stage}`,
    progress: {current: pct, total: 100, unit: '%'}, eta_s: Math.max(0, Math.round((rec.duration_ms - elapsed) / 1000)),
    demo_mode: true, started_at: new Date(rec.started_at).toISOString(), updated_at: new Date().toISOString(),
    log_tail: [`[${stage}] ${stage === 'ready' ? 'Site ready to query.' : 'Working...'}`], error: null,
  };
}

export async function getRunMeta(): Promise<Record<string, unknown>> {
  return {
    run_id: 'demo__cascade__delft3d', engine: 'Delft3D FM (demo)', mesh_cells: 33018, wall_time_s: 41.2,
    disk_bytes: 812_000_000, note: 'Live demo engine run metadata (design/target-state-preview).',
  };
}

export async function getTerrainMeta(siteId: string): Promise<Record<string, unknown>> {
  const world = getWorld(siteId);
  return {
    vertical_datum: 'EGM2008', resolution_m: 12.5,
    dem_layer: {url: renderTerrainImage(world, 0).dataUrl, label: 'DEM hillshade'}, domain_mask_layer: {url: renderRaster(world, 'zone', () => 0.3).dataUrl, label: 'Domain mask'},
    dem_size_bytes: 1_260_000_000, dem_cell_count: 12_700_000, dataset: store.datasetSelections.dem,
    length_m: world.length_m,
  };
}

// --- Flood query (screens 1/4/6, Simulation, Dashboard) -----------------

export async function queryFlood(request: FloodQueryRequest): Promise<FloodQueryResponse> {
  if (!request.site_id) throw new Error('A site_id is required to run a flood query.');
  const world = getWorld(request.site_id);
  const scenarioType: ScenarioType = store.currentScenarioType ?? world.defaultScenarioType;
  return runFloodQuery(request, scenarioType);
}

export async function getScenarioPair(siteId: string): Promise<{low: FloodQueryResponse; high: FloodQueryResponse}> {
  const world = getWorld(siteId);
  const scenarioType = world.defaultScenarioType;
  const low = runFloodQuery({site_id: siteId, model: 'delft3d', mode: 'scenario', inputs: {
    breach_width_m: {type: 'exact', value: world.emulatorInputs[1].low}, failure_time_s: {type: 'exact', value: world.emulatorInputs[2].high},
  }}, scenarioType);
  const high = runFloodQuery({site_id: siteId, model: 'delft3d', mode: 'scenario', inputs: {
    breach_width_m: {type: 'exact', value: world.emulatorInputs[1].high}, failure_time_s: {type: 'exact', value: world.emulatorInputs[2].low},
  }}, scenarioType);
  return {low, high};
}

export async function getOutsideRangeExample(siteId: string): Promise<FloodQueryResponse> {
  const world = getWorld(siteId);
  return runFloodQuery({site_id: siteId, model: 'delft3d', mode: 'scenario', inputs: {
    water_volume_m3: {type: 'exact', value: world.emulatorInputs[0].high * 1.1},
  }}, world.defaultScenarioType);
}

// --- Scene3D (near-field, screen 4) --------------------------------------

const scene3dCache = new Map<string, Scene3DResponse>();

export async function getScene3d(queryId: string): Promise<Scene3DResponse> {
  const stored = store.getQuery(queryId);
  if (!stored) throw new Error(`No preview demo query cached for query_id ${JSON.stringify(queryId)}`);
  let scene = scene3dCache.get(queryId);
  if (!scene) { scene = renderScene3d(getWorld(stored.site_id), stored.scenario_type, stored.inputs, queryId); scene3dCache.set(queryId, scene); }
  return structuredClone(scene);
}

export async function getScene3dArrays(scene: Scene3DResponse): Promise<{terrain: Float32Array; flood: Float32Array}> {
  const [terrainRes, floodRes] = await Promise.all([fetch(scene.terrain.url), fetch(scene.flood_surface.url)]);
  const [terrainBuf, floodBuf] = await Promise.all([terrainRes.arrayBuffer(), floodRes.arrayBuffer()]);
  return {terrain: new Float32Array(terrainBuf), flood: new Float32Array(floodBuf)};
}

// --- Impact / Compare / Validation ---------------------------------------

export async function getImpact(queryId: string): Promise<ImpactResponse> {
  return buildImpact(queryId);
}

export async function getTimeline(queryId: string) {
  return buildTimeline(queryId);
}

export async function getCompare(siteId: string): Promise<CompareResponse> {
  const world = getWorld(siteId);
  const lastQueryId = store.recentQueryIds.find(id => store.getQuery(id)?.site_id === siteId);
  const stored = lastQueryId ? store.getQuery(lastQueryId) : undefined;
  const inputs: EngineInputs = stored?.inputs ?? Object.fromEntries(world.emulatorInputs.map(r => [r.name, r.default])) as unknown as EngineInputs;
  return buildCompare(siteId, stored?.scenario_type ?? world.defaultScenarioType, inputs);
}

export async function getValidation(siteId: string): Promise<ValidationResponse> {
  return {
    contract_version: '0.3.0', site_id: siteId, model: 'delft3d', n_runs: 24,
    per_run: [], summary: {iou_median: 0.87, depth_rmse_wet_m: 0.31, arrival_mae_s: 145},
    baseline_linear: {iou_median: 0.68}, grade_thresholds_ref: 'docs/m5_specs.md §7',
    events: siteId === 'rishi_ganga' ? ['chamoli_2021'] : [],
    // Real LOOCV results on the project's synthetic test world (backend/m5_emulator,
    // project documentation §7.10) -- measured, but not a site-specific validation.
    synthetic_loocv: {
      world: 'synthetic_valley', model: 'gp_emulator', n_runs: 30,
      note: 'Leave-one-out cross-validation on the 40 km synthetic test valley: the emulator is refitted 30 times, each time predicting the one run it did not see.',
      summary: {depth_rmse_m: 0.067, arrival_rmse_s: 815, interval_coverage_wet_pct: 87.0, interval_coverage_poi_pct: 85.3},
      baseline_linear: {depth_rmse_m: 0.139, arrival_rmse_s: 1622},
      baseline_nearest: {depth_rmse_m: 0.243, arrival_rmse_s: 1466},
      acceptance: {monotonic_pairs: '300 / 300', terrace_classified: '27 / 30 folds'},
    },
  };
}

export async function getHistoricalValidation(siteId: string, eventId: string): Promise<HistoricalValidationResponse> {
  const world = getWorld(siteId);
  const raini = world.pois.find(p => p.poi_id.includes('raini'))!;
  const tapovan = world.pois.find(p => p.poi_id.includes('tapovan'))!;
  const inputs: EngineInputs = {water_volume_m3: 26_900_000, breach_width_m: 120, failure_time_s: 3600};
  const atRaini = computeProfile(world, inputs, 'river_blockage', raini.chainage_m);
  const atTapovan = computeProfile(world, inputs, 'river_blockage', tapovan.chainage_m);
  const observed = {
    event_type: 'Rock-and-ice avalanche from Ronti Peak, transformed into a debris flow and downstream flood',
    source_volume_m3: 26_900_000, rishiganga_frontal_speed_ms: 25.0, rishiganga_mean_discharge_m3s_low: 8200, rishiganga_mean_discharge_m3s_high: 14200,
    tapovan_downstream_frontal_speed_ms: 12.0, tapovan_downstream_mean_discharge_m3s_low: 2900, tapovan_downstream_mean_discharge_m3s_high: 4900,
  };
  const predicted = {
    rishiganga_area_velocity_ms: atRaini.velocity_ms, rishiganga_area_discharge_m3s: atRaini.discharge_m3s,
    tapovan_velocity_ms: atTapovan.velocity_ms, tapovan_discharge_m3s: atTapovan.discharge_m3s,
  };
  const pctDiff = (sim: number, obsLow: number, obsHigh: number) => {
    const obsMid = (obsLow + obsHigh) / 2;
    return obsMid ? ((sim - obsMid) / obsMid) * 100 : 0;
  };
  return {
    contract_version: '0.3.0', site_id: siteId, event_id: eventId,
    comparison_domain: 'Rishiganga hydropower project reach and Tapovan-Vishnugad barrage reach',
    observed: {...observed, available: true},
    predicted,
    metrics: {
      rishiganga_discharge_diff_pct: pctDiff(predicted.rishiganga_area_discharge_m3s, observed.rishiganga_mean_discharge_m3s_low, observed.rishiganga_mean_discharge_m3s_high),
      tapovan_discharge_diff_pct: pctDiff(predicted.tapovan_discharge_m3s, observed.tapovan_downstream_mean_discharge_m3s_low, observed.tapovan_downstream_mean_discharge_m3s_high),
    },
    caveats: [],
    provenance: {method: 'gp_emulator', source: 'fixture:preview'},
  };
}

// --- GEE monitoring (screen 7, deliverable iv) ---------------------------

const OUTDATED_THRESHOLD_PCT = 10;

export async function getObserved(siteId: string): Promise<GeeLayers> {
  const gee = store.geeState.get(siteId);
  if (!gee) throw new Error(`No preview demo GEE state for site_id ${JSON.stringify(siteId)}`);
  const latest = gee.series[gee.series.length - 1];
  const first = gee.series[0];
  const changePct = first.area_m2 ? ((latest.area_m2 - first.area_m2) / first.area_m2) * 100 : 0;
  const world = getWorld(siteId);
  // Illustrative pre/post scenes on the flood map's own grid, with the lake drawn from the area series.
  const preImg = renderTerrainImage(world, first.area_m2, {toChainage: 400}), postImg = renderTerrainImage(world, latest.area_m2, {toChainage: 400});
  const pre = {event_id: `${siteId}_pre`, phase: 'pre' as const, date: first.date, url: preImg.dataUrl, bounds_latlng: preImg.bounds_latlng};
  const post = {event_id: `${siteId}_post`, phase: 'post' as const, date: latest.date, url: postImg.dataUrl, bounds_latlng: postImg.bounds_latlng};
  return {
    site_id: siteId, source: 'cache', fetched_at: new Date(gee.lastCheckedAt).toISOString(),
    lake_area_series: gee.series.map(p => ({date: p.date, area_m2: p.area_m2, method: 's2_water_index', cloud_pct: 8, source: 'src_072'})),
    lake_latest: {type: 'FeatureCollection', features: [{type: 'Feature', geometry: {type: 'Polygon', coordinates: [lakeOutline(world.breach_lon, world.breach_lat, latest.area_m2)]}, properties: {area_m2: latest.area_m2, date: latest.date}}]},
    rainfall: [{date: latest.date, precip_mm: 38, dataset: 'gpm_imerg'}],
    imagery: [pre, post],
    observed_extents: [],
    recheck: {outdated: Math.abs(changePct) >= OUTDATED_THRESHOLD_PCT, change_pct: changePct, threshold_pct: OUTDATED_THRESHOLD_PCT},
  };
}

/** Illustrative lake outline of the given area, elongated along the valley,
 * with an irregular shoreline (deterministic, so it does not change per render). */
function lakeOutline(lon: number, lat: number, areaM2: number): number[][] {
  const r = Math.sqrt(Math.max(areaM2, 1) / Math.PI), mLon = 110540 * Math.cos(lat * Math.PI / 180), mLat = 110540;
  const pts: number[][] = [];
  const shape = (a: number) => 1 + 0.12 * Math.sin(3 * a + 0.7) + 0.07 * Math.sin(5 * a + 2.1) + 0.04 * Math.cos(9 * a);
  for (let k = 0; k <= 64; k++) {
    const a = (k / 64) * Math.PI * 2, rr = r * shape(a);
    pts.push([lon + (rr * 1.45 * Math.cos(a)) / mLon, lat + (rr * 0.7 * Math.sin(a)) / mLat]);
  }
  pts[pts.length - 1] = pts[0];
  return pts;
}

export async function refreshObserved(siteId: string): Promise<GeeLayers> {
  const gee = store.geeState.get(siteId);
  if (gee) {
    const last = gee.series[gee.series.length - 1];
    const drift = 1 + (Math.sin(gee.series.length * 1.7) * 0.04);
    const nextDate = new Date(); nextDate.setDate(nextDate.getDate());
    gee.series.push({date: nextDate.toISOString().slice(0, 10), area_m2: Math.round(last.area_m2 * drift)});
    gee.lastCheckedAt = Date.now();
  }
  return getObserved(siteId);
}

export async function updateRecheckFrequency(siteId: string, frequencyDays: number): Promise<SiteSummary> {
  const site = store.sites.find(s => s.site_id === siteId);
  if (!site) throw new Error(`No preview demo site for site_id ${JSON.stringify(siteId)}`);
  const lastCheckedAt = site.recheck?.last_checked_at ?? new Date().toISOString();
  const nextCheckAt = new Date(new Date(lastCheckedAt).getTime() + frequencyDays * 86400000).toISOString();
  site.recheck = {frequency_days: frequencyDays, last_checked_at: lastCheckedAt, next_check_at: nextCheckAt};
  return structuredClone(site);
}

export {depthClass, dvClass};
export {store};

// --- Scenario library (screen: Scenario Library) --------------------------
// The emulator's training design as described in docs/m5_specs.md: a 30-run
// maximin-style Latin hypercube over (V_w, B_ave, T_f) inside each input's
// range, plus 5 held-out check runs and 3 SPH near-field comparison runs
// (low / mid / high volume). Every number is computed by the demo engine.

export type LibraryRun = {
  run_id: string; role: 'training' | 'holdout' | 'sph'; engine: 'D-Flow FM' | 'DualSPHysics';
  water_volume_m3: number; breach_width_m: number; failure_time_s: number;
  extent_km2: number; peak_depth_m: number; loocv_iou: number | null; wall_time_s: number;
};

// Same sampling as the engine's scenario response (engine/index.ts
// buildScenarioResponse), so the library and home page match the workspace.
function floodedAreaKm2(world: ReturnType<typeof getWorld>, inputs: EngineInputs, scenarioType: string): number {
  const samples = 40;
  let area = 0;
  for (let i = 0; i <= samples; i++) {
    const c = (i / samples) * world.length_m;
    if (computeProfile(world, inputs, scenarioType, c).depth_m >= 0.3) area += (world.length_m / samples) * widthAt(world, c);
  }
  return area / 1e6;
}

export async function getScenarioLibrary(siteId: string): Promise<LibraryRun[]> {
  const world = getWorld(siteId);
  const byName = Object.fromEntries(world.emulatorInputs.map(r => [r.name, r]));
  const vw = byName.water_volume_m3, bw = byName.breach_width_m, tf = byName.failure_time_s;
  const scale = (r: typeof vw, u: number) => r.slider.mapping === 'log' ? r.low * Math.pow(r.high / r.low, u) : r.low + u * (r.high - r.low);
  const rand = mulberry32(hashSeed(`${siteId}|library`));
  const lhs = (n: number) => {
    const perms = [0, 1, 2].map(() => { const p = Array.from({length: n}, (_, i) => i); for (let i = n - 1; i > 0; i--) { const j = Math.floor(rand() * (i + 1)); [p[i], p[j]] = [p[j], p[i]]; } return p; });
    return Array.from({length: n}, (_, i) => perms.map(p => (p[i] + 0.5) / n));
  };
  const make = (role: LibraryRun['role'], idx: number, u: number[]): LibraryRun => {
    const inputs = {water_volume_m3: scale(vw, u[0]), breach_width_m: scale(bw, u[1]), failure_time_s: scale(tf, u[2])};
    const sph = role === 'sph';
    return {
      run_id: `${siteId}_${sph ? 'sph' : role === 'holdout' ? 'h' : 'r'}${String(idx + 1).padStart(2, '0')}`, role,
      engine: sph ? 'DualSPHysics' : 'D-Flow FM', ...inputs,
      extent_km2: floodedAreaKm2(world, inputs, world.defaultScenarioType),
      peak_depth_m: computeProfile(world, inputs, world.defaultScenarioType, 0).depth_m,
      loocv_iou: role === 'training' ? 0.84 + 0.1 * rand() : null,
      wall_time_s: sph ? 900 + 600 * u[0] : 380 + 190 * u[0] + 60 * rand(),
    };
  };
  return [
    ...lhs(30).map((u, i) => make('training', i, u)),
    ...lhs(5).map((u, i) => make('holdout', i, u)),
    ...[0.15, 0.5, 0.85].map((v, i) => make('sph', i, [v, 0.5, 0.5])),
  ];
}

// --- Landing page (preview mode) -----------------------------------------
// The home page's hero map, data card and impact teaser, computed from the
// site's default scenario so the page shows the same numbers as the workspace.
export type PreviewLanding = {
  name: string; terrainUrl: string; terrainBounds: [[number, number], [number, number]]; floodUrl: string; extent_km2: number; peak_depth_m: number;
  coords: string; places: {name: string; kind: string; population: number; arrival_min: number; depth_m: number}[];
};
export async function getPreviewLanding(siteId: string): Promise<PreviewLanding> {
  const world = getWorld(siteId);
  const gee = store.geeState.get(siteId);
  const inputs = Object.fromEntries(world.emulatorInputs.map(r => [r.name, r.default])) as EngineInputs;
  const scenario = world.defaultScenarioType;
  const terrain = renderTerrainImage(world, gee ? gee.series[gee.series.length - 1].area_m2 : 0);
  const flood = renderRaster(world, 'depth', c => computeProfile(world, inputs, scenario, c).depth_m);
  const [[s, w], [n, e]] = terrain.bounds_latlng;
  const places = world.pois.map(p => { const pt = computeProfile(world, inputs, scenario, p.chainage_m); return {name: p.name, kind: p.kind, population: p.population ?? 0, arrival_min: pt.arrival_s / 60, depth_m: pt.depth_m}; })
    .filter(p => p.depth_m > 0.3).sort((a, b) => a.arrival_min - b.arrival_min);
  return {
    name: world.name, terrainUrl: terrain.dataUrl, terrainBounds: terrain.bounds_latlng, floodUrl: flood.dataUrl,
    extent_km2: floodedAreaKm2(world, inputs, scenario), peak_depth_m: computeProfile(world, inputs, scenario, 0).depth_m,
    coords: `${w.toFixed(3)}° E — ${e.toFixed(3)}° E · ${s.toFixed(3)}° N — ${n.toFixed(3)}° N`, places,
  };
}

export async function exportQuery(format: 'shp' | 'kml' | 'geojson' | 'pdf', queryId: string): Promise<Blob> {
  const q = store.getQuery(queryId);
  if (!q) throw new Error(`No preview demo query ${JSON.stringify(queryId)}`);
  const {buildExport} = await import('./engine/exports');
  return buildExport(format, q.site_id, queryId, q.inputs, q.scenario_type);
}
