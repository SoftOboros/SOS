"""SOS-10A `in-process` medium emitter — Rust + C dispatch tables + FFI bridge.

Authority: ``docs/concepts/SOS-10-CONCEPTS.md`` §6.1 (ratified 2026-05-23;
all 8 PCDNs resolved). Input contract is owned by SOS-10-ANNOT
(``sos10_annotations.py``); this module is a *consumer* of that contract
and MUST NOT redefine its types or value grammars.

Public surface:
    emit_in_process(annotations, *, chart_sos_id, output_dir=None)
        -> dict[str, str]
    emit_in_process_from_chart(chart_path, **kwargs) -> dict[str, str]

What this module emits
----------------------

For each piece (declared by ``sos:lang`` on a top-level ``<state>``) that
is the TARGET of at least one ``kind="in-process"`` cross-piece
transition, this emitter produces one dispatch-table artifact:

- ``lang="rust"`` → ``<piece>_dispatch.rs``
    - ``pub struct OrchestratorEvent { event_id: u32, payload: *const c_void }``
    - ``pub type EventHandler = fn(&OrchestratorEvent)``
    - ``pub static DISPATCH_TABLE: &[(u32, EventHandler)]``
    - ``pub fn dispatch_event(ev: &OrchestratorEvent) -> Option<()>``

- ``lang="c"`` → ``<piece>_dispatch.h`` + ``<piece>_dispatch.c``
    - ``typedef struct { uint32_t event_id; const void *payload; } sos_event_t;``
    - ``typedef void (*sos_event_handler_t)(const sos_event_t *);``
    - ``typedef struct { uint32_t event_id; sos_event_handler_t handler; }
       sos_dispatch_entry_t;``
    - ``extern const sos_dispatch_entry_t sos_<piece>_dispatch_table[];``
    - ``void sos_<piece>_dispatch_event(const sos_event_t *ev);``

When a chart carries adjacent ``rust`` ↔ ``c`` in-process transitions, a
companion ``<piece>_ffi.rs`` is emitted on the Rust side. It declares the
shared payload as ``#[repr(C)]`` and exposes ``extern "C"`` shims that
forward to the local Rust dispatcher; the C-side handler can simply
``#include`` the matching header and call through the C dispatch table.

Event-ID determinism (INV-SOS-G mirror)
---------------------------------------

Each cross-piece event name maps to a deterministic ``u32`` event_id
derived from the tuple ``(chart_sos_id_uuid, event_name)``. The hash is
the FIPS-180-4 SHA-256 of the UTF-8 byte string
``"{chart_sos_id}|{event_name}"`` truncated to its leading 4 bytes,
interpreted as a big-endian unsigned integer.

Two emit runs against the same chart MUST produce byte-identical
event-ID assignments. Two charts that differ only in ``sos:id`` produce
DIFFERENT event-ID assignments (the chart id is part of the hash input).

@spec citations on every emitted file
-------------------------------------

Each emitted file carries a block comment citing:

- ``SOS-10-CONCEPTS §6.1`` — in-process medium contract.
- ``INV-S-ORCH-1`` — one orchestrator per system.
- ``INV-S-ORCH-2`` — piece-as-sub-chart.
- ``INV-S-ORCH-4`` — wire format derived (here: from event vocabulary
  + chart sos:id, not authored).
- ``INV-SOS-A`` — every emitted file is a build output.
- The chart's ``sos:id`` UUID (when present).
"""

from __future__ import annotations

import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Self-relative import — this module lives at tools/sos-codegen/.
_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sos10_annotations import (  # noqa: E402
    CrossPieceTransitionAnnotation,
    OrchestratorAnnotations,
    PieceAnnotation,
    parse_orchestrator_annotations,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# In-process is the only medium kind this emitter handles. Other media
# (shared-memory, mmio, network) have their own emitter modules.
_IN_PROCESS_KIND: str = "in-process"

# SV-identifier shape — piece ids that don't satisfy this can't safely
# appear in Rust/C symbol names.
_SV_IDENTIFIER_RE: re.Pattern[str] = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# Per PCDN-SOS-10-001 / -003: rust is the v1 default piece language. The
# in-process emitter only knows how to emit for `rust` and `c` at v1;
# other targets (e.g. `python` via PyO3) are not in scope for SOS-10A
# (the PyO3 bridge is a future sub-phase).
_SUPPORTED_LANGS: frozenset[str] = frozenset({"rust", "c"})


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EmittedEvent:
    """One event entry assigned a deterministic u32 id.

    `event_id` is the leading-4-bytes of ``SHA-256(chart_sos_id + "|" +
    event_name)`` interpreted big-endian. `target_piece` is the piece
    whose dispatch table will register a handler for this event (the
    transition's ``target_state_id``).
    """

    event_name: str
    event_id: int
    source_piece: str
    target_piece: str
    source_lang: str
    target_lang: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compute_event_id(chart_sos_id: str, event_name: str) -> int:
    """Deterministic u32 event-id derived from (chart_sos_id, event_name).

    The hash input is the UTF-8 bytes of ``"{chart_sos_id}|{event_name}"``.
    The output is the leading 4 bytes of SHA-256 interpreted as a
    big-endian unsigned integer. This gives 2^32 distinct ids; the
    birthday-collision probability across a single chart's event
    vocabulary is negligible (≥ 2^16 events before a 1% chance of any
    collision). Collisions WITHIN one chart are detected at emit time
    and surfaced as ``ValueError`` so the chart author can rename.
    """
    digest = hashlib.sha256(
        f"{chart_sos_id}|{event_name}".encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:4], byteorder="big", signed=False)


def _extract_chart_sos_id(chart_ast: dict) -> Optional[str]:
    """Pull ``sos:id`` off the root scxml ``other_attributes`` (or None).

    scjson surfaces the root element's ``other_attributes`` the same way
    states do — either as a flat dict or wrapped under
    ``{"other_attributes": "<json-string>"}``. We accept both shapes.
    """
    import json

    oa = chart_ast.get("other_attributes")
    if oa is None:
        return None
    raw: Optional[str]
    if isinstance(oa, str):
        raw = oa
    elif isinstance(oa, dict):
        inner = oa.get("other_attributes")
        if isinstance(inner, str):
            raw = inner
        elif isinstance(inner, dict):
            v = inner.get("sos:id")
            return v if isinstance(v, str) else None
        else:
            v = oa.get("sos:id")
            return v if isinstance(v, str) else None
    else:
        return None

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    v = parsed.get("sos:id")
    return v if isinstance(v, str) else None


def _in_process_transitions(
    annotations: OrchestratorAnnotations,
) -> list[CrossPieceTransitionAnnotation]:
    """Return only the cross-piece transitions whose medium is in-process."""
    return [
        t for t in annotations.transitions
        if t.medium.kind == _IN_PROCESS_KIND
    ]


def _piece_lang_map(annotations: OrchestratorAnnotations) -> dict[str, str]:
    """Map ``piece_id -> lang`` for fast lookup."""
    return {p.state_id: p.lang for p in annotations.pieces}


def _assign_event_ids(
    transitions: list[CrossPieceTransitionAnnotation],
    *,
    chart_sos_id: str,
    lang_map: dict[str, str],
) -> list[EmittedEvent]:
    """Assign deterministic ids to in-process events, detecting collisions.

    Walk order is the parser's document order so the resulting list is
    byte-identical across runs.
    """
    seen: dict[int, str] = {}
    out: list[EmittedEvent] = []
    for t in transitions:
        ev_id = _compute_event_id(chart_sos_id, t.event)
        if ev_id in seen and seen[ev_id] != t.event:
            raise ValueError(
                f"event-id collision: events {seen[ev_id]!r} and "
                f"{t.event!r} both hash to 0x{ev_id:08x} under chart "
                f"sos:id {chart_sos_id!r}. Rename one event."
            )
        seen[ev_id] = t.event
        src_lang = lang_map.get(t.source_state_id, "rust")
        tgt_lang = lang_map.get(t.target_state_id, "rust")
        out.append(
            EmittedEvent(
                event_name=t.event,
                event_id=ev_id,
                source_piece=t.source_state_id,
                target_piece=t.target_state_id,
                source_lang=src_lang,
                target_lang=tgt_lang,
            )
        )
    return out


def _validate_piece_id(piece_id: str) -> None:
    """Raise if a piece id is not a valid Rust/C symbol token."""
    if not _SV_IDENTIFIER_RE.match(piece_id):
        raise ValueError(
            f"piece id {piece_id!r} is not an SV identifier; cannot be "
            f"used as a Rust/C symbol root"
        )


def _spec_block(chart_sos_id: str, comment: str = "//") -> list[str]:
    """Return the @spec citation block as a list of comment lines."""
    return [
        f"{comment} @spec SOS-10-CONCEPTS §6.1 (in-process medium contract)",
        f"{comment} @spec INV-S-ORCH-1 (one orchestrator per system)",
        f"{comment} @spec INV-S-ORCH-2 (piece-as-sub-chart)",
        f"{comment} @spec INV-S-ORCH-4 (wire format derived, not authored)",
        f"{comment} @spec INV-SOS-A (every emitted file is a build output)",
        f"{comment} @spec chart sos:id {chart_sos_id}",
        f"{comment} AUTO-GENERATED by sos-codegen/in_process_emit.py — do not edit.",
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def emit_in_process(
    annotations: OrchestratorAnnotations,
    *,
    chart_sos_id: str,
    output_dir: Optional[Path | str] = None,
) -> dict[str, str]:
    """Emit per-piece dispatch-table artifacts for the in-process medium.

    Args:
        annotations: parsed SOS-10 orchestrator annotations.
        chart_sos_id: the orchestrator chart's ``sos:id`` UUID. Forms part
            of every event-id hash so two charts with disjoint UUIDs
            produce disjoint event-id namespaces.
        output_dir: optional directory; if provided, every emitted file
            is also written to disk under this root.

    Returns:
        Mapping ``filename -> file text``. Filenames carry no directory
        component. Only pieces participating in at least one in-process
        transition appear in the output.

    Raises:
        ValueError: a piece id is not an SV identifier; an event-id
            collision occurred; an in-process transition crosses a piece
            whose ``sos:lang`` is not in ``{"rust", "c"}``.
    """
    if not isinstance(chart_sos_id, str) or not chart_sos_id:
        raise ValueError(
            f"chart_sos_id must be a non-empty string; got {chart_sos_id!r}"
        )

    transitions = _in_process_transitions(annotations)
    lang_map = _piece_lang_map(annotations)

    # Determine which pieces participate in any in-process transition.
    participating: set[str] = set()
    for t in transitions:
        participating.add(t.source_state_id)
        participating.add(t.target_state_id)

    # Validate languages.
    for piece_id in sorted(participating):
        lang = lang_map.get(piece_id, "rust")
        if lang not in _SUPPORTED_LANGS:
            raise ValueError(
                f"piece {piece_id!r} has sos:lang={lang!r}; the in-process "
                f"emitter supports {sorted(_SUPPORTED_LANGS)} at v1 "
                f"(SOS-10 §6.1). PyO3 support is a future sub-phase."
            )
        _validate_piece_id(piece_id)

    # Assign event-ids deterministically.
    events = _assign_event_ids(
        transitions, chart_sos_id=chart_sos_id, lang_map=lang_map
    )

    # Bucket events by their TARGET piece — that's the dispatcher that
    # registers the handler. (A piece dispatches events it handles, not
    # events it sends.)
    target_events: dict[str, list[EmittedEvent]] = {}
    for ev in events:
        target_events.setdefault(ev.target_piece, []).append(ev)

    out: dict[str, str] = {}

    # Stable file-order: walk pieces in document order.
    for piece in annotations.pieces:
        pid = piece.state_id
        if pid not in participating:
            continue
        piece_events = target_events.get(pid, [])
        lang = lang_map.get(pid, "rust")

        if lang == "rust":
            fname = f"{pid}_dispatch.rs"
            out[fname] = _emit_rust_dispatch(
                piece=piece,
                events=piece_events,
                chart_sos_id=chart_sos_id,
            )
        elif lang == "c":
            h_fname = f"{pid}_dispatch.h"
            c_fname = f"{pid}_dispatch.c"
            h_text, c_text = _emit_c_dispatch(
                piece=piece,
                events=piece_events,
                chart_sos_id=chart_sos_id,
            )
            out[h_fname] = h_text
            out[c_fname] = c_text

    # FFI bridge: emit if any in-process transition crosses rust ↔ c.
    has_rust_c_boundary = any(
        {ev.source_lang, ev.target_lang} == {"rust", "c"}
        for ev in events
    )
    if has_rust_c_boundary:
        ffi_events = [
            ev for ev in events
            if {ev.source_lang, ev.target_lang} == {"rust", "c"}
        ]
        out["ffi_bridge.rs"] = _emit_ffi_bridge_rs(
            events=ffi_events, chart_sos_id=chart_sos_id
        )

    if output_dir is not None:
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        for fname, text in out.items():
            (out_path / fname).write_text(text, encoding="utf-8")

    return out


def emit_in_process_from_chart(
    chart_path: str | Path,
    *,
    chart_sos_id: Optional[str] = None,
    output_dir: Optional[Path | str] = None,
) -> dict[str, str]:
    """Convenience wrapper: loader → parser → emitter.

    ``chart_sos_id`` defaults to the root scxml's ``sos:id`` attribute
    when present; raises ``ValueError`` when neither is supplied.
    """
    from loader import load_chart  # noqa: WPS433 - lazy import

    ast = load_chart(Path(chart_path))
    if ast.raw_scjson is None:
        raise RuntimeError(
            f"loader returned ChartAst without raw_scjson for {chart_path!r}"
        )
    annotations = parse_orchestrator_annotations(ast.raw_scjson)
    sos_id = chart_sos_id or _extract_chart_sos_id(ast.raw_scjson)
    if not sos_id:
        raise ValueError(
            f"chart {chart_path!r} has no root sos:id and no chart_sos_id "
            f"override supplied; cannot derive deterministic event-ids "
            f"(INV-S-ORCH-4 + INV-SOS-G)."
        )
    return emit_in_process(
        annotations, chart_sos_id=sos_id, output_dir=output_dir
    )


# ---------------------------------------------------------------------------
# Rust emission
# ---------------------------------------------------------------------------


def _emit_rust_dispatch(
    *,
    piece: PieceAnnotation,
    events: list[EmittedEvent],
    chart_sos_id: str,
) -> str:
    """Emit ``<piece>_dispatch.rs`` for a rust-lang piece."""
    pid = piece.state_id
    lines: list[str] = []
    lines.extend(_spec_block(chart_sos_id, comment="//"))
    lines.append(f"// Piece: {pid} (sos:lang=rust)")
    lines.append("")
    lines.append("#![allow(dead_code)]")
    lines.append("")
    lines.append("use core::ffi::c_void;")
    lines.append("")
    lines.append("/// Orchestrator-level cross-piece event envelope.")
    lines.append("///")
    lines.append("/// Per SOS-10-CONCEPTS §6.1 the in-process medium uses a")
    lines.append("/// function-pointer dispatch table keyed by `event_id`. The")
    lines.append("/// `payload` is an opaque pointer the handler casts to the")
    lines.append("/// per-event `#[repr(C)]` struct declared in `ffi_bridge.rs`")
    lines.append("/// (when a Rust↔C boundary exists).")
    lines.append("#[repr(C)]")
    lines.append("pub struct OrchestratorEvent {")
    lines.append("    pub event_id: u32,")
    lines.append("    pub payload: *const c_void,")
    lines.append("}")
    lines.append("")
    lines.append("/// Handler signature for in-process dispatch.")
    lines.append("pub type EventHandler = fn(&OrchestratorEvent);")
    lines.append("")
    # Stub handlers — chart-author overrides them by re-exporting matching
    # symbols in their own crate. The emitter emits the registration; the
    # body remains the implementer's responsibility (INV-S-ORCH-4 wire
    # format is derived; handler body is NOT).
    if events:
        lines.append("// --- handler stubs (one per event this piece handles) ---")
        for ev in events:
            sym = f"handle_{_safe_event_symbol(ev.event_name)}"
            lines.append(
                f"/// Handler for `{ev.event_name}` "
                f"(source piece `{ev.source_piece}`, event_id 0x{ev.event_id:08x})."
            )
            lines.append(f"#[allow(unused_variables)]")
            lines.append(f"fn {sym}(ev: &OrchestratorEvent) {{")
            lines.append("    // implementer-provided body")
            lines.append("}")
            lines.append("")
        lines.append("// --- deterministic dispatch table (INV-SOS-G mirror) ---")
        lines.append(
            "pub static DISPATCH_TABLE: &[(u32, EventHandler)] = &["
        )
        for ev in events:
            sym = f"handle_{_safe_event_symbol(ev.event_name)}"
            lines.append(
                f"    (0x{ev.event_id:08x}u32, {sym} as EventHandler), "
                f"// {ev.event_name}"
            )
        lines.append("];")
    else:
        # Piece is source-only (it sends in-process events but does not
        # handle any). Emit an empty table so callers can still link.
        lines.append("// piece sends in-process events but handles none")
        lines.append("pub static DISPATCH_TABLE: &[(u32, EventHandler)] = &[];")
    lines.append("")
    lines.append("/// Dispatch one event to its registered handler.")
    lines.append("///")
    lines.append("/// Returns `Some(())` when an entry matched; `None` when no")
    lines.append("/// handler is registered for the event_id (caller decides")
    lines.append("/// how to surface — orchestrator may treat as INV-SOS-H")
    lines.append("/// failure-in-chart-vocabulary).")
    lines.append("pub fn dispatch_event(ev: &OrchestratorEvent) -> Option<()> {")
    lines.append("    for &(eid, handler) in DISPATCH_TABLE.iter() {")
    lines.append("        if eid == ev.event_id {")
    lines.append("            handler(ev);")
    lines.append("            return Some(());")
    lines.append("        }")
    lines.append("    }")
    lines.append("    None")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# C emission
# ---------------------------------------------------------------------------


def _emit_c_dispatch(
    *,
    piece: PieceAnnotation,
    events: list[EmittedEvent],
    chart_sos_id: str,
) -> tuple[str, str]:
    """Emit (``<piece>_dispatch.h``, ``<piece>_dispatch.c``) for a C piece."""
    pid = piece.state_id
    guard = f"SOS_{pid.upper()}_DISPATCH_H"
    table_sym = f"sos_{pid}_dispatch_table"
    dispatch_fn = f"sos_{pid}_dispatch_event"
    count_sym = f"sos_{pid}_dispatch_table_len"

    # ---- header ----------------------------------------------------------
    h: list[str] = []
    h.extend(_spec_block(chart_sos_id, comment="/*"))
    # Convert leading "/*" to proper C block-comment shape.
    h = [_c_blockcomment(line) for line in h]
    h.append(f"/* Piece: {pid} (sos:lang=c) */")
    h.append("")
    h.append(f"#ifndef {guard}")
    h.append(f"#define {guard}")
    h.append("")
    h.append("#include <stddef.h>")
    h.append("#include <stdint.h>")
    h.append("")
    h.append("#ifdef __cplusplus")
    h.append('extern "C" {')
    h.append("#endif")
    h.append("")
    h.append("/* Orchestrator cross-piece event envelope (SOS-10 §6.1). */")
    h.append("typedef struct {")
    h.append("    uint32_t    event_id;")
    h.append("    const void *payload;")
    h.append("} sos_event_t;")
    h.append("")
    h.append("typedef void (*sos_event_handler_t)(const sos_event_t *ev);")
    h.append("")
    h.append("typedef struct {")
    h.append("    uint32_t              event_id;")
    h.append("    sos_event_handler_t   handler;")
    h.append("} sos_dispatch_entry_t;")
    h.append("")
    # Per-event handler prototype declarations.
    if events:
        h.append("/* Per-event handler prototypes (one per event this piece handles). */")
        for ev in events:
            sym = f"sos_{pid}_handle_{_safe_event_symbol(ev.event_name)}"
            h.append(
                f"void {sym}(const sos_event_t *ev); "
                f"/* {ev.event_name}, event_id 0x{ev.event_id:08x} */"
            )
        h.append("")
    h.append(f"extern const sos_dispatch_entry_t {table_sym}[];")
    h.append(f"extern const size_t {count_sym};")
    h.append("")
    h.append("/*")
    h.append(" * Dispatch one event to its registered handler. Calls the matched")
    h.append(" * handler when an entry's event_id == ev->event_id; no-op when no")
    h.append(" * entry matches (orchestrator may treat as INV-SOS-H failure-")
    h.append(" * in-chart-vocabulary at a higher layer).")
    h.append(" */")
    h.append(f"void {dispatch_fn}(const sos_event_t *ev);")
    h.append("")
    h.append("#ifdef __cplusplus")
    h.append("}")
    h.append("#endif")
    h.append("")
    h.append(f"#endif /* {guard} */")
    h.append("")
    header_text = "\n".join(h)

    # ---- impl ------------------------------------------------------------
    c: list[str] = []
    c.extend([_c_blockcomment(line) for line in _spec_block(chart_sos_id, comment="/*")])
    c.append(f"/* Piece: {pid} (sos:lang=c) — dispatch table impl. */")
    c.append("")
    c.append(f'#include "{pid}_dispatch.h"')
    c.append("")
    # Weak stub handlers — chart-author overrides by linking their own
    # strong definition. ISO C11 doesn't include __attribute__((weak)) in
    # the standard; we guard with a preprocessor check so the headers
    # still parse under strict -std=c11 -Wpedantic. The real link target
    # is provided by the implementer.
    if events:
        c.append("/* Implementer-overridable stub handlers. */")
        c.append("#if defined(__GNUC__) || defined(__clang__)")
        c.append("#  define SOS_WEAK __attribute__((weak))")
        c.append("#else")
        c.append("#  define SOS_WEAK /* no weak-symbol support; provide a strong def */")
        c.append("#endif")
        c.append("")
        for ev in events:
            sym = f"sos_{pid}_handle_{_safe_event_symbol(ev.event_name)}"
            c.append(f"SOS_WEAK void {sym}(const sos_event_t *ev) {{")
            c.append("    (void)ev;")
            c.append("}")
        c.append("")
        c.append("/* Deterministic dispatch table (INV-SOS-G mirror). */")
        c.append(f"const sos_dispatch_entry_t {table_sym}[] = {{")
        for ev in events:
            sym = f"sos_{pid}_handle_{_safe_event_symbol(ev.event_name)}"
            c.append(
                f"    {{ 0x{ev.event_id:08x}u, {sym} }}, "
                f"/* {ev.event_name} */"
            )
        c.append("};")
        c.append(
            f"const size_t {count_sym} = "
            f"sizeof({table_sym}) / sizeof({table_sym}[0]);"
        )
    else:
        c.append("/* piece sends in-process events but handles none */")
        c.append(f"const sos_dispatch_entry_t {table_sym}[] = {{")
        c.append("    { 0u, (sos_event_handler_t)0 }  /* sentinel only */")
        c.append("};")
        c.append(f"const size_t {count_sym} = 0u;")
    c.append("")
    c.append(f"void {dispatch_fn}(const sos_event_t *ev) {{")
    c.append("    if (ev == (const sos_event_t *)0) { return; }")
    c.append(f"    for (size_t i = 0u; i < {count_sym}; ++i) {{")
    c.append(f"        if ({table_sym}[i].event_id == ev->event_id) {{")
    c.append(f"            {table_sym}[i].handler(ev);")
    c.append("            return;")
    c.append("        }")
    c.append("    }")
    c.append("}")
    c.append("")
    impl_text = "\n".join(c)
    return header_text, impl_text


def _c_blockcomment(line: str) -> str:
    """Normalise a `//` or stray `/*` comment line into proper C `/* … */`."""
    if line.startswith("/*") and line.endswith("*/"):
        return line
    if line.startswith("//"):
        # /spec-block lines all start with `//`; convert.
        return "/* " + line[2:].lstrip() + " */"
    if line.startswith("/*"):
        return "/* " + line[2:].lstrip() + " */"
    return line


# ---------------------------------------------------------------------------
# FFI bridge emission
# ---------------------------------------------------------------------------


def _emit_ffi_bridge_rs(
    *,
    events: list[EmittedEvent],
    chart_sos_id: str,
) -> str:
    """Emit ``ffi_bridge.rs`` — extern \"C\" shims for Rust↔C in-process edges.

    For each Rust↔C event we emit:
        - a `#[repr(C)]` payload struct (`<Event>Payload`) with a single
          `event_id` field for v1 (payload schema is a future sub-phase
          tracked by SOS-10 §14 unblocks); chart-authors extend by adding
          a real payload type in their crate.
        - an `extern "C"` shim `sos_dispatch_<event>(ev: *const sos_event_t)`
          that the C side can call to push an event back through the
          Rust dispatcher.
    """
    lines: list[str] = []
    lines.extend(_spec_block(chart_sos_id, comment="//"))
    lines.append("// Rust ↔ C in-process FFI bridge.")
    lines.append("//")
    lines.append("// Per SOS-10-CONCEPTS §6.1 a Rust↔C in-process boundary is")
    lines.append("// realised as `extern \"C\"` function calls with `#[repr(C)]`")
    lines.append("// payload structs. This file is the Rust-side mirror of the")
    lines.append("// C-side `sos_event_t` envelope declared in each C piece's")
    lines.append("// `<piece>_dispatch.h`.")
    lines.append("")
    lines.append("#![allow(non_camel_case_types)]")
    lines.append("#![allow(dead_code)]")
    lines.append("")
    lines.append("use core::ffi::c_void;")
    lines.append("")
    lines.append("/// C-ABI event envelope. Layout matches `sos_event_t` in the")
    lines.append("/// emitted C header — both come from the same SOS-10 §6.1")
    lines.append("/// contract so the layout is wire-format-derived, not authored.")
    lines.append("#[repr(C)]")
    lines.append("pub struct sos_event_t {")
    lines.append("    pub event_id: u32,")
    lines.append("    pub payload: *const c_void,")
    lines.append("}")
    lines.append("")
    seen_events: set[str] = set()
    for ev in events:
        if ev.event_name in seen_events:
            continue
        seen_events.add(ev.event_name)
        sym = f"sos_ffi_dispatch_{_safe_event_symbol(ev.event_name)}"
        lines.append(
            f"/// FFI shim for `{ev.event_name}` "
            f"(event_id 0x{ev.event_id:08x}; "
            f"crosses `{ev.source_piece}` ({ev.source_lang}) ↔ "
            f"`{ev.target_piece}` ({ev.target_lang}))."
        )
        lines.append(f"#[no_mangle]")
        lines.append(f"pub extern \"C\" fn {sym}(_ev: *const sos_event_t) {{")
        lines.append("    // implementer-provided body; the linker resolves the")
        lines.append("    // strong override against the C side's handler.")
        lines.append("}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Symbol helpers
# ---------------------------------------------------------------------------


def _safe_event_symbol(event_name: str) -> str:
    """Map an event name (e.g. ``"audio.start"``) to an SV-identifier token.

    Replaces every non-``[A-Za-z0-9_]`` character with ``_``; prepends
    ``ev_`` when the first char is a digit. Deterministic and reversible-
    by-inspection (the per-handler doc-comment carries the original
    event name).
    """
    safe = re.sub(r"[^A-Za-z0-9_]", "_", event_name)
    if safe and safe[0].isdigit():
        safe = f"ev_{safe}"
    return safe or "ev_unnamed"


__all__ = [
    "emit_in_process",
    "emit_in_process_from_chart",
    "EmittedEvent",
]
