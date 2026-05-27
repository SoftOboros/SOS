"""Frozen SOS-11 MCP tool catalog and permission classification.

Authority: ``docs/concepts/SOS-11-CONCEPTS.md`` section 5 and section 10.
This module is intentionally data-only: it names the ratified tool surface and
classifies tool calls for approval policy, but it does not implement chart
mutation semantics.
"""

from __future__ import annotations

import importlib
from enum import Enum
from typing import Any, Callable


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


# Canonical SOS-11 handler registry — declarative dotted-path bindings.
#
# Maps each primitive (§5.1) or higher-intent (§5.2) tool name with an
# implemented handler to its ``"module.path.callable"`` string. This is
# the SOS-11U1 harmonized single source of truth; the legacy
# ``TOOL_HANDLERS`` callable dict below is a resolution cache, not a
# primary registry. Read at the MCP dispatch surface; not load-bearing
# on the §5 catalog itself.
#
# Registration convention (post-SOS11U1): future Wave-N handler
# landings add ONE line here and require NO modification to
# :func:`get_handler`. An unbound name simply has no executable surface
# (the §15 wave entries name which primitives have handlers).
HANDLER_BINDINGS: dict[str, str] = {
    "extract_region_to_subchart": "sos11_mcp.extract.extract_region_to_subchart",
    "inline_subchart": "sos11_mcp.inline.inline_subchart",
}

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


# ---------------------------------------------------------------------------
# Tool-handler resolution cache — SOS11U1 harmonization.
# ---------------------------------------------------------------------------
#
# After the Wave-3J/Wave-3K cherry-pick auto-merge produced two parallel
# registries (the original ``TOOL_HANDLERS`` callable dict + Wave-3K's
# ``HANDLER_BINDINGS`` dotted-path dict), SOS11U1 collapses both to one:
# ``HANDLER_BINDINGS`` is the canonical declarative source of truth, and
# ``TOOL_HANDLERS`` is now a resolution cache populated on first lookup
# by :func:`get_handler`. Direct mutation of ``TOOL_HANDLERS`` remains
# supported for tests that want to inject a fake handler; production
# code SHOULD register via ``HANDLER_BINDINGS``.
#
# Lazy / deferred imports protect callers that import the catalog
# without needing the full SOS-12 dependency chain
# (sos12_annotations + sos12_contract_match + sos12_boundary_vectors)
# or scjson — importing :mod:`sos11_mcp.tool_catalog` MUST NOT
# transitively pull any handler module.
TOOL_HANDLERS: dict[str, Callable[..., Any]] = {}


def _resolve_binding(dotted_path: str) -> Callable[..., Any]:
    """Resolve a ``"module.path.callable"`` dotted path to a callable.

    Used by :func:`get_handler` to lazy-load handlers declared in
    :data:`HANDLER_BINDINGS`. Splitting on the last ``.`` gives the
    module-path / attribute boundary, then :func:`importlib.import_module`
    loads the module on first lookup.
    """
    module_name, _, attr_name = dotted_path.rpartition(".")
    if not module_name or not attr_name:
        raise ValueError(
            f"HANDLER_BINDINGS entry {dotted_path!r} is not a valid "
            "'module.path.callable' dotted path."
        )
    module = importlib.import_module(module_name)
    return getattr(module, attr_name)


def get_handler(tool_name: str) -> Callable[..., Any]:
    """Return the executable handler for a registered SOS-11 tool name.

    Resolution order (SOS11U1):

      1. If ``tool_name`` is in :data:`TOOL_HANDLERS` (either pre-cached
         from a prior lookup or test-injected), return that callable.
      2. Otherwise consult :data:`HANDLER_BINDINGS`; if a binding
         exists, lazy-import via :func:`_resolve_binding`, cache in
         ``TOOL_HANDLERS``, and return.
      3. Raise :class:`KeyError` for unknown catalog names AND for known
         catalog names whose handlers have not yet landed (the SOS-11
         §15 Wave-1 "Still open" list — the four-axis validation
         composer, the higher-intent decomposer, etc.).

    Callers SHOULD treat the absence of a handler as a permissions-
    rejected outcome per §10, not as a chart-author error.
    """
    _ensure_known(tool_name)
    cached = TOOL_HANDLERS.get(tool_name)
    if cached is not None:
        return cached
    binding = HANDLER_BINDINGS.get(tool_name)
    if binding is not None:
        handler = _resolve_binding(binding)
        TOOL_HANDLERS[tool_name] = handler
        return handler
    raise KeyError(
        f"Tool {tool_name!r} is registered in the SOS-11 catalog but no "
        "executable handler has landed yet (see SOS-11-CONCEPTS §15 "
        "'Still open' list)."
    )


__all__ = [
    "HANDLER_BINDINGS",
    "HIGHER_INTENT_TOOLS",
    "PRIMITIVE_TOOLS",
    "READ_ONLY",
    "READ_ONLY_QUERY_TOOLS",
    "STRUCTURE_CHANGING_EDIT",
    "STRUCTURE_PRESERVING_EDIT",
    "TOOL_HANDLERS",
    "Permission",
    "all_tool_names",
    "classify_tool",
    "decomposition_for",
    "get_handler",
    "is_higher_intent",
    "is_primitive",
]
