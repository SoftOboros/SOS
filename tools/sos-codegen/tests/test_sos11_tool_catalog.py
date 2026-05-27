"""Tests for the SOS-11 MCP frozen tool catalog."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# Make `sos-codegen` modules importable when pytest is invoked from any cwd.
_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sos11_mcp.tool_catalog import (  # noqa: E402
    HANDLER_BINDINGS,
    HIGHER_INTENT_TOOLS,
    PRIMITIVE_TOOLS,
    READ_ONLY_QUERY_TOOLS,
    TOOL_HANDLERS,
    Permission,
    all_tool_names,
    classify_tool,
    decomposition_for,
    get_handler,
    is_higher_intent,
    is_primitive,
)


EXPECTED_READ_ONLY_QUERY_TOOLS = (
    "query_state",
    "query_transitions",
    "query_vectors",
    "query_invariants",
    "query_event_vocabulary",
    "validate_chart",
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
    assert len(all_tool_names()) == 30
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


# ---------------------------------------------------------------------------
# SOS11U1 — tool-catalog registry harmonization.
# ---------------------------------------------------------------------------
#
# After Wave-3J (callable-based ``TOOL_HANDLERS`` + hardcoded
# ``get_handler`` branch for ``extract_region_to_subchart``) and
# Wave-3K (string-based ``HANDLER_BINDINGS`` mapping ``inline_subchart``
# to a dotted path) cherry-pick auto-merged, ``get_handler`` knew about
# extract but not inline. SOS11U1 collapses both to one: ``HANDLER_BINDINGS``
# is the canonical declarative registry; ``TOOL_HANDLERS`` is a
# resolution cache populated lazily on first lookup.


def test_handler_bindings_declares_both_wave_3_handlers() -> None:
    assert (
        HANDLER_BINDINGS["extract_region_to_subchart"]
        == "sos11_mcp.extract.extract_region_to_subchart"
    )
    assert (
        HANDLER_BINDINGS["inline_subchart"]
        == "sos11_mcp.inline.inline_subchart"
    )


def test_get_handler_resolves_inline_subchart_via_bindings() -> None:
    """SOS11U1: pre-harmonization this raised KeyError despite the binding existing."""
    handler = get_handler("inline_subchart")
    from sos11_mcp.inline import inline_subchart as _expected
    assert handler is _expected


def test_get_handler_resolves_extract_region_to_subchart_via_bindings() -> None:
    handler = get_handler("extract_region_to_subchart")
    from sos11_mcp.extract import extract_region_to_subchart as _expected
    assert handler is _expected


def test_get_handler_raises_helpful_keyerror_for_unhandled_known_tool() -> None:
    # ``factor_dispatch`` is in the catalog but has no HANDLER_BINDINGS entry yet.
    with pytest.raises(KeyError, match="no executable handler has landed"):
        get_handler("factor_dispatch")


def test_get_handler_raises_unknown_keyerror_for_unknown_tool() -> None:
    with pytest.raises(KeyError, match="Unknown SOS-11 MCP tool"):
        get_handler("reticulate_splines")


# ---------------------------------------------------------------------------
# SOS11W6C — validate_chart registered as read-only MCP tool (§5 amendment).
# ---------------------------------------------------------------------------
#
# Wave-4U2 (commit 236be36) shipped the four-axis validation composer at
# ``sos11_mcp.validation.validate_chart`` but left registration as a SOS-11
# MCP tool open ("the natural next entry alongside the harmonized... dictionaries"
# in the SOS11U2 §15 entry). Wave-6C closes that line item: ``validate_chart``
# joins ``READ_ONLY_QUERY_TOOLS`` (it inspects a chart and returns a report,
# no mutation) and ``HANDLER_BINDINGS`` (canonical declarative dispatch surface
# per SOS11U1).


def test_validate_chart_registered_in_read_only_tools() -> None:
    """SOS11W6C: ``validate_chart`` is a §10.1 read-only catalog member."""
    assert "validate_chart" in READ_ONLY_QUERY_TOOLS


def test_get_handler_validate_chart_returns_composer() -> None:
    """SOS11W6C: dispatch surface resolves to the Wave-4U2 composer callable."""
    handler = get_handler("validate_chart")
    from sos11_mcp.validation import validate_chart as _expected
    assert handler is _expected


def test_classify_tool_validate_chart_returns_read_only() -> None:
    """SOS11W6C: §10 permission scoping confirms read-only classification."""
    assert classify_tool("validate_chart") is Permission.READ_ONLY


def test_importing_tool_catalog_does_not_pull_extract_or_inline() -> None:
    """The lazy-import boundary is the cost-of-import contract.

    Importing :mod:`sos11_mcp.tool_catalog` MUST NOT transitively load
    :mod:`sos11_mcp.extract` or :mod:`sos11_mcp.inline` — callers that
    only need permission classification or catalog membership SHOULD
    NOT pay for the SOS-12 + scjson dependency chain those handler
    modules drag in.
    """
    probe = (
        "import sys\n"
        "import sos11_mcp.tool_catalog  # noqa: F401\n"
        "assert 'sos11_mcp.extract' not in sys.modules, "
        "'tool_catalog import pulled sos11_mcp.extract'\n"
        "assert 'sos11_mcp.inline' not in sys.modules, "
        "'tool_catalog import pulled sos11_mcp.inline'\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=str(_TOOLS_DIR),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Lazy-import boundary regressed: stdout={result.stdout!r} "
        f"stderr={result.stderr!r}"
    )
