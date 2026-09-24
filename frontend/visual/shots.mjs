// Screenshot every screen of the frontend, and diff two screenshot sets.
//   node shots.mjs shot <label> [baseURL]   -> docs/strip_check/<label>/*.png + console.json
//   node shots.mjs diff <labelA> <labelB>   -> per-screen changed-pixel % + <labelB>/diff-vs-<labelA>.json
import {chromium} from 'playwright';
import {mkdirSync, readFileSync, writeFileSync, existsSync} from 'node:fs';
import {fileURLToPath} from 'node:url';

const OUT = fileURLToPath(new URL('../../docs/strip_check/', import.meta.url));
const SCREENS = ['home', 'dashboard', 'simulation', 'library', 'compare', 'lab', 'impact',
  'data', 'monitoring', 'exports', 'sites', 'settings'];
const VIEWPORT = {width: 1440, height: 900};
const LAUNCH = {args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader']};

async function shoot(label, base = 'http://127.0.0.1:5173') {
  const dir = OUT + label + '/';
  mkdirSync(dir, {recursive: true});
  const browser = await chromium.launch(LAUNCH);
  const report = {};
  for (const [i, screen] of SCREENS.entries()) {
    const page = await browser.newPage({viewport: VIEWPORT, reducedMotion: 'reduce'});
    const errors = [];
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
    page.on('pageerror', e => errors.push(String(e)));
    const res = await page.goto(base + (screen === 'home' ? '/' : '/' + screen), {waitUntil: 'networkidle'});
    await page.waitForTimeout(2500); // let the 3D scene and async data settle
    const file = `${String(i).padStart(2, '0')}-${screen}.png`;
    await page.screenshot({path: dir + file, fullPage: true});
    report[screen] = {status: res?.status(), file, errors};
    console.log(`${label} ${screen}: HTTP ${res?.status()}, ${errors.length} console error(s)`);
    await page.close();
  }
  writeFileSync(dir + 'console.json', JSON.stringify(report, null, 2));
  await browser.close();
}

async function diff(a, b) {
  const browser = await chromium.launch(LAUNCH), page = await browser.newPage();
  const result = {};
  for (const [i, screen] of SCREENS.entries()) {
    const file = `${String(i).padStart(2, '0')}-${screen}.png`;
    const pa = OUT + a + '/' + file, pb = OUT + b + '/' + file;
    if (!existsSync(pa) || !existsSync(pb)) { result[screen] = null; continue; }
    const uri = p => 'data:image/png;base64,' + readFileSync(p).toString('base64');
    result[screen] = await page.evaluate(async ([x, y]) => {
      const load = src => new Promise(r => { const im = new Image(); im.onload = () => r(im); im.src = src; });
      const [ia, ib] = await Promise.all([load(x), load(y)]);
      const w = Math.max(ia.width, ib.width), h = Math.max(ia.height, ib.height);
      const px = im => { const c = new OffscreenCanvas(w, h), g = c.getContext('2d'); g.drawImage(im, 0, 0); return g.getImageData(0, 0, w, h).data; };
      const da = px(ia), db = px(ib);
      let changed = 0;
      for (let k = 0; k < da.length; k += 4)
        if (Math.abs(da[k] - db[k]) + Math.abs(da[k + 1] - db[k + 1]) + Math.abs(da[k + 2] - db[k + 2]) > 24) changed++;
      return {sizeA: [ia.width, ia.height], sizeB: [ib.width, ib.height], changedPct: +(100 * changed / (w * h)).toFixed(2)};
    }, [uri(pa), uri(pb)]);
    console.log(`${screen}: ${JSON.stringify(result[screen])}`);
  }
  writeFileSync(OUT + b + `/diff-vs-${a}.json`, JSON.stringify(result, null, 2));
  await browser.close();
}

const [cmd, x, y] = process.argv.slice(2);
if (cmd === 'shot') await shoot(x, y);
else if (cmd === 'diff') await diff(x, y);
else { console.error('usage: node shots.mjs shot <label> [baseURL] | diff <labelA> <labelB>'); process.exit(1); }
