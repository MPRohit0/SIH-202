"""Fixtures for backend/m4_sph tests: a synthetic near-field terrain (built by the real M1
pipeline over the synthetic V-shaped valley) plus a site config whose near-field inflow is a dam,
not `far_field` -- so the SPH inlet has an M2 hydrograph to draw on (CLAUDE.md rule 2: every
module runs end-to-end on synthetic data)."""

from __future__ import annotations

import pytest

from backend.m1_terrain.pipeline import build_terrain
from backend.m1_terrain.settings import TerrainSettings
from backend.shared.site_config import SiteConfig

from tests.m1_terrain import synthetic_valley as sv
from tests.m1_terrain.conftest import BREACH_LONLAT, DOWNSTREAM_LONLAT  # noqa: F401
from tests.shared.conftest import fully_sourced, synth_raw, write_site  # noqa: F401


@pytest.fixture
def synth_raw_sph(synth_raw) -> dict:
    """`synth_raw`, fully sourced, with the near-field inflow switched from `far_field` to the
    dam `synth_lake` -- so `hydrograph()` has something to compute at the inlet."""
    data = fully_sourced(synth_raw)
    inflow = data["domains"]["near_field"]["inflow"]
    inflow["from"] = "synth_lake"
    inflow["location"].update(
        value=list(DOWNSTREAM_LONLAT), status="sourced", source="Synthetic test fixture - not real data",
    )
    return data


@pytest.fixture
def synth_config_sph(synth_raw_sph) -> SiteConfig:
    return SiteConfig.model_validate(synth_raw_sph)


@pytest.fixture
def synth_sites_dir(write_site, synth_raw_sph):
    """`synth_raw_sph` written to `<tmp_path>/sites/synth.yaml`, for `load_site_config(sites_dir=...)`."""
    path = write_site(synth_raw_sph, stem="synth")
    return path.parent


@pytest.fixture
def synth_terrain_dir(tmp_path, synth_config_sph):
    """Run the real M1 pipeline over the synthetic valley, writing `data/synth/terrain/`-shaped
    output to `tmp_path/terrain`. Returns that directory."""
    cfg = synth_config_sph
    raw_dir, out_dir = tmp_path / "raw", tmp_path / "data" / "synth" / "terrain"
    bbox = cfg.domains.far_field.bbox.value
    breach = tuple(cfg.dams[0].breach_location.value)
    downstream = tuple(cfg.points_of_interest[0].location.value)
    lake = tuple(cfg.dams[0].location.value)
    sv.write_raw_rasters(raw_dir, bbox, breach, downstream, lake)
    sv.write_raw_provenance(raw_dir, "srtm_gl1")

    build_terrain(cfg, "srtm_gl1", raw_dir, out_dir, TerrainSettings())
    return out_dir


@pytest.fixture
def synth_hydrograph_params() -> dict:
    """Triangular-fallback params for `synth_lake` (no `volume_elevation` block -> weir method is
    blocked, `hydrograph()` falls back to `triangular`)."""
    return {
        "water_volume_m3": 1_000_000.0,
        "breach_width_m": 40.0,
        "failure_time_s": 1200.0,
        "peak_discharge_m3s": 500.0,
    }
