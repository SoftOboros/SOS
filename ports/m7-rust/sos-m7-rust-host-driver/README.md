# sos-m7-rust-host-driver

Host-side UART adapter binary for the SOS-04 M7 Rust reference port.

## Purpose

`sos-m7-rust-host-driver` is the **host-side adapter** described in
[SOS-04 §3 glossary] and [SOS-04 §7 conformance-mode protocol]. It
satisfies the SOS-03 §7.6 port-binary contract on behalf of the M7
firmware (`sos-m7-rust`) by bridging the harness's stdin/stdout to the
disco-analyzer's UART:

```
sos-conformance (harness, host)
   │ stdin (JSON wrapped vector)
   ▼
sos-m7-rust-host-driver (this crate; host)
   │ UART TX (raw bytes, 921600 8N1)
   ▼
sos-m7-rust (M7 firmware; CM7 of STM32H747I-DISCO)
   │ UART RX (JSONL trace records + done sentinel)
   ▼
sos-m7-rust-host-driver
   │ stdout (JSONL records; sentinel filtered out)
   ▼
sos-conformance
```

The adapter contains **no kernel logic**. It is a pure I/O bridge.

## Build

```sh
cargo build --release -p sos-m7-rust-host-driver
```

The binary lands at `target/release/sos-m7-rust-host-driver` (host
target — Linux x86_64 / aarch64, macOS arm64 / x86_64).

## Invocation

```sh
sos-m7-rust-host-driver --port /dev/tty.usbmodemXXXX
```

Flags:

| Flag | Default | Meaning |
|---|---|---|
| `--port <tty-path>` | (required) | Serial device the disco-analyzer's ST-Link VCP enumerates as. See "Discovering the port path" below. |
| `--baud <n>` | `921600` | UART baud (PCDN-SOS-04-007). 8N1, no flow control. |
| `--timeout <secs>` | `30` | Per-vector wall-clock timeout (PCDN-SOS-04-014). |

The adapter is invoked by `sos-conformance` via its `--port <bin>`
flag (SOS-03 §7.6 / SOS-04 §7). Typical end-to-end run:

```sh
./target/release/sos-conformance run \
    --suite conformance/vectors/ \
    --filter 'smoke/0001-*' \
    --port ./target/release/sos-m7-rust-host-driver
```

## Discovering the port path

The on-board ST-LINK exposes USART1 (per memalpha-confirmed UM2411
§5.10) as a USB Virtual Com Port. Path on each host:

- **macOS:** the VCP enumerates as `/dev/tty.usbmodemNNNNNNN` (digits
  follow the ST-LINK serial number). `ls /dev/tty.usbmodem*` after
  plugging the board in.
- **Linux:** the VCP enumerates as `/dev/ttyACM0` (or `/dev/ttyACM1` if
  another `cdc_acm` device is plugged in). `ls /dev/ttyACM*`. Note
  it is *not* `/dev/ttyUSB*` — that's reserved for FTDI-style USB-UART
  bridges; the ST-LINK VCP is `cdc_acm`.

There is no auto-detection at v1; the operator passes the path via
`--port` after discovering it. (Auto-detect by vendor/product ID is a
future amendment territory.)

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Firmware emitted the done sentinel; trace forwarded cleanly. |
| `2` | Wall-clock timeout elapsed before the sentinel arrived (mirrors SOS-03 §7.2's "vector failed" code). |
| `3` | Unrecoverable I/O error (port refused to open, RX stream errored, stdin empty). |

Diagnostics go to stderr; only JSONL trace records (sentinel filtered)
go to stdout.

## Wire framing

- **stdin → UART TX.** The harness's wrapped vector JSON
  (`{"name": ..., "config": ..., "input": [...]}` as written by
  `SubprocessPort` in `sim/sos-conformance/src/port.rs`) is read to EOF
  and forwarded byte-for-byte to the UART, with a trailing `\n` appended
  if absent. The firmware's parser (SOS-04 §6.2.1) reads bytes into
  `TRACE_RX_BUF` until a balanced document terminated by `\n` arrives.
- **UART RX → stdout.** Bytes accumulate into a line buffer; each
  `\n`-terminated line is one JSONL record. Records pass through
  unmodified.
- **Done sentinel filter.** The exact line `{"__sos_done": true}`
  (whitespace-tolerant — parsed via `serde_json`) is the firmware's
  end-of-trace signal per PCDN-SOS-04-005. INV-S-PORT-12 binds this
  adapter to filter the sentinel; it never reaches stdout.

## Relationship to sos-conformance

`sos-conformance`'s `SubprocessPort` (`sim/sos-conformance/src/port.rs`)
spawns this binary, writes a single wrapped JSON document to its stdin,
reads JSONL records from its stdout to EOF, and parses each record as a
`TraceRecord` per SOS-02 §7. This adapter realises that exact contract
on behalf of a port binary that physically lives across a UART.

## Crawl boundary

Do not crawl outside `streamz/submodules/SOS/`. SOS is a private
sibling subrepo; the source-of-truth doctrine for SOS-04 lives in
`docs/concepts/SOS-04-CONCEPTS.md`.
