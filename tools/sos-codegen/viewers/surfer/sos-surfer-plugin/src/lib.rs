//! SOS-08-G annotation-overlay plugin for the Surfer waveform viewer
//! (wave-3c GUI integration).
//!
//! Implements the SOS-08-G §5.2 annotation-overlay schema consumer
//! side of the Surfer plugin host's wit-bindgen interface. The plugin:
//!
//! 1. Reads a `<test>.annotations.jsonl` overlay file path passed by
//!    Surfer's plugin host.
//! 2. Validates the first-line schema-version header per
//!    INV-S-HDL-G-3 / SOS-08-G §6 (b).
//! 3. Discovers the waveform companion file(s) via the wave-3b
//!    `_meta.waveform_prefix` field (SOS-08-G §6 (a) co-locate
//!    amendment, 2026-05-24).
//! 4. Emits Surfer overlay-track install commands for the host to
//!    render — per-record markers (§6 (c)), per-chart_path comment
//!    tracks (§6 (d)), invariant-fire highlights (§6 (e)).
//!
//! ## Build
//!
//! Host-target check (no WASM toolchain required):
//!
//! ```sh
//! cargo check
//! ```
//!
//! Surfer plugin artifact (release build):
//!
//! ```sh
//! cargo build --release --target wasm32-unknown-unknown --features wasm
//! ```
//!
//! The release artifact lands at
//! `target/wasm32-unknown-unknown/release/sos_surfer_plugin.wasm`;
//! Surfer's plugin host loads it via the `surfer-plugin.toml` manifest
//! (sibling file in this directory).
//!
//! ## Spec citations
//!
//! - [SOS-08-G-CONCEPTS.md §5.2] overlay schema (six normative fields
//!   + two optional; `_meta` envelope with optional `waveform_prefix`).
//! - [SOS-08-G-CONCEPTS.md §6] viewer-integration contract.
//! - [SOS-08-G-CONCEPTS.md §15] wave-3c entry (this plugin).
//! - INV-S-HDL-G-1 (three-file output coupling).
//! - INV-S-HDL-G-3 (schema-version header required at line 0).

#![cfg_attr(feature = "wasm", no_std)]

#[cfg(feature = "wasm")]
extern crate alloc;

#[cfg(feature = "wasm")]
use alloc::{string::String, vec::Vec};

use serde::Deserialize;

/// Frozen SOS-08-G §5.2 schema identifier (canonicalized in
/// PCDN-G-wave1-001 / §15 2026-05-23). The plugin rejects any overlay
/// whose `_meta.schema` does not match this constant.
pub const SCHEMA_NAME: &str = "sos-08-g/annotations";

/// Frozen SOS-08-G §5.2 schema version (v1 per §12 (b)). Bumping the
/// version is a §15 amendment that requires this constant + the
/// Python emitter + the GTKWave extension to land together.
pub const SCHEMA_VERSION: &str = "1.0";

/// SOS-12 chart-path depth cap (mirrored per PCDN-G-002). Surfer's
/// overlay-track-name path truncates at this depth so deeply-nested
/// charts don't blow out the track sidebar.
pub const CHART_PATH_MAX_DEPTH: usize = 8;

/// Per-record annotation row per SOS-08-G §5.2 (INV-S-HDL-G-2).
///
/// Six normative fields + two optional. `transition_id`, `region`,
/// `invariant_id`, and `vector_index` are nullable per §5.2; serde
/// `Option<...>` mirrors the JSON `null`-vs-absent distinction.
#[derive(Debug, Clone, Deserialize)]
pub struct AnnotationRecord {
    pub cycle: u64,
    #[serde(default)]
    pub signal: String,
    pub chart_state: String,
    pub transition_id: Option<String>,
    #[serde(default)]
    pub chart_path: ChartPath,
    pub region: Option<String>,
    #[serde(default)]
    pub invariant_id: Option<String>,
    #[serde(default)]
    pub vector_index: Option<u64>,
}

/// `chart_path` can be either a list of segments (wave-2 nested-chart
/// walking) or a string (wave-1 single-segment shape). Surfer side
/// normalises both into a slash-joined `/seg/seg/...` string.
#[derive(Debug, Clone, Default, Deserialize)]
#[serde(untagged)]
pub enum ChartPath {
    /// Wave-2+ shape: `["chart", "parent", ..., "leaf"]`.
    Segments(Vec<String>),
    /// Wave-1 shape: `"/orchestrator/syscalls/sem.take"`.
    String(String),
    /// Absent / malformed → empty path.
    #[default]
    Empty,
}

impl ChartPath {
    pub fn to_path_string(&self) -> String {
        match self {
            ChartPath::Segments(segs) => {
                let mut out = String::from("/");
                for (i, s) in segs.iter().take(CHART_PATH_MAX_DEPTH).enumerate() {
                    if i > 0 {
                        out.push('/');
                    }
                    out.push_str(s);
                }
                out
            }
            ChartPath::String(s) if s.starts_with('/') => s.clone(),
            ChartPath::String(s) => {
                let mut out = String::from("/");
                out.push_str(s);
                out
            }
            ChartPath::Empty => String::from("/"),
        }
    }
}

/// Schema-header envelope per SOS-08-G §5.2 + PCDN-G-wave1-001.
#[derive(Debug, Clone, Deserialize)]
pub struct SchemaHeader {
    #[serde(rename = "_meta")]
    pub meta: SchemaMeta,
}

#[derive(Debug, Clone, Deserialize)]
pub struct SchemaMeta {
    pub schema: String,
    pub version: String,
    #[serde(default)]
    pub chart_path_max_depth: Option<u64>,
    /// SOS-08-G wave-3b additive field (PCDN-G-wave1-003 resolution,
    /// 2026-05-24): the per-test waveform-file prefix used by viewer
    /// extensions to locate `<prefix>.fst|.vcd` in the overlay's
    /// directory.
    #[serde(default)]
    pub waveform_prefix: Option<String>,
    /// SOS-08-G wave-3c-future additive field (§15 2026-05-24): path
    /// to the SOS-03 vector JSON file the cocotb test loaded. When
    /// present, the plugin emits `OpenVectorSource` commands for each
    /// record carrying `vector_index`, closing §6 (f) drill-down on
    /// the data-layer side. The host's link-back API consumes the
    /// command at runtime (when stabilised); forward-compat hosts
    /// stub the command as a no-op.
    #[serde(default)]
    pub vector_source: Option<String>,
}

/// Errors raised by [`parse_overlay`].
#[derive(Debug)]
pub enum LoadError {
    Empty,
    HeaderJson(String),
    BadSchema { found: String, expected: String },
    BadVersion { found: String, expected: String },
    RecordJson { line: usize, msg: String },
}

/// Parse a `.annotations.jsonl` overlay file into its header + records.
///
/// Per INV-S-HDL-G-3 the first line MUST be the schema-version
/// header; subsequent lines are annotation records. Empty lines are
/// skipped. Returns `Err(LoadError::BadSchema | BadVersion)` when the
/// header fails §6 (b) schema-version-aware validation.
pub fn parse_overlay(content: &str) -> Result<(SchemaHeader, Vec<AnnotationRecord>), LoadError> {
    let mut lines = content.lines().filter(|l| !l.trim().is_empty());
    let header_line = lines.next().ok_or(LoadError::Empty)?;
    let header: SchemaHeader = serde_json::from_str(header_line)
        .map_err(|e| LoadError::HeaderJson(e.to_string()))?;
    if header.meta.schema != SCHEMA_NAME {
        return Err(LoadError::BadSchema {
            found: header.meta.schema,
            expected: String::from(SCHEMA_NAME),
        });
    }
    if header.meta.version != SCHEMA_VERSION {
        return Err(LoadError::BadVersion {
            found: header.meta.version,
            expected: String::from(SCHEMA_VERSION),
        });
    }
    let mut records: Vec<AnnotationRecord> = Vec::new();
    for (idx, line) in lines.enumerate() {
        let record: AnnotationRecord = serde_json::from_str(line)
            .map_err(|e| LoadError::RecordJson { line: idx + 1, msg: e.to_string() })?;
        records.push(record);
    }
    Ok((header, records))
}

/// Surfer overlay-track install command emitted by the plugin per
/// SOS-08-G §6 (c/d/e). Surfer's host loads the plugin via wit-bindgen
/// and consumes a `Vec<SurferCommand>` returned from the plugin's
/// `render_overlay` entry point (see `wit/sos-surfer.wit` once the
/// Surfer plugin SDK stabilises).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SurferCommand {
    /// Install a per-record marker at `time` with `label`.
    Marker { time: u64, label: String },
    /// Install a named overlay-track row (creates the track if
    /// absent).
    AddOverlayTrack { name: String },
    /// Append an event (time, label) to a named overlay track.
    AddOverlayEvent {
        track: String,
        time: u64,
        label: String,
    },
    /// Apply the invariant-fire visual-treatment override (§6 (e)).
    MarkInvariant { time: u64, label: String },
    /// SOS-08-G wave-3c-future §6 (f): drill-down click target. The
    /// host's plugin link-back API routes the click to the user's
    /// editor (or a no-op stub on hosts without the link-back hook).
    /// `vector_source` mirrors `_meta.vector_source`; `vector_index`
    /// names the step within that file; `time` + `chart_state` give
    /// the host a chart-vocabulary tooltip for the link.
    OpenVectorSource {
        vector_source: String,
        vector_index: u64,
        time: u64,
        chart_state: String,
    },
}

/// Render the parsed annotation set into a flat list of Surfer
/// overlay-install commands.
///
/// Output shape mirrors the Python `to_surfer_commands` emitter:
///
/// 1. Per-record `Marker` commands (§6 (c)).
/// 2. Per-chart_path `AddOverlayTrack` + `AddOverlayEvent` pairs
///    (§6 (d) chart-path navigation SHOULD).
/// 3. Optional `sos:invariants` overlay track + `MarkInvariant`
///    highlights for records with `invariant_id != None` (§6 (e)).
/// 4. Optional `OpenVectorSource` commands for records carrying
///    `vector_index` when `vector_source` is non-empty (§6 (f) —
///    wave-3c-future drill-down). The Python `render_commands`
///    binding takes the value from `_meta.vector_source`; this Rust
///    entry-point overload accepts it as an explicit argument.
pub fn render_commands(records: &[AnnotationRecord]) -> Vec<SurferCommand> {
    render_commands_with_vector_source(records, None)
}

/// Variant of [`render_commands`] that threads the overlay's
/// `_meta.vector_source` through so the emit can produce
/// `OpenVectorSource` commands (§6 (f) wave-3c-future drill-down).
///
/// Callers that have parsed the overlay header (via [`parse_overlay`])
/// SHOULD pass `header.meta.vector_source.as_deref()`; the
/// drill-down commands emit when both the header carries a non-empty
/// `vector_source` AND the record has a `vector_index`.
pub fn render_commands_with_vector_source(
    records: &[AnnotationRecord],
    vector_source: Option<&str>,
) -> Vec<SurferCommand> {
    use std::collections::BTreeMap;

    let mut cmds: Vec<SurferCommand> = Vec::new();
    let mut sorted: Vec<&AnnotationRecord> = records.iter().collect();
    sorted.sort_by_key(|r| r.cycle);

    // --- per-record markers --- //
    for record in &sorted {
        let mut label = record.chart_state.clone();
        if let Some(tid) = &record.transition_id {
            label.push_str(&format!(" (t:{tid})"));
        }
        if let Some(invid) = &record.invariant_id {
            label.push_str(&format!(" [inv:{invid}]"));
        }
        cmds.push(SurferCommand::Marker {
            time: record.cycle,
            label: label.clone(),
        });
        if let Some(invid) = &record.invariant_id {
            cmds.push(SurferCommand::MarkInvariant {
                time: record.cycle,
                label: format!("{invid} @ {}", record.chart_state),
            });
        }
    }

    // --- per-chart_path overlay tracks --- //
    let mut by_path: BTreeMap<String, Vec<(u64, String)>> = BTreeMap::new();
    for record in &sorted {
        let path_key = record.chart_path.to_path_string();
        let mut label = record.chart_state.clone();
        if let Some(tid) = &record.transition_id {
            label.push_str(&format!(" (t:{tid})"));
        }
        by_path
            .entry(path_key)
            .or_default()
            .push((record.cycle, label));
    }
    for (chart_path, entries) in by_path {
        let track = format!("sos:{chart_path}");
        cmds.push(SurferCommand::AddOverlayTrack {
            name: track.clone(),
        });
        for (time, label) in entries {
            cmds.push(SurferCommand::AddOverlayEvent {
                track: track.clone(),
                time,
                label,
            });
        }
    }

    // --- invariant-fire overlay track --- //
    let has_invariants = sorted.iter().any(|r| r.invariant_id.is_some());
    if has_invariants {
        cmds.push(SurferCommand::AddOverlayTrack {
            name: String::from("sos:invariants"),
        });
        for record in &sorted {
            if let Some(invid) = &record.invariant_id {
                cmds.push(SurferCommand::AddOverlayEvent {
                    track: String::from("sos:invariants"),
                    time: record.cycle,
                    label: format!("{invid} @ {}", record.chart_state),
                });
            }
        }
    }

    // --- §6 (f) drill-down commands (wave-3c-future) --- //
    if let Some(src) = vector_source.filter(|s| !s.is_empty()) {
        for record in &sorted {
            if let Some(vi) = record.vector_index {
                cmds.push(SurferCommand::OpenVectorSource {
                    vector_source: String::from(src),
                    vector_index: vi,
                    time: record.cycle,
                    chart_state: record.chart_state.clone(),
                });
            }
        }
    }

    cmds
}

#[cfg(test)]
mod tests {
    use super::*;

    const SIMPLE_OVERLAY: &str = concat!(
        r#"{"_meta": {"schema": "sos-08-g/annotations", "version": "1.0", "#,
        r#""chart_path_max_depth": 8, "waveform_prefix": "test_demo_fsm"}}"#,
        "\n",
        r#"{"cycle": 0, "signal": "dut.cs", "chart_state": "idle", "#,
        r#""transition_id": null, "chart_path": "/orchestrator", "region": null}"#,
        "\n",
        r#"{"cycle": 12, "signal": "dut.cs", "chart_state": "arming", "#,
        r#""transition_id": "t1", "chart_path": "/orchestrator", "region": null, "#,
        r#""invariant_id": "INV-S-CHART-3"}"#,
        "\n",
    );

    #[test]
    fn parses_simple_overlay() {
        let (header, records) = parse_overlay(SIMPLE_OVERLAY).unwrap();
        assert_eq!(header.meta.schema, SCHEMA_NAME);
        assert_eq!(header.meta.version, SCHEMA_VERSION);
        assert_eq!(
            header.meta.waveform_prefix.as_deref(),
            Some("test_demo_fsm")
        );
        assert_eq!(records.len(), 2);
        assert_eq!(records[1].invariant_id.as_deref(), Some("INV-S-CHART-3"));
    }

    #[test]
    fn rejects_unknown_schema() {
        let bad = concat!(
            r#"{"_meta": {"schema": "other/schema", "version": "1.0"}}"#,
            "\n",
        );
        match parse_overlay(bad) {
            Err(LoadError::BadSchema { .. }) => {}
            _ => panic!("expected BadSchema"),
        }
    }

    #[test]
    fn renders_commands_includes_marker_and_overlay() {
        let (_, records) = parse_overlay(SIMPLE_OVERLAY).unwrap();
        let cmds = render_commands(&records);
        // At least two markers (one per record) + at least one
        // overlay track ("sos:/orchestrator") + invariant track.
        assert!(cmds
            .iter()
            .filter(|c| matches!(c, SurferCommand::Marker { .. }))
            .count()
            >= 2);
        assert!(cmds
            .iter()
            .any(|c| matches!(c, SurferCommand::AddOverlayTrack { name } if name == "sos:/orchestrator")));
        assert!(cmds
            .iter()
            .any(|c| matches!(c, SurferCommand::AddOverlayTrack { name } if name == "sos:invariants")));
        assert!(cmds
            .iter()
            .any(|c| matches!(c, SurferCommand::MarkInvariant { .. })));
    }

    const OVERLAY_WITH_VECTOR_SOURCE: &str = concat!(
        r#"{"_meta": {"schema": "sos-08-g/annotations", "version": "1.0", "#,
        r#""vector_source": "vectors/0001-two-tasks-yield.json"}}"#,
        "\n",
        r#"{"cycle": 5, "signal": "dut.cs", "chart_state": "idle", "#,
        r#""transition_id": null, "chart_path": "/orchestrator", "region": null, "#,
        r#""vector_index": 0}"#,
        "\n",
        r#"{"cycle": 17, "signal": "dut.cs", "chart_state": "running", "#,
        r#""transition_id": "t1", "chart_path": "/orchestrator", "region": null, "#,
        r#""vector_index": 2}"#,
        "\n",
        r#"{"cycle": 23, "signal": "dut.cs", "chart_state": "done", "#,
        r#""transition_id": null, "chart_path": "/orchestrator", "region": null}"#,
        "\n",
    );

    #[test]
    fn parses_vector_source_from_header() {
        // SOS-08-G wave-3c-future §15 (2026-05-24): `_meta.vector_source`
        // is the per-overlay drill-down link target.
        let (header, records) = parse_overlay(OVERLAY_WITH_VECTOR_SOURCE).unwrap();
        assert_eq!(
            header.meta.vector_source.as_deref(),
            Some("vectors/0001-two-tasks-yield.json"),
        );
        assert_eq!(records.len(), 3);
        assert_eq!(records[0].vector_index, Some(0));
        assert_eq!(records[1].vector_index, Some(2));
        assert_eq!(records[2].vector_index, None);
    }

    #[test]
    fn open_vector_source_commands_emitted_when_threaded() {
        let (header, records) = parse_overlay(OVERLAY_WITH_VECTOR_SOURCE).unwrap();
        let cmds = render_commands_with_vector_source(
            &records,
            header.meta.vector_source.as_deref(),
        );
        let openings: Vec<&SurferCommand> = cmds
            .iter()
            .filter(|c| matches!(c, SurferCommand::OpenVectorSource { .. }))
            .collect();
        // Two records carry `vector_index`; the third doesn't.
        assert_eq!(openings.len(), 2);
        // First emit corresponds to the cycle=5 record (vector_index=0).
        match openings[0] {
            SurferCommand::OpenVectorSource {
                vector_source,
                vector_index,
                time,
                chart_state,
            } => {
                assert_eq!(vector_source, "vectors/0001-two-tasks-yield.json");
                assert_eq!(*vector_index, 0);
                assert_eq!(*time, 5);
                assert_eq!(chart_state, "idle");
            }
            _ => panic!("expected OpenVectorSource"),
        }
    }

    #[test]
    fn open_vector_source_omitted_when_vector_source_absent() {
        // Backwards-compat: legacy overlays without `_meta.vector_source`
        // do NOT emit drill-down commands — the wave-3c emit shape is
        // unchanged for them.
        let (_, records) = parse_overlay(SIMPLE_OVERLAY).unwrap();
        let cmds = render_commands_with_vector_source(&records, None);
        assert!(
            !cmds
                .iter()
                .any(|c| matches!(c, SurferCommand::OpenVectorSource { .. })),
            "OpenVectorSource MUST NOT emit without _meta.vector_source"
        );
    }

    #[test]
    fn open_vector_source_omitted_for_empty_vector_source() {
        let (_, records) = parse_overlay(OVERLAY_WITH_VECTOR_SOURCE).unwrap();
        let cmds = render_commands_with_vector_source(&records, Some(""));
        assert!(
            !cmds
                .iter()
                .any(|c| matches!(c, SurferCommand::OpenVectorSource { .. })),
            "empty vector_source string MUST NOT trigger drill-down emit"
        );
    }

    #[test]
    fn render_commands_legacy_signature_omits_drill_down() {
        // Legacy `render_commands(records)` callers receive the wave-3c
        // emit shape verbatim — no OpenVectorSource even when records
        // carry vector_index.
        let (_, records) = parse_overlay(OVERLAY_WITH_VECTOR_SOURCE).unwrap();
        let cmds = render_commands(&records);
        assert!(
            !cmds
                .iter()
                .any(|c| matches!(c, SurferCommand::OpenVectorSource { .. })),
            "render_commands() (no vector_source arg) MUST NOT emit drill-down"
        );
    }

    #[test]
    fn chart_path_truncates_at_max_depth() {
        let mut segs = Vec::new();
        for i in 0..20 {
            segs.push(format!("seg{i}"));
        }
        let cp = ChartPath::Segments(segs);
        let s = cp.to_path_string();
        let count = s.matches('/').count();
        // Leading `/` + 8 segments → 8 slashes.
        assert_eq!(count, CHART_PATH_MAX_DEPTH);
    }
}
