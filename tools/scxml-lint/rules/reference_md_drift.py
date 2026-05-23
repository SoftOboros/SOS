"""SCXML-LINT-017 + SCXML-LINT-018 — REFERENCE.md cross-doc drift checks.

Per SOS-01 §6.7 (PCDN-SOS-01-005 resolved warning 2026-05-19):

* SCXML-LINT-017 — ``docs/REFERENCE.md`` syscall tables SHOULD list every
  event in ``ExternalEventName`` (§5.3) and SHOULD NOT list any event not
  in the enum.
* SCXML-LINT-018 — the "Task states" table in ``docs/REFERENCE.md``
  SHOULD list every ``TaskState`` value from SOS-00 §5.1 with matching
  numeric codes.

Both rules are ``warning`` severity. Detection scans REFERENCE.md text
for known token shapes ("task.X" / "sem.X" / "queue.X" / "sys.tick" /
"crit.X" / "sched.X" for -017; "ST_XXX" for -018).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from ._common import SEVERITY_WARNING, Finding
from .event_vocabulary import EXTERNAL_EVENT_NAMES

REFERENCE_RULE_ID_EVENTS = "SCXML-LINT-017"
REFERENCE_RULE_ID_STATES = "SCXML-LINT-018"

# §5.1 TaskState mirror — must stay in sync with SOS-00 §5.1.
TASK_STATES = (
    ("ST_DORMANT", 0),
    ("ST_READY", 1),
    ("ST_RUNNING", 2),
    ("ST_DELAY", 3),
    ("ST_BLK_SEM", 4),
    ("ST_BLK_QS", 5),
    ("ST_BLK_QR", 6),
    ("ST_SUSPEND", 7),
)

_EVENT_TOKEN = re.compile(
    r"\b(?:task|sem|queue|sys|crit|sched)\.[a-z_]+(?:_from_isr)?\b"
)
_STATE_TOKEN = re.compile(r"\bST_[A-Z_]+\b")


def check(scxml_path: Path, reference_md_path: Optional[Path]) -> List[Finding]:
    """Scan REFERENCE.md for drift vs the frozen enums.

    ``scxml_path`` is used only to anchor findings (so they appear in the
    GitHub Annotations UI alongside chart-side findings). The actual
    diagnostic text references REFERENCE.md.
    """
    findings: List[Finding] = []
    if reference_md_path is None or not reference_md_path.exists():
        return findings

    text = reference_md_path.read_text(encoding="utf-8")
    found_events = set(_EVENT_TOKEN.findall(text))

    # SCXML-LINT-017: extra events (in REFERENCE.md but not in enum)
    for evt in sorted(found_events - EXTERNAL_EVENT_NAMES):
        # Filter out tokens that are clearly internal (kernel.boot.done /
        # sched.run) -- the _EVENT_TOKEN pattern doesn't match them, but
        # be defensive.
        if evt in {"kernel.boot.done", "sched.run"}:
            continue
        findings.append(
            Finding(
                rule_id=REFERENCE_RULE_ID_EVENTS,
                severity=SEVERITY_WARNING,
                message=(
                    f"REFERENCE.md references event '{evt}' that is not in "
                    "SOS-01 §5.3 ExternalEventName. Either amend §5.3 or "
                    "remove the row from REFERENCE.md."
                ),
                path=str(reference_md_path),
                line=_find_line(text, evt),
            )
        )

    # SCXML-LINT-017: missing events (in enum but absent from REFERENCE.md)
    for evt in sorted(EXTERNAL_EVENT_NAMES - found_events):
        findings.append(
            Finding(
                rule_id=REFERENCE_RULE_ID_EVENTS,
                severity=SEVERITY_WARNING,
                message=(
                    f"REFERENCE.md does not document event '{evt}' from "
                    "SOS-01 §5.3 ExternalEventName."
                ),
                path=str(reference_md_path),
                line=1,
            )
        )

    # SCXML-LINT-018: TaskState mirror
    found_states = set(_STATE_TOKEN.findall(text))
    enum_states = {name for name, _ in TASK_STATES}
    for st in sorted(found_states - enum_states):
        findings.append(
            Finding(
                rule_id=REFERENCE_RULE_ID_STATES,
                severity=SEVERITY_WARNING,
                message=(
                    f"REFERENCE.md references task state '{st}' that is not "
                    "in SOS-00 §5.1 TaskState."
                ),
                path=str(reference_md_path),
                line=_find_line(text, st),
            )
        )
    for st in sorted(enum_states - found_states):
        findings.append(
            Finding(
                rule_id=REFERENCE_RULE_ID_STATES,
                severity=SEVERITY_WARNING,
                message=(
                    f"REFERENCE.md does not document task state '{st}' from "
                    "SOS-00 §5.1 TaskState."
                ),
                path=str(reference_md_path),
                line=1,
            )
        )
    return findings


def _find_line(text: str, token: str) -> int:
    """Return the 1-based line number of the first occurrence of ``token``."""
    idx = text.find(token)
    if idx < 0:
        return 1
    return text.count("\n", 0, idx) + 1
