// Preview data mode router (design/target-state-preview only).
//
// Returns fixture JSON in place of live API/mock responses when
// VITE_DATA_MODE=preview. Every fixture here is registered in manifest.json
// and validated against its contract schema by
// tests/frontend/test_preview_fixtures.py -- this file must not reshape a
// fixture in a way that could make it schema-invalid; it only selects and
// returns them.
//
// Default mode (no VITE_DATA_MODE, or any value other than 'preview') never
// imports this module's fixture data at runtime beyond the static import
// below; see src/data/source.ts for the mode switch.
import manifest from './manifest.json';
import siteList from './site_list.json';
import siteDetailTeesta from './site_detail.teesta.json';
import siteDetailRishiGanga from './site_detail.rishi_ganga.json';
import siteDetailDemoValley from './site_detail.demo_valley.json';
import siteDetailSynthEngdam from './site_detail.synth_engdam.json';
import siteCreateAccepted from './site_create_accepted.json';
import jobStageQueued from './job_status.onboarding.queued.json';
import jobStageTerrain from './job_status.onboarding.terrain.json';
import jobStageBreach from './job_status.onboarding.breach.json';
import jobStageDesign from './job_status.onboarding.design.json';
import jobStageSimulating from './job_status.onboarding.simulating.json';
import jobStageTraining from './job_status.onboarding.training.json';
import jobStageValidating from './job_status.onboarding.validating.json';
import jobStageReady from './job_status.onboarding.ready.json';
import runMetaTeestaPilot from './run_meta.teesta_pilot_s001__delft3d.json';
import floodQueryTeestaSph from './flood_query_response.teesta.sph_direct.json';
import scene3dTeestaSph from './scene3d.q_20260929T093000Z_9f3ab2.json';
import compareTeesta from './compare.teesta.json';
import floodQueryTeestaAzmiLow from './flood_query_response.teesta.scenario_azmi_low.json';
import floodQueryTeestaAzmiHigh from './flood_query_response.teesta.scenario_azmi_high.json';
import floodQueryTeestaUnknownBreach from './flood_query_response.teesta.unknown_breach.json';
import floodQueryTeestaOutsideRange from './flood_query_response.teesta.scenario_outside_range.json';
import geeLayersTeesta from './gee_layers.teesta.json';
import geeLayersRishiGanga from './gee_layers.rishi_ganga.json';
import type {SiteSummary, SiteDetail, SiteCreateAccepted, JobStatus, FloodQueryRequest, FloodQueryResponse, Scene3DResponse, CompareResponse, GeeLayers} from '../api';

const siteDetails: Record<string, SiteDetail> = {
  teesta: siteDetailTeesta as unknown as SiteDetail,
  rishi_ganga: siteDetailRishiGanga as unknown as SiteDetail,
  demo_valley: siteDetailDemoValley as unknown as SiteDetail,
  synth_engdam: siteDetailSynthEngdam as unknown as SiteDetail,
};

/** Every fixture file this router can serve, keyed exactly as manifest.json
 * lists them. Used by dev-time assertions; not required at runtime. */
export const fixtureManifest = manifest;

// Screen 7's re-check frequency control mutates this in place (via
// updateRecheckFrequency below) so the change is visible everywhere
// listSites() is read from in the same session -- a plain per-call
// structuredClone(siteList) would silently discard the edit.
const siteListStore: SiteSummary[] = structuredClone(siteList) as unknown as SiteSummary[];

export async function listSites(): Promise<SiteSummary[]> {
  return structuredClone(siteListStore);
}

export async function getSiteDetail(siteId: string): Promise<SiteDetail> {
  const detail = siteDetails[siteId];
  if (!detail) throw new Error(`No preview fixture for site_id ${JSON.stringify(siteId)}. Known preview sites: ${Object.keys(siteDetails).join(', ')}`);
  return structuredClone(detail);
}

export async function getSite(): Promise<SiteSummary | null> {
  const sites = await listSites();
  return sites[0] ?? null;
}

// Screen 2 (Add-a-Dam / run flow / job progress): a single scripted onboarding
// job that actually advances through the 8 real contract stages (job_status
// schema: onboarding kind) over ~20s of wall-clock time, so the preview shows
// live progress rather than a static snapshot. jobStartedAt is keyed by
// job_id so multiple "Add a new site" attempts in one session each get their
// own timeline.
const PREVIEW_JOB_ID = (siteCreateAccepted as unknown as SiteCreateAccepted).job_id;
const JOB_STAGE_SEQUENCE: JobStatus[] = [
  jobStageQueued, jobStageTerrain, jobStageBreach, jobStageDesign,
  jobStageSimulating, jobStageTraining, jobStageValidating, jobStageReady,
] as unknown as JobStatus[];
const JOB_STAGE_DURATION_MS = 2500;
const jobStartedAt = new Map<string, number>();

export async function createSite(): Promise<SiteCreateAccepted> {
  const accepted = structuredClone(siteCreateAccepted) as unknown as SiteCreateAccepted;
  jobStartedAt.set(accepted.job_id, Date.now());
  return accepted;
}

export async function getJob(jobId: string): Promise<JobStatus> {
  if (jobId !== PREVIEW_JOB_ID) throw new Error(`No preview fixture for job_id ${JSON.stringify(jobId)}.`);
  const startedAt = jobStartedAt.get(jobId) ?? Date.now();
  const elapsedMs = Date.now() - startedAt;
  const stageIndex = Math.min(JOB_STAGE_SEQUENCE.length - 1, Math.floor(elapsedMs / JOB_STAGE_DURATION_MS));
  return structuredClone(JOB_STAGE_SEQUENCE[stageIndex]);
}

/** Screen 2's run-metadata panel. The only real solver run in the repo is the
 * frozen teesta_pilot_s001 D-Flow FM pilot (docs/m3_spec.md) -- it is shown as
 * an example of the target-state panel, not as the new site's own output; see
 * the fixture's own x_preview_provenance note. */
export async function getRunMeta(): Promise<Record<string, unknown>> {
  return structuredClone(runMetaTeestaPilot);
}

/** Screen 3 (Terrain): x_preview_terrain is a proposed contract addition (see
 * README.md "Preview mode"), not a real site_detail field -- it only exists on
 * fixtures that were built with it (currently teesta). Its LayerRef URLs are
 * root-relative paths into frontend/public/preview/, served by Vite itself,
 * not backend files -- callers must not run them through api.fileUrl. */
export async function getTerrainMeta(siteId: string): Promise<Record<string, unknown> | null> {
  const detail = siteDetails[siteId] as unknown as {x_preview_terrain?: Record<string, unknown>} | undefined;
  return detail?.x_preview_terrain ? structuredClone(detail.x_preview_terrain) : null;
}

// Screen 4 (near-field 3D / SPH result), and future screens 5/6/8/9: canned
// flood_query_response fixtures keyed by "site_id|model|mode". There is no
// usable real Teesta SPH result in this repo to reuse (the real a02 attempt
// is flagged anomalous, see ui_text.json onboarding.noPairedSph) -- this is
// illustrative, per the fixture's own provenance note.
const FLOOD_QUERY_FIXTURES: Record<string, FloodQueryResponse> = {
  'teesta|sph|scenario': floodQueryTeestaSph as unknown as FloodQueryResponse,
  'teesta|delft3d|scenario': floodQueryTeestaAzmiLow as unknown as FloodQueryResponse,
  'teesta|delft3d|unknown_breach': floodQueryTeestaUnknownBreach as unknown as FloodQueryResponse,
};
const SCENE3D_FIXTURES: Record<string, Scene3DResponse> = {
  [(floodQueryTeestaSph as unknown as FloodQueryResponse).query_id]: scene3dTeestaSph as unknown as Scene3DResponse,
};

export async function queryFlood(request: FloodQueryRequest): Promise<FloodQueryResponse> {
  const key = `${request.site_id}|${request.model}|${request.mode}`;
  const fixture = FLOOD_QUERY_FIXTURES[key];
  if (!fixture) throw new Error(`No preview fixture for a flood query with site_id=${request.site_id}, model=${request.model}, mode=${request.mode}.`);
  return structuredClone(fixture);
}

export async function getScene3d(queryId: string): Promise<Scene3DResponse> {
  const scene = SCENE3D_FIXTURES[queryId];
  if (!scene) throw new Error(`No preview scene3d fixture for query_id ${JSON.stringify(queryId)}.`);
  return structuredClone(scene);
}

/** The scene3d binary arrays are served as static files under
 * frontend/public/preview/ by Vite itself (root-relative URLs), so this reads
 * them with a plain same-origin fetch rather than api.file (which targets the
 * backend's own origin/baseUrl). */
export async function getScene3dArrays(scene: Scene3DResponse): Promise<{terrain: Float32Array; flood: Float32Array}> {
  const [terrainRes, floodRes] = await Promise.all([fetch(scene.terrain.url), fetch(scene.flood_surface.url)]);
  if (!terrainRes.ok || !floodRes.ok) throw new Error('Failed to load the preview 3D scene terrain/flood arrays.');
  const [terrainBuf, floodBuf] = await Promise.all([terrainRes.arrayBuffer(), floodRes.arrayBuffer()]);
  return {terrain: new Float32Array(terrainBuf), flood: new Float32Array(floodBuf)};
}

/** Screen 5 (Model Comparison): SPH vs D-Flow FM on the same near-field
 * section and scenario as screen 4's flood_query_response. Every metric is
 * computed by gen_preview_assets.py from generated grids, not hand-typed --
 * see the fixture's own x_preview_provenance note. */
const COMPARE_FIXTURES: Record<string, CompareResponse> = {
  teesta: compareTeesta as unknown as CompareResponse,
};

export async function getCompare(siteId: string): Promise<CompareResponse> {
  const fixture = COMPARE_FIXTURES[siteId];
  if (!fixture) throw new Error(`No preview compare fixture for site_id ${JSON.stringify(siteId)}.`);
  return structuredClone(fixture);
}

/** Screen 6 (scenario mode): "Scenario mode shows both Azmi pair members as
 * separate scenarios, with no probabilities" -- both members are returned
 * together rather than picking one, since the target-state UI shows them
 * side by side, not toggled between. */
const SCENARIO_PAIR_FIXTURES: Record<string, {low: FloodQueryResponse; high: FloodQueryResponse}> = {
  teesta: {
    low: floodQueryTeestaAzmiLow as unknown as FloodQueryResponse,
    high: floodQueryTeestaAzmiHigh as unknown as FloodQueryResponse,
  },
};

export async function getScenarioPair(siteId: string): Promise<{low: FloodQueryResponse; high: FloodQueryResponse}> {
  const pair = SCENARIO_PAIR_FIXTURES[siteId];
  if (!pair) throw new Error(`No preview Azmi-pair fixture for site_id ${JSON.stringify(siteId)}.`);
  return {low: structuredClone(pair.low), high: structuredClone(pair.high)};
}

/** Acceptance test A6 (m5_specs.md §7): a scenario-mode query deliberately
 * placed 10% outside the trained V_w range, showing confidence correctly
 * firing "Low (C: query outside trained V_w range)". */
const OUTSIDE_RANGE_EXAMPLE_FIXTURES: Record<string, FloodQueryResponse> = {
  teesta: floodQueryTeestaOutsideRange as unknown as FloodQueryResponse,
};

export async function getOutsideRangeExample(siteId: string): Promise<FloodQueryResponse> {
  const fixture = OUTSIDE_RANGE_EXAMPLE_FIXTURES[siteId];
  if (!fixture) throw new Error(`No preview A6 example fixture for site_id ${JSON.stringify(siteId)}.`);
  return structuredClone(fixture);
}

// Screen 7 (GEE monitoring): teesta's series/imagery dates are the real
// ISRO/NRSC South Lhonak figures (docs/data_sources.md src_072); rishi_ganga
// is fully illustrative and demonstrates the library-outdated banner (its
// recheck.change_pct exceeds threshold_pct) -- see each fixture's own
// x_preview_provenance note for exactly which numbers are real vs illustrative.
const GEE_LAYERS_FIXTURES: Record<string, GeeLayers> = {
  teesta: geeLayersTeesta as unknown as GeeLayers,
  rishi_ganga: geeLayersRishiGanga as unknown as GeeLayers,
};

export async function getObserved(siteId: string): Promise<GeeLayers> {
  const fixture = GEE_LAYERS_FIXTURES[siteId];
  if (!fixture) throw new Error(`No preview gee_layers fixture for site_id ${JSON.stringify(siteId)}.`);
  return structuredClone(fixture);
}

/** "Refresh satellite cache" in preview mode re-serves the same fixture with
 * fetched_at bumped to now -- there is no live Earth Engine call to make. */
export async function refreshObserved(siteId: string): Promise<GeeLayers> {
  const fixture = await getObserved(siteId);
  fixture.fetched_at = new Date().toISOString();
  return fixture;
}

/** Screen 7's re-check frequency control (contract §5 #7, PUT
 * /sites/{site_id}/recheck). Mutates siteListStore in place so every reader
 * of listSites() sees the change for the rest of the session. */
export async function updateRecheckFrequency(siteId: string, frequencyDays: number): Promise<SiteSummary> {
  const site = siteListStore.find(s => s.site_id === siteId);
  if (!site) throw new Error(`No preview site_list entry for site_id ${JSON.stringify(siteId)}.`);
  const lastCheckedAt = site.recheck?.last_checked_at ?? new Date().toISOString();
  const nextCheckAt = new Date(new Date(lastCheckedAt).getTime() + frequencyDays * 86400000).toISOString();
  site.recheck = {frequency_days: frequencyDays, last_checked_at: lastCheckedAt, next_check_at: nextCheckAt};
  return structuredClone(site);
}
