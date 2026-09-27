// Guards the UI-shell strip (see docs/progress.md). Fails the build if:
//   1. TypeScript doesn't type-check.
//   2. The Vite build doesn't succeed.
//   3. Any removed piece's name creeps back into the source - a sign someone
//      re-added Tehri-specific data, the deleted browser solver, or the
//      removed Cloudflare/ChatGPT-auth backend instead of routing new data
//      needs through src/data/source.ts.
// Run with `npm run check:shell`.
import {spawnSync} from 'node:child_process';
import {readFileSync, readdirSync, statSync} from 'node:fs';
import {join, extname} from 'node:path';

const ROOT = new URL('..', import.meta.url).pathname;
const SCAN_DIRS = ['app', 'lib', 'src', 'components', 'hooks'];
const SCAN_EXT = new Set(['.ts', '.tsx', '.js', '.mjs', '.cjs', '.css', '.html']);
const SKIP_DIRS = new Set(['node_modules']);

// Each pattern names something Groups 1-5 removed. If it reappears, either
// the removal was undone or new code is bypassing src/data/source.ts.
const FORBIDDEN = [
  {pattern: /tehri/i, why: 'Tehri was the only site in the removed prototype (Group 2/3) - real sites come from a connected backend, not a hardcoded name'},
  {pattern: /\b4510\b/, why: "Tehri's hardcoded source cell index (Group 2)"},
  {pattern: /model-worker/, why: 'the removed Fast Screening solver (public/model-worker.js, Group 2) - flood results must come from source.ts'},
  {pattern: /\/api\/records/, why: 'the removed Cloudflare D1/R2 saved-runs endpoint (Group 2, rule 11: no cloud, no auth)'},
  {pattern: /oai-authenticated/, why: 'the removed ChatGPT-auth headers (Group 2, rule 11)'},
  {pattern: /240 ?m\b/, why: "Tehri's scenario-library breach-width literal (severity x 2.4 m, Group 3)"},
  {pattern: /SENTRIQ|Sentriq(?!App)/, why: 'the retired product name (rebranded to TerraFlow) reappearing as user-facing brand text - the lowercase `sentriq` folder, CSS classes and `SentriqApp` component name are unchanged code identifiers and do not match this'},
];

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    if (SKIP_DIRS.has(name) || name.endsWith(':Zone.Identifier')) continue;
    const full = join(dir, name);
    const st = statSync(full);
    if (st.isDirectory()) walk(full, out);
    else if (SCAN_EXT.has(extname(name))) out.push(full);
  }
  return out;
}

function run(label, cmd, args) {
  process.stdout.write(`-> ${label}\n`);
  const result = spawnSync(cmd, args, {cwd: ROOT, stdio: 'inherit'});
  if (result.status !== 0) {
    console.error(`\ncheck:shell failed at: ${label}`);
    process.exit(result.status ?? 1);
  }
}

run('tsc --noEmit', 'node', ['node_modules/typescript/bin/tsc', '--noEmit', '-p', 'tsconfig.json']);
run('vite build', 'node', ['node_modules/vite/bin/vite.js', 'build']);

process.stdout.write('-> scanning for removed pieces\n');
const files = SCAN_DIRS.flatMap(d => {
  try { return walk(join(ROOT, d)); } catch { return []; } // dir may not exist
});
let failed = false;
for (const file of files) {
  const text = readFileSync(file, 'utf8');
  for (const {pattern, why} of FORBIDDEN) {
    if (pattern.test(text)) {
      console.error(`  ${file.replace(ROOT, '')}: matches ${pattern} - ${why}`);
      failed = true;
    }
  }
}
if (failed) {
  console.error('\ncheck:shell failed: a removed piece reappeared. See docs/progress.md for what Groups 1-5 removed and why.');
  process.exit(1);
}
console.log('check:shell passed.');
