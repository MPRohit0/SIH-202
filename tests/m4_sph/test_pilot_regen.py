"""Regenerate the pilot calibration case and diff it against the original GenCase file
(DualSPHysics 5.4.3 `examples/main/01_DamBreak/CaseDambreakVal2D_Def.xml`), to validate
`case_xml`'s writer before it is trusted to build real near-field cases."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from backend.m4_sph.case_xml import canonicalize, diff_trees
from backend.m4_sph.generator import pilot_case_spec

FIXTURE = Path(__file__).parent.parent / "fixtures" / "m4_sph" / "CaseDambreakVal2D_Def.xml"


def test_pilot_case_matches_reference_gencase_xml():
    ours = canonicalize(pilot_case_spec().to_tree())
    reference = canonicalize(ET.parse(FIXTURE))
    diffs = diff_trees(ours, reference)
    assert diffs == []


def test_diff_trees_reports_a_changed_dp():
    spec = pilot_case_spec()
    spec.dp_m = 0.02
    ours = canonicalize(spec.to_tree())
    reference = canonicalize(ET.parse(FIXTURE))
    diffs = diff_trees(ours, reference)
    assert any("definition" in d and "@dp" in d for d in diffs)
