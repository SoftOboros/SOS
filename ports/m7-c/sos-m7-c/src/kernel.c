/* kernel.c — kernel-global state + boot init + event dispatcher.
 *
 * Per SOS-05-CONCEPTS.md §6.3 (static allocations) and §6.7 (critical
 * sections). The chart-derived script bodies (HELPERS block + the 20
 * transition `<script>` blocks from `rtos_kernel.scxml`) live in
 * `src/scripts.c` per SOS-05a (refactor 2026-05-21, no behaviour
 * change). The dispatcher's switch table stays here as the kernel's
 * canonical event entrypoint.
 */

#include "sos/kernel.h"
#include "sos/scripts.h"
#include "sos/stm32h747_minimal.h"
#include "sos/trace.h"
#include "sos/types.h"

/* ----- Kernel-global state (definition hoisted to sos/kernel.h per the
 * wave-9 trace.c agent's drift-risk flag; one canonical layout shared by
 * trace.c + kernel.c). The storage lives here as the single owning TU;
 * `sos_kernel_state()` is the accessor. */

static struct sos_datamodel g_dm;

/* Per-task PSP regions, in .task_stacks linker section (AXISRAM). */
static uint32_t task_stacks[SOS_MAX_TASKS][SOS_TASK_STACK_BYTES / 4u]
    __attribute__((section(".task_stacks"), aligned(8)));

/* Silence unused-static warnings under -Wunused at v1; the regions are
 * referenced by phase-3 PendSV PSP wiring. */
__attribute__((used)) static void *_kernel_keepalive[] = {
    (void *)&g_dm,
    (void *)task_stacks
};

/* USART1 NVIC priority per SOS-00 §6.2 (kernel-aware *_from_isr band).
 * The IRQ is programmed here but NOT enabled — phase 3 owns the IRQ-
 * driven RX path. The priority is set at boot so the phase-3 unmask
 * lands a no-op of priority sequencing. */
#define SOS_PRIO_USART1   0xA0u

/* ----- Critical-section wrappers (SOS-05 §6.7 / SOS-00 §6.5) ----- */

void sos_crit_enter(void)
{
    /* BASEPRI raise to 0xA0 with DSB+ISB ordering. CMSIS-Core's
     * `__set_BASEPRI` is supplied by `sos/stm32h747_minimal.h` (the
     * port's hand-coded CMSIS-Core subset). */
    __set_BASEPRI(0xA0u);
    __DSB();
    __ISB();
}

void sos_crit_exit(void)
{
    __DSB();
    __ISB();
    __set_BASEPRI(0u);
}

/* ----- Datamodel accessor (handlers + tests need this) ----- */

/* Return a pointer to the kernel-global datamodel. Forward declared in
 * sos/kernel.h once the cross-module need lands (phase 3); at v1 the
 * accessor is internal-only and lives here as the single owning TU. */
struct sos_datamodel *sos_kernel_state(void);

struct sos_datamodel *sos_kernel_state(void)
{
    return &g_dm;
}

/* ----- Initialisation (SOS-05 §6.8 step 6) ----- */

void sos_kernel_init(void)
{
    /* Defense-in-depth: §6.7 wrap. `sos_kernel_init` runs at boot
     * before any kernel-aware IRQ is unmasked (USART1 stays masked at
     * the NVIC; SysTick is already enabled by `sos_bsp_init` but its
     * handler safely no-ops on an empty datamodel — `g_dm.resched` is
     * false, no task is RUNNING, no `pend_ticks` accumulation matters
     * because `tick_count` is still zero at entry). The BASEPRI raise
     * is correctness for `INV-S5`-style block-under-critical
     * symmetry and costs ~3 cycles. */
    sos_crit_enter();

    /* 1. Zero the full datamodel. C-language equivalent of the Rust
     *    port's "build a default Datamodel in place" pattern in
     *    `kernel.rs::init()`. */
    {
        uint8_t *p = (uint8_t *)&g_dm;
        for (size_t i = 0u; i < sizeof(g_dm); ++i) {
            p[i] = 0u;
        }
    }

    /* 2. Dimensional constants (mirror sim::datamodel::Datamodel
     *    initializer fields). */
    g_dm.max_tasks   = SOS_MAX_TASKS;
    g_dm.max_prio    = SOS_MAX_PRIO;
    g_dm.max_sems    = SOS_MAX_SEMS;
    g_dm.max_queues  = SOS_MAX_QUEUES;
    g_dm.q_depth     = SOS_Q_DEPTH;

    /* 3. Initialise every TCB slot to DORMANT defaults. The bulk-zero
     *    in step 1 already cleared the storage, but slot id and the
     *    msg-tag enum need explicit values for the discriminant /
     *    "no message" sentinel (DORMANT = 0 is the bulk-zero result;
     *    blk_obj = -1 needs an explicit write because 0 is a valid
     *    sem/queue index). */
    for (size_t i = 0u; i < SOS_MAX_TASKS; ++i) {
        g_dm.tcb[i].id           = (sos_task_id_t)i;
        g_dm.tcb[i].prio         = 0;
        g_dm.tcb[i].state        = SOS_ST_DORMANT;
        g_dm.tcb[i].deadline     = 0;
        g_dm.tcb[i].blk_obj      = -1;
        g_dm.tcb[i].msg.tag      = SOS_MSG_NULL;
        g_dm.tcb[i].msg.u.i      = 0;
        g_dm.tcb[i].psp          = NULL;
        g_dm.tcb[i].psp_top      = NULL;
        g_dm.tcb[i].frame_has_fp = 0u;
    }

    /* 4. Semaphore pool: each slot is invalid until sem_create raises
     *    the valid flag. Bulk-zero already cleared everything; explicit
     *    `valid = false` makes intent obvious to a reviewer scanning
     *    boot state. */
    for (size_t i = 0u; i < SOS_MAX_SEMS; ++i) {
        g_dm.sems[i].valid        = false;
        g_dm.sems[i].count        = 0u;
        g_dm.sems[i].max          = 0u;
        g_dm.sems[i].waiter_count = 0u;
    }

    /* 5. Queue pool: same shape as sem pool. */
    for (size_t i = 0u; i < SOS_MAX_QUEUES; ++i) {
        g_dm.queues[i].valid       = false;
        g_dm.queues[i].cap         = 0u;
        g_dm.queues[i].count       = 0u;
        g_dm.queues[i].sendw_count = 0u;
        g_dm.queues[i].recvw_count = 0u;
    }

    /* 6. Ready pool counts cleared (bulk-zero already did this, but
     *    explicit init matches the per-pool clarity above). */
    for (size_t p = 0u; p < SOS_MAX_PRIO; ++p) {
        g_dm.ready_count[p] = 0u;
    }

    /* 7. Idle (TCB[0]): promote to RUNNING at boot — mirrors the chart's
     *    `<boot>` `ready_push(0); pick_next()` sequence and sim's
     *    `Datamodel::new`. Per first-bench finding 2026-05-21 + SOS-04
     *    Amendment 010 (mirrored for SOS-05): boot baseline MUST observe
     *    current=0 / tcb[0]=Running for SOS-03 vector-0001's
     *    expected_trace to match. ready[] stays empty: pick_next pops
     *    idle off ready[0] AND assigns current = 0 in one step. */
    g_dm.tcb[0].state              = SOS_ST_RUNNING;
    g_dm.tcb[0].prio               = 0;
    g_dm.ready_count[0]            = 0u;

    /* 8. Scalar fields. */
    g_dm.current     = 0;
    g_dm.tick_count  = 0;
    g_dm.rc          = (sos_rc_t)SOS_RC_OK;
    g_dm.irq_nest    = 0;
    g_dm.sched_lock  = 0;
    g_dm.pend_ticks  = 0;
    g_dm.resched     = false;

    /* 9. USART1 NVIC priority. The IRQ is left masked; phase 3 enables
     *    it after wiring the IRQ-driven RX path in transport.c. */
    NVIC->IPR[USART1_IRQn] = SOS_PRIO_USART1;

    sos_crit_exit();
}

/* ====================================================================
 * Top-level dispatcher — typed event name → script body.
 *
 * Mirrors sos-m7-rust/src/scripts.rs::dispatch_event with the same
 * macrostep semantics: if a per-event script sets `dm->resched`, run
 * the scheduler microstep to settle to quiescence. Returns whether the
 * currently-running task changed (so the caller MAY pend PendSV).
 *
 * The chart-derived script bodies live in `src/scripts.c`; the
 * prototypes used below are imported from `sos/scripts.h`.
 * ==================================================================== */

bool sos_dispatch_event(const sos_event_t *ev)
{
    if (ev == NULL) {
        return false;
    }
    struct sos_datamodel *dm = sos_kernel_state();
    sos_task_id_t before = dm->current;
    bool ok = false;
    switch (ev->name) {
        case SOS_EVN_TASK_CREATE:
            ok = script_sys_idle_task_create_0(ev);
            break;
        case SOS_EVN_TASK_DELAY:
            ok = script_sys_idle_task_delay_0(ev);
            break;
        case SOS_EVN_TASK_YIELD:
            ok = script_sys_idle_task_yield_0(ev);
            break;
        case SOS_EVN_TASK_SUSPEND:
            ok = script_sys_idle_task_suspend_0(ev);
            break;
        case SOS_EVN_TASK_RESUME:
            ok = script_sys_idle_task_resume_0(ev);
            break;
        case SOS_EVN_SEM_CREATE:
            ok = script_sys_idle_sem_create_0(ev);
            break;
        case SOS_EVN_SEM_TAKE:
            ok = script_sys_idle_sem_take_0(ev);
            break;
        case SOS_EVN_SEM_GIVE:
            ok = script_sys_idle_sem_give_0(ev);
            break;
        case SOS_EVN_SEM_GIVE_FROM_ISR:
            ok = script_sys_idle_sem_give_from_isr_0(ev);
            break;
        case SOS_EVN_QUEUE_CREATE:
            ok = script_sys_idle_queue_create_0(ev);
            break;
        case SOS_EVN_QUEUE_SEND:
            ok = script_sys_idle_queue_send_0(ev);
            break;
        case SOS_EVN_QUEUE_RECEIVE:
            ok = script_sys_idle_queue_receive_0(ev);
            break;
        case SOS_EVN_QUEUE_SEND_FROM_ISR:
            ok = script_sys_idle_queue_send_from_isr_0(ev);
            break;
        case SOS_EVN_SYS_TICK:
            ok = script_tick_idle_sys_tick_0(ev);
            break;
        case SOS_EVN_CRIT_ENTER:
            ok = script_prot_idle_crit_enter_0(ev);
            break;
        case SOS_EVN_CRIT_EXIT:
            ok = script_prot_idle_crit_exit_0(ev);
            break;
        case SOS_EVN_SCHED_SUSPEND:
            ok = script_prot_idle_sched_suspend_0(ev);
            break;
        case SOS_EVN_SCHED_RESUME:
            ok = script_prot_idle_sched_resume_0(ev);
            break;
        default:
            return false;
    }
    /* Macrostep: if the per-event script raised `resched`, settle. */
    if (ok && dm->resched) {
        dm->resched = false;
        (void)script_sched_idle_sched_run_0(ev);
    }
    /* Return: did the currently-running task change? */
    return ok && (dm->current != before);
}

/* Reference the boot-onentry parity stub so -Wunused-function does not
 * trip; the dispatcher does not invoke it (sos_kernel_init owns the
 * boot baseline) but the symbol is part of the documented script
 * surface. */
__attribute__((used)) static bool (* const _script_boot_keepalive)(const sos_event_t *) =
    &script_boot_onentry_0;

/* ----- TCB-layout lock (SOS-05 §6.4 PendSV body) ----- */

/* The PendSV asm in src/handlers.c indexes tcb_pool with a constant
 * stride; lock the structure size against silent reorderings. The
 * concrete stride is checked at phase 3 (when the PendSV body lands;
 * v1 records the assumption explicitly. */
_Static_assert(sizeof(sos_tcb_t) <= 64,
               "sos_tcb_t must fit in 64 bytes for PendSV indexing");
