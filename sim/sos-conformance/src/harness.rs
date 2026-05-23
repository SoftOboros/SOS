//! Harness orchestrator — drives a port binary through every
//! (filter-matching) vector and collects per-vector diff records.
//!
//! See SOS-03 §7 (harness behaviour), §7.2 (exit codes), §7.6 (port-binary
//! contract). v1 runs vectors **sequentially** per INV-S-CONF-7.

use std::path::{Path, PathBuf};

use crate::diff::{structural_diff_traces, DiffRecord, DiffSeverity};
use crate::filter::Filter;
use crate::port::{InProcessPort, Port, SubprocessPort};
use crate::vector_file::VectorFile;

/// Harness driver. Configured once per invocation; sequential per
/// INV-S-CONF-7.
pub struct Harness {
    /// Suite root scanned for `*.json` vectors (excluding `retired/`).
    pub suite: PathBuf,
    /// Optional port binary path (`None` invokes `InProcessPort` as a
    /// degenerate self-test).
    pub port: Option<PathBuf>,
    /// Optional `globset`-syntax filter applied to relative vector paths.
    pub filter: Option<String>,
}

impl Harness {
    /// Construct a harness configured for `suite`, `port`, and `filter`.
    pub fn new(suite: PathBuf, port: Option<PathBuf>, filter: Option<String>) -> Self {
        Self {
            suite,
            port,
            filter,
        }
    }

    /// Walk the suite, run each matched vector against the port, and
    /// collect a summary report.
    pub fn run(&self) -> anyhow::Result<HarnessReport> {
        // Build the filter (default: match everything).
        let pattern = self.filter.as_deref().unwrap_or("");
        let filter = Filter::from_pattern(pattern)?;

        // Discover vector files. Recursive walk; skip any path that
        // contains a `retired/` component per SOS-03 §6.1.
        let mut vector_paths: Vec<PathBuf> = Vec::new();
        walk_suite(&self.suite, &self.suite, &mut vector_paths)?;
        vector_paths.sort();

        let mut total = 0usize;
        let mut passed = 0usize;
        let mut failed: Vec<DiffRecord> = Vec::new();
        let mut per_vector: Vec<VectorOutcome> = Vec::new();

        for path in &vector_paths {
            let rel = path
                .strip_prefix(&self.suite)
                .unwrap_or(path)
                .to_string_lossy()
                .into_owned();
            if !filter.matches(&rel) {
                continue;
            }
            total += 1;
            let vec = match VectorFile::from_path(path) {
                Ok(v) => v,
                Err(e) => {
                    return Err(anyhow::anyhow!(
                        "vector load failed for {}: {e}",
                        path.display()
                    ));
                }
            };
            let stem = path
                .file_stem()
                .and_then(|s| s.to_str())
                .unwrap_or("<unknown>")
                .to_string();
            let diffs = self.run_one(&vec)?;
            if diffs.is_empty() {
                passed += 1;
                per_vector.push(VectorOutcome {
                    relative_path: rel,
                    vector_stem: stem,
                    diff_count: 0,
                });
            } else {
                per_vector.push(VectorOutcome {
                    relative_path: rel.clone(),
                    vector_stem: stem,
                    diff_count: diffs.len(),
                });
                for mut d in diffs {
                    d.vector_name = rel.clone();
                    failed.push(d);
                }
            }
        }

        Ok(HarnessReport {
            total,
            passed,
            failed,
            per_vector,
        })
    }

    /// Run one vector against the port and return its diff records.
    /// Empty `Vec` denotes a pass (every record matches).
    pub fn run_one(&self, vec: &VectorFile) -> anyhow::Result<Vec<DiffRecord>> {
        let actual = match &self.port {
            None => InProcessPort.execute_vector(vec)?,
            Some(bin) => SubprocessPort {
                binary: bin.clone(),
            }
            .execute_vector(vec)?,
        };
        let diffs = structural_diff_traces(&vec.expected_trace, &actual);
        Ok(diffs)
    }
}

/// Recursive suite walker. Collects `*.json` paths and skips any path
/// containing a `retired/` segment per SOS-03 §6.1.
fn walk_suite(root: &Path, dir: &Path, out: &mut Vec<PathBuf>) -> anyhow::Result<()> {
    let read = std::fs::read_dir(dir)
        .map_err(|e| anyhow::anyhow!("failed to read suite dir {}: {e}", dir.display()))?;
    for entry in read {
        let entry = entry?;
        let path = entry.path();
        let file_type = entry.file_type()?;
        if file_type.is_dir() {
            // Skip `retired/` at any depth.
            if let Some(name) = path.file_name().and_then(|n| n.to_str()) {
                if name == "retired" {
                    continue;
                }
            }
            walk_suite(root, &path, out)?;
        } else if file_type.is_file() {
            if path.extension().and_then(|e| e.to_str()) == Some("json") {
                out.push(path);
            }
        }
    }
    Ok(())
}

/// Per-vector outcome row used by the human-format reporter.
#[derive(Debug, Clone)]
pub struct VectorOutcome {
    /// Path relative to the suite root.
    pub relative_path: String,
    /// File stem (filename without `.json` suffix).
    pub vector_stem: String,
    /// Number of diff records (0 = pass).
    pub diff_count: usize,
}

/// Suite-level summary — passes / fails / per-vector outcomes. Mirrors
/// the `--format json` rollup of SOS-03 §7.3.
pub struct HarnessReport {
    /// Total vectors scanned (post-filter).
    pub total: usize,
    /// Count that matched their `expected_trace` exactly.
    pub passed: usize,
    /// Flat list of every failing diff record across every failed vector.
    pub failed: Vec<DiffRecord>,
    /// One row per executed vector — used by the human reporter.
    pub per_vector: Vec<VectorOutcome>,
}

impl HarnessReport {
    /// Convenience — does the report represent a clean pass?
    pub fn is_pass(&self) -> bool {
        self.failed.is_empty() && self.passed == self.total
    }

    /// Group failing diff records by their vector-relative path.
    pub fn failures_by_vector(&self) -> Vec<(String, Vec<&DiffRecord>)> {
        let mut grouped: std::collections::BTreeMap<String, Vec<&DiffRecord>> =
            std::collections::BTreeMap::new();
        for d in &self.failed {
            grouped
                .entry(d.vector_name.clone())
                .or_default()
                .push(d);
        }
        grouped.into_iter().collect()
    }

    /// Render a serialisable summary suitable for `--format json`.
    pub fn to_json_value(&self, suite_root: &str, port_binary: &str, filter: &str) -> serde_json::Value {
        let failures: Vec<serde_json::Value> = self
            .failures_by_vector()
            .into_iter()
            .map(|(vector, diffs)| {
                let diff_objs: Vec<serde_json::Value> = diffs
                    .iter()
                    .map(|d| {
                        serde_json::json!({
                            "severity": severity_str(d.severity),
                            "field_path": d.field_path,
                            "expected": d.expected,
                            "actual": d.actual,
                        })
                    })
                    .collect();
                serde_json::json!({
                    "vector": vector,
                    "diffs": diff_objs,
                })
            })
            .collect();
        serde_json::json!({
            "schema_version": 1,
            "suite_root": suite_root,
            "port_binary": port_binary,
            "filter": filter,
            "vectors_scanned": self.total,
            "vectors_run": self.total,
            "vectors_passed": self.passed,
            "vectors_failed": self.total.saturating_sub(self.passed),
            "failures": failures,
        })
    }
}

fn severity_str(s: DiffSeverity) -> &'static str {
    match s {
        DiffSeverity::Exact => "exact",
        DiffSeverity::BytesDiffer => "bytes_differ",
        DiffSeverity::RecordCountMismatch => "record_count_mismatch",
        DiffSeverity::ParseError => "parse_error",
    }
}
