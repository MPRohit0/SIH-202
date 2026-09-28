// Forward WGS84 Transverse Mercator (Snyder 1987 series). Closed-form, no external
// projection library. Verified against pyproj.Transformer for Teesta's EPSG:32645
// (2 cm agreement) -- accurate enough to place a marker in a several-km 3D scene.
const WGS84_A = 6378137.0;
const WGS84_F = 1 / 298.257223563;
const K0 = 0.9996;

export function lonLatToUtm(lonDeg: number, latDeg: number, epsg: number): {x: number; y: number} | null {
  const zone = epsg >= 32601 && epsg <= 32660 ? epsg - 32600 : epsg >= 32701 && epsg <= 32760 ? epsg - 32700 : null;
  if (zone === null) return null;
  const southern = epsg >= 32700;
  const e2 = WGS84_F * (2 - WGS84_F);
  const e1sq = e2 / (1 - e2);
  const lat = (latDeg * Math.PI) / 180;
  const lon = (lonDeg * Math.PI) / 180;
  const lon0 = (((zone - 1) * 6 - 180 + 3) * Math.PI) / 180;
  const N = WGS84_A / Math.sqrt(1 - e2 * Math.sin(lat) ** 2);
  const T = Math.tan(lat) ** 2;
  const C = e1sq * Math.cos(lat) ** 2;
  const A = Math.cos(lat) * (lon - lon0);
  const M = WGS84_A * (
    (1 - e2 / 4 - (3 * e2 ** 2) / 64 - (5 * e2 ** 3) / 256) * lat -
    ((3 * e2) / 8 + (3 * e2 ** 2) / 32 + (45 * e2 ** 3) / 1024) * Math.sin(2 * lat) +
    ((15 * e2 ** 2) / 256 + (45 * e2 ** 3) / 1024) * Math.sin(4 * lat) -
    ((35 * e2 ** 3) / 3072) * Math.sin(6 * lat)
  );
  const x = K0 * N * (A + ((1 - T + C) * A ** 3) / 6 + ((5 - 18 * T + T ** 2 + 72 * C - 58 * e1sq) * A ** 5) / 120) + 500000;
  let y = K0 * (M + N * Math.tan(lat) * (A ** 2 / 2 + ((5 - T + 9 * C + 4 * C ** 2) * A ** 4) / 24 + ((61 - 58 * T + T ** 2 + 600 * C - 330 * e1sq) * A ** 6) / 720));
  if (southern) y += 10000000;
  return {x, y};
}
