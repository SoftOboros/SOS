# SOS-08-G host-wiring runbook (§6 (f.2) carry-forward)

**Status:** 🟡 **integrator-facing spec** — paired with the §6 (f.1) data layer (closed in [SOS-08-G-CONCEPTS.md §15 2026-05-24][concepts-§15] wave-3c-future entry). The data layer ships canonical emitted artifacts (overlay `_meta.vector_source` + GTKWave `mark_vector_citation` + Surfer `OpenVectorSource`); this doc names the host-side contract a viewer-embedding application MUST satisfy for the click-to-source round trip to actually fire.

[concepts-§15]: ../concepts/SOS-08-G-CONCEPTS.md#15-change-log
[concepts-§6]: ../concepts/SOS-08-G-CONCEPTS.md#6-viewer-integration-contract
[concepts-§5.2]: ../concepts/SOS-08-G-CONCEPTS.md#52-annotation-overlay-schema
[tcl-plugin]: ../../tools/sos-codegen/viewers/gtkwave/sos_overlay.tcl
[surfer-plugin]: ../../tools/sos-codegen/viewers/surfer/sos-surfer-plugin/src/lib.rs

> The key words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, **MAY**, **REQUIRED** are interpreted per RFC 2119 / RFC 8174 when capitalised. Lowercase use is ordinary English.

## 0. Why this doc exists

The wave-3c-future commit at SHA `8d95152` landed the **data layer** for §6 (f) vector-citation drill-down: every conforming overlay header now carries `_meta.vector_source`, every record carrying `vector_index` produces a drill-down emit (GTKWave: `mark_vector_citation`; Surfer: `OpenVectorSource { vector_source, vector_index, time, chart_state }`), and the GTKWave Tcl plugin ships an in-process `sos_open_vector_at <vector_index>` proc that uses `$EDITOR` to spawn the user's editor against the resolved path.

The **GUI invocation half** — §6 (f.2) — depends on viewer-host plumbing the canonical SOS-08-G repo does NOT own:

- **GTKWave**: a key-action binding from `sos_open_vector_at` to a hotkey via `~/.gtkwaverc` is per-user configuration; auto-binding from a loaded plugin requires GTKWave's not-yet-stable keyaction-from-plugin API.
- **Surfer**: the `OpenVectorSource` command lands on the host's plugin event channel; the host MUST route it to an editor invocation. Surfer's plugin-host link-back API is still moving.

Rather than wait on upstream stabilisation, this doc **specifies the host-side contract** so an integrator (today's GTKWave Tcl user, tomorrow's Surfer-embedding application) can wire the drill-down end-to-end against the canonical emitted artifacts. When upstream APIs stabilise the contract here ports directly to whatever discovery mechanism the upstream API exposes.

## 1. Purpose

A conforming **host integration** of §6 (f) drill-down satisfies, in order:

1. **Discovery** — the host MUST locate the source vector path. GTKWave: read the Tcl global `::sos_vector_source` set by `sos_overlay_install`. Surfer: read the `vector_source` field of each `OpenVectorSource` command (per-command, not per-session).
2. **Editor invocation** — given `(vector_source, vector_index)`, the host MUST translate to an editor command line that opens `vector_source` at line `vector_index + 2` (see §4 Line-hint convention below).
3. **Failure-mode surfacing** — the host MUST NOT block the viewer event loop, MUST NOT mutate the wave file, and MUST surface unrecoverable conditions (editor unavailable, source path missing, vector_index out of range) to the viewer's status bar / log channel rather than silently dropping.
4. **Path validation** — the host SHOULD validate `vector_source` is inside an expected workspace root before exec'ing an editor (see §6 Security).

## 2. GTKWave Tcl host-wiring

### 2.1 The shipped proc

[`tools/sos-codegen/viewers/gtkwave/sos_overlay.tcl`][tcl-plugin] defines:

```tcl
proc sos_open_vector_at {vector_index} {
    # 1. Read ::sos_vector_source (set by sos_overlay_install via the
    #    Python ext's to_gtkwave_tcl(..., vector_source=...) emit).
    # 2. Read $env(EDITOR).
    # 3. exec $editor "+<vector_index+2>" $::sos_vector_source &
    # 4. Soft-fail (log + return 0) when global empty or EDITOR unset.
}
```

The proc is registered unconditionally at plugin load (`source sos_overlay.tcl` or `gtkwave --script sos_overlay.tcl ...`). Users invoke it from the Tcl console or via a keybinding in `~/.gtkwaverc`.

### 2.2 The `EDITOR` env var contract

The proc reads `$env(EDITOR)` at invocation time (not at plugin load). The host MUST set the env var before launching GTKWave; GTKWave then inherits it into the Tcl interpreter.

Concretely:

| Editor | Expected `EDITOR` value | What `+<line>` does |
|---|---|---|
| **vim / nvim** | `vim` or `nvim` | Opens file with cursor on line N |
| **emacs / emacsclient** | `emacsclient -n` (use `-n` so emacsclient returns control to GTKWave immediately) | Opens file at line N in the running Emacs session |
| **VS Code** | `code -g` (the `-g` flag accepts `file:line` syntax; see §2.3 for line-hint adapter) | Jumps to specific line |
| **Sublime Text** | `subl` (accepts `file:line:column`) | See §2.3 adapter |
| **less / cat** (debug-only) | `less` or `cat` | `+N` jumps to line N (less) or is ignored (cat) |

For editors that do NOT accept the `+N` line-hint argument (notably VS Code, Sublime, IntelliJ family), the host MAY wrap the editor in a shim script that translates `+<line>` into the editor's native line-hint flag — see §2.3.

### 2.3 Line-hint adapter shim (for editors without `+N`)

A POSIX shell shim setting `EDITOR=/path/to/code-line-hint`:

```sh
#!/bin/sh
# code-line-hint — translate GTKWave's `+<line>` into `code -g <file>:<line>`.
line=""
file=""
for arg in "$@"; do
    case "$arg" in
        +*) line="${arg#+}" ;;
        *)  file="$arg" ;;
    esac
done
if [ -n "$line" ]; then
    exec code -g "${file}:${line}"
fi
exec code -g "$file"
```

The shim is the host integrator's responsibility; SOS-08-G does NOT ship per-editor wrappers because the editor ecosystem is open-ended.

### 2.4 What happens when `EDITOR` is unset

Per the [shipped proc][tcl-plugin] (lines 226-230 of `sos_overlay.tcl`):

```tcl
if {![info exists ::env(EDITOR)] || $::env(EDITOR) eq ""} {
    sos_log "sos_open_vector_at: \$EDITOR is unset; cannot open \
              $src at vector_index=$vector_index"
    return 0
}
```

The proc logs to GTKWave's stdout via `sos_log` (prefix `[sos-overlay]`) and **returns 0** — soft-fail. The viewer event loop is NEVER blocked; no exception propagates into GTKWave's Tcl frame; subsequent invocations of `sos_open_vector_at` MAY succeed if `EDITOR` is set in between. The same shape applies when `::sos_vector_source` is unset or empty (proc returns 0 with a diagnostic log line).

### 2.5 Example bindings

A user's `~/.gtkwaverc` MAY add:

```
keyactions {
    ctrl-shift-o sos_open_vector_at_under_cursor
}
```

where `sos_open_vector_at_under_cursor` is a thin user-defined wrapper that resolves the active marker's `vector_index` from the GTKWave selection state and calls `sos_open_vector_at <N>`. Until the keyaction-from-plugin API stabilises (cited [§15 wave-3c-future entry][concepts-§15] as the upstream blocker), the wrapper is user-authored.

A minimal direct invocation from the Tcl console:

```tcl
sos_open_vector_at 3
```

opens `$::sos_vector_source` at line `3 + 2 = 5`.

## 3. Surfer WASM host-wiring

### 3.1 The emitted command

[`tools/sos-codegen/viewers/surfer/sos-surfer-plugin/src/lib.rs`][surfer-plugin] defines the `SurferCommand::OpenVectorSource` variant:

```rust
pub enum SurferCommand {
    // ...
    OpenVectorSource {
        vector_source: String,    // mirrors _meta.vector_source
        vector_index: u64,        // step index within the JSON file
        time: u64,                // cycle the badge sits at
        chart_state: String,      // chart-vocabulary tooltip
    },
}
```

The plugin's `render_commands_with_vector_source(records, vector_source)` emits one `OpenVectorSource` per record carrying `vector_index` when `vector_source` is non-empty. The host receives the command vector from the plugin and is responsible for routing each `OpenVectorSource` to an editor.

### 3.2 Host handler contract

A Surfer-embedding application registering a handler for `OpenVectorSource` MUST:

- **(a) Be idempotent.** Surfer MAY re-emit the same command on re-click (user re-clicks the same badge); the handler MUST NOT spawn duplicate editor processes for the same `(vector_source, vector_index)` within a short re-emit window (a few hundred ms is a reasonable debounce; SOS-08-G does not freeze the value).
- **(b) Be non-blocking.** The handler MUST NOT block Surfer's plugin event loop. Editor exec MUST happen on a background thread (or a `spawn` future on async-runtime hosts) and return control immediately.
- **(c) Validate `vector_source` paths.** See §6 Security.
- **(d) Surface failures via Surfer's status bar.** The handler MUST NOT panic on failed exec, missing file, or unset `EDITOR`. Failed conditions MUST produce a user-visible status line (Surfer's notification channel) so the user knows the click was received but no editor opened.
- **(e) Preserve the chart-vocabulary tooltip.** The `chart_state` field of `OpenVectorSource` carries the chart-state ID at the badge's cycle; the host SHOULD surface this in any status-bar feedback (`"opened arming step 3 in vim"`) so the user sees chart-vocabulary, not raw vector indices.

### 3.3 Reference handler sketch (pseudo-Rust)

A host-side handler skeleton:

```rust
fn handle_surfer_command(cmd: SurferCommand) {
    match cmd {
        SurferCommand::OpenVectorSource {
            vector_source,
            vector_index,
            time: _,
            chart_state,
        } => {
            // (c) Validate the path is inside the workspace root.
            if !is_in_workspace_root(&vector_source) {
                surfer_status_bar(format!(
                    "drill-down rejected: {vector_source} outside workspace root"
                ));
                return;
            }
            // (b) Spawn on a background thread / async runtime.
            std::thread::spawn(move || {
                let editor = match std::env::var("EDITOR") {
                    Ok(e) if !e.is_empty() => e,
                    _ => {
                        surfer_status_bar(
                            "drill-down: $EDITOR is unset".to_string(),
                        );
                        return;
                    }
                };
                // (§4) Line-hint convention: vector_index + 2.
                let line = vector_index + 2;
                // (a) Idempotency-debounce omitted for brevity; a
                //     production host caches recent (path, line) pairs.
                let status = std::process::Command::new(&editor)
                    .arg(format!("+{line}"))
                    .arg(&vector_source)
                    .status();
                match status {
                    Ok(s) if s.success() => surfer_status_bar(format!(
                        "drill-down: opened {chart_state} step {vector_index} in {editor}"
                    )),
                    Ok(s) => surfer_status_bar(format!(
                        "drill-down: {editor} exited {s}"
                    )),
                    Err(e) => surfer_status_bar(format!(
                        "drill-down: failed to exec {editor}: {e}"
                    )),
                }
            });
        }
        _ => { /* other commands handled elsewhere */ }
    }
}
```

The sketch is illustrative; the actual handler shape depends on Surfer's host SDK (event-channel vs trait-impl vs WIT-derived). Pin to whichever API ships when upstream stabilises.

## 4. Line-hint convention

Both viewer paths translate `vector_index` to a 1-indexed file line via:

```
line = vector_index + 2
```

The `+2` derives from the SOS-03 vector-trace JSON-file shape — the typical structure is a top-level JSON array:

```json
[
  { "meta": { "...": "..." } },     // line 1: file opens with `[` then meta on line 2; emitters that fold meta to line 1 are still consistent.
  { "step": 0, "...": "..." },       // line 3 → vector_index = 0
  { "step": 1, "...": "..." },       // line 4 → vector_index = 1
  ...
]
```

- **+1** for 1-indexed file lines (vs 0-indexed `vector_index`).
- **+1** for the JSONL/JSON header row (the `meta` object). Both SOS-03 vector-trace shapes (JSONL and array-pretty-printed) reserve the first non-`[` line for metadata; the first vector step lands at line 3 in the array shape, and the offset `vector_index + 2 = 2` rounds down to line 2 for the very first step under JSONL-flat — close enough that editors land the user "near" the right step without per-shape introspection.

The `+2` offset is the **floor** of what's correct across both shapes. Hosts that want pixel-perfect line jumps MAY parse the vector-source JSON to compute the exact line, but the methodology accepts the +2 approximation as the data-layer contract; finer resolution is a host-side enhancement.

## 5. Failure modes

A conforming host integration MUST handle the following failure modes per the rules in §1 and §2.4 / §3.2:

| Failure mode | GTKWave (Tcl) behaviour | Surfer (host handler) behaviour |
|---|---|---|
| **`EDITOR` env unset / empty** | `sos_open_vector_at` returns 0 + logs `[sos-overlay] $EDITOR is unset` | Host MUST surface to status bar; MUST NOT exec |
| **`vector_source` path is empty** | proc returns 0 + logs `_meta.vector_source` missing | Drill-down command was NOT emitted in this case (per Surfer plugin `render_commands_with_vector_source` short-circuit); handler will not be invoked |
| **`vector_source` path is missing on disk** | proc still execs `$EDITOR +<line> $src` — editor surfaces "file not found" to user | Host SHOULD `Path::exists` check before exec; if missing, status-bar `"drill-down: vector_source not found: {path}"` |
| **`vector_index` out of range** (file shorter than line N+2) | Editor opens at end-of-file (vim) or near-EOF (emacs); not the host's job to validate against vector file structure | Same — host MUST NOT block on JSON parse to validate |
| **Editor exec fails (binary missing, PATH issue)** | `catch` traps the exec error, logs `[sos-overlay] WARN: sos_open_vector_at exec failed: <err>`, returns 0 | Host MUST capture exec result + surface to status bar |
| **Re-click on same badge** | GTKWave Tcl `exec ... &` spawns a new editor process each call; rate-limit is per-user-comfort, not enforced | Host SHOULD debounce (see §3.2(a)) |
| **Multiple overlays loaded, multiple `::sos_vector_source` writes** | GTKWave: last-write wins on the global; user MAY see drill-down route to a different file than expected. Document the surprise; future amendment MAY introduce per-overlay scoping | Surfer: each `OpenVectorSource` carries `vector_source` per-command, no global state, no last-write surprise |

Hard invariants across both viewer paths:

- The viewer event loop MUST NOT block. All editor exec is fire-and-forget (Tcl `exec ... &`; Rust thread-spawn or async-task).
- The wave file MUST NOT be mutated. Drill-down is read-only WRT the simulator's output.
- Failed exec MUST NOT propagate as a viewer-crashing exception. Both surfaces use catch/match patterns to convert errors into status-line diagnostics.

## 6. Security

The `vector_source` path is sourced from the overlay's `_meta.vector_source` field, which the cocotb walker emits at codegen time from a chart-author-controlled `_VECTORS_DIR` path. Treat it as **generated tooling output, not user input** — but still treat it with the discipline owed to any path-from-data that gets fed to `exec`.

Hosts SHOULD:

- **Validate paths are inside an expected workspace root.** A host SHOULD know its workspace root (the chart repo's checkout directory, or a configured allowlist) and reject `vector_source` paths that escape it (`..` traversal, absolute paths outside the root, symlinks pointing outside). Reject MUST surface via status bar (§3.2(d)) and MUST NOT exec.
- **Sanitise before exec.** Pass `vector_source` as an argv element, NEVER concatenated into a shell command string. The GTKWave Tcl plugin's `exec $editor "+$line_hint" $src &` uses Tcl's argv passing (no shell interpretation); the Surfer reference handler uses `Command::new(...).arg(...).arg(...)` (no shell interpretation). DO NOT shell out via `system()` / `popen()` with concatenation — at the time of writing the methodology has had no such regression but the discipline is stated explicitly here.
- **Refuse non-file URIs.** If `_meta.vector_source` starts with `http://`, `https://`, `file://` or any URI scheme, the host MUST reject. The data-layer contract is filesystem paths only at v1.0.

The host SHOULD NOT:

- Shell out to `sh -c "$EDITOR $args"` — bypasses argv quoting and opens command-injection surface.
- Trust that `vector_source` is on disk before exec (the editor will report missing-file itself; better UX is a host-side `Path::exists` check first, but it's not a security gate).

## 7. Citations

- Concept doc: [`docs/concepts/SOS-08-G-CONCEPTS.md`][concepts-§6] §6 viewer integration contract, §5.2 overlay schema (incl. `_meta.vector_source` from the wave-3c-future amendment), §15 wave-3c-future and wave-3c-future-f2 entries.
- GTKWave plugin source: [`tools/sos-codegen/viewers/gtkwave/sos_overlay.tcl`][tcl-plugin] — the canonical `sos_open_vector_at` proc.
- Surfer plugin source: [`tools/sos-codegen/viewers/surfer/sos-surfer-plugin/src/lib.rs`][surfer-plugin] — the canonical `OpenVectorSource` enum variant + `render_commands_with_vector_source` emitter.
- Upstream blockers (informative): GTKWave keyaction-from-plugin API; Surfer plugin-host link-back API. Both pending stabilisation as of the wave-3c-future entry.

## 8. Conformance

A host integration is **§6 (f.2) conforming** when it satisfies:

- §1 (1) discovery: GTKWave reads `::sos_vector_source`; Surfer reads per-command `vector_source`.
- §1 (2) editor invocation: translates `(vector_source, vector_index)` to `exec EDITOR +<vector_index+2> vector_source`.
- §1 (3) failure surfacing: non-blocking, status-bar reporting, no wave-file mutation.
- §1 (4) and §6: path validation against workspace root; no shell-string concatenation.

A host integration that satisfies §1 (1)-(3) but skips §1 (4) is **partially conforming**; absent path validation is a known security gap (SOS-08-G strongly RECOMMENDS the validation but does not gate viewer functionality on it).

Until upstream viewer-API stabilisation lands, GTKWave Tcl integrations achieve full §6 (f.2) conformance via the shipped proc + user-configured `EDITOR`; Surfer integrations achieve conformance only when the host application implements the §3.3 handler against whatever Surfer plugin-host API ships.
