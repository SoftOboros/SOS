"""SCXML-LINT-009 — ECMAScript permitted-feature subset.

Per SOS-01 §5.1: ``<script>`` blocks MUST use only constructs from the
``Permitted`` rows of ``ECMAScriptFeature``. This module implements the
inverse — a textual sweep for the forbidden-list keywords. Detection is
deliberately conservative: simple word-boundary token matches on the
script body. Hand-compilation tooling (SOS-02) will do a real parse;
SOS-01's lint just catches obvious drift.

Severity: ``error``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Pattern, Tuple

from ._common import SEVERITY_ERROR, Finding, iter_elements

RULE_ID = "SCXML-LINT-009"

# Each entry: (human-readable token, compiled pattern). Patterns use
# word-boundary anchors where appropriate and small literal anchors
# elsewhere to avoid string-content false positives (the chart has no
# string literals, per §5.1 "Template literals" + no regex).
_FORBIDDEN: Tuple[Tuple[str, "Pattern[str]"], ...] = (
    ("async", re.compile(r"\basync\b")),
    ("await", re.compile(r"\bawait\b")),
    ("eval", re.compile(r"\beval\s*\(")),
    ("Function-constructor", re.compile(r"\bnew\s+Function\b")),
    ("Promise", re.compile(r"\bPromise\b")),
    ("function*-generator", re.compile(r"\bfunction\s*\*")),
    ("yield", re.compile(r"\byield\b")),
    ("class", re.compile(r"\bclass\b")),
    ("let", re.compile(r"\blet\b")),
    ("const", re.compile(r"\bconst\b")),
    ("for-in/for-of", re.compile(r"\bfor\s*\(\s*(?:var\s+)?\w+\s+(?:in|of)\b")),
    ("switch", re.compile(r"\bswitch\b")),
    ("try", re.compile(r"\btry\b")),
    ("catch", re.compile(r"\bcatch\b")),
    ("throw", re.compile(r"\bthrow\b")),
    ("typeof", re.compile(r"\btypeof\b")),
    ("instanceof", re.compile(r"\binstanceof\b")),
    ("Math.random", re.compile(r"\bMath\.random\b")),
    ("Date", re.compile(r"\bDate\s*(?:\.|\()")),
    ("console", re.compile(r"\bconsole\.")),
    ("JSON", re.compile(r"\bJSON\.")),
    ("regex-literal", re.compile(r"(?<![A-Za-z0-9_])/[^/\n]{1,80}/[gimsuy]*[\s;,)]")),
    ("arrow-function", re.compile(r"=>")),
    ("spread/rest", re.compile(r"\.\.\.[A-Za-z_]")),
    ("destructuring-obj", re.compile(r"(?:var|let|const)\s*\{")),
    ("destructuring-arr", re.compile(r"(?:var|let|const)\s*\[")),
    ("template-literal", re.compile(r"`")),
)


def _strip_line_comments(body: str) -> str:
    """Remove ``//`` line comments and ``/* ... */`` block comments.

    Keeps line breaks so line numbers stay accurate for the diagnostic.
    """
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
    """Sweep every ``<script>`` body for forbidden ECMAScript constructs."""
    findings: List[Finding] = []
    for script in iter_elements(tree.getroot(), "script"):
        raw_body = script.text or ""
        body = _strip_line_comments(raw_body)
        base_line = script.sourceline or 1
        for label, pat in _FORBIDDEN:
            m = pat.search(body)
            if m:
                offset = body.count("\n", 0, m.start())
                findings.append(
                    Finding(
                        rule_id=RULE_ID,
                        severity=SEVERITY_ERROR,
                        message=(
                            f"forbidden ECMAScript construct '{label}' at "
                            "matching site; see SOS-01 §5.1 ECMAScriptFeature."
                        ),
                        path=str(scxml_path),
                        line=base_line + offset,
                    )
                )
    return findings
