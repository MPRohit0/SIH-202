"""Tests for backend.m6_impact.exposure_osm — Overpass element parsing, GPKG
writing and skip-existing behaviour. No real network access: Overpass
responses are canned dicts, matching the `out geom;` element shape."""

from __future__ import annotations

import json

import geopandas as gpd
import pytest

from backend.m6_impact import exposure_osm as osm

BBOX = [88.45, 27.45, 88.55, 27.55]


def _way(id_, coords, tags):
    """coords: list of (lon, lat)."""
    return {
        "type": "way", "id": id_, "tags": tags,
        "geometry": [{"lat": lat, "lon": lon} for lon, lat in coords],
    }


def _node(id_, lon, lat, tags):
    return {"type": "node", "id": id_, "lat": lat, "lon": lon, "tags": tags}


# --------------------------------------------------------------------------- bbox / query


def test_bbox_south_west_north_east_order():
    assert osm._bbox_south_west_north_east(BBOX) == "(27.45,88.45,27.55,88.55)"


def test_build_query_contains_all_statements_and_out_geom():
    cats = osm.categories(BBOX)
    query = osm.build_query(cats["facilities"])
    for stmt in cats["facilities"].statements:
        assert stmt in query
    assert query.strip().endswith("out geom;")


# --------------------------------------------------------------------------- element -> row parsing


def test_buildings_polygon_from_closed_way():
    cat = osm.categories(BBOX)["buildings"]
    ring = [(88.50, 27.50), (88.501, 27.50), (88.501, 27.501), (88.50, 27.501), (88.50, 27.50)]
    elements = [_way(1, ring, {"building": "residential"})]
    rows = osm.elements_to_rows(elements, cat)
    assert len(rows) == 1
    assert rows[0]["osm_id"] == "way/1"
    assert rows[0]["kind"] == "residential"
    assert rows[0]["geometry"].geom_type == "Polygon"


def test_building_yes_tag_becomes_generic_building_kind():
    cat = osm.categories(BBOX)["buildings"]
    ring = [(88.50, 27.50), (88.501, 27.50), (88.501, 27.501), (88.50, 27.50)]
    rows = osm.elements_to_rows([_way(2, ring, {"building": "yes"})], cat)
    assert rows[0]["kind"] == "building"


def test_roads_line_from_way():
    cat = osm.categories(BBOX)["roads"]
    line = [(88.50, 27.50), (88.51, 27.51)]
    rows = osm.elements_to_rows([_way(3, line, {"highway": "primary", "name": "NH10"})], cat)
    assert len(rows) == 1
    assert rows[0]["kind"] == "primary"
    assert rows[0]["name"] == "NH10"
    assert rows[0]["geometry"].geom_type == "LineString"


def test_roads_ignores_non_highway_way():
    cat = osm.categories(BBOX)["roads"]
    rows = osm.elements_to_rows([_way(4, [(88.5, 27.5), (88.51, 27.51)], {"building": "yes"})], cat)
    assert rows == []


def test_facilities_hospital_node_and_bridge_way():
    cat = osm.categories(BBOX)["facilities"]
    elements = [
        _node(10, 88.50, 27.50, {"amenity": "hospital", "name": "District Hospital"}),
        _way(11, [(88.5, 27.5), (88.51, 27.5)], {"bridge": "yes"}),
        _node(12, 88.5, 27.5, {"shop": "bakery"}),  # not a facility -> dropped
    ]
    rows = osm.elements_to_rows(elements, cat)
    kinds = {r["kind"] for r in rows}
    assert kinds == {"hospital", "bridge"}
    assert all(r["geometry"].geom_type == "Point" for r in rows)


def test_places_filters_to_allowed_place_values():
    cat = osm.categories(BBOX)["places"]
    elements = [
        _node(20, 88.5, 27.5, {"place": "village", "name": "Lachen"}),
        _node(21, 88.5, 27.5, {"place": "islet", "name": "Not wanted"}),
    ]
    rows = osm.elements_to_rows(elements, cat)
    assert len(rows) == 1
    assert rows[0]["name"] == "Lachen"


def test_relations_are_never_included():
    cat = osm.categories(BBOX)["buildings"]
    elements = [{"type": "relation", "id": 99, "tags": {"building": "yes"}, "members": []}]
    assert osm.elements_to_rows(elements, cat) == []


def test_way_with_too_few_geometry_points_is_dropped():
    cat = osm.categories(BBOX)["roads"]
    elements = [_way(5, [(88.5, 27.5)], {"highway": "track"})]
    assert osm.elements_to_rows(elements, cat) == []


# --------------------------------------------------------------------------- fetch_category / GPKG output


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeClient:
    """Stands in for httpx.Client: counts calls, returns canned Overpass JSON."""

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def post(self, endpoint, data, **kwargs):
        self.calls += 1
        return _FakeResponse(self.payload)


def test_fetch_category_writes_gpkg_with_contract_columns(tmp_path):
    cat = osm.categories(BBOX)["places"]
    payload = {"elements": [_node(1, 88.5, 27.5, {"place": "town", "name": "Singtam"})]}
    client = _FakeClient(payload)
    out_path = tmp_path / "places.gpkg"

    entry = osm.fetch_category("places", cat, BBOX, out_path, client=client)

    assert entry["status"] == "fetched"
    assert entry["feature_count"] == 1
    assert client.calls == 1
    gdf = gpd.read_file(out_path)
    assert list(gdf.columns[:3]) == ["osm_id", "kind", "name"]
    assert gdf.crs.to_epsg() == 4326
    assert gdf.iloc[0]["kind"] == "town"


def test_fetch_category_skips_when_file_exists(tmp_path):
    cat = osm.categories(BBOX)["places"]
    out_path = tmp_path / "places.gpkg"
    out_path.write_text("not really a gpkg, just needs to exist")
    client = _FakeClient({"elements": []})

    entry = osm.fetch_category("places", cat, BBOX, out_path, client=client)

    assert entry == {"file": "places.gpkg", "status": "skipped_existing"}
    assert client.calls == 0


def test_fetch_category_empty_result_still_writes_valid_gpkg(tmp_path):
    cat = osm.categories(BBOX)["facilities"]
    client = _FakeClient({"elements": []})
    out_path = tmp_path / "facilities.gpkg"

    entry = osm.fetch_category("facilities", cat, BBOX, out_path, client=client)

    assert entry["feature_count"] == 0
    gdf = gpd.read_file(out_path)
    assert len(gdf) == 0
    assert list(gdf.columns[:3]) == ["osm_id", "kind", "name"]


def test_merge_provenance_writes_and_updates(tmp_path):
    osm._merge_provenance(tmp_path, {"osm_places": {"status": "fetched", "feature_count": 3}})
    osm._merge_provenance(tmp_path, {"osm_roads": {"status": "fetched", "feature_count": 7}})

    written = json.loads((tmp_path / "provenance.json").read_text(encoding="utf-8"))
    assert written["osm_places"]["feature_count"] == 3
    assert written["osm_roads"]["feature_count"] == 7


# --------------------------------------------------------------------------- fetch_all


def test_fetch_all_rejects_placeholder_bbox(synth_config):
    cfg = synth_config.model_copy(deep=True)
    cfg.domains.far_field.bbox.value = None
    cfg.domains.far_field.bbox.status = "placeholder"
    with pytest.raises(ValueError, match="placeholder"):
        osm.fetch_all(cfg, data_dir=None)  # bbox check happens before data_dir is touched


def test_fetch_all_skips_categories_whose_files_already_exist(tmp_path, synth_config, monkeypatch):
    exposure_dir = tmp_path / synth_config.site.id / "exposure"
    exposure_dir.mkdir(parents=True)
    for name, cat in osm.categories(synth_config.domains.far_field.bbox.value).items():
        (exposure_dir / cat.filename).write_text("placeholder file")

    def _boom(*args, **kwargs):
        raise AssertionError("Overpass should not be queried when all files already exist")

    monkeypatch.setattr(osm, "run_overpass_query", _boom)
    results = osm.fetch_all(synth_config, data_dir=tmp_path)
    assert all(r["status"] == "skipped_existing" for r in results.values())


def test_fetch_all_rerun_does_not_clobber_existing_provenance(tmp_path, synth_config, monkeypatch):
    exposure_dir = tmp_path / synth_config.site.id / "exposure"
    exposure_dir.mkdir(parents=True)
    rich_entry = {"status": "fetched", "feature_count": 42, "query": "..."}
    osm._merge_provenance(exposure_dir, {"osm_places": rich_entry})
    for name, cat in osm.categories(synth_config.domains.far_field.bbox.value).items():
        (exposure_dir / cat.filename).write_text("placeholder file")
    monkeypatch.setattr(osm, "run_overpass_query", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))

    osm.fetch_all(synth_config, data_dir=tmp_path)

    written = json.loads((exposure_dir / "provenance.json").read_text(encoding="utf-8"))
    assert written["osm_places"] == rich_entry
