<!--
AGENTS.md — Contributor guidance and project conventions for SOS.
-->

# SOS (Statechart-Orchestrated Scheduler)

A minimal RTOS kernel whose **behaviour is specified as a single SCXML statechart** (`rtos_kernel.scxml`), with reference implementations on Cortex-M7 in C and Rust. The science being proved is the methodology: SCXML → multiple equivalent language ports, verified by a shared conformance-vector suite.

This is a **public** repo, MIT-licensed (see [`LICENSE.md`](./LICENSE.md)). Position in the parent tree: `streamz/submodules/SOS/`. Clone via `https://github.com/SoftOboros/SOS.git`; contributors push via the `writable` SSH remote.

## Layout discipline

The top-level mirrors rlvgl / disco-analyzer so structural / semantic searches behave identically across all SoftOboros sub-repos:

```
.
├── AGENTS.md                # this file
├── CLAUDE.md                # agent runbook
├── README.md                # human-facing overview
├── rtos_kernel.scxml        # canonical kernel behaviour spec (NORMATIVE)
├── docs/
│   ├── REFERENCE.md         # human-readable mirror of the .scxml (informative)
│   └── concepts/
│       ├── README.md        # initiative index + phase roadmap
│       ├── SOS-NN-*.md      # phase concepts docs
│       └── ERRATA.md
└── (future) ports/, sim/, conformance/
```

## Single source of truth

`rtos_kernel.scxml` is the normative behaviour spec for the kernel. **All** ports — host simulator, M7 Rust, M7 C, future codegen output — are equivalent only insofar as they satisfy the conformance vectors derived from the .scxml. When in doubt:

1. The `.scxml` wins over `docs/REFERENCE.md`.
2. `docs/REFERENCE.md` wins over informal commentary in PR descriptions, commit messages, or other text.
3. Mutations to the `.scxml` ratify via §15 amendment to `docs/concepts/SOS-00-CONCEPTS.md` first, then land as a single coordinated commit that updates the `.scxml`, `REFERENCE.md`, conformance vectors, and every port.

## Spec-before-code discipline

This subrepo follows the parent-repo discipline (`softoboros.com/CLAUDE.md` § "Spec-Before-Code Planning Discipline"):

- Normative keywords (MUST, SHOULD, MAY) per RFC 2119 / 8174.
- Per-phase docs (`SOS-NN-*.md`) ratify before implementation; ratification = a dated §15 entry.
- Every frozen enum and invariant lives in `SOS-00-CONCEPTS.md`. Touching one requires a §15 amendment **first**, in a separate PR.
- Errata log at `docs/concepts/ERRATA.md` (memalpha shape).
- Stealth reverts of ratified content are prohibited — file an ERRATA entry first, in a separate commit, before any behaviour change that walks back ratified content.

## Source-of-truth boundaries

SOS deliberately keeps a tight crawl boundary so the LLM context budget stays bounded:

- **Do NOT crawl** the M7 hardware reference (RM0399, the Cortex-M7 architectural manual, the WM8994 codec docs, etc.) as part of normal SOS work. Reference them via citations to specific section numbers in SOS-00 §6 (M7 primitive bindings) — that section IS the curated subset SOS depends on.
- **Do NOT crawl** the sibling subrepo's source trees (`streamz/submodules/disco-analyzer/`). SOS's relationship to disco-analyzer is "shares a bench board"; the audio-analyzer code is not a dependency.
- **Do NOT crawl** the FreeRTOS-Kernel sources vendored at `disco-analyzer/analyzer-rtos/`. SOS is a sibling kernel, not a derivative; cross-pollination ratifies via §15 amendment with explicit citation, not implicit copy-paste.
- **Do** consult `docs/concepts/SOS-NN-*.md` and `rtos_kernel.scxml` freely — these are the load-bearing artifacts.

## Build commands

(none yet — phases 1/2/3 produce the simulator, the conformance harness, and the first M7 port. This section will populate as phases ratify.)

## Issue tracking

GitHub Issues is the intake surface. Triaged-and-accepted issues move into `docs/concepts/ERRATA.md` as `ERRATA-NNN` entries with stable identifiers — see parent CLAUDE.md "per-initiative ERRATA.md" convention. The errata log is the inward-facing institutional memory; resolved entries stay there as permanent record.
