# Problem Statement

[[SIH26 - Problem Statement]] (PS-26161)

# Problem statement Breakdown

## Build a software tool that:

- Simulates dam-break / natural-dam (landslide lake, moraine lake) failure using **SPH** and **Delft3D**, and compares them
- Predicts the inundated area and estimates loss/damage
- Has a **GUI dashboard** for input and output visualization
- Outputs in **.shp/.kml**
- Adds a **near-real-time layer using Google Earth Engine**
- Is demonstrated on a **real Indian river + dam** with open-source data

## Actual Use case:

"India has no fast, low-data, field-deployable decision-support tool for glacial lake outburst floods (GLOFs) and dam-break scenarios that a disaster authority can run in hours, with the sparse data actually available in Himalayan/NE India"

Events like Rishi Ganga (2021), South Lhonak / Teesta (2023) and Kosi (2008) happened in catchments with **poor/no real-time gauge data**. The actual gap isn't "we lack a good hydraulic model" — it's "we lack a tool that can produce a usable, defensible inundation estimate _despite_ missing breach parameters, missing discharge data, and missing high-res DEMs, fast enough to inform an evacuation decision." Speed and robustness-under-uncertainty matter more than physical accuracy to the third decimal place.

The SPH-vs-Delft3D comparison requirement is really a proxy for: **"show you understand the tradeoff between physical fidelity and computational speed, and can justify which model to use when."**

## End User

GUI/dashboard + shapefile/KML output requirement is the giveaway, these are for people who consume GIS layers, not people who write hydraulic code. Real users:

- District Disaster Management Authorities (DDMAs) / State Disaster Management Authorities (SDMAs)
- **NDMA** — policy-level scenario planning
- Central Water Commission (CWC) / dam operators — existing dam-break risk assessment (Dam Safety Act 2021 mandates Emergency Action Plans)
- **Army** — border Himalayan regions where GLOF risk is highest and data is thinnest
- State GIS cells who'll load our .shp/.kml into QGIS/Bhuvan

## Hidden Constraints

- DEM resolution (SRTM/CartoDEM ~30 m in narrow gorges; pre-event lake bathymetry usually unknown)
- Breach parameters aren't given anywhere
- Breach equations are calibrated on **man-made embankment dams** — applying them to moraine/landslide dams is an extrapolation
- **Breach formation time is poorly predictable by every method** (Azmi 2026: R² ≈ 0.24) → must be a scenario variable, not a point estimate
- Delft3D licensing (GUI suite vs open-source D-Flow FM kernel — verify current terms)
- SPH is computationally expensive (our GPU: RTX 4060, 8 GB VRAM → a few million particles, near-field only)
- 16 GB RAM → cannot hold full timestep × cell matrices; emulate summary maps
- Roughness coefficients (no calibrated Manning's n for Himalayan channels)
- **Himalayan floods are debris/sediment-laden**; our models are clear-water → speed and extent may be off
- Monsoon cloud coverage (optical imagery gaps)
- **SAR layover/shadow in steep narrow valleys** → Sentinel-1 flood mapping in gorges is unreliable
- The historical events listed are for implicit validation / demo candidates
- `.shp` or `.kml` output constraint
- "any river and Dam data" → need an onboarding path for new sites

# Demo sites

## 1. Teesta — South Lhonak GLOF → Teesta III (Oct 2023) ⭐ headline demo

- Moraine-dammed glacial lake breached; the flood travelled down the Teesta and contributed to the failure of the Teesta III (Chungthang) dam
- **Cascading scenario**: natural-dam breach + engineered-dam failure in one demo → covers both halves of the PS
- Breach engine applies to the moraine breach (with extrapolation caveat)
- ⚠️ Verify Teesta III dam type before applying embankment equations; if unsuitable, model its failure as an imposed scenario

## 2. Rishi Ganga — Chamoli (Feb 2021)

- ⚠️ **Not a classic dam break**: a rock-ice avalanche that became a debris flow, destroying the Rishiganga HEP and damaging Tapovan–Vishnugad
- Honest framing, use one or both:
    - **Validation case**: reconstruct the event as an equivalent hydrograph and compare with the documented extent, openly stating we approximate a mass flow as a water flood
    - **Forecasting case**: the post-event **landslide-dammed lake on the Raunthi Gad** — "what if it had failed?" (genuine natural-dam scenario)

> All event facts (volumes, dates, distances, sequence) must be taken from published studies / official reports and logged in `docs/data_sources.md`. Nothing from memory goes on a slide.

# Ideation

## Actual idea + uniqueness

We can't run the full, slow, "correct" simulation (SPH/Delft3D) live in front of judges — it takes hours. So instead, ==**we run the slow, correct simulation for a designed set of "what-if" scenarios beforehand**==, and train a **statistical emulator** on those results. During the demo, when someone asks "what if the breach is 60% wider and forms in 20 minutes?", the emulator answers in about a second — and, unlike a lookup table, **tells us how confident it is**.

### How the emulator works (Donnelly et al. 2022)

1. Run Delft3D (and SPH near-field) for ~20–40 scenarios chosen by **Latin hypercube sampling** over the inputs (lake volume / water level, breach width, breach formation time, …) — not a full grid, which explodes with 3–4 inputs
2. For each run, store **summary maps**: max depth, arrival time, max velocity
3. Compress the maps with **PCA** (a handful of components capture most variance)
4. Fit one **Gaussian Process** (Matérn 3/2 kernel) per component
5. Query = GP predicts components → decode back to full maps, **with predictive uncertainty**

Baseline for comparison: simple nearest-neighbour / linear blending of the two closest runs (our original idea). We show in validation that the GP beats it — that's a good slide.

### Uncertainty propagation — the "high-confidence / possible" layers

1. The breach engine (M2) gives each parameter a **range** (dual-method pair from Azmi 2026), not one number
2. Sample a few hundred parameter sets from those ranges
3. Push each through the GP emulator (milliseconds each)
4. Per cell: fraction of samples in which it floods = **probability of inundation**
    - ≥ 90% → **HIGH-CONFIDENCE FLOOD**
    - 10–90% → **POSSIBLE FLOOD EXTENSION**
5. Arrival time reported as median + range across samples

So the uncertainty on the map comes from **both** breach-parameter uncertainty and emulator uncertainty — computed, not drawn.

### Time simulation without huge data

Extent at time _t_ = all cells whose emulated **arrival time ≤ t**. This gives the flood-front animation from a single arrival-time map, no per-timestep emulation needed.

### "Add a Dam" tab (onboarding a new site)

1. Fetch/load the DEM for the new site (Bhuvan CartoDEM, SRTM, Copernicus DEM via OpenTopography)
2. Dam/lake specs — height, volume, location, dam type — user-entered or from open CWC / India-WRIS data
3. Run breach equations (Froehlich 1995/2008/2016, Xu & Zhang 2009, Zhong 2020, MacDonald & Langridge-Monopolis 1984, fused via Azmi DFM) → parameter ranges, instant
4. Generate the scenario set (Latin hypercube) and **queue** Delft3D + SPH runs — the slow part
5. Train the site's emulator, run leave-one-out validation, store as that site's own library

Until step 5 finishes, the site uses the **empirical fallback** (breach equations + DEM flow routing), clearly labelled "LOW CONFIDENCE — physics runs pending".

The tab shows a **real** async job status: "Onboarding new site — DEM loaded ✓, breach ranges computed ✓, Delft3D run 3/30 running (est. 40 min each)." A reduced-resolution "demo mode" run can finish live in minutes.

## Demo time

1. Judge picks a site and sets breach inputs (exact value or slider)
2. **Instantly** (< 1 s): the emulator's central-estimate flood map appears, with a note like "Chungthang: water arrives in ~X min (range A–B min)"
3. **Over the next few seconds**: Monte Carlo sampling runs and the map **resolves into HIGH-CONFIDENCE and POSSIBLE layers** — a genuine refinement, not a staged animation
4. For a non-onboarded site: the empirical fallback map appears, labelled low-confidence
5. Model Comparison panel: SPH vs Delft3D on the near-field domain, side by side and as a difference map
6. Judge downloads the flood layers as .shp/.kml that any GIS software or Google Earth can open

![[twin_final_architecture.png]]

> ⚠️ Update this diagram: M2 also feeds M5 (for Monte Carlo sampling); M5 now contains the PCA+GP emulator; M7 lake-area monitoring can trigger re-runs.

## Elevator Pitch framing

When a Himalayan glacial lake or dam threatens to break, disaster officials can't wait hours for physics simulations. Our tool runs SPH and Delft3D offline, trains a statistical emulator on the results, and answers any what-if scenario in seconds — with an honest confidence map, validated against real Himalayan floods.

## Why is this "winning" rather than just "a solution"?

- **Most teams** will either (a) fake a full simulation with a slow spinner and a canned result, (b) build only a pretty map with no real physics, or (c) claim "we integrated AI" with nothing concrete behind it.
- **We** can honestly say: "we're not pretending to run physics live — here's why that's the right engineering decision, here's a peer-reviewed method (GP emulation) that makes it fast, here's how we quantify uncertainty, and here's how it compares with a real historical flood." That's a **systems-design answer**.
- Judges from NDMA/CWC care about **the real operational constraint**: in a crisis you don't have hours. We built around that constraint — and we're upfront about our limitations (moraine extrapolation, clear-water assumption, failure-time uncertainty), which builds trust.

## SPH vs Delft3D — when to use which (our answer to the comparison requirement)

| SPH (DualSPHysics) | Delft3D (D-Flow FM)                                                         |                                                |
| ------------------ | --------------------------------------------------------------------------- | ---------------------------------------------- |
| Physics            | 3D, mesh-free, handles violent breach flow, splashing, complex free surface | 2D depth-averaged shallow water                |
| Domain             | **Near-field**: breach zone + first few hundred m to ~2 km                  | **Far-field**: tens of km downstream           |
| Cost               | Hours per run on GPU, particle count limited by VRAM                        | Minutes–hours per run on CPU                   |
| Role               | Checks what 2D misses near the breach                                       | Produces the scenario library for the emulator |

- Lake is fed into SPH as an **inflow boundary** (breach hydrograph from M2), not filled with particles
- Comparison is done on the **overlapping near-field domain**: extent IoU, depth and velocity differences, arrival time at probe points
- Conclusion we expect to show: 2D is adequate for far-field evacuation mapping; SPH adds value right at the breach

## What will the dashboard return?

Six result panels:

**1. Flood Summary** (every number = estimate + range + confidence)

- Inundated area
- Maximum depth
- Maximum velocity
- Peak discharge
- First arrival time at key locations

**2. Interactive Map**

- Flood extent (HIGH-CONFIDENCE / POSSIBLE layers)
- Depth
- Velocity
- Arrival time
- Infrastructure layers

**3. Time Simulation**

- Flood-front animation (from arrival-time map)
- Flood extent at different times
- Arrival-time information per village/asset

**4. Impact Analysis**

- Population (WorldPop)
- Buildings (OSM; Himalayan coverage is sparse — check open building-footprint datasets as a supplement)
- Roads, bridges
- Hospitals, schools
- Agriculture (Bhuvan LULC)
- Hydropower & other critical infrastructure
- **Loss estimate** using depth–damage curves (e.g. JRC global depth-damage functions) — shown as a range

**5. Model Comparison**

- SPH vs Delft3D (near-field)
- Difference / overlay (2D map + 3D Three.js view)
- Emulator vs held-out physics run
- Historical / satellite comparison

**6. Export & Evidence**

- SHP, KML, GeoJSON
- PDF report
- Simulation/data provenance (sources, versions, parameters, run IDs, confidence method)

# Key Issues + fixes

1. **Failing the explicit "comparison" requirement** Show SPH and Delft3D side by side on the near-field domain — extent, depth, velocity and arrival time — plus the "when to use which" table.
2. **GEE failure during demo** All GEE products are fetched offline and cached; local screenshots as a second fallback.
3. **Outdated cached library** Lakes grow and terrain changes. Instead of only a fixed "recalculate every 3 months" alert:
    - GEE monitors lake area; if it changes beyond a threshold → flag the site as "library outdated, re-run recommended"
    - Plus a user-set periodic re-check frequency
4. **Define uncertainty explicitly + separate prediction from observation** Never "arrival time: 42 mins". Always: estimate, possible range, confidence level, and whether it's predicted or observed.
5. **Fabricated-looking numbers** Every number in the UI must trace back to a computation or a cited source. Mock-ups use values clearly marked `ILLUSTRATIVE`.
6. **Emulator asked to extrapolate** If the query is outside the range of training scenarios, the GP's uncertainty widens — show a warning: "outside trained range, confidence reduced".
7. **Rishi Ganga mis-framing** Never present it as a dam break (see Demo sites).

We make the map with uncertainty in mind:

```md
HIGH-CONFIDENCE FLOOD   (flooded in ≥ 90% of samples)
████████

POSSIBLE FLOOD EXTENSION (flooded in 10–90% of samples)
░░░░░░░░
```

## Scenario inputs

```md
SCENARIO INPUTS

Initial Water Level
[ Exact ] [ Slider ]
Exact: 2470 m
OR
0 ───────●────── 10
         7

────────────────────────────────

Breach Width
[ Exact ] [ Slider ]
Exact: 72 m
OR
0 ─────●──────── 10
       5
(slider range = M2 dual-method range for this site)

────────────────────────────────

Breach Formation Time
[ Exact ] [ Slider ]
Exact: 18 min
OR
0 ────●───────── 10
      3
(wide range on purpose — no method predicts this well)
```

> Values above are `ILLUSTRATIVE`.

## Emulator validation (replaces "interpolation validation")

When a site is onboarded, we do **leave-one-out cross-validation (LOOCV)**: train on all runs but one, predict the held-out run, compare with the real physics output, repeat for every run. (Our old "use 10 and 30 to predict 20" idea is the 1-D special case of this.)

### Metrics

|Metric|What it tells us|Used for|
|---|---|---|
|**Flood-extent IoU**|Headline spatial agreement|Extent confidence|
|**F1 at 0.05 / 0.1 / 0.3 m**|Wet/dry classification (0.3 m ≈ property counted as flooded)|Extent confidence|
|Relative flooded-area error|Easy for judges to understand|Summary|
|Depth RMSE / MAE on wet cells only|Depth accuracy (dry cells excluded so error isn't flattered)|Depth confidence|
|Arrival-time MAE|ETA accuracy|ETA confidence|
|Velocity MAE|Velocity accuracy|Velocity confidence|
|GP-vs-linear-blend comparison|Shows why the emulator is worth it|Pitch slide|

### Confidence formula (to be calibrated on synthetic data, then real runs)

For each output (extent, depth, arrival time, velocity):

1. **Validation skill** — LOOCV score for that output at this site
2. **Query coverage** — is the query inside the range of training scenarios?
3. **Predictive spread** — GP uncertainty / Monte Carlo range relative to the estimate

```
HIGH      skill good AND inside trained range AND spread small
MODERATE  one condition fails
LOW       two or more fail, OR empirical fallback, OR extrapolating
```

Exact thresholds (e.g. IoU ≥ 0.8 for "good") are set once we see real LOOCV results — never hardcoded from guesses.

```
Overall emulator confidence: [computed]
┌────────────────────────────────┐
│ EMULATOR VALIDITY              │
│                                │
│ Flood extent       [computed]  │
│ Flood depth        [computed]  │
│ Arrival time       [computed]  │
│ Velocity           [computed]  │
└────────────────────────────────┘
```

## Historical Event validation

A "compare" feature in the dashboard that compares a past event with our prediction.

|Metric|Purpose|
|---|---|
|**IoU**|Simulated vs observed extent|
|**F1 / Dice**|Spatial classification agreement|
|**Flooded-area % error**|Total extent agreement|
|**Arrival-time error**|Timing agreement, if observations exist (reported times at dams/towns)|
|**Peak discharge % error**|Hydraulic validation, if published estimates exist|
|NSE/KGE|Optional, only with an observed discharge time series|

**Observed extent sources** (Himalayan gorges): pre/post-event **Sentinel-2** optical imagery showing erosion/deposition scars, and published post-event inundation maps. Sentinel-1 SAR is unreliable for narrow gorge flooding (layover/shadow) — but works well for **lake-area monitoring** through cloud cover.

```
┌──────────────────────────────────────────────────────────────┐
│              HISTORICAL VALIDATION RESULTS                   │
│              ⚠ ALL VALUES ILLUSTRATIVE — layout only         │
├──────────────────────────────────────────────────────────────┤
│   SPATIAL AGREEMENT                                          │
│   ┌─────────────────┐    ┌─────────────────┐                 │
│   │   FLOOD IoU     │    │    F1 / DICE    │                 │
│   │     0.xx        │    │     0.xx        │                 │
│   └─────────────────┘    └─────────────────┘                 │
│   ┌──────────────────────────────────────────────────────┐   │
│   │              FLOODED AREA COMPARISON                 │   │
│   │   Observed          xx km²                           │   │
│   │   Simulated         xx km²                           │   │
│   │   Relative Error    x.x%                             │   │
│   └──────────────────────────────────────────────────────┘   │
│   TEMPORAL AGREEMENT                                         │
│   ┌─────────────────┐    ┌─────────────────┐                 │
│   │ OBSERVED ETA    │    │ SIMULATED ETA   │                 │
│   │  xx min         │    │ xx min (A–B)    │                 │
│   │  [source]       │    │                 │                 │
│   └─────────────────┘    └─────────────────┘                 │
│   HYDRAULIC COMPARISON                                       │
│   ┌─────────────────┐    ┌─────────────────┐                 │
│   │ PEAK DISCHARGE  │    │   DEPTH MAE     │                 │
│   │ Obs: [source]   │    │   x.xx m        │                 │
│   │ Sim: xx (A–B)   │    │                 │                 │
│   └─────────────────┘    └─────────────────┘                 │
├──────────────────────────────────────────────────────────────┤
│   CAVEATS: clear-water model; debris flow approximated;      │
│   observed data sources listed in Export & Evidence          │
└──────────────────────────────────────────────────────────────┘
```

# Architecture & Tech stack

The solution is broken into independent modules, each runnable on **synthetic/dummy data** from day one, integrated through agreed contracts ([[SIH26 - Data Hand-off Contract]]).

```md
                   USER
                    ↓
             M8 Dashboard
                    ↓
          M0 Orchestrator/API  (job queue)
             │             │
             ▼             ▼
            M1            M2
         Terrain        Breach  ─────────────┐ (parameter ranges
             │             │                  │  for Monte Carlo)
             └──────┬──────┘                  │
                    ↓                         │
              ┌─────┴─────┐                   │
              ↓           ↓                   │
             M3          M4                   │
          Delft3D        SPH (near-field)     │
              └─────┬─────┘                   │
                    ↓                         │
                   M5  ◄──────────────────────┘
     Scenario cache → PCA+GP emulator → LOOCV validation
                    → Monte Carlo → confidence
              ┌─────┴─────┐
              ↓           ↓
             M6          M8
      Impact + Export  Dashboard

M7 GEE ──→ M5  (observed extent for historical validation)
M7 GEE ──→ M8  (overlays)
M7 GEE ──→ M0  (lake-area change → "library outdated" flag)
```

## Division into Modules

**0. Orchestrator / API**

- **Responsibility:** FastAPI app, async job queue for onboarding and simulation runs, serves the frontend, validates every payload against `contracts/`.
- **Maps to:** Backend lead
- **Provides TO others:** The REST API the dashboard consumes.

**1. Data & Terrain Pipeline**

- **Responsibility:** Ingest DEM + land cover for a site, clean/reproject/clip, produce terrain and roughness (Manning's n from land cover) rasters, river centreline, and STL terrain for SPH.
- **Maps to:** GIS/remote sensing person
- **Needs FROM others:** Only site lat/lon + bounding box (hardcoded for demo sites).
- **Provides TO others:** DEM (GeoTIFF), roughness raster, centreline, STL — consumed by M3, M4, M6.

**2. Breach Parameter Engine**

- **Responsibility:** From dam/lake specs (height, water volume above breach invert, dam type, failure mode, erodibility), compute peak discharge, breach width and failure time using the base equations and **Azmi (2026) data-fusion models**, output **dual-method ranges** and a breach hydrograph.
- **Maps to:** Hydrology/civil-domain person (mostly math)
- **Needs FROM others:** Nothing — dam specs (hardcode demo sites with sourced values).
- **Provides TO others:** Parameter ranges + hydrographs — consumed by M3/M4 (boundary conditions) and **M5 (Monte Carlo sampling)**.
- ⚠️ Implement each base equation from its **original paper**; hand-check against worked examples.

**3. Delft3D Simulation Runner**

- **Responsibility:** Generate D-Flow FM inputs (mesh, bathymetry, boundaries) for each scenario, launch runs in the background, convert outputs to summary maps (max depth, arrival time, max velocity).
- **Maps to:** Hydraulic modeller A
- **Needs FROM others:** DEM + roughness (M1), hydrographs (M2) — mocked initially.
- **Provides TO others:** Per-scenario summary rasters — consumed by M5.

**4. SPH Simulation Runner**

- **Responsibility:** DualSPHysics near-field cases (terrain STL + hydrograph inflow boundary), launch on GPU, convert outputs to the **same schema as M3**.
- **Maps to:** Hydraulic modeller B
- **Needs FROM others:** Terrain (M1), hydrographs (M2) — same mocked contract as M3.
- **Provides TO others:** Near-field summary rasters + probe time series — consumed by M5 and the comparison panel.

**5. Scenario Cache, Emulator & Validation Engine** — core IP

- **Responsibility:** Store per-site scenario libraries; train PCA+GP emulator; run LOOCV; answer live queries; run Monte Carlo over M2 ranges to produce probability-of-inundation maps and confidence levels.
- **Maps to:** Data scientist / backend engineer
- **Needs FROM others:** M3/M4 outputs — but fully buildable on **synthetic scenario rasters** from day one.
- **Provides TO others:** `get_flood(site, params) → {p_inundation, depth, arrival_time, velocity, ranges, confidence}` — consumed by M6 and M8.

**6. Impact & Loss Analysis + Export**

- **Responsibility:** Overlay flood layers on population/infrastructure (OSM, WorldPop, Bhuvan LULC), compute affected population/assets and loss ranges (depth–damage curves), export  .shp/.kml/.geojson + PDF report with provenance.
- **Maps to:** GIS analyst
- **Needs FROM others:** Flood output — mocked with a dummy polygon early.
- **Provides TO others:** Impact summary + downloadable files — consumed by M8.

**7. Near-Real-Time GEE Module**

- **Responsibility:** Offline fetch of lake-area time series (Sentinel-1/2), rainfall (CHIRPS/GPM), and pre/post-event Sentinel-2 imagery for validation; cached outputs + screenshot fallback.
- **Maps to:** Remote sensing person
- **Needs FROM others:** Only site coordinates.
- **Provides TO others:** Observed extent/imagery (M5 validation, M8 overlay), lake-area change flag (M0).

**8. Dashboard/GUI**

- **Responsibility:** Site selection, scenario inputs (exact/slider), "Add a Dam" onboarding flow, six result panels, 3D model-comparison view.
- **Maps to:** Frontend developer
- **Needs FROM others:** Only the agreed schemas — built against mock JSON from day one.
- **Note:** Its expected schema is the integration point, so **contracts are finalised first**, before anyone writes simulation code.

## Stack

**M0 — Orchestrator/API:** FastAPI, Pydantic v2, SQLite, background job runner

**M1 — Terrain:** `rasterio`, `GDAL`, `rioxarray`, `richdem`, `numpy-stl` (DEM → STL for SPH). Sources: Bhuvan CartoDEM, SRTM, Copernicus DEM (OpenTopography), Sentinel-2 / Bhuvan LULC

**M2 — Breach:** `numpy`, `pandas`, `scipy`

**M3 — Delft3D:** Delft3D FM / D-Flow FM (check current Deltares licensing), `hydrolib-core` (input files), `meshkernel` (mesh), `dfm_tools` (output post-processing)

**M4 — SPH:** DualSPHysics (GPU build), GenCase, MeasureTool / IsoSurface for outputs

**M5 — Emulator:** `scikit-learn` (PCA / randomized PCA, GaussianProcessRegressor with Matérn kernel), `numpy`, `scipy` (linear-blend baseline), GeoTIFF + `.npz` cache

**M6 — Impact:** `geopandas`, `shapely`, `simplekml`, PDF report generator. Sources: WorldPop, OSM (Overpass), depth–damage curves

**M7 — GEE:** Earth Engine Python API (offline prep only), cached GeoJSON/imagery, screenshots

**M8 — Dashboard:**

- React (Vite) — offline static build
- Leaflet / react-leaflet — 2D map, sliders redraw flood layers live
- Three.js / react-three-fiber — 3D terrain, breach geometry, SPH vs Delft3D surfaces
- Recharts / D3 — hydrographs, arrival-time curves, confidence charts
- Talks to FastAPI over localhost REST

**Cross-cutting**

- Python everywhere on the backend
- Localhost only: no cloud, no managed DB, no auth. Only GEE needs internet, and only during offline prep
- SI units; compute in UTM (Teesta ≈ EPSG:32645, Chamoli ≈ EPSG:32644), export in EPSG:4326
- Built with Claude Code, guided by `CLAUDE.md`; every module has pytest tests on synthetic data

## Hardware budget

- **GPU:** RTX 4060, 8 GB VRAM → SPH limited to a few million particles; measure VRAM per particle with a pilot
- **RAM:** 16 GB → Delft3D fine for ~1M-cell 2D grids (one run at a time); emulator uses summary maps, not full timestep stacks
- If laptop: plugged in, performance mode, good airflow, frequent output saves

## Build plan

**Parallel tracks from day 1**

|Track|First|Then|
|---|---|---|
|Backend (Claude Code)|Contracts → M0 skeleton with mocks → M2|M5 on synthetic data → M6 → M1 → M7 → M3/M4 wrappers|
|Modeller A|Install Delft3D, run a tutorial|Synthetic-valley pilot → Teesta clip pilot|
|Modeller B|Install DualSPHysics, run dam-break example|Terrain STL + inflow → near-field pilot|
|GIS|Download DEMs, OSM, WorldPop|M1 terrain for pilot domain|
|Frontend|Point at mock API|Swap panels to real endpoints one by one|

**Pilot gate** (before training the real emulator): one scenario in both models on the same near-field domain. Record runtime, memory, sanity of extent, post-processing time → fixes the **run budget** (how many scenarios, what resolution).

## References

- Azmi, M. (2026). An update on data-fusion-based dam breach empirical equations based on a worldwide historical dam failure database. _Natural Hazards_. https://doi.org/10.1007/s11069-026-08239-x
- Donnelly, J., Abolfathi, S., Pearson, J., Chatrabgoun, O., Daneshkhah, A. (2022). Gaussian process emulation of spatio-temporal outputs of a 2D inland flood model. _Water Research_ 225, 119100. https://doi.org/10.1016/j.watres.2022.119100
- Base breach equations (implement from originals): Froehlich (1995, 2008, 2016b); Xu & Zhang (2009); Zhong et al. (2020); MacDonald & Langridge-Monopolis (1984)
- Event studies for Teesta 2023 and Chamoli 2021: **to be added from literature search** (log in `docs/data_sources.md`)

## Data Hand-off contract

[[SIH26 - Data Hand-off Contract]]

[[SIH26 - file structure]] [[SIH26 - Random]]