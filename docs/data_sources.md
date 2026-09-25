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

## src_037 — CartoDEM, NRSC Bhoonidhi

National Remote Sensing Centre (ISRO), *CartoDEM* (version and release TBD — no public bulk-download
API; tiles must be requested/downloaded manually from Bhoonidhi, https://bhoonidhi.nrsc.gov.in).
**Version and vertical datum not yet confirmed** — do not set `status: sourced` on anything citing
this entry until both are filled in here (contract §1.3: "check CartoDEM's documentation").

Used for: the highest-resolution DEM candidate where available, mosaicked by
`backend/m1_terrain/download.py --cartodem-dir`.
