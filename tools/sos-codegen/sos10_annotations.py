"""SOS-10 orchestrator-chart annotation parser + validator.

Reads the loader's `ChartAst.raw_scjson` shape (or any scjson-derived dict)
and extracts the orchestrator-chart annotations declared by SOS-10:

- `sos:lang` attribute on each top-level `<state>` (PCDN-SOS-10-003) — names
  the language target each piece compiles to.
- `<sos:medium>` sub-element on each cross-piece `<transition>`
  (PCDN-SOS-10-004) — declares the medium for the cross-piece event.
  Sub-sub-elements `<sos:transport>` / `<sos:timeout>` / `<sos:idempotent>`
  carry medium-scoped detail (PCDN-SOS-10-004, PCDN-SOS-10-006).
- `sos:idempotent` attribute on `<transition>` (PCDN-SOS-10-005) — per-
  transition idempotency override.

This module IS the input contract every later SOS-10 sub-phase emitter reads
(per-medium emitters in §6 of SOS-10-CONCEPTS.md). It validates §5.1
orchestrator chart shape, §5.2 medium enumeration, and the per-medium
contracts of §6 (only the chart-side surface — wire format derivation
remains the emitter's responsibility per INV-S-ORCH-4).

Authority: `docs/concepts/SOS-10-CONCEPTS.md` (ratified 2026-05-23; all 8
PCDNs resolved). This parser does NOT enforce:

- Multi-orchestrator composition (INV-S-ORCH-1 / PCDN-SOS-10-007 is strict
  at v1 but is a chart-shape concern, not an annotation concern).
- Wire-format consistency (INV-S-ORCH-4; emitter concern).
- Per-medium failure-mode taxonomy (INV-S-ORCH-5; emitter concern).

Mirrors `tools/sos-codegen/sos09_annotations.py` in shape: dataclass-based
public surface + a single `parse_orchestrator_annotations(chart_ast: dict)`
entry point + a `Sos10AnnotationError` (ValueError subclass) error type.

Public surface:
    parse_orchestrator_annotations(chart_ast: dict) -> OrchestratorAnnotations
    Sos10AnnotationError

Invariants enforced:
    - Medium kind ∈ §5.2 frozen 4-value enum (Standards Action).
    - Transport name ∈ {"gRPC", "AMQP"} per PCDN-SOS-10-002 (Standards Action).
    - kind="network" MUST carry <sos:transport>; other kinds MUST NOT.
    - sos:lang values MUST be SV-identifiers; default "rust" per PCDN-001/003.
    - <sos:medium> may carry zero-or-one of each of <sos:transport>,
      <sos:timeout>, <sos:idempotent>.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Frozen enums — Standards Action registration policy.
# ---------------------------------------------------------------------------

# Per SOS-10-CONCEPTS §5.2 (ratified 2026-05-23). Adding a fifth value
# requires a §15 amendment + a new §6.N sub-section ratifying its emitter
# contract.
ALLOWED_MEDIUM_KINDS: frozenset[str] = frozenset(
    {"in-process", "shared-memory", "mmio", "network"}
)

# Per PCDN-SOS-10-002 ratification. gRPC primary at v1; AMQP secondary.
# Adding a third transport requires a §15 amendment.
ALLOWED_TRANSPORT_NAMES: frozenset[str] = frozenset({"gRPC", "AMQP"})

# Per PCDN-SOS-10-001 / -003 ratification: gateway-piece v1 language is
# Rust; the default for a `<state>` that omits `sos:lang` is "rust".
DEFAULT_PIECE_LANG: str = "rust"

# IEEE 1800-2017 §5.6 SV-identifier shape — the same shape SOS-09-A uses
# for `sos:name`. Per PCDN-SOS-10-003 the language token is also an
# SV-identifier (parser concerns; the codegen mapping table is the
# emitter's responsibility).
_SV_IDENTIFIER_RE: re.Pattern[str] = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# The two `sos:`-namespaced sub-element qnames the parser recognises on a
# transition. scjson surfaces foreign-namespace sub-elements via the
# `other_element` list with qname in James-Clark form
# `{https://softoboros.com/sos/1.0}<localname>`.
SOS_NS: str = "https://softoboros.com/sos/1.0"
_MEDIUM_QNAME: str = f"{{{SOS_NS}}}medium"
_TRANSPORT_QNAME: str = f"{{{SOS_NS}}}transport"
_TIMEOUT_QNAME: str = f"{{{SOS_NS}}}timeout"
_IDEMPOTENT_QNAME: str = f"{{{SOS_NS}}}idempotent"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class Sos10AnnotationError(ValueError):
    """Raised when chart annotations are malformed or violate frozen invariants.

    Carries an `element_path` (best-effort dotted SCXML id path) and an
    optional `rule` token naming which SOS-10 section or PCDN fired, for
    downstream error-reporting tooling.
    """

    def __init__(
        self,
        message: str,
        *,
        element_path: Optional[str] = None,
        rule: Optional[str] = None,
    ) -> None:
        self.element_path = element_path
        self.rule = rule
        prefix_parts: list[str] = []
        if rule:
            prefix_parts.append(f"[{rule}]")
        if element_path:
            prefix_parts.append(f"at <{element_path}>")
        prefix = " ".join(prefix_parts)
        super().__init__(f"{prefix}: {message}" if prefix else message)


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PieceAnnotation:
    """One piece of an orchestrator chart.

    Per SOS-10-CONCEPTS §5.1: each top-level `<state>` of an orchestrator
    chart corresponds to one piece. `state_id` matches the `<state id="…"/>`
    attribute; `lang` is the resolved language target (defaulting to
    `"rust"` per PCDN-SOS-10-001 / -003 when no `sos:lang` attribute is
    present); `extras` surfaces any other `sos:`-prefixed attributes the
    parser saw on the state (forward-compat with future SOS-10 sub-phases).
    """

    state_id: str
    lang: str
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TransportAnnotation:
    """Network-medium transport declaration.

    Per SOS-10-CONCEPTS §6.4 + PCDN-SOS-10-002: `name` ∈ {"gRPC", "AMQP"}.
    `timeout_ms` MAY override the per-medium default (gRPC=5000ms,
    AMQP=10000ms per PCDN-SOS-10-006) at the transport level; the more
    common form is to set the timeout at the medium level (see
    `MediumAnnotation.timeout`).
    """

    name: str
    timeout_ms: Optional[int] = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MediumAnnotation:
    """One `<sos:medium>` declaration on a cross-piece transition.

    Per SOS-10-CONCEPTS §5.2 + §6: `kind` ∈ §5.2 frozen 4-value enum;
    `transport` is REQUIRED when `kind="network"` and FORBIDDEN otherwise.
    `timeout` is opt-in (PCDN-SOS-10-006); `idempotent` is opt-in (per
    PCDN-SOS-10-005, but at the medium-element level — a per-transition
    override via the `sos:idempotent` attribute lives on
    `CrossPieceTransitionAnnotation.idempotent`).
    """

    kind: str
    transport: Optional[TransportAnnotation] = None
    timeout: Optional[int] = None  # milliseconds
    idempotent: Optional[bool] = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CrossPieceTransitionAnnotation:
    """One cross-piece transition extracted from the orchestrator chart.

    A transition is "cross-piece" iff its source state and target state are
    DIFFERENT top-level pieces AND it carries a `<sos:medium>` annotation.
    Intra-piece transitions (target stays inside the same piece) do not
    need annotation and are not included here.

    `idempotent` here is the per-transition `sos:idempotent` attribute
    override (PCDN-SOS-10-005); the medium-level `<sos:idempotent>`
    sub-element value lives on `medium.idempotent`. When both are set, the
    transition-level override wins; consumer code typically falls back to
    `medium.idempotent` when this field is None.
    """

    source_state_id: str
    target_state_id: str
    event: str
    medium: MediumAnnotation
    idempotent: Optional[bool] = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrchestratorAnnotations:
    """All SOS-10 annotations extracted from one orchestrator chart.

    `pieces` is ordered by document-order traversal of the orchestrator's
    top-level `<state>` children. `transitions` is ordered by document
    order of (source state, transition) pairs.
    """

    pieces: list[PieceAnnotation]
    transitions: list[CrossPieceTransitionAnnotation]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_other_attributes(node: dict[str, Any]) -> dict[str, Any]:
    """Return the parsed `other_attributes` JSON map for a scjson node, or {}.

    scjson 0.3.6 surfaces SCXML `other_attributes` as:
        node["other_attributes"]["other_attributes"] -> JSON string

    Mirrors the helper in `sos09_annotations.py`.
    """
    oa = node.get("other_attributes")
    if oa is None:
        return {}
    if isinstance(oa, str):
        raw = oa
    elif isinstance(oa, dict):
        inner = oa.get("other_attributes")
        if isinstance(inner, str):
            raw = inner
        elif isinstance(inner, dict):
            return inner
        elif inner is None:
            # scjson MAY surface a flat dict directly.
            return {k: v for k, v in oa.items() if k != "other_attributes"} or {}
        else:
            return {}
    else:
        return {}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise Sos10AnnotationError(
            f"malformed other_attributes JSON: {exc}",
            rule="parse",
        ) from exc
    if not isinstance(parsed, dict):
        raise Sos10AnnotationError(
            "other_attributes JSON must be an object",
            rule="parse",
        )
    return parsed


def _sos_keys(attrs: dict[str, Any]) -> dict[str, Any]:
    """Partition `sos:`-prefixed keys from a parsed other_attributes map."""
    return {
        k: v for k, v in attrs.items()
        if isinstance(k, str) and k.startswith("sos:")
    }


def _validate_sv_identifier(value: Any, *, element_path: str, key: str) -> str:
    """Reject anything that isn't an IEEE 1800-2017 §5.6 SV identifier."""
    if not isinstance(value, str) or not _SV_IDENTIFIER_RE.match(value):
        raise Sos10AnnotationError(
            f"{key} must be an SV identifier ([A-Za-z_][A-Za-z0-9_]*); "
            f"got {value!r}",
            element_path=element_path,
            rule="§5.1",
        )
    return value


def _parse_bool_token(token: Any, *, element_path: str, label: str) -> bool:
    """Permit "true"/"false" strings and Python booleans; reject everything else."""
    if isinstance(token, bool):
        return token
    if isinstance(token, str):
        low = token.strip().lower()
        if low == "true":
            return True
        if low == "false":
            return False
    raise Sos10AnnotationError(
        f"{label} must be boolean (true|false); got {token!r}",
        element_path=element_path,
        rule="PCDN-SOS-10-005",
    )


def _parse_int_token(token: Any, *, element_path: str, label: str) -> int:
    """Accept Python ints and integer strings; reject floats/booleans/garbage."""
    if isinstance(token, bool):
        raise Sos10AnnotationError(
            f"{label} must be an integer; got bool {token!r}",
            element_path=element_path,
            rule="PCDN-SOS-10-006",
        )
    if isinstance(token, int):
        return token
    if isinstance(token, str):
        try:
            return int(token, 10)
        except ValueError as exc:
            raise Sos10AnnotationError(
                f"{label} must be an integer; got {token!r}",
                element_path=element_path,
                rule="PCDN-SOS-10-006",
            ) from exc
    raise Sos10AnnotationError(
        f"{label} must be an integer; got {token!r} (type={type(token).__name__})",
        element_path=element_path,
        rule="PCDN-SOS-10-006",
    )


def _find_medium_element(
    transition_node: dict[str, Any]
) -> Optional[dict[str, Any]]:
    """Return the `<sos:medium>` other_element node (or None).

    Per PCDN-SOS-10-004: `<sos:medium>` is a sub-element of `<transition>`.
    A transition with more than one `<sos:medium>` is malformed; we raise
    when more than one is found.
    """
    elements = transition_node.get("other_element") or []
    if not isinstance(elements, list):
        return None
    found = [
        el for el in elements
        if isinstance(el, dict) and el.get("qname") == _MEDIUM_QNAME
    ]
    if len(found) > 1:
        raise Sos10AnnotationError(
            f"transition carries {len(found)} <sos:medium> sub-elements; "
            f"§5.1 + PCDN-SOS-10-004 permit zero or one",
            rule="§5.1",
        )
    return found[0] if found else None


def _parse_medium_element(
    medium_node: dict[str, Any],
    *,
    element_path: str,
) -> MediumAnnotation:
    """Parse a `<sos:medium>` node + its `<sos:transport>` /
    `<sos:timeout>` / `<sos:idempotent>` sub-sub-elements."""

    attrs = medium_node.get("attributes") or {}
    if not isinstance(attrs, dict):
        raise Sos10AnnotationError(
            "<sos:medium>.attributes must be a dict",
            element_path=element_path,
            rule="§5.2",
        )

    kind = attrs.get("kind")
    if kind not in ALLOWED_MEDIUM_KINDS:
        raise Sos10AnnotationError(
            f"<sos:medium kind={kind!r}> not in frozen 4-value enum "
            f"{sorted(ALLOWED_MEDIUM_KINDS)} per SOS-10-CONCEPTS §5.2 "
            f"(Standards Action)",
            element_path=element_path,
            rule="§5.2",
        )

    # Forward-compat: surface any non-`kind` attribute on the medium element.
    extras: dict[str, Any] = {k: v for k, v in attrs.items() if k != "kind"}

    children = medium_node.get("children") or []
    if not isinstance(children, list):
        children = []

    transport_node: Optional[dict[str, Any]] = None
    timeout_node: Optional[dict[str, Any]] = None
    idempotent_node: Optional[dict[str, Any]] = None

    for child in children:
        if not isinstance(child, dict):
            continue
        qn = child.get("qname")
        if qn == _TRANSPORT_QNAME:
            if transport_node is not None:
                raise Sos10AnnotationError(
                    "<sos:medium> carries multiple <sos:transport> children; "
                    "at most one is permitted",
                    element_path=element_path,
                    rule="§6.4",
                )
            transport_node = child
        elif qn == _TIMEOUT_QNAME:
            if timeout_node is not None:
                raise Sos10AnnotationError(
                    "<sos:medium> carries multiple <sos:timeout> children; "
                    "at most one is permitted",
                    element_path=element_path,
                    rule="PCDN-SOS-10-006",
                )
            timeout_node = child
        elif qn == _IDEMPOTENT_QNAME:
            if idempotent_node is not None:
                raise Sos10AnnotationError(
                    "<sos:medium> carries multiple <sos:idempotent> children; "
                    "at most one is permitted",
                    element_path=element_path,
                    rule="PCDN-SOS-10-005",
                )
            idempotent_node = child
        # Unknown sub-element qnames are silently ignored to preserve
        # forward-compat with future SOS-10 sub-phases (§14 unblocks).

    # Cross-validation: transport is REQUIRED iff kind="network".
    if kind == "network" and transport_node is None:
        raise Sos10AnnotationError(
            "<sos:medium kind='network'> MUST carry a <sos:transport> child "
            "per SOS-10-CONCEPTS §6.4 + INV-S-ORCH-3",
            element_path=element_path,
            rule="§6.4",
        )
    if kind != "network" and transport_node is not None:
        raise Sos10AnnotationError(
            f"<sos:medium kind={kind!r}> MUST NOT carry a <sos:transport> "
            f"child (transport only applies to kind='network' per §6.4)",
            element_path=element_path,
            rule="§6.4",
        )

    # Parse transport.
    transport: Optional[TransportAnnotation] = None
    if transport_node is not None:
        t_attrs = transport_node.get("attributes") or {}
        if not isinstance(t_attrs, dict):
            raise Sos10AnnotationError(
                "<sos:transport>.attributes must be a dict",
                element_path=element_path,
                rule="§6.4",
            )
        t_name = t_attrs.get("name")
        if t_name not in ALLOWED_TRANSPORT_NAMES:
            raise Sos10AnnotationError(
                f"<sos:transport name={t_name!r}> not in allowed set "
                f"{sorted(ALLOWED_TRANSPORT_NAMES)} per PCDN-SOS-10-002 "
                f"(Standards Action)",
                element_path=element_path,
                rule="PCDN-SOS-10-002",
            )
        t_timeout_ms: Optional[int] = None
        if "timeout-ms" in t_attrs:
            t_timeout_ms = _parse_int_token(
                t_attrs["timeout-ms"],
                element_path=element_path,
                label="<sos:transport timeout-ms>",
            )
        t_extras: dict[str, Any] = {
            k: v for k, v in t_attrs.items()
            if k not in {"name", "timeout-ms"}
        }
        transport = TransportAnnotation(
            name=t_name,
            timeout_ms=t_timeout_ms,
            extras=t_extras,
        )

    # Parse timeout.
    timeout_ms: Optional[int] = None
    if timeout_node is not None:
        ts_attrs = timeout_node.get("attributes") or {}
        if "ms" not in ts_attrs:
            raise Sos10AnnotationError(
                "<sos:timeout> MUST carry an `ms` attribute per "
                "SOS-10-CONCEPTS §6.4 / PCDN-SOS-10-006",
                element_path=element_path,
                rule="PCDN-SOS-10-006",
            )
        timeout_ms = _parse_int_token(
            ts_attrs["ms"],
            element_path=element_path,
            label="<sos:timeout ms>",
        )
        if timeout_ms < 0:
            raise Sos10AnnotationError(
                f"<sos:timeout ms={timeout_ms}> must be non-negative",
                element_path=element_path,
                rule="PCDN-SOS-10-006",
            )

    # Parse medium-level idempotent.
    idempotent: Optional[bool] = None
    if idempotent_node is not None:
        i_attrs = idempotent_node.get("attributes") or {}
        # Accept either <sos:idempotent value="true"/> or
        # <sos:idempotent>true</sos:idempotent>; the latter surfaces as
        # `text`, the former as attributes["value"].
        if "value" in i_attrs:
            idempotent = _parse_bool_token(
                i_attrs["value"],
                element_path=element_path,
                label="<sos:idempotent value>",
            )
        else:
            text = (idempotent_node.get("text") or "").strip()
            if text:
                idempotent = _parse_bool_token(
                    text,
                    element_path=element_path,
                    label="<sos:idempotent>",
                )
            else:
                raise Sos10AnnotationError(
                    "<sos:idempotent> requires either a `value` attribute "
                    "or boolean text content per PCDN-SOS-10-005",
                    element_path=element_path,
                    rule="PCDN-SOS-10-005",
                )

    return MediumAnnotation(
        kind=kind,
        transport=transport,
        timeout=timeout_ms,
        idempotent=idempotent,
        extras=extras,
    )


def _parse_piece(
    state_node: dict[str, Any],
    *,
    element_path: str,
) -> PieceAnnotation:
    """Extract a piece annotation from one top-level `<state>` element.

    Defaults `lang` to `"rust"` per PCDN-SOS-10-001 / -003 when no
    `sos:lang` attribute is present. Any other `sos:`-prefixed attribute on
    the state is preserved in `extras` for forward-compat.
    """
    attrs = _extract_other_attributes(state_node)
    sos_attrs = _sos_keys(attrs)

    state_id = state_node.get("id") or "<anonymous>"

    lang_raw = sos_attrs.get("sos:lang")
    if lang_raw is None:
        lang = DEFAULT_PIECE_LANG
    else:
        lang = _validate_sv_identifier(
            lang_raw, element_path=element_path, key="sos:lang"
        )

    extras = {k: v for k, v in sos_attrs.items() if k != "sos:lang"}
    return PieceAnnotation(state_id=state_id, lang=lang, extras=extras)


def _parse_transition(
    transition_node: dict[str, Any],
    *,
    source_state_id: str,
    piece_ids: set[str],
) -> Optional[CrossPieceTransitionAnnotation]:
    """Extract a cross-piece transition annotation, or None if intra-piece.

    A transition is cross-piece iff:
        (a) it carries a `<sos:medium>` sub-element, AND
        (b) its `target` references a different piece (top-level state).

    Per SOS-10-CONCEPTS §5.1: only transitions whose target is a different
    piece need a `<sos:medium>` annotation. We raise if a transition has a
    `<sos:medium>` but its target is the same piece (a chart-author error)
    — but only when the target is parseable as a piece-id at all.
    """
    medium_node = _find_medium_element(transition_node)
    if medium_node is None:
        return None

    target_raw = transition_node.get("target")
    if isinstance(target_raw, list):
        target = target_raw[0] if target_raw else None
    elif isinstance(target_raw, str):
        target = target_raw
    else:
        target = None

    if target is None:
        raise Sos10AnnotationError(
            "cross-piece transition (carries <sos:medium>) MUST have a "
            "`target` attribute per SOS-10-CONCEPTS §5.1",
            element_path=source_state_id,
            rule="§5.1",
        )

    # Per INV-S-ORCH-1 + §5.1: every state in an orchestrator chart's
    # top-level state list is a piece. A target that isn't a known
    # top-level piece is a chart-author error. We surface that here.
    if target not in piece_ids:
        raise Sos10AnnotationError(
            f"cross-piece transition target {target!r} is not a top-level "
            f"piece of the orchestrator chart (known pieces: "
            f"{sorted(piece_ids)}). Per SOS-10-CONCEPTS §5.1 every cross-"
            f"piece transition target MUST be a sibling top-level <state>",
            element_path=source_state_id,
            rule="§5.1",
        )

    element_path = f"{source_state_id} -> {target}"
    medium = _parse_medium_element(medium_node, element_path=element_path)

    # Parse the transition-level `sos:idempotent` attribute (PCDN-005).
    tr_attrs = _extract_other_attributes(transition_node)
    sos_tr_attrs = _sos_keys(tr_attrs)
    tr_idempotent: Optional[bool] = None
    if "sos:idempotent" in sos_tr_attrs:
        tr_idempotent = _parse_bool_token(
            sos_tr_attrs["sos:idempotent"],
            element_path=element_path,
            label="<transition sos:idempotent>",
        )
    extras = {k: v for k, v in sos_tr_attrs.items() if k != "sos:idempotent"}

    event = transition_node.get("event") or ""
    if not isinstance(event, str) or not event:
        raise Sos10AnnotationError(
            "cross-piece transition MUST carry an `event` attribute per "
            "SOS-10-CONCEPTS §5.1 (cross-piece events are named)",
            element_path=element_path,
            rule="§5.1",
        )

    return CrossPieceTransitionAnnotation(
        source_state_id=source_state_id,
        target_state_id=target,
        event=event,
        medium=medium,
        idempotent=tr_idempotent,
        extras=extras,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_orchestrator_annotations(chart_ast: dict) -> OrchestratorAnnotations:
    """Walk the orchestrator scjson AST and produce a typed annotation model.

    `chart_ast` is the dict surfaced by `loader.load_chart(...).raw_scjson`
    (or any equivalent scjson-shape dict). The root represents the
    orchestrator's `<scxml>` element; its top-level `state` children are
    pieces (per SOS-10-CONCEPTS §5.1).

    Raises `Sos10AnnotationError` on any violation of §5.1 / §5.2 / §6
    chart-side surface rules. Wire-format consistency, multi-orchestrator
    composition, and per-medium failure taxonomy are NOT checked here
    (per the module docstring's "what we do not validate" list).
    """
    if not isinstance(chart_ast, dict):
        raise Sos10AnnotationError(
            f"chart_ast must be a dict; got {type(chart_ast).__name__}",
            rule="parse",
        )

    states = chart_ast.get("state") or []
    if not isinstance(states, list):
        raise Sos10AnnotationError(
            "orchestrator chart root must carry a `state` list of pieces",
            rule="§5.1",
        )

    pieces: list[PieceAnnotation] = []
    piece_ids: set[str] = set()
    for st in states:
        if not isinstance(st, dict):
            continue
        sid = st.get("id") or "<anonymous>"
        element_path = sid
        piece = _parse_piece(st, element_path=element_path)
        # Per INV-S-ORCH-1 strict at v1: piece-ids MUST be unique within
        # the orchestrator chart. Duplicates would make
        # `<transition target="…">` resolution ambiguous.
        if piece.state_id in piece_ids:
            raise Sos10AnnotationError(
                f"duplicate piece state_id {piece.state_id!r} in "
                f"orchestrator chart; piece ids MUST be unique",
                element_path=element_path,
                rule="§5.1",
            )
        piece_ids.add(piece.state_id)
        pieces.append(piece)

    # Now walk transitions on each top-level piece, collecting cross-piece
    # annotations.
    transitions: list[CrossPieceTransitionAnnotation] = []
    for st in states:
        if not isinstance(st, dict):
            continue
        source_state_id = st.get("id") or "<anonymous>"
        for tr in st.get("transition") or []:
            if not isinstance(tr, dict):
                continue
            ann = _parse_transition(
                tr,
                source_state_id=source_state_id,
                piece_ids=piece_ids,
            )
            if ann is not None:
                transitions.append(ann)

    return OrchestratorAnnotations(pieces=pieces, transitions=transitions)


__all__ = [
    "MediumAnnotation",
    "OrchestratorAnnotations",
    "PieceAnnotation",
    "Sos10AnnotationError",
    "TransportAnnotation",
    "CrossPieceTransitionAnnotation",
    "parse_orchestrator_annotations",
    # Frozen enums exported for downstream emitters that want to mirror them.
    "ALLOWED_MEDIUM_KINDS",
    "ALLOWED_TRANSPORT_NAMES",
    "DEFAULT_PIECE_LANG",
]
