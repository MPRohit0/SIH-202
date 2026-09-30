// Live near-field 3D scene generation (design/target-state-preview, screen 4
// / SPH lab). Builds a small terrain + flood-surface grid from the engine's
// own profile function and packs it exactly like the real contract expects
// (float32 little-endian row-major binary), as a data: URL so no server file
// is needed -- getScene3dArrays() fetches it the same way it would a real
// file.
import type {Scene3DResponse} from './types';
import type {World} from './world';
import {widthAt} from './world';
import {computeProfile, type EngineInputs} from './physics';

const NF_WIDTH = 80, NF_HEIGHT = 60, CELL_M = 15;

function float32ToDataUrl(values: Float32Array): string {
  const bytes = new Uint8Array(values.buffer);
  let binary = '';
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return `data:application/octet-stream;base64,${btoa(binary)}`;
}

/** Renders the near-field terrain (a gorge cross-section, bed dropping with
 * chainage) and the flood surface (terrain + the engine's own depth profile)
 * for the first NF_HEIGHT*CELL_M metres below the breach. */
export function renderScene3d(world: World, scenarioType: string, inputs: EngineInputs, queryId: string): Scene3DResponse {
  const terrain = new Float32Array(NF_WIDTH * NF_HEIGHT);
  const flood = new Float32Array(NF_WIDTH * NF_HEIGHT);
  const bedTopElev = 1926, bedBottomElev = 1750;
  // Gorge below the breach: a gently meandering channel with steep, rough
  // valley walls. Water is only drawn where the engine's depth is > 5 cm;
  // everywhere else the flood surface is nodata so the terrain shows through.
  const rough = (x: number, y: number) => Math.sin(x * 0.37 + y * 0.11) * Math.cos(y * 0.23 - x * 0.07) + 0.5 * Math.sin(x * 0.9 + y * 0.6);
  let maxElev = -Infinity;
  for (let row = 0; row < NF_HEIGHT; row++) {
    const chainageM = row * CELL_M;
    const bedElevAtChainage = bedTopElev - (bedTopElev - bedBottomElev) * (row / (NF_HEIGHT - 1));
    const halfWidthCells = Math.min(NF_WIDTH / 2 - 8, (widthAt(world, chainageM) / CELL_M) / 2);
    const centre = NF_WIDTH / 2 + Math.sin(row / 11) * 7;
    const pt = computeProfile(world, inputs, scenarioType, chainageM);
    for (let col = 0; col < NF_WIDTH; col++) {
      const distFromCentre = Math.abs(col - centre);
      const beyond = Math.max(0, distFromCentre - halfWidthCells);
      const bed = bedElevAtChainage + Math.pow(beyond, 1.35) * 5 + (beyond > 0 ? rough(col, row) * 6 : 0);
      const idx = row * NF_WIDTH + col;
      terrain[idx] = bed;
      maxElev = Math.max(maxElev, bed);
      const localDepth = distFromCentre <= halfWidthCells ? pt.depth_m * (1 - 0.35 * (distFromCentre / Math.max(halfWidthCells, 1)) ** 2) : 0;
      flood[idx] = localDepth > 0.05 ? bed + localDepth : -9999;
    }
  }
  const byteLength = terrain.byteLength;
  return {
    contract_version: '0.3.0', query_id: queryId,
    frame: {crs_epsg: 32645, origin_x_utm_m: 640000, origin_y_utm_m: 3079000, vertical_exaggeration: 1.5, vertical_exaggeration_applies_to: 'z_axis', units: 'm', axis_order: 'east,north,up'},
    terrain: {
      url: float32ToDataUrl(terrain), encoding: 'float32_le_row_major', width: NF_WIDTH, height: NF_HEIGHT,
      cell_size_x_m: CELL_M, cell_size_y_m: CELL_M, origin_x_utm_m: 640000, origin_y_utm_m: 3079000,
      origin_local_x_m: 0, origin_local_y_m: 0, transform: [CELL_M, 0, 640000, 0, -CELL_M, 3079000],
      crs_epsg: 32645, min_elev_m: bedBottomElev, max_elev_m: maxElev, nodata: -9999, byte_length: byteLength,
    },
    flood_surface: {url: float32ToDataUrl(flood), encoding: 'float32_le_row_major', nodata: -9999, basis: 'terrain + engine depth profile', width: NF_WIDTH, height: NF_HEIGHT, byte_length: byteLength},
    comparison: {nearfield_bounds_local: [[0, 0], [NF_WIDTH * CELL_M, NF_HEIGHT * CELL_M]], delft3d_surface_url: null, delft3d_surface_basis: null, sph_surfaces: []},
    payload_bytes: byteLength * 2, max_payload_mb: 20,
  };
}
