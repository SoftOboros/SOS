//! Diff types and structural-comparison policy — SOS-03 §6.5 and §5.3.
//!
//! The harness's diff is **structural per record**, NOT byte-exact at the
//! stream level (PCDN-SOS-03-001). Each leaf mismatch surfaces as one
//! [`DiffRecord`] with a precise `field_path`; record-count and parse-error
//! failures use the corresponding [`DiffSeverity`] variant.

use serde::{Deserialize, Serialize};

/// Defensive cap on the number of `DiffRecord` entries a single
/// `structural_diff_traces` call emits. Large diffs are rarely useful;
/// the cap protects against pathological cases where every field differs
/// across every record.
const MAX_DIFF_RECORDS: usize = 100;

/// Severity of one diff record — four-value frozen enum per SOS-03 §5.3
/// (Specification Required).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DiffSeverity {
    /// Port record matches expected record byte-for-byte. Non-failure;
    /// surfaces only in `--format json` for distinguishing checked-and-
    /// matched from unchecked (SOS-03 §5.3).
    Exact,
    /// Same structure, at least one value differs at a named `field_path`
    /// (SOS-03 §5.3). The common failure mode.
    BytesDiffer,
    /// Port emitted fewer or more records than expected (SOS-03 §5.3).
    RecordCountMismatch,
    /// Port stdout could not be parsed as JSONL (SOS-03 §5.3).
    ParseError,
}

/// One structured diff record reported by the harness. Mirrors the
/// `failures[].diffs[]` element of SOS-03 §7.3's `--format json` output.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DiffRecord {
    /// Vector path relative to the suite root (e.g.
    /// `smoke/0004-queue-full-empty-rejection-vs-block-timeout`).
    pub vector_name: String,
    /// Severity classification.
    pub severity: DiffSeverity,
    /// Dot-bracket path into the trace record (e.g. `tcb[2].state`).
    /// `None` for structural failures (`RecordCountMismatch`,
    /// `ParseError`).
    pub field_path: Option<String>,
    /// Expected value at `field_path`.
    pub expected: serde_json::Value,
    /// Actual value at `field_path`.
    pub actual: serde_json::Value,
}

/// Compare an expected trace and an actual trace structurally per
/// SOS-03 §6.5. Each leaf mismatch emits one [`DiffRecord`]; the harness
/// does NOT stop at the first diff per record. Capped at
/// [`MAX_DIFF_RECORDS`] defensive limit (SOS-03 §6.5 narrative).
pub fn structural_diff_traces(
    expected: &[sos_sim::TraceRecord],
    actual: &[sos_sim::TraceRecord],
) -> Vec<DiffRecord> {
    let mut diffs: Vec<DiffRecord> = Vec::new();

    if expected.len() != actual.len() {
        diffs.push(DiffRecord {
            vector_name: String::new(),
            severity: DiffSeverity::RecordCountMismatch,
            field_path: None,
            expected: serde_json::Value::from(expected.len()),
            actual: serde_json::Value::from(actual.len()),
        });
    }

    let prefix_len = expected.len().min(actual.len());
    for k in 0..prefix_len {
        if diffs.len() >= MAX_DIFF_RECORDS {
            return diffs;
        }
        // Serialise each record to a `serde_json::Value` and walk
        // structurally. Per SOS-03 §6.5 we walk objects + arrays and
        // compare leaves with `==`. `serde_json::to_value` cannot fail
        // for our types (no NaN floats, no map-with-non-string-keys).
        let exp = serde_json::to_value(&expected[k]).expect("TraceRecord must serialise");
        let act = serde_json::to_value(&actual[k]).expect("TraceRecord must serialise");
        let prefix = format!("[{k}]");
        walk(&prefix, &exp, &act, &mut diffs);
    }

    diffs
}

/// Recursively walk two `serde_json::Value` trees, emitting one
/// `DiffRecord` per leaf mismatch into `out`. Stops appending past
/// `MAX_DIFF_RECORDS`.
fn walk(
    path: &str,
    expected: &serde_json::Value,
    actual: &serde_json::Value,
    out: &mut Vec<DiffRecord>,
) {
    if out.len() >= MAX_DIFF_RECORDS {
        return;
    }
    match (expected, actual) {
        (serde_json::Value::Object(e_map), serde_json::Value::Object(a_map)) => {
            // Walk every key in either map. Per SOS-03 §6.5 we walk the
            // canonical field order from `expected`; any key only in
            // `actual` surfaces as a mismatch via the Null/value compare.
            let mut keys: Vec<&String> = e_map.keys().collect();
            for k in a_map.keys() {
                if !e_map.contains_key(k) {
                    keys.push(k);
                }
            }
            for k in keys {
                if out.len() >= MAX_DIFF_RECORDS {
                    return;
                }
                let child_path = format!("{path}.{k}");
                let e_child = e_map.get(k).unwrap_or(&serde_json::Value::Null);
                let a_child = a_map.get(k).unwrap_or(&serde_json::Value::Null);
                walk(&child_path, e_child, a_child, out);
            }
        }
        (serde_json::Value::Array(e_arr), serde_json::Value::Array(a_arr)) => {
            if e_arr.len() != a_arr.len() {
                // Array length mismatch is itself a leaf-level diff —
                // we record the whole arrays at this path. This keeps
                // diagnostic information local.
                out.push(DiffRecord {
                    vector_name: String::new(),
                    severity: DiffSeverity::BytesDiffer,
                    field_path: Some(path.to_string()),
                    expected: expected.clone(),
                    actual: actual.clone(),
                });
                return;
            }
            for (i, (e_child, a_child)) in e_arr.iter().zip(a_arr.iter()).enumerate() {
                if out.len() >= MAX_DIFF_RECORDS {
                    return;
                }
                let child_path = format!("{path}[{i}]");
                walk(&child_path, e_child, a_child, out);
            }
        }
        (e, a) => {
            if e != a {
                out.push(DiffRecord {
                    vector_name: String::new(),
                    severity: DiffSeverity::BytesDiffer,
                    field_path: Some(path.to_string()),
                    expected: e.clone(),
                    actual: a.clone(),
                });
            }
        }
    }
}
