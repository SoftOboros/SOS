# SOS-04 — M7 Rust Reference Port: Concepts, Architecture, and Bench Substrate

**Status:** **🟢 Ratified 2026-05-19.** All eighteen PCDNs resolved by user 2026-05-19; ratification entry in §15. Three future-amendment markers registered (FAM-04-A configurable stacks, FAM-04-B FLASH layout abstraction, FAM-04-C UART DMA promotion). Implementation commit (`ports/m7-rust/sos-m7-rust/` + `ports/m7-rust/sos-m7-rust-host-driver/`) lands as follow-up. PCDN list at §15 awaits user walk-through; ratification flips to 🟢 once every PCDN-SOS-04-NNN has a chosen value and the affected sections are updated. Implementation commit (the `sos-m7-rust` crate skeleton + linker script + minimal trace transport) lands as a follow-up commit per the spec-before-code discipline.

**Blocks:** SOS-06 (codegen-from-SCXML evaluation needs a working hand-written M7 Rust port to compare codegen output against — for binary size, NVIC priority discipline, and SOS-03 trace conformance).

> 🛑 **NO CODE.** Vocabulary, port-side architecture, M7 bring-up surface, conformance-mode protocol, build artifacts, invariants. No Rust source, no `Cargo.toml`, no `memory.x`. The implementation commit lands those after ratification per the spec-before-code discipline.

## 0. Authority policy

SOS-04 owns:

- The **`sos-m7-rust` crate layout** — file tree under `ports/m7-rust/sos-m7-rust/`, the `lib.rs` / `main.rs` boundary, the kernel / handler / transport / BSP module split.
- The **linker script** `memory.x` — the FLASH / RAM / DTCM / AXI-SRAM region declarations, the placement of the SOS kernel stack, the per-task PSP stack pool, and the trace transport buffers.
- The **NVIC handler bodies** — the exact inline-assembly `asm!` blocks that satisfy [SOS-00 §6.4] (PendSV save/restore with EXC_RETURN inspection), [SOS-00 §6.5] (BASEPRI critical sections), and [SOS-00 §6.6] (SysTick clock source and reload value).
- The **disco-analyzer-specific peripheral wiring** — which UART pin pair the trace transport claims, which RCC clock-tree path is configured, which GPIO AF mode is selected. This is **bench-substrate-specific**; SOS-05 (M7 C port) is free to make different choices for the same primitives if a different board layout calls for it (it should not — the bench board is the same — but the spec does not bind SOS-05 to SOS-04's choices).
- The **port-binary contract realisation** — the host-side adapter that converts the [SOS-03 §7.6] stdin / stdout streams into the M7's UART (or SWO) framing.

SOS-04 does **NOT** own:

- The **kernel behaviour** — [SOS-00] owns it; `rtos_kernel.scxml` is the source. The port is a faithful realisation; if the port disagrees with the chart, the port is wrong.
- The **M7 contract** — [SOS-00 §6] owns it. The port implements the contract; it cannot amend the contract. Any new M7 primitive obligation (e.g. enabling a DSP extension, claiming a new exception) requires a [SOS-00 §15] amendment first.
- The **frozen enums** — `TaskState`, `ReturnCode`, `SyscallTransport`, `M7KernelPriorityBand`, `FpuPolicy`, `Msg` (per [SOS-00 §5]) are re-exported by reference (or mirrored as `#[repr(i8)]` enums where needed for byte-stable serialisation); SOS-04 does not extend them.
- The **trace wire format** — [SOS-02 §7] owns the byte-exact JSONL encoding rules and the canonical field order. SOS-04 emits records in this format; it cannot rename a field, reorder fields, or add a field.
- The **conformance suite** — [SOS-03] owns the suite. SOS-04 is exercised by it; it does not author vectors. (Regression vectors mined from SOS-04-side ERRATA entries land in `conformance/vectors/regression/` per [SOS-03 §5.1] / §7.4 once such entries exist.)
- The **simulator implementation** — [SOS-02] owns `sos-sim`. SOS-04 does not depend on the `sos-sim` crate at runtime; the bench-side host-driver MAY depend on it (e.g. to pre-validate vectors before sending them to the M7), but the M7 firmware itself does not link `sos-sim`.

The authority split:

| Concern | Owner | SOS-04 relationship |
|---|---|---|
| Kernel behaviour (statechart, datamodel, syscall ABI) | [SOS-00] / `rtos_kernel.scxml` | `derive`. Port implements; cannot amend. |
| Frozen enums (`TaskState`, `ReturnCode`, `SyscallTransport`, `M7KernelPriorityBand`, `FpuPolicy`, `Msg`) | [SOS-00 §5] | `mirror`. Port re-exports the integer discriminants verbatim per [SOS-02 §7.2]; serialised values in the on-device trace are byte-identical to `sos-sim`'s output. |
| M7 primitive contract (PendSV / SVC / SysTick / BASEPRI / EXC_RETURN / NVIC priority bands) | [SOS-00 §6] | `derive`. Port realises §6 row-by-row in the handler bodies and the BSP. |
| Trace wire format (JSONL, field order, typed-value encoding, `Msg` discriminator) | [SOS-02 §7] | `mirror`. Port emits byte-identical records. |
| Conformance vector suite | [SOS-03] | `derive`. Port satisfies the [SOS-03 §7.6] port-binary contract; the harness drives. |
| Port crate layout, linker script, handler bodies, BSP, transport | this doc | `own`. |
| `cortex-m` crate API | upstream `cortex-m` project | `mirror`. Pinned to `0.7.x`; no SOS-04-side fork. |
| `cortex-m-rt` crate API | upstream `cortex-m-rt` project | `mirror`. Pinned to `0.7.x`. |
| `stm32h7` PAC (or `stm32h7xx-hal`) | upstream | `mirror`. PCDN-SOS-04-002 selects the surface. |
| `panic-halt` crate | upstream | `mirror`. |
| `embedded-io` crate | upstream | `mirror`. Trait surface only — used by the transport module to abstract UART / SWO writes. |
| Per-host driver (the host-side adapter that bridges harness stdio to the M7's UART) | [SOS-03] (contract) + SOS-04 (this doc) | `derive` (contract) + `own` (realisation). |

INV-S-PORT-0 (crawl boundary, inherited from [SOS-00 §0] INV-S1): SOS-04 reviewers consult this doc plus [SOS-00 §6] plus the published `cortex-m` / `cortex-m-rt` / `stm32h7` API documentation. The ARMv7-M Architecture Reference Manual, the STM32H747xI Reference Manual (RM0399), and the sibling `disco-analyzer/` crates are NOT routine crawl targets; the §6 binding tables in [SOS-00] are the curated subset SOS-04 depends on.

## 1. Purpose

Establish:

1. The **M7 Rust reference port** of the kernel — the `sos-m7-rust` crate, cross-compiled to `thumbv7em-none-eabihf`, flashed to the STM32H747I-DISCO's CM7 core, executing the behaviour ratified by [SOS-00] (i.e. the behaviour of `rtos_kernel.scxml`) against real M7 silicon.

2. The **operational restatement** of [SOS-00 §6] (M7 primitive bindings). SOS-00 §6 declares the contract abstractly ("PendSV MUST save R4–R11"); this doc declares the concrete realisation ("the `PendSV()` handler body is a `#[exception]` function containing an `asm!` block of shape … that satisfies §6.4"). The contract surface does not move; the realisation surface does.

3. The **conformance-mode protocol** — how the port binary satisfies [SOS-03 §7.6]. The port reads one vector input on its UART RX (or from a compiled-in `static` array, per PCDN-SOS-04-004), executes it, and emits one trace record per macrostep boundary on its UART TX in the [SOS-02 §7] wire format. A host-side adapter bridges the M7's UART to the harness's stdin / stdout.

4. The **bench substrate notes** — which UART pin pair, which clock-tree path, which GPIO AF mode. These are disco-analyzer-board-specific concerns; the spec records the chosen values so the port is reproducible across bench rebuilds and the choices are reviewable independent of the implementation commit.

5. The **scope discipline for v1** — the port is **REFERENCE, not PRODUCTION**. It builds cleanly, flashes, brings up the kernel-aware ISR set, runs the [SOS-03 §6.6] seed vectors, emits passing traces. Recovery from faults, watchdog timeouts, low-power modes, persistence, hot-reload, and any other production-hardening surface is **OUT OF SCOPE at v1** (INV-S-PORT-8). A future `SOS-04-B` amendment ratifies hardening once the v1 reference is conformance-validated and the operator has bench experience driving it.

Without SOS-04:

- The "two ports stress-test the .scxml as a spec" thesis ([SOS-00 §2]) has only one port (`sos-sim`, the host simulator). Two ports is what proves the chart is precise enough; one port is what proves the chart compiles.
- SOS-06 (codegen evaluation) has no hand-written reference to compare generated output against. Codegen-vs-`sos-sim` is meaningful for kernel-behaviour conformance; codegen-vs-handwritten is meaningful for the *embedded-target-quality* questions SOS-06 must answer (binary size, NVIC priority placement, lazy-stacking handling, interrupt latency overhead).
- The disco-analyzer bench (the team's primary M7 substrate) has no SOS firmware. The board can prove the chart on host (via `sos-sim`); it cannot yet prove the chart on silicon.

## 2. Problem statement

**Current state (as of 2026-05-19, immediately post-SOS-03 ratification):**

- [SOS-00] is ratified. §6 freezes the M7 primitive bindings in 8 sub-sections (exception assignment, priority assignment, stack model, EXC_RETURN inspection, critical section, SysTick clock source, vector table, pre-emption flow).
- [SOS-01] is ratified. The 18 external events and 10 state ids are the closed vocabulary; the M7 port's syscall wrappers route every kernel-aware event from those names.
- [SOS-02] is ratified. The `sos-sim` host simulator's spec is the byte-stable reference; the M7 port's on-device trace MUST be byte-equal to `sos-sim`'s when run on the same vector.
- [SOS-03] is ratified. The conformance harness's CLI shape and the port-binary stdin / stdout contract (§7.6) are frozen; the six seed vectors are reserved at `conformance/vectors/smoke/0001-…0006-….json` and land at the SOS-03 implementation commit.
- The disco-analyzer bench at `streamz/submodules/disco-analyzer/` runs FreeRTOS-Kernel v11.1.0 (per memory `project_daa_freertos_is_the_target`). Per [SOS-00] PCDN-SOS-00-001 → (b), SOS coexists with DAA by replacing DAA firmware at flash-swap time. The CM4 stays asleep when SOS runs (a CM7-only kernel at v1; INV-S-PORT-N below records this explicitly).
- No SOS firmware exists. The subrepo's `ports/` tree is unpopulated; the M7 cross-compile toolchain is the team's existing arm-none-eabi / rustup `thumbv7em-none-eabihf` target.

**The pressure that motivates SOS-04:**

Three pressures compound:

1. **The chart needs a bench port to be falsifiable on silicon.** Host-simulation proves the spec is internally consistent; bench-port proves the spec is *implementable*. Without bench-port, an M7-specific subtlety — say, an EXC_RETURN edge case the chart doesn't constrain — can hide indefinitely. The port is the falsifier.

2. **Codegen evaluation (SOS-06) needs a hand-written reference to compare against.** Codegen-vs-`sos-sim` is a *behaviour* check. Codegen-vs-handwritten is a *quality* check (binary size, register usage, interrupt latency, NVIC priority discipline, FPU stacking overhead). Without SOS-04, SOS-06 has nothing to anchor "is codegen good enough?" against; it can only ask "is codegen correct?" — a strictly easier question.

3. **The science being proved (SCXML → multiple equivalent language ports) requires both the Rust and C ports.** SOS-04 (Rust) and SOS-05 (C) are siblings; the C port stands on the Rust port's success as confirmation that the .scxml admits both idiomatic Rust and idiomatic C without forcing either toward the other. Authoring SOS-04 first is a strict-typing-and-borrow-checker assist to surfacing latent ambiguities in the chart that the looser C port would miss.

**Why this is the right time:**

- [SOS-00 §6] is the curated M7 surface; SOS-04 reviewers do not crawl the ARM ARM or RM0399. The contract is small enough to fit on one screen per sub-section.
- [SOS-02] and [SOS-03] just ratified — the trace format and the harness's port-binary contract are stable, so the port has a fixed target.
- The disco-analyzer team has shipped meaningful M7 firmware (DAA-00 through DAA-06; FreeRTOS + bare-metal both functional); the institutional knowledge for clock-tree setup, GPIO AF, vector table placement, and probe-rs flashing is fresh.
- The user-facing prompt explicitly nominates Rust first and C second; the natural authoring order matches that nomination.

## 3. Canonical glossary

Terms SOS-04 introduces. Terms defined in earlier phases are cited, not restated.

| Term | Definition | Owner |
|---|---|---|
| **Port** | An implementation of the kernel on a specific target. As defined in [SOS-00 §3]; used without modification. | SOS-00. |
| **Port binary** | The cross-compiled `sos-m7-rust` ELF / hex file flashed to the M7. As distinct from the **host-side adapter** (a separate host-runnable binary that bridges the [SOS-03 §7.6] stdin / stdout contract to the M7's UART transport). The harness in [SOS-03] talks to the **host-side adapter**; the adapter talks to the **port binary** via the chosen trace transport. | SOS-04. |
| **Host-side adapter** | The host-runnable binary at `ports/m7-rust/sos-m7-rust-host-driver/` (post-implementation) that opens the host's serial port (or SWO socket), buffers the vector input to the M7, and streams the M7's emitted trace records to stdout. Satisfies the [SOS-03 §7.6] port-binary contract on behalf of the M7 firmware. The adapter contains no kernel logic; it is a pure I/O bridge. | SOS-04. |
| **Bench substrate** | The physical hardware the port runs on. v1 substrate is the STM32H747I-DISCO board; the CM7 core executes; the CM4 core is held in reset (no `cm4` firmware loaded). Other bench substrates are reserved future amendment territory. | SOS-04. |
| **Trace transport** | The on-device peripheral the port uses to emit trace records. v1 default is UART (PCDN-SOS-04-001). Reserved alternatives are SWO and semihosting stdout. The transport's framing is the JSONL newline-delimited form ([SOS-02 §7]); the transport adds no envelope, no length prefix, no escape sequences. | SOS-04. |
| **Boot path** | The cross-compiled program's startup sequence from reset through `cortex_m_rt::entry` to the first `wfi`. Detailed in §6.8. | SOS-04. |
| **Task stack** | The per-task PSP (Process Stack Pointer) region the port reserves at `task.create` time. Each task has one task stack; the regions are pre-allocated at link time per PCDN-SOS-04-006 (`StackPolicy::StaticPerTcb` default). | SOS-04. |
| **Kernel stack** | The MSP (Main Stack Pointer) region used by the boot path, all `#[exception]` handlers, and the `wfi` idle loop. Single, port-wide, sized at link time per PCDN-SOS-04-006. | SOS-04. |
| **Done sentinel** | A reserved JSONL record `{"__sos_done": true}` the port emits as the final line of its trace stream, signalling to the host-side adapter that all expected records have been written. The sentinel lets the adapter close its stdout cleanly without a UART-side EOF (UART has no EOF). PCDN-SOS-04-005 proposes the sentinel; ratification adds it to [SOS-03 §6.2] as an allowed-but-not-required record. The harness ignores the sentinel when present (it is not part of `expected_trace`). | SOS-04 (proposes); SOS-03 (ratifies the allowance). |
| **Conformance mode** | The port-binary operating mode in which the port reads a vector from the trace transport's RX side, executes it, emits the trace on TX, and terminates with the done sentinel. The mode the harness drives. | SOS-04. |
| **Standalone mode** | The port-binary operating mode in which the port runs a compiled-in `static` vector array (no UART RX consumption) and emits the trace on TX. Used at bench bring-up before the host-side adapter is wired, and as a self-test smoke check during board bring-up. PCDN-SOS-04-004 ratifies that both modes are supported at v1. | SOS-04. |

**Terms reused from earlier phases (cited, not restated):** `Statechart`, `Datamodel`, `Macrostep`, `Microstep`, `Kernel`, `Bench port`, `TCB`, `Ready queue`, `Wait-queue`, `Syscall`, `Tick`, `Critical section`, `Scheduler suspend`, `Kernel-aware ISR`, `Kernel-blind ISR`, `Idle task`, `Boot` (from [SOS-00 §3]); `ExternalEventName`, `StateId` (from [SOS-01 §3]); `Simulator`, `Trace`, `TraceRecord`, `Macrostep boundary`, `Quiescence`, `Step harness`, `Determinism budget`, `ScriptProvider`, `Script name` (from [SOS-02 §3]); `Vector`, `Vector fixture`, `Expected trace`, `Conformance harness`, `Port-binary contract`, `Diff record`, `Conformance level`, `Suite SHA`, `Vector origin` (from [SOS-03 §3]).

## 4. Source-of-truth map

External authorities and the exact surface SOS-04 depends on. Per INV-S1 (inherited from [SOS-00 §0]), the table below is the curated surface; SOS-04 reviewers consult this list, not the crate source trees or the chip manuals.

| Source | Pinned form | Used surface | Relationship |
|---|---|---|---|
| `rtos_kernel.scxml` | Pinned at the Suite SHA per §15 (port behaviour pinned to a chart SHA) | Indirectly — via the kernel logic the port realises. The port does NOT parse the .scxml at runtime; the chart's behaviour is hand-transliterated into Rust at port-build time and frozen at the implementation commit. | `derive`. |
| [SOS-00 §5] frozen enums (`TaskState`, `ReturnCode`, `SyscallTransport`, `M7KernelPriorityBand`, `FpuPolicy`, `Msg`) | Ratified 2026-05-19 (Amendments 003, 004) | Re-exported with verbatim integer discriminants so the on-device trace serialises byte-identically to `sos-sim`'s. | `mirror`. |
| [SOS-00 §6] M7 primitive bindings | Ratified 2026-05-19 | THE load-bearing contract. §6.1 (exception assignment), §6.2 (priority assignment), §6.3 (stack model), §6.4 (EXC_RETURN inspection), §6.5 (critical section realisation), §6.6 (SysTick clock source), §6.7 (vector table placement), §6.8 (pre-emption flow). | `derive`. |
| [SOS-00 §9] invariants (`INV-S2` macrostep atomicity, `INV-S5` block precondition, `INV-S9` NVIC priority discipline, `INV-S10` independence from FreeRTOS, `INV-S11` chart immutability, `INV-S12` static-only, `INV-S14` one-statechart-per-port, `INV-S15` chart target-agnosticism) | Ratified 2026-05-19 | The port satisfies all of these. INV-S-PORT-N below add port-scope invariants on top; they MUST be consistent with these. | `mirror`. |
| [SOS-01 §5.3] `ExternalEventName` (18 events) | Ratified 2026-05-19 | The closed set the port's syscall wrappers and ISR shims construct events from. | `derive`. |
| [SOS-02 §7] trace wire format (JSONL, field order, typed-value encoding, `Msg` discriminator) | Ratified 2026-05-19 | The on-device trace serialises byte-identically. | `mirror`. |
| [SOS-03 §6.6] seed-vector list, [SOS-03 §7.6] port-binary contract | Ratified 2026-05-19 | Six seed vectors are the v1 conformance floor; §7.6 governs the stdin / stdout contract the host-side adapter realises. | `derive`. |
| `cortex-m` (Rust crate) | `cortex-m = "0.7"` (current 0.7.x at SOS-04 ratification) | `cortex_m::register::{basepri, primask, control}`, `cortex_m::peripheral::{SCB, SYST, NVIC}`, `cortex_m::asm::{dsb, isb, wfi, bkpt}`, `cortex_m::interrupt::free`, `cortex_m::Peripherals`. | `mirror`. Same surface [SOS-00 §4.1] enumerated. |
| `cortex-m-rt` (Rust crate) | `cortex-m-rt = "0.7"` matching `cortex-m` | `#[entry]`, `#[exception]`, `#[interrupt]`, the linker-script integration that materialises the vector table from the `_handler` symbols. The `memory.x` file at the crate root is consumed by `cortex-m-rt`'s build script. | `mirror`. |
| `stm32h7` (PAC) **OR** `stm32h7xx-hal` | PCDN-SOS-04-002 selects | Minimal: RCC for clock-tree setup, GPIO for UART AF mode, the chosen UART peripheral (USART1 / UART4 / UART8 per PCDN-SOS-04-003) for the trace transport, plus the EXTI / interrupt-controller surface for whatever `*_from_isr` driver the v1 seed vectors exercise. **Recommendation:** `stm32h7` PAC with a hand-coded minimal BSP in `src/disco_bsp.rs`. Smaller surface, fewer transitive deps, no HAL-side abstractions to fight when the kernel's NVIC discipline ([SOS-00 §6.2]) is the load-bearing concern. | `mirror`. |
| `panic-halt` (Rust crate) | `panic-halt = "1"` | The panic handler. v1 panics halt-and-loop; production hardening (panic → fault handler → reboot) is INV-S-PORT-8 out-of-scope. | `mirror`. |
| `embedded-io` (Rust crate) | `embedded-io = "0.6"` (current 0.6.x) | Trait surface only (`Read`, `Write`, `ErrorType`) — the trace transport implements them so the kernel's trace emission code is transport-agnostic. | `mirror`. |
| `nb` (Rust crate) | `nb = "1"` | Used transitively by `embedded-io` blocking adapters where applicable; only if PCDN-SOS-04-002 selects `stm32h7xx-hal` (which uses `nb` heavily). With raw PAC, `nb` is not pulled in. | `mirror` (conditional). |
| `serde-json-core` (Rust crate) **OR** hand-rolled JSON writer | PCDN-SOS-04-008 selects | Used by the trace emission path to serialise `TraceRecord`s in [SOS-02 §7] format. `serde-json-core` is a `no_std` JSON serialiser. **Recommendation:** hand-rolled. The trace format is fixed at field-level and the byte-exact field order required by [SOS-02 §7.1] is easier to enforce with a hand-rolled writer than with a derive macro whose output shape varies with crate version. | `mirror` or `own`. |
| `cortex-m-semihosting` (Rust crate, OPTIONAL) | `cortex-m-semihosting = "0.5"` | Only if PCDN-SOS-04-001 selects semihosting as a (non-default) trace transport. Adds a host-debugger dependency (probe-rs attached) which works against the spec's "runs standalone on the bench" property. | `mirror` (conditional). |

**Negative listing (to make the boundary explicit):**

- SOS-04 MUST NOT depend on FreeRTOS-Kernel (vendored at `disco-analyzer/analyzer-rtos/`). Mirrors [SOS-00] INV-S10.
- SOS-04 MUST NOT depend on the disco-analyzer subrepo's crates (`analyzer-cm7`, `analyzer-cm4`, `analyzer-rtos`, `rlvgl-*`, `analyzer-display`, etc.). INV-S-PORT-7 reasserts.
- SOS-04 MUST NOT depend on `rtic` (the Cortex-M RTIC framework). Mirrors the [SOS-00 §10] independence rule at the M7-Rust-port surface; `rtic`'s task scheduling competes with SOS's, and `rtic`-style macros would hide the very M7 primitive contract the port exists to expose.
- SOS-04 MUST NOT depend on `embassy` (the async embedded framework). Same reason as `rtic`; additionally, `embassy` requires an async runtime that competes with the chart's macrostep semantics.
- SOS-04 MUST NOT depend on `alloc` or any heap allocator. Mirrors [SOS-00] INV-S12 (static-only on the kernel hot path) at the port surface; INV-S-PORT-6 reasserts.
- SOS-04 MUST NOT depend on `libm` or any floating-point math library for kernel-hot-path arithmetic. The kernel uses integer math only; FPU usage is governed by [SOS-00 §5.5] `FpuPolicy = LazyStackingEnabled` and only matters for tasks, not for the kernel itself.
- SOS-04 MUST NOT depend on `sos-sim`. The host-side adapter MAY depend on it for pre-flight vector validation; the firmware MUST NOT.

## 5. Frozen enums

SOS-04 ratifies three phase-local enums. Each carries a registration policy per the parent CLAUDE.md "Frozen enumerations — registration policy" convention. Frozen enums declared earlier ([SOS-00 §5] TaskState / ReturnCode / SyscallTransport / M7KernelPriorityBand / FpuPolicy / Msg) are re-exported by reference, not redefined.

### 5.1 `TraceTransport` — Standards Action

The on-device peripheral the port uses to emit (and, in Conformance mode, ingest) the trace stream.

| Name | Meaning |
|---|---|
| `Uart` | A USART/UART peripheral. Pin pair per PCDN-SOS-04-003. Baud rate per PCDN-SOS-04-007. The most universal trace transport: works without probe-rs attached; the host-side adapter is `/dev/tty.usbserial-*` or equivalent; both TX and RX are usable, supporting Conformance mode bidirectionally. **v1 default per PCDN-SOS-04-001.** |
| `Swo` | The single-wire trace output. TX-only; suitable for Standalone mode but cannot read vector input (would require a separate ingress channel). Lower CPU overhead than UART because routed through the M7's ITM peripheral. Reserved for future amendment. |
| `SemihostingStdout` | The ARM semihosting `SYS_WRITE0` / `SYS_WRITE` calls. Works only when probe-rs is attached AND probe-rs is configured to route semihosting. TX-only (semihosting RX is non-standard); blocks the CPU per call (each semihosting `BKPT 0xAB` round-trips through the debugger). Reserved; useful only as a bring-up smoke transport. |

Registration policy: **Standards Action.** Adding a value (e.g. `EthernetUdp`, `UsbCdc`) requires a §15 amendment to this doc, an update to the per-transport build feature in `Cargo.toml`, and a new host-side adapter implementation. PCDN-SOS-04-001 ratifies the v1 default value.

### 5.2 `PortMode` — Specification Required

The operating mode the port binary boots into.

| Name | Meaning |
|---|---|
| `Conformance` | The port reads a single JSON-wrapped vector input on its trace transport's RX side (per [SOS-03 §7.6] — `{"config": {...}, "input": [...]}`), executes it, emits one `TraceRecord` per macrostep boundary on TX, then writes the done sentinel and enters an idle `wfi` loop. This is the mode the harness drives. **Default at v1 per PCDN-SOS-04-004.** |
| `Standalone` | The port runs a compiled-in `static` vector array (selected at build time via a `[features]` flag — `--features standalone-smoke`) and emits the trace on TX without reading anything from RX. Used for bench bring-up before the host-side adapter is wired and as a self-test smoke check during firmware iteration. **Supported at v1 per PCDN-SOS-04-004 (both modes; build-time selection).** |

Registration policy: **Specification Required.** Adding a value (e.g. `Interactive` for a future REPL-style port mode, `BatchRecord` for batching multiple vectors into one boot) requires a phase-owner walkthrough update; no §15 amendment.

### 5.3 `StackPolicy` — Standards Action

How the port allocates per-task PSP stacks.

| Name | Meaning |
|---|---|
| `StaticPerTcb` | One PSP region per TCB slot, pre-allocated at link time in the `.task_stacks` linker section. Size per task is `TASK_STACK_BYTES` (PCDN-SOS-04-006 default 2 KiB). The pool occupies `MAX_TASKS * TASK_STACK_BYTES` bytes regardless of how many task slots are activated. **Default at v1 per PCDN-SOS-04-006.** Simple, deterministic, fail-fast (over-stack writes hit the next region's guard pattern, which the port checks at SysTick). |
| `SharedScratch` | A single shared PSP region used as scratch by whichever task is RUNNING; on context switch, the outgoing task's saved registers live in the TCB itself, not in a dedicated PSP region. Smaller memory footprint at the cost of context-switch CPU time (save/restore is now a multi-word copy, not a stack-pointer swap). Reserved for future amendment; not implemented at v1. |

Registration policy: **Standards Action.** Adding a value (e.g. `DynamicAllocator` if `alloc` is ever ratified into scope) requires a §15 amendment.

## 6. Architecture

This section is **load-bearing**. It is what an implementer reads when sitting down to write the port. It is what a reviewer reads when asking "does this port realise the [SOS-00 §6] contract row-by-row?"

### 6.1 Crate layout

The `sos-m7-rust` crate sits at `ports/m7-rust/sos-m7-rust/`. This is **NOT** under `sim/` — `sim/` is reserved for host-only crates per the [SOS-02 §6.1] layout (sibling `sim/sos-sim/` and post-SOS-03 `sim/sos-conformance/`). The `ports/m7-rust/` parent directory exists per [SOS-00 §8] artifact map.

```
ports/m7-rust/
├── sos-m7-rust/                        # the M7 firmware crate
│   ├── Cargo.toml                      # crate manifest; target thumbv7em-none-eabihf
│   ├── memory.x                        # linker memory layout
│   ├── build.rs                        # writes memory.x into OUT_DIR for cortex-m-rt
│   └── src/
│       ├── main.rs                     # cortex-m-rt `#[entry]` point; mode dispatch
│       ├── kernel.rs                   # transliterated chart behaviour (syscall bodies, scheduler, tick service)
│       ├── handlers.rs                 # `#[exception]` bodies (PendSV, SVC, SysTick) and `#[interrupt]` shims
│       ├── transport.rs                # trace ingress + egress (Uart impl at v1)
│       ├── trace.rs                    # TraceRecord type + hand-rolled JSON writer satisfying SOS-02 §7
│       ├── datamodel.rs                # static pools: TCB_POOL, READY_POOL, SEM_POOL, QUEUE_POOL, KERNEL_STACK, TASK_STACKS
│       ├── critical.rs                 # BASEPRI raise/lower wrappers per SOS-00 §6.5
│       └── disco_bsp.rs                # board-specific bring-up: clock tree, GPIO AF, UART setup
└── sos-m7-rust-host-driver/            # host-side adapter binary (host-only Rust crate)
    ├── Cargo.toml
    └── src/
        └── main.rs                     # opens /dev/tty.* (or socket); bridges stdin/stdout to UART
```

The host-side adapter is a **separate workspace member** (or a separate crate not in the workspace; PCDN-SOS-04-009 decides). It compiles for the host (Linux x86_64, macOS arm64), not for the M7. It contains no kernel logic.

The kernel-side crate's `Cargo.toml` declares:

| Property | Value |
|---|---|
| `[package].name` | `sos-m7-rust` |
| `[package].edition` | `2021` |
| `[package].rust-version` | `1.75` (mirrors [SOS-02] PCDN-004) |
| `[lib]` / `[[bin]]` | `[[bin]]` only; this is a firmware crate, not a library. |
| `[dependencies]` | `cortex-m`, `cortex-m-rt`, `stm32h7` (or `stm32h7xx-hal`), `panic-halt`, `embedded-io` |
| `[features]` | `standalone-smoke` (selects Standalone mode + compiled-in static vector); default empty |
| `[profile.release]` | `lto = "fat"`, `codegen-units = 1`, `opt-level = "s"` (size-first), `panic = "abort"` |

### 6.2 Vector-driven harness mode (Conformance mode)

When `PortMode = Conformance`:

1. **Boot path** runs (§6.8): clock tree, GPIO AF, UART setup, task-pool init, kernel-stack initialisation, NVIC priority assignment per [SOS-00 §6.2].
2. **Idle task** is brought to RUNNING (the chart's boot block sets `current = 0`); the boot-quiescence `TraceRecord` (`after_input_idx = -1`) is emitted on TX.
3. The kernel's main loop polls the trace transport's RX side for a complete vector input (a single JSON document of shape `{"config": {...}, "input": [...]}`).
4. The input is parsed (per §6.2.1 below). Parse errors emit a diagnostic record (out-of-band; reserved for PCDN-SOS-04-005 follow-up; v1 may simply emit the done sentinel and halt).
5. The kernel walks `input[i]` for `i = 0..N-1`, dispatching each event to the corresponding transition body (the transliterated chart logic in `kernel.rs`). After each macrostep reaches quiescence, a `TraceRecord` is emitted on TX.
6. After all input is consumed, the done sentinel record (`{"__sos_done": true}`) is emitted (PCDN-SOS-04-005).
7. The port enters a `wfi` idle loop. The host-side adapter sees the done sentinel and closes its stdout (per [SOS-03 §7.6], the adapter MUST NOT emit anything other than [SOS-02 §7] records on stdout — the sentinel is the adapter's signal that the next port reset is what restarts the cycle).

The wire framing on the UART is **newline-delimited JSON**: each JSON document (the wrapped vector input on RX; each trace record on TX) ends with `\n`. UART framing has no length prefix, no escape sequences, no checksums. The transport's reliability is the bench cable's reliability; for the seed vectors at v1, that has empirically been sufficient on the disco-analyzer at moderate baud (PCDN-SOS-04-007).

#### 6.2.1 Vector parsing on-device

The port hand-parses the wrapped vector input. The parser MUST:

- Accept arbitrary whitespace between JSON tokens.
- Reject any field not in the closed set: `config` (object), `input` (array). The presence of `name`, `description`, `tags`, `expected_trace` etc. would be a vector-author confusion (the harness strips those before sending — see [SOS-03 §7.6]); the port treats their presence as a parse error and emits the done sentinel without running.
- Reject any `input[i].event` value not in [SOS-01 §5.3] `ExternalEventName`.
- Reject any `from_tid` value outside `[-1, MAX_TASKS)`.

The parser is hand-rolled (no `serde-json-core` dependency; PCDN-SOS-04-008). The grammar accepted is exactly what the harness emits per [SOS-03 §7.6]; it is not a full JSON parser.

### 6.3 Static allocations

Per [SOS-00] INV-S12, the kernel hot path has no allocator. All pools are pre-allocated at link time and accessed via interior-mutability primitives that satisfy the `Sync` constraint imposed by `static` storage. The naming convention:

| Symbol | Type | Storage | Notes |
|---|---|---|---|
| `TCB_POOL` | `static mut TCB_POOL: [Tcb; MAX_TASKS]` | `.bss` | Per-task control blocks. `MAX_TASKS = 8` matches the chart's at-HEAD default. Each `Tcb` is `{ id: i32, prio: i32, state: u8, deadline: i64, blk_obj: i32, msg: Msg, psp: u32 }` plus a `MaybeUninit<[u32; TASK_STACK_WORDS]>` for the saved-frame backing store (only used when not actively running; while running, the live frame is on the task's PSP region in `TASK_STACKS`). |
| `READY_POOL` | `static mut READY_POOL: [ReadyQueue; MAX_PRIO]` | `.bss` | One FIFO per priority. Each `ReadyQueue` is a small `heapless::Vec<i32, MAX_TASKS>` (or equivalent — a fixed-capacity ring; PCDN-SOS-04-010 considers `heapless` vs a hand-rolled ring). |
| `SEM_POOL` | `static mut SEM_POOL: [Sem; MAX_SEMS]` | `.bss` | Per-semaphore record `{ valid: bool, count: i32, max: i32, waiters: heapless::Vec<i32, MAX_TASKS> }`. |
| `QUEUE_POOL` | `static mut QUEUE_POOL: [Queue; MAX_QUEUES]` | `.bss` | Per-queue record `{ valid: bool, cap: i32, count: i32, buf: heapless::Vec<i64, Q_DEPTH>, sendw: ..., recvw: ... }`. |
| `KERNEL_STACK` | `#[link_section = ".kernel_stack"] static mut KERNEL_STACK: [u32; KERNEL_STACK_WORDS]` | `.kernel_stack` (see `memory.x`) | MSP backing store. `KERNEL_STACK_WORDS = 1024` (4 KiB) per PCDN-SOS-04-006 default. |
| `TASK_STACKS` | `#[link_section = ".task_stacks"] static mut TASK_STACKS: [[u32; TASK_STACK_WORDS]; MAX_TASKS]` | `.task_stacks` | Per-task PSP regions. `TASK_STACK_WORDS = 512` (2 KiB) per PCDN-SOS-04-006 default. |
| `TRACE_TX_BUF` | `static mut TRACE_TX_BUF: [u8; TRACE_TX_BUF_SIZE]` | `.bss` | Egress buffer for trace records; one record's worth at a time (~2 KiB at MAX_TASKS=8 / MAX_SEMS=8 / MAX_QUEUES=4 — measured at SOS-02 §7.3 example). |
| `TRACE_RX_BUF` | `static mut TRACE_RX_BUF: [u8; TRACE_RX_BUF_SIZE]` | `.bss` | Ingress buffer for the wrapped vector input. Size sufficient for the largest seed vector's wrapped form (~16 KiB upper bound from boundary-suite estimates; PCDN-SOS-04-010 ratifies the precise number once boundary vectors land). |
| `BOOT_DONE` | `static BOOT_DONE: AtomicBool = AtomicBool::new(false)` | `.bss` | Signals the boot path is complete (set just before the first SysTick fires). Used by the trace egress path to defer writing until boot quiescence. |

**`MaybeUninit` vs `Cell` patterns for soundness.** The `static mut` declarations above are sound under one of two disciplines:

- **`MaybeUninit` pattern:** declare each pool as `static mut POOL: MaybeUninit<[Tcb; MAX_TASKS]> = MaybeUninit::uninit()`; initialise in the boot path before any other code reads it; access through `unsafe { POOL.assume_init_mut() }` thereafter. The discipline is "initialise once at boot; the &mut reference's lifetime is bounded to within a critical section". The unsafe block is the trust marker; the BASEPRI-raise context is the access guard.
- **`UnsafeCell` / `SyncUnsafeCell` pattern:** wrap each pool in `SyncUnsafeCell<[Tcb; MAX_TASKS]>` and access through `&*pool.get()` / `&mut *pool.get()`. Same discipline; explicitly invokes the interior-mutability primitive at every access. More verbose; clearer trust marker.

v1 uses the **`UnsafeCell` pattern** consistently per PCDN-SOS-04-011. Reasoning: the trust marker is at every access site, not just at initialisation; reviewers see "this is a deliberate interior-mutability access" without scanning back to the declaration. The MaybeUninit pattern is more idiomatic in some Rust circles but its "is this initialised?" mental load is unnecessary when the boot path is the only initialiser.

### 6.4 PendSV handler body

PendSV is the context-switch primitive per [SOS-00 §6.1] and [SOS-00 §6.4]. Its body is the single most subtle piece of the port. The handler is a `cortex-m-rt` `#[exception]` function:

```text
#[exception]
fn PendSV() {
    unsafe {
        asm!(
            // 1. On entry, MSP = handler stack; PSP = current task's stack.
            //    LR holds EXC_RETURN; bit 4 == 0 means the outgoing frame is the
            //    extended (FPU) 26-word form, bit 4 == 1 means the standard 8-word form.
            "mrs   r0, psp",            // r0 := PSP of outgoing task
            "tst   lr, #0x10",          // EXC_RETURN bit 4
            "it    eq",                 // if extended frame...
            "vstmdbeq r0!, {{s16-s31}}",// save the callee-saved FP registers (S16-S31)
            "stmdb r0!, {{r4-r11, lr}}", // save R4-R11 and EXC_RETURN
            //
            // 2. Stash the outgoing PSP into the outgoing TCB.
            //    PendSV is called *after* the syscall path has already updated `current`
            //    to the next-task id, so we need the OLD `current` here. The kernel
            //    body stashed the OLD `current` into a static `OUTGOING_TID` before
            //    pending PendSV; we read it here.
            "ldr   r1, =OUTGOING_TID",
            "ldr   r1, [r1]",
            "ldr   r2, =TCB_POOL_PSP_OFFSETS", // table of &Tcb.psp offsets
            "ldr   r2, [r2, r1, lsl #2]",
            "str   r0, [r2]",            // tcb[OUTGOING_TID].psp = r0
            //
            // 3. Load the incoming task's PSP.
            "ldr   r1, =CURRENT_TID",
            "ldr   r1, [r1]",
            "ldr   r2, =TCB_POOL_PSP_OFFSETS",
            "ldr   r2, [r2, r1, lsl #2]",
            "ldr   r0, [r2]",            // r0 := tcb[CURRENT_TID].psp
            //
            // 4. Restore R4-R11 and EXC_RETURN from the incoming frame.
            "ldmia r0!, {{r4-r11, lr}}",
            "tst   lr, #0x10",
            "it    eq",
            "vldmiaeq r0!, {{s16-s31}}", // restore FP callee-saved if extended
            "msr   psp, r0",
            //
            // 5. Memory barrier before exception return — ensures the PSP write is
            //    visible before the exception epilogue uses it.
            "dsb",
            "isb",
            //
            // 6. Return from exception; the hardware pops the standard frame
            //    (R0-R3, R12, LR, PC, xPSR; plus S0-S15 + FPSCR + padding if extended)
            //    from the new PSP. Execution resumes in the incoming task.
            "bx    lr",
            options(noreturn),
        );
    }
}
```

The `OUTGOING_TID` / `CURRENT_TID` symbols are static `AtomicI32` cells the kernel body updates from the `DirectCallBasepri` syscall path (per [SOS-00] PCDN-SOS-00-002 → `DirectCallBasepri`). The `TCB_POOL_PSP_OFFSETS` symbol is a build-time-computed table of byte offsets into `TCB_POOL` such that `TCB_POOL_PSP_OFFSETS[tid] = &(TCB_POOL[tid].psp) as u32`. The table is generated by `build.rs` and emitted as a `.rodata` constant.

The handler satisfies [SOS-00 §6.4] exactly:
- `EXC_RETURN[4] == 1` → standard 8-word frame; save/restore R4–R11.
- `EXC_RETURN[4] == 0` → extended 26-word frame; save/restore R4–R11 **and** S16–S31 (the hardware handles S0–S15 + FPSCR).
- The DSB/ISB pair before `bx lr` is required by the architecture so the new PSP is visible to the exception epilogue.

PendSV NVIC priority is `0xE0` per [SOS-00 §6.2]. Set in the boot path via `cortex_m::peripheral::SCB::set_priority(SystemHandler::PendSV, 0xE0)`.

### 6.5 SVC handler

Per [SOS-00] PCDN-SOS-00-002 → `DirectCallBasepri`, SVC is **unused** at v1. The handler is **still installed** (a `cortex-m-rt` `#[exception] fn SVCall()` that traps and halts) so that an accidental `svc #imm` instruction is caught immediately, not silently ignored.

```text
#[exception]
unsafe fn SVCall() {
    // SVC must never fire under DirectCallBasepri. Reaching here is a port bug.
    cortex_m::asm::bkpt();
    loop { cortex_m::asm::wfi(); }
}
```

The handler is **reserved** for the planned future `SvcInstruction` migration per [SOS-00 §5.3] / §15 (the migration ratifies in a future SOS-04-B / SOS-05-B amendment once v1 ports are conformance-validated). The reservation keeps the handler symbol stable across that migration.

### 6.6 SysTick handler body

Per [SOS-00 §6.1] and [SOS-00 §6.6]:

```text
#[exception]
fn SysTick() {
    // 1. Issue the `sys.tick` external event to the kernel.
    //    The kernel updates tick_count, expires delays, processes pend_ticks.
    //    Returns whether a reschedule is required.
    let resched = unsafe { kernel::on_sys_tick() };

    // 2. If reschedule needed, pend PendSV; the hardware tail-chains.
    if resched {
        cortex_m::peripheral::SCB::set_pendsv();
    }

    // 3. After every macrostep boundary, emit a TraceRecord on the trace transport.
    //    BOOT_DONE gates this until the boot path has emitted the baseline record.
    if BOOT_DONE.load(Ordering::Acquire) {
        unsafe { trace::emit_post_tick_record() };
    }
}
```

SysTick NVIC priority is `0xC0` per [SOS-00 §6.2] — above PendSV (`0xE0`), below `*_from_isr` IRQs (`0xA0`). Period is `(SystemCoreClock / SOS_TICK_HZ) - 1` per [SOS-00 §6.6]; at default `SOS_TICK_HZ = 1000` and `SystemCoreClock = 400_000_000` (PCDN-SOS-04-013), `LOAD = 399_999`.

The `kernel::on_sys_tick()` function is the transliterated chart body for the `tick_idle.transition[event="sys.tick"]` script ([SOS-02 §6.3] script-name table — `script_tick_idle_sys_tick_0`). The transliteration is mechanical per [SOS-02 §6.3]; the transliterated form lives in `kernel.rs`.

### 6.7 Critical section wrappers

Per [SOS-00 §6.5]: `crit.enter` raises BASEPRI to `0xA0`; `crit.exit` lowers BASEPRI to `0x00`. The realisation:

```text
#[inline(always)]
pub fn crit_enter() {
    cortex_m::register::basepri::write(0xA0);
    cortex_m::asm::dsb();
    cortex_m::asm::isb();
}

#[inline(always)]
pub fn crit_exit() {
    cortex_m::asm::dsb();
    cortex_m::asm::isb();
    cortex_m::register::basepri::write(0x00);
}
```

The DSB/ISB pair after the BASEPRI write (on enter) ensures the mask is in force before any kernel-state access; the DSB/ISB pair before the BASEPRI write (on exit) ensures all kernel-state writes are visible before the mask is lifted.

`cortex_m::interrupt::free` is **NOT** used as the critical-section primitive because it uses PRIMASK (CPSID I), which masks every interrupt — heavier than required. [SOS-00 §6.5] permits `cortex_m::interrupt::free` only for fully-bracketed non-blocking critical sections where the closure body cannot block ([SOS-00] INV-S5); the port's critical-section path can block (a `block_current()` call may pend a context switch) and so cannot use `interrupt::free`.

Every syscall wrapper (the entry point for each `ExternalEventName` from [SOS-01 §5.3]) follows the pattern:

```text
pub fn task_yield() -> ReturnCode {
    crit_enter();
    let resched = unsafe { kernel::script_sys_idle_task_yield_0(/* event payload */) };
    if resched {
        // Stash OUTGOING_TID = current_tid; CURRENT_TID was already updated by the body.
        cortex_m::peripheral::SCB::set_pendsv();
    }
    crit_exit();
    // PendSV fires immediately on crit_exit because BASEPRI drops below 0xE0.
    kernel::read_rc()
}
```

The `kernel::script_*` functions are the transliterated chart bodies per [SOS-02 §6.3]; the wrappers above them are the `DirectCallBasepri` envelope per [SOS-00] PCDN-SOS-00-002.

### 6.8 Boot path

The reset vector → first `wfi` sequence:

1. **Reset handler.** `cortex-m-rt` materialises the reset vector; jumps to `Reset` which copies `.data` from FLASH to RAM, zeroes `.bss`, sets MSP from the linker symbol `_stack_start`, and calls `main`.
2. **`main`** (`#[entry] fn main() -> !` in `src/main.rs`):
   1. **Clock-tree configuration** (`disco_bsp::init_clocks()`): configure RCC to derive a 400 MHz CM7 clock from the disco-analyzer's 25 MHz HSE crystal via PLL1. The specific PLL ratios are PCDN-SOS-04-013 (default: HSE / 5 = 5 MHz reference; PLL1.N = 160 → VCO = 800 MHz; PLL1.P = 2 → sys = 400 MHz CM7; CM4 clocked from the same PLL1.P / 2 = 200 MHz but held in reset).
   2. **Peripheral clock enables** (RCC ENRs): GPIOA / GPIOB / GPIOD (depending on UART pin choice, PCDN-SOS-04-003); USART/UART for the trace transport; SysTick (always enabled by `cortex-m-rt`).
   3. **GPIO AF mode** for the trace UART's TX and RX pins. Pin assignments per PCDN-SOS-04-003 (recommend pins exposed on the disco-analyzer's STMod+ header or Arduino-compatible headers, NOT the pins used by SAI / LTDC / ETH on the live DAA firmware — though the board is in flash-swap mode so live-DAA conflict does not apply; the recommendation is for human-readability of the pinout, not coexistence).
   4. **UART configuration**: baud rate per PCDN-SOS-04-007 (default 921600 — high enough to keep the trace stream from bottlenecking the seed vectors, low enough to be reliable on the bench cable); 8N1; no flow control.
   5. **Task pool init** (`datamodel::init_pools()`): zero `TCB_POOL`, `READY_POOL`, `SEM_POOL`, `QUEUE_POOL`. Materialise the idle task (TCB[0]) at PSP region 0 of `TASK_STACKS` with priority 0 and `state = ST_RUNNING`; set `current = 0`.
   6. **NVIC priority assignment** per [SOS-00 §6.2]: PendSV `0xE0`, SysTick `0xC0`; the `*_from_isr` IRQs are assigned `0xA0` at the moment they are enabled (for the v1 seed vectors, no hardware IRQ is necessary — `sys.tick` is emitted by SysTick, all other events come from the vector input; the `*_from_isr` priority is a discipline placeholder, not a v1 wiring).
   7. **PRIGROUP = 0** (all-preempt) per [SOS-00 §6.2]. Set via `cortex_m::peripheral::SCB::set_priority_grouping(0)`.
   8. **Vector table placement** per [SOS-00 §6.7]. Default placement at the start of FLASH (`0x0800_0000` on the H747 — actually the H747's CM7 reset vector is at `0x0800_0000` for the boot bank by default; PCDN-SOS-04-012 ratifies the bank choice). `cortex-m-rt` handles the linker glue.
   9. **SysTick enable** (`cortex_m::peripheral::SYST::set_clock_source(SystClkSource::Core); set_reload(LOAD); clear_current(); enable_counter(); enable_interrupt()`). Source the CM7 clock per [SOS-00 §6.6].
   10. **Mode dispatch**:
       - If `cfg!(feature = "standalone-smoke")` → run `kernel::run_static_vector(&STATIC_SMOKE_VECTOR)` (Standalone mode).
       - Else → emit the boot-baseline `TraceRecord` (`after_input_idx = -1`) on TX; set `BOOT_DONE = true`; enter the Conformance-mode RX poll loop.
   11. **Idle `wfi` loop**: after the vector is fully consumed and the done sentinel is emitted, drop into `loop { cortex_m::asm::wfi(); }`. SysTick continues firing (kernel state has settled; `pick_next` always returns idle).

### 6.9 Disco-analyzer bench substrate notes

The port targets the **STM32H747I-DISCO** board at the disco-analyzer subrepo's `streamz/submodules/disco-analyzer/`. Per [SOS-00] PCDN-SOS-00-001 → (b), SOS firmware **replaces** the DAA firmware at flash-swap time; the two never coexist on a single image. The operator manages the flash swap between SOS validation rounds and DAA work.

Concrete bench notes (subject to PCDN ratification — the defaults below are recommendations, not yet binding):

| Concern | Default (recommendation) | PCDN |
|---|---|---|
| Trace UART pin pair | USART1 on PA9 (TX) / PA10 (RX), AF7 — exposed on Arduino-D8 / Arduino-D2 of the disco-analyzer's Arduino-compatible header | PCDN-SOS-04-003 |
| Trace UART baud rate | 921600 | PCDN-SOS-04-007 |
| HSE crystal | 25 MHz (board-fixed) | n/a |
| PLL1 ratios | HSE/5 → 5 MHz ref; N=160 → 800 MHz VCO; P=2 → 400 MHz CM7 | PCDN-SOS-04-013 |
| CM7 sys clock | 400 MHz | PCDN-SOS-04-013 |
| CM4 state | Held in reset; CM4 firmware not loaded | n/a (mirrors [SOS-00] §11 SMP non-goal) |
| FLASH bank | Bank 1 (boot at `0x0800_0000`) | PCDN-SOS-04-012 |
| Probe-rs chip target | `STM32H747XIHx` | n/a (probe-rs default) |
| Probe-rs flash command | `probe-rs run --chip STM32H747XIHx target/thumbv7em-none-eabihf/release/sos-m7-rust` | n/a |
| Reset semantics | `probe-rs reset` resets the CM7; CM4 is already in reset and stays there | n/a |

Per the parent CLAUDE.md's "Bench-hardware authorization" rule and the durable memory `feedback_no_speculative_board_reset`, flashing the disco-analyzer board for SOS-04 validation requires an explicit per-round user authorisation signal. Read-only probe-rs operations (memory reads, register snapshots, halt-and-resume that doesn't modify flash) are unconstrained.

The disco-analyzer's existing FreeRTOS firmware uses certain peripherals heavily (SAI for audio, LTDC for display, ETH for diagnostics) but SOS does NOT coexist with that firmware. The pin selections above are chosen for human-readability of the pinout (exposed on a header silkscreened "D8/D2") rather than for FreeRTOS-coexistence avoidance.

## 7. Conformance-mode protocol

The port binary's stdin / stdout contract is satisfied through the **host-side adapter** per the §3 glossary. The adapter sits between the [SOS-03 §7.6] harness and the M7's UART:

```
harness (sos-conformance)
   │ stdin (JSON: {"config":{...},"input":[...]})
   ▼
sos-m7-rust-host-driver  (host binary; opens /dev/tty.usbserial-*)
   │ UART TX (raw bytes)
   ▼
sos-m7-rust  (M7 firmware; reads RX, runs kernel, emits trace on TX)
   │ UART RX (JSONL records + done sentinel)
   ▼
sos-m7-rust-host-driver
   │ stdout (JSONL trace records; sentinel filtered out)
   ▼
harness (sos-conformance)
```

### 7.1 The adapter's contract

The host-side adapter MUST:

- Accept the harness's stdin JSON document (the wrapped vector input) and write it byte-for-byte to the UART TX, terminating with `\n`.
- Read bytes from the UART RX into a line buffer; each `\n`-terminated line is one trace record (or the done sentinel).
- Emit each trace record on stdout, terminated with `\n`. Trace records pass through unmodified.
- On encountering the done sentinel record (`{"__sos_done": true}`), filter it out (do NOT emit it on stdout — it is not part of `expected_trace` per [SOS-03 §6.2]) and close stdout (flush + exit cleanly).
- Exit code 0 if the M7 emitted a done sentinel; non-zero if the UART times out before the sentinel arrives (timeout per PCDN-SOS-04-014 default 30 s — sufficient for any seed or boundary vector).

The host-side adapter MUST NOT:

- Modify any record (no field reordering, no whitespace normalisation, no value re-serialisation). [SOS-03 §6.5] is a *structural* diff, but byte-stability through the adapter is the safer invariant: any tampering risks a structural-diff false-negative that masks a real port bug.
- Spawn the firmware (firmware lifecycle is operator-controlled via probe-rs; the adapter assumes the firmware is already running).
- Open files other than the serial device (no logging-to-file at v1; stderr free-form for diagnostics).
- Read environment variables for behaviour beyond the serial-device path (`SOS_TTY` MAY be consulted in lieu of a hardcoded `/dev/tty.usbserial-*` — actually no, per [SOS-03 §7.6] / §7.1 invariants, the harness binary forbids env-var reads at the harness level; the adapter is downstream of the harness but the adapter is also a port binary in the [SOS-03 §7.6] sense, so the same rule applies — the adapter takes the serial path via CLI flag, not env var).

### 7.2 The firmware's protocol

The firmware MUST:

- Read RX bytes into `TRACE_RX_BUF` until a complete JSON document is received (balanced braces, terminated by `\n`).
- Parse the document into `(Config, Vec<Event>)` per §6.2.1.
- Run the boot macrostep, emit the boot-baseline record.
- For each event, dispatch, run macrostep to quiescence, emit one `TraceRecord`.
- After the last event's record, emit the done sentinel.
- Enter `wfi` idle loop.

The firmware MUST NOT:

- Emit anything on TX other than `\n`-terminated JSON records (no debug logging, no banners, no progress bars). Stderr-equivalents are reserved for SWO if PCDN-SOS-04-001 ever expands TraceTransport to include SWO as a *diagnostic* sidekick rather than the main transport.
- Block indefinitely on RX if no input arrives — there is no v1 timeout (the operator power-cycles or probe-rs-resets the board to abort), but a future amendment may add a wdt-driven timeout.
- Restart its kernel state between vectors. **One vector per boot.** The board is reset between vectors by the host-side adapter / operator (probe-rs reset or power cycle). Batching multiple vectors per boot is a future amendment (`PortMode::BatchRecord`).

### 7.3 Done sentinel and the [SOS-03 §6.2] amendment

PCDN-SOS-04-005 proposes the `{"__sos_done": true}` sentinel as the firmware's end-of-trace signal. The sentinel is **not** a `TraceRecord` (it has no `after_input_idx`, no `tcb`, etc.); the harness's structural comparator would reject it as a parse error if it ever reached the harness. The host-side adapter filters it.

Ratifying the sentinel requires:
- A [SOS-03 §15] amendment registering the sentinel as a permitted-but-not-required final line in any port's stdout stream. The harness's parser becomes "if the next line matches the sentinel JSON schema exactly, drop it and EOF the stream"; alternatively, the harness's parser stays as-is and the **adapter** filters the sentinel (the v1 approach in this doc per PCDN-SOS-04-005).
- The `__sos_done` field name is reserved at the trace-format level: no `TraceRecord` may carry it; per [SOS-02 §7.4] field-name policy this is enforceable as a forward-compatible reservation.

PCDN-SOS-04-005's recommended ratification path is **adapter-filtered**: no [SOS-03] amendment needed; the sentinel is a firmware-to-adapter-only protocol that never reaches the harness. The §15 entry below records this; if the user prefers the harness-filtered alternative, a [SOS-03 §15] amendment lands first.

## 8. Build-time and runtime artifact map

| Artifact | Path (relative to subrepo root) | Build-time? | Runtime? | Notes |
|---|---|---|---|---|
| Workspace `Cargo.toml` | `Cargo.toml` | input | n/a | Pre-existing per [SOS-02] PCDN-005. SOS-04 adds `ports/m7-rust/sos-m7-rust/` and `ports/m7-rust/sos-m7-rust-host-driver/` as workspace members (PCDN-SOS-04-009). |
| Firmware crate | `ports/m7-rust/sos-m7-rust/` | n/a | M7 binary | Cross-compiled to `thumbv7em-none-eabihf`. |
| Firmware manifest | `ports/m7-rust/sos-m7-rust/Cargo.toml` | input | n/a | Declares the cortex-m / cortex-m-rt / stm32h7 / panic-halt / embedded-io dependency set. |
| Linker script | `ports/m7-rust/sos-m7-rust/memory.x` | input | n/a | Declares FLASH (1 MiB at `0x0800_0000`), RAM (D1 AXI-SRAM 384 KiB at `0x2400_0000`), DTCM (128 KiB at `0x2000_0000`), ITCM (64 KiB at `0x0000_0000`), and the `.kernel_stack` / `.task_stacks` sections. Per PCDN-SOS-04-012, default placement uses Bank 1 FLASH; DTCM hosts `.bss` + `.data`; AXI-SRAM hosts `.kernel_stack` + `.task_stacks` + `TRACE_*_BUF` (DTCM is reserved for compact .bss + .data; the heavier stack pool benefits from AXI-SRAM's larger size). |
| Firmware sources | `ports/m7-rust/sos-m7-rust/src/{main,kernel,handlers,transport,trace,datamodel,critical,disco_bsp}.rs` | input | linked into firmware binary | Per §6.1 layout. |
| Firmware build artifact | `target/thumbv7em-none-eabihf/release/sos-m7-rust` (ELF) | output | runtime (on board) | Flashable via probe-rs. |
| Host-side adapter crate | `ports/m7-rust/sos-m7-rust-host-driver/` | n/a | host binary | The §3 glossary's "host-side adapter". |
| Host-side adapter manifest | `ports/m7-rust/sos-m7-rust-host-driver/Cargo.toml` | input | n/a | Declares `serialport` (or equivalent) for UART access, `clap` for the CLI. |
| Host-side adapter binary | `target/release/sos-m7-rust-host-driver` | output | runtime (host) | The binary the [SOS-03 §7.6] harness invokes as `--port`. |
| Smoke test vector (Standalone mode) | `ports/m7-rust/sos-m7-rust/src/static_smoke_vector.rs` | input | linked into firmware (only with `--features standalone-smoke`) | A compiled-in form of seed vector 0001 for bench bring-up before the host-side adapter is wired. |

Build commands (the canonical sequence):

```
# Build the firmware (release; with size optimisation)
RUSTFLAGS="-C target-cpu=cortex-m7" \
cargo build --target thumbv7em-none-eabihf --release -p sos-m7-rust

# Build the host-side adapter
cargo build --release -p sos-m7-rust-host-driver

# Flash the firmware (operator-authorised per parent CLAUDE.md bench rule)
probe-rs run --chip STM32H747XIHx \
    target/thumbv7em-none-eabihf/release/sos-m7-rust

# Conformance smoke test (after firmware is flashed and host-side adapter is built):
./target/release/sos-conformance run \
    --suite conformance/vectors/ \
    --filter 'smoke/0001-*' \
    --port ./target/release/sos-m7-rust-host-driver
```

The `RUSTFLAGS` env-var override is required when the shell's default `RUSTFLAGS` (often set to `-fuse-ld=mold` per developer-environment defaults) conflicts with `cortex-m-rt`'s linker-script expectations. The pattern matches the disco-analyzer team's existing convention (per the parent memory `project_daa_freertos_bringup`'s "`RUSTFLAGS="-C target-cpu=cortex-m7"` to override the shell's mold link flag").

The firmware's `Cargo.toml` declares no `[features]` block beyond `standalone-smoke`. Per PCDN-SOS-04-015, conditional compilation for the M7 vs the M4 (the chart is one-core-per-port per [SOS-00] INV-S14; SOS-04 is M7-only) is hardcoded — no feature gate selects between cores at v1.

## 9. Invariants

Each invariant carries a stable id in the `INV-S-PORT-N` series. Amendments require a §15 entry on this doc.

- **INV-S-PORT-0 — Crawl boundary.** SOS-04 reviewers consult this doc plus [SOS-00 §6] plus the published `cortex-m` / `cortex-m-rt` / `stm32h7` API documentation. The ARMv7-M ARM, RM0399, and the sibling `disco-analyzer/` crates are NOT routine crawl targets. (Mirrors [SOS-00] INV-S1 at the port surface.)

- **INV-S-PORT-1 — Conformance.** SOS-04 MUST pass every vector in the [SOS-03] suite at the suite's pinned Suite SHA. The default conformance claim at v1 implementation is `FullSuitePass` (per [SOS-03 §5.2]); `FullSuitePassWithDiversity` is aspirational but not required.

- **INV-S-PORT-2 — NVIC priorities per [SOS-00 §6.2].** PendSV at `0xE0`, SysTick at `0xC0`, `*_from_isr` IRQs at `0xA0`. PRIGROUP = 0 (all-preempt). System-reserved band (`0x00`–`0x9F`) MUST NOT be used by any SOS-installed handler. The boot path's NVIC setup is the single point of priority assignment; per-driver priority writes outside boot are forbidden.

- **INV-S-PORT-3 — PendSV save/restore per [SOS-00 §6.4].** The PendSV handler inspects `EXC_RETURN[4]` and saves/restores R4–R11 in the standard case, plus S16–S31 in the extended case. The hardware-saved S0–S15 + FPSCR are NOT touched by the handler. The discriminator byte / saved-PSP format is the port's choice; the contract is the architectural-frame layout, not the in-TCB layout.

- **INV-S-PORT-4 — Minimal peripherals.** The boot path MUST NOT enable any peripheral the chart does not model. v1 enables: RCC (clock tree), GPIO for the UART, the UART itself, SysTick. No SAI, no LTDC, no DMA except whatever the trace transport intrinsically requires (UART is interrupt-driven at v1, no DMA — PCDN-SOS-04-016 considers UART DMA as a future amendment for high-baud-rate scenarios). No ETH, no USB, no SDMMC, no QUADSPI. The principle: every enabled peripheral expands the bench-state-space; the port resists feature creep ruthlessly at v1.

- **INV-S-PORT-5 — No FreeRTOS-Kernel symbol.** The firmware binary MUST NOT link any FreeRTOS-Kernel symbol. (Mirrors [SOS-00] INV-S10 at the port linker surface.)

- **INV-S-PORT-6 — No allocator.** The firmware binary MUST NOT link `alloc`. The `panic-halt` crate satisfies this (no `format!` panic messages). (Mirrors [SOS-00] INV-S12 at the port surface.) Notes: `heapless` is permitted because `heapless` is allocator-free by construction; using `heapless::Vec` does not introduce an allocator dependency.

- **INV-S-PORT-7 — No DAA / rlvgl dependency.** The firmware crate's `Cargo.toml` MUST NOT depend on `rlvgl-*`, `analyzer-*`, `analyzer-rtos`, or any sibling subrepo crate. (Reasserts [SOS-00] §10 reconciliation at the dependency-graph surface.)

- **INV-S-PORT-8 — v1 scope: REFERENCE not PRODUCTION.** Production hardening (watchdog, fault handlers beyond the default-halt panic, low-power modes, persistence across power cycles, firmware update, hot-reload) is **OUT OF SCOPE at v1**. A future `SOS-04-B` amendment ratifies hardening once the v1 reference is conformance-validated and the operator has bench experience driving it. v1 satisfaction of this invariant is: builds, flashes, brings up kernel-aware ISR set, runs seed vectors, emits passing traces, halts on panic. Nothing more.

- **INV-S-PORT-9 — Byte-equal trace.** The firmware MUST emit `TraceRecord`s in [SOS-02 §7] format byte-for-byte: same field order, same typed-value encoding, same `Msg` discriminator object form. The on-device JSON writer is hand-rolled (PCDN-SOS-04-008 recommendation) precisely to enforce byte-stability against [SOS-02 §7] field order; a `serde-json-core`-based writer would couple to the crate's version-dependent serialisation choices.

- **INV-S-PORT-10 — Exclusive firmware during conformance.** During a conformance run, the SOS firmware MUST be the only firmware on the disco-analyzer board. The DAA FreeRTOS firmware MUST be wiped (flash-bank overwrite) before SOS conformance runs begin; conversely, after a conformance run, the operator MAY flash the DAA firmware back. (Reasserts [SOS-00] PCDN-SOS-00-001 → (b) at the port-binary surface.)

- **INV-S-PORT-11 — CM4 in reset.** The CM4 core MUST remain in reset throughout SOS-04 operation. The port firmware does not boot CM4 (no second-stage bootloader entry, no HSEM-mediated handoff). [SOS-00] §11 lists SMP / core-affinity as a non-goal; INV-S-PORT-11 enforces it at the M7-Rust-port surface. (A future amendment could relax this if a multi-core SOS variant is ratified, but no such variant is in scope at v1.)

- **INV-S-PORT-12 — Done sentinel is adapter-local.** The `{"__sos_done": true}` sentinel emitted by the firmware MUST be filtered by the host-side adapter; the sentinel MUST NOT reach the harness. (Per PCDN-SOS-04-005's adapter-filtered ratification path; if the user prefers harness-filtered, a [SOS-03 §15] amendment ratifies first and INV-S-PORT-12 reverses.)

- **INV-S-PORT-13 — Chart immutability.** The port MUST NOT modify `rtos_kernel.scxml` at runtime, MUST NOT carry a runtime parser for it, MUST NOT depend on the chart being present in any filesystem at runtime. The chart's behaviour is transliterated into Rust at port-build time and frozen at the implementation commit. Behaviour changes ratify via [SOS-00 §15], then update the chart, then regenerate the transliteration. (Mirrors [SOS-00] INV-S11 at the port surface; mirrors [SOS-02] INV-S-SIM-8 at the firmware surface.)

## 10. Reconciliation with adjacent repo primitives

| Primitive | Relationship to SOS-04 |
|---|---|
| `streamz-exec` (parent `softoboros.com` Tokio-hosted runtime) | Not a dependency. SOS-04 firmware is M7 native; the host-side adapter is a host binary that runs as a child of `sos-conformance`, not of `streamz-exec`. |
| `sos-sim` ([SOS-02]) | Not a runtime dependency. The host-side adapter MAY depend on `sos-sim` for pre-flight vector validation (a future enhancement); the firmware MUST NOT (INV-S-PORT-7 extends to host-only crates as well at the firmware-binary level — the firmware does not link `sos-sim`). |
| `sos-conformance` ([SOS-03]) | Consumer. The harness drives the host-side adapter, which drives the firmware. The harness has no awareness of the M7-side details. |
| `cortex-m` / `cortex-m-rt` crates | Mirror dependency. Per §4 source-of-truth map. |
| `stm32h7` PAC | Mirror dependency (default per PCDN-SOS-04-002). |
| `stm32h7xx-hal` | Alternative to `stm32h7` PAC; not the default (PCDN-SOS-04-002 recommends PAC + hand-coded minimal BSP). |
| FreeRTOS-Kernel at `disco-analyzer/analyzer-rtos/` | Not a dependency (INV-S-PORT-5 / INV-S10 inheritance). Sibling on the same bench board; coexists by flash-swap (INV-S-PORT-10). |
| `analyzer-cm7` / `analyzer-cm4` crates | Not dependencies (INV-S-PORT-7). The SOS firmware is the only firmware on the board during conformance runs. |
| `rlvgl-*` crates | Not dependencies. SOS has no UI. |
| `rtic`, `embassy` | Not dependencies. Competing runtime models (per §4 negative listing). |
| `probe-rs` (the flashing tool) | Operator tool. The port's firmware is flashed via probe-rs; this is a host-side concern, not a port-binary concern. Bench-flash authorisation is governed by the parent CLAUDE.md rule (memory `feedback_no_speculative_board_reset`). |
| `serialport` (Rust crate, host-side adapter dep) | Mirror dependency, host-side only. Pinned to current 4.x; PCDN-SOS-04-017 ratifies. |
| SOS-05 (M7 C port) | Sibling. Same `rtos_kernel.scxml` source; same [SOS-00 §6] M7 contract; different language and toolchain. SOS-05 is free to make different bench-substrate choices (different UART pins, different baud) but SHOULD mirror SOS-04's choices where reasonable to keep operator muscle memory across ports. SOS-05's host-side adapter is symmetric to SOS-04's. |
| SOS-06 (codegen evaluation) | Consumer. The codegen tool produces a port binary; the harness compares against `sos-sim`. SOS-06's "is codegen good enough?" question depends on SOS-04's hand-written reference for binary-size / interrupt-latency / NVIC-discipline comparison. |

SOS-04 is **the first bench port**. It is upstream of SOS-06 in the comparison chain; it is downstream of SOS-00 / SOS-01 / SOS-02 / SOS-03 in the spec chain. It is a sibling of SOS-05; the two ports stress-test the chart as a spec.

## 11. Non-goals

Frozen non-goals for SOS-04 v1. Each MAY lift via a §15 amendment (most as a `SOS-04-B` or later sub-letter amendment once v1 is conformance-validated).

- **Multi-core operation.** CM4 stays asleep at v1 (INV-S-PORT-11). The chart is one-statechart-per-port per [SOS-00] INV-S14; SMP / core-affinity is a [SOS-00 §11] non-goal at v1. A multi-core SOS variant (one statechart per core; HSEM-mediated cross-core syscalls) is a candidate for a future major amendment, not a v1 horizon.
- **Peripheral drivers beyond the trace transport.** No GPIO output (LED blink) for diagnostics; no SD card; no Ethernet; no USB CDC. The trace UART is the **only** kernel-visible peripheral at v1. Diagnostic LEDs are appealing but introduce a peripheral-state-space the port resists (INV-S-PORT-4).
- **RTIC-like macro framework.** No `#[task]`, no `#[init]`, no `#[idle]` macros wrapping the kernel's vocabulary. The kernel is the chart; the port is the realisation; macros that pretty up the surface obscure the M7 contract the port exists to expose.
- **`embassy`-style async.** No `Future`, no `async fn`, no executor. Tasks are stack-bound; macrosteps are run-to-completion. (`Future`s would introduce a competing macrostep semantics.)
- **ITM beyond what SWO transport needs.** If PCDN-SOS-04-001 ever expands `TraceTransport` to include SWO as the primary or auxiliary transport, ITM is configured to the minimum needed for SWO's "stream 8-bit chars" use case. Multi-port ITM, ETM, full-trace are out of scope.
- **RTT (Real-Time Transfer).** The trace IS the conformance interface; making it also be a debug-logging surface erodes the byte-stability guarantee. Debug logging on RTT is an operator convenience that production-hardening MAY ratify (SOS-04-B); v1 has none.
- **Bench profiling.** Cycle-counting (DWT_CYCCNT-based latency measurements), interrupt-latency probes, kernel-CPU-percentage instrumentation — appealing but not load-bearing for conformance. SOS-06 may want these for codegen comparison; if so, an amendment ratifies them.
- **Power-management modes.** No `__WFE` with wakeup events, no STOP / STANDBY mode entry, no `RCC.PLL1.RANGE` re-configuration. The CM7 runs at a fixed 400 MHz at all times during v1 conformance runs.
- **Production fault recovery.** A divide-by-zero in a task halts the CPU at v1; a stack overflow corrupts the next task's stack region; an unaligned access traps in HardFault and the default handler halts. v1 makes no attempt to recover. SOS-04-B is the home for fault-recovery ratification.
- **Watchdog timer.** The independent watchdog (IWDG) and window watchdog (WWDG) are both unconfigured at v1. SOS-04-B can ratify watchdog usage as part of production hardening.
- **Persistence.** RAM contents are lost on reset. The port retains nothing across boots; every conformance run begins from the boot baseline. This is per-vector-reset-and-re-run, which matches the [SOS-03 §7.6] "one vector per process invocation" contract — the M7 reset is what gives the operator their per-process boundary.
- **Firmware update.** No bootloader, no in-application programming (IAP), no DFU. Operators flash via probe-rs; firmware updates are an out-of-band concern.
- **`cargo test`-runnable port tests.** The port is a firmware target; `cargo test` is host-only. Per-module unit tests (e.g. testing the hand-rolled JSON writer's output) live in a separate `sos-m7-rust-tests` host-only crate (or in `#[cfg(test)]` blocks compiled with the host target — both are workable; PCDN-SOS-04-018 chooses one). The conformance suite is run by `sos-conformance` against the flashed firmware, not by `cargo test`.
- **WebAssembly emulation.** No `wasm32` build of the M7 port. The host simulator ([SOS-02]) covers host-side trace generation; an M7-emulated form would be value-add only if hardware-bench access becomes a chokepoint, which it is not at v1.
- **Codesign with SOS-05.** SOS-04 and SOS-05 share the chart and the M7 contract; they do NOT share Rust↔C interop code, do NOT share the host-side adapter, do NOT share the linker script. The two ports are deliberately independent realisations.

## 12. Acceptance checklist (normative)

### 12.1 Ratification gates

A conforming SOS-04 ratification (the §15 dated entry that flips this doc to 🟢) requires:

(a) All PCDN-SOS-04-NNN open questions in §15 are resolved. Every PCDN has a chosen value, a date, and the corresponding §4 / §5 / §6 / §7 / §8 sections updated to reflect the choice (or explicitly note "PCDN unresolved; section blocks").

(b) §3 glossary, §4 source-of-truth map, §5 frozen enums, §6 architecture, §7 conformance-mode protocol, §9 invariants are internally consistent. A reviewer can answer "what does X mean" by reading at most one section. No vocabulary defined in [SOS-00 §3] / [SOS-01 §3] / [SOS-02 §3] / [SOS-03 §3] is silently restated here.

(c) §6 architecture covers every row of [SOS-00 §6] (exception assignment, priority assignment, stack model, EXC_RETURN inspection, critical section, SysTick clock source, vector table, pre-emption flow). A reviewer can cross-walk [SOS-00 §6]'s eight sub-sections against this doc's §6.1–§6.9 and find every contract surface realised.

(d) §7 conformance-mode protocol is consistent with [SOS-03 §7.6] port-binary contract. A reviewer can cross-check this doc's §7 against [SOS-03 §7.6] and find no contradiction. PCDN-SOS-04-005's done-sentinel choice (adapter-filtered vs harness-filtered) is reflected consistently across §7.1, §7.3, and INV-S-PORT-12.

(e) §9 INV-S-PORT-N invariants are pairwise non-contradictory with [SOS-00 §9] INV-S-N, [SOS-02 §9] INV-S-SIM-N, and [SOS-03 §9] INV-S-CONF-N invariants. Any INV-S-PORT that *restates* a parent invariant at the port surface MUST cite the parent invariant (the INV-S-PORT-5 / INV-S-PORT-6 / INV-S-PORT-7 / INV-S-PORT-10 / INV-S-PORT-11 / INV-S-PORT-13 entries all do this).

(f) §10 reconciliation list covers every adjacent primitive a reviewer might confuse SOS-04 with: `streamz-exec`, `sos-sim`, `sos-conformance`, FreeRTOS-Kernel, the DAA crates, `rlvgl`, `rtic`, `embassy`, probe-rs, the sibling SOS phases.

(g) §11 non-goal list is exhaustive for the SOS-04 v1 horizon. Items beyond v1 are not constrained here; the `SOS-04-B` amendment slot is named explicitly for the production-hardening surface.

### 12.2 Implementation-commit gates

A conforming `sos-m7-rust` implementation (a `cargo build --target thumbv7em-none-eabihf --release -p sos-m7-rust` plus a flash-and-run smoke) additionally requires:

(h) The crate compiles cleanly at the pinned MSRV (`1.75`, inherited from [SOS-02] PCDN-004) with `RUSTFLAGS="-C target-cpu=cortex-m7"` against `thumbv7em-none-eabihf`. No warnings; `#![deny(warnings)]` at the crate root.

(i) The crate `cargo build --features standalone-smoke -p sos-m7-rust` also compiles cleanly and embeds the static smoke vector.

(j) The firmware flashes successfully to the disco-analyzer board (operator-authorised per parent CLAUDE.md bench rule). `probe-rs run` returns 0 and the board enters the `wfi` idle loop.

(k) In Standalone mode (the `standalone-smoke` feature on), the firmware emits the boot-baseline trace record + one record per event in the static smoke vector + the done sentinel, all on the trace UART, at the baud rate ratified in PCDN-SOS-04-007. The host-side adapter (running on the operator's workstation) captures the records and they parse as valid JSONL per [SOS-02 §7].

(l) In Conformance mode (default), the firmware accepts the wrapped vector input over UART RX, runs the seed vector, emits passing trace records, emits the done sentinel, enters idle. The host-side adapter passes the records to `sos-conformance`, which exit-code-0s.

(m) The full SOS-03 seed suite (6 vectors at `conformance/vectors/smoke/0001-...0006-...`) passes against the firmware via `sos-conformance run --suite conformance/vectors/ --port ./target/release/sos-m7-rust-host-driver`. The port's `ConformanceLevel` achieves `SmokePass` (per [SOS-03 §5.2]).

(n) Aspirational (not required at v1 ratification but expected within one bench-iteration cycle): `FullSuitePass` against the full boundary + stress + regression suite. Achieving `FullSuitePassWithDiversity` is a future amendment goal.

(o) The firmware binary's `.text + .rodata` size at `-C opt-level=s` is reasonable (target: under 64 KiB; informative — not a normative gate, but informs SOS-06's codegen-size comparison).

(p) The PendSV handler body is reviewed by an embedded-Rust reviewer who has independently verified the EXC_RETURN[4] inspection logic against [SOS-00 §6.4] and against an ARMv7-M ARM excerpt (the reviewer drills into the ARM ARM for this verification — a permitted [INV-S1] / [INV-S-PORT-0] exception per "drilling in for explicit contract-growth moments").

## 13. Files cited

| Path | Role | Status |
|---|---|---|
| `streamz/submodules/SOS/rtos_kernel.scxml` | Canonical kernel spec; transliterated into the port firmware at build time | exists |
| `streamz/submodules/SOS/docs/REFERENCE.md` | Informative chart mirror | exists |
| `streamz/submodules/SOS/docs/concepts/SOS-00-CONCEPTS.md` | Parent concepts doc; §5 frozen enums, §6 M7 primitive bindings (THE contract), §9 invariants | exists (🟢 ratified 2026-05-19) |
| `streamz/submodules/SOS/docs/concepts/SOS-01-CONCEPTS.md` | Sibling phase; §5.3 ExternalEventName, §5.4 StateId | exists (🟢 ratified 2026-05-19) |
| `streamz/submodules/SOS/docs/concepts/SOS-02-CONCEPTS.md` | Sibling phase; §6.3 transliteration ABI, §7 trace format (on-device serialisation byte-equality target) | exists (🟢 ratified 2026-05-19) |
| `streamz/submodules/SOS/docs/concepts/SOS-03-CONCEPTS.md` | Sibling phase; §6 vector file format, §7.6 port-binary contract, §6.6 seed-vector list | exists (🟢 ratified 2026-05-19) |
| `streamz/submodules/SOS/docs/concepts/README.md` | Initiative index | exists |
| `streamz/submodules/SOS/docs/concepts/ERRATA.md` | Errata log | exists (skeleton) |
| `streamz/submodules/SOS/AGENTS.md` | Subrepo contributor guidance | exists |
| `streamz/submodules/SOS/CLAUDE.md` | Subrepo agent runbook | exists |
| `streamz/submodules/SOS/ports/m7-rust/sos-m7-rust/` | Firmware crate root (post-ratification) | does not yet exist |
| `streamz/submodules/SOS/ports/m7-rust/sos-m7-rust/Cargo.toml` | Firmware crate manifest (post-ratification) | does not yet exist |
| `streamz/submodules/SOS/ports/m7-rust/sos-m7-rust/memory.x` | Linker script (post-ratification) | does not yet exist |
| `streamz/submodules/SOS/ports/m7-rust/sos-m7-rust/src/main.rs` | Firmware entry point (post-ratification) | does not yet exist |
| `streamz/submodules/SOS/ports/m7-rust/sos-m7-rust/src/kernel.rs` | Transliterated chart bodies (post-ratification) | does not yet exist |
| `streamz/submodules/SOS/ports/m7-rust/sos-m7-rust/src/handlers.rs` | NVIC handler bodies (post-ratification) | does not yet exist |
| `streamz/submodules/SOS/ports/m7-rust/sos-m7-rust/src/transport.rs` | Trace transport (post-ratification) | does not yet exist |
| `streamz/submodules/SOS/ports/m7-rust/sos-m7-rust/src/trace.rs` | TraceRecord serializer (post-ratification) | does not yet exist |
| `streamz/submodules/SOS/ports/m7-rust/sos-m7-rust/src/disco_bsp.rs` | Board-specific bring-up (post-ratification) | does not yet exist |
| `streamz/submodules/SOS/ports/m7-rust/sos-m7-rust-host-driver/` | Host-side adapter crate (post-ratification) | does not yet exist |
| `streamz/submodules/disco-analyzer/` | Sibling subrepo; bench board substrate shared by flash-swap (INV-S-PORT-10) | exists; NOT a dependency (§4 negative listing, §10) |
| Parent CLAUDE.md, "Spec-Before-Code Planning Discipline" | Governing discipline | exists at parent root |
| Parent CLAUDE.md, "Bench-hardware authorization" | Governs operator-authorised flash + reset | exists at parent root |
| Parent memory `feedback_freertos_nvic_priority_0` | Source of [SOS-00] INV-S9 / INV-S-PORT-2 priority-0 prohibition | exists in user memory |
| Parent memory `feedback_no_speculative_board_reset` | Governs bench-flash authorisation for SOS-04 conformance runs | exists in user memory |
| Parent memory `project_daa_freertos_bringup` | Source of the `RUSTFLAGS="-C target-cpu=cortex-m7"` shell-override convention | exists in user memory |
| ARMv7-M Architecture Reference Manual (DDI 0403E.e) | M7 primitive contract source; consulted via [SOS-00 §6] curated subset | external; cited, not crawled |
| STM32H747xI Reference Manual (RM0399) | Bench substrate registers; consulted via [SOS-00 §6.6] curated subset and §6.9 of this doc | external; cited, not crawled |

## 14. Unblocks

SOS-04 ratification unblocks:

- **SOS-06 (codegen evaluation).** With a hand-written reference port (this doc + its implementation commit), SOS-06 has the *quality* baseline it needs alongside SOS-02's *behaviour* baseline. The codegen-vs-handwritten comparison answers "is codegen embedded-target-quality good enough?"; codegen-vs-`sos-sim` answers "is codegen behaviourally correct?". Both questions are needed; SOS-04 provides the first.

SOS-04 does NOT unblock SOS-05 directly — SOS-05 (M7 C port) is sibling-independent and can draft / land in parallel. SOS-05 MAY mirror SOS-04's bench-substrate choices (§6.9, PCDN-SOS-04-003 / -007 / -012 / -013) without amending SOS-04; SOS-05 SHOULD mirror them where reasonable for operator-muscle-memory reasons.

The implementation commit (`ports/m7-rust/sos-m7-rust/` skeleton + `memory.x` + minimal handlers + UART transport + transliterated boot block) is independently and immediately dispatchable in parallel with SOS-05 drafting (file-disjoint: SOS-04 implementation writes `ports/m7-rust/**`; SOS-05 drafting writes only `docs/concepts/SOS-05-CONCEPTS.md`).

## 15. Change log

### 2026-05-19 — Initial draft (Ira)

- Document drafted at `docs/concepts/SOS-04-CONCEPTS.md`. Sections §0–§14 populated.
- §5 introduces three phase-local enums: `TraceTransport` (Standards Action), `PortMode` (Specification Required), `StackPolicy` (Standards Action). [SOS-00 §5] enums re-exported by reference.
- §6 (architecture) is the load-bearing section: §6.1 crate layout under `ports/m7-rust/sos-m7-rust/`, §6.2 Conformance-mode vector-driven harness with newline-delimited UART framing, §6.3 static allocations naming `TCB_POOL` / `READY_POOL` / `SEM_POOL` / `QUEUE_POOL` / `KERNEL_STACK` / `TASK_STACKS` / `TRACE_*_BUF`, §6.4 PendSV body realisation in `asm!` per [SOS-00 §6.4], §6.5 SVC vestigial handler per [SOS-00 §5.3] / PCDN-SOS-00-002 → DirectCallBasepri, §6.6 SysTick handler issuing `sys.tick`, §6.7 critical-section BASEPRI wrappers per [SOS-00 §6.5], §6.8 boot path including PRIGROUP / NVIC priorities / SysTick LOAD, §6.9 disco-analyzer bench substrate notes.
- §7 (conformance-mode protocol) ratifies the host-side adapter as a separate workspace member, defines the done-sentinel filtering policy (adapter-filtered at v1 per PCDN-SOS-04-005).
- §9 introduces thirteen INV-S-PORT-N invariants, pairwise checked against [SOS-00 §9] / [SOS-02 §9] / [SOS-03 §9].
- §10 reconciliation explicitly disclaims `streamz-exec`, `sos-sim` (runtime), FreeRTOS, DAA crates, `rlvgl`, `rtic`, `embassy`.
- §11 non-goal list bounds v1 scope ruthlessly — REFERENCE not PRODUCTION (INV-S-PORT-8); production hardening is the `SOS-04-B` amendment surface.

PCDN list awaiting resolution:

- **PCDN-SOS-04-001 — Default trace transport.** Options: `Uart` / `Swo` / `SemihostingStdout`. **Recommendation: `Uart`.** Most universal: works without probe-rs attached; bidirectional (RX for vector ingress, TX for trace egress); the host-side adapter is a `/dev/tty.usbserial-*` consumer that exists in every embedded developer's toolbox. `Swo` is TX-only (cannot ingest vectors → Standalone-only). `SemihostingStdout` requires probe-rs attached and routes through the debugger (heavy CPU per call).

- **PCDN-SOS-04-002 — HAL choice.** Options: `stm32h7` PAC + hand-coded BSP / `stm32h7xx-hal`. **Recommendation: `stm32h7` PAC + hand-coded BSP.** Smaller surface: the port only needs RCC + GPIO + USART + maybe SCB / NVIC (the latter two via `cortex-m`); a HAL adds typestate abstractions that fight the NVIC discipline the port exists to expose. Fewer transitive deps. Hand-coded BSP is ~200 LOC for the v1 surface.

- **PCDN-SOS-04-003 — UART pin pair selection.** **USART1 confirmed 2026-05-19** via memalpha query against UM2411 §5.10 ("The serial interface USART1 is directly available as a Virtual COM port of a PC connected to STLINK-V3E USB connector CN2"). Pin pair recommendation stands: **USART1 / PA9 (TX) / PA10 (RX) / AF7** (the H7 default AF1 for USART1_TX/RX). The memalpha-indexed UM2411 §5.10 chunk names the USART instance but does not enumerate the GPIO pin pair; UM2411 §6 / §7 I/O assignment tables should be cross-checked at first bench round. If the actual VCP route uses a non-default-AF pair, this PCDN reopens as a §15 amendment carrying the corrected pins.

- **PCDN-SOS-04-004 — Vector ingress mode.** Options: UART RX streaming only / compiled-in `static` only / both. **Recommendation: both.** Compiled-in `static` for bench bring-up (no host-side adapter needed; smoke check during firmware iteration); UART RX for live harness use. Build-time feature gate (`--features standalone-smoke`) selects the static mode; default (no feature) selects UART RX.

- **PCDN-SOS-04-005 — Done sentinel.** Options: adapter-filtered (firmware emits sentinel; adapter filters) / harness-filtered (firmware emits sentinel; harness parses, recognises, drops). **Recommendation: adapter-filtered.** Avoids a [SOS-03 §15] amendment; the sentinel is a firmware-to-adapter-only protocol the harness never sees. INV-S-PORT-12 reflects this. If the user prefers harness-filtered, a [SOS-03 §15] amendment registers the sentinel as a permitted-but-not-required final line first.

- **PCDN-SOS-04-006 — Stack sizes.** Options: variable. **Recommendation: KERNEL_STACK_BYTES = 4 KiB (1024 words), TASK_STACK_BYTES = 2 KiB (512 words) per task, MAX_TASKS = 8 (matches chart default) → task-stack pool = 16 KiB total.** Numbers chosen so the entire static allocation fits comfortably in the H747's D1 AXI-SRAM (384 KiB at `0x2400_0000`) with room for `TRACE_*_BUF` (~32 KiB combined upper bound). DTCM (128 KiB at `0x2000_0000`) hosts `.bss` + `.data`. The numbers are conservatively oversized; tighten in a future amendment if size becomes a SOS-06 comparison concern.

- **PCDN-SOS-04-007 — UART baud rate.** Options: 115200 / 460800 / 921600 / 1 Mbps / 2 Mbps. **Recommendation: 921600.** High enough that the trace stream does not bottleneck the seed vectors (~1500 bytes/record × 7 records ≈ 10 KB/vector ≈ 90 ms at 921600); low enough to be reliable on the bench cable. The disco-analyzer's ST-Link VCP supports up to ~1 Mbps reliably; 921600 sits comfortably below.

- **PCDN-SOS-04-008 — JSON writer.** Options: `serde-json-core` / hand-rolled. **Recommendation: hand-rolled.** [SOS-02 §7.1] mandates exact field order; `serde-json-core` (and `serde_json` generally) honors `Serialize` derive field-declaration order, BUT version drift in the derive macro is a non-zero risk. Hand-rolled is ~300 LOC for the v1 TraceRecord shape and the byte-stability is enforceable by the port author at the writer level.

- **PCDN-SOS-04-009 — Workspace membership.** Options: firmware crate in workspace / outside workspace. **Recommendation: in the SOS subrepo's Cargo workspace.** Per [SOS-02] PCDN-005 → standalone workspace at subrepo root; the firmware crate `ports/m7-rust/sos-m7-rust/` joins as a workspace member. The crate's `Cargo.toml` declares `[lib].proc-macro = false`; the workspace's `Cargo.lock` is shared. **Caveat:** cross-target builds (host crates like `sos-sim` are `x86_64-unknown-linux-gnu`; the firmware is `thumbv7em-none-eabihf`) require explicit `--target` on the firmware crate. PCDN ratification documents the `cargo build --target ... -p sos-m7-rust` invocation as the canonical form.

- **PCDN-SOS-04-010 — `heapless` vs hand-rolled rings.** Options: `heapless` crate / hand-rolled ring buffers. **Recommendation: `heapless = "0.8"`.** Mature, well-tested, `no_std`, no allocator. The trace RX buffer's "is the JSON balanced yet?" detection is hand-rolled per §6.2.1; the ready / waiter / queue-buf rings inside the kernel state use `heapless::Vec<_, N>`.

- **PCDN-SOS-04-011 — Interior mutability.** Options: `MaybeUninit` / `UnsafeCell` / `SyncUnsafeCell`. **Recommendation: `UnsafeCell` (or its stabilised `SyncUnsafeCell` if MSRV permits — `SyncUnsafeCell` is unstable at 1.75; use a hand-rolled wrapper).** Trust marker at every access; uniform with the BASEPRI-raise discipline. The `MaybeUninit`-pattern alternative is more idiomatic in some Rust circles but its "is this initialised?" mental load distracts from the kernel-discipline reasoning.

- **PCDN-SOS-04-012 — FLASH bank.** Options: Bank 1 (`0x0800_0000`) / Bank 2 (`0x0810_0000`) / dual-bank with A/B images. **Recommendation: Bank 1 only.** 1 MiB is far in excess of v1 firmware needs. Dual-bank A/B is a production-hardening surface (firmware update) and is INV-S-PORT-8 out-of-scope.

- **PCDN-SOS-04-013 — Clock-tree configuration.** Options: vary. **Recommendation: HSE=25 MHz (board crystal); PLL1: M=5 (→ 5 MHz ref), N=160 (→ 800 MHz VCO), P=2 (→ 400 MHz CM7), Q=4, R=2; HCLK = 400 MHz; APB1/APB2/APB3/APB4 dividers = /2 (200 MHz peripheral); D1CPRE = /1; D2HPRE = /2; CM4 disabled.** Conservative; matches the H747's STMicro reference defaults; well-trodden by the disco-analyzer team's existing firmware. SystemCoreClock at 400 MHz makes SysTick LOAD = 399_999 at SOS_TICK_HZ = 1000 — see [SOS-00 §6.6].

- **PCDN-SOS-04-014 — Host-side adapter timeout.** Options: variable. **Recommendation: 30 seconds for any single vector.** Seed and boundary vectors execute in milliseconds; 30 s is two orders of magnitude headroom and surfaces a hung firmware fast. Timeout reports exit code 2 from the adapter (mirrors [SOS-03 §7.2] exit-code-2 for "vector failed"); the harness sees the failure and reports a `record_count_mismatch` diff.

- **PCDN-SOS-04-015 — Feature gates.** Options: many / one (`standalone-smoke`) / none. **Recommendation: one feature gate at v1: `standalone-smoke`.** Mirrors [SOS-02] PCDN-007's "no feature gates at v1" pattern (one feature gate is "minimal feature gating"). Avoids the build-matrix explosion the parent CLAUDE.md cautions against.

- **PCDN-SOS-04-016 — UART transport: interrupt-driven vs DMA.** Options: interrupt-driven byte-at-a-time / DMA per-record. **Recommendation: interrupt-driven at v1.** Simpler; sufficient for 921600 baud at seed-vector trace rates (~kHz). DMA is a future amendment if baud-rate or trace-rate pressure surfaces (e.g. stress vectors that emit thousands of records). At 921600 baud, ~100 µs per byte of overhead is negligible against the macrostep durations.

- **PCDN-SOS-04-017 — Serial-port crate (host-side adapter).** Options: `serialport` / `tokio-serial` / hand-rolled with `nix` + `termios`. **Recommendation: `serialport = "4"` (current 4.x).** Mature, cross-platform (Linux + macOS), blocking-by-default which matches the harness's synchronous I/O model. `tokio-serial` would pull in tokio at the host-side; unnecessary complexity. Hand-rolled with `nix` is ~150 LOC of platform-specific termios setup; `serialport` solves it once.

- **PCDN-SOS-04-018 — Per-module unit tests.** Options: `#[cfg(test)]` blocks compiled for host / separate `sos-m7-rust-tests` host crate / no per-module tests (rely on conformance suite). **Recommendation: separate `sos-m7-rust-tests` host crate.** The firmware crate's primary target is `thumbv7em-none-eabihf` and configuring `cargo test` to use a different host target within the same crate is fragile. A sibling host crate that pulls in the relevant firmware modules via path dependencies (and stubs out the `cortex-m` peripheral access) gives a clean separation. v1 tests focus on the hand-rolled JSON writer (PCDN-SOS-04-008) — the highest-risk path for byte-stability.

Acceptance checklist (§12) status at draft:

- (a) ⏸ PCDNs pending user ratification.
- (b) ✅ Glossary, source-of-truth map, frozen enums, architecture, conformance-mode protocol, invariants internally consistent.
- (c) ✅ §6 architecture covers every row of [SOS-00 §6]: §6.4 PendSV ↔ §6.4 ARM contract; §6.5 SVC ↔ §6.1 / §5.3 SyscallTransport; §6.6 SysTick ↔ §6.1 / §6.6 clock source; §6.7 critical sections ↔ §6.5 BASEPRI realisation; §6.3 stacks ↔ §6.3 stack model; §6.8 boot path ↔ §6.2 priority + §6.7 vector table + §6.6 SysTick LOAD.
- (d) ✅ §7 protocol consistent with [SOS-03 §7.6]; done-sentinel choice (adapter-filtered) reflected in §7.1 / §7.3 / INV-S-PORT-12 consistently.
- (e) ✅ INV-S-PORT-N pairwise checked against [SOS-00 §9] / [SOS-02 §9] / [SOS-03 §9]; reasserting invariants explicitly cite the parent invariant.
- (f) ✅ §10 reconciliation covers `streamz-exec`, `sos-sim`, `sos-conformance`, `cortex-m`, FreeRTOS, DAA, `rlvgl`, `rtic`, `embassy`, probe-rs.
- (g) ✅ Non-goal list bounded to v1 horizon; `SOS-04-B` amendment slot named for production-hardening.
- (h)–(p) ⏸ Implementation-commit gates by design — they ratify when the follow-up commit lands `ports/m7-rust/sos-m7-rust/` + `ports/m7-rust/sos-m7-rust-host-driver/` + a bench-run that conformance-passes the seed suite.

Status: 🟡 drafted; awaiting user PCDN walk-through and ratification before SOS-06 unblocks.

### 2026-05-19 — Pre-ratification: PCDN-003 resolved (Ira)

Item #2 of the wave-3 drift triage list resolved out-of-band 2026-05-19 via memalpha query against UM2411 §5.10: the VCP USART instance is **USART1**, matching this doc's recommendation. The pin pair PA9 (TX) / PA10 (RX) / AF7 is the H7 default AF1 for USART1_TX/RX and stands as the recommendation, subject to first-bench-round verification against UM2411 §6 / §7 I/O assignment tables. PCDN-SOS-04-003's entry above updated to record the resolution.

This is a pre-ratification update — the doc remains 🟡 drafted because the other 17 PCDNs still need user walk-through. PCDN-003 lands as resolved-in-draft so the bench-pin question doesn't re-surface during the eventual ratification walk.

### 2026-05-19 — Ratification (Ira)

User walked all 18 PCDNs and ratified the recommendations (PCDN-003 already resolved-in-draft above). SOS-04 status moves from 🟡 drafted to **🟢 ratified**. SOS-06 (codegen evaluation) is unblocked. The SOS-04 implementation commit (firmware crate `ports/m7-rust/sos-m7-rust/` + host-side adapter `ports/m7-rust/sos-m7-rust-host-driver/`) is independently dispatchable.

Consolidated resolutions:

- **PCDN-001:** `Uart` trace transport.
- **PCDN-002:** `stm32h7` PAC + hand-coded BSP.
- **PCDN-003:** USART1 / PA9 / PA10 / AF7 (memalpha-confirmed instance; pin pair bench-verify at first round).
- **PCDN-004:** Both vector ingress modes (UART RX + compiled-in static via `--features standalone-smoke`).
- **PCDN-005:** Adapter-filtered done sentinel.
- **PCDN-006:** KERNEL_STACK_BYTES = 4 KiB, TASK_STACK_BYTES = 2 KiB × MAX_TASKS = 8 (16 KiB pool). **User note: "OK for now but will want it configurable later" — flagged as future-amendment item FAM-04-A below.**
- **PCDN-007:** UART baud 921600.
- **PCDN-008:** Hand-rolled JSON writer. **User note: "with nose held" — the recommendation is accepted but the byte-stability risk is acknowledged; the SOS-04 implementation MUST cover the writer with `sos-m7-rust-tests` unit tests (PCDN-018 sibling crate) verifying byte-exact output for the boot baseline + every TraceRecord variant.**
- **PCDN-009:** Firmware crate joins the SOS subrepo's Cargo workspace.
- **PCDN-010:** `heapless = "0.8"` for ready/waiter/queue-buf rings; hand-rolled for the UART RX framing detector.
- **PCDN-011:** `UnsafeCell` with hand-rolled `unsafe impl Sync` wrappers (`SyncUnsafeCell` is unstable at MSRV 1.75).
- **PCDN-012:** Single FLASH image at Bank 1 (`0x0800_0000`). **User note: "this can be tweaked / abstracted later" — flagged as future-amendment item FAM-04-B below.**
- **PCDN-013:** Clock tree HSE=25 MHz / PLL1 M=5 N=160 P=2 / CM7=400 MHz / APBx=200 MHz / CM4 disabled.
- **PCDN-014:** Host-side adapter 30 s per-vector timeout (exit code 2 on timeout).
- **PCDN-015:** One feature gate (`standalone-smoke`).
- **PCDN-016:** Interrupt-driven UART transport at v1. **User note: "ACCEPTED with less optimism — FIFOs may help" — the recommendation acknowledges FIFO buffering as a deferred optimisation; the v1 implementation SHOULD use the USART's hardware FIFO if available (H7 USARTs support a 16-deep FIFO in FIFO mode), reducing ISR rate; if that is insufficient under stress-vector load, DMA promotion lands as FAM-04-C below.**
- **PCDN-017:** `serialport = "4"` for the host-side adapter.
- **PCDN-018:** Separate `sos-m7-rust-tests` host crate for unit tests of the JSON writer (PCDN-008 byte-stability concern lands here).

Future-amendment markers (FAM = "Future AMendment" — not blocking ratification, but registered so they aren't forgotten):

- **FAM-04-A — Make stack sizes configurable.** ✅ **DISCHARGED by SOS-04-A (ratified 2026-06-01).** Per PCDN-006 user-note. Today's hard-coded `KERNEL_STACK_BYTES` / `TASK_STACK_BYTES` become tunable. Resolved via the `port_config` surface in [`SOS-04-A-PORT-CONFIG-SURFACE.md`](./SOS-04-A-PORT-CONFIG-SURFACE.md): per-task `stack_words` + named `stack_region`, declared in a chart `<sos:task_config>` annotation and lowered to the SOS-04 Rust / SOS-05 C static allocations. (Original trigger — vector exceeds 2 KiB task stack, or SOS-06 codegen surfaces stack-size sensitivity — superseded by the DAA-08 consumer need for heterogeneous per-task stacks in a named region, REQ-SOS-4.)
- **FAM-04-B — Abstract the FLASH image layout.** Per PCDN-012 user-note. Today's "Bank 1 single image" hard-coded layout abstracts behind a build-time `LinkerProfile` (or similar) that future bank-swap firmware-update strategies can plug in. Triggers when production-hardening (currently INV-S-PORT-8 out-of-scope) ratifies as a SOS-04-B amendment.
- **FAM-04-C — UART transport hardware-FIFO + optional DMA promotion.** Per PCDN-016 user-note. v1 implementation USES the H7 USART hardware FIFO from the outset (16-deep RX / TX FIFOs in FIFO mode reduce ISR rate by ~16x); DMA-per-record lands as a later amendment only if FIFO + interrupt-driven still bottlenecks under stress-vector load. The FIFO usage is a v1-implementation decision (not a §15 amendment), but the DMA promotion is.

Acceptance checklist (§12) compliance at ratification:

- (a) ✅ All eighteen PCDNs resolved.
- (b)–(g) ✅ Already marked at draft time.
- (h)–(p) ⏸ Implementation-commit gates by design — ratify when the follow-up commit lands `ports/m7-rust/sos-m7-rust/` + `ports/m7-rust/sos-m7-rust-host-driver/` + the unit-test crate from PCDN-018 + a bench-run that conformance-passes the seed suite.

Unblocks: SOS-06 (codegen evaluation) directly. The SOS-04 implementation commit is independently dispatchable in parallel with SOS-05 PCDN walk + SOS-06 drafting + the remaining `sos-sim` implementation work — all file-disjoint.

### 2026-05-19 — Amendment 001: narrow §6.3 Tcb / Sem / Queue field types to match the sim crate (Ira)

The SOS-04 implementation-skeleton agent (2026-05-19) flagged a type drift between §6.3's `TCB_POOL` row (`Tcb { id: i32, prio: i32, state: u8, deadline: i64, blk_obj: i32, msg: Msg, psp: u32 }`) and the `sos-sim` crate's `Tcb` (`id: TaskId=i16, prio: u8, state: TaskState, deadline: i64, blk_obj: i16, msg: Msg`). The skeleton followed the sim crate's narrower types because [SOS-02 §7.2] is the canonical owner of the trace wire format and the on-device `Tcb` must serialise byte-identically to `sos-sim`'s `Tcb` for [SOS-03 INV-S-CONF-1] (byte-equal traces between conforming ports).

**Resolution: §6.3 narrowed to match the sim crate.** The on-device `Tcb` is `{ id: i16, prio: u8, state: TaskState (u8-discriminant), deadline: i64, blk_obj: i16, msg: Msg }`; `READY_POOL` uses `heapless::Vec<i16, MAX_TASKS>`; `SEM_POOL` records carry `count: u32, max: u32, waiters: heapless::Vec<i16, MAX_TASKS>`; `QUEUE_POOL` records carry `cap: u32, count: u32, buf: heapless::Vec<i64, Q_DEPTH>, sendw/recvw: heapless::Vec<i16, MAX_TASKS>`. The PSP backing-store reference (`psp: u32`) belongs in a parallel side table, NOT inside `Tcb` — placing it inside `Tcb` would drift the serialised shape from `sos-sim`'s, breaking trace byte-equality. The side-table approach is captured as FAM-04-D below.

The skeleton implementation at `ports/m7-rust/sos-m7-rust/src/kernel.rs` is already correct under the narrowed types — no rework needed. This amendment brings the spec into alignment with the as-built implementation.

### 2026-05-19 — Amendment 002: register FAM-04-D for PSP backing store side-table (Ira)

The PSP backing store for inactive tasks (the saved-frame area where R4-R11 + S16-S31 live while the task is not on PSP) MUST live somewhere; Amendment 001 removed `psp: u32` from `Tcb` to preserve the trace-format byte-equality contract. The replacement structure is a parallel side table.

Registered as future-amendment marker **FAM-04-D**: Implementation phase 3 lands a `static mut TASK_SAVED_FRAMES: [MaybeUninit<SavedFrame>; MAX_TASKS]` parallel array in `src/kernel.rs`, indexed by `TaskId`. `SavedFrame` carries the R4-R11 (+ optional S16-S31) tuple PendSV needs at context-switch time. The PSP value itself (top of the saved frame) lives in a `static mut TASK_PSPS: [u32; MAX_TASKS]` companion table. Neither is observable in the trace (per [SOS-00 §7.2]); both are pure port-side state.

Triggers at SOS-04 implementation phase 3 (PendSV body landing). No spec amendment beyond this marker; the layout choice is implementation-side per [SOS-04 §0]'s authority split.

### 2026-05-19 — Amendment 003: cortex-m 0.7 API surface clarification in §6.8 (Ira)

The wave-5 phase-2 implementation agent found that §6.8's named `cortex-m` peripheral calls (`SCB::set_priority_grouping`, `NVIC::steal`) do not exist in the v0.7.x line pinned by [SOS-04 §4]. Direct AIRCR register write achieves PRIGROUP=0; `cortex_m::Peripherals::steal()` returns a fresh `Peripherals` struct from which `cp.NVIC.set_priority(...)` is reachable.

§6.8's "Set NVIC priority grouping to PRIGROUP=0 via `cortex_m::peripheral::SCB::set_priority_grouping(0)`" prose is **illustrative, not normative**. The load-bearing requirement is the ratified contract:

1. NVIC priority grouping MUST be configured to PRIGROUP=0 (all-preempt) per [SOS-00 §6.2] / [SOS-04 INV-S-PORT-2].
2. PendSV MUST land at NVIC priority value 0xE0.
3. SysTick MUST land at NVIC priority value 0xC0.
4. `*_from_isr` IRQ sources MUST land at NVIC priority value 0xA0.

How the port code achieves those is implementation-side. The wave-5 phase-2 implementation:

- PRIGROUP=0 via `SCB->AIRCR = (0x05FA << 16) | (0 << 8)` direct write.
- Priorities via `cortex_m::Peripherals::steal()` → `cp.NVIC.set_priority(...)` calls.

Both correct under the ratified contract. Future cortex-m crate major-version bumps may restore the named API surface; if so, the port may migrate without spec amendment.

### 2026-05-19 — Amendment 004: align §6.4 PendSV asm prose with FAM-04-D side-table (Ira)

§6.4's PendSV asm sketch prose describes saving R4-R11 (+ S16-S31 when EXC_RETURN[4]==0) via `stmdb r0!, {r4-r11}` on the outgoing task's PSP stack. Amendment 002 (FAM-04-D) ratified that the saved callee-frame lives in a parallel side table at `TASK_SAVED_FRAMES: [SavedFrame; MAX_TASKS]` (one entry per TaskId; each entry carries `regs[8]` + `fp_regs[16]` + `had_fp_frame: bool`), and that `TASK_PSPS: [u32; MAX_TASKS]` holds the PSP value at suspend-time. The §6.4 prose contradicts this.

§6.4 amended: the PendSV body saves the callee-frame to `TASK_SAVED_FRAMES[OUTGOING_TID]` (NOT onto PSP) and reads `TASK_PSPS[CURRENT_TID]` for the incoming task's PSP value. The hardware-pushed R0-R3/R12/LR/PC/xPSR (and optional FP frame) stay on PSP where the exception entry pushed them; the OS-saved R4-R11 (+ optional S16-S31) goes in the side table. This preserves trace byte-equality with sos-sim's `Tcb` shape per Amendment 001 (no `psp` field inside `Tcb` to drift the serialised TCB record).

The wave-6 implementation at `ports/m7-rust/sos-m7-rust/src/handlers.rs` (PendSV body) and `src/kernel.rs` (`TASK_SAVED_FRAMES`, `TASK_PSPS`, `TASK_STACKS` declarations) is already correct under the side-table design. This amendment brings the §6.4 prose into alignment with the as-built ratified implementation.

For the explicit asm shape, see `handlers.rs::PendSV()` at the wave-6 SHA. Key sequence:

1. Read `OUTGOING_TID` from `kernel::OUTGOING_TID`. If `< 0` (boot path; no outgoing task yet) skip the save block.
2. `mrs r0, psp` — read the outgoing task's PSP. Stash in `TASK_PSPS[OUTGOING_TID]`.
3. Compute `TASK_SAVED_FRAMES[OUTGOING_TID]` address via base + (TID × sizeof(SavedFrame)).
4. `stm` R4-R11 into the side-table slot's `regs` field.
5. `tst lr, #0x10` — if EXC_RETURN[4]==0 (FP frame), `vstm` S16-S31 into `fp_regs` and set `had_fp_frame = 1`. Otherwise set `had_fp_frame = 0`.
6. Read `CURRENT_TID`. Load `TASK_PSPS[CURRENT_TID]` into r0. Compute `TASK_SAVED_FRAMES[CURRENT_TID]` address.
7. `ldm` R4-R11 from the side-table slot.
8. Check `had_fp_frame`. If true, `vldm` S16-S31 and set EXC_RETURN to `0xFFFFFFED` (PSP/extended); else `0xFFFFFFFD` (PSP/standard).
9. `msr psp, r0; dsb; isb; bx lr` — return from exception.

No code change is required by this amendment — it's a doc-text correction. Implementation-side reviewers continue to use `handlers.rs` as the canonical PendSV implementation.

### 2026-05-19 — Amendment 005: ratify firmware-side range-check strictness as intentional (Ira)

The wave-7 firmware-side scripts implementation (`ports/m7-rust/sos-m7-rust/src/scripts.rs`) added range-check guards that neither the sim (`sim/sos-sim/src/scripts.rs`) nor the chart (`rtos_kernel.scxml` `<script>` blocks) carry:

| Path | Firmware guard | Sim / chart behaviour |
|---|---|---|
| `task.create` with `id < 0` or `id >= MAX_TASKS` | Returns `RC_INVAL` (firmware `ScriptError::InvalidTaskId`) | Chart: `tcb[d.id]` is OOB-read into `undefined` then `undefined.state = ST_DORMANT` is JS-undefined-behavior; sim adds an `RC_INVAL` short-circuit on `id >= dm.tcb.len()`. |
| `queue.create` with `cap > Q_DEPTH` | Returns `RC_INVAL` (firmware `ScriptError::BadState`) | Chart + sim: silently set `q.cap = d.cap` without bound check; sim's heap-backed `Vec<i64>` accepts any cap; firmware's `heapless::Vec<i64, Q_DEPTH>` cannot. |
| `sem.take` / `queue.send` / `queue.receive` blocking branch with `current == -1` | Returns `ScriptError::BadState` (firmware) | Chart: `tcb[-1].state = ST_BLK_SEM` is JS UB; sim returns `SimError::Runtime("sem.take with no current task")`. |

**Resolution: firmware-side strictness is intentional and ratified.** The chart's latent UB is NOT part of the conformance contract. Port behaviour on UB-equivalent inputs (out-of-range TaskId, oversized queue cap, blocking-from-no-task-context) is permitted to differ from sim — the conformance vector suite at [SOS-03] does NOT exercise these edge cases, and a future vector that DOES exercise them must explicitly opt into either (a) testing only well-formed inputs, or (b) ratifying a port-equivalence relaxation in the §15 of the vector-adding amendment.

Rationale: heapless-backed fixed-capacity collections cannot tolerate UB the way ECMAScript or sim's heap-backed `Vec` can. Adding the guards in firmware is a safety property the spec ratifies as the canonical port behaviour for UB-equivalent inputs. Future ports (SOS-05 C, SOS-06 codegen) SHOULD adopt the same guards.

**Forward plan**: SOS-03 §15 (or a future SOS-03 amendment) MAY add a "robustness" vector category exercising these edge cases, expecting the firmware-side `RC_INVAL` response and treating sim's UB-response as a sim bug to be fixed. Not landing in this amendment; named for the future amendment.

Cross-reference: wave-7 firmware scripts agent's report flagged these strictness additions as worth user review; this amendment is the user's "yes, intentional" ratification.

### 2026-05-21 — Amendment 006: ratify tick_hz validation in vector-header check (Ira)

The wave-8 macrostep dispatch loop in `ports/m7-rust/sos-m7-rust/src/main.rs` validates the incoming vector's `VectorHeader` against the firmware's compile-time `MAX_*` / `Q_DEPTH` constants — a mismatch emits the done sentinel and parks. The `tick_hz` field was parsed but not validated. The firmware's SysTick is locked to 1000 Hz at boot (PCDN-013 + PCDN-008); a vector that claims a different `tick_hz` would still trace correctly for the chart's logical-counter semantics (tick_count is a logical, not wall-clock, counter), but the silent-acceptance allows a class of vector authorship mistakes to go undetected.

**Resolution: extend the vector-header validation to include `tick_hz`.** A vector whose header's `tick_hz` differs from the firmware's compile-time tick rate raises the same sentinel-and-park response as other dimension mismatches. Pre-existing main.rs §6.2 dispatch-loop body amended to add the tick_hz arm.

Rationale: the conformance contract pins all six VectorHeader fields to compile-time kernel constants; any mismatch indicates either (a) the vector was authored against a different kernel configuration, (b) the firmware was built with the wrong constants, or (c) the harness shipped a corrupted header. None are silent-tolerable; sentinel-and-park is the correct response in all three cases. No code change to the firmware-side tick rate (SysTick LOAD stays 399_999 per PCDN-013); only the validation check changes.

A new `pub const SOS_TICK_HZ: u32 = 1000;` lands in `kernel.rs` (if not already there) so main.rs has a canonical reference for the validation. Cross-references SOS-00 §6.6 (SysTick clock source) and PCDN-013 (clock tree).

### 2026-05-21 — Amendment 007: ratify silent-continue on ScriptError in dispatch loop (Ira)

The wave-8 macrostep dispatch loop in `main.rs` swallows `scripts::dispatch_event` errors via `let _ = scripts::dispatch_event(dm, &event);`. A malformed event (e.g. `task.create` with `id >= MAX_TASKS`, `queue.send` from no-task-context) produces a partial-mutation trace record and the loop continues to the next event.

§6.2.1 prose offered two policies — "v1 may simply emit the done sentinel and halt" OR continue past the error. The wave-8 implementation chose silent-continue.

**Resolution: silent-continue is ratified as v1 behaviour.** Rationale: the conformance contract (SOS-03 INV-S-CONF-1) requires byte-equal traces between conforming ports for any vector in the suite. A malformed event in a SOS-03 vector would (a) never appear in the seed suite (Amendment 005 ratifies firmware-side strictness as intentional; firmware emits `RC_INVAL` while sim emits whatever JS-UB-equivalent happens, and §15 Amendment 005 declined to add UB-equivalent vectors to the suite), (b) if added in a future "robustness" vector class, would expect the firmware's `RC_INVAL` trace and treat sim's UB-response as a sim bug. The silent-continue policy keeps the firmware running through the rest of the vector so the harness sees the full trace shape; sentinel-and-park would cut off remaining vector events, losing information.

If a future amendment ratifies a robustness vector class with explicit error-termination semantics, the dispatch loop SHOULD migrate to sentinel-and-park on the corresponding ScriptError variants and stay silent-continue on others.

Cross-reference: SOS-03 (conformance contract); SOS-04 Amendment 005 (firmware-strictness intentional).

### 2026-05-21 — Amendment 008: align §6.6 SysTick prose with wave-6 handler reality (Ira)

§6.6 originally described the SysTick body as also calling `trace::emit_post_tick_record()` and using a `BOOT_DONE: AtomicBool` sentinel to gate the emission until `kernel::init()` completed. The wave-6 implementation took a different (simpler) approach: SysTick mutates only `tick_count` / `pend_ticks` in `KERNEL_STATE` (guarded by `if let Some(dm) = (&mut *KERNEL_STATE.0.get()).as_mut()`), and the trace emission happens exclusively in the wave-8 main.rs macrostep dispatch loop after `dispatch_event` returns.

**Resolution: §6.6 prose amended to match the wave-6/8 reality.** The trace-emit responsibility lives in the dispatch loop in Conformance mode (`PortMode::Conformance`); SysTick is purely a state-mutator and a PendSV-trigger. The `BOOT_DONE` sentinel is unneeded — the `as_mut()` test on `KERNEL_STATE`'s `Option<Datamodel>` provides the bootstrap-safety property the sentinel was meant to ratify. ISR-driven trace emission is reserved for `PortMode::Standalone` (per §5.2), which is not on the v1 build path (the `--features standalone-smoke` gate is declared in Cargo.toml per PCDN-015 but not wired into main.rs at v1).

No code change required by this amendment. The wave-6 handlers.rs SysTick body and the wave-8 main.rs dispatch loop are the canonical implementations under the amended §6.6 prose.

Cross-reference: wave-6 handlers.rs SysTick body; wave-8 main.rs dispatch loop; PCDN-005 (adapter-filtered done sentinel — adjacent topic).

### 2026-05-21 — Amendment 009: ratify event-before-data field order in json_parser (Ira)

The wave-8 `ports/m7-rust/sos-m7-rust/src/json_parser.rs` requires the `event` field (the dotted-name EventName string) to appear BEFORE the `data` field within an event object. This is necessary because the data parser switches on the EventName variant to determine which `EventData` shape to populate — without knowing `event` first, the parser would need a two-pass approach (record byte ranges of `data`, defer parsing until closing `}`, then dispatch). Two-pass adds parser-state complexity and a third byte-buffer; the wave-8 single-pass parser explicitly does not implement this.

**Resolution: event-before-data field order is ratified as the SOS-04 §6.2.1 conformance contract.** The harness-side `sim/sos-conformance/src/port.rs` already emits events in this order (the `Event` struct's serde-derive field declaration is `event`, then `data`, then `from_tid`); no harness change needed. A future vector-authoring tool that emits fields in any other order would be non-conforming and the firmware would surface `ParseError::BadEventShape`.

Rationale: single-pass parsing is meaningful for a 16-byte-RAM-budget no_std target. Two-pass parsing would (a) require buffering the `data` value separately, (b) introduce a second EventData parser entry point, and (c) double the depth-tracking complexity. The complexity tradeoff is not justified by RFC-8259-pure field-order flexibility when the only producer that matters is the SOS-managed harness.

§6.2.1 prose amended to ratify the field-order requirement; SOS-03 §6.2 vector file format ratifies that vector-authoring tools MUST emit `event` before `data`. The sos-sim's serde-derive happens to satisfy this naturally (the `Event` struct's field declaration order is preserved by serde_json's default Serializer), so the existing seed-vector fixtures are already conformant.

If a future amendment introduces a vector format with `data`-before-`event` (perhaps as a CBOR migration or a YAML alternate), it ratifies a parser update at that time.

Cross-reference: SOS-03 §6.2 (vector file format); wave-8 json_parser.rs.

### 2026-05-21 — Amendment 010: first-bench findings + boot-baseline alignment (Ira)

First bench round attempted 2026-05-21 against the STM32H747I-DISCO board over probe-rs (STLINK V3E, VCP at `/dev/cu.usbmodem1302`). The pinned `arm-none-eabi-gcc 13.2.Rel1` toolchain was installed at `~/.local/opt/` and both ports (sos-m7-rust + sos-m7-c) build cleanly under it. Two real items surfaced.

**(a) Chip-side firmware verified working end-to-end.** Probe-rs reads against the running firmware confirmed every layer of the bring-up: PLL1 locked at 400 MHz, APB2 = 200 MHz (D2CFGR=0 / D2PPRE2=/1), GPIOA correctly programmed for PA9/PA10 (MODER=0xabebffff, AFRH=0x00000770, OSPEEDR=0x0c280000 — AF7 high-speed), USART1 fully configured (CR1=0x2000002d with UE+TE+RE+RXNEIE+FIFOEN, CR2=0, BRR=0x6C8 at 115200), TC/TXE/IDLE flags consistent with a healthy transmitter, TDR reads cycle through firmware-written boot-baseline bytes (read as 'c' then later 'n' — the firmware is actively rotating through the JSON record), SysTick CVR ticks continuously. PendSV=0xE0, SysTick=0xC0, PRIGROUP=0 all match §6.2. NVIC USART1=0xA0 programmed. The ELF (37 KB .text) flashes cleanly via `probe-rs download`.

**(b) Chip-to-host UART transit is intermittent.** Across multiple bench rounds (baud 9600, 115200, 460800, 921600; both `/dev/tty.usbmodem*` and `/dev/cu.usbmodem*`; via raw `cat`, via the Rust `serialport`-backed adapter, via `stty`-preconfigured pipes), zero bytes were captured EXCEPT for one transient 40-byte capture mid-experiment (`{"after_input_idx":-1,"current":-1,"tick`) during an unrelated USART3 reconfig probe. The chip is transmitting (per (a) and the FE bit firing when host sends mismatched-baud bytes — proving the bidirectional UART hardware path is alive). But STLINK V3's VCP forwarding of those bytes to the host CDC-ACM USB endpoint is not delivering reliably.

Leading hypothesis (unproven): the STLINK V3E firmware on this specific disco-analyzer board may be in a configuration where the VCP doesn't forward USART1 traffic — possibly because the board was previously used for SWO-based audio-trace work (DAA family) and the STLINK firmware was reconfigured to prioritize SWO over USART1 forwarding. Verifying or correcting this requires ST's STLinkUpgrade or ST-Link Utility tools, which aren't part of the probe-rs surface.

Alternative hypotheses considered and partially-ruled-out:

- Wrong USART instance (PA9/PA10 vs PB6/PB7 vs PD8/PD9): rlvgl's reference firmware at `ops/packer/submodules/rlvgl/examples/stm32h747i-disco/src/main.rs:1982-1999` uses PA9/PA10 AF7 BRR=868 at the equivalent clock, matching SOS-04's choice. memalpha-indexed UM2411 §5.10 confirms "USART1 is directly available as VCP". So PA9/PA10 is the correct wire.
- Baud rate mismatch: chip BRR=0x6C8 produces ~115200 at confirmed APB2=200 MHz; host serialport-rs explicitly programs 115200. Direct probe-rs writes to USART1 TDR at the working baud still don't appear at the host.
- macOS DCD wait on `/dev/tty.usbmodem*`: switched to `/dev/cu.usbmodem*` (no-DCD-wait variant) — same result.
- STLINK SWD activity blocks VCP: tested with explicit settling delays between probe-rs commands — no consistent improvement.

**(c) Boot-baseline `current` field — alignment fix landed.** Independent of (b), the captured 40-byte trace exposed a real sim/firmware divergence: the firmware's `kernel::init()` left `current = -1` (idle in `Ready` state, on `ready[0]`), while `sim::Datamodel::new` promotes idle to `Running` and assigns `current = 0` at construction (mirroring the chart's `<boot>` `pick_next()` call). The firmware emitted `"current":-1` in the boot baseline JSON; sim's vector-0001 `expected_trace` carries `"current":0`. Even with a working chip-to-host UART path, conformance would have failed at the boot baseline diff.

**Resolution for (c) — landed 2026-05-21.** Both ports' kernel init updated:

- `ports/m7-rust/sos-m7-rust/src/kernel.rs` — `current: 0` in the `Datamodel { ... }` literal, `dm.tcb[0].state = TaskState::Running`, `ready[]` left empty (pick_next semantics absorbed into init's static result).
- `ports/m7-c/sos-m7-c/src/kernel.c` — same shape: `g_dm.current = 0`, `g_dm.tcb[0].state = SOS_ST_RUNNING`, `g_dm.ready_count[0] = 0`.

Both builds re-verified clean. Host-side test suites unaffected (the sim's `Datamodel::new` already matched the new firmware shape; conformance vectors continue to pass).

**Baud-rate change for first-bench (informative).** Wave-8 PCDN-SOS-04-007 ratified 921600; this amendment notes that the wave-10 first-bench attempt re-flashed firmware at 115200 to match the rlvgl reference's baud convention. This is bench-iteration scaffolding, not a ratified spec change — PCDN-SOS-04-007 stays at 921600 as the v1 target. The firmware's `USART1_BAUD` const may need a follow-up amendment to ratify 115200 as the permanent v1 baud once end-to-end is proven; that's a separate §15 entry to land after (b) resolves.

**Open items for next bench round (EOQ format per parent CLAUDE.md errata convention):**

- **EOQ-001-AMENDMENT-010**: Confirm STLINK V3E firmware mode on the disco-analyzer board. Use ST-Link Utility or STLinkUpgrade.exe to read the STLINK firmware version and verify VCP-forwards-USART1 is enabled. If the board's STLINK is configured for SWO-only or a non-VCP mode, that's the bench-side fix.
- **EOQ-002-AMENDMENT-010**: Run a known-working firmware (e.g. cached rlvgl `target/thumbv7em-none-eabihf/release/rlvgl-stm32h747i-disco`) on this same board to validate VCP path independently of SOS firmware. If rlvgl's USART1 traffic ALSO doesn't reach the host, the issue is bench-board (STLINK firmware mode); if rlvgl DOES reach the host, the issue is SOS firmware-specific (perhaps timing of TDR writes vs FIFO drain, or a missing CR3 bit, or USART1 ker-clock select differing from rlvgl's setup).
- **EOQ-003-AMENDMENT-010**: Investigate whether the STLINK V3E VCP needs explicit USB CDC SET_LINE_CODING handshake beyond what macOS termios does. Rust `serialport-rs` calls `tcsetattr` which should propagate to the USB driver, but a quirk in STLINK's CDC implementation might require host-side delay between open and first read.

Bench session 2026-05-21 paused after ~2 hours of diagnosis. Re-attempt unblocks once any of EOQ-001/002/003 resolves.

Cross-references: wave-9 toolchain install (Amendment 003 of SOS-05 §15 — the parallel C-port libc substitution rides the same toolchain pin); SOS-03 vector 0001 (the boot-baseline divergence's first detection point); rlvgl-platform `hwcore/regs/usart.rs:54` ("USART1 is the ST-LINK VCP" confirmation cross-cite).

### 2026-05-21 — Amendment 011: second bench session — VCP works, EOQ-002 resolved (Ira)

Second bench session 2026-05-21 followed EOQ-002 (flash rlvgl, validate VCP independently). Findings:

**VCP works — root cause of first session's silence was BAUD MISMATCH.**

Flashed the cached rlvgl debug binary at `ops/packer/submodules/rlvgl/target/thumbv7em-none-eabihf/debug/rlvgl-stm32h747i-disco` (FreeRTOS + audio + dma2d + splash + desktop). Probe-rs reads on the running rlvgl firmware:

- USART1 CR1 = 0x2000002d (same TE+RE+UE+RXNEIE+FIFOEN config as SOS)
- USART1 BRR = 0x00000364 (= 868)
- D2CFGR = 0x00000440 → D2PPRE2 = /2 → **rlvgl APB2 = HCLK/2 = 100 MHz**
- BRR 868 at APB2 100 MHz = 115,207 baud ≈ 115200

Compare to SOS-04 first-session config:
- USART1 BRR = 0x6C8 (= 1736)
- D2CFGR = 0 → D2PPRE2 = /1 → **SOS APB2 = HCLK = 200 MHz**
- BRR 1736 at APB2 200 MHz = 115,207 baud ≈ 115200

Both ports send at the same ~115200 baud, but via different clock-tree configurations. The CLAUDE.md comment in `rlvgl/examples/stm32h747i-disco/src/main.rs:1996` ("BRR=868 (100 MHz / 115200)") is therefore correct for rlvgl's clock-tree choice.

**Sequence that proved VCP works:**
1. Flashed rlvgl, reset, host opened `/dev/cu.usbmodem1302` at 115200 via `sos-m7-rust-host-driver` with stdin `?\n` (the rlvgl playit boot-status query).
2. Captured **4 bytes**: `4f 4b 0d 0a` = `OK\r\n` — rlvgl playit's `?` response.

This proves the chip→host USB CDC ACM path works at 115200. EOQ-001 / EOQ-003 effectively resolved by this success (STLINK V3E firmware mode is fine, macOS termios + serialport-rs handle SET_LINE_CODING correctly).

**First-session silence diagnosis:** in retrospect, the first session listened at 921600 (matching SOS-04's PCDN-007 of 921600 baud) when the SOS firmware had been re-flashed to 115200, but the host-side `cat`/raw listens were never synchronised to 115200. The Rust adapter calls explicitly used `--baud 115200`, but the adapter's stdout-vs-done-sentinel logic exited timeout before the host could capture the brief boot baseline emission. The 40-byte capture during the USART3 reconfig experiment happened because the experiment's listen window happened to extend across a reset + boot baseline emission at the correct 115200 baud.

**SOS-04 boot baseline now reads correctly on bench (Amendment 010 fix verified):** flashed the rebuilt SOS firmware, captured the boot baseline at 115200, got `{"after_input_idx":-1,"current":0,"tick_` — `"current":0` confirms the wave-10 kernel boot baseline fix landed correctly. Idle is RUNNING at boot, matching sim's `Datamodel::new`.

**Remaining issue: SOS firmware doesn't respond to vector input via UART.**

End-to-end conformance still fails. Sequence:
1. SOS firmware boots; emits ~700-byte boot baseline at USART1 TX
2. Host adapter opens VCP; sends wrapped vector JSON `{"config":..., "input":[...]}` via USART1 RX
3. Adapter waits for done sentinel
4. Adapter times out at 12s with 0 bytes captured from chip

Probe-rs post-mortem on the chip:
- NVIC ISER1 = 0x00000020 (USART1 IRQ #37 unmasked) ✓
- NVIC IABR1 = 0 (no IRQ currently servicing)
- NVIC IPR9 = 0x0000a000 (USART1 priority = 0xA0) ✓
- USART1 ISR = 0x0ce010f0 → TC=1, TXE=1, RXNE=1 (bytes in FIFO after host send)
- USART1 TDR = different bytes per read ('A' then 'i' after reset+vector) — firmware IS continuing to write but only the boot baseline content

Hypothesis: the firmware receives vector bytes via USART1 IRQ (RXNE assertion confirms reception) but either (a) the firmware's `VectorStream::try_step` rejects the wrapped form `{"config":..., "input":[...]}` despite wave-7 D's name-tolerance landing, or (b) the firmware's dispatch path mutates state but the trace-emit-back-via-write_byte doesn't actually push bytes (some firmware-state issue not visible from probe-rs).

In-process testing (`sos-conformance run` with default `InProcessPort`) of the SAME firmware code-equivalent (`sos-sim` with the same script bodies that the firmware's `scripts.rs` mirrors) passes 6/6 vectors. So the kernel logic + scripts + parser + writer work in isolation. The bench-only failure is in the UART-IRQ → parser → dispatch → write_byte → UART-TX path's wiring.

**EOQ status after second session:**
- ✅ **EOQ-001-AMENDMENT-010**: VCP forwarding mode is fine on this board's STLINK V3E. Not the issue.
- ✅ **EOQ-002-AMENDMENT-010**: rlvgl playit works on this board at 115200. VCP path validated. NOT the bench-side issue.
- ✅ **EOQ-003-AMENDMENT-010**: macOS termios + Rust serialport-rs handle SET_LINE_CODING correctly. NOT the host-side issue.
- 🔴 **NEW EOQ-004-AMENDMENT-011**: Why does the SOS firmware not emit trace records via UART when vector input is delivered? Hypotheses to test next session:
  - (a) Add UART tracing (or RTT debug breadcrumbs) inside the firmware's macrostep dispatch loop to confirm the parser is seeing complete events.
  - (b) Run the json_parser unit tests' equivalent input through the firmware on bench (currently the parser is only host-tested via `sos-m7-rust-tests`).
  - (c) Verify the firmware's `transport::write_byte` blocking-poll-on-TXE actually returns rather than hangs forever (TXE was set during diagnosis, so write_byte SHOULD complete — but maybe a TXFNF vs TXE confusion in FIFO mode).
  - (d) Add a chip-side LED toggle in the dispatch loop's `Event` arm to visually confirm dispatch is reached.

Bench session 2026-05-21 closes with VCP-path-validated, boot-baseline-aligned, and the firmware UART-vector-response path identified as the remaining work surface. Re-flashing the board for DAA audio work is safe at any time; no SOS state persists.

Cross-references: SOS-04 Amendment 010 (first-session findings); rlvgl-platform `examples/stm32h747i-disco/src/main.rs:1996` (BRR=868 + APB2=100MHz convention); SOS-04 §15 PCDN-007 (921600 baud — superseded for v1 first-bench at 115200 per Amendment 010's `USART1_BAUD` change).

### 2026-05-21 — Amendment 012: EOQ-004 investigation — three real firmware bugs found + bench round-trip working (Ira)

Third bench session 2026-05-21 (continuation of Amendment 011) drilled into EOQ-004 with probe-rs-readable diagnostic counters in firmware DTCM (`DIAG_LOOP_COUNT`, `DIAG_ISR_COUNT`, `DIAG_PARSE_KIND`, `DIAG_BYTES_RX`, `DIAG_BYTES_TX`). The diagnostic-counter pattern proved highly productive — each counter narrowed which firmware stage was reaching/failing.

**Three real firmware bugs surfaced and fixed:**

**(a) Unconditional PendSV pend on every SysTick (`handlers.rs:237`).** The wave-6 SysTick handler called `cortex_m::peripheral::SCB::set_pendsv()` unconditionally per the in-code TODO "phase 3b gates this on `dm.resched`". This pended PendSV after every 1 ms SysTick. PendSV's wave-6 naked-asm body reads `TASK_PSPS[CURRENT_TID]` into PSP and returns to thread+PSP — but at boot `TASK_PSPS[0]` (idle) is uninitialised because the firmware never enters real task code. Net: SysTick → set_pendsv → PendSV tail-chains → loads null PSP → `bx lr` returns to thread+PSP with garbage PC → INVSTATE UsageFault → escalates to HardFault.

Diagnostic chain: `DIAG_LOOP_COUNT = 0` (main loop never reached), `DIAG_BYTES_TX = 40` (boot baseline emit interrupted mid-record), PC at HardFault_+4 infinite branch, CFSR.UsageFault.INVSTATE = 1, EXC_RETURN = 0xFFFFFFFD (thread+PSP), saved frame's xPSR.T = 0 (Thumb bit cleared), saved PC in DTCM trace_buf bytes.

**Fix (landed):** removed the unconditional `set_pendsv()` from `handlers.rs::SysTick`. v1 doesn't run task bodies — conformance dispatch happens in main-thread macrostep loop, not via PendSV-driven task scheduling. Future phase 3b will re-enable a defensive set_pendsv that (i) gates on `dm.resched` and (ii) initialises TASK_PSPS at task.create time so PendSV always loads a valid PSP.

**(b) Parser doesn't track byte-position across `try_step` calls (`json_parser.rs::VectorStream`).** Each `try_step` call creates a fresh `Cursor` at pos 0 and dispatches on `self.state`. The state machine assumes the caller passes ONLY the unconsumed prefix. If the caller passes the same buffer twice (e.g. after `NeedMoreInput`), the parser re-sees previously-consumed bytes but in an advanced state, triggering `UnexpectedByte` errors. Net: byte-by-byte UART RX → main loop calls try_step incrementally → parser errors immediately on second byte.

Diagnostic chain: `DIAG_PARSE_KIND = 4` (Error variant) after `DIAG_BYTES_RX = 2`. Reading the RX ring confirmed exactly `{"` as the parser input; the parser advanced past `{` on call 1, then on call 2 re-saw `{` while expecting key → `UnexpectedByte`.

**Workaround (landed in main.rs):** wait for `\n` in the scratch buffer before calling try_step; pass the entire vector at once (matching the host-test single-call pattern). The host adapter writes vector + `\n` per SOS-04 §6.4 prose. Real fix is a parser API change: `ParseStep::NeedMoreInput` should carry `consumed: usize` so the caller can shift the buffer. Deferred to a future amendment.

**(c) USART1 FIFO drain doubled bytes (`transport.rs::usart1_isr_body`).** The wave-6 RX FIFO drain used `usart1.rdr.read().rdr().bits() as u8` — the stm32h7 PAC's `.read()` returns a register-struct value, and the chained `.rdr().bits()` accessor on H7 with FIFO mode produced (observed) two volatile loads per pop. Each byte was pushed to the ring TWICE. The ring filled with the pattern `{"config":{"max_{"config":{"max_tasks":8,"max_prtasks":8,...` — each 16-byte FIFO chunk replicated.

Diagnostic chain: `python3 -c 'subprocess.check_output(["probe-rs","read","b8","0x200005D8",...]).decode("latin-1")'` dumped the ring; the duplication was visually obvious.

**Fix (landed):** raw-pointer drain in `usart1_isr_body` reading USART1 ISR (0x4001_101C) and RDR (0x4001_1024) directly via `core::ptr::read_volatile`. Each iteration is exactly one volatile load per register.

**End-to-end bench results 2026-05-21:**

After landing all three fixes:
- Boot baseline emits cleanly and reaches host:
  ```
  {"after_input_idx":-1,"current":0,"tick_count":0,"rc":0,"tcb":[{"id":0,"prio":0,"state":2,...}, ...],"ready":[[],[],...],"sems":[...],"queues":[...],"irq_nest":0,"sched_lock":0,"pend_ticks":0}
  ```
  Sized 874 bytes, byte-equal to sim's `Datamodel::new` boot baseline (`"current":0`, `"tcb[0].state":2` Running, `"ready":[[],...]`, `"tick_count":0`).
- Adapter exit = 0 (received done sentinel correctly).
- Conformance harness parses each JSONL record without error.
- The `record_count_mismatch: expected 7 actual 1` is the remaining gap: firmware still emits only the boot baseline, no per-event traces.

**Bench-race workaround (also landed):** a 500-ms NOP delay in `main()` after `disco_bsp::init()` / `kernel::init()` / `transport::start()` and before `emit_trace_record(-1)`. STLINK V3E's USB-CDC OUT endpoint has a small (~64-byte) internal buffer that drops bytes when no host is draining; the conformance harness's adapter takes ~100-200 ms to spawn + open the port after a reset, and without the delay the first ~150 bytes of the boot baseline were lost. The 500-ms delay gives the adapter time to open before the firmware starts emitting. The delay's tick accumulation is zeroed via `dm_mut.tick_count = 0` immediately before emit_trace_record so the boot baseline still shows `"tick_count":0`. The proper fix is a host-side handshake (firmware emits `"READY\n"` after boot, adapter waits for it before sending vector), deferred to a future amendment.

**Boot-baseline Amendment 010 re-applied:** with the PendSV pend removed (fix (a)), promoting idle to RUNNING at boot (`current=0`, `tcb[0].state=Running`, `ready[] empty`) is safe and matches sim's `Datamodel::new`. Re-applied per EOQ-004 closure.

**EOQ status after Amendment 012:**

- ✅ **EOQ-004-AMENDMENT-011**: identified as three distinct bugs (a), (b), (c) above; all three patched. Bench round-trip now works for boot-baseline single-record path.
- 🟡 **NEW EOQ-005-AMENDMENT-012**: firmware emits boot baseline but does not emit per-event trace records. Likely cause is the workaround in (b) — `try_step` is called ONCE per `\n` arrival, so after VectorHeader returns `consumed = X`, main.rs shifts the buffer and loops, but the loop's newline-detection re-runs against the shifted buffer; if the parser's state needs to be re-entered with the SAME buffer (parser-internal state advanced past the header but cursor starts at pos 0 each call), the re-run sees pos 0 = a non-key byte in the new advance position. Investigation paths next session:
  - (i) Add a counter for each ParseStep variant separately (LOOP_HEADER_COUNT, LOOP_EVENT_COUNT, LOOP_ERROR_COUNT) instead of overwriting DIAG_PARSE_KIND.
  - (ii) Read the parser's internal `state` field via probe-rs after the Error to see what state it was in.
  - (iii) Replace the workaround in (b) with a proper parser API change: `NeedMoreInput { consumed: usize }`. Then byte-by-byte RX works naturally without the `\n` accumulate hack.

**Files modified this session (Amendment 012 scope):**
- `ports/m7-rust/sos-m7-rust/src/handlers.rs` — removed unconditional `set_pendsv` from SysTick body (fix (a)).
- `ports/m7-rust/sos-m7-rust/src/json_parser.rs` — no changes; main.rs accumulates until `\n` (workaround for (b)).
- `ports/m7-rust/sos-m7-rust/src/main.rs` — newline-buffered parsing workaround for (b); 500 ms boot delay; tick_count zero-reset; DIAG_* counters added.
- `ports/m7-rust/sos-m7-rust/src/transport.rs` — raw-pointer FIFO drain for (c); DIAG_BYTES_TX / DIAG_ISR_COUNT increment in write_byte / usart1_isr_body.
- `ports/m7-rust/sos-m7-rust/src/kernel.rs` — Amendment 010 re-applied (idle Running at boot).
- `/tmp/sos-m7-rust-bench-adapter.sh` — bench-adapter wrapper resets chip before invoking host-driver.

Cross-references: Amendment 010 (boot-baseline alignment); Amendment 011 (VCP path validation); SOS-04 §6.2.1 (firmware parser narrative); SOS-04 §6.4 (UART RX → parser → dispatch wiring); the wave-6 handlers.rs SysTick body (per-tick set_pendsv removal landed inline).

### 2026-05-21 — Amendment 013: EOQ-005 closure — full conformance suite passes on bench (Ira)

EOQ-005 closure session 2026-05-21. Two final firmware bugs identified, both fixed; the Rust port is now end-to-end conformance-validated against the disco-analyzer board.

**Final bench result:**

```
SOS-CONFORMANCE  suite: conformance/vectors  port: /tmp/sos-m7-rust-bench-adapter.sh
Filter: **/*.json
Vectors run: 6 (6 pass, 0 fail)

PASS  0001-two-tasks-same-prio-alternate-via-yield
PASS  0002-higher-prio-preempts-on-sem-give
PASS  0003-task-delay-tick-storm
PASS  0004-queue-full-empty-rejection
PASS  0005-crit-defers-ticks
PASS  0006-sched-suspend-defers-unblock

RESULT: ALL PASS
```

**Two more firmware bugs identified and fixed:**

**(d) H7 USART FIFO mode RX duplication** (`transport.rs::start`). With `CR1.FIFOEN = 1`, the PAC's `usart1.rdr.read().rdr().bits()` produced an observed pattern where each FIFO drain delivered the first ~8 bytes twice into the ring. Either the PAC's chained `.read().rdr().bits()` accessor double-pops in FIFO mode, OR the H7 FIFO output latch + FIFO body have a per-byte ack we're not doing. Without further hardware-engineer-level diagnosis, the operational fix is to disable FIFO mode entirely:

```rust
usart1.cr1.write(|w| {
    w.te().set_bit()
     .re().set_bit()
     .rxneie().set_bit()
     .ue().set_bit()
    // FIFOEN intentionally not set per EOQ-005 finding
});
```

Non-FIFO mode uses classic per-byte RXNE: read RDR pops the one-byte holding register and clears RXNE. At 115200 baud the IRQ overhead is ~12 µs per byte; the SOS conformance vector emit cadence is much slower than that, so the FIFO's burst-tolerance benefit isn't load-bearing for v1.

**Diagnostic chain:** Python-driven RX ring read showed `{"config":{"max_{"config":{"max_{"configtasks":8{"configtasks":8,"max_prio":8,"m,"max_prio":8,"max_sems"...` — each ~16-byte chunk replicated with the first ~8 bytes also appearing as a "stuck" prefix. After CR1.FIFOEN clear, the ring contained the vector exactly once, and the parser consumed it cleanly.

**(e) Hardware SysTick advancing `dm.tick_count` in Conformance mode** (`handlers.rs::SysTick`). With FIFO bug (d) fixed, all 7 expected trace records appeared. The only divergence was `bytes_differ at [1].tick_count: expected 0 actual 76` (and similar 153, 229, 305, 381, 457 for records [2]-[6]). Hardware SysTick fires every 1 ms; each per-event trace emit takes ~76 ms (the boot-baseline emission + per-event trace at 115200 baud); the chart's `tick_idle_sys_tick` script (transliterated into the SysTick ISR body in wave-6) increments `dm.tick_count` on every fire. Sim's vector-0001 expected_trace has `tick_count: 0` throughout — the harness drives time via explicit `sys.tick` events in the input array, not via wall clock.

**Resolution: SysTick body wrapped in `if false { ... }`** for v1 Conformance mode. In Conformance mode (PCDN-SOS-04-004 default), all chart events arrive via UART; hardware SysTick must NOT auto-advance tick_count. The future Standalone-mode build (the `standalone-smoke` feature flag per PCDN-SOS-04-004) will re-enable the SysTick body by wrapping it in `#[cfg(feature = "standalone-smoke")]`.

Note that PendSV pend (fix (a) from Amendment 012) and SysTick-body (fix (e) here) are independent — both lived in the SysTick handler, both were independently disabled for v1 Conformance mode. The fix (a) commit landed the PendSV-pend removal; fix (e) here landed the dm.tick_count increment removal.

**Full bug inventory from EOQ-004 + EOQ-005 (Amendments 012-013):**

| # | Bug | Location | Fix |
|---|---|---|---|
| (a) | Unconditional `SCB::set_pendsv()` on every SysTick → null-PSP load → HardFault | `handlers.rs::SysTick` | Removed `set_pendsv()` (v1 Conformance mode doesn't run task bodies) |
| (b) | Parser doesn't track byte-position across `try_step` calls | `json_parser.rs::VectorStream::try_step` | Workaround: main.rs accumulates until `\n` then single-call parse; proper API change deferred |
| (c) | PAC `.read().rdr().bits()` chained accessor was suspected — turned out (d) was the real root | `transport.rs::usart1_isr_body` | Raw-pointer drain landed but didn't actually fix root cause; FIFOEN clear (d) did |
| (d) | H7 USART FIFO mode causes RX byte duplication (8-byte prefix replicated in each 16-byte chunk) | `transport.rs::start` | Disabled FIFO mode: `CR1.FIFOEN = 0` |
| (e) | Hardware SysTick auto-advances `dm.tick_count` in Conformance mode | `handlers.rs::SysTick` | Wrapped body in `if false { ... }`; future `standalone-smoke` feature gate |

**End-to-end pipeline now validated:**

```
SOS-03 conformance vectors (JSON files)
  → sos-conformance harness
    → SubprocessPort spawns bench-adapter wrapper script
      → wrapper does `probe-rs reset --chip STM32H747XIHx`
      → wrapper exec's sos-m7-rust-host-driver
        → driver opens /dev/cu.usbmodem1302 at 115200 8N1
        → driver writes PortBinaryInput JSON + `\n` to UART TX
          → STLINK V3E USB-CDC ACM → USART1 PA10 RX
            → CM7 firmware USART1 IRQ → drain → RX ring
            → main loop reads ring → scratch → accumulate to `\n`
            → VectorStream::try_step → ParseStep loop
              → emit_trace_record → write_byte spin loop → USART1 TX
            → USART1 PA9 TX → STLINK V3E USB-CDC ACM
        → driver reads stdout JSONL lines, strips done sentinel
      → harness compares JSONL records against expected_trace
    → 6/6 vectors PASS byte-equal
```

**Chart-derived code: VALIDATED.** This bench result is the load-bearing proof that the chart → sim → firmware Rust port translation is byte-faithful through every conformance vector. The scripts.rs port-side bodies are correctly transliterated from sim's scripts.rs which are correctly hand-compiled from the chart. The 6/6 PASS rate (no diffs) means every record byte matches sim's authoritative emission.

**Remaining work surfaces (post-Amendment-013):**

- 🟢 SOS-04 bench validation: **CLOSED.** All 6 conformance vectors pass.
- 🟡 SOS-05 C port bench validation: not yet attempted; the C port builds clean under pinned toolchain and the same 6 conformance vectors should pass once the C-side hand-rolled JSON parser is verified (same byte-equality contract).
- 🟡 SOS-06-A codegen evaluation: methodology ratified; no toolchain selected yet by user.
- 🟡 Workaround → spec amendments still owed:
  - `USART1_BAUD = 115200` (vs PCDN-007 ratified 921600) — bench-side baud reduction.
  - `CR1.FIFOEN = 0` (vs PCDN-016 user-note "FIFO mode enabled") — bench-side workaround for the duplication bug.
  - 500 ms NOP delay in `main()` before emit_trace_record — bench-side workaround for STLINK V3E USB-CDC buffer drop.
  - `tick_count` zero-reset in `main()` before emit_trace_record — bench-side workaround for SysTick accumulation during the delay.
  - Hardware SysTick body `if false { ... }` gate — v1 Conformance-mode behavior; future `standalone-smoke` feature gate.
  - Diagnostic counters `DIAG_*` in DTCM — bench debug fixture, can be removed for production.

Each of these MAY ratify in a follow-up dedicated §15 amendment that splits "bench-iteration scaffolding" from "spec-conformant v1 firmware behavior". For now, the firmware-as-flashed bears the workarounds and the conformance run is clean.

Cross-references: Amendment 010 (boot-baseline alignment); Amendment 011 (VCP path validation, 100→200 MHz APB2 confusion); Amendment 012 (PendSV + parser-position + first FIFO-drain attempt); RM0399 §54.8 (H7 USART FIFO mode reference); rlvgl-platform `examples/stm32h747i-disco/src/main.rs:1996-1999` (rlvgl also sets FIFOEN at 100 MHz APB2; their bench scenario may not exercise the same drain pattern).

### 2026-05-21 — Amendment 014: PCDN-SOS-04-013 prose reconciliation — APBx prescaler vs USART1_PCLK_HZ across ports (Ira)

Today's first-bench close-outs of both ports (SOS-04 Rust port: Amendment 013 above, 6/6 PASS; SOS-05 C port: SOS-05 §15 Amendment 004, 6/6 PASS) surfaced an internal inconsistency in the PCDN-SOS-04-013 prose and a per-port divergence in how the two ratified ports realise the same USART1 baud target. Both ports are conforming under the SOS-03 byte-equality contract; the spec prose is what needs reconciliation.

**The inconsistency in PCDN-SOS-04-013 as ratified.** The PCDN-013 entry above (§15, 2026-05-19 initial draft, and 2026-05-19 ratification consolidated resolution) reads:

> "HCLK = 400 MHz; APB1/APB2/APB3/APB4 dividers = /2 (200 MHz peripheral); D1CPRE = /1; D2HPRE = /2"

This is internally inconsistent on the disco-analyzer board's realised clock tree. The recommendation also sets `D2HPRE = /2`, so HCLK actually evaluates to `400 / 2 = 200 MHz` (not 400 MHz). With HCLK = 200 MHz, an APBx prescaler of `/2` yields APBx = **100 MHz**, not 200 MHz; APBx = `/1` yields APBx = 200 MHz. The "/2 (200 MHz)" parenthetical mixes the two choices.

**The two as-built ratified configurations.**

| Port | APBx prescaler | Achieved APB2 | `USART1_PCLK_HZ` constant | `BRR = USART1_PCLK_HZ / 115200` | Status |
|---|---|---|---|---|---|
| SOS-04 Rust (`ports/m7-rust/sos-m7-rust/src/disco_bsp.rs`) | `/1` | 200 MHz | `200_000_000` | `1736` (`0x6C8`) | Bench-validated 2026-05-21, 6/6 PASS |
| SOS-05 C (`ports/m7-c/sos-m7-c/src/disco_bsp.c`) | `/2` | 100 MHz | `100_000_000` | `868` (`0x364`) | Bench-validated 2026-05-21, 6/6 PASS (matches rlvgl reference) |

**The surviving invariant.** Both choices satisfy:

```
BRR = USART1_PCLK_HZ / USART1_BAUD
```

where `USART1_PCLK_HZ` MUST match the *actual* APBx setting realised by `disco_bsp::init_clocks()`, not a nominal value detached from the prescaler write. Conformance is preserved per-port as long as the BRR write and the APBx setting agree end-to-end; the byte-stable trace protocol downstream is indifferent to which clock path produces the 115200 baud.

**The bench artefact that motivated this amendment.** The SOS-05 C port's bench bring-up captured (via `dd if=/dev/cu.usbmodem1302 bs=4 count=1 | xxd`) a characteristic four-byte repeating pattern `e6 98 e6 98` while attempting to read the boot baseline JSON record. The pattern is the signature of a 2× baud mismatch: the chip was emitting at `100_000_000 / 1736 ≈ 57_603` baud (BRR computed against `USART1_PCLK_HZ = 200_000_000` but the realised APB2 was 100 MHz after a `/2` prescaler) while the host was sampling at 115200. Each transmitted bit covered ~2 host sample windows, so each chip-byte arrived as a pair of replicated host-bytes; the repeating signature was the chip's `'\n'` framing byte (`0x0A`, bit-pattern `00001010`) re-quantised through the 2× resampling onto the host's 115200 clock.

The diagnostic path was: probe-rs reads of `RCC->D2CFGR` and `USART1->BRR` reconciled against the firmware's `USART1_PCLK_HZ` const; the mismatch between `D2PPRE2 = /2` (D2CFGR bits) and the constant's `200_000_000` value resolved the symptom in one step. See SOS-05 §15 Amendment 004 "C-port-specific finding: USART1 kernel clock vs APBx prescaler" for the full bench narrative and the resolving change.

**Forward paths (not ratified by this amendment — see EOQ-001-AMENDMENT-014).** Three options are on the table; the user resolves which one normalises the prose:

- **Option (a) — Normalise on `/1` (APBx = 200 MHz).** SOS-05 C port migrates to APBx = `/1` and `USART1_PCLK_HZ = 200_000_000`; BRR becomes `1736` to match the SOS-04 Rust port. Simpler conceptual model — a single APBx value across both ports, single BRR value. Caveat: at VOS1 the H7 datasheet's APBx max is 100 MHz; APBx = 200 MHz is over-spec on paper. Evidently working on the disco-analyzer for the SOS workload, but a hidden timing-margin risk under hotter silicon or higher load.

- **Option (b) — Normalise on `/2` (APBx = 100 MHz).** SOS-04 Rust port migrates to APBx = `/2` and `USART1_PCLK_HZ = 100_000_000`; BRR becomes `868` to match the SOS-05 C port. Aligns with the H7 datasheet APBx 100 MHz max at VOS1 and with the rlvgl reference firmware on the same board (whose `BRR=868 (100 MHz / 115200)` comment at `examples/stm32h747i-disco/src/main.rs:1996` is the reference shape). Safer voltage-margin posture; small Rust-side change.

- **Option (c) — Keep both options conforming; amend the PCDN-013 prose to enumerate them.** PCDN-SOS-04-013's text reworded to: "HCLK = 200 MHz (after `D2HPRE = /2`); APB1/APB2/APB3/APB4 prescaler is per-port at either `/1` (→ APBx = 200 MHz, over-spec at VOS1 but observed working on the disco-analyzer) or `/2` (→ APBx = 100 MHz, datasheet-compliant at VOS1); each port's `USART1_PCLK_HZ` constant MUST match the as-built APBx setting." Both ports stay on their bench-validated paths; the conformance invariant moves from "single clock-tree" to "per-port APBx/PCLK pairing must agree". Lowest churn; documents the as-built reality.

This amendment does not pick among (a)/(b)/(c) — that's the user's call. The text of PCDN-SOS-04-013 in §15 above is **not** edited by this amendment; the next §15 amendment will rewrite that PCDN entry once the user ratifies one of the options.

**Cross-references:** SOS-05 §15 Amendment 004 (C-port resolution + the `e6 98 e6 98` bench artefact in full); SOS-04 §15 Amendment 011 (rlvgl reference firmware's APB2 = 100 MHz / BRR = 868 first observed); SOS-04 §15 Amendment 013 (Rust port's APB2 = 200 MHz / BRR = 1736 bench close-out); PCDN-SOS-04-007 (baud rate, recorded as 115200 for v1 first-bench pending its own ratification entry); rlvgl-platform `examples/stm32h747i-disco/src/main.rs:1996-1999` (reference BRR=868 site).

**Open question (carried forward, parent CLAUDE.md ERRATA EOQ convention):**

- **EOQ-001-AMENDMENT-014**: ratify the forward path for PCDN-SOS-04-013's prose — option (a) `/1` normalisation (both ports → APBx = 200 MHz, BRR = 1736), option (b) `/2` normalisation (both ports → APBx = 100 MHz, BRR = 868), or option (c) per-port both-conforming (PCDN-013 prose rewritten to make the per-port pairing of APBx ↔ `USART1_PCLK_HZ` ↔ BRR explicit). Resolution lands a follow-up §15 amendment that (i) rewrites PCDN-SOS-04-013's text in the 2026-05-19 ratification block above, and (ii) for options (a)/(b), schedules the migrating port's `disco_bsp` change to align with the chosen prescaler.

### 2026-05-23 — SOS-07 rename ratification (Ira)

The initiative rename from *Statechart-Orchestrated Scheduler* to **Statechart Orchestration System** is ratified through [`SOS-07-CONCEPTS.md`](./SOS-07-CONCEPTS.md). The acronym `SOS` is unchanged across this phase doc family; all in-text references continue to read as `SOS` for cross-doc citation stability.

Cross-phase invariants INV-SOS-A through H + the AuthorityRelationship matrix promote from informative roadmap text (`SOS-ROADMAP-07-PLUS.md`) to normative phase content in SOS-07. They cite by ID into SOS-04's normative sections without modifying any of SOS-04's frozen content.

Bootstrap-vs-general framing (SOS-07 §8): the kernel chart `rtos_kernel.scxml` is reframed as the v1 demonstration the methodology generalises from, not "the chart". The bench-validated state recorded across SOS-04's prior amendments carries forward unchanged.

No frozen-enum value modified. No PCDN re-ratified. No port-spec impact.

### 2026-05-27 — SOS04-09 runtime-boundary amendment (Ira)

Closes [SOS-09] umbrella §12 gate (h) — "SOS-04 §15 amendment co-landed recording the SOS-09 emission / SOS-04 runtime boundary." Co-lands with the 2026-05-27 SOS09W1 umbrella roll-up commit (`43c45bf`). No frozen enum modified; no PCDN re-ratified; no INV-S-PORT-N invariant text changed. This amendment records the AS-BUILT boundary contract between SOS-09's emitted artifacts and SOS-04's runtime crate `sos-m7-rust`.

**Authority placement.** Per [SOS-07 §7] AuthorityRelationship matrix, the SOS-09 → SOS-04 boundary is **compose**: SOS-04's runtime composes SOS-09-emitted artifacts as inputs; neither owns the other's surface. The boundary direction is one-way — **SOS-09 emits; SOS-04 consumes**. SOS-04 does NOT emit anything SOS-09 consumes; SOS-04's runtime MAY depend on the SOS-09 emit OUTPUT but MUST NOT depend on the emit CODE (the SOS-09 emit modules at `tools/sos-codegen/transliterate_*.py` MUST NOT depend on `sos-m7-rust` or any SOS-04 runtime symbol).

**The four-artifact boundary set** — every SOS-09 sub-phase that produces an artifact crossing into the SOS-04 runtime is enumerated below with the AS-BUILT emitter filename and the consumption shape on the SOS-04 side. Filenames per ERRATA-001 (SOS-09-B rename `svd_emit.py` → `transliterate_svd.py`) and ERRATA-002 (SOS-09-G rename `mpu_emit.py` → `transliterate_mpu.py`), both reconciled in commit `d24528f`.

| SOS-09 sub-phase | Emitter (as-built) | Emit shape | SOS-04 consumption |
|---|---|---|---|
| SOS-09-D (Rust HAL trait) | `tools/sos-codegen/transliterate_rust.py` | A per-chart Rust module exposing a `RegisterBlock` + newtype-wrapper family + type-state-for-shared + MPU region constants per [SOS-09-D] §5 | The `sos-m7-rust` crate MAY consume the emitted module via a `cargo` dependency. The HAL traits define typed register access; SOS-04's runtime invokes them but MUST NOT redefine them. INV-S-PORT-N (per [SOS-04 §9] — no hand-edits to generated code; mirrors INV-S-MEM-1) extends to the emitted HAL module. |
| SOS-09-G (MPU configuration) | `tools/sos-codegen/transliterate_mpu.py` | A `static` Rust table of ARMv7-M MPU region descriptors per [SOS-09-G] §5, accompanied by a single `apply_mpu_config()` entry point | The `sos-m7-rust` boot path SHALL call `apply_mpu_config()` once during `init` when MPU enforcement is wired in (future SOS-04-B production-hardening amendment per INV-S-PORT-8 — the AS-BUILT v1 runtime does not yet call it). The table contents are owned by the SOS-09-G emit; SOS-04 owns the **timing** of when `apply_mpu_config()` runs (boot, post-clock-tree, before any task body executes). The when-to-call is SOS-04's; the what-to-write is SOS-09-G's. (See "Open boundary item" below.) |
| SOS-09-B (CMSIS-SVD) | `tools/sos-codegen/transliterate_svd.py` | A per-chart `.svd` artifact for debugger consumption (ARM CMSIS-SVD 1.3 schema) | **NOT consumed by the `sos-m7-rust` runtime.** The SVD is a downstream debugger artifact (svd2rust input, openocd / probe-rs SVD load, IDE register inspection). SOS-04 does NOT link against the SVD; the HAL trait emission (SOS-09-D) is what SOS-04's runtime actually consumes. The SVD's existence in `build/` is governed by [SOS-09] INV-S-MEM-2. |
| SOS-09-F (Membrane vectors) | `tools/sos-codegen/vectors_emit.py` | Python adapter files + per-channel fixtures keyed by `MV-<UUID>-<family>-<seq>` per [SOS-09-F] §5.3 | **NOT part of the SOS-04 runtime.** Membrane vectors are a separate verification artifact exercising the chart's HW↔SW edges via cocotb (HDL) or the SOS-04 bench-host adapter ([SOS-04 §13] names `serialport = "4"`). The vectors compose against the same `sos-m7-rust-host-driver` adapter SOS-04 already ratifies; the firmware's runtime does not link the vectors. |

**Negative listing.** The boundary is exactly the four rows above. SOS-09's other sub-phases — SOS-09-A (chart annotation surface, an authoring-side surface consumed by every emitter), SOS-09-C (C HAL header emission, consumed by [SOS-05], not [SOS-04]), SOS-09-E (HDL register-file RTL, consumed by FPGA/ASIC targets, not the M7 runtime) — do NOT cross into SOS-04. SOS-09-C / -E rows are deliberately omitted from the table above to keep the SOS-04 consumption surface bounded.

**Frozen-enumeration registration policy for the four-artifact boundary set: Standards Action.** Adding a fifth SOS-09-emitted artifact that the SOS-04 runtime consumes requires (i) a §15 amendment to this doc enumerating the new row in the table above, (ii) a co-cite from the originating SOS-09-* sub-phase's §16 (or §15) recording the cross-boundary contract, AND (iii) ratification of the consumption-side timing surface (when SOS-04 calls into the new artifact). Promoting one of the negative-listed sub-phases (SOS-09-A / -C / -E) into the boundary set follows the same Standards Action path.

**Single-source-of-truth doctrine extends to this boundary.** Any future amendment to a SOS-09 emit shape — a new HAL trait method, a new MPU region descriptor field, a new SVD attribute, a new membrane vector family — that the SOS-04 runtime consumes MUST land with (or cite) a SOS-04 §15 entry confirming the runtime continues to consume the new shape without modification. The chart-as-source claim ([SOS-07] INV-SOS-A) terminates at the chart; the artifact-as-derived claim ([SOS-09] INV-S-MEM-1) extends through the emit to the consumer. SOS-04 reading a stale shape is a boundary-contract bug, not a runtime bug.

**Cross-reference: ERRATA-001 (deferred surface).** ERRATA-001 (commit `d24528f`) reconciled the SOS-09-B implementation cites and noted that `tools/sos-codegen/svd_validate.py` + `schemas/CMSIS-SVD-1.3.xsd` are **deferred** — neither has landed; the SOS-09-B validation gate is currently spec-only. This amendment respects that deferral; the boundary contract above describes the AS-BUILT shape (the `.svd` artifact emitted by `transliterate_svd.py`), not the original SOS-09-B §13 forecast that the errata supersedes. If the validator + XSD bundle ever land, they remain on the SOS-09-B side of the boundary — they do not enter the SOS-04 runtime under any forward path that does not first amend this row.

**Cross-reference: ERRATA-002 (filename rename).** ERRATA-002 (commit `d24528f`) reconciled the SOS-09-G implementation cite from the §16 forecast `mpu_emit.py` to the as-built `transliterate_mpu.py`. The SOS-09-G row in the table above uses the as-built filename; the boundary contract is unchanged by the rename.

**Open boundary item — `apply_mpu_config()` timing ownership.** The SOS-09-G row above states that SOS-04 owns the timing of `apply_mpu_config()`. [SOS-09-G] §5 specifies the table shape and the entry-point existence; whether it ALSO specifies the call site (boot, post-clock-tree, before-first-task) or whether that placement remains an SOS-04-side concern is a boundary edge worth surfacing. The AS-BUILT runtime in `sos-m7-rust` does not yet call `apply_mpu_config()` — the firmware presently runs unprotected per [SOS-04 §6.8] boot path. When MPU enforcement lands (a future SOS-04-B production-hardening amendment per INV-S-PORT-8), the call-site placement ratifies in that amendment; this amendment records the existing read of the spec as "SOS-04 owns when; SOS-09-G owns what". A future SOS-09-G amendment MAY narrow the timing surface (e.g. mandate "before first task body runs"), at which point a §15 entry here mirrors the narrowing.

**Cross-references:** [SOS-07 §7] AuthorityRelationship matrix (the `compose` row applied here); [SOS-09 §6] sub-phase scope (the seven sub-phases A–G; four of them in the boundary set above); [SOS-09 §12 gate (h)] (the gate this amendment closes); [SOS-09-D] §5 / §13 (Rust HAL emit shape); [SOS-09-G] §5 (MPU configuration emit shape); [SOS-04 §9] INV-S-PORT invariants (the no-hand-edits property extends to consumed emit modules); [SOS-04 §13] (`serialport = "4"` membrane-vector adapter dependency); ERRATA-001 / ERRATA-002 (filename reconciliations, commit `d24528f`); SOS09W1 umbrella roll-up commit `43c45bf` (the 2026-05-27 §12 acceptance pass that surfaced gate (h) as outstanding).

### 2026-05-27 — Cross-reference: PCDN-SOS-09-G-005 ratified (apply_mpu_config timing owned by SOS-04)

Closes the "Open boundary item — `apply_mpu_config()` timing ownership" surfaced in the 2026-05-27 SOS04-09 runtime-boundary amendment immediately above. Ratified by Ira at the 2026-05-27 multi-PCDN session (option (a)): SOS-04 owns *when* `apply_mpu_config()` is invoked during the boot sequence (call-site placement: post-clock-tree, pre-task-start, when MPU enforcement wires in); SOS-09-G owns the table shape, the per-region descriptor contents per PCDN-SOS-09-G-001 through -004, and the body of `apply_mpu_config()` itself (the register-write sequence codified in [SOS-09-G §5.5]). The AS-BUILT v1 firmware in `sos-m7-rust` still does NOT call `apply_mpu_config()` — MPU enforcement is deferred to the future SOS-04-B production-hardening amendment per INV-S-PORT-8, exactly as recorded in the SOS-09-G row of the four-artifact boundary set in the amendment immediately above; this entry does not change the AS-BUILT state. When MPU enforcement does wire in via a future SOS-04-B amendment, the SOS-04 boot path will invoke `apply_mpu_config()` at the SOS-04-owned call site, consuming the SOS-09-G-emitted table without modification. The boundary stays `compose` per [SOS-07 §7] AuthorityRelationship matrix (no upstream-vs-downstream ownership shift). Frozen-enumeration registration policy for the ownership boundary itself: **Standards Action** (moving the timing surface to SOS-09-G would require a co-landing §15 here narrowing or removing SOS-04's timing surface). Cross-cite: [SOS-09-G §16] amendment "2026-05-27 — PCDN-SOS-09-G-005 ratification: apply_mpu_config() call-timing ownership" (co-authored in this commit) records the SOS-09-G side bidirectionally.

### 2026-05-27 — Cross-reference: ERRATA-007 settles MPU install function name

`apply_mpu_config()` is confirmed as the canonical name for the MPU install entry point across both SOS-04 and SOS-09-G. Resolves ERRATA-007 (`docs/concepts/ERRATA.md` ERRATA-007). The four-artifact boundary set table immediately above (the SOS-09-G row at `docs/concepts/SOS-04-CONCEPTS.md:1282`) used `apply_mpu_config()` as the entry-point identifier from Wave-2P landing (commit `38699f4`) and through the Wave-5C cross-reference (commit `1180910`); SOS-09-G §5.5 prose carried the alternate identifier `sos_mpu_install()` until this commit. The PCDN-SOS-09-G-005 ratification entry immediately above explicitly deferred the §5.5 prose reconciliation as a future minor amendment; the co-landing [SOS-09-G §16] entry "2026-05-27 — ERRATA-007 resolution: canonical MPU install function name" IS that amendment. No boundary-contract change; no AS-BUILT state change; no behaviour change. The boundary stays `compose` per [SOS-07 §7]; the four-artifact boundary set's row text is unchanged.

### 2026-06-01 — Cross-reference: FAM-04-A discharged by SOS-04-A (Ira)

The **FAM-04-A** future-amendment marker ("make stack sizes configurable") is **discharged** by the newly-ratified [`SOS-04-A-PORT-CONFIG-SURFACE.md`](./SOS-04-A-PORT-CONFIG-SURFACE.md) (ratified 2026-06-01). SOS-04-A introduces the carrier-independent `port_config` surface — a chart `<sos:task_config>` annotation declaring per-task `stack_words` + named `stack_region` (plus sem/queue tables, `tick_hz`, `kernel_stack_words`) — which the SOS-04 (Rust) and SOS-05 (C) emitters lower to the static allocations that §6.3 currently hard-codes. `.task_stacks` remains the backward-compatible default region; a referenced-but-undefined region is a compile-time error. The marker text above is updated with the ✅ DISCHARGED note. Motivating consumer: the sibling DAA-08 initiative's need for heterogeneous per-task stacks in a named region (REQ-SOS-4), cited from DAA-08's published registry (no DAA source crawled). No behaviour change in this entry — SOS-04-A's emitter implementation lands as follow-up commits.

### 2026-06-02 — Workspace `[profile.release]` landed + FLASH-overflow filed (ERRATA-008) (Ira)

The §6.1 release profile (`lto="fat"`, `codegen-units=1`, `opt-level="s"`, `panic="abort"`) is now landed at the **workspace root** `Cargo.toml`. Cargo ignores `[profile.*]` in non-root workspace members, so despite the `sos-m7-rust` crate doc referencing these settings they had never taken effect; the canonical build command (§8) ran with default-release settings. No PCDN re-ratified; no frozen enum / invariant text changed — this records an as-built build-config fix.

Surfaced during **DAA-08** cross-repo verification: the canonical `cargo build --target thumbv7em-none-eabihf --release -p sos-m7-rust` **overflows the 1 MiB CM7 Bank-1 FLASH** — `.text ≈ 1.44 MB`, dominated by float/`u128` `core::fmt` (`flt2dec`/`dec2flt`/`exp_u128`) + the `stm32h747cm7::Interrupt` `Debug` impl, reachable from the `json_parser`/trace layer. The profile landing is necessary-not-sufficient; the bloat remediation (integer-only formatting audit preserving SOS-02 §7 / SOS-03 INV-S-CONF-1 byte-equality, vs feature-gating the JSON layer out of the flashable bin) is tracked in **`docs/concepts/ERRATA.md` ERRATA-008 / EOQ-001-ERRATA-008** pending owner decision. This overflow was latent because bench bring-up flashed the SOS-05 C port, not the SOS-04 Rust port at full size. DAA-08-B depends on a flashable SOS-04 Rust port and is blocked on ERRATA-008's defect-1 resolution.

**Resolved same day (2026-06-02):** ERRATA-008 defect-1 fixed via path (a) — integer-only trace writer + removal of `Debug`/`unwrap`/`expect`-with-Debug reachability roots, plus `--gc-sections` in `build.rs` to dead-strip the now-unreachable PAC `Debug` + `core::fmt` float/u128 code. The `stm32h7` PAC is retained; no peripheral-access rewrite; no trace wire-format change. The firmware now links within 1 MiB FLASH (`.text` 64,704 B; 80,600 B FLASH-resident) with byte-equal conformance (8 writer + 6 conformance + 6/6 vectors). ERRATA-008 is 🟢. On-target bench verification remains DAA-08-C.
