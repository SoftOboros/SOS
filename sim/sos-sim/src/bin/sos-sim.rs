//! `sos-sim` — host-runnable CLI binary for the SOS reference simulator.
//!
//! See SOS-02 §6.6 for the CLI grammar (`run --vector <path> [--out <path>]
//! [--format <format>]`) and exit-code table. v1 implements only the
//! `jsonl` format and the `run` subcommand; reserved values reject with
//! exit code 4.

use std::fs;
use std::io::{self, BufWriter, Read, Write};
use std::path::PathBuf;
use std::process;

use clap::{Parser, Subcommand};

use sos_sim::error::SimError;
use sos_sim::{HandCompiledScripts, Simulator, Vector};

/// SOS-02 §6.6 exit codes.
const EXIT_OK: i32 = 0;
const EXIT_VECTOR_PARSE: i32 = 1;
const EXIT_RUNTIME: i32 = 2;
const EXIT_IO: i32 = 3;
const EXIT_UNSUPPORTED_FORMAT: i32 = 4;

/// Top-level CLI grammar.
#[derive(Debug, Parser)]
#[command(name = "sos-sim", version, about = "SOS host simulator (SOS-02)")]
struct Cli {
    /// Subcommand.
    #[command(subcommand)]
    cmd: Cmd,
}

/// Subcommands. v1 ships `run` only.
#[derive(Debug, Subcommand)]
enum Cmd {
    /// Run a vector to completion and emit its trace.
    Run {
        /// Path to the vector JSON file. Use `-` to read from stdin
        /// (entire file is buffered before parsing — PreLoaded mode).
        #[arg(long)]
        vector: String,
        /// Path to write the trace. Use `-` (or omit) for stdout.
        #[arg(long)]
        out: Option<String>,
        /// Trace serialisation format. v1 only accepts `jsonl`.
        #[arg(long, default_value = "jsonl")]
        format: String,
    },
}

fn main() {
    let cli = Cli::parse();
    let code = match run(cli) {
        Ok(()) => EXIT_OK,
        Err(CliError::VectorParse(msg)) => {
            let _ = writeln!(io::stderr(), "vector parse error: {msg}");
            EXIT_VECTOR_PARSE
        }
        Err(CliError::Runtime(msg)) => {
            let _ = writeln!(io::stderr(), "simulator runtime error: {msg}");
            EXIT_RUNTIME
        }
        Err(CliError::Io(err)) => {
            let _ = writeln!(io::stderr(), "I/O error: {err}");
            EXIT_IO
        }
        Err(CliError::UnsupportedFormat(fmt)) => {
            let _ = writeln!(io::stderr(), "unsupported trace format: {fmt}");
            EXIT_UNSUPPORTED_FORMAT
        }
    };
    process::exit(code);
}

/// CLI-side error enum. Maps onto SOS-02 §6.6 exit codes.
enum CliError {
    VectorParse(String),
    Runtime(String),
    Io(io::Error),
    UnsupportedFormat(String),
}

impl From<SimError> for CliError {
    fn from(err: SimError) -> Self {
        match err {
            SimError::VectorParse(msg) => CliError::VectorParse(msg),
            SimError::Runtime(msg) => CliError::Runtime(msg),
            SimError::Io(e) => CliError::Io(e),
            SimError::Json(e) => CliError::VectorParse(format!("JSON error: {e}")),
        }
    }
}

impl From<io::Error> for CliError {
    fn from(err: io::Error) -> Self {
        CliError::Io(err)
    }
}

fn run(cli: Cli) -> Result<(), CliError> {
    match cli.cmd {
        Cmd::Run {
            vector,
            out,
            format,
        } => run_cmd(&vector, out.as_deref(), &format),
    }
}

fn run_cmd(vector_path: &str, out_path: Option<&str>, format: &str) -> Result<(), CliError> {
    // SOS-02 §6.6: `--format jsonl` is the only accepted value at v1;
    // reserved formats reject with exit code 4.
    match format {
        "jsonl" => {}
        other => return Err(CliError::UnsupportedFormat(other.to_string())),
    }

    // Read the vector source — `-` denotes stdin per SOS-02 §6.6.
    let vector_text = read_vector_source(vector_path)?;
    let vector = Vector::from_json(&vector_text).map_err(CliError::from)?;

    // Construct the simulator (which drives the boot macrostep and
    // emits the baseline trace record).
    let mut sim = Simulator::new(vector.config, HandCompiledScripts::new());

    // Run the vector to completion. Trace accumulates internally; we
    // serialise it after the loop exits per the in-memory emission
    // discipline (SOS-02 §6.4 — the `run_with_writer` streaming variant
    // is a future addition).
    sim.run_vector(&vector).map_err(CliError::from)?;

    // Write the trace to the requested sink.
    write_trace(sim.trace(), out_path)?;
    Ok(())
}

/// Read the vector source either from a file path or stdin (when the path
/// is `-`). The entire file is buffered before parsing (PreLoaded mode).
fn read_vector_source(path: &str) -> Result<String, CliError> {
    if path == "-" {
        let mut buf = String::new();
        io::stdin().read_to_string(&mut buf)?;
        Ok(buf)
    } else {
        fs::read_to_string(PathBuf::from(path)).map_err(CliError::Io)
    }
}

/// Write the trace either to a file path or to stdout (when the path is
/// `None` or `Some("-")`).
fn write_trace(trace: &sos_sim::Trace, out_path: Option<&str>) -> Result<(), CliError> {
    match out_path {
        None | Some("-") => {
            let stdout = io::stdout();
            let mut writer = BufWriter::new(stdout.lock());
            trace.write_jsonl(&mut writer)?;
            Ok(())
        }
        Some(path) => {
            let file = fs::File::create(PathBuf::from(path))?;
            let mut writer = BufWriter::new(file);
            trace.write_jsonl(&mut writer)?;
            Ok(())
        }
    }
}
