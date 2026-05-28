# SOS-08 — Chart-family registry

**Status:** 🟢 **Informative registry.** Authoritative listing of chart families that consume the SOS-08 HDL backend stack and the SOS-09 hardware/software-membrane emit pipeline.

## 0. Authority policy

This document is **informative**. It exists per [SIS-08E PCDN-005][sis-08e-pcdn-005] ratification (parent repo, 2026-05-28) as the dedicated home for chart-family rows that previously lived inline in [`SOS-08-CONCEPTS.md`](./SOS-08-CONCEPTS.md) §13. Per the ratified decision (option (b) — dedicated SOS-authored registry doc), the registry is authored by SOS and cited by SIS phases that introduce chart families (SIS-08B, SIS-08D C2-A, SIS-08E C3, and successors).

The registry is **not normative** in the spec-before-code sense — chart families themselves ratify in their authoring phase's concept doc (typically a parent-repo `TODO-SIS-NN-*.md`). This file is the cross-family index that lets reviewers locate the chart family's spec lineage, emitter, and bench substrate without grep-scanning every phase doc.

Each row records:
- **Family** — the canonical chart-family id (e.g. `SIS-08B`, `SIS-08D C2-A`, `SIS-08E C3`).
- **Chart tree** — the SOS-side tree under `charts/<family>/` that holds the SCXML + manifest + emitted artifacts.
- **Status** — 🟢 ratified / 🟡 drafted / 🔴 not started.
- **Scope** — one-line summary of what the chart family proves.
- **Originating doc** — authority pin to the phase doc that owns the chart family's contract.
- **Emitter** — the `tools/sos-codegen/` Python script that drives chart-tree generation.

Row additions are **Standards Action** — adding a new chart family requires a §2 amendment to this doc and a ratification walkthrough. Modifying an existing row's scope, originating-doc pin, or emitter pin requires a §2 amendment (status flips and bench-substrate updates are permissible without §2 amendment when the underlying phase doc records the change). Demotion to a less-formal registration policy requires a §2 amendment.

[sis-08e-pcdn-005]: ../../../../../docs/todo/streamz/statechart-orchestration/TODO-SIS-08E-C3-PLAN.md

## 1. Registry

| Family | Chart tree | Status | Scope | Originating doc | Emitter |
|---|---|---|---|---|---|
| **SIS-08B** | `charts/sis08_first_slice/` | 🟢 | First hardware-slice precedent — memory-mapped FIFO membrane (queue + status + command + mailbox-notify + credit-budget channels). Exercises the SOS-09-A annotation grammar + SOS-09-B SVD emit + SOS-09-G MPU emit + SOS-09-F vector emit end-to-end. | parent repo `docs/todo/streamz/statechart-orchestration/TODO-SIS-08B-FIRST-HARDWARE-SLICE.md` | `tools/sos-codegen/sis08_first_slice.py` |
| **SIS-08D C2-A** | `charts/sis08d_c2_membrane/` | 🟢 | SRAM-membrane proof — disco-analyzer-targeted single SRAM-window membrane (command + status + mailbox data + mailbox notify + SRAM-window channels). Validates the SIS-08D §4 membrane-contract requirements (ownership, byte layout, command/status/transfer surface, notification, vector suite reference) on the same SOS-09 emit pipeline as the SIS-08B precedent. Bespoke integration vector at `charts/sis08d_c2_membrane/vectors/sis08d_c2_membrane/test_c2a_membrane_contract.py` is the SIS-08D §5 step-1 interpreted-simulation evidence. | parent repo `docs/todo/streamz/statechart-orchestration/TODO-SIS-08D-C2-IMPLEMENTATION-PLAN.md` §3 work package C2-A + §4 | `tools/sos-codegen/sis08d_c2_membrane.py` |

## 2. Change log

### 2026-05-28 — Initial registry doc (SIS-08E prerequisite)

- Authored `SOS-08-CHART-REGISTRY.md` per [SIS-08E PCDN-005][sis-08e-pcdn-005] ratification (parent repo, 2026-05-28; option (b) — dedicated SOS-authored registry doc).
- Migrated the SIS-08B (`charts/sis08_first_slice/`) and SIS-08D C2-A (`charts/sis08d_c2_membrane/`) informational rows out of [`SOS-08-CONCEPTS.md`](./SOS-08-CONCEPTS.md) §13. The §13 entry now points here; future chart-family additions land via §2 amendments to this doc rather than inline in `SOS-08-CONCEPTS.md` §13.
- Reciprocal cross-cite recorded in `SOS-08-CONCEPTS.md` §15 (2026-05-28 entry).
- Frozen-enumeration registration policy: NEW rows are **Standards Action** (per §0).
- No normative behavior change. The migrated rows were informational; this is a documentation reorganization that prepares the SIS-08E C3-A dispatch (which will add 4–6 new chart-family rows for the C3 multi-membrane orchestration).

Status: 🟢 **informative registry**, ready to absorb SIS-08E C3-A chart-family rows when that work dispatches.
