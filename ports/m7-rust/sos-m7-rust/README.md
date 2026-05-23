# sos-m7-rust

The SOS-04 M7 Rust reference port. Cross-compiled to
`thumbv7em-none-eabihf` and flashed to the CM7 core of the
STM32H747I-DISCO board.

**Status:** skeleton (this commit). Compiles cleanly under
`cargo check --target thumbv7em-none-eabihf -p sos-m7-rust`; kernel
bodies, JSON writer, transport implementation, and the host-side
adapter land in subsequent commits.

## See also

- [`docs/concepts/SOS-04-CONCEPTS.md`](../../../docs/concepts/SOS-04-CONCEPTS.md) — ratified 2026-05-19; load-bearing spec for this port.
- [`docs/concepts/SOS-00-CONCEPTS.md`](../../../docs/concepts/SOS-00-CONCEPTS.md) — parent concepts; §6 is the M7 primitive contract this crate realises.
- [`docs/concepts/SOS-02-CONCEPTS.md`](../../../docs/concepts/SOS-02-CONCEPTS.md) — §7 trace wire format the on-device writer matches byte-for-byte.

## Build

```bash
# Skeleton check (no implementation yet; verifies linking)
cargo check --target thumbv7em-none-eabihf -p sos-m7-rust

# Release build (once the implementation phases land)
RUSTFLAGS="-C target-cpu=cortex-m7" \
cargo build --target thumbv7em-none-eabihf --release -p sos-m7-rust

# Standalone smoke (PCDN-SOS-04-004 — compiled-in static vector)
cargo build --target thumbv7em-none-eabihf --release \
  -p sos-m7-rust --features standalone-smoke
```

The crate-local `.cargo/config.toml` pins `target = "thumbv7em-none-eabihf"`
and the `-C link-arg=-Tlink.x` + `-C target-cpu=cortex-m7` rustflags so
invocations from inside the crate directory work without extra flags.

## Flash + run (bench-authorisation required)

Per the parent CLAUDE.md "Bench-hardware authorization" rule, flashing
the disco-analyzer board requires explicit per-round operator
authorisation:

```bash
probe-rs run --chip STM32H747XIH6 \
    target/thumbv7em-none-eabihf/release/sos-m7-rust
```

## Implementation roadmap

The skeleton stages bodies into discrete phases so each lands as a
small, reviewable commit:

1. **Skeleton (this commit).** Cargo manifest, linker script, module
   shells, NVIC handler stubs, dimensional constants, `Datamodel` type
   shape. `cargo check` passes; no kernel logic.
2. **Kernel body + BSP.** `disco_bsp::init` (clock tree, GPIO AF,
   SysTick), `kernel::init` (pool zeroing, idle promotion, NVIC
   priorities), `transport::start` (USART1 921600 + FIFO), SysTick body
   issuing `sys.tick`, the BASEPRI critical-section wrappers.
3. **JSON writer + PendSV.** Hand-rolled `trace::write_record`, naked
   PendSV save/restore body inspecting `EXC_RETURN[4]`, byte-stability
   unit tests in the separate `sos-m7-rust-tests` host crate
   (PCDN-SOS-04-018).
4. **Host-side adapter + bench-run.** `sos-m7-rust-host-driver` host
   binary bridging the conformance harness's stdin/stdout to USART1;
   first bench run against the SOS-03 seed suite.

## Layout

```
ports/m7-rust/sos-m7-rust/
├── Cargo.toml            # crate manifest
├── memory.x              # linker memory regions (FLASH/DTCM/SRAM)
├── build.rs              # copies memory.x into OUT_DIR
├── .cargo/config.toml    # crate-local target + rustflags
└── src/
    ├── main.rs           # cortex-m-rt #[entry]; mode dispatch
    ├── kernel.rs         # static pools + Datamodel + frozen enums
    ├── handlers.rs       # PendSV / SysTick / SVC #[exception] shims
    ├── transport.rs      # USART1 RX/TX trace transport
    ├── trace.rs          # SOS-02 §7 JSONL writer signature
    └── disco_bsp.rs      # clock tree + GPIO AF + SysTick bring-up
```
