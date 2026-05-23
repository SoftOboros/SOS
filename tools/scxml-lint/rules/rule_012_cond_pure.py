"""SCXML-LINT-012 — transition ``cond`` is side-effect-free.

Per SOS-01 §6.5: a transition's ``cond`` attribute MUST evaluate using
only top-level datamodel identifiers and the ``_event`` identifier. It
MUST NOT call helper functions, MUST NOT mutate datamodel state, MUST
NOT have side effects.

Per W3C SCXML 1.0 §3.13 ``cond`` is part of transition selection;
side-effecting evaluation is unspecified-order.

Severity: ``error``.

Detection is conservative: a ``cond`` expression is rejected if it
contains assignment operators, increment/decrement, or a function-call
syntax that is not one of the implicit ``_event``-typed reads.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List

from ._common import SEVERITY_ERROR, Finding, iter_elements

RULE_ID = "SCXML-LINT-012"

# Reject any assignment operator (=, +=, -=, etc.) unless it's a
# comparator (==, !=, <=, >=, ===, !==).
_ASSIGN_RE = re.compile(r"(?<![=!<>])=(?!=)|[+\-*/%&|^]=")
_INC_DEC_RE = re.compile(r"\+\+|--")
# A function-call shape: identifier followed by ``(``. We allow the
# implicit ``_event``-namespace reads which are property access, not
# calls. We explicitly forbid any helper-function invocation.
_CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")


def check(tree, scxml_path: Path) -> List[Finding]:
    """Walk every ``<transition cond=...>`` and check the expression."""
    findings: List[Finding] = []
    for tr in iter_elements(tree.getroot(), "transition"):
        cond = tr.get("cond")
        if not cond:
            continue
        line = tr.sourceline or 1

        if _ASSIGN_RE.search(cond):
            findings.append(Finding(RULE_ID, SEVERITY_ERROR,
                f"<transition cond='{cond}'> contains an assignment "
                "operator; cond expressions MUST be side-effect-free.",
                str(scxml_path), line))
        if _INC_DEC_RE.search(cond):
            findings.append(Finding(RULE_ID, SEVERITY_ERROR,
                f"<transition cond='{cond}'> contains '++' or '--'; cond "
                "expressions MUST be side-effect-free.",
                str(scxml_path), line))
        for m in _CALL_RE.finditer(cond):
            callee = m.group(1)
            findings.append(Finding(RULE_ID, SEVERITY_ERROR,
                f"<transition cond='{cond}'> invokes function '{callee}(...)'; "
                "cond expressions MUST be pure datamodel reads. Move the call "
                "into the transition body.",
                str(scxml_path), line))

    return findings
