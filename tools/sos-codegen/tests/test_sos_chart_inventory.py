"""Structural validation for `docs/inventory/SOS-CHART-INVENTORY.md`.

PCDN-SOS-08-C-007 was ratified 2026-05-25 with an addendum requesting a
chart-inventory + vector-migration audit before the per-`<param>` walker
work lands. The audit doc at `docs/inventory/SOS-CHART-INVENTORY.md` is
the result of that pre-implementation pass. This test module is the
regression guard: it asserts the doc exists, carries the required
sections, catalogues enough chart artifacts to be credible, and has the
substantive content the C-007 implementer relies on.

The test is intentionally STRUCTURAL — it does not re-run the inventory
analysis. The doc itself is the artifact under audit; the test pins its
shape against the dispatch task's deliverable contract.

Cited spec rules:
    - PCDN-SOS-08-C-007 (ratified 2026-05-25, addendum requesting this
      audit).
    - SOS-08-C-CONCEPTS.md (the per-`<param>` port-shape concepts doc
      the audit feeds).

Excluded:
    - Re-walking the chart corpus (the doc already did this — this test
      asserts the doc's claims survive review, not that they're
      independently re-derivable).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


# Repo-root locator: this test lives at
# `tools/sos-codegen/tests/test_sos_chart_inventory.py`; the inventory
# doc lives at `docs/inventory/SOS-CHART-INVENTORY.md`. Walk up three
# parents to reach the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_INVENTORY_PATH = _REPO_ROOT / "docs" / "inventory" / "SOS-CHART-INVENTORY.md"


# Required section headers (anchored to start-of-line "## §N").
_REQUIRED_SECTIONS = [
    "## §0 Header",
    "## §1 Scope",
    "## §2 Methodology",
    "## §3 Chart artifact catalogue",
    "## §4 Payload-bearing event analysis",
    "## §5 Migration manifest",
    "## §6 Generated test vector inventory",
    "## §7 Summary statistics",
    "## §8 Migration sequencing recommendation",
    "## §9 Out-of-scope items",
    "## §10 Change log",
]


@pytest.fixture(scope="module")
def inventory_text() -> str:
    """Read the inventory doc once per test module."""

    assert _INVENTORY_PATH.exists(), (
        f"PCDN-SOS-08-C-007 audit deliverable missing: "
        f"{_INVENTORY_PATH} not found. The dispatch task requires "
        f"this doc be created BEFORE the C-007 walker work lands."
    )
    return _INVENTORY_PATH.read_text(encoding="utf-8")


class TestInventoryDocExists:
    """Smoke check: the audit deliverable is committed."""

    def test_inventory_file_exists(self) -> None:
        assert _INVENTORY_PATH.exists(), (
            f"{_INVENTORY_PATH} is the PCDN-SOS-08-C-007 audit "
            "deliverable; it must exist on this branch."
        )

    def test_inventory_file_non_empty(self, inventory_text: str) -> None:
        # A trivial size floor — the doc has 9 chart entries + 11
        # vector entries + 11 required sections; well over 1 KB.
        assert len(inventory_text) > 1024, (
            "Inventory doc appears truncated; expected substantive "
            "content well over 1 KB."
        )


class TestRequiredSectionsPresent:
    """Each §N section header must appear at the document level."""

    @pytest.mark.parametrize("section_header", _REQUIRED_SECTIONS)
    def test_section_present(
        self, inventory_text: str, section_header: str
    ) -> None:
        # Section headers are at the document's top level (`## `),
        # never indented. Match at line start.
        pattern = re.compile(
            r"^" + re.escape(section_header), re.MULTILINE
        )
        assert pattern.search(inventory_text), (
            f"Required section header missing: {section_header!r}. "
            f"The PCDN-SOS-08-C-007 audit doc must carry sections "
            f"§0..§10 per the dispatch task contract."
        )


class TestChartCatalogue:
    """§3 must catalogue at least 5 chart artifacts."""

    def test_section_3_has_minimum_5_chart_entries(
        self, inventory_text: str
    ) -> None:
        # The §3 catalogue is a markdown table; each catalogued chart
        # row carries the literal `.scxml` substring (the file
        # extension is the most reliable marker since the chart
        # description column always cites the path). Count `.scxml`
        # references inside the §3 block.
        section_3_match = re.search(
            r"^## §3 Chart artifact catalogue\b.*?(?=^## §4 |\Z)",
            inventory_text,
            re.MULTILINE | re.DOTALL,
        )
        assert section_3_match, "§3 section block not extractable"
        section_3 = section_3_match.group(0)
        scxml_refs = section_3.count(".scxml")
        # Each chart is referenced at least once in the table row
        # (chart path); some carry follow-up mentions. The floor
        # of 5 is well below the 9 actual entries.
        assert scxml_refs >= 5, (
            f"§3 must catalogue at least 5 chart artifacts; counted "
            f"{scxml_refs} `.scxml` references in the §3 block. If "
            f"the inventory found fewer, the §2 methodology missed "
            f"a directory — re-scan before commit."
        )


class TestMigrationManifest:
    """§5 must either carry a migration manifest entry, or explicitly
    assert that no chart needs migration with rationale."""

    def test_section_5_has_manifest_or_no_migration_assertion(
        self, inventory_text: str
    ) -> None:
        section_5_match = re.search(
            r"^## §5 Migration manifest\b.*?(?=^## §6 |\Z)",
            inventory_text,
            re.MULTILINE | re.DOTALL,
        )
        assert section_5_match, "§5 section block not extractable"
        section_5 = section_5_match.group(0).lower()

        # Acceptable shape (a): an actual migration manifest with one
        # or more entries. We detect by looking for a `migration` table
        # row or a `event_` port reference, paired with `event` and
        # `param` keywords.
        has_manifest_shape = (
            "param" in section_5
            and "event" in section_5
            and ("table" in section_5 or "|" in section_5 or "manifest" in section_5)
        )
        # Acceptable shape (b): an explicit no-migration assertion
        # with rationale. The dispatch task contract names this case
        # ("OR an explicit 'no charts require migration' assertion
        # with rationale").
        has_no_migration_assertion = (
            "no charts" in section_5 or "no migration" in section_5
        ) and ("rationale" in section_5 or "zero" in section_5)

        assert has_manifest_shape or has_no_migration_assertion, (
            "§5 must either (a) carry a migration manifest with at "
            "least one entry citing events + params + capture sites, "
            "or (b) explicitly assert 'no charts require migration' "
            "with rationale. Neither shape detected."
        )


class TestVectorInventory:
    """§6 must catalogue generated vectors or explicitly note none."""

    def test_section_6_catalogues_vectors_or_notes_none(
        self, inventory_text: str
    ) -> None:
        section_6_match = re.search(
            r"^## §6 Generated test vector inventory\b.*?(?=^## §7 |\Z)",
            inventory_text,
            re.MULTILINE | re.DOTALL,
        )
        assert section_6_match, "§6 section block not extractable"
        section_6 = section_6_match.group(0)

        # Acceptable: at least one `.json` or `.jsonl` reference (vector
        # cited by path), OR an explicit `no generated vectors found`
        # statement.
        has_vector_refs = (
            ".json" in section_6 or ".jsonl" in section_6
        )
        section_6_lower = section_6.lower()
        has_explicit_none = "no generated vectors" in section_6_lower

        assert has_vector_refs or has_explicit_none, (
            "§6 must either catalogue generated vector files (citing "
            "their `.json` or `.jsonl` paths) or explicitly state "
            "'no generated vectors found'."
        )


class TestSummaryStatistics:
    """§7 must contain counts."""

    def test_section_7_has_counts(self, inventory_text: str) -> None:
        section_7_match = re.search(
            r"^## §7 Summary statistics\b.*?(?=^## §8 |\Z)",
            inventory_text,
            re.MULTILINE | re.DOTALL,
        )
        assert section_7_match, "§7 section block not extractable"
        section_7 = section_7_match.group(0)

        # The dispatch task asks §7 to carry "counts" — at minimum
        # the total chart count and the total payload-bearing-event
        # count. Detect by looking for at least three digit
        # occurrences in the section body (numerical statistics).
        digit_count = len(re.findall(r"\b\d+\b", section_7))
        assert digit_count >= 3, (
            f"§7 must carry numerical counts (total charts, total "
            f"payload-bearing events, total migration-affected "
            f"references); only {digit_count} digit token(s) found."
        )

        # Also assert the section names what it counts. Look for
        # the word `total` as the canonical marker.
        assert "Total" in section_7 or "total" in section_7, (
            "§7 should call its numbers 'total ...' so a reader "
            "can see what's being counted."
        )


class TestSequencingRecommendation:
    """§8 must carry a sequencing recommendation — actionable steps."""

    def test_section_8_has_actionable_steps(
        self, inventory_text: str
    ) -> None:
        section_8_match = re.search(
            r"^## §8 Migration sequencing recommendation\b.*?(?=^## §9 |\Z)",
            inventory_text,
            re.MULTILINE | re.DOTALL,
        )
        assert section_8_match, "§8 section block not extractable"
        section_8 = section_8_match.group(0)

        # A sequencing recommendation should carry ordered steps.
        # Detect via numbered-list markers (`1.`, `2.`, etc.) — at
        # least two ordered items.
        ordered_items = re.findall(r"^\s*\d+\.\s", section_8, re.MULTILINE)
        assert len(ordered_items) >= 2, (
            f"§8 must carry an ordered list of sequencing steps; "
            f"only {len(ordered_items)} numbered item(s) found."
        )


class TestChangeLogPresent:
    """§10 must carry a dated change-log entry per the dispatch task."""

    def test_change_log_has_date(self, inventory_text: str) -> None:
        section_10_match = re.search(
            r"^## §10 Change log\b.*\Z",
            inventory_text,
            re.MULTILINE | re.DOTALL,
        )
        assert section_10_match, "§10 section block not extractable"
        section_10 = section_10_match.group(0)

        # ISO date pattern YYYY-MM-DD. The dispatch task requires
        # `2026-05-25 — wave-1 inventory complete ...` as the dated
        # entry.
        iso_date = re.search(r"\b202\d-\d{2}-\d{2}\b", section_10)
        assert iso_date is not None, (
            "§10 change log must carry an ISO-format dated entry "
            "(YYYY-MM-DD) per the dispatch task's deliverable "
            "contract."
        )
