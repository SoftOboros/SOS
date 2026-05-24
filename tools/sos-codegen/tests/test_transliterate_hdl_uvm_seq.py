"""SOS-08-F UVM sequence walker tests (wave-1).

@spec docs/concepts/SOS-08-F-CONCEPTS.md §5..§7 (emission contract +
      invariants)
@spec docs/concepts/SOS-08-F-CONCEPTS.md §15 (2026-05-23 ratification)
@spec docs/concepts/SOS-07-CONCEPTS.md  §6    (INV-SOS-A..H — cited)
@spec docs/concepts/SOS-07-CONCEPTS.md  §7    (AuthorityRelationship —
      UVM is `derive`)
@spec docs/concepts/SOS-08-CONCEPTS.md  §7    (INV-S-HDL-1..5 — cited)

These tests verify the wave-1 surface of
``transliterate_hdl_uvm_seq.render_target``:
  * Three files emitted per chart (package, header, integration
    example), all rooted under ``uvm/<chart>/`` per §6.
  * Consolidated SystemVerilog package per §5.7 (PCDN-F-006).
  * Baseline ``sos_seq_item`` class with all six chart-vocabulary
    metadata fields per §6.2.
  * Six per-family ``uvm_sequence`` subclasses per §6.1 + §6.3.
  * Empty virtual ``pre_body`` / ``post_body`` hooks per §5.6 +
    PCDN-F-005.
  * `uvm_object_utils` factory registration in-package per §5.5 +
    PCDN-F-004.
  * Audit catches INV-S-HDL-F-1 / -3 / -4 violations.
  * Integration example demonstrates the §6.5 five-step contract.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


TESTS_DIR = Path(__file__).resolve().parent
TOOL_DIR = TESTS_DIR.parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))


uvm_seq = pytest.importorskip(
    "transliterate_hdl_uvm_seq",
    reason="transliterate_hdl_uvm_seq not importable — wave-1 UVM "
    "sequence suite skips until the module lands.",
)


def _simple_chart() -> dict:
    """Minimal chart_ir — SOS-08-F is chart-agnostic so the shape is
    only used for chart-name extraction."""
    return {
        "initial": "idle",
        "state": [{"id": "idle"}, {"id": "active"}],
    }


# ---------------------------------------------------------------------------
# File-set
# ---------------------------------------------------------------------------


class TestFileSet:
    """§6 emission contract: three artifacts per chart."""

    def test_emits_three_files(self):
        files = uvm_seq.render_target(_simple_chart(), {"chart_name": "demo"})
        assert len(files) == 3, (
            f"SOS-08-F §6: expected 3 emitted files, got {len(files)}: "
            f"{sorted(files)}"
        )

    def test_emits_consolidated_package(self):
        files = uvm_seq.render_target(_simple_chart(), {"chart_name": "demo"})
        assert "uvm/demo/sos_uvm_seq_pkg.sv" in files

    def test_emits_header(self):
        files = uvm_seq.render_target(_simple_chart(), {"chart_name": "demo"})
        assert "uvm/demo/sos_uvm_seq_pkg.svh" in files

    def test_emits_integration_example(self):
        files = uvm_seq.render_target(_simple_chart(), {"chart_name": "demo"})
        assert "uvm/demo/sos_uvm_integration_example.sv" in files


# ---------------------------------------------------------------------------
# Consolidated package shape
# ---------------------------------------------------------------------------


class TestPackageStructure:
    """§5.7 + PCDN-F-006: one consolidated `sos_uvm_seq_pkg`."""

    def _pkg(self) -> str:
        files = uvm_seq.render_target(_simple_chart(), {"chart_name": "demo"})
        return files["uvm/demo/sos_uvm_seq_pkg.sv"]

    def test_package_declared(self):
        pkg = self._pkg()
        assert "package sos_uvm_seq_pkg" in pkg
        assert "endpackage" in pkg

    def test_package_imports_uvm_pkg(self):
        # The package MUST import uvm_pkg — that's how its base classes
        # (uvm_sequence, uvm_sequence_item) come into scope.
        assert "import uvm_pkg::*;" in self._pkg()

    def test_package_includes_uvm_macros(self):
        assert "uvm_macros.svh" in self._pkg()

    def test_package_name_helper_matches(self):
        assert uvm_seq.package_name() == "sos_uvm_seq_pkg"


# ---------------------------------------------------------------------------
# Baseline `sos_seq_item`
# ---------------------------------------------------------------------------


class TestBaselineSeqItem:
    """§6.2: baseline transaction class with chart-vocabulary fields."""

    def _pkg(self) -> str:
        return uvm_seq.render_target(_simple_chart(), {"chart_name": "demo"})[
            "uvm/demo/sos_uvm_seq_pkg.sv"
        ]

    def test_sos_seq_item_declared(self):
        pkg = self._pkg()
        assert "class sos_seq_item extends uvm_sequence_item" in pkg

    def test_sos_seq_item_carries_family(self):
        assert "sos_event_family_e family" in self._pkg()

    def test_sos_seq_item_carries_chart_state(self):
        # INV-S-HDL-F-3 + §6.2: chart_state field present.
        assert "chart_state" in self._pkg()

    def test_sos_seq_item_carries_transition_id(self):
        assert "transition_id" in self._pkg()

    def test_sos_seq_item_carries_invariant_id(self):
        assert "invariant_id" in self._pkg()

    def test_sos_seq_item_carries_event_id(self):
        assert "event_id" in self._pkg()

    def test_sos_seq_item_uses_uvm_object_utils_begin(self):
        # PCDN-F-004: in-package factory registration.
        pkg = self._pkg()
        assert "`uvm_object_utils_begin(sos_seq_item)" in pkg
        assert "`uvm_object_utils_end" in pkg

    def test_sos_seq_item_field_macros_present(self):
        pkg = self._pkg()
        for macro in (
            "`uvm_field_enum",
            "`uvm_field_int",
            "`uvm_field_string",
        ):
            assert macro in pkg, (
                f"SOS-08-F §6.2: sos_seq_item missing field macro {macro}"
            )


# ---------------------------------------------------------------------------
# Six per-family sequence subclasses
# ---------------------------------------------------------------------------


class TestPerFamilySequences:
    """§6.1 + §6.3: one sequence subclass per chart event family."""

    def _pkg(self) -> str:
        return uvm_seq.render_target(_simple_chart(), {"chart_name": "demo"})[
            "uvm/demo/sos_uvm_seq_pkg.sv"
        ]

    def test_six_families_frozen(self):
        # PCDN-SOS-08-F-002 resolved 2026-05-23: six families.
        assert uvm_seq.CHART_EVENT_FAMILIES == (
            "task", "sem", "queue", "timer", "event", "tick",
        )

    @pytest.mark.parametrize("family",
                             ("task", "sem", "queue", "timer", "event", "tick"))
    def test_per_family_sequence_class(self, family):
        pkg = self._pkg()
        cls = f"class sos_{family}_sequence extends uvm_sequence #(sos_seq_item)"
        assert cls in pkg, (
            f"SOS-08-F §6.3: missing per-family sequence class for "
            f"family `{family}`"
        )

    def test_sequence_class_name_helper(self):
        assert uvm_seq.sequence_class_name("sem") == "sos_sem_sequence"

    @pytest.mark.parametrize("family",
                             ("task", "sem", "queue", "timer", "event", "tick"))
    def test_per_family_has_object_utils(self, family):
        # §5.5 + PCDN-F-004: in-package factory registration.
        pkg = self._pkg()
        assert f"`uvm_object_utils(sos_{family}_sequence)" in pkg

    @pytest.mark.parametrize("family",
                             ("task", "sem", "queue", "timer", "event", "tick"))
    def test_per_family_has_body_task(self, family):
        # §6.3: every per-family sequence has a body() task.
        pkg = self._pkg()
        assert f"sos_{family}_sequence" in pkg
        # Find the class body and ensure `task body()` appears within
        # a reasonable scope of the class declaration.
        idx = pkg.find(f"class sos_{family}_sequence")
        end = pkg.find(f"endclass : sos_{family}_sequence", idx)
        assert idx >= 0 and end > idx
        block = pkg[idx:end]
        assert "virtual task body()" in block, (
            f"SOS-08-F §6.3: sos_{family}_sequence missing body() task"
        )

    @pytest.mark.parametrize("family",
                             ("task", "sem", "queue", "timer", "event", "tick"))
    def test_per_family_has_pre_post_body_hooks(self, family):
        # §5.6 + PCDN-F-005: empty virtual pre_body / post_body hooks.
        pkg = self._pkg()
        idx = pkg.find(f"class sos_{family}_sequence")
        end = pkg.find(f"endclass : sos_{family}_sequence", idx)
        block = pkg[idx:end]
        assert "virtual task pre_body()" in block, (
            f"SOS-08-F §5.6: sos_{family}_sequence missing pre_body() hook"
        )
        assert "virtual task post_body()" in block, (
            f"SOS-08-F §5.6: sos_{family}_sequence missing post_body() hook"
        )

    @pytest.mark.parametrize(
        "family,family_upper",
        [
            ("task", "TASK"), ("sem", "SEM"), ("queue", "QUEUE"),
            ("timer", "TIMER"), ("event", "EVENT"), ("tick", "TICK"),
        ],
    )
    def test_per_family_sets_family_enum_in_body(self, family, family_upper):
        """§6.3 body() template: tx.family is set to SOS_FAMILY_<FAMILY>."""
        pkg = self._pkg()
        idx = pkg.find(f"class sos_{family}_sequence")
        end = pkg.find(f"endclass : sos_{family}_sequence", idx)
        block = pkg[idx:end]
        assert f"tx.family        = SOS_FAMILY_{family_upper}" in block


# ---------------------------------------------------------------------------
# Discriminated-union enum
# ---------------------------------------------------------------------------


class TestEnum:
    """§5.3 + §6.2: sos_event_family_e enum with six tags."""

    def _pkg(self) -> str:
        return uvm_seq.render_target(_simple_chart(), {"chart_name": "demo"})[
            "uvm/demo/sos_uvm_seq_pkg.sv"
        ]

    def test_enum_declared(self):
        assert "typedef enum" in self._pkg()
        assert "} sos_event_family_e;" in self._pkg()

    @pytest.mark.parametrize(
        "tag",
        ("SOS_FAMILY_TASK", "SOS_FAMILY_SEM", "SOS_FAMILY_QUEUE",
         "SOS_FAMILY_TIMER", "SOS_FAMILY_EVENT", "SOS_FAMILY_TICK"),
    )
    def test_each_family_tag(self, tag):
        assert tag in self._pkg()


# ---------------------------------------------------------------------------
# Header file
# ---------------------------------------------------------------------------


class TestHeader:
    """sos_uvm_seq_pkg.svh exports for split-compilation drivers."""

    def _svh(self) -> str:
        return uvm_seq.render_target(_simple_chart(), {"chart_name": "demo"})[
            "uvm/demo/sos_uvm_seq_pkg.svh"
        ]

    def test_header_has_include_guard(self):
        svh = self._svh()
        assert "`ifndef SOS_UVM_SEQ_PKG_SVH" in svh
        assert "`define SOS_UVM_SEQ_PKG_SVH" in svh
        assert "`endif" in svh

    def test_header_exports_enum(self):
        assert "sos_event_family_e" in self._svh()

    def test_header_exports_chart_event_struct(self):
        assert "sos_chart_event_s" in self._svh()


# ---------------------------------------------------------------------------
# Integration example (§6.5 five-step worked example)
# ---------------------------------------------------------------------------


class TestIntegrationExample:
    """§6.5: informative customer-integration shape."""

    def _ex(self) -> str:
        return uvm_seq.render_target(_simple_chart(), {"chart_name": "demo"})[
            "uvm/demo/sos_uvm_integration_example.sv"
        ]

    def test_step_1_package_import(self):
        assert "import sos_uvm_seq_pkg::*;" in self._ex()

    def test_step_2_sequencer_typedef(self):
        # Step 2: customer declares uvm_sequencer #(sos_seq_item).
        assert "uvm_sequencer #(sos_seq_item)" in self._ex()

    def test_step_3_driver_extends_uvm_driver(self):
        # Step 3: customer-owned uvm_driver subclass (informative).
        assert "extends uvm_driver #(sos_seq_item)" in self._ex()

    def test_step_4_test_class_starts_sequence(self):
        # Step 4: test class invokes seq.start().
        ex = self._ex()
        assert "extends uvm_test" in ex
        assert ".start(" in ex

    def test_step_4_test_class_wires_vector_path(self):
        # Step 4: customer wires the chart's bounded-reachability JSONL.
        assert ".vector_path" in self._ex()

    def test_step_5_chart_vocabulary_failure_format(self):
        # Step 5: §6.6 chart-vocabulary failure-message shape.
        ex = self._ex()
        assert "[SOS-SEQ]" in ex
        assert "tx.chart_state" in ex
        assert "tx.transition_id" in ex
        assert "tx.invariant_id" in ex


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------


class TestInvariants:
    """Audit INV-S-HDL-F-1..5 on the emitted artifact set."""

    def _files(self) -> dict:
        return uvm_seq.render_target(_simple_chart(), {"chart_name": "demo"})

    def test_inv_f1_no_forbidden_uvm_base_classes_in_normative_files(self):
        """INV-S-HDL-F-1: package + header MUST NOT extend uvm_env /
        uvm_agent / uvm_sequencer / uvm_driver / uvm_monitor /
        uvm_scoreboard / uvm_test. (The integration example is
        documentation; it deliberately authors a uvm_driver demo
        shape to illustrate the customer-side contract.)"""
        files = self._files()
        normative = {
            k: v for k, v in files.items()
            if not k.endswith("sos_uvm_integration_example.sv")
        }
        forbidden = (
            "uvm_env", "uvm_agent", "uvm_sequencer", "uvm_driver",
            "uvm_monitor", "uvm_scoreboard", "uvm_test",
        )
        import re as _re
        for fname, src in normative.items():
            scanned = _re.sub(r"//.*$", "", src, flags=_re.MULTILINE)
            for base in forbidden:
                assert not _re.search(
                    rf"\bextends\s+{_re.escape(base)}\b", scanned
                ), (
                    f"INV-S-HDL-F-1 violation in {fname}: extends {base}"
                )

    def test_inv_f1_no_config_db_writes(self):
        """INV-S-HDL-F-1: no uvm_config_db references in normative files."""
        files = self._files()
        normative = {
            k: v for k, v in files.items()
            if not k.endswith("sos_uvm_integration_example.sv")
        }
        import re as _re
        for fname, src in normative.items():
            scanned = _re.sub(r"//.*$", "", src, flags=_re.MULTILINE)
            assert not _re.search(r"\buvm_config_db\s*[#:]", scanned), (
                f"INV-S-HDL-F-1 violation in {fname}: uvm_config_db::"
            )

    def test_inv_f3_metadata_fields_present(self):
        """INV-S-HDL-F-3: chart-vocabulary metadata on sos_seq_item."""
        pkg = self._files()["uvm/demo/sos_uvm_seq_pkg.sv"]
        for field in ("chart_state", "transition_id", "invariant_id"):
            assert field in pkg, (
                f"INV-S-HDL-F-3 violation: sos_seq_item missing field "
                f"`{field}`"
            )

    def test_inv_f4_no_sva_emission(self):
        """INV-S-HDL-F-4: no `assert property`, no `bind` directive."""
        import re as _re
        for fname, src in self._files().items():
            scanned = _re.sub(r"//.*$", "", src, flags=_re.MULTILINE)
            assert not _re.search(r"\bassert\s+property\b", scanned), (
                f"INV-S-HDL-F-4 violation in {fname}: assert property"
            )
            assert not _re.search(r"^\s*bind\s+\w+", scanned,
                                  flags=_re.MULTILINE), (
                f"INV-S-HDL-F-4 violation in {fname}: bind directive"
            )

    def test_inv_f5_uvm_1_2_grammar_only(self):
        """INV-S-HDL-F-5: emitter uses only UVM 1.2 grammar constructs.

        Wave-1 check: the emitted code does NOT use UVM 2.0-only APIs
        (e.g. `uvm_resource_db` post-1.2 forms, `uvm_event_pool` post-1.2
        forms). The walker uses only `uvm_sequence`, `uvm_sequence_item`,
        `uvm_object_utils*`, `uvm_field_*`, and `uvm_error` — all UVM 1.2
        grammar that runs unchanged on UVM 2.0.
        """
        pkg = self._files()["uvm/demo/sos_uvm_seq_pkg.sv"]
        # Allowed list — every uvm_* macro/class the package uses MUST
        # be in this set. Any new uvm_* reference is a wave-2 ratification.
        allowed_uvm_tokens = {
            "uvm_pkg", "uvm_macros", "uvm_sequence", "uvm_sequence_item",
            "uvm_object_utils", "uvm_object_utils_begin",
            "uvm_object_utils_end", "uvm_field_enum", "uvm_field_int",
            "uvm_field_string",
        }
        import re as _re
        tokens = set(_re.findall(r"\buvm_\w+", pkg))
        unexpected = tokens - allowed_uvm_tokens
        assert not unexpected, (
            f"INV-S-HDL-F-5: package uses UVM tokens not on the "
            f"UVM-1.2-known-good list: {sorted(unexpected)}. Adding "
            f"such a token requires a §15 amendment confirming the "
            f"token exists in both UVM 1.2 and UVM 2.0."
        )


# ---------------------------------------------------------------------------
# Invariant audit error path
# ---------------------------------------------------------------------------


class TestInvariantAuditErrorPath:
    """The walker's internal audit catches forbidden constructs."""

    def test_audit_catches_extends_uvm_env(self):
        with pytest.raises(uvm_seq.InvariantAuditError):
            uvm_seq._audit_all({
                "uvm/x/sos_uvm_seq_pkg.sv":
                    "package sos_uvm_seq_pkg;\n"
                    "  class my_env extends uvm_env;\n  endclass\n"
                    "endpackage\n",
            })

    def test_audit_catches_assert_property(self):
        with pytest.raises(uvm_seq.InvariantAuditError):
            uvm_seq._audit_all({
                "uvm/x/sos_uvm_seq_pkg.sv":
                    "package sos_uvm_seq_pkg;\n"
                    "  assert property (@(posedge clk) 1) else $error;\n"
                    "endpackage\n",
            })

    def test_audit_catches_bind_directive(self):
        with pytest.raises(uvm_seq.InvariantAuditError):
            uvm_seq._audit_all({
                "uvm/x/sos_uvm_seq_pkg.sv":
                    "bind dut my_assertions u_a (clk, rst);\n",
            })

    def test_audit_catches_missing_chart_state(self):
        with pytest.raises(uvm_seq.InvariantAuditError):
            uvm_seq._audit_all({
                "uvm/x/sos_uvm_seq_pkg.sv":
                    "package sos_uvm_seq_pkg;\n"
                    "  class sos_seq_item extends uvm_sequence_item;\n"
                    "    rand int event_id;\n"
                    "  endclass\n"
                    "endpackage\n",
            })

    def test_audit_permits_example_uvm_driver_demo(self):
        """The integration example deliberately illustrates the
        customer-side uvm_driver shape — audit MUST NOT flag it."""
        uvm_seq._audit_all({
            "uvm/x/sos_uvm_integration_example.sv":
                "class example_driver extends uvm_driver #(sos_seq_item);\n"
                "endclass\n",
        })

    def test_audit_passes_on_clean_emit(self):
        uvm_seq.render_target(_simple_chart(), {"chart_name": "demo"})


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_rejects_non_dict_chart_ir(self):
        with pytest.raises(uvm_seq.UnsupportedChartError):
            uvm_seq.render_target("not a dict", {"chart_name": "demo"})

    def test_default_chart_name(self):
        files = uvm_seq.render_target(_simple_chart(), None)
        assert any(k.startswith("uvm/chart/") for k in files)


# ---------------------------------------------------------------------------
# Parallel-chart acceptance (SOS-08-F is chart-agnostic)
# ---------------------------------------------------------------------------


class TestParallelChartAccepted:
    """SOS-08-F is chart-structure-agnostic — the vector IR is the same
    regardless of parallelism. The walker MUST accept parallel charts."""

    def test_accepts_parallel_chart(self):
        parallel = {
            "initial": "regions",
            "parallel": [{"id": "regions", "state": [{"id": "a"}]}],
        }
        files = uvm_seq.render_target(parallel, {"chart_name": "p"})
        # Audit passes, files emitted — same shape as single-region.
        assert len(files) == 3
