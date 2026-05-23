# SOS — Phase Roadmap

Initiative-family index for the Statechart-Orchestrated Scheduler. Each row below is the **informative** abstract of a phase doc; the per-phase `SOS-NN-*.md` is the **normative** artifact (see parent CLAUDE.md "Normative vs. informative sections").

## Status legend

- 🟢 ratified — §15 dated entry exists; implementation MAY proceed
- 🟡 drafted — concepts written; open PCDN items pending user resolution
- 🔴 not started

## Phase index

| Phase | Status | Subject | Blocks |
|---|---|---|---|
| **SOS-00** | 🟢 ratified 2026-05-19 | Foundational concepts: vocabulary, source-of-truth map, frozen enums, M7 primitive bindings, invariants. All 11 PCDNs resolved. | 01, 02, 03, 04, 05, 06 |
| **SOS-01** | 🟢 ratified 2026-05-19 | SCXML normalization + linting. Confirms `rtos_kernel.scxml` is well-formed against the SCXML 1.0 schema (vendored at `docs/specs/scxml.xsd` per PCDN-001); ratifies 18 lint rules (11 error / 7 warning) covering schema, structural, style, determinism, comment, and datamodel categories; freezes ECMAScript subset (12 permitted / 22 forbidden); freezes ExternalEventName + StateId vocabularies; script-block cap 40 LOC per PCDN-003; resolves PCDN-SOS-00-005 with hand-compiled-only v1 (AST/trace deferred to SOS-02-B). Implementation commit (vendored XSD + Python+lxml lint runner + CI workflow) lands as follow-up. | 02, 03 |
| **SOS-02** | 🟢 ratified 2026-05-19 | Host simulator. Rust crate `sos-sim` executes the .scxml against a host harness; emits SOS-00 §7-shape trace as JSONL. Crate name `sos-sim`; MSRV 1.75; CLI via `clap = "4"`; standalone Cargo workspace at the SOS subrepo root; `PreLoaded` vector input only at v1; no feature gates. `ScriptProvider` trait is the extension point for SOS-01's deferred AST-walk question. Implementation commit (workspace + crate skeleton) lands as follow-up. | 03 |
| **SOS-03** | 🟢 ratified 2026-05-19 | Conformance vector suite. Vector file format: per-vector JSON at `conformance/vectors/<category>/<NNNN>-<slug>.json`; 4 frozen enums (VectorCategory, ConformanceLevel, DiffSeverity, VectorOrigin); `sos-conformance` harness as a separate crate in the same Cargo workspace as `sos-sim`; structural per-record diff (PCDN-001); committed-by-author `expected_trace` (PCDN-003 — auditable); manual sequential ID allocation (PCDN-005); `globset = "0.4"` for `--filter`; short-form `{"valid": false}` canonical. 12 INV-S-CONF-N invariants. Implementation commit (harness scaffold + 6 seed vectors + CI extension) lands as follow-up. | 04, 05, 06 |
| **SOS-04** | 🟢 ratified 2026-05-19 | M7 Rust reference port. `sos-m7-rust` crate at `ports/m7-rust/sos-m7-rust/` (Cargo workspace member); target `thumbv7em-none-eabihf`; bench substrate STM32H747I-DISCO CM7 (sole firmware per PCDN-SOS-00-001 = (b)). USART1 / PA9 / PA10 / AF7 at 921600 baud (memalpha-confirmed); `stm32h7` PAC + hand-coded BSP; `heapless = "0.8"` rings; `UnsafeCell` interior mutability; hand-rolled JSON writer (PCDN-008 byte-stability covered by separate `sos-m7-rust-tests` host crate); one feature gate `standalone-smoke`; clock tree HSE=25 / CM7=400 / APBx=200 / CM4 disabled; host-side adapter `serialport = "4"` with 30 s timeout. 3 future-amendment markers (FAM-04-A configurable stacks, FAM-04-B FLASH layout abstraction, FAM-04-C UART DMA promotion). Implementation commit lands as follow-up. | 06 |
| **SOS-05** | 🟢 ratified 2026-05-19 | M7 C reference port. `sos-m7-c` project at `ports/m7-c/sos-m7-c/` (outside Cargo workspace — CMake sibling). CMake ≥ 3.20 with toolchain file + presets; picolibc; split headers under `include/sos/` + convenience `sos/sos.h`; C11; clang-tidy CI gate; `arm-none-eabi-gcc 13.2.Rel1`; USART1 (memalpha-confirmed, shared with SOS-04); no STM32CubeH7 HAL (hand-coded against bare CMSIS device header); JSONL-bidirectional UART framing aligned with SOS-04; bench-host adapter in C. §9 INV-S-PORT-N IDs shared with SOS-04. v1 is REFERENCE not PRODUCTION — hardening deferred to SOS-05-B. | 06 |
| **SOS-06** | 🟢 ratified 2026-05-19 | Codegen-from-SCXML evaluation. Ratifies the *methodology* for evaluating SCXML→source-tree codegen, not a specific toolchain. 4 frozen enums (EvaluationMetric, SuitabilityVerdict, Pathway, MetricSeverity); 7-item metric list (`FunctionalConformance` is the only Blocker; DWT cycle counter; median-of-100 measurement; `task.yield` round-robin as canonical representative macrostep; match-baseline opt-level; 1.5x/2x thresholds). 3 outcome verdicts (CanonicalReplacement / Coexist / NotYetSuitable) with mechanical verdict procedure. 11 INV-S-CG-N invariants. 7-question structured Auditability checklist. Terminal phase of v1 roadmap. Future SOS-06-A / SOS-06-B amendments land evaluation-run results. | — |

## Dependency arrows

```
SOS-00 ──┬──> SOS-01 ──┬──> SOS-02
         │             └──> SOS-03 ──┬──> SOS-04
         │                           ├──> SOS-05
         │                           └──> SOS-06
         └──> (M7 primitive bindings consumed by SOS-04, SOS-05, SOS-06)
```

## Conformance levels

Per parent CLAUDE.md "Conformance targets" convention, SOS declares two conformance levels:

- **A conforming SOS port MUST satisfy SOS-00 §9 invariants AND pass every SOS-03 vector.** Vectors are versioned; "passes SOS-03 v1.0" is a meaningful claim.
- **A conforming SOS bench port MUST additionally satisfy SOS-00 §6 (M7 primitive bindings).** Host-simulator-only ports satisfy the kernel-level conformance but not the bench-level conformance.

The SOS-02 host simulator is the bootstrap reference: it is conformance-level "kernel" by construction (it interprets the canonical .scxml directly) but **not** conformance-level "bench" (it has no PendSV).

## Errata log

`docs/concepts/ERRATA.md` is the inward-facing institutional memory for accepted issues. GitHub Issues is the intake surface; triaged-and-accepted issues move into ERRATA with stable `ERRATA-NNN` ids per the parent CLAUDE.md convention.
