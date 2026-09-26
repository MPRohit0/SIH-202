from backend.m4_sph.vram_estimator import (
    PILOT_DIR,
    calibrate,
    estimate_particle_count,
    estimate_vram_mib,
    parse_dualsphysics_log,
    parse_nvidia_smi_log,
    smallest_dp_within_budget,
)


def test_parse_dualsphysics_log_matches_pilot_run():
    stats = parse_dualsphysics_log(PILOT_DIR / "dualsphysics_output.log")
    assert stats["max_particles"] == 21001
    assert stats["max_cells"] == 22720
    assert stats["gpu_memory_bytes"] == 3764136
    assert stats["gpu_memory_cells_bytes"] == 363560


def test_parse_nvidia_smi_log_matches_pilot_run():
    stats = parse_nvidia_smi_log(PILOT_DIR / "nvidia_smi.log")
    assert stats["baseline_mib"] == 815
    assert stats["peak_mib"] == 974


def test_calibration_is_positive_and_sane():
    cal = calibrate()
    assert cal.bytes_per_particle > 0
    assert cal.bytes_per_cell > 0
    assert cal.cells_per_particle > 0
    assert cal.context_overhead_mib >= 0


def test_particle_count_scales_with_volume_and_dp():
    small = estimate_particle_count(10, 10, 1, dp_m=0.5)
    large_domain = estimate_particle_count(20, 20, 1, dp_m=0.5)
    finer_dp = estimate_particle_count(10, 10, 1, dp_m=0.25)

    assert large_domain["total_particles"] > small["total_particles"]
    assert finer_dp["total_particles"] > small["total_particles"]


def test_vram_estimate_increases_with_particle_count():
    cal = calibrate()
    low = estimate_vram_mib(1000, cal)
    high = estimate_vram_mib(1_000_000, cal)
    assert high > low
    assert low >= cal.context_overhead_mib


def test_smallest_dp_within_budget_is_feasible_and_monotonic():
    cal = calibrate()
    result = smallest_dp_within_budget(50, 50, 2, cal, vram_budget_mib=8188, margin=0.15)
    assert result["feasible"] is True
    assert result["predicted_vram_mib"] <= result["budget_mib"]

    # a finer dp than the reported answer should no longer fit
    finer = result["dp_m"] * 0.9
    counts = estimate_particle_count(50, 50, 2, finer)
    assert estimate_vram_mib(counts["total_particles"], cal) > result["budget_mib"]


def test_infeasible_case_reports_reason():
    cal = calibrate()
    result = smallest_dp_within_budget(
        5000, 5000, 50, cal, vram_budget_mib=8188, margin=0.15, dp_max_m=2.0
    )
    assert result["feasible"] is False
    assert "reason" in result
