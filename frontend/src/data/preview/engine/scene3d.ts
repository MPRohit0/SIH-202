// Live near-field 3D scene generation (design/target-state-preview, screen 4
// / SPH lab, and the Compare page's Card A/B 3D tabs). Builds a small
// terrain + flood-surface grid and packs it exactly like the real contract
// expects (float32 little-endian row-major binary), as a data: URL so no
// server file is needed -- getScene3dArrays() fetches it the same way it
// would a real file.
import type {Scene3DResponse} from './types';
import type {World} from './world';
import {widthAt} from './world';
import {computeProfile, type EngineInputs} from './physics';

const NF_WIDTH = 80, NF_HEIGHT = 60, CELL_M = 15;

export function float32ToDataUrl(values: Float32Array): string {
  const bytes = new Uint8Array(values.buffer);
  let binary = '';
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return `data:application/octet-stream;base64,${btoa(binary)}`;
}

export type GorgeTerrain = {nx: number; ny: number; cellM: number; bed: Float32Array; minElevM: number; maxElevM: number};

/** Shared near-field "gorge" terrain: a V-shaped valley cross-section whose
 * bed drops linearly with chainage (row) and whose walls rise beyond the
 * local channel width (from world's reach widths) -- used by both the SPH
 * educational lab's 3D scene (renderScene3d, below) and the Compare page's
 * synthetic solver grids (engine/compare.ts), so both read the exact same
 * shape instead of two hand-maintained copies. */
export function buildGorgeTerrain(world: World, nx: number, ny: number, cellM: number): GorgeTerrain {
  const bedTopElev = 1926, bedBottomElev = 1750;
  const bed = new Float32Array(nx * ny);
  for (let row = 0; row < ny; row++) {
    const chainageM = row * cellM;
    const bedElevAtChainage = bedTopElev - (bedTopElev - bedBottomElev) * (row / (ny - 1));
    const halfWidthCells = Math.min(nx / 2 - 2, (widthAt(world, chainageM) / cellM) / 2);
    for (let col = 0; col < nx; col++) {
      const distFromCentre = Math.abs(col - nx / 2);
      const bankRise = Math.max(0, distFromCentre - halfWidthCells) * 1.4; // valley walls rise beyond the channel
      bed[row * nx + col] = bedElevAtChainage + bankRise;
    }
  }
  return {nx, ny, cellM, bed, minElevM: bedBottomElev, maxElevM: bedTopElev};
}

/** Packs a terrain + flood-surface pair (already-computed bed/water-surface
 * elevation grids, same nx*ny shape) into a contract-shaped Scene3DResponse. */
export function packScene3d(
  nx: number, ny: number, cellM: number, bed: Float32Array, floodSurface: Float32Array,
  minElevM: number, maxElevM: number, queryId: string, floodBasis = 'terrain + synthetic solver depth grid',
  crsEpsg = 32645,
): Scene3DResponse {
  const byteLength = bed.byteLength;
  return {
    contract_version: '0.3.0', query_id: queryId,
    frame: {crs_epsg: crsEpsg, origin_x_utm_m: 640000, origin_y_utm_m: 3079000, vertical_exaggeration: 1.5, vertical_exaggeration_applies_to: 'z_axis', units: 'm', axis_order: 'east,north,up'},
    terrain: {
      url: float32ToDataUrl(bed), encoding: 'float32_le_row_major', width: nx, height: ny,
      cell_size_x_m: cellM, cell_size_y_m: cellM, origin_x_utm_m: 640000, origin_y_utm_m: 3079000,
      origin_local_x_m: 0, origin_local_y_m: 0, transform: [cellM, 0, 640000, 0, -cellM, 3079000],
      crs_epsg: crsEpsg, min_elev_m: minElevM, max_elev_m: maxElevM, nodata: -9999, byte_length: byteLength,
    },
    flood_surface: {url: float32ToDataUrl(floodSurface), encoding: 'float32_le_row_major', nodata: -9999, basis: floodBasis, width: nx, height: ny, byte_length: byteLength},
    comparison: {nearfield_bounds_local: [[0, 0], [nx * cellM, ny * cellM]], delft3d_surface_url: null, delft3d_surface_basis: null, sph_surfaces: []},
    payload_bytes: byteLength * 2, max_payload_mb: 20,
  };
}

/** Renders the near-field terrain and the flood surface (terrain + the
 * engine's own depth profile) for the first NF_HEIGHT*CELL_M metres below
 * the breach -- unchanged behaviour, now built from the shared helpers. */
export function renderScene3d(world: World, scenarioType: string, inputs: EngineInputs, queryId: string): Scene3DResponse {
  const {nx, ny, bed, minElevM, maxElevM} = buildGorgeTerrain(world, NF_WIDTH, NF_HEIGHT, CELL_M);
  const flood = new Float32Array(nx * ny);
  for (let row = 0; row < ny; row++) {
    const chainageM = row * CELL_M;
    const halfWidthCells = Math.min(nx / 2 - 2, (widthAt(world, chainageM) / CELL_M) / 2);
    const pt = computeProfile(world, inputs, scenarioType, chainageM);
    for (let col = 0; col < nx; col++) {
      const distFromCentre = Math.abs(col - nx / 2);
      const idx = row * nx + col;
      const localDepth = distFromCentre <= halfWidthCells ? pt.depth_m : 0;
      flood[idx] = bed[idx] + localDepth;
    }
  }
  return packScene3d(nx, ny, CELL_M, bed, flood, minElevM, maxElevM, queryId, 'terrain + engine depth profile', world.crs_epsg);
}
