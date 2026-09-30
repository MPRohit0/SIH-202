import {test, expect} from '@playwright/test';

// design/target-state-preview: exercises the Simulation workspace page's live
// demo engine (the 3D terrain tab, the 2D contract raster, the demo banner
// layout, and the absence of any real backend traffic). Only meaningful
// against the 'preview' project (VITE_DATA_MODE=preview, see
// visual/playwright.config.js) -- same preview-only gating as
// compare.preview.spec.js.

test.beforeEach(async ({}, testInfo) => {
  test.skip(testInfo.project.name !== 'preview', 'preview-only: exercises the live demo engine');
});

test('simulation page loads with the demo banner in flow (not overlapping the logo)', async ({page}) => {
  await page.goto('/simulation', {waitUntil: 'networkidle'});
  await expect(page.locator('#root')).toBeVisible();
  const banner = page.locator('.preview-banner');
  const logo = page.locator('.sentriq-logo').first();
  await expect(banner).toBeVisible();
  await expect(logo).toBeVisible();
  const bannerBox = await banner.boundingBox();
  const logoBox = await logo.boundingBox();
  expect(bannerBox).not.toBeNull();
  expect(logoBox).not.toBeNull();
  // No vertical overlap: the banner's bottom edge must sit at or above the logo's top edge.
  expect(bannerBox.y + bannerBox.height).toBeLessThanOrEqual(logoBox.y + 1);
});

test('no network request to /api/v1/ happens while in preview mode', async ({page}) => {
  const apiRequests = [];
  page.on('request', req => { if (req.url().includes('/api/v1')) apiRequests.push(req.url()); });

  await page.goto('/simulation', {waitUntil: 'networkidle'});
  await page.getByRole('button', {name: 'Run flood query'}).click();
  await page.waitForTimeout(1500);
  await page.getByRole('tab', {name: /3D terrain/i}).click();
  await page.waitForTimeout(1500);
  await page.getByRole('tab', {name: /2D map/i}).click();
  await page.waitForTimeout(1500);

  expect(apiRequests).toEqual([]);
});

test('clicking 3D terrain renders a canvas with no console errors', async ({page}) => {
  const errors = [];
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
  page.on('pageerror', err => errors.push(err.message));

  await page.goto('/simulation', {waitUntil: 'networkidle'});
  await page.getByRole('button', {name: 'Run flood query'}).click();
  await page.waitForTimeout(1500);
  await page.getByRole('tab', {name: /3D terrain/i}).click();
  await page.waitForTimeout(1500);

  await expect(page.locator('.map-stage canvas').first()).toBeVisible();
  expect(errors).toEqual([]);
});

test('the 2D map raster has non-uniform pixel values (an actual flood shape, not a flat fill)', async ({page}) => {
  await page.goto('/simulation', {waitUntil: 'networkidle'});
  await page.getByRole('button', {name: 'Run flood query'}).click();
  await page.waitForTimeout(1500);
  await page.getByRole('tab', {name: /2D map/i}).click();
  await page.waitForTimeout(500);

  const raster = page.locator('.contract-flood-raster');
  await expect(raster).toBeVisible();

  const samples = await raster.evaluate((img) => {
    const canvas = document.createElement('canvas');
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(img, 0, 0);
    const {data} = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const pixels = [];
    for (let i = 0; i < data.length; i += 4 * 977) {
      pixels.push(`${data[i]},${data[i + 1]},${data[i + 2]},${data[i + 3]}`);
    }
    return pixels;
  });

  const distinct = new Set(samples);
  expect(distinct.size).toBeGreaterThan(1);
});

test('the terrain panel shows the site\'s real CRS and grid resolution, not placeholder text', async ({page}) => {
  await page.goto('/simulation', {waitUntil: 'networkidle'});
  const strip = page.locator('.command-strip');
  await expect(strip).not.toContainText('EPSG:4326');
  await expect(strip).toContainText('EPSG:326');
  await expect(strip).not.toContainText('— m grid');
});
