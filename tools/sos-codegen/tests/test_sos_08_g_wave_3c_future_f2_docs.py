"""SOS-08-G wave-3c-future (f.2) host-wiring doc assertions.

@spec  docs/concepts/SOS-08-G-CONCEPTS.md §6 (viewer integration
       contract — (f) vector-citation drill-down)
@spec  docs/concepts/SOS-08-G-CONCEPTS.md §15 wave-3c-future-f2
       (2026-05-24): host-wiring spec landed at
       ``docs/ops/SOS-08-G-host-wiring.md``.

This module verifies the wave-3c-future (f.2) doc deliverables landed
intact: the host-wiring runbook is present at the expected path with
the required section headings, names the canonical viewer-side
sources, and cites the spec-frozen contract surfaces (``EDITOR`` env
var for GTKWave; ``OpenVectorSource`` command for Surfer;
``vector_index + 2`` line-hint convention). It also asserts the §15
amendment in ``SOS-08-G-CONCEPTS.md`` carries the dated entry per the
spec-before-code discipline.

@invariants  INV-S-HDL-G-1 through G-6 (preserved by doc-only entry)
@invariants  INV-SOS-H (chart vocabulary survives into editor link)
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Repo-root resolution: this test file lives at
# tools/sos-codegen/tests/test_sos_08_g_wave_3c_future_f2_docs.py
# → repo root is three parents up.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_HOST_WIRING_PATH = _REPO_ROOT / "docs" / "ops" / "SOS-08-G-host-wiring.md"
_CONCEPTS_PATH = _REPO_ROOT / "docs" / "concepts" / "SOS-08-G-CONCEPTS.md"


@pytest.fixture(scope="module")
def host_wiring_text() -> str:
    """Read the host-wiring doc; skip if not found (gives a friendly
    failure mode under partial worktree checkouts)."""
    if not _HOST_WIRING_PATH.exists():
        pytest.fail(
            f"SOS-08-G host-wiring doc missing at {_HOST_WIRING_PATH} — "
            "wave-3c-future (f.2) deliverable not present"
        )
    return _HOST_WIRING_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def concepts_text() -> str:
    if not _CONCEPTS_PATH.exists():
        pytest.fail(f"SOS-08-G concepts doc missing at {_CONCEPTS_PATH}")
    return _CONCEPTS_PATH.read_text(encoding="utf-8")


class TestHostWiringDocPresence:
    """The host-wiring doc exists at the expected path."""

    def test_host_wiring_doc_exists(self) -> None:
        assert _HOST_WIRING_PATH.exists(), (
            f"host-wiring runbook MUST exist at "
            f"docs/ops/SOS-08-G-host-wiring.md (got: {_HOST_WIRING_PATH})"
        )

    def test_host_wiring_doc_is_nonempty(self, host_wiring_text: str) -> None:
        assert len(host_wiring_text) > 1000, (
            "host-wiring doc MUST carry substantive content "
            "(host contract, failure-mode matrix, security guidance) — "
            f"got {len(host_wiring_text)} bytes"
        )


class TestHostWiringSectionHeadings:
    """Required section headings per the wave-3c-future (f.2) spec."""

    def test_purpose_section_present(self, host_wiring_text: str) -> None:
        # Allow either "## 1. Purpose" or "# Purpose" — section heading
        # identification is by name, not strict numbering.
        assert "Purpose" in host_wiring_text, (
            "host-wiring doc MUST carry a Purpose section "
            "(host contract overview)"
        )

    def test_gtkwave_tcl_section_present(self, host_wiring_text: str) -> None:
        assert "GTKWave" in host_wiring_text and "Tcl" in host_wiring_text, (
            "host-wiring doc MUST carry a GTKWave Tcl host-wiring section"
        )

    def test_surfer_wasm_section_present(self, host_wiring_text: str) -> None:
        assert "Surfer" in host_wiring_text and (
            "WASM" in host_wiring_text or "wasm" in host_wiring_text
        ), "host-wiring doc MUST carry a Surfer WASM host-wiring section"

    def test_line_hint_section_present(self, host_wiring_text: str) -> None:
        # Section title carries "Line-hint" (the §4 anchor in the doc).
        assert "Line-hint" in host_wiring_text, (
            "host-wiring doc MUST carry a Line-hint convention section"
        )

    def test_failure_modes_section_present(self, host_wiring_text: str) -> None:
        assert "Failure mode" in host_wiring_text, (
            "host-wiring doc MUST carry a Failure modes section "
            "(editor unavailable, missing path, out-of-range)"
        )

    def test_security_section_present(self, host_wiring_text: str) -> None:
        assert "Security" in host_wiring_text, (
            "host-wiring doc MUST carry a Security section "
            "(workspace-root validation, argv-not-shell-string)"
        )


class TestHostWiringContractMentions:
    """Required contract-surface terms per the (f.2) spec deliverables."""

    def test_editor_env_var_mentioned(self, host_wiring_text: str) -> None:
        # The GTKWave path's editor invocation contract reads
        # `$env(EDITOR)` (Tcl) / `std::env::var("EDITOR")` (Rust).
        assert "EDITOR" in host_wiring_text, (
            "host-wiring doc MUST name the `EDITOR` env var contract "
            "(GTKWave Tcl path; Surfer host-handler reference sketch)"
        )

    def test_open_vector_source_command_mentioned(
        self, host_wiring_text: str
    ) -> None:
        # Surfer side: the plugin's `SurferCommand::OpenVectorSource`
        # variant is the command shape the host handler MUST register
        # against.
        assert "OpenVectorSource" in host_wiring_text, (
            "host-wiring doc MUST name the `OpenVectorSource` Surfer "
            "command (the host handler contract surface)"
        )

    def test_line_hint_convention_named(self, host_wiring_text: str) -> None:
        # `line = vector_index + 2` is the cross-viewer offset
        # convention; both viewer paths translate the same way.
        assert "vector_index + 2" in host_wiring_text, (
            "host-wiring doc MUST name the `vector_index + 2` "
            "line-hint convention (per §4)"
        )


class TestHostWiringSourceCitations:
    """The doc cites both viewer-side canonical sources by path."""

    def test_cites_gtkwave_tcl_source(self, host_wiring_text: str) -> None:
        # Path may appear with absolute / relative prefixes; assert the
        # leaf path fragment.
        assert "sos_overlay.tcl" in host_wiring_text, (
            "host-wiring doc MUST cite the GTKWave Tcl plugin source "
            "(tools/sos-codegen/viewers/gtkwave/sos_overlay.tcl)"
        )
        # Stronger: the full repo-relative path SHOULD appear at least
        # once so a reader can navigate without ambiguity.
        assert (
            "tools/sos-codegen/viewers/gtkwave/sos_overlay.tcl"
            in host_wiring_text
        ), (
            "host-wiring doc SHOULD cite the GTKWave plugin via its "
            "full repo-relative path"
        )

    def test_cites_surfer_rust_source(self, host_wiring_text: str) -> None:
        assert "lib.rs" in host_wiring_text, (
            "host-wiring doc MUST cite the Surfer plugin Rust source "
            "(tools/sos-codegen/viewers/surfer/sos-surfer-plugin/src/lib.rs)"
        )
        assert (
            "tools/sos-codegen/viewers/surfer/sos-surfer-plugin/src/lib.rs"
            in host_wiring_text
        ), (
            "host-wiring doc SHOULD cite the Surfer plugin via its "
            "full repo-relative path"
        )


class TestHostWiringFailureAndSecurityNormatives:
    """The MUST/SHOULD failure-mode + security disciplines are named."""

    def test_non_blocking_event_loop_named(
        self, host_wiring_text: str
    ) -> None:
        # Hard invariant: the viewer event loop MUST NOT block.
        assert "MUST NOT block" in host_wiring_text or (
            "non-blocking" in host_wiring_text
            or "Non-blocking" in host_wiring_text
        ), (
            "host-wiring doc MUST state the non-blocking event-loop "
            "discipline as a normative requirement"
        )

    def test_no_wave_file_mutation_named(self, host_wiring_text: str) -> None:
        assert "MUST NOT" in host_wiring_text and (
            "wave file" in host_wiring_text or "mutate" in host_wiring_text
        ), (
            "host-wiring doc MUST state the read-only-WRT-wave-file "
            "discipline"
        )

    def test_workspace_root_validation_named(
        self, host_wiring_text: str
    ) -> None:
        # Security MUST/SHOULD: validate paths inside workspace root.
        assert "workspace root" in host_wiring_text, (
            "host-wiring doc Security section MUST name workspace-root "
            "path validation"
        )

    def test_no_shell_string_concatenation_named(
        self, host_wiring_text: str
    ) -> None:
        # The argv-not-shell-string discipline is load-bearing for the
        # security claim.
        assert (
            "argv" in host_wiring_text
            or "shell" in host_wiring_text
        ), (
            "host-wiring doc Security section MUST name the "
            "argv-not-shell-string-concatenation discipline"
        )


class TestConceptsSection15Amendment:
    """SOS-08-G-CONCEPTS.md §15 carries the wave-3c-future-f2
    2026-05-24 dated entry per spec-before-code discipline."""

    def test_section_15_entry_dated_2026_05_24(
        self, concepts_text: str
    ) -> None:
        # The new dated entry header per the methodology:
        # `### 2026-05-24 — Impl wave-3c-future-f2: §6 (f.2) host-wiring spec ...`
        assert "2026-05-24" in concepts_text, (
            "SOS-08-G-CONCEPTS.md §15 MUST carry a 2026-05-24 dated entry"
        )
        # Stronger: the specific wave-3c-future-f2 marker must appear so
        # this entry is distinguishable from the prior 2026-05-24
        # wave-3c-future (f.1) entry.
        assert "wave-3c-future-f2" in concepts_text or (
            "(f.2)" in concepts_text and "host-wiring" in concepts_text
        ), (
            "SOS-08-G-CONCEPTS.md §15 MUST carry the wave-3c-future-f2 "
            "amendment naming the host-wiring spec deliverable"
        )

    def test_section_15_cites_host_wiring_doc(
        self, concepts_text: str
    ) -> None:
        assert "SOS-08-G-host-wiring.md" in concepts_text, (
            "SOS-08-G-CONCEPTS.md §15 amendment MUST cite the "
            "host-wiring doc at docs/ops/SOS-08-G-host-wiring.md"
        )

    def test_section_15_acknowledges_upstream_gating(
        self, concepts_text: str
    ) -> None:
        # The amendment must be explicit that host implementation is
        # upstream-gated (not part of this carry-forward).
        # Match either the broader "upstream" wording or the specific
        # "Surfer plugin-host" / "GTKWave keyaction" upstream blockers.
        assert "upstream" in concepts_text, (
            "SOS-08-G-CONCEPTS.md §15 wave-3c-future-f2 entry MUST "
            "acknowledge upstream-API gating of the host implementation"
        )

    def test_section_15_names_what_closes_and_what_stays_open(
        self, concepts_text: str
    ) -> None:
        # The amendment lists what (f.2) closes vs what stays open per
        # the task spec; assert both halves are present.
        assert "closes" in concepts_text.lower() or (
            "closed" in concepts_text.lower()
        ), (
            "§15 wave-3c-future-f2 entry MUST name what (f.2) closes "
            "(the spec / host-wiring contract)"
        )
        assert "open" in concepts_text.lower(), (
            "§15 wave-3c-future-f2 entry MUST name what stays open "
            "(host implementation upstream-gated)"
        )
