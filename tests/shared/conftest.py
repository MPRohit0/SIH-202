"""Fixtures for backend/shared tests: the synthetic site and helpers to mutate it."""

import copy
import warnings
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "shared"
SYNTH_PATH = FIXTURE_DIR / "synth.yaml"
SITES_DIR = REPO_ROOT / "sites"

SYNTH_PLACEHOLDERS = [
    "domains.near_field.inflow.location",
    "dams[0].breach_inputs.water_volume_above_invert",
    "points_of_interest[1].location",
    "events[0].imagery_post_event",
]


@pytest.fixture
def synth_path() -> Path:
    return SYNTH_PATH


@pytest.fixture
def synth_raw() -> dict:
    """A fresh, mutable copy of the synthetic site config as a plain dict."""
    with open(SYNTH_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture
def write_site(tmp_path):
    """Write a (mutated) config dict to tmp_path/<stem>.yaml and return the path."""

    def _write(data: dict, stem: str | None = None) -> Path:
        stem = stem or data["site"]["id"]
        path = tmp_path / f"{stem}.yaml"
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=False)
        return path

    return _write


def fully_sourced(data: dict) -> dict:
    """Return a copy of the synthetic config with every placeholder turned into a sourced value."""
    data = copy.deepcopy(data)
    fills = {
        ("domains", "near_field", "inflow", "location"): [88.485, 27.499],
        ("dams", 0, "breach_inputs", "water_volume_above_invert"): 1_000_000,
        ("points_of_interest", 1, "location"): [88.52, 27.47],
        ("events", 0, "imagery_post_event"): "2020-01-05",
    }
    for path, value in fills.items():
        node = data
        for key in path:
            node = node[key]
        node.update(value=value, status="sourced", source="Synthetic test fixture - not real data")
    return data


@pytest.fixture
def synth_config():
    """The synthetic site loaded and validated (placeholder warning suppressed)."""
    from backend.shared.site_config import load_site_config

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return load_site_config(SYNTH_PATH)
