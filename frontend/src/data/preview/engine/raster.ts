// Live client-side raster rendering for the demo engine
// (design/target-state-preview). Every map layer is painted on an in-memory
// <canvas> from the current profile function and exported as a data: URL, so
// depth/probability/zone/diff maps actually change when the user changes an
// input -- there are no pre-baked PNGs left to serve.
import styles from '../../../../../contracts/styles.json';
import {computeProfile, type EngineInputs} from './physics';
import {getWorld, widthAt, chainageToLonLat, type World} from './world';

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

function makeCanvas(w: number, h: number): {canvas: HTMLCanvasElement; ctx: CanvasRenderingContext2D} {
  const canvas = document.createElement('canvas');
  canvas.width = w; canvas.height = h;
  const ctx = canvas.getContext('2d')!;
  return {canvas, ctx};
}

/** dist-from-centre shape factor in [0,1]: full depth in the channel,
 * tapering to 0 at the bank -- same taper used by the pre-engine generator. */
function bankTaper(distFromCentre: number): number {
  if (distFromCentre < 0.42) return 1;
  if (distFromCentre < 0.5) return Math.max(0, 1 - (distFromCentre - 0.42) / 0.08);
  return 0;
}

export type RasterKind = 'depth' | 'p_inundation' | 'zone' | 'diff';

// --- Map geometry --------------------------------------------------------
// Every demo map layer (flood rasters, the terrain basemap, the pre/post lake
// images) is painted on the same geographic grid, so they line up exactly
// when stacked. The river is a smoothed polyline through the breach and the
// on-river points of interest, in chainage order; each pixel is classified by
// its nearest point on that line (chainage along the river, distance across).

/** Map box width:height in metres -- matches the map panel's shape so the
 * image is not stretched when the panel fills it. */
const MAP_ASPECT = 2.2;
const PX_W = 1100;
const M_PER_DEG_LAT = 110540;

type Field = {
  w: number; h: number; bounds: [[number, number], [number, number]];
  chainage: Float32Array; dist: Float32Array; relief: Float32Array;
};
const fieldCache = new Map<string, Field>();

export function centreline(world: World): {lon: number; lat: number; chainage: number}[] {
  const onRiver = world.pois.filter(p => p.kind === 'village' || p.kind === 'dam' || p.kind === 'bridge')
    .sort((a, b) => a.chainage_m - b.chainage_m);
  const knots = [{lon: world.breach_lon, lat: world.breach_lat, chainage: 0}, ...onRiver.map(p => ({lon: p.lon, lat: p.lat, chainage: p.chainage_m}))];
  if (knots.length < 2) { const [lon, lat] = chainageToLonLat(world, world.length_m); knots.push({lon, lat, chainage: world.length_m}); }
  // Catmull-Rom densify, with a gentle meander so the river is not a set of straight segments.
  const out: {lon: number; lat: number; chainage: number}[] = [];
  for (let i = 0; i < knots.length - 1; i++) {
    const p0 = knots[Math.max(0, i - 1)], p1 = knots[i], p2 = knots[i + 1], p3 = knots[Math.min(knots.length - 1, i + 2)];
    const n = 40;
    for (let k = 0; k < n; k++) {
      const t = k / n, t2 = t * t, t3 = t2 * t;
      const cr = (a: number, b: number, c: number, d: number) => 0.5 * (2 * b + (-a + c) * t + (2 * a - 5 * b + 4 * c - d) * t2 + (-a + 3 * b - 3 * c + d) * t3);
      const dLon = p2.lon - p1.lon, dLat = p2.lat - p1.lat, len = Math.hypot(dLon, dLat) || 1;
      const wiggle = Math.sin(t * Math.PI * 3 + i) * Math.sin(t * Math.PI) * len * 0.06;
      out.push({lon: cr(p0.lon, p1.lon, p2.lon, p3.lon) - dLat / len * wiggle, lat: cr(p0.lat, p1.lat, p2.lat, p3.lat) + dLon / len * wiggle,
        chainage: p1.chainage + t * (p2.chainage - p1.chainage)});
    }
  }
  out.push(knots[knots.length - 1]);
  return out;
}

// Small deterministic value noise for the relief (no Math.random: maps must not flicker between renders).
function hash(x: number, y: number): number { const s = Math.sin(x * 127.1 + y * 311.7) * 43758.5453; return s - Math.floor(s); }
function noise(x: number, y: number): number {
  const xi = Math.floor(x), yi = Math.floor(y), xf = x - xi, yf = y - yi;
  const u = xf * xf * (3 - 2 * xf), v = yf * yf * (3 - 2 * yf);
  const a = hash(xi, yi), b = hash(xi + 1, yi), c = hash(xi, yi + 1), d = hash(xi + 1, yi + 1);
  return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v;
}
function fbm(x: number, y: number): number { let s = 0, amp = 0.5, f = 1; for (let o = 0; o < 5; o++) { s += amp * noise(x * f, y * f); amp *= 0.5; f *= 2; } return s; }

/** The shared map grid for a world. `toChainage` limits the box to the reach
 * from the breach to that chainage (the near-field comparison view). */
function fieldFor(world: World, toChainage?: number): Field {
  const key = `${world.site_id}:${toChainage ?? 'all'}`;
  const hit = fieldCache.get(key);
  if (hit) return hit;
  const line = centreline(world);
  const shown = toChainage === undefined ? line : line.filter(p => p.chainage <= toChainage);
  const lat0 = line[0].lat, mPerDegLon = M_PER_DEG_LAT * Math.cos(lat0 * Math.PI / 180);
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const p of shown.length > 1 ? shown : line.slice(0, 2)) {
    minX = Math.min(minX, p.lon * mPerDegLon); maxX = Math.max(maxX, p.lon * mPerDegLon);
    minY = Math.min(minY, p.lat * M_PER_DEG_LAT); maxY = Math.max(maxY, p.lat * M_PER_DEG_LAT);
  }
  // Pad, then widen the short side so the box has the panel's shape.
  const pad = Math.max(maxX - minX, maxY - minY) * 0.12 + 800;
  let spanX = maxX - minX + 2 * pad, spanY = maxY - minY + 2 * pad;
  if (spanX / spanY < MAP_ASPECT) spanX = spanY * MAP_ASPECT; else spanY = spanX / MAP_ASPECT;
  const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
  const x0 = cx - spanX / 2, y1 = cy + spanY / 2;
  const w = PX_W, h = Math.round(PX_W / MAP_ASPECT), mPerPx = spanX / w;
  const pts = line.map(p => ({x: p.lon * mPerDegLon, y: p.lat * M_PER_DEG_LAT, c: p.chainage}));
  const chainage = new Float32Array(w * h), dist = new Float32Array(w * h), relief = new Float32Array(w * h);
  for (let row = 0; row < h; row++) {
    const y = y1 - (row + 0.5) * mPerPx;
    for (let col = 0; col < w; col++) {
      const x = x0 + (col + 0.5) * mPerPx;
      let best = Infinity, bestC = 0;
      for (let i = 0; i < pts.length - 1; i++) {
        const a = pts[i], b = pts[i + 1], dx = b.x - a.x, dy = b.y - a.y, len2 = dx * dx + dy * dy || 1;
        const t = Math.max(0, Math.min(1, ((x - a.x) * dx + (y - a.y) * dy) / len2));
        const ex = a.x + t * dx - x, ey = a.y + t * dy - y, d2 = ex * ex + ey * ey;
        if (d2 < best) { best = d2; bestC = a.c + t * (b.c - a.c); }
      }
      const i = row * w + col, d = Math.sqrt(best);
      chainage[i] = bestC; dist[i] = d;
      // Valley relief: ridges rise away from the river, rough mountain texture on top.
      const t = Math.min(1, d / 7000); relief[i] = Math.sqrt(t) * 0.75 + fbm(x / 9000, y / 9000) * 0.45 + fbm(x / 2000, y / 2000) * 0.06;
    }
  }
  const bounds: [[number, number], [number, number]] = [[(y1 - spanY) / M_PER_DEG_LAT, x0 / mPerDegLon], [y1 / M_PER_DEG_LAT, (x0 + spanX) / mPerDegLon]];
  const field = {w, h, bounds, chainage, dist, relief};
  fieldCache.set(key, field);
  return field;
}

/** Paints one raster layer for `world` at the given inputs/scenario type and
 * returns its data: URL plus the lat/lon bounds it covers (for a Leaflet-style
 * image overlay). `sample(chainageM, distFrac)` lets callers substitute the
 * ensemble's p_floods or a diff value in place of a plain single-run depth;
 * distFrac is the distance from the river centre as a fraction of the local
 * flooded width (0 = centre, 0.5 = edge). */
export function renderRaster(
  world: World, kind: RasterKind, sample: (chainageM: number, distFrac: number) => number,
  opts: {toChainage?: number} = {},
): {dataUrl: string; bounds_latlng: [[number, number], [number, number]]} {
  // No DOM (e.g. the Node-side fixture dump script, frontend/scripts/
  // dump_preview_fixtures.mjs): skip the canvas paint and return an empty
  // layer URL -- schema-valid (url is just a string), just not a real image.
  // The browser always has document, so this never short-circuits at runtime.
  if (typeof document === 'undefined') return {dataUrl: '', bounds_latlng: [[0, 0], [0, 0]]};
  const f = fieldFor(world, opts.toChainage);
  const {canvas, ctx} = makeCanvas(f.w, f.h);
  const img = ctx.createImageData(f.w, f.h);
  const cache = new Map<number, number>();
  for (let i = 0; i < f.w * f.h; i++) {
    const c = f.chainage[i];
    if (opts.toChainage !== undefined && c > opts.toChainage) continue;
    if (c >= world.length_m) continue;
    const width = widthAt(world, c);
    const distFrac = f.dist[i] / width;
    const taper = bankTaper(distFrac);
    if (taper <= 0) continue;
    const ck = Math.round(c / 25);
    let v = cache.get(ck);
    if (v === undefined) { v = sample(ck * 25, 0); cache.set(ck, v); }
    const raw = v * taper;
    let color: string;
    if (kind === 'p_inundation') color = probColor(raw);
    else if (kind === 'zone') color = raw >= 0.5 ? 'rgba(215,38,61,0.7)' : raw >= 0.1 ? 'rgba(244,162,89,0.55)' : 'rgba(0,0,0,0)';
    else if (kind === 'diff') color = raw <= 0 ? 'rgba(0,0,0,0)' : lerpColor('#fff3b0', '#d7263d', Math.min(1, raw / 0.5));
    else color = depthColor(raw);
    const [r, g, b, a] = parseColor(color);
    img.data[i * 4] = r; img.data[i * 4 + 1] = g; img.data[i * 4 + 2] = b; img.data[i * 4 + 3] = a;
  }
  ctx.putImageData(img, 0, 0);
  return {dataUrl: canvas.toDataURL('image/png'), bounds_latlng: f.bounds};
}

/** Illustrative shaded-relief basemap on the same grid as the flood layers,
 * with the source lake drawn at the breach sized from `lakeAreaM2`. Used for
 * the map background and the pre/post lake images in preview mode. */
export function renderTerrainImage(world: World, lakeAreaM2: number, opts: {toChainage?: number} = {}): {dataUrl: string; bounds_latlng: [[number, number], [number, number]]} {
  if (typeof document === 'undefined') return {dataUrl: '', bounds_latlng: [[0, 0], [0, 0]]};
  const f = fieldFor(world, opts.toChainage);
  const {canvas, ctx} = makeCanvas(f.w, f.h);
  const img = ctx.createImageData(f.w, f.h);
  const [[south, west], [north, east]] = f.bounds;
  const mPerPx = (north - south) * M_PER_DEG_LAT / f.h;
  const lakeR = Math.sqrt(Math.max(0, lakeAreaM2) / Math.PI);
  const bx = (world.breach_lon - west) / (east - west) * f.w, by = (north - world.breach_lat) / (north - south) * f.h;
  for (let row = 0; row < f.h; row++) {
    for (let col = 0; col < f.w; col++) {
      const i = row * f.w + col;
      const z = f.relief[i];
      const zx = f.relief[row * f.w + Math.min(f.w - 1, col + 1)] - z, zy = f.relief[Math.min(f.h - 1, row + 1) * f.w + col] - z;
      const shade = Math.max(0.25, Math.min(1.25, 0.85 + (-zx * 0.7 + zy * 0.7) * 35));
      // Valley floor green, slopes brown-grey, high ridges pale (snow line).
      let r = 46 + z * 60, g = 66 + z * 40, b = 52 + z * 30;
      if (z > 0.95) { const s = Math.min(1, (z - 0.95) * 5); r += (205 - r) * s; g += (212 - g) * s; b += (215 - b) * s; }
      const d = f.dist[i];
      if (d < 60 && f.chainage[i] < world.length_m) { r = 58; g = 92; b = 110; } // the river itself
      const lake = Math.hypot((col - bx) * mPerPx, (row - by) * mPerPx * 1.25) < lakeR;
      if (lake) { r = 40; g = 96; b = 150; }
      img.data[i * 4] = Math.min(255, r * (lake ? 1 : shade)); img.data[i * 4 + 1] = Math.min(255, g * (lake ? 1 : shade)); img.data[i * 4 + 2] = Math.min(255, b * (lake ? 1 : shade)); img.data[i * 4 + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  return {dataUrl: canvas.toDataURL('image/png'), bounds_latlng: f.bounds};
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
