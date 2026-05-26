"""Tests for SOS-11 SCXML diff helpers."""

from __future__ import annotations

import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sos11_mcp.contracts import ScxmlDiff  # noqa: E402
from sos11_mcp.diffs import (  # noqa: E402
    build_scxml_diff,
    render_unified_diff,
    structured_scxml_diff,
)


def _chart(
    states: list[dict],
    datamodel: list[dict] | None = None,
) -> dict:
    raw: dict = {"state": states, "initial": [states[0]["id"]] if states else []}
    if datamodel is not None:
        raw["datamodel"] = [{"data": datamodel}]
    return raw


def test_structured_diff_orders_added_and_removed_states_deterministically() -> None:
    before = _chart([{"id": "root"}, {"id": "beta"}, {"id": "epsilon"}])
    after = _chart([{"id": "root"}, {"id": "zeta"}, {"id": "alpha"}])

    diff = structured_scxml_diff(before, after)

    assert [state["id"] for state in diff["states"]["added"]] == ["alpha", "zeta"]
    assert [state["id"] for state in diff["states"]["removed"]] == [
        "beta",
        "epsilon",
    ]


def test_transition_identity_distinguishes_guarded_and_duplicate_transitions() -> None:
    before = _chart(
        [
            {
                "id": "idle",
                "transition": [
                    {
                        "event": "tick",
                        "cond": "counter > 0",
                        "target": ["ready"],
                    }
                ],
            },
            {"id": "ready"},
        ]
    )
    after = _chart(
        [
            {
                "id": "idle",
                "transition": [
                    {"event": "tick", "target": ["ready"]},
                    {"event": "tick", "target": ["ready"]},
                ],
            },
            {"id": "ready"},
        ]
    )

    diff = structured_scxml_diff(before, after)

    assert [(tr["cond"], tr["occurrence"]) for tr in diff["transitions"]["added"]] == [
        (None, 1),
        (None, 2),
    ]
    assert [(tr["cond"], tr["occurrence"]) for tr in diff["transitions"]["removed"]] == [
        ("counter > 0", 1)
    ]
    assert all("source" in tr["id"] for tr in diff["transitions"]["added"])


def test_datamodel_entries_report_added_removed_and_changed() -> None:
    before = _chart(
        [{"id": "idle"}],
        datamodel=[
            {"id": "counter", "expr": "0"},
            {"id": "flag", "expr": "false"},
        ],
    )
    after = _chart(
        [{"id": "idle"}],
        datamodel=[
            {"id": "counter", "expr": "counter + 1"},
            {"id": "mode", "expr": "'armed'", "type": "string"},
        ],
    )

    diff = structured_scxml_diff(before, after)

    assert diff["datamodel"]["added"] == [
        {"id": "mode", "expr": "'armed'", "type": "string"}
    ]
    assert diff["datamodel"]["removed"] == [{"id": "flag", "expr": "false"}]
    assert diff["datamodel"]["changed"] == [
        {
            "id": "counter",
            "before": {"id": "counter", "expr": "0"},
            "after": {"id": "counter", "expr": "counter + 1"},
        }
    ]


def test_event_vocabulary_reports_added_and_removed_events() -> None:
    before = _chart(
        [
            {
                "id": "idle",
                "transition": [
                    {"event": "alpha beta", "target": ["done"]},
                ],
            },
            {"id": "done"},
        ]
    )
    after = _chart(
        [
            {
                "id": "idle",
                "transition": [
                    {"event": "beta gamma", "target": ["done"]},
                ],
            },
            {"id": "done"},
        ]
    )

    diff = structured_scxml_diff(before, after)

    assert diff["events"] == {"added": ["gamma"], "removed": ["alpha"]}


def test_render_unified_diff_uses_standard_unified_diff_headers() -> None:
    before_xml = '<scxml>\n  <state id="idle"/>\n</scxml>\n'
    after_xml = '<scxml>\n  <state id="ready"/>\n</scxml>\n'

    rendered = render_unified_diff(
        before_xml,
        after_xml,
        fromfile="old.scxml",
        tofile="new.scxml",
    )

    assert rendered.startswith("--- old.scxml\n+++ new.scxml\n")
    assert '-  <state id="idle"/>\n' in rendered
    assert '+  <state id="ready"/>\n' in rendered


def test_build_scxml_diff_returns_contract_payload_with_optional_text_diff() -> None:
    before = _chart([{"id": "idle"}])
    after = _chart([{"id": "ready"}])

    diff = build_scxml_diff(
        before,
        after,
        before_xml='<scxml><state id="idle"/></scxml>\n',
        after_xml='<scxml><state id="ready"/></scxml>\n',
    )

    assert isinstance(diff, ScxmlDiff)
    payload = diff.to_dict()
    assert payload["ast_diff"]["states"]["added"] == [
        {"id": "ready", "kind": "state", "parent": None, "initial": []}
    ]
    assert payload["rendered_unified_diff"].startswith(
        "--- before.scxml\n+++ after.scxml\n"
    )


def test_build_scxml_diff_omits_text_diff_when_xml_is_not_supplied() -> None:
    diff = build_scxml_diff(_chart([{"id": "idle"}]), _chart([{"id": "ready"}]))

    assert diff.to_dict() == {
        "ast_diff": structured_scxml_diff(
            _chart([{"id": "idle"}]),
            _chart([{"id": "ready"}]),
        )
    }
