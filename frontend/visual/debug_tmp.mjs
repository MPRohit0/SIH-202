import {chromium} from 'playwright';
async function main() {
  const browser = await chromium.launch({args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader']});
  const page = await browser.newPage({viewport: {width: 1440, height: 1200}});
  page.on('console', m => console.log('[console]', m.text()));
  page.on('pageerror', e => console.log('[pageerror]', String(e)));
  await page.goto('http://127.0.0.1:5174/dashboard', {waitUntil: 'networkidle'});
  await page.waitForTimeout(500);
  await page.getByRole('button', {name: /run flood query/i}).click({timeout: 5000});
  await page.waitForTimeout(1500);
  const info = await page.evaluate(() => {
    const w = window;
    return {hasDebug: !!w.__debugFloodQuery};
  });
  console.log('info', info);
  await browser.close();
}
main();
