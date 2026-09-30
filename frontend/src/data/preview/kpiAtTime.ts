// Preview mode only (VITE_DATA_MODE=preview): makes the 4-tile KPI strip under
// the terrain view follow the playback slider. This is a display curve, not
// solver output — it scales the end-of-run values the tiles already show by a
// progress factor of slider time. The "Demo mode — simulated data" banner
// covers it; default mode never calls this.

/** Rise time constant as a fraction of the run length (300 min of an 1,800 min run). */
export const GROWTH_TAU_FRACTION = 1 / 6;
/** Half-width of the displayed range, as a fraction of the displayed value. */
export const RANGE_FRACTION = 0.15;

const clamp01 = (x: number) => Math.min(1, Math.max(0, x));

/** Smooth rise f = 1 − exp(−t/τ), normalised so f(0) = 0 and f(t_end) = 1 exactly. */
export function kpiGrowthAtTime(tMin: number, tEndMin: number): number {
  if (!(tEndMin > 0)) return 1;
  const tau = tEndMin * GROWTH_TAU_FRACTION;
  const t = clamp01(tMin / tEndMin) * tEndMin;
  return clamp01((1 - Math.exp(-t / tau)) / (1 - Math.exp(-tEndMin / tau)));
}

/** End-of-run estimate × factor. The value is rounded to 1 decimal in display
 * units (value × scale, e.g. m² → km²) and gets a ±15% range; the range is
 * null (shown as "—") while the value is 0. Returned in the input's units. */
export function kpiAtTime(final: {value: number | null}, factor: number, scale = 1): {value: number | null; low: number | null; high: number | null} {
  if (final.value === null) return {value: null, low: null, high: null};
  const value = Math.round(final.value * scale * factor * 10) / 10 / scale;
  if (value === 0) return {value: 0, low: null, high: null};
  return {value, low: value * (1 - RANGE_FRACTION), high: value * (1 + RANGE_FRACTION)};
}
