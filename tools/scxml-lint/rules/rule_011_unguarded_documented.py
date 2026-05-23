"""SCXML-LINT-011 — unguarded transitions are documented or terminal.

Per SOS-01 §6.5: every ``<transition event="X"/>`` lacking a ``cond``
attribute SHOULD be either (a) trivially terminal (target is a sibling
state with no datamodel mutation in the body) OR (b) preceded by an
explanatory XML comment.

Per SOS-01 §10.2 the chart at HEAD has ~16 unguarded transitions in the
``syscalls`` and ``protection`` regions whose guards live in script
bodies. Severity is ``warning`` at ratification with grace-period to
SOS-03 land, when a comment sweep will upgrade it to ``error``.

Note: the SCXML-LINT-010 ``_event.data: ...`` payload comment satisfies
clause (b) — a transition with that header comment does NOT fire here.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from ._common import (
    SCXML_NS_PREFIX,
    SEVERITY_WARNING,
    Finding,
    iter_elements,
    localname,
    preceding_comment,
)

RULE_ID = "SCXML-LINT-011"


# Keywords that mark a comment as guard-reasoning (rather than a
# ``_event.data:`` payload-shape header per SCXML-LINT-010).
_GUARD_REASON_KEYWORDS = (
    "always",
    "no cond",
    "no guard",
    "unguarded",
    "bounds-check",
    "bounds check",
    "guard inside",
    "always processes",
)


def _explains_unguarded(comment: str) -> bool:
    """Return True if ``comment`` reads as guard-reasoning."""
    low = comment.lower()
    return any(kw in low for kw in _GUARD_REASON_KEYWORDS)


def _has_body_mutation(tr) -> bool:
    """Return True if the transition has any executable content."""
    for child in tr:
        if isinstance(getattr(child, "tag", None), str):
            tag = localname(child.tag)
            if tag in ("script", "assign", "raise", "send", "log", "if"):
                return True
    return False


def check(tree, scxml_path: Path) -> List[Finding]:
    """Walk ``<transition>`` elements; flag undocumented unguarded ones."""
    findings: List[Finding] = []
    root = tree.getroot()

    for tr in iter_elements(root, "transition"):
        event = tr.get("event")
        if not event:
            continue
        if tr.get("cond"):
            continue
        # Trivially terminal: no body mutation. Permitted without comment.
        if not _has_body_mutation(tr):
            continue
        comment = preceding_comment(tr)
        # Per §10.2: a ``_event.data:`` payload header satisfies SCXML-LINT-010
        # but does NOT satisfy this rule — the comment must explain why no
        # ``cond`` is needed. Look for guard-reasoning keywords.
        if comment is not None and _explains_unguarded(comment):
            continue
        findings.append(Finding(RULE_ID, SEVERITY_WARNING,
            f"unguarded transition event='{event}' has body mutation but no "
            "leading XML comment explaining why no <cond> is needed "
            "(e.g. '<!-- always processes; bounds-check inside script -->').",
            str(scxml_path), tr.sourceline or 1))

    return findings
