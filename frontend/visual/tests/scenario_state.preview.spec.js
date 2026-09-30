import {test, expect} from '@playwright/test';

// design/target-state-preview: exercises computeScenarioState's wiring into
// the Dashboard/Simulation KPI tiles and the downstream-impact POI rows --
// previously these were computed once per query (or, for most Physics-run
// controls, never at all) and never revisited on slider drag or control
// changes (docs/progress.md). Preview-only, same gating as the other
// *.preview.spec.js files.

test.beforeEach(async ({}, testInfo) => {
  test.skip(testInfo.project.name !== 'preview', 'preview-only: exercises the scenario-state engine');
});

async function readKpiValues(page) {
  const text = await page.locator('[data-testid="kpi-tiles"]').innerText();
  // First number on each of the 4 "label / value+unit / range" triples.
  return text.trim();
}

test('dashboard KPI tiles change at 3 different timeline slider positions', async ({page}) => {
  await page.goto('/dashboard', {waitUntil: 'networkidle'});
  await page.waitForSelector('[data-testid="kpi-tiles"]');
  const slider = page.locator('[aria-label="Flood simulation time"]');
  await slider.waitFor({state: 'visible'});
  const values = [];
  for (const steps of [0, 12, 24]) {
    await slider.click();
    await page.keyboard.press('Home');
    for (let i = 0; i < steps; i++) await page.keyboard.press('ArrowRight');
    await page.waitForTimeout(150);
    values.push(await readKpiValues(page));
  }
  expect(new Set(values).size).toBe(3);
});

test('water head, breach width and severity each move the KPIs in the expected direction', async ({page}) => {
  await page.goto('/simulation', {waitUntil: 'networkidle'});
  await page.waitForSelector('[data-testid="kpi-tiles"]');

  // Severity (Rapid query mode).
  await page.getByRole('tab', {name: /rapid query/i}).click();
  const severitySlider = page.locator('[aria-label="Scenario severity"]');
  await severitySlider.click(); await page.keyboard.press('Home');
  await page.waitForTimeout(150);
  const lowSeverity = await readKpiValues(page);
  await severitySlider.click(); await page.keyboard.press('End');
  await page.waitForTimeout(150);
  const highSeverity = await readKpiValues(page);
  expect(highSeverity).not.toBe(lowSeverity);

  // Water head and breach width (Physics run mode) -- also confirms these
  // controls are no longer inert (they were never read by the engine before).
  await page.getByRole('tab', {name: /physics run/i}).click();
  const headInput = page.locator('input[aria-label="Water head"]');
  const widthInput = page.locator('input[aria-label="Breach width"]');

  await headInput.fill('20'); await headInput.blur(); await page.waitForTimeout(150);
  const lowHead = await readKpiValues(page);
  await headInput.fill('110'); await headInput.blur(); await page.waitForTimeout(150);
  const highHead = await readKpiValues(page);
  expect(highHead).not.toBe(lowHead);

  await widthInput.fill('60'); await widthInput.blur(); await page.waitForTimeout(150);
  const lowWidth = await readKpiValues(page);
  await widthInput.fill('170'); await widthInput.blur(); await page.waitForTimeout(150);
  const highWidth = await readKpiValues(page);
  expect(highWidth).not.toBe(lowWidth);
});

test('downstream-impact POI rows show "not reached" before the front arrives and a real low<high range after', async ({page}) => {
  await page.goto('/dashboard', {waitUntil: 'networkidle'});
  await page.waitForSelector('[data-testid="kpi-tiles"]');
  const slider = page.locator('[aria-label="Flood simulation time"]');
  await slider.waitFor({state: 'visible'});

  // t=0: every POI row should read "Not reached".
  await slider.click(); await page.keyboard.press('Home');
  await page.waitForTimeout(150);
  const rowsAtStart = page.locator('[data-testid="poi-row"]');
  await expect(rowsAtStart.first()).toBeVisible();
  const countAtStart = await rowsAtStart.count();
  for (let i = 0; i < countAtStart; i++) {
    await expect(rowsAtStart.nth(i)).toContainText('Not reached');
  }

  // t=max: the nearest POI (Lachen, listed first) should have arrived, with
  // a real (non-collapsed) low-high arrival range, not "Not reached".
  await slider.click(); await page.keyboard.press('End');
  await page.waitForTimeout(150);
  const rowsAtEnd = page.locator('[data-testid="poi-row"]');
  const firstRowText = await rowsAtEnd.first().innerText();
  expect(firstRowText).not.toContain('Not reached');
  expect(firstRowText).toMatch(/(\d+(\.\d+)?)–(\d+(\.\d+)?) min/);
  const [, lowStr, , highStr] = firstRowText.match(/(\d+(\.\d+)?)–(\d+(\.\d+)?) min/);
  expect(Number(lowStr)).toBeLessThan(Number(highStr));
});
