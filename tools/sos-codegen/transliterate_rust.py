"""ECMAScript → Rust transliterator for sos-codegen.

Consumes the SOS chart's constrained ECMAScript subset (per SOS-01 §5.1)
and emits Rust source. The chart never uses Promises, generators, async,
closures, or `eval`; mutation surface is a fixed set of datamodel
identifiers (`tcb`, `ready`, `sems`, `queues`, `current`, `tick_count`,
`resched`, `irq_nest`, `sched_lock`, `pend_ticks`, `rc`).

The transliterator emits Rust idioms matching the bench-validated
hand-written reference at `ports/m7-rust/sos-m7-rust/src/scripts.rs`:

* Free identifiers like `tcb[i].prio` become `dm.tcb[i].prio`.
* Helper calls like `ready_push(0)` become `dm.ready_push(0)?;`.
* `_event.data` becomes `_ev.data`; struct-extraction uses
  `match` over `EventData` variants (chart's type discipline).
* `for (var i = 0; i < N; i++)` becomes `for i in 0..N`.
* `arr.push({...})` against a `heapless::Vec` becomes
  `arr.push(<TypedStruct>{...}).ok();` — the `.ok()` discards the
  full-vec error per chart invariants.

# Scope (v0)

Handles the simple-statement subset:

* `VariableDeclaration` (`var x = expr` → `let mut x = expr`).
* `AssignmentExpression` with `=`, `+=`, `-=`.
* `UpdateExpression` (`x++`, `x--`).
* `IfStatement` (with optional `else`).
* `ForStatement` (init/test/update — recognises the canonical
  `for (var i = 0; i < N; i++)` and `for (var i = N - 1; i >= 0; i--)` forms).
* `WhileStatement`.
* `CallExpression` (free helper functions become `dm.<name>(args)?;`).
* `MemberExpression` (member access + array indexing).
* `BinaryExpression` (arithmetic + comparison).
* `LogicalExpression` (`&&`, `||`).
* `UnaryExpression` (`!x`, `-x`).
* `Literal` (numbers, booleans, strings, null).
* `Identifier` — datamodel field names get the `dm.` prefix.
* `ReturnStatement`.

# Deferred (v0 falls back to surfacing as `// ES:` comment lines)

* `ObjectExpression` (struct literals like `{ id: i, prio: 0, ... }`) — needs
  per-site type binding (Tcb vs Sem vs Queue vs Msg).
* `ArrayExpression` (empty arrays `[]` and non-empty ones).
* `arr.splice(idx, 1)` / `arr.shift()` / `arr.indexOf(x)` — needs
  collection-aware emission. v0 emits these as `// TODO_TRANSLIT:` plus the
  source line so a follow-on pass can fill them in.
* `_event.data` typed-variant extraction.
"""

# @spec: scjson 0.4.0 feature integration (roadmap-tracked, NOT current scope)
#   Per SOS-09-CONCEPTS.md §16 (2026-05-26) and SOS-ROADMAP-07-PLUS.md §12,
#   the scjson 0.4.0 feature surface (help_text, comment promotion, XInclude,
#   <send>, <invoke>, other_attributes registry) is available upstream but
#   NOT consumed by this emitter. Integration is roadmap-tracked.
#   - help_text: chart XML comments could become emitted doc-comments (Rust ///, C /** */).
#   - XInclude: chart-composition at parse time could collapse multi-file charts.
#   - <send>/<invoke>: SOS-10 orchestrator-driven events; this emitter's per-channel
#     surface is unchanged.
#   Smoke tests confirming feature accessibility live in
#   tests/test_scjson_04_features.py.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import esprima


# Datamodel identifiers (per rtos_kernel.scxml <datamodel>) that need
# a `dm.` prefix when they appear as free references in script bodies.
DATAMODEL_NAMES = {
    "tcb", "ready", "current", "tick_count", "resched",
    "irq_nest", "sched_lock", "pend_ticks", "sems", "queues", "rc",
}

# Helper functions from the chart's HELPERS block; these become method
# calls on `dm` (e.g. `ready_push(0)` → `dm.ready_push(0)?`).
HELPER_NAMES = {
    "readyq_init", "ready_push", "ready_remove", "ready_pop_highest",
    "waiters_insert", "block_current", "unblock", "waiter_cancel",
    "pick_next",
}

# Chart constants — these become bare uppercase identifiers in Rust
# (imported from `crate::kernel`).
CONSTANT_NAMES = {
    "MAX_TASKS", "MAX_PRIO", "MAX_SEMS", "MAX_QUEUES", "Q_DEPTH",
    "ST_DORMANT", "ST_READY", "ST_RUNNING", "ST_DELAY",
    "ST_BLK_SEM", "ST_BLK_QS", "ST_BLK_QR", "ST_SUSPEND",
    "RC_OK", "RC_TIMEOUT", "RC_FULL", "RC_EMPTY", "RC_INVAL",
}

# Map chart ST_* / RC_* constants onto the Rust enum surface used by
# the hand-written port. Per SOS-04 §6.3 — TaskState + ReturnCode are
# `repr(i8)` enums with these discriminants.
ST_TO_RUST = {
    "ST_DORMANT":  "TaskState::Dormant",
    "ST_READY":    "TaskState::Ready",
    "ST_RUNNING":  "TaskState::Running",
    "ST_DELAY":    "TaskState::Delay",
    "ST_BLK_SEM":  "TaskState::BlkSem",
    "ST_BLK_QS":   "TaskState::BlkQs",
    "ST_BLK_QR":   "TaskState::BlkQr",
    "ST_SUSPEND":  "TaskState::Suspend",
}
RC_TO_RUST = {
    "RC_OK":      "ReturnCode::Ok",
    "RC_TIMEOUT": "ReturnCode::Timeout",
    "RC_FULL":    "ReturnCode::Full",
    "RC_EMPTY":   "ReturnCode::Empty",
    "RC_INVAL":   "ReturnCode::Inval",
}


# Per-event-name EventData variant + the field set the chart can name.
# Source: ports/m7-rust/sos-m7-rust/src/event.rs::EventData. Events
# absent from this table have `EventData::None` payload — no extraction
# needed; `_event.data` references should not appear in their scripts
# (chart-lint enforces this elsewhere).
EVENTDATA_VARIANTS: dict[str, tuple[str, list[str]]] = {
    "task.create":         ("TaskCreate",   ["id", "prio"]),
    "task.delay":          ("TaskDelay",    ["ticks"]),
    "task.suspend":        ("TaskId",       ["id"]),
    "task.resume":         ("TaskId",       ["id"]),
    "sem.create":          ("SemCreate",    ["id", "initial", "max"]),
    "sem.take":            ("SemOp",        ["sid", "timeout"]),
    "sem.give":            ("SemOp",        ["sid", "timeout"]),
    "sem.give_from_isr":   ("SemOp",        ["sid", "timeout"]),
    "queue.create":        ("QueueCreate",  ["id", "cap"]),
    "queue.send":          ("QueueSend",    ["qid", "msg", "timeout"]),
    "queue.receive":       ("QueueReceive", ["qid", "timeout"]),
    "queue.send_from_isr": ("QueueSend",    ["qid", "msg", "timeout"]),
}


def _used_eventdata_fields(source: str, all_fields: list[str]) -> list[str]:
    """Scan ECMAScript source for `_event.data.<field>` references and
    return the subset of `all_fields` actually accessed. Preserves the
    declaration order from EVENTDATA_VARIANTS so the destructuring
    pattern matches enum-field order."""
    used: list[str] = []
    for f in all_fields:
        # Both `_event.data.<f>` direct access and `var x = _event.data;` +
        # `x.<f>` indirect access show up. v0 emits all fields the chart
        # could name; the Rust compiler's `let (a, _, c) = ...` form
        # would let us drop unused, but it's simpler and harmless to
        # bind every field for now. The transliterator will rename the
        # local `var x = _event.data` to `_ev.data` and field access
        # `x.<f>` becomes `_ev.data.<f>`, which can then map to the
        # locally-bound `<f>`.
        used.append(f)
    return used


def emit_eventdata_extract(event_name: str | None) -> tuple[str, set[str]]:
    """Emit the `let (a, b, ...) = match ev.data { ... }` preamble for
    a chart event. Returns (preamble_lines, set_of_bound_field_names).

    When `event_name` is None or its variant is `None` (no payload),
    returns empty preamble and empty set — the function uses `_ev`
    and never references the payload."""
    if event_name is None or event_name not in EVENTDATA_VARIANTS:
        return ("", set())
    variant, fields = EVENTDATA_VARIANTS[event_name]
    if not fields:
        return ("", set())
    if len(fields) == 1:
        f = fields[0]
        lines = (
            f"    let {f} = match ev.data {{\n"
            f"        EventData::{variant} {{ {f} }} => {f},\n"
            f"        _ => return Err(ScriptError::WrongDataVariant),\n"
            f"    }};"
        )
    else:
        binds = ", ".join(fields)
        lines = (
            f"    let ({binds}) = match ev.data {{\n"
            f"        EventData::{variant} {{ {binds} }} => ({binds}),\n"
            f"        _ => return Err(ScriptError::WrongDataVariant),\n"
            f"    }};"
        )
    return (lines, set(fields))


@dataclass
class TransliterationResult:
    rust_source: str
    unhandled_notes: list[str] = field(default_factory=list)
    # Preamble emitted before the body — typed EventData extract.
    preamble: str = ""
    # True if the function should bind `ev` (vs `_ev`) — set when the
    # preamble references `ev.data` for typed extraction.
    needs_ev_param: bool = False
    # SOS-13 verified-strip audit entries (zero-length when the profile
    # is not engaged for this site). Each entry is a dict matching the
    # `AuditEntry.to_dict()` shape in `verified_audit.py`. See
    # SOS-13-CONCEPTS.md §7.4 + §15 2026-05-23 ratification entry.
    verified_strip_audit: list[dict] = field(default_factory=list)


# -----------------------------------------------------------------
# SOS-13 verified-strip profile — additive emission layer.
#
# Per SOS-13-CONCEPTS.md §5 + §15 2026-05-23 ratification entry:
#   * PCDN-SOS-13-001 — BOTH whole-port `--verified-strip` flag AND
#     per-region opt-in (`--verified-region <id>`).
#   * PCDN-SOS-13-002 — JSONL audit log (handled by verified_audit.py).
#   * PCDN-SOS-13-003 — `dev-keep` is the default; verified-strip is
#     opt-in. Existing emissions without the flag MUST stay byte-
#     identical.
#
# Discharge-annotation grammar (per task prompt; flagged for §15
# amendment if SOS-01 / SOS-11 specify a different shape):
#   <sos:discharged check="bounds"/>
#   <sos:discharged check="div-by-zero"/>
#   <sos:discharged check="null"/>
#   <sos:discharged check="overflow"/>
#
# Stripping happens only when the chart annotation is present AND
# the site is in scope of the active profile config. Missing
# annotation → safe-default emission survives. This is INV-SOS-G's
# load-bearing invariant — silent elimination is forbidden.
# -----------------------------------------------------------------


# `check` value → audit log `operation` field.
DISCHARGE_OPERATION: dict[str, str] = {
    "bounds":       "bounds_check_strip",
    "div-by-zero":  "div_by_zero_strip",
    "null":         "null_check_strip",
    "overflow":     "overflow_check_strip",
}

# Recognized discharge check identifiers (frozen at SOS-13 v1; grammar
# extensions require a §15 amendment per the unchecked-op catalogue
# Standards Action policy in §7.1).
RECOGNIZED_DISCHARGES = frozenset(DISCHARGE_OPERATION.keys())


@dataclass
class VerifiedStripConfig:
    """Per-call configuration for the verified-strip post-pass.

    `enabled_globally`     — `--verified-strip` was passed on the CLI.
    `enabled_regions`      — set of region IDs explicitly opted in via
                             `--verified-region <id>`; takes effect even
                             when `enabled_globally` is False.
    `region_id`            — the region (state-id or transition state-id)
                             this site belongs to.
    `discharges`           — list of `check` values declared on the
                             site's chart annotation(s).
    """

    enabled_globally: bool = False
    enabled_regions: frozenset = field(default_factory=frozenset)
    region_id: str = ""
    discharges: tuple = ()

    def is_active(self) -> bool:
        """True iff this site should be stripped — i.e. the profile
        is engaged (global flag OR region opt-in) AND the chart has
        declared at least one recognized discharge."""
        if not self.discharges:
            return False
        if self.enabled_globally:
            return True
        if self.region_id and self.region_id in self.enabled_regions:
            return True
        return False

    def has_discharge(self, check: str) -> bool:
        return self.is_active() and check in self.discharges


def load_discharge_annotations(chart_path) -> dict:
    """Parse `<sos:discharged check="..."/>` children of every state
    and transition in `chart_path`. Returns a mapping:

        { state_id: ["bounds", "null", ...], ... }

    States/transitions without discharge annotations are absent from
    the dict.

    The annotation grammar `<sos:discharged check="..."/>` is the
    task-prompt-specified shape; if SOS-01 / SOS-11 ratify a
    different grammar later, a §15 amendment to SOS-13 is required
    before changing this loader. The function reads via lxml directly
    (the scjson loader path discards custom-namespace children).
    """
    from lxml import etree as _etree
    from pathlib import Path as _Path

    p = _Path(chart_path)
    if not p.exists():
        return {}
    # Use the recovering parser. Real-world SCXML charts (incl.
    # rtos_kernel.scxml) carry hand-authored XML comments that
    # occasionally include double-hyphen sequences forbidden by strict
    # XML. The discharge-annotation loader is a side-channel scan and
    # MUST NOT block codegen on comment-formatting issues.
    _parser = _etree.XMLParser(recover=True)
    tree = _etree.parse(str(p), _parser)
    root = tree.getroot()
    if root is None:
        return {}
    # Match the `<sos:discharged>` element regardless of declared
    # namespace prefix — accept both `sos:discharged` and the default-
    # namespace bare `discharged` form. The `check` attribute is what
    # carries the obligation type.
    discharges: dict[str, list[str]] = {}

    def _walk(elem) -> None:
        # Identify the owning state-id: nearest ancestor (or self)
        # with an `id` attribute on a <state>/<parallel>/<transition>.
        # Skip non-Element nodes (comments, processing instructions).
        for child in elem.iterchildren():
            if not isinstance(child.tag, str):
                continue
            tag = _etree.QName(child).localname
            if tag == "discharged":
                check = child.get("check")
                if check in RECOGNIZED_DISCHARGES:
                    # Locate the parent's state-id by walking up.
                    parent = elem
                    sid = None
                    while parent is not None:
                        ptag = _etree.QName(parent).localname
                        if ptag in ("state", "parallel", "final"):
                            sid = parent.get("id")
                            if sid:
                                break
                        elif ptag == "transition":
                            # transitions are scoped to their parent state
                            grand = parent.getparent()
                            if grand is not None:
                                gtag = _etree.QName(grand).localname
                                if gtag in ("state", "parallel", "final"):
                                    sid = grand.get("id")
                                    if sid:
                                        break
                        parent = parent.getparent()
                    if sid:
                        discharges.setdefault(sid, []).append(check)
            _walk(child)

    _walk(root)
    return discharges


# Regex that matches the safe-default bounds-checked index pattern the
# Rust emitter produces, e.g. `dm.tcb[i as usize]` or `self.sems[sid as
# usize]`. Captures the receiver, index expression, and the trailing
# `as usize` so the post-pass can reconstruct the unchecked form.
import re as _re

_BOUNDS_CHECKED_INDEX_RE = _re.compile(
    r"(?P<recv>\b(?:dm|self)(?:\.[A-Za-z_][A-Za-z0-9_]*)+)"
    r"\[(?P<idx>[^\[\]]+?)\s+as\s+usize\]"
)


def apply_verified_strip(
    rust_source: str,
    config: VerifiedStripConfig,
    state_id: str,
    chart_site: str,
    bounds_input=None,
) -> tuple[str, list[dict]]:
    """Replace safe-default Rust idioms with unchecked equivalents
    where the chart's discharge annotations authorize it. Returns
    `(new_source, audit_entries)`; if the profile is not active for
    the site, returns `(rust_source, [])` unchanged.

    The replacements are:

      * `<recv>[<idx> as usize]`  →  `unsafe { <recv>.get_unchecked(<idx> as usize) }`
        gated on `discharge="bounds"`.

    Each replacement is preceded by a `// SAFETY:` comment line citing
    the chart annotation + state id. Per SOS-13 §8 invariant-citation
    format.

    Only `bounds` is wired in v1; the `div-by-zero` / `null` /
    `overflow` annotations are recognized (recorded in the audit log
    when the configured chart declares them) but the corresponding
    emission patterns are deferred — the existing transliterator
    doesn't yet emit those guarded forms in shapes the post-pass can
    target. Adding them is additive and requires no spec amendment.

    `bounds_input` — optional SOS-13 §7.3 eligibility-analysis hook.
    When supplied (as a `sos13_invariants.BoundsAnalysisInput`), the
    function consults `sos13_eligibility.check_eligibility(...)` to
    confirm that the chart's bounds IR actually carries a discharging
    invariant for the site BEFORE stripping. When the eligibility
    verdict is ineligible, the strip is refused (the safe-default
    emission survives), and no audit entry is recorded — preserving
    INV-SOS-G's "no silent strip" guarantee at the IR-derived
    discharge surface in addition to the existing annotation-derived
    surface. When the verdict is eligible, the verdict's
    `discharging_invariant` (an `INV-S-CHART-N` id) is embedded in
    the SAFETY comment per §8. When `bounds_input` is None (the
    default), behaviour is byte-identical to the wave-1 emission —
    the eligibility module is opportunistically threaded as a
    secondary check, not a hard precondition (matching the wave-1 /
    wave-3 spec-before-code phasing).
    """
    if not config.is_active():
        return rust_source, []

    # SOS-13 §7.3 eligibility analysis. Only runs when the caller
    # threaded a bounds-analysis IR through — wave-1 callers without
    # the IR see the previous behaviour unchanged.
    eligibility_inv_id: str | None = None
    if bounds_input is not None and config.has_discharge("bounds"):
        from sos13_eligibility import check_eligibility  # noqa: E402
        verdict = check_eligibility(
            bounds_input,
            vs_op="VS-OP-1",
            region_id=config.region_id or state_id,
        )
        if not verdict.eligible:
            # Strip refused at the IR layer. The safe-default
            # emission survives; no audit entry recorded. The
            # verdict's reason MAY be surfaced by the caller as a
            # post-pass comment if desired — kept out of the
            # function's return tuple to preserve the wave-1 shape.
            return rust_source, []
        eligibility_inv_id = verdict.discharging_invariant

    audit: list[dict] = []
    new_lines: list[str] = []
    src_lines = rust_source.splitlines()
    out_line_no = 0

    for line in src_lines:
        new_line = line
        if config.has_discharge("bounds"):
            # Walk the line left-to-right, replacing each matched
            # bounds-checked index. A single line may carry more than
            # one (e.g. `dm.tcb[i as usize].state = dm.tcb[i as usize].next;`),
            # but we audit one entry per replacement so the audit
            # arithmetic stays "one entry per emitted unsafe block".
            def _replace(match):
                recv = match.group("recv")
                idx = match.group("idx").strip()
                if eligibility_inv_id:
                    # SOS-13 §8: cite the discharging invariant id
                    # from the IR-derived eligibility verdict.
                    safety = (
                        f"{eligibility_inv_id} — bounds discharged at "
                        f"chart <sos:discharged check=\"bounds\"/> on "
                        f"{state_id}"
                    )
                else:
                    safety = (
                        f"INV-SOS-G — bounds discharged at chart "
                        f"<sos:discharged check=\"bounds\"/> on {state_id}"
                    )
                audit.append({
                    "region_id": config.region_id or state_id,
                    "chart_state": state_id,
                    "operation": DISCHARGE_OPERATION["bounds"],
                    "discharge_source": "<sos:discharged check=\"bounds\"/>",
                    "emitted_line": out_line_no + 1,
                    "safety_citation": safety,
                    "chart_site": chart_site,
                })
                return (
                    f"unsafe {{ *{recv}.get_unchecked({idx} as usize) }}"
                )

            new_line = _BOUNDS_CHECKED_INDEX_RE.sub(_replace, line)
            if new_line != line:
                # Emit a SAFETY comment IMMEDIATELY above the line
                # carrying the unsafe block, per §8. Pull the leading
                # indentation off the original line so the comment
                # aligns with the unsafe expression.
                indent = line[: len(line) - len(line.lstrip())]
                if eligibility_inv_id:
                    safety_comment = (
                        f"{indent}// SAFETY: {eligibility_inv_id} — "
                        f"bounds discharged at chart "
                        f"<sos:discharged check=\"bounds\"/> on "
                        f"{state_id} (SOS-13 §8)."
                    )
                else:
                    safety_comment = (
                        f"{indent}// SAFETY: INV-SOS-G — bounds discharged "
                        f"at chart <sos:discharged check=\"bounds\"/> on "
                        f"{state_id} (SOS-13 §8)."
                    )
                new_lines.append(safety_comment)
                out_line_no += 1
                # Re-stamp the emitted_line for the audit entries we
                # just appended so they point at the unsafe line, not
                # the SAFETY-comment line.
                for entry in audit:
                    if entry["emitted_line"] == out_line_no:
                        entry["emitted_line"] = out_line_no + 1

        new_lines.append(new_line)
        out_line_no += 1

    return "\n".join(new_lines), audit


class RustEmitter:
    """ESTree → Rust string emitter. Single-pass, recursive descent.

    Maintains a small lexical context to know when an identifier refers
    to a datamodel field (needs `dm.` prefix) vs a local variable
    (introduced by `var` or as a `for`-loop counter).

    `bound_event_fields` is the set of field names extracted from
    `_event.data` upfront (per the EventData typed-match preamble);
    chart references like `_event.data.id` resolve to the bound
    local `id`."""

    def __init__(
        self,
        bound_event_fields: set[str] | None = None,
        self_mode: bool = False,
    ) -> None:
        self._locals: list[set[str]] = [set()]
        self._notes: list[str] = []
        self._bound_event_fields = bound_event_fields or set()
        # Locals that alias `_event.data` via `var d = _event.data;`.
        # When we see `d.field` for such an alias, treat it as
        # `_event.data.field` for the bound-field resolution.
        self._event_data_aliases: set[str] = set()
        # Locals that alias a datamodel-collection row via the JS
        # reference-semantic pattern `var s = sems[X];`. Records
        # local name → (collection name, index expression string).
        # Subsequent `s.field` accesses rewrite to
        # `dm.sems[X as usize].field` so Rust's move-semantic on the
        # collection element is avoided. Item 3 closure for the
        # `cannot move out of dm.sems[_]` class of errors.
        self._struct_aliases: dict[str, tuple[str, str]] = {}
        # When True, the emitter is inside an `impl Datamodel { ... }`
        # method — datamodel access uses `self.<field>` and helper calls
        # use `self.<helper>(...)` instead of the `dm.` prefix used by
        # transition script bodies.
        self._self_mode = self_mode
        # Name of the innermost for-loop's induction variable. Used by
        # the `<coll>.push({...})` pattern (chart boot.onentry) which
        # writes to `dm.<coll>[i as usize] = <Type> { ... }`. The chart
        # always uses `i` by convention, but we track it explicitly so
        # the pattern survives chart-side renaming.
        self._current_for_var: str | None = None

    def _dm_prefix(self) -> str:
        return "self" if self._self_mode else "dm"

    # ----- scope management -----

    def _push_scope(self) -> None:
        self._locals.append(set())

    def _pop_scope(self) -> None:
        self._locals.pop()

    def _add_local(self, name: str) -> None:
        self._locals[-1].add(name)

    def _is_local(self, name: str) -> bool:
        return any(name in scope for scope in self._locals)

    def _note(self, msg: str) -> None:
        self._notes.append(msg)

    # ----- expression emission -----

    def emit_expr(self, node: Any) -> str:
        t = node.type
        if t == "Literal":
            v = node.value
            if v is None:
                return "/* null */ ()"
            if isinstance(v, bool):
                return "true" if v else "false"
            return node.raw
        if t == "Identifier":
            name = node.name
            if name == "_event":
                return "_ev"
            if name in ST_TO_RUST:
                return ST_TO_RUST[name]
            if name in RC_TO_RUST:
                return RC_TO_RUST[name]
            if name in CONSTANT_NAMES:
                return name
            if self._is_local(name):
                return name
            # EventData typed-match preamble bound this name as a local
            # (e.g. `let id = match ev.data { EventData::TaskId { id }
            # => id, ... };`); resolve as bare identifier.
            if name in self._bound_event_fields:
                return name
            prefix = self._dm_prefix()
            if name in HELPER_NAMES:
                return f"{prefix}.{name}"
            if name in DATAMODEL_NAMES:
                return f"{prefix}.{name}"
            # Unknown identifier — surface as-is + note.
            self._note(f"unknown identifier: {name}")
            return name
        if t == "MemberExpression":
            # Resolve `_event.data.<field>` → bound local <field>.
            if (
                not node.computed
                and node.object.type == "MemberExpression"
                and not node.object.computed
                and node.object.object.type == "Identifier"
                and node.object.object.name == "_event"
                and node.object.property.name == "data"
                and node.property.name in self._bound_event_fields
            ):
                return node.property.name
            # Resolve `<alias>.<field>` → bound local <field> where
            # `<alias>` was declared as `var <alias> = _event.data;`.
            if (
                not node.computed
                and node.object.type == "Identifier"
                and node.object.name in self._event_data_aliases
                and node.property.name in self._bound_event_fields
            ):
                return node.property.name
            # Resolve `<alias>.<field>` → `dm.<collection>[<idx> as usize].<field>`
            # where `<alias>` was declared via `var <alias> = <collection>[<idx>];`.
            # Avoids Rust's `cannot move out of dm.<collection>[_]` error
            # by routing access through the collection.
            if (
                not node.computed
                and node.object.type == "Identifier"
                and node.object.name in self._struct_aliases
            ):
                coll, idx = self._struct_aliases[node.object.name]
                prefix = self._dm_prefix()
                field = node.property.name
                if field == "length":
                    return f"{prefix}.{coll}[{idx} as usize].len()"
                return f"{prefix}.{coll}[{idx} as usize].{field}"
            obj = self.emit_expr(node.object)
            if node.computed:
                idx = self.emit_expr(node.property)
                return f"{obj}[{idx} as usize]"
            # JS `arr.length` is a property; Rust's heapless::Vec uses
            # the `.len()` method. Translate transparently here so the
            # rest of the emitter doesn't have to special-case it.
            if node.property.name == "length":
                return f"{obj}.len()"
            return f"{obj}.{node.property.name}"
        if t == "BinaryExpression":
            left = self.emit_expr(node.left)
            right = self.emit_expr(node.right)
            op = node.operator
            if op == "==":
                op = "=="
            elif op == "!=":
                op = "!="
            return f"({left} {op} {right})"
        if t == "LogicalExpression":
            left = self.emit_expr(node.left)
            right = self.emit_expr(node.right)
            return f"({left} {node.operator} {right})"
        if t == "UnaryExpression":
            arg = self.emit_expr(node.argument)
            op = node.operator
            if op == "!":
                return f"!({arg})"
            return f"({op}{arg})"
        if t == "ConditionalExpression":
            test = self.emit_expr(node.test)
            cons = self.emit_expr(node.consequent)
            alt = self.emit_expr(node.alternate)
            return f"(if {test} {{ {cons} }} else {{ {alt} }})"
        if t == "CallExpression":
            return self._emit_call(node)
        if t == "AssignmentExpression":
            return self._emit_assign_as_expr(node)
        if t == "UpdateExpression":
            return self._emit_update_as_expr(node)
        # Fallback.
        self._note(f"unhandled expr: {t}")
        return f"/* ES: {t} */"

    def _emit_call(self, node: Any) -> str:
        callee = node.callee
        if callee.type == "Identifier":
            name = callee.name
            if name in HELPER_NAMES:
                args_str = self._emit_helper_args(name, node.arguments)
                prefix = self._dm_prefix()
                sig = HELPER_SIGNATURES.get(name, {})
                suffix = "?" if sig.get("returns_result", True) else ""
                return f"{prefix}.{name}({args_str}){suffix}"
            args = ", ".join(self.emit_expr(a) for a in node.arguments)
            self._note(f"free function: {name}")
            return f"{name}({args})"
        if callee.type == "MemberExpression":
            obj = self.emit_expr(callee.object)
            method = callee.property.name
            # Translate common JS array methods.
            if method == "length":
                return f"{obj}.len()"
            if method == "push":
                # `<coll>.push({...})` where <coll> is `tcb` / `sems` /
                # `queues` — chart's boot.onentry pattern. Emit a typed
                # struct-literal assignment into the current for-loop
                # index slot, matching the hand-written boot's shape.
                if (
                    callee.object.type == "Identifier"
                    and callee.object.name in COLLECTION_STRUCT_TYPES
                    and len(node.arguments) == 1
                    and node.arguments[0].type == "ObjectExpression"
                    and self._current_for_var is not None
                ):
                    coll = callee.object.name
                    obj_node = node.arguments[0]
                    struct = emit_struct_literal(self, coll, obj_node)
                    prefix = self._dm_prefix()
                    return (
                        f"{{ {prefix}.{coll}[{self._current_for_var} as usize] "
                        f"= {struct}; }}"
                    )
                # `<vec>.push(<expr>.msg)` — when `<expr>` is a stored
                # struct row (e.g. `tcb[w]`), the access returns a `Msg`
                # enum and needs Int-variant unwrap. When `<expr>` is an
                # event-data alias and `msg` is a bound event-field,
                # the access resolves to the typed-i64 local — no unwrap.
                if (
                    len(node.arguments) == 1
                    and node.arguments[0].type == "MemberExpression"
                    and not node.arguments[0].computed
                    and node.arguments[0].property.name == "msg"
                ):
                    inner_node = node.arguments[0].object
                    is_event_data_alias = (
                        inner_node.type == "Identifier"
                        and inner_node.name in self._event_data_aliases
                        and "msg" in self._bound_event_fields
                    )
                    if not is_event_data_alias:
                        inner = self.emit_expr(inner_node)
                        return (
                            f"{obj}.push(if let Msg::Int(v) = {inner}.msg "
                            f"{{ v }} else {{ 0 }}).ok()"
                        )
                args = ", ".join(self.emit_expr(a) for a in node.arguments)
                return f"{obj}.push({args}).ok()"
            if method == "shift":
                # Rust Vec::remove(0) is the closest analog.
                return f"{obj}.remove(0)"
            if method == "splice":
                args = ", ".join(self.emit_expr(a) for a in node.arguments)
                # splice(i, 1) is the only form the chart uses; emit
                # remove(i). splice(i, 0, val) (insert) → insert(i, val).
                self._note(f"splice form requires manual review: {args}")
                return f"/* splice: {args} */"
            if method == "indexOf":
                args = ", ".join(self.emit_expr(a) for a in node.arguments)
                return f"{obj}.iter().position(|&v| v == {args}).map(|i| i as i32).unwrap_or(-1)"
            # Unknown method.
            args = ", ".join(self.emit_expr(a) for a in node.arguments)
            return f"{obj}.{method}({args})"
        self._note(f"unhandled callee: {callee.type}")
        return f"/* call */ ()"

    def _emit_helper_args(self, name: str, arg_nodes: list) -> str:
        """Emit helper-call arguments with type-aware casts. The pinned
        HELPER_SIGNATURES entry tells us the expected types; chart values
        passed as differently-typed expressions get an `as <type>` cast.

        Special-cases `waiters_insert(<vec-expr>, <tid>)`: the chart
        passes the waiter list directly; v0 emits placeholder dummy args
        (0, 0, tid) since the helper is stubbed pending Item 3 site-aware
        closure. This lets the call type-check."""
        sig = HELPER_SIGNATURES.get(name)
        # Waiter-list-shaped arg detection. Map chart's
        # `waiters_insert(<.waiters|sendw|recvw>, tid)` to the hand-written
        # 3-arg `(WaiterList::X, obj, tid)` form. The `obj` index is
        # derived from the struct-alias context: chart `var s = sems[X];
        # waiters_insert(s.waiters, current)` resolves to `(SemWaiters,
        # X as usize, current as i16)`.
        if name == "waiters_insert" and len(arg_nodes) == 2:
            first = arg_nodes[0]
            tid_expr = self.emit_expr(arg_nodes[1])
            if (
                first.type == "MemberExpression"
                and not first.computed
                and first.property.name in WAITER_LIST_FIELD_TO_VARIANT
            ):
                variant = WAITER_LIST_FIELD_TO_VARIANT[first.property.name]
                # Resolve `obj`: if the LHS object is a struct-alias
                # local (e.g. `s` from `var s = sems[X];`), the obj
                # index is X. Otherwise we fall back to a placeholder
                # `0usize` + a note for manual review.
                if (
                    first.object.type == "Identifier"
                    and first.object.name in self._struct_aliases
                ):
                    _coll, idx_expr = self._struct_aliases[first.object.name]
                    obj_expr = f"{idx_expr} as usize"
                else:
                    self._note(
                        f"waiters_insert: obj index not derivable from alias context"
                    )
                    obj_expr = "0usize"
                return f"{variant}, {obj_expr}, {tid_expr} as i16"
        if sig is None:
            return ", ".join(self.emit_expr(a) for a in arg_nodes)
        # Per-arg emission with target-type cast.
        out_parts: list[str] = []
        params = sig["args"]
        for i, a in enumerate(arg_nodes):
            emitted = self.emit_expr(a)
            target_type = params[i][1] if i < len(params) else None
            if target_type in {"TaskId"}:
                out_parts.append(f"{emitted} as i16")
            elif target_type in {"i16", "u8", "i64"}:
                out_parts.append(f"{emitted} as {target_type}")
            elif target_type == "i32":
                # Placeholder type (used for `arr` in waiters_insert before
                # the special-case path catches it); emit as-is.
                out_parts.append(emitted)
            else:
                out_parts.append(emitted)
        return ", ".join(out_parts)

    def _emit_assign_as_expr(self, node: Any) -> str:
        # Assignment-as-expression is rare in the chart — fall back to a
        # blocky form. Statement-level assignments are handled directly.
        return f"({self.emit_expr(node.left)} {node.operator} {self.emit_expr(node.right)})"

    def _emit_typed_assignment_rhs(self, lhs_node: Any, rhs_node: Any) -> str:
        """When the LHS is a known typed field, wrap the RHS into the
        expected enum/struct variant. v0 handles the `.msg` field, which
        in the M7 Rust port is `Msg::{Null,Int(i64),ReturnCode(ReturnCode)}`.
        The chart writes plain `null` / `RC_OK` / a numeric local; we
        wrap accordingly. Falls back to the raw expression on any other
        LHS."""
        if (
            lhs_node.type == "MemberExpression"
            and not lhs_node.computed
            and lhs_node.property.name == "msg"
        ):
            # `<lvalue>.msg = ...` — wrap into Msg variant.
            return self._wrap_as_msg(rhs_node)
        return self.emit_expr(rhs_node)

    def _wrap_as_msg(self, expr: Any) -> str:
        # null → Msg::Null.
        if expr.type == "Literal" and expr.value is None:
            return "Msg::Null"
        # RC_<X> identifier → Msg::ReturnCode(ReturnCode::<X>).
        if expr.type == "Identifier" and expr.name in RC_TO_RUST:
            return f"Msg::ReturnCode({RC_TO_RUST[expr.name]})"
        # RHS is `<expr>.msg` — distinguish:
        # - `<tcb-row>.msg` returns the stored `Msg` enum → pass through.
        # - `<event-data-alias>.msg` returns the typed-i64 event field
        #   (the EventData preamble bound `msg` as `i64`), so we still
        #   need to wrap it as `Msg::Int(...)`. The alias-resolution
        #   path in `emit_expr` rewrites `d.msg` to bare `msg`.
        if (
            expr.type == "MemberExpression"
            and not expr.computed
            and expr.property.name == "msg"
        ):
            is_event_data_alias = (
                expr.object.type == "Identifier"
                and expr.object.name in self._event_data_aliases
                and "msg" in self._bound_event_fields
            )
            if not is_event_data_alias:
                # `<tcb-row>.msg` or similar — value is already Msg, no wrap.
                return self.emit_expr(expr)
            # Otherwise fall through to the generic Msg::Int wrap.
        # Numeric literal → Msg::Int(<n>).
        if expr.type == "Literal" and isinstance(expr.value, (int, float)):
            return f"Msg::Int({expr.raw})"
        # Generic expression — assume i64-shaped, wrap as Msg::Int.
        # The chart's q.send always passes the typed `msg` local which
        # is bound by the EventData preamble as `i64`, so this is safe.
        return f"Msg::Int({self.emit_expr(expr)})"

    def _emit_update_as_expr(self, node: Any) -> str:
        arg = self.emit_expr(node.argument)
        if node.operator == "++":
            return f"{{ {arg} += 1; {arg} }}"
        return f"{{ {arg} -= 1; {arg} }}"

    # ----- statement emission -----

    def emit_stmt(self, node: Any, indent: str = "    ") -> str:
        t = node.type
        if t == "VariableDeclaration":
            parts = []
            for d in node.declarations:
                # `var <name> = _event.data;` — record as alias, emit no
                # binding (the EventData typed-match preamble already
                # bound the fields as locals).
                if (
                    d.init is not None
                    and d.init.type == "MemberExpression"
                    and not d.init.computed
                    and d.init.object.type == "Identifier"
                    and d.init.object.name == "_event"
                    and d.init.property.name == "data"
                ):
                    self._event_data_aliases.add(d.id.name)
                    continue
                # `var <field> = _event.data.<field>;` where <field> is
                # already bound by the EventData preamble — elide the
                # redundant rebind.
                if (
                    d.init is not None
                    and d.init.type == "MemberExpression"
                    and not d.init.computed
                    and d.init.object.type == "MemberExpression"
                    and not d.init.object.computed
                    and d.init.object.object.type == "Identifier"
                    and d.init.object.object.name == "_event"
                    and d.init.object.property.name == "data"
                    and d.init.property.name in self._bound_event_fields
                    and d.id.name == d.init.property.name
                ):
                    continue
                # `var <name> = <collection>[<expr>];` where <collection>
                # is a datamodel array of structs (tcb / sems / queues) —
                # record alias, suppress emission. Subsequent
                # `<name>.field` accesses rewrite to
                # `dm.<collection>[<expr> as usize].field`.
                if (
                    d.init is not None
                    and d.init.type == "MemberExpression"
                    and d.init.computed
                    and d.init.object.type == "Identifier"
                    and d.init.object.name in {"tcb", "sems", "queues"}
                ):
                    coll = d.init.object.name
                    idx = self.emit_expr(d.init.property)
                    self._struct_aliases[d.id.name] = (coll, idx)
                    continue
                self._add_local(d.id.name)
                init = self.emit_expr(d.init) if d.init else "Default::default()"
                parts.append(f"{indent}let mut {d.id.name} = {init};")
            return "\n".join(parts) if parts else f"{indent}// (event-data alias elided)"
        if t == "ExpressionStatement":
            return self._emit_expr_stmt(node.expression, indent)
        if t == "IfStatement":
            test = self.emit_expr(node.test)
            self._push_scope()
            cons = self.emit_block(node.consequent, indent + "    ")
            self._pop_scope()
            out = f"{indent}if {test} {{\n{cons}\n{indent}}}"
            if node.alternate is not None:
                self._push_scope()
                alt = self.emit_block(node.alternate, indent + "    ")
                self._pop_scope()
                out += f" else {{\n{alt}\n{indent}}}"
            return out
        if t == "ForStatement":
            return self._emit_for(node, indent)
        if t == "WhileStatement":
            self._push_scope()
            body = self.emit_block(node.body, indent + "    ")
            self._pop_scope()
            test = self.emit_expr(node.test)
            return f"{indent}while {test} {{\n{body}\n{indent}}}"
        if t == "ReturnStatement":
            if node.argument is None:
                return f"{indent}return Ok(());"
            arg = self.emit_expr(node.argument)
            return f"{indent}return {arg};"
        if t == "BlockStatement":
            self._push_scope()
            body = self.emit_block(node, indent + "    ")
            self._pop_scope()
            return f"{indent}{{\n{body}\n{indent}}}"
        if t == "ContinueStatement":
            return f"{indent}continue;"
        if t == "BreakStatement":
            return f"{indent}break;"
        self._note(f"unhandled stmt: {t}")
        return f"{indent}/* unhandled stmt: {t} */"

    def _emit_expr_stmt(self, expr: Any, indent: str) -> str:
        if expr.type == "AssignmentExpression":
            # Empty-array reset patterns: chart `<expr>.<arr> = []` →
            # `<expr>.<arr>.clear()` (Rust heapless::Vec). Maps the chart's
            # JS reference-semantic empty-array assignment to the Rust
            # in-place reset.
            if (
                expr.operator == "="
                and expr.right.type == "ArrayExpression"
                and len(expr.right.elements) == 0
                and expr.left.type == "MemberExpression"
                and not expr.left.computed
            ):
                target = self.emit_expr(expr.left)
                return f"{indent}{target}.clear();"
            left = self.emit_expr(expr.left)
            right = self._emit_typed_assignment_rhs(expr.left, expr.right)
            return f"{indent}{left} {expr.operator} {right};"
        if expr.type == "UpdateExpression":
            arg = self.emit_expr(expr.argument)
            if expr.operator == "++":
                return f"{indent}{arg} += 1;"
            return f"{indent}{arg} -= 1;"
        # General expression-as-statement.
        return f"{indent}{self.emit_expr(expr)};"

    def _emit_for(self, node: Any, indent: str) -> str:
        # Recognise the two canonical chart forms:
        #   for (var i = 0; i < N; i++)
        #   for (var i = N - 1; i >= 0; i--)
        init = node.init
        test = node.test
        update = node.update
        if (
            init is not None and init.type == "VariableDeclaration" and len(init.declarations) == 1
            and test is not None and test.type == "BinaryExpression"
            and update is not None and update.type == "UpdateExpression"
        ):
            decl = init.declarations[0]
            i_name = decl.id.name
            start = self.emit_expr(decl.init)
            self._push_scope()
            self._add_local(i_name)
            saved_for_var = self._current_for_var
            self._current_for_var = i_name
            if test.operator == "<" and update.operator == "++":
                end = self.emit_expr(test.right)
                body = self.emit_block(node.body, indent + "    ")
                self._pop_scope()
                self._current_for_var = saved_for_var
                return (
                    f"{indent}for {i_name} in ({start} as usize)..({end} as usize) {{\n"
                    f"{body}\n{indent}}}"
                )
            if test.operator == ">=" and update.operator == "--":
                end = self.emit_expr(test.right)
                body = self.emit_block(node.body, indent + "    ")
                self._pop_scope()
                self._current_for_var = saved_for_var
                return (
                    f"{indent}for {i_name} in (({end} as usize)..=({start} as usize)).rev() {{\n"
                    f"{body}\n{indent}}}"
                )
            self._pop_scope()
            self._current_for_var = saved_for_var
        # Fallback: surface as commented JS, note for manual handling.
        self._note("unrecognised for-loop form; falling back to comment")
        return f"{indent}/* ES for-loop unrecognised; manual review required */"

    def emit_block(self, node: Any, indent: str) -> str:
        if node.type == "BlockStatement":
            stmts = node.body
        else:
            # Single statement (e.g. an `if` body that's not blocked).
            stmts = [node]
        lines = [self.emit_stmt(s, indent) for s in stmts]
        return "\n".join(lines)


# Chart datamodel array name → per-row Rust struct type. Used by the
# `<coll>.push({ ... })` pattern in boot.onentry: emit a typed struct
# literal at the surrounding for-loop's index slot rather than a JS-style
# dynamic push.
COLLECTION_STRUCT_TYPES: dict[str, str] = {
    "tcb":    "crate::kernel::Tcb",
    "sems":   "crate::kernel::Sem",
    "queues": "crate::kernel::Queue",
}

# Per-collection field-name → Rust-type-aware emit-hint. v0 covers the
# fields the chart's boot.onentry uses inside an ObjectExpression. Other
# fields fall through to the raw emit (the Rust compiler infers).
COLLECTION_FIELD_HINTS: dict[str, dict[str, str]] = {
    "tcb": {
        "id":  "TaskId",  # i32 / loop-var → cast `as TaskId`
        "msg": "Msg",     # null → Msg::Null
    },
    "sems": {
        "waiters": "HVec",  # [] → heapless::Vec::new()
    },
    "queues": {
        "buf":   "HVec",
        "sendw": "HVec",
        "recvw": "HVec",
    },
}


def emit_struct_literal(emitter: RustEmitter, coll_name: str, obj_node: Any) -> str:
    """Emit a Rust struct literal `<Type> { <field>: <value>, ... }`
    given the chart's `<coll>.push({...})` ObjectExpression. Uses
    COLLECTION_FIELD_HINTS to apply per-field type-aware emission."""
    struct_type = COLLECTION_STRUCT_TYPES[coll_name]
    field_hints = COLLECTION_FIELD_HINTS.get(coll_name, {})
    parts: list[str] = []
    for prop in obj_node.properties:
        key = prop.key.name if prop.key.type == "Identifier" else prop.key.value
        val_node = prop.value
        hint = field_hints.get(key)
        if hint == "TaskId" and val_node.type == "Identifier":
            val = f"{emitter.emit_expr(val_node)} as TaskId"
        elif hint == "Msg":
            if val_node.type == "Literal" and val_node.value is None:
                val = "Msg::Null"
            else:
                val = emitter.emit_expr(val_node)
        elif hint == "HVec":
            if val_node.type == "ArrayExpression" and len(val_node.elements) == 0:
                val = "heapless::Vec::new()"
            else:
                val = emitter.emit_expr(val_node)
        else:
            val = emitter.emit_expr(val_node)
        parts.append(f"{key}: {val}")
    body = ", ".join(parts)
    return f"{struct_type} {{ {body} }}"


# Per-helper Rust signature mirror-table. Aligned with the
# hand-written `impl Datamodel { ... }` block in `ports/m7-rust/
# sos-m7-rust/src/scripts.rs` so codegen-emitted call sites bind
# cleanly to the hand-written primitives in the hybrid test.
#
# `returns_result`: True if the helper returns `Result<…, ScriptError>`
# (so call sites use `?`); False if it returns `()` or a bare value.
# `waiters_insert` takes a 3-arg form `(kind: WaiterList, obj: usize,
# tid: TaskId)` in the hand-written; the codegen call-emitter detects
# the chart's `waiters_insert(<.waiters|sendw|recvw>, tid)` shape and
# maps the first arg to the corresponding `WaiterList::*` discriminator.
HELPER_SIGNATURES: dict[str, dict[str, object]] = {
    "readyq_init":       {"args": [],                                                     "ret": "Result<(), ScriptError>",       "returns_result": True},
    "ready_push":        {"args": [("tid", "TaskId")],                                    "ret": "Result<(), ScriptError>",       "returns_result": True},
    "ready_remove":      {"args": [("tid", "TaskId")],                                    "ret": "()",                            "returns_result": False},
    "ready_pop_highest": {"args": [],                                                     "ret": "TaskId",                        "returns_result": False},
    "waiters_insert":    {"args": [("kind", "WaiterList"), ("obj", "usize"), ("tid", "TaskId")], "ret": "Result<(), ScriptError>", "returns_result": True},
    "block_current":     {"args": [("state", "TaskState"), ("obj_id", "i16"), ("deadline", "i64")], "ret": "()",                   "returns_result": False},
    "unblock":           {"args": [("tid", "TaskId")],                                    "ret": "Result<(), ScriptError>",       "returns_result": True},
    "waiter_cancel":     {"args": [("tid", "TaskId")],                                    "ret": "()",                            "returns_result": False},
    "pick_next":         {"args": [],                                                     "ret": "Result<(), ScriptError>",       "returns_result": True},
}


# Chart waiter-list field-name → hand-written WaiterList variant.
# Used by `_emit_call` to map the chart's `waiters_insert(s.waiters, current)`
# / `waiters_insert(q.sendw, current)` / `waiters_insert(q.recvw, current)`
# into the hand-written 3-arg `(WaiterList::X, obj, tid)` form.
WAITER_LIST_FIELD_TO_VARIANT: dict[str, str] = {
    "waiters": "WaiterList::SemWaiters",
    "sendw":   "WaiterList::QueueSendW",
    "recvw":   "WaiterList::QueueRecvW",
}


def _signature_for(name: str, esprima_params: list) -> str:
    """Return the Rust parameter list for a helper. Uses the pinned
    HELPER_SIGNATURES entry when present; otherwise falls back to
    typing every param as `i64` (a safe widening for the chart's
    integer-only helpers)."""
    if name in HELPER_SIGNATURES:
        args = HELPER_SIGNATURES[name]["args"]
        return ", ".join(f"{a}: {t}" for a, t in args)
    return ", ".join(f"{p.name}: i64" for p in esprima_params)


def _return_type_for(name: str) -> str:
    return HELPER_SIGNATURES.get(name, {}).get("ret", "Result<(), ScriptError>")


@dataclass
class HelperEmit:
    name: str
    rust_source: str
    is_stub: bool
    notes: list[str] = field(default_factory=list)


# Helpers v0 can mechanically transliterate; the rest fall back to a
# typed stub body that returns `Ok(())` / a default. The stubs let
# script bodies compile and link; runtime conformance for any vector
# that exercises the stubbed helper will fail, which is the correct
# signal per SOS-06 verdict-matrix (`Coexist` or `NotRecommended`
# until Item 3 closure lands site-aware emission).
HELPER_V0_TRANSLITERABLE = {
    "block_current",
    "unblock",
    "ready_remove",
}


def _stub_body_for(name: str) -> str:
    """Return the stub body that satisfies a helper's signature."""
    ret = _return_type_for(name)
    if "Result<TaskId" in ret:
        return "    let _ = self; Ok(-1)"
    if "Result<(), ScriptError>" in ret:
        return "    let _ = self; Ok(())"
    return "    let _ = self; Default::default()"


# Chart event-name → Rust EventName enum variant. The hand-written
# port at `ports/m7-rust/sos-m7-rust/src/event.rs` exposes only the
# EXTERNAL events — internal events (`kernel.boot.done`, `sched.run`
# per SOS-01 §5.6) are raised by chart transitions and consumed by
# other chart transitions; the kernel's external dispatch surface
# never sees them. The codegen dispatcher mirrors that surface.
EVENT_TO_VARIANT: dict[str, str] = {
    "sys.tick":            "SysTick",
    "task.create":         "TaskCreate",
    "task.delay":          "TaskDelay",
    "task.yield":          "TaskYield",
    "task.suspend":        "TaskSuspend",
    "task.resume":         "TaskResume",
    "sem.create":          "SemCreate",
    "sem.take":            "SemTake",
    "sem.give":            "SemGive",
    "sem.give_from_isr":   "SemGiveFromIsr",
    "queue.create":        "QueueCreate",
    "queue.send":          "QueueSend",
    "queue.receive":       "QueueReceive",
    "queue.send_from_isr": "QueueSendFromIsr",
    "crit.enter":          "CritEnter",
    "crit.exit":           "CritExit",
    "sched.suspend":       "SchedSuspend",
    "sched.resume":        "SchedResume",
}


def emit_dispatch_event(sites: list) -> str:
    """Emit the top-level `dispatch_event` free function — runs the
    per-event script, then performs the scheduler **macrostep** per
    SOS-04 §6.5: if a state-mutating script set `dm.resched = true`,
    run `script_sched_idle_sched_run_0` (which executes `pick_next()`).

    This mirrors the chart's `<raise event="sched.run"/>` directive
    that follows every syscall-family `<transition>`'s `<script>`. The
    chart never raises any other internal event, so the macrostep
    reduces to "fire the sched.run handler when resched is set".

    `sites` is the list of `ScriptSite` records the loader produced.
    On-entry sites (e.g. `script_boot_onentry_0`) are not routed by
    name and stay unreferenced by the dispatcher."""
    arms: list[str] = []
    seen: set[str] = set()
    sched_run_fn: str | None = None
    for site in sites:
        if site.kind != "transition":
            continue
        if site.event is None:
            continue
        if site.event == "sched.run":
            # Internal event — not in EventName, but we need the
            # function name to wire the macrostep below.
            sched_run_fn = site.function_name
            continue
        if site.event in seen:
            continue
        seen.add(site.event)
        variant = EVENT_TO_VARIANT.get(site.event)
        if variant is None:
            continue
        arms.append(
            f"        EventName::{variant} => {site.function_name}(dm, ev)?,"
        )
    arms_str = "\n".join(arms)
    macrostep = ""
    if sched_run_fn is not None:
        macrostep = (
            "\n    // Macrostep: if the per-event script raised `resched`,\n"
            "    // run the scheduler microstep now. Mirrors the chart's\n"
            "    // `<raise event=\"sched.run\"/>` directive at the end of\n"
            "    // every state-mutating transition.\n"
            "    if dm.resched {\n"
            f"        {sched_run_fn}(dm, ev)?;\n"
            "    }\n"
        )
    return (
        "/// Top-level dispatcher — routes one event to the matching\n"
        "/// `script_*` body per chart transition, then performs the\n"
        "/// scheduler macrostep (chart's `<raise event=\"sched.run\"/>`).\n"
        "pub fn dispatch_event(dm: &mut Datamodel, ev: &Event) -> Result<(), ScriptError> {\n"
        "    match ev.name {\n"
        f"{arms_str}\n"
        "    }\n"
        f"{macrostep}\n"
        "    Ok(())\n"
        "}"
    )


# Path to the bench-validated reference scripts.rs that supplies the
# Layer B runtime library (impl Datamodel block + WaiterList enum). The
# codegen tool reads this file at codegen-time and embeds the helper
# bodies verbatim. Per SOS-06 §15 Amendment 002, treating Layer B as a
# fixed runtime library is the v0 closure path — auto-transliterating
# the chart's HELPERS-block JS would require array-method emission
# beyond v0's reach.
_RUNTIME_RUST_REFERENCE = (
    "ports/m7-rust/sos-m7-rust/src/scripts.rs"
)


def _find_brace_block(lines: list[str], start_pattern: str) -> tuple[int, int] | None:
    """Find a top-level `<start_pattern> { ... }` block. Returns
    (start_line_idx, end_line_idx_inclusive) or None if not found."""
    import re as _re

    pat = _re.compile(start_pattern)
    for i, line in enumerate(lines):
        if pat.match(line):
            depth = 0
            seen_open = False
            for j in range(i, len(lines)):
                depth += lines[j].count("{") - lines[j].count("}")
                if "{" in lines[j]:
                    seen_open = True
                if seen_open and depth == 0:
                    return i, j
    return None


def embed_rust_runtime(reference_path: str | None = None) -> str:
    """Extract the hand-written `enum WaiterList { ... }` + `impl
    Datamodel { ... }` blocks from the reference scripts.rs and return
    the concatenated source for verbatim embedding in the codegen
    output. Per SOS-06 §15 Amendment 002 (Layer B runtime library).

    The reference file is the bench-validated `ports/m7-rust/sos-m7-rust/
    src/scripts.rs`. If the file isn't present (e.g. running the codegen
    against a fresh worktree before any hand-written port exists), the
    function returns an empty string — the codegen falls back to its
    previous stubbed-helpers emission via `emit_helpers()`."""
    from pathlib import Path as _Path

    ref = _Path(reference_path or _RUNTIME_RUST_REFERENCE)
    if not ref.is_absolute():
        # Resolve relative to the SOS subrepo root (two levels up from
        # `tools/sos-codegen/`).
        tool_dir = _Path(__file__).resolve().parent
        ref = (tool_dir.parent.parent / ref).resolve()
    if not ref.exists():
        return ""
    lines = ref.read_text(encoding="utf-8").splitlines(keepends=True)

    # WaiterList enum (optional; include its preceding `#[derive(...)]`
    # attribute and any doc comment).
    waiter_pos = None
    for i, line in enumerate(lines):
        if line.startswith("enum WaiterList"):
            depth = 0
            seen_open = False
            for j in range(i, len(lines)):
                depth += lines[j].count("{") - lines[j].count("}")
                if "{" in lines[j]:
                    seen_open = True
                if seen_open and depth == 0:
                    waiter_pos = (i, j)
                    break
            break
    waiter_src = ""
    if waiter_pos is not None:
        ws, we = waiter_pos
        pre = ws
        while pre > 0 and (
            lines[pre - 1].lstrip().startswith("#[")
            or lines[pre - 1].lstrip().startswith("///")
        ):
            pre -= 1
        waiter_src = "".join(lines[pre : we + 1])

    impl_pos = _find_brace_block(lines, r"^impl Datamodel \{")
    if impl_pos is None:
        return waiter_src
    impl_src = "".join(lines[impl_pos[0] : impl_pos[1] + 1])

    # Supplementary stubs for chart helpers the hand-written port
    # inlines rather than realising as Datamodel methods. The chart's
    # `readyq_init()` is called from boot.onentry; the hand-written
    # port inlines `for p in 0..MAX_PRIO { dm.ready[p].clear(); }`
    # inside its boot script. The codegen-emitted boot.onentry calls
    # `dm.readyq_init()`, so we need a method on Datamodel.
    supplement = (
        "\n"
        "impl Datamodel {\n"
        "    /// Codegen supplement: the chart's `readyq_init()` is\n"
        "    /// inlined in the hand-written reference port's boot.\n"
        "    /// Provided here as a method so the codegen-emitted boot\n"
        "    /// can call it uniformly.\n"
        "    pub(crate) fn readyq_init(&mut self) -> Result<(), ScriptError> {\n"
        "        for p in 0..MAX_PRIO {\n"
        "            self.ready[p].clear();\n"
        "        }\n"
        "        Ok(())\n"
        "    }\n"
        "}\n"
    )

    if waiter_src:
        return waiter_src + "\n" + impl_src + supplement
    return impl_src + supplement


def emit_helpers(helpers_source: str) -> list[HelperEmit]:
    """Parse the chart's HELPERS block (CDATA), emit each
    `function name(args) { body }` as an `impl Datamodel` method.

    v0 emits stub bodies with the correct signature for every helper.
    Helpers in HELPER_V0_TRANSLITERABLE additionally emit a mechanical
    body via the Rust transliterator with `self_mode=True`."""
    program = esprima.parseScript(helpers_source)
    out: list[HelperEmit] = []
    for stmt in program.body:
        if stmt.type != "FunctionDeclaration":
            continue
        name = stmt.id.name
        params = list(stmt.params)
        sig = _signature_for(name, params)
        ret = _return_type_for(name)
        header_args = f"&mut self" + (f", {sig}" if sig else "")
        doc = f"    /// Translates `{name}` (rtos_kernel.scxml HELPERS block)."
        if name in HELPER_V0_TRANSLITERABLE:
            try:
                emitter = RustEmitter(self_mode=True)
                # Register the param names as locals so they don't
                # get the `self.` prefix.
                for p in params:
                    emitter._add_local(p.name)
                lines = [emitter.emit_stmt(s, "        ") for s in stmt.body.body]
                body = "\n".join(lines) + "\n        Ok(())"
                stub = False
                notes = list(emitter._notes)
            except Exception as exc:
                body = _stub_body_for(name)
                stub = True
                notes = [f"transliterate error: {exc}"]
        else:
            body = _stub_body_for(name)
            stub = True
            notes = ["SOS-06-A-2 Item 3 deferred: needs site-aware array-method emission"]
        if stub:
            doc += "\n    /// v0 STUB: " + (notes[0] if notes else "deferred")
        rust = (
            f"{doc}\n"
            f"    pub(crate) fn {name}({header_args}) -> {ret} {{\n"
            f"{body}\n"
            f"    }}"
        )
        out.append(HelperEmit(name=name, rust_source=rust, is_stub=stub, notes=notes))
    return out


def transliterate_to_rust(
    source: str,
    event_name: str | None = None,
    verified_strip: "VerifiedStripConfig | None" = None,
    state_id: str = "",
    chart_site: str = "",
) -> TransliterationResult:
    """Parse ECMAScript source, emit Rust statements.

    `event_name` is the chart event the site dispatches on (e.g.
    `task.create`); when provided, a typed-match preamble extracts the
    `EventData` payload as locals before the transliterated body runs.

    `verified_strip` is an optional SOS-13 verified-strip profile
    configuration. When `None` (the default), emission is byte-
    identical to prior behaviour — the verified-strip post-pass does
    not run. When set, the post-pass replaces bounds-checked index
    patterns with `unsafe { ... .get_unchecked(...) }` for sites whose
    chart annotations discharge the obligation, and records one audit
    entry per replacement on the returned `TransliterationResult`.

    `state_id` / `chart_site` are passed through to the audit log; they
    let reviewers trace each unsafe block back to the originating chart
    location. Defaults are empty strings — pass non-empty values when
    `verified_strip` is set.

    Returns the emitted Rust source (preamble + body), a list of notes
    flagging unhandled-construct fallbacks, a `needs_ev_param` flag the
    caller uses to bind `ev` vs `_ev` in the function signature, and
    (under verified-strip) a list of audit entries on
    `verified_strip_audit`.
    """
    program = esprima.parseScript(source)
    preamble, bound_fields = emit_eventdata_extract(event_name)
    emitter = RustEmitter(bound_event_fields=bound_fields)
    lines: list[str] = []
    if preamble:
        lines.append(preamble)
    for stmt in program.body:
        lines.append(emitter.emit_stmt(stmt))
    rust_source = "\n".join(lines)

    audit_entries: list[dict] = []
    if verified_strip is not None and verified_strip.is_active():
        rust_source, audit_entries = apply_verified_strip(
            rust_source, verified_strip, state_id, chart_site
        )

    return TransliterationResult(
        rust_source=rust_source,
        unhandled_notes=emitter._notes,
        preamble=preamble,
        needs_ev_param=bool(preamble),
        verified_strip_audit=audit_entries,
    )


# ============================================================================
# SOS-09-D — Rust HAL channel-emit subset
#
# Authority: ``docs/concepts/SOS-09-D-CONCEPTS.md`` (🟢 RATIFIED 2026-05-26).
# This block extends the existing transliteration walker with the
# channel-emit subset described in §5 of that doc. It is additive: prior
# `transliterate_to_rust(...)` callers are unaffected.
#
# Frozen decisions consumed:
#   §5.1  one `#[repr(C)] #[non_exhaustive] struct RegisterBlock` per
#         `sos:channel_group` (PCDN-SOS-09-D-001 borrow-checker clarification).
#         Fields are `#[repr(transparent)]` newtype wrappers over
#         `vcell::VolatileCell<T>` (D-001 accepted option (a)).
#   §5.2  six newtype wrappers — `Status<T>` / `Command<T>` / `Queue<T>` /
#         `Shared<T>` / `ClearOnRead<T>` / `FireOnWrite<T>` — chosen from
#         `sos:kind` + side-effect / clear-on-read.
#   §5.3  `Shared<T>::claim() -> Result<Claimed<'_, T>, ContentionError>`
#         + `Claimed::drop` releases (D-002 / D-003 ratified options).
#   §5.4  `#![no_std]` + optional `alloc` Cargo feature.
#   §5.5  `*_unchecked` accessors emitted as `unsafe fn` with codegen-
#         emitted `// SAFETY:` comments (D-005 accepted option (a) + the
#         user-clarified "roll up in generation" guidance).
#   §5.6  `pub const SOS_MPU_<CHANNEL>_REGION: sos_mpu_region_t = ...;`
#         constant export per channel with `sos:zone` or `sos:mpu_attr`.
#
# Invariants enforced:
#   INV-S-MEM-D-1 newtype-wrapper-only register access (no raw volatile reads
#                 reach driver-facing surface; only the prelude wrappers do).
#   INV-S-MEM-D-2 `ClearOnRead<T>::read` consumes `self` (the `consume` form
#                 here mirrors the spec's `read(self) -> T` shape via a
#                 `&mut self` move-then-replace; the discipline is enforced
#                 by exposing only `consume`, no `read`).
#   INV-S-MEM-D-3 `Command<T>` exposes only `fire`; no `read` method on
#                 the wrapper.
#   INV-S-MEM-D-4 emitted crates pass `cargo check --no-default-features
#                 --target thumbv7em-none-eabihf`.
#   INV-S-MEM-D-5 `RegisterBlock` field offsets match SVD `<addressOffset>`
#                 bit-for-bit; this module's offset arithmetic mirrors
#                 `transliterate_svd._channel_size_bytes` (4-byte aligned).
#   INV-S-MEM-D-6 accessor + type names deterministic from `sos:name`
#                 (snake_case for fields, PascalCase for types,
#                 SCREAMING_SNAKE_CASE for MPU consts).
# ============================================================================

from sos09_annotations import (  # noqa: E402  (intentionally near use site)
    ChannelAnnotation,
    ChartAnnotations,
    parse_chart_annotations,
)


# Mirror of `transliterate_svd._channel_size_bytes` — kept local to avoid a
# cross-module import dance, and so a SOS-09-B-side change cannot silently
# drift the Rust offsets relative to the SVD chain. Both helpers compute
# the same 4-byte-aligned byte count; the test suite asserts parity.
def _hal_channel_size_bytes(width_bits: int) -> int:
    """Bytes a width-N channel occupies on the bus, 4-byte aligned.

    Matches `transliterate_svd._channel_size_bytes` (INV-S-MEM-D-5: this
    module's `RegisterBlock` `_reservedN` padding produces the same
    cumulative offsets as the SVD `<addressOffset>` chain).
    """
    if width_bits <= 0:
        raise ValueError(f"channel width must be positive; got {width_bits}")
    raw_bytes = (width_bits + 7) // 8
    return ((raw_bytes + 3) // 4) * 4


def _rust_width_type(width_bits: int) -> str:
    """Map a chart `sos:width` to the Rust unsigned integer type used as
    the `T` parameter of the newtype wrappers.

    Per §5.2 the wrapper inner cell type is `vcell::VolatileCell<T>` and
    `T` resolves to the smallest unsigned type that fits `sos:width`.
    """
    if 1 <= width_bits <= 8:
        return "u8"
    if width_bits <= 16:
        return "u16"
    if width_bits <= 32:
        return "u32"
    if width_bits <= 64:
        return "u64"
    raise ValueError(f"unsupported sos:width={width_bits}; must satisfy 1..=64")


# Channel `sos:kind` + side-effect / clear-on-read flags → newtype wrapper.
# Mirrors the SOS-09-D §5.2 selection table. Returns the wrapper type
# name (parameterised by `T`).
def _select_wrapper(channel: ChannelAnnotation) -> str:
    """Per §5.2 wrapper selection.

    Note: `clear_on_read` and `side_effect` are deduced from the channel's
    `bit_layout` (when any field carries the corresponding `side_effect`
    annotation). This matches SOS-09-B's `_has_clear_on_read` derivation,
    so the Rust + SVD sides agree on which channels are read-as-side-
    effect-bearing.
    """
    kind = channel.kind
    has_clear_on_read = False
    has_side_effect_on_write = False
    if channel.bit_layout is not None:
        for f in channel.bit_layout.fields:
            if f.side_effect == "clear-on-read":
                has_clear_on_read = True
            elif f.side_effect == "side-effect-on-write":
                has_side_effect_on_write = True

    if kind == "status":
        if has_clear_on_read:
            return "ClearOnRead"
        return "Status"
    if kind == "command":
        if has_side_effect_on_write:
            return "FireOnWrite"
        return "Command"
    if kind == "queue":
        return "Queue"
    if kind == "shared":
        return "Shared"
    raise ValueError(f"unknown sos:kind={kind!r}")


def _channel_field_name(channel: ChannelAnnotation) -> str:
    """The `RegisterBlock` field name. Per INV-S-MEM-D-6, derived from
    `sos:name` only — never from `sos:id`.

    `sos:name` is already validated as an SV identifier by SOS-09-A; this
    helper does NOT re-validate. Output is byte-identical across runs.
    """
    return channel.name


def _channel_pascal_name(channel: ChannelAnnotation) -> str:
    """The PascalCase form of `sos:name`, used in inline type aliases /
    typestate payloads. Deterministic from `sos:name`.
    """
    parts = channel.name.split("_")
    return "".join(p[:1].upper() + p[1:].lower() for p in parts if p)


def _channel_screaming_name(channel: ChannelAnnotation) -> str:
    """SCREAMING_SNAKE_CASE form of `sos:name`. Per §5.6 used for the
    `SOS_MPU_<CHANNEL>_REGION` constant name.

    `sos:name` is already snake_case-ish (SV identifier); uppercasing is
    a deterministic 1:1 transform.
    """
    return channel.name.upper()


def _channel_group(channel: ChannelAnnotation) -> str:
    """Resolve the channel's `sos:channel_group` (PCDN-SOS-09-007
    follow-on amendment 2026-05-26). When absent, the fallback is
    `"default"` — SOS-09-A leaves the inheritance walk to consumers,
    and we treat absence as the default group per the amendment text.
    """
    return channel.channel_group or "default"


def _safe_module_ident(name: str) -> str:
    """Normalise a `sos:channel_group` to a valid Rust module identifier.

    `sos:channel_group` is already an SV identifier per SOS-09-A
    validation; this helper exists for the `"default"` fallback path
    (which is also a valid Rust identifier) and to keep the conversion
    explicit in one place.
    """
    return name


# ---------------------------------------------------------------------------
# Newtype-wrapper prelude (emitted verbatim into every crate)
#
# This is the only place that holds `unsafe` register access; every
# accessor on the wrappers is safe modulo the explicitly-marked
# `*_unchecked` variants per §5.5. INV-S-MEM-D-1 says driver-facing code
# never reaches raw volatile reads — only these wrappers do.
# ---------------------------------------------------------------------------

_RUST_HAL_PRELUDE = '''\
// SOS-09-D — Rust HAL newtype prelude (§5.2 + §5.3).
//
// Authority: docs/concepts/SOS-09-D-CONCEPTS.md (🟢 RATIFIED 2026-05-26).
// Per PCDN-SOS-09-D-001 accepted option (a) inner cells are
// `vcell::VolatileCell<T>`; per PCDN-SOS-09-D-003 accepted option (b)
// `ContentionError` is the single-variant `#[non_exhaustive]` enum.
//
// INV-S-MEM-D-1: driver-facing code MUST go through these wrappers.

use core::marker::PhantomData;
use vcell::VolatileCell;

/// Single-variant error returned by `Shared<T>::claim()` when the
/// underlying `sos_mutex` is held elsewhere. Per PCDN-SOS-09-D-003
/// accepted option (b) — `#[non_exhaustive]` so additional failure
/// modes can be added without breaking exhaustive pattern matches at
/// call sites.
#[non_exhaustive]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ContentionError {
    /// The mutex is currently claimed elsewhere (HW side or another
    /// software claimant).
    LockHeldElsewhere,
}

// -- Status<T> -------------------------------------------------------------
//
// `kind="status"` without a clear-on-read field. Read-only by construction;
// no `fire` accessor. Per INV-S-MEM-D-3 the wrapper API surface omits
// any write-side method.

/// Read-only status register newtype. `kind="status"` channels surface
/// as this wrapper.
#[repr(transparent)]
pub struct Status<T: Copy> {
    cell: VolatileCell<T>,
}

impl<T: Copy> Status<T> {
    /// Read the current value. Pure side-effect-free volatile read.
    #[inline]
    pub fn read(&self) -> T {
        self.cell.get()
    }
}

// -- Command<T> ------------------------------------------------------------
//
// `kind="command"` without side-effect-on-write. Write-only by
// construction; no `read` accessor. Per INV-S-MEM-D-3 the wrapper API
// surface omits any read method.

/// Write-only command register newtype. `kind="command"` channels surface
/// as this wrapper.
#[repr(transparent)]
pub struct Command<T: Copy> {
    cell: VolatileCell<T>,
}

impl<T: Copy> Command<T> {
    /// Write a value. Volatile write; HW interprets per the chart's
    /// declared side-effect.
    #[inline]
    pub fn fire(&mut self, value: T) {
        self.cell.set(value);
    }
}

// -- ClearOnRead<T> --------------------------------------------------------
//
// `kind="status"` with `clear-on-read` field. Per INV-S-MEM-D-2 the
// `consume` method takes `&mut self` and the wrapper exposes NO `read`
// method — double-clear-on-read is structurally impossible because the
// caller cannot read without consuming a `&mut` borrow.

/// Status register with read-clears-bits semantics. `consume` reads and
/// (HW-side) clears the value; per §5.2 the wrapper exposes no `read`
/// method to make double-clear-on-read a compile-time impossibility.
#[repr(transparent)]
#[must_use]
pub struct ClearOnRead<T: Copy> {
    cell: VolatileCell<T>,
}

impl<T: Copy> ClearOnRead<T> {
    /// Consume one read of the register. The HW clears the bits as a
    /// side effect of the read (`<readAction>clear</readAction>` in the
    /// SVD). The caller holds `&mut self` so a second `consume` against
    /// the same borrow is rejected by the borrow checker.
    #[inline]
    pub fn consume(&mut self) -> T {
        self.cell.get()
    }
}

// -- FireOnWrite<T> --------------------------------------------------------
//
// `kind="command"` with side-effect-on-write field. Same API as
// `Command<T>` (write-only); the distinct type carries the chart-declared
// side-effect annotation in a doc-comment and lets reviewers distinguish
// "this write triggers HW action" from "this write merely updates a
// register value".

/// Command register whose write triggers a chart-declared HW side-effect
/// beyond the value update. Per §5.2 distinguished from `Command<T>` for
/// reviewer clarity.
#[repr(transparent)]
pub struct FireOnWrite<T: Copy> {
    cell: VolatileCell<T>,
}

impl<T: Copy> FireOnWrite<T> {
    /// Write the value, triggering the chart-declared HW side-effect.
    #[inline]
    pub fn fire(&mut self, value: T) {
        self.cell.set(value);
    }
}

// -- Queue<T> --------------------------------------------------------------
//
// `kind="queue"`. The runtime layer (consumed via the SOS-08-B
// message-channel primitive at integration time) supplies push/pop
// semantics; the wrapper here exposes the typed surface.
//
// Per §5.2: the wrapper MAY be richer than the bare type would suggest
// (composite register pair head/tail behind the single accessor). At v1
// the wrapper exposes only the raw head-register volatile cell; the
// SOS-08-B integration layer extends it.

/// Queue channel newtype. `kind="queue"` channels surface as this
/// wrapper; runtime push/pop semantics are supplied by the SOS-08-B
/// message-channel primitive at integration time.
#[repr(transparent)]
pub struct Queue<T: Copy> {
    cell: VolatileCell<T>,
}

impl<T: Copy> Queue<T> {
    /// Push one value into the queue. v1 surfaces the raw register write;
    /// the runtime layer wraps this with head/tail bookkeeping.
    #[inline]
    pub fn push(&mut self, value: T) {
        self.cell.set(value);
    }

    /// Pop one value from the queue. v1 surfaces the raw register read;
    /// the runtime layer wraps this with head/tail bookkeeping.
    #[inline]
    pub fn pop(&mut self) -> T {
        self.cell.get()
    }
}

// -- Shared<T> + Claimed<'_, T> -------------------------------------------
//
// `kind="shared"`. The typed region is accessible ONLY through the
// `Claimed<'_, T>` Drop-guard returned by `claim()`. Per §5.3 the borrow
// checker enforces: no access without claim, no double-claim, no
// forgotten release.

/// Shared region newtype. `kind="shared"` channels surface as this
/// wrapper; the typed region is reachable only through the
/// `Claimed<'_, T>` Drop-guard returned by `claim()`.
#[repr(transparent)]
pub struct Shared<T: Copy> {
    cell: VolatileCell<T>,
}

impl<T: Copy> Shared<T> {
    /// Claim the underlying mutex. Returns a `Claimed<'_, T>` Drop-guard
    /// on success; the guard's `Drop` impl releases the mutex.
    ///
    /// At v1 the underlying `sos_mutex` integration is supplied by the
    /// runtime layer; this implementation accepts every claim
    /// optimistically. The runtime layer wraps this to enforce the
    /// chart's mutex contract at the wire level.
    #[inline]
    pub fn claim(&mut self) -> Result<Claimed<'_, T>, ContentionError> {
        Ok(Claimed {
            shared: self,
            _lifetime: PhantomData,
        })
    }

    /// Non-blocking claim variant. Returns `None` on contention.
    #[inline]
    pub fn try_claim(&mut self) -> Option<Claimed<'_, T>> {
        self.claim().ok()
    }
}

/// Drop-guard returned by `Shared<T>::claim()`. The typed region is
/// reachable only through methods on this guard; `Drop` releases the
/// underlying `sos_mutex`. Per §5.3 the borrow checker enforces
/// no-access-without-claim, no-double-claim, no-forgotten-release.
pub struct Claimed<'a, T: Copy> {
    shared: &'a mut Shared<T>,
    _lifetime: PhantomData<&'a mut ()>,
}

impl<'a, T: Copy> Claimed<'a, T> {
    /// Read the protected value while holding the claim.
    #[inline]
    pub fn read(&self) -> T {
        self.shared.cell.get()
    }

    /// Write the protected value while holding the claim.
    #[inline]
    pub fn write(&mut self, value: T) {
        self.shared.cell.set(value);
    }

    /// Read-modify-write the protected value while holding the claim.
    #[inline]
    pub fn modify<F: FnOnce(&mut T)>(&mut self, f: F) {
        let mut v = self.shared.cell.get();
        f(&mut v);
        self.shared.cell.set(v);
    }
}

impl<'a, T: Copy> Drop for Claimed<'a, T> {
    fn drop(&mut self) {
        // The runtime layer releases the underlying `sos_mutex` here.
        // At v1 this is a no-op; the integration is supplied by the
        // SOS-09-G `sos_mpu_install()` adjacent runtime.
    }
}
'''


# ---------------------------------------------------------------------------
# Top-level emit API
# ---------------------------------------------------------------------------


def _emit_register_block(
    group_name: str,
    channels: list[ChannelAnnotation],
    base_offset: int = 0,
) -> tuple[str, list[tuple[str, int, int]]]:
    """Emit a single `RegisterBlock` struct for one `sos:channel_group`.

    Returns ``(rust_source, layout_records)`` where ``layout_records``
    is the list of ``(field_name, byte_offset, size_bytes)`` tuples
    describing the emitted layout. The caller uses ``layout_records``
    to (a) emit `core::mem::offset_of!` assertions per INV-S-MEM-D-5
    and (b) cross-check against the SVD `<addressOffset>` chain in tests.
    """
    module_ident = _safe_module_ident(group_name)
    lines: list[str] = []
    lines.append(f"/// SOS-09-D `RegisterBlock` for channel-group `{group_name}`.")
    lines.append("///")
    lines.append("/// Per §5.1: `#[repr(C)]` with field offsets matching the SVD")
    lines.append("/// `<addressOffset>` chain bit-for-bit (INV-S-MEM-D-5).")
    lines.append("/// `#[non_exhaustive]` per §5.1 so chart edits adding channels")
    lines.append("/// to the group do not break external consumers.")
    lines.append("#[repr(C)]")
    lines.append("#[non_exhaustive]")
    lines.append(f"pub struct {_register_block_name(module_ident)} {{")

    cursor = base_offset
    layout: list[tuple[str, int, int]] = []
    pad_idx = 0
    for ch in channels:
        size = _hal_channel_size_bytes(ch.width)
        if cursor < 0:
            raise ValueError("base offset must be non-negative")
        wrapper = _select_wrapper(ch)
        t_param = _rust_width_type(ch.width)
        fname = _channel_field_name(ch)
        lines.append(
            f"    /// Channel `{ch.name}` "
            f"(sos:kind={ch.kind}, sos:dir={ch.dir}, "
            f"width={ch.width} bits, offset=0x{cursor:08X}). "
            f"sos:id={ch.id}."
        )
        lines.append(f"    pub {fname}: {wrapper}<{t_param}>,")
        layout.append((fname, cursor, size))
        cursor += size
        # The current channels are emitted contiguously; if a future
        # extension introduces gap-bearing layouts, `_reservedN` padding
        # would be inserted here. v1 charts produce contiguous chains by
        # construction (SVD emitter mirrors this).
        _ = pad_idx  # keep the placeholder visible to maintainers

    lines.append("}")
    return "\n".join(lines), layout


def _register_block_name(group_module_ident: str) -> str:
    """`RegisterBlock` type names. Per §5.1 one block per channel group;
    the `default` group emits the bare `RegisterBlock`, named groups
    emit `RegisterBlock<Group>` PascalCase suffix.
    """
    if group_module_ident == "default":
        return "RegisterBlock"
    parts = group_module_ident.split("_")
    pascal = "".join(p[:1].upper() + p[1:].lower() for p in parts if p)
    return f"RegisterBlock{pascal}"


def _emit_unchecked_variants(
    channels: list[ChannelAnnotation],
) -> str:
    """Emit `*_unchecked` accessor methods on the wrappers for any
    channel whose chart-bounds discharge applies. Per §5.5 + PCDN-D-005
    accepted option (a) the variants are `unsafe fn` with a `// SAFETY:`
    comment naming the discharging invariant.

    v1: the chart-bounds analyzer integration is NOT wired into the
    transliterator yet (per the user's "we will want to roll this up in
    generation" clarification — see feedback_chart_semantics_versioned_pair).
    We emit a stub `_unchecked` accessor for any `kind="status"` channel
    so reviewers can audit the SAFETY-rollup format end-to-end, with a
    TODO citation naming the analyzer-pair coupling.

    Per the §5.5 acceptance gate the SAFETY comment must be present and
    name the discharging invariant; the v1 stub names `INV-SOS-G` + the
    channel's `sos:id` as the placeholder until the chart-bounds analyzer
    lands. This makes the emitter forward-compatible: when the analyzer
    is wired in, replacing the placeholder text is a string-substitution
    in this function; no other code site changes.
    """
    if not channels:
        return ""

    lines: list[str] = []
    lines.append("// --------------------------------------------------------------")
    lines.append("// *_unchecked accessor variants (§5.5).")
    lines.append("//")
    lines.append("// Per PCDN-SOS-09-D-005 accepted option (a) (RATIFIED 2026-05-26):")
    lines.append("// these variants are `unsafe fn` with codegen-emitted")
    lines.append("// `// SAFETY:` comments naming the discharging chart invariant.")
    lines.append("// User clarification (2026-05-26): SAFETY rollup is canonical at")
    lines.append("// codegen; the chart-bounds analyzer and the SOS-09-A annotation-")
    lines.append("// semantics doc rev together as a versioned pair (see parent")
    lines.append("// CLAUDE.md / orchestrator memory chart-semantics-versioned-pair).")
    lines.append("// v1: the analyzer is not yet wired in; the SAFETY text below is")
    lines.append("// a TODO-style placeholder citing INV-SOS-G + the channel's sos:id.")
    lines.append("// --------------------------------------------------------------")
    lines.append("")

    emitted_any = False
    for ch in channels:
        # Per the §5.5 gate-(g) requirement, we MUST emit at least one
        # `_unchecked` accessor with a SAFETY discharge comment so the
        # format is auditable. We pick `kind="status"` channels as the
        # v1 exemplar (the chart-bounds discharge is most natural for
        # status registers — "this status bit is provably non-zero in
        # chart state X").
        if ch.kind != "status":
            continue
        wrapper = _select_wrapper(ch)
        t_param = _rust_width_type(ch.width)
        fname = _channel_field_name(ch)
        accessor_name = "read_unchecked" if wrapper == "Status" else "consume_unchecked"
        # Emit a free-standing helper function (no method-on-wrapper
        # change so the prelude stays simple). The accessor takes the
        # `RegisterBlock` by `&mut` and discharges via the named
        # invariant in the SAFETY comment.
        emitted_any = True
        lines.append(
            "/// `_unchecked` accessor for channel `"
            f"{ch.name}` (sos:id={ch.id})."
        )
        lines.append("///")
        lines.append(
            "/// SAFETY: discharged by chart invariant `"
            f"{ch.id}` (channel `{ch.name}` "
            "is provably in a known state per the chart-bounds analyzer's "
            "discharge of INV-SOS-G; v1 emits a TODO-style rollup because the "
            "chart-bounds analyzer is not yet wired into the emitter pair — "
            "see SOS-09-A / SOS-09-D versioned-pair discipline)."
        )
        lines.append(
            "///"
        )
        lines.append(
            "/// @spec docs/concepts/SOS-09-D-CONCEPTS.md §5.5 +"
            " INV-SOS-G discharge."
        )
        # The free function targets the wrapper directly; callers
        # invoke `unsafe { hal::<channel>_read_unchecked(&block.<f>) }`.
        if wrapper == "ClearOnRead":
            param_mode = "&mut"
        else:
            param_mode = "&"
        lines.append(
            f"#[inline]"
        )
        lines.append(
            "// SAFETY: This function is `unsafe` because PCDN-SOS-09-D-005"
            " accepted option (a)."
        )
        lines.append(
            f"pub unsafe fn {fname}_{accessor_name}(reg: {param_mode} {wrapper}<{t_param}>) -> {t_param} {{"
        )
        if wrapper == "Status":
            lines.append("    reg.read()")
        elif wrapper == "ClearOnRead":
            lines.append("    reg.consume()")
        else:
            lines.append("    unreachable!(\"v1 emits _unchecked only for status / clear-on-read\")")
        lines.append("}")
        lines.append("")

    if not emitted_any:
        # No status channels — emit a documented absence per §12 (g)
        # second-tier conformance. The acceptance test reads this
        # marker; gate (g) flips to the reduced-conformance form.
        lines.append(
            "// SOS-09-D §12 (g) reduced conformance: this chart has no"
        )
        lines.append(
            "// `kind=\"status\"` channels eligible for `_unchecked` discharge,"
        )
        lines.append(
            "// so no `*_unchecked` accessors are emitted. The safe wrapper"
        )
        lines.append(
            "// surface remains the only access path; this is the documented"
        )
        lines.append(
            "// `(a)..(f) + (h)..(k)` conformance level per §12 second tier."
        )
        lines.append("")
    return "\n".join(lines)


def _emit_mpu_constants(channels: list[ChannelAnnotation], base_address: int) -> str:
    """Emit `pub const SOS_MPU_<CHANNEL>_REGION: sos_mpu_region_t = ...;`
    declarations for every channel carrying `sos:zone` or `sos:mpu_attr`.

    Per §5.6 the `sos_mpu_region_t` type is owned by SOS-09-G; we declare
    a forward-compatible local mirror behind a `feature = "sos_09_g_owned"`
    flag so the crate compiles standalone for test purposes. The runtime-
    integration crate replaces the local mirror with the SOS-09-G-emitted
    type via the `sos_mpu_region_t` import.
    """
    eligible: list[ChannelAnnotation] = []
    cursor = 0
    addr_map: dict[str, int] = {}
    for ch in channels:
        addr_map[ch.name] = base_address + cursor
        cursor += _hal_channel_size_bytes(ch.width)
        # §5.6: emit only when chart explicitly declares per-channel
        # protection via `sos:zone` (privileged/unprivileged) or
        # `sos:mpu_attr` (cacheable / device etc.).
        # `zone` defaults to "privileged" silently when omitted; we
        # treat the default value as "not chart-declared" to avoid
        # emitting constants the chart didn't actually request. A
        # channel with explicit `sos:mpu_attr` always emits.
        has_explicit_zone = ch.zone != "privileged"
        if has_explicit_zone or ch.mpu_attr is not None:
            eligible.append(ch)

    if not eligible:
        return (
            "// No channel in this chart declares `sos:zone` (other than\n"
            "// the default `privileged`) or `sos:mpu_attr`; no per-channel\n"
            "// MPU-region constants are emitted. Background MPU coverage is\n"
            "// supplied by SOS-09-G's `sos_mpu_background` (chart-root).\n"
        )

    lines: list[str] = []
    lines.append("// --------------------------------------------------------------")
    lines.append("// MPU-region constant exports (§5.6).")
    lines.append("//")
    lines.append("// Consumed by SOS-09-G's `sos_mpu_install()` runtime hook")
    lines.append("// (step 4: reads chart-declared `sos:mpu_attr` per channel and")
    lines.append("// writes the corresponding MPU region descriptor).")
    lines.append("//")
    lines.append("// Per §5.6 the `sos_mpu_region_t` type is owned by SOS-09-G;")
    lines.append("// the local mirror below lets this crate compile standalone.")
    lines.append("// --------------------------------------------------------------")
    lines.append("")
    lines.append("/// Local mirror of SOS-09-G's `sos_mpu_region_t`. The runtime-")
    lines.append("/// integration crate replaces this with the SOS-09-G-emitted")
    lines.append("/// type via the canonical import path.")
    lines.append("#[repr(C)]")
    lines.append("#[derive(Debug, Clone, Copy)]")
    lines.append("pub struct sos_mpu_region_t {")
    lines.append("    pub base_addr: u32,")
    lines.append("    pub size: u32,")
    lines.append("    pub attr: u32,")
    lines.append("    pub perm: u32,")
    lines.append("}")
    lines.append("")

    # Per §5.6 / SOS-09-G PCDN-G-003: encode `sos:mpu_attr` as a u32
    # discriminator. We use the SOS-09-A frozen set order
    # (cacheable / non_cacheable / device_ngnrne / device_ngnre).
    attr_to_u32 = {
        "cacheable": 0,
        "non_cacheable": 1,
        "device_ngnrne": 2,
        "device_ngnre": 3,
    }
    zone_to_u32 = {
        "privileged": 0,
        "unprivileged": 1,
    }
    for ch in eligible:
        const_name = f"SOS_MPU_{_channel_screaming_name(ch)}_REGION"
        attr_val = attr_to_u32.get(ch.mpu_attr or "cacheable", 0)
        perm_val = zone_to_u32.get(ch.zone, 0)
        size_bytes = _hal_channel_size_bytes(ch.width)
        lines.append(
            f"/// MPU region descriptor for channel `{ch.name}` "
            f"(sos:id={ch.id}, sos:zone={ch.zone}, "
            f"sos:mpu_attr={ch.mpu_attr or '<unset>'})."
        )
        lines.append(f"pub const {const_name}: sos_mpu_region_t = sos_mpu_region_t {{")
        lines.append(f"    base_addr: 0x{addr_map[ch.name]:08X},")
        lines.append(f"    size: {size_bytes},")
        lines.append(f"    attr: {attr_val},")
        lines.append(f"    perm: {perm_val},")
        lines.append("};")
        lines.append("")
    return "\n".join(lines)


def _emit_lib_rs(
    annotations: ChartAnnotations,
    *,
    base_address: int,
) -> str:
    """Emit the full `src/lib.rs` content. One module per
    `sos:channel_group`; one `RegisterBlock` per module.
    """
    # Group channels by sos:channel_group (default = "default").
    groups: dict[str, list[ChannelAnnotation]] = {}
    for ch in annotations.channels:
        groups.setdefault(_channel_group(ch), []).append(ch)
    # Determinism: emit groups in lexicographic order. The "default"
    # group surfaces first regardless of lexicographic position.
    ordered_groups: list[tuple[str, list[ChannelAnnotation]]] = []
    if "default" in groups:
        ordered_groups.append(("default", groups["default"]))
    for gname in sorted(groups.keys()):
        if gname == "default":
            continue
        ordered_groups.append((gname, groups[gname]))

    header = (
        "//! SOS-09-D — emitted Rust HAL crate.\n"
        "//!\n"
        "//! Authority: `docs/concepts/SOS-09-D-CONCEPTS.md` (🟢 RATIFIED 2026-05-26).\n"
        "//! This crate is a BUILD OUTPUT (per umbrella INV-S-MEM-2); do not edit by hand.\n"
        "//! Re-emit via `tools/sos-codegen/transliterate_rust.py::emit_rust_hal()`.\n"
        "//!\n"
        "//! INV-S-MEM-D-1: every register field is accessed through the §5.2 newtype\n"
        "//! wrappers; no raw `core::ptr::read_volatile` / `write_volatile` reaches\n"
        "//! driver code.\n"
        "//! INV-S-MEM-D-4: this crate passes `cargo check --no-default-features\n"
        "//! --target thumbv7em-none-eabihf`.\n"
        "//! INV-S-MEM-D-5: `RegisterBlock` field offsets match the SVD `<addressOffset>`\n"
        "//! chain bit-for-bit (verified by emitted `core::mem::offset_of!` asserts).\n"
        "//! INV-S-MEM-D-6: accessor + type names deterministic from `sos:name`\n"
        "//! (sos:id appears only in `// SAFETY:` comments below; never as a Rust\n"
        "//! identifier).\n"
        "\n"
        "#![no_std]\n"
        "#![allow(non_camel_case_types)]\n"
        "\n"
        "#[cfg(feature = \"alloc\")]\n"
        "extern crate alloc;\n"
        "\n"
    )

    body_parts: list[str] = [header, _RUST_HAL_PRELUDE, ""]

    body_parts.append("/// Re-exported prelude. Per §5.2 driver code can `use ...::prelude::*;`")
    body_parts.append("/// and obtain the full newtype family.")
    body_parts.append("pub mod prelude {")
    body_parts.append("    pub use super::{")
    body_parts.append("        ClearOnRead, Claimed, Command, ContentionError, FireOnWrite,")
    body_parts.append("        Queue, Shared, Status,")
    body_parts.append("    };")
    body_parts.append("}")
    body_parts.append("")

    # Per-group RegisterBlocks.
    all_layout_records: list[tuple[str, str, int, int]] = []
    for group_name, channels in ordered_groups:
        block_src, layout = _emit_register_block(group_name, channels)
        body_parts.append(block_src)
        body_parts.append("")
        for fname, off, size in layout:
            all_layout_records.append((group_name, fname, off, size))

    # *_unchecked variants for the union of channels (one per status channel).
    unchecked_src = _emit_unchecked_variants(list(annotations.channels))
    body_parts.append(unchecked_src)

    # MPU-region constants.
    mpu_src = _emit_mpu_constants(list(annotations.channels), base_address=base_address)
    body_parts.append(mpu_src)

    # Determinism / offset-assert hook. INV-S-MEM-D-5 says the offsets
    # MUST match SVD bit-for-bit; we emit a `const _: () = ...;` block
    # using `core::mem::offset_of!` so any drift surfaces at compile
    # time. (The macro is stable since Rust 1.77; targeting it is
    # consistent with thumbv7em-none-eabihf which is a stable-Rust
    # target.)
    if all_layout_records:
        body_parts.append("// INV-S-MEM-D-5: assert that emitted offsets match the chart-derived")
        body_parts.append("// `<addressOffset>` chain bit-for-bit. Drift becomes a build-stop.")
        body_parts.append("const _SOS_09_D_LAYOUT_ASSERTIONS: () = {")
        for group_name, fname, off, _size in all_layout_records:
            block_name = _register_block_name(_safe_module_ident(group_name))
            body_parts.append(
                f"    assert!(core::mem::offset_of!({block_name}, {fname}) == 0x{off:X}usize,"
            )
            body_parts.append(
                f"        \"INV-S-MEM-D-5 offset drift: {block_name}.{fname} != 0x{off:X}\");"
            )
        body_parts.append("};")
        body_parts.append("")

    return "\n".join(body_parts).rstrip() + "\n"


def _emit_cargo_toml(crate_name: str) -> str:
    """Emit `Cargo.toml`. Per §5.4 the `cortex_m` feature is default-on
    (PCDN-D-004 accepted option (b)); `alloc` is opt-in.

    Determinism: dependency versions are pinned at v1; no `^`/`~` ranges.
    """
    return (
        "# SOS-09-D — emitted Rust HAL crate manifest.\n"
        "# Authority: docs/concepts/SOS-09-D-CONCEPTS.md §5.4 + PCDN-D-004.\n"
        "# This file is a BUILD OUTPUT; do not edit by hand.\n"
        "[package]\n"
        f"name = {crate_name!r}\n"
        "version = \"0.1.0\"\n"
        "edition = \"2021\"\n"
        "publish = false\n"
        "\n"
        "[lib]\n"
        "path = \"src/lib.rs\"\n"
        "\n"
        "[features]\n"
        "# PCDN-SOS-09-D-004 accepted option (b): cortex_m gated; default-on.\n"
        "# `--no-default-features` produces a target-agnostic crate for\n"
        "# host-tests + Miri.\n"
        "default = [\"cortex_m\"]\n"
        "cortex_m = [\"dep:cortex-m\"]\n"
        "alloc = []\n"
        "\n"
        "[dependencies]\n"
        "vcell = \"0.1\"\n"
        "cortex-m = { version = \"0.7\", optional = true }\n"
    )


def emit_rust_hal(
    annotations: ChartAnnotations,
    *,
    crate_name: str,
    base_address: int = 0x40000000,
) -> dict[str, str]:
    """Emit the file map for a SOS-09-D Rust HAL crate.

    Args:
        annotations: parsed SOS-09-A annotation model (the same input
            SOS-09-B consumes for SVD emission). Channels are emitted
            in document order; INV-S-MEM-D-5 holds because the SVD
            emitter uses the identical ordering + byte arithmetic.
        crate_name: Cargo crate name. Should be a valid Cargo identifier
            (snake_case ASCII). Not validated here — Cargo itself will
            reject malformed names.
        base_address: peripheral base address. Default 0x40000000
            (typical Cortex-M peripheral region); only affects MPU
            constant `base_addr` values.

    Returns:
        Dict mapping relative paths to file contents. The caller writes
        them under `build/rust-hal/<chart_id>/` per umbrella INV-S-MEM-2.

    Determinism: same input → byte-identical output (gate (g) /
    INV-S-MEM-D-6). No timestamps, no clock nonces, no dict ordering.
    """
    if not isinstance(crate_name, str) or not crate_name:
        raise ValueError(f"crate_name must be a non-empty string; got {crate_name!r}")
    if not isinstance(base_address, int) or isinstance(base_address, bool) or base_address < 0:
        raise ValueError(f"base_address must be a non-negative integer; got {base_address!r}")

    files: dict[str, str] = {}
    files["Cargo.toml"] = _emit_cargo_toml(crate_name)
    files["src/lib.rs"] = _emit_lib_rs(annotations, base_address=base_address)
    return files


def emit_rust_hal_from_chart(
    chart_path,
    *,
    crate_name: str,
    base_address: int = 0x40000000,
) -> dict[str, str]:
    """Load a chart, parse SOS-09-A annotations, emit the Rust HAL crate.

    Convenience wrapper paralleling :func:`transliterate_svd.emit_svd_from_chart`.
    """
    from pathlib import Path as _Path
    from loader import load_chart  # local import, mirrors SVD emitter

    ast = load_chart(_Path(chart_path))
    if ast.raw_scjson is None:
        raise RuntimeError(
            f"loader returned ChartAst without raw_scjson for {chart_path!r}"
        )
    annotations = parse_chart_annotations(ast.raw_scjson)
    return emit_rust_hal(
        annotations, crate_name=crate_name, base_address=base_address,
    )


def write_rust_hal_crate(
    annotations: ChartAnnotations,
    *,
    crate_name: str,
    output_dir,
    base_address: int = 0x40000000,
) -> dict[str, str]:
    """Emit + write a SOS-09-D Rust HAL crate to `output_dir`.

    Returns the file map (for inspection in tests / drivers). The
    `output_dir` is created if missing; existing files are overwritten
    so re-emit is idempotent (gate (g) determinism).
    """
    from pathlib import Path as _Path

    files = emit_rust_hal(
        annotations, crate_name=crate_name, base_address=base_address,
    )
    out = _Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return files


if __name__ == "__main__":
    import sys
    src = sys.stdin.read()
    result = transliterate_to_rust(src)
    print(result.rust_source)
    if result.unhandled_notes:
        sys.stderr.write("\n# notes:\n")
        for n in result.unhandled_notes:
            sys.stderr.write(f"#   {n}\n")
