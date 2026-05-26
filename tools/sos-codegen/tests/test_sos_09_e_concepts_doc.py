"""SOS-09-E concepts-doc structural assertions.

@spec  docs/concepts/SOS-09-E-CONCEPTS.md (HDL register-file RTL
       emission sub-phase)
@spec  docs/concepts/SOS-09-CONCEPTS.md §5.2 (channel → membrane-
       primitive mapping; parent decision SOS-09-E mirrors with HDL-
       specific structural wiring)
@spec  docs/concepts/SOS-09-CONCEPTS.md §7 INV-S-MEM-1 through 6 —
       umbrella invariants SOS-09-E cites.
@spec  docs/concepts/SOS-08-A-CONCEPTS.md (L0 primitive library —
       sos_strobe_latch / sos_dpram_arb / sos_mutex / sos_synchronizer
       composed without modification).
@spec  docs/concepts/SOS-09-A-CONCEPTS.md (chart annotation surface —
       consumed via other_attributes JSON with sos:-prefixed keys).
@spec  docs/concepts/SOS-09-B-CONCEPTS.md (CMSIS-SVD emission — the
       silicon-side counterpart; SOS-09-E mirrors the address-offset
       assignment byte-for-byte per INV-S-MEM-E-6).
@spec  Parent CLAUDE.md "Spec-Before-Code Planning Discipline /
       Phase document shape" — §0..§16 section layout precedent.

This module verifies that the SOS-09-E-CONCEPTS.md doc is structurally
sound at the DRAFT stage (pre-PCDN-walkthrough):

  - Status banner is 🟡 DRAFT 2026-05-26.
  - Required sections (§0..§16) present.
  - §5 names 7 frozen decisions (§5.1..§5.7) with explicit registration
    policies.
  - §6 declares 6 INV-S-MEM-E-* invariants.
  - §15 files 6 PCDNs PCDN-SOS-09-E-001..006 with 🟡 PENDING status.
  - §16 awaits ratification.
  - §8 cites IEEE Std 1076-2008 (VHDL), IEEE Std 1800-2017 (SV),
    AMBA AXI4-Lite, AMBA APB as `derive` relationships.
  - §8 cites SOS-08-A primitives as `mirror`.
  - The doc cites SOS-09 umbrella + SOS-09-A + SOS-09-B + SOS-08-A as
    upstream authorities.
  - VHDL-2008 + SystemVerilog-2017 textually present.
  - AXI4-Lite + APB textually present.

@invariants  INV-SOS-A (chart-as-source) — RTL is a build output;
             chart is canonical.
@invariants  INV-S-MEM-3 (protection is end-to-end) — SOS-09-E + 09-G
             together fence the protection zone.
@invariants  INV-S-MEM-E-6 — RTL offsets match SVD <offset> byte-for-
             byte.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Repo-root resolution: this test file lives at
# tools/sos-codegen/tests/test_sos_09_e_concepts_doc.py
# → repo root is three parents up.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONCEPTS_PATH = _REPO_ROOT / "docs" / "concepts" / "SOS-09-E-CONCEPTS.md"


@pytest.fixture(scope="module")
def concepts_text() -> str:
    if not _CONCEPTS_PATH.exists():
        pytest.fail(
            f"SOS-09-E concepts doc missing at {_CONCEPTS_PATH}"
        )
    return _CONCEPTS_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# File presence & top-of-file metadata
# ---------------------------------------------------------------------------


class TestDocPresence:
    """The doc exists and carries the expected title + status badge."""

    def test_file_exists(self) -> None:
        assert _CONCEPTS_PATH.exists(), (
            f"SOS-09-E concepts doc MUST exist at {_CONCEPTS_PATH}."
        )

    def test_title_heading(self, concepts_text: str) -> None:
        assert concepts_text.startswith(
            "# SOS-09-E — HDL register-file RTL emission"
        ), (
            "Top-of-file heading MUST name the SOS-09-E sub-phase as "
            "the HDL register-file RTL emission path."
        )

    def test_draft_status_marker(self, concepts_text: str) -> None:
        # Pre-PCDN-walkthrough, the top-of-file status MUST be 🟡 DRAFT.
        first_block = concepts_text[:500]
        assert "🟡" in first_block, (
            "Top-of-file MUST carry a 🟡 DRAFT status marker at the "
            "pre-PCDN-walkthrough stage."
        )
        assert "DRAFT" in first_block, (
            "Top-of-file MUST carry an explicit DRAFT marker."
        )
        assert "2026-05-26" in first_block, (
            "Top-of-file status banner MUST carry the draft date "
            "2026-05-26."
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
    """The doc carries §0..§16 per the SOS-09-B / SOS-09-G precedent."""

    REQUIRED_SECTION_NUMBERS = {
        "0",   # Authority policy
        "1",   # Purpose
        "2",   # Problem statement
        "3",   # Canonical glossary
        "4",   # Source-of-truth map
        "5",   # Frozen decisions
        "6",   # Cross-sub-phase invariants
        "7",   # Enumeration policy catalog
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
            f"Required §N sections missing from SOS-09-E doc: {missing}. "
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
# §5 frozen decisions — 7 subsections + registration policies
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
    """§5 has 7 frozen decisions (§5.1..§5.7) each with a policy."""

    def test_all_seven_subsections_present(self, section_5: str) -> None:
        for sub in ("5.1", "5.2", "5.3", "5.4", "5.5", "5.6", "5.7"):
            assert f"### {sub}" in section_5, (
                f"§{sub} MUST appear as a subsection of §5."
            )

    def test_5_1_bus_interface_enumeration(self, section_5: str) -> None:
        # §5.1 — bus interface enumeration `axi4lite` / `apb`.
        assert "axi4lite" in section_5, (
            "§5.1 MUST enumerate `axi4lite` as a bus interface."
        )
        assert "apb" in section_5, (
            "§5.1 MUST enumerate `apb` as a bus interface."
        )

    def test_5_2_per_channel_realisation_table(
        self, section_5: str
    ) -> None:
        # §5.2 — per-channel realisation table; one row per chart
        # `kind` value.
        for kind in ("status", "command", "queue", "shared"):
            assert f"`{kind}`" in section_5, (
                f"§5.2 MUST name the `{kind}` channel kind."
            )

    def test_5_2_sos_08_a_primitives_named(self, section_5: str) -> None:
        # §5.2 names the composed primitives.
        for primitive in (
            "sos_strobe_latch",
            "sos_dpram_arb",
            "sos_mutex",
            "sos_synchronizer",
            "sos_message_channel",
        ):
            assert primitive in section_5, (
                f"§5.2 MUST name the SOS-08-A primitive `{primitive}`."
            )

    def test_5_3_write_mask_policy(self, section_5: str) -> None:
        # §5.3 — write-mask synthesized from field-level RW/RO/WO/
        # reserved declarations.
        assert "write-mask" in section_5.lower() or "write_mask" in section_5, (
            "§5.3 MUST name the write-mask concept."
        )
        for access_kind in ("RW", "RO", "WO", "reserved"):
            assert access_kind in section_5, (
                f"§5.3 MUST enumerate the `{access_kind}` field-access "
                f"declaration in the write-mask synthesis rule."
            )

    def test_5_4_read_clear_gating(self, section_5: str) -> None:
        # §5.4 — clear-on-read gated by valid + zone + read_enable.
        assert "clear-on-read" in section_5.lower() or "clear_on_read" in section_5, (
            "§5.4 MUST name the clear-on-read concept."
        )
        assert "zone" in section_5.lower(), (
            "§5.4 MUST name zone gating in the read-clear policy."
        )
        assert "read_enable" in section_5 or "read enable" in section_5.lower(), (
            "§5.4 MUST name the read_enable gating axis."
        )

    def test_5_5_access_violation_event(self, section_5: str) -> None:
        # §5.5 — access-violation event aggregation into one
        # strobe-latch per chart channel-group.
        assert "access_violation" in section_5 or "access-violation" in section_5, (
            "§5.5 MUST name the access-violation event concept."
        )
        assert "sos_strobe_latch" in section_5, (
            "§5.5 MUST aggregate access-violation strobes into a "
            "`sos_strobe_latch`."
        )

    def test_5_6_language_emission_shape(self, section_5: str) -> None:
        # §5.6 — VHDL-2008 + SystemVerilog-2017 co-emission +
        # synthesis-tool target set.
        assert "VHDL-2008" in section_5, (
            "§5.6 MUST name VHDL-2008 as an emitted language."
        )
        assert "SystemVerilog-2017" in section_5, (
            "§5.6 MUST name SystemVerilog-2017 as an emitted language."
        )
        assert "Vivado" in section_5, (
            "§5.6 MUST name Xilinx Vivado as a synthesis target."
        )
        assert "Quartus" in section_5, (
            "§5.6 MUST name Intel Quartus Pro as a synthesis target."
        )
        assert "Yosys" in section_5, (
            "§5.6 MUST name Yosys as a synthesis target."
        )

    def test_5_7_sos_regfile_template(self, section_5: str) -> None:
        # §5.7 — `sos_regfile` template module shape.
        assert "sos_regfile" in section_5, (
            "§5.7 MUST name the `sos_regfile` template module."
        )

    def test_registration_policies_present(self, section_5: str) -> None:
        # Every §5.x carries a registration policy line.
        # We expect at least 7 mentions of "Standards Action" or
        # "Specification Required" (one per §5.x).
        policy_count = section_5.count("Standards Action") + section_5.count(
            "Specification Required"
        )
        assert policy_count >= 7, (
            f"§5 MUST declare a registration policy for each of the 7 "
            f"frozen-decision subsections; found {policy_count} policy "
            f"mentions."
        )

    def test_5_1_is_standards_action(self, section_5: str) -> None:
        # §5.1 bus interface enum is Standards Action per spec.
        # Find the §5.1 subsection.
        m = re.search(
            r"### 5\.1.*?(?=### 5\.2)", section_5, re.DOTALL
        )
        assert m is not None, "Could not locate §5.1 subsection."
        assert "Standards Action" in m.group(0), (
            "§5.1 bus interface enumeration MUST be registered as "
            "Standards Action."
        )

    def test_5_7_is_specification_required(self, section_5: str) -> None:
        # §5.7 sos_regfile template is Specification Required per spec.
        m = re.search(
            r"### 5\.7.*?$", section_5, re.DOTALL
        )
        assert m is not None, "Could not locate §5.7 subsection."
        assert "Specification Required" in m.group(0), (
            "§5.7 `sos_regfile` template MUST be registered as "
            "Specification Required."
        )


# ---------------------------------------------------------------------------
# §6 cross-sub-phase invariants — INV-S-MEM-E-N
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def section_6(concepts_text: str) -> str:
    """Slice from §6 heading through §7 heading."""
    pattern = re.compile(
        r"^## 6\. Cross-sub-phase invariants.*?(?=^## 7\.)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(concepts_text)
    if match is None:
        pytest.fail("Could not locate §6 Cross-sub-phase invariants.")
    return match.group(0)


class TestSection6Invariants:
    """§6 declares all 6 INV-S-MEM-E-* invariants."""

    def test_all_six_invariants_present(self, section_6: str) -> None:
        invariants = set(re.findall(r"INV-S-MEM-E-\d+", section_6))
        expected = {
            "INV-S-MEM-E-1",
            "INV-S-MEM-E-2",
            "INV-S-MEM-E-3",
            "INV-S-MEM-E-4",
            "INV-S-MEM-E-5",
            "INV-S-MEM-E-6",
        }
        missing = expected - invariants
        assert not missing, (
            f"§6 MUST declare all 6 INV-S-MEM-E-* invariants; "
            f"missing: {missing}."
        )

    def test_invariant_e_1_single_decode_line(self, section_6: str) -> None:
        # INV-S-MEM-E-1: every chart-declared register maps to exactly
        # one decode line.
        e1_match = re.search(
            r"INV-S-MEM-E-1.*?(?=INV-S-MEM-E-2|$)", section_6, re.DOTALL
        )
        assert e1_match is not None, (
            "INV-S-MEM-E-1 declaration block MUST be locatable."
        )
        assert "decode line" in e1_match.group(0).lower(), (
            "INV-S-MEM-E-1 MUST reference the decode-line concept."
        )

    def test_invariant_e_2_write_mask(self, section_6: str) -> None:
        # INV-S-MEM-E-2: every writable register has a write-mask;
        # reserved-bit writes dropped.
        e2_match = re.search(
            r"INV-S-MEM-E-2.*?(?=INV-S-MEM-E-3|$)", section_6, re.DOTALL
        )
        assert e2_match is not None
        body = e2_match.group(0).lower()
        assert "write-mask" in body or "write_mask" in body, (
            "INV-S-MEM-E-2 MUST reference the write-mask concept."
        )
        assert "reserved" in body, (
            "INV-S-MEM-E-2 MUST reference reserved-bit handling."
        )

    def test_invariant_e_3_clear_on_read_zone(self, section_6: str) -> None:
        # INV-S-MEM-E-3: clear-on-read NEVER cleared by non-matching-
        # zone accesses.
        e3_match = re.search(
            r"INV-S-MEM-E-3.*?(?=INV-S-MEM-E-4|$)", section_6, re.DOTALL
        )
        assert e3_match is not None
        body = e3_match.group(0).lower()
        assert "clear-on-read" in body or "clear_on_read" in body, (
            "INV-S-MEM-E-3 MUST reference clear-on-read semantics."
        )
        assert "zone" in body, (
            "INV-S-MEM-E-3 MUST reference zone gating."
        )

    def test_invariant_e_4_violation_determinism(
        self, section_6: str
    ) -> None:
        # INV-S-MEM-E-4: access-violation events deterministic.
        e4_match = re.search(
            r"INV-S-MEM-E-4.*?(?=INV-S-MEM-E-5|$)", section_6, re.DOTALL
        )
        assert e4_match is not None
        body = e4_match.group(0).lower()
        assert "deterministic" in body, (
            "INV-S-MEM-E-4 MUST reference determinism."
        )
        assert "access-violation" in body or "violation" in body, (
            "INV-S-MEM-E-4 MUST reference access-violation events."
        )

    def test_invariant_e_5_bit_identical(self, section_6: str) -> None:
        # INV-S-MEM-E-5: VHDL + SV bit-identical simulation.
        e5_match = re.search(
            r"INV-S-MEM-E-5.*?(?=INV-S-MEM-E-6|$)", section_6, re.DOTALL
        )
        assert e5_match is not None
        body = e5_match.group(0).lower()
        assert "vhdl" in body and "systemverilog" in body, (
            "INV-S-MEM-E-5 MUST name both VHDL and SystemVerilog."
        )
        assert "bit-identical" in body or "bit identical" in body, (
            "INV-S-MEM-E-5 MUST claim bit-identical simulation."
        )

    def test_invariant_e_6_svd_offset_match(self, section_6: str) -> None:
        # INV-S-MEM-E-6: RTL offsets match SVD <offset> byte-for-byte;
        # build-stop on mismatch.
        e6_match = re.search(
            r"INV-S-MEM-E-6.*?(?=Frozen-enumeration|$)",
            section_6,
            re.DOTALL,
        )
        assert e6_match is not None
        body = e6_match.group(0).lower()
        assert "svd" in body, (
            "INV-S-MEM-E-6 MUST reference the SVD artifact."
        )
        assert "byte-for-byte" in body or "byte for byte" in body, (
            "INV-S-MEM-E-6 MUST claim byte-for-byte offset match."
        )


# ---------------------------------------------------------------------------
# §15 PCDNs — exactly 6 PCDNs with PENDING status
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
    """§15 files 6 PCDNs PCDN-SOS-09-E-001..006 with 🟡 PENDING status."""

    def test_pcdn_count_is_six(self, section_15: str) -> None:
        pcdn_ids = set(re.findall(r"PCDN-SOS-09-E-\d{3}", section_15))
        assert len(pcdn_ids) >= 6, (
            f"§15 MUST file at least 6 PCDNs; found "
            f"{len(pcdn_ids)} unique: {sorted(pcdn_ids)}."
        )

    def test_pcdn_001_bus_default(self, section_15: str) -> None:
        # PCDN-SOS-09-E-001 — bus interface default (AXI4-Lite vs APB).
        assert "PCDN-SOS-09-E-001" in section_15, (
            "PCDN-SOS-09-E-001 (bus interface default) MUST be filed."
        )

    def test_pcdn_002_reserved_bit(self, section_15: str) -> None:
        # PCDN-SOS-09-E-002 — reserved-bit handling policy.
        assert "PCDN-SOS-09-E-002" in section_15, (
            "PCDN-SOS-09-E-002 (reserved-bit handling) MUST be filed."
        )

    def test_pcdn_003_violation_aggregation(self, section_15: str) -> None:
        # PCDN-SOS-09-E-003 — access-violation aggregation strategy.
        assert "PCDN-SOS-09-E-003" in section_15, (
            "PCDN-SOS-09-E-003 (access-violation aggregation strategy) "
            "MUST be filed."
        )

    def test_pcdn_004_clock_domain_default(self, section_15: str) -> None:
        # PCDN-SOS-09-E-004 — clock-domain crossing default.
        assert "PCDN-SOS-09-E-004" in section_15, (
            "PCDN-SOS-09-E-004 (clock-domain crossing default) MUST "
            "be filed."
        )

    def test_pcdn_005_template_structure(self, section_15: str) -> None:
        # PCDN-SOS-09-E-005 — single template vs two templates.
        assert "PCDN-SOS-09-E-005" in section_15, (
            "PCDN-SOS-09-E-005 (sos_regfile template structure) MUST "
            "be filed."
        )

    def test_pcdn_006_write_side_effect_timing(self, section_15: str) -> None:
        # PCDN-SOS-09-E-006 — write-side-effect timing.
        assert "PCDN-SOS-09-E-006" in section_15, (
            "PCDN-SOS-09-E-006 (write-side-effect timing) MUST be filed."
        )

    def test_pcdns_carry_pending_status(self, section_15: str) -> None:
        # Each PCDN carries a 🟡 PENDING marker per the DRAFT-stage shape.
        pending_count = section_15.count("PENDING")
        pcdn_ids = set(re.findall(r"PCDN-SOS-09-E-\d{3}", section_15))
        assert pending_count >= len(pcdn_ids), (
            f"Every PCDN SHOULD carry a 🟡 PENDING status marker at "
            f"draft stage; found {pending_count} PENDING markers for "
            f"{len(pcdn_ids)} PCDNs."
        )

    def test_pcdns_carry_recommendation(self, section_15: str) -> None:
        # Each PCDN includes a `**Recommendation**:` line per the
        # SOS-09-B / SOS-09-G precedent.
        recommendation_count = section_15.count("**Recommendation**")
        pcdn_ids = set(re.findall(r"PCDN-SOS-09-E-\d{3}", section_15))
        assert recommendation_count >= len(pcdn_ids), (
            f"Every PCDN SHOULD carry a **Recommendation**: line; "
            f"found {recommendation_count} recommendations for "
            f"{len(pcdn_ids)} PCDNs."
        )


# ---------------------------------------------------------------------------
# §16 change log — awaiting ratification
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def section_16(concepts_text: str) -> str:
    """Slice from §16 heading through EOF."""
    pattern = re.compile(
        r"^## 16\. Change log.*$", re.DOTALL | re.MULTILINE
    )
    match = pattern.search(concepts_text)
    if match is None:
        pytest.fail("Could not locate §16 Change log section.")
    return match.group(0)


class TestSection16ChangeLog:
    """§16 carries the initial-draft entry and awaits ratification."""

    def test_change_log_has_initial_draft_entry(
        self, section_16: str
    ) -> None:
        assert "2026-05-26" in section_16, (
            "§16 MUST carry a 2026-05-26 dated initial-draft entry."
        )
        assert "Initial draft" in section_16, (
            "§16 MUST carry an 'Initial draft' entry."
        )

    def test_change_log_awaits_ratification(self, section_16: str) -> None:
        # Pre-PCDN-walkthrough, the §16 entry MUST close with a
        # 🟡 DRAFT status — there is no 🟢 ratified entry yet.
        assert "🟡" in section_16, (
            "§16 MUST carry the 🟡 draft status marker."
        )
        assert "awaiting PCDN walkthrough" in section_16, (
            "§16 MUST state that the doc awaits PCDN walkthrough."
        )

    def test_change_log_no_premature_ratification(
        self, section_16: str
    ) -> None:
        # Pre-PCDN-walkthrough, there is no 'Ratified' entry.
        assert "Ratified" not in section_16, (
            "§16 MUST NOT carry a 'Ratified' entry at the draft "
            "stage; ratification happens after PCDN walkthrough."
        )


# ---------------------------------------------------------------------------
# §8 standards integration matrix — derive + mirror relationships
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
    """§8 cites VHDL, SV, AXI4-Lite, APB, SOS-08-A primitives."""

    def test_vhdl_ieee_std_row(self, section_8: str) -> None:
        assert "1076-2008" in section_8 or "IEEE Std 1076" in section_8, (
            "§8 MUST include a row for IEEE Std 1076-2008 (VHDL)."
        )

    def test_sv_ieee_std_row(self, section_8: str) -> None:
        assert "1800-2017" in section_8 or "IEEE Std 1800" in section_8, (
            "§8 MUST include a row for IEEE Std 1800-2017 (SV)."
        )

    def test_axi4_lite_row(self, section_8: str) -> None:
        assert "AXI4-Lite" in section_8, (
            "§8 MUST include a row for AMBA AXI4-Lite."
        )

    def test_apb_row(self, section_8: str) -> None:
        assert "APB" in section_8, (
            "§8 MUST include a row for AMBA APB."
        )

    def test_derive_relationships_present(self, section_8: str) -> None:
        # External-standard rows must be `derive`.
        assert "**derive**" in section_8, (
            "§8 MUST include at least one **derive** relationship."
        )

    def test_mirror_relationships_present(self, section_8: str) -> None:
        # SOS-08-A primitives are consumed as `mirror`.
        assert "**mirror**" in section_8, (
            "§8 MUST include at least one **mirror** relationship "
            "(SOS-08-A primitive consumption)."
        )

    def test_compose_relationship_for_sos_09_b(self, section_8: str) -> None:
        # SOS-09-B address-offset assignment is consumed as `compose`.
        assert "**compose**" in section_8, (
            "§8 MUST include a **compose** relationship (SOS-09-B "
            "address-offset assignment)."
        )

    def test_sos_08_a_primitives_in_matrix(self, section_8: str) -> None:
        # All five composed primitives are matrix rows.
        for primitive in (
            "sos_strobe_latch",
            "sos_dpram_arb",
            "sos_mutex",
            "sos_synchronizer",
            "sos_message_channel",
        ):
            assert primitive in section_8, (
                f"§8 MUST include a row for the SOS-08-A primitive "
                f"`{primitive}`."
            )


# ---------------------------------------------------------------------------
# Cross-phase invariant citations + upstream-doc citations
# ---------------------------------------------------------------------------


class TestUpstreamCitations:
    """The doc cites SOS-09 umbrella + 09-A + 09-B + 08-A as upstream."""

    def test_cites_sos_09_umbrella(self, concepts_text: str) -> None:
        assert "SOS-09-CONCEPTS.md" in concepts_text, (
            "Doc MUST cite the SOS-09 umbrella (SOS-09-CONCEPTS.md)."
        )

    def test_cites_sos_09_a(self, concepts_text: str) -> None:
        assert "SOS-09-A" in concepts_text, (
            "Doc MUST cite SOS-09-A (chart annotation surface) as "
            "the annotation-schema source."
        )

    def test_cites_sos_09_b(self, concepts_text: str) -> None:
        assert "SOS-09-B" in concepts_text, (
            "Doc MUST cite SOS-09-B (CMSIS-SVD emission) — the "
            "silicon-side counterpart that shares address offsets."
        )

    def test_cites_sos_08_a(self, concepts_text: str) -> None:
        assert "SOS-08-A" in concepts_text, (
            "Doc MUST cite SOS-08-A (L0 primitive library) as "
            "the source of the composed primitives."
        )

    def test_cites_inv_s_mem_umbrella(self, concepts_text: str) -> None:
        # Umbrella's INV-S-MEM-1 through 6 are cited.
        assert (
            "INV-S-MEM-1" in concepts_text
            or "INV-S-MEM-2" in concepts_text
            or "INV-S-MEM-3" in concepts_text
        ), (
            "Doc MUST cite at least one of the SOS-09 umbrella "
            "INV-S-MEM-N invariants."
        )

    def test_cites_inv_sos_umbrella(self, concepts_text: str) -> None:
        # SOS-07 INV-SOS-* cross-phase invariants cited.
        assert (
            "INV-SOS-A" in concepts_text
            or "INV-SOS-H" in concepts_text
        ), (
            "Doc MUST cite at least one of the SOS-07 cross-phase "
            "INV-SOS-* invariants."
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

    def test_files_cited_lists_walker_entry_points(
        self, concepts_text: str
    ) -> None:
        # §13 MUST name the existing HDL walker entry points
        # (cited but not modified in this draft).
        assert "transliterate_hdl_vhdl.py" in concepts_text, (
            "Doc MUST cite the existing VHDL walker entry point in "
            "§13 Files cited."
        )
        assert "transliterate_hdl_sv.py" in concepts_text, (
            "Doc MUST cite the existing SystemVerilog walker entry "
            "point in §13 Files cited."
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
    """§9 declares acceptance gates (a)..(i) for the emit path."""

    def test_gates_a_through_i_present(self, section_9: str) -> None:
        # Nine gates covering the contract surface.
        for letter in (
            "(a)", "(b)", "(c)", "(d)", "(e)", "(f)", "(g)", "(h)", "(i)"
        ):
            assert letter in section_9, (
                f"§9 MUST declare gate {letter}."
            )

    def test_gate_names_synthesis_tools(self, section_9: str) -> None:
        # The synthesis-tool coverage gate names the three v1 targets.
        assert "Vivado" in section_9, (
            "§9 acceptance gates MUST name Xilinx Vivado."
        )
        assert "Quartus" in section_9, (
            "§9 acceptance gates MUST name Intel Quartus Pro."
        )
        assert "Yosys" in section_9, (
            "§9 acceptance gates MUST name Yosys."
        )


# ---------------------------------------------------------------------------
# PCDN-SOS-09-001 amendment compliance — no xmlns:sos in SOS-09-E
# ---------------------------------------------------------------------------


class TestPCDN001AmendmentCompliance:
    """SOS-09-E honours PCDN-SOS-09-001 amended 2026-05-25.

    The amendment retracted the `xmlns:sos` URL registration; SOS-09-E
    must not emit any `xmlns:sos` into the RTL output, and must treat
    `sos:` as a JSON-key string prefix inside `other_attributes`, not
    an XML namespace prefix.
    """

    def test_other_attributes_referenced(self, concepts_text: str) -> None:
        # The doc must reference `other_attributes` as the annotation
        # source.
        assert "other_attributes" in concepts_text, (
            "SOS-09-E MUST reference `other_attributes` as the "
            "annotation source (PCDN-SOS-09-001 amended 2026-05-25)."
        )

    def test_no_xmlns_sos_emit_endorsement(self, concepts_text: str) -> None:
        # The doc MUST NOT instruct SOS-09-E to emit `xmlns:sos`
        # into the RTL output.
        # A safe check: the phrase "MUST NOT emit any `xmlns:sos`"
        # (or similar) appears, since the RTL is plain VHDL/SV with
        # no XML at all.
        assert (
            "MUST NOT emit" in concepts_text
            or "MUST NOT" in concepts_text
        ), (
            "Doc SHOULD clarify the xmlns:sos prohibition in the "
            "RTL emission output per PCDN-SOS-09-001 amended."
        )


# ---------------------------------------------------------------------------
# Language + bus textual presence (top-level smoke)
# ---------------------------------------------------------------------------


class TestLanguageAndBusPresence:
    """VHDL-2008 + SV-2017 + AXI4-Lite + APB textually present."""

    def test_vhdl_2008_present(self, concepts_text: str) -> None:
        assert "VHDL-2008" in concepts_text, (
            "Doc MUST name VHDL-2008 as an emitted language."
        )

    def test_systemverilog_2017_present(self, concepts_text: str) -> None:
        assert "SystemVerilog-2017" in concepts_text, (
            "Doc MUST name SystemVerilog-2017 as an emitted language."
        )

    def test_axi4_lite_present(self, concepts_text: str) -> None:
        assert "AXI4-Lite" in concepts_text, (
            "Doc MUST name AMBA AXI4-Lite as an emitted bus interface."
        )

    def test_apb_present(self, concepts_text: str) -> None:
        assert "APB" in concepts_text, (
            "Doc MUST name AMBA APB as an emitted bus interface."
        )

    def test_sos_regfile_template_named(self, concepts_text: str) -> None:
        assert "sos_regfile" in concepts_text, (
            "Doc MUST name the `sos_regfile` template module."
        )

    def test_axi_lite_default(self, concepts_text: str) -> None:
        # AXI4-Lite is the v1 default per §5.1 and PCDN-SOS-09-E-001
        # recommendation.
        # The combination of "AXI4-Lite" and "default" must co-occur.
        assert re.search(
            r"AXI4-Lite.*default|default.*AXI4-Lite",
            concepts_text,
            re.DOTALL,
        ), (
            "Doc MUST identify AXI4-Lite as the v1 default bus "
            "interface."
        )
