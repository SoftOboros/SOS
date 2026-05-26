"""SOS-09-G MPU configuration emitter.

Derives ARMv7-M MPU region descriptors from a parsed
:class:`~sos09_annotations.ChartAnnotations` model (the SOS-09-A
authoritative input contract), then emits a C array and a Rust constant
that the `sos_mpu_install()` runtime consumes at startup.

Authority: ``docs/concepts/SOS-09-G-CONCEPTS.md`` (ratified 2026-05-25).
This module IS the implementation of SOS-09-G's emission surface
(§5.2 region-descriptor shape, §5.3 emission outputs, §5.4 SRD policy,
§5.5 ``sos_mpu_install`` enable invariant via the
``mpu_background`` chart-root toggle, §7 INV-S-MEM-G-1..4).

Public surface:
    MpuRegion
    derive_mpu_regions(annotations, *, base_address=0x40000000)
    emit_mpu_c(regions, *, table_name="sos_mpu_regions")
    emit_mpu_rust(regions, *, const_name="SOS_MPU_REGIONS")
    emit_mpu_background_setting(annotations)
    Sos09MpuError

Invariants enforced (per §7 of SOS-09-G-CONCEPTS.md):
    INV-S-MEM-G-1  every channel with zone="privileged" → AP=priv-only
    INV-S-MEM-G-2  region sized to power-of-two ≥ channel footprint
    INV-S-MEM-G-3  emission is deterministic (idempotency at the install
                   layer is enforced by the runtime, but the table itself
                   must be byte-identical across re-emits)
    INV-S-MEM-G-4  overlapping regions (post-rounding) are a hard error

Determinism note: same `ChartAnnotations` in → byte-identical output. No
floating-point, no dict-ordering, no time-based fields. Channels are
processed in `annotations.channels` order (already document-order from
the SOS-09-A walker).
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

from dataclasses import dataclass
from typing import Iterable

from sos09_annotations import ChannelAnnotation, ChartAnnotations


# ---------------------------------------------------------------------------
# Frozen value tokens (mirrors the §5.2 attribute / §5.4 access enumeration)
# ---------------------------------------------------------------------------

# Two attribute classes covered by the v1 emitter (per the SOS-09-G §5.2
# narrowed-scope ratification 2026-05-25). The four chart-author override
# tokens collapse onto these two values at v1; the future "more general
# vendor support pass" (per PCDN-SOS-09-G-004's deferred extension) widens
# them into the full ARMv7-M attribute matrix.
ATTR_DEVICE_NGNRNE: str = "device-nGnRnE"
ATTR_NORMAL_WB_WA: str = "normal-wb-wa"
ALLOWED_ATTRS: frozenset[str] = frozenset({ATTR_DEVICE_NGNRNE, ATTR_NORMAL_WB_WA})

# AP[2:0] encoding tokens per ARM DDI 0403E.e B3.5.6 Table B3-15.
# Privileged-only RW (AP=0b001) — the default for zone="privileged" channels;
# privileged RW + unprivileged RO (AP=0b010) — reserved for future read-share
# affordances; full RW (AP=0b011) — for zone="unprivileged".
ACCESS_PRIV_RW_UNPRIV_NONE: str = "priv-rw-unpriv-none"   # AP=0b001
ACCESS_PRIV_RW_UNPRIV_RO: str = "priv-rw-unpriv-ro"       # AP=0b010
ACCESS_PRIV_RW_UNPRIV_RW: str = "priv-rw-unpriv-rw"       # AP=0b011
ALLOWED_ACCESS: frozenset[str] = frozenset(
    {
        ACCESS_PRIV_RW_UNPRIV_NONE,
        ACCESS_PRIV_RW_UNPRIV_RO,
        ACCESS_PRIV_RW_UNPRIV_RW,
    }
)

# Per-channel override token → emitter attribute mapping. PCDN-SOS-09-G-003
# ratification (2026-05-25) permits four input values; the v1 emitter
# collapses each onto one of the two attribute classes.
_MPU_ATTR_OVERRIDE_MAP: dict[str, str] = {
    "cacheable": ATTR_NORMAL_WB_WA,
    "non_cacheable": ATTR_NORMAL_WB_WA,
    "device_ngnrne": ATTR_DEVICE_NGNRNE,
    "device_ngnre": ATTR_DEVICE_NGNRNE,
}

# §5.2: kind-default attribute. Register channels get strongly-ordered
# Device memory; only `shared` channels (their datamodel scope) default to
# Normal Cacheable so the MPU-protected side can participate in cacheable
# operations on the DPRAM-backed shared region.
_DEFAULT_ATTR_BY_KIND: dict[str, str] = {
    "status": ATTR_DEVICE_NGNRNE,
    "command": ATTR_DEVICE_NGNRNE,
    "queue": ATTR_DEVICE_NGNRNE,
    "shared": ATTR_NORMAL_WB_WA,
}

# Minimum / maximum MPU region size, expressed as raw log2(bytes) per the
# ``MpuRegion.size_log2`` field shape. The ARMv7-M MPU's MPU_RASR.SIZE
# field encodes ``log2(bytes) - 1``, so the wire-level encoding range is
# 4..31; the in-memory ``size_log2`` we expose is one larger (5..32).
# 32 B is the architectural minimum region size per ARM DDI 0403E.e B3.5;
# 4 GB is the architectural maximum.
MIN_SIZE_LOG2: int = 5    # 2**5  = 32 B
MAX_SIZE_LOG2: int = 32   # 2**32 = 4 GB

# Minimum address-granularity for channel allocation. Even narrow channels
# (8-bit, 16-bit) occupy ≥ 4 bytes of address space at the SVD layout,
# matching the SOS-09-B emitter spec.
_MIN_CHANNEL_BYTES: int = 4


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class Sos09MpuError(Exception):
    """Raised on MPU region derivation / emission failures.

    Carries an optional ``channel_id`` (sos:id UUID of the offending
    channel) and ``rule`` token (which §7 invariant or §5.x decision
    was violated).
    """

    def __init__(
        self,
        message: str,
        *,
        channel_id: str | None = None,
        rule: str | None = None,
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
# Public dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MpuRegion:
    """One MPU region descriptor — language-agnostic intermediate form.

    Fields mirror the C struct ``sos_mpu_region_t`` and Rust struct
    ``MpuRegion`` defined in SOS-09-G §5.3; this is the language-neutral
    pivot the C and Rust emitters share.

    ``size_log2`` is the raw ``log2(size_in_bytes)`` of the MPU region
    (i.e. the region's byte size is ``2 ** size_log2``). The ARMv7-M
    ``MPU_RASR.SIZE`` field encodes ``log2(bytes) - 1``, so the runtime
    writes ``size_log2 - 1`` into that field. Storing the raw log makes
    address-alignment arithmetic ``region.base & ((1 << size_log2) - 1)``
    read naturally; the runtime adapts at the wire boundary.

    Valid range: ``MIN_SIZE_LOG2`` (5 → 32 B) to ``MAX_SIZE_LOG2``
    (32 → 4 GB).
    """

    name: str            # SV-identifier; derived from channel.name
    base_address: int    # byte address; aligned to 2**size_log2
    size_log2: int       # raw log2(size in bytes); 5..32 valid (32 B..4 GB)
    attr: str            # one of ALLOWED_ATTRS; per §5.2
    access: str          # one of ALLOWED_ACCESS; derived from zone
    xn: bool = True      # execute-never; True for register + datamodel regions
    enable: bool = True
    channel_id: str = ""  # originating sos:id UUID (traceability)
    srd: int = 0          # sub-region disable bitmap (0 at v1; §5.4)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _channel_footprint_bytes(channel: ChannelAnnotation) -> int:
    """Return the natural byte footprint of a channel's register surface.

    Per SOS-09-B's layout rule (mirrored from the SVD emitter spec):
    ``ceil(width/8)`` then rounded up to a 4-byte minimum so even narrow
    channels (1-bit, 8-bit) get a 32-bit register slot. Shared channels
    keep the same minimum at v1 — their full datamodel-scope region size
    is derived from the natural footprint and rounded up to MPU alignment
    by the size-log2 helper below.
    """
    raw = (channel.width + 7) // 8
    if raw < _MIN_CHANNEL_BYTES:
        return _MIN_CHANNEL_BYTES
    return raw


def _size_log2_for(byte_footprint: int) -> int:
    """Return SIZE field value (log2(bytes)) for the smallest MPU region
    enclosing ``byte_footprint``. Result satisfies
    ``MIN_SIZE_LOG2 <= result <= MAX_SIZE_LOG2`` and
    ``2**result >= byte_footprint``.
    """
    if byte_footprint <= 0:
        raise Sos09MpuError(
            f"channel footprint must be > 0; got {byte_footprint}",
            rule="§5.2",
        )
    # ceil(log2(byte_footprint)).
    size_log2 = 0
    n = 1
    while n < byte_footprint:
        n <<= 1
        size_log2 += 1
    if size_log2 < MIN_SIZE_LOG2:
        return MIN_SIZE_LOG2
    if size_log2 > MAX_SIZE_LOG2:
        raise Sos09MpuError(
            f"channel footprint {byte_footprint} bytes exceeds the ARMv7-M "
            f"MPU maximum region size (2**{MAX_SIZE_LOG2}); reduce sos:width "
            f"or split the channel",
            rule="§5.2",
        )
    return size_log2


def _align_up(value: int, alignment: int) -> int:
    """Round ``value`` up to the next multiple of ``alignment`` (a power of two)."""
    if alignment <= 0:
        raise ValueError("alignment must be positive")
    mask = alignment - 1
    return (value + mask) & ~mask


def _derive_attr(channel: ChannelAnnotation) -> str:
    """Resolve the channel's MPU attribute per §5.2.

    Default-by-kind; chart-author ``sos:mpu_attr`` override (already
    validated by ``sos09_annotations.parse_chart_annotations``) trumps the
    kind default.
    """
    if channel.mpu_attr is not None:
        mapped = _MPU_ATTR_OVERRIDE_MAP.get(channel.mpu_attr)
        if mapped is None:
            # Defence-in-depth — `parse_chart_annotations` rejects unknown
            # values, but if a caller bypasses the parser we still refuse to
            # emit junk.
            raise Sos09MpuError(
                f"sos:mpu_attr value {channel.mpu_attr!r} is not a recognised "
                f"override token (expected one of "
                f"{sorted(_MPU_ATTR_OVERRIDE_MAP)})",
                channel_id=channel.id,
                rule="§5.2",
            )
        return mapped
    default = _DEFAULT_ATTR_BY_KIND.get(channel.kind)
    if default is None:
        raise Sos09MpuError(
            f"unknown channel kind {channel.kind!r}; expected one of "
            f"{sorted(_DEFAULT_ATTR_BY_KIND)}",
            channel_id=channel.id,
            rule="§5.2",
        )
    return default


def _derive_access(channel: ChannelAnnotation) -> str:
    """Resolve the channel's AP encoding per §5.2.

    zone="privileged"   → priv-rw-unpriv-none (AP=0b001)
    zone="unprivileged" → priv-rw-unpriv-rw   (AP=0b011)
    """
    if channel.zone == "privileged":
        return ACCESS_PRIV_RW_UNPRIV_NONE
    if channel.zone == "unprivileged":
        return ACCESS_PRIV_RW_UNPRIV_RW
    raise Sos09MpuError(
        f"unknown channel zone {channel.zone!r}; expected one of "
        f"{{'privileged', 'unprivileged'}}",
        channel_id=channel.id,
        rule="§5.2",
    )


def _check_no_overlap(regions: Iterable[MpuRegion]) -> None:
    """Verify regions do not overlap (post-alignment).

    INV-S-MEM-G-4 (overlap → hard error). Two channels that would map to
    the same MPU region are a chart-author error: the chart-walk allocator
    cannot make them disjoint without changing the chart's address
    geometry.
    """
    regions_sorted = sorted(regions, key=lambda r: r.base_address)
    for i in range(1, len(regions_sorted)):
        prev = regions_sorted[i - 1]
        cur = regions_sorted[i]
        prev_end = prev.base_address + (1 << prev.size_log2)
        if cur.base_address < prev_end:
            raise Sos09MpuError(
                f"MPU regions overlap: {prev.name!r} "
                f"[0x{prev.base_address:08X}..0x{prev_end:08X}) and "
                f"{cur.name!r} "
                f"[0x{cur.base_address:08X}..0x{cur.base_address + (1 << cur.size_log2):08X})",
                channel_id=cur.channel_id,
                rule="INV-S-MEM-G-4",
            )


def _address_for_channel(
    channels: tuple[ChannelAnnotation, ...],
    idx: int,
    *,
    base_address: int,
) -> tuple[int, int]:
    """Compute ``(base_addr, size_log2)`` for the ``idx``-th channel.

    Algorithm (canonical — MUST match SOS-09-B's SVD-emitter layout when
    that emitter lands): chart-walk order × per-channel footprint, padded
    up so each region's base is aligned to its own size_log2 power of two.

    Returns the aligned ``base_addr`` and the ``size_log2`` for use in
    ``MpuRegion`` construction.

    The cursor starts at ``base_address`` and after each channel advances
    by ``2 ** size_log2`` of THAT channel (post-alignment). This gives a
    deterministic, chart-walk-order layout where every channel occupies
    exactly its own power-of-two region with no gaps beyond the alignment
    padding the architecture demands.
    """
    cursor = base_address
    for i in range(idx):
        prev_size_log2 = _size_log2_for(_channel_footprint_bytes(channels[i]))
        cursor = _align_up(cursor, 1 << prev_size_log2)
        cursor += 1 << prev_size_log2
    this_size_log2 = _size_log2_for(_channel_footprint_bytes(channels[idx]))
    aligned = _align_up(cursor, 1 << this_size_log2)
    return aligned, this_size_log2


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def derive_mpu_regions(
    annotations: ChartAnnotations,
    *,
    base_address: int = 0x40000000,
) -> tuple[MpuRegion, ...]:
    """Derive MPU regions from a parsed annotation set.

    Per SOS-09-G §5.2 coverage scope (PCDN-G-003 narrowed-scope
    ratification 2026-05-25):

    - Register channels (kind ∈ {status, command, queue}) each get a
      Device-nGnRnE region by default; ``sos:mpu_attr`` override flips the
      attribute per ``_MPU_ATTR_OVERRIDE_MAP``.
    - Shared channels (kind = shared) each get a single Normal Cacheable
      region (the datamodel-scope region) by default; ``sos:mpu_attr``
      override flips the attribute.
    - zone="privileged" → AP=0b001 (priv-rw-unpriv-none).
    - zone="unprivileged" → AP=0b011 (priv-rw-unpriv-rw).
    - XN=1 for all emitted regions (register-mapped peripherals + shared
      datamodel are not code).

    Address layout: chart-walk order; each region's base aligned to its
    own size_log2 power of two; no overlap (INV-S-MEM-G-4).

    ``base_address`` is the starting cursor; defaults to ``0x40000000``
    (the standard ARMv7-M peripheral address window). Callers MAY pass a
    different base when emitting into SRAM (e.g. ``0x20000000``) — the
    chart's protection topology is independent of the start address.
    """
    if not isinstance(annotations, ChartAnnotations):
        raise Sos09MpuError(
            f"annotations must be a ChartAnnotations; got "
            f"{type(annotations).__name__}",
            rule="parse",
        )

    channels = annotations.channels
    regions: list[MpuRegion] = []
    for idx, channel in enumerate(channels):
        base_addr, size_log2 = _address_for_channel(
            channels, idx, base_address=base_address,
        )
        attr = _derive_attr(channel)
        access = _derive_access(channel)
        regions.append(
            MpuRegion(
                name=channel.name,
                base_address=base_addr,
                size_log2=size_log2,
                attr=attr,
                access=access,
                xn=True,
                enable=True,
                channel_id=channel.id,
                srd=0,
            )
        )

    _check_no_overlap(regions)
    return tuple(regions)


def _attr_c_token(attr: str) -> str:
    """Return the C-macro token for an attribute value."""
    if attr == ATTR_DEVICE_NGNRNE:
        return "SOS_MPU_ATTR_DEVICE_NGNRNE"
    if attr == ATTR_NORMAL_WB_WA:
        return "SOS_MPU_ATTR_NORMAL_WB_WA"
    raise Sos09MpuError(f"unrecognised attr {attr!r}", rule="emit")


def _access_c_token(access: str) -> str:
    if access == ACCESS_PRIV_RW_UNPRIV_NONE:
        return "SOS_MPU_AP_PRIV_RW_UNPRIV_NONE"
    if access == ACCESS_PRIV_RW_UNPRIV_RO:
        return "SOS_MPU_AP_PRIV_RW_UNPRIV_RO"
    if access == ACCESS_PRIV_RW_UNPRIV_RW:
        return "SOS_MPU_AP_PRIV_RW_UNPRIV_RW"
    raise Sos09MpuError(f"unrecognised access {access!r}", rule="emit")


def _attr_rust_token(attr: str) -> str:
    if attr == ATTR_DEVICE_NGNRNE:
        return "MpuAttr::DeviceNGnRnE"
    if attr == ATTR_NORMAL_WB_WA:
        return "MpuAttr::NormalWbWa"
    raise Sos09MpuError(f"unrecognised attr {attr!r}", rule="emit")


def _access_rust_token(access: str) -> str:
    if access == ACCESS_PRIV_RW_UNPRIV_NONE:
        return "MpuAccess::PrivRwUnprivNone"
    if access == ACCESS_PRIV_RW_UNPRIV_RO:
        return "MpuAccess::PrivRwUnprivRo"
    if access == ACCESS_PRIV_RW_UNPRIV_RW:
        return "MpuAccess::PrivRwUnprivRw"
    raise Sos09MpuError(f"unrecognised access {access!r}", rule="emit")


def emit_mpu_c(
    regions: tuple[MpuRegion, ...],
    *,
    table_name: str = "sos_mpu_regions",
) -> str:
    """Emit a complete C source file declaring the MPU region table.

    Includes ``sos_mpu.h`` (where the struct type and the attribute /
    access ``#define`` tokens live), defines
    ``const sos_mpu_region_t <table_name>[] = { ... };``, and a
    ``const size_t <table_name>_count = N;`` length constant.

    Output is deterministic — same regions in → byte-identical output.
    """
    if not _is_sv_identifier(table_name):
        raise Sos09MpuError(
            f"table_name {table_name!r} must be an SV identifier",
            rule="emit",
        )

    lines: list[str] = [
        "/* SOS-09-G MPU region table — auto-generated. Do not edit by hand. */",
        '#include "sos_mpu.h"',
        "",
        f"const sos_mpu_region_t {table_name}[] = {{",
    ]
    for region in regions:
        lines.extend(_emit_c_row(region))
    lines.append("};")
    lines.append("")
    lines.append(
        f"const size_t {table_name}_count = "
        f"sizeof({table_name}) / sizeof({table_name}[0]);"
    )
    lines.append("")
    return "\n".join(lines)


def _emit_c_row(region: MpuRegion) -> list[str]:
    return [
        "    {",
        f"        .name = \"{region.name}\",",
        f"        .base_address = 0x{region.base_address:08X}u,",
        f"        .size_log2 = {region.size_log2}u,",
        f"        .attr = {_attr_c_token(region.attr)},",
        f"        .access = {_access_c_token(region.access)},",
        f"        .xn = {'1' if region.xn else '0'},",
        f"        .enable = {'1' if region.enable else '0'},",
        f"        .srd = 0x{region.srd:02X}u,",
        f"        .channel_id = \"{region.channel_id}\",",
        "    },",
    ]


def emit_mpu_rust(
    regions: tuple[MpuRegion, ...],
    *,
    const_name: str = "SOS_MPU_REGIONS",
) -> str:
    """Emit a Rust module-fragment declaring the MPU region constant.

    The ``MpuRegion`` struct (and the ``MpuAttr`` / ``MpuAccess`` enums)
    live in a sibling ``sos_mpu`` crate — this emitter provides the
    constant only. Caller is responsible for ``use sos_mpu::{...};`` at
    the top of the file that includes the emitted fragment.

    Output is deterministic — same regions in → byte-identical output.
    """
    if not _is_sv_identifier_caps(const_name):
        raise Sos09MpuError(
            f"const_name {const_name!r} must be an UPPER_SNAKE_CASE identifier",
            rule="emit",
        )

    lines: list[str] = [
        "// SOS-09-G MPU region table — auto-generated. Do not edit by hand.",
        "use sos_mpu::{MpuAccess, MpuAttr, MpuRegion};",
        "",
        f"pub const {const_name}: &[MpuRegion] = &[",
    ]
    for region in regions:
        lines.extend(_emit_rust_row(region))
    lines.append("];")
    lines.append("")
    return "\n".join(lines)


def _emit_rust_row(region: MpuRegion) -> list[str]:
    return [
        "    MpuRegion {",
        f"        name: \"{region.name}\",",
        f"        base_address: 0x{region.base_address:08X},",
        f"        size_log2: {region.size_log2},",
        f"        attr: {_attr_rust_token(region.attr)},",
        f"        access: {_access_rust_token(region.access)},",
        f"        xn: {'true' if region.xn else 'false'},",
        f"        enable: {'true' if region.enable else 'false'},",
        f"        srd: 0x{region.srd:02X},",
        f"        channel_id: \"{region.channel_id}\",",
        "    },",
    ]


def emit_mpu_background_setting(annotations: ChartAnnotations) -> dict[str, str]:
    """Emit the language-pair declaration for ``PRIVDEFENA``.

    Per §5.5 ``sos_mpu_install`` step 4: the runtime reads the chart's
    ``sos:mpu_background`` value to decide whether to set ``PRIVDEFENA=1``
    (the kernel-default case, also the absent-key default) or
    ``PRIVDEFENA=0`` (the strict case — every kernel access must lie in an
    explicit region).

    Returns a dict with two keys:
        ``c_define``  — a complete ``#define`` line for the C side.
        ``rust_const`` — a complete ``pub const`` line for the Rust side.
    """
    if not isinstance(annotations, ChartAnnotations):
        raise Sos09MpuError(
            f"annotations must be a ChartAnnotations; got "
            f"{type(annotations).__name__}",
            rule="parse",
        )
    background = annotations.mpu_background
    if background == "kernel_default":
        bit = 1
        rust_bool = "true"
    elif background == "strict":
        bit = 0
        rust_bool = "false"
    else:
        # Defence-in-depth — parser rejects this, but make the emitter
        # safe-by-construction.
        raise Sos09MpuError(
            f"unrecognised mpu_background {background!r}; expected one of "
            f"{{'kernel_default', 'strict'}}",
            rule="§5.5",
        )
    return {
        "c_define": f"#define SOS_MPU_BACKGROUND_PRIVDEFENA {bit}",
        "rust_const": f"pub const SOS_MPU_BACKGROUND_PRIVDEFENA: bool = {rust_bool};",
    }


# ---------------------------------------------------------------------------
# Identifier helpers — local re-implementation to avoid coupling to
# `sos09_annotations`'s private regex
# ---------------------------------------------------------------------------


def _is_sv_identifier(s: str) -> bool:
    if not s or not isinstance(s, str):
        return False
    if not (s[0].isalpha() or s[0] == "_"):
        return False
    return all(c.isalnum() or c == "_" for c in s)


def _is_sv_identifier_caps(s: str) -> bool:
    """Like ``_is_sv_identifier`` but also rejects lower-case letters.

    Used for Rust const-name validation; idiomatic Rust constants are
    SCREAMING_SNAKE_CASE.
    """
    if not _is_sv_identifier(s):
        return False
    return all(not c.isalpha() or c.isupper() or c == "_" for c in s)


__all__ = [
    "ATTR_DEVICE_NGNRNE",
    "ATTR_NORMAL_WB_WA",
    "ALLOWED_ATTRS",
    "ACCESS_PRIV_RW_UNPRIV_NONE",
    "ACCESS_PRIV_RW_UNPRIV_RO",
    "ACCESS_PRIV_RW_UNPRIV_RW",
    "ALLOWED_ACCESS",
    "MIN_SIZE_LOG2",
    "MAX_SIZE_LOG2",
    "MpuRegion",
    "Sos09MpuError",
    "derive_mpu_regions",
    "emit_mpu_c",
    "emit_mpu_rust",
    "emit_mpu_background_setting",
]
