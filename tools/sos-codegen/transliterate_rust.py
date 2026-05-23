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
    source: str, event_name: str | None = None
) -> TransliterationResult:
    """Parse ECMAScript source, emit Rust statements.

    `event_name` is the chart event the site dispatches on (e.g.
    `task.create`); when provided, a typed-match preamble extracts the
    `EventData` payload as locals before the transliterated body runs.

    Returns the emitted Rust source (preamble + body), a list of notes
    flagging unhandled-construct fallbacks, and a `needs_ev_param`
    flag the caller uses to bind `ev` vs `_ev` in the function signature.
    """
    program = esprima.parseScript(source)
    preamble, bound_fields = emit_eventdata_extract(event_name)
    emitter = RustEmitter(bound_event_fields=bound_fields)
    lines: list[str] = []
    if preamble:
        lines.append(preamble)
    for stmt in program.body:
        lines.append(emitter.emit_stmt(stmt))
    return TransliterationResult(
        rust_source="\n".join(lines),
        unhandled_notes=emitter._notes,
        preamble=preamble,
        needs_ev_param=bool(preamble),
    )


if __name__ == "__main__":
    import sys
    src = sys.stdin.read()
    result = transliterate_to_rust(src)
    print(result.rust_source)
    if result.unhandled_notes:
        sys.stderr.write("\n# notes:\n")
        for n in result.unhandled_notes:
            sys.stderr.write(f"#   {n}\n")
