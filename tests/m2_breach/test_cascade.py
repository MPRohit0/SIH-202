"""Tests for backend.m2_breach.cascade — two-stage imposed cascade triggering.

Uses tests/fixtures/m2_breach/synth_cascade.yaml: synth_lake (moraine, upstream, HD) ->
synth_dam2 (concrete, triggered_by synth_lake, equations_applicable: false).
"""

from __future__ import annotations

import copy

import numpy as np
import pytest

from backend.m2_breach.cascade import (
    CascadeStage,
    UnsupportedCascadeApproach,
    cascade_plan,
    trigger_time,
    triggered_hydrograph,
)
from backend.m2_breach.hydrograph import HydrographBlocked, hydrograph_for_dam
from backend.m0_api import schemas
from backend.shared.site_config import SiteConfig

DAM2_PARAMS = {
    "water_volume_m3": 500_000.0,
    "breach_width_m": 30.0,
    "failure_time_s": 600.0,
    "peak_discharge_m3s": 900.0,
}


# ---------------------------------------------------------------------------
# cascade_plan
# ---------------------------------------------------------------------------


def test_cascade_plan_order_and_threshold(synth_cascade_config):
    plan = cascade_plan(synth_cascade_config)
    assert [s.dam_id for s in plan] == ["synth_lake", "synth_dam2"]

    upstream, downstream = plan
    assert upstream.order == 0 and upstream.triggered_by is None and upstream.threshold_m3s is None
    assert downstream.order == 1 and downstream.triggered_by == "synth_lake"
    assert downstream.threshold_m3s == 500.0
    assert downstream.equations_applicable is False
    assert upstream.equations_applicable is True


def test_cascade_plan_three_dam_chain(synth_cascade_raw):
    raw = copy.deepcopy(synth_cascade_raw)
    dam3 = copy.deepcopy(raw["dams"][1])
    dam3["id"] = "synth_dam3"
    dam3["name"] = "Synthetic third dam"
    dam3["triggered_by"] = "synth_dam2"
    dam3["trigger"]["value"]["value"] = 700.0
    raw["dams"].append(dam3)

    cfg = SiteConfig.model_validate(raw)
    plan = cascade_plan(cfg)
    assert [s.dam_id for s in plan] == ["synth_lake", "synth_dam2", "synth_dam3"]
    assert plan[2].triggered_by == "synth_dam2"
    assert plan[2].threshold_m3s == 700.0


def test_cascade_plan_rejects_dambreak_structure(synth_cascade_raw):
    raw = copy.deepcopy(synth_cascade_raw)
    raw["cascade"]["approach"] = "dambreak_structure"
    cfg = SiteConfig.model_validate(raw)
    with pytest.raises(UnsupportedCascadeApproach):
        cascade_plan(cfg)


# ---------------------------------------------------------------------------
# trigger_time
# ---------------------------------------------------------------------------


def test_trigger_time_linear_interpolation():
    t_s = [0.0, 100.0, 200.0, 300.0]
    q_m3s = [0.0, 400.0, 800.0, 1000.0]
    # threshold 600 is halfway between t=100 (q=400) and t=200 (q=800)
    t = trigger_time(t_s, q_m3s, 600.0)
    assert t == pytest.approx(150.0)


def test_trigger_time_exact_sample():
    t_s = [0.0, 100.0, 200.0]
    q_m3s = [0.0, 500.0, 1000.0]
    assert trigger_time(t_s, q_m3s, 500.0) == pytest.approx(100.0)


def test_trigger_time_never_reached():
    t_s = [0.0, 100.0, 200.0]
    q_m3s = [0.0, 100.0, 200.0]
    assert trigger_time(t_s, q_m3s, 5000.0) is None


def test_trigger_time_first_sample_already_above():
    t_s = [0.0, 100.0]
    q_m3s = [700.0, 800.0]
    assert trigger_time(t_s, q_m3s, 500.0) == pytest.approx(0.0)


def test_trigger_time_rejects_non_increasing_t():
    with pytest.raises(ValueError, match="strictly increasing"):
        trigger_time([0.0, 100.0, 50.0], [0.0, 100.0, 200.0], 50.0)


def test_trigger_time_rejects_negative_start():
    with pytest.raises(ValueError, match="t0"):
        trigger_time([-10.0, 0.0, 100.0], [0.0, 100.0, 200.0], 50.0)


# ---------------------------------------------------------------------------
# triggered_hydrograph
# ---------------------------------------------------------------------------


def test_triggered_hydrograph_sets_t_offset_and_zero_before_it(synth_cascade_config):
    inflow_t_s = np.array([0.0, 200.0, 400.0, 600.0])
    inflow_q_m3s = np.array([0.0, 300.0, 600.0, 900.0])  # crosses 500 between 200 and 400

    hg, trigger = triggered_hydrograph(synth_cascade_config, "synth_dam2", DAM2_PARAMS,
                                        inflow_t_s, inflow_q_m3s, inflow_source="synthetic_test")

    assert trigger.triggered is True
    assert trigger.trigger_time_s == pytest.approx(1000.0 / 3.0)
    assert trigger.threshold_m3s == 500.0
    assert trigger.triggered_by == "synth_lake"
    assert trigger.inflow_peak_m3s == pytest.approx(900.0)

    assert hg is not None
    assert hg.t_offset_s == pytest.approx(1000.0 / 3.0)
    before = hg.t_s < hg.t_offset_s
    assert np.all(hg.q_m3s[before] == 0.0)
    assert "cascade_superposition" in {c["id"] for c in hg.caveats}


def test_triggered_hydrograph_releases_own_storage_only(synth_cascade_config):
    """Superposition: the hydrograph conserves synth_dam2's own water_volume_m3, not the
    upstream inflow volume."""
    inflow_t_s = np.array([0.0, 100.0, 200.0])
    inflow_q_m3s = np.array([0.0, 600.0, 1200.0])

    hg, _ = triggered_hydrograph(synth_cascade_config, "synth_dam2", DAM2_PARAMS,
                                  inflow_t_s, inflow_q_m3s, inflow_source="synthetic_test")
    assert hg.volume_m3 == pytest.approx(DAM2_PARAMS["water_volume_m3"], rel=1e-6)


def test_triggered_hydrograph_peak_checked_against_imposed_range(synth_cascade_config):
    inflow_t_s = np.array([0.0, 100.0, 200.0])
    inflow_q_m3s = np.array([0.0, 600.0, 1200.0])
    hg, _ = triggered_hydrograph(synth_cascade_config, "synth_dam2", DAM2_PARAMS,
                                  inflow_t_s, inflow_q_m3s, inflow_source="synthetic_test")
    # DAM2_PARAMS peak_discharge_m3s=900 is within the imposed range [800, 1500].
    assert hg.peak_within_m2_range is True


def test_triggered_hydrograph_not_triggered_returns_none(synth_cascade_config):
    inflow_t_s = np.array([0.0, 100.0, 200.0])
    inflow_q_m3s = np.array([0.0, 50.0, 100.0])  # never reaches 500

    hg, trigger = triggered_hydrograph(synth_cascade_config, "synth_dam2", DAM2_PARAMS,
                                        inflow_t_s, inflow_q_m3s, inflow_source="synthetic_test")
    assert hg is None
    assert trigger.triggered is False
    assert trigger.trigger_time_s is None
    assert trigger.inflow_peak_m3s == pytest.approx(100.0)


def test_triggered_hydrograph_placeholder_threshold_blocks(synth_cascade_raw):
    raw = copy.deepcopy(synth_cascade_raw)
    raw["dams"][1]["trigger"]["value"] = {
        "value": None, "unit": "m^3/s", "source": "Placeholder: not sourced yet", "status": "placeholder",
    }
    cfg = SiteConfig.model_validate(raw)

    with pytest.raises(HydrographBlocked):
        triggered_hydrograph(cfg, "synth_dam2", DAM2_PARAMS,
                              [0.0, 100.0], [0.0, 1000.0], inflow_source="synthetic_test")


def test_triggered_hydrograph_rejects_non_triggered_dam(synth_cascade_config):
    with pytest.raises(ValueError, match="not a triggered dam"):
        triggered_hydrograph(synth_cascade_config, "synth_lake", DAM2_PARAMS,
                              [0.0, 100.0], [0.0, 1000.0], inflow_source="synthetic_test")


def test_triggered_hydrograph_sidecar_validates_against_schema(synth_cascade_config):
    from dataclasses import replace

    inflow_t_s = np.array([0.0, 200.0, 400.0])
    inflow_q_m3s = np.array([0.0, 300.0, 900.0])
    hg, _ = triggered_hydrograph(synth_cascade_config, "synth_dam2", DAM2_PARAMS,
                                  inflow_t_s, inflow_q_m3s, inflow_source="synthetic_test")
    hg = replace(hg, scenario_id="synth_cascade__s001")
    schemas.validate("hydrograph_sidecar.schema.json", hg.sidecar())


# ---------------------------------------------------------------------------
# End-to-end: upstream hydrograph -> synthetic routed inflow -> downstream trigger
# ---------------------------------------------------------------------------


def test_end_to_end_upstream_hydrograph_drives_downstream_trigger(synth_cascade_config):
    upstream = synth_cascade_config.dams[0]
    upstream_params = {
        "water_volume_m3": 1_000_000.0,
        "breach_width_m": 45.0,
        "failure_time_s": 900.0,
        "peak_discharge_m3s": 1800.0,
    }
    upstream_hg = hydrograph_for_dam(upstream, upstream_params)
    assert upstream_hg.t_offset_s == 0.0  # most upstream dam: t_offset_s = 0 (t0 rule)

    # Stand-in for a stage-1 Delft3D routed-inflow observation at synth_dam2: a lagged,
    # attenuated copy of the upstream hydrograph. NOT a routing model — test scaffolding only.
    lag_s = 250.0
    attenuation = 0.7
    downstream_t_s = upstream_hg.t_s + lag_s
    downstream_q_m3s = upstream_hg.q_m3s * attenuation

    hg, trigger = triggered_hydrograph(synth_cascade_config, "synth_dam2", DAM2_PARAMS,
                                        downstream_t_s, downstream_q_m3s,
                                        inflow_source="synthetic_test:lagged_upstream_hydrograph")

    assert trigger.triggered is True
    # the downstream dam cannot fail before the (lagged) inflow arrives
    assert trigger.trigger_time_s >= lag_s
    assert hg.t_offset_s == trigger.trigger_time_s
