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


def discover_waveform_paths(path: Path) -> list[Path]:
    """Resolve the waveform file paths a viewer should open for the
    given annotation overlay (SOS-08-G wave-3b co-locate semantics).

    Reads the overlay's first-line `_meta` header and, when
    `waveform_prefix` is present (wave-3b filename-prefix coordination
    by construction per PCDN-G-wave1-003), returns
    `[<dir>/<prefix>.fst, <dir>/<prefix>.vcd]` paths in the same
    directory as the overlay. Existence is NOT enforced here — the
    caller checks `Path.exists()` per its own retry/fallback policy.
    When the header lacks `waveform_prefix` (wave-1 / wave-2 overlays),
    falls back to the same-prefix-as-overlay convention:
    `<overlay-without-suffix>.fst|.vcd`.

    Cites: SOS-08-G §6 (a) co-locate (amended 2026-05-24); §5.2 +
    INV-S-HDL-G-1 (three-file output coupling).
    """
    path = Path(path)
    overlay_dir = path.parent
    # Same-prefix wave-1 fallback. The overlay's filename without
    # `.annotations.jsonl` is the wave-1 same-prefix base.
    name = path.name
    if name.endswith(".annotations.jsonl"):
        base = name[: -len(".annotations.jsonl")]
    else:
        base = path.stem
    fallback = [overlay_dir / f"{base}.fst", overlay_dir / f"{base}.vcd"]
    # Read just the header line to extract `_meta.waveform_prefix`
    # when present. Defensive: missing file / malformed line → fall
    # back to the same-prefix convention without raising.
    try:
        with path.open("r", encoding="utf-8") as fh:
            first_line = fh.readline().strip()
    except OSError:
        return fallback
    if not first_line:
        return fallback
    try:
        header = json.loads(first_line)
    except json.JSONDecodeError:
        return fallback
    meta = header.get("_meta", header)
    waveform_prefix = meta.get("waveform_prefix")
    if not isinstance(waveform_prefix, str) or not waveform_prefix:
        return fallback
    return [
        overlay_dir / f"{waveform_prefix}.fst",
        overlay_dir / f"{waveform_prefix}.vcd",
    ]


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
    """Emit a GTKWave Tcl script that installs chart-state markers +
    comment-trace overlay tracks.

    GTKWave's Tcl extension API exposes ``gtkwave::addCommentTracesFromList``
    for inserting comment-trace rows in the waveform pane (where each
    row holds a list of (time, label) pairs rendered as text badges on
    the timeline) and a numbered ``set_marker_name`` /
    ``set_named_marker_value`` family for installing up-to-26 named
    markers (A..Z).

    Wave-1 emitted only named markers; wave-3c (2026-05-24) adds the
    comment-trace overlay tracks so the badge layer has no per-test
    record cap and chart-path navigation per §6 (d) is rendered as a
    dedicated track named ``sos:<chart_path>``. Invariant-fire records
    (§6 (e)) get a separate ``sos:invariants`` track so the visual
    treatment is distinct from ordinary chart-state transitions.

    Output shape:

      1. Named markers A..P (or fewer when the record count is below
         26 — wave-1 cap preserved as the *quick-jump* layer GTKWave
         keyboard shortcuts navigate).
      2. ``gtkwave::addCommentTracesFromList`` calls — one per
         unique ``chart_path`` value — installing a comment-trace
         track in the waveform pane.
      3. A dedicated ``sos:invariants`` comment-trace track when the
         overlay carries any ``invariant_id``-bearing records.

    The cycle column maps to the dump's time scale; the wave-3c emit
    uses the raw cycle value as the time. Vector authors who require
    a cycle→ns multiplier (e.g., a 10ns clock) MAY set the
    ``SOS_GTKWAVE_TIME_SCALE`` env var consumed by ``sos_overlay.tcl``;
    wave-3c-future will thread the multiplier through the emit step.
    """
    lines: list[str] = []
    lines.append("# SOS-08-G annotation overlay — GTKWave Tcl script")
    lines.append(f"# schema={SCHEMA_NAME} version={SCHEMA_VERSION}")
    lines.append(f"# records={len(annotations)}")
    lines.append(
        "# Wave-3c: named markers A..Z + comment-trace overlay tracks "
        "(per-chart-path + invariants)."
    )
    lines.append("")

    sorted_recs = sorted(
        annotations,
        key=lambda r: r.get("cycle", 0) if isinstance(r.get("cycle"), int) else 0,
    )

    # --- Section 1: named markers (§6 (c) per-record render) --- #
    lines.append(
        "# --- named markers (max 26 per GTKWave; keyboard-navigable A..Z) ---"
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
        lines.append(f"# record {idx}: cycle={cycle}")
        lines.append(f"gtkwave::/Edit/Set_Named_Marker {marker_letter} {cycle}")
        lines.append(
            f"gtkwave::/Edit/Set_Marker_Name {marker_letter} \"{label}\""
        )
        # Conventional alias surface — test fixtures + downstream
        # wave-3c-future viewer hooks grep for the unprefixed forms.
        lines.append(f"add_marker {marker_letter} {cycle} \"{label}\"")
        lines.append("")
    if len(sorted_recs) > 26:
        lines.append(
            f"# NOTE: {len(sorted_recs) - 26} record(s) beyond the named-"
            "marker cap; rendered via comment-trace tracks below."
        )
        lines.append("")

    # --- Section 2: per-chart_path comment-trace overlay tracks (§6 (d)) --- #
    lines.append("# --- per-chart_path comment-trace overlay tracks (§6 (d)) ---")
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
        # GTKWave's `addCommentTracesFromList` consumes a Tcl list of
        # alternating time/comment elements; the wave-3c emit wraps the
        # list in curly braces and escapes the labels.
        pairs: list[str] = []
        for cycle, label in entries:
            pairs.append(f"{cycle} \"{_tcl_escape(label)}\"")
        flat = " ".join(pairs)
        lines.append(
            f"gtkwave::addCommentTracesFromList \"{_tcl_escape(track_name)}\" "
            f"{{{flat}}}"
        )
    lines.append("")

    # --- Section 3: invariant-fire comment-trace track (§6 (e)) --- #
    invariants = [
        record
        for record in sorted_recs
        if record.get("invariant_id") is not None
    ]
    if invariants:
        lines.append("# --- invariant-fire overlay track (§6 (e)) ---")
        pairs = []
        for record in invariants:
            cycle = record.get("cycle", 0)
            invariant_id = record.get("invariant_id", "?")
            chart_state = record.get("chart_state", "?")
            label = f"{invariant_id} @ {chart_state}"
            pairs.append(f"{cycle} \"{_tcl_escape(label)}\"")
            # Conventional alias — sos_overlay.tcl + downstream wave-
            # 3c-future hooks grep this for visual-treatment overrides.
            lines.append(
                f"mark_invariant \"{_tcl_escape(label)}\" {cycle}"
            )
        flat = " ".join(pairs)
        lines.append(
            f"gtkwave::addCommentTracesFromList \"sos:invariants\" "
            f"{{{flat}}}"
        )
        lines.append("")

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
        choices=("stdout", "tcl", "gtkwave"),
        default="stdout",
        help="Output shape: 'stdout' human preview (default), 'tcl' or "
        "'gtkwave' (aliases) GTKWave Tcl marker script invoked from "
        "sos_overlay.tcl during wave-3c GUI integration.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="When --format=tcl|gtkwave, write the Tcl script to this "
        "path instead of stdout.",
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
    # `tcl` and `gtkwave` are equivalent aliases — the latter is the
    # explicit name the wave-3c sos_overlay.tcl loader uses when
    # shelling out from inside the GTKWave Tcl interpreter.
    tcl = to_gtkwave_tcl(records)
    if args.output is None:
        sys.stdout.write(tcl)
    else:
        args.output.write_text(tcl, encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via CLI smoke
    raise SystemExit(main())
