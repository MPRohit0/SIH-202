// Deterministic PRNG + seeding for the preview demo engine
// (design/target-state-preview). Every "random" number in the engine comes
// from here, seeded by the current inputs, so the same inputs always produce
// the same outputs (the brief's "seeded and deterministic" requirement) and
// "Reset demo" just means re-deriving from the default inputs again.

/** FNV-1a string hash -> 32-bit unsigned int, used to turn an arbitrary seed
 * key (site id + scenario type + input values) into a numeric PRNG seed. */
export function hashSeed(key: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < key.length; i++) {
    h ^= key.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

/** mulberry32: a small, fast, deterministic PRNG. Returns a function that
 * yields floats in [0, 1) on each call, advancing its own internal state. */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return function next() {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Builds a seed key from the exact values that should change the outcome --
 * two calls with identical arguments always produce an identical key. */
export function seedKeyFrom(parts: Record<string, string | number | boolean | undefined | null>): string {
  return Object.keys(parts).sort().map(k => `${k}=${parts[k]}`).join('|');
}

/** A low-discrepancy sequence (fractional parts of i*sqrt(prime)) for Monte
 * Carlo sampling -- deterministic and well-spread without needing many draws,
 * same technique used by the earlier gen_preview_assets.py:_weyl_points. */
export function weylPoints(n: number, dims: number, offset: number): number[][] {
  const bases = [2, 3, 5, 7, 11].slice(0, dims).map(Math.sqrt);
  const out: number[][] = [];
  for (let i = offset; i < offset + n; i++) {
    out.push(bases.map(b => ((i + 1) * b) % 1));
  }
  return out;
}
