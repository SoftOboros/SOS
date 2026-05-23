/* scripts.c — chart-derived script bodies + HELPERS-block helpers.
 *
 * Per SOS-02 §6.3 (script-name table) and SOS-05 §6.3 / §6.4. C analogue
 * of `ports/m7-rust/sos-m7-rust/src/scripts.rs`. Each `<script>` block
 * in `rtos_kernel.scxml` is transliterated 1:1 into a
 * `script_<state>_<event>_<index>` free function below; the chart's
 * top-level HELPERS block (lines 77-165) is realised as the
 * file-static `dm_*` helper functions.
 *
 * Extracted from `src/kernel.c` in SOS-05a (refactor, no behaviour
 * change). Function bodies are character-identical to the lines they
 * replaced; only linkage changed (`static` removed from the 20
 * `script_*_0` functions so the dispatcher in `kernel.c` may bind via
 * the prototypes in `sos/scripts.h`). The HELPERS-block functions and
 * private helpers (`dm_sem_give_common`, `dm_queue_push`) remain
 * file-static — they are private to this TU.
 */

#include "sos/kernel.h"
#include "sos/scripts.h"
#include "sos/types.h"

/* ====================================================================
 * Helper functions on `struct sos_datamodel` — mirror of the chart's
 * HELPERS block (rtos_kernel.scxml lines 77-165) and the Rust port's
 * `impl Datamodel { ... }` methods in `sos-m7-rust/src/scripts.rs`.
 *
 * heapless::Vec<T, N> is realised as the wave-2 `T arr[N] + uint8_t
 * arr_count` pattern; "push" / "remove(i)" become explicit count-bump
 * and memmove operations. Capacity overflows are chart-invariant
 * unreachable; on the rare paths where they would surface, the helper
 * sets `dm->rc = SOS_RC_INVAL` and bails (parallels Rust's
 * `ScriptError::*Full`).
 * ==================================================================== */

/* Discriminator for the three waiter lists — sem.waiters, queue.sendw,
 * queue.recvw. Parallels Rust's `WaiterList` enum. */
typedef enum {
    DM_WL_SEM_WAITERS = 0,
    DM_WL_QUEUE_SENDW = 1,
    DM_WL_QUEUE_RECVW = 2
} dm_waiter_list_t;

/* ready_push (rtos_kernel.scxml lines 86-89) — append `tid` to the tail
 * of its priority FIFO and flip its state to READY. */
static void dm_ready_push(struct sos_datamodel *dm, sos_task_id_t tid)
{
    if (tid < 0 || (size_t)tid >= SOS_MAX_TASKS) {
        dm->rc = (sos_rc_t)SOS_RC_INVAL;
        return;
    }
    sos_prio_t p = dm->tcb[tid].prio;
    if (p < 0 || (size_t)p >= SOS_MAX_PRIO) {
        dm->rc = (sos_rc_t)SOS_RC_INVAL;
        return;
    }
    uint8_t n = dm->ready_count[p];
    if ((size_t)n >= SOS_MAX_TASKS) {
        /* Chart invariant says this is unreachable. */
        dm->rc = (sos_rc_t)SOS_RC_INVAL;
        return;
    }
    dm->ready_pool[p][n] = tid;
    dm->ready_count[p] = (uint8_t)(n + 1u);
    dm->tcb[tid].state = SOS_ST_READY;
}

/* ready_remove (rtos_kernel.scxml lines 92-96) — drop `tid` from its
 * priority FIFO if present. */
static void dm_ready_remove(struct sos_datamodel *dm, sos_task_id_t tid)
{
    if (tid < 0 || (size_t)tid >= SOS_MAX_TASKS) {
        return;
    }
    sos_prio_t p = dm->tcb[tid].prio;
    if (p < 0 || (size_t)p >= SOS_MAX_PRIO) {
        return;
    }
    uint8_t n = dm->ready_count[p];
    for (uint8_t i = 0u; i < n; ++i) {
        if (dm->ready_pool[p][i] == tid) {
            /* Shift tail down by one. */
            for (uint8_t j = (uint8_t)(i + 1u); j < n; ++j) {
                dm->ready_pool[p][j - 1u] = dm->ready_pool[p][j];
            }
            dm->ready_count[p] = (uint8_t)(n - 1u);
            return;
        }
    }
}

/* ready_pop_highest (rtos_kernel.scxml lines 99-104) — pop the head of
 * the highest non-empty priority FIFO; returns -1 if no task is ready. */
static sos_task_id_t dm_ready_pop_highest(struct sos_datamodel *dm)
{
    int32_t p = (int32_t)dm->max_prio - 1;
    while (p >= 0) {
        uint8_t n = dm->ready_count[p];
        if (n > 0u) {
            sos_task_id_t head = dm->ready_pool[p][0];
            for (uint8_t j = 1u; j < n; ++j) {
                dm->ready_pool[p][j - 1u] = dm->ready_pool[p][j];
            }
            dm->ready_count[p] = (uint8_t)(n - 1u);
            return head;
        }
        --p;
    }
    return -1;
}

/* waiters_insert (rtos_kernel.scxml lines 108-113) — priority-descending,
 * FIFO-within-priority insertion. Common driver for sem/queue lists. */
static void dm_waiters_insert(struct sos_datamodel *dm,
                              sos_task_id_t *arr,
                              uint8_t *count,
                              sos_task_id_t tid)
{
    if (tid < 0 || (size_t)tid >= SOS_MAX_TASKS) {
        dm->rc = (sos_rc_t)SOS_RC_INVAL;
        return;
    }
    uint8_t n = *count;
    if ((size_t)n >= SOS_MAX_TASKS) {
        /* Chart invariant says this is unreachable. */
        dm->rc = (sos_rc_t)SOS_RC_INVAL;
        return;
    }
    sos_prio_t p = dm->tcb[tid].prio;
    uint8_t i = 0u;
    while (i < n) {
        sos_task_id_t head = arr[i];
        if (dm->tcb[head].prio < p) {
            break;
        }
        ++i;
    }
    /* Shift tail up by one to open slot i. */
    for (uint8_t j = n; j > i; --j) {
        arr[j] = arr[j - 1u];
    }
    arr[i] = tid;
    *count = (uint8_t)(n + 1u);
}

/* Forward decls — block_current / unblock cross-reference dm_ready_push
 * and (indirectly) each other through scripts; keep the C linker happy. */
static void dm_pick_next(struct sos_datamodel *dm);
static void dm_waiter_cancel(struct sos_datamodel *dm, sos_task_id_t tid);

/* block_current (rtos_kernel.scxml lines 117-123) — park `current` in
 * `state` against `blk_obj` / `deadline`; clear `current` and raise
 * `resched`. */
static void dm_block_current(struct sos_datamodel *dm,
                             sos_task_state_t state,
                             int16_t blk_obj,
                             sos_tick_t deadline)
{
    sos_task_id_t cur = dm->current;
    if (cur < 0 || (size_t)cur >= SOS_MAX_TASKS) {
        /* Chart precondition says current must be set; surface as INVAL
         * to mirror Rust's ScriptError::BadState collapse. */
        dm->rc = (sos_rc_t)SOS_RC_INVAL;
        return;
    }
    dm->tcb[cur].state    = state;
    dm->tcb[cur].blk_obj  = blk_obj;
    dm->tcb[cur].deadline = deadline;
    dm->current  = -1;
    dm->resched  = true;
}

/* unblock (rtos_kernel.scxml lines 126-131) — move `tid` from a blocked
 * state back to READY; raise `resched`. */
static void dm_unblock(struct sos_datamodel *dm, sos_task_id_t tid)
{
    if (tid < 0 || (size_t)tid >= SOS_MAX_TASKS) {
        dm->rc = (sos_rc_t)SOS_RC_INVAL;
        return;
    }
    dm->tcb[tid].deadline = 0;
    dm->tcb[tid].blk_obj  = -1;
    dm_ready_push(dm, tid);
    dm->resched = true;
}

/* waiter_cancel (rtos_kernel.scxml lines 135-145) — remove `tid` from
 * whichever waiter list its blocked state implies; no-op otherwise. */
static void dm_waiter_cancel(struct sos_datamodel *dm, sos_task_id_t tid)
{
    if (tid < 0 || (size_t)tid >= SOS_MAX_TASKS) {
        return;
    }
    sos_task_state_t s   = dm->tcb[tid].state;
    int16_t          obj = dm->tcb[tid].blk_obj;
    if (obj < 0) {
        return;
    }
    size_t idx = (size_t)obj;
    sos_task_id_t *arr   = NULL;
    uint8_t       *count = NULL;
    if (s == SOS_ST_BLK_SEM) {
        if (idx >= SOS_MAX_SEMS) {
            return;
        }
        arr   = dm->sems[idx].waiters;
        count = &dm->sems[idx].waiter_count;
    } else if (s == SOS_ST_BLK_QS) {
        if (idx >= SOS_MAX_QUEUES) {
            return;
        }
        arr   = dm->queues[idx].sendw;
        count = &dm->queues[idx].sendw_count;
    } else if (s == SOS_ST_BLK_QR) {
        if (idx >= SOS_MAX_QUEUES) {
            return;
        }
        arr   = dm->queues[idx].recvw;
        count = &dm->queues[idx].recvw_count;
    } else {
        return;
    }
    uint8_t n = *count;
    for (uint8_t i = 0u; i < n; ++i) {
        if (arr[i] == tid) {
            for (uint8_t j = (uint8_t)(i + 1u); j < n; ++j) {
                arr[j - 1u] = arr[j];
            }
            *count = (uint8_t)(n - 1u);
            return;
        }
    }
}

/* pick_next (rtos_kernel.scxml lines 149-163) — scheduler microstep:
 * round-robin current into its tail, then promote the highest-priority
 * ready task to RUNNING. */
static void dm_pick_next(struct sos_datamodel *dm)
{
    if (dm->current >= 0) {
        size_t cur = (size_t)dm->current;
        if (cur < SOS_MAX_TASKS && dm->tcb[cur].state == SOS_ST_RUNNING) {
            dm->tcb[cur].state = SOS_ST_READY;
            dm_ready_push(dm, dm->tcb[cur].id);
        }
    }
    sos_task_id_t n = dm_ready_pop_highest(dm);
    if (n >= 0) {
        dm->tcb[n].state = SOS_ST_RUNNING;
        dm->current = n;
    } else {
        dm->current = -1;
    }
    dm->resched = false;
}

/* ====================================================================
 * Script bodies — one per <script> block in rtos_kernel.scxml. Each
 * returns true on success and false on a payload-shape mismatch
 * (parallels Rust's ScriptError::WrongDataVariant collapse). Per-script
 * doc-comments cite the .scxml line range mirrored.
 *
 * Prototypes for the 20 script bodies live in `sos/scripts.h` so the
 * dispatcher in `kernel.c` can bind them by name. External linkage is
 * deliberate; the script bodies themselves do not call each other
 * directly (the macrostep / scheduler microstep is the only inter-
 * script edge, driven from the dispatcher).
 * ==================================================================== */

/* rtos_kernel.scxml lines 172-192 — boot/onentry. The firmware's
 * sos_kernel_init() already performs the equivalent setup; this is the
 * parity stub. */
bool script_boot_onentry_0(const sos_event_t *ev)
{
    (void)ev;
    /* Idempotent no-op for parity with sim. sos_kernel_init() owns the
     * real boot baseline. */
    return true;
}

/* rtos_kernel.scxml lines 210-212 — sched_idle / sched.run. */
bool script_sched_idle_sched_run_0(const sos_event_t *ev)
{
    (void)ev;
    struct sos_datamodel *dm = sos_kernel_state();
    if (dm->sched_lock == 0) {
        dm_pick_next(dm);
    }
    return true;
}

/* rtos_kernel.scxml lines 225-252 — tick_idle / sys.tick. */
bool script_tick_idle_sys_tick_0(const sos_event_t *ev)
{
    (void)ev;
    struct sos_datamodel *dm = sos_kernel_state();
    if (dm->irq_nest > 0 || dm->sched_lock > 0) {
        dm->pend_ticks += 1;
        return true;
    }
    dm->tick_count += 1;
    uint32_t n = dm->max_tasks;
    if (n > SOS_MAX_TASKS) {
        n = SOS_MAX_TASKS;
    }
    for (size_t i = 0u; i < n; ++i) {
        sos_task_state_t state = dm->tcb[i].state;
        sos_tick_t       deadline = dm->tcb[i].deadline;
        if (state == SOS_ST_DELAY && deadline <= dm->tick_count) {
            dm->tcb[i].msg.tag  = SOS_MSG_RC;
            dm->tcb[i].msg.u.rc = (sos_rc_t)SOS_RC_OK;
            dm_unblock(dm, (sos_task_id_t)i);
            continue;
        }
        bool is_blocked = (state == SOS_ST_BLK_SEM ||
                           state == SOS_ST_BLK_QS  ||
                           state == SOS_ST_BLK_QR);
        if (is_blocked && deadline > 0 && deadline <= dm->tick_count) {
            dm_waiter_cancel(dm, (sos_task_id_t)i);
            dm->tcb[i].msg.tag  = SOS_MSG_RC;
            dm->tcb[i].msg.u.rc = (sos_rc_t)SOS_RC_TIMEOUT;
            dm_unblock(dm, (sos_task_id_t)i);
        }
    }
    return true;
}

/* rtos_kernel.scxml lines 270-286 — task.create. */
bool script_sys_idle_task_create_0(const sos_event_t *ev)
{
    if (ev->data.tag != SOS_EVD_TASK_CREATE) {
        struct sos_datamodel *dm = sos_kernel_state();
        dm->rc = (sos_rc_t)SOS_RC_INVAL;
        return false;
    }
    struct sos_datamodel *dm = sos_kernel_state();
    sos_task_id_t id   = ev->data.u.task_create.id;
    uint8_t       prio = ev->data.u.task_create.prio;
    if (id < 0 || (size_t)id >= SOS_MAX_TASKS) {
        dm->rc = (sos_rc_t)SOS_RC_INVAL;
        return true;
    }
    size_t idx = (size_t)id;
    if (dm->tcb[idx].state != SOS_ST_DORMANT) {
        dm->rc = (sos_rc_t)SOS_RC_INVAL;
        return true;
    }
    dm->tcb[idx].prio     = (sos_prio_t)prio;
    dm->tcb[idx].deadline = 0;
    dm->tcb[idx].blk_obj  = -1;
    dm->tcb[idx].msg.tag  = SOS_MSG_NULL;
    dm->tcb[idx].msg.u.i  = 0;
    dm_ready_push(dm, id);
    dm->resched = true;
    dm->rc = (sos_rc_t)SOS_RC_OK;
    return true;
}

/* rtos_kernel.scxml lines 289-300 — task.delay. */
bool script_sys_idle_task_delay_0(const sos_event_t *ev)
{
    if (ev->data.tag != SOS_EVD_TASK_DELAY) {
        struct sos_datamodel *dm = sos_kernel_state();
        dm->rc = (sos_rc_t)SOS_RC_INVAL;
        return false;
    }
    struct sos_datamodel *dm = sos_kernel_state();
    int64_t ticks = ev->data.u.task_delay.ticks;
    if (ticks > 0) {
        sos_tick_t dl = (sos_tick_t)((int64_t)dm->tick_count + ticks);
        dm_block_current(dm, SOS_ST_DELAY, -1, dl);
    } else {
        dm->resched = true;
    }
    dm->rc = (sos_rc_t)SOS_RC_OK;
    return true;
}

/* rtos_kernel.scxml lines 302-305 — task.yield. */
bool script_sys_idle_task_yield_0(const sos_event_t *ev)
{
    (void)ev;
    struct sos_datamodel *dm = sos_kernel_state();
    dm->resched = true;
    dm->rc = (sos_rc_t)SOS_RC_OK;
    return true;
}

/* rtos_kernel.scxml lines 308-326 — task.suspend. */
bool script_sys_idle_task_suspend_0(const sos_event_t *ev)
{
    if (ev->data.tag != SOS_EVD_TASK_ID) {
        struct sos_datamodel *dm = sos_kernel_state();
        dm->rc = (sos_rc_t)SOS_RC_INVAL;
        return false;
    }
    struct sos_datamodel *dm = sos_kernel_state();
    sos_task_id_t id = ev->data.u.task_id.id;
    if (id < 0 || (size_t)id >= SOS_MAX_TASKS) {
        dm->rc = (sos_rc_t)SOS_RC_INVAL;
        return true;
    }
    size_t idx = (size_t)id;
    sos_task_state_t s = dm->tcb[idx].state;
    if (s == SOS_ST_READY) {
        dm_ready_remove(dm, id);
        dm->tcb[idx].state = SOS_ST_SUSPEND;
        dm->rc = (sos_rc_t)SOS_RC_OK;
    } else if (s == SOS_ST_RUNNING) {
        dm->tcb[idx].state = SOS_ST_SUSPEND;
        dm->current = -1;
        dm->resched = true;
        dm->rc = (sos_rc_t)SOS_RC_OK;
    } else {
        dm->rc = (sos_rc_t)SOS_RC_INVAL;
    }
    return true;
}

/* rtos_kernel.scxml lines 329-341 — task.resume. */
bool script_sys_idle_task_resume_0(const sos_event_t *ev)
{
    if (ev->data.tag != SOS_EVD_TASK_ID) {
        struct sos_datamodel *dm = sos_kernel_state();
        dm->rc = (sos_rc_t)SOS_RC_INVAL;
        return false;
    }
    struct sos_datamodel *dm = sos_kernel_state();
    sos_task_id_t id = ev->data.u.task_id.id;
    if (id < 0 || (size_t)id >= SOS_MAX_TASKS) {
        dm->rc = (sos_rc_t)SOS_RC_INVAL;
        return true;
    }
    size_t idx = (size_t)id;
    if (dm->tcb[idx].state == SOS_ST_SUSPEND) {
        dm_ready_push(dm, id);
        dm->resched = true;
        dm->rc = (sos_rc_t)SOS_RC_OK;
    } else {
        dm->rc = (sos_rc_t)SOS_RC_INVAL;
    }
    return true;
}

/* rtos_kernel.scxml lines 346-356 — sem.create. */
bool script_sys_idle_sem_create_0(const sos_event_t *ev)
{
    if (ev->data.tag != SOS_EVD_SEM_CREATE) {
        struct sos_datamodel *dm = sos_kernel_state();
        dm->rc = (sos_rc_t)SOS_RC_INVAL;
        return false;
    }
    struct sos_datamodel *dm = sos_kernel_state();
    int16_t  id      = ev->data.u.sem_create.id;
    uint32_t initial = ev->data.u.sem_create.initial;
    uint32_t max     = ev->data.u.sem_create.max;
    if (id < 0 || (size_t)id >= SOS_MAX_SEMS) {
        dm->rc = (sos_rc_t)SOS_RC_INVAL;
        return true;
    }
    size_t idx = (size_t)id;
    dm->sems[idx].valid        = true;
    dm->sems[idx].count        = initial;
    dm->sems[idx].max          = max;
    dm->sems[idx].waiter_count = 0u;
    dm->rc = (sos_rc_t)SOS_RC_OK;
    return true;
}

/* rtos_kernel.scxml lines 360-378 — sem.take. */
bool script_sys_idle_sem_take_0(const sos_event_t *ev)
{
    if (ev->data.tag != SOS_EVD_SEM_OP) {
        struct sos_datamodel *dm = sos_kernel_state();
        dm->rc = (sos_rc_t)SOS_RC_INVAL;
        return false;
    }
    struct sos_datamodel *dm = sos_kernel_state();
    int16_t sid     = ev->data.u.sem_op.sid;
    int64_t timeout = ev->data.u.sem_op.timeout;
    if (sid < 0 || (size_t)sid >= SOS_MAX_SEMS || !dm->sems[(size_t)sid].valid) {
        dm->rc = (sos_rc_t)SOS_RC_INVAL;
        return true;
    }
    size_t idx = (size_t)sid;
    if (dm->sems[idx].count > 0u) {
        dm->sems[idx].count -= 1u;
        dm->rc = (sos_rc_t)SOS_RC_OK;
    } else if (timeout == 0) {
        dm->rc = (sos_rc_t)SOS_RC_TIMEOUT;
    } else {
        sos_tick_t dl = (timeout < 0)
            ? 0
            : (sos_tick_t)((int64_t)dm->tick_count + timeout);
        sos_task_id_t cur = dm->current;
        if (cur < 0) {
            dm->rc = (sos_rc_t)SOS_RC_INVAL;
            return false;
        }
        dm_waiters_insert(dm,
                          dm->sems[idx].waiters,
                          &dm->sems[idx].waiter_count,
                          cur);
        dm_block_current(dm, SOS_ST_BLK_SEM, sid, dl);
        dm->rc = (sos_rc_t)SOS_RC_OK;
    }
    return true;
}

/* Shared sem-give helper for sem.give and sem.give_from_isr; the
 * difference is the from_isr path skips the dm->rc write on invalid
 * descriptors (mirrors Rust's silent-discard on ISR path). Returns true
 * if a waiter was woken or the count was incremented. */
static void dm_sem_give_common(struct sos_datamodel *dm, size_t idx,
                               bool *out_full)
{
    *out_full = false;
    if (dm->sems[idx].waiter_count > 0u) {
        sos_task_id_t w = dm->sems[idx].waiters[0];
        /* Remove index 0. */
        uint8_t n = dm->sems[idx].waiter_count;
        for (uint8_t j = 1u; j < n; ++j) {
            dm->sems[idx].waiters[j - 1u] = dm->sems[idx].waiters[j];
        }
        dm->sems[idx].waiter_count = (uint8_t)(n - 1u);
        dm->tcb[w].msg.tag  = SOS_MSG_RC;
        dm->tcb[w].msg.u.rc = (sos_rc_t)SOS_RC_OK;
        dm_unblock(dm, w);
    } else if (dm->sems[idx].count < dm->sems[idx].max) {
        dm->sems[idx].count += 1u;
    } else {
        *out_full = true;
    }
}

/* rtos_kernel.scxml lines 381-398 — sem.give. */
bool script_sys_idle_sem_give_0(const sos_event_t *ev)
{
    if (ev->data.tag != SOS_EVD_SEM_OP) {
        struct sos_datamodel *dm = sos_kernel_state();
        dm->rc = (sos_rc_t)SOS_RC_INVAL;
        return false;
    }
    struct sos_datamodel *dm = sos_kernel_state();
    int16_t sid = ev->data.u.sem_op.sid;
    if (sid < 0 || (size_t)sid >= SOS_MAX_SEMS || !dm->sems[(size_t)sid].valid) {
        dm->rc = (sos_rc_t)SOS_RC_INVAL;
        return true;
    }
    bool full = false;
    dm_sem_give_common(dm, (size_t)sid, &full);
    dm->rc = full ? (sos_rc_t)SOS_RC_FULL : (sos_rc_t)SOS_RC_OK;
    return true;
}

/* rtos_kernel.scxml lines 401-415 — sem.give_from_isr. */
bool script_sys_idle_sem_give_from_isr_0(const sos_event_t *ev)
{
    if (ev->data.tag != SOS_EVD_SEM_OP) {
        struct sos_datamodel *dm = sos_kernel_state();
        dm->rc = (sos_rc_t)SOS_RC_INVAL;
        return false;
    }
    struct sos_datamodel *dm = sos_kernel_state();
    int16_t sid = ev->data.u.sem_op.sid;
    if (sid < 0 || (size_t)sid >= SOS_MAX_SEMS) {
        /* ISR path: silent discard on out-of-range descriptor. */
        return true;
    }
    if (dm->sems[(size_t)sid].valid) {
        bool full = false;
        dm_sem_give_common(dm, (size_t)sid, &full);
        /* ISR path: no `dm->rc` write on the wake / full split. */
        (void)full;
    }
    return true;
}

/* rtos_kernel.scxml lines 420-432 — queue.create. */
bool script_sys_idle_queue_create_0(const sos_event_t *ev)
{
    if (ev->data.tag != SOS_EVD_QUEUE_CREATE) {
        struct sos_datamodel *dm = sos_kernel_state();
        dm->rc = (sos_rc_t)SOS_RC_INVAL;
        return false;
    }
    struct sos_datamodel *dm = sos_kernel_state();
    int16_t  id  = ev->data.u.queue_create.id;
    uint32_t cap = ev->data.u.queue_create.cap;
    if (id < 0 || (size_t)id >= SOS_MAX_QUEUES) {
        dm->rc = (sos_rc_t)SOS_RC_INVAL;
        return true;
    }
    if ((size_t)cap > SOS_Q_DEPTH) {
        dm->rc = (sos_rc_t)SOS_RC_INVAL;
        return true;
    }
    size_t idx = (size_t)id;
    dm->queues[idx].valid       = true;
    dm->queues[idx].cap         = cap;
    dm->queues[idx].count       = 0u;
    dm->queues[idx].sendw_count = 0u;
    dm->queues[idx].recvw_count = 0u;
    dm->rc = (sos_rc_t)SOS_RC_OK;
    return true;
}

/* Push a message onto the tail of a queue's bounded ring buffer. */
static void dm_queue_push(struct sos_datamodel *dm, size_t idx, int64_t msg)
{
    uint32_t n = dm->queues[idx].count;
    if ((size_t)n >= SOS_Q_DEPTH) {
        /* Chart invariant: count < cap <= Q_DEPTH. */
        dm->rc = (sos_rc_t)SOS_RC_INVAL;
        return;
    }
    dm->queues[idx].buf[n] = msg;
    dm->queues[idx].count = n + 1u;
}

/* rtos_kernel.scxml lines 435-461 — queue.send. */
bool script_sys_idle_queue_send_0(const sos_event_t *ev)
{
    if (ev->data.tag != SOS_EVD_QUEUE_SEND) {
        struct sos_datamodel *dm = sos_kernel_state();
        dm->rc = (sos_rc_t)SOS_RC_INVAL;
        return false;
    }
    struct sos_datamodel *dm = sos_kernel_state();
    int16_t qid     = ev->data.u.queue_send.qid;
    int64_t msg     = ev->data.u.queue_send.msg;
    int64_t timeout = ev->data.u.queue_send.timeout;
    if (qid < 0 || (size_t)qid >= SOS_MAX_QUEUES || !dm->queues[(size_t)qid].valid) {
        dm->rc = (sos_rc_t)SOS_RC_INVAL;
        return true;
    }
    size_t idx = (size_t)qid;
    if (dm->queues[idx].recvw_count > 0u) {
        sos_task_id_t w = dm->queues[idx].recvw[0];
        uint8_t n = dm->queues[idx].recvw_count;
        for (uint8_t j = 1u; j < n; ++j) {
            dm->queues[idx].recvw[j - 1u] = dm->queues[idx].recvw[j];
        }
        dm->queues[idx].recvw_count = (uint8_t)(n - 1u);
        dm->tcb[w].msg.tag = SOS_MSG_INT;
        dm->tcb[w].msg.u.i = msg;
        dm_unblock(dm, w);
        dm->rc = (sos_rc_t)SOS_RC_OK;
    } else if (dm->queues[idx].count < dm->queues[idx].cap) {
        dm_queue_push(dm, idx, msg);
        dm->rc = (sos_rc_t)SOS_RC_OK;
    } else if (timeout == 0) {
        dm->rc = (sos_rc_t)SOS_RC_FULL;
    } else {
        sos_tick_t dl = (timeout < 0)
            ? 0
            : (sos_tick_t)((int64_t)dm->tick_count + timeout);
        sos_task_id_t cur = dm->current;
        if (cur < 0) {
            dm->rc = (sos_rc_t)SOS_RC_INVAL;
            return false;
        }
        dm->tcb[cur].msg.tag = SOS_MSG_INT;
        dm->tcb[cur].msg.u.i = msg;
        dm_waiters_insert(dm,
                          dm->queues[idx].sendw,
                          &dm->queues[idx].sendw_count,
                          cur);
        dm_block_current(dm, SOS_ST_BLK_QS, qid, dl);
        dm->rc = (sos_rc_t)SOS_RC_OK;
    }
    return true;
}

/* rtos_kernel.scxml lines 464-499 — queue.receive. */
bool script_sys_idle_queue_receive_0(const sos_event_t *ev)
{
    if (ev->data.tag != SOS_EVD_QUEUE_RECEIVE) {
        struct sos_datamodel *dm = sos_kernel_state();
        dm->rc = (sos_rc_t)SOS_RC_INVAL;
        return false;
    }
    struct sos_datamodel *dm = sos_kernel_state();
    int16_t qid     = ev->data.u.queue_receive.qid;
    int64_t timeout = ev->data.u.queue_receive.timeout;
    if (qid < 0 || (size_t)qid >= SOS_MAX_QUEUES || !dm->queues[(size_t)qid].valid) {
        dm->rc = (sos_rc_t)SOS_RC_INVAL;
        return true;
    }
    size_t idx = (size_t)qid;
    if (dm->queues[idx].count > 0u) {
        /* Pop head of buf. */
        int64_t m = dm->queues[idx].buf[0];
        uint32_t n = dm->queues[idx].count;
        for (uint32_t j = 1u; j < n; ++j) {
            dm->queues[idx].buf[j - 1u] = dm->queues[idx].buf[j];
        }
        dm->queues[idx].count = n - 1u;
        sos_task_id_t cur = dm->current;
        if (cur < 0) {
            dm->rc = (sos_rc_t)SOS_RC_INVAL;
            return false;
        }
        dm->tcb[cur].msg.tag = SOS_MSG_INT;
        dm->tcb[cur].msg.u.i = m;
        /* Pull from blocked sender if any (buffered case). */
        if (dm->queues[idx].sendw_count > 0u) {
            sos_task_id_t w = dm->queues[idx].sendw[0];
            uint8_t sn = dm->queues[idx].sendw_count;
            for (uint8_t j = 1u; j < sn; ++j) {
                dm->queues[idx].sendw[j - 1u] = dm->queues[idx].sendw[j];
            }
            dm->queues[idx].sendw_count = (uint8_t)(sn - 1u);
            if (dm->tcb[w].msg.tag != SOS_MSG_INT) {
                dm->rc = (sos_rc_t)SOS_RC_INVAL;
                return false;
            }
            int64_t pending = dm->tcb[w].msg.u.i;
            dm_queue_push(dm, idx, pending);
            dm->tcb[w].msg.tag  = SOS_MSG_RC;
            dm->tcb[w].msg.u.rc = (sos_rc_t)SOS_RC_OK;
            dm_unblock(dm, w);
        }
        dm->rc = (sos_rc_t)SOS_RC_OK;
    } else if (dm->queues[idx].sendw_count > 0u) {
        /* Zero-capacity / contended path: direct sender → receiver handoff. */
        sos_task_id_t w = dm->queues[idx].sendw[0];
        uint8_t sn = dm->queues[idx].sendw_count;
        for (uint8_t j = 1u; j < sn; ++j) {
            dm->queues[idx].sendw[j - 1u] = dm->queues[idx].sendw[j];
        }
        dm->queues[idx].sendw_count = (uint8_t)(sn - 1u);
        sos_task_id_t cur = dm->current;
        if (cur < 0) {
            dm->rc = (sos_rc_t)SOS_RC_INVAL;
            return false;
        }
        if (dm->tcb[w].msg.tag != SOS_MSG_INT) {
            dm->rc = (sos_rc_t)SOS_RC_INVAL;
            return false;
        }
        int64_t pending = dm->tcb[w].msg.u.i;
        dm->tcb[cur].msg.tag = SOS_MSG_INT;
        dm->tcb[cur].msg.u.i = pending;
        dm->tcb[w].msg.tag   = SOS_MSG_RC;
        dm->tcb[w].msg.u.rc  = (sos_rc_t)SOS_RC_OK;
        dm_unblock(dm, w);
        dm->rc = (sos_rc_t)SOS_RC_OK;
    } else if (timeout == 0) {
        dm->rc = (sos_rc_t)SOS_RC_EMPTY;
    } else {
        sos_tick_t dl = (timeout < 0)
            ? 0
            : (sos_tick_t)((int64_t)dm->tick_count + timeout);
        sos_task_id_t cur = dm->current;
        if (cur < 0) {
            dm->rc = (sos_rc_t)SOS_RC_INVAL;
            return false;
        }
        dm_waiters_insert(dm,
                          dm->queues[idx].recvw,
                          &dm->queues[idx].recvw_count,
                          cur);
        dm_block_current(dm, SOS_ST_BLK_QR, qid, dl);
        dm->rc = (sos_rc_t)SOS_RC_OK;
    }
    return true;
}

/* rtos_kernel.scxml lines 502-518 — queue.send_from_isr. */
bool script_sys_idle_queue_send_from_isr_0(const sos_event_t *ev)
{
    if (ev->data.tag != SOS_EVD_QUEUE_SEND) {
        struct sos_datamodel *dm = sos_kernel_state();
        dm->rc = (sos_rc_t)SOS_RC_INVAL;
        return false;
    }
    struct sos_datamodel *dm = sos_kernel_state();
    int16_t qid = ev->data.u.queue_send.qid;
    int64_t msg = ev->data.u.queue_send.msg;
    if (qid < 0 || (size_t)qid >= SOS_MAX_QUEUES) {
        /* ISR path: silent discard. */
        return true;
    }
    size_t idx = (size_t)qid;
    if (dm->queues[idx].valid) {
        if (dm->queues[idx].recvw_count > 0u) {
            sos_task_id_t w = dm->queues[idx].recvw[0];
            uint8_t n = dm->queues[idx].recvw_count;
            for (uint8_t j = 1u; j < n; ++j) {
                dm->queues[idx].recvw[j - 1u] = dm->queues[idx].recvw[j];
            }
            dm->queues[idx].recvw_count = (uint8_t)(n - 1u);
            dm->tcb[w].msg.tag = SOS_MSG_INT;
            dm->tcb[w].msg.u.i = msg;
            dm_unblock(dm, w);
        } else if (dm->queues[idx].count < dm->queues[idx].cap) {
            dm_queue_push(dm, idx, msg);
        }
    }
    return true;
}

/* rtos_kernel.scxml lines 532-534 — crit.enter. */
bool script_prot_idle_crit_enter_0(const sos_event_t *ev)
{
    (void)ev;
    struct sos_datamodel *dm = sos_kernel_state();
    dm->irq_nest += 1;
    return true;
}

/* rtos_kernel.scxml lines 536-541 — crit.exit. */
bool script_prot_idle_crit_exit_0(const sos_event_t *ev)
{
    (void)ev;
    struct sos_datamodel *dm = sos_kernel_state();
    if (dm->irq_nest > 0) {
        dm->irq_nest -= 1;
    }
    return true;
}

/* rtos_kernel.scxml lines 543-545 — sched.suspend. */
bool script_prot_idle_sched_suspend_0(const sos_event_t *ev)
{
    (void)ev;
    struct sos_datamodel *dm = sos_kernel_state();
    dm->sched_lock += 1;
    return true;
}

/* rtos_kernel.scxml lines 547-573 — sched.resume. */
bool script_prot_idle_sched_resume_0(const sos_event_t *ev)
{
    (void)ev;
    struct sos_datamodel *dm = sos_kernel_state();
    if (dm->sched_lock > 0) {
        dm->sched_lock -= 1;
    }
    if (dm->sched_lock == 0 && dm->pend_ticks > 0) {
        while (dm->pend_ticks > 0) {
            dm->pend_ticks -= 1;
            dm->tick_count += 1;
            uint32_t n = dm->max_tasks;
            if (n > SOS_MAX_TASKS) {
                n = SOS_MAX_TASKS;
            }
            for (size_t i = 0u; i < n; ++i) {
                sos_task_state_t state    = dm->tcb[i].state;
                sos_tick_t       deadline = dm->tcb[i].deadline;
                if (state == SOS_ST_DELAY && deadline <= dm->tick_count) {
                    dm->tcb[i].msg.tag  = SOS_MSG_RC;
                    dm->tcb[i].msg.u.rc = (sos_rc_t)SOS_RC_OK;
                    dm_unblock(dm, (sos_task_id_t)i);
                } else {
                    bool is_blocked = (state == SOS_ST_BLK_SEM ||
                                       state == SOS_ST_BLK_QS  ||
                                       state == SOS_ST_BLK_QR);
                    if (is_blocked && deadline > 0 && deadline <= dm->tick_count) {
                        dm_waiter_cancel(dm, (sos_task_id_t)i);
                        dm->tcb[i].msg.tag  = SOS_MSG_RC;
                        dm->tcb[i].msg.u.rc = (sos_rc_t)SOS_RC_TIMEOUT;
                        dm_unblock(dm, (sos_task_id_t)i);
                    }
                }
            }
        }
    }
    return true;
}
