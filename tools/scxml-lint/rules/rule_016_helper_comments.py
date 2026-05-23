"""SCXML-LINT-016 — helper-block functions are documented.

Per SOS-01 §6.6: inside the top-level ``<script>`` block (the helper
extraction target — first ``<script>`` element directly under
``<scxml>``), every ``function name(...)`` declaration SHOULD be
preceded by at least one ``// ...`` comment describing its purpose.

Per SOS-01 §10.1 the chart at HEAD complies (every helper carries a
leading comment); the rule promotes the current practice to enforcement.

Severity: ``warning``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List

from ._common import SCXML_NS_PREFIX, SEVERITY_WARNING, Finding

RULE_ID = "SCXML-LINT-016"

_FUNCTION_DECL = re.compile(r"^\s*function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")


def _find_top_level_helper_block(root):
    """Return the first ``<script>`` directly under ``<scxml>`` or None."""
    for child in root:
        if getattr(child, "tag", None) == f"{SCXML_NS_PREFIX}script":
            return child
    return None


def check(tree, scxml_path: Path) -> List[Finding]:
    """Verify each helper-block ``function`` is preceded by a ``//`` comment."""
    findings: List[Finding] = []
    helper_block = _find_top_level_helper_block(tree.getroot())
    if helper_block is None:
        return findings

    body = helper_block.text or ""
    base_line = helper_block.sourceline or 1
    lines = body.splitlines()

    for idx, line in enumerate(lines):
        m = _FUNCTION_DECL.match(line)
        if not m:
            continue
        name = m.group(1)
        # Walk backward past blank lines; require a // comment immediately
        # above (single- or multi-line).
        j = idx - 1
        while j >= 0 and lines[j].strip() == "":
            j -= 1
        if j < 0 or not lines[j].lstrip().startswith("//"):
            # Report at the script base line + the function's offset.
            findings.append(Finding(RULE_ID, SEVERITY_WARNING,
                f"helper function '{name}' in the top-level <script> block "
                "lacks a leading '// ...' description comment.",
                str(scxml_path), base_line + idx))
    return findings
