from __future__ import annotations

import pytest

pytest_plugins = ["tests.shared.conftest", "tests.m4_sph.conftest"]


@pytest.fixture
def synth_m3_sites_dir(synth_raw_sph, write_site):
    data = synth_raw_sph
    data["domains"]["far_field"]["inflow"]["base_flow"] = {
        "value": 12.0, "unit": "m^3/s", "source": "Synthetic test fixture", "status": "placeholder",
    }
    return write_site(data, stem="synth").parent
