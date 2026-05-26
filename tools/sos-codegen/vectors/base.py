"""SOS-09-F membrane-vector base types.

Authoritative artefacts owned by this module (per
``docs/concepts/SOS-09-F-CONCEPTS.md`` §4):

  - ``VectorFamily`` — the §5.1 six-family frozen enumeration. Standards
    Action; adding a member requires §16 amendment + cross-phase review.
  - ``FAMILIES_BY_KIND`` — the §5.1 channel-kind → applicable-families
    table. Standards Action.
  - ``MembraneVector`` — the §5.2 abstract base, four-method protocol
    (``setup`` / ``stimulate`` / ``observe`` / ``assert_invariants``).
    Standards Action; adding or removing a method breaks every emitted
    adapter.
  - ``VectorStep`` — record of one stimulus step (the bus.read /
    bus.write / wait_irq calls a family produces, in order).
  - ``trace_key`` — the §5.3 ``MV-<UUID>-<family>-<seq>`` formatter.
    Standards Action.
  - ``derive_seed`` — the §5.4 / PCDN-SOS-09-F-001 chart-UUID-derived
    deterministic seed (``hash(sos:id, family, seq)``).
  - ``render_failure_message`` — the §5.6 failure-message vocabulary
    renderer. Refuses raw-address-only messages per INV-S-MEM-F-2.

This module is a pure-Python contract. The cocotb-side adapter wiring
(the emitted ``test_<family>.py`` files) imports from this module and
the family modules under ``vectors/families/``; the harness primitives
that the adapters call into live at ``vectors/harness.py``.
"""

from __future__ import annotations

import abc
import enum
import hashlib
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

# RFC 4122 canonical hyphenated UUID regex (mirrors sos09_annotations).
_UUID_RE: re.Pattern[str] = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class EmissionError(Exception):
    """Raised when membrane-vector emission violates a §6 invariant.

    Carries enough context (channel name, family, invariant id) for the
    walker to surface a chart-vocabulary error message to the operator.
    """

    def __init__(
        self,
        message: str,
        *,
        invariant: Optional[str] = None,
        channel_name: Optional[str] = None,
        family: Optional[str] = None,
    ) -> None:
        self.invariant = invariant
        self.channel_name = channel_name
        self.family = family
        prefix_parts: list[str] = []
        if invariant:
            prefix_parts.append(f"[{invariant}]")
        if channel_name:
            prefix_parts.append(f"channel={channel_name!r}")
        if family:
            prefix_parts.append(f"family={family!r}")
        prefix = " ".join(prefix_parts)
        super().__init__(f"{prefix}: {message}" if prefix else message)


class VectorFamily(str, enum.Enum):
    """The §5.1 six-family frozen enumeration.

    Standards Action: adding a member breaks INV-S-MEM-F-1 / §5.1's
    family-per-kind table and requires a §16 amendment to
    SOS-09-F-CONCEPTS.md plus cross-phase review (SOS-03 §15 also
    mirrors the family set).
    """

    INITIAL_VALUE = "initial_value"
    WRITE_THEN_READ = "write_then_read"
    SIDE_EFFECT = "side_effect"
    CLEAR_ON_READ = "clear_on_read"
    ATOMICITY = "atomicity"
    PROTECTION = "protection"


# §5.1 family-per-kind applicability table. Channel-kind → frozenset of
# families that apply (subject to additional channel-attribute gating
# performed in vectors_emit.plan_channel; see the per-row notes in §5.1).
#
# Standards Action — flipping a kind → family edge changes which vectors
# the emitter ships, and INV-S-MEM-F-1 ("every applicable family is
# emitted") is asserted against this table.
FAMILIES_BY_KIND: dict[str, frozenset[VectorFamily]] = {
    "status": frozenset(
        {
            VectorFamily.INITIAL_VALUE,
            VectorFamily.CLEAR_ON_READ,
            VectorFamily.PROTECTION,
            VectorFamily.ATOMICITY,
        }
    ),
    "command": frozenset(
        {
            VectorFamily.INITIAL_VALUE,
            VectorFamily.WRITE_THEN_READ,
            VectorFamily.SIDE_EFFECT,
            VectorFamily.PROTECTION,
            VectorFamily.ATOMICITY,
        }
    ),
    "queue": frozenset(
        {
            VectorFamily.INITIAL_VALUE,
            VectorFamily.WRITE_THEN_READ,
            VectorFamily.SIDE_EFFECT,
            VectorFamily.PROTECTION,
            VectorFamily.ATOMICITY,
        }
    ),
    "shared": frozenset(
        {
            VectorFamily.INITIAL_VALUE,
            VectorFamily.WRITE_THEN_READ,
            VectorFamily.CLEAR_ON_READ,
            VectorFamily.SIDE_EFFECT,
            VectorFamily.ATOMICITY,
            VectorFamily.PROTECTION,
        }
    ),
}


@dataclass(frozen=True)
class VectorStep:
    """One stimulus step inside a vector.

    A vector is a list of steps; the harness replays the list in order.
    Each step names one of the §5.4 Python CPU stub primitives plus the
    argument tuple, an optional expected value, and an optional human-
    readable chart-vocabulary description that the §5.6 failure renderer
    uses for ``<stimulus>``.

    The frozen-dataclass shape keeps the emitter deterministic per
    INV-S-MEM-F-6 — same chart annotation + same seed produce
    bit-identical step lists across replays.
    """

    primitive: str          # bus.read | bus.write | wait_irq | concurrent_writer | install_mpu | set_zone | seed
    args: tuple[Any, ...]
    expected: Any = None
    description: str = ""


@dataclass(frozen=True)
class ChannelVectorPlan:
    """All vectors emitted for one chart channel.

    The walker (vectors_emit.plan_channel) produces one
    ChannelVectorPlan per ChannelAnnotation. Each ``family_vectors``
    entry maps a VectorFamily to an ordered list of VectorStep
    sequences — one inner list per ``<seq>`` within that family. The
    traceability key for the j-th vector of family f is
    ``MV-<channel.id>-<f.value>-<j>`` per §5.3.
    """

    channel_id: str               # sos:id UUID
    channel_name: str             # sos:name SV-identifier
    channel_kind: str             # status | command | queue | shared
    channel_zone: str             # privileged | unprivileged
    channel_dir: str              # hw→sw | sw→hw | bidirectional
    address: int                  # byte offset within the SVD peripheral
    width_bits: int               # 1..64
    irq: Optional[str] = None
    mutex: Optional[str] = None
    privilege_region: Optional[str] = None
    # family -> list of step sequences (one per <seq>).
    family_vectors: dict[VectorFamily, list[list[VectorStep]]] = field(
        default_factory=dict
    )


# ---------------------------------------------------------------------------
# §5.3 traceability key formatter
# ---------------------------------------------------------------------------


def trace_key(channel_id: str, family: VectorFamily | str, seq: int) -> str:
    """Return ``MV-<UUID>-<family>-<seq>`` per §5.3.

    Args:
        channel_id: the channel's ``sos:id`` UUID. Validated against the
            RFC 4122 canonical hyphenated form (per PCDN-SOS-09-A-003).
        family: ``VectorFamily`` member OR its string value.
        seq: non-negative integer; the walker assigns these in
            document order within each (channel, family) pair.

    Raises:
        EmissionError: ``channel_id`` is not an RFC 4122 UUID
            (rule §5.3); ``seq`` is negative; ``family`` is not a
            known family.
    """
    if not isinstance(channel_id, str) or not _UUID_RE.match(channel_id):
        raise EmissionError(
            f"trace_key channel_id must be RFC 4122 UUID; got {channel_id!r}",
            invariant="§5.3",
        )
    if isinstance(family, VectorFamily):
        family_token = family.value
    elif isinstance(family, str):
        try:
            family_token = VectorFamily(family).value
        except ValueError as exc:
            raise EmissionError(
                f"trace_key family must be a VectorFamily member; got {family!r}",
                invariant="§5.1",
            ) from exc
    else:
        raise EmissionError(
            f"trace_key family must be a VectorFamily or str; got {type(family).__name__}",
            invariant="§5.1",
        )
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 0:
        raise EmissionError(
            f"trace_key seq must be non-negative integer; got {seq!r}",
            invariant="§5.3",
        )
    return f"MV-{channel_id}-{family_token}-{seq}"


# ---------------------------------------------------------------------------
# §5.4 + PCDN-SOS-09-F-001 chart-UUID-derived deterministic seed
# ---------------------------------------------------------------------------


def derive_seed(channel_id: str, family: VectorFamily | str, seq: int) -> int:
    """Return a 64-bit deterministic seed from (channel UUID, family, seq).

    Per PCDN-SOS-09-F-001 (ratified option (a)): the seed source is a
    chart-UUID-derived hash; no ``PYTEST_SEED`` env var override. Same
    chart + same family + same seq → bit-identical seed across replays,
    across CI nodes, across years (INV-S-MEM-F-6).

    The hash uses SHA-256 and takes the leading 8 bytes as an unsigned
    big-endian integer. SHA-256 is overkill for a seed but its output
    is stable across Python versions and platforms — unlike Python's
    builtin ``hash()`` which is process-local.
    """
    family_token = (
        family.value if isinstance(family, VectorFamily) else str(family)
    )
    h = hashlib.sha256()
    h.update(channel_id.encode("utf-8"))
    h.update(b"|")
    h.update(family_token.encode("utf-8"))
    h.update(b"|")
    h.update(str(int(seq)).encode("utf-8"))
    digest = h.digest()[:8]
    return int.from_bytes(digest, byteorder="big", signed=False)


# ---------------------------------------------------------------------------
# §5.2 MembraneVector base class
# ---------------------------------------------------------------------------


class MembraneVector(abc.ABC):
    """Abstract base for SOS-09-F membrane vectors.

    Carries the seven §5.2 metadata fields (``trace_key``,
    ``channel_id``, ``channel_name``, ``channel_kind``, ``channel_zone``,
    ``family``, plus implementation-specific extras) and the four
    abstract methods (``setup`` / ``stimulate`` / ``observe`` /
    ``assert_invariants``).

    Concrete subclasses live under ``vectors/families/<family>.py``;
    each emits its own ``VectorStep`` sequence via ``stimulate(...)``,
    then ``observe(...)`` collects harness state, then
    ``assert_invariants(...)`` checks the §5.6 vocabulary failure shape.

    Adding or removing a method is a Standards Action per §5.2 — the
    emitted ``test_<family>.py`` files call these methods by name.
    """

    def __init__(
        self,
        *,
        plan: ChannelVectorPlan,
        family: VectorFamily,
        seq: int = 0,
    ) -> None:
        self._plan = plan
        self._family = family
        self._seq = int(seq)
        # Public metadata surface — emitted into the per-test JUnit
        # attributes and the §5.6 failure message vocabulary.
        self.trace_key: str = trace_key(plan.channel_id, family, seq)
        self.channel_id: str = plan.channel_id
        self.channel_name: str = plan.channel_name
        self.channel_kind: str = plan.channel_kind
        self.channel_zone: str = plan.channel_zone
        self.family: str = family.value
        self.seed: int = derive_seed(plan.channel_id, family, seq)

    @abc.abstractmethod
    def setup(self, harness: Any) -> None:
        """Pre-stimulus configuration (e.g. install MPU; seed RNG)."""

    @abc.abstractmethod
    def stimulate(self, harness: Any) -> None:
        """Drive the bus stimulus via harness primitives."""

    @abc.abstractmethod
    def observe(self, harness: Any) -> Any:
        """Return the observed value(s) for assert_invariants."""

    @abc.abstractmethod
    def assert_invariants(self, harness: Any) -> None:
        """Raise on §6 violations; render via render_failure_message."""


# ---------------------------------------------------------------------------
# §5.6 failure-message vocabulary
# ---------------------------------------------------------------------------


# §5.5 failure-type vocabulary (Specification Required per §5.5 / §7).
FAILURE_TYPES: frozenset[str] = frozenset(
    {
        "WriteThenReadMismatch",
        "SideEffectNotObserved",
        "ClearOnReadNotCleared",
        "AtomicityTornRead",
        "AtomicityMutexNotSerialised",
        "ProtectionAccessAccepted",
        "ProtectionEventNotObserved",
        "InitialValueMismatch",
    }
)


def render_failure_message(
    *,
    channel_name: str,
    channel_kind: str,
    channel_zone: str,
    family: VectorFamily | str,
    stimulus: str,
    expected: Any,
    observed: Any,
    channel_id: str,
) -> str:
    """Render a §5.6 chart-vocabulary failure message.

    Shape:
        "channel <sos:name> [kind=<kind>, zone=<zone>] failed <family>
         vector at <stimulus>: expected <X>, got <Y>;
         chart trace: <sos:id-UUID>"

    Per INV-S-MEM-F-2, ``channel_name`` and ``channel_id`` MUST be
    populated (raw-address-only messages are an emitter bug — caught
    here, surfacing as EmissionError before any vector ships).
    """
    if not isinstance(channel_name, str) or not channel_name:
        raise EmissionError(
            "failure-message channel_name MUST be populated "
            "(raw-address-only messages forbidden)",
            invariant="INV-S-MEM-F-2",
        )
    if not isinstance(channel_id, str) or not _UUID_RE.match(channel_id):
        raise EmissionError(
            f"failure-message channel_id MUST be an RFC 4122 UUID; "
            f"got {channel_id!r}",
            invariant="INV-S-MEM-F-2",
        )
    if not isinstance(stimulus, str) or not stimulus:
        raise EmissionError(
            "failure-message stimulus MUST be populated "
            "(chart-vocabulary stimulus description required)",
            invariant="INV-S-MEM-F-2",
        )
    family_token = (
        family.value if isinstance(family, VectorFamily) else str(family)
    )
    return (
        f"channel {channel_name} "
        f"[kind={channel_kind}, zone={channel_zone}] "
        f"failed {family_token} vector at {stimulus}: "
        f"expected {expected!r}, got {observed!r}; "
        f"chart trace: {channel_id}"
    )


# ---------------------------------------------------------------------------
# UUID helpers
# ---------------------------------------------------------------------------


def is_canonical_uuid(value: str) -> bool:
    """Return True iff ``value`` is an RFC 4122 canonical hyphenated UUID."""
    if not isinstance(value, str) or not _UUID_RE.match(value):
        return False
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError):
        return False
    return True


__all__ = [
    "ChannelVectorPlan",
    "EmissionError",
    "FAILURE_TYPES",
    "FAMILIES_BY_KIND",
    "MembraneVector",
    "VectorFamily",
    "VectorStep",
    "derive_seed",
    "is_canonical_uuid",
    "render_failure_message",
    "trace_key",
]
