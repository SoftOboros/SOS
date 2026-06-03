//! NVIC exception handler bodies.
//!
//! Per SOS-04-CONCEPTS.md §6.4 (PendSV body), §6.5 (SVC vestigial),
//! §6.6 (SysTick body), and SOS-00 §6.1 / §6.2 / §6.4 (exception
//! assignment + priority assignment + EXC_RETURN inspection: PendSV
//! `0xE0`, SysTick `0xC0`, `*_from_isr` `0xA0`). Priority programming
//! lives in `disco_bsp::init_nvic_priorities()` per §6.8 step 6.
//!
//! Phase 3 (this commit) lands:
//!   * Real PendSV save/restore body — inline `asm!` per SOS-00 §6.4.
//!   * Minimal viable SysTick body — bumps `tick_count` (or `pend_ticks`
//!     when nested) and pends PendSV unconditionally. The full chart
//!     dispatch (`sys.tick` body — `delay`/`timeout` expiry walk) lands
//!     in a follow-up phase 3b; the marker is below.
//!   * SVCall stays the catch-bug stub per PCDN-SOS-00-002 (v1 transport
//!     is `DirectCallBasepri`; SVC is reserved for a future migration).

use core::arch::asm;
use cortex_m_rt::exception;

// Only the conformance-mode `SysTick` no-op touches `KERNEL_STATE` here; it
// is dropped under `host-exceptions` (a host supplies its own SysTick), so
// gate the import to match and keep the host build warning-clean.
#[cfg(not(feature = "host-exceptions"))]
use crate::kernel::KERNEL_STATE;

/// PendSV — context-switch primitive. NVIC priority `0xE0` per
/// SOS-00 §6.2 (programmed in `disco_bsp::init_nvic_priorities()`).
///
/// Behaviour per SOS-00 §6.4 and SOS-04 §6.4:
///
/// 1. Read `EXC_RETURN` (in LR on entry). Bit 4 of EXC_RETURN
///    discriminates the outgoing frame layout:
///      - `EXC_RETURN[4] == 1` ⇒ standard 8-word frame on the outgoing
///        PSP (R0-R3, R12, LR, PC, xPSR).
///      - `EXC_RETURN[4] == 0` ⇒ extended 26-word frame on the outgoing
///        PSP (standard + S0-S15 + FPSCR + padding). The OS MUST also
///        save/restore S16-S31 (callee-saved FP registers).
///
/// 2. If `OUTGOING_TID >= 0`, save R4-R11 (+ S16-S31 if extended) to
///    `TASK_SAVED_FRAMES[OUTGOING_TID]`, record the current PSP into
///    `TASK_PSPS[OUTGOING_TID]`, and set `had_fp_frame` to the
///    EXC_RETURN[4] state of the outgoing frame. `OUTGOING_TID == -1`
///    is the boot-path sentinel: no outgoing task; skip the save half.
///
/// 3. Load `TASK_PSPS[CURRENT_TID]` into PSP. Restore R4-R11 (+ S16-S31
///    if `had_fp_frame`) from `TASK_SAVED_FRAMES[CURRENT_TID]`.
///
/// 4. Reconstruct the EXC_RETURN sentinel for the incoming task:
///    `0xFFFFFFFD` (return to thread mode, PSP, no FP frame) or
///    `0xFFFFFFED` (same but with FP frame). The asm builds it from the
///    incoming `had_fp_frame` flag.
///
/// 5. DSB + ISB before `bx lr` so the new PSP is architecturally
///    visible before the exception epilogue uses it.
///
/// On entry, hardware has already pushed the outgoing task's R0-R3 /
/// R12 / LR / PC / xPSR (and, for the extended frame, S0-S15 + FPSCR +
/// padding) onto the outgoing PSP. The handler MUST NOT touch that
/// frame — it stays where hardware put it; the exception return on
/// `bx lr` pops it from the NEW PSP back into the registers.
///
/// The body is a single `asm!` block with `options(noreturn)` so the
/// Rust compiler emits no epilogue (the `bx lr` at the end of the asm
/// is the exception return).
#[exception]
fn PendSV() {
    unsafe {
        asm!(
            // ---- Outgoing save side ---------------------------------
            //
            // r3 := OUTGOING_TID (i32). If -1, skip the save block.
            "ldr   r3, ={outgoing_tid}",
            "ldr   r3, [r3]",
            "cmp   r3, #0",
            "blt   2f",                  // OUTGOING_TID < 0 ⇒ skip save
            //
            // r0 := PSP of outgoing task.
            "mrs   r0, psp",
            //
            // r1 := &TASK_PSPS[OUTGOING_TID]; store outgoing PSP there.
            "ldr   r1, ={task_psps}",
            "str   r0, [r1, r3, lsl #2]",
            //
            // r1 := &TASK_SAVED_FRAMES[OUTGOING_TID]. Each SavedFrame is
            // 100 bytes: regs[8] = 32, fp_regs[16] = 64, had_fp_frame
            // (bool, 1 byte; aligned/padded to 4 = 4 total trailing).
            // Layout: 0..32 = regs, 32..96 = fp_regs, 96 = had_fp_frame.
            // Size = 100 (with Rust's natural u32 alignment, the struct
            // is padded to a multiple of 4). Index by r3 * 100.
            "ldr   r1, ={task_saved_frames}",
            "movs  r2, #100",            // sizeof(SavedFrame) = 100
            "mla   r1, r2, r3, r1",      // r1 = base + r3 * 100
            //
            // Save R4-R11 → SavedFrame.regs[0..8] (offset 0).
            "stm   r1, {{r4-r11}}",
            //
            // EXC_RETURN[4] discriminator. Bit clear ⇒ extended (FPU)
            // frame ⇒ save S16-S31 and set had_fp_frame = 1.
            "tst   lr, #0x10",
            "bne   1f",                  // bit set ⇒ standard frame
            //
            // Extended frame: save S16-S31 → SavedFrame.fp_regs[0..16]
            // (offset 32 from the SavedFrame base in r1).
            "add   r2, r1, #32",
            "vstm  r2, {{s16-s31}}",
            // Set had_fp_frame = 1 at offset 96.
            "movs  r2, #1",
            "strb  r2, [r1, #96]",
            "b     2f",
            //
            "1:",                        // standard frame branch
            // Clear had_fp_frame at offset 96 so the restore side
            // doesn't try to pop a non-existent FP block.
            "movs  r2, #0",
            "strb  r2, [r1, #96]",
            //
            "2:",                        // ---- Incoming restore side -
            //
            // r3 := CURRENT_TID (i32). The syscall path guarantees this
            // is a valid task id at this point (>= 0 and the slot is
            // active). PendSV does not defend against a bad value —
            // INV-S5 makes it a port bug if one arrives.
            "ldr   r3, ={current_tid}",
            "ldr   r3, [r3]",
            //
            // r0 := TASK_PSPS[CURRENT_TID].
            "ldr   r1, ={task_psps}",
            "ldr   r0, [r1, r3, lsl #2]",
            //
            // r1 := &TASK_SAVED_FRAMES[CURRENT_TID].
            "ldr   r1, ={task_saved_frames}",
            "movs  r2, #100",
            "mla   r1, r2, r3, r1",
            //
            // Restore R4-R11 ← SavedFrame.regs.
            "ldm   r1, {{r4-r11}}",
            //
            // Inspect incoming had_fp_frame at offset 96.
            "ldrb  r2, [r1, #96]",
            "cmp   r2, #0",
            "beq   3f",                  // no FP frame on incoming
            //
            // Incoming task had an FP frame: restore S16-S31 from
            // SavedFrame.fp_regs (offset 32), and build EXC_RETURN =
            // 0xFFFFFFED (return to thread mode, PSP, extended frame).
            "add   r2, r1, #32",
            "vldm  r2, {{s16-s31}}",
            "ldr   lr, =0xFFFFFFED",
            "b     4f",
            //
            "3:",                        // standard-frame incoming
            "ldr   lr, =0xFFFFFFFD",     // thread mode, PSP, no FP frame
            //
            "4:",                        // ---- Exception return ------
            //
            // Install incoming PSP, fence, return-from-exception.
            "msr   psp, r0",
            "dsb",
            "isb",
            "bx    lr",
            //
            outgoing_tid       = sym crate::kernel::OUTGOING_TID,
            current_tid        = sym crate::kernel::CURRENT_TID,
            task_psps          = sym crate::kernel::TASK_PSPS,
            task_saved_frames  = sym crate::kernel::TASK_SAVED_FRAMES,
            options(noreturn),
        );
    }
}

/// SysTick — tick service. NVIC priority `0xC0` per SOS-00 §6.2.
/// Period = `(SystemCoreClock / SOS_TICK_HZ) - 1` per SOS-00 §6.6
/// (1 ms at 400 MHz CM7 → `LOAD = 399_999`).
///
/// Phase 3a (this commit) — minimal viable body:
///
///   1. Take the kernel state under SOS-00 §6.5 critical-section
///      semantics. SysTick at NVIC priority `0xC0` is already strictly
///      lower priority than `*_from_isr` IRQs at `0xA0`; a hardware IRQ
///      MAY preempt SysTick mid-body. The `.scxml`'s nested-tick
///      handling (`irq_nest > 0 → pend_ticks++`) covers that case.
///
///   2. If `irq_nest > 0 || sched_lock > 0`, increment `pend_ticks` (no
///      dispatch). Else increment `tick_count` and (in phase 3b) walk
///      `tcb[]` for delay/timeout expiry.
///
///   3. Pend PendSV unconditionally so the dispatch logic in phase 3b
///      observes the tick advance even if no task became READY this
///      pass (the scheduler is a no-op when no `resched` is needed,
///      but the unconditional pend keeps the wake-loop alive at v1).
///
/// Phase 3b extends step 2 to:
///   - Walk `dm.tcb[]` looking for `state == Delay && deadline <=
///     tick_count` ⇒ deposit `RC_OK`, move to `ready_push(id)`, set
///     `resched = true`.
///   - Same walk for `state == BlkSem/BlkQs/BlkQr && deadline != 0 &&
///     deadline <= tick_count` ⇒ deposit `RC_TIMEOUT`, remove from the
///     object's waiter list, move to `ready_push(id)`, set `resched`.
///   - Drain `pend_ticks` if it accumulated under nested ISR / sched-
///     lock and replay the above body once per accumulated tick.
///
/// The reference for the phase 3b body is `sos-sim`'s `scripts.rs`
/// `script_tick_idle_sys_tick_0` — the canonical transliteration of the
/// chart's `<transition event="sys.tick">` body.
///
/// SOS-04-B note: a real-execution host (the §5.5 embeddable front-end)
/// supplies its own `SysTick` body that calls [`crate::embed::on_sys_tick`]
/// to drive the macrostep + pend PendSV. To let the host own the `SysTick`
/// exception symbol without a duplicate-definition link error, this
/// conformance no-op is dropped under the `host-exceptions` feature (default
/// OFF — the conformance bin builds with the feature off and gets this body
/// unchanged; INV-S-EMBED-1). The feature gates **only** which crate defines
/// `SysTick`; PendSV / SVCall are unaffected.
#[cfg(not(feature = "host-exceptions"))]
#[exception]
fn SysTick() {
    // EOQ-005 (2026-05-21): in Conformance mode, "time" is driven by
    // explicit `sys.tick` events arriving via UART from the harness —
    // hardware SysTick MUST NOT auto-advance `dm.tick_count`, else
    // every per-event trace record diverges from sim by the wall-clock
    // elapsed (sim sees `tick_count: 0` throughout vector 0001; bench
    // saw `tick_count: 76, 153, 229, ...`).
    //
    // SOS-04 has two modes per PCDN-004 (`standalone-smoke` feature
    // flag): Standalone mode drives time from hardware SysTick;
    // Conformance mode receives time via UART events. v1 builds
    // without `standalone-smoke` → Conformance mode → SysTick body is
    // a no-op.
    //
    // Phase 3b (FAM-04-x): wrap this body in `#[cfg(feature =
    // "standalone-smoke")]` to re-enable hardware-tick increment when
    // the firmware is built for Standalone use.
    if false {
    unsafe {
        let cell = &mut *KERNEL_STATE.0.get();
        if let Some(dm) = cell.as_mut() {
            if dm.irq_nest > 0 || dm.sched_lock > 0 {
                dm.pend_ticks = dm.pend_ticks.saturating_add(1);
            } else {
                dm.tick_count = dm.tick_count.saturating_add(1);
                // TODO(phase 3b): walk dm.tcb[] for delay/timeout
                // expiry; deposit RC_OK / RC_TIMEOUT into tcb[id].msg;
                // move expired tasks to ready_push; set
                // dm.resched = true if any task unblocked. Reference
                // implementation: sim/sos-sim/src/scripts.rs
                // `script_tick_idle_sys_tick_0`.
            }
        }
    }
    } // end if false (EOQ-005 hardware-SysTick-disabled gate)

    // EOQ-004 (2026-05-21): the previous unconditional `set_pendsv()`
    // here caused first-bench HardFault. v1 doesn't run actual tasks —
    // PendSV's context-switch attempts load TASK_PSPS[CURRENT_TID] which
    // is uninitialised for idle (no task body, no PSP setup). The fault
    // path: SysTick fires → set_pendsv → PendSV tail-chains → loads
    // null PSP → INVSTATE UsageFault → escalates to HardFault.
    //
    // For conformance-mode operation, PendSV is unnecessary: the
    // macrostep dispatch loop in `main.rs` mutates the datamodel and
    // emits trace records directly from main-thread context. Real task
    // switching is FAM-04-x deferred future work.
    //
    // Phase 3b will re-enable a defensive set_pendsv path that:
    //   (a) gates on `dm.resched` to avoid spurious pends, and
    //   (b) initialises TASK_PSPS[i] at task.create time so PendSV
    //       always loads a valid PSP.
    //
    // For now, no PendSV is pended.
}

/// SVC — reserved per SOS-04 §6.5 + PCDN-SOS-00-002 → `DirectCallBasepri`.
///
/// SVC is **unused** at v1; the handler is installed only to catch an
/// accidental `svc #imm` instruction (it would be a port bug for one to
/// fire). The future `SvcInstruction` migration (FAM noted in SOS-00
/// §15) replaces the body in a coordinated SOS-04-B / SOS-05-B
/// amendment once v1 ports are conformance-validated. The handler
/// symbol's stability across that migration is why this stub exists
/// rather than no SVC handler at all.
#[exception]
fn SVCall() {
    // Should never fire under DirectCallBasepri. Reaching here is a
    // port bug; bkpt to surface it immediately to whatever debugger is
    // attached. With no debugger attached the bkpt is a no-op and we
    // fall into the wfi loop.
    cortex_m::asm::bkpt();
    loop {
        cortex_m::asm::wfi();
    }
}
