"""SOS-08-G GTKWave annotation-overlay extension (wave-1 scaffold).

Reads a ``<test>.annotations.jsonl`` review-artifact overlay file
(per the SOS-08-G three-file output contract — `.fst` + `.vcd` +
`.annotations.jsonl`) and either:

  1. renders a human-readable cycle-by-cycle preview to stdout (the
     wave-1 CLI surface used by chart authors before GUI integration
     lands), or
  2. emits a GTKWave Tcl script that adds chart-state markers to the
     waveform timeline (the actual GUI integration shape — GTKWave
     loads ``.tcl`` files via ``--script`` or the
     ``File → Read Save File`` menu to install custom markers).

Wave-1 scope: functional scaffolding only — the script is runnable
standalone (``python3 sos_gtkwave_ext.py <test.annotations.jsonl>``)
so chart authors can preview annotations even before installing the
GUI extension. Full integration with GTKWave's ``gtkwave-extensions``
API lands in wave-2 once that API stabilises.

@spec  SOS-08-G-CONCEPTS.md §6.1 (annotation overlay format — `.fst`
       and `.vcd` co-located with `.annotations.jsonl` per shared
       filename prefix; viewer extension MUST locate overlay by
       co-location per §6 (a)).
@spec  SOS-08-G-CONCEPTS.md §5.2 + §15 (PCDN-G-001 resolution):
       schema-version header is the first line of the overlay file;
       header carries `{"_meta": {"schema": "sos-08-g/annotations",
       "version": "1.0", "chart_path_max_depth": 8}}` per
       PCDN-G-001 + PCDN-G-002 resolutions.
@spec  SOS-08-G-CONCEPTS.md §5.5 + §15 (PCDN-G-004 resolution):
       viewer-extension distribution location is in-subrepo at
       ``tools/sos-codegen/viewers/{gtkwave,surfer}/``.
@spec  SOS-08-G-CONCEPTS.md §6 (viewer integration contract —
       (a) co-locate, (b) schema-version-aware, (c) per-record render
       are MUST; (d) chart-path navigation, (e) invariant-fire
       highlighting, (f) vector-citation drill-down are SHOULD).
@spec  SOS-08-G-CONCEPTS.md §7 cross-sub-phase invariants:
         INV-S-HDL-G-1 (three-file output coupling),
         INV-S-HDL-G-2 (chart-vocabulary mandatory in overlay),
         INV-S-HDL-G-3 (schema-version header required at line 0),
         INV-S-HDL-G-4 (build-output discipline — overlay is not
                        tracked source),
         INV-S-HDL-G-5 (generation co-location with SOS-08-D/E/F),
         INV-S-HDL-G-6 (chart-diff + waveform-diff parity for
                        MCP-workflow review).

Wave-2 work (deferred, NOT in this scaffold):
  - Live GTKWave integration via the ``gtkwave-extensions`` API
    (signals/markers added at runtime as the user scrubs).
  - Chart-path navigation UI affordance (§6 (d) SHOULD).
  - Vector-citation click-through to the SOS-03 vector definition
    (§6 (f) SHOULD).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable, Sequence

# ---------------------------------------------------------------------------
# Schema constants (frozen by SOS-08-G §5.2 + §15 PCDN-G-001 resolution).
# ---------------------------------------------------------------------------

SCHEMA_NAME = "sos-08-g/annotations"
"""Schema identifier per SOS-08-G §5.2 (canonicalized in PCDN-G-wave1-001)."""

SCHEMA_VERSION = "1.0"
"""Schema version frozen at v1.0 per SOS-08-G §5.2 + §12 (b)."""

CHART_PATH_MAX_DEPTH = 8
"""Chart-path depth cap mirrored from SOS-12 per PCDN-G-002 resolution."""

NORMATIVE_FIELDS: tuple[str, ...] = (
    "cycle",
    "signal",
    "chart_state",
    "transition_id",
    "chart_path",
    "region",
)
"""Six normative annotation-record fields per SOS-08-G §5.2."""

OPTIONAL_FIELDS: tuple[str, ...] = (
    "invariant_id",
    "vector_index",
)
"""Two optional annotation-record fields per SOS-08-G §5.2."""


# ---------------------------------------------------------------------------
# Loader + validator
# ---------------------------------------------------------------------------


def validate_schema_header(header: dict) -> None:
    """Validate the first-line schema-version header per INV-S-HDL-G-3.

    Accepts either the simple shape (``{"schema": ..., "version": ...}``)
    or the canonical ``_meta`` envelope shape; both are permitted
    because PCDN-G-wave1-001 ratifies the ``_meta``-wrapped form as the
    emit-side canonical envelope while preserving the flat shape for
    legacy / external producers.

    Raises ``ValueError`` if the header does not declare the v1
    ``sos-08-g/annotations`` schema.
    """
    meta = header.get("_meta", header)
    schema = meta.get("schema")
    version = meta.get("version")
    if schema != SCHEMA_NAME:
        raise ValueError(
            f"unrecognized annotation schema {schema!r} "
            f"(expected {SCHEMA_NAME!r}); per SOS-08-G INV-S-HDL-G-3 "
            f"the overlay's first line MUST be the schema header"
        )
    if version != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported annotation schema version {version!r} "
            f"(this extension supports {SCHEMA_VERSION!r})"
        )


def load_annotations(path: Path) -> list[dict]:
    """Load + validate an SOS-08-G annotation overlay file.

    Returns the list of annotation records (header NOT included).
    Raises ``FileNotFoundError`` if the overlay is absent;
    ``ValueError`` if the file is empty, the header is malformed, or
    any record fails JSON parsing.

    Wave-1 surfaces the header through ``validate_schema_header``; it
    does NOT enforce per-record normative-field presence (that is the
    generation-point's responsibility per INV-S-HDL-G-2 and is
    re-asserted by the wave-2 conformance checker).
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"annotation overlay not found at {path!s}; "
            f"per SOS-08-G §6 (a) the viewer MAY render the waveform "
            f"alone if the overlay is absent but standalone invocation "
            f"of this script requires the overlay"
        )
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        raise ValueError(
            f"annotation overlay {path!s} is empty; "
            f"per INV-S-HDL-G-3 the first line MUST be the schema header"
        )
    try:
        header = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"annotation overlay {path!s} line 0 is not valid JSON: {exc}"
        ) from exc
    validate_schema_header(header)
    records: list[dict] = []
    for idx, raw in enumerate(lines[1:], start=1):
        try:
            records.append(json.loads(raw))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"annotation overlay {path!s} line {idx} is not valid JSON: {exc}"
            ) from exc
    return records


# ---------------------------------------------------------------------------
# Stdout preview (CLI-only wave-1 surface)
# ---------------------------------------------------------------------------


def _format_record(record: dict) -> str:
    """Render one annotation record as a single human-readable line.

    Renders the six normative fields + the two optional fields when
    present. Mirrors the per-record render contract of SOS-08-G §6 (c)
    at the CLI surface so chart authors can preview the overlay
    without GTKWave installed.
    """
    cycle = record.get("cycle", "?")
    signal = record.get("signal", "?")
    chart_state = record.get("chart_state", "?")
    transition_id = record.get("transition_id")
    chart_path = record.get("chart_path", "?")
    region = record.get("region")
    invariant_id = record.get("invariant_id")
    vector_index = record.get("vector_index")

    parts = [
        f"cycle={cycle:>6}" if isinstance(cycle, int) else f"cycle={cycle!s:>6}",
        f"signal={signal}",
        f"chart_state={chart_state}",
        f"transition_id={transition_id if transition_id is not None else '-'}",
        f"chart_path={chart_path}",
    ]
    if region is not None:
        parts.append(f"region={region}")
    if invariant_id is not None:
        parts.append(f"invariant_id={invariant_id}")
    if vector_index is not None:
        parts.append(f"vector_index={vector_index}")
    return "  ".join(parts)


def render_to_stdout(
    annotations: Sequence[dict],
    stream=None,
) -> None:
    """Print cycle-by-cycle chart-state transitions in human-readable form.

    Wave-1 CLI preview surface — the script's primary user-facing
    output before GTKWave's GUI integration lands in wave-2. Output
    is sorted by ``cycle`` so the scrub order matches what GTKWave
    would render on the timeline.
    """
    out = stream if stream is not None else sys.stdout
    print("# SOS-08-G annotation overlay — wave-1 stdout preview", file=out)
    print(f"# schema={SCHEMA_NAME} version={SCHEMA_VERSION}", file=out)
    print(f"# records={len(annotations)}", file=out)
    sorted_recs = sorted(
        annotations,
        key=lambda r: r.get("cycle", 0) if isinstance(r.get("cycle"), int) else 0,
    )
    for record in sorted_recs:
        print(_format_record(record), file=out)


# ---------------------------------------------------------------------------
# GTKWave Tcl emission (GUI integration shape)
# ---------------------------------------------------------------------------


def _tcl_escape(value: object) -> str:
    """Escape a value for inclusion in a GTKWave Tcl string literal."""
    text = str(value)
    # GTKWave's Tcl interpreter is fairly strict; escape brackets, dollar
    # signs, and backslashes which would otherwise be interpreted.
    return (
        text.replace("\\", "\\\\")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("$", "\\$")
        .replace('"', '\\"')
    )


def to_gtkwave_tcl(annotations: Sequence[dict]) -> str:
    """Emit a GTKWave Tcl script that installs chart-state markers.

    GTKWave's Tcl extension API exposes ``gtkwave::addCommentTracesFromList``
    and a numbered ``set_marker_name`` / ``set_named_marker_value``
    family for installing named markers on the timeline. Wave-1 emits
    ``set_marker_name`` + ``set_named_marker`` calls — one per
    annotation record — carrying the chart-state badge as the marker
    label. Wave-2 will expand this to a full ``addCommentTracesFromList``
    overlay track so badges live in their own pane.

    GTKWave accepts up to 26 named markers (A..Z); if the annotation
    set exceeds 26 records the emitter truncates with a Tcl comment
    explaining the limit (wave-1 limitation; wave-2 will batch markers
    via the comment-trace track which has no count limit).
    """
    lines: list[str] = []
    lines.append("# SOS-08-G annotation overlay — GTKWave Tcl markers")
    lines.append(f"# schema={SCHEMA_NAME} version={SCHEMA_VERSION}")
    lines.append(f"# records={len(annotations)}")
    lines.append("# Wave-1 scaffold: markers A..Z (max 26). Wave-2 lifts the cap")
    lines.append("# via gtkwave::addCommentTracesFromList overlay track.")
    lines.append("")

    sorted_recs = sorted(
        annotations,
        key=lambda r: r.get("cycle", 0) if isinstance(r.get("cycle"), int) else 0,
    )
    cap = min(len(sorted_recs), 26)
    for idx in range(cap):
        record = sorted_recs[idx]
        marker_letter = chr(ord("A") + idx)
        cycle = record.get("cycle", 0)
        chart_state = _tcl_escape(record.get("chart_state", "?"))
        transition_id = record.get("transition_id")
        invariant_id = record.get("invariant_id")
        label_parts = [chart_state]
        if transition_id:
            label_parts.append(f"t:{_tcl_escape(transition_id)}")
        if invariant_id:
            label_parts.append(f"inv:{_tcl_escape(invariant_id)}")
        label = "/".join(label_parts)
        # GTKWave time units are in the dump's time scale; the cycle
        # column maps to "cycle * clock_period" in the .fst/.vcd. The
        # wave-2 integration resolves the multiplier from the test
        # config; wave-1 emits the raw cycle and lets the user adjust
        # the marker scale interactively (documented in the README).
        lines.append(f"# record {idx}: cycle={cycle}")
        lines.append(f"gtkwave::/Edit/Set_Named_Marker {marker_letter} {cycle}")
        lines.append(
            f"gtkwave::/Edit/Set_Marker_Name {marker_letter} \"{label}\""
        )
        # Add an explicit add_marker line so test fixtures (and future
        # wave-2 implementations that switch to a different GTKWave
        # command surface) can grep for the conventional name.
        lines.append(f"add_marker {marker_letter} {cycle} \"{label}\"")
        lines.append("")
    if len(sorted_recs) > 26:
        lines.append(
            f"# NOTE: {len(sorted_recs) - 26} additional records suppressed "
            "(GTKWave named-marker cap = 26). Wave-2 will use the "
            "comment-trace overlay track which has no cap."
        )
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sos_gtkwave_ext",
        description=(
            "SOS-08-G GTKWave annotation-overlay extension "
            "(wave-1 scaffold — preview + Tcl emission)."
        ),
    )
    parser.add_argument(
        "annotations",
        type=Path,
        help="Path to <test>.annotations.jsonl overlay file.",
    )
    parser.add_argument(
        "--format",
        choices=("stdout", "tcl"),
        default="stdout",
        help="Output shape: 'stdout' human preview (default), 'tcl' GTKWave script.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="When --format=tcl, write the Tcl script to this path "
        "instead of stdout.",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(list(argv) if argv is not None else None)
    try:
        records = load_annotations(args.annotations)
    except (FileNotFoundError, ValueError) as exc:
        print(f"sos_gtkwave_ext: {exc}", file=sys.stderr)
        return 2
    if args.format == "stdout":
        render_to_stdout(records)
        return 0
    tcl = to_gtkwave_tcl(records)
    if args.output is None:
        sys.stdout.write(tcl)
    else:
        args.output.write_text(tcl, encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via CLI smoke
    raise SystemExit(main())
