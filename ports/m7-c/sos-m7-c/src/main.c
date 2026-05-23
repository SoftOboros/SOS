/* main.c — SOS-05 firmware entry point.
 *
 * Per SOS-05-CONCEPTS.md §6.2 (conformance-mode harness), §6.8 (boot
 * path), PCDN-SOS-04-005 (adapter-filtered done sentinel), and
 * PCDN-SOS-04-016 (interrupt-driven USART). The boot path mirrors the
 * Rust port at `ports/m7-rust/sos-m7-rust/src/main.rs`:
 *
 *   sos_bsp_init()          — clocks + GPIO AF + USART1 8N1 FIFO + SysTick.
 *   sos_kernel_init()       — pool zero + idle TCB to READY + NVIC pri.
 *   sos_uart_start_rx_irq() — RXNEIE + unmask USART1 NVIC line.
 *   emit boot-baseline trace record (after_input_idx = -1).
 *   Conformance-mode macrostep dispatch loop:
 *     - Refill 4 KiB scratch from the IRQ-fed RX ring (non-blocking).
 *     - Drive the hand-rolled JSON parser; consume one parse step:
 *         · NeedMoreInput   → wfi until next USART1 IRQ.
 *         · VectorHeader    → validate against compile-time dimensions.
 *         · Event           → set current = from_tid if present, call
 *                              sos_dispatch_event, emit trace record.
 *         · EndOfInput      → emit done sentinel, park.
 *         · Error           → emit done sentinel, park.
 *
 * The done sentinel is `{"__sos_done":true}\n` — hand-rolled byte
 * sequence per PCDN-SOS-04-005 + INV-S-PORT-12, intentionally not a
 * TraceRecord (no after_input_idx, no tcb). The host-side adapter
 * filters it before the harness sees it.
 */

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "sos/bsp.h"
#include "sos/event.h"
#include "sos/json_parser.h"
#include "sos/kernel.h"
#include "sos/stm32h747_minimal.h"
#include "sos/trace.h"
#include "sos/types.h"

/* RX scratch buffer size. Matches `SOS_RX_RING_CAPACITY` in transport.c
 * (4 KiB) so the parser can hold a full wrapped vector input in the
 * worst case (one full ring's worth of bytes between two parse steps).
 * Per SOS-04 §6.2.1 prose this is approximately one full vector for the
 * seed-vector suite. */
#define SOS_RX_SCRATCH_BYTES    4096u

/* Trace-record scratch buffer size. Per `trace.c`: ~2 KiB suffices for
 * any seed-vector record at the canonical dimensional defaults. */
#define SOS_TRACE_SCRATCH_BYTES 2048u

static uint8_t s_rx_scratch[SOS_RX_SCRATCH_BYTES];
static uint8_t s_trace_scratch[SOS_TRACE_SCRATCH_BYTES];

/* Emit the adapter-filtered done sentinel per PCDN-SOS-04-005 +
 * INV-S-PORT-12. The sentinel is NOT a TraceRecord (no
 * `after_input_idx`, no `tcb`); the host-side adapter filters it before
 * the harness sees it. Hand-rolled bytes so the v1 firmware does not
 * pull a JSON writer into the sentinel-emission path. */
static void emit_done_sentinel(void)
{
    static const char SENTINEL[] = "{\"__sos_done\":true}\n";
    for (size_t i = 0u; SENTINEL[i] != '\0'; ++i) {
        sos_uart_write_byte((uint8_t)SENTINEL[i]);
    }
}

/* Park forever — the adapter sees the sentinel, exits, and the operator
 * power-cycles (or probe-rs resets) the board to begin the next
 * vector. Per SOS-04 §7.2: one vector per boot. */
static void park_forever(void)
{
    for (;;) {
        __asm volatile ("wfi");
    }
}

/* Emit one trace record over USART1. `after_input_idx = -1` is the
 * boot-baseline marker per SOS-00 §3 / §15 Amendment 002; otherwise the
 * zero-based index of the just-consumed event. On overrun the record is
 * truncated to the scratch capacity; the harness sees the truncation as
 * a record-count mismatch. */
static void emit_trace_record(int64_t after_input_idx)
{
    const struct sos_datamodel *dm = sos_kernel_state();
    size_t n = sos_trace_write_record(s_trace_scratch,
                                      sizeof s_trace_scratch,
                                      dm,
                                      after_input_idx);
    if (n > sizeof s_trace_scratch) {
        n = sizeof s_trace_scratch;
    }
    for (size_t i = 0u; i < n; ++i) {
        sos_uart_write_byte(s_trace_scratch[i]);
    }
}

/* ---------------------------------------------------------------------------
 * DWT cycle-count instrumentation (SOS-06-A `MacrostepCycleCount` metric).
 *
 * Per PCDN-SOS-06-003 the canonical macrostep is the chart's
 * `task.yield` round-robin among 8 tasks. The firmware measures cycles
 * around every `sos_dispatch_event` call and accumulates total + count
 * into a pair of static atomics in the static (.bss) page. Bench-side
 * post-mortem reads the addresses via `probe-rs read` and computes mean
 * cycles/macrostep.
 *
 * Counter layout (zero-init by C startup):
 *   sos_macrostep_cycles_lo (u32)  — low 32 bits of accumulated cycles
 *   sos_macrostep_cycles_hi (u32)  — high 32 bits
 *   sos_macrostep_count     (u32)  — number of dispatches measured
 * --------------------------------------------------------------------------- */
volatile uint32_t sos_macrostep_cycles_lo = 0;
volatile uint32_t sos_macrostep_cycles_hi = 0;
volatile uint32_t sos_macrostep_count = 0;

static void sos_dwt_enable(void)
{
    /* DEMCR.TRCENA = 1; DWT_CTRL.CYCCNTENA = 1; DWT_CYCCNT = 0.
     * Addresses per ARMv7-M ARM (SOS-00 §6 distils the relevant subset). */
    *((volatile uint32_t *)0xE000EDFC) |= (1u << 24);
    *((volatile uint32_t *)0xE0001000) |= 1u;
    *((volatile uint32_t *)0xE0001004) = 0u;
}

static inline uint32_t sos_dwt_read_cyccnt(void)
{
    return *((volatile uint32_t *)0xE0001004);
}

static void sos_record_macrostep_cycles(uint32_t delta)
{
    uint32_t old_lo = sos_macrostep_cycles_lo;
    uint32_t new_lo = old_lo + delta;
    if (new_lo < old_lo) {
        sos_macrostep_cycles_hi += 1u;
    }
    sos_macrostep_cycles_lo = new_lo;
    sos_macrostep_count += 1u;
}

int main(void)
{
    /* §6.8 step 1–5: clock tree (PCDN-SOS-04-013), peripheral clock
     * enables, GPIO AF for USART1 TX/RX (PCDN-SOS-04-003), SysTick LOAD,
     * SCB priority grouping = 0 (all-preempt). */
    sos_bsp_init();
    /* DWT cycle counter for the SOS-06-A `MacrostepCycleCount` metric. */
    sos_dwt_enable();

    /* Static pools, idle TCB to READY at prio 0, NVIC priorities per
     * SOS-00 §6.2 (PendSV 0xE0, SysTick 0xC0, *_from_isr 0xA0). The
     * USART1 IRQ priority is programmed here; the NVIC line stays
     * masked until `sos_uart_start_rx_irq()` flips it. */
    sos_kernel_init();

    /* Enable RXNEIE in USART1->CR1 and unmask the USART1 NVIC line.
     * From this point on, RX bytes feed the IRQ-driven ring buffer and
     * `sos_uart_try_read_byte()` is the consumer-side pop. */
    sos_uart_start_rx_irq();

    /* EOQ-005 (2026-05-21, mirrors Rust port main.rs): NOP delay before
     * the first trace emit. The bench adapter shell wrapper does a
     * `probe-rs reset` then spawns the host-driver, which opens the
     * STLINK-V3E VCP a few hundred ms after reset. Without this delay
     * the boot-baseline record's first ~150 bytes are dropped by the
     * USB-CDC stack before the host claims the port. 500 ms is
     * comfortably above the observed adapter-open latency. At 400 MHz
     * CPU, ~10 NOPs per iteration, 50e6 iterations ≈ ~500 ms. */
    for (volatile uint32_t i = 0u; i < 50000000u; ++i) {
        __asm volatile ("nop");
    }

    /* Boot-baseline trace record (§6.2 step 2). The harness compares
     * this record against the simulator's boot baseline before any
     * event is dispatched. */
    emit_trace_record(-1);

    /* Conformance-mode macrostep dispatch loop (§6.2 steps 3–7).
     * Mirrors `sos-m7-rust/src/main.rs` step-for-step. */
    sos_vector_stream_t parser;
    sos_vector_stream_init(&parser);

    size_t  scratch_len     = 0u;
    int64_t after_input_idx = -1;

    for (;;) {
        /* 1. Refill scratch from the RX ring (drain whatever the ISR
         *    has delivered since the last refill). Non-blocking: stops
         *    when the ring is empty or the scratch is full. */
        while (scratch_len < sizeof s_rx_scratch) {
            uint8_t b;
            if (sos_uart_try_read_byte(&b) != 0) {
                break;
            }
            s_rx_scratch[scratch_len] = b;
            scratch_len += 1u;
        }

        if (scratch_len == 0u) {
            __asm volatile ("wfi");
            continue;
        }

        /* 2. Drive the parser. */
        sos_parse_step_t step =
            sos_vector_stream_try_step(&parser, s_rx_scratch, scratch_len);

        switch (step.kind) {
            case SOS_PARSE_STEP_NEED_MORE_INPUT:
                /* Parser consumed nothing actionable; wait for more
                 * bytes. The USART1 IRQ wakes us via wfi. */
                __asm volatile ("wfi");
                break;

            case SOS_PARSE_STEP_VECTOR_HEADER: {
                /* Vector-header check: the firmware's compiled-in
                 * dimensions are frozen at build time. A header that
                 * disagrees would invalidate the trace contract per
                 * INV-S-PORT-9; emit the sentinel and park. */
                if (step.header.max_tasks  != (size_t)SOS_MAX_TASKS
                 || step.header.max_prio   != (size_t)SOS_MAX_PRIO
                 || step.header.max_sems   != (size_t)SOS_MAX_SEMS
                 || step.header.max_queues != (size_t)SOS_MAX_QUEUES
                 || step.header.q_depth    != (size_t)SOS_Q_DEPTH
                 || step.header.tick_hz    != (uint32_t)SOS_TICK_HZ) {
                    emit_done_sentinel();
                    park_forever();
                }
                /* Shift consumed bytes off the front of the scratch. */
                if (step.consumed > 0u && step.consumed <= scratch_len) {
                    if (step.consumed < scratch_len) {
                        memmove(s_rx_scratch,
                                s_rx_scratch + step.consumed,
                                scratch_len - step.consumed);
                    }
                    scratch_len -= step.consumed;
                }
                break;
            }

            case SOS_PARSE_STEP_EVENT: {
                /* Per SOS-00 §7.1 / sim::Simulator::run_vector: inject
                 * `from_tid` into `current` before dispatch when
                 * present; ISR-context events (`sys.tick`,
                 * `*_from_isr`) carry no from_tid and leave `current`
                 * untouched. */
                struct sos_datamodel *dm = sos_kernel_state();
                if (step.event.from_tid_present) {
                    dm->current = step.event.from_tid;
                }
                /* SOS-04 Amendment 007 / silent-continue: a chart-
                 * invariant violation shouldn't be reachable in a
                 * well-formed vector; v1 emits the record anyway so
                 * the harness sees the divergence. */
                {
                    uint32_t cyc_pre = sos_dwt_read_cyccnt();
                    (void)sos_dispatch_event(&step.event);
                    uint32_t cyc_post = sos_dwt_read_cyccnt();
                    sos_record_macrostep_cycles(cyc_post - cyc_pre);
                }
                after_input_idx += 1;

                emit_trace_record(after_input_idx);

                if (step.consumed > 0u && step.consumed <= scratch_len) {
                    if (step.consumed < scratch_len) {
                        memmove(s_rx_scratch,
                                s_rx_scratch + step.consumed,
                                scratch_len - step.consumed);
                    }
                    scratch_len -= step.consumed;
                }
                break;
            }

            case SOS_PARSE_STEP_END_OF_INPUT:
                /* No further input will be consumed; skip the scratch
                 * shift and proceed straight to the sentinel + park. */
                emit_done_sentinel();
                park_forever();
                break;

            case SOS_PARSE_STEP_ERROR:
            default:
                /* Per §6.2 step 4: v1 emits the done sentinel and
                 * halts. The harness sees a truncated trace (records
                 * up to the parse error) and reports a vector failure. */
                emit_done_sentinel();
                park_forever();
                break;
        }
    }
}
