"""SOS-08-C wave-3-f-future-xreg (2026-05-24 §15) — chart-event raiser
map + cross-region capture helpers.

Shared between ``transliterate_hdl_sv.py`` and
``transliterate_hdl_vhdl.py``.  Per the spec-before-code discipline (see
SOS-08-C §15 wave-3-f-future-xreg amendment), cross-region event-value
capture lifts the wave-3-f-future-A intra-region constraint: a region's
``<onentry>`` / ``<onexit>`` ``<assign expr="event.<EV>.value"/>`` MAY
now reference an event raised by a DIFFERENT region, with the value
arriving on the chart-top broadcast bus the cycle after the raise.

The helpers in this module are dialect-agnostic — they take a
duck-typed ``regions`` sequence where each region exposes ``.name``
and ``.states``, and each state exposes ``.transitions`` carrying a
``.raise_events`` iterable.  Both walkers' ``HdlRegion`` dataclasses
satisfy this shape.

Authority boundary (per the SOS-08-C §0 declaration):
  - Bus signal naming (``chart_event_<EV>_raise_valid`` /
    ``chart_event_<EV>_raise_data``) — relationship **own** (this repo
    authors the convention).
  - Same-cycle multi-raiser conflict semantics — relationship
    **derive** from SCXML §3.13 (microstep ordering); the spec defines
    the run-to-completion ordering, we lower it to a lower-region-
    index priority mux + a runtime ``$warning`` so chart authors
    notice unintended races without blocking codegen.
"""

from __future__ import annotations

from typing import Any, Iterable


def build_chart_event_raiser_map(
    regions: Iterable[Any],
) -> dict[str, list[str]]:
    """Build ``{event_name -> [region_name, ...]}`` from a region list.

    The returned list is **region-document-order** (the order of
    ``regions`` as passed in).  Document order is load-bearing for the
    multi-raiser priority mux: a same-cycle conflict resolves with the
    lower-document-index region's payload winning (cited SCXML §3.13
    microstep ordering — see §15 wave-3-f-future-xreg).

    A region appears at most once per event even if multiple
    transitions raise the same event (the bus aggregation OR's the
    region's own valid pulse internally; this map names region-level
    raisers, not transition-level).
    """
    out: dict[str, list[str]] = {}
    for region in regions:
        rname = getattr(region, "name", None)
        if rname is None:
            continue
        seen_in_region: set[str] = set()
        for state in getattr(region, "states", []) or []:
            for tr in getattr(state, "transitions", []) or []:
                for ev in getattr(tr, "raise_events", []) or []:
                    if not ev or ev in seen_in_region:
                        continue
                    seen_in_region.add(ev)
                    bucket = out.setdefault(ev, [])
                    if rname not in bucket:
                        bucket.append(rname)
    return out


def is_cross_region_capture(
    event_name: str,
    capturing_region_name: str,
    chart_event_raisers: dict[str, list[str]],
) -> bool:
    """Return True iff ``event_name`` is raised by at least one region
    OTHER than ``capturing_region_name`` (and is raised somewhere in
    the chart).

    The contract is:
      * Event raised by no region anywhere in the chart → return False
        (caller treats as the chart-vocab "unraised event" error).
      * Event raised by the capturing region (and possibly others) →
        return False (the capture is satisfiable intra-region; no
        broadcast bus tap required for THIS region's purposes —
        though the chart-top still aggregates).
      * Event raised by sibling regions only → return True (the
        capturing region needs the broadcast bus).
    """
    raisers = chart_event_raisers.get(event_name, [])
    if not raisers:
        return False
    if capturing_region_name in raisers:
        return False
    return True


def chart_event_bus_valid_name(event_name_ident: str) -> str:
    """Chart-top broadcast bus VALID signal name for ``event_name_ident``
    (the already-sanitised event identifier).

    Naming is **normative** per SOS-08-C §15 wave-3-f-future-xreg.
    """
    return f"chart_event_{event_name_ident}_raise_valid"


def chart_event_bus_data_name(event_name_ident: str) -> str:
    """Chart-top broadcast bus DATA signal name for ``event_name_ident``.

    Naming is **normative** per SOS-08-C §15 wave-3-f-future-xreg.
    """
    return f"chart_event_{event_name_ident}_raise_data"


__all__ = [
    "build_chart_event_raiser_map",
    "is_cross_region_capture",
    "chart_event_bus_valid_name",
    "chart_event_bus_data_name",
]
