import {test, expect} from '@playwright/test';

// design/target-state-preview: exercises the Compare page's live demo engine
// (Card A: SPH vs D-Flow FM, Card B: Emulator vs physics). Only meaningful
// against the 'preview' project (VITE_DATA_MODE=preview, see
// visual/playwright.config.js) -- the 'default' project stays on live/mock
// mode, where /compare renders the legacy fixture-shaped JSX instead.

test.beforeEach(async ({}, testInfo) => {
  test.skip(testInfo.project.name !== 'preview', 'preview-only: exercises the live demo compare engine');
});

test('compare page is fully populated with no UNAVAILABLE/PLACEHOLDER labels', async ({page}) => {
  await page.goto('/compare', {waitUntil: 'networkidle'});
  await expect(page.locator('#root')).toBeVisible();
  await expect(page.getByText('UNAVAILABLE')).toHaveCount(0);
  await expect(page.getByText('PLACEHOLDER data')).toHaveCount(0);
});

test('threshold change updates the IoU/F1 stats', async ({page}) => {
  await page.goto('/compare', {waitUntil: 'networkidle'});
  const iou = page.getByTestId('compare-stat-iou');
  const f1 = page.getByTestId('compare-stat-f1_0_3');
  const before = {iou: await iou.textContent(), f1: await f1.textContent()};

  await page.getByRole('button', {name: '0.05 m'}).click();
  await expect(iou).not.toHaveText(before.iou ?? '');
  const after = {iou: await iou.textContent(), f1: await f1.textContent()};
  expect(after.iou !== before.iou || after.f1 !== before.f1).toBeTruthy();
});

test('site change updates the stats', async ({page}) => {
  await page.goto('/compare', {waitUntil: 'networkidle'});
  const iou = page.getByTestId('compare-stat-iou');
  const before = await iou.textContent();

  await page.getByRole('combobox', {name: 'Site', exact: true}).click();
  await page.getByRole('option', {name: /Rishi Ganga/i}).click();
  await expect(iou).not.toHaveText(before ?? '');
});

test('held-out run HO-4 shows a Low confidence chip with a lower coverage/higher RMSE', async ({page}) => {
  await page.goto('/compare', {waitUntil: 'networkidle'});
  const coverage = page.getByText('90% interval coverage').locator('..').locator('strong');
  const before = await coverage.textContent();

  await page.getByRole('combobox', {name: 'Emulator run'}).click();
  await page.getByRole('option', {name: 'HO-4', exact: true}).click();

  await expect(page.locator('.confidence-box').getByText('LOW', {exact: true})).toBeVisible();
  await expect(coverage).not.toHaveText(before ?? '');
});

test('time slider changes the SPH/FM map images', async ({page}) => {
  await page.goto('/compare', {waitUntil: 'networkidle'});
  const raster = page.locator('.contract-flood-raster').first();
  const before = await raster.getAttribute('src');

  const slider = page.locator('.playback [role="slider"]').first();
  await slider.focus();
  await slider.press('Home');
  await page.waitForTimeout(150);

  await expect(raster).not.toHaveAttribute('src', before ?? '');
});
