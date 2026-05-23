/* startup.S — minimal ARMv7-M startup assembly for SOS-05.
 *
 * Per SOS-05-CONCEPTS.md §6.8 (boot path). Provides:
 *   - the ARMv7-M vector table in .isr_vector
 *   - Reset_Handler: BSS zero + .data copy + branch to main
 *   - default weak IRQ stubs (overridden by handlers.c for PendSV /
 *     SVC / SysTick / USART1; rest stay at the default infinite loop)
 *
 * Skeleton commit: vector table contains only the named CM7 exception
 * slots + USART1 (the only IRQ SOS-05 uses at v1; INV-S-PORT-4). The
 * full interrupt-line table can land in a phase-2 amendment if other
 * IRQs become relevant.
 */

    .syntax unified
    .cpu cortex-m7
    .fpu fpv5-d16
    .thumb

/* ---- Linker-script-provided symbols ---- */
    .extern _stack_start
    .extern _sdata, _edata, _sidata, _sbss, _ebss
    .extern main

/* ---- Vector table ---- */
    .section .isr_vector, "a", %progbits
    .type    g_pfnVectors, %object
    .globl   g_pfnVectors
g_pfnVectors:
    .word   _stack_start                /* initial MSP */
    .word   Reset_Handler               /* reset */
    .word   NMI_Handler                 /* NMI */
    .word   HardFault_Handler           /* HardFault */
    .word   MemManage_Handler           /* MemManage */
    .word   BusFault_Handler            /* BusFault */
    .word   UsageFault_Handler          /* UsageFault */
    .word   0                           /* reserved */
    .word   0                           /* reserved */
    .word   0                           /* reserved */
    .word   0                           /* reserved */
    .word   SVC_Handler                 /* SVCall */
    .word   DebugMon_Handler            /* DebugMon */
    .word   0                           /* reserved */
    .word   PendSV_Handler              /* PendSV */
    .word   SysTick_Handler             /* SysTick */

    /* External IRQs — STM32H747xx external interrupt 0..(N-1).
     * SOS-05 v1 only wires USART1 (IRQ #37). Pad-to-37 with the
     * Default_Handler weak symbol so unintended IRQs trap. */
    .rept 37
    .word   Default_Handler
    .endr
    .word   USART1_IRQHandler           /* IRQ 37 — USART1 */

    .size g_pfnVectors, . - g_pfnVectors

/* ---- Reset_Handler ---- */
    .section .text.Reset_Handler, "ax", %progbits
    .type    Reset_Handler, %function
    .globl   Reset_Handler
    .thumb_func
Reset_Handler:
    /* MSP already set by hardware from vector[0]; refresh to be safe. */
    ldr     r0, =_stack_start
    msr     msp, r0

    /* Copy .data from LOAD (FLASH) to RUN (DTCM). */
    ldr     r0, =_sdata
    ldr     r1, =_edata
    ldr     r2, =_sidata
1:
    cmp     r0, r1
    bcs     2f
    ldr     r3, [r2], #4
    str     r3, [r0], #4
    b       1b
2:

    /* Zero .bss. */
    ldr     r0, =_sbss
    ldr     r1, =_ebss
    movs    r2, #0
3:
    cmp     r0, r1
    bcs     4f
    str     r2, [r0], #4
    b       3b
4:

    /* Enable FPU (CP10/CP11 full access) before main(). */
    ldr     r0, =0xE000ED88   /* SCB->CPACR */
    ldr     r1, [r0]
    orr     r1, r1, #(0xF << 20)
    str     r1, [r0]
    dsb
    isb

    bl      main

    /* main() should never return. Trap if it does. */
5:
    b       5b
    .size Reset_Handler, . - Reset_Handler

/* ---- Default_Handler ---- */
    .section .text.Default_Handler, "ax", %progbits
    .type    Default_Handler, %function
    .weak    Default_Handler
    .thumb_func
Default_Handler:
    b       .
    .size Default_Handler, . - Default_Handler
