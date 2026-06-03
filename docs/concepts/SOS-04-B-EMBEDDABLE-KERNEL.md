# SOS-04-B — Embeddable Kernel: Real Task-Body Execution & Host-App Library API

**Status:** **DRAFT 2026-06-03** (branch `daa08-amp-proposals`; §15). Awaiting ratification.
This is a **terms / spec** doc: it pins how the SOS-04 M7 port grows from a *scheduling /
conformance model* into an **embeddable RTOS that executes real application task bodies** and
exposes a consumable kernel-library API. **NO code lands under SOS-04-B itself** — the three
PCDNs (§5) must ratify first; implementation lands as follow-up commits citing this doc's §15.

**Proposed by the sibling disco-analyzer DAA-08 initiative** (REQ-SOS-1/2 at the *real-execution*
level, beyond the model level G-A0 already proved). DAA-08-B (the analyzer's `sos` CM7 build)
cannot proceed until this lands: it needs to host real `audio`/`render` task functions on the SOS
kernel, and the current port runs no task bodies.

## 0. Authority policy

Sub-letter of SOS-04 (M7 reference port). SOS-04 owns the port architecture (§6 static
allocations, §6.4 PendSV, §6.5 BASEPRI critical sections, §6.8 boot). SOS-04-B **extends** it with
two capabilities the conformance-model port does not have:

1. **Task-body execution** — `task.create` primes a real PSP stack frame so PendSV can context-
   switch *into application code*, not just model TCB state.
2. **A host-app library API** — a `no_std` library surface a foreign `bin` (e.g. the disco
   analyzer's `analyzer-cm7`) links against to create tasks with entry functions, start the
   scheduler, and give/take semaphores from task and ISR context.

| Concern | Owner | SOS-04-B relationship |
|---|---|---|
| Kernel state machine (scripts/macrostep, Tcb pool, sem/queue) | SOS-00 / SOS-04 §6.3 | **mirror** — reused unchanged; SOS-04-B adds a real-execution *front-end*, not new model semantics |
| PendSV save/restore, EXC_RETURN, BASEPRI crit | SOS-04 §6.4/§6.5 | **extend** — adds first-switch stack-frame priming; PendSV body otherwise unchanged |
| Trace wire format / byte-equality | SOS-02 §7 / SOS-03 INV-S-CONF-1 | **mirror** — unchanged; entry-fn + PSP priming are port-layer, NOT serialized model state |
| The embeddable kernel library API | This doc | `own` |
| The analyzer's consumption of that API | disco-analyzer DAA-08-B | `derive`/`compose` (consumer; cited, not crawled) |

Per INV-D27 (DAA side) / INV-S10/S11 (SOS side): the embeddable capability ratifies **here, in
SOS's lineage, first**; DAA then consumes it via the published library API and bumps the parent
submodule pin. DAA does not fork the kernel's stack-priming/PendSV internals.

## 1. Purpose

Let a host application run its own tasks on the SOS kernel:

1. Define the **task-entry ABI** and **PSP stack-priming** so a created task's first PendSV switch
   "returns" into an application entry function (the missing piece `handlers.rs:242-255` registers).
2. Expose a **`no_std` kernel-library API** (create task with entry fn + stack region, start
   scheduler, `sem_take` blocking, `sem_give_from_isr`, tick hook) that a foreign `bin` links —
   the SOS equivalent of the analyzer's `analyzer-rtos` surface (`scheduler::init(audio_entry,
   render_entry)`, `sync::AudioSemaphore::{take_blocking, give_from_isr}`).
3. Keep the **conformance-model firmware and its byte-equal traces unchanged** — one kernel core,
   two front-ends (the SOS-02/03 vector driver; and the new real-execution host API).

## 2. Problem statement

**Evidence, pinned to `HEAD` of branch `daa08-amp-proposals` (2026-06-03).**

### 2.1 The port runs no task bodies

- `task.create` carries only `{id, prio}` — no entry function:
  `ports/m7-rust/sos-m7-rust/src/scripts.rs:361,366` (`script_sys_idle_task_create_0`,
  `EventData::TaskCreate { id, prio }`).
- The port self-documents the gap: `ports/m7-rust/sos-m7-rust/src/handlers.rs:242-255` —
  *"v1 doesn't run actual tasks … [PSP] is uninitialised for idle (no task body, no PSP setup) …
  initialises `TASK_PSPS[i]` at task.create time so PendSV"* [can switch into bodies].
- The state for real switching exists (`kernel::{TASK_STACKS, TASK_PSPS, TASK_SAVED_FRAMES}`,
  `handlers.rs` PendSV body with `EXC_RETURN 0xFFFFFFFD`) — but no path primes an entry-fn frame.

### 2.2 The kernel is bin-only — no consumable library

- `ports/m7-rust/sos-m7-rust/Cargo.toml` declares only `[[bin]]`; there is no `lib.rs`. The kernel
  is reachable only from the crate's own `main` + the conformance dispatch loop
  (`main.rs:150` `kernel::init()`, `scripts::dispatch_event`).
- `kernel.rs` exposes `pub fn init()` and pub *state*, but no callable "create task with entry /
  start scheduler / sem op" API a foreign crate can drive.

### 2.3 The consumer need (cited, not crawled)

The disco-analyzer's RTOS surface (its FreeRTOS reference, `analyzer-rtos`) is minimal and is what
an SOS-hosted build must reproduce:

- `scheduler::init(audio_entry, render_entry) -> !` — create two tasks (with entry fns) + start.
- `sync::AudioSemaphore::{take_blocking(), give_from_isr() -> bool}` — binary sem, task + ISR.
- `scheduler::handle_systick()` — 1 kHz tick.

(DAA-08 §2.1 / DAA-08-A §2 task table; DAA REQ-SOS-1/2. G-A0 — SOS conformance vector
`daa08-analyzer-two-task-hsem-wake` — already proved the *model* reproduces this; SOS-04-B is the
*real-execution* counterpart.)

## 3. Glossary

| Term | Meaning | Owner |
|---|---|---|
| **Embeddable kernel** | The SOS-04 kernel exposed as a `no_std` library a host `bin` links and drives, with real task-body execution. | own (SOS-04-B). |
| **Task entry ABI** | The signature + calling/stack convention by which a host registers a task body and the kernel primes its first-run PSP frame. | own. |
| **PSP stack priming** | Writing an initial Cortex-M exception-return frame to a task's PSP region at create time so the first PendSV switch lands in the entry fn. | own (extends SOS-04 §6.4). |
| **Real-execution front-end** | The driver that feeds the kernel from real ISRs/syscalls and runs task bodies — as opposed to the SOS-02/03 conformance-vector front-end. | own. |
| **Host app** | A foreign `bin` (e.g. `analyzer-cm7`) that links the embeddable kernel and supplies the task entry functions + ISRs. | consumer (DAA-08-B). |

## 4. Source-of-truth map (additions for SOS-04-B)

| Component | Pinned form | Used surface | Spec ref |
|---|---|---|---|
| Kernel state machine | `scripts.rs` `dispatch_event` + `kernel.rs` pools | macrostep, Tcb/sem state — reused unchanged | SOS-00 §5, SOS-04 §6.3 |
| PendSV / EXC_RETURN | `handlers.rs` | save/restore body; SOS-04-B adds first-switch priming | SOS-04 §6.4 |
| BASEPRI critical section | `handlers.rs` / SOS-04 §6.5 | the DirectCallBasepri envelope syscalls run under | SOS-00 PCDN-SOS-00-002, SOS-04 §6.5 |
| Trace serialization | `sos-m7-rust-trace` | unchanged; not extended by SOS-04-B | SOS-02 §7 |
| The kernel-library API | this doc §5 (frozen on ratification) | host-app create/start/sem/tick surface | SOS-04-B §5 |

## 5. Frozen decisions (PCDNs — awaiting ratification)

### 5.1 PCDN-SOS-04-B-001 — Library packaging

**How is the kernel exposed to a host `bin`?**
- **(A) bin+lib in the existing crate** — add `src/lib.rs` to `sos-m7-rust`; the conformance `bin`
  consumes the lib; host apps depend on `sos-m7-rust` as a lib. *Con:* host pulls the crate's
  `json_parser`/`transport` deps it doesn't need.
- **(B) extract a `sos-m7-rust-kernel` lib crate** — kernel core (kernel/handlers/scripts/event) +
  the embeddable API in a dependency-light `no_std` lib; both the conformance `bin` and host apps
  depend on it. *Pro:* clean consumer surface; *Con:* a one-time extraction/refactor.
- **(C) feature gate** — an `embed` Cargo feature on `sos-m7-rust` that exposes the API + drops the
  conformance front-end. *Con:* a host still depends on the bin crate; feature-unification risk.

**Recommendation: (B).** Cleanest consumer contract (analyzer-cm7 depends only on the kernel lib),
and it makes "one kernel core, two front-ends" structural. *Decision: __pending__.*

### 5.2 PCDN-SOS-04-B-002 — Task entry ABI & stack priming

**How does a host register a task body, and what frame is primed?**
- Entry signature options: **(A)** `extern "C" fn() -> !` (never returns; matches the FreeRTOS
  task convention the analyzer uses); **(B)** `extern "C" fn(arg: *mut ()) -> !` (one arg pointer,
  passed in R0); **(C)** `fn()` with a kernel-installed task-exit trap if it returns.
- Priming: at create time, write a Cortex-M basic exception-return frame to the task's PSP region
  in `kernel::TASK_STACKS[i]` and set `TASK_PSPS[i]`: `xPSR = 0x0100_0000` (Thumb), `PC = entry`,
  `LR = task_exit_trap`, `R0 = arg` (or 0), `R1..R3/R12 = 0`; 8-byte-aligned. The embedded
  `task.create` gains an `entry`/`stack_region` parameter; the SOS-02/03 event-model `task.create`
  stays `{id, prio}` (additive — entry/PSP are not serialized model state, see PCDN-003).

**Recommendation: (A)** `extern "C" fn() -> !` + a `task_exit_trap` that faults/halts (a returning
task is a bug), R0=0. *Decision: __pending__.*

### 5.3 PCDN-SOS-04-B-003 — Syscall / ISR execution model & conformance compatibility

**How do real-context syscalls bridge to the macrostep, and is the trace model preserved?**
- `sem_take(sid, timeout)` runs from a **task** context; `sem_give_from_isr(sid)` and the tick run
  from **ISR** context. Each enters the kernel via the **DirectCallBasepri envelope** (SOS-00
  PCDN-SOS-00-002 / SOS-04 §6.5): mask with BASEPRI, run the existing `dispatch_event` macrostep
  (including any `sched.run`), unmask, then **pend PendSV** iff `current` changed — the real
  context switch happens on PendSV exit (SOS-04 §6.4), exactly as the model computes `current`.
- **Conformance compatibility (the load-bearing constraint):** the kernel **core** (state machine,
  `Tcb` serialization, macrostep) is **unchanged**; the embeddable additions (entry fn, PSP
  priming, real ISR/syscall front-end, PendSV pend) are **port-layer**, never serialized. The
  SOS-02/03 conformance front-end keeps driving via `dispatch_event` with no task bodies and
  emits byte-identical traces (INV-S-CONF-1 intact). One kernel core, two front-ends.

**Recommendation: as stated** (DirectCallBasepri + pend-PendSV; model/trace unchanged).
*Decision: __pending__.*

### 5.4 Registration policy

- **Kernel-library API surface (§5 once ratified):** *Specification Required* — adding/altering an
  API entry needs a SOS-04-B walkthrough update; no SOS-00 §15 amendment (it exposes existing
  kernel pools/semantics, it does not change them).
- **Task entry ABI (PCDN-002):** *Standards Action* on SOS-04-B — it is a cross-port contract
  (SOS-05 C port must mirror it); changing it requires a §15 amendment here.

## 6. Invariants

- **INV-S-EMBED-1 — Model/trace immutability.** SOS-04-B MUST NOT change the kernel state machine,
  `Tcb` serialization, or any byte of a conformance trace. Embeddable additions are port-layer.
  (Subordinate to SOS-03 INV-S-CONF-1.)
- **INV-S-EMBED-2 — One kernel core, two front-ends.** The conformance-vector driver and the
  real-execution host API drive the *same* macrostep core; neither forks kernel semantics.
- **INV-S-EMBED-3 — Host owns app, kernel owns scheduling.** The host supplies task entry fns,
  ISRs (HSEM doorbell, peripherals), and the idle body if it overrides the default; the kernel owns
  task lifecycle, the scheduler, PendSV/SysTick/SVC, and BASEPRI critical sections. A host MUST NOT
  hand-roll context switching (that is INV-D27's reciprocal on the SOS side).

## 7. Non-goals

- **SMP / second core.** Unchanged from SOS-00 §11 / SOS-14 (the analyzer's CM4 stays bare-metal).
- **Dynamic/heap task allocation.** Static pools only (SOS-00 INV-S12); the host supplies stack
  regions via the SOS-04-A `port_config` surface.
- **Changing the conformance model or trace format.** Explicitly preserved (INV-S-EMBED-1).
- **The analyzer's `sos` feature itself.** That is DAA-08-B (consumer), not SOS-04-B.
- **Authoring the AMP/HSEM medium.** That is SOS-14; SOS-04-B only requires that
  `sem_give_from_isr` be callable from the host's HSEM0 ISR.

## 8. Acceptance (ratification gates)

- (a) PCDN-SOS-04-B-001/002/003 each resolved with a chosen value + updated prose.
- (b) The §5 kernel-library API is enumerated (function signatures) and frozen.
- (c) INV-S-EMBED-1..3 stated; the model/trace-immutability guarantee is explicit and testable
  (the existing 7-vector conformance suite MUST still pass byte-equal after implementation).
- (d) A worked acceptance target for the implementation phase: a minimal two-task host example
  (idle + one task that `sem_take`s, woken by a `sem_give_from_isr` from an IRQ) runs on the port
  and the existing conformance suite is unaffected — the SOS-side mirror of DAA-08 G-A1/G-A2.
- (e) §13 files-cited complete; §15 dated ratification entry.

## 13. Files cited

SOS: `ports/m7-rust/sos-m7-rust/src/scripts.rs:361,366` (task.create event handler),
`ports/m7-rust/sos-m7-rust/src/handlers.rs:242-255` (the registered "v1 runs no tasks" gap) + the
PendSV body, `ports/m7-rust/sos-m7-rust/src/kernel.rs` (`TASK_STACKS`/`TASK_PSPS`/
`TASK_SAVED_FRAMES`, `pub fn init`), `ports/m7-rust/sos-m7-rust/src/main.rs:150` (kernel::init +
dispatch loop), `ports/m7-rust/sos-m7-rust/Cargo.toml` (bin-only), `docs/concepts/SOS-04-CONCEPTS.md`
§6.3/§6.4/§6.5/§6.8, `docs/concepts/SOS-04-A-PORT-CONFIG-SURFACE.md` (stack regions / sub-letter
precedent), `docs/concepts/SOS-00-CONCEPTS.md` §5/§6 + PCDN-SOS-00-002, `docs/concepts/SOS-03-CONCEPTS.md`
INV-S-CONF-1. Consumer (cited, not crawled): disco-analyzer `DAA-08-A` §2/§5, `DAA-08` §7
REQ-SOS-1/2.

## 14. Unblocks

- **DAA-08-B** — the analyzer's `sos` CM7 build hosts `audio`/`render` on this API.
- **SOS-05-B (mirror)** — the C port mirrors the task entry ABI (PCDN-002 is Standards Action so the
  two ports stay in lockstep).
- **SOS-14 consumption** — the AMP/HSEM doorbell medium's CM7 side calls `sem_give_from_isr`.

## 15. Change log

- **2026-06-03 (drafting)** — SOS-04-B drafted on branch `daa08-amp-proposals`, **proposed by the
  sibling disco-analyzer DAA-08 initiative** (REQ-SOS-1/2 at real-execution level). §2 pins the
  evidence: the port runs no task bodies (`scripts.rs:366` create is `{id,prio}`-only;
  `handlers.rs:242-255` self-documents the gap) and is bin-only (no consumable library). §5 raises
  three PCDNs (library packaging; task entry ABI + PSP priming; syscall/ISR execution model +
  conformance compatibility). §6 adds INV-S-EMBED-1..3 (model/trace immutability; one core / two
  front-ends; host-owns-app/kernel-owns-scheduling). **Awaiting ratification** — no code lands until
  the three PCDNs resolve.
