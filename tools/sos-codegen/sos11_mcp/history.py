"""SOS-11 chart-history commit metadata helpers.

These helpers only construct commit metadata and messages. They never invoke
git and never mutate a chart repository.
"""

from __future__ import annotations

from dataclasses import dataclass

from sos11_mcp.contracts import ToolCallResult


DEFAULT_COMMIT_SUBJECT_MAX_LENGTH = 72
COMMIT_SUBJECT_SEPARATOR = ": "
SUMMARY_TRUNCATION_MARKER = "..."
DEFAULT_AUTHOR_MODE = "human-via-agent"
ALLOWED_AUTHOR_MODES = frozenset({DEFAULT_AUTHOR_MODE, "agent"})


@dataclass(frozen=True)
class ChartCommitMetadata:
    """Metadata needed by a caller that will create a chart-history commit."""

    subject: str
    body: str
    author_mode: str
    scxml_diff: str | dict[str, object]

    @property
    def message(self) -> str:
        """Return the complete commit message."""
        return f"{self.subject}\n\n{self.body}"


def _require_non_empty(label: str, value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} must be non-empty")
    return normalized


def _single_line_summary(summary: str) -> str:
    return " ".join(summary.strip().split())


def _truncate_summary(summary: str, max_length: int) -> str:
    if len(summary) <= max_length:
        return summary
    if max_length < len(SUMMARY_TRUNCATION_MARKER):
        raise ValueError("subject length leaves no room for a summary")
    if max_length == len(SUMMARY_TRUNCATION_MARKER):
        return SUMMARY_TRUNCATION_MARKER
    return (
        f"{summary[: max_length - len(SUMMARY_TRUNCATION_MARKER)].rstrip()}"
        f"{SUMMARY_TRUNCATION_MARKER}"
    )


def build_commit_subject(
    tool_name: str,
    summary: str,
    *,
    max_length: int = DEFAULT_COMMIT_SUBJECT_MAX_LENGTH,
) -> str:
    """Build an SOS-11 commit subject from a tool name and chart summary."""
    tool_name = _require_non_empty("tool_name", tool_name)
    summary = _require_non_empty("summary", _single_line_summary(summary))
    prefix = f"{tool_name}{COMMIT_SUBJECT_SEPARATOR}"
    max_summary_length = max_length - len(prefix)
    if max_summary_length <= 0:
        raise ValueError("tool_name leaves no room for a summary")
    return f"{prefix}{_truncate_summary(summary, max_summary_length)}"


def build_commit_body(result: ToolCallResult) -> str:
    """Build an SOS-11 commit body from a successful tool-call result."""
    vector_delta_lines = [
        "vector_delta:",
        f"  summary: {result.vector_delta.summary}",
    ]
    if result.vector_delta.full_delta_call_id is not None:
        vector_delta_lines.append(
            f"  full_delta_call_id: {result.vector_delta.full_delta_call_id}"
        )

    return f"{result.summary}\n\n" + "\n".join(vector_delta_lines)


def commit_metadata(
    tool_name: str,
    result: ToolCallResult,
    *,
    author_mode: str = DEFAULT_AUTHOR_MODE,
) -> ChartCommitMetadata:
    """Build SOS-11 chart-history commit metadata without creating a commit."""
    if author_mode not in ALLOWED_AUTHOR_MODES:
        allowed = ", ".join(sorted(ALLOWED_AUTHOR_MODES))
        raise ValueError(f"author_mode must be one of: {allowed}")

    scxml_diff: str | dict[str, object]
    if result.scxml_diff.rendered_unified_diff is not None:
        scxml_diff = result.scxml_diff.rendered_unified_diff
    else:
        scxml_diff = {"ast_diff": dict(result.scxml_diff.ast_diff)}

    return ChartCommitMetadata(
        subject=build_commit_subject(tool_name, result.summary),
        body=build_commit_body(result),
        author_mode=author_mode,
        scxml_diff=scxml_diff,
    )
