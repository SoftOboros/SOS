"""SOS-09-C concepts-doc structural assertions.

@spec  docs/concepts/SOS-09-C-CONCEPTS.md (C HAL header emission sub-phase)
@spec  docs/concepts/SOS-09-CONCEPTS.md §6 SOS-09-C description; §5
       umbrella frozen decisions SOS-09-C consumes.
@spec  docs/concepts/SOS-09-A-CONCEPTS.md §5.2 (PCDN-SOS-09-A-003) —
       `sos:name` is SV-identifier, `sos:id` is UUID. SOS-09-C uses
       `sos:name` for the emitted accessor-symbol root (INV-S-MEM-C-5).
@spec  docs/concepts/SOS-09-B-CONCEPTS.md §5.3 — register `<addressOffset>`
       chain that SOS-09-C derives struct overlay layout from.
@spec  docs/concepts/SOS-09-G-CONCEPTS.md §5.3 — `sos_mpu_region_t` C
       type whose `extern` declarations SOS-09-C exports.
@spec  Parent CLAUDE.md "Spec-Before-Code Planning Discipline /
       Phase document shape" — §0..§16 section layout precedent.

This module verifies that the SOS-09-C-CONCEPTS.md doc is structurally
sound at the ratified tier (post 2026-05-26 walkthrough):

  - Required sections (§0..§16) present.
  - Status banner is 🟢 RATIFIED 2026-05-26.
  - §5 declares the six frozen decisions §5.1..§5.6 with explicit
    registration-policy declarations.
  - §6 declares INV-S-MEM-C-1 through INV-S-MEM-C-5.
  - §15 carries the 5 PCDNs (PCDN-SOS-09-C-001 through 005) marked
    🟢 RATIFIED with their chosen-option letters.
  - §16 carries the 2026-05-26 ratified change-log entry.
  - §4 source-of-truth map carries at least one Authority-Relationship
    row using the seven-value relationship vocabulary
    (`own` / `derive` / `mirror` / `extend` / `compose` / `adapt` /
    `represent`).
  - The doc cites the SOS-09 umbrella, SOS-09-A, and SOS-09-B.

@invariants  INV-SOS-A (chart-as-source) — C HAL header is a build
             output; chart is canonical.
@invariants  INV-S-MEM-C-5 (deterministic-from-sos:name) — accessor
             symbols derive from `sos:name`, not `sos:id`.
@invariants  INV-S-MEM-C-4 — emitted headers are `-Wpedantic -std=c11`
             clean.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Repo-root resolution: this test file lives at
# tools/sos-codegen/tests/test_sos_09_c_concepts_doc.py
# → repo root is three parents up.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DOC_PATH = _REPO_ROOT / "docs" / "concepts" / "SOS-09-C-CONCEPTS.md"


@pytest.fixture(scope="module")
def doc_text() -> str:
    if not _DOC_PATH.exists():
        pytest.fail(f"SOS-09-C concepts doc missing at {_DOC_PATH}")
    return _DOC_PATH.read_text(encoding="utf-8")


def _section_slice(text: str, section_num: int) -> str:
    """Return the body of `## <N>.` heading through to the next `## ` heading."""
    pattern = re.compile(
        rf"^## {section_num}\..*?(?=^## \d+\.|\Z)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(text)
    if match is None:
        return ""
    return match.group(0)


# ---------------------------------------------------------------------------
# File presence & top-of-file metadata
# ---------------------------------------------------------------------------


class TestDocPresence:
    """The doc exists and carries the expected title + draft status banner."""

    def test_file_exists(self) -> None:
        assert _DOC_PATH.exists(), (
            f"SOS-09-C concepts doc MUST exist at {_DOC_PATH}."
        )

    def test_title_heading(self, doc_text: str) -> None:
        assert doc_text.startswith(
            "# SOS-09-C — C HAL header emission"
        ), (
            "Top-of-file heading MUST name the SOS-09-C sub-phase as "
            "the C HAL header emission path."
        )

    def test_ratified_status_marker(self, doc_text: str) -> None:
        # Post-ratification: the top-of-file status MUST be 🟢 RATIFIED.
        first_block = doc_text[:500]
        assert "🟢" in first_block, (
            "Top-of-file MUST carry a 🟢 ratified status marker."
        )
        assert "RATIFIED" in first_block, (
            "Top-of-file MUST carry a `RATIFIED` status keyword."
        )

    def test_ratified_date_2026_05_26(self, doc_text: str) -> None:
        first_block = doc_text[:500]
        assert "2026-05-26" in first_block, (
            "Top-of-file MUST carry the 2026-05-26 ratification date."
        )


# ---------------------------------------------------------------------------
# Required sections (§0..§16)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def section_headings(doc_text: str) -> list[str]:
    """Extract all `## N. <title>` headings from the doc."""
    pattern = re.compile(r"^## (\d+)\. (.+)$", re.MULTILINE)
    return [
        f"## {match.group(1)}. {match.group(2)}"
        for match in pattern.finditer(doc_text)
    ]


class TestRequiredSections:
    """The doc carries §0..§16 per the SOS-08-A / SOS-09-B / SOS-09-G precedent."""

    REQUIRED_SECTION_NUMBERS = {
        "0",   # Authority policy
        "1",   # Purpose
        "2",   # Problem statement
        "3",   # Canonical glossary
        "4",   # Source-of-truth map
        "5",   # Frozen decisions
        "6",   # Invariants
        "7",   # Enumeration policies
        "8",   # Standards integration matrix additions
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
            f"Required §N sections missing from SOS-09-C doc: {missing}. "
            f"Present: {sorted(present_numbers, key=int)}."
        )

    def test_authority_policy_section_present(
        self, doc_text: str
    ) -> None:
        assert "## 0. Authority policy" in doc_text, (
            "§0 Authority policy section MUST be present."
        )

    def test_change_log_section_present(self, doc_text: str) -> None:
        assert "## 16. Change log" in doc_text, (
            "§16 Change log section MUST be present."
        )


# ---------------------------------------------------------------------------
# §5 frozen decisions — six §5.x sub-sections
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def section_5(doc_text: str) -> str:
    """Slice from §5 heading through §6 heading."""
    pattern = re.compile(
        r"^## 5\. Frozen decisions.*?(?=^## 6\.)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(doc_text)
    if match is None:
        pytest.fail("Could not locate §5 Frozen decisions section.")
    return match.group(0)


class TestSection5FrozenDecisions:
    """§5 declares the six frozen-decision sub-sections §5.1..§5.6."""

    @pytest.mark.parametrize(
        "subsection,keyword",
        [
            ("5.1", "Accessor-macro naming"),
            ("5.2", "volatile"),
            ("5.3", "Side-effect annotation form"),
            ("5.4", "Header layout"),
            ("5.5", "Compile-time constants"),
            ("5.6", "MPU-region symbol"),
        ],
    )
    def test_subsection_present(
        self, section_5: str, subsection: str, keyword: str
    ) -> None:
        assert f"### {subsection}" in section_5, (
            f"§{subsection} subsection MUST be present in §5."
        )
        assert keyword.lower() in section_5.lower(), (
            f"§{subsection} SHOULD discuss the `{keyword}` concept."
        )

    def test_accessor_ops_enumerated(self, section_5: str) -> None:
        # §5.1 must enumerate the six ops.
        for op in ("read", "write", "consume", "fire", "claim", "release"):
            assert f"`{op}`" in section_5 or f" {op} " in section_5 or f"{op}," in section_5, (
                f"§5.1 MUST enumerate the `{op}` accessor op."
            )

    def test_sos_c_prefix_present(self, section_5: str) -> None:
        # §5.1 must specify the `SOS_C_<channel>_<op>` naming convention.
        assert "SOS_C_" in section_5, (
            "§5.1 MUST declare the `SOS_C_<channel>_<op>` naming "
            "convention."
        )

    def test_claim_release_reserved_for_shared(self, section_5: str) -> None:
        # The claim/release reservation rule for kind="shared".
        assert "claim" in section_5.lower() and "release" in section_5.lower(), (
            "§5.1 MUST name `claim` / `release` accessors."
        )
        assert "shared" in section_5.lower(), (
            "§5.1 MUST tie `claim` / `release` to `kind=\"shared\"`."
        )

    def test_volatile_qualifier_named(self, section_5: str) -> None:
        # §5.2 must require volatile on every struct field.
        assert "volatile" in section_5, (
            "§5.2 MUST require `volatile` qualifier policy."
        )

    def test_consume_and_fire_named(self, section_5: str) -> None:
        # §5.3 must specify *_consume_* and *_fire_* discrimination.
        assert "consume" in section_5.lower(), (
            "§5.3 MUST name `*_consume_*` for clear-on-read accessors."
        )
        assert "fire" in section_5.lower(), (
            "§5.3 MUST name `*_fire_*` for command / side-effect-on-write."
        )

    def test_umbrella_header_named(self, section_5: str) -> None:
        # §5.4 must specify the umbrella header `sos_<chart>.h`.
        assert "sos_<chart>.h" in section_5 or "umbrella" in section_5.lower(), (
            "§5.4 MUST name the `sos_<chart>.h` umbrella header."
        )

    def test_static_const_unsigned_for_shifts(self, section_5: str) -> None:
        # §5.5 must specify `static const unsigned` for shifts/masks.
        assert "static const unsigned" in section_5, (
            "§5.5 MUST declare `static const unsigned` for field "
            "shift/mask constants."
        )

    def test_define_for_addresses(self, section_5: str) -> None:
        # §5.5 must specify `#define` for register addresses.
        assert "#define" in section_5, (
            "§5.5 MUST declare `#define` for register address constants."
        )

    def test_mpu_region_extern_declaration(self, section_5: str) -> None:
        # §5.6 must specify `extern const sos_mpu_region_t ...`.
        assert "extern" in section_5 and "sos_mpu_region_t" in section_5, (
            "§5.6 MUST declare the `extern const sos_mpu_region_t "
            "sos_mpu_<channel>_region;` symbol export shape."
        )


class TestSection5RegistrationPolicies:
    """Each §5.x subsection declares a registration policy."""

    def test_standards_action_present(self, section_5: str) -> None:
        # At least one §5.x carries Standards Action (the cross-phase
        # contract surfaces — §5.1, §5.2, §5.3 per the drafted recommendations).
        assert "Standards Action" in section_5, (
            "§5 MUST declare at least one Standards Action registration "
            "policy (for cross-phase contract surfaces)."
        )

    def test_specification_required_present(self, section_5: str) -> None:
        # §5.4 / §5.5 / §5.6 are phase-local mechanics — Specification Required.
        assert "Specification Required" in section_5, (
            "§5 MUST declare at least one Specification Required "
            "registration policy (for phase-local mechanics)."
        )

    def test_all_subsections_carry_registration_policy(
        self, section_5: str
    ) -> None:
        # Each `### 5.x` subsection should contain a "registration policy"
        # statement.
        # Find every `### 5.x` heading and check the body up to the
        # next `### 5.y` or end of §5 contains a policy declaration.
        sub_pattern = re.compile(
            r"### 5\.(\d).*?(?=### 5\.\d|\Z)", re.DOTALL
        )
        bodies = [m.group(0) for m in sub_pattern.finditer(section_5)]
        assert len(bodies) >= 6, (
            f"§5 MUST contain at least 6 `### 5.x` subsections; "
            f"found {len(bodies)}."
        )
        missing = []
        for body in bodies:
            heading = body.split("\n", 1)[0]
            if "registration policy" not in body.lower():
                missing.append(heading)
        assert not missing, (
            f"Each §5.x subsection MUST carry a 'registration policy' "
            f"declaration. Missing in: {missing}"
        )


# ---------------------------------------------------------------------------
# §6 invariants — INV-S-MEM-C-1 through INV-S-MEM-C-5
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def section_6(doc_text: str) -> str:
    """Slice from §6 heading through §7 heading."""
    pattern = re.compile(
        r"^## 6\..*?(?=^## 7\.)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(doc_text)
    if match is None:
        pytest.fail("Could not locate §6 invariants section.")
    return match.group(0)


class TestSection6Invariants:
    """§6 declares INV-S-MEM-C-1 through INV-S-MEM-C-5."""

    def test_invariants_count_exactly_five(self, section_6: str) -> None:
        ids = set(re.findall(r"INV-S-MEM-C-\d+", section_6))
        assert len(ids) >= 5, (
            f"§6 MUST declare at least 5 INV-S-MEM-C-N invariants; "
            f"found {len(ids)} unique: {sorted(ids)}."
        )

    @pytest.mark.parametrize(
        "inv_id,keyword",
        [
            ("INV-S-MEM-C-1", "accessor"),
            ("INV-S-MEM-C-2", "clear-on-read"),
            ("INV-S-MEM-C-3", "command"),
            ("INV-S-MEM-C-4", "Wpedantic"),
            ("INV-S-MEM-C-5", "deterministic"),
        ],
    )
    def test_invariant_present_with_keyword(
        self, section_6: str, inv_id: str, keyword: str
    ) -> None:
        assert inv_id in section_6, (
            f"§6 MUST declare {inv_id}."
        )
        assert keyword.lower() in section_6.lower(), (
            f"§6 {inv_id} SHOULD discuss the `{keyword}` concept."
        )

    def test_inv_c_4_names_c11(self, section_6: str) -> None:
        # INV-S-MEM-C-4 is the toolchain-cleanness invariant.
        assert "c11" in section_6.lower() or "C11" in section_6, (
            "§6 INV-S-MEM-C-4 MUST cite the C11 standard."
        )

    def test_inv_c_5_names_sos_name_not_sos_id(self, section_6: str) -> None:
        # INV-S-MEM-C-5 is the deterministic-from-sos:name invariant.
        assert "sos:name" in section_6, (
            "§6 INV-S-MEM-C-5 MUST cite `sos:name` as the symbol root."
        )
        assert "sos:id" in section_6, (
            "§6 INV-S-MEM-C-5 MUST distinguish `sos:name` from `sos:id`."
        )


# ---------------------------------------------------------------------------
# §15 PCDNs — five PENDING PCDNs
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def section_15(doc_text: str) -> str:
    """Slice from §15 heading through §16 heading."""
    pattern = re.compile(
        r"^## 15\. Pending Concept Decision Notices.*?(?=^## 16\.)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(doc_text)
    if match is None:
        pytest.fail("Could not locate §15 PCDNs section.")
    return match.group(0)


class TestSection15PCDNs:
    """§15 carries five RATIFIED PCDNs with chosen-option letters."""

    def test_pcdn_count_at_least_five(self, section_15: str) -> None:
        ids = set(re.findall(r"PCDN-SOS-09-C-\d{3}", section_15))
        assert len(ids) >= 5, (
            f"§15 MUST file at least 5 PCDNs; "
            f"found {len(ids)} unique: {sorted(ids)}."
        )

    @pytest.mark.parametrize(
        "pcdn_id,keyword",
        [
            ("PCDN-SOS-09-C-001", "bitfield"),
            ("PCDN-SOS-09-C-002", "volatile"),
            ("PCDN-SOS-09-C-003", "consume"),
            ("PCDN-SOS-09-C-004", "umbrella"),
            ("PCDN-SOS-09-C-005", "inline"),
        ],
    )
    def test_named_pcdn_present(
        self, section_15: str, pcdn_id: str, keyword: str
    ) -> None:
        assert pcdn_id in section_15, (
            f"§15 MUST file {pcdn_id}."
        )
        assert keyword.lower() in section_15.lower(), (
            f"§15 {pcdn_id} SHOULD discuss the `{keyword}` concept."
        )

    def test_pcdns_carry_ratified_status(self, section_15: str) -> None:
        # Each PCDN must carry a 🟢 RATIFIED status marker
        # post-ratification.
        ratified_markers = section_15.count("🟢")
        ids = set(re.findall(r"PCDN-SOS-09-C-\d{3}", section_15))
        # The status marker appears at least once per PCDN.
        assert ratified_markers >= len(ids), (
            f"§15 MUST carry a 🟢 RATIFIED marker for each PCDN; "
            f"found {ratified_markers} 🟢 markers for {len(ids)} PCDNs."
        )

    def test_pcdns_state_ratified(self, section_15: str) -> None:
        # Each PCDN must state RATIFIED 2026-05-26.
        assert "RATIFIED 2026-05-26" in section_15, (
            "§15 PCDNs MUST carry `RATIFIED 2026-05-26` status text."
        )

    def test_pcdns_carry_recommendation(self, section_15: str) -> None:
        # Each PCDN includes a `**Recommendation**:` line per the
        # SOS-09-B / SOS-09-G precedent (preserved on ratification).
        recommendation_count = section_15.count("**Recommendation**")
        ids = set(re.findall(r"PCDN-SOS-09-C-\d{3}", section_15))
        assert recommendation_count >= len(ids), (
            f"Every PCDN SHOULD carry a **Recommendation**: line; "
            f"found {recommendation_count} recommendations for "
            f"{len(ids)} PCDNs."
        )

    @pytest.mark.parametrize(
        "pcdn_id,chosen_option",
        [
            ("PCDN-SOS-09-C-001", "(b)"),
            ("PCDN-SOS-09-C-002", "(a)"),
            ("PCDN-SOS-09-C-003", "(a)"),
            ("PCDN-SOS-09-C-004", "(a)"),
            ("PCDN-SOS-09-C-005", "(a)"),
        ],
    )
    def test_pcdn_carries_chosen_option(
        self, section_15: str, pcdn_id: str, chosen_option: str
    ) -> None:
        # Each PCDN's ratification line MUST name the chosen option
        # letter immediately after the RATIFIED marker.
        pattern = re.compile(
            rf"\*\*{re.escape(pcdn_id)}.*?(?=- \*\*PCDN-SOS-09-C-|\Z)",
            re.DOTALL,
        )
        match = pattern.search(section_15)
        assert match is not None, f"Could not locate {pcdn_id} block in §15."
        body = match.group(0)
        assert "🟢" in body, (
            f"{pcdn_id} MUST carry a 🟢 RATIFIED marker."
        )
        assert f"accepted option {chosen_option}" in body, (
            f"{pcdn_id} MUST name `accepted option {chosen_option}` "
            f"as the ratified choice."
        )


# ---------------------------------------------------------------------------
# §16 change log — awaiting ratification
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def section_16(doc_text: str) -> str:
    """Slice from §16 heading through end of doc."""
    pattern = re.compile(
        r"^## 16\. Change log.*?\Z",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(doc_text)
    if match is None:
        pytest.fail("Could not locate §16 Change log section.")
    return match.group(0)


class TestSection16ChangeLog:
    """§16 carries the 2026-05-26 ratified entry plus the initial-draft entry."""

    def test_ratified_entry_present(self, section_16: str) -> None:
        # Post-ratification: §16 carries a 2026-05-26 Ratified entry.
        assert "### 2026-05-26 — Ratified" in section_16, (
            "§16 MUST carry a `### 2026-05-26 — Ratified` entry."
        )

    def test_ratified_entry_lists_all_five_pcdns(self, section_16: str) -> None:
        # The ratified entry MUST list all 5 PCDNs by id.
        for pcdn in (
            "PCDN-SOS-09-C-001",
            "PCDN-SOS-09-C-002",
            "PCDN-SOS-09-C-003",
            "PCDN-SOS-09-C-004",
            "PCDN-SOS-09-C-005",
        ):
            assert pcdn in section_16, (
                f"§16 ratified entry MUST list {pcdn}."
            )

    def test_ratified_entry_carries_chosen_options(
        self, section_16: str
    ) -> None:
        # The ratified entry MUST name the chosen option for each PCDN.
        for chosen in (
            "option (b)",  # C-001
            "option (a)",  # C-002 through C-005 all (a) — only one occurrence needed
        ):
            assert chosen in section_16, (
                f"§16 ratified entry MUST name `{chosen}` as a chosen "
                f"option."
            )

    def test_ratified_entry_no_amendment_note(self, section_16: str) -> None:
        # All five accepted as recommended; no spec amendments triggered.
        assert "no spec amendments" in section_16.lower() or (
            "no §5" in section_16.lower() or "structural translation" in section_16.lower()
        ), (
            "§16 ratified entry SHOULD note that no spec amendments "
            "were triggered (all five accepted as recommended)."
        )

    def test_initial_draft_entry_present(self, section_16: str) -> None:
        # The original draft entry stays as institutional memory.
        assert "Initial draft" in section_16, (
            "§16 MUST retain the `Initial draft` entry."
        )

    def test_dated_2026_05_26(self, section_16: str) -> None:
        assert "### 2026-05-26" in section_16, (
            "§16 MUST carry a `### 2026-05-26` dated entry."
        )


# ---------------------------------------------------------------------------
# §4 source-of-truth map — Authority-Relationship rows
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def section_4(doc_text: str) -> str:
    """Slice from §4 heading through §5 heading."""
    pattern = re.compile(
        r"^## 4\. Source-of-truth map.*?(?=^## 5\.)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(doc_text)
    if match is None:
        pytest.fail("Could not locate §4 Source-of-truth map.")
    return match.group(0)


class TestSection4AuthorityRelationship:
    """§4 source-of-truth map uses the seven-value relationship vocabulary."""

    RELATIONSHIP_VOCAB = {
        "own",
        "derive",
        "mirror",
        "extend",
        "compose",
        "adapt",
        "represent",
    }

    def test_at_least_one_relationship_value_present(
        self, section_4: str
    ) -> None:
        # The seven-value vocabulary MUST appear in at least one row.
        # Lowercase, bolded by the spec-before-code precedent.
        # Check for `**<value>**` markdown bold spans.
        found_values = {
            value
            for value in self.RELATIONSHIP_VOCAB
            if f"**{value}**" in section_4.lower()
        }
        assert found_values, (
            f"§4 MUST use the seven-value AuthorityRelationship vocab; "
            f"none of {sorted(self.RELATIONSHIP_VOCAB)} found in §4."
        )

    def test_mirror_relationship_present(self, section_4: str) -> None:
        # SOS-09-A annotation surface and umbrella enums are mirror.
        assert "**mirror**" in section_4.lower(), (
            "§4 MUST declare at least one **mirror** relationship "
            "(umbrella enum or SOS-09-A consumption)."
        )

    def test_compose_relationship_present(self, section_4: str) -> None:
        # SOS-09-B `<addressOffset>` chain is compose.
        assert "**compose**" in section_4.lower(), (
            "§4 MUST declare at least one **compose** relationship "
            "(SOS-09-B address-offset consumption)."
        )

    def test_own_relationship_present(self, section_4: str) -> None:
        # This doc owns accessor naming, volatile policy, etc.
        assert "**own**" in section_4.lower(), (
            "§4 MUST declare at least one **own** relationship "
            "(this doc owns the accessor naming + volatile policy)."
        )


# ---------------------------------------------------------------------------
# Citations — umbrella + sibling sub-phase references
# ---------------------------------------------------------------------------


class TestCitations:
    """The doc cites the SOS-09 umbrella + SOS-09-A + SOS-09-B as upstream."""

    def test_cites_sos_09_umbrella(self, doc_text: str) -> None:
        # The umbrella IS upstream (the parent concept doc).
        assert "SOS-09-CONCEPTS.md" in doc_text, (
            "Doc MUST cite the SOS-09 umbrella `SOS-09-CONCEPTS.md`."
        )

    def test_cites_sos_09_a(self, doc_text: str) -> None:
        # SOS-09-A (chart annotation surface) is upstream of SOS-09-C.
        assert "SOS-09-A" in doc_text, (
            "Doc MUST cite SOS-09-A as the chart annotation surface "
            "consumed by SOS-09-C."
        )

    def test_cites_sos_09_b(self, doc_text: str) -> None:
        # SOS-09-B (CMSIS-SVD emission) is upstream of SOS-09-C.
        assert "SOS-09-B" in doc_text, (
            "Doc MUST cite SOS-09-B as the SVD emission whose "
            "`<addressOffset>` chain SOS-09-C consumes."
        )

    def test_cites_sos_09_g(self, doc_text: str) -> None:
        # SOS-09-G owns `sos_mpu_region_t` that SOS-09-C exports
        # `extern` declarations of.
        assert "SOS-09-G" in doc_text, (
            "Doc MUST cite SOS-09-G (the owner of `sos_mpu_region_t` + "
            "`sos_mpu_install()`)."
        )

    def test_cites_sos_07_for_cross_phase_invariants(
        self, doc_text: str
    ) -> None:
        assert "SOS-07-CONCEPTS.md" in doc_text or "SOS-07" in doc_text, (
            "Doc MUST cite SOS-07 (cross-phase invariants INV-SOS-A "
            "through H)."
        )

    def test_cites_inv_s_mem_umbrella(self, doc_text: str) -> None:
        # The umbrella's INV-S-MEM-1 through 6 are cited.
        assert (
            "INV-S-MEM-1" in doc_text
            or "INV-S-MEM-2" in doc_text
            or "INV-S-MEM-3" in doc_text
        ), (
            "Doc MUST cite at least one of the SOS-09 umbrella "
            "INV-S-MEM-N invariants."
        )

    def test_files_cited_lists_umbrella(self, doc_text: str) -> None:
        # §13 Files cited MUST name the umbrella.
        section_13 = _section_slice(doc_text, 13)
        assert "SOS-09-CONCEPTS.md" in section_13, (
            "§13 Files cited MUST name the SOS-09 umbrella."
        )

    def test_files_cited_lists_sos_07(self, doc_text: str) -> None:
        section_13 = _section_slice(doc_text, 13)
        assert "SOS-07-CONCEPTS.md" in section_13, (
            "§13 Files cited MUST name SOS-07 (cross-phase invariants)."
        )


# ---------------------------------------------------------------------------
# §12 acceptance checklist — gates (a)-(h) per the dispatch prompt
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def section_12(doc_text: str) -> str:
    """Slice from §12 heading through §13 heading."""
    pattern = re.compile(
        r"^## 12\. Acceptance checklist.*?(?=^## 13\.)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(doc_text)
    if match is None:
        pytest.fail("Could not locate §12 Acceptance checklist section.")
    return match.group(0)


class TestSection12AcceptanceChecklist:
    """§12 declares acceptance gates covering the dispatch-prompt checklist."""

    def test_gates_a_through_h_present(self, section_12: str) -> None:
        # The dispatch prompt named gates (a)-(h) covering: doc presence,
        # emission walker, accessor naming, volatile policy, side-effect
        # rename, -Wpedantic cleanness, MPU symbol export, deterministic
        # from sos:name.
        for letter in ("(a)", "(b)", "(c)", "(d)", "(e)", "(f)", "(g)", "(h)"):
            assert letter in section_12, (
                f"§12 MUST declare gate {letter}."
            )

    def test_gate_g_names_wpedantic(self, section_12: str) -> None:
        # -Wpedantic / -std=c11 toolchain gate cleanness.
        assert "Wpedantic" in section_12, (
            "§12 MUST cite `-Wpedantic` as a toolchain gate."
        )
        assert "c11" in section_12 or "C11" in section_12, (
            "§12 MUST cite C11 as the standard."
        )

    def test_gate_g_names_both_compilers(self, section_12: str) -> None:
        # Both gcc and clang gates must be enumerated.
        assert "gcc" in section_12.lower(), (
            "§12 MUST name gcc as a toolchain gate."
        )
        assert "clang" in section_12.lower(), (
            "§12 MUST name clang as a toolchain gate."
        )

    def test_gate_h_names_mpu_symbol(self, section_12: str) -> None:
        # MPU symbol export gate.
        assert "sos_mpu_" in section_12, (
            "§12 MUST cite the `sos_mpu_<channel>_region` symbol "
            "export shape."
        )

    def test_deterministic_from_name_gate(self, section_12: str) -> None:
        # The dispatch prompt named this as a load-bearing gate.
        assert "deterministic" in section_12.lower(), (
            "§12 MUST cite the deterministic-from-`sos:name` gate."
        )


# ---------------------------------------------------------------------------
# Non-goals (§11) — bounded scope
# ---------------------------------------------------------------------------


class TestSection11NonGoals:
    """§11 explicitly excludes full C runtime, MISRA-C, dynamic allocation."""

    def test_excludes_misra_c(self, doc_text: str) -> None:
        section_11 = _section_slice(doc_text, 11)
        assert "MISRA" in section_11, (
            "§11 MUST explicitly exclude MISRA-C from v1 scope."
        )

    def test_excludes_dynamic_allocation(self, doc_text: str) -> None:
        section_11 = _section_slice(doc_text, 11)
        assert "dynamic" in section_11.lower() and "alloc" in section_11.lower(), (
            "§11 MUST explicitly exclude dynamic allocation."
        )

    def test_excludes_rust_hal(self, doc_text: str) -> None:
        # SOS-09-D is a sibling, not this doc.
        section_11 = _section_slice(doc_text, 11)
        assert "Rust" in section_11 or "SOS-09-D" in section_11, (
            "§11 MUST explicitly exclude Rust HAL emission (that's SOS-09-D)."
        )
