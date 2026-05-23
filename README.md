# SOS — Statechart-Orchestrated Scheduler

A minimal preemptive priority-based RTOS kernel **specified as a single SCXML statechart**, with reference implementations on Cortex-M7 hardware in both C and Rust.

The product here is the **methodology** more than the kernel: prove that a non-trivial deeply-embedded behaviour can be specified in SCXML at a level of precision sufficient to drive multiple language ports, and that the resulting kernels remain provably equivalent under a shared conformance-vector suite.

This is a **private** repo (no public distribution). It is intended to become a submodule of the parent `softoboros.com` tree at `streamz/submodules/SOS/`.

## Layout discipline

Top-level layout follows the rlvgl / disco-analyzer convention so structural and semantic searches behave the same way across all SoftOboros sub-repos:

```
.
├── AGENTS.md                # contributor + agent guide
├── CLAUDE.md                # agent runbook (where things live, source-of-truth boundary)
├── README.md                # this file
├── rtos_kernel.scxml        # CANONICAL kernel behaviour spec (normative)
├── docs/
│   ├── REFERENCE.md         # human-readable derivation of the .scxml (informative)
│   └── concepts/            # spec-before-code phase docs (SOS-NN-*)
│       ├── README.md        # initiative index + phase roadmap
│       ├── SOS-00-CONCEPTS.md
│       └── ERRATA.md
└── (future: ports/, sim/, conformance/)
```

`rtos_kernel.scxml` is the single normative source for kernel behaviour. Every port (host simulator, M7 Rust, M7 C, future codegen) MUST conform to it via the conformance-vector suite ratified in SOS-03. Drift between a port and the .scxml is a defect in the port, never in the .scxml (the .scxml moves only via §15 amendment to SOS-00-CONCEPTS.md).

## Reference target

Cortex-M7 on the STM32H747I-DISCO (the same board the sibling `disco-analyzer/` subrepo uses). The M7 reference port is the first-class target because:

- It exercises every primitive the kernel needs (PendSV, SVC, SysTick, BASEPRI, MSP/PSP, EXC_RETURN, NVIC priority grouping).
- The hardware is already on the bench for sister work, so bench-flash iterations stay cheap.
- It provides a real-world comparison point against the FreeRTOS-Kernel v11.1.0 vendored at `disco-analyzer/analyzer-rtos/` (see SOS-00 §10 for the reconciliation — SOS and FreeRTOS are siblings, not replacements for each other).

A host-runnable simulator (SOS-02) is the second target, and exists so unit tests and conformance vectors do not require bench access.

## Relationship to the parent repo

SOS is a sibling subrepo to `streamz/submodules/disco-analyzer/`. The two are independent:

- DAA owns the audio-analyzer product on STM32H747I-DISCO and uses FreeRTOS-Kernel as its runtime (see DAA-00 §10, `feedback_freertos_nvic_priority_0`).
- SOS owns the SCXML-driven-kernel methodology and does not ship inside any DAA product. The M7 reference port (SOS-04 / SOS-05) MAY use the disco-analyzer board as a bench substrate, but the SOS kernel never replaces the FreeRTOS-Kernel that DAA runs on.

## Status

Phase 0 (concepts) is in draft. No code is written yet. Per the parent-repo spec-before-code discipline, no implementation lands until `SOS-00-CONCEPTS.md` carries a §15 ratification entry.

See `docs/concepts/README.md` for the phase roadmap.
