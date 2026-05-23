"""SCXML-LINT-C-1 — document-order priority warning.

Per ``docs/concepts/SOS-08-C-CONCEPTS.md`` §5.2 (transition mux priority
discipline), §6.3 (Step 3 — guard expression compilation), and §15
2026-05-23 PCDN-SOS-08-C-006 resolution: the SOS chart validator MUST
emit a ``warning``-severity finding when two transitions in the same
source state could simultaneously evaluate true under bounded
reachability, because document-order resolves that overlap and chart
authors who reorder transitions for legibility risk silently inverting
the resulting priority.

This rule lands as a SOS-01 §15 amendment co-landing with the SOS-08-C
implementation; it is purely additive to the §6 rule registry.

Detection scope at v1
---------------------
Proving guard-condition mutual-exclusion in the general case requires
formal-methods support (SMT solver over the chart's bounded
reachability), which is wave-2+ work. At v1 the scaffold flags the
*unambiguous* sub-case:

* A state with two-or-more transitions that all lack a ``cond``
  attribute. Two unguarded transitions on the same source state are
  always simultaneously enabled (modulo their ``event`` matcher), and
  document-order ALWAYS picks the first; the second is dead code unless
  the author is intentionally relying on document-order priority.

A pair counts as overlapping when one of:

* Both transitions are eventless and unguarded (always-fire pair).
* Both share the same ``event`` value (or both omit ``event``) and
  neither carries a ``cond``.

Guarded-transition overlap detection — even the trivial cases of
syntactically identical ``cond`` strings or trivially negated guards —
is deferred to wave-2+ work. The v1 scaffold therefore produces false
NEGATIVES (overlapping guarded transitions are not flagged) but no
known false positives within the unguarded sub-case.

Wave-2+ tightening candidates
-----------------------------
* Syntactically-identical ``cond`` strings on two transitions of the
  same source state with overlapping ``event`` matchers.
* Pairs where one ``cond`` is a strict refinement of the other under
  the SOS-01 §5.1 ECMAScript subset (e.g. ``a > 0`` and ``a > 1``).
* SMT-backed bounded-reachability proofs over the datamodel.

Severity
--------
``warning``. Document-order priority IS the rule per §5.2; this rule
surfaces a chart-author awareness need, not a violation.

Failure message
---------------
Chart vocabulary per INV-S-HDL-5: cite the source-state ID, the
``event``/``cond`` shape of each transition in the offending pair, and
reference "SOS-08-C §5 — document-order priority resolves overlapping
transitions".
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from ._common import (
    SEVERITY_WARNING,
    Finding,
    iter_elements,
    localname,
)

RULE_ID = "SCXML-LINT-C-1"

# Citation appended to every chart-vocabulary warning message.
_SPEC_CITE = (
    "SOS-08-C §5 — document-order priority resolves overlapping transitions"
)


def _enclosing_state_id(tr) -> Optional[str]:
    """Return the ``id`` of the nearest ``<state>``/``<parallel>``/``<final>``
    ancestor of ``tr`` (the transition's source state).

    SCXML places ``<transition>`` directly under its source state, so we
    walk up one level first and fall back to a general scan in case the
    chart has intermediate wrappers.
    """
    cur = tr.getparent()
    while cur is not None:
        tag = getattr(cur, "tag", None)
        if isinstance(tag, str):
            name = localname(tag)
            if name in ("state", "parallel", "final"):
                sid = cur.get("id")
                if sid:
                    return sid
        cur = cur.getparent()
    return None


def _transition_shape(tr) -> str:
    """Render a short chart-vocabulary handle for ``tr``.

    Used in the warning message to identify which transition pair
    overlapped. ``event``/``target`` are surfaced when present; absent
    fields render as ``(none)``.
    """
    ev = tr.get("event") or "(none)"
    target = tr.get("target") or "(internal)"
    return f"event='{ev}' target='{target}'"


def _is_overlapping_pair(a, b) -> bool:
    """Return True if transitions ``a`` and ``b`` form an overlapping pair
    under the v1 scaffold detection rules.

    Both must lack a ``cond``. They overlap when their ``event``
    matchers could fire simultaneously:

    * Both omit ``event`` (eventless / always-on).
    * Both share the same ``event`` value.

    (Per W3C SCXML 1.0 ``event`` supports descriptor-prefix matching,
    e.g. ``error.execution`` matches ``error``; v1 ignores this and
    treats descriptors literally. False negatives here are acceptable
    given the rule's warning severity.)
    """
    if a.get("cond") or b.get("cond"):
        return False
    ev_a = a.get("event")
    ev_b = b.get("event")
    if ev_a is None and ev_b is None:
        return True
    if ev_a is not None and ev_b is not None and ev_a == ev_b:
        return True
    return False


def _collect_state_transitions(state_el) -> List:
    """Return ``<transition>`` elements that are *direct* children of ``state_el``.

    SCXML semantics: a transition belongs to its parent state. Deeper
    descendants belong to nested states and must not be conflated.
    """
    transitions = []
    for child in state_el:
        tag = getattr(child, "tag", None)
        if isinstance(tag, str) and localname(tag) == "transition":
            transitions.append(child)
    return transitions


def _find_first_overlap(transitions) -> Optional[Tuple[int, int]]:
    """Return the (i, j) index pair (i < j) of the first overlapping pair.

    Walks transitions in document order and returns on the first match.
    Returning only the first pair keeps the warning surface readable
    even when a state has many overlapping transitions; the chart
    author fixes that pair, re-runs lint, sees the next pair, etc.
    """
    n = len(transitions)
    for i in range(n):
        for j in range(i + 1, n):
            if _is_overlapping_pair(transitions[i], transitions[j]):
                return (i, j)
    return None


def check(tree, scxml_path: Path) -> List[Finding]:
    """Walk every ``<state>``/``<parallel>``/``<final>``; warn on overlapping
    transition pairs per the v1 scaffold rules.

    One finding per state with ≥1 overlapping pair (the first such
    pair). Reporting every pair would multiply warnings on states with
    many unguarded transitions; the first-pair convention mirrors how
    rule_004 reports the first nesting site.
    """
    findings: List[Finding] = []
    root = tree.getroot()
    path_str = str(scxml_path)

    # The chart's transition mux rule applies to every container of
    # transitions: ``<state>``, ``<parallel>``, ``<final>``. We iterate
    # all three element types and collect direct-child transitions.
    seen_states = set()
    for name in ("state", "parallel", "final"):
        for state_el in iter_elements(root, name):
            sid = state_el.get("id") or "(unnamed)"
            # Guard against double-visiting if iter_elements returns the
            # same element under two passes (defensive — shouldn't happen
            # given disjoint local-name partitioning).
            key = id(state_el)
            if key in seen_states:
                continue
            seen_states.add(key)

            transitions = _collect_state_transitions(state_el)
            if len(transitions) < 2:
                continue

            pair = _find_first_overlap(transitions)
            if pair is None:
                continue

            i, j = pair
            tr_a, tr_b = transitions[i], transitions[j]
            findings.append(Finding(
                RULE_ID,
                SEVERITY_WARNING,
                (
                    f"state '{sid}' has two transitions whose guards could "
                    f"simultaneously be true; document-order priority will "
                    f"pick the first. Transition #{i + 1} "
                    f"({_transition_shape(tr_a)}) precedes transition "
                    f"#{j + 1} ({_transition_shape(tr_b)}). "
                    f"{_SPEC_CITE}."
                ),
                path_str,
                tr_a.sourceline or state_el.sourceline or 1,
            ))

    return findings
