"""SCXML-LINT-002 — root ``<scxml>`` element attributes.

Per SOS-01 §6.2: the root element MUST be ``<scxml>`` with
``xmlns="http://www.w3.org/2005/07/scxml"``, ``version="1.0"``,
``datamodel="ecmascript"``, and ``initial`` set to a value listed in
§5.4 ``StateId``. No other attributes are permitted on the root.

Severity: ``error``.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from ._common import SCXML_NS, SEVERITY_ERROR, Finding, localname
from .event_vocabulary import STATE_IDS

RULE_ID = "SCXML-LINT-002"

# The canonical attribute set on the root element. Any attribute not in
# this set (excluding the xmlns declaration itself) is a violation.
_REQUIRED_ATTRS = {
    "version": "1.0",
    "datamodel": "ecmascript",
}
_ALLOWED_ATTRS = frozenset({"version", "datamodel", "initial", "xmlns"})


def check(tree, scxml_path: Path) -> List[Finding]:
    """Verify the root element identity, namespace, and attribute set."""
    findings: List[Finding] = []
    root = tree.getroot()
    line = root.sourceline or 1

    if localname(root.tag) != "scxml":
        findings.append(Finding(RULE_ID, SEVERITY_ERROR,
            f"root element must be <scxml>, got <{localname(root.tag)}>",
            str(scxml_path), line))
        return findings

    if not root.tag.startswith("{") or root.tag.split("}", 1)[0][1:] != SCXML_NS:
        findings.append(Finding(RULE_ID, SEVERITY_ERROR,
            f"root <scxml> must declare xmlns='{SCXML_NS}'",
            str(scxml_path), line))

    for attr, expected in _REQUIRED_ATTRS.items():
        actual = root.get(attr)
        if actual is None:
            findings.append(Finding(RULE_ID, SEVERITY_ERROR,
                f"root <scxml> missing required attribute '{attr}'='{expected}'",
                str(scxml_path), line))
        elif actual != expected:
            findings.append(Finding(RULE_ID, SEVERITY_ERROR,
                f"root <scxml> {attr}='{actual}', expected '{expected}'",
                str(scxml_path), line))

    initial = root.get("initial")
    if initial is None:
        findings.append(Finding(RULE_ID, SEVERITY_ERROR,
            "root <scxml> missing required 'initial' attribute",
            str(scxml_path), line))
    elif initial not in STATE_IDS:
        findings.append(Finding(RULE_ID, SEVERITY_ERROR,
            f"root <scxml> initial='{initial}' is not in §5.4 StateId",
            str(scxml_path), line))

    for attr in root.attrib:
        if localname(attr) not in _ALLOWED_ATTRS:
            findings.append(Finding(RULE_ID, SEVERITY_ERROR,
                f"root <scxml> carries unexpected attribute '{attr}'; "
                "only xmlns/version/datamodel/initial are permitted",
                str(scxml_path), line))

    return findings
