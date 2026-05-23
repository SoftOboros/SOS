# SOS-02 — Host Simulator: Concepts, Architecture, and Trace Contract

**Status:** **🟢 Ratified 2026-05-19.** All seven PCDNs resolved by user 2026-05-19; ratification entry in §15. The simulator's external API, trace format, and CLI shape are binding from this commit forward; implementation lands as a follow-up commit per the spec-before-code discipline.

**Blocks:** SOS-03 (conformance vector suite needs a reference implementation against which to generate canonical traces; SOS-04 / SOS-05 reuse the trace contract ratified here).

> 🛑 **NO CODE.** This is a concepts doc. Vocabulary, module layout, frozen enums, the trace wire format, invariants. The implementing PR(s) land after ratification.

## 0. Authority policy

SOS-02 owns:

- The **host simulator's external API** — the Rust types a downstream consumer (a conformance harness, an ad-hoc smoke test) uses to drive the simulator and read traces.
- The **trace wire format** — the byte-exact JSON shape ports compare against. (SOS-03 owns the *suite* of vectors; SOS-02 owns the *format* of one trace record.)
- The **CLI binary** `sos-sim` — argument grammar, exit codes, stdin/stdout discipline.
- The **module layout** of the `sos-sim` crate — `lib.rs` exports, sub-module boundaries, the `ScriptProvider` trait surface that anchors PCDN-SOS-00-005's deferred AST/trace decision.

SOS-02 does **NOT** own:

- The **kernel behaviour** — that is `rtos_kernel.scxml`, owned by SOS-00. SOS-02 is a faithful interpreter; if the simulator's behaviour disagrees with the chart, the simulator is wrong.
- The **frozen enums** — `TaskState`, `ReturnCode`, `SyscallTransport`, `M7KernelPriorityBand`, `FpuPolicy` are SOS-00 §5. SOS-02 re-exports them by reference; it does not extend them.
- The **invariants** — `INV-S1` through `INV-S15` are SOS-00 §9. SOS-02 adds `INV-S-SIM-N` *for the simulator implementation*; those MUST be consistent with the SOS-00 invariants and MUST NOT amend them.
- The **lint rules** that constrain what's transpilable from `<script>` bodies — SOS-01 owns the ECMAScript subset, the event-name and state-id contract, and the lint-checker that enforces both. SOS-02 *consumes* SOS-01's frozen contract; pre-SOS-01-ratification, SOS-02 references its outputs as "SOS-01 §N forward-reference" with the understanding that SOS-01 ratifies before SOS-02 implementation begins.
- The **conformance vector suite** — SOS-03 owns the canonical fixture set; SOS-02 owns only the format and the bootstrap interpreter against which SOS-03 generates the expected traces.

The authority split:

| Concern | Owner | SOS-02 relationship |
|---|---|---|
| Kernel behaviour (statechart, datamodel, syscall ABI) | SOS-00 / `rtos_kernel.scxml` | `derive` — SOS-02 implements; cannot amend. |
| Frozen enums, invariants, M7 primitive bindings | SOS-00 | `mirror` — SOS-02 re-exports; cannot extend. |
| ECMAScript subset usable in `<script>` blocks; event-name / state-id contract | SOS-01 (pending) | `derive` — SOS-02 hand-compiles within that subset. Pre-SOS-01 ratification, SOS-02 cites the subset as the .scxml's *current* usage and flags any gaps. |
| Conformance vector suite | SOS-03 (pending) | SOS-02 produces the canonical traces against which SOS-03 vectors are pinned. SOS-02 owns the wire format; SOS-03 owns the suite. |
| Per-port bench mapping (PendSV, SVC, SysTick, BASEPRI) | SOS-00 §6, SOS-04 / SOS-05 | `not-a-dep` — SOS-02 is a host binary. INV-S-SIM-4 forbids embedded targets. |
| `serde`, `serde_json` crate APIs | upstream `serde` project | `mirror` — pinned to a current 1.x release; no local fork. |
| `clap` crate API (CLI) | upstream `clap` project | `mirror` — pinned to current 4.x release if PCDN-SOS-02-003 ratifies the dependency; otherwise the CLI is hand-rolled. |
| Rust toolchain MSRV | this doc | `own` — SOS-02 pins; ports MUST be at-or-above. |

The crawl boundary inherited from SOS-00 INV-S1 applies: SOS-02 reviewers do not crawl `serde` / `clap` sources, the SCXML 1.0 Recommendation, or ECMA-262 as routine reference. This doc plus SOS-00 plus the cited section numbers is the SOS-02 surface.

## 1. Purpose

Establish:

1. The **reference implementation** of the SOS kernel — a Rust crate (`sos-sim`) that executes `rtos_kernel.scxml` on a host OS (Linux / macOS) and emits a byte-deterministic state-trace. SOS-02 is the canonical interpreter against which every other port (SOS-04 M7 Rust, SOS-05 M7 C, SOS-06 codegen) is conformance-compared.

2. The **trace wire format** — a JSONL-encoded sequence of `(after_input_idx, observable_state_snapshot)` records (per SOS-00 §3 `State trace` + §7.1, as harmonised in SOS-00 §15 Amendment 002). SOS-03 builds its conformance vectors atop this format; SOS-04 / SOS-05 emit traces in this format for direct byte-equality checking.

3. The **module layout and external API** of `sos-sim` — `Simulator`, `Datamodel`, `Trace`, `Event`, `ScriptProvider` — the surface a downstream consumer programs against.

4. The **hand-compiled `<script>` ABI** — every `<script>` block in the .scxml is transpiled by hand into a Rust function. This is the v1 bootstrap path (per PCDN-SOS-00-005 → (b)); the abstraction (`ScriptProvider` trait) is shaped so SOS-01's deferred AST/trace decision is a localised diff, not a rewrite.

5. The **determinism budget** — what guarantees the simulator offers. Identical vector → identical trace bytes, no clock dependence, no allocator-address dependence, no `HashMap` iteration order leakage.

6. The **CLI shape** — `sos-sim run --vector <path>` is the one-shot run mode; later flags (`--format`, `--out`) ratify here, not in SOS-03.

Without SOS-02:

- SOS-03 has no reference implementation to generate canonical traces from. Conformance vectors would have to be hand-authored, which is both error-prone and re-litigates the kernel's behaviour on every test.
- SOS-04 and SOS-05 have no host-comparable baseline. Bench-only validation would conflate kernel bugs with port-specific timing artifacts.
- The .scxml remains a spec without a known-good interpreter — an attractive target for "trust me, this is what it means" interpretations.

## 2. Problem statement

**Current state (as of 2026-05-19, just-post SOS-00 ratification):**

- `rtos_kernel.scxml` exists at the subrepo root, ratified as the canonical behaviour spec by SOS-00.
- `docs/REFERENCE.md` mirrors it informally; the two are presumed consistent by visual inspection.
- There is no executable form of the chart anywhere. The subrepo is currently four files (`AGENTS.md`, `CLAUDE.md`, `README.md`, `rtos_kernel.scxml`) plus `docs/` content. No `Cargo.toml`, no `sim/` tree, no `cargo build` target.
- The parent repo is `git@github.com:SoftOboros/SOS.git` (private), registered as a submodule of `softoboros.com` at `streamz/submodules/SOS/` per PCDN-SOS-00-010.
- The sibling DAA family at `disco-analyzer/` has firmware shipping on the STM32H747I-DISCO, but its FreeRTOS-Kernel runtime is INV-S10-excluded — SOS does not borrow code from it.

**The pressure that motivates SOS-02:**

1. **SOS-03 cannot begin without SOS-02.** A conformance vector is `(input, expected_trace)`. The expected trace is generated *by running the canonical interpreter on the input*. With no interpreter, SOS-03 has nothing to generate against. Hand-authoring expected traces is rejected as error-prone and as a re-litigation of the chart's behaviour at every test fixture.

2. **Two reference ports (SOS-04 Rust, SOS-05 C) need a host-comparable baseline.** Bench-only validation conflates kernel logic bugs with hardware timing artifacts. Running the same vector input through `sos-sim` on the host and through the M7 port on the bench, and demanding byte-equal traces, separates the two failure modes cleanly.

3. **The science being proved (SCXML → multiple equivalent language ports) requires a control case.** The host simulator is that control: a Rust-only, allocator-permitted, deterministic-by-construction implementation. If a port disagrees with `sos-sim`, the port is wrong (or the chart is, in which case SOS-00 §15 amends it).

4. **The .scxml is unverified.** Pre-SOS-02, "this chart is correct" is opinion. Post-SOS-02 + the SOS-03 suite, "this chart is correct" is "passes vectors 1..N, which exercise the surface area documented in `docs/REFERENCE.md` § Testing surface."

**Why this is the right time:**

- SOS-00 just ratified. The frozen enums (§5), invariants (§9), and observable-state subset (§7.2) are stable enough to anchor an interpreter.
- The chart is ~580 lines. A hand-compiled transpilation of every `<script>` block fits in a single tractable Rust file (`scripts.rs`, projected ~600–800 lines).
- The Rust ecosystem (serde, serde_json, clap) is mature enough that the simulator has zero ambient build complexity.
- The user-resolved PCDN-SOS-00-005 → (b) (hand-compiled scripts as the bootstrap) gives a concrete, narrow scope for v1.

## 3. Canonical glossary

Terms SOS-02 introduces. Terms defined in SOS-00 §3 (Statechart, Datamodel, Macrostep, Microstep, Kernel, Port, Conformance vector, State trace, TCB, Ready queue, Wait-queue, Syscall, Tick, Critical section, Scheduler suspend, Idle task, Boot) are cited by reference and not restated.

| Term | Definition | Owner |
|---|---|---|
| **Simulator** | The Rust crate `sos-sim`. A host-runnable, deterministic, allocator-permitted reference implementation of the kernel defined by `rtos_kernel.scxml`. Owned by SOS-02. | SOS-02. |
| **Vector** | The conformance-vector JSON document defined in SOS-00 §7.1. Has fields `name`, `config`, `input`, `expected_trace`. SOS-02 consumes the `input` half (and `config` for sizing); SOS-03 owns the production of the `expected_trace` half by running SOS-02 over the same input. | SOS-00 (shape); SOS-02 (consumer); SOS-03 (producer of the canonical `expected_trace`). |
| **Trace** | The ordered sequence of `TraceRecord` values produced by running the simulator. Each `TraceRecord` is the observable subset of the datamodel at a macrostep boundary. Equivalent to SOS-00 §7's "state trace" with this doc owning the wire format. | SOS-02. |
| **TraceRecord** | One element of a trace. Fields per SOS-00 §7.2 (`after_input_idx`, `current`, `tick_count`, `rc`, `tcb[]`, `ready[]`, `sems[]`, `queues[]`, `irq_nest`, `sched_lock`, `pend_ticks`). Serialised per §7. | SOS-02. |
| **Macrostep boundary** | The instant between two consecutive macrosteps. SOS-02 writes one `TraceRecord` at each macrostep boundary (and one at boot, before any input event). Cited from W3C SCXML 1.0 §3.13 via SOS-00 §3. | W3C (concept); SOS-02 (trace emission policy). |
| **Datamodel cell** | A single named field of the simulator's `Datamodel` struct, mirroring one `<data id="...">` declaration in the .scxml. Type-mapped per §6.1: numeric scalars → `i64` or `i32`; arrays → `Vec<T>`; records → named structs; the `ready[][]` 2D structure → `Vec<Vec<TaskId>>`. | SOS-02. |
| **Step harness** | The simulator's outer driver loop. Reads events from the vector, dispatches each to the appropriate `<transition>` body (i.e. the corresponding `scripts::*` function), runs the resulting macrostep to quiescence, emits a `TraceRecord`. Owned by the `Simulator` struct's `step()` method. | SOS-02. |
| **Event injection** | The mechanism by which an external event (from the vector or from a synthetic source) enters the simulator. Two modes: `PreLoaded` (entire vector loaded at startup; v1 default), `Streaming` (events arrive on stdin; reserved). See §5 `EventInjectionMode`. | SOS-02. |
| **Determinism budget** | The set of guarantees the simulator offers about output determinism. Concretely: same vector → same trace bytes; no clock reads; no env var reads; no allocator-address leakage; iteration over keyed structures uses `BTreeMap` (sorted) rather than `HashMap`. Detailed in §6.5. | SOS-02. |
| **ScriptProvider** | The Rust trait that abstracts "how a `<script>` body runs". v1 has one impl: `HandCompiledScripts`, the static dispatch table from script-name to Rust function. Future SOS-01 impls (`AstWalkScripts`, `TraceReplayScripts`) plug in at the same trait. | SOS-02. |
| **Script name** | The stable identifier of a single `<script>` block in the .scxml, used as the lookup key in any `ScriptProvider` implementation. Convention: `script_<state>_<transition-event>_<index>` (e.g. `script_boot_onentry_0`, `script_sys_idle_task_create_0`). One per `<script>...</script>` element in source order within its parent. | SOS-02. |
| **Quiescence** | The state of the statechart after a macrostep, when no further `<raise>` events are queued and the chart is ready to receive the next external event. Concept from W3C SCXML 1.0 §3.13; SOS-02 emits `TraceRecord` at quiescence. | W3C (concept); SOS-02 (trace emission discipline). |

## 4. Source-of-truth map

External authorities SOS-02 depends on. Per INV-S1 (inherited from SOS-00), the table below is the curated surface; SOS-02 reviewers consult this list, not the crates' source trees.

| Source | Pinned form | Used surface | Relationship |
|---|---|---|---|
| `rtos_kernel.scxml` (SOS-00) | Pinned at SOS-00 §15 SHA per SOS-02 ratification | Every `<datamodel>` field, every `<script>` body, every `<transition>` predicate, every `<state>` id, every `<raise>` target. The simulator IS this file, transliterated. | `derive`. |
| `SOS-00-CONCEPTS.md` | Ratified 2026-05-19 | §3 glossary, §5 frozen enums (`TaskState`, `ReturnCode`), §7 observable-state subset, §9 invariants (`INV-S2` macrostep atomicity, `INV-S5` block precondition, `INV-S6` blk_obj integrity, `INV-S7` ready-queue integrity, `INV-S8` wait-queue ordering, `INV-S12` static-only — relaxed for the simulator per §10). | `mirror`. SOS-02 re-exports the §5 enums verbatim; cannot extend. |
| `SOS-01-CONCEPTS.md` | Pending ratification | The lint-frozen event-name list (forward-reference: "SOS-01 §5 ExternalEventName enum"), the lint-frozen state-id list, the ECMAScript subset declared transpilable. Pre-SOS-01-ratification, SOS-02 enumerates the events the .scxml currently uses and the script subset currently in use, and flags any deviation. | `derive` (forward). |
| W3C SCXML 1.0 Recommendation | Recommendation, 1 September 2015 (via SOS-00 §4) | Document structure (§3.1), macrostep semantics (§3.13), `<parallel>` region semantics (§3.4), `<raise>` queueing (§3.13.2). | `derive`. Same surface SOS-00 curated; no SOS-02-side expansion. |
| ECMA-262 (subset per SOS-01) | Subset (forward-ref SOS-01 §5) | Arithmetic, comparison, `var`, `for`, `if/else`, array `push`/`shift`/`splice`/`indexOf`/`length`, object property access, `null`. Used at *transpilation time* by the simulator author; the running simulator emits transpiled Rust. | `derive`. |
| `serde` (Rust crate) | `serde = "1"` (current 1.x; recommended floor `1.0.193`) | `Serialize` derive, `Deserialize` derive. Used to derive both for `Event`, `Vector`, `TraceRecord`, `Config`, and helper structs. | `mirror`. No SOS-02-side fork. |
| `serde_json` (Rust crate) | `serde_json = "1"` (current 1.x; recommended floor `1.0.108`) | `to_writer`, `from_reader`, `to_value`. Used for the JSONL on-disk format. Field-ordering discipline in §7 below. | `mirror`. |
| `clap` (Rust crate) | `clap = "4"` with `derive` feature, current 4.5.x at SOS-02 ratification | `Parser` derive for the CLI. Conditional on PCDN-SOS-02-003 ratifying `clap`; alternative is a 50-line hand-rolled argparse. | `mirror` (if ratified); not-a-dep (if rejected). |
| `anyhow` (Rust crate) | `anyhow = "1"` (current 1.x) | `anyhow::Result`, `?` propagation in the CLI and the loader. Used in `bin/sos-sim.rs` only; the library API uses concrete error types. | `mirror`. |
| Rust toolchain | MSRV proposed `1.75` (see PCDN-SOS-02-004) | Standard library, `std::collections::BTreeMap`, `std::io::{Read,Write,BufRead,BufReader,BufWriter}`. No nightly features. | `own` (pin); `mirror` (stdlib surface). |

**Negative listing:**

- SOS-02 MUST NOT depend on `cortex-m`, `cortex-m-rt`, CMSIS headers, or any other embedded-target API. INV-S-SIM-4.
- SOS-02 MUST NOT depend on Tokio, async-std, smol, or any other async runtime. The simulator is synchronous; vectors are processed sequentially; no Future ever exists.
- SOS-02 MUST NOT depend on the disco-analyzer subrepo's crates (`analyzer-cm7`, `analyzer-cm4`, `analyzer-rtos`, etc.) or on the vendored FreeRTOS-Kernel. INV-S10.
- SOS-02 MUST NOT pull in a regex engine, a parser combinator (`nom`, `pest`), or an ECMAScript engine (`boa`, `quickjs`, `v8`). Per PCDN-SOS-00-005 → (b), `<script>` handling is hand-compilation, not interpretation, at v1.

## 5. Frozen enums

SOS-02 ratifies four phase-local enums. Each carries a registration policy per the parent CLAUDE.md convention.

### 5.1 `TraceFormat` — Standards Action

The on-wire encoding used to serialise a trace.

| Name | Meaning |
|---|---|
| `JsonLines` | One `TraceRecord` per line, UTF-8 JSON, LF line terminator, no trailing whitespace. v1 default. Streamable; trivially diff-able; readable in a terminal. |
| `Cbor` *(reserved)* | RFC 8949 CBOR, length-prefixed records. Reserved for high-throughput future use (large vector suites, byte-bandwidth-constrained CI). Not implemented at v1. |
| `MessagePack` *(reserved)* | Reserved for symmetry with `Cbor`; same status. |

v1 (per PCDN-SOS-02-002): `JsonLines` is the default and the only implemented format. `Cbor` / `MessagePack` are reserved names so that downstream CLI flags (`--format cbor`) don't get a "did you mean" alias hijack. Adding either requires a §15 amendment to this doc, a corresponding wire-format spec, and an update to the SOS-03 harness.

### 5.2 `EventInjectionMode` — Specification Required

How input events enter the simulator.

| Name | Meaning |
|---|---|
| `PreLoaded` | The entire vector (`input` array) is read at simulator startup and held in memory. Events are dispatched sequentially. v1 default. Simpler determinism story (no I/O races); sufficient for SOS-03 vectors which are bounded-length by construction. |
| `Streaming` *(reserved)* | Events arrive on stdin one JSON document per line; the simulator processes each on arrival and emits a trace record on stdout. Reserved for future interactive / fuzzing scenarios. Not implemented at v1. |

v1 (per PCDN-SOS-02-006): `PreLoaded`. Streaming MAY be added in a localised diff once the v1 simulator passes the SOS-03 suite.

### 5.3 `SimulatorFeature` — Standards Action

Capability tags published by the simulator at runtime (`sos-sim --features` or via the library API). Lets downstream tooling assert "this `sos-sim` build supports the feature my vector requires."

| Name | Meaning |
|---|---|
| `HandCompiledScripts` | The simulator drives `<script>` bodies via a static dispatch table to Rust functions. MANDATORY at v1; every conforming `sos-sim` build advertises this feature. |
| `AstWalkScripts` *(reserved)* | The simulator drives `<script>` bodies via an AST walker over a SOS-01-ratified parse of the chart's ECMAScript subset. Reserved pending SOS-01's deferred AST-vs-trace decision (PCDN-SOS-00-005). |
| `TraceReplayScripts` *(reserved)* | The simulator drives `<script>` bodies by replaying a previously-captured execution trace. Reserved for SOS-06 codegen-comparison scenarios where the codegen output emits the trace and the simulator validates by replay. |

Adding a value (or moving one out of *reserved*) requires a §15 amendment.

### 5.4 `ObservableField` — Standards Action

The frozen list of fields a `TraceRecord` carries. Restated from SOS-00 §7.2; SOS-02 owns the *serialisation order* of these fields (§7.1 below) but cannot add, remove, or rename.

| Name | Type (Rust) | Source-of-truth datamodel cell |
|---|---|---|
| `after_input_idx` | `i64` | not a datamodel cell — the position in the vector's `input` array; `-1` for the boot-quiescence record |
| `current` | `i32` | `current` |
| `tick_count` | `i64` | `tick_count` |
| `rc` | `i32` | `rc` |
| `tcb` | `Vec<TcbSnapshot>` (length `MAX_TASKS`) | `tcb[i].{id, prio, state, deadline, blk_obj, msg}` for each `i` |
| `ready` | `Vec<Vec<i32>>` (length `MAX_PRIO`, inner is task-id sequence) | `ready[p]` |
| `sems` | `Vec<SemSnapshot>` (length `MAX_SEMS`, only `valid` entries' inner fields are observed) | `sems[s].{valid, count, max, waiters}` |
| `queues` | `Vec<QueueSnapshot>` (length `MAX_QUEUES`, only `valid` entries' inner fields are observed) | `queues[q].{valid, count, cap, buf, sendw, recvw}` |
| `irq_nest` | `i32` | `irq_nest` |
| `sched_lock` | `i32` | `sched_lock` |
| `pend_ticks` | `i32` | `pend_ticks` |

Excluded (intentionally not observable; mirrors SOS-00 §7.2): PendSV pending state, BASEPRI value, raw register contents, ISR latency, microstep interleaving within a macrostep. The macrostep is the atomic unit of observation.

Adding a value requires a §15 amendment to SOS-00 §7.2 *first* (because §7.2 is the source of truth), then a mirroring amendment here.

## 6. Architecture

This section is **load-bearing**. It is what an implementer reads when they sit down to write `sos-sim`. It is what a reviewer reads when they ask "is this implementation faithful to the chart?"

### 6.1 Module layout

The `sos-sim` crate has the following top-level structure. Directory paths are relative to the crate root `sim/sos-sim/`.

```
sim/sos-sim/
├── Cargo.toml
├── src/
│   ├── lib.rs            # public API surface; re-exports
│   ├── simulator.rs      # struct Simulator + step harness
│   ├── datamodel.rs      # struct Datamodel + Tcb + Sem + Queue
│   ├── events.rs         # enum Event + parsing
│   ├── trace.rs          # struct Trace + TraceRecord + snapshot logic + serializer
│   ├── vector.rs         # struct Vector + Config + loader
│   ├── scripts.rs        # hand-compiled <script> bodies — ONE Rust fn per <script> block
│   ├── provider.rs       # trait ScriptProvider + struct HandCompiledScripts
│   └── bin/
│       └── sos-sim.rs    # CLI entry point
└── tests/                # crate-local unit tests (NOT the SOS-03 conformance suite)
    └── smoke.rs
```

Public API exports (from `lib.rs`):

| Symbol | Kind | Role |
|---|---|---|
| `Simulator` | `struct` | Top-level kernel-instance. Owns a `Datamodel`, a `ScriptProvider`, and a `Trace` buffer. |
| `Datamodel` | `struct` | The full mutable state. Mirrors every `<data id="...">` in the chart. |
| `Tcb` | `struct` | One task control block. Fields `id, prio, state, deadline, blk_obj, msg`. |
| `Sem` | `struct` | One semaphore. Fields `valid, count, max, waiters`. |
| `Queue` | `struct` | One message queue. Fields `valid, cap, count, buf, sendw, recvw`. |
| `Event` | `enum` | An external event. One variant per `<transition event="...">` in the chart. Carries the `_event.data` payload as variant fields. |
| `EventName` | `enum` | The string-name view of `Event` — used at parse time. Mirrors SOS-01's forthcoming `ExternalEventName` enum (forward-ref). |
| `Trace` | `struct` | Ordered sequence of `TraceRecord`. Owns the on-disk serialisation. |
| `TraceRecord` | `struct` | One observable-state snapshot. Fields per §5.4. |
| `Vector` | `struct` | Parsed vector input. Fields `name, config, input, expected_trace`. |
| `Config` | `struct` | Per-vector sizing: `max_tasks`, `max_prio`, `max_sems`, `max_queues`, `q_depth`, `tick_hz`. |
| `ScriptProvider` | `trait` | The pluggable script-execution surface. v1 has one impl: `HandCompiledScripts`. |
| `HandCompiledScripts` | `struct` | Static dispatch from script-name to Rust function. Constructed via `HandCompiledScripts::new()`. Zero-sized. |
| `TaskState` | `enum` | Re-export of SOS-00 §5.1. |
| `ReturnCode` | `enum` | Re-export of SOS-00 §5.2. |
| `SimError` | `enum` | Concrete error type for the library API. Variants: `VectorParse`, `InvariantViolation(String)`, `UnknownEvent(String)`, `Io(io::Error)`. |

The CLI binary `bin/sos-sim.rs` consumes only the public API; no private modules are reached through.

### 6.2 Macrostep execution model

The simulator's step harness implements W3C SCXML 1.0 §3.13 macrostep semantics over the chart's `<parallel id="running">` block. The control flow:

1. **External event arrives** (from `Vector.input[i]`). The harness converts the JSON event object to an `Event` enum variant via `events::parse_event(&json) -> Event`.

2. **Set `current` from `from_tid`.** Per SOS-00 §7.1, vectors carry an optional `from_tid` on each input event. If present, the harness assigns `dm.current = from_tid` *before* dispatching, modelling "task X issued this syscall". If absent (`null`), `dm.current` is left untouched (ISR-context events).

3. **Dispatch to transition body.** The harness matches the `Event` variant to the corresponding `<transition>` in the chart and invokes the transpiled body via the active `ScriptProvider`. The body mutates `Datamodel`, possibly raises one or more internal events (`sched.run` is the common one; `kernel.boot.done` is the boot-time one).

4. **Drain internal-event queue.** The harness keeps a single `VecDeque<Event>` internal queue. While non-empty, it pops the head, dispatches to its transition body, and continues. Per SOS-00 §3 and W3C SCXML 1.0 §3.13, this loop is the macrostep. Per the chart's structure (every state-mutating transition raises at most `sched.run`), the loop terminates after at most 2 internal events per external event.

5. **Reach quiescence.** Internal queue empty. The macrostep is complete.

6. **Emit `TraceRecord`.** The harness calls `Trace::snapshot(&self.dm, after_input_idx)` and appends the record to the buffer. INV-S-SIM-6 guarantees this happens only at quiescence.

7. **Loop to step 1** until the vector's input array is exhausted.

The boot block is a special case: there is a synthetic "input index -1" record emitted after the boot macrostep completes (i.e. after `kernel.boot.done` has fired and the chart has settled in `running`). This gives downstream tools a consistent "before any user event" baseline.

INV-S2 (macrostep atomicity, SOS-00) is trivially satisfied: the simulator is single-threaded; only one transition body runs at a time by construction.

### 6.3 Hand-compiled `<script>` ABI

Per PCDN-SOS-00-005 → (b), each `<script>` block in the .scxml is transpiled by hand into a Rust function. The transpilation is mechanical; the lint rules SOS-01 will ratify constrain the surface to the subset that transpiles cleanly.

**Signature.** Every transpiled script function has shape:

```text
fn script_<NAME>(dm: &mut Datamodel, ev: &Event)
```

The `ev` parameter carries `_event.data` (per chart vocabulary). Scripts that ignore the event (e.g. `task.yield`, `crit.enter`) accept the parameter and do not read it. Scripts that ignore the datamodel (none, in practice) accept the parameter and do not write it.

**Naming convention.** Script names map 1:1 to `<script>` blocks in the chart, in document order. The naming pattern:

| Chart location | Function name |
|---|---|
| Top-level `<script>` (the "HELPERS" block at the chart root) | Helpers are NOT a single function; each helper (`readyq_init`, `ready_push`, `ready_remove`, `ready_pop_highest`, `waiters_insert`, `block_current`, `unblock`, `waiter_cancel`, `pick_next`) becomes a free function `fn helper_<name>(dm: &mut Datamodel, ...)` in `scripts.rs`. |
| `<state id="boot"><onentry><script>` | `script_boot_onentry_0` |
| `<state id="sched_idle"><transition event="sched.run"><script>` | `script_sched_idle_sched_run_0` |
| `<state id="tick_idle"><transition event="sys.tick"><script>` | `script_tick_idle_sys_tick_0` |
| `<state id="sys_idle"><transition event="task.create"><script>` | `script_sys_idle_task_create_0` |
| `<state id="sys_idle"><transition event="task.delay"><script>` | `script_sys_idle_task_delay_0` |
| `<state id="sys_idle"><transition event="task.yield"><script>` | `script_sys_idle_task_yield_0` |
| `<state id="sys_idle"><transition event="task.suspend"><script>` | `script_sys_idle_task_suspend_0` |
| `<state id="sys_idle"><transition event="task.resume"><script>` | `script_sys_idle_task_resume_0` |
| `<state id="sys_idle"><transition event="sem.create"><script>` | `script_sys_idle_sem_create_0` |
| `<state id="sys_idle"><transition event="sem.take"><script>` | `script_sys_idle_sem_take_0` |
| `<state id="sys_idle"><transition event="sem.give"><script>` | `script_sys_idle_sem_give_0` |
| `<state id="sys_idle"><transition event="sem.give_from_isr"><script>` | `script_sys_idle_sem_give_from_isr_0` |
| `<state id="sys_idle"><transition event="queue.create"><script>` | `script_sys_idle_queue_create_0` |
| `<state id="sys_idle"><transition event="queue.send"><script>` | `script_sys_idle_queue_send_0` |
| `<state id="sys_idle"><transition event="queue.receive"><script>` | `script_sys_idle_queue_receive_0` |
| `<state id="sys_idle"><transition event="queue.send_from_isr"><script>` | `script_sys_idle_queue_send_from_isr_0` |
| `<state id="prot_idle"><transition event="crit.enter"><script>` | `script_prot_idle_crit_enter_0` |
| `<state id="prot_idle"><transition event="crit.exit"><script>` | `script_prot_idle_crit_exit_0` |
| `<state id="prot_idle"><transition event="sched.suspend"><script>` | `script_prot_idle_sched_suspend_0` |
| `<state id="prot_idle"><transition event="sched.resume"><script>` | `script_prot_idle_sched_resume_0` |

The trailing `_0` accommodates the future case of a transition body containing more than one `<script>` element (none today; reserved). The `<transition event="sched.run" cond="sched_lock &gt; 0"/>` predicate-only transition in `sched_idle` has no `<script>` and therefore no function.

**Transpilation rules** (mechanical, SOS-01 will lint):

| ECMAScript construct | Rust translation |
|---|---|
| `var x = expr;` | `let mut x = expr;` (Rust let-mut at function scope) |
| `var x;` (undeclared init) | `let mut x: ... = Default::default();` (type from first assignment) |
| `for (var i = 0; i < N; i++) { ... }` | `for i in 0..N { ... }` |
| `for (var i = 0; i < arr.length; i++)` | `for i in 0..arr.len()` |
| `arr.push(x)` | `arr.push(x)` |
| `arr.shift()` | `arr.remove(0)` (chart is small; O(N) acceptable) |
| `arr.splice(i, n)` | `arr.drain(i..i+n)` collected as needed; for n=1 use `arr.remove(i)` |
| `arr.indexOf(x)` | `arr.iter().position(|v| *v == x).map(|i| i as i32).unwrap_or(-1)` |
| `arr.length` | `arr.len()` (cast to `i32` / `i64` at use-site) |
| `obj.field` | `obj.field` (named struct field; type from `Datamodel` definition) |
| `obj.field = x` | `obj.field = x` |
| `tcb[i].state = ST_X` | `dm.tcb[i as usize].state = TaskState::X` |
| `tcb[d.id]` | `dm.tcb[d.id as usize]` (`d` bound to `ev` payload) |
| Numeric literal `0` / `-1` / `8` | Same; type-context determined by Rust's elaboration |
| `null` (in `msg`) | `Msg::Null` (see §6.3.1 on the `Msg` discriminated union) |
| `_event.data` | `ev` parameter (already in scope) |
| `if (cond) { ... } else { ... }` | `if cond { ... } else { ... }` |
| `&&`, `\|\|`, `!`, `==`, `!=`, `<`, `<=`, `>`, `>=` | Same |

**Identifiers.** Chart-side identifiers (`MAX_TASKS`, `ST_DORMANT`, `RC_OK`) are mapped to Rust `const` items in `datamodel.rs` (for the numeric constants) and to `enum TaskState` / `enum ReturnCode` variants (for the typed sets). The transpiled scripts use the const items where the chart uses raw integers; they use the enum variants where the chart's `<data id="ST_*">` declarations are inspected as state identifiers.

#### 6.3.1 `Msg` representation

The chart's `msg` field carries either a queue payload (an arbitrary integer in the v1 chart; the chart's `<data>` does not constrain) or a return code (deposited at unblock). SOS-02 represents this as a discriminated union:

```text
enum Msg {
    Null,
    Int(i64),
    ReturnCode(ReturnCode),
}
```

Transpilation of `tcb[i].msg = RC_OK` becomes `dm.tcb[i].msg = Msg::ReturnCode(ReturnCode::Ok)`. Transpilation of `tcb[i].msg = d.msg` (where `d.msg` is a queue payload) becomes `dm.tcb[i].msg = Msg::Int(d.msg)`. The wire format (§7) encodes `Msg` as a JSON value (`null`, an integer, or a small object `{"rc": <name>}` — see §7.2).

### 6.4 Trace emission

A `TraceRecord` is written at exactly the points specified by INV-S-SIM-6:

1. After boot macrostep quiescence (the `after_input_idx = -1` baseline record).
2. After each external-event macrostep reaches quiescence (records with `after_input_idx >= 0`).

The harness calls `Trace::snapshot(dm, after_input_idx)`, which:

1. Reads the datamodel observables per §5.4.
2. Constructs a `TraceRecord` with fields in the **canonical order** specified in §7.1.
3. Pushes the record into the in-memory `Vec<TraceRecord>` (for `PreLoaded` mode) and, if a writer was supplied, immediately writes it to the output sink as one JSON-encoded line.

Two emission disciplines coexist:

- **In-memory** (`Simulator::run_to_completion() -> Trace`): the entire trace lives in `Vec<TraceRecord>` for downstream API consumers (the SOS-03 harness diffs in-memory traces from two sources).
- **Streaming** (`Simulator::run_with_writer<W: Write>(w: W) -> io::Result<()>`): each record is JSON-encoded and written immediately. The CLI uses this path. INV-S-SIM-7 forbids buffering policy that delays records past quiescence.

### 6.5 Determinism budget

The simulator offers the following concrete guarantees. INV-S-SIM-1 through INV-S-SIM-3 enforce these at the spec level; §9 carries the normative invariants.

**Hard guarantees (MUST):**

- Same input vector + same `sos-sim` build → same trace bytes. Byte-equal — not just semantically equal.
- No reads from system time (`std::time::Instant::now`, `SystemTime::now`).
- No reads from environment variables at runtime. (Reading env vars at build-time to set version strings is permitted; runtime reads are forbidden.)
- No reads from external files other than the input vector (and the output trace file if `--out` is supplied).
- No use of `std::collections::HashMap`, `HashSet`, or any `Hash`-derived iteration. Keyed structures use `BTreeMap` / `BTreeSet`; the datamodel is *array-based* throughout, mirroring the chart, so this constraint mostly applies to scratch state within the harness.
- No `thread::spawn`, no `std::thread::sleep`, no parallelism. The simulator is single-threaded.
- No allocator-address-dependent code paths. Specifically: no `format!("{:p}", &x)`-style debug strings reaching the trace; no use of `Box::new` followed by pointer comparison.

**Soft guarantees (SHOULD):**

- The simulator SHOULD be reproducible across rustc versions at the same `Cargo.toml` lockfile pin. Cross-version reproducibility is not a hard guarantee because rustc may change integer-arithmetic codegen for `panic-on-overflow` builds in debug; the SOS-03 harness runs in `--release` to dodge this.
- The simulator SHOULD produce identical traces across host operating systems (Linux, macOS). It MAY produce different traces if a JSON serialiser ever inserts platform-specific newlines; the JSONL writer in `trace.rs` explicitly writes `\n` and never `\r\n`.

**Non-guarantees:**

- The simulator is not byte-equal to its own output across `sos-sim` versions. A new SOS-02 release MAY change formatting (whitespace, field ordering) IF it bumps the major version and ratifies the change in §15. The SOS-03 suite is regenerated when this happens.
- The simulator is not byte-equal to the SOS-04 / SOS-05 port outputs at the file level — those ports may use different output drivers. The conformance comparison is record-by-record, not file-by-file (the conformance harness, SOS-03, owns this).

### 6.6 CLI shape

The `sos-sim` binary has one subcommand at v1: `run`. The CLI grammar:

```
sos-sim run --vector <PATH> [--out <PATH>] [--format <FORMAT>]
sos-sim --version
sos-sim --help
```

Arguments:

| Flag | Type | Default | Meaning |
|---|---|---|---|
| `--vector <PATH>` | path (required) | — | Path to the vector JSON file. Use `-` to read from stdin (entire file is buffered before parsing — PreLoaded mode). |
| `--out <PATH>` | path (optional) | stdout | Path to write the trace. Use `-` (or omit) for stdout. |
| `--format <FORMAT>` | `jsonl` (v1 only) | `jsonl` | Trace serialisation format. v1 only accepts `jsonl`; reserved values `cbor`, `msgpack` are recognised at parse time and rejected with exit code 4 ("unsupported format"). |

Exit codes:

| Code | Meaning |
|---|---|
| `0` | Trace emitted successfully; all input events consumed. |
| `1` | Vector parse error. Includes JSON syntax errors and SOS-01-lint violations (forward-ref). stderr carries a one-line description. |
| `2` | Simulator runtime error: an INV-S or INV-S-SIM invariant was violated mid-run, OR the simulator's transpiled body returned an inconsistent state. stderr carries the invariant identifier and a one-line snapshot. |
| `3` | I/O error: cannot read the vector file, cannot write the trace, stdout closed mid-stream. |
| `4` | Unsupported format requested (e.g. `--format cbor` at v1). |
| `5` | Reserved. |

The binary MUST NOT consult environment variables (per INV-S-SIM-2). It MUST NOT open any file other than `--vector` (input) and `--out` (output). It MUST flush stdout / the output file before exiting.

### 6.7 Extension points for SOS-01's deferred decision

PCDN-SOS-00-005 deferred to SOS-01 the question of whether SOS-02 *additionally* drives the chart via an AST-walk or trace-replay engine, beyond the hand-compiled bootstrap. SOS-02 v1 ships only the hand-compiled path, BUT it does so behind an abstraction that makes adding an alternative a localised diff.

The abstraction is the `ScriptProvider` trait:

```text
trait ScriptProvider {
    // Dispatch to a named <script> body. The simulator's harness passes the
    // canonical script name (per §6.3 naming convention) and a mutable
    // datamodel reference plus the event payload. Implementations MUST NOT
    // raise events or perform I/O; they MUST be pure functions of (dm, ev).
    fn run_script(&self, name: &str, dm: &mut Datamodel, ev: &Event);
}
```

v1 has one implementation:

```text
struct HandCompiledScripts;
impl ScriptProvider for HandCompiledScripts {
    fn run_script(&self, name: &str, dm: &mut Datamodel, ev: &Event) {
        match name {
            "script_boot_onentry_0" => scripts::script_boot_onentry_0(dm, ev),
            "script_sched_idle_sched_run_0" => scripts::script_sched_idle_sched_run_0(dm, ev),
            // ... one arm per row of the §6.3 table ...
            other => panic!("unknown script: {}", other),
        }
    }
}
```

The `Simulator` is constructed via `Simulator::with_script_provider(provider)`. The default constructor `Simulator::new()` is shorthand for `Simulator::with_script_provider(HandCompiledScripts)`.

Future SOS-01-ratified implementations (`AstWalkScripts`, `TraceReplayScripts`) add a struct + an `impl ScriptProvider` block; no change to `Simulator`, `Datamodel`, `Event`, `Trace`, or the harness. The trait is the **only** abstraction layer in `sos-sim`; the rest is concrete types.

INV-S-SIM-5 (below) constrains the v1 simulator to only ship `HandCompiledScripts`; alternate providers ratify in SOS-01 (or later) §15 amendments.

## 7. Trace serialisation format

The on-wire format is **JSON Lines** (RFC 7464, "JavaScript Object Notation (JSON) Text Sequences", and the broader JSONL convention). One JSON object per line, UTF-8 encoded, LF line terminator (no CR). The simulator emits no trailing whitespace, no blank lines between records, and no leading byte-order mark.

The schema source is SOS-00 §7.1. SOS-02 ratifies the *field order* in each record, the encoding of each typed value, and the boot-baseline record's representation.

### 7.1 `TraceRecord` field order

The canonical JSON object for one `TraceRecord` has fields in this exact order. JSON object key ordering is technically unordered per RFC 8259, but byte-equality across simulator runs requires a stable order — `serde_json` preserves insertion order when constructing from a `BTreeMap` or from a struct via the `Serialize` derive. SOS-02 uses the `Serialize` derive on `TraceRecord` with `#[serde(rename_all = "snake_case")]` and the field declaration order shown.

```json
{"after_input_idx": -1, "current": 0, "tick_count": 0, "rc": 0, "tcb": [...], "ready": [...], "sems": [...], "queues": [...], "irq_nest": 0, "sched_lock": 0, "pend_ticks": 0}
```

Field order:
1. `after_input_idx`
2. `current`
3. `tick_count`
4. `rc`
5. `tcb`
6. `ready`
7. `sems`
8. `queues`
9. `irq_nest`
10. `sched_lock`
11. `pend_ticks`

### 7.2 Typed value encoding

JSON has only one numeric type; the column "in-memory type" below is the canonical Rust type the simulator (and the SOS-04 / SOS-05 ports) MUST use. The "wire form" column documents how serde renders that type. Where the wire widens beyond the in-memory type (deliberately — see Amendment 001 in §15), the widening is value-preserving (no information loss); recipients downcast safely.

| Field | In-memory type | Wire form | Encoding rule |
|---|---|---|---|
| `after_input_idx` | `i64` | signed integer | `-1` for the boot baseline record; otherwise the zero-based index into `Vector.input`. |
| `current` | `TaskId` = `i16` (per SOS-00 §3) | signed integer (widened to `i32` on the wire) | The chart's `current` cell. `-1` when no task is running. Wire widening is intentional — keeps the trace robust to future `TaskId` widening without re-keying every vector. |
| `tick_count` | `i64` | signed integer | The chart's `tick_count`. Always `>= 0`. |
| `rc` | `ReturnCode` (`i8`-discriminant enum per SOS-00 §5.2) | signed integer | One of `0` / `-1` / `-2` / `-3` / `-4`. |
| `tcb[i].id` | `TaskId` = `i16` | signed integer (widened to `i32`) | Same widening pattern as `current`. |
| `tcb[i].prio` | `u8` | unsigned integer | `0..MAX_PRIO`. |
| `tcb[i].state` | `TaskState` (`u8`-discriminant enum per SOS-00 §5.1) | unsigned integer | `0..=7`. |
| `tcb[i].deadline` | `i64` | signed integer | Tick value, or `0` for "infinite wait". |
| `tcb[i].blk_obj` | `i16` | signed integer (widened to `i32`) | Sem / queue index, or `-1` when not blocked. |
| `tcb[i].msg` | `Msg` (per SOS-00 §5.6, §15 Amendment 004) | `null` \| signed integer \| `{"rc": <i8>}` | The on-wire discriminator object form preserves the chart's distinction between "queue payload that happens to equal 0" (`Msg::Int(0)`) and "return code `RC_OK`" (`Msg::ReturnCode(Ok)` → `{"rc": 0}`). |
| `ready[p]` | `Vec<TaskId>` per `p` | array of signed integers (each widened to `i32`) | FIFO of task-ids at priority `p`. Empty array when no task is ready. Outer length is `MAX_PRIO`. |
| `sems[s]` | `Sem` (per `sim/sos-sim/src/datamodel.rs`) | object — `{"valid": false}` short form when invalid; full record when valid | Short form is canonical per SOS-03 PCDN-007. Full form: `valid` (`true`), `count` (unsigned), `max` (unsigned), `waiters` (array of widened TaskIds, head first). |
| `queues[q]` | `Queue` | object — symmetric to sems | Short: `{"valid": false}`. Full: `valid`, `cap`, `count`, `buf` (array of payloads in FIFO order), `sendw`, `recvw`. |
| `irq_nest` | `u32` | unsigned integer (wire-widened to `i32`-range; always emitted as a non-negative integer) | `>= 0`. |
| `sched_lock` | `u32` | unsigned integer (same widening) | `>= 0`. |
| `pend_ticks` | `u32` | unsigned integer (same widening) | `>= 0`. |

The "valid==false short form" for sems and queues is deliberate: at v1 the chart pre-allocates all slots as invalid descriptors at boot, so the boot baseline trace is dominated by `{"valid": false}` entries. Omitting the zeroed inner fields keeps the trace readable; the trace is human-readable as a debugging artifact, not only machine-diffed.

### 7.3 Example trace record

The boot-baseline trace record, immediately after the chart's `<boot>` macrostep settles, with `MAX_TASKS=8`, `MAX_PRIO=8`, `MAX_SEMS=8`, `MAX_QUEUES=4`:

```json
{"after_input_idx":-1,"current":0,"tick_count":0,"rc":0,"tcb":[{"id":0,"prio":0,"state":2,"deadline":0,"blk_obj":-1,"msg":null},{"id":1,"prio":0,"state":0,"deadline":0,"blk_obj":-1,"msg":null},{"id":2,"prio":0,"state":0,"deadline":0,"blk_obj":-1,"msg":null},{"id":3,"prio":0,"state":0,"deadline":0,"blk_obj":-1,"msg":null},{"id":4,"prio":0,"state":0,"deadline":0,"blk_obj":-1,"msg":null},{"id":5,"prio":0,"state":0,"deadline":0,"blk_obj":-1,"msg":null},{"id":6,"prio":0,"state":0,"deadline":0,"blk_obj":-1,"msg":null},{"id":7,"prio":0,"state":0,"deadline":0,"blk_obj":-1,"msg":null}],"ready":[[],[],[],[],[],[],[],[]],"sems":[{"valid":false},{"valid":false},{"valid":false},{"valid":false},{"valid":false},{"valid":false},{"valid":false},{"valid":false}],"queues":[{"valid":false},{"valid":false},{"valid":false},{"valid":false}],"irq_nest":0,"sched_lock":0,"pend_ticks":0}
```

(Idle is `tcb[0]`, state `2` = `ST_RUNNING`, in `current`; the other slots are `ST_DORMANT`. `ready[0]` is empty because idle was popped from it by `pick_next()` during the boot macrostep.)

A post-`task.create` record (after the first user event in a vector with `from_tid: null`, creating task 1 at priority 3):

```json
{"after_input_idx":0,"current":1,"tick_count":0,"rc":0,"tcb":[{"id":0,"prio":0,"state":1,"deadline":0,"blk_obj":-1,"msg":null},{"id":1,"prio":3,"state":2,"deadline":0,"blk_obj":-1,"msg":null},{"id":2,"prio":0,"state":0,"deadline":0,"blk_obj":-1,"msg":null},{"id":3,"prio":0,"state":0,"deadline":0,"blk_obj":-1,"msg":null},{"id":4,"prio":0,"state":0,"deadline":0,"blk_obj":-1,"msg":null},{"id":5,"prio":0,"state":0,"deadline":0,"blk_obj":-1,"msg":null},{"id":6,"prio":0,"state":0,"deadline":0,"blk_obj":-1,"msg":null},{"id":7,"prio":0,"state":0,"deadline":0,"blk_obj":-1,"msg":null}],"ready":[[0],[],[],[],[],[],[],[]],"sems":[{"valid":false},{"valid":false},{"valid":false},{"valid":false},{"valid":false},{"valid":false},{"valid":false},{"valid":false}],"queues":[{"valid":false},{"valid":false},{"valid":false},{"valid":false}],"irq_nest":0,"sched_lock":0,"pend_ticks":0}
```

(Task 1 at priority 3 preempted idle. Idle moves back into `ready[0]`; task 1 becomes `RUNNING`.)

### 7.4 Field name policy

Field names use `snake_case`, matching the chart's `<data id="...">` declarations verbatim where the chart uses snake_case (`tick_count`, `blk_obj`, `sched_lock`, `irq_nest`, `pend_ticks`). The chart's mixed-case identifiers (`MAX_TASKS` etc.) are not surfaced in the trace (they appear only in the vector's `config`). The wire format MUST NOT rename a chart-side cell during emission; SOS-01's lint MAY enforce this.

## 8. Build-time and runtime artifact map

| Artifact | Path (relative to subrepo root) | Build-time? | Runtime? | Notes |
|---|---|---|---|---|
| Workspace `Cargo.toml` | `Cargo.toml` (at subrepo root) | input | n/a | Per PCDN-SOS-02-005, expected at SOS-02 implementation land. Single workspace; `sim/sos-sim/` is its first member. |
| Lockfile | `Cargo.lock` | input | n/a | Committed. Pins `serde`, `serde_json`, `clap` (if used), `anyhow` to exact versions for byte-deterministic builds. |
| `sos-sim` crate | `sim/sos-sim/` | n/a | host binary | The simulator. |
| `sos-sim` library | `sim/sos-sim/src/lib.rs` | output | linked into bin + downstream consumers (e.g. the SOS-03 harness in a future phase) |
| `sos-sim` CLI binary | `sim/sos-sim/src/bin/sos-sim.rs` → `target/release/sos-sim` | output | runtime | The host-runnable binary. |
| Unit tests | `sim/sos-sim/tests/` | n/a | `cargo test -p sos-sim` | Smoke tests for the simulator itself. NOT the SOS-03 suite (which lives at `conformance/` per SOS-00 §8). |
| Vector samples | `sim/sos-sim/tests/fixtures/` | input | input (test harness) | Tiny hand-authored vectors for smoke testing. SOS-03 owns the canonical suite. |
| MSRV declaration | `sim/sos-sim/Cargo.toml` (`rust-version = "1.75"`) | input | n/a | See PCDN-SOS-02-004. |

Build commands (host, no cross-compile):

```
# Build
cargo build -p sos-sim
cargo build --release -p sos-sim

# Test (smoke)
cargo test -p sos-sim

# Run
cargo run -p sos-sim -- run --vector path/to/vector.json
cargo run --release -p sos-sim -- run --vector path/to/vector.json --out trace.jsonl
```

The simulator MUST NOT have a `[features]` block in its `Cargo.toml` at v1. PCDN-SOS-02-007 (added below) considers whether the optional `clap` dependency should be feature-gated; the recommendation is no, to keep the build matrix at 1.

## 9. Invariants

Each invariant carries a stable ID. Amendments require a §15 entry. INV-S-SIM-N invariants are simulator-scoped; they MUST be consistent with SOS-00 §9 invariants and MUST NOT relax or contradict any INV-S-N.

- **INV-S-SIM-1 — Byte-deterministic trace.** The simulator's output trace MUST be byte-identical across runs of the same `sos-sim` build on the same vector. (Cross-build determinism is a SHOULD per §6.5.)
- **INV-S-SIM-2 — No ambient input.** The simulator MUST NOT depend on system time, environment variables, network sockets, the user's locale, or any input other than the vector file (and the output trace file path). Reads of `std::time::Instant::now`, `SystemTime::now`, or `std::env::var` from the simulator's library or binary code are forbidden.
- **INV-S-SIM-3 — Sorted iteration over keyed structures.** Any internal scratch structure keyed by a non-trivial key (string, struct) MUST use `BTreeMap` / `BTreeSet`, never `HashMap` / `HashSet`. The datamodel itself is array-indexed throughout (mirroring the chart), so this constraint primarily applies to harness scratch state.
- **INV-S-SIM-4 — Host-only target.** The simulator MUST NOT compile for any embedded target (`thumbv7em-none-eabihf`, `thumbv7em-none-eabi`, etc.). The crate's `Cargo.toml` declares no embedded-target compatibility; the source MAY use `std`, `alloc`, and the host filesystem freely. Per PCDN-SOS-00-005 / SOS-00 §10, the simulator's allocator-permitted nature is intentional: it relaxes INV-S12 (static-only) only for the host-binary form; the embedded ports (SOS-04, SOS-05) re-impose INV-S12.
- **INV-S-SIM-5 — Single v1 ScriptProvider.** The v1 simulator MUST ship exactly one `ScriptProvider` implementation, `HandCompiledScripts`. Alternative providers (`AstWalkScripts`, `TraceReplayScripts`) ratify in SOS-01 §15 amendments first.
- **INV-S-SIM-6 — Trace at quiescence.** A `TraceRecord` MUST be emitted at and only at macrostep quiescence (post-boot baseline; post-external-event quiescence). The simulator MUST NOT emit a record mid-macrostep. (This preserves SOS-00 INV-S2 macrostep atomicity at the observation surface.)
- **INV-S-SIM-7 — No buffering past quiescence.** When the simulator writes traces to a streaming sink (`Simulator::run_with_writer`), each record MUST be flushed to the sink before the next macrostep begins. Buffering that delays a record past quiescence is forbidden. (Rationale: a partial trace from a panicking simulator is more diagnostically useful than a trace that ends one record short of where the bug actually is.)
- **INV-S-SIM-8 — No chart amendment from the simulator.** The simulator MUST NOT modify `rtos_kernel.scxml` at runtime, MUST NOT depend on `rtos_kernel.scxml` being present in the filesystem at runtime (the chart's behaviour is baked into `scripts.rs` at build time), and MUST NOT carry a "patches.json" or similar override file. Behaviour changes ratify via SOS-00 §15, then update the chart, then regenerate `scripts.rs`. This mirrors SOS-00 INV-S11 at the simulator surface.
- **INV-S-SIM-9 — Faithful enum re-export.** The simulator's `TaskState` and `ReturnCode` enums MUST be exact re-exports (variant names and integer discriminants per SOS-00 §5.1 and §5.2). Adding a variant requires a §15 amendment to SOS-00 *first*. The integer discriminants serialise into the trace per §7.2; drift would corrupt the wire format.
- **INV-S-SIM-10 — Single-statechart instance.** The simulator hosts exactly one instance of the kernel per `Simulator` value. Constructing `N` `Simulator` values yields `N` independent kernels with no shared state and no inter-kernel events. (Mirrors SOS-00 INV-S14 at the simulator surface; reinforces that SMP / multi-instance is out of scope.)

## 10. Reconciliation with adjacent repo primitives

SOS-02 deliberately stays narrow. The reconciliation table makes explicit what it is *not*:

| Primitive | Relationship to SOS-02 |
|---|---|
| `streamz-exec` (parent `softoboros.com` Tokio-hosted streamz runtime) | Not a consumer. `sos-sim` is synchronous, single-threaded, and does not import Tokio. The two never coexist in a single process. |
| `cortex-m` / `cortex-m-rt` crates | Not a dependency. INV-S-SIM-4 forbids embedded targets; the simulator never sees the M7 primitive layer. |
| FreeRTOS-Kernel at `disco-analyzer/analyzer-rtos/` | Not a dependency. SOS-00 INV-S10 forbids code borrowing; vocabulary borrowing is permitted. |
| `analyzer-cm7` / `analyzer-cm4` crates (disco-analyzer family) | Not a dependency. SOS shares the bench board *with* DAA in flash-swap mode (per PCDN-SOS-00-001 → (b)); it does not link against DAA crates. |
| `rlvgl` family (parent `ops/packer/submodules/rlvgl/`) | Not a dependency. The simulator has no UI. |
| `serde` / `serde_json` / `clap` / `anyhow` | Mirror dependencies. Pinned in `Cargo.lock`; no SOS-02-side forks. |
| SOS-04 (M7 Rust port, future) | Sibling. Same `Datamodel` shape, same script bodies (because the chart is one); different harness (M7 port uses interrupt-driven event injection, not vector-replay). Trace format identical — that's the conformance contract. |
| SOS-05 (M7 C port, future) | Sibling. Different language, identical trace format. The conformance harness (SOS-03) compares traces from both against SOS-02's. |
| SOS-03 (conformance vectors, future) | Consumer. Imports `sos-sim` as a library; uses `Simulator::run_to_completion` to generate canonical traces; emits each as the `expected_trace` half of a fixture. |
| SOS-06 (codegen, future) | Compares against SOS-02 traces by definition. May add `TraceReplayScripts` provider per §6.7 to inject codegen-generated traces into the simulator's framework. |

The simulator is **a standalone host binary plus library**. It has no upstream consumers (it IS the upstream of SOS-03, SOS-04, SOS-05, SOS-06) and minimal downstream dependencies (the four crates in §4).

## 11. Non-goals

Explicit non-goals for SOS-02 v1. Each is a localised future amendment (none requires restructuring the crate).

- **Performance optimisation.** The v1 simulator targets *clarity over speed*. Hand-compiled scripts use `Vec::remove(0)` instead of a ring buffer; iteration is naive; no profile-guided rebuilds. The 8-task, 8-priority chart is small enough that wall-clock matters for nobody.
- **Interactive REPL.** The CLI is one-shot run. `sos-sim run --vector X` reads, computes, writes, exits. No "drop into a prompt", no step-by-step debugger.
- **GUI / visualisation.** The deliverable is text JSONL on stdout. Visualisation (a state-diagram replay player, a Gantt of task scheduling) rides in a separate downstream tool and is not bounded by this phase.
- **Multiple kernels per simulator instance.** One `Simulator` value, one kernel. Multi-instance SMP-modelling is excluded by SOS-00 INV-S14 and re-asserted by INV-S-SIM-10.
- **Concurrency in the simulator itself.** No threads, no async, no parallel macrostep speculation. Determinism budget (§6.5) explicitly forbids it.
- **Fuzzing harness.** SOS-03 may build one atop `sos-sim`; SOS-02 does not ship its own.
- **WebAssembly target.** The simulator MAY compile to wasm32 incidentally (no embedded-target-specific code), but SOS-02 does not certify it; INV-S-SIM-4 phrasing covers only the *forbidden* targets, not the *certified* ones. SOS-03 may certify wasm32 if a browser-side trace replay becomes interesting.
- **Backward-compatible trace format across major versions.** A SOS-02 v2 MAY change the field order or rename fields; the SOS-03 suite regenerates against the new format. There is no migration story for old `.jsonl` files.
- **An ECMAScript engine.** `boa`, `quickjs`, `v8`, and `deno_core` are all explicitly out. The bootstrap is hand-compiled scripts; SOS-01 ratifies whether an AST-walking interpreter joins as a sibling provider.
- **Multiple `<script>`-per-transition bodies.** The chart currently has at most one `<script>` per transition. The naming convention reserves `_0`, `_1`, ... but the v1 simulator panics on `_N` for `N >= 1` (forward-reservation enforced at the transpilation step).
- **Vector validation against SOS-01 lint rules.** Pre-SOS-01-ratification, the simulator accepts any well-formed JSON vector. Post-SOS-01, the simulator is expected to lint-check vectors (event names against the frozen list, etc.); that capability ratifies in SOS-01 or a `SOS-02-A` amendment.

## 12. Acceptance checklist (normative)

A conforming SOS-02 ratification (i.e. the §15 dated entry that flips this doc to 🟢) requires:

(a) All six PCDN-SOS-02-NNN open questions in §15 are resolved. Every PCDN has a chosen value, a date, and the corresponding §4 / §5 / §6 / §8 sections updated to reflect the choice.

(b) §3 glossary, §4 source-of-truth map, §5 frozen enums, §6 architecture, §7 trace format, §9 invariants are internally consistent. A reviewer can answer "what does X mean" by reading at most one section. No vocabulary defined in SOS-00 §3 is silently restated here; references use the SOS-00 citation form.

(c) §6.3 script-name table covers every `<script>` block in `rtos_kernel.scxml` at the SHA pinned in §13. A reviewer can `grep '<script>' rtos_kernel.scxml | wc -l` and compare against the table's row count. Helper functions (the chart's top-level `<script>` block contents) are listed in the §6.3 narrative.

(d) §7 (trace format) has been walked field-by-field against SOS-00 §7.2. No field is named here that is absent from SOS-00 §7.2; no field is named in SOS-00 §7.2 that is missing here. The §7.3 example trace records are valid JSON and parse round-trip with `serde_json`.

(e) §9 INV-S-SIM-N invariants are pairwise non-contradictory with SOS-00 §9 INV-S-N invariants. Any INV-S-SIM that *relaxes* a SOS-00 invariant (e.g. INV-S-SIM-4 relaxes INV-S12 for the host-binary form) MUST cite the SOS-00 invariant it relaxes and the scope of the relaxation.

(f) §10 reconciliation list covers every adjacent primitive a reviewer might confuse SOS-02 with. The list is exhaustive at the SOS-02 ratification date; future primitives ratify via §15 amendment to add a row.

(g) §11 non-goal list is exhaustive for the SOS-02 v1 horizon. Items beyond v1 are not constrained here.

A conforming `sos-sim` implementation (i.e. a `cargo build -p sos-sim` that satisfies SOS-02) additionally requires:

(h) The binary `sos-sim --version` prints a version that matches the `Cargo.toml` `version` field and a SHA that matches the chart-pinned SHA in §13.

(i) For every vector in the SOS-03 v1.0 suite (once that ratifies), `sos-sim run --vector V > T.jsonl` produces a `T.jsonl` that is byte-equal to the `expected_trace` half of `V` (after the obvious framing translation from a JSON array of records to a JSONL stream).

(j) `cargo test -p sos-sim` passes on Linux x86_64 and macOS arm64 at the pinned MSRV.

(k) The binary returns exit code 1 on a malformed vector, exit code 2 on an invariant violation (a synthetic vector designed to trigger one is in `tests/fixtures/`), exit code 3 on `--out` pointing at an unwritable path, exit code 4 on `--format cbor`.

## 13. Files cited

| Path | Role | Status |
|---|---|---|
| `streamz/submodules/SOS/rtos_kernel.scxml` | Canonical kernel spec; pinned at the SOS-00-ratification SHA | exists |
| `streamz/submodules/SOS/docs/REFERENCE.md` | Informative chart mirror | exists |
| `streamz/submodules/SOS/docs/concepts/SOS-00-CONCEPTS.md` | Parent concepts doc; §3, §5, §7, §9 are mirror-source for this phase | exists (🟢 ratified 2026-05-19) |
| `streamz/submodules/SOS/docs/concepts/SOS-01-CONCEPTS.md` | Sibling phase; lint + ECMAScript subset (forward-ref) | does not yet exist |
| `streamz/submodules/SOS/docs/concepts/README.md` | Initiative index | exists |
| `streamz/submodules/SOS/AGENTS.md` | Subrepo contributor guidance | exists |
| `streamz/submodules/SOS/CLAUDE.md` | Subrepo agent runbook | exists |
| `streamz/submodules/SOS/docs/concepts/ERRATA.md` | Errata log (skeleton) | exists |
| `streamz/submodules/SOS/sim/sos-sim/` | Simulator crate root (post-ratification) | does not yet exist |
| `streamz/submodules/SOS/sim/sos-sim/Cargo.toml` | Crate manifest (post-ratification) | does not yet exist |
| `streamz/submodules/SOS/sim/sos-sim/src/lib.rs` | Library entry point (post-ratification) | does not yet exist |
| `streamz/submodules/SOS/sim/sos-sim/src/scripts.rs` | Hand-compiled script bodies (post-ratification) | does not yet exist |
| `streamz/submodules/SOS/sim/sos-sim/src/bin/sos-sim.rs` | CLI binary (post-ratification) | does not yet exist |
| `streamz/submodules/SOS/Cargo.toml` | Workspace root (PCDN-SOS-02-005 deciding) | does not yet exist |
| Parent CLAUDE.md, "Spec-Before-Code Planning Discipline" | Governing discipline | exists at parent root |
| W3C SCXML 1.0 Recommendation §3.13 (Macrosteps) | Macrostep semantics SOS-02 implements | external, cited |
| RFC 7464 / JSONL convention | Trace wire format | external, cited |
| RFC 8259 (JSON) | Trace wire format | external, cited |

## 14. Unblocks

SOS-02 ratification unblocks:

- **SOS-03 (conformance vector suite).** With a reference simulator, SOS-03 can generate canonical traces by running `sos-sim` against hand-authored input vectors. The `expected_trace` half of each fixture is `sos-sim`'s output. Without SOS-02, SOS-03 would have to either (a) hand-author traces, which is error-prone, or (b) treat the first-implemented port as canonical, which contaminates the conformance comparison.
- **SOS-04 (M7 Rust port).** With a frozen trace format and a known-good reference implementation, SOS-04 has a concrete target: emit traces in §7's format that byte-equal `sos-sim`'s on every SOS-03 vector. The bench-side instrumentation (probe-rs RTT-stream of trace records, or post-run SRAM dump and host-side trace assembly) ratifies in SOS-04.
- **SOS-05 (M7 C port).** Same as SOS-04, in C. The §7 trace format is language-agnostic.
- **SOS-06 (codegen evaluation).** Codegen output is compared against `sos-sim`. The `TraceReplayScripts` extension point in §6.7 lets the codegen tool inject its own trace into the simulator's framework for diff-against-baseline at the script-body granularity.

SOS-02 does NOT unblock SOS-01 (SOS-01 is sibling, and SOS-01 ratifies first by §15 ordering). If SOS-01 lands after SOS-02 begins implementation, the SOS-01-frozen event-name list MAY require a §15 amendment here to align the `Event` enum's variants.

## 15. Change log

### 2026-05-19 — Initial draft (Ira)

- Document drafted at `docs/concepts/SOS-02-CONCEPTS.md`. Sections §0–§14 populated.
- Frozen enums §5.1 (`TraceFormat`), §5.2 (`EventInjectionMode`), §5.3 (`SimulatorFeature`), §5.4 (`ObservableField`) introduced as proposed-frozen with defaults pending PCDN resolution.
- §6 (architecture) carries the bulk of the doc; §6.3 hand-compiled script ABI lists every `<script>` block in the chart at SOS-00-ratification SHA.
- §7 (trace serialisation) ratifies the JSONL wire format and field order.
- §9 introduces ten INV-S-SIM-N invariants, pairwise checked against SOS-00 §9.
- §10 reconciliation explicitly disclaims dependency on `streamz-exec`, `cortex-m`, FreeRTOS, DAA crates, and any UI / async runtime.

Open PCDN questions:

- **PCDN-SOS-02-001 — Crate name.** **Resolved `sos-sim` 2026-05-19.** Short, unambiguous in context, mirrors the SOS-00 §8 artifact map row.

- **PCDN-SOS-02-002 — Default trace serialisation format.** **Resolved `JsonLines` 2026-05-19.** User noted JsonLines "works well with scjson form or trace and stimulus" — alignment with the scjson family is an additional load-bearing reason beyond the original streaming + diff-ability rationale. `Cbor` / `MessagePack` remain reserved enum names; adding either requires a §15 amendment to this doc, a corresponding wire-format spec, and an update to the SOS-03 harness.

- **PCDN-SOS-02-003 — CLI dependency on `clap`.** **Resolved `clap = "4"` with `derive` feature 2026-05-19.** Small enough, well-known enough, derive gives type-safe definitions. Re-evaluate only if compile time becomes a friction point.

- **PCDN-SOS-02-004 — Rust MSRV.** **Resolved `1.75` 2026-05-19.** Stable late-2023, supports `let-else`, no nightly features required.

- **PCDN-SOS-02-005 — Workspace integration.** **Resolved standalone 2026-05-19** ("clean separation — SOS workspace"). The SOS subrepo gets its own Cargo workspace at the subrepo root (`/Users/iraabbott/softoboros/streamz/submodules/SOS/Cargo.toml`), independent of the parent `softoboros.com` Python workspace and the sibling `disco-analyzer` Cargo workspace. `sim/sos-sim/` is the first workspace member; the future C port (SOS-05) gets a parallel sibling tree, not workspace membership.

- **PCDN-SOS-02-006 — Vector input mode at v1.** **Resolved `PreLoaded` 2026-05-19.** `Streaming` is reserved; revisit when an interactive use case appears.

- **PCDN-SOS-02-007 — Feature gating.** **Resolved NO 2026-05-19.** No `[features]` block in `sos-sim`'s `Cargo.toml` at v1; the `clap` dependency is small enough that the build-matrix complexity of feature-gating exceeds the gain. Revisit only if a downstream consumer's build budget pinches.

Acceptance checklist (§12) status at draft:

- (a) ⏸ Pending PCDN resolution.
- (b) ✅ Glossary, source-of-truth map, frozen enums, architecture, trace format, invariants internally consistent.
- (c) ✅ §6.3 script-name table covers every `<script>` in the chart at the SOS-00-ratification SHA (20 transition-bodied scripts + 1 boot onentry script + the helpers block).
- (d) ✅ §7 walked against SOS-00 §7.2; field set matches.
- (e) ✅ INV-S-SIM-N invariants checked pairwise against SOS-00 §9 invariants. INV-S-SIM-4 explicitly cites the relaxation of INV-S12 it imposes (host-only allocator permission).
- (f) ✅ §10 reconciliation covers Tokio, cortex-m, FreeRTOS, DAA, rlvgl, async runtimes, sibling SOS phases.
- (g) ✅ Non-goal list bounded to v1 horizon.

Status: 🟡 drafted; awaiting user PCDN walk-through and ratification before SOS-03 begins.

### 2026-05-19 — Ratification (Ira)

User walked the PCDN list and ratified every open question. SOS-02 status moves from 🟡 drafted to **🟢 ratified**. SOS-03 (conformance vector suite) is unblocked; the SOS-02 implementation commit (Cargo workspace + `sos-sim` crate) lands as a follow-up.

Consolidated resolutions:

- **PCDN-SOS-02-001:** `sos-sim`.
- **PCDN-SOS-02-002:** `JsonLines` default. The user-added rationale ("works well with scjson form or trace and stimulus") aligns SOS's trace wire format with the wider scjson family, reinforcing the choice beyond the originally-cited streaming + diff-ability properties.
- **PCDN-SOS-02-003:** `clap = "4"` with `derive` feature.
- **PCDN-SOS-02-004:** Rust MSRV `1.75`.
- **PCDN-SOS-02-005:** Standalone Cargo workspace at the SOS subrepo root.
- **PCDN-SOS-02-006:** `PreLoaded` vector input only at v1.
- **PCDN-SOS-02-007:** No feature gates at v1.

Acceptance checklist (§12) compliance at ratification:

- (a) ✅ All seven PCDNs resolved.
- (b)–(k) ⏸ Implementation-commit gates by design — they ratify when the follow-up implementation commit lands the Cargo workspace + `sos-sim` crate skeleton + types + trait + (eventually) the hand-compiled scripts module. Ratification of *this concepts doc* completes at (a); the implementation gates ride downstream.

Unblocks: SOS-03 (conformance vectors). The SOS-02 implementation commit is independently and immediately dispatchable in parallel with SOS-03 drafting (file-disjoint: SOS-02 implementation writes `Cargo.toml`, `sim/sos-sim/**`, `rust-toolchain.toml`; SOS-03 drafting writes only `docs/concepts/SOS-03-CONCEPTS.md`).

### 2026-05-19 — Amendment 001: document wire-width policy in §7.2 (Ira)

The `sos-sim` deserialisation-layer implementation (landed 2026-05-19) surfaced a width drift: SOS-00 §3 declares `TaskId = i16` (a tight type bounded by `MAX_TASKS=8`), but §7.2's original wording said "number (signed)" without naming a width — and the `TraceRecord.current` field in `sim/sos-sim/src/trace.rs` was implemented as `i32`. The implementation widens `i16 → i32` losslessly during snapshot construction.

**Resolved: the wire widening is intentional, and §7.2 now documents both columns explicitly** (in-memory type vs. wire form). Rationale:

1. **Forward-compat.** If a future amendment widens `TaskId` (e.g. to `i32` to support `MAX_TASKS > 32767`), the wire format does not break.
2. **Recipient-side simplicity.** A port's trace consumer (SOS-03 harness, or a future cross-port diff tool) decodes JSON integers into the widest reasonable container without per-field width tracking; downcasts happen at the recipient's convenience.
3. **No precision loss.** All widenings are signed-to-signed or unsigned-to-signed-with-non-negative range; values round-trip byte-identical.

§7.2 amended to add an "In-memory type" column citing the SOS-00-declared Rust types, plus a "Wire form" column documenting which fields widen. No implementation rework needed — the as-built `TraceRecord` fields already use the wire types.

If a future amendment decides to narrow the wire to match in-memory exactly (a defensible alternative — strict-equality types are easier to reason about), it ratifies as Amendment 002 with the coordinated `TraceRecord` field-type changes.

### 2026-05-19 — Amendment 002: document SemSnapshot / QueueSnapshot serde-untagged anti-pattern (Ira)

The wave-6.5 fix to `sim/sos-sim/src/datamodel.rs` (custom Serialize for `Msg`, superseding the previous `#[serde(untagged)]` derive that silently collapsed `Msg::ReturnCode(Ok)` to bare `0`) surfaced that the SOS-02 §7.2 "short-form for invalid sem/queue" wire-form contract is also implemented via `#[serde(untagged)]` on `SemSnapshot` and `QueueSnapshot` in `sim/sos-sim/src/trace.rs`. The two snapshot enums are SAFE today — their `Valid { valid: true, count, max, waiters }` and `Invalid { valid: false }` variants are structurally distinguishable (the `Valid` form always has `count`/`max`/`waiters` keys; the `Invalid` form has only `valid: false`). Serde's untagged-deserialiser correctly distinguishes them on parse, and the serialiser emits the right shape on encode.

However: **the same anti-pattern** that caused the Msg bug applies here. Any future amendment that adds a new `SemSnapshot` or `QueueSnapshot` variant must verify the new variant is structurally distinct from the existing ones — otherwise serde's "try each variant in declaration order" untagged dispatch will silently mis-encode. The Msg bug was load-bearing-and-undetected for several waves; the snapshot enums could harbor the same class of bug.

§7 amended (informative): per-snapshot-enum serialisation MUST preserve structural distinguishability of variants. The current `Valid`/`Invalid` two-variant shape is the **canonical** form; future amendments adding a third or fourth variant SHOULD prefer a custom Serialize impl (mirroring the Msg fix) over extending the `#[serde(untagged)]` derive. The cost of the custom impl is ~30 LOC per enum; the cost of an undetected wire-form collapse is a class of conformance-test false-negatives that may not surface until a port emits a real trace and `sos-conformance` is wired against it (which is exactly when the Msg bug surfaced).

No code change is required by this amendment — `SemSnapshot` and `QueueSnapshot` continue to work correctly under the current variant set. The note is forward-looking guidance for future amendments touching these enums.

Cross-reference: SOS-00 §15 Amendment 003 (Msg wire form ratification) + Amendment 004 (Msg on-wire discriminator clarification); SOS-02 wave-6.5 Msg fix at `sim/sos-sim/src/datamodel.rs`.
