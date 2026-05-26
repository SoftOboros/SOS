"""Tests for ``mmio_emit.py`` — SOS-10 §6.3 mmio-medium emitter.

Authority: ``docs/concepts/SOS-10-CONCEPTS.md`` §6.3 (ratified 2026-05-23):
the ``mmio`` medium composes SOS-09 membrane primitives. The emitter
takes the orchestrator's chart-side annotations and synthesises SOS-09
:class:`ChannelAnnotation`-shaped JSON entries; the actual six-artifact
emission (C HAL, Rust HAL, regfile, SVD, MPU, vectors) remains downstream.

This test module covers:

- Happy path (2-piece rust->vhdl chart, one mmio transition).
- Request-response hint produces a command + status pair.
- Channel-group derivation (``<src>_to_<dst>`` per SOS-09-007).
- Determinism (two emit runs produce byte-identical manifest JSON).
- Sanity pipe-back: the synthesised JSON, wrapped in the minimal SOS-09
  chart shape, parses cleanly through
  :func:`sos09_annotations.parse_chart_annotations`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Make `sos-codegen` modules importable when pytest is invoked from any cwd.
_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from loader import load_chart  # noqa: E402
from mmio_emit import (  # noqa: E402
    DerivedChannel,
    MmioEmitError,
    emit_mmio,
    plan_mmio,
)
from sos09_annotations import (  # noqa: E402
    Sos09AnnotationError,
    parse_chart_annotations,
)
from sos10_annotations import (  # noqa: E402
    CrossPieceTransitionAnnotation,
    MediumAnnotation,
    OrchestratorAnnotations,
    PieceAnnotation,
    parse_orchestrator_annotations,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SOS_NS = "https://softoboros.com/sos/1.0"
MEDIUM_QN = f"{{{SOS_NS}}}medium"


def _wrap_other_attrs(payload: dict) -> dict:
    return {"other_attributes": json.dumps(payload)}


def _medium(kind: str, *, extras: dict | None = None) -> dict:
    attrs: dict = {"kind": kind}
    if extras:
        attrs.update(extras)
    return {"qname": MEDIUM_QN, "text": "", "attributes": attrs}


def _transition(event: str, target: str, *, medium: dict | None = None) -> dict:
    tr: dict = {"event": event, "target": [target]}
    if medium is not None:
        tr["other_element"] = [medium]
    return tr


def _piece(state_id: str, *, lang: str, transitions: list[dict] | None = None) -> dict:
    node: dict = {
        "id": state_id,
        "other_attributes": _wrap_other_attrs({"sos:lang": lang}),
    }
    if transitions is not None:
        node["transition"] = transitions
    return node


def _chart(pieces: list[dict]) -> dict:
    return {
        "state": pieces,
        "version": 1.0,
        "datamodel_attribute": "ecmascript",
        "initial": [pieces[0]["id"]] if pieces else [],
    }


def _build_orchestrator(chart: dict) -> OrchestratorAnnotations:
    return parse_orchestrator_annotations(chart)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_happy_path_single_mmio_transition():
    """A 2-piece chart with one rust->vhdl mmio transition emits exactly
    one ``command`` channel with the expected name + direction."""
    chart = _chart(
        [
            _piece(
                "mcu",
                lang="rust",
                transitions=[
                    _transition("start_capture", "fabric", medium=_medium("mmio")),
                ],
            ),
            _piece("fabric", lang="vhdl"),
        ]
    )
    orch = _build_orchestrator(chart)
    plans = plan_mmio(orch, chart_id="test_chart")

    assert len(plans) == 1
    p = plans[0]
    assert isinstance(p, DerivedChannel)
    assert p.sos_kind == "command"
    assert p.sos_dir == "sw→hw"  # rust -> vhdl
    assert p.source_piece == "mcu"
    assert p.target_piece == "fabric"
    assert p.event == "start_capture"
    assert p.role == "cmd"
    # Name shape: <dst>__<event>_<role>
    assert p.sos_name == "fabric__start_capture__cmd"
    # Channel group: <src>_to_<dst>.
    assert p.sos_channel_group == "mcu_to_fabric"
    assert p.sos_privilege_region == "mcu_to_fabric"
    assert p.sos_atomicity == "atomic"
    assert p.sos_zone == "unprivileged"
    assert p.sos_width == 32


def test_non_mmio_transitions_filtered():
    """Transitions on other media (in-process, shared-memory, network)
    are silently skipped — only mmio yields channels."""
    chart = _chart(
        [
            _piece(
                "alpha",
                lang="rust",
                transitions=[
                    _transition("evt1", "beta", medium=_medium("in-process")),
                ],
            ),
            _piece(
                "beta",
                lang="c",
                transitions=[
                    _transition("evt2", "alpha", medium=_medium("shared-memory")),
                ],
            ),
        ]
    )
    orch = _build_orchestrator(chart)
    plans = plan_mmio(orch, chart_id="x")
    assert plans == []


# ---------------------------------------------------------------------------
# Request-response hint
# ---------------------------------------------------------------------------


def test_request_response_hint_yields_command_plus_status():
    """``mmio_kind="request_response"`` extras hint -> one ``command`` +
    one ``status`` channel. The status channel reverses the direction."""
    chart = _chart(
        [
            _piece(
                "mcu",
                lang="rust",
                transitions=[
                    _transition(
                        "rpc.read_status",
                        "fabric",
                        medium=_medium("mmio", extras={"mmio_kind": "request_response"}),
                    ),
                ],
            ),
            _piece("fabric", lang="vhdl"),
        ]
    )
    orch = _build_orchestrator(chart)
    plans = plan_mmio(orch, chart_id="rpc_chart")

    assert len(plans) == 2
    by_role = {p.role: p for p in plans}
    assert set(by_role) == {"cmd", "resp"}

    cmd = by_role["cmd"]
    assert cmd.sos_kind == "command"
    assert cmd.sos_dir == "sw→hw"
    assert cmd.sos_atomicity == "atomic"

    resp = by_role["resp"]
    assert resp.sos_kind == "status"
    assert resp.sos_dir == "hw→sw"  # reverses sw→hw
    assert resp.sos_atomicity == "atomic"

    # IDs must differ — same chart/event/transition, different roles.
    assert cmd.sos_id != resp.sos_id

    # Both share the same channel_group.
    assert cmd.sos_channel_group == resp.sos_channel_group == "mcu_to_fabric"


def test_streaming_hint_yields_queue():
    """``mmio_kind="streaming"`` -> one ``queue`` channel."""
    chart = _chart(
        [
            _piece(
                "mcu",
                lang="rust",
                transitions=[
                    _transition(
                        "audio.frame",
                        "fabric",
                        medium=_medium("mmio", extras={"mmio_kind": "streaming"}),
                    ),
                ],
            ),
            _piece("fabric", lang="vhdl"),
        ]
    )
    orch = _build_orchestrator(chart)
    plans = plan_mmio(orch, chart_id="x")
    assert len(plans) == 1
    assert plans[0].sos_kind == "queue"
    # queue at sw->hw direction is permitted per SOS-09-A §5.2 matrix.
    assert plans[0].sos_dir == "sw→hw"


def test_shared_surface_hint_yields_shared_bidirectional():
    """``mmio_kind="shared_surface"`` -> ``shared`` channel, dir=bidirectional."""
    chart = _chart(
        [
            _piece(
                "mcu",
                lang="rust",
                transitions=[
                    _transition(
                        "regs.touch",
                        "fabric",
                        medium=_medium("mmio", extras={"mmio_kind": "shared_surface"}),
                    ),
                ],
            ),
            _piece("fabric", lang="vhdl"),
        ]
    )
    orch = _build_orchestrator(chart)
    plans = plan_mmio(orch, chart_id="x")
    assert len(plans) == 1
    assert plans[0].sos_kind == "shared"
    assert plans[0].sos_dir == "bidirectional"
    assert plans[0].sos_atomicity == "mutex-required"


def test_unknown_mmio_kind_hint_raises():
    """An mmio_kind value outside the recognised set is a hard error."""
    chart = _chart(
        [
            _piece(
                "mcu",
                lang="rust",
                transitions=[
                    _transition(
                        "evt",
                        "fabric",
                        medium=_medium("mmio", extras={"mmio_kind": "bogus"}),
                    ),
                ],
            ),
            _piece("fabric", lang="vhdl"),
        ]
    )
    orch = _build_orchestrator(chart)
    with pytest.raises(MmioEmitError) as exc_info:
        plan_mmio(orch, chart_id="x")
    assert "bogus" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Channel-group derivation (SOS-09-007 two-axis ratification)
# ---------------------------------------------------------------------------


def test_channel_group_derivation_two_axis():
    """Per SOS-09-007 two-axis amendment 2026-05-26: channel_group =
    ``<src>_to_<dst>``."""
    chart = _chart(
        [
            _piece(
                "mcu",
                lang="rust",
                transitions=[
                    _transition("evt", "fabric", medium=_medium("mmio")),
                ],
            ),
            _piece("fabric", lang="vhdl"),
        ]
    )
    orch = _build_orchestrator(chart)
    plans = plan_mmio(orch, chart_id="x")
    assert plans[0].sos_channel_group == "mcu_to_fabric"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_emit_is_byte_deterministic(tmp_path):
    """Two emit calls against the same orchestrator produce byte-identical
    manifest JSON. Determinism is load-bearing for content-addressable
    build outputs."""
    chart = _chart(
        [
            _piece(
                "mcu",
                lang="rust",
                transitions=[
                    _transition("start_capture", "fabric", medium=_medium("mmio")),
                    _transition(
                        "rpc.read",
                        "fabric",
                        medium=_medium("mmio", extras={"mmio_kind": "request_response"}),
                    ),
                ],
            ),
            _piece(
                "fabric",
                lang="vhdl",
                transitions=[
                    _transition(
                        "audio.frame",
                        "mcu",
                        medium=_medium("mmio", extras={"mmio_kind": "streaming"}),
                    ),
                ],
            ),
        ]
    )
    orch = _build_orchestrator(chart)

    out_a = tmp_path / "run_a"
    out_b = tmp_path / "run_b"
    res_a = emit_mmio(orch, chart_id="det_chart", out_dir=out_a)
    res_b = emit_mmio(orch, chart_id="det_chart", out_dir=out_b)

    blob_a = res_a["manifest_path"].read_bytes()
    blob_b = res_b["manifest_path"].read_bytes()
    assert blob_a == blob_b

    # And the adapter script is also byte-identical.
    adp_a = res_a["adapter_path"].read_bytes()
    adp_b = res_b["adapter_path"].read_bytes()
    assert adp_a == adp_b


def test_emit_writes_expected_layout(tmp_path):
    """Emitter writes ``build/mmio/<chart_id>/`` with the manifest +
    adapter."""
    chart = _chart(
        [
            _piece(
                "mcu",
                lang="rust",
                transitions=[
                    _transition("evt", "fabric", medium=_medium("mmio")),
                ],
            ),
            _piece("fabric", lang="vhdl"),
        ]
    )
    orch = _build_orchestrator(chart)
    res = emit_mmio(orch, chart_id="layout_chart", out_dir=tmp_path)
    target_dir = tmp_path / "build" / "mmio" / "layout_chart"
    assert (target_dir / "derived_sos09_channels.json").is_file()
    assert (target_dir / "feed_sos09.py").is_file()
    assert res["manifest_path"] == target_dir / "derived_sos09_channels.json"
    assert res["adapter_path"] == target_dir / "feed_sos09.py"

    manifest = json.loads(res["manifest_path"].read_text())
    assert manifest["chart_id"] == "layout_chart"
    assert len(manifest["channels"]) == 1
    # Provenance recorded.
    assert manifest["provenance"][0]["source_piece"] == "mcu"
    assert manifest["provenance"][0]["target_piece"] == "fabric"
    assert manifest["provenance"][0]["event"] == "evt"
    assert manifest["provenance"][0]["role"] == "cmd"

    # Adapter script is syntactically valid Python (compile-only check —
    # the script imports sos09_annotations at runtime, which we don't
    # need to exercise here).
    adapter_src = res["adapter_path"].read_text()
    compile(adapter_src, str(res["adapter_path"]), "exec")


# ---------------------------------------------------------------------------
# Sanity pipe-back: synthesised JSON parses cleanly through SOS-09-A.
# ---------------------------------------------------------------------------


def _wrap_as_sos09_chart_ast(channels: list[dict]) -> dict:
    """Wrap channel-annotation dicts in the minimal scjson chart shape
    SOS-09-A consumes. Mirrors :func:`feed_sos09.build_sos09_chart_ast`
    in the adapter script (intentionally — we exercise the same shape)."""
    states: list[dict] = []
    for ch in channels:
        states.append(
            {
                "id": ch["sos:name"],
                "other_attributes": {"other_attributes": json.dumps(ch)},
            }
        )
    return {"state": states, "version": 1.0, "datamodel_attribute": "ecmascript"}


def test_sanity_pipe_back_through_sos09_parser():
    """The synthesised channel-annotation dicts must round-trip cleanly
    through :func:`sos09_annotations.parse_chart_annotations` — no
    :class:`Sos09AnnotationError` raised, every channel surfaces with
    matching ``sos:id`` / ``sos:name`` / ``sos:kind`` / ``sos:dir``."""
    chart = _chart(
        [
            _piece(
                "mcu",
                lang="rust",
                transitions=[
                    _transition("start_capture", "fabric", medium=_medium("mmio")),
                    _transition(
                        "rpc.read_status",
                        "fabric",
                        medium=_medium("mmio", extras={"mmio_kind": "request_response"}),
                    ),
                ],
            ),
            _piece(
                "fabric",
                lang="vhdl",
                transitions=[
                    _transition(
                        "telemetry.tick",
                        "mcu",
                        medium=_medium("mmio", extras={"mmio_kind": "streaming"}),
                    ),
                    _transition(
                        "shared.regs",
                        "mcu",
                        medium=_medium("mmio", extras={"mmio_kind": "shared_surface"}),
                    ),
                ],
            ),
        ]
    )
    orch = _build_orchestrator(chart)
    plans = plan_mmio(orch, chart_id="pipe_back_chart")
    channels = [p.as_sos09_annotation_dict() for p in plans]

    chart_ast = _wrap_as_sos09_chart_ast(channels)
    try:
        sos09 = parse_chart_annotations(chart_ast)
    except Sos09AnnotationError as exc:
        pytest.fail(f"synthesised SOS-09 annotations failed pipe-back parse: {exc}")

    # The SOS-09-A parser surfaces one ChannelAnnotation per emitted dict.
    assert len(sos09.channels) == len(channels)
    by_name = {c.name: c for c in sos09.channels}
    for derived in plans:
        ch = by_name[derived.sos_name]
        assert ch.id == derived.sos_id
        assert ch.kind == derived.sos_kind
        assert ch.dir == derived.sos_dir
        assert ch.channel_group == derived.sos_channel_group
        assert ch.privilege_region == derived.sos_privilege_region


# ---------------------------------------------------------------------------
# Fixture-driven smoke
# ---------------------------------------------------------------------------


_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "sos_10_mmio"
    / "orchestrator_mcu_fabric_mmio.scxml"
)


def test_fixture_smoke(tmp_path):
    """End-to-end: load the 2-piece fixture via scjson, parse via SOS-10,
    emit via mmio_emit, verify manifest contents."""
    ast = load_chart(_FIXTURE).raw_scjson
    orch = parse_orchestrator_annotations(ast)
    # The fixture has two mmio transitions (one each direction).
    assert len([t for t in orch.transitions if t.medium.kind == "mmio"]) == 2
    res = emit_mmio(orch, chart_id="fixture_chart", out_dir=tmp_path)
    assert len(res["channels"]) == 2
    # Direction inference: mcu(rust)->fabric(vhdl) is sw→hw; reverse is hw→sw.
    by_event = {p.event: p for p in res["plans"]}
    assert by_event["start_capture"].sos_dir == "sw→hw"
    assert by_event["audio.frame"].sos_dir == "hw→sw"
