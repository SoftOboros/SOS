//! sos-m7-rust-host-driver — library surface.
//!
//! The library exposes [`run_adapter`] so a future integrated harness
//! could call into the adapter without spawning a subprocess. `main.rs`
//! is a thin CLI wrapper that parses `clap` args and calls `run_adapter`.
//!
//! See SOS-04 §7 (conformance-mode protocol) and SOS-04 §3 glossary
//! ("host-side adapter") for the contract this realises. The adapter
//! contains NO kernel logic — it is a pure I/O bridge between
//! sos-conformance's stdin/stdout (per SOS-03 §7.6) and the M7's UART.
//!
//! ## Wire framing
//!
//! - **stdin → UART TX:** the wrapped vector JSON (a single document of
//!   shape `{"name": ..., "config": ..., "input": [...]}` as written by
//!   `SubprocessPort` in `sim/sos-conformance/src/port.rs`) is read to
//!   EOF, then written verbatim to the UART followed by a single `\n`
//!   terminator (per SOS-04 §6.2.1 — firmware reads bytes into
//!   `TRACE_RX_BUF` until a balanced document terminated by `\n`).
//! - **UART RX → stdout:** bytes are accumulated into a line buffer;
//!   each `\n`-terminated line is one JSONL record. Records pass
//!   through unmodified onto stdout (per SOS-04 §7.1 — no field
//!   reordering, no whitespace normalisation, no re-serialisation).
//! - **Done sentinel:** the line `{"__sos_done": true}` (with arbitrary
//!   internal whitespace tolerated) is the firmware's end-of-trace
//!   signal per PCDN-SOS-04-005. INV-S-PORT-12 binds the adapter to
//!   filter the sentinel; it MUST NOT reach stdout. Encountering the
//!   sentinel is the only clean exit path.

use std::io::{BufRead, BufReader, Read, Write};
use std::time::{Duration, Instant};

use anyhow::{anyhow, Context, Result};
use serde::Deserialize;

/// CLI options + library entry-point options.
///
/// The CLI ([`main`]) parses these via `clap`; library callers
/// construct an [`AdapterOptions`] value directly.
#[derive(Debug, Clone)]
pub struct AdapterOptions {
    /// OS-level serial-device path. On macOS typically a member of
    /// `/dev/tty.usbmodem*` (the disco-analyzer's ST-Link VCP enumerates
    /// as `/dev/tty.usbmodemNNNNNNN`). On Linux typically `/dev/ttyACM0`
    /// or `/dev/ttyACM1` (the ST-Link VCP is the `cdc_acm` device, not
    /// `/dev/ttyUSB*` which is reserved for FTDI-style USB-UART bridges).
    /// The operator discovers the right path at bench-bring-up time; the
    /// adapter does not auto-detect.
    pub port_path: String,
    /// Baud rate. PCDN-SOS-04-007 default: 921600. 8N1, no flow control.
    pub baud_rate: u32,
    /// Per-vector wall-clock timeout. PCDN-SOS-04-014 default: 30 s.
    pub timeout: Duration,
}

impl Default for AdapterOptions {
    fn default() -> Self {
        Self {
            port_path: String::new(),
            baud_rate: 921_600,
            timeout: Duration::from_secs(30),
        }
    }
}

/// The done sentinel literal per PCDN-SOS-04-005.
const DONE_SENTINEL_FIELD: &str = "__sos_done";

/// Schema used to detect the sentinel line. Matches `{"__sos_done":
/// true}` (and tolerates serialiser whitespace variations because we
/// parse via `serde_json`, not by byte-compare).
#[derive(Deserialize)]
struct DoneSentinel {
    #[serde(rename = "__sos_done")]
    flag: bool,
}

/// Test whether a JSONL line is the firmware's done sentinel. Returns
/// `true` only on a JSON object with `__sos_done: true` as its single
/// field. Defence in depth: a future `TraceRecord` cannot accidentally
/// carry `__sos_done` per SOS-02 §7.4 field-name policy (SOS-04 §7.3
/// reserves the name at the trace-format level), but the field-only
/// check would still spuriously match a record that DID carry the field
/// — so we additionally bail on any record that isn't precisely the
/// shape `{"__sos_done": true}`.
fn is_done_sentinel(line: &str) -> bool {
    let trimmed = line.trim();
    if !trimmed.contains(DONE_SENTINEL_FIELD) {
        // Cheap reject — most trace records don't carry the field name.
        return false;
    }
    let value: serde_json::Value = match serde_json::from_str(trimmed) {
        Ok(v) => v,
        Err(_) => return false,
    };
    let obj = match value.as_object() {
        Some(o) => o,
        None => return false,
    };
    // Exactly one field named `__sos_done` with value `true`.
    if obj.len() != 1 {
        return false;
    }
    matches!(
        obj.get(DONE_SENTINEL_FIELD).and_then(|v| v.as_bool()),
        Some(true)
    ) && serde_json::from_str::<DoneSentinel>(trimmed)
        .map(|s| s.flag)
        .unwrap_or(false)
}

/// Run the adapter end-to-end. Returns `Ok(())` if the firmware emitted
/// the done sentinel before the timeout; returns an `Err` otherwise
/// (used by `main.rs` to select the right process exit code).
pub fn run_adapter(opts: &AdapterOptions) -> Result<()> {
    // 1. Read the wrapped vector JSON from stdin (a single document, to
    //    EOF — matches the SOS-03 §7.6 / `SubprocessPort` contract which
    //    closes stdin after writing the payload).
    let mut stdin_buf = String::new();
    std::io::stdin()
        .read_to_string(&mut stdin_buf)
        .context("failed to read vector JSON from stdin")?;

    if stdin_buf.trim().is_empty() {
        return Err(anyhow!("empty stdin — no vector JSON to forward"));
    }

    // 2. Open the serial port with the configured baud rate. The
    //    serialport crate's `new(...).open()` defaults to 8N1, no flow
    //    control — matches PCDN-SOS-04-007 / SOS-04 §6.4 §6.8 BSP setup.
    //    Use a short read timeout (100 ms) so the receive loop can
    //    periodically re-check the wall-clock deadline (PCDN-SOS-04-014).
    let port = serialport::new(&opts.port_path, opts.baud_rate)
        .timeout(Duration::from_millis(100))
        .open()
        .with_context(|| {
            format!(
                "failed to open serial port {:?} at {} baud",
                opts.port_path, opts.baud_rate
            )
        })?;

    // 3. Write the vector JSON to UART TX, appending `\n` if absent.
    //    The firmware's parser (SOS-04 §6.2.1) reads bytes into
    //    TRACE_RX_BUF until a balanced JSON document terminated by `\n`
    //    arrives, so the trailing newline is load-bearing.
    let mut write_port = port.try_clone().context(
        "failed to clone serial-port handle for the TX/RX split — \
         platform may not support concurrent reader+writer on this device",
    )?;
    write_port
        .write_all(stdin_buf.as_bytes())
        .context("failed to write vector JSON to UART TX")?;
    if !stdin_buf.ends_with('\n') {
        write_port
            .write_all(b"\n")
            .context("failed to write trailing newline to UART TX")?;
    }
    write_port
        .flush()
        .context("failed to flush UART TX after vector JSON")?;
    // Drop the writer; we don't need it again. The kernel emits only on
    // RX from here; the firmware's protocol forbids a second vector per
    // boot (SOS-04 §7.2 "One vector per boot").
    drop(write_port);

    // 4. Read JSONL lines from UART RX until the sentinel arrives or
    //    the wall-clock deadline elapses. Use a BufReader for line
    //    framing. Each `read_line` call is bounded by the 100 ms
    //    serial-port read timeout, so we can re-check the deadline
    //    between reads without hot-spinning.
    let deadline = Instant::now() + opts.timeout;
    let mut reader = BufReader::new(port);
    let stdout = std::io::stdout();
    let mut out = stdout.lock();
    let mut line = String::new();

    loop {
        if Instant::now() >= deadline {
            return Err(anyhow!(
                "timed out after {:?} waiting for done sentinel on UART RX",
                opts.timeout
            ));
        }
        line.clear();
        match reader.read_line(&mut line) {
            Ok(0) => {
                // EOF — serial ports normally don't emit EOF; treat as
                // an unrecoverable RX error.
                return Err(anyhow!(
                    "serial port reached EOF before done sentinel arrived"
                ));
            }
            Ok(_) => {
                if line.trim().is_empty() {
                    continue;
                }
                if is_done_sentinel(&line) {
                    // INV-S-PORT-12: sentinel is adapter-local; do NOT
                    // emit it on stdout. Clean exit.
                    out.flush().ok();
                    return Ok(());
                }
                // Trace record passes through verbatim. The harness's
                // JSONL parser tolerates trailing whitespace per
                // sos-conformance `port.rs` (`line.trim()`); we write
                // the line exactly as received so byte-stability holds.
                out.write_all(line.as_bytes())
                    .context("failed to write trace record to stdout")?;
                // Flush per [SOS-02] INV-S-SIM-7 — one flush per record
                // so the harness can stream-parse without buffering.
                out.flush().ok();
            }
            Err(e) if e.kind() == std::io::ErrorKind::TimedOut => {
                // Expected: short serialport read timeout fired with no
                // data. Re-check the wall-clock deadline.
                continue;
            }
            Err(e) => {
                return Err(anyhow!("UART RX read error: {e}"));
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sentinel_detected() {
        assert!(is_done_sentinel(r#"{"__sos_done": true}"#));
        assert!(is_done_sentinel(r#"{"__sos_done":true}"#));
        assert!(is_done_sentinel("  {\"__sos_done\": true}  \n"));
    }

    #[test]
    fn non_sentinel_records_rejected() {
        // Real trace records — never match.
        assert!(!is_done_sentinel(
            r#"{"after_input_idx": -1, "current": 0, "tasks": []}"#
        ));
        assert!(!is_done_sentinel(r#"{"__sos_done": false}"#));
        // Object with extra fields — never matches.
        assert!(!is_done_sentinel(
            r#"{"__sos_done": true, "extra": 1}"#
        ));
        // Not an object.
        assert!(!is_done_sentinel(r#"true"#));
        // Bad JSON.
        assert!(!is_done_sentinel(r#"{__sos_done: true}"#));
        // Empty.
        assert!(!is_done_sentinel(""));
    }
}
