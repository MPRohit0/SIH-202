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
import {api, useMocks, type FloodQueryRequest, type FloodQueryResponse, type ImpactResponse, type CompareResponse, type GeeLayers, type Timeline, type SiteSummary, type JobStatus} from './api';
import uiText from '../content/ui_text.json';

export type Awaiting = {status: 'awaiting'; reason: string};

export type {SiteSummary} from './api';

/** Contract §5.1 — GET /sites. */
export async function listSites(): Promise<SiteSummary[]> {
  return api.sites();
}

/** Contract §5.1 — GET /sites, GET /sites/{site_id}. */
export async function getSite(): Promise<SiteSummary | null> {
  const sites = await api.sites();
  return sites[0] ?? null;
}

/** Terrain for the active site (part of site detail / GET /scene3d/{query_id}). */
export async function getTerrain(siteId?: string): Promise<Awaiting & {grid: Grid | null}> {
  if (siteId) await api.site(siteId);
  else await api.sites();
  return {status: 'awaiting', reason: 'Site contract loaded; terrain grids are exposed through scene3d binary files, not the legacy Grid array required by this canvas.', grid: null};
}

/** Contract §5.4/§5 #10 — POST /flood/query, GET /flood/{query_id}. Covers
 * both the rapid-query slider and the Physics-run form. */
export async function queryFlood(request: FloodQueryRequest): Promise<FloodQueryResponse> {
  if (!request.site_id) throw new Error('A site_id is required to run a flood query.');
  let response = await api.floodQuery(request);
  if (response.status === 'failed') throw new Error('Flood query failed.');
  while (response.status === 'partial') {
    await new Promise(resolve => setTimeout(resolve, 500));
    response = await api.flood(response.query_id);
    if (response.status === 'failed') throw new Error('Flood query failed.');
  }
  return response;
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
  return api.impact(queryId);
}

/** Contract §5 #15 — GET /compare/{site_id}. */
export async function getCompare(siteId: string, scenarioId?: string): Promise<CompareResponse> {
  if (!siteId) throw new Error('A site_id is required to load model comparison.');
  return api.compare(siteId, scenarioId);
}

/** Contract §5 #19/#20 — GET /gee/{site_id}, POST /gee/{site_id}/refresh. */
export async function getObserved(siteId: string): Promise<GeeLayers> {
  if (!siteId) throw new Error('A site_id is required to load satellite layers.');
  return api.gee(siteId);
}
export async function refreshObserved(siteId: string): Promise<GeeLayers> {
  if (!siteId) throw new Error('A site_id is required to refresh satellite layers.');
  return api.refreshGee(siteId);
}
export async function getTimeline(queryId: string, intervalS = 300): Promise<Timeline> {
  if (!queryId) throw new Error('A query_id is required to load the flood timeline.');
  return api.timeline(queryId, intervalS);
}

/** Contract §6 — GET /styles (contracts/styles.json). Drives map legends and
 * colour classes; see STYLE_GUIDE.md §2.6 for the frontend palette that
 * should seed it. */
export async function getStyles(): Promise<Awaiting & {styles: unknown | null}> {
  return {status: 'awaiting', reason: 'Styles loaded from the contract; no display change is applied until map data is available.', styles: await api.styles()};
}

/** Contract §5 #18 — GET /export/{query_id}?format=. */
export async function exportUrl(format: 'shp' | 'kml' | 'geojson' | 'pdf', queryId: string): Promise<{url: string}> {
  if (!queryId) throw new Error('A query_id is required to export flood results.');
  const response = await api.export(queryId, format);
  return {url: URL.createObjectURL(await response.blob())};
}

/** Contract §5.2 — POST /sites (Add a Dam). */
export async function createSite(_input: {name: string; grid: Grid; params: Params}): Promise<Awaiting & {jobId: string | null}> {
  if (useMocks) {
    try { const accepted = await api.createSite(api.examples.siteRequest); return {status: 'awaiting', reason: 'Mock onboarding job accepted; the legacy UI has no contract job-progress state.', jobId: accepted.job_id}; } catch { /* retain the empty state */ }
  }
  throw new Error(uiText.onboarding.missingInputs);
}

/** Contract §5.3 — GET /jobs/{job_id}. */
export async function getJob(jobId: string): Promise<JobStatus> {
  if (!jobId) throw new Error('A job_id is required to load job status.');
  return api.job(jobId);
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
