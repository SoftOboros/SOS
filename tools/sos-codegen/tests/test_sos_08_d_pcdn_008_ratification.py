"""SOS-08-D PCDN-SOS-08-D-008 ratification doc assertions.

@spec  docs/concepts/SOS-08-D-CONCEPTS.md §15 2026-05-25 entry
       "PCDN-SOS-08-D-008 ratification — `<sos:clock_domains>`
       element formalised".
@spec  docs/concepts/SOS-08-D-CONCEPTS.md §14 PCDN-SOS-08-D-008
       (status marker updated to 🟢 ratified 2026-05-25).

This module verifies that the post-Q1–Q9 walkthrough ratification
of PCDN-SOS-08-D-008 landed intact in the SOS-08-D concepts doc:

  - The §15 2026-05-25 ratification entry exists naming the PCDN.
  - The entry carries the normative element shape (source × kind
    identity model, kind enum, alias resolution, backwards-compat,
    sampling-clock inheritance, phase v2-staging).
  - Standards Action registration policy declared.
  - The Q1–Q9 decision log appears with all nine questions tabulated.
  - The §14 PCDN-SOS-08-D-008 entry carries a status marker that a
    §14 reader sees immediately (ratified 2026-05-25).

@invariants  INV-S-HDL-D-1 through D-6 (preserved by doc-only entry —
             the ratification names walker impact as deferred to a
             follow-up wave, no normative invariant churn here).
@invariants  INV-SOS-H (chart vocabulary survives in the ratified
             element shape — `source`, `kind`, `period_ns`,
             `duty_cycle`, `phase_ns` attribute names are chart-vocab
             surface).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Repo-root resolution: this test file lives at
# tools/sos-codegen/tests/test_sos_08_d_pcdn_008_ratification.py
# → repo root is three parents up.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONCEPTS_PATH = _REPO_ROOT / "docs" / "concepts" / "SOS-08-D-CONCEPTS.md"


@pytest.fixture(scope="module")
def concepts_text() -> str:
    if not _CONCEPTS_PATH.exists():
        pytest.fail(
            f"SOS-08-D concepts doc missing at {_CONCEPTS_PATH}"
        )
    return _CONCEPTS_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def ratification_entry(concepts_text: str) -> str:
    """Return the body of the 2026-05-25 PCDN-008 ratification §15 entry.

    Slice runs from the entry's date heading through to the next §15
    date heading or end-of-file.
    """
    pattern = re.compile(
        r"### 2026-05-25 — PCDN-SOS-08-D-008 ratification.*?"
        r"(?=^### \d{4}-\d{2}-\d{2}|\Z)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(concepts_text)
    if match is None:
        pytest.fail(
            "Could not locate §15 2026-05-25 PCDN-SOS-08-D-008 "
            "ratification entry."
        )
    return match.group(0)


@pytest.fixture(scope="module")
def section14_entry(concepts_text: str) -> str:
    """Return the §14 PCDN-SOS-08-D-008 entry text up to the next PCDN bullet."""
    pattern = re.compile(
        r"- \*\*PCDN-SOS-08-D-008 — `<sos:clock_domains>` element shape"
        r".*?(?=^- \*\*PCDN-SOS-08-D-\d{3}|^## )",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(concepts_text)
    if match is None:
        pytest.fail("Could not locate §14 PCDN-SOS-08-D-008 entry.")
    return match.group(0)


# ---------------------------------------------------------------------------
# §15 ratification entry — existence + heading
# ---------------------------------------------------------------------------


class TestRatificationEntryExists:
    """The 2026-05-25 ratification entry MUST exist."""

    def test_dated_heading_present(self, concepts_text: str) -> None:
        assert (
            "### 2026-05-25 — PCDN-SOS-08-D-008 ratification"
            in concepts_text
        ), (
            "Expected §15 2026-05-25 dated heading naming the PCDN."
        )

    def test_entry_names_clock_domains_element(
        self, ratification_entry: str
    ) -> None:
        assert "`<sos:clock_domains>`" in ratification_entry, (
            "Ratification entry MUST name the `<sos:clock_domains>` element."
        )

    def test_entry_status_marker_ratified(
        self, ratification_entry: str
    ) -> None:
        # 🟢 ratified appears in both the heading-adjacent intro line
        # and the closing Status: line.
        assert "🟢 ratified" in ratification_entry, (
            "Entry MUST carry the 🟢 ratified status marker."
        )


# ---------------------------------------------------------------------------
# §15 ratification entry — normative MUST/SHOULD/MAY language
# ---------------------------------------------------------------------------


class TestRatificationMustLanguage:
    """Normative keyword density per RFC 2119 / 8174."""

    def test_must_count_at_least_four(self, ratification_entry: str) -> None:
        # Capitalised normative MUST keyword (per RFC 8174 — capitals
        # carry binding force; lowercase is advisory).
        # Count distinct occurrences anywhere in the entry.
        must_count = len(
            re.findall(r"\bMUST\b", ratification_entry)
        )
        assert must_count >= 4, (
            f"Ratification entry should carry at least 4 capitalised "
            f"MUST normative keywords; found {must_count}."
        )

    def test_must_resolve_clock_references(
        self, ratification_entry: str
    ) -> None:
        assert "MUST resolve all clock references" in ratification_entry, (
            "Walker alias-resolution MUST language missing."
        )

    def test_walker_must_support_absence_via_backwards_compat(
        self, ratification_entry: str
    ) -> None:
        # The backwards-compat MUST sentence covers Q6's "walker MUST
        # support absence" requirement (implicit clock derived from
        # chart-root when the block is absent).
        # We anchor on the explicit backwards-compat MUST language.
        assert (
            "Backwards-compat (MUST)" in ratification_entry
            or "Backwards-compat (**MUST**)" in ratification_entry
        ), (
            "Backwards-compat MUST clause (walker MUST support absence) "
            "missing from ratification entry."
        )
        # And the implicit-clock-derived-from-chart-root language.
        assert 'source="chart_root"' in ratification_entry, (
            "Backwards-compat implicit-source language missing."
        )

    def test_should_for_user_supplied_source(
        self, ratification_entry: str
    ) -> None:
        # Q6: users SHOULD supply source=
        assert "SHOULD supply" in ratification_entry, (
            "Q6 user SHOULD-supply-source language missing."
        )

    def test_may_keyword_present(self, ratification_entry: str) -> None:
        # Q1 deferred: future pin-mapping MAY supply source=
        assert re.search(r"\bMAY\b", ratification_entry), (
            "RFC 2119 MAY keyword missing from ratification entry."
        )


# ---------------------------------------------------------------------------
# §15 ratification entry — kind enum
# ---------------------------------------------------------------------------


class TestKindEnum:
    """Q2 frozen enum at v1 = rising + falling; reserved future kinds."""

    def test_rising_listed(self, ratification_entry: str) -> None:
        assert "`rising`" in ratification_entry, (
            "Kind enum MUST list `rising`."
        )

    def test_falling_listed(self, ratification_entry: str) -> None:
        assert "`falling`" in ratification_entry, (
            "Kind enum MUST list `falling`."
        )

    def test_posedge_emit_mapping(self, ratification_entry: str) -> None:
        assert "@(posedge clk)" in ratification_entry, (
            "Kind=rising SV emit mapping to @(posedge clk) missing."
        )

    def test_negedge_emit_mapping(self, ratification_entry: str) -> None:
        assert "@(negedge clk)" in ratification_entry, (
            "Kind=falling SV emit mapping to @(negedge clk) missing."
        )

    def test_reserved_future_kinds_both_ddr(
        self, ratification_entry: str
    ) -> None:
        assert "`both`" in ratification_entry, (
            "Reserved future kind `both` (DDR) missing."
        )
        assert "DDR" in ratification_entry, (
            "DDR clarification on reserved `both` missing."
        )

    def test_reserved_future_quadrature_pair(
        self, ratification_entry: str
    ) -> None:
        assert "`quadrature_pair`" in ratification_entry, (
            "Reserved future kind `quadrature_pair` missing."
        )

    def test_reserved_future_three_phase_and_waltz(
        self, ratification_entry: str
    ) -> None:
        assert "three-phase" in ratification_entry, (
            "Reserved future three-phase kind missing."
        )
        assert "waltz" in ratification_entry, (
            "Reserved future waltz / arbitrary-meter kind missing."
        )

    def test_actionable_error_for_unsupported_kind(
        self, ratification_entry: str
    ) -> None:
        assert "SOS-08-D wave-future-clkkind" in ratification_entry, (
            "Actionable error prefix for unsupported kind missing."
        )


# ---------------------------------------------------------------------------
# §15 ratification entry — identity model
# ---------------------------------------------------------------------------


class TestIdentityModel:
    """Q3 + Q4: same `(source, kind)` = aliases; alphabetic-first canonical."""

    def test_source_kind_pair_identity(
        self, ratification_entry: str
    ) -> None:
        # The identity-model paragraph MUST say `(source, kind)`.
        assert "`(source, kind)`" in ratification_entry, (
            "Identity-model paragraph MUST state the `(source, kind)` pair."
        )

    def test_aliases_terminology(self, ratification_entry: str) -> None:
        assert "aliases" in ratification_entry.lower(), (
            "Q3 alias terminology missing from identity-model paragraph."
        )

    def test_alphabetic_first_canonical_name_rule(
        self, ratification_entry: str
    ) -> None:
        # Q3 (a): walker picks alphabetic-first as canonical.
        assert "alphabetic-first" in ratification_entry, (
            "Alphabetic-first canonical-name rule (Q3 (a)) missing."
        )

    def test_resolved_pair_comparison_for_downstream_consumers(
        self, ratification_entry: str
    ) -> None:
        # Q4: resolved-pair comparison for all downstream consumers.
        # Phrasing: "resolve all clock references ... through alias-
        # resolution to the canonical pair".
        # We assert the canonical-pair resolution language.
        assert "canonical pair" in ratification_entry, (
            "Q4 canonical-pair resolution language missing."
        )


# ---------------------------------------------------------------------------
# §15 ratification entry — element shape attributes
# ---------------------------------------------------------------------------


class TestElementShape:
    """Q5: element shape ratified per draft."""

    def test_source_attribute_documented(
        self, ratification_entry: str
    ) -> None:
        assert "source=" in ratification_entry, (
            "Element shape MUST document the `source=` attribute."
        )

    def test_kind_attribute_documented(
        self, ratification_entry: str
    ) -> None:
        assert "kind=" in ratification_entry, (
            "Element shape MUST document the `kind=` attribute."
        )

    def test_period_ns_attribute_documented(
        self, ratification_entry: str
    ) -> None:
        assert "period_ns=" in ratification_entry, (
            "Element shape MUST document the `period_ns=` attribute."
        )

    def test_duty_cycle_attribute_documented(
        self, ratification_entry: str
    ) -> None:
        assert "duty_cycle=" in ratification_entry, (
            "Element shape MUST document the `duty_cycle=` attribute."
        )

    def test_phase_ns_attribute_documented(
        self, ratification_entry: str
    ) -> None:
        # Q7 (a): per-clock phase_ns reserved for v2 quadrature
        # support; walker parses + stores at v1; emit ignores.
        assert "phase_ns=" in ratification_entry, (
            "Element shape MUST document the v2-staged `phase_ns=` attribute."
        )


# ---------------------------------------------------------------------------
# §15 ratification entry — Q8 sampling-clock inheritance
# ---------------------------------------------------------------------------


class TestSamplingClockInheritance:
    """Q8: `<sos:sampling_clock>` inherits kind from referenced declaration."""

    def test_sampling_clock_inherits_kind(
        self, ratification_entry: str
    ) -> None:
        # The doc text reads: '<sos:sampling_clock> does NOT carry its
        # own kind=; it inherits from the referenced <sos:clock>
        # declaration.'
        assert "<sos:sampling_clock>" in ratification_entry, (
            "Q8 sampling-clock-inheritance paragraph missing."
        )
        assert "inherits" in ratification_entry, (
            "Sampling-clock kind inheritance language missing."
        )


# ---------------------------------------------------------------------------
# §15 ratification entry — Q9 uniform CDC banner
# ---------------------------------------------------------------------------


class TestUniformCdcBanner:
    """Q9: uniform CDC banner v1; same-source-different-kind opt deferred."""

    def test_uniform_cdc_banner_decision(
        self, ratification_entry: str
    ) -> None:
        # The boundary-detection paragraph names same-source-different-
        # kind boundaries getting the same banner as different-source.
        assert "Same-source-different-kind" in ratification_entry or (
            "same-source-different-kind" in ratification_entry
        ), (
            "Q9 same-source-different-kind banner-decision language missing."
        )


# ---------------------------------------------------------------------------
# §15 ratification entry — Standards Action registration policy
# ---------------------------------------------------------------------------


class TestRegistrationPolicy:
    """Standards Action declared for the kind enum + element shape."""

    def test_standards_action_present(
        self, ratification_entry: str
    ) -> None:
        assert "Standards Action" in ratification_entry, (
            "Registration policy: Standards Action MUST be declared."
        )

    def test_authority_relationship_own(
        self, ratification_entry: str
    ) -> None:
        # Authority: `own` for the element shape, identity model,
        # alias-resolution rule, kind enum.
        assert "`own`" in ratification_entry, (
            "Authority relationship `own` MUST be declared per §0 "
            "standards-integration discipline."
        )


# ---------------------------------------------------------------------------
# §15 ratification entry — Q1–Q9 decision log
# ---------------------------------------------------------------------------


class TestQ1Q9DecisionLog:
    """All nine Q-references appear in the decision log."""

    @pytest.mark.parametrize(
        "q_marker",
        [
            "Q1 (b):",
            "Q2:",
            "Q3 (a):",
            "Q4:",
            "Q5:",
            "Q6:",
            "Q7 (a):",
            "Q8:",
            "Q9:",
        ],
    )
    def test_q_marker_present(
        self, ratification_entry: str, q_marker: str
    ) -> None:
        assert q_marker in ratification_entry, (
            f"Q1–Q9 decision log entry for `{q_marker}` missing."
        )

    def test_q1_opaque_source_string(
        self, ratification_entry: str
    ) -> None:
        # Q1 (b) summary: opaque source string at v1; pin-mapping future.
        assert "opaque" in ratification_entry, (
            "Q1 (b) opaque-source-string summary missing."
        )

    def test_q2_rising_falling(self, ratification_entry: str) -> None:
        # Q2 summary names rising + falling.
        # Already covered by TestKindEnum but reinforce in the log slice.
        assert "rising" in ratification_entry and "falling" in ratification_entry, (
            "Q2 rising + falling enum summary missing from decision log."
        )

    def test_q9_uniform_banner_deferred_optimisation(
        self, ratification_entry: str
    ) -> None:
        # Q9 summary: uniform CDC banner v1; optimisation deferred.
        assert "optimisation deferred" in ratification_entry or (
            "optimization deferred" in ratification_entry
        ), (
            "Q9 deferred-optimisation summary missing from decision log."
        )


# ---------------------------------------------------------------------------
# §15 ratification entry — tracking / cross-references
# ---------------------------------------------------------------------------


class TestTracking:
    """The Tracking block names the filing commit + cross-referenced PCDNs."""

    def test_tracking_block_present(
        self, ratification_entry: str
    ) -> None:
        assert "Tracking" in ratification_entry, (
            "Tracking block missing from ratification entry."
        )

    def test_filing_commit_cited(self, ratification_entry: str) -> None:
        # The PCDN was filed in commit 1ecbf31; the ratification entry
        # cites that commit.
        assert "1ecbf31" in ratification_entry, (
            "Filing commit 1ecbf31 MUST be cited in Tracking block."
        )

    def test_pcdn_sos_08_010_cross_reference(
        self, ratification_entry: str
    ) -> None:
        # Cross-references PCDN-SOS-08-010 (region clock= attribute).
        assert "PCDN-SOS-08-010" in ratification_entry, (
            "Cross-reference to PCDN-SOS-08-010 missing from Tracking block."
        )


# ---------------------------------------------------------------------------
# §14 PCDN-SOS-08-D-008 entry — status marker update
# ---------------------------------------------------------------------------


class TestSection14StatusMarker:
    """§14 entry now carries a status marker indicating ratified 2026-05-25."""

    def test_section14_entry_still_present(
        self, section14_entry: str
    ) -> None:
        # The original PCDN filing text MUST remain intact alongside
        # the new status marker.
        assert "Surfaced by 2026-05-24 wave-4 implementation" in section14_entry, (
            "Original §14 PCDN-SOS-08-D-008 filing text deleted — should "
            "be preserved alongside the new status marker."
        )

    def test_section14_status_ratified_marker(
        self, section14_entry: str
    ) -> None:
        # A §14 reader MUST immediately see that the PCDN is ratified.
        assert "🟢" in section14_entry and "ratified" in section14_entry, (
            "§14 PCDN-SOS-08-D-008 entry MUST carry a 🟢 ratified status marker."
        )

    def test_section14_status_dated_2026_05_25(
        self, section14_entry: str
    ) -> None:
        assert "2026-05-25" in section14_entry, (
            "§14 PCDN-SOS-08-D-008 status marker MUST be dated 2026-05-25."
        )

    def test_section14_points_at_section15_entry(
        self, section14_entry: str
    ) -> None:
        # The status marker should redirect the reader to the §15 entry.
        assert "§15" in section14_entry, (
            "§14 status marker SHOULD redirect to the §15 ratification entry."
        )
