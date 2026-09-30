# TerraFlow frontend — UI shell

This is a **UI shell**: every screen, layout and style from the original prototype, with
its data source removed. There is no in-browser solver, no bundled site data, and no
cloud or auth backend. Every screen currently shows an honest "no site connected" /
"awaiting backend" state. This is expected — it is not broken, it is waiting for
`docs/handoff_contract.md`'s REST API (`http://localhost:8000/api/v1`) to be wired up.

If you're looking for what this app *used to* do (a self-contained Tehri/Bhagirathi demo
with an in-browser hydraulic solver, a Cloudflare-hosted saved-runs backend, and a GEE
script generator), see `docs/progress.md`, which records what was removed, from where,
and why, group by group.

## Run it

```
npm install
npm run dev            # http://127.0.0.1:5173
npm run build           # -> dist/, a static site
npm run start            # preview the production build
npm run check:shell     # tsc + build + a guard against reintroducing removed pieces
```

Plain Vite + React. No Next.js, no vinext, no wrangler, no Cloudflare Workers, nothing to
provision. `npm run build` produces a static `dist/` folder that any static file server
(including the eventual M0 API) can serve, with an SPA fallback to `index.html` for
client-side routes.

## Where data comes from

Every screen reads through **one seam**: [`src/data/source.ts`](src/data/source.ts).
Every function in it stands in for a real `/api/v1/...` call and today resolves to an
`{status: 'awaiting', reason, ...emptyData}` shape — the same empty state the UI already
renders (`<Empty>`, `nf()` → "—", disabled buttons). To connect a real backend, replace
the bodies of these functions with `fetch()` calls; nothing else in the app should need
to change. Two of them (`listScenarios`, `listSavedRuns`) don't have a matching endpoint
in the current contract yet — check with whoever owns `docs/handoff_contract.md` before
inventing one.

## What's intentionally non-functional right now

- **Every upload/import button** (DEM, hydrograph CSV, exposure GeoJSON, observed
  extent, SPH/Delft3D result import) is visibly present but `disabled`. Their parsers
  were removed along with the code paths that consumed their output (the in-browser
  solver, the demo exposure inventory). Re-enabling one means deciding where its parsed
  result should live — almost certainly a call into `source.ts`, not client-side state.
- **"Download for offline" / "Prepare offline workspace"** are disabled the same way;
  the IndexedDB + service-worker caching they drove is gone.
- **"Generate prepared scenarios"** (site onboarding) is disabled until a DEM is
  connected — which, per the point above, currently never happens.
- The **SPH particle tank** (Compare Models → "Educational Explainer") is the one piece
  of the original prototype kept fully working as-is. It's self-contained (no data
  dependency) and is now labelled "Educational Explainer" everywhere it's named, so it
  can't be mistaken for a project SPH result.

## Preview mode (design/target-state-preview branch only)

Set `VITE_DATA_MODE=preview` (e.g. in `.env.local`, or `VITE_DATA_MODE=preview npm run dev`) to
serve every `source.ts` function from the fixtures in `src/data/preview/*.json` instead of the
live API or `VITE_USE_MOCKS` contract examples. This exists only on `design/target-state-preview`
to demonstrate the finished UI before the real M1–M7 pipeline produces this data; the root
`README.md` "Preview mode" section explains the honesty rules (banner, watermark, provenance
stamp, caveat) every fixture follows, and `tests/frontend/test_preview_fixtures.py` enforces them
plus schema validity. `src/data/preview/manifest.json` is the single source of truth mapping each
fixture file to the contract schema it must validate against — both that test and
`src/data/preview/index.ts` (the router `source.ts` calls into) read it.

Default mode (`VITE_DATA_MODE` unset, or anything other than `'preview'`) is untouched: every
`source.ts` function's original code path runs unchanged, so this mode adds a data source, it
doesn't modify the existing ones. `visual/playwright.config.js` has a `preview` project (a second
dev server on :5174 with `VITE_DATA_MODE=preview`) with its own baselines under
`visual/tests/__screenshots__/preview/`, run with `npx playwright test --project=preview`; the
existing `default` project and its baselines are unaffected.

## Docs

| File | What it is |
|---|---|
| `STYLE_GUIDE.md` | Colour palette, spacing, components — the current shell |
| `API_USAGE.md` | Every data need, where it's routed through `source.ts`, and what's disabled and why |
| `../docs/progress.md` | The strip's history: what was removed, group by group, and what's left to connect |
| `../docs/handoff_contract.md` | The real API this app should eventually call |
