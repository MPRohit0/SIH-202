import json
import zipfile
from io import BytesIO

from fastapi.testclient import TestClient

from backend.m0_api import registry
from backend.m0_api.main import app
from backend.m0_api.worker import Worker


def test_i1_demo_site_to_generated_artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("SIH26_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SIH26_FAKE_STAGE_S", "0")
    registry._initialised.clear()
    config = json.loads(open("tests/fixtures/i1/site_config.json").read())
    client = TestClient(app)

    accepted = client.post("/api/v1/sites", json={"site_config": config, "demo_mode": True})
    assert accepted.status_code == 202, accepted.text
    job_id = accepted.json()["job_id"]
    assert client.get(f"/api/v1/jobs/{job_id}").json()["stage"] == "queued"
    assert client.get("/api/v1/sites/demo_valley").json()["status"] == "onboarding"
    worker = Worker()
    stages = ["queued"]
    try:
        for _ in range(30):
            worker.tick()
            status = client.get(f"/api/v1/jobs/{job_id}").json()
            stages.append(status["stage"])
            if status["stage"] == "ready" or status["stage"] == "failed":
                break
        assert status["stage"] == "ready", status
        assert status["demo_mode"] is True
        assert {"queued","terrain","breach","design","simulating","training","validating","ready"}.issubset(stages)
        assert (tmp_path / "demo_valley/terrain/dem.tif").stat().st_size > 0
        from backend.m0_api import schemas
        schemas.validate("run_meta.schema.json", json.loads((tmp_path / "demo_valley/runs/demo_valley_demo_s001__synthetic/run_meta.json").read_text()))
    finally:
        worker.close()

    listed = client.get("/api/v1/sites").json()
    assert next(s for s in listed if s["site_id"] == "demo_valley")["status"] == "demo_mode"
    detail = client.get("/api/v1/sites/demo_valley")
    assert detail.status_code == 200 and detail.json()["domain"]["features"][0]["properties"]["synthetic"]
    request = {"site_id":"demo_valley","model":"delft3d","mode":"scenario","inputs":{}}
    result_response = client.post("/api/v1/flood/query", json=request)
    assert result_response.status_code == 200, result_response.text
    result = result_response.json()
    assert result["flags"]["demo_mode"] is True
    assert result["confidence"]["overall"]["level"] == "LOW"
    assert result["flags"]["has_placeholders"] is True
    query_id = result["query_id"]
    assert client.get(f"/api/v1/flood/{query_id}").json() == result

    png = client.get(f"/api/v1/flood/{query_id}/layers/depth_p50.png")
    assert png.status_code == 200 and png.headers["content-type"].startswith("image/png")
    assert len(png.content) > 100
    import rasterio
    with rasterio.open(tmp_path / "demo_valley/queries" / query_id / "layers/depth_p50.tif") as raster:
        assert float(raster.read(1).max()) == result["summary"]["max_depth_m"]["value"]
    impact = client.get(f"/api/v1/impact/{query_id}")
    assert impact.status_code == 200 and impact.json()["provenance"]["synthetic"]
    compare = client.get("/api/v1/compare/demo_valley")
    assert compare.status_code == 200 and compare.json()["scenario_id"] == "demo_valley_demo_s001"
    assert not compare.json()["sph_vs_delft3d"]["available"]
    timeline = client.get(f"/api/v1/flood/{query_id}/timeline?interval_s=600")
    assert timeline.status_code == 200 and len(timeline.json()["frames"]) == 4
    for item in timeline.json()["frames"]:
        for band in ("median_url", "high_url", "possible_url"):
            frame = client.get(item[band])
            assert frame.status_code == 200 and frame.headers["content-type"].startswith("image/png")
            assert len(frame.content) > 100
    exported = client.get(f"/api/v1/export/{query_id}?format=shp")
    assert exported.status_code == 200
    with zipfile.ZipFile(BytesIO(exported.content)) as archive:
        assert archive.testzip() is None
        assert {"extent.shp", "extent.shx", "extent.dbf", "extent.prj", "extent.cpg"}.issubset(archive.namelist())
        assert "README.txt" in archive.namelist()
    for fmt, content_type in (("geojson","application/geo+json"),("kml","application/vnd.google-earth.kml+xml"),("pdf","application/pdf")):
        response = client.get(f"/api/v1/export/{query_id}?format={fmt}")
        assert response.status_code == 200 and response.headers["content-type"].startswith(content_type)
        if fmt == "pdf":
            from pypdf import PdfReader
            text = PdfReader(BytesIO(response.content)).pages[0].extract_text()
            assert "maximum depth" in text.lower()
    vector = client.get(f"/api/v1/flood/{query_id}/extent.geojson")
    assert vector.status_code == 200 and vector.json()["features"]
    validation = client.get("/api/v1/validation/demo_valley")
    assert validation.status_code == 200 and validation.json()["n_runs"] == 0 and not validation.json()["validation_available"]
    assert client.get("/api/v1/sites/not_configured").status_code == 404
    assert client.get("/api/v1/flood/q_20260927T000000Z_000000").status_code == 404
    assert client.get("/api/v1/impact/q_20260927T000000Z_000000").status_code == 404
    assert client.get("/api/v1/export/q_20260927T000000Z_000000?format=geojson").status_code == 404
    (tmp_path / "demo_valley/queries" / query_id / "layers/depth_p50.tif").unlink()
    assert client.get(f"/api/v1/flood/{query_id}/layers/depth_p50.png").status_code == 404
