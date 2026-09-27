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
import type {Scenario, Exposure} from '@/lib/sentriq';
import {api, useMocks} from './api';

export type Awaiting = {status: 'awaiting'; reason: string};

export type SiteSummary = {
  site_id: string;
  name: string;
  status: 'onboarding' | 'demo_mode' | 'ready' | 'outdated' | 'failed';
  bbox_lonlat?: [number, number, number, number];
  has_placeholders?: boolean;
};

/** Contract §5.1 — GET /sites, GET /sites/{site_id}. */
export async function getSite(): Promise<Awaiting & {site: SiteSummary | null}> {
  try {
    const sites = await api.sites() as SiteSummary[];
    return {status: 'awaiting', reason: 'Site metadata loaded; terrain grids are not part of the site summary response.', site: sites[0] ?? null};
  } catch {
    return {status: 'awaiting', reason: 'No site is connected yet. Add a site or connect the backend API.', site: null};
  }
}

/** Terrain for the active site (part of site detail / GET /scene3d/{query_id}). */
export async function getTerrain(siteId?: string): Promise<Awaiting & {grid: Grid | null}> {
  try {
    if (siteId) await api.site(siteId);
    else await api.sites();
    return {status: 'awaiting', reason: 'Site contract loaded; terrain grids are exposed through scene3d binary files, not the legacy Grid array required by this canvas.', grid: null};
  } catch {
    return {status: 'awaiting', reason: 'No site is connected yet. Add a site or connect the backend API.', grid: null};
  }
}

/** Contract §5.4/§5 #10 — POST /flood/query, GET /flood/{query_id}. Covers
 * both the rapid-query slider and the Physics-run form. */
export async function queryFlood(request: {site_id?: string; severity?: number; params?: Params}): Promise<Awaiting & {result: Result | null}> {
  if (!useMocks && !request.site_id) {
    return {status: 'awaiting', reason: 'A contract site_id is required before a flood query can be submitted.', result: null};
  }
  try {
    const contractRequest = useMocks ? api.examples.floodRequest : {
      site_id: request.site_id!, model: 'delft3d', mode: 'unknown_breach',
      inputs: request.params ? {breach_width_m: {type: 'exact', value: request.params.width}} : {},
    };
    await api.floodQuery(contractRequest);
    return {status: 'awaiting', reason: 'The contract response is available, but its Estimate and layer schema cannot be represented by the legacy raster Result model.', result: null};
  } catch {
    return {status: 'awaiting', reason: 'No emulator or screening run is connected yet.', result: null};
  }
}

/** The prepared scenario library for the active site. No endpoint exists for
 * this in docs/handoff_contract.md §5 yet — ask before wiring this to a
 * real route. */
export async function listScenarios(): Promise<Awaiting & {scenarios: Scenario[]}> {
  return {status: 'awaiting', reason: 'No scenario library exists for this site yet.', scenarios: []};
}

/** Contract §5 #14 / §4.7 — GET /impact/{query_id}. Not yet wired to the
 * impact view (which still computes client-side from assets + result); see
 * docs/progress.md. */
export async function getImpact(queryId?: string): Promise<Awaiting & {assets: Exposure[]}> {
  if (queryId) try { await api.impact(queryId); } catch { /* retain the empty state */ }
  return {status: 'awaiting', reason: 'No exposure inventory is connected yet.', assets: []};
}

/** Contract §5 #15 — GET /compare/{site_id}. Not yet wired to the compare
 * view (which still relies on client-side GeoJSON import); see
 * docs/progress.md. */
export async function getCompare(_model: 'SPH' | 'Delft3D', siteId?: string): Promise<Awaiting & {area: number | null; max: number | null; name: string | null}> {
  if (siteId) try { await api.compare(siteId); } catch { /* retain the empty state */ }
  return {status: 'awaiting', reason: 'No comparison run is connected yet.', area: null, max: null, name: null};
}

/** Contract §5 #19/#20 — GET /gee/{site_id}, POST /gee/{site_id}/refresh. */
export async function getObserved(siteId?: string): Promise<Awaiting & {observed: unknown | null}> {
  if (siteId) try { await api.gee(siteId); } catch { /* retain the empty state */ }
  return {status: 'awaiting', reason: 'No satellite observation is connected yet.', observed: null};
}

/** Contract §6 — GET /styles (contracts/styles.json). Drives map legends and
 * colour classes; see STYLE_GUIDE.md §2.6 for the frontend palette that
 * should seed it. */
export async function getStyles(): Promise<Awaiting & {styles: unknown | null}> {
  try { return {status: 'awaiting', reason: 'Styles loaded from the contract; no display change is applied until map data is available.', styles: await api.styles()}; }
  catch { return {status: 'awaiting', reason: 'Map styles are unavailable.', styles: null}; }
}

/** Contract §5 #18 — GET /export/{query_id}?format=. */
export async function exportUrl(format: string, queryId?: string): Promise<Awaiting & {url: string | null}> {
  if (queryId && (format === 'shp' || format === 'kml' || format === 'geojson' || format === 'pdf')) {
    try { await api.export(queryId, format); } catch { /* retain the empty state */ }
  }
  return {status: 'awaiting', reason: 'No result is available to export yet.', url: null};
}

/** Contract §5.2 — POST /sites (Add a Dam). */
export async function createSite(_input: {name: string; grid: Grid; params: Params}): Promise<Awaiting & {jobId: string | null}> {
  if (useMocks) {
    try { const accepted = await api.createSite(api.examples.siteRequest) as {job_id: string}; return {status: 'awaiting', reason: 'Mock onboarding job accepted; the legacy UI has no contract job-progress state.', jobId: accepted.job_id}; } catch { /* retain the empty state */ }
  }
  return {status: 'awaiting', reason: 'Site onboarding is not connected to the backend API yet.', jobId: null};
}

/** Contract §5.3 — GET /jobs/{job_id}. */
export async function getJob(jobId: string): Promise<Awaiting & {job: unknown | null}> {
  try { const job = await api.job(jobId); return {status: 'awaiting', reason: 'Job contract status loaded.', job}; } catch { /* retain the empty state */ }
  return {status: 'awaiting', reason: 'No job is running.', job: null};
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
