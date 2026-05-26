from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import loader
from sos11_mcp.chart_query import (
    query_datamodel_entries,
    query_event_vocabulary,
    query_invariants,
    query_state,
    query_transitions,
)

FIXTURES = TOOLS_DIR / "tests" / "fixtures"


def _raw_fixture(name: str) -> dict:
    return loader.load_chart(FIXTURES / name).raw_scjson


def test_query_state_finds_nested_state_and_parallel_wrapper() -> None:
    raw = _raw_fixture("parallel_two_regions.scxml")

    parallel = query_state(raw, "par")
    nested = query_state(raw, "a_idle")

    assert parallel == {
        "id": "par",
        "kind": "parallel",
        "initial": [],
        "children": [
            {"id": "region_a", "kind": "state"},
            {"id": "region_b", "kind": "state"},
        ],
        "transitions": [],
    }
    assert nested["id"] == "a_idle"
    assert nested["kind"] == "state"
    assert nested["transitions"] == [
        {
            "source": "a_idle",
            "target": ["a_ready"],
            "event": "go_a",
            "cond": None,
        }
    ]


def test_query_transitions_filters_by_source_target_and_event() -> None:
    raw = _raw_fixture("parallel_two_regions.scxml")

    assert query_transitions(raw, source="a_idle") == [
        {
            "source": "a_idle",
            "target": ["a_ready"],
            "event": "go_a",
            "cond": None,
        }
    ]
    assert query_transitions(raw, target="b_ready") == [
        {
            "source": "b_idle",
            "target": ["b_ready"],
            "event": "go_b",
            "cond": None,
        }
    ]
    assert query_transitions(raw, event="go_a") == [
        {
            "source": "a_idle",
            "target": ["a_ready"],
            "event": "go_a",
            "cond": None,
        }
    ]
    assert query_transitions(raw, source="a_idle", target="b_ready") == []


def test_query_transitions_normalizes_string_targets() -> None:
    raw = copy.deepcopy(_raw_fixture("single_guarded_transition.scxml"))
    raw["state"][0]["transition"][0]["target"] = "ready"

    assert query_transitions(raw, source="idle", target="ready", event="tick")[0] == {
        "source": "idle",
        "target": ["ready"],
        "event": "tick",
        "cond": "counter > 0",
    }


def test_query_event_vocabulary_is_sorted_from_transition_events() -> None:
    raw = _raw_fixture("parallel_two_regions.scxml")

    assert query_event_vocabulary(raw) == ["go_a", "go_b"]


def test_query_datamodel_entries_returns_ids_and_expressions() -> None:
    raw = _raw_fixture("single_region_with_datamodel.scxml")

    assert query_datamodel_entries(raw) == [
        {"id": "counter", "expr": "0"},
        {"id": "flag", "expr": "false"},
    ]


def test_query_invariants_returns_empty_until_chart_grammar_exists() -> None:
    raw = _raw_fixture("parallel_two_regions.scxml")

    assert query_invariants(raw) == []
    assert query_invariants(raw, state="a_idle") == []


def test_query_state_missing_state_raises_clear_key_error() -> None:
    raw = _raw_fixture("parallel_two_regions.scxml")

    with pytest.raises(KeyError, match="state id not found: missing"):
        query_state(raw, "missing")
