/* transport.c — USART1 trace transport.
 *
 * Per SOS-05-CONCEPTS.md §6.2 (vector-driven harness mode) and §7
 * (conformance-mode protocol). PCDN-SOS-05-008 → USART1;
 * PCDN-SOS-05-010 → JSONL-bidirectional framing inherited from SOS-04
 * §6.2.
 *
 * Phase 2 implementation: the byte-level RX / TX primitives against
 * the USART1 FIFO. USART1 itself is configured (baud, FIFOEN, TE/RE/UE)
 * by `disco_bsp.c::sos_bsp_init` per §6.8 step ordering — the BSP owns
 * the whole peripheral-init phase so the boot sequence reads as
 * (clocks → GPIO → peripherals → kernel).
 *
 * Wave-10 (this commit): adds the single-producer / single-consumer
 * RX ring buffer, the USART1 ISR drain routine, and the NVIC-unmask
 * helper. Mirrors the structure in
 * `ports/m7-rust/sos-m7-rust/src/transport.rs`:
 *   - 4 KiB byte ring; producer = USART1 IRQ, consumer = main loop.
 *   - `sos_uart_isr_drain` greedily drains the RX FIFO and pushes into
 *     the ring; bytes dropped on full-ring are silently discarded (the
 *     downstream JSON parser surfaces the resulting truncation).
 *   - `sos_uart_try_read_byte` is the task-mode pop; non-blocking.
 *   - `sos_uart_start_rx_irq` sets the USART1 IRQ priority (0xA0 per
 *     SOS-00 §6.2), enables RXNEIE, and unmasks the NVIC line. The
 *     priority is also written by `sos_kernel_init` per wave-7; the
 *     write here is idempotent and keeps the wire-up sequence local
 *     to the transport module that owns the IRQ semantics.
 *
 * The TX path stays polling-FIFO (blocking spin while TXFNF=0). At
 * 921 600 baud the per-byte wait is ~11 µs; the trace cadence is far
 * lower than that, so an IRQ-driven TX would not reduce wall-clock
 * time enough to justify the additional state.
 */

#include "sos/bsp.h"
#include "sos/stm32h747_minimal.h"

/* ---------------------------------------------------------------------------
 * RX ring buffer.
 *
 * Single-producer (USART1 IRQ) / single-consumer (main thread) byte ring.
 * `rx_head` is written only by the ISR; `rx_tail` is written only by the
 * consumer. Both are `volatile` so the compiler does not hoist or coalesce
 * loads across the producer/consumer boundary; the ARMv7-M atomic-word
 * memory model guarantees the single-word loads/stores below are atomic
 * with respect to each side.
 *
 * The ring capacity is 4 KiB — per SOS-04 §6.2.1 prose, approximately one
 * full wrapped vector input for the seed-vector suite. Drops on overflow
 * are recoverable: the downstream JSON parser surfaces the resulting
 * truncation as a parse error, the dispatch loop emits the done sentinel,
 * and the harness reports a vector failure (rather than silently lying
 * about the trace).
 * ---------------------------------------------------------------------------
 */

#define SOS_RX_RING_CAPACITY  4096u

static uint8_t           rx_ring[SOS_RX_RING_CAPACITY];
static volatile uint16_t rx_head; /* producer write index (mod capacity) */
static volatile uint16_t rx_tail; /* consumer read  index (mod capacity) */

/* USART1 IRQ priority per SOS-00 §6.2 (`*_from_isr` kernel-aware band). */
#define SOS_PRIO_USART1   0xA0u

/* Push one byte onto the RX ring. Returns true on success, false when
 * the ring is full (the byte is dropped). Callable only from the
 * USART1 ISR (single-producer invariant). */
static bool sos_uart_rx_ring_push(uint8_t b)
{
    uint16_t head = rx_head;
    uint16_t tail = rx_tail;
    uint16_t next = (uint16_t)((head + 1u) % SOS_RX_RING_CAPACITY);
    if (next == tail) {
        /* Ring full — drop the byte. Downstream JSON parser surfaces
         * the resulting truncation as a parse error. */
        return false;
    }
    rx_ring[head] = b;
    rx_head = next;
    return true;
}

/* Push one byte onto the TX FIFO. Blocking spin while the FIFO is
 * full; at 921600 baud one byte takes ~11 µs so the bounded wait is
 * acceptable at v1. */
void sos_uart_write_byte(uint8_t b)
{
    while ((USART1->ISR & USART_ISR_TXE) == 0u) { /* spin */ }
    USART1->TDR = (uint32_t)b;
}

/* Pop one byte from the RX FIFO if available (polled). Returns 0 with
 * the byte stored in *out, or -1 if no byte is pending. This is the
 * pre-IRQ polling path; production wave-10 firmware uses
 * `sos_uart_try_read_byte` against the IRQ-fed ring. Retained as the
 * non-IRQ smoke-test path. */
int sos_uart_read_byte(uint8_t *out)
{
    if ((USART1->ISR & USART_ISR_RXNE) == 0u) {
        return -1;
    }
    *out = (uint8_t)(USART1->RDR & 0xFFu);
    return 0;
}

/* Pop one byte from the IRQ-fed RX ring. Returns 0 on success
 * (byte stored in *out), -1 if the ring is empty. Single-consumer:
 * this function is the only reader of `rx_tail`. The USART1 ISR is the
 * only writer of `rx_head`. */
int sos_uart_try_read_byte(uint8_t *out)
{
    uint16_t tail = rx_tail;
    uint16_t head = rx_head;
    if (tail == head) {
        return -1;
    }
    *out = rx_ring[tail];
    rx_tail = (uint16_t)((tail + 1u) % SOS_RX_RING_CAPACITY);
    return 0;
}

/* USART1 ISR body — drains the hardware FIFO into the static RX ring;
 * bytes dropped on full-ring are silently discarded (the downstream
 * parser surfaces the resulting truncation).
 *
 * Per RM0399 the H7 USART RX FIFO is 16-byte. Draining greedily on
 * each IRQ keeps the IRQ rate near once-per-buffer rather than
 * once-per-byte at high baud. */
void sos_uart_isr_drain(void)
{
    /* Drain the RX FIFO until empty. In FIFO mode RXNE tracks
     * RX-FIFO-not-empty per RM0399 §54.8.10. */
    while ((USART1->ISR & USART_ISR_RXNE) != 0u) {
        uint8_t b = (uint8_t)(USART1->RDR & 0xFFu);
        (void)sos_uart_rx_ring_push(b);
    }

    /* Clear any overrun condition. ORE latches until acknowledged via
     * ICR; without the clear a sticky overrun would keep RXNE asserted
     * and starve subsequent interrupts. */
    if ((USART1->ISR & USART_ISR_ORE) != 0u) {
        USART1->ICR = USART_ICR_ORECF;
    }
}

/* Program the USART1 NVIC priority (0xA0 per SOS-00 §6.2), enable
 * RXNEIE in USART1->CR1, and unmask the USART1 NVIC line. Idempotent
 * with the priority write performed in `sos_kernel_init`; this entry
 * point exists so the IRQ wire-up step is local to the transport
 * module that owns the IRQ semantics. */
void sos_uart_start_rx_irq(void)
{
    /* 1. Belt-and-suspenders: re-write the USART1 IRQ priority. The
     *    kernel boot path also writes 0xA0 here but keeping the write
     *    co-located with the unmask makes the wire-up order self-
     *    describing. */
    NVIC->IPR[USART1_IRQn] = SOS_PRIO_USART1;

    /* 2. Enable RXNEIE — the RX-FIFO-not-empty interrupt source.
     *    The other CR1 bits (FIFOEN, TE, RE, UE) were programmed by
     *    `init_usart1()` in disco_bsp.c. */
    USART1->CR1 |= USART_CR1_RXNEIE;

    /* 3. Unmask the USART1 NVIC line. ISER is the set-enable register;
     *    writing 1 to bit (IRQn % 32) of ISER[IRQn / 32] enables it.
     *    USART1_IRQn = 37 → ISER[1] bit 5. */
    NVIC->ISER[USART1_IRQn / 32] = (1UL << (USART1_IRQn % 32));
}

/* `sos_trace_write_record` body now lives in src/trace.c per SOS-05 §6.1
 * project layout (wave-9 implementation). The transport-side stub that
 * previously sat here would multiply-define the symbol at link time. */
