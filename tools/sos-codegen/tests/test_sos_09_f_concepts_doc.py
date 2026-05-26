"""SOS-09-F concepts-doc structural assertions.

@spec  docs/concepts/SOS-09-F-CONCEPTS.md (Membrane vectors sub-phase,
       drafted 2026-05-26)
@spec  docs/concepts/SOS-09-CONCEPTS.md §6 SOS-09-F summary;
       §7 INV-S-MEM-1 through 6 — umbrella invariants SOS-09-F cites;
       PCDN-SOS-09-005 (cocotb + Python CPU stub) — ratified at umbrella.
@spec  docs/concepts/SOS-09-A-CONCEPTS.md §5.2 — `sos:id` (UUID) and
       `sos:name` (SV-identifier) identity/name split per PCDN-SOS-09-A-003
       ratification 2026-05-25.
@spec  docs/concepts/SOS-09-B-CONCEPTS.md — CMSIS-SVD register surface
       SOS-09-F enumerates from.
@spec  docs/concepts/SOS-09-G-CONCEPTS.md — `sos_mpu_install()` runtime
       hook SOS-09-F protection vectors invoke during harness setup.
@spec  docs/concepts/SOS-03-CONCEPTS.md — base vector framework SOS-09-F
       adapts via SOS-03 §15 amendment.
@spec  docs/concepts/SOS-08-D-CONCEPTS.md — cocotb HDL framework SOS-09-F
       composes with via the membrane-vector adapter layer.
@spec  Parent CLAUDE.md "Spec-Before-Code Planning Discipline /
       Phase document shape" — §0..§16 section layout precedent
       (SOS-08-A / SOS-09-A / SOS-09-B / SOS-09-G as reference shapes).

This module verifies the SOS-09-F-CONCEPTS.md doc is structurally sound:

  - Required sections §0..§16 present.
  - Status banner is 🟡 DRAFT 2026-05-26.
  - §5 names all six vector families.
  - §5 declares the `MembraneVector` four-method protocol.
  - §5 declares the `MV-<UUID>-<family>-<seq>` traceability key shape.
  - §5 names cocotb + Python CPU stub as the v1 harness.
  - §5 declares the failure-message vocabulary with the chart-trace UUID.
  - §5 declares the atomicity cocotb coroutine pair model.
  - §6 declares INV-S-MEM-F-1 through INV-S-MEM-F-6 (all six).
  - §15 files five PCDNs PCDN-SOS-09-F-001..005 with 🟡 PENDING status.
  - §8 cites cocotb (`derive`), SOS-03 (`adapt`), SOS-08-D (`compose`),
    SOS-09-A/B/E/G as upstream relationships.
  - §16 awaits ratification (empty resolution log, dated draft entry).
  - The doc cites RFC 4122 + UUID + sos:id + sos:name (traceability shape).
  - All six vector families enumerated textually.
  - cocotb textually present.

@invariants  INV-SOS-B (vectors-as-deliverable) — load-bearing for this
             sub-phase; vectors ARE the integration contract.
@invariants  INV-SOS-H (vector-to-chart traceability) — failure
             rendering vocabulary cites chart `sos:name` + `sos:id` UUID.
@invariants  INV-S-MEM-F-1 through F-6 declared in this doc's §6.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Repo-root resolution: this test file lives at
# tools/sos-codegen/tests/test_sos_09_f_concepts_doc.py
# → repo root is three parents up.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DOC_PATH = _REPO_ROOT / "docs" / "concepts" / "SOS-09-F-CONCEPTS.md"


@pytest.fixture(scope="module")
def doc_text() -> str:
    if not _DOC_PATH.exists():
        pytest.fail(f"SOS-09-F concepts doc missing at {_DOC_PATH}")
    return _DOC_PATH.read_text(encoding="utf-8")


def _section_slice(text: str, section_num: int) -> str:
    """Return body of `## <N>.` heading through to the next `## ` heading."""
    pattern = re.compile(
        rf"^## {section_num}\..*?(?=^## \d+\.|\Z)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(text)
    if match is None:
        return ""
    return match.group(0)


# ---------------------------------------------------------------------------
# Existence + section presence
# ---------------------------------------------------------------------------


class TestDocExists:
    """The doc exists and carries the expected top-level heading."""

    def test_doc_present(self) -> None:
        assert _DOC_PATH.exists(), (
            f"Expected SOS-09-F concepts doc at {_DOC_PATH}."
        )

    def test_top_level_heading(self, doc_text: str) -> None:
        assert doc_text.startswith("# SOS-09-F"), (
            "Doc MUST begin with `# SOS-09-F` top-level heading."
        )

    def test_top_level_heading_names_membrane_vectors(
        self, doc_text: str
    ) -> None:
        first_line = doc_text.splitlines()[0]
        assert "Membrane vectors" in first_line, (
            "Top-of-file heading MUST name the SOS-09-F sub-phase "
            "as 'Membrane vectors'."
        )

    def test_status_draft_banner(self, doc_text: str) -> None:
        # The doc is a DRAFT awaiting PCDN walkthrough — must carry
        # the 🟡 DRAFT status badge at top of file.
        head = doc_text.split("## 0.", 1)[0]
        assert "🟡" in head, (
            "Doc top-of-file MUST carry a 🟡 status marker (draft)."
        )
        assert "DRAFT" in head, (
            "Doc top-of-file MUST carry a DRAFT status banner."
        )
        assert "2026-05-26" in head, (
            "Doc top-of-file MUST carry the 2026-05-26 draft date."
        )


class TestRequiredSections:
    """Sections §0..§16 present (per Spec-Before-Code phase document shape)."""

    @pytest.mark.parametrize(
        "section_num,heading_text",
        [
            (0, "Authority policy"),
            (1, "Purpose"),
            (2, "Problem statement"),
            (3, "Canonical glossary"),
            (4, "Source-of-truth map"),
            (5, "Frozen decisions"),
            (6, "invariants"),  # cross-sub-phase invariants
            (7, "Enumeration"),  # enumeration policies recap
            (8, "Standards integration"),
            (10, "Reconciliation"),
            (11, "Non-goals"),
            (12, "Acceptance checklist"),
            (13, "Files cited"),
            (14, "Unblocks"),
            (15, "Pending Concept Decision Notices"),
            (16, "Ratification"),  # ratification log
        ],
    )
    def test_section_present(
        self, doc_text: str, section_num: int, heading_text: str
    ) -> None:
        pattern = re.compile(
            rf"^## {section_num}\.\s+.*$", re.MULTILINE
        )
        headings = pattern.findall(doc_text)
        assert headings, (
            f"Doc MUST carry a `## {section_num}.` section heading."
        )
        keyword = heading_text.lower()
        found = any(keyword in h.lower() for h in headings)
        assert found, (
            f"Section {section_num} heading SHOULD reference the keyword "
            f"`{heading_text}` (case-insensitive). Found: {headings}"
        )


# ---------------------------------------------------------------------------
# §5 frozen decisions — vector family enumeration
# ---------------------------------------------------------------------------


class TestSection5VectorFamilies:
    """§5.1 names all six vector families."""

    @pytest.mark.parametrize(
        "family",
        [
            "initial_value",
            "write_then_read",
            "side_effect",
            "clear_on_read",
            "atomicity",
            "protection",
        ],
    )
    def test_family_present(self, doc_text: str, family: str) -> None:
        section5 = _section_slice(doc_text, 5)
        assert family in section5, (
            f"§5 MUST name vector family `{family}` "
            f"(one of the six §5.1 frozen families)."
        )

    def test_family_enumeration_block_present(self, doc_text: str) -> None:
        section5 = _section_slice(doc_text, 5)
        # The §5.1 frozen enum: `vector_family ∈ { ... }` shape.
        assert "vector_family" in section5, (
            "§5.1 MUST declare a `vector_family` frozen enumeration."
        )

    def test_family_count_at_least_six(self, doc_text: str) -> None:
        section5 = _section_slice(doc_text, 5)
        families = {
            "initial_value",
            "write_then_read",
            "side_effect",
            "clear_on_read",
            "atomicity",
            "protection",
        }
        found = {f for f in families if f in section5}
        assert len(found) == 6, (
            f"§5 MUST enumerate all six vector families; found {found}."
        )

    def test_family_kind_applicability_table(self, doc_text: str) -> None:
        section5 = _section_slice(doc_text, 5)
        # §5.1 table — channel kind → applicable families.
        assert "Channel `kind`" in section5 or "channel kind" in section5.lower(), (
            "§5.1 MUST declare the channel-kind → applicable-families "
            "table."
        )


# ---------------------------------------------------------------------------
# §5 frozen decisions — vector adapter shape (four-method protocol)
# ---------------------------------------------------------------------------


class TestSection5VectorAdapter:
    """§5.2 names the `MembraneVector` four-method protocol."""

    def test_membrane_vector_base_class_named(self, doc_text: str) -> None:
        section5 = _section_slice(doc_text, 5)
        assert "MembraneVector" in section5, (
            "§5.2 MUST name the `MembraneVector` base class."
        )

    @pytest.mark.parametrize(
        "method", ["setup", "stimulate", "observe", "assert_invariants"]
    )
    def test_adapter_method_present(
        self, doc_text: str, method: str
    ) -> None:
        section5 = _section_slice(doc_text, 5)
        assert method in section5, (
            f"§5.2 MUST name the `{method}` method of the vector adapter."
        )

    def test_harness_binding_forms_listed(self, doc_text: str) -> None:
        section5 = _section_slice(doc_text, 5)
        # The three harness forms are cocotb+stub, real-hw-loopback,
        # ISS; the latter two are deferred. The shape must list cocotb
        # as the v1 binding.
        assert "cocotb" in section5.lower(), (
            "§5.2 MUST name cocotb as the v1 harness binding."
        )


# ---------------------------------------------------------------------------
# §5 frozen decisions — traceability key format
# ---------------------------------------------------------------------------


class TestSection5TraceabilityKey:
    """§5.3 declares the `MV-<UUID>-<family>-<seq>` key shape."""

    def test_trace_key_format_shape(self, doc_text: str) -> None:
        section5 = _section_slice(doc_text, 5)
        # The literal MV- prefix.
        assert "MV-" in section5, (
            "§5.3 MUST declare the `MV-` traceability key prefix."
        )

    def test_uuid_rooted_identifier(self, doc_text: str) -> None:
        section5 = _section_slice(doc_text, 5)
        assert "UUID" in section5, (
            "§5.3 MUST declare the UUID-rooted traceability key."
        )

    def test_rename_preserves_traceability(self, doc_text: str) -> None:
        section5 = _section_slice(doc_text, 5)
        # Per PCDN-SOS-09-A-003, sos:name rename preserves trace.
        assert "rename" in section5.lower(), (
            "§5.3 MUST explain that `sos:name` rename preserves "
            "traceability (UUID-rooted)."
        )

    def test_pcdn_a_003_cited(self, doc_text: str) -> None:
        # The identity/name split per PCDN-SOS-09-A-003 is load-bearing.
        assert "PCDN-SOS-09-A-003" in doc_text, (
            "Doc MUST cite PCDN-SOS-09-A-003 (UUID identity vs SV-identifier "
            "name split) as the basis for the traceability key shape."
        )


# ---------------------------------------------------------------------------
# §5 frozen decisions — co-simulation harness
# ---------------------------------------------------------------------------


class TestSection5Harness:
    """§5.4 names cocotb + Python CPU stub as the v1 harness."""

    def test_cocotb_named(self, doc_text: str) -> None:
        section5 = _section_slice(doc_text, 5)
        assert "cocotb" in section5, (
            "§5.4 MUST name cocotb as the v1 co-simulation framework."
        )

    def test_python_cpu_stub_named(self, doc_text: str) -> None:
        section5 = _section_slice(doc_text, 5)
        assert "Python CPU stub" in section5 or "Python CPU-stub" in section5, (
            "§5.4 MUST name the `Python CPU stub` v1 SW-side model."
        )

    def test_stub_primitives_listed(self, doc_text: str) -> None:
        section5 = _section_slice(doc_text, 5)
        # Core primitives bus.read, bus.write, wait_irq.
        assert "bus.read" in section5, (
            "§5.4 MUST name the `bus.read` primitive."
        )
        assert "bus.write" in section5, (
            "§5.4 MUST name the `bus.write` primitive."
        )
        assert "wait_irq" in section5, (
            "§5.4 MUST name the `wait_irq` primitive."
        )

    def test_pcdn_005_cited(self, doc_text: str) -> None:
        # Per PCDN-SOS-09-005 (umbrella-ratified): cocotb + Python CPU stub.
        assert "PCDN-SOS-09-005" in doc_text, (
            "Doc MUST cite PCDN-SOS-09-005 (umbrella-ratified harness "
            "choice) as the basis for the cocotb + Python CPU stub harness."
        )


# ---------------------------------------------------------------------------
# §5 frozen decisions — JUnit XML report
# ---------------------------------------------------------------------------


class TestSection5Report:
    """§5.5 names JUnit XML as the report format."""

    def test_junit_xml_named(self, doc_text: str) -> None:
        section5 = _section_slice(doc_text, 5)
        assert "JUnit" in section5 and "XML" in section5, (
            "§5.5 MUST name `JUnit XML` as the report format."
        )

    def test_ci_consumer_referenced(self, doc_text: str) -> None:
        section5 = _section_slice(doc_text, 5)
        assert "CI" in section5, (
            "§5.5 MUST reference CI consumption of the report."
        )


# ---------------------------------------------------------------------------
# §5 frozen decisions — failure-rendering vocabulary
# ---------------------------------------------------------------------------


class TestSection5FailureVocabulary:
    """§5.6 declares the chart-vocabulary failure-message shape."""

    def test_failure_message_template_shape(self, doc_text: str) -> None:
        section5 = _section_slice(doc_text, 5)
        # The shape must reference sos:name + chart trace UUID.
        assert "sos:name" in section5, (
            "§5.6 MUST reference `sos:name` in the failure-message shape."
        )
        assert "chart trace" in section5.lower() or "sos:id" in section5, (
            "§5.6 MUST reference the chart-trace UUID (sos:id) in "
            "the failure-message shape."
        )

    def test_failure_message_names_channel_kind(self, doc_text: str) -> None:
        section5 = _section_slice(doc_text, 5)
        assert "kind" in section5.lower(), (
            "§5.6 failure-message shape MUST name the channel `kind`."
        )

    def test_failure_message_names_channel_zone(self, doc_text: str) -> None:
        section5 = _section_slice(doc_text, 5)
        assert "zone" in section5.lower(), (
            "§5.6 failure-message shape MUST name the protection `zone`."
        )


# ---------------------------------------------------------------------------
# §5 frozen decisions — atomicity concurrent-stimulus model
# ---------------------------------------------------------------------------


class TestSection5Atomicity:
    """§5.7 names the atomicity vector concurrent-stimulus model."""

    def test_coroutine_pair_named(self, doc_text: str) -> None:
        section5 = _section_slice(doc_text, 5)
        assert "coroutine" in section5.lower(), (
            "§5.7 MUST name cocotb coroutines as the atomicity "
            "concurrent-stimulus model."
        )

    def test_mutex_serialisation_named(self, doc_text: str) -> None:
        section5 = _section_slice(doc_text, 5)
        assert "mutex" in section5.lower(), (
            "§5.7 MUST name `sos_mutex` serialisation as the "
            "atomicity-vector assertion."
        )

    def test_no_torn_read_named(self, doc_text: str) -> None:
        section5 = _section_slice(doc_text, 5)
        assert "torn read" in section5.lower(), (
            "§5.7 MUST assert no torn read as the atomicity invariant."
        )


# ---------------------------------------------------------------------------
# §5 — registration policies are declared per frozen decision
# ---------------------------------------------------------------------------


class TestSection5RegistrationPolicies:
    """Each §5.x frozen decision declares its registration policy."""

    def test_standards_action_present(self, doc_text: str) -> None:
        section5 = _section_slice(doc_text, 5)
        assert "Standards Action" in section5, (
            "§5 MUST declare at least one frozen decision with "
            "**Standards Action** registration policy."
        )

    def test_specification_required_present(self, doc_text: str) -> None:
        section5 = _section_slice(doc_text, 5)
        assert "Specification Required" in section5, (
            "§5 MUST declare at least one frozen decision with "
            "**Specification Required** registration policy."
        )


# ---------------------------------------------------------------------------
# §6 cross-sub-phase invariants — INV-S-MEM-F-1 through INV-S-MEM-F-6
# ---------------------------------------------------------------------------


class TestSection6Invariants:
    """§6 declares INV-S-MEM-F-1 through 6."""

    def test_invariant_count_at_least_six(self, doc_text: str) -> None:
        section6 = _section_slice(doc_text, 6)
        invariants = set(re.findall(r"INV-S-MEM-F-\d+", section6))
        assert len(invariants) >= 6, (
            f"§6 MUST declare at least 6 INV-S-MEM-F-N invariants; "
            f"found {len(invariants)} unique: {sorted(invariants)}."
        )

    @pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 6])
    def test_specific_invariant_present(self, doc_text: str, n: int) -> None:
        section6 = _section_slice(doc_text, 6)
        assert f"INV-S-MEM-F-{n}" in section6, (
            f"§6 MUST declare INV-S-MEM-F-{n}."
        )

    def test_invariant_2_chart_vocabulary(self, doc_text: str) -> None:
        # INV-S-MEM-F-2: failure messages name chart sos:name + UUID.
        section6 = _section_slice(doc_text, 6)
        f2_match = re.search(
            r"INV-S-MEM-F-2.*?(?=INV-S-MEM-F-3|\Z)",
            section6,
            re.DOTALL,
        )
        assert f2_match is not None, "INV-S-MEM-F-2 body MUST be present."
        f2_body = f2_match.group(0)
        assert "sos:name" in f2_body or "sos:id" in f2_body, (
            "INV-S-MEM-F-2 MUST name `sos:name` or `sos:id` (chart "
            "vocabulary requirement)."
        )

    def test_invariant_5_protection_event(self, doc_text: str) -> None:
        # INV-S-MEM-F-5: protection vector observes access-violation event.
        section6 = _section_slice(doc_text, 6)
        f5_match = re.search(
            r"INV-S-MEM-F-5.*?(?=INV-S-MEM-F-6|\Z)",
            section6,
            re.DOTALL,
        )
        assert f5_match is not None, "INV-S-MEM-F-5 body MUST be present."
        f5_body = f5_match.group(0)
        assert "access-violation" in f5_body.lower() or "INV-S-MEM-E-5" in f5_body, (
            "INV-S-MEM-F-5 MUST name the access-violation event "
            "(or cite INV-S-MEM-E-5)."
        )

    def test_invariant_6_deterministic(self, doc_text: str) -> None:
        # INV-S-MEM-F-6: harness state deterministic from chart + seed.
        section6 = _section_slice(doc_text, 6)
        f6_match = re.search(
            r"INV-S-MEM-F-6.*?(?=INV-S-MEM-F-7|\Z|\n## )",
            section6,
            re.DOTALL,
        )
        assert f6_match is not None, "INV-S-MEM-F-6 body MUST be present."
        f6_body = f6_match.group(0)
        assert "deterministic" in f6_body.lower(), (
            "INV-S-MEM-F-6 MUST declare deterministic harness state."
        )


# ---------------------------------------------------------------------------
# §8 standards integration matrix additions
# ---------------------------------------------------------------------------


class TestSection8Standards:
    """§8 cites cocotb, SOS-03, SOS-08-D, SOS-09-A/B/E/G."""

    def test_cocotb_derive_row(self, doc_text: str) -> None:
        section8 = _section_slice(doc_text, 8)
        assert "cocotb" in section8, "§8 MUST include a row for cocotb."

    def test_sos_03_adapt_relationship(self, doc_text: str) -> None:
        section8 = _section_slice(doc_text, 8)
        assert "SOS-03" in section8, (
            "§8 MUST cite SOS-03 (base vector framework)."
        )
        assert "**adapt**" in section8, (
            "§8 MUST declare at least one **adapt** relationship "
            "(SOS-03 base vector framework)."
        )

    def test_sos_08_d_compose_relationship(self, doc_text: str) -> None:
        section8 = _section_slice(doc_text, 8)
        assert "SOS-08-D" in section8, (
            "§8 MUST cite SOS-08-D (cocotb HDL framework)."
        )
        assert "**compose**" in section8, (
            "§8 MUST declare at least one **compose** relationship "
            "(SOS-08-D cocotb framework or SOS-09-G install hook)."
        )

    def test_sos_09_a_mirror_relationship(self, doc_text: str) -> None:
        section8 = _section_slice(doc_text, 8)
        assert "SOS-09-A" in section8, (
            "§8 MUST cite SOS-09-A (chart annotation surface)."
        )
        assert "**mirror**" in section8, (
            "§8 MUST declare at least one **mirror** relationship "
            "(SOS-09-A annotation schema consumption)."
        )

    def test_sos_09_b_cited(self, doc_text: str) -> None:
        section8 = _section_slice(doc_text, 8)
        assert "SOS-09-B" in section8, (
            "§8 MUST cite SOS-09-B (CMSIS-SVD register surface)."
        )

    def test_sos_09_e_cited(self, doc_text: str) -> None:
        section8 = _section_slice(doc_text, 8)
        assert "SOS-09-E" in section8, (
            "§8 MUST cite SOS-09-E (access-violation event source)."
        )

    def test_sos_09_g_cited(self, doc_text: str) -> None:
        section8 = _section_slice(doc_text, 8)
        assert "SOS-09-G" in section8, (
            "§8 MUST cite SOS-09-G (MPU configuration via sos_mpu_install)."
        )

    def test_at_least_one_authority_relationship_row(
        self, doc_text: str
    ) -> None:
        section8 = _section_slice(doc_text, 8)
        # The seven AuthorityRelationship values per SOS-07 §7.
        relationships = [
            "**mirror**",
            "**adapt**",
            "**extend**",
            "**compose**",
            "**own**",
            "**derive**",
            "**represent**",
        ]
        found = [r for r in relationships if r in section8]
        assert len(found) >= 1, (
            "§8 MUST declare at least one AuthorityRelationship row; "
            f"found none of {relationships}."
        )


# ---------------------------------------------------------------------------
# §15 PCDNs — five PCDNs filed with 🟡 PENDING status
# ---------------------------------------------------------------------------


class TestSection15PCDNs:
    """§15 files PCDN-SOS-09-F-001..005 with 🟡 PENDING status."""

    def test_pcdn_count_at_least_five(self, doc_text: str) -> None:
        section15 = _section_slice(doc_text, 15)
        pcdn_ids = set(re.findall(r"PCDN-SOS-09-F-\d{3}", section15))
        assert len(pcdn_ids) >= 5, (
            f"§15 MUST file at least 5 PCDNs; "
            f"found {len(pcdn_ids)} unique: {sorted(pcdn_ids)}."
        )

    @pytest.mark.parametrize(
        "pcdn_id",
        [
            "PCDN-SOS-09-F-001",
            "PCDN-SOS-09-F-002",
            "PCDN-SOS-09-F-003",
            "PCDN-SOS-09-F-004",
            "PCDN-SOS-09-F-005",
        ],
    )
    def test_specific_pcdn_filed(self, doc_text: str, pcdn_id: str) -> None:
        section15 = _section_slice(doc_text, 15)
        assert pcdn_id in section15, (
            f"§15 MUST file {pcdn_id}."
        )

    def test_pcdns_carry_pending_status(self, doc_text: str) -> None:
        section15 = _section_slice(doc_text, 15)
        pending_count = section15.count("🟡")
        pcdn_ids = set(re.findall(r"PCDN-SOS-09-F-\d{3}", section15))
        assert pending_count >= len(pcdn_ids), (
            f"Every PCDN MUST carry a 🟡 PENDING status marker; "
            f"found {pending_count} 🟡 markers for {len(pcdn_ids)} PCDNs."
        )

    def test_pcdns_carry_pending_date(self, doc_text: str) -> None:
        section15 = _section_slice(doc_text, 15)
        # The pending walkthrough is marked with the 2026-05-26 date.
        assert "PENDING USER WALKTHROUGH 2026-05-26" in section15, (
            "§15 PCDNs MUST carry the `PENDING USER WALKTHROUGH "
            "2026-05-26` status marker."
        )

    def test_pcdns_carry_recommendation(self, doc_text: str) -> None:
        section15 = _section_slice(doc_text, 15)
        recommendation_count = section15.count("**Recommendation**")
        pcdn_ids = set(re.findall(r"PCDN-SOS-09-F-\d{3}", section15))
        assert recommendation_count >= len(pcdn_ids), (
            f"Every PCDN SHOULD carry a **Recommendation**: line; "
            f"found {recommendation_count} recommendations for "
            f"{len(pcdn_ids)} PCDNs."
        )


# ---------------------------------------------------------------------------
# §16 ratification log — awaits ratification, empty resolution
# ---------------------------------------------------------------------------


class TestSection16Ratification:
    """§16 awaits ratification (empty resolution log)."""

    def test_section_16_present(self, doc_text: str) -> None:
        section16 = _section_slice(doc_text, 16)
        assert len(section16) > 50, (
            "§16 MUST be present with at least the draft-entry text."
        )

    def test_awaits_ratification_noted(self, doc_text: str) -> None:
        section16 = _section_slice(doc_text, 16)
        assert (
            "awaiting" in section16.lower()
            or "awaits ratification" in section16.lower()
        ), (
            "§16 MUST note that the doc awaits ratification."
        )

    def test_initial_draft_entry_dated(self, doc_text: str) -> None:
        section16 = _section_slice(doc_text, 16)
        assert "2026-05-26" in section16, (
            "§16 MUST carry a 2026-05-26 dated initial-draft entry."
        )

    def test_no_ratified_table_yet(self, doc_text: str) -> None:
        # Before PCDN walkthrough, no PCDN should be marked ratified
        # (no 🟢 in section 16 ratification table — the head of file
        # 🟡 marker is in the status banner, not section 16).
        section16 = _section_slice(doc_text, 16)
        # Look for explicit "ratified" status against a PCDN-F-* id;
        # if the user has not walked through, no such pairing exists.
        ratified_pcdn = re.search(
            r"PCDN-SOS-09-F-\d{3}[^\n]*ratified",
            section16,
            re.IGNORECASE,
        )
        assert ratified_pcdn is None, (
            "§16 MUST NOT mark any PCDN as ratified before user "
            "walkthrough; found ratified PCDN-F-* in §16."
        )


# ---------------------------------------------------------------------------
# Cross-phase invariant citations
# ---------------------------------------------------------------------------


class TestCrossPhaseInvariantCitation:
    """Doc cites umbrella invariants per the phase shape."""

    def test_cites_inv_sos_b(self, doc_text: str) -> None:
        # INV-SOS-B (vectors-as-deliverable) is load-bearing.
        assert "INV-SOS-B" in doc_text, (
            "Doc MUST cite INV-SOS-B (vectors-as-deliverable) as the "
            "load-bearing cross-phase invariant for this sub-phase."
        )

    def test_cites_inv_sos_h(self, doc_text: str) -> None:
        # INV-SOS-H (vector-to-chart traceability) is load-bearing for §5.6.
        assert "INV-SOS-H" in doc_text, (
            "Doc MUST cite INV-SOS-H (vector-to-chart traceability) "
            "as backing for the failure-vocabulary."
        )

    def test_cites_inv_s_mem_umbrella(self, doc_text: str) -> None:
        # The umbrella's INV-S-MEM-1..6 are cited.
        umbrella_invs = re.findall(r"INV-S-MEM-\d+", doc_text)
        assert len(umbrella_invs) >= 1, (
            "Doc MUST cite at least one of the SOS-09 umbrella "
            "INV-S-MEM-N invariants."
        )


# ---------------------------------------------------------------------------
# §13 Files cited — upstream sub-phase docs
# ---------------------------------------------------------------------------


class TestFilesCited:
    """§13 cites the umbrella + sibling sub-phase docs."""

    @pytest.mark.parametrize(
        "cited_doc",
        [
            "SOS-09-CONCEPTS.md",
            "SOS-07-CONCEPTS.md",
            "SOS-09-A-CONCEPTS.md",
            "SOS-09-B-CONCEPTS.md",
            "SOS-09-E-CONCEPTS.md",
            "SOS-09-G-CONCEPTS.md",
            "SOS-03-CONCEPTS.md",
            "SOS-08-D-CONCEPTS.md",
        ],
    )
    def test_files_cited_entry(
        self, doc_text: str, cited_doc: str
    ) -> None:
        assert cited_doc in doc_text, (
            f"Doc MUST cite {cited_doc} (Files cited / §13 entry "
            "or inline reference)."
        )


# ---------------------------------------------------------------------------
# PCDN-SOS-09-001 amendment compliance — sos: is a JSON-key prefix
# ---------------------------------------------------------------------------


class TestPCDN001AmendmentCompliance:
    """SOS-09-F honours PCDN-SOS-09-001 amended 2026-05-25.

    The amendment retracted the `xmlns:sos` URL registration; SOS-09-F
    must read `sos:`-prefixed keys from `other_attributes` JSON, not
    from XML namespace prefixes, and must not emit `xmlns:sos` into
    any artifact.
    """

    def test_other_attributes_referenced(self, doc_text: str) -> None:
        assert "other_attributes" in doc_text, (
            "SOS-09-F MUST reference `other_attributes` as the "
            "annotation source (PCDN-SOS-09-001 amended 2026-05-25)."
        )

    def test_no_xmlns_endorsement(self, doc_text: str) -> None:
        # The URL `https://softoboros.com/sos/1.0` MAY appear in
        # historical retraction context only. SOS-09-F MUST NOT
        # endorse it as an emit output declaration.
        if "https://softoboros.com/sos/1.0" in doc_text:
            url_pos = doc_text.find("https://softoboros.com/sos/1.0")
            surrounding = doc_text[max(0, url_pos - 200):url_pos + 200]
            forbidden_endorsement = (
                "xmlns:sos=\"https://softoboros.com/sos/1.0\""
                in surrounding
                and "MUST emit" in surrounding
            )
            assert not forbidden_endorsement, (
                "SOS-09-F MUST NOT endorse `xmlns:sos` URL "
                "registration."
            )


# ---------------------------------------------------------------------------
# UUID + sos:id + sos:name (the traceability key shape)
# ---------------------------------------------------------------------------


class TestTraceabilityShape:
    """The doc carries the UUID + sos:id + sos:name traceability shape."""

    def test_uuid_textually_present(self, doc_text: str) -> None:
        assert "UUID" in doc_text, (
            "Doc MUST mention UUID (the chart `sos:id` shape)."
        )

    def test_rfc_4122_cited(self, doc_text: str) -> None:
        # RFC 4122 owns the UUID canonical form; doc must cite it.
        assert "RFC 4122" in doc_text or "RFC4122" in doc_text, (
            "Doc MUST cite RFC 4122 (UUID canonical form)."
        )

    def test_sos_id_referenced(self, doc_text: str) -> None:
        assert "sos:id" in doc_text, (
            "Doc MUST reference `sos:id` (identity-only chart handle)."
        )

    def test_sos_name_referenced(self, doc_text: str) -> None:
        assert "sos:name" in doc_text, (
            "Doc MUST reference `sos:name` (emission-facing handle)."
        )


# ---------------------------------------------------------------------------
# cocotb textually present + Python CPU stub
# ---------------------------------------------------------------------------


class TestCocotbPresent:
    """The doc names cocotb + Python CPU stub textually."""

    def test_cocotb_present_in_doc(self, doc_text: str) -> None:
        assert "cocotb" in doc_text.lower(), (
            "Doc MUST name cocotb (v1 harness framework per "
            "PCDN-SOS-09-005)."
        )

    def test_python_cpu_stub_present_in_doc(self, doc_text: str) -> None:
        assert (
            "Python CPU stub" in doc_text or "Python CPU-stub" in doc_text
        ), (
            "Doc MUST name the Python CPU stub (v1 SW-side model)."
        )


# ---------------------------------------------------------------------------
# All six vector families enumerated textually anywhere in the doc
# ---------------------------------------------------------------------------


class TestVectorFamiliesTextuallyPresent:
    """The six vector families appear textually in the doc body."""

    @pytest.mark.parametrize(
        "family",
        [
            "initial_value",
            "write_then_read",
            "side_effect",
            "clear_on_read",
            "atomicity",
            "protection",
        ],
    )
    def test_family_in_doc(self, doc_text: str, family: str) -> None:
        assert family in doc_text, (
            f"Vector family `{family}` MUST appear textually in "
            f"the doc body."
        )


# ---------------------------------------------------------------------------
# §12 acceptance checklist — gates (a)..(i)
# ---------------------------------------------------------------------------


class TestSection12AcceptanceChecklist:
    """§12 declares acceptance gates (a)..(i)."""

    @pytest.mark.parametrize(
        "letter",
        ["(a)", "(b)", "(c)", "(d)", "(e)", "(f)", "(g)", "(h)", "(i)"],
    )
    def test_gate_letter_present(
        self, doc_text: str, letter: str
    ) -> None:
        section12 = _section_slice(doc_text, 12)
        assert letter in section12, (
            f"§12 MUST declare acceptance gate {letter}."
        )

    def test_pending_status_on_gates(self, doc_text: str) -> None:
        # All gates carry ⏸ pending status pre-ratification.
        section12 = _section_slice(doc_text, 12)
        pending_count = section12.count("⏸")
        assert pending_count >= 8, (
            f"§12 MUST declare at least 8 gates with ⏸ pending status; "
            f"found {pending_count}."
        )


# ---------------------------------------------------------------------------
# Sub-phase scope clarity — SOS-09-F is the membrane-vectors sub-phase
# ---------------------------------------------------------------------------


class TestSubPhaseScope:
    """Doc identifies itself as the SOS-09-F membrane-vectors sub-phase."""

    def test_umbrella_cited_as_parent(self, doc_text: str) -> None:
        assert "SOS-09-CONCEPTS.md" in doc_text, (
            "Doc MUST cite the SOS-09 umbrella as its parent."
        )

    def test_inv_s_mem_e_5_referenced(self, doc_text: str) -> None:
        # The protection vector observes the SOS-09-E access-violation
        # event surfaced by INV-S-MEM-E-5; doc MUST reference it.
        assert "INV-S-MEM-E-5" in doc_text, (
            "Doc MUST reference INV-S-MEM-E-5 (SOS-09-E's per-channel "
            "access-violation strobe-latch invariant)."
        )

    def test_sos_mpu_install_referenced(self, doc_text: str) -> None:
        # The protection family vector calls SOS-09-G's runtime hook.
        assert "sos_mpu_install" in doc_text, (
            "Doc MUST reference `sos_mpu_install()` (SOS-09-G runtime "
            "hook called during harness setup)."
        )
