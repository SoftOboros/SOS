"""Frozen SOS-11 MCP tool catalog and permission classification.

Authority: ``docs/concepts/SOS-11-CONCEPTS.md`` section 5 and section 10.
This module is intentionally data-only: it names the ratified tool surface and
classifies tool calls for approval policy, but it does not implement chart
mutation semantics.
"""

from __future__ import annotations

from enum import Enum


class Permission(str, Enum):
    """SOS-11 agent permission levels."""

    READ_ONLY = "read-only"
    STRUCTURE_PRESERVING_EDIT = "structure-preserving-edit"
    STRUCTURE_CHANGING_EDIT = "structure-changing-edit"


READ_ONLY = Permission.READ_ONLY.value
STRUCTURE_PRESERVING_EDIT = Permission.STRUCTURE_PRESERVING_EDIT.value
STRUCTURE_CHANGING_EDIT = Permission.STRUCTURE_CHANGING_EDIT.value


READ_ONLY_QUERY_TOOLS: tuple[str, ...] = (
    "query_state",
    "query_transitions",
    "query_vectors",
    "query_invariants",
    "query_event_vocabulary",
)

PRIMITIVE_TOOLS: tuple[str, ...] = (
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

HIGHER_INTENT_TOOLS: tuple[str, ...] = (
    "add_event_handler_for_state",
    "extract_orthogonal_region",
    "factor_dispatch",
    "replace_transition_target",
    "split_state",
    "merge_states",
    "add_timeout_to_state",
    "wrap_in_critical_section",
)


_STRUCTURE_PRESERVING_TOOLS = frozenset(
    {
        "add_event_to_vocabulary",
        "add_datamodel_entry",
        "update_datamodel_entry",
        "add_invariant",
        "rename_state",
    }
)

_ALL_TOOL_NAMES = READ_ONLY_QUERY_TOOLS + PRIMITIVE_TOOLS + HIGHER_INTENT_TOOLS
_ALL_TOOL_NAME_SET = frozenset(_ALL_TOOL_NAMES)

_HIGHER_INTENT_DECOMPOSITIONS: dict[str, tuple[str, ...]] = {
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


def all_tool_names() -> tuple[str, ...]:
    """Return every SOS-11 tool name in ratified document order."""

    return _ALL_TOOL_NAMES


def classify_tool(
    name: str, *, datamodel_type_compatible: bool = True
) -> Permission:
    """Return the SOS-11 permission level for a tool name.

    ``update_datamodel_entry`` is structure-preserving only when the type
    update is compatible with existing references. Callers that know an update
    is type-incompatible must pass ``datamodel_type_compatible=False`` to get
    the stricter structure-changing classification.
    """

    _ensure_known(name)

    if name in READ_ONLY_QUERY_TOOLS:
        return Permission.READ_ONLY

    if name == "update_datamodel_entry" and not datamodel_type_compatible:
        return Permission.STRUCTURE_CHANGING_EDIT

    if name in _STRUCTURE_PRESERVING_TOOLS:
        return Permission.STRUCTURE_PRESERVING_EDIT

    return Permission.STRUCTURE_CHANGING_EDIT


def is_primitive(name: str) -> bool:
    """Return whether ``name`` is a ratified SOS-11 primitive operation."""

    _ensure_known(name)
    return name in PRIMITIVE_TOOLS


def is_higher_intent(name: str) -> bool:
    """Return whether ``name`` is a ratified SOS-11 higher-intent operation."""

    _ensure_known(name)
    return name in HIGHER_INTENT_TOOLS


def decomposition_for(name: str) -> tuple[str, ...]:
    """Return the primitive decomposition for a higher-intent tool."""

    _ensure_known(name)
    try:
        return _HIGHER_INTENT_DECOMPOSITIONS[name]
    except KeyError as exc:
        raise KeyError(f"Tool {name!r} is not a higher-intent SOS-11 tool") from exc


def _ensure_known(name: str) -> None:
    if name not in _ALL_TOOL_NAME_SET:
        raise KeyError(f"Unknown SOS-11 MCP tool: {name!r}")


__all__ = [
    "HIGHER_INTENT_TOOLS",
    "PRIMITIVE_TOOLS",
    "READ_ONLY",
    "READ_ONLY_QUERY_TOOLS",
    "STRUCTURE_CHANGING_EDIT",
    "STRUCTURE_PRESERVING_EDIT",
    "Permission",
    "all_tool_names",
    "classify_tool",
    "decomposition_for",
    "is_higher_intent",
    "is_primitive",
]
