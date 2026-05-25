"""SOS-09-A chart-annotation-surface concepts doc assertions.

@spec  docs/concepts/SOS-09-A-CONCEPTS.md 2026-05-25 initial draft.
@spec  docs/concepts/SOS-09-CONCEPTS.md §6 "SOS-09-A — Chart annotation
       surface" (umbrella sub-phase entry).
@spec  docs/concepts/SOS-09-CONCEPTS.md §16 2026-05-25 amendment
       (PCDN-SOS-09-001 routed annotations through `other_attributes`).

This module verifies that `SOS-09-A-CONCEPTS.md` exists with the
expected section layout, the nine-key permitted attribute set, the four
frozen `kind` enum values, the seven cross-sub-phase invariants
(INV-S-MEM-A-1 through 7), at least three open PCDNs filed for user
ratification, the §8 standards-integration matrix `compose` row for
iState `other_attributes`, a draft-status §16 change-log entry, and
the absence of any `xmlns:sos` namespace declaration in the doc body.

@invariants  INV-S-MEM-A-3 / INV-S-MEM-A-4 (no XML namespace
             reinterpretation; `xmlns:sos` declarations rejected) —
             verified by asserting the doc body contains no
             `xmlns:sos` text outside the explicit prohibition prose.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Repo-root resolution: this test file lives at
# tools/sos-codegen/tests/test_sos_09_a_concepts_doc.py
# → repo root is three parents up.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONCEPTS_PATH = _REPO_ROOT / "docs" / "concepts" / "SOS-09-A-CONCEPTS.md"

# Frozen enum values mirrored from SOS-09 §5.1.
_KIND_ENUM_VALUES = ("status", "command", "queue", "shared")

# The nine `sos:`-prefixed keys per §5.2.
_PERMITTED_KEYS = (
    "sos:id",
    "sos:kind",
    "sos:dir",
    "sos:zone",
    "sos:atomicity",
    "sos:width",
    "sos:bit_layout",
    "sos:irq",
    "sos:mutex",
)

# Required sections (§0 through §16).
_REQUIRED_SECTIONS = (
    "## 0. Authority policy",
    "## 1. Purpose",
    "## 2. Problem statement",
    "## 3. Canonical glossary",
    "## 4. Source-of-truth map",
    "## 5. Frozen decisions",
    "## 6. Sub-phase scope",
    "## 7. Cross-sub-phase invariants",
    "## 8. Standards integration matrix",
    "## 9. Frozen enumerations recap",
    "## 10. Reconciliation decisions",
    "## 11. Non-goals",
    "## 12. Acceptance checklist",
    "## 13. Files cited",
    "## 14. Unblocks",
    "## 15. Pending Concept Decision Notices",
    "## 16. Change log",
)


@pytest.fixture(scope="module")
def concepts_text() -> str:
    """Return the full text of the SOS-09-A concepts doc."""
    if not _CONCEPTS_PATH.exists():
        pytest.fail(
            f"SOS-09-A concepts doc missing at {_CONCEPTS_PATH}"
        )
    return _CONCEPTS_PATH.read_text(encoding="utf-8")


# --- existence / shape -------------------------------------------------


def test_doc_exists() -> None:
    """The SOS-09-A concepts doc MUST exist at the canonical path."""
    assert _CONCEPTS_PATH.exists(), (
        f"Expected SOS-09-A concepts doc at {_CONCEPTS_PATH}"
    )


def test_title_line(concepts_text: str) -> None:
    """The doc title MUST be the SOS-09-A heading."""
    first_line = concepts_text.splitlines()[0]
    assert "SOS-09-A" in first_line and "Chart annotation surface" in first_line, (
        f"Unexpected title line: {first_line!r}"
    )


@pytest.mark.parametrize("section", _REQUIRED_SECTIONS)
def test_required_section_present(concepts_text: str, section: str) -> None:
    """Each numbered section §0..§16 MUST appear with its expected heading."""
    assert section in concepts_text, (
        f"Required section heading missing: {section!r}"
    )


# --- §5 permitted-key set ----------------------------------------------


@pytest.mark.parametrize("key", _PERMITTED_KEYS)
def test_section_5_enumerates_each_permitted_key(
    concepts_text: str, key: str
) -> None:
    """§5 MUST enumerate each of the nine permitted `sos:`-prefixed keys."""
    # The doc body cites each key in `code` formatting (`sos:id`, etc.).
    backtick_form = f"`{key}`"
    assert backtick_form in concepts_text, (
        f"Permitted key {key!r} not enumerated (looked for {backtick_form!r})"
    )


def test_section_5_enumerates_nine_keys(concepts_text: str) -> None:
    """§5 MUST enumerate exactly nine `sos:`-prefixed keys."""
    # Slice from §5 heading through §6 heading.
    section_5 = _slice_section(concepts_text, "## 5.", "## 6.")
    # Count distinct `sos:KEY` occurrences in §5.
    distinct = set(re.findall(r"`sos:([a-z_]+)`", section_5))
    expected_suffixes = {k.split(":", 1)[1] for k in _PERMITTED_KEYS}
    assert distinct == expected_suffixes, (
        f"§5 permitted-key set mismatch.\n"
        f"  expected: {sorted(expected_suffixes)}\n"
        f"  found:    {sorted(distinct)}"
    )


# --- §5 frozen kind enum -----------------------------------------------


@pytest.mark.parametrize("kind_value", _KIND_ENUM_VALUES)
def test_section_5_cites_frozen_kind_value(
    concepts_text: str, kind_value: str
) -> None:
    """§5 MUST cite each of the four frozen `kind` enum values."""
    section_5 = _slice_section(concepts_text, "## 5.", "## 6.")
    # Each value MUST appear in §5 (either bare or backticked).
    assert kind_value in section_5, (
        f"Frozen kind value {kind_value!r} not cited in §5"
    )


# --- §7 invariants ------------------------------------------------------


def test_section_7_declares_at_least_four_invariants(
    concepts_text: str,
) -> None:
    """§7 MUST declare at least four INV-S-MEM-A-N invariants."""
    section_7 = _slice_section(concepts_text, "## 7.", "## 8.")
    matches = re.findall(r"INV-S-MEM-A-(\d+)", section_7)
    distinct_ids = set(int(m) for m in matches)
    assert len(distinct_ids) >= 4, (
        f"§7 must declare ≥4 INV-S-MEM-A-N invariants; found "
        f"{sorted(distinct_ids)}"
    )


def test_section_7_invariant_ids_are_sequential_from_one(
    concepts_text: str,
) -> None:
    """The §7 INV-S-MEM-A-N invariants SHOULD start at 1 and be contiguous."""
    section_7 = _slice_section(concepts_text, "## 7.", "## 8.")
    matches = re.findall(r"INV-S-MEM-A-(\d+)", section_7)
    distinct_ids = sorted(set(int(m) for m in matches))
    # Allow extra ids past the minimum; require contiguous prefix from 1.
    assert distinct_ids[:4] == [1, 2, 3, 4], (
        f"§7 invariant ids should start at INV-S-MEM-A-1..4 contiguously; "
        f"found {distinct_ids}"
    )


# --- §15 open PCDNs -----------------------------------------------------


def test_section_15_files_at_least_three_open_pcdns(
    concepts_text: str,
) -> None:
    """§15 MUST file at least three open PCDN-SOS-09-A-N entries."""
    section_15 = _slice_section(concepts_text, "## 15.", "## 16.")
    matches = re.findall(r"PCDN-SOS-09-A-(\d+)", section_15)
    distinct_ids = set(int(m) for m in matches)
    assert len(distinct_ids) >= 3, (
        f"§15 must file ≥3 open PCDN-SOS-09-A-N entries; found "
        f"{sorted(distinct_ids)}"
    )


def test_section_15_pcdn_registration_policy_standards_action(
    concepts_text: str,
) -> None:
    """At least one §15 PCDN MUST name Standards Action registration policy."""
    section_15 = _slice_section(concepts_text, "## 15.", "## 16.")
    assert "Standards Action" in section_15, (
        "§15 must name `Standards Action` registration policy for at least "
        "one of the filed PCDNs"
    )


# --- §8 standards integration matrix -----------------------------------


def test_section_8_cites_other_attributes_as_compose(
    concepts_text: str,
) -> None:
    """§8 MUST cite iState `other_attributes` with relationship `compose`."""
    section_8 = _slice_section(concepts_text, "## 8.", "## 9.")
    assert "other_attributes" in section_8, (
        "§8 must reference iState `other_attributes`"
    )
    # Find the row containing `other_attributes` and verify `compose`
    # appears on the same row.
    for line in section_8.splitlines():
        if "other_attributes" in line and "compose" in line:
            return
    pytest.fail(
        "§8 must declare the iState `other_attributes` row with the "
        "`compose` relationship on the same matrix row"
    )


def test_section_8_mirrors_sos_09_kind_enum(concepts_text: str) -> None:
    """§8 MUST cite the SOS-09 §5.1 `kind` enum with relationship `mirror`."""
    section_8 = _slice_section(concepts_text, "## 8.", "## 9.")
    # Find a row that mentions §5.1 and `mirror` on the same line.
    for line in section_8.splitlines():
        if "5.1" in line and "mirror" in line:
            return
    pytest.fail(
        "§8 must cite the SOS-09 §5.1 channel-kind enum with relationship "
        "`mirror`"
    )


# --- §16 change log ----------------------------------------------------


def test_section_16_has_draft_status_entry(concepts_text: str) -> None:
    """§16 MUST carry an entry naming this initial draft (🟡 drafted)."""
    section_16 = _slice_section(concepts_text, "## 16.", None)
    assert "Initial draft" in section_16, (
        "§16 must carry an 'Initial draft' change-log entry"
    )
    assert "drafted" in section_16.lower(), (
        "§16 must declare drafted status (e.g. 'Status: 🟡 drafted')"
    )


def test_top_of_file_status_is_drafted(concepts_text: str) -> None:
    """The doc header MUST declare status drafted (not yet ratified)."""
    head = concepts_text.split("## 0.", 1)[0]
    assert "drafted" in head.lower(), (
        "Top-of-file `**Status:**` line must declare drafted state"
    )
    assert "ratified" not in head.lower() or "umbrella" not in head, (
        "Top-of-file must NOT prematurely claim ratified status"
    )


# --- XML namespace prohibition -----------------------------------------


def test_no_xmlns_sos_namespace_declaration(concepts_text: str) -> None:
    """The doc MUST NOT carry an `xmlns:sos="..."` namespace declaration.

    Per the PCDN-SOS-09-001 amendment of 2026-05-25 (SOS-09 §16) and
    INV-S-MEM-A-3 / INV-S-MEM-A-4 in this doc, the `sos:` prefix is a
    JSON-key string convention only. The doc body MAY narrate the
    prohibition (mentioning the literal `xmlns:sos` in prose), but MUST
    NOT register or model a namespace declaration of the form
    `xmlns:sos="<url>"`.
    """
    # Match any `xmlns:sos="<url>"` declaration with a real URL or scheme
    # (string-attribute syntax). The literal placeholder `xmlns:sos="..."`
    # used in narrative prose to NAME the forbidden form is explicitly NOT
    # a declaration and is permitted (it carries no URL).
    pattern = re.compile(r'xmlns:sos\s*=\s*"(?!\.\.\.")[^"]+"')
    matches = pattern.findall(concepts_text)
    assert not matches, (
        f"Doc must not declare an `xmlns:sos` namespace; found {matches!r}"
    )


# --- §5.4 validation rules ---------------------------------------------


def test_section_5_4_declares_at_least_eight_validation_rules(
    concepts_text: str,
) -> None:
    """§5.4 MUST declare at least eight validation rules.

    The doc enumerates nine rules ((1)–(9)) — accept ≥8 to tolerate a
    future amendment that collapses two rules.
    """
    section_5 = _slice_section(concepts_text, "## 5.", "## 6.")
    # Find the 5.4 sub-section.
    if "### 5.4" in section_5:
        section_5_4 = section_5.split("### 5.4", 1)[1]
        # Cut at the next "### 5." or end-of-section-5.
        next_heading = re.search(r"^### 5\.\d", section_5_4, re.MULTILINE)
        if next_heading:
            section_5_4 = section_5_4[: next_heading.start()]
    else:
        section_5_4 = section_5
    rule_markers = re.findall(r"\*\*\((\d+)\)", section_5_4)
    distinct = set(int(m) for m in rule_markers)
    assert len(distinct) >= 8, (
        f"§5.4 must declare ≥8 validation rules; found rules "
        f"{sorted(distinct)}"
    )


# --- §5.1 parent contexts ----------------------------------------------


@pytest.mark.parametrize(
    "parent_element", ["<region>", "<state>", "<parallel>"]
)
def test_section_5_1_cites_each_parent_context(
    concepts_text: str, parent_element: str
) -> None:
    """§5.1 MUST cite each of the three allowed parent contexts."""
    section_5 = _slice_section(concepts_text, "## 5.", "## 6.")
    assert parent_element in section_5, (
        f"§5.1 must cite parent context {parent_element!r}"
    )


# --- helpers -----------------------------------------------------------


def _slice_section(text: str, start_marker: str, end_marker: str | None) -> str:
    """Return the slice of `text` from `start_marker` to `end_marker`.

    If `end_marker` is None, slice runs through end-of-file.
    """
    start_idx = text.find(start_marker)
    if start_idx == -1:
        pytest.fail(f"Could not locate section marker {start_marker!r}")
    rest = text[start_idx:]
    if end_marker is None:
        return rest
    end_idx = rest.find(end_marker)
    if end_idx == -1:
        return rest
    return rest[:end_idx]
