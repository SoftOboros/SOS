/* sos/types.h — frozen-enum / typedef surface for the SOS M7 C port.
 *
 * Per SOS-05-CONCEPTS.md §6.3 (static allocations + C typedefs) and
 * §5 (frozen enums). Discriminants match SOS-00 §5.1 / §5.2 exactly so
 * trace bytes are byte-identical to sos-sim's output (INV-S-PORT-9).
 *
 * Skeleton commit: typedefs + dimensional constants. No function bodies.
 */

#ifndef SOS_TYPES_H
#define SOS_TYPES_H

#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>

/* ----- Dimensional constants (SOS-05 §6.3) ----- */

#define SOS_MAX_TASKS        8u
#define SOS_MAX_PRIO         8u
#define SOS_MAX_SEMS         8u
#define SOS_MAX_QUEUES       4u
#define SOS_Q_DEPTH         16u
#define SOS_TASK_STACK_BYTES 1024u   /* per-task PSP region; AXISRAM .task_stacks */
#define SOS_KERNEL_STACK_BYTES 4096u /* MSP backing store; top of DTCM */
#define SOS_TICK_HZ          1000u   /* SysTick 1 kHz per SOS-00 §6.6 */

/* ----- Frozen scalar typedefs (SOS-05 §6.3 / SOS-00 §5) ----- */

/* Task identifier. Chart uses `-1` as the "none" sentinel; the port
 * realises as a signed type. SOS-04 Amendment 001 widens to i16. */
typedef int16_t sos_task_id_t;

/* Syscall return code. Mirrors SOS-00 §5.2. */
typedef int8_t  sos_rc_t;

/* Monotonic tick counter / deadline / pend_ticks. */
typedef int32_t sos_tick_t;

/* Priority band index. */
typedef int8_t  sos_prio_t;

/* ----- Frozen enums (SOS-00 §5.1 / §5.2 / §5.6) ----- */

typedef enum {
    SOS_ST_DORMANT  = 0,
    SOS_ST_READY    = 1,
    SOS_ST_RUNNING  = 2,
    SOS_ST_DELAY    = 3,
    SOS_ST_BLK_SEM  = 4,
    SOS_ST_BLK_QS   = 5,
    SOS_ST_BLK_QR   = 6,
    SOS_ST_SUSPEND  = 7
} sos_task_state_t;

enum {
    SOS_RC_OK      =  0,
    SOS_RC_TIMEOUT = -1,
    SOS_RC_FULL    = -2,
    SOS_RC_EMPTY   = -3,
    SOS_RC_INVAL   = -4
};

/* SOS-00 §5.6 Msg as a tagged union. The on-wire form is JSON-
 * discriminated per SOS-02 §7.2; the in-memory form is C-tagged. */
typedef enum {
    SOS_MSG_NULL = 0,
    SOS_MSG_INT  = 1,
    SOS_MSG_RC   = 2
} sos_msg_tag_t;

typedef struct {
    sos_msg_tag_t tag;
    union {
        int64_t i;
        sos_rc_t rc;
    } u;
} sos_msg_t;

/* ----- TCB (SOS-05 §6.3) ----- */

typedef struct {
    sos_task_id_t    id;
    sos_prio_t       prio;
    sos_task_state_t state;
    sos_tick_t       deadline;
    int16_t          blk_obj;     /* -1 when unblocked; else sem/queue index */
    sos_msg_t        msg;
    uint32_t        *psp;         /* saved PSP pointer (PendSV target) */
    uint32_t        *psp_top;     /* initial top of TCB's stack region */
    uint8_t          frame_has_fp;
    uint8_t          _pad[3];
} sos_tcb_t;

/* ----- Semaphore / queue descriptors (SOS-05 §6.3) ----- */

typedef struct {
    bool          valid;
    uint32_t      count;
    uint32_t      max;
    sos_task_id_t waiters[SOS_MAX_TASKS];
    uint8_t       waiter_count;
} sos_sem_t;

typedef struct {
    bool          valid;
    int64_t       buf[SOS_Q_DEPTH];
    uint32_t      cap;
    uint32_t      count;
    sos_task_id_t sendw[SOS_MAX_TASKS];
    uint8_t       sendw_count;
    sos_task_id_t recvw[SOS_MAX_TASKS];
    uint8_t       recvw_count;
} sos_queue_t;

/* ----- Layout invariants (PCDN-SOS-05-004 — C11 _Static_assert) ----- */

_Static_assert(sizeof(sos_task_id_t) == 2,
               "Task ID must be int16_t per SOS-04 Amendment 001");
_Static_assert(sizeof(sos_rc_t) == 1,
               "Return code must be int8_t per SOS-00 §5.2");
_Static_assert(sizeof(sos_tick_t) == 4,
               "Tick counter must be int32_t per SOS-05 §6.3");

#endif /* SOS_TYPES_H */
