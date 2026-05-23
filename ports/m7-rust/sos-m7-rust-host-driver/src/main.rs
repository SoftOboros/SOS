//! sos-m7-rust-host-driver — CLI entry point.
//!
//! Thin wrapper around [`sos_m7_rust_host_driver::run_adapter`]. See
//! `lib.rs` (and SOS-04 §7) for the protocol the adapter realises.
//!
//! Exit codes:
//! - `0` — firmware emitted the done sentinel; trace forwarded cleanly.
//! - `2` — wall-clock timeout elapsed before the sentinel arrived. The
//!   harness's `SubprocessPort` interprets any non-zero exit as a
//!   "vector failed" — exit code 2 mirrors SOS-03 §7.2's vector-failed
//!   code so downstream reports surface as `record_count_mismatch` or
//!   similar.
//! - `3` — unrecoverable I/O error (serial port refused to open, RX
//!   stream errored, stdin empty, etc.).

use std::process::ExitCode;
use std::time::Duration;

use clap::Parser;

use sos_m7_rust_host_driver::{run_adapter, AdapterOptions};

/// Host-side adapter for the SOS-04 M7 Rust reference port.
///
/// Bridges the sos-conformance harness (stdin/stdout, per SOS-03 §7.6)
/// to the disco-analyzer firmware's UART (per SOS-04 §7).
#[derive(Debug, Parser)]
#[command(
    name = "sos-m7-rust-host-driver",
    version,
    about = "Host-side UART adapter for the SOS-04 M7 Rust firmware.",
    long_about = "Reads a wrapped vector JSON from stdin, forwards it to the disco-analyzer\n\
                  over UART, streams the firmware's JSONL trace records back on stdout,\n\
                  and exits when the firmware emits its done sentinel.\n\
                  \n\
                  Discover the serial-device path at bench-bring-up time:\n\
                    macOS: ls /dev/tty.usbmodem*        # ST-Link VCP enumerates as usbmodem\n\
                    Linux: ls /dev/ttyACM*              # ST-Link VCP enumerates as cdc_acm"
)]
struct Cli {
    /// OS-level serial-device path. On macOS typically
    /// `/dev/tty.usbmodemNNNNNNN`; on Linux typically `/dev/ttyACM0`.
    #[arg(long)]
    port: String,

    /// UART baud rate (PCDN-SOS-04-007 default).
    #[arg(long, default_value_t = 921_600)]
    baud: u32,

    /// Per-vector wall-clock timeout in seconds (PCDN-SOS-04-014 default).
    #[arg(long, default_value_t = 30)]
    timeout: u64,
}

fn main() -> ExitCode {
    let cli = Cli::parse();
    let opts = AdapterOptions {
        port_path: cli.port,
        baud_rate: cli.baud,
        timeout: Duration::from_secs(cli.timeout),
    };

    match run_adapter(&opts) {
        Ok(()) => ExitCode::from(0),
        Err(err) => {
            // Mirror the diagnostic-on-stderr discipline from SOS-04
            // §7.1: stderr is free-form; the harness captures it for
            // diagnostic reporting but does not parse it.
            eprintln!("sos-m7-rust-host-driver: {err:#}");
            // Distinguish timeout from other failures so the harness's
            // post-mortem can read either ExitCode + stderr together.
            let msg = format!("{err:#}");
            if msg.contains("timed out") {
                ExitCode::from(2)
            } else {
                ExitCode::from(3)
            }
        }
    }
}
