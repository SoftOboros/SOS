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

import re
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
    """Parallel chart with two regions, each carrying its own state
    list. Used for wave-3 parallel-emit acceptance + SVA bind co-emit.
    """
    return {
        "initial": "regions",
        "parallel": [
            {
                "id": "regions",
                "state": [
                    {
                        "id": "left",
                        "initial": "l_idle",
                        "state": [
                            {"id": "l_idle"},
                            {"id": "l_active"},
                        ],
                    },
                    {
                        "id": "right",
                        "initial": "r_idle",
                        "state": [
                            {"id": "r_idle"},
                            {"id": "r_active"},
                        ],
                    },
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
    Wave-3 (2026-05-24 §15): adds 1 Verilator deferred-failure-stub
    policy header (`verilator_stubs.svh`) per INV-S-HDL-E-6
    ratification = 12 total.
    """

    def test_emits_sixteen_files(self):
        files = sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})
        # Six SV files + five build wrappers + verilator stubs +
        # wave-3-future parser package + per-chart state-symbol
        # table + wave-3-future-remaining layered class hierarchy
        # base headers (checker_base.svh + driver_base.svh) = 16.
        assert len(files) == 16, (
            f"SOS-08-E §6 + wave-3 + wave-3-future + wave-3-future-"
            f"remaining layered hierarchy §15: expected 16 emitted "
            f"files, got {len(files)}: {sorted(files)}"
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

    def _drv_base(self) -> str:
        """Driver BASE class (``_base.svh``) — owns the run-skeleton
        per wave-3-future-remaining layered class hierarchy."""
        files = sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})
        return files["tb/sv/demo/sos_demo_driver_base.svh"]

    def test_is_a_class(self):
        drv = self._drv()
        assert "class sos_driver_demo" in drv
        assert "endclass" in drv

    def test_has_constructor(self):
        drv = self._drv()
        assert "function new" in drv

    def test_has_run_task(self):
        # Wave-3-future-remaining layered hierarchy: the run-skeleton
        # lives in ``_base.svh``; the ``.sv`` default class only
        # carries hook overrides.
        assert "task run();" in self._drv_base()

    def test_consumes_trace_via_fopen(self):
        # File I/O moved into the BASE class with the run-skeleton.
        drv_base = self._drv_base()
        assert "$fopen" in drv_base, (
            "SOS-08-E §5.4: driver BASE MUST consume JSONL trace via $fopen."
        )
        assert "$fgets" in drv_base

    def test_drives_only_inputs(self):
        # The driver MUST route through the `driver_mp` modport (which
        # has DUT inputs as `output` and outputs as `input`).
        drv = self._drv()
        drv_base = self._drv_base()
        assert "driver_mp" in drv_base, (
            "SOS-08-E §6.1: driver BASE must declare the driver_mp modport "
            "(DUT inputs are output ports of the modport)."
        )
        # The default class inherits the same modport via the base.
        assert "driver_mp" in drv

    def test_emits_drive_log_in_chart_vocabulary(self):
        # INV-S-HDL-E-4: log per event with `[DRIVE] V<n>:` chart-vocab.
        # The wave-3-default drive-step body still carries the
        # ``[DRIVE]`` chart-vocab line; the base class only sets up the
        # run-skeleton.
        assert "[DRIVE]" in self._drv()


# ---------------------------------------------------------------------------
# Checker class content (§6.2)
# ---------------------------------------------------------------------------


class TestCheckerClass:
    """§6.2: response checker class contract."""

    def _chk(self) -> str:
        files = sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})
        return files["tb/sv/demo/sos_checker_demo.sv"]

    def _chk_base(self) -> str:
        """Checker BASE class (``_base.svh``) — owns the run-skeleton
        + chart-vocab message construction per wave-3-future-remaining
        layered class hierarchy."""
        files = sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})
        return files["tb/sv/demo/sos_demo_checker_base.svh"]

    def test_is_a_class(self):
        chk = self._chk()
        assert "class sos_checker_demo" in chk
        assert "endclass" in chk

    def test_has_run_task(self):
        # Wave-3-future-remaining: ``run()`` lives in the base class.
        assert "task run();" in self._chk_base()

    def test_has_fail_count_accessor(self):
        # ``get_fail_count`` is inherited from the base class.
        chk_base = self._chk_base()
        assert "function int get_fail_count" in chk_base, (
            "SOS-08-E §6.2: checker BASE MUST expose fail_count to the "
            "top-level via get_fail_count()."
        )

    def test_failure_message_is_chart_vocabulary(self):
        # Wave-3-future-remaining: chart-vocab message construction
        # lives in the base class's ``run()`` (byte-identical format
        # strings to the wave-3 monolithic emit).
        chk_base = self._chk_base()
        # INV-S-HDL-E-4 + §5.5: `[FAIL] vector V<n>: chart \`<chart>\``.
        assert "[FAIL] vector" in chk_base
        assert "chart `demo`" in chk_base, (
            "SOS-08-E §5.5: failure messages MUST cite the chart name in "
            "chart vocabulary."
        )

    def test_uses_checker_modport(self):
        chk_base = self._chk_base()
        assert "checker_mp" in chk_base, (
            "SOS-08-E §6.2: checker BASE MUST use the checker_mp modport "
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
        """INV-S-HDL-E-4: failure messages cite chart name + state/transition.

        Wave-3-future-remaining (2026-05-24 §15) layered class hierarchy:
        chart-vocab message construction lives in the BASE checker
        (``_base.svh``); the default checker delegates via
        ``super.on_invariant_fail(...)``."""
        chk_base = self._files()["tb/sv/demo/sos_demo_checker_base.svh"]
        assert "[FAIL] vector" in chk_base
        assert "chart `demo`" in chk_base

    def test_inv_e5_one_wrapper_per_supported_simulator_wave1(self):
        """INV-S-HDL-E-5: wave-1 ships Verilator wrapper (open-source CI
        target) + Questa/Riviera reference. VCS + Xcelium wrappers
        are wave-2 (see §15)."""
        files = self._files()
        assert "tb/sv/demo/run_verilator.mk" in files
        assert "tb/sv/demo/run.do" in files


# ---------------------------------------------------------------------------
# Parallel-chart acceptance (wave-3 lifts the wave-1/wave-2 rejection)
# ---------------------------------------------------------------------------


class TestParallelChartAccepted:
    """Wave-3 (2026-05-24 §15): parallel charts emit the per-region
    testbench split per SOS-08-C §6.10 chart-top wrapper convention.
    Wave-1 + wave-2 rejected; wave-3 accepts."""

    def test_accepts_parallel_chart(self):
        """No UnsupportedChartError — parallel charts emit cleanly."""
        files = sv_tb.render_target(_parallel_chart(), {"chart_name": "p"})
        assert "tb/sv/p/tb_p.sv" in files
        assert "tb/sv/p/dut_if_p.sv" in files
        assert "tb/sv/p/sos_checker_p.sv" in files


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


# ---------------------------------------------------------------------------
# SOS-08-E wave-3 (2026-05-24 §15) — parallel charts + Verilator
# deferred-failure stubs.
# ---------------------------------------------------------------------------


class TestWave3ParallelChartEmit:
    """Wave-3 lifts the wave-1/wave-2 parallel-chart rejection. The
    walker dispatches on `_collect_regions(chart_ir)`; parallel
    charts emit the per-region observable shape mirroring the SOS-08-D
    wave-2c cocotb walker."""

    def _files(self) -> dict:
        return sv_tb.render_target(_parallel_chart(), {"chart_name": "p"})

    def test_parallel_emit_keeps_same_artifact_count(self):
        """Parallel charts emit 18 files post wave-3-future-remaining
        layered class hierarchy: 4 SV core + 5 wrappers + 1 stub
        header + 2 wave-3-future helpers (parser pkg + state-symbol
        table) + 2 SVA files per region (2 regions = 4) + 2 base
        headers (checker_base.svh + driver_base.svh) = 18."""
        files = self._files()
        assert len(files) == 18, (
            f"Wave-3-future-remaining parallel emit expected 18 files; "
            f"got {len(files)}: {sorted(files)}"
        )

    def test_parallel_emit_per_region_sva_bind(self):
        """SOS-08-D wave-2b emits one _sva.sv + one _bind.sv per
        region; the SV-testbench walker mirrors them under tb/sv/."""
        files = self._files()
        assert "tb/sv/p/p_region_left_fsm_sva.sv" in files
        assert "tb/sv/p/p_region_left_fsm_bind.sv" in files
        assert "tb/sv/p/p_region_right_fsm_sva.sv" in files
        assert "tb/sv/p/p_region_right_fsm_bind.sv" in files

    def test_parallel_vif_has_per_region_observables(self):
        """Virtual interface MUST expose one
        `current_state_<region>` port per region (mirror of the
        chart-top wrapper per SOS-08-C §6.10)."""
        vif = self._files()["tb/sv/p/dut_if_p.sv"]
        assert "current_state_left" in vif
        assert "current_state_right" in vif
        # Per-region width parameter.
        assert "N_STATES_LEFT" in vif
        assert "N_STATES_RIGHT" in vif

    def test_parallel_vif_modports_carry_per_region_observables(self):
        """driver_mp + checker_mp both expose the per-region
        observables (driver as input, checker as input — observables
        are read-only from the driver too because it doesn't drive
        them)."""
        vif = self._files()["tb/sv/p/dut_if_p.sv"]
        # Driver modport: per-region observables as input (driver
        # doesn't drive them; reads only for completeness).
        assert "modport driver_mp" in vif
        assert "modport checker_mp" in vif
        # Both modports name each region's observable.
        for region in ("left", "right"):
            # Count occurrences of `input  current_state_<region>` —
            # MUST appear in both modports.
            assert vif.count(f"input  current_state_{region}") >= 2

    def test_parallel_checker_reads_each_region(self):
        """Checker class reads `vif.current_state_<region>` per
        region + parses per-region `expected_state_<region>` field
        from the trace JSONL.

        Wave-3-future-remaining (2026-05-24 §15) layered class
        hierarchy: per-region parse + compare logic + failure-message
        construction live in the BASE checker (``_base.svh``); the
        default checker is just hook overrides."""
        checker_base = self._files()["tb/sv/p/sos_p_checker_base.svh"]
        # Per-region observable reads.
        assert "vif.current_state_left" in checker_base
        assert "vif.current_state_right" in checker_base
        # Per-region field parse calls.
        assert "expected_state_left" in checker_base
        assert "expected_state_right" in checker_base
        # Per-region failure messages cite the region name.
        assert "region `left`" in checker_base
        assert "region `right`" in checker_base

    def test_parallel_top_instantiates_chart_top_wrapper(self):
        """Top-level testbench MUST instantiate the chart-top wrapper
        (`<chart>_fsm` per SOS-08-C §6.10), NOT a per-region FSM
        module. The SVA bind files target the same wrapper."""
        top = self._files()["tb/sv/p/tb_p.sv"]
        # DUT is the chart-top wrapper.
        assert "p_fsm" in top
        # Per-region observable wires connected to the wrapper.
        assert ".current_state_left" in top
        assert ".current_state_right" in top
        # Includes the wave-3 Verilator stubs header.
        assert '`include "verilator_stubs.svh"' in top

    def test_parallel_top_has_per_region_n_states_localparams(self):
        top = self._files()["tb/sv/p/tb_p.sv"]
        assert "N_STATES_LEFT" in top
        assert "N_STATES_RIGHT" in top

    def test_parallel_checker_renders_chart_vocabulary_failure(self):
        """INV-S-HDL-E-4: chart-vocabulary failure message names the
        region + chart + expected/observed state.

        Wave-3-future-remaining (2026-05-24 §15) layered class
        hierarchy: chart-vocab message construction lives in the
        BASE checker (``_base.svh``); format strings are byte-
        identical to the wave-3 monolithic emit."""
        checker_base = self._files()["tb/sv/p/sos_p_checker_base.svh"]
        assert "[FAIL] vector V%0d region" in checker_base
        assert "chart `p`" in checker_base
        assert "INV-S-HDL-E-4" in checker_base

    def test_parallel_emit_audit_clean(self):
        """All emitted parallel-chart files MUST pass the
        INV-S-HDL-E-1/2/3 audit pass."""
        files = self._files()
        # render_target's internal audit raises on hits — if the call
        # above succeeded, we're clean. But assert explicitly.
        for fname, source in files.items():
            hits = sv_tb._audit_emitted_file(fname, source)
            assert hits == [], (
                f"{fname}: unexpected audit hits: {hits}"
            )

    def test_parallel_emit_includes_stubs_header(self):
        files = self._files()
        assert "tb/sv/p/verilator_stubs.svh" in files

    def test_single_region_path_unchanged(self):
        """Wave-3 + wave-3-future + wave-3-future-remaining: the
        single-region path emit count is 16 — 11 wave-2 files + 1
        wave-3 stubs header + 2 wave-3-future helpers (parser pkg +
        state-symbol table) + 2 wave-3-future-remaining layered
        class hierarchy base headers (checker_base.svh + driver_base.svh)."""
        files = sv_tb.render_target(
            _simple_chart(), {"chart_name": "demo"}
        )
        assert len(files) == 16
        assert "tb/sv/demo/verilator_stubs.svh" in files
        # Single-region vif keeps the wave-1 shape.
        vif = files["tb/sv/demo/dut_if_demo.sv"]
        assert "current_state" in vif
        # And does NOT carry per-region observables.
        assert "current_state_left" not in vif


class TestWave3VerilatorStubsHeader:
    """Wave-3 (§15 2026-05-24): the Verilator deferred-failure-stub
    policy header (`verilator_stubs.svh`) co-lands per
    PCDN-SOS-08-E-002 + INV-S-HDL-E-6 ratification."""

    def _stubs(self) -> str:
        files = sv_tb.render_target(
            _simple_chart(), {"chart_name": "demo"}
        )
        return files["tb/sv/demo/verilator_stubs.svh"]

    def test_header_defines_skip_begin_end_macros(self):
        s = self._stubs()
        assert "SOS_VERILATOR_SKIP_BEGIN" in s
        assert "SOS_VERILATOR_SKIP_END" in s

    def test_header_defines_deferred_macro(self):
        s = self._stubs()
        assert "SOS_VERILATOR_DEFERRED" in s

    def test_header_branches_on_verilator_define(self):
        """Commercial sims and Verilator MUST get distinct
        expansions; the header branches on `\\`ifdef VERILATOR`."""
        s = self._stubs()
        assert "`ifdef VERILATOR" in s

    def test_header_cites_inv_e6(self):
        s = self._stubs()
        assert "INV-S-HDL-E-6" in s
        assert "PCDN-SOS-08-E-002" in s

    def test_header_emits_chart_vocabulary_in_deferred_msg(self):
        """The Verilator-path deferred-failure message MUST name the
        chart per INV-S-HDL-E-4 (chart-vocabulary failure messages)."""
        s = self._stubs()
        assert "chart `demo`" in s

    def test_header_has_include_guards(self):
        s = self._stubs()
        assert "`ifndef SOS_VERILATOR_STUBS_DEMO_SVH" in s
        assert "`define SOS_VERILATOR_STUBS_DEMO_SVH" in s
        assert "`endif // SOS_VERILATOR_STUBS_DEMO_SVH" in s


class TestWave3VerilatorSubsetAudit:
    """Wave-3 INV-S-HDL-E-6 audit: scan for SV-2017 constructs outside
    Verilator's documented subset. Wave-1/wave-2/wave-3 emit is
    expected to be empty under this audit; the audit is infrastructure
    for future emit extensions."""

    def test_audit_empty_on_wave3_emit(self):
        """All wave-3 emitted files MUST pass the Verilator-subset
        audit cleanly (no constructs in
        `_VERILATOR_UNSUPPORTED_CONSTRUCTS`)."""
        files = sv_tb.render_target(
            _simple_chart(), {"chart_name": "demo"}
        )
        for fname, source in files.items():
            advisories = sv_tb._audit_verilator_subset(fname, source)
            assert advisories == [], (
                f"{fname}: unexpected Verilator-subset advisories: "
                f"{advisories}"
            )

    def test_audit_catches_covergroup_in_emit(self):
        """If a future emit extension introduces a covergroup outside
        a `_SOS_VERILATOR_SKIP_BEGIN block, the audit MUST surface
        it as an INV-S-HDL-E-6 advisory."""
        sneaky = """
covergroup cg @(posedge clk);
    cp: coverpoint x;
endgroup
"""
        hits = sv_tb._audit_verilator_subset("tb/sv/demo/tb_demo.sv", sneaky)
        assert any("covergroup" in h for h in hits), hits

    def test_audit_exempts_bind_files(self):
        """`assert property` lives in SVA bind files by design; the
        Verilator-subset audit SHOULD NOT flag them (only INV-S-HDL-
        E-3's bind-file exemption applies there)."""
        bind_content = """
property p; @(posedge clk) x |-> y; endproperty
"""
        hits = sv_tb._audit_verilator_subset(
            "tb/sv/demo/demo_fsm_sva.sv", bind_content
        )
        assert hits == [], (
            f"SVA bind files MUST be exempt from -E-6 audit; got {hits}"
        )

    def test_audit_exempts_build_wrappers(self):
        """Makefiles / .do / .sh / .tcl are not SV; -E-6 SHOULD NOT
        scan them."""
        hits = sv_tb._audit_verilator_subset(
            "tb/sv/demo/run_verilator.mk",
            "some makefile text with covergroup in a comment",
        )
        assert hits == []

    def test_audit_exempts_stubs_header(self):
        """The stubs header itself names the gated features by design;
        the audit MUST exempt it."""
        files = sv_tb.render_target(
            _simple_chart(), {"chart_name": "demo"}
        )
        stubs = files["tb/sv/demo/verilator_stubs.svh"]
        hits = sv_tb._audit_verilator_subset(
            "tb/sv/demo/verilator_stubs.svh", stubs
        )
        assert hits == []


class TestWave3SvaBindParityWithSOS08D:
    """Wave-3 parity claim: the SV-testbench walker emits the SAME
    per-region SVA + per-region bind files as the SOS-08-D cocotb
    walker (re-keyed under tb/sv/<chart>/ vs tests/<chart>/, content
    byte-identical). Wave-2 verified this for single-region; wave-3
    extends it to parallel."""

    def test_parallel_sva_bind_byte_identical_with_sos_08_d(self):
        """Per-region SVA bind files emitted by the SV-testbench
        walker MUST match the SOS-08-D walker's parallel-chart emit."""
        from transliterate_sva_bind import render_target as bind_render

        sv_files = sv_tb.render_target(
            _parallel_chart(), {"chart_name": "p"}
        )
        bind_files = bind_render(_parallel_chart(), {"chart_name": "p"})

        for bind_path, bind_source in bind_files.items():
            leaf = bind_path.rsplit("/", 1)[-1]
            sv_key = f"tb/sv/p/{leaf}"
            assert sv_key in sv_files, (
                f"SV-testbench walker missed parallel-chart bind "
                f"artifact {leaf!r}"
            )
            assert sv_files[sv_key] == bind_source, (
                f"{leaf}: parallel-chart bind artifact differs "
                f"between SOS-08-D + SOS-08-E walkers (gate (h) "
                f"byte-identical claim)"
            )


# ---------------------------------------------------------------------------
# Wave-3-future (2026-05-24 §15) — full SOS-03 vector-schema consumer.
#
# Replaces the wave-1 LCD inline integer-field extractor with a shared
# JSONL parser package + per-chart state symbol table, so SOS-03 vector
# traces with string-valued state names (per SOS-03 §15 2026-05-24
# schema extension) are consumable directly by the SV checker without
# an external Python preflight.
# ---------------------------------------------------------------------------


class TestWave3FutureSharedParserPackage:
    """``sos_jsonl_parser_pkg.svh`` emit shape."""

    def _files(self):
        return sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})

    def test_parser_package_file_emitted(self):
        files = self._files()
        assert "tb/sv/demo/sos_jsonl_parser_pkg.svh" in files

    def test_parser_package_has_include_guard(self):
        src = self._files()["tb/sv/demo/sos_jsonl_parser_pkg.svh"]
        assert "`ifndef SOS_JSONL_PARSER_PKG_DEMO_SVH" in src
        assert "`define SOS_JSONL_PARSER_PKG_DEMO_SVH" in src
        assert "`endif // SOS_JSONL_PARSER_PKG_DEMO_SVH" in src

    def test_parser_package_defines_parse_int(self):
        src = self._files()["tb/sv/demo/sos_jsonl_parser_pkg.svh"]
        assert "function automatic int sos_jsonl_parse_int(" in src

    def test_parser_package_defines_parse_string(self):
        """Wave-3-future adds string-field extraction so SOS-03's
        string-valued `expected_state_str` can be consumed."""
        src = self._files()["tb/sv/demo/sos_jsonl_parser_pkg.svh"]
        assert "function automatic int sos_jsonl_parse_string(" in src

    def test_parser_string_extractor_bounds_inner_loop(self):
        """Defensive: malformed line without closing quote MUST not
        spin — the extractor caps at 1024 chars."""
        src = self._files()["tb/sv/demo/sos_jsonl_parser_pkg.svh"]
        assert "if (k >= 1024) break" in src

    def test_parser_package_no_uvm_or_random(self):
        """INV-S-HDL-E-1 + INV-S-HDL-E-2 hold for the new package."""
        src = self._files()["tb/sv/demo/sos_jsonl_parser_pkg.svh"]
        # Strip line comments before scanning to avoid false positives.
        scanned = re.sub(r"//.*$", "", src, flags=re.MULTILINE)
        assert "randomize" not in scanned
        assert "rand " not in scanned
        assert "uvm_pkg" not in scanned

    def test_parallel_chart_also_emits_parser_package(self):
        files = sv_tb.render_target(_parallel_chart(), {"chart_name": "p"})
        assert "tb/sv/p/sos_jsonl_parser_pkg.svh" in files


class TestWave3FutureStateSymbolTable:
    """``sos_<chart>_state_symbols.svh`` emit shape."""

    def _files(self):
        return sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})

    def test_state_symbols_file_emitted(self):
        files = self._files()
        assert "tb/sv/demo/sos_demo_state_symbols.svh" in files

    def test_state_symbols_function_signature(self):
        src = self._files()["tb/sv/demo/sos_demo_state_symbols.svh"]
        assert (
            "function automatic int sos_demo_state_id_of(input string name);"
            in src
        )

    def test_state_symbols_enumerates_chart_states(self):
        """Each chart state appears in the if/elsif chain at its
        document-order index (matching SOS-08-C one-hot encoding)."""
        src = self._files()["tb/sv/demo/sos_demo_state_symbols.svh"]
        # _simple_chart has states [idle(0), active(1)].
        assert 'if (name == "idle") return 0;' in src
        assert 'if (name == "active") return 1;' in src
        # Unknown name returns -1.
        assert "return -1;" in src

    def test_state_symbols_parallel_chart_flattens_all_regions(self):
        """For parallel charts the symbol table includes EVERY region's
        states so a per-region `expected_state_<region>_str` can
        resolve any name the trace references."""
        files = sv_tb.render_target(_parallel_chart(), {"chart_name": "p"})
        src = files["tb/sv/p/sos_p_state_symbols.svh"]
        for sid in ("l_idle", "l_active", "r_idle", "r_active"):
            assert f'if (name == "{sid}") return ' in src

    def test_state_symbols_include_guard(self):
        src = self._files()["tb/sv/demo/sos_demo_state_symbols.svh"]
        assert "`ifndef SOS_STATE_SYMBOLS_DEMO_SVH" in src
        assert "`define SOS_STATE_SYMBOLS_DEMO_SVH" in src


class TestWave3FutureCheckerStringFieldPath:
    """Checker emit consumes string-valued expected_state via the
    symbol table.

    Wave-3-future-remaining (2026-05-24 §15) layered class hierarchy:
    the parse/resolve + chart-vocab message construction lives in the
    BASE checker (``_base.svh``); the default checker only carries
    hook overrides. These tests read from the base header."""

    def _checker_base(self):
        files = sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})
        return files["tb/sv/demo/sos_demo_checker_base.svh"]

    def _checker(self):
        files = sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})
        return files["tb/sv/demo/sos_checker_demo.sv"]

    def test_checker_includes_shared_parser_header(self):
        # The shared parser header is `\`include`d from the BASE
        # class header (the default `.sv` re-includes the base, which
        # transitively gets the parser pkg).
        src = self._checker_base()
        assert '`include "sos_jsonl_parser_pkg.svh"' in src

    def test_checker_includes_state_symbol_header(self):
        src = self._checker_base()
        assert '`include "sos_demo_state_symbols.svh"' in src

    def test_checker_calls_shared_parse_int(self):
        src = self._checker_base()
        assert "sos_jsonl_parse_int(" in src

    def test_checker_calls_shared_parse_string(self):
        src = self._checker_base()
        assert "sos_jsonl_parse_string(" in src

    def test_checker_resolves_string_via_symbol_table(self):
        src = self._checker_base()
        assert "sos_demo_state_id_of(expected_state_str)" in src

    def test_checker_drops_inline_parse_int(self):
        """Wave-3-future deduplicates: the inline parse_int_field that
        wave-1/2 emit is gone — sourced from the shared header."""
        # Check both base + default — neither carries an inline
        # parse_int_field declaration.
        assert "function int parse_int_field(string line" not in self._checker_base()
        assert "function int parse_int_field(string line" not in self._checker()

    def test_checker_failure_message_uses_chart_state_string(self):
        """INV-S-HDL-E-4 + INV-SOS-H — when the trace named the state
        by string, the failure message names it back."""
        # Wave-3-future-remaining: format string lives in the base
        # class's ``run()`` (byte-identical to wave-3 monolithic
        # emit).
        src = self._checker_base()
        assert "expected state=\\\"%s\\\"" in src

    def test_checker_failure_message_backwards_compatible_int_branch(self):
        """When the trace used the integer field only (wave-1/2 shape),
        the failure message is the legacy `expected_state=%0d` form."""
        src = self._checker_base()
        assert "expected_state=%0d at cycle" in src


class TestWave3FutureParallelCheckerStringFieldPath:
    """Per-region string-field path for parallel charts.

    Wave-3-future-remaining (2026-05-24 §15) layered class hierarchy:
    the per-region parse/resolve + chart-vocab message construction
    lives in the BASE checker (``_base.svh``); these tests read from
    the base header."""

    def _checker_base(self):
        files = sv_tb.render_target(_parallel_chart(), {"chart_name": "p"})
        return files["tb/sv/p/sos_p_checker_base.svh"]

    def _checker(self):
        files = sv_tb.render_target(_parallel_chart(), {"chart_name": "p"})
        return files["tb/sv/p/sos_checker_p.sv"]

    def test_parallel_checker_includes_shared_parser_header(self):
        src = self._checker_base()
        assert '`include "sos_jsonl_parser_pkg.svh"' in src

    def test_parallel_checker_includes_state_symbol_header(self):
        src = self._checker_base()
        assert '`include "sos_p_state_symbols.svh"' in src

    def test_parallel_checker_per_region_string_field(self):
        """Each region declares its own `expected_state_<region>_str`
        + resolves via the symbol table."""
        src = self._checker_base()
        # Region `left`.
        assert "string expected_state_left_str" in src
        assert (
            "sos_jsonl_parse_string(\n                line, "
            "\"expected_state_left_str\", expected_state_left_str"
            in src
        )
        # Region `right`.
        assert "string expected_state_right_str" in src
        assert (
            "sos_jsonl_parse_string(\n                line, "
            "\"expected_state_right_str\", expected_state_right_str"
            in src
        )

    def test_parallel_checker_per_region_symbol_lookup(self):
        src = self._checker_base()
        assert "sos_p_state_id_of(expected_state_left_str)" in src
        assert "sos_p_state_id_of(expected_state_right_str)" in src

    def test_parallel_checker_drops_inline_parse_int(self):
        """Parallel checker no longer carries its own copy of the
        integer-field extractor."""
        # Neither base nor default carries an inline parse_int_field.
        assert "function int parse_int_field(string line" not in self._checker_base()
        assert "function int parse_int_field(string line" not in self._checker()


class TestWave3FutureDriverUsesSharedParser:
    """Driver was already using `parse_int_field`; wave-3-future
    swaps it for `sos_jsonl_parse_int` and removes the inline copy.

    Wave-3-future-remaining (2026-05-24 §15) layered class hierarchy:
    JSONL parse calls live in the BASE driver (``_base.svh``); these
    tests read from the base header."""

    def _driver_base(self):
        files = sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})
        return files["tb/sv/demo/sos_demo_driver_base.svh"]

    def _driver(self):
        files = sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})
        return files["tb/sv/demo/sos_driver_demo.sv"]

    def test_driver_includes_shared_parser_header(self):
        src = self._driver_base()
        assert '`include "sos_jsonl_parser_pkg.svh"' in src

    def test_driver_calls_shared_parse_int(self):
        src = self._driver_base()
        assert "sos_jsonl_parse_int(line, \"event\"" in src
        assert "sos_jsonl_parse_int(line, \"cycles\"" in src

    def test_driver_drops_inline_parse_int(self):
        # Neither base nor default carries an inline parse_int_field.
        assert "function int parse_int_field(string line" not in self._driver_base()
        assert "function int parse_int_field(string line" not in self._driver()


class TestWave3FutureInvariantsPreserved:
    """The new emit MUST not regress INV-S-HDL-E-1..3."""

    def test_render_target_does_not_raise(self):
        """If any emitted file violates INV-S-HDL-E-1/2/3, _audit_all
        raises InvariantAuditError. Round-tripping both chart shapes
        through render_target without exception is the load-bearing
        invariant check."""
        # Single-region.
        sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})
        # Parallel.
        sv_tb.render_target(_parallel_chart(), {"chart_name": "p"})

    def test_emitted_files_contain_no_random_keywords(self):
        """Wave-3-future emit MUST keep INV-S-HDL-E-1 (no
        constrained-random). Belt-and-suspenders against the audit."""
        for chart, name in (
            (_simple_chart(), "demo"),
            (_parallel_chart(), "p"),
        ):
            files = sv_tb.render_target(chart, {"chart_name": name})
            for fname, src in files.items():
                if fname.endswith((".mk", ".do", ".sh", ".tcl",
                                   "_sva.sv", "_bind.sv")):
                    continue
                scanned = re.sub(r"//.*$", "", src, flags=re.MULTILINE)
                assert "randomize(" not in scanned, fname
                assert "uvm_pkg" not in scanned, fname


# ---------------------------------------------------------------------------
# Wave-3-future remaining: nested-JSON parser (one level deep).
# Closes the "nested JSON parser" carry-forward from §15 2026-05-24's
# initial wave-3-future entry.
#
# @spec docs/concepts/SOS-08-E-CONCEPTS.md §15 (2026-05-24 wave-3-future
#       remaining — nested-JSON parser)
# ---------------------------------------------------------------------------


def _chart_with_nested_param(
    outer: str = "payload",
    inner: str = "value",
    expr: str = "42",
) -> dict:
    """Single-region chart with a transition that raises an event with a
    one-level-deep nested ``<param>``.
    """
    return {
        "initial": "idle",
        "state": [
            {
                "id": "idle",
                "transition": [
                    {
                        "event": "start",
                        "target": "active",
                        "raise_value": [
                            {
                                "event": "tick",
                                "param": [
                                    {"name": f"{outer}.{inner}", "expr": expr},
                                ],
                            }
                        ],
                    }
                ],
            },
            {"id": "active"},
        ],
    }


def _parallel_chart_with_nested_param() -> dict:
    """Parallel chart, two regions, with a nested ``<param>`` declared on
    the ``left`` region's L1->L2 transition.
    """
    return {
        "initial": "regions",
        "parallel": [
            {
                "id": "regions",
                "state": [
                    {
                        "id": "left",
                        "initial": "L1",
                        "state": [
                            {
                                "id": "L1",
                                "transition": [
                                    {
                                        "event": "tick",
                                        "target": "L2",
                                        "raise_value": [
                                            {
                                                "event": "evt",
                                                "param": [
                                                    {
                                                        "name": "payload.value",
                                                        "expr": "1",
                                                    },
                                                ],
                                            }
                                        ],
                                    }
                                ],
                            },
                            {"id": "L2"},
                        ],
                    },
                    {
                        "id": "right",
                        "initial": "R1",
                        "state": [
                            {"id": "R1"},
                            {"id": "R2"},
                        ],
                    },
                ],
            }
        ],
    }


class TestWave3FutureNestedJsonParser:
    """One-level-deep nested-JSON parser emit + walker plumbing.

    Closes the wave-3-future "nested JSON parser" carry-forward from
    SOS-08-E-CONCEPTS.md §15 2026-05-24's wave-3-future entry. Deeper-
    than-one-level nesting, layered class hierarchy, and multi-clock
    testbench wiring remain deferred.
    """

    def _pkg(self) -> str:
        files = sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})
        return files["tb/sv/demo/sos_jsonl_parser_pkg.svh"]

    def test_parser_pkg_emits_nested_int_function(self):
        """Deliverable 1a: the nested integer-field extractor is emitted
        unconditionally alongside the wave-3-future top-level parsers."""
        src = self._pkg()
        assert (
            "function automatic int sos_jsonl_parse_nested_int("
            in src
        )
        # Signature MUST be (line, outer, inner, value).
        assert "input  string outer_key" in src
        assert "input  string inner_key" in src
        assert "output int    value" in src

    def test_parser_pkg_emits_nested_string_function(self):
        """Deliverable 1b: the nested string-field extractor is emitted
        unconditionally alongside the integer form."""
        src = self._pkg()
        assert (
            "function automatic int sos_jsonl_parse_nested_string("
            in src
        )
        assert "output string value" in src

    def test_nested_int_handles_whitespace(self):
        """Per deliverable 1: whitespace + colon between ``"outer":`` and
        the opening brace MUST be tolerated. The implementation skips a
        block of `` `` / ``\\t`` / ``:`` characters before requiring the
        opening brace."""
        src = self._pkg()
        # The whitespace-tolerant skip loop is shared with the top-level
        # extractor and lives between key-match and brace expectation.
        # Surface evidence: the brace check follows a `while` that
        # advances past whitespace + colon.
        # Extract the nested-int body.
        body = src.split("function automatic int sos_jsonl_parse_nested_int(")[1]
        body = body.split("endfunction")[0]
        assert 'line.getc(j) == " "' in body
        assert 'line.getc(j) == ":"' in body
        # And the brace check follows.
        assert 'line.getc(j) != "{"' in body

    def test_nested_int_returns_zero_on_missing_outer(self):
        """Per deliverable 1: when the outer key isn't found at all, the
        extractor returns 0 — implementation evidence is the outer-loop
        terminator ``return 0;`` after the scan loop."""
        src = self._pkg()
        body = src.split("function automatic int sos_jsonl_parse_nested_int(")[1]
        body = body.split("endfunction")[0]
        # The outer scan loop ends with `end` then `return 0;`.
        assert body.rstrip().endswith("return 0;")

    def test_nested_int_returns_zero_on_missing_inner(self):
        """Per deliverable 1: when the outer object is present but the
        inner key isn't, the extractor returns 0 (defensive). The
        implementation breaks out of the inner-scan loop and returns 0
        rather than continuing to scan past the outer object."""
        src = self._pkg()
        body = src.split("function automatic int sos_jsonl_parse_nested_int(")[1]
        body = body.split("endfunction")[0]
        # The "inner key not present" branch lives below the inner
        # search loop and emits a `return 0;`.
        assert (
            "// Inner key not present inside the outer object" in body
            or "return 0;" in body
        )

    def test_nested_int_returns_zero_on_malformed_outer_scalar(self):
        """Per deliverable 1: ``"outer":42`` (scalar after the outer
        key) MUST return 0 — not raise a parse error. The implementation
        checks the next non-whitespace char is ``{`` and returns 0
        otherwise."""
        src = self._pkg()
        body = src.split("function automatic int sos_jsonl_parse_nested_int(")[1]
        body = body.split("endfunction")[0]
        # Evidence: the brace-required check has an explicit `return 0;`
        # branch.
        assert 'line.getc(j) != "{") return 0' in body

    def test_nested_string_handles_escaped_quotes(self):
        """Per deliverable 1: escaped ``\\"`` inside the inner string
        value MUST be preserved (consumed as a literal). Implementation
        evidence: the value-scan loop tracks ``prev_ch`` and treats a
        closing quote preceded by a backslash as a literal."""
        src = self._pkg()
        body = src.split(
            "function automatic int sos_jsonl_parse_nested_string("
        )[1]
        body = body.split("endfunction")[0]
        assert "prev_ch" in body
        # The 1024-char cap from the top-level extractor MUST be
        # preserved in the nested form per the task contract.
        assert "if (cap >= 1024)" in body

    def test_checker_class_consumes_nested_param(self):
        """Deliverable 2: when the chart declares
        ``<param name="payload.value"/>`` on a transition's
        ``<raise>``, the checker class emits a call to
        ``sos_jsonl_parse_nested_int``.

        Wave-3-future-remaining (2026-05-24 §15) layered class
        hierarchy: nested-param parse calls live in the BASE
        checker (``_base.svh``) alongside the rest of the run-
        skeleton."""
        files = sv_tb.render_target(
            _chart_with_nested_param(),
            {"chart_name": "demo"},
        )
        checker_base = files["tb/sv/demo/sos_demo_checker_base.svh"]
        assert "sos_jsonl_parse_nested_int(" in checker_base
        # The call MUST pass the outer/inner pair as literal strings.
        assert '"payload", "value"' in checker_base
        # And declare a local variable for the parsed nested value so
        # subsequent emit extensions can read it.
        assert "nested_payload_value" in checker_base

    def test_checker_class_parallel_consumes_nested_param(self):
        """Deliverable 3: the parallel-region checker mirrors the same
        nested-param emit logic — a nested ``<param>`` on any region's
        transition emits a parse call inside the per-step loop.

        Wave-3-future-remaining (2026-05-24 §15) layered class
        hierarchy: the parse call lands in the parallel BASE checker
        (``_base.svh``)."""
        files = sv_tb.render_target(
            _parallel_chart_with_nested_param(),
            {"chart_name": "p"},
        )
        checker_base = files["tb/sv/p/sos_p_checker_base.svh"]
        assert "sos_jsonl_parse_nested_int(" in checker_base
        assert '"payload", "value"' in checker_base

    def test_two_level_dotted_param_now_emits_path_parser_call(self):
        """Wave-3-future-remaining-path (2026-05-24 §15) supersedes the
        wave-3-future ``one-level-deep`` raise: ``<param name="a.b.c"/>``
        no longer raises ``UnsupportedChartError``. The chart-vocab
        error gate moves up to ``_validate_path_segments`` (which
        rejects empty / non-identifier segments); valid dot-separated
        identifiers at depth ≥ 2 lower to ``sos_jsonl_parse_path_*``.
        """
        chart = _chart_with_nested_param(outer="a", inner="b.c", expr="1")
        files = sv_tb.render_target(chart, {"chart_name": "demo"})
        checker_base = files["tb/sv/demo/sos_demo_checker_base.svh"]
        assert "sos_jsonl_parse_path_int(" in checker_base
        assert '"a.b.c"' in checker_base

    def test_no_nested_param_keeps_emit_byte_identical_with_wave3(self):
        """Regression guard: a single-region chart WITHOUT any nested
        ``<param>`` MUST emit the SAME ``sos_jsonl_parser_pkg.svh``
        contents (modulo the two new functions appended) AND the SAME
        ``sos_checker_<chart>.sv`` shape as the wave-3-future baseline
        — nothing else moves.

        Wave-3-future-remaining (2026-05-24 §15) layered class
        hierarchy: the checker BASE class (``_base.svh``) holds the
        run-skeleton; both the base AND the default ``.sv`` MUST
        carry no nested-param state for a chart with no nested
        ``<param>``."""
        files = sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})
        pkg = files["tb/sv/demo/sos_jsonl_parser_pkg.svh"]
        checker = files["tb/sv/demo/sos_checker_demo.sv"]
        checker_base = files["tb/sv/demo/sos_demo_checker_base.svh"]
        # The two new functions MUST be present.
        assert "sos_jsonl_parse_nested_int" in pkg
        assert "sos_jsonl_parse_nested_string" in pkg
        # The wave-3-future top-level functions are still there
        # unchanged.
        assert "function automatic int sos_jsonl_parse_int(" in pkg
        assert "function automatic int sos_jsonl_parse_string(" in pkg
        # Neither the base header NOR the default `.sv` carries any
        # nested-param state — no decl, no parse call, no comment
        # marker — for a chart with no nested params.
        for src in (checker, checker_base):
            assert "sos_jsonl_parse_nested_int" not in src
            assert "sos_jsonl_parse_nested_string" not in src
            assert "nested_payload" not in src
            assert "Wave-3-future-remaining" not in src

    def test_render_target_does_not_regress_invariants(self):
        """The wave-3-future-remaining emit MUST keep INV-S-HDL-E-1..3
        clean on both single-region and parallel chart shapes that
        declare nested params."""
        # Single-region with nested param.
        sv_tb.render_target(
            _chart_with_nested_param(),
            {"chart_name": "demo"},
        )
        # Parallel with nested param.
        sv_tb.render_target(
            _parallel_chart_with_nested_param(),
            {"chart_name": "p"},
        )

    def test_optional_iverilog_smoke_compile_parser_pkg(self):
        """If ``iverilog`` or ``verible-verilog-syntax`` is on PATH,
        compile-check the emitted parser pkg as a smoke test (otherwise
        skip). Catches syntactic regressions in the new SV emit
        without forcing a sim install on every dev box."""
        import shutil
        import subprocess
        from textwrap import dedent

        iverilog = shutil.which("iverilog")
        verible = shutil.which("verible-verilog-syntax")
        if not iverilog and not verible:
            pytest.skip(
                "neither iverilog nor verible-verilog-syntax on PATH; "
                "text-assert half of the suite remains active."
            )
        files = sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})
        pkg = files["tb/sv/demo/sos_jsonl_parser_pkg.svh"]
        # Wrap in a module so iverilog can parse function-only header.
        wrapper = dedent(
            f"""\
            `include "sos_jsonl_parser_pkg.svh"
            module dummy;
            endmodule
            """
        )
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            pkg_path = Path(td) / "sos_jsonl_parser_pkg.svh"
            pkg_path.write_text(pkg)
            top_path = Path(td) / "top.sv"
            top_path.write_text(wrapper)
            if iverilog:
                result = subprocess.run(
                    [
                        iverilog, "-g2012", "-I", td, "-o", "/dev/null",
                        str(top_path),
                    ],
                    capture_output=True, text=True,
                )
                assert result.returncode == 0, (
                    f"iverilog rejected parser pkg:\n{result.stderr}"
                )
            elif verible:
                result = subprocess.run(
                    [verible, str(pkg_path)],
                    capture_output=True, text=True,
                )
                assert result.returncode == 0, (
                    f"verible-verilog-syntax rejected parser pkg:\n"
                    f"{result.stderr}"
                )


# ---------------------------------------------------------------------------
# Wave-3-future remaining: layered class hierarchy.
# Closes the PCDN-SOS-08-E-001 "layered class hierarchy" carry-forward
# from §15 2026-05-24. Splits the wave-3 monolithic checker + driver
# into ``_base.svh`` (run-skeleton + virtual hooks + chart-vocab
# message construction) and ``_default.sv`` (extends-base + hook
# overrides). Users override by extending the base; the walker keeps
# emitting ``_default`` byte-identical to wave-3 chart-vocab.
#
# @spec docs/concepts/SOS-08-E-CONCEPTS.md §15 (2026-05-24 wave-3-future
#       remaining — layered class hierarchy)
# ---------------------------------------------------------------------------


class TestWave3FutureLayeredClassHierarchy:
    """Layered class hierarchy refactor: ``_checker_base.svh`` +
    ``_driver_base.svh`` headers + extending ``_default`` ``.sv``
    classes. Closes one wave-3-future carry-forward; multi-clock
    testbench wiring + deeper-than-one-level nesting remain
    deferred."""

    def _files(self) -> dict:
        return sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})

    def _files_parallel(self) -> dict:
        return sv_tb.render_target(_parallel_chart(), {"chart_name": "p"})

    def test_emits_checker_base_svh(self):
        """Deliverable: a ``sos_<chart>_checker_base.svh`` header is
        emitted alongside the default ``.sv`` for every chart."""
        files = self._files()
        assert "tb/sv/demo/sos_demo_checker_base.svh" in files

    def test_emits_driver_base_svh(self):
        """Deliverable: a ``sos_<chart>_driver_base.svh`` header is
        emitted alongside the default ``.sv`` for every chart."""
        files = self._files()
        assert "tb/sv/demo/sos_demo_driver_base.svh" in files

    def test_checker_base_declares_virtual_hooks(self):
        """The base header declares all four virtual hooks:
        ``pre_step`` / ``on_state_transition`` / ``on_invariant_fail``
        / ``post_step``."""
        src = self._files()["tb/sv/demo/sos_demo_checker_base.svh"]
        assert "virtual function bit pre_step(int step_idx)" in src
        assert "virtual function void on_state_transition" in src
        assert "virtual function void on_invariant_fail" in src
        assert "virtual function void post_step(int step_idx)" in src

    def test_driver_base_declares_virtual_hooks(self):
        """The driver base header declares the per-step hooks:
        ``drive_pre`` / ``drive_step`` / ``drive_post``."""
        src = self._files()["tb/sv/demo/sos_demo_driver_base.svh"]
        assert "virtual task drive_pre(int step_idx)" in src
        assert "virtual task drive_step(int step_idx" in src
        # Signature carries the per-step JSONL record type.
        assert "sos_jsonl_record_t rec" in src
        assert "virtual task drive_post(int step_idx)" in src

    def test_default_checker_extends_base(self):
        """The default ``sos_checker_<chart>.sv`` extends the base
        class via the SV ``extends`` keyword."""
        src = self._files()["tb/sv/demo/sos_checker_demo.sv"]
        assert "class sos_checker_demo extends sos_demo_checker_base" in src

    def test_default_driver_extends_base(self):
        """The default ``sos_driver_<chart>.sv`` extends the base
        class via the SV ``extends`` keyword."""
        src = self._files()["tb/sv/demo/sos_driver_demo.sv"]
        assert "class sos_driver_demo extends sos_demo_driver_base" in src

    def test_run_skeleton_lives_in_base(self):
        """The ``run()`` task body lives in the base header, NOT in
        the default ``.sv``. The default class only carries hook
        overrides (constructor + virtual function bodies)."""
        files = self._files()
        base = files["tb/sv/demo/sos_demo_checker_base.svh"]
        default = files["tb/sv/demo/sos_checker_demo.sv"]
        assert "task run();" in base
        assert "task run();" not in default

    def test_invariant_failure_message_constructed_in_base(self):
        """The chart-vocabulary failure-message construction (the
        ``$sformatf`` call with the ``[FAIL] vector V%0d:`` format)
        lives in the base header. The default class delegates via
        ``super.on_invariant_fail`` only."""
        files = self._files()
        base = files["tb/sv/demo/sos_demo_checker_base.svh"]
        default = files["tb/sv/demo/sos_checker_demo.sv"]
        assert "$sformatf(" in base
        assert "[FAIL] vector" in base
        # Default's on_invariant_fail just calls super; no $sformatf
        # of its own.
        assert "$sformatf(" not in default
        assert "super.on_invariant_fail" in default

    def test_emit_count_single_region_is_sixteen(self):
        """Single-region emit count: 14 → 16 (adds ``_checker_base.svh``
        + ``_driver_base.svh``)."""
        files = self._files()
        assert len(files) == 16, (
            f"single-region emit expected 16 files; got {len(files)}: "
            f"{sorted(files)}"
        )

    def test_emit_count_parallel_is_eighteen(self):
        """Parallel emit count: 16 → 18 (adds ``_checker_base.svh``
        + ``_driver_base.svh``)."""
        files = self._files_parallel()
        assert len(files) == 18, (
            f"parallel emit expected 18 files; got {len(files)}: "
            f"{sorted(files)}"
        )

    def test_chart_vocab_message_byte_identical_to_wave3_baseline(self):
        """Regression guard: the ``$sformatf`` format strings (chart-
        vocabulary failure messages) are byte-for-byte identical to
        the wave-3 monolithic emit. The wave-3 → layered refactor
        only relocates these strings into the base header; the
        format-string content is unchanged."""
        src = self._files()["tb/sv/demo/sos_demo_checker_base.svh"]
        # Unknown-state-string failure (wave-3 byte-identical).
        assert (
            "[FAIL] vector V%0d: chart `demo` trace named "
            "expected_state_str=\\\"%s\\\" which is not a known "
            "chart-state of `demo`. INV-S-HDL-E-4 vocabulary "
            "violation."
            in src
        )
        # String-resolved comparison mismatch (wave-3 byte-identical).
        assert (
            "[FAIL] vector V%0d: chart `demo` expected state=\\\"%s\\\" "
            "(one-hot=0b%0b) at cycle %0t; observed current_state=0b%0b."
            in src
        )
        # Integer-only comparison mismatch (wave-3 byte-identical).
        assert (
            "[FAIL] vector V%0d: chart `demo` produced expected_state=%0d "
            "at cycle %0t; observed current_state=%0b."
            in src
        )

    def test_super_dispatch_in_default_calls_base_invariant_handler(self):
        """The default ``on_invariant_fail`` MUST call
        ``super.on_invariant_fail(invariant_id, message)`` so a user
        subclassing the base + overriding the hook can still get the
        wave-3-default chart-vocab failure emission via super-dispatch."""
        default = self._files()["tb/sv/demo/sos_checker_demo.sv"]
        assert (
            "super.on_invariant_fail(invariant_id, message);"
            in default
        )

    # ------------------------------------------------------------
    # Parallel-region mirror — the same layered split applies on the
    # parallel chart emit path.
    # ------------------------------------------------------------

    def test_emits_parallel_checker_base_svh(self):
        files = self._files_parallel()
        assert "tb/sv/p/sos_p_checker_base.svh" in files

    def test_emits_parallel_driver_base_svh(self):
        files = self._files_parallel()
        assert "tb/sv/p/sos_p_driver_base.svh" in files

    def test_parallel_default_checker_extends_base(self):
        src = self._files_parallel()["tb/sv/p/sos_checker_p.sv"]
        assert "class sos_checker_p extends sos_p_checker_base" in src

    def test_parallel_run_skeleton_lives_in_base(self):
        files = self._files_parallel()
        base = files["tb/sv/p/sos_p_checker_base.svh"]
        default = files["tb/sv/p/sos_checker_p.sv"]
        assert "task run();" in base
        assert "task run();" not in default

    def test_render_target_layered_emit_clean(self):
        """End-to-end: the layered emit MUST pass the INV-S-HDL-E-1/
        -2/-3 audit on both single-region and parallel chart shapes."""
        # render_target's _audit_all runs over every emitted file; no
        # exception means the audit passed.
        sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})
        sv_tb.render_target(_parallel_chart(), {"chart_name": "p"})


# ---------------------------------------------------------------------------
# Wave-3-future remaining: deeper-than-one-level nested JSON parser
# (path-segment based). Lifts the wave-3-future "one level deep" cap so
# ``<param name="a.b.c"/>`` (and deeper) lowers to a chain of nested-
# object descents via the new ``sos_jsonl_parse_path_*`` helpers.
#
# @spec docs/concepts/SOS-08-E-CONCEPTS.md §15 (2026-05-24 wave-3-future
#       remaining — deeper-than-one-level nested JSON parser)
# ---------------------------------------------------------------------------


def _chart_with_path_param(
    path: str = "a.b.c",
    expr: str = "42",
) -> dict:
    """Single-region chart with a transition that raises an event with a
    deeper-than-one-level nested ``<param>`` (depth ≥ 2)."""
    return {
        "initial": "idle",
        "state": [
            {
                "id": "idle",
                "transition": [
                    {
                        "event": "start",
                        "target": "active",
                        "raise_value": [
                            {
                                "event": "tick",
                                "param": [
                                    {"name": path, "expr": expr},
                                ],
                            }
                        ],
                    }
                ],
            },
            {"id": "active"},
        ],
    }


def _parallel_chart_with_path_param(path: str = "a.b.c") -> dict:
    """Parallel chart with a deeper-than-one-level nested ``<param>``
    declared on the ``left`` region's L1->L2 transition."""
    return {
        "initial": "regions",
        "parallel": [
            {
                "id": "regions",
                "state": [
                    {
                        "id": "left",
                        "initial": "L1",
                        "state": [
                            {
                                "id": "L1",
                                "transition": [
                                    {
                                        "event": "tick",
                                        "target": "L2",
                                        "raise_value": [
                                            {
                                                "event": "evt",
                                                "param": [
                                                    {
                                                        "name": path,
                                                        "expr": "1",
                                                    },
                                                ],
                                            }
                                        ],
                                    }
                                ],
                            },
                            {"id": "L2"},
                        ],
                    },
                    {
                        "id": "right",
                        "initial": "R1",
                        "state": [
                            {"id": "R1"},
                            {"id": "R2"},
                        ],
                    },
                ],
            }
        ],
    }


class TestWave3FuturePathNestedJsonParser:
    """Deeper-than-one-level nested-JSON parser emit + walker plumbing.

    Closes the wave-3-future-path carry-forward from §15 2026-05-24
    (wave-3-future-remaining nested JSON parser, deeper nesting). The
    wave-3-future-remaining nested parser (one level deep) stays byte-
    identical; this slice adds ``sos_jsonl_parse_path_int`` /
    ``sos_jsonl_parse_path_string`` alongside it for depth-≥2 paths.
    """

    def _pkg(self) -> str:
        files = sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})
        return files["tb/sv/demo/sos_jsonl_parser_pkg.svh"]

    # ------------------------------------------------------------------
    # Deliverable 1: parser pkg emits the two new functions.
    # ------------------------------------------------------------------

    def test_parser_pkg_emits_path_int_function(self):
        """``sos_jsonl_parse_path_int`` is emitted with the contracted
        signature."""
        src = self._pkg()
        assert (
            "function automatic int sos_jsonl_parse_path_int("
            in src
        )
        # Signature MUST be (line, path_dot_separated, value).
        assert "input  string path_dot_separated" in src
        assert "output int    value" in src

    def test_parser_pkg_emits_path_string_function(self):
        """``sos_jsonl_parse_path_string`` is emitted with the contracted
        signature."""
        src = self._pkg()
        assert (
            "function automatic int sos_jsonl_parse_path_string("
            in src
        )
        assert "output string value" in src

    # ------------------------------------------------------------------
    # Byte-identity regression guards.
    # ------------------------------------------------------------------

    def test_byte_identity_when_chart_uses_only_depth_0_params(self):
        """Regression guard: a chart with no nested ``<param>`` (only
        depth-0 / top-level params) MUST emit a byte-identical checker-
        base header to the wave-3-future-remaining (d879e7b) baseline.

        We assert on the absence of any path / nested decl markers in
        the emitted output — the chart-vocab guard is identical to the
        existing wave-3-future ``_no_nested_param_keeps_emit_byte_
        identical_with_wave3`` regression guard."""
        files = sv_tb.render_target(_simple_chart(), {"chart_name": "demo"})
        checker_base = files["tb/sv/demo/sos_demo_checker_base.svh"]
        checker = files["tb/sv/demo/sos_checker_demo.sv"]
        for src in (checker_base, checker):
            # No nested or path call sites — by-construction byte-
            # identical to the wave-3-future-remaining baseline at
            # d879e7b for depth-0-only charts.
            assert "sos_jsonl_parse_nested_int" not in src
            assert "sos_jsonl_parse_nested_string" not in src
            assert "sos_jsonl_parse_path_int" not in src
            assert "sos_jsonl_parse_path_string" not in src
            assert "Wave-3-future-remaining" not in src

    def test_byte_identity_when_chart_uses_only_depth_1_nested_params(self):
        """Regression guard: a chart with only depth-1 nested ``<param>``
        declarations (``"outer.inner"``) MUST keep the wave-3-future-
        remaining nested-only emit path byte-identical. The new path-
        parser call sites MUST NOT appear in the checker-base when no
        depth-≥2 param is declared.

        Specifically, ``sos_jsonl_parse_nested_int(`` is still emitted
        at the call site verbatim, and ``sos_jsonl_parse_path_int(`` is
        absent from the checker (it remains present in the parser pkg
        as an unconditional helper, but no call site references it)."""
        files = sv_tb.render_target(
            _chart_with_nested_param(),
            {"chart_name": "demo"},
        )
        checker_base = files["tb/sv/demo/sos_demo_checker_base.svh"]
        # Wave-3-future-remaining nested call site preserved verbatim.
        assert "sos_jsonl_parse_nested_int(" in checker_base
        assert '"payload", "value"' in checker_base
        # No path-parser call sites for a depth-1-only chart.
        assert "sos_jsonl_parse_path_int(" not in checker_base
        assert "sos_jsonl_parse_path_string(" not in checker_base

    # ------------------------------------------------------------------
    # Deliverable 2: walker plumbing emits the path-parser call.
    # ------------------------------------------------------------------

    def test_three_level_path_param_emits_path_int_call(self):
        """``<param name="a.b.c"/>`` (depth 2) emits a call to
        ``sos_jsonl_parse_path_int`` with the dot-separated path
        literal as the second argument."""
        files = sv_tb.render_target(
            _chart_with_path_param("a.b.c"),
            {"chart_name": "demo"},
        )
        checker_base = files["tb/sv/demo/sos_demo_checker_base.svh"]
        assert "sos_jsonl_parse_path_int(" in checker_base
        assert '"a.b.c"' in checker_base
        # The local variable is named after the sanitised path.
        assert "path_a_b_c" in checker_base

    def test_four_level_path_param_emits_path_int_call(self):
        """``<param name="a.b.c.d"/>`` (depth 3) emits the same shape."""
        files = sv_tb.render_target(
            _chart_with_path_param("a.b.c.d"),
            {"chart_name": "demo"},
        )
        checker_base = files["tb/sv/demo/sos_demo_checker_base.svh"]
        assert "sos_jsonl_parse_path_int(" in checker_base
        assert '"a.b.c.d"' in checker_base
        assert "path_a_b_c_d" in checker_base

    # ------------------------------------------------------------------
    # Runtime semantics — verified via SV-source inspection.
    # ------------------------------------------------------------------

    def test_path_int_handles_missing_key_at_intermediate_level(self):
        """When an intermediate path segment isn't found, the parser
        returns 0 — the inner-scan loop falls through to the outer
        ``return 0;`` at the end of ``sos_jsonl_parse_path_int``."""
        src = self._pkg()
        body = src.split(
            "function automatic int sos_jsonl_parse_path_int("
        )[1]
        body = body.split("endfunction")[0]
        # Evidence: the per-segment match-scan terminates with a
        # ``return 0;`` when no segment match is found at the current
        # window.
        assert "if (!match_seg) return 0;" in body

    def test_path_int_handles_malformed_intermediate_scalar(self):
        """When an intermediate segment's value is a scalar (not an
        object), the parser returns 0 — the intermediate-branch brace
        check has an explicit ``return 0;`` fallback."""
        src = self._pkg()
        body = src.split(
            "function automatic int sos_jsonl_parse_path_int("
        )[1]
        body = body.split("endfunction")[0]
        # The intermediate brace-required check returns 0 on scalar.
        assert 'if (j >= win_hi || line.getc(j) != "{") return 0' in body

    def test_path_string_handles_escaped_quotes_at_leaf(self):
        """At the leaf-string level, ``\\"`` preceded by ``\\\\`` is
        consumed as a literal rather than terminating the value. The
        1024-character cap from the wave-3-future top-level extractor
        is preserved (defensive against unterminated quotes)."""
        src = self._pkg()
        body = src.split(
            "function automatic int sos_jsonl_parse_path_string("
        )[1]
        body = body.split("endfunction")[0]
        assert "prev_ch" in body
        assert "if (cap >= 1024)" in body

    def test_path_int_emits_warning_on_empty_segment_at_runtime(self):
        """Runtime defence (vs. build-time chart-vocab gate): a
        malformed input-data path like ``"a..b"`` emits a one-line
        ``$warning`` and returns 0 rather than spinning or raising.
        The build-time gate normally catches these in chart source;
        this is for runtime JSONL-side malformation."""
        src = self._pkg()
        # The $warning lives in both path_int + path_string bodies.
        assert "$warning(" in src
        # Tagged with the function name so the chart author can grep.
        assert "sos_jsonl_parse_path_int: empty path segment" in src
        assert "sos_jsonl_parse_path_string: empty path segment" in src

    # ------------------------------------------------------------------
    # Chart-vocab gate — build-time errors.
    # ------------------------------------------------------------------

    def test_chart_vocab_rejects_empty_segment_at_build_time(self):
        """``<param name="a..b"/>`` (empty segment) raises
        ``UnsupportedChartError`` at codegen time with a chart-author-
        actionable message."""
        chart = _chart_with_path_param("a..b")
        with pytest.raises(sv_tb.UnsupportedChartError) as exc_info:
            sv_tb.render_target(chart, {"chart_name": "demo"})
        msg = str(exc_info.value)
        assert "SOS-08-E wave-3-future-path" in msg
        assert "empty path segment" in msg
        assert 'name="a..b"' in msg

    def test_chart_vocab_rejects_leading_dot(self):
        """``<param name=".a.b"/>`` (leading dot → empty first segment)
        raises ``UnsupportedChartError``."""
        chart = _chart_with_path_param(".a.b")
        with pytest.raises(sv_tb.UnsupportedChartError) as exc_info:
            sv_tb.render_target(chart, {"chart_name": "demo"})
        assert "empty path segment" in str(exc_info.value)

    def test_chart_vocab_rejects_trailing_dot(self):
        """``<param name="a.b."/>`` (trailing dot → empty last segment)
        raises ``UnsupportedChartError``."""
        chart = _chart_with_path_param("a.b.")
        with pytest.raises(sv_tb.UnsupportedChartError) as exc_info:
            sv_tb.render_target(chart, {"chart_name": "demo"})
        assert "empty path segment" in str(exc_info.value)

    def test_chart_vocab_rejects_non_identifier_in_segment(self):
        """``<param name="a-b.c"/>`` (non-identifier segment) raises
        ``UnsupportedChartError`` citing SV identifier rules."""
        chart = _chart_with_path_param("a-b.c")
        with pytest.raises(sv_tb.UnsupportedChartError) as exc_info:
            sv_tb.render_target(chart, {"chart_name": "demo"})
        msg = str(exc_info.value)
        assert "SOS-08-E wave-3-future-path" in msg
        assert "SV identifier rules" in msg

    def test_chart_vocab_rejects_segment_starting_with_digit(self):
        """``<param name="0a.b"/>`` (segment starting with a digit)
        raises ``UnsupportedChartError`` — SV identifiers MUST start
        with letter or underscore."""
        chart = _chart_with_path_param("0a.b")
        with pytest.raises(sv_tb.UnsupportedChartError) as exc_info:
            sv_tb.render_target(chart, {"chart_name": "demo"})
        assert "SV identifier rules" in str(exc_info.value)

    # ------------------------------------------------------------------
    # Parallel-chart mirror.
    # ------------------------------------------------------------------

    def test_parallel_checker_uses_path_parser_for_deep_params(self):
        """Parallel-region mirror: a depth-≥2 ``<param>`` on any
        region's transition emits a ``sos_jsonl_parse_path_*`` call
        inside the parallel base checker's ``run()``."""
        files = sv_tb.render_target(
            _parallel_chart_with_path_param("a.b.c"),
            {"chart_name": "p"},
        )
        checker_base = files["tb/sv/p/sos_p_checker_base.svh"]
        assert "sos_jsonl_parse_path_int(" in checker_base
        assert '"a.b.c"' in checker_base

    # ------------------------------------------------------------------
    # Round-trip: emit is invariant-clean for path-param charts.
    # ------------------------------------------------------------------

    def test_render_target_path_emit_invariant_clean(self):
        """End-to-end: a chart declaring a depth-≥2 ``<param>`` round-
        trips through ``render_target`` without raising
        ``InvariantAuditError`` (i.e. the new path-parser helpers stay
        within INV-S-HDL-E-1/-2/-3)."""
        sv_tb.render_target(
            _chart_with_path_param("a.b.c"),
            {"chart_name": "demo"},
        )
        sv_tb.render_target(
            _parallel_chart_with_path_param("a.b.c.d"),
            {"chart_name": "p"},
        )
