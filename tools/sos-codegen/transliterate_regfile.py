"""SOS-09-E HDL register-file RTL emitter.

Walks a :class:`~sos09_annotations.ChartAnnotations` model (the SOS-09-A
authoritative input contract) and emits a parameterised ``sos_regfile``
RTL module per chart channel-group, in BOTH VHDL-2008 and
SystemVerilog-2017. The two language emissions are produced from the
same Jinja2 template family and share identical structural decisions
(channel set, register addresses, primitive instantiations, access-
violation aggregation), satisfying language parity per gate (g) of
``docs/concepts/SOS-09-E-CONCEPTS.md`` §12 and INV-S-MEM-E-5.

Authority: ``docs/concepts/SOS-09-E-CONCEPTS.md`` (ratified 2026-05-26);
sub-phase of the SOS-09 umbrella. Input contract owned by SOS-09-A
(``sos09_annotations.py``); this module is a *consumer* of that contract
and MUST NOT redefine the types or value grammars exposed there.

PCDN decisions encoded here (all RATIFIED 2026-05-26):

- PCDN-SOS-09-E-001(a): AXI4-Lite default bus; APB available via
  ``sos:bus="apb"`` channel-group annotation.
- PCDN-SOS-09-E-002(a): reserved bits read as zero, write-ignored.
- PCDN-SOS-09-E-003(a): ONE ``sos_strobe_latch`` per
  ``sos:privilege_region`` aggregating access-violation events.
- PCDN-SOS-09-E-004(a): cross-clock channels (per chart-declared
  ``sos:clock_domain``) get ``sos_synchronizer`` insertion.
- PCDN-SOS-09-E-005(a): single parameterised ``sos_regfile`` template
  (bus type is a generic/parameter), NOT two separate templates.
- PCDN-SOS-09-E-006(b): fire-on-write strobes are REGISTERED
  (one-cycle pulse aligned to the bus clock), not combinational.

Public surface:
    emit_regfile(annotations, *, peripheral_name, bus_type="axi4lite",
                 base_address=0x40000000, bus_clock_domain="bus") -> dict[str, str]
    emit_regfile_from_chart(chart_path, **kwargs) -> dict[str, str]
    Sos09RegfileError

Determinism: same ``ChartAnnotations`` in → byte-identical UTF-8 output.
Channels iterate in document order (``annotations.channels``); register
offsets follow the same dense 4-byte-aligned policy SOS-09-B uses, so
INV-S-MEM-E-6 (RTL offsets = SVD ``<addressOffset>`` byte-for-byte)
holds by construction.

@spec  SOS-09-E-CONCEPTS.md §5.1..§5.7 (frozen decisions)
@spec  SOS-09-E-CONCEPTS.md §6 INV-S-MEM-E-1..6 (invariants)
@spec  SOS-09-E-CONCEPTS.md §9 (a)..(i) (acceptance gates)
@spec  SOS-09-E-CONCEPTS.md §12 (b)..(l) (implementation gates)
@spec  SOS-09-A-CONCEPTS.md §5.2 (twelve-key set; consumed without modification)
@spec  SOS-09-B-CONCEPTS.md §5.3 (address-offset assignment; mirrored)
@spec  SOS-08-A-CONCEPTS.md §6 (L0 primitive contracts; composed unmodified)
@spec  SOS-08-B-CONCEPTS.md (sos_message_channel; composed for queue channels)
@spec  SOS-08-D-CONCEPTS.md (clock-domain declaration; drives sync insertion)
@spec  SOS-07-CONCEPTS.md §6 INV-SOS-A..H (cross-phase invariants)
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
from pathlib import Path
from typing import Any, Iterable, Optional

from sos09_annotations import (
    BitField,
    BitLayout,
    ChannelAnnotation,
    ChartAnnotations,
    parse_chart_annotations,
)


# ---------------------------------------------------------------------------
# Frozen value tokens (mirror SOS-09-E §5.1; do NOT extend without amendment)
# ---------------------------------------------------------------------------

# PCDN-SOS-09-E-001(a) — AXI4-Lite default; APB also supported.
BUS_AXI4LITE: str = "axi4lite"
BUS_APB: str = "apb"
ALLOWED_BUS_TYPES: frozenset[str] = frozenset({BUS_AXI4LITE, BUS_APB})
DEFAULT_BUS_TYPE: str = BUS_AXI4LITE

# Channel kinds we realise. Mirror of SOS-09-A `ALLOWED_KINDS`.
_KIND_STATUS: str = "status"
_KIND_COMMAND: str = "command"
_KIND_QUEUE: str = "queue"
_KIND_SHARED: str = "shared"

# Reserved-bit policy (PCDN-SOS-09-E-002(a) — read as 0, write ignored).
RESERVED_READ_VALUE: int = 0

# Default fall-back tokens for the channel-group / privilege-region
# inheritance walk (per SOS-09-A §5.2 amendment 2026-05-26: absence
# resolves to "default" at the consumer side — see §5.2 commentary).
DEFAULT_PRIVILEGE_REGION: str = "default"
DEFAULT_BUS_CLOCK_DOMAIN: str = "bus"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class Sos09RegfileError(Exception):
    """Raised on register-file emission failures.

    Carries an optional ``channel_id`` and ``rule`` (the SOS-09-E §
    number or INV-S-MEM-E-* citation that fired).
    """

    def __init__(
        self,
        message: str,
        *,
        channel_id: Optional[str] = None,
        rule: Optional[str] = None,
    ) -> None:
        self.channel_id = channel_id
        self.rule = rule
        prefix_parts: list[str] = []
        if rule:
            prefix_parts.append(f"[{rule}]")
        if channel_id:
            prefix_parts.append(f"channel={channel_id}")
        prefix = " ".join(prefix_parts)
        super().__init__(f"{prefix}: {message}" if prefix else message)


# ---------------------------------------------------------------------------
# Address-offset assignment (mirror of SOS-09-B §5.3)
# ---------------------------------------------------------------------------


def _channel_size_bytes(width_bits: int) -> int:
    """Bytes a channel occupies — 4-byte aligned per SOS-09-B §5.3.

    This MUST match ``transliterate_svd._channel_size_bytes`` byte-for-
    byte; INV-S-MEM-E-6 (SVD-offset = RTL-offset) is enforced by callers
    via the gate (h) cross-check, but the simplest way to keep them
    aligned is to share the policy.
    """
    if width_bits <= 0:
        raise Sos09RegfileError(
            f"channel width must be positive; got {width_bits}",
            rule="§5.3",
        )
    raw_bytes = (width_bits + 7) // 8
    return ((raw_bytes + 3) // 4) * 4


def _assign_offsets(channels: Iterable[ChannelAnnotation]) -> list[int]:
    """Return a parallel list of byte offsets for ``channels`` in doc order."""
    offsets: list[int] = []
    cursor = 0
    for ch in channels:
        offsets.append(cursor)
        cursor += _channel_size_bytes(ch.width)
    return offsets


# ---------------------------------------------------------------------------
# Per-channel view (Jinja2 template input)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BitFieldView:
    """Template-friendly bit-field shape.

    Carries the per-bit ``write_mask`` and ``read_mask`` boolean axes
    derived from ``access`` per SOS-09-E §5.3. Reserved/RO bits clear
    write_mask; reserved/WO bits clear read_mask.
    """

    name: str
    start_bit: int
    width: int
    access: str
    side_effect: Optional[str]
    reset_value: int
    # Derived per §5.3 — one boolean per bit *position*, not per bit
    # *index* — i.e. ``writable`` is True for all bits in [start_bit,
    # start_bit + width) when access ∈ {RW, WO}; ``readable`` is True
    # when access ∈ {RW, RO}.
    writable: bool
    readable: bool


@dataclass(frozen=True)
class ChannelView:
    """Template-friendly per-channel realisation view.

    All fields are pre-computed; the template only formats. This keeps
    INV-S-MEM-E-5 (bit-identical VHDL/SV) tractable because both
    templates consume the SAME view.
    """

    # Identity / position
    id: str                       # sos:id (UUID)
    name: str                     # SV identifier from sos:name
    kind: str                     # status / command / queue / shared
    dir: str                      # hw→sw / sw→hw / hw↔sw
    width: int                    # sos:width
    offset_bytes: int             # byte offset within peripheral
    index: int                    # 0-based doc-order index

    # Annotations
    zone: str                     # privileged / unprivileged
    atomicity: str                # atomic / mutex-required
    irq: Optional[str]
    mutex: Optional[str]
    channel_group: Optional[str]
    privilege_region: str         # resolved (absence → DEFAULT_PRIVILEGE_REGION)
    clock_domain: Optional[str]   # cross-domain marker; None = bus-domain
    cross_domain: bool            # True iff clock_domain != bus_clock_domain

    # Derived field tables (per §5.3)
    fields: tuple[BitFieldView, ...]
    write_mask: int               # bitmask: 1 = bus may write
    read_mask: int                # bitmask: 1 = bus reads bit; 0 reads zero
    reset_value: int
    reset_mask: int               # bitmask of all declared (non-reserved) bits

    # Behaviour flags
    has_clear_on_read: bool
    has_side_effect_on_write: bool

    # SV-safe identifier shortcuts used by templates
    @property
    def reg_offset_const(self) -> str:
        """Per-register byte-offset constant name (uppercased SV ident)."""
        return f"REG_OFFSET_{self.name.upper()}"

    @property
    def width_w(self) -> int:
        """Padded register width for the bus-side data slice.

        AXI4-Lite / APB are 32-bit at v1 (§5.1); a narrow channel
        (e.g. 16-bit) lives in the low bits of a 32-bit slot.
        """
        return 32 if self.width <= 32 else self.width


@dataclass(frozen=True)
class PrivilegeRegionView:
    """One privilege region — aggregates all access-violation strobes
    from the channels that share ``sos:privilege_region`` (or fall back
    to ``DEFAULT_PRIVILEGE_REGION`` when none is declared).

    Per PCDN-SOS-09-E-003(a): one ``sos_strobe_latch`` per region. Per
    §5.5: the latch's ``level_out`` surfaces as a chart-declared status
    channel for SW visibility — the template emits the OR-aggregation
    and the latch instance; the SW-side surfacing is a chart concern.
    """

    name: str                              # privilege_region identifier
    member_channel_names: tuple[str, ...]  # channels feeding this latch
    latch_inst: str                        # SV identifier for the latch instance
    violation_signal: str                  # aggregated violation strobe name


@dataclass(frozen=True)
class RegfileView:
    """Whole-`sos_regfile` template input."""

    peripheral_name: str
    bus_type: str                          # axi4lite / apb
    base_address: int
    bus_clock_domain: str
    channels: tuple[ChannelView, ...]
    privilege_regions: tuple[PrivilegeRegionView, ...]
    total_address_span_bytes: int

    # Witness fields the test suite consumes (acceptance gate (h)).
    svd_offset_map: tuple[tuple[str, int], ...]

    # PCDN citations rendered into header banners.
    pcdn_citations: tuple[str, ...] = (
        "PCDN-SOS-09-E-001(a) AXI4-Lite default",
        "PCDN-SOS-09-E-002(a) reserved bits read as zero",
        "PCDN-SOS-09-E-003(a) one strobe-latch per privilege_region",
        "PCDN-SOS-09-E-004(a) chart-declared cross-clock-domain channels",
        "PCDN-SOS-09-E-005(a) single parameterised template",
        "PCDN-SOS-09-E-006(b) registered fire-on-write strobe",
    )


# ---------------------------------------------------------------------------
# View construction
# ---------------------------------------------------------------------------


def _derive_field_view(field_decl: BitField) -> BitFieldView:
    """Map a ``BitField`` to its template view with masks derived per §5.3."""
    writable = field_decl.access in ("RW", "WO")
    readable = field_decl.access in ("RW", "RO")
    return BitFieldView(
        name=field_decl.name,
        start_bit=field_decl.start_bit,
        width=field_decl.width,
        access=field_decl.access,
        side_effect=field_decl.side_effect,
        reset_value=field_decl.reset_value,
        writable=writable,
        readable=readable,
    )


def _compute_masks(
    channel: ChannelAnnotation,
    field_views: tuple[BitFieldView, ...],
) -> tuple[int, int, int, int]:
    """Return (write_mask, read_mask, reset_value, reset_mask) per §5.3.

    For each declared field, OR its bit-position window into write_mask
    iff writable, into read_mask iff readable, into reset_mask
    unconditionally (the bit position is *declared*), and into
    reset_value masked by its declared reset_value. Reserved bits and
    gaps are absent from all masks — read returns 0, write ignored.
    """
    width = channel.width
    width_mask = (1 << width) - 1 if width < 64 else 0xFFFFFFFFFFFFFFFF
    write_mask = 0
    read_mask = 0
    reset_value = 0
    reset_mask = 0
    for fv in field_views:
        win = ((1 << fv.width) - 1) << fv.start_bit
        reset_mask |= win
        reset_value |= (fv.reset_value & ((1 << fv.width) - 1)) << fv.start_bit
        if fv.writable:
            write_mask |= win
        if fv.readable:
            read_mask |= win
    # If no fields were declared the channel is a flat flop bank; the
    # kind-axis access policy applies (per §5.2 and SOS-09-B).
    if not field_views:
        if channel.kind == _KIND_STATUS:
            read_mask = width_mask
            write_mask = 0
        elif channel.kind == _KIND_COMMAND:
            read_mask = 0
            write_mask = width_mask
        else:  # queue / shared
            read_mask = width_mask
            write_mask = width_mask
        reset_mask = width_mask
    return write_mask, read_mask, reset_value, reset_mask


def _resolve_clock_domain(
    channel: ChannelAnnotation,
    bus_clock_domain: str,
) -> tuple[Optional[str], bool]:
    """Return (clock_domain, cross_domain) for a channel.

    Per PCDN-SOS-09-E-004(a) the chart declares clock-domain assignments
    via ``<sos:clock_domains>`` (consumed by SOS-08-D); here we look at
    the channel's ``extras`` map for an optional ``sos:clock_domain``
    string and compare to ``bus_clock_domain``. Absence ⇒ same-domain.
    """
    raw = channel.extras.get("sos:clock_domain") if channel.extras else None
    if isinstance(raw, str) and raw and raw != bus_clock_domain:
        return raw, True
    return raw if isinstance(raw, str) else None, False


def _build_channel_view(
    channel: ChannelAnnotation,
    offset: int,
    index: int,
    bus_clock_domain: str,
) -> ChannelView:
    """Construct a per-channel template view."""
    if channel.bit_layout is not None:
        field_views = tuple(
            _derive_field_view(f) for f in channel.bit_layout.fields
        )
    else:
        field_views = ()

    write_mask, read_mask, reset_value, reset_mask = _compute_masks(
        channel, field_views
    )

    has_clear_on_read = any(
        f.side_effect == "clear-on-read" for f in field_views
    )
    has_side_effect_on_write = any(
        f.side_effect == "side-effect-on-write" for f in field_views
    )

    clock_domain, cross_domain = _resolve_clock_domain(
        channel, bus_clock_domain
    )

    privilege_region = (
        channel.privilege_region
        if channel.privilege_region is not None
        else DEFAULT_PRIVILEGE_REGION
    )

    return ChannelView(
        id=channel.id,
        name=channel.name,
        kind=channel.kind,
        dir=channel.dir,
        width=channel.width,
        offset_bytes=offset,
        index=index,
        zone=channel.zone,
        atomicity=channel.atomicity,
        irq=channel.irq,
        mutex=channel.mutex,
        channel_group=channel.channel_group,
        privilege_region=privilege_region,
        clock_domain=clock_domain,
        cross_domain=cross_domain,
        fields=field_views,
        write_mask=write_mask,
        read_mask=read_mask,
        reset_value=reset_value,
        reset_mask=reset_mask,
        has_clear_on_read=has_clear_on_read,
        has_side_effect_on_write=has_side_effect_on_write,
    )


def _build_privilege_regions(
    channels: tuple[ChannelView, ...],
) -> tuple[PrivilegeRegionView, ...]:
    """Group channels by ``privilege_region`` (PCDN-SOS-09-E-003(a))."""
    # Group order = first-seen channel order (deterministic).
    grouped: dict[str, list[ChannelView]] = {}
    for ch in channels:
        grouped.setdefault(ch.privilege_region, []).append(ch)

    regions: list[PrivilegeRegionView] = []
    for region_name, members in grouped.items():
        regions.append(
            PrivilegeRegionView(
                name=region_name,
                member_channel_names=tuple(m.name for m in members),
                latch_inst=f"u_violation_latch_{region_name}",
                violation_signal=f"violation_event_{region_name}",
            )
        )
    return tuple(regions)


def _build_regfile_view(
    annotations: ChartAnnotations,
    *,
    peripheral_name: str,
    bus_type: str,
    base_address: int,
    bus_clock_domain: str,
) -> RegfileView:
    """Walk annotations → RegfileView. Validates bus_type + grouping."""
    if bus_type not in ALLOWED_BUS_TYPES:
        raise Sos09RegfileError(
            f"bus_type {bus_type!r} not in {sorted(ALLOWED_BUS_TYPES)}",
            rule="§5.1",
        )
    if not peripheral_name or not isinstance(peripheral_name, str):
        raise Sos09RegfileError(
            f"peripheral_name must be a non-empty string; got {peripheral_name!r}",
            rule="§5.7",
        )
    if not isinstance(base_address, int) or base_address < 0:
        raise Sos09RegfileError(
            f"base_address must be a non-negative integer; got {base_address!r}",
            rule="§5.7",
        )

    offsets = _assign_offsets(annotations.channels)

    # INV-S-MEM-E-1: every register has exactly one decode line — duplicate
    # name → reject.
    seen_names: set[str] = set()
    for ch in annotations.channels:
        if ch.name in seen_names:
            raise Sos09RegfileError(
                f"duplicate channel name {ch.name!r}; one decode line per name",
                channel_id=ch.id,
                rule="INV-S-MEM-E-1",
            )
        seen_names.add(ch.name)

    channel_views = tuple(
        _build_channel_view(
            ch, off, idx, bus_clock_domain=bus_clock_domain,
        )
        for idx, (ch, off) in enumerate(zip(annotations.channels, offsets))
    )

    # INV-S-MEM-E-1 additional: detect duplicate offsets (defence in
    # depth — _assign_offsets is monotonic but a future width-of-0 bug
    # would surface here).
    offset_seen: set[int] = set()
    for ch in channel_views:
        if ch.offset_bytes in offset_seen:
            raise Sos09RegfileError(
                f"duplicate register byte-offset 0x{ch.offset_bytes:x} "
                f"at channel {ch.name!r}",
                channel_id=ch.id,
                rule="INV-S-MEM-E-1",
            )
        offset_seen.add(ch.offset_bytes)

    privilege_regions = _build_privilege_regions(channel_views)

    total_span = sum(_channel_size_bytes(ch.width) for ch in annotations.channels)
    if total_span == 0:
        total_span = 4  # SVD-emitter convention

    svd_offset_map = tuple((ch.name, ch.offset_bytes) for ch in channel_views)

    return RegfileView(
        peripheral_name=peripheral_name,
        bus_type=bus_type,
        base_address=base_address,
        bus_clock_domain=bus_clock_domain,
        channels=channel_views,
        privilege_regions=privilege_regions,
        total_address_span_bytes=total_span,
        svd_offset_map=svd_offset_map,
    )


# ---------------------------------------------------------------------------
# SVD-offset cross-check (gate (h) / INV-S-MEM-E-6)
# ---------------------------------------------------------------------------


def assert_svd_offsets_match(
    view: RegfileView,
    svd_offsets: dict[str, int],
) -> None:
    """Raise ``Sos09RegfileError`` if any channel's RTL offset disagrees
    with the SOS-09-B-emitted SVD ``<addressOffset>``.

    The check uses channel ``name`` as the join key (mirrors the SVD
    emitter's ``<register><name>`` mapping). Missing names are
    tolerated *only* if the SVD genuinely emits a subset (e.g. a future
    grouping policy); a present-on-both-sides mismatch is a build-stop.
    """
    for ch in view.channels:
        if ch.name not in svd_offsets:
            continue
        expected = svd_offsets[ch.name]
        if expected != ch.offset_bytes:
            raise Sos09RegfileError(
                f"INV-S-MEM-E-6 violation: channel {ch.name!r} RTL "
                f"offset 0x{ch.offset_bytes:x} != SVD offset 0x{expected:x}",
                channel_id=ch.id,
                rule="INV-S-MEM-E-6",
            )


# ---------------------------------------------------------------------------
# Public emit API
# ---------------------------------------------------------------------------


_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def _render(view: RegfileView, *, language: str) -> str:
    """Render the regfile module text via Jinja2.

    ``language`` is ``"vhdl"`` or ``"sv"`` — selects the template file
    (``sos_regfile.vhd.j2`` or ``sos_regfile.sv.j2``). Both templates
    consume the SAME ``view`` per INV-S-MEM-E-5.
    """
    try:
        from jinja2 import Environment, FileSystemLoader, StrictUndefined
    except ImportError as exc:  # pragma: no cover - jinja2 is a hard dep
        raise Sos09RegfileError(
            f"jinja2 is required for SOS-09-E emission ({exc})",
            rule="§5.7",
        ) from exc

    if language == "vhdl":
        template_name = "sos_regfile.vhd.j2"
    elif language == "sv":
        template_name = "sos_regfile.sv.j2"
    else:
        raise Sos09RegfileError(
            f"unknown language {language!r}; expected 'vhdl' or 'sv'",
            rule="§5.6",
        )

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        autoescape=False,  # plain text, never HTML
        trim_blocks=True,
        lstrip_blocks=True,
    )

    def _hex32(v: int) -> str:
        return f"32'h{v & 0xFFFFFFFF:08X}"

    def _hex32_vhdl(v: int) -> str:
        return f'x"{v & 0xFFFFFFFF:08X}"'

    env.filters["hex32"] = _hex32
    env.filters["hex32_vhdl"] = _hex32_vhdl

    template = env.get_template(template_name)
    return template.render(view=view)


def emit_regfile(
    annotations: ChartAnnotations,
    *,
    peripheral_name: str,
    bus_type: str = DEFAULT_BUS_TYPE,
    base_address: int = 0x40000000,
    bus_clock_domain: str = DEFAULT_BUS_CLOCK_DOMAIN,
) -> dict[str, str]:
    """Emit the regfile RTL in VHDL-2008 + SystemVerilog-2017.

    Args:
        annotations: parsed SOS-09-A annotation model. Channels emit in
            ``annotations.channels`` document order.
        peripheral_name: target peripheral / module-base name. MUST be
            a non-empty string; templates use it verbatim as the SV
            module / VHDL entity name (suffixed with ``_regfile``).
        bus_type: ``"axi4lite"`` (default, PCDN-SOS-09-E-001(a)) or
            ``"apb"``. Selects the bus-slave port set at elaboration
            time per PCDN-SOS-09-E-005(a).
        base_address: peripheral base address (informational; the
            bus-decode logic uses byte offsets relative to the slave
            port, not absolute addresses).
        bus_clock_domain: name of the bus-side clock domain. Channels
            whose ``sos:clock_domain`` differs trigger automatic
            ``sos_synchronizer`` insertion per PCDN-SOS-09-E-004(a).

    Returns:
        ``{"sos_regfile_<peripheral>.vhd": <VHDL text>,
           "sos_regfile_<peripheral>.sv":  <SV text>}``.

    Raises:
        Sos09RegfileError: validation failure (duplicate name/offset,
            unknown bus type, etc.).
    """
    view = _build_regfile_view(
        annotations,
        peripheral_name=peripheral_name,
        bus_type=bus_type,
        base_address=base_address,
        bus_clock_domain=bus_clock_domain,
    )
    vhd_text = _render(view, language="vhdl")
    sv_text = _render(view, language="sv")
    return {
        f"sos_regfile_{peripheral_name}.vhd": vhd_text,
        f"sos_regfile_{peripheral_name}.sv": sv_text,
    }


def emit_regfile_from_chart(
    chart_path: str | Path,
    **kwargs,
) -> dict[str, str]:
    """Loader → annotations parser → regfile emitter convenience wrapper."""
    from loader import load_chart  # noqa: WPS433 - lazy

    ast = load_chart(Path(chart_path))
    if ast.raw_scjson is None:
        raise Sos09RegfileError(
            f"loader returned ChartAst without raw_scjson for {chart_path!r}",
            rule="§5.7",
        )
    annotations = parse_chart_annotations(ast.raw_scjson)
    return emit_regfile(annotations, **kwargs)


# ---------------------------------------------------------------------------
# Convenience accessor for the walker integration (gate (j) `@spec` cite)
# ---------------------------------------------------------------------------


def build_view(
    annotations: ChartAnnotations,
    *,
    peripheral_name: str,
    bus_type: str = DEFAULT_BUS_TYPE,
    base_address: int = 0x40000000,
    bus_clock_domain: str = DEFAULT_BUS_CLOCK_DOMAIN,
) -> RegfileView:
    """Expose the constructed view for inspection / cross-check tests."""
    return _build_regfile_view(
        annotations,
        peripheral_name=peripheral_name,
        bus_type=bus_type,
        base_address=base_address,
        bus_clock_domain=bus_clock_domain,
    )


__all__ = [
    "ALLOWED_BUS_TYPES",
    "BUS_APB",
    "BUS_AXI4LITE",
    "BitFieldView",
    "ChannelView",
    "DEFAULT_BUS_CLOCK_DOMAIN",
    "DEFAULT_BUS_TYPE",
    "DEFAULT_PRIVILEGE_REGION",
    "PrivilegeRegionView",
    "RegfileView",
    "RESERVED_READ_VALUE",
    "Sos09RegfileError",
    "assert_svd_offsets_match",
    "build_view",
    "emit_regfile",
    "emit_regfile_from_chart",
]
