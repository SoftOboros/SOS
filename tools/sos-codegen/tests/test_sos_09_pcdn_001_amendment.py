"""SOS-09 PCDN-SOS-09-001 amendment doc assertions.

@spec  docs/concepts/SOS-09-CONCEPTS.md 2026-05-25 change-log entry
       "PCDN-SOS-09-001 amendment — channel annotations on
       `other_attributes` (retraction + re-ratification)".
@spec  docs/concepts/SOS-09-CONCEPTS.md PCDN-SOS-09-001 entry
       (status marker added pointing at the amendment).
@spec  docs/concepts/SOS-09-CONCEPTS.md 2026-05-23 ratification table
       PCDN-001 row (superseded marker appended).

This module verifies that the PCDN-SOS-09-001 amendment of 2026-05-25
landed intact in the SOS-09 concepts doc:

  - The 2026-05-25 amendment entry exists naming the PCDN.
  - The entry retracts the 2026-05-23 `xmlns:sos="https://softoboros.com/sos/1.0"`
    resolution.
  - The entry mandates `other_attributes` for channel annotations.
  - The entry uses a `sos:` STRING prefix inside `other_attributes` JSON
    (e.g. `"sos:kind": "status"`), NOT an XML namespace prefix.
  - The scope clause carves OUT SOS-08-D / -E namespaced ELEMENTS.
  - The 2026-05-23 ratification row's PCDN-001 cell carries a
    "superseded" marker.
  - The PCDN-SOS-09-001 §15 entry carries an "amended" status marker.
  - No `xmlns:sos` declaration appears in chart-author-facing XML
    examples (occurrences are confined to the retraction/quotation
    context within the amendment narrative).

@invariants  INV-SOS-A (chart-as-source) — preserved by routing
             annotations through iState's `other_attributes` surface.
@invariants  INV-SOS-D (scjson round-trip) — preserved by NOT
             registering a custom XML namespace.
@invariants  Element-vs-attribute distinction — preserved: this
             amendment touches attributes only; SOS-08-D / -E namespaced
             ELEMENTS remain outside scope.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Repo-root resolution: this test file lives at
# tools/sos-codegen/tests/test_sos_09_pcdn_001_amendment.py
# → repo root is three parents up.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONCEPTS_PATH = _REPO_ROOT / "docs" / "concepts" / "SOS-09-CONCEPTS.md"


@pytest.fixture(scope="module")
def concepts_text() -> str:
    if not _CONCEPTS_PATH.exists():
        pytest.fail(
            f"SOS-09 concepts doc missing at {_CONCEPTS_PATH}"
        )
    return _CONCEPTS_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def amendment_entry(concepts_text: str) -> str:
    """Return the body of the 2026-05-25 PCDN-001 amendment change-log entry.

    Slice runs from the entry's date heading through end-of-file (the
    amendment is the latest change-log entry).
    """
    pattern = re.compile(
        r"### 2026-05-25 — PCDN-SOS-09-001 amendment.*?"
        r"(?=^### \d{4}-\d{2}-\d{2}|\Z)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(concepts_text)
    if match is None:
        pytest.fail(
            "Could not locate 2026-05-25 PCDN-SOS-09-001 amendment "
            "change-log entry."
        )
    return match.group(0)


@pytest.fixture(scope="module")
def ratification_2026_05_23(concepts_text: str) -> str:
    """Return the 2026-05-23 ratification change-log entry slice.

    Runs from the "### 2026-05-23 — Ratified" heading through to the next
    "### " heading (which is the 2026-05-25 amendment).
    """
    pattern = re.compile(
        r"### 2026-05-23 — Ratified.*?(?=^### \d{4}-\d{2}-\d{2})",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(concepts_text)
    if match is None:
        pytest.fail(
            "Could not locate 2026-05-23 ratification change-log entry."
        )
    return match.group(0)


@pytest.fixture(scope="module")
def pcdn_001_pending_entry(concepts_text: str) -> str:
    """Return the PCDN-SOS-09-001 bullet entry from the PCDNs section.

    Slice runs from the PCDN-SOS-09-001 bullet through to the next
    PCDN-SOS-09 bullet or section heading.
    """
    pattern = re.compile(
        r"- \*\*PCDN-SOS-09-001 — Channel-annotation XML namespace"
        r".*?(?=^- \*\*PCDN-SOS-09-\d{3}|^## )",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(concepts_text)
    if match is None:
        pytest.fail("Could not locate PCDN-SOS-09-001 PCDNs-section entry.")
    return match.group(0)


# ---------------------------------------------------------------------------
# Amendment entry — existence + heading
# ---------------------------------------------------------------------------


class TestAmendmentEntryExists:
    """The 2026-05-25 amendment entry MUST exist and name the PCDN."""

    def test_dated_heading_present(self, concepts_text: str) -> None:
        assert (
            "### 2026-05-25 — PCDN-SOS-09-001 amendment"
            in concepts_text
        ), (
            "Expected 2026-05-25 dated heading naming the PCDN."
        )

    def test_entry_names_pcdn(self, amendment_entry: str) -> None:
        assert "PCDN-SOS-09-001" in amendment_entry, (
            "Amendment entry MUST name PCDN-SOS-09-001."
        )

    def test_entry_status_amended(self, amendment_entry: str) -> None:
        # 🟢 amended 2026-05-25 — supersedes the 2026-05-23 resolution.
        assert "🟢 amended 2026-05-25" in amendment_entry, (
            "Amendment entry MUST carry the 🟢 amended 2026-05-25 marker."
        )

    def test_entry_supersedes_language(self, amendment_entry: str) -> None:
        assert "supersedes" in amendment_entry.lower(), (
            "Amendment entry MUST declare it supersedes the 2026-05-23 "
            "resolution."
        )


# ---------------------------------------------------------------------------
# Amendment entry — retraction of xmlns:sos
# ---------------------------------------------------------------------------


class TestRetraction:
    """The amendment MUST explicitly retract the xmlns:sos resolution."""

    def test_retraction_section_present(self, amendment_entry: str) -> None:
        assert "**Retraction.**" in amendment_entry, (
            "Amendment entry MUST carry a **Retraction.** section."
        )

    def test_retraction_quotes_xmlns_sos(self, amendment_entry: str) -> None:
        # The retraction explicitly cites the URL being retracted (for
        # forensic traceability). The URL MAY appear in the retraction
        # quote and the implementation-impact paragraph; what matters is
        # that the retraction CONTEXT names it.
        assert "xmlns:sos" in amendment_entry, (
            "Retraction MUST cite the `xmlns:sos` attribute being retracted."
        )

    def test_retraction_quotes_softoboros_url(
        self, amendment_entry: str
    ) -> None:
        assert "https://softoboros.com/sos/1.0" in amendment_entry, (
            "Retraction MUST cite the `https://softoboros.com/sos/1.0` URL "
            "being retracted (for forensic/historical clarity)."
        )

    def test_url_explicitly_not_registered(
        self, amendment_entry: str
    ) -> None:
        # The retraction MUST say the URL is NOT registered.
        assert "NOT registered" in amendment_entry, (
            "Retraction MUST state the URL is NOT registered by SOS."
        )

    def test_two_tier_convention_retracted(
        self, amendment_entry: str
    ) -> None:
        assert "two-tier convention" in amendment_entry, (
            "Retraction MUST explicitly retract the two-tier convention."
        )


# ---------------------------------------------------------------------------
# Amendment entry — amended resolution body
# ---------------------------------------------------------------------------


class TestAmendedResolution:
    """The amended resolution mandates `other_attributes` for SOS-09."""

    def test_amended_resolution_section(self, amendment_entry: str) -> None:
        assert "**Amended resolution.**" in amendment_entry, (
            "Amendment entry MUST carry an **Amended resolution.** section."
        )

    def test_other_attributes_mandated(self, amendment_entry: str) -> None:
        assert "`other_attributes`" in amendment_entry, (
            "Amended resolution MUST mandate iState's `other_attributes` "
            "extension surface."
        )

    def test_iState_extension_surface_named(
        self, amendment_entry: str
    ) -> None:
        # Phrase: "iState's `other_attributes` extension surface".
        assert "iState's `other_attributes` extension surface" in amendment_entry, (
            "Amended resolution MUST name iState's `other_attributes` "
            "extension surface."
        )

    def test_four_attribute_set_named(self, amendment_entry: str) -> None:
        # The four SOS-09 channel-annotation attributes.
        for attr in ("kind", "dir", "mutex", "protection-zone"):
            assert f"`{attr}`" in amendment_entry, (
                f"Amendment entry MUST name the `{attr}` channel attribute "
                f"in the amended four-attribute set."
            )


# ---------------------------------------------------------------------------
# Amendment entry — `sos:` STRING prefix (not XML namespace prefix)
# ---------------------------------------------------------------------------


class TestSosStringPrefixConvention:
    """The `sos:` prefix is a JSON-key string prefix, NOT an XML namespace."""

    def test_string_prefix_language(self, amendment_entry: str) -> None:
        # Phrase: "STRING prefix" appears explicitly.
        assert "STRING prefix" in amendment_entry, (
            "Amendment entry MUST clarify the `sos:` prefix is a STRING "
            "prefix (not an XML namespace prefix)."
        )

    def test_not_an_xml_namespace_prefix(
        self, amendment_entry: str
    ) -> None:
        # "NOT an XML namespace prefix" or equivalent disclaimer.
        assert "NOT an XML namespace prefix" in amendment_entry, (
            "Amendment entry MUST disclaim the `sos:` prefix as NOT an "
            "XML namespace prefix."
        )

    def test_example_uses_sos_prefixed_json_key(
        self, amendment_entry: str
    ) -> None:
        # Example: "sos:kind": "status"
        assert '"sos:kind": "status"' in amendment_entry, (
            "Amendment entry MUST contain an example using the "
            '`"sos:kind": "status"` JSON-key convention.'
        )

    def test_example_uses_sos_dir(self, amendment_entry: str) -> None:
        assert '"sos:dir"' in amendment_entry, (
            "Amendment entry MUST contain a `\"sos:dir\"` JSON-key example."
        )

    def test_example_uses_sos_mutex(self, amendment_entry: str) -> None:
        assert '"sos:mutex"' in amendment_entry, (
            "Amendment entry MUST contain a `\"sos:mutex\"` JSON-key "
            "example."
        )

    def test_example_uses_sos_protection_zone(
        self, amendment_entry: str
    ) -> None:
        assert '"sos:protection-zone"' in amendment_entry, (
            "Amendment entry MUST contain a `\"sos:protection-zone\"` "
            "JSON-key example."
        )

    def test_no_xmlns_sos_declaration_in_examples(
        self, amendment_entry: str
    ) -> None:
        # The amended example MUST NOT declare `xmlns:sos="..."` on the
        # host element. The amendment entry as a whole MAY mention the
        # string `xmlns:sos` in the retraction context, but the example
        # block (the ```...``` fence) MUST be free of an xmlns:sos=
        # attribute.
        fence_match = re.search(
            r"```\s*\n(.*?)```",
            amendment_entry,
            re.DOTALL,
        )
        assert fence_match is not None, (
            "Amendment entry MUST contain a fenced XML example."
        )
        example_body = fence_match.group(1)
        assert "xmlns:sos" not in example_body, (
            "The amended XML example MUST NOT contain `xmlns:sos=` — the "
            "`sos:` prefix lives inside the `other_attributes` JSON, not "
            "as an XML namespace declaration."
        )


# ---------------------------------------------------------------------------
# Amendment entry — scope clarification (carve-out for SOS-08-D / -E)
# ---------------------------------------------------------------------------


class TestScopeClarification:
    """The amendment scope is SOS-09 channel ANNOTATIONS only."""

    def test_scope_clarification_section(
        self, amendment_entry: str
    ) -> None:
        assert "**Scope clarification" in amendment_entry, (
            "Amendment entry MUST carry a **Scope clarification** section."
        )

    def test_annotations_only_language(self, amendment_entry: str) -> None:
        assert "channel ANNOTATIONS only" in amendment_entry, (
            "Scope clarification MUST say 'channel ANNOTATIONS only'."
        )

    def test_carves_out_sos_08_d(self, amendment_entry: str) -> None:
        assert "SOS-08-D" in amendment_entry, (
            "Scope clarification MUST carve out SOS-08-D namespaced "
            "ELEMENTS as not amended."
        )

    def test_carves_out_sos_08_e(self, amendment_entry: str) -> None:
        assert "SOS-08-E" in amendment_entry, (
            "Scope clarification MUST carve out SOS-08-E namespaced "
            "ELEMENTS as not amended."
        )

    @pytest.mark.parametrize(
        "element",
        [
            "<sos:cross_invariant>",
            "<sos:clock_domains>",
            "<sos:shared_signal>",
        ],
    )
    def test_carves_out_named_namespaced_elements(
        self, amendment_entry: str, element: str
    ) -> None:
        assert element in amendment_entry, (
            f"Scope clarification MUST name the SOS-08-D / -E namespaced "
            f"element `{element}` in the carve-out list."
        )

    def test_element_vs_attribute_distinction_preserved(
        self, amendment_entry: str
    ) -> None:
        assert "element-vs-attribute distinction" in amendment_entry, (
            "Scope clarification MUST explicitly preserve the "
            "element-vs-attribute distinction."
        )


# ---------------------------------------------------------------------------
# Amendment entry — rationale (quoting the original staging-recommendation)
# ---------------------------------------------------------------------------


class TestRationale:
    """The amendment quotes the four original 2026-05-23 staging rationale points."""

    def test_rationale_section_present(self, amendment_entry: str) -> None:
        assert "**Rationale**" in amendment_entry, (
            "Amendment entry MUST carry a **Rationale** section."
        )

    def test_scjson_round_trip_preserved(
        self, amendment_entry: str
    ) -> None:
        assert "scjson round-trip" in amendment_entry, (
            "Rationale MUST cite the scjson round-trip preservation."
        )

    def test_off_the_namespace_registration_hook(
        self, amendment_entry: str
    ) -> None:
        assert "namespace-registration hook" in amendment_entry, (
            "Rationale MUST cite keeping SOS off the namespace-registration "
            "hook."
        )

    def test_position_x_y_precedent_cited(
        self, amendment_entry: str
    ) -> None:
        assert "position_x" in amendment_entry and "position_y" in amendment_entry, (
            "Rationale MUST cite the existing iState `position_x` / "
            "`position_y` precedent."
        )


# ---------------------------------------------------------------------------
# Amendment entry — implementation impact + authority + tracking
# ---------------------------------------------------------------------------


class TestImplementationImpact:
    """Implementation-impact paragraph covers no-code-retraction + future-emit obligation."""

    def test_implementation_impact_section(
        self, amendment_entry: str
    ) -> None:
        assert "**Implementation impact.**" in amendment_entry, (
            "Amendment entry MUST carry an **Implementation impact.** section."
        )

    def test_no_code_retraction_needed(self, amendment_entry: str) -> None:
        # "No code retraction is needed" or "implementation has not begun".
        assert (
            "implementation has not begun" in amendment_entry
            or "No code retraction" in amendment_entry
        ), (
            "Implementation-impact section MUST state that SOS-09 "
            "implementation has not begun (no code retraction needed)."
        )

    def test_future_emit_path_must_read_other_attributes(
        self, amendment_entry: str
    ) -> None:
        # The future emit path MUST read channel annotations from
        # other_attributes.
        assert "MUST read channel annotations from `other_attributes`" in amendment_entry, (
            "Implementation-impact section MUST instruct the future "
            "emit path to read annotations from `other_attributes`."
        )


class TestAuthority:
    """Authority section uses `own` + `compose` AuthorityRelationship values."""

    def test_authority_section(self, amendment_entry: str) -> None:
        assert "**Authority.**" in amendment_entry, (
            "Amendment entry MUST carry an **Authority.** section."
        )

    def test_authority_relationship_own(
        self, amendment_entry: str
    ) -> None:
        assert "`own`" in amendment_entry, (
            "Authority section MUST declare `own` for the channel-annotation "
            "key convention."
        )

    def test_authority_relationship_compose(
        self, amendment_entry: str
    ) -> None:
        assert "`compose`" in amendment_entry, (
            "Authority section MUST declare `compose` for the relationship "
            "to iState's `other_attributes` surface."
        )


class TestTracking:
    """Tracking block cites the test module and §16 row marker."""

    def test_tracking_section_present(self, amendment_entry: str) -> None:
        assert "**Tracking.**" in amendment_entry, (
            "Amendment entry MUST carry a **Tracking.** section."
        )

    def test_test_module_path_cited(self, amendment_entry: str) -> None:
        assert (
            "tools/sos-codegen/tests/test_sos_09_pcdn_001_amendment.py"
            in amendment_entry
        ), (
            "Tracking section MUST cite the test module path."
        )


# ---------------------------------------------------------------------------
# Ratification-table row — superseded marker
# ---------------------------------------------------------------------------


class TestRatificationTableSupersededMarker:
    """The 2026-05-23 ratification row PCDN-001 cell has a superseded marker."""

    def test_superseded_marker_present(
        self, ratification_2026_05_23: str
    ) -> None:
        # The row's resolution cell now ends with the superseded note.
        assert (
            "🟡 superseded 2026-05-25"
            in ratification_2026_05_23
        ), (
            "2026-05-23 ratification row PCDN-001 MUST carry a "
            "🟡 superseded 2026-05-25 marker."
        )

    def test_original_resolution_preserved(
        self, ratification_2026_05_23: str
    ) -> None:
        # Per spec-before-code discipline: original resolution text is
        # preserved as institutional memory.
        assert (
            'Custom `xmlns:sos="https://softoboros.com/sos/1.0"`'
            in ratification_2026_05_23
        ), (
            "Original 2026-05-23 PCDN-001 resolution text MUST be "
            "preserved as institutional memory (not deleted)."
        )

    def test_points_at_amendment_entry(
        self, ratification_2026_05_23: str
    ) -> None:
        assert "amendment entry below" in ratification_2026_05_23, (
            "Superseded marker SHOULD direct the reader to the amendment "
            "change-log entry."
        )


# ---------------------------------------------------------------------------
# PCDN-001 entry (PCDNs section) — amended status marker
# ---------------------------------------------------------------------------


class TestPcdn001PendingEntryMarker:
    """The PCDN-SOS-09-001 entry in the PCDNs section carries an amended marker."""

    def test_amended_status_present(
        self, pcdn_001_pending_entry: str
    ) -> None:
        assert "🟢 amended 2026-05-25" in pcdn_001_pending_entry, (
            "PCDN-SOS-09-001 entry in the PCDNs section MUST carry a "
            "🟢 amended 2026-05-25 status marker."
        )

    def test_original_pcdn_text_preserved(
        self, pcdn_001_pending_entry: str
    ) -> None:
        # Per spec-before-code discipline: original PCDN narrative
        # stays intact alongside the new marker.
        assert (
            "Custom XML namespace" in pcdn_001_pending_entry
            and "leveraging the iState `other_attributes`"
            in pcdn_001_pending_entry
        ), (
            "Original PCDN-SOS-09-001 narrative MUST be preserved alongside "
            "the new status marker (not deleted)."
        )

    def test_points_at_change_log_amendment(
        self, pcdn_001_pending_entry: str
    ) -> None:
        assert (
            "change-log amendment" in pcdn_001_pending_entry
            or "amendment entry below" in pcdn_001_pending_entry
        ), (
            "PCDN-SOS-09-001 status marker SHOULD point at the change-log "
            "amendment entry."
        )


# ---------------------------------------------------------------------------
# Whole-doc scan — no `xmlns:sos` in chart-author-facing XML
# ---------------------------------------------------------------------------


class TestWholeDocXmlnsScan:
    """No `xmlns:sos` declaration appears in chart-author-facing XML."""

    def test_no_xmlns_sos_in_xml_fences(
        self, concepts_text: str
    ) -> None:
        # Iterate every ```...``` fenced block in the doc; assert none
        # contains an `xmlns:sos=` declaration anywhere in its body.
        # The retraction quotation in the amendment narrative is in
        # prose, NOT inside a fenced code block, so it is exempt.
        for fence_body in re.findall(r"```.*?\n(.*?)```", concepts_text, re.DOTALL):
            assert "xmlns:sos" not in fence_body, (
                "No fenced XML example in SOS-09-CONCEPTS.md may contain "
                "`xmlns:sos` — chart-author-facing XML examples MUST use "
                "the `other_attributes` JSON convention per the 2026-05-25 "
                "amendment."
            )

    def test_softoboros_url_not_used_as_working_namespace(
        self, concepts_text: str
    ) -> None:
        # The URL `https://softoboros.com/sos/1.0` MAY appear in the
        # retraction quotation (as the URL being retracted), in the
        # 2026-05-23 ratification row (as the original superseded
        # resolution), and in the PCDN-SOS-09-001 entry (as the original
        # PCDN text and as the explicit retraction marker). It MUST NOT
        # appear as a working namespace declaration anywhere — i.e.
        # outside those documented retraction/historical contexts.
        # We assert it does NOT appear as `xmlns:sos="https://softoboros.com/sos/1.0"`
        # inside any fenced XML example.
        pattern = re.compile(
            r'xmlns:sos\s*=\s*"https://softoboros\.com/sos/1\.0"'
        )
        for fence_body in re.findall(r"```.*?\n(.*?)```", concepts_text, re.DOTALL):
            assert pattern.search(fence_body) is None, (
                "The URL `https://softoboros.com/sos/1.0` MUST NOT appear "
                "as a working `xmlns:sos=` namespace declaration inside any "
                "fenced XML example in SOS-09-CONCEPTS.md."
            )


# ---------------------------------------------------------------------------
# Frozen-enumeration registration policy
# ---------------------------------------------------------------------------


class TestRegistrationPolicy:
    """Standards Action declared for the four-attribute set."""

    def test_standards_action_declared(
        self, amendment_entry: str
    ) -> None:
        assert "Standards Action" in amendment_entry, (
            "Amendment entry MUST declare Standards Action registration "
            "policy for the four-attribute set."
        )
