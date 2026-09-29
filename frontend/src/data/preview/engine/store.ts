// Central, module-level demo state (design/target-state-preview). Not a React
// store -- app.tsx already owns its own useState for the UI; this just holds
// the state that must persist *between* separate preview/index.ts calls in
// the same session (e.g. "what did queryFlood(...) compute for this
// query_id, so getImpact(query_id) can look it up"), the same role the old
// fixture router's siteListStore/jobStartedAt maps played.
import type {ScenarioType, EmulatorInputRange} from './world';
import {getWorld, WORLDS, TEESTA, registerWorldFromTemplate} from './world';
import type {EngineInputs} from './physics';
import type {SiteSummary} from './types';

export type StoredQuery = {
  query_id: string; site_id: string; scenario_type: ScenarioType;
  mode: 'scenario' | 'unknown_breach'; inputs: EngineInputs; created_at: number;
  datasetPerturbation: number;
};

export type ScenarioLibraryEntry = {
  id: string; site_id: string; name: string; scenario_type: ScenarioType;
  mode: 'scenario' | 'unknown_breach'; inputs: EngineInputs; query_id: string; created_at: number;
};

export type DemoAlert = {
  id: string; site_id: string; severity: 'info' | 'warning'; text: string;
  action_label: string; scenario_type: ScenarioType; inputs: EngineInputs;
};

export type GeeState = {
  series: Array<{date: string; area_m2: number}>;
  lastCheckedAt: number;
  baselineAreaM2: number;
};

export type JobRecord = {
  job_id: string; site_id: string; kind: 'onboarding' | 'recheck' | 'rerun';
  started_at: number; duration_ms: number; result_site_id?: string;
};

function defaultInputsFor(scenarioType: ScenarioType, ranges: EmulatorInputRange[]): EngineInputs {
  const byName = Object.fromEntries(ranges.map(r => [r.name, r.default]));
  return {
    water_volume_m3: byName.water_volume_m3, breach_width_m: byName.breach_width_m, failure_time_s: byName.failure_time_s,
  };
}

class DemoStore {
  sites: SiteSummary[] = [];
  queries = new Map<string, StoredQuery>();
  jobs = new Map<string, JobRecord>();
  scenarioLibrary: ScenarioLibraryEntry[] = [];
  geeState = new Map<string, GeeState>();
  alerts: DemoAlert[] = [];
  datasetSelections: Record<string, string> = {dem: 'copernicus_glo30', land_cover: 'esa_worldcover', population: 'worldpop', hydrology: 'cwc_gauge'};
  recentQueryIds: string[] = [];
  /** The scenario type (dam_breach/glof/river_blockage/cascade) the Simulation
   * screen's selector last chose; queryFlood() reads this so the rest of the
   * app doesn't need to thread scenarioType through every call. */
  currentScenarioType: ScenarioType | undefined = undefined;
  private queryCounter = 0;
  private nextSiteSuffix = 1;

  constructor() { this.reset(); }

  reset() {
    this.sites = [
      {site_id: 'teesta', name: 'Teesta — South Lhonak GLOF to Teesta III', status: 'ready', bbox_lonlat: TEESTA.bbox_lonlat, has_placeholders: false},
      {site_id: 'rishi_ganga', name: 'Rishi Ganga — Raunthi Gad landslide lake', status: 'outdated', status_reason_key: 'outdated_config_changed', bbox_lonlat: WORLDS.rishi_ganga.bbox_lonlat, has_placeholders: false,
        recheck: {frequency_days: 30, last_checked_at: new Date(Date.now() - 25 * 86400000).toISOString(), next_check_at: new Date(Date.now() + 5 * 86400000).toISOString()}},
    ];
    this.queries.clear();
    this.jobs.clear();
    this.scenarioLibrary = [];
    this.geeState = new Map([
      ['teesta', {series: [
        {date: '2023-08-01', area_m2: 1_674_000}, {date: '2023-09-28', area_m2: 1_674_000}, {date: '2023-10-04', area_m2: 603_000},
        {date: '2024-06-01', area_m2: 640_000}, {date: '2025-06-01', area_m2: 705_000},
      ], lastCheckedAt: Date.now(), baselineAreaM2: 705_000}],
      ['rishi_ganga', {series: [
        {date: '2021-03-01', area_m2: 210_000}, {date: '2022-06-01', area_m2: 245_000}, {date: '2023-06-01', area_m2: 268_000},
      ], lastCheckedAt: Date.now() - 25 * 86400000, baselineAreaM2: 268_000}],
    ]);
    this.alerts = [
      {id: 'alert_seed_rishi_ganga', site_id: 'rishi_ganga', severity: 'warning',
        text: 'Raunthi Gad lake area has grown 15% since the last approved run — the emulator library is outdated.',
        action_label: 'Run scenario now', scenario_type: 'river_blockage',
        inputs: defaultInputsFor('river_blockage', WORLDS.rishi_ganga.emulatorInputs)},
    ];
    this.recentQueryIds = [];
    this.queryCounter = 0;
    this.nextSiteSuffix = 1;
  }

  worldFor(siteId: string) { return getWorld(siteId); }

  newQueryId(): string {
    this.queryCounter += 1;
    const n = String(this.queryCounter).padStart(4, '0');
    return `q_demo_${Date.now().toString(36)}_${n}`;
  }

  saveQuery(q: StoredQuery) {
    this.queries.set(q.query_id, q);
    this.recentQueryIds.unshift(q.query_id);
    this.recentQueryIds = this.recentQueryIds.slice(0, 10);
  }

  getQuery(queryId: string): StoredQuery | undefined { return this.queries.get(queryId); }

  addScenarioToLibrary(entry: Omit<ScenarioLibraryEntry, 'id' | 'created_at'>): ScenarioLibraryEntry {
    const full: ScenarioLibraryEntry = {...entry, id: `lib_${this.scenarioLibrary.length + 1}`, created_at: Date.now()};
    this.scenarioLibrary.push(full);
    return full;
  }

  newJobId(kind: JobRecord['kind']): string { return `job_${kind}_${Date.now().toString(36)}`; }

  startJob(rec: JobRecord) { this.jobs.set(rec.job_id, rec); }
  getJob(jobId: string): JobRecord | undefined { return this.jobs.get(jobId); }

  addSiteFromDam(name: string, lon: number, lat: number): SiteSummary {
    const id = `demo_site_${this.nextSiteSuffix++}`;
    const world = registerWorldFromTemplate(id, name, lon, lat);
    const summary: SiteSummary = {site_id: id, name, status: 'onboarding', bbox_lonlat: world.bbox_lonlat, has_placeholders: false};
    this.sites.push(summary);
    return summary;
  }

  markSiteReady(siteId: string) {
    const s = this.sites.find(s => s.site_id === siteId);
    if (s) s.status = 'ready';
  }
}

export const store = new DemoStore();
