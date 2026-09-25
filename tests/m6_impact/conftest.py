"""Fixtures for backend/m6_impact tests. Reuses tests/fixtures/shared/synth.yaml
(fully sourced far-field bbox/grid_resolution/crs) rather than duplicating it."""

from __future__ import annotations

import pytest

from backend.shared.site_config import SiteConfig

from tests.shared.conftest import synth_raw  # noqa: F401  (re-exported fixture)


@pytest.fixture
def synth_config(synth_raw) -> SiteConfig:
    return SiteConfig.model_validate(synth_raw)
