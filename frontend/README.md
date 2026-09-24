# SENTRIQ · SIH 26161 disaster-intelligence prototype

This is a working browser prototype, not a validated operational dam-break forecasting system.

## Demonstration
1. Open Simulation workspace. A completed hypothetical Tehri run is preloaded.
2. Change breach width, water head, volume cap, formation time, duration or Manning roughness. Run simulation; watch real progress and cancel if needed.
3. Select Time series and play. Hover to inspect elevation/depth. Pan/zoom or choose a new inflow cell.
4. Open Impact assessment. Default exposure points and replacement values are explicitly synthetic; import real point GeoJSON to replace them.
5. Open SPH Concept Lab for the separate educational particle tank. In Model Comparison, import actual external SPH/Delft3D georeferenced outputs to calculate area/depth differences.
6. Export KML, GeoJSON, hydrograph CSV or complete JSON. The GIS exports contain maximum-depth wet cells and arrival time.
7. Generate the Earth Engine script under Satellite analysis. Run it in an authorised GEE project, inspect acquisitions and thresholds, export polygons, then import the observed extent.

## Scientific scope
The Fast Screening stage uses a local-inertial regular-grid finite-volume screening solver, NOT Delft3D or SPH. It routes a hypothetical input hydrograph over real coarse terrain with gravity and Manning friction. Face discharges are positivity limited. North/east/west boundaries are closed; south allows free outflow. Source hydrograph: 1.7*b*H^(3/2), linear rise over formation time, exponential recession with a volume cap. Initial surface is dry. No base flow, infiltration, rainfall, dynamic breach growth, channel bathymetry, subgrid buildings or dam defences are represented. This may cause deep local ponding on coarse terrain. The model should not be described as a validated Tehri dam-break prediction.

The separate 204-particle SPH lab is a 2D weakly compressible SPH tank experiment with pressure, viscosity and gravity. Simplified wall collisions and a small particle count make it educational, not a benchmark-certified DualSPHysics run. It does not generate the map.

The bundled baseline was computed by the same worker as live runs. Dry rest, positive depth, input volume and conservation checks are in scripts/check-model.cjs. Conservation is necessary but does not establish hydrodynamic accuracy. A Ritter dry-bed benchmark, grid convergence and field/published-case validation remain future work.

## Real data
Tehri/Bhagirathi regional terrain: https://elevation-tiles-prod.s3.amazonaws.com/terrarium/10/735/421.png
Catalogue: https://registry.opendata.aws/terrain-tiles/
Attribution: https://github.com/tilezen/joerd/blob/master/docs/attribution.md
Downloaded 2026-09-22. Decode Terrarium, resample to uniform latitude, then 2x2 mean to a 128x128 grid (~264 m). Vertical units are metres. No surveyed bed correction was applied. Tile sources may combine elevation products; consult source attribution before reusing.
Dam reference: https://www.thdc.co.in/en/projects/hydro/tehri-dam-HPP-stage-I
Official dam dimensions/storage are references; current reservoir telemetry is not connected.

## Large source rasters
Install Python dependencies using `python -m pip install -r requirements.txt`.
`python prepare_dem.py dem.tif catchment.asc --bounds W S E N`
GDAL reads from the source raster without loading it all into application memory. Output is bounded to 40,000 cells by default. The dashboard accepts <=60,000 cells / 25 MB. This is preprocessing for large inputs, NOT an unbounded production simulation backend. Use only metre elevations and verify vertical datum. NoData must be resolved before import.

## External engines: required for the full SIH specification
- DualSPHysics: https://dual.sphysics.org/ ; official example https://github.com/DualSPHysics/DualSPHysics/tree/master/examples/main/01_DamBreak
- Delft3D / D-Flow FM: https://oss.deltares.nl/web/delft3dfm

These engines are NOT installed, hosted, automatically configured, or executed by this prototype. Prepare and run a validated model externally using a suitable CPU/GPU machine. Use identical study bounds, vertical datum, hydrograph and time window. For SPH, reconstruct maximum water depth on a georeferenced raster from particle output. For Delft3D, export maximum water depth from the model results to a GeoTIFF. Then:
`python depth_to_geojson.py max_depth.tif model-result.geojson`
Import the output into the matching model card. The dashboard requires simple non-overlapping polygons within its active DEM and numeric depth_m. It reports area above 0.3 m and maximum depth; it does not infer model accuracy or benchmark timing.

## GIS output
The dashboard exports KML directly, satisfying the .shp OR .kml requirement for a prototype. To get Shapefile:
`python geojson_to_shp.py jaldrishti-inundation.geojson inundation`
Distribute all .shp/.shx/.dbf/.prj/.cpg components together. Cell polygons intentionally remain unmerged to retain depth/arrival attributes.

## Exposure schema
FeatureCollection of Points in EPSG:4326. Required properties: name (string), population (nonnegative number), value_inr (nonnegative replacement value). Optional type. All points must lie inside the DEM. Default points are generated from wet cells for interface demonstration and are not towns or official data.
Loss proxy: replacement value * min(depth/5, 0.8), deliberately uncalibrated. Depth classes: low >=0.3 m, moderate >=1 m, high >=3 m. These are interface classes, not an official hazard classification. First wetting is NOT an evacuation deadline.

## Satellite framework
The downloadable GEE script uses Sentinel-1 VV before/after linear-power ratio, dark-water threshold, matching orbit, permanent-water mask, slope <5 degrees and minimum connected pixels. An authorised GEE project and available acquisitions are required. It is not continuous real-time monitoring; radar shadows, vegetation and thresholds require local verification. Export and simplify polygons to single outer rings within the DEM before importing them.

## Official architecture
Site / scenario input → data and terrain processing → Fast Screening → required SPH + Delft3D → engine-specific scenario library → interpolation → validation → impact / GEE / export → command centre.

Fast Screening is preliminary. The SPH Concept Lab is educational. Neither replaces actual geospatial SPH and Delft3D river runs.

## Remaining work for full operational / final integration
1. Install and automate genuine SPH and Delft3D jobs on a server with case generation, queues, mesh/particle preparation and output normalization.
2. Connect authenticated GEE processing and store acquisition timestamps; add near-real-time job scheduling.
3. Obtain suitable river bathymetry, reservoir levels, hydrological boundaries, population/asset inventories and calibrated depth–damage functions.
4. Validate breach assumptions, model convergence, conservation and observed inundation against an accepted benchmark and Indian case study.
5. Move large-domain jobs, raster pyramids and long-running output storage to a production backend.

No authentication credentials, alerts to officials, live emergency instructions or evacuation routes are included.
