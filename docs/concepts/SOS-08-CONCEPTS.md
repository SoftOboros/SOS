# SOS-08 — HDL backend (synthesizable VHDL-2008 + SystemVerilog-2017)

**Status:** 🟢 **ratified 2026-05-23**. All 11 PCDNs walked; resolutions recorded in §15.

## 0. Authority policy

This phase doc is the **umbrella** for the HDL backend work. Per the Spec-Before-Code Planning Discipline (parent CLAUDE.md), it ratifies the cross-sub-phase decisions; the per-sub-phase contracts (SOS-08-A primitive library, SOS-08-B service composition, SOS-08-C chart→FSM emission, SOS-08-D cocotb+SVA, SOS-08-E SV testbench+SVA, SOS-08-F UVM sequences, SOS-08-G waveform+annotation, SOS-08-H cooperative-only) land as their own sub-phase concept docs once the umbrella's PCDNs resolve.

Normative sections of this doc: §3 glossary, §4 source-of-truth map, §5 frozen decisions (synthesizable subset, vendor-IP override mechanism), §6 sub-phase scope, §7 cross-sub-phase invariants, §8 standards integration matrix additions, §12 acceptance checklist.

Informative sections: §1 purpose, §2 problem statement, §11 non-goals, §15 change log.

All keywords MUST, MUST NOT, SHALL, SHOULD, SHOULD NOT, MAY are interpreted per RFC 2119 / 8174 when capitalised.

This doc cites SOS-07 §6 for cross-phase invariants (INV-SOS-A through H) and §7 for the AuthorityRelationship matrix. It does not re-derive them.

## 1. Purpose

To take the Statechart Orchestration System's bench-validated methodology (proven at the kernel-bootstrap level by SOS-04 Rust + SOS-05 C reaching `CanonicalReplacement` per SOS-06 §5.2 (d)) and extend it across the hardware/software membrane onto synthesizable HDL.

The unlock the article frames: one statechart → C + Rust + VHDL + Verilog from one source, with bounded-reachability vectors that exercise both sides of the membrane against the same model. The chart is the spec; the verification artifact is the vectors; the implementations are interchangeable views.

SOS-08 is the phase that makes that promise true on the HDL side.

## 2. Problem statement

Five observations from the SOS-07 reframe converge on this phase:

1. **RTOS primitives and HDL synchronization primitives are isomorphic.** Mutex ≅ arbiter+grant register. Counting semaphore ≅ credit counter. Mailbox ≅ async FIFO. Event flag ≅ strobe+latch. Timer ≅ rate generator + counter. The asymmetry is that hardware gets spatial replication nearly free while software multiplexes one CPU; the design question rotates, the algebra doesn't.

2. **HDL has no kernel.** Every project re-derives the same handful of primitives — dual-port-plus-arbiter, async FIFO with Gray pointers, credit counters. The world's most-reinvented module is the membrane between an MAC writing descriptors and a driver draining a ring buffer. The reinvention isn't waste — it's that there's no "use the OS primitives" because there's no OS.

3. **A statechart-driven HDL backend can be the kernel.** Three layers (L0 primitives, L1 services, L2 tasks-as-generated-FSMs), each with verified handshake-compatible interfaces, generated from charts that already specify the synchronization contract on the software side. The user's "spend a day or two getting it solid" tax is really a tax on not having a kernel; SOS-08 ships the kernel.

4. **Bounded-vector verification is the unlock most HDL flows lack.** Constrained-random simulation chases statistical confidence ("we ran 10M cycles"); SOS-08 emits exhaustive vectors within the chart's reachability bound. The verification claim is "no bad state is reachable within the bound" — a stronger position than UVM shops have access to without separate property authoring.

5. **The cocotb + open-source-synth stack lets the methodology adopt without enterprise tooling.** EOQ-003 + EOQ-004 resolutions name this explicitly: cocotb-first (Icarus / Verilator / GHDL run vectors); Yosys + nextpnr / GHDL synth produce bitstreams; Lattice ECP5 + iCE40 are the first SoC targets. The napkin-to-silicon adoption story survives unfunded teams and indie hardware shops.

## 3. Canonical glossary

Terms normative within SOS-08+. Authority relationships per §8.

| Term | Definition |
|---|---|
| **Layer 0 (L0) primitives** | Parameterized portable RTL modules: `sos_fifo_async`, `sos_arbiter_rr`, `sos_arbiter_priority`, `sos_mutex`, `sos_credit_counter`, `sos_dpram_arb`, `sos_tick_gen`, `sos_synchronizer`, `sos_strobe_latch`, `sos_rate_divider`. Each primitive ships with parameterized SVA/PSL safety-property assertions + an MTBF-justified synchronizer treatment. |
| **Layer 1 (L1) services** | Composed L0 primitives with named interfaces matching the FreeRTOS / POSIX vocabulary (so the C/Rust side and HDL side share nouns): `sos_mailbox`, `sos_event_group`, `sos_resource_pool`, `sos_periodic_task`, `sos_message_channel`. |
| **Layer 2 (L2) tasks** | FSMs generated from chart regions, instantiated with the standard port set: clock, reset, tick, event-in channel, event-out channel, resource-claim channel. SOS-08-C is the L2 emission contract. |
| **handshake-compatible port** | Every L0 primitive + L1 service + L2 task exposes a uniform request/acknowledge / ready/valid port shape. The HDL analogue of "everything is a file descriptor" — composition is tractable because the interface is universal. |
| **vendor-IP override** | An L0 primitive's portable RTL implementation MAY be swapped at synthesis time for a vendor-IP instantiation (e.g. `xpm_fifo_async`, `dcfifo`, Lattice `generic_fifo_dc`) via a parameter or build-script flag. The wrapper interface stays; the implementation underneath changes. |
| **synthesizable subset** | The subset of VHDL-2008 / SystemVerilog-2017 that current production synthesis tools accept: structural + RTL-modelling constructs only; no testbench-only primitives (`semaphore`, `mailbox`, `assert property` with non-bind-able antecedents, `program` blocks, dynamic processes, `randomize()`, `class` outside the testbench files). |
| **cooperative-only scheduling** | Per EOQ-008-ROADMAP resolution: v1 HDL emission has no preemption. FSMs run to completion within a single chart macrostep; there is no save/restore mechanism. Documented as a design choice in every SOS-08 deliverable. |
| **review artifact** | A waveform + chart-state-overlay file (SOS-08-G) the developer uses to review an MCP-mediated chart modification's behaviour at the hardware level — the hardware analog of the graphical chart diff at the spec level. |

## 4. Source-of-truth map

| Concept | Authority |
|---|---|
| Synthesizable subset of VHDL-2008 | IEEE 1076-2008 (external); locally **derived** per §5.1 |
| Synthesizable subset of SystemVerilog-2017 | IEEE 1800-2017 (external); locally **derived** per §5.1 |
| L0 primitive library | **this doc** (§6 sketches each); per-primitive contracts ratify in SOS-08-A-CONCEPTS.md |
| L1 service composition contracts | **this doc** (§6); per-service contracts ratify in SOS-08-B-CONCEPTS.md |
| L2 chart→FSM emission strategy | **this doc** (§6); per-region contracts ratify in SOS-08-C-CONCEPTS.md |
| Vector emission priorities | SOS-07 §7 standards integration matrix; EOQ-003-ROADMAP resolution carries forward |
| Cooperative-only design | **this doc** (§5.2); SOS-08-H-CONCEPTS.md is the dedicated sub-phase doc |
| Vendor-IP override mechanism | **this doc** (§5.3) |
| Cross-sub-phase invariants | **this doc** (§7) |
| Cross-phase invariants INV-SOS-A through H | `SOS-07-CONCEPTS.md` §6 (referenced, not redefined) |

## 5. Frozen decisions

### 5.1 Dialect targets

Per EOQ-002-ROADMAP resolution: **VHDL-2008** + **SystemVerilog-2017** only. Older dialects (VHDL-1993, Verilog-2005) deferred indefinitely. Open-source synth (Yosys for SV; GHDL synth + Yosys for VHDL) supports both subsets sufficient for v1 deliverables.

Frozen-enumeration registration policy: **Standards Action** (adding a third dialect requires §15 amendment + cross-phase review).

### 5.2 Cooperative-only scheduling

Per EOQ-008-ROADMAP resolution: v1 HDL emission is **cooperative only**. Rationale recorded in detail at SOS-08-H-CONCEPTS.md when that sub-phase ratifies. Preemption is a "can of worms" with a small set of genuine use cases (sub-microsecond interrupt handling in safety-critical paths); deferred indefinitely as its own potential future initiative.

Frozen-enumeration registration policy: **Standards Action**.

### 5.3 Vendor-IP override pattern

Every L0 primitive MUST be authored with two implementation paths:

1. **Portable RTL** (default) — synthesizable VHDL-2008 / SV-2017 using only generic primitives. Backend-agnostic across Xilinx / Intel / Lattice / open-source-synth / ASIC.
2. **Vendor-IP shim** — a parameterized wrapper that instantiates the vendor's optimised IP (`xpm_fifo_async` for AMD/Xilinx, `dcfifo` for Intel/Altera, `generic_fifo_dc` for Lattice) underneath the same interface as the portable form.

The override is selected via a per-primitive parameter (or build-script flag), not via a separate source file. Switching backends is a build-time decision; chart code does not change.

For Lattice SoC targets (per EOQ-004-ROADMAP) the portable RTL path is exercised first — that's the path that goes through Yosys + nextpnr without vendor-tooling. Vendor-IP shims for Lattice come later.

Frozen-enumeration registration policy for the vendor list: **Specification Required** (adding a vendor requires a phase-owner walkthrough; modifying the wrapper-interface contract requires §15 amendment here).

### 5.4 Vector emission priority

Per EOQ-003-ROADMAP resolution (substantial reframe), the SOS-08-D through SOS-08-G sub-phases land in this priority order:

1. **SOS-08-D — cocotb + SVA bind files** (primary, open-source-sim path).
2. **SOS-08-E — SystemVerilog testbench + SVA bind files** (LCD path, class-based, no UVM dep).
3. **SOS-08-F — UVM sequences only** (stimulus plug-in; not full UVM env).
4. **SOS-08-G — Waveform + transaction-level annotation files** (review artifact; per EOQ-011-ROADMAP resolution: `.fst` + `.vcd` + JSON-Lines overlay `{cycle, signal, chart_state, transition_id}`).

The formal-flow path (SymbiYosys / JasperGold) consumes the SVA bind files emitted by D/E/F directly. No separate emitter; same artifact, two consumers.

Frozen-enumeration registration policy: **Standards Action** (adding a fifth emitter requires §15 amendment).

## 6. Sub-phase scope (informative summary; each sub-phase ratifies in its own doc)

### SOS-08-A — L0 primitive library

Eleven primitives, each shipping with: portable RTL (VHDL + SV), vendor-IP shim parameters, SVA/PSL safety-property assertions, MTBF-justified synchronizer treatment where async, parameterized cocotb testbench, generated synthesizable instantiation example.

| Primitive | Purpose | Notes |
|---|---|---|
| `sos_fifo_async` | Cross-clock-domain message queue | Gray-coded pointers; 2-FF synchronizers; depth parameterized |
| `sos_fifo_sync` | Single-clock-domain message queue | Simpler than async; same interface shape |
| `sos_arbiter_rr` | Round-robin arbiter | N-requester, M-grant; fair within bounded cycles |
| `sos_arbiter_priority` | Priority arbiter with optional aging | Aging prevents starvation under sustained high-priority load |
| `sos_mutex` | 1-bit lock register + arbiter | Tries through `sos_arbiter_rr` or `sos_arbiter_priority` |
| `sos_credit_counter` | Distributed semaphore | Over/underflow guards; assertion-checked |
| `sos_dpram_arb` | Dual-port RAM + arbiter | The hardware-side IPC building block; sized parameter |
| `sos_tick_gen` | Periodic rate generator | One per system; fanout downstream |
| `sos_synchronizer` | N-FF synchronizer | 2-FF default; configurable for higher-MTBF targets |
| `sos_strobe_latch` | Pulse-to-level + ack | Event-flag primitive |
| `sos_rate_divider` | Programmable rate divider | Per-task slower ticks |

### SOS-08-B — L1 service composition

Composed L0 primitives matching FreeRTOS / POSIX vocabulary:

| Service | Composed from | API noun-set |
|---|---|---|
| `sos_mailbox` | `sos_fifo_sync` or `sos_fifo_async` + handshake | Mailbox post/take with priority |
| `sos_event_group` | N × `sos_strobe_latch` + `sos_arbiter_rr` | Event flags |
| `sos_resource_pool` | Free-list FIFO over static pool | Static-allocation discipline |
| `sos_periodic_task` | `sos_rate_divider` strobe into FSM enable | Periodic-task scaffolding |
| `sos_message_channel` | `sos_fifo_async` + ready/valid handshake | Cross-domain event channels |

The vocabulary deliberately mirrors FreeRTOS/POSIX so a developer reading the chart sees the same nouns on both sides of the membrane. The implementation is HDL; the interface is RTOS.

### SOS-08-C — Chart → FSM emission

Statechart compilation to synthesizable RTL:

- One FSM per chart region. State register encoded per synthesis tool's preferred encoding (one-hot at v1 default; other encodings opt-in via parameter).
- Transitions emitted as combinational `next_state` logic.
- Event queues as Layer-1 `sos_message_channel` instantiations.
- Deferred events as a separate register file outside the FSM encoding (avoids fighting the synthesis tool's encoding heuristics).
- Per INV-SOS-G, eliminated branches (proved unreachable by bound analysis) emit as `assume false` annotations the synthesis tool uses to optimize state-encoding.

### SOS-08-D — cocotb + SVA bind files (primary)

The primary vector path per EOQ-003. Two artifacts emitted side-by-side from one IR:

- **cocotb testbench** — Python coroutines that drive RTL signals + check expected behaviour against the chart's bounded-reachability vectors.
- **SVA bind file** — `bind <module> <assertion_module> ...` SystemVerilog binding that asserts the chart's invariants concurrently with the testbench. Same SVA properties feed the formal-flow path (SymbiYosys / JasperGold) without additional emission.

Per INV-SOS-H: every cocotb test failure renders in chart vocabulary; every SVA failure trace points back to the chart state/transition/invariant that generated the property.

### SOS-08-E — SystemVerilog testbench + SVA bind files

The LCD path: class-based, self-checking, constrained-random-free, no UVM dependency. Same SVA bind files as SOS-08-D. Every commercial simulator (Questa, Riviera, VCS, Xcelium) runs it; no enterprise-method expertise required.

### SOS-08-F — UVM sequences only

Stimulus emission for plug-in into the customer's existing UVM environment. SOS does NOT emit full UVM testbenches at v1 (per EOQ-003). The customer wraps the SOS sequences in their own UVM scaffolding (sequencer, driver, environment, test classes). 10% of engineering cost for 80% of adoption value.

### SOS-08-G — Waveform + transaction-level annotation

The review artifact (per EOQ-011-ROADMAP). Three files per generated test run:

1. `.fst` waveform (GTKWave + Surfer native; compact).
2. `.vcd` waveform (universal compatibility).
3. `<test>.annotations.jsonl` overlay file with `{cycle, signal, chart_state, transition_id}` tuples. The chart-vocabulary bridge that closes the MCP-workflow review loop at the hardware level.

GTKWave + Surfer + commercial viewers each render the waveform format they prefer; the overlay file is consumed by viewer extensions to render chart-state badges on the waveform timeline.

### SOS-08-H — Cooperative-only scheduling

The ratification doc for the v1 cooperative-only design. Documents the design rationale (preemption-in-HDL costs shadow register files or chart-side save-point annotations; the genuine use cases are a small subset of HDL workloads); names the explicit non-goal; records the open-question status of a future preemption phase if a concrete user case demands it.

## 7. Cross-sub-phase invariants

In addition to the cross-phase invariants INV-SOS-A through H (from SOS-07), the following invariants are normative across SOS-08's sub-phases:

- **INV-S-HDL-1 — Handshake-compatible ports.** Every L0 primitive, L1 service, and L2 task exposes the canonical request/acknowledge OR ready/valid handshake port shape. Composition through this port shape is the universal-interface property that makes the kernel-style architecture work.

- **INV-S-HDL-2 — Static-allocation discipline.** No dynamic allocation in any SOS-08 emission. Free-list FIFOs over static pools (per `sos_resource_pool` shape) handle the cases that would use `malloc` in software. Bounded resources are part of the verification claim.

- **INV-S-HDL-3 — Cross-domain isolation.** Any signal that crosses clock domains MUST go through `sos_synchronizer` or `sos_fifo_async`. The bounds analysis explicitly excludes the synchronizer flops from the formal model (metastability is a physical phenomenon below the digital abstraction) and verifies them separately via the standard MTBF calculation. SOS-08-D ensures every cross-domain signal has a synchronizer + an assertion that the synchronized signal is the only one downstream code consumes.

- **INV-S-HDL-4 — Cooperative-only at v1.** Per EOQ-008. Documented in every sub-phase deliverable. Re-opening this invariant requires a §15 amendment to SOS-08-H + cross-phase review.

- **INV-S-HDL-5 — Vector-to-chart traceability for HDL.** Concretizes INV-SOS-H for the HDL target: every cocotb test, SV testbench, UVM sequence, SVA property, and waveform annotation MUST carry chart-vocabulary metadata so failures render at the chart level, never the RTL-signal level alone.

## 8. Standards integration matrix additions

The following rows EXTEND the SOS-07 §7 matrix:

| Concept | Upstream authority | Local relationship | Phase that declares it | Mutation rights |
|---|---|---|---|---|
| VHDL-2008 synthesizable subset | IEEE 1076-2008 | **derive** | SOS-08 (this doc, §5.1) | none — emit conformant subset |
| SystemVerilog-2017 synthesizable subset | IEEE 1800-2017 | **derive** | SOS-08 | same |
| SVA (subset within IEEE 1800-2017) | IEEE 1800-2017 | **derive** (chart invariants → assert property) | SOS-08-D | same |
| UVM (subset for sequence-only emission) | Accellera | **derive** (sequences plug into customer env) | SOS-08-F | same |
| cocotb (Python testbench framework) | open project | **derive** | SOS-08-D | same |
| GTKWave / Surfer waveform viewers | open projects | **represent** | SOS-08-G | none |
| AMD/Xilinx UNIMACRO IP (`xpm_fifo_async`, etc.) | AMD/Xilinx | **compose** (vendor-IP shim path) | SOS-08-A | none — shim wrapper owns the interface |
| Intel/Altera megafunctions (`dcfifo`, etc.) | Intel | **compose** | SOS-08-A | same |
| Lattice generic primitives (`generic_fifo_dc`, etc.) | Lattice | **compose** | SOS-08-A | same |
| Yosys + nextpnr open-source synth | open project (CHIPS Alliance / YosysHQ) | **derive** (target backend for portable RTL path) | SOS-08-A | none |
| GHDL synth (open-source VHDL synthesis) | open project | **derive** | SOS-08-A | none |
| Icarus Verilog (open-source simulator) | open project | **derive** (cocotb backend) | SOS-08-D | none |
| Verilator (open-source simulator) | open project | **derive** (cocotb backend) | SOS-08-D | none |

## 9. Non-goals

This phase does NOT:

- Emit full UVM testbenches at v1. Only UVM-compatible sequences (per EOQ-003 / §6 SOS-08-F).
- Emit preemption-supporting RTL at v1. Cooperative-only per §5.2 / EOQ-008.
- Support older HDL dialects (VHDL-1993, Verilog-2005). Per EOQ-002.
- Target distributed-via-network HDL flows. Per EOQ-004; that's SOS-10 (multi-language orchestrator) at v2.
- Replace existing HDL design tools. Vendor synthesis tools (Vivado, Quartus, Diamond/Radiant, Yosys) consume the emitted RTL; SOS doesn't ship synthesis.
- Verify metastability in the formal model. INV-S-HDL-3 explicitly excludes synchronizer flops from formal proof; MTBF calculation handles that path separately.

## 10. Reconciliation decisions vs adjacent repo primitives

### vs. SOS-04 / SOS-05 software-side primitives

`sos_mailbox` / `sos_event_group` / `sos_resource_pool` use the same vocabulary as the chart-side syscalls (`sem.take` / `sem.give` / `queue.send` / `queue.receive`). The HDL service is the realisation of the chart-side syscall on the hardware side of the membrane; SOS-09 ratifies the membrane-crossing contract in detail.

### vs. SOS-06 codegen-evaluation methodology

The seven SOS-06 metrics (`FunctionalConformance`, `BinarySize`, `RamFootprint`, `BuildTime`, `SourceLineCount`, `MacrostepCycleCount`, `Auditability`) apply to HDL targets with minor adjustments:

- `BinarySize.text` becomes `AreaFootprint` (LUTs + FFs + BRAM at synthesis; cycle-count at a chosen target board).
- `RamFootprint.bss` becomes static-allocation accounting (number of registers / BRAM blocks allocated, vs unbounded).
- `MacrostepCycleCount` becomes `MacrostepClockCount` (cycles between event entry and quiescence).
- `BuildTime` becomes synth+place+route time at a representative target.

A SOS-06 §15 amendment co-lands when SOS-08-A ratifies, recording the HDL-target metric extension.

### vs. INV-SOS-G (verified-codegen position)

SOS-13 concretizes INV-SOS-G for Rust. The HDL analog lands when a sub-phase or successor phase ratifies the synthesizer-side equivalents (`assume false` annotations the synth tool consumes to optimize encoding; pruned-state-encoding emissions; etc.). This is a SOS-08 follow-on, not part of v1.

## 11. Pending Concept Decision Notices (PCDNs)

These are the open questions whose resolution moves this doc from 🟡 drafted to 🟢 ratified.

- **PCDN-SOS-08-001 — L0 primitive interface shape: req/ack vs ready/valid.** AXI-Stream uses ready/valid; legacy designs use req/ack. SOS-08-A's L0 primitives could expose either. **Recommendation**: ready/valid for data-bearing channels (mailboxes, FIFOs, message channels — AXI compatibility); req/ack for control-only handshakes (mutex grant, event-strobe ack). Both forms are handshake-compatible per INV-S-HDL-1.

- **PCDN-SOS-08-002 — State-encoding default for SOS-08-C.** One-hot, binary, or Gray? One-hot is fastest but biggest; binary is the synthesis default; Gray reduces switching noise but is rarely worth it on modern silicon. **Recommendation**: one-hot at v1 (decode-fast, area-cheap on modern FPGAs); per-region override via chart annotation.

- **PCDN-SOS-08-003 — Vendor-IP shim default at synth time.** When the user builds for an AMD/Xilinx target, does the L0 primitive default to `xpm_fifo_async` or portable RTL? **Recommendation**: portable RTL default (cross-vendor consistency); user opts into vendor IP via per-primitive parameter at build time (`-Dvendor=xilinx`).

- **PCDN-SOS-08-004 — cocotb-vs-pyuvm choice for SOS-08-D.** cocotb 1.x is the established Python testbench framework; pyuvm overlays UVM semantics on top of cocotb. Should SOS-08-D emit cocotb-classic or pyuvm? **Recommendation**: cocotb-classic at v1 (lowest barrier; pyuvm is essentially UVM-as-Python and we've already deferred full UVM). pyuvm-compatible emission is a SOS-08-F follow-on if a customer requests it.

- **PCDN-SOS-08-005 — Cross-clock-domain handshake protocol.** Two-flop synchronizer + ready/valid is the simple form; multi-cycle path constraints with handshake-protected data are the optimised form. **Recommendation**: simple form (2-FF sync + ready/valid) at v1; optimised form opt-in per channel via chart annotation.

- **PCDN-SOS-08-006 — Lattice SoC target sub-prioritization.** Per EOQ-004-ROADMAP, "Lattice SoC soon". Within Lattice's offering: ECP5 (open-source-synth-supported, Yosys+nextpnr-ecp5), iCE40 (smaller, also Yosys+nextpnr-ice40 supported), MachXO (proprietary tools). **Recommendation**: ECP5 first (largest Lattice part supported by Yosys+nextpnr; matches the unfunded-team adoption story). iCE40 next. MachXO deferred.

- **PCDN-SOS-08-007 — SVA bind file scope per cocotb test.** Should every cocotb test bind all chart invariants, or only invariants relevant to the test's reachable states? **Recommendation**: full bind by default (assertion non-trigger is cheap; complete coverage is the verification value); per-test scoping opt-in for performance.

- **PCDN-SOS-08-008 — Synth-time elimination of unreachable transitions.** Per INV-SOS-G, eliminated branches emit as `assume false`. **Recommendation**: opt-in at v1 (`--verified-strip` flag, parallel to the Rust SOS-13 mechanism). Default emission preserves all transitions for debug ease.

- **PCDN-SOS-08-009 — Vector-IR canonical format.** The chart's bounded-reachability produces traces (sequences) + invariants (properties). What's the on-disk canonical form between the chart compiler and SOS-08-D/E/F/G emitters? **Recommendation**: JSON-Lines for traces (one event per line; matches the existing conformance vector format); JSON for invariants (structured property definitions); both schema-validated by the codegen tool.

- **PCDN-SOS-08-010 — Multi-clock-domain chart annotation.** When a chart region runs at a different clock from its parent, the chart needs an annotation declaring the clock relationship. **Recommendation**: `<region clock="domain_b" />` attribute on `<state>` and `<parallel>` elements; the chart compiler ensures every cross-domain transition has an `sos_synchronizer` or `sos_fifo_async` between regions.

- **PCDN-SOS-08-011 — Top-level wrapper generation.** When the chart-driven design becomes a full SoC top-level, does SOS-08 emit the top-level wrapper (clock/reset distribution, IO pin assignment, board-specific instantiations) or leave that to the user? **Recommendation**: SOS-08 emits a parameterized top-level wrapper template; per-board overrides (Lattice ECP5 dev board, generic FPGA dev board, ASIC tape-out wrapper) are board-specific files the user maintains. Top-level wrapper is a generated artifact in `build/`, not a tracked source.

## 12. Acceptance checklist

A conforming SOS-08 umbrella ratification satisfies:

- (a) ⏸ PCDN-SOS-08-001 through 011 resolved.
- (b) ⏸ Each sub-phase SOS-08-A through SOS-08-H has its own concept doc drafted and ratified.
- (c) ⏸ At least one L0 primitive (recommended: `sos_fifo_async`) is implemented as portable RTL + cocotb tests + SVA properties as a worked-example exercise of the SOS-08-A contract.
- (d) ⏸ The codegen tool gains an HDL-emit path; chart → VHDL + SystemVerilog emission tested on at least one chart (recommended: a sub-chart factored out of `rtos_kernel.scxml` for the worked example).
- (e) ⏸ Bench validation: on a Lattice ECP5 dev board (per PCDN-SOS-08-006), the worked-example chart synthesizes via Yosys+nextpnr, places + routes, and passes its cocotb tests against the generated bitstream's behaviour as observed via a simulator (Verilator).
- (f) ⏸ Cross-phase invariants INV-SOS-A through H cited correctly in each sub-phase doc.
- (g) ⏸ SOS-06 §15 amendment co-landed extending the seven metrics to HDL targets.

(j) and onward are implementation gates that ratify when the sub-phase landings happen.

## 13. Files cited

| Path | Role |
|---|---|
| `docs/concepts/SOS-07-CONCEPTS.md` | Cross-phase invariants + AuthorityRelationship matrix; cited but not redefined. |
| `docs/concepts/SOS-ROADMAP-07-PLUS.md` | Informative roadmap; the EOQ resolutions this phase promotes. |
| `docs/concepts/SOS-06-CONCEPTS.md` | Codegen-evaluation methodology; extended at HDL-target ratification. |
| `rtos_kernel.scxml` | Bootstrap kernel chart; the worked-example HDL emission target candidate. |
| `tools/sos-codegen/` | Codegen tool; gains HDL emit paths. |
| Parent `CLAUDE.md` | Spec-Before-Code Planning Discipline. |

## 14. Unblocks

This phase's umbrella ratification (after PCDN resolution) unblocks:

- **SOS-08-A through SOS-08-H sub-phase concept-doc cycles**, each independently.
- **SOS-09** (hardware/software membrane) — depends on SOS-08-A/B existing.
- The article's "cocotb-runs-the-kernel-chart-on-a-Lattice-FPGA" demo, which is the napkin-to-silicon claim made concrete.

## 15. Change log

### 2026-05-23 — Initial draft (Ira)

- Authored `SOS-08-CONCEPTS.md` as the umbrella concept doc for HDL-backend work.
- Frozen decisions §5: VHDL-2008 + SV-2017 only (EOQ-002); cooperative-only (EOQ-008); vendor-IP override pattern with portable-RTL default (EOQ-004 + new PCDN-003); vector emission priority cocotb → SV → UVM sequences → waveform (EOQ-003 + EOQ-011).
- Sub-phase scope §6 sketches SOS-08-A through SOS-08-H; each ratifies separately.
- Cross-sub-phase invariants §7: INV-S-HDL-1 through 5.
- AuthorityRelationship matrix §8: adds 13 rows to SOS-07 §7 (HDL standards, vendor IP families, open-source toolchains).
- Reconciliation §10 names the HDL-side metric extensions to SOS-06's seven metrics.
- 11 PCDNs raised covering the umbrella-level decisions that need user input before sub-phase work begins.

Status: 🟡 **drafted**, awaiting PCDN walkthrough.

### 2026-05-23 — Ratified (Ira)

All 11 PCDNs walked and resolved:

| PCDN | Resolution |
|---|---|
| **001 — L0 interface shape** | ✅ **Mixed**: ready/valid for data-bearing channels (mailboxes, FIFOs, message channels — AXI-compatible); req/ack for control-only handshakes (mutex grant, event-strobe ack). Both forms are handshake-compatible per INV-S-HDL-1. |
| **002 — State-encoding default for SOS-08-C** | ✅ **One-hot at v1** (decode-fast, area-cheap on modern FPGAs — the v1 target). Per-region binary override via chart annotation for ASIC-flow opt-in. |
| **003 — Vendor-IP default at synth time** | ✅ **Portable RTL default**; user opts into vendor IP via `-Dvendor=xilinx` (or `-Dvendor=intel`, `-Dvendor=lattice`) per-primitive at build time. Preserves cross-vendor consistency and the open-source-synth adoption story. |
| **004 — cocotb-classic vs pyuvm for SOS-08-D** | ✅ **cocotb-classic at v1**. Lowest barrier; full UVM already deferred per EOQ-003. pyuvm-compatible emission is a SOS-08-F follow-on if a customer requests it. |
| **005 — CDC handshake protocol** | ✅ **Simple form (2-FF synchronizer + ready/valid) at v1**. Multi-cycle-path-constrained optimized form is opt-in per channel via chart annotation. |
| **006 — Lattice SoC sub-target** | ✅ **ECP5 first** (largest Lattice part supported by Yosys + nextpnr; aligns with the unfunded-team open-source-synth story). iCE40 next. MachXO (proprietary Diamond/Radiant tools) deferred. |
| **007 — SVA bind file scope per cocotb test** | ✅ **Full bind by default**. Assertion non-trigger is cheap; complete coverage is the verification value. Per-test scoping opt-in for performance-critical regression runs. |
| **008 — Synth-time elimination of unreachable transitions** | ✅ **Opt-in via `--verified-strip` flag**, parallel to SOS-13's Rust mechanism. Default emission preserves all transitions for debug ease; `--verified-strip` emits `assume false` annotations the synth tool consumes to optimize state-encoding. |
| **009 — Vector-IR canonical format** | ✅ **JSONL for traces** (one event per line; matches the existing conformance vector format); **JSON for invariants** (structured property definitions). Both schema-validated by the codegen tool. |
| **010 — Multi-clock-domain chart annotation** | ✅ **`<region clock="domain_b"/>`** attribute on `<state>` and `<parallel>` elements. Chart compiler ensures every cross-domain transition has an `sos_synchronizer` or `sos_fifo_async` between regions (per INV-S-HDL-3). |
| **011 — Top-level wrapper generation** | ✅ **Generated parameterized wrapper template** in `build/`, NOT a tracked source. Per-board overrides (Lattice ECP5 dev board, generic FPGA dev board, ASIC tape-out wrapper) are board-specific files the user maintains. Top-level wrapper is a generated artifact per INV-SOS-A. |

Status: 🟢 **ratified**. SOS-08 sub-phase concept-doc cycles (SOS-08-A through SOS-08-H) unblocked. SOS-09 (membrane) depends on SOS-08-A/B existing; that dependency chain begins clearing as SOS-08-A ratifies.
