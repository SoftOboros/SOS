"""SOS-08-C post-wave follow-up doc assertions: PCDN-SOS-08-C-007 +
C-008 + boolean-literal subset widening.

@spec  docs/concepts/SOS-08-C-CONCEPTS.md §14 (Pending Concept Decision
       Notices — PCDN-SOS-08-C-007, PCDN-SOS-08-C-008)
@spec  docs/concepts/SOS-08-C-CONCEPTS.md §15 entry 2026-05-25
       ("Post-wave follow-ups: PCDN-SOS-08-C-007 + C-008 +
       boolean-literal amendment")

This module verifies the three doc-side deliverables landed by the
2026-05-25 audit pass:

1. **PCDN-SOS-08-C-007** in §14 — wave-3-e port-shape extension for
   per-``<param>`` sub-buses, tracking the wave-1 commit ``f0284fc``
   placeholder rejection at ``_EVENT_PAYLOAD_RE``.

2. **PCDN-SOS-08-C-008** in §14 — shared-datamodel HDL wiring,
   tracking the D3 wave-4 commit ``1dc5649`` SVA-side emit at
   ``_emit_shared_signal_invariants`` whose HDL-wiring counterpart is
   deferred to SOS-08-C.

3. **Boolean-literal widening cross-reference** in §15 — the
   wave-3-f-future-assign ratified subset is widened to admit ``true``
   and ``false`` literals (lowered to integer ``1`` and ``0``), matching
   the wave-2 commit ``d879e7b`` implementation behaviour and the
   authority-boundary row update for ECMA-262.

The assertions below grep the canonical doc text for the expected
fragments — the prose may evolve, but the load-bearing identifiers
(``PCDN-SOS-08-C-007``, ``PCDN-SOS-08-C-008``, ``Standards Action``,
``shared_<name>``, ``true`` → ``1`` / ``false`` → ``0`` mapping, commit
SHA prefixes ``f0284fc`` / ``1dc5649`` / ``d879e7b``) are stable.

@invariants  INV-S-HDL-C-1 through C-5 (preserved by doc-only entry)
@invariants  Standards-integration §0 authority policy (ECMA-262
             ``derive`` row widened in scope, not changed in kind)
"""

from __future__ import annotations

from pathlib import Path

import pytest


# Repo-root resolution: this test file lives at
# tools/sos-codegen/tests/test_sos_08_c_pcdns_007_008_and_bool_lit.py
# → repo root is three parents up.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONCEPTS_PATH = _REPO_ROOT / "docs" / "concepts" / "SOS-08-C-CONCEPTS.md"


@pytest.fixture(scope="module")
def concepts_text() -> str:
    """Read SOS-08-C-CONCEPTS.md; fail loudly if missing so worktree
    miswiring doesn't silently pass these assertions."""
    if not _CONCEPTS_PATH.exists():
        pytest.fail(
            f"SOS-08-C concepts doc missing at {_CONCEPTS_PATH} — "
            "post-wave follow-up deliverable not present"
        )
    return _CONCEPTS_PATH.read_text(encoding="utf-8")


def _section_after(text: str, anchor: str) -> str:
    """Return the substring of ``text`` after the first occurrence of
    ``anchor``. Fail the test if the anchor is not present."""
    idx = text.find(anchor)
    assert idx >= 0, f"anchor not found in concepts doc: {anchor!r}"
    return text[idx:]


def _section_between(text: str, start_anchor: str, end_anchor: str) -> str:
    """Return the substring between two anchors; fails if either is
    missing or if start does not precede end."""
    start = text.find(start_anchor)
    end = text.find(end_anchor)
    assert start >= 0, f"start anchor not found: {start_anchor!r}"
    assert end >= 0, f"end anchor not found: {end_anchor!r}"
    assert start < end, (
        f"start anchor {start_anchor!r} must precede end anchor {end_anchor!r}"
    )
    return text[start:end]


# ---------------------------------------------------------------------------
# PCDN-SOS-08-C-007 — wave-3-e port-shape extension for per-<param>
# sub-buses
# ---------------------------------------------------------------------------


class TestPcdnSos08C007:
    """§14 entry for PCDN-SOS-08-C-007 — wave-3-e port-shape extension
    for per-``<param>`` sub-buses (post-wave-1 follow-up)."""

    def test_pcdn_007_entry_exists(self, concepts_text: str) -> None:
        """The §14 PCDN block contains the PCDN-SOS-08-C-007 header."""
        assert "PCDN-SOS-08-C-007" in concepts_text

    def test_pcdn_007_names_per_param_sub_buses(
        self, concepts_text: str
    ) -> None:
        """The recommendation explicitly cites the per-``<param>``
        sub-buses extension."""
        entry = _section_after(concepts_text, "PCDN-SOS-08-C-007")
        assert "per-`<param>` sub-buses" in entry

    def test_pcdn_007_registration_policy_is_standards_action(
        self, concepts_text: str
    ) -> None:
        """Cross-walker contract surface → Standards Action."""
        entry = _section_after(concepts_text, "PCDN-SOS-08-C-007")
        # Look at only this PCDN's entry block, before the next PCDN.
        next_pcdn_idx = entry.find("PCDN-SOS-08-C-008")
        assert next_pcdn_idx > 0, (
            "PCDN-SOS-08-C-008 must follow C-007 in document order"
        )
        block = entry[:next_pcdn_idx]
        assert "Standards Action" in block

    def test_pcdn_007_names_unblock_target(self, concepts_text: str) -> None:
        """C-007 unblocks SOS-08-C wave-3-f-future-B FULL impl."""
        entry = _section_after(concepts_text, "PCDN-SOS-08-C-007")
        next_pcdn_idx = entry.find("PCDN-SOS-08-C-008")
        block = entry[:next_pcdn_idx]
        # Case-insensitive substring grep, since the doc may write
        # "Unblocks" with sentence capitalisation.
        lower = block.lower()
        assert "unblocks" in lower
        assert "sos-08-c wave-3-f-future-b" in lower

    def test_pcdn_007_cites_tracking_commit(self, concepts_text: str) -> None:
        """The wave-1 placeholder commit f0284fc is cited as the
        tracking placeholder."""
        entry = _section_after(concepts_text, "PCDN-SOS-08-C-007")
        next_pcdn_idx = entry.find("PCDN-SOS-08-C-008")
        block = entry[:next_pcdn_idx]
        assert "f0284fc" in block


# ---------------------------------------------------------------------------
# PCDN-SOS-08-C-008 — shared-datamodel HDL wiring
# ---------------------------------------------------------------------------


class TestPcdnSos08C008:
    """§14 entry for PCDN-SOS-08-C-008 — shared-datamodel HDL wiring
    (post-wave-1 follow-up)."""

    def test_pcdn_008_entry_exists(self, concepts_text: str) -> None:
        assert "PCDN-SOS-08-C-008" in concepts_text

    def test_pcdn_008_names_shared_signal_element(
        self, concepts_text: str
    ) -> None:
        """Cites the ``<sos:shared_signal>`` element name."""
        entry = _section_after(concepts_text, "PCDN-SOS-08-C-008")
        # The section ends at the next "## " heading; restrict scope.
        next_section_idx = entry.find("\n## ")
        block = entry if next_section_idx < 0 else entry[:next_section_idx]
        assert "`<sos:shared_signal>`" in block or "<sos:shared_signal>" in block

    def test_pcdn_008_names_hdl_wiring(self, concepts_text: str) -> None:
        """The recommendation distinguishes the HDL-wiring side from
        the assertion side."""
        entry = _section_after(concepts_text, "PCDN-SOS-08-C-008")
        next_section_idx = entry.find("\n## ")
        block = entry if next_section_idx < 0 else entry[:next_section_idx]
        assert "HDL wiring" in block or "HDL-side wiring" in block or "HDL-side" in block

    def test_pcdn_008_names_chart_top_signal_naming(
        self, concepts_text: str
    ) -> None:
        """``shared_<name>`` is the normative chart-top signal name."""
        entry = _section_after(concepts_text, "PCDN-SOS-08-C-008")
        next_section_idx = entry.find("\n## ")
        block = entry if next_section_idx < 0 else entry[:next_section_idx]
        assert "shared_<name>" in block or "`shared_<name>`" in block

    def test_pcdn_008_registration_policy_is_standards_action(
        self, concepts_text: str
    ) -> None:
        entry = _section_after(concepts_text, "PCDN-SOS-08-C-008")
        next_section_idx = entry.find("\n## ")
        block = entry if next_section_idx < 0 else entry[:next_section_idx]
        assert "Standards Action" in block

    def test_pcdn_008_cites_tracking_commit(self, concepts_text: str) -> None:
        """D3 wave-4 commit 1dc5649 is cited as the SVA-side counterpart."""
        entry = _section_after(concepts_text, "PCDN-SOS-08-C-008")
        next_section_idx = entry.find("\n## ")
        block = entry if next_section_idx < 0 else entry[:next_section_idx]
        assert "1dc5649" in block


# ---------------------------------------------------------------------------
# §15 entry 2026-05-25 — post-wave follow-ups
# ---------------------------------------------------------------------------


class TestS15PostWaveFollowUpEntry:
    """§15 dated entry 2026-05-25 documenting the two new PCDNs +
    boolean-literal widening + ECMA-262 authority-boundary update."""

    def test_dated_entry_exists(self, concepts_text: str) -> None:
        """A §15 entry dated 2026-05-25 mentioning all three issues."""
        assert "2026-05-25" in concepts_text
        # The dated entry header carries the date.
        assert "### 2026-05-25 — Post-wave follow-ups" in concepts_text

    def test_entry_names_all_three_issues(self, concepts_text: str) -> None:
        """The §15 entry mentions PCDN-SOS-08-C-007, PCDN-SOS-08-C-008,
        and the boolean-literal amendment."""
        s15 = _section_after(
            concepts_text,
            "### 2026-05-25 — Post-wave follow-ups",
        )
        assert "PCDN-SOS-08-C-007" in s15
        assert "PCDN-SOS-08-C-008" in s15
        assert "boolean-literal" in s15.lower() or "boolean literal" in s15.lower()

    def test_entry_cites_all_three_commits(self, concepts_text: str) -> None:
        """Each of the three load-bearing commits is cited by SHA prefix
        in the §15 entry."""
        s15 = _section_after(
            concepts_text,
            "### 2026-05-25 — Post-wave follow-ups",
        )
        assert "f0284fc" in s15
        assert "1dc5649" in s15
        assert "d879e7b" in s15

    def test_boolean_literal_mapping_explicit(
        self, concepts_text: str
    ) -> None:
        """``true`` → ``1`` and ``false`` → ``0`` mapping is explicit in
        the §15 entry. The grep tolerates a few formatting variations:
        the canonical form is `true` / `false` paired with `1` / `0`."""
        s15 = _section_after(
            concepts_text,
            "### 2026-05-25 — Post-wave follow-ups",
        )
        # The mapping appears at minimum as a quoted form: true/false
        # along with the integer constants 1/0.
        assert "true" in s15
        assert "false" in s15
        assert "1" in s15
        assert "0" in s15
        # And the dedicated normative MUST sentence pairs them.
        lower = s15.lower()
        assert (
            "`true` or `false`" in s15
            or "`true` and `false`" in s15
            or ("true" in lower and "false" in lower and "lower" in lower)
        )

    def test_entry_widens_wave3f_future_assign_subset(
        self, concepts_text: str
    ) -> None:
        """The §15 entry explicitly references the wave-3-f-future-assign
        ratified subset that is being widened."""
        s15 = _section_after(
            concepts_text,
            "### 2026-05-25 — Post-wave follow-ups",
        )
        assert "wave-3-f-future-assign" in s15
        # Cites the 2026-05-24 ratification date.
        assert "2026-05-24" in s15

    def test_authority_boundary_ecma262_boolean_subset_present(
        self, concepts_text: str
    ) -> None:
        """The authority-boundary update for the ECMA-262 boolean-literal
        subset is documented in the §15 entry."""
        s15 = _section_after(
            concepts_text,
            "### 2026-05-25 — Post-wave follow-ups",
        )
        # The widened authority-boundary row's load-bearing tokens:
        # ECMA-262 + boolean-literal + derive.
        assert "ECMA-262" in s15
        assert "boolean-literal" in s15 or "Boolean Literal" in s15 or "Boolean literal" in s15
        assert "derive" in s15

    def test_entry_post_hoc_widening_self_described(
        self, concepts_text: str
    ) -> None:
        """The §15 entry self-describes the widening as post-hoc — i.e.
        the implementation in d879e7b already emits the behaviour and
        the doc is catching up."""
        s15 = _section_after(
            concepts_text,
            "### 2026-05-25 — Post-wave follow-ups",
        )
        assert "post-hoc" in s15.lower() or "post-wave" in s15.lower()


# ---------------------------------------------------------------------------
# Cross-cutting sanity checks
# ---------------------------------------------------------------------------


class TestDocCrossCutting:
    """Cross-cutting invariants on the SOS-08-C concept doc that the
    post-wave follow-up entry MUST preserve."""

    def test_concepts_doc_exists(self) -> None:
        assert _CONCEPTS_PATH.exists()
        assert _CONCEPTS_PATH.is_file()

    def test_s14_pcdn_section_present(self, concepts_text: str) -> None:
        """§14 (PCDN) section header is present."""
        assert "## 14. Pending Concept Decision Notices (PCDNs)" in concepts_text

    def test_s15_change_log_section_present(self, concepts_text: str) -> None:
        """§15 (change log) section header is present."""
        assert "## 15. Change log" in concepts_text

    def test_pcdn_007_appears_before_change_log_section(
        self, concepts_text: str
    ) -> None:
        """PCDN-SOS-08-C-007 is filed in §14, not §15 — so its first
        occurrence in the doc precedes the §15 heading."""
        first_007 = concepts_text.find("PCDN-SOS-08-C-007")
        s15_idx = concepts_text.find("## 15. Change log")
        assert first_007 >= 0
        assert s15_idx >= 0
        assert first_007 < s15_idx

    def test_pcdn_008_appears_before_change_log_section(
        self, concepts_text: str
    ) -> None:
        """PCDN-SOS-08-C-008 is filed in §14, not §15 — so its first
        occurrence precedes the §15 heading."""
        first_008 = concepts_text.find("PCDN-SOS-08-C-008")
        s15_idx = concepts_text.find("## 15. Change log")
        assert first_008 >= 0
        assert s15_idx >= 0
        assert first_008 < s15_idx
