"""Calls every endpoint in docs/handoff_contract.md §5 against the mock M0
server and validates each response against its contracts/schemas/*.json
schema (CLAUDE.md rule 2: every module runs end-to-end on synthetic data
with pytest tests; contract §8: the API test suite calls every endpoint and
validates every response).

`main.py` already validates its own responses before sending them (a 500
there means the server violated its own contract); this file re-validates
independently, the way a real client/CI check would, and additionally checks
status codes, error shapes and the one 404 code path the mock supports.
"""

from __future__ import annotations

import json
import zipfile
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from backend.m0_api import schemas
from backend.m0_api.main import app

client = TestClient(app)

API = "/api/v1"
KNOWN_SITE = "teesta"
OTHER_SITE = "rishiganga"
UNKNOWN_SITE = "nosuchsite"
QUERY_ID = "q_20260924T101500Z_3fa9c1"
JOB_ID = "job_20260924T101500Z_b17e02"
EVENT_ID = "teesta_2023"


def assert_matches(schema_name: str, payload) -> None:
    schemas.validate(schema_name, payload)  # raises ContractViolation on mismatch


# =============================================================================
# 1-2. health, styles
# =============================================================================
def test_health():
    r = client.get(f"{API}/health")
    assert r.status_code == 200
    assert_matches("health.schema.json", r.json())


def test_styles():
    r = client.get(f"{API}/styles")
    assert r.status_code == 200
    body = r.json()
    assert_matches("styles.schema.json", body)
    assert body["contract_version"] == "0.1.0"


# =============================================================================
# 3-4. sites
# =============================================================================
def test_list_sites():
    r = client.get(f"{API}/sites")
    assert r.status_code == 200
    body = r.json()
    assert_matches("site_list.schema.json", body)
    assert {s["site_id"] for s in body} >= {KNOWN_SITE, OTHER_SITE}


def test_get_site_detail_known():
    r = client.get(f"{API}/sites/{KNOWN_SITE}")
    assert r.status_code == 200
    body = r.json()
    assert_matches("site_detail.schema.json", body)
    assert body["site_id"] == KNOWN_SITE


def test_get_site_detail_other_site_is_patched_not_hardcoded():
    r = client.get(f"{API}/sites/{OTHER_SITE}")
    assert r.status_code == 200
    body = r.json()
    assert_matches("site_detail.schema.json", body)
    assert body["site_id"] == OTHER_SITE


def test_get_site_detail_unknown_is_404_with_error_shape():
    r = client.get(f"{API}/sites/{UNKNOWN_SITE}")
    assert r.status_code == 404
    assert_matches("error.schema.json", r.json()["detail"])
    assert r.json()["detail"]["error"]["code"] == "site_not_found"


def test_get_site_detail_malformed_id_is_422():
    r = client.get(f"{API}/sites/NOT-VALID!!")
    assert r.status_code == 422


# =============================================================================
# 5. POST /sites
# =============================================================================
def test_create_site_accepted():
    r = client.post(f"{API}/sites", json={"site_config": {"site_id": "kosi"}, "demo_mode": True})
    assert r.status_code == 202
    body = r.json()
    assert_matches("site_create_accepted.schema.json", body)
    assert body["site_id"] == "kosi"


def test_create_site_missing_config_is_422():
    r = client.post(f"{API}/sites", json={"demo_mode": True})
    assert r.status_code == 422
    assert_matches("error.schema.json", r.json()["detail"])


# =============================================================================
# 6. GET /jobs/{job_id}
# =============================================================================
def test_get_job():
    r = client.get(f"{API}/jobs/{JOB_ID}")
    assert r.status_code == 200
    body = r.json()
    assert_matches("job_status.schema.json", body)
    assert body["job_id"] == JOB_ID


# =============================================================================
# 7-8. recheck, rerun
# =============================================================================
def test_set_recheck():
    r = client.put(f"{API}/sites/{KNOWN_SITE}/recheck", json={"frequency_days": 30})
    assert r.status_code == 200
    body = r.json()
    assert_matches("site_summary.schema.json", body)
    assert body["recheck"]["frequency_days"] == 30


def test_set_recheck_unknown_site_404():
    r = client.put(f"{API}/sites/{UNKNOWN_SITE}/recheck", json={"frequency_days": 30})
    assert r.status_code == 404


def test_rerun_site():
    r = client.post(f"{API}/sites/{KNOWN_SITE}/rerun")
    assert r.status_code == 202
    assert_matches("job_accepted.schema.json", r.json())


# =============================================================================
# 9-10. flood query
# =============================================================================
VALID_FLOOD_QUERY = {
    "site_id": KNOWN_SITE,
    "model": "delft3d",
    "mode": "unknown_breach",
    "inputs": {"breach_width_m": {"type": "exact", "value": 72.0}, "failure_time_s": {"type": "slider", "position": 3}},
    "options": {"n_samples": 500, "seed": None},
}


def test_post_flood_query():
    r = client.post(f"{API}/flood/query", json=VALID_FLOOD_QUERY)
    assert r.status_code == 200
    body = r.json()
    assert_matches("flood_query_response.schema.json", body)
    assert body["site_id"] == KNOWN_SITE
    assert body["mode"] == "unknown_breach"


def test_post_flood_query_unknown_site_404():
    r = client.post(f"{API}/flood/query", json={**VALID_FLOOD_QUERY, "site_id": UNKNOWN_SITE})
    assert r.status_code == 404


def test_post_flood_query_bad_mode_422():
    r = client.post(f"{API}/flood/query", json={**VALID_FLOOD_QUERY, "mode": "not_a_mode"})
    assert r.status_code == 422
    assert_matches("error.schema.json", r.json()["detail"])


def test_get_flood_by_query_id():
    r = client.get(f"{API}/flood/{QUERY_ID}")
    assert r.status_code == 200
    body = r.json()
    assert_matches("flood_query_response.schema.json", body)
    assert body["query_id"] == QUERY_ID


# =============================================================================
# 11-13. layers, extent, timeline
# =============================================================================
def test_get_flood_layer_png():
    r = client.get(f"{API}/flood/{QUERY_ID}/layers/p_inundation.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content.startswith(b"\x89PNG")


def test_get_flood_layer_non_png_400():
    r = client.get(f"{API}/flood/{QUERY_ID}/layers/p_inundation.tif")
    assert r.status_code == 400


def test_get_flood_extent_geojson():
    r = client.get(f"{API}/flood/{QUERY_ID}/extent.geojson")
    assert r.status_code == 200
    body = r.json()
    assert_matches("geojson_feature_collection.schema.json", body)
    assert body["type"] == "FeatureCollection"


def test_get_flood_timeline():
    r = client.get(f"{API}/flood/{QUERY_ID}/timeline")
    assert r.status_code == 200
    body = r.json()
    assert_matches("timeline.schema.json", body)
    assert body["query_id"] == QUERY_ID


# =============================================================================
# 14. impact
# =============================================================================
def test_get_impact():
    r = client.get(f"{API}/impact/{QUERY_ID}")
    assert r.status_code == 200
    body = r.json()
    assert_matches("impact.schema.json", body)
    assert body["query_id"] == QUERY_ID


# =============================================================================
# 15. compare
# =============================================================================
def test_get_compare():
    r = client.get(f"{API}/compare/{KNOWN_SITE}")
    assert r.status_code == 200
    assert_matches("compare.schema.json", r.json())


def test_get_compare_with_scenario_id():
    r = client.get(f"{API}/compare/{KNOWN_SITE}", params={"scenario_id": "teesta__s009"})
    assert r.status_code == 200
    body = r.json()
    assert_matches("compare.schema.json", body)
    assert body["scenario_id"] == "teesta__s009"


# =============================================================================
# 16-17. validation
# =============================================================================
def test_get_validation():
    r = client.get(f"{API}/validation/{KNOWN_SITE}")
    assert r.status_code == 200
    body = r.json()
    assert_matches("validation.schema.json", body)
    assert body["site_id"] == KNOWN_SITE


def test_get_historical_validation():
    r = client.get(f"{API}/validation/{KNOWN_SITE}", params={"event": EVENT_ID})
    assert r.status_code == 200
    body = r.json()
    assert_matches("historical_validation.schema.json", body)
    assert body["event_id"] == EVENT_ID


# =============================================================================
# 18. export
# =============================================================================
@pytest.mark.parametrize(
    "fmt,content_type",
    [
        ("shp", "application/zip"),
        ("kml", "application/vnd.google-earth.kml+xml"),
        ("geojson", "application/geo+json"),
        ("pdf", "application/pdf"),
    ],
)
def test_export_formats(fmt, content_type):
    r = client.get(f"{API}/export/{QUERY_ID}", params={"format": fmt})
    assert r.status_code == 200
    assert r.headers["content-type"] == content_type
    assert "attachment" in r.headers["content-disposition"]
    assert len(r.content) > 0


def test_export_shp_is_a_real_zip():
    r = client.get(f"{API}/export/{QUERY_ID}", params={"format": "shp"})
    with zipfile.ZipFile(BytesIO(r.content)) as zf:
        assert zf.testzip() is None
        assert zf.namelist()


def test_export_geojson_matches_schema():
    r = client.get(f"{API}/export/{QUERY_ID}", params={"format": "geojson"})
    assert_matches("geojson_feature_collection.schema.json", json.loads(r.content))


def test_export_invalid_format_400():
    r = client.get(f"{API}/export/{QUERY_ID}", params={"format": "shx"})
    assert r.status_code == 400
    assert_matches("error.schema.json", r.json()["detail"])


# =============================================================================
# 19-20. gee
# =============================================================================
def test_get_gee():
    r = client.get(f"{API}/gee/{KNOWN_SITE}")
    assert r.status_code == 200
    body = r.json()
    assert_matches("gee_layers.schema.json", body)
    assert body["site_id"] == KNOWN_SITE


def test_refresh_gee():
    r = client.post(f"{API}/gee/{KNOWN_SITE}/refresh")
    assert r.status_code == 200
    assert_matches("gee_layers.schema.json", r.json())


def test_get_gee_unknown_site_404():
    r = client.get(f"{API}/gee/{UNKNOWN_SITE}")
    assert r.status_code == 404


# =============================================================================
# 21. scene3d
# =============================================================================
def test_get_scene3d():
    r = client.get(f"{API}/scene3d/{QUERY_ID}")
    assert r.status_code == 200
    body = r.json()
    assert_matches("scene3d.schema.json", body)
    assert body["query_id"] == QUERY_ID


# =============================================================================
# 22. files
# =============================================================================
def test_get_file_png():
    r = client.get(f"{API}/files/teesta/queries/{QUERY_ID}/layers/p_inundation.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"


def test_get_file_geojson():
    r = client.get(f"{API}/files/teesta/gee/observed/teesta_2023_observed.geojson")
    assert r.status_code == 200
    assert_matches("geojson_feature_collection.schema.json", r.json())


def test_get_file_bin():
    r = client.get(f"{API}/files/teesta/queries/{QUERY_ID}/scene3d/terrain.bin")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/octet-stream"


def test_get_file_unknown_extension_404():
    r = client.get(f"{API}/files/teesta/raw/readme.txt")
    assert r.status_code == 404
    assert_matches("error.schema.json", r.json()["detail"])
