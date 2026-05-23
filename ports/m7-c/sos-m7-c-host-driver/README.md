# sos-m7-c-host-driver

Host-side UART adapter binary for the SOS-05 M7 C reference port. The
C-language analog of `sos-m7-rust-host-driver`; same wire framing, same
exit-code policy, same sentinel-filter rule.

## Purpose

`sos-m7-c-host-driver` is the **host-side adapter** described in
[SOS-04 §3 glossary] (inherited by SOS-05 §3) and [SOS-05 §7
conformance-mode protocol]. It satisfies the SOS-03 §7.6 port-binary
contract on behalf of the M7 C firmware (`sos-m7-c`) by bridging the
harness's stdin/stdout to the disco-analyzer's USART1 VCP:

```
sos-conformance (harness, host)
   │ stdin (JSON wrapped vector)
   ▼
sos-m7-c-host-driver (this directory; host)
   │ UART TX (raw bytes, 921600 8N1)
   ▼
sos-m7-c (M7 firmware; CM7 of STM32H747I-DISCO)
   │ UART RX (JSONL trace records + done sentinel)
   ▼
sos-m7-c-host-driver
   │ stdout (JSONL records; sentinel filtered out)
   ▼
sos-conformance
```

Per PCDN-SOS-05-011, the adapter is implemented in C for symmetry with
the firmware. It depends on **POSIX termios only** — no `libserialport`,
no `boost::asio`, no other external library.

The adapter contains **no kernel logic**. It is a pure I/O bridge.

## Build

```sh
cd ports/m7-c/sos-m7-c-host-driver
cmake -S . -B build
cmake --build build
```

The binary lands at `build/sos-m7-c-host-driver`. Host target only;
this directory is never cross-compiled for ARM (the firmware lives in
`ports/m7-c/sos-m7-c/`).

Build tested on:

- macOS arm64 (Apple clang 17, CMake 3.20+)
- Linux x86_64 (gcc 11+ / clang 14+)

## Invocation

```sh
./build/sos-m7-c-host-driver --port /dev/tty.usbmodemXXXX
```

Flags:

| Flag | Default | Meaning |
|---|---|---|
| `--port <tty-path>` | (required) | Serial device the disco-analyzer's ST-Link VCP enumerates as. See "Discovering the port path" below. |
| `--baud <n>` | `921600` | UART baud (PCDN-SOS-05-007). 8N1, no flow control. |
| `--timeout <secs>` | `30` | Per-vector wall-clock timeout (PCDN-SOS-04-014 / SOS-05 inheritance). |
| `-h`, `--help` | — | Print usage and exit 0. |

Supported baud rates (compile-time enumerated against the host's
termios `Bxxxx` macros): 9600, 38400, 57600, 115200, 230400, 460800,
921600, 1000000. Unsupported values exit 3 with a diagnostic.

The adapter is invoked by `sos-conformance` via its `--port <bin>` flag
(SOS-03 §7.6 / SOS-05 §7). Typical end-to-end run:

```sh
./target/release/sos-conformance run \
    --suite conformance/vectors/ \
    --filter 'smoke/0001-*' \
    --port ports/m7-c/sos-m7-c-host-driver/build/sos-m7-c-host-driver
```

## Discovering the port path

The on-board ST-LINK exposes USART1 (PCDN-SOS-05-008, per memalpha-
confirmed UM2411 §5.10) as a USB Virtual Com Port. Path on each host:

- **macOS:** the VCP enumerates as `/dev/tty.usbmodemNNNNNNN` (digits
  follow the ST-LINK serial number). Run `ls /dev/tty.usbmodem*` after
  plugging the board in.
- **Linux:** the VCP enumerates as `/dev/ttyACM0` (or `/dev/ttyACM1` if
  another `cdc_acm` device is plugged in). Run `ls /dev/ttyACM*`. Note
  it is *not* `/dev/ttyUSB*` — that's reserved for FTDI-style USB-UART
  bridges; the ST-LINK VCP is `cdc_acm`.

There is no auto-detection at v1; the operator passes the path via
`--port` after discovering it.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Firmware emitted the done sentinel; trace forwarded cleanly. |
| `2` | Wall-clock timeout elapsed before the sentinel arrived (mirrors SOS-03 §7.2's "vector failed" code). |
| `3` | Unrecoverable I/O error (port refused to open, RX stream errored, stdin empty, unsupported baud, etc.). |

Diagnostics go to stderr; only JSONL trace records (sentinel filtered)
go to stdout.

## Wire framing

- **stdin → UART TX.** The harness's wrapped vector JSON
  (`{"name": ..., "config": ..., "input": [...]}` as written by
  `SubprocessPort` in `sim/sos-conformance/src/port.rs`) is read to
  EOF and forwarded byte-for-byte to the UART, with a trailing `\n`
  appended if absent. The firmware's parser (SOS-05 §6.2.1, inherited
  from SOS-04) reads bytes into `TRACE_RX_BUF` until a balanced document
  terminated by `\n` arrives.
- **UART RX → stdout.** Bytes accumulate into a line buffer; each
  `\n`-terminated line is one JSONL record. Records pass through
  unmodified (no field reordering, no whitespace normalisation).
- **Done sentinel filter.** The line `{"__sos_done":true}` (whitespace-
  tolerant — parsed by a hand-rolled token scanner that mirrors the
  Rust adapter's `serde_json` one-key check) is the firmware's
  end-of-trace signal per PCDN-SOS-04-005 / SOS-05 inheritance.
  INV-S-PORT-12 binds this adapter to filter the sentinel; it never
  reaches stdout.

## Implementation notes

- **No external dependencies.** Only POSIX headers: `termios.h`,
  `unistd.h`, `fcntl.h`, `sys/select.h`, `sys/time.h`, plus standard C.
  `getopt_long` is from `<getopt.h>` — present on both macOS libc and
  glibc; if you port to a libc without it, swap for `getopt`.
- **Strict C11.** `-Wall -Wextra -Wpedantic -Werror` plus
  `-Wstrict-prototypes -Wmissing-prototypes -Wshadow -Wpointer-arith
  -Wcast-align`. The build is clean on both Apple clang 17 and gcc.
- **Cross-platform baud rate setting.** macOS `<termios.h>` only
  defines `Bxxxx` up to `B230400`; the SOS-05 default rate 921600 is
  set via the `IOSSIOSPEED` ioctl from `<IOKit/serial/ioss.h>` after a
  placeholder `tcsetattr`. On glibc the `Bxxxx` constants up to
  `B4000000` are present so the direct `cfsetispeed/cfsetospeed`
  path is used. No IOKit framework linkage is needed — only the ioctl
  number is consumed.
- **Select-driven receive loop.** A 100 ms `select(2)` tick mirrors the
  Rust adapter's 100 ms `serialport` read timeout, allowing the wall-
  clock deadline to be re-checked between read bursts without hot-
  spinning.
- **Pseudo-tty friendly.** `tcdrain` after TX is non-fatal; some
  pseudo-tty backends return `ENOTTY` there. `O_NONBLOCK` is asserted
  during `open(2)` (to avoid hanging on DCD) and cleared immediately.

## Relationship to sos-conformance

`sos-conformance`'s `SubprocessPort` (`sim/sos-conformance/src/port.rs`)
spawns this binary, writes a single wrapped JSON document to its stdin,
reads JSONL records from its stdout to EOF, and parses each record as
a `TraceRecord` per SOS-02 §7. This adapter realises that exact
contract on behalf of a port binary that physically lives across a
UART.

## Crawl boundary

Do not crawl outside `streamz/submodules/SOS/`. SOS is a private
sibling subrepo; the source-of-truth doctrine for SOS-05 lives in
`docs/concepts/SOS-05-CONCEPTS.md`.
