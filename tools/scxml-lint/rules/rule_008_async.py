"""SCXML-LINT-008 — no ``async`` / ``await`` / ``Promise`` / generators.

Per SOS-01 §6.4: ``<script>`` blocks MUST NOT use ``async``, ``await``,
``Promise``, ``function*``, or ``yield``. SCXML 1.0 macrostep semantics
(§3.13) require run-to-completion; async constructs introduce
continuation points inside what is supposed to be an atomic microstep,
violating [SOS-00 §9] INV-S2.

Severity: ``error``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Pattern, Tuple

from ._common import SEVERITY_ERROR, Finding, iter_elements

RULE_ID = "SCXML-LINT-008"

_FORBIDDEN: Tuple[Tuple[str, "Pattern[str]"], ...] = (
    ("async", re.compile(r"\basync\b")),
    ("await", re.compile(r"\bawait\b")),
    ("Promise", re.compile(r"\bPromise\b")),
    ("generator (function*)", re.compile(r"\bfunction\s*\*")),
    ("yield", re.compile(r"\byield\b")),
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
    """Sweep every ``<script>`` body for async / promise / generator usage."""
    findings: List[Finding] = []
    for script in iter_elements(tree.getroot(), "script"):
        body = _strip_comments(script.text or "")
        base_line = script.sourceline or 1
        for label, pat in _FORBIDDEN:
            m = pat.search(body)
            if m:
                offset = body.count("\n", 0, m.start())
                findings.append(Finding(RULE_ID, SEVERITY_ERROR,
                    f"async / generator construct '{label}' inside <script>; "
                    "violates run-to-completion (INV-S2).",
                    str(scxml_path), base_line + offset))
    return findings
