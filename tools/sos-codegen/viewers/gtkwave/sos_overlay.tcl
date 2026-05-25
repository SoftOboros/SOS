# SOS-08-G GTKWave overlay extension (wave-3c GUI integration).
#
# Loadable Tcl script that hooks the running GTKWave instance and
# installs chart-state markers + comment-trace overlay tracks from a
# `<test>.annotations.jsonl` overlay file (per SOS-08-G §5.2 schema).
#
# Discovery proceeds via SOS-08-G §6 (a) co-locate semantics (wave-3b):
# the script reads the loaded waveform's path, locates matching
# `.annotations.jsonl` files in the same directory by reading their
# `_meta.waveform_prefix` header field, then shells out to the sibling
# Python extension to convert the JSONL into the Tcl marker commands
# that GTKWave's command surface accepts.
#
# Wave-3c MUST conformance gates satisfied:
#   §6 (a) co-locate          — sos_overlay_find_overlays
#   §6 (b) schema-version-aware — Python ext validates header before emit
#   §6 (c) per-record render  — gtkwave::/Edit/Set_Named_Marker per record
#
# Wave-3c SHOULD conformance gates partially satisfied:
#   §6 (d) chart-path navigation — comment-trace track shows chart_path
#   §6 (e) invariant-fire highlighting — mark_invariant track separately
#   §6 (f) vector-citation drill-down — wave-3c-future (requires GTKWave
#                                       link-back to vector files)
#
# @spec  SOS-08-G-CONCEPTS.md §5.2 (overlay schema)
# @spec  SOS-08-G-CONCEPTS.md §6 (viewer integration contract)
# @spec  SOS-08-G-CONCEPTS.md §15 wave-3c (2026-05-24)
# @spec  INV-S-HDL-G-1 (three-file output coupling — overlay co-located
#        with waveform via `_meta.waveform_prefix`)
# @spec  INV-S-HDL-G-3 (schema-version header validated before consume)
#
# Usage:
#   gtkwave --script sos_overlay.tcl <waveform.fst>
#
# Or interactively from GTKWave's GUI:
#   File → Read Tcl Script... → sos_overlay.tcl
#
# Environment:
#   SOS_GTKWAVE_PYTHON   — override the python interpreter (default: python3)
#   SOS_OVERLAY_VERBOSE  — set to 1 for chatty status output

set sos_overlay_version "1.0"
set sos_overlay_python_default "python3"

proc sos_log {msg} {
    # Always print SOS-overlay status lines so the user can confirm the
    # extension fired even when the GTKWave window is the only signal.
    puts "\[sos-overlay\] $msg"
}

proc sos_log_verbose {msg} {
    if {[info exists ::env(SOS_OVERLAY_VERBOSE)]} {
        sos_log $msg
    }
}

proc sos_overlay_python_interp {} {
    if {[info exists ::env(SOS_GTKWAVE_PYTHON)]} {
        return $::env(SOS_GTKWAVE_PYTHON)
    }
    return $::sos_overlay_python_default
}

proc sos_overlay_script_dir {} {
    # Resolve the directory containing this Tcl script so we can find
    # the sibling Python extension regardless of GTKWave's CWD.
    if {[info script] ne ""} {
        return [file dirname [file normalize [info script]]]
    }
    return [pwd]
}

proc sos_overlay_dump_path {} {
    # Best-effort: GTKWave's Tcl surface exposes the current dump file
    # path via `gtkwave::getDumpFileName`. When invoked from CLI
    # `--script` mode the API may be available; otherwise the user can
    # set ::sos_overlay_dump_path explicitly before sourcing.
    if {[info exists ::sos_overlay_dump_path]} {
        return $::sos_overlay_dump_path
    }
    if {[catch {
        set result [gtkwave::getDumpFileName]
    } err]} {
        sos_log_verbose "gtkwave::getDumpFileName unavailable: $err"
        return ""
    }
    return $result
}

proc sos_overlay_extract_prefix {header_line} {
    # Parse the `_meta.waveform_prefix` field from the overlay's
    # first-line header. Tcl has no built-in JSON parser; the header
    # shape is constrained enough (single-line JSON, fixed field
    # ordering by the emitter) that a regex extraction is robust at
    # v1.0. When the field is absent, return the empty string and let
    # the caller fall back to the wave-1 same-prefix-as-overlay
    # convention.
    if {[regexp {"waveform_prefix"\s*:\s*"([^"]+)"} $header_line _ prefix]} {
        return $prefix
    }
    return ""
}

proc sos_overlay_find_overlays {dump_dir dump_stem} {
    # Returns the list of .annotations.jsonl files in $dump_dir that
    # correspond to the loaded waveform.
    #
    # Discovery order (mirrors SOS-08-G §6 (a) viewer-integration
    # contract):
    #
    #   1. Wave-3b: read each candidate's first-line header; match by
    #      `_meta.waveform_prefix == $dump_stem`.
    #   2. Wave-1 fallback: match by exact filename `<stem>.annotations.jsonl`.
    #
    # A single waveform MAY have multiple corresponding overlays (one
    # per @cocotb.test() in a parallel-tests run); all matching
    # overlays are installed.
    set matches {}
    set candidates [glob -nocomplain -directory $dump_dir *.annotations.jsonl]
    foreach candidate $candidates {
        set header ""
        if {![catch {
            set fh [open $candidate r]
            set header [gets $fh]
            close $fh
        } err]} {
            set prefix [sos_overlay_extract_prefix $header]
            if {$prefix ne "" && $prefix eq $dump_stem} {
                lappend matches $candidate
                continue
            }
        }
        # Wave-1 same-prefix-as-overlay fallback.
        set candidate_stem [file rootname [file tail $candidate]]
        # Strip `.annotations` suffix from the stem.
        regsub {\.annotations$} $candidate_stem "" candidate_stem
        if {$candidate_stem eq $dump_stem} {
            lappend matches $candidate
        }
    }
    return $matches
}

proc sos_overlay_emit_tcl {overlay_path} {
    # Shell out to the sibling Python extension to convert the JSONL
    # overlay into the Tcl marker commands GTKWave's command surface
    # consumes. The Python extension validates the schema header per
    # INV-S-HDL-G-3 + §6 (b) so a malformed overlay surfaces here as
    # an exec error, not silently mis-rendered.
    set script_dir [sos_overlay_script_dir]
    set py_ext [file join $script_dir sos_gtkwave_ext.py]
    if {![file exists $py_ext]} {
        sos_log "ERROR: python extension not found at $py_ext"
        return ""
    }
    set py [sos_overlay_python_interp]
    if {[catch {
        set tcl_output [exec $py $py_ext --format gtkwave $overlay_path]
    } err]} {
        sos_log "ERROR: exec failed for $overlay_path: $err"
        return ""
    }
    return $tcl_output
}

proc sos_overlay_install {overlay_path} {
    # Install markers + comment traces from one overlay file. Returns
    # the number of records installed (0 if the overlay was empty or
    # exec failed).
    set tcl_output [sos_overlay_emit_tcl $overlay_path]
    if {$tcl_output eq ""} {
        return 0
    }
    # The emitted Tcl is a sequence of gtkwave::/Edit/Set_Named_Marker
    # + gtkwave::/Edit/Set_Marker_Name calls plus the conventional
    # add_marker / mark_invariant / mark_vector_citation aliases the
    # wave-1 + wave-3c-future emit shapes use. `eval` executes them in
    # the current interp. Wave-3c-future: emitted Tcl MAY include a
    # `set ::sos_vector_source "<path>"` line that the eval lands; the
    # `sos_open_vector_at` proc below consults the resulting global.
    if {[catch {
        eval $tcl_output
    } err]} {
        sos_log "WARN: eval failed for $overlay_path: $err"
        return 0
    }
    # Count records (best-effort: count `add_marker` occurrences in the
    # emitted text). This is informational; the actual marker count is
    # capped at 26 (A..Z) per GTKWave's named-marker model.
    set count [regexp -all {^add_marker } $tcl_output]
    return $count
}

# SOS-08-G wave-3c-future §6 (f) — vector-citation drill-down.
#
# `sos_open_vector_at <vector_index>` resolves the click-through for a
# badge with vector_index=N. Strategy:
#   1. Read the per-overlay vector_source path from the global
#      `::sos_vector_source` set by sos_overlay_install via the emit
#      from `to_gtkwave_tcl(..., vector_source=...)`.
#   2. Spawn `${EDITOR}` (env var) against the resolved path. Most
#      editors accept a `+<line>` argument to jump to a specific line;
#      we pass `+<vector_index+2>` as a best-effort target (vector
#      step N appears around line N+2 in the JSON for the typical
#      SOS-03 vector-trace shape: `[meta, step0, step1, ...]`).
#   3. When `$env(EDITOR)` is unset or the file path is empty, the
#      proc logs the diagnostic + returns 0 without raising — keeps
#      key-bound invocations soft-fail in GTKWave's GUI context.
#
# The proc is INSTALLED unconditionally at plugin load so users can
# rebind it to any key via their `~/.gtkwaverc` `keyactions` section.
# The default binding is documented in the plugin README (no Tcl
# binding emitted here so a user's existing key map is unaffected).
proc sos_open_vector_at {vector_index} {
    if {![info exists ::sos_vector_source]} {
        sos_log "sos_open_vector_at: no ::sos_vector_source global set; \
                  overlay header missing _meta.vector_source"
        return 0
    }
    set src $::sos_vector_source
    if {$src eq ""} {
        sos_log "sos_open_vector_at: ::sos_vector_source is empty; \
                  overlay header missing _meta.vector_source"
        return 0
    }
    if {![info exists ::env(EDITOR)] || $::env(EDITOR) eq ""} {
        sos_log "sos_open_vector_at: \$EDITOR is unset; cannot open \
                  $src at vector_index=$vector_index"
        return 0
    }
    set editor $::env(EDITOR)
    set line_hint [expr {$vector_index + 2}]
    sos_log "sos_open_vector_at: $editor +$line_hint $src \
              (vector_index=$vector_index)"
    if {[catch {
        exec $editor "+$line_hint" $src &
    } err]} {
        sos_log "WARN: sos_open_vector_at exec failed: $err"
        return 0
    }
    return 1
}

proc sos_overlay_main {} {
    sos_log "SOS-08-G overlay extension v$::sos_overlay_version loaded"

    set dump_path [sos_overlay_dump_path]
    if {$dump_path eq ""} {
        sos_log "no dump file loaded; set ::sos_overlay_dump_path to override"
        return
    }
    set dump_dir [file dirname $dump_path]
    set dump_stem [file rootname [file tail $dump_path]]
    sos_log_verbose "dump_path=$dump_path"
    sos_log_verbose "dump_dir=$dump_dir, dump_stem=$dump_stem"

    set overlays [sos_overlay_find_overlays $dump_dir $dump_stem]
    if {[llength $overlays] == 0} {
        sos_log "no .annotations.jsonl overlays found in $dump_dir"
        return
    }
    sos_log "discovered [llength $overlays] overlay(s) for $dump_stem"

    set total 0
    foreach overlay $overlays {
        set installed [sos_overlay_install $overlay]
        sos_log "installed $installed markers from [file tail $overlay]"
        incr total $installed
    }
    sos_log "done: $total marker(s) installed"
}

# Auto-invoke at script load time. Callers that want manual control
# (e.g., GUI loads where `sos_overlay_dump_path` needs to be set
# first) MAY set `::sos_overlay_skip_auto_main` before sourcing.
if {![info exists ::sos_overlay_skip_auto_main]} {
    sos_overlay_main
}
