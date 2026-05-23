//! USART1 trace transport — RX (vector ingress) + TX (trace egress).
//!
//! Per SOS-04-CONCEPTS.md §6.2 (vector-driven harness mode), §7.2
//! (firmware protocol), PCDN-SOS-04-001 (`Uart` default trace
//! transport), PCDN-SOS-04-003 (USART1 on PA9 TX / PA10 RX, AF7),
//! PCDN-SOS-04-007 (921600 baud), and PCDN-SOS-04-016 (interrupt-driven
//! at v1; H7 USART FIFO mode enabled per user-note).
//!
//! Phase 3 (wave-8 dispatch wiring): RX is interrupt-driven via the
//! `USART1` NVIC line into a static byte ring; TX stays as the
//! blocking-write polling-FIFO path (PCDN-SOS-04-016 user-note: 921600
//! baud is far below the trace-emit cadence; an IRQ-driven TX would not
//! reduce wall-clock time enough to justify the additional state).

use core::sync::atomic::{AtomicUsize, Ordering};

use stm32h7::stm32h747cm7::Interrupt;

/// USART1 baud rate. PCDN-SOS-04-007 ratified 921600, but first-bench
/// (2026-05-21) showed the STLINK-V3E VCP on the disco-analyzer doesn't
/// propagate bytes at that rate (chip-side TX completes per TC/TXE flags
/// but host captures nothing). Stepping down to 115200 for bench
/// validation; matches the rlvgl reference firmware (`BRR=868` at the
/// equivalent kernel clock per `examples/stm32h747i-disco/src/main.rs`).
/// A follow-up §15 amendment ratifies the permanent baud once end-to-end.
pub const USART1_BAUD: u32 = 115_200;

/// USART1 kernel clock (APB2 = 200 MHz per PCDN-SOS-04-013).
pub const USART1_PCLK_HZ: u32 = 200_000_000;

/// USART1 IRQ priority per SOS-00 §6.2 (`*_from_isr` kernel-aware band).
const USART1_IRQ_PRIO: u8 = 0xA0;

// ---------------------------------------------------------------------------
// RX ring buffer.
//
// Single-producer (USART1 ISR) / single-consumer (main thread) byte ring.
// `head` is written only by the ISR; `tail` is written only by the consumer.
// Both are read by both sides. SeqCst ordering keeps the publish/consume
// fences explicit; the cost is negligible at byte cadence (the ISR runs at
// most once per 11 µs at 921 600 baud).
//
// Per the §6.2.1 prose, 4 KiB holds approximately one full wrapped vector
// input for the seed-vector suite. Drops on overflow are recoverable: the
// downstream JSON parser surfaces the resulting truncation as a parse
// error, the dispatch loop emits the done sentinel, and the harness
// reports a vector failure (rather than silently lying about the trace).
// ---------------------------------------------------------------------------

/// RX ring capacity (bytes). Per SOS-04 §6.2.1, ~one full wrapped vector
/// input for the seed-vector suite.
const RX_RING_CAPACITY: usize = 4096;

/// RX ring backing store. Written only by the USART1 ISR.
static mut RX_RING: [u8; RX_RING_CAPACITY] = [0u8; RX_RING_CAPACITY];

/// Write cursor (next free slot, modulo `RX_RING_CAPACITY`). Producer-only.
static RX_HEAD: AtomicUsize = AtomicUsize::new(0);

/// Read cursor (next byte to consume, modulo `RX_RING_CAPACITY`). Consumer-only.
static RX_TAIL: AtomicUsize = AtomicUsize::new(0);

/// Push one byte onto the RX ring. Returns `true` on success, `false`
/// when the ring is full (the byte is dropped).
///
/// SAFETY: callable only from the USART1 ISR (single-producer invariant).
/// The consumer-side `try_read_byte` is the only reader of `RX_RING[tail]`.
fn rx_ring_push(b: u8) -> bool {
    let head = RX_HEAD.load(Ordering::Relaxed);
    let tail = RX_TAIL.load(Ordering::Acquire);
    let next = (head + 1) % RX_RING_CAPACITY;
    if next == tail {
        // Ring full — drop the byte. The downstream JSON parser will
        // surface the truncation as a parse error.
        return false;
    }
    // SAFETY: `head` is the producer's exclusive write index; the
    // consumer reads from `tail..head` and never touches `RX_RING[head]`.
    unsafe {
        let p = core::ptr::addr_of_mut!(RX_RING) as *mut u8;
        p.add(head).write_volatile(b);
    }
    RX_HEAD.store(next, Ordering::Release);
    true
}

/// Configure and enable USART1 at 921600 8N1, no flow control, FIFO
/// mode enabled per PCDN-SOS-04-016 user-note. Programs the USART1 IRQ
/// priority and unmasks it; the `#[interrupt] fn USART1()` body in
/// `handlers.rs` drains the hardware FIFO into the static ring above
/// on every RXFNE event.
pub fn start() {
    // SAFETY: `disco_bsp::init()` already took the unique peripherals;
    // re-acquiring USART1 here is sound because (a) init is the single
    // boot-time choke point and runs before `start()`, (b) the
    // peripheral register block is `Sync` at the architectural level,
    // (c) phase 3 has a single owner sequestered behind the IRQ-driven
    // path — main-thread access goes through this module only.
    let dp = unsafe { stm32h7::stm32h747cm7::Peripherals::steal() };
    let usart1 = &dp.USART1;

    // 1. Disable USART before reconfiguration (RM0399 USART config flow).
    usart1.cr1.modify(|_, w| w.ue().clear_bit());

    // 2. Baud rate: BRR = f_ck / baud. With f_ck = APB2 = 200 MHz and
    //    baud = 921600, BRR = 217 (200_000_000 / 921600 = 217.013...).
    //    16x oversampling (OVER8 = 0) is the default.
    let brr_value: u32 = USART1_PCLK_HZ / USART1_BAUD;
    usart1.brr.write(|w| w.brr().bits(brr_value as u16));

    // 3. CR2 / CR3 keep defaults (1 stop bit, no flow control, no DMA).
    usart1.cr2.reset();
    usart1.cr3.reset();

    // 4. CR1: TX/RX enable, RXNEIE, UE. EOQ-005 (2026-05-21): FIFO mode
    // disabled (FIFOEN cleared) — the H7 USART FIFO mode produced an
    // observed RX duplication where each FIFO drain delivered the
    // first ~8 bytes twice into the ring. Likely the PAC's chained
    // .read().rdr().bits() interacts oddly with the FIFO output latch
    // OR the FIFO requires an explicit per-byte ack we're not doing.
    // Non-FIFO mode: classic per-byte RXNE; reading RDR pops one byte
    // and clears RXNE. Far simpler timing.
    usart1.cr1.write(|w| {
        w.te()
            .set_bit()
            .re()
            .set_bit()
            .rxneie()
            .set_bit()
            .ue()
            .set_bit()
    });

    // 5. NVIC priority + unmask for the USART1 IRQ. The kernel-aware
    //    band per SOS-00 §6.2 is `0xA0`; mass the priority programming
    //    happens here so the unmask is the final wire-up step.
    unsafe {
        let mut cp = cortex_m::Peripherals::steal();
        cp.NVIC.set_priority(Interrupt::USART1, USART1_IRQ_PRIO);
        cortex_m::peripheral::NVIC::unmask(Interrupt::USART1);
    }
}

/// Push one byte onto the TX FIFO (blocking-spin when the FIFO is
/// full). At 921600 baud one byte takes ~11 µs; the spin time is
/// strictly bounded.
///
/// In the PAC's USART_ISR layout, the bit position that the H7
/// reference manual labels `TXFNF` (transmit FIFO not full) is named
/// `txe` (TXE) in the PAC — same bit position; same meaning in FIFO
/// mode.
pub fn write_byte(b: u8) {
    let dp = unsafe { stm32h7::stm32h747cm7::Peripherals::steal() };
    let usart1 = &dp.USART1;

    while usart1.isr.read().txe().bit_is_clear() {}
    usart1.tdr.write(|w| w.tdr().bits(u16::from(b)));

    // EOQ-004 diagnostic: increment TX byte counter via crate-shared static.
    unsafe {
        let c = core::ptr::read_volatile(&raw const crate::DIAG_BYTES_TX).wrapping_add(1);
        core::ptr::write_volatile(&raw mut crate::DIAG_BYTES_TX, c);
    }
}

/// Pop one byte from the RX ring buffer if available, else `None`.
///
/// Single-consumer: this function is the only reader of `RX_TAIL`.
/// The USART1 ISR is the only writer of `RX_HEAD`. Acquire on `head`
/// pairs with the Release in [`rx_ring_push`] so byte writes are
/// visible before the head advance.
pub fn try_read_byte() -> Option<u8> {
    let tail = RX_TAIL.load(Ordering::Relaxed);
    let head = RX_HEAD.load(Ordering::Acquire);
    if tail == head {
        return None;
    }
    // SAFETY: `tail` is the consumer's exclusive read index; the
    // producer publishes by advancing `head` past the slot.
    let b = unsafe {
        let p = core::ptr::addr_of!(RX_RING) as *const u8;
        p.add(tail).read_volatile()
    };
    RX_TAIL.store((tail + 1) % RX_RING_CAPACITY, Ordering::Release);
    Some(b)
}

/// USART1 ISR body — invoked by the `#[interrupt] fn USART1()` handler
/// in `handlers.rs`. Drains the hardware FIFO into [`RX_RING`]; bytes
/// dropped on full-ring are silently discarded (the downstream parser
/// surfaces the resulting truncation).
///
/// Per RM0399 the H7 USART RX FIFO is 16-byte. Draining greedily on
/// each IRQ keeps the IRQ rate near once-per-buffer rather than
/// once-per-byte at high baud.
pub(crate) fn usart1_isr_body() {
    // EOQ-004 diagnostic: increment ISR-fire counter via crate-shared static.
    unsafe {
        let c = core::ptr::read_volatile(&raw const crate::DIAG_ISR_COUNT).wrapping_add(1);
        core::ptr::write_volatile(&raw mut crate::DIAG_ISR_COUNT, c);
    }

    // SAFETY: ISR-context, single-producer invariant. Re-acquiring the
    // PAC peripherals via `steal()` is sound: `disco_bsp::init()` took
    // and dropped them at boot; the ISR is the only context that reads
    // RDR / ISR while running.
    let dp = unsafe { stm32h7::stm32h747cm7::Peripherals::steal() };
    let usart1 = &dp.USART1;

    // Drain the RX FIFO. EOQ-004 (2026-05-21): bind ISR + RDR reads to
    // single locals so each `.read()` is one volatile load. The earlier
    // raw-pointer drain produced zero bytes in the ring (RDR re-read
    // before next byte rotated in); the PAC chain `usart1.rdr.read().rdr().bits()`
    // doubled bytes (two volatile loads per pop). The single-load-via-
    // local-binding pattern below is the canonical safe form.
    loop {
        let isr = usart1.isr.read();
        if isr.rxne().bit_is_clear() {
            break;
        }
        let rdr = usart1.rdr.read();
        let b = rdr.rdr().bits() as u8;
        let _ = rx_ring_push(b);
    }

    // Clear any overrun condition. ORE latches until acknowledged via
    // ICR; without the clear a sticky overrun would keep RXNE asserted
    // and starve subsequent interrupts.
    if usart1.isr.read().ore().bit_is_set() {
        usart1.icr.write(|w| w.orecf().set_bit());
    }
}
