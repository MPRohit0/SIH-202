import pytest

from backend.m4_sph.settings import DEFAULT_SETTINGS_PATH, SphSettings, load_sph_settings


def test_default_settings_load():
    settings = load_sph_settings()
    assert settings.dp_m == "auto"
    assert settings.vram_budget_mib == 8188.0
    assert 0.0 <= settings.vram_margin < 1.0


def test_overrides_apply_on_top_of_the_file():
    settings = load_sph_settings(dp_m=0.05, t_end_s=100.0)
    assert settings.dp_m == 0.05
    assert settings.t_end_s == 100.0
    assert settings.inlet_width_m == 20.0  # unmodified default from the file


def test_unknown_setting_in_file_rejected(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("dp_m: auto\nnot_a_real_setting: 1\n")
    with pytest.raises(ValueError, match="unknown setting"):
        load_sph_settings(bad)


@pytest.mark.parametrize("kwargs", [
    {"dp_m": -0.01},
    {"dp_m": 0},
    {"dp_m": "not_auto"},
    {"t_start_s": 10.0, "t_end_s": 10.0},
    {"t_start_s": 10.0, "t_end_s": 5.0},
    {"vram_margin": 1.0},
    {"vram_margin": -0.1},
])
def test_invalid_settings_raise(kwargs):
    with pytest.raises(ValueError):
        SphSettings(**kwargs)


def test_config_file_exists():
    assert DEFAULT_SETTINGS_PATH.exists()
