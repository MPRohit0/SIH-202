# Frontend API and data usage

The only HTTP boundary is [`src/data/api.ts`](src/data/api.ts). It implements the
REST routes in `../docs/handoff_contract.md` §5 and imports mock payloads directly
from `../contracts/examples/` and `../contracts/styles.json`; the fixture files are
the contract examples, so they stay in sync with the source of truth. UI code should
use `src/data/source.ts`, never call `fetch()` directly.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `VITE_USE_MOCKS` | `false` | When `true`, JSON endpoints return cloned contract example JSON without making a network request. |
| `VITE_API_BASE_URL` | `http://localhost:8000/api/v1` | Backend API base URL. |

Example: `VITE_USE_MOCKS=true npm run dev`.

## Route coverage

`api` exposes health, styles, sites, site detail/create/recheck/rerun, jobs, flood
query/poll, timeline, extent GeoJSON, impact, compare, validation, historical
validation, export, GEE read/refresh, 3D scene metadata and static files. `request()`
handles JSON errors using the contract error envelope and throws `ApiError`; raw
file/export responses use `fetch()` because their contract responses are binary.

The flood mock uses `flood_query_response.example.json`, and mock POST calls use the
corresponding contract request/accepted examples. Other mock routes use their named
example JSON. No route or response shape is invented for scenario listing or saved
runs: neither has a REST endpoint in the current contract, so those legacy UI seams
continue to return empty states.

## Current UI adapter limits

The API client returns contract payloads unchanged. `source.ts` retains a small
compatibility adapter for the current canvas UI, whose `Grid` and `Result` types
require decoded raster arrays that the contract supplies as files/URLs. Those data
cannot be converted honestly without loading the corresponding scene and layer
files, so unsupported legacy values remain `null` and render as empty states. The
impact view still computes its old summary totals from local assets and result arrays;
they are not contract `Estimate` objects and must be replaced when that view is wired
to `/impact/{query_id}`.

`getTerrain()` can read site metadata but does not manufacture a raster grid from
the contract's scene metadata. The existing scenario list, saved-run list and
save-run functions remain empty because no matching routes exist. Contract APIs
are ready for screens to consume as they move off the legacy canvas models.
