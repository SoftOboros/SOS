"""SOS-08-G wave-3c — full GUI integration test surface.

Covers:
  - `sos_overlay.tcl` loadable plugin file structure + parse-cleanliness.
  - `sos_gtkwave_ext.to_gtkwave_tcl` comment-trace overlay tracks
    (§6 (d) chart-path navigation) + invariant-fire track (§6 (e)).
  - `sos_surfer_ext.to_surfer_commands` overlay-track emit (§6 (d/e)).
  - `sos-surfer-plugin/` Rust crate scaffold: Cargo.toml, src/lib.rs,
    surfer-plugin.toml, README.md present + well-formed.
  - `viewers/README.md` unified install guide + per-viewer README.md
    presence.

@spec  SOS-08-G-CONCEPTS.md §6 (viewer integration contract).
@spec  SOS-08-G-CONCEPTS.md §15 wave-3c (2026-05-24).
@spec  PCDN-G-004 (in-subrepo distribution location).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_VIEWERS = Path(__file__).resolve().parent.parent
if str(_VIEWERS) not in sys.path:
    sys.path.insert(0, str(_VIEWERS))

from gtkwave.sos_gtkwave_ext import (  # noqa: E402
    load_annotations,
    to_gtkwave_tcl,
)
from surfer.sos_surfer_ext import to_surfer_commands  # noqa: E402

_FIXTURE = _VIEWERS / "tests" / "fixtures" / "example_annotations.jsonl"
_GTKWAVE_DIR = _VIEWERS / "gtkwave"
_SURFER_PLUGIN = _VIEWERS / "surfer" / "sos-surfer-plugin"


# ---------------------------------------------------------------------------
# 1. sos_overlay.tcl loadable plugin file
# ---------------------------------------------------------------------------


class TestGtkwaveTclPlugin:
    """`tools/sos-codegen/viewers/gtkwave/sos_overlay.tcl` —
    loadable Tcl extension that hooks GTKWave's command surface and
    installs chart-state markers from an `.annotations.jsonl` overlay.
    """

    def _tcl(self) -> str:
        return (_GTKWAVE_DIR / "sos_overlay.tcl").read_text(encoding="utf-8")

    def test_tcl_file_exists(self):
        assert (_GTKWAVE_DIR / "sos_overlay.tcl").exists()

    def test_tcl_declares_proc_main(self):
        """The plugin's auto-invoked entry point MUST be named
        `sos_overlay_main` so users can re-trigger it manually after
        loading a different waveform without restarting GTKWave."""
        assert "proc sos_overlay_main" in self._tcl()

    def test_tcl_finds_overlays_by_meta_prefix(self):
        """Wave-3b co-locate semantics: the plugin MUST consult
        `_meta.waveform_prefix` before falling back to the wave-1
        same-prefix convention."""
        tcl = self._tcl()
        assert "proc sos_overlay_find_overlays" in tcl
        assert "waveform_prefix" in tcl
        # Wave-1 fallback path documented in-line.
        assert "same-prefix" in tcl.lower() or "wave-1" in tcl.lower()

    def test_tcl_shells_out_to_python_ext(self):
        """The plugin shells out to `sos_gtkwave_ext.py --format
        gtkwave` to convert JSONL → Tcl. Python ext path resolves
        from `info script`, so the plugin MUST NOT hard-code an
        absolute path."""
        tcl = self._tcl()
        assert "info script" in tcl
        assert "sos_gtkwave_ext.py" in tcl
        assert "--format" in tcl
        assert "gtkwave" in tcl

    def test_tcl_honours_verbose_env(self):
        """`SOS_OVERLAY_VERBOSE` env var gates diagnostic prints so the
        user can quiet the plugin in production GTKWave sessions."""
        assert "SOS_OVERLAY_VERBOSE" in self._tcl()

    def test_tcl_honours_python_override_env(self):
        """`SOS_GTKWAVE_PYTHON` env var overrides the python
        interpreter — necessary for users on systems with python2 still
        in PATH ahead of python3."""
        assert "SOS_GTKWAVE_PYTHON" in self._tcl()

    def test_tcl_skip_auto_main_supported(self):
        """Allow callers (GUI-load scenarios) to suppress the auto-
        invocation by setting `sos_overlay_skip_auto_main` before
        sourcing — useful when the user wants to set
        `sos_overlay_dump_path` manually first."""
        assert "sos_overlay_skip_auto_main" in self._tcl()

    def test_tcl_cites_spec_sections(self):
        """The Tcl plugin MUST cite the SOS-08-G spec sections it
        implements so a future reviewer can trace the conformance
        gates."""
        tcl = self._tcl()
        assert "SOS-08-G" in tcl
        assert "§5.2" in tcl or "§6" in tcl
        assert "INV-S-HDL-G" in tcl

    def test_tcl_balanced_braces(self):
        """Sanity check: the Tcl source MUST be brace-balanced.
        Imbalanced braces would prevent GTKWave from loading the
        plugin at all."""
        tcl = self._tcl()
        # Count braces outside of strings (rough heuristic — Tcl proc
        # bodies use { and } as the dominant structure, comments
        # don't carry stray braces in this file).
        opens = tcl.count("{")
        closes = tcl.count("}")
        assert opens == closes, (
            f"brace mismatch: {opens} opens vs {closes} closes"
        )


# ---------------------------------------------------------------------------
# 2. to_gtkwave_tcl comment-trace overlay tracks (§6 (d), §6 (e))
# ---------------------------------------------------------------------------


class TestGtkwaveTclEmitWave3c:
    """`to_gtkwave_tcl` — wave-3c (2026-05-24) extends the emit to
    include `gtkwave::addCommentTracesFromList` overlay-track calls
    per §6 (d) + §6 (e)."""

    def _records(self) -> list:
        return load_annotations(_FIXTURE)

    def test_emits_comment_trace_per_chart_path(self):
        """One `gtkwave::addCommentTracesFromList` call per unique
        `chart_path` value. The fixture has two distinct paths
        (`/orchestrator` and `/orchestrator/syscalls/sem.take`) so the
        emit MUST carry two such calls."""
        tcl = to_gtkwave_tcl(self._records())
        # Count addCommentTracesFromList calls explicitly (multiple
        # may appear, including the invariants track).
        path_tracks = re.findall(
            r'gtkwave::addCommentTracesFromList "sos:/orchestrator',
            tcl,
        )
        assert len(path_tracks) >= 2

    def test_emits_invariants_track(self):
        """Fixture record 5 carries `invariant_id="INV-S-CHART-3"` —
        the wave-3c emit MUST install a dedicated `sos:invariants`
        comment-trace overlay track per §6 (e)."""
        tcl = to_gtkwave_tcl(self._records())
        assert 'gtkwave::addCommentTracesFromList "sos:invariants"' in tcl
        assert "mark_invariant" in tcl
        assert "INV-S-CHART-3" in tcl

    def test_named_markers_still_emitted(self):
        """Wave-1 named markers A..Z must remain — wave-3c is additive,
        not a replacement."""
        tcl = to_gtkwave_tcl(self._records())
        assert "gtkwave::/Edit/Set_Named_Marker A" in tcl
        assert "add_marker A" in tcl

    def test_overlay_track_carries_chart_state_labels(self):
        """The comment-trace track entries MUST carry the
        `chart_state` field (not just raw RTL signal traces) per
        INV-S-HDL-G-2 / §6 (c)."""
        tcl = to_gtkwave_tcl(self._records())
        # Fixture chart states.
        for state in ["idle", "arming", "running", "halted"]:
            assert state in tcl

    def test_chart_path_string_normalised(self):
        """`chart_path` may arrive as either a list (wave-2 walk) or a
        string (wave-1 shape). The emit MUST normalise both into a
        slash-joined `/seg/seg/...` track name."""
        records = [
            {"cycle": 0, "chart_state": "x", "transition_id": None,
             "chart_path": ["chart", "outer", "inner"], "region": None},
        ]
        tcl = to_gtkwave_tcl(records)
        assert "sos:/chart/outer/inner" in tcl


# ---------------------------------------------------------------------------
# 3. to_surfer_commands overlay-track emit (§6 (d), §6 (e))
# ---------------------------------------------------------------------------


class TestSurferCommandEmitWave3c:
    """`to_surfer_commands` — wave-3c (2026-05-24) extends the emit
    with `add_overlay_track` + `add_overlay_event` calls per §6 (d/e)."""

    def _records(self) -> list:
        return load_annotations(_FIXTURE)

    def test_emits_overlay_track_per_chart_path(self):
        cmds = to_surfer_commands(self._records())
        assert 'add_overlay_track "sos:/orchestrator"' in cmds
        assert "add_overlay_track" in cmds
        # At least one per-chart_path track.
        assert cmds.count("add_overlay_track") >= 2

    def test_emits_invariants_overlay_track(self):
        cmds = to_surfer_commands(self._records())
        assert 'add_overlay_track "sos:invariants"' in cmds
        assert "INV-S-CHART-3" in cmds

    def test_per_record_markers_still_emitted(self):
        """Wave-1 `add_marker` per record must remain."""
        cmds = to_surfer_commands(self._records())
        assert cmds.count("add_marker") >= 1


# ---------------------------------------------------------------------------
# 4. sos-surfer-plugin/ Rust crate scaffold (PCDN-G-004)
# ---------------------------------------------------------------------------


class TestSurferPluginCrateScaffold:
    """Scaffold validation only — building the actual WASM artifact
    requires `rustup target add wasm32-unknown-unknown` and is
    deferred to CI (or manual build per the crate's README). Tests
    here validate the source-tree shape + manifest structure."""

    def test_cargo_toml_exists(self):
        assert (_SURFER_PLUGIN / "Cargo.toml").exists()

    def test_cargo_toml_parses(self):
        try:
            import tomllib
        except ImportError:  # pragma: no cover - Python < 3.11
            pytest.skip("tomllib not available")
        text = (_SURFER_PLUGIN / "Cargo.toml").read_text(encoding="utf-8")
        data = tomllib.loads(text)
        assert data["package"]["name"] == "sos-surfer-plugin"
        # cdylib for the WASM build target.
        assert "cdylib" in data["lib"]["crate-type"]
        # wit-bindgen optional dep gated on the `wasm` feature.
        assert "wit-bindgen" in data["dependencies"]
        assert data["features"]["wasm"] == ["wit-bindgen"]

    def test_cargo_toml_declares_surfer_metadata(self):
        """The `[package.metadata.surfer]` table names the plugin so
        Surfer's host can route overlays to it without prompting."""
        try:
            import tomllib
        except ImportError:  # pragma: no cover
            pytest.skip("tomllib not available")
        text = (_SURFER_PLUGIN / "Cargo.toml").read_text(encoding="utf-8")
        data = tomllib.loads(text)
        meta = data["package"]["metadata"]["surfer"]
        assert meta["schema"] == "sos-08-g/annotations"
        assert meta["schema-version"] == "1.0"

    def test_lib_rs_exists(self):
        assert (_SURFER_PLUGIN / "src" / "lib.rs").exists()

    def test_lib_rs_declares_schema_constants(self):
        """The Rust constants MUST match the Python constants by hand
        (cross-language source-of-truth lockstep at schema-version
        bumps; §15 amendment is the gate)."""
        src = (_SURFER_PLUGIN / "src" / "lib.rs").read_text(encoding="utf-8")
        assert 'SCHEMA_NAME: &str = "sos-08-g/annotations"' in src
        assert 'SCHEMA_VERSION: &str = "1.0"' in src
        assert "CHART_PATH_MAX_DEPTH: usize = 8" in src

    def test_lib_rs_declares_parse_overlay(self):
        """`parse_overlay(content) -> Result<(Header, Vec<Record>), _>`
        is the schema-validating entry point per §6 (b)."""
        src = (_SURFER_PLUGIN / "src" / "lib.rs").read_text(encoding="utf-8")
        assert "pub fn parse_overlay" in src
        assert "SCHEMA_NAME" in src
        assert "BadSchema" in src

    def test_lib_rs_declares_render_commands(self):
        """`render_commands(records) -> Vec<SurferCommand>` is the
        host-facing emit entry point."""
        src = (_SURFER_PLUGIN / "src" / "lib.rs").read_text(encoding="utf-8")
        assert "pub fn render_commands" in src
        assert "enum SurferCommand" in src
        # The four emit shapes per §6 (c/d/e).
        for variant in (
            "Marker",
            "AddOverlayTrack",
            "AddOverlayEvent",
            "MarkInvariant",
        ):
            assert variant in src

    def test_surfer_plugin_toml_exists(self):
        assert (_SURFER_PLUGIN / "surfer-plugin.toml").exists()

    def test_surfer_plugin_toml_parses(self):
        try:
            import tomllib
        except ImportError:  # pragma: no cover
            pytest.skip("tomllib not available")
        text = (_SURFER_PLUGIN / "surfer-plugin.toml").read_text(
            encoding="utf-8"
        )
        data = tomllib.loads(text)
        assert data["plugin"]["name"] == "sos-surfer-plugin"
        # Schema fields drive Surfer host's overlay routing.
        assert data["schema"]["name"] == "sos-08-g/annotations"
        assert data["schema"]["version"] == "1.0"
        # Discovery modes match SOS-08-G §6 (a) co-locate semantics
        # (wave-3b: meta-waveform-prefix primary + same-prefix fallback).
        assert "meta-waveform-prefix" in data["discovery"]["modes"]
        assert "same-prefix-fallback" in data["discovery"]["modes"]

    def test_surfer_plugin_toml_declares_conformance_features(self):
        try:
            import tomllib
        except ImportError:  # pragma: no cover
            pytest.skip("tomllib not available")
        text = (_SURFER_PLUGIN / "surfer-plugin.toml").read_text(
            encoding="utf-8"
        )
        data = tomllib.loads(text)
        features = data["features"]
        # MUST gates true; SHOULD gates partially true.
        assert features["schema-version-validation"] is True
        assert features["per-record-markers"] is True
        assert features["chart-path-overlay-tracks"] is True
        assert features["invariant-fire-highlighting"] is True
        # SHOULD-gate (f) is wave-3c-future (vector-citation drill-
        # down — requires Surfer link-back API).
        assert features["vector-citation-drilldown"] is False

    def test_readme_exists(self):
        assert (_SURFER_PLUGIN / "README.md").exists()

    def test_readme_documents_build_command(self):
        readme = (_SURFER_PLUGIN / "README.md").read_text(encoding="utf-8")
        assert "wasm32-unknown-unknown" in readme
        assert "cargo build" in readme
        # Host-target check is the no-WASM-toolchain shortcut.
        assert "cargo check" in readme

    def test_readme_documents_install_path(self):
        readme = (_SURFER_PLUGIN / "README.md").read_text(encoding="utf-8")
        assert "surfer/plugins" in readme


# ---------------------------------------------------------------------------
# 5. README files (PCDN-G-004 distribution + viewer integration docs)
# ---------------------------------------------------------------------------


class TestWave3cReadmes:
    """Wave-3c ships three READMEs documenting the GUI install paths."""

    def test_unified_viewers_readme_exists(self):
        assert (_VIEWERS / "README.md").exists()

    def test_unified_readme_lists_both_viewers(self):
        readme = (_VIEWERS / "README.md").read_text(encoding="utf-8")
        assert "GTKWave" in readme
        assert "Surfer" in readme
        assert "PCDN-G-004" in readme

    def test_unified_readme_documents_conformance_matrix(self):
        readme = (_VIEWERS / "README.md").read_text(encoding="utf-8")
        # Both viewers' gate-by-gate status.
        for gate in ("(a) MUST", "(b) MUST", "(c) MUST", "(d) SHOULD", "(e) SHOULD"):
            assert gate in readme

    def test_gtkwave_readme_exists(self):
        assert (_GTKWAVE_DIR / "README.md").exists()

    def test_gtkwave_readme_documents_install_paths(self):
        readme = (_GTKWAVE_DIR / "README.md").read_text(encoding="utf-8")
        assert "gtkwave --script" in readme
        assert "sos_overlay.tcl" in readme


# ---------------------------------------------------------------------------
# 6. wave-3c-future §6 (f) drill-down — data-layer landing
# ---------------------------------------------------------------------------
#
# Wave-3c-future closes the §6 (f) vector-citation drill-down on the
# data-layer side: writer threads `_meta.vector_source` through the
# overlay header; both viewers' emitters render per-record drill-down
# bindings; the Tcl plugin defines `sos_open_vector_at`. The GUI
# invocation layer (host-side link-back call) stays gated on upstream
# viewer-API stability — the wave-3c-future emit is forward-compatible
# with that future stabilisation.

_FIXTURE_VEC = _VIEWERS / "tests" / "fixtures" / "example_with_vector_source.jsonl"


class TestWave3cFutureDrillDownDataLayer:
    """Wave-3c-future writer + emit path for §6 (f)."""

    def test_fixture_present(self):
        assert _FIXTURE_VEC.exists()

    def test_overlay_header_exposes_vector_source(self):
        """`load_overlay_header` returns the `_meta.vector_source`
        field when the overlay declares it."""
        from gtkwave.sos_gtkwave_ext import load_overlay_header
        meta = load_overlay_header(_FIXTURE_VEC)
        assert meta.get("vector_source") == "vectors/0001-two-tasks-yield.json"

    def test_load_overlay_header_omits_field_when_absent(self):
        """Legacy overlay without `_meta.vector_source` returns a
        header where the field is absent — drill-down emit MUST then
        be skipped (wave-3c emit byte-identity preserved)."""
        from gtkwave.sos_gtkwave_ext import load_overlay_header
        meta = load_overlay_header(_FIXTURE)
        assert "vector_source" not in meta


class TestWave3cFutureGtkwaveTclEmit:
    """`to_gtkwave_tcl(..., vector_source=...)` emits the drill-down
    section."""

    def _tcl(self):
        records = load_annotations(_FIXTURE_VEC)
        return to_gtkwave_tcl(
            records,
            vector_source="vectors/0001-two-tasks-yield.json",
        )

    def test_emit_sets_sos_vector_source_global(self):
        tcl = self._tcl()
        assert (
            'set ::sos_vector_source "vectors/0001-two-tasks-yield.json"'
            in tcl
        )

    def test_emit_has_drill_down_section_header(self):
        tcl = self._tcl()
        assert "vector-citation drill-down" in tcl

    def test_emit_one_mark_vector_citation_per_vector_record(self):
        """Fixture has 4 records with `vector_index` — emit MUST
        produce one `mark_vector_citation` per record."""
        tcl = self._tcl()
        count = len(re.findall(r"^mark_vector_citation ", tcl, re.MULTILINE))
        assert count == 4

    def test_emit_mark_vector_citation_includes_cycle_index_and_state(self):
        """Each `mark_vector_citation` line names cycle, vector_index,
        and chart_state so a downstream Tcl hook can build a chart-
        vocabulary tooltip without re-parsing the overlay."""
        tcl = self._tcl()
        # The cycle=12, vector_index=0, chart_state="arming" record.
        assert 'mark_vector_citation 12 0 "arming"' in tcl
        # The cycle=102, vector_index=3, chart_state="acquired" record.
        assert 'mark_vector_citation 102 3 "acquired"' in tcl

    def test_emit_clears_global_when_vector_source_none(self):
        """When `vector_source=None` AND records carry `vector_index`,
        emit MUST clear the global so a stale path from a previous
        overlay install doesn't bleed into the new overlay's
        drill-down resolution."""
        records = load_annotations(_FIXTURE_VEC)
        tcl = to_gtkwave_tcl(records, vector_source=None)
        assert 'set ::sos_vector_source ""' in tcl

    def test_emit_omits_section_when_no_vector_source_and_no_vector_records(self):
        """An overlay with neither `vector_source` nor any
        `vector_index`-bearing records does NOT emit the drill-down
        section at all — wave-3c emit shape byte-preserved."""
        records = [
            {
                "cycle": 0,
                "signal": "s",
                "chart_state": "idle",
                "transition_id": None,
                "chart_path": "/orchestrator",
                "region": None,
            }
        ]
        tcl = to_gtkwave_tcl(records, vector_source=None)
        assert "vector-citation drill-down" not in tcl

    def test_legacy_signature_omits_drill_down_section(self):
        """`to_gtkwave_tcl(records)` (no vector_source kwarg) emits the
        wave-3c byte-identity result — drill-down section appears only
        when records carry vector_index AND the section is opened by
        the `or vector_records` clause; in this case fixture HAS
        vector_index records so the section emits but with a cleared
        global (matches the previous test's contract)."""
        records = load_annotations(_FIXTURE_VEC)
        tcl = to_gtkwave_tcl(records)
        # No vector_source threading → global is cleared, but section
        # opens because the records carry vector_index (lets a
        # downstream hook surface "this overlay has vectorable badges
        # but no source path" as a visible diagnostic).
        assert 'set ::sos_vector_source ""' in tcl


class TestWave3cFutureSurferCommandEmit:
    """`to_surfer_commands(..., vector_source=...)` emits the
    drill-down section."""

    def _cmds(self):
        records = load_annotations(_FIXTURE_VEC)
        return to_surfer_commands(
            records,
            vector_source="vectors/0001-two-tasks-yield.json",
        )

    def test_emit_sets_vector_source(self):
        cmds = self._cmds()
        assert (
            'set_vector_source "vectors/0001-two-tasks-yield.json"' in cmds
        )

    def test_emit_one_open_vector_source_per_record(self):
        cmds = self._cmds()
        count = len(re.findall(r"^open_vector_source ", cmds, re.MULTILINE))
        assert count == 4

    def test_emit_open_vector_source_carries_chart_state(self):
        cmds = self._cmds()
        # Record cycle=12, vector_index=0, chart_state="arming".
        assert (
            'open_vector_source "vectors/0001-two-tasks-yield.json" 0 12 "arming"'
            in cmds
        )

    def test_legacy_signature_omits_drill_down_commands(self):
        """`to_surfer_commands(records)` without vector_source emits
        no `open_vector_source` lines — wave-3c byte-identity for
        legacy callers."""
        records = load_annotations(_FIXTURE_VEC)
        cmds = to_surfer_commands(records)
        assert "open_vector_source" not in cmds


class TestWave3cFutureGtkwaveTclPluginProc:
    """The `sos_overlay.tcl` plugin gains the `sos_open_vector_at` proc."""

    def test_proc_declared(self):
        src = (_GTKWAVE_DIR / "sos_overlay.tcl").read_text(encoding="utf-8")
        assert re.search(
            r"^proc\s+sos_open_vector_at\s+\{", src, re.MULTILINE
        )

    def test_proc_consults_sos_vector_source_global(self):
        src = (_GTKWAVE_DIR / "sos_overlay.tcl").read_text(encoding="utf-8")
        assert "::sos_vector_source" in src

    def test_proc_uses_editor_env(self):
        src = (_GTKWAVE_DIR / "sos_overlay.tcl").read_text(encoding="utf-8")
        # The proc consults $env(EDITOR) for the fallback editor.
        assert "env(EDITOR)" in src

    def test_proc_passes_line_hint_to_editor(self):
        """The proc passes a `+<line>` argument so most editors jump
        to the right step in the vector JSON (line N+2 matches the
        typical SOS-03 vector-trace shape)."""
        src = (_GTKWAVE_DIR / "sos_overlay.tcl").read_text(encoding="utf-8")
        assert 'exec $editor "+$line_hint"' in src


class TestWave3cFutureWriterVectorSourceHeader:
    """The cocotb-emitted `AnnotationWriter` accepts `vector_source`
    and writes it into the `_meta` envelope. Verified by exec'ing the
    emitted helpers module + inspecting an instantiated writer's
    on-disk header line."""

    @staticmethod
    def _simple_chart():
        return {
            "initial": "A",
            "state": [
                {"id": "A", "transition": [{"target": "B"}]},
                {"id": "B", "transition": [{"target": "C"}]},
                {"id": "C", "transition": [{"target": "A"}]},
            ],
        }

    @staticmethod
    def _render():
        # Mirror tests/test_transliterate_cocotb.py::_exec_helpers shape.
        sys.path.insert(0, str(_VIEWERS.parent))
        try:
            from transliterate_cocotb import render_target  # noqa: E402
        finally:
            sys.path.pop(0)
        return render_target(
            TestWave3cFutureWriterVectorSourceHeader._simple_chart(),
            {"chart_name": "demo"},
        )

    def _exec_helpers(self):
        files = self._render()
        helpers_src = files["tests/demo/_cocotb_helpers.py"]
        ns: dict = {}
        exec(compile(helpers_src, "_cocotb_helpers.py", "exec"), ns)
        return ns, helpers_src

    def test_annotation_writer_accepts_vector_source_kwarg(self):
        """Wave-3c-future: `AnnotationWriter.__init__` takes a
        `vector_source` kwarg the test body passes through from the
        loaded SOS-03 vector path."""
        ns, _ = self._exec_helpers()
        import inspect
        sig = inspect.signature(ns["AnnotationWriter"].__init__)
        assert "vector_source" in sig.parameters

    def test_header_carries_vector_source_when_provided(
        self, tmp_path, monkeypatch
    ):
        """When the writer is given a `vector_source`, the on-disk
        first-line `_meta` envelope MUST carry it for viewer
        extensions to consult per §6 (f)."""
        monkeypatch.delenv("SOS_WAVEFORM_PREFIX", raising=False)
        monkeypatch.delenv("MODULE", raising=False)
        ns, _ = self._exec_helpers()
        writer = ns["AnnotationWriter"](
            "drill",
            output_dir=tmp_path,
            vector_source="vectors/0001-two-tasks-yield.json",
        )
        writer.close()
        import json as _json
        first_line = (tmp_path / "drill.annotations.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()[0]
        meta = _json.loads(first_line)["_meta"]
        assert meta["vector_source"] == "vectors/0001-two-tasks-yield.json"

    def test_header_omits_vector_source_when_absent(
        self, tmp_path, monkeypatch
    ):
        """Wave-3c byte-identity for legacy callers: without
        `vector_source`, the header MUST NOT carry the field — viewer
        extensions then skip drill-down emit entirely."""
        monkeypatch.delenv("SOS_WAVEFORM_PREFIX", raising=False)
        monkeypatch.delenv("MODULE", raising=False)
        ns, _ = self._exec_helpers()
        writer = ns["AnnotationWriter"]("nodrill", output_dir=tmp_path)
        writer.close()
        import json as _json
        first_line = (tmp_path / "nodrill.annotations.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()[0]
        meta = _json.loads(first_line)["_meta"]
        assert "vector_source" not in meta

    def test_test_body_passes_vector_source_to_writer(self):
        """The generated single-region cocotb test body MUST pass
        `vector_source=str(_VECTORS_DIR / "<vector>.json")` when
        constructing the AnnotationWriter so the SOS-03 vector path
        threads through by construction."""
        files = self._render()
        test_module = next(
            v
            for k, v in files.items()
            if k.endswith("test_demo_fsm.py")
        )
        assert "vector_source=str(_VECTORS_DIR" in test_module
