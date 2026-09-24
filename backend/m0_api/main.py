"""M0 — FastAPI orchestrator (contract §5), mock mode.

Serves every endpoint in `docs/handoff_contract.md` §5 from the example JSON
in `contracts/examples/` (contract §8: "The frontend's mock mode serves the
example files from contracts/, so mocks can never drift from the contract").
Every response is validated against its `contracts/schemas/*.json` schema
before being sent.

What this is NOT yet: there is no job queue, no `data/registry.sqlite`, and
no real M1-M7 output behind any of this. Every well-formed ID returns the
same mock payload; only `site_id` is checked against a short list of sites
this mock server "knows about" (`mocks.KNOWN_SITE_IDS`), so 404 handling has
at least one real code path to test. Wiring this to real modules is the next
session's work, not this one's.

Run: `uvicorn backend.m0_api.main:app --reload --port 8000`
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Body, FastAPI, HTTPException, Path, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from backend.m0_api import mock_files, mocks, schemas

app = FastAPI(title="SIH26 GLOF/dam-break decision-support API", version="0.1.0")

# Contract §5: "CORS allows the Vite dev server (http://localhost:5173)."
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

API = "/api/v1"

# --- ID patterns (contract §1.7) --------------------------------------------
SiteIdPath = Annotated[str, Path(pattern=r"^[a-z][a-z0-9_]{2,31}$")]
QueryIdPath = Annotated[str, Path(pattern=r"^q_\d{8}T\d{6}Z_[0-9a-f]{6}$")]
JobIdPath = Annotated[str, Path(pattern=r"^job_\d{8}T\d{6}Z_[0-9a-f]{6}$")]


# --- helpers -----------------------------------------------------------------
def _validated_json(schema_name: str, payload: Any, status_code: int = 200) -> JSONResponse:
    """Validate `payload` against `schema_name`, or fail loudly: a payload
    this server itself builds should always match its own contract."""
    try:
        schemas.validate(schema_name, payload)
    except schemas.ContractViolation as exc:
        raise HTTPException(
            status_code=500,
            detail=mocks.error("contract_violation", f"Server built a response that violates its own contract: {exc}"),
        ) from exc
    return JSONResponse(content=payload, status_code=status_code)


def _require_known_site(site_id: str) -> None:
    if site_id not in mocks.KNOWN_SITE_IDS:
        raise HTTPException(
            status_code=404,
            detail=mocks.error("site_not_found", f"No site '{site_id}' is configured.", {"site_id": site_id}),
        )


def _validate_request_body(schema_name: str, body: Any) -> None:
    try:
        schemas.validate(schema_name, body)
    except schemas.ContractViolation as exc:
        raise HTTPException(status_code=422, detail=mocks.error("invalid_request", str(exc))) from exc


# =============================================================================
# 1. GET /health
# =============================================================================
@app.get(f"{API}/health")
def get_health() -> JSONResponse:
    return _validated_json("health.schema.json", mocks.mock_response("health.example.json"))


# =============================================================================
# 2. GET /styles
# =============================================================================
@app.get(f"{API}/styles")
def get_styles() -> JSONResponse:
    import json

    styles = json.loads((schemas.CONTRACTS_DIR / "styles.json").read_text())
    return _validated_json("styles.schema.json", styles)


# =============================================================================
# 3-4. GET /sites, GET /sites/{site_id}
# =============================================================================
@app.get(f"{API}/sites")
def list_sites() -> JSONResponse:
    return _validated_json("site_list.schema.json", mocks.mock_response("site_list.example.json"))


@app.get(f"{API}/sites/{{site_id}}")
def get_site(site_id: SiteIdPath) -> JSONResponse:
    _require_known_site(site_id)
    return _validated_json("site_detail.schema.json", mocks.mock_response("site_detail.example.json", site_id=site_id))


# =============================================================================
# 5. POST /sites (Add a Dam)
# =============================================================================
@app.post(f"{API}/sites", status_code=202)
def create_site(body: Annotated[dict, Body(...)]) -> JSONResponse:
    _validate_request_body("site_create_request.schema.json", body)
    site_config = body.get("site_config", {})
    new_site_id = site_config.get("site_id") or "new_site"
    payload = mocks.mock_response("site_create_accepted.example.json", site_id=new_site_id)
    return _validated_json("site_create_accepted.schema.json", payload, status_code=202)


# =============================================================================
# 6. GET /jobs/{job_id}
# =============================================================================
@app.get(f"{API}/jobs/{{job_id}}")
def get_job(job_id: JobIdPath) -> JSONResponse:
    return _validated_json("job_status.schema.json", mocks.mock_response("job_status.example.json", job_id=job_id))


# =============================================================================
# 7. PUT /sites/{site_id}/recheck
# =============================================================================
@app.put(f"{API}/sites/{{site_id}}/recheck")
def set_recheck(site_id: SiteIdPath, body: Annotated[dict, Body(...)]) -> JSONResponse:
    _require_known_site(site_id)
    _validate_request_body("recheck_request.schema.json", body)
    summary = mocks.mock_response("site_summary.example.json", site_id=site_id)
    summary["recheck"]["frequency_days"] = body["frequency_days"]
    return _validated_json("site_summary.schema.json", summary)


# =============================================================================
# 8. POST /sites/{site_id}/rerun
# =============================================================================
@app.post(f"{API}/sites/{{site_id}}/rerun", status_code=202)
def rerun_site(site_id: SiteIdPath) -> JSONResponse:
    _require_known_site(site_id)
    return _validated_json("job_accepted.schema.json", mocks.mock_response("job_accepted.example.json"), status_code=202)


# =============================================================================
# 9-10. POST /flood/query, GET /flood/{query_id}
# =============================================================================
@app.post(f"{API}/flood/query")
def query_flood(body: Annotated[dict, Body(...)]) -> JSONResponse:
    _validate_request_body("flood_query_request.schema.json", body)
    _require_known_site(body["site_id"])
    payload = mocks.mock_response("flood_query_response.example.json", site_id=body["site_id"])
    payload["mode"] = body["mode"]
    return _validated_json("flood_query_response.schema.json", payload)


@app.get(f"{API}/flood/{{query_id}}")
def get_flood(query_id: QueryIdPath) -> JSONResponse:
    payload = mocks.mock_response("flood_query_response.example.json", query_id=query_id)
    return _validated_json("flood_query_response.schema.json", payload)


# =============================================================================
# 11. GET /flood/{query_id}/layers/{layer_id}.png
# =============================================================================
@app.get(f"{API}/flood/{{query_id}}/layers/{{layer_filename}}")
def get_flood_layer(query_id: QueryIdPath, layer_filename: str) -> Response:
    if not layer_filename.endswith(".png"):
        raise HTTPException(status_code=400, detail=mocks.error("invalid_layer", f"'{layer_filename}' is not a .png layer request."))
    return Response(content=mock_files.mock_png(), media_type="image/png")


# =============================================================================
# 12. GET /flood/{query_id}/extent.geojson
# =============================================================================
@app.get(f"{API}/flood/{{query_id}}/extent.geojson")
def get_flood_extent(query_id: QueryIdPath) -> JSONResponse:
    return _validated_json("geojson_feature_collection.schema.json", mocks.mock_response("extent_geojson.example.json"))


# =============================================================================
# 13. GET /flood/{query_id}/timeline
# =============================================================================
@app.get(f"{API}/flood/{{query_id}}/timeline")
def get_flood_timeline(query_id: QueryIdPath) -> JSONResponse:
    return _validated_json("timeline.schema.json", mocks.mock_response("timeline.example.json", query_id=query_id))


# =============================================================================
# 14. GET /impact/{query_id}
# =============================================================================
@app.get(f"{API}/impact/{{query_id}}")
def get_impact(query_id: QueryIdPath) -> JSONResponse:
    return _validated_json("impact.schema.json", mocks.mock_response("impact.example.json", query_id=query_id))


# =============================================================================
# 15. GET /compare/{site_id}?scenario_id=
# =============================================================================
@app.get(f"{API}/compare/{{site_id}}")
def get_compare(site_id: SiteIdPath, scenario_id: str | None = Query(default=None)) -> JSONResponse:
    _require_known_site(site_id)
    ids = {"site_id": site_id}
    if scenario_id:
        ids["scenario_id"] = scenario_id
    return _validated_json("compare.schema.json", mocks.mock_response("compare.example.json", **ids))


# =============================================================================
# 16-17. GET /validation/{site_id}[?event=]
# =============================================================================
@app.get(f"{API}/validation/{{site_id}}")
def get_validation(site_id: SiteIdPath, event: str | None = Query(default=None)) -> JSONResponse:
    _require_known_site(site_id)
    if event:
        payload = mocks.mock_response("historical_validation.example.json", site_id=site_id, event_id=event)
        return _validated_json("historical_validation.schema.json", payload)
    payload = mocks.mock_response("validation.example.json", site_id=site_id)
    return _validated_json("validation.schema.json", payload)


# =============================================================================
# 18. GET /export/{query_id}?format=shp|kml|geojson|pdf
# =============================================================================
_EXPORT_MEDIA_TYPES = {
    "shp": "application/zip",
    "kml": "application/vnd.google-earth.kml+xml",
    "geojson": "application/geo+json",
    "pdf": "application/pdf",
}


@app.get(f"{API}/export/{{query_id}}")
def export_query(query_id: QueryIdPath, format: str = Query(...)) -> Response:  # noqa: A002 - contract's param name
    if format not in _EXPORT_MEDIA_TYPES:
        raise HTTPException(
            status_code=400,
            detail=mocks.error("invalid_format", f"format must be one of {sorted(_EXPORT_MEDIA_TYPES)}, got '{format}'."),
        )
    site_id = "teesta"  # mock-only: no registry to look the query's site up in yet
    if format == "shp":
        content, filename = mock_files.mock_shapefile_zip(site_id, query_id), f"{site_id}_{query_id}_extent.zip"
    elif format == "kml":
        content, filename = mock_files.mock_kml(site_id, query_id), f"{site_id}_{query_id}_extent.kml"
    elif format == "geojson":
        import json

        content = json.dumps(mocks.mock_response("extent_geojson.example.json")).encode()
        filename = f"{site_id}_{query_id}_extent.geojson"
    else:
        content, filename = mock_files.mock_pdf(f"{site_id} {query_id}"), f"{site_id}_{query_id}_report.pdf"
    return Response(
        content=content,
        media_type=_EXPORT_MEDIA_TYPES[format],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# =============================================================================
# 19-20. GET /gee/{site_id}, POST /gee/{site_id}/refresh
# =============================================================================
@app.get(f"{API}/gee/{{site_id}}")
def get_gee(site_id: SiteIdPath) -> JSONResponse:
    _require_known_site(site_id)
    return _validated_json("gee_layers.schema.json", mocks.mock_response("gee_layers.example.json", site_id=site_id))


@app.post(f"{API}/gee/{{site_id}}/refresh")
def refresh_gee(site_id: SiteIdPath) -> JSONResponse:
    _require_known_site(site_id)
    return _validated_json("gee_layers.schema.json", mocks.mock_response("gee_layers.example.json", site_id=site_id))


# =============================================================================
# 21. GET /scene3d/{query_id}
# =============================================================================
@app.get(f"{API}/scene3d/{{query_id}}")
def get_scene3d(query_id: QueryIdPath) -> JSONResponse:
    return _validated_json("scene3d.schema.json", mocks.mock_response("scene3d.example.json", query_id=query_id))


# =============================================================================
# 22. GET /files/{path}
# =============================================================================
@app.get(f"{API}/files/{{path:path}}")
def get_file(path: str) -> Response:
    if path.endswith(".png"):
        return Response(content=mock_files.mock_png(), media_type="image/png")
    if path.endswith(".geojson"):
        import json

        return Response(content=json.dumps(mocks.mock_response("geojson_feature_collection.example.json")).encode(), media_type="application/geo+json")
    if path.endswith(".bin"):
        # Mock float32 payload for Scene3D terrain/flood_surface binaries (contract §5.9).
        return Response(content=b"\x00\x00\x00\x00" * 16, media_type="application/octet-stream")
    raise HTTPException(status_code=404, detail=mocks.error("file_not_found", f"No mock file for '{path}'."))
