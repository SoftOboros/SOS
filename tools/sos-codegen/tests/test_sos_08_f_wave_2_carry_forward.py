# SPDX-License-Identifier: MIT
"""Structural tests for the SOS-08-F wave-2 carry-forward — UVM 2.0
cross-runtime CI smoke (SOS08F2c).

These tests pin the SOS08F2c carry-forward surface authored on
2026-05-24 per the §15 amendment of ``docs/concepts/SOS-08-F-CONCEPTS.md``.
All checks are static structural assertions — no simulator is invoked
and no UVM runtime is exercised. The CI smoke itself is a build-only /
parse-only screen per the README's declared-scope section.

Per the SOS-08-F-CONCEPTS.md INV-S-HDL-F-5 amendment, the UVM 1.2
grammar must remain forward-compatible with IEEE 1800.2-2017 (UVM 2.0).
This module asserts:

* ``examples/uvm_integration/Makefile`` carries a ``UVM_VERSION``
  variable defaulting to ``1.2`` (regression guard against accidentally
  flipping the default away from the INV-S-HDL-F-5 primary target).
* ``Makefile`` carries ``sim-golden-uvm2`` and ``sim-violation-uvm2``
  recursive-make targets that flip ``UVM_VERSION=2.0`` for the
  invocation.
* The UVM-1.2 targets ``sim-golden`` and ``sim-violation`` still exist
  (regression guard — the carry-forward MUST NOT delete the primary
  flow).
* ``examples/uvm_integration/README.md`` documents the build-only-smoke
  scope explicitly.
* ``.github/workflows/sos-uvm-smoke.yml`` exists, runs on PR + push to
  ``webslinger``, and includes both the Verilator lint step and the
  Python pytest step.
* The canonical ``[SOS-SEQ]`` scoreboard line shape (defined in
  ``tb/sos_kernel_scoreboard.sv``) is the same scaffold under both UVM
  versions — i.e. it is sourced from a single file (no per-version
  branch), preserving INV-S-HDL-F-3 chart-vocabulary traceability
  across UVM 1.2 and UVM 2.0.
"""

from __future__ import annotations

import pathlib
import re

import pytest


# ---------------------------------------------------------------------------
# Repo-root resolution. The test file lives at
#   tools/sos-codegen/tests/test_sos_08_f_wave_2_carry_forward.py
# so the repo root is three levels up.
# ---------------------------------------------------------------------------


REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
EXAMPLE_ROOT = REPO_ROOT / "examples" / "uvm_integration"
MAKEFILE = EXAMPLE_ROOT / "Makefile"
README = EXAMPLE_ROOT / "README.md"
SCOREBOARD = EXAMPLE_ROOT / "tb" / "sos_kernel_scoreboard.sv"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "sos-uvm-smoke.yml"
CONCEPTS_DOC = REPO_ROOT / "docs" / "concepts" / "SOS-08-F-CONCEPTS.md"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read(path: pathlib.Path) -> str:
    assert path.exists(), f"missing expected file: {path}"
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Makefile — UVM_VERSION variable + uvm2 targets
# ---------------------------------------------------------------------------


class TestCarryForwardMakefileUvmVersion:
    """Makefile carries a UVM_VERSION variable defaulting to 1.2."""

    def test_makefile_exists(self):
        assert MAKEFILE.exists(), f"expected {MAKEFILE} (wave-2 example Makefile)"

    def test_uvm_version_variable_declared(self):
        text = _read(MAKEFILE)
        # Conditional assignment, allowing whitespace variation:
        #     UVM_VERSION ?= 1.2
        pattern = re.compile(r"^\s*UVM_VERSION\s*\?=\s*([0-9.]+)", re.MULTILINE)
        m = pattern.search(text)
        assert m is not None, (
            "Makefile must declare `UVM_VERSION ?= <version>` per "
            "SOS-08-F §15 wave-2 carry-forward (SOS08F2c)."
        )

    def test_uvm_version_default_is_1_2(self):
        """Regression guard: do NOT flip the default away from 1.2.

        INV-S-HDL-F-5 designates UVM 1.2 as the primary target with
        UVM 2.0 as forward-compatibility; flipping the default would
        silently change the customer-facing build surface.
        """
        text = _read(MAKEFILE)
        pattern = re.compile(r"^\s*UVM_VERSION\s*\?=\s*([0-9.]+)", re.MULTILINE)
        m = pattern.search(text)
        assert m is not None, "UVM_VERSION declaration missing"
        assert m.group(1) == "1.2", (
            f"UVM_VERSION default must remain `1.2` per INV-S-HDL-F-5 "
            f"(found `{m.group(1)}`)"
        )


class TestCarryForwardMakefileUvm2Targets:
    """Makefile carries the sim-*-uvm2 targets."""

    def test_sim_golden_uvm2_target_exists(self):
        text = _read(MAKEFILE)
        # Target declaration: `sim-golden-uvm2:` at start of a line.
        assert re.search(r"^sim-golden-uvm2\s*:", text, re.MULTILINE), (
            "Makefile must declare `sim-golden-uvm2:` target per SOS08F2c."
        )

    def test_sim_violation_uvm2_target_exists(self):
        text = _read(MAKEFILE)
        assert re.search(r"^sim-violation-uvm2\s*:", text, re.MULTILINE), (
            "Makefile must declare `sim-violation-uvm2:` target per SOS08F2c."
        )

    def test_uvm2_targets_set_uvm_version_2_0(self):
        """The `sim-*-uvm2` recipes must override UVM_VERSION=2.0.

        Recursive-make pattern is the carry-forward's chosen mechanism;
        an inline `VECTOR :=` style would not propagate to the per-SIM
        ifeq blocks that depend on `UVM_VERSION`.
        """
        text = _read(MAKEFILE)
        # Search for the body lines following the sim-*-uvm2 targets.
        # Accept either:
        #     $(MAKE) UVM_VERSION=2.0 sim-golden
        # or a UVM_VERSION-flipping override in any shape.
        for tgt in ("sim-golden-uvm2", "sim-violation-uvm2"):
            # Capture body up to next blank line or next target.
            body_pat = re.compile(
                rf"^{re.escape(tgt)}\s*:.*?(?=^\S|\Z)",
                re.MULTILINE | re.DOTALL,
            )
            m = body_pat.search(text)
            assert m is not None, f"target body for {tgt} not found"
            body = m.group(0)
            assert "UVM_VERSION=2.0" in body or "UVM_VERSION = 2.0" in body, (
                f"{tgt} body must set UVM_VERSION=2.0 (body was:\n{body})"
            )

    def test_uvm_1_2_targets_still_exist(self):
        """Regression guard: the primary UVM-1.2 targets MUST still exist.

        The carry-forward adds new variants; it does NOT remove the
        UVM-1.2 flow per the spec's primary-target framing.
        """
        text = _read(MAKEFILE)
        assert re.search(r"^sim-golden\s*:", text, re.MULTILINE), (
            "Primary `sim-golden:` target deleted — SOS08F2c MUST preserve "
            "the UVM-1.2 flow."
        )
        assert re.search(r"^sim-violation\s*:", text, re.MULTILINE), (
            "Primary `sim-violation:` target deleted — SOS08F2c MUST "
            "preserve the UVM-1.2 flow."
        )

    def test_phony_includes_uvm2_targets(self):
        """The .PHONY list should mention the new uvm2 targets so
        `make sim-golden-uvm2` doesn't trip the disk-file check."""
        text = _read(MAKEFILE)
        phony_match = re.search(r"^\.PHONY:\s*(.+)$", text, re.MULTILINE)
        assert phony_match is not None, "Makefile missing .PHONY declaration"
        phony_targets = phony_match.group(1).split()
        for tgt in ("sim-golden-uvm2", "sim-violation-uvm2"):
            assert tgt in phony_targets, (
                f"{tgt} missing from .PHONY (would treat target as file)"
            )


# ---------------------------------------------------------------------------
# README — declared-scope documentation
# ---------------------------------------------------------------------------


class TestCarryForwardReadme:
    """README documents the build-only-smoke scope explicitly."""

    def test_readme_exists(self):
        assert README.exists(), f"expected {README}"

    def test_readme_names_uvm_2_0_smoke_section(self):
        text = _read(README)
        # Section heading explicitly naming the smoke.
        assert re.search(r"UVM\s*2\.0\s+cross[- ]runtime\s+smoke", text, re.IGNORECASE), (
            "README must carry a section naming the 'UVM 2.0 cross-runtime "
            "smoke' carry-forward."
        )

    def test_readme_declares_build_only_scope(self):
        """The scope discipline ('build/parse only, NOT simulator-run')
        MUST be in plain prose so a reviewer reading the README does not
        infer that CI green means a UVM runtime executed."""
        text = _read(README)
        # Accept variants of the build-only / parse-only framing.
        markers = (
            "build-only",
            "build only",
            "parse-only",
            "parse only",
        )
        assert any(marker in text.lower() for marker in markers), (
            "README must describe the smoke as build-only / parse-only "
            "(found neither phrase)."
        )

    def test_readme_states_no_vendor_simulator_in_ci(self):
        text = _read(README)
        # Some form of "no vendor simulator in CI" disclaimer.
        lowered = text.lower()
        assert "vendor simulator" in lowered or "no simulator" in lowered or "licensed simulator" in lowered, (
            "README must state that vendor simulators are not invoked in CI "
            "(INV-S-HDL-F-2 customer-owned constraint)."
        )

    def test_readme_cites_sos_seq_line_shape(self):
        """The canonical `[SOS-SEQ]` scoreboard line must be cited in
        the README's UVM 2.0 section so cross-version chart-vocab
        preservation per INV-S-HDL-F-3 is reader-visible."""
        text = _read(README)
        assert "[SOS-SEQ]" in text, (
            "README must cite the canonical `[SOS-SEQ]` scoreboard line "
            "shape (chart-vocab traceability per INV-S-HDL-F-3)."
        )
        # Each chart-vocab field name should appear next to it.
        for field in ("state=", "transition=", "invariant=", "family=", "event="):
            assert field in text, (
                f"README's [SOS-SEQ] citation must include `{field}` field"
            )


# ---------------------------------------------------------------------------
# GitHub Actions workflow — file existence + triggers + steps
# ---------------------------------------------------------------------------


class TestCarryForwardWorkflow:
    """`.github/workflows/sos-uvm-smoke.yml` exists with expected triggers + steps."""

    def test_workflow_file_exists(self):
        assert WORKFLOW.exists(), f"expected {WORKFLOW}"

    def test_workflow_has_pr_and_push_triggers(self):
        text = _read(WORKFLOW)
        # YAML structure: top-level `on:` with `push:` + `pull_request:`.
        assert re.search(r"^on:\s*$", text, re.MULTILINE), (
            "workflow must declare top-level `on:` trigger block"
        )
        assert re.search(r"^\s+push:", text, re.MULTILINE), (
            "workflow must trigger on push"
        )
        assert re.search(r"^\s+pull_request:", text, re.MULTILINE), (
            "workflow must trigger on pull_request"
        )

    def test_workflow_push_branches_includes_webslinger(self):
        text = _read(WORKFLOW)
        # Push block carries `branches: [webslinger]` (per parent's
        # webslinger integration branch convention).
        push_block = re.search(
            r"^\s+push:.*?(?=^\s+pull_request:|\Z)", text,
            re.MULTILINE | re.DOTALL,
        )
        assert push_block is not None, "push trigger block not found"
        assert "webslinger" in push_block.group(0), (
            "workflow push trigger must include `webslinger` branch"
        )

    def test_workflow_has_lint_job(self):
        text = _read(WORKFLOW)
        # Job named `lint` (verilator parse-only).
        assert re.search(r"^\s+lint:", text, re.MULTILINE), (
            "workflow must declare a `lint:` job (verilator parse-only)"
        )

    def test_workflow_has_python_tests_job(self):
        text = _read(WORKFLOW)
        assert re.search(r"^\s+python-tests:", text, re.MULTILINE), (
            "workflow must declare a `python-tests:` job"
        )

    def test_workflow_installs_verilator(self):
        text = _read(WORKFLOW)
        assert "verilator" in text.lower(), (
            "workflow must install/run verilator for the parse step"
        )

    def test_workflow_runs_pytest(self):
        text = _read(WORKFLOW)
        assert "pytest" in text, "workflow must run pytest for the python-tests job"

    def test_workflow_sets_up_python_3_11(self):
        text = _read(WORKFLOW)
        # Both jobs should set up Python 3.11.
        assert "python-version: '3.11'" in text or 'python-version: "3.11"' in text, (
            "workflow must set up Python 3.11"
        )

    def test_workflow_does_not_run_vendor_simulator(self):
        """Scope discipline — no `vsim`/`vcs`/`xrun` invocation in CI.

        The smoke is explicitly build-only; a future commit silently
        adding a vendor-simulator step would invalidate the spec
        statement and the README's declared scope.
        """
        text = _read(WORKFLOW).lower()
        # The make targets reference these as recipe shapes — guard
        # against actual CI run lines.
        forbidden_run_patterns = (
            "run: vsim",
            "run: vcs",
            "run: xrun",
            "run: make sim-golden",
            "run: make sim-violation",
        )
        for pat in forbidden_run_patterns:
            assert pat not in text, (
                f"workflow must not invoke vendor simulator in CI "
                f"(found `{pat}`)"
            )


# ---------------------------------------------------------------------------
# Cross-version `[SOS-SEQ]` scaffold — single-source-of-truth check
# ---------------------------------------------------------------------------


class TestSosSeqLineCrossVersion:
    """The `[SOS-SEQ]` line scaffold is sourced from a single scoreboard
    file shared across UVM 1.2 and UVM 2.0 build flows.

    Per INV-S-HDL-F-3, the chart-vocabulary traceability survives the
    UVM boundary. Because the scoreboard source is the SAME file under
    both `sim-golden` (UVM 1.2) and `sim-golden-uvm2` (UVM 2.0) build
    flows, the `[SOS-SEQ]` line shape is identical across versions by
    construction.
    """

    def test_scoreboard_file_exists(self):
        assert SCOREBOARD.exists(), f"expected {SCOREBOARD}"

    def test_scoreboard_emits_sos_seq_line(self):
        text = _read(SCOREBOARD)
        assert "[SOS-SEQ]" in text, (
            "scoreboard must emit the canonical `[SOS-SEQ]` chart-vocab "
            "failure line per §6.6 / INV-S-HDL-F-3"
        )

    def test_scoreboard_carries_all_chart_vocab_fields(self):
        """All five chart-vocab fields (state, transition, invariant,
        family, event) must appear in the scoreboard's `[SOS-SEQ]`
        format strings — the load-bearing INV-S-HDL-F-3 evidence."""
        text = _read(SCOREBOARD)
        for field in ("state=%s", "transition=%0d", "invariant=%0d", "family=%s", "event=%0d"):
            assert field in text, (
                f"scoreboard `[SOS-SEQ]` line must format `{field}` per §6.6"
            )

    def test_scoreboard_is_single_source_for_both_uvm_versions(self):
        """The Makefile's UVM-1.2 and UVM-2.0 targets both reference the
        same `sos_kernel_scoreboard.sv` via `SV_SOURCES` — no per-version
        scoreboard variant exists.

        Verified structurally: the SV_SOURCES list contains exactly one
        scoreboard entry, and there is no `*_uvm2.sv` companion file.
        """
        mk_text = _read(MAKEFILE)
        # SV_SOURCES list mentions the scoreboard once.
        sb_refs = mk_text.count("sos_kernel_scoreboard.sv")
        assert sb_refs == 1, (
            f"expected exactly 1 reference to `sos_kernel_scoreboard.sv` "
            f"in Makefile SV_SOURCES (found {sb_refs}); a per-UVM-version "
            f"scoreboard variant would split INV-S-HDL-F-3 evidence."
        )
        # No companion uvm2-specific scoreboard.
        companion = SCOREBOARD.with_name("sos_kernel_scoreboard_uvm2.sv")
        assert not companion.exists(), (
            "per-UVM-version scoreboard variants are not permitted — "
            "INV-S-HDL-F-3 requires a single chart-vocab rendering source."
        )

    def test_concepts_doc_cites_carry_forward(self):
        """The §15 amendment for SOS08F2c must cite this carry-forward."""
        text = _read(CONCEPTS_DOC)
        # The amendment entry should mention the UVM 2.0 cross-runtime
        # smoke landing.
        assert re.search(
            r"SOS08F2c", text,
        ) or re.search(
            r"UVM\s*2\.0\s+cross[- ]runtime\s+(?:CI\s+)?smoke", text, re.IGNORECASE,
        ), (
            "SOS-08-F-CONCEPTS.md §15 must carry the SOS08F2c "
            "carry-forward entry (UVM 2.0 cross-runtime CI smoke)."
        )
