/// <reference types="vite/client" />

import breachParams from '../../../contracts/examples/breach_params.example.json';
import compare from '../../../contracts/examples/compare.example.json';
import errorExample from '../../../contracts/examples/error.example.json';
import extent from '../../../contracts/examples/extent_geojson.example.json';
import floodRequest from '../../../contracts/examples/flood_query_request.example.json';
import floodResponse from '../../../contracts/examples/flood_query_response.example.json';
import geeLayers from '../../../contracts/examples/gee_layers.example.json';
import geojson from '../../../contracts/examples/geojson_feature_collection.example.json';
import health from '../../../contracts/examples/health.example.json';
import historicalValidation from '../../../contracts/examples/historical_validation.example.json';
import impact from '../../../contracts/examples/impact.example.json';
import jobAccepted from '../../../contracts/examples/job_accepted.example.json';
import jobStatus from '../../../contracts/examples/job_status.example.json';
import scenarioDesign from '../../../contracts/examples/scenario_design.example.json';
import scene3d from '../../../contracts/examples/scene3d.example.json';
import siteAccepted from '../../../contracts/examples/site_create_accepted.example.json';
import siteDetail from '../../../contracts/examples/site_detail.example.json';
import siteList from '../../../contracts/examples/site_list.example.json';
import siteRequest from '../../../contracts/examples/site_create_request.example.json';
import siteSummary from '../../../contracts/examples/site_summary.example.json';
import styles from '../../../contracts/styles.json';
import timeline from '../../../contracts/examples/timeline.example.json';
import validation from '../../../contracts/examples/validation.example.json';

const baseUrl = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1').replace(/\/$/, '');
export const useMocks = import.meta.env.VITE_USE_MOCKS === 'true';

const fixtures: Record<string, unknown> = {
  health, styles, sites: siteList, site: siteDetail, siteSummary, siteRequest,
  siteAccepted, jobAccepted, jobStatus, floodRequest, floodResponse, impact,
  compare, validation, historicalValidation, geeLayers, scene3d, timeline,
  extent, geojson, breachParams, scenarioDesign, error: errorExample,
};

export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly payload?: unknown) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(path: string, options: RequestInit = {}, fixture?: keyof typeof fixtures): Promise<T> {
  if (useMocks && fixture) return structuredClone(fixtures[fixture]) as T;
  const response = await fetch(`${baseUrl}${path}`, {
    ...options,
    headers: {'Content-Type': 'application/json', ...options.headers},
  });
  const payload: unknown = response.status === 204 ? undefined : await response.json().catch(() => undefined);
  if (!response.ok) {
    const message = (payload as {error?: {message?: string}} | undefined)?.error?.message;
    throw new ApiError(message || `API request failed (${response.status})`, response.status, payload);
  }
  return payload as T;
}

const json = (body: unknown): RequestInit => ({method: 'POST', body: JSON.stringify(body)});

export const api = {
  health: () => request('/health', {}, 'health'),
  styles: () => request('/styles', {}, 'styles'),
  sites: () => request('/sites', {}, 'sites'),
  site: (siteId: string) => request(`/sites/${encodeURIComponent(siteId)}`, {}, 'site'),
  createSite: (body: unknown) => request('/sites', json(useMocks ? siteRequest : body), 'siteAccepted'),
  job: (jobId: string) => request(`/jobs/${encodeURIComponent(jobId)}`, {}, 'jobStatus'),
  recheck: (siteId: string, body: unknown) => request(`/sites/${encodeURIComponent(siteId)}/recheck`, {method: 'PUT', body: JSON.stringify(body)}, 'siteSummary'),
  rerun: (siteId: string) => request(`/sites/${encodeURIComponent(siteId)}/rerun`, {method: 'POST'}, 'jobAccepted'),
  floodQuery: (body: unknown) => request('/flood/query', json(useMocks ? floodRequest : body), 'floodResponse'),
  flood: (queryId: string) => request(`/flood/${encodeURIComponent(queryId)}`, {}, 'floodResponse'),
  timeline: (queryId: string, intervalS = 300) => request(`/flood/${encodeURIComponent(queryId)}/timeline?interval_s=${intervalS}`, {}, 'timeline'),
  extent: (queryId: string) => request(`/flood/${encodeURIComponent(queryId)}/extent.geojson`, {}, 'extent'),
  impact: (queryId: string) => request(`/impact/${encodeURIComponent(queryId)}`, {}, 'impact'),
  compare: (siteId: string, scenarioId?: string) => request(`/compare/${encodeURIComponent(siteId)}${scenarioId ? `?scenario_id=${encodeURIComponent(scenarioId)}` : ''}`, {}, 'compare'),
  validation: (siteId: string) => request(`/validation/${encodeURIComponent(siteId)}`, {}, 'validation'),
  historicalValidation: (siteId: string, eventId: string) => request(`/validation/${encodeURIComponent(siteId)}?event=${encodeURIComponent(eventId)}`, {}, 'historicalValidation'),
  export: (queryId: string, format: 'shp' | 'kml' | 'geojson' | 'pdf') => fetch(`${baseUrl}/export/${encodeURIComponent(queryId)}?format=${format}`),
  gee: (siteId: string) => request(`/gee/${encodeURIComponent(siteId)}`, {}, 'geeLayers'),
  refreshGee: (siteId: string) => request(`/gee/${encodeURIComponent(siteId)}/refresh`, {method: 'POST'}, 'geeLayers'),
  scene3d: (queryId: string, verticalExaggeration = 1.5) => request(`/scene3d/${encodeURIComponent(queryId)}?vertical_exaggeration=${verticalExaggeration}`, {}, 'scene3d'),
  file: (path: string) => {
    const relativePath = path.replace(/^\/api\/v1\/?/, '').replace(/^\/+/, '');
    return fetch(`${baseUrl}/${relativePath}`);
  },
  // Contract example fixture access for contract data with no GET route.
  examples: {scenarioDesign, siteRequest, breachParams, geojson, floodRequest},
};

export type Api = typeof api;
