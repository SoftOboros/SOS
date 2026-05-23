/* trace.c — hand-rolled JSONL trace writer for the SOS-05 M7 C port.
 *
 * Per SOS-05-CONCEPTS.md §6.2 and PCDN-SOS-05-008 (which parallels
 * PCDN-SOS-04-008): the writer emits one TraceRecord byte-for-byte
 * identical to what `sos-sim` produces via `serde_json::to_writer`
 * (INV-S-PORT-9 / INV-S-SIM-1). The C writer mirrors the canonical
 * Rust writer at ports/m7-rust/sos-m7-rust-trace/src/lib.rs::emit_record
 * call-for-call so a reviewer can diff the two side-by-side.
 *
 * Wire-format contract (SOS-02 §7 + §15 Amendment 001):
 *   - JSONL: one JSON object per record, LF-terminated, no internal
 *     whitespace, no leading BOM.
 *   - Field order: after_input_idx, current, tick_count, rc, tcb,
 *     ready, sems, queues, irq_nest, sched_lock, pend_ticks.
 *   - Per-TCB field order: id, prio, state, deadline, blk_obj, msg.
 *   - Msg encoding (SOS-00 §5.6 Amendment 004):
 *       SOS_MSG_NULL → `null`
 *       SOS_MSG_INT  → bare signed decimal integer
 *       SOS_MSG_RC   → `{"rc":<i8>}`
 *   - Sem/Queue: short form `{"valid":false}` when invalid; long form
 *     when valid (sem: valid,count,max,waiters | queue:
 *     valid,cap,count,buf,sendw,recvw).
 *   - All TaskId / blk_obj values widen from i16 → i32 on the wire.
 *   - irq_nest, sched_lock, pend_ticks emit as non-negative decimal
 *     integers (in-memory `int32_t` widened to `i64` for the helper).
 *
 * Implementation policy:
 *   - No snprintf / printf. picolibc dependency surface is large and
 *     byte-stability across libc versions is not contracted; a hand-
 *     rolled reverse-digit accumulator is byte-stable by construction.
 *   - No static mutable state — `sos_trace_writer_t` is the entire
 *     mutable surface and lives on the caller's stack.
 *   - On buffer overrun the writer continues bumping `pos` past `cap`
 *     so the caller sees the would-have-been length; bytes past `cap`
 *     are silently dropped. The caller MUST treat `return_value > cap`
 *     as a truncation and reject the record. This matches the SOS-04
 *     Rust writer's "clamp at cap, return truncation point" pattern in
 *     intent: both signal overflow without UB.
 */

#include "sos/kernel.h"
#include "sos/trace.h"
#include "sos/types.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* `struct sos_datamodel` layout lives in sos/kernel.h (hoisted from the
 * wave-9 trace.c agent's local mirror per its own drift-risk flag). One
 * canonical definition; no INV-S-PORT-9 hazard. */

/* ----- Writer state --------------------------------------------------
 *
 * `pos` is allowed to advance past `cap`: bytes beyond `cap` are not
 * stored but `pos` keeps incrementing, so the return value reflects the
 * full intended record length and the caller can detect truncation by
 * comparing `return_value` against `cap`. `overrun` is sticky once set.
 */
typedef struct {
    uint8_t *buf;
    size_t   cap;
    size_t   pos;
    bool     overrun;
} sos_trace_writer_t;

/* ----- Primitive emitters -------------------------------------------- */

static inline void w_byte(sos_trace_writer_t *w, uint8_t b)
{
    if (w->pos < w->cap) {
        w->buf[w->pos] = b;
    } else {
        w->overrun = true;
    }
    w->pos += 1u;
}

static inline void w_str(sos_trace_writer_t *w, const char *s)
{
    /* Walks the string until NUL. No locale dependence; all callers
     * pass ASCII literals known at compile time. */
    while (*s != '\0') {
        w_byte(w, (uint8_t)*s);
        ++s;
    }
}

/* Reverse-digit-accumulate signed decimal writer. The algorithm:
 *   1. Capture sign; convert to unsigned-positive magnitude. INT64_MIN
 *      is the one corner case where `-v` overflows i64 — we treat the
 *      magnitude via `(uint64_t)-(v + 1) + 1u` which is value-equal to
 *      `2^63` without invoking signed overflow UB.
 *   2. Emit digits into a 20-byte buffer LSB-first; `0` is the
 *      special case (one digit '0').
 *   3. Emit the leading '-' if applicable, then the digits in reverse.
 *
 * The buffer size 20 holds INT64_MIN's 19 digits + one byte of slack.
 * The result is byte-equivalent to `core::fmt::Display` on i64 in Rust
 * (no leading '+', no leading zeros except for the literal `0`, no
 * trailing whitespace, no thousands separators).
 */
static void w_i64(sos_trace_writer_t *w, int64_t v)
{
    uint8_t digits[20];
    size_t  n = 0u;
    uint64_t mag;
    bool     neg = false;

    if (v < 0) {
        neg = true;
        /* Compute |v| without invoking signed overflow on INT64_MIN. */
        mag = (uint64_t)(-(v + 1)) + 1u;
    } else {
        mag = (uint64_t)v;
    }

    if (mag == 0u) {
        digits[n++] = (uint8_t)'0';
    } else {
        while (mag > 0u) {
            digits[n++] = (uint8_t)('0' + (mag % 10u));
            mag /= 10u;
        }
    }

    if (neg) {
        w_byte(w, (uint8_t)'-');
    }
    /* Flush reversed. */
    while (n > 0u) {
        n -= 1u;
        w_byte(w, digits[n]);
    }
}

/* Unsigned 64-bit writer. Used for `count`, `max`, `cap`, and the
 * widened `irq_nest` / `sched_lock` / `pend_ticks` (although those are
 * non-negative `int32_t` in this port and could equally route through
 * `w_i64`; the explicit unsigned helper documents intent at the call
 * site). */
static void w_u64(sos_trace_writer_t *w, uint64_t v)
{
    uint8_t digits[20];
    size_t  n = 0u;

    if (v == 0u) {
        w_byte(w, (uint8_t)'0');
        return;
    }
    while (v > 0u) {
        digits[n++] = (uint8_t)('0' + (v % 10u));
        v /= 10u;
    }
    while (n > 0u) {
        n -= 1u;
        w_byte(w, digits[n]);
    }
}

/* ----- Composite emitters -------------------------------------------- */

static void w_id_array(sos_trace_writer_t *w,
                       const sos_task_id_t *ids,
                       size_t n)
{
    w_byte(w, (uint8_t)'[');
    for (size_t i = 0u; i < n; ++i) {
        if (i > 0u) {
            w_byte(w, (uint8_t)',');
        }
        /* SOS-02 §7.2: TaskId widens i16 → i32 on the wire. Casting via
         * (int64_t) for the helper is value-preserving (i16 < i32 <
         * i64). */
        w_i64(w, (int64_t)ids[i]);
    }
    w_byte(w, (uint8_t)']');
}

static void w_i64_array(sos_trace_writer_t *w,
                        const int64_t *vals,
                        size_t n)
{
    w_byte(w, (uint8_t)'[');
    for (size_t i = 0u; i < n; ++i) {
        if (i > 0u) {
            w_byte(w, (uint8_t)',');
        }
        w_i64(w, vals[i]);
    }
    w_byte(w, (uint8_t)']');
}

static void w_msg(sos_trace_writer_t *w, const sos_msg_t *m)
{
    switch (m->tag) {
    case SOS_MSG_NULL:
        w_str(w, "null");
        break;
    case SOS_MSG_INT:
        w_i64(w, m->u.i);
        break;
    case SOS_MSG_RC:
        /* SOS-00 §5.6 Amendment 004: discriminator object form. The
         * `rc` field carries an i8 in memory; widening to i64 for the
         * helper is value-preserving. */
        w_str(w, "{\"rc\":");
        w_i64(w, (int64_t)m->u.rc);
        w_byte(w, (uint8_t)'}');
        break;
    default:
        /* Unreachable per SOS-00 §5.6 enum closure; emit `null` as a
         * defensive fallback rather than corrupting the record. */
        w_str(w, "null");
        break;
    }
}

static void w_tcb(sos_trace_writer_t *w, const sos_tcb_t *tcb)
{
    /* Field order per SOS-02 §7.2 + sos_sim::TcbSnapshot declaration:
     * id, prio, state, deadline, blk_obj, msg. */
    w_str(w, "{\"id\":");
    w_i64(w, (int64_t)tcb->id);

    w_str(w, ",\"prio\":");
    /* SOS-02 §7.2: `prio` is `u8`, emitted as unsigned. The in-memory
     * type here is `sos_prio_t = int8_t` — the chart's value range is
     * 0..MAX_PRIO so the wire byte sequence is identical, but we route
     * via `w_u64` after a non-negative cast to keep the wire form
     * unsigned-decimal-shaped per the spec. */
    w_u64(w, (uint64_t)(uint8_t)tcb->prio);

    w_str(w, ",\"state\":");
    /* TaskState discriminants 0..7 (SOS-00 §5.1). Emit as unsigned. */
    w_u64(w, (uint64_t)(uint8_t)tcb->state);

    w_str(w, ",\"deadline\":");
    /* `deadline` is `sos_tick_t = int32_t`; widen to i64 for the
     * helper, value-preserving. */
    w_i64(w, (int64_t)tcb->deadline);

    w_str(w, ",\"blk_obj\":");
    w_i64(w, (int64_t)tcb->blk_obj);

    w_str(w, ",\"msg\":");
    w_msg(w, &tcb->msg);

    w_byte(w, (uint8_t)'}');
}

static void w_sem(sos_trace_writer_t *w, const sos_sem_t *s)
{
    if (!s->valid) {
        /* SOS-02 §7.2 short form (SOS-03 PCDN-007). */
        w_str(w, "{\"valid\":false}");
        return;
    }
    /* Long form: valid, count, max, waiters. */
    w_str(w, "{\"valid\":true,\"count\":");
    w_u64(w, (uint64_t)s->count);
    w_str(w, ",\"max\":");
    w_u64(w, (uint64_t)s->max);
    w_str(w, ",\"waiters\":");
    /* `waiters[0..waiter_count]` per the wave-7 sos_sem_t typedef. */
    w_id_array(w, s->waiters, (size_t)s->waiter_count);
    w_byte(w, (uint8_t)'}');
}

static void w_queue(sos_trace_writer_t *w, const sos_queue_t *q)
{
    if (!q->valid) {
        w_str(w, "{\"valid\":false}");
        return;
    }
    /* Long form: valid, cap, count, buf, sendw, recvw. */
    w_str(w, "{\"valid\":true,\"cap\":");
    w_u64(w, (uint64_t)q->cap);
    w_str(w, ",\"count\":");
    w_u64(w, (uint64_t)q->count);
    w_str(w, ",\"buf\":");
    /* `buf[0..count]` — the staged payloads in FIFO order. */
    w_i64_array(w, q->buf, (size_t)q->count);
    w_str(w, ",\"sendw\":");
    w_id_array(w, q->sendw, (size_t)q->sendw_count);
    w_str(w, ",\"recvw\":");
    w_id_array(w, q->recvw, (size_t)q->recvw_count);
    w_byte(w, (uint8_t)'}');
}

/* ----- Top-level emitter --------------------------------------------- */

size_t sos_trace_write_record(uint8_t *buf, size_t cap,
                              const struct sos_datamodel *dm,
                              int64_t after_input_idx)
{
    sos_trace_writer_t w = {
        .buf     = buf,
        .cap     = cap,
        .pos     = 0u,
        .overrun = false,
    };

    /* SOS-02 §7.1 field order: after_input_idx, current, tick_count,
     * rc, tcb, ready, sems, queues, irq_nest, sched_lock, pend_ticks. */

    w_str(&w, "{\"after_input_idx\":");
    w_i64(&w, after_input_idx);

    w_str(&w, ",\"current\":");
    /* TaskId widens i16 → i32 on the wire (SOS-02 §7.2 + §15 Amendment 001). */
    w_i64(&w, (int64_t)dm->current);

    w_str(&w, ",\"tick_count\":");
    /* `tick_count` is `sos_tick_t = int32_t`; widen losslessly. */
    w_i64(&w, (int64_t)dm->tick_count);

    w_str(&w, ",\"rc\":");
    /* `rc` is `sos_rc_t = int8_t` (SOS-00 §5.2 discriminants). */
    w_i64(&w, (int64_t)dm->rc);

    /* ----- tcb array ----- */
    w_str(&w, ",\"tcb\":[");
    for (size_t i = 0u; i < SOS_MAX_TASKS; ++i) {
        if (i > 0u) {
            w_byte(&w, (uint8_t)',');
        }
        w_tcb(&w, &dm->tcb[i]);
    }
    w_byte(&w, (uint8_t)']');

    /* ----- ready array (length MAX_PRIO, each inner is [ids...]) ----- */
    w_str(&w, ",\"ready\":[");
    for (size_t p = 0u; p < SOS_MAX_PRIO; ++p) {
        if (p > 0u) {
            w_byte(&w, (uint8_t)',');
        }
        /* Inner array: `ready_pool[p][0..ready_count[p]]`. */
        w_id_array(&w, dm->ready_pool[p], (size_t)dm->ready_count[p]);
    }
    w_byte(&w, (uint8_t)']');

    /* ----- sems array ----- */
    w_str(&w, ",\"sems\":[");
    for (size_t i = 0u; i < SOS_MAX_SEMS; ++i) {
        if (i > 0u) {
            w_byte(&w, (uint8_t)',');
        }
        w_sem(&w, &dm->sems[i]);
    }
    w_byte(&w, (uint8_t)']');

    /* ----- queues array ----- */
    w_str(&w, ",\"queues\":[");
    for (size_t i = 0u; i < SOS_MAX_QUEUES; ++i) {
        if (i > 0u) {
            w_byte(&w, (uint8_t)',');
        }
        w_queue(&w, &dm->queues[i]);
    }
    w_byte(&w, (uint8_t)']');

    /* ----- trailing scalar fields ----- */
    w_str(&w, ",\"irq_nest\":");
    /* `irq_nest` is `int32_t` in the C port, always non-negative per
     * the chart. Widen to i64 to route through the signed helper —
     * byte-equivalent to the Rust `write!(w, "{}", input.irq_nest)`
     * on a non-negative `u32`. */
    w_i64(&w, (int64_t)dm->irq_nest);

    w_str(&w, ",\"sched_lock\":");
    w_i64(&w, (int64_t)dm->sched_lock);

    w_str(&w, ",\"pend_ticks\":");
    w_i64(&w, (int64_t)dm->pend_ticks);

    w_byte(&w, (uint8_t)'}');

    /* JSONL framing — exactly one LF terminates the record (SOS-02 §6.5). */
    w_byte(&w, (uint8_t)'\n');

    return w.pos;
}
