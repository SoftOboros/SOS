/* handlers.c — NVIC exception handler stubs.
 *
 * Per SOS-05-CONCEPTS.md §6.4 (PendSV naked body), §6.5 (vestigial SVC),
 * §6.6 (SysTick body). Skeleton commit: each handler is a tight infinite
 * loop so the vector-table slots link and a stray exception traps in a
 * known spot. Real bodies land in phase 2 / phase 3.
 */

#include "sos/bsp.h"
#include "sos/kernel.h"
#include "sos/types.h"

/* Forward declarations — the ARMv7-M vector table (in startup.S) takes the
 * addresses of these handlers, so they need external linkage; under
 * -Wmissing-prototypes (enabled by toolchain-arm-none-eabi.cmake's
 * -Wall -Wextra -Wpedantic) every external function needs a prototype
 * visible at its definition. Per CMSIS-Core convention each handler's
 * name is `<vector_name>_Handler`. */
void PendSV_Handler(void);
void SVC_Handler(void);
void SysTick_Handler(void);
void USART1_IRQHandler(void);
void NMI_Handler(void);
void HardFault_Handler(void);
void MemManage_Handler(void);
void BusFault_Handler(void);
void UsageFault_Handler(void);
void DebugMon_Handler(void);

/* PendSV — context-switch primitive. NVIC priority 0xE0 per SOS-00 §6.2.
 *
 * TODO(SOS-05 phase 3): naked-function inline-asm body per SOS-05 §6.4.
 * Save R4–R11 + LR; conditionally save S16–S31 when EXC_RETURN[4] == 0;
 * swap PSP between outgoing/incoming TCBs; bx lr to return from
 * exception via the hardware-unstacked frame. */
__attribute__((naked)) void PendSV_Handler(void)
{
    __asm volatile ("b . \n");
}

/* SVC — reserved under DirectCallBasepri (PCDN-SOS-00-002). Unexpected
 * SVC is a port bug; trap to a tight loop. */
__attribute__((naked)) void SVC_Handler(void)
{
    __asm volatile ("b . \n");
}

/* SysTick — tick service. NVIC priority 0xC0 per SOS-00 §6.2 / §6.6.
 *
 * TODO(SOS-05 phase 2): issue SOS_EVT_SYS_TICK to the dispatcher; if
 * the macrostep changed `current`, pend PendSV via SCB->ICSR.
 *
 * EOQ-005 (2026-05-21, mirrors Rust port handlers.rs): the hardware
 * SysTick body is wrapped in `if (0)` for v1 Conformance mode. Reason:
 * PCDN-SOS-04-004's Conformance vs Standalone mode design routes time
 * via explicit `sys.tick` UART events; the simulator's tick_count
 * advances only on those events. With hardware SysTick firing at
 * 1 kHz, the firmware's `dm->tick_count` advances continuously during
 * the boot delay + per-vector pause, which diverges the trace
 * baseline (sim expects 0, firmware reads 76, 153, 229, ...). Future
 * `standalone-smoke` feature gate will re-enable this body for the
 * Standalone-mode demo. */
void SysTick_Handler(void)
{
    if (0) {
        /* Wave-10 dispatcher (kernel.c::sos_dispatch_event) reads
         * ev->name + ev->data exclusively. */
        sos_event_t ev = {
            .name             = SOS_EVN_SYS_TICK,
            .data             = { .tag = SOS_EVD_NONE },
            .from_tid_present = false,
            .from_tid         = 0,
            .kind             = SOS_EVT_SYS_TICK,
            .task_id          = -1,
            .arg_i32_0        = 0,
            .arg_i32_1        = 0,
            .arg_i64          = 0,
            .msg              = { .tag = SOS_MSG_NULL, .u = { .i = 0 } },
        };
        (void)sos_dispatch_event(&ev);
    }
}

/* USART1 RX IRQ — *_from_isr band at 0xA0. Drains the hardware FIFO
 * into the static RX ring via transport.c::sos_uart_isr_drain so the
 * macrostep loop in main.c can consume bytes from the ring via
 * sos_uart_try_read_byte. Mirrors the Rust port's
 * `#[interrupt] fn USART1()` → `transport::usart1_isr_body()`. */
void USART1_IRQHandler(void)
{
    sos_uart_isr_drain();
}

/* Generic fault traps. v1 hardening: tight loops with predictable PC
 * for post-mortem inspection. Full diagnosis is a §15 amendment. */
__attribute__((naked)) void NMI_Handler(void)         { __asm volatile ("b . \n"); }
__attribute__((naked)) void HardFault_Handler(void)   { __asm volatile ("b . \n"); }
__attribute__((naked)) void MemManage_Handler(void)   { __asm volatile ("b . \n"); }
__attribute__((naked)) void BusFault_Handler(void)    { __asm volatile ("b . \n"); }
__attribute__((naked)) void UsageFault_Handler(void)  { __asm volatile ("b . \n"); }
__attribute__((naked)) void DebugMon_Handler(void)    { __asm volatile ("b . \n"); }
