// Live client-side raster rendering for the demo engine
// (design/target-state-preview). Every map layer is painted on an in-memory
// <canvas> from the current profile function and exported as a data: URL, so
// depth/probability/zone/diff maps actually change when the user changes an
// input -- there are no pre-baked PNGs left to serve.
import styles from '../../../../../contracts/styles.json';
import {computeProfile, type EngineInputs} from './physics';
import {getWorld, widthAt, chainageToLonLat, type World} from './world';

// Higher resolution than the original 90x220 so the depth-class colour steps
// don't turn into visibly blocky bands once the CSS layer stretches this
// raster across a wide map panel (docs/progress.md preview 2D map fix).
const W = 200, H = 460;

function lerpColor(a: string, b: string, t: number): string {
  const pa = hexToRgb(a), pb = hexToRgb(b);
  const r = Math.round(pa[0] + (pb[0] - pa[0]) * t);
  const g = Math.round(pa[1] + (pb[1] - pa[1]) * t);
  const bl = Math.round(pa[2] + (pb[2] - pa[2]) * t);
  return `rgb(${r},${g},${bl})`;
}
function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.replace('#', ''), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function depthColor(depthM: number): string {
  const breaks = styles.depth_p50.breaks_m as number[];
  const colors = styles.depth_p50.colors as string[];
  if (depthM < 0.1) return 'rgba(0,0,0,0)';
  for (let i = 0; i < breaks.length; i++) {
    if (depthM < breaks[i]) {
      const lo = i === 0 ? 0.1 : breaks[i - 1];
      const t = (depthM - lo) / (breaks[i] - lo);
      return lerpColor(colors[i], colors[i + 1], Math.max(0, Math.min(1, t)));
    }
  }
  return colors[colors.length - 1];
}

/** contracts/styles.json depth_diff: diverging blue-white-red, range_m [-2, 2]
 * (SPH minus FM, or predicted minus true). Values outside the range clamp. */
function diffColor(v: number): string {
  const [lo, hi] = styles.depth_diff.range_m as [number, number];
  const colors = styles.depth_diff.colors as string[]; // [negative, mid, positive]
  const t = Math.max(0, Math.min(1, (v - lo) / (hi - lo)));
  return t < 0.5 ? lerpColor(colors[0], colors[1], t / 0.5) : lerpColor(colors[1], colors[2], (t - 0.5) / 0.5);
}

function probColor(p: number): string {
  const stops = styles.p_inundation.stops as [number, string][];
  if (p < stops[0][0]) return 'rgba(0,0,0,0)';
  for (let i = 0; i < stops.length - 1; i++) {
    if (p <= stops[i + 1][0]) {
      const t = (p - stops[i][0]) / (stops[i + 1][0] - stops[i][0]);
      return lerpColor(stops[i][1], stops[i + 1][1], Math.max(0, Math.min(1, t)));
    }
  }
  return stops[stops.length - 1][1];
}

function makeCanvas(): {canvas: HTMLCanvasElement; ctx: CanvasRenderingContext2D} {
  const canvas = document.createElement('canvas');
  canvas.width = W; canvas.height = H;
  const ctx = canvas.getContext('2d')!;
  return {canvas, ctx};
}

/** dist-from-centre shape factor in [0,1]: full depth in the channel,
 * tapering to 0 at the bank. `halfWidthFrac` is this row's actual channel
 * half-width as a fraction of the raster's across-channel span (derived from
 * widthAt(), same per-chainage width the gorge terrain uses in scene3d.ts's
 * buildGorgeTerrain), so the painted channel narrows through the gorge and
 * widens downstream instead of always covering a fixed fraction of the
 * image -- without this the raster looked like a flat, uniform band with no
 * valley shape (docs/progress.md preview 2D map fix). */
function bankTaper(distFromCentre: number, halfWidthFrac: number): number {
  const plateau = halfWidthFrac * 0.82;
  if (distFromCentre < plateau) return 1;
  if (distFromCentre < halfWidthFrac) return Math.max(0, 1 - (distFromCentre - plateau) / Math.max(halfWidthFrac - plateau, 1e-6));
  return 0;
}

export type RasterKind = 'depth' | 'p_inundation' | 'zone' | 'diff';

function boundsFor(world: World): [[number, number], [number, number]] {
  const [lonA, latA] = chainageToLonLat(world, 0);
  const [lonB, latB] = chainageToLonLat(world, world.length_m);
  const maxW = Math.max(...world.reaches.map(r => r.width_m));
  const padDeg = maxW / 2 / 111320;
  return [
    [Math.min(latA, latB) - padDeg, Math.min(lonA, lonB) - padDeg],
    [Math.max(latA, latB) + padDeg, Math.max(lonA, lonB) + padDeg],
  ];
}

/** Paints one raster layer for `world` at the given inputs/scenario type and
 * returns its data: URL plus the lat/lon bounds it covers (for a Leaflet-style
 * image overlay). `sample(chainageM)` lets callers substitute the ensemble's
 * p_floods or a diff value in place of a plain single-run depth. */
export function renderRaster(
  world: World, kind: RasterKind, sample: (chainageM: number, distFrac: number) => number,
): {dataUrl: string; bounds_latlng: [[number, number], [number, number]]} {
  const bounds = boundsFor(world);
  // No DOM (e.g. the Node-side fixture dump script, frontend/scripts/
  // dump_preview_fixtures.mjs): skip the canvas paint and return an empty
  // layer URL -- schema-valid (url is just a string), just not a real image.
  // The browser always has document, so this never short-circuits at runtime.
  if (typeof document === 'undefined') return {dataUrl: '', bounds_latlng: bounds};
  const {canvas, ctx} = makeCanvas();
  const img = ctx.createImageData(W, H);
  const maxWidthM = Math.max(...world.reaches.map(r => r.width_m));
  for (let row = 0; row < H; row++) {
    const chainageM = (row / (H - 1)) * world.length_m;
    // This row's channel half-width as a fraction of the raster's across-channel
    // span, so the painted channel actually narrows/widens with chainage like
    // widthAt() says it should (see bankTaper's doc comment).
    const halfWidthFrac = Math.min(0.49, (widthAt(world, chainageM) / maxWidthM) * 0.49);
    for (let col = 0; col < W; col++) {
      const across = col / (W - 1) - 0.5;
      const dist = Math.abs(across);
      const taper = bankTaper(dist, halfWidthFrac);
      const raw = sample(chainageM, dist) * taper;
      let color: string;
      if (kind === 'p_inundation') color = probColor(raw);
      else if (kind === 'zone') color = raw >= 0.5 ? 'rgba(215,38,61,0.7)' : raw >= 0.1 ? 'rgba(244,162,89,0.55)' : 'rgba(0,0,0,0)';
      else if (kind === 'diff') color = raw <= 0 ? 'rgba(0,0,0,0)' : lerpColor('#fff3b0', '#d7263d', Math.min(1, raw / 0.5));
      else color = depthColor(raw);
      const idxPx = (row * W + col) * 4;
      const [r, g, b, a] = parseColor(color);
      img.data[idxPx] = r; img.data[idxPx + 1] = g; img.data[idxPx + 2] = b; img.data[idxPx + 3] = a;
    }
  }
  ctx.putImageData(img, 0, 0);
  const dataUrl = canvas.toDataURL('image/png');
  return {dataUrl, bounds_latlng: bounds};
}

function parseColor(color: string): [number, number, number, number] {
  if (color.startsWith('rgba')) {
    const [r, g, b, a] = color.replace(/[rgba() ]/g, '').split(',').map(Number);
    return [r, g, b, Math.round((a ?? 1) * 255)];
  }
  if (color.startsWith('rgb')) {
    const [r, g, b] = color.replace(/[rgb() ]/g, '').split(',').map(Number);
    return [r, g, b, 255];
  }
  const [r, g, b] = hexToRgb(color);
  return [r, g, b, 255];
}

/** Depth raster for a single deterministic profile run (scenario mode). */
export function renderDepthRaster(world: World, scenarioType: string, inputs: EngineInputs) {
  return renderRaster(world, 'depth', chainageM => computeProfile(world, inputs, scenarioType, chainageM).depth_m);
}

export function renderRasterForSite(siteId: string, kind: RasterKind, sample: (chainageM: number, distFrac: number) => number) {
  return renderRaster(getWorld(siteId), kind, sample);
}

/** Paints an already-computed per-cell grid (row-major, nx*ny) with no
 * chainage/world lookup of its own -- used by the Compare page's synthetic
 * SPH/FM/prediction grids (engine/compare.ts). Returns '' with no DOM
 * (the Node-side fixture dump script), same convention as renderRaster. */
export function renderGrid(values: Float32Array, nx: number, ny: number, styleId: 'depth_p50' | 'depth_diff'): string {
  if (typeof document === 'undefined') return '';
  const {canvas, ctx} = makeCanvas();
  canvas.width = nx; canvas.height = ny;
  const img = ctx.createImageData(nx, ny);
  for (let row = 0; row < ny; row++) {
    for (let col = 0; col < nx; col++) {
      const v = values[row * nx + col];
      const color = styleId === 'depth_diff' ? diffColor(v) : depthColor(v);
      const idx = (row * nx + col) * 4;
      const [r, g, b, a] = parseColor(color);
      img.data[idx] = r; img.data[idx + 1] = g; img.data[idx + 2] = b; img.data[idx + 3] = a;
    }
  }
  ctx.putImageData(img, 0, 0);
  return canvas.toDataURL('image/png');
}
