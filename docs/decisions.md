# Team decisions

## 2026-09-24 — Site config schema: YAML v1 vs contract §3.1 (PENDING team decision)

**Status:** pending — needs agreement from all module owners (contract §9) before the contract is changed.

`backend/shared/site_config.py` validates the format actually used in `sites/template.yaml` and
`sites/teesta.yaml` (`schema_version: 1`), **not** `docs/handoff_contract.md` §3.1. The contract has not
been edited. Differences to resolve:

| Topic | sites/*.yaml (v1, what the loader accepts) | contract §3.1 |
|---|---|---|
| Version key | `schema_version: 1` | `contract_version: 0.1.0` |
| Site id / name | `site: {id, name, region, river}` | top-level `site_id`, `name`, `state` |
| CRS | `crs.utm_epsg` as a SourcedValue | `crs_epsg` plain int |
| Domain keys | `far_field` / `near_field` | `farfield` / `nearfield` |
| Extent | `bbox` (SourcedValue) | `bbox_lonlat` (SourcedValue) |
| Resolution | `grid_resolution` (SourcedValue, m) | `cell_size_m` plain setting ⚙️ |
| Inflow point | `inflow: {from, location}` per domain | not in §3.1 |
| Dam id | bare slug (`south_lhonak`) | `<site_id>__<slug>` (§1.7) |
| POI id / type key | `id`, `category` (village, dam, bridge, hospital) | `poi_id` `<site>__poi__<slug>`, `kind` (adds town, school, …) |
| Dam kinds | moraine_dammed_lake, embankment_dam, concrete_dam, landslide_dam | natural_moraine, natural_landslide, embankment, cfrd, concrete, barrage |
| Breach input names | `breach_inputs.water_volume_above_invert`, … (no unit suffix) | `water_volume_above_breach_invert_m3`, … (flat, suffixed) |
| Enum values | `O/P`, `H/M/L` | `overtopping/piping`, `high/medium/low` |
| Units | `m^3` | `m3` (§1.1 suffix style) |
| `source` | free-text citation | `src_NNN` ID from docs/data_sources.md |
| `status` | `sourced` \| `placeholder` | adds `assumed` |
| Missing in v1 | — | `dem`, `landcover`, `cascade`, `thresholds`, `simulation`, `recheck`, `demo_mode`, `emulator_inputs`, `crest_elevation_m`, `reservoir_storage_m3`, `lake_area_m2`, `volume_elevation`, `equations_applicable`, `imposed_ranges` |
| Events | full `events` objects in the site file | list of event ids; details in docs/events/ |

Also found:
- `sites/teesta.yaml` refers to `sites/_template.yaml`; the file is `sites/template.yaml`.
- The repo has an empty `contract/` folder; CLAUDE.md and the contract say `contracts/`.

**Decide:** either migrate the YAML to §3.1 (and update the loader), or amend §3.1 to v1 (bump `contract_version`).
