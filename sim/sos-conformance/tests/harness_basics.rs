//! Smoke tests for the harness internals — one test per
//! implementation slot per SOS-03 §12.2 (l).
//!
//! The conformance suite itself is the integration test surface and is
//! exercised by `sos-conformance run --suite ...`; these unit tests cover
//! the harness primitives (loader, diff, filter, port, harness). The six
//! seed fixtures under `conformance/vectors/smoke/` remain the smoke
//! baseline.

use std::path::PathBuf;

use sos_conformance::{
    structural_diff_traces, DiffSeverity, Filter, Harness, InProcessPort, Port, VectorCategory,
    VectorFile, VectorOrigin,
};

/// Locate the repo's conformance/vectors directory by walking up from
/// `CARGO_MANIFEST_DIR` (`sim/sos-conformance/`).
fn suite_root() -> PathBuf {
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    manifest
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .join("conformance")
        .join("vectors")
}

fn first_seed_vector_path() -> PathBuf {
    suite_root()
        .join("smoke")
        .join("0001-two-tasks-same-prio-alternate-via-yield.json")
}

// ---------------------------------------------------------------------------
// Slot 1: VectorFile::from_path + vector_id_from_filename
// ---------------------------------------------------------------------------

#[test]
fn vector_file_loader_parses_seed_fixture() {
    let p = first_seed_vector_path();
    let v = VectorFile::from_path(&p).expect("must load");
    assert_eq!(v.name, "two-tasks-same-prio-alternate-via-yield");
    assert!(matches!(v.category, VectorCategory::Smoke));
    assert!(matches!(v.origin, VectorOrigin::Seed));
    // expected_trace length is len(input) + 1 per SOS-03 §6.2.
    assert_eq!(v.expected_trace.len(), v.input.len() + 1);
    // ID extracted from the filename.
    assert_eq!(VectorFile::vector_id_from_filename(&p), Some(1));
    // Non-conforming filenames return None.
    assert_eq!(
        VectorFile::vector_id_from_filename(std::path::Path::new("nope.json")),
        None
    );
    assert_eq!(
        VectorFile::vector_id_from_filename(std::path::Path::new("0123-slug.json")),
        Some(123)
    );
}

// ---------------------------------------------------------------------------
// Slot 2: structural_diff_traces
// ---------------------------------------------------------------------------

#[test]
fn structural_diff_detects_value_mismatch_and_count_mismatch() {
    let v = VectorFile::from_path(&first_seed_vector_path()).unwrap();
    // Identical traces produce no diff records.
    let diffs = structural_diff_traces(&v.expected_trace, &v.expected_trace);
    assert!(diffs.is_empty(), "identical traces must diff clean");

    // Mutate one field to ensure we detect bytes_differ with a field_path.
    let mut tweaked = v.expected_trace.clone();
    tweaked[0].current = 99;
    let diffs = structural_diff_traces(&v.expected_trace, &tweaked);
    assert!(!diffs.is_empty(), "tweak must produce a diff");
    assert!(diffs
        .iter()
        .any(|d| d.severity == DiffSeverity::BytesDiffer
            && d.field_path.as_deref() == Some("[0].current")));

    // Shorter trace produces a record_count_mismatch.
    let truncated: Vec<_> = v.expected_trace.iter().take(2).cloned().collect();
    let diffs = structural_diff_traces(&v.expected_trace, &truncated);
    assert!(diffs
        .iter()
        .any(|d| d.severity == DiffSeverity::RecordCountMismatch));
}

// ---------------------------------------------------------------------------
// Slot 3: Filter::from_pattern + Filter::matches
// ---------------------------------------------------------------------------

#[test]
fn filter_globs_compile_and_match_relative_paths() {
    // Empty pattern matches everything.
    let f = Filter::from_pattern("").unwrap();
    assert!(f.matches("smoke/0001-foo.json"));
    assert!(f.matches("boundary/0099.json"));

    // Single glob — match only smoke/.
    let f = Filter::from_pattern("smoke/*").unwrap();
    assert!(f.matches("smoke/0001-foo.json"));
    assert!(!f.matches("boundary/0099-bar.json"));

    // Comma-separated multi-pattern.
    let f = Filter::from_pattern("smoke/*,regression/*").unwrap();
    assert!(f.matches("smoke/0001-foo.json"));
    assert!(f.matches("regression/0001-bar.json"));
    assert!(!f.matches("boundary/0001-bar.json"));

    // Invalid glob surfaces as anyhow::Error.
    assert!(Filter::from_pattern("[unterminated").is_err());
}

// ---------------------------------------------------------------------------
// Slot 4: InProcessPort::execute_vector
// ---------------------------------------------------------------------------

#[test]
fn in_process_port_reproduces_committed_trace() {
    let v = VectorFile::from_path(&first_seed_vector_path()).unwrap();
    let actual = InProcessPort.execute_vector(&v).unwrap();
    let diffs = structural_diff_traces(&v.expected_trace, &actual);
    assert!(
        diffs.is_empty(),
        "in-process port must reproduce committed trace exactly; got {} diffs",
        diffs.len()
    );
}

// ---------------------------------------------------------------------------
// Slot 5: SubprocessPort::execute_vector
// ---------------------------------------------------------------------------

#[test]
fn subprocess_port_reports_missing_binary_as_spawn_error() {
    use sos_conformance::SubprocessPort;
    let port = SubprocessPort {
        binary: PathBuf::from("/no/such/binary/please-do-not-exist"),
    };
    let v = VectorFile::from_path(&first_seed_vector_path()).unwrap();
    let err = port.execute_vector(&v).unwrap_err();
    let msg = format!("{err}");
    assert!(
        msg.contains("failed to spawn port binary"),
        "expected spawn failure message, got: {msg}"
    );
}

// ---------------------------------------------------------------------------
// Slot 6: Harness::run + run_one
// ---------------------------------------------------------------------------

#[test]
fn harness_run_against_in_process_port_passes_full_suite() {
    let smoke_harness = Harness::new(suite_root(), None, Some("smoke/*.json".to_string()));
    let smoke_report = smoke_harness.run().expect("smoke harness run must succeed");
    assert_eq!(smoke_report.total, 6, "expect six smoke seed vectors");
    assert_eq!(
        smoke_report.passed, 6,
        "in-process port must pass every smoke committed-trace vector"
    );
    assert!(smoke_report.failed.is_empty());
    assert!(smoke_report.is_pass());

    let full_harness = Harness::new(suite_root(), None, None);
    let report = full_harness.run().expect("full harness run must succeed");
    assert_eq!(
        report.total, 7,
        "expect six smoke vectors plus DAA-08 diversity vector"
    );
    assert_eq!(
        report.passed, 7,
        "in-process port must pass every committed-trace vector"
    );
    assert!(report
        .per_vector
        .iter()
        .any(|v| v.relative_path == "diversity/0001-daa08-analyzer-two-task-hsem-wake.json"));
    assert!(report.failed.is_empty());
    assert!(report.is_pass());
}
