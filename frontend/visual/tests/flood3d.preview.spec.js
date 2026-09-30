import {test, expect} from '@playwright/test';

// design/target-state-preview: the 3D terrain's flood surface used to be a
// single static median snapshot with no time axis at all (docs/progress.md)
// -- these tests exercise the fix: the flood front now starts at the breach
// marker and spreads downstream as the slider/playback/controls move.
// Preview-only, same gating as the other *.preview.spec.js files.
//
// Serial, not parallel: three WebGL/software-rendered (SwiftShader) 3D
// scenes running at once starve each other of CPU in a constrained sandbox
// and start throwing on canvas.screenshot() -- an environment ceiling, not a
// bug (confirmed: all three pass reliably with --workers=1, and fail only
// under full parallelism). Serial keeps them reliable everywhere without
// touching the shared playwright.config for every other spec file. A lone
// retry absorbs any contention from OTHER spec files' 3D/WebGL tests still
// running in sibling workers (screens.spec.js, simulation.preview.spec.js).
test.describe.configure({mode: 'serial', retries: 1});

test.beforeEach(async ({}, testInfo) => {
  test.skip(testInfo.project.name !== 'preview', 'preview-only: exercises the real Teesta 3D flood animation');
});

async function openTeesta3d(page) {
  await page.goto('/', {waitUntil: 'networkidle'});
  await page.getByRole('button', {name: /open teesta iii demo/i}).first().click();
  await page.waitForTimeout(2000);
  await page.getByRole('tab', {name: /3D terrain/i}).click();
  await page.waitForTimeout(1200);
}

async function setSliderFraction(page, frac) {
  const slider = page.locator('[aria-label="Flood simulation time"]');
  await slider.click();
  await page.keyboard.press('Home');
  for (let i = 0; i < Math.round(frac * 24); i++) await page.keyboard.press('ArrowRight');
  await page.waitForTimeout(500);
}

// Counts pixels that changed vs the t=0 baseline (guaranteed fully dry: at
// distance 0 from the breach, timeFactor(0, 0, duration) = 0) instead of
// matching against a fixed water-colour palette -- the terrain itself is lit
// (MeshStandardMaterial) and can render close to almost any hue depending on
// the sun/rim lights, so "does this pixel look blue" is not a reliable
// signal, but "how much of the frame differs from the known-dry baseline"
// is: it only grows as more of the real flood footprint wets/deepens.
async function diffPixelCount(page, bufferA, bufferB) {
  const a = `data:image/png;base64,${bufferA.toString('base64')}`;
  const b = `data:image/png;base64,${bufferB.toString('base64')}`;
  return page.evaluate(async ({a, b}) => {
    const load = src => new Promise((resolve, reject) => {
      const img = new Image(); img.onload = () => resolve(img); img.onerror = reject; img.src = src;
    });
    const [imgA, imgB] = await Promise.all([load(a), load(b)]);
    const canvas = document.createElement('canvas');
    canvas.width = imgA.naturalWidth; canvas.height = imgA.naturalHeight;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(imgA, 0, 0);
    const dataA = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(imgB, 0, 0);
    const dataB = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
    let changed = 0;
    for (let i = 0; i < dataA.length; i += 4 * 3) { // sample every 3rd pixel: fast, plenty of signal
      const dr = dataA[i] - dataB[i], dg = dataA[i + 1] - dataB[i + 1], db = dataA[i + 2] - dataB[i + 2];
      if (dr * dr + dg * dg + db * db > 400) changed++; // ~11 per channel tolerance (antialiasing/lighting noise floor)
    }
    return changed;
  }, {a, b});
}

test('3D view at t=10%/50%/100% differ, with more of the frame changed (more wet area) at later times', async ({page}) => {
  await openTeesta3d(page);
  const canvas = page.locator('.three-host canvas').first();
  await expect(canvas).toBeVisible();

  await setSliderFraction(page, 0);
  const shot0 = await canvas.screenshot(); // guaranteed fully dry
  await setSliderFraction(page, 0.10);
  const shot10 = await canvas.screenshot();
  await setSliderFraction(page, 0.50);
  const shot50 = await canvas.screenshot();
  await setSliderFraction(page, 1.00);
  const shot100 = await canvas.screenshot();

  expect(Buffer.compare(shot10, shot50)).not.toBe(0);
  expect(Buffer.compare(shot50, shot100)).not.toBe(0);
  expect(Buffer.compare(shot10, shot100)).not.toBe(0);

  const diff10 = await diffPixelCount(page, shot0, shot10);
  const diff50 = await diffPixelCount(page, shot0, shot50);
  const diff100 = await diffPixelCount(page, shot0, shot100);
  expect(diff50).toBeGreaterThan(diff10);
  expect(diff100).toBeGreaterThan(diff50);
});

test('pressing play animates the 3D canvas with no console errors', async ({page}) => {
  const errors = [];
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', e => errors.push(String(e)));

  await openTeesta3d(page);
  await setSliderFraction(page, 0);
  const canvas = page.locator('.three-host canvas').first();
  const before = await canvas.screenshot();

  await page.getByRole('button', {name: /play flood playback/i}).click();
  await page.waitForTimeout(2000);
  const after = await canvas.screenshot();

  expect(Buffer.compare(before, after)).not.toBe(0);
  expect(errors).toEqual([]);
});

test('changing severity changes the 3D view at the same t', async ({page}) => {
  await openTeesta3d(page);
  await setSliderFraction(page, 1.0);
  const canvas = page.locator('.three-host canvas').first();
  const before = await canvas.screenshot();

  await page.getByRole('tab', {name: /rapid query/i}).click();
  const severitySlider = page.locator('[aria-label="Scenario severity"]');
  await severitySlider.click();
  await page.keyboard.press('Home'); // severity -> minimum
  await page.waitForTimeout(300);
  await page.getByRole('tab', {name: /3D terrain/i}).click();
  await page.waitForTimeout(500);
  const after = await canvas.screenshot();

  expect(Buffer.compare(before, after)).not.toBe(0);
});
