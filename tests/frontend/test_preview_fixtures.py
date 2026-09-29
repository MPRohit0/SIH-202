"""Validates frontend/src/data/preview/*.json against contracts/schemas.

design/target-state-preview adds a VITE_DATA_MODE=preview data source for the
frontend that returns fixture JSON instead of live API responses (see
docs/progress.md and the branch's README section). Every fixture listed in
manifest.json must still be a real, schema-valid contract payload -- the
"target state" is illustrative numbers, not a relaxed contract. This test
reuses the same validator the backend uses on real responses
(backend/m0_api/schemas.validate) so the preview never drifts from the
contract that docs/handoff_contract.md defines.

This test does not touch backend/, contracts/, sites/ or docs/ -- it only
reads them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.m0_api.schemas import ContractViolation, validate

PREVIEW_DIR = Path(__file__).resolve().parents[2] / "frontend" / "src" / "data" / "preview"
MANIFEST_PATH = PREVIEW_DIR / "manifest.json"

# Schemas whose confidence-bearing Estimate fields live at these JSON Pointer-ish
# paths. Kept intentionally small and explicit -- new fixture kinds add a case
# here rather than a generic walk, so a missed spot fails loudly instead of
# silently passing.
PREVIEW_CAVEAT_ID = "preview_illustrative"
FROZEN_PILOT_BASIS_PREFIX = "frozen pilot"


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text())


def _load(fixture_name: str) -> dict:
    entry = _manifest()["fixtures"][fixture_name]
    return json.loads((PREVIEW_DIR / entry["file"]).read_text())


def _fixture_names() -> list[str]:
    return sorted(_manifest()["fixtures"].keys())


def test_manifest_exists():
    assert MANIFEST_PATH.is_file(), "frontend/src/data/preview/manifest.json is missing"


@pytest.mark.parametrize("fixture_name", _fixture_names())
def test_fixture_validates_against_its_schema(fixture_name):
    entry = _manifest()["fixtures"][fixture_name]
    payload = _load(fixture_name)
    try:
        validate(entry["schema"], payload)
    except ContractViolation as exc:
        pytest.fail(f"{fixture_name} ({entry['file']}) failed {entry['schema']}: {exc}")


def test_every_preview_json_file_is_in_the_manifest():
    manifest = _manifest()
    manifest_files = {entry["file"] for entry in manifest["fixtures"].values()}
    manifest_files |= {entry["file"] for entry in manifest.get("sidecars", {}).values() if isinstance(entry, dict)}
    on_disk = {p.name for p in PREVIEW_DIR.glob("*.json") if p.name != "manifest.json"}
    orphaned = on_disk - manifest_files
    assert not orphaned, f"Preview fixtures not listed in manifest.json: {sorted(orphaned)}"


def _iter_caveats(payload) -> list:
    """Caveats are normally {id, severity, text_key} objects, but run_meta and
    scenario_design use plain string arrays of caveat ids (contract §2.4)."""
    caveats = payload.get("caveats", [])
    ids = []
    for c in caveats:
        ids.append(c["id"] if isinstance(c, dict) else c)
    return ids


# site_list is a bare array of SiteSummary objects (contract §5.1); SiteSummary
# carries no provenance field, so the stamp lives only on each site_detail record.
FIXTURES_WITHOUT_OWN_PROVENANCE = {"site_list"}


def _stamp_payload(fixture_name: str) -> dict:
    """The payload to check for the honesty stamp: a fixture's own JSON, or --
    for a strict (additionalProperties:false) schema that cannot carry
    provenance/caveats itself, such as scene3d -- its manifest-registered
    sidecar file."""
    sidecar = _manifest().get("sidecars", {}).get(fixture_name)
    if sidecar:
        return json.loads((PREVIEW_DIR / sidecar["file"]).read_text())
    return _load(fixture_name)


@pytest.mark.parametrize(
    "fixture_name", [n for n in _fixture_names() if n not in FIXTURES_WITHOUT_OWN_PROVENANCE]
)
def test_fixture_is_stamped_as_preview(fixture_name):
    """Every fixture must be unambiguously marked as illustrative, not model
    output (CLAUDE.md rule 3; the branch's honesty requirements)."""
    payload = _stamp_payload(fixture_name)
    provenance = payload.get("provenance") or payload.get("x_preview_provenance")
    assert provenance is not None, (
        f"{fixture_name} has no provenance or x_preview_provenance object stamping it as preview data"
    )
    assert provenance.get("source") == "fixture:preview", (
        f"{fixture_name}.provenance.source must be 'fixture:preview', got {provenance.get('source')!r}"
    )
    assert PREVIEW_CAVEAT_ID in _iter_caveats(payload), (
        f"{fixture_name} is missing the '{PREVIEW_CAVEAT_ID}' caveat"
    )


def _iter_estimates(node, path=""):
    """Yield (path, estimate_dict) for every dict that looks like a contract
    Estimate (has the required Estimate keys)."""
    required = {"value", "low", "high", "unit", "interval", "kind"}
    if isinstance(node, dict):
        if required.issubset(node.keys()):
            yield path, node
        for key, value in node.items():
            yield from _iter_estimates(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from _iter_estimates(item, f"{path}[{i}]")


@pytest.mark.parametrize("fixture_name", _fixture_names())
def test_estimates_never_mix_observed_and_predicted_and_are_labelled(fixture_name):
    payload = _load(fixture_name)
    for path, estimate in _iter_estimates(payload):
        kind = estimate.get("kind")
        confidence = estimate.get("confidence")
        if kind == "observed":
            assert confidence is None, (
                f"{fixture_name}{path}: an observed Estimate must have confidence=null, got {confidence!r}"
            )
        basis = estimate.get("basis", "")
        is_frozen_pilot = basis.startswith(FROZEN_PILOT_BASIS_PREFIX)
        if kind == "predicted" and not is_frozen_pilot:
            assert basis == "illustrative", (
                f"{fixture_name}{path}: a non-frozen-pilot predicted Estimate must have "
                f"basis='illustrative' (or a 'frozen pilot...' basis), got {basis!r}"
            )


def test_site_list_covers_every_status():
    site_list = _load("site_list")
    statuses = {site["status"] for site in site_list}
    required = {"ready", "onboarding", "demo_mode", "outdated"}
    missing = required - statuses
    assert not missing, f"site_list.json is missing site status(es): {sorted(missing)}"
