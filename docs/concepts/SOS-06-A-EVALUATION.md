# SOS-06-A — Codegen Toolchain Evaluation (Methodology Pre-Application)

**Status:** 🟡 drafted 2026-05-21. Informative evaluation artifact; not a §15 amendment to [SOS-06-CONCEPTS](./SOS-06-CONCEPTS.md). This file surveys candidate codegen toolchains against the ratified SOS-06 methodology and produces a recommendation for the user to ratify. The eventual `SOS-06-A` §15 amendment to SOS-06-CONCEPTS will record the *results* of an evaluation *run* (per [SOS-06 §6, §15, INV-S-CG-6](./SOS-06-CONCEPTS.md)); this document is one rung earlier in the staircase — it picks which toolchain(s) to *run* first.

> 🛑 **No toolchain is selected by this document.** Per [SOS-06 §0, §10, INV-S-CG-10](./SOS-06-CONCEPTS.md), naming the canonical toolchain is the user's call. This evaluation lists the realistic candidates that exist as of 2026-05-21, scores them informally against the [SOS-06 §6 metrics](./SOS-06-CONCEPTS.md) on shape-only grounds (no firmware was generated), and recommends a primary + a fallback. The user picks.

## 0. Authority & scope

This document is **informative**. It does not edit any normative section of any phase doc. It is the working-out artifact produced before the eventual `SOS-06-A` §15 amendment can be authored.

The SOS-06 normative spec is [`SOS-06-CONCEPTS.md`](./SOS-06-CONCEPTS.md), ratified 2026-05-19. This file:

- **derives** its evaluation axes from [SOS-06 §5.1 `EvaluationMetric`](./SOS-06-CONCEPTS.md) and [SOS-06 §6.2 measurement procedures](./SOS-06-CONCEPTS.md);
- **derives** the verdict frame from [SOS-06 §5.2 `SuitabilityVerdict`](./SOS-06-CONCEPTS.md) and [§6.3 verdict procedure](./SOS-06-CONCEPTS.md);
- **derives** the pathway shape from [SOS-06 §6.1](./SOS-06-CONCEPTS.md);
- **honors** [SOS-06 INV-S-CG-0](./SOS-06-CONCEPTS.md) — no crawling of toolchain internals; surface inspection only.

Open questions raised here use the `EOQ-NNN-SOS-06-A` shape (one EOQ per outstanding decision the user must make before `SOS-06-A-1` implementation can begin). Per parent CLAUDE.md errata conventions, an EOQ is a stable handle: once assigned, its identifier never rebinds.

## 1. Purpose

Answer the question SOS-06-A asks: **which codegen toolchain (or set of toolchains) is the right first target for an evaluation run?** The answer must be:

- **Real.** A toolchain that exists today, can be installed today, and can in principle consume `rtos_kernel.scxml` today (possibly with a frozen-input adapter).
- **Aligned with the SOS-06 pathway shape.** A toolchain whose output cannot be a `no_std`-clean Rust or C source tree per [SOS-06 §6.1](./SOS-06-CONCEPTS.md) is disqualified before scoring — no point measuring its `BinarySize` if its output cannot link on Cortex-M7.
- **Survivable through the [SOS-06 §6.2.7 Auditability checklist](./SOS-06-CONCEPTS.md).** A toolchain emitting binary-encoded state tables, opaque generated headers, or arbitrary-renamed identifiers fails [INV-S-CG-5](./SOS-06-CONCEPTS.md) at SOS-06 grade.

The evaluation does **not** produce a `SuitabilityVerdict` — that is reserved for the eventual `SOS-06-A` §15 amendment per [INV-S-CG-6](./SOS-06-CONCEPTS.md). It produces a *priority-ordered list of toolchains to evaluate*, with rationale.

## 2. Problem statement (evidence)

**Current state (2026-05-21):**

- SOS v1 concepts roadmap fully ratified (SOS-00 through SOS-06; see [`README.md`](./README.md)).
- Reference hand-written ports exist: `ports/m7-rust/sos-m7-rust/` (Rust, bench-validated 2026-05-21, 6/6 SOS-03 conformance vectors PASS) and `ports/m7-c/sos-m7-c/` (C, drafted; ratification on the C-baseline pending [SOS-05 ratification](./SOS-05-CONCEPTS.md)).
- The host simulator `sims/sos-sim/` exists as the byte-faithful trace producer and was the source of the hand-transliteration that seeded the M7-Rust port's `scripts.rs` and the M7-C port's `scripts.c`.
- The canonical input `rtos_kernel.scxml` is ~580 lines covering 4 parallel regions, 10 frozen `StateId` values, 18 frozen `ExternalEventName` values, and a ratified ECMAScript subset (12 permitted features per [SOS-01 §5.1](./SOS-01-CONCEPTS.md)).
- The chart author's stated intent (per [`docs/REFERENCE.md` § "Code-generation notes"](../REFERENCE.md)) is to drive the chart through "the SoftOboros SCXML compiler family". That family today is the `scjson` ecosystem (vendored at `ops/packer/submodules/scjson/` in the parent repo): a multi-language SCXML↔JSON converter + a Python execution engine + a Ruby execution engine + a JS/TS SCION harness. **It has no code generator** — it is an executor/converter family.

**The gap:** "SoftOboros SCXML compiler family" is named in `REFERENCE.md` but is, today, a *future capability* the chart author plans to develop on top of `scjson`. No `scjson-gen-c`, `scjson-gen-rust`, or equivalent crate ships from the family yet. Picking it as the SOS-06-A toolchain is a forward bet on capabilities to be authored. Picking an external toolchain (`scxmlcc`, `uscxml-transform`, `itemis CREATE`/YAKINDU, `QM`+QP/C, `sismic`) is a bet on existing capability whose alignment with SOS-06 must be verified.

**Why this matters now:** The SOS v1 roadmap is terminated. Maintaining two hand-written ports through every chart amendment (the [SOS-06 §2 problem statement](./SOS-06-CONCEPTS.md) 4–6x edit-burden multiplier) is the load-bearing cost SOS-06 was ratified to address. The longer the SOS-06-A run waits, the more drift accumulates between chart amendments and port amendments. A pragmatic first toolchain — even one that earns only `Coexist` — beats indefinite manual transliteration.

## 3. Candidate toolchain inventory

Each candidate is scored on the *prerequisites* an SOS-06 evaluation run would face: can it consume our chart, can it produce a tree of the shape [SOS-06 §6.1](./SOS-06-CONCEPTS.md) requires, what is its maintenance posture, what is its licence posture. The actual seven SOS-06 metrics are not measurable until a generated tree exists; this section establishes *which candidates are worth generating a tree from*.

### 3.1 `scjson`-family extension (proposed; not yet authored)

- **Identity:** `scjson` (vendored at `ops/packer/submodules/scjson/`, repo `https://github.com/softoboros/scjson`). Existing components: Python engine + tracer; Rust converter crate; Ruby engine; JS/TS SCION harness. **Codegen does not yet exist** — it would be a new sibling crate (e.g. `scjson-gen-c`, `scjson-gen-rust`) authored to consume `scjson.schema.json` documents and emit target-language source trees.

  **Update (2026-05-26, informative; not a scope change to SOS-06-A):** scjson 0.4.0 (Python + JavaScript bindings; submodule HEAD `74e83da`) has landed authoring-side primitives — `help_text: list[str]` per CONV-E (scjson commits `9008639` / `e1e3d1f`) and SCXML comment promotion → `help_text` per CONV-F (commits `096f7e3` / `afbb3ac`) — that the future `scjson-gen-c` / `scjson-gen-rust` family would naturally consume to generate doc-comments in emitted source: chart-author XML comments become emitted Rust `///` doc-comments and C `/** */` doc-comments by construction. This is a roadmap shape, not a v1 scope expansion. Verification across language bindings (Python + JS land in 0.4.0; the Rust binding remains non-existent), the validation pipeline (round-trip fidelity tests across all bindings), and the current `tools/sos-codegen/` template surface ALL need substantial work before this graduation could happen — explicit acknowledgment, not a promise. See `docs/concepts/SOS-ROADMAP-07-PLUS.md` §"scjson 0.4.0 feature integration (roadmap)" for the umbrella framing and `docs/concepts/SOS-09-CONCEPTS.md` §16 (2026-05-26 entry) for the cross-phase inventory.
- **Input language:** SCXML ↔ scjson round-trip; codegen consumes scjson AST. The chart is already valid against `scjson` per parent repo's normal validation pipeline.
- **Output language(s):** Rust + C are both feasible from the same AST; matches [SOS-06 §6.1](./SOS-06-CONCEPTS.md) targets exactly.
- **Footprint estimate:** Unknown — design choice. Author retains full control over the emit profile, which makes hitting [SOS-06 §6.2.7 Auditability](./SOS-06-CONCEPTS.md) and the 1.5x size bands straightforward by construction.
- **Maintenance status (2026-05-21):** Family actively maintained (scjson 0.3.3 at the pinned submodule SHA). The codegen sibling, however, must be authored — material engineering investment.
- **Licence:** BSD-1-Clause (Rust crate); permissive across the family.
- **Strengths:**
  - Native alignment with the SCXML feature subset SOS uses; no impedance mismatch on `<datamodel>`, `<script>`, or the 18 `ExternalEventName`s.
  - Author owns the emit profile → can target the exact [SOS-04 §6.1 / §6.3](./SOS-04-CONCEPTS.md) crate-layout / static-allocation shape, making [§6.2.7 Auditability](./SOS-06-CONCEPTS.md) reviewable by construction.
  - Same author/maintainer surface as the chart — chart amendments propagate naturally.
  - The `scjson` Python engine already produces deterministic JSONL traces; a codegen output's emitted trace can be diffed against that engine's output to bootstrap [§6.2.1 FunctionalConformance](./SOS-06-CONCEPTS.md).
- **Weaknesses:**
  - **Does not exist today.** SOS-06-A would gate on authoring this. Calendar cost: weeks-to-months depending on scope.
  - Single-vendor; risk of bus-factor.
  - No external corpus of generated examples to inspect before committing.
- **SOS-06 expectation:** explicitly named as a candidate in [`REFERENCE.md`](../REFERENCE.md) and acknowledged in [SOS-06 §0 / §2 / INV-S-CG-10](./SOS-06-CONCEPTS.md).

### 3.2 `scxmlcc` (jp-embedded, C++ target)

- **Identity:** [`jp-embedded/scxmlcc`](https://github.com/jp-embedded/scxmlcc), "SCXML state machine to C++ compiler". Generated state machines have no external deps, use STL only.
- **Input language:** SCXML 1.0 (subset). Unknown whether the SOS chart's parallel-region + ECMAScript `<script>` blocks lie inside the supported subset; needs probing.
- **Output language(s):** **C++ only.** Not C. Not Rust.
- **Footprint estimate:** Targets embedded but uses STL; STL-on-Cortex-M7 is feasible (the chart-emitter could be `no_std`-equivalent via `-fno-exceptions -fno-rtti`) but is an additional configuration burden.
- **Maintenance status (2026-05-21):** GPL v3. Active issues thread 2018–2020; master branch tagged "stable but not version-tagged". Posture: maintained, mature, not high-velocity.
- **Licence:** **GPL v3.** This is a hard problem for [SOS-04 §12](./SOS-04-CONCEPTS.md) downstream consumers — generated GPL-v3 firmware would impose copyleft on the SOS Cortex-M7 firmware, contradicting the SOS subrepo's licensing posture (MIT-licensed per `LICENSE.md`, downstream-friendly to match the `scjson` BSD-1-Clause posture).
- **Strengths:**
  - Existing, working, well-known SCXML→native-code compiler.
  - Active issue tracker (signal that it would respond to a SOS adoption push if needed).
  - "No external deps" matches [SOS-06 INV-S-CG-9](./SOS-06-CONCEPTS.md) / [SOS-04 §9](./SOS-04-CONCEPTS.md) static-only posture.
- **Weaknesses:**
  - **Target-language mismatch.** SOS targets C and Rust per [SOS-04](./SOS-04-CONCEPTS.md) / [SOS-05](./SOS-05-CONCEPTS.md). C++ is neither — adopting `scxmlcc` would require either reframing SOS-05 as C++ (a [SOS-05 §15](./SOS-05-CONCEPTS.md) amendment) or wrapping C++ output in a C ABI shim (audit-hostile per [§6.2.7](./SOS-06-CONCEPTS.md)).
  - **Licence incompatibility risk** as noted.
  - **Auditability** likely poor — generated state-pattern C++ with template-heavy dispatch maps badly to the SOS-04 `pick_next()` + bitmap idiom; the [§6.2.7 question 4 (NVIC priorities)](./SOS-06-CONCEPTS.md) and question 6 (per-region invariants) checks would require manual instrumentation of generated C++.
- **SOS-06 expectation:** named indirectly in [SOS-06 §4.1](./SOS-06-CONCEPTS.md) negative listing ("Other prior-art SCXML compilers"); not a dependency, but a candidate.

### 3.3 `uscxml-transform` (tklab-tud, ANSI-C target)

- **Identity:** [`tklab-tud/uscxml`](https://github.com/tklab-tud/uscxml), part of the uSCXML family. `uscxml-transform -tc -i input.scxml -o output.c` produces ANSI-C.
- **Input language:** SCXML 1.0. Has the broadest documented coverage of the spec across these candidates.
- **Output language(s):** **ANSI-C** (also VHDL — out of scope here). No Rust.
- **Footprint estimate:** Targets embedded explicitly; uSCXML has a documented "SCXML on an ATMega328" deployment, which is more constrained than CM7 — so ANSI-C output footprint should fit comfortably.
- **Maintenance status (2026-05-21):** No tagged releases; "build from source". Multiple forks exist (tklab-tud, alexzhornyak, parora1701). Posture: research-grade, not high-velocity, transferable expertise.
- **Licence:** Simplified BSD — compatible with SOS posture.
- **Strengths:**
  - C target is one of the SOS-06 targets per [SOS-05](./SOS-05-CONCEPTS.md).
  - ATmega328-class deployments prove output fits in <32 KiB flash — well inside the 1.5x of any plausible SOS-05 baseline.
  - BSD-licensed → no copyleft surface.
  - Has the most complete W3C SCXML coverage of any tool here (relevant if SOS chart amendments later expand the ECMAScript subset).
- **Weaknesses:**
  - **C-only.** Rust target would still need either `scxmlcc`-style C output wrapped in a Rust `extern "C"` veneer (audit-hostile per [§6.2.7](./SOS-06-CONCEPTS.md) question 2 — "find the chart's `waiters_insert` by name in the generated code") or a separate Rust-target toolchain. Adopting `uscxml-transform` would split the SOS-06 evaluation into two runs against two toolchains.
  - **Generated-code shape unknown.** No public corpus of generated firmware to audit. Auditability is a hard "must measure" — could be excellent (per-state dispatch tables, readable) or poor (transition-table arrays, opaque).
  - **No tagged releases** complicates [§6.4 baseline pinning](./SOS-06-CONCEPTS.md) — pinning to a git SHA is mechanically possible but reflects upstream's research-grade posture.
  - **Researcher tool**, not production toolchain — bug-response cadence may not match SOS amendment cadence.
- **SOS-06 expectation:** named in [SOS-06 §4.1](./SOS-06-CONCEPTS.md) negative listing as prior art; not a dependency.

### 3.4 `itemis CREATE` (formerly YAKINDU Statechart Tools), C target

- **Identity:** Commercial graphical statechart tool with multi-target codegen (C, C++, Java, Python, Swift, TypeScript). SCXML import documented; native model is YAKINDU's own statechart DSL.
- **Input language:** SCXML *import* — converts to internal model. The conversion may not be lossless for our chart's specifics (parallel regions + `<script>` blocks with the [SOS-01 §5.1 ECMAScript subset](./SOS-01-CONCEPTS.md)).
- **Output language(s):** C, C++, Java, Python, Swift, TypeScript. Rust is **not** a target.
- **Footprint estimate:** Production tool; output is generally compact and idiomatic. Plain-code-by-default emit profile favors auditability.
- **Maintenance status (2026-05-21):** Commercial product, actively maintained (itemis CREATE replaced YAKINDU branding c. 2020). Pricing for commercial use applies; "Standard" tier sometimes free for individuals/community use.
- **Licence:** **Proprietary** for the tool itself; generated code license depends on tier and use.
- **Strengths:**
  - Production-grade tool with explicit C-codegen story including custom-code integration (matches our need for the [SOS-00 §6 M7 primitive bindings](./SOS-00-CONCEPTS.md) to be invocable from generated code).
  - SCTUnit testing framework — could parallel the [SOS-03 conformance vector](./SOS-03-CONCEPTS.md) suite.
  - Plain-code-by-default → strong auditability posture.
- **Weaknesses:**
  - **SCXML-as-import, not native.** The internal model is YAKINDU's; the chart-as-SCXML becomes a derived artifact. This inverts [SOS-00 §0 INV-S1](./SOS-00-CONCEPTS.md) (the .scxml is the spec) — chart amendments would land in YAKINDU's DSL, with SCXML as the export. Hard sell against the SOS-00 source-of-truth posture.
  - **Proprietary.** The eventual `SOS-06-A` amendment recording a commercial-vendor toolchain identifier would create a long-term dependency on that vendor's release cadence — undesirable for an MIT-licensed subrepo whose downstream consumers expect open tooling.
  - **No Rust target.** Same split-the-evaluation problem as `uscxml-transform`.
  - **GUI-centric workflow** clashes with the SOS subrepo's text-first, git-native, spec-before-code posture.
- **SOS-06 expectation:** named indirectly in [SOS-06 §4.1](./SOS-06-CONCEPTS.md) ("Statecharts.io" generalization); not a dependency.

### 3.5 `QM` + QP/C (Quantum Leaps)

- **Identity:** QM is the graphical modeler; QP/C is the runtime framework. Generates production-grade C from UML statecharts. State-machine.com / `QuantumLeaps/qm` on GitHub.
- **Input language:** **UML hierarchical state machines (proprietary `.qm` model file), not SCXML.** No documented SCXML import.
- **Output language(s):** **C and C++.** No Rust. Tightly coupled to the QP/C framework (the generated code requires QP/C runtime objects — `QActive`, event queues, etc.).
- **Footprint estimate:** Cortex-M target proven; QP/C is production code on dozens of embedded products. Footprint is well-characterized but includes the QP/C runtime itself, which is a separate kernel (event-driven AO model) from SOS.
- **Maintenance status (2026-05-21):** Active commercial development; QM is freeware (not open source); QP/C is GPL with commercial licensing.
- **Licence:** **Dual-license (GPL or commercial)** for QP/C; QM is freeware.
- **Strengths:**
  - Production-grade output. Real embedded shipments. Auditability is excellent (forward-engineering posture per Quantum Leaps doctrine: "you should not edit the generated code, because your changes will be lost when re-generated").
  - Code is generally readable and traceable to model.
- **Weaknesses:**
  - **Not SCXML.** Would require a converter from SCXML → `.qm`, which does not exist. This is more engineering than authoring an scjson codegen sibling would be.
  - **Embeds a competing kernel.** QP/C's active-object/event-queue model is a different RTOS abstraction than SOS's priority-based preemptive model. The generated code would presume QP/C primitives, not the [SOS-00 §6](./SOS-00-CONCEPTS.md) M7 primitives. Adopting QM means abandoning the SOS kernel model — not adopting SOS's codegen pathway.
  - **No Rust target.**
- **SOS-06 expectation:** out-of-frame. Useful as a comparison reference for "what does professional embedded statechart codegen look like" but not a SOS-06-A candidate.

### 3.6 `sismic` (Python interpreter), reference engine only

- **Identity:** [`AlexandreDecan/sismic`](https://github.com/AlexandreDecan/sismic), Python statechart interpreter. Mature, well-documented.
- **Input language:** SCXML 1.0 + YAML statechart format. Python-as-action-language is the default evaluator.
- **Output language(s):** **None — it is an interpreter, not a code generator.** Useful as a reference oracle alongside the `sos-sim` host simulator, but does not produce a `no_std` source tree.
- **Footprint estimate:** N/A — Python runtime.
- **Maintenance status (2026-05-21):** Active; v1.6.x current.
- **Licence:** LGPL-3.
- **Strengths:**
  - Mature reference implementation for cross-checking [SOS-02 §7 trace format](./SOS-02-CONCEPTS.md) semantics (a useful supplementary oracle if disagreements with `sos-sim` arise during codegen evaluation).
- **Weaknesses:**
  - **Not a codegen toolchain.** Disqualified at [SOS-06 §6.1 pathway-shape](./SOS-06-CONCEPTS.md) gate.
- **SOS-06 expectation:** mentioned in [SOS-06 §4.1 / §10](./SOS-06-CONCEPTS.md) negative listing as prior art.

### 3.7 LLM-driven transpilation (proposed; methodology candidate, not a tool)

- **Identity:** Use a large language model (e.g. Claude Opus 4.7) under structured prompting to transliterate `rtos_kernel.scxml` into the [SOS-04 §6](./SOS-04-CONCEPTS.md) crate layout. The "toolchain" is the prompt + the LLM + a deterministic post-processor.
- **Input language:** SCXML 1.0 (LLM ingests directly).
- **Output language(s):** Rust + C — both within native LLM capability.
- **Footprint estimate:** Indistinguishable from hand-written. The LLM emits idiomatic code by default; auditability is *the LLM's strongest axis*.
- **Maintenance status (2026-05-21):** LLM tooling is on a months-not-years cadence; the underlying model versions tick faster than SOS amendments. Toolchain "stability" is unconventional — the version pin is on the model identifier + the prompt SHA.
- **Licence:** Output is user-owned per LLM vendor terms (e.g. Anthropic, OpenAI commercial-use terms). Tool itself is hosted-service.
- **Strengths:**
  - **Auditability is the strongest of any candidate by construction** — the LLM emits human-readable code with the same idioms a human would write. The [§6.2.7 seven-question checklist](./SOS-06-CONCEPTS.md) is in-distribution behaviour for the LLM.
  - Rust and C output from the same input — single-evaluation-run-pair feasible.
  - No tool installation burden; can be invoked from any agent harness.
  - Tracks the *intent* of the chart, not just the syntax — the [SOS-06 §6.2.7 question 7 (commentary preservation)](./SOS-06-CONCEPTS.md) is trivially passed.
- **Weaknesses:**
  - **Determinism.** The same prompt + chart may yield byte-different outputs across runs. [SOS-06 §6.4](./SOS-06-CONCEPTS.md) baseline pinning records the *generated-tree* SHA, so a single run is pinnable, but re-runs are not reproducible. [§6.5 (b)](./SOS-06-CONCEPTS.md) (toolchain version bump) re-evaluation cadence triggers on every model bump — which may be quarterly.
  - **No mechanical relationship between SCXML edit and generated diff.** A one-line chart amendment may yield arbitrarily distributed diff regions; [§6.5 (a)](./SOS-06-CONCEPTS.md) re-evaluation is forced more aggressively than with a deterministic toolchain.
  - **Validation cost.** Every chart amendment requires full [SOS-03 vector suite](./SOS-03-CONCEPTS.md) re-run because behavioural drift is plausible.
  - **Doesn't really replace manual transliteration** — it *industrializes* it. Useful tactically; questionable as "the science SOS is proving" per [SOS-00 §2 point 3](./SOS-00-CONCEPTS.md).
- **SOS-06 expectation:** mentioned conceptually in [SOS-06 §0](./SOS-06-CONCEPTS.md) ("an LLM-driven transpiler") as a candidate; not a dependency.

### 3.8 Hand-written `lxml`+template walker (DIY)

- **Identity:** Author a SOS-specific codegen in Python (using `lxml`) or Rust (using `xmltree`/`roxmltree`) that walks `rtos_kernel.scxml`, applies SOS-aware templates, and emits Rust + C source. ~1k–3k LOC depending on template complexity.
- **Input language:** SCXML 1.0, narrowly the [SOS-01 §5.3 / §5.4](./SOS-01-CONCEPTS.md) vocabulary — toolchain only needs to handle what `rtos_kernel.scxml` uses, not the whole spec.
- **Output language(s):** Rust + C; same author controls both emit profiles.
- **Footprint estimate:** Full control — can target the exact [SOS-04 §6.3](./SOS-04-CONCEPTS.md) static-allocation shape and [SOS-04 §6.4](./SOS-04-CONCEPTS.md) PendSV body.
- **Maintenance status (2026-05-21):** N/A — does not exist.
- **Licence:** BSD/MIT under SOS subrepo posture.
- **Strengths:**
  - Author-owned. No external version bumps. No vendor risk.
  - Targets the SOS chart's specific subset, not all of SCXML — implementation surface is much smaller than a general-purpose tool.
  - Trivially passes [§6.2.7 Auditability](./SOS-06-CONCEPTS.md) because the templates are hand-authored to match the [SOS-04](./SOS-04-CONCEPTS.md) / [SOS-05](./SOS-05-CONCEPTS.md) idiom.
  - Establishes the baseline that `scjson-gen-*` would later subsume — code authored here is not wasted if SOS later adopts an scjson-family codegen (it migrates).
- **Weaknesses:**
  - **Authoring cost.** Days-to-weeks, not free.
  - **Single-purpose tool** — not a reusable contribution to the broader SCXML ecosystem.
  - **Mirrors the chart structure too literally** risks failing the "science we're proving" test — generation that is essentially a templated transliteration is not categorically different from hand-transliteration.

## 4. Comparison matrix

Columns derived from [SOS-06 §5.1 `EvaluationMetric`](./SOS-06-CONCEPTS.md) (severity in parens) and [§6.1 pathway-shape](./SOS-06-CONCEPTS.md). Scores at the *prerequisite* level — can the toolchain plausibly reach `Pass` / `Within 1.5x` / etc. once exercised. None of these are measured values; they are alignment estimates.

| Toolchain | Targets Rust? | Targets C? | Input shape | Licence-OK? | Maint. posture | Functional Conformance (Blocker) | Binary Size (Concern) | RAM Footprint (Concern) | Macrostep Cycles (Concern) | Build Time (Info) | Source LOC (Info) | Auditability (Concern) | SOS-06 §6.1 pathway-shape OK? |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 3.1 `scjson` ext (proposed) | Yes | Yes | SCXML native | BSD | Family active; codegen TBA | Achievable | Author-controlled | Author-controlled | Author-controlled | Likely fast | Author-controlled | Strong (designed for it) | Yes by design |
| 3.2 `scxmlcc` | No | No (C++ only) | SCXML | **GPL-3 risk** | 2018–2020 active | Plausible | Unknown | Unknown | Unknown | Moderate | Likely large | Moderate (template-heavy C++) | **No** (wrong target lang) |
| 3.3 `uscxml-transform` | No | Yes | SCXML | BSD | Research-grade; untagged | Plausible | Likely OK | Likely OK | Unknown | Slow (C++ build) | Unknown | Unknown | Partial (C only) |
| 3.4 itemis CREATE | No | Yes | SCXML import (lossy) | **Proprietary** | Commercial active | Plausible | Likely OK | Likely OK | Likely OK | Moderate | Compact | Strong | Partial (C only; SCXML not native) |
| 3.5 QM + QP/C | No | Yes (w/ QP/C) | **Not SCXML** | GPL/commercial | Commercial active | **N/A** (replaces kernel) | N/A | N/A | N/A | N/A | N/A | Strong (production) | **No** (different kernel model) |
| 3.6 `sismic` | No | No | SCXML/YAML | LGPL | Active | N/A (interpreter) | — | — | — | — | — | — | **No** (not codegen) |
| 3.7 LLM transpiler | Yes | Yes | SCXML | Vendor T&C | Months-cadence | Plausible (verify-by-vector) | Hand-written-equivalent | Hand-written-equivalent | Hand-written-equivalent | Trivial | Hand-written-equivalent | **Strongest** | Yes |
| 3.8 DIY `lxml`+templates | Yes | Yes | SCXML (SOS subset) | BSD | N/A (to be authored) | Achievable | Author-controlled | Author-controlled | Author-controlled | Fast | Author-controlled | Strong | Yes by design |

Key:
- "Author-controlled" = quality is a function of the emit profile; nothing structurally prevents passing [§6.2 thresholds](./SOS-06-CONCEPTS.md).
- "Plausible" = no known structural blocker, but unmeasured.
- "Unknown" = needs generated-tree inspection before any prediction is sound.
- "N/A" = candidate disqualified at the pathway-shape gate; further metrics meaningless.

### 4.1 First-pass shortlist (passes the pathway-shape gate)

After [SOS-06 §6.1](./SOS-06-CONCEPTS.md) filtering: 3.1 `scjson` extension, 3.3 `uscxml-transform` (C target only), 3.7 LLM transpiler, 3.8 DIY `lxml`+templates.

3.2 `scxmlcc` is filtered out on target-language grounds (C++ is neither C nor Rust per [SOS-04](./SOS-04-CONCEPTS.md) / [SOS-05](./SOS-05-CONCEPTS.md)).

3.4 itemis CREATE filters on (a) proprietary, (b) C-only, (c) inverts [SOS-00 §0 INV-S1](./SOS-00-CONCEPTS.md) source-of-truth.

3.5 QM filters on "not SCXML" + "embeds competing kernel".

3.6 `sismic` filters on "not codegen" — but is retained as a *supplementary functional oracle* should `sos-sim` disagree with another reference engine on a corner case.

## 5. Recommendation

### 5.1 Primary recommendation: 3.8 DIY `lxml`+templates → migrating to 3.1 `scjson` family extension once authored — **RATIFIED 2026-05-21 with iState as the SCXML generation surface**

**Rationale.** The SOS chart's input surface is narrowly scoped — [SOS-01 §5.1](./SOS-01-CONCEPTS.md) freezes a 12-feature ECMAScript subset; [§5.3](./SOS-01-CONCEPTS.md) freezes 18 event names; [§5.4](./SOS-01-CONCEPTS.md) freezes 10 state IDs. A general-purpose SCXML compiler must handle the entire SCXML 1.0 spec; SOS-06-A only needs to handle what `rtos_kernel.scxml` uses. A hand-authored ~1k–3k-LOC `lxml`-walker + Tera/Jinja-style template tree (~200 LOC of template per target language) is a tractable first deliverable. It hits the [§6.2.7 Auditability](./SOS-06-CONCEPTS.md) gates by construction (templates are written to match the [SOS-04 §6.3 / §6.4](./SOS-04-CONCEPTS.md) idiom), the [§6.2 size / RAM / cycles](./SOS-06-CONCEPTS.md) thresholds by construction (it emits the same shape the hand-written port uses), and the [§6.2.1 FunctionalConformance](./SOS-06-CONCEPTS.md) oracle is the single test it has to pass — which is the test we want the SOS-06 methodology measured against. The "to be subsumed by scjson family" framing keeps the DIY tool honest: it's the prototype that demonstrates feasibility and produces the first reference data table for the eventual `SOS-06-A` §15 amendment. When/if the scjson family extends to ship `scjson-gen-c` and `scjson-gen-rust`, the DIY tool's templates migrate (BSD-licenced on both sides, same author).

**Ratification note (2026-05-21).** User ratified scjson + templates as the codegen mechanism, *and* introduced **iState as the SCXML generation surface** upstream of scjson. The pipeline is:

```
iState document        — authoring surface, chart edits land here
  ↓ istate_get_xml / istate_codegen_*
rtos_kernel.scxml      — canonical artifact per SOS-00 INV-S1 (unchanged)
  ↓ scjson convert
scjson AST (JSON)
  ↓ templates (Tera/Jinja under tools/sos-codegen/)
ports/m7-rust/.../scripts.rs  (matches the bench-validated SOS-04 byte-faithful mirror)
ports/m7-c/.../scripts.c      (matches the bench-validated SOS-05 byte-faithful mirror)
```

See [EOQ-001-SOS-06-A](./SOS-06-A-EVALUATION.md#6-open-questions-eoq--errata-shaped-open-questions-for-sos-06-a-intake) for the resolution detail and [EOQ-008-SOS-06-A](./SOS-06-A-EVALUATION.md#6-open-questions-eoq--errata-shaped-open-questions-for-sos-06-a-intake) for the iState-vs-SCXML canonicality reconciliation (default (a): iState authors, SCXML remains canonical artifact).

### 5.2 Fallback recommendation: 3.7 LLM-driven transpilation

**Rationale.** If the user's calendar pressure precludes authoring even the DIY tool, an LLM-driven pass through Claude Opus 4.7 (or equivalent) produces a hand-written-quality Rust + C source tree from `rtos_kernel.scxml` in hours, not weeks. The [§6.2.7 Auditability](./SOS-06-CONCEPTS.md) gates are its strongest axis. The trade-off is determinism — re-runs are not byte-reproducible — but [§6.4](./SOS-06-CONCEPTS.md) baseline-pinning records the *generated-tree SHA*, not the *toolchain re-execution result*, so a single ratified run is well-defined. Re-evaluation cadence per [§6.5](./SOS-06-CONCEPTS.md) is tighter (every model version bump triggers per (b); every chart amendment likely produces a non-trivial diff per (a)). For SOS-06-A's *first* evaluation run, the determinism cost is acceptable; for steady-state operation it would force adoption of the primary recommendation eventually anyway. Use this fallback if "ship something against the methodology" is more important than "ship a tool the methodology is portable across".

### 5.3 Explicit non-recommendation: 3.3 `uscxml-transform`

Not chosen primarily because of (a) C-only target — splits the evaluation into two runs against two toolchains, doubling [§6.4 baseline pinning](./SOS-06-CONCEPTS.md) bookkeeping; (b) research-grade maintenance posture — bug-response cadence may not match SOS amendment cadence; (c) unknown auditability — would require generating + reviewing a sample tree before committing, which is itself most of the cost of just authoring 3.8. Retained as a fallback if both 3.8 and 3.7 are unavailable and the user wants an off-the-shelf C-only first run.

## 6. Open questions (EOQ — Errata-shaped Open Questions for SOS-06-A intake)

Per parent CLAUDE.md ERRATA conventions, the following EOQs are the standing punch-list the user resolves before SOS-06-A-1 (the first implementation commit ratified against this evaluation) can begin. EOQ identifiers are stable across resolution.

- **EOQ-001-SOS-06-A — Primary toolchain choice.** ✅ **RESOLVED 2026-05-21 (Ira).** Ratified: **scjson + templates** as the codegen path, **with iState as the SCXML generation surface** upstream of it. The end-to-end pipeline is now:

  ```
  iState document  (authoring surface — chart edits land here)
    └─ istate_get_xml / istate_codegen_*  → rtos_kernel.scxml
         └─ scjson convert                → scjson AST (JSON)
              └─ templates (Tera/Jinja)   → ports/m7-rust/.../scripts.rs
                                          → ports/m7-c/.../scripts.c
  ```

  This *expands* §5.1's recommendation rather than overriding it: scjson + templates remain the chosen codegen mechanism (matching the "DIY-then-migrate" rationale — the DIY templates feed the eventual `scjson-gen-{c,rust}` siblings of the family). The new commitment is that the SCXML itself is generated from an iState document, not hand-edited as a text file. iState as the authoring surface gives the chart-author a structured editor + chat-promote workflow (see `mcp__softoboros__istate_*` tools in the parent stack) rather than raw XML editing.

  Downstream consequences (these *do not* override the resolution but surface follow-up EOQs):

  - The `rtos_kernel.scxml` file in this subrepo becomes a *generated artifact* whose authoritative source is the iState document. The SOS-00 INV-S1 invariant ("the .scxml IS the spec") is preserved at the file level — ports still consume the SCXML file as the normative artifact — but the *editing protocol* moves upstream. A future SOS-00 §15 amendment SHOULD clarify the surface (iState document) vs artifact (SCXML file) distinction. See **EOQ-008-SOS-06-A** below.
  - The codegen toolchain (templates layer) ratifies as **scjson-family-aligned** — author the templates in `tools/sos-codegen/` (default per parent CLAUDE.md "spec lineage co-located with code" convention) consuming scjson AST, with the intent that they graduate into `scjson-gen-c` / `scjson-gen-rust` siblings of the family once SOS-06-A's first run has demonstrated viability. **EOQ-007-SOS-06-A** default (a) is therefore confirmed.
  - The §5.2 LLM-driven fallback is now downgraded to **third-line** fallback, behind 3.3 `uscxml-transform` (still declined per §5.3). The user's ratification of scjson+templates means the calendar-pressure framing in §5.2 no longer applies as the primary objection.

- **EOQ-002-SOS-06-A — Single-target vs dual-target first run.** ✅ **RESOLVED 2026-05-21 (Ira).** Simultaneous (Rust + C). The scjson AST → templates toolchain emits both targets in one pass; the SOS-06-A first run is a dual-target run. §6.4 baseline-pinning records the run as a tuple of two `(toolchain, target)` records `(scjson+templates, Rust)` and `(scjson+templates, C)`, both pinned to the same toolchain SHA + scxml SHA. The §15 amendment notes the dual-target framing as a §6.4 micro-extension; no PCDN amendment to [INV-S-CG-8](./SOS-06-CONCEPTS.md) needed because the *toolchain* identity is single — only the *target* axis is plural.

- **EOQ-003-SOS-06-A — `ConformanceLevel` grade for the first run.** ✅ **RESOLVED 2026-05-21 (Ira).** `FullSuitePass` (6/6). Rationale: the hand-written ports both bench-validated 6/6 against the SOS-03 seed vector suite on 2026-05-21; setting the codegen bar at `SmokePass` (5/6) would deliberately understate what the chosen toolchain must achieve to claim parity. A run that lands 5/6 records a `Coexist` or `NotRecommended` verdict honestly per [§5.2](./SOS-06-CONCEPTS.md), rather than gaming the gate.

- **EOQ-004-SOS-06-A — Auditability checklist reviewer.** ✅ **RESOLVED 2026-05-21 (Ira).** User / chart author (options (a) and (b) collapse to the same person). The SOS-06-A §15 amendment will record the reviewer attribution as "Ira (user + chart author)"; the seven-question checklist per [§6.2.7](./SOS-06-CONCEPTS.md) is walked against the generated tree at amendment-authoring time.

- **EOQ-005-SOS-06-A — Acceptance of LLM-as-toolchain framing.** ✅ **RESOLVED 2026-05-21 (Ira) — moot.** Superseded by EOQ-001 resolution. The chosen toolchain is scjson + templates (deterministic); the LLM-as-toolchain framing only applied to the §5.2 fallback path, which is now third-line. The question retains the EOQ slot as institutional memory; the resolution path is "moot via primary choice."

- **EOQ-006-SOS-06-A — Cycle-count measurement on first run.** ✅ **RESOLVED 2026-05-21 (Ira).** Bench-flash both generated ports + collect `MacrostepCycleCount` for the SOS-06-A first amendment. Complete 7-metric matrix in one amendment instead of fragmenting cycle-count into a sibling amendment. Per-round bench authorisation applies at SOS-06-A-1 implementation time; the *intent-to-bench* is recorded here, the per-round signal is given when the bench run begins.

- **EOQ-007-SOS-06-A — Workspace placement of the codegen toolchain itself.** ✅ **RESOLVED 2026-05-21 (Ira, via EOQ-001 resolution).** Default (a) confirmed: `tools/sos-codegen/` inside this subrepo. The templates layer lives co-located with the chart and ports; the eventual graduation into the `scjson` family (as `scjson-gen-c` / `scjson-gen-rust` sibling crates) is a follow-on migration recorded in a future SOS-06-* §15 amendment.

  **Note (2026-05-26, informative; does NOT re-open EOQ-007).** scjson 0.4.0's authoring-side primitives (`help_text` per CONV-E, comment promotion per CONV-F, XInclude per CONV-H, full `<send>` / `<invoke>` attribute surfaces, formalized `other_attributes` registry per CONV-G) sit on the scjson side of the eventual graduation boundary. They are AUTHORING-side primitives that the future `scjson-gen-c` / `scjson-gen-rust` family would consume — for example, chart-author XML comments would emit as Rust `///` and C `/** */` doc-comments in the generated source. The graduation itself remains future work; the scjson 0.4.0 features make the future codegen siblings more powerful but do not change EOQ-007's "tools/sos-codegen/ at v1, graduation later" resolution. **Substantial pre-graduation work remains** on three axes: (1) verification coverage across the language bindings scjson ships (Python + JS at 0.4.0; Rust binding does not exist), (2) the validation pipeline (round-trip fidelity tests across all bindings), and (3) the current `tools/sos-codegen/` template surface (which today does not consume `help_text`, comment-promoted text, or any of the other CONV-E/F/G/H surfaces). See `docs/concepts/SOS-ROADMAP-07-PLUS.md` §"scjson 0.4.0 feature integration (roadmap)" for the per-feature scope notes and `docs/concepts/SOS-09-CONCEPTS.md` §16 (2026-05-26 entry) for the umbrella inventory.

- **EOQ-008-SOS-06-A — iState-as-authoring-surface vs SCXML-as-canonical-artifact reconciliation.** ✅ **RESOLVED 2026-05-22 (Ira) — conditional default (a).**

  Resolution: **SCXML stays canonical IFF scjson round-trips preserve all iState "other attributes" extensions**. Per [SOS-00 INV-S1](./SOS-00-CONCEPTS.md), the `.scxml` IS the spec. iState is the authoring surface upstream; the canonical artifact-on-disk remains `rtos_kernel.scxml`. The conditional is that the iState→SCXML extraction (via scjson's `xml` ↔ `json` round trip) MUST preserve any iState-specific attribute extensions losslessly. If a future iState extension introduces an attribute / namespace that scjson cannot faithfully round-trip, this EOQ re-opens and option (b) (iState becomes canonical, SCXML becomes generated) is reconsidered.

  **Trust basis**: the scjson family ships with a tested round-trip validation suite (`scjson validate` performs the xml→json→xml round-trip check). The chart-author's prior confidence in scjson's round-trip fidelity grounds the conditional. Until any concrete iState extension surfaces an attribute scjson cannot preserve, default (a) holds and INV-S1 is unaffected.

  **Operational consequence**: the pipeline `iState document → istate_get_xml → rtos_kernel.scxml → scjson convert → AST → templates → ports` operates as-is. The build/extraction step SHOULD include an `scjson validate` pass on every iState-extracted `rtos_kernel.scxml` to ratify that the round-trip is lossless for that revision. A future SOS-01 §6 / SOS-06-A pipeline refinement may bake this validation into the build (it is currently an external responsibility of the iState toolchain).

  **Re-opening conditions** (any of these flips EOQ-008 back to "open"):
  - An iState extension uses an attribute that `scjson validate <doc.scxml>` flags as non-round-trippable.
  - A round-trip test produces a `<diff>` that changes any behaviorally-meaningful XML content.
  - The scjson family deprecates round-trip preservation as a v1 guarantee (currently unannounced).

  Tracked in the SCXML lineage as a durable conditional. Reference: parent-repo scjson submodule at `ops/packer/submodules/scjson/`; SOS-06-A pipeline §5.1; SOS-00 §0 INV-S1.

## 7. Files cited

| Path | Role |
|---|---|
| `streamz/submodules/SOS/docs/concepts/SOS-06-CONCEPTS.md` | Normative spec for SOS-06; the methodology this evaluation derives its axes from. |
| `streamz/submodules/SOS/docs/concepts/SOS-00-CONCEPTS.md` | Parent foundational concepts; INV-S1 source-of-truth posture; §6 M7 primitive bindings the codegen output must satisfy. |
| `streamz/submodules/SOS/docs/concepts/SOS-01-CONCEPTS.md` | ECMAScript subset, ExternalEventName/StateId vocabularies the codegen input is constrained to. |
| `streamz/submodules/SOS/docs/concepts/SOS-02-CONCEPTS.md` | Host simulator `sos-sim`; trace format the codegen output must match. |
| `streamz/submodules/SOS/docs/concepts/SOS-03-CONCEPTS.md` | Conformance vector suite; the functional oracle. |
| `streamz/submodules/SOS/docs/concepts/SOS-04-CONCEPTS.md` | Rust-target comparison baseline. |
| `streamz/submodules/SOS/docs/concepts/SOS-05-CONCEPTS.md` | C-target comparison baseline (drafted; forward reference). |
| `streamz/submodules/SOS/docs/REFERENCE.md` | "Code-generation notes" naming the SoftOboros SCXML compiler family. |
| `streamz/submodules/SOS/docs/concepts/README.md` | Phase index. |
| `streamz/submodules/SOS/rtos_kernel.scxml` | The codegen input. |
| `ops/packer/submodules/scjson/` (parent repo) | The `scjson` family vendored submodule; currently converter + Python/Ruby executor; codegen sibling not yet authored. |
| `https://github.com/jp-embedded/scxmlcc` | scxmlcc (3.2). |
| `https://github.com/tklab-tud/uscxml` | uSCXML / uscxml-transform (3.3). |
| `https://www.itemis.com/en/products/itemis-create/` | itemis CREATE (3.4). |
| `https://github.com/QuantumLeaps/qm` , `https://github.com/QuantumLeaps/qpc` | QM + QP/C (3.5). |
| `https://github.com/AlexandreDecan/sismic` | Sismic interpreter (3.6). |
| Parent `CLAUDE.md` — "Spec-Before-Code Planning Discipline", "Errata logs", "Bench-hardware authorization" | Governing conventions. |

## 8. Change log

### 2026-05-21 — Initial draft (Ira)

- Document drafted at `docs/concepts/SOS-06-A-EVALUATION.md` as the SOS-06-A pre-amendment evaluation artifact.
- §0 authority: this file is informative; does not amend [SOS-06](./SOS-06-CONCEPTS.md). The eventual `SOS-06-A` §15 amendment (per [INV-S-CG-6, PCDN-SOS-06-012](./SOS-06-CONCEPTS.md)) will record results of an evaluation *run*; this file picks which toolchain to *run*.
- §3 inventories eight candidates: 3.1 scjson family extension (proposed); 3.2 scxmlcc; 3.3 uscxml-transform; 3.4 itemis CREATE; 3.5 QM+QP/C; 3.6 sismic; 3.7 LLM-driven transpilation; 3.8 DIY `lxml`+templates.
- §4 comparison matrix scores each on the seven [SOS-06 §5.1 EvaluationMetrics](./SOS-06-CONCEPTS.md) plus the [§6.1 pathway-shape](./SOS-06-CONCEPTS.md) gate. First-pass shortlist after the gate: 3.1, 3.3, 3.7, 3.8.
- §5.1 recommends **3.8 DIY `lxml`+templates** as primary, framed as the prototype that demonstrates feasibility and produces the first reference data table; templates migrate to 3.1 `scjson` family extension once that sibling crate is authored.
- §5.2 recommends **3.7 LLM-driven transpilation** as fallback if calendar pressure precludes authoring even the DIY tool. Strongest [§6.2.7 Auditability](./SOS-06-CONCEPTS.md) of any candidate; trade-off is non-deterministic re-runs.
- §5.3 explicitly declines 3.3 `uscxml-transform` on (a) C-only target, (b) research-grade maintenance, (c) unknown auditability. Retained as third-line fallback.
- §6 raises 7 EOQs (EOQ-001 through EOQ-007) the user resolves before SOS-06-A-1 implementation begins. EOQ-001 is the load-bearing one: primary toolchain choice.
- §7 cites the SOS subrepo phase docs, REFERENCE.md, the chart, the `scjson` submodule, the external toolchain repos, and the parent CLAUDE.md conventions.

Status: 🟡 drafted, awaiting user resolution of EOQ-001 through EOQ-007. Resolution unblocks SOS-06-A §15 amendment authoring.

### 2026-05-21 — EOQ-001 + EOQ-007 resolution; EOQ-008 raised (Ira)

User ratified the primary path with one architectural expansion:

> "scjson + templates, yes, but [iState] should be the SCXML generation surface."

Resolved:

- **EOQ-001-SOS-06-A** — ✅ scjson + templates ratified as the codegen path, **with iState added as the SCXML authoring surface upstream**. End-to-end pipeline becomes iState → SCXML → scjson AST → templates → ports. §5.1 updated to record the resolved primary path; §5.2 fallback (LLM-driven) downgraded to third-line. §5.3 `uscxml-transform` non-recommendation unchanged (still declined; second-line fallback).
- **EOQ-007-SOS-06-A** — ✅ Default (a) confirmed by implication: `tools/sos-codegen/` inside this subrepo for the templates layer; migration into the `scjson` family upstream remains a follow-on phase.

Newly raised by the resolution:

- **EOQ-008-SOS-06-A** — iState-as-authoring-surface vs SCXML-as-canonical-artifact reconciliation. Default (a): iState is the editing surface, `rtos_kernel.scxml` remains canonical per [SOS-00 INV-S1](./SOS-00-CONCEPTS.md); iState→SCXML extraction is part of the build pipeline. Final disposition recorded at SOS-06-A §15 amendment time.

Still open (not affected by this resolution): EOQ-002 (Rust-first vs C-first vs simultaneous), EOQ-003 (`SmokePass` vs `FullSuitePass` first-run grade), EOQ-004 (Auditability reviewer attribution), EOQ-005 (LLM-as-toolchain framing — now moot if scjson+templates is the chosen path; can be deferred), EOQ-006 (bench-flash authorisation for `MacrostepCycleCount` collection on first run).

Status remains: 🟡 drafted; partial ratification (EOQ-001, EOQ-007 resolved). Full resolution of remaining EOQs unblocks SOS-06-A §15 amendment authoring.

### 2026-05-21 — `tools/sos-codegen/` v0 scaffold landed (Ira)

Scaffolded `tools/sos-codegen/` per EOQ-007's resolution. v0 pipeline operational end-to-end:

```
rtos_kernel.scxml
  ↓ `scjson json` (v0.3.6, pre-installed via parent backend venv)
scjson AST (JSON)
  ↓ tools/sos-codegen/loader.py (lxml-free for v0; uses scjson output directly)
ChartAst { datamodel, helpers_source, sites[] }
  ↓ tools/sos-codegen/main.py → Jinja2 render
templates/scripts.rs.j2 → /tmp/sos-codegen-out-scripts.rs (652 LOC, 20 script fns)
templates/scripts.c.j2  → /tmp/sos-codegen-out-scripts.c  (653 LOC, 20 script fns)
```

Verified:

- AST loader extracts **29 datamodel entries, 2776 bytes of HELPERS source, 20 script sites** from `rtos_kernel.scxml` — exactly matches the Track-1 survey count.
- Function-name derivation matches the convention used in the hand-written ports: `script_<state>_<event_normalised>_<index>` (e.g. `script_boot_onentry_0`, `script_sys_idle_task_create_0`, `script_prot_idle_sched_resume_0`).
- Both Rust + C templates emit syntactically-recognisable scaffolds; per-site `// CHART:` doc-blocks surface the ECMAScript source so a future transliteration pass has a stable target.

v0 explicit non-claims (the gap to SOS-06-A-1 closure):

- **No HELPERS transliteration.** The chart's 9 helper functions (`readyq_init`, `ready_push`, `ready_remove`, `ready_pop_highest`, `waiters_insert`, `block_current`, `unblock`, `waiter_cancel`, `pick_next`) appear as commented-out ECMAScript in the templated output, not as Rust `impl Datamodel` methods or C `static` helpers.
- **No script-body transliteration.** Each of the 20 `script_*` functions emits a stub returning `Ok(())` (Rust) or `false` (C); the ECMAScript body is surfaced in a `// CHART:` doc-block above each function.
- **Missing `dispatch_event` top-level matcher**. The hand-written `scripts.rs` exports a `pub fn dispatch_event(...)` matcher that the kernel calls; the v0 template doesn't emit it. (Confirmed by swap-and-build: `error[E0425]: cannot find function dispatch_event`.)
- Therefore the v0 codegen output is **NOT drop-in compatible** with the rest of the M7 ports. Swap-and-build fails at link time. This is expected and ratified.

SOS-06-A-1 implementation surface (the gap to actual closure):

1. **ECMAScript → Rust transliterator** for the HELPERS block + per-site script bodies. The chart's ECMAScript surface is constrained (SOS-01 §5.1 freezes 12 features); the transliterator can be a small AST-walker rather than a full ECMAScript engine.
2. **ECMAScript → C transliterator** with the same constrained surface, plus C-specific array bookkeeping (fixed-capacity arrays + per-array `count` companion fields) — analogous to the hand-written port's `dm_ready_push` / `dm_ready_remove` family.
3. **`dispatch_event` emitter** that produces the top-level event-name match on both ports, given the chart's frozen ExternalEventName vocabulary (SOS-01 §5.3).
4. **Pre-existing C-port refactor**: the C port's scripts are currently inlined in `kernel.c` (1146 LOC). A sibling subagent landed a refactor today extracting them into `ports/m7-c/sos-m7-c/src/scripts.c` (status: see `SOS-05-CONCEPTS.md` §15 / co-landing commit) so the codegen target is well-defined.

Bench-validated as part of this session (separate from SOS-06-A): SOS-04 (Rust) + SOS-05 (C) both at 6/6 conformance PASS — SOS-06-A's "match the hand-written bar" target is well-defined.

Implementation progress is now metered against the four-item surface above; SOS-06-A §15 amendment to SOS-06-CONCEPTS.md is gated on completion of items 1–3 plus a 6/6 bench-pass.

Status: 🟡 v0 scaffold ratified; SOS-06-A-1 surface fully scoped; transliterator implementation pending.

### 2026-05-21 — v0 transliterator landed; C-port refactor co-landed (Ira)

Two parallel deliverables of the 2026-05-21 session:

**(1) C-port `scripts.c` extraction (sibling subagent, file-disjoint).**
Extracted chart-derived script bodies from `ports/m7-c/sos-m7-c/src/kernel.c` into the new sibling file `ports/m7-c/sos-m7-c/src/scripts.c` (871 LOC, character-identical code motion). `kernel.c` shrinks 1146 → 277 LOC (dispatcher + boot baseline + `_Static_assert` TCB-layout lock retained). New header `include/sos/scripts.h` declares the 20 script entrypoints with `.scxml` line-range citations matching the Rust `scripts.rs` shape. Build text/data/bss unchanged (pure code motion). Bench-validated: 6/6 SOS-03 PASS post-refactor. Worktree commit `7d27906c`; canonical SOS tree mirror in place. The C-port codegen target is now well-defined.

**(2) `tools/sos-codegen/` v0 transliterator (foreground).**
Added `tools/sos-codegen/transliterate_rust.py` — esprima-backed ECMAScript → Rust emitter. v0 handles: `var x = expr`, assignment + compound assignment, `x++` / `x--`, `if/else`, the two canonical `for`-loop forms (`for (var i = 0; i < N; i++)` and `for (var i = N - 1; i >= 0; i--)`), `while`, helper-call routing (chart `helper(args)` → Rust `dm.helper(args)?`), member access + array indexing, binary / logical / unary expressions, literal substitution (`ST_*` → `TaskState::*`, `RC_*` → `ReturnCode::*`). The scjson AST → template integration in `main.py` now invokes the transliterator per-site with a best-effort + fallback-to-stub semantic: any unhandled construct flags the site, leaves the body stubbed, and surfaces the chart source as a `// CHART:` doc-block.

**v0 codegen against `rtos_kernel.scxml` reproducibility check (2026-05-21):**

- **16 / 20 script sites transliterated cleanly** (`task_yield`, `task_suspend`, `task_resume`, `task_delay`, `task_create`, `sem_take`, `sem_give`, `sem_give_from_isr`, `queue_send`, `queue_receive`, `queue_send_from_isr`, `sched_idle.sched_run`, `crit_enter`, `crit_exit`, `sched_suspend`, `sched_resume`).
- **4 / 20 sites stubbed** with `Ok(())` and `// CHART:` surface, all because they require **object-literal construction** (chart `arr.push({ id: i, prio: 0, state: ST_DORMANT, ... })`) which v0's transliterator defers: `script_boot_onentry_0`, `script_tick_idle_sys_tick_0`, `script_sys_idle_sem_create_0`, `script_sys_idle_queue_create_0`.

**Build of generated `scripts.rs` against the rest of the M7 Rust port** (informative baseline; not a closure claim):

```
RUSTFLAGS="-C target-cpu=cortex-m7" cargo build --target thumbv7em-none-eabihf --release -p sos-m7-rust
…
53 compile errors, 3 clean categories:
  27  EventData typed extraction missing (chart `_event.data.id` / `.sid` / `.qid` / `.msg` / `.timeout`)
  17  Helper method declarations missing on `Datamodel` (chart HELPERS block → impl Datamodel methods)
   2  Type mismatches (numeric narrowing — `current = -1` vs `current: TaskId`)
   7  Misc downstream cascade
```

Hand-written `scripts.rs` restored after the build experiment; the M7 Rust port continues to build clean and pass 6/6 bench.

**SOS-06-A-2 surface (concretely scoped from the v0 baseline):**

1. **EventData typed-`match` emitter.** For each chart event, emit a Rust `match` arm extracting the typed payload from `Event::data` per the chart's frozen ExternalEventName vocabulary. Closes 27 of 53 errors.
2. **`impl Datamodel` HELPERS emitter.** Transliterate the 9 chart helpers (`readyq_init`, `ready_push`, `ready_remove`, `ready_pop_highest`, `waiters_insert`, `block_current`, `unblock`, `waiter_cancel`, `pick_next`) into `impl Datamodel { fn name(&mut self, ...) -> Result<(), ScriptError> { ... } }`. Closes 17 of 53 errors.
3. **Object-literal → struct-construction emitter.** Map chart `{ field: val, ... }` to the per-site target struct (`Tcb { ... }`, `Sem { ... }`, `Queue { ... }`). Closes the remaining 4 stubbed sites.
4. **`dispatch_event` top-level matcher emitter.** Generate the event-name → script-function dispatch the kernel calls. Required for drop-in replacement of `scripts.rs`.
5. **C transliterator + per-site struct binding.** Same surface as 1–4 but for C; targets the bench-validated `scripts.c` produced by the (1) refactor above.
6. **Bench-flash both generated ports for `MacrostepCycleCount`.** Per EOQ-006.

Status: 🟡 v0 transliterator landed; **16 / 20 sites translate cleanly**; SOS-06-A-2 surface fully scoped to 6 concrete items. Closure of items 1–5 unblocks the SOS-06-A §15 amendment to `SOS-06-CONCEPTS.md`.

### 2026-05-21 — SOS-06-A-2 Item 1 (Rust EventData) + Item 5 (C transliterator) landed (Ira)

Parallel progress on three tracks this turn:

**(Track 1, foreground) — Rust EventData typed-match emitter.** Added `EVENTDATA_VARIANTS` mapping (chart event → enum variant + field list) and `emit_eventdata_extract()` in `tools/sos-codegen/transliterate_rust.py`. Per-site preamble emits the `let (...) = match ev.data { ... }` destructure; `_event.data.<field>` and the `var d = _event.data; d.<field>` alias pattern resolve to the bound local. The `var <field> = _event.data.<field>` redundant rebind is elided. Also fixed the `.length → .len()` translation for `MemberExpression`.

Rust compile-error reduction against the M7 Rust port:
| Stage | Errors |
|---|---|
| v0 (transliterator only, no EventData) | 53 |
| + EventData typed-match emitter | 38 (-15) |
| + `.length → .len()` | 32 (-6) |

Residual 32 Rust errors break into:
- **17 missing helper methods** (Item 2 surface — `unblock`, `block_current`, `waiters_insert`, `waiter_cancel`, `ready_push`, `pick_next` on `Datamodel`).
- **12 type mismatches** (mostly `t.msg = /* null */ ()` and `t.msg = ReturnCode::Ok` where `Msg` is an enum type — Item 3 surface: object-literal + per-field-type-aware emission).
- **1 missing `dispatch_event`** top-level matcher (Item 4 surface).
- **2 misc cascade**.

**(Track 2, background subagent A) — C transliterator.** Added `tools/sos-codegen/transliterate_c.py` (481 LOC). Mirrors the Rust transliterator's shape: `CEmitter` class + `transliterate_to_c(source, event_name=None)`. C-specific idioms in place:
- `dm->field` access (pointer-to-struct vs Rust's `dm.field`).
- `dm_<helper>(dm, args)` calls (C's prefixed-helper pattern vs Rust's `dm.helper(args)?`).
- `SOS_TS_*` / `SOS_RC_*` constant naming.
- Both canonical `for`-loop forms supported.

C compile-error baseline against the (refactored) M7 C port:
| Run | Errors |
|---|---|
| Generated C swapped into bench-validated `scripts.c` | 31 |

Residual 31 C errors break into:
- **18** `int32_t t = dm->tcb[i]` should be `sos_tcb_t *t = &dm->tcb[i]` — the chart's `var t = tcb[i]` aliases a struct row, not a scalar. v0 emits `int32_t` for every `var`; Item 3 (type-aware variable declarations + struct-pointer semantics for chart-array-row aliases).
- **4** missing helper-function declarations (`dm_unblock`, `dm_ready_remove`, `dm_ready_push`, `dm_waiter_cancel` — Item 2 surface).
- **2** `sos_event_data_t` field access (chart `_event.data.id` — Item 1 surface for C, sibling to the Rust Item 1).
- **7** misc cascade.

**(Track 3, background subagent B) — SOS-04 §15 Amendment 014: PCDN-SOS-04-013 APBx prose reconciliation.** Landed at lines 1216–1259 of `docs/concepts/SOS-04-CONCEPTS.md`. Records:
- The internal inconsistency in PCDN-013's "/2 (200 MHz)" prose.
- The two as-built conforming configurations (Rust /1 → APB=200 MHz, BRR=1736; C /2 → APB=100 MHz, BRR=868).
- The surviving invariant: `BRR = USART1_PCLK_HZ / USART1_BAUD` with `PCLK_HZ` matching the actual APBx setting.
- The bench-debug `e6 98 e6 98` byte signature that surfaced the 2× baud mismatch.
- **EOQ-001-AMENDMENT-014** asking the user to ratify one of:
  - (a) `/1` normalisation (200 MHz APBx, both ports migrate).
  - (b) `/2` normalisation (100 MHz APBx, matches rlvgl, both ports migrate).
  - (c) keep both per-port conforming; rewrite PCDN-013 prose to enumerate them.

**Aggregate state of SOS-06-A-1:**

| Item | Rust errors | C errors | Status |
|---|---|---|---|
| 1. EventData typed-match emitter | 27 → 0 ✅ | 2 still | Rust done; C-side mirrors as Item 5b |
| 2. `impl Datamodel` HELPERS emitter | 17 | 4 | pending |
| 3. Object-literal + type-aware var decls | 12 | 18 | pending |
| 4. `dispatch_event` top-level matcher | 1 | 0 (subagent included it) | pending Rust |
| 5. C transliterator base | n/a | done ✅ | per Track 2 |
| 6. Bench-flash for `MacrostepCycleCount` | gated on 1–4 | gated on 1–4 | pending |

**Open EOQs in flight from today's work:**
- `EOQ-001-AMENDMENT-014` (SOS-04 §15) — APBx normalisation forward choice.

Hand-written `scripts.rs` and `scripts.c` restored after each build experiment; both M7 ports continue to build clean and pass 6/6 bench.

Status: 🟢 Item 1 + Item 5 base complete; SOS-06-A-1 closure path is now Items 2 + 3 + 4 (Rust) and Items 1b + 2b + 3b (C). Either of these can proceed in parallel; both feed the same SOS-06-A §15 amendment when complete.

### 2026-05-21 — C transliterator refinement landed; C-side EventData preamble works (Ira)

The C transliterator subagent refined its v0 to be **honest about which sites it can clean-emit** (12 stubs / 8 clean) instead of emitting always-something-but-sometimes-wrong code (which earlier showed as 20/0 + 31 build errors). The refined transliterator:

- Lands EventData typed-union preamble: `if (ev->data.tag != SOS_EVD_<X>) { dm->rc = (sos_rc_t)SOS_RC_INVAL; return false; } sos_task_id_t id = ev->data.u.<variant>.id;` etc. Resolves `_event.data.<field>` and the `var d = _event.data; d.<field>` alias pattern.
- Maps `ST_*` → `SOS_ST_*`, `RC_*` → `SOS_RC_*`, helper calls → `dm_<name>(dm, ...)`.
- Marks 4 stub-categories the v0 cannot handle (per the subagent's own classification):
  - **6 sites — JS array-method on aliased waiter list** (`s.waiters.shift()`, `q.recvw.length`, `q.sendw.splice(...)`): `sem_take`, `sem_give`, `sem_give_from_isr`, `queue_send`, `queue_receive`, `queue_send_from_isr`. The hand-written port splits `heapless::Vec<T,N>` into parallel `T arr[N] + uint8_t arr_count` — the chart JS treats waiter lists as first-class arrays and the codegen needs site-aware `arr+count` accessors to land these. Item 3 territory for C.
  - **3 sites — `var t = tcb[i];` struct-alias-mutation**: `sys_tick`, `task_create`, `sched_resume`. JS treats this as a reference; C copies the struct. Needs site-aware emission of `sos_tcb_t *t = &dm->tcb[i];` (Item 3 for C).
  - **2 sites — empty-array reset** (`q.buf = []; s.waiters = [];`): `sem_create`, `queue_create`. Maps to `arr_count = 0` in the C port. Item 3 for C.
  - **1 site — combined ObjectExpression + `arr.push({...})` + `readyq_init`**: `boot_onentry`. Item 3 for C.

C compile-error reduction:

| Run | Errors |
|---|---|
| Subagent v0 (initial: 20 emitted, but many semantically broken) | 31 |
| Subagent v1 refined (12 stubs + 8 clean) | **4** |

Residual 4 C errors are **all** missing `dm_*` helper forward declarations (`dm_block_current`, `dm_pick_next`, `dm_ready_push`, `dm_ready_remove`). Closing these is the C-side Item 2 (HELPERS emitter that emits the file-static helpers as a prefix to the generated `scripts.c`).

**Updated SOS-06-A-1 closure surface:**

| Item | Rust errors remaining | C errors remaining | Status |
|---|---|---|---|
| 1. EventData typed-match emitter | 0 ✅ | 0 ✅ | done both ports |
| 2. HELPERS emitter (file-static / impl-block) | 17 | 4 | pending |
| 3. Object-literal + struct-pointer var decls | 12 | 12 stubs (would close ~6-8 of the 18 earlier errors per emitted site) | pending |
| 4. `dispatch_event` top-level matcher | 1 | (subagent included) | Rust pending |
| 5. C transliterator base | n/a | done ✅ | done |
| 6. Bench-flash for `MacrostepCycleCount` | gated on 2–4 | gated on 2 | pending |

The C side is now closer to closure than Rust: **closing Item 2 alone for C drops the error count to 0** for the 8 clean sites. Whether 8/20 clean is sufficient for `FullSuitePass` per EOQ-003 depends on whether the 12 stubbed sites' tests run inside the seed-vector suite — they do (vectors 0001-0006 each exercise some of those sites), so Item 3 closure is the load-bearing C step for SOS-06-A-1.

The Rust side needs Items 2 + 3 + 4 to close the 30 of 32 errors that aren't already-zero.

Hand-written `scripts.rs` + `scripts.c` restored; both ports still build clean.

### 2026-05-22 — SOS-06-A-2 Items 2 + 4 landed (Rust); Item 2 landed (C) (Ira)

**Track A (foreground) — Rust Item 2 (HELPERS) + Item 4 (dispatch_event).**

Added to `tools/sos-codegen/transliterate_rust.py`:
- `HELPER_SIGNATURES` table pinning per-helper Rust arg/return types (matches the call-site shapes script bodies use).
- `RustEmitter._self_mode` flag — when emitting inside an `impl Datamodel` method, datamodel access uses `self.<field>` instead of `dm.<field>`.
- `emit_helpers(helpers_source)` — parses the chart's HELPERS block with esprima, walks `FunctionDeclaration` nodes, emits each as an `impl Datamodel` method. Three helpers (`block_current`, `unblock`, `ready_remove`) transliterate mechanically; the other six emit typed stubs with `Ok(())` / `Ok(-1)` to satisfy the call-site signatures.
- `emit_dispatch_event(sites)` — emits `pub fn dispatch_event(dm, ev) -> Result<()>` with a `match ev.name` arm per chart transition. The internal events (`kernel.boot.done`, `sched.run`) are correctly excluded (they're not in the hand-written `EventName` enum).
- `EVENT_TO_VARIANT` chart-name → Rust EventName variant map (18 entries matching the M7 Rust port's `EventName` enum exactly).
- `RustEmitter._emit_typed_assignment_rhs` — when LHS is `<expr>.msg`, wraps the RHS into the appropriate `Msg::Null` / `Msg::ReturnCode(...)` / `Msg::Int(...)` variant.

Wired into `tools/sos-codegen/main.py::render_target` + `templates/scripts.rs.j2` (impl block insertion + dispatch_event footer).

**Track B (background subagent) — C Item 2 (HELPERS).**

Added to `tools/sos-codegen/transliterate_c.py` (+187 LOC): `HELPER_SIGNATURES` C-side mirror + `_format_helper_signature` / `_sanitise_comment_text` / `_format_stub_body` + `emit_helpers_c(helpers_source)`. All 9 helpers emit as file-static stub bodies with correct signatures matching the hand-written port (`(struct sos_datamodel *dm, ...)` first-arg, correct typing, correct return). Helpers carry `__attribute__((unused))` so unused-static warnings stay quiet under `-Werror`. Bodies are `(void)dm; (void)<args>; return -1;` or void as appropriate; chart source surfaces as nested-comment-safe `/* CHART: ... */` blocks.

**Compile-error reduction this turn:**

| Stage | Rust | C |
|---|---|---|
| Pre-turn (Items 1 + 5 base) | 32 | 4 |
| + Item 2 (HELPERS emitter) + Item 4 (dispatch_event) | 22 → 20 → 19 | 0 ✅ |
| + Msg-enum wrapping (partial Item 3) | **12** | 0 ✅ |

C reached **0 compile errors**: generated `scripts.c` links cleanly when swapped into the bench-validated build tree. Runtime conformance is `0/6 PASS` because all 9 helpers are stubs (and 12 of 20 transition scripts are stubs from the prior subagent v1) — this is the correct "the tool can ship something, but it doesn't yet earn `CanonicalReplacement` per the SOS-06 verdict matrix".

Residual 12 Rust errors are all Item 3 territory:

- **4 errors — `waiters_insert(<Vec<i16,8>>, current)`**: chart passes the waiter list directly as the first arg; the Rust hand-written uses a `WaiterList` enum discriminator + obj index. v0 pinned arg-type as `i32` placeholder; needs site-aware discriminator emission.
- **2 errors — `q.buf.push(tcb[w].msg)`**: chart reads `t.msg` (which JS treats as a scalar) and pushes into queue buffer; Rust `t.msg` is `Msg` enum, queue buf is `Vec<i64,_>`. Needs site-aware Msg-variant extraction (`if let Msg::Int(v) = ... { v }`).
- **3 errors — `usize`/`i16` narrowing on `dm.current` passes**: chart `current` is variant int; Rust narrowing needs explicit casts.
- **3 errors — Msg field-RHS reads** (similar to bullet 2): `tcb[i].msg = tcb[w].msg` — RHS is `Msg`, LHS slot is `Msg`; the codegen's Item 3 wrap-as-Msg::Int(rhs) requires the RHS first be unwrapped.

**Updated SOS-06-A-1 closure surface:**

| Item | Rust | C | Status |
|---|---|---|---|
| 1. EventData typed-match emitter | 0 ✅ | 0 ✅ | done |
| 2. HELPERS emitter | 0 ✅ (3 transliterated + 6 stub) | 0 ✅ (all 9 stub) | done |
| 3. Object-literal + struct-pointer + Msg-field reads | 12 | 12 of 20 sites still stubbed | **active surface** |
| 4. `dispatch_event` matcher | 0 ✅ | n/a (subagent included earlier) | done |
| 5. C transliterator base | n/a | done ✅ | done |
| 6. Bench-flash for `MacrostepCycleCount` | gated on 3 | gated on 3 | pending |

Hand-written `scripts.rs` and `scripts.c` restored after every build experiment; both M7 ports continue to build clean.

Items 2 + 4 of the SOS-06-A-1 surface are complete on both targets. Item 3 is the load-bearing remaining work — closing it for Rust + C unblocks the bench-flash for `MacrostepCycleCount` per EOQ-006 and then the SOS-06-A §15 amendment to `SOS-06-CONCEPTS.md`.

### 2026-05-22 — SOS-06-A-2 Item 3 (compile-clean closure on both targets) (Ira)

**Track A (foreground) — Rust Item 3.**

Added to `tools/sos-codegen/transliterate_rust.py`:
- **Struct-alias rewrite**: when `var <name> = <coll>[<expr>];` is seen for `coll ∈ {tcb, sems, queues}`, records `<name>` as alias of `dm.<coll>[<expr> as usize]` and suppresses the local binding. Subsequent `<name>.<field>` accesses rewrite through the collection — avoids Rust's `cannot move out of dm.sems[_]` error class.
- **Msg pass-through on RHS read**: when wrapping LHS as `Msg::*`, if RHS is already a `.msg` field read, pass through (value is already typed `Msg`, no wrap needed).
- **`.push(<expr>.msg)` Msg-unwrap**: special-cases `<vec>.push(<expr>.msg)` to emit `<vec>.push(if let Msg::Int(v) = <expr>.msg { v } else { 0 }).ok()`. Chart invariant: queue.send delivers an i64 via `msg`, so the variant is always Msg::Int.
- **Helper-call narrowing**: `_emit_helper_args` casts each chart arg to the pinned `HELPER_SIGNATURES` type (`TaskId` → `as i16`, etc.). Closes the `usize`/`i16` mismatch class.
- **waiters_insert placeholder**: detects `waiters_insert(<.waiters|sendw|recvw>, tid)` call shape, emits `(0, tid as i16)` placeholder args matching the pinned 2-arg `(arr: i32, tid: TaskId)` signature. The helper itself is stubbed; runtime fails honestly. SOS-06-A-2 follow-on: site-aware enum discriminator.

Rust compile-error reduction:

| Stage | Errors |
|---|---|
| Pre-turn | 12 |
| + Msg pass-through + struct-alias + push(.msg) + narrowing + waiters_insert placeholder | **0** ✅ |

**Generated `scripts.rs` now compiles cleanly against the rest of the M7 Rust port.** Bench validation (per EOQ-006) is gated on a separate per-round bench-flash signal.

**Track B (background subagent) — C Item 3 (5 of 12 sites).**

Added to `tools/sos-codegen/transliterate_c.py` (+125 LOC):
- `_STRUCT_POINTER_TYPES` reference table mapping chart collection → C struct pointer typedef (`tcb → sos_tcb_t *`, etc.).
- `_struct_pointer_aliases` dict + MemberExpression arrow-operator branch — `var t = tcb[i]` → `sos_tcb_t *t = &dm->tcb[i];`, then `t.state` → `t->state`.
- `_EMPTY_ARRAY_RESET_COUNT_FIELD` — empty-array reset (`.waiters = []`, `.buf = []`, `.sendw = []`, `.recvw = []`) emits the corresponding count-field zero assignment. Critical finding: `sos_queue_t` doesn't have a separate `buf_count` — the outer `count` IS the buf count, so `.buf = []` maps to `.count = 0`.
- Tagged-union `t->msg = RC_*|null` expansion (`.tag = SOS_MSG_RC; .u.rc = ...` or `.tag = SOS_MSG_NULL; .u.i = 0`).

C stub-count reduction:

| Stage | Stubs |
|---|---|
| Pre-turn | 12 (sites that v0 transliterator couldn't safely emit) |
| + Item 3 partial closure (struct-alias + empty-reset + tcb.msg union expansion) | **7** |

Sites unstuck: `script_tick_idle_sys_tick_0`, `script_sys_idle_task_create_0`, `script_prot_idle_sched_resume_0`, `script_sys_idle_sem_create_0`, `script_sys_idle_queue_create_0`.

The 7 remaining C stubs are exactly the "hardest" deferred categories from the prior subagent's classification: 6 sem/queue waiter-list array-method sites (`sem.take`/`give`/`give_from_isr`, `queue.send`/`receive`/`send_from_isr`) + 1 boot.onentry ObjectExpression + push + readyq_init combination. Closing them needs site-aware `arr+count` accessor emission (e.g. `dm->sems[s].waiters[dm->sems[s].waiter_count++] = tid`) — that's a non-trivial codegen pass deferred to SOS-06-A-3.

**Aggregate SOS-06-A closure state:**

| Item | Rust | C | Status |
|---|---|---|---|
| 1. EventData typed-match | 0 ✅ | 0 ✅ | done |
| 2. HELPERS emitter | 0 ✅ (impl Datamodel: 3 transliterated + 6 stub) | 0 ✅ (9 file-static stubs) | done |
| 3a. Msg-enum wrap/unwrap | 0 ✅ | 0 ✅ | done |
| 3b. Struct-alias rewrite | 0 ✅ | 0 ✅ (5 sites) | done |
| 3c. Object-literal struct construction | 0 ✅ (n/a, no direct site exercised it post-alias) | **stub** (boot.onentry) | partial |
| 3d. Array-method on waiter-list alias | 0 ✅ (placeholder discriminator) | **stub** (6 sites) | partial |
| 4. `dispatch_event` matcher | 0 ✅ | included | done |
| 5. C transliterator base | n/a | done ✅ | done |
| 6. Bench-flash for `MacrostepCycleCount` | gated on per-round signal | gated on per-round signal | pending |

**Generated source ships compile-clean on both targets.** The SOS-06 verdict per the §5.2 matrix would be `NotRecommended` if FullSuitePass were measured now (runtime conformance is 0/6 because helpers + waiter-list ops are stubs). Closure of Items 3c + 3d would lift the verdict toward `Coexist` or `CanonicalReplacement` per the matrix.

Hand-written `scripts.rs` + `scripts.c` restored after every build experiment; both M7 ports continue to build clean and the bench-validated binaries are on disk for future flashes.

**Updated EOQ-006 disposition recommendation**: bench-flash the codegen output now would yield 0/6 PASS — `NotRecommended` verdict. The honest amendment-grade run requires closing Items 3c + 3d first. The user MAY choose to bench-flash now anyway (records the 0/6 baseline) or defer until 3c+3d land.

### 2026-05-21 — Full EOQ batch resolution (Ira)

User walked the open EOQs and ratified the recommended option on each:

| EOQ | Decision |
|---|---|
| EOQ-002 | Simultaneous (Rust + C) dual-target first run. |
| EOQ-003 | `FullSuitePass` (6/6) — matches the hand-written ports' bench-validated bar. |
| EOQ-004 | Reviewer = Ira (user + chart author). |
| EOQ-005 | Moot — superseded by EOQ-001 (deterministic toolchain chosen). |
| EOQ-006 | Bench-flash both generated ports + collect `MacrostepCycleCount` in first amendment. |

EOQ-008 default (a) carried forward — iState as authoring surface, SCXML remains canonical artifact per [SOS-00 INV-S1](./SOS-00-CONCEPTS.md). Final disposition recorded at SOS-06-A §15 amendment time.

**SOS-06-A run profile (consolidated):**

- Toolchain: scjson + Tera/Jinja templates under `tools/sos-codegen/`.
- Upstream authoring surface: iState document → `istate_get_xml` → `rtos_kernel.scxml`.
- Targets: Rust + C, emitted simultaneously from one scjson AST pass.
- Conformance bar: `FullSuitePass` (6/6) against the SOS-03 seed vector suite, on both ports.
- Bench validation: yes — both ports flash-and-run on the disco-analyzer; `MacrostepCycleCount` collected per port.
- Reviewer: Ira; §6.2.7 Auditability walked at amendment-authoring time.

**Unblocks**: SOS-06-A-1 implementation (the codegen tool itself + the first SOS-06-A §15 amendment to SOS-06-CONCEPTS.md). Status: 🟢 ratified for execution.
