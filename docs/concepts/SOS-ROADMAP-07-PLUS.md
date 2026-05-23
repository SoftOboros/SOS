# SOS Roadmap — Phases 07 through 13 (Statechart Orchestration System)

**Status:** 🟡 informative roadmap, drafted 2026-05-22. This document is **not normative**. It names the phases that will land as their own normative `SOS-NN-CONCEPTS.md` docs per the Spec-Before-Code Planning Discipline (parent CLAUDE.md). Each phase it names is **a future ratification**, not a current commitment.

The earlier SOS phases — SOS-00 (foundational), SOS-01 (lint), SOS-02 (host simulator), SOS-03 (conformance vectors), SOS-04 (M7 Rust port), SOS-05 (M7 C port), SOS-06 (codegen-evaluation methodology) — completed v1 of the **bootstrap** demonstration: a small RTOS kernel specified as a single SCXML statechart, with bench-validated reference ports on Cortex-M7 and a codegen tool that produces both ports at `CanonicalReplacement` verdict per SOS-06 §5.2 (d).

This roadmap names the next seven phases that lift SOS from "we proved the methodology on a kernel" to "the methodology owns the spec-before-code orchestration of arbitrary multi-language, multi-target systems."

## 0. Authority and scope

This document is **informative**. It does not amend any normative section of any phase doc. Per the Spec-Before-Code discipline, every phase named here lands its own `SOS-NN-CONCEPTS.md` ratification before any behaviour change in that phase's surface.

The renames + scope expansions this roadmap recommends require ratification via:

- SOS-00 §15 amendment to rename the initiative and broaden the charter.
- A new SOS-07-CONCEPTS doc declaring the cross-domain scope formally.
- Per-phase concept docs SOS-08 through SOS-13 following.

Open questions raised here use the shape `EOQ-NNN-ROADMAP` (sequential within this document).

## 1. The reframe — what the present moment surfaced

Five facts produced by SOS-00…06 + the bench validation + the article work together:

1. **The chart is the only artifact that survives** every translation step — through `scjson` round-trip, through bounded-reachability vector emission, through both port-language emissions, through bench validation. The bench-validated `CanonicalReplacement` verdict on both Rust and C ports proves that the chart is the spec, the rest is downstream.
2. **The bounded-vector deliverable inverts the usual TDD trust direction**. Tests are no longer authored examples; they are exhaustive vector sets derived from the chart's reachability bound. The chart is the spec; the vectors are the contract; both implementations are views.
3. **The Statechart-Orchestrated Scheduler** name was always too narrow. The kernel was the proving ground; the methodology that emerged is not kernel-specific. The natural rename is **Statechart Orchestration System**.
4. **iState (Infinity State)** is the authoring surface; SCXML is the canonical artifact. EOQ-008 from SOS-06-A-EVALUATION resolved conditionally: SCXML stays canonical IFF scjson round-trips preserve all iState "other attributes" extensions, which is empirically true today and validated in the round-trip pipeline.
5. **The hardware/software membrane is the natural next target.** RTOS primitives (mutex, semaphore, mailbox, event flag, timer) and HDL synchronization primitives (arbiter, credit counter, async FIFO, strobe-and-latch, rate generator) are isomorphic — both solve "N requesters, M < N resources, fair ordering, no corruption". One declarative spec language compiling to both sides is the cleanest demonstration of the methodology.

## 2. Rename — Statechart Orchestration System

**SOS-07** is the rename + expanded-charter phase. It lands as a `SOS-07-CONCEPTS.md` ratification + a SOS-00 §15 amendment. The acronym `SOS` is load-bearing; the expansion changes.

| Before | After |
|---|---|
| Statechart-Orchestrated Scheduler | Statechart **Orchestration System** |
| "An RTOS specified as SCXML" | "A spec-before-code orchestration system whose canonical form is SCXML, whose authoring surface is iState, and whose targets include any language or hardware backend that can host a generated FSM" |
| Bootstrap = "the kernel chart `rtos_kernel.scxml`" | Bootstrap = "the kernel chart, as the v1 demonstration; subsequent phases address general orchestration" |

The rename is mechanical across docs but the **charter expansion** carries weight: SOS-07 formally records that the methodology applies to arbitrary chart-driven systems, not just an RTOS kernel. The kernel chart becomes one chart among future many.

## 3. Cross-phase invariants

These hold across every phase named below. Each is recorded with a name so future phase docs can cite them by ID rather than re-deriving them.

- **INV-SOS-A — Chart-as-source.** Every domain SOS targets has the chart (in SCXML form, on disk) as its sole upstream spec. Hand-edits to generated artifacts are prohibited as a process matter; tooling makes them rejected as a compile-error matter where possible.

- **INV-SOS-B — Vectors-as-deliverable at every layer.** Bounded reachability emits exhaustive vector sets at the chart level. Hierarchical composition (charts-dispatching-charts) preserves boundedness via per-layer contract enforcement; each layer's vectors test that layer's behaviour against its declared environment, never the joint Cartesian product.

- **INV-SOS-C — MCP as the sole chart modification surface.** Human-and-agent chart edits flow through MCP tools that operate on the chart's semantic structure (`add_state`, `remove_transition`, `nest_region`, `extract_region_to_subchart`), never on raw SCXML text. The graphical viewer renders diffs in the same notation the developer authors.

- **INV-SOS-D — iState authoring, SCXML canonical.** EOQ-008 resolution carries: iState is the authoring surface, SCXML is the canonical artifact on disk, scjson is the round-trip oracle that proves the iState↔SCXML extraction is lossless. INV-S1 from SOS-00 stays intact at the artifact layer.

- **INV-SOS-E — Explicit authority relationships.** When SOS integrates an external standard (SCXML, VHDL, Verilog, SystemVerilog, SVD, OCI, IEEE-754, etc.) the integrating phase doc declares the `AuthorityRelationship` (mirror / adapt / extend / compose / own / derive / represent) per parent CLAUDE.md's "Standards integration" convention. Undeclared relationships read as `mirror` with no mutation rights.

- **INV-SOS-F — Bound composition.** Joint reachability across hierarchically-composed charts is computed as the per-layer bound × independence axes, NOT the Cartesian product. Orthogonal regions are the natural independence axes; sequential composition uses contract-matching at the dispatch boundary.

- **INV-SOS-G — Verified-codegen position.** Generated code (Rust, C, VHDL, Verilog, anything else) MAY omit runtime checks whose obligation is discharged by the chart's bounds analysis, provided every elimination cites the discharging invariant. This is the "third position" beyond default-safe Rust and default-unchecked C — verified-by-construction omissions, made auditable by per-elimination invariant citations.

- **INV-SOS-H — Vector-to-chart traceability.** Every emitted vector (cocotb, SV testbench, UVM sequence, waveform annotation) carries metadata naming the chart state, transition, or invariant that generated it. Failure messages render in chart vocabulary: "transition T42 in subchart `auth.connecting` produced a vector that violated invariant I7" — never raw RTL signal traces alone. The chart-level failure message is what makes the verification artifact part of the spec-as-source story; without it, the developer has to translate signal traces back to chart terms by hand, which reintroduces the documentation-drift failure mode the methodology was designed to prevent.

## 4. Phase outline

Each phase below lands its own normative `SOS-NN-CONCEPTS.md`. The §-numbering structure follows SOS-00 / SOS-04 / SOS-06 precedent.

### SOS-07 — Statechart Orchestration System (rename + charter)

**Scope:** rename the initiative; update SOS-00 §15 to record the broadened charter; establish INV-SOS-A through G as cross-phase invariants; define the relationship between the bootstrap kernel chart and future application charts.

**Deliverables:**
- `SOS-07-CONCEPTS.md` (this document, lifted into normative form after EOQ resolution).
- SOS-00 §15 amendment recording the rename + charter expansion.
- README / AGENTS / CLAUDE updates reflecting the rename.
- iState project rename (`/proj/sos` is already correct).

**Out of scope:** any behaviour change. SOS-07 is documentation and ratification only.

### SOS-08 — HDL backend (synthesizable VHDL + Verilog)

The biggest phase by scope. Subdivides as:

- **SOS-08-A — HDL primitive library (Layer 0).** Parameterized, portable RTL for: `sos_fifo_async` (Gray-coded), `sos_arbiter_rr`, `sos_arbiter_priority`, `sos_mutex`, `sos_credit_counter`, `sos_dpram_arb`, `sos_tick_gen`, `sos_synchronizer` (n-FF), `sos_strobe_latch`, `sos_rate_divider`. Each primitive ships with parameterized SVA/PSL assertions of its safety properties and an MTBF-justified synchronizer treatment. Vendor-IP overrides per target (xpm_fifo_async, dcfifo, Lattice generic_fifo_dc) opt-in via parameter.

- **SOS-08-B — HDL service composition (Layer 1).** Composed primitives with named interfaces: `sos_mailbox`, `sos_event_group`, `sos_resource_pool`, `sos_periodic_task`, `sos_message_channel`. Wrappers that match the FreeRTOS / POSIX vocabulary so the C/Rust side and HDL side share nouns.

- **SOS-08-C — Chart → FSM emission.** Statechart compilation to synthesizable RTL: one FSM per chart region, state register encoded per synthesis-tool's preferred encoding (one-hot at v1 default), transitions emitted as combinational `next_state` logic, event queues as Layer-1 `sos_message_channel` instantiations, deferred events as a separate register file outside the FSM encoding to avoid synthesis-tool encoding-heuristic fights.

- **SOS-08-D — cocotb + SVA bind file emission (PRIMARY vector path).** Per EOQ-003 resolution, cocotb is the v1-priority vector emitter. Rationale: (1) zero impedance mismatch with the bounds-analysis IR — both are Python objects; (2) runs against open-source simulators (Icarus Verilog, Verilator, GHDL), so users can verify without a paid EDA licence — load-bearing for the napkin-to-silicon adoption story; (3) cultural fit with the Python-tooling crowd that already builds generator-driven workflows; (4) excellent debug story (failing vectors drop into `pdb` against live RTL state). SVA bind files emitted **alongside** the cocotb testbench, not as a separate target — the chart's bound analysis produces two artifact families (traces = vectors, invariants = properties), and SVA is the invariant projection of the same model. Both run concurrently in the cocotb test: example-based confidence (vectors pass) plus property-based confidence (invariants hold). Every failure renders in chart vocabulary per INV-SOS-H.

- **SOS-08-E — SystemVerilog testbench + SVA bind file emission.** Lowest-common-denominator commercial-simulator path. Coding-style contract: **class-based, self-checking, constrained-random-free, no UVM dependency**. The "boring but universal" target — every Questa/Riviera/VCS user can consume it; no UVM expertise required. SVA bind files travel with it (same emission as SOS-08-D).

- **SOS-08-F — UVM sequence emission (stimulus-only, plug-in).** Per EOQ-003 resolution, SOS does NOT emit full UVM testbenches at v1. UVM environments are heavyweight (class hierarchy, register layer, scoreboard, sequencer, factory patterns) and enterprise shops have their own environments they want to keep using; they want stimulus and properties, not infrastructure. SOS emits UVM-compatible sequences — the stimulus portion that plugs into the customer's existing UVM environment. Customer wraps the SOS sequences in their own scaffolding. Full UVM testbench emission deferred until a paying customer requires it.

- **SOS-08-G — Waveform + transaction-level annotation emission (review artifact).** Per EOQ-011, not a vector format but a review artifact. Generated `.fst` / `.vcd` waveform references with named-transaction annotations overlaying which RTL behaviour corresponds to which chart state. The hardware analog of the graphical chart diff in the MCP-mediated workflow: when an agent modifies a chart, the developer sees the chart-level diff (legible at spec level) AND the waveform-level diff (legible at hardware level). The annotation layer bridges the two notations. Closes the review loop end-to-end.

- **SOS-08-H — Cooperative-only scheduling (v1 ratification).** Per EOQ-008 resolution, **preemption is explicitly out of scope for v1**. Rationale: preemption-in-HDL costs shadow register files (area-expensive) or requires explicit save-point chart annotations (complexity-expensive); the genuine use cases are a small set (hard real-time interrupt handling at sub-microsecond latencies in safety-critical paths); the design space is wide enough to be its own initiative. v1 HDL emission is **cooperative only**, documented as such in every SOS-08 deliverable. A future SOS-08-* phase OR a v2 effort addresses preemption when a concrete user case demands it.

**Formal-flow path (SymbiYosys / JasperGold) — no separate emitter needed.** Consumes the SVA bind files emitted by SOS-08-D / E / F. Same artifacts, different consumer; users with formal-verification tools point them at the SVA bind files and prove the properties exhaustively. This is the most defensible verification claim the methodology produces: "exhaustive vectors within the bound, plus formal-provable invariants" — neither half can be waved away.

**Open-source synthesis path (Yosys + nextpnr / GHDL synth).** Per EOQ-004 resolution noting an upcoming Lattice SoC target, the open-source synthesis flow (Yosys for SystemVerilog / nextpnr for Lattice ECP5 + iCE40; GHDL synth + Yosys for VHDL) is a first-class target. This aligns naturally with SOS-08-D's cocotb-first priority — both are open-source, both pull the verification + synthesis story below a paid-tools floor. The "napkin to silicon" claim survives unfunded teams + academic users + indie hardware shops only if both halves of the flow stay open. Vendor-IP overrides (Xilinx/Intel) opt-in per target via the SOS-08-A vendor-IP-shim mechanism; the Lattice path uses only generic primitives.

**Cross-phase contracts:**
- INV-SOS-G is heavily exercised: synthesis tools optimize away unreachable transitions when the chart's bound analysis marks them unreachable.
- INV-SOS-F is the formal model: per-region FSMs compose via Layer-1 channels, joint reachability is per-region × independence-axis (orthogonal parallel regions = independent axes).
- Vendor-IP override path is the canonical example of `AuthorityRelationship = compose` (SOS owns the wrapper interface; vendor IP is composed underneath, swap-in at synthesis time).

### SOS-09 — Hardware/software membrane (register handoff + protection)

**Scope:** the membrane between a software side (C/Rust on a CPU) and a hardware side (FPGA fabric or ASIC). Today this membrane is described as a register-map PDF that lies; SOS-09 makes the membrane a chart annotation that emits:

1. **Software-side accessors** (Rust `HAL`-style typed register access, C macros against an SVD-derived header).
2. **Hardware-side register file RTL** (synthesizable VHDL/Verilog, with read/write/clear-on-read semantics, side-effect-on-write notification, atomicity guarantees).
3. **Register-map artifact** (CMSIS-SVD XML and/or a SystemRDL emit, depending on EOQ-005 resolution). This is the artifact that historically can't lie — generated, therefore can't drift.
4. **Membrane vectors** that test the read/write pairing across the boundary at every register, including read-modify-write atomicity, clear-on-read semantics, side-effect-on-write.

**Channel categories:**

| Chart annotation | SW side | HW side | Membrane primitive |
|---|---|---|---|
| `<channel kind="status" dir="hw→sw"/>` | RO register / IRQ on change | output register + strobe | sos_strobe_latch |
| `<channel kind="command" dir="sw→hw"/>` | WO register / write-triggers-action | input register + handshake | handshake req/ack |
| `<channel kind="queue" dir="hw↔sw"/>` | ring buffer in DPRAM + IRQ | DMA descriptor + IRQ strobe | sos_dpram_arb + sos_message_channel |
| `<channel kind="shared" dir="hw↔sw" mutex/>` | typed atomic region | sos_mutex + atomic R-M-W primitive | sos_mutex |

**Protection model:** per-channel access control encoded in the chart. The chart declares which CPU side (privileged/unprivileged, security-zone, MPU region) can read/write each register; the membrane emitter generates MPU configuration, register-map access-control bits, and (on the HW side) decode logic that enforces the access pattern. Cross-zone access generates a documented exception path, also chart-derived.

**Why this lifts the methodology:** the register map / membrane is where every hardware-software co-design project has historically failed silently. The PDF is right at tape-out; six months later the driver team has tweaked the firmware to work around an erratum, the RTL team has tweaked the silicon to work around a different erratum, and the PDF is wrong on both sides. SOS-09 makes the PDF a generated artifact whose source is the chart, whose verification is the membrane vectors, and whose evolution is a chart amendment. The PDF can't lie because the PDF is the build output.

### SOS-10 — Multi-language orchestration (higher-level synchronizer)

**Scope:** systems composed of pieces in different languages, where each piece is a chart-driven sub-system, and a top-level chart orchestrates them. Examples:

- An MCU + FPGA + co-processor system, where the MCU side is Rust/C (SOS-04 / SOS-05), the FPGA side is VHDL/Verilog (SOS-08), and the orchestrator chart describes the data flow + power state machine across all three.
- A multi-host distributed system where each host runs a different language stack (Rust microservice, Python data plane, Go control plane) but the top-level orchestration chart describes message flow + failure handling.
- A multi-process system on a single host (kernel driver + userspace daemon + signaling library) where each side has its own chart and the top-level orchestrator describes the IPC contract.

**Deliverables:**
- `SOS-10-CONCEPTS.md` defining the **orchestrator chart** model: a chart whose states are *charts* (in a piece-of-the-system sense), whose transitions are cross-piece events with explicit medium (shared memory, AMQP, gRPC, named pipe, MMIO, AXI, etc.), and whose bounded-reachability analysis covers the joint protocol.
- Per-medium emitter modules (start with the four most common: in-process function call, shared-memory ring buffer, AMQP/Kafka messaging, MMIO over a bus).
- Vector emission that exercises the orchestrator-level protocol end-to-end, with each piece either stubbed at its API boundary or live-driven (selectable per piece).

**Authority relationships:** the orchestrator chart **composes** the per-piece charts; it does not own them. Cross-piece events are **derived** from the per-piece chart's external-event vocabulary (the chart of piece A declares which events it can receive; the orchestrator chart can only fire those events at A).

**The unlock:** today, cross-piece integration is the gnarliest part of any multi-language system, because each piece's chart (if it has one) lives in a different format with a different authoring surface. SOS-10 hoists the cross-piece contract into a chart of its own. The orchestrator's bounded reachability covers the joint protocol, the vectors derived from the orchestrator validate every piece-pair interaction, and the verification gap that historically lived between pieces becomes a chart-level invariant.

### SOS-11 — MCP-mediated chart editing

**Scope:** the MCP tool surface that makes the chart load-bearing as a process matter, not just as an architectural matter. INV-SOS-C is the cross-cutting invariant; SOS-11 is where it lands.

**Deliverables:**
- A defined MCP tool surface that is **algebraic** over the chart structure, not syntactic over SCXML text. Tools include `add_state`, `remove_state`, `add_transition`, `remove_transition`, `nest_region`, `unnest_region`, `extract_region_to_subchart`, `inline_subchart`, `add_event_to_vocabulary`, `add_datamodel_entry`, etc.
- Each tool call's effect on the chart is computed by the tool, and the resulting chart is validated through the existing scjson round-trip + scxml-lint + bounded-reachability stack BEFORE the chart is committed. Tool calls that violate any invariant fail before commit.
- Tool calls emit a vector delta as part of their result. The agent's response to the developer includes "here's the chart diff, here's the vector diff" — the verification consequence is visible at modification-review time.
- The graphical viewer (browser-based, served via the iState surface) renders before/after chart diffs with chart-level semantics, not text diffs.

**Out of scope at SOS-11:** the MCP host plumbing. SOS-11 specifies the tools; the iState MCP server hosts them as part of its tool catalogue.

### SOS-12 — Recursive chart dispatch (charts-dispatching-charts)

**Scope:** the hierarchical decomposition pattern that lets the methodology scale past toy charts.

**Deliverables:**
- A formal model of **chart-as-sub-chart**: a chart whose states are sub-charts, whose transitions reference sub-chart contracts, and whose bounded reachability composes per-layer.
- Tooling for `extract_region_to_subchart` (MCP) and `inline_subchart` (MCP) that maintain bounded-reachability invariants across the factoring.
- Per-sub-chart **contract declarations**: declared events-in, declared events-out, declared invariants. The parent chart's verification treats the sub-chart as an atomic transition with the declared contract; the sub-chart's verification treats its environment as the declared contract (matched from above).
- **Legibility-as-discipline** integration: when a chart hits a project-configured legibility threshold (e.g. 15 peer states at one level), the MCP layer makes `extract_region_to_subchart` the preferred operation; `add_state_anyway` fails the lint pass.

**The protocol-stack motivating example:** a top-level message-type dispatch chart (5-10 states, one per category), per-category sub-charts (5-15 states each), per-handler sub-charts (whatever size the semantics require). The whole protocol becomes legible at every level; no individual chart exceeds the legibility threshold.

### SOS-13 — Verified-codegen Rust position

**Scope:** formalize INV-SOS-G's "third position" for the Rust target. The bench measurement of `+12 %` text vs hand-written Rust on the codegen kernel sits inside the 1.5× gate but is removable.

**Deliverables:**
- A `verified-strip` profile in `tools/sos-codegen/` Rust emission that, when the chart's bounds analysis certifies the precondition, emits `get_unchecked`, `unwrap_unchecked`, `unreachable_unchecked` against the chart-discharged obligation. Every `unsafe` block carries a comment naming the discharging invariant.
- A `dev-keep` profile that keeps default-safe Rust idiom for development / chart-authoring iteration. Switchable per-region per project.
- Updated `MacrostepCycleCount` and `BinarySize.text` measurements on the bench under `verified-strip`. Target: within 0-2 % of hand-written C on the SOS-04 substrate.
- SOS-06 §15 amendment recording the `verified-strip` measurements + the architectural claim ("verified Rust occupies a third position safe-Rust and C cannot reach").
- Article-quality framing of the result: the language-size debate isn't C-vs-Rust, it's "which debugging posture does the codegen pick, and which costs does the proof discharge."

## 5. Standards integration — AuthorityRelationship matrix

Per INV-SOS-E, every external standard SOS integrates declares its relationship. Below is the matrix as it stands at SOS-07 reframe; future phases extend it.

| Concept | Upstream authority | Local relationship | Phase that declares it | Mutation rights |
|---|---|---|---|---|
| SCXML 1.0 | W3C Recommendation 2015 | **mirror** (chart on disk is verbatim SCXML) | SOS-00 §0 INV-S1 | none — locally |
| scjson AST | scjson project (BSD-1-Clause) | **adapt** (we use scjson's JSON as build IR) | SOS-06-A | none — upstream owns |
| iState extensions | iState project | **extend** (position_x/position_y on `other_attributes`) | SOS-06 §15 Amd 005 EOQ-008 | iState owns the extensions; SOS preserves via scjson round-trip |
| ARMv7-M ISA / Cortex-M7 | ARM (proprietary docs) | **mirror** (SOS-00 §6 distils the subset SOS depends on) | SOS-00 §6 | none — SOS-00 §6 IS the local authority |
| FreeRTOS / POSIX vocabulary | open implementations | **mirror** (we use the names because users know them) | SOS-08-B | none — names are vocabulary, not API |
| VHDL (IEEE 1076-2008) | IEEE Standard | **derive** (emit synthesizable subset) | SOS-08 | none — we emit conformant subset |
| Verilog / SystemVerilog (IEEE 1800-2017) | IEEE Standard | **derive** (emit synthesizable subset) | SOS-08 | same |
| SVA (SystemVerilog Assertions) | IEEE 1800-2017 subset | **derive** (emit from chart invariants) | SOS-08-D | same |
| UVM | Accellera | **derive** (emit sequences from chart vectors) | SOS-08-D | same |
| cocotb | open project | **derive** (emit Python testbench from vectors) | SOS-08-D | same |
| CMSIS-SVD | ARM (vendor-neutral) | **derive** (emit register map from chart) | SOS-09 | none — we emit valid SVD |
| SystemRDL | Accellera | **derive** (alternative register map format) | SOS-09 | same |
| AMQP 1.0 | OASIS | **compose** (orchestrator chart fires AMQP-medium transitions) | SOS-10 | none — AMQP is one medium among many |
| gRPC | open project | **compose** (same pattern) | SOS-10 | same |
| MCP (Model Context Protocol) | Anthropic-led, open | **adapt** (we author tools; MCP is the wire format) | SOS-11 | none — MCP wire is upstream |

This matrix is **load-bearing** for the article framing: SOS sits at the confluence of standards, and the discipline is to be explicit about how each one is consumed. The matrix is also a defence against the failure mode CLAUDE.md names: "we copied it into our schema, therefore we own it."

## 6. Phase dependencies + sequencing

```
SOS-07 (rename) ──┬──> SOS-08 (HDL backend, multi-sub-phase) ──┬──> SOS-09 (membrane)
                  │                                              │
                  ├──> SOS-11 (MCP tools) ──┬──> SOS-12 (recursive dispatch)
                  │                          │
                  └──> SOS-13 (verified-Rust)─┘                  │
                                                                 ▼
                                                         SOS-10 (orchestrator)
```

- **SOS-07 must land first** because it touches every existing doc (rename).
- **SOS-08, SOS-11, SOS-13 can proceed in parallel** after SOS-07 (file-disjoint authoring surfaces).
- **SOS-09 depends on SOS-08** (needs synthesizable RTL primitives to put on the HW side of the membrane).
- **SOS-12 depends on SOS-08** (sub-chart contracts need to be expressible in the HDL backend too) **and SOS-11** (the MCP tools that maintain the legibility threshold).
- **SOS-10 depends on SOS-09** (the orchestrator's HW↔SW edges go through the membrane).

Cardinality of work: SOS-07 is ~1 week of editing; SOS-08 is multi-month with 5 sub-phases; SOS-09 is multi-month; SOS-10 is multi-month; SOS-11/12/13 are individually 1-2 weeks each.

## 7. Existing-phase amendments required

The rename + charter expansion lands as a sequence of §15 amendments on the existing phase docs. Per Spec-Before-Code discipline, each amendment is its own dated entry citing this roadmap.

| Phase | Amendment scope |
|---|---|
| SOS-00 | §15: rename to Statechart Orchestration System; INV-SOS-A through G added to invariants; charter expanded; the v1 kernel-chart is reframed as the bootstrap. |
| SOS-01 | §15: lint rules extended for iState `position_x`/`position_y` attributes (already partial since they're tolerated as `other_attributes`); HDL-region annotations (`<region target="hw">`) become a lint rule once SOS-08 lands. |
| SOS-02 | §15: simulator scope unchanged; reframe the kernel-chart as the v1 demonstration; future application charts use the same simulator. |
| SOS-03 | §15: vector framework extended to cover HDL targets per SOS-08-D; vector IR formalized as the canonical interchange format. |
| SOS-04 / SOS-05 | §15: "first reference port" reframing; the M7 Rust + C ports become two of N targets, not "the" targets. SOS-13 results land as further §15 amendments. |
| SOS-06 | §15: codegen evaluation methodology extended to cover HDL targets (the seven metrics apply with a few HDL-specific adjustments — `RamFootprint` becomes `AreaFootprint`, `MacrostepCycleCount` becomes `MacrostepClockCount`, etc.). |

## 8. Open questions (EOQ-NNN-ROADMAP)

These are the user-decisions whose resolution unblocks the named phases. They follow the EOQ pattern used in SOS-06-A-EVALUATION.

- **EOQ-001-ROADMAP — Version bump for the rename.** ✅ **RESOLVED 2026-05-22 (Ira) — v1 development continues.** No v2 bump. The SOS-07 rename + charter expansion lands as prose amendments to existing phase docs; previously-ratified content stays valid. The "v1 = kernel bootstrap, v2 = orchestration system" framing is rejected: SOS v1 *is* the orchestration system — the bootstrap kernel is its first proving ground, not a separate generation.

- **EOQ-002-ROADMAP — HDL dialect target choice.** ✅ **RESOLVED 2026-05-22 (Ira) — VHDL-2008 + SystemVerilog-2017 only.** Older dialects (VHDL-1993, Verilog-2005) deferred indefinitely. Open-source synth (Yosys, GHDL synth) supports both 2008/2017 subsets, so the unfunded-team adoption story doesn't require an older-dialect fallback.

- **EOQ-003-ROADMAP — Vector format prioritization.** ✅ **RESOLVED 2026-05-22 (Ira) — substantial reframe.** Priority isn't "technical purity" — it's "who unblocks adoption." Resolution:

  1. **cocotb first** — open-source simulators (Icarus, Verilator, GHDL) make the "napkin-to-silicon" claim survive unfunded teams; Python objects match the bounds-analysis IR directly (zero impedance mismatch); Python-tooling crowd cultural fit; failing vectors drop into `pdb`. Early-adopter overlap is FPGA / embedded / academic, not Synopsys customers — that's fine for v1.
  2. **SystemVerilog testbench second** — class-based, self-checking, constrained-random-free, no UVM dependency. The "boring but universal" target. Every commercial simulator runs it; no enterprise expertise required.
  3. **SVA bind files emitted ALONGSIDE every format, NOT as a separate target.** SVA is the property/invariant projection of the chart's bound analysis; vectors are the trace projection. They are duals, both derivable from the same model, both shipped together. Every cocotb test ships `bind` SVA properties; every SV testbench ships the same. Same SVA bind files feed the formal-flow path (SymbiYosys/JasperGold) for users with formal tools — zero additional authoring cost, since the chart's bound analysis already produces the properties.
  4. **UVM sequences only, not full environments.** Generating idiomatic UVM testbenches is more engineering than the other three combined; enterprise shops have UVM environments they want to keep using. SOS emits UVM-compatible sequences (stimulus portion); customer wraps in their own scaffolding. 10% of engineering for 80% of adoption value. Full UVM environment emission deferred until a paying customer requires it.
  5. **Formal-flow path (SymbiYosys / JasperGold)** consumes SVA bind files emitted by paths 1–4 directly. No separate emitter; same artifact, two consumers.

  **Per-format contract**: each emitter takes the bounded-reachability artifact (sequences + invariants) and produces a directory with testbench, properties, build script, README with simulator invocation, AND **round-trip metadata** (per INV-SOS-H) so failing vectors trace back to chart artifacts — not just RTL signals. SOS-08-D through SOS-08-G in §4 are restructured to reflect this priority + SVA-everywhere posture.

- **EOQ-004-ROADMAP — Multi-language orchestrator scope.** ✅ **RESOLVED 2026-05-22 (Ira) — same-host at v1; Lattice SoC target named explicitly.** Same-process + multi-process at v1; multi-host deferred. Additionally: a **Lattice SoC** target is named for early addition (Lattice ECP5 / iCE40 + open-source synth flow via Yosys + nextpnr). This validates the cocotb-first + open-source-synth-flow priority in §4 — both halves of the flow stay open, the unfunded-team story holds, and the upcoming SoC target exercises the methodology against real hardware before any commercial-tool gating.

- **EOQ-005-ROADMAP — Register map format.** ✅ **RESOLVED 2026-05-22 (Ira) — CMSIS-SVD primary, SystemRDL secondary.** Widest tool ecosystem first (every Cortex-M debug tool consumes SVD; `svd2rust` / `chiptool` already in the Rust ecosystem). SystemRDL as alternate for non-Cortex-M targets + semantically-richer register designs. Custom JSON declined.

- **EOQ-006-ROADMAP — MCP tool surface granularity.** ✅ **RESOLVED 2026-05-22 (Ira) — both layers shipped.** Primitives (`add_state`, `add_transition`, etc.) are the atomic operations the agent uses; higher-intent operations (`add_event_handler_for_state`, `extract_orthogonal_region`) are syntactic sugar that decompose into primitive sequences. Agent picks at request time; primitive operations are always available for fine-grained edits.

- **EOQ-007-ROADMAP — Bound composition algebra naming.** ✅ **RESOLVED 2026-05-22 (Ira) — cite CSP explicitly.** INV-SOS-F's per-layer × independence axis bound composition is named relative to CSP (Communicating Sequential Processes). CSP is the lineage Handel-C / occam-π came from; the citation makes formal-methods readers' mapping straightforward + acknowledges the prior art SOS extends rather than rediscovers. SOS-specific algebra (with bounded-vector emission as a first-class operation) is named in SOS-12.

- **EOQ-008-ROADMAP — Preemption in HDL.** ✅ **RESOLVED 2026-05-22 (Ira) — no preemption in v1, documented.** Rationale: preemption is a "can of worms" with a small set of genuine use cases. Cooperative-only is the v1 design (SOS-08-H ratifies it). Preemption deferred indefinitely; reopens as its own initiative if/when a concrete user case demands it. v1 HDL deliverables document the cooperative-only design choice explicitly so users with preemption expectations are surfaced before they ship.

- **EOQ-009-ROADMAP — Bootstrap-chart governance.** ✅ **RESOLVED 2026-05-22 (Ira) — kernel chart stays as bench fixture.** `rtos_kernel.scxml` continues to bench-validate against the SOS-03 conformance suite on every toolchain release, proving end-to-end methodology integrity. Future application charts have their own validation surfaces; the kernel chart is the v1 demonstration that the methodology survives a real (non-toy) workload through full bench validation.

- **EOQ-010-ROADMAP — Article-as-amendment.** ✅ **RESOLVED 2026-05-22 (Ira) — stand-alone artifact.** The November 2026 article publishes independently; cites the per-phase docs as references; the docs don't cite the article. Prose-of-record stays in the concept docs.

- **EOQ-011-ROADMAP — Waveform-annotation review-artifact specifics.** *(Raised 2026-05-22 by EOQ-003 reframe.)* SOS-08-G emits waveform + transaction-annotation files as a review artifact (the hardware analog of the chart diff in the MCP workflow). Open question: which waveform format and annotation schema? Candidates: (a) `.fst` (fastsignaltrace, GTKWave-native, open + small); (b) `.vcd` (universal but bulky); (c) Riviera/Questa's proprietary native format (best annotation tooling); (d) all three with a single annotation schema overlaid. Recommendation: (d) — emit `.fst` + `.vcd` with a separate annotation-overlay file (likely JSON-Lines with `{cycle, signal, chart_state, transition_id}` tuples) that GTKWave + Surfer + commercial viewers can consume. Final disposition resolves at SOS-08-G concepts-doc-authoring time.

## 9. The article framing — protagonist and conceptual driver

The user's directive: **iState (Infinity State) as the central character; Statechart Orchestration System as the primary conceptual driver across domains.** This roadmap reflects that framing:

- **Infinity State is the protagonist.** It's the authoring surface, the graphical editor, the round-trip oracle's destination, the agent's view-of-record. INV-SOS-D names it explicitly. The user never sees raw SCXML unless they explicitly request it; the chart lives in iState as a first-class artifact with its own version history, its own MCP tool surface, its own collaborative editing model.

- **SOS is the methodology that gives iState its meaning.** Without SOS, iState is "another diagramming tool". With SOS, iState is the napkin that is also the spec that is also the source-of-truth that is also the contract that is also the verification oracle. The reframing is not "Infinity State joins SOS" — it's "Infinity State is what SOS looks like from the developer's chair."

- **The bootstrap kernel proves the methodology**; the HDL backend proves the cross-domain claim; the membrane proves the spec-as-contract claim; the orchestrator proves the multi-language claim; recursive dispatch proves the scaling claim; verified-codegen Rust proves the language-cost-debate claim. Each phase named here is one section of the article's argument made concrete in code.

- **The TDD-as-precursor framing** lands across all phases simultaneously: every phase emits vectors as a build artifact; every phase's bounded-reachability is the exhaustive-vector position TDD was reaching for. The article makes the claim once at altitude; the roadmap makes the claim true at every layer.

## 10. Files cited

| Path | Role |
|---|---|
| `docs/concepts/SOS-00-CONCEPTS.md` | foundational; gets §15 amendment for rename. |
| `docs/concepts/SOS-01-CONCEPTS.md` | lint; gets §15 amendment when SOS-08 HDL annotations land. |
| `docs/concepts/SOS-02-CONCEPTS.md` | simulator; gets §15 amendment for reframe. |
| `docs/concepts/SOS-03-CONCEPTS.md` | conformance vectors; gets §15 amendment for HDL vector framework. |
| `docs/concepts/SOS-04-CONCEPTS.md` | M7 Rust port; gets §15 amendment for "first ref port" reframing + SOS-13 results. |
| `docs/concepts/SOS-05-CONCEPTS.md` | M7 C port; gets §15 amendment for "first ref port" reframing. |
| `docs/concepts/SOS-06-CONCEPTS.md` | codegen evaluation methodology; gets §15 amendment for HDL extension. |
| `docs/concepts/SOS-06-A-EVALUATION.md` | toolchain evaluation, including EOQ-008 (iState↔SCXML reconciliation). |
| `docs/concepts/SOS-ROADMAP-07-PLUS.md` | this doc; informative roadmap. |
| `rtos_kernel.scxml` | bootstrap chart; stays bench-validated as the v1 demonstration fixture. |
| `tools/sos-codegen/` | codegen tool; gets HDL backends in SOS-08, register-map emit in SOS-09. |
| Parent `CLAUDE.md` | Spec-Before-Code discipline; AuthorityRelationship matrix conventions. |

## 11. What this roadmap does NOT do

For the avoidance of doubt, this document **does not**:

- Ratify any of SOS-07 through SOS-13. Each phase lands its own normative concepts doc through the standard ratification cycle.
- Change any existing phase's normative content. The §15 amendments named in §7 land as separate dated entries on the affected phase docs.
- Bind the codegen tool to any specific HDL dialect, vector format, or register-map standard. Those decisions are EOQ-resolved per phase.
- Promise a delivery schedule. The phase ordering in §6 is a logical-dependency graph, not a Gantt chart.

The roadmap exists to surface the planning conversation in writable form, so that future phase ratifications have a place to point back to when explaining their motivation. It is **a starting frame**, not a commitment.

## 12. Change log

### 2026-05-22 — Initial draft (Ira)

- Authored as the prose-of-record for the SOS-07-through-SOS-13 expansion conversation.
- Names seven phases (SOS-07 through SOS-13) with §-numbered scope statements.
- Records cross-phase invariants INV-SOS-A through G.
- Records the AuthorityRelationship matrix as of the SOS-07 reframe.
- Raises ten roadmap-level EOQs (EOQ-001-ROADMAP through EOQ-010-ROADMAP) that gate the named phases.
- Identifies six existing-phase §15 amendments required to land the rename + charter expansion.
- Frames iState as the protagonist + SOS as the conceptual driver per user directive.

Status: 🟡 informative, awaiting user resolution of EOQ-001 through EOQ-010 before the SOS-07 ratification cycle begins.

### 2026-05-22 — EOQ batch resolution (Ira)

User walked all 10 roadmap EOQs and ratified the resolutions captured in §8 above.

**Headline outcomes:**

- **v1 development continues** (EOQ-001). No version bump for the rename. The kernel-bootstrap-vs-orchestration-system distinction lives at the phase level, not the version level.
- **HDL dialects pinned**: VHDL-2008 + SystemVerilog-2017 only (EOQ-002).
- **Vector-format priority substantially reframed** (EOQ-003): cocotb first (open-source-sim, Python-IR alignment, napkin-to-silicon adoption story), SV testbench second (LCD path), **SVA bind files emitted alongside every format** (NOT separate), UVM = sequences only (plug-in, not full env), formal-flow consumes the SVA bind files directly. SOS-08-D through SOS-08-G in §4 restructured to match.
- **Lattice SoC target added** (EOQ-004). Open-source synth flow (Yosys + nextpnr / GHDL synth) is a first-class target; validates the cocotb-first + open-source-sim priority.
- **Register map**: CMSIS-SVD primary, SystemRDL secondary (EOQ-005).
- **MCP tools**: both primitive + higher-intent layers shipped (EOQ-006).
- **CSP citation explicit** for INV-SOS-F (EOQ-007).
- **No preemption in v1**, documented (EOQ-008). Cooperative-only is the v1 design; preemption is its own potential future initiative.
- **Kernel chart stays as bench fixture** (EOQ-009).
- **Article = stand-alone artifact** (EOQ-010); docs don't cite article.

**New invariant added** (§3): **INV-SOS-H — Vector-to-chart traceability.** Every emitted vector carries metadata naming the chart state/transition/invariant that generated it; failure messages render in chart vocabulary, not raw RTL signals. The chart-level failure message is what makes the verification artifact part of the spec-as-source story.

**New EOQ raised** (§8): **EOQ-011-ROADMAP** — waveform-annotation review-artifact specifics. Resolves at SOS-08-G concepts-doc-authoring time.

**SOS-08 sub-phase restructure** (§4):
- SOS-08-A: HDL primitive library (Layer 0) — unchanged.
- SOS-08-B: HDL service composition (Layer 1) — unchanged.
- SOS-08-C: Chart → FSM emission — unchanged (cooperative-only per EOQ-008).
- **SOS-08-D**: cocotb + SVA bind file emission (PRIMARY vector path).
- **SOS-08-E**: SystemVerilog testbench + SVA bind file emission.
- **SOS-08-F**: UVM sequences only (plug-in, not full environment).
- **SOS-08-G**: Waveform + transaction-annotation emission (review artifact).
- **SOS-08-H**: Cooperative-only scheduling (v1 ratification).
- Formal-flow path (SymbiYosys / JasperGold) consumes SVA bind files; no separate emitter.
- Open-source synthesis path (Yosys + nextpnr / GHDL synth) named explicitly for the Lattice SoC target.

**Unblocks**: the SOS-07 ratification cycle (rename + charter expansion + INV adds + SOS-00 §15 amendment). The 10 resolved EOQs are sufficient to write a SOS-07-CONCEPTS.md draft; EOQ-011 lives downstream in SOS-08-G.

Status: 🟢 **EOQ-resolved; SOS-07 cycle unblocked**. Per-phase concept docs (SOS-07, SOS-08-*, SOS-09, SOS-10, SOS-11, SOS-12, SOS-13) follow per their own ratification cycles.
