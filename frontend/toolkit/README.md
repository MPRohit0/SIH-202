# Sentriq · SIH 26161 modelling toolkit

Sentriq is an interactive research prototype for dam-break and controlled-release screening, using a prepared Tehri / Bhagirathi terrain domain.

## Demonstration sequence
1. On the homepage, drag the terrain and change breach severity. Query timing measures local interpolation only.
2. Launch Simulation. Rapid query blends four previously computed breach-width scenarios (25%, 50%, 75%, 100% of a hypothetical 240 m breach).
3. Switch to Physics run. Change parameters or import a time_min,flow_m3s CSV, then run. The worker computes real depth, approximate cell-centred velocity, first wetting, hydrograph and volume accounting.
4. Use 2D map layers and flood playback. The 3D mesh uses the actual DEM and exaggerated relief; software rendering supports devices without WebGL.
5. Open Compare Models. Run the separate educational SPH tank experiment or import external geospatial SPH/Delft3D outputs.
6. Inspect the exposure inventory. Default points and populations are synthetic. Replace them with georeferenced point GeoJSON.
7. Export a Shapefile ZIP, KML, GeoJSON, printable report or complete scenario JSON. Metadata accompanies the selected scenario.
8. Generate an Earth Engine script, run it in an authorised GEE project, review results and import observed polygons.
9. Save a scenario to authenticated cloud storage, or explicitly prepare an offline copy on your device. Add Site creates four new screening scenarios from an uploaded DEM.

## Scientific scope
The geospatial engine is a local-inertial regular-grid finite-volume screening solver. It is not Delft3D or geospatial SPH. Face discharges are positivity limited. North/east/west boundaries are closed; south permits free outflow. The illustrative breach hydrograph uses Q = 1.7*b*H^(3/2), a linear rise, exponential recession and volume cap. A discharge CSV overrides that boundary. Controlled release supports gate count and ramp-up.

The model starts dry. It does not represent base flow, rainfall, infiltration, dynamic breach growth, surveyed bathymetry, subgrid buildings or flood defences. Coarse terrain may produce deep local ponding. Cell velocity is approximated from face discharges and water depth; it is not a calibrated hazard product. Neither field accuracy nor a confidence probability is claimed.

Interpolation is component-wise linear interpolation between adjacent cached breach widths, with other parameters fixed. It does not solve the hydraulic equations. Arrival time is interpolated only where both neighbours become wet; a location reached by only one neighbour is marked separately. Spread reflects scenario sensitivity, not statistical confidence.

The SPH laboratory is a separate 204-particle weakly compressible tank experiment with pressure, viscosity, gravity and simplified boundary collisions. It does not generate the geospatial map and is not a certified DualSPHysics benchmark.

## Terrain provenance
Tehri / Bhagirathi elevation tile: https://elevation-tiles-prod.s3.amazonaws.com/terrarium/10/735/421.png
Catalogue: https://registry.opendata.aws/terrain-tiles/
Attribution: https://github.com/tilezen/joerd/blob/master/docs/attribution.md
Downloaded 2026-09-22. Terrarium elevation is decoded, resampled to uniform latitude, and averaged to a 128 × 128 grid (~264 m). Vertical units are metres. No surveyed bed correction is applied.
Dam reference: https://www.thdc.co.in/en/projects/hydro/tehri-dam-HPP-stage-I
Reservoir telemetry is not connected. Breach and discharge parameters are illustrative.

## Prepare large source rasters
Install dependencies: `python -m pip install -r requirements.txt`
Prepare an area: `python prepare_dem.py dem.tif catchment.asc --bounds W S E N`
GDAL reads the source window without loading the entire raster. The output defaults to at most 40,000 cells; browser imports accept up to 60,000 cells / 25 MB. Resolve NoData and verify vertical datum and metre elevations before importing. Production-scale domains require a dedicated modelling backend.

## External engines
DualSPHysics: https://dual.sphysics.org/
Delft3D / D-Flow FM: https://oss.deltares.nl/web/delft3dfm
These engines are not installed or executed by the prototype. Run them externally with a suitable validated case, matching terrain, datum, boundary hydrograph and simulation window. Reconstruct maximum depth on a georeferenced raster, then:
`python depth_to_geojson.py max_depth.tif model-result.geojson`
Import simple non-overlapping WGS84 polygons inside the active DEM, each with numeric depth_m. The dashboard compares area above 0.3 m and peak depth. Model agreement does not establish accuracy.

## GIS output
Direct Shapefile export contains .shp, .shx, .dbf, .prj and scenario-metadata.json. DBF field names may be shortened; full assumptions remain in metadata. Cell polygons are intentionally unmerged to retain per-cell attributes. KML and GeoJSON include metadata. Alternative conversion:
`python geojson_to_shp.py sentriq-inundation.geojson inundation`

## Exposure input
GeoJSON FeatureCollection of Points in EPSG:4326 within the active DEM. Required properties: name (string), population (nonnegative number). Optional: type, buildings, area_ha. Use School or Health facility for critical facilities. Agricultural area is a point-inventory proxy, not raster overlap. No monetary loss is calculated. Depth classes low >=0.3 m, moderate >=1 m, high >=3 m are illustrative interface classes. First wetting is not an evacuation deadline.

## Satellite workflow
Sentinel-1 VV before/after linear-power ratios, matched orbit, permanent-water masking, slope filtering and connected-pixel screening are included in the downloadable GEE script. It requires an authorised Earth Engine project and available acquisitions. Radar shadows, vegetation, terrain and thresholds require local checks. Imported polygons retain their supplied attributes. Import time is not satellite acquisition time. No live processing connection is implied.

## Remaining production integration
- Automate genuine geospatial SPH and Delft3D runs on suitable CPU/GPU infrastructure.
- Connect an authorised GEE project with acquisition timestamps and job scheduling.
- Add surveyed bathymetry, measured boundary conditions and verified exposure inventories.
- Validate benchmark behaviour, convergence and Indian case-study accuracy.
- Expand raster processing, monitoring and job queues for production domains.
