"""SCXML-LINT-013 and SCXML-LINT-014 — frozen event / state vocabulary.

Per SOS-01 §5.3 + §5.4: every ``<transition event="X"/>`` whose name
carries a ``.`` separator MUST name a value from ``ExternalEventName``
(§5.3) and every ``<transition target="X"/>`` MUST name a value from
``StateId`` (§5.4). Internal events (``kernel.boot.done``, ``sched.run``)
are exempt per §5.6.

Both rules are ``error`` severity per SOS-01 §6.5.

Note: SOS-01 §6.5 lists these as rules -013 (event names) and -014
(target ids). The task brief grouped them together with the "comment per
event" / "state-id documentation" pair (-010, -011) — implementing the
contract-freezing rules here is the load-bearing piece.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from ._common import SEVERITY_ERROR, Finding, iter_elements

# §5.3 ``ExternalEventName`` — 18 frozen values at SOS-01 ratification.
EXTERNAL_EVENT_NAMES = frozenset({
    "task.create",
    "task.delay",
    "task.yield",
    "task.suspend",
    "task.resume",
    "sem.create",
    "sem.take",
    "sem.give",
    "sem.give_from_isr",
    "queue.create",
    "queue.send",
    "queue.receive",
    "queue.send_from_isr",
    "sys.tick",
    "crit.enter",
    "crit.exit",
    "sched.suspend",
    "sched.resume",
})

# §5.6 internal events — exempt from the external-vocabulary check.
INTERNAL_EVENT_NAMES = frozenset({"kernel.boot.done", "sched.run"})

# §5.4 ``StateId`` — 10 frozen values at SOS-01 ratification.
STATE_IDS = frozenset({
    "boot",
    "running",
    "scheduler",
    "sched_idle",
    "tick_service",
    "tick_idle",
    "syscalls",
    "sys_idle",
    "protection",
    "prot_idle",
})

EVENT_RULE_ID = "SCXML-LINT-013"
TARGET_RULE_ID = "SCXML-LINT-014"


def check(tree, scxml_path: Path) -> List[Finding]:
    """Walk every ``<transition>`` and validate its event / target attrs."""
    findings: List[Finding] = []
    for tr in iter_elements(tree.getroot(), "transition"):
        event = tr.get("event")
        if event and "." in event:
            if event not in EXTERNAL_EVENT_NAMES and event not in INTERNAL_EVENT_NAMES:
                findings.append(
                    Finding(
                        rule_id=EVENT_RULE_ID,
                        severity=SEVERITY_ERROR,
                        message=(
                            f"transition event='{event}' is not in §5.3 "
                            "ExternalEventName (and is not the §5.6 internal "
                            "exempt set). Amend SOS-01 §5.3 first."
                        ),
                        path=str(scxml_path),
                        line=tr.sourceline or 1,
                    )
                )
        target = tr.get("target")
        if target:
            for tid in target.split():
                if tid not in STATE_IDS:
                    findings.append(
                        Finding(
                            rule_id=TARGET_RULE_ID,
                            severity=SEVERITY_ERROR,
                            message=(
                                f"transition target='{tid}' is not in §5.4 "
                                "StateId. Amend SOS-01 §5.4 first."
                            ),
                            path=str(scxml_path),
                            line=tr.sourceline or 1,
                        )
                    )
    return findings
