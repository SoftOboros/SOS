"""SOS-08 wave-3 conformance audit doc-assertion module.

@spec  docs/concepts/SOS-08-WAVE3-CONFORMANCE.md
       (2026-05-25 wave-3 conformance audit; this test module verifies
       the doc's structural content)
@spec  docs/concepts/SOS-08-CONCEPTS.md §12 (umbrella acceptance gates)
@spec  docs/concepts/SOS-08-WAVE1-CONFORMANCE.md (wave-1 baseline)
@spec  docs/concepts/SOS-08-WAVE2-CONFORMANCE.md (wave-2 baseline)
@spec  docs/concepts/SOS-09-CONCEPTS.md §16 (PCDN-SOS-09-001 amendment)

This module verifies the wave-3 conformance audit doc landed for the
2026-05-25 wave-3 close (`webslinger` SHA ``fb621ed``):

1. The wave-3 audit doc exists at the expected sibling path next to
   ``SOS-08-WAVE1-CONFORMANCE.md`` and ``SOS-08-WAVE2-CONFORMANCE.md``.

2. The doc structure matches the dispatch deliverable shape:
   §0 status banner, §2 scope, §3 per-gate audit, §5 carry-forward
   closures, §6 PCDNs, §7 test count migration, §8 wave-4 candidate
   list, §9 authority-boundary updates, §10 change log.

3. §2 catalogues at least 12 of the 14 commits between wave-2 close
   (``c2aa1cf``) and wave-3 close (``fb621ed``) by seven-char SHA
   prefix (dispatch asked for ≥12 of 15; actual range carries 14
   commits, see audit-doc §10).

4. §3 gates (e) and (g) still ⏸ — bench validation has not landed.

5. §5 carry-forward closures table lists every closed wave-future
   item, including the wave-7 cleanup contributions to C, D, E.

6. §6 cites PCDN-SOS-08-D-008, PCDN-SOS-08-C-007, PCDN-SOS-08-C-008
   and the PCDN-SOS-09-001 amendment by ID.

7. §7 names the 1258-test cumulative pass count for the wave-3 close.

8. §8 lists the SOS-09 sub-phase concept docs as the next gating
   items for wave-4.

@invariants  Informative audit; preserves the invariants cited in
             each sub-phase's §15 by reference only. No new normative
             content authored by this test module.
"""

from __future__ import annotations

from pathlib import Path

import pytest


# Repo-root resolution: this test file lives at
# tools/sos-codegen/tests/test_sos_08_wave3_conformance.py
# → repo root is three parents up.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_WAVE3_AUDIT_PATH = (
    _REPO_ROOT / "docs" / "concepts" / "SOS-08-WAVE3-CONFORMANCE.md"
)
_WAVE2_AUDIT_PATH = (
    _REPO_ROOT / "docs" / "concepts" / "SOS-08-WAVE2-CONFORMANCE.md"
)
_WAVE1_AUDIT_PATH = (
    _REPO_ROOT / "docs" / "concepts" / "SOS-08-WAVE1-CONFORMANCE.md"
)

# The fourteen commits landed between wave-2 close (c2aa1cf,
# 2026-05-25) and the wave-3 audit (fb621ed, 2026-05-25). Truncated
# to seven-char prefixes — that's how the audit doc cites them.
_WAVE3_COMMIT_SHAS = [
    "cb3001c",  # SOS08D008 — file PCDN-SOS-08-D-008
    "83c9aba",  # SOS08D4cf — compound traversal-order alphabetic
    "82a49af",  # SOS08W2 — wave-2 audit + E verb pin
    "a396c67",  # SOS08C78b — file PCDN-SOS-08-C-007 + C-008
    "5d25063",  # SOS08D008R — ratify PCDN-SOS-08-D-008
    "e6f84f5",  # SOS08C78R — ratify PCDN-SOS-08-C-007 + C-008
    "b193cf0",  # SOS08ED008X — E §15 cross-ref of D-008
    "93de5f5",  # SOSINV1 — chart-inventory + vector-migration audit
    "3566eb1",  # SOS08D008I — implement <sos:clock_domains> D-side
    "df890f2",  # SOS08C007I — per-<param> sub-bus emit
    "192a189",  # SOS08CE008I — E walker consumes _clock_domains
    "37d0145",  # SOS08C008I — shared-signal HDL wiring
    "3ea7526",  # SOS09001A — PCDN-SOS-09-001 amendment
    "fb621ed",  # SOS7CLN — wave-7 coherence cleanup
]


@pytest.fixture(scope="module")
def wave3_audit_text() -> str:
    """Read the wave-3 audit doc; fail if not found."""
    if not _WAVE3_AUDIT_PATH.exists():
        pytest.fail(
            f"SOS-08 wave-3 audit doc missing at {_WAVE3_AUDIT_PATH} — "
            "expected per the 2026-05-25 wave-3 audit landing"
        )
    return _WAVE3_AUDIT_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------
# Group 1: existence + sibling-layout
# ---------------------------------------------------------------


class TestWave3AuditExists:
    """The wave-3 audit doc exists at the expected sibling path
    next to ``SOS-08-WAVE1-CONFORMANCE.md`` and
    ``SOS-08-WAVE2-CONFORMANCE.md``."""

    def test_audit_doc_file_present(self) -> None:
        assert _WAVE3_AUDIT_PATH.exists(), (
            f"SOS-08 wave-3 audit doc missing at {_WAVE3_AUDIT_PATH}"
        )

    def test_audit_doc_is_sibling_of_wave1(self) -> None:
        assert _WAVE1_AUDIT_PATH.exists(), (
            "wave-1 audit doc must exist as the audit-shape reference"
        )
        assert _WAVE3_AUDIT_PATH.parent == _WAVE1_AUDIT_PATH.parent

    def test_audit_doc_is_sibling_of_wave2(self) -> None:
        assert _WAVE2_AUDIT_PATH.exists(), (
            "wave-2 audit doc must exist as the direct predecessor"
        )
        assert _WAVE3_AUDIT_PATH.parent == _WAVE2_AUDIT_PATH.parent


# ---------------------------------------------------------------
# Group 2: required structural sections
# ---------------------------------------------------------------


class TestWave3AuditStructure:
    """Required sections per the dispatch's deliverable shape:
    §0 status banner, §2 scope, §3 per-gate audit, §5 carry-forward
    closures, §6 PCDNs, §7 test count migration, §8 wave-4 candidate
    list, §9 authority-boundary updates, §10 change log."""

    def test_section_0_status_banner_present(
        self, wave3_audit_text: str
    ) -> None:
        assert (
            "## 0. Status banner" in wave3_audit_text
            or "## 0 Status banner" in wave3_audit_text
        ), "§0 status banner section missing"

    def test_status_banner_declares_wave3_complete(
        self, wave3_audit_text: str
    ) -> None:
        # The banner must declare a wave-3 audit completion outcome.
        assert "wave-3" in wave3_audit_text.lower(), (
            "audit doc must mention wave-3 explicitly"
        )
        # Find the §0 banner block and assert it carries the
        # 🟢 + "wave-3 audit complete" status.
        banner_start = wave3_audit_text.find("## 0.")
        assert banner_start >= 0
        # Slice to the next §1 / §2 header.
        next_section = wave3_audit_text.find("## 1.", banner_start)
        banner_block = wave3_audit_text[banner_start:next_section]
        assert "🟢" in banner_block, (
            "§0 must carry the 🟢 wave-3 audit-complete marker"
        )
        assert (
            "wave-3 audit complete" in banner_block.lower()
            or "audit complete" in banner_block.lower()
        ), "§0 must declare wave-3 audit complete"

    def test_status_banner_dated_2026_05_25(
        self, wave3_audit_text: str
    ) -> None:
        # The dispatch specified a 2026-05-25 audit completion date.
        banner_start = wave3_audit_text.find("## 0.")
        assert banner_start >= 0
        next_section = wave3_audit_text.find("## 1.", banner_start)
        banner_block = wave3_audit_text[banner_start:next_section]
        assert "2026-05-25" in banner_block, (
            "§0 banner must carry the 2026-05-25 audit-completion date"
        )

    def test_section_2_scope_present(
        self, wave3_audit_text: str
    ) -> None:
        assert "## 2. Scope" in wave3_audit_text, (
            "§2 scope section missing"
        )

    def test_section_3_per_gate_audit_present(
        self, wave3_audit_text: str
    ) -> None:
        assert "## 3. Per-gate audit" in wave3_audit_text, (
            "§3 per-gate audit section missing"
        )

    def test_section_5_carry_forward_closures_present(
        self, wave3_audit_text: str
    ) -> None:
        assert "## 5. Carry-forward closures" in wave3_audit_text, (
            "§5 carry-forward closures section missing"
        )

    def test_section_6_pcdns_present(
        self, wave3_audit_text: str
    ) -> None:
        assert "## 6. PCDNs filed" in wave3_audit_text, (
            "§6 PCDNs section missing"
        )

    def test_section_7_test_count_migration_present(
        self, wave3_audit_text: str
    ) -> None:
        assert "## 7. Test count migration" in wave3_audit_text, (
            "§7 test count migration section missing"
        )

    def test_section_8_wave4_candidate_list_present(
        self, wave3_audit_text: str
    ) -> None:
        assert "## 8. Wave-4 candidate list" in wave3_audit_text, (
            "§8 wave-4 candidate list section missing"
        )

    def test_section_9_authority_boundary_present(
        self, wave3_audit_text: str
    ) -> None:
        assert "## 9. Authority-boundary" in wave3_audit_text, (
            "§9 authority-boundary table updates section missing"
        )

    def test_section_10_change_log_present(
        self, wave3_audit_text: str
    ) -> None:
        assert "## 10. Change log" in wave3_audit_text, (
            "§10 change log missing"
        )


# ---------------------------------------------------------------
# Group 3: §2 commit catalog
# ---------------------------------------------------------------


class TestWave3AuditCommitCatalog:
    """§2 catalogues the commits landed between wave-2 close and
    this audit. Dispatch requires at least 12 of the actual 14
    commits cited by seven-char SHA prefix."""

    def test_at_least_twelve_commits_cited(
        self, wave3_audit_text: str
    ) -> None:
        cited = [
            sha
            for sha in _WAVE3_COMMIT_SHAS
            if sha in wave3_audit_text
        ]
        assert len(cited) >= 12, (
            f"§2 should cite at least 12 of {len(_WAVE3_COMMIT_SHAS)} "
            f"wave-3 commits by SHA prefix; got {len(cited)}: {cited}"
        )

    def test_fb621ed_cited_as_wave3_close(
        self, wave3_audit_text: str
    ) -> None:
        # The wave-7 cleanup commit closes wave-3 — must be cited.
        assert "fb621ed" in wave3_audit_text, (
            "wave-3 close commit fb621ed must be cited in the wave-3 "
            "audit"
        )

    def test_3ea7526_amendment_cited(
        self, wave3_audit_text: str
    ) -> None:
        # The SOS-09-001 amendment commit must be cited.
        assert "3ea7526" in wave3_audit_text, (
            "PCDN-SOS-09-001 amendment commit 3ea7526 must be cited"
        )

    def test_c2aa1cf_wave2_close_referenced(
        self, wave3_audit_text: str
    ) -> None:
        # The wave-2 close SHA must appear as the range start anchor.
        assert "c2aa1cf" in wave3_audit_text, (
            "§2 must reference c2aa1cf as the wave-2 close anchor"
        )


# ---------------------------------------------------------------
# Group 4: §3 gate status
# ---------------------------------------------------------------


def _extract_gate_block(text: str, gate_letter: str) -> str:
    """Slice the §3 subsection for a given gate letter."""
    needle = f"### Gate ({gate_letter})"
    start = text.find(needle)
    assert start >= 0, f"§3 must carry a '{needle}' subsection"
    rest = text[start:]
    next_header = rest.find("\n### ", 1)
    if next_header < 0:
        next_header = rest.find("\n## ", 1)
    return rest[:next_header] if next_header > 0 else rest


class TestWave3AuditGateStatus:
    """Gates (e) and (g) MUST remain ⏸ — wave-3 does not authorize
    a bench session, so neither gate flips without one."""

    def test_gate_e_still_deferred(
        self, wave3_audit_text: str
    ) -> None:
        gate_e_block = _extract_gate_block(wave3_audit_text, "e")
        assert "⏸" in gate_e_block, (
            "gate (e) must remain ⏸ in wave-3 audit; flipping it "
            "requires a bench session that has not landed"
        )

    def test_gate_g_still_half_deferred(
        self, wave3_audit_text: str
    ) -> None:
        gate_g_block = _extract_gate_block(wave3_audit_text, "g")
        assert "⏸" in gate_g_block, (
            "gate (g) must still carry a ⏸ marker for numbers; "
            "paper translation landed in wave-1 but numerical "
            "readings remain co-gated on gate (e)"
        )

    def test_gates_a_through_d_and_f_satisfied(
        self, wave3_audit_text: str
    ) -> None:
        # The five satisfied gates must each carry a ✅ in their block.
        for letter in ("a", "b", "c", "d", "f"):
            block = _extract_gate_block(wave3_audit_text, letter)
            assert "✅" in block, (
                f"gate ({letter}) must carry ✅ in the wave-3 audit"
            )


# ---------------------------------------------------------------
# Group 5: §5 carry-forward closures
# ---------------------------------------------------------------


class TestWave3CarryForwardClosures:
    """§5 must list the closed wave-future items per sub-phase,
    including the wave-7 cleanup contributions."""

    def test_c_007_implementation_closure_cited(
        self, wave3_audit_text: str
    ) -> None:
        # SOS-08-C wave-3-f-future-B FULL — per-<param> sub-buses —
        # implemented by df890f2, closes PCDN-SOS-08-C-007.
        assert "df890f2" in wave3_audit_text
        assert (
            "PCDN-SOS-08-C-007" in wave3_audit_text
        ), "§5 / §6 must cite PCDN-SOS-08-C-007 closure"

    def test_c_008_implementation_closure_cited(
        self, wave3_audit_text: str
    ) -> None:
        # SOS-08-C shared-datamodel HDL chart-side wiring —
        # implemented by 37d0145, closes PCDN-SOS-08-C-008.
        assert "37d0145" in wave3_audit_text
        assert "PCDN-SOS-08-C-008" in wave3_audit_text

    def test_d_008_implementation_closure_cited(
        self, wave3_audit_text: str
    ) -> None:
        # SOS-08-D <sos:clock_domains> walker — implemented by
        # 3566eb1, closes PCDN-SOS-08-D-008.
        assert "3566eb1" in wave3_audit_text
        assert "PCDN-SOS-08-D-008" in wave3_audit_text

    def test_wave7_cleanup_cited_in_closures(
        self, wave3_audit_text: str
    ) -> None:
        # §5 must cite the wave-7 cleanup (fb621ed) contributions
        # to sub-phases C, D, E.
        section_5_start = wave3_audit_text.find(
            "## 5. Carry-forward"
        )
        assert section_5_start >= 0
        section_6_start = wave3_audit_text.find(
            "## 6. PCDNs", section_5_start
        )
        section_5_block = wave3_audit_text[
            section_5_start:section_6_start
        ]
        assert "fb621ed" in section_5_block, (
            "§5 must cite the wave-7 cleanup commit fb621ed in the "
            "closure table"
        )

    def test_no_software_backlog_headline(
        self, wave3_audit_text: str
    ) -> None:
        # The dispatch headline: SOS-08 family is in a "no
        # software-tractable backlog" state after wave-3.
        assert (
            "no software-tractable backlog" in wave3_audit_text
            or "no remaining software-tractable" in wave3_audit_text
        ), (
            "§5 / §10 must state the no-software-tractable-backlog "
            "headline at the SOS-08 sub-phase scope"
        )


# ---------------------------------------------------------------
# Group 6: §6 PCDNs filed / ratified / amended
# ---------------------------------------------------------------


class TestWave3PCDNs:
    """§6 cites the three sub-phase PCDNs that traversed
    file → ratify → implement within wave-3, plus the SOS-09-001
    amendment."""

    @pytest.mark.parametrize(
        "pcdn_id",
        [
            "PCDN-SOS-08-D-008",
            "PCDN-SOS-08-C-007",
            "PCDN-SOS-08-C-008",
            "PCDN-SOS-09-001",
        ],
    )
    def test_pcdn_cited_by_id(
        self, wave3_audit_text: str, pcdn_id: str
    ) -> None:
        assert pcdn_id in wave3_audit_text, (
            f"§6 must cite {pcdn_id} by ID"
        )

    def test_sos_09_amendment_named(
        self, wave3_audit_text: str
    ) -> None:
        # The SOS-09-001 amendment is the load-bearing fourth
        # PCDN — must be explicitly identified as an AMENDMENT
        # (not a fresh PCDN).
        assert "amendment" in wave3_audit_text.lower()
        assert "other_attributes" in wave3_audit_text, (
            "§6 must name the other_attributes extension surface "
            "that PCDN-SOS-09-001 amendment chose"
        )


# ---------------------------------------------------------------
# Group 7: §7 test count migration
# ---------------------------------------------------------------


class TestWave3TestCountMigration:
    """§7 must state the 1258-test cumulative pass count and the
    +346 delta from wave-2 close."""

    def test_1258_test_count_cited(
        self, wave3_audit_text: str
    ) -> None:
        assert "1258" in wave3_audit_text, (
            "§7 must cite the 1258-test cumulative pass count at "
            "wave-3 close (verified by pytest -q at fb621ed)"
        )

    def test_912_baseline_cited(
        self, wave3_audit_text: str
    ) -> None:
        # Wave-2 close baseline.
        assert "912" in wave3_audit_text, (
            "§7 must cite the 912-test wave-2 close baseline"
        )

    def test_delta_346_cited(
        self, wave3_audit_text: str
    ) -> None:
        # The +346 cumulative delta is the headline test count
        # number for wave-3.
        assert "346" in wave3_audit_text, (
            "§7 must cite the +346 cumulative delta from wave-2 "
            "close to wave-3 close"
        )


# ---------------------------------------------------------------
# Group 8: §8 wave-4 candidate list
# ---------------------------------------------------------------


class TestWave3Wave4Candidates:
    """§8 lists the SOS-09 sub-phase concept docs as the next
    gating items for wave-4."""

    def test_sos_09_subphase_docs_named_as_next_gating(
        self, wave3_audit_text: str
    ) -> None:
        section_8_start = wave3_audit_text.find(
            "## 8. Wave-4 candidate"
        )
        assert section_8_start >= 0
        section_9_start = wave3_audit_text.find(
            "## 9.", section_8_start
        )
        section_8_block = wave3_audit_text[
            section_8_start:section_9_start
        ]
        # The SOS-09 sub-phase concept docs (A through G) must be
        # named in §8.
        assert "SOS-09" in section_8_block, (
            "§8 must name SOS-09 as a wave-4 candidate"
        )
        assert (
            "SOS-09-A" in section_8_block
            and "SOS-09-G" in section_8_block
        ), (
            "§8 must enumerate the SOS-09-A through SOS-09-G "
            "sub-phase concept docs"
        )
        assert (
            "concept doc" in section_8_block.lower()
            or "concept-doc" in section_8_block.lower()
        ), "§8 must describe these as concept-doc drafting work"

    def test_gate_e_and_g_still_listed_as_open(
        self, wave3_audit_text: str
    ) -> None:
        section_8_start = wave3_audit_text.find(
            "## 8. Wave-4 candidate"
        )
        assert section_8_start >= 0
        section_9_start = wave3_audit_text.find(
            "## 9.", section_8_start
        )
        section_8_block = wave3_audit_text[
            section_8_start:section_9_start
        ]
        # Gate (e) and (g) must still appear as wave-4 candidates.
        assert "Gate (e)" in section_8_block, (
            "§8 must list Gate (e) bench validation as an open "
            "wave-4 candidate"
        )
        assert "Gate (g)" in section_8_block, (
            "§8 must list Gate (g) numerical readings as an open "
            "wave-4 candidate"
        )

    def test_status_marker_hygiene_called_out(
        self, wave3_audit_text: str
    ) -> None:
        section_8_start = wave3_audit_text.find(
            "## 8. Wave-4 candidate"
        )
        assert section_8_start >= 0
        section_9_start = wave3_audit_text.find(
            "## 9.", section_8_start
        )
        section_8_block = wave3_audit_text[
            section_8_start:section_9_start
        ]
        # The dispatch specified §14 PCDN status-marker hygiene as
        # an informative wave-4 item.
        assert (
            "Status-marker hygiene" in section_8_block
            or "status-marker hygiene" in section_8_block
        ), (
            "§8 must list §14 PCDN status-marker hygiene as an "
            "informative wave-4 cleanup item"
        )


# ---------------------------------------------------------------
# Group 9: §10 change log
# ---------------------------------------------------------------


class TestWave3ChangeLog:
    """§10 carries a single dated 2026-05-25 entry."""

    def test_dated_entry_present(
        self, wave3_audit_text: str
    ) -> None:
        assert "### 2026-05-25" in wave3_audit_text, (
            "§10 must carry a dated 2026-05-25 entry for the "
            "wave-3 audit completion"
        )

    def test_entry_names_author(
        self, wave3_audit_text: str
    ) -> None:
        # The wave-2 audit's §10 names "(Ira)"; wave-3 follows the
        # same convention.
        change_log_start = wave3_audit_text.find("## 10. Change log")
        assert change_log_start >= 0
        change_log_block = wave3_audit_text[change_log_start:]
        assert "(Ira)" in change_log_block, (
            "§10 dated entry must name the author per the "
            "wave-1 / wave-2 convention"
        )
