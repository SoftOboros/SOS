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
      dialect-neutral surface called from steps 2, 3, 4, 5, 6, 7, 9, 10;
      §7 INV-S-HDL-C-1..5 (deterministic emission; per-region
      observability; cross-domain transition enforcement; guard
      synthesizability; cooperative completion);
      §15 ratification entry (2026-05-23) — PCDN-SOS-08-C-001..006
      resolutions; wave-2 reconciliation pins canonical helper
      signatures + adds the guard / parallel / chart-top / synchronizer
      surface.
  - ``docs/concepts/SOS-08-A-CONCEPTS.md`` §6 — L0 primitive contracts
    this layer instantiates via SOS-08-B services. Per §5.1 / INV-S-
    HDL-A-1 reset is synchronous active-high; this module mirrors
    that for chart-emitted region FSMs (INV-S-HDL-A-1 → INV-S-HDL-C
    by composition). §6.9 owns the ``sos_synchronizer`` primitive
    (`STAGES` mandatory no-default per §15 wave-2 amendment; ports
    `clk_dst`, `rst_dst`, `d_src`, `d_dst`) instantiated by
    :func:`emit_sync_inst`.
  - ``docs/concepts/SOS-08-B-CONCEPTS.md`` §6 — L1 service contracts
    for event ingress/egress.
  - ``docs/concepts/SOS-01-CONCEPTS.md`` §5.1 — ECMAScript subset
    that guard expressions compile from; :func:`emit_guard_expr` is
    the dialect-neutral lowering point.

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
  - **INV-S-HDL-C-3** (cross-domain transition enforcement) — enforced
    at the chart-top wrapper emit step by :func:`emit_chart_top_wrapper`,
    which instantiates one :func:`emit_sync_inst` per cross-domain edge
    declared in the ``cross_domain_signals`` argument. Per PCDN-C-002
    resolution (SOS-08-C §15) the synchronizer is retained regardless
    of ``--verified-strip`` reachability.
  - **INV-S-HDL-C-4** (guard expression synthesizability) — partially
    enforced here via :func:`compute_guard_depth` against the default
    budget; :func:`emit_guard_expr` is the defense-in-depth emit-time
    gate that raises :class:`GuardDepthError` if the configured budget
    is exceeded. SCXML-LINT-C-2 SHOULD have caught the over-depth case
    at chart-compile time per PCDN-SOS-08-C-004.
  - **INV-S-HDL-C-5** (cooperative completion) — no preemption /
    save-restore registers are emitted by anything in this module;
    callers MUST honour that by construction.

PCDN resolutions (SOS-08-C §15, 2026-05-23) consulted:
  - PCDN-C-001 (clock-domain default = inherit-from-parent;
    :func:`emit_chart_top_wrapper` honours this by deduplicating
    clock-input ports across regions sharing a domain).
  - PCDN-C-002 (verified-strip × multi-clock = retain synchronizers;
    :func:`emit_sync_inst` is unconditionally emitted from
    :func:`emit_chart_top_wrapper`).
  - PCDN-C-003 (reset-state default = SCXML ``<initial>`` w/ optional
    ``<reset state="..."/>`` override).
  - PCDN-C-004 (guard-depth budget default = 8 chained operators;
    enforced via SCXML-LINT-C-2 at chart-compile time AND
    :func:`emit_guard_expr` at emit time).
  - PCDN-C-005 (chart annotation wins for state encoding; ``--target``
    is a hint only for unannotated regions).
  - PCDN-C-006 (document-order priority lint warning; SCXML-LINT-C-1).

This module is dialect-neutral substrate; it does NOT crawl SCXML, does
NOT touch templates, and does NOT shell out. The chart-IR transit is
the per-dialect walker's responsibility.

Wave-2 reconciliation (2026-05-23):
  - ``HdlPort`` fields ratified canonical (no bridge / canonical split).
    ``width: int`` is canonical; ``width_expr: Optional[str]`` is the
    symbolic-expression escape hatch (e.g. ``"N_STATES-1 downto 0"``).
  - ``ResetPolarity.SYNC_ACTIVE_HIGH`` is canonical; ``ACTIVE_HIGH_SYNC``
    retained as a deprecated alias for in-flight wave-1 call sites
    (VHDL walker `transliterate_hdl_vhdl.py:603`).
  - ``map_datamodel_type`` canonical 3-arg shape returns a dialect-typed
    string. The 1-arg form is RETAINED for backward compatibility (emits
    a ``DeprecationWarning``) and returns the historical
    ``(width, hint)`` tuple. ``datamodel_width`` is the sibling helper
    for callers that want just the integer width.
  - ``emit_signal_decl`` canonical signature takes a pre-rendered
    ``signal_type: str``; ``emit_signal_decl_int`` is the sibling helper
    for callers that pass an integer ``width``.
  - New helpers landed: :class:`GuardDepthError`, :func:`emit_guard_expr`,
    :func:`emit_sync_inst`, :func:`emit_chart_top_wrapper`,
    :func:`port_width_from_signal_width`, :func:`datamodel_width`,
    :func:`emit_signal_decl_int`.
"""

from __future__ import annotations

import ast
import math
import re
import warnings
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Optional, Union


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

    Wave-2 reconciliation: ``SYNC_ACTIVE_HIGH`` is the canonical name.
    ``ACTIVE_HIGH_SYNC`` is retained as a deprecated alias for in-flight
    wave-1 call sites (notably ``transliterate_hdl_vhdl.py:603``); new
    code SHOULD use ``SYNC_ACTIVE_HIGH``.

    Registration policy: **Standards Action** (changing this requires
    a coordinated §15 amendment in SOS-08-A AND SOS-08-C; downstream
    L0 primitives all assume this convention).
    """

    SYNC_ACTIVE_HIGH = "sync_active_high"

    @classmethod
    def _missing_(cls, value):
        # Accept the sibling-walker spelling `active_high_sync` as an alias
        # for the canonical `sync_active_high`. Deprecated; wave-3 will
        # remove once walkers migrate.
        if value == "active_high_sync":
            return cls.SYNC_ACTIVE_HIGH
        return None


# Deprecated alias for the sibling-walker spelling (wave-1 drift).
# Marked for removal once the VHDL walker migrates to `SYNC_ACTIVE_HIGH`.
ResetPolarity.ACTIVE_HIGH_SYNC = ResetPolarity.SYNC_ACTIVE_HIGH  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Port / signal abstractions.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HdlPort:
    """Dialect-neutral abstract port representation.

    Wave-2 canonical surface (all fields are canonical; no canonical /
    bridge split):

    * ``name`` — port identifier (must be a valid VHDL + SV identifier).
    * ``direction`` — one of ``"in"`` / ``"out"`` / ``"inout"``.
    * ``width`` — integer bit-width. ``1`` → scalar (``std_logic`` /
      ``wire``); ``>1`` → vector. The canonical width source when known.
    * ``dialect_hint`` — optional dialect-specific type override. ``None``
      means "let :func:`emit_port_decl` choose the default rendering for
      the requested dialect from ``width``".
    * ``width_expr`` — optional symbolic-width expression
      (e.g. ``"N_STATES-1 downto 0"``, ``"std_logic_vector(7 downto 0)"``).
      Used when the width is a generic/parameter expression that cannot
      be reduced to an integer at emit time. Walkers prefer integer
      ``width`` when it is known; fall back to ``width_expr`` when
      symbolic. When both are set, ``width_expr`` wins (it is the more
      specific / pre-rendered form, typically inherited from
      :func:`map_datamodel_type`'s 3-arg shape output).
    * ``kind`` — optional dialect-extension type hint (e.g. ``"signed"`` /
      ``"unsigned"`` / ``"logic"``). Informational; the per-dialect
      walker MAY consume it to refine rendering.
    * ``signed`` — flag for signed integer interpretation. Informational
      (the dialect-rendering helper does NOT currently switch on it; the
      ``kind`` / ``dialect_hint`` channel is the authoritative path).
    * ``comment`` — optional trailing comment (rendered as ``--`` /
      ``//`` per dialect).

    Cites: SOS-08-C §6.2 (region FSM module port list); SOS-08-A §5.1
    (handshake-port shape ratification); §15 wave-2 reconciliation entry.
    """

    name: str
    direction: Literal["in", "out", "inout"]
    width: int = 1  # in bits; 1 → scalar (std_logic / wire), >1 → vector
    dialect_hint: Optional[str] = None
    width_expr: Optional[str] = None
    kind: Optional[str] = None
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

    Resolution order for the rendered type form:

    1. ``port.width_expr`` (pre-rendered symbolic) — wins when set; the
       caller already knows the dialect-typed string.
    2. ``port.dialect_hint`` (pre-rendered dialect-typed string).
    3. Auto-render from ``port.width``: scalar (``std_logic`` / ``wire``)
       for width 1; vector (``std_logic_vector(W-1 downto 0)`` /
       ``wire [W-1:0]``) for width > 1.

    Wave-2: the width>1 auto-render path is now correct; the wave-1
    shape always emitted scalar form regardless of width.

    Examples
    --------
    ``HdlPort("rst", "in", 1)`` →

      * VHDL: ``rst : in std_logic``
      * SV:   ``input wire rst``

    ``HdlPort("evt_payload", "in", 64)`` →

      * VHDL: ``evt_payload : in std_logic_vector(63 downto 0)``
      * SV:   ``input wire [63:0] evt_payload``

    ``HdlPort("state", "out", width_expr="std_logic_vector(3 downto 0)")``
    (VHDL) → ``state : out std_logic_vector(3 downto 0)``.

    Cites: SOS-08-C §6.2 (region FSM module port list); SOS-08-A §5.1
    (handshake-port shape ratification); §15 wave-2 reconciliation.
    """
    if port.width < 1:
        raise ValueError(f"port {port.name!r} has invalid width {port.width}")

    if dialect is Dialect.VHDL:
        direction = _vhdl_direction(port.direction)
        if port.width_expr is not None:
            type_form = port.width_expr
        elif port.dialect_hint is not None:
            type_form = port.dialect_hint
        elif port.width == 1:
            type_form = "std_logic"
        else:
            type_form = f"std_logic_vector({port.width - 1} downto 0)"
        return f"{port.name} : {direction} {type_form}"

    if dialect is Dialect.SV:
        direction = _sv_direction(port.direction)
        if port.width_expr is not None:
            # The SV wave-1 convention places the symbolic width between
            # `wire` and the port name (e.g. `wire [N-1:0]`). Callers MAY
            # also pass a fully-rendered type string in `dialect_hint`.
            return f"{direction} wire {port.width_expr} {port.name}"
        if port.dialect_hint is not None:
            type_form = port.dialect_hint
            if port.width == 1:
                return f"{direction} {type_form} {port.name}"
            return f"{direction} {type_form} [{port.width - 1}:0] {port.name}"
        if port.width == 1:
            return f"{direction} wire {port.name}"
        return f"{direction} wire [{port.width - 1}:0] {port.name}"

    raise ValueError(f"unsupported dialect {dialect!r}")


def emit_signal_decl(
    name: str,
    signal_type: Optional[str] = None,
    dialect: Dialect = Dialect.VHDL,
    *,
    comment: Optional[str] = None,
    # ---- deprecated/legacy keyword channels retained for wave-1 callers ----
    width: Optional[int] = None,
    registered: bool = False,
    kind: Optional[str] = None,
    signed: bool = False,
) -> str:
    """Emit an internal signal declaration (wave-2 canonical signature).

    Wave-2 canonical signature::

        emit_signal_decl(name, signal_type, dialect, *, comment=None)

    Where ``signal_type`` is a pre-rendered dialect-typed string
    (e.g. ``"std_logic"``, ``"std_logic_vector(31 downto 0)"`` for VHDL;
    ``"logic"``, ``"logic [31:0]"`` for SV). The integer-width form
    lives in :func:`emit_signal_decl_int`.

    Wave-1 backward-compat shim: if ``signal_type`` is ``None`` and
    ``width`` is passed (kw or positional), the call is silently
    rewritten as ``emit_signal_decl_int(name, width, dialect,
    registered=registered)`` with a :class:`DeprecationWarning`. This
    keeps in-flight sibling walkers compiling until they migrate.

    Examples
    --------
    VHDL: ``signal state : std_logic_vector(3 downto 0);``
    SV:   ``logic [3:0] state;``

    Cites: SOS-08-C §5.4 (datamodel signal typing: registered iff
    written by ``<assign>``); §15 wave-2 reconciliation.
    """
    # Wave-1 shim: caller passed an integer width via the positional
    # second arg OR the `width=` kwarg. Detect and route through the
    # integer helper.
    if signal_type is None or isinstance(signal_type, int):
        # `signal_type` was the int (positional wave-1 form
        # `emit_signal_decl(name, width, dialect, registered)`).
        if isinstance(signal_type, int):
            effective_width = signal_type
        elif width is not None:
            effective_width = width
        else:
            effective_width = 1
        warnings.warn(
            "emit_signal_decl(name, width, ...) is deprecated; pass a "
            "pre-rendered `signal_type` string or call "
            "emit_signal_decl_int(name, width, dialect, registered=...) "
            "explicitly.",
            DeprecationWarning,
            stacklevel=2,
        )
        return emit_signal_decl_int(
            name,
            int(effective_width),
            dialect,
            registered=registered,
            comment=comment,
        )

    if not isinstance(signal_type, str):
        raise TypeError(
            f"emit_signal_decl: signal_type must be a str (dialect-rendered "
            f"type form); got {type(signal_type).__name__}"
        )

    trailing = ""
    if comment:
        trailing = f"  -- {comment}" if dialect is Dialect.VHDL else f"  // {comment}"

    if dialect is Dialect.VHDL:
        return f"signal {name} : {signal_type};{trailing}"
    if dialect is Dialect.SV:
        # If the caller already pre-rendered the storage class (`logic` /
        # `bit` / `reg`) into `signal_type`, don't re-prefix it. Otherwise
        # default to `logic`.
        stripped = signal_type.lstrip()
        if stripped.startswith(("logic", "bit", "reg")):
            return f"{signal_type} {name};{trailing}"
        return f"logic {signal_type} {name};{trailing}"
    raise ValueError(f"unsupported dialect {dialect!r}")


def emit_signal_decl_int(
    name: str,
    width: int,
    dialect: Dialect,
    *,
    registered: bool = False,
    comment: Optional[str] = None,
) -> str:
    """Emit an internal signal declaration from an integer ``width``.

    Sibling to :func:`emit_signal_decl` for callers that have not
    pre-rendered the dialect type string. Wave-2 helper.

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
        suffix_bits: list[str] = []
        if comment:
            suffix_bits.append(comment)
        suffix_bits.append("registered" if registered else "combinational")
        suffix = "  -- " + "; ".join(suffix_bits)
        return f"signal {name} : {type_form};{suffix}"
    if dialect is Dialect.SV:
        intent = "registered" if registered else "combinational"
        comment_bits = f"{comment}; {intent}" if comment else intent
        if width == 1:
            return f"logic {name};  // {comment_bits}"
        return f"logic [{width - 1}:0] {name};  // {comment_bits}"
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


def _lookup_type(scxml_type: Optional[str]) -> tuple[int, str]:
    """Internal: resolve ``(width, hint)`` from a chart datamodel type
    identifier, defaulting to signed-32 per SOS-08-C §5.4."""
    key = (scxml_type or "").strip().lower()
    return _TYPE_TABLE.get(key, (32, f"unknown[{scxml_type}]→signed32"))


def datamodel_width(scxml_type: Optional[str]) -> int:
    """Return the bit-width for an SCXML datamodel type identifier.

    Wave-2 helper: wraps :data:`_TYPE_TABLE` so callers that just need
    the integer width (e.g. for ``HdlPort.width`` or a register length)
    can avoid the dialect-string rendering done by
    :func:`map_datamodel_type`.

    Unknown types default to 32 bits (signed) per SOS-08-C §5.4 and
    INV-S-HDL-C-4 (the budget metric depends on a fixed default).

    Cites: SOS-08-C §5.4; SOS-04 / SOS-05 default width.
    """
    width, _hint = _lookup_type(scxml_type)
    return width


def port_width_from_signal_width(scxml_type: Optional[str], name: str) -> int:
    """Return the appropriate ``HdlPort.width`` for a chart datamodel
    declaration named ``name`` of type ``scxml_type``.

    Wave-2 helper (mirror of :func:`datamodel_width` with a chart-
    author-friendly signature that names the datamodel id; the ``name``
    is currently informational — preserved in the signature so a future
    wave can specialise width for named annotations like
    ``<data id="x" width="8"/>`` without changing the call site).

    Cites: SOS-08-C §5.4; §6.2 (region FSM datamodel port shape).
    """
    if not isinstance(name, str) or not name:
        raise ValueError("port_width_from_signal_width: name must be non-empty str")
    return datamodel_width(scxml_type)


def map_datamodel_type(
    scxml_type: str,
    initial_expr: Optional[str] = None,
    dialect: Optional[Union[Dialect, str]] = None,
):
    """Map an SCXML datamodel type identifier to a dialect-typed string.

    Wave-2 canonical signature (3-arg)::

        map_datamodel_type(scxml_type: str,
                           initial_expr: Optional[str],
                           dialect: Dialect) -> str

    Returns a pre-rendered dialect type form suitable for
    :class:`HdlPort` ``width_expr`` / :func:`emit_signal_decl`
    ``signal_type``:

      * VHDL: ``"std_logic"`` (1-bit) or ``"signed(W-1 downto 0)"``.
      * SV:   ``"logic"`` (1-bit) or ``"logic signed [W-1:0]"``.

    ``initial_expr`` is currently informational (preserved for symmetry
    with the C / Rust transliterators which use it to widen the inferred
    type beyond the chart's declared one). The L2 emitter trusts the
    chart's declared type.

    Backward-compat (wave-1 1-arg shape)::

        map_datamodel_type(scxml_type) -> (width_bits, hint)

    Calls without ``dialect`` return the historical ``(width, hint)``
    tuple AND emit a :class:`DeprecationWarning`. New code SHOULD call
    :func:`datamodel_width` for just the integer width, or pass an
    explicit ``dialect`` for the rendered-type form.

    Unknown types default to 32-bit signed per SOS-08-C §5.4.

    Cites: SOS-08-C §5.4 (datamodel signal typing); SOS-04-CONCEPTS.md
    (i32 default width); SOS-05-CONCEPTS.md (C port mirrors);
    §15 wave-2 reconciliation.
    """
    width, hint = _lookup_type(scxml_type)
    if dialect is None:
        warnings.warn(
            "map_datamodel_type(scxml_type) 1-arg form is deprecated; "
            "call with (scxml_type, initial_expr, dialect) to receive a "
            "dialect-typed string, or call datamodel_width(scxml_type) "
            "for just the integer width.",
            DeprecationWarning,
            stacklevel=2,
        )
        return (width, hint)

    d_value = getattr(dialect, "value", dialect)
    if d_value in ("vhdl", "VHDL"):
        if width == 1:
            return "std_logic"
        return f"signed({width - 1} downto 0)"
    if d_value in ("sv", "SV", "systemverilog", "SYSTEMVERILOG"):
        if width == 1:
            return "logic"
        return f"logic signed [{width - 1}:0]"
    raise ValueError(f"map_datamodel_type: unsupported dialect {dialect!r}")


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

    arms: list[tuple[str, str, int]] = []
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


class GuardDepthError(ValueError):
    """Raised when a guard expression exceeds the configured depth budget.

    Sibling to ``SCXML-LINT-C-2`` (PCDN-SOS-08-C-004): the lint catches
    over-depth guards at chart-compile time; :class:`GuardDepthError`
    is the defense-in-depth gate at emit time for charts that bypassed
    or pre-date the lint pass.

    The error message is rendered in chart vocabulary per INV-S-HDL-5
    (the failing ``cond`` string + the depth + the budget).
    """

    def __init__(self, expr: str, depth: int, budget: int):
        self.expr = expr
        self.depth = depth
        self.budget = budget
        super().__init__(
            f"guard expression {expr!r} has depth {depth} which exceeds the "
            f"configured budget {budget} (PCDN-SOS-08-C-004; "
            f"SCXML-LINT-C-2 should have rejected this at chart-compile "
            f"time)."
        )


def compute_guard_depth(guard_expr: str) -> int:
    """Return the count of guard-depth-contributing operators in
    ``guard_expr``.

    Convention (matches SCXML-LINT-C-2 sibling): a Python ``BoolOp``
    like ``a and b and c`` contributes ``N-1`` operators to the path
    where N is the number of operands. The metric counts:

    * Each ``BoolOp`` contributes ``len(values) - 1`` (the join count).
    * Each ``Compare`` contributes ``len(ops)`` (the comparator count;
      a chained compare ``a < b < c`` counts 2).
    * Each ``UnaryOp`` (``not`` / ``~`` / unary ``+`` / ``-``) counts 1.
    * Each ``BinOp`` (``+`` / ``-`` / ``*`` / ``&`` / ``|`` / ``^``) counts 1.
    * Function calls (only ``In(...)`` is permitted) count 1.

    Used by the per-dialect walker to enforce SCXML-LINT-C-2 at
    emission time (per PCDN-SOS-08-C-004; lint also runs at chart-
    compile time inside SOS-01's linter pipeline).

    Falls back to a regex over :data:`_GUARD_OPERATORS` (the wave-1
    behaviour) when the input is not parseable as a Python expression
    — useful when callers pass pre-compiled dialect-specific guard
    strings (e.g. ``a && b``) instead of chart-source syntax.

    Trailing/leading whitespace is irrelevant.

    Cites: PCDN-SOS-08-C-004; SCXML-LINT-C-2.
    """
    if not guard_expr:
        return 0

    text = guard_expr.strip()
    if not text:
        return 0

    # Preferred path: parse as a Python expression and walk the AST.
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:
        # Fall through to regex over dialect-specific operator strings.
        operators_by_length = sorted(_GUARD_OPERATORS, key=len, reverse=True)
        pattern = "|".join(re.escape(op) for op in operators_by_length)
        return len(re.findall(pattern, text))

    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.BoolOp):
            count += max(0, len(node.values) - 1)
        elif isinstance(node, ast.Compare):
            count += len(node.ops)
        elif isinstance(node, (ast.UnaryOp, ast.BinOp)):
            count += 1
        elif isinstance(node, ast.Call):
            count += 1
    return count


# ---------------------------------------------------------------------------
# Guard expression compilation (wave-2; SOS-08-C §5.3 + §6.3).
# ---------------------------------------------------------------------------


# Operator translation tables. Indexed by AST node class names so the
# walker can dispatch via `type(node).__name__` — keeps the table data,
# not control flow.
_GUARD_COMPARE_OPS_VHDL: dict[str, str] = {
    "Eq":    "=",
    "NotEq": "/=",
    "Lt":    "<",
    "LtE":   "<=",
    "Gt":    ">",
    "GtE":   ">=",
}
_GUARD_COMPARE_OPS_SV: dict[str, str] = {
    "Eq":    "==",
    "NotEq": "!=",
    "Lt":    "<",
    "LtE":   "<=",
    "Gt":    ">",
    "GtE":   ">=",
}
_GUARD_BOOL_OPS_VHDL: dict[str, str] = {"And": "and", "Or": "or"}
_GUARD_BOOL_OPS_SV:   dict[str, str] = {"And": "&&", "Or": "||"}
_GUARD_UNARY_OPS_VHDL: dict[str, str] = {"Not": "not", "Invert": "not", "USub": "-", "UAdd": "+"}
_GUARD_UNARY_OPS_SV:   dict[str, str] = {"Not": "!",   "Invert": "~",   "USub": "-", "UAdd": "+"}
_GUARD_BINOP_OPS_VHDL: dict[str, str] = {
    "Add": "+", "Sub": "-", "Mult": "*",
    "BitAnd": "and", "BitOr": "or", "BitXor": "xor",
}
_GUARD_BINOP_OPS_SV: dict[str, str] = {
    "Add": "+", "Sub": "-", "Mult": "*",
    "BitAnd": "&", "BitOr": "|", "BitXor": "^",
}


def emit_guard_expr(
    expr_str: str,
    dialect: Dialect,
    *,
    depth_budget: int = DEFAULT_GUARD_DEPTH_BUDGET,
) -> str:
    """Compile an SCXML ``cond`` Python-syntax expression to a dialect-
    specific combinational HDL expression.

    Per SOS-08-C §5.3 + §6.3 + INV-S-HDL-C-4: the supported subset is
    the SOS-01 §5.1 12-feature ECMAScript subset rendered via Python
    syntax (the SCXML `cond` is Python-shape in this project). Wave-2
    surface:

    * Comparisons: ``==``, ``!=``, ``<``, ``<=``, ``>``, ``>=``
      (single-comparator AND chains of comparators per Python's chained
      compare semantics).
    * Boolean ops: ``and``, ``or``, ``not`` (Python keywords).
    * Arithmetic: ``+``, ``-``, ``*``.
    * Bitwise: ``&``, ``|``, ``^``, ``~``.
    * Identifiers: map to ``<name>_q`` signal references (registered
      datamodel signal naming convention per the wave-1 walker).
    * Integer / boolean literals: rendered directly. ``True`` /
      ``False`` in VHDL render as ``true`` / ``false``; in SV as
      ``1'b1`` / ``1'b0``.
    * Parenthesised sub-expressions: preserved.

    Honors :data:`DEFAULT_GUARD_DEPTH_BUDGET` (default 8) per
    PCDN-SOS-08-C-004. Raises :class:`GuardDepthError` if the operator
    count exceeds ``depth_budget`` — defense in depth; SCXML-LINT-C-2
    SHOULD have caught this at lint time.

    Returns a single-line expression (no embedded newlines). The caller
    decides how to parenthesise it within the larger mux arm.

    Cites: SOS-08-C §5.3 (RTL realisation table); §6.3 (compile pass);
    INV-S-HDL-C-4 (synthesizable subset); PCDN-SOS-08-C-004 (depth budget).
    """
    if dialect not in (Dialect.VHDL, Dialect.SV):
        raise ValueError(f"emit_guard_expr: unsupported dialect {dialect!r}")
    if not isinstance(expr_str, str):
        raise TypeError(
            f"emit_guard_expr: expr_str must be str; got {type(expr_str).__name__}"
        )

    expr_clean = expr_str.strip()
    if not expr_clean:
        # Empty guard means "unconditional"; surface as the dialect
        # literal-true so the mux arm renders cleanly.
        return "true" if dialect is Dialect.VHDL else "1'b1"

    depth = compute_guard_depth(expr_clean)
    if depth > depth_budget:
        raise GuardDepthError(expr_clean, depth, depth_budget)

    try:
        tree = ast.parse(expr_clean, mode="eval")
    except SyntaxError as e:
        raise ValueError(
            f"emit_guard_expr: cannot parse guard {expr_clean!r}: {e}"
        ) from e

    return _render_guard_node(tree.body, dialect)


def _render_guard_node(node: ast.AST, dialect: Dialect) -> str:
    """Render one AST node to the dialect's HDL surface. Recursive.

    Closed over the operator-table dicts above. The dispatch is by
    ``type(node)`` rather than a visitor pattern because the surface
    is small (8 node classes) and the registry policy keeps it
    inspectable.
    """
    # ---- Boolean operators (and / or) ----
    if isinstance(node, ast.BoolOp):
        table = _GUARD_BOOL_OPS_VHDL if dialect is Dialect.VHDL else _GUARD_BOOL_OPS_SV
        op_name = type(node.op).__name__
        if op_name not in table:
            raise ValueError(f"emit_guard_expr: unsupported BoolOp {op_name!r}")
        op = table[op_name]
        parts = [_render_guard_node(v, dialect) for v in node.values]
        # Wrap each operand to preserve precedence.
        return f" {op} ".join(f"({p})" for p in parts)

    # ---- Unary operators (not / ~ / unary +/-) ----
    if isinstance(node, ast.UnaryOp):
        table_u = _GUARD_UNARY_OPS_VHDL if dialect is Dialect.VHDL else _GUARD_UNARY_OPS_SV
        op_name = type(node.op).__name__
        if op_name not in table_u:
            raise ValueError(f"emit_guard_expr: unsupported UnaryOp {op_name!r}")
        operand = _render_guard_node(node.operand, dialect)
        op = table_u[op_name]
        # `not` (VHDL) / `!` (SV) needs the parens around its operand.
        return f"{op} ({operand})"

    # ---- Binary operators (arithmetic + bitwise) ----
    if isinstance(node, ast.BinOp):
        table_b = _GUARD_BINOP_OPS_VHDL if dialect is Dialect.VHDL else _GUARD_BINOP_OPS_SV
        op_name = type(node.op).__name__
        if op_name not in table_b:
            raise ValueError(f"emit_guard_expr: unsupported BinOp {op_name!r}")
        left = _render_guard_node(node.left, dialect)
        right = _render_guard_node(node.right, dialect)
        op = table_b[op_name]
        return f"({left} {op} {right})"

    # ---- Compare ops (==, !=, <, <=, >, >=). Python allows chains
    #      like `a < b < c`; we expand into `(a < b) and (b < c)`. ----
    if isinstance(node, ast.Compare):
        table_c = _GUARD_COMPARE_OPS_VHDL if dialect is Dialect.VHDL else _GUARD_COMPARE_OPS_SV
        # Build pairwise comparisons.
        bool_join = "and" if dialect is Dialect.VHDL else "&&"
        operands = [node.left] + list(node.comparators)
        sub_exprs: list[str] = []
        for i, cmp_op in enumerate(node.ops):
            op_name = type(cmp_op).__name__
            if op_name not in table_c:
                raise ValueError(
                    f"emit_guard_expr: unsupported Compare op {op_name!r}"
                )
            lhs = _render_guard_node(operands[i], dialect)
            rhs = _render_guard_node(operands[i + 1], dialect)
            sub_exprs.append(f"({lhs} {table_c[op_name]} {rhs})")
        if len(sub_exprs) == 1:
            return sub_exprs[0]
        return f" {bool_join} ".join(sub_exprs)

    # ---- Identifier ----
    if isinstance(node, ast.Name):
        return f"{node.id}_q"

    # ---- Attribute access (e.g. `_event.data.foo`) — emit a flattened
    # signal name so the walker can recognise the chart-side scope
    # without re-parsing. The chart-compile-time slice is the walker's
    # job; here we render the access as a dotted identifier that the
    # caller MAY normalise. ----
    if isinstance(node, ast.Attribute):
        base = _render_guard_node(node.value, dialect)
        # Strip the auto-suffixed `_q` from `Name` rendering when
        # composing attributes — `_event.data.foo` should render as
        # `_event_data_foo` not `_event_q_data_foo`.
        if base.endswith("_q"):
            base = base[:-2]
        return f"{base}_{node.attr}"

    # ---- Constants ----
    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, bool):
            if dialect is Dialect.VHDL:
                return "true" if v else "false"
            return "1'b1" if v else "1'b0"
        if isinstance(v, int):
            return str(v)
        # Strings / floats / None / bytes are not in the synthesizable
        # subset per SOS-01 §5.1.
        raise ValueError(
            f"emit_guard_expr: literal {v!r} of type {type(v).__name__} is "
            f"outside the SOS-01 §5.1 ECMAScript subset"
        )

    # ---- Function call — restricted to In(state_id) per SOS-08-C §5.3. ----
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id != "In":
            fn_name = getattr(node.func, "id", repr(node.func))
            raise ValueError(
                f"emit_guard_expr: call to {fn_name!r} is not in the "
                f"synthesizable subset; only `In(state_id)` is permitted "
                f"per SOS-08-C §5.3"
            )
        if len(node.args) != 1 or not isinstance(node.args[0], ast.Constant):
            raise ValueError(
                "emit_guard_expr: In(...) requires exactly one string-literal "
                "argument (the state-id)"
            )
        state_id = node.args[0].value
        if not isinstance(state_id, str):
            raise ValueError(
                f"emit_guard_expr: In(...) argument must be a string state-id; "
                f"got {state_id!r}"
            )
        if dialect is Dialect.VHDL:
            return f"(state = ST_{state_id})"
        return f"(state == ST_{state_id})"

    raise ValueError(
        f"emit_guard_expr: AST node {type(node).__name__!r} is outside the "
        f"SOS-01 §5.1 ECMAScript subset (SOS-08-C §5.3 RTL realisation)"
    )


# ---------------------------------------------------------------------------
# Clock-/reset-port naming helpers (PCDN-SOS-08-C-wave3-clk-naming-passthrough).
# ---------------------------------------------------------------------------


def clk_port_name(domain: str) -> str:
    """Return the wrapper-side clock port name for a clock-domain value.

    Per the 2026-05-23 SOS-08-C wave-3 polish PCDN
    (``PCDN-SOS-08-C-wave3-clk-naming-passthrough``), the chart-author's
    ``<sos:region clock="..."/>`` attribute is the literal port name —
    the walker passes the value through verbatim instead of prepending
    ``clk_`` to it. For backward compatibility with legacy fixtures that
    wrote a bare domain (e.g. ``clock="main"``), this helper prepends
    ``clk_`` only when the input does not already start with it.

    Examples::

        clk_port_name("clk_main")  -> "clk_main"   # pass-through
        clk_port_name("clk_fast")  -> "clk_fast"   # pass-through
        clk_port_name("main")      -> "clk_main"   # legacy fallback
    """

    return domain if domain.startswith("clk_") else f"clk_{domain}"


def rst_port_name(domain: str) -> str:
    """Return the wrapper-side reset port name for a clock-domain value.

    Per ``PCDN-SOS-08-C-wave3-clk-naming-passthrough`` (2026-05-23): the
    reset port mirrors the clock port's domain suffix. If the input
    starts with ``clk_``, the ``clk_`` prefix is rewritten to ``rst_``
    (preserving the trailing domain identifier). If the input is bare,
    ``rst_`` is prepended.

    Examples::

        rst_port_name("clk_main")  -> "rst_main"
        rst_port_name("clk_fast")  -> "rst_fast"
        rst_port_name("main")      -> "rst_main"   # legacy fallback
    """

    if domain.startswith("clk_"):
        return "rst_" + domain[len("clk_"):]
    return f"rst_{domain}"


# ---------------------------------------------------------------------------
# Cross-domain synchronizer instantiation (wave-2; SOS-08-A §6.9 binding).
# ---------------------------------------------------------------------------


def emit_sync_inst(
    inst_name: str,
    src_signal: str,
    dst_signal: str,
    src_clk: str,
    dst_clk: str,
    dst_rst: str,
    width: int,
    stages: int,
    dialect: Dialect,
) -> str:
    """Emit an ``sos_synchronizer`` instance per SOS-08-A §6.9.

    Used by :func:`emit_chart_top_wrapper` at every cross-domain edge
    declared in the chart's ``cross_domain_signals`` audit. Per PCDN-
    SOS-08-C-002 (resolved retain_synchronizers): synchronizer instances
    are retained regardless of ``--verified-strip`` reachability — the
    MTBF claim is independent of chart reachability proofs.

    Parameters
    ----------
    inst_name : str
        Instance name (must be a valid VHDL + SV identifier).
    src_signal : str
        Source-domain signal name (caller's responsibility to Gray-code
        for ``width > 1`` per SOS-08-A §6.9 contract).
    dst_signal : str
        Destination-domain signal name.
    src_clk : str
        Source-domain clock name. NOT a port on the synchronizer per
        SOS-08-A §15 wave-2 (the source clock is asynchronous to the
        destination by definition); preserved in the signature so the
        cdc-audit.json artifact can record which crossing this instance
        services.
    dst_clk : str
        Destination-domain clock name (the ``clk_dst`` port).
    dst_rst : str
        Destination-domain reset name (the ``rst_dst`` port).
    width : int
        Bit-width of the signal (``WIDTH`` generic).
    stages : int
        Number of synchronizer flip-flop stages (``STAGES`` generic;
        mandatory no-default per SOS-08-A §15 wave-2; must be ≥ 2).
    dialect : Dialect
        Output HDL dialect.

    Returns
    -------
    str
        Multi-line instance declaration.

    Cites: SOS-08-A §6.9 (`sos_synchronizer` interface signature);
    SOS-08-A §15 wave-2 (`STAGES` mandatory; no `src_clk` port);
    SOS-08-C §6.7 (cross-domain transition wiring); INV-S-HDL-C-3
    (cross-domain transition enforcement); PCDN-SOS-08-C-002
    (retain_synchronizers).
    """
    if stages < 2:
        raise ValueError(
            f"emit_sync_inst: stages must be ≥ 2 per SOS-08-A §6.9 contract; "
            f"got {stages}"
        )
    if width < 1:
        raise ValueError(f"emit_sync_inst: width must be ≥ 1; got {width}")

    # Note: `src_clk` is NOT routed as a port (per SOS-08-A §15 wave-2)
    # — it's emitted as an inline comment so the cdc-audit consumer can
    # see which domain originated this crossing.
    audit_comment_vhdl = (
        f"-- cdc-audit: {src_clk} -> {dst_clk} (width={width}, stages={stages})"
    )
    audit_comment_sv = (
        f"// cdc-audit: {src_clk} -> {dst_clk} (width={width}, stages={stages})"
    )

    if dialect is Dialect.VHDL:
        return (
            f"{audit_comment_vhdl}\n"
            f"{inst_name} : entity work.sos_synchronizer\n"
            f"    generic map (\n"
            f"        STAGES => {stages},\n"
            f"        WIDTH  => {width}\n"
            f"    )\n"
            f"    port map (\n"
            f"        clk_dst => {dst_clk},\n"
            f"        rst_dst => {dst_rst},\n"
            f"        d_src   => {src_signal},\n"
            f"        d_dst   => {dst_signal}\n"
            f"    );"
        )
    if dialect is Dialect.SV:
        return (
            f"{audit_comment_sv}\n"
            f"sos_synchronizer #(\n"
            f"    .STAGES({stages}),\n"
            f"    .WIDTH({width})\n"
            f") {inst_name} (\n"
            f"    .clk_dst({dst_clk}),\n"
            f"    .rst_dst({dst_rst}),\n"
            f"    .d_src({src_signal}),\n"
            f"    .d_dst({dst_signal})\n"
            f");"
        )
    raise ValueError(f"emit_sync_inst: unsupported dialect {dialect!r}")


# ---------------------------------------------------------------------------
# Chart-top wrapper emission (wave-2; SOS-08-C §6.10).
# ---------------------------------------------------------------------------


def _safe_event_ident_top(name: str) -> str:
    """Sanitise an SCXML event name for chart-top boundary port use.

    SOS-08-C wave-3-b (2026-05-24 §15): chart-top wrapper exposes
    per-region event egress as `event_<region>_<name>_send_valid`
    output ports. SCXML event names may contain dots (`sem.give`);
    we substitute non-alphanumerics with `_` so the resulting port
    name is a legal identifier in both VHDL and SV. The original
    event name is preserved in the per-region FSM module's port
    declaration trailing comment for chart-vocabulary traceability.

    Mirrors `transliterate_hdl_{sv,vhdl}._safe_event_ident*` so the
    chart-top boundary port name matches the per-region module's
    output port name byte-for-byte.
    """
    out = re.sub(r"[^A-Za-z0-9_]", "_", name).strip("_").lower()
    if not out:
        return "ev"
    if out[0].isdigit():
        out = "ev_" + out
    return out


def emit_chart_top_wrapper(
    chart_name: str,
    region_modules: list[dict],
    cross_domain_signals: list[dict],
    dialect: Dialect,
) -> str:
    """Emit the chart-top wrapper per SOS-08-C §6.10.

    Wave-2 canonical region-module shape (per the 2026-05-23 SOS-08-C
    PCDN walkthrough resolution `PCDN-SOS-08-C-wave2-wrapper-shape` and
    `PCDN-SOS-08-C-wave2-region-naming`):

    Each entry in ``region_modules`` is a dict with the following keys:

      * ``name`` (str) — the region's unqualified id (e.g. ``region_a``),
        used to derive the instance name (``u_region_<name>``) and the
        per-region observability output ``current_state_<name>``.
      * ``module`` (str) — the full HDL module/entity name to instantiate
        (e.g. ``<chart>_region_<name>_fsm``). Per the 2026-05-23 PCDN Q1
        resolution, region modules carry the ``_fsm`` suffix on BOTH
        dialects.
      * ``clock_domain`` (str) — the clock-domain identifier (e.g.
        ``main`` / ``clk_fast``). Wrapper emits one ``clk_<dom>`` +
        ``rst_<dom>`` port per distinct domain (PCDN-C-001
        inherit-from-parent).
      * ``datamodel_signals`` (list[dict]) — per-signal records of shape
        ``{"name": <str>, "width": <int>, "direction": "in"|"out"}``.
        ``direction`` is from the region's perspective: ``"out"``
        signals become wrapper outputs (named ``<region>_<signal>``
        when colliding across regions, else ``<signal>``); ``"in"``
        signals become wrapper inputs.
      * ``state_width`` (int) — width of the region's one-hot state
        vector (= number of states in that region); drives the
        ``current_state_<region>`` output port width.

    The wrapper:
      * Deduplicates ``clock_domain`` values; emits ``clk_<dom>`` +
        ``rst_<dom>`` once per distinct domain (PCDN-C-001).
      * Hoists each region's ``datamodel_signals`` to the wrapper
        boundary; collisions disambiguate via ``<region>_<signal>``.
      * Instantiates each region's module (``<module> u_region_<name>``).
      * For each cross-domain signal in ``cross_domain_signals``,
        instantiates :func:`emit_sync_inst` (PCDN-C-002 retain
        regardless of ``--verified-strip`` reachability).
      * Adds one ``current_state_<region>`` observability output per
        region (INV-S-HDL-C-2).

    ``cross_domain_signals`` retains the existing wave-2 shape:
    ``{"name", "src_region", "dst_region", "width", "stages"?}`` where
    ``stages`` defaults to 2 (SOS-08-A §15 wave-2 default).

    Backward compatibility (wave-1 / wave-2 in-flight callers):
    the older region-module shape ``{name, clock, reset, ports}`` is
    still accepted; calls passing that shape route through the legacy
    rendering path and emit a :class:`DeprecationWarning`. Detection
    keys on ``"module"`` (new shape) vs ``"clock"`` (old shape).

    Cites: SOS-08-C §6.10 (chart-top wrapper emission); §6.7 (per-
    region clock annotation); §15 wave-2 ratification
    (`PCDN-SOS-08-C-wave2-wrapper-shape`,
    `PCDN-SOS-08-C-wave2-region-naming`); PCDN-SOS-08-C-001
    (inherit-from-parent default); PCDN-SOS-08-C-002
    (retain_synchronizers); INV-S-HDL-C-3 (cross-domain transition
    enforcement); INV-S-HDL-C-2 (per-region observability).
    """
    if dialect not in (Dialect.VHDL, Dialect.SV):
        raise ValueError(f"emit_chart_top_wrapper: unsupported dialect {dialect!r}")
    if not isinstance(chart_name, str) or not chart_name:
        raise ValueError("emit_chart_top_wrapper: chart_name must be non-empty str")
    if not isinstance(region_modules, list) or not region_modules:
        raise ValueError(
            "emit_chart_top_wrapper: region_modules must be a non-empty list"
        )

    # ---- Shape detection: new wave-2 PCDN walkthrough shape vs legacy. ----
    # New shape carries `module` per entry. Legacy carries `clock`.
    new_shape_entries = [bool("module" in rm) for rm in region_modules]
    if all(new_shape_entries):
        return _emit_chart_top_wrapper_new(
            chart_name, region_modules, cross_domain_signals, dialect
        )
    if not any(new_shape_entries):
        warnings.warn(
            "emit_chart_top_wrapper: the {name,clock,reset,ports} region_modules "
            "shape is deprecated; migrate to "
            "{name, module, clock_domain, datamodel_signals, state_width} per "
            "PCDN-SOS-08-C-wave2-wrapper-shape (2026-05-23). Legacy shape will "
            "be removed in wave-3.",
            DeprecationWarning,
            stacklevel=2,
        )
        return _emit_chart_top_wrapper_legacy(
            chart_name, region_modules, cross_domain_signals, dialect
        )
    raise ValueError(
        "emit_chart_top_wrapper: region_modules entries mix the new "
        "(`module` key) and legacy (`clock` key) shapes; all entries must "
        "follow the same shape within a single call."
    )


def _emit_chart_top_wrapper_new(
    chart_name: str,
    region_modules: list[dict],
    cross_domain_signals: list[dict],
    dialect: Dialect,
) -> str:
    """New wave-2 canonical shape realisation
    (`PCDN-SOS-08-C-wave2-wrapper-shape`).
    """
    # ---- Validate entries + index by region name. ----
    region_index: dict[str, dict] = {}
    for rm in region_modules:
        for required in ("name", "module", "clock_domain", "datamodel_signals",
                         "state_width"):
            if required not in rm:
                raise ValueError(
                    f"emit_chart_top_wrapper: region_modules entry missing "
                    f"required key {required!r}: {rm!r}"
                )
        if not isinstance(rm["datamodel_signals"], list):
            raise TypeError(
                f"emit_chart_top_wrapper: region {rm['name']!r} "
                f"datamodel_signals must be list[dict]; got "
                f"{type(rm['datamodel_signals']).__name__}"
            )
        if not isinstance(rm["state_width"], int) or rm["state_width"] < 1:
            raise ValueError(
                f"emit_chart_top_wrapper: region {rm['name']!r} state_width "
                f"must be a positive int; got {rm['state_width']!r}"
            )
        region_index[rm["name"]] = rm

    # ---- Deduplicate clock domains; emit clk_<dom>/rst_<dom> per domain. ----
    # Determinism per INV-S-HDL-C-1: preserve first-seen order.
    clock_order: list[str] = []
    for rm in region_modules:
        dom = rm["clock_domain"]
        if dom not in clock_order:
            clock_order.append(dom)

    top_name = f"{chart_name}_top"

    # ---- Resolve datamodel-signal collisions across regions. ----
    # If two regions expose a signal with the same name, the wrapper
    # disambiguates by prefixing the region name. Per-region records
    # carry the resolved wrapper-side port name.
    signal_owners: dict[str, list[str]] = {}
    for rm in region_modules:
        for sig in rm["datamodel_signals"]:
            if "name" not in sig or "width" not in sig or "direction" not in sig:
                raise ValueError(
                    f"emit_chart_top_wrapper: region {rm['name']!r} "
                    f"datamodel_signals entry missing name/width/direction: "
                    f"{sig!r}"
                )
            if sig["direction"] not in ("in", "out"):
                raise ValueError(
                    f"emit_chart_top_wrapper: region {rm['name']!r} signal "
                    f"{sig['name']!r} direction must be 'in' or 'out'; got "
                    f"{sig['direction']!r}"
                )
            signal_owners.setdefault(sig["name"], []).append(rm["name"])

    def _wrapper_port_name(region_name: str, sig_name: str) -> str:
        # Single owner per signal name → use bare signal name.
        # Multiple owners → prefix with region name to disambiguate.
        owners = signal_owners.get(sig_name, [])
        if len(owners) <= 1:
            return sig_name
        return f"{region_name}_{sig_name}"

    # ---- Build the top-boundary port list. ----
    # Order (deterministic per INV-S-HDL-C-1):
    #   1. clk_<dom> per distinct domain.
    #   2. rst_<dom> per distinct domain.
    #   3. Per-region datamodel signals (in region iteration order).
    #   4. Per-region current_state_<name> observability outputs.
    boundary_ports: list[HdlPort] = []
    # PCDN-SOS-08-C-wave3-clk-naming-passthrough (2026-05-23): walker
    # passes the chart-author's clock-domain value through verbatim
    # instead of prepending `clk_`. clk_port_name / rst_port_name handle
    # the legacy-bare-domain fallback in one place.
    for dom in clock_order:
        boundary_ports.append(
            HdlPort(name=clk_port_name(dom), direction="in", width=1)
        )
    for dom in clock_order:
        boundary_ports.append(
            HdlPort(name=rst_port_name(dom), direction="in", width=1)
        )
    seen_port_names: set[str] = {p.name for p in boundary_ports}
    for rm in region_modules:
        for sig in rm["datamodel_signals"]:
            port_name = _wrapper_port_name(rm["name"], sig["name"])
            if port_name in seen_port_names:
                continue
            seen_port_names.add(port_name)
            boundary_ports.append(
                HdlPort(
                    name=port_name,
                    direction=sig["direction"],
                    width=int(sig["width"]),
                )
            )
    for rm in region_modules:
        boundary_ports.append(
            HdlPort(
                name=f"current_state_{rm['name']}",
                direction="out",
                width=int(rm["state_width"]),
            )
        )

    # SOS-08-C wave-3-c (2026-05-24 §15): per-chart-wide-event message-
    # channel instantiation. Each region_module MAY carry an optional
    # `raise_events: list[str]` listing event names this region raises.
    # The chart-top wrapper collects all chart-wide unique event names
    # and instantiates ONE `sos_message_channel` per unique name per
    # SOS-08-C §6.5 + §6.4. Per-region `event_<name>_send_valid`
    # outputs are OR-aggregated and fed into the channel's
    # `s_axis_tvalid` (INV-S-HDL-4 cooperative — at most one region
    # pulses per cycle, so the OR is correct).
    #
    # Wave-3-c exposes ONLY the channel's downstream-facing handshake
    # at the boundary: `event_<name>_recv_valid` (output) +
    # `event_<name>_recv_ready` (input). Payload + event_id at the
    # boundary, plus the slave-side `tready` and producer-side
    # backpressure, land in wave-3-d / -3-e per the wave-3-a roadmap.
    chart_event_set: list[str] = []
    chart_event_producers: dict[str, list[str]] = {}
    chart_event_consumers: dict[str, list[str]] = {}
    for rm in region_modules:
        for ev in rm.get("raise_events", []) or []:
            if ev not in chart_event_producers:
                if ev not in chart_event_set:
                    chart_event_set.append(ev)
                chart_event_producers[ev] = []
            chart_event_producers[ev].append(rm["name"])
        # SOS-08-C wave-3-d-3 (2026-05-24 §15): collect per-region
        # consume events for chart-top fanout + recv_ready aggregation.
        for ev in rm.get("consume_events", []) or []:
            if ev not in chart_event_consumers:
                if ev not in chart_event_set:
                    chart_event_set.append(ev)
                chart_event_consumers[ev] = []
            chart_event_consumers[ev].append(rm["name"])
    for ev in chart_event_set:
        ev_ident = _safe_event_ident_top(ev)
        boundary_ports.append(
            HdlPort(
                name=f"event_{ev_ident}_recv_valid",
                direction="out",
                width=1,
            )
        )
        boundary_ports.append(
            HdlPort(
                name=f"event_{ev_ident}_recv_ready",
                direction="in",
                width=1,
            )
        )

    # ---- Emit per dialect. ----
    if dialect is Dialect.VHDL:
        return _emit_chart_top_wrapper_vhdl_new(
            top_name, boundary_ports, region_modules,
            cross_domain_signals, region_index, clock_order,
            _wrapper_port_name,
            chart_event_set=chart_event_set,
            chart_event_producers=chart_event_producers,
            chart_event_consumers=chart_event_consumers,
        )
    return _emit_chart_top_wrapper_sv_new(
        top_name, boundary_ports, region_modules,
        cross_domain_signals, region_index, clock_order,
        _wrapper_port_name,
        chart_event_set=chart_event_set,
        chart_event_producers=chart_event_producers,
        chart_event_consumers=chart_event_consumers,
    )


def _emit_chart_top_wrapper_legacy(
    chart_name: str,
    region_modules: list[dict],
    cross_domain_signals: list[dict],
    dialect: Dialect,
) -> str:
    """Legacy {name,clock,reset,ports} realisation. Retained for
    backward compat with wave-1 / in-flight wave-2 callers; will be
    removed in wave-3 per the 2026-05-23 PCDN walkthrough."""
    clock_order: list[str] = []
    reset_order: list[str] = []
    region_index: dict[str, dict] = {}
    for rm in region_modules:
        if "name" not in rm or "clock" not in rm or "reset" not in rm:
            raise ValueError(
                f"emit_chart_top_wrapper: region_modules entry missing "
                f"required keys (name/clock/reset): {rm!r}"
            )
        region_index[rm["name"]] = rm
        if rm["clock"] not in clock_order:
            clock_order.append(rm["clock"])
        if rm["reset"] not in reset_order:
            reset_order.append(rm["reset"])

    top_name = f"{chart_name}_top"

    seen_port_names: set[str] = set(clock_order) | set(reset_order)
    boundary_ports: list[HdlPort] = []
    for ck in clock_order:
        boundary_ports.append(HdlPort(name=ck, direction="in", width=1))
    for rs in reset_order:
        boundary_ports.append(HdlPort(name=rs, direction="in", width=1))
    for rm in region_modules:
        for p in rm.get("ports", []):
            if not isinstance(p, HdlPort):
                raise TypeError(
                    f"emit_chart_top_wrapper: region {rm['name']!r} port "
                    f"entries must be HdlPort instances; got "
                    f"{type(p).__name__}"
                )
            if p.name in seen_port_names:
                continue
            seen_port_names.add(p.name)
            boundary_ports.append(p)

    if dialect is Dialect.VHDL:
        return _emit_chart_top_wrapper_vhdl(
            top_name, boundary_ports, region_modules,
            cross_domain_signals, region_index,
        )
    return _emit_chart_top_wrapper_sv(
        top_name, boundary_ports, region_modules,
        cross_domain_signals, region_index,
    )


def _emit_chart_top_wrapper_vhdl_new(
    top_name: str,
    boundary_ports: list[HdlPort],
    region_modules: list[dict],
    cross_domain_signals: list[dict],
    region_index: dict[str, dict],
    clock_order: list[str],
    wrapper_port_name,
    chart_event_set: list[str] | None = None,
    chart_event_producers: dict[str, list[str]] | None = None,
    chart_event_consumers: dict[str, list[str]] | None = None,
) -> str:
    """VHDL realisation of the new wave-2 wrapper shape
    (`PCDN-SOS-08-C-wave2-wrapper-shape`)."""
    chart_event_consumers = chart_event_consumers or {}
    lines: list[str] = []
    # Header comment per SOS-08-C §6.10 + §15 wave-2 ratification.
    lines.append(
        "-- SOS-08-C §6.10 chart-top wrapper "
        "(PCDN-SOS-08-C-wave2-wrapper-shape, 2026-05-23)."
    )
    lines.append(
        "-- PCDN-C-001: clock-domain inherit-from-parent (one clk_<dom>/"
        "rst_<dom> per domain)."
    )
    lines.append(
        "-- PCDN-C-002: synchronizers retained regardless of "
        "--verified-strip."
    )
    lines.append("library ieee;")
    lines.append("use ieee.std_logic_1164.all;")
    lines.append("")
    lines.append(f"entity {top_name} is")
    lines.append("    port (")
    rendered = [emit_port_decl(p, Dialect.VHDL) for p in boundary_ports]
    for i, pl in enumerate(rendered):
        suffix = ";" if i < len(rendered) - 1 else ""
        lines.append(f"        {pl}{suffix}")
    lines.append("    );")
    lines.append(f"end entity {top_name};")
    lines.append("")
    lines.append(f"architecture rtl of {top_name} is")
    # Declare cross-domain wires (one wire per CDC edge, in dst domain).
    for cd in cross_domain_signals:
        w = int(cd.get("width", 1))
        name = cd["name"]
        if w == 1:
            lines.append(f"    signal {name}_sync : std_logic;")
        else:
            lines.append(
                f"    signal {name}_sync : std_logic_vector({w - 1} downto 0);"
            )
    lines.append("begin")
    # Synchronizer instances per PCDN-C-002.
    for i, cd in enumerate(cross_domain_signals):
        src_id = cd["src_region"]
        dst_id = cd["dst_region"]
        src_rm = region_index.get(src_id)
        dst_rm = region_index.get(dst_id)
        if src_rm is None or dst_rm is None:
            raise ValueError(
                f"emit_chart_top_wrapper: cross_domain_signals[{i}] references "
                f"unknown region(s): src={src_id!r} dst={dst_id!r}"
            )
        lines.append(
            emit_sync_inst(
                inst_name=f"u_sync_{cd['name']}",
                src_signal=cd["name"],
                dst_signal=f"{cd['name']}_sync",
                src_clk=clk_port_name(src_rm["clock_domain"]),
                dst_clk=clk_port_name(dst_rm["clock_domain"]),
                dst_rst=rst_port_name(dst_rm["clock_domain"]),
                width=int(cd.get("width", 1)),
                stages=int(cd.get("stages", 2)),
                dialect=Dialect.VHDL,
            )
        )
    # Region instances.
    for rm in region_modules:
        inst = f"u_region_{rm['name']}"
        dom = rm["clock_domain"]
        lines.append(f"    {inst} : entity work.{rm['module']}")
        lines.append("        port map (")
        port_lines: list[str] = []
        # PCDN-SOS-08-C-wave3-clk-naming-passthrough: pass domain through.
        port_lines.append(f"clk => {clk_port_name(dom)}")
        port_lines.append(f"rst => {rst_port_name(dom)}")
        for sig in rm["datamodel_signals"]:
            wrapper_side = wrapper_port_name(rm["name"], sig["name"])
            port_lines.append(f"{sig['name']} => {wrapper_side}")
        port_lines.append(
            f"current_state => current_state_{rm['name']}"
        )
        # SOS-08-C wave-3-c: connect per-event egress outputs to
        # INTERNAL signals (wave-3-b passthrough boundary superseded).
        # The signals feed the per-event sos_message_channel
        # instance's s_axis_tvalid input via OR-aggregation below.
        #
        # SOS-08-C wave-3-d (2026-05-24 §15): also wire the matching
        # `event_<name>_send_ready` input from the chart-wide
        # `ev_<name>_send_ready` signal that carries the channel's
        # `s_axis_tready`. Broadcast is correct under INV-S-HDL-4.
        for ev in rm.get("raise_events", []) or []:
            ev_ident = _safe_event_ident_top(ev)
            port_lines.append(
                f"event_{ev_ident}_send_valid => "
                f"w_ev_{rm['name']}_{ev_ident}_pulse"
            )
            port_lines.append(
                f"event_{ev_ident}_send_ready => "
                f"ev_{ev_ident}_send_ready"
            )
        # SOS-08-C wave-3-d-3: consume-event ingress fanout +
        # per-consumer recv_ready wire.
        for ev in rm.get("consume_events", []) or []:
            ev_ident = _safe_event_ident_top(ev)
            port_lines.append(
                f"event_{ev_ident}_recv_valid => "
                f"ev_{ev_ident}_recv_valid_w"
            )
            port_lines.append(
                f"event_{ev_ident}_recv_ready => "
                f"w_ev_{rm['name']}_{ev_ident}_ready"
            )
        for j, pl in enumerate(port_lines):
            suffix = "," if j < len(port_lines) - 1 else ""
            lines.append(f"            {pl}{suffix}")
        lines.append("        );")
    chart_event_set = chart_event_set or []
    chart_event_producers = chart_event_producers or {}
    if chart_event_set:
        lines.append("")
        lines.append(
            "    -- ----- SOS-08-C wave-3-c: per-event message channels -----"
        )
        # Per-event channel instances.
        for idx, ev in enumerate(sorted(chart_event_set)):
            ev_ident = _safe_event_ident_top(ev)
            producers = chart_event_producers.get(ev, [])
            consumers = chart_event_consumers.get(ev, [])
            agg_terms = " or ".join(
                f"w_ev_{r}_{ev_ident}_pulse" for r in producers
            ) or "'0'"
            lines.append(
                f"    ev_{ev_ident}_send_valid <= {agg_terms};"
                f"  -- chart event `{ev}`"
            )
            # Wave-3-d-3: recv_valid_w drives boundary observer port.
            lines.append(
                f"    event_{ev_ident}_recv_valid <= "
                f"ev_{ev_ident}_recv_valid_w;"
                f"  -- chart event `{ev}` boundary observer"
            )
            ready_terms = [f"event_{ev_ident}_recv_ready"] + [
                f"w_ev_{r}_{ev_ident}_ready" for r in consumers
            ]
            lines.append(
                f"    ev_{ev_ident}_recv_ready_w <= "
                f"{' or '.join(ready_terms)};"
                f"  -- chart event `{ev}` recv_ready aggregate"
            )
            first_dom = clock_order[0] if clock_order else "main"
            if producers and producers[0] in region_index:
                first_dom = region_index[producers[0]]["clock_domain"]
            elif consumers and consumers[0] in region_index:
                first_dom = region_index[consumers[0]]["clock_domain"]
            lines.append(
                f"    u_chan_{ev_ident} : entity work.sos_message_channel\n"
                f"        generic map (\n"
                f"            EVENT_ID_WIDTH => 8,\n"
                f"            PAYLOAD_WIDTH  => 8,\n"
                f"            DEPTH          => 4,\n"
                f"            READ_LATENCY   => 0,\n"
                f"            RESET_MEM      => '1'\n"
                f"        )\n"
                f"        port map (\n"
                f"            clk              => {clk_port_name(first_dom)},\n"
                f"            rst              => {rst_port_name(first_dom)},\n"
                f"            s_axis_tdata     => (others => '0'),\n"
                f"            s_axis_tevent_id => std_logic_vector(to_unsigned({idx}, 8)),\n"
                f"            s_axis_tpayload  => (others => '0'),\n"
                f"            s_axis_tvalid    => ev_{ev_ident}_send_valid,\n"
                f"            s_axis_tready    => ev_{ev_ident}_send_ready,\n"
                f"            m_axis_tdata     => open,\n"
                f"            m_axis_tevent_id => open,\n"
                f"            m_axis_tpayload  => open,\n"
                f"            m_axis_tvalid    => ev_{ev_ident}_recv_valid_w,\n"
                f"            m_axis_tready    => ev_{ev_ident}_recv_ready_w,\n"
                f"            full             => open,\n"
                f"            empty            => open,\n"
                f"            count            => open\n"
                f"        );"
            )
    lines.append("end architecture rtl;")
    # VHDL declares the per-region pulse signals + per-event aggregated
    # signal in the architecture's declarative region. We assemble the
    # final string by injecting the declarations after `architecture
    # rtl of <top_name> is`.
    if chart_event_set:
        decl_block: list[str] = []
        decl_block.append(
            "    -- ----- SOS-08-C wave-3-c: event-egress signals -----"
        )
        producer_wires_emitted: set[str] = set()
        for ev in sorted(chart_event_set):
            ev_ident = _safe_event_ident_top(ev)
            for region_name in chart_event_producers.get(ev, []):
                wire_name = f"w_ev_{region_name}_{ev_ident}_pulse"
                if wire_name in producer_wires_emitted:
                    continue
                producer_wires_emitted.add(wire_name)
                decl_block.append(f"    signal {wire_name} : std_logic;")
            decl_block.append(
                f"    signal ev_{ev_ident}_send_valid : std_logic;"
            )
            # SOS-08-C wave-3-d (2026-05-24 §15): per-event send_ready
            # signal carrying the channel's `s_axis_tready` broadcast
            # back to every producer region's `event_<name>_send_ready`
            # input port.
            decl_block.append(
                f"    signal ev_{ev_ident}_send_ready : std_logic;"
            )
            # SOS-08-C wave-3-d-3: per-consumer recv_ready signals +
            # per-event recv_valid fanout + aggregated recv_ready.
            for region_name in chart_event_consumers.get(ev, []):
                decl_block.append(
                    f"    signal w_ev_{region_name}_{ev_ident}_ready : std_logic;"
                )
            decl_block.append(
                f"    signal ev_{ev_ident}_recv_valid_w : std_logic;"
            )
            decl_block.append(
                f"    signal ev_{ev_ident}_recv_ready_w : std_logic;"
            )
        decl_text = "\n".join(decl_block)
        # Locate the architecture-decl marker (the line right after the
        # `architecture rtl of <top_name> is` line) and inject.
        out = "\n".join(lines)
        marker = f"architecture rtl of {top_name} is"
        out = out.replace(marker, marker + "\n" + decl_text, 1)
        return out
    return "\n".join(lines)


def _emit_chart_top_wrapper_sv_new(
    top_name: str,
    boundary_ports: list[HdlPort],
    region_modules: list[dict],
    cross_domain_signals: list[dict],
    region_index: dict[str, dict],
    clock_order: list[str],
    wrapper_port_name,
    chart_event_set: list[str] | None = None,
    chart_event_producers: dict[str, list[str]] | None = None,
    chart_event_consumers: dict[str, list[str]] | None = None,
) -> str:
    """SystemVerilog realisation of the new wave-2 wrapper shape
    (`PCDN-SOS-08-C-wave2-wrapper-shape`).

    SOS-08-C wave-3-c (2026-05-24 §15): when chart-wide events are
    present, instantiates one ``sos_message_channel`` per unique
    event name + OR-aggregates per-region ``event_<name>_send_valid``
    pulses into the channel's slave-side ``s_axis_tvalid`` input.
    Channel parameters default to a v1 baseline (EVENT_ID_WIDTH=8,
    PAYLOAD_WIDTH=8, DEPTH=4, READ_LATENCY=0, RESET_MEM=1) per
    SOS-08-B §6.5 + §5.
    """
    chart_event_set = chart_event_set or []
    chart_event_producers = chart_event_producers or {}
    chart_event_consumers = chart_event_consumers or {}
    lines: list[str] = []
    lines.append(
        "// SOS-08-C §6.10 chart-top wrapper "
        "(PCDN-SOS-08-C-wave2-wrapper-shape, 2026-05-23)."
    )
    lines.append(
        "// PCDN-C-001: clock-domain inherit-from-parent (one clk_<dom>/"
        "rst_<dom> per domain)."
    )
    lines.append(
        "// PCDN-C-002: synchronizers retained regardless of "
        "--verified-strip."
    )
    lines.append(f"module {top_name} (")
    rendered = [emit_port_decl(p, Dialect.SV) for p in boundary_ports]
    for i, pl in enumerate(rendered):
        suffix = "," if i < len(rendered) - 1 else ""
        lines.append(f"    {pl}{suffix}")
    lines.append(");")
    # Cross-domain wires.
    for cd in cross_domain_signals:
        w = int(cd.get("width", 1))
        name = cd["name"]
        if w == 1:
            lines.append(f"    logic {name}_sync;")
        else:
            lines.append(f"    logic [{w - 1}:0] {name}_sync;")
    # Synchronizer instances per PCDN-C-002.
    for i, cd in enumerate(cross_domain_signals):
        src_id = cd["src_region"]
        dst_id = cd["dst_region"]
        src_rm = region_index.get(src_id)
        dst_rm = region_index.get(dst_id)
        if src_rm is None or dst_rm is None:
            raise ValueError(
                f"emit_chart_top_wrapper: cross_domain_signals[{i}] references "
                f"unknown region(s): src={src_id!r} dst={dst_id!r}"
            )
        lines.append(
            emit_sync_inst(
                inst_name=f"u_sync_{cd['name']}",
                src_signal=cd["name"],
                dst_signal=f"{cd['name']}_sync",
                src_clk=clk_port_name(src_rm["clock_domain"]),
                dst_clk=clk_port_name(dst_rm["clock_domain"]),
                dst_rst=rst_port_name(dst_rm["clock_domain"]),
                width=int(cd.get("width", 1)),
                stages=int(cd.get("stages", 2)),
                dialect=Dialect.SV,
            )
        )
    # Region instances.
    for rm in region_modules:
        inst = f"u_region_{rm['name']}"
        dom = rm["clock_domain"]
        lines.append(f"    {rm['module']} {inst} (")
        port_lines: list[str] = []
        # PCDN-SOS-08-C-wave3-clk-naming-passthrough: pass domain through.
        port_lines.append(f".clk({clk_port_name(dom)})")
        port_lines.append(f".rst({rst_port_name(dom)})")
        for sig in rm["datamodel_signals"]:
            wrapper_side = wrapper_port_name(rm["name"], sig["name"])
            port_lines.append(f".{sig['name']}({wrapper_side})")
        port_lines.append(
            f".current_state(current_state_{rm['name']})"
        )
        # SOS-08-C wave-3-c: connect per-event egress outputs to
        # INTERNAL wires (wave-3-b passthrough boundary ports
        # superseded). The internal wires feed the per-event
        # `sos_message_channel` instance's `s_axis_tvalid` input via
        # OR-aggregation below.
        #
        # SOS-08-C wave-3-d (2026-05-24 §15): also wire the matching
        # `event_<name>_send_ready` input from the chart-wide
        # `ev_<name>_send_ready` wire that carries the channel's
        # `s_axis_tready`. The fanout is a broadcast — every producer
        # region sees the same ready signal — which is correct under
        # INV-S-HDL-4 cooperative-only (at most one producer pulses
        # per cycle).
        for ev in rm.get("raise_events", []) or []:
            ev_ident = _safe_event_ident_top(ev)
            port_lines.append(
                f".event_{ev_ident}_send_valid"
                f"(w_ev_{rm['name']}_{ev_ident}_pulse)"
            )
            port_lines.append(
                f".event_{ev_ident}_send_ready"
                f"(ev_{ev_ident}_send_ready)"
            )
        # SOS-08-C wave-3-d-3: connect per-consumed-event ingress.
        # `_recv_valid` is fanout of channel's m_axis_tvalid (shared
        # broadcast); `_recv_ready` is per-consumer wire OR-aggregated
        # into channel's m_axis_tready below.
        for ev in rm.get("consume_events", []) or []:
            ev_ident = _safe_event_ident_top(ev)
            port_lines.append(
                f".event_{ev_ident}_recv_valid"
                f"(ev_{ev_ident}_recv_valid_w)"
            )
            port_lines.append(
                f".event_{ev_ident}_recv_ready"
                f"(w_ev_{rm['name']}_{ev_ident}_ready)"
            )
        for j, pl in enumerate(port_lines):
            suffix = "," if j < len(port_lines) - 1 else ""
            lines.append(f"        {pl}{suffix}")
        lines.append("    );")

    # SOS-08-C wave-3-c: per-event sos_message_channel instances +
    # producer-side OR-aggregation. One channel per chart-wide unique
    # event name (sorted-deterministic order per INV-S-HDL-C-1).
    if chart_event_set:
        lines.append("")
        lines.append(
            "    // ----- SOS-08-C wave-3-c: per-event message channels -----"
        )
        # Per-region pulse wires (declared once, OR-aggregated below).
        producer_wires_emitted: set[str] = set()
        for ev in sorted(chart_event_set):
            ev_ident = _safe_event_ident_top(ev)
            for region_name in chart_event_producers.get(ev, []):
                wire_name = f"w_ev_{region_name}_{ev_ident}_pulse"
                if wire_name in producer_wires_emitted:
                    continue
                producer_wires_emitted.add(wire_name)
                lines.append(f"    wire {wire_name};")
        # Per-event send_ready wire (wave-3-d): the channel's
        # `s_axis_tready` output broadcast to every producer region's
        # `event_<name>_send_ready` input. One wire per chart-wide
        # unique event.
        for ev in sorted(chart_event_set):
            ev_ident = _safe_event_ident_top(ev)
            lines.append(
                f"    wire ev_{ev_ident}_send_ready;"
                f"  // chart event `{ev}` (wave-3-d backpressure)"
            )
        # SOS-08-C wave-3-d-3: per-consumer recv_ready wires (declared
        # once per (region, event) consume edge), per-event
        # recv_valid_w fanout wires, and per-event aggregated
        # recv_ready_w into the channel's m_axis_tready.
        consumer_wires_emitted: set[str] = set()
        for ev in sorted(chart_event_set):
            ev_ident = _safe_event_ident_top(ev)
            for region_name in chart_event_consumers.get(ev, []):
                wire_name = f"w_ev_{region_name}_{ev_ident}_ready"
                if wire_name in consumer_wires_emitted:
                    continue
                consumer_wires_emitted.add(wire_name)
                lines.append(
                    f"    wire {wire_name};"
                    f"  // chart event `{ev}` consumer-ready (region `{region_name}`)"
                )
            # recv_valid_w: internal fanout wire carrying channel
            # m_axis_tvalid; assigned to boundary port + region inputs.
            lines.append(
                f"    wire ev_{ev_ident}_recv_valid_w;"
                f"  // chart event `{ev}` recv_valid fanout"
            )
        # One channel + OR-aggregated valid + hardcoded event_id per
        # unique event. Channel params per SOS-08-B §5 v1 baseline.
        for idx, ev in enumerate(sorted(chart_event_set)):
            ev_ident = _safe_event_ident_top(ev)
            producers = chart_event_producers.get(ev, [])
            consumers = chart_event_consumers.get(ev, [])
            agg_terms = " | ".join(
                f"w_ev_{r}_{ev_ident}_pulse" for r in producers
            ) or "1'b0"
            lines.append(
                f"    wire ev_{ev_ident}_send_valid = {agg_terms};"
                f"  // chart event `{ev}`"
            )
            # SOS-08-C wave-3-d-3: recv_valid_w drives both the
            # boundary `event_<name>_recv_valid` output AND each
            # consuming region's `event_<name>_recv_valid` input.
            lines.append(
                f"    assign event_{ev_ident}_recv_valid = "
                f"ev_{ev_ident}_recv_valid_w;"
                f"  // chart event `{ev}` boundary observer"
            )
            # recv_ready_w aggregates the boundary `_recv_ready`
            # input AND every consuming region's _recv_ready output.
            # Broadcast under INV-S-HDL-4 cooperative-only — at most
            # one consumer is ready per cycle in the typical case.
            ready_terms = [f"event_{ev_ident}_recv_ready"] + [
                f"w_ev_{r}_{ev_ident}_ready" for r in consumers
            ]
            lines.append(
                f"    wire ev_{ev_ident}_recv_ready_w = "
                f"{' | '.join(ready_terms)};"
                f"  // chart event `{ev}` recv_ready aggregate"
            )
            # Choose clock domain: first producer's clock domain.
            # Multi-domain producers requires the async channel
            # variant (`sos_message_channel_async`) which is deferred
            # to its own wave (post wave-3-d); v1 assumes single
            # clock domain across producers of a given event.
            first_dom = clock_order[0] if clock_order else "main"
            if producers and producers[0] in region_index:
                first_dom = region_index[producers[0]]["clock_domain"]
            elif consumers and consumers[0] in region_index:
                first_dom = region_index[consumers[0]]["clock_domain"]
            lines.append(
                f"    // SOS-08-C wave-3-c channel for event `{ev}` — "
                f"event_id={idx}\n"
                f"    // Wave-3-d-1: s_axis_tready → ev_<name>_send_ready\n"
                f"    // (broadcast to producer regions).\n"
                f"    // Wave-3-d-3: m_axis_tvalid → ev_<name>_recv_valid_w\n"
                f"    // (fanout to boundary + consumer regions);\n"
                f"    //              m_axis_tready ← OR of boundary +\n"
                f"    //              per-consumer recv_ready signals.\n"
                f"    sos_message_channel #(\n"
                f"        .EVENT_ID_WIDTH(8),\n"
                f"        .PAYLOAD_WIDTH(8),\n"
                f"        .DEPTH(4),\n"
                f"        .READ_LATENCY(0),\n"
                f"        .RESET_MEM(1)\n"
                f"    ) u_chan_{ev_ident} (\n"
                f"        .clk({clk_port_name(first_dom)}),\n"
                f"        .rst({rst_port_name(first_dom)}),\n"
                f"        .s_axis_tdata('0),\n"
                f"        .s_axis_tevent_id(8'd{idx}),\n"
                f"        .s_axis_tpayload('0),\n"
                f"        .s_axis_tvalid(ev_{ev_ident}_send_valid),\n"
                f"        .s_axis_tready(ev_{ev_ident}_send_ready),\n"
                f"        .m_axis_tdata(),\n"
                f"        .m_axis_tevent_id(),\n"
                f"        .m_axis_tpayload(),\n"
                f"        .m_axis_tvalid(ev_{ev_ident}_recv_valid_w),\n"
                f"        .m_axis_tready(ev_{ev_ident}_recv_ready_w),\n"
                f"        .full(),\n"
                f"        .empty(),\n"
                f"        .count()\n"
                f"    );"
            )
    lines.append("endmodule")
    return "\n".join(lines)


def _emit_chart_top_wrapper_vhdl(
    top_name: str,
    boundary_ports: list[HdlPort],
    region_modules: list[dict],
    cross_domain_signals: list[dict],
    region_index: dict[str, dict],
) -> str:
    """VHDL realisation of the wrapper (SOS-08-C §6.10)."""
    lines: list[str] = []
    lines.append(f"entity {top_name} is")
    lines.append("    port (")
    rendered = [emit_port_decl(p, Dialect.VHDL) for p in boundary_ports]
    for i, pl in enumerate(rendered):
        suffix = ";" if i < len(rendered) - 1 else ""
        lines.append(f"        {pl}{suffix}")
    lines.append("    );")
    lines.append(f"end entity {top_name};")
    lines.append("")
    lines.append(f"architecture rtl of {top_name} is")
    # Declare cross-domain wires (one wire per CDC edge, in dst domain).
    for cd in cross_domain_signals:
        w = int(cd.get("width", 1))
        name = cd["name"]
        if w == 1:
            lines.append(f"    signal {name}_sync : std_logic;")
        else:
            lines.append(
                f"    signal {name}_sync : std_logic_vector({w - 1} downto 0);"
            )
    lines.append("begin")
    # Synchronizer instances (retain regardless of --verified-strip
    # per PCDN-C-002).
    for i, cd in enumerate(cross_domain_signals):
        src_id = cd["src_region"]
        dst_id = cd["dst_region"]
        src_rm = region_index.get(src_id)
        dst_rm = region_index.get(dst_id)
        if src_rm is None or dst_rm is None:
            raise ValueError(
                f"emit_chart_top_wrapper: cross_domain_signals[{i}] references "
                f"unknown region(s): src={src_id!r} dst={dst_id!r}"
            )
        lines.append(
            emit_sync_inst(
                inst_name=f"u_sync_{cd['name']}",
                src_signal=cd["name"],
                dst_signal=f"{cd['name']}_sync",
                src_clk=src_rm["clock"],
                dst_clk=dst_rm["clock"],
                dst_rst=dst_rm["reset"],
                width=int(cd.get("width", 1)),
                stages=int(cd.get("stages", 2)),
                dialect=Dialect.VHDL,
            )
        )
    # Region instances.
    for rm in region_modules:
        inst = f"u_{rm['name']}"
        lines.append(
            f"    {inst} : entity work.sos_region_{rm['name']}"
        )
        lines.append("        port map (")
        port_lines: list[str] = []
        port_lines.append(f"clk => {rm['clock']}")
        port_lines.append(f"rst => {rm['reset']}")
        for p in rm.get("ports", []):
            # Wire region port to top-boundary signal of the same name.
            port_lines.append(f"{p.name} => {p.name}")
        for j, pl in enumerate(port_lines):
            suffix = "," if j < len(port_lines) - 1 else ""
            lines.append(f"            {pl}{suffix}")
        lines.append("        );")
    lines.append("end architecture rtl;")
    return "\n".join(lines)


def _emit_chart_top_wrapper_sv(
    top_name: str,
    boundary_ports: list[HdlPort],
    region_modules: list[dict],
    cross_domain_signals: list[dict],
    region_index: dict[str, dict],
) -> str:
    """SystemVerilog realisation of the wrapper (SOS-08-C §6.10)."""
    lines: list[str] = []
    lines.append(f"module {top_name} (")
    rendered = [emit_port_decl(p, Dialect.SV) for p in boundary_ports]
    for i, pl in enumerate(rendered):
        suffix = "," if i < len(rendered) - 1 else ""
        lines.append(f"    {pl}{suffix}")
    lines.append(");")
    # Declare cross-domain wires.
    for cd in cross_domain_signals:
        w = int(cd.get("width", 1))
        name = cd["name"]
        if w == 1:
            lines.append(f"    logic {name}_sync;")
        else:
            lines.append(f"    logic [{w - 1}:0] {name}_sync;")
    # Synchronizer instances.
    for i, cd in enumerate(cross_domain_signals):
        src_id = cd["src_region"]
        dst_id = cd["dst_region"]
        src_rm = region_index.get(src_id)
        dst_rm = region_index.get(dst_id)
        if src_rm is None or dst_rm is None:
            raise ValueError(
                f"emit_chart_top_wrapper: cross_domain_signals[{i}] references "
                f"unknown region(s): src={src_id!r} dst={dst_id!r}"
            )
        lines.append(
            emit_sync_inst(
                inst_name=f"u_sync_{cd['name']}",
                src_signal=cd["name"],
                dst_signal=f"{cd['name']}_sync",
                src_clk=src_rm["clock"],
                dst_clk=dst_rm["clock"],
                dst_rst=dst_rm["reset"],
                width=int(cd.get("width", 1)),
                stages=int(cd.get("stages", 2)),
                dialect=Dialect.SV,
            )
        )
    # Region instances.
    for rm in region_modules:
        inst = f"u_{rm['name']}"
        lines.append(f"    sos_region_{rm['name']} {inst} (")
        port_lines: list[str] = []
        port_lines.append(f".clk({rm['clock']})")
        port_lines.append(f".rst({rm['reset']})")
        for p in rm.get("ports", []):
            port_lines.append(f".{p.name}({p.name})")
        for j, pl in enumerate(port_lines):
            suffix = "," if j < len(port_lines) - 1 else ""
            lines.append(f"        {pl}{suffix}")
        lines.append("    );")
    lines.append("endmodule")
    return "\n".join(lines)


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
    "emit_signal_decl_int",
    "emit_fsm_state_encoding",
    "emit_fsm_state_constants",
    "emit_register_process",
    "emit_combinational_block",
    "emit_header_comment",
    "emit_transition_mux",
    "emit_guard_expr",
    "emit_sync_inst",
    "emit_chart_top_wrapper",
    # Datamodel + analysis
    "map_datamodel_type",
    "datamodel_width",
    "port_width_from_signal_width",
    "compute_guard_depth",
    "encoding_width",
    # Exceptions
    "GuardDepthError",
    # Constants
    "DEFAULT_GUARD_DEPTH_BUDGET",
]
