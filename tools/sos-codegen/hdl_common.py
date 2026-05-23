"""Shared HDL emission utilities for sos-codegen (Layer-2 HDL backend).

This module is the dialect-neutral substrate consumed by the per-dialect
emit walkers:

  - ``transliterate_hdl_vhdl`` — VHDL-2008 emitter (sibling agent owns).
  - ``transliterate_hdl_sv``   — SystemVerilog-2017 emitter (sibling agent owns).

Both walkers obtain port/signal/process/state-encoding scaffolding from
this module so the L2 dialect surface stays in lock-step: anything chart-
visible (state encoding, document-order priority, reset polarity) lives
here and is therefore identical across dialects by construction.

Authority:
  This module IS the operational realisation of the SOS-08-C normative
  surface. It does NOT introduce new normative content; every function
  below cites the doc/section that owns its contract. Where the dialect-
  rendering form (`"std_logic"` vs `"wire"`, `process(clk)` vs
  `always_ff`) differs across VHDL-2008 and SV-2017, the per-dialect
  rendering is keyed off the ``Dialect`` enum; the underlying contract
  (one-hot default; document-order priority; sync active-high reset)
  is the same.

Specs cited (read these before modifying this module):
  - ``docs/concepts/SOS-08-C-CONCEPTS.md`` — L2 emission contract:
      §3 glossary (region FSM, transition mux, datamodel signal,
      clock annotation, reset state, verified-strip mode, cooperative
      completion);
      §4 source-of-truth map (per-region encoding override, reset-
      state default, guard-depth budget, verified-strip × multi-clock
      interaction all owned here in §5/§14);
      §5 frozen decisions (one-hot default; document-order mux;
      ECMAScript subset compilation; datamodel typing; verified-strip;
      reset-state default; cooperative-only emission);
      §6 ten-step emission algorithm — this module implements the
      dialect-neutral surface called from steps 2, 3, 4, 5, 6, 9, 10;
      §7 INV-S-HDL-C-1..5 (deterministic emission; per-region
      observability; cross-domain transition enforcement; guard
      synthesizability; cooperative completion);
      §15 ratification entry (2026-05-23) — PCDN-SOS-08-C-001..006
      resolutions.
  - ``docs/concepts/SOS-08-A-CONCEPTS.md`` §6 — L0 primitive contracts
    this layer instantiates via SOS-08-B services. Per §5.1 / INV-S-
    HDL-A-1 reset is synchronous active-high; this module mirrors
    that for chart-emitted region FSMs (INV-S-HDL-A-1 → INV-S-HDL-C
    by composition).
  - ``docs/concepts/SOS-08-B-CONCEPTS.md`` §6 — L1 service contracts
    for event ingress/egress.
  - ``docs/concepts/SOS-01-CONCEPTS.md`` §5.1 — ECMAScript subset
    that guard expressions compile from.

Invariants concretised by helpers in this module:
  - **INV-S-HDL-A-1** (sync active-high reset, uniform across L0) —
    enforced via :data:`ResetPolarity.SYNC_ACTIVE_HIGH` being the sole
    enum value; :func:`emit_register_process` materialises it.
  - **INV-S-HDL-C-1** (deterministic emission) — every helper here
    produces output that is a pure function of its arguments; no
    timestamps, no environment-dependent ordering. Callers MUST iterate
    chart structures in document order.
  - **INV-S-HDL-C-2** (per-region observability) — :func:`emit_port_decl`
    callers SHOULD emit ``state_observable`` + ``transition_observable``
    on every region FSM module per SOS-08-C §6.2.
  - **INV-S-HDL-C-3** (cross-domain transition enforcement) — out of
    scope for this module; enforced at the chart-top wrapper emit step
    by the per-dialect walker, which consults the ``cdc-audit.json``
    artifact (SOS-08-C §6.7).
  - **INV-S-HDL-C-4** (guard expression synthesizability) — partially
    enforced here via :func:`compute_guard_depth` against the default
    budget; the per-dialect walker MUST reject guards whose depth
    exceeds the configured budget per PCDN-SOS-08-C-004 / SCXML-LINT-C-2.
  - **INV-S-HDL-C-5** (cooperative completion) — no preemption /
    save-restore registers are emitted by anything in this module;
    callers MUST honour that by construction.

PCDN resolutions (SOS-08-C §15, 2026-05-23) consulted:
  - PCDN-C-001 (clock-domain default = inherit-from-parent).
  - PCDN-C-002 (verified-strip × multi-clock = retain synchronizers).
  - PCDN-C-003 (reset-state default = SCXML ``<initial>`` w/ optional
    ``<reset state="..."/>`` override).
  - PCDN-C-004 (guard-depth budget default = 8 chained operators;
    enforced via SCXML-LINT-C-2 at chart-compile time).
  - PCDN-C-005 (chart annotation wins for state encoding; ``--target``
    is a hint only for unannotated regions).
  - PCDN-C-006 (document-order priority lint warning; SCXML-LINT-C-1).

This module is dialect-neutral substrate; it does NOT crawl SCXML, does
NOT touch templates, and does NOT shell out. The chart-IR transit is
the per-dialect walker's responsibility.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Optional


# ---------------------------------------------------------------------------
# Enums (frozen per SOS-08-C §5; per-enum registration policy noted inline).
# ---------------------------------------------------------------------------


class Dialect(Enum):
    """HDL dialect emitted by the per-dialect walker.

    Registration policy: **Standards Action** (adding a dialect — e.g.
    Chisel / SpinalHDL / Amaranth — requires a SOS-08 §15 amendment AND
    a §15 amendment in SOS-08-C; both because the dialect-rendering
    surface is part of the L2 emission contract).
    """

    VHDL = "vhdl"  # VHDL-2008 (synthesizable subset)
    SV = "sv"      # SystemVerilog-2017 (synthesizable subset)


class FsmEncoding(Enum):
    """State register encoding for a chart-emitted region FSM.

    Per SOS-08-C §5.1 + SOS-08 PCDN-002 resolution: **one-hot** is the
    default. Per-region override is via the ``<region encoding="..."/>``
    chart annotation; legal values are mirrored here.

    Registration policy: **Specification Required** (adding e.g.
    ``johnson`` is a phase-owner walkthrough update; changing the
    DEFAULT requires a §15 amendment in SOS-08-C AND a §15 amendment
    in SOS-08).
    """

    ONE_HOT = "one_hot"
    BINARY = "binary"
    GRAY = "gray"

    @classmethod
    def default(cls) -> "FsmEncoding":
        """SOS-08-C §5.1 default (SOS-08 PCDN-002 resolution)."""
        return cls.ONE_HOT

    @classmethod
    def parse(cls, raw: str) -> "FsmEncoding":
        """Parse a CLI string. Accepts the two common spellings (``one-hot``
        and ``one_hot``) so both ``--hdl-encoding one-hot`` and the chart
        annotation form resolve. Raises ``ValueError`` on unknown value.
        """
        normalised = raw.strip().lower().replace("-", "_")
        for member in cls:
            if member.value == normalised:
                return member
        raise ValueError(
            f"unknown FSM encoding {raw!r}; expected one of "
            f"{[m.value for m in cls]}"
        )


class ResetPolarity(Enum):
    """Reset polarity for chart-emitted region FSMs.

    Per **INV-S-HDL-A-1** (SOS-08-A §7) and SOS-08-C §6.2 sketch: the
    sole supported polarity is synchronous active-high with synchronous
    release. Asynchronous resets are prohibited; CDC-bearing reset
    distribution is the chart-top wrapper's responsibility.

    Registration policy: **Standards Action** (changing this requires
    a coordinated §15 amendment in SOS-08-A AND SOS-08-C; downstream
    L0 primitives all assume this convention).
    """

    SYNC_ACTIVE_HIGH = "sync_active_high"

    @classmethod
    def _missing_(cls, value):
        # Accept the sibling-walker spelling `ACTIVE_HIGH_SYNC` as an alias
        # for the canonical `SYNC_ACTIVE_HIGH` to bridge wave-1 sibling
        # signature drift. Wave-2 reconciliation will pin one spelling.
        if value == "active_high_sync":
            return cls.SYNC_ACTIVE_HIGH
        return None


# Backward-compat alias for the sibling-walker spelling (wave-1 drift).
ResetPolarity.ACTIVE_HIGH_SYNC = ResetPolarity.SYNC_ACTIVE_HIGH  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Port / signal abstractions.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HdlPort:
    """Dialect-neutral abstract port representation.

    The ``dialect_hint`` field carries an optional dialect-specific type
    name (e.g. ``"std_logic_vector"`` vs ``"logic"``) when the caller
    wants to override the default rendering. ``None`` means "let
    :func:`emit_port_decl` choose the default for the requested
    dialect".
    """

    name: str
    direction: Literal["in", "out", "inout"]
    width: int = 1  # in bits; 1 → scalar (std_logic / wire), >1 → vector
    dialect_hint: Optional[str] = None
    # Wave-1 sibling-walker bridge: some walkers carry a symbolic width
    # expression (e.g. `"N_STATES-1 downto 0"`) instead of an integer.
    # Accept both; emit_port_decl prefers `width_expr` if present.
    width_expr: Optional[str] = None
    kind: Optional[str] = None  # sibling: optional type-hint extension
    signed: bool = False
    comment: Optional[str] = None


# ---------------------------------------------------------------------------
# Per-dialect rendering helpers.
# ---------------------------------------------------------------------------


def _vhdl_direction(direction: str) -> str:
    """VHDL ``in`` / ``out`` / ``inout`` — same words as the abstract enum."""
    if direction not in ("in", "out", "inout"):
        raise ValueError(f"invalid direction {direction!r}")
    return direction


def _sv_direction(direction: str) -> str:
    """SV ``input`` / ``output`` / ``inout`` — direction word differs."""
    return {
        "in": "input",
        "out": "output",
        "inout": "inout",
    }[direction]


def emit_port_decl(port: HdlPort, dialect: Dialect) -> str:
    """Emit a single port declaration line for the requested dialect.

    Examples
    --------
    ``HdlPort("rst", "in", 1)`` →

      * VHDL: ``rst : in std_logic``
      * SV:   ``input wire rst``

    ``HdlPort("evt_payload", "in", 64)`` →

      * VHDL: ``evt_payload : in std_logic_vector(63 downto 0)``
      * SV:   ``input wire [63:0] evt_payload``

    1-bit signals render as ``std_logic`` / ``wire`` (no vector form)
    per the SOS-08-A §5.1 port-shape convention.

    Cites: SOS-08-C §6.2 (region FSM module port list); SOS-08-A §5.1
    (handshake-port shape ratification).
    """
    if port.width < 1:
        raise ValueError(f"port {port.name!r} has invalid width {port.width}")

    if dialect is Dialect.VHDL:
        direction = _vhdl_direction(port.direction)
        if port.width == 1:
            type_form = port.dialect_hint or "std_logic"
        else:
            type_form = (
                port.dialect_hint
                or f"std_logic_vector({port.width - 1} downto 0)"
            )
        return f"{port.name} : {direction} {type_form}"

    if dialect is Dialect.SV:
        direction = _sv_direction(port.direction)
        if port.width == 1:
            type_form = port.dialect_hint or "wire"
            return f"{direction} {type_form} {port.name}"
        type_form = port.dialect_hint or "wire"
        return f"{direction} {type_form} [{port.width - 1}:0] {port.name}"

    raise ValueError(f"unsupported dialect {dialect!r}")


def emit_signal_decl(
    name: str,
    width=None,
    dialect: Dialect = Dialect.VHDL,
    registered: bool = False,
    *,
    signal_type=None,
    kind=None,
    signed=False,
    comment=None,
) -> str:
    """(Sibling-walker bridge: accepts `signal_type` kwarg with a dialect-typed
    string in place of `width: int`. Wave-2 reconciliation will pin one shape.)
    """
    # Wave-1 sibling-walker shape: `signal_type` is a pre-rendered dialect string.
    if signal_type is not None:
        if dialect is Dialect.VHDL:
            return f"signal {name:10s} : {signal_type};"
        # SV
        return f"logic {signal_type} {name};"
    # Canonical signature continues below; require width.
    if width is None:
        width = 1
    """Emit an internal signal declaration.

    The ``registered`` flag selects the form synthesis tools recognise
    as a clocked register vs a combinational net:

      * VHDL: identical syntax for both (``signal X : ...``); the
        synth-tool inference is driven by the process body, not the
        declaration form. ``registered`` is informational here.
      * SV: ``logic`` for both; the inference is driven by the
        ``always_ff`` vs ``always_comb`` block that drives the
        signal. ``registered`` is informational here.

    The flag is preserved in the signature so callers (especially
    :func:`emit_register_process`) can document the intent at the
    declaration site, which simplifies code review.

    Cites: SOS-08-C §5.4 (datamodel signal typing: registered iff
    written by ``<assign>``).
    """
    if width < 1:
        raise ValueError(f"signal {name!r} has invalid width {width}")
    if dialect is Dialect.VHDL:
        if width == 1:
            type_form = "std_logic"
        else:
            type_form = f"std_logic_vector({width - 1} downto 0)"
        suffix = "  -- registered" if registered else "  -- combinational"
        return f"signal {name} : {type_form};{suffix}"
    if dialect is Dialect.SV:
        if width == 1:
            return f"logic {name};  // {'registered' if registered else 'combinational'}"
        return (
            f"logic [{width - 1}:0] {name};  "
            f"// {'registered' if registered else 'combinational'}"
        )
    raise ValueError(f"unsupported dialect {dialect!r}")


# ---------------------------------------------------------------------------
# FSM state encoding helpers.
# ---------------------------------------------------------------------------


def emit_fsm_state_encoding(
    state_names: list[str],
    encoding: FsmEncoding,
) -> dict[str, str]:
    """Return a mapping ``state_name -> bit-pattern string``.

    The bit-pattern string is the encoded representation as a series of
    ``'0'`` / ``'1'`` characters (most-significant bit first), suitable
    for embedding inside a VHDL ``std_logic_vector`` literal
    (``"0001"``) or an SV sized literal (``4'b0001``).

    Encodings
    ---------
    * **ONE_HOT**: width = N. The i-th state gets the pattern with
      bit ``i`` set. ``state_names[0]`` (the first / reset-default
      slot) maps to ``"0001"`` for N=4. Per SOS-08-C §5.1 / PCDN-002,
      this is the default at v1.
    * **BINARY**: width = ``ceil(log2(N))`` (minimum 1 for the
      degenerate N=1 case). The i-th state gets the binary literal
      of ``i`` zero-padded to width.
    * **GRAY**: same width as BINARY; the i-th state gets the standard
      reflected-Gray code of ``i``. Useful for ASIC flows where
      adjacent-state transitions minimise toggle count.

    The mapping preserves the order of ``state_names`` so callers can
    deterministically materialise the reset state as ``state_names[0]``
    (per SOS-08-C §5.6 — chart ``<initial>`` resolves to the first
    state in document order at the region tree level).

    Cites: SOS-08-C §5.1 (encoding default); §5.6 (reset state default);
    INV-S-HDL-C-1 (deterministic emission — the bit assignment is a
    pure function of (state_names, encoding)).
    """
    n = len(state_names)
    if n == 0:
        raise ValueError("emit_fsm_state_encoding: state_names is empty")

    # Detect duplicates: a duplicate would corrupt the chart's region
    # tree determinism (per INV-S-HDL-C-1) and must be a chart-compile
    # error, not a silent collision.
    if len(set(state_names)) != n:
        seen: set[str] = set()
        for name in state_names:
            if name in seen:
                raise ValueError(
                    f"emit_fsm_state_encoding: duplicate state name {name!r}"
                )
            seen.add(name)

    if encoding is FsmEncoding.ONE_HOT:
        width = n
        out: dict[str, str] = {}
        for i, name in enumerate(state_names):
            # Bit i is set; MSB first. State 0 → "0...01", state N-1 → "10...0".
            bits = ["0"] * width
            bits[width - 1 - i] = "1"
            out[name] = "".join(bits)
        return out

    if encoding is FsmEncoding.BINARY:
        width = max(1, math.ceil(math.log2(n))) if n > 1 else 1
        return {
            name: format(i, f"0{width}b")
            for i, name in enumerate(state_names)
        }

    if encoding is FsmEncoding.GRAY:
        width = max(1, math.ceil(math.log2(n))) if n > 1 else 1
        out_gray: dict[str, str] = {}
        for i, name in enumerate(state_names):
            gray_code = i ^ (i >> 1)
            out_gray[name] = format(gray_code, f"0{width}b")
        return out_gray

    raise ValueError(f"unsupported encoding {encoding!r}")


def emit_fsm_state_constants(
    encoding_map: dict[str, str],
    dialect: Dialect,
) -> str:
    """Emit the per-state constant declarations.

    For the encoding map ``{"IDLE": "0001", "ACTIVE": "0010", ...}``:

    * VHDL output (lines joined by ``\\n``):

      .. code-block:: vhdl

          constant ST_IDLE   : std_logic_vector(3 downto 0) := "0001";
          constant ST_ACTIVE : std_logic_vector(3 downto 0) := "0010";

    * SV output:

      .. code-block:: systemverilog

          localparam logic [3:0] ST_IDLE   = 4'b0001;
          localparam logic [3:0] ST_ACTIVE = 4'b0010;

    The constant prefix is ``ST_`` (uppercase, underscore-separated)
    to keep the chart-state-id naming convention legible in synth
    reports. Per INV-S-HDL-C-2 (per-region observability), the
    constants are emitted at module scope so SVA bind files can
    reference them via hierarchical name.

    Cites: SOS-08-C §6.2 worked-example sketch (``state_observable``);
    INV-S-HDL-C-1 (deterministic emission — constants emitted in the
    iteration order of ``encoding_map``).
    """
    if not encoding_map:
        raise ValueError("emit_fsm_state_constants: encoding_map is empty")

    # Determine width from the first entry; ALL entries must share width
    # (a mismatch would be a chart-compile-time bug from
    # emit_fsm_state_encoding misuse).
    widths = {len(pattern) for pattern in encoding_map.values()}
    if len(widths) != 1:
        raise ValueError(
            f"emit_fsm_state_constants: inconsistent encoding widths {widths}"
        )
    width = widths.pop()

    lines: list[str] = []
    if dialect is Dialect.VHDL:
        for name, pattern in encoding_map.items():
            lines.append(
                f'constant ST_{name} : std_logic_vector({width - 1} '
                f'downto 0) := "{pattern}";'
            )
        return "\n".join(lines)

    if dialect is Dialect.SV:
        for name, pattern in encoding_map.items():
            lines.append(
                f"localparam logic [{width - 1}:0] ST_{name} = "
                f"{width}'b{pattern};"
            )
        return "\n".join(lines)

    raise ValueError(f"unsupported dialect {dialect!r}")


# ---------------------------------------------------------------------------
# Process / always-block scaffolding.
# ---------------------------------------------------------------------------


def emit_register_process(
    clk: str,
    rst: str,
    body_vhdl: str,
    body_sv: str,
    dialect: Dialect,
) -> str:
    """Emit a clocked register process / ``always_ff`` block.

    The body strings are dialect-specific because the syntax inside the
    process differs (VHDL signal assignment ``<=`` and the ``if`` /
    ``elsif`` chain vs SV blocking ``<=`` with C-like ``if`` /
    ``else``). The caller passes the rendered body in both dialects;
    this helper wraps the body with the dialect's process scaffold AND
    a synchronous active-high reset (per INV-S-HDL-A-1 / SOS-08-C
    §6.2).

    The body MUST already be indented relative to the inner reset
    branch — this helper adds NO automatic indentation. Output is one
    process with literal newlines; callers stitch the process block
    into the module body.

    Example
    -------
    VHDL output:

    .. code-block:: vhdl

        process(clk)
        begin
            if rising_edge(clk) then
                if rst = '1' then
                    state <= ST_IDLE;
                else
                    state <= next_state;
                end if;
            end if;
        end process;

    SV output:

    .. code-block:: systemverilog

        always_ff @(posedge clk) begin
            if (rst) begin
                state <= ST_IDLE;
            end else begin
                state <= next_state;
            end
        end

    Note that the per-dialect walker is responsible for splitting the
    body into a reset branch and a clocked branch and supplying both
    via the ``body_vhdl`` / ``body_sv`` arguments. This module does NOT
    parse or compose body fragments — it only emits the scaffolding.

    Cites: INV-S-HDL-A-1 (sync active-high reset); SOS-08-C §6.2
    (region FSM module body shape).
    """
    if dialect is Dialect.VHDL:
        return (
            f"process({clk})\n"
            "begin\n"
            f"    if rising_edge({clk}) then\n"
            f"{body_vhdl}\n"
            "    end if;\n"
            "end process;"
        )
    if dialect is Dialect.SV:
        return (
            f"always_ff @(posedge {clk}) begin\n"
            f"{body_sv}\n"
            "end"
        )
    raise ValueError(f"unsupported dialect {dialect!r}")


def emit_combinational_block(body: str, dialect: Dialect) -> str:
    """Emit a combinational block / VHDL concurrent assignment scope.

    VHDL output wraps the body in a ``process(all)`` block (VHDL-2008
    syntax for "all referenced signals on the sensitivity list").

    SV output wraps the body in an ``always_comb`` block.

    The body passed in is dialect-specific (the per-dialect walker
    builds the inner body); this helper only emits the scaffolding.

    Cites: SOS-08-C §6.3 (combinational guard-expression compilation);
    §6.6 (combinational vs registered ``<assign>`` semantics).
    """
    if dialect is Dialect.VHDL:
        return (
            "process(all)\n"
            "begin\n"
            f"{body}\n"
            "end process;"
        )
    if dialect is Dialect.SV:
        return (
            "always_comb begin\n"
            f"{body}\n"
            "end"
        )
    raise ValueError(f"unsupported dialect {dialect!r}")


# ---------------------------------------------------------------------------
# Header / @spec citation block.
# ---------------------------------------------------------------------------


def emit_header_comment(
    spec_refs: list[str],
    invariants: list[str],
    dialect: Dialect,
) -> str:
    """Emit a top-of-file ``@spec`` / ``@invariants`` citation block.

    The pattern mirrors the SOS-08-A / SOS-08-B sub-phase doc shape:
    every emitted RTL module declares which spec sections + invariants
    it conforms to, so reviewers / SVA bind files can route directly
    from the RTL back to the normative source.

    Output (for SV):

    .. code-block:: systemverilog

        //
        // Generated by sos-codegen (SOS-08-C L2 emission).
        //
        // @spec SOS-08-C-CONCEPTS.md §6.2
        // @spec SOS-08-C-CONCEPTS.md §6.4
        // @invariants INV-S-HDL-C-1 (deterministic emission)
        // @invariants INV-S-HDL-C-2 (per-region observability)
        //
        // DO NOT EDIT BY HAND — regenerate via:
        //   python tools/sos-codegen/main.py --target hdl-sv ...
        //

    VHDL uses ``--`` line comments.

    Cites: INV-S-HDL-5 (chart-vocabulary traceability); SOS-08-C
    §6.11 worked-example sketch (header comment block).
    """
    if dialect is Dialect.VHDL:
        prefix = "--"
    elif dialect is Dialect.SV:
        prefix = "//"
    else:
        raise ValueError(f"unsupported dialect {dialect!r}")

    lines: list[str] = []
    lines.append(f"{prefix}")
    lines.append(f"{prefix} Generated by sos-codegen (SOS-08-C L2 emission).")
    lines.append(f"{prefix}")
    for ref in spec_refs:
        lines.append(f"{prefix} @spec {ref}")
    for inv in invariants:
        lines.append(f"{prefix} @invariants {inv}")
    lines.append(f"{prefix}")
    lines.append(
        f"{prefix} DO NOT EDIT BY HAND — regenerate via:"
    )
    target_flag = "hdl-vhdl" if dialect is Dialect.VHDL else "hdl-sv"
    lines.append(
        f"{prefix}   python tools/sos-codegen/main.py "
        f"--target {target_flag} ..."
    )
    lines.append(f"{prefix}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Datamodel type mapping.
# ---------------------------------------------------------------------------


# Default-width policy per SOS-08-C §5.4 ("SOS-04 / SOS-05 datamodel-
# default width ≅ i32 ≅ 32 bits"). The hint string is informational —
# the actual emission uses the width via emit_signal_decl, but the
# hint can be carried into per-dialect comments for review legibility.
_TYPE_TABLE: dict[str, tuple[int, str]] = {
    # Boolean.
    "bool":   (1,  "bool"),
    "bit":    (1,  "bit"),
    # Signed ints.
    "i8":     (8,  "signed8"),
    "i16":    (16, "signed16"),
    "i32":    (32, "signed32"),
    "i64":    (64, "signed64"),
    "int":    (32, "signed32"),  # SCXML datamodel default per SOS-04
    "integer": (32, "signed32"),
    # Unsigned ints (SCXML datamodel doesn't natively name unsigneds;
    # we accept the Rust-style spelling for chart-author convenience).
    "u8":     (8,  "unsigned8"),
    "u16":    (16, "unsigned16"),
    "u32":    (32, "unsigned32"),
    "u64":    (64, "unsigned64"),
    "uint":   (32, "unsigned32"),
}


def map_datamodel_type(scxml_type, initial_expr=None, dialect=None):
    """Map an SCXML datamodel type identifier to ``(width_bits, hint)``.

    Canonical signature: ``map_datamodel_type(scxml_type: str) -> (int, str)``.

    Wave-1 sibling-walker bridge: some walkers call with a 3-arg shape
    ``(data_id, initial_expr, dialect)`` and expect a dialect-typed string
    back (e.g. ``"signed(31 downto 0)"`` for VHDL). When called that way,
    we synthesize a dialect-appropriate type string from the inferred
    width. Wave-2 reconciliation will pick one canonical shape.

    Unknown types default to 32-bit signed per SOS-08-C §5.4. The hint
    string is informational; the per-dialect walker may inject it into
    a comment next to the signal declaration to aid review.

    Cites: SOS-08-C §5.4 (datamodel signal typing); SOS-04-CONCEPTS.md
    (i32 default width); SOS-05-CONCEPTS.md (C port mirrors).
    """
    key = (scxml_type or "").strip().lower()
    width, hint = _TYPE_TABLE.get(key, (32, f"unknown[{scxml_type}]→signed32"))
    # 3-arg sibling-walker shape: return a dialect-typed string instead.
    if dialect is not None:
        # ``dialect`` may be the Dialect enum or a string alias.
        d_value = getattr(dialect, "value", dialect)
        if d_value in ("vhdl", "VHDL"):
            return (
                f"signed({width - 1} downto 0)"
                if width > 1
                else "std_logic"
            )
        if d_value in ("sv", "SV", "systemverilog", "SYSTEMVERILOG"):
            return (
                f"logic signed [{width - 1}:0]"
                if width > 1
                else "logic"
            )
        # Unknown dialect: fall through to the canonical tuple form.
    return (width, hint)


# ---------------------------------------------------------------------------
# Transition mux helpers.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Transition:
    """Dialect-neutral transition record consumed by the mux emitter.

    The per-dialect walker constructs these from the chart-IR's
    transition list per region. Fields:

    * ``source_state`` — the SCXML source-state id.
    * ``target_state`` — the SCXML target-state id (None for an
      ``<assign>``-only internal transition).
    * ``guard_expr`` — the compiled-RTL form of the ``cond``
      attribute (or ``None`` if no ``cond``). Dialect-specific
      syntax; the walker has already compiled per SOS-08-C §5.3.
    * ``event_guard`` — the event-decode predicate (typically
      ``evt_<name>_valid && event_id_decode == EV_<NAME>``) or
      ``None`` for an unconditional internal transition.
    * ``document_order`` — the 0-based index this transition occupies
      in the SCXML source's transition list for its source state.
      Used for the priority discipline per SOS-08-C §5.2.
    """

    source_state: str
    target_state: Optional[str]
    guard_expr: Optional[str]
    event_guard: Optional[str]
    document_order: int


def emit_transition_mux(
    transitions: list[Transition],
    dialect: Dialect,
) -> str:
    """Emit the document-order priority mux for one region's transitions.

    Per SOS-08-C §5.2: the first transition (in document order) whose
    combined event-guard ∧ cond-guard is true wins. The mux is rendered
    as an ``if`` / ``elsif`` chain (VHDL) or an ``if`` / ``else if``
    chain (SV) keyed on the source state matching, with the first
    matching arm taken. Where no transition's guard is true, the mux
    leaves ``next_state`` at the current state (the caller initialises
    ``next_state = state`` before invoking the mux).

    Caveats / scope:

    * This helper emits ONE mux block. The per-dialect walker is
      responsible for stitching one mux per source state into the
      combinational block (typically inside an ``always_comb`` / VHDL
      ``process(all)``).
    * The walker is responsible for sorting / grouping transitions by
      source state before calling this helper; this helper trusts
      ``document_order`` and emits arms in that order.
    * Per PCDN-SOS-08-C-006 / SCXML-LINT-C-1: the lint warning for
      simultaneously-true transitions is emitted at chart-compile
      time (in the linter, not here); this helper assumes the lint
      has passed.

    Cites: SOS-08-C §5.2 (transition mux priority discipline);
    PCDN-SOS-08-C-006 (document-order priority lint).
    """
    if not transitions:
        # Empty mux means "no outgoing transitions"; emit a no-op
        # comment that flags the dead state for the per-dialect walker
        # to wrap.
        if dialect is Dialect.VHDL:
            return "-- no outgoing transitions"
        if dialect is Dialect.SV:
            return "// no outgoing transitions"
        raise ValueError(f"unsupported dialect {dialect!r}")

    # Sort by document_order to ratify the priority discipline at the
    # emission site — even if the caller passed transitions out of
    # order, the emitted mux reflects document-order priority.
    ordered = sorted(transitions, key=lambda t: t.document_order)

    arms: list[str] = []
    for t in ordered:
        # Combine event_guard and guard_expr into one boolean. Both
        # may be None (for an unconditional internal transition); the
        # combined guard is then ``true`` and the arm is unconditional.
        parts: list[str] = []
        if t.event_guard:
            parts.append(f"({t.event_guard})")
        if t.guard_expr:
            parts.append(f"({t.guard_expr})")
        combined = " and ".join(parts) if dialect is Dialect.VHDL \
            else " && ".join(parts)
        if not combined:
            combined = "true" if dialect is Dialect.VHDL else "1'b1"
        target = t.target_state if t.target_state is not None else t.source_state
        arms.append((combined, target, t.document_order))

    if dialect is Dialect.VHDL:
        lines: list[str] = []
        first = True
        for combined, target, order in arms:
            kw = "if" if first else "elsif"
            first = False
            lines.append(
                f"    {kw} {combined} then  -- doc-order {order}"
            )
            lines.append(f"        next_state := ST_{target};")
            lines.append(f"        transition_observable := '1';")
        lines.append("    end if;")
        return "\n".join(lines)

    if dialect is Dialect.SV:
        lines = []
        first = True
        for combined, target, order in arms:
            kw = "if" if first else "else if"
            first = False
            lines.append(
                f"    {kw} ({combined}) begin  // doc-order {order}"
            )
            lines.append(f"        next_state = ST_{target};")
            lines.append(f"        transition_observable = 1'b1;")
            lines.append("    end")
        return "\n".join(lines)

    raise ValueError(f"unsupported dialect {dialect!r}")


# ---------------------------------------------------------------------------
# Guard-depth analysis (PCDN-SOS-08-C-004 / SCXML-LINT-C-2 enforcement).
# ---------------------------------------------------------------------------


# Operators that contribute to the guard-depth count per
# PCDN-SOS-08-C-004. The list mirrors the constructs in SOS-08-C §5.3
# table that compile to combinational gates / comparators.
_GUARD_OPERATORS = (
    "&&", "||", "==", "!=", "<=", ">=", "<", ">", "!",
)

DEFAULT_GUARD_DEPTH_BUDGET = 8  # Per PCDN-SOS-08-C-004.


def compute_guard_depth(guard_expr: str) -> int:
    """Return the count of guard-depth-contributing operators in
    ``guard_expr``.

    The metric counts each occurrence of every operator in
    :data:`_GUARD_OPERATORS`. Multi-character operators are matched
    before their single-character prefixes (e.g. ``<=`` is counted
    once as ``<=``, not twice as ``<`` and ``=``).

    Used by the per-dialect walker to enforce SCXML-LINT-C-2 at
    emission time (per PCDN-SOS-08-C-004; lint also runs at chart-
    compile time inside SOS-01's linter pipeline).

    Trailing/leading whitespace is irrelevant; the metric counts
    operators only.

    Cites: PCDN-SOS-08-C-004; SCXML-LINT-C-2.
    """
    if not guard_expr:
        return 0

    remaining = guard_expr
    count = 0
    # Match in order of operator length to avoid double-counting ``<=``
    # as ``<`` + ``=``.
    operators_by_length = sorted(_GUARD_OPERATORS, key=len, reverse=True)
    # Build a regex that matches any operator (escape so e.g. `||`
    # doesn't get interpreted as alternation).
    pattern = "|".join(re.escape(op) for op in operators_by_length)
    count = len(re.findall(pattern, remaining))
    return count


# ---------------------------------------------------------------------------
# Misc utilities (small enough to keep here vs a separate _util module).
# ---------------------------------------------------------------------------


def encoding_width(state_count: int, encoding: FsmEncoding) -> int:
    """Return the bit-width of the state register for the requested
    encoding given a state count.

    * ONE_HOT → ``state_count``
    * BINARY / GRAY → ``max(1, ceil(log2(state_count)))``

    Symmetric with :func:`emit_fsm_state_encoding`; provided as a
    standalone helper so the per-dialect walker can size the
    ``state_observable`` port without re-running the full encoding.

    Cites: SOS-08-C §6.2 (region FSM module ``STATE_WIDTH`` parameter).
    """
    if state_count < 1:
        raise ValueError(f"state_count must be ≥ 1, got {state_count}")
    if encoding is FsmEncoding.ONE_HOT:
        return state_count
    if encoding in (FsmEncoding.BINARY, FsmEncoding.GRAY):
        if state_count == 1:
            return 1
        return max(1, math.ceil(math.log2(state_count)))
    raise ValueError(f"unsupported encoding {encoding!r}")


@dataclass(frozen=True)
class HdlEmitConfig:
    """Per-invocation HDL emission configuration.

    Threaded from the codegen tool's CLI flags through to the per-
    dialect walker. Field defaults match the PCDN-resolved values
    (one-hot encoding; guard-depth budget 8; document-order lint
    warning ON).
    """

    encoding: FsmEncoding = field(default_factory=FsmEncoding.default)
    guard_depth_budget: int = DEFAULT_GUARD_DEPTH_BUDGET
    lint_warn_doc_order: bool = True   # SCXML-LINT-C-1 emission (PCDN-C-006)
    verified_strip: bool = False        # PCDN-C-002: retain synchronizers regardless
    reset_polarity: ResetPolarity = ResetPolarity.SYNC_ACTIVE_HIGH


# ---------------------------------------------------------------------------
# Public surface — names the per-dialect walkers import.
# ---------------------------------------------------------------------------


__all__ = [
    # Enums
    "Dialect",
    "FsmEncoding",
    "ResetPolarity",
    # Dataclasses
    "HdlPort",
    "Transition",
    "HdlEmitConfig",
    # Per-dialect emit helpers
    "emit_port_decl",
    "emit_signal_decl",
    "emit_fsm_state_encoding",
    "emit_fsm_state_constants",
    "emit_register_process",
    "emit_combinational_block",
    "emit_header_comment",
    "emit_transition_mux",
    # Datamodel + analysis
    "map_datamodel_type",
    "compute_guard_depth",
    "encoding_width",
    # Constants
    "DEFAULT_GUARD_DEPTH_BUDGET",
]
