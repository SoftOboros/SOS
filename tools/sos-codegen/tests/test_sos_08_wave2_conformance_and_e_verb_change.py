"""SOS-08 wave-2 conformance audit + SOS-08-E `$display`→`$error`
verb-change normative-pin doc-assertions.

@spec  docs/concepts/SOS-08-WAVE2-CONFORMANCE.md
       (2026-05-25 wave-2 conformance audit; this test module verifies
       the doc's structural content)
@spec  docs/concepts/SOS-08-E-CONCEPTS.md §15 2026-05-25 post-wave-2
       follow-up: ``$display``→``$error`` verb-change normative pin.
@spec  docs/concepts/SOS-08-CONCEPTS.md §12 (umbrella acceptance gates)
@spec  docs/concepts/SOS-08-WAVE1-CONFORMANCE.md (wave-1 baseline —
       frozen; this wave-2 audit is the sibling)

This module verifies two doc deliverables landed for the 2026-05-25
audit window:

1. The wave-2 conformance audit doc
   (``docs/concepts/SOS-08-WAVE2-CONFORMANCE.md``) exists with the
   required structural sections and content commitments — the 11
   commits-since-wave-1 catalogued, gates (e) + (g) still ⏸, three
   new sub-phase PCDNs cited by ID.

2. The SOS-08-E §15 change log carries a dated ``2026-05-25`` entry
   pinning ``$error`` as the MUST-use system task in the walker-emitted
   default ``on_invariant_fail`` body, citing commit ``fa06f7a`` and
   IEEE 1800-2017 §20.10.3 as the simulator-severity rationale.

@invariants  INV-S-HDL-E-4 (chart-vocabulary failure messages — the
             format-string content is byte-identical across the
             verb-change; only severity tagging changes).
"""

from __future__ import annotations

from pathlib import Path

import pytest


# Repo-root resolution: this test file lives at
# tools/sos-codegen/tests/test_sos_08_wave2_conformance_and_e_verb_change.py
# → repo root is three parents up.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_WAVE2_AUDIT_PATH = (
    _REPO_ROOT / "docs" / "concepts" / "SOS-08-WAVE2-CONFORMANCE.md"
)
_E_CONCEPTS_PATH = (
    _REPO_ROOT / "docs" / "concepts" / "SOS-08-E-CONCEPTS.md"
)

# The eleven commits landed between wave-1 close (f0284fc, 2026-05-23)
# and the wave-2 audit (c2aa1cf, 2026-05-25). Truncated to seven-char
# prefixes — that's how the audit doc cites them.
_WAVE2_COMMIT_SHAS = [
    "e74a6e2",  # SOS08F2c
    "ffc27e8",  # SOS08G3cf2
    "9010510",  # SOS08E3f
    "7916145",  # SOS08D4r
    "fa06f7a",  # SOS08E3l (the $display→$error commit)
    "d879e7b",  # SOS08C3fa
    "945de92",  # SOS08D4c
    "5963e04",  # SOS08E3p
    "8467087",  # SOS08C3fx
    "1dc5649",  # SOS08D4ms
    "c2aa1cf",  # SOS08E3m
]


@pytest.fixture(scope="module")
def wave2_audit_text() -> str:
    """Read the wave-2 audit doc; fail if not found."""
    if not _WAVE2_AUDIT_PATH.exists():
        pytest.fail(
            f"SOS-08 wave-2 audit doc missing at {_WAVE2_AUDIT_PATH} — "
            "expected per the 2026-05-25 audit landing"
        )
    return _WAVE2_AUDIT_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def e_concepts_text() -> str:
    """Read the SOS-08-E concepts doc; fail if not found."""
    if not _E_CONCEPTS_PATH.exists():
        pytest.fail(
            f"SOS-08-E concepts doc missing at {_E_CONCEPTS_PATH}"
        )
    return _E_CONCEPTS_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------
# Group 1: wave-2 conformance audit doc — existence + structure
# ---------------------------------------------------------------


class TestWave2AuditExists:
    """The wave-2 audit doc exists at the expected sibling path
    next to ``SOS-08-WAVE1-CONFORMANCE.md``."""

    def test_audit_doc_file_present(self) -> None:
        assert _WAVE2_AUDIT_PATH.exists(), (
            f"SOS-08 wave-2 audit doc missing at {_WAVE2_AUDIT_PATH}"
        )

    def test_audit_doc_is_sibling_of_wave1(self) -> None:
        wave1_path = (
            _REPO_ROOT
            / "docs"
            / "concepts"
            / "SOS-08-WAVE1-CONFORMANCE.md"
        )
        assert wave1_path.exists(), (
            "wave-1 audit doc must exist as the audit-shape reference"
        )
        # Both docs live in the same directory — sibling layout.
        assert _WAVE2_AUDIT_PATH.parent == wave1_path.parent


class TestWave2AuditStructure:
    """Required sections per the dispatch's deliverable shape:
    §0 status banner, §2 scope, §3 per-gate audit, §5 carry-forward
    closures, §8 wave-3 candidate list, §10 change log."""

    def test_section_0_status_banner_present(
        self, wave2_audit_text: str
    ) -> None:
        # Section header. Accept either "## 0." or a "Status banner"
        # heading style.
        assert (
            "## 0. Status banner" in wave2_audit_text
            or "## 0 Status banner" in wave2_audit_text
        ), "§0 status banner section missing"

    def test_status_banner_names_wave2(
        self, wave2_audit_text: str
    ) -> None:
        # The banner must declare a wave-2 audit outcome.
        assert "wave-2" in wave2_audit_text.lower(), (
            "audit doc must mention wave-2 explicitly"
        )

    def test_section_2_scope_present(
        self, wave2_audit_text: str
    ) -> None:
        # §2 scope — catalogues the commits-since-wave-1.
        assert "## 2. Scope" in wave2_audit_text, (
            "§2 scope section missing"
        )

    def test_section_3_per_gate_audit_present(
        self, wave2_audit_text: str
    ) -> None:
        assert "## 3. Per-gate audit" in wave2_audit_text, (
            "§3 per-gate audit section missing"
        )

    def test_section_5_carry_forward_closures_present(
        self, wave2_audit_text: str
    ) -> None:
        assert "## 5. Carry-forward closures" in wave2_audit_text, (
            "§5 carry-forward closures section missing"
        )

    def test_section_8_wave3_candidate_list_present(
        self, wave2_audit_text: str
    ) -> None:
        assert "## 8. Wave-3 candidate list" in wave2_audit_text, (
            "§8 wave-3 candidate list missing"
        )

    def test_section_10_change_log_present(
        self, wave2_audit_text: str
    ) -> None:
        assert "## 10. Change log" in wave2_audit_text, (
            "§10 change log missing"
        )


class TestWave2AuditCommitCatalog:
    """§2 catalogues the eleven commits landed between wave-1 close
    and this audit. Dispatch requires at least 8 of 11 cited by
    seven-char SHA prefix."""

    def test_at_least_eight_of_eleven_commits_cited(
        self, wave2_audit_text: str
    ) -> None:
        cited = [
            sha
            for sha in _WAVE2_COMMIT_SHAS
            if sha in wave2_audit_text
        ]
        assert len(cited) >= 8, (
            f"§2 should cite at least 8 of {len(_WAVE2_COMMIT_SHAS)} "
            f"wave-2 commits by SHA prefix; got {len(cited)}: {cited}"
        )

    def test_fa06f7a_cited_as_verb_change_commit(
        self, wave2_audit_text: str
    ) -> None:
        # The $display→$error verb-change commit must be visible in
        # the wave-2 audit's commit catalog.
        assert "fa06f7a" in wave2_audit_text, (
            "verb-change commit fa06f7a must be cited in the wave-2 "
            "audit"
        )


class TestWave2AuditGateStatus:
    """Gates (e) and (g) MUST remain ⏸ — wave-2 does not authorize
    a bench session, so neither gate flips without one."""

    def test_gate_e_still_deferred(
        self, wave2_audit_text: str
    ) -> None:
        # Gate (e) — bench validation on Lattice ECP5. The audit
        # must clearly mark gate (e) as ⏸ (deferred / pending).
        gate_e_section_start = wave2_audit_text.find(
            "### Gate (e)"
        )
        assert gate_e_section_start >= 0, (
            "§3 must carry a 'Gate (e)' subsection"
        )
        # Read until the next ### or ## heading.
        rest = wave2_audit_text[gate_e_section_start:]
        next_header = rest.find("\n### ", 1)
        if next_header < 0:
            next_header = rest.find("\n## ", 1)
        gate_e_block = (
            rest[:next_header] if next_header > 0 else rest
        )
        # Must explicitly state ⏸ or "unchanged" deferred status.
        assert "⏸" in gate_e_block, (
            "gate (e) must remain ⏸ in wave-2 audit; flipping it "
            "requires a bench session that has not landed"
        )

    def test_gate_g_still_half_deferred(
        self, wave2_audit_text: str
    ) -> None:
        # Gate (g) — SOS-06 §15 amendment. Paper landed in wave-1;
        # numerical readings still ⏸ (co-gated on gate (e)).
        gate_g_section_start = wave2_audit_text.find(
            "### Gate (g)"
        )
        assert gate_g_section_start >= 0, (
            "§3 must carry a 'Gate (g)' subsection"
        )
        rest = wave2_audit_text[gate_g_section_start:]
        next_header = rest.find("\n### ", 1)
        if next_header < 0:
            next_header = rest.find("\n## ", 1)
        gate_g_block = (
            rest[:next_header] if next_header > 0 else rest
        )
        # ⏸ must still appear in the gate (g) block (numbers are
        # still pending).
        assert "⏸" in gate_g_block, (
            "gate (g) must still carry a ⏸ marker for numbers; "
            "paper translation landed in wave-1 but numerical "
            "readings remain co-gated on gate (e)"
        )


class TestWave2AuditPCDNs:
    """§6 cites the three new sub-phase PCDNs filed during wave-2
    review by ID."""

    @pytest.mark.parametrize(
        "pcdn_id",
        [
            "PCDN-SOS-08-D-008",
            "PCDN-SOS-08-C-007",
            "PCDN-SOS-08-C-008",
        ],
    )
    def test_new_pcdn_cited_by_id(
        self, wave2_audit_text: str, pcdn_id: str
    ) -> None:
        assert pcdn_id in wave2_audit_text, (
            f"§6 must cite {pcdn_id} by ID — wave-2 review surfaced "
            "three new sub-phase PCDNs"
        )


# ---------------------------------------------------------------
# Group 2: SOS-08-E §15 verb-change normative pin
# ---------------------------------------------------------------


class TestVerbChangeAmendmentExists:
    """The SOS-08-E §15 change log carries a dated 2026-05-25 entry
    pinning the verb-change normatively."""

    def test_dated_entry_present(
        self, e_concepts_text: str
    ) -> None:
        # The 2026-05-25 dated heading must appear in §15.
        assert "### 2026-05-25" in e_concepts_text, (
            "SOS-08-E §15 must carry a dated 2026-05-25 entry for "
            "the verb-change normative pin"
        )

    def test_entry_names_display_to_error_shift(
        self, e_concepts_text: str
    ) -> None:
        # The entry must clearly name BOTH verbs and the direction
        # of the shift.
        # We accept either `$display`→`$error` (with backticks +
        # arrow) or "$display" ... "$error" in close proximity.
        entry_start = e_concepts_text.find("### 2026-05-25")
        assert entry_start >= 0
        # Slice to the end of the file or the next === / --- block.
        entry_block = e_concepts_text[entry_start:]
        assert "$display" in entry_block, (
            "verb-change entry must name `$display` (the old verb)"
        )
        assert "$error" in entry_block, (
            "verb-change entry must name `$error` (the new verb)"
        )


class TestVerbChangeAmendmentContent:
    """Normative content commitments per the dispatch:
    - Must name `$error` as the MUST-use system task.
    - Must cite commit ``fa06f7a``.
    - Must cite IEEE 1800-2017 §20.10.3 as the severity rationale.
    """

    def test_error_named_as_must_use(
        self, e_concepts_text: str
    ) -> None:
        # The amendment must explicitly carry an RFC-2119 MUST that
        # names `$error` as the required walker-emitted verb.
        entry_start = e_concepts_text.find("### 2026-05-25")
        assert entry_start >= 0
        entry_block = e_concepts_text[entry_start:]
        # Must use the RFC-2119 keyword MUST in the same vicinity
        # as `$error` for the rule to be normative.
        assert "MUST use `$error`" in entry_block or (
            "MUST" in entry_block and "`$error`" in entry_block
        ), (
            "amendment must declare `$error` as the MUST-use "
            "system task in the walker-emitted default body"
        )

    def test_cites_fa06f7a(self, e_concepts_text: str) -> None:
        entry_start = e_concepts_text.find("### 2026-05-25")
        assert entry_start >= 0
        entry_block = e_concepts_text[entry_start:]
        assert "fa06f7a" in entry_block, (
            "amendment must cite the resolving commit fa06f7a"
        )

    def test_cites_ieee_1800_2017_severity_section(
        self, e_concepts_text: str
    ) -> None:
        # The rationale must cite IEEE 1800-2017 §20.10.3 (the
        # simulator-severity reference for $error).
        entry_start = e_concepts_text.find("### 2026-05-25")
        assert entry_start >= 0
        entry_block = e_concepts_text[entry_start:]
        # Accept either "§20.10.3" or "20.10.3" with "IEEE 1800".
        assert "IEEE 1800-2017" in entry_block, (
            "amendment must cite IEEE 1800-2017 as the simulator-"
            "severity rationale"
        )
        assert "20.10.3" in entry_block, (
            "amendment must cite §20.10.3 of IEEE 1800-2017 (the "
            "system-severity-task subsection) as the rationale "
            "for promoting `$display` to `$error`"
        )
