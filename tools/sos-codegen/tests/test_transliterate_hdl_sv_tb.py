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
    """SOS-08-E §6 emission contract.

    Wave-1: 6 SV files + 2 build wrappers (Verilator, Questa) = 8.
    Wave-2 (2026-05-23 §15): adds 3 more wrappers (VCS, Xcelium,
    Riviera) closing PCDN-E-005's five-of-five gate = 11 total.
    """

    def test_emits_eleven_files(self):
        files = sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})
        # Six SV files + five build wrappers = 11 (wave-2).
        assert len(files) == 11, (
            f"SOS-08-E §6 + wave-2 §15: expected 11 emitted files, "
            f"got {len(files)}: {sorted(files)}"
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

    def test_emits_vcs_makefile(self):
        """Wave-2: VCS build wrapper per PCDN-E-005."""
        files = sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})
        assert "tb/sv/demo/Makefile.sv" in files

    def test_emits_xcelium_script(self):
        """Wave-2: Xcelium build wrapper per PCDN-E-005."""
        files = sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})
        assert "tb/sv/demo/run_xrun.sh" in files

    def test_emits_riviera_tcl(self):
        """Wave-2: Riviera-PRO build wrapper per PCDN-E-005."""
        files = sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})
        assert "tb/sv/demo/run_riviera.tcl" in files


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


# ---------------------------------------------------------------------------
# SOS-08-E wave-2: VCS / Xcelium / Riviera build wrappers (PCDN-E-005
# five-of-five closure) + cross-path equivalence with SOS-08-D (gate (h)).
# ---------------------------------------------------------------------------


class TestWave2BuildWrappers:
    """PCDN-E-005 (resolved 2026-05-23): separate wrappers per simulator.
    Wave-2 closes the remaining 3 of 5 (VCS, Xcelium, Riviera) that
    wave-1 deferred."""

    def _files(self) -> dict:
        return sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})

    def test_vcs_makefile_invokes_vcs(self):
        wrapper = self._files()["tb/sv/demo/Makefile.sv"]
        assert "VCS" in wrapper
        assert "vcs" in wrapper.lower()

    def test_vcs_makefile_enables_assertions(self):
        wrapper = self._files()["tb/sv/demo/Makefile.sv"]
        # VCS SVA flag.
        assert "-assert enable_diag" in wrapper

    def test_vcs_makefile_lists_all_sources(self):
        wrapper = self._files()["tb/sv/demo/Makefile.sv"]
        for fname in (
            "dut_if_demo.sv",
            "sos_driver_demo.sv",
            "sos_checker_demo.sv",
            "demo_fsm_sva.sv",
            "demo_fsm_bind.sv",
            "tb_demo.sv",
        ):
            assert fname in wrapper, f"VCS Makefile missing {fname}"

    def test_xcelium_script_invokes_xrun(self):
        wrapper = self._files()["tb/sv/demo/run_xrun.sh"]
        assert "xrun" in wrapper.lower()

    def test_xcelium_script_enables_assertions(self):
        wrapper = self._files()["tb/sv/demo/run_xrun.sh"]
        assert "-assert" in wrapper

    def test_xcelium_script_is_bash(self):
        wrapper = self._files()["tb/sv/demo/run_xrun.sh"]
        # Shebang + `set -euo pipefail` make this a portable bash
        # wrapper rather than a /bin/sh script.
        assert wrapper.startswith("#!/usr/bin/env bash")
        assert "set -euo pipefail" in wrapper

    def test_riviera_wrapper_invokes_alog_asim(self):
        wrapper = self._files()["tb/sv/demo/run_riviera.tcl"]
        # Riviera-PRO uses alog/asim (or vlog/vsim aliases); the wave-2
        # split uses the native Riviera commands.
        assert "alog" in wrapper
        assert "asim" in wrapper

    def test_riviera_wrapper_distinct_from_questa(self):
        files = self._files()
        questa = files["tb/sv/demo/run.do"]
        riviera = files["tb/sv/demo/run_riviera.tcl"]
        # Wave-2 split: the two wrappers are no longer byte-identical.
        # Questa uses vlog/vsim; Riviera uses alog/asim.
        assert questa != riviera

    def test_all_five_wrappers_emitted(self):
        """INV-S-HDL-E-5 closure: per-simulator build wrapper for each
        of the five supported simulators (PCDN-E-005)."""
        files = self._files()
        for fname in (
            "tb/sv/demo/run_verilator.mk",  # Verilator (wave-1)
            "tb/sv/demo/run.do",            # Questa     (wave-1, refined wave-2)
            "tb/sv/demo/Makefile.sv",       # VCS        (wave-2)
            "tb/sv/demo/run_xrun.sh",       # Xcelium    (wave-2)
            "tb/sv/demo/run_riviera.tcl",   # Riviera    (wave-2)
        ):
            assert fname in files, (
                f"INV-S-HDL-E-5: missing build wrapper {fname}"
            )

    def test_all_wrappers_audit_clean(self):
        """Every wrapper passes the INV-S-HDL-E-1/-2/-3 audit."""
        # render_target's _audit_all runs over every emitted file; if
        # we got this far it passed.
        files = self._files()
        for fname in (
            "tb/sv/demo/Makefile.sv",
            "tb/sv/demo/run_xrun.sh",
            "tb/sv/demo/run_riviera.tcl",
        ):
            assert files[fname]  # non-empty


# ---------------------------------------------------------------------------
# SOS-08-E wave-2 cross-path equivalence with SOS-08-D (gate (h)).
# ---------------------------------------------------------------------------


sva_bind = pytest.importorskip(
    "transliterate_sva_bind",
    reason="cross-path equivalence test requires sibling walker.",
)
cocotb_walker = pytest.importorskip(
    "transliterate_cocotb",
    reason="cross-path equivalence test requires SOS-08-D cocotb walker.",
)


class TestCrossPathEquivalenceWithSOS08D:
    """SOS-08-E §12 gate (h) — cross-path equivalence with SOS-08-D.

    The claim: rendering the same chart through SOS-08-D (cocotb path)
    and SOS-08-E (SV testbench path) produces SVA bind file content
    that is byte-identical between the two paths. This is the
    load-bearing claim of the dual-emission design — one chart, two
    test scaffoldings, ONE assertion artifact.
    """

    def test_sva_module_byte_identical_across_paths(self):
        cfg = {"chart_name": "kernel"}
        from_e = sv_tb.render_target(_simple_chart(), cfg)
        from_d = sva_bind.render_target(_simple_chart(), cfg)

        # SOS-08-E emits at tb/sv/<chart>/; SOS-08-D at tests/<chart>/.
        # The SVA module body MUST be byte-identical.
        e_sva = from_e["tb/sv/kernel/kernel_fsm_sva.sv"]
        d_sva = from_d["tests/kernel/kernel_fsm_sva.sv"]
        assert e_sva == d_sva, (
            "SOS-08-E §5.2 + §12 gate (h): SVA assertion module MUST be "
            "byte-identical across cocotb (SOS-08-D) + SV testbench "
            "(SOS-08-E) paths. Diverging content means the dual-"
            "emission equivalence claim regresses."
        )

    def test_bind_directive_byte_identical_across_paths(self):
        cfg = {"chart_name": "kernel"}
        from_e = sv_tb.render_target(_simple_chart(), cfg)
        from_d = sva_bind.render_target(_simple_chart(), cfg)
        assert (
            from_e["tb/sv/kernel/kernel_fsm_bind.sv"]
            == from_d["tests/kernel/kernel_fsm_bind.sv"]
        )

    def test_sva_module_byte_identical_with_guards(self):
        """Equivalence MUST hold across a non-trivial chart with
        transition guards (the SVA bind walker lowers guards into the
        assertion antecedent; both paths must produce the same lowered
        text)."""
        chart_with_guards = {
            "initial": "idle",
            "datamodel": [{"data": [{"id": "ready", "expr": "0"}]}],
            "state": [
                {
                    "id": "idle",
                    "transition": [
                        {"event": "go", "cond": "ready == 1",
                         "target": "active"},
                    ],
                },
                {"id": "active"},
            ],
        }
        cfg = {"chart_name": "guarded"}
        from_e = sv_tb.render_target(chart_with_guards, cfg)
        from_d = sva_bind.render_target(chart_with_guards, cfg)
        assert (
            from_e["tb/sv/guarded/guarded_fsm_sva.sv"]
            == from_d["tests/guarded/guarded_fsm_sva.sv"]
        )

    def test_sos_08_e_does_not_emit_cocotb_artifacts(self):
        """Gate (h) sanity check: the SV-testbench path MUST NOT emit
        Python cocotb test files (those are SOS-08-D's territory)."""
        files = sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})
        for fname in files:
            assert not fname.endswith(".py"), (
                f"SOS-08-E MUST NOT emit Python files; saw {fname}"
            )

    def test_sos_08_d_does_not_emit_sv_testbench_artifacts(self):
        """Gate (h) sanity check: the cocotb path MUST NOT emit
        SV-testbench class files (those are SOS-08-E's territory)."""
        files = cocotb_walker.render_target(
            _simple_chart(), {"chart_name": "demo"}
        )
        forbidden_prefixes = ("tb_", "sos_driver_", "sos_checker_", "dut_if_")
        for fname in files:
            leaf = fname.rsplit("/", 1)[-1]
            for pref in forbidden_prefixes:
                if leaf.startswith(pref) and leaf.endswith(".sv"):
                    pytest.fail(
                        f"SOS-08-D MUST NOT emit SV testbench file "
                        f"{leaf!r}; that's SOS-08-E's territory."
                    )
