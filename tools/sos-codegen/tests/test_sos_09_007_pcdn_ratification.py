"""SOS-09 PCDN-SOS-09-007 ratification doc assertions.

@spec  docs/concepts/SOS-09-CONCEPTS.md §15.7
       "PCDN-SOS-09-007 — Channel-group as one axis or two".
@spec  docs/concepts/SOS-09-CONCEPTS.md §16 2026-05-26 change-log entry
       "PCDN-SOS-09-007 ratification + analyzer/annotation-semantics
       versioned-pair note".

This module verifies that the PCDN-SOS-09-007 umbrella ratification of
2026-05-26 landed intact in the SOS-09 umbrella concepts doc:

  - §15.7 sub-section exists and names PCDN-SOS-09-007.
  - PCDN-SOS-09-007 carries 🟢 RATIFIED 2026-05-26 status with the
    accepted-option-(b) resolution (two axes with default-from-inheritance).
  - The two-axis resolution names BOTH `sos:channel_group` AND
    `sos:privilege_region` annotation keys.
  - The default-from-inheritance rule is stated explicitly.
  - §15.7 cross-references PCDN-SOS-09-D-001 and PCDN-SOS-09-E-003.
  - §15.7 declares Standards Action as the frozen-enumeration
    registration policy.
  - §16 carries a 2026-05-26 entry naming PCDN-SOS-09-007.
  - The §16 2026-05-26 entry cites the analyzer/annotation-semantics
    versioned-pair discipline.
  - The §16 2026-05-26 entry mentions the deferred SOS-09-A §5.2
    twelve-key expansion (and that it lands JIT, not in this commit).
  - The §16 2026-05-26 entry declares scjson out-of-scope.

@invariants  INV-SOS-A (chart-as-source) — preserved: the two new
             axes ride within the chart `other_attributes` surface.
@invariants  INV-SOS-D (scjson round-trip) — preserved: the new keys
             use the existing `sos:`-prefixed convention inside
             `other_attributes` (no scjson amendment required).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Repo-root resolution: this test file lives at
# tools/sos-codegen/tests/test_sos_09_007_pcdn_ratification.py
# → repo root is three parents up.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONCEPTS_PATH = _REPO_ROOT / "docs" / "concepts" / "SOS-09-CONCEPTS.md"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def concepts_text() -> str:
    if not _CONCEPTS_PATH.exists():
        pytest.fail(
            f"SOS-09 concepts doc missing at {_CONCEPTS_PATH}"
        )
    return _CONCEPTS_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def pcdn_007_subsection(concepts_text: str) -> str:
    """Return the §15.7 PCDN-SOS-09-007 sub-section body.

    Slice runs from the §15.7 heading through to the start of §16.
    """
    pattern = re.compile(
        r"### 15\.7 PCDN-SOS-09-007.*?(?=^## 16\.|\Z)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(concepts_text)
    if match is None:
        pytest.fail(
            "Could not locate §15.7 PCDN-SOS-09-007 sub-section "
            "in SOS-09-CONCEPTS.md."
        )
    return match.group(0)


@pytest.fixture(scope="module")
def change_log_2026_05_26(concepts_text: str) -> str:
    """Return the body of the §16 2026-05-26 change-log entry.

    Slice runs from the dated heading through to the next dated heading
    or end-of-file.
    """
    pattern = re.compile(
        r"### 2026-05-26 — PCDN-SOS-09-007 ratification.*?"
        r"(?=^### \d{4}-\d{2}-\d{2}|\Z)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(concepts_text)
    if match is None:
        pytest.fail(
            "Could not locate §16 2026-05-26 PCDN-SOS-09-007 ratification "
            "change-log entry in SOS-09-CONCEPTS.md."
        )
    return match.group(0)


# ---------------------------------------------------------------------------
# §15.7 sub-section — existence + headings
# ---------------------------------------------------------------------------


class TestPcdn007SubsectionExists:
    """The §15.7 sub-section MUST exist and name PCDN-SOS-09-007."""

    def test_concepts_doc_readable(self, concepts_text: str) -> None:
        assert concepts_text, (
            "SOS-09-CONCEPTS.md must be non-empty and readable."
        )

    def test_subsection_heading_present(self, concepts_text: str) -> None:
        assert "### 15.7 PCDN-SOS-09-007" in concepts_text, (
            "Expected §15.7 sub-section heading naming PCDN-SOS-09-007."
        )

    def test_subsection_names_pcdn(self, pcdn_007_subsection: str) -> None:
        assert "PCDN-SOS-09-007" in pcdn_007_subsection, (
            "§15.7 sub-section MUST name PCDN-SOS-09-007."
        )

    def test_subsection_title_describes_axis_question(
        self, pcdn_007_subsection: str
    ) -> None:
        # Title shape: "Channel-group as one axis or two".
        assert "axis" in pcdn_007_subsection.lower(), (
            "§15.7 title MUST describe the axis-count question."
        )


# ---------------------------------------------------------------------------
# §15.7 sub-section — RATIFIED status + accepted option (b)
# ---------------------------------------------------------------------------


class TestPcdn007Status:
    """PCDN-SOS-09-007 MUST carry the 🟢 RATIFIED 2026-05-26 marker."""

    def test_ratified_status_marker(self, pcdn_007_subsection: str) -> None:
        assert "🟢" in pcdn_007_subsection, (
            "§15.7 MUST carry the 🟢 (green) status marker."
        )

    def test_ratified_2026_05_26(self, pcdn_007_subsection: str) -> None:
        assert "RATIFIED 2026-05-26" in pcdn_007_subsection, (
            "§15.7 MUST carry the RATIFIED 2026-05-26 marker."
        )

    def test_accepted_option_b(self, pcdn_007_subsection: str) -> None:
        assert "accepted option (b)" in pcdn_007_subsection, (
            "§15.7 MUST state the resolution as 'accepted option (b)'."
        )


# ---------------------------------------------------------------------------
# §15.7 sub-section — two-axis resolution
# ---------------------------------------------------------------------------


class TestPcdn007TwoAxisResolution:
    """The resolution names both annotation-key axes."""

    def test_names_sos_channel_group(self, pcdn_007_subsection: str) -> None:
        assert "sos:channel_group" in pcdn_007_subsection, (
            "§15.7 MUST name the `sos:channel_group` annotation key "
            "(Rust borrow scope / RegisterBlock boundary axis)."
        )

    def test_names_sos_privilege_region(
        self, pcdn_007_subsection: str
    ) -> None:
        assert "sos:privilege_region" in pcdn_007_subsection, (
            "§15.7 MUST name the `sos:privilege_region` annotation key "
            "(HDL MPU + access-violation aggregation axis)."
        )

    def test_two_axes_language(self, pcdn_007_subsection: str) -> None:
        # The resolution must explicitly talk about "two axes" or "two
        # axis" or "two independent ... axes".
        text = pcdn_007_subsection.lower()
        assert "two axes" in text or "two-axis" in text, (
            "§15.7 MUST explicitly name the resolution as 'two axes' "
            "(or 'two-axis')."
        )

    def test_rust_borrow_scope_named(self, pcdn_007_subsection: str) -> None:
        # `sos:channel_group` is the Rust borrow scope / RegisterBlock
        # boundary axis. The resolution prose must describe it as such.
        text = pcdn_007_subsection
        assert "borrow" in text.lower(), (
            "§15.7 MUST describe `sos:channel_group` in terms of Rust "
            "borrow scope."
        )
        assert "RegisterBlock" in text, (
            "§15.7 MUST cite the Rust `RegisterBlock` boundary in the "
            "channel-group axis description."
        )

    def test_hdl_mpu_axis_described(self, pcdn_007_subsection: str) -> None:
        text = pcdn_007_subsection
        assert "MPU" in text, (
            "§15.7 MUST cite the HDL MPU axis when describing "
            "`sos:privilege_region`."
        )
        assert "access-violation" in text.lower(), (
            "§15.7 MUST describe `sos:privilege_region` as covering "
            "access-violation aggregation on the HDL side."
        )


# ---------------------------------------------------------------------------
# §15.7 sub-section — default-from-inheritance rule
# ---------------------------------------------------------------------------


class TestPcdn007DefaultFromInheritance:
    """The default rule (privilege_region inherits from channel_group) is named."""

    def test_inheritance_rule_present(
        self, pcdn_007_subsection: str
    ) -> None:
        text = pcdn_007_subsection.lower()
        # Accept any of: "inherits", "inheritance", "default", or
        # equivalent textual presence.
        has_inheritance = (
            "inherit" in text or "default" in text
        )
        assert has_inheritance, (
            "§15.7 MUST name the default-from-inheritance rule "
            "(privilege_region defaults to / inherits the value of "
            "channel_group when unset)."
        )

    def test_inheritance_direction_explicit(
        self, pcdn_007_subsection: str
    ) -> None:
        # The rule's DIRECTION must be unambiguous: privilege_region
        # inherits FROM channel_group (not vice-versa). We assert both
        # keys appear in close proximity to inherit/default language.
        text = pcdn_007_subsection
        # Find a sentence (between full-stops) that names both
        # privilege_region and (inherits or default).
        match = re.search(
            r"sos:privilege_region[^.]*?(?:inherit|default)[^.]*?sos:channel_group",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        match_other_order = re.search(
            r"sos:channel_group[^.]*?(?:inherit|default)[^.]*?sos:privilege_region",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        assert match is not None or match_other_order is not None, (
            "§15.7 MUST name the inheritance direction in a sentence "
            "naming both keys: privilege_region inherits from "
            "channel_group when unset."
        )


# ---------------------------------------------------------------------------
# §15.7 sub-section — cross-references to D-001 and E-003
# ---------------------------------------------------------------------------


class TestPcdn007CrossReferences:
    """§15.7 MUST cross-reference PCDN-SOS-09-D-001 and PCDN-SOS-09-E-003."""

    def test_cites_pcdn_d_001(self, pcdn_007_subsection: str) -> None:
        assert "PCDN-SOS-09-D-001" in pcdn_007_subsection, (
            "§15.7 MUST cross-reference PCDN-SOS-09-D-001 (Rust "
            "RegisterBlock borrow-enclosure unit) as the sibling PCDN "
            "consuming the `sos:channel_group` axis."
        )

    def test_cites_pcdn_e_003(self, pcdn_007_subsection: str) -> None:
        assert "PCDN-SOS-09-E-003" in pcdn_007_subsection, (
            "§15.7 MUST cross-reference PCDN-SOS-09-E-003 (HDL "
            "channel-group strobe-latch aggregation unit) as the sibling "
            "PCDN consuming the `sos:privilege_region` axis."
        )


# ---------------------------------------------------------------------------
# §15.7 sub-section — registration policy
# ---------------------------------------------------------------------------


class TestPcdn007RegistrationPolicy:
    """§15.7 declares Standards Action as the frozen-enumeration policy."""

    def test_standards_action_declared(
        self, pcdn_007_subsection: str
    ) -> None:
        assert "Standards Action" in pcdn_007_subsection, (
            "§15.7 MUST declare Standards Action as the "
            "frozen-enumeration registration policy for the axis count."
        )


# ---------------------------------------------------------------------------
# §15.7 sub-section — implementation note (deferred SOS-09-A amendment)
# ---------------------------------------------------------------------------


class TestPcdn007ImplementationNote:
    """The implementation note describes the deferred SOS-09-A amendment."""

    def test_mentions_sos_09_a_five_two(
        self, pcdn_007_subsection: str
    ) -> None:
        # The deferred SOS-09-A §5.2 amendment.
        assert "§5.2" in pcdn_007_subsection or "5.2" in pcdn_007_subsection, (
            "§15.7 implementation note MUST cite the deferred SOS-09-A "
            "§5.2 ten-key set expansion."
        )

    def test_mentions_twelve_key_expansion(
        self, pcdn_007_subsection: str
    ) -> None:
        # The expansion is from ten to twelve keys.
        text = pcdn_007_subsection.lower()
        assert "twelve-key" in text or "twelve key" in text, (
            "§15.7 implementation note MUST describe the expansion as a "
            "twelve-key set."
        )

    def test_mentions_spec_before_code_discipline(
        self, pcdn_007_subsection: str
    ) -> None:
        # The implementation-note cites the SBC discipline rule that
        # invariant/enum amendments precede behaviour PRs.
        text = pcdn_007_subsection
        assert "Spec-Before-Code" in text or "spec-before-code" in text.lower(), (
            "§15.7 implementation note MUST cite the Spec-Before-Code "
            "discipline as the authority for the amendment-first rule."
        )


# ---------------------------------------------------------------------------
# §16 2026-05-26 change-log entry — existence + heading
# ---------------------------------------------------------------------------


class TestChangeLog2026_05_26Exists:
    """The §16 2026-05-26 dated entry MUST exist and name the PCDN."""

    def test_dated_heading_present(self, concepts_text: str) -> None:
        assert (
            "### 2026-05-26 — PCDN-SOS-09-007 ratification"
            in concepts_text
        ), (
            "§16 MUST carry a 2026-05-26 dated heading naming "
            "PCDN-SOS-09-007 ratification."
        )

    def test_entry_names_pcdn(self, change_log_2026_05_26: str) -> None:
        assert "PCDN-SOS-09-007" in change_log_2026_05_26, (
            "§16 2026-05-26 entry MUST name PCDN-SOS-09-007."
        )

    def test_entry_status_ratified(
        self, change_log_2026_05_26: str
    ) -> None:
        assert (
            "🟢 ratified 2026-05-26" in change_log_2026_05_26
            or "🟢 RATIFIED 2026-05-26" in change_log_2026_05_26
        ), (
            "§16 2026-05-26 entry MUST carry a 🟢 ratified 2026-05-26 marker."
        )

    def test_entry_resolution_b(self, change_log_2026_05_26: str) -> None:
        text = change_log_2026_05_26.lower()
        assert "(b)" in text or "option (b)" in text, (
            "§16 2026-05-26 entry MUST cite option (b) as the resolution."
        )


# ---------------------------------------------------------------------------
# §16 2026-05-26 entry — versioned-pair discipline citation
# ---------------------------------------------------------------------------


class TestChangeLogVersionedPairDiscipline:
    """The §16 entry MUST cite the analyzer/annotation-semantics versioned-pair discipline."""

    def test_versioned_pair_phrase_present(
        self, change_log_2026_05_26: str
    ) -> None:
        # Accept any of: "versioned pair", "version together", "versioned-pair",
        # or equivalent textual presence.
        text = change_log_2026_05_26.lower()
        has_phrase = (
            "versioned pair" in text
            or "versioned-pair" in text
            or "version together" in text
            or "rev together" in text
        )
        assert has_phrase, (
            "§16 2026-05-26 entry MUST cite the "
            "analyzer/annotation-semantics versioned-pair discipline "
            "(phrase 'versioned pair' / 'versioned-pair' / 'rev together')."
        )

    def test_mentions_analyzer(self, change_log_2026_05_26: str) -> None:
        assert "analyzer" in change_log_2026_05_26.lower(), (
            "§16 2026-05-26 entry MUST mention the chart-bounds analyzer "
            "as one half of the versioned pair."
        )

    def test_mentions_sos_09_a_concepts(
        self, change_log_2026_05_26: str
    ) -> None:
        assert "SOS-09-A" in change_log_2026_05_26, (
            "§16 2026-05-26 entry MUST cite SOS-09-A-CONCEPTS.md as the "
            "annotation-semantics half of the versioned pair."
        )

    def test_mentions_safety_comments_canonical_example(
        self, change_log_2026_05_26: str
    ) -> None:
        # The canonical example is D-005 codegen-emitted // SAFETY: comments.
        # Accept any reasonable phrasing.
        text = change_log_2026_05_26
        assert "SAFETY" in text or "D-005" in text, (
            "§16 2026-05-26 entry MUST cite the D-005 // SAFETY: comments "
            "canonical example of a safety-bearing emit backend that "
            "binds the versioned-pair discipline."
        )


# ---------------------------------------------------------------------------
# §16 2026-05-26 entry — deferred SOS-09-A §5.2 amendment note
# ---------------------------------------------------------------------------


class TestChangeLogDeferredAmendment:
    """The §16 entry mentions the deferred SOS-09-A §5.2 amendment."""

    def test_mentions_deferred_amendment(
        self, change_log_2026_05_26: str
    ) -> None:
        text = change_log_2026_05_26.lower()
        # Accept "twelve-key", "§5.2", "future §15 amendment", "JIT",
        # or equivalent textual presence.
        has_deferred = (
            "twelve-key" in text
            or "twelve key" in text
            or "§5.2" in change_log_2026_05_26
            or "future §15 amendment" in change_log_2026_05_26.lower()
            or "jit" in text
        )
        assert has_deferred, (
            "§16 2026-05-26 entry MUST mention the deferred SOS-09-A "
            "§5.2 amendment (twelve-key expansion, JIT with D/E "
            "implementation)."
        )

    def test_amendment_explicitly_not_in_this_commit(
        self, change_log_2026_05_26: str
    ) -> None:
        text = change_log_2026_05_26.lower()
        # The deferral must be explicit: the amendment is NOT included
        # in this commit. Accept "not included", "deferred", "separate
        # commit", or similar.
        explicit = (
            "not included in this commit" in text
            or "deferred" in text
            or "separate" in text
            or "future" in text
        )
        assert explicit, (
            "§16 2026-05-26 entry MUST make the deferral explicit "
            "(the SOS-09-A amendment is NOT in this commit)."
        )


# ---------------------------------------------------------------------------
# §16 2026-05-26 entry — scjson out-of-scope note
# ---------------------------------------------------------------------------


class TestChangeLogScjsonOutOfScope:
    """The §16 entry declares scjson out-of-scope."""

    def test_scjson_not_in_scope(self, change_log_2026_05_26: str) -> None:
        text = change_log_2026_05_26
        # Accept "scjson is NOT in scope" or "no scjson" or equivalent.
        has_scjson_oos = (
            "scjson is NOT in scope" in text
            or "no scjson" in text.lower()
            or ("scjson" in text.lower() and "not in scope" in text.lower())
            or ("scjson" in text.lower() and "out-of-scope" in text.lower())
            or ("scjson" in text.lower() and "out of scope" in text.lower())
        )
        assert has_scjson_oos, (
            "§16 2026-05-26 entry MUST declare scjson out-of-scope for "
            "the PCDN-007 round (no scjson schema amendment required)."
        )

    def test_other_attributes_preservation_named(
        self, change_log_2026_05_26: str
    ) -> None:
        # The justification for scjson-out-of-scope is that
        # `other_attributes` already preserves the JSON.
        assert "other_attributes" in change_log_2026_05_26, (
            "§16 2026-05-26 entry MUST cite `other_attributes` as the "
            "preservation surface that lets scjson stay out of scope."
        )


# ---------------------------------------------------------------------------
# §16 2026-05-26 entry — annotation keys present (matching §15.7)
# ---------------------------------------------------------------------------


class TestChangeLogAnnotationKeys:
    """The §16 entry restates the two annotation keys for the wave-N reader."""

    def test_change_log_names_channel_group(
        self, change_log_2026_05_26: str
    ) -> None:
        assert "sos:channel_group" in change_log_2026_05_26, (
            "§16 2026-05-26 entry MUST restate the `sos:channel_group` "
            "key (for readers who land on the change log without "
            "scrolling §15.7)."
        )

    def test_change_log_names_privilege_region(
        self, change_log_2026_05_26: str
    ) -> None:
        assert "sos:privilege_region" in change_log_2026_05_26, (
            "§16 2026-05-26 entry MUST restate the `sos:privilege_region` "
            "key (for readers who land on the change log without "
            "scrolling §15.7)."
        )


# ---------------------------------------------------------------------------
# §16 2026-05-26 entry — test coverage trail
# ---------------------------------------------------------------------------


class TestChangeLogTestCoverageTrail:
    """The §16 entry cites this test module (for forward traceability)."""

    def test_cites_this_test_module(
        self, change_log_2026_05_26: str
    ) -> None:
        # Forward traceability: the entry names the test file that
        # binds the ratification.
        assert (
            "tools/sos-codegen/tests/test_sos_09_007_pcdn_ratification.py"
            in change_log_2026_05_26
        ), (
            "§16 2026-05-26 entry MUST cite the test module path "
            "`tools/sos-codegen/tests/test_sos_09_007_pcdn_ratification.py` "
            "for forward traceability."
        )
