"""SCXML-LINT-H-1 — reject preemption-related markup at chart-validation time.

Per ``docs/concepts/SOS-08-H-CONCEPTS.md`` §5 (frozen non-feature,
cooperative-only at v1) and §15 2026-05-23 PCDN-SOS-08-H-001 resolution
(hard-reject): the SOS chart validator MUST hard-reject any preemption-
related annotation. A silent warn-and-ignore would invite chart authors
to author against semantics SOS does not implement at v1, then debug
phantom semantics against an emitter that silently dropped the markup.

Rejected forms:

* Attributes (on any element): ``preemptible``, ``priority-preempt``,
  ``preempt``, ``interrupt-priority``.
* Elements (any namespace): ``preempt`` and any ``preempt-*`` element
  local name; this covers a hypothetical ``<sos:preempt>`` /
  ``<sos:preempt-task>`` markup and any bare ``<preempt>``.

NOT rejected:

* Datamodel ``<data>`` ``id`` / ``expr`` values containing the substring
  "preempt" — datamodel variable names are user-owned vocabulary and
  carry no scheduling semantics by themselves. Only *structural* markup
  (attributes on chart elements, executable-content elements) is rejected.

Failure messages render in chart vocabulary per INV-S-HDL-5: name the
offending attribute or element local-name, the nearest chart-state ID
context, and cite SOS-08-H §5. No XPath, no parser-internal strings.

Severity: ``error``.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from ._common import SEVERITY_ERROR, Finding, localname

RULE_ID = "SCXML-LINT-H-1"

# Attribute local-names that convey preemption semantics. Match is on the
# attribute's local name (namespace-agnostic) — a chart author who tries
# ``preemptible="true"`` on a ``<state>`` or ``sos:preemptible="true"``
# both fire.
_PREEMPTION_ATTR_NAMES = frozenset({
    "preemptible",
    "priority-preempt",
    "preempt",
    "interrupt-priority",
})

# Element local-name prefix for preemption-related custom executable
# content. Any element whose local name is ``preempt`` or starts with
# ``preempt-`` fires (covers ``<sos:preempt>``, ``<preempt>``,
# ``<sos:preempt-task>``, etc.).
_PREEMPTION_ELEMENT_LOCALNAME = "preempt"
_PREEMPTION_ELEMENT_PREFIX = "preempt-"

# SOS-08-H §5 citation appended to every chart-vocabulary error message.
_SPEC_CITE = "SOS-08-H §5 — preemption is not supported at v1 (cooperative-only)"


def _nearest_state_id(el) -> Optional[str]:
    """Return the ``id`` of the nearest ``<state>``/``<parallel>``/``<final>``
    ancestor (or the element itself if it carries one).

    Used for the chart-vocabulary context handle in the failure message.
    Returns ``None`` when the offending markup is on the root or in a
    region with no enclosing state id.
    """
    cur = el
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


def _state_context_phrase(el) -> str:
    """Render the chart-state context for a failure message.

    Always produces text — ``"in state '<id>'"`` when a containing state
    is found, ``"at the chart root"`` otherwise.
    """
    sid = _nearest_state_id(el)
    if sid:
        return f"in state '{sid}'"
    return "at the chart root"


def _is_preemption_element(el) -> bool:
    """Return True if ``el`` is a custom preemption-related element.

    Matches ``<preempt>`` and ``<preempt-*>`` by local name, in any
    namespace (chart-author MAY namespace it ``sos:`` or leave it bare).
    """
    tag = getattr(el, "tag", None)
    if not isinstance(tag, str):
        return False
    name = localname(tag)
    if name == _PREEMPTION_ELEMENT_LOCALNAME:
        return True
    if name.startswith(_PREEMPTION_ELEMENT_PREFIX):
        return True
    return False


def check(tree, scxml_path: Path) -> List[Finding]:
    """Walk every element; reject preemption-related attributes and elements.

    Emits one ``Finding`` per offending attribute/element occurrence so a
    chart author with multiple preemption attempts sees every site at
    once rather than fixing them one bench-cycle at a time.
    """
    findings: List[Finding] = []
    root = tree.getroot()
    path_str = str(scxml_path)

    for el in root.iter():
        tag = getattr(el, "tag", None)
        if not isinstance(tag, str):
            # Skip comments / processing instructions.
            continue

        # 1) Preemption-related custom element (e.g. <sos:preempt>).
        if _is_preemption_element(el):
            ctx = _state_context_phrase(el)
            findings.append(Finding(
                RULE_ID,
                SEVERITY_ERROR,
                f"preemption-related element <{localname(tag)}> {ctx} is "
                f"not permitted; {_SPEC_CITE}.",
                path_str,
                el.sourceline or 1,
            ))
            # Fall through: an element MAY also carry preemption attrs.

        # 2) Preemption-related attributes on any element.
        for attr in el.attrib:
            if localname(attr) in _PREEMPTION_ATTR_NAMES:
                ctx = _state_context_phrase(el)
                findings.append(Finding(
                    RULE_ID,
                    SEVERITY_ERROR,
                    f"preemption-related attribute '{localname(attr)}' on "
                    f"<{localname(tag)}> {ctx} is not permitted; "
                    f"{_SPEC_CITE}.",
                    path_str,
                    el.sourceline or 1,
                ))

    return findings
