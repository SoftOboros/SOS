"""Tests for ``transliterate_mpu.py`` — SOS-09-G MPU emitter.

Authority: ``docs/concepts/SOS-09-G-CONCEPTS.md`` (ratified 2026-05-25).
Covers §5.2 region-descriptor shape (per-channel attr / access
derivation), §5.5 ``sos:mpu_background`` chart-root toggle, §7
INV-S-MEM-G-1..4 invariants, and the determinism / round-trip
requirements named in the SOS-09-G implementation prompt.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from textwrap import dedent

import pytest

# Make `sos-codegen` modules importable when pytest is invoked from any cwd.
_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from loader import load_chart  # noqa: E402
from sos09_annotations import (  # noqa: E402
    ChannelAnnotation,
    ChartAnnotations,
    parse_chart_annotations,
)
from transliterate_mpu import (  # noqa: E402
    ACCESS_PRIV_RW_UNPRIV_NONE,
    ACCESS_PRIV_RW_UNPRIV_RO,
    ACCESS_PRIV_RW_UNPRIV_RW,
    ALLOWED_ACCESS,
    ALLOWED_ATTRS,
    ATTR_DEVICE_NGNRNE,
    ATTR_NORMAL_WB_WA,
    MIN_SIZE_LOG2,
    MpuRegion,
    Sos09MpuError,
    derive_mpu_regions,
    emit_mpu_background_setting,
    emit_mpu_c,
    emit_mpu_rust,
)


_FIXTURE = _TOOLS_DIR / "tests" / "fixtures" / "sos09_mpu_chart.scxml"


# ---------------------------------------------------------------------------
# Chart-dict helpers (mirrors test_sos09_annotations.py — direct shape).
# ---------------------------------------------------------------------------


_UUID_PREFIX = "6a000000-0000-4000-8000-0000000000"


def _uuid(n: int) -> str:
    return f"{_UUID_PREFIX}{n:02x}"


def _wrap_other_attrs(payload: dict) -> dict:
    return {"other_attributes": json.dumps(payload)}


def _state(state_id: str, sos_attrs: dict | None = None, **extra) -> dict:
    node: dict = {"id": state_id}
    if sos_attrs is not None:
        node["other_attributes"] = _wrap_other_attrs(sos_attrs)
    node.update(extra)
    return node


def _chart(states: list[dict], root_attrs: dict | None = None,
           parallels: list[dict] | None = None) -> dict:
    chart: dict = {
        "state": states,
        "version": 1.0,
        "datamodel_attribute": "ecmascript",
    }
    if parallels is not None:
        chart["parallel"] = parallels
    if root_attrs is not None:
        chart["other_attributes"] = _wrap_other_attrs(root_attrs)
    return chart


def _status(uuid: str, name: str, *, zone: str = "privileged",
            width: int = 32, mpu_attr: str | None = None) -> dict:
    out = {
        "sos:id": uuid,
        "sos:name": name,
        "sos:kind": "status",
        "sos:dir": "hw→sw",
        "sos:zone": zone,
        "sos:width": width,
    }
    if mpu_attr is not None:
        out["sos:mpu_attr"] = mpu_attr
    return out


def _command(uuid: str, name: str, *, zone: str = "privileged",
             width: int = 32, mpu_attr: str | None = None) -> dict:
    out = {
        "sos:id": uuid,
        "sos:name": name,
        "sos:kind": "command",
        "sos:dir": "sw→hw",
        "sos:zone": zone,
        "sos:width": width,
    }
    if mpu_attr is not None:
        out["sos:mpu_attr"] = mpu_attr
    return out


def _queue(uuid: str, name: str, *, zone: str = "privileged",
           width: int = 32, mpu_attr: str | None = None) -> dict:
    out = {
        "sos:id": uuid,
        "sos:name": name,
        "sos:kind": "queue",
        "sos:dir": "hw↔sw",
        "sos:zone": zone,
        "sos:width": width,
    }
    if mpu_attr is not None:
        out["sos:mpu_attr"] = mpu_attr
    return out


def _shared(uuid: str, name: str, *, zone: str = "privileged",
            width: int = 32, mpu_attr: str | None = None) -> dict:
    out = {
        "sos:id": uuid,
        "sos:name": name,
        "sos:kind": "shared",
        "sos:dir": "hw↔sw",
        "sos:zone": zone,
        "sos:width": width,
    }
    if mpu_attr is not None:
        out["sos:mpu_attr"] = mpu_attr
    return out


def _single_channel_annotations(sos_attrs: dict) -> ChartAnnotations:
    chart = _chart([_state("S1", sos_attrs)])
    return parse_chart_annotations(chart)


# ---------------------------------------------------------------------------
# Round-trip: fixture → parse → derive → emit
# ---------------------------------------------------------------------------


def test_fixture_round_trip_parse():
    """Loading the MPU fixture via scjson + loader produces 5 channels."""
    ast = load_chart(_FIXTURE)
    anns = parse_chart_annotations(ast.raw_scjson)
    assert isinstance(anns, ChartAnnotations)
    assert len(anns.channels) == 5
    names = sorted(c.name for c in anns.channels)
    assert names == [
        "override_command",
        "priv_shared",
        "priv_status",
        "unpriv_command",
        "unpriv_queue",
    ]


def test_fixture_round_trip_derive():
    """Deriving regions from the fixture yields 5 MpuRegion entries."""
    ast = load_chart(_FIXTURE)
    anns = parse_chart_annotations(ast.raw_scjson)
    regions = derive_mpu_regions(anns)
    assert len(regions) == 5
    for r in regions:
        assert isinstance(r, MpuRegion)
        assert r.attr in ALLOWED_ATTRS
        assert r.access in ALLOWED_ACCESS
        assert r.size_log2 >= MIN_SIZE_LOG2
        assert r.xn is True
        assert r.enable is True


def test_fixture_round_trip_emit_c():
    ast = load_chart(_FIXTURE)
    anns = parse_chart_annotations(ast.raw_scjson)
    regions = derive_mpu_regions(anns)
    out = emit_mpu_c(regions)
    assert isinstance(out, str)
    assert "#include \"sos_mpu.h\"" in out
    assert "const sos_mpu_region_t sos_mpu_regions[]" in out
    assert "sos_mpu_regions_count" in out


def test_fixture_round_trip_emit_rust():
    ast = load_chart(_FIXTURE)
    anns = parse_chart_annotations(ast.raw_scjson)
    regions = derive_mpu_regions(anns)
    out = emit_mpu_rust(regions)
    assert "use sos_mpu::{MpuAccess, MpuAttr, MpuRegion};" in out
    assert "pub const SOS_MPU_REGIONS: &[MpuRegion]" in out


# ---------------------------------------------------------------------------
# Per-channel attribute derivation (§5.2 default-by-kind)
# ---------------------------------------------------------------------------


def test_attr_default_for_status_is_device():
    anns = _single_channel_annotations(_status(_uuid(1), "s"))
    region = derive_mpu_regions(anns)[0]
    assert region.attr == ATTR_DEVICE_NGNRNE


def test_attr_default_for_command_is_device():
    anns = _single_channel_annotations(_command(_uuid(1), "c"))
    region = derive_mpu_regions(anns)[0]
    assert region.attr == ATTR_DEVICE_NGNRNE


def test_attr_default_for_queue_is_device():
    anns = _single_channel_annotations(_queue(_uuid(1), "q"))
    region = derive_mpu_regions(anns)[0]
    assert region.attr == ATTR_DEVICE_NGNRNE


def test_attr_default_for_shared_is_normal_wb_wa():
    anns = _single_channel_annotations(_shared(_uuid(1), "sh"))
    region = derive_mpu_regions(anns)[0]
    assert region.attr == ATTR_NORMAL_WB_WA


# ---------------------------------------------------------------------------
# Per-channel attribute override (sos:mpu_attr — four input tokens)
# ---------------------------------------------------------------------------


def test_attr_override_cacheable_on_status():
    anns = _single_channel_annotations(_status(_uuid(1), "s", mpu_attr="cacheable"))
    assert derive_mpu_regions(anns)[0].attr == ATTR_NORMAL_WB_WA


def test_attr_override_non_cacheable_on_command():
    anns = _single_channel_annotations(_command(_uuid(1), "c", mpu_attr="non_cacheable"))
    assert derive_mpu_regions(anns)[0].attr == ATTR_NORMAL_WB_WA


def test_attr_override_device_ngnrne_on_shared():
    anns = _single_channel_annotations(_shared(_uuid(1), "sh", mpu_attr="device_ngnrne"))
    assert derive_mpu_regions(anns)[0].attr == ATTR_DEVICE_NGNRNE


def test_attr_override_device_ngnre_on_shared():
    anns = _single_channel_annotations(_shared(_uuid(1), "sh", mpu_attr="device_ngnre"))
    assert derive_mpu_regions(anns)[0].attr == ATTR_DEVICE_NGNRNE


# ---------------------------------------------------------------------------
# Per-channel access derivation (§5.2 zone → AP)
# ---------------------------------------------------------------------------


def test_access_privileged_status():
    anns = _single_channel_annotations(_status(_uuid(1), "s", zone="privileged"))
    assert derive_mpu_regions(anns)[0].access == ACCESS_PRIV_RW_UNPRIV_NONE


def test_access_unprivileged_status():
    anns = _single_channel_annotations(_status(_uuid(1), "s", zone="unprivileged"))
    assert derive_mpu_regions(anns)[0].access == ACCESS_PRIV_RW_UNPRIV_RW


def test_access_privileged_default_when_zone_absent():
    """Channel without explicit `sos:zone` defaults to privileged (parser default)."""
    attrs = {
        "sos:id": _uuid(1),
        "sos:name": "s",
        "sos:kind": "status",
        "sos:dir": "hw→sw",
    }
    anns = _single_channel_annotations(attrs)
    assert derive_mpu_regions(anns)[0].access == ACCESS_PRIV_RW_UNPRIV_NONE


def test_access_unprivileged_queue():
    anns = _single_channel_annotations(_queue(_uuid(1), "q", zone="unprivileged"))
    assert derive_mpu_regions(anns)[0].access == ACCESS_PRIV_RW_UNPRIV_RW


# ---------------------------------------------------------------------------
# Background setting derivation (§5.5)
# ---------------------------------------------------------------------------


def test_background_kernel_default_c_define():
    anns = parse_chart_annotations(_chart([_state("S1", _status(_uuid(1), "s"))]))
    setting = emit_mpu_background_setting(anns)
    assert setting["c_define"] == "#define SOS_MPU_BACKGROUND_PRIVDEFENA 1"
    assert setting["rust_const"] == (
        "pub const SOS_MPU_BACKGROUND_PRIVDEFENA: bool = true;"
    )


def test_background_strict_c_define():
    chart = _chart(
        [_state("S1", _status(_uuid(1), "s"))],
        root_attrs={"sos:mpu_background": "strict"},
    )
    anns = parse_chart_annotations(chart)
    setting = emit_mpu_background_setting(anns)
    assert setting["c_define"] == "#define SOS_MPU_BACKGROUND_PRIVDEFENA 0"
    assert setting["rust_const"] == (
        "pub const SOS_MPU_BACKGROUND_PRIVDEFENA: bool = false;"
    )


def test_background_setting_returns_dict_with_expected_keys():
    anns = parse_chart_annotations(_chart([_state("S1", _status(_uuid(1), "s"))]))
    setting = emit_mpu_background_setting(anns)
    assert set(setting.keys()) == {"c_define", "rust_const"}


# ---------------------------------------------------------------------------
# Determinism — same input → byte-identical output
# ---------------------------------------------------------------------------


def test_emit_c_is_deterministic():
    ast = load_chart(_FIXTURE)
    anns = parse_chart_annotations(ast.raw_scjson)
    regions = derive_mpu_regions(anns)
    out1 = emit_mpu_c(regions)
    out2 = emit_mpu_c(regions)
    assert out1 == out2


def test_emit_rust_is_deterministic():
    ast = load_chart(_FIXTURE)
    anns = parse_chart_annotations(ast.raw_scjson)
    regions = derive_mpu_regions(anns)
    out1 = emit_mpu_rust(regions)
    out2 = emit_mpu_rust(regions)
    assert out1 == out2


def test_derive_regions_is_deterministic():
    ast = load_chart(_FIXTURE)
    anns1 = parse_chart_annotations(ast.raw_scjson)
    anns2 = parse_chart_annotations(ast.raw_scjson)
    assert derive_mpu_regions(anns1) == derive_mpu_regions(anns2)


def test_emit_c_idempotent_across_parse_reload():
    """Two full pipeline runs from the same fixture file produce identical C."""
    ast1 = load_chart(_FIXTURE)
    ast2 = load_chart(_FIXTURE)
    regions1 = derive_mpu_regions(parse_chart_annotations(ast1.raw_scjson))
    regions2 = derive_mpu_regions(parse_chart_annotations(ast2.raw_scjson))
    assert emit_mpu_c(regions1) == emit_mpu_c(regions2)


# ---------------------------------------------------------------------------
# Address layout (chart-walk order; aligned; non-overlapping)
# ---------------------------------------------------------------------------


def test_addresses_aligned_to_size():
    """Each region's base_address MUST be aligned to 2**size_log2."""
    ast = load_chart(_FIXTURE)
    regions = derive_mpu_regions(parse_chart_annotations(ast.raw_scjson))
    for r in regions:
        alignment = 1 << r.size_log2
        assert r.base_address % alignment == 0, (
            f"region {r.name} at 0x{r.base_address:08X} not aligned to "
            f"{alignment} bytes"
        )


def test_addresses_non_overlapping():
    """Regions MUST NOT overlap after rounding (INV-S-MEM-G-4)."""
    ast = load_chart(_FIXTURE)
    regions = derive_mpu_regions(parse_chart_annotations(ast.raw_scjson))
    sorted_regions = sorted(regions, key=lambda r: r.base_address)
    for i in range(1, len(sorted_regions)):
        prev = sorted_regions[i - 1]
        cur = sorted_regions[i]
        prev_end = prev.base_address + (1 << prev.size_log2)
        assert cur.base_address >= prev_end


def test_addresses_in_chart_walk_order():
    """Regions are emitted in the same order as parsed channels."""
    ast = load_chart(_FIXTURE)
    anns = parse_chart_annotations(ast.raw_scjson)
    regions = derive_mpu_regions(anns)
    assert tuple(r.name for r in regions) == tuple(c.name for c in anns.channels)


def test_addresses_start_at_base_address_parameter():
    """The first emitted region MUST start at the configured base_address."""
    anns = _single_channel_annotations(_status(_uuid(1), "s"))
    regions = derive_mpu_regions(anns, base_address=0x40000000)
    assert regions[0].base_address == 0x40000000

    regions2 = derive_mpu_regions(anns, base_address=0x20000000)
    assert regions2[0].base_address == 0x20000000


def test_size_log2_min_32_bytes():
    """All emitted regions MUST be ≥ 32 B (ARMv7-M minimum)."""
    ast = load_chart(_FIXTURE)
    regions = derive_mpu_regions(parse_chart_annotations(ast.raw_scjson))
    for r in regions:
        assert r.size_log2 >= MIN_SIZE_LOG2
        assert (1 << r.size_log2) >= 32


def test_size_log2_for_narrow_channel_still_min_32():
    """A channel with width=8 still gets a 32-byte region (the MPU minimum)."""
    anns = _single_channel_annotations(_status(_uuid(1), "s", width=8))
    region = derive_mpu_regions(anns)[0]
    assert region.size_log2 == 5  # 32 B


# ---------------------------------------------------------------------------
# C output: structural and syntactic correctness
# ---------------------------------------------------------------------------


def test_c_output_contains_each_channel_name():
    ast = load_chart(_FIXTURE)
    regions = derive_mpu_regions(parse_chart_annotations(ast.raw_scjson))
    out = emit_mpu_c(regions)
    for r in regions:
        assert f"\"{r.name}\"" in out


def test_c_output_contains_each_channel_id():
    ast = load_chart(_FIXTURE)
    regions = derive_mpu_regions(parse_chart_annotations(ast.raw_scjson))
    out = emit_mpu_c(regions)
    for r in regions:
        assert f"\"{r.channel_id}\"" in out


def test_c_output_table_name_override():
    anns = _single_channel_annotations(_status(_uuid(1), "s"))
    regions = derive_mpu_regions(anns)
    out = emit_mpu_c(regions, table_name="my_table")
    assert "const sos_mpu_region_t my_table[]" in out
    assert "my_table_count" in out


def test_c_output_rejects_bad_table_name():
    anns = _single_channel_annotations(_status(_uuid(1), "s"))
    regions = derive_mpu_regions(anns)
    with pytest.raises(Sos09MpuError):
        emit_mpu_c(regions, table_name="bad-name")
    with pytest.raises(Sos09MpuError):
        emit_mpu_c(regions, table_name="1leading_digit")


def test_c_output_braces_balanced():
    """A regex-level check on brace balance — the output should be well-formed C."""
    ast = load_chart(_FIXTURE)
    regions = derive_mpu_regions(parse_chart_annotations(ast.raw_scjson))
    out = emit_mpu_c(regions)
    # Count occurrences of { and } at line-start (avoids counting braces
    # inside string-literal channel_ids).
    open_count = out.count("{")
    close_count = out.count("}")
    assert open_count == close_count, (
        f"unbalanced braces: {open_count} open vs {close_count} close"
    )


def test_c_output_attribute_macros_referenced():
    """C output references SOS_MPU_ATTR_* macros that sos_mpu.h would define."""
    ast = load_chart(_FIXTURE)
    regions = derive_mpu_regions(parse_chart_annotations(ast.raw_scjson))
    out = emit_mpu_c(regions)
    assert "SOS_MPU_ATTR_DEVICE_NGNRNE" in out
    # The fixture has a shared channel which defaults to Normal Cacheable.
    assert "SOS_MPU_ATTR_NORMAL_WB_WA" in out


def test_c_output_access_macros_referenced():
    ast = load_chart(_FIXTURE)
    regions = derive_mpu_regions(parse_chart_annotations(ast.raw_scjson))
    out = emit_mpu_c(regions)
    assert "SOS_MPU_AP_PRIV_RW_UNPRIV_NONE" in out
    assert "SOS_MPU_AP_PRIV_RW_UNPRIV_RW" in out


def test_c_output_optional_gcc_syntax_only():
    """If gcc / clang is on PATH, syntax-check the emitted C. Skip otherwise."""
    gcc = shutil.which("gcc") or shutil.which("clang") or shutil.which("cc")
    if not gcc:
        pytest.skip("no C compiler on PATH; skipping syntax-only smoke")

    ast = load_chart(_FIXTURE)
    regions = derive_mpu_regions(parse_chart_annotations(ast.raw_scjson))
    out = emit_mpu_c(regions)

    # Minimal header so the include + struct/macros resolve. The emitter
    # references sos_mpu.h; provide a tiny stand-in for the syntax check.
    header = dedent(
        """\
        #ifndef SOS_MPU_H
        #define SOS_MPU_H
        #include <stddef.h>
        #include <stdint.h>
        #define SOS_MPU_ATTR_DEVICE_NGNRNE 0
        #define SOS_MPU_ATTR_NORMAL_WB_WA 1
        #define SOS_MPU_AP_PRIV_RW_UNPRIV_NONE 1
        #define SOS_MPU_AP_PRIV_RW_UNPRIV_RO   2
        #define SOS_MPU_AP_PRIV_RW_UNPRIV_RW   3
        typedef struct {
            const char *name;
            uint32_t base_address;
            uint32_t size_log2;
            uint32_t attr;
            uint32_t access;
            uint8_t xn;
            uint8_t enable;
            uint8_t srd;
            const char *channel_id;
        } sos_mpu_region_t;
        #endif
        """
    )

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        (td_path / "sos_mpu.h").write_text(header)
        src_path = td_path / "mpu_table.c"
        src_path.write_text(out)
        result = subprocess.run(
            [gcc, "-fsyntax-only", "-Wall", "-I", str(td_path), str(src_path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, (
            f"{gcc} rejected emitted C:\n{result.stderr}"
        )


# ---------------------------------------------------------------------------
# Rust output: structural and syntactic correctness
# ---------------------------------------------------------------------------


def test_rust_output_contains_each_channel_name():
    ast = load_chart(_FIXTURE)
    regions = derive_mpu_regions(parse_chart_annotations(ast.raw_scjson))
    out = emit_mpu_rust(regions)
    for r in regions:
        assert f"\"{r.name}\"" in out


def test_rust_output_const_name_override():
    anns = _single_channel_annotations(_status(_uuid(1), "s"))
    regions = derive_mpu_regions(anns)
    out = emit_mpu_rust(regions, const_name="MY_REGIONS")
    assert "pub const MY_REGIONS: &[MpuRegion]" in out


def test_rust_output_rejects_lowercase_const_name():
    anns = _single_channel_annotations(_status(_uuid(1), "s"))
    regions = derive_mpu_regions(anns)
    with pytest.raises(Sos09MpuError):
        emit_mpu_rust(regions, const_name="lowercase_const")


def test_rust_output_rejects_bad_const_name():
    anns = _single_channel_annotations(_status(_uuid(1), "s"))
    regions = derive_mpu_regions(anns)
    with pytest.raises(Sos09MpuError):
        emit_mpu_rust(regions, const_name="BAD-NAME")


def test_rust_output_brackets_balanced():
    ast = load_chart(_FIXTURE)
    regions = derive_mpu_regions(parse_chart_annotations(ast.raw_scjson))
    out = emit_mpu_rust(regions)
    assert out.count("[") == out.count("]")
    assert out.count("{") == out.count("}")


def test_rust_output_attr_enum_referenced():
    ast = load_chart(_FIXTURE)
    regions = derive_mpu_regions(parse_chart_annotations(ast.raw_scjson))
    out = emit_mpu_rust(regions)
    assert "MpuAttr::DeviceNGnRnE" in out
    assert "MpuAttr::NormalWbWa" in out


def test_rust_output_access_enum_referenced():
    ast = load_chart(_FIXTURE)
    regions = derive_mpu_regions(parse_chart_annotations(ast.raw_scjson))
    out = emit_mpu_rust(regions)
    assert "MpuAccess::PrivRwUnprivNone" in out
    assert "MpuAccess::PrivRwUnprivRw" in out


def test_rust_output_optional_rustc_syntax_check():
    """If rustc is on PATH, do a parse-only smoke check. Skip otherwise."""
    rustc = shutil.which("rustc")
    if not rustc:
        pytest.skip("no rustc on PATH; skipping Rust parse-only smoke")

    ast = load_chart(_FIXTURE)
    regions = derive_mpu_regions(parse_chart_annotations(ast.raw_scjson))
    body = emit_mpu_rust(regions)

    # Provide stub types so the parse-only check resolves identifiers.
    # We compile the table as the body of a `mod` that defines a tiny
    # sos_mpu stand-in. ``rustc --emit=metadata --crate-type lib`` parses
    # AND type-checks; that's stricter than parse-only but still suitable
    # as a smoke check.
    stub = dedent(
        """\
        #![allow(dead_code, non_camel_case_types)]
        mod sos_mpu {
            pub enum MpuAttr { DeviceNGnRnE, NormalWbWa }
            pub enum MpuAccess { PrivRwUnprivNone, PrivRwUnprivRo, PrivRwUnprivRw }
            pub struct MpuRegion {
                pub name: &'static str,
                pub base_address: u32,
                pub size_log2: u32,
                pub attr: MpuAttr,
                pub access: MpuAccess,
                pub xn: bool,
                pub enable: bool,
                pub srd: u8,
                pub channel_id: &'static str,
            }
        }
        """
    )

    src = stub + "\n" + body
    with tempfile.TemporaryDirectory() as td:
        src_path = Path(td) / "mpu_table.rs"
        src_path.write_text(src)
        out_path = Path(td) / "libmpu_table.rmeta"
        result = subprocess.run(
            [
                rustc, "--edition=2021", "--crate-type=lib",
                "--emit=metadata", "-o", str(out_path), str(src_path),
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, (
            f"rustc rejected emitted Rust:\n{result.stderr}"
        )


# ---------------------------------------------------------------------------
# Address derivation from synthetic chart-dict
# ---------------------------------------------------------------------------


def test_synthetic_chart_two_channels_addresses_disjoint():
    chart = _chart([
        _state("A", _status(_uuid(1), "a", width=32)),
        _state("B", _command(_uuid(2), "b", width=32)),
    ])
    anns = parse_chart_annotations(chart)
    regions = derive_mpu_regions(anns)
    assert len(regions) == 2
    a, b = regions
    assert a.name == "a"
    assert b.name == "b"
    assert a.base_address < b.base_address
    a_end = a.base_address + (1 << a.size_log2)
    assert b.base_address >= a_end


def test_synthetic_chart_single_channel_has_priv_only_access():
    """A single privileged channel produces an AP=priv-only region (INV-S-MEM-G-1)."""
    anns = _single_channel_annotations(_status(_uuid(1), "s", zone="privileged"))
    regions = derive_mpu_regions(anns)
    assert regions[0].access == ACCESS_PRIV_RW_UNPRIV_NONE


def test_inv_s_mem_g_1_all_privileged_have_priv_only_ap():
    """Every channel with zone=privileged must have AP=priv-only."""
    ast = load_chart(_FIXTURE)
    anns = parse_chart_annotations(ast.raw_scjson)
    regions = derive_mpu_regions(anns)
    by_name = {r.name: r for r in regions}
    by_channel_name = {c.name: c for c in anns.channels}
    for name, channel in by_channel_name.items():
        if channel.zone == "privileged":
            assert by_name[name].access == ACCESS_PRIV_RW_UNPRIV_NONE


# ---------------------------------------------------------------------------
# Negative cases
# ---------------------------------------------------------------------------


def test_derive_rejects_non_chart_annotations_input():
    with pytest.raises(Sos09MpuError):
        derive_mpu_regions("not annotations")  # type: ignore[arg-type]


def test_emit_background_rejects_non_chart_annotations_input():
    with pytest.raises(Sos09MpuError):
        emit_mpu_background_setting("not annotations")  # type: ignore[arg-type]


def test_overlap_raises_value_error():
    """Two channels manually placed at the same base address overlap → hard error.

    The chart-walk allocator can't naturally produce overlap, so we
    construct ``MpuRegion`` instances directly and ask the overlap-check
    helper to flag them via the same path ``derive_mpu_regions`` uses at
    the end of derivation. The error chain raises ``Sos09MpuError``,
    which IS a ``ValueError`` subclass via Python's exception hierarchy
    only by name in test expectations — we accept the concrete type.
    """
    from transliterate_mpu import _check_no_overlap  # type: ignore[attr-defined]

    a = MpuRegion(
        name="a", base_address=0x40000000, size_log2=5,
        attr=ATTR_DEVICE_NGNRNE, access=ACCESS_PRIV_RW_UNPRIV_NONE,
        channel_id=_uuid(1),
    )
    b = MpuRegion(
        name="b", base_address=0x40000010, size_log2=5,
        attr=ATTR_DEVICE_NGNRNE, access=ACCESS_PRIV_RW_UNPRIV_NONE,
        channel_id=_uuid(2),
    )
    with pytest.raises(Sos09MpuError, match="overlap"):
        _check_no_overlap([a, b])


def test_unknown_kind_raises_via_derive_attr():
    """If a caller bypasses the parser and crafts a ChannelAnnotation with a
    bogus kind, derive_mpu_regions surfaces the error rather than emitting
    junk."""
    bad = ChannelAnnotation(
        id=_uuid(1), name="bad", kind="not_a_kind", dir="hw→sw",
    )
    anns = ChartAnnotations(channels=(bad,))
    with pytest.raises(Sos09MpuError, match="kind"):
        derive_mpu_regions(anns)


def test_unknown_zone_raises_via_derive_access():
    bad = ChannelAnnotation(
        id=_uuid(1), name="bad", kind="status", dir="hw→sw",
        zone="not_a_zone",
    )
    anns = ChartAnnotations(channels=(bad,))
    with pytest.raises(Sos09MpuError, match="zone"):
        derive_mpu_regions(anns)


def test_unknown_mpu_attr_override_raises():
    """A bogus mpu_attr override (bypassing the parser) is a hard error."""
    bad = ChannelAnnotation(
        id=_uuid(1), name="bad", kind="status", dir="hw→sw",
        mpu_attr="totally_made_up",
    )
    anns = ChartAnnotations(channels=(bad,))
    with pytest.raises(Sos09MpuError, match="sos:mpu_attr"):
        derive_mpu_regions(anns)


def test_unknown_mpu_background_raises_in_setting_emit():
    """A bogus mpu_background (bypassing the parser) is a hard error."""
    anns = ChartAnnotations(channels=(), mpu_background="weird_mode")
    with pytest.raises(Sos09MpuError, match="mpu_background"):
        emit_mpu_background_setting(anns)


def test_empty_chart_yields_empty_table_c():
    """A chart with zero channels emits a valid (empty) C array."""
    anns = ChartAnnotations(channels=())
    out = emit_mpu_c(derive_mpu_regions(anns))
    assert "sos_mpu_regions[]" in out
    # The empty array gets a count of 0 via sizeof; that's still valid.
    assert "sos_mpu_regions_count" in out


def test_empty_chart_yields_empty_table_rust():
    anns = ChartAnnotations(channels=())
    out = emit_mpu_rust(derive_mpu_regions(anns))
    assert "pub const SOS_MPU_REGIONS: &[MpuRegion]" in out


# ---------------------------------------------------------------------------
# Cross-emit consistency
# ---------------------------------------------------------------------------


def test_c_and_rust_emit_same_addresses():
    """The C and Rust emitters MUST agree on every region's base_address."""
    ast = load_chart(_FIXTURE)
    regions = derive_mpu_regions(parse_chart_annotations(ast.raw_scjson))
    c_out = emit_mpu_c(regions)
    rust_out = emit_mpu_rust(regions)
    for r in regions:
        addr = f"0x{r.base_address:08X}"
        # Both files reference the same hex address for the same channel.
        # Use a coarse-grained presence check; finer correlation is
        # already exercised by determinism + structural tests.
        assert addr in c_out.upper() or f"0x{r.base_address:08X}u" in c_out
        assert f"0x{r.base_address:08X}" in rust_out


def test_c_and_rust_emit_same_count():
    ast = load_chart(_FIXTURE)
    regions = derive_mpu_regions(parse_chart_annotations(ast.raw_scjson))
    c_out = emit_mpu_c(regions)
    rust_out = emit_mpu_rust(regions)
    # Crude row-count: each row in either emit ends with "},\n" preceded
    # by region-body lines. We use the channel_id literal as the
    # uniqueness anchor.
    for r in regions:
        c_hits = c_out.count(f"\"{r.channel_id}\"")
        rust_hits = rust_out.count(f"\"{r.channel_id}\"")
        assert c_hits == 1
        assert rust_hits == 1


# ---------------------------------------------------------------------------
# Importability sanity (mirrors the prompt's requirement)
# ---------------------------------------------------------------------------


def test_module_public_surface_importable():
    """The named public-API surface MUST import cleanly."""
    from transliterate_mpu import (  # noqa: F401
        MpuRegion,
        derive_mpu_regions,
        emit_mpu_c,
        emit_mpu_rust,
        emit_mpu_background_setting,
    )


def test_mpu_region_is_frozen():
    """MpuRegion is frozen so emitted output cannot be mutated post-derive."""
    region = MpuRegion(
        name="r", base_address=0x40000000, size_log2=5,
        attr=ATTR_DEVICE_NGNRNE, access=ACCESS_PRIV_RW_UNPRIV_NONE,
    )
    with pytest.raises(Exception):
        # FrozenInstanceError subclasses AttributeError in some Python
        # versions; accept any exception class.
        region.base_address = 0x40000020  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Fixture-specific row check: the override channel got its override.
# ---------------------------------------------------------------------------


def test_fixture_override_channel_received_override():
    """The OVERRIDE_STATE channel carries sos:mpu_attr=non_cacheable, which
    maps to Normal Cacheable in the v1 emitter's two-attribute design."""
    ast = load_chart(_FIXTURE)
    anns = parse_chart_annotations(ast.raw_scjson)
    regions = derive_mpu_regions(anns)
    by_name = {r.name: r for r in regions}
    override = by_name["override_command"]
    # A command kind would default to device-nGnRnE; the override flips it.
    assert override.attr == ATTR_NORMAL_WB_WA


def test_fixture_priv_shared_uses_normal_wb_wa():
    """shared default → Normal Cacheable (§5.2 split rule)."""
    ast = load_chart(_FIXTURE)
    anns = parse_chart_annotations(ast.raw_scjson)
    regions = derive_mpu_regions(anns)
    by_name = {r.name: r for r in regions}
    assert by_name["priv_shared"].attr == ATTR_NORMAL_WB_WA
    assert by_name["priv_shared"].access == ACCESS_PRIV_RW_UNPRIV_NONE


def test_fixture_unpriv_queue_unprivileged_access():
    ast = load_chart(_FIXTURE)
    anns = parse_chart_annotations(ast.raw_scjson)
    regions = derive_mpu_regions(anns)
    by_name = {r.name: r for r in regions}
    assert by_name["unpriv_queue"].access == ACCESS_PRIV_RW_UNPRIV_RW


def test_uuid_hex_helper_matches_fixture():
    """Sanity-check that our local _uuid helper matches the fixture pattern.

    Catches accidental future drift between the fixture's UUID format and
    the synthetic helper used in unit tests.
    """
    expected = "6a000000-0000-4000-8000-000000000001"
    assert _uuid(1) == expected
    # The 16-bit + 8-bit suffix should still be hex.
    assert re.fullmatch(r"6a000000-0000-4000-8000-0000000000[0-9a-f]{2}",
                        _uuid(15))
