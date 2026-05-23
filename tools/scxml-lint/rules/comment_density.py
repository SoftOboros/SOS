"""SCXML-LINT-010 + SCXML-LINT-015 — comment-density rules.

Per SOS-01 §6.5 / §6.6:

* SCXML-LINT-010 (``error``): every external ``<transition event="..."/>``
  MUST be immediately preceded by a ``<!-- _event.data: { ... } -->``
  comment describing payload shape. Internal-event transitions
  (``kernel.boot.done``, ``sched.run``) are exempt.
* SCXML-LINT-015 (``warning``): every non-trivial ``<state id="..."/>``
  SHOULD be preceded by an XML intent comment.

Both rules anchor on the preceding XML comment in document order.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from ._common import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    Finding,
    iter_elements,
    localname,
    preceding_comment,
)
from .event_vocabulary import EXTERNAL_EVENT_NAMES

TRANSITION_RULE_ID = "SCXML-LINT-010"
STATE_RULE_ID = "SCXML-LINT-015"


def check(tree, scxml_path: Path) -> List[Finding]:
    """Walk transitions + states; report missing leading comments."""
    findings: List[Finding] = []
    root = tree.getroot()

    for tr in iter_elements(root, "transition"):
        event = tr.get("event")
        if not event or event not in EXTERNAL_EVENT_NAMES:
            continue
        comment = preceding_comment(tr)
        if comment is None or "_event.data" not in comment:
            findings.append(
                Finding(
                    rule_id=TRANSITION_RULE_ID,
                    severity=SEVERITY_ERROR,
                    message=(
                        f"external transition event='{event}' lacks the "
                        "required '<!-- _event.data: ... -->' header comment."
                    ),
                    path=str(scxml_path),
                    line=tr.sourceline or 1,
                )
            )

    for st in iter_elements(root, "state"):
        # "Non-trivial" — has children beyond a single self-closing
        # ``<transition/>`` and is not the implicit-final-only case.
        children = [c for c in st if isinstance(getattr(c, "tag", None), str)]
        if len(children) == 0:
            continue
        if len(children) == 1 and localname(children[0].tag) == "transition":
            continue
        if preceding_comment(st) is None:
            findings.append(
                Finding(
                    rule_id=STATE_RULE_ID,
                    severity=SEVERITY_WARNING,
                    message=(
                        f"<state id='{st.get('id') or '?'}'> lacks a leading "
                        "XML intent comment."
                    ),
                    path=str(scxml_path),
                    line=st.sourceline or 1,
                )
            )

    return findings
