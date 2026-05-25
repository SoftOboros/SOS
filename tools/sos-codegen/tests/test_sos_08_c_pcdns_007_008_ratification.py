"""SOS-08-C ratification assertions for PCDN-SOS-08-C-007 +
PCDN-SOS-08-C-008.

@spec  docs/concepts/SOS-08-C-CONCEPTS.md §14 (Pending Concept Decision
       Notices — PCDN-SOS-08-C-007, PCDN-SOS-08-C-008 status markers)
@spec  docs/concepts/SOS-08-C-CONCEPTS.md §15 entry 2026-05-25
       ("PCDN-SOS-08-C-007 + C-008 ratification — per-<param> sub-buses
       + shared-datamodel HDL wiring")

This module is the ratification-side companion to
``test_sos_08_c_pcdns_007_008_and_bool_lit.py`` (which asserts the §14
*filing* of the two PCDNs in commit ``2f06c1d``). The ratification
entry recorded in this commit adds the user-imposed addenda to both
PCDNs:

- **C-007 addendum** — implementation is gated on a chart-inventory +
  vector-migration audit landing in parallel under
  ``docs/inventory/SOS-CHART-INVENTORY.md``. The walker code change MUST
  consume the inventory's identified set of legacy-shape chart fixtures.

- **C-008 addendum** — v1 normative scope is same-clock-domain shared
  signals only. Cross-domain shared signals use an EXTENDED naming
  convention (not a replacement of v1 ``shared_<name>``) in a future
  PCDN; the v1 walker MUST reject cross-domain readers at the chart-
  vocab layer.

Both PCDNs additionally carry an authority-boundary row update for the
``own``-relationship + Standards Action registration policy, and an
order-of-operations specification that sequences the walker code changes
behind their respective gates.

@invariants  INV-S-HDL-C-1 through C-5 (preserved by ratification entry)
@invariants  SOS-08-D one-driver invariant (preserved by construction —
             owner_region drives; readers don't write)
"""

from __future__ import annotations

from pathlib import Path

import pytest


# Repo-root resolution: this test file lives at
# tools/sos-codegen/tests/test_sos_08_c_pcdns_007_008_ratification.py
# → repo root is three parents up.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONCEPTS_PATH = _REPO_ROOT / "docs" / "concepts" / "SOS-08-C-CONCEPTS.md"

_RATIFICATION_HEADER = (
    "### 2026-05-25 — PCDN-SOS-08-C-007 + C-008 ratification"
)


@pytest.fixture(scope="module")
def concepts_text() -> str:
    """Read SOS-08-C-CONCEPTS.md; fail loudly if missing so worktree
    miswiring doesn't silently pass these assertions."""
    if not _CONCEPTS_PATH.exists():
        pytest.fail(
            f"SOS-08-C concepts doc missing at {_CONCEPTS_PATH} — "
            "ratification deliverable not present"
        )
    return _CONCEPTS_PATH.read_text(encoding="utf-8")


def _section_after(text: str, anchor: str) -> str:
    """Return the substring of ``text`` after the first occurrence of
    ``anchor``. Fail the test if the anchor is not present."""
    idx = text.find(anchor)
    assert idx >= 0, f"anchor not found in concepts doc: {anchor!r}"
    return text[idx:]


def _ratification_block(text: str) -> str:
    """Return the §15 ratification entry block — from the dated header
    to the next ``### `` heading (or EOF). Fails if the header is
    missing."""
    start = text.find(_RATIFICATION_HEADER)
    assert start >= 0, (
        f"§15 ratification header missing: {_RATIFICATION_HEADER!r}"
    )
    # The next "### " marks the start of the next dated entry; if
    # absent, the block runs to EOF.
    rest = text[start + len(_RATIFICATION_HEADER):]
    next_idx = rest.find("\n### ")
    if next_idx < 0:
        return text[start:]
    return text[start : start + len(_RATIFICATION_HEADER) + next_idx]


# ---------------------------------------------------------------------------
# §15 ratification entry — single combined entry covering both PCDNs
# ---------------------------------------------------------------------------


class TestS15RatificationEntry:
    """The §15 2026-05-25 ratification entry naming BOTH C-007 and
    C-008."""

    def test_dated_entry_exists(self, concepts_text: str) -> None:
        """A §15 entry dated 2026-05-25 with the ratification header is
        present."""
        assert _RATIFICATION_HEADER in concepts_text

    def test_entry_title_names_both_pcdns(self, concepts_text: str) -> None:
        """The dated header explicitly names BOTH C-007 and C-008 — it
        is a single combined entry, not two separate entries."""
        # The header text we wrote includes both PCDN identifiers.
        header_line_start = concepts_text.find(_RATIFICATION_HEADER)
        assert header_line_start >= 0
        # The remainder of the line up to the next newline contains
        # the title.
        line_end = concepts_text.find("\n", header_line_start)
        header_line = concepts_text[header_line_start:line_end]
        assert "C-007" in header_line
        assert "C-008" in header_line

    def test_entry_block_mentions_both_pcdns(
        self, concepts_text: str
    ) -> None:
        """The body of the ratification entry mentions both PCDNs by
        full identifier."""
        block = _ratification_block(concepts_text)
        assert "PCDN-SOS-08-C-007" in block
        assert "PCDN-SOS-08-C-008" in block

    def test_entry_marks_both_resolved_with_green(
        self, concepts_text: str
    ) -> None:
        """Both PCDNs are marked RESOLVED with the 🟢 status icon
        inside the ratification block."""
        block = _ratification_block(concepts_text)
        # Allow either "RESOLVED 🟢" or "🟢 RESOLVED" ordering.
        c007_resolved = (
            "PCDN-SOS-08-C-007 → RESOLVED 🟢" in block
            or "PCDN-SOS-08-C-007 → RESOLVED" in block
            and "🟢" in block
        )
        c008_resolved = (
            "PCDN-SOS-08-C-008 → RESOLVED 🟢" in block
            or "PCDN-SOS-08-C-008 → RESOLVED" in block
            and "🟢" in block
        )
        assert c007_resolved, "PCDN-SOS-08-C-007 must be marked RESOLVED"
        assert c008_resolved, "PCDN-SOS-08-C-008 must be marked RESOLVED"


# ---------------------------------------------------------------------------
# PCDN-SOS-08-C-007 ratification — per-<param> sub-buses
# ---------------------------------------------------------------------------


class TestC007Ratification:
    """The §15 entry's C-007 section carries the normative recommendation
    text and the chart-inventory addendum."""

    def test_per_param_sub_buses_named(self, concepts_text: str) -> None:
        block = _ratification_block(concepts_text)
        # Restrict to the C-007 portion: from the C-007 RESOLVED marker
        # to the C-008 RESOLVED marker.
        c007_idx = block.find("PCDN-SOS-08-C-007 → RESOLVED")
        c008_idx = block.find("PCDN-SOS-08-C-008 → RESOLVED")
        assert c007_idx >= 0 and c008_idx > c007_idx
        c007_block = block[c007_idx:c008_idx]
        assert "per-`<param>` sub-buses" in c007_block

    def test_byte_identity_alias_preserved(self, concepts_text: str) -> None:
        """The legacy unnamed ``_recv_data`` bus is preserved as a
        byte-identity alias."""
        block = _ratification_block(concepts_text)
        c007_idx = block.find("PCDN-SOS-08-C-007 → RESOLVED")
        c008_idx = block.find("PCDN-SOS-08-C-008 → RESOLVED")
        c007_block = block[c007_idx:c008_idx]
        assert "byte-identity alias" in c007_block

    def test_value_name_collision_hard_reject(
        self, concepts_text: str
    ) -> None:
        """A ``<param name="value">`` collision is a hard reject."""
        block = _ratification_block(concepts_text)
        c007_idx = block.find("PCDN-SOS-08-C-007 → RESOLVED")
        c008_idx = block.find("PCDN-SOS-08-C-008 → RESOLVED")
        c007_block = block[c007_idx:c008_idx]
        assert "hard reject" in c007_block

    def test_registration_policy_standards_action(
        self, concepts_text: str
    ) -> None:
        block = _ratification_block(concepts_text)
        c007_idx = block.find("PCDN-SOS-08-C-007 → RESOLVED")
        c008_idx = block.find("PCDN-SOS-08-C-008 → RESOLVED")
        c007_block = block[c007_idx:c008_idx]
        assert "Standards Action" in c007_block

    def test_chart_inventory_addendum_present(
        self, concepts_text: str
    ) -> None:
        """The chart-inventory addendum names the inventory deliverable
        and gates the walker change behind it."""
        block = _ratification_block(concepts_text)
        # The "chart-inventory" string appears in the C-007 addendum.
        assert "chart-inventory" in block
        # And the inventory path is cited.
        assert "SOS-CHART-INVENTORY.md" in block

    def test_unused_sub_buses_optimisation_optional(
        self, concepts_text: str
    ) -> None:
        """Unused sub-buses MAY be suppressed as an optimisation —
        opt-in, not a normative requirement."""
        block = _ratification_block(concepts_text)
        c007_idx = block.find("PCDN-SOS-08-C-007 → RESOLVED")
        c008_idx = block.find("PCDN-SOS-08-C-008 → RESOLVED")
        c007_block = block[c007_idx:c008_idx]
        # The optimisation language tolerates British or American
        # spelling.
        lower = c007_block.lower()
        assert "optimis" in lower or "optimiz" in lower


# ---------------------------------------------------------------------------
# PCDN-SOS-08-C-008 ratification — shared-datamodel HDL wiring
# ---------------------------------------------------------------------------


class TestC008Ratification:
    """The §15 entry's C-008 section carries the normative recommendation
    text + the same-clock-domain v1 constraint + the EXTENDED-naming
    forward-compat stance."""

    def _c008_block(self, concepts_text: str) -> str:
        block = _ratification_block(concepts_text)
        c008_idx = block.find("PCDN-SOS-08-C-008 → RESOLVED")
        assert c008_idx >= 0
        return block[c008_idx:]

    def test_shared_signal_element_named(self, concepts_text: str) -> None:
        """The C-008 block cites the ``<sos:shared_signal>`` element."""
        c008 = self._c008_block(concepts_text)
        assert "<sos:shared_signal" in c008

    def test_shared_name_signal_form(self, concepts_text: str) -> None:
        """The C-008 block names the chart-top signal as
        ``shared_<name>``."""
        c008 = self._c008_block(concepts_text)
        assert "`shared_<name>`" in c008 or "shared_<name>" in c008

    def test_owner_region_drives(self, concepts_text: str) -> None:
        """The C-008 block declares the driving register process lives
        inside ``owner_region``'s per-region logic."""
        c008 = self._c008_block(concepts_text)
        assert "owner_region" in c008

    def test_same_clock_domain_only_v1(self, concepts_text: str) -> None:
        """v1 normative scope is same-clock-domain shared signals only."""
        c008 = self._c008_block(concepts_text)
        # The phrase appears verbatim per the user-imposed addendum.
        assert "same-clock-domain only" in c008

    def test_registration_policy_standards_action(
        self, concepts_text: str
    ) -> None:
        c008 = self._c008_block(concepts_text)
        assert "Standards Action" in c008

    def test_forward_compat_naming_extended_not_replaced(
        self, concepts_text: str
    ) -> None:
        """The forward-compat stance for cross-domain shared signals
        explicitly says the naming convention will be EXTENDED, not
        replaced. Implementations MUST NOT pre-emptively widen the v1
        ``shared_<name>`` form."""
        c008 = self._c008_block(concepts_text)
        # The key word "EXTENDED" appears (case-sensitive in our entry).
        assert "EXTENDED" in c008
        # And the "not replaced" / "not a replacement" framing pairs
        # with it.
        assert (
            "not replaced" in c008
            or "not a replacement" in c008
            or "EXTENDED, not replaced" in c008
        )
        # And implementations are explicitly told NOT to pre-emptively
        # widen.
        lower = c008.lower()
        assert "must not pre-emptively widen" in lower or (
            "must not" in lower and "widen" in lower
        )

    def test_cross_domain_rejection_at_chart_vocab(
        self, concepts_text: str
    ) -> None:
        """v1 walker rejects cross-domain shared-signal readers at the
        chart-vocab layer."""
        c008 = self._c008_block(concepts_text)
        lower = c008.lower()
        assert "reject" in lower
        # Either "cross-domain" or "different clock domains" framing.
        assert "cross-domain" in lower or "different clock domains" in lower


# ---------------------------------------------------------------------------
# Authority-boundary additions
# ---------------------------------------------------------------------------


class TestAuthorityBoundaryAdditions:
    """The ratification entry adds (or updates) authority-boundary rows
    for both PCDNs reflecting the ``own`` relationship + Standards
    Action registration policy."""

    def test_authority_table_present(self, concepts_text: str) -> None:
        block = _ratification_block(concepts_text)
        # The table header naming "Upstream authority" identifies the
        # authority-boundary additions.
        assert "Upstream authority" in block

    def test_c007_authority_row_is_own(self, concepts_text: str) -> None:
        block = _ratification_block(concepts_text)
        # The C-007 row's "Upstream authority" cell is "none — `own`".
        # We assert the load-bearing tokens appear together in the
        # block; we don't enforce strict row formatting.
        assert "event_<ev>_recv_data_<param>" in block
        assert "`own`" in block or "own" in block

    def test_c008_authority_row_is_own(self, concepts_text: str) -> None:
        block = _ratification_block(concepts_text)
        # The C-008 row's signal naming + ownership-by-region rule.
        assert "shared_<name>" in block
        assert "ownership-by-region" in block or "owner_region" in block


# ---------------------------------------------------------------------------
# Order-of-operations
# ---------------------------------------------------------------------------


class TestOrderOfOperations:
    """The ratification entry documents the sequencing of walker code
    changes behind the C-007 inventory gate and the C-008 v1 same-domain
    constraint."""

    def test_order_section_present(self, concepts_text: str) -> None:
        block = _ratification_block(concepts_text)
        # The "Order-of-operations" header marker we wrote.
        assert "Order-of-operations" in block

    def test_c007_sequenced_after_inventory(
        self, concepts_text: str
    ) -> None:
        """The C-007 sequencing places the inventory pass before the
        walker code change."""
        block = _ratification_block(concepts_text)
        # Verify the inventory is named as step (1) of the C-007
        # sequence and the walker change as step (2).
        # Conservative grep: the inventory string precedes the walker
        # string within the C-007 sub-section of the order list.
        order_idx = block.find("Order-of-operations")
        assert order_idx >= 0
        order_block = block[order_idx:]
        # C-007 entry in the order section.
        c007_order_idx = order_block.find("PCDN-SOS-08-C-007")
        assert c007_order_idx >= 0
        # Inventory mention within the C-007 sub-section comes before
        # the walker change mention.
        c008_order_idx = order_block.find("PCDN-SOS-08-C-008", c007_order_idx)
        assert c008_order_idx > c007_order_idx
        c007_order = order_block[c007_order_idx:c008_order_idx]
        inventory_pos = c007_order.find("inventory")
        walker_pos = c007_order.find("walker")
        assert inventory_pos >= 0
        assert walker_pos >= 0
        assert inventory_pos < walker_pos, (
            "C-007 inventory step must precede the walker code change "
            "step in the order-of-operations specification"
        )

    def test_c008_sequenced_for_walker_then_invariant_check(
        self, concepts_text: str
    ) -> None:
        """The C-008 sequencing places the walker code change first,
        then verification that SOS-08-D's one-driver invariant continues
        to hold."""
        block = _ratification_block(concepts_text)
        order_idx = block.find("Order-of-operations")
        order_block = block[order_idx:]
        c008_order_idx = order_block.find("PCDN-SOS-08-C-008")
        assert c008_order_idx >= 0
        c008_order = order_block[c008_order_idx:]
        # The one-driver invariant is named in the verification step.
        assert "one-driver invariant" in c008_order


# ---------------------------------------------------------------------------
# Tracking citations
# ---------------------------------------------------------------------------


class TestTrackingCitations:
    """The ratification entry cites the three load-bearing commits."""

    def test_f0284fc_cited(self, concepts_text: str) -> None:
        """``f0284fc`` is cited (wave-3-f-future-A — surfaces C-007)."""
        block = _ratification_block(concepts_text)
        assert "f0284fc" in block

    def test_1dc5649_cited(self, concepts_text: str) -> None:
        """``1dc5649`` is cited (SOS-08-D wave-4-future-shared —
        surfaces C-008)."""
        block = _ratification_block(concepts_text)
        assert "1dc5649" in block

    def test_2f06c1d_cited(self, concepts_text: str) -> None:
        """``2f06c1d`` is cited (wave-5 §14 filing entry for both
        PCDNs)."""
        block = _ratification_block(concepts_text)
        assert "2f06c1d" in block


# ---------------------------------------------------------------------------
# §14 status markers
# ---------------------------------------------------------------------------


class TestS14StatusMarkers:
    """§14 PCDN entries for C-007 and C-008 carry "🟢 ratified
    2026-05-25" status markers without losing the original PCDN text."""

    def test_c007_s14_entry_marked_ratified(
        self, concepts_text: str
    ) -> None:
        # Find the §14 section.
        s14_idx = concepts_text.find(
            "## 14. Pending Concept Decision Notices (PCDNs)"
        )
        s15_idx = concepts_text.find("## 15. Change log")
        assert s14_idx >= 0 and s15_idx > s14_idx
        s14 = concepts_text[s14_idx:s15_idx]
        # The C-007 line carries the ratified marker with the date.
        c007_pos = s14.find("PCDN-SOS-08-C-007")
        assert c007_pos >= 0
        # The marker text should appear on the same line / bullet as
        # the PCDN identifier.
        line_end = s14.find("\n", c007_pos)
        # Some entries span multiple lines (the recommendation runs
        # long); the marker is in the header portion before the first
        # period after the identifier.
        c007_line = s14[c007_pos : c007_pos + 600]
        assert "🟢" in c007_line
        assert "ratified" in c007_line.lower()
        assert "2026-05-25" in c007_line

    def test_c008_s14_entry_marked_ratified(
        self, concepts_text: str
    ) -> None:
        s14_idx = concepts_text.find(
            "## 14. Pending Concept Decision Notices (PCDNs)"
        )
        s15_idx = concepts_text.find("## 15. Change log")
        s14 = concepts_text[s14_idx:s15_idx]
        c008_pos = s14.find("PCDN-SOS-08-C-008")
        assert c008_pos >= 0
        c008_line = s14[c008_pos : c008_pos + 600]
        assert "🟢" in c008_line
        assert "ratified" in c008_line.lower()
        assert "2026-05-25" in c008_line

    def test_c007_s14_original_recommendation_text_preserved(
        self, concepts_text: str
    ) -> None:
        """The original PCDN-SOS-08-C-007 recommendation text is NOT
        deleted by the status marker addition — the load-bearing
        "byte-identity alias" phrase from the §14 recommendation still
        appears."""
        s14_idx = concepts_text.find(
            "## 14. Pending Concept Decision Notices (PCDNs)"
        )
        s15_idx = concepts_text.find("## 15. Change log")
        s14 = concepts_text[s14_idx:s15_idx]
        c007_pos = s14.find("PCDN-SOS-08-C-007")
        c008_pos = s14.find("PCDN-SOS-08-C-008")
        c007_block = s14[c007_pos:c008_pos]
        assert "byte-identity alias" in c007_block

    def test_c008_s14_original_recommendation_text_preserved(
        self, concepts_text: str
    ) -> None:
        """The original PCDN-SOS-08-C-008 recommendation text is NOT
        deleted by the status marker addition — the load-bearing
        ``<sos:shared_signal>`` + "ownership-by-region" tokens still
        appear."""
        s14_idx = concepts_text.find(
            "## 14. Pending Concept Decision Notices (PCDNs)"
        )
        s15_idx = concepts_text.find("## 15. Change log")
        s14 = concepts_text[s14_idx:s15_idx]
        c008_pos = s14.find("PCDN-SOS-08-C-008")
        c008_block = s14[c008_pos:]
        assert "<sos:shared_signal" in c008_block
        assert "ownership-by-region" in c008_block


# ---------------------------------------------------------------------------
# Cross-cutting sanity
# ---------------------------------------------------------------------------


class TestCrossCutting:
    """Cross-cutting invariants the ratification entry MUST preserve."""

    def test_concepts_doc_exists(self) -> None:
        assert _CONCEPTS_PATH.exists()
        assert _CONCEPTS_PATH.is_file()

    def test_ratification_status_line_present(
        self, concepts_text: str
    ) -> None:
        """The §15 entry ends with a "ratified — implementation pending"
        status line."""
        block = _ratification_block(concepts_text)
        lower = block.lower()
        assert "ratified" in lower
        assert "implementation pending" in lower
