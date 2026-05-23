# `sos-conformance`

Conformance vector suite harness for the SOS Statechart-Orchestrated
Scheduler. Ratified by
[SOS-03](../../docs/concepts/SOS-03-CONCEPTS.md).

This is the **skeleton landing**. Types, traits, module structure, CLI
grammar, and one seed vector fixture are in place; harness body, loader,
diff, and the remaining five seed vectors land in subsequent commits per
the spec-before-code discipline.

## Build

```bash
# From the SOS subrepo root:
cargo build -p sos-conformance
cargo test  -p sos-conformance --no-run
```

If your shell sets `RUSTFLAGS` for embedded sibling projects (e.g.
`-fuse-ld=mold` for the disco-analyzer family), clear it for SOS host
builds: `RUSTFLAGS="" cargo build -p sos-conformance`. Mirrors the
sibling `sos-sim` crate's documented workaround.

## Run (once bodies land)

```bash
# Degenerate self-test (sos-sim vs sos-sim, every vector trivially passes)
cargo run --release -p sos-conformance -- run --suite conformance/vectors/

# Non-default port
./target/release/sos-conformance run --suite conformance/vectors/ \
    --port ./target/m7-rust-port/sos-m7-rust-host-driver

# Filtered subset
./target/release/sos-conformance run --suite conformance/vectors/ \
    --filter 'smoke/*'

# CI consumption
./target/release/sos-conformance run --suite conformance/vectors/ \
    --format json --out /tmp/report.json
```

## Layout

- `src/lib.rs` — public API surface (re-exports of `VectorFile`,
  `Harness`, `Filter`, `DiffRecord`, port traits).
- `src/main.rs` — CLI binary (`run`, reserved `generate`, `lint`).
- `src/vector_file.rs` — on-disk JSON fixture types (SOS-03 §6.2
  mirror); `VectorCategory`, `VectorOrigin` enums.
- `src/diff.rs` — `DiffRecord`, `DiffSeverity`, structural-comparison
  entry point (SOS-03 §6.5).
- `src/harness.rs` — harness orchestrator; sequential per INV-S-CONF-7.
- `src/filter.rs` — `--filter <GLOB>` wrapper around `globset`
  (SOS-03 §7.5, PCDN-SOS-03-006).
- `src/port.rs` — `Port` trait + `InProcessPort` / `SubprocessPort`
  implementations (SOS-03 §7.6 port-binary contract).

## See also

- [`SOS-03-CONCEPTS.md`](../../docs/concepts/SOS-03-CONCEPTS.md) §5
  (frozen enums), §6 (vector file format), §7 (harness behaviour),
  §9 (invariants).
- [`SOS-02-CONCEPTS.md`](../../docs/concepts/SOS-02-CONCEPTS.md) §5.4
  (`ObservableField`), §6.1 (module layout), §7 (trace serialisation
  format).
- [`SOS-00-CONCEPTS.md`](../../docs/concepts/SOS-00-CONCEPTS.md) §5
  (frozen enums), §7 (conformance vector framework).
- [`SOS-01-CONCEPTS.md`](../../docs/concepts/SOS-01-CONCEPTS.md) §5.3
  (`ExternalEventName`).
