# rtos_kernel.scxml — Reference

Preemptive priority-based RTOS kernel modeled as a single SCXML statechart.
ECMAScript datamodel. FreeRTOS-shaped primitives, deliberately constrained.

## Topology

```
scxml
├── boot                    one-shot init, transitions to running
└── running   (parallel)
    ├── scheduler           sched.run → pick_next() if sched_lock==0
    ├── tick_service        sys.tick → advance time, expire delays/timeouts
    ├── syscalls            external API dispatch on event name
    └── protection          crit_*/sched_* nesting counters
```

The four regions share the datamodel. Mutation safety derives from SCXML's
run-to-completion macrostep: at most one transition's executable content
runs at a time. There are no explicit kernel locks because the model does
not actually run concurrently — `irq_nest` and `sched_lock` exist only to
model the constraints a generated implementation must enforce.

## Task states

| Code | Symbol      | Meaning                                  |
|-----:|-------------|------------------------------------------|
| 0    | ST_DORMANT  | TCB slot unused                          |
| 1    | ST_READY    | In a `ready[prio]` queue, eligible       |
| 2    | ST_RUNNING  | `current == id`, removed from ready[]    |
| 3    | ST_DELAY    | Time-blocked, on no waiter list          |
| 4    | ST_BLK_SEM  | On `sems[blk_obj].waiters`               |
| 5    | ST_BLK_QS   | On `queues[blk_obj].sendw`, msg pending  |
| 6    | ST_BLK_QR   | On `queues[blk_obj].recvw`               |
| 7    | ST_SUSPEND  | Off all lists, awaits explicit resume    |

`tcb[i]` fields: `id, prio, state, deadline, blk_obj, msg`.
`deadline == 0` means infinite wait. `msg` carries both queue payloads
and the final return code deposited when a blocked task is unblocked.

## Ready-queue invariant

`ready` is an array of length `MAX_PRIO`, each entry a FIFO queue of tids.
At any quiescent point:

* RUNNING task is **not** in any `ready[p]`.
* READY tasks appear in exactly one `ready[p]`, where `p == tcb[id].prio`.
* Blocked/suspended/dormant tasks appear in **no** `ready[p]`.

Round-robin among equal priority is achieved by `pick_next()` pushing the
outgoing RUNNING task to the tail of `ready[prio]` before popping the head
of the highest non-empty priority.

## Syscall ABI

All syscalls are external SCXML events. Parameters live in `_event.data`.
Immediate result lands in `rc`. For potentially-blocking calls, the
ultimate result is deposited in `tcb[id].msg` when the task is unblocked
(timeout, give, send, etc.).

### Tasks

| Event         | `data`               | rc                       |
|---------------|----------------------|--------------------------|
| task.create   | `{id, prio}`         | OK / INVAL               |
| task.delay    | `{ticks}`            | OK (ticks≤0 ⇒ yield)     |
| task.yield    | —                    | OK                       |
| task.suspend  | `{id}`               | OK / INVAL               |
| task.resume   | `{id}`               | OK / INVAL               |

`task.suspend` is defined only for READY or RUNNING targets. Suspending a
blocked task is not modeled.

### Semaphores (counting; binary ⇒ `max=1`)

| Event              | `data`                          | rc                                 |
|--------------------|---------------------------------|------------------------------------|
| sem.create         | `{id, initial, max}`            | OK                                 |
| sem.take           | `{sid, timeout}`                | OK / TIMEOUT / INVAL               |
| sem.give           | `{sid}`                         | OK / INVAL / FULL                  |
| sem.give_from_isr  | `{sid}`                         | — (no rc; ISR context)             |

`timeout`: `0` = poll, `-1` = block forever, `>0` = ticks.

### Message queues

| Event                | `data`                | rc                                 |
|----------------------|-----------------------|------------------------------------|
| queue.create         | `{id, cap}`           | OK                                 |
| queue.send           | `{qid, msg, timeout}` | OK / FULL / INVAL                  |
| queue.receive        | `{qid, timeout}`      | OK / EMPTY / INVAL (msg in `.msg`) |
| queue.send_from_isr  | `{qid, msg}`          | —                                  |

Direct-handoff fast paths bypass the buffer when a counterpart waiter
exists, preserving priority ordering at both ends.

### Time and protection

| Event          | `data` | Effect                                       |
|----------------|--------|----------------------------------------------|
| sys.tick       | —      | Advance `tick_count`; expire delays/timeouts |
| crit.enter     | —      | `irq_nest++`                                 |
| crit.exit      | —      | `irq_nest--`, raise sched.run                |
| sched.suspend  | —      | `sched_lock++`                               |
| sched.resume   | —      | `sched_lock--`; on zero, flush `pend_ticks`  |

While `irq_nest>0` or `sched_lock>0`, `sys.tick` increments `pend_ticks`
instead of advancing time; deferred ticks are replayed when both clear.

### Internal events

| Event              | Source                        | Sink                |
|--------------------|-------------------------------|---------------------|
| kernel.boot.done   | boot.onentry                  | boot → running      |
| sched.run          | every state-mutating syscall  | scheduler region    |

## Wait-queue ordering

Per-object waiters (`sems[*].waiters`, `queues[*].sendw`, `queues[*].recvw`)
are kept in **priority-descending, FIFO-within-priority** order via
`waiters_insert`. `give`/`send`/`receive` always wake the head, giving
priority-correct release without scan cost at wake time.

Priority inheritance is **not** modeled; this kernel is deadlock-prone
under priority-inversion in the same way as a stock counting semaphore.
Adding it is a localized change to `sem.take`/`sem.give` plus a `holder`
field in the sem record.

## Concurrency / safety invariants

The model encodes — but does not enforce in the simulator — these
contract requirements for any generated implementation:

1. `sys.tick` is the only event admissible from ISR context outside the
   explicit `*_from_isr` family.
2. Non-ISR syscalls require `current >= 0` (a task context).
3. `block_current()` must only be called when `sched_lock == 0` and
   `irq_nest == 0`; in a real port the caller wrappers check this.
4. `pick_next()` is idempotent; redundant `sched.run` raises are safe.
5. A blocked task's `blk_obj` matches exactly one of: `sems` index (for
   BLK_SEM), `queues` index (for BLK_QS, BLK_QR), `-1` (for DELAY).

## Code-generation notes

This chart is designed for the SoftOboros SCXML compiler family. Notes
for backends:

* The datamodel is purely value-typed (`Number`, `Boolean`, fixed-shape
  records, fixed-length arrays). It maps to C structs + static arrays
  cleanly with no allocator. `tcb` becomes `tcb_t tcb[MAX_TASKS]`,
  `ready` becomes `tid_t ready[MAX_PRIO][MAX_TASKS+1]` with a length
  shadow, etc.
* `_event.data` becomes a tagged union per event family; the syscall
  dispatcher becomes a `switch` on event id.
* `<raise event="sched.run"/>` is a tail call to the scheduler step in
  generated C; the internal queue is degenerate (depth 1) because no
  syscall raises more than one internal event before returning.
* `ready_pop_highest` is the canonical site for a priority bitmap +
  CLZ optimization in any backend with a hardware count-leading-zeros.
* `waiters_insert` is O(N_waiters); acceptable for `MAX_TASKS=8`,
  replaceable with a per-priority bucket list at scale.

## Deliberate omissions vs. FreeRTOS

* No software timers (use `task.delay` or build atop `sys.tick`).
* No event groups / direct-to-task notifications.
* No mutexes with priority inheritance.
* No memory allocator; static pools only.
* No stream/message-buffer streaming variants.
* No tickless idle.
* No SMP / core affinity.

Each is a localized extension; none requires restructuring the parallel
topology.

## Testing surface

Drive the chart with sequences of external events and observe `tcb`,
`current`, `tick_count`, and per-object state. Suggested smoke tests:

1. Two tasks at the same priority alternating via `task.yield`.
2. Higher-priority task preempts on `sem.give`.
3. `task.delay` followed by `sys.tick` storms shows monotonic wake-up.
4. Queue `FULL`/`EMPTY` rejection vs. blocking with timeout.
5. `crit.enter` + `sys.tick × N` + `crit.exit` produces N catch-up ticks
   and at most one reschedule.
6. `sched.suspend` deferring a high-priority unblock until `sched.resume`.
