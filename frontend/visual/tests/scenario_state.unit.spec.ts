import {test, expect} from '@playwright/test';
import {computeScenarioState} from '../../src/data/preview/engine/scenario_state';

const base = {site: 'teesta', t_min: 60, severity: 50, water_head_m: 40, breach_width_m: 120,
  formation_min: 15, duration_min: 60, manning_n: 0.045, volume_cap_mcm: 100};

test('monotonic in severity/head/width/volume', () => {
  const lo = computeScenarioState({...base, severity: 10});
  const hi = computeScenarioState({...base, severity: 90});
  expect(hi.max_depth_m.value).toBeGreaterThan(lo.max_depth_m.value);
  expect(hi.peak_discharge_m3s.value).toBeGreaterThan(lo.peak_discharge_m3s.value);
  expect(hi.flood_extent_km2.value).toBeGreaterThan(lo.flood_extent_km2.value);

  const loH = computeScenarioState({...base, water_head_m: 15});
  const hiH = computeScenarioState({...base, water_head_m: 100});
  expect(hiH.max_depth_m.value).toBeGreaterThan(loH.max_depth_m.value);

  const loW = computeScenarioState({...base, breach_width_m: 60});
  const hiW = computeScenarioState({...base, breach_width_m: 180});
  expect(hiW.max_depth_m.value).toBeGreaterThan(loW.max_depth_m.value);

  const loV = computeScenarioState({...base, volume_cap_mcm: 20});
  const hiV = computeScenarioState({...base, volume_cap_mcm: 400});
  expect(hiV.max_depth_m.value).toBeGreaterThan(loV.max_depth_m.value);
});

test('longer formation lowers peak and delays arrival', () => {
  const shortF = computeScenarioState({...base, formation_min: 2, t_min: 200});
  const longF = computeScenarioState({...base, formation_min: 45, t_min: 200});
  expect(longF.max_depth_m.value).toBeLessThan(shortF.max_depth_m.value);
  const shortArr = shortF.pois.find(p => p.poi_id.includes('chungthang'))!.arrival_min.value;
  const longArr = longF.pois.find(p => p.poi_id.includes('chungthang'))!.arrival_min.value;
  expect(longArr).toBeGreaterThan(shortArr);
});

test('higher Manning n slows arrival and slightly raises depth', () => {
  const smoothN = computeScenarioState({...base, manning_n: 0.02, t_min: 200});
  const roughN = computeScenarioState({...base, manning_n: 0.12, t_min: 200});
  const smoothArr = smoothN.pois.find(p => p.poi_id.includes('chungthang'))!.arrival_min.value;
  const roughArr = roughN.pois.find(p => p.poi_id.includes('chungthang'))!.arrival_min.value;
  expect(roughArr).toBeGreaterThan(smoothArr);
  expect(roughN.max_depth_m.value).toBeGreaterThan(smoothN.max_depth_m.value);
});

test('arrival grows with distance downstream', () => {
  const s = computeScenarioState({...base, t_min: 500});
  for (let i = 1; i < s.pois.length; i++) {
    // world POIs are listed in increasing chainage order
    expect(s.pois[i].arrival_min.value).toBeGreaterThanOrEqual(s.pois[i - 1].arrival_min.value);
  }
});

test('S-curve time behaviour: 0 before arrival, rises, POI fills after arrival', () => {
  const poiId = 'teesta__poi__chungthang';
  const before = computeScenarioState({...base, t_min: 1}).pois.find(p => p.poi_id === poiId)!;
  expect(before.reached).toBe(false);
  expect(before.depth_m.value).toBe(0);

  const justAfter = computeScenarioState({...base, t_min: 40}).pois.find(p => p.poi_id === poiId)!;
  const later = computeScenarioState({...base, t_min: 200}).pois.find(p => p.poi_id === poiId)!;
  expect(justAfter.reached).toBe(true);
  expect(justAfter.depth_m.value).toBeGreaterThan(0);
  expect(later.depth_m.value).toBeGreaterThanOrEqual(justAfter.depth_m.value);
  expect(later.arrival_min.low).toBeLessThan(later.arrival_min.high);
});

test('overall KPIs rise with t then plateau (never collapsed ranges)', () => {
  const t1 = computeScenarioState({...base, t_min: 5});
  const t2 = computeScenarioState({...base, t_min: 30});
  const t3 = computeScenarioState({...base, t_min: 60});
  expect(t2.max_depth_m.value).toBeGreaterThan(t1.max_depth_m.value);
  expect(t3.flood_extent_km2.value).toBeGreaterThan(t2.flood_extent_km2.value);
  for (const s of [t1, t2, t3]) {
    expect(s.max_depth_m.low).toBeLessThan(s.max_depth_m.high);
  }
});
