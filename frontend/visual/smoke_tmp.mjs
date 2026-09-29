import {chromium} from 'playwright';

async function main() {
  const browser = await chromium.launch({args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader']});
  const page = await browser.newPage({viewport: {width: 1440, height: 1200}, reducedMotion: 'reduce'});
  const errors = [];
  page.on('console', m => { if (m.type() === 'error') errors.push('[console] ' + m.text()); });
  page.on('pageerror', e => errors.push('[pageerror] ' + String(e)));

  const screens = ['dashboard', 'simulation', 'compare', 'impact', 'monitoring', 'validation', 'data', 'exports', 'sites', 'settings', 'library', 'lab'];
  for (const screen of screens) {
    await page.goto(`http://127.0.0.1:5174/${screen}`, {waitUntil: 'networkidle'});
    await page.waitForTimeout(700);
  }

  // Run a flood query from Dashboard, then check Simulation/Impact/Compare.
  await page.goto('http://127.0.0.1:5174/dashboard', {waitUntil: 'networkidle'});
  await page.waitForTimeout(500);
  await page.getByRole('button', {name: /run flood query/i}).click({timeout: 5000}).catch(e => errors.push('[click] run failed: ' + e.message));
  await page.waitForTimeout(1500);
  await page.screenshot({path: '/tmp/smoke_dashboard.png', fullPage: true});

  await page.getByRole('button', {name: 'Impact Analysis'}).click({timeout: 5000}).catch(e => errors.push('[click] impact nav failed: ' + e.message));
  await page.waitForTimeout(1000);
  await page.screenshot({path: '/tmp/smoke_impact.png', fullPage: true});

  await page.getByRole('button', {name: 'Compare Models'}).click({timeout: 5000}).catch(e => errors.push('[click] compare nav failed: ' + e.message));
  await page.waitForTimeout(1000);
  await page.screenshot({path: '/tmp/smoke_compare.png', fullPage: true});

  await page.getByRole('button', {name: 'GEE-ready Monitoring'}).click({timeout: 5000}).catch(e => errors.push('[click] gee nav failed: ' + e.message));
  await page.waitForTimeout(1000);
  await page.screenshot({path: '/tmp/smoke_gee.png', fullPage: true});

  console.log('ERRORS:', JSON.stringify(errors, null, 2));
  await browser.close();
}
main();
