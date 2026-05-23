# SOS-00 — Statechart-Orchestrated Scheduler: Concepts and Source-of-Truth Map

**Status:** **🟢 Ratified 2026-05-19.** All eleven PCDN open questions resolved; §15 carries the ratification entry. Per the parent CLAUDE.md spec-before-code discipline, implementation phases (SOS-01 onward) are unblocked.

**Blocks:** SOS-01, SOS-02, SOS-03, SOS-04, SOS-05, SOS-06 (unblocked at ratification).

> 🛑 **NO CODE.** Vocabulary, source-of-truth map, frozen enums, M7 primitive bindings, and invariants only. Phase 0 ratifies the framing; sub-letter phases (SOS-NN-X) decompose execution.

### Load-bearing resolution: "M7 primitives as references" (PCDN-SOS-00-011, resolved 2026-05-19)

The user-facing prompt's phrase "M7 primitives as references in the state machine" admits three plausible readings:

1. **Annotate the chart** — embed M7 primitive references (`sys.tick → SysTick`, `pick_next → PendSV`, `crit.enter → BASEPRI`) as informative comments inside the `.scxml`.
2. **Implement against** — the chart stays target-agnostic; M7 primitives appear concretely in the **port code** (CMSIS-Core headers + intrinsics for the C port; the `cortex-m` crate for the Rust port). The chart's abstract events are mapped to those primitives in this doc's §6, not in the chart itself.
3. **Model them in-chart** — add an `<state id="mcu">` region with `PRIMASK` / `BASEPRI` / `PendSV-pending` as datamodel fields.

**Resolved: reading 2.** *"We want the primitives to live in the project, not the state chart."* The `.scxml` is target-agnostic and stays that way (INV-S15 below). M7 primitives live in the per-port crates (`ports/m7-rust/`, `ports/m7-c/`). The mapping `(abstract event ↔ M7 primitive)` lives in this doc §6 and in the port-specific phase docs SOS-04 / SOS-05; it does NOT live in the chart.

This resolution governs every section below. Where §6 names CMSIS or cortex-m primitives, it is naming the **port-side** library surface, not extending the chart.

## 0. Authority policy

This doc is the **single normative source** for SOS-side vocabulary, frozen enums, M7 primitive bindings, and invariants. The kernel's **behaviour** is normative-by-reference to `rtos_kernel.scxml`; this doc governs the spec **around** the .scxml (terms, file conventions, port obligations, M7 mapping) and ratifies amendments to the .scxml itself via §15 entries.

The authority split:

| Concern | Owner | SOS relationship |
|---|---|---|
| Kernel behaviour (state machine, syscall ABI at the SCXML event/state level, datamodel) | `rtos_kernel.scxml` | `own` — SOS owns this; the .scxml moves only via §15 amendment to this doc, then a coordinated commit landing the .scxml + REFERENCE.md + conformance-vector regen + every port. |
| SCXML 1.0 datamodel and execution-content semantics | W3C SCXML 1.0 Recommendation (C.R. 2015-09-01) | `derive` — SOS conforms to a documented subset of SCXML 1.0; the .scxml MUST validate against the public schema. The subset is named in §4. |
| ECMAScript subset usable inside `<script>` blocks | ECMA-262 (subset) | `derive` — SOS-01 ratifies the precise subset (no closures over outer-scope, no async, no `eval`, etc.). The host-simulator port (SOS-02) implements the subset by hand or via an embedded engine; that choice ratifies in PCDN-SOS-00-005. |
| Cortex-M7 ISA and exception model (PendSV, SVC, SysTick, BASEPRI, EXC_RETURN, MSP/PSP, NVIC) | ARMv7-M Architecture Reference Manual (ARM DDI 0403E.e) | `derive` — SOS depends on a narrow contract documented in §6 (M7 primitive bindings). §6 is the curated subset SOS reviewers consult; the ARM ARM is NOT a regular crawl target. |
| STM32H747I-specific peripheral usage (SysTick clock source, NVIC vector table layout) | STM32H747xI Reference Manual (RM0399) | `derive` — limited to SysTick clock source selection and the vector table placement. Cited in §6. |
| FreeRTOS-Kernel v11.1.0 sources (vendored at sibling repo `streamz/submodules/disco-analyzer/analyzer-rtos/`) | FreeRTOS project | NOT a dependency. Sibling kernel. Cross-pollination ratifies via explicit §15 amendment with a named delta; implicit copy is forbidden (INV-S10). |
| Conformance vectors | This doc (SOS-03 ratifies the schema; SOS-00 §7 frames it) | `own`. |
| Per-port adaptation (PendSV save/restore code, SVC stub layout, linker script, startup sequence) | Per-port phase doc (SOS-04 for M7 Rust, SOS-05 for M7 C) | `derive` — each port's spec ratifies its bindings to §6; ports MUST NOT amend §6 or §9 invariants. |

INV-S1 (vendor compartmentalization, mirroring DAA-00 INV-D8 and CSG-00 INV-CSG-D1): SOS-side specs and code cite external sources by published reference only. SOS-side reviewers (human or LLM) work from this doc plus the cited section numbers; they do not crawl the ARM ARM, the SCXML 1.0 Recommendation, or the FreeRTOS-Kernel sources as part of normal SOS work. Drilling in is reserved for explicit "the contract surface needs to grow" moments and triggers a §15 amendment.

## 1. Purpose

Establish:

1. The vocabulary that distinguishes **the canonical .scxml-resident behaviour** from **per-port M7 binding details**, so subsequent phase docs and ports can decompose without re-litigating "is this thing in the spec or in the port?".
2. The authority split (§0) that prevents SOS from silently forking SCXML 1.0 semantics, drifting on the M7 contract surface, or coupling itself to FreeRTOS.
3. A canonical glossary (§3) and source-of-truth map (§4) sufficient for downstream phases to cite SOS terms by reference, not by restatement.
4. A frozen-enum set (§5) covering the kernel-side surface (task states, return codes, syscall transport choice) **and** the M7 primitive bindings (§6) covering the hardware-side surface (which interrupt does what, which priority band, which CPU registers).
5. A minimal invariant set (§9) — sufficient to constrain the simulator and both ports without pre-committing every binding detail.
6. The conformance-vector framework (§7) — informative scaffolding for SOS-03.
7. The reconciliation (§10) with the sibling FreeRTOS-Kernel runtime at `disco-analyzer/analyzer-rtos/` — they are independent kernels on the same hardware family; SOS does not replace FreeRTOS, and FreeRTOS does not bound SOS.

Without this layer:

- Each port re-derives the M7 binding details (PendSV save/restore frame, SVC stub layout, BASEPRI mask value) and the resulting ports drift bit-for-bit.
- "What's a syscall vs. what's an ISR" gets re-litigated at every PR.
- The conformance question ("does my port pass?") has no spec-level definition, so port equivalence is opinion-driven.
- Vocabulary drift erodes the value of the .scxml as a spec — if the docs around it call `tcb` "thread control block" in one place, "task descriptor" in another, and "process record" somewhere else, the .scxml stops being a discoverable spec.

## 2. Problem statement

**Current state (as of 2026-05-19):**

- `rtos_kernel.scxml` exists at the repo root (currently `streamz/submodules/SOS/rtos_kernel.scxml`). It is a single-file SCXML 1.0 statechart, ECMAScript datamodel, with four orthogonal regions inside a `<parallel id="running">`: `scheduler`, `tick_service`, `syscalls`, `protection`. Behaviour covers tasks (8 priority levels), counting/binary semaphores, bounded message queues, tick-delays, critical sections, and scheduler suspend. The chart cites a target compiler family ("SoftOboros SCXML compiler family") in its informative §"Code-generation notes" but does not depend on it.
- `docs/REFERENCE.md` is the informative human-readable reference covering the topology, syscall ABI, wait-queue ordering, concurrency / safety invariants, and a six-item testing-surface checklist (formerly `rtos_kernel.md` at top level; moved 2026-05-19 as part of the SOS-00 ratification commit).
- The repo is **two files in a directory**. No build files, no port source, no test harness, no submodule registration in the parent tree (the parent's `git status` shows `streamz/submodules/SOS/` as untracked).
- The intended bench substrate (STM32H747I-DISCO) is already in heavy use by the sibling `disco-analyzer/` subrepo (DAA family). The board has a FreeRTOS-Kernel v11.1.0 + SOS-style task plumbing already in place via DAA-03d. SOS coexists by NOT linking against any of that; bench validation for SOS happens at flash-firmware-swap time (PCDN-SOS-00-001 → default (b)).

**The pressure that motivates SOS-00:**

Three pressures compound:

1. **The .scxml has more semantic content than is enforceable without a spec around it.** Right now it is well-written and internally consistent, but nothing prevents the next edit from breaking the "at most one transition's executable content runs at a time" invariant or rebinding `task.delay` to something else under the same name. The .scxml needs a spec **about** itself.
2. **Two ports (Rust + C) is a stress test of the .scxml as a spec.** If the .scxml is sufficient to drive two ports that pass identical conformance vectors, the .scxml has demonstrated its precision. If it isn't, the gaps surface as port-specific decisions that need to be lifted back into the spec. That feedback loop is the **science** SOS is proving.
3. **The "M7 primitives as references" framing is load-bearing.** The user-facing prompt explicitly named M7 primitives as the reference target. That choice is not arbitrary: PendSV / SVC / SysTick / BASEPRI / EXC_RETURN are the smallest meaningful set of "context switch + protection + tick" primitives at the lowest level the user expects production-grade RTOS work to live at. Tying the spec to that primitive set frames every port decision in concrete terms. A port that hides PendSV behind a "context_switch()" abstraction without specifying how that abstraction lands on the M7 has skipped the science.

**Why this is the right time:**

- The .scxml is small enough (~580 lines) that a foundational concepts doc can address every state and transition without becoming a maintenance burden.
- The sibling `disco-analyzer/` family has produced enough working M7 firmware (DAA-00 through DAA-06; FreeRTOS + bare-metal both shipping) that the M7 primitive contract is well-understood at the team level. SOS-00 §6 distils that knowledge into a curated subset, rather than re-deriving from the ARM ARM.
- The parent-repo durable memory `feedback_freertos_nvic_priority_0` ("FreeRTOS + NVIC priority 0 = wedge") is fresh institutional knowledge that needs to live in a port-level spec (it lands in §6 + §9 INV-S9).

## 3. Canonical glossary

Reserved SOS vocabulary. Capitalised use of these terms in SOS docs MUST refer to the defined meaning; alternative phrasings introduce drift and are forbidden in normative sections.

| Term | Definition | Owner relationship |
|---|---|---|
| **Statechart** | The single SCXML 1.0 document at `rtos_kernel.scxml`. The kernel's normative behaviour. As defined in W3C SCXML 1.0 §3.1 (Document Structure); used without modification. | SOS. |
| **Datamodel** | The ECMAScript-subset state cell defined in the statechart's `<datamodel>` and mutated by `<script>` blocks. As defined in W3C SCXML 1.0 §C.2 (ECMAScript Data Model); SOS subsets per SOS-01 ratification. | W3C / ECMA-262; subset owned by SOS-01. |
| **Macrostep** | A run-to-completion processing of an external event, including all triggered internal `<raise>` events, until quiescence. As defined in W3C SCXML 1.0 §3.13 (Selecting and Executing Transitions); used without modification. | W3C. |
| **Microstep** | One transition firing inside a macrostep. As defined in W3C SCXML 1.0 §3.13; used without modification. The "at most one transition's executable content runs at a time" property is a microstep property. | W3C. |
| **Kernel** | The behaviour the statechart defines, instantiated by a port. There is one statechart and N kernels (one per port: host simulator, M7 Rust, M7 C, future codegen). | SOS. |
| **Port** | An implementation of the kernel on a specific target. Each port has its own SOS-NN phase doc (SOS-02 host simulator, SOS-04 M7 Rust, SOS-05 M7 C). Ports MUST satisfy SOS-00 §9 invariants AND pass SOS-03 conformance vectors. | SOS (port spec); each port's phase doc (port-specific bindings). |
| **Bench port** | A port that runs on real hardware (STM32H747I-DISCO is the v1 reference board). Bench ports additionally satisfy §6 M7 primitive bindings. SOS-04 and SOS-05 are bench ports; SOS-02 is not. | SOS. |
| **Conformance vector** | An input event sequence + the canonical state-trace it produces under the .scxml. Vectors are the **contract** every port satisfies. Format ratified in SOS-03. | SOS. |
| **State trace** | The ordered sequence of `(after_input_idx, observable_state_snapshot)` pairs produced by executing a vector's input. One record per macrostep-quiescence; `after_input_idx` is the zero-based index into the vector's `input` array (`-1` for the boot baseline). "Observable state" is a frozen subset of the datamodel (`current`, `tick_count`, `rc`, each TCB's `(state, prio, deadline, blk_obj, msg)`, ready-queue contents, per-object waiter lists). Details in §7. | SOS. |
| **TCB** | Task Control Block. A datamodel record in `tcb[i]`: `{ id, prio, state, deadline, blk_obj, msg }`. Fixed-size pool; no allocator. The `msg` field is polymorphic (see §5.6 `Msg`) — it carries either a queue payload (`Int`) or the final return code deposited at unblock (`ReturnCode`), or `Null` when no message is staged. As defined in the .scxml; restated here for cross-doc citation. | SOS. |
| **Ready queue** | The array `ready[MAX_PRIO]`, each element a FIFO queue of TIDs at that priority. Ready-queue invariant in §9 INV-S7. | SOS. |
| **Wait-queue** | A per-object FIFO ordered by `tcb[tid].prio` descending, FIFO-within-priority. Lives at `sems[*].waiters`, `queues[*].sendw`, `queues[*].recvw`. Ordering invariant in §9 INV-S8. | SOS. |
| **Syscall** | An external event issued by task code or ISR code to invoke kernel behaviour. Includes the task ops (`task.create/delay/yield/suspend/resume`), semaphore ops (`sem.create/take/give`), queue ops (`queue.create/send/receive`), critical-section and scheduler-lock ops (`crit.enter/exit`, `sched.suspend/resume`), and the ISR-context variants (`sem.give_from_isr`, `queue.send_from_isr`). Does NOT include `sys.tick` (timer-ISR notification — see **Tick** below) or `sched.run` (internal-only, raised by the syscall path). The chart's `syscalls` region name is organisational — not all syscalls live there (`crit.*` / `sched.*` live in `protection`). Frozen full list of external events: SOS-01 §5 `ExternalEventName`. Names + parameter shapes: `docs/REFERENCE.md` § Syscall ABI. | SOS. |
| **Syscall transport** | The per-port mechanism that converts a task-mode function call into a statechart event. PCDN-SOS-00-002 resolves the v1 transport choice. Frozen value ratifies in §5.3. | SOS. |
| **Tick** | The `sys.tick` external event. Source on a bench port is the SysTick exception (§6); source on the host simulator is a synthetic event the harness injects. | SOS. |
| **Critical section** | The interval between a `crit.enter` and matching `crit.exit` event. Modeled by `irq_nest` in the datamodel. Per-port realisation in §6 (BASEPRI mask on M7). | SOS. |
| **Scheduler suspend** | The interval between `sched.suspend` and matching `sched.resume`. Modeled by `sched_lock`. Distinct from critical section: defers reschedule but does NOT mask interrupts. | SOS. |
| **Kernel-aware ISR** | Any ISR that either (a) invokes a `*_from_isr` syscall, or (b) shares data with a `*_from_isr` syscall, or (c) is the SysTick or PendSV exception itself. Kernel-aware ISRs MUST run at NVIC priority ≥ 0xA0 on M7 (§6, §9 INV-S9). | SOS. |
| **Kernel-blind ISR** | An ISR with no kernel interaction. SOS imposes no priority constraint. The port spec MAY install such ISRs at priorities < 0xA0 (i.e. higher than kernel-aware ISRs) for low-latency hardware response. | SOS. |
| **Idle task** | Task 0, reserved at boot, priority 0 (lowest). Runs whenever no other task is READY. Per .scxml boot block. | SOS. |
| **Boot** | The one-shot init macrostep that runs `readyq_init()`, allocates the TCB pool, brings idle to RUNNING, and transitions `boot → running`. As defined in the .scxml; first-class state in the conformance trace's prefix. | SOS. |

## 4. Source-of-truth map

External authorities and the exact surface SOS depends on. **SOS must not reach into these specs outside the cited surface.** Growth ratifies via §15 amendment.

| Source | Pinned form | Used surface | Relationship |
|---|---|---|---|
| W3C SCXML 1.0 Recommendation | Recommendation, 1 September 2015 | Document structure (§3.1), datamodel (§C.2 ECMAScript), executable content (`<script>`, `<raise>`, `<assign>`, `<if>`), transition selection + macrostep semantics (§3.13), `<parallel>` region semantics (§3.4). | `mirror`. The .scxml validates against the public schema (https://www.w3.org/2011/04/SCXML/scxml.xsd). |
| ECMA-262 (ECMAScript) | A documented SOS-01 subset | Arithmetic, comparison, array `push` / `shift` / `splice` / `indexOf`, object property access, conditional `if/else`, `for` loops, `var` declarations. **No** closures, `async`, `await`, `eval`, `Function` constructor, regex, prototype mutation. SOS-01 freezes the exact subset. | `derive`. |
| ARMv7-M Architecture Reference Manual (ARM DDI 0403E.e) | E.e (current at time of writing) | Exception model (B1.5), exception priority (B1.5.4), priority grouping (B3.2.10), PendSV / SVC / SysTick exception types (B1.5.2), MSP/PSP usage (B1.4.4), EXC_RETURN values (B1.5.8), BASEPRI / PRIMASK / FAULTMASK (B1.4.3), FPU lazy stacking (B1.5.10, A2.7). | `derive`. §6 is the curated subset SOS depends on. |
| STM32H747xI Reference Manual (RM0399) | Rev 4 or later | SysTick clock source selection (§35.3.2), NVIC vector table placement (§D1.2.3), priority grouping default. | `derive`. |
| FreeRTOS-Kernel v11.1.0 | Vendored at `disco-analyzer/analyzer-rtos/FreeRTOS-Kernel/` in the sibling subrepo | **NOT used.** Listed to make the negative explicit: SOS does not link FreeRTOS, does not copy from its sources, and does not depend on its symbols. SOS is allowed to **borrow vocabulary** (TCB, ready queue, tickless idle as a non-goal in §11) because that vocabulary is industry-standard; vocabulary borrowing is `mirror`, code borrowing would be `extend` and is forbidden by INV-S10. | not-a-dep. |
| `rtos_kernel.scxml` (this repo) | Pinned to a SHA per port via §15 entry | The full statechart. Every state, every transition, every script block, every datamodel field. | `own`. |
| `docs/REFERENCE.md` (this repo) | This repo, this SHA | Topology overview, syscall ABI table, wait-queue ordering, testing-surface checklist. Informative; the .scxml is authoritative when the two disagree. | `own`. |

### 4.1 Port-side library surfaces (per PCDN-SOS-00-011 reading 2)

The .scxml is target-agnostic. The M7 primitives the user named (PendSV, SVC, SysTick, BASEPRI, PRIMASK, MSP/PSP, EXC_RETURN) appear **in the ports**, sourced from two library surfaces, one per port:

| Library | Port | Used surface | Pinned at | Relationship |
|---|---|---|---|---|
| **CMSIS-Core (Cortex-M7)** | SOS-05 (C port) | `core_cm7.h`, `cmsis_gcc.h` intrinsics. Specific surface: `__set_BASEPRI`, `__get_BASEPRI`, `__disable_irq` / `__enable_irq`, `__DSB`, `__ISB`, `__WFI`, `NVIC_SetPriorityGrouping`, `NVIC_SetPriority`, `NVIC_EnableIRQ`, `SCB->ICSR` (for PendSV pending), `SysTick->LOAD` / `CTRL` / `VAL`. Naked-function PendSV and SVC handlers use inline assembly via `__asm volatile (...)`. | The CMSIS-Core version that ships with the toolchain pin SOS-05 ratifies (intent: a recent CMSIS 5 release; v5.9.0+ as the floor). | `adapt`. CMSIS-Core is consumed verbatim; the SOS-side affordance is the wrapper translating SOS event semantics into CMSIS calls. CMSIS itself is unchanged. |
| **`cortex-m` crate (Rust)** | SOS-04 (Rust port) | v0.7.x API: `cortex_m::register::basepri`, `cortex_m::register::primask`, `cortex_m::register::control`, `cortex_m::peripheral::SCB`, `cortex_m::peripheral::SYST`, `cortex_m::peripheral::NVIC`, `cortex_m::asm::{dsb, isb, wfi}`, `cortex_m::interrupt::free`. PendSV / SVC handlers via `#[exception]` from `cortex-m-rt`. | `cortex-m = "0.7"` (latest 0.7.x at SOS-04 ratification); `cortex-m-rt` matching. | `adapt`. Same shape as CMSIS — `cortex-m` is consumed verbatim; SOS owns the wrapper that turns SOS events into `cortex-m` register / peripheral calls. |

**Negative listing (to make the boundary explicit):**

- The .scxml MUST NOT name CMSIS or `cortex-m` symbols. The chart's vocabulary stops at abstract events (`sys.tick`, `crit.enter`, `sched.run`, etc.).
- The host simulator (SOS-02) MUST NOT depend on `cortex-m`. Its target is `cfg(not(target_os = "none"))` — host OS, integer math only.
- The port crates (SOS-04, SOS-05) MUST NOT redefine the SCXML event vocabulary. They translate it; they do not amend it.

## 5. Frozen enums

SOS ratifies five frozen enums at Phase 0. Each carries a registration policy per the parent CLAUDE.md convention.

### 5.1 `TaskState` — Standards Action

The values legal for `tcb[i].state`. Frozen values (mirror of the .scxml `ST_*` constants):

| Name | Numeric | Meaning |
|---|---|---|
| `ST_DORMANT` | 0 | TCB slot unused. |
| `ST_READY` | 1 | In a `ready[prio]` queue, eligible to run. |
| `ST_RUNNING` | 2 | `current == id`, removed from `ready[]`. |
| `ST_DELAY` | 3 | Time-blocked, on no waiter list. |
| `ST_BLK_SEM` | 4 | On `sems[blk_obj].waiters`. |
| `ST_BLK_QS` | 5 | On `queues[blk_obj].sendw`, msg pending. |
| `ST_BLK_QR` | 6 | On `queues[blk_obj].recvw`. |
| `ST_SUSPEND` | 7 | Off all lists, awaits explicit resume. |

Adding a value requires a §15 amendment to this doc, a corresponding `.scxml` data declaration, and an update to every port. **Reserved (not legal yet):** `ST_BLK_MTX` (mutex hold), `ST_BLK_EVT` (event group) — explicit non-goals per §11.

### 5.2 `ReturnCode` — Standards Action

The values legal for `rc` and for the `msg` field deposited at unblock. Frozen values (mirror of the .scxml `RC_*` constants):

| Name | Numeric | Meaning |
|---|---|---|
| `RC_OK` | 0 | Success. |
| `RC_TIMEOUT` | -1 | Wait expired. |
| `RC_FULL` | -2 | Queue or semaphore at capacity. |
| `RC_EMPTY` | -3 | Queue empty on poll. |
| `RC_INVAL` | -4 | Invalid argument (bad object id, bad state). |

Adding a value requires a §15 amendment.

### 5.3 `SyscallTransport` — Standards Action (resolved at PCDN-SOS-00-002 → (b) default)

Per-port mechanism that delivers a syscall event to the statechart. Frozen values:

- `SvcInstruction` — task code issues an `svc #imm` with the syscall id in `imm`; the SVC handler is the kernel entry. Task code runs unprivileged (PSP, CONTROL.nPRIV=1).
- `DirectCallBasepri` — task code calls an ordinary C/Rust function; the function raises BASEPRI to the kernel-aware mask, mutates kernel state, lowers BASEPRI on return. All tasks privileged.

**v1 (ratified per PCDN-SOS-00-002):** `DirectCallBasepri`. Lower complexity; sufficient for the conformance ports. **Stipulation:** migration to `SvcInstruction` is a planned future amendment (not an open option for indefinite deferral). The port architecture MUST keep the syscall transport as a single localised layer (per-syscall wrappers, no transport-specific logic in the kernel body) so the migration is a localised diff. A subsequent phase (likely a `SOS-04-B` / `SOS-05-B` amendment) will ratify the migration once the v1 ports are conformance-validated.

### 5.4 `M7KernelPriorityBand` — Standards Action

The NVIC priority bands SOS reserves on M7. Frozen values (lower numerical value = higher priority on ARMv7-M):

| Band | Priority range (hex) | Semantics |
|---|---|---|
| **System-reserved** | `0x00`–`0x9F` | **Forbidden** for SOS-installed handlers. Includes the parent-repo durable rule "never set an ISR to priority 0 under SOS" (mirroring `feedback_freertos_nvic_priority_0`). |
| **Kernel-aware** | `0xA0`–`0xEF` | Mandatory band for any ISR that interacts with the kernel (`*_from_isr` callers, SysTick, PendSV). PendSV MUST be at the **lowest** kernel-aware priority (`0xE0` recommended) so it cannot preempt other kernel-aware ISRs. SysTick MUST be at a kernel-aware priority strictly higher than PendSV. |
| **Kernel-blind** | `0xF0`–`0xFF` | Available for low-priority background work that doesn't touch the kernel. (Intentionally below kernel-aware; the conventional "above kernel-aware for fast hardware" slot is the system-reserved band, which SOS forbids — see INV-S9 commentary.) |

INV-S9 commentary: the choice to forbid the `<0xA0` band (rather than allowing low-numerical-priority kernel-blind ISRs) is deliberate. SOS-aware code cannot reason about ISR pre-emption from a band it does not control; granting that band to "kernel-blind" code makes "blind" meaningful only by convention, not by spec. A port that needs ultra-low-latency hardware response must declare it explicitly and ratify a §15 amendment.

### 5.5 `FpuPolicy` — Standards Action (resolved at PCDN-SOS-00-003 → (a) default)

How the M7 port handles the FPU. Frozen values:

- `LazyStackingEnabled` — `FPCCR.LSPEN=1`, `FPCCR.ASPEN=1` (reset defaults). FPU state is stacked only on first FP instruction post-exception. PendSV inspects `EXC_RETURN` bit 4 to decide whether to save/restore S0–S31 + FPSCR.
- `LazyStackingDisabled` — `FPCCR.LSPEN=0`, `FPCCR.ASPEN=0`. All tasks treated as integer-only; FPU usage in tasks is undefined behaviour.

**v1 (ratified per PCDN-SOS-00-003):** `LazyStackingEnabled`. M7 reset default; preserves FPU usability; PendSV inspection of `EXC_RETURN[4]` is a few extra instructions.

### 5.6 `Msg` — Standards Action

The discriminated-union type carried in the polymorphic `tcb[i].msg` field. The chart's ECMAScript datamodel tolerates dynamic polymorphism at runtime; ports MUST realise the type explicitly. Frozen variants:

| Variant | Carries | Set when |
|---|---|---|
| `Null` | nothing | TCB initialisation; default rest state for non-blocked / non-waiting TCBs. |
| `Int(i64)` | queue payload | A queue-send caller stages its outgoing payload in `tcb[current].msg` before blocking (see `queue.send` in the .scxml when `q.count == q.cap && d.timeout != 0`); a queue-receive caller's pulled payload lands here at unblock. |
| `ReturnCode(ReturnCode)` | one of `RC_OK / RC_TIMEOUT / RC_FULL / RC_EMPTY / RC_INVAL` | At unblock from a blocked syscall (sem.take, queue.send, queue.receive, task.delay): the final result is deposited into `tcb[id].msg` by the unblocker (`tick_service` tick-expiry path, `sem.give`, `queue.send`, `queue.receive`). |

The discriminator is **on-wire** in the trace JSONL form (per Amendment 004; supersedes the off-wire form ratified by Amendment 003). The conformance trace's `tcb[i].msg` field serialises as:

| Variant | JSONL form |
|---|---|
| `Null` | `null` |
| `Int(N)` | `N` (bare signed integer) |
| `ReturnCode(rc)` | `{"rc": <i8>}` (tagged object with the `RC_*` discriminant value) |

This makes the harness diff-trivial and the port-equivalence check unambiguous — a port that emits the wrong variant produces a structurally-different record, not a numerically-equivalent one that requires macrostep-context replay to interpret. Trade-off accepted: trace records carry a few extra bytes per blocked-syscall unblock.

Adding a variant requires a §15 amendment to this doc and a coordinated update to every port. **Reserved (not legal yet):** `Bytes(u32, [u8])` (variable-length payload reference), `Obj(u32)` (handle to an externally-owned object). Both are deferred to future amendments if streaming or richer message buffers ratify.

INV-S6 (blk_obj integrity) does NOT constrain `msg` — a task's `msg` may carry a stale value from a prior unblock when re-blocking; the .scxml's contract is that `msg` is meaningful ONLY at the moment of unblock for the unblocked task, and ONLY between `queue.send` block and the eventual send-completion for a queued sender. Ports MUST NOT introduce assertions that would forbid stale `msg` between meaningful-windows.

## 6. M7 primitive bindings

This section is **load-bearing**. It is the curated subset of the ARMv7-M Architecture Reference Manual (DDI 0403E.e) and STM32H747xI Reference Manual (RM0399) that SOS depends on. Per INV-S1, SOS reviewers consult this section; they do not crawl those manuals as routine reference.

Per PCDN-SOS-00-011 (resolved): the bindings below describe **what the port code does**, sourced from CMSIS-Core (C) and the `cortex-m` crate (Rust) per §4.1. The chart references none of this. Every row in the tables below is a *port-side* obligation expressed in port-side library terms.

### 6.1 Exception assignment

| SCXML role | M7 exception | Port-side primitive | Notes |
|---|---|---|---|
| Context switch primitive | **PendSV** (IPSR 14) | C: naked-function `PendSV_Handler` (CMSIS vector name); pend via `SCB->ICSR |= SCB_ICSR_PENDSVSET_Msk`. Rust: `#[exception] fn PendSV()` (`cortex-m-rt`); pend via `cortex_m::peripheral::SCB::set_pendsv()`. | Tail-chained from SVC / SysTick. Save current task's PSP-frame R4–R11 (+ S16–S31 if `EXC_RETURN[4]==0`); load next task's frame; `bx lr`. Inline assembly required in both ports for the save/restore body. |
| Syscall entry (if `SyscallTransport=SvcInstruction`) | **SVC** (IPSR 11) | C: `SVC_Handler` (CMSIS vector name) + `__asm volatile ("svc %0" :: "i" (id))` at call sites. Rust: `#[exception] fn SVCall()` + `cortex_m::asm::svc::<id>()`. | Handler decodes `svc #imm`, dispatches to the kernel function corresponding to the syscall id. If `SyscallTransport=DirectCallBasepri` (the v1 default), SVC is unused by the kernel and MAY be left at any priority. |
| Tick | **SysTick** (IPSR 15) | C: `SysTick_Handler` + `SysTick->{LOAD,VAL,CTRL}`. Rust: `#[exception] fn SysTick()` + `cortex_m::peripheral::SYST`. | Period set per `SOS_TICK_HZ` (PCDN-SOS-00-008 default 1 kHz). Handler issues the `sys.tick` statechart event and pends PendSV if the resulting `current` differs from the entering `current`. |
| External `*_from_isr` callers | Any kernel-aware NVIC IRQ (priority ≥ 0xA0) | C: `NVIC_SetPriority(IRQn, 0xA0 >> __NVIC_PRIO_BITS_SHIFT)`; handler body. Rust: `cortex_m::peripheral::NVIC::set_priority(&mut nvic, IRQn, 0xA0)`. | Handler issues a `sem.give_from_isr` or `queue.send_from_isr` event, then pends PendSV if the kernel returned `resched=true`. |

### 6.2 Priority assignment

NVIC priority grouping MUST be configured to **all-preempt** (PRIGROUP=0): every priority bit is a preempt bit, no subpriority bits. This means a higher-priority ISR can interrupt a lower-priority ISR, which is required for the kernel-aware band semantics in §5.4 to hold.

Specific assignments (within the kernel-aware band `0xA0`–`0xEF`):

| Vector | Priority (hex) | Reason |
|---|---|---|
| PendSV | `0xE0` | Lowest kernel-aware — cannot preempt other kernel-aware ISRs; runs only when no other kernel-aware ISR is pending. |
| SysTick | `0xC0` | Above PendSV (so SysTick can pend PendSV mid-context-switch tail); below all `*_from_isr` IRQs (so a hardware event in flight isn't delayed by tick processing). |
| `*_from_isr` IRQs | `0xA0` | Highest kernel-aware. Allows hardware-driven wakes to land with minimum tick-induced latency. Mirrors the existing disco-analyzer HSEM0 priority documented at `disco-analyzer/analyzer-cm7/src/hsem.rs:158`. |

Ports MUST assign exactly these priorities to PendSV and SysTick. Ports MAY use any value in `[0xA0, 0xC0)` for `*_from_isr` IRQs; the `0xA0` choice is the **default**.

### 6.3 Stack pointer model

| Mode | SP | Purpose |
|---|---|---|
| Kernel / handler mode (post-boot) | MSP | Used by all handlers (PendSV, SVC, SysTick, `*_from_isr` IRQs) and by the initial boot code. MSP lives in the linker-defined `.kernel_stack` region; size set by the port. |
| Task / thread mode | PSP | Each task has a fixed-size PSP stack carved out of the linker-defined `.task_stacks` region or `static` arrays. The port allocates one PSP region per TCB at `task.create` time. |

CONTROL register at task start:
- `nPRIV` = 1 if `SyscallTransport=SvcInstruction` (tasks unprivileged); else `nPRIV` = 0 (tasks privileged).
- `SPSEL` = 1 (PSP).
- `FPCA` = 0 (set automatically by FPU on first FP instruction if `FpuPolicy=LazyStackingEnabled`).

### 6.4 EXC_RETURN inspection (for PendSV)

PendSV MUST inspect `EXC_RETURN` (in LR on entry to the handler) to determine the outgoing frame layout:

| `EXC_RETURN[4]` | Outgoing frame contains | PendSV save/restore obligation |
|---|---|---|
| 1 | Standard 8-word frame (R0–R3, R12, LR, PC, xPSR) | Save/restore R4–R11. |
| 0 | Extended 26-word frame (standard + S0–S15, FPSCR + padding) | Save/restore R4–R11 **and** S16–S31. The hardware handles S0–S15. |

The outgoing TCB's stored frame layout MUST be sized to accommodate the extended case; ports MAY use a discriminator byte adjacent to the saved PSP to short-circuit S16–S31 save/restore for tasks that never used the FPU since their last entry.

### 6.5 Critical section realisation

`crit.enter` MUST raise BASEPRI to a value that masks the entire kernel-aware band (`0xA0`–`0xEF`). The exact MSR target value is `0xA0` (anything at or below this priority value is masked; values above remain enabled). Ports MAY use `cpsid i` (PRIMASK) instead **only** if the port spec explicitly ratifies it; PRIMASK masks all interrupts including system-reserved, which is heavier than required.

`crit.exit` MUST lower BASEPRI to `0x00` (the reset default; no priority masked).

Port-side realisations:
- **C (CMSIS):** `__set_BASEPRI(0xA0)` on enter, `__set_BASEPRI(0x00)` on exit. `__DSB(); __ISB();` between the BASEPRI write and any memory operation that depends on the mask being in force.
- **Rust (`cortex-m`):** `cortex_m::register::basepri::write(0xA0)` on enter, `cortex_m::register::basepri::write(0x00)` on exit. `cortex_m::asm::dsb(); cortex_m::asm::isb();` after the write. Alternatively for fully-bracketed critical sections, `cortex_m::interrupt::free(|cs| { ... })` MAY be used **only when the closure body cannot block** (INV-S5); the closure body uses PRIMASK, not BASEPRI, and the port spec MUST ratify the use site.

INV-S5 (block_current under critical section) means `crit.enter` MUST NOT block. Ports that need a blocking critical-section pattern use `sched.suspend` / `sched.resume` instead.

### 6.6 SysTick clock source

STM32H747xI: SysTick MUST source from the CPU clock (`CTRL.CLKSOURCE=1`) for SOS-04 / SOS-05 reference ports. The external 8 MHz reference (`CLKSOURCE=0`) is permitted only via §15 amendment.

`SOS_TICK_HZ` builds the `LOAD` value as `(SystemCoreClock / SOS_TICK_HZ) - 1`. At default 1 kHz on a 400 MHz CM7, `LOAD = 399999`.

### 6.7 Vector table placement

Vector table MUST be placed at the M7 reset vector address; on STM32H747I-DISCO with the default linker layout the table sits at the start of FLASH (typically `0x0800_0000`). Ports that relocate it (e.g. to ITCM for cache predictability) ratify in their phase doc; SOS-00 does not constrain placement beyond "MUST be present, MUST contain the SOS PendSV / SVC / SysTick handlers".

### 6.8 Pre-emption flow (informative diagram)

```
Task A (PSP, BASEPRI=0)
   |
   v   issues syscall → DirectCallBasepri raises BASEPRI=0xA0
   v   mutates statechart datamodel (ready[], current, ...)
   v   if (resched) pend PendSV
   v   lowers BASEPRI=0
   v
PendSV (priority 0xE0)
   |
   v   save R4-R11 (+S16-S31 if EXC_RETURN[4]==0) to current task's PSP frame
   v   tcb[current].psp = SP
   v   current = next_task_id          // already updated by syscall path
   v   SP = tcb[current].psp
   v   load R4-R11 (+S16-S31) from next task's PSP frame
   v   bx lr (with EXC_RETURN that selects PSP + thread mode)
   |
Task B (PSP, BASEPRI=0)
```

Tick path:

```
SysTick (priority 0xC0)
   |
   v   tick_count++; expire delays/timeouts; raise sched.run
   v   if (resched) pend PendSV
   v   (BASEPRI not touched — handler runs at NVIC priority 0xC0,
       which already masks all kernel-aware IRQs at 0xA0... no wait,
       0xC0 > 0xA0 numerically means LOWER priority — see commentary)
```

**Commentary on the SysTick/`*_from_isr` priority ordering:** SysTick at `0xC0` is lower priority than `*_from_isr` IRQs at `0xA0`. A hardware IRQ can preempt SysTick mid-tick-service; the .scxml accommodates this via `irq_nest > 0 → pend_ticks++`. The hardware IRQ executes its `*_from_isr` syscall under its own NVIC priority (which raises BASEPRI to mask the kernel-aware band for the duration of the syscall body); when the IRQ returns, SysTick resumes, observes `irq_nest == 0`, and replays via the standard tick body. This is the spec-level model the port MUST realise.

## 7. Conformance vector framework (informative; SOS-03 ratifies the schema)

A conformance vector is the unit of equivalence between two ports. SOS-03 ratifies the wire format; SOS-00 frames the shape so downstream phases can cite it.

### 7.1 Vector shape

```
{
  "name": "two-tasks-same-prio-alternate-via-yield",
  "config": {
    "max_tasks": 8,
    "max_prio":  8,
    "max_sems":  8,
    "max_queues": 4,
    "q_depth":   16,
    "tick_hz":   1000
  },
  "input": [
    { "event": "task.create", "data": { "id": 1, "prio": 3 } },
    { "event": "task.create", "data": { "id": 2, "prio": 3 } },
    { "event": "task.yield",  "data": null, "from_tid": 1 },
    { "event": "task.yield",  "data": null, "from_tid": 2 },
    ...
  ],
  "expected_trace": [
    { "after_input_idx": 0, "current": 0, "tick_count": 0, "rc": 0, "tcb": [...], "ready": [...] },
    { "after_input_idx": 1, "current": 0, "tick_count": 0, "rc": 0, "tcb": [...], "ready": [...] },
    ...
  ]
}
```

`from_tid` is an injection mechanism: in the simulator and ports, the harness sets `current` to `from_tid` before dispatching the event (modeling "task X issued this syscall"). For ISR-originated events (`sys.tick`, `*_from_isr`), `from_tid` is `null`.

### 7.2 Observable state subset

The state-trace snapshot includes ONLY:

- `current`
- `tick_count`
- `rc`
- `tcb[i]` for `i in [0, MAX_TASKS)` — only the fields `{ id, prio, state, deadline, blk_obj, msg }`
- `ready[p]` for `p in [0, MAX_PRIO)` — the tid sequences
- `sems[s].{ count, max, waiters[] }` for `s in [0, MAX_SEMS)` if `valid`
- `queues[q].{ count, cap, buf[], sendw[], recvw[] }` for `q in [0, MAX_QUEUES)` if `valid`
- `irq_nest`, `sched_lock`, `pend_ticks`

Excluded (intentionally not observable): PendSV state, BASEPRI value, raw register contents, ISR latency, the precise interleaving of microsteps within a macrostep (the macrostep is the atomic unit of observation).

### 7.3 Determinism requirement

A port is conformant iff for every vector in the SOS-03 suite, the port's emitted trace **equals** `expected_trace` field-for-field, in order, after every external event in `input`.

This requires:
- Identical ECMAScript-subset evaluation semantics (or transpiled equivalent).
- Identical scheduling decisions (round-robin tie-breaking, wait-queue insertion order).
- Identical event dispatch order when multiple events are pending (the .scxml's macrostep ordering is deterministic; ports MUST preserve it).

### 7.4 The seed vector list

SOS-03 will ratify the canonical suite. The seed list (from `docs/REFERENCE.md` § "Testing surface") is:

1. Two tasks at the same priority alternating via `task.yield`.
2. Higher-priority task preempts on `sem.give`.
3. `task.delay` followed by `sys.tick` storms shows monotonic wake-up.
4. Queue FULL / EMPTY rejection vs. blocking with timeout.
5. `crit.enter` + `sys.tick × N` + `crit.exit` produces N catch-up ticks and at most one reschedule.
6. `sched.suspend` deferring a high-priority unblock until `sched.resume`.

SOS-03 expands these into formal fixtures and adds boundary cases (timeout exactly at tick_count, queue direct-handoff with sender at higher priority than receiver, etc.).

## 8. Build-time and runtime artifact map

Ratified deliverable shape per port. SOS-00 declares the shape; per-port phase docs (SOS-02, SOS-04, SOS-05) ratify the file contents.

| Artifact | Owner phase | Path | Build-time? | Runtime? |
|---|---|---|---|---|
| `rtos_kernel.scxml` | SOS-00 | repo root | input | n/a (not loaded at runtime by any v1 port) |
| `docs/REFERENCE.md` | SOS-00 | docs/ | input | n/a |
| Host simulator crate `sos-sim` | SOS-02 | `sim/sos-sim/` | n/a | hosts the simulator |
| Conformance vector fixtures | SOS-03 | `conformance/vectors/*.json` | input | input (loaded by the conformance harness) |
| Conformance harness | SOS-03 | `conformance/harness/` | n/a | runs vectors against any port |
| M7 Rust port crate `sos-m7-rust` | SOS-04 | `ports/m7-rust/` | n/a | runtime binary on bench |
| M7 C port project `sos-m7-c` | SOS-05 | `ports/m7-c/` | n/a | runtime binary on bench |
| Codegen evaluation output (optional) | SOS-06 | `ports/m7-codegen/` | (TBD) | (TBD) |

Per INV-S12 (static-only), every port's `Cargo.toml` / `CMakeLists.txt` MUST disable allocator-by-default on the kernel hot path. Heap MAY be available for non-kernel application code on the same target; the kernel itself MUST NOT consume it.

## 9. Invariants

Each invariant has a stable ID. Amendments require a §15 entry and SHOULD cite the resolving phase doc.

- **INV-S1 — Crawl boundary.** SOS-side specs and code cite external authorities by published reference (W3C SCXML, ECMA-262, ARM ARM, RM0399); they do not crawl those sources as routine reference. The curated subsets in §3, §4, and §6 are the authoritative SOS-side surface.
- **INV-S2 — Macrostep atomicity.** Ports MUST execute statechart macrosteps atomically with respect to other macrosteps. At most one transition's executable content runs at a time. Realisation: BASEPRI raise during syscall body; PendSV runs only on entry/exit.
- **INV-S3 — ISR-context admissibility.** `sys.tick` is the only event admissible from ISR context outside the explicit `*_from_isr` family. Ports MUST enforce this; calling `sem.take` from an ISR is undefined behaviour.
- **INV-S4 — Task-context admissibility.** Non-ISR syscalls require `current >= 0` (a task context). Ports MUST trap or assert this; calling `task.delay` from the boot path before idle becomes RUNNING is undefined behaviour.
- **INV-S5 — Block precondition.** `block_current()` MUST only be called when `sched_lock == 0` AND `irq_nest == 0`. Ports MUST enforce this; the syscall wrappers SHOULD assert and return `RC_INVAL` if violated.
- **INV-S6 — blk_obj integrity.** A blocked task's `blk_obj` matches exactly one of: `sems` index (BLK_SEM), `queues` index (BLK_QS / BLK_QR), or `-1` (DELAY).
- **INV-S7 — Ready-queue integrity.** RUNNING task is NOT in any `ready[p]`. READY tasks appear in EXACTLY one `ready[p]` where `p == tcb[id].prio`. Blocked / suspended / dormant tasks appear in NO `ready[p]`.
- **INV-S8 — Wait-queue ordering.** Per-object waiters (`sems[*].waiters`, `queues[*].sendw`, `queues[*].recvw`) are kept in priority-descending, FIFO-within-priority order. `give` / `send` / `receive` always wake the head.
- **INV-S9 — M7 NVIC priority discipline.** Kernel-aware ISRs (PendSV, SVC, SysTick, all `*_from_isr` callers) MUST run at NVIC priority ≥ 0xA0 on M7. Priority 0 is **forbidden** for any SOS-installed handler (mirrors the parent-repo durable rule `feedback_freertos_nvic_priority_0`). PRIGROUP MUST be 0 (all-preempt).
- **INV-S10 — Independence from FreeRTOS.** SOS does not link FreeRTOS-Kernel, does not copy from its sources, and does not depend on its symbols. Vocabulary borrowing (TCB, ready queue) is permitted; code borrowing is forbidden.
- **INV-S11 — Spec immutability via .scxml.** Ports do not modify `rtos_kernel.scxml`. The .scxml moves only via a §15 amendment to this doc, then a coordinated commit landing the .scxml + REFERENCE.md + conformance-vector regen + every port.
- **INV-S12 — Static-only on the kernel hot path.** All pools (`tcb`, `sems`, `queues`, `ready`, wait-queues, per-task PSP regions, kernel MSP region) are fixed-size at build time. No allocator on the kernel hot path. Application code outside the kernel MAY allocate freely.
- **INV-S13 — Conformance equivalence.** Two ports are equivalent iff they pass the same SOS-03 conformance vector suite. Trace-level divergence is a port defect, never a spec defect.
- **INV-S14 — One statechart per port.** Each port hosts exactly one instance of `rtos_kernel.scxml`. Multi-instance (e.g. one statechart per CPU core for SMP) is an explicit non-goal per §11.
- **INV-S15 — Chart is target-agnostic.** `rtos_kernel.scxml` MUST NOT name any M7 primitive (PendSV, SVC, SysTick, BASEPRI, PRIMASK, MSP, PSP, EXC_RETURN, NVIC priority value, CMSIS symbol, `cortex-m` symbol). The chart's vocabulary stops at abstract events and datamodel fields. M7 primitives live in the per-port crates (`ports/m7-rust/`, `ports/m7-c/`) and the mapping between them and chart events lives in §6 of this doc. Resolution source: PCDN-SOS-00-011.

## 10. Reconciliation with sibling FreeRTOS-Kernel

`disco-analyzer/analyzer-rtos/` vendors FreeRTOS-Kernel v11.1.0 (per memory `project_daa_freertos_is_the_target`). The disco-analyzer family uses it as the audio-analyzer's production runtime. SOS coexists with FreeRTOS as follows:

| Concern | FreeRTOS-Kernel | SOS |
|---|---|---|
| **Authority** | Owned by the FreeRTOS project; vendored at a specific commit. | Owned here; spec is `rtos_kernel.scxml` + `SOS-00-CONCEPTS.md`. |
| **Behaviour model** | C source + headers; behaviour implicit in implementation. | SCXML statechart; behaviour explicit in spec, traced via SOS-03 vectors. |
| **Where it runs (today, on disco-analyzer)** | CM7, via `analyzer-rtos` crate. | Not yet flashed. Bench validation (SOS-04 / SOS-05) flashes a SOS-only firmware that replaces the DAA firmware at flash-swap time (PCDN-SOS-00-001 → default (b)). |
| **Shared resources** | None at runtime. The two never coexist on a single firmware image. | None. |
| **Code reuse** | None permitted by INV-S10. | n/a. |
| **Vocabulary reuse** | "TCB", "ready queue", "tick", "BASEPRI mask" — industry-standard, mirrored. | Permitted; mirrors. |
| **The "FreeRTOS + NVIC priority 0 wedge" rule** | Owned by the FreeRTOS port layer's `configMAX_SYSCALL_INTERRUPT_PRIORITY`. | Mirrored as INV-S9 + §6.2 priority band rule. SOS enforces the equivalent rule in spec. |

The sibling subrepo's FreeRTOS-Kernel sources are **NOT** crawled by SOS-side work. Cross-pollination ratifies via explicit §15 citation with a named delta. The `analyzer-rtos` crate's existence does NOT obligate SOS to match its API surface.

## 11. Non-goals

Frozen non-goals for SOS-00 through SOS-06 (initial scope). Each may be lifted via a §15 amendment.

- **Software timers.** Tasks use `task.delay` or build atop `sys.tick`. No `xTimerCreate` analog.
- **Event groups.** No `xEventGroupSetBits` analog.
- **Direct-to-task notifications.** No `xTaskNotify` analog.
- **Mutexes with priority inheritance.** The kernel ships counting/binary semaphores only. Priority-inversion behaviour is the stock-semaphore behaviour (deadlock-prone if misused). Adding priority inheritance is a localised future amendment (sem.take/sem.give + a `holder` field).
- **Memory allocator.** Static pools only (INV-S12).
- **Stream / message-buffer streaming variants.** Fixed-size queue payloads only.
- **Tickless idle.** Tick fires at `SOS_TICK_HZ` always.
- **SMP / core affinity.** One statechart per port (INV-S14). The disco-analyzer's CM4 is not in scope; SOS runs on CM7 only at v1.
- **Heap-based task creation.** Task IDs are pre-allocated TCB slot indices; `task.create` activates a dormant slot.
- **Dynamic priority change.** A task's priority is set at create time and constant thereafter at v1. Reserved for a future amendment.
- **Multiple statechart instances per port.** Per INV-S14, one statechart per port.
- **Inter-port communication.** SOS ports don't talk to each other. Two boards running SOS are two independent kernels.

## 12. Acceptance checklist (normative)

A conforming SOS-00 ratification (i.e. the moment §15 gets its dated entry) requires:

(a) The PCDN list in §15 is fully resolved. Every `PCDN-SOS-00-NNN` open question has a chosen value, dated, and the corresponding §3 / §4 / §5 / §6 / §9 sections updated to reflect the choice (or explicitly note "PCDN unresolved; section blocks").

(b) The .scxml at `rtos_kernel.scxml` validates against the W3C SCXML 1.0 XSD (e.g. via `xmllint --schema https://www.w3.org/2011/04/SCXML/scxml.xsd rtos_kernel.scxml --noout`). Run pre-ratification; record the output in the §15 entry. (SOS-01 will automate this in CI.)

(c) The glossary §3, source-of-truth map §4, frozen enums §5, M7 primitive bindings §6, and invariants §9 are internally consistent. A reviewer can answer any "what does X mean" question by reading at most one section.

(d) The reconciliation §10 has been read by a reviewer familiar with the sibling `disco-analyzer/analyzer-rtos/` codebase, who has confirmed that no FreeRTOS-Kernel symbol or source-file is depended on by any text in §3, §4, §5, §6.

(e) The non-goal list §11 is exhaustive for the SOS-00..06 horizon. Items beyond that horizon are not constrained here.

A conforming SOS bench port (i.e. SOS-04 or SOS-05) additionally requires:

(f) Every NVIC priority assignment respects §6.2 and §9 INV-S9.
(g) The port's PendSV save/restore respects §6.4 (EXC_RETURN inspection for FPU frame).
(h) The port passes the SOS-03 conformance vector suite at the ratification of that vector suite version.

## 13. Files cited

| Path | Role | Status |
|---|---|---|
| `streamz/submodules/SOS/rtos_kernel.scxml` | Canonical kernel spec | exists (SOS-00 base); §15 amendments evolve it |
| `streamz/submodules/SOS/docs/REFERENCE.md` | Human reference (moved from `rtos_kernel.md` at SOS-00 ratification) | exists |
| `streamz/submodules/SOS/README.md` | Subrepo overview | created at SOS-00 land |
| `streamz/submodules/SOS/AGENTS.md` | Agent guide | created at SOS-00 land |
| `streamz/submodules/SOS/CLAUDE.md` | Agent runbook | created at SOS-00 land |
| `streamz/submodules/SOS/docs/concepts/README.md` | Initiative index | created at SOS-00 land |
| `streamz/submodules/SOS/docs/concepts/ERRATA.md` | Errata log | created at SOS-00 land (skeleton, no entries) |
| `streamz/submodules/SOS/docs/concepts/SOS-00-CONCEPTS.md` | This doc | created at SOS-00 land |
| `streamz/submodules/disco-analyzer/analyzer-rtos/` | Sibling FreeRTOS-Kernel runtime (DAA family) | exists; NOT a dependency (§10) |
| `streamz/submodules/disco-analyzer/analyzer-cm7/src/hsem.rs:158` | Reference for the `0xA0` kernel-aware priority value | exists in sibling subrepo; cited, not crawled |
| Parent CLAUDE.md, "Spec-Before-Code Planning Discipline" | Governing discipline | exists at parent repo root |
| Parent memory `feedback_freertos_nvic_priority_0` | Source of INV-S9 | exists in user memory |
| Parent memory `feedback_no_speculative_board_reset` | Governs bench-flash authorization | exists in user memory |

## 14. Unblocks

This phase unblocks:

- **SOS-01** (SCXML normalization + lint). Needs §4 (source-of-truth) and §5 (frozen enums) to be ratified before lint rules can be specified.
- **SOS-02** (host simulator). Needs §3 (glossary), §5 (enums), §7 (conformance-trace observable subset), and PCDN-SOS-00-005 (datamodel handling).
- **SOS-03** (conformance vectors). Needs §7 (trace shape) and §5 (enum values to ground vectors).
- **SOS-04** (M7 Rust port). Needs §6 (M7 primitive bindings), §9 INV-S9 (priority discipline), and §5.3 / §5.5 (transport + FPU policy).
- **SOS-05** (M7 C port). Same as SOS-04.
- **SOS-06** (codegen evaluation). Needs §3 + §4 + §5 + §9 + a passing SOS-04 to compare against.

## 15. Change log

### 2026-05-19 — Initial draft (Ira)

- Document drafted at `docs/concepts/SOS-00-CONCEPTS.md`.
- Sections §0–§14 populated.
- Frozen enums §5.1, §5.2 mirror the .scxml constants.
- §5.3 (`SyscallTransport`), §5.4 (`M7KernelPriorityBand`), §5.5 (`FpuPolicy`) introduced as proposed-frozen with default picks pending PCDN resolution.
- §6 (M7 primitive bindings) is new content; mirrors the curated subset of the ARM ARM and RM0399 SOS depends on.
- §10 reconciliation with sibling FreeRTOS-Kernel (DAA family) introduced.
- §11 non-goal list ported from `docs/REFERENCE.md` § "Deliberate omissions vs. FreeRTOS".

### 2026-05-19 — Ratification (Ira)

User walked the PCDN list and ratified every open question. SOS-00 status moves from 🟡 drafted to **🟢 ratified**. SOS-01 onward are unblocked.

PCDN resolutions:

- **PCDN-SOS-00-001 — Bench coexistence model.** **Resolved (b):** SOS-04 / SOS-05 bench validation replaces DAA firmware at flash-swap time. Operator manages the flash swap between SOS validation rounds and DAA work. SOS does not coexist with DAA on a single image.

- **PCDN-SOS-00-002 — Syscall transport on M7.** **Resolved `DirectCallBasepri` with migration stipulation.** v1 ports use `DirectCallBasepri`; migration to `SvcInstruction` is a *planned future amendment*, not an open option for indefinite deferral. The port architecture MUST keep the syscall transport as a single localised layer (per-syscall wrappers, no transport-specific logic in the kernel body) so the migration is a localised diff. A subsequent phase (likely `SOS-04-B` / `SOS-05-B` amendment) ratifies the migration once v1 ports are conformance-validated. Restated in §5.3.

- **PCDN-SOS-00-003 — FPU policy.** **Resolved `LazyStackingEnabled`.** M7 reset default; preserves FPU usability for tasks.

- **PCDN-SOS-00-004 — Test-target shape.** **Resolved (c):** Both — SOS-02 host simulator + SOS-04/05 bench ports. Phase roadmap unchanged.

- **PCDN-SOS-00-005 — Datamodel handling for SOS-02.** **Resolved (b) as starting point, with explicit deferral to SOS-01 for the AST-vs-trace question.** v1 SOS-02 hand-compiles `<script>` blocks into Rust and treats the transpiled form as a derived artifact. SOS-01 revisits whether to *additionally* drive the chart via an AST or trace-based execution path; that decision does not block SOS-00 ratification. The hand-compiled path remains the bootstrap form regardless of how the SOS-01 decision lands.

- **PCDN-SOS-00-006 — Port permanence.** **Resolved (a):** SOS-04 / SOS-05 are reference (canonical) ports. Demotion to historical reference is a §15 amendment ratifying after SOS-06 demonstrates codegen quality.

- **PCDN-SOS-00-007 — Kernel-aware NVIC band.** **Resolved `0xA0`–`0xEF`** per §5.4 / §6.2.

- **PCDN-SOS-00-008 — Default tick rate.** **Resolved (c) at draft default** — configurable via `SOS_TICK_HZ` with 1 kHz default. The user did not redirect this entry during ratification; the default stands. (If a different default tick rate is preferred, a follow-up §15 amendment trivially adjusts.)

- **PCDN-SOS-00-009 — Initiative name.** **Resolved: "Statechart-Orchestrated Scheduler".** The `SOS` prefix is what's load-bearing for cross-doc citation; the expansion is informative.

- **PCDN-SOS-00-010 — Submodule registration.** **Resolved 2026-05-22 (final):** the submodule clone URL is `https://github.com/SoftOboros/SOS.git` (public, MIT-licensed, under the `SoftOboros` GitHub org); contributors with push rights add a second remote `writable = git@github.com:SoftOboros/SOS.git` per the parent-repo convention (`dynatroni`, `scjson`, `scjson-swift`, `scir`, `rlvgl` all follow this two-remote shape). Initial commit landed 2026-05-22 as `3b040c9` on branch `webslinger`; parent registration commit `3ce55824` adds `streamz/submodules/SOS` to `.gitmodules`.

- **PCDN-SOS-00-011 — "M7 primitives as references" interpretation.** **Resolved (already, in-draft): reading 2 (implement-against).** Chart stays target-agnostic; M7 primitives live in port code via CMSIS-Core (C) and the `cortex-m` crate (Rust). Ratified as INV-S15. §4.1 documents the port-side library surfaces. §6 bodies cite CMSIS / `cortex-m` symbols concretely.

Acceptance checklist (§12) compliance at ratification:

- (a) ✅ All eleven PCDNs resolved.
- (b) ⏸ Deferred to SOS-01 (`xmllint --schema scxml.xsd` automation lands as part of the SCXML lint phase; pre-SOS-01 the .scxml is presumed-valid based on visual inspection and the originating author's intent).
- (c) ✅ Glossary, source-of-truth map, frozen enums, M7 primitive bindings, and invariants internally consistent.
- (d) ✅ Reconciliation §10 written; explicitly cites no FreeRTOS-Kernel symbol or source-file.
- (e) ✅ Non-goal list §11 covers the SOS-00..06 horizon.

Unblocks: SOS-01 (SCXML normalization + lint). SOS-01's scope is amended to explicitly include the AST-vs-trace deferral from PCDN-005.

### 2026-05-19 — Amendment 001: broaden Syscall glossary entry (Ira)

SOS-01 drafting surfaced that §3 `Syscall` was defined by region membership (`syscalls`), which excluded `crit.*` and `sched.*` despite their syscall semantics, and would also exclude `*_from_isr` variants by the same reading. §3 `Syscall` row replaced with a definition keyed on caller intent ("issued by task code or ISR code to invoke kernel behaviour") rather than chart-region membership. The row now enumerates the included families explicitly and excludes `sys.tick` + `sched.run` explicitly. Cross-reference to SOS-01 §5 `ExternalEventName` added for the full external-event list. No invariant, frozen enum, or chart construct changed. No port-spec impact.

### 2026-05-19 — Amendment 002: harmonise trace-record key to `after_input_idx` (Ira)

SOS-02 drafting surfaced that §3 `State trace` row used `(macrostep_index, ...)` as the key-name placeholder while §7.1 example used `"after_input_idx"`. Same concept, two spellings. Harmonised on `after_input_idx` (the §7.1 example was already correct; the §3 row was the drift point). §3 `State trace` row updated to use `after_input_idx`, and the row now explicitly notes the `-1` value used for the boot-baseline record. The sibling SOS-02 §1 / §3 / §7 already use `after_input_idx` end-to-end; no SOS-02 edit needed beyond the pre-existing draft.

### 2026-05-19 — Amendment 003: ratify `Msg` as a §5.6 frozen enum (Ira)

SOS-02 drafting surfaced that `tcb[i].msg` is polymorphic — used for both queue payloads and return-code deposits — but SOS-00 typed it only implicitly. The chart's ECMAScript datamodel tolerates the polymorphism dynamically; ports MUST realise it explicitly. New §5.6 `Msg` (Standards Action) frozen enum added with three variants (`Null`, `Int(i64)`, `ReturnCode(ReturnCode)`); registration policy + reserved variants documented. §3 `TCB` row updated to cite §5.6 and describe the field semantics. INV-S6 commentary added: `msg` is *not* an invariant-constrained field — it carries meaningful values only at well-defined moments (unblock, queue-send-stage); ports MUST NOT add assertions that would forbid stale `msg` between meaningful-windows. SOS-02 typed this as `enum Msg { Null, Int(i64), ReturnCode(ReturnCode) }` in its §6.3.1 — that becomes the canonical port-side realisation.

*Note: the wire-form clause originally appended to this amendment ("Int and ReturnCode both serialise as signed integers, discriminator recoverable from macrostep context") is superseded by Amendment 004 below — the wire form is on-wire-discriminated, not context-discriminated.*

### 2026-05-19 — Amendment 004: align `Msg` wire form with SOS-02 §7.2 (on-wire discriminator) (Ira)

SOS-02 implementation skeleton surfaced a contradiction between SOS-00 §5.6 (which Amendment 003 set as "discriminator off-wire; both `Int` and `ReturnCode` serialise as signed integers") and SOS-02 §7.2 (which explicitly specifies `{"rc": <int>}` object form for `ReturnCode`). The on-wire form is the better design for three reasons: (1) the SOS-03 harness can diff records without macrostep-context replay; (2) port-equivalence checks are structurally unambiguous — a port that emits the wrong variant produces a structurally-different record, not a numerically-equivalent one; (3) the chart's distinction between queue-payload-zero (`Int(0)`) and `RC_OK` (`ReturnCode(Ok)`) is preserved in the trace, which off-wire form had collapsed.

§5.6 amended: the wire-form sub-section now declares `Null` → `null`, `Int(N)` → bare integer, `ReturnCode(rc)` → `{"rc": <i8>}`. SOS-02 §7.2 is the authoritative wire-format owner; this amendment brings SOS-00 §5.6 into alignment with it. The SOS-02 skeleton implementation (landed 2026-05-19) is already correct under the new form — no implementation rework needed.

Trade-off accepted: trace records carry a few extra bytes per blocked-syscall unblock. Per the SOS-03 PCDN-001 default (structural diff for `expected_trace`), this is a cleaner-and-cheaper-to-diff format despite the byte cost.
