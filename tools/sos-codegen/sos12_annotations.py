"""SOS-12 dispatch + contract annotation parser + validator.

Reads the loader's `ChartAst.raw_scjson` shape (or any scjson-derived dict)
and extracts the SOS-12 chart-decomposition annotations:

- `<sos:dispatch ref="…"/>` elements (PCDN-SOS-12-001 ratified shape) that
  appear as children of `<state>` elements and declare the sub-chart the
  parent dispatches into. The `ref` attribute names a sub-chart filename
  (resolved relative to the parent chart's directory) or chart-id token.
- `<sos:contract>` elements (PCDN-SOS-12-004 ratified shape) at the root
  of a sub-chart's `<scxml>` document carrying the four-tuple contract
  surface (events_in, events_out, invariants, datamodel_boundary). Per
  PCDN-SOS-12-002 the datamodel boundary is per-sub-chart (`reads` and
  `writes` attributes carry space-separated field-name lists).

The module also validates the dispatch-tree's recursion depth against the
PCDN-SOS-12-005 cap (default 8 levels per §6.5 / §10.3 / INV-S-DISP-5).
Exceeding the cap raises a chart-author-friendly error citing the spec
section.

This module IS the input contract every later SOS-12 sub-phase consumes
(Wave-1B's bound-composition module; Wave-2's contract-matching verifier;
the codegen lowering of dispatched states in SOS-04 / SOS-05). It does NOT
implement bound composition (Wave-1B); it does NOT match parent-↔sub
contracts pairwise (Wave-2); it does NOT emit boundary vectors (downstream
of the verifier). Clear extension points are left as docstring TODOs for
each downstream consumer.

Authority:
    `docs/concepts/SOS-12-CONCEPTS.md` (ratified 2026-05-23; all 6 PCDNs
    walked). Per the §15 PCDN resolutions:

    - PCDN-001: `<sos:dispatch ref="…"/>` custom element under the
      `xmlns:sos="https://softoboros.com/sos/1.0"` namespace.
    - PCDN-002: per-sub-chart `<sos:contract reads="…" writes="…"/>`
      with explicit field lists (space-separated tokens).
    - PCDN-004: inline in sub-chart SCXML — root-level `<sos:contract>`.
    - PCDN-005: recursion depth capped at 8 (override via constructor).
    - INV-S-DISP-1 / -5 (§10.1): per-layer vector counts are local — this
      parser surfaces the dispatch boundaries; consumers MUST NOT replay
      across layers per INV-S-DISP-1.

Public surface:
    parse_dispatch_annotations(ast: dict, *,
        chart_path: Path | None = None,
        max_depth: int = DEFAULT_MAX_DEPTH,
        loader: callable | None = None,
    ) -> DispatchInventory
    DispatchAnnotation
    Contract
    DispatchInventory
    Sos12AnnotationError

Frozen enums:
    DEFAULT_MAX_DEPTH = 8           # PCDN-SOS-12-005 / §6.5 / §10.3
    PERMITTED_DISPATCH_ATTRS        # {"ref"} — PCDN-001 frozen set
    PERMITTED_CONTRACT_ATTRS        # {"reads", "writes"} — PCDN-002 frozen set
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# Frozen enums + namespace constants (Standards Action registration policy).
# ---------------------------------------------------------------------------

# Per SOS-09 PCDN-001 amended resolution: the `xmlns:sos` namespace URL used
# by SOS-08-D / -E / SOS-12 / future phases for NEW elements (distinct from
# the SOS-09 `sos:`-prefix-in-`other_attributes` annotation convention which
# does NOT declare an XML namespace).
SOS_NS: str = "https://softoboros.com/sos/1.0"
_DISPATCH_QNAME: str = f"{{{SOS_NS}}}dispatch"
_CONTRACT_QNAME: str = f"{{{SOS_NS}}}contract"
_EVENTS_IN_QNAME: str = f"{{{SOS_NS}}}events-in"
_EVENTS_OUT_QNAME: str = f"{{{SOS_NS}}}events-out"
_INVARIANTS_QNAME: str = f"{{{SOS_NS}}}invariants"
_EVENT_QNAME: str = f"{{{SOS_NS}}}event"
_MAINTAINED_QNAME: str = f"{{{SOS_NS}}}maintained-by-subchart"
_ASSUMED_QNAME: str = f"{{{SOS_NS}}}assumed-of-environment"


# PCDN-SOS-12-005 / §6.5 / §10.3 default recursion depth cap. Adding to or
# loosening this enum requires a §15 amendment (Specification Required —
# projects MAY override per chart-family via `chart-family.toml`; here we
# accept an explicit constructor `max_depth` keyword).
DEFAULT_MAX_DEPTH: int = 8


# PCDN-SOS-12-001 frozen attribute set for `<sos:dispatch>`. Unknown
# attributes are rejected (Standards Action — adding a new attribute
# requires a §15 amendment).
PERMITTED_DISPATCH_ATTRS: frozenset[str] = frozenset({"ref"})


# PCDN-SOS-12-002 / PCDN-SOS-12-004 frozen attribute set for `<sos:contract>`.
# `reads` and `writes` are space-separated lists of datamodel field names.
PERMITTED_CONTRACT_ATTRS: frozenset[str] = frozenset({"reads", "writes"})


# Permitted child qnames inside `<sos:contract>` (PCDN-SOS-12-004 §5.1).
PERMITTED_CONTRACT_CHILDREN: frozenset[str] = frozenset(
    {_EVENTS_IN_QNAME, _EVENTS_OUT_QNAME, _INVARIANTS_QNAME}
)


# Permitted child qnames inside `<sos:invariants>`.
PERMITTED_INVARIANT_CHILDREN: frozenset[str] = frozenset(
    {_MAINTAINED_QNAME, _ASSUMED_QNAME}
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class Sos12AnnotationError(ValueError):
    """Raised when SOS-12 dispatch / contract annotations are malformed or
    violate frozen invariants.

    Carries an `element_path` (best-effort dotted SCXML id path naming the
    offending parent context) and an optional `rule` token naming which
    SOS-12-CONCEPTS section, PCDN, or INV-S-DISP-* invariant fired, for
    downstream error-reporting tooling (mirrors the shape of
    `Sos09AnnotationError` and `Sos10AnnotationError`).
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
class DispatchAnnotation:
    """One `<sos:dispatch ref="…"/>` annotation extracted from a parent chart.

    Per PCDN-SOS-12-001 / §5.1: a `<sos:dispatch>` element sits inside a
    parent `<state>` element and names the sub-chart that state dispatches
    into. `parent_state_id` is the enclosing `<state id="…"/>`;
    `ref` is the raw attribute value (sub-chart filename or chart-id token);
    `resolved_path` is the absolute filesystem path when the parser was
    given a chart_path anchor and the ref resolves to a file on disk
    (otherwise None — chart-id tokens that don't correspond to a file are
    left for Wave-2's contract-matching verifier to resolve via project
    chart-family configuration).
    """

    parent_state_id: str
    ref: str
    resolved_path: Optional[Path] = None
    # Forward-compat: any non-`ref` attribute the parser surfaces here. Per
    # PCDN-SOS-12-001 unknown attributes are rejected at the parser surface
    # (so `extras` is normally empty); this field exists for parity with
    # SOS-09 / SOS-10 module shape and to surface attributes whose names
    # might be added by a future §15 amendment without the parser having
    # been updated.
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Contract:
    """One sub-chart's `<sos:contract>` four-tuple.

    Per §5.1 / PCDN-SOS-12-002 / PCDN-SOS-12-004 ratification:

    - `events_in` / `events_out` are tuples of event-name strings (closed
      sets per §5.1 per-field requirements).
    - `invariants_maintained` are per-chart invariants the sub-chart's
      bounded-reachability analysis verifies on behalf of its environment.
    - `invariants_assumed` are per-chart invariants the sub-chart assumes
      its environment satisfies; the parent's verification MUST prove
      these at the dispatch boundary.
    - `reads` / `writes` are space-separated field-name token sets carried
      as attributes on `<sos:contract>` per PCDN-SOS-12-002 (per-sub-chart
      explicit `reads="…"`/`writes="…"`).

    Wave-2's contract-matching verifier consumes this object pairwise with
    the parent chart's expected event vocabulary and datamodel grants;
    that comparison is deliberately NOT performed here.
    """

    events_in: tuple[str, ...] = ()
    events_out: tuple[str, ...] = ()
    invariants_maintained: tuple[str, ...] = ()
    invariants_assumed: tuple[str, ...] = ()
    reads: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()


@dataclass(frozen=True)
class DispatchInventory:
    """All SOS-12 annotations extracted from one chart-family rooted at one
    parent chart, plus depth-bounded recursion through every reachable
    sub-chart.

    Fields:

    - `chart_ref` — a stable identifier for the parent chart. When the
      parser was given a `chart_path` anchor this is the filename; when
      driven from raw AST without a path it is `"<root>"`.
    - `dispatches` — every `<sos:dispatch>` found at the parent chart's
      `<state>` tree, in document-order.
    - `contract` — the parent chart's own `<sos:contract>` (None for the
      top-level chart, which is not itself dispatched-into; populated for
      sub-charts whose `<sos:contract>` was parsed during recursion).
    - `sub_inventories` — child DispatchInventory objects, one per
      successfully-resolved sub-chart. Sub-charts whose `ref` could not be
      resolved to a file (no chart_path anchor; or the ref names a token
      rather than a file) appear in `unresolved_refs` instead.
    - `unresolved_refs` — `<sos:dispatch ref="…">` values that the parser
      could not resolve to a file. The Wave-2 contract-matching verifier
      consumes this list to resolve chart-id tokens against project-level
      chart-family configuration. NOT an error condition by itself.
    - `depth` — the recursion depth this inventory sits at (0 for the
      root; +1 per successful dispatch resolution).
    """

    chart_ref: str
    dispatches: tuple[DispatchAnnotation, ...] = ()
    contract: Optional[Contract] = None
    sub_inventories: tuple["DispatchInventory", ...] = ()
    unresolved_refs: tuple[str, ...] = ()
    depth: int = 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _iter_other_elements(node: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the `other_element` list of a scjson node (empty if missing)."""
    elements = node.get("other_element") or []
    if not isinstance(elements, list):
        return []
    return [el for el in elements if isinstance(el, dict)]


def _split_token_list(value: Any, *, attr_name: str, element_path: str) -> tuple[str, ...]:
    """Per PCDN-SOS-12-002: the `reads` / `writes` attributes carry
    whitespace-separated token lists.

    Tokens MUST be non-empty strings; duplicates within one list are
    rejected as chart-author errors (a contract that names the same field
    twice is most likely a typo).
    """
    if value is None or value == "":
        return ()
    if not isinstance(value, str):
        raise Sos12AnnotationError(
            f"<sos:contract {attr_name}={value!r}> must be a string of "
            "whitespace-separated field-name tokens (PCDN-SOS-12-002)",
            element_path=element_path,
            rule="PCDN-SOS-12-002",
        )
    tokens = value.split()
    seen: set[str] = set()
    for tok in tokens:
        if not tok:
            continue
        if tok in seen:
            raise Sos12AnnotationError(
                f"<sos:contract {attr_name}=…> contains duplicate field "
                f"token {tok!r} (PCDN-SOS-12-002 — each field name SHOULD "
                "appear at most once per contract attribute)",
                element_path=element_path,
                rule="PCDN-SOS-12-002",
            )
        seen.add(tok)
    return tuple(tokens)


def _parse_event_list(
    parent_qname: str,
    parent_node: dict[str, Any],
    *,
    element_path: str,
) -> tuple[str, ...]:
    """Parse a `<sos:events-in>` or `<sos:events-out>` child list.

    Each child MUST be a `<sos:event>` element whose `text` holds the
    event name. Unknown children inside an events-in / events-out wrapper
    are rejected (Standards Action — adding a new sub-element requires a
    §15 amendment).
    """
    events: list[str] = []
    seen: set[str] = set()
    for child in parent_node.get("children") or []:
        if not isinstance(child, dict):
            continue
        qn = child.get("qname")
        if qn != _EVENT_QNAME:
            local = parent_qname.rsplit("}", 1)[-1]
            raise Sos12AnnotationError(
                f"<sos:{local}> may only carry <sos:event> children; "
                f"found unexpected child {qn!r}",
                element_path=element_path,
                rule="PCDN-SOS-12-004",
            )
        name = (child.get("text") or "").strip()
        if not name:
            local = parent_qname.rsplit("}", 1)[-1]
            raise Sos12AnnotationError(
                f"<sos:event> inside <sos:{local}> must carry a non-empty "
                "event-name text body",
                element_path=element_path,
                rule="PCDN-SOS-12-004",
            )
        if name in seen:
            local = parent_qname.rsplit("}", 1)[-1]
            raise Sos12AnnotationError(
                f"duplicate event name {name!r} in <sos:{local}>; per §5.1 "
                "events-in / events-out are closed sets",
                element_path=element_path,
                rule="§5.1",
            )
        seen.add(name)
        events.append(name)
    return tuple(events)


def _parse_invariants(
    invariants_node: dict[str, Any],
    *,
    element_path: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Parse the `<sos:invariants>` child of a contract.

    Returns `(maintained, assumed)` tuples. Per §5.1: each child is either
    `<sos:maintained-by-subchart>` or `<sos:assumed-of-environment>`, with
    the invariant id carried as text.
    """
    maintained: list[str] = []
    assumed: list[str] = []
    for child in invariants_node.get("children") or []:
        if not isinstance(child, dict):
            continue
        qn = child.get("qname")
        if qn not in PERMITTED_INVARIANT_CHILDREN:
            raise Sos12AnnotationError(
                f"<sos:invariants> may only carry "
                f"<sos:maintained-by-subchart> or "
                f"<sos:assumed-of-environment> children; found {qn!r}",
                element_path=element_path,
                rule="PCDN-SOS-12-004",
            )
        inv_id = (child.get("text") or "").strip()
        if not inv_id:
            local = qn.rsplit("}", 1)[-1]
            raise Sos12AnnotationError(
                f"<sos:{local}> must carry a non-empty invariant-id text body",
                element_path=element_path,
                rule="PCDN-SOS-12-004",
            )
        if qn == _MAINTAINED_QNAME:
            maintained.append(inv_id)
        else:
            assumed.append(inv_id)
    return tuple(maintained), tuple(assumed)


def _parse_contract_element(
    contract_node: dict[str, Any],
    *,
    element_path: str,
) -> Contract:
    """Parse one `<sos:contract>` element into a typed Contract dataclass.

    Per PCDN-SOS-12-002 (ratified): `reads` and `writes` are explicit
    space-separated field-name attributes on the `<sos:contract>` element
    itself; unknown attributes raise (frozen attribute set).

    Per PCDN-SOS-12-004 (ratified): `<sos:contract>` carries optional
    children `<sos:events-in>`, `<sos:events-out>`, `<sos:invariants>`
    (zero-or-one of each).
    """
    attrs = contract_node.get("attributes") or {}
    if not isinstance(attrs, dict):
        raise Sos12AnnotationError(
            "<sos:contract>.attributes must be a dict",
            element_path=element_path,
            rule="PCDN-SOS-12-004",
        )
    unknown_attrs = sorted(set(attrs) - PERMITTED_CONTRACT_ATTRS)
    if unknown_attrs:
        raise Sos12AnnotationError(
            f"<sos:contract> carries unknown attribute(s) {unknown_attrs!r}; "
            f"permitted set is {sorted(PERMITTED_CONTRACT_ATTRS)} per "
            "PCDN-SOS-12-002 (Standards Action — adding a new attribute "
            "requires a §15 amendment to SOS-12-CONCEPTS.md)",
            element_path=element_path,
            rule="PCDN-SOS-12-002",
        )

    reads = _split_token_list(
        attrs.get("reads"), attr_name="reads", element_path=element_path
    )
    writes = _split_token_list(
        attrs.get("writes"), attr_name="writes", element_path=element_path
    )

    events_in: tuple[str, ...] = ()
    events_out: tuple[str, ...] = ()
    invariants_maintained: tuple[str, ...] = ()
    invariants_assumed: tuple[str, ...] = ()

    seen_children: set[str] = set()
    for child in contract_node.get("children") or []:
        if not isinstance(child, dict):
            continue
        qn = child.get("qname")
        if qn not in PERMITTED_CONTRACT_CHILDREN:
            raise Sos12AnnotationError(
                f"<sos:contract> may only carry <sos:events-in>, "
                f"<sos:events-out>, or <sos:invariants> children; "
                f"found {qn!r}",
                element_path=element_path,
                rule="PCDN-SOS-12-004",
            )
        if qn in seen_children:
            local = qn.rsplit("}", 1)[-1]
            raise Sos12AnnotationError(
                f"<sos:contract> carries multiple <sos:{local}> children; "
                "at most one of each is permitted",
                element_path=element_path,
                rule="PCDN-SOS-12-004",
            )
        seen_children.add(qn)

        if qn == _EVENTS_IN_QNAME:
            events_in = _parse_event_list(qn, child, element_path=element_path)
        elif qn == _EVENTS_OUT_QNAME:
            events_out = _parse_event_list(qn, child, element_path=element_path)
        elif qn == _INVARIANTS_QNAME:
            invariants_maintained, invariants_assumed = _parse_invariants(
                child, element_path=element_path
            )

    return Contract(
        events_in=events_in,
        events_out=events_out,
        invariants_maintained=invariants_maintained,
        invariants_assumed=invariants_assumed,
        reads=reads,
        writes=writes,
    )


def _find_chart_root_contract(
    root: dict[str, Any],
    *,
    element_path: str,
) -> Optional[Contract]:
    """Locate the chart-root `<sos:contract>` element, if any.

    Per PCDN-SOS-12-004: a sub-chart MAY declare its contract via a
    `<sos:contract>` element directly under `<scxml>`. Multiple
    contracts at chart root are rejected as a chart-author error.
    """
    contracts = [
        el for el in _iter_other_elements(root)
        if el.get("qname") == _CONTRACT_QNAME
    ]
    if len(contracts) > 1:
        raise Sos12AnnotationError(
            f"chart root carries {len(contracts)} <sos:contract> "
            "elements; at most one is permitted (PCDN-SOS-12-004)",
            element_path=element_path,
            rule="PCDN-SOS-12-004",
        )
    if not contracts:
        return None
    return _parse_contract_element(contracts[0], element_path=element_path)


def _walk_state_tree_for_dispatches(
    node: dict[str, Any],
    *,
    parent_path: str,
    out: list[DispatchAnnotation],
    chart_dir: Optional[Path],
) -> None:
    """Depth-first walk of `<state>` / `<parallel>` children, emitting one
    DispatchAnnotation per `<sos:dispatch>` found.

    Per PCDN-SOS-12-001: `<sos:dispatch>` is permitted only inside a
    `<state>` element (the dispatched state). A `<sos:dispatch>` inside a
    `<parallel>` or other element is rejected.
    """
    for st in node.get("state", []) or []:
        if not isinstance(st, dict):
            continue
        sid = st.get("id") or "<anonymous>"
        element_path = f"{parent_path}.{sid}" if parent_path else sid

        for el in _iter_other_elements(st):
            qn = el.get("qname")
            if qn != _DISPATCH_QNAME:
                # Forward-compat: other foreign elements on a state are
                # ignored here (they may belong to SOS-08-D / -E or future
                # phases). This parser owns ONLY `<sos:dispatch>`.
                continue
            ann = _parse_dispatch_element(
                el, parent_state_id=element_path, chart_dir=chart_dir
            )
            out.append(ann)

        _walk_state_tree_for_dispatches(
            st, parent_path=element_path, out=out, chart_dir=chart_dir,
        )

    for par in node.get("parallel", []) or []:
        if not isinstance(par, dict):
            continue
        pid = par.get("id") or "<anonymous-parallel>"
        element_path = f"{parent_path}.{pid}" if parent_path else pid
        # `<sos:dispatch>` directly on a `<parallel>` is rejected — per
        # §5.1 dispatched states are sequential composition. Cross-region
        # orchestration uses SOS-10's `<sos:medium>` surface, not SOS-12.
        for el in _iter_other_elements(par):
            qn = el.get("qname")
            if qn == _DISPATCH_QNAME:
                raise Sos12AnnotationError(
                    "<sos:dispatch> is not permitted on a <parallel> "
                    "element; per PCDN-SOS-12-001 / §5.1 dispatched states "
                    "are sequential composition. Place the dispatch inside "
                    "one of the parallel's child <state> elements.",
                    element_path=element_path,
                    rule="PCDN-SOS-12-001",
                )
        _walk_state_tree_for_dispatches(
            par, parent_path=element_path, out=out, chart_dir=chart_dir,
        )


def _parse_dispatch_element(
    el: dict[str, Any],
    *,
    parent_state_id: str,
    chart_dir: Optional[Path],
) -> DispatchAnnotation:
    """Parse one `<sos:dispatch ref="…"/>` element.

    Per PCDN-SOS-12-001: the only permitted attribute is `ref`. Unknown
    attributes raise (Standards Action). When chart_dir is provided, a
    ref ending in a path-like form is resolved against it; the resolved
    path is recorded for the recursion walk to consume.
    """
    attrs = el.get("attributes") or {}
    if not isinstance(attrs, dict):
        raise Sos12AnnotationError(
            "<sos:dispatch>.attributes must be a dict",
            element_path=parent_state_id,
            rule="PCDN-SOS-12-001",
        )
    unknown = sorted(set(attrs) - PERMITTED_DISPATCH_ATTRS)
    if unknown:
        raise Sos12AnnotationError(
            f"<sos:dispatch> carries unknown attribute(s) {unknown!r}; "
            f"permitted set is {sorted(PERMITTED_DISPATCH_ATTRS)} per "
            "PCDN-SOS-12-001 (Standards Action — adding a new attribute "
            "requires a §15 amendment to SOS-12-CONCEPTS.md)",
            element_path=parent_state_id,
            rule="PCDN-SOS-12-001",
        )
    ref = attrs.get("ref")
    if not isinstance(ref, str) or not ref.strip():
        raise Sos12AnnotationError(
            f"<sos:dispatch ref=…> requires a non-empty `ref` attribute; "
            f"got {ref!r}",
            element_path=parent_state_id,
            rule="PCDN-SOS-12-001",
        )

    # Resolution policy: when the caller has anchored the parent chart on
    # disk via chart_path → chart_dir, we ALWAYS produce a candidate
    # resolved_path (chart_dir / ref). The downstream loader is then
    # responsible for raising FileNotFoundError if the file is absent
    # (the default loader, which shells out to scjson, surfaces a
    # FileNotFoundError early). Tests that supply a custom loader can
    # intercept the path arbitrarily — including for refs whose backing
    # file does not exist on disk. When chart_dir is None (no anchor)
    # we have no way to resolve the ref to a path, so it goes to the
    # parent inventory's `unresolved_refs` list for Wave-2 chart-id-token
    # resolution to handle.
    resolved: Optional[Path] = None
    if chart_dir is not None:
        resolved = (chart_dir / ref.strip()).resolve()

    return DispatchAnnotation(
        parent_state_id=parent_state_id,
        ref=ref.strip(),
        resolved_path=resolved,
    )


def _default_loader(path: Path) -> dict:
    """Default sub-chart loader used by `parse_dispatch_annotations`.

    Lazy-imports the loader module so the parser is importable in
    environments where `scjson` is not installed (e.g. unit tests that
    drive the parser directly with synthetic AST dicts).
    """
    import importlib  # local import keeps the module's import cost low
    import sys as _sys
    from pathlib import Path as _P
    here = _P(__file__).resolve().parent
    if str(here) not in _sys.path:
        _sys.path.insert(0, str(here))
    loader_mod = importlib.import_module("loader")
    ast_obj = loader_mod.load_chart(path)
    return ast_obj.raw_scjson  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_dispatch_annotations(
    ast: dict,
    *,
    chart_path: Optional[Path] = None,
    max_depth: int = DEFAULT_MAX_DEPTH,
    loader: Optional[Callable[[Path], dict]] = None,
    _current_depth: int = 0,
    _seen_paths: Optional[set[Path]] = None,
) -> DispatchInventory:
    """Walk a scjson chart AST and return a typed dispatch + contract
    inventory.

    Arguments:
        ast — the dict surfaced by `loader.load_chart(...).raw_scjson`
            (or any equivalent scjson-shape dict). The root represents
            the chart's `<scxml>` element.
        chart_path — absolute path of the chart on disk. Required for
            dispatch-tree recursion (the parser resolves `<sos:dispatch
            ref="…">` against this directory). Optional when the caller
            only wants per-chart annotations without recursion.
        max_depth — recursion-depth cap per PCDN-SOS-12-005 / §6.5 /
            §10.3. Default 8. The cap counts dispatch-tree depth; depth
            0 is the root chart, depth 1 is a directly-dispatched
            sub-chart, etc. A chart whose dispatches would produce a
            child at depth > max_depth raises an error citing
            INV-S-DISP-5 / §6.5.
        loader — optional override for the sub-chart loader. Default
            shells out to scjson via `loader.load_chart`. Tests supply
            a synthetic loader to drive recursion without touching disk.

    Returns:
        DispatchInventory rooted at the chart, with recursive
        sub-inventories for every successfully-resolved `<sos:dispatch
        ref="…">` reference. Unresolvable refs (no chart_path anchor, or
        ref naming a chart-id token) appear in `unresolved_refs` and do
        NOT count toward the depth cap (they have no measurable depth).

    Raises:
        Sos12AnnotationError on any annotation-shape violation or on
        depth-cap overrun. The first violation encountered is raised;
        subsequent violations are not aggregated (chart-author errors
        are typically addressed one at a time, per the precedent of
        SOS-09-A / SOS-10 annotation parsers).
    """
    if not isinstance(ast, dict):
        raise Sos12AnnotationError(
            f"ast must be a dict; got {type(ast).__name__}",
            rule="parse",
        )
    if _seen_paths is None:
        _seen_paths = set()

    chart_dir: Optional[Path] = None
    chart_ref: str = "<root>"
    if chart_path is not None:
        chart_path = chart_path.resolve()
        chart_dir = chart_path.parent
        chart_ref = chart_path.name
        # INV-S-DISP-3 acyclicity check at the parser layer: revisiting
        # the same chart file during a single dispatch walk is the
        # canonical cycle shape. We surface it as a parser error rather
        # than letting recursion blow the depth cap, because the error
        # message is more actionable.
        if chart_path in _seen_paths:
            raise Sos12AnnotationError(
                f"dispatch-tree cycle detected at {chart_ref!r}; the same "
                "chart file is reached twice along one root→leaf walk "
                "(INV-S-DISP-3 — dispatch-tree MUST be a DAG)",
                element_path=chart_ref,
                rule="INV-S-DISP-3",
            )
        _seen_paths = _seen_paths | {chart_path}

    contract = _find_chart_root_contract(ast, element_path=chart_ref)

    dispatches: list[DispatchAnnotation] = []
    _walk_state_tree_for_dispatches(
        ast, parent_path="", out=dispatches, chart_dir=chart_dir,
    )

    # Depth-cap check BEFORE we recurse. The depth of a child inventory
    # is _current_depth + 1; if that exceeds max_depth we reject HERE
    # with a chart-author-friendly diagnostic naming the offending
    # dispatch site.
    if dispatches and _current_depth + 1 > max_depth:
        offender = dispatches[0]
        raise Sos12AnnotationError(
            f"dispatch-tree depth would exceed cap max_depth={max_depth} "
            f"at parent_state={offender.parent_state_id!r} dispatching to "
            f"{offender.ref!r} (depth would be {_current_depth + 1}; cap "
            f"per PCDN-SOS-12-005 / §6.5 / INV-S-DISP-5). Project chart-"
            f"families MAY override the cap via the `max_depth` parameter "
            "or chart-family.toml `recursion_depth_limit`.",
            element_path=offender.parent_state_id,
            rule="§6.5",
        )

    sub_inventories: list[DispatchInventory] = []
    unresolved: list[str] = []
    if loader is None:
        loader = _default_loader

    for d in dispatches:
        if d.resolved_path is None:
            unresolved.append(d.ref)
            continue
        sub_ast = loader(d.resolved_path)
        sub_inv = parse_dispatch_annotations(
            sub_ast,
            chart_path=d.resolved_path,
            max_depth=max_depth,
            loader=loader,
            _current_depth=_current_depth + 1,
            _seen_paths=_seen_paths,
        )
        sub_inventories.append(sub_inv)

    return DispatchInventory(
        chart_ref=chart_ref,
        dispatches=tuple(dispatches),
        contract=contract,
        sub_inventories=tuple(sub_inventories),
        unresolved_refs=tuple(unresolved),
        depth=_current_depth,
    )


# ---------------------------------------------------------------------------
# Wave-1B / Wave-2 extension points
# ---------------------------------------------------------------------------
#
# This module deliberately stops at parsing + structural validation +
# depth-cap enforcement. The following extension surfaces are reserved for
# downstream phases and SHOULD NOT be added here:
#
# 1. Bound composition (Wave-1B / §6 algebra). Consume `DispatchInventory`
#    recursively: bound(family) = bound(parent_chart) + sum(bound(s) for s in
#    sub_inventories). The per-chart bound (= |reachable_states(C)|) is the
#    SOS-03 vector framework's responsibility; sum-not-product across the
#    dispatch-tree is the operational realisation of INV-SOS-F per §6.3.
#
# 2. Contract matching (Wave-2 / §5.3 PCDN-SOS-12-006 ratified as compile-
#    time error). Consume both `DispatchInventory.dispatches` (parent chart's
#    declared sub-charts) and each `DispatchInventory.contract` (sub-chart's
#    declared contract). For each (parent_dispatch, sub_inventory) pair,
#    verify: (a) every event the parent routes into the dispatched state
#    appears in `sub.contract.events_in`; (b) every event the parent
#    expects out appears in `sub.contract.events_out`; (c) the parent's
#    datamodel grants imply `sub.contract.reads ⊆ grants_read` and
#    `sub.contract.writes ⊆ grants_write`; (d) the parent's invariants
#    imply `sub.contract.invariants_assumed`. The §5.3 / INV-S-DISP-2
#    contract-mismatch failure mode at v1 is compile-time error.
#
# 3. Boundary vector emission (downstream of contract-match verifier per
#    §7.2). Generate constant-size vector sets per dispatch boundary that
#    test event-in, event-out, datamodel-boundary, and assumed-invariant
#    discharge — without enumerating the sub-chart's internal states
#    (INV-S-DISP-1 — no replay across layers).
#
# Each downstream consumer SHOULD cite SOS-12-CONCEPTS.md §X in its own
# §15 entry when it lands, per the Spec-Before-Code discipline.

__all__ = [
    "Contract",
    "DispatchAnnotation",
    "DispatchInventory",
    "Sos12AnnotationError",
    "parse_dispatch_annotations",
    # Frozen enums exported for downstream emitters that want to mirror them.
    "DEFAULT_MAX_DEPTH",
    "PERMITTED_DISPATCH_ATTRS",
    "PERMITTED_CONTRACT_ATTRS",
    "PERMITTED_CONTRACT_CHILDREN",
    "PERMITTED_INVARIANT_CHILDREN",
    "SOS_NS",
]
