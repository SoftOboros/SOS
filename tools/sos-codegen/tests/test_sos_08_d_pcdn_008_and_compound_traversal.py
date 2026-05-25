"""SOS-08-D post-wave-4 follow-up doc assertions.

@spec  docs/concepts/SOS-08-D-CONCEPTS.md §14 PCDN-SOS-08-D-008
       (`<sos:clock_domains>` element shape, post-wave-1 follow-up).
@spec  docs/concepts/SOS-08-D-CONCEPTS.md §15 2026-05-25 entry
       (post-wave-4 follow-ups: PCDN-SOS-08-D-008 + compound
       traversal-order pin).
@spec  docs/concepts/SOS-08-D-CONCEPTS.md §4 source-of-truth map row
       for compound-child traversal order (relationship `mirror`).

This module verifies the two doc-only follow-ups landed intact:

  Issue A — PCDN-SOS-08-D-008 formally declares the
            ``<sos:clock_domains>`` element shape so the two wave-4
            walkers (`SOS08D4ms` at 1dc5649; `SOS08E3m` at c2aa1cf)
            reference a single normative source rather than each
            re-deriving the contract.
  Issue B — Compound cross-invariant child-traversal order is
            normatively pinned in the alphabetic operator order
            ``and / implies / not / or`` (with state_ref leaves
            first); cites ``_collect_compound_children`` at
            ``tools/sos-codegen/transliterate_sva_bind.py`` as the
            implementation locus.

The doc-amendments also add a §4 source-of-truth map row recording
the SOS-08-D ↔ scjson-loader relationship for compound-child
traversal order (relationship ``mirror`` per §0 standards-integration
discipline).

@invariants  INV-S-HDL-D-1 through D-6 (preserved by doc-only entry)
@invariants  INV-SOS-H (chart vocabulary survives in the new PCDN
             ratification + §15 amendment language)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Repo-root resolution: this test file lives at
# tools/sos-codegen/tests/test_sos_08_d_pcdn_008_and_compound_traversal.py
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


# ---------------------------------------------------------------------------
# §14 PCDN-SOS-08-D-008 assertions
# ---------------------------------------------------------------------------


def test_pcdn_008_entry_exists(concepts_text: str) -> None:
    """The new PCDN-SOS-08-D-008 entry lives in §14 with the canonical
    title fragment naming the ``<sos:clock_domains>`` element shape."""
    assert "PCDN-SOS-08-D-008" in concepts_text
    assert "<sos:clock_domains>" in concepts_text
    # The entry should appear in §14 — verify it sits before §15.
    pcdn_idx = concepts_text.index("PCDN-SOS-08-D-008")
    changelog_idx = concepts_text.index("## 15. Change log")
    # The §14 entry must appear before §15 header. (A second cite in
    # §15 is expected and unrelated to this assertion.)
    assert pcdn_idx < changelog_idx, (
        "PCDN-SOS-08-D-008 must be filed in §14 before §15"
    )


def test_pcdn_008_declares_element_shape(concepts_text: str) -> None:
    """PCDN-SOS-08-D-008's recommendation pins the element shape with
    the per-clock child element and required attributes."""
    # Extract the PCDN-008 paragraph (one bullet item — ends at the next
    # bullet or the section header).
    match = re.search(
        r"\*\*PCDN-SOS-08-D-008[^\n]*\*\*[\s\S]+?(?=\n- \*\*PCDN-|\n## )",
        concepts_text,
    )
    assert match is not None, "Could not locate PCDN-SOS-08-D-008 entry body"
    entry = match.group(0)
    assert "<sos:clock_domains>" in entry
    assert "<sos:clock" in entry
    assert "name=" in entry
    assert "period_ns" in entry
    assert "duty_cycle" in entry


def test_pcdn_008_lists_three_union_sources(concepts_text: str) -> None:
    """The chart-vocab clock-id set is the union of three sources:
    (a) the new element's declared names, (b) region ``clock=``
    annotations per PCDN-SOS-08-010, (c) the chart-top reference
    ``clk``."""
    match = re.search(
        r"\*\*PCDN-SOS-08-D-008[^\n]*\*\*[\s\S]+?(?=\n- \*\*PCDN-|\n## )",
        concepts_text,
    )
    assert match is not None
    entry = match.group(0)
    # Source (a): the new <sos:clock_domains> block.
    assert "<sos:clock_domains>" in entry
    # Source (b): region clock= attributes per PCDN-SOS-08-010.
    assert "PCDN-SOS-08-010" in entry
    assert "region" in entry and "clock=" in entry
    # Source (c): chart-top reference clk.
    assert "chart-top reference" in entry
    assert "`clk`" in entry


def test_pcdn_008_registration_policy_standards_action(
    concepts_text: str,
) -> None:
    """The PCDN names Standards Action as the registration policy for
    the new element."""
    match = re.search(
        r"\*\*PCDN-SOS-08-D-008[^\n]*\*\*[\s\S]+?(?=\n- \*\*PCDN-|\n## )",
        concepts_text,
    )
    assert match is not None
    entry = match.group(0)
    assert "Standards Action" in entry


def test_pcdn_008_cites_both_wave_4_commits(concepts_text: str) -> None:
    """The PCDN entry names both surfacing commits — either by SHA
    (``1dc5649`` / ``c2aa1cf``) or by commit subject (`SOS08D4ms` /
    `SOS08E3m`)."""
    match = re.search(
        r"\*\*PCDN-SOS-08-D-008[^\n]*\*\*[\s\S]+?(?=\n- \*\*PCDN-|\n## )",
        concepts_text,
    )
    assert match is not None
    entry = match.group(0)
    cites_d4ms = ("1dc5649" in entry) or ("SOS08D4ms" in entry)
    cites_e3m = ("c2aa1cf" in entry) or ("SOS08E3m" in entry)
    assert cites_d4ms, (
        "PCDN-SOS-08-D-008 must cite the SOS08D4ms surfacing commit"
    )
    assert cites_e3m, (
        "PCDN-SOS-08-D-008 must cite the SOS08E3m surfacing commit"
    )


# ---------------------------------------------------------------------------
# §15 2026-05-25 amendment assertions
# ---------------------------------------------------------------------------


def _extract_2026_05_25_entry(text: str) -> str:
    """Slice the 2026-05-25 §15 entry body."""
    pat = (
        r"### 2026-05-25 — Post-wave-4 follow-ups[\s\S]+?"
        r"(?=\n### \d{4}-\d{2}-\d{2}|\Z)"
    )
    match = re.search(pat, text)
    assert match is not None, "2026-05-25 §15 entry not found"
    return match.group(0)


def test_changelog_2026_05_25_entry_exists(concepts_text: str) -> None:
    """A §15 entry dated 2026-05-25 names both Issue A and Issue B."""
    entry = _extract_2026_05_25_entry(concepts_text)
    assert "Issue A" in entry
    assert "Issue B" in entry
    # Issue A is the PCDN-SOS-08-D-008 filing; Issue B is the
    # compound-traversal-order pin.
    assert "PCDN-SOS-08-D-008" in entry
    assert (
        "traversal" in entry
        or "traverse" in entry
        or "traversal-order" in entry
    )


def test_issue_a_cites_wave_4_commits(concepts_text: str) -> None:
    """Issue A's body cites the two wave-4 commits that surfaced the
    PCDN — by SHA or by commit subject."""
    entry = _extract_2026_05_25_entry(concepts_text)
    # Slice Issue A only (up to "**Issue B").
    issue_a_match = re.search(
        r"\*\*Issue A[\s\S]+?(?=\*\*Issue B)", entry
    )
    assert issue_a_match is not None, "Issue A block not found"
    issue_a = issue_a_match.group(0)
    cites_d4ms = ("1dc5649" in issue_a) or ("SOS08D4ms" in issue_a)
    cites_e3m = ("c2aa1cf" in issue_a) or ("SOS08E3m" in issue_a)
    assert cites_d4ms, "Issue A must cite SOS08D4ms (1dc5649)"
    assert cites_e3m, "Issue A must cite SOS08E3m (c2aa1cf)"


def test_issue_b_lists_four_boolean_operators_in_alphabetic_order(
    concepts_text: str,
) -> None:
    """Issue B explicitly lists the four boolean operators ``and``,
    ``implies``, ``not``, ``or`` in alphabetic order."""
    entry = _extract_2026_05_25_entry(concepts_text)
    issue_b_match = re.search(
        r"\*\*Issue B[\s\S]+?(?=\*\*Authority boundary update|"
        r"\*\*Wave-4 commit cross-references|\*\*Test coverage|"
        r"Status: |\Z)",
        entry,
    )
    assert issue_b_match is not None, "Issue B block not found"
    issue_b = issue_b_match.group(0)
    # Search for the alphabetic operator order — tolerant of code-tick
    # wrapping and commas.
    pat = re.compile(
        r"`?and`?\s*,\s*`?implies`?\s*,\s*`?not`?\s*,\s*`?or`?",
        re.IGNORECASE,
    )
    assert pat.search(issue_b), (
        "Issue B must list the four operators in alphabetic order "
        "`and`, `implies`, `not`, `or`"
    )


def test_issue_b_cites_collect_compound_children_by_path(
    concepts_text: str,
) -> None:
    """Issue B cites ``_collect_compound_children`` along with its
    implementing file path so future readers can navigate directly."""
    entry = _extract_2026_05_25_entry(concepts_text)
    assert "_collect_compound_children" in entry
    assert "tools/sos-codegen/transliterate_sva_bind.py" in entry


def test_issue_b_pins_state_ref_leaves_first(concepts_text: str) -> None:
    """Issue B normatively states that ``<sos:state_ref>`` leaves are
    traversed first, before the boolean operators."""
    entry = _extract_2026_05_25_entry(concepts_text)
    issue_b_match = re.search(
        r"\*\*Issue B[\s\S]+?(?=\*\*Authority boundary update|"
        r"\*\*Wave-4 commit cross-references|\*\*Test coverage|"
        r"Status: |\Z)",
        entry,
    )
    assert issue_b_match is not None
    issue_b = issue_b_match.group(0)
    # Either "state_ref> leaves first" or "leaves first" near state_ref.
    assert "state_ref" in issue_b
    assert "leaves first" in issue_b or "leaves-first" in issue_b


# ---------------------------------------------------------------------------
# §4 source-of-truth map authority-boundary row
# ---------------------------------------------------------------------------


def test_source_of_truth_row_compound_traversal_order_mirror(
    concepts_text: str,
) -> None:
    """The §4 source-of-truth map carries a row recording the
    compound-child traversal-order relationship as ``mirror`` between
    SOS-08-D and the scjson loader."""
    # Slice §4 only.
    map_match = re.search(
        r"## 4\. Source-of-truth map[\s\S]+?(?=## 5\.)",
        concepts_text,
    )
    assert map_match is not None, "§4 source-of-truth map not found"
    map_text = map_match.group(0)
    # Row must name the concept + the scjson-loader authority + mirror.
    assert "Compound-child traversal order" in map_text
    assert "scjson loader" in map_text
    assert "mirror" in map_text.lower()


def test_source_of_truth_row_names_alphabetic_operator_order(
    concepts_text: str,
) -> None:
    """The §4 row references the canonical alphabetic operator order
    so a reader of §4 alone can resolve the rule without scrolling to
    §15."""
    map_match = re.search(
        r"## 4\. Source-of-truth map[\s\S]+?(?=## 5\.)",
        concepts_text,
    )
    assert map_match is not None
    map_text = map_match.group(0)
    pat = re.compile(
        r"`?and`?\s*,\s*`?implies`?\s*,\s*`?not`?\s*,\s*`?or`?",
        re.IGNORECASE,
    )
    assert pat.search(map_text), (
        "§4 row must list `and`, `implies`, `not`, `or` in alphabetic order"
    )


def test_changelog_authority_boundary_update_mentions_mirror(
    concepts_text: str,
) -> None:
    """The §15 entry's authority-boundary-update paragraph names the
    ``mirror`` relationship explicitly."""
    entry = _extract_2026_05_25_entry(concepts_text)
    assert "Authority boundary update" in entry
    # Match "**mirror**" or "mirror" near the authority-boundary
    # paragraph.
    boundary_match = re.search(
        r"\*\*Authority boundary update[\s\S]+?(?=\n\*\*|Status: |\Z)",
        entry,
    )
    assert boundary_match is not None
    boundary = boundary_match.group(0).lower()
    assert "mirror" in boundary
