# SOS-04-A — Declarative Port-Config Surface & Per-Task Stack Placement

**Status:** 🟡 **drafted 2026-06-01** — **proposed by the sibling disco-analyzer DAA-08
initiative** (REQ-SOS-3/4), and the realisation of SOS-04's pre-existing future-amendment marker
**FAM-04-A (configurable stacks)**. Open PCDNs pending; awaiting SOS-owner ratification. No
implementation lands until this doc carries a §15 ratification entry.

## 0. Authority policy

Sub-letter of SOS-04 (M7 reference ports). SOS-04 owns the port architecture; SOS-04-A **adds** a
declarative **port-config surface** — a chart-level / port-level description of the task table,
semaphore table, tick rate, and **per-task stack placement** — that the port emitter lowers to the
static allocations currently hard-coded in SOS-04 §6.3. It binds the placement to SOS-09's
protection-zone model for optional MPU emission.

| Concern | Owner | SOS-04-A relationship |
|---|---|---|
| Port architecture, `KERNEL_STACK`/`TASK_STACKS` model, syscall wrappers | SOS-04 §6 | **extend** — replaces uniform hard-coded stacks with a declared, heterogeneous table (FAM-04-A) |
| Per-task region placement + access attributes + MPU | SOS-09-A / SOS-09-G | **compose** — stack-region affinity lowers through SOS-09 |
| Kernel datamodel (`MAX_TASKS`, `MAX_PRIO`, `SOS_TICK_HZ`) | SOS-00 | Consumed; the surface declares instances, not new kernel semantics |
| The config surface schema | This doc | `own` |

## 1. Purpose

1. Define a **declarative port-config surface** so a port's task/sem/tick configuration is
   *declared* rather than hand-coded as linker constants (SOS-04 §6.3 currently fixes
   `TASK_STACK_WORDS = 512` uniformly for all `MAX_TASKS`).
2. Support **heterogeneous, per-task stack sizes** and **per-task stack-region placement** (a named
   linker section / memory region per task), realising FAM-04-A.
3. Make the surface the single input that the SOS-04 (Rust) and SOS-05 (C) emitters consume, so the
   same declaration produces both ports' static allocations + `task.create` sequence.

## 2. Problem statement

**Current SOS-04 (§6.3).** `TASK_STACKS` is `#[link_section = ".task_stacks"] static mut [[u32;
TASK_STACK_WORDS]; MAX_TASKS]` — one uniform stack size, one region, for every task. Stack sizes and
allocation are hard-coded linker-script constants; there is **no config-declaration mechanism**
(confirmed by FAM-04-A, the SOS-04 future-amendment marker for "configurable stacks").

**Consumer need (cited, not crawled).** DAA-08 §7 places two requirements:

- **REQ-SOS-3** — declare a port-config surface (task table: id/prio/stack-size/entry; sem table;
  `SOS_TICK_HZ`) equivalent to a hand-written RTOS config + the static-create call sites.
- **REQ-SOS-4** — place individual task stacks in a *named region* (the consumer's high-priority and
  render tasks need heterogeneous stacks — e.g. 2 KiB and 8 KiB — in a specific SRAM region, not the
  default), which the uniform `TASK_STACKS` array cannot express.

**Why it generalizes.** Heterogeneous per-task stacks + region placement is a baseline expectation
for any non-trivial RTOS port (hot tasks in fast TCM, large tasks in bulk SRAM, ISR-touched buffers
in non-cacheable windows). FAM-04-A already anticipated it; SOS-04-A discharges the marker.

## 3. Glossary

| Term | Definition | Owner relationship |
|---|---|---|
| **Port-config surface** | The declarative description (chart annotation and/or port manifest) of a port's task table, semaphore table, tick rate, and stack placement. | own (SOS-04-A) |
| **Task entry** | One row of the task table: `{ id, prio, stack_words, stack_region, entry_symbol }`. | own |
| **Stack region** | A named linker section / memory region a task's PSP stack is placed in. Distinct per task; default region preserves SOS-04 §6.3 behaviour. | compose (SOS-09 for attributes/MPU) |

## 4. The config surface

### 4.1 Schema (proposed)

A port-config declaration is a set of typed entries. PCDN-SOS-04-A-001 decides the *carrier* (chart
`<sos:task_config>` annotation vs a port-local manifest file vs both); the *schema* below is carrier-
independent:

```
port_config {
  tick_hz: u32                      // default 1000 (SOS-00 §6.6 / PCDN-SOS-00-008)
  kernel_stack_words: u32           // default 1024 (SOS-04 §6.3)
  tasks: [
    { id: u8, prio: u8,             // prio in 0..MAX_PRIO
      stack_words: u32,             // per-task; heterogeneous (FAM-04-A)
      stack_region: symbol,         // named linker section; default ".task_stacks"
      entry: symbol }               // task entry function
  ]
  sems: [ { id: u8, max: u32, initial: u32 } ]
  queues: [ { id: u8, cap: u32 } ]  // empty when unused
}
```

### 4.2 Constraints

- `tasks.len() ≤ MAX_TASKS`; `sems.len() ≤ MAX_SEMS`; `queues.len() ≤ MAX_QUEUES`; `prio < MAX_PRIO`
  (all SOS-00 datamodel bounds — the surface declares instances within the frozen pool sizes, it
  does not change them).
- Task id 0 / prio 0 reserved for idle (SOS-00 boot region) unless the declaration explicitly
  supplies an idle entry.
- `stack_region` defaults to `.task_stacks` → byte-for-byte SOS-04 §6.3 behaviour when unspecified
  (backward compatible).

### 4.3 Emission

The emitter lowers a `port_config` to:

- **Rust (SOS-04):** replaces the uniform `TASK_STACKS` array with per-task
  `#[link_section = "<stack_region>"] static mut [u32; <stack_words>]` allocations + a generated
  boot sequence of `task.create{id,prio}` calls wiring each PSP to its allocation
  (mirrors SOS-04 §6.3 TCB init).
- **C (SOS-05):** the equivalent `__attribute__((section(...)))` arrays + create sequence.
- **Linker:** the named `stack_region` sections must be provided by the port's linker script; the
  surface validates that every referenced region exists (compile-time error otherwise).

### 4.4 SOS-09 composition (optional per-task protection)

A task entry MAY carry a SOS-09-A core-affinity / protection annotation on its `stack_region` (e.g.
a guard region, or — for the observation-membrane pattern — a read-only view of a producer's slot).
When present, SOS-09-G emits the MPU configuration for that region at task-context setup. Absent any
annotation, no MPU region is emitted (SOS-04 §6.3 behaviour). This is the seam through which a
consumer's per-task stack/region protections are declared once and realised across ports.

## 5. Frozen surface (registration policy)

- **`port_config` schema fields (§4.1)** — **Specification Required.** Adding a field (e.g.
  `fpu: bool` per-task, or `core: ALLOWED_CORES` for AMP-preparation per SOS-09-A) requires a
  phase-owner walkthrough update; no SOS-00 §15 amendment, since the surface declares instances
  within already-frozen kernel pools.
- Changing a kernel pool bound (`MAX_TASKS`, etc.) remains **Standards Action** on SOS-00 — out of
  scope for SOS-04-A.

## 6. Acceptance (ratification gates)

- (a) §4.1 schema + §4.2 constraints frozen; the carrier decided (PCDN-SOS-04-A-001).
- (b) §4.3 emission specified for both SOS-04 (Rust) and SOS-05 (C), with the default-region
  backward-compatibility guarantee and the missing-region compile-time error.
- (c) §4.4 SOS-09 composition seam specified (optional; absent → no MPU emission).
- (d) FAM-04-A marked discharged in SOS-04's future-amendment markers.
- (e) all PCDN-SOS-04-A-NNN resolved.
- (f) a worked example: a heterogeneous-stack, multi-region task table (the DAA-08 §2 instance is
  the reference example) lowers correctly in the emitter's host tests.

## 13. Files cited

SOS: `SOS-04-CONCEPTS.md §6.3` (current static-allocation model) + its FAM-04-A marker,
`SOS-05-CONCEPTS.md §6` (C port), `SOS-00-CONCEPTS.md §5/§6.3/§6.6` (datamodel bounds, stack model,
tick), `SOS-09-A-CONCEPTS.md` (core-affinity / `sos:core` + placement enum), `SOS-09-G-CONCEPTS.md`
(MPU emission). Cross-initiative (cited, not crawled): disco-analyzer `DAA-08-A-PORT-CONFIG-AND-PARITY-HARNESS.md §2`
(the worked task/sem/tick instance), `DAA-08-CONCEPTS.md §7` (REQ-SOS-3/4).

## 15. Change log

- **2026-06-01 (drafting)** — SOS-04-A drafted on branch `daa08-amp-proposals`, **proposed by the
  sibling DAA-08 initiative** (REQ-SOS-3/4) and realising SOS-04's **FAM-04-A** marker. Defines a
  carrier-independent `port_config` schema (task table with per-task `stack_words` + `stack_region`,
  sem/queue tables, `tick_hz`/`kernel_stack_words`), lowering to both the SOS-04 Rust and SOS-05 C
  ports, with `.task_stacks` as the backward-compatible default region and a missing-region
  compile-time error. §4.4 adds the optional SOS-09 protection-composition seam. Registration of
  schema fields is Specification Required (instances within frozen kernel pools; no SOS-00
  amendment). **Open PCDNs:** PCDN-SOS-04-A-001 (carrier: chart annotation vs port manifest vs
  both), PCDN-SOS-04-A-002 (whether `core`/AMP-affinity fields land here or wait for SOS-14),
  PCDN-SOS-04-A-003 (idle-task declaration: implicit vs explicit row). Awaiting SOS-owner
  ratification.
