"""Tests for SOS-11 MCP agent approval gates."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make `sos-codegen` modules importable when pytest is invoked from any cwd.
_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sos11_mcp.contracts import FailureCode, ToolCallError  # noqa: E402
from sos11_mcp.permissions import (  # noqa: E402
    ApprovalRequirement,
    PermissionGrant,
    approval_requirement,
    ensure_permission,
)


@pytest.mark.parametrize(
    ("tool_name", "requirement"),
    (
        ("query_state", ApprovalRequirement.NO_APPROVAL),
        ("rename_state", ApprovalRequirement.TEXT_APPROVAL),
        ("add_transition", ApprovalRequirement.GRAPHICAL_PREVIEW_APPROVAL),
    ),
)
def test_approval_requirement_maps_representative_tool_ranks(
    tool_name: str, requirement: ApprovalRequirement
) -> None:
    assert approval_requirement(tool_name) is requirement


def test_type_incompatible_datamodel_update_requires_graphical_preview() -> None:
    assert (
        approval_requirement(
            "update_datamodel_entry", datamodel_type_compatible=False
        )
        is ApprovalRequirement.GRAPHICAL_PREVIEW_APPROVAL
    )


def test_unknown_tool_names_propagate_from_catalog() -> None:
    with pytest.raises(KeyError, match="Unknown SOS-11 MCP tool"):
        approval_requirement("reticulate_splines")

    with pytest.raises(KeyError, match="Unknown SOS-11 MCP tool"):
        ensure_permission("reticulate_splines")


def test_read_only_tool_passes_without_approval() -> None:
    result = ensure_permission("query_vectors")

    assert isinstance(result, PermissionGrant)
    assert result.to_dict() == {
        "tool_name": "query_vectors",
        "requirement": "no-approval",
        "text_approved": False,
        "graphical_preview_approved": False,
    }


def test_structure_preserving_tool_requires_text_approval() -> None:
    denied = ensure_permission("add_invariant")

    assert isinstance(denied, ToolCallError)
    assert denied.code is FailureCode.PERMISSION_DENIED
    assert "Tool `add_invariant`" in denied.diagnosis
    assert "text approval" in denied.diagnosis
    assert denied.chart_unchanged is True

    granted = ensure_permission("add_invariant", text_approved=True)

    assert isinstance(granted, PermissionGrant)
    assert granted.requirement is ApprovalRequirement.TEXT_APPROVAL


def test_text_only_approval_is_insufficient_for_structure_changing_tool() -> None:
    denied = ensure_permission("add_state", text_approved=True)

    assert isinstance(denied, ToolCallError)
    assert denied.to_dict() == {
        "code": "PermissionDenied",
        "diagnosis": (
            "Tool `add_state` cannot proceed because the chart edit is missing "
            "text approval plus graphical diff preview approval."
        ),
        "failed_axis": None,
        "chart_unchanged": True,
    }


def test_full_approval_passes_for_structure_changing_tool() -> None:
    result = ensure_permission(
        "split_state",
        text_approved=True,
        graphical_preview_approved=True,
    )

    assert isinstance(result, PermissionGrant)
    assert result.to_dict() == {
        "tool_name": "split_state",
        "requirement": "text-and-graphical-preview-approval",
        "text_approved": True,
        "graphical_preview_approved": True,
    }
