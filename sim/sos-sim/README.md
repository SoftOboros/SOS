# `sos-sim`

Host simulator for the SOS Statechart-Orchestrated Scheduler. Reference
implementation of [`rtos_kernel.scxml`](../../rtos_kernel.scxml), ratified
by [SOS-02](../../docs/concepts/SOS-02-CONCEPTS.md).

This is the **skeleton landing**. Types, traits, module structure, and the
CLI grammar are in place; function bodies (the macrostep harness, the
hand-compiled `<script>` bodies, trace emission) land in subsequent
commits per the spec-before-code discipline.

## Build

```bash
# From the SOS subrepo root:
cargo build -p sos-sim
cargo test  -p sos-sim --no-run
```

If your shell sets `RUSTFLAGS` for embedded sibling projects (e.g.
`-fuse-ld=mold` for the disco-analyzer family), clear it for SOS host
builds: `RUSTFLAGS="" cargo build -p sos-sim`. Mirrors the parent
repo's documented workaround.

## Run (once bodies land)

```bash
cargo run -p sos-sim -- run --vector path/to/vector.json
cargo run --release -p sos-sim -- run --vector path/to/vector.json --out trace.jsonl
```

## Layout

- `src/lib.rs` — public API surface (re-exports of `Simulator`,
  `Datamodel`, `Trace`, `Event`, `ScriptProvider`).
- `src/datamodel.rs` — the chart's datamodel as Rust types.
- `src/event.rs` — `EventName` (SOS-01 §5.3 mirror) + `Event`.
- `src/trace.rs` — `Trace`, `TraceRecord`, JSONL writer.
- `src/simulator.rs` — the macrostep harness.
- `src/script_provider.rs` — the `ScriptProvider` trait.
- `src/scripts.rs` — `HandCompiledScripts` (v1 reference provider).
- `src/vector.rs` — `Vector` + `Config` (SOS-00 §7.1 mirror).
- `src/error.rs` — `SimError`.
- `src/bin/sos-sim.rs` — CLI binary.

## See also

- [`SOS-02-CONCEPTS.md`](../../docs/concepts/SOS-02-CONCEPTS.md) §6
  (architecture), §7 (trace format), §9 (invariants).
- [`SOS-00-CONCEPTS.md`](../../docs/concepts/SOS-00-CONCEPTS.md) §5
  (frozen enums), §7 (conformance vector framework).
- [`SOS-01-CONCEPTS.md`](../../docs/concepts/SOS-01-CONCEPTS.md) §5.3
  (`ExternalEventName`), §5.4 (`StateId`).
