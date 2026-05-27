"""Tests for SOS-13 verified-strip eligibility analysis.

Per [SOS-13-CONCEPTS.md §7.3]
(../../../docs/concepts/SOS-13-CONCEPTS.md) — *eligibility analysis* —
and §12(b) acceptance gate. These tests pin:

  - the five v1 VS-OP ids are accepted (VS-OP-1 through VS-OP-5);
    anything else raises `UnknownVSOpError`;
  - VS-OP-1 (`get_unchecked`): eligible iff a `<sos:discharged
    check="bounds"/>` annotation exists on the region AND a chart-
    derived invariant covers it; orphan discharge → ineligible;
  - VS-OP-2 / VS-OP-3 (`unwrap_unchecked`): same pattern, gated on
    `check="null"` per §7.5's null → (VS-OP-2, VS-OP-3) mapping;
  - VS-OP-4 (`unreachable_unchecked`): structural — needs a derived
    invariant on the region (no `<sos:discharged>` required; §7.5
    carve-out);
  - VS-OP-5 (non-empty heapless access): structural via INV-S7 /
    INV-S8 cited in `bound_evidence` (§7.5 explicit carve-out);
  - `region_id` missing → ineligible (cannot resolve the chart
    site);
  - `chart_bounds=None` → all VS-OPs ineligible (conservative
    default per §7.3);
  - bonus integration test exercising the existing wave-1
    `apply_verified_strip` callable with both eligible and
    ineligible bounds-derived verdicts (the hook site is the choke
    point that the eligibility module gates).

INV-SOS-G is the cross-phase invariant these tests defend: no strip
is silent — every eligible verdict carries a citable invariant; every
ineligible verdict carries a chart-author-actionable reason.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Mirror the sos-codegen flat-package layout used by sibling tests.
TESTS_DIR = Path(__file__).resolve().parent
TOOL_DIR = TESTS_DIR.parent
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from sos13_eligibility import (  # noqa: E402
    EligibilityVerdict,
    STRUCTURAL_VS_OPS,
    SUPPORTED_VS_OPS,
    UnknownVSOpError,
    VS_OP_5_STRUCTURAL_INVARIANTS,
    VS_OP_TO_CHECK,
    check_eligibility,
)
from sos13_invariants import (  # noqa: E402
    BoundsAnalysisInput,
    DischargeAnnotation,
    InvariantSpec,
)


pytestmark = pytest.mark.verified_strip


# ---------------------------------------------------------------
# Fixtures — minimal BoundsAnalysisInput shapes per VS-OP scenario.
# ---------------------------------------------------------------


def _bounds_with_bounds_discharge(region: str = "sched_dispatch") -> BoundsAnalysisInput:
    """VS-OP-1 eligible: bounds discharge + matching chart-derived
    invariant."""
    return BoundsAnalysisInput.from_lists(
        chart_id="t",
        invariants=[
            InvariantSpec(
                text="tid < MAX_TASKS at sched dispatch entry",
                chart_site=f"{region}.onentry",
                status="derived",
                bound_evidence="ready-queue scan bounds tid",
            ),
        ],
        discharges=[
            DischargeAnnotation(chart_state=region, check="bounds"),
        ],
    )


def _bounds_with_null_discharge(region: str = "sem_take") -> BoundsAnalysisInput:
    """VS-OP-2 / VS-OP-3 eligible: null discharge + matching invariant."""
    return BoundsAnalysisInput.from_lists(
        chart_id="t",
        invariants=[
            InvariantSpec(
                text="Option<TaskHandle> is Some at this site",
                chart_site=f"{region}.guard",
                status="declared",
            ),
        ],
        discharges=[
            DischargeAnnotation(chart_state=region, check="null"),
        ],
    )


def _bounds_with_reachability_only(region: str = "sched_dispatch") -> BoundsAnalysisInput:
    """VS-OP-4 eligible: chart-derived invariant on the region; NO
    `<sos:discharged>` (because §7.5 carves VS-OP-4 out of the
    discharge grammar)."""
    return BoundsAnalysisInput.from_lists(
        chart_id="t",
        invariants=[
            InvariantSpec(
                text="TaskState variants Ready/Running/Blocked only",
                chart_site=f"{region}.onentry",
                status="derived",
                bound_evidence="reachability prunes Suspended branch",
            ),
        ],
        discharges=(),
    )


def _bounds_with_vs_op_5_evidence(
    region: str = "sched_dispatch",
    invariant: str = "INV-S7",
) -> BoundsAnalysisInput:
    """VS-OP-5 eligible: invariant on the region whose `bound_evidence`
    cites INV-S7 (or INV-S8)."""
    return BoundsAnalysisInput.from_lists(
        chart_id="t",
        invariants=[
            InvariantSpec(
                text="ready[p] is non-empty at pick_next",
                chart_site=f"{region}.guard",
                status="derived",
                bound_evidence=(
                    f"{invariant} ready-queue integrity prevents empty pop"
                ),
            ),
        ],
        discharges=(),
    )


def _bounds_empty() -> BoundsAnalysisInput:
    """No invariants, no discharges — every VS-OP is ineligible."""
    return BoundsAnalysisInput.from_lists(chart_id="t")


# ---------------------------------------------------------------
# Catalogue + frozen-enumeration guards.
# ---------------------------------------------------------------


def test_supported_vs_ops_frozen_at_five():
    """SOS-13 §7.1 catalogue is frozen at five values (VS-OP-1
    through VS-OP-5). Standards Action policy gates additions."""
    assert SUPPORTED_VS_OPS == frozenset(
        {"VS-OP-1", "VS-OP-2", "VS-OP-3", "VS-OP-4", "VS-OP-5"}
    )


def test_unknown_vs_op_raises():
    """Per §7.1's Standards Action policy, an unrecognised VS-OP id
    is a hard error — the module MUST NOT silently fall back to
    'eligible' or 'safe-default'."""
    with pytest.raises(UnknownVSOpError):
        check_eligibility(_bounds_empty(), "VS-OP-99", region_id="r")


def test_structural_vs_ops_carve_out_matches_spec():
    """§7.5 carves VS-OP-4 (reachability) and VS-OP-5 (non-empty
    heapless) out of the `<sos:discharged>` chart-annotation grammar."""
    assert STRUCTURAL_VS_OPS == frozenset({"VS-OP-4", "VS-OP-5"})


def test_vs_op_to_check_mapping_matches_section_7_5_table():
    """§7.5's table maps `bounds → VS-OP-1`, `null → (VS-OP-2,
    VS-OP-3)`. Reversed (vs_op → check), that's the three discharge-
    gated VS-OPs."""
    assert VS_OP_TO_CHECK == {
        "VS-OP-1": "bounds",
        "VS-OP-2": "null",
        "VS-OP-3": "null",
    }


# ---------------------------------------------------------------
# `chart_bounds=None` short-circuits to ineligible for every VS-OP.
# ---------------------------------------------------------------


@pytest.mark.parametrize("vs_op", sorted(SUPPORTED_VS_OPS))
def test_none_bounds_rejects_every_vs_op(vs_op):
    """No bounds IR → no proof → ineligible. Conservative default
    per §7.3's 'keep the check' principle. INV-SOS-G demands a citable
    invariant; without an IR, none is available."""
    verdict = check_eligibility(None, vs_op, region_id="any_region")
    assert verdict.eligible is False
    assert verdict.discharging_invariant is None
    assert "ineligible" in verdict.reason.lower() or "refused" in verdict.reason.lower()
    assert verdict.vs_op == vs_op


# ---------------------------------------------------------------
# VS-OP-1 — bounds discharge.
# ---------------------------------------------------------------


def test_vs_op_1_eligible_with_bounds_discharge():
    bounds = _bounds_with_bounds_discharge("sched_dispatch")
    verdict = check_eligibility(bounds, "VS-OP-1", region_id="sched_dispatch")
    assert verdict.eligible is True
    # INV-S-CHART-1 is the 1-based id of the sole invariant in the
    # fixture (per sos13_invariants._invariant_id numbering).
    assert verdict.discharging_invariant == "INV-S-CHART-1"
    assert verdict.vs_op == "VS-OP-1"
    assert "bounds" in verdict.reason


def test_vs_op_1_ineligible_without_bounds_discharge():
    """Bounds IR carries an invariant but no `<sos:discharged>` —
    eligibility refused because the chart author hasn't declared the
    discharge explicitly (per §7.5's INV-SOS-G enforcement)."""
    bounds = BoundsAnalysisInput.from_lists(
        chart_id="t",
        invariants=[
            InvariantSpec(
                text="tid < MAX_TASKS",
                chart_site="sched_dispatch.onentry",
                status="derived",
            ),
        ],
        discharges=(),
    )
    verdict = check_eligibility(bounds, "VS-OP-1", region_id="sched_dispatch")
    assert verdict.eligible is False
    assert verdict.discharging_invariant is None
    assert "<sos:discharged" in verdict.reason


def test_vs_op_1_missing_region_id_rejects():
    """Region-scoped VS-OPs need a region_id to look up the
    annotation. None / empty → ineligible."""
    bounds = _bounds_with_bounds_discharge()
    for rid in (None, "", "   "):
        verdict = check_eligibility(bounds, "VS-OP-1", region_id=rid)
        assert verdict.eligible is False
        assert verdict.discharging_invariant is None


def test_vs_op_1_orphan_discharge_rejects():
    """Discharge annotation exists but NO chart-derived invariant
    covers the region. Per §7.5, the registry surfaces orphans to
    reviewers; eligibility refuses the strip because INV-SOS-G
    requires a citable invariant."""
    bounds = BoundsAnalysisInput.from_lists(
        chart_id="t",
        invariants=(),  # no invariants
        discharges=[
            DischargeAnnotation(chart_state="sched_dispatch", check="bounds"),
        ],
    )
    verdict = check_eligibility(bounds, "VS-OP-1", region_id="sched_dispatch")
    assert verdict.eligible is False
    assert verdict.discharging_invariant is None
    assert "orphan" in verdict.reason.lower()


def test_vs_op_1_explicit_invariant_binding_honored():
    """When the DischargeAnnotation carries `discharges_invariant`
    explicitly, the verdict uses that id verbatim (matching the
    `_build_registry` explicit-binding policy in sos13_invariants)."""
    bounds = BoundsAnalysisInput.from_lists(
        chart_id="t",
        invariants=[
            InvariantSpec(
                text="explicit invariant text",
                chart_site="other_state.onentry",
                status="derived",
            ),
        ],
        discharges=[
            DischargeAnnotation(
                chart_state="sched_dispatch",
                check="bounds",
                discharges_invariant="INV-S-CHART-42",
            ),
        ],
    )
    verdict = check_eligibility(bounds, "VS-OP-1", region_id="sched_dispatch")
    assert verdict.eligible is True
    assert verdict.discharging_invariant == "INV-S-CHART-42"


# ---------------------------------------------------------------
# VS-OP-2 / VS-OP-3 — null discharge.
# ---------------------------------------------------------------


@pytest.mark.parametrize("vs_op", ["VS-OP-2", "VS-OP-3"])
def test_vs_op_2_and_3_eligible_with_null_discharge(vs_op):
    bounds = _bounds_with_null_discharge("sem_take")
    verdict = check_eligibility(bounds, vs_op, region_id="sem_take")
    assert verdict.eligible is True
    assert verdict.discharging_invariant == "INV-S-CHART-1"
    assert verdict.vs_op == vs_op
    # The reason MUST surface the null check value so chart authors
    # can correlate the verdict with the §7.5 grammar.
    assert "null" in verdict.reason


@pytest.mark.parametrize("vs_op", ["VS-OP-2", "VS-OP-3"])
def test_vs_op_2_and_3_ineligible_without_null_discharge(vs_op):
    """A bounds discharge does NOT satisfy VS-OP-2/3 — only a
    `check="null"` annotation does (per §7.5's mapping table)."""
    bounds = _bounds_with_bounds_discharge("sem_take")
    verdict = check_eligibility(bounds, vs_op, region_id="sem_take")
    assert verdict.eligible is False
    assert verdict.discharging_invariant is None


# ---------------------------------------------------------------
# VS-OP-4 — structural reachability (no <sos:discharged> required).
# ---------------------------------------------------------------


def test_vs_op_4_eligible_with_invariant_on_region():
    """VS-OP-4 discharges structurally — the bounds analysis itself
    pruned the unreachable branch, recorded as an InvariantSpec on
    the region. No `<sos:discharged>` required (§7.5 carve-out)."""
    bounds = _bounds_with_reachability_only("sched_dispatch")
    verdict = check_eligibility(bounds, "VS-OP-4", region_id="sched_dispatch")
    assert verdict.eligible is True
    assert verdict.discharging_invariant == "INV-S-CHART-1"
    assert "VS-OP-4" in verdict.reason
    # The verdict's reason MUST NOT pretend the eligibility came from
    # a chart annotation — the §7.5 carve-out language is the load-
    # bearing distinction.
    assert "carve-out" in verdict.reason.lower() or "structural" in verdict.reason.lower()


def test_vs_op_4_ineligible_without_invariant_on_region():
    """No InvariantSpec covers the region → the reachability proof
    is absent → ineligible. Emitting unreachable_unchecked without a
    proof would violate INV-SOS-G."""
    bounds = _bounds_with_reachability_only("some_other_state")
    verdict = check_eligibility(bounds, "VS-OP-4", region_id="sched_dispatch")
    assert verdict.eligible is False
    assert verdict.discharging_invariant is None
    assert "INV-SOS-G" in verdict.reason


def test_vs_op_4_missing_region_id_rejects():
    bounds = _bounds_with_reachability_only()
    verdict = check_eligibility(bounds, "VS-OP-4", region_id=None)
    assert verdict.eligible is False


# ---------------------------------------------------------------
# VS-OP-5 — structural via INV-S7 / INV-S8.
# ---------------------------------------------------------------


@pytest.mark.parametrize("invariant", VS_OP_5_STRUCTURAL_INVARIANTS)
def test_vs_op_5_eligible_with_inv_s7_or_s8_evidence(invariant):
    """VS-OP-5 eligible when the region's invariant evidence cites
    INV-S7 or INV-S8 (per §7.5's VS-OP-5 carve-out). The discharging
    invariant is the cross-port id (NOT INV-S-CHART-N — VS-OP-5's
    authority is SOS-00 §9 invariants per §8's three-namespace
    citation surface)."""
    bounds = _bounds_with_vs_op_5_evidence(
        region="sched_dispatch", invariant=invariant
    )
    verdict = check_eligibility(bounds, "VS-OP-5", region_id="sched_dispatch")
    assert verdict.eligible is True
    assert verdict.discharging_invariant == invariant
    assert verdict.vs_op == "VS-OP-5"


def test_vs_op_5_ineligible_without_structural_invariant():
    """Invariant exists but its evidence doesn't cite INV-S7 / INV-S8
    — the §7.5 carve-out doesn't apply. Refused."""
    bounds = BoundsAnalysisInput.from_lists(
        chart_id="t",
        invariants=[
            InvariantSpec(
                text="some invariant",
                chart_site="sched_dispatch.guard",
                status="derived",
                bound_evidence="unrelated bound proof",
            ),
        ],
    )
    verdict = check_eligibility(bounds, "VS-OP-5", region_id="sched_dispatch")
    assert verdict.eligible is False
    assert verdict.discharging_invariant is None


def test_vs_op_5_ineligible_when_evidence_empty():
    """An invariant with no bound_evidence cannot cite INV-S7 /
    INV-S8 → ineligible."""
    bounds = BoundsAnalysisInput.from_lists(
        chart_id="t",
        invariants=[
            InvariantSpec(
                text="some invariant",
                chart_site="sched_dispatch.guard",
                status="derived",
                bound_evidence="",
            ),
        ],
    )
    verdict = check_eligibility(bounds, "VS-OP-5", region_id="sched_dispatch")
    assert verdict.eligible is False


# ---------------------------------------------------------------
# Verdict-shape integrity.
# ---------------------------------------------------------------


def test_verdict_carries_vs_op_label_on_every_path():
    """The verdict.vs_op field mirrors the call argument so callers
    threading verdicts through pipelines can self-describe."""
    bounds = _bounds_with_bounds_discharge()
    for vs_op in sorted(SUPPORTED_VS_OPS):
        verdict = check_eligibility(bounds, vs_op, region_id="sched_dispatch")
        assert verdict.vs_op == vs_op


def test_eligible_verdict_always_carries_invariant():
    """Per INV-SOS-G — eligibility never returns None for the
    discharging invariant. If the analysis couldn't name the
    invariant, it would be required to return eligible=False."""
    # Cover one eligible case per VS-OP path.
    scenarios = [
        (_bounds_with_bounds_discharge(), "VS-OP-1", "sched_dispatch"),
        (_bounds_with_null_discharge(), "VS-OP-2", "sem_take"),
        (_bounds_with_null_discharge(), "VS-OP-3", "sem_take"),
        (_bounds_with_reachability_only(), "VS-OP-4", "sched_dispatch"),
        (_bounds_with_vs_op_5_evidence(), "VS-OP-5", "sched_dispatch"),
    ]
    for bounds, vs_op, region in scenarios:
        verdict = check_eligibility(bounds, vs_op, region_id=region)
        assert verdict.eligible, f"{vs_op} should be eligible in this fixture"
        assert verdict.discharging_invariant, (
            f"{vs_op}: INV-SOS-G requires a named invariant on eligible"
        )


def test_type_error_on_non_bounds_input():
    """Passing something that isn't a BoundsAnalysisInput (or None)
    is a hard TypeError, not a silent ineligible."""
    with pytest.raises(TypeError):
        check_eligibility({"chart_id": "fake"}, "VS-OP-1", region_id="r")


# ---------------------------------------------------------------
# Integration — apply_verified_strip is the wave-1 hook site;
# eligibility is the choke point that gates it.
# ---------------------------------------------------------------


def test_integration_apply_verified_strip_only_strips_when_eligible():
    """The existing wave-1 `apply_verified_strip` runs only when a
    discharge annotation is present on the region. The eligibility
    module is the spec-aligned gate that decides the same question
    from the bounds-analysis IR. Both surfaces MUST agree for
    INV-SOS-G to hold.

    Concretely: a bounds-discharge annotation on `boot_bounded` MUST
    produce both (a) an eligible VS-OP-1 verdict AND (b) an actual
    unsafe-block emission from `apply_verified_strip`. The
    eligibility module and the post-pass are two independent
    realisations of the §7.5 INV-SOS-G enforcement; this test pins
    their agreement on the common case."""
    from transliterate_rust import (  # noqa: E402
        VerifiedStripConfig,
        apply_verified_strip,
    )

    # Eligibility says "yes":
    bounds = _bounds_with_bounds_discharge("boot_bounded")
    eligible = check_eligibility(
        bounds, "VS-OP-1", region_id="boot_bounded"
    )
    assert eligible.eligible is True
    assert eligible.discharging_invariant == "INV-S-CHART-1"

    # apply_verified_strip says "yes" via its own discharge-config
    # surface (the two surfaces are decoupled at wave-1; future
    # waves will thread the eligibility verdict through):
    src = "dm.tcb[i as usize].state = 1;"
    cfg = VerifiedStripConfig(
        enabled_globally=True,
        region_id="boot_bounded",
        discharges=("bounds",),
    )
    out, audit = apply_verified_strip(
        src, cfg, "boot_bounded", "boot_bounded.onentry"
    )
    assert "unsafe" in out
    assert "get_unchecked" in out
    assert len(audit) == 1
    assert audit[0]["operation"] == "bounds_check_strip"


def test_integration_apply_verified_strip_bounds_input_hook_eligible():
    """The wave-5 `apply_verified_strip` hook accepts an optional
    `bounds_input` parameter that gates the strip on the IR-derived
    eligibility verdict. When eligible, the SAFETY comment cites
    the verdict's `INV-S-CHART-N` id (not the generic INV-SOS-G
    placeholder)."""
    from transliterate_rust import (  # noqa: E402
        VerifiedStripConfig,
        apply_verified_strip,
    )

    bounds = _bounds_with_bounds_discharge("boot_bounded")
    src = "dm.tcb[i as usize].state = 1;"
    cfg = VerifiedStripConfig(
        enabled_globally=True,
        region_id="boot_bounded",
        discharges=("bounds",),
    )
    out, audit = apply_verified_strip(
        src,
        cfg,
        "boot_bounded",
        "boot_bounded.onentry",
        bounds_input=bounds,
    )
    assert "unsafe" in out
    assert "get_unchecked" in out
    # SAFETY comment cites the IR-derived invariant id, not the
    # generic INV-SOS-G placeholder.
    assert "INV-S-CHART-1" in out
    assert len(audit) == 1
    assert "INV-S-CHART-1" in audit[0]["safety_citation"]


def test_integration_apply_verified_strip_bounds_input_hook_refuses():
    """When the eligibility verdict is ineligible (no chart-derived
    invariant covers the region, even though the config has a
    discharge), the wave-5 hook refuses the strip. The safe-default
    emission survives and no audit entry is recorded — the IR
    layer's INV-SOS-G enforcement caught what the chart-annotation
    layer missed (orphan-discharge case)."""
    from transliterate_rust import (  # noqa: E402
        VerifiedStripConfig,
        apply_verified_strip,
    )

    # Orphan discharge: annotation says "bounds discharged" but no
    # InvariantSpec covers the region.
    bounds = BoundsAnalysisInput.from_lists(
        chart_id="t",
        invariants=(),
        discharges=[
            DischargeAnnotation(chart_state="boot_bounded", check="bounds"),
        ],
    )
    src = "dm.tcb[i as usize].state = 1;"
    cfg = VerifiedStripConfig(
        enabled_globally=True,
        region_id="boot_bounded",
        discharges=("bounds",),
    )
    out, audit = apply_verified_strip(
        src,
        cfg,
        "boot_bounded",
        "boot_bounded.onentry",
        bounds_input=bounds,
    )
    # Strip refused — output is byte-identical to input; audit empty.
    assert out == src
    assert audit == []


def test_integration_apply_verified_strip_no_bounds_input_preserves_wave_1_behaviour():
    """Calling `apply_verified_strip` without the `bounds_input`
    kwarg MUST behave exactly as wave-1 — the eligibility hook is
    opportunistic, not a hard precondition. This pins the
    spec-before-code phasing: the hook is wired but the existing
    callers (and the test suite for wave-1) keep working."""
    from transliterate_rust import (  # noqa: E402
        VerifiedStripConfig,
        apply_verified_strip,
    )

    src = "dm.tcb[i as usize].state = 1;"
    cfg = VerifiedStripConfig(
        enabled_globally=True,
        region_id="boot_bounded",
        discharges=("bounds",),
    )
    out, audit = apply_verified_strip(
        src, cfg, "boot_bounded", "boot_bounded.onentry"
    )
    assert "unsafe" in out
    assert "get_unchecked" in out
    assert "INV-SOS-G" in out  # wave-1 placeholder, not INV-S-CHART-N
    assert len(audit) == 1


def test_integration_eligibility_refusal_aligns_with_strip_refusal():
    """Mirror of the previous test for the negative case. When the
    eligibility module says 'no chart-discharge', the wave-1
    post-pass MUST also refuse the strip (because its own discharge
    config is similarly missing the annotation)."""
    from transliterate_rust import (  # noqa: E402
        VerifiedStripConfig,
        apply_verified_strip,
    )

    bounds = BoundsAnalysisInput.from_lists(
        chart_id="t",
        invariants=[
            InvariantSpec(
                text="tid < MAX_TASKS",
                chart_site="boot_bounded.onentry",
                status="derived",
            ),
        ],
        discharges=(),  # no discharge → ineligible
    )
    eligible = check_eligibility(
        bounds, "VS-OP-1", region_id="boot_bounded"
    )
    assert eligible.eligible is False

    # The wave-1 post-pass agrees — no discharges in the config →
    # is_active() returns False → no strip.
    src = "dm.tcb[i as usize].state = 1;"
    cfg = VerifiedStripConfig(
        enabled_globally=True,
        region_id="boot_bounded",
        discharges=(),  # no discharge in config either
    )
    out, audit = apply_verified_strip(
        src, cfg, "boot_bounded", "boot_bounded.onentry"
    )
    assert out == src
    assert audit == []
