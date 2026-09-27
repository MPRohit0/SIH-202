import {test, expect} from '@playwright/test';

const screens = [
  ['home', '/'],
  ['dashboard', '/dashboard'],
  ['simulation', '/simulation'],
  ['library', '/library'],
  ['compare', '/compare'],
  ['lab', '/lab'],
  ['impact', '/impact'],
  ['data', '/data'],
  ['monitoring', '/monitoring'],
  ['exports', '/exports'],
  ['sites', '/sites'],
  ['settings', '/settings'],
];

for (const [name, route] of screens) {
  test(`${name} visual snapshot`, async ({page}) => {
    await page.goto(route, {waitUntil: 'networkidle'});
    await expect(page.locator('#root')).toBeVisible();
    await expect(page).toHaveScreenshot(`${name}.png`, {
      fullPage: true,
      animations: 'disabled',
      caret: 'hide',
      timeout: 15_000,
    });
  });
}
