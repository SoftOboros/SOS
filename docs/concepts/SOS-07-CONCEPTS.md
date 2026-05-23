# SOS-07 — Statechart Orchestration System (rename + cross-phase invariants)

**Status:** 🟢 ratified 2026-05-23. Normative.

## 0. Authority policy

This phase doc ratifies the rename of the SOS initiative from *Statechart-Orchestrated Scheduler* to **Statechart Orchestration System**, and promotes the cross-phase invariants and AuthorityRelationship matrix from informative roadmap text (`SOS-ROADMAP-07-PLUS.md`) to normative phase content. The acronym `SOS` is load-bearing across the existing phase-doc family (`SOS-00` through `SOS-06`) and remains unchanged.

Per the parent CLAUDE.md "Spec-Before-Code Planning Discipline":

- **Normative** sections of this doc: §3 glossary, §4 source-of-truth map, §5 frozen decisions, §6 cross-phase invariants, §7 standards integration matrix, §8 bootstrap-vs-general framing, §12 acceptance checklist.
- **Informative** sections: §1 purpose, §2 problem statement, §11 non-goals, §15 change log.
- All keywords MUST, MUST NOT, SHALL, SHOULD, SHOULD NOT, MAY are interpreted per RFC 2119 / RFC 8174 when capitalised.

This doc cites the [`SOS-ROADMAP-07-PLUS.md`](./SOS-ROADMAP-07-PLUS.md) roadmap as the source of the consensus the EOQs converged on. The roadmap stays as informative reference; this doc is the load-bearing artifact.

## 1. Purpose

To make the SOS initiative's expanded scope a first-class spec object so that subsequent phases (SOS-08 HDL backend, SOS-09 hardware/software membrane, SOS-10 multi-language orchestrator, SOS-11 MCP-mediated chart editing, SOS-12 recursive chart dispatch, SOS-13 verified-codegen Rust position) can be authored against a stable cross-phase substrate rather than re-arguing the rename, the cross-phase invariants, or the standards-integration posture per phase.

In short: SOS-07 retires "the rename + invariants are open questions" as a recurring blocker.

## 2. Problem statement

Five facts produced by SOS-00 through SOS-06 + the bench validation + the article work together to motivate this phase:

1. **The chart is the only artifact that survives every translation step.** Through `scjson` round-trip, through bounded-reachability vector emission, through both port-language emissions, through bench validation. Both M7 ports earn `CanonicalReplacement` verdict per SOS-06 §5.2 (d).

2. **The bounded-vector deliverable inverts the usual TDD trust direction.** Tests are no longer authored examples; they are exhaustive vector sets derived from the chart's reachability bound. The chart is the spec; the vectors are the contract; both implementations are views.

3. **The "Scheduler" name was always too narrow.** The kernel was the proving ground; the methodology that emerged is not kernel-specific. The natural rename is *Statechart Orchestration System*.

4. **iState (Infinity State) is the authoring surface; SCXML is the canonical artifact.** EOQ-008 from `SOS-06-A-EVALUATION.md` resolved conditionally: SCXML stays canonical IFF scjson round-trips preserve all iState "other attributes" extensions, which is empirically true today and validated in the round-trip pipeline.

5. **The hardware/software membrane is the natural next target.** RTOS primitives (mutex, semaphore, mailbox, event flag, timer) and HDL synchronization primitives (arbiter, credit counter, async FIFO, strobe-and-latch, rate generator) are isomorphic — both solve "N requesters, M < N resources, fair ordering, no corruption". One declarative spec language compiling to both sides is the cleanest demonstration of the methodology.

These facts, in combination, exceed what the original "Statechart-Orchestrated Scheduler" name could carry. SOS-07 retires the narrow name.

## 3. Canonical glossary

These terms are normative across SOS-07+. Authority relationships per the seven-value `AuthorityRelationship` enum from parent CLAUDE.md are recorded in §7.

| Term | Definition |
|---|---|
| **Statechart Orchestration System (SOS)** | The methodology + tooling stack whose canonical form is SCXML, whose authoring surface is iState, and whose targets include any language or hardware backend that can host a generated FSM. SOS is what is being built across all SOS-NN phases. |
| **bootstrap kernel chart** | `rtos_kernel.scxml` — the v1 demonstration that the methodology survives a non-toy workload through full bench validation. Reframed by this phase as "one chart among future many", not "the chart". |
| **chart-as-source** | The discipline that the chart (in SCXML form, on disk) is the sole upstream spec for every target SOS produces. Hand-edits to generated artifacts are prohibited as a process matter and rejected as a compile-error matter where possible. |
| **vectors-as-deliverable** | The discipline that bounded reachability emits exhaustive vector sets at every layer of the chart hierarchy, and that those vectors ship with the IP as part of the integration contract. The vectors *are* the contract in runnable form. |
| **Infinity State (iState)** | The authoring surface (graphical chart editor, persistent document store, MCP-tool host) that owns the developer-facing chart surface. The user never sees raw SCXML unless they explicitly request it; the chart lives in iState as a first-class artifact with its own version history and its own MCP tool surface. |
| **bootstrap-vs-general** | The reframing that distinguishes the kernel chart (proves the methodology on a non-toy workload) from future application charts (use the methodology against arbitrary domains). |
| **verified-codegen position** | The third position beyond default-safe Rust and default-unchecked C: the codegen MAY omit runtime checks whose obligation is discharged by the chart's bounds analysis, with every omission citing the discharging invariant. Auditable, not silent. |
| **AuthorityRelationship** | The seven-value enum per parent CLAUDE.md "Standards integration": `mirror`, `adapt`, `extend`, `compose`, `own`, `derive`, `represent`. Every external standard SOS touches declares its relationship; undeclared relationships read as `mirror` with no mutation rights. |

## 4. Source-of-truth map

For every concept the SOS-07+ phase family touches, **exactly one** doc is the canonical authority. Other docs reference; they do not redefine.

| Concept | Authority |
|---|---|
| Initiative name (Statechart Orchestration System) | **this doc** (§5.1) |
| Bootstrap kernel chart definition | `rtos_kernel.scxml` (the file itself) |
| Chart spec language semantics | SCXML 1.0 W3C Recommendation 2015 (external) |
| scjson AST shape | scjson project (`ops/packer/submodules/scjson/`, external) |
| iState extensions (`position_x`/`position_y`) | iState project (external) |
| ARMv7-M ISA / Cortex-M7 contract | **`SOS-00-CONCEPTS.md` §6** (local distillation) |
| Conformance vector framework | **`SOS-03-CONCEPTS.md`** (extended at SOS-08-D for HDL) |
| Codegen evaluation methodology | **`SOS-06-CONCEPTS.md`** (extended at SOS-08 for HDL) |
| Cross-phase invariants INV-SOS-A through H | **this doc** (§6) |
| AuthorityRelationship matrix | **this doc** (§7) |
| Bootstrap-vs-general framing | **this doc** (§8) |
| Phase scoping for SOS-08 through SOS-13 | `SOS-ROADMAP-07-PLUS.md` (informative); each individual `SOS-NN-CONCEPTS.md` (normative when ratified) |

## 5. Frozen decisions

### 5.1 Initiative name

**The initiative is named *Statechart Orchestration System*.** The acronym `SOS` is unchanged across the existing phase-doc family (`SOS-00` through `SOS-06`); the expansion changes only.

**Frozen enumeration registration policy** for the initiative-name field: **Standards Action**. Any future rename requires a §15 amendment to this doc and a ratification session (per parent CLAUDE.md frozen-enumeration policy: name encodes an invariant — the cross-phase-doc citation surface — so amendments need cross-phase review).

### 5.2 Charter

The Statechart Orchestration System is the methodology + tooling stack whose canonical form is SCXML, whose authoring surface is iState, and whose targets include any language or hardware backend that can host a generated FSM. The charter is intentionally domain-agnostic; the bootstrap kernel chart is one demonstration of the charter, not its definition.

### 5.3 Versioning

SOS continues at **v1**. EOQ-001-ROADMAP resolution: the rename does not warrant a major-version bump; previously-ratified content stays valid; the rename is recorded as a prose amendment on the existing phase docs. The bootstrap-vs-general distinction lives at the phase level (this doc and onwards), not the version axis.

## 6. Cross-phase invariants — INV-SOS-A through H

These eight invariants are **normative across every SOS-NN phase**, ratified through this phase doc. Future phases cite them by ID; future amendments to them require ratification through this doc's §15.

Frozen enumeration registration policy for the invariant set: **Standards Action**. Adding or modifying an INV-SOS-* invariant requires a §15 amendment here and cross-phase review.

### INV-SOS-A — Chart-as-source

Every domain SOS targets has the chart (in SCXML form, on disk) as its **sole** upstream spec. Hand-edits to generated artifacts are prohibited as a process matter; tooling makes them rejected as a compile-error matter where possible. This is the load-bearing discipline that makes the rest of the invariants meaningful.

### INV-SOS-B — Vectors-as-deliverable at every layer

Bounded reachability MUST emit exhaustive vector sets at the chart level. Hierarchical composition (charts-dispatching-charts; SOS-12) MUST preserve boundedness via per-layer contract enforcement; each layer's vectors test that layer's behaviour against its declared environment, never the joint Cartesian product. Vectors ship with the IP as part of the integration contract.

### INV-SOS-C — MCP as sole modification surface

Human-and-agent chart edits flow through MCP tools (SOS-11) that operate on the chart's semantic structure (`add_state`, `remove_transition`, `nest_region`, `extract_region_to_subchart`), never on raw SCXML text. The graphical viewer renders diffs in the same notation the developer authors.

### INV-SOS-D — iState authoring, SCXML canonical

EOQ-008 (`SOS-06-A-EVALUATION.md`) conditional resolution carries forward: iState is the authoring surface; SCXML on disk is the canonical artifact; scjson is the round-trip oracle that proves the iState↔SCXML extraction is lossless. INV-S1 (from SOS-00) stays intact at the artifact layer. Re-opening conditions are recorded in `SOS-06-A-EVALUATION.md` §8.

### INV-SOS-E — Explicit AuthorityRelationship

When SOS integrates an external standard (SCXML, VHDL, Verilog, SystemVerilog, SVA, UVM, cocotb, CMSIS-SVD, SystemRDL, AMQP, gRPC, MCP wire, etc.) the integrating phase doc declares the `AuthorityRelationship` (mirror / adapt / extend / compose / own / derive / represent) per parent CLAUDE.md. Undeclared relationships read as `mirror` with no mutation rights. The matrix is recorded in §7.

### INV-SOS-F — Bound composition

Joint reachability across hierarchically-composed charts MUST be computed as **per-layer × independence axes**, NOT as the Cartesian product. Orthogonal regions (SCXML `<parallel>`) are the natural independence axes; sequential composition uses contract-matching at the dispatch boundary. Per EOQ-007 resolution, this is the SOS-specific analogue of CSP (Communicating Sequential Processes); the algebraic detail lands in `SOS-12-CONCEPTS.md`.

### INV-SOS-G — Verified-codegen position

Generated code (Rust, C, VHDL, Verilog, anything else) MAY omit runtime checks whose obligation is discharged by the chart's bounds analysis, provided every elimination cites the discharging invariant. This is the "third position" beyond default-safe Rust and default-unchecked C — verified-by-construction omissions, made auditable by per-elimination invariant citations. Concretized at `SOS-13-CONCEPTS.md` for the Rust target.

### INV-SOS-H — Vector-to-chart traceability

Every emitted vector (cocotb, SV testbench, UVM sequence, waveform annotation, conformance JSONL) MUST carry metadata naming the chart state, transition, or invariant that generated it. Failure messages render in chart vocabulary: *"transition T42 in subchart `auth.connecting` produced a vector that violated invariant I7"* — never raw RTL signal traces alone, never raw event indices alone. The chart-level failure message is what makes the verification artifact part of the spec-as-source story; without it, the developer translates signal traces back to chart terms by hand, which reintroduces the documentation-drift failure mode the methodology was designed to prevent.

## 7. Standards integration matrix

Per INV-SOS-E. Frozen enumeration registration policy: **Specification Required** for adding new rows (a phase-owner walkthrough update is sufficient; no §15 amendment to this doc needed). Modifying an existing row's relationship requires a §15 amendment here.

| Concept | Upstream authority | Local relationship | Phase that declares it | Mutation rights |
|---|---|---|---|---|
| SCXML 1.0 | W3C Recommendation 2015 | **mirror** | SOS-00 §0 INV-S1 | none — locally |
| scjson AST | scjson project (BSD-1-Clause) | **adapt** | SOS-06-A | none — upstream owns |
| iState extensions | iState project | **extend** (`position_x`/`position_y` on `other_attributes`) | SOS-06 §15 Amd 005 EOQ-008 | iState owns the extensions; SOS preserves via scjson round-trip |
| ARMv7-M ISA / Cortex-M7 | ARM (proprietary docs) | **mirror** | SOS-00 §6 | none — SOS-00 §6 IS the local authority |
| FreeRTOS / POSIX vocabulary | open implementations | **mirror** | SOS-08-B (forthcoming) | none — names are vocabulary, not API |
| VHDL (IEEE 1076-2008) | IEEE Standard | **derive** | SOS-08 (forthcoming) | none — emit conformant subset |
| Verilog / SystemVerilog (IEEE 1800-2017) | IEEE Standard | **derive** | SOS-08 (forthcoming) | same |
| SVA (SystemVerilog Assertions) | IEEE 1800-2017 subset | **derive** | SOS-08-D (forthcoming) | same |
| UVM | Accellera | **derive** (sequences only at v1; not full env) | SOS-08-F (forthcoming) | same |
| cocotb | open project | **derive** | SOS-08-D (forthcoming) | same |
| GTKWave / Surfer waveform viewers | open projects | **represent** | SOS-08-G (forthcoming) | none |
| CMSIS-SVD | ARM (vendor-neutral) | **derive** (primary register-map format) | SOS-09 (forthcoming) | none — emit valid SVD |
| SystemRDL | Accellera | **derive** (secondary register-map format) | SOS-09 (forthcoming) | same |
| AMQP 1.0 | OASIS | **compose** | SOS-10 (forthcoming) | none — AMQP is one medium among many |
| gRPC | open project | **compose** | SOS-10 (forthcoming) | same |
| MCP (Model Context Protocol) | Anthropic-led, open | **adapt** | SOS-11 (forthcoming) | none — MCP wire is upstream |
| CSP (Communicating Sequential Processes) | Hoare 1978 + ISO | **compose** (cite for bound-composition lineage) | SOS-12 (forthcoming) | none — citation only |

This matrix is the defence against the failure mode CLAUDE.md names: *"we copied it into our schema, therefore we own it."* Every external standard's relationship is explicit; no silent ownership creep.

## 8. Bootstrap-vs-general framing

The kernel chart `rtos_kernel.scxml` proves the methodology end-to-end:

- Authored as SCXML, with iState layout extensions per EOQ-008.
- Bench-validated 6/6 SOS-03 conformance on STM32H747I-DISCO.
- Two reference ports (Rust, C) at `CanonicalReplacement` verdict.
- Codegen tool produces both ports byte-equivalent to the bench-validated hand-written reference.
- Bounded-vector emission covers the full chart at the seed-suite level.
- DWT cycle-count instrumentation in both ports, `MacrostepCycleCount` measured.

Per **EOQ-009-ROADMAP** resolution: the kernel chart continues to bench-validate against the SOS-03 conformance suite on every toolchain release. It is the **fixture** that proves the methodology survives a real (non-toy) workload through full bench validation.

The bootstrap-vs-general distinction:

| Aspect | Bootstrap (kernel chart) | General (future application charts) |
|---|---|---|
| Scope | One RTOS kernel | Any chart-driven system |
| Authority | SOS-00 INV-S1 (the chart is the spec) | Same |
| Tooling | Same codegen tool, same conformance suite | Same |
| Validation | Bench-validated 6/6 on the disco-analyzer | Per-chart validation surface (varies) |
| Role | Proof-of-methodology | Application of methodology |

Future application charts inherit the methodology + tooling from the bootstrap; they do not re-derive it. The bootstrap is the v1 demonstration; the methodology is what generalises.

## 9. Frozen enumerations from SOS-07

This phase freezes two enumerations:

### 9.1 Cross-phase invariants

`{ INV-SOS-A, INV-SOS-B, INV-SOS-C, INV-SOS-D, INV-SOS-E, INV-SOS-F, INV-SOS-G, INV-SOS-H }`

Registration policy: **Standards Action**.

### 9.2 AuthorityRelationship values applied in §7

`{ mirror, adapt, extend, compose, own, derive, represent }` — as defined by parent CLAUDE.md "Standards integration: authority boundary declarations". Per-row applications are per §7.

Registration policy: **Specification Required** (rows can be added by phase-owner walkthrough); **Standards Action** (modifying an existing row's relationship value requires §15 amendment to this doc).

## 10. Reconciliation decisions vs adjacent repo primitives

### vs. SOS-00 INV-S1 ("the .scxml IS the spec")

INV-SOS-A (chart-as-source) **adapts** INV-S1 with: "across all SOS targets, not just M7 ports". The two are mutually consistent; INV-SOS-A extends the territorial reach without modifying the canonical-artifact claim. A SOS-00 §15 amendment records this extension in dated form (see this drop's amendments to SOS-00).

### vs. SOS-06-A-EVALUATION EOQ-008 (iState↔SCXML canonicality)

INV-SOS-D **mirrors** EOQ-008's conditional resolution: SCXML canonical IFF scjson round-trips preserve all iState extensions. INV-SOS-D names this as a cross-phase invariant; EOQ-008 retains its conditional-resolution detail (re-opening conditions, scjson trust basis) in `SOS-06-A-EVALUATION.md` §6.

### vs. parent CLAUDE.md "Standards integration"

§7 of this doc **mirrors** parent CLAUDE.md's seven-value `AuthorityRelationship` enum verbatim; no SOS-specific extension. Per-row applications in §7 are local; the enum itself is upstream.

### vs. SOS-06 §15 Amendments 001 through 005

The bench-validated `CanonicalReplacement` verdict + the `MacrostepCycleCount` metric closure (Amendment 005) provide the empirical grounding INV-SOS-G stands on. INV-SOS-G generalises the per-target finding ("verified Rust occupies a third position") to a cross-phase invariant; SOS-13 will make the concrete claim per-target.

## 11. Non-goals

This phase does NOT:

- Modify any existing phase doc's normative content. The §15 amendments on SOS-00 through SOS-06 (in this drop) cite this doc as the rename's authoritative artifact; they do not re-author the normative sections.
- Author SOS-08 through SOS-13 normative content. Each per-phase concept doc is its own ratification cycle.
- Change the codegen tool's behaviour. SOS-07 is a documentation + invariant-promotion phase only.
- Re-validate the bench. The bench-validated state at SOS-06 §15 Amendment 005 (both targets at `CanonicalReplacement`, 6/6 PASS, `MacrostepCycleCount` measured) carries forward unchanged.
- Modify any code in `tools/sos-codegen/`, `ports/m7-rust/`, `ports/m7-c/`, `sim/sos-sim/`, or `conformance/vectors/`.

## 12. Acceptance checklist

A conforming SOS-07 ratification satisfies all of:

- (a) ✅ `docs/concepts/SOS-07-CONCEPTS.md` exists and follows the per-phase concept-doc shape (§0 authority, §3 glossary, §4 source-of-truth map, §5 frozen decisions, §6 invariants, §7 standards integration matrix, §12 acceptance, §15 change log).
- (b) ✅ INV-SOS-A through H ratified as normative cross-phase invariants in §6.
- (c) ✅ AuthorityRelationship matrix in §7 covers every external standard the SOS-07+ phase family integrates.
- (d) ✅ Bootstrap-vs-general framing in §8 records the relationship between `rtos_kernel.scxml` and future application charts.
- (e) ✅ SOS-00 §15 receives a dated amendment citing SOS-07 as the rename's authoritative artifact.
- (f) ✅ Top-level `README.md`, `AGENTS.md`, `CLAUDE.md` reflect the "Statechart Orchestration System" wording.
- (g) ✅ SOS-01 through SOS-06 each receive a §15 amendment citing SOS-07 + recording the bootstrap-reframe context.
- (h) ✅ `SOS-ROADMAP-07-PLUS.md` marked with SOS-07 ratification status.

## 13. Files cited

| Path | Role |
|---|---|
| `docs/concepts/SOS-ROADMAP-07-PLUS.md` | Informative roadmap (this doc is the normative artifact the roadmap pointed at). |
| `docs/concepts/SOS-00-CONCEPTS.md` | Foundational concepts; receives §15 amendment in this drop. |
| `docs/concepts/SOS-01-CONCEPTS.md` through `SOS-06-CONCEPTS.md` | Existing phase docs; each receives small §15 amendment in this drop. |
| `docs/concepts/SOS-06-A-EVALUATION.md` | EOQ-008 conditional resolution carried into INV-SOS-D. |
| `rtos_kernel.scxml` | Bootstrap kernel chart; stays bench-validated as the v1 demonstration. |
| Parent `CLAUDE.md` | Spec-Before-Code discipline; AuthorityRelationship enum (§7 mirrors). |
| `README.md`, `AGENTS.md`, `CLAUDE.md` (SOS subrepo) | Top-level docs; updated to "Statechart Orchestration System" wording. |

## 14. Unblocks

This phase's ratification unblocks the per-phase concept-doc cycles for:

- **SOS-08** (HDL backend: VHDL-2008 + SystemVerilog-2017, primitives + services + chart→FSM + vector emission + cooperative-only scheduling).
- **SOS-09** (hardware/software membrane via CMSIS-SVD primary + SystemRDL secondary).
- **SOS-10** (multi-language orchestrator at same-host scope; Lattice SoC target inbound).
- **SOS-11** (MCP-mediated chart editing with primitive + higher-intent tool layers).
- **SOS-12** (recursive chart dispatch; CSP citation; per-layer contract enforcement).
- **SOS-13** (verified-codegen Rust position; `verified-strip` profile emitting `*_unchecked` justified by chart-discharged obligations).

Each per-phase cycle proceeds independently and on its own ratification schedule.

## 15. Change log

### 2026-05-23 — Ratified (Ira)

- Authored `SOS-07-CONCEPTS.md` per the Spec-Before-Code discipline.
- Renamed the initiative: *Statechart-Orchestrated Scheduler* → **Statechart Orchestration System**. Acronym `SOS` unchanged.
- Ratified INV-SOS-A through H as cross-phase invariants.
- Ratified AuthorityRelationship matrix for all external standards the SOS-07+ phase family integrates.
- Recorded bootstrap-vs-general framing: kernel chart is the v1 demonstration; methodology generalises.
- Cited `SOS-ROADMAP-07-PLUS.md` as the informative source the EOQ batch resolution lived in.
- Co-landed with §15 amendments on SOS-00 through SOS-06 (in this drop's commit) and rename-pass updates on README / AGENTS / CLAUDE.

Status: 🟢 ratified; subsequent SOS-NN phase ratifications proceed independently.
