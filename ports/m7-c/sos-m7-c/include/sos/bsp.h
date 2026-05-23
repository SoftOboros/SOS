/* sos/bsp.h — board-support API (SOS-05 §6.8 / §6.10).
 *
 * Provides the small surface the kernel + transport need to talk to the
 * STM32H747I-DISCO bench substrate. Skeleton commit: prototypes only;
 * bodies land in src/disco_bsp.c at phase 2.
 */

#ifndef SOS_BSP_H
#define SOS_BSP_H

#include "sos/types.h"

#ifdef __cplusplus
extern "C" {
#endif

/* HSE=25 MHz → PLL1 (M=5, N=160, P=2) → 400 MHz CM7 sysclk;
 * RCC enables for GPIOA + USART1; GPIOA PA9/PA10 AF7;
 * SCB priority-grouping = 0 (all-preempt) per SOS-00 §6.2.
 * Does NOT enable SysTick — that's `sos_kernel_init` per §6.8 step 6. */
void sos_bsp_init(void);

/* Write one byte to the conformance UART (USART1, PCDN-SOS-05-008).
 * Blocks while TXFNF=0. */
void sos_uart_write_byte(uint8_t b);

/* Read one byte from the conformance UART if available. Returns 0 on
 * success (byte stored in *out), -1 if no byte is pending. Polls the
 * RXNE bit directly — pre-wave-10 path retained for non-IRQ smoke
 * scenarios. */
int sos_uart_read_byte(uint8_t *out);

/* Pop one byte from the IRQ-driven RX ring buffer if available.
 * Returns 0 on success (byte stored in *out), -1 if the ring is
 * empty. Mirrors `transport::try_read_byte()` in the Rust port. The
 * ring is fed by the USART1 IRQ; the main loop drains it at macrostep
 * boundaries. */
int sos_uart_try_read_byte(uint8_t *out);

/* Drain the USART1 RX FIFO into the IRQ-fed ring buffer. Callable only
 * from the USART1 ISR (single-producer invariant); declared in the
 * public header so `USART1_IRQHandler` in handlers.c can call across
 * TUs. Mirrors `transport::usart1_isr_body()` in the Rust port. */
void sos_uart_isr_drain(void);

/* Program the USART1 NVIC priority + RXNEIE in CR1 + unmask the NVIC
 * line so subsequent RX bytes drive the IRQ-driven RX path. Called once
 * from main() after `sos_kernel_init()`; mirrors `transport::start()`
 * in the Rust port's NVIC-unmask half. */
void sos_uart_start_rx_irq(void);

#ifdef __cplusplus
}
#endif

#endif /* SOS_BSP_H */
