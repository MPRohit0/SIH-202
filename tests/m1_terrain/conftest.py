"""Fixtures for backend/m1_terrain tests. Reuses tests/fixtures/shared/synth.yaml, plus a
synthetic V-shaped valley DEM/landcover (`synthetic_valley.py`) so every pipeline stage has a
known-correct answer to check against (CLAUDE.md rule 2: synthetic data, not real DEMs, for
module tests)."""

from __future__ import annotations

import copy

import pytest

from backend.shared.site_config import SiteConfig

from tests.shared.conftest import synth_raw  # noqa: F401  (re-exported fixture)

from . import synthetic_valley as sv

BREACH_LONLAT = (88.46, 27.54)      # synth.yaml dams[0] (synth_lake) breach_location
LAKE_LONLAT = (88.46, 27.545)       # synth.yaml dams[0] location
DOWNSTREAM_LONLAT = (88.49, 27.49)  # synth.yaml points_of_interest[0] (town_a) location

# The second dam sits 1500 m downstream of the breach, exactly on the analytical thalweg (d=0),
# so its reservoir bowl is centred on the channel.
SECOND_DAM_S_M = 1500.0


@pytest.fixture
def synth_config(synth_raw) -> SiteConfig:
    return SiteConfig.model_validate(synth_raw)


@pytest.fixture
def valley_geometry() -> sv.ValleyGeometry:
    return sv.valley_geometry(BREACH_LONLAT, DOWNSTREAM_LONLAT)


@pytest.fixture
def second_dam_lonlat(valley_geometry) -> tuple[float, float]:
    x, y = valley_geometry.point_at(SECOND_DAM_S_M)
    return sv.utm_to_lonlat(x, y)


def _sourced(value, unit, note="Synthetic test fixture - not real data"):
    return {"value": value, "unit": unit, "source": note, "status": "sourced"}


@pytest.fixture
def synth_raw_two_dams(synth_raw, second_dam_lonlat) -> dict:
    """`synth_raw` with a second (embankment) dam downstream of `synth_lake`, on the analytical
    thalweg, fully sourced (no placeholders) so terrain burn-in/reservoir tests don't need to
    special-case a null input."""
    data = copy.deepcopy(synth_raw)
    lon, lat = second_dam_lonlat
    data["dams"].append({
        "id": "synth_dam2",
        "name": "Synthetic embankment dam",
        "kind": "embankment_dam",
        "triggered_by": None,
        "location": _sourced([lon, lat], "deg"),
        "breach_location": _sourced([lon, lat], "deg"),
        "breach_inputs": {
            "water_volume_above_invert": _sourced(500_000, "m^3"),
            "water_height_above_invert": _sourced(10, "m"),
            "breach_height": _sourced(10, "m"),
            "dam_height": _sourced(15, "m"),
            "average_embankment_width": _sourced(80, "m"),
            "dam_type": _sourced("HD", "enum"),
            "failure_mode": _sourced("O", "enum"),
            "erodibility": _sourced("H", "enum"),
        },
    })
    return data


@pytest.fixture
def synth_config_two_dams(synth_raw_two_dams) -> SiteConfig:
    return SiteConfig.model_validate(synth_raw_two_dams)
