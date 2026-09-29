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
import type {SiteSummary, SiteDetail, SiteCreateAccepted, JobStatus} from '../api';

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
