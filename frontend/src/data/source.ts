// Single seam between the UI and real data.
//
// Every function here stands in for a call the backend's REST API
// (docs/handoff_contract.md §5, base http://localhost:8000/api/v1) will
// eventually make. Today there is no backend wired up, so every function
// resolves to an "awaiting" status with empty data — the shapes components
// already render as their normal empty states (<Empty>, "—" via nf(),
// disabled buttons). When the API is live, only this file should need to
// change; components should not start calling fetch() directly.
//
// Two functions in this file (listScenarios, listSavedRuns) have no
// endpoint in the current contract. They are flagged below; ask before
// inventing routes for them.
import type {Grid, Params, Result} from '@/lib/model';
import type {Scenario, Exposure} from '@/lib/sentriq';

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
  return {status: 'awaiting', reason: 'No site is connected yet. Add a site or connect the backend API.', site: null};
}

/** Terrain for the active site (part of site detail / GET /scene3d/{query_id}). */
export async function getTerrain(): Promise<Awaiting & {grid: Grid | null}> {
  return {status: 'awaiting', reason: 'No site is connected yet. Add a site or connect the backend API.', grid: null};
}

/** Contract §5.4/§5 #10 — POST /flood/query, GET /flood/{query_id}. Covers
 * both the rapid-query slider and the Physics-run form. */
export async function queryFlood(_request: {site_id?: string; severity?: number; params?: Params}): Promise<Awaiting & {result: Result | null}> {
  return {status: 'awaiting', reason: 'No emulator or screening run is connected yet.', result: null};
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
export async function getImpact(): Promise<Awaiting & {assets: Exposure[]}> {
  return {status: 'awaiting', reason: 'No exposure inventory is connected yet.', assets: []};
}

/** Contract §5 #15 — GET /compare/{site_id}. Not yet wired to the compare
 * view (which still relies on client-side GeoJSON import); see
 * docs/progress.md. */
export async function getCompare(_model: 'SPH' | 'Delft3D'): Promise<Awaiting & {area: number | null; max: number | null; name: string | null}> {
  return {status: 'awaiting', reason: 'No comparison run is connected yet.', area: null, max: null, name: null};
}

/** Contract §5 #19/#20 — GET /gee/{site_id}, POST /gee/{site_id}/refresh. */
export async function getObserved(): Promise<Awaiting & {observed: unknown | null}> {
  return {status: 'awaiting', reason: 'No satellite observation is connected yet.', observed: null};
}

/** Contract §6 — GET /styles (contracts/styles.json). Drives map legends and
 * colour classes; see STYLE_GUIDE.md §2.6 for the frontend palette that
 * should seed it. */
export async function getStyles(): Promise<Awaiting & {styles: unknown | null}> {
  return {status: 'awaiting', reason: 'contracts/styles.json is not published yet.', styles: null};
}

/** Contract §5 #18 — GET /export/{query_id}?format=. */
export async function exportUrl(_format: string): Promise<Awaiting & {url: string | null}> {
  return {status: 'awaiting', reason: 'No result is available to export yet.', url: null};
}

/** Contract §5.2 — POST /sites (Add a Dam). */
export async function createSite(_input: {name: string; grid: Grid; params: Params}): Promise<Awaiting & {jobId: string | null}> {
  return {status: 'awaiting', reason: 'Site onboarding is not connected to the backend API yet.', jobId: null};
}

/** Contract §5.3 — GET /jobs/{job_id}. */
export async function getJob(_jobId: string): Promise<Awaiting & {job: unknown | null}> {
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
