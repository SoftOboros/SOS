"""SCXML-LINT-004 — no nested ``<parallel>`` elements.

Per SOS-01 §6.2: the chart MAY contain at most one ``<parallel>``
element. A ``<parallel>`` declared inside another ``<parallel>`` is
forbidden — nested parallels combinatorially explode the configuration
set the simulator and ports must reason about.

The chart at HEAD has exactly one ``<parallel id="running">`` directly
under the root; this rule pass-cleans at HEAD per §10.1.

Severity: ``error``.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from ._common import SEVERITY_ERROR, Finding, iter_elements, localname

RULE_ID = "SCXML-LINT-004"


def check(tree, scxml_path: Path) -> List[Finding]:
    """Walk every ``<parallel>``; flag any that has a ``<parallel>`` ancestor."""
    findings: List[Finding] = []
    root = tree.getroot()

    for par in iter_elements(root, "parallel"):
        anc = par.getparent()
        while anc is not None:
            if localname(getattr(anc, "tag", "") or "") == "parallel":
                findings.append(Finding(RULE_ID, SEVERITY_ERROR,
                    f"<parallel id='{par.get('id') or '?'}'> nested inside "
                    f"<parallel id='{anc.get('id') or '?'}'>; flatten to siblings",
                    str(scxml_path), par.sourceline or 1))
                break
            anc = anc.getparent()

    return findings
