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
import type {SiteSummary, SiteDetail} from '../api';

const siteDetails: Record<string, SiteDetail> = {
  teesta: siteDetailTeesta as unknown as SiteDetail,
  rishi_ganga: siteDetailRishiGanga as unknown as SiteDetail,
  demo_valley: siteDetailDemoValley as unknown as SiteDetail,
  synth_engdam: siteDetailSynthEngdam as unknown as SiteDetail,
};

/** Every fixture file this router can serve, keyed exactly as manifest.json
 * lists them. Used by dev-time assertions; not required at runtime. */
export const fixtureManifest = manifest;

export async function listSites(): Promise<SiteSummary[]> {
  return structuredClone(siteList) as unknown as SiteSummary[];
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
