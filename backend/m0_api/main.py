"""M0 — FastAPI orchestrator (contract §5).

Most endpoints are still mocks. They serve the example JSON in
`contracts/examples/` (contract §8: "The frontend's mock mode serves the
example files from contracts/, so mocks can never drift from the contract").
Every response is validated against its `contracts/schemas/*.json` schema
before it is sent.

Real so far: the job system. `POST /sites` creates an onboarding job in
`data/registry.sqlite` and `GET /jobs/{job_id}` reads it back. The API holds
no job state of its own, so restarting it loses nothing. A separate process,
`python -m backend.m0_api.worker`, does the work: every stage is a fake task
for now (except a `recheck` job's `checking` stage, which is real -- see
`worker.py`), and solver runs are detached fake-solver processes.

Also real: `GET /sites`/`GET /sites/{id}` overlay `backend.m0_api.site_status`
(the worker's scheduled lake-area + library-age re-checks) onto the mocked
base response; `PUT /sites/{id}/recheck` persists the schedule for real.
`POST /sites/{id}/rerun` queues a genuine job, but an `onboarding`-kind one --
`jobs.STAGES` has no `rerun` entry yet (contract §5.3 lists no stages for it),
so this does not actually skip terrain the way "re-run" implies.

Still mocked: most endpoints. Scene3D builds real assets when a query's median depth and its
site terrain are present, otherwise it serves the contract example. `site_id` is checked only
against a short list of sites this server "knows about" (`mocks.KNOWN_SITE_IDS`).

Run: `uvicorn backend.m0_api.main:app --reload --port 8000`
"""

from __future__ import annotations

import logging
import re
from typing import Annotated, Any

from fastapi import Body, FastAPI, HTTPException, Path, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from backend.m0_api import jobs, mock_files, mocks, registry, rendering, schemas, site_status
from backend.m0_api import compare as api_compare
from backend.m0_api import scene3d as api_scene3d
from backend.m0_api import timeline as api_timeline
from backend.m7_gee import cache as gee_cache
from backend.m7_gee import fetch as gee_fetch
from backend.m7_gee import imagery as gee_imagery
from backend.shared.site_config import SiteConfigError, load_site_config

log = logging.getLogger("m0.main")

app = FastAPI(title="SIH26 GLOF/dam-break decision-support API", version="0.2.0")

# Contract §5: "CORS allows the Vite dev server (http://localhost:5173)."
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

API = "/api/v1"

# --- ID patterns (contract §1.7) --------------------------------------------
SITE_ID_PATTERN = r"^[a-z][a-z0-9_]{2,31}$"
SiteIdPath = Annotated[str, Path(pattern=SITE_ID_PATTERN)]
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
    sites = mocks.mock_response("site_list.example.json")
    sites = [site_status.overlay(s["site_id"], s) for s in sites]
    return _validated_json("site_list.schema.json", sites)


@app.get(f"{API}/sites/{{site_id}}")
def get_site(site_id: SiteIdPath) -> JSONResponse:
    _require_known_site(site_id)
    detail = mocks.mock_response("site_detail.example.json", site_id=site_id)
    detail = site_status.overlay(site_id, detail)
    return _validated_json("site_detail.schema.json", detail)


# =============================================================================
# 5. POST /sites (Add a Dam)
# =============================================================================
@app.post(f"{API}/sites", status_code=202)
def create_site(body: Annotated[dict, Body(...)]) -> JSONResponse:
    _validate_request_body("site_create_request.schema.json", body)
    site_config = body["site_config"]
    site_id = site_config.get("site", {}).get("id") if isinstance(site_config.get("site"), dict) else None
    if not isinstance(site_id, str) or not re.match(SITE_ID_PATTERN, site_id):
        raise HTTPException(
            status_code=422,
            detail=mocks.error("invalid_request", f"site_config.site.id must match {SITE_ID_PATTERN}.", {"field": "site_config.site.id"}),
        )
    conn = registry.connect()
    try:
        active = jobs.find_active_job(conn, site_id)
        if active is not None:
            raise HTTPException(
                status_code=409,
                detail=mocks.error("site_onboarding_in_progress", f"Site '{site_id}' already has an active job.", {"site_id": site_id, "job_id": active}),
            )
        job_id = jobs.create_job(conn, "onboarding", site_id, demo_mode=bool(body.get("demo_mode", False)), payload={"site_config": site_config})
    finally:
        conn.close()
    return _validated_json("site_create_accepted.schema.json", {"job_id": job_id, "site_id": site_id}, status_code=202)


# =============================================================================
# 6. GET /jobs/{job_id}
# =============================================================================
@app.get(f"{API}/jobs/{{job_id}}")
def get_job(job_id: JobIdPath) -> JSONResponse:
    conn = registry.connect()
    try:
        status = jobs.job_status(conn, job_id)
    finally:
        conn.close()
    if status is None:
        raise HTTPException(status_code=404, detail=mocks.error("job_not_found", f"No job '{job_id}'.", {"job_id": job_id}))
    return _validated_json("job_status.schema.json", status)


# =============================================================================
# 7. PUT /sites/{site_id}/recheck
# =============================================================================
@app.put(f"{API}/sites/{{site_id}}/recheck")
def set_recheck(site_id: SiteIdPath, body: Annotated[dict, Body(...)]) -> JSONResponse:
    _require_known_site(site_id)
    _validate_request_body("recheck_request.schema.json", body)
    site_status.set_frequency(
        site_id, body["frequency_days"], body.get("lake_area_change_threshold_pct")
    )
    summary = mocks.mock_response("site_summary.example.json", site_id=site_id)
    summary = site_status.overlay(site_id, summary)
    return _validated_json("site_summary.schema.json", summary)


# =============================================================================
# 8. POST /sites/{site_id}/rerun
# =============================================================================
@app.post(f"{API}/sites/{{site_id}}/rerun", status_code=202)
def rerun_site(site_id: SiteIdPath) -> JSONResponse:
    """Queues a real job -- but an `onboarding`-kind one (existing contract §5.3 stages), not a
    `rerun`-kind job: `jobs.STAGES` has no `rerun` entry yet (docs/progress.md, open gap), so this
    does NOT skip terrain the way "re-run reuses existing terrain" implies. That needs its own
    decision (rerun stage list + contract §5.3 change) before it can be done honestly."""
    _require_known_site(site_id)
    try:
        cfg = load_site_config(site_id)
    except SiteConfigError as e:
        raise HTTPException(
            status_code=404,
            detail=mocks.error("site_not_found", f"No site config for '{site_id}': {e}", {"site_id": site_id}),
        ) from e
    conn = registry.connect()
    try:
        active = jobs.find_active_job(conn, site_id)
        if active is not None:
            raise HTTPException(
                status_code=409,
                detail=mocks.error("site_onboarding_in_progress", f"Site '{site_id}' already has an active job.", {"site_id": site_id, "job_id": active}),
            )
        job_id = jobs.create_job(conn, "onboarding", site_id, payload={"site_config": cfg.model_dump(mode="json"), "rerun": True})
    finally:
        conn.close()
    return _validated_json("job_accepted.schema.json", {"job_id": job_id}, status_code=202)


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
    layer_id = layer_filename[: -len(".png")]
    # Contract §1.8: real GeoTIFFs land at data/<site_id>/queries/<query_id>/layers/.
    # M5 doesn't produce them yet, so this is a real render only when one has been
    # placed there by hand (e.g. a test); otherwise fall back to the mock PNG.
    for site_id in mocks.KNOWN_SITE_IDS:
        tif_path = registry.data_dir() / site_id / "queries" / query_id / "layers" / f"{layer_id}.tif"
        if tif_path.is_file():
            try:
                png_bytes = rendering.render_and_cache(tif_path, layer_id)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=mocks.error("invalid_layer", str(exc))) from exc
            return Response(content=png_bytes, media_type="image/png")
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
def get_flood_timeline(query_id: QueryIdPath, interval_s: int = Query(300, ge=60, le=86400)) -> JSONResponse:
    found = api_timeline.find_query_timeline_dir(query_id)
    if found is None:
        return _validated_json("timeline.schema.json", mocks.mock_response("timeline.example.json", query_id=query_id))
    site_id, timeline_dir = found
    response = api_timeline.build_response(site_id, timeline_dir, query_id, interval_s)
    if len(response["frames"]) > api_timeline.MAX_FRAMES:
        raise HTTPException(status_code=422, detail=mocks.error(
            "too_many_frames", f"{len(response['frames'])} frames exceeds the {api_timeline.MAX_FRAMES} limit; increase interval_s."))
    return _validated_json("timeline.schema.json", response)


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
    found = api_compare.find_compare_sidecar(site_id, scenario_id)
    if found is not None:
        model, held_out_run_id, sidecar_path = found
        response = api_compare.build_response(site_id, scenario_id, model, held_out_run_id, sidecar_path)
        return _validated_json("compare.schema.json", response)
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
def _gee_layers_or_mock(site_id: str) -> dict:
    """Real cache (`data/<site_id>/gee/`) once M7 has actually fetched something for this site
    (`gee_meta.json` exists, so `fetched_at` is set); otherwise the contract's mock, same as every
    other still-mocked endpoint (module docstring)."""
    layers = gee_cache.load_layers(site_id, data_dir=registry.data_dir())
    if layers.get("fetched_at") is None:
        return mocks.mock_response("gee_layers.example.json", site_id=site_id)
    return layers


@app.get(f"{API}/gee/{{site_id}}")
def get_gee(site_id: SiteIdPath) -> JSONResponse:
    _require_known_site(site_id)
    return _validated_json("gee_layers.schema.json", _gee_layers_or_mock(site_id))


@app.post(f"{API}/gee/{{site_id}}/refresh")
def refresh_gee(site_id: SiteIdPath) -> JSONResponse:
    """Tries a live Earth Engine fetch (lake area/rainfall via `gee_fetch.run`, event imagery via
    `gee_imagery.refresh`); either falls back to the existing cache on its own on any failure --
    missing/expired credentials, no network, no usable scene -- so this handler never 500s over a
    live-fetch problem, only over `site_id` not being configured at all."""
    _require_known_site(site_id)
    data_dir = registry.data_dir()
    live_ok = False
    try:
        cfg = load_site_config(site_id)
        provider = gee_fetch.best_effort_provider()
        lake_result = gee_fetch.run(site_id, provider=provider, data_dir=data_dir)
        img_result = gee_imagery.refresh(site_id, cfg=cfg, data_dir=data_dir)
        live_ok = not lake_result.errors and img_result.source == "live"
    except SiteConfigError as e:
        log.warning("refresh_gee: site config error for '%s', serving existing cache: %s", site_id, e)
    except Exception as e:  # never let a refresh attempt take the endpoint down
        log.warning("refresh_gee: unexpected error for '%s', serving existing cache: %s", site_id, e)

    payload = _gee_layers_or_mock(site_id)
    if live_ok:
        payload["source"] = "live"
    return _validated_json("gee_layers.schema.json", payload)


# =============================================================================
# 21. GET /scene3d/{query_id}
# =============================================================================
@app.get(f"{API}/scene3d/{{query_id}}")
def get_scene3d(
    query_id: QueryIdPath,
    vertical_exaggeration: float = Query(api_scene3d.DEFAULT_VERTICAL_EXAGGERATION, ge=0.1, le=10.0),
) -> JSONResponse:
    try:
        payload = api_scene3d.build_scene(query_id, vertical_exaggeration)
    except ValueError as exc:
        raise HTTPException(status_code=413, detail=mocks.error("scene_too_large", str(exc))) from exc
    if payload is None:
        payload = mocks.mock_response("scene3d.example.json", query_id=query_id)
        payload["frame"]["vertical_exaggeration"] = vertical_exaggeration
    return _validated_json("scene3d.schema.json", payload)


#: A timeline frame PNG's path, anchored end to end so no other shape of
#: `path` (in particular nothing with `..` or extra segments) can match.
TIMELINE_FRAME_PATH_RE = re.compile(
    rf"^(?P<site_id>{SITE_ID_PATTERN[1:-1]})/queries/(?P<query_id>q_\d{{8}}T\d{{6}}Z_[0-9a-f]{{6}})"
    r"/timeline/(?P<band>median|high|possible)_t(?P<t_s>\d+)\.png$"
)

#: A Compare depth-difference PNG's path, anchored the same way (run_id
#: restricted to id-safe characters -- no `/` or `.` -- so nothing can
#: escape `validation/compare/`).
COMPARE_DIFF_PATH_RE = re.compile(
    rf"^(?P<site_id>{SITE_ID_PATTERN[1:-1]})/emulator/(?P<model>delft3d|sph)/validation/compare/"
    r"(?P<run_id>[A-Za-z0-9_]+)__depth_diff\.png$"
)

#: An M7 event-imagery PNG under `data/<site_id>/gee/imagery/` (`gee_imagery.convert`), anchored
#: the same way so nothing can escape that directory.
GEE_IMAGERY_PATH_RE = re.compile(
    rf"^(?P<site_id>{SITE_ID_PATTERN[1:-1]})/gee/imagery/(?P<filename>[A-Za-z0-9_]+\.png)$"
)

#: An M7 observed-extent GeoJSON under `data/<site_id>/gee/observed/` (`gee_observed.convert`),
#: anchored the same way so nothing can escape that directory.
GEE_OBSERVED_PATH_RE = re.compile(
    rf"^(?P<site_id>{SITE_ID_PATTERN[1:-1]})/gee/observed/(?P<filename>[A-Za-z0-9_]+_observed\.geojson)$"
)

SCENE_ASSET_PATH_RE = re.compile(
    rf"^(?P<site_id>{SITE_ID_PATTERN[1:-1]})/queries/(?P<query_id>q_\d{{8}}T\d{{6}}Z_[0-9a-f]{{6}})"
    r"/scene3d/(?P<filename>terrain\.bin|flood_surface\.bin|delft3d_surface\.glb)$"
)
SPH_SURFACE_PATH_RE = re.compile(
    rf"^(?P<site_id>{SITE_ID_PATTERN[1:-1]})/runs/(?P<run_id>[A-Za-z0-9_]+__sph)/surfaces/(?P<filename>t\d+\.glb)$"
)


# =============================================================================
# 22. GET /files/{path}
# =============================================================================
@app.get(f"{API}/files/{{path:path}}")
def get_file(path: str) -> Response:
    m = SCENE_ASSET_PATH_RE.match(path)
    if m is not None:
        asset_path = registry.data_dir() / m["site_id"] / "queries" / m["query_id"] / "scene3d" / m["filename"]
        if asset_path.is_file():
            media_type = "model/gltf-binary" if asset_path.suffix == ".glb" else "application/octet-stream"
            return Response(content=asset_path.read_bytes(), media_type=media_type)
        if m["filename"] in {"terrain.bin", "flood_surface.bin"}:
            # Contract example grid is 500 x 375 float32 samples (750,000 bytes).
            return Response(content=b"\x00" * 750_000, media_type="application/octet-stream")
        raise HTTPException(status_code=404, detail=mocks.error("file_not_found", f"No scene asset at '{path}'.", {"path": path}))

    m = SPH_SURFACE_PATH_RE.match(path)
    if m is not None:
        asset_path = registry.data_dir() / m["site_id"] / "runs" / m["run_id"] / "surfaces" / m["filename"]
        if asset_path.is_file():
            return Response(content=asset_path.read_bytes(), media_type="model/gltf-binary")
        raise HTTPException(status_code=404, detail=mocks.error("file_not_found", f"No SPH surface at '{path}'.", {"path": path}))

    m = TIMELINE_FRAME_PATH_RE.match(path)
    if m is not None:
        timeline_dir = registry.data_dir() / m["site_id"] / "queries" / m["query_id"] / "timeline"
        if (timeline_dir / "timeline_data.json").is_file():
            png_bytes = api_timeline.render_frame(timeline_dir, m["band"], int(m["t_s"]))
            return Response(content=png_bytes, media_type="image/png")

    m = COMPARE_DIFF_PATH_RE.match(path)
    if m is not None:
        sidecar_path = (
            registry.data_dir() / m["site_id"] / "emulator" / m["model"] / "validation" / "compare" / f"{m['run_id']}.json"
        )
        if sidecar_path.is_file():
            png_bytes = api_compare.render_diff_layer(sidecar_path, m["run_id"])
            return Response(content=png_bytes, media_type="image/png")

    m = GEE_IMAGERY_PATH_RE.match(path)
    if m is not None:
        png_path = registry.data_dir() / m["site_id"] / "gee" / "imagery" / m["filename"]
        if png_path.is_file():
            return Response(content=png_path.read_bytes(), media_type="image/png")
        raise HTTPException(
            status_code=404,
            detail=mocks.error("file_not_found", f"No GEE imagery file at '{png_path}'.", {"path": path}),
        )

    m = GEE_OBSERVED_PATH_RE.match(path)
    if m is not None:
        geojson_path = registry.data_dir() / m["site_id"] / "gee" / "observed" / m["filename"]
        if geojson_path.is_file():
            return Response(content=geojson_path.read_bytes(), media_type="application/geo+json")
        raise HTTPException(
            status_code=404,
            detail=mocks.error("file_not_found", f"No observed-extent file at '{geojson_path}'.", {"path": path}),
        )
    if path.endswith(".png"):
        return Response(content=mock_files.mock_png(), media_type="image/png")
    if path.endswith(".geojson"):
        import json

        return Response(content=json.dumps(mocks.mock_response("geojson_feature_collection.example.json")).encode(), media_type="application/geo+json")
    if path.endswith(".bin"):
        # Mock float32 payload for Scene3D terrain/flood_surface binaries (contract §5.9).
        return Response(content=b"\x00\x00\x00\x00" * 16, media_type="application/octet-stream")
    raise HTTPException(status_code=404, detail=mocks.error("file_not_found", f"No mock file for '{path}'."))
