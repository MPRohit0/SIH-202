// Contract response shapes, duplicated from src/data/api.ts (not imported
// from it) so the demo engine has zero runtime dependency on the app's HTTP
// client layer (api.ts pulls in import.meta.env and every contracts/examples/
// *.json file, none of which the engine needs) -- this keeps the engine
// standalone enough to run under plain Node for
// frontend/scripts/dump_preview_fixtures.mjs. These are structurally
// identical to api.ts's types, so values built with them satisfy api.ts's
// types wherever preview/index.ts hands them back (TypeScript structural
// typing) -- if api.ts's shapes change, update both.
export type SiteSummary = {
  site_id: string; name: string;
  status: 'onboarding' | 'demo_mode' | 'ready' | 'outdated' | 'failed';
  status_reason_key?: string | null; bbox_lonlat?: [number, number, number, number];
  has_placeholders?: boolean;
  recheck?: {frequency_days: number; last_checked_at: string | null; next_check_at: string | null};
};
export type Estimate = {
  value: number | null; low: number | null; high: number | null;
  unit: string | null; interval: 'P10-P90' | 'method_range' | 'zone_range' | 'none';
  kind: 'predicted' | 'observed' | 'input'; confidence?: 'HIGH' | 'MODERATE' | 'LOW' | null;
  basis?: string; source?: string;
};
export type FloodQueryRequest = {
  site_id: string; scenario_id?: string; model: 'delft3d' | 'sph'; mode: 'scenario' | 'unknown_breach';
  inputs: Record<string, {type: 'exact'; value: number} | {type: 'slider'; position: number}>;
  options?: {n_samples?: number; seed?: number | null};
};
export type FloodQueryResponse = {
  contract_version: string; query_id: string; site_id: string;
  status: 'partial' | 'complete' | 'failed'; method: 'gp_emulator' | 'empirical_fallback' | 'delft3d_direct' | 'sph_direct';
  mode: 'scenario' | 'unknown_breach';
  resolved_inputs: Record<string, Estimate>;
  summary: {
    inundated_area_m2: Estimate; max_depth_m: Estimate; max_velocity_ms: Estimate;
    peak_discharge_m3s: Estimate; first_arrival: {poi_id: string; name: string; arrival_s: Estimate};
  };
  confidence: Record<'overall' | 'extent' | 'depth' | 'arrival' | 'velocity', {
    level: 'HIGH' | 'MODERATE' | 'LOW'; components: Record<string, string>; reason_key: string | null;
  }>;
  layers: Array<{layer_id: string; label_key?: string; type: string; url: string; bounds_latlng: number[][]; style_id: string; unit: string | null; available: boolean}>;
  vectors: {extent_url: string};
  flags: {outside_trained_range: boolean; demo_mode: boolean; library_outdated: boolean; has_placeholders: boolean};
  placeholder_fields: string[];
  caveats: Array<{id: string; severity: 'info' | 'warning' | 'critical'; text_key: string}>;
  provenance: Record<string, unknown>;
  timing_ms: {median_phase: number; full_phase: number};
};
export type ImpactResponse = {
  contract_version: string; query_id: string; site_id: string;
  population_persons: Estimate;
  assets: {
    buildings: {high: number; possible: number}; roads_m: {high: number; possible: number};
    bridges: {high: number; possible: number}; hospitals: {high: number; possible: number};
    schools: {high: number; possible: number}; cropland_m2: {high: number; possible: number};
    hydropower: Array<{name: string; zone: 'high' | 'possible'; depth_m: Estimate}>;
  };
  loss_inr: Estimate & {by_asset_class?: Record<string, Estimate>; assumptions?: string[]};
  warning_table: Array<{poi_id: string; name: string; kind: string; chainage_m: number; zone: 'high' | 'possible'; p_inundation: number; arrival_s: Estimate; depth_m: Estimate; velocity_ms: Estimate; x_preview_depth_class?: string; x_preview_dv_class?: string; x_preview_dv_m2s?: number}>;
  not_affected_poi_count: number; data_coverage_notes: string[];
  has_placeholders: boolean; placeholder_fields: string[];
  caveats: Array<{id: string; severity: 'info' | 'warning' | 'critical'; text_key: string}>;
  provenance: Record<string, unknown>;
  x_preview_population_by_arrival_band?: Array<{arrival_band_min: string; low_persons: number; high_persons: number}>;
  x_preview_population_by_arrival_band_note?: string;
  x_preview_critical_facilities_note?: string;
};
export type CompareResponse = {
  site_id: string; scenario_id: string;
  sph_vs_delft3d: {available: boolean; domain: string; time_window_s: number; metrics: {iou?: number; f1_0_3?: number; depth_rmse_wet_m?: number; velocity_mae_ms?: number}; probes: Array<{poi_id: string; arrival_delft3d_s: number; arrival_sph_s: number; diff_s: number}>; layers: FloodQueryResponse['layers']; run_ids: string[]};
  emulator_vs_physics: {available: boolean; held_out_run_id: string | null; metrics: {iou?: number; depth_rmse_wet_m?: number; arrival_mae_s?: number}; layers: FloodQueryResponse['layers']};
  gp_vs_linear: {iou_median_gp?: number; iou_median_linear?: number; arrival_mae_s_gp?: number; arrival_mae_s_linear?: number}; when_to_use_key: string;
  caveats: Array<{id: string; severity: 'info' | 'warning' | 'critical'; text_key: string}>;
};
export type GeeLayers = {
  site_id: string; source: 'live' | 'cache' | 'screenshot_fallback'; fetched_at: string;
  lake_area_series: Array<{date: string; area_m2: number; method: 's2_water_index' | 's1_threshold'; cloud_pct: number | null; source?: string | null}>;
  lake_latest: {type: 'FeatureCollection'; features: Array<{type: 'Feature'; geometry: {type: string; coordinates: unknown}; properties: Record<string, unknown>}>};
  rainfall: Array<{date: string; precip_mm: number; dataset: 'chirps' | 'gpm_imerg'}>;
  imagery: Array<{event_id: string; phase: 'pre' | 'post'; date: string; url: string; bounds_latlng: number[][]}>;
  observed_extents: Array<{event_id: string; url: string; method: 'manual_digitized' | 'change_detection'}>;
  recheck: {outdated: boolean; change_pct: number | null; threshold_pct: number};
  caveats?: Array<{id: string; severity: 'info' | 'warning' | 'critical'; text_key: string}>;
};
export type HistoricalValidationResponse = {
  contract_version: string; site_id: string; event_id: string;
  observed: {available?: boolean; extent_url?: string; note?: string} & Record<string, unknown>;
  predicted: Record<string, unknown>;
  metrics: Record<string, unknown>;
  comparison_domain: string;
  caveats: Array<{id: string; severity: 'info' | 'warning' | 'critical'; text_key: string}>;
  provenance: Record<string, unknown>;
  x_preview_event_kind?: 'mass_flow';
  x_preview_framing?: string;
};
export type Scene3DResponse = {
  contract_version: string; query_id: string;
  frame: {crs_epsg: number | null; origin_x_utm_m: number; origin_y_utm_m: number; vertical_exaggeration: number; vertical_exaggeration_applies_to: string; units: string; axis_order: string};
  terrain: {url: string; encoding: string; width: number; height: number; cell_size_x_m: number; cell_size_y_m: number; origin_x_utm_m: number; origin_y_utm_m: number; origin_local_x_m: number; origin_local_y_m: number; transform: number[]; crs_epsg: number | null; min_elev_m: number | null; max_elev_m: number | null; nodata: number; byte_length: number};
  flood_surface: {url: string; encoding: string; nodata: number; basis: string; width: number; height: number; byte_length: number};
  comparison: {nearfield_bounds_local: number[][]; delft3d_surface_url: string | null; delft3d_surface_basis: string | null; sph_surfaces: Array<{t_s: number; url: string}>};
  payload_bytes: number; max_payload_mb: number;
};
