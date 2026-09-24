"""Tests for backend.shared.site_config — site config model and loader."""

import warnings

import pytest

from backend.shared.site_config import (
    PlaceholderWarning,
    SiteConfig,
    SiteConfigError,
    load_site_config,
)

from .conftest import SITES_DIR, SYNTH_PLACEHOLDERS, fully_sourced


def load_quiet(path, **kwargs) -> SiteConfig:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", PlaceholderWarning)
        return load_site_config(path, **kwargs)


# --------------------------------------------------------------------------- valid config


def test_synthetic_config_loads(synth_path):
    cfg = load_quiet(synth_path)
    assert isinstance(cfg, SiteConfig)
    assert cfg.site.id == "synth"
    assert cfg.crs.utm_epsg.value == 32645
    assert cfg.domains.far_field.bbox.value == [88.45, 27.45, 88.55, 27.55]
    assert cfg.domains.far_field.grid_resolution.value == 30
    assert cfg.domains.near_field.inflow.from_ == "far_field"
    assert cfg.dams[0].id == "synth_lake"
    assert cfg.dams[0].breach_inputs.dam_type.value == "HD"
    assert cfg.events[0].breach_times["synth_lake"].status == "sourced"


def test_placeholder_fields_listed_exactly(synth_config):
    assert synth_config.placeholder_fields == SYNTH_PLACEHOLDERS
    assert synth_config.has_placeholders is True


def test_load_by_site_id(synth_path):
    cfg = load_quiet("synth", sites_dir=synth_path.parent)
    assert cfg.site.id == "synth"


def test_fully_sourced_config_has_no_placeholders(synth_raw, write_site):
    path = write_site(fully_sourced(synth_raw))
    with warnings.catch_warnings():
        warnings.simplefilter("error", PlaceholderWarning)  # any placeholder warning fails the test
        cfg = load_site_config(path)
    assert cfg.placeholder_fields == []
    assert cfg.has_placeholders is False


# --------------------------------------------------------------------------- placeholder warning


def test_placeholder_warning_is_loud(synth_path):
    with pytest.warns(PlaceholderWarning) as record:
        load_site_config(synth_path)
    assert len(record) == 1, "exactly one consolidated warning per load"
    msg = str(record[0].message)
    assert "4 PLACEHOLDER" in msg
    assert "has_placeholders" in msg
    for field in SYNTH_PLACEHOLDERS:
        assert field in msg


def test_placeholder_warning_also_logged(synth_path, caplog):
    with pytest.warns(PlaceholderWarning), caplog.at_level("WARNING"):
        load_site_config(synth_path)
    assert any("PLACEHOLDER" in r.getMessage() for r in caplog.records)


# --------------------------------------------------------------------------- SourcedValue rules


@pytest.mark.parametrize("missing", ["unit", "source", "status"])
def test_value_missing_required_key_rejected(synth_raw, write_site, missing):
    del synth_raw["dams"][0]["breach_inputs"]["dam_height"][missing]
    with pytest.raises(SiteConfigError, match=missing):
        load_quiet(write_site(synth_raw))


@pytest.mark.parametrize("missing", ["unit", "source", "status"])
def test_nested_value_missing_key_rejected(synth_raw, write_site, missing):
    del synth_raw["events"][0]["breach_times"]["synth_lake"][missing]
    with pytest.raises(SiteConfigError):
        load_quiet(write_site(synth_raw))


def test_unknown_status_rejected(synth_raw, write_site):
    synth_raw["crs"]["utm_epsg"]["status"] = "guessed"
    with pytest.raises(SiteConfigError):
        load_quiet(write_site(synth_raw))


def test_null_value_requires_placeholder(synth_raw, write_site):
    synth_raw["dams"][0]["breach_inputs"]["dam_height"]["value"] = None
    with pytest.raises(SiteConfigError, match="null"):
        load_quiet(write_site(synth_raw))


def test_sourced_value_requires_nonempty_source(synth_raw, write_site):
    synth_raw["dams"][0]["breach_inputs"]["dam_height"]["source"] = "  "
    with pytest.raises(SiteConfigError, match="source"):
        load_quiet(write_site(synth_raw))


def test_placeholder_may_have_empty_source(synth_raw, write_site):
    synth_raw["points_of_interest"][1]["location"]["source"] = ""
    cfg = load_quiet(write_site(synth_raw))
    assert "points_of_interest[1].location" in cfg.placeholder_fields


def test_unknown_unit_rejected(synth_raw, write_site):
    synth_raw["dams"][0]["breach_inputs"]["dam_height"]["unit"] = "ft"
    with pytest.raises(SiteConfigError):
        load_quiet(write_site(synth_raw))


def test_wrong_unit_for_field_rejected(synth_raw, write_site):
    synth_raw["domains"]["far_field"]["bbox"]["unit"] = "m"
    with pytest.raises(SiteConfigError):
        load_quiet(write_site(synth_raw))


def test_extra_key_rejected(synth_raw, write_site):
    synth_raw["dams"][0]["breach_inputs"]["dam_height"]["units"] = "m"
    with pytest.raises(SiteConfigError):
        load_quiet(write_site(synth_raw))


def test_bad_enum_value_rejected(synth_raw, write_site):
    synth_raw["dams"][0]["breach_inputs"]["failure_mode"]["value"] = "overtopping"
    with pytest.raises(SiteConfigError):
        load_quiet(write_site(synth_raw))


def test_bad_bbox_order_rejected(synth_raw, write_site):
    synth_raw["domains"]["far_field"]["bbox"]["value"] = [88.55, 27.45, 88.45, 27.55]
    with pytest.raises(SiteConfigError):
        load_quiet(write_site(synth_raw))


def test_point_out_of_range_rejected(synth_raw, write_site):
    synth_raw["points_of_interest"][0]["location"]["value"] = [27.49, 188.49]
    with pytest.raises(SiteConfigError):
        load_quiet(write_site(synth_raw))


def test_non_utm_epsg_rejected(synth_raw, write_site):
    synth_raw["crs"]["utm_epsg"]["value"] = 4326
    with pytest.raises(SiteConfigError):
        load_quiet(write_site(synth_raw))


def test_bad_datetime_rejected(synth_raw, write_site):
    synth_raw["events"][0]["onset"]["value"] = "3rd October"
    with pytest.raises(SiteConfigError):
        load_quiet(write_site(synth_raw))


# --------------------------------------------------------------------------- cross-field rules


def test_site_id_must_match_file_name(synth_raw, write_site):
    with pytest.raises(SiteConfigError, match="file name"):
        load_quiet(write_site(synth_raw, stem="other_name"))


def test_bad_site_id_pattern_rejected(synth_raw, write_site):
    synth_raw["site"]["id"] = "Synth-Site"
    with pytest.raises(SiteConfigError):
        load_quiet(write_site(synth_raw, stem="Synth-Site"))


def test_unknown_triggered_by_rejected(synth_raw, write_site):
    synth_raw["dams"][0]["triggered_by"] = "no_such_dam"
    with pytest.raises(SiteConfigError, match="triggered_by"):
        load_quiet(write_site(synth_raw))


def test_unknown_inflow_from_rejected(synth_raw, write_site):
    synth_raw["domains"]["far_field"]["inflow"]["from"] = "no_such_dam"
    with pytest.raises(SiteConfigError, match="inflow"):
        load_quiet(write_site(synth_raw))


def test_unknown_breach_time_dam_rejected(synth_raw, write_site):
    bt = synth_raw["events"][0]["breach_times"]
    bt["ghost_dam"] = bt.pop("synth_lake")
    with pytest.raises(SiteConfigError, match="breach_times"):
        load_quiet(write_site(synth_raw))


def test_duplicate_dam_ids_rejected(synth_raw, write_site):
    import copy

    synth_raw["dams"].append(copy.deepcopy(synth_raw["dams"][0]))
    with pytest.raises(SiteConfigError, match="duplicate"):
        load_quiet(write_site(synth_raw))


def test_near_field_outside_far_field_rejected(synth_raw, write_site):
    synth_raw["domains"]["near_field"]["bbox"]["value"] = [88.54, 27.48, 88.60, 27.50]
    with pytest.raises(SiteConfigError, match="near_field"):
        load_quiet(write_site(synth_raw))


def test_non_dividing_cell_sizes_rejected(synth_raw, write_site):
    synth_raw["domains"]["near_field"]["grid_resolution"]["value"] = 7
    with pytest.raises(SiteConfigError, match="divide"):
        load_quiet(write_site(synth_raw))


def test_breach_higher_than_dam_warns(synth_raw, write_site):
    synth_raw["dams"][0]["breach_inputs"]["breach_height"]["value"] = 40
    with pytest.warns(UserWarning, match="breach_height"):
        load_quiet(write_site(synth_raw))


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_site_config(tmp_path / "nope.yaml")


# --------------------------------------------------------------------------- real config smoke test


def test_teesta_config_loads_with_placeholder_warning():
    with pytest.warns(PlaceholderWarning):
        cfg = load_site_config(SITES_DIR / "teesta.yaml")
    assert cfg.site.id == "teesta"
    assert cfg.crs.utm_epsg.value == 32645
    assert cfg.has_placeholders is True
    assert [d.id for d in cfg.dams] == ["south_lhonak", "teesta_iii"]
