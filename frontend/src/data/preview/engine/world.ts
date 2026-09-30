// The shared demo world (design/target-state-preview): real place names, real
// approximate coordinates and real chainages for two sites -- Teesta (South
// Lhonak GLOF cascading to Teesta III) and Rishi Ganga (Raunthi Gad
// landslide lake near Tapovan). Only the simulated flood numbers are
// invented; the geography, dam specs and POI list are the same ones already
// used in sites/teesta.yaml / site_detail.*.json.

export type ScenarioType = 'dam_breach' | 'glof' | 'river_blockage' | 'cascade';

export type PoiKind = 'village' | 'dam' | 'bridge' | 'hospital' | 'army_camp';

export type Poi = {
  poi_id: string; name: string; kind: PoiKind; chainage_m: number;
  lon: number; lat: number; population?: number;
};

export type EmulatorInputRange = {
  name: 'water_volume_m3' | 'breach_width_m' | 'failure_time_s';
  label_key: string; unit: string; low: number; high: number; default: number;
  slider: {positions: number[]; mapping: 'linear' | 'log'};
};

export type ReachWidth = {from_chainage_m: number; width_m: number};

export type CascadeDam = {
  dam_id: string; name: string; chainage_m: number;
  dam_height_m: number; trigger_discharge_m3s: number;
};

export type World = {
  site_id: string; name: string; bbox_lonlat: [number, number, number, number];
  breach_lon: number; breach_lat: number;
  /** The site's real UTM zone (CLAUDE.md §"CRS": Teesta EPSG:32645, Rishi
   * Ganga EPSG:32644) -- used for the scene3d frame and the Terrain panel's
   * CRS label instead of a hardcoded/placeholder value. */
  crs_epsg: number;
  /** Total centreline length modelled, in metres from the breach (chainage 0). */
  length_m: number;
  /** Piecewise-linear valley width by reach, narrowest (gorge) near the
   * breach, widening toward the confluence -- read with widthAt(). */
  reaches: ReachWidth[];
  pois: Poi[];
  emulatorInputs: EmulatorInputRange[];
  /** Present only for the cascade-capable site (Teesta): a second dam whose
   * storage can be overtopped by the upstream hydrograph. */
  cascadeDam?: CascadeDam;
  /** River-blockage scenario: the blockage/lake this scenario type fills and
   * then fails (Raunthi Gad on Rishi Ganga). Absent where not applicable. */
  blockage?: {lake_id: string; name: string; fill_rate_m3s: number};
  scenarioTypes: ScenarioType[];
  defaultScenarioType: ScenarioType;
};

const linear = (n: number) => Array.from({length: n}, (_, i) => i);

export const TEESTA: World = {
  site_id: 'teesta',
  name: 'Teesta — South Lhonak GLOF to Teesta III',
  bbox_lonlat: [88.0, 27.5, 89.0, 28.2],
  breach_lon: 88.409, breach_lat: 27.888,
  crs_epsg: 32645,
  length_m: 32000,
  // Gorge for the first ~10 km below South Lhonak, widening past Chungthang
  // toward the Sangkalang/Mangan reach.
  reaches: [
    {from_chainage_m: 0, width_m: 180},
    {from_chainage_m: 5000, width_m: 220},
    {from_chainage_m: 11500, width_m: 320}, // just above the Teesta III confluence
    {from_chainage_m: 13000, width_m: 420},
    {from_chainage_m: 22000, width_m: 520},
    {from_chainage_m: 30000, width_m: 650},
  ],
  pois: [
    {poi_id: 'teesta__poi__lachen', name: 'Lachen', kind: 'village', chainage_m: 2000, lon: 88.556, lat: 27.716, population: 950},
    {poi_id: 'teesta__poi__chungthang', name: 'Chungthang', kind: 'village', chainage_m: 12000, lon: 88.633, lat: 27.605, population: 2400},
    {poi_id: 'teesta__poi__teesta_iii', name: 'Teesta III (Chungthang) dam', kind: 'dam', chainage_m: 12200, lon: 88.635, lat: 27.602, population: 0},
    {poi_id: 'teesta__poi__sangkalang_bridge', name: 'Sangkalang bridge', kind: 'bridge', chainage_m: 24000, lon: 88.556, lat: 27.44, population: 0},
    {poi_id: 'teesta__poi__mangan_district_hospital', name: 'Mangan district hospital', kind: 'hospital', chainage_m: 31000, lon: 88.532, lat: 27.508, population: 0},
  ],
  emulatorInputs: [
    {name: 'water_volume_m3', label_key: 'input_water_volume_m3', unit: 'm3', low: 5_000_000, high: 15_000_000, default: 10_500_000, slider: {positions: linear(11), mapping: 'log'}},
    {name: 'breach_width_m', label_key: 'input_breach_width_m', unit: 'm', low: 60, high: 180, default: 120, slider: {positions: linear(11), mapping: 'linear'}},
    {name: 'failure_time_s', label_key: 'input_failure_time_s', unit: 's', low: 900, high: 10800, default: 3600, slider: {positions: linear(11), mapping: 'log'}},
  ],
  cascadeDam: {
    dam_id: 'teesta__teesta_iii', name: 'Teesta III (Chungthang)', chainage_m: 12200,
    dam_height_m: 60, trigger_discharge_m3s: 1800,
  },
  scenarioTypes: ['glof', 'dam_breach', 'cascade'],
  defaultScenarioType: 'cascade',
};

export const RISHI_GANGA: World = {
  site_id: 'rishi_ganga',
  name: 'Rishi Ganga — Raunthi Gad landslide lake',
  bbox_lonlat: [79.6, 30.4, 79.9, 30.7],
  breach_lon: 79.72, breach_lat: 30.61,
  crs_epsg: 32644,
  length_m: 8000,
  reaches: [
    {from_chainage_m: 0, width_m: 90},
    {from_chainage_m: 2500, width_m: 140},
    {from_chainage_m: 5000, width_m: 210},
    {from_chainage_m: 6500, width_m: 260}, // Tapovan barrage reach
  ],
  pois: [
    {poi_id: 'rishi_ganga__poi__raini', name: 'Raini village', kind: 'village', chainage_m: 3000, lon: 79.75, lat: 30.58, population: 350},
    {poi_id: 'rishi_ganga__poi__rrhpp_tapovan', name: 'Tapovan-Vishnugad RRHPP barrage', kind: 'dam', chainage_m: 6500, lon: 79.79, lat: 30.54, population: 0},
  ],
  emulatorInputs: [
    {name: 'water_volume_m3', label_key: 'input_water_volume_m3', unit: 'm3', low: 500_000, high: 2_000_000, default: 1_000_000, slider: {positions: linear(11), mapping: 'log'}},
    {name: 'breach_width_m', label_key: 'input_breach_width_m', unit: 'm', low: 30, high: 90, default: 55, slider: {positions: linear(11), mapping: 'linear'}},
    {name: 'failure_time_s', label_key: 'input_failure_time_s', unit: 's', low: 600, high: 5400, default: 1800, slider: {positions: linear(11), mapping: 'log'}},
  ],
  blockage: {lake_id: 'rishi_ganga__raunthi_gad_lake', name: 'Raunthi Gad landslide lake', fill_rate_m3s: 45},
  scenarioTypes: ['river_blockage', 'dam_breach'],
  defaultScenarioType: 'river_blockage',
};

export const WORLDS: Record<string, World> = {teesta: TEESTA, rishi_ganga: RISHI_GANGA};

/** Add-a-Dam (deliverable v): registers a new world for a freshly onboarded
 * site, cloning Teesta's reach/POI/input-range shape (renamed, recentred on
 * the picked dam's coordinates) so it is immediately queryable through the
 * same engine -- no separate "new site" code path to build and keep in sync. */
export function registerWorldFromTemplate(siteId: string, name: string, lon: number, lat: number): World {
  const w: World = {
    ...TEESTA,
    site_id: siteId, name, breach_lon: lon, breach_lat: lat,
    bbox_lonlat: [lon - 0.35, lat - 0.35, lon + 0.35, lat + 0.35],
    pois: TEESTA.pois.map(p => ({...p, poi_id: p.poi_id.replace('teesta__', `${siteId}__`)})),
    cascadeDam: undefined, blockage: undefined,
    scenarioTypes: ['dam_breach', 'glof'], defaultScenarioType: 'dam_breach',
  };
  WORLDS[siteId] = w;
  return w;
}

export function getWorld(siteId: string): World {
  const w = WORLDS[siteId];
  if (!w) throw new Error(`No preview demo world for site_id ${JSON.stringify(siteId)}`);
  return w;
}

/** Valley width (m) at a chainage, piecewise-linear between the world's
 * named reach breakpoints -- narrower reaches attenuate flow more slowly
 * (gorge-like), wider reaches attenuate faster (plains-like). */
/** Approximate lon/lat at a chainage: linear interpolation from the breach
 * point toward the farthest POI's real coordinates, extrapolated beyond it if
 * needed. Good enough for a believable map overlay bounding box; this is not
 * a surveyed centreline. */
export function chainageToLonLat(world: World, chainageM: number): [number, number] {
  const last = world.pois[world.pois.length - 1];
  const t = last.chainage_m > 0 ? chainageM / last.chainage_m : 0;
  const lon = world.breach_lon + t * (last.lon - world.breach_lon);
  const lat = world.breach_lat + t * (last.lat - world.breach_lat);
  return [lon, lat];
}

export function widthAt(world: World, chainageM: number): number {
  const reaches = world.reaches;
  if (chainageM <= reaches[0].from_chainage_m) return reaches[0].width_m;
  for (let i = 0; i < reaches.length - 1; i++) {
    const a = reaches[i], b = reaches[i + 1];
    if (chainageM >= a.from_chainage_m && chainageM <= b.from_chainage_m) {
      const t = (chainageM - a.from_chainage_m) / (b.from_chainage_m - a.from_chainage_m);
      return a.width_m + t * (b.width_m - a.width_m);
    }
  }
  return reaches[reaches.length - 1].width_m;
}
