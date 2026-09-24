"""Fixtures for backend/m2_breach tests. Reuses tests/fixtures/shared/synth.yaml
(one moraine/HD dam, one placeholder breach input) rather than duplicating it."""

from __future__ import annotations

import copy
import warnings
from pathlib import Path

import pytest

from backend.shared.site_config import SiteConfig, load_site_config
from tests.shared.conftest import SYNTH_PATH, fully_sourced


CASCADE_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "m2_breach"
SYNTH_CASCADE_PATH = CASCADE_FIXTURE_DIR / "synth_cascade.yaml"


@pytest.fixture
def synth_raw() -> dict:
    import yaml
    with open(SYNTH_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture
def synth_cascade_raw() -> dict:
    import yaml
    with open(SYNTH_CASCADE_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture
def synth_cascade_config(synth_cascade_raw) -> SiteConfig:
    return SiteConfig.model_validate(synth_cascade_raw)


@pytest.fixture
def synth_config_with_placeholder(synth_raw) -> SiteConfig:
    """The fixture as shipped: one placeholder (water_volume_above_invert)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return SiteConfig.model_validate(synth_raw)


@pytest.fixture
def synth_config_sourced(synth_raw) -> SiteConfig:
    """Every placeholder filled in — fully computable."""
    return SiteConfig.model_validate(fully_sourced(synth_raw))


def _dam(raw: dict, index: int = 0) -> dict:
    return raw["dams"][index]


def _source(value, unit: str = "-", source: str = "Synthetic test fixture - not real data") -> dict:
    return {"value": value, "unit": unit, "source": source, "status": "sourced"}


def _placeholder(unit: str) -> dict:
    return {"value": None, "unit": unit, "source": "Placeholder: synthetic test value", "status": "placeholder"}


# Synthetic hydrograph config blocks (backend/m2_breach/hydrograph.py, weir.py, storage.py).
# Coefficient/exponent VALUES are illustrative test fixtures, not sourced facts (CLAUDE.md rule 3
# — no coefficient here is used as a code default; hydrograph.py always reads them from config).
SYNTH_VOLUME_ELEVATION_RELATION = {
    "method": "area_volume_relation",
    "area_volume_exponent_b": _source(1.5),
}

SYNTH_VOLUME_ELEVATION_SURVEYED = {
    "method": "surveyed_curve",
    "breach_invert_elevation_m": _source(2870.0, unit="m"),
    "points": _source(
        [[2870.0, 0.0], [2875.0, 1_500_000.0], [2880.0, 4_000_000.0], [2890.0, 12_000_000.0]],
        unit="m^3",
    ),
}

SYNTH_IMPOSED_RANGES = {
    "peak_discharge_m3s": _source([800.0, 1500.0], unit="m^3/s"),
    "breach_width_m": _source([20.0, 40.0], unit="m"),
    "failure_time_s": _source([600.0, 3600.0], unit="s"),
}

SYNTH_BREACH_HYDROGRAPH = {
    "weir_coefficient_rect": _source(1.7, unit="m^0.5/s"),
    "weir_coefficient_side": _source(1.3, unit="m^0.5/s"),
    "side_slope_z": _source(0.5),
}


@pytest.fixture
def make_config(synth_raw):
    """Build a SiteConfig from the synth fixture with dams[0] mutated.

    `overrides` is applied to dams[0].breach_inputs.<field>.value, and
    `kind`/`dam_type` are shortcuts for the two fields tests touch most.
    `volume_elevation`/`breach_hydrograph` attach those (optional) blocks whole, e.g.
    `SYNTH_VOLUME_ELEVATION_RELATION` / `SYNTH_BREACH_HYDROGRAPH` above.
    """

    def _make(kind: str | None = None, dam_type: str | None = None, volume_elevation: dict | None = None,
              breach_hydrograph: dict | None = None, equations_applicable: bool | None = None,
              imposed_ranges: dict | None = None, **field_overrides) -> SiteConfig:
        raw = copy.deepcopy(fully_sourced(synth_raw))
        dam = raw["dams"][0]
        if kind is not None:
            dam["kind"] = kind
        if dam_type is not None:
            dam["breach_inputs"]["dam_type"]["value"] = dam_type
        if volume_elevation is not None:
            dam["volume_elevation"] = copy.deepcopy(volume_elevation)
        if breach_hydrograph is not None:
            dam["breach_hydrograph"] = copy.deepcopy(breach_hydrograph)
        if equations_applicable is not None:
            dam["equations_applicable"] = equations_applicable
        if imposed_ranges is not None:
            dam["imposed_ranges"] = copy.deepcopy(imposed_ranges)
        for field, value in field_overrides.items():
            dam["breach_inputs"][field]["value"] = value
        return SiteConfig.model_validate(raw)

    return _make
