"""Tests for ``transliterate_regfile.py`` — SOS-09-E HDL register-file emitter.

Authority: ``docs/concepts/SOS-09-E-CONCEPTS.md`` (🟢 RATIFIED 2026-05-26).
Covers the §12 implementation gates (b)–(l) — the (a) gate (PCDN ratification)
already passed at the concepts-doc level.

Gates covered:
    (b) sos_regfile template exists and accepts a bus-type parameter
    (c) per-channel realisation table for all four kinds
    (d) write-mask + reserved-bit-read-as-zero policies
    (e) read-clear gating
    (f) access-violation aggregation per privilege_region
    (g) language parity — VHDL + SV emissions of the same chart agree structurally
    (h) SVD-offset match (INV-S-MEM-E-6)
    (i) synthesis-tool coverage — Yosys parse-only on SV emission;
        skipped with reason if Yosys is not on PATH (gate is implementation-
        side optional per §12 conformance text)
    (j)-(l) invariant citations via ``@spec`` block in the emitter source

@spec  docs/concepts/SOS-09-E-CONCEPTS.md §5.1..§5.7 (frozen decisions)
@spec  docs/concepts/SOS-09-E-CONCEPTS.md §6 INV-S-MEM-E-1..6
@spec  docs/concepts/SOS-09-E-CONCEPTS.md §9 acceptance gates (a)..(i)
@spec  docs/concepts/SOS-09-E-CONCEPTS.md §12 implementation gates (b)..(l)
@spec  docs/concepts/SOS-09-A-CONCEPTS.md (annotation surface — consumed)
@spec  docs/concepts/SOS-09-B-CONCEPTS.md §5.3 (address-offset assignment — mirrored)
@spec  docs/concepts/SOS-08-A-CONCEPTS.md §6 (L0 primitives — composed)
@spec  docs/concepts/SOS-08-D-CONCEPTS.md (clock-domain → sync insertion)
@spec  docs/concepts/SOS-07-CONCEPTS.md §6 INV-SOS-A..H (cross-phase invariants)
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Make ``sos-codegen`` modules importable when pytest is invoked from any cwd.
_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sos09_annotations import (  # noqa: E402
    BitField,
    BitLayout,
    ChannelAnnotation,
    ChartAnnotations,
    parse_chart_annotations,
)
from transliterate_regfile import (  # noqa: E402
    ALLOWED_BUS_TYPES,
    BUS_APB,
    BUS_AXI4LITE,
    DEFAULT_PRIVILEGE_REGION,
    RegfileView,
    Sos09RegfileError,
    assert_svd_offsets_match,
    build_view,
    emit_regfile,
    emit_regfile_from_chart,
)
from transliterate_svd import emit_svd  # noqa: E402


_FIXTURE_DIR = _TOOLS_DIR / "tests" / "fixtures" / "sos_09_e"
_FIXTURE_CHART = _FIXTURE_DIR / "regfile_demo.scxml"


# ---------------------------------------------------------------------------
# Chart-dict helpers (mirror test_transliterate_svd shape)
# ---------------------------------------------------------------------------


def _uuid(n: int) -> str:
    return f"aaaa0000-0000-4000-8000-0000000000{n:02x}"


def _wrap_other_attrs(payload: dict) -> dict:
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
            zone: str = "privileged",
            privilege_region: str | None = None,
            bit_layout: dict | None = None) -> dict:
    out: dict = {
        "sos:id": uuid,
        "sos:name": name,
        "sos:kind": "status",
        "sos:dir": "hw→sw",
        "sos:width": width,
        "sos:zone": zone,
    }
    if bit_layout is not None:
        out["sos:bit_layout"] = bit_layout
    if privilege_region is not None:
        out["sos:privilege_region"] = privilege_region
    return out


def _command(uuid: str, name: str, *, width: int = 32,
             zone: str = "privileged",
             privilege_region: str | None = None,
             clock_domain: str | None = None,
             bit_layout: dict | None = None) -> dict:
    out: dict = {
        "sos:id": uuid,
        "sos:name": name,
        "sos:kind": "command",
        "sos:dir": "sw→hw",
        "sos:width": width,
        "sos:zone": zone,
    }
    if bit_layout is not None:
        out["sos:bit_layout"] = bit_layout
    if privilege_region is not None:
        out["sos:privilege_region"] = privilege_region
    if clock_domain is not None:
        out["sos:clock_domain"] = clock_domain
    return out


def _queue(uuid: str, name: str, *, width: int = 32,
           direction: str = "hw↔sw",
           privilege_region: str | None = None) -> dict:
    out: dict = {
        "sos:id": uuid,
        "sos:name": name,
        "sos:kind": "queue",
        "sos:dir": direction,
        "sos:width": width,
    }
    if privilege_region is not None:
        out["sos:privilege_region"] = privilege_region
    return out


def _shared(uuid: str, name: str, *, width: int = 32,
            mutex: str | None = None,
            privilege_region: str | None = None) -> dict:
    out: dict = {
        "sos:id": uuid,
        "sos:name": name,
        "sos:kind": "shared",
        "sos:dir": "hw↔sw",
        "sos:width": width,
    }
    if mutex is not None:
        out["sos:mutex"] = mutex
    if privilege_region is not None:
        out["sos:privilege_region"] = privilege_region
    return out


def _parse(chart: dict) -> ChartAnnotations:
    return parse_chart_annotations(chart)


def _emit(chart: dict, *, peripheral_name: str = "TestDev",
          bus_type: str = BUS_AXI4LITE,
          **kwargs) -> dict[str, str]:
    return emit_regfile(
        _parse(chart),
        peripheral_name=peripheral_name,
        bus_type=bus_type,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Fixture-driven smoke + structural assertions
# ---------------------------------------------------------------------------


def test_fixture_chart_emits_both_languages():
    """Gate (b)+(g) smoke — fixture chart produces VHDL + SV pair."""
    files = emit_regfile_from_chart(_FIXTURE_CHART, peripheral_name="Demo")
    assert "sos_regfile_Demo.vhd" in files
    assert "sos_regfile_Demo.sv" in files
    assert files["sos_regfile_Demo.vhd"].startswith("--")
    assert "module sos_regfile_Demo" in files["sos_regfile_Demo.sv"]
    assert "entity sos_regfile_Demo" in files["sos_regfile_Demo.vhd"]


def test_fixture_chart_byte_identical_on_two_emits():
    """Determinism — same chart → byte-identical bytes twice (INV-S-MEM-2 style)."""
    a = emit_regfile_from_chart(_FIXTURE_CHART, peripheral_name="Demo")
    b = emit_regfile_from_chart(_FIXTURE_CHART, peripheral_name="Demo")
    assert a == b


# ---------------------------------------------------------------------------
# Gate (b) — sos_regfile template + bus-type parameter
# ---------------------------------------------------------------------------


def test_template_emits_bus_type_generic_parameter():
    """Gate (b): the SV emission carries a ``BUS_TYPE`` parameter and the
    VHDL emission carries a corresponding generic.

    PCDN-SOS-09-E-005(a) — single template, bus-type parameter; NOT two
    templates.
    """
    chart = _chart(
        states=[_state("RX", _status(_uuid(1), "rx"))],
    )
    files = _emit(chart, peripheral_name="P")
    sv = files["sos_regfile_P.sv"]
    vhd = files["sos_regfile_P.vhd"]
    assert "parameter BUS_TYPE" in sv
    assert "BUS_TYPE" in vhd and "string" in vhd
    # Default is AXI4-Lite per PCDN-SOS-09-E-001(a).
    assert "axi4lite" in sv and "axi4lite" in vhd


def test_template_emits_apb_when_requested():
    """Gate (b): bus_type='apb' yields APB as the default-string parameter."""
    chart = _chart(states=[_state("RX", _status(_uuid(2), "rx"))])
    files = _emit(chart, peripheral_name="P", bus_type=BUS_APB)
    assert 'parameter BUS_TYPE = "apb"' in files["sos_regfile_P.sv"]
    assert 'BUS_TYPE : string  := "apb"' in files["sos_regfile_P.vhd"]


def test_unknown_bus_type_raises():
    """Gate (b): bus_type outside the v1 enum is a build-stop."""
    chart = _chart(states=[_state("RX", _status(_uuid(3), "rx"))])
    with pytest.raises(Sos09RegfileError):
        _emit(chart, peripheral_name="P", bus_type="ahb")


def test_axi_and_apb_emissions_share_internal_decode():
    """Gate (b)+(g): both bus types share the same internal decode logic
    (the parameterised approach per PCDN-SOS-09-E-005(a))."""
    chart = _chart(states=[_state("RX", _status(_uuid(4), "rx"))])
    axi = _emit(chart, peripheral_name="P", bus_type=BUS_AXI4LITE)["sos_regfile_P.sv"]
    apb = _emit(chart, peripheral_name="P", bus_type=BUS_APB)["sos_regfile_P.sv"]
    # Same template emits both — only the BUS_TYPE default differs.
    # The decode signal names + register-offset constants are byte-identical.
    pattern = re.compile(r"localparam \[ADDR_W-1:0\] REG_OFFSET_RX = 0;")
    assert pattern.search(axi) and pattern.search(apb)


# ---------------------------------------------------------------------------
# Gate (c) — per-kind realisation for all four kinds
# ---------------------------------------------------------------------------


def test_status_channel_instantiates_strobe_latch():
    """Gate (c) status row: SOS-08-A sos_strobe_latch composed (no rewrite)."""
    chart = _chart(states=[_state("S", _status(_uuid(5), "s"))])
    sv = _emit(chart, peripheral_name="P")["sos_regfile_P.sv"]
    vhd = _emit(chart, peripheral_name="P")["sos_regfile_P.vhd"]
    assert "sos_strobe_latch u_status_s" in sv
    assert "u_status_s : sos_strobe_latch" in vhd


def test_command_channel_holds_value_and_emits_registered_fire():
    """Gate (c) command row + PCDN-SOS-09-E-006(b): fire strobe is REGISTERED."""
    chart = _chart(states=[_state("C", _command(_uuid(6), "c"))])
    sv = _emit(chart, peripheral_name="P")["sos_regfile_P.sv"]
    # Registered fire strobe — declared as ``reg`` and updated inside always_ff.
    assert "reg                          c_fire_reg;" in sv
    assert "c_fire_reg  <= 1'b1;" in sv
    assert "c_fire_reg  <= 1'b0;" in sv


def test_queue_channel_instantiates_message_channel():
    """Gate (c) queue row: SOS-08-B sos_message_channel composed (no rewrite)."""
    chart = _chart(
        parallels=[{
            "id": "Q",
            "other_attributes": _wrap_other_attrs(
                _queue(_uuid(7), "q")
            )["other_attributes"],
        }],
    )
    sv = _emit(chart, peripheral_name="P")["sos_regfile_P.sv"]
    assert "sos_message_channel" in sv
    assert "u_queue_q" in sv


def test_shared_channel_instantiates_dpram_arb_and_mutex():
    """Gate (c) shared row: SOS-08-A sos_dpram_arb + sos_mutex composed."""
    chart = _chart(
        parallels=[{
            "id": "S",
            "other_attributes": _wrap_other_attrs(
                _shared(_uuid(8), "sh", mutex="m")
            )["other_attributes"],
        }],
    )
    sv = _emit(chart, peripheral_name="P")["sos_regfile_P.sv"]
    assert "sos_mutex" in sv
    assert "sos_dpram_arb" in sv
    assert "u_mutex_sh" in sv
    assert "u_dpram_sh" in sv


def test_all_four_kinds_render_distinctly():
    """Gate (c) — one chart with all four kinds emits all four primitive
    compositions in a single regfile."""
    chart = _chart(
        states=[
            _state("ST", _status(_uuid(9), "s_ch")),
            _state("CM", _command(_uuid(10), "c_ch")),
        ],
        parallels=[
            {
                "id": "QQ",
                "other_attributes": _wrap_other_attrs(
                    _queue(_uuid(11), "q_ch")
                )["other_attributes"],
                "state": [
                    _state("SH", _shared(_uuid(12), "sh_ch", mutex="m_ch")),
                ],
            }
        ],
    )
    files = _emit(chart, peripheral_name="P")
    sv = files["sos_regfile_P.sv"]
    assert "sos_strobe_latch u_status_s_ch" in sv
    assert "c_ch_fire_reg" in sv
    assert "sos_message_channel" in sv and "u_queue_q_ch" in sv
    assert "sos_mutex" in sv and "u_mutex_sh_ch" in sv


# ---------------------------------------------------------------------------
# Gate (d) — write-mask + reserved-bits-read-as-zero
# ---------------------------------------------------------------------------


def test_write_mask_excludes_reserved_bits():
    """Gate (d): writes to reserved-bit positions are masked out at the
    flop-bank D-input.

    Chart command channel: bit 0 = WO start; bit 4..7 = RW mode; bits 1..3
    + 8..31 reserved/RO/gap → write_mask = 0xF1.
    """
    layout = {
        "fields": [
            {"name": "start", "start_bit": 0, "width": 1, "access": "WO",
             "side_effect": None, "reset_value": 0},
            {"name": "mode",  "start_bit": 4, "width": 4, "access": "RW",
             "side_effect": None, "reset_value": 3},
            {"name": "lockd", "start_bit": 8, "width": 8, "access": "RO",
             "side_effect": None, "reset_value": 0},
            {"name": "rsv",   "start_bit": 16, "width": 16, "access": "reserved",
             "side_effect": None, "reset_value": 0},
        ],
    }
    chart = _chart(
        states=[_state("CMD", _command(_uuid(13), "cmd",
                                       bit_layout=layout))],
    )
    view = build_view(_parse(chart), peripheral_name="P")
    ch = view.channels[0]
    # writable bits: start(0) + mode(4..7); 0b1111_0001 = 0xF1.
    assert ch.write_mask == 0xF1
    # readable bits: mode(4..7) + lockd(8..15); 0xFFF0.
    assert ch.read_mask == 0xFFF0
    # reset_value: mode = 3 << 4 = 0x30.
    assert ch.reset_value == 0x30


def test_reserved_bits_read_as_zero_via_read_mask():
    """Gate (d) reserved-read-as-zero: read_mask clears reserved positions.

    On a chart status channel with declared bits 0..7 only, the upper 24
    bits are an implicit gap and read_mask has zeros in those positions.
    """
    layout = {
        "fields": [
            {"name": "ready", "start_bit": 0, "width": 1, "access": "RO",
             "side_effect": "clear-on-read", "reset_value": 0},
            {"name": "count", "start_bit": 1, "width": 7, "access": "RO",
             "side_effect": None, "reset_value": 0},
        ],
    }
    chart = _chart(
        states=[_state("ST", _status(_uuid(14), "s",
                                     bit_layout=layout))],
    )
    view = build_view(_parse(chart), peripheral_name="P")
    ch = view.channels[0]
    # Read-mask covers bits 0..7 only.
    assert ch.read_mask == 0xFF
    # The implicit gap bits 8..31 are NOT in the read mask.
    for bit in range(8, 32):
        assert (ch.read_mask >> bit) & 1 == 0


def test_write_mask_emitted_into_rtl_text():
    """Gate (d): write_mask appears as a localparam / constant in both
    languages' emitted RTL."""
    chart = _chart(
        states=[_state("CMD", _command(_uuid(15), "cmd"))],
    )
    files = _emit(chart, peripheral_name="P")
    assert "WRITE_MASK_CMD" in files["sos_regfile_P.sv"]
    assert "WRITE_MASK_CMD" in files["sos_regfile_P.vhd"]


# ---------------------------------------------------------------------------
# Gate (e) — read-clear gating
# ---------------------------------------------------------------------------


def test_clear_on_read_gated_on_decode_read():
    """Gate (e) / INV-S-MEM-E-3: the clear strobe fires only when the
    decoded read line for that register is asserted.

    The emitter's clear path uses ``decode_<name>_read`` (which is itself
    ANDed with zone_match per §5.4) as the ack input to sos_strobe_latch.
    """
    layout = {
        "fields": [
            {"name": "ready", "start_bit": 0, "width": 1, "access": "RO",
             "side_effect": "clear-on-read", "reset_value": 0},
        ],
    }
    chart = _chart(
        states=[_state("ST", _status(_uuid(16), "s",
                                     bit_layout=layout))],
    )
    sv = _emit(chart, peripheral_name="P")["sos_regfile_P.sv"]
    # The strobe-latch's `ack` is wired to decode_<name>_read.
    # Match the pattern in the rendered text.
    assert ".ack(decode_s_read)" in sv


def test_no_clear_on_read_field_yields_tied_ack():
    """Gate (e): channels WITHOUT clear-on-read don't have their latch
    cleared by bus reads (ack tied to 0)."""
    chart = _chart(
        states=[_state("ST", _status(_uuid(17), "s"))],
    )
    sv = _emit(chart, peripheral_name="P")["sos_regfile_P.sv"]
    assert ".ack(1'b0)" in sv


def test_decode_read_AND_gates_zone_match():
    """Gate (e) + INV-S-MEM-E-3: decode_<name>_read is the conjunction of
    addr_match AND zone_match AND access_type_read_ok AND bus_read_valid.

    A non-matching-zone read does NOT fire decode_<name>_read by
    construction — the AND-gate forces a `0`.
    """
    chart = _chart(
        states=[_state("ST", _status(_uuid(18), "s"))],
    )
    sv = _emit(chart, peripheral_name="P")["sos_regfile_P.sv"]
    # Conjunction includes zone_match_s.
    assert "decode_s_read" in sv
    assert "zone_match_s" in sv
    # The decode line uses bitwise AND across all four predicates.
    decode_block = sv[sv.find("wire decode_s_read"):]
    decode_block = decode_block[:decode_block.find(";") + 1]
    for token in ("bus_read_valid", "addr_match_s",
                  "zone_match_s", "access_type_read_ok_s"):
        assert token in decode_block, f"missing {token} in decode line"


# ---------------------------------------------------------------------------
# Gate (f) — access-violation strobe aggregation per privilege_region
# ---------------------------------------------------------------------------


def test_one_strobe_latch_per_privilege_region():
    """Gate (f) / PCDN-SOS-09-E-003(a): each ``sos:privilege_region``
    yields exactly one ``sos_strobe_latch`` instance for the OR-aggregated
    access-violation strobes from member channels.
    """
    chart = _chart(
        states=[
            _state("A", _status(_uuid(20), "a", privilege_region="core")),
            _state("B", _command(_uuid(21), "b", privilege_region="core")),
            _state("C", _status(_uuid(22), "c", privilege_region="dma",
                                zone="unprivileged")),
        ],
    )
    view = build_view(_parse(chart), peripheral_name="P")
    assert {r.name for r in view.privilege_regions} == {"core", "dma"}

    sv = _emit(chart, peripheral_name="P")["sos_regfile_P.sv"]
    # Exactly two violation-latch instances.
    assert sv.count("u_violation_latch_") == 2
    assert "u_violation_latch_core" in sv
    assert "u_violation_latch_dma" in sv
    # Member channels feed into the right OR aggregator.
    core_idx = sv.find("violation_or_core")
    core_block = sv[core_idx:sv.find(";", core_idx)]
    assert "access_violation_a" in core_block
    assert "access_violation_b" in core_block
    assert "access_violation_c" not in core_block  # belongs to dma


def test_unannotated_channels_share_default_region():
    """Gate (f) / SOS-09-A amendment 2026-05-26: channels without
    ``sos:privilege_region`` fall back to ``DEFAULT_PRIVILEGE_REGION``
    and aggregate into a single strobe-latch."""
    chart = _chart(
        states=[
            _state("A", _status(_uuid(23), "a")),
            _state("B", _command(_uuid(24), "b")),
        ],
    )
    view = build_view(_parse(chart), peripheral_name="P")
    regions = {r.name for r in view.privilege_regions}
    assert regions == {DEFAULT_PRIVILEGE_REGION}
    sv = _emit(chart, peripheral_name="P")["sos_regfile_P.sv"]
    assert sv.count("u_violation_latch_") == 1


def test_violation_aggregator_does_not_cross_region_boundary():
    """Gate (f): the per-region OR-tree contains ONLY its members; channels
    in a different privilege_region are NOT folded into the same latch.
    """
    chart = _chart(
        states=[
            _state("X", _status(_uuid(25), "x", privilege_region="r1")),
            _state("Y", _status(_uuid(26), "y", privilege_region="r2",
                                zone="unprivileged")),
        ],
    )
    view = build_view(_parse(chart), peripheral_name="P")
    by_region = {r.name: r.member_channel_names for r in view.privilege_regions}
    assert by_region["r1"] == ("x",)
    assert by_region["r2"] == ("y",)


# ---------------------------------------------------------------------------
# Gate (g) — language parity (VHDL + SV structurally consistent)
# ---------------------------------------------------------------------------


def test_language_parity_channel_set_matches():
    """Gate (g) / INV-S-MEM-E-5: the channel set declared in VHDL and SV
    emissions of the same chart is identical (same names, same kinds)."""
    files = emit_regfile_from_chart(_FIXTURE_CHART, peripheral_name="Demo")
    sv = files["sos_regfile_Demo.sv"]
    vhd = files["sos_regfile_Demo.vhd"]

    # Each channel emits hw_<name>_<port> in both languages.
    for ch_name in ("rx_status", "tx_command", "io_queue",
                    "shared_block", "dma_status"):
        assert f"hw_{ch_name}" in sv, f"missing hw_{ch_name} in SV"
        assert f"hw_{ch_name}" in vhd, f"missing hw_{ch_name} in VHDL"


def test_language_parity_register_offsets_match():
    """Gate (g): per-channel REG_OFFSET_<name> constants carry the same
    byte offset in both languages (INV-S-MEM-E-5 + INV-S-MEM-E-6)."""
    files = emit_regfile_from_chart(_FIXTURE_CHART, peripheral_name="Demo")
    sv = files["sos_regfile_Demo.sv"]
    vhd = files["sos_regfile_Demo.vhd"]

    # SV form: ``localparam [ADDR_W-1:0] REG_OFFSET_RX_STATUS = 0;``
    sv_offsets = dict(re.findall(
        r"localparam \[ADDR_W-1:0\] REG_OFFSET_(\w+) = (\d+);", sv
    ))
    # VHDL form: ``constant REG_OFFSET_RX_STATUS : ... to_unsigned(0, 32);``
    vhd_offsets = dict(re.findall(
        r"constant REG_OFFSET_(\w+) : unsigned\(31 downto 0\) "
        r":= to_unsigned\((\d+), 32\);",
        vhd,
    ))
    assert sv_offsets == vhd_offsets
    assert sv_offsets, "no register offsets emitted"


def test_language_parity_privilege_region_aggregators_match():
    """Gate (g): the privilege_region set + member assignment is identical
    between VHDL and SV emissions."""
    files = emit_regfile_from_chart(_FIXTURE_CHART, peripheral_name="Demo")
    sv = files["sos_regfile_Demo.sv"]
    vhd = files["sos_regfile_Demo.vhd"]
    sv_regions = set(re.findall(r"u_violation_latch_(\w+)", sv))
    vhd_regions = set(re.findall(r"u_violation_latch_(\w+)", vhd))
    assert sv_regions == vhd_regions
    assert sv_regions, "no privilege regions emitted"


# ---------------------------------------------------------------------------
# Gate (h) — SVD-offset match (INV-S-MEM-E-6)
# ---------------------------------------------------------------------------


def test_svd_offsets_match_rtl_offsets_on_fixture():
    """Gate (h) / INV-S-MEM-E-6: the byte offset emitted into the SVD
    by SOS-09-B for a given channel is byte-identical to the offset
    consumed by SOS-09-E's bus-decode logic."""
    annotations = parse_chart_annotations(
        # Reuse the SV emitter's chart loader path.
        __import__("loader").load_chart(_FIXTURE_CHART).raw_scjson
    )
    view = build_view(annotations, peripheral_name="Demo")
    svd_text = emit_svd(annotations, device_name="Demo")
    # Parse <name> + <addressOffset> pairs out of the SVD.
    name_re = re.compile(
        r"<register>.*?<name>(\w+)</name>"
        r".*?<addressOffset>0x([0-9A-Fa-f]+)</addressOffset>",
        re.DOTALL,
    )
    svd_offsets = {
        name: int(off_hex, 16)
        for name, off_hex in name_re.findall(svd_text)
    }
    # Cross-check: every channel name in the view appears in the SVD with
    # matching offset.
    for ch in view.channels:
        assert ch.name in svd_offsets, f"SVD missing {ch.name!r}"
        assert svd_offsets[ch.name] == ch.offset_bytes, (
            f"INV-S-MEM-E-6 violation on {ch.name!r}: "
            f"RTL=0x{ch.offset_bytes:x} SVD=0x{svd_offsets[ch.name]:x}"
        )
    # And the helper enforces it without raising.
    assert_svd_offsets_match(view, svd_offsets)


def test_assert_svd_offsets_match_raises_on_drift():
    """Gate (h) negative case: forced drift triggers a hard error."""
    chart = _chart(states=[_state("X", _status(_uuid(30), "x"))])
    view = build_view(_parse(chart), peripheral_name="P")
    with pytest.raises(Sos09RegfileError):
        assert_svd_offsets_match(view, {"x": 0xDEAD})


# ---------------------------------------------------------------------------
# INV-S-MEM-E-1 — duplicate-name + duplicate-offset rejection
# ---------------------------------------------------------------------------


def test_duplicate_channel_name_rejected_by_emitter():
    """INV-S-MEM-E-1: two channels with the same name → build-stop.

    SOS-09-A enforces this upstream at chart-parse time (§5.4(1) name
    uniqueness), so an emitter-level test must bypass the parser and
    feed a forged ``ChartAnnotations``. SOS-09-E adds its own defensive
    check (per §6 INV-S-MEM-E-1) — this asserts the defensive layer
    actually fires.
    """
    forged = ChartAnnotations(
        channels=(
            ChannelAnnotation(
                id=_uuid(31), name="dup", kind="status", dir="hw→sw",
            ),
            ChannelAnnotation(
                id=_uuid(32), name="dup", kind="status", dir="hw→sw",
            ),
        ),
    )
    with pytest.raises(Sos09RegfileError):
        emit_regfile(forged, peripheral_name="P")


# ---------------------------------------------------------------------------
# PCDN-SOS-09-E-004(a) — cross-clock-domain channels get sync insertion
# ---------------------------------------------------------------------------


def test_cross_clock_domain_command_inserts_synchronizer():
    """PCDN-SOS-09-E-004(a): a channel with ``sos:clock_domain`` !=
    bus_clock_domain triggers ``sos_synchronizer`` insertion on its
    fire/req path."""
    chart = _chart(
        states=[_state("CMD", _command(_uuid(33), "xc",
                                       clock_domain="hw_clk"))],
    )
    sv = _emit(chart, peripheral_name="P", bus_clock_domain="bus")["sos_regfile_P.sv"]
    # Look for the synchronizer INSTANCE (not the header comment cite).
    assert "u_sync_xc_fire" in sv
    assert "sos_synchronizer #(.WIDTH(1), .STAGES(2)) u_sync_xc_fire" in sv


def test_same_clock_domain_does_not_insert_synchronizer():
    """PCDN-SOS-09-E-004(a): channels in the bus domain don't get
    a ``sos_synchronizer`` instance on the fire strobe."""
    chart = _chart(
        states=[_state("CMD", _command(_uuid(34), "ic"))],
    )
    sv = _emit(chart, peripheral_name="P", bus_clock_domain="bus")["sos_regfile_P.sv"]
    # No synchronizer INSTANCE (the header comment may mention the term).
    assert "u_sync_ic_fire" not in sv
    assert "sos_synchronizer #(" not in sv


# ---------------------------------------------------------------------------
# PCDN-SOS-09-E-002(a) — reserved bits read as zero
# ---------------------------------------------------------------------------


def test_reserved_bits_excluded_from_read_mask_via_emit_text():
    """PCDN-SOS-09-E-002(a) + gate (d): the emitted READ_MASK has zeros at
    reserved bit positions."""
    layout = {
        "fields": [
            {"name": "lo", "start_bit": 0, "width": 8, "access": "RO",
             "side_effect": None, "reset_value": 0},
            {"name": "rsv", "start_bit": 8, "width": 24, "access": "reserved",
             "side_effect": None, "reset_value": 0},
        ],
    }
    chart = _chart(
        states=[_state("ST", _status(_uuid(35), "s", bit_layout=layout))],
    )
    sv = _emit(chart, peripheral_name="P")["sos_regfile_P.sv"]
    # READ_MASK_S = 0x000000FF (only the declared RO field).
    assert "READ_MASK_S  = 32'h000000FF" in sv


# ---------------------------------------------------------------------------
# §13 cite — view exposes pcdn_citations for source-trace audits
# ---------------------------------------------------------------------------


def test_view_carries_six_pcdn_citations():
    """The RegfileView surfaces all six PCDN-E citations for §13-style
    @spec block audits."""
    chart = _chart(states=[_state("S", _status(_uuid(40), "s"))])
    view = build_view(_parse(chart), peripheral_name="P")
    # All six ratified PCDNs cited textually.
    joined = " ".join(view.pcdn_citations)
    for n in range(1, 7):
        assert f"PCDN-SOS-09-E-00{n}" in joined


# ---------------------------------------------------------------------------
# Gate (i) — synthesis-tool coverage (Yosys parse-only)
# ---------------------------------------------------------------------------


def test_yosys_parse_only_emission():
    """Gate (i) / SOS-09-E §5.6: if Yosys is on PATH, attempt a
    parse-only synth of the SV emission. Skip with reason otherwise.

    Parse-only mode: ``yosys -p 'read_verilog -sv <file>; hierarchy
    -check'`` — exercises the SV-2017 frontend without requiring the
    L0 primitive sources to be elaborated. The L0 modules are declared
    extern at the emission boundary; a full structural elaboration
    would require pulling in ``rtl/sos_*/`` sources, which is outside
    the per-phase emit-only acceptance gate (membrane vectors in
    SOS-09-F own the elaborated synthesis path).
    """
    yosys = shutil.which("yosys")
    if yosys is None:
        pytest.skip(
            "Yosys not on PATH; gate (i) defers to membrane-vector "
            "harness in SOS-09-F per §12 conformance text."
        )

    files = emit_regfile_from_chart(_FIXTURE_CHART, peripheral_name="Demo")
    sv_text = files["sos_regfile_Demo.sv"]
    out = _TOOLS_DIR / "tests" / "fixtures" / "sos_09_e" / "_yosys_smoke.sv"
    out.write_text(sv_text, encoding="utf-8")
    try:
        result = subprocess.run(
            [yosys, "-q", "-p", f"read_verilog -sv {out}"],
            capture_output=True, text=True, timeout=60,
        )
        # parse-only acceptance: Yosys exits 0 and reports no fatal error.
        assert result.returncode == 0, (
            f"Yosys parse-only failed: "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
    finally:
        try:
            out.unlink()
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------------------
# Walker integration — exposes regfile emit from the existing entry points
# ---------------------------------------------------------------------------


def test_vhdl_walker_exposes_render_regfile_vhdl():
    """The existing VHDL walker module gains a ``render_regfile_vhdl``
    entry point that emits the SOS-09-E artifact (gate j @spec cite)."""
    import transliterate_hdl_vhdl as walker
    chart = _chart(states=[_state("S", _status(_uuid(50), "s"))])
    files = walker.render_regfile_vhdl(chart, {"peripheral_name": "P"})
    assert set(files) == {"sos_regfile_P.vhd"}


def test_sv_walker_exposes_render_regfile_sv():
    """Sibling test for the SV walker."""
    import transliterate_hdl_sv as walker
    chart = _chart(states=[_state("S", _status(_uuid(51), "s"))])
    files = walker.render_regfile_sv(chart, {"peripheral_name": "P"})
    assert set(files) == {"sos_regfile_P.sv"}
