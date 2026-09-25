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

import copy
import importlib
import json
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from backend.m0_api import mock_files, schemas
from backend.m0_api.main import app
from backend.m0_api.worker import Worker
from tests.m0_api.conftest import wait_until

SYNTH_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "shared" / "synth.yaml"


def valid_site_config(site_id: str = "kosi") -> dict:
    """A full, `site_config.schema.json`-valid config for POST /sites tests
    (the schema now `$ref`s the real `SiteConfig` model, contract §5.2)."""
    cfg = copy.deepcopy(yaml.safe_load(SYNTH_FIXTURE.read_text()))
    cfg["site"]["id"] = site_id
    return cfg

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
    assert body["contract_version"] == "0.2.0"


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
    r = client.post(f"{API}/sites", json={"site_config": valid_site_config(), "demo_mode": True})
    assert r.status_code == 202
    body = r.json()
    assert_matches("site_create_accepted.schema.json", body)
    assert body["site_id"] == "kosi"


def test_create_site_missing_config_is_422():
    r = client.post(f"{API}/sites", json={"demo_mode": True})
    assert r.status_code == 422
    assert_matches("error.schema.json", r.json()["detail"])


@pytest.mark.parametrize("site_config", [{}, {"site_id": "Bad-Id"}, {"site_id": 7}])
def test_create_site_bad_site_id_is_422(site_config):
    r = client.post(f"{API}/sites", json={"site_config": site_config})
    assert r.status_code == 422
    assert_matches("error.schema.json", r.json()["detail"])


def test_create_site_twice_while_active_is_409():
    first = client.post(f"{API}/sites", json={"site_config": valid_site_config()})
    r = client.post(f"{API}/sites", json={"site_config": valid_site_config()})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert_matches("error.schema.json", detail)
    assert detail["error"]["code"] == "site_onboarding_in_progress"
    assert detail["error"]["details"]["job_id"] == first.json()["job_id"]


# =============================================================================
# 6. GET /jobs/{job_id}
# =============================================================================
def test_get_job_created_by_post_sites():
    job_id = client.post(f"{API}/sites", json={"site_config": valid_site_config(), "demo_mode": True}).json()["job_id"]
    r = client.get(f"{API}/jobs/{job_id}")
    assert r.status_code == 200
    body = r.json()
    assert_matches("job_status.schema.json", body)
    assert body["job_id"] == job_id
    assert body["site_id"] == "kosi"
    assert body["kind"] == "onboarding"
    assert body["stage"] == "queued"
    assert body["demo_mode"] is True


def test_get_unknown_job_is_404():
    r = client.get(f"{API}/jobs/{JOB_ID}")
    assert r.status_code == 404
    assert_matches("error.schema.json", r.json()["detail"])
    assert r.json()["detail"]["error"]["code"] == "job_not_found"


def test_job_survives_api_restart():
    job_id = client.post(f"{API}/sites", json={"site_config": valid_site_config()}).json()["job_id"]
    import backend.m0_api.main as main_module

    restarted = importlib.reload(main_module)  # a fresh app: nothing carried over in memory
    r = TestClient(restarted.app).get(f"{API}/jobs/{job_id}")
    assert r.status_code == 200
    assert r.json()["stage"] == "queued"


def test_job_runs_to_ready_through_worker():
    job_id = client.post(f"{API}/sites", json={"site_config": valid_site_config()}).json()["job_id"]
    worker = Worker()
    worker.acquire_lock()
    worker.recover()
    try:
        wait_until(lambda: client.get(f"{API}/jobs/{job_id}").json()["stage"] == "ready", worker.tick)
    finally:
        worker.close()
    body = client.get(f"{API}/jobs/{job_id}").json()
    assert_matches("job_status.schema.json", body)
    assert body["started_at"] is not None


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


def test_get_flood_layer_renders_real_geotiff_when_present(data_dir):
    """A GeoTIFF at the contract §1.8 layers path is rendered for real
    (backend/m0_api/rendering.py), not served as the 1x1 mock PNG."""
    import numpy as np

    from backend.shared.grid import CanonicalGrid, write_grid_raster

    grid = CanonicalGrid(
        site_id=KNOWN_SITE, grid_id="farfield", crs_epsg=32645,
        origin_x=500_000.0, origin_y=3_100_000.0, cell_size_m=30.0, width=4, height=3,
    )
    layers_dir = data_dir / KNOWN_SITE / "queries" / QUERY_ID / "layers"
    layers_dir.mkdir(parents=True)
    write_grid_raster(layers_dir / "depth_p50.tif", np.full(grid.shape, 1.0, dtype=np.float32), grid)

    r = client.get(f"{API}/flood/{QUERY_ID}/layers/depth_p50.png")
    assert r.status_code == 200
    assert r.content.startswith(b"\x89PNG")
    assert r.content != mock_files.mock_png()
    assert (layers_dir / "depth_p50.png").is_file()  # cached alongside the source .tif


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


def _write_synthetic_timeline(data_dir, *, query_id=QUERY_ID, site_id=KNOWN_SITE, t_end_s=3600.0, width=6, height=3):
    """Writes real timeline/*.tif + timeline_data.json under `data_dir`, the
    way M5's `write_timeline_inputs` would after a real query -- the M0
    tests then only exercise the route, not the M5 arithmetic (covered in
    tests/m5_emulator/test_timeline.py)."""
    import dataclasses

    import numpy as np

    from backend.m2_breach.hydrograph import triangular
    from backend.m5_emulator import timeline as m5_timeline
    from backend.m5_emulator.query import FloodResult
    from backend.shared.grid import CanonicalGrid

    grid = CanonicalGrid(
        site_id=site_id, grid_id="farfield", crs_epsg=32645,
        origin_x=500_000.0, origin_y=3_100_000.0, cell_size_m=30.0, width=width, height=height,
    )
    col = np.tile(np.arange(width), (height, 1)).astype(np.float32)
    frac = col / (width - 1)  # 0 (upstream) -> 1 (downstream)
    p50 = frac * t_end_s * 0.6
    p10 = np.maximum(p50 - 300.0, 0.0)
    p90 = p50 + 300.0
    extent_class = np.where(frac < 0.7, np.uint8(2), np.uint8(1))

    result = FloodResult(
        site_id=site_id, model="synthetic", mode="scenario", resolved_inputs={},
        p_inundation=np.ones(grid.shape, dtype=np.float32), extent_class=extent_class,
        median={"arrival_time": p50}, p10={"arrival_time": p10}, p90={"arrival_time": p90},
        poi_depth={}, poi_velocity={}, poi_arrival={}, poi_p_inundation={},
        inundated_area_m2=(0.0, 0.0, 0.0), max_depth_site=(0.0, 0.0, 0.0), max_velocity_site=(0.0, 0.0, 0.0),
        outside_trained_range=False, confidence={"overall": {"level": "MODERATE"}}, n_samples=None,
    )
    chainage_m, cell_index = np.arange(width) * grid.cell_size_m, np.arange(width)
    hg = dataclasses.replace(triangular(Q_p=500.0, V=2_000_000.0, T_f=600.0), dam_id="synth_dam")

    query_dir = data_dir / site_id / "queries" / query_id
    m5_timeline.write_timeline_inputs(
        result, grid, query_dir, hydrographs=[hg], chainage_m=chainage_m, cell_index=cell_index,
        pois={}, t_end_s=t_end_s, contract_version="0.2.0", created_at="2026-09-24T10:15:00Z",
    )
    return query_dir


def test_get_flood_timeline_real_when_written(data_dir):
    _write_synthetic_timeline(data_dir)
    r = client.get(f"{API}/flood/{QUERY_ID}/timeline")
    assert r.status_code == 200
    body = r.json()
    assert_matches("timeline.schema.json", body)
    assert body["interval_s"] == 300
    assert body["t_end_s"] == 3600.0
    assert body["frames"]
    assert any(row["arrival_p50_s"] is not None for row in body["arrival_profile"])
    assert body["hydrographs"][0]["dam_id"] == "synth_dam"
    assert any(c["id"] == "arrival_depth_not_joint" for c in body["caveats"])


def test_get_flood_timeline_interval_s_changes_frame_count(data_dir):
    _write_synthetic_timeline(data_dir)
    coarse = client.get(f"{API}/flood/{QUERY_ID}/timeline", params={"interval_s": 1800}).json()
    fine = client.get(f"{API}/flood/{QUERY_ID}/timeline", params={"interval_s": 300}).json()
    assert len(fine["frames"]) > len(coarse["frames"])
    assert fine["frames"][-1]["t_s"] <= fine["t_end_s"]


def test_get_flood_timeline_too_many_frames_422(data_dir):
    _write_synthetic_timeline(data_dir, t_end_s=100_000.0)
    r = client.get(f"{API}/flood/{QUERY_ID}/timeline", params={"interval_s": 60})
    assert r.status_code == 422


def test_get_flood_timeline_interval_s_out_of_range_422():
    r = client.get(f"{API}/flood/{QUERY_ID}/timeline", params={"interval_s": 10})
    assert r.status_code == 422


def test_get_flood_timeline_frame_png_renders_and_caches(data_dir):
    query_dir = _write_synthetic_timeline(data_dir)
    r = client.get(f"{API}/files/{KNOWN_SITE}/queries/{QUERY_ID}/timeline/median_t300.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content.startswith(b"\x89PNG")
    assert r.content != mock_files.mock_png()
    assert (query_dir / "timeline" / "median_t300.png").is_file()


def test_get_flood_timeline_frame_png_high_and_possible_differ(data_dir):
    _write_synthetic_timeline(data_dir)
    high = client.get(f"{API}/files/{KNOWN_SITE}/queries/{QUERY_ID}/timeline/high_t3600.png")
    possible = client.get(f"{API}/files/{KNOWN_SITE}/queries/{QUERY_ID}/timeline/possible_t3600.png")
    assert high.status_code == possible.status_code == 200
    assert high.content != possible.content


def test_get_flood_timeline_frame_png_falls_back_to_mock_when_no_query():
    r = client.get(f"{API}/files/{KNOWN_SITE}/queries/{QUERY_ID}/timeline/median_t300.png")
    assert r.status_code == 200
    assert r.content == mock_files.mock_png()


def test_get_flood_timeline_frame_path_rejects_traversal(data_dir):
    _write_synthetic_timeline(data_dir)
    r = client.get(f"{API}/files/{KNOWN_SITE}/queries/../../../etc/timeline/median_t300.png")
    # doesn't match TIMELINE_FRAME_PATH_RE (query_id pattern fails) -> falls through to the generic mock/404 path
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        assert r.content == mock_files.mock_png()


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


def _write_synthetic_compare(data_dir, *, site_id=KNOWN_SITE, model="delft3d", scenario_id="teesta_s005"):
    """Writes a real compare sidecar + depth_diff.tif under `data_dir`, the
    way M5's `write_compare_inputs` would after a real LOOCV run -- a small
    (N=6, coarse-grid, n_restarts=1) synthetic library keeps the one real GP
    fit this triggers fast. The M0 tests then only exercise the route, not
    the M5 arithmetic (covered in tests/m5_emulator/test_compare.py)."""
    from backend.m5_emulator import compare as m5_compare
    from backend.m5_emulator import library as lib
    from backend.m5_emulator.emulator import EmulatorSettings
    from backend.m5_emulator.inputs import make_input_specs
    from backend.shared.grid import CanonicalGrid

    grid = CanonicalGrid(
        site_id=site_id, grid_id="farfield", crs_epsg=32645,
        origin_x=500_000.0, origin_y=3_100_000.0, cell_size_m=250.0, width=160, height=12,
    )
    library = lib.build_synthetic_library(grid, n=6, seed=5)
    ranges = {
        name: (float(library.X_raw[:, i].min()), float(library.X_raw[:, i].max()))
        for i, name in enumerate(lib.INPUT_ORDER)
    }
    specs = make_input_specs(ranges)
    settings = EmulatorSettings(seed=5, n_restarts=1)
    maps = {"max_depth": library.max_depth, "max_velocity": library.max_velocity, "arrival_time": library.arrival_time}

    held_out_run_id = f"{scenario_id}__{model}"
    report = {
        "per_run": [{
            "run_id": held_out_run_id, "iou": 0.42, "depth_rmse_wet_m": 0.11, "arrival_mae_s": 123.0,
        }],
        "summary": {"extent": {"iou_median": 0.42}, "arrival": {"mae_s_median": 123.0}},
        "baseline_linear": {"extent": {"iou_median": 0.20}, "arrival": {"mae_s_median": 400.0}},
    }

    out_dir = data_dir / site_id / "emulator" / model / "validation"
    compare_dir = m5_compare.write_compare_inputs(
        report, library.X_raw, maps, library.grid, specs, [held_out_run_id] + library.run_ids[1:], library.t_end_s,
        settings, held_out_run_id, out_dir, contract_version="0.2.0", created_at="2026-09-25T00:00:00Z",
    )
    return compare_dir


def test_get_compare_real_when_written(data_dir):
    _write_synthetic_compare(data_dir)
    r = client.get(f"{API}/compare/{KNOWN_SITE}", params={"scenario_id": "teesta_s005"})
    assert r.status_code == 200
    body = r.json()
    assert_matches("compare.schema.json", body)
    assert body["emulator_vs_physics"]["held_out_run_id"] == "teesta_s005__delft3d"
    assert body["emulator_vs_physics"]["metrics"]["iou"] == 0.42
    assert body["gp_vs_linear"]["iou_median_gp"] == 0.42
    assert body["gp_vs_linear"]["iou_median_linear"] == 0.20
    assert body["emulator_vs_physics"]["layers"][0]["style_id"] == "depth_diff"
    # sph_vs_delft3d / when_to_use_key are unaffected -- still the mock (out of scope)
    assert body["sph_vs_delft3d"] == schemas.load_example("compare.example.json")["sph_vs_delft3d"]
    assert any(c["id"] == "synthetic_world_not_real_physics" for c in body["caveats"])


def test_get_compare_falls_back_to_mock_without_scenario_id(data_dir):
    _write_synthetic_compare(data_dir)
    r = client.get(f"{API}/compare/{KNOWN_SITE}")
    assert r.status_code == 200
    body = r.json()
    assert body["emulator_vs_physics"]["held_out_run_id"] != "teesta_s005__delft3d"


def test_get_compare_falls_back_to_mock_when_no_sidecar_written():
    r = client.get(f"{API}/compare/{KNOWN_SITE}", params={"scenario_id": "teesta_s999"})
    assert r.status_code == 200
    body = r.json()
    assert_matches("compare.schema.json", body)


def test_get_compare_diff_png_renders_and_caches(data_dir):
    compare_dir = _write_synthetic_compare(data_dir)
    r = client.get(f"{API}/files/{KNOWN_SITE}/emulator/delft3d/validation/compare/teesta_s005__delft3d__depth_diff.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content.startswith(b"\x89PNG")
    assert r.content != mock_files.mock_png()
    assert (compare_dir / "teesta_s005__delft3d__depth_diff.png").is_file()


def test_get_compare_diff_png_falls_back_to_mock_when_no_sidecar():
    r = client.get(f"{API}/files/{KNOWN_SITE}/emulator/delft3d/validation/compare/nope__delft3d__depth_diff.png")
    assert r.status_code == 200
    assert r.content == mock_files.mock_png()


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
