"""SOS-13 verified-strip eligibility analysis.

Per [SOS-13-CONCEPTS.md §7.3]
(../../docs/concepts/SOS-13-CONCEPTS.md) — *eligibility analysis* — the
codegen tool MUST, before emitting any `VS-OP-*` unsafe block under
`--profile verified-strip`, ask the chart's bound-analysis IR whether
the discharging obligation for that site is satisfied. The analysis
answers "yes (with a citable invariant)" → emit unchecked; "no" or
"unknown" → fall back to the `dev-keep` safe-default form.

This module is that analysis. It consumes the same `BoundsAnalysisInput`
shape that Wave-1E [`sos13_invariants.py`](./sos13_invariants.py)
already defines (so the SOS-02 / SOS-03 future-wiring stays consistent
across both modules) and returns an `EligibilityVerdict` per call.

## VS-OP catalogue mapping (per [§7.1] + [§7.5])

| `vs_op`     | Rust operation              | Discharge source                                                  |
|-------------|-----------------------------|--------------------------------------------------------------------|
| `VS-OP-1`   | `slice.get_unchecked(i)`    | `<sos:discharged check="bounds"/>` on the region's chart-state.    |
| `VS-OP-2`   | `option.unwrap_unchecked()` | `<sos:discharged check="null"/>` on the region's chart-state.      |
| `VS-OP-3`   | `result.unwrap_unchecked()` | `<sos:discharged check="null"/>` on the region's chart-state.      |
| `VS-OP-4`   | `core::hint::unreachable_unchecked()` | Structural — the region's chart-bounds carry a derived/declared invariant covering the branch (no `<sos:discharged>` required; §7.5 explicitly carves VS-OP-4 out of the chart annotation grammar, mirroring §7.5's VS-OP-5 carve-out for INV-S7/INV-S8). |
| `VS-OP-5`   | non-empty heapless access   | Structural — INV-S7 / INV-S8 ready-queue / wait-queue invariants (§7.5 explicit carve-out). The region's chart-bounds MUST carry an invariant whose `bound_evidence` cites INV-S7 or INV-S8. |

Conservative default: when the spec text is partial on a `vs_op`'s
eligibility rule (currently only VS-OP-4 and VS-OP-5 — both structural),
this module REFUSES to mark the site eligible without a clear
discharging invariant. The fallback "emit safe form" surface is always
sound; the upgrade path is the explicit opt-in.

## Spec deviation note (logged in SOS-13 §15)

The Wave-5 task prompt named a hypothetical `VS-OP-5 = transmute_unchecked`
catalogue entry; the ratified [§7.1] catalogue lists VS-OP-5 as
*non-empty heapless access* discharging via the structural INV-S7 /
INV-S8 invariants. This module follows the ratified spec. The prompt's
"VS-OP-4 = `assume`" framing is reconciled the same way — the ratified
§7.1 names VS-OP-4 as `core::hint::unreachable_unchecked()`; we treat
both `assume` and `unreachable_unchecked` as VS-OP-4 since both
discharge against the same reachability claim.

## Public surface

    EligibilityVerdict          — one analysis result.
    SUPPORTED_VS_OPS            — frozen set of the five v1 VS-OP ids.
    check_eligibility(...)      — pure function: bounds + vs_op → verdict.
    UnknownVSOpError            — raised for vs_op outside the catalogue.

## Integration

Wave-3 `transliterate_rust.py` calls `check_eligibility(...)` at the
top of `apply_verified_strip(...)` (or a per-site equivalent) to gate
the strip on a chart-level proof. When the verdict is ineligible, the
post-pass leaves the safe-default emission in place and (per §7.3
last paragraph) the eligibility module's `verdict.reason` MAY be
embedded as a comment so the reviewer can see *why* the strip didn't
happen.

The eligibility analysis does NOT modify the chart, the bounds IR, or
the generated Rust; it is a pure read-only oracle. Side effects (audit
log writes, SAFETY comment emission) remain in `transliterate_rust.py` /
`verified_audit.py` per the existing SOS-13 wave-1 architecture.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sos13_invariants import (
    BoundsAnalysisInput,
    CHECK_TO_VS_OPS,
    DischargeAnnotation,
    InvariantSpec,
    RECOGNIZED_CHECKS,
    _invariant_id,
)


# -----------------------------------------------------------------
# Frozen VS-OP catalogue — mirrors SOS-13 §7.1.
# -----------------------------------------------------------------

# The five v1 VS-OP identifiers, per §7.1's frozen enumeration. Adding
# a new VS-OP requires a Standards Action §15 amendment to SOS-13 §7.1;
# this constant MUST be updated in the same change.
SUPPORTED_VS_OPS: frozenset[str] = frozenset(
    {"VS-OP-1", "VS-OP-2", "VS-OP-3", "VS-OP-4", "VS-OP-5"}
)


# VS-OPs that discharge against the `<sos:discharged>` chart annotation
# grammar (§7.5). Inverse of CHECK_TO_VS_OPS — given a vs_op, what
# `check` value would discharge it?
VS_OP_TO_CHECK: dict[str, str] = {
    "VS-OP-1": "bounds",
    "VS-OP-2": "null",
    "VS-OP-3": "null",
}

# VS-OPs whose discharging authority is structural (no explicit
# `<sos:discharged>` annotation required; the §7.5 grammar explicitly
# carves these out). The bounds-analysis IR carries the proof directly
# as an InvariantSpec whose `bound_evidence` cites the discharging
# invariant.
STRUCTURAL_VS_OPS: frozenset[str] = frozenset({"VS-OP-4", "VS-OP-5"})


# Invariant ids whose presence in a chart-derived invariant's
# `bound_evidence` field signals that a VS-OP-5 (non-empty heapless
# access) is structurally discharged. From SOS-13 §7.5 "VS-OP-5 (...)
# discharges via the chart's wait-queue / ready-queue invariants" and
# SOS-00 §9 (cross-port invariants).
VS_OP_5_STRUCTURAL_INVARIANTS: tuple[str, ...] = ("INV-S7", "INV-S8")


# -----------------------------------------------------------------
# Verdict dataclass + error type
# -----------------------------------------------------------------


class UnknownVSOpError(ValueError):
    """Raised when `check_eligibility` is called with a `vs_op` outside
    the frozen v1 catalogue (`SUPPORTED_VS_OPS`). Per SOS-13 §7.1's
    Standards Action registration policy, a new VS-OP requires a §15
    amendment + a coordinated update to `SUPPORTED_VS_OPS` before this
    module will accept it."""


@dataclass(frozen=True)
class EligibilityVerdict:
    """One eligibility analysis result.

    Attributes:
        eligible:               True iff the VS-OP MAY be emitted at
                                this site. When False, the caller MUST
                                fall back to `dev-keep` safe-default
                                emission per §7.3.
        discharging_invariant:  The `INV-S-CHART-N` (or `INV-S7` /
                                `INV-S8` for structural VS-OP-5) id
                                whose discharge justifies the strip,
                                per INV-SOS-G. None when `eligible` is
                                False.
        reason:                 Chart-author-friendly explanation. On
                                an eligible verdict this names the
                                proof source; on an ineligible verdict
                                this explains what's missing so the
                                chart author knows what to declare.
        vs_op:                  The VS-OP id the verdict applies to.
                                Mirrored back from the call so callers
                                that thread verdicts through pipelines
                                can self-describe.
    """

    eligible: bool
    discharging_invariant: Optional[str]
    reason: str
    vs_op: str = ""


# -----------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------


def _matching_discharge(
    bounds: BoundsAnalysisInput,
    region_id: str,
    check: str,
) -> Optional[DischargeAnnotation]:
    """Find the first `DischargeAnnotation` on the given region whose
    `check` matches. Returns None if no match — the caller treats that
    as "ineligible" per §7.3's conservative default."""
    for ann in bounds.discharges:
        if ann.chart_state == region_id and ann.check == check:
            return ann
    return None


def _invariant_for_state(
    bounds: BoundsAnalysisInput,
    region_id: str,
) -> Optional[tuple[int, InvariantSpec]]:
    """Find the first chart-derived invariant whose `chart_site` is
    rooted at `region_id` (matching the prefix policy used by
    `sos13_invariants._build_registry`'s fallback path). Returns a
    `(1-based-index, spec)` tuple or None.

    The 1-based index lets the caller reconstruct the `INV-S-CHART-N`
    id via `sos13_invariants._invariant_id(i)`, keeping the numbering
    convention consistent across modules."""
    for i, spec in enumerate(bounds.invariants, start=1):
        prefix = spec.chart_site.split(".", 1)[0]
        if prefix == region_id:
            return (i, spec)
    return None


def _invariant_for_state_with_evidence(
    bounds: BoundsAnalysisInput,
    region_id: str,
    evidence_keywords: tuple[str, ...],
) -> Optional[tuple[int, InvariantSpec]]:
    """Find the first invariant on `region_id` whose `bound_evidence`
    field mentions one of `evidence_keywords` (case-sensitive,
    substring). Used by VS-OP-5's structural discharge check — the
    invariant MUST cite INV-S7 or INV-S8 in its evidence text for the
    structural mapping to apply (per §7.5's VS-OP-5 carve-out)."""
    for i, spec in enumerate(bounds.invariants, start=1):
        prefix = spec.chart_site.split(".", 1)[0]
        if prefix != region_id:
            continue
        if not spec.bound_evidence:
            continue
        for kw in evidence_keywords:
            if kw in spec.bound_evidence:
                return (i, spec)
    return None


def _resolve_chart_invariant_id(
    bounds: BoundsAnalysisInput,
    region_id: str,
    explicit: str,
) -> Optional[str]:
    """Resolve an `INV-S-CHART-N` id for a discharge on `region_id`.

    If the `DischargeAnnotation` set `discharges_invariant` explicitly
    (matching the explicit-binding path in
    `sos13_invariants._build_registry`), return that verbatim. Otherwise
    fall back to a prefix match against the chart-derived invariants;
    return `INV-S-CHART-<n>` for the first matching invariant, or None
    if no invariant covers the region (orphan discharge — see §7.5)."""
    if explicit.strip():
        return explicit
    match = _invariant_for_state(bounds, region_id)
    if match is None:
        return None
    idx, _ = match
    return _invariant_id(idx)


# -----------------------------------------------------------------
# Per-VS-OP eligibility rules
# -----------------------------------------------------------------


def _eligibility_for_discharge_vs_op(
    bounds: BoundsAnalysisInput,
    vs_op: str,
    region_id: Optional[str],
) -> EligibilityVerdict:
    """VS-OP-1 / VS-OP-2 / VS-OP-3 — discharged via the `<sos:discharged>`
    chart annotation grammar (§7.5).

    Eligibility rule: the region MUST carry a `<sos:discharged>`
    annotation whose `check` value maps to this VS-OP. The discharging
    invariant is the `INV-S-CHART-N` whose chart-site is rooted at the
    region (explicit binding wins; prefix match is the fallback, matching
    the existing `_build_registry` policy in `sos13_invariants`).
    """
    check = VS_OP_TO_CHECK[vs_op]
    if region_id is None or not region_id.strip():
        return EligibilityVerdict(
            eligible=False,
            discharging_invariant=None,
            reason=(
                f"{vs_op} requires a region_id to look up the chart's "
                f"<sos:discharged check=\"{check}\"/> annotation; none "
                f"provided (per SOS-13 §7.3 + §7.5)."
            ),
            vs_op=vs_op,
        )
    ann = _matching_discharge(bounds, region_id, check)
    if ann is None:
        return EligibilityVerdict(
            eligible=False,
            discharging_invariant=None,
            reason=(
                f"{vs_op} requires a <sos:discharged check=\"{check}\"/> "
                f"annotation on chart-state {region_id!r}; none found in "
                f"the bounds-analysis IR. Add the annotation to the "
                f"chart to opt this site into verified-strip."
            ),
            vs_op=vs_op,
        )
    inv_id = _resolve_chart_invariant_id(
        bounds, region_id, ann.discharges_invariant
    )
    if inv_id is None:
        # Orphan discharge — annotation exists but no chart-derived
        # invariant covers the region. §7.5 surfaces this to the
        # reviewer via the registry; the eligibility surface treats it
        # as a conservative "ineligible" so we never strip without a
        # citable invariant.
        return EligibilityVerdict(
            eligible=False,
            discharging_invariant=None,
            reason=(
                f"{vs_op} discharge annotation on {region_id!r} is "
                f"orphan — no INV-S-CHART-N covers the region. Strip "
                f"refused (per §7.3's conservative default); INV-SOS-G "
                f"requires a citable invariant per emitted unsafe block."
            ),
            vs_op=vs_op,
        )
    return EligibilityVerdict(
        eligible=True,
        discharging_invariant=inv_id,
        reason=(
            f"{vs_op} eligible: chart-state {region_id!r} declares "
            f"<sos:discharged check=\"{check}\"/>, discharged by {inv_id} "
            f"(per SOS-13 §7.3, §7.5, INV-SOS-G)."
        ),
        vs_op=vs_op,
    )


def _eligibility_for_vs_op_4(
    bounds: BoundsAnalysisInput,
    region_id: Optional[str],
) -> EligibilityVerdict:
    """VS-OP-4 (`unreachable_unchecked` / `assume`) — structural
    discharge.

    §7.5 explicitly carves VS-OP-4 out of the `<sos:discharged>` chart
    annotation grammar (the grammar's four `check` values cover
    `bounds | div-by-zero | null | overflow`; reachability is not in
    the list). The discharge comes from the chart's bounds analysis
    itself: if the branch is not in the chart's reachable-state set,
    the chart-derived `INV-S-CHART-N` series carries the reachability
    proof as a `derived` (or `declared`) invariant rooted at the
    region.

    Eligibility rule: the region MUST have at least one
    chart-derived `InvariantSpec` whose `chart_site` is rooted at
    `region_id`. The discharging invariant is the matching
    `INV-S-CHART-N`."""
    if region_id is None or not region_id.strip():
        return EligibilityVerdict(
            eligible=False,
            discharging_invariant=None,
            reason=(
                "VS-OP-4 requires a region_id to look up the chart's "
                "reachability proof; none provided (per SOS-13 §7.3)."
            ),
            vs_op="VS-OP-4",
        )
    match = _invariant_for_state(bounds, region_id)
    if match is None:
        return EligibilityVerdict(
            eligible=False,
            discharging_invariant=None,
            reason=(
                f"VS-OP-4 requires the chart's bounds analysis to "
                f"carry a reachability invariant rooted at "
                f"{region_id!r}; none found. Strip refused — emitting "
                f"unreachable_unchecked without a citable invariant "
                f"would violate INV-SOS-G."
            ),
            vs_op="VS-OP-4",
        )
    idx, _ = match
    inv_id = _invariant_id(idx)
    return EligibilityVerdict(
        eligible=True,
        discharging_invariant=inv_id,
        reason=(
            f"VS-OP-4 eligible: chart-state {region_id!r} carries "
            f"{inv_id} as a structural reachability invariant (per "
            f"SOS-13 §7.3, §7.5's VS-OP-4 carve-out, INV-SOS-G)."
        ),
        vs_op="VS-OP-4",
    )


def _eligibility_for_vs_op_5(
    bounds: BoundsAnalysisInput,
    region_id: Optional[str],
) -> EligibilityVerdict:
    """VS-OP-5 (non-empty `heapless::Vec` access) — structural
    discharge via INV-S7 / INV-S8.

    §7.5 explicitly states: "VS-OP-5 (heapless-vec non-empty access)
    discharges via the chart's wait-queue / ready-queue invariants and
    does not require an explicit `<sos:discharged>` since the
    discharging invariant is the structural INV-S7 / INV-S8 contract
    rather than a per-scope assertion."

    Eligibility rule: the region MUST carry a chart-derived
    InvariantSpec whose `bound_evidence` text cites INV-S7 or INV-S8.
    The discharging invariant is the cited SOS-00 §9 invariant
    (NOT an `INV-S-CHART-N` — VS-OP-5's authority is the cross-port
    invariant series, not the chart-derived series; this matches the
    §8 citation format's three-namespace surface)."""
    if region_id is None or not region_id.strip():
        return EligibilityVerdict(
            eligible=False,
            discharging_invariant=None,
            reason=(
                "VS-OP-5 requires a region_id to look up the chart's "
                "non-empty-queue invariant; none provided (per SOS-13 "
                "§7.3 + §7.5 VS-OP-5 carve-out)."
            ),
            vs_op="VS-OP-5",
        )
    match = _invariant_for_state_with_evidence(
        bounds, region_id, VS_OP_5_STRUCTURAL_INVARIANTS
    )
    if match is None:
        return EligibilityVerdict(
            eligible=False,
            discharging_invariant=None,
            reason=(
                f"VS-OP-5 requires the chart-state {region_id!r} to "
                f"carry an invariant whose bound_evidence cites INV-S7 "
                f"or INV-S8 (per SOS-13 §7.5 VS-OP-5 carve-out + "
                f"SOS-00 §9 cross-port invariants). None found. Strip "
                f"refused."
            ),
            vs_op="VS-OP-5",
        )
    _, spec = match
    # Pull the first INV-S7 / INV-S8 mention out of the evidence text
    # — the citation surface (§8) names the cross-port invariant
    # directly, not the chart-derived wrapper.
    for kw in VS_OP_5_STRUCTURAL_INVARIANTS:
        if kw in spec.bound_evidence:
            return EligibilityVerdict(
                eligible=True,
                discharging_invariant=kw,
                reason=(
                    f"VS-OP-5 eligible: chart-state {region_id!r} "
                    f"carries an invariant citing {kw} as the "
                    f"structural non-empty proof (per SOS-13 §7.5, "
                    f"SOS-00 §9, INV-SOS-G)."
                ),
                vs_op="VS-OP-5",
            )
    # Unreachable in practice — the helper that returned `match`
    # already confirmed one of the keywords matched. Defensive.
    return EligibilityVerdict(
        eligible=False,
        discharging_invariant=None,
        reason="VS-OP-5 internal: matched invariant lost evidence cite.",
        vs_op="VS-OP-5",
    )


# -----------------------------------------------------------------
# Public entrypoint
# -----------------------------------------------------------------


def check_eligibility(
    chart_bounds: Optional[BoundsAnalysisInput],
    vs_op: str,
    region_id: Optional[str] = None,
) -> EligibilityVerdict:
    """Decide whether `vs_op` MAY be emitted at the call site rooted at
    `region_id`, given the chart's bounds-analysis IR.

    Returns an `EligibilityVerdict`. The caller (typically
    `transliterate_rust.apply_verified_strip`) consults `eligible`:

      * True  — emit the unchecked Rust form per §7.1; embed
                `discharging_invariant` in the SAFETY comment per §8;
                record an audit-log entry per §7.4.
      * False — fall back to the `dev-keep` safe-default emission per
                §7.3's last paragraph ("the default is 'keep the
                check'"). The `reason` field MAY be emitted as a
                comment so the reviewer can see why the strip didn't
                happen.

    Per INV-SOS-G, no unchecked emission is silent: this function is
    the choke point that enforces that invariant on the codegen side.

    Raises:
        UnknownVSOpError: `vs_op` is not in `SUPPORTED_VS_OPS`. Per
            §7.1's Standards Action policy, adding a VS-OP requires a
            §15 amendment first.
    """
    if vs_op not in SUPPORTED_VS_OPS:
        raise UnknownVSOpError(
            f"Unknown vs_op {vs_op!r}; expected one of "
            f"{sorted(SUPPORTED_VS_OPS)}. Adding a VS-OP requires a "
            f"§15 amendment to SOS-13 §7.1 (Standards Action policy)."
        )

    # `chart_bounds=None` short-circuits to ineligible — the chart's
    # bounds analysis hasn't produced an IR, so we cannot prove any
    # discharge. This is the conservative default per §7.3.
    if chart_bounds is None:
        return EligibilityVerdict(
            eligible=False,
            discharging_invariant=None,
            reason=(
                f"{vs_op} ineligible: no chart_bounds supplied. The "
                f"bounds-analysis IR is the discharging authority; "
                f"without it, INV-SOS-G cannot be satisfied."
            ),
            vs_op=vs_op,
        )

    if not isinstance(chart_bounds, BoundsAnalysisInput):
        raise TypeError(
            "check_eligibility() expects chart_bounds to be a "
            "BoundsAnalysisInput (or None); got "
            f"{type(chart_bounds).__name__}"
        )

    if vs_op in VS_OP_TO_CHECK:
        return _eligibility_for_discharge_vs_op(
            chart_bounds, vs_op, region_id
        )
    if vs_op == "VS-OP-4":
        return _eligibility_for_vs_op_4(chart_bounds, region_id)
    if vs_op == "VS-OP-5":
        return _eligibility_for_vs_op_5(chart_bounds, region_id)
    # Defensive — SUPPORTED_VS_OPS membership was already checked.
    raise UnknownVSOpError(
        f"Internal: vs_op {vs_op!r} passed the catalogue check but no "
        f"dispatcher matched. This indicates an unsynchronised update "
        f"between SUPPORTED_VS_OPS and the dispatch table; a §15 "
        f"amendment is required."
    )


__all__ = [
    "EligibilityVerdict",
    "SUPPORTED_VS_OPS",
    "STRUCTURAL_VS_OPS",
    "VS_OP_TO_CHECK",
    "VS_OP_5_STRUCTURAL_INVARIANTS",
    "UnknownVSOpError",
    "check_eligibility",
]
