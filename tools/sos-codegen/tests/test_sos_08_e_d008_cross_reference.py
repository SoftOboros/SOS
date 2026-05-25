"""SOS-08-E §15 cross-reference assertions for PCDN-SOS-08-D-008.

@spec  docs/concepts/SOS-08-E-CONCEPTS.md §15 2026-05-25 entry
       (PCDN-SOS-08-D-008 cross-reference — `<sos:clock_domains>`
       shape now formal).
@spec  docs/concepts/SOS-08-D-CONCEPTS.md §15 2026-05-25 entry
       (Post-wave-4 follow-ups: PCDN-SOS-08-D-008 ratification —
       upstream authority that SOS-08-E mirrors).

This module verifies the SOS-08-E §15 cross-reference entry landed
intact. The cross-reference records that the wave-3-future-mclk
implementation (commit `c2aa1cf`, "SOS08E3m") assumed
`<sos:clock_domains>` element shape is now **formally ratified** by
PCDN-SOS-08-D-008, that the SOS-08-E walker MUST consume the SAME
parsed shape as the SOS-08-D walker (via a future shared helper),
the kind enum at v1 is `rising` + `falling`, alias resolution
collapses two `<sos:clock>` sharing `(source, kind)` to one domain,
and backwards-compatibility for charts without `<sos:clock_domains>`
is preserved.

The cross-reference is doc-only — no walker changes. Implementation
of the shared helper + alias-resolution emit collapse is owed by a
follow-up wave; this test pins the contract surface so the follow-up
PR can audit against the §15 entry.

@invariants  INV-S-HDL-E-1 through E-6 (preserved by doc-only entry)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Repo-root resolution: this test file lives at
# tools/sos-codegen/tests/test_sos_08_e_d008_cross_reference.py
# → repo root is three parents up.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONCEPTS_PATH = _REPO_ROOT / "docs" / "concepts" / "SOS-08-E-CONCEPTS.md"


@pytest.fixture(scope="module")
def concepts_text() -> str:
    if not _CONCEPTS_PATH.exists():
        pytest.fail(
            f"SOS-08-E concepts doc missing at {_CONCEPTS_PATH}"
        )
    return _CONCEPTS_PATH.read_text(encoding="utf-8")


def _extract_d008_xref_entry(text: str) -> str:
    """Slice the 2026-05-25 §15 cross-reference entry body."""
    pat = (
        r"### 2026-05-25 — PCDN-SOS-08-D-008 cross-reference"
        r"[\s\S]+?(?=\n### \d{4}-\d{2}-\d{2}|\Z)"
    )
    match = re.search(pat, text)
    assert match is not None, (
        "2026-05-25 PCDN-SOS-08-D-008 cross-reference §15 entry "
        "not found in SOS-08-E concepts doc"
    )
    return match.group(0)


# ---------------------------------------------------------------------------
# Entry existence + structural assertions
# ---------------------------------------------------------------------------


def test_d008_cross_reference_entry_exists(concepts_text: str) -> None:
    """The §15 2026-05-25 entry exists and names PCDN-SOS-08-D-008."""
    entry = _extract_d008_xref_entry(concepts_text)
    assert "PCDN-SOS-08-D-008" in entry, (
        "Cross-reference entry must name PCDN-SOS-08-D-008"
    )
    # The entry must appear after §15 header and after the prior
    # 2026-05-25 verb-change entry (this is the second 2026-05-25
    # entry on E).
    changelog_idx = concepts_text.index("## 15. Change log")
    entry_idx = concepts_text.index(
        "### 2026-05-25 — PCDN-SOS-08-D-008 cross-reference"
    )
    assert entry_idx > changelog_idx, (
        "PCDN-SOS-08-D-008 cross-reference entry must live in §15"
    )


def test_d008_cross_reference_must_consume_same_parsed_shape(
    concepts_text: str,
) -> None:
    """The entry pins the walker mirror obligation: SOS-08-E walker
    MUST consume the SAME parsed shape as the SOS-08-D walker."""
    entry = _extract_d008_xref_entry(concepts_text)
    assert "MUST consume the SAME parsed shape" in entry, (
        "Walker mirror obligation phrase must appear verbatim"
    )


def test_d008_cross_reference_kind_enum_rising_falling(
    concepts_text: str,
) -> None:
    """The entry names the v1 kind enum as `rising` + `falling`."""
    entry = _extract_d008_xref_entry(concepts_text)
    assert "rising" in entry, "Kind enum must mention rising"
    assert "falling" in entry, "Kind enum must mention falling"
    # Kind enum at v1 phrasing is load-bearing.
    assert "Kind enum at v1" in entry or "kind enum at v1" in entry, (
        "Entry must scope the rising+falling enum to v1"
    )


def test_d008_cross_reference_alias_resolution_documented(
    concepts_text: str,
) -> None:
    """The entry documents the alias-resolution stance: two
    `<sos:clock>` sharing `(source, kind)` are aliases of one
    domain."""
    entry = _extract_d008_xref_entry(concepts_text)
    assert "Alias resolution" in entry or "alias resolution" in entry, (
        "Entry must name 'alias resolution' as a normative item"
    )
    # The (source, kind) tuple is the identity carrier.
    assert "(source, kind)" in entry, (
        "Entry must cite the (source, kind) identity tuple"
    )
    # The alphabetic-first canonical-name rule is load-bearing.
    assert "alphabetic-first" in entry, (
        "Alias resolution must cite the alphabetic-first canonical-"
        "name rule"
    )


def test_d008_cross_reference_backwards_compat_must_cited(
    concepts_text: str,
) -> None:
    """The entry cites the backwards-compatibility MUST — charts
    without `<sos:clock_domains>` continue to emit byte-identical."""
    entry = _extract_d008_xref_entry(concepts_text)
    assert (
        "Backwards-compat" in entry
        or "backwards-compat" in entry
        or "Backwards-compatibility" in entry
    ), "Entry must name backwards-compatibility"
    # MUST keyword present (RFC 2119) in the backwards-compat region.
    assert "MUST" in entry, (
        "Entry must use the RFC 2119 MUST keyword (backwards-compat "
        "obligation is normative)"
    )
    # Cite the byte-identity regression guards.
    assert "byte-identical" in entry or "byte-identity" in entry, (
        "Backwards-compat must cite byte-identical emit guarantee"
    )


def test_d008_cross_reference_authority_relationship_mirror(
    concepts_text: str,
) -> None:
    """The entry declares the authority relationship as `mirror` —
    SOS-08-E mirrors SOS-08-D's element ownership without
    modification."""
    entry = _extract_d008_xref_entry(concepts_text)
    # The authority section must be present.
    assert "Authority" in entry, "Entry must carry an Authority section"
    # The relationship value is `mirror`.
    assert "mirror" in entry, (
        "Authority relationship must be `mirror` (SOS-08-E mirrors "
        "PCDN-SOS-08-D-008 without modification)"
    )


def test_d008_cross_reference_element_shape_xml_reproduced(
    concepts_text: str,
) -> None:
    """The entry reproduces the `<sos:clock_domains>` element shape
    as XML, with the per-clock child carrying all five canonical
    attributes (name, source, kind, period_ns, duty_cycle, phase_ns)."""
    entry = _extract_d008_xref_entry(concepts_text)
    assert "<sos:clock_domains>" in entry, (
        "Entry must reproduce the <sos:clock_domains> XML element"
    )
    assert "<sos:clock " in entry or "<sos:clock\n" in entry, (
        "Entry must reproduce the <sos:clock ...> per-clock child"
    )
    for attr in ("name=", "source=", "kind=", "period_ns",
                 "duty_cycle", "phase_ns"):
        assert attr in entry, (
            f"Element-shape XML fragment must carry `{attr}` attribute"
        )


def test_d008_cross_reference_cites_c2aa1cf(concepts_text: str) -> None:
    """The entry cites commit `c2aa1cf` (the wave-3-future-mclk
    surfacing commit that assumed the now-ratified shape)."""
    entry = _extract_d008_xref_entry(concepts_text)
    assert "c2aa1cf" in entry, (
        "Entry must cite commit c2aa1cf (SOS08E3m wave-3-future-mclk "
        "— surfacing commit)"
    )


# ---------------------------------------------------------------------------
# Additional structural pins (kind-enum rejection routing,
# sampling-clock inheritance applicability, follow-up wave obligation)
# ---------------------------------------------------------------------------


def test_d008_cross_reference_kind_enum_rejection_routes_through_d(
    concepts_text: str,
) -> None:
    """The entry pins the kind-enum rejection contract: kind values
    outside v1 enum raise the SAME chart-vocab error as the SOS-08-D
    walker (`SOS-08-D wave-future-clkkind:`)."""
    entry = _extract_d008_xref_entry(concepts_text)
    assert "SOS-08-D wave-future-clkkind" in entry, (
        "Kind-enum rejection contract must cite the verbatim "
        "`SOS-08-D wave-future-clkkind:` chart-vocab error string"
    )


def test_d008_cross_reference_sampling_clock_inheritance_pre_staged(
    concepts_text: str,
) -> None:
    """The entry pre-stages the `<sos:sampling_clock>` kind-inheritance
    rule for future E phases that introduce sampling-clock-aware
    testbench stimulus."""
    entry = _extract_d008_xref_entry(concepts_text)
    assert "<sos:sampling_clock>" in entry, (
        "Entry must cite <sos:sampling_clock> applicability"
    )
    assert "kind inheritance" in entry or "kind-inheritance" in entry, (
        "Entry must name the kind-inheritance rule"
    )


def test_d008_cross_reference_status_green_pending_followup(
    concepts_text: str,
) -> None:
    """The entry status is green (cross-reference logged) with the
    follow-up implementation wave still owed."""
    entry = _extract_d008_xref_entry(concepts_text)
    # Status line uses the standard green-circle marker.
    assert "Status:" in entry, "Entry must carry a Status line"
    assert "cross-reference logged" in entry, (
        "Status must read 'cross-reference logged'"
    )
    assert "follow-up" in entry, (
        "Status must call out the follow-up implementation wave"
    )
