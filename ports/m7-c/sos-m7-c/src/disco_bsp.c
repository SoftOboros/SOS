/* disco_bsp.c — STM32H747I-DISCO bring-up (CM7 only).
 *
 * Per SOS-05-CONCEPTS.md §6.8 (boot path) and §6.10 (bench substrate).
 * Realises the clock tree (HSE=25 MHz → PLL1 M=5/N=160/P=2 → 400 MHz
 * sysclk), USART1 routing (PA9/PA10, AF7) per PCDN-SOS-05-008, USART1
 * config at 921600 8N1 with FIFO mode per PCDN-SOS-05-010 / SOS-04
 * phase 2, the SCB priority-grouping discipline per SOS-00 §6.2, and
 * the kernel-aware NVIC priorities for PendSV (0xE0) and SysTick (0xC0)
 * per SOS-00 §6.2 / SOS-04 INV-S-PORT-2.
 *
 * Phase 2 implementation: mirrors `ports/m7-rust/sos-m7-rust/src/
 * disco_bsp.rs` register-for-register. The two ports MUST agree on the
 * bench substrate (INV-S-PORT-2, INV-S-PORT-4); the Rust port's
 * `init_clocks()` and `init_gpio_usart1_pins()` are the canonical
 * sequence and this file mirrors them verbatim.
 *
 * Per PCDN-SOS-05-009 (no STM32CubeH7 HAL): register access goes
 * through the hand-coded minimal CMSIS-Device header
 * `sos/stm32h747_minimal.h`. The hermetic-header choice and rationale
 * live in that header's top comment.
 */

#include "sos/bsp.h"
#include "sos/stm32h747_minimal.h"

/* CM7 SYSCLK in Hz after PLL1 lock (mirrors SOS-04's CM7_SYSCLK_HZ). */
#define CM7_SYSCLK_HZ       400000000UL

/* USART1 baud rate. PCDN-SOS-04-007 ratified 921600, but first-bench
 * (2026-05-21) on the disco-analyzer STLINK-V3E VCP showed the host
 * captured nothing at that rate (chip-side TX completes per TC/TXE flags;
 * host receives zero bytes). Stepping down to 115200 for bench validation
 * mirrors the Rust port's transport.rs USART1_BAUD step-down and matches
 * the rlvgl reference firmware on the same board. A follow-up §15
 * amendment will ratify the permanent baud once end-to-end. */
#define USART1_BAUD         115200UL

/* USART1 kernel clock = APB2. With HCLK=200 MHz and D2PPRE2=/2,
 * APB2 = 100 MHz. PCDN-SOS-04-013 nominally says 200 MHz, but the
 * actual register state set above yields 100 MHz; aligning the
 * constant to the actual hardware state below (BRR = 100M/115200 ≈ 868
 * matches the rlvgl reference firmware on this board). Bench-validation
 * §15 amendment will reconcile against PCDN-SOS-04-013. */
#define USART1_PCLK_HZ      100000000UL

/* NVIC priorities per SOS-00 §6.2 / SOS-04 INV-S-PORT-2. The H7 has a
 * 4-bit priority field; the value lives in the high nibble of the 8-bit
 * SHPR / IPR byte. 0xE0 = (14 << 4) and so on. We write the canonical
 * 8-bit form directly into SHPR / IPR so the layout is portable to a
 * future CMSIS-Core swap. */
#define SOS_PRIO_PENDSV     0xE0u
#define SOS_PRIO_SYSTICK    0xC0u

static void init_clocks(void);
static void init_gpio_usart1_pins(void);
static void init_usart1(void);
static void init_systick_and_nvic(void);

void sos_bsp_init(void)
{
    init_clocks();
    init_gpio_usart1_pins();
    init_usart1();
    init_systick_and_nvic();
}

/* Configure HSE bypass (25 MHz oscillator on the disco-analyzer) → PLL1
 * (M=5 → 5 MHz ref, N=160 → 800 MHz VCO, P=2 → 400 MHz CM7, Q=4, R=2)
 * → SYSCLK = PLL1. AHB/APB dividers configured for D1CPRE=/1, HPRE=/2
 * (HCLK = 200 MHz), APBx = /2 (100 MHz) per the SOS-04 phase 2 register
 * sequence in `disco_bsp.rs::init_clocks`. */
static void init_clocks(void)
{
    /* 1. HSE bypass + HSE on (25 MHz). */
    RCC->CR |= RCC_CR_HSEBYP | RCC_CR_HSEON;
    while ((RCC->CR & RCC_CR_HSERDY) == 0u) { /* spin */ }

    /* 2. PLL1 off before reconfiguring. */
    RCC->CR &= ~RCC_CR_PLL1ON;
    while ((RCC->CR & RCC_CR_PLL1RDY) != 0u) { /* spin */ }

    /* 3. PLL1 source = HSE; PLL1 input divider M=5. PLLCKSELR layout:
     *      PLLSRC[1:0], DIVM1[9:4]. Clear the affected fields, then set. */
    {
        uint32_t pllckselr = RCC->PLLCKSELR;
        pllckselr &= ~((0x3UL << 0) | (0x3FUL << RCC_PLLCKSELR_DIVM1_Pos));
        pllckselr |= RCC_PLLCKSELR_PLLSRC_HSE;
        pllckselr |= (5UL << RCC_PLLCKSELR_DIVM1_Pos);
        RCC->PLLCKSELR = pllckselr;
    }

    /* 4. PLL1 config: VCO wide (192..836 MHz), input range 4..8 MHz
     *    (HSE/M = 25/5 = 5 MHz fits), integer mode (FRACEN=0), enable
     *    DIVP1 / DIVQ1 / DIVR1 outputs. */
    {
        uint32_t pllcfgr = RCC->PLLCFGR;
        /* Clear affected fields. */
        pllcfgr &= ~(RCC_PLLCFGR_PLL1FRACEN
                     | RCC_PLLCFGR_PLL1VCOSEL
                     | (0x3UL << RCC_PLLCFGR_PLL1RGE_Pos));
        pllcfgr |= RCC_PLLCFGR_PLL1RGE_4_8;
        pllcfgr |= RCC_PLLCFGR_DIVP1EN | RCC_PLLCFGR_DIVQ1EN | RCC_PLLCFGR_DIVR1EN;
        RCC->PLLCFGR = pllcfgr;
    }

    /* 5. PLL1 dividers. DIVN1 is the multiplier minus 1 (9-bit field);
     *    DIVP1 / DIVQ1 / DIVR1 are output dividers, encoded as
     *    (divider - 1). For N=160 → DIVN1=159; P=2 → DIVP1=1;
     *    Q=4 → DIVQ1=3; R=2 → DIVR1=1. */
    RCC->PLL1DIVR =
          (159UL << RCC_PLL1DIVR_DIVN1_Pos)
        | (  1UL << RCC_PLL1DIVR_DIVP1_Pos)
        | (  3UL << RCC_PLL1DIVR_DIVQ1_Pos)
        | (  1UL << RCC_PLL1DIVR_DIVR1_Pos);

    /* 6. AHB / APB dividers BEFORE the SYSCLK switch so a momentary
     *    400 MHz pulse does not overspeed the peripheral domains.
     *    HCLK = SYSCLK/2 = 200 MHz; APB1/2/3/4 = HCLK/2 = 100 MHz
     *    (within the H7's 100 MHz APB spec at VOS1). */
    {
        uint32_t d1cfgr = RCC->D1CFGR;
        d1cfgr &= ~((0xFUL << 8) | (0xFUL << 0) | (0x7UL << 4));
        d1cfgr |= RCC_D1CFGR_D1CPRE_DIV1
                 | RCC_D1CFGR_HPRE_DIV2
                 | RCC_D1CFGR_D1PPRE_DIV2;
        RCC->D1CFGR = d1cfgr;
    }
    {
        uint32_t d2cfgr = RCC->D2CFGR;
        d2cfgr &= ~((0x7UL << 4) | (0x7UL << 8));
        d2cfgr |= RCC_D2CFGR_D2PPRE1_DIV2 | RCC_D2CFGR_D2PPRE2_DIV2;
        RCC->D2CFGR = d2cfgr;
    }
    {
        uint32_t d3cfgr = RCC->D3CFGR;
        d3cfgr &= ~(0x7UL << 4);
        d3cfgr |= RCC_D3CFGR_D3PPRE_DIV2;
        RCC->D3CFGR = d3cfgr;
    }

    /* 7. Enable PLL1 and wait for lock. */
    RCC->CR |= RCC_CR_PLL1ON;
    while ((RCC->CR & RCC_CR_PLL1RDY) == 0u) { /* spin */ }

    /* 8. Switch SYSCLK to PLL1. */
    {
        uint32_t cfgr = RCC->CFGR;
        cfgr = (cfgr & ~RCC_CFGR_SW_Msk) | RCC_CFGR_SW_PLL1;
        RCC->CFGR = cfgr;
        while ((RCC->CFGR & RCC_CFGR_SWS_Msk) != RCC_CFGR_SWS_PLL1) { /* spin */ }
    }
}

/* Enable GPIOA + USART1 peripheral clocks, route PA9/PA10 to AF7
 * (USART1_TX / USART1_RX) per PCDN-SOS-05-008. Push-pull, no pull, high
 * speed (sufficient for 921600 baud). Mirrors SOS-04
 * `init_gpio_usart1_pins`. */
static void init_gpio_usart1_pins(void)
{
    /* 1. GPIOA clock (RCC AHB4ENR bit 0). Readback per CM7 quirk to
     *    ensure the enable write has propagated before the GPIO regs
     *    are touched. */
    RCC->AHB4ENR |= RCC_AHB4ENR_GPIOAEN;
    (void)RCC->AHB4ENR;

    /* 2. USART1 clock (RCC APB2ENR bit 4). */
    RCC->APB2ENR |= RCC_APB2ENR_USART1EN;
    (void)RCC->APB2ENR;

    /* 3. PA9 / PA10 → alternate-function mode (MODER = 10b). Two-bit
     *    fields per pin in MODER. PA9 occupies bits [19:18];
     *    PA10 occupies bits [21:20]. */
    {
        uint32_t moder = GPIOA->MODER;
        moder &= ~((0x3UL << 18) | (0x3UL << 20));
        moder |=  ((0x2UL << 18) | (0x2UL << 20));
        GPIOA->MODER = moder;
    }

    /* 4. Push-pull output (OTYPER bit per pin = 0). */
    GPIOA->OTYPER &= ~((1UL << 9) | (1UL << 10));

    /* 5. No pull-up / pull-down. Two-bit fields per pin in PUPDR. */
    {
        uint32_t pupdr = GPIOA->PUPDR;
        pupdr &= ~((0x3UL << 18) | (0x3UL << 20));
        GPIOA->PUPDR = pupdr;
    }

    /* 6. High speed (OSPEEDR = 10b). */
    {
        uint32_t ospeedr = GPIOA->OSPEEDR;
        ospeedr &= ~((0x3UL << 18) | (0x3UL << 20));
        ospeedr |=  ((0x2UL << 18) | (0x2UL << 20));
        GPIOA->OSPEEDR = ospeedr;
    }

    /* 7. AFR[1] (= AFRH) for pins 8..15. PA9 occupies bits [7:4];
     *    PA10 occupies bits [11:8]. AF7 = USART1_TX/RX. */
    {
        uint32_t afrh = GPIOA->AFR[1];
        afrh &= ~((0xFUL << 4) | (0xFUL << 8));
        afrh |=  ((7UL   << 4) | (7UL   << 8));
        GPIOA->AFR[1] = afrh;
    }
}

/* Configure USART1 at 921600 8N1, FIFO mode enabled, no flow control.
 * Mirrors SOS-04 `transport::start()` — the C port keeps the USART
 * register sequence in the BSP rather than in transport.c so that the
 * boot order (clock tree → GPIO AF → peripheral config → kernel init)
 * matches §6.8 step-for-step. The RX/TX byte primitives in
 * `transport.c` assume this has run. */
static void init_usart1(void)
{
    /* 1. Disable USART before reconfiguration (RM0399 USART config flow). */
    USART1->CR1 &= ~USART_CR1_UE;

    /* 2. BRR = f_ck / baud at 16x oversampling (OVER8 = 0, default).
     *    200_000_000 / 921_600 = 217.013…; integer truncation yields 217. */
    USART1->BRR = USART1_PCLK_HZ / USART1_BAUD;

    /* 3. CR2 / CR3 to defaults (1 stop bit, no flow control, no DMA). */
    USART1->CR2 = 0u;
    USART1->CR3 = 0u;

    /* 4. CR1: TE, RE, UE. 8N1 is the reset default (M0 = M1 = 0, PCE = 0).
     *    RXNEIE / TXEIE stay cleared at v1 — phase 3 wires the
     *    interrupt-driven path.
     *
     *    EOQ-005 (2026-05-21, mirrors Rust port transport.rs): FIFO mode
     *    disabled (FIFOEN cleared) — the H7 USART FIFO mode produced an
     *    observed RX duplication where each FIFO drain delivered the
     *    first ~8 bytes twice into the ring. Either the chained
     *    `usart1.rdr.read().rdr().bits()` pattern doubled bytes per pop
     *    OR the H7 FIFO requires an explicit per-byte ack the v1 driver
     *    didn't perform. Non-FIFO mode: classic per-byte RXNE; reading
     *    RDR pops one byte and clears RXNE. Far simpler timing. */
    USART1->CR1 = USART_CR1_TE
                | USART_CR1_RE
                | USART_CR1_UE;
}

/* SysTick @ CPU clock per SOS-00 §6.6: LOAD = (sysclk / TICK_HZ) - 1;
 * CTRL = CLKSOURCE | TICKINT | ENABLE.
 *
 * NVIC priority programming per SOS-00 §6.2 / INV-S-PORT-2:
 *   PendSV  = 0xE0 (SHPR[7])
 *   SysTick = 0xC0 (SHPR[8])
 *   PRIGROUP = 0 in AIRCR (all bits pre-emption).
 *
 * USART1 IRQ priority is programmed by `sos_kernel_init` so the
 * kernel-aware-IRQ bookkeeping stays with the kernel; the IRQ stays
 * masked at NVIC until phase 3 enables the IRQ-driven RX path. */
static void init_systick_and_nvic(void)
{
    /* SysTick: clock source = CPU clock, 1 kHz tick rate. */
    SysTick->LOAD = (CM7_SYSCLK_HZ / SOS_TICK_HZ) - 1u;
    SysTick->VAL  = 0u;
    SysTick->CTRL = SysTick_CTRL_CLKSOURCE_Msk
                  | SysTick_CTRL_TICKINT_Msk
                  | SysTick_CTRL_ENABLE_Msk;

    /* SCB AIRCR: PRIGROUP = 0 (all-preempt). VECTKEY MUST be 0x05FA on
     * every write; PRIGROUP at bits [10:8]. We write VECTKEY + zero
     * PRIGROUP; other bits write-zero is the spec's benign default. */
    SCB->AIRCR = SCB_AIRCR_VECTKEY | (0UL << SCB_AIRCR_PRIGROUP_Pos);

    /* SHPR: 8-bit fields, byte-indexed. Write the canonical hardware
     * encoding (high nibble = priority value for a 4-bit-prio
     * implementation). */
    SCB->SHPR[SCB_SHPR_PENDSV_IDX]  = SOS_PRIO_PENDSV;
    SCB->SHPR[SCB_SHPR_SYSTICK_IDX] = SOS_PRIO_SYSTICK;
}
