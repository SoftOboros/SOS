"""Tests for the SOS-11 MCP frozen tool catalog."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make `sos-codegen` modules importable when pytest is invoked from any cwd.
_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sos11_mcp.tool_catalog import (  # noqa: E402
    HIGHER_INTENT_TOOLS,
    PRIMITIVE_TOOLS,
    READ_ONLY_QUERY_TOOLS,
    Permission,
    all_tool_names,
    classify_tool,
    decomposition_for,
    is_higher_intent,
    is_primitive,
)


EXPECTED_READ_ONLY_QUERY_TOOLS = (
    "query_state",
    "query_transitions",
    "query_vectors",
    "query_invariants",
    "query_event_vocabulary",
)

EXPECTED_PRIMITIVE_TOOLS = (
    "add_state",
    "remove_state",
    "rename_state",
    "add_transition",
    "remove_transition",
    "nest_region",
    "unnest_region",
    "extract_region_to_subchart",
    "inline_subchart",
    "add_event_to_vocabulary",
    "remove_event_from_vocabulary",
    "add_datamodel_entry",
    "remove_datamodel_entry",
    "update_datamodel_entry",
    "add_invariant",
    "remove_invariant",
)

EXPECTED_HIGHER_INTENT_TOOLS = (
    "add_event_handler_for_state",
    "extract_orthogonal_region",
    "factor_dispatch",
    "replace_transition_target",
    "split_state",
    "merge_states",
    "add_timeout_to_state",
    "wrap_in_critical_section",
)


def test_tool_groups_match_sos_11_sections_5_and_10() -> None:
    assert READ_ONLY_QUERY_TOOLS == EXPECTED_READ_ONLY_QUERY_TOOLS
    assert PRIMITIVE_TOOLS == EXPECTED_PRIMITIVE_TOOLS
    assert HIGHER_INTENT_TOOLS == EXPECTED_HIGHER_INTENT_TOOLS


def test_all_tool_names_returns_frozen_catalog_without_duplicates() -> None:
    expected = (
        EXPECTED_READ_ONLY_QUERY_TOOLS
        + EXPECTED_PRIMITIVE_TOOLS
        + EXPECTED_HIGHER_INTENT_TOOLS
    )
    assert all_tool_names() == expected
    assert len(all_tool_names()) == 29
    assert len(set(all_tool_names())) == len(all_tool_names())


@pytest.mark.parametrize("name", EXPECTED_READ_ONLY_QUERY_TOOLS)
def test_read_only_query_tools_are_read_only(name: str) -> None:
    assert classify_tool(name) is Permission.READ_ONLY
    assert not is_primitive(name)
    assert not is_higher_intent(name)


@pytest.mark.parametrize(
    "name",
    (
        "add_event_to_vocabulary",
        "add_datamodel_entry",
        "update_datamodel_entry",
        "add_invariant",
        "rename_state",
    ),
)
def test_structure_preserving_primitives(name: str) -> None:
    assert classify_tool(name) is Permission.STRUCTURE_PRESERVING_EDIT
    assert is_primitive(name)
    assert not is_higher_intent(name)


def test_type_incompatible_datamodel_update_is_structure_changing() -> None:
    assert (
        classify_tool("update_datamodel_entry", datamodel_type_compatible=False)
        is Permission.STRUCTURE_CHANGING_EDIT
    )


@pytest.mark.parametrize(
    "name",
    (
        "add_state",
        "remove_state",
        "add_transition",
        "remove_transition",
        "nest_region",
        "unnest_region",
        "extract_region_to_subchart",
        "inline_subchart",
        "remove_event_from_vocabulary",
        "remove_datamodel_entry",
        "remove_invariant",
    ),
)
def test_structure_changing_primitives(name: str) -> None:
    assert classify_tool(name) is Permission.STRUCTURE_CHANGING_EDIT
    assert is_primitive(name)
    assert not is_higher_intent(name)


@pytest.mark.parametrize("name", EXPECTED_HIGHER_INTENT_TOOLS)
def test_higher_intent_tools_are_structure_changing(name: str) -> None:
    assert classify_tool(name) is Permission.STRUCTURE_CHANGING_EDIT
    assert not is_primitive(name)
    assert is_higher_intent(name)


def test_higher_intent_decompositions_are_primitive_sequences() -> None:
    expected = {
        "add_event_handler_for_state": (
            "add_event_to_vocabulary",
            "add_transition",
        ),
        "extract_orthogonal_region": (
            "nest_region",
            "add_state",
        ),
        "factor_dispatch": (
            "extract_region_to_subchart",
            "add_event_to_vocabulary",
        ),
        "replace_transition_target": (
            "remove_transition",
            "add_transition",
        ),
        "split_state": (
            "add_state",
            "add_transition",
            "remove_transition",
            "add_transition",
        ),
        "merge_states": (
            "rename_state",
            "remove_state",
        ),
        "add_timeout_to_state": (
            "add_event_to_vocabulary",
            "add_transition",
            "add_datamodel_entry",
        ),
        "wrap_in_critical_section": (
            "add_transition",
            "add_transition",
        ),
    }

    for name, decomposition in expected.items():
        assert decomposition_for(name) == decomposition
        assert all(is_primitive(primitive) for primitive in decomposition)


def test_replace_transition_target_decomposition_and_classification() -> None:
    assert decomposition_for("replace_transition_target") == (
        "remove_transition",
        "add_transition",
    )
    assert classify_tool("replace_transition_target") is Permission.STRUCTURE_CHANGING_EDIT


@pytest.mark.parametrize(
    "fn",
    (
        classify_tool,
        is_primitive,
        is_higher_intent,
        decomposition_for,
    ),
)
def test_unknown_tool_names_raise_clear_key_error(fn) -> None:
    with pytest.raises(KeyError, match="Unknown SOS-11 MCP tool"):
        fn("reticulate_splines")


def test_decomposition_for_rejects_non_higher_intent_tool() -> None:
    with pytest.raises(KeyError, match="not a higher-intent SOS-11 tool"):
        decomposition_for("add_transition")
