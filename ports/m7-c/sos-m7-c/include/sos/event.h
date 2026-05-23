/* sos/event.h — external-event surface (SOS-05 §6.6 / §6.2).
 *
 * Mirrors SOS-01 §5 ExternalEventName and the M7 Rust port's
 * `Event` / `EventName` / `EventData` shape in
 * `ports/m7-rust/sos-m7-rust/src/event.rs`. Discriminants are stable
 * per SOS-00 §5; adding a value requires a §15 amendment to SOS-00 /
 * SOS-01.
 *
 * Two coexisting type families are exposed:
 *
 *   1. `sos_event_kind_t` + flat `sos_event_t.{kind, task_id, arg_*, msg}`
 *      — the original skeleton shape used by `SysTick_Handler` and
 *      `sos_dispatch_event` at the kernel boundary. Retained as the
 *      stable in-kernel ABI per the §6 skeleton commits.
 *
 *   2. `sos_event_name_t` + `sos_event_data_t` (tagged union) — the
 *      typed Rust-mirror shape the wave-8 hand-rolled JSON parser
 *      produces. Mirrors `EventName` (18 variants) and `EventData`
 *      (9 variants) byte-for-byte against `sos-m7-rust/src/event.rs`.
 *
 * The parser populates `name`, `data`, and `from_tid` on the same
 * `sos_event_t` struct; the dispatcher MAY consume either family
 * depending on its phase of implementation. Phase 2 keeps both
 * surfaces alive; phase 3 will collapse onto the typed pair once
 * the dispatcher's transition bodies move to a typed-payload switch.
 */

#ifndef SOS_EVENT_H
#define SOS_EVENT_H

#include <stdint.h>

#include "sos/types.h"

#ifdef __cplusplus
extern "C" {
#endif

/* External event kinds the port dispatches into the chart. Mirrors the
 * `<raise>` targets in rtos_kernel.scxml and SOS-01 §5. The integer
 * values are local to the port; the wire-side names (in the vector JSON)
 * are the canonical identifiers. */
typedef enum {
    SOS_EVT_NONE             = 0,
    SOS_EVT_SYS_TICK         = 1,
    SOS_EVT_TASK_CREATE      = 2,
    SOS_EVT_TASK_DELAY       = 3,
    SOS_EVT_TASK_YIELD       = 4,
    SOS_EVT_TASK_SUSPEND     = 5,
    SOS_EVT_TASK_RESUME      = 6,
    SOS_EVT_SEM_CREATE       = 7,
    SOS_EVT_SEM_TAKE         = 8,
    SOS_EVT_SEM_GIVE         = 9,
    SOS_EVT_QUEUE_CREATE     = 10,
    SOS_EVT_QUEUE_SEND       = 11,
    SOS_EVT_QUEUE_RECEIVE    = 12,
    SOS_EVT_CRIT_ENTER       = 13,
    SOS_EVT_CRIT_EXIT        = 14,
    SOS_EVT_SCHED_LOCK       = 15,
    SOS_EVT_SCHED_UNLOCK     = 16
} sos_event_kind_t;

/* External event NAME — mirrors SOS-01 §5.3 `ExternalEventName` (18
 * variants at HEAD), one-to-one with `EventName` in the Rust port.
 *
 * Wire-form dotted strings (`task.create`, `sem.give_from_isr`, …) live
 * on the parser side (`sos/json_parser.h`); this enum is the in-
 * firmware representation only.
 *
 * Discriminants are NOT compatible with `sos_event_kind_t` — the latter
 * predates this enum and was used in the skeleton phase. New parser-
 * facing code SHOULD use `sos_event_name_t`. */
typedef enum {
    SOS_EVN_TASK_CREATE       = 0,
    SOS_EVN_TASK_DELAY        = 1,
    SOS_EVN_TASK_YIELD        = 2,
    SOS_EVN_TASK_SUSPEND      = 3,
    SOS_EVN_TASK_RESUME       = 4,
    SOS_EVN_SEM_CREATE        = 5,
    SOS_EVN_SEM_TAKE          = 6,
    SOS_EVN_SEM_GIVE          = 7,
    SOS_EVN_SEM_GIVE_FROM_ISR = 8,
    SOS_EVN_QUEUE_CREATE      = 9,
    SOS_EVN_QUEUE_SEND        = 10,
    SOS_EVN_QUEUE_RECEIVE     = 11,
    SOS_EVN_QUEUE_SEND_FROM_ISR = 12,
    SOS_EVN_SYS_TICK          = 13,
    SOS_EVN_CRIT_ENTER        = 14,
    SOS_EVN_CRIT_EXIT         = 15,
    SOS_EVN_SCHED_SUSPEND     = 16,
    SOS_EVN_SCHED_RESUME      = 17
} sos_event_name_t;

/* Tagged-union payload tag — mirrors `EventData` variants in the Rust
 * port. The variant choice per `sos_event_name_t` is:
 *
 *   * No payload — `task.yield`, `sys.tick`, `crit.enter`, `crit.exit`,
 *     `sched.suspend`, `sched.resume` → `SOS_EVD_NONE`.
 *   * Shared payload variants — `task.suspend` + `task.resume` share
 *     `SOS_EVD_TASK_ID`; `sem.take`/`sem.give`/`sem.give_from_isr`
 *     share `SOS_EVD_SEM_OP`; `queue.send` + `queue.send_from_isr`
 *     share `SOS_EVD_QUEUE_SEND`.
 *   * Per-name variants — `task.create`, `task.delay`, `sem.create`,
 *     `queue.create`, `queue.receive`.
 */
typedef enum {
    SOS_EVD_NONE         = 0,
    SOS_EVD_TASK_CREATE  = 1,
    SOS_EVD_TASK_DELAY   = 2,
    SOS_EVD_TASK_ID      = 3,
    SOS_EVD_SEM_CREATE   = 4,
    SOS_EVD_SEM_OP       = 5,
    SOS_EVD_QUEUE_CREATE = 6,
    SOS_EVD_QUEUE_SEND   = 7,
    SOS_EVD_QUEUE_RECEIVE = 8
} sos_event_data_tag_t;

typedef struct {
    sos_event_data_tag_t tag;
    union {
        /* SOS_EVD_NONE — no fields. */
        struct { uint8_t _unused; } none;
        /* SOS_EVD_TASK_CREATE — `task.create` `{ id, prio }`. */
        struct {
            sos_task_id_t id;
            uint8_t       prio;
        } task_create;
        /* SOS_EVD_TASK_DELAY — `task.delay` `{ ticks }`. */
        struct {
            int64_t ticks;
        } task_delay;
        /* SOS_EVD_TASK_ID — `task.suspend` / `task.resume` `{ id }`. */
        struct {
            sos_task_id_t id;
        } task_id;
        /* SOS_EVD_SEM_CREATE — `sem.create` `{ id, initial, max }`. */
        struct {
            int16_t  id;
            uint32_t initial;
            uint32_t max;
        } sem_create;
        /* SOS_EVD_SEM_OP — `sem.take`/`sem.give`/`sem.give_from_isr`
         * `{ sid, timeout }`. */
        struct {
            int16_t sid;
            int64_t timeout;
        } sem_op;
        /* SOS_EVD_QUEUE_CREATE — `queue.create` `{ id, cap }`. */
        struct {
            int16_t  id;
            uint32_t cap;
        } queue_create;
        /* SOS_EVD_QUEUE_SEND — `queue.send` / `queue.send_from_isr`
         * `{ qid, msg, timeout }`. */
        struct {
            int16_t qid;
            int64_t msg;
            int64_t timeout;
        } queue_send;
        /* SOS_EVD_QUEUE_RECEIVE — `queue.receive` `{ qid, timeout }`. */
        struct {
            int16_t qid;
            int64_t timeout;
        } queue_receive;
    } u;
} sos_event_data_t;

/* One external event injected from a vector input or a kernel-aware ISR.
 *
 * Backwards-compat fields (kind, task_id, arg_i32_0/1, arg_i64, msg)
 * are the original skeleton shape used by `sos_dispatch_event` and the
 * ISR handlers.
 *
 * The wave-8 parser populates `name`, `data`, and `from_tid_present` +
 * `from_tid` (the latter pair models the Rust Option<TaskId>). */
typedef struct {
    /* ----- Skeleton-phase fields (kernel.c / handlers.c consumers) ----- */
    sos_event_kind_t kind;
    sos_task_id_t    task_id;     /* originating / target task; -1 if N/A */
    int32_t          arg_i32_0;   /* generic int payload; meaning per kind */
    int32_t          arg_i32_1;
    int64_t          arg_i64;
    sos_msg_t        msg;

    /* ----- Typed parser-emit fields (wave 8 hand-rolled JSON parser) ----- */
    sos_event_name_t name;
    sos_event_data_t data;
    /* `from_tid` is an Option<TaskId>; the C side splits it into a
     * presence flag + the integer slot so callers don't have to invent
     * a sentinel that collides with a valid TaskId. */
    bool             from_tid_present;
    sos_task_id_t    from_tid;
} sos_event_t;

#ifdef __cplusplus
}
#endif

#endif /* SOS_EVENT_H */
