"""Tests for backend.m6_impact.exports: the shapefile/KML/PDF export builders behind
`GET /export/{query_id}` (docs/handoff_contract.md §4.7 "Exports").

These exercise the builders directly (no HTTP), plus regression tests for the two bugs the
export route shipped with: an incomplete/mis-attributed shapefile bundle, and a PDF that was
effectively blank (its report text lived inside a PDF comment, which no viewer renders)."""

from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
import pytest
from pypdf import PdfReader

from backend.m6_impact import exports

EXTENT_GEOJSON = {
    "type": "FeatureCollection",
    "features": [{
        "type": "Feature",
        "properties": {"source_run_id": "teesta_2023_mvp__delft3d", "synthetic": False},
        "geometry": {"type": "Polygon", "coordinates": [
            [[88.60, 27.60], [88.61, 27.60], [88.61, 27.61], [88.60, 27.61], [88.60, 27.60]],
        ]},
    }],
}

MULTI_WITH_HOLE_GEOJSON = {
    "type": "FeatureCollection",
    "features": [{"type": "Feature", "properties": {}, "geometry": {"type": "MultiPolygon", "coordinates": [
        [[[88.0, 27.0], [88.1, 27.0], [88.1, 27.1], [88.0, 27.1], [88.0, 27.0]],
         [[88.02, 27.02], [88.02, 27.04], [88.04, 27.04], [88.04, 27.02], [88.02, 27.02]]],
        [[[88.5, 27.5], [88.6, 27.5], [88.6, 27.6], [88.5, 27.6], [88.5, 27.5]]],
    ]}}]}

SUMMARY = {
    "max_depth_m": {"value": 66.89, "low": None, "high": None, "unit": "m"},
    "max_velocity_ms": {"value": 32.77, "low": None, "high": None, "unit": "m/s"},
    "inundated_area_m2": {"value": 19043100.0, "low": None, "high": None, "unit": "m2"},
    "peak_discharge_m3s": {"value": None, "low": None, "high": None, "unit": "m3/s"},
    "first_arrival": {"poi_id": "teesta__poi__chungthang", "name": "Chungthang",
                       "arrival_s": {"value": 22920.0, "low": None, "high": None, "unit": "s"}},
}

CAVEATS = [
    {"id": "direct_solver_output", "severity": "warning", "text_key": "caveat_direct_solver_output"},
    {"id": "dem_depression_ponding", "severity": "warning", "text_key": "caveat_dem_depression_ponding"},
]

WARNING_TABLE = [{
    "poi_id": "teesta__poi__chungthang", "name": "Chungthang", "kind": "village", "chainage_m": 70224.9,
    "zone": "possible", "p_inundation": 1.0,
    "arrival_s": {"value": 22920.0, "unit": "s", "confidence": "LOW"},
    "depth_m": {"value": 11.6, "unit": "m"},
    "velocity_ms": {"value": 5.46, "unit": "m/s"},
}]

POI_LOCATIONS = {"chungthang": (88.646, 27.603)}


# ---- depth class / caveat labels ----

@pytest.mark.parametrize("depth,expected", [
    (None, None), (0.0, None), (0.05, None),
    (0.1, "wet"), (0.29, "wet"),
    (0.3, "low"), (0.99, "low"),
    (1.0, "moderate"), (1.99, "moderate"),
    (2.0, "high"), (4.99, "high"),
    (5.0, "extreme"), (66.89, "extreme"),
])
def test_depth_class_label(depth, expected):
    assert exports.depth_class_label(depth) == expected


def test_caveat_label_known_id_is_readable_sentence():
    label = exports.caveat_label({"id": "dem_depression_ponding"})
    assert "DEM depression" in label


def test_caveat_label_unknown_id_falls_back_to_readable_id():
    label = exports.caveat_label({"id": "some_new_caveat"})
    assert label == "Some new caveat"


# ---- shapefile bundle ----

def test_shapefile_zip_has_all_sidecars_and_correct_crs():
    content = exports.build_shapefile_zip(
        EXTENT_GEOJSON, site_id="teesta", query_id="q_test", run_ids=["teesta_2023_mvp__delft3d"],
        method="delft3d_direct", zone="possible", confidence_level="LOW", has_placeholders=True,
        caveats=CAVEATS, summary=SUMMARY, warning_table=WARNING_TABLE, poi_locations=POI_LOCATIONS,
    )
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        assert archive.testzip() is None
        names = set(archive.namelist())
        assert {"extent.shp", "extent.shx", "extent.dbf", "extent.prj", "extent.cpg"}.issubset(names)
        assert {"pois_warning.shp", "pois_warning.shx", "pois_warning.dbf", "pois_warning.prj"}.issubset(names)
        assert "README.txt" in names
        with tempfile.TemporaryDirectory() as tmp:
            archive.extractall(tmp)
            extent = gpd.read_file(Path(tmp) / "extent.shp")
            assert str(extent.crs) == "EPSG:4326"
            assert len(extent) == 1
            row = extent.iloc[0]
            assert row["site_id"] == "teesta"
            assert row["query_id"] == "q_test"
            assert row["method"] == "delft3d_direct"
            assert row["zone"] == "possible"
            assert row["dep_class"] == "extreme"  # 66.89 m
            assert row["has_ph"] == 1
            assert "direct_solver_output" in row["caveats"]

            pois = gpd.read_file(Path(tmp) / "pois_warning.shp")
            assert len(pois) == 1
            assert pois.iloc[0]["name"] == "Chungthang"
            assert pois.iloc[0].geometry.x == pytest.approx(88.646)
            assert pois.iloc[0].geometry.y == pytest.approx(27.603)


def test_shapefile_zip_field_names_fit_dbf_10_char_limit():
    content = exports.build_shapefile_zip(
        EXTENT_GEOJSON, site_id="teesta", query_id="q_test", run_ids=[], method="delft3d_direct",
        zone="possible", confidence_level="LOW", has_placeholders=False, caveats=[], summary=SUMMARY,
    )
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        with tempfile.TemporaryDirectory() as tmp:
            archive.extractall(tmp)
            extent = gpd.read_file(Path(tmp) / "extent.shp")
            for column in extent.columns:
                if column != "geometry":
                    assert len(column) <= 10, column


def test_shapefile_zip_skips_pois_layer_when_no_locations_known():
    content = exports.build_shapefile_zip(
        EXTENT_GEOJSON, site_id="teesta", query_id="q_test", run_ids=[], method="delft3d_direct",
        zone="possible", confidence_level="LOW", has_placeholders=False, caveats=[], summary=SUMMARY,
        warning_table=WARNING_TABLE, poi_locations={},  # no matching POI locations
    )
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        assert not any(name.startswith("pois_warning.") for name in archive.namelist())


# ---- KML ----

def test_kml_covers_every_part_of_a_multipolygon_with_holes():
    import xml.etree.ElementTree as ET

    kml = exports.extent_geojson_to_kml(MULTI_WITH_HOLE_GEOJSON, "Test extent")
    root = ET.fromstring(kml)  # raises if not well-formed XML
    ns = {"k": "http://www.opengis.net/kml/2.2"}
    polygons = root.findall(".//k:Polygon", ns)
    assert len(polygons) == 2
    assert len(root.findall(".//k:innerBoundaryIs", ns)) == 1
    outer_coords = polygons[0].find(".//k:outerBoundaryIs//k:coordinates", ns).text
    assert "88.5,27.5" not in outer_coords


def test_kml_has_a_style_and_description():
    kml = exports.extent_geojson_to_kml(EXTENT_GEOJSON, "Test extent", description="Max depth: 66.89 m")
    assert "<Style" in kml
    assert "Max depth: 66.89 m" in kml


def test_pois_kml_folder_has_one_placemark_per_located_poi():
    import xml.etree.ElementTree as ET

    folder = exports.pois_kml_folder(WARNING_TABLE, POI_LOCATIONS)
    root = ET.fromstring(f'<kml xmlns="http://www.opengis.net/kml/2.2">{folder}</kml>')
    ns = {"k": "http://www.opengis.net/kml/2.2"}
    placemarks = root.findall(".//k:Placemark", ns)
    assert len(placemarks) == 1
    assert placemarks[0].find("k:name", ns).text == "Chungthang"


def test_pois_kml_folder_empty_when_no_locations_known():
    assert exports.pois_kml_folder(WARNING_TABLE, {}) == ""


# ---- PDF ----

def _build_report(**overrides) -> bytes:
    kwargs = dict(
        site_id="teesta", site_name="Teesta basin", query_id="q_test",
        report_label="Direct solver result", is_synthetic=False, summary=SUMMARY,
        impact={"population_persons": {"value": 287.8, "unit": "persons"},
                "assets": {"buildings": {"high": 0, "possible": 346}},
                "loss_inr": {"value": None, "basis": "not computed: single deterministic run"},
                "warning_table": WARNING_TABLE},
        caveats=CAVEATS, provenance={"method": "delft3d_direct", "run_ids": ["teesta_2023_mvp__delft3d"]},
        has_placeholders=True, map_png_bytes=None, map_bounds_latlng=None, map_label=None,
    )
    kwargs.update(overrides)
    return exports.build_pdf_report(**kwargs)


def test_pdf_report_is_not_empty_and_has_at_least_one_page():
    content = _build_report()
    assert len(content) > 2000  # the old comment-only mock PDF was ~200 bytes
    reader = PdfReader(io.BytesIO(content))
    assert len(reader.pages) >= 1


def test_pdf_report_text_contains_real_numbers_and_caveats():
    content = _build_report()
    text = PdfReader(io.BytesIO(content)).pages[0].extract_text()
    assert "Teesta basin" in text
    assert "q_test" in text
    assert "66.89" in text  # max depth
    assert "32.77" in text  # max velocity
    assert "Chungthang" in text  # warning table entry
    assert "DEM depression" in text  # caveat_label(dem_depression_ponding)
    assert "delft3d_direct" in text  # provenance.method


def test_pdf_report_without_impact_says_so_rather_than_omitting_the_section():
    content = _build_report(impact=None)
    text = PdfReader(io.BytesIO(content)).pages[0].extract_text()
    assert "not available for this query" in text


def test_pdf_report_without_map_is_still_a_real_report():
    content = _build_report(map_png_bytes=None, map_bounds_latlng=None)
    assert len(content) > 1000
    text = PdfReader(io.BytesIO(content)).pages[0].extract_text()
    assert "No raster layer available" in text
    assert "66.89" in text
