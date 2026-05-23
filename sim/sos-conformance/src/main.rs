//! `sos-conformance` — host-runnable CLI binary for the SOS conformance
//! harness.
//!
//! See SOS-03 §7.1 for the CLI grammar (`run --suite <DIR>
//! [--port <BIN>] [--filter <GLOB>] [--format <FORMAT>] [--out <PATH>]`)
//! and §7.2 for the exit-code table. v1 implements the `run` subcommand
//! body; `generate` and `lint` are reserved subcommand slots.

use std::fs::File;
use std::io::{self, BufWriter, Write};
use std::path::PathBuf;
use std::process::ExitCode;

use clap::{Parser, Subcommand, ValueEnum};

use sos_conformance::{Harness, HarnessReport};

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

/// Subcommands. v1 ships `run` only; `generate` and `lint` are reserved.
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
    /// Reserved: regenerate a vector's `expected_trace` by running
    /// `sos-sim` over its `input`. Lands in a follow-up commit.
    Generate {
        /// Path to the vector file to regenerate.
        #[arg(long)]
        vector: PathBuf,
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
        Cmd::Generate { .. } => {
            let _ = writeln!(io::stderr(), "`generate` subcommand not implemented at v1");
            EXIT_SETUP
        }
        Cmd::Lint { .. } => {
            let _ = writeln!(io::stderr(), "`lint` subcommand not implemented at v1");
            EXIT_SETUP
        }
    };
    ExitCode::from(code)
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
        let _ = writeln!(io::stderr(), "suite directory does not exist: {}", suite.display());
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
        OutputFormat::Human => render_human(&report, &suite, port.as_deref(), filter.as_deref(), out.as_deref()),
        OutputFormat::Json => render_json(&report, &suite, port.as_deref(), filter.as_deref(), out.as_deref()),
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
    writeln!(w, "SOS-CONFORMANCE  suite: {}  port: {}", suite.display(), port_disp)?;
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
