"""M0's half of Compare's "emulator vs physics" / "GP vs linear" sections
(`docs/handoff_contract.md` §5.6, route #15): reads what
`backend.m5_emulator.compare.write_compare_inputs` wrote under
`data/<site_id>/emulator/<model>/validation/compare/`, merges it into the
mock `compare.example.json` shape (`sph_vs_delft3d`/`when_to_use_key` stay
mocked -- no real SPH/Delft3D run data exists yet, out of scope here), and
renders/caches the depth-difference PNG with M0-5 (`rendering.py`).
"""

from __future__ import annotations

import json
from pathlib import Path

from backend.m0_api import mocks, registry, rendering

#: contract §1.7 model enum -- tried in order when resolving a scenario_id
#: to a held-out run_id, since the request only names the scenario.
MODELS = ("delft3d", "sph")

DIFF_LAYER_ID = "depth_diff"


def find_compare_sidecar(site_id: str, scenario_id: str | None) -> tuple[str, str, Path] | None:
    """`(model, held_out_run_id, sidecar_path)` for the first model that has
    one written, or `None` (falls back to the mock -- including when no
    `scenario_id` was given, since a run_id can't be resolved without one)."""
    if not scenario_id:
        return None
    for model in MODELS:
        held_out_run_id = f"{scenario_id}__{model}"
        sidecar_path = registry.data_dir() / site_id / "emulator" / model / "validation" / "compare" / f"{held_out_run_id}.json"
        if sidecar_path.is_file():
            return model, held_out_run_id, sidecar_path
    return None


def build_response(site_id: str, scenario_id: str, model: str, held_out_run_id: str, sidecar_path: Path) -> dict:
    """The full `Compare` dict, `emulator_vs_physics`/`gp_vs_linear` real,
    everything else from the mock example."""
    sidecar = json.loads(sidecar_path.read_text())
    response = mocks.mock_response("compare.example.json", site_id=site_id, scenario_id=scenario_id)

    diff_url = f"/api/v1/files/{site_id}/emulator/{model}/validation/compare/{held_out_run_id}__depth_diff.png"
    response["emulator_vs_physics"] = {
        "available": True, "held_out_run_id": held_out_run_id, "metrics": sidecar["metrics"],
        "layers": [{
            "layer_id": DIFF_LAYER_ID, "type": "raster_png", "url": diff_url,
            "bounds_latlng": sidecar["bounds_latlng"], "style_id": "depth_diff", "unit": "m", "available": True,
        }],
    }
    response["gp_vs_linear"] = sidecar["gp_vs_linear"]
    response["caveats"] = [*response["caveats"], *sidecar["caveats"]]
    return response


def render_diff_layer(sidecar_path: Path, held_out_run_id: str) -> bytes:
    """The one `depth_diff` PNG a compare sidecar has, cached beside its
    source `.tif` (same one-render-per-artifact rule as `rendering.render_and_cache`)."""
    tif_path = sidecar_path.parent / f"{held_out_run_id}__depth_diff.tif"
    return rendering.render_and_cache(tif_path, DIFF_LAYER_ID)
