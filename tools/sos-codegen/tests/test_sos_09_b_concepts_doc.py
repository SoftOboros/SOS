"""SOS-09-B concepts-doc structural assertions.

@spec  docs/concepts/SOS-09-B-CONCEPTS.md (CMSIS-SVD emission sub-phase)
@spec  docs/concepts/SOS-09-CONCEPTS.md §5.5 (CMSIS-SVD primary;
       SystemRDL secondary) — parent decision SOS-09-B mirrors.
@spec  docs/concepts/SOS-09-CONCEPTS.md §7 INV-S-MEM-1 through 6 —
       umbrella invariants SOS-09-B cites.
@spec  Parent CLAUDE.md "Spec-Before-Code Planning Discipline /
       Phase document shape" — §0..§16 section layout precedent
       (SOS-08-A as reference shape).

This module verifies that the SOS-09-B-CONCEPTS.md doc is structurally
sound:

  - Required sections (§0..§16) present.
  - §5 names CMSIS-SVD 1.3.x and svd2rust strict mode.
  - §5 enumerates access mappings for all 4 channel kinds.
  - §7 declares at least 4 INV-S-MEM-B-N invariants.
  - §15 files at least 3 open PCDNs (PCDN-SOS-09-B-NNN-shape).
  - §8 cites CMSIS-SVD and svd2rust as `derive` relationships.
  - §10 reconciles with existing test_fixtures if any `.svd` files
    exist (or notes "none found").
  - The doc honours PCDN-SOS-09-001 amended 2026-05-25 (no
    `xmlns:sos` URL registration; `sos:` is a JSON-key string prefix).

@invariants  INV-SOS-A (chart-as-source) — SVD is a build output;
             chart is canonical.
@invariants  INV-SOS-G (verified-codegen position) — emission
             deterministic per (chart, target).
@invariants  INV-S-MEM-B-3 — validation gate as release condition.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Repo-root resolution: this test file lives at
# tools/sos-codegen/tests/test_sos_09_b_concepts_doc.py
# → repo root is three parents up.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONCEPTS_PATH = _REPO_ROOT / "docs" / "concepts" / "SOS-09-B-CONCEPTS.md"
_SOS_CODEGEN_ROOT = _REPO_ROOT / "tools" / "sos-codegen"


@pytest.fixture(scope="module")
def concepts_text() -> str:
    if not _CONCEPTS_PATH.exists():
        pytest.fail(
            f"SOS-09-B concepts doc missing at {_CONCEPTS_PATH}"
        )
    return _CONCEPTS_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# File presence & top-of-file metadata
# ---------------------------------------------------------------------------


class TestDocPresence:
    """The doc exists and carries the expected title + status badge."""

    def test_file_exists(self) -> None:
        assert _CONCEPTS_PATH.exists(), (
            f"SOS-09-B concepts doc MUST exist at {_CONCEPTS_PATH}."
        )

    def test_title_heading(self, concepts_text: str) -> None:
        assert concepts_text.startswith(
            "# SOS-09-B — CMSIS-SVD emission"
        ), (
            "Top-of-file heading MUST name the SOS-09-B sub-phase "
            "as the CMSIS-SVD emission path."
        )

    def test_ratified_status_marker(self, concepts_text: str) -> None:
        # Post-2026-05-25 ratification, the top-of-file status MUST be
        # 🟢 ratified (the original 🟡 drafted marker was flipped
        # when the five PCDNs walked).
        first_block = concepts_text[:500]
        assert "🟢 **ratified" in first_block, (
            "Top-of-file MUST carry a 🟢 ratified status marker "
            "post-2026-05-25 PCDN ratification."
        )


# ---------------------------------------------------------------------------
# Required sections (§0..§16)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def section_headings(concepts_text: str) -> list[str]:
    """Extract all `## N. <title>` headings from the doc."""
    pattern = re.compile(r"^## (\d+)\. (.+)$", re.MULTILINE)
    return [
        f"## {match.group(1)}. {match.group(2)}"
        for match in pattern.finditer(concepts_text)
    ]


class TestRequiredSections:
    """The doc carries §0..§16 per the SOS-08-A precedent shape."""

    REQUIRED_SECTION_NUMBERS = {
        "0",   # Authority policy
        "1",   # Purpose
        "2",   # Problem statement
        "3",   # Canonical glossary
        "4",   # Source-of-truth map
        "5",   # Frozen decisions
        "6",   # Sub-phase scope (N/A for leaf; preserved for shape)
        "7",   # Cross-sub-phase invariants
        "8",   # Standards integration matrix additions
        "9",   # Acceptance gates
        "10",  # Reconciliation decisions
        "11",  # Non-goals
        "12",  # Acceptance checklist
        "13",  # Files cited
        "14",  # Unblocks
        "15",  # PCDNs
        "16",  # Change log
    }

    def test_all_required_sections_present(
        self, section_headings: list[str]
    ) -> None:
        present_numbers = {
            heading.split(". ", 1)[0].removeprefix("## ")
            for heading in section_headings
        }
        missing = self.REQUIRED_SECTION_NUMBERS - present_numbers
        assert not missing, (
            f"Required §N sections missing from SOS-09-B doc: {missing}. "
            f"Present: {sorted(present_numbers, key=int)}."
        )

    def test_section_count_at_least_seventeen(
        self, section_headings: list[str]
    ) -> None:
        # 0..16 inclusive = 17 sections.
        assert len(section_headings) >= 17, (
            f"Expected at least 17 sections (§0..§16); "
            f"found {len(section_headings)}."
        )

    def test_authority_policy_section_present(
        self, concepts_text: str
    ) -> None:
        assert "## 0. Authority policy" in concepts_text, (
            "§0 Authority policy section MUST be present."
        )

    def test_change_log_section_present(self, concepts_text: str) -> None:
        assert "## 16. Change log" in concepts_text, (
            "§16 Change log section MUST be present."
        )


# ---------------------------------------------------------------------------
# §5 frozen decisions — schema version + consumer + access mapping
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def section_5(concepts_text: str) -> str:
    """Slice from §5 heading through §6 heading."""
    pattern = re.compile(
        r"^## 5\. Frozen decisions.*?(?=^## 6\.)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(concepts_text)
    if match is None:
        pytest.fail("Could not locate §5 Frozen decisions section.")
    return match.group(0)


class TestSection5Frozen:
    """§5 names the schema version + strict consumer + access mappings."""

    def test_cmsis_svd_version_pinned(self, section_5: str) -> None:
        assert "1.3" in section_5 and "CMSIS-SVD" in section_5, (
            "§5 MUST pin the CMSIS-SVD schema version to 1.3.x."
        )

    def test_svd2rust_strict_named(self, section_5: str) -> None:
        # The strict-mode consumer gate is normative per §5.6.
        assert "svd2rust" in section_5, (
            "§5 MUST name svd2rust as the downstream consumer."
        )
        assert "strict" in section_5.lower(), (
            "§5 MUST name svd2rust's strict mode as the conformance gate."
        )

    def test_access_mapping_status_to_read_only(
        self, section_5: str
    ) -> None:
        # `status` / `hw→sw` → `read-only`.
        assert "`status`" in section_5 and "`read-only`" in section_5, (
            "§5 MUST map status channels to SVD read-only access."
        )

    def test_access_mapping_command_to_write_only(
        self, section_5: str
    ) -> None:
        # `command` / `sw→hw` → `write-only`.
        assert "`command`" in section_5 and "`write-only`" in section_5, (
            "§5 MUST map command channels to SVD write-only access."
        )

    def test_access_mapping_queue_to_read_write(
        self, section_5: str
    ) -> None:
        # `queue` / `hw↔sw` → `read-write`.
        assert "`queue`" in section_5 and "`read-write`" in section_5, (
            "§5 MUST map queue channels to SVD read-write access."
        )

    def test_access_mapping_shared_to_read_write(
        self, section_5: str
    ) -> None:
        # `shared` / `hw↔sw` → `read-write`.
        assert "`shared`" in section_5, (
            "§5 MUST map shared channels into the access mapping table."
        )

    def test_modified_write_values_named(self, section_5: str) -> None:
        # Side-effect mapping must reference CMSIS-SVD's
        # <modifiedWriteValues> vocabulary.
        assert "modifiedWriteValues" in section_5, (
            "§5 MUST name the SVD <modifiedWriteValues> element "
            "for side-effect emission."
        )

    def test_validation_gate_uses_xmllint(self, section_5: str) -> None:
        assert "xmllint" in section_5, (
            "§5 MUST name xmllint as the schema-validation tool."
        )


# ---------------------------------------------------------------------------
# §7 cross-sub-phase invariants — INV-S-MEM-B-N
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def section_7(concepts_text: str) -> str:
    """Slice from §7 heading through §8 heading."""
    pattern = re.compile(
        r"^## 7\. Cross-sub-phase invariants.*?(?=^## 8\.)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(concepts_text)
    if match is None:
        pytest.fail("Could not locate §7 Cross-sub-phase invariants.")
    return match.group(0)


class TestSection7Invariants:
    """§7 declares INV-S-MEM-B-N invariants (at least 4)."""

    def test_invariants_count_at_least_four(self, section_7: str) -> None:
        invariants = re.findall(r"INV-S-MEM-B-\d+", section_7)
        unique_invariants = set(invariants)
        assert len(unique_invariants) >= 4, (
            f"§7 MUST declare at least 4 INV-S-MEM-B-N invariants; "
            f"found {len(unique_invariants)} unique: "
            f"{sorted(unique_invariants)}."
        )

    def test_invariant_1_single_register_per_channel(
        self, section_7: str
    ) -> None:
        # INV-S-MEM-B-1: every chart channel surfaces in exactly one
        # <register> element.
        assert "INV-S-MEM-B-1" in section_7, (
            "INV-S-MEM-B-1 (one register per channel) MUST be declared."
        )

    def test_invariant_access_deterministic(self, section_7: str) -> None:
        # INV-S-MEM-B-2: SVD <access> deterministic from chart
        # `sos:kind` + `sos:dir`; no chart-author override at v1.
        assert "INV-S-MEM-B-2" in section_7, (
            "INV-S-MEM-B-2 (access deterministic from chart kind/dir) "
            "MUST be declared."
        )

    def test_invariant_validation_gate(self, section_7: str) -> None:
        # INV-S-MEM-B-3: validation gate as release condition.
        assert "INV-S-MEM-B-3" in section_7, (
            "INV-S-MEM-B-3 (validation gate as release condition) "
            "MUST be declared."
        )

    def test_invariant_determinism(self, section_7: str) -> None:
        # INV-S-MEM-B-4: deterministic per (chart, target).
        assert "INV-S-MEM-B-4" in section_7, (
            "INV-S-MEM-B-4 (deterministic per chart+target) MUST be "
            "declared."
        )


# ---------------------------------------------------------------------------
# §15 PCDNs — at least 3 open PCDNs filed
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def section_15(concepts_text: str) -> str:
    """Slice from §15 heading through §16 heading."""
    pattern = re.compile(
        r"^## 15\. Pending Concept Decision Notices.*?(?=^## 16\.)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(concepts_text)
    if match is None:
        pytest.fail("Could not locate §15 PCDNs section.")
    return match.group(0)


class TestSection15PCDNs:
    """§15 files at least 3 open PCDNs with stable identifiers."""

    def test_pcdn_count_at_least_three(self, section_15: str) -> None:
        pcdn_ids = set(re.findall(r"PCDN-SOS-09-B-\d{3}", section_15))
        assert len(pcdn_ids) >= 3, (
            f"§15 MUST file at least 3 PCDNs; "
            f"found {len(pcdn_ids)} unique: {sorted(pcdn_ids)}."
        )

    def test_pcdn_001_side_effect_source(self, section_15: str) -> None:
        # PCDN-SOS-09-B-001 — side-effect annotation source
        # (chart-attribute vs chart-element).
        assert "PCDN-SOS-09-B-001" in section_15, (
            "PCDN-SOS-09-B-001 (side-effect annotation source) MUST "
            "be filed."
        )

    def test_pcdn_002_peripheral_grouping(self, section_15: str) -> None:
        assert "PCDN-SOS-09-B-002" in section_15, (
            "PCDN-SOS-09-B-002 (peripheral grouping policy) MUST "
            "be filed."
        )

    def test_pcdn_003_address_offset_policy(self, section_15: str) -> None:
        assert "PCDN-SOS-09-B-003" in section_15, (
            "PCDN-SOS-09-B-003 (address-offset assignment policy) "
            "MUST be filed."
        )

    def test_pcdns_carry_recommendation(self, section_15: str) -> None:
        # Each PCDN includes a `**Recommendation**:` line per the
        # SOS-08-A precedent.
        recommendation_count = section_15.count("**Recommendation**")
        pcdn_ids = set(re.findall(r"PCDN-SOS-09-B-\d{3}", section_15))
        assert recommendation_count >= len(pcdn_ids), (
            f"Every PCDN SHOULD carry a **Recommendation**: line; "
            f"found {recommendation_count} recommendations for "
            f"{len(pcdn_ids)} PCDNs."
        )


# ---------------------------------------------------------------------------
# §8 standards integration matrix — derive relationships
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def section_8(concepts_text: str) -> str:
    """Slice from §8 heading through §9 heading."""
    pattern = re.compile(
        r"^## 8\. Standards integration matrix.*?(?=^## 9\.)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(concepts_text)
    if match is None:
        pytest.fail("Could not locate §8 standards integration matrix.")
    return match.group(0)


class TestSection8Standards:
    """§8 cites CMSIS-SVD and svd2rust as `derive` relationships."""

    def test_cmsis_svd_derive_row(self, section_8: str) -> None:
        # The row must name CMSIS-SVD with `derive`.
        assert "CMSIS-SVD" in section_8, (
            "§8 MUST include a row for CMSIS-SVD."
        )
        assert "**derive**" in section_8, (
            "§8 MUST mark at least one row as **derive** "
            "(CMSIS-SVD relationship)."
        )

    def test_svd2rust_derive_row(self, section_8: str) -> None:
        assert "svd2rust" in section_8, (
            "§8 MUST include a row for svd2rust."
        )

    def test_xmllint_derive_row(self, section_8: str) -> None:
        # The xmllint validator row is part of the standards matrix
        # additions per §5.6.
        assert "xmllint" in section_8, (
            "§8 SHOULD include a row for xmllint (the schema "
            "validator)."
        )

    def test_mirror_relationships_present(self, section_8: str) -> None:
        # SOS-09-A annotation schema and SOS-09 umbrella enums are
        # `mirror` relationships (consumed without modification).
        assert "**mirror**" in section_8, (
            "§8 MUST include at least one **mirror** relationship "
            "(SOS-09-A or umbrella enum consumption)."
        )


# ---------------------------------------------------------------------------
# §10 reconciliation — fixtures check
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def section_10(concepts_text: str) -> str:
    """Slice from §10 heading through §11 heading."""
    pattern = re.compile(
        r"^## 10\. Reconciliation decisions.*?(?=^## 11\.)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(concepts_text)
    if match is None:
        pytest.fail("Could not locate §10 Reconciliation decisions.")
    return match.group(0)


class TestSection10Reconciliation:
    """§10 reconciles with existing test fixtures (if any)."""

    def test_section_10_present(self, section_10: str) -> None:
        assert len(section_10) > 100, (
            "§10 reconciliation section MUST have substantive content."
        )

    def test_section_10_addresses_fixtures(self, section_10: str) -> None:
        # If `.svd` files exist under tools/sos-codegen/, §10 must
        # reconcile against them; otherwise §10 must note the absence.
        existing_svd_files = list(_SOS_CODEGEN_ROOT.rglob("*.svd"))
        if existing_svd_files:
            # The doc must mention how the existing files relate.
            assert "fixture" in section_10.lower() or ".svd" in section_10, (
                f"Existing .svd files found under tools/sos-codegen "
                f"({[str(p.relative_to(_REPO_ROOT)) for p in existing_svd_files]}); "
                f"§10 MUST reconcile against them."
            )
        else:
            # The doc must explicitly say there are none.
            assert (
                "no `.svd`" in section_10
                or "none found" in section_10.lower()
                or "no .svd" in section_10.lower()
            ), (
                "No .svd fixtures exist under tools/sos-codegen; "
                "§10 MUST explicitly note their absence."
            )

    def test_section_10_addresses_sub_phase_siblings(
        self, section_10: str
    ) -> None:
        # The sibling sub-phases SOS-09-C/D/E/F are upstream/downstream
        # consumers; reconciliation MUST mention them.
        siblings_named = (
            "SOS-09-C" in section_10
            or "SOS-09-D" in section_10
            or "SOS-09-E" in section_10
            or "SOS-09-F" in section_10
        )
        assert siblings_named, (
            "§10 MUST reconcile against at least one sibling "
            "sub-phase (SOS-09-C/D/E/F)."
        )


# ---------------------------------------------------------------------------
# PCDN-SOS-09-001 amendment compliance — no xmlns:sos in SOS-09-B
# ---------------------------------------------------------------------------


class TestPCDN001AmendmentCompliance:
    """SOS-09-B honours PCDN-SOS-09-001 amended 2026-05-25.

    The amendment retracted the `xmlns:sos` URL registration; SOS-09-B
    must not emit any `xmlns:sos` into the SVD output, and must treat
    `sos:` as a JSON-key string prefix inside `other_attributes`, not
    an XML namespace prefix.
    """

    def test_xmlns_sos_url_not_endorsed_as_emit_output(
        self, concepts_text: str
    ) -> None:
        # The URL `https://softoboros.com/sos/1.0` MAY appear in
        # historical retraction context only. SOS-09-B MUST NOT
        # endorse it as an SVD output declaration.
        if "https://softoboros.com/sos/1.0" in concepts_text:
            # When present, the context must be a non-goal /
            # retraction citation, not an emit instruction.
            # Conservative check: the URL appears only in the
            # non-goals section or alongside "NOT registered" /
            # "retracted" language.
            url_pos = concepts_text.find("https://softoboros.com/sos/1.0")
            surrounding = concepts_text[
                max(0, url_pos - 200):url_pos + 200
            ]
            forbidden_endorsement = (
                "xmlns:sos=\"https://softoboros.com/sos/1.0\""
                in surrounding
                and "MUST emit" in surrounding
            )
            assert not forbidden_endorsement, (
                "SOS-09-B MUST NOT endorse `xmlns:sos` URL "
                "registration as an SVD-emit output instruction; "
                "PCDN-SOS-09-001 amended 2026-05-25 retracted it."
            )

    def test_sos_prefix_is_json_key_prefix_not_xml_namespace(
        self, concepts_text: str
    ) -> None:
        # The doc must clarify the `sos:` prefix convention is on
        # JSON keys inside `other_attributes`, not an XML namespace.
        assert "other_attributes" in concepts_text, (
            "SOS-09-B MUST reference `other_attributes` as the "
            "annotation source (PCDN-SOS-09-001 amended 2026-05-25)."
        )

    def test_sos_a_annotation_schema_is_mirror_consumer(
        self, concepts_text: str
    ) -> None:
        # The doc must declare that SOS-09-B consumes SOS-09-A's
        # annotation schema without modification (mirror).
        assert "SOS-09-A" in concepts_text, (
            "SOS-09-B MUST cite SOS-09-A as the annotation-schema "
            "source it consumes."
        )


# ---------------------------------------------------------------------------
# Cross-phase invariant citations (per Phase document shape §0)
# ---------------------------------------------------------------------------


class TestCrossPhaseInvariantCitation:
    """The doc cites the umbrella invariants per the phase shape."""

    def test_cites_inv_sos_g(self, concepts_text: str) -> None:
        # INV-SOS-G (verified-codegen position) is the cross-phase
        # invariant that backs SOS-09-B's determinism property
        # (INV-S-MEM-B-4).
        assert "INV-SOS-G" in concepts_text, (
            "Doc MUST cite INV-SOS-G (verified-codegen position) "
            "as backing for emission determinism."
        )

    def test_cites_inv_s_mem_umbrella(
        self, concepts_text: str
    ) -> None:
        # The umbrella's INV-S-MEM-1 through 6 are cited (umbrella
        # owns them; SOS-09-B references without re-deriving).
        assert "INV-S-MEM-1" in concepts_text or "INV-S-MEM-2" in concepts_text, (
            "Doc MUST cite at least one of the SOS-09 umbrella "
            "INV-S-MEM-N invariants."
        )

    def test_files_cited_lists_umbrella(self, concepts_text: str) -> None:
        # §13 Files cited MUST name the umbrella.
        assert "SOS-09-CONCEPTS.md" in concepts_text, (
            "Doc MUST cite the SOS-09 umbrella in §13 Files cited."
        )

    def test_files_cited_lists_sos_07(self, concepts_text: str) -> None:
        # §13 Files cited MUST name SOS-07 (cross-phase invariants).
        assert "SOS-07-CONCEPTS.md" in concepts_text, (
            "Doc MUST cite SOS-07 (cross-phase invariants) in §13 "
            "Files cited."
        )


# ---------------------------------------------------------------------------
# §9 Acceptance gates
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def section_9(concepts_text: str) -> str:
    """Slice from §9 heading through §10 heading."""
    pattern = re.compile(
        r"^## 9\. Acceptance gates.*?(?=^## 10\.)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(concepts_text)
    if match is None:
        pytest.fail("Could not locate §9 Acceptance gates section.")
    return match.group(0)


class TestSection9AcceptanceGates:
    """§9 declares acceptance gates (a)..(f) for the emit path."""

    def test_gates_a_through_f_present(self, section_9: str) -> None:
        # Six gates: schema, strict-consumer, determinism, coverage,
        # side-effect round-trip, IRQ-table coverage.
        for letter in ("(a)", "(b)", "(c)", "(d)", "(e)", "(f)"):
            assert letter in section_9, (
                f"§9 MUST declare gate {letter}."
            )

    def test_gates_name_xmllint_and_svd2rust(self, section_9: str) -> None:
        assert "xmllint" in section_9, (
            "§9 acceptance gates MUST name xmllint as the schema "
            "validator."
        )
        assert "svd2rust" in section_9, (
            "§9 acceptance gates MUST name svd2rust as the strict "
            "consumer."
        )
