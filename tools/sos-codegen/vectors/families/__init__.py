"""SOS-09-F per-family stimulus modules.

Per ``docs/concepts/SOS-09-F-CONCEPTS.md`` §5.1 / §5.2, every emitted
vector lives in a per-family Python module that exports a
``generate(channel, seed) -> list[VectorStep]`` callable plus a
``MembraneVector`` subclass. The walker
(``vectors_emit.plan_channel``) selects family modules by the channel
``sos:kind`` per the §5.1 family-per-kind table.

Public surface:

    FAMILY_REGISTRY: dict[VectorFamily, FamilyModule]

Each FamilyModule exposes:

    generate(plan: ChannelVectorPlan, seq: int) -> list[VectorStep]
    vector_class: type[MembraneVector]
"""

from __future__ import annotations

from ..base import VectorFamily
from . import (  # noqa: F401
    atomicity,
    clear_on_read,
    initial_value,
    protection,
    side_effect,
    write_then_read,
)


FAMILY_REGISTRY = {
    VectorFamily.INITIAL_VALUE: initial_value,
    VectorFamily.WRITE_THEN_READ: write_then_read,
    VectorFamily.SIDE_EFFECT: side_effect,
    VectorFamily.CLEAR_ON_READ: clear_on_read,
    VectorFamily.ATOMICITY: atomicity,
    VectorFamily.PROTECTION: protection,
}


__all__ = [
    "FAMILY_REGISTRY",
    "atomicity",
    "clear_on_read",
    "initial_value",
    "protection",
    "side_effect",
    "write_then_read",
]
