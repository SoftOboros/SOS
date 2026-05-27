"""SOS-13 `BoundsAnalysisInput` producer interface.

Per [SOS-13-CONCEPTS.md §7.3 + §8.1]
(../../docs/concepts/SOS-13-CONCEPTS.md), the chart's bounds-analysis
output (the `BoundsAnalysisInput` dataclass defined in
[`sos13_invariants.py`](./sos13_invariants.py), wave-1E §15 SOS13F1
entry) is the discharging authority for the
[`sos13_eligibility.py`](./sos13_eligibility.py) (wave-5E §15 SOS13E1)
oracle. Without a producer, the consumer side has no canonical way to
manufacture instances: tests synthesise them inline; future SOS-02
host-simulator wiring and SOS-03 conformance-vector wiring each need a
*named* producer surface so the eligibility oracle has one wire to call
into.

This module defines:

  - `BoundsProducer`              — runtime-checkable Protocol for any
                                    upstream that emits a
                                    `BoundsAnalysisInput`.
  - `InMemoryBoundsProducer`      — minimal stub that returns a
                                    pre-built input verbatim; lets tests
                                    and demo scripts exercise the
                                    consumer chain without standing up
                                    a real chart walker.

This module does NOT wire SOS-02 or SOS-03 end-to-end; those bridges
are deferred to future per-phase §15 amendments (named in the SOS-13
§15 SOS13W6D entry that ratified this module).

## Authority boundary

- `BoundsAnalysisInput`, `InvariantSpec`, `DischargeAnnotation` are
  authored in [`sos13_invariants.py`](./sos13_invariants.py); this
  module imports them without redefinition. The dataclass surface
  remains the canonical input contract for both the artefact generator
  (`generate_invariants`) and the eligibility oracle
  (`check_eligibility`); producers populate it, neither side mutates
  it.
- The `BoundsProducer` Protocol's `produce()` signature is owned by
  this module; the registration policy for changing it is
  **Specification Required** (per the SOS-13 §15 SOS13W6D entry below).
- Adding a sibling producer class (e.g. `Sos02TraceBoundsProducer`,
  `Sos03VectorBoundsProducer`, `ScxmlWalkerBoundsProducer`) is **Expert
  Review** — each new producer SHOULD ship next to the stub here unless
  it carries a substantial dependency that warrants its own module.

## `Path` vs `str` vs `bytes` — `Path` chosen

The Protocol's `produce()` accepts `pathlib.Path` rather than `str` or
`bytes`. Reasons:

  1. The expected real producers (SCXML-walker, SOS-02 trace reader,
     SOS-03 vector runner) consume artefacts that live on disk; `Path`
     is the idiomatic Python type for filesystem locations.
  2. `Path` carries platform-correct join semantics; producers that
     resolve sibling artefacts (e.g. SOS-03 reading a `vectors/*.json`
     alongside the chart) avoid str-join landmines.
  3. The stub here ignores the parameter entirely, so the choice has
     no cost for in-memory producers; producers that work from a
     pre-loaded in-memory representation MAY accept any `Path` (or
     `Path(".")`) and ignore it.

Changing this to `str | Path` (the duck-typed broadest contract) or to
`bytes` (for archive-backed producers) requires a Specification
Required §15 amendment per the registration policy above; reviewers
landing the SOS-02 / SOS-03 producers MAY propose that broadening if
either upstream's actual artefact source motivates it.

## INV-SOS-G alignment

Per [SOS-07 INV-SOS-G](../../docs/concepts/SOS-07-CONCEPTS.md), no
verified-strip emission is silent — every unchecked block cites the
invariant that discharges it. The producer/consumer split this module
formalises preserves that invariant by construction:

  - The PRODUCER is responsible for binding each `<sos:discharged>`
    site to its `INV-S-CHART-N` (the `discharges_invariant` field on
    `DischargeAnnotation`); the consumer trusts that binding.
  - The CONSUMER (`sos13_eligibility.check_eligibility`) is
    responsible for refusing strips that lack a citable discharge; the
    producer trusts that refusal.

The two responsibilities never overlap, so adding a new producer (or
fixing a producer bug) cannot accidentally erode INV-SOS-G unless it
also passes the consumer's eligibility check — which is the choke
point that defends the invariant.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from sos13_invariants import BoundsAnalysisInput


# -----------------------------------------------------------------
# Producer Protocol
# -----------------------------------------------------------------


@runtime_checkable
class BoundsProducer(Protocol):
    """Producer interface for `BoundsAnalysisInput`.

    Implementers convert a chart-shaped upstream representation into
    the typed dataclass that SOS-13 eligibility analysis (and the
    `INV-S-CHART-N` artefact generator) consumes.

    The Protocol intentionally accepts a `pathlib.Path` so a producer
    MAY consume the chart's on-disk SCXML or scjson artefact directly;
    producers that work from in-memory representations adapt by
    serialising-then-calling, by accepting any path and ignoring it
    (the stub pattern), or by exposing a sibling constructor /
    factory.

    Conformance:

      - `produce()` MUST return a `BoundsAnalysisInput` instance whose
        `invariants` tuple is stable-ordered across calls for the same
        upstream input (so the `INV-S-CHART-N` numbering does not
        churn build-to-build for unchanged charts; mirrors the
        ordering contract in `sos13_invariants.BoundsAnalysisInput`).
      - `produce()` MUST NOT mutate the returned instance after
        return; the dataclass is frozen by construction but producers
        SHOULD also avoid retaining the instance in mutable internal
        state.
      - `produce()` MAY raise — file-not-found, schema-parse, or
        upstream-IR errors propagate to the caller. The caller decides
        whether an error short-circuits eligibility analysis (typical:
        treat as `chart_bounds=None`, which `check_eligibility` already
        handles conservatively) or aborts the build.

    Real producers landing in future waves (SOS-02 wiring, SOS-03
    wiring, SCXML-walker producer) MUST type-check against this
    Protocol; `isinstance(producer, BoundsProducer)` SHOULD pass at
    runtime via the `@runtime_checkable` decoration.
    """

    def produce(self, chart_path: Path) -> BoundsAnalysisInput:
        """Produce a `BoundsAnalysisInput` for the chart at `chart_path`.

        See the class docstring for conformance requirements.
        """
        ...


# -----------------------------------------------------------------
# Minimal in-memory stub producer
# -----------------------------------------------------------------


class InMemoryBoundsProducer:
    """Stub producer for tests and demo scripts.

    Constructed with a pre-built `BoundsAnalysisInput`; `produce()`
    returns it verbatim regardless of `chart_path`. Lets tests exercise
    the consumer (`sos13_eligibility.check_eligibility`) and the
    generator (`sos13_invariants.generate_invariants`) without standing
    up a real chart walker, file fixture, or simulator trace.

    Example:

        from pathlib import Path
        from sos13_invariants import (
            BoundsAnalysisInput, InvariantSpec, DischargeAnnotation,
        )
        from sos13_bounds_producer import InMemoryBoundsProducer
        from sos13_eligibility import check_eligibility

        bounds = BoundsAnalysisInput.from_lists(
            chart_id="demo",
            invariants=[InvariantSpec(text="tid in [0, MAX)",
                                      chart_site="sched.onentry")],
            discharges=[DischargeAnnotation(chart_state="sched",
                                            check="bounds")],
        )
        producer = InMemoryBoundsProducer(bounds)
        verdict = check_eligibility(
            producer.produce(Path("ignored.scxml")),
            vs_op="VS-OP-1",
            region_id="sched",
        )
        assert verdict.eligible

    The stub is the reference shape that future producer
    implementations follow: small constructor, single `produce()`
    method, no hidden state.
    """

    def __init__(self, bounds: BoundsAnalysisInput) -> None:
        if not isinstance(bounds, BoundsAnalysisInput):
            raise TypeError(
                "InMemoryBoundsProducer expects a BoundsAnalysisInput; "
                f"got {type(bounds).__name__}"
            )
        self._bounds = bounds

    def produce(self, chart_path: Path) -> BoundsAnalysisInput:
        """Return the pre-built `BoundsAnalysisInput` verbatim.

        `chart_path` is accepted to satisfy the `BoundsProducer`
        Protocol but ignored by this stub. Real producers consume it.
        """
        # chart_path intentionally unused; satisfying the Protocol.
        del chart_path
        return self._bounds


__all__ = [
    "BoundsProducer",
    "InMemoryBoundsProducer",
]
