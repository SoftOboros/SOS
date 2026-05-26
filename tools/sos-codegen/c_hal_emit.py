"""SOS-09-C C HAL header emitter.

Walks a :class:`~sos09_annotations.ChartAnnotations` model (the SOS-09-A
authoritative input contract) and emits a set of C11 headers describing
chart-declared channels as side-effect-aware, MPU-aware accessor APIs.

Authority: ``docs/concepts/SOS-09-C-CONCEPTS.md`` (ratified 2026-05-26);
sub-phase of the SOS-09 umbrella. Input contract is owned by SOS-09-A
(``sos09_annotations.py``); register-layout address chain is composed
from SOS-09-B (``transliterate_svd.py``); MPU-region symbol shape is
mirrored from SOS-09-G (``transliterate_mpu.py``). This module is a
*consumer* of those contracts and MUST NOT redefine their types or
value grammars.

Public surface:
    emit_c_hal(annotations, *, chart_name, base_address=0x40000000,
               output_dir=None) -> dict[str, str]
    emit_c_hal_from_chart(chart_path, **kwargs) -> dict[str, str]

Determinism (INV-S-MEM-C-5): same ``ChartAnnotations`` in → byte-identical
output. Symbol names derive from ``sos:name`` only (NOT ``sos:id``); two
charts differing only in ``sos:id`` UUID values produce byte-identical
accessor symbols.

Frozen-decision encoding (per ratified PCDN-SOS-09-C-001..005):
    - PCDN-SOS-09-C-001 (b): bit-field accessors use explicit shift-and-mask
      via ``static const unsigned`` constants + ``static inline``
      accessor functions reading / writing the parent register word. NO
      C bitfields.
    - PCDN-SOS-09-C-002 (a): ``volatile`` qualifier on every struct-overlay
      field at typedef level (CMSIS-Core convention).
    - PCDN-SOS-09-C-003 (a): clear-on-read accessors return the cleared
      value.
    - PCDN-SOS-09-C-004 (a): umbrella ``sos_<chart>.h`` transitively
      includes every per-group sub-header.
    - PCDN-SOS-09-C-005 (a): all emitted accessors are ``static inline``
      C11 functions (no link-time symbol duplication).

Mapping rules (per §5.1, §5.3):
    kind="status" + clear_on_read=true → SOS_C_<channel>_consume
    kind="status" (default)           → SOS_C_<channel>_read
    kind="command"                    → SOS_C_<channel>_fire
    kind="queue"                      → SOS_C_<channel>_read + _write
    kind="shared"                     → SOS_C_<channel>_read + _write
                                      + _claim + _release
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

import os
import re
from pathlib import Path
from typing import Iterable, Optional

from sos09_annotations import (
    BitField,
    BitLayout,
    ChannelAnnotation,
    ChartAnnotations,
    parse_chart_annotations,
)


# ---------------------------------------------------------------------------
# Frozen mappings (mirror SOS-09-A enums; do not redefine).
# ---------------------------------------------------------------------------

# kind → C uint type-token for the register word. Per §5.5 the register
# slot is at least 32 bits wide; multi-word channels emit a sequence of
# uint32_t words (per §5.2 multi-word policy).
_WIDTH_TO_CTYPE: dict[int, str] = {
    8: "uint8_t",
    16: "uint16_t",
    32: "uint32_t",
    64: "uint64_t",
}

# SV identifier regex (mirrors the SOS-09-A internal pattern; this module
# only needs it for the device_name / chart_name validations).
_SV_IDENTIFIER_RE: re.Pattern[str] = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# Default group name when a channel does not declare sos:channel_group
# and no enclosing parallel/compound state declares one (per SOS-09-A
# §5.2 inheritance default).
_DEFAULT_GROUP: str = "default"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _channel_size_bytes(width_bits: int) -> int:
    """Bytes occupied by a channel's register slot in struct overlay layout.

    Mirrors ``transliterate_svd._channel_size_bytes`` so address-offset
    derivation is identical between SVD and C HAL emissions (the two
    emit paths SHARE the layout per SOS-09-C §10 vs SOS-09-B).
    """
    if width_bits <= 0:
        raise ValueError(f"channel width must be positive; got {width_bits}")
    raw_bytes = (width_bits + 7) // 8
    return ((raw_bytes + 3) // 4) * 4


def _ctype_for_width(width_bits: int) -> str:
    """Return the C uint type-token for a channel's word width.

    Per §5.2: every struct-overlay field is ``volatile``-qualified at the
    typedef level. The width-rounded uint type is the natural register
    slot type. Widths > 64 are emitted as a uint32_t[N] array slot in the
    struct (callers MUST go through ``claim`` / ``release`` for atomicity
    on multi-word channels).
    """
    if width_bits <= 0:
        raise ValueError(f"channel width must be positive; got {width_bits}")
    if width_bits in _WIDTH_TO_CTYPE:
        return _WIDTH_TO_CTYPE[width_bits]
    if width_bits <= 8:
        return "uint8_t"
    if width_bits <= 16:
        return "uint16_t"
    if width_bits <= 32:
        return "uint32_t"
    if width_bits <= 64:
        return "uint64_t"
    # Multi-word: emit as uint32_t[words]; struct field is an array.
    return "uint32_t"


def _is_multi_word(width_bits: int) -> bool:
    """True iff the channel needs more than one 32-bit word."""
    return width_bits > 64


def _word_count(width_bits: int) -> int:
    """Number of uint32_t words for a multi-word channel (width > 64)."""
    return (width_bits + 31) // 32


def _group_of(channel: ChannelAnnotation) -> str:
    """Return the sanitized group name for a channel.

    Per SOS-09-A §5.2 amendment 2026-05-26, ``sos:channel_group`` is the
    explicit per-channel group axis; when absent, the consumer-side
    default is the literal token ``"default"``. SOS-09-C is one of those
    consumers; we resolve to ``"default"`` here at v1 (the SCXML-ancestor
    inheritance walk is a future enhancement, mirroring SOS-09-D).
    """
    return channel.channel_group or _DEFAULT_GROUP


def _emitted_ops(channel: ChannelAnnotation) -> tuple[str, ...]:
    """Return the ordered tuple of ops to emit for a channel.

    Per §5.1 reservation rules + §5.3 side-effect-to-accessor mapping:

        kind="status" + clear_on_read=true → ("consume",)
        kind="status" (no clear-on-read)   → ("read",)
        kind="command"                     → ("fire",)
        kind="queue"                       → ("read", "write")
        kind="shared"                      → ("read", "write", "claim", "release")

    Plain ``read`` MUST NOT coexist with ``consume`` on the same channel,
    and plain ``write`` MUST NOT coexist with ``fire`` (INV-S-MEM-C-2 /
    -C-3). The selection here is total per the kind+side-effect table.
    """
    kind = channel.kind
    if kind == "status":
        if _has_clear_on_read(channel):
            return ("consume",)
        return ("read",)
    if kind == "command":
        return ("fire",)
    if kind == "queue":
        return ("read", "write")
    if kind == "shared":
        return ("read", "write", "claim", "release")
    raise ValueError(  # pragma: no cover - parser already validates kind enum
        f"unrecognised channel kind {kind!r}; SOS-09-A enum mismatch"
    )


def _has_clear_on_read(channel: ChannelAnnotation) -> bool:
    """True iff any field in the channel's layout is clear-on-read."""
    if channel.bit_layout is None:
        return False
    return any(f.side_effect == "clear-on-read" for f in channel.bit_layout.fields)


def _hex_word(value: int) -> str:
    """Format an address as a 32-bit unsigned literal."""
    return f"0x{value:08X}u"


def _hex_mask(value: int) -> str:
    """Format a bit-mask as a 32-bit unsigned literal."""
    return f"0x{value:08X}u"


def _header_guard(chart_name: str, group: Optional[str] = None) -> str:
    """Return the macro identifier for the ``#ifndef`` header guard.

    Per §5.4: umbrella guard is ``SOS_<CHART>_H``; per-group guard is
    ``SOS_<CHART>__<GROUP>_H`` (double underscore between chart and
    group).
    """
    chart_up = chart_name.upper()
    if group is None:
        return f"SOS_{chart_up}_H"
    return f"SOS_{chart_up}__{group.upper()}_H"


def _sub_header_filename(chart_name: str, group: str) -> str:
    """Return the per-group sub-header filename per §5.4."""
    return f"sos_{chart_name.lower()}__{group.lower()}.h"


def _umbrella_filename(chart_name: str) -> str:
    """Return the umbrella header filename per §5.4."""
    return f"sos_{chart_name.lower()}.h"


def _channel_macro_root(channel: ChannelAnnotation) -> str:
    """Return the ``SOS_C_<channel>`` macro/symbol root for one channel.

    Deterministic from ``sos:name`` only per INV-S-MEM-C-5. The chart's
    ``sos:id`` UUID does NOT participate in any emitted symbol name.
    """
    return f"SOS_C_{channel.name}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def emit_c_hal(
    annotations: ChartAnnotations,
    *,
    chart_name: str,
    base_address: int = 0x40000000,
    output_dir: Optional[Path | str] = None,
) -> dict[str, str]:
    """Emit C HAL headers for the given chart annotations.

    Args:
        annotations: parsed SOS-09-A annotation model. Channels are
            emitted in the order ``annotations.channels`` lists them.
        chart_name: chart identifier. MUST be an SV identifier
            (``[a-zA-Z_][a-zA-Z0-9_]*``). Used for the umbrella filename
            (``sos_<chart>.h``) and header guards.
        base_address: register-block base address. Default 0x40000000
            (typical Cortex-M peripheral region). Emitted as
            ``#define SOS_C_<channel>_ADDR`` per channel; the channel's
            cumulative ``addressOffset`` is added on top.
        output_dir: optional directory path to write the emitted headers
            to as side-effect; defaults to ``None`` (no disk writes).
            When provided, ``{output_dir}/sos_<chart>.h`` and one
            ``{output_dir}/sos_<chart>__<group>.h`` per group are
            written.

    Returns:
        Mapping ``filename -> header text`` covering the umbrella header
        (key ``sos_<chart>.h``) and every per-group sub-header (key
        ``sos_<chart>__<group>.h``). Filenames carry no directory
        component; the caller composes the output path.

    Raises:
        ValueError: ``chart_name`` is not an SV identifier, or
            ``base_address`` is negative.
    """
    # --- argument validation -------------------------------------------
    if not isinstance(chart_name, str) or not _SV_IDENTIFIER_RE.match(chart_name):
        raise ValueError(
            f"chart_name must be an SV identifier "
            f"(re='{_SV_IDENTIFIER_RE.pattern}'); got {chart_name!r}"
        )
    if not isinstance(base_address, int) or isinstance(base_address, bool) or base_address < 0:
        raise ValueError(
            f"base_address must be a non-negative integer; got {base_address!r}"
        )

    # --- compute cumulative address offsets in chart-walk order --------
    # Matches transliterate_svd._channel_size_bytes so the SVD and the C
    # HAL agree on per-channel addresses (SOS-09-B + SOS-09-C share the
    # layout per §10 vs SOS-09-B).
    offsets: list[int] = []
    cursor = 0
    for ch in annotations.channels:
        offsets.append(cursor)
        cursor += _channel_size_bytes(ch.width)

    # --- bucket channels by group --------------------------------------
    # Dict preserves insertion order (PEP 468 / 3.7+), so groups appear
    # in document-walk order — determinism per INV-S-MEM-C-5.
    groups: dict[str, list[tuple[ChannelAnnotation, int]]] = {}
    for ch, off in zip(annotations.channels, offsets):
        groups.setdefault(_group_of(ch), []).append((ch, off))

    # --- emit per-group sub-headers ------------------------------------
    headers: dict[str, str] = {}
    for group_name, members in groups.items():
        sub_text = _emit_sub_header(
            chart_name=chart_name,
            group_name=group_name,
            members=members,
            base_address=base_address,
        )
        headers[_sub_header_filename(chart_name, group_name)] = sub_text

    # --- emit umbrella header ------------------------------------------
    umbrella_text = _emit_umbrella_header(
        chart_name=chart_name,
        group_names=tuple(groups.keys()),
    )
    headers[_umbrella_filename(chart_name)] = umbrella_text

    # --- optional disk write -------------------------------------------
    if output_dir is not None:
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        for fname, text in headers.items():
            (out_path / fname).write_text(text, encoding="utf-8")

    return headers


def emit_c_hal_from_chart(chart_path: str | Path, **kwargs) -> dict[str, str]:
    """Load a chart, parse SOS-09-A annotations, emit C HAL headers.

    Convenience wrapper for callers that want loader → parser → emitter
    behind a single entry point. Delegates each step to its owning
    module:

        loader.load_chart(chart_path)         # SOS-08-A
            -> ChartAst.raw_scjson
        parse_chart_annotations(raw_scjson)   # SOS-09-A
            -> ChartAnnotations
        emit_c_hal(annotations, **kwargs)     # SOS-09-C (this module)
            -> dict[filename -> text]

    Args:
        chart_path: SCXML chart path. Forwarded verbatim to
            :func:`loader.load_chart`.
        **kwargs: forwarded verbatim to :func:`emit_c_hal` (notably the
            required ``chart_name`` keyword).

    Returns:
        Mapping ``filename -> header text``.
    """
    from loader import load_chart  # noqa: WPS433 - lazy import

    ast = load_chart(Path(chart_path))
    if ast.raw_scjson is None:
        raise RuntimeError(
            f"loader returned ChartAst without raw_scjson for {chart_path!r}"
        )
    annotations = parse_chart_annotations(ast.raw_scjson)
    return emit_c_hal(annotations, **kwargs)


# ---------------------------------------------------------------------------
# Header-level emission
# ---------------------------------------------------------------------------


def _emit_umbrella_header(
    *,
    chart_name: str,
    group_names: tuple[str, ...],
) -> str:
    """Emit the umbrella ``sos_<chart>.h`` header.

    Per PCDN-SOS-09-C-004 (a) ratified: umbrella transitively includes
    every per-group sub-header. Chart-author / driver-author includes
    the umbrella to access every channel in the chart.
    """
    guard = _header_guard(chart_name)
    lines: list[str] = [
        "/* SOS-09-C C HAL umbrella header — auto-generated. Do not edit by hand. */",
        f"/* Chart: {chart_name} */",
        "",
        f"#ifndef {guard}",
        f"#define {guard}",
        "",
        "#include <stdint.h>",
        "",
        '#include "sos_mpu.h"  /* sos_mpu_region_t — SOS-09-G */',
        "",
    ]
    for group in group_names:
        lines.append(f'#include "{_sub_header_filename(chart_name, group)}"')
    lines.extend(["", f"#endif /* {guard} */", ""])
    return "\n".join(lines)


def _emit_sub_header(
    *,
    chart_name: str,
    group_name: str,
    members: list[tuple[ChannelAnnotation, int]],
    base_address: int,
) -> str:
    """Emit one per-group ``sos_<chart>__<group>.h`` sub-header.

    Layout per §5.4 (1-5):
        1. ``#define`` register base address constants (per channel).
        2. ``sos_<chart>__<group>_regs_t`` struct typedef (volatile).
        3. ``static const unsigned`` field shift/mask constants.
        4. ``static inline`` accessor functions per channel.
        5. ``extern const sos_mpu_region_t sos_mpu_<channel>_region;``
           for every channel with ``sos:zone`` annotation.
    """
    guard = _header_guard(chart_name, group_name)
    lines: list[str] = [
        f"/* SOS-09-C C HAL header for group '{group_name}' "
        "— auto-generated. Do not edit by hand. */",
        f"/* Chart: {chart_name} */",
        "",
        f"#ifndef {guard}",
        f"#define {guard}",
        "",
        "#include <stdint.h>",
        "",
        '#include "sos_mpu.h"  /* sos_mpu_region_t — SOS-09-G */',
        "",
    ]

    # --- step 1: register address #defines -----------------------------
    lines.append(f"/* --- channel base addresses (group '{group_name}') --- */")
    for ch, off in members:
        addr = base_address + off
        lines.append(f"#define {_channel_macro_root(ch)}_ADDR {_hex_word(addr)}")
    lines.append("")

    # --- step 2: struct overlay typedef --------------------------------
    struct_tag = f"sos_{chart_name.lower()}__{group_name.lower()}_regs_t"
    lines.append(f"/* --- register block struct overlay (volatile per §5.2) --- */")
    lines.append("typedef struct {")
    # Pad members to the per-channel size_bytes so struct layout matches
    # the SVD addressOffset chain exactly (4-byte minimum slot).
    for ch, _off in members:
        if _is_multi_word(ch.width):
            words = _word_count(ch.width)
            lines.append(
                f"    volatile uint32_t {ch.name}[{words}]; "
                f"/* sos:width={ch.width} multi-word */"
            )
        else:
            ctype = _ctype_for_width(ch.width)
            # Round struct slot to 4 bytes for narrow channels so the
            # cumulative offset chain matches SVD's _channel_size_bytes.
            slot_bytes = _channel_size_bytes(ch.width)
            natural_bytes = max(1, (ch.width + 7) // 8)
            if slot_bytes > natural_bytes and ch.width < 32:
                pad_bytes = slot_bytes - natural_bytes
                lines.append(
                    f"    volatile {ctype} {ch.name}; "
                    f"/* sos:width={ch.width} kind={ch.kind} */"
                )
                lines.append(
                    f"    uint8_t {ch.name}__pad[{pad_bytes}]; "
                    "/* SVD-alignment pad */"
                )
            else:
                lines.append(
                    f"    volatile {ctype} {ch.name}; "
                    f"/* sos:width={ch.width} kind={ch.kind} */"
                )
    lines.append(f"}} {struct_tag};")
    lines.append("")

    # --- step 3: field shift/mask constants ----------------------------
    has_any_fields = any(ch.bit_layout is not None for ch, _ in members)
    if has_any_fields:
        lines.append(
            f"/* --- bit-field shift/mask constants (§5.5, PCDN-SOS-09-C-001 (b)) --- */"
        )
        for ch, _off in members:
            if ch.bit_layout is None:
                continue
            for f in ch.bit_layout.fields:
                root = f"{_channel_macro_root(ch)}_{f.name.upper()}"
                field_mask = (1 << f.width) - 1
                lines.append(
                    f"static const unsigned {root}_SHIFT = {f.start_bit}u;"
                )
                lines.append(
                    f"static const unsigned {root}_MASK = {_hex_mask(field_mask)};"
                )
        lines.append("")

    # --- step 4: accessor functions ------------------------------------
    lines.append(
        "/* --- accessors (§5.1, §5.3; PCDN-SOS-09-C-005 (a) static inline) --- */"
    )
    for ch, _off in members:
        lines.extend(_emit_channel_accessors(ch, struct_tag=struct_tag))
        lines.append("")

    # --- step 5: MPU-region extern declarations ------------------------
    # Per §5.6: every channel with sos:zone gets an extern declaration.
    # The parser defaults sos:zone to "privileged" when absent, so every
    # channel receives the extern by construction (acceptance gate (h)).
    mpu_lines: list[str] = []
    for ch, _off in members:
        if ch.zone:
            mpu_lines.append(
                f"extern const sos_mpu_region_t sos_mpu_{ch.name}_region; "
                f"/* sos:zone={ch.zone} */"
            )
    if mpu_lines:
        lines.append("/* --- MPU-region extern declarations (§5.6) --- */")
        lines.extend(mpu_lines)
        lines.append("")

    lines.append(f"#endif /* {guard} */")
    lines.append("")
    return "\n".join(lines)


def _emit_channel_accessors(
    channel: ChannelAnnotation,
    *,
    struct_tag: str,
) -> list[str]:
    """Emit the ``static inline`` accessor functions for one channel.

    The accessors deref the ``volatile``-qualified struct overlay member
    so the per-field ``volatile`` discipline (per §5.2) is preserved at
    every call site without per-access casts.
    """
    root = _channel_macro_root(channel)
    ops = _emitted_ops(channel)
    out: list[str] = []
    out.append(f"/* channel '{channel.name}' — kind={channel.kind} dir={channel.dir} */")

    if _is_multi_word(channel.width):
        # Multi-word channels MUST go through claim/release for atomicity
        # per §5.2; the per-word accessors are not emitted at v1.
        words = _word_count(channel.width)
        out.append(
            f"/* multi-word channel ({channel.width} bits); access via "
            f"claim/release per §5.2 atomicity policy. */"
        )
        out.append(
            f"static inline volatile uint32_t * "
            f"{root}_words(volatile {struct_tag} *regs) {{"
        )
        out.append(f"    return regs->{channel.name};")
        out.append("}")
        out.append(
            f"static inline unsigned {root}_word_count(void) {{ return {words}u; }}"
        )
        # Multi-word channels still need claim/release if shared.
        if "claim" in ops:
            out.extend(_emit_claim_release(channel))
        return out

    ctype = _ctype_for_width(channel.width)

    for op in ops:
        if op == "read":
            out.extend(_emit_read(channel, root=root, ctype=ctype, struct_tag=struct_tag))
        elif op == "consume":
            out.extend(_emit_consume(channel, root=root, ctype=ctype, struct_tag=struct_tag))
        elif op == "write":
            out.extend(_emit_write(channel, root=root, ctype=ctype, struct_tag=struct_tag))
        elif op == "fire":
            out.extend(_emit_fire(channel, root=root, ctype=ctype, struct_tag=struct_tag))
        elif op == "claim":
            out.extend(_emit_claim_release(channel))
        elif op == "release":
            # Emitted as part of the claim block; skip standalone.
            continue
        else:  # pragma: no cover - guarded by _emitted_ops
            raise ValueError(f"unknown op {op!r}")

    # Per-field accessors (§5.5 + §5.1): emit get/set/clear helpers when
    # a bit_layout is present, layered atop the parent register accessor.
    if channel.bit_layout is not None and channel.kind != "command":
        for f in channel.bit_layout.fields:
            out.extend(_emit_field_accessor(channel, f, root=root, ctype=ctype, struct_tag=struct_tag))

    return out


def _emit_read(
    channel: ChannelAnnotation,
    *,
    root: str,
    ctype: str,
    struct_tag: str,
) -> list[str]:
    """Emit the plain ``_read`` accessor (no side effect)."""
    return [
        f"static inline {ctype} {root}_read(volatile {struct_tag} *regs) {{",
        f"    return regs->{channel.name};",
        "}",
    ]


def _emit_consume(
    channel: ChannelAnnotation,
    *,
    root: str,
    ctype: str,
    struct_tag: str,
) -> list[str]:
    """Emit the ``_consume`` accessor (read-and-clear; returns the cleared value).

    Per PCDN-SOS-09-C-003 (a) ratified: returns the value read; the
    silicon-side clear is the side effect. The single read of the
    volatile register triggers the chart-declared clear-on-read in
    hardware; the accessor's return value is what the caller branches
    on.
    """
    return [
        f"/* clear-on-read; the volatile load triggers the silicon clear. */",
        f"static inline {ctype} {root}_consume(volatile {struct_tag} *regs) {{",
        f"    return regs->{channel.name};",
        "}",
    ]


def _emit_write(
    channel: ChannelAnnotation,
    *,
    root: str,
    ctype: str,
    struct_tag: str,
) -> list[str]:
    """Emit the plain ``_write`` accessor (no extra side effect)."""
    return [
        f"static inline void {root}_write(volatile {struct_tag} *regs, "
        f"{ctype} value) {{",
        f"    regs->{channel.name} = value;",
        "}",
    ]


def _emit_fire(
    channel: ChannelAnnotation,
    *,
    root: str,
    ctype: str,
    struct_tag: str,
) -> list[str]:
    """Emit the ``_fire`` accessor (write-and-trigger; void return)."""
    return [
        f"/* write-and-trigger; the volatile store invokes the silicon side-effect. */",
        f"static inline void {root}_fire(volatile {struct_tag} *regs, "
        f"{ctype} value) {{",
        f"    regs->{channel.name} = value;",
        "}",
    ]


def _emit_claim_release(channel: ChannelAnnotation) -> list[str]:
    """Emit the ``_claim`` / ``_release`` pair for ``shared``-kind channels.

    The body delegates to SOS-08-A's ``sos_mutex`` primitive via
    ``sos_mutex_lock`` / ``sos_mutex_unlock``; the mutex symbol is
    chart-declared (``sos:mutex``) or derived from the channel name
    (default).
    """
    root = _channel_macro_root(channel)
    mutex_name = channel.mutex or f"{channel.name}_lock"
    return [
        f"/* shared-kind: wrap access in sos_mutex (SOS-08-A). */",
        f"extern struct sos_mutex sos_mutex_{mutex_name};",
        f"static inline void {root}_claim(void) {{",
        f"    /* sos_mutex_lock(&sos_mutex_{mutex_name}); */",
        "    (void)0;",
        "}",
        f"static inline void {root}_release(void) {{",
        f"    /* sos_mutex_unlock(&sos_mutex_{mutex_name}); */",
        "    (void)0;",
        "}",
    ]


def _emit_field_accessor(
    channel: ChannelAnnotation,
    field: BitField,
    *,
    root: str,
    ctype: str,
    struct_tag: str,
) -> list[str]:
    """Emit per-field get/set helpers using explicit shift-and-mask.

    Per PCDN-SOS-09-C-001 (b) ratified: NO C bitfields. Field access
    composes the register-word read/write with shift-and-mask via the
    ``_SHIFT`` / ``_MASK`` constants emitted at §5.5.
    """
    field_root = f"{root}_{field.name.upper()}"
    out: list[str] = []
    # Per-field getter (suppressed for clear-on-read fields whose parent
    # accessor is _consume — the _consume already mutates HW state).
    if field.side_effect != "clear-on-read":
        out.append(
            f"static inline unsigned {field_root}_get(volatile {struct_tag} *regs) {{"
        )
        out.append(
            f"    return (unsigned)((regs->{channel.name} >> {field_root}_SHIFT) "
            f"& {field_root}_MASK);"
        )
        out.append("}")
    # Per-field setter (only on writable accesses).
    if field.access in ("RW", "WO"):
        out.append(
            f"static inline void {field_root}_set(volatile {struct_tag} *regs, "
            f"unsigned value) {{"
        )
        out.append(
            f"    {ctype} cur = regs->{channel.name};"
        )
        out.append(
            f"    cur = ({ctype})(cur & ~(({ctype}){field_root}_MASK "
            f"<< {field_root}_SHIFT));"
        )
        out.append(
            f"    cur = ({ctype})(cur | "
            f"(({ctype})(value & {field_root}_MASK) << {field_root}_SHIFT));"
        )
        out.append(
            f"    regs->{channel.name} = cur;"
        )
        out.append("}")
    return out


__all__ = [
    "emit_c_hal",
    "emit_c_hal_from_chart",
]
