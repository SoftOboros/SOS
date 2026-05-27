"""SOS-13 verified-strip audit-log writer/reader.

Per [SOS-13-CONCEPTS.md §15 2026-05-23 ratification entry]
(../../docs/concepts/SOS-13-CONCEPTS.md):

- PCDN-SOS-13-002 resolved as **JSONL** — one elimination per line, diff-
  friendly, consistent with the existing conformance-vector format.
- PCDN-SOS-13-005 resolved **mandatory 6/6** at bench gate; this module
  does NOT enforce the gate — it only emits/reads the audit artifact.
  Bench-time gating is the separate harness's concern.

Concretizes [INV-SOS-G](../../docs/concepts/SOS-07-CONCEPTS.md) — every
runtime-check elimination MUST cite its discharging chart annotation, and
the citation MUST be persisted in a reviewable artifact. This module owns
the artifact's serialization surface.

The audit record shape (one JSON object per line):

    {
        "schema_version":    1,
        "region_id":         "<state-id-or-transition-region>",
        "chart_state":       "<state id from SCXML>",
        "operation":         "bounds_check_strip"
                             | "div_by_zero_strip"
                             | "null_check_strip"
                             | "overflow_check_strip",
        "discharge_source":  "<sos:discharged check=\\\"...\\\"/>",
        "emitted_line":      <int>,
        "safety_citation":   "<the SAFETY-comment text emitted in source>"
    }

The fields mirror the §7.4 prose model adapted to the JSONL line shape
that PCDN-SOS-13-002's ratification rests on.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator


AUDIT_SCHEMA_VERSION = 1


@dataclass
class AuditEntry:
    """One verified-strip audit record. Matches the JSONL shape above."""

    region_id: str
    chart_state: str
    operation: str
    discharge_source: str
    emitted_line: int
    safety_citation: str
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "region_id": self.region_id,
            "chart_state": self.chart_state,
            "operation": self.operation,
            "discharge_source": self.discharge_source,
            "emitted_line": self.emitted_line,
            "safety_citation": self.safety_citation,
        }
        if self.extra:
            d.update(
                {k: v for k, v in self.extra.items() if k != "schema_version"}
            )
        return d


class AuditLogWriter:
    """Append-only JSONL writer. One record per `write()` call.

    Usage:
        with AuditLogWriter(path) as w:
            w.write(entry)

    Truncates the file on entry (each codegen invocation produces a
    fresh audit log; verified-strip-audit.jsonl is build-scoped per
    SOS-13 §7.4 prose, "Per build under `--profile verified-strip`").
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._fh = None

    def __enter__(self) -> "AuditLogWriter":
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self._path.open("w", encoding="utf-8")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def write(self, entry: AuditEntry) -> None:
        assert self._fh is not None, "AuditLogWriter used outside context"
        line = json.dumps(entry.to_dict(), separators=(",", ":"), sort_keys=True)
        self._fh.write(line + "\n")

    def write_many(self, entries: Iterable[AuditEntry]) -> None:
        for e in entries:
            self.write(e)


def write_audit_log(path: Path, entries: Iterable[AuditEntry]) -> int:
    """Convenience: write all `entries` to `path` as JSONL. Returns
    the number of records emitted. Truncates an existing file."""
    n = 0
    with AuditLogWriter(path) as w:
        for e in entries:
            w.write(e)
            n += 1
    return n


def read_audit_log(path: Path) -> list[dict]:
    """Read a verified-strip audit log file and return the records as
    a list of dicts. Raises `json.JSONDecodeError` on a malformed line
    (rather than silently skipping — a malformed audit record is a
    correctness incident, not a "best effort" recovery)."""
    out: list[dict] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


def iter_audit_log(path: Path) -> Iterator[dict]:
    """Streaming form of `read_audit_log` — yields one dict per
    JSONL record. Useful for very large audit logs."""
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)
