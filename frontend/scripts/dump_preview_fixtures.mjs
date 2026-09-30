#!/usr/bin/env node
// Compiles the demo engine (frontend/src/data/preview/engine/*.ts) to plain
// CommonJS with the already-installed `typescript` package (no ts-node/tsx,
// no new dependency) and calls its defaultSnapshot(siteId) for each site,
// writing the result to frontend/src/data/preview/generated/*.json.
//
// This is what tests/frontend/test_preview_fixtures.py validates against
// contracts/schemas/*.schema.json -- a shape regression check on the engine's
// output, now that the running app computes everything live instead of
// reading static fixture JSON (design/target-state-preview).
//
// Usage: node frontend/scripts/dump_preview_fixtures.mjs
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {dirname, join} from 'node:path';
import {mkdirSync, writeFileSync, rmSync} from 'node:fs';

const SCRIPTS_DIR = dirname(fileURLToPath(import.meta.url));
const FRONTEND_DIR = join(SCRIPTS_DIR, '..');
const REPO_ROOT = join(FRONTEND_DIR, '..');
// Sibling of frontend/, not nested inside it -- so relative imports inside
// the compiled engine files (e.g. raster.ts's ../../../../../contracts/
// styles.json) resolve to the same real path as they do from their original
// location under frontend/src/... (see tsconfig.dump.json's outDir comment).
const BUILD_DIR = join(REPO_ROOT, '.dump_build');
const GENERATED_DIR = join(FRONTEND_DIR, 'src', 'data', 'preview', 'generated');

rmSync(BUILD_DIR, {recursive: true, force: true});
execFileSync(process.execPath, [join(FRONTEND_DIR, 'node_modules', 'typescript', 'bin', 'tsc'), '-p', join(SCRIPTS_DIR, 'tsconfig.dump.json')], {stdio: 'inherit'});
// tsc emitted plain CommonJS (`module: commonjs`); frontend/package.json says
// "type": "module", so mark this build output as CommonJS explicitly or
// Node's ESM loader would try (and fail) to parse it as an ES module.
writeFileSync(join(BUILD_DIR, 'package.json'), JSON.stringify({type: 'commonjs'}));

const {createRequire} = await import('node:module');
const require = createRequire(import.meta.url);
const enginePath = join(BUILD_DIR, 'src', 'data', 'preview', 'engine', 'index.js');
const {defaultSnapshot} = require(enginePath);

mkdirSync(GENERATED_DIR, {recursive: true});
for (const siteId of ['teesta', 'rishi_ganga']) {
  const snapshot = defaultSnapshot(siteId);
  writeFileSync(join(GENERATED_DIR, `${siteId}.default_snapshot.json`), JSON.stringify(snapshot, null, 2) + '\n');
  console.log(`Wrote generated/${siteId}.default_snapshot.json`);
}

rmSync(BUILD_DIR, {recursive: true, force: true});
