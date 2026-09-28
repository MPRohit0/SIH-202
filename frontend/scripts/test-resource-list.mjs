// Unit tests for src/offline/resource-list.ts. No test framework is set up
// for frontend/src (only the Playwright visual suite exists), so this uses
// Vite's own ssrLoadModule (already a devDependency) to resolve the TS
// module's relative imports correctly in plain Node, following the same
// small-standalone-script convention as check-shell.mjs.
// Run with `npm run test:offline`.
import assert from 'node:assert/strict';
import {createServer} from 'vite';

const server = await createServer({
  configFile: new URL('../vite.config.ts', import.meta.url).pathname,
  server: {middlewareMode: true},
  appType: 'custom',
});

let failures = 0;
function test(name, fn) {
  try {
    fn();
    console.log(`ok - ${name}`);
  } catch (e) {
    failures++;
    console.error(`FAIL - ${name}`);
    console.error(e);
  }
}

try {
  const {collectResourceUrls, collectGlobalUrls} = await server.ssrLoadModule('/src/offline/resource-list.ts');

  const baseBundle = {
    siteId: 'teesta',
    floodQuery: {query_id: 'q_123', layers: [], vectors: null},
    impact: null,
    compare: null,
    timeline: null,
    validation: null,
    gee: null,
    scene3d: null,
  };

  test('collectGlobalUrls includes styles and sites', () => {
    const urls = collectGlobalUrls();
    assert.ok(urls.some(u => u.endsWith('/styles')));
    assert.ok(urls.some(u => u.endsWith('/sites')));
  });

  test('collectResourceUrls includes the base validation endpoint with no events', () => {
    const urls = collectResourceUrls({...baseBundle, validation: {events: []}});
    assert.ok(urls.some(u => u.endsWith('/validation/teesta')));
    assert.ok(!urls.some(u => u.includes('?event=')));
  });

  test('collectResourceUrls includes a historical-validation URL per event', () => {
    const urls = collectResourceUrls({...baseBundle, validation: {events: ['sikkim_glof_2023', 'other_event']}});
    assert.ok(urls.some(u => u.endsWith('/validation/teesta?event=sikkim_glof_2023')),
      `expected a sikkim_glof_2023 historical-validation URL, got: ${JSON.stringify(urls)}`);
    assert.ok(urls.some(u => u.endsWith('/validation/teesta?event=other_event')),
      `expected an other_event historical-validation URL, got: ${JSON.stringify(urls)}`);
  });

  test('collectResourceUrls handles validation being null (no run yet)', () => {
    const urls = collectResourceUrls({...baseBundle, validation: null});
    assert.ok(urls.some(u => u.endsWith('/validation/teesta')));
    assert.ok(!urls.some(u => u.includes('?event=')));
  });

  test('collectResourceUrls URL-encodes event ids with special characters', () => {
    const urls = collectResourceUrls({...baseBundle, validation: {events: ['a b/c']}});
    assert.ok(urls.some(u => u.endsWith('/validation/teesta?event=a%20b%2Fc')),
      `expected an encoded event id, got: ${JSON.stringify(urls)}`);
  });

  test('collectResourceUrls includes all four export formats by default', () => {
    const urls = collectResourceUrls(baseBundle);
    for (const format of ['shp', 'kml', 'geojson', 'pdf']) {
      assert.ok(urls.some(u => u.includes(`export/q_123?format=${format}`)), `missing export format ${format}`);
    }
  });
} finally {
  await server.close();
}

if (failures > 0) {
  console.error(`\n${failures} test(s) failed.`);
  process.exit(1);
}
console.log('\nAll resource-list tests passed.');
