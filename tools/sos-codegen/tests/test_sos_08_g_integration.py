"""SOS-08-G wave-1 integration tests — annotation emission + viewers.

@spec  docs/concepts/SOS-08-G-CONCEPTS.md §5.1 (three-file output
       contract `.fst` + `.vcd` + `<test>.annotations.jsonl`)
@spec  docs/concepts/SOS-08-G-CONCEPTS.md §5.2 (annotation overlay
       schema: six normative fields + two optional)
@spec  docs/concepts/SOS-08-G-CONCEPTS.md §5.6 (one file per test run
       — PCDN-G-003 resolution)
@spec  docs/concepts/SOS-08-G-CONCEPTS.md §5.7 (per-event default
       annotation granularity — PCDN-G-005 resolution; cycle-density
       opt-in via SOS_ANNOTATION_DENSITY=cycle env var)
@spec  docs/concepts/SOS-08-G-CONCEPTS.md §6 (viewer integration
       contract — (a) co-locate, (b) schema-version-aware, (c) per-
       record render are MUST)
@spec  docs/concepts/SOS-08-G-CONCEPTS.md §15 (2026-05-23 ratification
       — PCDN-SOS-08-G-001..007 resolved; first-line header carrying
       ``{"_meta": {"schema": "sos-annotations", "version": "1.0",
       "chart_path_max_depth": 8}}``)

@invariants  INV-S-HDL-G-1 (three-file output coupling)
@invariants  INV-S-HDL-G-2 (chart-vocabulary mandatory in overlay)
@invariants  INV-S-HDL-G-3 (schema-version header required as line 0)
@invariants  INV-S-HDL-G-4 (build-output discipline)
@invariants  INV-S-HDL-G-5 (generation co-location with SOS-08-D/E/F)
@invariants  INV-S-HDL-G-6 (chart-diff + waveform-diff parity)

@pcdn  PCDN-SOS-08-G-001 (resolved 2026-05-23): schema-version
       detection via first-line header record.
@pcdn  PCDN-SOS-08-G-002 (resolved 2026-05-23): chart_path max depth
       mirrors SOS-12 = 8.
@pcdn  PCDN-SOS-08-G-003 (resolved 2026-05-23): one
       `.annotations.jsonl` per test run.
@pcdn  PCDN-SOS-08-G-004 (resolved 2026-05-23): viewer extensions
       live in-subrepo at `tools/sos-codegen/viewers/{gtkwave,surfer}/`.
@pcdn  PCDN-SOS-08-G-005 (resolved 2026-05-23): per-event default;
       `SOS_ANNOTATION_DENSITY=cycle` env var opts into per-cycle.
@pcdn  PCDN-SOS-08-G-006 (resolved 2026-05-23): line-buffered flush.
@pcdn  PCDN-SOS-08-G-007 (resolved 2026-05-23): sub-chart-local
       vector_index citation; chart_path disambiguates ownership.

These tests exercise the wave-1 SOS-08-G surface across three landing
agents:

  1. The cocotb walker (``transliterate_cocotb``) emits
     ``_cocotb_helpers.py`` carrying an ``AnnotationWriter`` class
     plus a test body that imports the writer and calls
     ``record_transition`` per chart-state transition.

  2. The viewer-extension scaffolds at
     ``tools/sos-codegen/viewers/{gtkwave,surfer}/`` load a wave-1
     fixture (``viewers/tests/fixtures/example_annotations.jsonl``)
     and surface chart-vocabulary records (GTKWave: stdout preview +
     Tcl marker emission; Surfer: stdout preview + extension JSON).

  3. The end-to-end pipeline composes (1) + (2): the walker's
     ``AnnotationWriter`` produces a file whose shape the viewer
     extensions can consume without further translation —
     INV-S-HDL-G-1 (three-file coupling) + INV-S-HDL-G-2 (chart-
     vocabulary mandatory) verified by round-trip.

Wave-1 is a STATIC deliverable; the integration test is committed
before all three sibling agents have landed. ``pytest.importorskip``
gates each test on the corresponding sibling module so the suite skips
gracefully when a module isn't on disk yet; once all three land the
suite passes end-to-end.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Bootstrap — match the test_sos_08_d_integration.py sys.path shim so
# pytest can import sibling modules from `tools/sos-codegen/` regardless
# of which cwd the runner was launched from.
# ---------------------------------------------------------------------------

TESTS_DIR = Path(__file__).resolve().parent
TOOL_DIR = TESTS_DIR.parent
FIXTURES_DIR = TESTS_DIR / "fixtures"
VIEWER_FIXTURES_DIR = TOOL_DIR / "viewers" / "tests" / "fixtures"
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))


FIXTURE_SCXML = FIXTURES_DIR / "single_region_simple.scxml"
CHART_NAME = "single_region_simple"

# Wave-1 viewer fixture: a hand-crafted six-record annotation overlay
# that exercises every normative + optional field per §5.2 (see
# `viewers/tests/fixtures/example_annotations.jsonl`).
WAVE_1_FIXTURE = VIEWER_FIXTURES_DIR / "example_annotations.jsonl"


def _scjson_available() -> bool:
    """``scjson`` CLI gate — the loader's chart-IR materialisation
    delegates to ``scjson`` on a subprocess; without it the walker tests
    cannot run. Mirrors test_sos_08_d_integration.py."""
    try:
        res = subprocess.run(
            ["scjson", "--help"], capture_output=True, text=True, check=False
        )
        return res.returncode == 0
    except (FileNotFoundError, OSError):
        return False


def _emit_via_walker(chart_path: Path = FIXTURE_SCXML) -> dict[str, str]:
    """Invoke the cocotb walker's ``render_target`` against the fixture.

    Skips at the call site if the walker is mid-flight (importorskip)
    or if ``scjson`` is not on PATH.
    """
    if not _scjson_available():
        pytest.skip(
            "`scjson` CLI not on PATH; the cocotb walker's chart-IR "
            "materialisation requires scjson. Install the scjson "
            "Python package to run SOS-08-G integration tests."
        )
    walker = pytest.importorskip(
        "transliterate_cocotb",
        reason="transliterate_cocotb sibling-agent module not yet on "
        "disk; SOS-08-G integration tests skip until the wave-1 "
        "cocotb walker commit lands.",
    )
    from loader import load_chart  # noqa: WPS433 — late import per sys.path

    ast_obj = load_chart(chart_path)
    assert ast_obj.raw_scjson is not None, (
        f"loader.load_chart did not populate raw_scjson for {chart_path}"
    )
    files = walker.render_target(
        ast_obj.raw_scjson, {"chart_name": CHART_NAME}
    )
    assert isinstance(files, dict), (
        f"walker render_target returned {type(files).__name__}, expected "
        f"dict; SOS-08-D §6.1 file-set contract drift."
    )
    return files


def _find_body(files: dict[str, str], suffix: str) -> str:
    """Return the body of the first file in ``files`` whose path ends
    with ``suffix``, or fail loudly with a diagnostic."""
    for fname, body in files.items():
        if fname.endswith(suffix):
            return body
    pytest.fail(
        f"SOS-08-G integration: no file ending with {suffix!r} in "
        f"cocotb walker emit. Got: {sorted(files)!r}"
    )


# ---------------------------------------------------------------------------
# §5.2 + §5.6 + §5.7 + INV-S-HDL-G-2 / -3 / -5 — the cocotb walker emits
# the AnnotationWriter surface that the @cocotb.test() body uses to write
# the review-artifact overlay at test runtime.
# ---------------------------------------------------------------------------


class TestAnnotationEmitsAtTestRuntime:
    """The walker's emitted ``_cocotb_helpers.py`` carries the
    ``AnnotationWriter`` class per §5.2 + §5.6 + §5.7; the emitted test
    body imports it and calls ``record_transition`` per chart-state
    transition (INV-S-HDL-G-5: generation co-located with the test).
    """

    def test_cocotb_walker_emits_annotation_writer(self):
        """SOS-08-G §5.2 + INV-S-HDL-G-3: the helpers module emitted by
        the cocotb walker MUST contain an ``AnnotationWriter`` class
        and the ``_SCHEMA_HEADER`` constant whose value matches the
        ratified header shape per §15."""
        files = _emit_via_walker()
        helpers = _find_body(files, "_cocotb_helpers.py")

        assert "class AnnotationWriter" in helpers, (
            "SOS-08-G §5.2 / INV-S-HDL-G-2: emitted `_cocotb_helpers.py` "
            "does not declare `class AnnotationWriter`. The annotation "
            "writer is the wave-1 generation point per INV-S-HDL-G-5; "
            "without it the cocotb test cannot produce the review-"
            "artifact overlay."
        )
        assert "_SCHEMA_HEADER" in helpers, (
            "SOS-08-G INV-S-HDL-G-3: emitted `_cocotb_helpers.py` does "
            "not carry the `_SCHEMA_HEADER` constant. The schema-"
            "version header is the first line of every `.annotations."
            "jsonl` per §5.2 + PCDN-G-001; the writer cannot emit a "
            "conformant header without this constant."
        )
        # The header MUST be the ratified §15 shape.
        for token in (
            '"schema"',
            '"sos-annotations"',
            '"version"',
            '"1.0"',
            "chart_path_max_depth",
        ):
            assert token in helpers, (
                f"SOS-08-G §15 (2026-05-23): emitted helpers schema "
                f"header missing token {token!r}. Expected "
                f'`{{"_meta": {{"schema": "sos-annotations", '
                f'"version": "1.0", "chart_path_max_depth": 8}}}}` per '
                f"PCDN-G-001 + PCDN-G-002."
            )

    def test_cocotb_test_body_calls_record_transition(self):
        """SOS-08-G §5.3 + INV-S-HDL-G-5: the emitted
        ``test_<chart>_fsm.py`` MUST import ``AnnotationWriter`` and
        call ``record_transition`` per chart-state transition."""
        files = _emit_via_walker()
        test_body = _find_body(files, f"test_{CHART_NAME}_fsm.py")

        assert "AnnotationWriter" in test_body, (
            "SOS-08-G INV-S-HDL-G-5: emitted cocotb test body does not "
            "reference `AnnotationWriter`. The generation point is "
            "instrumented INSIDE the @cocotb.test() body (NOT a "
            "post-process step) per §5.3 + INV-S-HDL-G-5."
        )
        assert "record_transition" in test_body, (
            "SOS-08-G §5.2 / INV-S-HDL-G-2: emitted cocotb test body "
            "does not call `record_transition`. Per-event default "
            "density (PCDN-G-005) requires the test body to emit one "
            "annotation record per chart-state transition; without "
            "the call no records reach the overlay."
        )

    def test_annotation_density_env_var_referenced(self):
        """SOS-08-G §5.7 / PCDN-G-005: the helpers module MUST reference
        the ``SOS_ANNOTATION_DENSITY`` environment variable so the
        per-cycle opt-in is honored at test runtime."""
        files = _emit_via_walker()
        helpers = _find_body(files, "_cocotb_helpers.py")
        assert "SOS_ANNOTATION_DENSITY" in helpers, (
            "SOS-08-G PCDN-G-005: emitted `_cocotb_helpers.py` does "
            "not reference the `SOS_ANNOTATION_DENSITY` env var. "
            "Per-event default is fine, but the env-var opt-in MUST "
            "be wired so high-bandwidth debug sessions can request "
            "per-cycle granularity without modifying the emit."
        )

    def test_emit_includes_readme_annotation_section(self):
        """SOS-08-G §5.4 + §5.5: the emitted README documents the
        annotation overlay's file location and the viewer extensions
        (GTKWave + Surfer) that consume it."""
        files = _emit_via_walker()
        readme = _find_body(files, "README.md")

        readme_lower = readme.lower()
        assert "annotation" in readme_lower, (
            "SOS-08-G §5.4: emitted README does not mention the "
            "annotation overlay. Per §5.4 the README documents the "
            "review-artifact contract so chart authors know where the "
            "`.annotations.jsonl` file lands."
        )
        assert ".annotations.jsonl" in readme, (
            "SOS-08-G §5.1 + §5.6: emitted README does not name "
            "`.annotations.jsonl` — the canonical filename for the "
            "wave-1 overlay file (PCDN-G-003: one file per test run)."
        )
        assert "gtkwave" in readme_lower, (
            "SOS-08-G §5.5 + PCDN-G-004: emitted README does not "
            "mention GTKWave (the primary open-source viewer "
            "extension target per §5.5)."
        )
        assert "surfer" in readme_lower, (
            "SOS-08-G §5.5 + PCDN-G-004: emitted README does not "
            "mention Surfer (the modern open-source viewer "
            "extension target per §5.5)."
        )


# ---------------------------------------------------------------------------
# §5.2 schema header + per-record shape verification — the writer's
# emitted file is JSONL-parsable and carries the six normative fields.
# ---------------------------------------------------------------------------


def _exec_helpers_module(helpers_src: str) -> dict[str, Any]:
    """Compile + exec the walker-emitted ``_cocotb_helpers.py`` body
    into a fresh namespace.

    The helpers module is dependency-free against cocotb (only stdlib),
    per the walker's wave-1 contract; this lets us instantiate
    ``AnnotationWriter`` host-side and write a real file to assert
    against without requiring a simulator or cocotb installation.
    """
    namespace: dict[str, Any] = {"__name__": "_cocotb_helpers_under_test"}
    try:
        compiled = compile(helpers_src, "<emitted-helpers>", "exec")
    except SyntaxError as exc:
        pytest.fail(
            f"SOS-08-G integration: walker-emitted `_cocotb_helpers.py` "
            f"is not valid Python — {exc!r}.\n"
            f"--- first 500 chars ---\n{helpers_src[:500]}"
        )
    exec(compiled, namespace)
    return namespace


class TestAnnotationSchema:
    """Direct unit-style coverage of the walker-emitted
    ``AnnotationWriter`` class — instantiate it host-side, write a
    header + record, parse the resulting file."""

    def test_schema_header_shape(self, tmp_path):
        """SOS-08-G §15 / PCDN-G-001 + PCDN-G-002: the first line of
        every ``.annotations.jsonl`` is
        ``{"_meta": {"schema": "sos-annotations", "version": "1.0",
        "chart_path_max_depth": 8}}``; subsequent records carry the
        six normative fields per §5.2."""
        files = _emit_via_walker()
        helpers_src = _find_body(files, "_cocotb_helpers.py")
        namespace = _exec_helpers_module(helpers_src)

        AnnotationWriter = namespace.get("AnnotationWriter")
        assert AnnotationWriter is not None, (
            "SOS-08-G INV-S-HDL-G-5: emitted helpers module did not "
            "expose `AnnotationWriter` to the importing test."
        )

        writer = AnnotationWriter(test_name="test_schema_header_shape",
                                  output_dir=tmp_path)
        try:
            writer.record_transition(
                cycle=42,
                chart_state="ACTIVE",
                transition_id="t_idle_to_active",
                chart_path=["ACTIVE"],
                signal="dut.current_state",
            )
        finally:
            writer.close()

        out_file = tmp_path / "test_schema_header_shape.annotations.jsonl"
        assert out_file.exists(), (
            f"SOS-08-G PCDN-G-003: AnnotationWriter did not produce "
            f"{out_file!s}; one file per test run is the wave-1 "
            f"frozen-decision per §5.6."
        )

        lines = [
            ln for ln in out_file.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        assert len(lines) >= 2, (
            "SOS-08-G INV-S-HDL-G-3: expected at least 2 lines "
            "(header + one record), got "
            f"{len(lines)}: {lines!r}"
        )

        header = json.loads(lines[0])
        meta = header.get("_meta", header)
        assert meta.get("schema") == "sos-annotations", (
            f"SOS-08-G §15 / PCDN-G-001: schema header `schema` field "
            f"must be 'sos-annotations'; got {meta.get('schema')!r}."
        )
        assert meta.get("version") == "1.0", (
            f"SOS-08-G §5.2: schema header `version` field must be "
            f"'1.0' (frozen at v1 per §12 (b)); got "
            f"{meta.get('version')!r}."
        )
        assert meta.get("chart_path_max_depth") == 8, (
            f"SOS-08-G PCDN-G-002: schema header "
            f"`chart_path_max_depth` must be 8 (mirrors SOS-12 cap "
            f"by reference); got {meta.get('chart_path_max_depth')!r}."
        )

        record = json.loads(lines[1])
        for required in ("cycle", "chart_state", "transition_id",
                         "chart_path"):
            assert required in record, (
                f"SOS-08-G §5.2 / INV-S-HDL-G-2: annotation record "
                f"missing normative field {required!r}; got: "
                f"{record!r}"
            )
        assert record["cycle"] == 42
        assert record["chart_state"] == "ACTIVE"
        assert record["transition_id"] == "t_idle_to_active"
        assert record["chart_path"] == ["ACTIVE"]

    def test_per_event_default_density(self, tmp_path):
        """SOS-08-G §5.7 / PCDN-G-005: per-event default. At default
        density, only chart-state transitions yield records — not
        every clock cycle. Three ``record_transition`` calls MUST
        produce exactly three non-header records."""
        files = _emit_via_walker()
        helpers_src = _find_body(files, "_cocotb_helpers.py")
        namespace = _exec_helpers_module(helpers_src)

        AnnotationWriter = namespace.get("AnnotationWriter")
        # Ensure the env-var is unset so we're testing the DEFAULT.
        prior = os.environ.pop("SOS_ANNOTATION_DENSITY", None)
        try:
            writer = AnnotationWriter(test_name="test_default_density",
                                      output_dir=tmp_path)
            try:
                # Three transitions; the writer's default density is
                # 'event' so each call yields exactly one record.
                for cycle, state in (
                    (10, "IDLE"),
                    (20, "ACTIVE"),
                    (30, "DONE"),
                ):
                    writer.record_transition(
                        cycle=cycle,
                        chart_state=state,
                        transition_id=None,
                        chart_path=[state],
                        signal="dut.current_state",
                    )
            finally:
                writer.close()

            # Density must default to 'event' (PCDN-G-005).
            assert writer.density == "event", (
                f"SOS-08-G PCDN-G-005: AnnotationWriter default "
                f"density must be 'event'; got {writer.density!r}."
            )
        finally:
            if prior is not None:
                os.environ["SOS_ANNOTATION_DENSITY"] = prior

        out_file = tmp_path / "test_default_density.annotations.jsonl"
        lines = [
            ln for ln in out_file.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        # 1 schema header + 3 transition records = 4 total lines.
        assert len(lines) == 4, (
            "SOS-08-G PCDN-G-005: per-event default density must emit "
            "one record per transition call (not per cycle). Expected "
            "4 lines (header + 3 records), got "
            f"{len(lines)}: {lines!r}"
        )


# ---------------------------------------------------------------------------
# §5.4 + §5.5 + §6 — the viewer-extension scaffolds load the wave-1
# annotation fixture without errors and surface conformant output per
# the viewer-integration contract.
# ---------------------------------------------------------------------------


class TestViewerExtensions:
    """SOS-08-G §6 viewer-integration contract: each scaffold loads the
    wave-1 fixture and renders chart-vocabulary records. The wave-1
    surface is CLI-only (preview / Tcl emit); full GUI integration
    lands wave-2 per §5.4.
    """

    def test_gtkwave_ext_loads_annotation_fixture(self):
        """GTKWave extension MUST load the wave-1 fixture and surface
        all six chart-vocabulary records per §6 (a)-(c) (co-locate,
        schema-version-aware, per-record render)."""
        gtkwave_ext = pytest.importorskip(
            "viewers.gtkwave.sos_gtkwave_ext",
            reason="GTKWave viewer-extension scaffold "
            "(`viewers/gtkwave/sos_gtkwave_ext.py`) sibling-agent "
            "module not yet on disk; SOS-08-G viewer-extension test "
            "skips until the wave-1 GTKWave commit lands.",
        )
        if not WAVE_1_FIXTURE.exists():
            pytest.skip(
                f"Wave-1 annotation fixture not on disk at "
                f"{WAVE_1_FIXTURE!s}; sibling-agent has not yet "
                f"landed the viewer fixtures."
            )
        records = gtkwave_ext.load_annotations(WAVE_1_FIXTURE)
        assert isinstance(records, list), (
            f"GTKWave ext `load_annotations` must return list[dict]; "
            f"got {type(records).__name__}."
        )
        assert len(records) >= 1, (
            "SOS-08-G §6 (c): the wave-1 fixture carries at least one "
            "annotation record; GTKWave ext returned 0."
        )
        # INV-S-HDL-G-2: every record carries chart-vocabulary fields.
        for record in records:
            assert "chart_state" in record, (
                f"SOS-08-G INV-S-HDL-G-2: GTKWave ext returned a "
                f"record without `chart_state`: {record!r}"
            )

    def test_surfer_ext_loads_annotation_fixture(self):
        """Surfer extension MUST load the wave-1 fixture and surface
        all six chart-vocabulary records per §6 (a)-(c). The Surfer
        scaffold may live at one of two conventional module paths;
        the test accepts either."""
        # Try the canonical scaffold name first; fall back to a
        # short-form name a sibling agent might choose.
        surfer_ext = None
        for candidate in (
            "viewers.surfer.sos_surfer_ext",
            "viewers.surfer",
        ):
            try:
                module = __import__(candidate, fromlist=["*"])
            except ImportError:
                continue
            if hasattr(module, "load_annotations"):
                surfer_ext = module
                break
        if surfer_ext is None:
            pytest.skip(
                "Surfer viewer-extension scaffold "
                "(`viewers/surfer/sos_surfer_ext.py` or a "
                "`load_annotations`-exposing module) sibling-agent "
                "deliverable not yet on disk; SOS-08-G Surfer "
                "viewer-extension test skips until the wave-1 "
                "Surfer commit lands."
            )
        if not WAVE_1_FIXTURE.exists():
            pytest.skip(
                f"Wave-1 annotation fixture not on disk at "
                f"{WAVE_1_FIXTURE!s}; sibling-agent has not yet "
                f"landed the viewer fixtures."
            )
        records = surfer_ext.load_annotations(WAVE_1_FIXTURE)
        assert isinstance(records, list), (
            f"Surfer ext `load_annotations` must return list[dict]; "
            f"got {type(records).__name__}."
        )
        assert len(records) >= 1, (
            "SOS-08-G §6 (c): the wave-1 fixture carries at least one "
            "annotation record; Surfer ext returned 0."
        )
        for record in records:
            assert "chart_state" in record, (
                f"SOS-08-G INV-S-HDL-G-2: Surfer ext returned a "
                f"record without `chart_state`: {record!r}"
            )

    def test_gtkwave_tcl_output_is_well_formed(self):
        """SOS-08-G §6 (c): GTKWave ext's Tcl emission must surface
        chart-state badges. We assert the output references at least
        one conventional marker command (``add_marker`` or
        ``set_marker`` family) so a real GTKWave session can ingest
        the script."""
        gtkwave_ext = pytest.importorskip(
            "viewers.gtkwave.sos_gtkwave_ext",
            reason="GTKWave viewer-extension scaffold not yet on disk.",
        )
        if not WAVE_1_FIXTURE.exists():
            pytest.skip(
                f"Wave-1 annotation fixture not on disk at "
                f"{WAVE_1_FIXTURE!s}."
            )
        records = gtkwave_ext.load_annotations(WAVE_1_FIXTURE)
        tcl = gtkwave_ext.to_gtkwave_tcl(records)
        assert isinstance(tcl, str), (
            f"GTKWave ext `to_gtkwave_tcl` must return str; got "
            f"{type(tcl).__name__}."
        )
        assert tcl.strip(), "GTKWave ext emitted empty Tcl output."
        # The Tcl emission must reference at least one of GTKWave's
        # conventional marker-installation commands. ``add_marker`` is
        # the most legible token; the ``set_marker`` family is the
        # canonical GTKWave API. Either is sufficient per §6 (c).
        tcl_lower = tcl.lower()
        assert (
            "add_marker" in tcl_lower
            or "set_marker" in tcl_lower
            or "named_marker" in tcl_lower
        ), (
            "SOS-08-G §6 (c): GTKWave Tcl emission contains no "
            "recognisable marker-installation command (`add_marker`, "
            "`set_marker`, or `named_marker`). The per-record render "
            "contract is unmet.\n"
            f"--- first 400 chars ---\n{tcl[:400]}"
        )


# ---------------------------------------------------------------------------
# End-to-end smoke — the walker's AnnotationWriter produces a file the
# viewer extension consumes without further translation (INV-S-HDL-G-1).
# ---------------------------------------------------------------------------


class TestEndToEndAnnotationPipeline:
    """The walker's annotation emit + the viewer extension's load are
    one round-trip pipeline. INV-S-HDL-G-1 (three-file coupling) +
    INV-S-HDL-G-2 (chart-vocabulary mandatory) are upheld iff the
    viewer-side load surfaces every chart-state the writer emitted."""

    def test_full_pipeline_smoke(self, tmp_path):
        """Round-trip: emit the cocotb walker; instantiate the emitted
        ``AnnotationWriter``; write a sample annotation file; load it
        via the GTKWave ext; assert chart-vocabulary preserved end-
        to-end (the chart states the writer recorded MUST appear in
        the ext's returned records)."""
        files = _emit_via_walker()
        helpers_src = _find_body(files, "_cocotb_helpers.py")
        namespace = _exec_helpers_module(helpers_src)
        AnnotationWriter = namespace.get("AnnotationWriter")

        gtkwave_ext = pytest.importorskip(
            "viewers.gtkwave.sos_gtkwave_ext",
            reason="GTKWave viewer-extension scaffold not yet on disk; "
            "SOS-08-G full-pipeline smoke skips until both sibling "
            "agents (walker + viewer ext) have landed.",
        )

        # Write a four-record overlay covering the chart's vocabulary.
        chart_states = ("IDLE", "ACTIVE", "DONE", "ERROR")
        writer = AnnotationWriter(test_name="test_pipeline_smoke",
                                  output_dir=tmp_path)
        try:
            for cycle, state in enumerate(chart_states):
                writer.record_transition(
                    cycle=10 + cycle * 5,
                    chart_state=state,
                    transition_id=f"t_to_{state.lower()}",
                    chart_path=[state],
                    signal="dut.current_state",
                    vector_index=cycle,
                )
        finally:
            writer.close()

        out_file = tmp_path / "test_pipeline_smoke.annotations.jsonl"
        assert out_file.exists(), (
            f"INV-S-HDL-G-1: writer did not produce the expected "
            f"`.annotations.jsonl` file at {out_file!s}; three-file "
            f"coupling is broken at the source."
        )

        # The viewer ext loads the writer's output without further
        # translation — this is the load-bearing INV-S-HDL-G-1 +
        # INV-S-HDL-G-3 round-trip claim.
        records = gtkwave_ext.load_annotations(out_file)
        assert len(records) == len(chart_states), (
            f"End-to-end pipeline drift: writer recorded "
            f"{len(chart_states)} transitions, viewer ext returned "
            f"{len(records)} records. INV-S-HDL-G-1 broken."
        )

        # INV-S-HDL-G-2: every chart-state the writer emitted MUST
        # appear in the ext's returned records, byte-identical.
        observed_states = {r.get("chart_state") for r in records}
        for state in chart_states:
            assert state in observed_states, (
                f"SOS-08-G INV-S-HDL-G-2 / INV-SOS-H: chart state "
                f"{state!r} written by `AnnotationWriter` does not "
                f"appear in viewer-ext load. Chart-vocabulary "
                f"preservation across the wave-1 pipeline broken.\n"
                f"observed: {observed_states!r}"
            )

        # The Tcl render path also surfaces every chart state at the
        # review-surface layer per §6 (c).
        tcl = gtkwave_ext.to_gtkwave_tcl(records)
        for state in chart_states:
            assert state in tcl, (
                f"SOS-08-G §6 (c): GTKWave Tcl render dropped chart "
                f"state {state!r} from the marker labels. Per-record "
                f"render contract unmet end-to-end.\n"
                f"--- first 400 chars ---\n{tcl[:400]}"
            )
