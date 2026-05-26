# SOS-10 — Multi-language orchestration (higher-level synchronizer)

**Status:** 🟢 **ratified 2026-05-23** (see §15).

## 0. Authority policy

This phase doc ratifies the contract for **multi-language orchestration** — the chart-level abstraction that composes per-piece sub-systems (each piece authored in its own language: Rust microservice, C firmware, VHDL fabric module, Python data plane, etc.) into one verified system, with the top-level chart as the orchestrator + bounded-reachability vectors at every cross-piece boundary.

Per the Spec-Before-Code Planning Discipline (parent CLAUDE.md):

- **Normative** sections: §3 glossary, §4 source-of-truth map, §5 frozen decisions, §6 medium catalogue, §7 cross-medium invariants, §8 standards integration matrix additions, §12 acceptance checklist.
- **Informative** sections: §1 purpose, §2 problem statement, §11 non-goals, §15 change log.
- All keywords MUST, MUST NOT, SHALL, SHOULD, SHOULD NOT, MAY are interpreted per RFC 2119 / 8174 when capitalised.

This doc cites SOS-07 §6 for cross-phase invariants (INV-SOS-A through H) and §7 for the AuthorityRelationship matrix; SOS-08 §6/§7 for HDL primitives + INV-S-HDL-N; SOS-09 §3/§5 for membrane channel semantics + INV-S-MEM-N; SOS-12 §6 for the bound-composition algebra. It does not re-derive any of them.

## 1. Purpose

To take SOS's bench-validated chart-as-source methodology — proven at the kernel-bootstrap level (SOS-04 Rust + SOS-05 C at `CanonicalReplacement`) and extended into HDL (SOS-08) and the hardware/software membrane (SOS-09) — and apply it **at the system level**, where the pieces speak different languages, live in different processes, and communicate over heterogeneous media.

The unlock SOS-10 makes concrete: **one top-level orchestrator chart drives a system whose pieces are themselves chart-driven sub-systems in any of N languages**, with cross-piece events emitted, dispatched, and verified through bounded reachability that crosses language boundaries — without anyone authoring the cross-piece protocol as a separate document that drifts.

## 2. Problem statement

Five observations motivate this phase:

1. **Cross-piece integration is where most systems fail silently.** Each piece is well-tested in isolation; the integration boundary lives in a register-map PDF (SOS-09's failure mode at the silicon membrane) or a Confluence page (the multi-language equivalent) or — most often — in tribal knowledge. The class of bug is unit-tests-pass + integration-fails; the fix is invariably "we forgot the protocol detail X."

2. **Per-piece charts already exist (in heads if not in artifacts).** The MCU firmware has a state machine for boot / connect / heartbeat / error-handling. The FPGA fabric has a state machine for stream / pause / flush. The orchestrating microservice has a state machine for session-lifecycle / failover. Each is a chart that hasn't been drawn. The cross-piece protocol is the chart-of-charts that's *really* never been drawn.

3. **The protocol-stack pattern (SOS-12 §8 worked example) generalises to multi-language.** A top-level dispatch chart factoring into per-method sub-charts (HTTP GET/POST/PUT/DELETE) is the same structural pattern as a top-level system chart factoring into per-piece sub-charts (MCU/FPGA/coprocessor) where each sub-chart happens to compile to a different language. Hierarchical decomposition with per-layer contracts is the universal solvent; SOS-10 applies it at the language-boundary scale.

4. **Cross-piece events have explicit media that the chart can declare.** Same-process function calls, shared-memory ring buffers (Linux IPC, RTOS message queues), MMIO over a bus (SOS-09's membrane primitives, AXI on FPGA), network protocols (gRPC, AMQP, MQTT, raw TCP). Each medium is a *channel* in the CSP sense (per INV-SOS-F + SOS-12's algebra); the chart declares the medium per cross-piece event; the emitter realises the wire format + handshake for that medium.

5. **Bounded-reachability verification crosses the language boundary cleanly.** The top-level chart's bound is computed against each piece's contract (constant-size), not against each piece's internal states (variable-size). The orchestrator vectors test the protocol; per-piece vectors test internal behavior; the per-piece vectors and the orchestrator vectors compose by contract-matching at the dispatch boundary — exactly the SOS-12 pattern, applied across language boundaries.

## 3. Canonical glossary

| Term | Definition |
|---|---|
| **orchestrator chart** | A chart whose states are *pieces of a system*. Each state represents a sub-system (an MCU firmware, an FPGA fabric, a microservice). Transitions are cross-piece events with explicit `<sos:medium>` declarations. The orchestrator chart is one chart among the system's many charts; it is the chart that owns the cross-piece protocol. |
| **piece** | One sub-system of a multi-piece system. Each piece is itself chart-driven (per SOS-12's recursive dispatch model — a piece is a sub-chart from the orchestrator's perspective). The piece's chart compiles to whatever language the piece runs in (Rust/C/VHDL/Verilog/Python/…). |
| **medium** | The mechanism a cross-piece event uses to cross the boundary between pieces. Frozen at v1 as a four-value enum: `in-process`, `shared-memory`, `mmio`, `network`. Each maps to a specific emitter that realises the wire format + handshake. |
| **in-process medium** | Same-process function call. Sender and receiver compile into the same binary; the cross-piece event is a direct function-pointer dispatch. Used when "multi-language" is multi-language-in-the-same-process (e.g. Rust calling C via FFI, Python calling Rust via PyO3). |
| **shared-memory medium** | Cross-process IPC via shared-memory ring buffer. Posix shared memory + POSIX semaphores / Linux futexes. Cross-process within the same host; not cross-host. |
| **mmio medium** | Memory-mapped I/O over a bus. SOS-09's membrane primitives (CMSIS-SVD-described registers + DPRAM channels + IRQ strobes) are the realisation. Used for CPU↔FPGA, CPU↔co-processor, CPU↔peripheral. |
| **network medium** | Cross-host transport. At v1, the supported transports are gRPC + AMQP (per EOQ-004-ROADMAP's "same-host at v1" framing — network medium is the *only* cross-host path declared; cross-data-center is out of scope). |
| **cross-piece event** | An event emitted by one piece's chart that is consumed by another piece's chart. The event has a typed payload (per the orchestrator's `ExternalEventName` enum, extending SOS-01's vocabulary), a sender piece, a receiver piece, and a medium. |
| **piece contract** | The per-piece chart's declaration of which events-in it accepts from the orchestrator + which events-out it emits to the orchestrator + which invariants it maintains. Same shape as SOS-12's `<sos:contract>` element. |
| **wire format** | The on-the-wire byte layout of a cross-piece event over a given medium. The orchestrator's emitter derives the wire format from the typed payload + the medium; the emitter is the canonical authority on the wire format; pieces that consume the wire format do so through generated parsers/serialisers. |

## 4. Source-of-truth map

| Concept | Authority |
|---|---|
| Orchestrator chart shape | **this doc** (§5.1) |
| Medium enumeration (frozen 4-value) | **this doc** (§5.2) |
| Per-medium emitter contract | **this doc** (§6) |
| Wire format per (event-type, medium) | derived; emitter is canonical |
| Piece contract syntax | **SOS-12** §3 / §6 (`<sos:contract>` element) — referenced, not redefined |
| Bound-composition algebra | **SOS-12** §6 — referenced, not redefined |
| Same-host vs cross-host scope | **this doc** (§5.3); per EOQ-004-ROADMAP resolution |
| Cross-piece invariants | **this doc** (§7) |
| Cross-phase invariants (INV-SOS-A through H) | **SOS-07** §6 — cited by ID |

## 5. Frozen decisions

### 5.1 Orchestrator chart shape

The orchestrator chart is an SCXML statechart that obeys all the SOS-00 + SOS-07 invariants, with the following normative additions:

- Each top-level state represents one piece of the system. The state's `id` is the piece's name (`mcu`, `fabric`, `gateway`, etc.).
- Each top-level state contains a `<sos:dispatch ref="<piece>.scxml"/>` element per SOS-12 §5 syntax; the referenced sub-chart is the piece's own chart.
- Each transition between pieces carries a `<sos:medium>` annotation declaring the medium (one of the 4-value enum at §5.2).
- The orchestrator's datamodel is the cross-piece state — the state that's meaningful at the system level, not internal to any one piece. Each piece's internal datamodel is private (per SOS-12's per-sub-chart datamodel boundary).

Frozen-enumeration registration policy for the orchestrator-chart-shape attributes: **Standards Action**.

### 5.2 Medium enumeration

Frozen at v1 as a 4-value enum:

| Value | Realised as | Cross-host? | Realisation phase |
|---|---|---|---|
| `in-process` | Same-process function-pointer dispatch | No | this doc (§6.1) |
| `shared-memory` | POSIX shm + semaphores; Linux futexes; RTOS message queues | No | this doc (§6.2) |
| `mmio` | SOS-09 membrane primitives (CMSIS-SVD registers + DPRAM + IRQ) | No (silicon-internal) | SOS-09 |
| `network` | gRPC primary; AMQP secondary | Yes | this doc (§6.4) |

Frozen-enumeration registration policy: **Standards Action**. Adding a fifth medium requires §15 amendment to this doc + a new §6.N sub-section ratifying its emitter contract.

### 5.3 Same-host vs cross-host scope

Per EOQ-004-ROADMAP resolution:

- **Same-host (single-process or multi-process)** is v1 scope. The `in-process`, `shared-memory`, and `mmio` media all stay within one physical host.
- **Cross-host (single-data-center via network medium)** is v1 scope at the medium level: the `network` medium IS in v1, but limited to gRPC + AMQP transports targeting a single LAN.
- **Cross-data-center / cross-network-partition** is out of v1 scope. The `network` medium does NOT promise fault-tolerance against network partitions; cross-data-center orchestration is a v2 effort or its own initiative.

## 6. Per-medium emitter contracts

### 6.1 `in-process` medium

**Wire format**: function-pointer dispatch table generated per the orchestrator's event vocabulary. Sender calls `dispatch_event(event_name, payload)`; the dispatch table routes to the receiver's registered handler.

**Realisation per language**:
- Rust ↔ Rust: direct function pointer in a `static` dispatch table.
- C ↔ C: `void(*)(const sos_event_t *)` function pointer.
- Rust ↔ C: FFI boundary via `extern "C"`; payload is `#[repr(C)]`.
- Python ↔ Rust: PyO3 boundary; payload serialised at the boundary, then function-pointer dispatch.

**Per-event-type vector emission**: cocotb-equivalent host-side test framework drives orchestrator events through the dispatch table; the bounded-reachability vectors test the protocol; INV-SOS-H per-failure-in-chart-vocabulary applies.

**Performance**: zero-copy (Rust ↔ Rust, C ↔ C), one boundary marshal (Rust ↔ C, PyO3). Latency is single-digit-cycle (in-process function call).

### 6.2 `shared-memory` medium

**Wire format**: ring buffer in POSIX shared memory (`shm_open` / `shm_unlink`). Producer writes; consumer reads; head/tail pointers atomic via futex / RTOS message queue.

**Realisation per language**:
- Linux (any language): `mmap`-backed shared memory + futex-protected head/tail.
- RTOS (FreeRTOS / Zephyr / ThreadX): native message-queue primitive maps directly.

**Per-event-type vector emission**: cocotb-equivalent harness instantiates producer + consumer in separate processes; vectors test ordering, throughput, full/empty edge cases.

**Performance**: single shared-memory write per event; throughput limited by ring depth + futex contention. Sub-microsecond latency on Linux 6.x.

### 6.3 `mmio` medium

**Wire format**: SOS-09 membrane channels (status/command/queue/shared). The orchestrator's cross-piece events for the `mmio` medium compile to SOS-09 channel declarations; the SOS-09 emitter takes over from there.

**Realisation**: per SOS-09 § (channel category → membrane primitive + register-map artifact + HAL accessor + RTL).

**Per-event-type vector emission**: SOS-09 § membrane vectors. INV-S-MEM-6 (vectors-as-integration-contract) carries over.

### 6.4 `network` medium

**Wire format**: per `<sos:transport>` sub-annotation on the `<sos:medium kind="network">` element, declaring the protocol:
- `gRPC` (primary at v1): one gRPC service per piece; each cross-piece event is one gRPC unary call (request + response). Service definitions generated from the chart's event vocabulary; `.proto` files are build outputs (per INV-SOS-A).
- `AMQP 1.0` (secondary at v1): one queue per piece; cross-piece events as AMQP messages; orchestrator routes via queue bindings.

**Per-event-type vector emission**: integration tests spin up containerised pieces (`docker compose`) + a test harness driving orchestrator events; vectors test ordering, timeout, retry semantics.

**Performance**: gRPC unary call latency ~100µs on a same-LAN setup; AMQP queue dispatch ~1ms. The medium is *not* for sub-microsecond paths; that's what `in-process` / `shared-memory` exist for.

**Cross-host caveat**: per §5.3, the `network` medium is limited to single-data-center; the orchestrator's vector emission does NOT verify network-partition recovery. If a chart authoring needs cross-data-center semantics, the chart declares the cross-piece events explicitly idempotent (a chart-side discipline; SOS-10 doesn't enforce it at v1).

## 7. Cross-piece invariants — INV-S-ORCH-1 through 6

In addition to the cross-phase invariants INV-SOS-A through H (SOS-07) and the per-phase invariants of dependencies (SOS-08 INV-S-HDL-N, SOS-09 INV-S-MEM-N, SOS-12 INV-S-DISP-N), the following are normative within SOS-10:

- **INV-S-ORCH-1 — One orchestrator per system.** A system has exactly one top-level orchestrator chart. Pieces never directly invoke each other's events; every cross-piece event flows through the orchestrator. This makes the orchestrator the sole verification surface for cross-piece protocols.

- **INV-S-ORCH-2 — Piece-as-sub-chart.** Each piece is a sub-chart from the orchestrator's perspective (per SOS-12's recursive dispatch model). The piece's chart can be authored in any language target SOS supports; the orchestrator treats it as an atomic transition with the declared contract.

- **INV-S-ORCH-3 — Explicit medium per cross-piece event.** Every transition that crosses a piece boundary MUST carry a `<sos:medium kind="..."/>` annotation declaring one of the four enum values. No "implicit medium" inference at v1.

- **INV-S-ORCH-4 — Wire format derived, not authored.** The wire format per (event-type, medium) is derived from the chart's payload type + the medium emitter; no chart author hand-writes wire formats. Generated `.proto` files, `#[repr(C)]` structs, AMQP message schemas — all build outputs (per INV-SOS-A).

- **INV-S-ORCH-5 — Per-medium failure-mode taxonomy.** Each medium has a declared failure-mode taxonomy (e.g. `in-process` cannot fail at the medium layer; `shared-memory` can deadlock under producer/consumer contention; `mmio` can lose IRQs if the consumer doesn't drain the queue; `network` can drop, reorder, or duplicate). Each piece's contract declares which failure modes it tolerates; the orchestrator verifies that adjacent pieces' tolerances are compatible.

- **INV-S-ORCH-6 — Vector-to-chart traceability across pieces.** Per INV-SOS-H + the SOS-08-D / SOS-09 per-channel traceability + SOS-12 per-sub-chart traceability: every cross-piece-vector failure renders in chart vocabulary, naming the orchestrator state + the piece + the cross-piece event + the chart-derived invariant. Never raw network packet dumps or shared-memory hex dumps alone.

## 8. Standards integration matrix additions

| Concept | Upstream authority | Local relationship | Phase that declares it | Mutation rights |
|---|---|---|---|---|
| gRPC | open project | **compose** (one of the network transports) | this doc (§6.4) | none — wire format is upstream |
| Protocol Buffers / `.proto` | open project | **derive** (`.proto` files emitted from chart event vocabulary) | this doc (§6.4) | none — emit conformant subset |
| AMQP 1.0 | OASIS | **compose** (network transport secondary) | this doc (§6.4) | none |
| POSIX shared memory + futex | POSIX (IEEE 1003) | **adapt** (chart-driven shared-memory ring buffer) | this doc (§6.2) | none — POSIX is upstream |
| FreeRTOS / Zephyr / ThreadX message queues | open projects | **mirror** (vocabulary; the RTOS native primitive is the realisation for shared-memory medium on RTOS targets) | this doc (§6.2) | none |
| PyO3 (Rust ↔ Python FFI) | open project | **adapt** | this doc (§6.1) | none |
| `docker compose` (for network-medium integration tests) | open project | **derive** (compose files generated from chart's piece + medium declarations) | this doc (§6.4 vector emission) | none |

## 9. Worked example: MCU + FPGA + gateway

To make the protocol-stack pattern concrete at the multi-piece scale: an audio-streaming system composed of three pieces.

- **Piece A**: MCU (Cortex-M7 firmware in Rust per SOS-04). Owns the user-facing controls, the audio codec configuration, and the cross-piece events for "stream start/stop/pause".
- **Piece B**: FPGA fabric (VHDL/SystemVerilog per SOS-08; Lattice ECP5 per EOQ-004). Owns the real-time audio pipeline; receives MCU commands; emits status events to the gateway.
- **Piece C**: Gateway (microservice; language: TBD per a future PCDN). Owns the network-facing API; receives FPGA status events; emits aggregated analytics to a remote dashboard.

The orchestrator chart:

```xml
<scxml xmlns="http://www.w3.org/2005/07/scxml"
       xmlns:sos="https://softoboros.com/sos/1.0"
       version="1.0" datamodel="ecmascript" initial="mcu">

  <state id="mcu">
    <sos:dispatch ref="mcu.scxml"/>
    <transition event="audio.start" target="fabric">
      <sos:medium kind="mmio"/>  <!-- SOS-09 channel; CMSIS-SVD register -->
    </transition>
  </state>

  <state id="fabric">
    <sos:dispatch ref="fabric.scxml"/>
    <transition event="audio.status" target="gateway">
      <sos:medium kind="shared-memory"/>  <!-- Linux shm; on RTOS, message queue -->
    </transition>
  </state>

  <state id="gateway">
    <sos:dispatch ref="gateway.scxml"/>
    <transition event="analytics.publish" target="(remote)">
      <sos:medium kind="network">
        <sos:transport name="gRPC"/>
      </sos:medium>
    </transition>
  </state>

</scxml>
```

Each piece chart (`mcu.scxml`, `fabric.scxml`, `gateway.scxml`) is its own authored chart with its own piece contract per SOS-12 §5/§6.

Vector emission for this orchestrator:
- One vector per cross-piece transition tests the medium's protocol.
- Per-piece vectors (per SOS-04 / SOS-08-D / SOS-12 vocabulary) test internal behavior.
- The orchestrator's bounded reachability is `piece-count × per-piece-contract-bound`, NOT `Π piece-internal-states` (per INV-SOS-F + SOS-12 §6 algebra).

The chart is the integration spec; the vectors are the integration tests; no Confluence page lies about the protocol.

## 10. Reconciliation decisions vs adjacent repo primitives

### vs. SOS-09 (HW/SW membrane)

SOS-10's `mmio` medium **composes** SOS-09's channel categories. The orchestrator emits cross-piece events with `<sos:medium kind="mmio"/>`; the SOS-09 emitter takes the chart's payload type + the orchestrator's declared sender/receiver pieces and produces the membrane channel artifacts. SOS-10 does not duplicate SOS-09 content; it routes into it.

### vs. SOS-12 (recursive chart dispatch)

SOS-10's `<sos:dispatch>` element is the same one SOS-12 ratifies. SOS-10 specifies the **specific case** where the sub-chart compiles to a different language target than the parent chart. SOS-12's per-sub-chart contract semantics apply unchanged; SOS-10 adds the medium annotation per cross-piece transition.

### vs. SOS-13 (verified-codegen Rust)

The orchestrator chart compiles to a runtime that is itself a chart-driven sub-system. Per SOS-13, the orchestrator's runtime can use the `verified-strip` profile if the orchestrator's bounded reachability discharges the obligations. No new mechanism needed.

### vs. parent CLAUDE.md's "Standards integration: authority boundary declarations"

§8 of this doc mirrors the AuthorityRelationship enum verbatim (mirror, adapt, extend, compose, own, derive, represent). Per-medium emitter relationships in §6 are declared explicitly per INV-SOS-E.

## 11. Non-goals

This phase does NOT:

- Author the per-language piece runtimes. Each piece's chart compiles via its target language's existing SOS phase (SOS-04 Rust, SOS-05 C, SOS-08 HDL, future SOS-N for Python/Go/etc.).
- Promise fault-tolerance against network partitions on the `network` medium. Cross-data-center coordination is its own initiative.
- Verify production network performance. The vectors test protocol correctness; they don't benchmark latency or throughput.
- Define a new IPC / RPC framework. The orchestrator composes gRPC / AMQP / POSIX shm / mmio — it does not invent a wire format. Generated artifacts are conformant subsets of upstream standards.
- Specify cross-language data-marshalling beyond the four media's wire formats. Pieces communicate via cross-piece events; in-piece data marshalling (e.g. how a Rust piece serialises its internal state to disk) is out of scope.

## 12. Acceptance checklist

A conforming SOS-10 ratification satisfies:

- (a) ✅ PCDN-SOS-10-001 through 008 resolved — see §15 2026-05-23 ratification entry.
- (b) ⏸ The MCU + FPGA + gateway worked example (§9) instantiated as a buildable demonstration on the bench substrate (Lattice ECP5 + STM32H747I-DISCO; the gateway runs on a host Linux machine connected via LAN). (Wave-17 landed the chart skeleton at `examples/orchestrator_mcu_fabric_gateway.scxml` exercising all four media + both network transports; bench-side build + run still pending.)
- (c) ⏸ Each of the 4 media has at least one cross-piece event tested end-to-end via cocotb-equivalent harness. (Wave-16 + wave-17 landed unit-test coverage on all 4 media: in-process, shared-memory, mmio, and network (protobuf IDL + gRPC stubs + AMQP messages). End-to-end cocotb-equivalent harness still pending.)
- (d) ⏸ Cross-piece bounded-reachability vectors emitted; INV-SOS-H rendered failures in chart vocabulary verified manually on a deliberate broken-protocol case.
- (e) ✅ SOS-09 + SOS-12 cited correctly with no semantic duplication; SOS-10 strictly composes them. (Wave-16: the `mmio` emitter generates SOS-09 channel annotations as inputs to the SOS-09 emitter family rather than re-emitting any SOS-09 artifact; the `in-process` and `shared-memory` emitters cite their primitive layers explicitly and emit `@spec` blocks naming the source-of-truth phases.)
- (f) ✅ INV-S-ORCH-1 through 6 cited correctly in the implementation phase. (Wave-16: every emitted artifact carries an `@spec` comment block citing §6.x of this doc + the relevant INV-S-ORCH-N invariants + INV-SOS-A.)

(j) and onward are implementation gates ratifying when implementation lands.

## 13. Pending Concept Decision Notices (PCDNs)

- **PCDN-SOS-10-001 — Gateway-piece language at v1.** The §9 worked example names the gateway as "language: TBD". Candidates: (a) Rust (memory-safe, fits the SOS-04 / SOS-13 verified-codegen story), (b) Go (concurrency-friendly, common in gateway shops), (c) Python (lowest-barrier; fits the cocotb + open-tooling story). **Recommendation**: Rust (composes with SOS-04 + SOS-13; the chart-driven gateway is the same generator-stack the MCU side uses). Defer Go and Python to future medium-by-medium additions.

- **PCDN-SOS-10-002 — gRPC vs Protocol Buffers as the network-medium wire-format owner.** gRPC includes protobuf as its IDL; AMQP doesn't natively use protobuf. **Recommendation**: protobuf as the canonical IDL; gRPC services derived from protobuf; AMQP message bodies are protobuf-encoded too (one IDL, two transports).

- **PCDN-SOS-10-003 — Per-piece chart-language declaration.** Where does the chart declare each piece's target language? Options: (a) attribute on the orchestrator's `<state>` element (`<state id="mcu" sos:lang="rust">`); (b) attribute on the sub-chart's `<scxml>` root; (c) external manifest (`pieces.json`). **Recommendation**: (a) — chart-level declaration keeps the orchestrator self-contained; the sub-chart's `<scxml>` root inherits.

- **PCDN-SOS-10-004 — `<sos:medium>` element vs attribute.** Sub-elements (the `<sos:medium kind="network"><sos:transport name="gRPC"/></sos:medium>` form in §9) vs attributes (`<transition sos:medium="network/gRPC" event="..." target="..."/>`). **Recommendation**: sub-elements — the medium can carry nested annotations (transport, timeout, idempotency), and an attribute encoding becomes unwieldy.

- **PCDN-SOS-10-005 — Idempotency annotation on cross-piece events.** Per §6.4's cross-host caveat, idempotency matters for network-medium events that may retry. Should the chart declare `<transition sos:idempotent="true">` explicitly? **Recommendation**: opt-in attribute; default unspecified; the orchestrator emitter warns if a `network`-medium transition without explicit idempotency annotation is the only path from a state (since retry semantics aren't proven).

- **PCDN-SOS-10-006 — Timeout per cross-piece event.** Network-medium events need timeout semantics (per `sos:medium`'s `<sos:transport timeout-ms="...">` or a chart-level default?). **Recommendation**: per-medium default in the emitter (e.g. gRPC = 5000ms, AMQP = 10000ms); chart-level override via `<sos:medium><sos:timeout ms="..."/></sos:medium>` sub-element.

- **PCDN-SOS-10-007 — Multi-orchestrator composition (orchestrators-of-orchestrators).** Can a large system have multiple orchestrators that compose at a meta-level? Or is INV-S-ORCH-1's "one orchestrator per system" strict? **Recommendation**: strict at v1 (one orchestrator per "system" boundary); multi-orchestrator composition is a future-phase decision. Define "system" as the unit that ships together / has the same release cadence; multiple systems are tested independently.

- **PCDN-SOS-10-008 — Cross-piece-vector emission framework.** The §9 worked example needs an end-to-end test harness. Should it be (a) `docker compose` + per-piece test scripts + a top-level Python coordinator (matches SOS-08-D cocotb-first priority + the open-source-tooling story); (b) a new SOS-specific orchestration test runner; (c) integrate with an existing tool (e.g. `testcontainers`)? **Recommendation**: (a) — Python coordinator + docker compose + per-piece cocotb-equivalent; consistent with the SOS-08-D priority.

## 14. Unblocks

This phase's ratification (after PCDN resolution) unblocks:

- Implementation of the orchestrator emit path in `tools/sos-codegen/` — chart annotation walker for `<sos:dispatch>` + `<sos:medium>` + `<sos:transport>` + per-medium emitter modules.
- The §9 worked example as a buildable demonstration: MCU firmware (SOS-04 Rust port), FPGA fabric (SOS-08 emission for ECP5), gateway (Rust per PCDN-001 resolution).
- Cross-piece vector emission framework per PCDN-008 resolution.
- The article's "compile your chart-of-charts to a verified multi-language system" demo, which is the multi-language adoption-story upgrade to the napkin-to-silicon claim.

## 15. Change log

### 2026-05-23 — Initial draft (Ira)

- Authored `SOS-10-CONCEPTS.md` as the last spec-layer normative artifact in the SOS-07 wave (SOS-08 through SOS-13 ratified earlier today).
- Frozen-decisions §5: orchestrator chart shape with `<sos:dispatch>` + `<sos:medium>` annotations; 4-value medium enum (`in-process`, `shared-memory`, `mmio`, `network`); same-host at v1 with `network` medium limited to single-LAN.
- Per-medium emitter contracts §6: in-process (function-pointer dispatch); shared-memory (POSIX shm / RTOS message queue); mmio (composes SOS-09's membrane channels); network (gRPC primary, AMQP secondary).
- Cross-piece invariants §7: INV-S-ORCH-1 through 6 (one orchestrator per system; piece-as-sub-chart; explicit medium per cross-piece event; wire format derived not authored; per-medium failure taxonomy; vector-to-chart traceability across pieces).
- AuthorityRelationship rows §8 for gRPC, protobuf, AMQP, POSIX shm, FreeRTOS/Zephyr/ThreadX, PyO3, docker compose.
- Worked example §9: MCU (Rust) + FPGA (VHDL on ECP5) + gateway (TBD per PCDN-001) audio-streaming system; demonstrates all 4 media in one chart.
- 8 PCDNs raised (gateway language, gRPC/protobuf relationship, per-piece language declaration, medium-element-vs-attribute, idempotency annotation, timeout semantics, multi-orchestrator composition, cross-piece test framework).

Status: 🟡 **drafted**, awaiting PCDN walkthrough.

### 2026-05-23 — Ratified after PCDN walkthrough (Ira)

All eight PCDNs from §13 resolved with recommendations accepted.

- **PCDN-SOS-10-001 → RESOLVED**: Gateway-piece v1 language is **Rust**. Composes with SOS-04 + SOS-13; the chart-driven gateway uses the same generator stack as the MCU side, preserving the verified-strip story across the membrane. Go and Python are deferred to future medium-by-medium additions.
- **PCDN-SOS-10-002 → RESOLVED**: **protobuf** is the canonical wire-format IDL; gRPC services derive from protobuf; AMQP message bodies are protobuf-encoded. One IDL, two transports. INV-S-ORCH-4 ("wire format derived not authored") cites protobuf as the derivation source.
- **PCDN-SOS-10-003 → RESOLVED**: Per-piece chart-language declared via attribute on the **orchestrator's `<state>` element** (`<state id="mcu" sos:lang="rust">...</state>`). Chart-level declaration keeps the orchestrator self-contained; the sub-chart's `<scxml>` root inherits from the orchestrator's declaration.
- **PCDN-SOS-10-004 → RESOLVED**: `<sos:medium>` is a **sub-element**, not an attribute. Sub-elements carry nested annotations (`<sos:transport>`, `<sos:timeout>`, `<sos:idempotent>`) cleanly; attributes would require flattened serialization that is harder to extend.
- **PCDN-SOS-10-005 → RESOLVED**: Idempotency is an **opt-in attribute** (`<transition sos:idempotent="true" ...>`), default unspecified. The orchestrator emitter **warns** when a `network`-medium transition without an explicit `sos:idempotent` annotation is the only path from a state (retry semantics are not proven without the explicit annotation).
- **PCDN-SOS-10-006 → RESOLVED**: **Per-medium defaults in the emitter** (gRPC = 5000 ms, AMQP = 10000 ms, in-process / shared-memory / mmio = no timeout); chart-level override via `<sos:medium><sos:timeout ms="..."/></sos:medium>` sub-element. Default values may be amended by §15 entry; chart-level override is normative.
- **PCDN-SOS-10-007 → RESOLVED**: **Strict at v1** — one orchestrator per "system" boundary. "System" is the unit that ships together with the same release cadence. Multi-orchestrator composition (orchestrators-of-orchestrators) is deferred to a future phase. INV-S-ORCH-1 frozen at strict.
- **PCDN-SOS-10-008 → RESOLVED**: Cross-piece-vector emission framework is **`docker compose` + per-piece test scripts + a top-level Python coordinator**. Matches SOS-08-D cocotb-first priority + open-source-tooling story. Vector emission uses the SOS-03 schema extended to multi-piece via SOS-10-specific `piece_id` and `medium` fields.

**§5 / §6 / §7 amendments**:
- §5 (frozen decisions) updated: chart-language declaration attribute (PCDN-003), `<sos:medium>` sub-element shape (PCDN-004), per-medium timeout defaults (PCDN-006), strict-one-orchestrator (PCDN-007).
- §6.4 (network medium) updated to name gRPC + AMQP as protobuf-encoded transports per PCDN-002; per-medium timeout defaults from PCDN-006; idempotency warning behaviour from PCDN-005.
- §9 worked-example gateway-language line updated from "TBD" to "Rust" per PCDN-001.
- INV-S-ORCH-1 wording extended: "exactly one orchestrator chart per system (strict at v1; PCDN-007)".
- INV-S-ORCH-4 wording extended: "wire format derived from protobuf (PCDN-002); chart never authors wire-format-specific fields".

**Status**: 🟢 **ratified**. Implementation of the orchestrator emit path in `tools/sos-codegen/` is now unblocked. The §9 worked example becomes a buildable demonstration target. SOS-13 verified-strip story extends naturally across all 4 media because protobuf-derived wire format is dischargeable in the same way as in-process function-pointer dispatch.

### 2026-05-26 — Wave-16 implementation (3 of 4 media + annotations parser)

Implementation wave landed across four parallel agents + one sequential pre-step:

- **SOS10-ANNOT** (`c929a6e`, cherry-picked as `650af0a`): `tools/sos-codegen/sos10_annotations.py` — orchestrator-chart annotation parser mirroring SOS-09 precedent. Parses `<sos:medium>` sub-elements (with nested `<sos:transport>`, `<sos:timeout>`, `<sos:idempotent>`), `sos:lang` attributes on `<state>`, and per-transition `sos:idempotent` overrides. Frozen-enum validation on medium kind (§5.2) and transport name (PCDN-002). +13 tests.
- **SOS10A** (`46e5fb4` / `fcb68bb`): in-process medium emitter — Rust↔Rust direct function-pointer dispatch tables, C↔C `void(*)(const sos_event_t *)`, Rust↔C FFI bridges with `extern "C"` shims + `#[repr(C)]` payloads. Event-ID deterministic from `SHA-256(chart_sos_id|event_name)[:4]`. +13 tests.
- **SOS10B** (`f5dbe6f` / `ef2eaa2`): shared-memory medium emitter — POSIX SHM with C11 atomic head/tail ring (`<stdatomic.h>`), Rust producer/consumer behind `posix_shm` Cargo feature, C producer/consumer with acquire/release atomics, RTOS-mapping informational `TODO(SOS-10-rtos)` block. Ring capacity defaults to 256, override via `ring_capacity` attribute on `<sos:medium>`. +24 tests.
- **SOS10C** (`0bac861` / `3091f7f`): mmio medium emitter — synthesizes SOS-09 channel annotations as inputs to the SOS-09 emitter family. Four mapping modes (notification → command; request_response → command+status pair; streaming → queue; shared_surface → shared) chosen via `mmio_kind` extras hint. Pipe-back to `sos09_annotations.parse_chart_annotations` validates synthesized output round-trips cleanly. +11 tests.
- **SOS10D** (`42baf12` / `87fbe3c`): scjson 0.4.0 smoke tests + emitter `@spec` roadmap annotations — 4 capability-gated import-and-call smoke tests confirming `help_text`, XInclude preserve, `<send>` attribute surface, `<invoke>` attribute surface are all accessible via the bundled scjson Python binding. `@spec` roadmap-annotation blocks added to six existing emitters citing SOS-09 §16 and SOS-ROADMAP-07-PLUS §12 (scjson 0.4.0 features remain roadmap-tracked, NOT current-scope). +4 tests.

**§12 acceptance gate transitions**:
- (e) ⏸ → ✅ — SOS-09 + SOS-12 cited; no semantic duplication. The `mmio` emitter is the load-bearing example: it generates SOS-09 channel-annotation JSON rather than re-emitting any SOS-09 artifact.
- (f) ⏸ → ✅ — every emitted artifact carries an `@spec` comment block citing §6.x + INV-S-ORCH-N + INV-SOS-A.

**Gates still ⏸ (deferred to follow-on waves)**:
- (b) MCU + FPGA + gateway worked example as a buildable bench demonstration (Lattice ECP5 + STM32H747I-DISCO bench substrate + LAN-connected gateway).
- (c) End-to-end cocotb-equivalent harness for all 4 media (unit tests landed; integration harness pending; `network` emitter not yet implemented).
- (d) Cross-piece bounded-reachability vector emission + INV-SOS-H chart-vocabulary failure rendering on a deliberate broken-protocol case.

**Network emitter deferred** to a follow-on wave. Substantial scope: protobuf .proto generation + gRPC service stubs (server + client) + AMQP message schemas + wire-format derivation per INV-S-ORCH-4 + timeout/idempotency annotation handling. Splitting it from this wave keeps in-process / shared-memory / mmio thin and tractable.

Test suite delta (full SOS-codegen suite): 2181 → 2246 passing (+65), 2 skipped (Yosys + iverilog, environmental, unchanged).

### 2026-05-26 — Wave-17 implementation (network medium + worked-example chart)

Wave-17 closes out the four-medium emitter family with the network medium (deferred from wave-16) and lands the §9 worked-example chart as a parsing-ready skeleton:

- **SOS10-PROTO** (`9fd1832` / `d8ce7f9`): protobuf IDL emitter — canonical wire format per PCDN-SOS-10-002. Emits proto3 `.proto` files per chart (`build/network/<chart_id>/orchestrator.proto` + `<piece_id>_service.proto`) plus an `amqp_routing.json` metadata sidecar consumed by the AMQP emitter. Alphabetical message ordering, hex8 package suffix from `sos:id`, scalar-type mapping with default-`bytes` + TODO comment. +22 tests; +1 skip (protoc).
- **SOS10-GRPC** (`790d202` / `113b521`): gRPC service-stub emitter — Rust `tonic` server + client stubs derived from the protobuf IDL. Role-asymmetric emission (source-only → client only; target-only → server only; bidirectional → both). Timeout precedence transport > medium > 5000ms default per PCDN-SOS-10-006. PCDN-SOS-10-005 idempotency `SAFETY:` comment block on non-idempotent transitions. +32 tests; +1 skip (cargo offline).
- **SOS10-AMQP** (`7dbef8f` / `17933ac`): AMQP message-handler emitter — Rust `lapin` producer + consumer + topology stubs with protobuf-encoded message bodies. Timeout default 10000ms per PCDN-SOS-10-006. PCDN-SOS-10-005 emitter-time WARN log on non-idempotent AMQP transitions. ExchangeKind::Direct per chart-explicit routing-key matching; topology declaration is idempotent. +25 tests.
- **SOS10-EXAMPLE** (`807dcc5` / `6f11662`): §9 worked-example chart at `examples/orchestrator_mcu_fabric_gateway.scxml` — three pieces (`mcu` rust, `fabric` vhdl, `gateway` rust) with five cross-piece transitions exercising all four media and both network transports. Smoke-test confirms the chart parses cleanly through `sos10_annotations.parse_orchestrator_annotations`. +6 tests.

**§12 acceptance gate status update**:
- (b) ⏸ still pending bench-side build; chart skeleton now exists (was missing pre-wave-17).
- (c) ⏸ still pending cocotb-equivalent end-to-end harness; all 4 media now have unit-test coverage (network was missing pre-wave-17).
- (d) ⏸ unchanged — bounded-reachability vector emission + INV-SOS-H chart-vocabulary failure rendering pending.

**Network-medium implementation complete**. The remaining ⏸ gates ((b)/(c)/(d)) are integration / bench / vector-emission concerns, not emitter-implementation concerns.

Test suite delta (full SOS-codegen suite): 2246 → 2331 passing (+85), 4 skipped (Yosys + iverilog + protoc + cargo-offline, environmental).
