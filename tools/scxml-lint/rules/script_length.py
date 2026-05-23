"""SCXML-LINT-005 — ``<script>`` block length cap (40 LOC).

Per SOS-01 §6.3 + PCDN-SOS-01-003 (resolved 40 LOC 2026-05-19): every
``<script>`` block SHOULD be <= 40 non-blank non-comment lines. The
top-level helper block IS the helper-extraction target and is
exempt per the §10 / INV-S-LINT-2 recursive exception — implemented
here by skipping the *first* top-level ``<script>`` element that is a
direct child of the root ``<scxml>``.

Severity: ``warning`` at SOS-01 ratification.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from ._common import (
    SCXML_NS_PREFIX,
    SEVERITY_WARNING,
    Finding,
    cdata_lines,
    iter_elements,
    nonblank_noncomment_count,
)

RULE_ID = "SCXML-LINT-005"
LINE_CAP = 40


def check(tree, scxml_path: Path) -> List[Finding]:
    """Walk every ``<script>`` element and flag oversize blocks.

    The first top-level ``<script>`` directly under ``<scxml>`` is treated
    as the helper-extraction target and is exempt from the per-block cap.
    """
    findings: List[Finding] = []
    root = tree.getroot()

    helper_block = None
    for child in root:
        if getattr(child, "tag", None) == f"{SCXML_NS_PREFIX}script":
            helper_block = child
            break

    for script in iter_elements(root, "script"):
        if script is helper_block:
            continue
        loc = nonblank_noncomment_count(cdata_lines(script))
        if loc > LINE_CAP:
            findings.append(
                Finding(
                    rule_id=RULE_ID,
                    severity=SEVERITY_WARNING,
                    message=(
                        f"<script> block has {loc} non-blank non-comment lines; "
                        f"cap is {LINE_CAP}. Extract a named helper into the "
                        "top-level helper script block."
                    ),
                    path=str(scxml_path),
                    line=script.sourceline or 1,
                )
            )
    return findings
