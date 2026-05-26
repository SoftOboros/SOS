"""Smoke test for the SOS-10 §9 worked-example chart (skeleton).

Loads `examples/orchestrator_mcu_fabric_gateway.scxml` through scjson via
the loader, parses the resulting scjson dict through
`sos10_annotations.parse_orchestrator_annotations`, and asserts that all
four media of the §5.2 frozen enumeration are exercised by at least one
cross-piece transition, and that both transport names from
PCDN-SOS-10-002 (gRPC + AMQP) appear on a network transition.

Authority: `docs/concepts/SOS-10-CONCEPTS.md` §9 + §12 gate (b). The
chart is a SKELETON proof-of-concept (not a runnable system at v1); the
sole gate this test enforces is "the text parses cleanly through the
annotation parser".

The emitter-level integration tests are wave-18 work and live elsewhere
— this test deliberately does NOT run the chart through any of the four
medium emitters (in-process / shared-memory / mmio / network).
"""

from __future__ import annotations

import json
import re
import sys
import uuid
from pathlib import Path

# Make `sos-codegen` modules importable when pytest is invoked from any cwd.
_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from loader import load_chart  # noqa: E402
from sos10_annotations import (  # noqa: E402
    ALLOWED_MEDIUM_KINDS,
    ALLOWED_TRANSPORT_NAMES,
    parse_orchestrator_annotations,
)


# Resolve repo root from this file's location (worked-example chart lives
# at <repo>/examples/, not under tools/sos-codegen/).
_REPO_ROOT = Path(__file__).resolve().parents[3]
_CHART = _REPO_ROOT / "examples" / "orchestrator_mcu_fabric_gateway.scxml"


def _expected_uuid_str() -> str:
    """The UUID the chart's top-of-file comment + sos:id attribute pin.

    Kept here in lockstep with the chart's `sos:id` for the parse-equality
    assertion below; if the chart's UUID ever changes this constant moves
    in the same commit.
    """
    return "7f3e8a2c-1b5d-4f6a-9e3c-2d8b7a1f4e5d"


def _root_sos_id(raw_scjson: dict) -> str:
    """Extract the chart-root `sos:id` from the scjson-shaped dict.

    Mirrors the `_extract_other_attributes` shape `sos10_annotations.py`
    uses internally (scjson 0.3.6 surfaces `other_attributes` as a dict
    whose `other_attributes` key holds a JSON-string payload).
    """
    oa = raw_scjson.get("other_attributes")
    assert isinstance(oa, dict), (
        f"chart root should carry an other_attributes wrapper; got {oa!r}"
    )
    inner = oa.get("other_attributes")
    assert isinstance(inner, str), (
        f"chart root other_attributes.other_attributes should be a JSON "
        f"string; got {inner!r}"
    )
    payload = json.loads(inner)
    assert "sos:id" in payload, (
        f"chart root other_attributes JSON missing sos:id key; got "
        f"{sorted(payload)}"
    )
    return payload["sos:id"]


def test_chart_file_exists():
    """Sanity: the chart file exists at the documented examples/ path."""
    assert _CHART.exists(), f"worked-example chart missing at {_CHART}"


def test_chart_sos_id_is_rfc4122_v4():
    """Chart root carries a valid RFC-4122 v4 UUID under sos:id.

    Per the chart's top-of-file documentation + the §9 worked-example
    narrative; the UUID identifies this specific orchestrator chart so
    downstream emitters can attribute their outputs to it without
    ambiguity in multi-chart corpora.
    """
    raw = load_chart(_CHART).raw_scjson
    sos_id = _root_sos_id(raw)
    assert sos_id == _expected_uuid_str()

    # RFC-4122 parsing: uuid.UUID accepts the canonical 8-4-4-4-12 hex
    # form. Verify .version == 4 (random-derived per RFC 4122 §4.4).
    parsed = uuid.UUID(sos_id)
    assert parsed.version == 4, (
        f"sos:id {sos_id} should be a v4 UUID; got version={parsed.version}"
    )
    # Variant 1 (RFC 4122) — top two bits of clock_seq_hi == 0b10. The
    # variant property returns the RFC-4122 string for compliant UUIDs.
    assert parsed.variant == uuid.RFC_4122

    # Belt-and-suspenders: canonical hyphenated lower-case shape.
    canonical_re = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-"
        r"[0-9a-f]{12}$"
    )
    assert canonical_re.match(sos_id), (
        f"sos:id {sos_id} does not match the canonical RFC-4122 v4 shape"
    )


def test_chart_parses_three_pieces():
    """Exactly three pieces — mcu, fabric, gateway — with the expected
    sos:lang values per §9."""
    raw = load_chart(_CHART).raw_scjson
    out = parse_orchestrator_annotations(raw)

    by_id = {p.state_id: p for p in out.pieces}
    assert set(by_id) == {"mcu", "fabric", "gateway"}, (
        f"expected exactly {{'mcu','fabric','gateway'}}; got {sorted(by_id)}"
    )
    assert by_id["mcu"].lang == "rust"
    assert by_id["fabric"].lang == "vhdl"
    # Gateway carries an explicit sos:lang="rust" per PCDN-SOS-10-001;
    # we assert the resolved value here rather than relying on the
    # DEFAULT_PIECE_LANG fallback.
    assert by_id["gateway"].lang == "rust"


def test_chart_exercises_all_four_media():
    """At least one cross-piece transition per medium kind in the §5.2
    frozen enum (in-process, shared-memory, mmio, network).

    This is the §12 gate (b) starting-artifact check: the chart's
    annotation surface covers every medium the orchestrator stack must
    eventually emit code for.
    """
    raw = load_chart(_CHART).raw_scjson
    out = parse_orchestrator_annotations(raw)

    media_seen = {t.medium.kind for t in out.transitions}
    assert media_seen == ALLOWED_MEDIUM_KINDS, (
        f"chart should exercise every medium in the §5.2 frozen enum; "
        f"saw {sorted(media_seen)}, expected {sorted(ALLOWED_MEDIUM_KINDS)}"
    )


def test_chart_exercises_both_network_transports():
    """Network transitions cover BOTH PCDN-SOS-10-002 transport names.

    gRPC is the primary transport at v1; AMQP is the secondary. The
    worked example pins one network transition per transport so the
    network emitter has a concrete trigger for each branch.
    """
    raw = load_chart(_CHART).raw_scjson
    out = parse_orchestrator_annotations(raw)

    network_transports = {
        t.medium.transport.name
        for t in out.transitions
        if t.medium.kind == "network" and t.medium.transport is not None
    }
    assert network_transports == ALLOWED_TRANSPORT_NAMES, (
        f"network transitions should cover both PCDN-SOS-10-002 "
        f"transports; saw {sorted(network_transports)}, expected "
        f"{sorted(ALLOWED_TRANSPORT_NAMES)}"
    )


def test_chart_named_transitions_match_documented_layout():
    """Pin the (event, source, target, medium-kind, transport) tuples to
    the layout the chart's top-of-file comment documents.

    The chart's top comment is the authored summary readers see; this
    test makes "the chart matches its own comment" a verified property
    rather than an aspiration.
    """
    raw = load_chart(_CHART).raw_scjson
    out = parse_orchestrator_annotations(raw)

    documented = {
        # (event, source, target) -> (medium-kind, transport-name-or-None)
        ("local_status_update", "mcu", "mcu"): ("in-process", None),
        ("start_capture", "mcu", "fabric"): ("mmio", None),
        ("stream_metrics_burst", "mcu", "gateway"): ("shared-memory", None),
        ("analytics_event", "fabric", "gateway"): ("network", "AMQP"),
        ("dashboard_command", "gateway", "mcu"): ("network", "gRPC"),
    }

    observed = {
        (t.event, t.source_state_id, t.target_state_id): (
            t.medium.kind,
            t.medium.transport.name if t.medium.transport else None,
        )
        for t in out.transitions
    }
    assert observed == documented, (
        f"chart transitions do not match the top-of-file comment layout. "
        f"Documented: {sorted(documented.items())}; observed: "
        f"{sorted(observed.items())}"
    )
