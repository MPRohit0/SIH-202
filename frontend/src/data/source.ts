/// <reference types="vite/client" />
// Single seam between the UI and real data.
//
// Legacy UI adapters call the contract client in api.ts. Responses whose
// Estimate and raster/file forms cannot fit the old canvas models stay empty
// instead of being converted into guessed values. Components must not fetch.
//
// Two functions in this file (listScenarios, listSavedRuns) have no
// endpoint in the current contract. They are flagged below; ask before
// inventing routes for them.
import type {Grid, Params, Result} from '@/lib/model';
import type {Scenario} from '@/lib/sentriq';
import {api, useMocks, type FloodQueryRequest, type FloodQueryResponse, type ImpactResponse, type CompareResponse, type GeeLayers, type Timeline, type SiteSummary, type SiteDetail, type JobStatus, type ValidationResponse, type HistoricalValidationResponse, type Scene3DResponse} from './api';
import * as preview from './preview';
import type {CompareOpts, CompareWorkbench} from './preview/engine/compare';
import uiText from '../content/ui_text.json';
import * as offlineCache from '../offline/cache-store';
import {collectGlobalUrls, collectResourceUrls, type OfflineBundle} from '../offline/resource-list';

export type Awaiting = {status: 'awaiting'; reason: string};

export type {SiteSummary} from './api';
export type {SavedQuery} from '../offline/cache-store';
export type {OfflineBundle} from '../offline/resource-list';

/** design/target-state-preview: a third data source, alongside the live API and
 * VITE_USE_MOCKS, that serves the fixtures in src/data/preview/*.json. It exists
 * so the target-state screens can be demonstrated with illustrative, schema-valid
 * data before the real pipelines (M1-M7) produce it. Selected by
 * VITE_DATA_MODE=preview; every other value (including unset) leaves every
 * function below on its original, unchanged code path. See frontend/README.md
 * "Preview mode" for what this does and does not mean. */
export const isPreviewMode = (): boolean => { const mode = import.meta.env.VITE_DATA_MODE; return mode === 'preview' || !mode; };

/** Mock switch and the one registered direct solver scenario exposed for the MVP site. */
export function isMockMode(): boolean { return useMocks; }
export function directEventScenarioId(siteId: string): string | undefined {
  return !useMocks && !isPreviewMode() && siteId === 'teesta' ? 'teesta_2023_mvp' : undefined;
}

/** Contract §5.1 — GET /sites. */
export async function listSites(): Promise<SiteSummary[]> {
  if (isPreviewMode()) return preview.listSites();
  return api.sites();
}

/** Contract §5.1 — GET /sites, GET /sites/{site_id}. */
export async function getSite(): Promise<SiteSummary | null> {
  if (isPreviewMode()) return preview.getSite();
  const sites = await api.sites();
  return sites[0] ?? null;
}

/** Terrain for the active site (part of site detail / GET /scene3d/{query_id}). */
export async function getTerrain(siteId?: string): Promise<Awaiting & {grid: Grid | null}> {
  if (!isPreviewMode()) {
    if (siteId) await api.site(siteId);
    else await api.sites();
  }
  return {status: 'awaiting', reason: 'Site contract loaded; terrain grids are exposed through scene3d binary files, not the legacy Grid array required by this canvas.', grid: null};
}

/** Contract §5.4/§5 #10 — POST /flood/query, GET /flood/{query_id}. Covers
 * both the rapid-query slider and the Physics-run form. */
export async function queryFlood(request: FloodQueryRequest): Promise<FloodQueryResponse> {
  if (!request.site_id) throw new Error('A site_id is required to run a flood query.');
  if (isPreviewMode()) return preview.queryFlood(request);
  let response = await api.floodQuery(request);
  if (response.status === 'failed') throw new Error('Flood query failed.');
  while (response.status === 'partial') {
    await new Promise(resolve => setTimeout(resolve, 500));
    response = await api.flood(response.query_id);
    if (response.status === 'failed') throw new Error('Flood query failed.');
  }
  return response;
}

/** Typed adapter from the canonical LayerRef to the existing image-overlay renderer.
 * Uses the response already returned by queryFlood; it does not fetch a second result
 * or infer raster values/georeferencing from the legacy Grid model. */
export type FloodRasterOverlay = {
  layerId: string; url: string; boundsLatLng: [[number, number], [number, number]];
  styleId: string; unit: string | null;
};
export function floodRasterOverlay(response: FloodQueryResponse | null, layerId = 'depth_p50'): FloodRasterOverlay | null {
  const refs = response?.layers.filter(layer => layer.available && layer.type === 'raster_png') ?? [];
  // The frozen contract example only contains p_inundation. Preserve that mock
  // fixture path while real responses must provide the requested layer. Preview
  // mode's demo engine only ever renders one layer per response too (depth_p50
  // for a scenario query, p_inundation for an unknown_breach query) -- without
  // this fallback, requesting the "Depth" layer pill against an unknown_breach
  // result found no match and rendered nothing at all.
  const ref = refs.find(layer => layer.layer_id === layerId) ?? ((useMocks || isPreviewMode()) ? refs[0] : undefined);
  if (!ref || ref.bounds_latlng.length !== 2 || ref.bounds_latlng.some(point => point.length !== 2)) return null;
  return {layerId: ref.layer_id, url: fileUrl(ref.url), boundsLatLng: ref.bounds_latlng as [[number, number], [number, number]], styleId: ref.style_id, unit: ref.unit};
}

/** The existing playback control selects a contract Timeline snapshot URL.
 * Feed that file reference into the same raster image-overlay renderer used by
 * the static depth layer; no values or bounds are reconstructed in the UI. */
export function timelineRasterOverlay(timeline: Timeline | null, frameIndex: number): FloodRasterOverlay | null {
  const frames = timeline?.frames ?? [];
  if (!frames.length) return null;
  const frame = frames[Math.max(0, Math.min(frames.length - 1, frameIndex))];
  return {layerId: 'timeline_depth', url: fileUrl(frame.median_url),
    boundsLatLng: frame.bounds_latlng as [[number, number], [number, number]],
    styleId: 'depth_p50', unit: 'm'};
}

/** The prepared scenario library for the active site. No endpoint exists for
 * this in docs/handoff_contract.md §5 yet — ask before wiring this to a
 * real route. */
export async function listScenarios(): Promise<Awaiting & {scenarios: Scenario[]}> {
  return {status: 'awaiting', reason: 'No scenario library exists for this site yet.', scenarios: []};
}

/** Contract §5 #14 / §4.7 — GET /impact/{query_id}. */
export async function getImpact(queryId: string): Promise<ImpactResponse> {
  if (!queryId) throw new Error('A query_id is required to load impact results.');
  if (isPreviewMode()) return preview.getImpact(queryId);
  return api.impact(queryId);
}

/** Contract §5 #15 — GET /compare/{site_id}. `opts` (domain/threshold/tIndex/
 * runId) is preview-only -- ignored outside preview mode, where the contract
 * has no such query parameters yet. */
export async function getCompare(siteId: string, scenarioId?: string, opts?: CompareOpts): Promise<CompareResponse> {
  if (!siteId) throw new Error('A site_id is required to load model comparison.');
  if (isPreviewMode()) return preview.getCompare(siteId, opts);
  return api.compare(siteId, scenarioId);
}

/** design/target-state-preview Compare page: the raw grids/scenes/POI pairs
 * behind getCompare (Float32Arrays, Scene3DResponse objects, the run
 * dropdown list) -- returns null outside preview mode, same pattern as
 * getScenarioPair. See engine/compare.ts's module doc for what CompareView
 * does with this. */
export async function getCompareWorkbench(siteId: string, opts?: CompareOpts): Promise<CompareWorkbench | null> {
  if (!siteId || !isPreviewMode()) return null;
  return preview.getCompareWorkbench(siteId, opts);
}
/** Contract §5.7 — GET /validation/{site_id}. */
export async function getValidation(siteId: string): Promise<ValidationResponse> {
  if (!siteId) throw new Error('A site_id is required to load validation status.');
  if (isPreviewMode()) return preview.getValidation(siteId);
  return api.validation(siteId);
}
/** Contract §5.7 — GET /validation/{site_id}?event={event_id}. */
export async function getHistoricalValidation(siteId: string, eventId: string): Promise<HistoricalValidationResponse> {
  if (!siteId) throw new Error('A site_id is required to load historical validation.');
  if (!eventId) throw new Error('An event_id is required to load historical validation.');
  if (isPreviewMode()) return preview.getHistoricalValidation(siteId, eventId);
  return api.historicalValidation(siteId, eventId);
}

/** Contract §5 #19/#20 — GET /gee/{site_id}, POST /gee/{site_id}/refresh. */
export async function getObserved(siteId: string): Promise<GeeLayers> {
  if (!siteId) throw new Error('A site_id is required to load satellite layers.');
  if (isPreviewMode()) return preview.getObserved(siteId);
  return api.gee(siteId);
}
/** Resolve a contract file reference through the shared API client origin.
 * Preview URLs are already root-relative paths into frontend/public/preview/,
 * served by Vite itself -- passed through unchanged rather than prefixed with
 * the backend's own baseUrl (api.fileUrl targets the backend origin). */
export function fileUrl(path: string): string {
  // Preview mode never has a real backend to resolve a file reference against
  // (rule 11); falling through to api.fileUrl() for anything unexpected (e.g.
  // a preview fixture's intentionally blank '' url for imagery with no cached
  // screenshot) resolved to the bare API origin and produced a real, repeated
  // GET .../api/v1/ 404 against a backend that may not even be running.
  if (isPreviewMode()) return path;
  return api.fileUrl(path);
}
export async function refreshObserved(siteId: string): Promise<GeeLayers> {
  if (!siteId) throw new Error('A site_id is required to refresh satellite layers.');
  if (isPreviewMode()) return preview.refreshObserved(siteId);
  return api.refreshGee(siteId);
}

/** design/target-state-preview screen 7: the re-check frequency setting
 * (contract §5 #7, PUT /sites/{site_id}/recheck). */
export async function setRecheckFrequency(siteId: string, frequencyDays: number): Promise<SiteSummary> {
  if (!siteId) throw new Error('A site_id is required to update the re-check frequency.');
  if (isPreviewMode()) return preview.updateRecheckFrequency(siteId, frequencyDays);
  return api.recheck(siteId, {frequency_days: frequencyDays}) as Promise<SiteSummary>;
}
export async function getTimeline(queryId: string, intervalS = 300): Promise<Timeline> {
  if (!queryId) throw new Error('A query_id is required to load the flood timeline.');
  if (isPreviewMode()) return preview.getTimeline(queryId);
  return api.timeline(queryId, intervalS);
}

/** Contract §5.9 — GET /scene3d/{query_id}. */
export async function getScene3d(queryId: string, verticalExaggeration = 1.5): Promise<Scene3DResponse> {
  if (!queryId) throw new Error('A query_id is required to load the 3D scene.');
  if (isPreviewMode()) return preview.getScene3d(queryId);
  return api.scene3d(queryId, verticalExaggeration);
}

/** Fetches the scene's two headerless float32_le_row_major arrays (contracts/scene3d.md).
 * Kept here, not in the component, per this file's "components must not fetch" rule. */
export type Scene3DArrays = {terrain: Float32Array; flood: Float32Array};
export async function getScene3dArrays(scene: Scene3DResponse): Promise<Scene3DArrays> {
  if (isPreviewMode()) return preview.getScene3dArrays(scene);
  const [terrainRes, floodRes] = await Promise.all([api.file(scene.terrain.url), api.file(scene.flood_surface.url)]);
  if (!terrainRes.ok || !floodRes.ok) throw new Error('Failed to load the 3D scene terrain/flood arrays.');
  const [terrainBuf, floodBuf] = await Promise.all([terrainRes.arrayBuffer(), floodRes.arrayBuffer()]);
  return {terrain: new Float32Array(terrainBuf), flood: new Float32Array(floodBuf)};
}

/** Contract §5.1 — GET /sites/{site_id}, for the real dam list (location/breach_location). */
export async function getSiteDetail(siteId: string): Promise<SiteDetail> {
  if (!siteId) throw new Error('A site_id is required to load site detail.');
  if (isPreviewMode()) return preview.getSiteDetail(siteId);
  return api.site(siteId) as Promise<SiteDetail>;
}

/** A run's own run_meta.json, read through the generic asset passthrough (contract §1.8
 * file layout under /api/v1/files/) -- not a schema-validated response, just the real
 * artifact file M3 already wrote. Returns null (never invents) when it isn't there. */
export async function getRunMeta(siteId: string, runId: string): Promise<Record<string, unknown> | null> {
  if (!siteId || !runId) return null;
  const res = await api.file(`files/${siteId}/runs/${runId}/run_meta.json`);
  if (!res.ok) return null;
  return res.json();
}

/** Any other real per-site artifact JSON under data/<site_id>/... exposed through the same
 * generic passthrough (breach hydrograph forcing provenance, breach_params.json). `relPath`
 * is relative to the site's data dir, e.g. "breach/breach_params.json". 404 -> null. */
export async function getSiteArtifactJson(siteId: string, relPath: string): Promise<Record<string, unknown> | null> {
  if (!siteId || !relPath) return null;
  const res = await api.file(`files/${siteId}/${relPath}`);
  if (!res.ok) return null;
  return res.json();
}

/** Contract §6 — GET /styles (contracts/styles.json). Drives map legends and
 * colour classes; see STYLE_GUIDE.md §2.6 for the frontend palette that
 * should seed it. */
export async function getStyles(): Promise<Awaiting & {styles: unknown | null}> {
  // contracts/styles.json is the project's real, checked-in style definition (legend
  // colours/class edges), not simulation output, so preview mode serves it directly
  // rather than adding a fixture copy.
  const styles = isPreviewMode() ? api.examples.styles : await api.styles();
  return {status: 'awaiting', reason: 'Styles loaded from the contract; no display change is applied until map data is available.', styles};
}

/** Contract §5 #18 — GET /export/{query_id}?format=. */
export async function exportUrl(format: 'shp' | 'kml' | 'geojson' | 'pdf', queryId: string): Promise<{url: string}> {
  if (!queryId) throw new Error('A query_id is required to export flood results.');
  const response = await api.export(queryId, format);
  return {url: URL.createObjectURL(await response.blob())};
}

/** Contract §5.2 — POST /sites (Add a Dam). */
export async function createSite(_input: {name: string; grid: Grid; params: Params}): Promise<Awaiting & {jobId: string | null}> {
  if (isPreviewMode()) {
    const accepted = await preview.createSite();
    return {status: 'awaiting', reason: 'Preview onboarding job accepted; the legacy UI has no contract job-progress state.', jobId: accepted.job_id};
  }
  if (useMocks) {
    try { const accepted = await api.createSite(api.examples.siteRequest); return {status: 'awaiting', reason: 'Mock onboarding job accepted; the legacy UI has no contract job-progress state.', jobId: accepted.job_id}; } catch { /* retain the empty state */ }
  }
  throw new Error(uiText.onboarding.missingInputs);
}

/** Contract §5.3 — GET /jobs/{job_id}. */
export async function getJob(jobId: string): Promise<JobStatus> {
  if (!jobId) throw new Error('A job_id is required to load job status.');
  if (isPreviewMode()) return preview.getJob(jobId);
  return api.job(jobId);
}

/** design/target-state-preview screen 2's run-metadata panel (runtime, mesh
 * size, disk). Shows the one real solver run in the repo -- see the fixture's
 * own x_preview_provenance note for what it is and isn't. */
export async function getPreviewRunMeta(): Promise<Record<string, unknown>> {
  return preview.getRunMeta();
}

/** design/target-state-preview screen 3 (Terrain): vertical datum, resolution,
 * DEM and domain-mask layers. This is a proposed contract addition
 * (README.md "Preview mode"), not a real site_detail field, so default mode
 * returns null rather than guessing at a shape. */
export async function getTerrainMeta(siteId: string): Promise<Record<string, unknown> | null> {
  if (!siteId || !isPreviewMode()) return null;
  return preview.getTerrainMeta(siteId);
}

/** design/target-state-preview screen 6 (scenario mode): both Azmi-pair
 * members, shown side by side with no probabilities. Preview-only -- no
 * equivalent default-mode route exists yet for "run both pair members". */
export async function getScenarioPair(siteId: string): Promise<{low: FloodQueryResponse; high: FloodQueryResponse} | null> {
  if (!siteId || !isPreviewMode()) return null;
  return preview.getScenarioPair(siteId);
}

/** design/target-state-preview screen 6: acceptance test A6's "10% outside the
 * training box" confidence example (m5_specs.md §7). Preview-only. */
export async function getOutsideRangeExample(siteId: string): Promise<FloodQueryResponse | null> {
  if (!siteId || !isPreviewMode()) return null;
  return preview.getOutsideRangeExample(siteId);
}

/** Saved runs / sites. No endpoint exists for this in the contract yet (the
 * prototype used Cloudflare D1/R2 + ChatGPT auth, which rule 11 disallows).
 * Ask before wiring this to a real route. */
export async function listSavedRuns(): Promise<Awaiting & {records: unknown[]}> {
  return {status: 'awaiting', reason: 'Saved-run storage is not connected yet.', records: []};
}
export async function saveRun(_kind: 'run' | 'site', _name: string, _data: unknown): Promise<Awaiting & {record: unknown | null}> {
  return {status: 'awaiting', reason: 'Saved-run storage is not connected yet.', record: null};
}

/** Offline caching (src/offline/) — registers the app-shell service worker
 * once at startup; components never touch Cache Storage or the worker
 * directly, only through this seam. */
export function initOffline(): void { offlineCache.registerOfflineWorker(); }
export function isOfflineCacheSupported(): boolean { return offlineCache.isCacheSupported(); }
export function listSavedOfflineQueries() { return offlineCache.listSavedQueries(); }
export function latestSavedOfflineQuery() { return offlineCache.latestSavedQuery(); }
export function deleteSavedOfflineQuery(queryId: string): void { offlineCache.deleteSavedQuery(queryId); }

/** Estimates the download size of a "save for offline" of this bundle without saving anything. */
export async function estimateOfflineSaveSize(bundle: OfflineBundle) {
  return offlineCache.estimateSaveSize([...collectGlobalUrls(), ...collectResourceUrls(bundle)]);
}

/** Fetches and stores every resource behind an already-loaded query so the
 * dashboard can reopen it later with no connection. */
export async function saveQueryForOffline(bundle: OfflineBundle, siteName: string, onProgress?: (p: {done: number; total: number}) => void) {
  const urls = [...collectGlobalUrls(), ...collectResourceUrls(bundle)];
  return offlineCache.saveForOffline(bundle.siteId, bundle.floodQuery.query_id, siteName, urls, onProgress);
}

/** Reopens a previously saved query straight from the cache — never a fresh
 * POST /flood/query, which would mint a new, uncached query_id. */
export async function loadSavedOfflineQuery(queryId: string): Promise<FloodQueryResponse> {
  return api.flood(queryId);
}

/** design/target-state-preview: the scenario-state calculator behind every
 * slider/control-driven number on the Dashboard and Simulation pages (the
 * four KPI tiles, downstream-impact arrivals, the map legend range --
 * docs/progress.md). Preview-only; a pure function, so callers gate on
 * isPreviewMode() themselves rather than this module doing it. */
export {computeScenarioState, severityMultiplier as scenarioSeverityMultiplier, domainTraversalMinutes as scenarioDomainTraversalMinutes, timeFactor as scenarioTimeFactor} from './preview/engine/scenario_state';
export type {ScenarioState, ScenarioStateInputs, PoiState as ScenarioPoiState, Ranged as ScenarioRanged} from './preview/engine/scenario_state';
