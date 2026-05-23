/* sos/kernel.h — public kernel API surface (SOS-05 §6.1 / §6.3 / §6.7).
 *
 * The chart's <script> bodies are transliterated into src/kernel.c per
 * SOS-05 §6.1 + SOS-02 §6.3. Skeleton commit: prototypes only.
 */

#ifndef SOS_KERNEL_H
#define SOS_KERNEL_H

#include "sos/event.h"
#include "sos/types.h"

#ifdef __cplusplus
extern "C" {
#endif

/* ----- Datamodel (canonical layout; SOS-05 §6.3) -----
 *
 * The full kernel state mirroring `sim::datamodel::Datamodel`. Field order
 * matches SOS-02 §7.1 trace serialisation so the hand-rolled writer in
 * `trace.c` emits the bytes the harness expects. Declared here (rather
 * than file-static in kernel.c per the wave-9 trace.c agent's
 * "two-copies = drift risk" flag) so trace.c and any future TU read the
 * single canonical layout. */
struct sos_datamodel {
    uint32_t       max_tasks;
    uint32_t       max_prio;
    uint32_t       max_sems;
    uint32_t       max_queues;
    uint32_t       q_depth;
    sos_tcb_t      tcb[SOS_MAX_TASKS];
    sos_task_id_t  ready_pool[SOS_MAX_PRIO][SOS_MAX_TASKS];
    uint8_t        ready_count[SOS_MAX_PRIO];
    sos_task_id_t  current;
    sos_tick_t     tick_count;
    sos_rc_t       rc;
    int32_t        irq_nest;
    int32_t        sched_lock;
    int32_t        pend_ticks;
    sos_sem_t      sems[SOS_MAX_SEMS];
    sos_queue_t    queues[SOS_MAX_QUEUES];
    bool           resched;
};

/* Return a pointer to the kernel-global `struct sos_datamodel`. The
 * underlying storage is owned by kernel.c; handlers / transport / trace
 * call this accessor to reach kernel state. */
struct sos_datamodel *sos_kernel_state(void);

/* ----- Initialisation (SOS-05 §6.8 boot path) ----- */

/* Zero pools, promote idle (tcb[0]) to RUNNING, program NVIC priorities
 * per SOS-00 §6.2. Called once from main() after disco_bsp::init(). */
void sos_kernel_init(void);

/* ----- Event dispatch (SOS-05 §6.2 / §6.6) ----- */

/* Dispatch one external event into the chart, run the resulting
 * macrostep to quiescence, and return whether the currently-running
 * task changed (caller MAY pend PendSV if true). */
bool sos_dispatch_event(const sos_event_t *ev);

/* ----- Critical section wrappers (SOS-05 §6.7 / SOS-00 §6.5) ----- */

/* Raise BASEPRI to 0xA0 with DSB+ISB. */
void sos_crit_enter(void);

/* Lower BASEPRI to 0x00 with DSB+ISB. */
void sos_crit_exit(void);

#ifdef __cplusplus
}
#endif

#endif /* SOS_KERNEL_H */
