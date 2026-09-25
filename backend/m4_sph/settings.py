"""M4 SPH case settings (`config/m4_sph.yaml`) -- numerical/solver knobs, not site facts
(docs/handoff_contract.md rule 3; the contract itself notes M3/M4 simulation settings aren't in
`SiteConfig` yet). Loaded once per call and overridable, the way `config/manning_n.csv` is
project-maintained but not a `SourcedValue`."""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from pathlib import Path

import yaml

DEFAULT_SETTINGS_PATH = Path(__file__).resolve().parents[2] / "config" / "m4_sph.yaml"


@dataclass(frozen=True)
class SphSettings:
    dp_m: float | str = "auto"
    t_start_s: float = 0.0
    t_end_s: float | None = None
    time_out_s: float = 5.0
    inlet_width_m: float = 20.0
    inlet_height_m: float = 15.0
    inlet_layers: int = 4
    boundary_layers: int = 3
    probe_velocity_height_m: float = 1.0
    vram_budget_mib: float = 8188.0
    vram_margin: float = 0.15
    binaries_dir: str | None = None

    def __post_init__(self):
        if not (isinstance(self.dp_m, (int, float)) and self.dp_m > 0) and self.dp_m != "auto":
            raise ValueError(f"dp_m must be 'auto' or a positive number, got {self.dp_m!r}")
        if self.t_end_s is not None and self.t_end_s <= self.t_start_s:
            raise ValueError(f"t_end_s ({self.t_end_s}) must be greater than t_start_s ({self.t_start_s})")
        if not 0.0 <= self.vram_margin < 1.0:
            raise ValueError(f"vram_margin must be in [0, 1), got {self.vram_margin}")


def load_sph_settings(path: str | Path | None = None, **overrides) -> SphSettings:
    """Load `config/m4_sph.yaml` (or `path`), applying any keyword overrides on top."""
    path = Path(path) if path is not None else DEFAULT_SETTINGS_PATH
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    known = {f.name for f in fields(SphSettings)}
    unknown = set(raw) - known
    if unknown:
        raise ValueError(f"{path}: unknown setting(s): {', '.join(sorted(unknown))}")
    settings = SphSettings(**raw)
    return replace(settings, **overrides) if overrides else settings
