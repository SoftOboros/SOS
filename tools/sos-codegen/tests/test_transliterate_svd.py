"""Tests for ``transliterate_svd.py`` — SOS-09-B CMSIS-SVD emitter.

Authority: ``docs/concepts/SOS-09-B-CONCEPTS.md`` (ratified 2026-05-25)
plus the SOS-09 umbrella concepts doc.

Covers:
    - Round-trip: load fixture chart -> parse -> emit -> re-parse with
      ElementTree -> assert structure.
    - Schema conformance: device root has schemaVersion="1.3", required
      children present, peripheral + register tree populated.
    - Per-kind <access> derivation (status / command / queue / shared).
    - readAction=clear on registers that carry any clear-on-read field.
    - IRQ emission and sequential value assignment.
    - Per-field emission: name lowercased, bitOffset, bitWidth, access
      enum mapping (RW/RO/WO/reserved -> SVD strings).
    - resetValue / resetMask derivation from bit_layout (and the
      no-bit_layout default).
    - addressOffset cumulative + 4-byte alignment for sub-32-bit widths.
    - Byte-deterministic emission (same input -> same bytes, twice).
    - Negative cases: invalid device_name -> ValueError; reserved
      ``peripheral_grouping="per-channel-group"`` -> NotImplementedError;
      negative base_address -> ValueError; unknown peripheral_grouping
      -> ValueError.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

# Make `sos-codegen` modules importable when pytest is invoked from any cwd.
_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from loader import load_chart  # noqa: E402
from sos09_annotations import (  # noqa: E402
    BitField,
    BitLayout,
    ChannelAnnotation,
    ChartAnnotations,
    parse_chart_annotations,
)
from transliterate_svd import (  # noqa: E402
    emit_svd,
    emit_svd_from_chart,
)


_FIXTURE = _TOOLS_DIR / "tests" / "fixtures" / "sos09_svd_chart.scxml"


# ---------------------------------------------------------------------------
# Chart-dict helpers (mirrors test_sos09_annotations / test_transliterate_mpu
# in shape, so direct-dict construction stays consistent across SOS-09-A/B/G).
# ---------------------------------------------------------------------------


def _uuid(n: int) -> str:
    """Deterministic RFC 4122 v4 UUID literals for in-test channels."""
    return f"8a000000-0000-4000-8000-0000000000{n:02x}"


def _wrap_other_attrs(payload: dict) -> dict:
    """Wrap a payload dict in the scjson ``other_attributes`` shape."""
    return {"other_attributes": json.dumps(payload)}


def _state(state_id: str, sos_attrs: dict | None = None, **extra) -> dict:
    node: dict = {"id": state_id}
    if sos_attrs is not None:
        node["other_attributes"] = _wrap_other_attrs(sos_attrs)
    node.update(extra)
    return node


def _chart(
    states: list[dict] | None = None,
    *,
    root_attrs: dict | None = None,
    parallels: list[dict] | None = None,
) -> dict:
    chart: dict = {
        "state": states or [],
        "version": 1.0,
        "datamodel_attribute": "ecmascript",
    }
    if parallels is not None:
        chart["parallel"] = parallels
    if root_attrs is not None:
        chart["other_attributes"] = _wrap_other_attrs(root_attrs)
    return chart


def _status(uuid: str, name: str, *, width: int = 32,
            irq: str | None = None,
            bit_layout: dict | None = None) -> dict:
    out: dict = {
        "sos:id": uuid,
        "sos:name": name,
        "sos:kind": "status",
        "sos:dir": "hw→sw",
        "sos:width": width,
    }
    if irq is not None:
        out["sos:irq"] = irq
    if bit_layout is not None:
        out["sos:bit_layout"] = bit_layout
    return out


def _command(uuid: str, name: str, *, width: int = 32,
             bit_layout: dict | None = None) -> dict:
    out: dict = {
        "sos:id": uuid,
        "sos:name": name,
        "sos:kind": "command",
        "sos:dir": "sw→hw",
        "sos:width": width,
    }
    if bit_layout is not None:
        out["sos:bit_layout"] = bit_layout
    return out


def _queue(uuid: str, name: str, *, width: int = 32,
           direction: str = "hw↔sw") -> dict:
    return {
        "sos:id": uuid,
        "sos:name": name,
        "sos:kind": "queue",
        "sos:dir": direction,
        "sos:width": width,
    }


def _shared(uuid: str, name: str, *, width: int = 32,
            mutex: str | None = None) -> dict:
    out: dict = {
        "sos:id": uuid,
        "sos:name": name,
        "sos:kind": "shared",
        "sos:dir": "hw↔sw",
        "sos:width": width,
    }
    if mutex is not None:
        out["sos:mutex"] = mutex
    return out


def _parse(chart: dict) -> ChartAnnotations:
    """Parse a chart dict via A's authoritative API."""
    return parse_chart_annotations(chart)


def _emit(chart: dict, *, device_name: str = "TestDev",
          **kwargs) -> str:
    return emit_svd(_parse(chart), device_name=device_name, **kwargs)


def _emit_and_root(chart: dict, **kwargs) -> ET.Element:
    """Emit + return the parsed ``<device>`` root element."""
    return ET.fromstring(_emit(chart, **kwargs))


# ---------------------------------------------------------------------------
# Fixture-driven round-trip
# ---------------------------------------------------------------------------


def test_fixture_round_trip_yields_well_formed_svd():
    out = emit_svd_from_chart(_FIXTURE, device_name="Sos09Svd")
    # Re-parseable via stdlib ElementTree.
    root = ET.fromstring(out)
    assert root.tag == "device"


def test_fixture_emits_six_registers():
    out = emit_svd_from_chart(_FIXTURE, device_name="Sos09Svd")
    root = ET.fromstring(out)
    regs = root.findall("./peripherals/peripheral/registers/register")
    assert len(regs) == 6


def test_fixture_emits_two_interrupts_with_sequential_values():
    out = emit_svd_from_chart(_FIXTURE, device_name="Sos09Svd")
    root = ET.fromstring(out)
    interrupts = root.findall("./peripherals/peripheral/interrupt")
    assert len(interrupts) == 2
    names = [i.find("name").text for i in interrupts]
    values = [int(i.find("value").text) for i in interrupts]
    assert names == ["rx_irq", "fault_irq"]
    assert values == [0, 1]


def test_fixture_xml_declaration_canonical():
    out = emit_svd_from_chart(_FIXTURE, device_name="Sos09Svd")
    assert out.startswith('<?xml version="1.0" encoding="UTF-8"?>\n')


def test_fixture_byte_deterministic():
    a = emit_svd_from_chart(_FIXTURE, device_name="Sos09Svd")
    b = emit_svd_from_chart(_FIXTURE, device_name="Sos09Svd")
    assert a == b
    assert a.encode("utf-8") == b.encode("utf-8")


def test_fixture_register_names_match_channel_walk_order():
    out = emit_svd_from_chart(_FIXTURE, device_name="Sos09Svd")
    root = ET.fromstring(out)
    names = [
        r.find("name").text
        for r in root.findall("./peripherals/peripheral/registers/register")
    ]
    assert names == [
        "rx_status",
        "tx_command",
        "io_queue",
        "shared_block",
        "fault_status",
        "audit_log",
    ]


# ---------------------------------------------------------------------------
# Device root + schema-conformance
# ---------------------------------------------------------------------------


def _minimal_chart() -> dict:
    return _chart(states=[_state("S1", _status(_uuid(1), "ch_a"))])


def test_device_root_attributes():
    root = _emit_and_root(_minimal_chart(), device_name="DevName")
    assert root.tag == "device"
    assert root.get("schemaVersion") == "1.3"
    # ElementTree normalises the `xs:` namespace alias; assert via items.
    attrs = {k: v for k, v in root.items()}
    assert attrs["schemaVersion"] == "1.3"
    # Either ``xs:noNamespaceSchemaLocation`` (when the prefix declaration
    # was preserved verbatim) or the namespaced form ElementTree expands
    # to. Both forms reference the CMSIS-SVD.xsd value.
    schema_loc_value = None
    for k, v in attrs.items():
        if "noNamespaceSchemaLocation" in k:
            schema_loc_value = v
            break
    assert schema_loc_value == "CMSIS-SVD.xsd"


@pytest.mark.parametrize(
    "child_tag,expected",
    [
        ("name", "DevName"),
        ("version", "1.0"),
        ("addressUnitBits", "8"),
        ("width", "32"),
        ("size", "32"),
        ("resetValue", "0x00000000"),
        ("resetMask", "0xFFFFFFFF"),
    ],
)
def test_device_required_children(child_tag, expected):
    root = _emit_and_root(_minimal_chart(), device_name="DevName")
    el = root.find(child_tag)
    assert el is not None, f"missing required device child <{child_tag}>"
    assert el.text == expected


def test_device_has_description_child():
    root = _emit_and_root(_minimal_chart(), device_name="DevName")
    desc = root.find("description")
    assert desc is not None
    assert "DevName" in desc.text


def test_peripherals_container_present():
    root = _emit_and_root(_minimal_chart(), device_name="DevName")
    periph = root.find("./peripherals/peripheral")
    assert periph is not None
    assert periph.find("name").text == "DevName"


def test_peripheral_base_address_default():
    root = _emit_and_root(_minimal_chart(), device_name="DevName")
    base = root.find("./peripherals/peripheral/baseAddress")
    assert base is not None
    assert base.text == "0x40000000"


def test_peripheral_base_address_custom():
    root = _emit_and_root(
        _minimal_chart(),
        device_name="DevName",
        base_address=0x50001000,
    )
    base = root.find("./peripherals/peripheral/baseAddress")
    assert base.text == "0x50001000"


def test_address_block_present():
    root = _emit_and_root(_minimal_chart(), device_name="DevName")
    blk = root.find("./peripherals/peripheral/addressBlock")
    assert blk is not None
    assert blk.find("offset").text == "0x0"
    assert blk.find("usage").text == "registers"


def test_registers_container_present():
    root = _emit_and_root(_minimal_chart(), device_name="DevName")
    regs = root.find("./peripherals/peripheral/registers")
    assert regs is not None


# ---------------------------------------------------------------------------
# Per-kind register access derivation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind_helper,kind_name,svd_access",
    [
        (lambda: _status(_uuid(0xA1), "s_ch"), "status", "read-only"),
        (lambda: _command(_uuid(0xA2), "c_ch"), "command", "write-only"),
        (lambda: _queue(_uuid(0xA3), "q_ch"), "queue", "read-write"),
        (lambda: _shared(_uuid(0xA4), "sh_ch"), "shared", "read-write"),
    ],
)
def test_register_access_by_kind(kind_helper, kind_name, svd_access):
    chart = _chart(states=[_state("S", kind_helper())])
    root = _emit_and_root(chart, device_name="K")
    reg = root.find("./peripherals/peripheral/registers/register")
    assert reg is not None
    assert reg.find("access").text == svd_access


# ---------------------------------------------------------------------------
# readAction = clear when bit_layout has clear-on-read
# ---------------------------------------------------------------------------


def test_register_read_action_clear_when_any_clear_on_read_field():
    bl = {
        "fields": [
            {"name": "f0", "start_bit": 0, "width": 1, "access": "RO",
             "side_effect": "clear-on-read", "reset_value": 0},
        ]
    }
    chart = _chart(states=[_state("S", _status(_uuid(1), "ch", bit_layout=bl))])
    root = _emit_and_root(chart, device_name="ReadActDev")
    reg = root.find("./peripherals/peripheral/registers/register")
    ra = reg.find("readAction")
    assert ra is not None
    assert ra.text == "clear"


def test_register_no_read_action_without_clear_on_read():
    bl = {
        "fields": [
            {"name": "f0", "start_bit": 0, "width": 8, "access": "RO",
             "side_effect": None, "reset_value": 0},
        ]
    }
    chart = _chart(states=[_state("S", _status(_uuid(1), "ch", bit_layout=bl))])
    root = _emit_and_root(chart, device_name="NoClrDev")
    reg = root.find("./peripherals/peripheral/registers/register")
    assert reg.find("readAction") is None


def test_register_read_action_clear_present_when_only_one_field_clears():
    bl = {
        "fields": [
            {"name": "ready", "start_bit": 0, "width": 1, "access": "RO",
             "side_effect": "clear-on-read", "reset_value": 0},
            {"name": "count", "start_bit": 1, "width": 7, "access": "RO",
             "side_effect": None, "reset_value": 0},
        ]
    }
    chart = _chart(states=[_state("S", _status(_uuid(1), "ch", bit_layout=bl))])
    root = _emit_and_root(chart, device_name="OneClrDev")
    reg = root.find("./peripherals/peripheral/registers/register")
    assert reg.find("readAction").text == "clear"


def test_field_read_action_clear_emitted_per_field():
    bl = {
        "fields": [
            {"name": "ready", "start_bit": 0, "width": 1, "access": "RO",
             "side_effect": "clear-on-read", "reset_value": 0},
            {"name": "count", "start_bit": 1, "width": 7, "access": "RO",
             "side_effect": None, "reset_value": 0},
        ]
    }
    chart = _chart(states=[_state("S", _status(_uuid(1), "ch", bit_layout=bl))])
    root = _emit_and_root(chart, device_name="FieldClrDev")
    fields = root.findall("./peripherals/peripheral/registers/register/fields/field")
    by_name = {f.find("name").text: f for f in fields}
    assert by_name["ready"].find("readAction") is not None
    assert by_name["ready"].find("readAction").text == "clear"
    assert by_name["count"].find("readAction") is None


# ---------------------------------------------------------------------------
# IRQ emission
# ---------------------------------------------------------------------------


def test_irq_emitted_for_status_channel():
    chart = _chart(states=[
        _state("A", _status(_uuid(1), "ch_a", irq="irq_a")),
    ])
    root = _emit_and_root(chart, device_name="IrqDev")
    interrupts = root.findall("./peripherals/peripheral/interrupt")
    assert len(interrupts) == 1
    assert interrupts[0].find("name").text == "irq_a"
    assert interrupts[0].find("value").text == "0"


def test_irq_sequential_values_in_walk_order():
    chart = _chart(states=[
        _state("A", _status(_uuid(1), "ch_a", irq="irq_a")),
        _state("B", _status(_uuid(2), "ch_b", irq="irq_b")),
        _state("C", _status(_uuid(3), "ch_c", irq="irq_c")),
    ])
    root = _emit_and_root(chart, device_name="MultiIrq")
    interrupts = root.findall("./peripherals/peripheral/interrupt")
    assert [i.find("name").text for i in interrupts] == ["irq_a", "irq_b", "irq_c"]
    assert [i.find("value").text for i in interrupts] == ["0", "1", "2"]


def test_no_interrupt_when_no_irq_set():
    chart = _chart(states=[
        _state("A", _command(_uuid(1), "ch_a")),
        _state("B", _queue(_uuid(2), "ch_b")),
    ])
    root = _emit_and_root(chart, device_name="NoIrqDev")
    interrupts = root.findall("./peripherals/peripheral/interrupt")
    assert interrupts == []


def test_irq_skipped_for_non_irq_channels_between_irq_channels():
    chart = _chart(states=[
        _state("A", _status(_uuid(1), "ch_a", irq="irq_a")),
        _state("B", _command(_uuid(2), "ch_b")),
        _state("C", _status(_uuid(3), "ch_c", irq="irq_c")),
    ])
    root = _emit_and_root(chart, device_name="GapIrqDev")
    interrupts = root.findall("./peripherals/peripheral/interrupt")
    assert [i.find("name").text for i in interrupts] == ["irq_a", "irq_c"]
    # ch_b carries no irq -> irq_c's index is still sequential among irq-bearing.
    assert [i.find("value").text for i in interrupts] == ["0", "1"]


# ---------------------------------------------------------------------------
# Field emission (bit offsets, widths, access)
# ---------------------------------------------------------------------------


def test_field_bit_offset_and_width_emitted():
    bl = {
        "fields": [
            {"name": "lo", "start_bit": 0, "width": 4, "access": "RW",
             "side_effect": None, "reset_value": 0},
            {"name": "hi", "start_bit": 16, "width": 8, "access": "RW",
             "side_effect": None, "reset_value": 0},
        ]
    }
    chart = _chart(states=[_state("S", _command(_uuid(1), "ch", bit_layout=bl))])
    root = _emit_and_root(chart, device_name="FieldDev")
    fields = root.findall("./peripherals/peripheral/registers/register/fields/field")
    assert len(fields) == 2
    by_name = {f.find("name").text: f for f in fields}
    assert by_name["lo"].find("bitOffset").text == "0"
    assert by_name["lo"].find("bitWidth").text == "4"
    assert by_name["hi"].find("bitOffset").text == "16"
    assert by_name["hi"].find("bitWidth").text == "8"


def test_field_name_lowercased():
    bl = {
        "fields": [
            {"name": "MixedCase", "start_bit": 0, "width": 1, "access": "RW",
             "side_effect": None, "reset_value": 0},
        ]
    }
    chart = _chart(states=[_state("S", _command(_uuid(1), "ch", bit_layout=bl))])
    root = _emit_and_root(chart, device_name="CaseDev")
    field = root.find("./peripherals/peripheral/registers/register/fields/field")
    assert field.find("name").text == "mixedcase"


@pytest.mark.parametrize(
    "field_access,svd_access",
    [
        ("RW", "read-write"),
        ("RO", "read-only"),
        ("WO", "write-only"),
        ("reserved", "read-only"),
    ],
)
def test_field_access_enum_mapping(field_access, svd_access):
    # Use a status channel since RO + reserved are the most natural fit;
    # for WO we use a command channel (since status rejects WO at parse
    # time? actually A's parser doesn't gate field access by kind — only
    # bit layout is independently validated). Use a command channel for
    # WO and RW combinations.
    if field_access == "RW":
        wrap = _command
    elif field_access == "WO":
        wrap = _command
    else:
        wrap = _status
    bl = {
        "fields": [
            {"name": "f", "start_bit": 0, "width": 4, "access": field_access,
             "side_effect": None, "reset_value": 0},
        ]
    }
    chart = _chart(states=[_state("S", wrap(_uuid(1), "ch", bit_layout=bl))])
    root = _emit_and_root(chart, device_name="AccessDev")
    field = root.find("./peripherals/peripheral/registers/register/fields/field")
    assert field.find("access").text == svd_access


def test_field_omitted_when_no_bit_layout():
    chart = _chart(states=[_state("S", _command(_uuid(1), "ch"))])
    root = _emit_and_root(chart, device_name="NoLayoutDev")
    fields_el = root.find("./peripherals/peripheral/registers/register/fields")
    # If no bit_layout, the <fields> container is not emitted.
    assert fields_el is None


# ---------------------------------------------------------------------------
# resetValue / resetMask derivation
# ---------------------------------------------------------------------------


def test_reset_value_zero_with_no_bit_layout():
    chart = _chart(states=[_state("S", _command(_uuid(1), "ch"))])
    root = _emit_and_root(chart, device_name="ResetDev")
    reg = root.find("./peripherals/peripheral/registers/register")
    assert reg.find("resetValue").text == "0x00000000"


def test_reset_mask_full_width_with_no_bit_layout():
    chart = _chart(states=[_state("S", _command(_uuid(1), "ch", width=32))])
    root = _emit_and_root(chart, device_name="MaskDev")
    reg = root.find("./peripherals/peripheral/registers/register")
    assert reg.find("resetMask").text == "0xFFFFFFFF"


def test_reset_mask_full_width_16bit_channel():
    chart = _chart(states=[_state("S", _command(_uuid(1), "ch", width=16))])
    root = _emit_and_root(chart, device_name="Mask16Dev")
    reg = root.find("./peripherals/peripheral/registers/register")
    assert reg.find("resetMask").text == "0xFFFF"


def test_reset_value_ored_from_field_reset_values():
    bl = {
        "fields": [
            {"name": "a", "start_bit": 0, "width": 4, "access": "RW",
             "side_effect": None, "reset_value": 0x3},
            {"name": "b", "start_bit": 16, "width": 4, "access": "RW",
             "side_effect": None, "reset_value": 0xA},
        ]
    }
    chart = _chart(states=[_state("S", _command(_uuid(1), "ch", bit_layout=bl))])
    root = _emit_and_root(chart, device_name="OrDev")
    reg = root.find("./peripherals/peripheral/registers/register")
    # 0x3 at offset 0 OR 0xA at offset 16 -> 0x000A_0003
    assert reg.find("resetValue").text == "0x000A0003"


def test_reset_mask_ored_from_field_widths():
    bl = {
        "fields": [
            {"name": "a", "start_bit": 0, "width": 4, "access": "RW",
             "side_effect": None, "reset_value": 0},
            {"name": "b", "start_bit": 8, "width": 8, "access": "RW",
             "side_effect": None, "reset_value": 0},
        ]
    }
    chart = _chart(states=[_state("S", _command(_uuid(1), "ch", bit_layout=bl))])
    root = _emit_and_root(chart, device_name="MaskOrDev")
    reg = root.find("./peripherals/peripheral/registers/register")
    # bits 0..3 (0xF) | bits 8..15 (0xFF00) = 0xFF0F.
    assert reg.find("resetMask").text == "0x0000FF0F"


# ---------------------------------------------------------------------------
# Address offset cumulative + 4-byte alignment
# ---------------------------------------------------------------------------


def test_address_offsets_4byte_aligned_for_32bit_channels():
    chart = _chart(states=[
        _state("S0", _status(_uuid(1), "c0")),
        _state("S1", _status(_uuid(2), "c1")),
        _state("S2", _status(_uuid(3), "c2")),
    ])
    root = _emit_and_root(chart, device_name="OffDev")
    offs = [
        r.find("addressOffset").text
        for r in root.findall("./peripherals/peripheral/registers/register")
    ]
    assert offs == ["0x00000000", "0x00000004", "0x00000008"]


def test_address_offsets_round_up_for_sub_32bit_channels():
    chart = _chart(states=[
        _state("S0", _queue(_uuid(1), "c0", width=16)),  # 2B -> 4B slot
        _state("S1", _queue(_uuid(2), "c1", width=8)),   # 1B -> 4B slot
        _state("S2", _queue(_uuid(3), "c2", width=32)),
    ])
    root = _emit_and_root(chart, device_name="MixedWidths")
    offs = [
        r.find("addressOffset").text
        for r in root.findall("./peripherals/peripheral/registers/register")
    ]
    assert offs == ["0x00000000", "0x00000004", "0x00000008"]


def test_address_block_size_matches_total_span():
    chart = _chart(states=[
        _state("S0", _status(_uuid(1), "c0", width=32)),
        _state("S1", _status(_uuid(2), "c1", width=32)),
    ])
    root = _emit_and_root(chart, device_name="BlkDev")
    blk = root.find("./peripherals/peripheral/addressBlock/size")
    assert blk.text == "0x00000008"


def test_address_block_size_with_subword_channels():
    chart = _chart(states=[
        _state("S0", _queue(_uuid(1), "c0", width=16)),
        _state("S1", _queue(_uuid(2), "c1", width=16)),
    ])
    root = _emit_and_root(chart, device_name="SubBlkDev")
    blk = root.find("./peripherals/peripheral/addressBlock/size")
    # Both round up to 4B, total = 8B.
    assert blk.text == "0x00000008"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_byte_deterministic_inline_chart():
    chart = _chart(states=[
        _state("A", _status(_uuid(1), "ch_a", irq="irq_a")),
        _state("B", _command(_uuid(2), "ch_b")),
    ])
    a = _emit(chart, device_name="Det")
    b = _emit(chart, device_name="Det")
    assert a == b


def test_byte_deterministic_across_multiple_emits():
    chart = _chart(states=[
        _state("A", _status(_uuid(i), f"ch_{i}", irq=f"irq_{i}")) for i in range(1, 4)
    ])
    outs = [_emit(chart, device_name="Loop") for _ in range(5)]
    assert all(o == outs[0] for o in outs)


# ---------------------------------------------------------------------------
# Negative cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_name", ["", "1invalid", "has space", "kebab-case", "dot.name", None, 42])
def test_invalid_device_name_raises_value_error(bad_name):
    chart = _minimal_chart()
    annotations = _parse(chart)
    with pytest.raises(ValueError):
        emit_svd(annotations, device_name=bad_name)


def test_per_channel_group_grouping_raises_not_implemented():
    annotations = _parse(_minimal_chart())
    with pytest.raises(NotImplementedError):
        emit_svd(
            annotations,
            device_name="Dev",
            peripheral_grouping="per-channel-group",
        )


def test_unknown_grouping_raises_value_error():
    annotations = _parse(_minimal_chart())
    with pytest.raises(ValueError):
        emit_svd(annotations, device_name="Dev", peripheral_grouping="bogus")


def test_negative_base_address_raises_value_error():
    annotations = _parse(_minimal_chart())
    with pytest.raises(ValueError):
        emit_svd(annotations, device_name="Dev", base_address=-1)


# ---------------------------------------------------------------------------
# Schema-shape / structural assertions
# ---------------------------------------------------------------------------


def test_register_has_size_matching_channel_width():
    chart = _chart(states=[
        _state("S0", _status(_uuid(1), "c0", width=32)),
        _state("S1", _queue(_uuid(2), "c1", width=16)),
    ])
    root = _emit_and_root(chart, device_name="SizeDev")
    regs = root.findall("./peripherals/peripheral/registers/register")
    sizes = [r.find("size").text for r in regs]
    assert sizes == ["32", "16"]


def test_register_name_matches_channel_name():
    chart = _chart(states=[_state("S", _status(_uuid(1), "rx_status"))])
    root = _emit_and_root(chart, device_name="NameDev")
    reg = root.find("./peripherals/peripheral/registers/register")
    assert reg.find("name").text == "rx_status"


def test_empty_chart_emits_valid_device_with_no_registers():
    chart = _chart(states=[])
    root = _emit_and_root(chart, device_name="EmptyDev")
    regs = root.findall("./peripherals/peripheral/registers/register")
    assert regs == []
    # Schema-required device children must still be present.
    assert root.find("name").text == "EmptyDev"
    assert root.find("./peripherals/peripheral/registers") is not None


def test_emit_svd_returns_str():
    chart = _minimal_chart()
    out = _emit(chart, device_name="StrDev")
    assert isinstance(out, str)
    assert out.endswith("\n") or out.endswith(">")


# ---------------------------------------------------------------------------
# emit_svd_from_chart pipeline coverage
# ---------------------------------------------------------------------------


def test_emit_svd_from_chart_forwards_kwargs(tmp_path):
    # Use the fixture but override base_address.
    out = emit_svd_from_chart(
        _FIXTURE, device_name="FwdDev", base_address=0x60000000,
    )
    root = ET.fromstring(out)
    base = root.find("./peripherals/peripheral/baseAddress")
    assert base.text == "0x60000000"
    assert root.find("name").text == "FwdDev"


def test_emit_svd_from_chart_uses_authoritative_parser():
    # Round-trip through the loader must produce the same channel set
    # the in-memory parse_chart_annotations produces.
    ast = load_chart(_FIXTURE)
    direct = parse_chart_annotations(ast.raw_scjson)
    out_direct = emit_svd(direct, device_name="ParserDev")
    out_pipeline = emit_svd_from_chart(_FIXTURE, device_name="ParserDev")
    assert out_direct == out_pipeline


# ---------------------------------------------------------------------------
# Additional edge cases / coverage padding
# ---------------------------------------------------------------------------


def test_status_channel_with_irq_but_no_bit_layout_still_emits_register():
    chart = _chart(states=[_state("S", _status(_uuid(1), "rx", irq="rx_irq"))])
    root = _emit_and_root(chart, device_name="MinIrq")
    reg = root.find("./peripherals/peripheral/registers/register")
    assert reg is not None
    assert reg.find("name").text == "rx"
    # No <fields> when bit_layout is absent.
    assert reg.find("fields") is None
    # readAction not emitted absent clear-on-read fields.
    assert reg.find("readAction") is None


def test_command_channel_with_side_effect_on_write_does_not_set_read_action():
    bl = {
        "fields": [
            {"name": "go", "start_bit": 0, "width": 1, "access": "WO",
             "side_effect": "side-effect-on-write", "reset_value": 0},
        ]
    }
    chart = _chart(states=[_state("S", _command(_uuid(1), "ctl", bit_layout=bl))])
    root = _emit_and_root(chart, device_name="SeWriteDev")
    reg = root.find("./peripherals/peripheral/registers/register")
    # side-effect-on-write does NOT map to readAction=clear; that's a
    # read-side action only.
    assert reg.find("readAction") is None


def test_shared_channel_emits_read_write_access():
    chart = _chart(states=[_state("S", _shared(_uuid(1), "shr_ch", mutex="m"))])
    root = _emit_and_root(chart, device_name="ShDev")
    reg = root.find("./peripherals/peripheral/registers/register")
    assert reg.find("access").text == "read-write"


def test_queue_one_directional_emits_read_write_access():
    chart = _chart(states=[
        _state("A", _queue(_uuid(1), "q_in", direction="hw→sw")),
        _state("B", _queue(_uuid(2), "q_out", direction="sw→hw")),
    ])
    root = _emit_and_root(chart, device_name="QDev")
    regs = root.findall("./peripherals/peripheral/registers/register")
    # Both queue directions collapse to read-write at v1 (per-kind mapping).
    assert all(r.find("access").text == "read-write" for r in regs)


def test_all_field_kinds_round_trip_via_fromstring():
    # Ensure every emitted document is well-formed enough for ElementTree
    # to round-trip, even for the maximally-complex layout.
    bl = {
        "fields": [
            {"name": "rw_field", "start_bit": 0, "width": 4, "access": "RW",
             "side_effect": None, "reset_value": 1},
            {"name": "ro_field", "start_bit": 4, "width": 4, "access": "RO",
             "side_effect": "clear-on-read", "reset_value": 0},
            {"name": "wo_field", "start_bit": 8, "width": 4, "access": "WO",
             "side_effect": "side-effect-on-write", "reset_value": 0},
            {"name": "rsvd", "start_bit": 12, "width": 4, "access": "reserved",
             "side_effect": None, "reset_value": 0},
        ]
    }
    chart = _chart(states=[_state("S", _command(_uuid(1), "mixed", bit_layout=bl))])
    out = _emit(chart, device_name="MixedDev")
    # Round-trip through ElementTree must not throw.
    root = ET.fromstring(out)
    fields = root.findall("./peripherals/peripheral/registers/register/fields/field")
    assert len(fields) == 4
    accesses = sorted(f.find("access").text for f in fields)
    assert accesses == ["read-only", "read-only", "read-write", "write-only"]


def test_register_description_includes_kind_and_dir():
    chart = _chart(states=[_state("S", _status(_uuid(1), "rx_ch"))])
    root = _emit_and_root(chart, device_name="DescDev")
    reg = root.find("./peripherals/peripheral/registers/register")
    desc = reg.find("description")
    assert desc is not None
    assert "status" in desc.text
    assert "hw" in desc.text  # picks up the dir string


def test_emit_svd_uses_ascii_only_xml_decl():
    chart = _minimal_chart()
    out = _emit(chart, device_name="AsciiDev")
    # Declaration line must be canonical UTF-8 form.
    first_line = out.splitlines()[0]
    assert first_line == '<?xml version="1.0" encoding="UTF-8"?>'


def test_emit_svd_handles_underscore_device_name():
    chart = _minimal_chart()
    out = _emit(chart, device_name="_under_score123")
    root = ET.fromstring(out)
    assert root.find("name").text == "_under_score123"
