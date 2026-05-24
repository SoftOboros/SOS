"""SOS-08-E SystemVerilog testbench walker tests (wave-1).

@spec docs/concepts/SOS-08-E-CONCEPTS.md §5..§7 (emission contract + invariants)
@spec docs/concepts/SOS-08-E-CONCEPTS.md §15  (2026-05-23 ratification)
@spec docs/concepts/SOS-08-D-CONCEPTS.md §6.3 (SVA bind file artifact mirrored)
@spec docs/concepts/SOS-07-CONCEPTS.md  §6    (INV-SOS-A..H — cited)
@spec docs/concepts/SOS-08-CONCEPTS.md  §7    (INV-S-HDL-1..5 — cited)

These tests verify the wave-1 surface of
``transliterate_hdl_sv_tb.render_target``:
  * Eight files emitted per single-region chart (six SV files + two
    build wrappers), all rooted under ``tb/sv/<chart>/`` per §6.
  * Top-level testbench module instantiates DUT, vif, driver, checker.
  * Driver class consumes JSONL trace via ``$fopen``/``$fgets`` and
    drives only DUT inputs through the virtual interface modport
    (per §6.1 + INV-S-HDL-E-3).
  * Checker class observes DUT outputs and reports failures in chart
    vocabulary (``[FAIL] vector V<n>:`` — per §5.5 + INV-S-HDL-E-4).
  * SVA bind file content is byte-identical to ``transliterate_sva_bind``
    (per §5.2).
  * Invariant audit catches INV-S-HDL-E-1..3 forbidden constructs.
  * Parallel charts reject at wave-1.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


TESTS_DIR = Path(__file__).resolve().parent
TOOL_DIR = TESTS_DIR.parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))


sv_tb = pytest.importorskip(
    "transliterate_hdl_sv_tb",
    reason="transliterate_hdl_sv_tb not importable — wave-1 SV testbench "
    "suite skips until the module lands.",
)
sva_bind = pytest.importorskip(
    "transliterate_sva_bind",
    reason="transliterate_sva_bind not importable — SOS-08-E mirrors "
    "SOS-08-D's bind emit; suite skips without the sibling module.",
)


def _simple_chart() -> dict:
    """Two-state chart: idle ↔ active. Wave-1 single-region scope."""
    return {
        "initial": "idle",
        "state": [
            {
                "id": "idle",
                "transition": [{"event": "start", "target": "active"}],
            },
            {
                "id": "active",
                "transition": [{"event": "stop", "target": "idle"}],
            },
        ],
    }


def _parallel_chart() -> dict:
    """Chart with a top-level <parallel>; wave-1 must reject."""
    return {
        "initial": "regions",
        "parallel": [
            {
                "id": "regions",
                "state": [
                    {"id": "r0_idle"},
                    {"id": "r1_idle"},
                ],
            }
        ],
    }


# ---------------------------------------------------------------------------
# File-set + naming
# ---------------------------------------------------------------------------


class TestFileSet:
    """SOS-08-E §6 emission contract: eight artifacts per region."""

    def test_emits_eight_files(self):
        files = sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})
        # Six SV files + two build wrappers = 8.
        assert len(files) == 8, (
            f"SOS-08-E §6: expected 8 emitted files, got {len(files)}: "
            f"{sorted(files)}"
        )

    def test_emits_top_module(self):
        files = sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})
        assert "tb/sv/demo/tb_demo.sv" in files

    def test_emits_driver_class(self):
        files = sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})
        assert "tb/sv/demo/sos_driver_demo.sv" in files

    def test_emits_checker_class(self):
        files = sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})
        assert "tb/sv/demo/sos_checker_demo.sv" in files

    def test_emits_virtual_interface(self):
        files = sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})
        assert "tb/sv/demo/dut_if_demo.sv" in files

    def test_emits_sva_assertion_module(self):
        files = sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})
        assert "tb/sv/demo/demo_fsm_sva.sv" in files

    def test_emits_sva_bind_directive(self):
        files = sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})
        assert "tb/sv/demo/demo_fsm_bind.sv" in files

    def test_emits_verilator_makefile(self):
        files = sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})
        assert "tb/sv/demo/run_verilator.mk" in files

    def test_emits_questa_do(self):
        files = sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})
        assert "tb/sv/demo/run.do" in files


class TestNamingConventions:
    """Module + class names follow the documented naming convention."""

    def test_tb_module_name(self):
        assert sv_tb.tb_module_name("demo") == "tb_demo"

    def test_driver_class_name(self):
        assert sv_tb.driver_class_name("demo") == "sos_driver_demo"

    def test_checker_class_name(self):
        assert sv_tb.checker_class_name("demo") == "sos_checker_demo"

    def test_virtual_if_name(self):
        assert sv_tb.virtual_if_name("demo") == "dut_if_demo"

    def test_dut_module_name(self):
        assert sv_tb.dut_module_name("demo") == "demo_fsm"

    def test_name_sanitization_strips_punctuation(self):
        assert sv_tb.tb_module_name("my-chart.v2") == "tb_my_chart_v2"

    def test_name_sanitization_handles_reserved_words(self):
        # `module` is an SV keyword; the sanitizer suffixes `_id`.
        assert sv_tb.tb_module_name("module") == "tb_module_id"


# ---------------------------------------------------------------------------
# Top-level testbench module content (§6.3)
# ---------------------------------------------------------------------------


class TestTopModule:
    """§6.3: top instantiates DUT, vif, driver, checker; fork-joins; finish."""

    def _top(self) -> str:
        files = sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})
        return files["tb/sv/demo/tb_demo.sv"]

    def test_has_timescale(self):
        assert "`timescale" in self._top()

    def test_instantiates_dut(self):
        top = self._top()
        assert "demo_fsm " in top or "demo_fsm #" in top, (
            "SOS-08-E §6.3 (1): top-level testbench MUST instantiate the "
            "chart-emitted FSM module."
        )

    def test_instantiates_vif(self):
        assert "dut_if_demo " in self._top() or "dut_if_demo #" in self._top()

    def test_drives_clock(self):
        top = self._top()
        # Wave-1: 100 MHz default (period = 10 ns).
        assert "always #" in top and "clk = ~clk" in top, (
            "SOS-08-E §6.3 (3): top-level MUST drive clock."
        )

    def test_instantiates_driver_and_checker(self):
        top = self._top()
        assert "sos_driver_demo" in top
        assert "sos_checker_demo" in top

    def test_uses_fork_join(self):
        top = self._top()
        assert "fork" in top and "join" in top, (
            "SOS-08-E §6.3 (5): fork-join runs driver + checker "
            "concurrently."
        )

    def test_emits_pass_fail_summary(self):
        top = self._top()
        assert "[PASS]" in top, (
            "SOS-08-E §6.3 (6) + INV-S-HDL-E-4: [PASS] summary line."
        )
        assert "[FAIL" in top, (
            "SOS-08-E §6.3 (6) + INV-S-HDL-E-4: [FAIL count=N] summary."
        )

    def test_calls_finish(self):
        assert "$finish" in self._top()

    def test_includes_bind_file(self):
        # Wave-1: top `include-s the driver/checker/vif; the bind file
        # is compiled separately by the build wrapper. Verify the wrapper
        # references the bind file source so the property module attaches.
        files = sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})
        wrapper = files["tb/sv/demo/run_verilator.mk"]
        assert "demo_fsm_bind.sv" in wrapper


# ---------------------------------------------------------------------------
# Driver class content (§6.1)
# ---------------------------------------------------------------------------


class TestDriverClass:
    """§6.1: stimulus driver class contract."""

    def _drv(self) -> str:
        files = sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})
        return files["tb/sv/demo/sos_driver_demo.sv"]

    def test_is_a_class(self):
        drv = self._drv()
        assert "class sos_driver_demo" in drv
        assert "endclass" in drv

    def test_has_constructor(self):
        drv = self._drv()
        assert "function new" in drv

    def test_has_run_task(self):
        assert "task run();" in self._drv()

    def test_consumes_trace_via_fopen(self):
        drv = self._drv()
        assert "$fopen" in drv, (
            "SOS-08-E §5.4: driver MUST consume JSONL trace via $fopen."
        )
        assert "$fgets" in drv

    def test_drives_only_inputs(self):
        # The driver MUST route through the `driver_mp` modport (which
        # has DUT inputs as `output` and outputs as `input`).
        drv = self._drv()
        assert "driver_mp" in drv, (
            "SOS-08-E §6.1: driver must use the driver_mp modport (DUT "
            "inputs are output ports of the modport)."
        )

    def test_emits_drive_log_in_chart_vocabulary(self):
        # INV-S-HDL-E-4: log per event with `[DRIVE] V<n>:` chart-vocab.
        assert "[DRIVE]" in self._drv()


# ---------------------------------------------------------------------------
# Checker class content (§6.2)
# ---------------------------------------------------------------------------


class TestCheckerClass:
    """§6.2: response checker class contract."""

    def _chk(self) -> str:
        files = sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})
        return files["tb/sv/demo/sos_checker_demo.sv"]

    def test_is_a_class(self):
        chk = self._chk()
        assert "class sos_checker_demo" in chk
        assert "endclass" in chk

    def test_has_run_task(self):
        assert "task run();" in self._chk()

    def test_has_fail_count_accessor(self):
        chk = self._chk()
        assert "function int get_fail_count" in chk, (
            "SOS-08-E §6.2: checker MUST expose fail_count to the top-"
            "level via get_fail_count()."
        )

    def test_failure_message_is_chart_vocabulary(self):
        chk = self._chk()
        # INV-S-HDL-E-4 + §5.5: `[FAIL] vector V<n>: chart \`<chart>\``.
        assert "[FAIL] vector" in chk
        assert "chart `demo`" in chk, (
            "SOS-08-E §5.5: failure messages MUST cite the chart name in "
            "chart vocabulary."
        )

    def test_uses_checker_modport(self):
        chk = self._chk()
        assert "checker_mp" in chk, (
            "SOS-08-E §6.2: checker MUST use the checker_mp modport "
            "(observes only — no drives)."
        )


# ---------------------------------------------------------------------------
# Virtual interface (§6 dut_if_<chart>.sv)
# ---------------------------------------------------------------------------


class TestVirtualInterface:
    """Virtual interface ports + modports."""

    def _vif(self) -> str:
        files = sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})
        return files["tb/sv/demo/dut_if_demo.sv"]

    def test_declares_interface(self):
        vif = self._vif()
        assert "interface dut_if_demo" in vif

    def test_has_driver_modport(self):
        assert "modport driver_mp" in self._vif()

    def test_has_checker_modport(self):
        assert "modport checker_mp" in self._vif()

    def test_carries_current_state_observable(self):
        assert "current_state" in self._vif()

    def test_uses_include_guard(self):
        vif = self._vif()
        assert "`ifndef DUT_IF_DEMO_SV" in vif
        assert "`define DUT_IF_DEMO_SV" in vif


# ---------------------------------------------------------------------------
# SVA bind file mirror (§5.2)
# ---------------------------------------------------------------------------


class TestSvaBindMirror:
    """§5.2 + INV-S-HDL-D-4: SVA bind file content is byte-identical
    to SOS-08-D's emit. Only the filename prefix differs."""

    def test_sva_module_content_matches_sos_08_d(self):
        cfg = {"chart_name": "demo"}
        from_sv_tb = sv_tb.render_target(_simple_chart(), cfg)
        from_sva_bind = sva_bind.render_target(_simple_chart(), cfg)

        # SOS-08-D emits at tests/<chart>/; SOS-08-E at tb/sv/<chart>/.
        # The file content MUST match byte-for-byte.
        e_sva = from_sv_tb["tb/sv/demo/demo_fsm_sva.sv"]
        d_sva = from_sva_bind["tests/demo/demo_fsm_sva.sv"]
        assert e_sva == d_sva, (
            "SOS-08-E §5.2: SVA assertion module MUST be byte-identical "
            "to the SOS-08-D emit. Diverging content means the dual-"
            "emission equivalence claim (INV-S-HDL-D-4) is broken."
        )

    def test_bind_directive_matches_sos_08_d(self):
        cfg = {"chart_name": "demo"}
        from_sv_tb = sv_tb.render_target(_simple_chart(), cfg)
        from_sva_bind = sva_bind.render_target(_simple_chart(), cfg)
        assert (
            from_sv_tb["tb/sv/demo/demo_fsm_bind.sv"]
            == from_sva_bind["tests/demo/demo_fsm_bind.sv"]
        )


# ---------------------------------------------------------------------------
# Build wrappers (§6.4)
# ---------------------------------------------------------------------------


class TestBuildWrappers:
    """§6.4: at least one build wrapper per supported simulator at wave-1."""

    def _files(self) -> dict:
        return sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})

    def test_verilator_wrapper_invokes_verilator(self):
        wrapper = self._files()["tb/sv/demo/run_verilator.mk"]
        assert "verilator" in wrapper.lower()
        assert "--assert" in wrapper, (
            "SOS-08-E §6.4: build wrapper MUST enable SVA assertions."
        )

    def test_verilator_wrapper_compiles_all_sv(self):
        wrapper = self._files()["tb/sv/demo/run_verilator.mk"]
        # All six SV files must be referenced in dependency order.
        for fname in (
            "dut_if_demo.sv",
            "sos_driver_demo.sv",
            "sos_checker_demo.sv",
            "demo_fsm_sva.sv",
            "demo_fsm_bind.sv",
            "tb_demo.sv",
        ):
            assert fname in wrapper, (
                f"SOS-08-E §6.4: Verilator wrapper missing source {fname}"
            )

    def test_questa_wrapper_invokes_vlog_and_vsim(self):
        wrapper = self._files()["tb/sv/demo/run.do"]
        assert "vlog" in wrapper, (
            "SOS-08-E §6.4: Questa wrapper MUST call vlog for compilation."
        )
        assert "vsim" in wrapper

    def test_questa_wrapper_enables_assertdebug(self):
        wrapper = self._files()["tb/sv/demo/run.do"]
        assert "-assertdebug" in wrapper or "-assert" in wrapper


# ---------------------------------------------------------------------------
# Invariant satisfaction (§7)
# ---------------------------------------------------------------------------


class TestInvariants:
    """Audit emitted text for INV-S-HDL-E-1..6 satisfaction."""

    def _files(self) -> dict:
        return sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})

    def _non_bind_sv_files(self) -> dict:
        """Only the SV files that are NOT bind files — these are subject
        to the inline-assert prohibition."""
        files = self._files()
        return {
            k: v
            for k, v in files.items()
            if k.endswith(".sv")
            and not k.endswith("_sva.sv")
            and not k.endswith("_bind.sv")
        }

    def test_inv_e1_no_randomize_in_emit(self):
        """INV-S-HDL-E-1: no `randomize()`, `constraint`, `rand`, `randc`."""
        import re as _re
        for fname, src in self._files().items():
            # Strip comments to ignore spec-prose mentions.
            scanned = _re.sub(r"//.*$", "", src, flags=_re.MULTILINE)
            scanned = _re.sub(r"#.*$", "", scanned, flags=_re.MULTILINE)
            assert not _re.search(r"\brandomize\s*\(", scanned), (
                f"INV-S-HDL-E-1 violation in {fname}: randomize() call"
            )
            assert not _re.search(r"\bconstraint\s+\w+\s*\{", scanned), (
                f"INV-S-HDL-E-1 violation in {fname}: constraint block"
            )

    def test_inv_e2_no_uvm_imports(self):
        """INV-S-HDL-E-2: no UVM imports or macros."""
        import re as _re
        for fname, src in self._files().items():
            scanned = _re.sub(r"//.*$", "", src, flags=_re.MULTILINE)
            scanned = _re.sub(r"#.*$", "", scanned, flags=_re.MULTILINE)
            assert "import uvm_pkg" not in scanned, (
                f"INV-S-HDL-E-2 violation in {fname}: import uvm_pkg"
            )
            assert not _re.search(r"`uvm_\w+", scanned), (
                f"INV-S-HDL-E-2 violation in {fname}: `uvm_* macro"
            )

    def test_inv_e3_no_inline_assert_property_outside_bind(self):
        """INV-S-HDL-E-3: SVA only via bind files; no inline `assert
        property` in driver / checker / top / vif / wrappers."""
        import re as _re
        for fname, src in self._non_bind_sv_files().items():
            scanned = _re.sub(r"//.*$", "", src, flags=_re.MULTILINE)
            assert not _re.search(r"\bassert\s+property\b", scanned), (
                f"INV-S-HDL-E-3 violation in {fname}: inline assert property"
            )

    def test_inv_e4_chart_vocabulary_in_checker(self):
        """INV-S-HDL-E-4: failure messages cite chart name + state/transition."""
        chk = self._files()["tb/sv/demo/sos_checker_demo.sv"]
        assert "[FAIL] vector" in chk
        assert "chart `demo`" in chk

    def test_inv_e5_one_wrapper_per_supported_simulator_wave1(self):
        """INV-S-HDL-E-5: wave-1 ships Verilator wrapper (open-source CI
        target) + Questa/Riviera reference. VCS + Xcelium wrappers
        are wave-2 (see §15)."""
        files = self._files()
        assert "tb/sv/demo/run_verilator.mk" in files
        assert "tb/sv/demo/run.do" in files


# ---------------------------------------------------------------------------
# Parallel-chart rejection
# ---------------------------------------------------------------------------


class TestParallelRejection:
    """Wave-1: parallel charts MUST raise UnsupportedChartError."""

    def test_rejects_parallel_chart(self):
        with pytest.raises(sv_tb.UnsupportedChartError):
            sv_tb.render_target(_parallel_chart(), {"chart_name": "p"})


# ---------------------------------------------------------------------------
# Invariant audit error path
# ---------------------------------------------------------------------------


class TestInvariantAudit:
    """The walker's internal audit catches INV-S-HDL-E-1..3 violations."""

    def test_audit_catches_inline_randomize(self):
        """If a future walker change accidentally emits `randomize()`,
        the audit MUST catch it."""
        with pytest.raises(sv_tb.InvariantAuditError):
            sv_tb._audit_all({
                "tb/sv/x/sos_driver_x.sv": "class sos_driver_x;\n  task run();\n    randomize();\n  endtask\nendclass\n",
            })

    def test_audit_catches_uvm_import(self):
        with pytest.raises(sv_tb.InvariantAuditError):
            sv_tb._audit_all({
                "tb/sv/x/tb_x.sv": "import uvm_pkg::*;\nmodule tb_x; endmodule\n",
            })

    def test_audit_catches_inline_assert_property(self):
        with pytest.raises(sv_tb.InvariantAuditError):
            sv_tb._audit_all({
                "tb/sv/x/sos_checker_x.sv": "class sos_checker_x;\n  initial assert property (@(posedge clk) 1) else $error;\nendclass\n",
            })

    def test_audit_permits_assert_property_in_bind_file(self):
        # Bind files MUST contain `assert property` — that is the entire
        # point of the bind file. The audit MUST NOT flag them.
        sv_tb._audit_all({
            "tb/sv/x/x_fsm_sva.sv": "module x_fsm_sva; assert property (@(posedge clk) 1) else $error; endmodule\n",
        })

    def test_audit_passes_on_clean_emit(self):
        """End-to-end: a real emit passes the audit."""
        # render_target already runs _audit_all at the end; if this
        # returns without raising, the audit passed.
        sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})


# ---------------------------------------------------------------------------
# Non-dict input rejection
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_rejects_non_dict_chart_ir(self):
        with pytest.raises(sv_tb.UnsupportedChartError):
            sv_tb.render_target("not a dict", {"chart_name": "demo"})

    def test_default_chart_name_when_config_missing(self):
        # No config → chart_name defaults to "chart".
        files = sv_tb.render_target(_simple_chart(), None)
        assert any(k.startswith("tb/sv/chart/") for k in files)
