"""SOS-09-B CMSIS-SVD emitter.

Walks a :class:`~sos09_annotations.ChartAnnotations` model (the SOS-09-A
authoritative input contract) and emits a CMSIS-SVD 1.3 XML document
describing the SOS channels as a single peripheral whose registers map to
channels and whose register fields map to ``sos:bit_layout`` entries.

Authority: ``docs/concepts/SOS-09-B-CONCEPTS.md`` (ratified 2026-05-25);
sub-phase of the SOS-09 umbrella (``docs/concepts/SOS-09-CONCEPTS.md``).
Input contract is owned by SOS-09-A (``sos09_annotations.py``); this
module is a *consumer* of that contract and MUST NOT redefine the types
or value grammars exposed there.

Public surface:
    emit_svd(annotations, *, device_name, base_address=0x40000000,
             peripheral_grouping="one") -> str
    emit_svd_from_chart(chart_path, **kwargs) -> str

Determinism: same ``ChartAnnotations`` in -> byte-identical UTF-8 output.
No timestamps, no clock-derived nonces, no dict-ordering. Channels are
emitted in document order (``annotations.channels`` preserves the
SOS-09-A walker's depth-first ordering).

Mapping rules (per SOS-09-B-CONCEPTS §5.x):

- ``<peripheral><name>`` = ``device_name`` (SV-identifier, validated).
- ``<peripheral><baseAddress>`` = ``base_address`` (default 0x40000000).
- One ``<register>`` per :class:`ChannelAnnotation`, in walk order.
  - ``<name>`` = channel.name
  - ``<addressOffset>`` = walk-index * ceil(width_bytes) rounded up to
    4-byte alignment (cumulative, monotonic).
  - ``<size>`` = channel.width bits.
  - ``<access>`` derived from channel.kind:
        status   -> read-only
        command  -> write-only
        queue    -> read-write
        shared   -> read-write
  - ``<readAction>clear</readAction>`` emitted iff any field in
    ``bit_layout.fields`` has ``side_effect == "clear-on-read"``.
  - ``<resetValue>`` / ``<resetMask>`` derived from bit_layout (OR of
    ``(reset_value << start_bit)`` and ``((1<<width)-1) << start_bit``).
    No bit_layout -> resetValue=0, resetMask= ``(1<<channel.width)-1``.
- One ``<field>`` per :class:`BitField` (lowercased name):
  - ``<bitOffset>`` = field.start_bit
  - ``<bitWidth>`` = field.width
  - ``<access>`` mapped from field.access:
        RW       -> read-write
        RO       -> read-only
        WO       -> write-only
        reserved -> read-only
- Per-channel IRQ: when ``channel.irq is not None``, emit
  ``<interrupt><name>...</name><value>N</value></interrupt>`` on the
  peripheral with ``N`` = sequential index of irq-bearing channels in
  chart-walk order (0, 1, 2, ...). This is the v1 placeholder per
  PCDN-SOS-09-B-004 (deferred: vendor-vector-table integration).

Validation:
- ``device_name`` MUST match the SV-identifier regex
  (``[a-zA-Z_][a-zA-Z0-9_]*``). Otherwise ``ValueError``.
- ``peripheral_grouping="per-channel-group"`` is reserved for a future
  sub-phase per PCDN-SOS-09-B-002 and raises ``NotImplementedError``.
- Only ``peripheral_grouping="one"`` is supported at v1.
"""

from __future__ import annotations

import re
import xml.dom.minidom
from pathlib import Path
from typing import Iterable, Optional
from xml.etree import ElementTree as ET

from sos09_annotations import (
    BitField,
    BitLayout,
    ChannelAnnotation,
    ChartAnnotations,
    parse_chart_annotations,
)


# ---------------------------------------------------------------------------
# Frozen mappings (mirror, do not redefine, SOS-09-A enum values)
# ---------------------------------------------------------------------------

# Channel.kind -> SVD register <access> token (CMSIS-SVD 1.3 §schema).
_KIND_TO_SVD_ACCESS: dict[str, str] = {
    "status": "read-only",
    "command": "write-only",
    "queue": "read-write",
    "shared": "read-write",
}

# BitField.access (SOS-09-A §5.4(3) enum) -> SVD <access> token.
_FIELD_ACCESS_TO_SVD: dict[str, str] = {
    "RW": "read-write",
    "RO": "read-only",
    "WO": "write-only",
    "reserved": "read-only",
}

# SV identifier (IEEE 1800-2017 §5.6). Repeated locally rather than
# imported from sos09_annotations._SV_IDENTIFIER_RE — that name is
# underscore-prefixed and not part of the public surface.
_SV_IDENTIFIER_RE: re.Pattern[str] = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _channel_size_bytes(width_bits: int) -> int:
    """Bytes needed to hold ``width_bits``, rounded up to 4-byte alignment.

    The SVD ``addressOffset`` is byte-addressed, so a 16-bit channel still
    occupies a 4-byte slot for the next channel's alignment. This matches
    the typical M-profile MMIO layout.
    """
    if width_bits <= 0:
        raise ValueError(f"channel width must be positive; got {width_bits}")
    raw_bytes = (width_bits + 7) // 8
    # Round up to 4-byte alignment.
    return ((raw_bytes + 3) // 4) * 4


def _compute_reset(channel: ChannelAnnotation) -> tuple[int, int]:
    """Return ``(resetValue, resetMask)`` for one channel.

    With a bit_layout, both are OR-reductions over the field tuple. Without
    a bit_layout, ``resetValue`` is 0 and ``resetMask`` is the full
    ``channel.width`` mask (e.g. 0xFFFFFFFF for 32-bit).
    """
    if channel.bit_layout is None:
        full_mask = (1 << channel.width) - 1 if channel.width < 64 else 0xFFFFFFFFFFFFFFFF
        # Special-case 32 since most callers expect the exact width mask;
        # any width <= 64 falls into the generic path.
        if channel.width >= 64:
            full_mask = 0xFFFFFFFFFFFFFFFF
        return 0, full_mask

    reset_value = 0
    reset_mask = 0
    for f in channel.bit_layout.fields:
        field_mask = ((1 << f.width) - 1) << f.start_bit
        reset_mask |= field_mask
        reset_value |= (f.reset_value & ((1 << f.width) - 1)) << f.start_bit
    return reset_value, reset_mask


def _has_clear_on_read(channel: ChannelAnnotation) -> bool:
    """True iff any field in the channel's layout is clear-on-read."""
    if channel.bit_layout is None:
        return False
    return any(f.side_effect == "clear-on-read" for f in channel.bit_layout.fields)


def _hex_word(value: int, *, bits: int = 32) -> str:
    """Format an unsigned integer as ``0x...`` hex, width-sized for SVD.

    SVD allows ``0x``-prefixed hex; we pad to the channel width nibble
    count so output diffs are visually aligned across channels of the
    same width.
    """
    nibbles = max(1, (bits + 3) // 4)
    return f"0x{value:0{nibbles}X}"


def _sub_text(parent: ET.Element, tag: str, text: str) -> ET.Element:
    """Append a child element with text content; returns the child."""
    el = ET.SubElement(parent, tag)
    el.text = text
    return el


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def emit_svd(
    annotations: ChartAnnotations,
    *,
    device_name: str,
    base_address: int = 0x40000000,
    peripheral_grouping: str = "one",
) -> str:
    """Emit a CMSIS-SVD 1.3 XML document for the given channels.

    Args:
        annotations: parsed SOS-09-A annotation model. Channels are
            emitted in the order ``annotations.channels`` lists them
            (already document order from the SOS-09-A walker).
        device_name: peripheral / device name. MUST be an SV identifier
            (``[a-zA-Z_][a-zA-Z0-9_]*``). Used for ``<device><name>`` and
            ``<peripheral><name>``.
        base_address: peripheral base address. Default 0x40000000
            (typical Cortex-M peripheral region). Emitted as
            ``<peripheral><baseAddress>`` in hex.
        peripheral_grouping: future-proof toggle. Only ``"one"``
            (single-peripheral grouping) is supported at v1. The
            ``"per-channel-group"`` value is reserved for a future
            sub-phase per PCDN-SOS-09-B-002 and raises
            :class:`NotImplementedError`.

    Returns:
        UTF-8 string containing the SVD XML document. Pretty-printed via
        ``xml.dom.minidom``; byte-deterministic across runs.

    Raises:
        ValueError: ``device_name`` is not an SV identifier, or
            ``base_address`` is negative.
        NotImplementedError: ``peripheral_grouping`` is the reserved
            ``"per-channel-group"`` value.
    """
    # --- argument validation -------------------------------------------
    if not isinstance(device_name, str) or not _SV_IDENTIFIER_RE.match(device_name):
        raise ValueError(
            f"device_name must be an SV identifier "
            f"(re='{_SV_IDENTIFIER_RE.pattern}'); got {device_name!r}"
        )
    if not isinstance(base_address, int) or isinstance(base_address, bool) or base_address < 0:
        raise ValueError(
            f"base_address must be a non-negative integer; got {base_address!r}"
        )
    if peripheral_grouping == "per-channel-group":
        raise NotImplementedError(
            "peripheral_grouping='per-channel-group' is reserved for a future "
            "sub-phase (PCDN-SOS-09-B-002); only 'one' is supported at v1"
        )
    if peripheral_grouping != "one":
        raise ValueError(
            f"unknown peripheral_grouping {peripheral_grouping!r}; "
            f"supported: 'one' (PCDN-SOS-09-B-002 reserved: 'per-channel-group')"
        )

    # --- document root -------------------------------------------------
    device = ET.Element(
        "device",
        attrib={
            "schemaVersion": "1.3",
            "xmlns:xs": "http://www.w3.org/2001/XMLSchema-instance",
            "xs:noNamespaceSchemaLocation": "CMSIS-SVD.xsd",
        },
    )
    _sub_text(device, "name", device_name)
    _sub_text(device, "version", "1.0")
    _sub_text(
        device,
        "description",
        f"SOS-09-B generated CMSIS-SVD description for {device_name}",
    )
    _sub_text(device, "addressUnitBits", "8")
    _sub_text(device, "width", "32")
    _sub_text(device, "size", "32")
    _sub_text(device, "resetValue", "0x00000000")
    _sub_text(device, "resetMask", "0xFFFFFFFF")

    peripherals = ET.SubElement(device, "peripherals")
    peripheral = ET.SubElement(peripherals, "peripheral")
    _sub_text(peripheral, "name", device_name)
    _sub_text(
        peripheral,
        "description",
        f"SOS-09-B channel block for {device_name}",
    )
    _sub_text(peripheral, "baseAddress", _hex_word(base_address, bits=32))

    # --- address-block summary ----------------------------------------
    # Compute total span before iterating registers so we can emit
    # <addressBlock> before <registers> per SVD schema ordering.
    offsets: list[int] = []
    cursor = 0
    for ch in annotations.channels:
        offsets.append(cursor)
        cursor += _channel_size_bytes(ch.width)
    total_span = cursor if cursor > 0 else 4

    address_block = ET.SubElement(peripheral, "addressBlock")
    _sub_text(address_block, "offset", "0x0")
    _sub_text(address_block, "size", _hex_word(total_span, bits=32))
    _sub_text(address_block, "usage", "registers")

    # --- interrupt rollup ---------------------------------------------
    # Per PCDN-SOS-09-B-004: emit one <interrupt> per channel that
    # carries sos:irq, with sequential ``value`` in chart-walk order.
    irq_seq = 0
    for ch in annotations.channels:
        if ch.irq is not None:
            interrupt = ET.SubElement(peripheral, "interrupt")
            _sub_text(interrupt, "name", ch.irq)
            _sub_text(
                interrupt,
                "description",
                f"SOS-09-B placeholder vector for channel '{ch.name}'",
            )
            _sub_text(interrupt, "value", str(irq_seq))
            irq_seq += 1

    # --- registers -----------------------------------------------------
    registers = ET.SubElement(peripheral, "registers")
    for ch, offset in zip(annotations.channels, offsets):
        _emit_register(registers, ch, offset=offset)

    # --- pretty-print --------------------------------------------------
    raw = ET.tostring(device, encoding="utf-8", xml_declaration=False)
    dom = xml.dom.minidom.parseString(raw)
    pretty = dom.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")
    # ``minidom`` emits ``<?xml version="1.0" encoding="utf-8"?>``
    # (lowercase encoding token). The SVD spec / CMSIS examples use
    # uppercase ``UTF-8``; normalise so output is byte-deterministic and
    # matches the convention. Strip the minidom declaration entirely if
    # present, then prepend our canonical one.
    canonical_decl = '<?xml version="1.0" encoding="UTF-8"?>\n'
    if pretty.startswith("<?xml"):
        # Drop the first line (the declaration minidom inserted) and any
        # immediately-following whitespace-only line.
        nl = pretty.find("\n")
        if nl >= 0:
            pretty = pretty[nl + 1:]
    return canonical_decl + pretty


def emit_svd_from_chart(chart_path: str | Path, **kwargs) -> str:
    """Load a chart, parse SOS-09-A annotations, emit SVD.

    Convenience wrapper for callers that want the loader -> parser ->
    emitter pipeline behind a single entry point. Delegates each step to
    its owning module:

        loader.load_chart(chart_path)         # SOS-08-A
            -> ChartAst.raw_scjson
        parse_chart_annotations(raw_scjson)   # SOS-09-A
            -> ChartAnnotations
        emit_svd(annotations, **kwargs)       # SOS-09-B (this module)
            -> str

    Args:
        chart_path: SCXML chart path. Forwarded verbatim to
            :func:`loader.load_chart`.
        **kwargs: forwarded verbatim to :func:`emit_svd` (notably the
            required ``device_name`` keyword).

    Returns:
        UTF-8 string of pretty-printed SVD XML.
    """
    # Imported lazily so unit tests that build ``ChartAnnotations``
    # directly (the typical path for SVD-emission tests) don't depend on
    # the ``scjson`` CLI being available.
    from loader import load_chart  # noqa: WPS433

    ast = load_chart(Path(chart_path))
    if ast.raw_scjson is None:
        raise RuntimeError(
            f"loader returned ChartAst without raw_scjson for {chart_path!r}"
        )
    annotations = parse_chart_annotations(ast.raw_scjson)
    return emit_svd(annotations, **kwargs)


# ---------------------------------------------------------------------------
# Register-level emission
# ---------------------------------------------------------------------------


def _emit_register(
    parent: ET.Element,
    channel: ChannelAnnotation,
    *,
    offset: int,
) -> ET.Element:
    """Emit one ``<register>`` element under ``parent`` (the ``<registers>``
    container) for the given channel."""
    reg = ET.SubElement(parent, "register")
    _sub_text(reg, "name", channel.name)
    _sub_text(
        reg,
        "description",
        f"SOS-09-B channel '{channel.name}' (kind={channel.kind}, "
        f"dir={channel.dir})",
    )
    _sub_text(reg, "addressOffset", _hex_word(offset, bits=32))
    _sub_text(reg, "size", str(channel.width))
    _sub_text(reg, "access", _KIND_TO_SVD_ACCESS[channel.kind])

    if _has_clear_on_read(channel):
        _sub_text(reg, "readAction", "clear")

    reset_value, reset_mask = _compute_reset(channel)
    _sub_text(reg, "resetValue", _hex_word(reset_value, bits=channel.width))
    _sub_text(reg, "resetMask", _hex_word(reset_mask, bits=channel.width))

    if channel.bit_layout is not None and channel.bit_layout.fields:
        fields_el = ET.SubElement(reg, "fields")
        for f in channel.bit_layout.fields:
            _emit_field(fields_el, f)

    return reg


def _emit_field(parent: ET.Element, field: BitField) -> ET.Element:
    """Emit one ``<field>`` element under ``parent`` (the ``<fields>``
    container)."""
    fel = ET.SubElement(parent, "field")
    # SVD field names are conventionally lowercase; SOS-09-A allows
    # mixed-case SV identifiers, so we lowercase here for consistency.
    _sub_text(fel, "name", field.name.lower())
    _sub_text(
        fel,
        "description",
        f"bit-field '{field.name}' (access={field.access})",
    )
    _sub_text(fel, "bitOffset", str(field.start_bit))
    _sub_text(fel, "bitWidth", str(field.width))
    _sub_text(fel, "access", _FIELD_ACCESS_TO_SVD[field.access])
    if field.side_effect == "clear-on-read":
        _sub_text(fel, "readAction", "clear")
    return fel


__all__ = [
    "emit_svd",
    "emit_svd_from_chart",
]
