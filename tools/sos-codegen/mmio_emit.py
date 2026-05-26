"""SOS-10 `mmio` medium emitter — synthesises SOS-09 channel annotations.

Per ``docs/concepts/SOS-10-CONCEPTS.md`` §6.3 (ratified 2026-05-23): the
``mmio`` medium **composes** SOS-09 membrane primitives rather than
introducing a new wire format. Each cross-piece event with
``<sos:medium kind="mmio"/>`` compiles to one or more SOS-09 channel
declarations; the SOS-09 emitter family (C HAL, Rust HAL, regfile, SVD,
MPU, vectors) takes over from there per §6.3:

    "Wire format: SOS-09 membrane channels (status/command/queue/shared).
     The orchestrator's cross-piece events for the `mmio` medium compile
     to SOS-09 channel declarations; the SOS-09 emitter takes over from
     there."

This module reads an :class:`OrchestratorAnnotations` model (as produced
by :func:`sos10_annotations.parse_orchestrator_annotations`), filters for
``kind="mmio"`` cross-piece transitions, and synthesises one or two
SOS-09 :class:`ChannelAnnotation`-shaped JSON entries per transition
following the kind-mapping table below.

Crucially, this module does NOT invoke the SOS-09 emitters; it produces
INPUTS for them (the channel-annotation JSON + a small adapter script).
The actual six-artifact emission (C HAL / Rust HAL / regfile / SVD /
MPU / vectors) remains downstream. Per the task brief: "DO NOT invoke
SOS-09 emitters yourself or generate any SOS-09 output artifacts."

Authority: SOS-10-CONCEPTS §6.3, INV-S-ORCH-1 / -3 / -4; SOS-09-CONCEPTS
§5.1 (channel kinds: ``status`` / ``command`` / ``queue`` / ``shared``);
SOS-09-A-CONCEPTS §5.2 (the twelve-key annotation set this module emits
into).

Public surface:

    plan_mmio(orchestrator: OrchestratorAnnotations) -> list[DerivedChannel]
    emit_mmio(
        orchestrator: OrchestratorAnnotations,
        *, chart_id: str, out_dir: Path
    ) -> dict
    DerivedChannel  -- typed shape of one synthesised channel
    MmioEmitError   -- raised on unsupported mmio-kind hints
    main(argv)      -- CLI entry point

Kind-mapping defaults (per task brief + §6.3 + SOS-09 §5.1):

    notification (no return payload)   -> 1 `command` channel
                                          (direction inferred from
                                           piece-lang pair)
    request_response                   -> 1 `command` + 1 `status` pair
    streaming                          -> 1 `queue` channel
    shared_surface                     -> 1 `shared` channel

The chart MAY hint the mapping via a ``<sos:mmio_kind>...</sos:mmio_kind>``
sub-element of ``<sos:medium kind="mmio">`` (surfaced through
:class:`MediumAnnotation.extras` if/when SOS-10's annotation parser
expands to recognise it) or via the chart's ``other_element`` children of
the medium node. Until that hint is wired through, the default is
``notification`` and the emitter logs nothing — chart authors get a
single command channel per event.

Direction inference (sw <-> hw): a piece's ``lang`` token chooses the
side. The four canonical software langs are ``rust`` / ``c`` / ``cpp`` /
``python``; hardware langs are ``vhdl`` / ``systemverilog`` / ``sv``.
Any other lang token defaults to software. If both source and target are
software (e.g. python <-> c), the medium kind is misapplied — ``mmio``
SHOULD be ``in-process`` or ``shared-memory`` instead — but the emitter
still produces a valid channel (treating it as ``sw->hw`` from source's
perspective) and lets downstream tooling surface the misuse.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

# Self-relative import — this module lives at tools/sos-codegen/.
_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sos10_annotations import (  # noqa: E402
    CrossPieceTransitionAnnotation,
    MediumAnnotation,
    OrchestratorAnnotations,
    PieceAnnotation,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# UUID namespace for derived channel IDs. Picked once, frozen — changing
# this would re-key every previously-emitted channel manifest. (Generated
# via ``uuid.uuid5(uuid.NAMESPACE_URL, "https://softoboros.com/sos-10/mmio")``
# at module-author time; pasted here as a constant so the value does not
# depend on whatever NAMESPACE_URL resolves to in any given Python build.)
MMIO_UUID_NAMESPACE: uuid.UUID = uuid.UUID("a8d9f6c2-0b1a-5e2f-9c4d-1f6e3b8a7c91")

# `sos:mmio_kind` hint -> one or more (channel-role, sos:kind) tuples.
# The role is part of the synthesised channel name (e.g. "_cmd" / "_resp"
# / "_q" / "_shared") and the cache key for cross-event deduplication.
_MMIO_KIND_TO_CHANNELS: dict[str, tuple[tuple[str, str], ...]] = {
    "notification": (("cmd", "command"),),
    "request_response": (("cmd", "command"), ("resp", "status")),
    "streaming": (("q", "queue"),),
    "shared_surface": (("shared", "shared"),),
}

# Default hint when the chart's `<sos:medium kind="mmio">` has no
# `<sos:mmio_kind>` sub-element / extras override.
_DEFAULT_MMIO_KIND: str = "notification"

# Recognised software lang tokens. Anything not in HW_LANGS that isn't
# explicitly here still defaults to "software" — this preserves
# forward-compat with future SOS-04 lang additions.
_HW_LANGS: frozenset[str] = frozenset({"vhdl", "systemverilog", "sv", "verilog"})

# Direction grammar per SOS-09-A §5.2. The arrows are Unicode → because
# the annotation parser stores them that way.
_DIR_SW_TO_HW: str = "sw→hw"
_DIR_HW_TO_SW: str = "hw→sw"
_DIR_BIDIRECTIONAL: str = "bidirectional"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class MmioEmitError(ValueError):
    """Raised on mmio-medium mapping failures (e.g. unrecognised mmio_kind hint)."""

    def __init__(self, message: str, *, transition: Optional[str] = None) -> None:
        self.transition = transition
        prefix = f"[{transition}] " if transition else ""
        super().__init__(f"{prefix}{message}")


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DerivedChannel:
    """One synthesised SOS-09 channel derived from an mmio transition.

    Field names mirror SOS-09-A's ``sos:`` annotation key set so the
    JSON-serialised form is consumable verbatim by
    :func:`sos09_annotations.parse_chart_annotations` after the minimal
    chart-shape wrapping is applied.
    """

    sos_id: str  # RFC 4122 canonical UUID
    sos_name: str  # SV identifier (per SOS-09-A §5.2)
    sos_kind: str  # one of {status, command, queue, shared}
    sos_dir: str  # one of {sw→hw, hw→sw, bidirectional}
    sos_width: int  # default 32 per SOS-09-A §5.2
    sos_zone: str  # default "unprivileged" per task brief
    sos_atomicity: str  # "atomic" for cmd/status; "none" for queue/shared
    sos_channel_group: str  # "<src>_to_<dst>" per SOS-09-007 two-axis
    sos_privilege_region: str  # same default as channel_group at v1
    # Provenance — names the orchestrator transition this channel came from.
    source_piece: str
    target_piece: str
    event: str
    role: str  # "cmd" / "resp" / "q" / "shared"

    def as_sos09_annotation_dict(self) -> dict[str, Any]:
        """Return the ``sos:``-prefixed dict shape SOS-09-A parses.

        The returned dict is the value that would live inside a chart
        element's ``other_attributes`` JSON map, so SOS-09-A's
        :func:`parse_chart_annotations` can consume it after the
        minimal scjson-shape wrapping (see :func:`_wrap_as_sos09_chart`).
        """
        return {
            "sos:id": self.sos_id,
            "sos:name": self.sos_name,
            "sos:kind": self.sos_kind,
            "sos:dir": self.sos_dir,
            "sos:zone": self.sos_zone,
            "sos:atomicity": self.sos_atomicity,
            "sos:width": self.sos_width,
            "sos:channel_group": self.sos_channel_group,
            "sos:privilege_region": self.sos_privilege_region,
        }


# ---------------------------------------------------------------------------
# Direction inference helpers
# ---------------------------------------------------------------------------


def _is_hw_lang(lang: str) -> bool:
    return lang.lower() in _HW_LANGS


def _infer_direction(
    src_piece: PieceAnnotation,
    dst_piece: PieceAnnotation,
    *,
    channel_role: str,
) -> str:
    """Map (src.lang, dst.lang, role) -> SOS-09-A `sos:dir`.

    Rules:
      - role="cmd"   : direction follows the event flow src->dst.
      - role="resp"  : response flows back, so reverse src->dst.
      - role="q"     : streaming; direction follows event flow.
      - role="shared": always bidirectional (the shared register surface
                       has multiple readers + writers).

    Software-piece sends to hardware-piece -> sw->hw.
    Hardware-piece sends to software-piece -> hw->sw.
    Two software pieces (mmio is misapplied here, but we still emit a
    valid channel for downstream tooling to surface the misuse):
        default to sw->hw with the source treated as "sw".
    Two hardware pieces is structurally fine for fabric-internal MMIO;
    we treat that as sw->hw too (the source side is the "active" master).
    """
    if channel_role == "shared":
        return _DIR_BIDIRECTIONAL

    # Determine event-flow direction first.
    src_hw = _is_hw_lang(src_piece.lang)
    dst_hw = _is_hw_lang(dst_piece.lang)

    if src_hw and not dst_hw:
        forward = _DIR_HW_TO_SW
    elif not src_hw and dst_hw:
        forward = _DIR_SW_TO_HW
    elif src_hw and dst_hw:
        # Both hw — fabric-to-fabric MMIO. Treat source as master.
        forward = _DIR_SW_TO_HW
    else:
        # Both sw — mmio misapplication; treat source as sw.
        forward = _DIR_SW_TO_HW

    if channel_role == "resp":
        # Response reverses the flow.
        return _DIR_HW_TO_SW if forward == _DIR_SW_TO_HW else _DIR_SW_TO_HW
    return forward


# ---------------------------------------------------------------------------
# Hint extraction + channel synthesis
# ---------------------------------------------------------------------------


def _extract_mmio_kind_hint(medium: MediumAnnotation) -> str:
    """Read the ``sos:mmio_kind`` hint from medium ``extras`` if present.

    The SOS-10 parser surfaces unknown medium attributes via
    :attr:`MediumAnnotation.extras`. The hint key (when authored as a
    medium attribute) is ``mmio_kind``; when authored as a sub-element
    it would surface differently — at v1 we only recognise the attribute
    form. Absence -> :data:`_DEFAULT_MMIO_KIND`.
    """
    hint = medium.extras.get("mmio_kind")
    if hint is None:
        return _DEFAULT_MMIO_KIND
    if not isinstance(hint, str) or hint not in _MMIO_KIND_TO_CHANNELS:
        raise MmioEmitError(
            f"unrecognised mmio_kind hint {hint!r}; "
            f"allowed values: {sorted(_MMIO_KIND_TO_CHANNELS)}"
        )
    return hint


def _derive_width(medium: MediumAnnotation) -> int:
    """Read an optional ``width`` hint from medium ``extras`` (default 32).

    Per SOS-09-A §5.2: width MUST satisfy ``1 <= width <= 64``.
    """
    raw = medium.extras.get("width")
    if raw is None:
        return 32
    try:
        w = int(raw)
    except (TypeError, ValueError) as exc:
        raise MmioEmitError(
            f"mmio width hint must be an integer; got {raw!r}"
        ) from exc
    if not (1 <= w <= 64):
        raise MmioEmitError(
            f"mmio width hint must satisfy 1 <= width <= 64; got {w}"
        )
    return w


def _derive_zone(medium: MediumAnnotation) -> str:
    """Read an optional ``zone`` hint (default "unprivileged" per task brief)."""
    raw = medium.extras.get("zone")
    if raw is None:
        return "unprivileged"
    if raw not in ("privileged", "unprivileged"):
        raise MmioEmitError(
            f"mmio zone hint must be 'privileged' or 'unprivileged'; got {raw!r}"
        )
    return raw


def _channel_name(target_piece: str, event: str, role: str) -> str:
    """Synthesise an SV identifier of shape ``<dst>__<event>_<role_suffix>``.

    `event` may contain ``.`` (dotted scope) which SV identifiers do not
    permit; we normalise to underscores. Other non-identifier characters
    are stripped to underscores too.
    """
    parts = [target_piece, _sv_normalise(event), role]
    return "__".join(parts)


def _sv_normalise(token: str) -> str:
    """Normalise an arbitrary token to an SV-identifier-safe form."""
    out_chars: list[str] = []
    for ch in token:
        if ch.isalnum() or ch == "_":
            out_chars.append(ch)
        else:
            out_chars.append("_")
    result = "".join(out_chars)
    # Leading digit -> prefix underscore.
    if result and result[0].isdigit():
        result = "_" + result
    return result or "_"


def _derive_id(
    chart_id: str,
    source: str,
    target: str,
    event: str,
    role: str,
) -> str:
    """Deterministic UUID5-derived id for (chart, src, dst, event, role)."""
    name = f"{chart_id}|{source}|{target}|{event}|{role}"
    return str(uuid.uuid5(MMIO_UUID_NAMESPACE, name))


def _channel_group(source: str, target: str) -> str:
    """Per SOS-09-007 two-axis ratification: ``<src>_to_<dst>``."""
    return f"{_sv_normalise(source)}_to_{_sv_normalise(target)}"


def _atomicity_for_role(role: str) -> str:
    """`cmd`/`resp` -> "atomic"; `q`/`shared` -> "none" per task brief.

    Note: SOS-09-A's resolver normalises ``none`` -> kind-inferred default
    (``atomic`` for queue, ``mutex-required`` for shared). The string we
    emit here is the input token; SOS-09-A's resolver does the final mapping.
    The two valid input tokens are ``atomic`` and ``mutex-required``;
    SOS-09-A also accepts ``implicit`` / ``explicit``. We emit ``atomic``
    for cmd/status (since they are word-sized register writes), and
    ``mutex-required`` for shared (multi-writer surface). Queue at v1
    defaults to ``atomic`` since each push/pop is a single MMIO word.
    """
    if role == "shared":
        return "mutex-required"
    return "atomic"


# ---------------------------------------------------------------------------
# Top-level planner
# ---------------------------------------------------------------------------


def _index_pieces(orchestrator: OrchestratorAnnotations) -> dict[str, PieceAnnotation]:
    return {p.state_id: p for p in orchestrator.pieces}


def plan_mmio(
    orchestrator: OrchestratorAnnotations,
    *,
    chart_id: str = "chart",
) -> list[DerivedChannel]:
    """Walk the orchestrator and synthesise SOS-09 channel annotations.

    Filters for ``kind="mmio"`` cross-piece transitions; emits one or two
    :class:`DerivedChannel` per transition per the kind-mapping table.
    Output is ordered by document-order traversal of the orchestrator's
    transitions list (which is itself document-order per
    :func:`sos10_annotations.parse_orchestrator_annotations`).
    """
    pieces_by_id = _index_pieces(orchestrator)
    out: list[DerivedChannel] = []
    for tr in orchestrator.transitions:
        if tr.medium.kind != "mmio":
            continue
        try:
            src_piece = pieces_by_id[tr.source_state_id]
            dst_piece = pieces_by_id[tr.target_state_id]
        except KeyError as exc:
            # The SOS-10 parser already validates piece-id resolution; a
            # missing piece here would be an upstream bug. Surface it.
            raise MmioEmitError(
                f"transition references unknown piece {exc!s}",
                transition=f"{tr.source_state_id}->{tr.target_state_id}:{tr.event}",
            ) from exc

        hint = _extract_mmio_kind_hint(tr.medium)
        width = _derive_width(tr.medium)
        zone = _derive_zone(tr.medium)
        group = _channel_group(tr.source_state_id, tr.target_state_id)

        for (role, kind) in _MMIO_KIND_TO_CHANNELS[hint]:
            sos_id = _derive_id(
                chart_id, tr.source_state_id, tr.target_state_id, tr.event, role,
            )
            name = _channel_name(tr.target_state_id, tr.event, role)
            direction = _infer_direction(src_piece, dst_piece, channel_role=role)
            out.append(
                DerivedChannel(
                    sos_id=sos_id,
                    sos_name=name,
                    sos_kind=kind,
                    sos_dir=direction,
                    sos_width=width,
                    sos_zone=zone,
                    sos_atomicity=_atomicity_for_role(role),
                    sos_channel_group=group,
                    sos_privilege_region=group,
                    source_piece=tr.source_state_id,
                    target_piece=tr.target_state_id,
                    event=tr.event,
                    role=role,
                )
            )
    return out


# ---------------------------------------------------------------------------
# Emission
# ---------------------------------------------------------------------------


_ADAPTER_TEMPLATE_HEADER: str = '''"""Generated SOS-09 adapter for chart {chart_id_repr}.

DO NOT EDIT — regenerated by `mmio_emit.py` per SOS-10 §6.3. This script
loads the sibling ``derived_sos09_channels.json`` manifest, wraps each
synthesised channel in the minimal scjson chart shape SOS-09-A's parser
expects, and invokes the SOS-09 emitter family (C HAL, Rust HAL, regfile,
SVD, MPU, vectors) programmatically.

The actual six-artifact emission lives downstream; this script is the
concrete handoff documented at SOS-10 §6.3 ("the SOS-09 emitter takes
over from there").
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

CHART_ID = {chart_id_repr}

_HERE = Path(__file__).resolve().parent
_TOOLS_DIR = _HERE.parents[3]  # build/mmio/<chart>/ -> repo root
if str(_TOOLS_DIR / "tools" / "sos-codegen") not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR / "tools" / "sos-codegen"))
'''

_ADAPTER_TEMPLATE_BODY: str = '''
from sos09_annotations import parse_chart_annotations  # noqa: E402


def load_channels() -> list[dict]:
    with (_HERE / "derived_sos09_channels.json").open() as f:
        manifest = json.load(f)
    return manifest["channels"]


def build_sos09_chart_ast(channels: list[dict]) -> dict:
    """Wrap channel-annotation dicts in a minimal scjson chart shape.

    Each channel becomes the ``other_attributes`` payload of one
    synthetic ``<state>`` element. The result is exactly the input
    contract :func:`parse_chart_annotations` reads.
    """
    states: list[dict] = []
    for ch in channels:
        states.append(
            {
                "id": ch["sos:name"],
                "other_attributes": {"other_attributes": json.dumps(ch)},
            }
        )
    return {"state": states, "version": 1.0, "datamodel_attribute": "ecmascript"}


def main(argv: list[str] | None = None) -> int:
    channels = load_channels()
    chart_ast = build_sos09_chart_ast(channels)
    annotations = parse_chart_annotations(chart_ast)
    print(
        f"feed_sos09: loaded {len(annotations.channels)} channel(s) "
        f"from chart={CHART_ID!r}"
    )
    # Downstream emitter invocations are intentionally NOT performed here.
    # Per SOS-10 §6.3, this adapter is the handoff point; the caller is
    # responsible for routing `annotations` into c_hal_emit, transliterate_rust,
    # transliterate_regfile, transliterate_svd, transliterate_mpu, and
    # vectors_emit as appropriate.
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
'''


def emit_mmio(
    orchestrator: OrchestratorAnnotations,
    *,
    chart_id: str,
    out_dir: Path,
) -> dict[str, Any]:
    """Plan + write the manifest + adapter script.

    Returns a dict ``{"channels": [...], "manifest_path": Path,
    "adapter_path": Path}`` for caller introspection. Writes:

      - ``<out_dir>/build/mmio/<chart_id>/derived_sos09_channels.json``
      - ``<out_dir>/build/mmio/<chart_id>/feed_sos09.py``

    Determinism: the manifest JSON is sorted-key-encoded with newline
    termination, and the channel order follows the orchestrator's
    transition document order, so two runs against the same input
    produce byte-identical output.
    """
    plans = plan_mmio(orchestrator, chart_id=chart_id)

    target_dir = out_dir / "build" / "mmio" / chart_id
    target_dir.mkdir(parents=True, exist_ok=True)

    channels = [c.as_sos09_annotation_dict() for c in plans]
    provenance = [
        {
            "sos:id": c.sos_id,
            "sos:name": c.sos_name,
            "source_piece": c.source_piece,
            "target_piece": c.target_piece,
            "event": c.event,
            "role": c.role,
        }
        for c in plans
    ]
    manifest = {
        "chart_id": chart_id,
        "channels": channels,
        "provenance": provenance,
    }
    manifest_path = target_dir / "derived_sos09_channels.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    adapter_path = target_dir / "feed_sos09.py"
    adapter_src = (
        _ADAPTER_TEMPLATE_HEADER.format(chart_id_repr=repr(chart_id))
        + _ADAPTER_TEMPLATE_BODY
    )
    adapter_path.write_text(adapter_src, encoding="utf-8")

    return {
        "channels": channels,
        "manifest_path": manifest_path,
        "adapter_path": adapter_path,
        "plans": plans,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Synthesise SOS-09 channel annotations from an orchestrator "
            "chart's mmio-medium cross-piece transitions per SOS-10 §6.3."
        ),
    )
    parser.add_argument("chart", type=Path, help="path to orchestrator .scxml")
    parser.add_argument(
        "--chart-id",
        default=None,
        help="chart id (defaults to the .scxml stem)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path.cwd(),
        help="repo root (the build/mmio/<chart_id>/ tree is created under here)",
    )
    args = parser.parse_args(argv)

    # Local import — keeps `loader` (and scjson) out of the import path when
    # this module is consumed as a library.
    from loader import load_chart
    from sos10_annotations import parse_orchestrator_annotations

    chart_id = args.chart_id or args.chart.stem
    ast = load_chart(args.chart).raw_scjson
    orchestrator = parse_orchestrator_annotations(ast or {})
    result = emit_mmio(orchestrator, chart_id=chart_id, out_dir=args.out_dir)
    print(f"emitted {len(result['channels'])} channel(s) to {result['manifest_path']}")
    return 0


__all__ = [
    "DerivedChannel",
    "MmioEmitError",
    "MMIO_UUID_NAMESPACE",
    "plan_mmio",
    "emit_mmio",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
