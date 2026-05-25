"""SOS-08-G Surfer annotation-overlay extension (wave-1 scaffold).

Reads a ``<test>.annotations.jsonl`` review-artifact overlay file
(per the SOS-08-G three-file output contract — `.fst` + `.vcd` +
`.annotations.jsonl`) and either:

  1. renders a human-readable cycle-by-cycle preview to stdout (the
     wave-1 CLI surface used by chart authors before GUI integration
     lands), or
  2. emits a Surfer command-script (``.surfer-cmd``) that installs
     chart-state markers / cursor annotations on the waveform
     timeline (the actual GUI integration shape — Surfer's command
     palette accepts scripted batches of ``add_marker`` /
     ``add_cursor`` style commands).

Wave-1 scope: functional scaffolding only — the script is runnable
standalone (``python3 sos_surfer_ext.py <test.annotations.jsonl>``)
so chart authors can preview annotations even before installing the
GUI extension. Full integration with Surfer's WCP / WAL extension
APIs lands in wave-2 once that API stabilises.

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
         INV-S-HDL-G-1..6 (same set GTKWave extension cites — the
         viewer-side conformance contract is symmetric between
         GTKWave and Surfer).

Wave-2 work (deferred, NOT in this scaffold):
  - Live Surfer integration via the WCP (Waveform Communication
    Protocol) extension API.
  - Chart-path navigation UI affordance (§6 (d) SHOULD).
  - Invariant-fire visual treatment with Surfer's color-class API
    (§6 (e) SHOULD).
  - Vector-citation click-through to the SOS-03 vector definition
    (§6 (f) SHOULD).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable, Sequence

# Re-export the schema constants from the GTKWave module to avoid drift
# (both extensions are bound to the same SOS-08-G §5.2 schema; the
# shared-constants policy mirrors the convention used by SOS-08-D's
# cocotb helpers).
try:  # pragma: no cover - tested indirectly via the surfer scaffold tests
    from ..gtkwave.sos_gtkwave_ext import (
        CHART_PATH_MAX_DEPTH,
        NORMATIVE_FIELDS,
        OPTIONAL_FIELDS,
        SCHEMA_NAME,
        SCHEMA_VERSION,
        discover_waveform_paths,
        load_annotations,
        load_overlay_header,
        validate_schema_header,
    )
except ImportError:  # pragma: no cover - standalone invocation fallback
    # When the script is invoked directly via
    # `python3 tools/sos-codegen/viewers/surfer/sos_surfer_ext.py ...`
    # the relative-import above fails because the package context is
    # not established. Fall back to a path-bootstrap import that
    # mirrors the pattern used by tools/sos-codegen/tests.
    _HERE = Path(__file__).resolve().parent
    _VIEWERS = _HERE.parent
    if str(_VIEWERS) not in sys.path:
        sys.path.insert(0, str(_VIEWERS))
    from gtkwave.sos_gtkwave_ext import (  # type: ignore[no-redef]
        CHART_PATH_MAX_DEPTH,
        NORMATIVE_FIELDS,
        OPTIONAL_FIELDS,
        SCHEMA_NAME,
        SCHEMA_VERSION,
        discover_waveform_paths,
        load_annotations,
        load_overlay_header,
        validate_schema_header,
    )


__all__ = [
    "CHART_PATH_MAX_DEPTH",
    "NORMATIVE_FIELDS",
    "OPTIONAL_FIELDS",
    "SCHEMA_NAME",
    "SCHEMA_VERSION",
    "discover_waveform_paths",
    "load_annotations",
    "load_overlay_header",
    "validate_schema_header",
    "render_to_stdout",
    "to_surfer_commands",
    "main",
]


# ---------------------------------------------------------------------------
# Stdout preview (CLI-only wave-1 surface)
# ---------------------------------------------------------------------------


def _format_record(record: dict) -> str:
    """Render one annotation record as a single human-readable line.

    Mirrors the per-record render contract of SOS-08-G §6 (c) at the
    CLI surface so chart authors can preview the overlay without
    Surfer installed. Identical output shape to the GTKWave scaffold
    so the previews are interchangeable.
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
    output before Surfer's GUI integration lands in wave-2.
    """
    out = stream if stream is not None else sys.stdout
    print("# SOS-08-G annotation overlay — wave-1 stdout preview (surfer)", file=out)
    print(f"# schema={SCHEMA_NAME} version={SCHEMA_VERSION}", file=out)
    print(f"# records={len(annotations)}", file=out)
    sorted_recs = sorted(
        annotations,
        key=lambda r: r.get("cycle", 0) if isinstance(r.get("cycle"), int) else 0,
    )
    for record in sorted_recs:
        print(_format_record(record), file=out)


# ---------------------------------------------------------------------------
# Surfer command-script emission (GUI integration shape)
# ---------------------------------------------------------------------------


def _surfer_escape(value: object) -> str:
    """Escape a value for inclusion in a Surfer command-script argument.

    Surfer's command parser accepts double-quoted string literals with
    standard backslash escaping; we conservatively escape the same set
    GTKWave's Tcl path escapes.
    """
    text = str(value)
    return text.replace("\\", "\\\\").replace('"', '\\"')


def to_surfer_commands(
    annotations: Sequence[dict],
    vector_source: str | None = None,
) -> str:
    """Emit a Surfer command-script that installs chart-state markers +
    per-chart_path overlay tracks.

    Surfer's command palette (loaded via the ``--command-file`` CLI flag
    or pasted into the F1 palette) accepts batches of scripted
    commands. Wave-3c (2026-05-24) emits:

      1. Per-record ``add_marker`` calls (wave-1 surface preserved as
         the keyboard-navigable layer).
      2. Per-chart_path ``add_overlay_track`` + ``add_overlay_event``
         calls — one track per unique ``chart_path`` per §6 (d) chart-
         path navigation SHOULD gate.
      3. A dedicated ``sos:invariants`` overlay track for invariant-
         fire records per §6 (e) invariant-fire highlighting SHOULD.

    Surfer's overlay-track API is still in flux (the WCP spec evolves
    with each Surfer release); wave-3c emits the conventional command
    names the matching sos-surfer-plugin Rust/WASM plugin consumes
    when running inside Surfer's plugin host. Direct Surfer-CLI users
    may stub the unknown commands as no-ops in a ``.surfer.toml`` file
    until the underlying Surfer release ships them.
    """
    lines: list[str] = []
    lines.append("# SOS-08-G annotation overlay — Surfer command script")
    lines.append(f"# schema={SCHEMA_NAME} version={SCHEMA_VERSION}")
    lines.append(f"# records={len(annotations)}")
    lines.append(
        "# Wave-3c: per-record add_marker + per-chart_path overlay tracks "
        "+ invariant-fire highlight."
    )
    lines.append("")

    sorted_recs = sorted(
        annotations,
        key=lambda r: r.get("cycle", 0) if isinstance(r.get("cycle"), int) else 0,
    )

    # --- Section 1: per-record markers (§6 (c)) --- #
    lines.append("# --- per-record markers (§6 (c)) ---")
    for idx, record in enumerate(sorted_recs):
        cycle = record.get("cycle", 0)
        chart_state = _surfer_escape(record.get("chart_state", "?"))
        transition_id = record.get("transition_id")
        invariant_id = record.get("invariant_id")
        label_parts = [chart_state]
        if transition_id:
            label_parts.append(f"t:{_surfer_escape(transition_id)}")
        if invariant_id:
            label_parts.append(f"inv:{_surfer_escape(invariant_id)}")
        label = "/".join(label_parts)
        lines.append(f"# record {idx}: cycle={cycle}")
        lines.append(f'add_marker "{label}" {cycle}')
        if invariant_id is not None:
            # Conventional name — picked up by sos-surfer-plugin's
            # invariant-fire visual-treatment hook + grep-able by the
            # CLI smoke tests.
            lines.append(f'mark_invariant "{label}" {cycle}')
        lines.append("")

    # --- Section 2: per-chart_path overlay tracks (§6 (d)) --- #
    lines.append(
        "# --- per-chart_path overlay tracks (§6 (d) chart-path navigation) ---"
    )
    by_path: dict[str, list[tuple[int, str]]] = {}
    for record in sorted_recs:
        chart_path = record.get("chart_path")
        if isinstance(chart_path, list):
            chart_path_str = "/" + "/".join(str(seg) for seg in chart_path)
        elif isinstance(chart_path, str) and chart_path:
            chart_path_str = chart_path
        else:
            chart_path_str = "/"
        cycle = record.get("cycle", 0)
        chart_state = record.get("chart_state", "?")
        transition_id = record.get("transition_id")
        label = chart_state
        if transition_id:
            label = f"{chart_state} (t:{transition_id})"
        by_path.setdefault(chart_path_str, []).append((cycle, label))
    for chart_path_str, entries in sorted(by_path.items()):
        track_name = f"sos:{chart_path_str}"
        # add_overlay_track creates the named pane; add_overlay_event
        # populates it with (cycle, label) entries.
        lines.append(f'add_overlay_track "{_surfer_escape(track_name)}"')
        for cycle, label in entries:
            lines.append(
                f'add_overlay_event "{_surfer_escape(track_name)}" '
                f'{cycle} "{_surfer_escape(label)}"'
            )
    lines.append("")

    # --- Section 4 (wave-3c-future §6 (f)): vector-citation drill-down --- #
    #
    # When `vector_source` is provided (read from `_meta.vector_source`
    # in the overlay header) emit one `open_vector_source <path> <idx>`
    # command per annotation record carrying `vector_index`. Surfer's
    # plugin host either routes the command via its link-back API
    # (when the host releases a stabilised hook), or stubs it as a
    # no-op (forward-compatible — the wave-3c-future emit is correct
    # regardless of host-side adoption).
    #
    # When `vector_source` is None we emit NOTHING in this section —
    # Surfer's command list is consumed once at overlay-load time
    # (unlike the GTKWave Tcl plugin which retains the global across
    # subsequent installs), so there's no value in surfacing a
    # cleared-path sentinel. Wave-3c byte-identity preserved for the
    # legacy `to_surfer_commands(records)` call shape.
    if vector_source is not None:
        vector_records = [
            record
            for record in sorted_recs
            if record.get("vector_index") is not None
        ]
        lines.append(
            "# --- vector-citation drill-down (§6 (f) — wave-3c-future) ---"
        )
        lines.append(
            f'set_vector_source "{_surfer_escape(vector_source)}"'
        )
        for record in vector_records:
            cycle = record.get("cycle", 0)
            vector_index = record.get("vector_index")
            chart_state = record.get("chart_state", "?")
            # Each emitted `open_vector_source` is a click-target the
            # host's plugin can wire to the user's editor at runtime.
            # The chart_state token gives the host a chart-vocabulary
            # tooltip for the link.
            lines.append(
                f'open_vector_source "{_surfer_escape(vector_source)}" '
                f'{vector_index} {cycle} '
                f'"{_surfer_escape(chart_state)}"'
            )
        lines.append("")

    # --- Section 3: invariant-fire overlay track (§6 (e)) --- #
    invariants = [
        record
        for record in sorted_recs
        if record.get("invariant_id") is not None
    ]
    if invariants:
        lines.append("# --- invariant-fire overlay track (§6 (e)) ---")
        lines.append('add_overlay_track "sos:invariants"')
        for record in invariants:
            cycle = record.get("cycle", 0)
            invariant_id = record.get("invariant_id", "?")
            chart_state = record.get("chart_state", "?")
            label = f"{invariant_id} @ {chart_state}"
            lines.append(
                f'add_overlay_event "sos:invariants" {cycle} '
                f'"{_surfer_escape(label)}"'
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sos_surfer_ext",
        description=(
            "SOS-08-G Surfer annotation-overlay extension "
            "(wave-1 scaffold — preview + command-script emission)."
        ),
    )
    parser.add_argument(
        "annotations",
        type=Path,
        help="Path to <test>.annotations.jsonl overlay file.",
    )
    parser.add_argument(
        "--format",
        choices=("stdout", "surfer"),
        default="stdout",
        help="Output shape: 'stdout' human preview (default), "
        "'surfer' command script.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="When --format=surfer, write the command script to this "
        "path instead of stdout.",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(list(argv) if argv is not None else None)
    try:
        records = load_annotations(args.annotations)
    except (FileNotFoundError, ValueError) as exc:
        print(f"sos_surfer_ext: {exc}", file=sys.stderr)
        return 2
    if args.format == "stdout":
        render_to_stdout(records)
        return 0
    # Wave-3c-future (§6 (f)): thread `_meta.vector_source` from the
    # overlay header so emitted commands include the drill-down link
    # target. Mirrors the GTKWave extension's CLI surface.
    try:
        meta = load_overlay_header(args.annotations)
    except (FileNotFoundError, ValueError):
        meta = {}
    vector_source = meta.get("vector_source") if isinstance(meta, dict) else None
    if not isinstance(vector_source, str) or not vector_source:
        vector_source = None
    text = to_surfer_commands(records, vector_source=vector_source)
    if args.output is None:
        sys.stdout.write(text)
    else:
        args.output.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via CLI smoke
    raise SystemExit(main())
