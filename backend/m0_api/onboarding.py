"""Thin M0 orchestration for the contract-backed onboarding preparation steps.

This module passes the canonical ``SiteConfig`` and M2 scenario design between
modules. M1 and M2 remain independent of the API and each other.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from backend.m1_terrain.pipeline import build_terrain
from backend.m5_emulator import scenario_design
from backend.m5_emulator.scenario_design import ScenarioDesignSettings
from backend.m2_breach.breach_params import write_breach_params
from backend.shared.site_config import load_site_config


def materialize_site_config(site_id: str, config: dict, data_dir: str | Path) -> Path:
    """Persist the accepted JSON config in YAML form for module loaders."""
    root = Path(data_dir) / site_id / "config"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{site_id}.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def _load_config(site_id: str, data_dir: str | Path, config: dict | None = None):
    root = Path(data_dir) / site_id / "config"
    path = root / f"{site_id}.yaml"
    if config is not None:
        materialize_site_config(site_id, config, data_dir)
    if not path.is_file():
        raise FileNotFoundError(f"onboarding site config is missing: {path}")
    return load_site_config(site_id, sites_dir=root)


def prepare_terrain(site_id: str, data_dir: str | Path, config: dict | None = None) -> dict:
    """Run M1 from prepared raw contract inputs; refuse an ambiguous DEM choice."""
    from backend.m1_terrain import download

    cfg = _load_config(site_id, data_dir, config)
    raw_dir = Path(data_dir) / site_id / "raw"
    provenance_path = raw_dir / "provenance.json"
    if not provenance_path.is_file():
        raise FileNotFoundError(
            f"M1 raw inputs are missing at {raw_dir}; prepare DEM and land-cover data first"
        )
    raw_provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    candidates = [product for product in download.OPENTOPOGRAPHY_PRODUCTS
                  if f"dem_{product}" in raw_provenance]
    if len(candidates) != 1:
        raise ValueError(
            "M1 needs a selected DEM product; raw provenance must contain exactly one supported "
            f"candidate for this onboarding run, found {candidates}"
        )
    product = candidates[0]
    return build_terrain(cfg, product, raw_dir, Path(data_dir) / site_id / "terrain")


def prepare_breach(site_id: str, data_dir: str | Path) -> Path:
    """Run M2 and write its canonical breach-parameter result."""
    cfg = _load_config(site_id, data_dir)
    return write_breach_params(cfg, data_dir=Path(data_dir))


def prepare_design(site_id: str, data_dir: str | Path, *, demo: bool = False) -> Path:
    """Run M5's scenario design over M2's computed ranges."""
    cfg = _load_config(site_id, data_dir)
    target_dam = cfg.domains.far_field.inflow.from_
    settings = scenario_design.load_scenario_design_settings()
    if demo:
        settings = ScenarioDesignSettings(
            n=4, n_holdout=0, seed=settings.seed,
            input_widen_fraction=settings.input_widen_fraction, method=settings.method,
        )
    return scenario_design.write_scenario_design(
        cfg, target_dam, data_dir=Path(data_dir), settings=settings,
    )
