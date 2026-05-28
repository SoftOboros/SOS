"""Tests for ``c_hal_emit.py`` — SOS-09-C C HAL header emitter.

Authority: ``docs/concepts/SOS-09-C-CONCEPTS.md`` (ratified 2026-05-26)
plus the SOS-09 umbrella concepts doc.

Covers acceptance gates (c)–(j):
    (c) emitter produces ≥1 channel's worth of C HAL content
        (#define ADDR, volatile struct overlay, ≥1 op accessor, ≥1
        static const field constant).
    (d) accessor naming follows ``SOS_C_<channel>_<op>`` derived from
        ``sos:name`` (deterministically).
    (e) ``volatile`` appears on every struct-overlay field.
    (f) side-effect-bearing accessors use ``*_consume_*`` / ``*_fire_*``
        discriminating names; clear-on-read channels emit ``consume``
        NOT ``read``; command channels emit ``fire`` NOT ``write``.
    (g) emitted headers compile clean with ``gcc -Wall -Wextra
        -Wpedantic -std=c11`` AND ``clang -Wall -Wextra -Wpedantic
        -std=c11`` (skip when neither compiler is on PATH).
    (h) channels with ``sos:zone`` annotation emit an ``extern const
        sos_mpu_region_t sos_mpu_<channel>_region;`` declaration.
    (i) byte-identical determinism: two charts differing only in
        ``sos:id`` UUID values produce byte-identical accessor symbols
        (INV-S-MEM-C-5).
    (j) cross-phase invariants citation: the source carries §-citations
        to SOS-09 / SOS-09-A / SOS-09-B / SOS-09-G.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


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
from c_hal_emit import (  # noqa: E402
    emit_c_hal,
    emit_c_hal_from_chart,
)


_FIXTURE = _TOOLS_DIR / "tests" / "fixtures" / "sos_09_c" / "sos09_c_hal_chart.scxml"


# ---------------------------------------------------------------------------
# Chart-dict helpers (mirror test_transliterate_svd shape)
# ---------------------------------------------------------------------------


def _uuid(n: int) -> str:
    return f"8a000000-0000-4000-8000-0000000000{n:02x}"


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


def _status(uuid: str, name: str, *, width: int = 32, zone: str | None = None,
            irq: str | None = None,
            channel_group: str | None = None,
            bit_layout: dict | None = None) -> dict:
    out: dict = {
        "sos:id": uuid,
        "sos:name": name,
        "sos:kind": "status",
        "sos:dir": "hw→sw",
        "sos:width": width,
    }
    if zone is not None:
        out["sos:zone"] = zone
    if irq is not None:
        out["sos:irq"] = irq
    if channel_group is not None:
        out["sos:channel_group"] = channel_group
    if bit_layout is not None:
        out["sos:bit_layout"] = bit_layout
    return out


def _command(uuid: str, name: str, *, width: int = 32,
             channel_group: str | None = None,
             bit_layout: dict | None = None) -> dict:
    out: dict = {
        "sos:id": uuid,
        "sos:name": name,
        "sos:kind": "command",
        "sos:dir": "sw→hw",
        "sos:width": width,
    }
    if channel_group is not None:
        out["sos:channel_group"] = channel_group
    if bit_layout is not None:
        out["sos:bit_layout"] = bit_layout
    return out


def _queue(uuid: str, name: str, *, width: int = 32,
           direction: str = "hw↔sw",
           channel_group: str | None = None) -> dict:
    out: dict = {
        "sos:id": uuid,
        "sos:name": name,
        "sos:kind": "queue",
        "sos:dir": direction,
        "sos:width": width,
    }
    if channel_group is not None:
        out["sos:channel_group"] = channel_group
    return out


def _shared(uuid: str, name: str, *, width: int = 32,
            mutex: str | None = None,
            channel_group: str | None = None) -> dict:
    out: dict = {
        "sos:id": uuid,
        "sos:name": name,
        "sos:kind": "shared",
        "sos:dir": "hw↔sw",
        "sos:width": width,
    }
    if mutex is not None:
        out["sos:mutex"] = mutex
    if channel_group is not None:
        out["sos:channel_group"] = channel_group
    return out


def _parse(chart: dict) -> ChartAnnotations:
    return parse_chart_annotations(chart)


def _emit(chart: dict, *, chart_name: str = "test_chart", **kwargs) -> dict[str, str]:
    return emit_c_hal(_parse(chart), chart_name=chart_name, **kwargs)


# ---------------------------------------------------------------------------
# Fixture-driven smoke
# ---------------------------------------------------------------------------


def test_fixture_emits_umbrella_and_subheaders():
    out = emit_c_hal_from_chart(_FIXTURE, chart_name="sos09_c")
    # Umbrella header is always present.
    assert "sos_sos09_c.h" in out
    # Per-group sub-headers: rx, tx, default (from channels 3..6 without
    # sos:channel_group → fall back to "default").
    assert "sos_sos09_c__rx.h" in out
    assert "sos_sos09_c__tx.h" in out
    assert "sos_sos09_c__default.h" in out


def test_fixture_umbrella_transitively_includes_subheaders():
    out = emit_c_hal_from_chart(_FIXTURE, chart_name="sos09_c")
    umbrella = out["sos_sos09_c.h"]
    assert '#include "sos_sos09_c__rx.h"' in umbrella
    assert '#include "sos_sos09_c__tx.h"' in umbrella
    assert '#include "sos_sos09_c__default.h"' in umbrella


def test_fixture_byte_deterministic():
    a = emit_c_hal_from_chart(_FIXTURE, chart_name="sos09_c")
    b = emit_c_hal_from_chart(_FIXTURE, chart_name="sos09_c")
    assert a == b
    for fname, text in a.items():
        assert text.encode("utf-8") == b[fname].encode("utf-8")


# ---------------------------------------------------------------------------
# Gate (c): minimal emission content
# ---------------------------------------------------------------------------


def test_minimal_emission_carries_define_addr_struct_accessor_field_const():
    bl = {
        "fields": [
            {"name": "f0", "start_bit": 0, "width": 4, "access": "RW",
             "side_effect": None, "reset_value": 0},
        ]
    }
    chart = _chart(states=[_state("S", _status(_uuid(1), "rx_status", bit_layout=bl))])
    out = _emit(chart, chart_name="mini")
    sub = out["sos_mini__default.h"]
    # (c.i) #define register address.
    assert "#define SOS_C_rx_status_ADDR 0x40000000u" in sub
    # (c.ii) volatile-qualified struct overlay typedef.
    assert "typedef struct {" in sub
    assert "volatile uint32_t rx_status;" in sub
    assert "} sos_mini__default_regs_t;" in sub
    # (c.iii) at least one accessor.
    assert "static inline uint32_t SOS_C_rx_status_read(" in sub
    # (c.iv) static const field shift+mask.
    assert "static const unsigned SOS_C_rx_status_F0_SHIFT" in sub
    assert "static const unsigned SOS_C_rx_status_F0_MASK" in sub


# ---------------------------------------------------------------------------
# Gate (d): SOS_C_<channel>_<op> naming derived from sos:name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind_helper,expected_op",
    [
        (lambda: _status(_uuid(1), "s_ch"), "read"),
        (lambda: _command(_uuid(2), "c_ch"), "fire"),
        (lambda: _queue(_uuid(3), "q_ch"), "read"),
        (lambda: _shared(_uuid(4), "sh_ch"), "claim"),
    ],
)
def test_accessor_naming_follows_convention(kind_helper, expected_op):
    chart = _chart(states=[_state("S", kind_helper())])
    out = _emit(chart, chart_name="naming")
    sub = out["sos_naming__default.h"]
    # The op name appears as part of SOS_C_<channel>_<op>.
    ch_name = kind_helper()["sos:name"]
    assert f"SOS_C_{ch_name}_{expected_op}" in sub


def test_each_kind_emits_its_full_op_set():
    """One channel per kind, verify the emitted-op set is correct."""
    chart = _chart(states=[
        _state("A", _status(_uuid(0xA1), "s_ch")),
        _state("B", _command(_uuid(0xA2), "c_ch")),
        _state("C", _queue(_uuid(0xA3), "q_ch")),
        _state("D", _shared(_uuid(0xA4), "sh_ch")),
    ])
    out = _emit(chart, chart_name="ops")
    sub = out["sos_ops__default.h"]
    # status -> read only (no clear-on-read).
    assert "SOS_C_s_ch_read(" in sub
    assert "SOS_C_s_ch_consume(" not in sub
    assert "SOS_C_s_ch_write(" not in sub
    assert "SOS_C_s_ch_fire(" not in sub
    # command -> fire only.
    assert "SOS_C_c_ch_fire(" in sub
    assert "SOS_C_c_ch_write(" not in sub
    assert "SOS_C_c_ch_read(" not in sub
    # queue -> read + write.
    assert "SOS_C_q_ch_read(" in sub
    assert "SOS_C_q_ch_write(" in sub
    assert "SOS_C_q_ch_consume(" not in sub
    assert "SOS_C_q_ch_fire(" not in sub
    # shared -> read + write + claim + release.
    assert "SOS_C_sh_ch_read(" in sub
    assert "SOS_C_sh_ch_write(" in sub
    assert "SOS_C_sh_ch_claim(" in sub
    assert "SOS_C_sh_ch_release(" in sub


# ---------------------------------------------------------------------------
# Gate (e): volatile on every struct-overlay field
# ---------------------------------------------------------------------------


def test_struct_overlay_volatile_on_every_field():
    chart = _chart(states=[
        _state("A", _status(_uuid(0xB1), "s32", width=32)),
        _state("B", _command(_uuid(0xB2), "c16", width=16)),
        _state("C", _queue(_uuid(0xB3), "q8", width=8)),
    ])
    out = _emit(chart, chart_name="vol")
    sub = out["sos_vol__default.h"]
    # Every struct member uses the volatile-qualified type.
    assert "volatile uint32_t s32;" in sub
    assert "volatile uint16_t c16;" in sub
    assert "volatile uint8_t q8;" in sub


# ---------------------------------------------------------------------------
# Gate (f): side-effect-discriminating accessor names
# ---------------------------------------------------------------------------


def test_clear_on_read_emits_consume_not_read():
    """INV-S-MEM-C-2: a chart channel with sos:clear_on_read emits
    `_consume` and MUST NOT emit `_read`."""
    bl = {
        "fields": [
            {"name": "ready", "start_bit": 0, "width": 1, "access": "RO",
             "side_effect": "clear-on-read", "reset_value": 0},
        ]
    }
    chart = _chart(states=[_state("S", _status(_uuid(1), "irq_status", bit_layout=bl))])
    out = _emit(chart, chart_name="cor")
    sub = out["sos_cor__default.h"]
    assert "SOS_C_irq_status_consume(" in sub
    assert "SOS_C_irq_status_read(" not in sub


def test_command_emits_fire_not_write():
    """INV-S-MEM-C-3: kind="command" channels emit only `_fire`."""
    chart = _chart(states=[_state("S", _command(_uuid(1), "go"))])
    out = _emit(chart, chart_name="fr")
    sub = out["sos_fr__default.h"]
    assert "SOS_C_go_fire(" in sub
    assert "SOS_C_go_write(" not in sub
    assert "SOS_C_go_read(" not in sub


def test_consume_accessor_returns_cleared_value():
    """PCDN-SOS-09-C-003 (a): _consume returns the cleared value."""
    bl = {
        "fields": [
            {"name": "ready", "start_bit": 0, "width": 1, "access": "RO",
             "side_effect": "clear-on-read", "reset_value": 0},
        ]
    }
    chart = _chart(states=[_state("S", _status(_uuid(1), "ch", bit_layout=bl))])
    out = _emit(chart, chart_name="cv")
    sub = out["sos_cv__default.h"]
    # Returns a uint32_t (not void).
    assert "static inline uint32_t SOS_C_ch_consume(" in sub


def test_fire_accessor_returns_void():
    chart = _chart(states=[_state("S", _command(_uuid(1), "trigger"))])
    out = _emit(chart, chart_name="fv")
    sub = out["sos_fv__default.h"]
    assert "static inline void SOS_C_trigger_fire(" in sub


# ---------------------------------------------------------------------------
# Gate (h): MPU-region extern declarations
# ---------------------------------------------------------------------------


def test_zone_annotated_channel_emits_mpu_extern():
    """A channel with sos:zone gets an `extern const sos_mpu_region_t
    sos_mpu_<channel>_region;` per §5.6."""
    chart = _chart(states=[
        _state("S", _status(_uuid(1), "priv_ch", zone="privileged")),
        _state("U", _status(_uuid(2), "unpriv_ch", zone="unprivileged")),
    ])
    out = _emit(chart, chart_name="mpu")
    sub = out["sos_mpu__default.h"]
    assert "extern const sos_mpu_region_t sos_mpu_priv_ch_region;" in sub
    assert "extern const sos_mpu_region_t sos_mpu_unpriv_ch_region;" in sub


def test_umbrella_includes_sos_mpu_h():
    chart = _chart(states=[_state("S", _status(_uuid(1), "ch"))])
    out = _emit(chart, chart_name="mpu_inc")
    umbrella = out["sos_mpu_inc.h"]
    assert '#include "sos_mpu.h"' in umbrella


# ---------------------------------------------------------------------------
# Gate (i): deterministic-from-sos:name (NOT sos:id)
# ---------------------------------------------------------------------------


def test_byte_identical_when_only_sos_id_differs():
    """INV-S-MEM-C-5: two charts that differ only in sos:id UUIDs
    produce byte-identical accessor symbols and byte-identical output."""
    chart_a = _chart(states=[
        _state("S", _status(_uuid(0xAA), "rx_ch", irq="rx_irq")),
        _state("T", _command(_uuid(0xAB), "tx_ch")),
        _state("Q", _queue(_uuid(0xAC), "io_q")),
    ])
    # Same chart with completely different UUIDs.
    chart_b = _chart(states=[
        _state("S", _status(_uuid(0x01), "rx_ch", irq="rx_irq")),
        _state("T", _command(_uuid(0x02), "tx_ch")),
        _state("Q", _queue(_uuid(0x03), "io_q")),
    ])
    out_a = _emit(chart_a, chart_name="determ")
    out_b = _emit(chart_b, chart_name="determ")
    assert set(out_a.keys()) == set(out_b.keys())
    for fname in out_a:
        assert out_a[fname] == out_b[fname], (
            f"non-determinism in {fname}: differs by sos:id alone"
        )


def test_accessor_symbols_carry_no_uuid_substring():
    """Stronger check: emitted text contains zero UUID substrings."""
    chart = _chart(states=[_state("S", _status(_uuid(0xCC), "alpha"))])
    out = _emit(chart, chart_name="no_uuid")
    for fname, text in out.items():
        assert _uuid(0xCC) not in text, (
            f"emitted text contains the channel UUID, violating "
            f"INV-S-MEM-C-5 (file={fname})"
        )


# ---------------------------------------------------------------------------
# Header guard sanity
# ---------------------------------------------------------------------------


def test_header_guards_present():
    chart = _chart(states=[_state("S", _status(_uuid(1), "ch"))])
    out = _emit(chart, chart_name="gd")
    umbrella = out["sos_gd.h"]
    sub = out["sos_gd__default.h"]
    assert "#ifndef SOS_GD_H" in umbrella
    assert "#define SOS_GD_H" in umbrella
    assert "#endif /* SOS_GD_H */" in umbrella
    assert "#ifndef SOS_GD__DEFAULT_H" in sub
    assert "#define SOS_GD__DEFAULT_H" in sub
    assert "#endif /* SOS_GD__DEFAULT_H */" in sub


# ---------------------------------------------------------------------------
# Gate (g): -Wall -Wextra -Wpedantic -std=c11 cleanness
# ---------------------------------------------------------------------------


def _find_c_compiler() -> str | None:
    for tool in ("gcc", "clang"):
        path = shutil.which(tool)
        if path is not None:
            return path
    return None


def _write_sos_mpu_stub(out_dir: Path) -> None:
    """Write a minimal ``sos_mpu.h`` stub providing ``sos_mpu_region_t``
    so the emitted headers can be #included standalone for the toolchain
    cleanness gate. Mirrors the SOS-09-G §5.3 field shape (minimal —
    the exact layout is owned by SOS-09-G and not under test here)."""
    (out_dir / "sos_mpu.h").write_text(
        "/* Test stub for sos_mpu.h — owned by SOS-09-G in production. */\n"
        "#ifndef SOS_MPU_H\n"
        "#define SOS_MPU_H\n"
        "#include <stdint.h>\n"
        "typedef struct sos_mpu_region {\n"
        "    const char *name;\n"
        "    uint32_t base_address;\n"
        "    unsigned size_log2;\n"
        "    unsigned attr;\n"
        "    unsigned access;\n"
        "    unsigned xn;\n"
        "    unsigned enable;\n"
        "    unsigned srd;\n"
        "    const char *channel_id;\n"
        "} sos_mpu_region_t;\n"
        "struct sos_mutex { int _opaque; };\n"
        "#endif /* SOS_MPU_H */\n",
        encoding="utf-8",
    )


def _compile_clean(compiler: str, header_path: Path, include_dir: Path) -> tuple[int, str]:
    """Compile an empty TU that #includes ``header_path``; return
    ``(rc, stderr)``. Uses the gate flags from INV-S-MEM-C-4."""
    src = include_dir / "_probe.c"
    src.write_text(
        f'#include "{header_path.name}"\n'
        "int main(void) { return 0; }\n",
        encoding="utf-8",
    )
    out_bin = include_dir / "_probe.out"
    # ``-c`` not used — we want the linker to NOT be invoked here, but
    # the accessor functions are ``static inline`` so they don't produce
    # external references. We compile-only to avoid pulling in the
    # ``sos_mpu_*_region`` extern definitions (they live in SOS-09-G's
    # ``<chart>_mpu.c``, which is NOT part of this test surface).
    cmd = [
        compiler,
        "-Wall", "-Wextra", "-Wpedantic", "-Werror",
        "-std=c11",
        "-c", str(src),
        "-I", str(include_dir),
        "-o", str(out_bin),
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=60,
    )
    return result.returncode, result.stderr


@pytest.mark.skipif(_find_c_compiler() is None,
                    reason="neither gcc nor clang on PATH; gate (g) skipped")
def test_emitted_headers_compile_clean_wpedantic_c11():
    """Gate (g) per INV-S-MEM-C-4: -Wall -Wextra -Wpedantic -std=c11 clean."""
    compiler = _find_c_compiler()
    assert compiler is not None  # guarded by skipif

    chart = _chart(states=[
        _state("S", _status(_uuid(0xD1), "rx_status",
                            bit_layout={
                                "fields": [
                                    {"name": "ready", "start_bit": 0, "width": 1,
                                     "access": "RO", "side_effect": "clear-on-read",
                                     "reset_value": 0},
                                    {"name": "count", "start_bit": 1, "width": 7,
                                     "access": "RO", "side_effect": None,
                                     "reset_value": 0},
                                ]
                            })),
        _state("C", _command(_uuid(0xD2), "tx_command")),
        _state("Q", _queue(_uuid(0xD3), "io_queue", width=16)),
        _state("H", _shared(_uuid(0xD4), "shared_block", mutex="shared_lock")),
    ])
    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        _write_sos_mpu_stub(out_dir)
        emit_c_hal(_parse(chart), chart_name="probe", output_dir=out_dir)
        umbrella = out_dir / "sos_probe.h"
        assert umbrella.exists()

        rc, stderr = _compile_clean(compiler, umbrella, out_dir)
        assert rc == 0, (
            f"emitted headers failed -Wpedantic -std=c11 cleanness "
            f"under {compiler}; stderr:\n{stderr}"
        )


@pytest.mark.skipif(
    not (shutil.which("gcc") and shutil.which("clang")),
    reason="both gcc AND clang required for cross-compiler gate",
)
def test_emitted_headers_compile_clean_under_both_compilers():
    """Cross-compiler check per acceptance gate (g) full form."""
    chart = _chart(states=[
        _state("S", _status(_uuid(0xE1), "ch_a")),
        _state("T", _command(_uuid(0xE2), "ch_b")),
    ])
    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        _write_sos_mpu_stub(out_dir)
        emit_c_hal(_parse(chart), chart_name="dual", output_dir=out_dir)
        umbrella = out_dir / "sos_dual.h"
        for compiler in ("gcc", "clang"):
            path = shutil.which(compiler)
            assert path is not None
            rc, stderr = _compile_clean(path, umbrella, out_dir)
            assert rc == 0, (
                f"headers failed under {compiler}: stderr=\n{stderr}"
            )


# ---------------------------------------------------------------------------
# Validation negative cases
# ---------------------------------------------------------------------------


def test_invalid_chart_name_raises():
    chart = _chart(states=[_state("S", _status(_uuid(1), "ch"))])
    with pytest.raises(ValueError):
        emit_c_hal(_parse(chart), chart_name="0bad")
    with pytest.raises(ValueError):
        emit_c_hal(_parse(chart), chart_name="bad-dash")


def test_negative_base_address_raises():
    chart = _chart(states=[_state("S", _status(_uuid(1), "ch"))])
    with pytest.raises(ValueError):
        emit_c_hal(_parse(chart), chart_name="ok", base_address=-1)


# ---------------------------------------------------------------------------
# Disk-write side-effect
# ---------------------------------------------------------------------------


def test_output_dir_writes_files_to_disk():
    chart = _chart(states=[_state("S", _status(_uuid(1), "ch"))])
    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        result = emit_c_hal(_parse(chart), chart_name="disk", output_dir=out_dir)
        # Files exist on disk.
        for fname in result:
            assert (out_dir / fname).exists()
        # Disk contents match returned dict.
        for fname, text in result.items():
            assert (out_dir / fname).read_text(encoding="utf-8") == text


# ---------------------------------------------------------------------------
# Gate (j): cross-phase citations in source
# ---------------------------------------------------------------------------


def test_emitter_source_cites_cross_phase_anchors():
    """Gate (j): the SOS-09-C emit-path source cites cross-phase
    anchors (SOS-09 umbrella, SOS-09-A, SOS-09-B, SOS-09-G, plus the
    INV-S-MEM-C-* invariants)."""
    src = (_TOOLS_DIR / "c_hal_emit.py").read_text(encoding="utf-8")
    for anchor in (
        "SOS-09-A",  # chart annotation surface
        "SOS-09-B",  # CMSIS-SVD address chain
        "SOS-09-G",  # MPU region symbol shape
        "INV-S-MEM-C-5",  # determinism invariant
        "PCDN-SOS-09-C-001",  # bit-field policy ratification
        "PCDN-SOS-09-C-002",  # volatile placement ratification
        "PCDN-SOS-09-C-003",  # consume return-value ratification
        "PCDN-SOS-09-C-004",  # umbrella transitive include
        "PCDN-SOS-09-C-005",  # static inline ratification
    ):
        assert anchor in src, f"emitter source missing cross-phase anchor {anchor!r}"
