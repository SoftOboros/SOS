//! CLI smoke tests for sos-m7-rust-host-driver.
//!
//! These exercise only the CLI surface; the real end-to-end bench
//! validation (disco-analyzer + flashed firmware) is out of scope per
//! the parent CLAUDE.md bench-authorisation rule.

use std::path::PathBuf;
use std::process::{Command, Stdio};

/// Locate the binary that cargo just built. With cargo-test running,
/// `CARGO_BIN_EXE_<name>` is set to the built binary's path.
fn driver_binary() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_sos-m7-rust-host-driver"))
}

#[test]
fn help_flag_prints_help_and_exits_zero() {
    let output = Command::new(driver_binary())
        .arg("--help")
        .output()
        .expect("failed to spawn driver --help");
    assert!(
        output.status.success(),
        "--help should exit 0, got {:?}",
        output.status
    );
    let stdout = String::from_utf8_lossy(&output.stdout);
    // Sanity-check that the help text mentions the core CLI surface.
    assert!(
        stdout.contains("--port"),
        "help text missing --port flag: {stdout}"
    );
    assert!(
        stdout.contains("--baud") || stdout.contains("baud"),
        "help text missing baud option: {stdout}"
    );
    assert!(
        stdout.contains("--timeout") || stdout.contains("timeout"),
        "help text missing timeout option: {stdout}"
    );
}

#[test]
fn missing_port_arg_exits_nonzero() {
    let output = Command::new(driver_binary())
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .output()
        .expect("failed to spawn driver with no args");
    assert!(
        !output.status.success(),
        "no-args invocation should fail, got success exit"
    );
}

#[test]
fn dev_null_port_fails_gracefully() {
    // Pointing the adapter at /dev/null is a deliberate sanity probe:
    // /dev/null is a valid path but does not behave like a serial
    // device (it has no termios surface, no baud rate, etc.). The
    // adapter MUST report a non-zero exit, not panic.
    //
    // Feed an empty stdin so the adapter doesn't block waiting on it.
    // (Empty stdin path also exits non-zero via run_adapter's empty
    // check — that's also a graceful failure, which is what we want.)
    let mut child = Command::new(driver_binary())
        .arg("--port")
        .arg("/dev/null")
        .arg("--timeout")
        .arg("1") // short timeout so the test is fast
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("failed to spawn driver with --port /dev/null");
    // Close stdin immediately (EOF).
    drop(child.stdin.take());
    let output = child
        .wait_with_output()
        .expect("failed to await driver exit");
    assert!(
        !output.status.success(),
        "--port /dev/null should NOT exit 0 (it isn't a serial device)"
    );
    // The failure mode should be a clean diagnostic on stderr, not a
    // panic. Panic output on stderr starts with "thread '...' panicked".
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        !stderr.contains("panicked at"),
        "driver should fail gracefully, not panic; stderr was:\n{stderr}"
    );
}
