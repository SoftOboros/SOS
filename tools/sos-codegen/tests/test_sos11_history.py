"""Tests for SOS-11 chart-history commit metadata helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from sos11_mcp.contracts import (  # noqa: E402
    ScxmlDiff,
    ToolCallResult,
    ValidationReport,
    VectorDelta,
)
from sos11_mcp.history import (  # noqa: E402
    DEFAULT_AUTHOR_MODE,
    build_commit_body,
    build_commit_subject,
    commit_metadata,
)


def _result(
    *,
    summary: str = "added state `retrying` to subchart `auth.connecting`",
    vector_summary: str = "+4 traces enter `retrying`; -2 traces reach `failed`",
    full_delta_call_id: str | None = "call-vector-123",
) -> ToolCallResult:
    return ToolCallResult(
        scxml_diff=ScxmlDiff(
            ast_diff={"ops": [{"op": "add_state", "id": "retrying"}]},
            rendered_unified_diff="--- before.scxml\n+++ after.scxml\n",
        ),
        vector_delta=VectorDelta(
            summary=vector_summary,
            citations=("state:retrying",),
            full_delta_call_id=full_delta_call_id,
        ),
        summary=summary,
        validation=ValidationReport.all_passed(),
    )


def test_build_commit_subject_uses_tool_name_and_chart_summary() -> None:
    subject = build_commit_subject(
        "add_state",
        "retrying in subchart auth.connecting",
    )

    assert subject == "add_state: retrying in subchart auth.connecting"


def test_build_commit_subject_normalizes_to_one_line() -> None:
    subject = build_commit_subject(
        "add_transition",
        "timeout   from\nconnecting\tto retrying",
    )

    assert subject == "add_transition: timeout from connecting to retrying"


def test_build_commit_subject_truncates_only_summary_deterministically() -> None:
    summary = "retrying in subchart auth.connecting after tcp.refused events"

    first = build_commit_subject("add_state", summary, max_length=42)
    second = build_commit_subject("add_state", summary, max_length=42)

    assert first == second
    assert first == "add_state: retrying in subchart auth.co..."
    assert len(first) == 42
    assert first.startswith("add_state: ")


def test_build_commit_body_preserves_summary_verbatim() -> None:
    summary = "added transition `connecting` -> `retrying`\n\nReason: tcp.refused"
    body = build_commit_body(_result(summary=summary))

    assert body.startswith(f"{summary}\n\n")


def test_build_commit_body_includes_vector_delta_block() -> None:
    body = build_commit_body(
        _result(
            vector_summary="+4 traces enter `retrying`; -2 traces reach `failed`",
            full_delta_call_id="call-vector-123",
        )
    )

    assert "vector_delta:\n" in body
    assert "  summary: +4 traces enter `retrying`; -2 traces reach `failed`\n" in body
    assert "  full_delta_call_id: call-vector-123" in body


def test_build_commit_body_omits_full_delta_call_id_when_absent() -> None:
    body = build_commit_body(_result(full_delta_call_id=None))

    assert "vector_delta:\n" in body
    assert "full_delta_call_id" not in body


def test_commit_metadata_defaults_to_human_via_agent() -> None:
    metadata = commit_metadata("add_state", _result())

    assert metadata.author_mode == DEFAULT_AUTHOR_MODE
    assert metadata.subject.startswith("add_state: ")
    assert metadata.message == f"{metadata.subject}\n\n{metadata.body}"
    assert metadata.scxml_diff == "--- before.scxml\n+++ after.scxml\n"


def test_commit_metadata_accepts_agent_author_mode() -> None:
    metadata = commit_metadata("add_state", _result(), author_mode="agent")

    assert metadata.author_mode == "agent"


def test_commit_metadata_validates_author_mode() -> None:
    with pytest.raises(ValueError, match="author_mode must be one of"):
        commit_metadata("add_state", _result(), author_mode="robot")


def test_commit_metadata_uses_ast_diff_when_unified_diff_is_absent() -> None:
    result = ToolCallResult(
        scxml_diff=ScxmlDiff(ast_diff={"ops": [{"op": "remove_state", "id": "old"}]}),
        vector_delta=VectorDelta(summary="-1 trace reaches `old`"),
        summary="removed obsolete state `old`",
        validation=ValidationReport.all_passed(),
    )

    metadata = commit_metadata("remove_state", result)

    assert metadata.scxml_diff == {
        "ast_diff": {"ops": [{"op": "remove_state", "id": "old"}]}
    }
