# Agent Runbook

This file is the source of truth for Codex/Claude-style agents working on SOS. README and AGENTS.md are human-facing; this file is the operational checklist.

## Project shape (one-screen summary)

- **What it is:** the **Statechart Orchestration System** (SOS), a spec-before-code methodology + tooling stack whose canonical form is SCXML, whose authoring surface is iState, and whose targets include any language or hardware backend that can host a generated FSM. The v1 demonstration is a minimal preemptive priority-based RTOS kernel whose **behaviour is specified as a single SCXML statechart** at `rtos_kernel.scxml`, with bench-validated reference implementations on Cortex-M7 (STM32H747I-DISCO is the bench board). Cross-phase invariants (INV-SOS-A through H) and AuthorityRelationship matrix live in `docs/concepts/SOS-07-CONCEPTS.md`.
- **Science being proved:** SCXML can specify a non-trivial deeply-embedded behaviour at sufficient precision to drive multiple language ports that are equivalent under a shared conformance-vector suite.
- **Repo position:** `https://github.com/SoftOboros/SOS.git` (public, MIT — see `LICENSE.md`), submodule of parent `softoboros.com` at `streamz/submodules/SOS/`. The `writable` SSH remote (`git@github.com:SoftOboros/SOS.git`) is for contributors with push rights; clones use HTTPS.
- **Spec lineage:** `docs/concepts/SOS-NN-*.md`. SOS-00 is the foundational concepts doc; **draft, not yet ratified**.

## Source-of-truth boundaries (see SOS-00 §0, §4, §9 INV-S1)

The `.scxml` IS the spec. Ports adapt it; they do not amend it.

- **Do NOT crawl** Cortex-M7 architectural manual (ARMv7-M ARM), STM32H747 RM0399, or WM8994 codec docs as part of normal SOS work. SOS-00 §6 distils the M7 primitive contract SOS depends on; that section IS the authoritative subset.
- **Do NOT crawl** sibling subrepo `streamz/submodules/disco-analyzer/`. They share a bench board, nothing more.
- **Do NOT crawl** the FreeRTOS-Kernel vendored at `disco-analyzer/analyzer-rtos/`. SOS is a sibling; cross-pollination ratifies via explicit §15 citation, not implicit copy.
- **Do** read `rtos_kernel.scxml`, `docs/REFERENCE.md`, and every `docs/concepts/SOS-NN-*.md` freely.

This boundary is the load-bearing reason the LLM context window scales with this product. Crossing it silently erodes context budget for everything else.

## Build commands

(none yet — phases 1/2/3 produce the simulator, the conformance harness, and the first M7 ports. This section will populate as phases ratify and build infrastructure lands.)

Expected shape post-phase-3:

```bash
# Host simulator (Rust)
cargo test -p sos-sim

# Conformance harness (host)
cargo test -p sos-conformance

# M7 Rust port (cross-compile to disco-analyzer board)
RUSTFLAGS="-C target-cpu=cortex-m7" \
cargo build --target thumbv7em-none-eabihf -p sos-m7-rust

# M7 C port (CMake-driven; arm-none-eabi-gcc)
cmake --preset m7-disco && cmake --build --preset m7-disco
```

## Workspace layout (target)

```
rtos_kernel.scxml         # canonical kernel spec
docs/REFERENCE.md         # human-readable mirror
docs/concepts/SOS-NN-*.md # phase docs
sim/                      # SOS-02 host simulator + ECMAScript-or-compiled datamodel
conformance/              # SOS-03 conformance vectors + harness
ports/m7-rust/            # SOS-04 Rust port
ports/m7-c/               # SOS-05 C port
```

Phase docs decide each tree's contents; this is the planned shape, not yet realized.

## Running tests

(none yet — SOS-03 ratifies the test harness)

## Bench access

Bench access to the disco-analyzer board is **gated by the parent-repo durable rule** at `feedback_no_speculative_board_reset`: do not `probe-rs reset` or `probe-rs download` the board without an explicit per-round authorization signal from the user. Read-only `probe-rs` operations (memory reads, register snapshots, brief halt-and-resume that doesn't modify flash) are permitted.

When SOS-04 / SOS-05 reaches bench validation, agents follow the per-round authorization model documented in the parent CLAUDE.md "Bench-hardware authorization" section.

## NVIC priority discipline

The parent-repo durable rule `feedback_freertos_nvic_priority_0` ("FreeRTOS + NVIC priority 0 = wedge") applies to SOS by extension. The SOS kernel-aware ISR set (PendSV, SVC, SysTick, plus any user-installed `*_from_isr`-driving sources) MUST follow the priority discipline ratified in SOS-00 §6. **Priority 0 is reserved** (highest) and SOS kernel-aware ISRs MUST be at priority `≥ 0xA0` on the M7 (mirroring the value documented at `disco-analyzer/analyzer-cm7/src/hsem.rs:158` for HSEM0). The SOS-00 §6 binding restates this; do not rely on memory alone.
