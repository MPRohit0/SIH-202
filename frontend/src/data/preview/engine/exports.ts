// Preview-mode exports (design/target-state-preview): the flood extent and the
// downstream warning points for a demo query as GeoJSON, KML, a zipped
// Shapefile and a one-page PDF report -- built in the browser from the same
// engine state the screens show, in EPSG:4326 (lon, lat).
import * as shpwrite from '@mapbox/shp-write';
import {computeProfile, type EngineInputs} from './physics';
import {centreline} from './raster';
import {getWorld, widthAt, type World} from './world';

type Feature = {type: 'Feature'; geometry: {type: string; coordinates: unknown}; properties: Record<string, string | number>};

function extentPolygons(world: World, inputs: EngineInputs, scenario: string): number[][][][] {
  const line = centreline(world);
  const mLat = 110540, mLon = mLat * Math.cos(line[0].lat * Math.PI / 180);
  const runs: {l: number[]; r: number[]}[][] = [];
  let cur: {l: number[]; r: number[]}[] = [];
  for (let i = 0; i < line.length; i++) {
    const p = line[i], q = line[Math.min(line.length - 1, i + 1)], o = line[Math.max(0, i - 1)];
    const wet = p.chainage < world.length_m && computeProfile(world, inputs, scenario, p.chainage).depth_m >= 0.3;
    if (!wet) { if (cur.length > 1) runs.push(cur); cur = []; continue; }
    const dx = (q.lon - o.lon) * mLon, dy = (q.lat - o.lat) * mLat, len = Math.hypot(dx, dy) || 1;
    const half = widthAt(world, p.chainage) * 0.46, nx = -dy / len * half, ny = dx / len * half;
    cur.push({l: [p.lon + nx / mLon, p.lat + ny / mLat], r: [p.lon - nx / mLon, p.lat - ny / mLat]});
  }
  if (cur.length > 1) runs.push(cur);
  return runs.map(run => { const ring = [...run.map(s => s.l), ...run.reverse().map(s => s.r)]; ring.push(ring[0]); return [ring]; });
}

export function exportCollection(siteId: string, queryId: string, inputs: EngineInputs, scenario: string) {
  const world = getWorld(siteId);
  const polys = extentPolygons(world, inputs, scenario);
  const features: Feature[] = polys.map((poly, i) => ({type: 'Feature', geometry: {type: 'Polygon', coordinates: poly},
    properties: {layer: 'flood_extent', query_id: queryId, part: i + 1, threshold: 'depth > 0.3 m'}}));
  for (const p of world.pois) {
    const pt = computeProfile(world, inputs, scenario, p.chainage_m);
    features.push({type: 'Feature', geometry: {type: 'Point', coordinates: [p.lon, p.lat]}, properties: {
      layer: 'warning_point', name: p.name, kind: p.kind, depth_m: Math.round(pt.depth_m * 100) / 100,
      arr_min: Number.isFinite(pt.arrival_s) ? Math.round(pt.arrival_s / 60) : -1, zone: pt.depth_m >= 0.3 ? 'HIGH' : 'DRY'}});
  }
  return {type: 'FeatureCollection' as const, features};
}

const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

function toKml(fc: ReturnType<typeof exportCollection>, title: string): string {
  const marks = fc.features.map(f => {
    const desc = Object.entries(f.properties).map(([k, v]) => `${k}: ${v}`).join('<br/>');
    if (f.geometry.type === 'Polygon') {
      const ring = (f.geometry.coordinates as number[][][])[0].map(c => `${c[0]},${c[1]},0`).join(' ');
      return `<Placemark><name>Flood extent ${f.properties.part}</name><styleUrl>#flood</styleUrl><description><![CDATA[${desc}]]></description><Polygon><outerBoundaryIs><LinearRing><coordinates>${ring}</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>`;
    }
    const [lon, lat] = f.geometry.coordinates as number[];
    return `<Placemark><name>${esc(String(f.properties.name))}</name><description><![CDATA[${desc}]]></description><Point><coordinates>${lon},${lat},0</coordinates></Point></Placemark>`;
  }).join('\n');
  return `<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>${esc(title)}</name><Style id="flood"><LineStyle><color>ffd08a1f</color><width>1.5</width></LineStyle><PolyStyle><color>99d08a1f</color></PolyStyle></Style>\n${marks}\n</Document></kml>\n`;
}

/** Minimal single-page PDF (Helvetica text only) -- no PDF library needed. */
function toPdf(lines: string[]): Blob {
  const safe = (s: string) => s.replace(/[\\()]/g, m => '\\' + m).replace(/[^\x20-\x7e]/g, '-');
  const body = ['BT', '/F1 16 Tf', '50 800 Td', '18 TL', `(${safe(lines[0])}) Tj`, '/F1 10 Tf', '14 TL', 'T*',
    ...lines.slice(1).map(l => `(${safe(l)}) '`), 'ET'].join('\n');
  const objs = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>', `<< /Length ${body.length} >>\nstream\n${body}\nendstream`];
  let pdf = '%PDF-1.4\n';
  const offsets: number[] = [];
  objs.forEach((o, i) => { offsets.push(pdf.length); pdf += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const xref = pdf.length;
  pdf += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n${offsets.map(o => String(o).padStart(10, '0') + ' 00000 n \n').join('')}`;
  pdf += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return new Blob([pdf], {type: 'application/pdf'});
}

export async function buildExport(format: 'shp' | 'kml' | 'geojson' | 'pdf', siteId: string, queryId: string, inputs: EngineInputs, scenario: string): Promise<Blob> {
  const world = getWorld(siteId);
  const fc = exportCollection(siteId, queryId, inputs, scenario);
  if (format === 'geojson') return new Blob([JSON.stringify(fc, null, 1)], {type: 'application/geo+json'});
  if (format === 'kml') return new Blob([toKml(fc, `${world.name} · ${queryId}`)], {type: 'application/vnd.google-earth.kml+xml'});
  if (format === 'shp') {
    const out = await shpwrite.zip(fc as never, {outputType: 'arraybuffer', compression: 'DEFLATE', types: {polygon: 'flood_extent', point: 'warning_points'}} as never);
    return new Blob([out as ArrayBuffer], {type: 'application/zip'});
  }
  const pts = fc.features.filter(f => f.properties.layer === 'warning_point');
  return toPdf([
    `TerraFlow flood report - ${world.name}`,
    `Query ${queryId} · generated ${new Date().toISOString().slice(0, 16).replace('T', ' ')} UTC · DEMO MODE: simulated data`,
    '',
    `Scenario: ${scenario.replace('_', ' ')} · lake volume ${(inputs.water_volume_m3 / 1e6).toFixed(1)} Mm3 · breach width ${inputs.breach_width_m.toFixed(0)} m · failure time ${(inputs.failure_time_s / 60).toFixed(0)} min`,
    `Flood extent polygons: ${fc.features.length - pts.length} (depth > 0.3 m), EPSG:4326`,
    '',
    'Downstream warning table',
    ...pts.map(f => `  ${String(f.properties.name).padEnd(34)} ${String(f.properties.zone).padEnd(6)} depth ${f.properties.depth_m} m   arrival ${Number(f.properties.arr_min) < 0 ? 'not reached' : f.properties.arr_min + ' min'}`),
    '',
    'Caveats',
    '  Clear-water modelling; sediment and debris are not represented.',
    '  Moraine-dam results extrapolate beyond the breach equations\' calibration data.',
    '  Arrival is first wetting, not an evacuation deadline.',
  ]);
}
