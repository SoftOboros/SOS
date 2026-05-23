"""SCXML-LINT-003 — exactly one top-level ``<datamodel>`` declaration.

Per SOS-01 §6.2: the chart MUST contain exactly one ``<datamodel>`` block,
declared as a direct child of the root ``<scxml>`` element. Nested
``<datamodel>`` declarations inside ``<state>`` are forbidden — the
SOS-02 hand-compilation port does not support per-state scoping.

Severity: ``error``.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from ._common import SEVERITY_ERROR, Finding, iter_elements, localname

RULE_ID = "SCXML-LINT-003"


def check(tree, scxml_path: Path) -> List[Finding]:
    """Count ``<datamodel>`` elements; flag absent / extra / nested."""
    findings: List[Finding] = []
    root = tree.getroot()

    top_level = [
        c for c in root
        if isinstance(getattr(c, "tag", None), str)
        and localname(c.tag) == "datamodel"
    ]
    all_dms = list(iter_elements(root, "datamodel"))
    nested = [dm for dm in all_dms if dm not in top_level]

    if len(top_level) == 0:
        findings.append(Finding(RULE_ID, SEVERITY_ERROR,
            "chart contains no top-level <datamodel> block",
            str(scxml_path), root.sourceline or 1))
    elif len(top_level) > 1:
        for dm in top_level[1:]:
            findings.append(Finding(RULE_ID, SEVERITY_ERROR,
                f"chart declares {len(top_level)} top-level <datamodel> blocks; exactly one is required",
                str(scxml_path), dm.sourceline or 1))

    for dm in nested:
        findings.append(Finding(RULE_ID, SEVERITY_ERROR,
            "nested <datamodel> elements are forbidden; promote to the top-level block",
            str(scxml_path), dm.sourceline or 1))

    return findings
