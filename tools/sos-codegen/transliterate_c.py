"""ECMAScript → C transliterator for sos-codegen.

C analogue of `transliterate_rust.py`. Consumes the same constrained
ECMAScript subset and emits C source matching the bench-validated
hand-written reference at `ports/m7-c/sos-m7-c/src/scripts.c`.

The C port realises the chart's datamodel as a `struct sos_datamodel`
the script bodies access via a `dm` pointer (set from
`sos_kernel_state()` at the top of each function). The chart's HELPERS
block becomes the file-static `dm_*` helper functions (e.g.
`ready_push` → `dm_ready_push(dm, ...)`); free identifiers like `tcb`,
`ready`, `current` become `dm->tcb`, `dm->ready_pool[...]`, `dm->current`.

# Naming map (chart → C port)

* `tcb`         → `dm->tcb`
* `current`     → `dm->current`
* `tick_count`  → `dm->tick_count`
* `resched`     → `dm->resched`
* `irq_nest`    → `dm->irq_nest`
* `sched_lock`  → `dm->sched_lock`
* `pend_ticks`  → `dm->pend_ticks`
* `sems`        → `dm->sems`
* `queues`      → `dm->queues`
* `rc`          → `dm->rc`  (with `(sos_rc_t)` cast on assignment from
                             an RC_* literal)
* `ready`       — accessed only through HELPERS in the chart; no direct
                  reference appears in transition scripts.

# Helpers (chart → C port)

* `ready_push(t)`           → `dm_ready_push(dm, t)`
* `ready_remove(t)`         → `dm_ready_remove(dm, t)`
* `ready_pop_highest()`     → `dm_ready_pop_highest(dm)`
* `waiters_insert(arr, t)`  → STUB (needs site-aware arr → arr+count split)
* `block_current(s, o, d)`  → `dm_block_current(dm, s, o, d)`
* `unblock(t)`              → `dm_unblock(dm, (sos_task_id_t)t)`
* `waiter_cancel(t)`        → `dm_waiter_cancel(dm, (sos_task_id_t)t)`
* `pick_next()`             → `dm_pick_next(dm)`

# Constants (chart → C port)

* `ST_*`                    → `SOS_ST_*`
* `RC_*`                    → `SOS_RC_*`
* `MAX_TASKS`               → `SOS_MAX_TASKS` (etc.)
* `Q_DEPTH`                 → `SOS_Q_DEPTH`

# EventData typed-union preamble

When the caller passes `event_name`, the transliterator emits a
preamble that mirrors the hand-written port's tag-check + typed local
binding:

    if (ev->data.tag != SOS_EVD_TASK_CREATE) {
        dm->rc = (sos_rc_t)SOS_RC_INVAL;
        return false;
    }
    sos_task_id_t id   = ev->data.u.task_create.id;
    uint8_t       prio = ev->data.u.task_create.prio;

Chart references like `_event.data.id` (or `d.id` after
`var d = _event.data;`) then resolve to the bound local `id`.

# Scope (v0)

Same statement subset as the Rust transliterator (VariableDeclaration,
AssignmentExpression, UpdateExpression, IfStatement, ForStatement,
WhileStatement, CallExpression, MemberExpression, BinaryExpression,
LogicalExpression, UnaryExpression, ConditionalExpression, Literal,
Identifier, ReturnStatement, BlockStatement).

# Deferred (v0 falls back to stub)

* `ObjectExpression` — struct literals (e.g. boot's tcb pool init).
* `ArrayExpression` — empty arrays, etc.
* `arr.splice(idx, 1)` / `arr.shift()` / `arr.indexOf(x)` /
  `arr.length` / `arr.push(...)` — these require site-aware knowledge
  of which `dm->X[i].arr + arr_count` pair the JS `arr` aliases. The
  hand-written port inlines the array-management code at each site
  because the JS uses object-as-local-alias (e.g.
  `var s = sems[d.sid]; s.waiters.shift();`).
* Local struct-aliases like `var t = tcb[i];` — JS treats this as a
  reference to the struct, but C treats it as a copy. The
  transliterator emits the literal `int32_t t = dm->tcb[i];` which is
  structurally wrong; sites that rely on local-struct-mutation
  through the alias additionally trip the `.length` / `.push` notes
  and end up stubbed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import esprima


# Datamodel identifiers (per rtos_kernel.scxml <datamodel>) that need
# a `dm->` prefix when they appear as free references in script bodies.
DATAMODEL_NAMES = {
    "tcb", "ready", "current", "tick_count", "resched",
    "irq_nest", "sched_lock", "pend_ticks", "sems", "queues", "rc",
}

# Helper functions from the chart's HELPERS block; these become
# `dm_<name>(dm, args)` free calls in the C port.
HELPER_NAMES = {
    "readyq_init", "ready_push", "ready_remove", "ready_pop_highest",
    "waiters_insert", "block_current", "unblock", "waiter_cancel",
    "pick_next",
}

# Helpers the C port does not realise as a simple `dm_<name>(dm, ...)`
# call (because they touch arrays the JS aliases through locals).
# Mark these as stub-only.
#
# `readyq_init` is NOT in this set: the hand-written `scripts.c`
# inlines readyq-clear inside `sos_kernel_init`, but `embed_c_runtime`
# appends a supplementary `dm_readyq_init(struct sos_datamodel *dm)`
# stub so the codegen-emitted `boot.onentry` body can call it
# uniformly. Mirrors the Rust port's `impl Datamodel` supplement
# (see `transliterate_rust.py::embed_rust_runtime`).
HELPER_NEEDS_SITE_REWRITE = {
    "waiters_insert",
}

# Chart constants — these become SOS_-prefixed identifiers in the C
# port (defined in `sos/types.h`).
CONSTANT_NAMES = {
    "MAX_TASKS", "MAX_PRIO", "MAX_SEMS", "MAX_QUEUES", "Q_DEPTH",
    "ST_DORMANT", "ST_READY", "ST_RUNNING", "ST_DELAY",
    "ST_BLK_SEM", "ST_BLK_QS", "ST_BLK_QR", "ST_SUSPEND",
    "RC_OK", "RC_TIMEOUT", "RC_FULL", "RC_EMPTY", "RC_INVAL",
}

# Map chart ST_* / RC_* constants onto the C-port enum surface.
ST_TO_C = {
    "ST_DORMANT":  "SOS_ST_DORMANT",
    "ST_READY":    "SOS_ST_READY",
    "ST_RUNNING":  "SOS_ST_RUNNING",
    "ST_DELAY":    "SOS_ST_DELAY",
    "ST_BLK_SEM":  "SOS_ST_BLK_SEM",
    "ST_BLK_QS":   "SOS_ST_BLK_QS",
    "ST_BLK_QR":   "SOS_ST_BLK_QR",
    "ST_SUSPEND":  "SOS_ST_SUSPEND",
}
RC_TO_C = {
    "RC_OK":      "SOS_RC_OK",
    "RC_TIMEOUT": "SOS_RC_TIMEOUT",
    "RC_FULL":    "SOS_RC_FULL",
    "RC_EMPTY":   "SOS_RC_EMPTY",
    "RC_INVAL":   "SOS_RC_INVAL",
}
MAX_TO_C = {
    "MAX_TASKS":  "SOS_MAX_TASKS",
    "MAX_PRIO":   "SOS_MAX_PRIO",
    "MAX_SEMS":   "SOS_MAX_SEMS",
    "MAX_QUEUES": "SOS_MAX_QUEUES",
    "Q_DEPTH":    "SOS_Q_DEPTH",
}


# Pointer-element types for the chart's bounded-array datamodel
# entries, used when realising a `var t = tcb[i];` style struct-
# reference alias as a C pointer (`sos_tcb_t *t = &dm->tcb[i];`).
# Sourced from `ports/m7-c/sos-m7-c/include/sos/types.h`.
_STRUCT_POINTER_TYPES: dict[str, str] = {
    "tcb":    "sos_tcb_t",
    "sems":   "sos_sem_t",
    "queues": "sos_queue_t",
}


# When an empty-array reset `<expr>.<field> = []` lands on one of the
# chart's bounded waiter-list fields, the C port realises the storage
# as a `<field>` array plus a `<field>_count` counter (or, for the
# queue buf, just the queue's outer `count`). Reset semantics in C
# reduce to setting the count to zero — the storage itself need not
# be cleared. The chart-field → C count-field mapping below mirrors
# the hand-written reference at `ports/m7-c/sos-m7-c/src/scripts.c`
# and the struct layouts in `sos/types.h::sos_sem_t / sos_queue_t`.
_EMPTY_ARRAY_RESET_COUNT_FIELD: dict[str, str] = {
    "waiters": "waiter_count",
    "sendw":   "sendw_count",
    "recvw":   "recvw_count",
    # `q.buf = []` resets the queue's outer `count` (there is no
    # `buf_count` member — the queue's `count` IS buf's count).
    "buf":     "count",
}


# Site-aware metadata for the chart's bounded waiter-list / buffer
# fields on the `sos_sem_t` / `sos_queue_t` structs. Used by the
# struct-pointer-alias path to realise JS array-method calls
# (`<alias>.<wlist>.shift()` / `.length` / `.push(...)`) and
# `waiters_insert(<alias>.<wlist>, tid)` against the corresponding
# `(<field>[], <count_field>)` storage. The element type is the
# array's C element type, needed for the temp-variable declaration in
# the `shift()` expansion. Source of truth: `sos/types.h::sos_sem_t /
# sos_queue_t`. Per the chart's HELPERS block, only these four field
# names are ever the target of array methods; any other `<alias>.<X>`
# member access stays on the regular MemberExpression path.
_WAITER_LIST_INFO: dict[str, tuple[str, str]] = {
    # (count_field_name, element_c_type)
    "waiters": ("waiter_count", "sos_task_id_t"),
    "sendw":   ("sendw_count",  "sos_task_id_t"),
    "recvw":   ("recvw_count",  "sos_task_id_t"),
    # `q.buf` is the queue's int64 ring buffer; its count IS the
    # queue's outer `count` member (see SOS-05 §6.3).
    "buf":     ("count",        "int64_t"),
}


# Per-event-name tagged-union variant and the field set the chart can
# name. Source: ports/m7-c/sos-m7-c/include/sos/event.h::sos_event_data_t.
# Third tuple element is per-field C type (matches the union struct).
EVENTDATA_VARIANTS: dict[str, tuple[str, str, list[tuple[str, str]]]] = {
    "task.create": (
        "SOS_EVD_TASK_CREATE",
        "task_create",
        [("id", "sos_task_id_t"), ("prio", "uint8_t")],
    ),
    "task.delay": (
        "SOS_EVD_TASK_DELAY",
        "task_delay",
        [("ticks", "int64_t")],
    ),
    "task.suspend": (
        "SOS_EVD_TASK_ID",
        "task_id",
        [("id", "sos_task_id_t")],
    ),
    "task.resume": (
        "SOS_EVD_TASK_ID",
        "task_id",
        [("id", "sos_task_id_t")],
    ),
    "sem.create": (
        "SOS_EVD_SEM_CREATE",
        "sem_create",
        [("id", "int16_t"), ("initial", "uint32_t"), ("max", "uint32_t")],
    ),
    "sem.take": (
        "SOS_EVD_SEM_OP",
        "sem_op",
        [("sid", "int16_t"), ("timeout", "int64_t")],
    ),
    "sem.give": (
        "SOS_EVD_SEM_OP",
        "sem_op",
        [("sid", "int16_t"), ("timeout", "int64_t")],
    ),
    "sem.give_from_isr": (
        "SOS_EVD_SEM_OP",
        "sem_op",
        [("sid", "int16_t"), ("timeout", "int64_t")],
    ),
    "queue.create": (
        "SOS_EVD_QUEUE_CREATE",
        "queue_create",
        [("id", "int16_t"), ("cap", "uint32_t")],
    ),
    "queue.send": (
        "SOS_EVD_QUEUE_SEND",
        "queue_send",
        [("qid", "int16_t"), ("msg", "int64_t"), ("timeout", "int64_t")],
    ),
    "queue.receive": (
        "SOS_EVD_QUEUE_RECEIVE",
        "queue_receive",
        [("qid", "int16_t"), ("timeout", "int64_t")],
    ),
    "queue.send_from_isr": (
        "SOS_EVD_QUEUE_SEND",
        "queue_send",
        [("qid", "int16_t"), ("msg", "int64_t"), ("timeout", "int64_t")],
    ),
}


def emit_eventdata_preamble(event_name: str | None) -> tuple[str, set[str]]:
    """Emit the tag-check + typed-local preamble for a chart event.

    Returns (preamble_text, set_of_bound_field_names). When `event_name`
    is None or its variant is unknown, returns empty preamble + empty
    set — the function uses `ev` only as `(void)ev;`."""
    if event_name is None or event_name not in EVENTDATA_VARIANTS:
        return ("", set())
    tag, variant, fields = EVENTDATA_VARIANTS[event_name]
    indent = "    "
    lines: list[str] = []
    lines.append(f"{indent}if (ev->data.tag != {tag}) {{")
    lines.append(f"{indent}    dm->rc = (sos_rc_t)SOS_RC_INVAL;")
    lines.append(f"{indent}    return false;")
    lines.append(f"{indent}}}")
    # Width the type column for tidy alignment (mirrors the hand-
    # written port's spacing).
    if fields:
        width = max(len(ty) for _, ty in fields)
        for name, ty in fields:
            lines.append(
                f"{indent}{ty:<{width}} {name} = ev->data.u.{variant}.{name};"
            )
        # Suppress -Werror=unused-variable for bound fields the chart
        # script's body doesn't reference (e.g. `sem.give` extracts the
        # `timeout` field via the shared SOS_EVD_SEM_OP variant but the
        # chart body never names it). `(void)X;` is a no-op for fields
        # that are referenced and silences the diagnostic for fields
        # that aren't.
        for name, _ in fields:
            lines.append(f"{indent}(void){name};")
    return ("\n".join(lines), {name for name, _ in fields})


@dataclass
class TransliterationResult:
    c_source: str
    unhandled_notes: list[str] = field(default_factory=list)
    # The preamble (tag-check + typed extraction); empty when the
    # event has no payload variant.
    preamble: str = ""
    # True when the function should bind `ev` (vs only `(void)ev;`).
    needs_ev_param: bool = False


class CEmitter:
    """ESTree → C string emitter. Single-pass, recursive descent.

    Maintains a small lexical context to know when an identifier refers
    to a datamodel field (needs `dm->` prefix) vs a local variable
    (introduced by `var` or as a `for`-loop counter).

    `bound_event_fields` is the set of fields extracted from
    `_event.data` upfront by the preamble; chart references like
    `_event.data.id` resolve to the bound local `id` (no `ev->data.u`
    prefix needed at the use site)."""

    def __init__(self, bound_event_fields: set[str] | None = None) -> None:
        self._locals: list[set[str]] = [set()]
        self._notes: list[str] = []
        self._bound_event_fields = bound_event_fields or set()
        # Locals that alias `_event.data` via `var d = _event.data;`.
        # When we see `d.field` for such an alias, treat it as
        # `_event.data.field` for bound-field resolution.
        self._event_data_aliases: set[str] = set()
        # Locals declared as `var <name> = tcb[<expr>];` (or sems/queues).
        # JS treats this as a struct *reference*; C must realise it as a
        # pointer so subsequent `<name>.field` mutations propagate. The
        # value is the underlying datamodel array name (`"tcb"` etc.) —
        # MemberExpression emission uses `->` rather than `.` for these.
        self._struct_pointer_aliases: dict[str, str] = {}
        # Locals declared as the result of a waiter-list / buf shift()
        # expansion (or otherwise known to be the element type of one
        # of the bounded waiter-list arrays). These are int-typed in C
        # (either `sos_task_id_t` for waiter lists or `int64_t` for
        # `q.buf`); when they appear as the RHS of `<lvalue>.msg = ...`
        # the assignment expands to a tagged-INT write rather than a
        # struct copy. Value is the element's C type for the temp
        # declaration.
        self._int_typed_locals: dict[str, str] = {}
        # Track whether the body actually references `ev` directly
        # (i.e. `_event` outside of pre-bound `_event.data.<field>`
        # accesses).
        self._uses_ev = False
        # Name of the innermost for-loop's induction variable. Used by
        # the `<coll>.push({...})` pattern (chart boot.onentry) which
        # writes to `dm->coll[(size_t)(i)] = (<struct>){ ... };`. The
        # chart always uses `i` by convention, but we track it
        # explicitly so the pattern survives chart-side renaming.
        self._current_for_var: str | None = None

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

    # ----- waiter-list-on-struct-alias resolution -----

    def _resolve_waiter_list(self, node: Any) -> tuple[str, str, str, str] | None:
        """If `node` is a `<alias>.<wlist>` MemberExpression where
        `<alias>` is a struct-pointer alias (bound via `var x = sems[i]`
        or queues / tcb) and `<wlist>` is one of the chart's bounded
        waiter-list / buf fields, return:
            (alias_name, list_field, count_field, elem_c_type)
        else return None. Used by `.length`, `.shift()`, `.push(...)`,
        and `waiters_insert(...)` site rewrites."""
        if (
            node.type != "MemberExpression"
            or node.computed
            or node.object.type != "Identifier"
            or node.object.name not in self._struct_pointer_aliases
            or node.property.name not in _WAITER_LIST_INFO
        ):
            return None
        alias = node.object.name
        list_field = node.property.name
        count_field, elem_c_type = _WAITER_LIST_INFO[list_field]
        return (alias, list_field, count_field, elem_c_type)

    # ----- expression emission -----

    def emit_expr(self, node: Any) -> str:
        t = node.type
        if t == "Literal":
            v = node.value
            if v is None:
                self._note("null literal not representable in C tagged-union ports")
                return "/* null */ 0"
            if isinstance(v, bool):
                return "true" if v else "false"
            return node.raw
        if t == "Identifier":
            name = node.name
            if name == "_event":
                # Bare `_event` → `ev`; almost always followed by `.data.<field>`.
                self._uses_ev = True
                return "ev"
            if name in ST_TO_C:
                return ST_TO_C[name]
            if name in RC_TO_C:
                return RC_TO_C[name]
            if name in MAX_TO_C:
                return MAX_TO_C[name]
            if name in CONSTANT_NAMES:
                return name  # safety net; should be in one of the maps above
            if self._is_local(name):
                return name
            if name in HELPER_NAMES:
                # Helper-as-value is rare; emit the dm_-prefixed name
                # and let the call-site format args.
                return f"dm_{name}"
            if name in DATAMODEL_NAMES:
                return f"dm->{name}"
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
            obj_node = node.object
            # Struct-pointer alias: `<alias>.<field>` → `<alias>->{field}`
            # when `<alias>` was declared via `var <alias> = tcb[<expr>];`
            # (or sems/queues). The alias is a `<type>*` in C, so member
            # access uses the arrow operator.
            if (
                not node.computed
                and obj_node.type == "Identifier"
                and obj_node.name in self._struct_pointer_aliases
            ):
                prop_pa = node.property.name
                return f"{obj_node.name}->{prop_pa}"
            # `<alias>.<wlist>.length` — bounded waiter-list / buf count.
            # Recognised before the generic `.length` fallback so the
            # struct-pointer alias path resolves directly to the
            # corresponding `_count` field (or queue's outer `count`
            # for `q.buf`). Mirrors the hand-written reference at
            # `ports/m7-c/sos-m7-c/src/scripts.c`.
            if (
                not node.computed
                and node.property.name == "length"
            ):
                info = self._resolve_waiter_list(obj_node)
                if info is not None:
                    alias_name, _list_field, count_field, _elem = info
                    return f"{alias_name}->{count_field}"
            obj = self.emit_expr(obj_node)
            if node.computed:
                idx = self.emit_expr(node.property)
                # Array indexing — cast index to size_t for clarity.
                return f"{obj}[(size_t)({idx})]"
            prop = node.property.name
            # `_event.data` → `ev->data` (`ev` is a pointer in C port).
            if obj == "ev":
                return f"ev->{prop}"
            # `arr.length` → not generally translatable in C without
            # site-aware knowledge of the bounded-array's count field.
            if prop == "length":
                self._note(
                    f"`.length` access on `{obj}` requires site-aware count field"
                )
                return f"/* TODO_TRANSLIT: {obj}.length */"
            # Pointer-vs-value access: `dm->X` already dereferences via
            # the dm pointer, so `dm->X.Y` is correct C (X is a struct
            # member, Y is a field of that struct). Plain `obj.prop`
            # works for the locals case (`d.id` after `var d = ev->data`).
            return f"{obj}.{prop}"
        if t == "BinaryExpression":
            left = self.emit_expr(node.left)
            right = self.emit_expr(node.right)
            op = node.operator
            # `==` / `!=` are valid in C, no translation needed.
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
            return f"(({test}) ? ({cons}) : ({alt}))"
        if t == "CallExpression":
            return self._emit_call(node)
        if t == "AssignmentExpression":
            return self._emit_assign_as_expr(node)
        if t == "UpdateExpression":
            return self._emit_update_as_expr(node)
        if t == "ObjectExpression":
            self._note("object literal — needs typed-struct binding (stub)")
            return "/* TODO_TRANSLIT: object literal */ {0}"
        if t == "ArrayExpression":
            if not node.elements:
                self._note("empty array literal — needs site-aware reset")
                return "/* TODO_TRANSLIT: [] */"
            self._note("non-empty array literal not supported")
            return "/* TODO_TRANSLIT: array literal */"
        # Fallback.
        self._note(f"unhandled expr: {t}")
        return f"/* ES: {t} */"

    def _emit_call(self, node: Any) -> str:
        callee = node.callee
        if callee.type == "Identifier":
            name = callee.name
            # `waiters_insert(<alias>.<wlist>, tid)` — the chart passes
            # the waiter list directly; the hand-written port's
            # `dm_waiters_insert(dm, arr, count, tid)` takes the array
            # pointer and a pointer to its uint8_t count. Resolve via
            # the struct-pointer alias path so the call uses
            # `<alias>-><list_field>` and `&<alias>-><count_field>`.
            # Source: `ports/m7-c/sos-m7-c/src/scripts.c::dm_waiters_insert`.
            if name == "waiters_insert" and len(node.arguments) == 2:
                first = node.arguments[0]
                info = self._resolve_waiter_list(first)
                if info is not None:
                    alias_name, list_field, count_field, _elem = info
                    tid_expr = self.emit_expr(node.arguments[1])
                    return (
                        f"dm_waiters_insert(dm, "
                        f"{alias_name}->{list_field}, "
                        f"&{alias_name}->{count_field}, "
                        f"(sos_task_id_t)({tid_expr}))"
                    )
            args = [self.emit_expr(a) for a in node.arguments]
            if name in HELPER_NEEDS_SITE_REWRITE:
                self._note(
                    f"helper `{name}` cannot be transliterated 1:1 — "
                    "needs site-aware arr+count split"
                )
                return f"/* TODO_TRANSLIT: {name}({', '.join(args)}) */"
            if name in HELPER_NAMES:
                # Helper calls go through `dm_<name>(dm, args)`.
                if args:
                    return f"dm_{name}(dm, {', '.join(args)})"
                return f"dm_{name}(dm)"
            self._note(f"free function: {name}")
            return f"{name}({', '.join(args)})"
        if callee.type == "MemberExpression":
            method = callee.property.name
            # `<coll>.push({...})` where <coll> is `tcb` / `sems` /
            # `queues` — chart's boot.onentry pattern. Emit a typed
            # compound-literal assignment into the current for-loop
            # index slot, matching the hand-written boot's shape.
            # Recognised BEFORE arguments are pre-emitted because the
            # `ObjectExpression` argument trips the generic
            # `emit_expr` stub path otherwise.
            if (
                method == "push"
                and callee.object.type == "Identifier"
                and callee.object.name in COLLECTION_STRUCT_TYPES_C
                and len(node.arguments) == 1
                and node.arguments[0].type == "ObjectExpression"
                and self._current_for_var is not None
            ):
                coll = callee.object.name
                obj_node = node.arguments[0]
                struct = emit_struct_literal_c(self, coll, obj_node)
                return (
                    f"dm->{coll}[(size_t)({self._current_for_var})] "
                    f"= {struct}"
                )
        args = [self.emit_expr(a) for a in node.arguments]
        if callee.type == "MemberExpression":
            method = callee.property.name
            # Waiter-list-on-alias array methods. The struct-pointer
            # alias path lets us resolve `<alias>.<wlist>.<method>(...)`
            # against the corresponding `(<list_field>[], <count_field>)`
            # storage. Mirrors the hand-written reference; the chart
            # body around the call (e.g. `var w = s.waiters.shift()`,
            # `q.buf.push(d.msg)`) decides whether shift returns a value
            # or push appends.
            info = self._resolve_waiter_list(callee.object)
            if info is not None:
                alias_name, list_field, count_field, _elem = info
                if method == "shift":
                    # `<alias>.<wlist>.shift()` standing as an
                    # expression. The bench-validated emission requires
                    # the shift to span multiple statements (capture
                    # the front element, shift the tail down, decrement
                    # the count). v0 handles this at the
                    # `VariableDeclaration` statement level — the only
                    # form the chart uses for shift(). If we land here
                    # it means a context not yet covered (e.g. bare
                    # `s.waiters.shift();` discard); surface a note.
                    self._note(
                        f"`{alias_name}->{list_field}.shift()` outside of "
                        "`var X = ...shift()` form not yet supported"
                    )
                    return (
                        f"/* TODO_TRANSLIT: {alias_name}->{list_field}.shift() */"
                    )
                if method == "push":
                    # Only `q.buf.push(X)` is reached: the chart-level
                    # `q.count++` that always follows the push handles
                    # the increment. Waiter-list inserts go through
                    # `waiters_insert(...)` rather than `.push(...)`.
                    if list_field != "buf":
                        self._note(
                            f"`{alias_name}->{list_field}.push(...)` — only "
                            "`q.buf.push(...)` is supported in v0"
                        )
                        return (
                            f"/* TODO_TRANSLIT: "
                            f"{alias_name}->{list_field}.push(...) */"
                        )
                    if len(node.arguments) != 1:
                        self._note(
                            f"`{alias_name}->buf.push(...)` arity "
                            f"{len(node.arguments)} not supported"
                        )
                        return (
                            f"/* TODO_TRANSLIT: "
                            f"{alias_name}->buf.push(...) */"
                        )
                    # `q.buf` stores `int64_t`; the chart's RHS may be:
                    #   * an int-typed local / event field (e.g. `d.msg`
                    #     bound to int64) — emit directly.
                    #   * a `<row>.msg` access where `<row>` is a TCB
                    #     row — the C side has `sos_msg_t`, so we
                    #     unwrap to `<row>.msg.u.i` (the SOS_MSG_INT
                    #     variant). The chart invariant says senders
                    #     deposit their payload via `tcb[X].msg = ...`
                    #     before being parked on `q.sendw`; that
                    #     assignment lands as SOS_MSG_INT in the C
                    #     port (see _emit_expr_stmt's `.msg = ...`
                    #     handling). So `.u.i` is the correct
                    #     unwrap.
                    arg0 = node.arguments[0]
                    if (
                        arg0.type == "MemberExpression"
                        and not arg0.computed
                        and arg0.property.name == "msg"
                        and not (
                            arg0.object.type == "Identifier"
                            and arg0.object.name in self._event_data_aliases
                        )
                    ):
                        inner = self.emit_expr(arg0.object)
                        rhs_c = f"{inner}.msg.u.i"
                    else:
                        rhs_c = args[0]
                    # Inline single-element append; the chart's explicit
                    # `q.count++` on the next line completes the bump.
                    return (
                        f"{alias_name}->{list_field}"
                        f"[(size_t)({alias_name}->{count_field})] = {rhs_c}"
                    )
                if method == "length":
                    # `.length` as a call (rare) — funnel through the
                    # property-access path. v0 only sees `.length` as a
                    # MemberExpression (handled in emit_expr). Surface
                    # a note if we ever see `<x>.length()`.
                    self._note(
                        f"`{alias_name}->{list_field}.length()` (call form) "
                        "not supported"
                    )
                    return (
                        f"/* TODO_TRANSLIT: "
                        f"{alias_name}->{list_field}.length() */"
                    )
                # splice / indexOf on a waiter-list-on-alias: surface
                # the note explicitly so reviewers see which list-method
                # combination is missing.
                self._note(
                    f"`{alias_name}->{list_field}.{method}(...)` site-aware "
                    "rewrite not yet implemented"
                )
                return (
                    f"/* TODO_TRANSLIT: "
                    f"{alias_name}->{list_field}.{method}(...) */"
                )
            obj = self.emit_expr(callee.object)
            # JS array methods on chart-local aliases — these require
            # site-aware knowledge of the underlying bounded-array
            # storage. v0 surfaces a TODO_TRANSLIT comment and notes,
            # which falls back to stub at the template level.
            if method in ("push", "shift", "splice", "indexOf", "length"):
                self._note(
                    f"`{obj}.{method}(...)` requires site-aware array+count rewrite"
                )
                return f"/* TODO_TRANSLIT: {obj}.{method}({', '.join(args)}) */"
            # Unknown method.
            self._note(f"unknown method: {obj}.{method}")
            return f"{obj}.{method}({', '.join(args)})"
        self._note(f"unhandled callee: {callee.type}")
        return "/* call */ 0"

    def _emit_assign_as_expr(self, node: Any) -> str:
        return (
            f"({self.emit_expr(node.left)} "
            f"{node.operator} "
            f"{self.emit_expr(node.right)})"
        )

    def _emit_update_as_expr(self, node: Any) -> str:
        arg = self.emit_expr(node.argument)
        if node.operator == "++":
            return f"({arg}++)"
        return f"({arg}--)"

    # ----- statement emission -----

    def emit_stmt(self, node: Any, indent: str = "    ") -> str:
        t = node.type
        if t == "VariableDeclaration":
            parts: list[str] = []
            for d in node.declarations:
                # `var <name> = _event.data;` — record as alias, emit no
                # binding (the preamble already bound the fields).
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
                # already bound by the preamble — elide the redundant
                # rebind, but record the local so subsequent references
                # to <field> resolve cleanly.
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
                    self._add_local(d.id.name)
                    continue
                # Detect `var <x> = tcb[<expr>];` — JS treats this as a
                # struct reference, but C copies. Realise as a C pointer
                # alias (`sos_tcb_t *x = &dm->tcb[<expr>];`) so subsequent
                # `<x>.field` mutations through MemberExpression resolve
                # via `<x>->field` (see _struct_pointer_aliases). The
                # alias name is added to both the regular local-set and
                # the pointer-alias dict; the former so identifier
                # lookups don't accidentally treat it as a datamodel
                # field, the latter so MemberExpression picks `->`.
                if (
                    d.init is not None
                    and d.init.type == "MemberExpression"
                    and d.init.computed
                    and d.init.object.type == "Identifier"
                    and d.init.object.name in ("tcb", "sems", "queues")
                ):
                    arr = d.init.object.name
                    idx_expr = self.emit_expr(d.init.property)
                    c_type = _STRUCT_POINTER_TYPES[arr]
                    self._struct_pointer_aliases[d.id.name] = arr
                    self._add_local(d.id.name)
                    parts.append(
                        f"{indent}{c_type} *{d.id.name} = "
                        f"&dm->{arr}[(size_t)({idx_expr})];"
                    )
                    continue
                # `var <x> = <alias>.<wlist>.shift();` — expand into the
                # site-aware "capture front + memmove tail down +
                # decrement count" 3-statement block. Mirrors the
                # hand-written reference at
                # `ports/m7-c/sos-m7-c/src/scripts.c`. Only the
                # struct-pointer-alias path is recognised; bare
                # `<datamodel>.<wlist>.shift()` would need full
                # collection+index resolution (the chart never does
                # that — it always binds through an alias first).
                if (
                    d.init is not None
                    and d.init.type == "CallExpression"
                    and d.init.callee.type == "MemberExpression"
                    and not d.init.callee.computed
                    and d.init.callee.property.name == "shift"
                    and len(d.init.arguments) == 0
                ):
                    info = self._resolve_waiter_list(d.init.callee.object)
                    if info is not None:
                        alias_name, list_field, count_field, elem_c = info
                        self._add_local(d.id.name)
                        self._int_typed_locals[d.id.name] = elem_c
                        parts.append(
                            f"{indent}{elem_c} {d.id.name} = "
                            f"{alias_name}->{list_field}[0];"
                        )
                        # memmove the tail down by one slot. Element
                        # count to move is `count - 1` (count is the
                        # pre-shift count; we shift `count - 1` tail
                        # elements down by one to leave the slot at
                        # index `count - 1` logically empty).
                        parts.append(
                            f"{indent}memmove("
                            f"&{alias_name}->{list_field}[0], "
                            f"&{alias_name}->{list_field}[1], "
                            f"(size_t)({alias_name}->{count_field} - 1u)"
                            f" * sizeof({elem_c}));"
                        )
                        # Decrement the count *only* for waiter lists.
                        # `q.buf.shift()` is always paired in the chart
                        # with an explicit `q.count--` on the next line;
                        # decrementing here would double-decrement.
                        # Waiter lists have no chart-level decrement
                        # (the JS code mutates the list's `length`
                        # implicitly via shift()), so the C port must
                        # decrement the corresponding `*_count`.
                        if list_field != "buf":
                            parts.append(
                                f"{indent}{alias_name}->{count_field}--;"
                            )
                        continue
                self._add_local(d.id.name)
                if d.init is not None:
                    init = self.emit_expr(d.init)
                    parts.append(f"{indent}int32_t {d.id.name} = {init};")
                else:
                    parts.append(f"{indent}int32_t {d.id.name} = 0;")
            if not parts:
                return f"{indent}/* (event-data alias elided) */"
            return "\n".join(parts)
        if t == "ExpressionStatement":
            return self._emit_expr_stmt(node.expression, indent)
        if t == "IfStatement":
            test = self.emit_expr(node.test)
            self._push_scope()
            cons = self.emit_block(node.consequent, indent + "    ")
            self._pop_scope()
            out = f"{indent}if ({test}) {{\n{cons}\n{indent}}}"
            if node.alternate is not None:
                if node.alternate.type == "IfStatement":
                    # `else if` cascade — emit the alternate at the same
                    # indent level, with its leading whitespace stripped
                    # so it reads as `} else if (...) {`.
                    alt_stmt = self.emit_stmt(node.alternate, indent).lstrip()
                    out += f" else {alt_stmt}"
                else:
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
            return f"{indent}while ({test}) {{\n{body}\n{indent}}}"
        if t == "ReturnStatement":
            if node.argument is None:
                return f"{indent}return true;"
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
            # Special-case: empty-array reset on a bounded waiter list,
            # e.g. `s.waiters = []` → `<s-translated>.waiter_count = 0u;`.
            # Recognised before the generic left/right emit so the `[]`
            # never reaches ArrayExpression (which would TODO-stub).
            if (
                expr.operator == "="
                and expr.left.type == "MemberExpression"
                and not expr.left.computed
                and expr.right.type == "ArrayExpression"
                and not expr.right.elements
                and expr.left.property.name in _EMPTY_ARRAY_RESET_COUNT_FIELD
            ):
                count_field = _EMPTY_ARRAY_RESET_COUNT_FIELD[expr.left.property.name]
                obj_node = expr.left.object
                # Honour the struct-pointer alias path: `s.waiters = []`
                # where `s = &dm->sems[i]` → `s->waiter_count = 0u;`.
                if (
                    obj_node.type == "Identifier"
                    and obj_node.name in self._struct_pointer_aliases
                ):
                    obj_c = f"{obj_node.name}->"
                else:
                    obj_c = f"{self.emit_expr(obj_node)}."
                return f"{indent}{obj_c}{count_field} = 0u;"
            # Special-case: `<expr>.msg = <RC_*>` / `<expr>.msg = null` —
            # `msg` is a tagged union (sos_msg_t) in the C port; the
            # chart's single-line assignment expands to a paired
            # tag-and-value write. Handles the assignment that surfaces
            # in sys.tick / sched.resume (RC payloads) and task.create
            # (null reset). Without this expansion the alias-only path
            # emits `t->msg = SOS_RC_OK;` which fails to compile.
            if (
                expr.operator == "="
                and expr.left.type == "MemberExpression"
                and not expr.left.computed
                and expr.left.property.name == "msg"
            ):
                obj_node = expr.left.object
                if (
                    obj_node.type == "Identifier"
                    and obj_node.name in self._struct_pointer_aliases
                ):
                    obj_c = f"{obj_node.name}->"
                else:
                    obj_c = f"{self.emit_expr(obj_node)}."
                # RC_* identifier on the RHS.
                if (
                    expr.right.type == "Identifier"
                    and expr.right.name in RC_TO_C
                ):
                    rc_c = RC_TO_C[expr.right.name]
                    return (
                        f"{indent}{obj_c}msg.tag  = SOS_MSG_RC;\n"
                        f"{indent}{obj_c}msg.u.rc = (sos_rc_t){rc_c};"
                    )
                # `null` literal on the RHS.
                if (
                    expr.right.type == "Literal"
                    and expr.right.value is None
                ):
                    return (
                        f"{indent}{obj_c}msg.tag = SOS_MSG_NULL;\n"
                        f"{indent}{obj_c}msg.u.i = 0;"
                    )
                # `<lhs>.msg = <some-row>.msg` — struct copy. The RHS
                # evaluates to a `sos_msg_t` already, so a single C
                # assignment between sos_msg_t lvalues is a valid
                # whole-struct copy (the tag travels with the value).
                # This catches `tcb[current].msg = tcb[w].msg` in
                # `queue.receive` (zero-capacity handoff). The
                # event-data alias case (`d.msg` where `d` aliases
                # `_event.data`) is excluded — that resolves to the
                # bound int64 `msg` local and is handled by the
                # generic-int path below.
                if (
                    expr.right.type == "MemberExpression"
                    and not expr.right.computed
                    and expr.right.property.name == "msg"
                    and not (
                        expr.right.object.type == "Identifier"
                        and expr.right.object.name in self._event_data_aliases
                    )
                ):
                    rhs_c = self.emit_expr(expr.right)
                    return f"{indent}{obj_c}msg = {rhs_c};"
                # `<lhs>.msg = <int-typed-value>` — SOS_MSG_INT
                # expansion. Covers:
                #   * `tcb[w].msg = d.msg` (d.msg → bound int64 local
                #     `msg` via the event-data alias path; the chart
                #     event payload is the queue-send i64).
                #   * `tcb[current].msg = m` (m is the local declared
                #     by a prior `var m = q.buf.shift()` expansion;
                #     element type is int64).
                #   * Any other identifier known to be int-typed (see
                #     `_int_typed_locals`).
                if expr.right.type == "MemberExpression":
                    # `d.msg` style — alias resolution will reduce
                    # this to bare `msg` (the bound event field).
                    rhs_c = self.emit_expr(expr.right)
                    return (
                        f"{indent}{obj_c}msg.tag = SOS_MSG_INT;\n"
                        f"{indent}{obj_c}msg.u.i = (int64_t)({rhs_c});"
                    )
                if expr.right.type == "Identifier" and (
                    expr.right.name in self._int_typed_locals
                    or expr.right.name in self._bound_event_fields
                ):
                    rhs_c = self.emit_expr(expr.right)
                    return (
                        f"{indent}{obj_c}msg.tag = SOS_MSG_INT;\n"
                        f"{indent}{obj_c}msg.u.i = (int64_t)({rhs_c});"
                    )
                # Fall through to the generic path for other RHS shapes;
                # surface a note rather than emitting subtly-wrong code.
                self._note(
                    "`.msg = <non-RC, non-null, non-int>` assignment — "
                    "sos_msg_t expansion not supported for this RHS"
                )
            left = self.emit_expr(expr.left)
            right = self.emit_expr(expr.right)
            # `dm->rc = RC_*` benefits from a `(sos_rc_t)` cast for
            # parity with the hand-written port; the literal RC_* is
            # already an enum, but the explicit cast suppresses
            # -Wenum-int-mismatch under stricter compilers.
            if left == "dm->rc" and right.startswith("SOS_RC_"):
                return f"{indent}{left} {expr.operator} (sos_rc_t){right};"
            return f"{indent}{left} {expr.operator} {right};"
        if expr.type == "UpdateExpression":
            arg = self.emit_expr(expr.argument)
            if expr.operator == "++":
                return f"{indent}{arg}++;"
            return f"{indent}{arg}--;"
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
                    f"{indent}for (size_t {i_name} = (size_t)({start}); "
                    f"{i_name} < (size_t)({end}); ++{i_name}) {{\n"
                    f"{body}\n{indent}}}"
                )
            if test.operator == ">=" and update.operator == "--":
                end = self.emit_expr(test.right)
                body = self.emit_block(node.body, indent + "    ")
                self._pop_scope()
                self._current_for_var = saved_for_var
                # Down-counting loop with int32_t to permit `>= 0`.
                return (
                    f"{indent}for (int32_t {i_name} = (int32_t)({start}); "
                    f"{i_name} >= (int32_t)({end}); --{i_name}) {{\n"
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


# Chart datamodel array name → per-row C struct type. Used by the
# `<coll>.push({ ... })` pattern in boot.onentry: emit a typed compound
# literal at the surrounding for-loop's index slot rather than a JS-
# style dynamic push. Source of truth: `sos/types.h::sos_tcb_t /
# sos_sem_t / sos_queue_t`.
COLLECTION_STRUCT_TYPES_C: dict[str, str] = {
    "tcb":    "sos_tcb_t",
    "sems":   "sos_sem_t",
    "queues": "sos_queue_t",
}


# Per-collection field-name → C-type-aware emit-hint. Covers the
# fields the chart's boot.onentry uses inside an ObjectExpression.
# Hints supported:
#   * "task_id"     — cast value to `sos_task_id_t` (chart loop-var `i`).
#   * "prio"        — cast value to `sos_prio_t`.
#   * "state"       — RHS is an `ST_*` constant; the generic identifier
#                     emit path already maps it to `SOS_ST_*`, so no
#                     hint-specific transform is needed (this entry
#                     exists for documentation only).
#   * "blk_obj"     — int16_t; chart's `-1` literal lands as the
#                     UnaryExpression `-1` and emits cleanly without a
#                     cast.
#   * "msg_null"    — RHS is `null`; expand into a tagged-union init
#                     `{ .tag = SOS_MSG_NULL, .u = { .i = 0 } }`.
#   * "empty_array" — RHS is `[]`; the C struct layout uses a
#                     fixed-size array plus a separate `_count` field
#                     (or, for `queues.buf`, the queue's outer
#                     `count`). The compound literal's designated-init
#                     semantics zero omitted fields, so for these
#                     fields we elide emission entirely. Returning
#                     `None` from the hint resolver signals the
#                     skip-this-field path.
#
# Fields not listed fall through to the raw `emit_expr` (the chart
# value emits as a plain C expression and the compiler infers).
COLLECTION_FIELD_HINTS_C: dict[str, dict[str, str]] = {
    "tcb": {
        "id":      "task_id",     # chart loop var → cast `(sos_task_id_t)`
        "prio":    "prio",        # `(sos_prio_t)`
        "msg":     "msg_null",    # `null` → tagged-union NULL init
    },
    "sems": {
        "waiters": "empty_array",
    },
    "queues": {
        "buf":     "empty_array",
        "sendw":   "empty_array",
        "recvw":   "empty_array",
    },
}


def emit_struct_literal_c(
    emitter: CEmitter, coll_name: str, obj_node: Any
) -> str:
    """Emit a C compound literal `(<type>){ .<field> = <value>, ... }`
    given the chart's `<coll>.push({...})` ObjectExpression. Uses
    `COLLECTION_FIELD_HINTS_C` to apply per-field type-aware emission,
    eliding fields the hint flags as `empty_array` (designated-init
    zero-fills omitted fields, which is the correct C semantics for the
    chart's `[]` reset on bounded waiter-list / buf storage)."""
    struct_type = COLLECTION_STRUCT_TYPES_C[coll_name]
    field_hints = COLLECTION_FIELD_HINTS_C.get(coll_name, {})
    parts: list[str] = []
    for prop in obj_node.properties:
        key = prop.key.name if prop.key.type == "Identifier" else prop.key.value
        val_node = prop.value
        hint = field_hints.get(key)
        if hint == "empty_array":
            # Skip — designated-init zeros the omitted aggregate field.
            continue
        if hint == "task_id":
            val = f"(sos_task_id_t)({emitter.emit_expr(val_node)})"
        elif hint == "prio":
            val = f"(sos_prio_t)({emitter.emit_expr(val_node)})"
        elif hint == "msg_null":
            if val_node.type == "Literal" and val_node.value is None:
                val = "{ .tag = SOS_MSG_NULL, .u = { .i = 0 } }"
            else:
                # Non-null msg literal at struct-push isn't in the
                # chart today; fall back to emit_expr so any future
                # extension still produces a syntactically-valid C
                # initialiser (the compiler will diagnose mismatches).
                val = emitter.emit_expr(val_node)
        else:
            val = emitter.emit_expr(val_node)
        parts.append(f".{key} = {val}")
    body = ", ".join(parts)
    return f"({struct_type}){{ {body} }}"


def transliterate_to_c(
    source: str, event_name: str | None = None
) -> TransliterationResult:
    """Parse ECMAScript source, emit C statements.

    `event_name` is the chart event the site dispatches on (e.g.
    `task.create`); when provided, a typed-union preamble extracts the
    `sos_event_data_t` payload as locals before the transliterated body
    runs.

    Returns the emitted C source (preamble + body), a list of notes
    flagging unhandled-construct fallbacks, and a `needs_ev_param`
    flag the caller uses to suppress `(void)ev;` in the generated
    function body.
    """
    program = esprima.parseScript(source)
    preamble, bound_fields = emit_eventdata_preamble(event_name)
    emitter = CEmitter(bound_event_fields=bound_fields)
    lines: list[str] = []
    if preamble:
        lines.append(preamble)
    for stmt in program.body:
        lines.append(emitter.emit_stmt(stmt))
    return TransliterationResult(
        c_source="\n".join(lines),
        unhandled_notes=emitter._notes,
        preamble=preamble,
        needs_ev_param=bool(preamble) or emitter._uses_ev,
    )


# ---------------------------------------------------------------------------
# HELPERS block emission (SOS-06-A-2 Item 2).
#
# The chart's HELPERS block (rtos_kernel.scxml lines 77-165) defines 9
# free functions the per-site transition scripts call. The C port
# realises these as file-static `dm_<name>(struct sos_datamodel *dm, ...)`
# functions emitted ahead of the per-site script bodies in `scripts.c`.
#
# Per-helper signature table — load-bearing for ABI parity with the
# hand-written reference at `ports/m7-c/sos-m7-c/src/scripts.c`. The
# transition scripts call these by name with these arg shapes; the
# template must match.
# ---------------------------------------------------------------------------

# `(return_type, [(param_type, param_name), ...])` keyed by chart name.
HELPER_SIGNATURES: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "readyq_init": (
        "void",
        [],
    ),
    "ready_push": (
        "void",
        [("sos_task_id_t", "tid")],
    ),
    "ready_remove": (
        "void",
        [("sos_task_id_t", "tid")],
    ),
    "ready_pop_highest": (
        "sos_task_id_t",
        [],
    ),
    # site-aware: caller passes the bounded-array pair (arr, count).
    "waiters_insert": (
        "void",
        [
            ("sos_task_id_t *", "arr"),
            ("uint8_t *", "count"),
            ("sos_task_id_t", "tid"),
        ],
    ),
    "block_current": (
        "void",
        [
            ("sos_task_state_t", "state"),
            ("int16_t", "blk_obj"),
            ("sos_tick_t", "deadline"),
        ],
    ),
    "unblock": (
        "void",
        [("sos_task_id_t", "tid")],
    ),
    "waiter_cancel": (
        "void",
        [("sos_task_id_t", "tid")],
    ),
    "pick_next": (
        "void",
        [],
    ),
}


def _format_helper_signature(name: str, *, static: bool = True) -> str:
    """Format the C signature for helper `name`. `static=True` for the
    in-file definition; `static=False` for forward declarations.

    File-static helpers that are not (yet) called from any per-site
    transition script trip `-Werror=unused-function`. The v0 emitter
    decorates the definition with `__attribute__((unused))` to suppress
    that warning until SOS-06-A-2 Item 3 lands real bodies and Item 4
    wires every helper into a transliterated site."""
    ret, params = HELPER_SIGNATURES[name]
    args = ["struct sos_datamodel *dm"] + [f"{ty} {pn}" for ty, pn in params]
    if static:
        prefix = "static __attribute__((unused)) "
    else:
        prefix = ""
    return f"{prefix}{ret} dm_{name}({', '.join(args)})"


def _sanitise_comment_text(text: str) -> str:
    """Strip nested-comment sequences so embedded chart source can live
    inside a C `/* ... */` block without breaking the lexer."""
    # `/*` → `/ *` and `*/` → `* /` — preserves visual fidelity while
    # killing the lex hazard.
    return text.replace("/*", "/ *").replace("*/", "* /")


def _format_stub_body(name: str, chart_source: str) -> str:
    """Stub body that surfaces the chart source verbatim + a sentinel
    TODO marker. Returns void or -1 (for ready_pop_highest)."""
    ret, _ = HELPER_SIGNATURES[name]
    indent = "    "
    src_lines = _sanitise_comment_text(chart_source).splitlines()
    body: list[str] = []
    body.append(f"{indent}(void)dm;")
    # The caller's arg names are documented in HELPER_SIGNATURES; mark
    # them unused so -Werror=unused-parameter passes for stub bodies.
    _, params = HELPER_SIGNATURES[name]
    for _, pn in params:
        body.append(f"{indent}(void){pn};")
    body.append(f"{indent}/* SOS-06-A-2 Item 3: site-aware array-method emission needed. */")
    body.append(f"{indent}/* CHART source (rtos_kernel.scxml HELPERS block): */")
    for line in src_lines:
        body.append(f"{indent}/*   {line.rstrip()} */")
    if ret == "sos_task_id_t":
        body.append(f"{indent}return -1;")
    elif ret != "void":
        body.append(f"{indent}return 0;")
    return "\n".join(body)


def emit_helpers_c(helpers_source: str) -> str:
    """Parse the chart's HELPERS block, emit forward declarations + each
    helper as a file-static `dm_<name>` function.

    v0 emits stub bodies — bodies surface the chart source as comments
    and a `SOS-06-A-2 Item 3` follow-on marker. Signatures match the
    bench-validated hand-written reference at
    `ports/m7-c/sos-m7-c/src/scripts.c` so per-site transition scripts
    link cleanly against the helpers.
    """
    out: list[str] = []
    out.append(
        "/* ====================================================================\n"
        " * HELPERS block — chart-derived file-static helpers (SOS-06-A-2 v0).\n"
        " * Mirrors `rtos_kernel.scxml` lines 77-165. v0 emits STUB bodies; the\n"
        " * per-site transition scripts compile and link against the signatures,\n"
        " * but conformance vectors that exercise these helpers will fail at\n"
        " * runtime until SOS-06-A-2 Item 3 lands site-aware array-method\n"
        " * transliteration.\n"
        " * ==================================================================== */\n"
    )

    try:
        program = esprima.parseScript(helpers_source, {"range": True})
    except Exception as exc:
        out.append(f"/* sos-codegen: failed to parse HELPERS block: {exc} */\n")
        return "\n".join(out)

    # Collect FunctionDeclarations in source order. Preserve chart source
    # per-helper so the stub body can surface it.
    helper_sources: dict[str, str] = {}
    helper_order: list[str] = []
    for stmt in program.body:
        if stmt.type != "FunctionDeclaration":
            continue
        fname = stmt.id.name
        if fname not in HELPER_SIGNATURES:
            # Unknown helper — surface as a comment, don't emit.
            out.append(f"/* sos-codegen: unknown HELPERS function `{fname}` skipped. */\n")
            continue
        # Recover the function's source text from the input by slicing
        # at the FunctionDeclaration's range, if esprima populated it;
        # otherwise fall back to a placeholder.
        try:
            start = stmt.range[0]
            end = stmt.range[1]
            helper_sources[fname] = helpers_source[start:end]
        except Exception:
            helper_sources[fname] = f"function {fname}(...) {{ /* source unavailable */ }}"
        helper_order.append(fname)

    if not helper_order:
        out.append("/* sos-codegen: no FunctionDeclarations found in HELPERS block. */\n")
        return "\n".join(out)

    # Forward declarations — keeps the C linker happy regardless of the
    # order helpers call each other (e.g. unblock → ready_push,
    # pick_next → ready_pop_highest).
    out.append("/* Forward declarations. */")
    for fname in helper_order:
        out.append(_format_helper_signature(fname, static=True) + ";")
    out.append("")

    # Definitions — file-static stub bodies.
    for fname in helper_order:
        out.append(_format_helper_signature(fname, static=True))
        out.append("{")
        out.append(_format_stub_body(fname, helper_sources[fname]))
        out.append("}")
        out.append("")

    return "\n".join(out)


# ---------------------------------------------------------------------------
# Layer B runtime embed (SOS-06-A Phase 1 closure).
#
# v0 of `emit_helpers_c` emits typed-signature stubs for the chart's 9
# HELPERS because the ECMAScript-to-C transliterator can't safely handle
# the array idioms (`ready[p].push(...)`, `arr.shift()`, `arr.splice(...)`,
# `arr.indexOf(...)`). Per SOS-06 §15 Amendment 002 the codegen's value-
# add is the Layer A state machine (per-site scripts + dispatcher);
# Layer B is a runtime library bundled with codegen output and hand-
# coded in C. Phase 1 closure: splice the bench-validated hand-written
# `dm_*` helpers from `ports/m7-c/sos-m7-c/src/scripts.c` into the
# emitted source verbatim so the C target compiles end-to-end.
#
# The extractor below scans the hand-written `scripts.c`, finds every
# `static <ret> dm_<name>(...)` block (function definition OR forward
# declaration), captures the preceding doc-comment, and emits the
# concatenated runtime as a single string the Jinja template splices
# in ahead of the per-site script bodies.
# ---------------------------------------------------------------------------

# Regex matching the start of a `static ... dm_<name>(...)` declaration.
# The match begins at `static` (column 0) and continues until the closing
# `)` of the parameter list. Multi-line signatures are common (e.g.
# `dm_waiters_insert` spans 4 lines) so DOTALL is required.
_DM_DECL_RE = re.compile(
    r"^static\s+[^\n;{}]*?\bdm_([A-Za-z_][A-Za-z0-9_]*)\s*\([^;{}]*?\)",
    re.MULTILINE | re.DOTALL,
)


def _scan_preceding_doc_comment(source: str, decl_start: int) -> int:
    """Walk backward from `decl_start` over whitespace, and if the next
    non-whitespace character before the decl is the `/` closing a
    `*/` block comment, return the index of the opening `/*` so the
    caller can splice [comment_start .. decl_start). When no
    doc-comment is attached, returns `decl_start` unchanged.
    """
    i = decl_start - 1
    # Skip whitespace immediately before the decl.
    while i >= 0 and source[i] in " \t\r\n":
        i -= 1
    if i < 1 or source[i] != "/" or source[i - 1] != "*":
        return decl_start
    # We're sitting on the `/` of a closing `*/`. Walk back to `/*`.
    j = i - 1
    while j >= 1:
        if source[j - 1] == "/" and source[j] == "*":
            return j - 1
        j -= 1
    # Unterminated upstream — bail safely.
    return decl_start


def _balanced_block_end(source: str, brace_open: int) -> int:
    """Given the index of an opening `{`, return the index just past
    the matching closing `}`. Raises ValueError on imbalance."""
    depth = 0
    i = brace_open
    n = len(source)
    while i < n:
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError(
        f"unbalanced braces starting at offset {brace_open} in scripts.c"
    )


# Default reference path (relative to the SOS subrepo root) — mirrors
# `_RUNTIME_RUST_REFERENCE` in `transliterate_rust.py`.
_RUNTIME_C_REFERENCE = "ports/m7-c/sos-m7-c/src/scripts.c"


def embed_c_runtime(scripts_c_path: Path | str | None = None) -> str:
    """Extract every `static <ret> dm_<name>(...)` block from the hand-
    written reference `scripts.c` and return the concatenated source as
    a single string suitable for splicing into the generated `scripts.c`.

    Both function definitions (ending in a `{ ... }` body) and forward
    declarations (ending in `;`) are captured. The doc-comment block
    immediately preceding each decl is included verbatim.

    The result is wrapped in a clear banner identifying the upstream
    file so the generated `scripts.c` reads as: "the codegen splices
    the bench-validated Layer B runtime here."

    When `scripts_c_path` is None, falls back to the bench-validated
    reference at `<subrepo>/ports/m7-c/sos-m7-c/src/scripts.c`. When
    the resolved path doesn't exist, returns an empty string — the
    caller can then fall back to `emit_helpers_c()`'s stubs.
    """
    if scripts_c_path is None:
        ref = Path(_RUNTIME_C_REFERENCE)
    else:
        ref = Path(scripts_c_path)
    if not ref.is_absolute():
        # Resolve relative to the SOS subrepo root (two levels up
        # from `tools/sos-codegen/`).
        tool_dir = Path(__file__).resolve().parent
        ref = (tool_dir.parent.parent / ref).resolve()
    if not ref.exists():
        return ""

    scripts_c_path = ref
    source = ref.read_text(encoding="utf-8")

    # Track the end of the previous capture so the doc-comment scan
    # never crosses into already-captured territory.
    prev_capture_end = 0
    blocks: list[str] = []
    helper_names: list[str] = []

    for m in _DM_DECL_RE.finditer(source):
        decl_start = m.start()
        decl_end = m.end()
        # Determine if this is a forward decl (next non-ws is `;`) or
        # a full definition (next non-ws is `{`).
        i = decl_end
        n = len(source)
        while i < n and source[i] in " \t\r\n":
            i += 1
        if i >= n:
            continue
        if source[i] == ";":
            capture_end = i + 1
        elif source[i] == "{":
            capture_end = _balanced_block_end(source, i)
        else:
            # Unexpected — skip this decl rather than mis-capture.
            continue

        comment_start = _scan_preceding_doc_comment(source, decl_start)
        if comment_start < prev_capture_end:
            comment_start = decl_start
        # Inject `__attribute__((unused))` so script bodies that haven't
        # yet been transliterated (and therefore don't call every Layer B
        # helper) don't trip `-Werror=unused-function`. The marker
        # decorates only the leading `static` of the decl itself, not any
        # nested `static` inside the body or preceding comments.
        pre_block = source[comment_start:decl_start]
        decl_block = source[decl_start:capture_end]
        decl_block = re.sub(
            r"^static\s+",
            "static __attribute__((unused)) ",
            decl_block,
            count=1,
        )
        blocks.append(pre_block + decl_block)
        helper_names.append(m.group(1))
        prev_capture_end = capture_end

    if not blocks:
        return (
            "/* sos-codegen: no `static dm_*` declarations found in "
            f"{scripts_c_path.name}; emission proceeded with no runtime helpers. */\n"
        )

    banner_top = (
        "/* ====================================================================\n"
        f" * Layer B runtime — embedded verbatim from `{scripts_c_path.name}` by\n"
        " * `tools/sos-codegen/transliterate_c.py::embed_c_runtime` (SOS-06\n"
        " * §15 Amendment 002 / Phase 1 closure). The chart's HELPERS block\n"
        " * and the C-port-internal helpers (`dm_sem_give_common`,\n"
        " * `dm_queue_push`) are bundled with codegen output as a fixed\n"
        " * runtime library — they are NOT re-derived from chart source.\n"
        " *\n"
        f" * Embedded helpers: {', '.join(helper_names)}.\n"
        " * ==================================================================== */\n"
    )
    # Codegen supplement: the chart's `readyq_init()` is called from
    # `boot.onentry`, but the hand-written reference `scripts.c`
    # inlines the readyq-clear inside `sos_kernel_init()` rather than
    # exposing a `dm_readyq_init` symbol. The codegen-emitted
    # `script_boot_onentry_0` invokes `dm_readyq_init(dm)` uniformly
    # (mirroring the Rust port's `Datamodel::readyq_init` supplement),
    # so emit a small file-static stub here that zeros every
    # priority's `ready_count`. Storage in `ready_pool` is left
    # untouched — the push path only reads slots up to `ready_count`.
    supplement = (
        "\n"
        "/* Codegen supplement: chart's `readyq_init()` is inlined in\n"
        " * the hand-written reference port's `sos_kernel_init()`.\n"
        " * Provided here as a file-static so the codegen-emitted\n"
        " * `boot.onentry` can call it uniformly. */\n"
        "static __attribute__((unused)) void "
        "dm_readyq_init(struct sos_datamodel *dm)\n"
        "{\n"
        "    for (size_t p = 0u; p < SOS_MAX_PRIO; ++p) {\n"
        "        dm->ready_count[p] = 0u;\n"
        "    }\n"
        "}\n"
    )

    banner_bot = (
        "/* ====================================================================\n"
        " * End of embedded Layer B runtime.\n"
        " * ==================================================================== */\n"
    )
    return banner_top + "\n".join(blocks) + "\n" + supplement + banner_bot


if __name__ == "__main__":
    import sys
    src = sys.stdin.read()
    result = transliterate_to_c(src)
    print(result.c_source)
    if result.unhandled_notes:
        sys.stderr.write("\n# notes:\n")
        for n in result.unhandled_notes:
            sys.stderr.write(f"#   {n}\n")
