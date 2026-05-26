"""SOS-09-F membrane-vector emitter package.

Per ``docs/concepts/SOS-09-F-CONCEPTS.md`` (ratified 2026-05-26): this
package owns the six membrane-vector families (§5.1) and the cocotb +
Python CPU stub harness (§5.4). The chart-to-vector emission walker
lives at the sibling module ``vectors_emit``.

Public surface (re-exports from `.base`):

    MembraneVector        - abstract base, four-method protocol
    VectorStep            - per-step stimulus record
    ChannelVectorPlan     - per-channel emission plan
    VectorFamily          - frozen enum (six families)
    derive_seed           - chart-UUID-derived deterministic seed
    FAMILIES_BY_KIND      - §5.1 channel-kind → applicable-families table

Per the spec's §4 ``own`` authority relationships, this package is the
sole authority for vector-family enumeration, adapter shape, traceability
key format, and failure-message vocabulary.
"""

from __future__ import annotations

from .base import (  # noqa: F401
    ChannelVectorPlan,
    EmissionError,
    FAMILIES_BY_KIND,
    MembraneVector,
    VectorFamily,
    VectorStep,
    derive_seed,
    render_failure_message,
    trace_key,
)

__all__ = [
    "ChannelVectorPlan",
    "EmissionError",
    "FAMILIES_BY_KIND",
    "MembraneVector",
    "VectorFamily",
    "VectorStep",
    "derive_seed",
    "render_failure_message",
    "trace_key",
]
