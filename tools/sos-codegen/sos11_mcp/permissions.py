"""SOS-11 MCP agent approval gate helpers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from sos11_mcp.contracts import FailureCode, ToolCallError
from sos11_mcp.tool_catalog import Permission, classify_tool


class ApprovalRequirement(str, Enum):
    """User approval required before an SOS-11 MCP tool call may proceed."""

    NO_APPROVAL = "no-approval"
    TEXT_APPROVAL = "text-approval"
    GRAPHICAL_PREVIEW_APPROVAL = "text-and-graphical-preview-approval"


@dataclass(frozen=True)
class PermissionGrant:
    """Successful permission-gate result for a proposed tool call."""

    tool_name: str
    requirement: ApprovalRequirement
    text_approved: bool
    graphical_preview_approved: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "requirement": self.requirement.value,
            "text_approved": self.text_approved,
            "graphical_preview_approved": self.graphical_preview_approved,
        }


def approval_requirement(
    tool_name: str, *, datamodel_type_compatible: bool = True
) -> ApprovalRequirement:
    """Return the SOS-11 approval requirement for a tool name."""

    permission = classify_tool(
        tool_name, datamodel_type_compatible=datamodel_type_compatible
    )

    if permission is Permission.READ_ONLY:
        return ApprovalRequirement.NO_APPROVAL
    if permission is Permission.STRUCTURE_PRESERVING_EDIT:
        return ApprovalRequirement.TEXT_APPROVAL
    if permission is Permission.STRUCTURE_CHANGING_EDIT:
        return ApprovalRequirement.GRAPHICAL_PREVIEW_APPROVAL

    raise ValueError(f"Unhandled SOS-11 permission classification: {permission!r}")


def ensure_permission(
    tool_name: str,
    *,
    text_approved: bool = False,
    graphical_preview_approved: bool = False,
    datamodel_type_compatible: bool = True,
) -> PermissionGrant | ToolCallError:
    """Return permission metadata or a SOS-11 permission-denied error."""

    requirement = approval_requirement(
        tool_name, datamodel_type_compatible=datamodel_type_compatible
    )

    if requirement is ApprovalRequirement.NO_APPROVAL:
        return PermissionGrant(
            tool_name=tool_name,
            requirement=requirement,
            text_approved=text_approved,
            graphical_preview_approved=graphical_preview_approved,
        )

    if requirement is ApprovalRequirement.TEXT_APPROVAL and text_approved:
        return PermissionGrant(
            tool_name=tool_name,
            requirement=requirement,
            text_approved=text_approved,
            graphical_preview_approved=graphical_preview_approved,
        )

    if (
        requirement is ApprovalRequirement.GRAPHICAL_PREVIEW_APPROVAL
        and text_approved
        and graphical_preview_approved
    ):
        return PermissionGrant(
            tool_name=tool_name,
            requirement=requirement,
            text_approved=text_approved,
            graphical_preview_approved=graphical_preview_approved,
        )

    return ToolCallError(
        code=FailureCode.PERMISSION_DENIED,
        diagnosis=_permission_denied_diagnosis(tool_name, requirement),
    )


def _permission_denied_diagnosis(
    tool_name: str, requirement: ApprovalRequirement
) -> str:
    if requirement is ApprovalRequirement.TEXT_APPROVAL:
        missing = "text approval"
    elif requirement is ApprovalRequirement.GRAPHICAL_PREVIEW_APPROVAL:
        missing = "text approval plus graphical diff preview approval"
    else:
        missing = requirement.value

    return (
        f"Tool `{tool_name}` cannot proceed because the chart edit is missing "
        f"{missing}."
    )


__all__ = [
    "ApprovalRequirement",
    "PermissionGrant",
    "approval_requirement",
    "ensure_permission",
]
