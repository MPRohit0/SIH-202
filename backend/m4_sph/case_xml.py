"""GenCase `_Def.xml` model and writer (DualSPHysics 5.4, `XML_GUIDE_v5.4.pdf`).

GenCase's XML is plain, order-sensitive XML where documentation lives in `comment` /
`units_comment` *attributes* rather than XML comments, and a leading underscore on a tag name
(`_hdp`, `_computedt`, ...) means "documented but disabled" (GenCase ignores it, following the
convention used throughout the stock example decks). `CaseSpec` models the subset of the format
this project's near-field cases use: constants, geometry (a `dp`/pointmin/pointmax box, boundary
built from an STL file, one fluid fill box), inlet/outlet zones, gauges and execution parameters.

`canonicalize()` / `diff_trees()` strip the documentation attributes and disabled elements so two
trees can be compared on the values GenCase actually reads — used to diff a regenerated case
against a reference case built by hand in GenCase.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

_DOC_ATTRS = {"comment", "units_comment"}


def E(tag: str, attrib: dict | None = None, children: list[ET.Element] | None = None) -> ET.Element:
    """Build an `xml.etree.Element`, attributes stringified in insertion order."""
    el = ET.Element(tag, {k: _fmt(v) for k, v in (attrib or {}).items()})
    for child in children or []:
        el.append(child)
    return el


def _fmt(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if hasattr(value, "item") and not isinstance(value, str):
        value = value.item()  # unwrap numpy scalars (np.float64, np.int64, ...)
    if isinstance(value, float):
        return repr(value)
    return str(value)


def point(tag: str, x: float, y: float, z: float, **extra) -> ET.Element:
    return E(tag, {"x": x, "y": y, "z": z, **extra})


@dataclass
class TimeValue:
    time_s: float
    v_ms: float


@dataclass
class InOutZone:
    """A box-shaped inlet/outlet zone (`XML_GUIDE_INLETOUTLET.pdf`).

    `point`/`size` define the box in the SPH frame (§1.3), unrotated (`direction` along -y);
    `rotate_deg` (about a vertical axis through `rotate_center_xy`, default the box's own centre)
    turns the whole zone -- box and `direction` together, as in DualSPHysics's own inlet examples
    (`examples/inletoutlet/05_ShapesInlet3D`) -- to align it with the real inlet's flow direction.
    `velocity_times` gives a time-varying uniform inflow velocity (`imposevelocity mode="1"`);
    `zsurf_m` is the fixed free-surface height imposed at the zone (`imposezsurf mode="0"`).
    """

    point_xyz: tuple[float, float, float]
    size_xyz: tuple[float, float, float]
    direction_xyz: tuple[float, float, float]
    velocity_times: list[TimeValue]
    zsurf_m: float
    layers: int = 4
    refilling: int = 1
    inputtreatment: int = 2
    rotate_deg: float = 0.0
    rotate_center_xy: tuple[float, float] | None = None

    def to_element(self) -> ET.Element:
        px, py, pz = self.point_xyz
        sx, sy, sz = self.size_xyz
        dx, dy, dz = self.direction_xyz
        zone_children = [
            point("point", px, py, pz),
            point("size", sx, sy, sz),
            point("direction", dx, dy, dz),
        ]
        if self.rotate_deg:
            cx, cy = self.rotate_center_xy if self.rotate_center_xy is not None else (px + sx / 2, py + sy / 2)
            zone_children.append(E("rotateaxis", {"angle": self.rotate_deg, "anglesunits": "degrees"}, children=[
                point("point1", cx, cy, 0.0),
                point("point2", cx, cy, 1.0),
            ]))
        box = E("box", children=zone_children)
        velocitytimes = E("velocitytimes", {"comment": "Uniform inlet velocity in time"}, children=[
            E("timevalue", {"time": tv.time_s, "v": tv.v_ms}) for tv in self.velocity_times
        ])
        imposevelocity = E(
            "imposevelocity",
            {"mode": 1, "comment": "Imposed velocity 0:fixed value, 1:variable value, 2:Extrapolated value (default=0)"},
            children=[velocitytimes],
        )
        imposezsurf = E(
            "imposezsurf",
            {"mode": 0, "comment": "Inlet Z-surface 0:Imposed fixed value, 1:Imposed variable value, 2:Calculated from fluid domain (default=0)"},
            children=[E("zsurf", {"value": self.zsurf_m, "comment": "Characteristic inlet Z-surface", "units_comment": "m"})],
        )
        return E("inoutzone", children=[
            E("refilling", {"value": self.refilling, "comment": "Refilling mode. 0:Simple full, 1:Simple below zsurf, 2:Advanced for reverse flows (very slow) (default=1)"}),
            E("inputtreatment", {"value": self.inputtreatment, "comment": "Treatment of fluid entering the zone. 0:No changes, 1:Convert fluid, 2:Remove fluid"}),
            E("layers", {"value": self.layers, "comment": "Number of inlet/outlet particle layers"}),
            E("zone3d", {"comment": "Input zone for 3-D simulations"}, children=[box]),
            imposevelocity,
            imposezsurf,
        ])


@dataclass
class SwlGauge:
    name: str
    point0_xyz: tuple[float, float, float]
    point2_xyz: tuple[float, float, float]
    coefdp: float = 0.5
    compute_dt_s: float | None = None
    output_dt_s: float | None = None

    def to_element(self) -> ET.Element:
        x0, y0, z0 = self.point0_xyz
        x2, y2, z2 = self.point2_xyz
        children = []
        if self.compute_dt_s is not None:
            children.append(E("computedt", {"value": self.compute_dt_s, "comment": "Time between measurements. 0:all steps (default=default.computedt)", "units_comment": "s"}))
        if self.output_dt_s is not None:
            children.append(E("outputdt", {"value": self.output_dt_s, "comment": "Time between output measurements. 0:all steps (default=default.outputdt)", "units_comment": "s"}))
        children.append(E("pointdp", {"coefdp": self.coefdp, "comment": "Distance between check points (value=coefdp*Dp)"}))
        children.append(point("point0", x0, y0, z0, comment="Initial point", units_comment="m"))
        children.append(point("point2", x2, y2, z2, comment="Final point", units_comment="m"))
        return E("swl", {"name": self.name}, children=children)


@dataclass
class VelocityGauge:
    name: str
    point_xyz: tuple[float, float, float]

    def to_element(self) -> ET.Element:
        # Tag is `<velocity>`, not `<vel>` -- confirmed against DualSPHysics 5.4's own
        # `examples/others/GaugeSystem/GVel_Dam2d.xml` (docs/decisions.md, today's session);
        # the shorter tag silently produced no `GaugesVel_*.csv` gauge output.
        x, y, z = self.point_xyz
        return E("velocity", {"name": self.name}, children=[point("point", x, y, z, units_comment="m")])


@dataclass
class CaseSpec:
    """The subset of a GenCase `_Def.xml` this project generates.

    `constants`: ordered list of `(tag, attrib)` for `<constantsdef>` children, values from
    `docs/handoff_contract.md` / DualSPHysics defaults, cited per-field by the caller.
    `mk_boundcount` / `mk_fluidcount`: `<mkconfig>` — max distinct MK values used.
    `dp_m`, `pointref/min/max`: `<geometry><definition>` box (SPH frame, metres).
    `draw_commands`: ordered `<commands><mainlist>` children (fluid fill box, STL boundary draws).
    `inout_zones`: `<execution><special><inout>` zones (inlets).
    `swl_gauges`, `vel_gauges`: `<execution><special><gauges>` probes.
    `parameters`: ordered `(key, value, comment)` for `<execution><parameters>`.
    `simdomain_posmin/posmax`: `<simulationdomain>` margins, `"default"` or a numeric string.
    """

    dp_m: float
    pointref_xyz: tuple[float, float, float]
    pointmin_xyz: tuple[float, float, float]
    pointmax_xyz: tuple[float, float, float]
    constants: list[tuple[str, dict]]
    mk_boundcount: int
    mk_fluidcount: int
    draw_commands: list[ET.Element]
    parameters: list[tuple[str, object, str]]
    inout_zones: list[InOutZone] = field(default_factory=list)
    gauges_default: ET.Element | None = None
    swl_gauges: list[SwlGauge] = field(default_factory=list)
    vel_gauges: list[VelocityGauge] = field(default_factory=list)
    inout_determlimit: float = 1e3
    simdomain_posmin: tuple[str, str, str] = ("default", "default", "default")
    simdomain_posmax: tuple[str, str, str] = ("default", "default", "default")

    def to_tree(self) -> ET.ElementTree:
        constantsdef = E("constantsdef", children=[E(tag, attrib) for tag, attrib in self.constants])
        mkconfig = E("mkconfig", {"boundcount": self.mk_boundcount, "fluidcount": self.mk_fluidcount})
        rx, ry, rz = self.pointref_xyz
        n1x, n1y, n1z = self.pointmin_xyz
        n2x, n2y, n2z = self.pointmax_xyz
        definition = E("definition", {"dp": self.dp_m, "units_comment": "metres (m)"}, children=[
            point("pointref", rx, ry, rz),
            point("pointmin", n1x, n1y, n1z),
            point("pointmax", n2x, n2y, n2z),
        ])
        geometry = E("geometry", children=[definition, E("commands", children=[
            E("mainlist", children=list(self.draw_commands)),
        ])])
        casedef = E("casedef", children=[constantsdef, mkconfig, geometry])

        special_children = []
        if self.inout_zones:
            special_children.append(E("inout", children=[
                E("memoryresize", {"size0": 2, "size": 4}),
                E("determlimit", {"value": self.inout_determlimit}),
                *[z.to_element() for z in self.inout_zones],
            ]))
        if self.gauges_default is not None or self.swl_gauges or self.vel_gauges:
            gauges_children = []
            if self.gauges_default is not None:
                gauges_children.append(self.gauges_default)
            gauges_children.extend(g.to_element() for g in self.swl_gauges)
            gauges_children.extend(g.to_element() for g in self.vel_gauges)
            special_children.append(E("gauges", children=gauges_children))
        execution_children = []
        if special_children:
            execution_children.append(E("special", children=special_children))

        param_elements = [E("parameter", {"key": key, "value": value, "comment": comment}) for key, value, comment in self.parameters]
        p0x, p0y, p0z = self.simdomain_posmin
        p2x, p2y, p2z = self.simdomain_posmax
        param_elements.append(E("simulationdomain", children=[
            E("posmin", {"x": p0x, "y": p0y, "z": p0z}),
            E("posmax", {"x": p2x, "y": p2y, "z": p2z}),
        ]))
        execution_children.append(E("parameters", children=param_elements))
        execution = E("execution", children=execution_children)

        return ET.ElementTree(E("case", children=[casedef, execution]))


def write_case_xml(spec: CaseSpec, path: str | Path) -> Path:
    path = Path(path)
    tree = spec.to_tree()
    ET.indent(tree, space="    ")
    tree.write(path, encoding="UTF-8", xml_declaration=True)
    return path


def canonicalize(tree: ET.ElementTree | ET.Element) -> ET.Element:
    """Strip documentation attributes and GenCase-disabled (`_`-prefixed) elements, so two trees
    that differ only in comments/formatting compare equal."""
    root = tree.getroot() if isinstance(tree, ET.ElementTree) else tree

    def clean(el: ET.Element) -> ET.Element:
        attrib = {k: _norm_value(v) for k, v in el.attrib.items() if k not in _DOC_ATTRS}
        out = ET.Element(el.tag, attrib)
        out.text = (el.text or "").strip() or None
        for child in el:
            if child.tag.startswith("_"):
                continue
            out.append(clean(child))
        return out

    return clean(root)


def _norm_value(v: str) -> str:
    try:
        return repr(float(v))
    except ValueError:
        return v


def diff_trees(a: ET.Element, b: ET.Element, path: str = "case") -> list[str]:
    """Report the paths (`tag@attr` or `tag`) where canonicalized trees `a` and `b` differ."""
    diffs: list[str] = []
    if a.tag != b.tag:
        return [f"{path}: tag {a.tag!r} != {b.tag!r}"]
    if a.text != b.text:
        diffs.append(f"{path}#text: {a.text!r} != {b.text!r}")
    for key in sorted(set(a.attrib) | set(b.attrib)):
        av, bv = a.attrib.get(key), b.attrib.get(key)
        if av != bv:
            diffs.append(f"{path}@{key}: {av!r} != {bv!r}")
    a_children, b_children = list(a), list(b)
    if len(a_children) != len(b_children):
        diffs.append(f"{path}: {len(a_children)} children != {len(b_children)} children")
    for i, (ac, bc) in enumerate(zip(a_children, b_children)):
        diffs.extend(diff_trees(ac, bc, f"{path}/{ac.tag}[{i}]"))
    return diffs
