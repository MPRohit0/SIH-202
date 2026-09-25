# SIH26 — Data Hand-off Contract

**Version:** 0.1.0 (DRAFT) · **Status:** review as a team, then freeze before playbook step M0-1 **Repo location:** `docs/handoff_contract.md` · **Machine-readable version:** `contracts/` (JSON Schemas generated from this file in M0-1)

---

## 0. Rules that apply everywhere

1. This document and `contracts/` define every piece of data that passes between modules. If code and contract disagree, the code is wrong.
2. A module reads another module's data **only** through the files, functions and endpoints defined here — never by reaching into its internals.
3. Every JSON payload and metadata file carries `"contract_version": "0.1.0"`.
4. Every numeric **fact** (a dam height, a lake volume) is a `SourcedValue` (§2.1). Every numeric **result** is an `Estimate` (§2.2). Settings (thresholds, frequencies) are plain values documented in `docs/decisions.md`.
5. Any result that depends on a `placeholder` input sets `"has_placeholders": true` and lists the fields in `"placeholder_fields"`. The UI must show this.
6. Predicted and observed values are never mixed in one field: every `Estimate` says which it is (`kind`).
7. The API returns SI units. Converting to km, km², minutes or clock time is the frontend's job.
8. Contract changes follow §9. No silent changes.

---

## 1. Global conventions

### 1.1 Units

|Quantity|Unit|Key suffix|Notes|
|---|---|---|---|
|Length, depth, elevation|m|`_m`|elevations carry a `vertical_datum` in metadata|
|Area|m²|`_m2`||
|Volume|m³|`_m3`||
|Discharge|m³/s|`_m3s`||
|Velocity|m/s|`_ms`||
|Duration, arrival time|s|`_s`|relative to t0 (§1.2)|
|Probability|0–1|`p_` prefix|never percent in data|
|Percent (errors, changes)|%|`_pct`||
|Population|persons|`_persons`||
|Money|INR|`_inr`||
|Manning's n|s/m^(1/3)|`manning_n`||

### 1.2 Time

- **t0 = the moment the first (most upstream) breach starts forming.** Every hydrograph, arrival time and timeline frame is in seconds since t0. For a cascade, downstream breaches are also measured from the upstream t0.
- Timestamps (creation times, satellite acquisitions) are ISO 8601 in UTC with `Z`, e.g. `2026-09-24T10:15:00Z`. The UI may display IST.
- Clock times of arrival are shown only if the user supplies a breach start timestamp.

### 1.3 Coordinate systems

|Use|CRS|
|---|---|
|All computation, rasters, internal vectors|the site's UTM zone: Teesta **EPSG:32645**, Rishi Ganga **EPSG:32644** (stored as `crs_epsg` in the site config)|
|Everything sent to the frontend, GeoJSON, KML|**EPSG:4326**, coordinate order **lon, lat** (RFC 7946)|
|Leaflet image-overlay bounds|`bounds_latlng: [[south_lat, west_lon], [north_lat, east_lon]]` — note the lat-first order Leaflet expects|
|SPH geometry (STL, glTF)|local metric frame: x = UTM x − frame origin x, y = UTM y − frame origin y, z = elevation (m). Origin stored in `nearfield_frame.json`|

- Vertical datum: record it for every DEM (`vertical_datum` in `terrain/provenance.json`). SRTM uses EGM96 and Copernicus DEM uses EGM2008; check CartoDEM's documentation. Never mix DEMs without converting.

### 1.4 Canonical grids

Each site has two grids, written by M1, and **every raster in the project is aligned to one of them** (same CRS, transform and shape).

`grid.json` (far-field) and `grid_nearfield.json` (near-field):

```jsonc
{
  "contract_version": "0.1.0",
  "site_id": "teesta",
  "grid_id": "farfield",            // "farfield" | "nearfield"
  "crs_epsg": 32645,
  "origin_x": 500000.0,            // upper-left corner, metres  (ILLUSTRATIVE)
  "origin_y": 3100000.0,
  "cell_size_m": 30.0,
  "width": 2000,                   // columns
  "height": 1500,                  // rows
  "nodata": -9999.0,
  "pixel_is": "area"
}
```

- The near-field grid's origin lies on a far-field cell corner, and its cell size divides the far-field cell size exactly, so near-field cells nest inside far-field cells.
- Resampling onto a grid: bilinear for continuous terrain, nearest for categories, and the method used by M3/M4 converters is recorded in `run_meta.json`.

### 1.5 Nodata, dry cells and thresholds

- Float rasters use `nodata = -9999.0`. Categorical rasters use `uint8` with `nodata = 255`.
- `domain_mask.tif` (uint8: 1 inside model domain, 0 outside) is the **only** way to tell "outside the domain" from "inside but never wet".
- Depth and velocity: dry cells inside the domain are `0.0`, outside the domain are nodata.
- Arrival time: nodata where water never exceeds the arrival threshold during the simulation **or** the cell is outside the domain; use `domain_mask` to tell them apart.
- Thresholds (site config `thresholds`):

| Setting         | Default | Meaning                                                                     |
| --------------- | ------- | --------------------------------------------------------------------------- |
| `extent_m` ⚙️   | 0.3     | depth above which a cell counts as flooded (extent, IoU, F1, HIGH/POSSIBLE) |
| `arrival_m` ⚙️  | 0.1     | depth whose first exceedance defines arrival time (early-warning oriented)  |
| `high_p` ⚙️     | 0.9     | p_inundation at or above → HIGH-CONFIDENCE FLOOD                            |
| `possible_p` ⚙️ | 0.1     | p_inundation at or above (and below `high_p`) → POSSIBLE FLOOD EXTENSION    |

### 1.6 File formats

|Data|Format|
|---|---|
|Rasters|GeoTIFF, float32 (categories uint8), tiled, LZW-compressed, CRS and nodata set|
|Internal vectors (UTM)|GeoPackage `.gpkg`|
|Vectors for the frontend and exports|GeoJSON (EPSG:4326)|
|Tables / time series|CSV, UTF-8, header row, units in column names (`t_s,q_m3s`)|
|Structured data|JSON, UTF-8, `snake_case` keys|
|Site configs|YAML|
|Map overlays|PNG with transparency|
|3D meshes|glTF binary `.glb`|
|Trained emulator|`.npz` (PCA) + `.joblib` (GPs) + `manifest.json`|

### 1.7 IDs

|ID|Pattern|Example|
|---|---|---|
|`site_id`|`^[a-z][a-z0-9_]{2,31}$`|`teesta`, `rishiganga`|
|`dam_id`|`<site_id>__<slug>`|`teesta__south_lhonak`, `teesta__teesta3`|
|`scenario_id`|`<site_id>_s<NNN>` (design), `<site_id>_hist_<event>` (historical), `<site_id>_demo_s<NNN>` (demo mode), `<site_id>_n_<slug>` (named extra)|`teesta_s007`, `teesta_hist_2023`|
|`run_id`|`<scenario_id>__<model>`|`teesta_s007__delft3d`, `teesta_s003__sph`|
|`model`|`delft3d` \| `sph`||
|`query_id`|`q_<YYYYMMDDTHHMMSSZ>_<6 hex>`|`q_20260924T101500Z_3fa9c1`|
|`job_id`|`job_<YYYYMMDDTHHMMSSZ>_<6 hex>`|`job_20260924T101500Z_b17e02`|
|`event_id`|`<site-or-place>_<year>`|`teesta_2023`, `chamoli_2021`|
|`poi_id`|`<site_id>__poi__<slug>`|`teesta__poi__chungthang`|
|`input name`|fixed list in §3.3|`breach_width_m`|

### 1.8 Folder layout (`data/` is gitignored)

```
sites/<site_id>.yaml                      # site configs (in git)
contracts/                                # JSON Schemas + examples + styles.json (in git)
data/
  registry.sqlite                         # scenarios, runs, jobs, queries (§4.5)
  <site_id>/
    raw/                                  # untouched downloads (M1, M6)
    terrain/                              # M1 outputs (§4.1)
    breach/                               # M2 outputs (§4.2)
      hydrographs/
    design/scenario_design.json           # §4.3
    runs/<run_id>/                        # M3/M4 outputs (§4.4)
      case/  raw/  summary/  summary_nearfield/  surfaces/
      timeseries.csv  run_meta.json  log.txt
    emulator/<model>/                     # M5 trained model + validation (§4.6)
      validation/
    exposure/                             # M6 inputs (§4.7)
    gee/                                  # M7 outputs (§4.8)
      imagery/  observed/  fallback/
    events/<event_id>/validation.json     # M5 historical validation
    queries/<query_id>/                   # per-query results
      result.json  impact.json  layers/  timeline/  exports/
```

---

## 2. Shared JSON building blocks

### 2.1 SourcedValue — every input fact

```jsonc
{ "value": 123.4, "unit": "m", "source": "src_014", "status": "sourced", "note": "crest elevation from EAP" }
```

|Field|Type|Rule|
|---|---|---|
|`value`|number \| array \| null|`null` allowed only with `status: placeholder`|
|`unit`|string|from §1.1|
|`source`|string \| null|ID of an entry in `docs/data_sources.md` (e.g. `src_014`); required when `sourced`|
|`status`|`sourced` \| `placeholder` \| `assumed`|`assumed` = team assumption, justified in `note` and `docs/decisions.md`|
|`note`|string|optional|

### 2.2 Estimate — every result number

```jsonc
{
  "value": 2340.0,            // central value (median unless stated in "basis")
  "low": 1800.0,
  "high": 3100.0,
  "unit": "s",
  "interval": "P10-P90",      // "P10-P90" | "method_range" | "zone_range" | "none"
  "kind": "predicted",        // "predicted" | "observed" | "input"
  "confidence": "MODERATE",   // "HIGH" | "MODERATE" | "LOW" | null
  "basis": "median over 500 Monte Carlo samples"
}
```

- `method_range` = spread between two empirical methods (M2). `zone_range` = HIGH-only vs HIGH+POSSIBLE (M6 exposure counts).
- Observed values use `kind: "observed"`, `confidence: null`, and a `source`.

### 2.3 Confidence

```jsonc
{
  "level": "MODERATE",                  // HIGH | MODERATE | LOW
  "components": {
    "validation_skill": "GOOD",         // GOOD | FAIR | POOR | UNKNOWN   (from LOOCV)
    "query_coverage": "EDGE",           // INSIDE | EDGE | OUTSIDE        (query vs training range)
    "spread": "MEDIUM"                  // NARROW | MEDIUM | WIDE         (P10–P90 width vs median)
  },
  "reason_key": "conf_edge_of_training_range"
}
```

- Rule (defaults, thresholds in `docs/m5_spec.md`): all three good → HIGH; one weak → MODERATE; two or more weak, `OUTSIDE`, empirical fallback, or demo mode → LOW.
- `reason_key` refers to a message in `frontend/src/content/ui_text.json`.

### 2.4 Caveat

```jsonc
{ "id": "clear_water", "severity": "warning", "text_key": "caveat_clear_water" }
```

Standard caveat IDs: `moraine_extrapolation`, `concrete_dam_imposed`, `clear_water`, `failure_time_uncertain`, `mass_flow_approximation`, `dem_resolution`, `outside_trained_range`, `empirical_fallback`, `demo_mode`, `placeholder_data`, `library_outdated`, `observed_data_sparse`. Severity: `info` | `warning` | `critical`.

### 2.5 Provenance

```jsonc
{
  "method": "gp_emulator",     // gp_emulator | empirical_fallback | delft3d_direct | sph_direct | observed
  "contract_version": "0.1.0",
  "code_version": "a1b2c3d",   // git commit
  "solver_versions": { "delft3d": "<version string>", "dualsphysics": "<version string>" },
  "run_ids": ["teesta_s001__delft3d", "..."],
  "emulator_manifest": "data/teesta/emulator/delft3d/manifest.json",
  "data_sources": ["src_003", "src_014"],
  "parameters": { "n_samples": 500, "seed": 42 },
  "created_at": "2026-09-24T10:15:00Z"
}
```

### 2.6 LayerRef — a map layer the frontend can show

```jsonc
{
  "layer_id": "p_inundation",          // see §4.6 layer list
  "label_key": "layer_p_inundation",
  "type": "raster_png",                // raster_png | geojson
  "url": "/api/v1/flood/q_20260924T101500Z_3fa9c1/layers/p_inundation.png",
  "bounds_latlng": [[27.60, 88.30], [28.00, 88.80]],
  "style_id": "p_inundation",          // key in contracts/styles.json
  "unit": null,
  "available": true                    // false while a partial result is still computing
}
```

### 2.7 Error (all endpoints)

```jsonc
{ "error": { "code": "site_not_ready", "message": "Emulator for 'teesta' is not trained yet.", "details": {} } }
```

HTTP status: 400 bad request, 404 not found, 409 conflict (e.g. site still onboarding), 422 validation error, 500 internal, 503 dependency unavailable (e.g. live GEE).

---

## 3. Site config — `sites/<site_id>.yaml`

Owned by the team. Read by every module. Values that are facts use `SourcedValue` (written inline as `{value, unit, source, status}`).

### 3.1 Structure

```yaml
contract_version: 0.1.0
site_id: teesta
name: "Teesta — South Lhonak GLOF to Teesta III"
state: Sikkim
crs_epsg: 32645

domains:
  farfield:
    bbox_lonlat: {value: null, unit: deg, source: null, status: placeholder}   # [min_lon, min_lat, max_lon, max_lat]
    cell_size_m: 30            # ⚙️
  nearfield:
    bbox_lonlat: {value: null, unit: deg, source: null, status: placeholder}
    cell_size_m: 2             # ⚙️ must divide farfield cell size exactly

dem:
  source: copernicus_glo30     # ⚙️ srtm_gl1 | copernicus_glo30 | cartodem (decided after M1-2)
landcover:
  source: esa_worldcover       # esa_worldcover | bhuvan_lulc

dams:                          # upstream first
  - dam_id: teesta__south_lhonak
    name: "South Lhonak moraine dam"
    kind: natural_moraine      # natural_moraine | natural_landslide | embankment | cfrd | concrete | barrage
    order: 1
    location_lonlat:                         {value: null, unit: deg, source: null, status: placeholder}
    breach_location_lonlat:                  {value: null, unit: deg, source: null, status: placeholder}
    dam_height_m:                            {value: null, unit: m,  source: null, status: placeholder}
    crest_elevation_m:                       {value: null, unit: m,  source: null, status: placeholder}
    water_volume_above_breach_invert_m3:     {value: null, unit: m3, source: null, status: placeholder}  # Vw
    water_height_above_breach_invert_m:      {value: null, unit: m,  source: null, status: placeholder}  # hw
    breach_height_m:                         {value: null, unit: m,  source: null, status: placeholder}  # hb
    average_embankment_width_m:              {value: null, unit: m,  source: null, status: placeholder}  # Wave
    reservoir_storage_m3:                    {value: null, unit: m3, source: null, status: placeholder}  # S
    lake_area_m2:                            {value: null, unit: m2, source: null, status: placeholder}
    dam_type_code: {value: null, unit: null, source: null, status: placeholder}   # HD | CD | FD | ZD (Xu & Zhang classes)
    failure_mode:  {value: null, unit: null, source: null, status: placeholder}   # overtopping | piping
    erodibility:   {value: null, unit: null, source: null, status: placeholder}   # high | medium | low
    volume_elevation:
      method: area_volume_relation   # surveyed_curve | area_volume_relation
      relation: null                 # ⚙️ name of the published relation, source in data_sources.md
      points: []                     # [[elevation_m, volume_m3], ...] when surveyed_curve
    equations_applicable: true       # false → use imposed_ranges (e.g. concrete dams)
    imposed_ranges: null             # {peak_discharge_m3s: [lo, hi], breach_width_m: [lo, hi], failure_time_s: [lo, hi]} with sources
    initial_water_level_m: null      # for reservoirs inside the Delft3D domain

  - dam_id: teesta__teesta3
    name: "Teesta III (Chungthang)"
    kind: null                       # ⚙️ verify dam type from sources before choosing
    order: 2
    # ...same fields as above...

cascade:
  approach: null                     # ⚙️ dambreak_structure | two_stage_imposed
  trigger:                           # only for two_stage_imposed
    type: inflow_threshold
    value_m3s: {value: null, unit: m3s, source: null, status: placeholder}

points_of_interest:
  - poi_id: teesta__poi__chungthang
    name: Chungthang
    kind: town                       # village | town | dam | bridge | hospital | school | hydropower | other
    location_lonlat: {value: null, unit: deg, source: null, status: placeholder}

emulator_inputs: []                  # filled after M2 — see §3.3

thresholds: {extent_m: 0.3, arrival_m: 0.1, high_p: 0.9, possible_p: 0.1}   # ⚙️

simulation:
  delft3d: {duration_s: null, map_output_interval_s: 60, base_flow_m3s: {value: null, unit: m3s, source: null, status: placeholder}}   # ⚙️
  sph:     {time_window_s: null, dp_m: null, scenarios: []}   # ⚙️ scenario_ids that get SPH runs

recheck:
  frequency_days: 90                 # ⚙️ user-editable in the UI
  lake_area_change_threshold_pct: 10 # ⚙️

demo_mode:
  cell_size_m: 90                    # ⚙️
  n_scenarios: 6                     # ⚙️
  duration_s: null                   # ⚙️

events: [teesta_2023]
```

### 3.2 Rules

- `rishiganga.yaml` has the same structure. Its dams list is the Raunthi Gad landslide lake (`kind: natural_landslide`); the 2021 event is an `event` entry, **not** a dam.
- A config may be loaded with placeholders, but every result then carries `has_placeholders: true`.
- The loader (F3) rejects any fact missing `unit`, `source` (when `sourced`) or `status`.

### 3.3 Emulator inputs

Filled per site after M2 is done. Only these names are allowed:

|Name|Unit|Applies to|Notes|
|---|---|---|---|
|`water_volume_m3`|m³|a dam|use either this or `initial_water_level_m`, not both|
|`initial_water_level_m`|m|a dam||
|`breach_width_m`|m|a dam|final average breach width|
|`failure_time_s`|s|a dam|deliberately wide range|
|`manning_multiplier` ⚙️|–|whole domain|optional; scales the roughness raster (e.g. 0.8–1.25) to capture roughness uncertainty|

```yaml
emulator_inputs:
  - name: breach_width_m
    dam_id: teesta__south_lhonak
    range: {low: null, high: null, unit: m, basis: "M2 dual-method range", source: "breach/breach_params.json"}
    slider: {positions: [0, 10], mapping: linear}   # linear | log (log suggested for failure_time_s ⚙️)
    default: null                                   # value used when not set in unknown-breach mode is "sample full range"
```

Slider mapping: linear → `value = low + (p / 10) × (high − low)`; log → the same on `ln(value)`.

---

## 4. Module outputs

### 4.1 M1 — Terrain → `data/<site_id>/terrain/`

**Inputs:** site config (`domains`, `dem`, `landcover`, `dams` for burn-in), raw downloads, `data/manning_table.csv`.

|File|Type|Content|Consumers|
|---|---|---|---|
|`grid.json`, `grid_nearfield.json`|JSON|§1.4|everyone|
|`dem.tif`|float32, m|conditioned DEM with dams/reservoirs burned in, lake masked (not filled)|M3, M4, M5 fallback, M0-6|
|`dem_nearfield.tif`|float32, m|same on the near-field grid|M4|
|`landcover.tif`|uint8|class codes (legend in `provenance.json`)|M1, M6|
|`roughness.tif`|float32|Manning's n|M3, M5 fallback|
|`hand.tif`|float32, m|height above nearest drainage|M5 fallback|
|`domain_mask.tif`|uint8|1 = model domain (valley corridor)|everyone|
|`domain.gpkg`|polygon|model domain|M3|
|`centreline.gpkg`|linestring|main channel, `chainage_m` measured downstream from the most upstream breach|M5, M6|
|`chainage_samples.csv`|CSV|`chainage_m,x_m,y_m,bed_elev_m` every cell size|M5 timeline, M6|
|`pois.gpkg`|points|POIs from site config snapped to grid: `poi_id,name,kind,chainage_m,dist_to_channel_m,row,col`|M3, M4, M5, M6|
|`nearfield.stl`|STL|near-field terrain in the SPH frame (§1.3)|M4|
|`nearfield_frame.json`|JSON|`{crs_epsg, origin_x, origin_y, units: "m"}`|M4, M0-6|
|`provenance.json`|JSON|sources, versions, `vertical_datum`, processing steps, burn-in details|M6 report|

`manning_table.csv`: `class_code,class_name,manning_n,manning_n_low,manning_n_high,source`.

### 4.2 M2 — Breach engine → `data/<site_id>/breach/`

**Inputs:** `dams` from the site config.

**`breach_params.json`**

```jsonc
{
  "contract_version": "0.1.0",
  "site_id": "teesta",
  "has_placeholders": true,
  "placeholder_fields": ["dams[0].water_volume_above_breach_invert_m3"],
  "dams": [
    {
      "dam_id": "teesta__south_lhonak",
      "equations_applicable": true,
      "inputs_used": { "Vw_m3": 0.0, "hw_m": 0.0, "hb_m": 0.0, "hd_m": 0.0, "Wave_m": 0.0,
                       "dam_type_code": "HD", "failure_mode": "overtopping", "erodibility": "high" },
      "parameters": {
        "peak_discharge_m3s": {
          "methods": {
            "F16":  { "value": 0.0, "in_valid_range": true },
            "XZ9":  { "value": 0.0, "in_valid_range": true },
            "Z20":  { "value": 0.0, "in_valid_range": false },
            "DFM_updated": { "value": 0.0 },
            "DFM_2024":    { "value": 0.0 }
          },
          "selected_pair": ["DFM_updated", "DFM_2024"],
          "range": { "low": 0.0, "high": 0.0, "unit": "m3s", "interval": "method_range" }
        },
        "breach_width_m":  { "...": "same shape; pair DFM_updated + XZ9" },
        "failure_time_s":  { "...": "same shape; pair DFM_updated + F8; widened range ⚙️" }
      },
      "warnings": ["moraine_extrapolation"]
    }
  ],
  "provenance": { "method": "empirical", "code_version": "a1b2c3d", "data_sources": ["src_021"] }
}
```

- Method keys: `F95`, `F8`, `F16`, `XZ9`, `Z20`, `MCLM`, `DFM_updated`, `DFM_2024`. Pairs follow Azmi (2026).
- Dams with `equations_applicable: false` return `imposed_ranges` from the config, flagged with caveat `concrete_dam_imposed`.

**Hydrographs** — `hydrographs/<scenario_id>__<dam slug>.csv` + `.json` sidecar

```
t_s,q_m3s
0,0.0
10,12.5
...
```

Sidecar:

```jsonc
{
  "contract_version": "0.1.0",
  "scenario_id": "teesta_s007", "dam_id": "teesta__south_lhonak",
  "method": "breach_growth_weir",     // breach_growth_weir | triangular | imposed | equivalent_event
  "params": { "breach_width_m": 0.0, "failure_time_s": 0.0, "water_volume_m3": 0.0 },
  "dt_s": 10, "t_offset_s": 0,        // t_offset_s > 0 for downstream dams in a cascade
  "peak_q_m3s": 0.0, "time_to_peak_s": 0, "volume_m3": 0.0,
  "mass_balance_error_pct": 0.0,
  "peak_within_m2_range": true
}
```

**In-process function** (used by M0, M5 Monte Carlo, M3/M4 generators): `hydrograph(site_id: str, dam_id: str, params: dict) -> Hydrograph` returning `t_s`, `q_m3s` arrays and the sidecar fields.

### 4.3 Scenario design (M5 → M0, M3, M4) → `design/scenario_design.json`

```jsonc
{
  "contract_version": "0.1.0",
  "site_id": "teesta", "model": "delft3d",
  "method": "latin_hypercube", "seed": 42, "n": 30,
  "inputs": [ { "name": "breach_width_m", "dam_id": "teesta__south_lhonak", "low": 0.0, "high": 0.0, "unit": "m" } ],
  "scenarios": [ { "scenario_id": "teesta_s001", "kind": "design", "params": { "breach_width_m": 0.0, "failure_time_s": 0.0, "water_volume_m3": 0.0 } } ],
  "extra": [ { "scenario_id": "teesta_hist_2023", "kind": "historical", "params": {}, "source": "docs/events/teesta_2023.md" } ]
}
```

### 4.4 Run results (M3 and M4, identical schema) → `runs/<run_id>/`

**Inputs:** terrain (§4.1), hydrograph(s) (§4.2), scenario params (§4.3), simulation settings (site config).

|Path|Grid|Content|
|---|---|---|
|`summary/max_depth.tif`|far-field|m (Delft3D only)|
|`summary/max_velocity.tif`|far-field|m/s|
|`summary/arrival_time.tif`|far-field|s since t0, nodata = never / outside|
|`summary_nearfield/*.tif`|near-field|same three rasters; always for SPH, and for Delft3D runs listed in `simulation.sph.scenarios`|
|`summary/depth_snapshots/depth_t<seconds>.tif`|far-field|optional, for 3D view|
|`surfaces/t<seconds>.glb`|SPH frame|SPH water surfaces (SPH only)|
|`timeseries.csv`|–|`poi_id,t_s,depth_m,velocity_ms,wse_m` (long format)|
|`run_meta.json`|–|below|
|`case/`, `raw/`, `log.txt`|–|solver inputs, raw outputs, log (kept for provenance)|

`run_meta.json`

```jsonc
{
  "contract_version": "0.1.0",
  "run_id": "teesta_s007__delft3d", "scenario_id": "teesta_s007", "model": "delft3d",
  "status": "postprocessed",          // queued | running | completed | postprocessed | failed
  "solver_version": "<version string>",
  "resolution_m": 30, "dp_m": null, "particle_count": null, "peak_vram_mb": null,
  "sim_duration_s": 0, "wall_time_s": 0,
  "mass_balance_error_pct": 0.0,
  "thresholds": { "extent_m": 0.3, "arrival_m": 0.1 },
  "hydrographs": ["breach/hydrographs/teesta_s007__south_lhonak.csv"],
  "resampling": "linear interpolation from mesh cell centres",
  "warnings": [],
  "started_at": "2026-09-24T10:15:00Z", "finished_at": "2026-09-24T11:05:00Z"
}
```

### 4.5 Registry — `data/registry.sqlite`

|Table|Columns|
|---|---|
|`scenarios`|`scenario_id` PK, `site_id`, `kind` (design \| historical \| demo \| named), `params_json`, `created_at`|
|`runs`|`run_id` PK, `scenario_id`, `model`, `status`, `run_dir`, `meta_json`, `started_at`, `finished_at`, `error`|
|`jobs`|`job_id` PK, `kind` (onboarding \| campaign \| recheck \| rerun), `site_id`, `stage`, `progress_current`, `progress_total`, `progress_unit`, `eta_s`, `payload_json`, `created_at`, `updated_at`, `error`|
|`queries`|`query_id` PK, `site_id`, `request_json`, `status` (partial \| complete \| failed), `result_path`, `created_at`|

### 4.6 M5 — Emulator → `emulator/<model>/`, `queries/<query_id>/`

**Inputs:** registry + run results (§4.4–4.5), `breach_params.json`, site config, query requests.

**Trained model files**

|File|Content|
|---|---|
|`manifest.json`|`site_id, model, run_ids, inputs (names, ranges, scaling), outputs: {depth, velocity, arrival}: {transform, n_components, variance_explained, reconstruction_rmse}, kernel, length_scales[output][component][input], trained_at, code_version`|
|`pca_<output>.npz`|mean map, components, corridor cell indices|
|`gp_<output>.joblib`|fitted GPs, one per component|
|`validation/loocv.json`|below|
|`validation/*.png`|charts|

`validation/loocv.json`

```jsonc
{
  "contract_version": "0.1.0", "site_id": "teesta", "model": "delft3d", "n_runs": 30,
  "per_run": [ { "run_id": "teesta_s001__delft3d", "iou": 0.0, "f1": { "0.05": 0.0, "0.1": 0.0, "0.3": 0.0 },
                 "depth_rmse_wet_m": 0.0, "arrival_mae_s": 0.0, "velocity_mae_ms": 0.0,
                 "area_error_pct": 0.0, "coverage_90": 0.0 } ],
  "summary": {
    "extent":   { "iou_median": 0.0, "f1_0_3_median": 0.0, "area_error_pct_median": 0.0, "grade": "UNKNOWN" },
    "depth":    { "rmse_wet_m_median": 0.0, "grade": "UNKNOWN" },
    "arrival":  { "mae_s_median": 0.0, "grade": "UNKNOWN" },
    "velocity": { "mae_ms_median": 0.0, "grade": "UNKNOWN" },
    "coverage_90": 0.0
  },
  "baseline_linear": { "extent": { "iou_median": 0.0 }, "depth": { "rmse_wet_m_median": 0.0 }, "arrival": { "mae_s_median": 0.0 } },
  "grade_thresholds_ref": "docs/m5_spec.md"
}
```

**In-process function** `get_flood(site_id, model="delft3d", mode, inputs, n_samples=500, phase="full") -> FloodResult`

- `mode`: `scenario` (fixed inputs, sample GP uncertainty only) | `unknown_breach` (sample every input not given, across its range).
- `phase`: `median` (fast, central map only) | `full` (Monte Carlo layers + statistics).
- For a site without a trained emulator, returns the empirical fallback with `method: empirical_fallback`, confidence LOW.

**Layers** written to `queries/<query_id>/layers/` (GeoTIFF, far-field grid; M0-5 renders PNGs):

|`layer_id`|Content|Phase|
|---|---|---|
|`depth_p50`|median max depth (m)|median, full|
|`arrival_p50`|median arrival (s)|median, full|
|`velocity_p50`|median max velocity (m/s)|median, full|
|`p_inundation`|fraction of samples with depth > `extent_m`|full|
|`extent_class`|uint8: 0 dry, 1 POSSIBLE, 2 HIGH|full|
|`depth_p10`, `depth_p90`|m|full|
|`arrival_p10`, `arrival_p90`|s|full|
|`velocity_p90`|m/s|full|

Summary statistics are computed **per Monte Carlo sample**, then summarised across samples (e.g. `inundated_area_m2` = area with depth > `extent_m` in each sample → P10/P50/P90).

**Historical validation** → `events/<event_id>/validation.json` — shape in §5 (`/validation/{site_id}?event=`).

### 4.7 M6 — Impact & export → `queries/<query_id>/impact.json`, `exports/`

**Inputs:** M5 layers + result, `exposure/` data, `pois.gpkg`, styles.

**Exposure inputs** — `data/<site_id>/exposure/`

|File|Content|
|---|---|
|`population.tif`|WorldPop persons per cell, resampled to far-field grid (sum-preserving)|
|`buildings.gpkg`, `roads.gpkg`, `facilities.gpkg`, `places.gpkg`|OSM extracts (`osm_id`, `kind`, `name`)|
|`hydropower.gpkg`|hand-made list with `source`|
|`damage_curves.csv`|`asset_class,depth_m,damage_fraction,source`|
|`asset_values.csv`|`asset_class,value_inr_per_unit,unit,source,status`|
|`provenance.json`|sources, dates, coverage report summary|

**`impact.json`**

```jsonc
{
  "contract_version": "0.1.0", "query_id": "q_20260924T101500Z_3fa9c1", "site_id": "teesta",
  "population_persons": { "value": 0, "low": 0, "high": 0, "unit": "persons", "interval": "zone_range", "kind": "predicted",
                          "basis": "value = Σ p × pop; low = HIGH zone; high = HIGH + POSSIBLE" },
  "assets": {
    "buildings":  { "high": 0, "possible": 0 },
    "roads_m":    { "high": 0.0, "possible": 0.0 },
    "bridges":    { "high": 0, "possible": 0 },
    "hospitals":  { "high": 0, "possible": 0 },
    "schools":    { "high": 0, "possible": 0 },
    "cropland_m2":{ "high": 0.0, "possible": 0.0 },
    "hydropower": [ { "name": "Teesta III", "zone": "high", "depth_m": { "value": 0.0, "low": 0.0, "high": 0.0, "unit": "m", "interval": "P10-P90", "kind": "predicted" } } ]
  },
  "loss_inr": { "value": 0, "low": 0, "high": 0, "unit": "INR", "interval": "P10-P90", "kind": "predicted",
                "by_asset_class": {}, "assumptions": ["damage curves: src_031", "asset values: src_032"] },
  "warning_table": [
    { "poi_id": "teesta__poi__chungthang", "name": "Chungthang", "kind": "town", "chainage_m": 0.0,
      "zone": "high",                                   // high | possible
      "p_inundation": 0.0,
      "arrival_s":   { "value": 0, "low": 0, "high": 0, "unit": "s",  "interval": "P10-P90", "kind": "predicted", "confidence": "MODERATE" },
      "depth_m":     { "value": 0.0, "low": 0.0, "high": 0.0, "unit": "m", "interval": "P10-P90", "kind": "predicted" },
      "velocity_ms": { "value": 0.0, "low": 0.0, "high": 0.0, "unit": "ms", "interval": "P10-P90", "kind": "predicted" } }
  ],
  "not_affected_poi_count": 0,
  "data_coverage_notes": ["OSM building coverage is sparse in this valley"],
  "has_placeholders": true, "placeholder_fields": [],
  "caveats": [], "provenance": {}
}
```

- `warning_table` includes POIs in HIGH or POSSIBLE zones, sorted by `arrival_s.value` ascending.

**Exports** — `exports/<site_id>_<query_id>_<name>.<ext>`

|Format|Content|
|---|---|
|`.zip` (shapefile)|`extent` polygons (HIGH/POSSIBLE), `depth_classes`, `isochrones`, `pois_warning` points; all sidecars (`.shp .shx .dbf .prj .cpg`)|
|`.kml`|same layers, EPSG:4326, one Folder per layer, styled from `styles.json`, pop-up descriptions with estimates and caveats|
|`.geojson`|same layers, one FeatureCollection per layer|
|`.pdf`|map, summary, warning table, impacts, confidence, caveats, provenance|

Shapefile field names (≤ 10 characters):

|Field|Meaning|
|---|---|
|`zone`|`high` / `possible`|
|`p_inund`|p_inundation|
|`dep_p10`, `dep_p50`, `dep_p90`|depth (m)|
|`arr_p10`, `arr_p50`, `arr_p90`|arrival (s)|
|`vel_p50`, `vel_p90`|velocity (m/s)|
|`conf`|HIGH / MODERATE / LOW|
|`method`|gp_emulator / empirical_fallback|
|`site_id`, `query_id`|IDs|
|`iso_s`|isochrone time (s)|
|`dep_class`|depth class label|
|`has_ph`|1 if placeholders involved|

### 4.8 M7 — GEE → `data/<site_id>/gee/`

**Inputs:** site config (AOI, lake location, events), chosen scene IDs.

|File|Content|
|---|---|
|`lake_area.csv`|`date,area_m2,method,cloud_pct,scene_ids` (`method`: `s2_water_index` \| `s1_threshold`)|
|`lake_latest.geojson`|latest lake polygon, properties `date, area_m2, method`|
|`rainfall.csv`|`date,precip_mm,dataset,aggregation` (`dataset`: `chirps` \| `gpm_imerg`)|
|`imagery/<event_id>_<pre\|post>_<YYYYMMDD>.png/.tif`|RGB composites for the AOI|
|`observed/<event_id>_observed.geojson`|observed flood path, properties `event_id, method (manual_digitized \| change_detection), imagery_ref, digitized_by, date, kind: observed`|
|`fallback/*.png`|screenshots used if live and cache both fail|
|`gee_meta.json`|per product: `dataset, scene_ids, acquisition_dates, cloud_pct, fetched_at, source (live \| cache \| screenshot_fallback)`|
|`recheck.json`|`{site_id, checked_at, latest_area_m2, reference_area_m2, change_pct, threshold_pct, outdated, reason}` — `reference_area_m2` = lake area when the library was trained|

---

## 5. REST API (M0 ↔ M8)

Base URL: `http://localhost:8000/api/v1`. JSON unless stated. Errors per §2.7. CORS allows the Vite dev server (`http://localhost:5173`).

|#|Method + path|Purpose|Response|
|---|---|---|---|
|1|`GET /health`|liveness + versions|`{status, contract_version, code_version}`|
|2|`GET /styles`|colour scales and class styles|`contracts/styles.json` (§6)|
|3|`GET /sites`|site list|`[SiteSummary]`|
|4|`GET /sites/{site_id}`|site detail|`SiteDetail`|
|5|`POST /sites`|Add a Dam (onboarding)|`202 {job_id, site_id}`|
|6|`GET /jobs/{job_id}`|job progress|`JobStatus`|
|7|`PUT /sites/{site_id}/recheck`|set re-check frequency|`SiteSummary`|
|8|`POST /sites/{site_id}/rerun`|re-run library (reuses terrain)|`202 {job_id}`|
|9|`POST /flood/query`|run a scenario|`FloodQueryResponse` (may be `partial`)|
|10|`GET /flood/{query_id}`|poll until `complete`|`FloodQueryResponse`|
|11|`GET /flood/{query_id}/layers/{layer_id}.png`|overlay image|PNG|
|12|`GET /flood/{query_id}/extent.geojson`|HIGH/POSSIBLE polygons, isochrones|GeoJSON|
|13|`GET /flood/{query_id}/timeline`|Time Simulation data|`Timeline`|
|14|`GET /impact/{query_id}`|impact + warning table|`impact.json` (§4.7)|
|15|`GET /compare/{site_id}?scenario_id=`|model comparison|`Compare`|
|16|`GET /validation/{site_id}`|emulator validation|`Validation`|
|17|`GET /validation/{site_id}?event={event_id}`|historical validation|`HistoricalValidation`|
|18|`GET /export/{query_id}?format=shp\|kml\|geojson\|pdf`|download|file|
|19|`GET /gee/{site_id}`|satellite layers (from cache)|`GeeLayers`|
|20|`POST /gee/{site_id}/refresh`|try live fetch, fall back to cache|`GeeLayers`|
|21|`GET /scene3d/{query_id}`|3D view data|`Scene3D`|
|22|`GET /files/{path}`|static result files referenced by URLs above|file|

### 5.1 SiteSummary / SiteDetail

```jsonc
{
  "site_id": "teesta", "name": "Teesta — South Lhonak GLOF to Teesta III",
  "status": "ready",                       // onboarding | demo_mode | ready | outdated | failed
  "status_reason_key": null,               // e.g. "outdated_lake_area_change"
  "emulator_ready": true, "models_available": ["delft3d", "sph"],
  "last_trained_at": "2026-09-24T10:15:00Z",
  "recheck": { "frequency_days": 90, "last_checked_at": "...", "next_check_at": "..." },
  "bbox_lonlat": [88.0, 27.5, 89.0, 28.2],
  "events": ["teesta_2023"],
  "has_placeholders": true
}
```

`SiteDetail` adds:

- `dams`: `[{dam_id, name, kind, order, key_specs: {<name>: SourcedValue}}]`
- `emulator_inputs`: `[{name, dam_id, label_key, unit, low, high, slider: {positions, mapping}, default}]`
- `domain`, `centreline`, `pois`: GeoJSON FeatureCollections (EPSG:4326)
- `validation_summary`: `{extent, depth, arrival, velocity}` grades
- `caveats`: `[Caveat]`

### 5.2 POST /sites (Add a Dam)

Request:

```jsonc
{ "site_config": { "...": "the YAML structure of §3 as JSON" }, "demo_mode": true }
```

Response `202`: `{ "job_id": "job_20260924T101500Z_b17e02", "site_id": "new_site" }`. Validation errors return `422` listing the invalid fields.

### 5.3 JobStatus

```jsonc
{
  "job_id": "job_20260924T101500Z_b17e02", "kind": "onboarding", "site_id": "new_site",
  "stage": "simulating",   // onboarding: queued → terrain → breach → design → simulating → training → validating → ready | failed
                           // campaign:   queued → simulating → postprocessing → done | failed
                           // recheck:    queued → checking → done | failed
  "stage_label_key": "job_stage_simulating",
  "progress": { "current": 3, "total": 6, "unit": "runs" },
  "eta_s": 1800, "demo_mode": true,
  "started_at": "...", "updated_at": "...",
  "log_tail": ["run new_site_demo_s003__delft3d started"],
  "error": null
}
```

### 5.4 POST /flood/query

Request:

```jsonc
{
  "site_id": "teesta",
  "model": "delft3d",                 // the emulated model; SPH is comparison-only
  "mode": "unknown_breach",           // scenario | unknown_breach
  "inputs": {
    "breach_width_m": { "type": "exact",  "value": 72.0 },
    "failure_time_s": { "type": "slider", "position": 3 }
    // omitted inputs: fixed at default in scenario mode (error if no default), sampled over range in unknown_breach mode
  },
  "options": { "n_samples": 500, "seed": null }
}
```

Behaviour:

- Responds within **2 s** with `status: "partial"` (median layers available) or `"complete"`.
- The client polls `GET /flood/{query_id}` every 500 ms until `status: "complete"` (target: under 10 s).

Response (`FloodQueryResponse`):

```jsonc
{
  "contract_version": "0.1.0",
  "query_id": "q_20260924T101500Z_3fa9c1", "site_id": "teesta",
  "status": "complete",                    // partial | complete | failed
  "method": "gp_emulator",                 // gp_emulator | empirical_fallback
  "mode": "unknown_breach",
  "resolved_inputs": {
    "breach_width_m": { "value": 72.0, "low": 72.0, "high": 72.0, "unit": "m", "interval": "none", "kind": "input" },
    "failure_time_s": { "value": 0.0, "low": 0.0, "high": 0.0, "unit": "s", "interval": "none", "kind": "input", "basis": "slider position 3, log mapping" },
    "water_volume_m3": { "value": 0.0, "low": 0.0, "high": 0.0, "unit": "m3", "interval": "method_range", "kind": "input", "basis": "sampled over range" }
  },
  "summary": {
    "inundated_area_m2":  { "value": 0.0, "low": 0.0, "high": 0.0, "unit": "m2",  "interval": "P10-P90", "kind": "predicted", "confidence": "HIGH" },
    "max_depth_m":        { "value": 0.0, "low": 0.0, "high": 0.0, "unit": "m",   "interval": "P10-P90", "kind": "predicted", "confidence": "HIGH" },
    "max_velocity_ms":    { "value": 0.0, "low": 0.0, "high": 0.0, "unit": "ms",  "interval": "P10-P90", "kind": "predicted", "confidence": "HIGH" },
    "peak_discharge_m3s": { "value": 0.0, "low": 0.0, "high": 0.0, "unit": "m3s", "interval": "P10-P90", "kind": "predicted",
                            "basis": "breach outflow at teesta__south_lhonak (M2)" },
    "first_arrival": { "poi_id": "teesta__poi__chungthang", "name": "Chungthang",
                       "arrival_s": { "value": 0, "low": 0, "high": 0, "unit": "s", "interval": "P10-P90", "kind": "predicted", "confidence": "MODERATE" } }
  },
  "confidence": {
    "overall":  { "level": "MODERATE", "components": { "validation_skill": "GOOD", "query_coverage": "EDGE", "spread": "MEDIUM" }, "reason_key": "conf_edge_of_training_range" },
    "extent":   { "level": "HIGH", "components": {}, "reason_key": null },
    "depth":    { "level": "HIGH", "components": {}, "reason_key": null },
    "arrival":  { "level": "MODERATE", "components": {}, "reason_key": null },
    "velocity": { "level": "HIGH", "components": {}, "reason_key": null }
  },
  "layers": [ { "layer_id": "p_inundation", "type": "raster_png", "url": "...", "bounds_latlng": [[0, 0], [0, 0]], "style_id": "p_inundation", "unit": null, "available": true } ],
  "vectors": { "extent_url": "/api/v1/flood/q_20260924T101500Z_3fa9c1/extent.geojson" },
  "flags": { "outside_trained_range": false, "demo_mode": false, "library_outdated": false, "has_placeholders": true },
  "placeholder_fields": [],
  "caveats": [ { "id": "clear_water", "severity": "warning", "text_key": "caveat_clear_water" } ],
  "provenance": { "method": "gp_emulator", "run_ids": [], "parameters": { "n_samples": 500, "seed": 42 } },
  "timing_ms": { "median_phase": 0, "full_phase": 0 }
}
```

- `overall` confidence = the lowest of the four output levels.

### 5.5 Timeline

`GET /flood/{query_id}/timeline?interval_s=300` (default 300 s, i.e. every 5 min; range 60-86400 s).
Frame time `t_s = k * interval_s` for `k = 1, 2, ...`, up to `t_end_s` (the run's simulation end).
**Extent at time t = cells whose arrival <= t.** Three PNGs per frame, all on the query's canonical
grid, all transparent outside their extent:

- `median_url`: cells where the median (P50) arrival time <= t, coloured by arrival time
  (`arrival_p50` style).
- `high_url`: HIGH-confidence cells (`extent_class == 2`) whose P90 arrival time <= t
  (`extent_class` style, code 2).
- `possible_url`: POSSIBLE-or-HIGH cells (`extent_class >= 1`) whose P10 arrival time <= t and not
  already in `high_url` (`extent_class` style, code 1).

At `t_s = t_end_s`, `high_url` + `possible_url` together reproduce the query's final `extent_class`
layer; frames are monotone (a cell, once lit, stays lit in later frames).

`arrival_profile` samples the centreline every canonical grid cell size (`chainage_samples.csv`,
§4.1); `arrival_p10_s`/`arrival_p90_s` are `null` where that percentile never arrives within
`t_end_s`; a chainage row is omitted entirely if even the median never arrives. Arrival and depth
percentiles are per-cell marginals, not a true joint distribution -- flagged via
`caveat_arrival_depth_not_joint`.

```jsonc
{
  "query_id": "q_20260924T101500Z_3fa9c1", "interval_s": 300, "t_end_s": 21600,
  "frames": [ { "t_s": 300, "median_url": "...png", "high_url": "...png", "possible_url": "...png", "bounds_latlng": [[0, 0], [0, 0]] } ],
  "hydrographs": [ { "dam_id": "teesta__south_lhonak", "t_offset_s": 0, "points": [ { "t_s": 0, "q_m3s": 0.0 } ] } ],
  "arrival_profile": [ { "chainage_m": 0.0, "arrival_p10_s": 0, "arrival_p50_s": 0, "arrival_p90_s": 0 },
                        { "chainage_m": 12000.0, "arrival_p10_s": 2100, "arrival_p50_s": 2400, "arrival_p90_s": null } ],
  "pois_on_profile": [ { "poi_id": "teesta__poi__chungthang", "name": "Chungthang", "chainage_m": 12000.0 } ],
  "caveats": [ { "id": "clear_water", "severity": "warning", "text_key": "caveat_clear_water" } ],
  "provenance": { "method": "gp_emulator", "contract_version": "0.1.0", "created_at": "2026-09-24T10:15:00Z" }
}
```

PNG URLs follow `/api/v1/files/<site_id>/queries/<query_id>/timeline/{median|high|possible}_t<t_s>.png`
(§1.8 `queries/<query_id>/timeline/`), served by route #22 (`GET /files/{path}`).

Extent at time t = cells whose arrival ≤ t.

### 5.6 Compare

```jsonc
{
  "site_id": "teesta", "scenario_id": "teesta_s003",
  "sph_vs_delft3d": {
    "available": true, "domain": "nearfield", "time_window_s": 0,
    "metrics": { "iou": 0.0, "f1_0_3": 0.0, "depth_rmse_wet_m": 0.0, "velocity_mae_ms": 0.0 },
    "probes": [ { "poi_id": "...", "arrival_delft3d_s": 0, "arrival_sph_s": 0, "diff_s": 0 } ],
    "layers": [ { "layer_id": "depth_diff_nearfield", "type": "raster_png", "url": "...", "bounds_latlng": [[0, 0], [0, 0]], "style_id": "depth_diff", "unit": "m", "available": true } ],
    "run_ids": ["teesta_s003__delft3d", "teesta_s003__sph"]
  },
  "emulator_vs_physics": {
    "available": true, "held_out_run_id": "teesta_s012__delft3d",
    "metrics": { "iou": 0.0, "depth_rmse_wet_m": 0.0, "arrival_mae_s": 0.0 },
    "layers": []
  },
  "gp_vs_linear": { "iou_median_gp": 0.0, "iou_median_linear": 0.0, "arrival_mae_s_gp": 0.0, "arrival_mae_s_linear": 0.0 },
  "when_to_use_key": "when_to_use_sph_delft3d",
  "caveats": []
}
```

### 5.7 Validation and HistoricalValidation

`GET /validation/{site_id}` returns `validation/loocv.json` (§4.6) plus `"events": ["teesta_2023"]`.

`GET /validation/{site_id}?event=teesta_2023`:

```jsonc
{
  "contract_version": "0.1.0", "site_id": "teesta", "event_id": "teesta_2023",
  "observed": {
    "extent_url": "/api/v1/files/teesta/gee/observed/teesta_2023_observed.geojson",
    "area_m2": { "value": 0.0, "unit": "m2", "kind": "observed", "source": "src_040" },
    "arrival_reports":  [ { "place": "Chungthang", "arrival_s": 0, "source": "src_041", "note": "reported time" } ],
    "peak_discharge_estimates": [ { "location": "...", "value_m3s": 0.0, "source": "src_042" } ]
  },
  "predicted": {
    "emulator":       { "query_id": "q_...", "area_m2": { "...": "Estimate" } },
    "delft3d_direct": { "run_id": "teesta_hist_2023__delft3d", "area_m2": { "...": "Estimate" } }
  },
  "metrics": {
    "emulator":       { "iou": 0.0, "f1_dice": 0.0, "area_error_pct": 0.0,
                        "arrival_errors": [ { "place": "Chungthang", "error_s": 0, "low_s": 0, "high_s": 0 } ],
                        "peak_errors": [ { "source": "src_042", "error_pct": 0.0 } ] },
    "delft3d_direct": { "...": "same shape" }
  },
  "comparison_domain": "valley corridor only",
  "caveats": [ { "id": "clear_water", "severity": "warning", "text_key": "caveat_clear_water" } ],
  "provenance": {}
}
```

### 5.8 GeeLayers

```jsonc
{
  "site_id": "teesta", "source": "cache",          // live | cache | screenshot_fallback
  "fetched_at": "2026-09-24T10:15:00Z",
  "lake_area_series": [ { "date": "2026-08-01", "area_m2": 0.0, "method": "s1_threshold", "cloud_pct": null } ],
  "lake_latest": { "type": "FeatureCollection", "features": [] },
  "rainfall": [ { "date": "2026-09-20", "precip_mm": 0.0, "dataset": "gpm_imerg" } ],
  "imagery": [ { "event_id": "teesta_2023", "phase": "post", "date": "2023-10-10", "url": "...png", "bounds_latlng": [[0, 0], [0, 0]] } ],
  "observed_extents": [ { "event_id": "teesta_2023", "url": "...geojson", "method": "manual_digitized" } ],
  "recheck": { "outdated": false, "change_pct": 0.0, "threshold_pct": 10 }
}
```

### 5.9 Scene3D

```jsonc
{
  "query_id": "q_...", "frame": { "crs_epsg": 32645, "origin_x": 0.0, "origin_y": 0.0, "vertical_exaggeration": 1.5 },
  "terrain": { "url": "...bin", "encoding": "float32_le_row_major", "width": 500, "height": 375, "cell_size_m": 120.0, "min_elev_m": 0.0, "max_elev_m": 0.0 },
  "flood_surface": { "url": "...bin", "encoding": "float32_le_row_major", "nodata": -9999.0, "basis": "terrain + depth_p50" },
  "comparison": {
    "nearfield_bounds_local": [[0, 0], [0, 0]],
    "delft3d_surface_url": "...bin",
    "sph_surfaces": [ { "t_s": 300, "url": "...glb" } ]
  },
  "max_payload_mb": 20
}
```

---

## 6. Shared styles — `contracts/styles.json`

One file drives map overlays (M0-5), KML styling (M6-6) and legends (M8). Colours ⚙️ should come from the frontend palette in `frontend/STYLE_GUIDE.md`.

```jsonc
{
  "contract_version": "0.1.0",
  "extent_class": {
    "high":     { "fill": "#<hex>", "opacity": 0.65, "label_key": "legend_high" },
    "possible": { "fill": "#<hex>", "opacity": 0.35, "pattern": "hatch", "label_key": "legend_possible" }
  },
  "p_inundation": { "type": "continuous", "stops": [[0.1, "#<hex>"], [0.5, "#<hex>"], [0.9, "#<hex>"]] },
  "depth_p50":    { "type": "classes", "breaks_m": [0.3, 0.5, 2.0, 5.0], "colors": ["#<hex>", "#<hex>", "#<hex>", "#<hex>", "#<hex>"] },
  "arrival_p50":  { "type": "classes", "breaks_s": [900, 1800, 3600, 7200], "colors": ["#<hex>", "#<hex>", "#<hex>", "#<hex>", "#<hex>"] },
  "velocity_p50": { "type": "classes", "breaks_ms": [0.5, 1.0, 2.0, 5.0], "colors": ["#<hex>", "#<hex>", "#<hex>", "#<hex>", "#<hex>"] },
  "depth_diff":   { "type": "diverging", "range_m": [-2.0, 2.0], "colors": ["#<hex>", "#ffffff", "#<hex>"] },
  "isochrones":   { "stroke": "#<hex>", "width": 1.5, "interval_s": 900 }
}
```

Depth classes, arrival classes and the isochrone interval are ⚙️ (playbook M6-3).

---

## 7. Ownership matrix

|Module|Owner (role)|Produces|Consumed by|
|---|---|---|---|
|Team|all|`sites/*.yaml`, `docs/data_sources.md`, `docs/decisions.md`|everyone|
|M0|backend lead|API (§5), registry, jobs, renders, `styles.json` served|M8|
|M1|GIS|terrain (§4.1)|M3, M4, M5, M6, M0|
|M2|hydrology|`breach_params.json`, hydrographs, `hydrograph()` (§4.2)|M3, M4, M5, M0|
|M3|modeller A|Delft3D run results (§4.4)|M5, M0|
|M4|modeller B|SPH run results (§4.4)|M5 (compare), M0|
|M5|data scientist|design, emulator, validation, `get_flood()` (§4.3, §4.6)|M0, M6|
|M6|GIS analyst|`impact.json`, exports (§4.7)|M0, M8|
|M7|remote sensing|GEE outputs (§4.8)|M5, M0, M8|
|M8|frontend|UI|—|

---

## 8. Contract tests

- `contracts/` holds one JSON Schema per payload in this document plus a valid example file for each (generated in M0-1).
- Every module has a pytest test that validates its outputs against the matching schema, using synthetic fixtures in `tests/fixtures/<module>/`.
- Raster outputs are checked for: CRS, transform and shape equal to the site grid; dtype; nodata; units in metadata.
- The API test suite calls every endpoint and validates every response.
- The frontend's mock mode serves the example files from `contracts/`, so mocks can never drift from the contract.

---

## 9. Changing the contract

1. Write the proposed change and the reason in `docs/decisions.md`.
2. Get agreement from the owners of every module that produces or consumes the affected data (§7).
3. Update this file, bump `contract_version` (patch: clarification; minor: new optional field or endpoint; before 1.0, a breaking change also bumps minor and must be called out).
4. Update `contracts/` schemas and examples, then run all contract tests.
5. Tell Claude Code in the next session: "The contract changed to <version>; see docs/decisions.md; update affected modules and tests."
