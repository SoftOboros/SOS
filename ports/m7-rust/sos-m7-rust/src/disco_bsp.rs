//! Board-specific bring-up for the STM32H747I-DISCO (CM7 only).
//!
//! Per SOS-04-CONCEPTS.md §6.8 (boot path) and §6.9 (bench substrate).
//! Realises the clock tree ratified by PCDN-SOS-04-013, the GPIO AF
//! routing ratified by PCDN-SOS-04-003, SysTick configuration per
//! SOS-00 §6.6, and the NVIC priority-grouping discipline per
//! SOS-00 §6.2 / §9 INV-S9.
//!
//! Phase 2 implementation: HSE bypass → PLL1 (M=5, N=160, P=2) → 400 MHz
//! CM7 sysclk, GPIOA AF7 for USART1 PA9/PA10, SysTick `LOAD = 399_999`
//! for 1 kHz at 400 MHz, PRIGROUP = 0, PendSV `0xE0`, SysTick `0xC0`.
//! USART1 register configuration (BRR/CR1/CR3) lives in `transport::start()`.

use cortex_m::peripheral::scb::SystemHandler;
use cortex_m::peripheral::syst::SystClkSource;

/// CM7 SYSCLK in Hz after PLL1 lock (PCDN-SOS-04-013).
pub const CM7_SYSCLK_HZ: u32 = 400_000_000;

/// SysTick interrupt rate per SOS-00 §6.6 (1 kHz).
pub const SOS_TICK_HZ: u32 = 1_000;

/// AIRCR vector key per ARMv7-M; write fails silently without it.
const SCB_AIRCR_VECTKEY: u32 = 0x05FA << 16;

/// PendSV NVIC priority per SOS-00 §6.2 / SOS-04 INV-S-PORT-2.
const PENDSV_PRIO: u8 = 0xE0;

/// SysTick NVIC priority per SOS-00 §6.2 / SOS-04 INV-S-PORT-2.
const SYSTICK_PRIO: u8 = 0xC0;

fn park_forever() -> ! {
    loop {
        cortex_m::asm::wfi();
    }
}

/// Bring up the CM7 clock tree, GPIO AF for the trace UART pins, and
/// SysTick. NVIC priority programming happens here per §6.8 step 6
/// even though it logically belongs to the kernel — clock + NVIC + SCB
/// configuration is all one boot phase per SOS-00 §6.2 / §6.8.
///
/// Takes ownership of both peripheral roots (`cortex_m::Peripherals` and
/// `stm32h7::stm32h747cm7::Peripherals`). Subsequent boot stages
/// (`transport::start()`) re-acquire individual peripherals via
/// `Peripherals::steal()` — this is sound because `disco_bsp::init()`
/// is the single peripheral-init choke point and is called exactly once.
pub fn init() {
    let cp = match cortex_m::Peripherals::take() {
        Some(p) => p,
        None => park_forever(),
    };
    let dp = match stm32h7::stm32h747cm7::Peripherals::take() {
        Some(p) => p,
        None => park_forever(),
    };

    init_clocks(&dp);
    init_gpio_usart1_pins(&dp);
    init_systick(cp.SYST);
    init_nvic_priorities(cp.SCB);
}

/// Configure HSE (25 MHz crystal, bypass mode on the disco-analyzer
/// where the crystal is driven by an oscillator output) → PLL1
/// (M=5 → 5 MHz ref, N=160 → 800 MHz VCO, P=2 → 400 MHz CM7, Q=4, R=2)
/// → SYSCLK = PLL1. AHB/APB dividers configured for D1CPRE=/1,
/// D2HPRE=/2 (HCLK = 200 MHz, but D1 domain runs at 400 MHz), APBx=/2.
fn init_clocks(dp: &stm32h7::stm32h747cm7::Peripherals) {
    let rcc = &dp.RCC;

    // 1. Enable HSE bypass + HSE oscillator (25 MHz off-chip).
    rcc.cr.modify(|_, w| w.hsebyp().bypassed().hseon().on());
    while rcc.cr.read().hserdy().bit_is_clear() {}

    // 2. Disable PLL1 before reconfiguring divider ratios.
    rcc.cr.modify(|_, w| w.pll1on().off());
    while rcc.cr.read().pll1rdy().bit_is_set() {}

    // 3. Select HSE as PLL source and set PLL1 M = 5. `pllsrc()` uses
    //    the enum-typed safe writer; `divm1()` is a 6-bit safe field.
    rcc.pllckselr
        .modify(|_, w| w.pllsrc().hse().divm1().bits(5));

    // 4. PLL1 VCO range select. With M=5 and HSE=25 MHz, ref_ck = 5 MHz
    //    which lies in the 4–8 MHz "wide VCO" band; set:
    //      PLL1RGE = Range4 (4–8 MHz reference input range)
    //      PLL1VCOSEL = 0  (wide VCO, 192–836 MHz; our 800 MHz VCO fits)
    //      PLL1FRACEN = 0  (integer mode)
    //      DIVP1EN = 1, DIVQ1EN = 1, DIVR1EN = 1
    rcc.pllcfgr.modify(|_, w| {
        w.pll1vcosel()
            .clear_bit()
            .pll1rge()
            .range4()
            .pll1fracen()
            .clear_bit()
            .divp1en()
            .set_bit()
            .divq1en()
            .set_bit()
            .divr1en()
            .set_bit()
    });

    // 5. PLL1 dividers: N=160 (multiplier - 1 = 159 in the 9-bit
    //    DIVN1 field), P=2 (DIVP1 enum Div2), Q=4 (encoded as 3),
    //    R=2 (encoded as 1). DIVN1 is unsafe-`bits`; DIVP1 has an
    //    enum-typed safe writer; DIVQ1 / DIVR1 are safe `bits`.
    rcc.pll1divr.modify(|_, w| {
        unsafe { w.divn1().bits(159) }
            .divp1()
            .div2()
            .divq1()
            .bits(3)
            .divr1()
            .bits(1)
    });

    // 6. Enable PLL1 and wait for lock.
    rcc.cr.modify(|_, w| w.pll1on().on());
    while rcc.cr.read().pll1rdy().bit_is_clear() {}

    // 7. AHB / APB dividers BEFORE switching SYSCLK to PLL1 so that the
    //    400 MHz clock does not over-drive the peripheral domains.
    //      D1CPRE = /1 (CM7 = 400 MHz)
    //      HPRE   = /2 (HCLK / D2 / D3 = 200 MHz)
    //      D1PPRE = /2 (APB3 = 100 MHz)
    //    The H7's "200 MHz peripheral" tier comes from HPRE-derived
    //    HCLK followed by APBx /1; the spec calls for APBx = 200 MHz
    //    so we keep APBx dividers at /1 (HCLK already = 200 MHz).
    //
    //    Per PCDN-SOS-04-013: "APB1/APB2/APB3/APB4 = /2 (200 MHz)".
    //    The H7 quirk: APB clocks are HCLK / DnPPREx; with HCLK = 200,
    //    DnPPREx = /1 yields 200; DnPPREx = /2 yields 100. The PCDN
    //    text refers to APBx _running at_ 200, which we achieve by
    //    DnPPREx = /1 once HPRE has already halved SYSCLK.
    //
    //    PAC encoding (HPRE_A): Div1 = 0, Div2 = 8.
    //    PAC encoding (D{1..3}PPRE_A): Div1 = 0, Div2 = 4.
    rcc.d1cfgr.modify(|_, w| {
        w.d1cpre()
            .div1() // D1 CPRE = /1 (CM7 = 400 MHz)
            .hpre()
            .div2() // HPRE = /2 (HCLK = 200 MHz)
            .d1ppre()
            .div1() // APB3 = HCLK/1 (= 200 MHz)
    });
    rcc.d2cfgr.modify(|_, w| {
        w.d2ppre1()
            .div1() // APB1 = HCLK/1
            .d2ppre2()
            .div1() // APB2 = HCLK/1
    });
    rcc.d3cfgr.modify(|_, w| {
        w.d3ppre().div1() // APB4 = HCLK/1
    });

    // 8. Switch SYSCLK to PLL1.
    rcc.cfgr.modify(|_, w| w.sw().pll1());
    while !rcc.cfgr.read().sws().is_pll1() {}
}

/// Enable GPIOA + USART1 peripheral clocks, then route PA9/PA10 to
/// AF7 (USART1_TX/RX) per PCDN-SOS-04-003. Push-pull output, no pull,
/// high speed.
fn init_gpio_usart1_pins(dp: &stm32h7::stm32h747cm7::Peripherals) {
    let rcc = &dp.RCC;
    let gpioa = &dp.GPIOA;

    // 1. GPIOA peripheral clock (RCC AHB4ENR bit 0).
    rcc.ahb4enr.modify(|_, w| w.gpioaen().set_bit());
    // Read-back per CM7 quirk to ensure the clock-enable write has
    // propagated before we configure GPIO registers.
    let _ = rcc.ahb4enr.read();

    // 2. USART1 peripheral clock (RCC APB2ENR bit 4).
    rcc.apb2enr.modify(|_, w| w.usart1en().set_bit());
    let _ = rcc.apb2enr.read();

    // 3. PA9 / PA10 → alternate function mode.
    gpioa
        .moder
        .modify(|_, w| w.moder9().alternate().moder10().alternate());

    // 4. Push-pull output (default but explicit), no pull-up/pull-down.
    gpioa
        .otyper
        .modify(|_, w| w.ot9().push_pull().ot10().push_pull());
    gpioa
        .pupdr
        .modify(|_, w| w.pupdr9().floating().pupdr10().floating());

    // 5. High speed (sufficient for 921600 baud).
    gpioa
        .ospeedr
        .modify(|_, w| w.ospeedr9().high_speed().ospeedr10().high_speed());

    // 6. Alternate-function AF7 (USART1) on PA9 and PA10. Both pins
    //    are in the high half-word, so AFRH (afr9 / afr10).
    gpioa.afrh.modify(|_, w| w.afr9().bits(7).afr10().bits(7));
}

/// Configure SysTick per SOS-00 §6.6: clock source = CPU clock,
/// reload = (SystemCoreClock / SOS_TICK_HZ) - 1 → 399_999 at 400 MHz /
/// 1 kHz, current = 0, enable counter and interrupt.
fn init_systick(mut syst: cortex_m::peripheral::SYST) {
    syst.set_clock_source(SystClkSource::Core);
    syst.set_reload(CM7_SYSCLK_HZ / SOS_TICK_HZ - 1);
    syst.clear_current();
    syst.enable_counter();
    syst.enable_interrupt();
}

/// Program PRIGROUP = 0 (all-preempt) per SOS-00 §6.2 / §9 INV-S9, then
/// assign PendSV = 0xE0 and SysTick = 0xC0 per SOS-00 §6.2.
/// `*_from_isr` priorities (0xA0) are programmed when the corresponding
/// IRQ is enabled — at v1, the only kernel-aware IRQ source is USART1,
/// which `transport::start()` programs.
fn init_nvic_priorities(mut scb: cortex_m::peripheral::SCB) {
    // PRIGROUP = 0 (all bits = pre-emption, no sub-priority). The
    // cortex-m 0.7 crate has no dedicated `set_priority_grouping` API,
    // so we write AIRCR directly. The VECTKEY value 0x05FA is the
    // mandatory unlock per ARMv7-M ARM B3.2.6.
    unsafe {
        // AIRCR layout: bits 31:16 must read VECTKEY 0x05FA on write;
        // bits 10:8 are PRIGROUP. Other bits write-zero is the spec's
        // documented benign value at boot.
        let scb_ptr = cortex_m::peripheral::SCB::PTR;
        (*scb_ptr).aircr.write(SCB_AIRCR_VECTKEY); // PRIGROUP = 0
    }

    unsafe {
        scb.set_priority(SystemHandler::PendSV, PENDSV_PRIO);
        scb.set_priority(SystemHandler::SysTick, SYSTICK_PRIO);
    }
}
