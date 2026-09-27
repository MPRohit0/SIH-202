# Frontend API and data usage

The only HTTP boundary is [`src/data/api.ts`](src/data/api.ts). It implements the
REST routes in `../docs/handoff_contract.md` §5 and imports mock payloads directly
from `../contracts/examples/` and `../contracts/styles.json`; the fixtures are the
contract examples. UI code should use `src/data/source.ts`, never call `fetch()`
directly.

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
example JSON. Scenario listing and Saved Runs have no REST endpoint in the current
contract, so their legacy UI seams return empty states.

## Current UI adapter limits

Flood Summary, Impact Analysis, Model Comparison, Monitoring/GEE, Playback/Timeline,
and Exports consume their corresponding contract responses through `source.ts`. The
current canvas `Grid` and `Result` types require decoded raster arrays; the contract
supplies raster/file references instead. `getTerrain()` therefore leaves the legacy
grid empty, and the map does not yet render the returned flood raster layers.

`GET /sites` and `GET /jobs/{job_id}` preserve API errors for shell/onboarding error
handling. Site creation remains unavailable from the current form: it does not collect
enough fields to construct the complete `site_config` required by `POST /sites`.

M0 is not a live scientific backend for most result endpoints yet. Its implementation
serves contract examples when flood, impact, validation, comparison, or timeline
results are absent. Accessible file URLs can likewise resolve to generated mock or
zero-filled files. A successful response must not be described as a fresh model result
unless M0 has real backing data for that response.
