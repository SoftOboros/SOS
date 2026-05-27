"""SOS-09 umbrella §12 gate (c) — six-emitter end-to-end worked example.

Authority: ``docs/concepts/SOS-09-CONCEPTS.md`` §12 (c):

    "At least one chart channel (recommended: a `kind=\"status\"` channel)
    emits all six artifacts (CMSIS-SVD entry, SystemRDL entry, C HAL
    header, Rust HAL trait, HDL register-file RTL, membrane vector set)
    as a worked example."

This test takes a single SCXML fixture carrying ONE `kind="status"`
channel (``telemetry_status``, sos:id
``11111111-1111-4111-8111-111111111111``) and drives it through every
SOS-09 emit path that is currently wired in ``tools/sos-codegen/``.
SystemRDL emission is deferred per SOS-09-B §16 + PCDN-SOS-09-B-005(a):
the corresponding test parametrisation skips cleanly with the deferral
citation as the skip reason.

The cross-validation property — and the load-bearing demonstration that
the gate's "single source of truth across the membrane" claim is real
— is the channel-trace assertion in
``test_channel_id_trace_appears_across_all_active_emitters``: the same
``sos:name`` and/or ``sos:id`` MUST appear in every active emitter's
output. If a future emitter rename breaks the trace, this test fails
and the gate must be re-evaluated.

Per ERRATA-004 alignment, the channel's ``sos:dir`` uses the canonical
arrow form (``hw→sw``).

Per the SOS-09 umbrella §16 2026-05-27 acceptance roll-up entry,
*"no single chart channel currently threads end-to-end through all six
emit paths"* was the explicit ⏸ reason for gate (c). This test unifies
the per-sub-phase fixtures' coverage into the one chart the umbrella
asks for.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

# Make ``sos-codegen`` modules importable when pytest is invoked from any cwd.
_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from c_hal_emit import emit_c_hal_from_chart  # noqa: E402
from loader import load_chart  # noqa: E402
from sos09_annotations import parse_chart_annotations  # noqa: E402
from transliterate_regfile import emit_regfile_from_chart  # noqa: E402
from transliterate_rust import emit_rust_hal_from_chart  # noqa: E402
from transliterate_svd import emit_svd_from_chart  # noqa: E402
from vectors_emit import emit_vectors  # noqa: E402


_FIXTURE = (
    _TOOLS_DIR
    / "tests"
    / "fixtures"
    / "sos_09"
    / "worked_example"
    / "six_emitter_chart.scxml"
)

# The single channel under test — pinned to the values authored in the
# fixture. Any drift between the fixture and these constants is a test
# failure on its own.
_CHANNEL_NAME = "telemetry_status"
_CHANNEL_UUID = "11111111-1111-4111-8111-111111111111"
_CHANNEL_KIND = "status"
_CHANNEL_DIR = "hw→sw"  # ERRATA-004 arrow form
_CHANNEL_IRQ = "telemetry_ready"
_CHANNEL_GROUP = "telemetry"
_CHANNEL_PRIVILEGE_REGION = "telemetry"


# ---------------------------------------------------------------------------
# Fixture-existence + parse sanity
# ---------------------------------------------------------------------------


def test_fixture_chart_exists():
    """Sanity: the worked-example chart exists at the documented path."""
    assert _FIXTURE.exists(), f"worked-example chart missing at {_FIXTURE}"


def test_fixture_carries_one_status_channel_with_expected_annotations():
    """The chart carries exactly one channel and its annotation surface
    matches the pinned constants above.

    The gate-(c) text recommends a ``kind="status"`` channel; the
    fixture honours that recommendation. The chart is deliberately
    minimal — one channel is the gate-(c) minimum — and the test pins
    that minimality so future expansion of the fixture is a deliberate
    edit, not a drift.
    """
    ast = load_chart(_FIXTURE)
    annotations = parse_chart_annotations(ast.raw_scjson)

    assert len(annotations.channels) == 1, (
        f"worked-example chart should carry exactly one channel; "
        f"got {len(annotations.channels)}"
    )
    ch = annotations.channels[0]
    assert ch.name == _CHANNEL_NAME
    assert ch.id == _CHANNEL_UUID
    assert ch.kind == _CHANNEL_KIND
    assert ch.dir == _CHANNEL_DIR
    assert ch.irq == _CHANNEL_IRQ
    assert ch.channel_group == _CHANNEL_GROUP
    assert ch.privilege_region == _CHANNEL_PRIVILEGE_REGION


# ---------------------------------------------------------------------------
# Per-emitter activation tests
# ---------------------------------------------------------------------------


def test_emit_path_1_svd_emits_register_for_channel():
    """SOS-09-B CMSIS-SVD: the single status channel materialises as a
    `<peripheral><registers><register name="telemetry_status">` entry
    AND its IRQ surfaces as a `<peripheral><interrupt name="telemetry_ready">`.

    Authority: ``docs/concepts/SOS-09-B-CONCEPTS.md`` (🟢 RATIFIED 2026-05-25).
    """
    out = emit_svd_from_chart(_FIXTURE, device_name="Sos09Demo")
    # The channel name MUST appear as a `<name>telemetry_status</name>` text node.
    assert f"<name>{_CHANNEL_NAME}</name>" in out, (
        "SOS-09-B SVD output should carry a <name>telemetry_status</name> "
        "register entry; missing means the channel did not materialise"
    )
    # The IRQ name MUST appear in a `<name>telemetry_ready</name>` text node.
    assert f"<name>{_CHANNEL_IRQ}</name>" in out, (
        "SOS-09-B SVD output should carry the IRQ name as a <name> node"
    )


def test_emit_path_2_systemrdl_is_deferred():
    """SOS-09-B SystemRDL: deferred per PCDN-SOS-09-B-005(a) — see
    ``docs/concepts/SOS-09-B-CONCEPTS.md`` §16 (2026-05-25 ratification).

    Per the umbrella §5.5 frozen decision, CMSIS-SVD is the **primary**
    register-map artifact and SystemRDL is the **secondary**. The
    SystemRDL emission path is explicitly deferred to a future sibling
    sub-phase (working name ``SOS-09-B2-SYSTEMRDL``) when a
    non-Cortex-M target enters the SOS bench substrate. SOS-09-B at
    v1 authors CMSIS-SVD only.

    This test exists to make the deferral visible in the §12 (c)
    worked-example acceptance surface — the gate-(c) text names all
    six emit paths; an absent SystemRDL emit is a deliberate scope
    choice, not an oversight, and the skip reason cites the deferral
    authority.
    """
    pytest.skip(
        "SOS-09-B SystemRDL emission is deferred per PCDN-SOS-09-B-005(a) "
        "ratified 2026-05-25 — future sibling sub-phase "
        "(SOS-09-B2-SYSTEMRDL) when a non-Cortex-M target enters the SOS "
        "bench substrate. Gate (c)'s six-artifact surface lists "
        "SystemRDL as one of the six; the deferral is recorded here so "
        "the gate-(c) worked-example accounting is complete: 5 of 6 "
        "emitters wired in this worktree, 1 of 6 explicitly deferred."
    )


def test_emit_path_3_c_hal_emits_accessor_for_channel():
    """SOS-09-C C HAL: the single status channel materialises as a
    ``SOS_C_telemetry_status_*`` accessor in the per-channel-group
    sub-header. Clear-on-read field drives ``_consume_`` naming per
    SOS-09-C §5.3 gate (f).

    Authority: ``docs/concepts/SOS-09-C-CONCEPTS.md`` (🟢 RATIFIED 2026-05-26).
    """
    headers = emit_c_hal_from_chart(_FIXTURE, chart_name="sos09_demo")
    # The per-channel-group sub-header carries the channel-bearing
    # content; the umbrella header is an #include rollup.
    sub_header_name = f"sos_sos09_demo__{_CHANNEL_GROUP}.h"
    assert sub_header_name in headers, (
        f"SOS-09-C should emit a per-group sub-header named "
        f"{sub_header_name!r}; got {sorted(headers)}"
    )
    sub_text = headers[sub_header_name]
    # Channel name must surface as a SOS_C_<name>_* accessor.
    assert f"SOS_C_{_CHANNEL_NAME}_" in sub_text, (
        "SOS-09-C sub-header should carry a SOS_C_telemetry_status_ "
        "accessor symbol; missing means the channel did not materialise"
    )
    # clear-on-read field drives _consume naming (SOS-09-C §5.3).
    assert f"SOS_C_{_CHANNEL_NAME}_consume" in sub_text, (
        "SOS-09-C sub-header should emit the _consume accessor for the "
        "clear-on-read channel per SOS-09-C §5.3 (the destructiveness "
        "must be syntactically visible)"
    )


def test_emit_path_4_rust_hal_emits_typed_accessor_for_channel():
    """SOS-09-D Rust HAL: the single status channel materialises as a
    typed accessor in ``src/lib.rs``. The channel's ``sos:id`` UUID
    appears in the emitted source per the SAFETY/INV-SOS-G citation
    discipline (gate (g) ``_unchecked`` discharge).

    Authority: ``docs/concepts/SOS-09-D-CONCEPTS.md`` (🟢 RATIFIED 2026-05-26).
    """
    files = emit_rust_hal_from_chart(
        _FIXTURE, crate_name="sos09_demo_hal",
    )
    assert "src/lib.rs" in files, (
        f"SOS-09-D should emit src/lib.rs; got {sorted(files)}"
    )
    lib_rs = files["src/lib.rs"]
    # Channel name surfaces as a field / accessor name.
    assert _CHANNEL_NAME in lib_rs, (
        "SOS-09-D src/lib.rs should carry the channel name "
        "'telemetry_status' as a typed field/accessor; missing means "
        "the channel did not materialise"
    )
    # The channel's UUID surfaces in the emitted source per the
    # SAFETY/discharge discipline (this is the cross-validation hook
    # back to the chart channel's identity).
    assert _CHANNEL_UUID in lib_rs, (
        "SOS-09-D src/lib.rs should carry the channel's sos:id UUID "
        f"({_CHANNEL_UUID}) per the gate-(g) _unchecked SAFETY citation "
        "discipline (INV-SOS-G discharge naming the channel by UUID)"
    )


def test_emit_path_5_hdl_regfile_emits_channel_in_both_languages():
    """SOS-09-E HDL register-file RTL: the single status channel
    materialises as a register-port + strobe-latch in BOTH the VHDL
    and the SystemVerilog emissions of the regfile.

    Authority: ``docs/concepts/SOS-09-E-CONCEPTS.md`` (🟢 RATIFIED 2026-05-26).
    """
    files = emit_regfile_from_chart(
        _FIXTURE, peripheral_name="sos09_demo",
    )
    vhd_name = "sos_regfile_sos09_demo.vhd"
    sv_name = "sos_regfile_sos09_demo.sv"
    assert vhd_name in files and sv_name in files, (
        f"SOS-09-E should emit both {vhd_name} and {sv_name}; "
        f"got {sorted(files)}"
    )
    # Both language outputs MUST carry the channel name (INV-S-MEM-E-1
    # single-source register definition).
    assert _CHANNEL_NAME in files[vhd_name], (
        "SOS-09-E VHDL emission should carry the channel name"
    )
    assert _CHANNEL_NAME in files[sv_name], (
        "SOS-09-E SystemVerilog emission should carry the channel name"
    )


def test_emit_path_6_membrane_vectors_emit_per_family_plan():
    """SOS-09-F membrane vectors: the single status channel produces a
    per-family vector plan whose ``plans.json`` carries the channel's
    UUID. The clear-on-read bit_layout drives a ``clear_on_read``
    family entry; the channel's protection-zone declaration drives a
    ``protection`` family entry; every channel produces an
    ``initial_value`` family entry.

    Per INV-SOS-H, the membrane vector set is the integration contract
    rendered in chart vocabulary — the channel's sos:name and sos:id
    are the load-bearing trace through the vector set.

    Authority: ``docs/concepts/SOS-09-F-CONCEPTS.md`` (🟢 RATIFIED 2026-05-26).
    """
    ast = load_chart(_FIXTURE)
    annotations = parse_chart_annotations(ast.raw_scjson)
    with tempfile.TemporaryDirectory() as td:
        summary = emit_vectors(
            annotations, chart_id="sos09_demo", out_dir=td,
        )
        assert len(summary["plans"]) == 1
        plan = summary["plans"][0]
        assert plan["channel_name"] == _CHANNEL_NAME
        assert plan["channel_id"] == _CHANNEL_UUID
        assert plan["channel_kind"] == _CHANNEL_KIND
        # Per SOS-09-F §5.1: status + clear-on-read field + protection
        # zone yields these families.
        families = set(plan["families"])
        assert {"initial_value", "clear_on_read", "protection"} <= families, (
            f"SOS-09-F plan should carry the expected family set for a "
            f"status channel with clear-on-read + protection; got {families}"
        )
        # plans.json carries the channel name + UUID per INV-SOS-H trace.
        assert _CHANNEL_NAME in summary["files"]["plans.json"]
        assert _CHANNEL_UUID in summary["files"]["plans.json"]


# ---------------------------------------------------------------------------
# Cross-validation: single-source-of-truth across the membrane
# ---------------------------------------------------------------------------


def test_channel_id_trace_appears_across_all_active_emitters():
    """The single chart channel's name (and, where the emitter carries
    UUIDs, the channel's sos:id) MUST appear in every active emitter's
    output.

    This is the load-bearing assertion that closes gate (c): the chart
    is the single source of truth, and the six emit paths are
    consistent by construction. Five of six are checked here; the
    SystemRDL emit path is deferred per
    ``test_emit_path_2_systemrdl_is_deferred``.

    Per INV-S-MEM-1 (single-source register definition): every artifact
    that mentions ``telemetry_status`` MUST trace back to this one
    chart channel — there is no other chart in the worktree that emits
    a channel with this name.
    """
    # SVD
    svd = emit_svd_from_chart(_FIXTURE, device_name="Sos09Demo")
    assert _CHANNEL_NAME in svd

    # C HAL — per-group sub-header
    c_hal = emit_c_hal_from_chart(_FIXTURE, chart_name="sos09_demo")
    c_text = "\n".join(c_hal.values())
    assert _CHANNEL_NAME in c_text

    # Rust HAL — src/lib.rs
    rust = emit_rust_hal_from_chart(_FIXTURE, crate_name="sos09_demo_hal")
    rust_text = "\n".join(rust.values())
    assert _CHANNEL_NAME in rust_text
    # Rust HAL carries UUID by discipline.
    assert _CHANNEL_UUID in rust_text

    # HDL regfile — VHDL + SV
    rtl = emit_regfile_from_chart(_FIXTURE, peripheral_name="sos09_demo")
    rtl_text = "\n".join(rtl.values())
    assert _CHANNEL_NAME in rtl_text

    # Membrane vectors — plans.json carries both name and UUID
    ast = load_chart(_FIXTURE)
    annotations = parse_chart_annotations(ast.raw_scjson)
    with tempfile.TemporaryDirectory() as td:
        summary = emit_vectors(
            annotations, chart_id="sos09_demo", out_dir=td,
        )
        plans_text = summary["files"]["plans.json"]
        assert _CHANNEL_NAME in plans_text
        assert _CHANNEL_UUID in plans_text


def test_svd_carries_chart_declared_irq_name():
    """Cross-emitter consistency: the IRQ name declared on the chart
    channel MUST appear in the SOS-09-B SVD `<interrupt>` table. The
    SVD is the canonical IRQ surface (per PCDN-SOS-SOS-09-004 logical
    IRQ → per-target NVIC table mapping); downstream Rust HAL / C HAL
    consumers compose against the SVD-derived NVIC table, not against
    a re-declaration of the IRQ name in their own emit output.

    Authority for the IRQ surface boundary: SOS-09 umbrella §6
    (SOS-09-B owns CMSIS-SVD); PCDN-SOS-SOS-09-004 (logical-IRQ-name
    mapping policy); SOS-09 umbrella §5.5 (CMSIS-SVD primary).
    """
    svd = emit_svd_from_chart(_FIXTURE, device_name="Sos09Demo")
    # Both the IRQ name node and an `<interrupt>` element must surface.
    assert f"<name>{_CHANNEL_IRQ}</name>" in svd, (
        "SOS-09-B SVD output should emit the chart-declared IRQ name "
        "as a <name> child of an <interrupt> element; missing means "
        "the IRQ side of the channel did not materialise"
    )
    assert "<interrupt>" in svd, (
        "SOS-09-B SVD output should carry at least one <interrupt> "
        "element since the chart channel declares sos:irq"
    )
