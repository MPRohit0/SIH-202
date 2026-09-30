// Real Teesta assets (design/target-state-preview). The rest of the demo
// engine paints a synthetic "gorge" channel for every site (raster.ts,
// scene3d.ts's buildGorgeTerrain) so the preview works fully offline with no
// real DEM/solver output required. Teesta is the one site with a real,
// registered D-Flow FM run already on disk (teesta_2023_mvp__delft3d,
// docs/decisions.md), so its scenario-mode depth raster and 3D terrain use a
// static snapshot of that real run instead of the synthetic model -- the
// same real flood shape and mountain terrain main's live-backend build shows,
// captured once (frontend/scripts/gen_real_teesta_preview_assets.py) and
// checked in under frontend/public/preview/teesta_real_*. The engine still
// computes the numeric summary/KPI values and the unknown_breach probability
// raster synthetically; only this one scenario-mode depth/terrain pair is
// swapped for real data.
export const REAL_TEESTA_DEPTH_RASTER = {
  url: '/preview/teesta_real_depth_p50.png',
  bounds_latlng: [[27.44414761229194, 88.14428925703383], [27.95590852711294, 88.70844504794988]] as [[number, number], [number, number]],
};

export type RealScene3DMeta = {
  contract_version: string; source_query_id: string;
  frame: {crs_epsg: number; origin_x_utm_m: number; origin_y_utm_m: number; vertical_exaggeration: number; vertical_exaggeration_applies_to: string; units: string; axis_order: string};
  terrain: {url: string; encoding: string; width: number; height: number; cell_size_x_m: number; cell_size_y_m: number; origin_x_utm_m: number; origin_y_utm_m: number; origin_local_x_m: number; origin_local_y_m: number; transform: number[]; crs_epsg: number; min_elev_m: number; max_elev_m: number; nodata: number; byte_length: number};
  flood_surface: {url: string; encoding: string; nodata: number; basis: string; width: number; height: number; byte_length: number};
};

let cached: Promise<RealScene3DMeta> | null = null;
export function fetchRealTeestaScene3dMeta(): Promise<RealScene3DMeta> {
  if (!cached) cached = fetch('/preview/teesta_real_scene3d.json').then(res => res.json());
  return cached;
}

// Real GEE monitoring assets (screen 7): a static snapshot of the real M7 GEE
// cache already on disk for Teesta (data/teesta/gee/ -- the same cache main's
// live backend reads), captured once
// (frontend/scripts/gen_real_teesta_gee_preview_assets.py). Without this the
// preview engine's GEE screen painted a single dry Point (no lake outline),
// two empty imagery URLs and a 5-point synthetic area series instead of the
// real lake polygon, real satellite thumbnails and the real ~3-year monthly
// series main shows.
export type RealGeeSeries = {
  source_cache: string; fetched_at: string;
  lake_area_series: Array<{date: string; area_m2: number | null; method: string | null; cloud_pct: number | null; source: string | null}>;
  rainfall: Array<{date: string; precip_mm: number | null; dataset: string}>;
  imagery: Array<{phase: string; date: string; url: string; bounds_latlng: number[][]}>;
};

let cachedGee: Promise<RealGeeSeries> | null = null;
export function fetchRealTeestaGeeSeries(): Promise<RealGeeSeries> {
  if (!cachedGee) cachedGee = fetch('/preview/teesta_real_gee_series.json').then(res => res.json());
  return cachedGee;
}

export type RealLakeLatest = {type: 'FeatureCollection'; features: Array<{type: 'Feature'; geometry: {type: string; coordinates: unknown}; properties: Record<string, unknown>}>};
let cachedLakeLatest: Promise<RealLakeLatest> | null = null;
export function fetchRealTeestaLakeLatest(): Promise<RealLakeLatest> {
  if (!cachedLakeLatest) cachedLakeLatest = fetch('/preview/teesta_real_lake_latest.geojson').then(res => res.json());
  return cachedLakeLatest;
}
