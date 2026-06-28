//! `sos-conformance` — host-runnable CLI binary for the SOS conformance
//! harness.
//!
//! See SOS-03 §7.1 for the CLI grammar (`run --suite <DIR>
//! [--port <BIN>] [--filter <GLOB>] [--format <FORMAT>] [--out <PATH>]`)
//! and §7.2 for the exit-code table. v1 implements the `run` and
//! `generate` subcommands; `lint` is a reserved subcommand slot.

use std::fs::File;
use std::io::{self, BufWriter, Write};
use std::path::{Path, PathBuf};
use std::process::ExitCode;

use clap::{Parser, Subcommand, ValueEnum};

use sos_conformance::{Harness, HarnessReport, InProcessPort, Port, VectorFile};

/// SOS-03 §7.2 exit codes.
const EXIT_OK: u8 = 0;
const EXIT_SETUP: u8 = 1;
const EXIT_VECTOR_FAIL: u8 = 2;
const EXIT_PORT_MISSING: u8 = 3;
const EXIT_IO: u8 = 4;

/// Top-level CLI grammar.
#[derive(Debug, Parser)]
#[command(
    name = "sos-conformance",
    version,
    about = "SOS conformance vector suite harness (SOS-03)"
)]
struct Cli {
    /// Subcommand.
    #[command(subcommand)]
    cmd: Cmd,
}

/// Subcommands. v1 ships `run` and `generate`; `lint` is reserved.
#[derive(Debug, Subcommand)]
enum Cmd {
    /// Run every (filter-matching) vector in the suite directory against
    /// the named port binary and report pass / fail.
    Run {
        /// Path to the suite root, typically `conformance/vectors/`.
        #[arg(long)]
        suite: PathBuf,
        /// Path to the port binary. Defaults to the in-process simulator
        /// (degenerate self-test) when omitted.
        #[arg(long)]
        port: Option<PathBuf>,
        /// Glob pattern matched against vector paths relative to `--suite`.
        /// Defaults to matching every JSON file per SOS-03 §7.5.
        #[arg(long)]
        filter: Option<String>,
        /// Output format. `human` (default) for terminal consumption,
        /// `json` for CI consumption per SOS-03 §7.3.
        #[arg(long, default_value_t = OutputFormat::Human, value_enum)]
        format: OutputFormat,
        /// Where to write the report. Defaults to stdout.
        #[arg(long)]
        out: Option<PathBuf>,
    },
    /// Regenerate vector `expected_trace` values by running in-process
    /// `sos-sim` over each vector's `input`.
    Generate {
        /// Path to the vector file to regenerate.
        #[arg(value_name = "VECTOR")]
        vector: Option<PathBuf>,
        /// Path to the vector file to regenerate. Compatibility spelling
        /// for the reserved v1 CLI slot.
        #[arg(long = "vector", value_name = "VECTOR")]
        vector_flag: Option<PathBuf>,
        /// Regenerate every JSON vector under this suite root.
        #[arg(long)]
        suite: Option<PathBuf>,
    },
    /// Reserved: validate a vector file against the SOS-03 §6.2 schema
    /// without running it. Lands in a follow-up commit.
    Lint {
        /// Path to the vector file to validate.
        #[arg(long)]
        vector: PathBuf,
    },
}

/// Output format for the harness report.
#[derive(Debug, Clone, Copy, ValueEnum)]
enum OutputFormat {
    /// Multi-line per-failure with summary at the end (SOS-03 §7.3).
    Human,
    /// Single JSON document for CI consumption (SOS-03 §7.3).
    Json,
}

fn main() -> ExitCode {
    let cli = Cli::parse();
    let code = match cli.cmd {
        Cmd::Run {
            suite,
            port,
            filter,
            format,
            out,
        } => run_cmd(suite, port, filter, format, out),
        Cmd::Generate {
            vector,
            vector_flag,
            suite,
        } => generate_cmd(vector, vector_flag, suite),
        Cmd::Lint { .. } => {
            let _ = writeln!(io::stderr(), "`lint` subcommand not implemented at v1");
            EXIT_SETUP
        }
    };
    ExitCode::from(code)
}

fn generate_cmd(
    vector: Option<PathBuf>,
    vector_flag: Option<PathBuf>,
    suite: Option<PathBuf>,
) -> u8 {
    let mut targets: Vec<PathBuf> = Vec::new();

    match (vector, vector_flag, suite) {
        (Some(v), None, None) | (None, Some(v), None) => {
            targets.push(v);
        }
        (None, None, Some(suite)) => {
            if !suite.exists() {
                let _ = writeln!(
                    io::stderr(),
                    "suite directory does not exist: {}",
                    suite.display()
                );
                return EXIT_SETUP;
            }
            if let Err(e) = collect_vector_paths(&suite, &mut targets) {
                let _ = writeln!(io::stderr(), "suite walk failed: {e}");
                return EXIT_IO;
            }
        }
        (None, None, None) => {
            let _ = writeln!(
                io::stderr(),
                "generate requires a VECTOR path or --suite <DIR>"
            );
            return EXIT_SETUP;
        }
        _ => {
            let _ = writeln!(
                io::stderr(),
                "generate accepts exactly one of VECTOR, --vector <VECTOR>, or --suite <DIR>"
            );
            return EXIT_SETUP;
        }
    }

    targets.sort();
    let mut generated = 0usize;
    for path in targets {
        match generate_one(&path) {
            Ok(record_count) => {
                generated += 1;
                println!(
                    "GENERATED  {}  ({} trace records)",
                    path.display(),
                    record_count
                );
            }
            Err(e) => {
                let _ = writeln!(io::stderr(), "generate failed for {}: {e}", path.display());
                return EXIT_SETUP;
            }
        }
    }
    println!("RESULT: GENERATED {generated} vector(s)");
    EXIT_OK
}

fn generate_one(path: &Path) -> anyhow::Result<usize> {
    let mut vec = VectorFile::from_path(path)?;
    let expected_trace = InProcessPort.execute_vector(&vec)?;
    let record_count = expected_trace.len();
    vec.expected_trace = expected_trace;

    let mut writer = BufWriter::new(File::create(path).map_err(|e| {
        anyhow::anyhow!(
            "failed to open vector file for write {}: {e}",
            path.display()
        )
    })?);
    serde_json::to_writer_pretty(&mut writer, &vec).map_err(|e| {
        anyhow::anyhow!(
            "failed to serialize generated vector {}: {e}",
            path.display()
        )
    })?;
    writeln!(writer)?;
    writer.flush()?;
    Ok(record_count)
}

fn collect_vector_paths(root: &Path, out: &mut Vec<PathBuf>) -> io::Result<()> {
    let read = std::fs::read_dir(root)?;
    for entry in read {
        let entry = entry?;
        let path = entry.path();
        let file_type = entry.file_type()?;
        if file_type.is_dir() {
            if path.file_name().and_then(|name| name.to_str()) == Some("retired") {
                continue;
            }
            collect_vector_paths(&path, out)?;
        } else if file_type.is_file()
            && path.extension().and_then(|ext| ext.to_str()) == Some("json")
        {
            out.push(path);
        }
    }
    Ok(())
}

fn run_cmd(
    suite: PathBuf,
    port: Option<PathBuf>,
    filter: Option<String>,
    format: OutputFormat,
    out: Option<PathBuf>,
) -> u8 {
    // Pre-flight: suite must exist.
    if !suite.exists() {
        let _ = writeln!(
            io::stderr(),
            "suite directory does not exist: {}",
            suite.display()
        );
        return EXIT_SETUP;
    }
    // Pre-flight: port (if specified) must exist and be a file.
    if let Some(p) = &port {
        if !p.exists() {
            let _ = writeln!(io::stderr(), "port binary not found: {}", p.display());
            return EXIT_PORT_MISSING;
        }
    }

    let harness = Harness::new(suite.clone(), port.clone(), filter.clone());
    let report = match harness.run() {
        Ok(r) => r,
        Err(e) => {
            // Distinguish port-spawn failures from generic setup errors
            // by best-effort message inspection. The port-spawn path in
            // `SubprocessPort::execute_vector` returns "failed to spawn
            // port binary" when exec() itself fails.
            let msg = format!("{e}");
            if msg.contains("failed to spawn port binary") {
                let _ = writeln!(io::stderr(), "{msg}");
                return EXIT_PORT_MISSING;
            }
            let _ = writeln!(io::stderr(), "harness error: {msg}");
            return EXIT_SETUP;
        }
    };

    // Render the report to the requested sink.
    let render_result = match format {
        OutputFormat::Human => render_human(
            &report,
            &suite,
            port.as_deref(),
            filter.as_deref(),
            out.as_deref(),
        ),
        OutputFormat::Json => render_json(
            &report,
            &suite,
            port.as_deref(),
            filter.as_deref(),
            out.as_deref(),
        ),
    };
    if let Err(e) = render_result {
        let _ = writeln!(io::stderr(), "I/O error rendering report: {e}");
        return EXIT_IO;
    }

    if report.is_pass() {
        EXIT_OK
    } else {
        EXIT_VECTOR_FAIL
    }
}

fn open_writer(out: Option<&std::path::Path>) -> io::Result<Box<dyn Write>> {
    match out {
        None => Ok(Box::new(io::stdout().lock())),
        Some(p) => Ok(Box::new(BufWriter::new(File::create(p)?))),
    }
}

fn render_human(
    report: &HarnessReport,
    suite: &std::path::Path,
    port: Option<&std::path::Path>,
    filter: Option<&str>,
    out: Option<&std::path::Path>,
) -> io::Result<()> {
    let mut w = open_writer(out)?;
    let port_disp = match port {
        Some(p) => p.display().to_string(),
        None => "<in-process sos-sim>".to_string(),
    };
    writeln!(
        w,
        "SOS-CONFORMANCE  suite: {}  port: {}",
        suite.display(),
        port_disp
    )?;
    writeln!(w, "Filter: {}", filter.unwrap_or("**/*.json"))?;
    writeln!(
        w,
        "Vectors run: {} ({} pass, {} fail)",
        report.total,
        report.passed,
        report.total.saturating_sub(report.passed)
    )?;
    writeln!(w)?;

    let failures = report.failures_by_vector();
    let failed_set: std::collections::BTreeSet<String> =
        failures.iter().map(|(v, _)| v.clone()).collect();

    for outcome in &report.per_vector {
        if failed_set.contains(&outcome.relative_path) {
            writeln!(w, "FAIL  {}", outcome.vector_stem)?;
        } else {
            writeln!(w, "PASS  {}", outcome.vector_stem)?;
        }
    }
    writeln!(w)?;

    for (vector, diffs) in &failures {
        writeln!(w, "-- {} ({} diffs)", vector, diffs.len())?;
        for d in diffs {
            match d.field_path.as_deref() {
                Some(path) => writeln!(
                    w,
                    "    {} at {}: expected {} actual {}",
                    severity_str(d.severity),
                    path,
                    d.expected,
                    d.actual
                )?,
                None => writeln!(
                    w,
                    "    {}: expected {} actual {}",
                    severity_str(d.severity),
                    d.expected,
                    d.actual
                )?,
            }
        }
    }

    if report.is_pass() {
        writeln!(w, "RESULT: ALL PASS")?;
    } else {
        writeln!(w, "RESULT: FAIL")?;
    }
    w.flush()?;
    Ok(())
}

fn render_json(
    report: &HarnessReport,
    suite: &std::path::Path,
    port: Option<&std::path::Path>,
    filter: Option<&str>,
    out: Option<&std::path::Path>,
) -> io::Result<()> {
    let mut w = open_writer(out)?;
    let port_str = match port {
        Some(p) => p.display().to_string(),
        None => "<in-process sos-sim>".to_string(),
    };
    let filter_str = filter.unwrap_or("**/*.json");
    let value = report.to_json_value(&suite.display().to_string(), &port_str, filter_str);
    serde_json::to_writer_pretty(&mut w, &value).map_err(io::Error::from)?;
    writeln!(w)?;
    w.flush()?;
    Ok(())
}

fn severity_str(s: sos_conformance::DiffSeverity) -> &'static str {
    match s {
        sos_conformance::DiffSeverity::Exact => "exact",
        sos_conformance::DiffSeverity::BytesDiffer => "bytes_differ",
        sos_conformance::DiffSeverity::RecordCountMismatch => "record_count_mismatch",
        sos_conformance::DiffSeverity::ParseError => "parse_error",
    }
}
