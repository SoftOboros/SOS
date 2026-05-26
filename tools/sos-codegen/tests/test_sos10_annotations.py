"""Tests for `sos10_annotations.py` — SOS-10 orchestrator chart parser.

Authority: `docs/concepts/SOS-10-CONCEPTS.md` (🟢 ratified 2026-05-23; all 8
PCDNs resolved). Covers §5.1 orchestrator-chart shape, §5.2 medium
enumeration, §6 per-medium contracts (chart-side surface only — wire
format derivation remains the emitter's responsibility per INV-S-ORCH-4).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make `sos-codegen` modules importable when pytest is invoked from any cwd.
_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from loader import load_chart  # noqa: E402
from sos10_annotations import (  # noqa: E402
    ALLOWED_MEDIUM_KINDS,
    ALLOWED_TRANSPORT_NAMES,
    DEFAULT_PIECE_LANG,
    CrossPieceTransitionAnnotation,
    MediumAnnotation,
    OrchestratorAnnotations,
    PieceAnnotation,
    Sos10AnnotationError,
    TransportAnnotation,
    parse_orchestrator_annotations,
)


# ---------------------------------------------------------------------------
# scjson-shape builders for in-test chart dicts. Mirrors the SOS-09 test
# helpers but builds the sub-element shape SOS-10 uses (`other_element`
# lists with James-Clark qnames + attributes + optional children).
# ---------------------------------------------------------------------------

import json

SOS_NS = "https://softoboros.com/sos/1.0"
MEDIUM_QN = f"{{{SOS_NS}}}medium"
TRANSPORT_QN = f"{{{SOS_NS}}}transport"
TIMEOUT_QN = f"{{{SOS_NS}}}timeout"
IDEMPOTENT_QN = f"{{{SOS_NS}}}idempotent"


def _wrap_other_attrs(payload: dict) -> dict:
    """scjson-0.3.6 shape: outer dict with inner JSON-string under same key."""
    return {"other_attributes": json.dumps(payload)}


def _medium_element(
    kind: str,
    *,
    transport: str | None = None,
    transport_timeout_ms: int | None = None,
    timeout_ms: int | None = None,
    idempotent: bool | None = None,
) -> dict:
    children: list[dict] = []
    if transport is not None:
        t_attrs: dict = {"name": transport}
        if transport_timeout_ms is not None:
            t_attrs["timeout-ms"] = str(transport_timeout_ms)
        children.append({"qname": TRANSPORT_QN, "text": "", "attributes": t_attrs})
    if timeout_ms is not None:
        children.append(
            {"qname": TIMEOUT_QN, "text": "", "attributes": {"ms": str(timeout_ms)}}
        )
    if idempotent is not None:
        children.append(
            {
                "qname": IDEMPOTENT_QN,
                "text": "",
                "attributes": {"value": "true" if idempotent else "false"},
            }
        )
    node: dict = {"qname": MEDIUM_QN, "text": "", "attributes": {"kind": kind}}
    if children:
        node["children"] = children
    return node


def _transition(
    event: str,
    target: str,
    *,
    medium: dict | None = None,
    sos_attrs: dict | None = None,
) -> dict:
    tr: dict = {"event": event, "target": [target]}
    if medium is not None:
        tr["other_element"] = [medium]
    if sos_attrs is not None:
        tr["other_attributes"] = _wrap_other_attrs(sos_attrs)
    return tr


def _piece(
    state_id: str,
    *,
    lang: str | None = None,
    transitions: list[dict] | None = None,
    extras: dict | None = None,
) -> dict:
    sos_attrs: dict = {}
    if lang is not None:
        sos_attrs["sos:lang"] = lang
    if extras is not None:
        sos_attrs.update(extras)
    node: dict = {"id": state_id}
    if sos_attrs:
        node["other_attributes"] = _wrap_other_attrs(sos_attrs)
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


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


def test_happy_path_three_pieces_three_media():
    """3-piece chart with one transition per medium kind (in-process,
    shared-memory, network/gRPC). Verifies pieces, lang inheritance,
    transitions, and medium-kind / transport coverage."""
    chart = _chart(
        [
            _piece(
                "alpha",
                lang="rust",
                transitions=[
                    _transition(
                        "evt.alpha_to_beta",
                        "beta",
                        medium=_medium_element("in-process"),
                    )
                ],
            ),
            _piece(
                "beta",
                lang="c",
                transitions=[
                    _transition(
                        "evt.beta_to_gamma",
                        "gamma",
                        medium=_medium_element("shared-memory", timeout_ms=2000),
                    )
                ],
            ),
            _piece(
                "gamma",
                lang="python",
                transitions=[
                    _transition(
                        "evt.gamma_to_alpha",
                        "alpha",
                        medium=_medium_element(
                            "network",
                            transport="gRPC",
                            timeout_ms=5000,
                            idempotent=True,
                        ),
                    )
                ],
            ),
        ]
    )

    out = parse_orchestrator_annotations(chart)

    assert isinstance(out, OrchestratorAnnotations)
    assert [p.state_id for p in out.pieces] == ["alpha", "beta", "gamma"]
    assert [p.lang for p in out.pieces] == ["rust", "c", "python"]

    assert len(out.transitions) == 3

    t0, t1, t2 = out.transitions
    assert (t0.source_state_id, t0.target_state_id, t0.event) == (
        "alpha", "beta", "evt.alpha_to_beta",
    )
    assert t0.medium.kind == "in-process"
    assert t0.medium.transport is None
    assert t0.medium.timeout is None

    assert (t1.source_state_id, t1.target_state_id, t1.event) == (
        "beta", "gamma", "evt.beta_to_gamma",
    )
    assert t1.medium.kind == "shared-memory"
    assert t1.medium.timeout == 2000

    assert (t2.source_state_id, t2.target_state_id, t2.event) == (
        "gamma", "alpha", "evt.gamma_to_alpha",
    )
    assert t2.medium.kind == "network"
    assert isinstance(t2.medium.transport, TransportAnnotation)
    assert t2.medium.transport.name == "gRPC"
    assert t2.medium.timeout == 5000
    assert t2.medium.idempotent is True


def test_frozen_enum_exports_match_spec():
    """The exported frozen-enum sets MUST mirror §5.2 and PCDN-SOS-10-002."""
    assert ALLOWED_MEDIUM_KINDS == frozenset(
        {"in-process", "shared-memory", "mmio", "network"}
    )
    assert ALLOWED_TRANSPORT_NAMES == frozenset({"gRPC", "AMQP"})
    assert DEFAULT_PIECE_LANG == "rust"


# ---------------------------------------------------------------------------
# Frozen-enum validation
# ---------------------------------------------------------------------------


def test_invalid_medium_kind_raises():
    """`kind="invalid"` is outside §5.2 frozen 4-value enum → error."""
    chart = _chart(
        [
            _piece(
                "alpha",
                lang="rust",
                transitions=[
                    _transition(
                        "evt", "beta", medium=_medium_element("ipc")  # not in enum
                    )
                ],
            ),
            _piece("beta", lang="c"),
        ]
    )
    with pytest.raises(Sos10AnnotationError) as exc_info:
        parse_orchestrator_annotations(chart)
    assert "5.2" in (exc_info.value.rule or "")
    assert "ipc" in str(exc_info.value)


def test_invalid_transport_name_raises():
    """Transport names outside {gRPC, AMQP} → error citing PCDN-SOS-10-002."""
    chart = _chart(
        [
            _piece(
                "alpha",
                lang="rust",
                transitions=[
                    _transition(
                        "evt",
                        "beta",
                        medium=_medium_element("network", transport="REST"),
                    )
                ],
            ),
            _piece("beta", lang="c"),
        ]
    )
    with pytest.raises(Sos10AnnotationError) as exc_info:
        parse_orchestrator_annotations(chart)
    assert "PCDN-SOS-10-002" in (exc_info.value.rule or "")


# ---------------------------------------------------------------------------
# Cross-validation: kind="network" requires transport; others forbid it.
# ---------------------------------------------------------------------------


def test_network_without_transport_raises():
    """`kind="network"` without `<sos:transport>` → error citing §6.4."""
    chart = _chart(
        [
            _piece(
                "alpha",
                lang="rust",
                transitions=[
                    _transition(
                        "evt", "beta", medium=_medium_element("network")
                    )
                ],
            ),
            _piece("beta", lang="c"),
        ]
    )
    with pytest.raises(Sos10AnnotationError) as exc_info:
        parse_orchestrator_annotations(chart)
    assert "transport" in str(exc_info.value).lower()
    assert "6.4" in (exc_info.value.rule or "")


def test_inprocess_with_transport_raises():
    """`kind="in-process"` carrying a transport is malformed → error."""
    chart = _chart(
        [
            _piece(
                "alpha",
                lang="rust",
                transitions=[
                    _transition(
                        "evt",
                        "beta",
                        medium=_medium_element("in-process", transport="gRPC"),
                    )
                ],
            ),
            _piece("beta", lang="c"),
        ]
    )
    with pytest.raises(Sos10AnnotationError) as exc_info:
        parse_orchestrator_annotations(chart)
    assert "MUST NOT" in str(exc_info.value)


def test_shared_memory_with_transport_raises():
    """`kind="shared-memory"` with a transport is also rejected."""
    chart = _chart(
        [
            _piece(
                "alpha",
                lang="rust",
                transitions=[
                    _transition(
                        "evt",
                        "beta",
                        medium=_medium_element(
                            "shared-memory", transport="AMQP"
                        ),
                    )
                ],
            ),
            _piece("beta", lang="c"),
        ]
    )
    with pytest.raises(Sos10AnnotationError):
        parse_orchestrator_annotations(chart)


# ---------------------------------------------------------------------------
# Defaulting + override semantics.
# ---------------------------------------------------------------------------


def test_missing_sos_lang_defaults_to_rust():
    """Per PCDN-SOS-10-001 / -003: omitting `sos:lang` defaults to `"rust"`."""
    chart = _chart(
        [
            _piece("alpha"),  # no sos:lang
            _piece("beta", lang="c"),
        ]
    )
    out = parse_orchestrator_annotations(chart)
    by_id = {p.state_id: p for p in out.pieces}
    assert by_id["alpha"].lang == "rust"
    assert by_id["beta"].lang == "c"


def test_transition_idempotent_attribute_overrides_medium_level():
    """Per-transition `sos:idempotent` attribute is recorded as the override
    on the transition annotation; the medium-level `<sos:idempotent>` value
    is preserved on the medium annotation so consumers can resolve which
    wins."""
    chart = _chart(
        [
            _piece(
                "alpha",
                lang="rust",
                transitions=[
                    _transition(
                        "evt",
                        "beta",
                        medium=_medium_element(
                            "network", transport="gRPC", idempotent=False
                        ),
                        sos_attrs={"sos:idempotent": "true"},
                    )
                ],
            ),
            _piece("beta", lang="c"),
        ]
    )
    out = parse_orchestrator_annotations(chart)
    assert len(out.transitions) == 1
    tr = out.transitions[0]
    # Medium-level value preserved.
    assert tr.medium.idempotent is False
    # Transition-level override recorded.
    assert tr.idempotent is True


def test_invalid_sos_lang_value_raises():
    """`sos:lang` MUST be an SV identifier (PCDN-SOS-10-003 is namespaced)."""
    chart = _chart(
        [
            _piece("alpha", lang="not a valid identifier!"),
            _piece("beta", lang="c"),
        ]
    )
    with pytest.raises(Sos10AnnotationError):
        parse_orchestrator_annotations(chart)


# ---------------------------------------------------------------------------
# Cross-piece transition target validation.
# ---------------------------------------------------------------------------


def test_cross_piece_transition_target_must_be_known_piece():
    """A `<sos:medium>` transition whose target is not a top-level piece is
    a chart-author error per §5.1."""
    chart = _chart(
        [
            _piece(
                "alpha",
                lang="rust",
                transitions=[
                    _transition(
                        "evt",
                        "unknown_piece",
                        medium=_medium_element("in-process"),
                    )
                ],
            ),
            _piece("beta", lang="c"),
        ]
    )
    with pytest.raises(Sos10AnnotationError) as exc_info:
        parse_orchestrator_annotations(chart)
    assert "unknown_piece" in str(exc_info.value)


def test_intra_piece_transition_without_medium_is_ignored():
    """A transition with no `<sos:medium>` annotation is not surfaced as a
    cross-piece transition (intra-piece transitions don't need declaration)."""
    chart = _chart(
        [
            _piece(
                "alpha",
                lang="rust",
                transitions=[
                    _transition("intra_evt", "beta", medium=None),
                ],
            ),
            _piece("beta", lang="c"),
        ]
    )
    out = parse_orchestrator_annotations(chart)
    assert out.transitions == []


# ---------------------------------------------------------------------------
# Fixture-driven integration: drive scjson end-to-end on the 3-piece chart.
# ---------------------------------------------------------------------------


_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "sos_10"
    / "orchestrator_3piece.scxml"
)


def test_fixture_three_piece_orchestrator_roundtrip():
    """End-to-end: scjson the §9-mirror fixture, parse, verify pieces +
    transitions match the expected medium layout."""
    ast = load_chart(_FIXTURE).raw_scjson
    out = parse_orchestrator_annotations(ast)

    by_id = {p.state_id: p for p in out.pieces}
    assert set(by_id) == {"mcu", "fabric", "gateway"}
    assert by_id["mcu"].lang == "rust"
    assert by_id["fabric"].lang == "vhdl"
    # `gateway` omits sos:lang; defaults to "rust" per PCDN-SOS-10-001 / -003.
    assert by_id["gateway"].lang == DEFAULT_PIECE_LANG

    assert len(out.transitions) == 3
    by_src = {t.source_state_id: t for t in out.transitions}

    # mcu -> fabric : mmio
    assert by_src["mcu"].target_state_id == "fabric"
    assert by_src["mcu"].event == "audio.start"
    assert by_src["mcu"].medium.kind == "mmio"
    assert by_src["mcu"].medium.transport is None
    # transition-level sos:idempotent="false" recorded as override.
    assert by_src["mcu"].idempotent is False

    # fabric -> gateway : shared-memory, with sos:timeout=2000.
    assert by_src["fabric"].target_state_id == "gateway"
    assert by_src["fabric"].medium.kind == "shared-memory"
    assert by_src["fabric"].medium.timeout == 2000
    assert by_src["fabric"].medium.transport is None

    # gateway -> mcu : network / gRPC, timeout=5000, idempotent=true.
    assert by_src["gateway"].target_state_id == "mcu"
    assert by_src["gateway"].medium.kind == "network"
    assert by_src["gateway"].medium.transport is not None
    assert by_src["gateway"].medium.transport.name == "gRPC"
    assert by_src["gateway"].medium.timeout == 5000
    assert by_src["gateway"].medium.idempotent is True
