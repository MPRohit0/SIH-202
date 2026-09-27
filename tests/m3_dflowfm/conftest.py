from __future__ import annotations

import pytest

# Re-export shared fixtures into this test subtree rather than registering sibling conftests as
# plugins (pytest 8 rejects non-root `pytest_plugins` declarations).
from tests.shared.conftest import synth_raw, write_site  # noqa: F401
from tests.m4_sph.conftest import (  # noqa: F401
    synth_config_sph, synth_hydrograph_params, synth_raw_sph, synth_sites_dir,
    synth_terrain_dir,
)


@pytest.fixture
def synth_m3_sites_dir(synth_raw_sph, write_site):
    data = synth_raw_sph
    data["domains"]["far_field"]["inflow"]["base_flow"] = {
        "value": 12.0, "unit": "m^3/s", "source": "Synthetic test fixture", "status": "placeholder",
    }
    return write_site(data, stem="synth").parent
