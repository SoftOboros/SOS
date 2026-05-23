/* sos/scripts.h — chart-derived script function declarations.
 *
 * Per SOS-02 §6.3 (script-name table) and SOS-05 §6.3 / §6.4. C analogue
 * of `ports/m7-rust/sos-m7-rust/src/scripts.rs`. Each `<script>` block
 * in `rtos_kernel.scxml` is transliterated 1:1 into a
 * `script_<state>_<event>_<index>` free function in `src/scripts.c`;
 * this header exposes the surface the kernel.c dispatcher binds against.
 *
 * The helper functions translating the chart's HELPERS block (lines
 * 77-165 of `rtos_kernel.scxml`) are file-static inside `src/scripts.c`
 * — they are private to the script bodies and are not exported here.
 */

#ifndef SOS_SCRIPTS_H
#define SOS_SCRIPTS_H

#include "sos/event.h"
#include "sos/types.h"

#ifdef __cplusplus
extern "C" {
#endif

/* ---------------------------------------------------------------------
 * Script bodies — one per `<script>` block in `rtos_kernel.scxml`. Each
 * returns true on success and false on a payload-shape mismatch
 * (parallels Rust's `ScriptError::WrongDataVariant` collapse). Per-
 * function doc-comments in `src/scripts.c` cite the `.scxml` line range
 * mirrored. Listed in chart document order.
 * --------------------------------------------------------------------- */

bool script_boot_onentry_0(const sos_event_t *ev);                   /* lines 172-192 */
bool script_sched_idle_sched_run_0(const sos_event_t *ev);           /* lines 210-212 */
bool script_tick_idle_sys_tick_0(const sos_event_t *ev);             /* lines 225-252 */
bool script_sys_idle_task_create_0(const sos_event_t *ev);           /* lines 270-286 */
bool script_sys_idle_task_delay_0(const sos_event_t *ev);            /* lines 289-300 */
bool script_sys_idle_task_yield_0(const sos_event_t *ev);            /* lines 302-305 */
bool script_sys_idle_task_suspend_0(const sos_event_t *ev);          /* lines 308-326 */
bool script_sys_idle_task_resume_0(const sos_event_t *ev);           /* lines 329-341 */
bool script_sys_idle_sem_create_0(const sos_event_t *ev);            /* lines 346-356 */
bool script_sys_idle_sem_take_0(const sos_event_t *ev);              /* lines 360-378 */
bool script_sys_idle_sem_give_0(const sos_event_t *ev);              /* lines 381-398 */
bool script_sys_idle_sem_give_from_isr_0(const sos_event_t *ev);     /* lines 401-415 */
bool script_sys_idle_queue_create_0(const sos_event_t *ev);          /* lines 420-432 */
bool script_sys_idle_queue_send_0(const sos_event_t *ev);            /* lines 435-461 */
bool script_sys_idle_queue_receive_0(const sos_event_t *ev);         /* lines 464-499 */
bool script_sys_idle_queue_send_from_isr_0(const sos_event_t *ev);   /* lines 502-518 */
bool script_prot_idle_crit_enter_0(const sos_event_t *ev);           /* lines 532-534 */
bool script_prot_idle_crit_exit_0(const sos_event_t *ev);            /* lines 536-541 */
bool script_prot_idle_sched_suspend_0(const sos_event_t *ev);        /* lines 543-545 */
bool script_prot_idle_sched_resume_0(const sos_event_t *ev);         /* lines 547-573 */

#ifdef __cplusplus
}
#endif

#endif /* SOS_SCRIPTS_H */
