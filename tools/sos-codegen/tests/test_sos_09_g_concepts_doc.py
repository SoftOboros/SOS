"""SOS-09-G concepts-doc assertions.

@spec  docs/concepts/SOS-09-G-CONCEPTS.md (sub-phase, drafted 2026-05-25)
@spec  docs/concepts/SOS-09-CONCEPTS.md §6 SOS-09-G description; §5.4
       protection-zone enum (privileged / unprivileged at v1 per
       PCDN-SOS-09-006); PCDN-SOS-09-001 amended 2026-05-25
       (channel annotations on `other_attributes`, `sos:`-prefixed keys).

This module verifies the SOS-09-G concepts doc satisfies the shape
contract of the Spec-Before-Code Planning Discipline phase document
shape (parent CLAUDE.md / SOS-08-A-CONCEPTS.md precedent):

  - The doc exists at `docs/concepts/SOS-09-G-CONCEPTS.md`.
  - Required sections §0..§16 are present.
  - §5 (frozen decisions) names the ARMv7-M MPU target with the
    correct per-target region counts (8 on M3/M4/M0+, 16 on M7).
  - §5 names the `Device-nGnRnE` memory attribute default.
  - §5 maps `privileged` → AP=0b001 and `unprivileged` → AP=0b011.
  - §7 declares at least 4 INV-S-MEM-G-N invariants.
  - §15 files at least 3 open PCDNs with Standards Action policy.
  - §8 cites ARM DDI 0403 as `derive`.
  - §16 has a 2026-05-25 draft-status entry.

@invariants  INV-SOS-A (chart-as-source) — preserved: the MPU table
             is a build output traceable to chart-declared `sos:zone`.
@invariants  INV-S-MEM-3 (protection is end-to-end) — closed by
             SOS-09-G + SOS-09-E being co-emitted.
@invariants  INV-S-MEM-G-1 through 4 — declared in this doc's §7.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Repo-root resolution: this test file lives at
# tools/sos-codegen/tests/test_sos_09_g_concepts_doc.py
# → repo root is three parents up.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DOC_PATH = _REPO_ROOT / "docs" / "concepts" / "SOS-09-G-CONCEPTS.md"


@pytest.fixture(scope="module")
def doc_text() -> str:
    if not _DOC_PATH.exists():
        pytest.fail(f"SOS-09-G concepts doc missing at {_DOC_PATH}")
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
# Existence + section presence
# ---------------------------------------------------------------------------


class TestDocExists:
    """The doc exists and carries the expected top-level heading."""

    def test_doc_present(self) -> None:
        assert _DOC_PATH.exists(), (
            f"Expected SOS-09-G concepts doc at {_DOC_PATH}."
        )

    def test_top_level_heading(self, doc_text: str) -> None:
        assert doc_text.startswith("# SOS-09-G"), (
            "Doc MUST begin with `# SOS-09-G` top-level heading."
        )

    def test_status_ratified(self, doc_text: str) -> None:
        # Post-2026-05-25 ratification, the top-of-file status MUST
        # be 🟢 ratified (the original 🟡 drafted marker was flipped
        # when the four PCDNs walked).
        head = doc_text.split("## 0.", 1)[0]
        assert "🟢" in head and "ratified" in head.lower(), (
            "Doc top-of-file MUST carry a 🟢 ratified status badge "
            "post-2026-05-25 PCDN ratification."
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
            (7, "Cross-sub-phase invariants"),
            (8, "Standards integration"),
            (9, "Acceptance"),
            (10, "Reconciliation"),
            (11, "Non-goals"),
            (13, "Files cited"),
            (14, "Unblocks"),
            (15, "Pending Concept Decision Notices"),
            (16, "Change log"),
        ],
    )
    def test_section_present(
        self, doc_text: str, section_num: int, heading_text: str
    ) -> None:
        # Match `## <N>. <some text containing the keyword phrase>`.
        # Heading_text comparison is case-insensitive on the keyword.
        pattern = re.compile(
            rf"^## {section_num}\.\s+.*$", re.MULTILINE
        )
        headings = pattern.findall(doc_text)
        assert headings, (
            f"Doc MUST carry a `## {section_num}.` section heading."
        )
        # At least one heading at this level mentions the expected keyword.
        keyword = heading_text.lower()
        found = any(keyword in h.lower() for h in headings)
        assert found, (
            f"Section {section_num} heading SHOULD reference the keyword "
            f"`{heading_text}` (case-insensitive). Found: {headings}"
        )


# ---------------------------------------------------------------------------
# §5 frozen decisions — target MPU + per-target region counts
# ---------------------------------------------------------------------------


class TestSection5TargetMPU:
    """§5 names ARMv7-M MPU with the correct per-target region counts."""

    def test_armv7m_named(self, doc_text: str) -> None:
        section5 = _section_slice(doc_text, 5)
        assert "ARMv7-M" in section5, (
            "§5 MUST name `ARMv7-M MPU` as the v1 target."
        )

    def test_region_count_8_for_m3_m4(self, doc_text: str) -> None:
        section5 = _section_slice(doc_text, 5)
        # 8 regions on Cortex-M3, Cortex-M4 (CMSIS_NUMBER 0-7).
        assert "8 MPU regions" in section5 or "8 regions" in section5, (
            "§5 MUST name `8 MPU regions` for Cortex-M3 / M4 targets."
        )
        assert "Cortex-M3" in section5 and "Cortex-M4" in section5, (
            "§5 MUST name Cortex-M3 and Cortex-M4 as 8-region targets."
        )

    def test_region_count_16_for_m7(self, doc_text: str) -> None:
        section5 = _section_slice(doc_text, 5)
        assert "16 MPU regions" in section5 or "16 regions" in section5, (
            "§5 MUST name `16 MPU regions` for Cortex-M7."
        )
        assert "Cortex-M7" in section5, (
            "§5 MUST name Cortex-M7 as a 16-region target."
        )

    def test_cmsis_region_number_cited(self, doc_text: str) -> None:
        section5 = _section_slice(doc_text, 5)
        assert "MPU_REGION_NUMBER" in section5, (
            "§5 MUST cite the CMSIS `MPU_REGION_NUMBER` macro name "
            "when stating per-target region counts."
        )

    def test_trustzone_deferred(self, doc_text: str) -> None:
        section5 = _section_slice(doc_text, 5)
        # PCDN-SOS-09-006 ratified two-zone v1 scope; TrustZone deferred.
        assert "TrustZone" in section5, (
            "§5 MUST mention TrustZone (Cortex-M33+) as out-of-scope at v1."
        )


# ---------------------------------------------------------------------------
# §5 frozen decisions — Device-nGnRnE attribute default + AP mapping
# ---------------------------------------------------------------------------


class TestSection5DeviceAttribute:
    """§5 names `Device-nGnRnE` as the v1 memory attribute default."""

    def test_device_ngnrne_named(self, doc_text: str) -> None:
        section5 = _section_slice(doc_text, 5)
        assert "Device-nGnRnE" in section5, (
            "§5 MUST name `Device-nGnRnE` as the v1 attribute default."
        )

    def test_strongly_ordered_language(self, doc_text: str) -> None:
        section5 = _section_slice(doc_text, 5)
        assert (
            "strongly-ordered" in section5.lower()
            or "non-cacheable" in section5.lower()
        ), (
            "§5 SHOULD describe `Device-nGnRnE` as strongly-ordered / "
            "non-cacheable for register-mapped peripherals."
        )


class TestSection5APMapping:
    """§5 maps `privileged` → AP=0b001 and `unprivileged` → AP=0b011."""

    def test_privileged_ap_001(self, doc_text: str) -> None:
        section5 = _section_slice(doc_text, 5)
        # `privileged` zone maps to AP=0b001 (or 001) — the encoding
        # MUST appear in the same paragraph/sentence as the `privileged`
        # label. Allow either `0b001` literal or the bare `001` digits.
        # Search any line that pairs "privileged" with "001".
        pattern = re.compile(
            r"privileged.{0,200}?(?:0b)?001(?!\d)",
            re.IGNORECASE | re.DOTALL,
        )
        assert pattern.search(section5) is not None, (
            "§5 MUST map `privileged` → AP=0b001 (RW priv, no unpriv)."
        )

    def test_unprivileged_ap_011(self, doc_text: str) -> None:
        section5 = _section_slice(doc_text, 5)
        pattern = re.compile(
            r"unprivileged.{0,200}?(?:0b)?011(?!\d)",
            re.IGNORECASE | re.DOTALL,
        )
        assert pattern.search(section5) is not None, (
            "§5 MUST map `unprivileged` → AP=0b011 (RW full)."
        )

    def test_ap_field_named(self, doc_text: str) -> None:
        section5 = _section_slice(doc_text, 5)
        # The `AP[2:0]` CMSIS field name or equivalent MUST be cited so a
        # reviewer can locate the encoding in the ARM ARM directly.
        assert "AP[2:0]" in section5 or "AP=" in section5, (
            "§5 MUST cite the `AP[2:0]` CMSIS access-permission field name."
        )


# ---------------------------------------------------------------------------
# §5 frozen decisions — SRD policy + emission outputs + install hook
# ---------------------------------------------------------------------------


class TestSection5SRDPolicy:
    """§5 declares the sub-region disable (SRD) bitmap policy."""

    def test_srd_named(self, doc_text: str) -> None:
        section5 = _section_slice(doc_text, 5)
        assert "SRD" in section5, (
            "§5 MUST name the SRD (sub-region disable) bitmap."
        )

    def test_srd_mask_outside_footprint(self, doc_text: str) -> None:
        section5 = _section_slice(doc_text, 5)
        # Set bits disable sub-regions outside the channel footprint; clear
        # bits keep sub-regions inside enabled.
        assert "outside" in section5.lower() and "footprint" in section5.lower(), (
            "§5 MUST describe SRD masking sub-regions outside the channel "
            "footprint."
        )


class TestSection5EmissionOutputs:
    """§5 declares C array + Rust constant emission outputs."""

    def test_c_array_named(self, doc_text: str) -> None:
        section5 = _section_slice(doc_text, 5)
        assert "sos_mpu_table" in section5, (
            "§5 MUST name the `sos_mpu_table` C array emission output."
        )

    def test_rust_constant_named(self, doc_text: str) -> None:
        section5 = _section_slice(doc_text, 5)
        assert "SOS_MPU_TABLE" in section5, (
            "§5 MUST name the `SOS_MPU_TABLE` Rust constant emission "
            "output."
        )

    def test_install_hook_named(self, doc_text: str) -> None:
        """Per ERRATA-007 (commit `92b1120`) the canonical name is
        `apply_mpu_config()`. §5 normative prose now uses the canonical
        name; the historical `sos_mpu_install` name survives only in
        pre-2026-05-27 §15/§16 entries (institutional memory)."""
        section5 = _section_slice(doc_text, 5)
        assert "apply_mpu_config" in section5, (
            "§5 MUST name the `apply_mpu_config()` runtime hook "
            "(canonical per ERRATA-007)."
        )

    def test_install_idempotent(self, doc_text: str) -> None:
        section5 = _section_slice(doc_text, 5)
        assert "idempotent" in section5.lower(), (
            "§5 MUST state that `apply_mpu_config()` is idempotent."
        )


# ---------------------------------------------------------------------------
# §7 cross-sub-phase invariants
# ---------------------------------------------------------------------------


class TestSection7Invariants:
    """§7 declares at least 4 INV-S-MEM-G-N invariants."""

    def test_at_least_four_invariants(self, doc_text: str) -> None:
        section7 = _section_slice(doc_text, 7)
        # Find INV-S-MEM-G-N bullets.
        pattern = re.compile(r"INV-S-MEM-G-(\d+)")
        ids = set(pattern.findall(section7))
        assert len(ids) >= 4, (
            f"§7 MUST declare at least 4 INV-S-MEM-G-N invariants; "
            f"found {sorted(ids)}."
        )

    @pytest.mark.parametrize(
        "inv_id,keyword",
        [
            ("INV-S-MEM-G-1", "privileged"),
            ("INV-S-MEM-G-2", "exactly"),
            ("INV-S-MEM-G-3", "idempotent"),
            ("INV-S-MEM-G-4", "violation"),
        ],
    )
    def test_invariant_present(
        self, doc_text: str, inv_id: str, keyword: str
    ) -> None:
        section7 = _section_slice(doc_text, 7)
        assert inv_id in section7, (
            f"§7 MUST declare {inv_id}."
        )
        # The keyword characterising the invariant SHOULD appear in §7.
        assert keyword.lower() in section7.lower(), (
            f"§7 {inv_id} SHOULD discuss the `{keyword}` concept."
        )

    def test_inv_g1_names_AP_001(self, doc_text: str) -> None:
        section7 = _section_slice(doc_text, 7)
        # INV-S-MEM-G-1 mandates AP=0b001 for privileged channels.
        assert "0b001" in section7 or "AP=" in section7, (
            "§7 INV-S-MEM-G-1 SHOULD cite the AP=0b001 encoding."
        )

    def test_inv_g2_forbids_over_protection(self, doc_text: str) -> None:
        section7 = _section_slice(doc_text, 7)
        # Over-protection forbidden because of address-space leak.
        assert "leaks" in section7.lower() or "leak" in section7.lower(), (
            "§7 INV-S-MEM-G-2 SHOULD explain over-protection is forbidden "
            "due to address-space-layout leakage."
        )


# ---------------------------------------------------------------------------
# §8 standards integration matrix
# ---------------------------------------------------------------------------


class TestSection8StandardsMatrix:
    """§8 cites ARM DDI 0403 as `derive`; CMSIS / cortex-m as `mirror`."""

    def test_arm_ddi_0403_cited(self, doc_text: str) -> None:
        section8 = _section_slice(doc_text, 8)
        assert "DDI 0403" in section8, (
            "§8 MUST cite ARM DDI 0403 (ARMv7-M Architecture Reference "
            "Manual) as the upstream MPU spec authority."
        )

    def test_arm_ddi_0403_derive(self, doc_text: str) -> None:
        section8 = _section_slice(doc_text, 8)
        # The row authority is `derive` — SOS-09-G emits configurations
        # valid per the ARM ARM; ARM owns the spec.
        # The relationship is declared in the same row as the spec.
        # Look for the substring pattern.
        pattern = re.compile(
            r"DDI 0403.*?\*\*derive\*\*", re.DOTALL
        )
        assert pattern.search(section8) is not None, (
            "§8 MUST declare the ARM DDI 0403 row with `derive` "
            "relationship."
        )

    def test_cmsis_core_mirror(self, doc_text: str) -> None:
        section8 = _section_slice(doc_text, 8)
        assert "CMSIS-Core" in section8 or "CMSIS" in section8, (
            "§8 MUST cite CMSIS-Core (MPU_RBAR/MPU_RASR encoding)."
        )
        assert "**mirror**" in section8, (
            "§8 MUST declare at least one row with `mirror` relationship "
            "(CMSIS-Core / cortex-m / sos:zone / SOS-00 §6)."
        )

    def test_sos_zone_mirror(self, doc_text: str) -> None:
        section8 = _section_slice(doc_text, 8)
        assert "sos:zone" in section8, (
            "§8 MUST cite the `sos:zone` annotation as a consumed "
            "(mirror) row from SOS-09-A."
        )

    def test_sos_09_b_compose(self, doc_text: str) -> None:
        section8 = _section_slice(doc_text, 8)
        assert "SOS-09-B" in section8, (
            "§8 MUST cite SOS-09-B's address-offset assignment as input."
        )
        assert "**compose**" in section8, (
            "§8 MUST declare the SOS-09-B row with `compose` relationship."
        )


# ---------------------------------------------------------------------------
# §15 PCDNs — at least 3 with Standards Action policy
# ---------------------------------------------------------------------------


class TestSection15PCDNs:
    """§15 files at least 3 open PCDNs with Standards Action registration."""

    def test_at_least_three_pcdns(self, doc_text: str) -> None:
        section15 = _section_slice(doc_text, 15)
        pattern = re.compile(r"PCDN-SOS-09-G-(\d{3})")
        ids = set(pattern.findall(section15))
        assert len(ids) >= 3, (
            f"§15 MUST file at least 3 PCDN-SOS-09-G-NNN entries; "
            f"found {sorted(ids)}."
        )

    def test_standards_action_declared(self, doc_text: str) -> None:
        section15 = _section_slice(doc_text, 15)
        assert "Standards Action" in section15, (
            "§15 MUST declare Standards Action registration policy for "
            "the PCDN set."
        )

    @pytest.mark.parametrize(
        "pcdn_id,keyword",
        [
            ("PCDN-SOS-09-G-001", "budget"),
            ("PCDN-SOS-09-G-002", "background"),
            ("PCDN-SOS-09-G-003", "attribute"),
        ],
    )
    def test_named_pcdn_present(
        self, doc_text: str, pcdn_id: str, keyword: str
    ) -> None:
        section15 = _section_slice(doc_text, 15)
        assert pcdn_id in section15, (
            f"§15 MUST file {pcdn_id}."
        )
        # The PCDN paragraph SHOULD discuss the named keyword.
        assert keyword.lower() in section15.lower(), (
            f"§15 {pcdn_id} SHOULD discuss the `{keyword}` concept."
        )


# ---------------------------------------------------------------------------
# §16 change log
# ---------------------------------------------------------------------------


class TestSection16ChangeLog:
    """§16 carries a 2026-05-25 draft-status entry."""

    def test_dated_entry_present(self, doc_text: str) -> None:
        section16 = _section_slice(doc_text, 16)
        assert "### 2026-05-25" in section16, (
            "§16 MUST carry a `### 2026-05-25` dated entry."
        )

    def test_initial_draft_entry(self, doc_text: str) -> None:
        section16 = _section_slice(doc_text, 16)
        # First entry SHOULD say "Initial draft".
        assert "Initial draft" in section16, (
            "§16 first entry SHOULD say `Initial draft`."
        )

    def test_initial_draft_preserved(self, doc_text: str) -> None:
        # The Initial draft change-log entry MUST be preserved as
        # institutional memory even post-ratification; the per-doc
        # 🟢 ratified entry sits AFTER the initial-draft entry.
        section16 = _section_slice(doc_text, 16)
        assert "🟡" in section16 and "drafted" in section16, (
            "§16 MUST preserve the Initial draft 🟡 drafted status "
            "as institutional memory."
        )

    def test_ratification_entry_present(self, doc_text: str) -> None:
        """§16 MUST carry a 🟢 Ratified entry post-2026-05-25 walkthrough."""
        section16 = _section_slice(doc_text, 16)
        assert "### 2026-05-25 — Ratified" in section16, (
            "§16 MUST carry a `### 2026-05-25 — Ratified` entry."
        )
        assert "🟢" in section16, (
            "§16 ratification entry MUST include a 🟢 ratified marker."
        )


# ---------------------------------------------------------------------------
# §9 acceptance gates
# ---------------------------------------------------------------------------


class TestSection9AcceptanceGates:
    """§9 names the v1 acceptance gates (a)-(d)."""

    def test_gate_a_clang_cargo(self, doc_text: str) -> None:
        section9 = _section_slice(doc_text, 9)
        assert "(a)" in section9, "§9 MUST name gate (a)."
        # Gate (a) requires clang + cargo check.
        assert "clang" in section9 and "cargo check" in section9, (
            "§9 gate (a) MUST cite `clang` (C) and `cargo check` (Rust)."
        )

    def test_gate_b_cocotb(self, doc_text: str) -> None:
        section9 = _section_slice(doc_text, 9)
        assert "(b)" in section9, "§9 MUST name gate (b)."
        assert "cocotb" in section9.lower(), (
            "§9 gate (b) MUST cite the cocotb co-sim framework."
        )

    def test_gate_c_idempotency(self, doc_text: str) -> None:
        section9 = _section_slice(doc_text, 9)
        assert "(c)" in section9, "§9 MUST name gate (c)."
        assert "idempot" in section9.lower(), (
            "§9 gate (c) MUST cite idempotency."
        )

    def test_gate_d_bench_deferred(self, doc_text: str) -> None:
        section9 = _section_slice(doc_text, 9)
        assert "(d)" in section9, "§9 MUST name gate (d)."
        assert "bench" in section9.lower(), (
            "§9 gate (d) MUST cite bench-validation."
        )
        assert "defer" in section9.lower(), (
            "§9 gate (d) SHOULD state bench-validation is deferred."
        )
