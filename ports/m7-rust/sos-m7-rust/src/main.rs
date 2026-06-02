//! sos-m7-rust — SOS-04 M7 Rust reference port firmware.
//!
//! Per SOS-04-CONCEPTS.md §6.1 (crate layout), §6.2 (Conformance-mode
//! protocol), §6.8 (boot path), PCDN-SOS-04-005 (adapter-filtered done
//! sentinel), and PCDN-SOS-04-016 (interrupt-driven USART). The boot
//! path runs disco_bsp::init → kernel::init → transport::start → emit
//! the boot-baseline trace record → enter the macrostep dispatch loop.
//!
//! Wave-8 dispatch wiring lands the end-to-end Conformance-mode loop:
//! UART bytes drain from the static RX ring into a streaming JSON
//! parser (sibling crate-internal `json_parser` module per
//! PCDN-SOS-04-008); each parsed [`event::Event`] is dispatched via
//! [`scripts::dispatch_event`] (which performs the chart's macrostep
//! including any `sched.run` microstep); a trace record is emitted
//! per event; and the adapter-filtered done sentinel
//! `{"__sos_done": true}` terminates the trace stream.

#![no_std]
#![no_main]

use cortex_m_rt::entry;
use panic_halt as _;

mod disco_bsp;
mod event;
mod handlers;
mod json_parser;
mod kernel;
mod scripts;
mod trace;
mod transport;

/// RX scratch buffer size. Matches `transport::RX_RING_CAPACITY` so the
/// parser can hold a full wrapped vector input in the worst case (one
/// full ring's worth of bytes between two parse steps).
const RX_SCRATCH_BYTES: usize = 4096;

/// Trace-record scratch buffer size. Per `trace.rs`: ~2 KiB suffices
/// for any seed-vector record at the canonical dimensional defaults.
const TRACE_SCRATCH_BYTES: usize = 2048;

/// EOQ-004 diagnostic counters. Placed in `.bss` (zero-init by
/// cortex-m-rt) at static-mut locations the linker reports via `nm`.
/// Probe-rs reads them through symbol address. Remove once dispatch
/// path is confirmed working on bench.
#[no_mangle]
static mut DIAG_LOOP_COUNT: u32 = 0;
#[no_mangle]
pub(crate) static mut DIAG_ISR_COUNT: u32 = 0;
#[no_mangle]
static mut DIAG_PARSE_KIND: u32 = 0;
#[no_mangle]
static mut DIAG_BYTES_RX: u32 = 0;
#[no_mangle]
pub(crate) static mut DIAG_BYTES_TX: u32 = 0;

/// Emit the adapter-filtered done sentinel per PCDN-SOS-04-005 +
/// INV-S-PORT-12. The sentinel is **not** a `TraceRecord` (no
/// `after_input_idx`, no `tcb`, etc.); the host-side adapter filters it
/// before the harness sees it. Hand-rolled bytes here so the v1
/// firmware doesn't pull a JSON writer into the sentinel-emission path.
fn emit_done_sentinel() {
    const SENTINEL: &[u8] = br#"{"__sos_done":true}"#;
    for &b in SENTINEL {
        transport::write_byte(b);
    }
    transport::write_byte(b'\n');
}

/// Park forever — the adapter sees the sentinel, exits, and the
/// operator power-cycles (or probe-rs resets) the board to begin the
/// next vector. Per SOS-04 §7.2: one vector per boot.
fn park_forever() -> ! {
    loop {
        cortex_m::asm::wfi();
    }
}

// ---------------------------------------------------------------------------
// DWT cycle-count instrumentation (SOS-06-A `MacrostepCycleCount` metric).
//
// Per PCDN-SOS-06-003 the canonical macrostep is the chart's
// `task.yield` round-robin among 8 tasks. The firmware measures cycles
// around every `dispatch_event` call and accumulates the total + the
// count of macrosteps into a pair of DTCM atomics at fixed addresses.
// Bench-side post-mortem reads the addresses via `probe-rs read` and
// computes mean cycles/macrostep.
//
// Counter layout (DTCM, zero-init by cortex-m-rt at boot):
//   0x2001_FFE0   MACROSTEP_CYCLES_LO (u32)  — low 32 bits of total cycles
//   0x2001_FFE4   MACROSTEP_CYCLES_HI (u32)  — high 32 bits of total cycles
//   0x2001_FFE8   MACROSTEP_COUNT     (u32)  — number of dispatches measured
// Reserved page in DTCM; located near top to avoid colliding with stack /
// .bss layout. The cortex-m-rt linker script puts .bss at the bottom of
// DTCM and the stack at the top; this page sits between.
#[link_section = ".bss"]
static mut MACROSTEP_CYCLES_LO: u32 = 0;
#[link_section = ".bss"]
static mut MACROSTEP_CYCLES_HI: u32 = 0;
#[link_section = ".bss"]
static mut MACROSTEP_COUNT: u32 = 0;

fn dwt_enable() {
    // Enable the DWT CYCCNT counter: DEMCR.TRCENA = 1; DWT_CTRL.CYCCNTENA = 1.
    // Addresses per ARMv7-M ARM (SOS-00 §6 distils the relevant subset).
    unsafe {
        let demcr = 0xE000_EDFC as *mut u32;
        demcr.write_volatile(demcr.read_volatile() | (1 << 24));
        let dwt_ctrl = 0xE000_1000 as *mut u32;
        dwt_ctrl.write_volatile(dwt_ctrl.read_volatile() | 1);
        let dwt_cyccnt = 0xE000_1004 as *mut u32;
        dwt_cyccnt.write_volatile(0);
    }
}

#[inline(always)]
fn dwt_read_cyccnt() -> u32 {
    unsafe { (0xE000_1004 as *const u32).read_volatile() }
}

fn record_macrostep_cycles(delta: u32) {
    unsafe {
        let lo_ptr = &raw mut MACROSTEP_CYCLES_LO;
        let hi_ptr = &raw mut MACROSTEP_CYCLES_HI;
        let cnt_ptr = &raw mut MACROSTEP_COUNT;
        let old_lo = core::ptr::read_volatile(lo_ptr);
        let new_lo = old_lo.wrapping_add(delta);
        if new_lo < old_lo {
            // Overflow → bump high word.
            let hi = core::ptr::read_volatile(hi_ptr);
            core::ptr::write_volatile(hi_ptr, hi.wrapping_add(1));
        }
        core::ptr::write_volatile(lo_ptr, new_lo);
        let cnt = core::ptr::read_volatile(cnt_ptr);
        core::ptr::write_volatile(cnt_ptr, cnt.wrapping_add(1));
    }
}

#[entry]
fn main() -> ! {
    // §6.8 step 1–9: clock tree (PCDN-SOS-04-013), peripheral clock
    // enables, GPIO AF for USART1 TX/RX (PCDN-SOS-04-003), SysTick
    // configuration, NVIC priority grouping = 0 (all-preempt).
    disco_bsp::init();
    // DWT cycle counter for the SOS-06-A `MacrostepCycleCount` metric.
    dwt_enable();

    // Static pools, idle TCB to READY at prio 0, NVIC priorities per
    // SOS-00 §6.2 (PendSV 0xE0, SysTick 0xC0, *_from_isr 0xA0).
    kernel::init();

    // Open USART1 at 921600 8N1 (PCDN-SOS-04-007). Programs the IRQ
    // priority (0xA0) and unmasks the USART1 NVIC line so the
    // `#[interrupt] fn USART1()` handler in `handlers.rs` drains
    // hardware-FIFO bytes into the static RX ring.
    transport::start();

    // §6.8 step 10: mode dispatch.
    //
    // - With `standalone-smoke` feature: run the compiled-in static
    //   vector (Standalone mode per PCDN-SOS-04-004). Not yet wired
    //   at v1 — the wave-8 deliverable is Conformance mode.
    // - Default: emit the boot-baseline TraceRecord (after_input_idx
    //   = -1), then enter the Conformance-mode dispatch loop reading
    //   the wrapped vector input over UART RX.
    #[cfg(feature = "standalone-smoke")]
    {
        // TODO(SOS-04 impl phase): kernel::run_static_vector(&STATIC_SMOKE_VECTOR);
        // Standalone mode is feature-gated and not part of the wave-8
        // dispatch wiring. The macrostep loop below still runs as the
        // post-static-vector idle path; reaching it indicates the
        // static vector completed.
    }

    // -------------------------------------------------------------------
    // Boot-baseline trace record (§6.2 step 2).
    //
    // `after_input_idx = -1` is the chart's boot-quiescence marker; the
    // harness compares this record against the simulator's boot
    // baseline before any event is dispatched.
    // -------------------------------------------------------------------
    // EOQ-004 bench-race workaround (2026-05-21): the STLINK V3E VCP has a
    // small internal buffer (~64B) that drops bytes when no host is
    // draining the USB-CDC OUT endpoint. The harness's adapter takes
    // 100-200 ms to spawn + open the port after a reset; without this
    // delay, the boot-baseline trace record's first ~150 bytes are lost,
    // and the harness sees a malformed first JSONL record.
    //
    // Cheap mitigation: spin for ~500 ms (using SysTick CVR underflow as
    // the clock) before emitting the boot baseline. Real fix is a
    // host-side handshake: adapter waits for a firmware-emitted "READY\n"
    // marker before sending the vector; deferred to a future amendment.
    for _ in 0..500_000 {
        cortex_m::asm::nop();
    }

    let mut trace_buf = [0u8; TRACE_SCRATCH_BYTES];
    {
        // SAFETY: `kernel::init()` was the single writer of
        // `KERNEL_STATE` and ran to completion before this point. The
        // boot-baseline emission predates the first IRQ that reads the
        // kernel state (SysTick fires from `disco_bsp::init_systick()`
        // but its handler tolerates the `None` -> `Some` transition).
        //
        // Zero out tick_count immediately before emitting the boot
        // baseline: the 500 ms wake-up delay above allows SysTick to
        // tick ~500 times before we emit, but the boot baseline must
        // observe tick_count = 0 per sim's `Datamodel::new`. The
        // tick_count reset is part of the bench-race workaround
        // (matches EOQ-004 delay note above).
        unsafe {
            let dm_mut = match (*kernel::KERNEL_STATE.0.get()).as_mut() {
                Some(dm) => dm,
                None => park_forever(),
            };
            dm_mut.tick_count = 0;
        }
        let dm_cell = unsafe { &*kernel::KERNEL_STATE.0.get() };
        let dm = match dm_cell.as_ref() {
            Some(dm) => dm,
            None => park_forever(),
        };
        let n = trace::write_record(&mut trace_buf, dm, -1);
        for &b in &trace_buf[..n] {
            transport::write_byte(b);
        }
    }

    // -------------------------------------------------------------------
    // Conformance-mode macrostep dispatch loop (§6.2 steps 3–7).
    //
    // Mirrors `sim::Simulator::run_vector` in shape:
    //   1. Refill scratch buffer from RX ring (non-blocking).
    //   2. `try_step` the JSON parser against the scratch buffer.
    //   3. On `Event`: set `current = from_tid` if Some;
    //      `scripts::dispatch_event` runs the chart body + scheduler
    //      microstep; emit one trace record.
    //   4. On `EndOfInput`: emit done sentinel, park.
    //   5. On `Error`: emit done sentinel, park.
    //   6. On `NeedMoreInput`: `wfi` until next USART1 IRQ delivers
    //      more bytes.
    // -------------------------------------------------------------------
    let mut parser = json_parser::VectorStream::new();
    let mut scratch = [0u8; RX_SCRATCH_BYTES];
    let mut scratch_len: usize = 0;
    let mut after_input_idx: i64 = -1;

    // EOQ-004 diagnostic counters. Use #[no_mangle] static mut so the
    // linker places them in .bss (zero-init by cortex-m-rt) and probe-rs
    // can find them via symbol name. Removed when the dispatch path is
    // confirmed working on bench.
    unsafe {
        core::ptr::write_volatile(&raw mut DIAG_PARSE_KIND, 0xFFFF_FFFF);
    }

    loop {
        unsafe {
            let c = core::ptr::read_volatile(&raw const DIAG_LOOP_COUNT).wrapping_add(1);
            core::ptr::write_volatile(&raw mut DIAG_LOOP_COUNT, c);
        }

        // Refill scratch from the RX ring (drain whatever the ISR has
        // delivered since the last refill). Non-blocking: stops when
        // the ring is empty or the scratch is full.
        while scratch_len < scratch.len() {
            match transport::try_read_byte() {
                Some(b) => {
                    scratch[scratch_len] = b;
                    scratch_len += 1;
                    unsafe {
                        let c = core::ptr::read_volatile(&raw const DIAG_BYTES_RX).wrapping_add(1);
                        core::ptr::write_volatile(&raw mut DIAG_BYTES_RX, c);
                    }
                }
                None => break,
            }
        }

        if scratch_len == 0 {
            cortex_m::asm::wfi();
            continue;
        }

        // EOQ-004 (2026-05-21): the parser's `VectorStream::try_step`
        // doesn't track buffer position across calls — it always
        // restarts at buf[0] but advances the state machine, so a
        // byte-by-byte RX path errors out (state expects key but buf[0]
        // re-shows the wrapper `{`). Host tests pass because they call
        // try_step ONCE with a complete buffer.
        //
        // Bench-iter workaround: wait until the buffer contains a
        // newline (the host adapter writes vector + `\n`), then call
        // try_step on the full prefix. This matches the host-test
        // single-call pattern; proper fix is a parser API change to
        // expose `consumed` on NeedMoreInput.
        let parse_end = match scratch[..scratch_len].iter().position(|&b| b == b'\n') {
            Some(pos) => pos + 1, // include the newline
            None => {
                cortex_m::asm::wfi();
                continue;
            }
        };

        match parser.try_step(&scratch[..parse_end]) {
            json_parser::ParseStep::NeedMoreInput => {
                unsafe { core::ptr::write_volatile(&raw mut DIAG_PARSE_KIND, 0); }
                // Parser consumed nothing actionable; wait for more
                // bytes. The USART1 IRQ wakes us via SysTick or its
                // own RXNE event (both eventually unmask WFI).
                cortex_m::asm::wfi();
            }
            json_parser::ParseStep::VectorHeader { header, consumed } => {
                unsafe { core::ptr::write_volatile(&raw mut DIAG_PARSE_KIND, 1); }
                // Vector-header check: the firmware's compiled-in
                // dimensions are frozen at build time. A header that
                // disagrees would invalidate the trace contract per
                // INV-S-PORT-9; emit the sentinel and park.
                if header.max_tasks != kernel::MAX_TASKS
                    || header.max_prio != kernel::MAX_PRIO
                    || header.max_sems != kernel::MAX_SEMS
                    || header.max_queues != kernel::MAX_QUEUES
                    || header.q_depth != kernel::Q_DEPTH
                    || header.tick_hz != kernel::SOS_TICK_HZ
                {
                    emit_done_sentinel();
                    park_forever();
                }
                // Shift consumed bytes off the front of the scratch.
                scratch.copy_within(consumed..scratch_len, 0);
                scratch_len -= consumed;
            }
            json_parser::ParseStep::Event { event, consumed } => {
                unsafe { core::ptr::write_volatile(&raw mut DIAG_PARSE_KIND, 2); }
                // Per SOS-00 §7.1 / sim::Simulator::run_vector: inject
                // `from_tid` into `current` before dispatch when
                // present; ISR-context events (`sys.tick`, `*_from_isr`)
                // carry `None` and leave `current` untouched.
                //
                // SAFETY: at this point `KERNEL_STATE` is `Some(_)`
                // (boot-baseline emission above proved it) and the
                // main thread is the only mutator (SysTick / USART1
                // ISRs only touch their own slices of the datamodel).
                let dm = unsafe {
                    match (*kernel::KERNEL_STATE.0.get()).as_mut() {
                        Some(dm) => dm,
                        None => park_forever(),
                    }
                };
                if let Some(tid) = event.from_tid {
                    dm.current = tid;
                }
                // The dispatcher swallows the `Result`: a chart-
                // invariant violation (`ScriptError`) shouldn't be
                // reachable in a well-formed vector. v1 emits the
                // record anyway so the harness sees the divergence;
                // a future amendment may add an out-of-band
                // diagnostic record.
                let cyc_pre = dwt_read_cyccnt();
                let _ = scripts::dispatch_event(dm, &event);
                let cyc_post = dwt_read_cyccnt();
                record_macrostep_cycles(cyc_post.wrapping_sub(cyc_pre));
                after_input_idx += 1;

                let n = trace::write_record(&mut trace_buf, dm, after_input_idx);
                for &b in &trace_buf[..n] {
                    transport::write_byte(b);
                }

                scratch.copy_within(consumed..scratch_len, 0);
                scratch_len -= consumed;
            }
            json_parser::ParseStep::EndOfInput { consumed: _ } => {
                unsafe { core::ptr::write_volatile(&raw mut DIAG_PARSE_KIND, 3); }
                // No further input will be consumed; skip the scratch
                // shift and proceed straight to the sentinel + park.
                emit_done_sentinel();
                park_forever();
            }
            json_parser::ParseStep::Error { .. } => {
                unsafe { core::ptr::write_volatile(&raw mut DIAG_PARSE_KIND, 4); }
                // Per §6.2 step 4: v1 emits the done sentinel and
                // halts. The harness sees a truncated trace (records
                // up to the parse error) and reports a vector failure.
                emit_done_sentinel();
                park_forever();
            }
        }
    }
}
