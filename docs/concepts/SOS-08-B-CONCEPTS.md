# SOS-08-B — HDL Layer-1 service composition

**Status:** 🟢 **ratified 2026-05-23** (see §15).

## 0. Authority policy

This phase doc ratifies the Layer-1 (L1) service-composition contracts for the SOS HDL backend. The umbrella `SOS-08-CONCEPTS.md` §6 named five L1 services (`sos_mailbox`, `sos_event_group`, `sos_resource_pool`, `sos_periodic_task`, `sos_message_channel`); this doc ratifies each service's interface, L0 composition recipe, behavioural contract, SVA property set, vector-emission contract, and software-side analog mapping.

The umbrella owns the cross-sub-phase decisions (synthesizable subset, vendor-IP override, cooperative-only, vector emission priority); this doc owns the per-service contracts that the chart-side syscall vocabulary (from SOS-04 / SOS-05) reifies on the hardware side of the membrane.

**Normative** sections of this doc: §3 glossary, §4 source-of-truth map, §5 frozen decisions, §6 per-service contracts (six subsections), §7 cross-service invariants, §8 standards integration matrix additions, §10 reconciliation, §12 acceptance checklist.

**Informative** sections: §1 purpose, §2 problem statement, §11 non-goals, §15 change log.

All keywords MUST, MUST NOT, SHALL, SHOULD, SHOULD NOT, MAY, RECOMMENDED are interpreted per RFC 2119 / 8174 when capitalised.

This doc cites SOS-07 §6 invariants (INV-SOS-A through H), SOS-08 §7 invariants (INV-S-HDL-1 through 5), and the SOS-08-A L0 primitive contracts by primitive name. SOS-08-A is being authored in parallel; this doc assumes the L0 contracts exist with the names + handshake shape sketched in SOS-08 §6 SOS-08-A.

## 1. Purpose

To take the FreeRTOS / POSIX-shaped vocabulary the chart side uses (SOS-04 / SOS-05 syscall ABI: `sem.take`, `sem.give`, `queue.send`, `queue.receive`, `task.create`, `task.delay`, plus the future event-group and mailbox-with-priority extensions) and ratify the hardware-side L1 services that realise the same vocabulary on the HDL backend. The L1 services are the layer the chart author thinks in; the L0 primitives are an implementation detail the L1 layer hides.

Per INV-S-HDL-1 (handshake-compatible ports), every L1 service composes from L0 primitives through the canonical req/ack or ready/valid shape, and exposes the same shape outward. The composition is recursive: a chart-side `<transition event="sem.take">` lowers to an L1 `sos_resource_pool::acquire` call, which lowers to an L0 `sos_fifo_sync::dequeue` operation, which lowers to two synchronous register reads and one combinational arbitration result. Each layer has its own SVA property set; failures render at the layer at which they originated, in chart vocabulary at the top.

## 2. Problem statement

Four observations motivate ratifying the L1 contracts as their own sub-phase, rather than rolling them into the L0 sub-phase or the chart-emission sub-phase:

1. **L1 is the chart-author-facing layer.** The chart author writes `sem.take` or `queue.send`; they do not write `sos_arbiter_rr.req[3] = 1`. The L1 contracts are the API a chart author sees; the L0 contracts are the API a hardware engineer doing primitive-level work sees. Ratifying them as one doc fuses two audiences with different review priorities.

2. **L1 composition rules are the load-bearing correctness claim.** A mailbox built from `sos_fifo_sync` + a ready/valid handshake on the producer side has different correctness obligations than the underlying FIFO alone. Priority dispatch composes across multiple parallel FIFOs + an arbiter; that composition's SVA properties are NOT the union of the per-component properties — they are a new claim about message ordering across priority lanes. Ratifying the composition rules separately surfaces them for review.

3. **Vector-emission scope at L1 differs from L0.** L0 cocotb tests cover the primitive in isolation; L1 cocotb tests cover service-level behavior against the chart-side verb set. The vector emission contract at L1 has to round-trip the chart vocabulary back to RTL signals (per INV-SOS-H + INV-S-HDL-5), which is a different obligation than the L0 contract surface.

4. **Vendor-IP override pass-through is an L1 concern.** When the L0 `sos_fifo_async` is swapped for `xpm_fifo_async` at build time, the L1 `sos_mailbox` composed from it must transparently absorb the swap with no chart-side change. Ratifying the pass-through rule at the L1 level (rather than re-deriving it per service) keeps the cross-vendor consistency story tractable.

## 3. Canonical glossary

Terms normative within SOS-08-B+. Authority relationships per §8.

| Term | Definition |
|---|---|
| **Mailbox** | Bounded message-passing primitive between producers and consumers. The hardware analog of FreeRTOS `xQueueSend`/`xQueueReceive` and POSIX `mq_send`/`mq_receive`. Realised as `sos_mailbox` (this phase). |
| **Event group** | N-bit event-flag bundle supporting wait-any, wait-all, and clear-on-read. The hardware analog of FreeRTOS `xEventGroupWaitBits` and POSIX signals. Realised as `sos_event_group` (this phase). |
| **Resource pool** | Static-allocation free-list of typed resource IDs (TCB slots, semaphore handles, queue handles). The hardware analog of FreeRTOS static memory pools and the SOS-04 `TCB_POOL` / `SEM_POOL` / `QUEUE_POOL` static allocations. Realised as `sos_resource_pool` (this phase). |
| **Periodic task** | An FSM whose enable signal is driven by a periodic strobe; the hardware analog of FreeRTOS `xTaskCreatePeriodic` and POSIX timer-driven signal handlers. Realised as `sos_periodic_task` (this phase). |
| **Message channel** | Cross-clock-domain typed event channel with metadata header; the hardware analog of FreeRTOS streams across an ISR boundary and POSIX named pipes. Realised as `sos_message_channel` (this phase). |
| **Service-level SVA** | SVA properties that assert L1-layer guarantees (mailbox ordering across priority lanes, event-group atomic clear-on-read, pool acquire/release symmetry) — not the per-L0 properties; the composition's emergent claim. |
| **L1 pass-through** | The discipline that L1 services inherit their L0 primitive's vendor-IP shim selection transparently — the chart side neither sees nor selects the vendor backend. |
| **Service-level cocotb test** | A cocotb testbench that drives the L1 interface (post / take / set / wait / acquire / release / tick) and checks behaviour against chart-vocabulary expectations — not RTL signal traces. |
| **Service-level SVA bind** | A `bind` declaration that attaches service-level SVA properties to the L1 module's instance, alongside whatever L0-level binds are already present. |

## 4. Source-of-truth map

| Concept | Authority |
|---|---|
| L0 primitive contracts | `SOS-08-A-CONCEPTS.md` (parallel-authored) — cited, not redefined |
| L1 service interface signatures | **this doc** §6.1–6.5 (one per service) |
| L1 → L0 composition recipes | **this doc** §6.1–6.5 (composition diagram per service) |
| Service-level SVA property sets | **this doc** §6.1–6.5 |
| Service-level cocotb test contracts | **this doc** §6.1–6.5; vector-emission obligations §6 cross-service tail |
| Vendor-IP override pass-through rule | **this doc** §5.3 |
| Software-side vocabulary mapping (L1 verb ↔ FreeRTOS / POSIX / chart-syscall event) | **this doc** §6.1–6.5 + §10 reconciliation |
| Cross-service invariants | **this doc** §7 |
| Cross-phase invariants INV-SOS-A through H | `SOS-07-CONCEPTS.md` §6 |
| Cross-sub-phase invariants INV-S-HDL-1 through 5 | `SOS-08-CONCEPTS.md` §7 |
| RTL source paths (per-service `*.vhd` / `*.sv`) | `rtl/services/sos_<service>.{vhd,sv}` (created at SOS-08-B implementation) |
| Cocotb test paths | `tests/services/sos_<service>/` (created at SOS-08-B implementation) |
| SVA bind file paths | `rtl/services/sos_<service>_sva.sv` (created at SOS-08-B implementation) |

## 5. Frozen decisions

### 5.1 FreeRTOS / POSIX vocabulary mirror

The five L1 services SHALL use the FreeRTOS / POSIX vocabulary as their outward-facing verb set: `post` / `take` (mailbox), `set` / `wait` / `clear` (event group), `acquire` / `release` (resource pool), `tick` / `enable` (periodic task), `send` / `receive` (message channel). Renames are coordinated commits across this doc, the RTL, the cocotb tests, and the chart-emission tables in SOS-08-C.

Per the SOS-07 §7 row "FreeRTOS / POSIX vocabulary | mirror", the relationship is **mirror with no mutation rights**: SOS uses the vocabulary, not the API. The API surface (return codes, blocking semantics, timeout shape) is SOS-owned — it matches the chart-side syscall ABI from SOS-01 §5.3, NOT the upstream RTOS API.

Frozen-enumeration registration policy: **Standards Action** (changing the verb-set requires a §15 amendment here + a coordinated update to the chart's `ExternalEventName` enum and to SOS-08-C's emission tables).

### 5.2 "L1 composes L0 without modifying L0 behaviour" discipline

An L1 service SHALL instantiate L0 primitives and route signals among them; it SHALL NOT reach inside a primitive to modify its behaviour, gate its outputs in ways the primitive's SVA properties do not permit, or expose internal state of the primitive as part of the L1 interface. The L0 contract is the boundary; the L1 service either accepts the L0 primitive as-is or files a SOS-08-A §15 amendment to extend the primitive.

This discipline is the load-bearing reason the per-layer SVA composition is sound: the L1 SVA properties depend on the L0 SVA properties holding unmodified.

Frozen-enumeration registration policy: **Standards Action**.

### 5.3 Vendor-IP override pass-through

An L1 service SHALL inherit its constituent L0 primitives' vendor-IP shim parameters without re-interpretation. When a user builds with `-Dvendor=xilinx`, an `sos_mailbox` composed from `sos_fifo_sync` MUST transparently use the `xpm_fifo_sync`-shim variant of the FIFO; the chart-side code, the L1 interface, and the service-level SVA properties remain unchanged. The L1 service author MUST NOT introduce additional vendor selection at the L1 layer; vendor selection is L0-resident, full stop.

Frozen-enumeration registration policy: **Standards Action**.

### 5.4 Service-level SVA binding default

Per umbrella PCDN-SOS-08-007 resolution (full bind by default), each L1 service ships with a service-level SVA bind file that binds the service-level properties to every instance of the service module. Per-test scoping is opt-in for performance regressions only.

Frozen-enumeration registration policy: **Specification Required**.

## 6. Per-service contracts

### 6.1 `sos_mailbox`

#### Interface signature

```
module sos_mailbox #(
    parameter int WIDTH      = 32,    // message width in bits
    parameter int DEPTH      = 8,     // total slots across all priority lanes
    parameter int NUM_PRIO   = 1,     // number of priority lanes; see PCDN-SOS-08-B-001
    parameter int CROSS_CLK  = 0      // 0 = sync, 1 = async (selects L0 FIFO variant)
)(
    input  logic                       clk_p, rst_p,          // producer clock domain
    input  logic                       clk_c, rst_c,          // consumer clock domain (== clk_p if CROSS_CLK = 0)
    // producer side (ready/valid)
    input  logic                       post_valid,
    input  logic [$clog2(NUM_PRIO):0]  post_prio,
    input  logic [WIDTH-1:0]           post_msg,
    output logic                       post_ready,
    output logic [1:0]                 post_rc,               // 00 OK, 01 RC_FULL, 10 RC_INVAL
    // consumer side (req/ack — drained on take)
    input  logic                       take_req,
    output logic                       take_ack,
    output logic [WIDTH-1:0]           take_msg,
    output logic [$clog2(NUM_PRIO):0]  take_prio,
    // irq-on-non-empty
    output logic                       irq_non_empty
);
```

#### L0 composition

```
  +-- post_prio --+
  |               |
  v               v
 [lane-select MUX]
  |
  v
 NUM_PRIO × sos_fifo_sync     (or sos_fifo_async when CROSS_CLK=1)
  |     |     |
  |     |     +-- prio[NUM_PRIO-1] ---+
  |     +-- prio[1] ------------------+
  +-- prio[0] -----------------------+|
                                     vv
                          sos_arbiter_priority
                                     |
                                     v
                            consumer port (take)
```

The L1 service composes `NUM_PRIO` parallel `sos_fifo_sync` (or `sos_fifo_async` when `CROSS_CLK=1`) instances, one per priority lane, with `sos_arbiter_priority` (or `sos_arbiter_rr` when `NUM_PRIO=1`) selecting which lane the consumer drains from. The `irq_non_empty` signal is the OR of every lane's non-empty flag. `post_rc = RC_FULL` when the targeted lane's FIFO reports full; `post_rc = RC_INVAL` when `post_prio >= NUM_PRIO`.

#### Behavioural contract (chart-side mapping)

| L1 verb | Chart event (SOS-01 §5.3) | FreeRTOS API | POSIX API |
|---|---|---|---|
| `post(prio, msg)` | `queue.send` (with `prio` derived from chart datamodel) | `xQueueSend` (no priority); `xQueueSendToFront` (priority hint) | `mq_send` (msg + prio) |
| `take()` | `queue.receive` | `xQueueReceive` | `mq_receive` |
| `irq_non_empty` | drives a chart-internal event (chart-side ISR shim consumes) | task notification | signal |

The chart side authoring `queue.send` lowers via SOS-08-C to a `post` transaction on the L1 mailbox; `queue.receive` lowers to a `take` transaction; `queue.send_from_isr` (SOS-01 §5.3) lowers to a `post` on the ISR clock domain (using `CROSS_CLK=1` if the ISR runs on a different clock).

#### Service-level SVA

- `SVA-MBX-1` — **ordering within a priority lane**: every `post` accepted at lane `k` (i.e. `post_valid && post_ready && post_prio == k`) eventually appears at `take_msg` in FIFO order relative to other accepted posts at lane `k`.
- `SVA-MBX-2` — **priority dispatch**: when multiple lanes are non-empty, the next `take_ack` drains from the highest-priority non-empty lane (or by RR within a priority class for `sos_arbiter_rr` configurations).
- `SVA-MBX-3` — **no loss on full**: a `post_valid` with the targeted lane full asserts `post_rc == RC_FULL` and `post_ready == 0`; the message is NOT consumed.
- `SVA-MBX-4` — **no spurious irq**: `irq_non_empty` asserts iff at least one lane is non-empty.
- `SVA-MBX-5` — **invalid-prio rejection**: `post_valid && post_prio >= NUM_PRIO` asserts `post_rc == RC_INVAL` and `post_ready == 1` (one-cycle reject — no FIFO write).

#### Vector emission contract

- Cocotb test directory: `tests/services/sos_mailbox/`.
- Tests: ordering (per-lane FIFO), priority dispatch (multi-lane), full-condition rejection, IRQ assertion, cross-clock-domain variant (with `CROSS_CLK=1`).
- SVA bind file: `rtl/services/sos_mailbox_sva.sv`.
- Per INV-S-HDL-5, every test failure renders as `"mailbox post[prio=K, msg=M] expected at take[seq=N], observed at seq=N' — violates SVA-MBX-K"` — chart-vocabulary level, not raw RTL signal traces.

#### Vendor-IP override pass-through

`sos_mailbox` inherits the constituent FIFO's vendor-IP shim selection transparently. `-Dvendor=xilinx` causes the inner `sos_fifo_sync`/`sos_fifo_async` instances to compile against `xpm_fifo_sync`/`xpm_fifo_async`; the arbiter and lane-select logic remain portable RTL.

### 6.2 `sos_event_group`

#### Interface signature

```
module sos_event_group #(
    parameter int N_BITS = 32     // event-flag count; see PCDN-SOS-08-B-002
)(
    input  logic                  clk, rst,
    // strobe-set side (per-bit)
    input  logic [N_BITS-1:0]     set_strobe,    // one-cycle pulse per bit to assert
    // wait side
    input  logic                  wait_valid,
    input  logic [N_BITS-1:0]     wait_mask,     // bits to wait on
    input  logic                  wait_all,      // 0 = wait-any, 1 = wait-all
    input  logic                  wait_clear,    // clear matched bits on satisfy
    output logic                  wait_ack,
    output logic [N_BITS-1:0]     wait_bits,     // observed bits at satisfy
    // probe (non-blocking read)
    output logic [N_BITS-1:0]     current_bits
);
```

#### L0 composition

```
  set_strobe[0]  --> sos_strobe_latch[0]  --> latched[0]
  set_strobe[1]  --> sos_strobe_latch[1]  --> latched[1]
   ...
  set_strobe[N-1]--> sos_strobe_latch[N-1]--> latched[N-1]
                                                  |
                                                  v
                            (AND-mask + reduce-OR for wait-any /
                             AND-mask + reduce-AND for wait-all)
                                                  |
                                                  v
                                             match signal --> wait_ack
                                                  |
                                                  +-- wait_clear ? clear matched bits in latches
```

Each event bit is realised by one `sos_strobe_latch` (pulse-to-level + ack). The wait-side combinational logic computes `wait_mask & latched_bits`, reduces by OR (any) or AND-equal-mask (all), and pulses `wait_ack` when the predicate is satisfied. `wait_clear` routes back to the per-bit latch ack inputs to clear only the matched bits. `sos_arbiter_rr` is NOT instantiated at the service level for v1 — the wait side is single-consumer; multi-consumer wait MAY land as a later amendment.

#### Behavioural contract (chart-side mapping)

| L1 verb | Chart event (proposed; not in SOS-01 §5.3 today) | FreeRTOS API | POSIX API |
|---|---|---|---|
| `set(bits)` (strobed bits) | `event.set` (proposed §15 amendment) | `xEventGroupSetBits` | `pthread_kill` (per-signal) |
| `wait(mask, all, clear)` | `event.wait` (proposed §15 amendment) | `xEventGroupWaitBits` | `sigwait` |
| `current_bits` (probe) | `event.peek` (proposed §15 amendment) | `xEventGroupGetBits` | `sigpending` |

The chart-side events `event.set` / `event.wait` / `event.peek` are NOT yet in `ExternalEventName` (SOS-01 §5.3). Their addition is gated on PCDN-SOS-08-B-002 resolution + a coordinated SOS-01 §15 amendment + a chart edit to `rtos_kernel.scxml` (or to a successor application chart that exercises event groups). The L1 service contract exists ahead of the chart-side vocabulary as a forward declaration of the HDL realisation.

#### Service-level SVA

- `SVA-EVG-1` — **strobe-eventually-latched**: every cycle where `set_strobe[k]` is asserted, `latched[k]` becomes 1 within one clock cycle and remains 1 until cleared.
- `SVA-EVG-2` — **wait-any correctness**: with `wait_valid && !wait_all`, `wait_ack` asserts iff `(latched & wait_mask) != 0`; `wait_bits == latched & wait_mask` at the satisfying cycle.
- `SVA-EVG-3` — **wait-all correctness**: with `wait_valid && wait_all`, `wait_ack` asserts iff `(latched & wait_mask) == wait_mask`.
- `SVA-EVG-4` — **clear-on-satisfy atomicity**: with `wait_clear` set and `wait_ack` asserted, exactly the bits in `wait_bits` clear from `latched` on the following cycle; bits outside `wait_bits` are unaffected.
- `SVA-EVG-5` — **probe non-disturbance**: reading `current_bits` does NOT clear, set, or modify `latched`.

#### Vector emission contract

- Cocotb test directory: `tests/services/sos_event_group/`.
- Tests: per-bit set + latch; wait-any single-bit; wait-any multi-bit; wait-all; clear-on-read atomicity; concurrent set + wait; probe non-disturbance.
- SVA bind file: `rtl/services/sos_event_group_sva.sv`.
- Failure-message rendering per INV-S-HDL-5.

#### Vendor-IP override pass-through

`sos_event_group` uses no vendor-IP-eligible L0 primitive (`sos_strobe_latch` is portable-only by design; no vendor shim is planned). The pass-through rule still applies trivially: there is no vendor selection to inherit.

### 6.3 `sos_resource_pool`

#### Interface signature

```
module sos_resource_pool #(
    parameter int ID_WIDTH  = 16,   // see PCDN-SOS-08-B-003
    parameter int POOL_SIZE = 16    // total static resources
)(
    input  logic                       clk, rst,
    // acquire side (req/ack)
    input  logic                       acquire_req,
    output logic                       acquire_ack,
    output logic [ID_WIDTH-1:0]        acquire_id,
    output logic [1:0]                 acquire_rc,    // 00 OK, 01 RC_FULL (exhausted)
    // release side (ready/valid)
    input  logic                       release_valid,
    input  logic [ID_WIDTH-1:0]        release_id,
    output logic                       release_ready,
    output logic [1:0]                 release_rc,    // 00 OK, 10 RC_INVAL (id not currently acquired)
    // probe
    output logic [$clog2(POOL_SIZE):0] free_count
);
```

#### L0 composition

```
  reset:        sos_fifo_sync ← initialise with IDs [0 .. POOL_SIZE-1]
                                  (refill at boot via control-path counter)
  acquire_req:  sos_fifo_sync.dequeue → acquire_id (next free ID)
  release:      sos_fifo_sync.enqueue ← release_id
  acquire_rc:   = RC_FULL when sos_fifo_sync.empty (pool exhausted)
  release_rc:   = RC_INVAL when an out-of-band tracker says release_id was not acquired
```

A `sos_fifo_sync` of `ID_WIDTH`-wide entries, initialised at reset with the full set of pool IDs `[0, 1, ..., POOL_SIZE-1]` via a one-shot refill controller (driven at startup; visible only via the `free_count` probe afterwards). `acquire` dequeues an ID; `release` enqueues an ID back. An auxiliary tracker (a bit-vector of `POOL_SIZE` bits, one per ID) records "currently acquired" status to enforce SVA-POOL-2 (double-free detection); the tracker is a service-level register-set, NOT exposed at the interface.

#### Behavioural contract (chart-side mapping)

| L1 verb | Chart event (SOS-01 §5.3) | FreeRTOS API | POSIX API |
|---|---|---|---|
| `acquire()` | `task.create` (allocates TCB slot from `TCB_POOL`) | `xTaskCreateStatic` | n/a (static-only) |
| `acquire()` | `sem.create` (allocates `SEM_POOL` handle) | `xSemaphoreCreateStaticBinary` | n/a |
| `acquire()` | `queue.create` (allocates `QUEUE_POOL` handle) | `xQueueCreateStatic` | n/a |
| `release(id)` | (no chart event today; future `task.delete` / `sem.delete` / `queue.delete`) | `vTaskDelete` / static-pool free | n/a |
| `free_count` (probe) | chart-internal datamodel state | available-handles count | n/a |

Per SOS-04 / SOS-05, the chart-side `TCB_POOL` / `SEM_POOL` / `QUEUE_POOL` allocations are static and never freed; the resource pool's `release` path is currently exercised only at chart teardown (boot test) and as a future extensibility hook. The SVA properties still enforce correctness on the release path so that future chart events MAY exercise it without regression risk.

#### Service-level SVA

- `SVA-POOL-1` — **acquired-once**: between two consecutive `acquire_ack` cycles returning the same `acquire_id`, exactly one `release_valid && release_ready` with `release_id == acquire_id` MUST occur.
- `SVA-POOL-2` — **no double-free**: `release_valid && release_id == k` with `tracker[k] == 0` (not currently acquired) asserts `release_rc == RC_INVAL` and `release_ready == 1` (one-cycle reject — no FIFO write).
- `SVA-POOL-3` — **exhaustion**: `acquire_req` with `free_count == 0` asserts `acquire_rc == RC_FULL` and `acquire_ack == 0`.
- `SVA-POOL-4` — **conservation**: `free_count + popcount(tracker) == POOL_SIZE` at every cycle after reset is complete.
- `SVA-POOL-5` — **reset re-initialises**: after `rst` deasserts, `free_count` reaches `POOL_SIZE` within `POOL_SIZE + 1` cycles (the refill controller's bound).

#### Vector emission contract

- Cocotb test directory: `tests/services/sos_resource_pool/`.
- Tests: acquire-all-then-release-all conservation; double-free detection; exhaustion handling; release-without-acquire (SVA-POOL-2); reset re-initialisation.
- SVA bind file: `rtl/services/sos_resource_pool_sva.sv`.
- Failure-message rendering per INV-S-HDL-5.

#### Vendor-IP override pass-through

`sos_resource_pool` inherits the inner `sos_fifo_sync`'s vendor-IP shim selection transparently. The tracker bit-vector is portable-only (a register file).

### 6.4 `sos_periodic_task`

#### Interface signature

```
module sos_periodic_task #(
    parameter int TICK_DIV = 1     // base tick / TICK_DIV = task tick rate
)(
    input  logic        clk, rst,
    input  logic        base_tick,         // upstream tick from sos_tick_gen
    // FSM enable
    output logic        task_enable,       // one-cycle pulse on each task tick
    input  logic        task_busy,         // FSM asserts when working
    // overrun detection
    output logic        overrun            // asserts iff task_busy still 1 at next tick
);
```

#### L0 composition

```
  base_tick --> sos_rate_divider(TICK_DIV) --> task_tick
                                                   |
                                                   v
                                               task_enable (pulse)
                                                   |
                                          +--------+--------+
                                          |                 |
                                          v                 v
                                       FSM enable     overrun-detector
                                                        (latches if
                                                         task_busy at
                                                         next task_tick)
```

A single `sos_rate_divider` consumes the upstream `base_tick` (sourced from a system-level `sos_tick_gen` per PCDN-SOS-08-B-004 resolution — see §11) and emits `task_tick` at the divided rate. `task_enable` pulses on each `task_tick`; the overrun detector latches a fault if `task_busy` is still asserted at the next `task_tick`. The overrun output is a sticky fault; clearing requires reset.

#### Behavioural contract (chart-side mapping)

| L1 verb | Chart event (SOS-01 §5.3) | FreeRTOS API | POSIX API |
|---|---|---|---|
| `task_enable` pulse | `sys.tick` (chart-internal at v1; SOS-01 §5.3) | `xTaskCreatePeriodic` body entry | `timer_create` + signal handler |
| `task_busy` (input from FSM) | chart-region `inProgress` state | `vTaskGetTaskInfo` running flag | n/a |
| `overrun` (sticky) | proposed chart event `task.overrun` (future §15 amendment) | `vApplicationStackOverflowHook` semantic analog | `SIGXCPU` |

Per SOS-04 / SOS-05, the chart-side `sys.tick` event is the macrostep tick; `sos_periodic_task` is the hardware-side scaffolding that turns a hardware tick source into FSM enables. A chart region modelled as a periodic task lowers (via SOS-08-C) to an FSM whose enable signal is the `task_enable` output of an `sos_periodic_task` instance.

#### Service-level SVA

- `SVA-PT-1` — **tick periodicity**: `task_tick` asserts every `TICK_DIV` cycles of `base_tick` (within one base-tick cycle of jitter at reset).
- `SVA-PT-2` — **enable arrives once per tick**: each `task_tick` pulse produces exactly one `task_enable` pulse on the next cycle.
- `SVA-PT-3` — **overrun detection**: if `task_busy` is high at a `task_tick` boundary, `overrun` latches high and remains until reset.
- `SVA-PT-4` — **enable masked under overrun (optional)**: under `overrun == 1`, the implementation MAY suppress further `task_enable` pulses; the chart annotation declares which mode applies. (Default: pulses continue; the FSM observes both `task_busy` and `overrun`.)
- `SVA-PT-5` — **base-tick monotonic**: `task_tick` count is monotonic non-decreasing across non-reset cycles.

The bound-analysis assertion that the FSM completes its work before the next tick is NOT in the per-instance SVA — it is a chart-compile-time check (the FSM's bounded-reachability against the task period). Bound-analysis fires at chart compile, NOT at simulation; the SVA fires on overrun detection at runtime.

#### Vector emission contract

- Cocotb test directory: `tests/services/sos_periodic_task/`.
- Tests: tick periodicity at `TICK_DIV ∈ {1, 2, 8, 100}`; overrun detection (FSM that holds `task_busy` past the next tick); reset clears overrun.
- SVA bind file: `rtl/services/sos_periodic_task_sva.sv`.
- Failure-message rendering per INV-S-HDL-5.

#### Vendor-IP override pass-through

`sos_periodic_task` uses no vendor-IP-eligible L0 primitive (`sos_rate_divider` is portable-only).

### 6.5 `sos_message_channel`

#### Interface signature

```
module sos_message_channel #(
    parameter int EVENT_ID_WIDTH = 16,    // chart ExternalEventName index width
    parameter int PAYLOAD_WIDTH  = 64,    // see PCDN-SOS-08-B-005
    parameter int DEPTH          = 8
)(
    input  logic                       clk_tx, rst_tx,
    input  logic                       clk_rx, rst_rx,
    // send (ready/valid)
    input  logic                       send_valid,
    input  logic [EVENT_ID_WIDTH-1:0]  send_event_id,
    input  logic [PAYLOAD_WIDTH-1:0]   send_payload,
    output logic                       send_ready,
    output logic [1:0]                 send_rc,    // 00 OK, 01 RC_FULL
    // receive (ready/valid)
    input  logic                       recv_ready,
    output logic                       recv_valid,
    output logic [EVENT_ID_WIDTH-1:0]  recv_event_id,
    output logic [PAYLOAD_WIDTH-1:0]   recv_payload
);
```

#### L0 composition

```
  (clk_tx domain)                              (clk_rx domain)
  send_event_id ----+                          +---> recv_event_id
  send_payload  ----+--> {payload, event_id} --+---> recv_payload
                    |                          |
                    v                          ^
                 sos_fifo_async (Gray pointers, 2-FF sync per pointer)
                    |                          |
                 send_ready                 recv_valid
```

The send-side packs `{send_event_id, send_payload}` into one wide word and writes it as a single FIFO entry; the CDC handshake of `sos_fifo_async` guarantees that the packed word arrives atomically on the receive side (no torn writes — the CDC handshake's stipulated property per SOS-08-A `sos_fifo_async` contract). The receive side unpacks. `send_rc == RC_FULL` on FIFO full.

#### Behavioural contract (chart-side mapping)

| L1 verb | Chart event (SOS-01 §5.3) | FreeRTOS API | POSIX API |
|---|---|---|---|
| `send(event_id, payload)` | any `ExternalEventName` from §5.3 (sent across a clock-domain boundary) | `xStreamBufferSendFromISR` | named-pipe `write` |
| `receive()` | drives chart-internal event-dispatch on the receive clock domain | `xStreamBufferReceive` | named-pipe `read` |
| `recv_event_id` | one of the 18 ratified `ExternalEventName` indices | event-type tag | message header |

The `event_id` encoding maps directly to the SOS-01 §5.3 `ExternalEventName` enum's stable index (per the enum's append-only-with-deprecation policy, INV-S-LINT-3). Adding a new event to §5.3 widens `EVENT_ID_WIDTH` only if the enum exceeds the current width; pruning is by deprecation, never by index reuse.

#### Service-level SVA

- `SVA-MSGCH-1` — **CDC atomicity**: every `send_valid && send_ready` produces exactly one `recv_valid` with matching `{event_id, payload}`; no torn writes (the packed word arrives intact).
- `SVA-MSGCH-2` — **ordering preserved across CDC**: messages emerge from the receive side in the same order they entered the send side.
- `SVA-MSGCH-3` — **no loss on full**: `send_valid` with FIFO full asserts `send_rc == RC_FULL` and `send_ready == 0`; the message is NOT consumed.
- `SVA-MSGCH-4` — **event-id within enum**: `send_event_id` MUST be a valid index into `ExternalEventName` (SOS-01 §5.3); chart-emission ensures this at compile time, and the SVA asserts it at runtime as a defence-in-depth check.
- `SVA-MSGCH-5` — **bounded latency** (informative; not formally proved): under stable producer / consumer rates within the FIFO's depth budget, `recv_valid` follows `send_valid` within a bounded number of cycles (the CDC handshake's worst-case latency, documented per `sos_fifo_async` contract).

#### Vector emission contract

- Cocotb test directory: `tests/services/sos_message_channel/`.
- Tests: send-receive round-trip; full-condition rejection; ordering across CDC; invalid event-id rejection; bounded-latency probe (under nominal load).
- SVA bind file: `rtl/services/sos_message_channel_sva.sv`.
- Failure-message rendering per INV-S-HDL-5; failures cite the chart-side `ExternalEventName` whose dispatch produced the failing vector.

#### Vendor-IP override pass-through

`sos_message_channel` inherits the inner `sos_fifo_async`'s vendor-IP shim selection transparently (e.g. `xpm_fifo_async` under `-Dvendor=xilinx`).

## 7. Cross-service invariants

In addition to INV-SOS-A through H (SOS-07) and INV-S-HDL-1 through 5 (SOS-08), the following invariants are normative across SOS-08-B:

- **INV-S-HDL-B-1 — Vocabulary mirror discipline.** Every L1 service's outward verb set SHALL be expressible in the FreeRTOS / POSIX vocabulary (per §5.1). New verbs require a §15 amendment here + a chart-side `ExternalEventName` amendment in SOS-01 §5.3.

- **INV-S-HDL-B-2 — L0 non-modification.** L1 services compose L0 primitives without modifying L0 behaviour (per §5.2). L0 contract is the boundary; L1 either accepts or files a SOS-08-A amendment.

- **INV-S-HDL-B-3 — Service-level SVA on every L1 instance.** Every L1 service module ships with a service-level SVA bind file binding to every instance (per §5.4, PCDN-SOS-08-007 resolution).

- **INV-S-HDL-B-4 — Vendor-IP pass-through.** L1 services inherit L0 vendor-IP shim parameters transparently; the chart side does not select vendor backends (per §5.3).

- **INV-S-HDL-B-5 — Chart-vocabulary failure rendering.** Every L1 service-level cocotb test or SVA failure renders in chart vocabulary (per INV-SOS-H + INV-S-HDL-5); a failure that references only RTL signals is a verification-emission bug, not a passing test.

## 8. Standards integration matrix additions

The following rows EXTEND the SOS-07 §7 and SOS-08 §8 matrix. Per INV-SOS-E.

| Concept | Upstream authority | Local relationship | Phase that declares it | Mutation rights |
|---|---|---|---|---|
| FreeRTOS API verb set | open implementation (FreeRTOS LLC) | **mirror** (vocabulary only; the API surface itself is SOS-owned per chart-syscall ABI) | SOS-08-B | none — locally |
| POSIX threads + IPC verb set | IEEE Std 1003.1-2017 | **mirror** (vocabulary only) | SOS-08-B | none |
| SVA service-level property idioms (`bind`, `property`, `sequence`) | IEEE 1800-2017 §16 | **derive** | SOS-08-B | none — emit conformant subset |
| Cocotb service-level testbench idioms (`@cocotb.test`, ReadyValidDriver, ReadyValidMonitor) | cocotb project | **derive** | SOS-08-B | none |

## 9. Frozen enumerations from SOS-08-B

This phase freezes one enumeration:

### 9.1 L1 service set

`{ sos_mailbox, sos_event_group, sos_resource_pool, sos_periodic_task, sos_message_channel }`

Registration policy: **Standards Action**. Adding a sixth L1 service requires a §15 amendment here + cross-phase review (the L1 vocabulary is the chart-author-facing surface; new verbs change the chart's `ExternalEventName` contract).

## 10. Reconciliation decisions vs adjacent repo primitives

### vs. SOS-04 (Rust port) `TCB_POOL` / `SEM_POOL` / `QUEUE_POOL`

The chart-side `TCB_POOL`, `SEM_POOL`, `QUEUE_POOL` static allocations in `ports/m7-rust/src/kernel.rs` (per SOS-04 §6) are the software-side analog of `sos_resource_pool`. Both realise the same chart-side concept (static-only resource allocation discharging INV-SOS-G's bounded-resource claim); the HDL realisation uses a `sos_fifo_sync` of IDs whereas the software realisation uses a `heapless::Vec<TCB, MAX_TASKS>` indexed by ID. The chart-side syscall vocabulary is identical: `task.create` / `sem.create` / `queue.create` lower to `acquire` on either backend.

### vs. SOS-05 (C port) static-pool macros

Same as SOS-04, modulo language. The C port's `TCB_POOL[]` array + free-list head pointer + bitfield tracker are the software analog of `sos_resource_pool`'s composition. No chart-side semantic difference.

### vs. SOS-01 §5.3 `ExternalEventName`

The L1 verb sets in §6.1–6.5 are NOT a re-derivation of SOS-01 §5.3; they are the HDL realisation of the same vocabulary. Where this doc names a chart event NOT currently in SOS-01 §5.3 (`event.set` / `event.wait` / `event.peek` / `task.overrun`), the entry is **proposed** and gated on a future SOS-01 §15 amendment. Implementing those L1 services without first amending §5.3 produces an unreachable code path (no chart event ever lowers to the service); the implementation MAY proceed for L0/L1 verification purposes, but chart-side exercise requires the §5.3 amendment.

### vs. SOS-08 §6 service-set sketch

This doc's §6.1–6.5 ratify the service contracts that SOS-08 §6 (umbrella, SOS-08-B row) sketched informatively. The five services and their L0 compositions are unchanged from the sketch; this doc adds interface signatures, SVA property sets, and vector-emission contracts.

### vs. INV-S-HDL-2 (static-allocation discipline)

`sos_resource_pool` is the canonical realisation of INV-S-HDL-2 for the chart-side dynamic-allocation analogs (`task.create`, `sem.create`, `queue.create`). Every chart event that the software-side syscall ABI would name "create" or "allocate" lowers to `sos_resource_pool::acquire` on the HDL backend.

### vs. INV-S-HDL-3 (cross-domain isolation)

`sos_mailbox` (with `CROSS_CLK=1`) and `sos_message_channel` are the canonical realisations of INV-S-HDL-3 for the chart-side cross-clock-domain analogs. Every chart-side `queue.send_from_isr` (SOS-01 §5.3) where the ISR runs on a different clock from the receiving task lowers to one of these services.

## 11. Non-goals

This phase does NOT:

- Author L0 primitive contracts. SOS-08-A is the authoritative artifact for those; this doc cites L0 primitives by name and trusts their contracts as ratified there.
- Define a sixth L1 service. The five named services are sufficient for the chart-side vocabulary today; adding a service is a §15 amendment.
- Specify the FSM emission strategy for L2 tasks. That is SOS-08-C's responsibility.
- Specify the cocotb testbench framework details. SOS-08-D ratifies the framework; this doc specifies which tests live where and what they assert.
- Specify the SVA bind file syntax. SOS-08-D ratifies the binding mechanism; this doc specifies which properties to bind.
- Resolve PCDN-SOS-08-B-004 (global vs per-task tick). The §6.4 contract is written against the global-tick assumption (one `sos_tick_gen` per system, fanout downstream via per-task `sos_rate_divider`); per-task tick generation lands only if PCDN-SOS-08-B-004 resolves that way.
- Bench-validate the L1 services. Bench validation is the umbrella SOS-08 acceptance gate (a Lattice ECP5 worked example); per-service bench validation is the implementation-cycle artifact, not this phase doc.

## 12. Acceptance checklist

A conforming SOS-08-B ratification satisfies all of:

- (a) ✅ PCDN-SOS-08-B-001 through 006 (§14) resolved — see §15 2026-05-23 ratification entry.
- (b) ⏸ Each of the five services (`sos_mailbox`, `sos_event_group`, `sos_resource_pool`, `sos_periodic_task`, `sos_message_channel`) has its §6 subsection ratified: interface signature, L0 composition, behavioural contract, SVA property set, vector-emission contract, vendor-IP pass-through.
- (c) ⏸ Cross-service invariants INV-S-HDL-B-1 through 5 in §7 ratified.
- (d) ⏸ Standards integration matrix additions in §8 ratified (4 rows).
- (e) ⏸ Reconciliation §10 records the relationship to SOS-04 / SOS-05 static pools and to SOS-01 §5.3 vocabulary.
- (f) ⏸ Each service's RTL files exist at `rtl/services/sos_<service>.{vhd,sv}` (created at implementation cycle; this checklist gate fires at the implementation PR, not this doc's ratification).
- (g) ⏸ Each service's cocotb test directory exists at `tests/services/sos_<service>/` with at least one passing test per SVA property (implementation-cycle gate).
- (h) ⏸ Each service's SVA bind file exists at `rtl/services/sos_<service>_sva.sv` (implementation-cycle gate).
- (i) ⏸ Bench-verifiable on the Lattice ECP5 worked-example target (per umbrella SOS-08 §12 (e)): the worked-example chart uses at least `sos_mailbox` + `sos_resource_pool` + `sos_periodic_task` and the bitstream's behaviour against the cocotb tests passes via Verilator-observed signal traces.

## 13. Files cited

| Path | Role |
|---|---|
| `docs/concepts/SOS-08-CONCEPTS.md` | Umbrella; §6 outline, §7 INV-S-HDL-1 through 5, §8 standards matrix. |
| `docs/concepts/SOS-08-A-CONCEPTS.md` | Parallel-authored L0 primitive contracts; cited by primitive name. |
| `docs/concepts/SOS-08-C-CONCEPTS.md` | Future sub-phase; chart → FSM emission consumes this doc's L1 verb set. |
| `docs/concepts/SOS-08-D-CONCEPTS.md` | Future sub-phase; cocotb + SVA bind framework consumes this doc's per-service tests + binds. |
| `docs/concepts/SOS-07-CONCEPTS.md` | Cross-phase invariants INV-SOS-A through H; AuthorityRelationship matrix. |
| `docs/concepts/SOS-04-CONCEPTS.md` | Rust port; `TCB_POOL` / `SEM_POOL` / `QUEUE_POOL` static allocations §10 reconciles against. |
| `docs/concepts/SOS-05-CONCEPTS.md` | C port; same static pools, language-mirrored. |
| `docs/concepts/SOS-01-CONCEPTS.md` | §5.3 `ExternalEventName` — the chart-side vocabulary the L1 verb set mirrors. |
| `rtos_kernel.scxml` | Bootstrap kernel chart; the worked-example source for HDL emission. |
| Parent `CLAUDE.md` | Spec-Before-Code discipline; AuthorityRelationship enum. |

## 14. Pending Concept Decision Notices (PCDNs)

These open questions move this doc from 🟡 drafted to 🟢 ratified.

- **PCDN-SOS-08-B-001 — Priority levels for `sos_mailbox`.** Fix `NUM_PRIO` at 8 (matching the chart's `MAX_PRIO` per SOS-00 / SOS-04 datamodel), fix it at the FreeRTOS default of `configMAX_PRIORITIES` (typically 32 — but FreeRTOS does NOT have priority-queues natively; this is the priority-task analog), or expose it as a build-time parameter? **Recommendation**: parameterised with default 8 (matches chart `MAX_PRIO`); chart-emission MAY override per-mailbox if the chart's region declares a smaller lane count. The synthesis-time area cost is `NUM_PRIO × DEPTH` FIFO entries + an `NUM_PRIO`-input priority arbiter; 8 is a tractable default for ECP5-class targets.

- **PCDN-SOS-08-B-002 — Event-group bit count.** Fix `N_BITS` at 32 (matching the chart's `i32` datamodel word), at 8 (matching FreeRTOS's `EventBits_t` historical default — but FreeRTOS now defaults to 24 effective bits), or parameterise? **Recommendation**: parameterised with default 32 (chart datamodel word width); per-region override via chart annotation. The synthesis-time cost is `N_BITS × sos_strobe_latch` instances; 32 is well within ECP5 budget. Coupled question: does the chart-side `event.set` / `event.wait` payload encode the bit-mask as a 32-bit `i32` directly, or as a separate `bit_index` + `value` shape? — answer falls out of the SOS-01 §15 amendment that adds the events.

- **PCDN-SOS-08-B-003 — Resource-pool ID type width.** Use the chart's `task_id` width (the SOS-04 / SOS-05 `i16` per `TCB[MAX_TASKS]`), use a generic 32-bit, or parameterise? **Recommendation**: parameterised with default 16 bits (matches chart's `task_id`); chart-emission selects per-pool width based on `MAX_TASKS` / `MAX_SEMS` / `MAX_QUEUES`. Synthesis-time impact is negligible; consistency with the chart datamodel is the main win.

- **PCDN-SOS-08-B-004 — Periodic-task tick source.** One global `sos_tick_gen` per system with per-task `sos_rate_divider` fanout, OR independent `sos_rate_divider` per task fed from its own `sos_tick_gen`? **Recommendation**: one global `sos_tick_gen` per system; per-task `sos_rate_divider` for sub-rates. This matches the chart-side macrostep model (one `sys.tick` cadence for the whole chart, regions opt into slower-than-base rates via per-region annotation). Multi-clock-domain charts (per umbrella PCDN-SOS-08-010 resolution) get one `sos_tick_gen` per clock domain.

- **PCDN-SOS-08-B-005 — Message-channel metadata struct.** Chart-derived (the metadata struct's shape comes from the specific `ExternalEventName` being dispatched, with one packed-struct variant per event ID — a tagged union encoded as `{event_id, packed_payload}`), OR generic (a fixed `{id, payload_bytes}` shape with the chart-side decoder unpacking on receive)? **Recommendation**: generic (`{event_id, payload[PAYLOAD_WIDTH]}`) with `PAYLOAD_WIDTH` parameterised — set to the maximum chart-event payload width at chart-compile time. Chart emission packs and unpacks at the L1 boundary; the L1 service itself is event-shape-agnostic. This keeps the L1 service universal and pushes the per-event encoding into SOS-08-C's emission contract.

- **PCDN-SOS-08-B-006 — IRQ-on-non-empty mechanism for `sos_mailbox`.** Level-sensitive (`irq_non_empty == 1` while any lane is non-empty), edge-triggered (one-cycle pulse on transition from empty-to-non-empty per lane, requiring an external latch to be useful), or both (separate level + edge outputs)? **Recommendation**: level-sensitive only at v1 (simpler; matches the chart-side ISR shim's polling-or-blocked semantics). Edge-triggered MAY land as an addition later if a customer use case demands it.

## 15. Change log

### 2026-05-23 — Initial draft (Ira)

- Authored `SOS-08-B-CONCEPTS.md` as the per-sub-phase concept doc for L1 service composition under the SOS-08 umbrella.
- Five services ratified §6: `sos_mailbox` (§6.1), `sos_event_group` (§6.2), `sos_resource_pool` (§6.3), `sos_periodic_task` (§6.4), `sos_message_channel` (§6.5). Each carries interface signature + L0 composition diagram + behavioural contract (chart-syscall mapping) + service-level SVA property set + vector-emission contract + vendor-IP pass-through.
- Frozen decisions §5: FreeRTOS / POSIX vocabulary mirror (§5.1); L1-composes-L0-without-modification discipline (§5.2); vendor-IP override pass-through (§5.3); service-level SVA binding default (§5.4).
- Cross-service invariants §7: INV-S-HDL-B-1 through 5.
- Standards integration matrix §8 adds 4 rows (FreeRTOS / POSIX vocabulary, SVA service-level idioms, cocotb service-level idioms).
- Reconciliation §10 names the relationship to SOS-04 / SOS-05 static pools, to SOS-01 §5.3 `ExternalEventName`, and to INV-S-HDL-2 / INV-S-HDL-3.
- 6 PCDNs raised covering the per-service parameter defaults that need user input before implementation cycles begin.

Status: 🟡 **drafted**, awaiting PCDN walkthrough.

### 2026-05-23 — Ratified after PCDN walkthrough (Ira)

All six PCDNs from §14 resolved. Five recommendations accepted; PCDN-005 resolved to the user-chosen variant (chart-derived metadata struct) over the doc-recommended generic shape.

- **PCDN-SOS-08-B-001 → RESOLVED (recommendation accepted)**: `NUM_PRIO` parameterised with default 8 (matches chart `MAX_PRIO`); chart-emission MAY override per-mailbox when the chart region declares a smaller lane count.
- **PCDN-SOS-08-B-002 → RESOLVED (recommendation accepted)**: `N_BITS` parameterised with default 32 (chart datamodel `i32` width); per-region override via chart annotation. Coupled SOS-01 §15 amendment adding `event.set` / `event.wait` / `event.peek` to `ExternalEventName` lands when the first chart that exercises events gets authored.
- **PCDN-SOS-08-B-003 → RESOLVED (recommendation accepted)**: `ID_WIDTH` parameterised with default 16 bits (matches chart `task_id`); chart-emission per-pool selects width from `MAX_TASKS` / `MAX_SEMS` / `MAX_QUEUES`.
- **PCDN-SOS-08-B-004 → RESOLVED (recommendation accepted)**: one global `sos_tick_gen` per system; per-task `sos_rate_divider` for sub-rates. Multi-clock-domain charts (per umbrella PCDN-SOS-08-010) get one `sos_tick_gen` per clock domain.
- **PCDN-SOS-08-B-005 → RESOLVED (user-chosen variant)**: **chart-derived** metadata struct, one packed-struct variant per `ExternalEventName` ID encoded as a tagged union (`{event_id, packed_payload_variant}`). Diverges from doc-recommendation "generic `{event_id, payload[PAYLOAD_WIDTH]}` with chart-side encode/decode at the L1 boundary" — the user-chosen variant pushes type-safety into the HDL boundary itself, matching the typed-event story across SOS-01 §5.3 + SOS-12 contract surface. INV-S-HDL-B-2 amended accordingly: `sos_message_channel` is **chart-event-shape-aware** at chart-compile time, with per-event-name packed-struct variants emitted by SOS-08-C. The L1 service module itself remains structurally uniform; the per-event encoding lands as the metadata-struct variant generated by SOS-08-C, not as a SOS-08-B-side adapter.
- **PCDN-SOS-08-B-006 → RESOLVED (recommendation accepted)**: level-sensitive `irq_non_empty` only at v1. Edge-triggered variant deferred to future PCDN if a customer use case demands it.

**§7 / INV amendments**:
- INV-S-HDL-B-2 wording extended: "L1 services compose L0 primitives without modifying L0 behaviour; `sos_message_channel` is chart-event-shape-aware via SOS-08-C-emitted per-event packed-struct variants (PCDN-B-005), all other L1 services remain chart-vocabulary-agnostic at the module level."
- §6.5 `sos_message_channel` interface updated: `payload` field becomes a `union packed` of per-event-name variants emitted by SOS-08-C; the `event_id` field selects the active variant. SOS-08-C ratification depends on the per-event packing emission contract.

**Status**: 🟢 **ratified**. SOS-08-C ratification gate (chart→FSM emission) now has a frozen L1 service surface to emit against. SOS-09 (HW/SW membrane) gate that cited SOS-08-B as prerequisite is now unblocked.

### 2026-05-23 — Impl wave-1 PCDN amendments (Ira)

Wave-1 implementation of all five L1 services surfaced 17 sub-PCDNs across §6.1–§6.5 + §7 cross-service surface. Eight resolved by user walkthrough; nine ratified at agent-default per spec-before-code §3 source-of-truth doctrine (each named below with the rationale anchor). All folded into the SOS-08-B normative surface at this entry; per-section prose amendments recorded by reference below.

**User-resolved sub-PCDNs:**

- **PCDN-B-mailbox-sideband-width** (§6.1) — RESOLVED. Sideband width for `s_axis_tprio` / `take_prio` is `[$clog2(NUM_PRIO)-1:0]` (corrected from §6.1 prose which prints `[$clog2(NUM_PRIO):0]`). Wave-1 impl uses the corrected form. §6.1 prose stays as-is; this §15 entry is canonical.

- **PCDN-B-mailbox-post_rc-collapse** (§6.1) — RESOLVED. Spec body §6.1 `post_rc[1:0]` 2-bit bus (OK / RC_FULL / RC_INVAL) is WITHDRAWN. Canonical surface is AXI-Stream backpressure: `RC_FULL` encoded via `s_axis_tready=0` on the targeted lane; `RC_INVAL` encoded via `s_axis_tready=0` when `s_axis_tprio >= NUM_PRIO` (verified by SVA `a_no_tready_when_tprio_oor`). Chart compiler maps event semantics to AXI-Stream backpressure; no separate sideband return-code bus.

- **PCDN-B-mailbox-CROSS_CLK-deferred** (§6.1) — RESOLVED (deferred). `CROSS_CLK` generic + `sos_fifo_async` dual-clock variant DEFERRED to a future §15 amendment. v1 ships single-clock-only composing `sos_fifo_sync`. When a customer needs cross-domain mailbox, the variant lands (likely as `MODE = SINGLE_CLOCK | DUAL_CLOCK` mirroring the sos_dpram_arb pattern). Counts as a future named exception in INV-S-HDL-A-5 if/when added.

- **PCDN-B-mailbox-lane-priority** (§6.1) — RESOLVED. Lane-index priority convention: **higher lane index = higher priority**. Matches sos_arbiter_priority's "higher-value-wins" §6.4 convention. Chart-side mapping: `HIGH_PRIORITY = lane (NUM_PRIO-1)`; `LOW_PRIORITY = lane 0`. NOTE: this diverges from FreeRTOS's "priority 0 = highest" convention; chart-side documentation MUST translate at the L1 boundary (see §5.1 amendment below).

- **PCDN-B-mailbox-NUM_PRIO-1-clamp** (§6.1) — RESOLVED. `NUM_PRIO=1` degenerate case handled via `PRIO_W_EFF = max(1, $clog2(NUM_PRIO))` clamp (avoids 0-bit signals) + arbiter bypassed (sos_arbiter_priority requires N_REQS >= 2). Useful for chart authors who want one lane today with headroom for future expansion. SVA properties degenerate appropriately.

- **PCDN-B-GRANT_LATENCY_CYCLES-L1-inheritance** (§7) — RESOLVED. `GRANT_LATENCY_CYCLES` default-1 exception (originally an INV-S-HDL-A-5 named exception for L0 arbiter primitives, extended to "all L0 arbiter primitives" in SOS-08-A wave-2 §15) extends NATURALLY to L1 surfaces that compose L0 arbiter primitives. `sos_mailbox` surfaces `GRANT_LATENCY_CYCLES` from its inner `sos_arbiter_priority` and keeps the default-1. No new exception clause needed in INV-S-HDL-A-5 or INV-S-HDL-B-*. Future L1 services composing arbiters inherit by the same rule (see §7 amendment below).

- **PCDN-B-event-set-clear-shadow** (§6.2) — RESOLVED. Same-cycle `set_req` + `clear_req` on the same bit resolves via the underlying `sos_strobe_latch` wave-2 shadow-promote semantic (SOS-08-A PCDN-A-strobe-pending-shadow). Concrete outcomes:
  - bit currently CLEAR + same-cycle set+clear → bit becomes SET next cycle (L0 IDLE state: strobe wins, ack is a no-op).
  - bit currently SET + same-cycle set+clear → bit STAYS SET (L0 LATCHED + strobe + ack: ack consumes the live event, shadow captures the new strobe, shadow promotes — net stays LATCHED).
  Both edges preserved; no event loss. SVA property `a_bit_holds_under_concurrent_set_clear` (wave-1 impl) catches regressions. This is the canonical L1 semantic; chart authors MAY rely on the no-event-loss behaviour.

- **PCDN-B-pool-encoder-direction** (§6.3) — RESOLVED. `sos_resource_pool` free-slot allocator uses **lowest-id-first** priority encoder. Matches SOS-04 `TCB_POOL[0..MAX_TASKS)` + SOS-05 static-pool macro indexing convention. Chart-side reasoning stays consistent across software ports and HDL.

**Agent-default ratifications** (no user input required; resolved by spec-before-code source-of-truth doctrine + INV-S-HDL-B-2 corollary):

1. **sos_event_group: `pending_q` hidden at the L1 boundary.** The per-bit `pending_q` of the underlying `sos_strobe_latch` is an L0 implementation detail; surfacing it at L1 would violate INV-S-HDL-B-2 ("L1 composes L0 without modifying L0 behaviour" — corollary: L1 hides L0 implementation details from chart consumers). Internal observability is retained via auto-attached L0 SVA binds (module-type pattern), not L1 ports.

2. **sos_event_group: single-consumer `wait` semantics at v1** (matches §6.2 prose). Multi-consumer wait (composing `sos_arbiter_rr` over wait-ports) is a future §15 amendment if a customer needs concurrent wait observers on the same event group.

3. **sos_resource_pool §6.3 recipe substitution.** Spec §6.3 names L0 composition as `sos_fifo_sync + tracker bit-vector` (FIFO-of-free-IDs). Wave-1 impl uses `sos_credit_counter + sos_dpram_arb + free-vec + priority encoder` recipe. Net chart-visible contract identical (alloc/free/read_meta/write_meta + SVA-POOL-1..5). The recipe difference is informative; the canonical contract is unchanged. §6.3 prose stays; this §15 entry records the recipe substitution as a SOS-08-B impl convention.

4. **sos_resource_pool same-cycle alloc+free** (§6.3). When `alloc_req` and `free_req` both fire on the same cycle, alloc is applied first against the pre-update `free_vec`, then free is applied. Same-id collision (`free_id == alloc_id`) → bit ends up BUSY (the simultaneous free is silently absorbed because the encoder already chose that slot). Chart compiler is expected to keep alloc/free disjoint per INV-SOS-G; same-id collision is a chart-side correctness concern, not a primitive correctness defect.

5. **sos_periodic_task overrun-fault timing** (§6.4). `overrun_fault` asserts ONE CYCLE AFTER the offending `task_tick`. Both `task_enable` (registered output) and `overrun_fault` (registered output) rise on the same edge — one cycle after the `task_tick` pulse. Matches SVA-PT-2 phrasing + keeps the entire output surface synchronous off a single set of registers. Chart-side consumers reason about "overrun_fault rises one cycle after the missed deadline".

6. **sos_periodic_task FSM shape** (§6.4). Wave-1 impl uses an explicit 3-state one-hot FSM (IDLE/RUNNING/OVERRUN). Observationally equivalent to a sticky-overrun register + the rate divider; the FSM form is documentation convenience. Reserved as the canonical impl shape — SOS-08-C emission tables target this FSM shape. A future amendment MAY collapse to sticky-reg-only if no use case for distinct OVERRUN state emerges.

7. **sos_message_channel dual port representation** (§6.5). Wave-1 impl exposes BOTH packed `tdata = {event_id, payload}` AND decomposed sideband (`s_axis_tevent_id` + `s_axis_tpayload`) on each side. Producer-side OR-combines (chart emitter ties off the unused representation per instance); consumer-side both are wire-only derivatives of the FIFO output. SVA `m_axis_tdata == {m_axis_tevent_id, m_axis_tpayload}` asserts cross-representation consistency. This accommodates either chart-emitter style (packed-bus or sideband).

8. **sos_message_channel SVA-MSGCH-4 deferred** (§6.5). Enum-membership SVA (event_id is in the chart's `ExternalEventName` enumeration) is deferred to the SOS-08-C emission layer per PCDN-B-005 "chart-event-shape-aware at chart-compile time" boundary. SOS-08-B layer asserts cross-representation consistency + AXI-Stream handshake stability only; per-event-name enum membership lands when SOS-08-C emits the per-chart `sos_message_channel_packer_<chart>.{vhd,sv}` wrapper.

9. **sos_message_channel CDC variant deferred** (§6.5). Wave-1 impl composes single-clock `sos_fifo_sync`. Cross-domain message channel (composing `sos_fifo_async`) is a future §15 amendment, analogous to PCDN-B-mailbox-CROSS_CLK-deferred. INV-S-HDL-3 cited as N/A at v1; lands with the CDC variant.

**§5 / §6 / §7 amendments recorded by reference** (per-section prose stays as ratified; this entry is the canonical delta record):

- **§5.1** (FreeRTOS / POSIX vocabulary mirror) — FreeRTOS's "priority 0 = highest" convention is INVERTED at the HDL layer per PCDN-B-mailbox-lane-priority; chart-side documentation MUST translate at the L1 boundary. The vocabulary mirror remains intact (verb set unchanged); only the priority-direction convention diverges, and the divergence is L1-boundary-resolved.
- **§6.1** (sos_mailbox) — sideband width corrected; post_rc surface withdrawn (AXI-Stream backpressure canonical); CROSS_CLK deferred; NUM_PRIO=1 clamp; lane-priority direction (higher index = higher priority); GRANT_LATENCY_CYCLES inherited from inner arbiter.
- **§6.2** (sos_event_group) — same-cycle set+clear resolved via L0 shadow-promote; `pending_q` hidden at L1; single-consumer wait at v1.
- **§6.3** (sos_resource_pool) — free-vec + credit_counter + dpram_arb recipe substituted for FIFO-of-IDs (chart-visible contract unchanged); lowest-id-first priority encoder; same-cycle alloc+free behaviour ratified.
- **§6.4** (sos_periodic_task) — overrun-fault timing (registered, one-cycle delayed); 3-state one-hot FSM shape ratified as canonical impl.
- **§6.5** (sos_message_channel) — dual port representation (packed + sideband); SVA-MSGCH-4 deferred to SOS-08-C; CDC variant deferred.
- **INV-S-HDL-B-2** wording extended to recognize "L1 hides L0 implementation details from chart consumers" as the corollary of "L1 composes L0 without modifying L0 behaviour" (justifies `pending_q` hidden, justifies the `sos_resource_pool` recipe substitution being chart-invisible).
- **§7 cross-service invariants** extended: any L1 service composing an L0 arbiter primitive inherits the `GRANT_LATENCY_CYCLES` default-1 exception (no new named exception in INV-S-HDL-A-5; the exception flows through composition).

**Status**: 🟢 **ratified (continuing)** — impl wave-1 PCDN amendments fold the 5 L1 service implementation choices into the SOS-08-B normative surface. All 5 L1 services have ratified ports + generics + SVA + composition discipline. The SOS-08-A primitive surface + SOS-08-B service surface together form the complete L0+L1 layered RTL stack ready for SOS-08-C chart→FSM emission to instantiate against.

### 2026-05-24 — §6.5 amendment: ratify async sibling variant (`sos_message_channel_async`)

Wave-1's agent-default ratification #9 deferred the CDC variant to "a future §15 amendment". The SOS-08-C wave-3-d-2 work consuming this amendment promotes the deferred variant to a fully-specified sibling L1 service. Resolves the gap between §6.5 normative interface signature (which prints `clk_tx/rst_tx, clk_rx/rst_rx` per spec sketch from initial ratification) and the wave-1 impl (which composed `sos_fifo_sync` and exposes a single `clk/rst`).

**Resolution shape**: TWO sibling L1 primitives under the `sos_message_channel` family namespace, each with its own RTL + SVA + bind:

| Variant | RTL module | Composition | Use case | Selected when |
|---|---|---|---|---|
| **single-clock** (wave-1 baseline) | `sos_message_channel` | one `sos_fifo_sync` | producer + all consumers share one clock | SOS-08-C: producer.clock_domain == consumer.clock_domain ∀ consumers |
| **async / CDC** (wave-3-d-2) | `sos_message_channel_async` | one `sos_fifo_async` | producer and ≥ 1 consumer in different domains | SOS-08-C: producer.clock_domain ≠ consumer.clock_domain (for any consumer) |

Both variants share:
- Identical AXI-Stream packed + decomposed sideband convention on each side (slave-side OR-combine; master-side fanout).
- Identical generics `EVENT_ID_WIDTH`, `PAYLOAD_WIDTH`, `DEPTH`, `READ_LATENCY`, `RESET_MEM`.
- Identical pack/unpack consistency claim on the master-side via service-level SVA.
- Inherit the inner FIFO's vendor-IP shim selection (INV-S-HDL-B-4).

**Variant-specific surface** (async-only additions):

- Mandatory: `wr_clk, wr_rst, rd_clk, rd_rst` (replaces `clk, rst`).
- Generic: `SYNC_STAGES` (default 2 per `sos_fifo_async` precedent; INV-S-HDL-A-5 named exception).
- Observability: `wr_full, wr_count` (producer domain) + `rd_empty, rd_count` (consumer domain) — replaces the sync variant's unified `full/empty/count` triple.

**SOS-08-C selection contract** (consumed by wave-3-d-2 walker):

- For each chart-wide unique event name, compute the **producer-domain set** (union of producers' `clock_domain`) and the **consumer-domain set** (union of consumers' `clock_domain`).
- If both sets are singletons AND equal: emit `sos_message_channel` with that clock.
- If both sets are singletons but unequal: emit `sos_message_channel_async` with `wr_clk` = producer domain, `rd_clk` = consumer domain.
- If either set has cardinality > 1: NOT SUPPORTED at wave-3-d-2. The walker emits a chart-vocabulary error pointing at the multi-domain producer or consumer. (Future amendment may introduce a fan-in arbiter or multi-channel fanout primitive.)

**Invariants now operational**:

- **INV-S-HDL-3** (cross-domain isolation): was N/A for the wave-1 baseline; OPERATIONAL for `sos_message_channel_async`. The inner `sos_fifo_async`'s gray-coded pointer crossings + SYNC_STAGES-deep flop synchronizers + the documented MTBF analysis at `rtl/sos_fifo_async/MTBF.md` cover the CDC primitive obligation.
- **INV-S-HDL-B-1** (vocabulary mirror): both variants expose the same chart-side verbs (send / receive). The CDC variant is the FreeRTOS `xStreamBufferSendFromISR` analog when the ISR runs on a different clock from the receiving task (per §5.1 + §6.5 mapping).
- **INV-S-HDL-B-2** (L0 non-modification): both variants compose their L0 FIFO as a black-box.
- **INV-S-HDL-B-3** (service-level SVA): each variant ships its own SVA module + bind file (`sos_message_channel_sva.sv` for sync; `sos_message_channel_async_sva.sv` for CDC).
- **INV-S-HDL-B-4** (vendor-IP pass-through): CDC variant pass-through is `xpm_fifo_async` (Xilinx) per the same shim mechanism.

**SVA layering for the async variant**:

The async SVA module splits properties across the two clock domains:
- Slave-side properties (`tvalid_stable`, `tevent_id_stable`, `tpayload_stable`, `no_send_when_full`) clock on `wr_clk`, disable on `wr_rst`.
- Master-side properties (`master_pack_consistency`, FWFT-mode `tevent_id_stable` / `tpayload_stable`) clock on `rd_clk`, disable on `rd_rst`.
- Reset-clears properties split per-domain (`wr_reset_clears_count`, `wr_reset_clears_full`, `rd_reset_sets_empty`, `rd_reset_clears_count`).

The CDC handshake atomicity (packed word arrives intact across the boundary) is VERIFIED_BY_ELAB via the inner `sos_fifo_async`'s gray-code construction — no L1-level runtime assertion needed (the L0's MTBF analysis is the load-bearing artifact).

**Vendor-IP pass-through** (informative): `sos_message_channel_async` inherits the inner `sos_fifo_async`'s vendor-IP shim selection — `-Dvendor=xilinx` → `xpm_fifo_async`. Other vendor variants land per the SOS-08-A vendor shim discipline.

**Conformance gates** updated: §12 acceptance gate (b) ("each of the five services has its §6 subsection ratified") now reads as "each of the five service FAMILIES" — the message-channel family ratifies BOTH sibling variants under the same §6.5 subsection. PCDN-B-mailbox-CROSS_CLK-deferred (§6.1 mailbox CDC variant) remains deferred to a future amendment on the same precedent.

**Files added** in this amendment (rtl + tb):
- `rtl/sos_message_channel/sos_message_channel_async.sv`
- `rtl/sos_message_channel/sos_message_channel_async.vhd`
- `rtl/sos_message_channel/sos_message_channel_async_sva.sv`
- `tb/sos_message_channel/sos_message_channel_async_bind.sv`

Status: 🟢 **§6.5 async variant ratified**. SOS-08-C wave-3-d-2 walker logic consumes this amendment to select between the two variants based on producer/consumer clock-domain alignment.
