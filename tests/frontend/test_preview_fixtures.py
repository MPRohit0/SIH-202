"""Validates the demo engine's output shape against contracts/schemas
(design/target-state-preview).

The preview data layer used to be static, hand-authored fixture JSON, each
checked for contract shape AND for an "illustrative, not model output" honesty
stamp. It is now a live client-side demo engine
(frontend/src/data/preview/engine/) that computes every number from the
current user input -- there is no static fixture left to check basis wording
or provenance stamps on. What this test still checks is the one thing that
matters for a live engine: its output stays contract-valid.

frontend/scripts/dump_preview_fixtures.mjs compiles the engine with the
already-installed `typescript` package and calls its defaultSnapshot(site_id)
for each site, writing frontend/src/data/preview/generated/*.json. This test
validates those snapshots against contracts/schemas/*.schema.json with the
same validator the backend uses on real responses
(backend/m0_api/schemas.validate) -- re-run the dump script and commit the
refreshed generated/*.json after changing anything under engine/.

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


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text())


def _load(fixture_name: str):
    entry = _manifest()["fixtures"][fixture_name]
    payload = json.loads((PREVIEW_DIR / entry["file"]).read_text())
    if "key" in entry:
        payload = payload[entry["key"]]
    return payload


def _fixture_names() -> list[str]:
    return sorted(_manifest()["fixtures"].keys())


def test_manifest_exists():
    assert MANIFEST_PATH.is_file(), "frontend/src/data/preview/manifest.json is missing"


def test_generated_snapshots_exist():
    for site_id in ["teesta", "rishi_ganga"]:
        path = PREVIEW_DIR / "generated" / f"{site_id}.default_snapshot.json"
        assert path.is_file(), (
            f"{path} is missing -- run `node frontend/scripts/dump_preview_fixtures.mjs` "
            "and commit its output"
        )


@pytest.mark.parametrize("fixture_name", _fixture_names())
def test_fixture_validates_against_its_schema(fixture_name):
    entry = _manifest()["fixtures"][fixture_name]
    payload = _load(fixture_name)
    try:
        validate(entry["schema"], payload)
    except ContractViolation as exc:
        pytest.fail(f"{fixture_name} ({entry['file']}) failed {entry['schema']}: {exc}")


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
def test_estimates_have_valid_ordering(fixture_name):
    """low <= high whenever both are numbers, and an observed Estimate (none
    in this engine yet, but kept as a guard) always has confidence=null --
    the two structural rules that still make sense once "illustrative" values
    are simply invented rather than sourced."""
    payload = _load(fixture_name)
    for path, estimate in _iter_estimates(payload):
        low, high = estimate.get("low"), estimate.get("high")
        if isinstance(low, (int, float)) and isinstance(high, (int, float)):
            assert low <= high + 1e-6, f"{fixture_name}{path}: low ({low}) > high ({high})"
        if estimate.get("kind") == "observed":
            assert estimate.get("confidence") is None, (
                f"{fixture_name}{path}: an observed Estimate must have confidence=null"
            )
