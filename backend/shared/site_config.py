"""Site config model and loader for `sites/<site_id>.yaml` (schema v1).

The YAML layout is the one in `sites/template.yaml`. Every data value is a
SourcedValue: {value, unit, source, status[, note]}. A value missing `unit`,
`source` or `status` is rejected. `status: placeholder` values load, but the
loader warns loudly and lists them; every result built from such a config must
set `has_placeholders: true` (docs/handoff_contract.md §0 rule 5).

NOTE: this schema differs from docs/handoff_contract.md §3.1; the drift is
recorded in docs/decisions.md as a pending contract change.
"""

from __future__ import annotations

import logging
import math
import warnings
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any, Iterator, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

logger = logging.getLogger(__name__)

SITES_DIR = Path(__file__).resolve().parents[2] / "sites"

SITE_ID_PATTERN = r"^[a-z][a-z0-9_]{2,31}$"  # contract §1.7
SLUG_PATTERN = r"^[a-z][a-z0-9_]*$"

Unit = Literal["m", "m^3", "deg", "epsg", "enum", "iso8601"]
Status = Literal["sourced", "placeholder"]


class SiteConfigError(ValueError):
    """A site config file is missing or fails validation."""


class PlaceholderWarning(UserWarning):
    """A loaded site config contains `status: placeholder` values."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# =============================================================================
# SourcedValue and typed variants
# =============================================================================


class SourcedValue(_Strict):
    """A fact with its unit, source and status. `value` may be null only while placeholder."""

    value: float | int | str | list[float] | None
    unit: Unit
    source: str
    status: Status
    note: str | None = None

    @model_validator(mode="after")
    def _check_status(self):
        if self.value is None and self.status != "placeholder":
            raise ValueError(f"value is null but status is '{self.status}'; null is allowed only for placeholders")
        if self.status == "sourced" and not self.source.strip():
            raise ValueError("a sourced value needs a non-empty source (full citation)")
        return self


def _check_lon_lat(lon: float, lat: float) -> None:
    if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
        raise ValueError(f"({lon}, {lat}) is not a valid [lon, lat] in degrees (longitude first)")


class PointValue(SourcedValue):
    """[lon, lat] in EPSG:4326 decimal degrees."""

    value: list[float] | None
    unit: Literal["deg"]

    @field_validator("value")
    @classmethod
    def _point(cls, v):
        if v is not None:
            if len(v) != 2:
                raise ValueError(f"a point must be [lon, lat], got {len(v)} numbers")
            _check_lon_lat(*v)
        return v


class BBoxValue(SourcedValue):
    """[min_lon, min_lat, max_lon, max_lat] in EPSG:4326 decimal degrees."""

    value: list[float] | None
    unit: Literal["deg"]

    @field_validator("value")
    @classmethod
    def _bbox(cls, v):
        if v is not None:
            if len(v) != 4:
                raise ValueError(f"a bbox must be [min_lon, min_lat, max_lon, max_lat], got {len(v)} numbers")
            _check_lon_lat(v[0], v[1])
            _check_lon_lat(v[2], v[3])
            if not (v[0] < v[2] and v[1] < v[3]):
                raise ValueError(f"bbox {v} must satisfy min_lon < max_lon and min_lat < max_lat")
        return v


class LengthValue(SourcedValue):
    value: Annotated[float, Field(gt=0)] | None
    unit: Literal["m"]


class VolumeValue(SourcedValue):
    value: Annotated[float, Field(gt=0)] | None
    unit: Literal["m^3"]


class EpsgValue(SourcedValue):
    """A WGS 84 / UTM EPSG code (326nn north, 327nn south)."""

    value: int | None
    unit: Literal["epsg"]

    @field_validator("value")
    @classmethod
    def _utm(cls, v):
        if v is not None and not (32601 <= v <= 32660 or 32701 <= v <= 32760):
            raise ValueError(f"EPSG:{v} is not a WGS 84 / UTM zone (32601-32660, 32701-32760)")
        return v


class DamTypeValue(SourcedValue):
    value: Literal["HD", "CD", "FD", "ZD"] | None  # homogeneous | core-wall | concrete-faced | zoned-fill
    unit: Literal["enum"]


class FailureModeValue(SourcedValue):
    value: Literal["O", "P"] | None  # overtopping | piping
    unit: Literal["enum"]


class ErodibilityValue(SourcedValue):
    value: Literal["H", "M", "L"] | None
    unit: Literal["enum"]


class DateTimeValue(SourcedValue):
    """ISO 8601 date or datetime, kept as the original string."""

    value: str | None
    unit: Literal["iso8601"]

    @field_validator("value", mode="before")
    @classmethod
    def _iso(cls, v):
        if isinstance(v, (date, datetime)):  # unquoted YAML dates arrive as date objects
            v = v.isoformat()
        if v is not None:
            try:
                datetime.fromisoformat(v)
            except (TypeError, ValueError):
                raise ValueError(f"{v!r} is not an ISO 8601 date/datetime") from None
        return v


# =============================================================================
# Structure (mirrors sites/template.yaml)
# =============================================================================


class Site(_Strict):
    id: Annotated[str, Field(pattern=SITE_ID_PATTERN)]
    name: str
    region: str | None = None
    river: str | None = None


class Crs(_Strict):
    utm_epsg: EpsgValue


class Inflow(_Strict):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: str = Field(alias="from")  # a dam id, or "far_field" for the near-field domain
    location: PointValue


class Domain(_Strict):
    description: str | None = None
    bbox: BBoxValue
    grid_resolution: LengthValue
    inflow: Inflow


class Domains(_Strict):
    far_field: Domain
    near_field: Domain


class BreachInputs(_Strict):
    water_volume_above_invert: VolumeValue
    water_height_above_invert: LengthValue
    breach_height: LengthValue
    dam_height: LengthValue
    average_embankment_width: LengthValue
    dam_type: DamTypeValue
    failure_mode: FailureModeValue
    erodibility: ErodibilityValue


class Dam(_Strict):
    id: Annotated[str, Field(pattern=SLUG_PATTERN)]
    name: str
    kind: Literal["moraine_dammed_lake", "embankment_dam", "concrete_dam", "landslide_dam"]
    triggered_by: str | None = None
    location: PointValue
    breach_location: PointValue
    breach_inputs: BreachInputs


class PointOfInterest(_Strict):
    id: Annotated[str, Field(pattern=SLUG_PATTERN)]
    name: str
    category: Literal["village", "dam", "bridge", "hospital"]
    location: PointValue


class Event(_Strict):
    id: Annotated[str, Field(pattern=SLUG_PATTERN)]
    name: str
    kind: Literal["historical", "hypothetical"]
    onset: DateTimeValue
    breach_times: dict[str, DateTimeValue]
    simulation_start: DateTimeValue
    simulation_end: DateTimeValue
    imagery_pre_event: DateTimeValue
    imagery_post_event: DateTimeValue


def _bbox_contains(outer: list[float], inner: list[float]) -> bool:
    return outer[0] <= inner[0] and outer[1] <= inner[1] and inner[2] <= outer[2] and inner[3] <= outer[3]


def _duplicates(ids: list[str]) -> list[str]:
    return sorted({i for i in ids if ids.count(i) > 1})


class SiteConfig(_Strict):
    schema_version: Literal[1]
    site: Site
    crs: Crs
    domains: Domains
    dams: Annotated[list[Dam], Field(min_length=1)]  # upstream -> downstream
    points_of_interest: list[PointOfInterest] = []
    events: list[Event] = []

    @model_validator(mode="after")
    def _cross_checks(self):
        dam_ids = [d.id for d in self.dams]
        for label, ids in (("dam", dam_ids),
                           ("point_of_interest", [p.id for p in self.points_of_interest]),
                           ("event", [e.id for e in self.events])):
            if dups := _duplicates(ids):
                raise ValueError(f"duplicate {label} id(s): {', '.join(dups)}")

        for i, dam in enumerate(self.dams):
            if dam.triggered_by is not None and dam.triggered_by not in dam_ids[:i]:
                raise ValueError(f"dams[{i}].triggered_by '{dam.triggered_by}' is not a dam id listed "
                                 f"before it (dams are ordered upstream -> downstream)")

        ff, nf = self.domains.far_field, self.domains.near_field
        if ff.inflow.from_ not in dam_ids:
            raise ValueError(f"domains.far_field.inflow.from '{ff.inflow.from_}' must be a dam id")
        if nf.inflow.from_ not in [*dam_ids, "far_field"]:
            raise ValueError(f"domains.near_field.inflow.from '{nf.inflow.from_}' must be a dam id or 'far_field'")

        for event in self.events:
            if unknown := sorted(set(event.breach_times) - set(dam_ids)):
                raise ValueError(f"events '{event.id}' breach_times has unknown dam id(s): {', '.join(unknown)}")

        if ff.bbox.value is not None and nf.bbox.value is not None and not _bbox_contains(ff.bbox.value, nf.bbox.value):
            raise ValueError(f"near_field bbox {nf.bbox.value} must lie inside far_field bbox {ff.bbox.value}")

        far_cs, near_cs = ff.grid_resolution.value, nf.grid_resolution.value
        if far_cs is not None and near_cs is not None:
            ratio = far_cs / near_cs
            if near_cs > far_cs or not math.isclose(ratio, round(ratio), abs_tol=1e-9):
                raise ValueError(f"near_field grid_resolution ({near_cs} m) must divide far_field "
                                 f"grid_resolution ({far_cs} m) exactly")

        for dam in self.dams:
            hb, hd = dam.breach_inputs.breach_height.value, dam.breach_inputs.dam_height.value
            if hb is not None and hd is not None and hb > hd:
                warnings.warn(f"dam '{dam.id}': breach_height ({hb} m) exceeds dam_height ({hd} m)",
                              UserWarning, stacklevel=2)
        return self

    @property
    def placeholder_fields(self) -> list[str]:
        """Dotted paths of every `status: placeholder` value, in file order."""
        return list(_placeholder_paths(self, ""))

    @property
    def has_placeholders(self) -> bool:
        return bool(self.placeholder_fields)


def _placeholder_paths(obj: Any, path: str) -> Iterator[str]:
    if isinstance(obj, SourcedValue):
        if obj.status == "placeholder":
            yield path
    elif isinstance(obj, BaseModel):
        for name in type(obj).model_fields:
            yield from _placeholder_paths(getattr(obj, name), f"{path}.{name}" if path else name)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            yield from _placeholder_paths(item, f"{path}[{i}]")
    elif isinstance(obj, dict):
        for key, item in obj.items():
            yield from _placeholder_paths(item, f"{path}.{key}")


# =============================================================================
# Loader
# =============================================================================


def _resolve_path(path_or_id: str | Path, sites_dir: str | Path | None) -> Path:
    p = Path(path_or_id)
    if p.suffix in (".yaml", ".yml"):
        return p
    return Path(sites_dir or SITES_DIR) / f"{path_or_id}.yaml"


def load_site_config(path_or_id: str | Path, sites_dir: str | Path | None = None) -> SiteConfig:
    """Load and validate a site config.

    `path_or_id` is a path to a .yaml file or a site id looked up in `sites_dir`
    (default: the repo's `sites/`). Raises FileNotFoundError or SiteConfigError.
    Emits one PlaceholderWarning (and a log warning) listing every placeholder.
    """
    path = _resolve_path(path_or_id, sites_dir)
    if not path.is_file():
        raise FileNotFoundError(f"site config not found: {path}")

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise SiteConfigError(f"{path}: expected a YAML mapping at the top level")

    try:
        cfg = SiteConfig.model_validate(raw)
    except ValidationError as e:
        raise SiteConfigError(f"{path}: invalid site config\n{e}") from e

    if cfg.site.id != path.stem:
        raise SiteConfigError(f"{path}: site.id '{cfg.site.id}' must equal the file name '{path.stem}'")

    placeholders = cfg.placeholder_fields
    if placeholders:
        bar = "!" * 78
        msg = (f"\n{bar}\n{path}: {len(placeholders)} PLACEHOLDER value(s) — NOT for real results.\n"
               f"Every result built from this config must set has_placeholders=true.\n"
               + "\n".join(f"  - {p}" for p in placeholders) + f"\n{bar}")
        logger.warning(msg)
        warnings.warn(msg, PlaceholderWarning, stacklevel=2)
    return cfg
