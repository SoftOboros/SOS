# SOS-08-G GTKWave overlay extension (wave-3c)

GTKWave Tcl extension that renders [SOS-08-G](../../../../docs/concepts/SOS-08-G-CONCEPTS.md)
annotation-overlay (`.annotations.jsonl`) files as chart-state named
markers + per-chart_path comment-trace overlay tracks + invariant-fire
highlights on the waveform timeline.

This directory ships **two complementary surfaces**:

| File | Role |
|------|------|
| `sos_overlay.tcl` | Loadable GTKWave Tcl plugin (wave-3c GUI integration). Source from inside GTKWave or pass via `--script`. |
| `sos_gtkwave_ext.py` | Python CLI scaffold + Tcl emitter. Standalone preview + the actual JSONL→Tcl converter the Tcl plugin shells out to. |

## Status

🟢 **Wave-3c landed 2026-05-24.** The Tcl plugin co-locates the
overlay via the wave-3b `_meta.waveform_prefix` field and falls back
to the wave-1 same-prefix-as-overlay convention when absent.

## Install

### Quick install (per-user)

Copy `sos_overlay.tcl` + `sos_gtkwave_ext.py` into a directory on your
system, then load the Tcl from GTKWave:

```sh
# Option A: CLI --script flag (preferred for cocotb-classic build dirs)
gtkwave --script /path/to/sos_overlay.tcl sim_build/test_demo_fsm.fst

# Option B: GUI File menu
gtkwave sim_build/test_demo_fsm.fst
# Then: File → Read Tcl Script... → /path/to/sos_overlay.tcl
```

### Persistent install (per-system)

Add the script-load line to `~/.gtkwaverc` so it auto-runs on every
GTKWave launch:

```
# ~/.gtkwaverc
exec_command sos_overlay_path = source /path/to/sos_overlay.tcl
```

(The exact `.gtkwaverc` directive depends on the GTKWave version;
consult `man gtkwaverc`.)

## How it works

1. The Tcl plugin reads the currently-loaded waveform's path via
   `gtkwave::getDumpFileName`.
2. It scans the same directory for `.annotations.jsonl` overlay
   files whose `_meta.waveform_prefix` matches the waveform's
   filename stem (wave-3b co-locate semantics, falling back to the
   wave-1 same-prefix convention when absent).
3. For each matching overlay, it shells out to `sos_gtkwave_ext.py
   --format gtkwave <overlay>` and `eval`s the emitted Tcl marker
   commands.
4. The emit produces:
   - **Named markers A..Z** at each transition cycle (keyboard-
     navigable via GTKWave's marker shortcuts). Capped at 26.
   - **Per-chart_path comment-trace overlay tracks** rendering
     every record as a labelled badge in a dedicated pane
     (no cap; §6 (d) chart-path navigation).
   - **A `sos:invariants` overlay track** for invariant-fire records
     (§6 (e) invariant-fire highlighting).

## SOS-08-G §6 conformance gates

| Gate | Description | Status |
|------|-------------|--------|
| (a) MUST | Co-locate overlay via `_meta.waveform_prefix` | ✅ wave-3c (`sos_overlay_find_overlays`) |
| (b) MUST | Schema-version-aware | ✅ wave-3c (Python ext validates header) |
| (c) MUST | Per-record render | ✅ wave-3c (named markers + comment-trace badges) |
| (d) SHOULD | Chart-path navigation | ✅ wave-3c (per-chart_path overlay tracks) |
| (e) SHOULD | Invariant-fire highlighting | ✅ wave-3c (`sos:invariants` track) |
| (f) SHOULD | Vector-citation drill-down | ⏸ wave-3c-future (requires GTKWave link-back hook) |

## Environment variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `SOS_GTKWAVE_PYTHON` | Override the python interpreter used by `exec` | `python3` |
| `SOS_OVERLAY_VERBOSE` | Print diagnostic lines from the Tcl plugin | unset |

## Standalone Python preview

Without GTKWave installed you can still preview an overlay:

```sh
python3 sos_gtkwave_ext.py path/to/test.annotations.jsonl
# → human-readable cycle-by-cycle table on stdout
```

The same script emits the Tcl marker commands:

```sh
python3 sos_gtkwave_ext.py --format gtkwave path/to/test.annotations.jsonl
# → Tcl commands the Tcl plugin would source
```

## License

MIT (matches the SOS repo root licence).
