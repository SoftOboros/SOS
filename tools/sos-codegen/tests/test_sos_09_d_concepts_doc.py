"""SOS-09-D concepts-doc structural assertions.

@spec  docs/concepts/SOS-09-D-CONCEPTS.md (Rust HAL trait emission sub-phase)
@spec  docs/concepts/SOS-09-CONCEPTS.md §5.5 (CMSIS-SVD primary;
       SystemRDL secondary) — parent decision SOS-09-D inherits.
@spec  docs/concepts/SOS-09-CONCEPTS.md §6 (SOS-09-D row) — informative
       summary the per-phase doc SOS-09-D-CONCEPTS.md normatively
       expands.
@spec  docs/concepts/SOS-09-CONCEPTS.md §7 INV-S-MEM-1 through 6 —
       umbrella invariants SOS-09-D cites.
@spec  docs/concepts/SOS-09-A-CONCEPTS.md §5 — chart annotation
       surface SOS-09-D consumes (10-key set + sos:id UUID / sos:name
       SV-identifier split per PCDN-SOS-09-A-003 ratification
       2026-05-25).
@spec  docs/concepts/SOS-09-B-CONCEPTS.md §5 — CMSIS-SVD emission
       SOS-09-D's RegisterBlock layout consumes via `svd2rust --strict`.
@spec  docs/concepts/SOS-09-G-CONCEPTS.md §5.5 — `sos_mpu_install()`
       hook step 4 that SOS-09-D's MPU-region constant export feeds.
@spec  Parent CLAUDE.md "Spec-Before-Code Planning Discipline /
       Phase document shape" — §0..§16 section layout precedent
       (SOS-08-A / SOS-09-B as reference shapes).

This module verifies that the SOS-09-D-CONCEPTS.md doc is structurally
sound:

  - Status banner is 🟡 DRAFT (awaiting PCDN walkthrough).
  - Required sections (§0..§16) present.
  - §5 has the six frozen-decisions subsections §5.1..§5.6 each
    declaring a registration policy.
  - §6 declares the six INV-S-MEM-D-1..6 invariants.
  - §15 files five PCDNs (PCDN-SOS-09-D-001 through 005) with
    🟡 PENDING USER WALKTHROUGH markers.
  - §16 marked as awaiting ratification.
  - §4 source-of-truth map carries at least one AuthorityRelationship
    row.
  - The doc cites SOS-09 umbrella + SOS-09-A + SOS-09-B + SOS-09-G as
    upstream contexts.
  - svd2rust + chiptool both textually present (upstream-ecosystem
    comparands per §0).

@invariants  INV-SOS-A (chart-as-source) — the emitted Rust HAL crate
             is a build output; chart is canonical.
@invariants  INV-SOS-G (verified-codegen position) — the
             chart-bounds discharge backing *_unchecked accessors
             lives at INV-S-MEM-D-5/D-6.
@invariants  INV-S-MEM-D-1..6 — the SOS-09-D-specific invariants
             tested here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Repo-root resolution: this test file lives at
# tools/sos-codegen/tests/test_sos_09_d_concepts_doc.py
# → repo root is three parents up.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONCEPTS_PATH = _REPO_ROOT / "docs" / "concepts" / "SOS-09-D-CONCEPTS.md"


@pytest.fixture(scope="module")
def concepts_text() -> str:
    if not _CONCEPTS_PATH.exists():
        pytest.fail(
            f"SOS-09-D concepts doc missing at {_CONCEPTS_PATH}"
        )
    return _CONCEPTS_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# File presence & top-of-file metadata
# ---------------------------------------------------------------------------


class TestDocPresence:
    """The doc exists and carries the expected title + status badge."""

    def test_file_exists(self) -> None:
        assert _CONCEPTS_PATH.exists(), (
            f"SOS-09-D concepts doc MUST exist at {_CONCEPTS_PATH}."
        )

    def test_title_heading(self, concepts_text: str) -> None:
        assert concepts_text.startswith(
            "# SOS-09-D — Rust HAL trait emission"
        ), (
            "Top-of-file heading MUST name the SOS-09-D sub-phase "
            "as the Rust HAL trait emission path."
        )

    def test_draft_status_marker(self, concepts_text: str) -> None:
        # Pre-ratification, the top-of-file status MUST be
        # 🟡 DRAFT (awaiting PCDN walkthrough).
        first_block = concepts_text[:500]
        assert "🟡 **DRAFT" in first_block, (
            "Top-of-file MUST carry a 🟡 DRAFT status marker "
            "pre-ratification (awaiting PCDN walkthrough)."
        )

    def test_draft_date_present(self, concepts_text: str) -> None:
        # Draft date naming the 2026-05-26 ratification round.
        first_block = concepts_text[:500]
        assert "2026-05-26" in first_block, (
            "Top-of-file status MUST name the 2026-05-26 draft date."
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
    """The doc carries §0..§16 per the SOS-08-A / SOS-09-B precedent shape."""

    REQUIRED_SECTION_NUMBERS = {
        "0",   # Authority policy
        "1",   # Purpose
        "2",   # Problem statement
        "3",   # Canonical glossary
        "4",   # Source-of-truth map
        "5",   # Frozen decisions
        "6",   # Invariants (INV-S-MEM-D-*)
        "7",   # Enumeration policies
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
            f"Required §N sections missing from SOS-09-D doc: {missing}. "
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

    def test_invariants_section_present(self, concepts_text: str) -> None:
        assert "## 6. Invariants" in concepts_text, (
            "§6 Invariants section MUST be present."
        )


# ---------------------------------------------------------------------------
# §5 frozen decisions — six subsections, each declaring a registration policy
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
    """§5 carries six frozen-decisions subsections §5.1..§5.6."""

    EXPECTED_SUBSECTIONS = (
        "### 5.1 ",
        "### 5.2 ",
        "### 5.3 ",
        "### 5.4 ",
        "### 5.5 ",
        "### 5.6 ",
    )

    def test_all_six_frozen_subsections_present(
        self, section_5: str
    ) -> None:
        for sub in self.EXPECTED_SUBSECTIONS:
            assert sub in section_5, (
                f"§5 MUST declare subsection {sub.strip()} per the "
                f"SOS-09-D frozen-decisions catalog."
            )

    def test_5_1_register_block_shape(self, section_5: str) -> None:
        assert "### 5.1 " in section_5 and "RegisterBlock" in section_5, (
            "§5.1 MUST freeze the RegisterBlock struct shape."
        )
        # The struct is #[repr(C)] per svd2rust convention.
        assert "#[repr(C)]" in section_5, (
            "§5.1 MUST name the #[repr(C)] struct shape."
        )

    def test_5_2_newtype_wrapper_family(self, section_5: str) -> None:
        assert "### 5.2 " in section_5, (
            "§5.2 MUST freeze the newtype wrapper family."
        )
        # All six wrappers must be named.
        for wrapper in (
            "`Status<T>`",
            "`Command<T>`",
            "`Queue<T>`",
            "`Shared<T>`",
            "`ClearOnRead<T>`",
            "`FireOnWrite<T>`",
        ):
            assert wrapper in section_5, (
                f"§5.2 MUST name newtype wrapper {wrapper}."
            )

    def test_5_3_type_state_for_shared(self, section_5: str) -> None:
        assert "### 5.3 " in section_5, (
            "§5.3 MUST freeze the type-state pattern for kind=shared."
        )
        # Claimed Drop-guard and ContentionError must be named.
        assert "Claimed" in section_5, (
            "§5.3 MUST name Claimed<'_, T> as the Drop-guard."
        )
        assert "ContentionError" in section_5, (
            "§5.3 MUST name ContentionError as the claim() error type."
        )

    def test_5_4_no_std_and_alloc_policy(self, section_5: str) -> None:
        assert "### 5.4 " in section_5, (
            "§5.4 MUST freeze the #![no_std] + optional alloc policy."
        )
        assert "no_std" in section_5, (
            "§5.4 MUST mention the no_std policy."
        )
        assert "alloc" in section_5, (
            "§5.4 MUST mention the optional alloc Cargo feature."
        )

    def test_5_5_unchecked_accessor_policy(self, section_5: str) -> None:
        assert "### 5.5 " in section_5, (
            "§5.5 MUST freeze the *_unchecked accessor emission policy."
        )
        assert "_unchecked" in section_5, (
            "§5.5 MUST name *_unchecked accessors."
        )
        assert "SAFETY" in section_5, (
            "§5.5 MUST require // SAFETY: discharge comments."
        )
        assert "INV-SOS-G" in section_5, (
            "§5.5 MUST cite INV-SOS-G as the discharging invariant "
            "framework."
        )

    def test_5_6_mpu_region_constant_export(self, section_5: str) -> None:
        assert "### 5.6 " in section_5, (
            "§5.6 MUST freeze the MPU-region constant export shape."
        )
        # The const-name shape must be SCREAMING_SNAKE_CASE prefixed
        # with SOS_MPU_.
        assert "SOS_MPU_" in section_5, (
            "§5.6 MUST name the SOS_MPU_<CHANNEL>_REGION const-name "
            "convention."
        )
        assert "sos_mpu_region_t" in section_5, (
            "§5.6 MUST name the sos_mpu_region_t type (owned by "
            "SOS-09-G)."
        )

    def test_every_5_n_subsection_declares_registration_policy(
        self, section_5: str
    ) -> None:
        # Each §5.N must declare its frozen-enumeration registration
        # policy (Standards Action / Specification Required /
        # Expert Review).
        # Split §5 into per-subsection chunks.
        subsection_re = re.compile(
            r"### (5\.\d) (.+?)(?=### 5\.\d|\Z)",
            re.DOTALL,
        )
        subsections = list(subsection_re.finditer(section_5))
        assert len(subsections) >= 6, (
            f"Expected at least 6 §5.N subsections; "
            f"found {len(subsections)}."
        )
        for match in subsections:
            sub_id = match.group(1)
            sub_body = match.group(2)
            has_policy = (
                "**Standards Action**" in sub_body
                or "**Specification Required**" in sub_body
                or "**Expert Review**" in sub_body
            )
            assert has_policy, (
                f"§{sub_id} MUST declare a frozen-enumeration "
                f"registration policy (Standards Action / "
                f"Specification Required / Expert Review)."
            )


# ---------------------------------------------------------------------------
# §6 invariants — INV-S-MEM-D-1 through INV-S-MEM-D-6
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def section_6(concepts_text: str) -> str:
    """Slice from §6 heading through §7 heading."""
    pattern = re.compile(
        r"^## 6\. Invariants.*?(?=^## 7\.)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(concepts_text)
    if match is None:
        pytest.fail("Could not locate §6 Invariants section.")
    return match.group(0)


class TestSection6Invariants:
    """§6 declares INV-S-MEM-D-1 through INV-S-MEM-D-6 (all six)."""

    def test_invariants_count_at_least_six(self, section_6: str) -> None:
        invariants = re.findall(r"INV-S-MEM-D-\d+", section_6)
        unique_invariants = set(invariants)
        assert len(unique_invariants) >= 6, (
            f"§6 MUST declare at least 6 INV-S-MEM-D-N invariants; "
            f"found {len(unique_invariants)} unique: "
            f"{sorted(unique_invariants)}."
        )

    def test_invariant_d1_newtype_wrapper_only(self, section_6: str) -> None:
        # INV-S-MEM-D-1: every register field is accessed only through
        # emitted newtype wrappers.
        assert "INV-S-MEM-D-1" in section_6, (
            "INV-S-MEM-D-1 (newtype-wrapper-only register access) "
            "MUST be declared."
        )

    def test_invariant_d2_clear_on_read_consumes_self(
        self, section_6: str
    ) -> None:
        # INV-S-MEM-D-2: ClearOnRead<T>::read consumes self.
        assert "INV-S-MEM-D-2" in section_6, (
            "INV-S-MEM-D-2 (ClearOnRead<T>::read consumes self) "
            "MUST be declared."
        )

    def test_invariant_d3_command_no_read(self, section_6: str) -> None:
        # INV-S-MEM-D-3: Command<T> exposes only fire/claim/release,
        # never read.
        assert "INV-S-MEM-D-3" in section_6, (
            "INV-S-MEM-D-3 (Command<T> never exposes read) MUST be "
            "declared."
        )

    def test_invariant_d4_cargo_check_clean(self, section_6: str) -> None:
        # INV-S-MEM-D-4: every emitted crate is cargo check clean on
        # thumbv7em-none-eabihf.
        assert "INV-S-MEM-D-4" in section_6, (
            "INV-S-MEM-D-4 (cargo check clean on thumbv7em) MUST be "
            "declared."
        )
        # The target triple must appear in the invariant body.
        assert "thumbv7em-none-eabihf" in section_6, (
            "INV-S-MEM-D-4 MUST name the thumbv7em-none-eabihf "
            "target."
        )

    def test_invariant_d5_register_block_offsets(self, section_6: str) -> None:
        # INV-S-MEM-D-5: RegisterBlock field offsets emitted from
        # SVD <addressOffset>.
        assert "INV-S-MEM-D-5" in section_6, (
            "INV-S-MEM-D-5 (RegisterBlock offsets match SVD) MUST "
            "be declared."
        )

    def test_invariant_d6_name_deterministic(self, section_6: str) -> None:
        # INV-S-MEM-D-6: accessor + type names deterministic from
        # sos:name (NOT sos:id).
        assert "INV-S-MEM-D-6" in section_6, (
            "INV-S-MEM-D-6 (names deterministic from sos:name) MUST "
            "be declared."
        )
        # The invariant body must clarify the sos:name / sos:id split.
        assert "sos:name" in section_6 and "sos:id" in section_6, (
            "INV-S-MEM-D-6 MUST name both sos:name (emission) and "
            "sos:id (identity-only)."
        )


# ---------------------------------------------------------------------------
# §15 PCDNs — five PCDNs filed with 🟡 PENDING markers
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
    """§15 files five PCDNs (D-001..D-005) all marked 🟡 PENDING."""

    EXPECTED_PCDNS = (
        "PCDN-SOS-09-D-001",
        "PCDN-SOS-09-D-002",
        "PCDN-SOS-09-D-003",
        "PCDN-SOS-09-D-004",
        "PCDN-SOS-09-D-005",
    )

    def test_pcdn_count_at_least_five(self, section_15: str) -> None:
        pcdn_ids = set(re.findall(r"PCDN-SOS-09-D-\d{3}", section_15))
        assert len(pcdn_ids) >= 5, (
            f"§15 MUST file at least 5 PCDNs; "
            f"found {len(pcdn_ids)} unique: {sorted(pcdn_ids)}."
        )

    def test_pcdn_001_inner_cell_type(self, section_15: str) -> None:
        # PCDN-SOS-09-D-001 — vcell vs cortex_m::interrupt::Mutex.
        assert "PCDN-SOS-09-D-001" in section_15, (
            "PCDN-SOS-09-D-001 (inner cell type) MUST be filed."
        )
        # Both vcell and the cortex_m interrupt::Mutex must be named
        # as options.
        assert "vcell" in section_15.lower(), (
            "PCDN-SOS-09-D-001 MUST name vcell as an option."
        )

    def test_pcdn_002_trait_vs_struct(self, section_15: str) -> None:
        assert "PCDN-SOS-09-D-002" in section_15, (
            "PCDN-SOS-09-D-002 (trait vs struct naming) MUST be filed."
        )

    def test_pcdn_003_contention_error(self, section_15: str) -> None:
        assert "PCDN-SOS-09-D-003" in section_15, (
            "PCDN-SOS-09-D-003 (ContentionError type) MUST be filed."
        )
        assert "ContentionError" in section_15, (
            "PCDN-SOS-09-D-003 body MUST discuss ContentionError."
        )

    def test_pcdn_004_cortex_m_dependency(self, section_15: str) -> None:
        assert "PCDN-SOS-09-D-004" in section_15, (
            "PCDN-SOS-09-D-004 (cortex-m crate dependency) MUST be "
            "filed."
        )
        assert "cortex" in section_15.lower(), (
            "PCDN-SOS-09-D-004 body MUST discuss the cortex-m crate."
        )

    def test_pcdn_005_unchecked_unsafe(self, section_15: str) -> None:
        assert "PCDN-SOS-09-D-005" in section_15, (
            "PCDN-SOS-09-D-005 (*_unchecked unsafe annotation) MUST "
            "be filed."
        )
        assert "unsafe" in section_15.lower(), (
            "PCDN-SOS-09-D-005 body MUST discuss unsafe fn vs safe "
            "fn for *_unchecked."
        )

    def test_all_pcdns_marked_pending(self, section_15: str) -> None:
        # Each PCDN body must carry a 🟡 PENDING USER WALKTHROUGH
        # marker (pre-ratification).
        for pcdn in self.EXPECTED_PCDNS:
            # Find the PCDN line.
            pattern = re.compile(
                rf"\*\*{re.escape(pcdn)}.*?(?=- \*\*PCDN-SOS-09-D-|\Z)",
                re.DOTALL,
            )
            match = pattern.search(section_15)
            assert match is not None, (
                f"Could not locate {pcdn} block in §15."
            )
            pcdn_body = match.group(0)
            assert "🟡" in pcdn_body, (
                f"{pcdn} MUST carry a 🟡 status marker pre-ratification."
            )
            assert "PENDING" in pcdn_body.upper(), (
                f"{pcdn} MUST carry a PENDING status text "
                f"pre-ratification."
            )

    def test_pcdns_carry_recommendation(self, section_15: str) -> None:
        # Each PCDN includes a `**Recommendation**:` line per the
        # SOS-09-B precedent.
        recommendation_count = section_15.count("**Recommendation**")
        pcdn_ids = set(re.findall(r"PCDN-SOS-09-D-\d{3}", section_15))
        assert recommendation_count >= len(pcdn_ids), (
            f"Every PCDN SHOULD carry a **Recommendation**: line; "
            f"found {recommendation_count} recommendations for "
            f"{len(pcdn_ids)} PCDNs."
        )


# ---------------------------------------------------------------------------
# §16 change log — empty (awaiting ratification)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def section_16(concepts_text: str) -> str:
    """Slice from §16 heading through end-of-file."""
    pattern = re.compile(
        r"^## 16\. Change log.*\Z",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(concepts_text)
    if match is None:
        pytest.fail("Could not locate §16 Change log section.")
    return match.group(0)


class TestSection16ChangeLog:
    """§16 is marked as awaiting ratification (no §15-resolved entries)."""

    def test_change_log_awaits_ratification(self, section_16: str) -> None:
        # Pre-ratification, §16 carries a placeholder noting that
        # ratification has not yet happened.
        assert "awaiting ratification" in section_16.lower(), (
            "§16 MUST carry an 'awaiting ratification' marker "
            "pre-ratification."
        )

    def test_change_log_has_no_ratified_entry(self, section_16: str) -> None:
        # A ratified entry would carry a '🟢 ratified' marker. The
        # draft state has none.
        assert "🟢 ratified" not in section_16, (
            "§16 MUST NOT carry a 🟢 ratified marker pre-ratification."
        )


# ---------------------------------------------------------------------------
# §4 source-of-truth map — AuthorityRelationship row(s)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def section_4(concepts_text: str) -> str:
    """Slice from §4 heading through §5 heading."""
    pattern = re.compile(
        r"^## 4\. Source-of-truth map.*?(?=^## 5\.)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(concepts_text)
    if match is None:
        pytest.fail("Could not locate §4 Source-of-truth map section.")
    return match.group(0)


class TestSection4SourceOfTruth:
    """§4 carries at least one AuthorityRelationship row."""

    AUTHORITY_RELATIONSHIPS = (
        "**own**",
        "**derive**",
        "**mirror**",
        "**adapt**",
        "**extend**",
        "**compose**",
        "**represent**",
    )

    def test_section_4_has_authority_relationship_row(
        self, section_4: str
    ) -> None:
        # At least ONE of the seven AuthorityRelationship values must
        # appear in §4.
        found = [
            rel for rel in self.AUTHORITY_RELATIONSHIPS
            if rel in section_4
        ]
        assert found, (
            "§4 MUST include at least one AuthorityRelationship row "
            f"using one of {self.AUTHORITY_RELATIONSHIPS}."
        )

    def test_section_4_has_own_or_derive(self, section_4: str) -> None:
        # SOS-09-D should declare ownership of its emission template
        # AND derive relationships against svd2rust/chiptool.
        assert "**own**" in section_4 or "**derive**" in section_4, (
            "§4 SHOULD include either an **own** row (for SOS-09-D's "
            "emission template) or a **derive** row (for svd2rust / "
            "chiptool consumption)."
        )

    def test_section_4_has_mirror_row(self, section_4: str) -> None:
        # SOS-09-D mirrors SOS-09-A's annotation schema and SOS-09's
        # channel-category enum.
        assert "**mirror**" in section_4, (
            "§4 MUST include at least one **mirror** relationship "
            "(SOS-09-A annotation schema or umbrella enum consumption)."
        )


# ---------------------------------------------------------------------------
# Upstream phase citations — umbrella + A + B + G
# ---------------------------------------------------------------------------


class TestUpstreamCitations:
    """The doc cites SOS-09 umbrella + SOS-09-A + SOS-09-B + SOS-09-G."""

    def test_cites_sos_09_umbrella(self, concepts_text: str) -> None:
        assert "SOS-09-CONCEPTS.md" in concepts_text, (
            "Doc MUST cite the SOS-09 umbrella concept doc."
        )

    def test_cites_sos_09_a(self, concepts_text: str) -> None:
        assert "SOS-09-A" in concepts_text, (
            "Doc MUST cite SOS-09-A (chart annotation surface) as an "
            "upstream context."
        )

    def test_cites_sos_09_b(self, concepts_text: str) -> None:
        assert "SOS-09-B" in concepts_text, (
            "Doc MUST cite SOS-09-B (CMSIS-SVD emission) as an "
            "upstream context."
        )

    def test_cites_sos_09_g(self, concepts_text: str) -> None:
        assert "SOS-09-G" in concepts_text, (
            "Doc MUST cite SOS-09-G (MPU configuration) — SOS-09-D's "
            "MPU constant export feeds SOS-09-G's sos_mpu_install()."
        )

    def test_cites_sos_07_for_invariants(self, concepts_text: str) -> None:
        # SOS-07 owns INV-SOS-A through H; SOS-09-D cites without
        # redefining.
        assert "SOS-07-CONCEPTS.md" in concepts_text, (
            "Doc MUST cite SOS-07 (cross-phase invariants) in §13 "
            "Files cited."
        )


# ---------------------------------------------------------------------------
# Upstream ecosystem comparands — svd2rust + chiptool
# ---------------------------------------------------------------------------


class TestUpstreamEcosystemComparands:
    """svd2rust + chiptool are named as upstream ecosystem patterns."""

    def test_svd2rust_textually_present(self, concepts_text: str) -> None:
        # Per §0 authority policy, svd2rust is the relevant upstream
        # Rust-side toolchain that SOS-09-D is structurally
        # compatible with.
        assert "svd2rust" in concepts_text, (
            "Doc MUST name svd2rust as the upstream-ecosystem "
            "comparand (canonical SVD→Rust toolchain)."
        )

    def test_chiptool_textually_present(self, concepts_text: str) -> None:
        # Per §0 authority policy, chiptool is the modern alternative
        # SOS-09-D's type-state pattern is inspired by.
        assert "chiptool" in concepts_text, (
            "Doc MUST name chiptool as the upstream-ecosystem "
            "comparand (modern SVD→Rust alternative)."
        )

    def test_vcell_named(self, concepts_text: str) -> None:
        # The vcell crate is the default inner cell type per
        # PCDN-SOS-09-D-001 recommendation.
        assert "vcell" in concepts_text.lower(), (
            "Doc MUST name the vcell crate (default inner cell "
            "type per PCDN-SOS-09-D-001)."
        )


# ---------------------------------------------------------------------------
# Cross-phase invariant citations (per Phase document shape §0)
# ---------------------------------------------------------------------------


class TestCrossPhaseInvariantCitation:
    """The doc cites the umbrella + cross-phase invariants per the phase shape."""

    def test_cites_inv_sos_g(self, concepts_text: str) -> None:
        # INV-SOS-G (verified-codegen position) is the cross-phase
        # invariant that backs SOS-09-D's *_unchecked accessor
        # discharge surface (per §5.5 + INV-S-MEM-D-5/D-6).
        assert "INV-SOS-G" in concepts_text, (
            "Doc MUST cite INV-SOS-G (verified-codegen position) "
            "as backing for the *_unchecked discharge surface."
        )

    def test_cites_inv_s_mem_umbrella(self, concepts_text: str) -> None:
        # The umbrella's INV-S-MEM-1 through 6 are cited (umbrella
        # owns them; SOS-09-D references without re-deriving).
        umbrella_invariants = (
            "INV-S-MEM-1",
            "INV-S-MEM-2",
            "INV-S-MEM-3",
            "INV-S-MEM-4",
            "INV-S-MEM-5",
            "INV-S-MEM-6",
        )
        found = [inv for inv in umbrella_invariants if inv in concepts_text]
        assert found, (
            f"Doc MUST cite at least one of the SOS-09 umbrella "
            f"{umbrella_invariants} invariants."
        )

    def test_files_cited_lists_umbrella(self, concepts_text: str) -> None:
        # §13 Files cited MUST name the umbrella.
        assert "SOS-09-CONCEPTS.md" in concepts_text, (
            "Doc MUST cite the SOS-09 umbrella in §13 Files cited."
        )


# ---------------------------------------------------------------------------
# §7 enumeration policies — catalog table
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def section_7(concepts_text: str) -> str:
    """Slice from §7 heading through §8 heading."""
    pattern = re.compile(
        r"^## 7\. Enumeration policies.*?(?=^## 8\.)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(concepts_text)
    if match is None:
        pytest.fail("Could not locate §7 Enumeration policies section.")
    return match.group(0)


class TestSection7EnumerationPolicies:
    """§7 catalogs the §5.1..§5.6 registration policies."""

    def test_section_7_present(self, section_7: str) -> None:
        assert len(section_7) > 100, (
            "§7 Enumeration policies section MUST have substantive "
            "content."
        )

    def test_section_7_lists_all_six_subsections(
        self, section_7: str
    ) -> None:
        for sub_id in ("§5.1", "§5.2", "§5.3", "§5.4", "§5.5", "§5.6"):
            assert sub_id in section_7, (
                f"§7 enumeration-policy catalog MUST list {sub_id}."
            )

    def test_section_7_names_all_policy_classes(self, section_7: str) -> None:
        # Both Standards Action and Specification Required SHOULD
        # appear in the catalog (per the §5.N policies declared).
        assert "Standards Action" in section_7, (
            "§7 MUST name 'Standards Action' as one of the "
            "registration policy classes."
        )
        assert "Specification Required" in section_7, (
            "§7 MUST name 'Specification Required' as one of the "
            "registration policy classes."
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
    """§9 declares acceptance gates covering the SOS-09-D emit path."""

    def test_gates_a_through_g_present(self, section_9: str) -> None:
        # At minimum, gates (a)..(g) covering: layout, newtype family,
        # type-state, cargo check, unchecked discharge, MPU export,
        # determinism.
        for letter in ("(a)", "(b)", "(c)", "(d)", "(e)", "(f)", "(g)"):
            assert letter in section_9, (
                f"§9 MUST declare gate {letter}."
            )

    def test_gates_name_cargo_check_thumbv7em(self, section_9: str) -> None:
        assert "thumbv7em-none-eabihf" in section_9, (
            "§9 acceptance gates MUST name thumbv7em-none-eabihf "
            "as the cargo check target."
        )


# ---------------------------------------------------------------------------
# §10 reconciliation — siblings + upstream comparands
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
    """§10 reconciles vs siblings + upstream comparands."""

    def test_section_10_substantive(self, section_10: str) -> None:
        assert len(section_10) > 200, (
            "§10 reconciliation section MUST have substantive content."
        )

    def test_section_10_addresses_svd2rust(self, section_10: str) -> None:
        assert "svd2rust" in section_10, (
            "§10 MUST reconcile against svd2rust (canonical "
            "Rust-Embedded WG SVD→Rust toolchain)."
        )

    def test_section_10_addresses_sub_phase_siblings(
        self, section_10: str
    ) -> None:
        # Sibling sub-phases SOS-09-A/B/C/E/F/G all merit
        # reconciliation entries.
        siblings_named = [
            sib for sib in (
                "SOS-09-A",
                "SOS-09-B",
                "SOS-09-C",
                "SOS-09-E",
                "SOS-09-F",
                "SOS-09-G",
            )
            if sib in section_10
        ]
        assert len(siblings_named) >= 3, (
            f"§10 MUST reconcile against at least three sibling "
            f"sub-phases (SOS-09-A/B/C/E/F/G); found {siblings_named}."
        )


# ---------------------------------------------------------------------------
# §11 non-goals — explicit exclusions
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def section_11(concepts_text: str) -> str:
    """Slice from §11 heading through §12 heading."""
    pattern = re.compile(
        r"^## 11\. Non-goals.*?(?=^## 12\.)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(concepts_text)
    if match is None:
        pytest.fail("Could not locate §11 Non-goals section.")
    return match.group(0)


class TestSection11NonGoals:
    """§11 explicitly excludes runtime / tokio / generic library scope."""

    def test_no_tokio(self, section_11: str) -> None:
        # tokio is a std-targeting runtime; SOS-09-D's no_std policy
        # forbids it explicitly.
        assert "tokio" in section_11.lower(), (
            "§11 MUST explicitly exclude tokio."
        )

    def test_no_runtime_authoring(self, section_11: str) -> None:
        assert "runtime" in section_11.lower(), (
            "§11 MUST explicitly exclude authoring a runtime."
        )

    def test_no_generic_library(self, section_11: str) -> None:
        # The emitted HAL is per-chart, not a generic library.
        assert "generic" in section_11.lower(), (
            "§11 MUST explicitly exclude authoring a generic "
            "register-abstraction library."
        )


# ---------------------------------------------------------------------------
# Sanity: emitter walker script reference
# ---------------------------------------------------------------------------


class TestEmitterScriptReference:
    """§13 Files cited references the Rust transliteration walker."""

    def test_transliterate_rust_referenced(self, concepts_text: str) -> None:
        # The existing tools/sos-codegen/transliterate_rust.py walker
        # is the SOS-09-D emit-path home.
        assert "transliterate_rust" in concepts_text, (
            "Doc SHOULD reference tools/sos-codegen/transliterate_rust.py "
            "as the existing Rust transliteration walker that SOS-09-D "
            "extends."
        )
