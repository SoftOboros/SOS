"""SCXML-LINT-006 — ``<onentry>`` / ``<onexit>`` inline-script size cap.

Per SOS-01 §6.3: inline ``<script>`` content directly inside an
``<onentry>`` or ``<onexit>`` element MUST be <= 5 non-blank non-comment
lines. Longer logic MUST be extracted to a named helper.

Per SOS-01 §10.2 the ``boot/onentry`` block at HEAD violates this rule
(~17 non-blank lines); the §10 grace period downgrades severity to
``warning`` at SOS-01 ratification, with a planned upgrade to ``error``
in a §15 entry once the ``boot_init()`` extraction lands.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from ._common import (
    SEVERITY_WARNING,
    Finding,
    cdata_lines,
    iter_elements,
    localname,
    nonblank_noncomment_count,
)

RULE_ID = "SCXML-LINT-006"
LINE_CAP = 5


def check(tree, scxml_path: Path) -> List[Finding]:
    """Walk ``<onentry>`` / ``<onexit>`` script bodies; flag over-cap blocks."""
    findings: List[Finding] = []
    root = tree.getroot()

    for hook in root.iter():
        if not isinstance(getattr(hook, "tag", None), str):
            continue
        name = localname(hook.tag)
        if name not in ("onentry", "onexit"):
            continue
        for script in iter_elements(hook, "script"):
            loc = nonblank_noncomment_count(cdata_lines(script))
            if loc > LINE_CAP:
                findings.append(Finding(RULE_ID, SEVERITY_WARNING,
                    f"<{name}> inline <script> has {loc} non-blank non-comment "
                    f"lines; cap is {LINE_CAP}. Extract a named helper.",
                    str(scxml_path), script.sourceline or 1))

    return findings
