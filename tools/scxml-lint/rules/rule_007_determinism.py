"""SCXML-LINT-007 — no non-deterministic ECMAScript primitives.

Per SOS-01 §6.4: ``<script>`` blocks MUST NOT invoke ``Math.random``,
``Date.now``, ``new Date(...)``, ``console.*``, ``eval``, or the
``Function`` constructor. This rule overlaps SCXML-LINT-009 by design;
§6.4 calls these primitives out separately because they are the
load-bearing determinism guarantees that make INV-S2 (macrostep
atomicity) realisable in the hand-compilation port (INV-S-LINT-7).

Severity: ``error``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Pattern, Tuple

from ._common import SEVERITY_ERROR, Finding, iter_elements

RULE_ID = "SCXML-LINT-007"

_FORBIDDEN: Tuple[Tuple[str, "Pattern[str]"], ...] = (
    ("Math.random", re.compile(r"\bMath\.random\b")),
    ("Date.now", re.compile(r"\bDate\.now\b")),
    ("Date constructor", re.compile(r"\bnew\s+Date\b|\bDate\s*\(")),
    ("console.*", re.compile(r"\bconsole\.[A-Za-z_]+")),
    ("eval", re.compile(r"\beval\s*\(")),
    ("Function constructor", re.compile(r"\bnew\s+Function\b")),
)


def _strip_comments(body: str) -> str:
    """Remove ``//`` and ``/* */`` comments while preserving line numbers."""
    body = re.sub(r"/\*.*?\*/", lambda m: " " * len(m.group(0)), body, flags=re.DOTALL)
    out = []
    for line in body.splitlines(keepends=True):
        idx = line.find("//")
        if idx >= 0:
            out.append(line[:idx] + ("\n" if line.endswith("\n") else ""))
        else:
            out.append(line)
    return "".join(out)


def check(tree, scxml_path: Path) -> List[Finding]:
    """Sweep every ``<script>`` body for non-deterministic primitives."""
    findings: List[Finding] = []
    for script in iter_elements(tree.getroot(), "script"):
        body = _strip_comments(script.text or "")
        base_line = script.sourceline or 1
        for label, pat in _FORBIDDEN:
            m = pat.search(body)
            if m:
                offset = body.count("\n", 0, m.start())
                findings.append(Finding(RULE_ID, SEVERITY_ERROR,
                    f"non-deterministic primitive '{label}' inside <script>; "
                    "violates SOS-01 §6.4 / INV-S-LINT-7.",
                    str(scxml_path), base_line + offset))
    return findings
