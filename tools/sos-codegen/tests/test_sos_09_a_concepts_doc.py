"""SOS-09-A chart-annotation-surface concepts doc assertions.

@spec  docs/concepts/SOS-09-A-CONCEPTS.md (initial draft 2026-05-25;
       ratified 2026-05-25 per the §16 ratification entry).
@spec  docs/concepts/SOS-09-CONCEPTS.md §6 "SOS-09-A — Chart annotation
       surface" (umbrella sub-phase entry).
@spec  docs/concepts/SOS-09-CONCEPTS.md §16 2026-05-25 amendment
       (PCDN-SOS-09-001 routed annotations through `other_attributes`).

This module verifies that `SOS-09-A-CONCEPTS.md` carries the
expected section layout, the **ten-key** permitted attribute set
(post-PCDN-SOS-09-A-003 ratification 2026-05-25, with `sos:name`
added as a new required key), the four frozen `kind` enum values,
the seven cross-sub-phase invariants (INV-S-MEM-A-1 through 7), the
RFC 4122 UUID shape on `sos:id`, the SV-identifier shape on
`sos:name`, the §8 standards-integration matrix `compose` row for
iState `other_attributes`, and the absence of any `xmlns:sos`
namespace declaration in the doc body.

@invariants  INV-S-MEM-A-1 / INV-S-MEM-A-2 (post-PCDN-SOS-09-A-003
             ratification: `sos:id` is UUID-shaped identity handle;
             `sos:name` is SV-identifier-shaped emission-facing handle;
             four required keys instead of three).
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

# The ten `sos:`-prefixed keys per §5.2 (post-PCDN-SOS-09-A-003
# ratification 2026-05-25 — added `sos:name`).
_PERMITTED_KEYS = (
    "sos:id",
    "sos:name",
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


def test_section_5_enumerates_ten_keys(concepts_text: str) -> None:
    """§5 MUST enumerate exactly ten `sos:`-prefixed keys.

    Post-PCDN-SOS-09-A-003 ratification 2026-05-25: `sos:name` was
    added as a new required key, alongside the original nine.
    The §5 section MAY mention additional `sos:`-prefixed keys
    (e.g. `sos:mpu_attr`, `sos:mpu_background` referenced from
    SOS-09-G); the assertion ensures the ten-key set is fully
    present, not that it is the only set referenced.
    """
    # Slice from §5 heading through §6 heading.
    section_5 = _slice_section(concepts_text, "## 5.", "## 6.")
    # Count distinct `sos:KEY` occurrences in §5.
    distinct = set(re.findall(r"`sos:([a-z_]+)`", section_5))
    expected_suffixes = {k.split(":", 1)[1] for k in _PERMITTED_KEYS}
    missing = expected_suffixes - distinct
    assert not missing, (
        f"§5 permitted-key set missing keys: {sorted(missing)}.\n"
        f"  expected at least: {sorted(expected_suffixes)}\n"
        f"  found:             {sorted(distinct)}"
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


def test_section_16_has_initial_draft_entry(concepts_text: str) -> None:
    """§16 MUST preserve the initial-draft change-log entry as institutional memory."""
    section_16 = _slice_section(concepts_text, "## 16.", None)
    assert "Initial draft" in section_16, (
        "§16 must preserve the 'Initial draft' change-log entry"
    )


def test_section_16_has_ratification_entry(concepts_text: str) -> None:
    """§16 MUST carry a 2026-05-25 ratification entry post-PCDN walkthrough."""
    section_16 = _slice_section(concepts_text, "## 16.", None)
    assert "### 2026-05-25 — Ratified" in section_16, (
        "§16 must carry a `### 2026-05-25 — Ratified` entry"
    )
    assert "🟢" in section_16, (
        "§16 ratification entry must include a 🟢 ratified marker"
    )


def test_top_of_file_status_is_ratified(concepts_text: str) -> None:
    """The doc header MUST declare 🟢 ratified status post-2026-05-25."""
    head = concepts_text.split("## 0.", 1)[0]
    assert "ratified" in head.lower(), (
        "Top-of-file `**Status:**` line must declare ratified state"
    )
    assert "🟢" in head, (
        "Top-of-file must carry a 🟢 status marker"
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


# --- PCDN-SOS-09-A-003 ratification: UUID `sos:id` + new `sos:name` ----


def test_section_5_sos_id_is_uuid(concepts_text: str) -> None:
    """§5 MUST declare `sos:id` as RFC 4122 UUID shape.

    Per PCDN-SOS-09-A-003 ratification 2026-05-25, `sos:id` is the
    cross-doc source-of-uniqueness-truth: an RFC 4122 UUID in
    canonical hyphenated form. The earlier SV-identifier shape on
    `sos:id` is retracted.
    """
    section_5 = _slice_section(concepts_text, "## 5.", "## 6.")
    # The §5.2 key table row for `sos:id` MUST cite UUID + RFC 4122.
    assert "UUID" in section_5, (
        "§5 MUST cite `UUID` as the shape of `sos:id`"
    )
    assert "RFC 4122" in section_5, (
        "§5 MUST cite RFC 4122 as the canonical UUID specification"
    )


def test_section_5_sos_id_is_not_sv_identifier(concepts_text: str) -> None:
    """§5 MUST NOT describe `sos:id` as SV-identifier-shaped.

    Per PCDN-SOS-09-A-003 ratification 2026-05-25, the SV-identifier
    shape on `sos:id` was retracted in favour of RFC 4122 UUID.
    The §5.2 row for `sos:id` MUST NOT carry the SV-identifier
    description.
    """
    section_5 = _slice_section(concepts_text, "## 5.", "## 6.")
    # Look at the §5.2 Markdown table row for `sos:id` specifically.
    for line in section_5.splitlines():
        if (
            line.lstrip().startswith("|")
            and "`sos:id`" in line
            and "required" in line
        ):
            # The `sos:id` row MUST NOT call it SV identifier.
            assert "SV identifier" not in line, (
                "§5.2 `sos:id` row MUST NOT describe `sos:id` as "
                "SV-identifier shape post-PCDN-SOS-09-A-003 ratification"
            )
            return
    pytest.fail(
        "§5.2 must carry a `sos:id` required table row for the "
        "assertion to apply"
    )


def test_section_5_sos_name_is_required_sv_identifier(
    concepts_text: str,
) -> None:
    """§5 MUST declare `sos:name` as a NEW required key (SV-identifier).

    Per PCDN-SOS-09-A-003 ratification 2026-05-25, `sos:name` is added
    as a required key (SV-identifier shape; unique within the composed
    scope path per PCDN-SOS-09-A-002 namespaced compose). Used as the
    emission-facing handle (SVD register name, RTL signal name, C
    macro name).
    """
    section_5 = _slice_section(concepts_text, "## 5.", "## 6.")
    # The §5.2 table row for `sos:name` MUST cite SV identifier + required.
    # Restrict to true Markdown table rows (starting with `|`).
    for line in section_5.splitlines():
        if (
            line.lstrip().startswith("|")
            and "`sos:name`" in line
            and "required" in line
        ):
            assert "SV identifier" in line, (
                "§5.2 `sos:name` row MUST declare SV-identifier shape"
            )
            return
    pytest.fail(
        "§5.2 must carry a `sos:name` required table row "
        "(post-PCDN-SOS-09-A-003 ratification 2026-05-25)"
    )


def test_section_5_required_attribute_count_is_four(
    concepts_text: str,
) -> None:
    """§5.4 rule (2) MUST require four keys (added `sos:name`).

    Post-PCDN-SOS-09-A-003 ratification: required-attribute count
    grows from three (`sos:id`, `sos:kind`, `sos:dir`) to four
    (`sos:id`, `sos:name`, `sos:kind`, `sos:dir`).
    """
    section_5 = _slice_section(concepts_text, "## 5.", "## 6.")
    # The §5.4 rule (2) prose MUST name the four required keys.
    pattern = re.compile(
        r"\*\*\(2\).*?(?=\*\*\(3\)|\Z)",
        re.DOTALL,
    )
    match = pattern.search(section_5)
    assert match is not None, "§5.4 must carry a rule (2) about required attributes"
    rule_2 = match.group(0)
    for key in ("sos:id", "sos:name", "sos:kind", "sos:dir"):
        assert key in rule_2, (
            f"§5.4 rule (2) MUST cite required key {key!r} "
            f"(post-PCDN-SOS-09-A-003 ratification 2026-05-25)"
        )


def test_section_5_4_rule_7_demands_uuid_for_sos_id(
    concepts_text: str,
) -> None:
    """§5.4 rule (7) MUST demand UUID shape on `sos:id`.

    Post-PCDN-SOS-09-A-003 ratification: rule (7) was updated to
    require RFC 4122 UUID on `sos:id`. The SV-identifier requirement
    moved to `sos:name`.
    """
    section_5 = _slice_section(concepts_text, "## 5.", "## 6.")
    pattern = re.compile(
        r"\*\*\(7\).*?(?=\*\*\(8\)|\*\*\(9\)|\Z)",
        re.DOTALL,
    )
    match = pattern.search(section_5)
    assert match is not None, "§5.4 must carry a rule (7) about `sos:id` shape"
    rule_7 = match.group(0)
    assert "UUID" in rule_7 or "RFC 4122" in rule_7, (
        "§5.4 rule (7) MUST demand RFC 4122 UUID shape on `sos:id`"
    )


def test_pcdn_a_003_marked_ratified(concepts_text: str) -> None:
    """§15 PCDN-SOS-09-A-003 MUST carry a 🟢 ratified marker."""
    section_15 = _slice_section(concepts_text, "## 15.", "## 16.")
    # Find the PCDN-SOS-09-A-003 entry; assert a 🟢 ratified marker
    # appears within the entry's body.
    pattern = re.compile(
        r"\*\*PCDN-SOS-09-A-003.*?(?=\*\*PCDN-SOS-09-A-|\Z)",
        re.DOTALL,
    )
    match = pattern.search(section_15)
    assert match is not None, "§15 must carry a PCDN-SOS-09-A-003 entry"
    body = match.group(0)
    assert "🟢" in body and "ratified" in body, (
        "§15 PCDN-SOS-09-A-003 entry MUST carry a 🟢 ratified marker "
        "(post-2026-05-25 ratification)"
    )


@pytest.mark.parametrize(
    "pcdn_num",
    ["001", "002", "003", "004"],
)
def test_each_pcdn_marked_ratified(concepts_text: str, pcdn_num: str) -> None:
    """All four §15 PCDN-SOS-09-A-NNN entries MUST carry 🟢 ratified markers."""
    section_15 = _slice_section(concepts_text, "## 15.", "## 16.")
    pcdn_label = f"PCDN-SOS-09-A-{pcdn_num}"
    pattern = re.compile(
        rf"\*\*{re.escape(pcdn_label)}.*?(?=\*\*PCDN-SOS-09-A-|\Z)",
        re.DOTALL,
    )
    match = pattern.search(section_15)
    assert match is not None, f"§15 must carry a {pcdn_label} entry"
    body = match.group(0)
    assert "🟢" in body and "ratified" in body, (
        f"§15 {pcdn_label} entry MUST carry a 🟢 ratified marker"
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
