# Data sources

Every fact in `sites/*.yaml`, `data/<site_id>/exposure/*.csv` and any other `SourcedValue`-shaped
input cites one of the IDs below in its `source` field. Add a new entry here before setting
`status: sourced` on a value that uses it (CLAUDE.md rule 3).

## src_031 — JRC global flood depth-damage functions (damage curves)

Huizinga, J., de Moel, H., Szewczyk, W. (2017). *Global flood depth-damage functions:
methodology and the database with guidelines.* European Commission Joint Research Centre,
EUR 28552 EN. doi: [10.2760/16510](https://doi.org/10.2760/16510).

Used for: `data/<site_id>/exposure/damage_curves.csv` (`backend/m6_impact/jrc_damage.py`),
the fractional depth-damage curves, ASIA continent column, 6 impact categories
(residential, commercial, industrial, transport, infrastructure-roads, agriculture),
0-6 m depth. Local copy: `data/copy_of_global_flood_depth-damage_functions__30102017.xlsx`
(gitignored, `data/` — not committed; re-download from the JRC data catalogue to reproduce).

## src_032 — JRC global flood depth-damage functions (max damage values)

Same source and workbook as src_031, its six `MaxDamage-*` sheets (country-level maximum
damage values, 2010 price level).

Used for: `data/<site_id>/exposure/asset_values.csv` (`backend/m6_impact/jrc_damage.py`),
India's max-damage values: `value_eur2010` per m2 (building-based Total for residential/
commercial/industrial; value-added/ha converted to per-m2 for agriculture; GDP-per-capita-
scaled for infrastructure-roads/transport, per each sheet's own documented method). Each
`asset_values.csv` row's `jrc_cell` names the exact sheet and cell(s) the number came from.

**Known limitation** (`docs/impact_outputs.md` §5): these are 2010 national averages for
India. Himalayan stone or timber-built houses may cost quite differently to rebuild; treat
`loss_inr` as a rough estimate, not a precise valuation.

**Not yet sourced** (both placeholders in `config/impact.yaml`, per `docs/decisions.md`
2026-09-25): the 2010 annual-average EUR->INR rate (RBI reference rate) and the 2010->current
Indian price index (CPWD cost index or WPI, team to choose). `loss_inr.by_asset_class[*]`
stays a null Estimate until both are filled in.

## src_033 — SRTM GL1 (30 m), NASA JPL

NASA JPL (2013). *NASA Shuttle Radar Topography Mission Global 1 arc second [SRTMGL1].*
NASA EOSDIS Land Processes DAAC. doi: [10.5067/MEaSUREs/SRTM/SRTMGL1.003](https://doi.org/10.5067/MEaSUREs/SRTM/SRTMGL1.003).
**Verify this DOI before setting `status: sourced` on anything citing it** — written from memory
this session, not fetched from the DOI resolver.

Used for: one of the DEM candidates `backend/m1_terrain/download.py` fetches for the M1-2 DEM
comparison report (`data/<site_id>/raw/dem_srtm_gl1.tif`). Vertical datum: EGM96 geoid (contract
§1.3). Not yet used for anything downstream — DEM choice happens after the comparison report.

## src_034 — Copernicus DEM GLO-30, ESA / Airbus

European Space Agency, Sinergise (2021). *Copernicus Global Digital Elevation Model, GLO-30.*
Distributed via OpenTopography. doi: [10.5270/ESA-c5d3d65](https://doi.org/10.5270/ESA-c5d3d65).
**Verify this DOI before setting `status: sourced`** — same caveat as src_033.

Used for: another DEM candidate (`data/<site_id>/raw/dem_copernicus_glo30.tif`). Vertical datum:
EGM2008 geoid (contract §1.3).

## src_035 — OpenTopography Global DEM API

Access route for src_033/src_034: `https://portal.opentopography.org/API/globaldem`
(`demtype=SRTMGL1|COP30`), authenticated with an API key
(`.env` `OPENTOPOGRAPHY_API_KEY`, CLAUDE.md rule 12 — never logged or committed). Not a dataset
citation on its own; always cite src_033/src_034 for the actual DEM.

## src_036 — ESA WorldCover 10 m v200 (2021)

Zanaga, D. et al. (2022). *ESA WorldCover 10 m 2021 v200.* doi:
[10.5281/zenodo.7254221](https://doi.org/10.5281/zenodo.7254221). Public COG tiles at
`s3://esa-worldcover/v200/2021/map/` (`eu-central-1`, no auth needed).
**Verify this DOI before setting `status: sourced`** — same caveat as src_033.

Used for: `data/<site_id>/raw/landcover_esa_worldcover.tif` (`backend/m1_terrain/download.py`),
a landcover candidate feeding M1's `roughness.tif` (Manning's n lookup by class).

## src_043 — Historical Teesta III project parameters (existing CFRD)

Government of India, Ministry of Environment, Forest and Climate Change. *Minutes of the 19th
Meeting of the Expert Appraisal Committee (River Valley and Hydroelectric Projects), Teesta
Stage III HE Project agenda/site-visit materials*, 2024. [PARIVESH document](https://parivesh.nic.in/utildoc/114429141_1733834917785.pdf).
Use the table column labelled **Existing Salient Features** for the historical 2023 dam: CFRD,
60 m maximum height above riverbed, FRL EL 1585 m, MDDL EL 1565 m, gross storage 5.08 MCM
(EL 1530–1585 m), live storage 3.33 MCM (EL 1565–1585 m), and catchment 2786.7 km². The same
document separately describes a proposed replacement concrete-gravity dam; that replacement is
not the 2023 structure and must not be used for the historical event.

## src_044 — Sikkim 2023 flood reconstruction and cascade impacts

Authors, *The Sikkim flood of October 2023: Drivers, causes and impacts of a multihazard cascade*.
[White Rose repository record and paper](https://eprints.whiterose.ac.uk/id/eprint/224098/).
The paper reports its reconstruction reaching Chungthang at about 00:30 IST on 4 October and a
modelled peak discharge of about 5340 m³/s there. It does **not** provide the complete observed
hydrograph needed by M3. These values differ from the 03:20 / 7355 m³/s MVP reconstruction
targets; the latter must remain explicitly imposed targets, not attributed to this source.

## src_045 — South Lhonak GLOF discharge reconstruction (2025)

Gaikwad, D., Tiwari, R.K. & Goswami, A. (2025). *Reconstruction of the 2023 South Lhonak Lake
outburst flood and modelling future scenarios in the Sikkim Himalaya*. Natural Hazards.
doi: [10.1007/s11069-025-07350-9](https://doi.org/10.1007/s11069-025-07350-9). The abstract reports
modelled (not observed) peak discharge of approximately 7355 m³/s at Chungthang for the actual
event reconstruction. This is one reconstruction result, not a complete measured hydrograph.

## src_046 — CWC preliminary Teesta basin incident report

Central Water Commission / National Dam Safety Authority, *Preliminary report on incident
occurred on 04.10.2023 in Teesta Basin of Sikkim*, in the [3rd NCDS meeting agenda pack](https://cwc.gov.in/sites/default/files/agenda-3rd-ncds-meeting.pdf).
Records the 4 October event in the Teesta basin and impacts to Teesta III. Use for incident
context only; it is not a complete discharge time series.

## src_048 — OpenStreetMap exposure extract

OpenStreetMap contributors, data under the Open Database License (ODbL). Attribution and
licence: [OpenStreetMap copyright and licence](https://www.openstreetmap.org/copyright).
Project extracts are stored in `data/<site_id>/exposure/{buildings,roads,facilities,places}.gpkg`.
The Teesta files present at MVP time were retained pre-existing extracts; their original fetch
timestamp and exact Overpass request are not recorded in `data/teesta/exposure/provenance.json`.
Treat coverage and currency as unknown; do not infer that omitted assets are absent.

## src_049 — WorldPop 2020 India, 1 km, UN-adjusted population counts

WorldPop, University of Southampton. *Global 2000–2020, 1 km, UN-adjusted population counts*.
[Dataset description](https://hub.worldpop.org/Global1_2000-2020) and [2020 India raster](https://data.worldpop.org/GIS/Population/Global_2000_2020_1km_UNadj/2020/IND/).
The stored Teesta raster derives from the 2020 India raster, is clipped and sum-preserving
resampled to the project's 30 m far-field grid, and uniformly disaggregates source-cell counts;
it is not building-level detail or a current census. License: CC BY 4.0.

## src_037 — CartoDEM, NRSC Bhoonidhi

National Remote Sensing Centre (ISRO), *CartoDEM* (version and release TBD — no public bulk-download
API; tiles must be requested/downloaded manually from Bhoonidhi, https://bhoonidhi.nrsc.gov.in).
**Version and vertical datum not yet confirmed** — do not set `status: sourced` on anything citing
this entry until both are filled in here (contract §1.3: "check CartoDEM's documentation").

Used for: the highest-resolution DEM candidate where available, mosaicked by
`backend/m1_terrain/download.py --cartodem-dir`.

## src_038 — Sentinel-2 MSI Level-2A (surface reflectance), Copernicus / ESA

Copernicus Sentinel-2 (processed by ESA). *MSI Level-2A BOA Reflectance Product.* European Space
Agency. Accessed via Google Earth Engine `COPERNICUS/S2_SR_HARMONIZED`. No single DOI — ESA's
recommended citation form is dataset + processor + agency, not a versioned paper. **Verify the
current recommended citation wording on sentinels.copernicus.eu before setting `status: sourced`**
— it has changed collection-to-collection (Collection 1 vs earlier).

Used for: `backend/m7_gee/provider.py` `s2_month` — monthly cloud-masked NDWI composites for
`lake_area.csv` (`method: s2_water_index`), masked by the SCL band's cloud/cloud-shadow/cirrus
classes (3, 8, 9, 10) and its snow/ice class (11).

## src_039 — Sentinel-1 GRD (C-band SAR), Copernicus / ESA

ESA/Copernicus. *Sentinel-1 Level-1 Ground Range Detected (GRD).* Accessed via Google Earth Engine
`COPERNICUS/S1_GRD`. No single citable DOI (a mission/processor citation, not a dataset paper) —
same caveat as src_038.

Used for: `backend/m7_gee/scene_search.py` (scene browsing) and `backend/m7_gee/provider.py`
`s1_month` — the cloud-free fallback for monthly lake-area classification (`method:
s1_threshold`), VV backscatter thresholded.

## src_040 — CHIRPS Daily (rainfall), Climate Hazards Center / UCSB

Funk, C. et al. (2015). *The climate hazards infrared precipitation with stations—a new
environmental record for monitoring extremes.* Scientific Data, 2, 150066. doi:
[10.1038/sdata.2015.66](https://doi.org/10.1038/sdata.2015.66). Accessed via Google Earth Engine
`UCSB-CHG/CHIRPS/DAILY`. **Verify this DOI before setting `status: sourced`** — same caveat as
src_033. Known limitation (CLAUDE.md "Known limitations"): satellite-IR-based rainfall estimates
like CHIRPS tend to underestimate orographic (high-mountain) precipitation in steep Himalayan
terrain — flagged as caveat `chirps_mountain_underestimate` wherever CHIRPS is used.

Used for: `backend/m7_gee/provider.py` `rainfall_daily` (default dataset, `GeeSettings.
rain_dataset = "chirps"`) — catchment-mean daily rainfall for `rainfall.csv`. `GPM_IMERG`
(`NASA/GPM_L3/IMERG_V07`, no separate entry here — a NASA, not ESA/UCSB, product) is the
alternative (`--rain-dataset gpm_imerg`).

## src_041 — HydroBASINS level 12, HydroSHEDS / WWF

Lehner, B., Grill, G. (2013). *Global river hydrography and network routing: baseline data and new
approaches to study the world's large river systems.* Hydrological Processes, 27(15), 2171–2186.
doi: [10.1002/hyp.9740](https://doi.org/10.1002/hyp.9740). Accessed via Google Earth Engine
`WWF/HydroSHEDS/v1/Basins/hybas_12`. **Verify this DOI before setting `status: sourced`** — same
caveat as src_033.

Used for: `backend/m7_gee/provider.py` `catchment` — the rainfall catchment (the HydroBASINS
level-12 basin containing the lake, plus every basin upstream of it via `NEXT_DOWN`) that
`rainfall.csv` is averaged over. `docs/decisions.md` "M7 GEE fetch" has the reasoning for why
HydroBASINS was picked over an M1-derived flow-accumulation catchment.

## src_042 — Chamoli 2021 rock–ice avalanche reconstruction

Shugar, D. H. et al. (2021). *A massive rock and ice avalanche caused the 2021 disaster at
Chamoli, Indian Himalaya.* Science, 373, eabh4455. doi:
[10.1126/science.abh4455](https://doi.org/10.1126/science.abh4455). Open author manuscript and
supplementary materials: <https://eprints.whiterose.ac.uk/id/eprint/175202/>.

Used for: `docs/events/chamoli_2021.md`'s event onset, source-volume estimate, flow-process
classification, and the reported discharge/velocity bounds near the Rishiganga and Tapovan
projects. The paper does not provide a machine-ready discharge hydrograph or a catchment-wide
observed flood-depth raster; see the event record for M3 limits.
