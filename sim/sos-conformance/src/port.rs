//! Port-binary contract — the stdio surface a port satisfies to be
//! invoked by the harness (SOS-03 §7.6).
//!
//! Two implementations of [`Port`]: [`InProcessPort`] (default; invokes
//! `sos_sim::Simulator` directly, no subprocess) and [`SubprocessPort`]
//! (spawns a port binary, pipes the vector to stdin, parses trace from
//! stdout). The default mirrors the degenerate self-test invocation from
//! SOS-03 §7.6's "default port `sos-sim`" clause.

use std::io::{Read, Write};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant};

use serde::Serialize;

use crate::vector_file::VectorFile;

/// Wire shape written to the port binary's stdin per SOS-03 §7.6 and
/// SOS-04 §6.2.1. ONLY `config` and `input` appear on the wire — vector
/// metadata (`name`, `description`, `category`, `origin`, `tags`,
/// `expected_trace`) is harness-side and stays on the host. See
/// SOS-03 §15 Amendment 002 (2026-05-19) for the ratification trail.
#[derive(Serialize)]
struct PortBinaryInput<'a> {
    config: &'a sos_sim::Config,
    input: &'a [sos_sim::Event],
}

/// Subprocess wall-clock timeout (SOS-04 PCDN-014 alignment). A port that
/// fails to emit its trace within this window is treated as wedged.
const PORT_TIMEOUT: Duration = Duration::from_secs(30);

/// One port-binary surface — executes a vector and returns its trace.
pub trait Port {
    /// Execute `vec`'s `input` under `vec.config` and return the trace
    /// records the port emits. Order matches SOS-02 §6.4 (boot baseline
    /// first, then one record per input event).
    fn execute_vector(&self, vec: &VectorFile) -> anyhow::Result<Vec<sos_sim::TraceRecord>>;
}

/// In-process port — invokes `sos_sim::Simulator` directly. The default
/// when `--port` is not given. Useful for the degenerate self-test
/// (every vector trivially passes; verifies the suite is internally
/// consistent — SOS-03 §7.1).
pub struct InProcessPort;

impl Port for InProcessPort {
    fn execute_vector(&self, vec: &VectorFile) -> anyhow::Result<Vec<sos_sim::TraceRecord>> {
        let mut sim = sos_sim::Simulator::new(vec.config, sos_sim::HandCompiledScripts::new());
        let sim_vec = vector_file_to_sim_vector(vec);
        sim.run_vector(&sim_vec)
            .map_err(|e| anyhow::anyhow!("sos-sim runtime error: {e:?}"))?;
        Ok(sim.trace().records.clone())
    }
}

/// Subprocess port — spawns a port binary, pipes a wrapped
/// `{"config": ..., "input": [...]}` JSON document to stdin, and parses
/// the trace from stdout as JSONL (SOS-03 §7.6).
pub struct SubprocessPort {
    /// Absolute or `PATH`-resolved path to the port binary.
    pub binary: PathBuf,
}

impl Port for SubprocessPort {
    fn execute_vector(&self, vec: &VectorFile) -> anyhow::Result<Vec<sos_sim::TraceRecord>> {
        // Build the stdin payload per SOS-03 §7.6 and SOS-04 §6.2.1: a
        // wrapped JSON document containing ONLY `config` and `input`.
        // Vector metadata (`name`, `description`, `category`, `origin`,
        // `tags`, `expected_trace`) is stripped at this layer — it is a
        // harness-side concern, not part of the port-binary wire. See
        // SOS-03 §15 Amendment 002 (2026-05-19).
        let stdin_payload = serde_json::to_string(&PortBinaryInput {
            config: &vec.config,
            input: &vec.input,
        })?;

        let mut child = Command::new(&self.binary)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| {
                anyhow::anyhow!(
                    "failed to spawn port binary {}: {e}",
                    self.binary.display()
                )
            })?;

        // Write stdin in a separate thread to avoid deadlocks (port may
        // be writing trace to stdout while we're still writing stdin).
        let mut stdin = child.stdin.take().expect("piped stdin");
        let payload_for_thread = stdin_payload;
        let stdin_thread = thread::spawn(move || -> std::io::Result<()> {
            stdin.write_all(payload_for_thread.as_bytes())?;
            stdin.flush()?;
            drop(stdin);
            Ok(())
        });

        // Read stdout off the child concurrently with the timeout poll.
        let mut stdout = child.stdout.take().expect("piped stdout");
        let (tx, rx) = mpsc::channel::<std::io::Result<String>>();
        let stdout_thread = thread::spawn(move || {
            let mut buf = String::new();
            let result = stdout.read_to_string(&mut buf);
            let _ = tx.send(result.map(|_| buf));
        });

        let deadline = Instant::now() + PORT_TIMEOUT;
        let stdout_text = loop {
            let now = Instant::now();
            if now >= deadline {
                // Timed out — kill the child and report.
                let _ = child.kill();
                let _ = stdout_thread.join();
                let _ = stdin_thread.join();
                return Err(anyhow::anyhow!("port timeout"));
            }
            let remaining = deadline - now;
            match rx.recv_timeout(remaining) {
                Ok(Ok(text)) => break text,
                Ok(Err(e)) => {
                    let _ = child.kill();
                    return Err(anyhow::anyhow!("error reading port stdout: {e}"));
                }
                Err(mpsc::RecvTimeoutError::Timeout) => {
                    // Loop and re-check deadline.
                    continue;
                }
                Err(mpsc::RecvTimeoutError::Disconnected) => {
                    let _ = child.kill();
                    return Err(anyhow::anyhow!("port stdout channel disconnected"));
                }
            }
        };

        // Drain stderr (best-effort) and wait for the child to exit.
        let _ = stdin_thread.join();
        let _ = stdout_thread.join();
        let _ = child.wait();

        // Parse JSONL stdout into TraceRecord. Per SOS-03 §7.6 each line
        // is one JSON-encoded TraceRecord; empty lines are tolerated.
        let mut records: Vec<sos_sim::TraceRecord> = Vec::new();
        for (idx, line) in stdout_text.lines().enumerate() {
            let trimmed = line.trim();
            if trimmed.is_empty() {
                continue;
            }
            let rec: sos_sim::TraceRecord = serde_json::from_str(trimmed).map_err(|e| {
                anyhow::anyhow!("failed to parse JSONL trace record at line {idx}: {e}")
            })?;
            records.push(rec);
        }
        Ok(records)
    }
}

/// Adapter from the [`VectorFile`] shape to the [`sos_sim::Vector`] shape.
/// `sos_sim::Vector` carries only `name`, `config`, `input` — the
/// `expected_trace` and other metadata are SOS-03's domain.
fn vector_file_to_sim_vector(vf: &VectorFile) -> sos_sim::Vector {
    sos_sim::Vector {
        name: vf.name.clone(),
        config: vf.config,
        input: vf.input.clone(),
    }
}
