//! Embeddable host-app library API — construction + tick subset.
//!
//! Per `docs/concepts/SOS-04-B-EMBEDDABLE-KERNEL.md`:
//!   * §5.2 PCDN-SOS-04-B-002 (ratified 2026-06-03) — task entry ABI is
//!     `extern "C" fn() -> !`; at create time the kernel primes a basic
//!     Cortex-M exception-return frame at the top of the task's PSP region
//!     (`xPSR = 0x0100_0000`, `PC = entry`, `LR = task_exit_trap`,
//!     `R0..R3/R12 = 0`, 8-byte aligned) and sets `TASK_PSPS[id]`.
//!   * §5.5 — the frozen `no_std` library API. **This module now implements
//!     the COMPLETE §5.5 surface** across two waves:
//!       - wave 2 (PCDN-002): construction + tick — [`create_sem`],
//!         [`create_task`], [`start_scheduler`], [`on_sys_tick`];
//!       - wave 3 (PCDN-003): the real-context syscall / ISR front-ends —
//!         [`sem_take`], [`task_delay`], [`sem_give_from_isr`], each running
//!         the DirectCallBasepri envelope (mask BASEPRI → unchanged
//!         `dispatch_event` macrostep → unmask → pend PendSV iff `current`
//!         changed). The pend predicate + the `sem_give_from_isr` yield hint
//!         are factored into the pure, host-tested [`envelope_outcome`].
//!
//! ## Invariants honoured (§6)
//!
//! - **INV-S-EMBED-1 (model/trace immutability):** every model effect goes
//!   through the unchanged [`crate::scripts::dispatch_event`] macrostep
//!   using the existing [`crate::event`] payloads — no kernel state-machine,
//!   `Tcb`, or trace bytes change. The additions here (PSP frame priming,
//!   the first-PendSV trigger) are pure port-layer state never serialised.
//! - **INV-S-EMBED-2 (one core / two front-ends):** these functions drive
//!   the same `dispatch_event` core the conformance bin drives.
//! - **INV-S-EMBED-3 (host owns app / kernel owns scheduling):** the host
//!   supplies the `entry` fn; the kernel owns lifecycle / scheduler /
//!   PendSV.
//!
//! ## Context-switch execution is bench-only
//!
//! The actual register save/restore is the Cortex-M PendSV asm in
//! [`crate::handlers`]; it can only be exercised on the board. The
//! host-testable surface is [`compute_primed_frame`] (the pure
//! frame-layout math), unit-tested below.

// The runtime functions ([`create_sem`], [`create_task`], [`start_scheduler`],
// [`on_sys_tick`], [`task_exit_trap`]) touch `cortex_m` intrinsics and the
// live `KERNEL_STATE`; they only build on the embedded target. The pure
// frame-layout math ([`compute_primed_frame`], [`PrimedFrame`], constants) is
// host-visible so SOS-04-B §8 gate (c) / wave-2 can unit-test the priming
// computation on the host. INV-S-EMBED-1: a build-target gate only — no model
// or trace change.
#[cfg(target_arch = "arm")]
use crate::event::{Event, EventData, EventName};
#[cfg(target_arch = "arm")]
use crate::kernel::{
    self, Datamodel, StackRegion, TaskId, MAX_TASKS, TASK_STACK_BYTES,
};

// ---------------------------------------------------------------------------
// Pure, host-testable frame-layout math (PCDN-002).
// ---------------------------------------------------------------------------

/// The basic (non-FPU) Cortex-M exception-return frame is 8 words = 32 bytes.
/// Hardware pops it from the PSP on exception return, in this address order
/// (low → high): `R0, R1, R2, R3, R12, LR, PC, xPSR`. The PSP points at the
/// lowest word (`R0`).
pub const BASIC_FRAME_WORDS: usize = 8;
/// Size in bytes of [`BASIC_FRAME_WORDS`].
pub const BASIC_FRAME_BYTES: usize = BASIC_FRAME_WORDS * 4;

/// `xPSR` value for a freshly-primed task: only the Thumb (T) bit set
/// (bit 24). All ARMv7-M code is Thumb, so the T bit MUST be set or the
/// first instruction fetch faults (INVSTATE UsageFault).
pub const INITIAL_XPSR: u32 = 0x0100_0000;

/// The fully-primed basic exception-return frame plus the resulting PSP.
///
/// `frame` is in hardware pop order (`R0, R1, R2, R3, R12, LR, PC, xPSR`);
/// `psp` is the stack pointer that PendSV installs (`MSR PSP, psp`) so the
/// exception-return epilogue pops `frame` into the registers. `psp` equals
/// the address of `frame[0]` (`R0`).
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct PrimedFrame {
    /// The 8 hardware-frame words, in pop order.
    pub frame: [u32; BASIC_FRAME_WORDS],
    /// PSP value to install (address of `frame[0]` in the task's stack).
    pub psp: u32,
}

/// Compute the primed basic exception-return frame for a task.
///
/// `stack_base` is the low address of the task's PSP region;
/// `stack_bytes` its size. The frame is placed at the TOP of the region
/// (`stack_base + stack_bytes`), 8-byte aligned per AAPCS / ARM ARM
/// B1.5.7, with the PSP `BASIC_FRAME_BYTES` below the aligned top.
///
/// `entry` is the task body address; `exit_trap` is the `LR` target a
/// returning task lands on. Per the Thumb ABI both are stored with bit 0
/// set (the interworking bit); hardware loads `PC = entry & ~1` while
/// `xPSR.T` (set via [`INITIAL_XPSR`]) keeps the core in Thumb state, and
/// `LR` keeps bit 0 set so a `bx lr` / `pop {pc}` from the body returns in
/// Thumb state. `R0..R3` and `R12` are zeroed (PCDN-002, `R0 = 0`).
///
/// Pure function: no `static` access, no asm — host-testable.
pub const fn compute_primed_frame(
    stack_base: u32,
    stack_bytes: usize,
    entry: u32,
    exit_trap: u32,
) -> PrimedFrame {
    // Top of the region, then align DOWN to an 8-byte boundary so the
    // hardware-popped frame leaves SP 8-byte aligned (exception-entry
    // alignment requirement).
    let raw_top = stack_base + stack_bytes as u32;
    let aligned_top = raw_top & !0x7u32;
    let psp = aligned_top - BASIC_FRAME_BYTES as u32;

    // Thumb interworking: PC/LR carry bit 0 set. The core uses xPSR.T for
    // the actual ISA state; storing PC with bit 0 set is the conventional
    // (and harmless) form a `bx`/exception-return treats as Thumb.
    let pc = entry | 1;
    let lr = exit_trap | 1;

    PrimedFrame {
        // R0, R1, R2, R3, R12, LR, PC, xPSR
        frame: [0, 0, 0, 0, 0, lr, pc, INITIAL_XPSR],
        psp,
    }
}

// ---------------------------------------------------------------------------
// Pure, host-testable DirectCallBasepri envelope decision (PCDN-003).
// ---------------------------------------------------------------------------

/// Outcome of one DirectCallBasepri syscall/ISR envelope step, derived purely
/// from the model's `current` task id before and after the macrostep.
///
/// PCDN-003: every real-context entry runs the existing `dispatch_event`
/// macrostep under a BASEPRI mask, then decides — from `current` alone —
/// whether to pend PendSV. The model's scheduler microstep (`sched.run`)
/// always promotes the highest-priority READY task to `current`; so a change
/// in `current` across the macrostep is exactly the signal that a different
/// (i.e. higher-priority, by the model's `pick_next` ordering) task must now
/// run. This is the load-bearing equivalence the envelope rests on:
///
///   * **pend PendSV** iff `current` changed (the running context must be
///     swapped on PendSV exit — SOS-04 §6.4);
///   * the **yield hint** returned by `sem_give_from_isr` ("a higher-priority
///     task was made ready") is the *same* predicate — when an ISR `give`
///     unblocks a waiter the macrostep's `sched.run` promotes it to `current`
///     iff it outranks the interrupted task, mirroring the analyzer's
///     `AudioSemaphore::give_from_isr() -> bool` contract.
///
/// Factored out as a pure function so the predicate (the only non-asm part of
/// the envelope) is host-unit-testable without the live `KERNEL_STATE` or any
/// `cortex_m` intrinsic. INV-S-EMBED-1: no model/trace state — pure math over
/// two ids the macrostep already computed.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct EnvelopeOutcome {
    /// Whether PendSV must be pended (the running task changed).
    pub pend_pendsv: bool,
    /// The outgoing task id to record in `OUTGOING_TID` when `pend_pendsv`
    /// (the task that was running before the macrostep). Meaningless when
    /// `!pend_pendsv`.
    pub outgoing: i32,
    /// The incoming task id to record in `CURRENT_TID` when `pend_pendsv`
    /// (the task selected by the macrostep). Meaningless when `!pend_pendsv`.
    pub incoming: i32,
}

/// Decide the envelope outcome from the `current` ids straddling the macrostep.
///
/// `prev_current` is `dm.current` before `dispatch_event`; `new_current` is
/// `dm.current` after. PendSV is pended (and the yield hint is true) iff they
/// differ — see [`EnvelopeOutcome`] for why this single predicate serves both
/// the context-switch request and the ISR yield hint.
///
/// Pure function: no `static` access, no asm — host-testable.
pub const fn envelope_outcome(prev_current: i32, new_current: i32) -> EnvelopeOutcome {
    let changed = new_current != prev_current;
    EnvelopeOutcome {
        pend_pendsv: changed,
        outgoing: prev_current,
        incoming: new_current,
    }
}

// ---------------------------------------------------------------------------
// task_exit_trap — the LR target for a primed task (PCDN-002).
// ---------------------------------------------------------------------------

/// Where a returning task lands. A SOS task entry is `extern "C" fn() -> !`
/// and MUST NOT return; if one does, control falls through to its `LR`,
/// which create-time priming points here. A returning task is a bug — halt
/// (breakpoint for an attached debugger, then `wfi` forever).
///
/// Stored into the primed frame's `LR` slot with bit 0 set (Thumb).
#[cfg(target_arch = "arm")]
pub extern "C" fn task_exit_trap() -> ! {
    cortex_m::asm::bkpt();
    loop {
        cortex_m::asm::wfi();
    }
}

/// Host build of [`task_exit_trap`] (test/doc only): the `cortex_m::asm`
/// intrinsics do not link off-target, so the host variant is a plain spin.
/// Its only host use is taking its address in the priming unit tests; it is
/// never executed.
#[cfg(not(target_arch = "arm"))]
pub extern "C" fn task_exit_trap() -> ! {
    loop {}
}

// ---------------------------------------------------------------------------
// Internal: drive a model event through the unchanged macrostep core.
// ---------------------------------------------------------------------------

/// Run one [`Event`] against the live `KERNEL_STATE` via the unchanged
/// [`crate::scripts::dispatch_event`] macrostep (INV-S-EMBED-1: no new model
/// semantics, reuse the existing dispatch path).
///
/// # Safety
/// Caller MUST ensure `kernel::init()` has populated `KERNEL_STATE` and that
/// no concurrent mutator of `KERNEL_STATE` runs (construction happens at
/// boot before the scheduler / interrupts touch the kernel; the tick path
/// runs from SysTick ISR context — see [`on_sys_tick`]). Mirrors the access
/// pattern the conformance bin uses (`main.rs` dispatch loop).
#[cfg(target_arch = "arm")]
unsafe fn dispatch(event: &Event) {
    let cell = &mut *kernel::KERNEL_STATE.0.get();
    if let Some(dm) = cell.as_mut() {
        // Surface-level ScriptErrors are chart-invariant-unreachable for
        // well-formed construction/tick events; ignore as the bin does for
        // the analogous boot path.
        let _ = crate::scripts::dispatch_event(dm, event);
    }
}

// ---------------------------------------------------------------------------
// §5.5 — Construction (boot context, before the scheduler runs).
// ---------------------------------------------------------------------------

/// Create a semaphore. Dispatches the existing `sem.create` model event so
/// model state matches exactly (no new semantics — INV-S-EMBED-1/2).
///
/// `id` is the descriptor slot (`0..MAX_SEMS`), `initial` the starting
/// count, `max` the ceiling. Boot-context only.
///
/// # Safety
/// Call at boot, before [`start_scheduler`], after `kernel::init()`.
#[cfg(target_arch = "arm")]
pub unsafe fn create_sem(id: u8, initial: u32, max: u32) {
    let event = Event {
        name: EventName::SemCreate,
        data: EventData::SemCreate {
            id: id as i16,
            initial,
            max,
        },
        from_tid: None,
    };
    dispatch(&event);
}

/// Create a task with a real entry function (PCDN-002).
///
/// Three effects, in order:
///   1. **Prime the PSP frame** — write the basic exception-return frame
///      ([`compute_primed_frame`]) to the TOP of `TASK_STACKS[id]` so the
///      first PendSV switch "returns" into `entry`.
///   2. **Set `TASK_PSPS[id]`** to the primed PSP (overriding the benign
///      placeholder `kernel::init()` staged).
///   3. **Dispatch `task.create{id, prio}`** — the unchanged model event;
///      `entry`/PSP are port-layer and NOT serialised (INV-S-EMBED-1).
///
/// `entry` is `extern "C" fn() -> !` (PCDN-002 = (A)); a returning task
/// reaches [`task_exit_trap`].
///
/// # Safety
/// Call at boot, before [`start_scheduler`], after `kernel::init()`.
/// `id` MUST be a valid task slot (`0..MAX_TASKS`); the model event rejects
/// out-of-range ids (`rc = Inval`) but the PSP priming below indexes the
/// static stack pool directly, so an out-of-range `id` is UB.
#[cfg(target_arch = "arm")]
pub unsafe fn create_task(id: TaskId, prio: u8, entry: extern "C" fn() -> !) {
    debug_assert!(id >= 0 && (id as usize) < MAX_TASKS);

    // (1)+(2): prime PSP frame and set TASK_PSPS[id]. Address the static
    // stack pool via raw pointers (avoids a shared ref to `static mut`,
    // matching kernel::init()'s addr_of! pattern / Rust 2024 lint).
    let stack_base = {
        let base = core::ptr::addr_of!(kernel::TASK_STACKS) as *const StackRegion;
        let slot = base.add(id as usize) as *const u8;
        slot as u32
    };
    let primed = compute_primed_frame(
        stack_base,
        TASK_STACK_BYTES,
        entry as *const () as usize as u32,
        task_exit_trap as *const () as usize as u32,
    );
    // Write the 8 frame words at the primed PSP (top of the region).
    let frame_ptr = primed.psp as *mut u32;
    for (i, &w) in primed.frame.iter().enumerate() {
        core::ptr::write_volatile(frame_ptr.add(i), w);
    }
    // Saved callee-registers start zeroed (SavedFrame::new); the first
    // restore reads R4-R11/S16-S31 as 0, which is correct for a task that
    // has never run. Set TASK_PSPS[id] to the primed frame's SP.
    kernel::TASK_PSPS[id as usize] = primed.psp;

    // (3): the unchanged model event. Entry/PSP are not part of it.
    let event = Event {
        name: EventName::TaskCreate,
        data: EventData::TaskCreate { id, prio },
        from_tid: None,
    };
    dispatch(&event);
}

/// Start the scheduler: select the highest-priority READY task and trigger
/// the first PendSV to context-switch INTO its primed PSP frame. Never
/// returns.
///
/// **First-switch handling.** PendSV's save side keys off `OUTGOING_TID`:
/// when it is `-1` (the boot sentinel, [`kernel::OUTGOING_TID`]'s
/// initialiser) PendSV skips the save half entirely (`handlers.rs`
/// `cmp r3,#0; blt 2f`). So the very first switch has no outgoing context
/// to corrupt — we leave `OUTGOING_TID = -1` and only set `CURRENT_TID` to
/// the chosen task. The currently-executing MSP boot context is simply
/// discarded; nothing is saved for it. This is exactly the sentinel the
/// PendSV body was written to honour, so **no PendSV asm change is needed.**
///
/// Effects:
///   1. Run the model's scheduler microstep (`sched.run`) so `current` is
///      the highest-priority READY task (reuse the existing dispatch path —
///      `script_sched_idle_sched_run_0` via the macrostep `resched` flag is
///      already exercised at create; here we force one explicit `pick_next`
///      to be certain `current` is selected even if no `resched` was left
///      pending).
///   2. Set `CURRENT_TID = current`, leave `OUTGOING_TID = -1`.
///   3. Pend PendSV and enable interrupts; the switch happens on the
///      PendSV tail-chain. Spin in `wfi` until it fires (it fires
///      immediately once PendSV is unmasked).
///
/// # Safety
/// Call exactly once, at the end of boot, after all [`create_task`] calls
/// and `kernel::init()`. Never returns.
#[cfg(target_arch = "arm")]
pub unsafe fn start_scheduler() -> ! {
    // (1) Ensure the highest-priority ready task is `current`. Run the
    // model scheduler microstep directly on the live state — same body the
    // macrostep runs (INV-S-EMBED-2). pick_next() promotes the top ready
    // task to RUNNING and sets `current`.
    let selected: i32 = {
        let cell = &mut *kernel::KERNEL_STATE.0.get();
        match cell.as_mut() {
            Some(dm) => {
                // If a task is already RUNNING (the model promotes idle/created
                // tasks), pick_next round-robins; calling it here selects the
                // highest-priority ready task deterministically. It is the same
                // `script_sched_idle_sched_run_0` body (Datamodel::pick_next).
                let _ = Datamodel::pick_next(dm);
                dm.current as i32
            }
            None => -1,
        }
    };

    // (2) Wire the PendSV TIDs. OUTGOING stays -1 (first switch: nothing to
    // save). CURRENT_TID is the task PendSV restores into.
    kernel::OUTGOING_TID = -1;
    kernel::CURRENT_TID = selected;

    // (3) Pend PendSV; unmask; let the tail-chain switch into the task.
    cortex_m::peripheral::SCB::set_pendsv();
    cortex_m::asm::dsb();
    cortex_m::asm::isb();
    // Enable interrupts so PendSV (lowest priority) can fire once we leave
    // any active masking. PendSV switches into the task and never returns
    // here through normal flow.
    cortex_m::interrupt::enable();

    loop {
        cortex_m::asm::wfi();
    }
}

// ---------------------------------------------------------------------------
// §5.5 — ISR context: SysTick body.
// ---------------------------------------------------------------------------

/// SysTick handler body (§5.5). Dispatches the existing `sys.tick` model
/// event (advancing delays/deadlines via the unchanged macrostep —
/// `script_tick_idle_sys_tick_0`) and pends PendSV iff `current` changed.
///
/// PCDN-003 (`task_delay` syscall front-end) is NOT added here — only the
/// tick advance + conditional context-switch request.
///
/// First-switch / re-entry note: when the tick unblocks a higher-priority
/// task the macrostep updates `current`; we then record the outgoing task
/// in `OUTGOING_TID`, the incoming in `CURRENT_TID`, and pend PendSV so the
/// switch happens on PendSV exit (SOS-04 §6.4). When `current` is unchanged
/// no PendSV is pended (avoids the spurious-pend HardFault EOQ-004 fixed).
///
/// # Safety context
/// Runs from SysTick ISR context. `KERNEL_STATE` access is sound because
/// SysTick (NVIC `0xC0`) and the construction path are not concurrent with
/// each other in the well-formed boot→run ordering; a future PCDN-003
/// task-context syscall path will share `KERNEL_STATE` under the
/// DirectCallBasepri envelope.
#[cfg(target_arch = "arm")]
pub fn on_sys_tick() {
    // SAFETY: ISR-context single-access to KERNEL_STATE; see fn doc. The
    // dispatch reuses the unchanged macrostep (INV-S-EMBED-1).
    unsafe {
        let prev_current: i32 = {
            let cell = &*kernel::KERNEL_STATE.0.get();
            match cell.as_ref() {
                Some(dm) => dm.current as i32,
                None => return,
            }
        };

        dispatch(&Event::sys_tick());

        let new_current: i32 = {
            let cell = &*kernel::KERNEL_STATE.0.get();
            match cell.as_ref() {
                Some(dm) => dm.current as i32,
                None => return,
            }
        };

        // Same pend predicate the PCDN-003 syscall envelope uses (factored
        // into the host-tested `envelope_outcome`): pend PendSV iff `current`
        // changed. SysTick already runs at `0xC0` (≥ kernel-aware), so no
        // BASEPRI bracket is needed here — the ISR context is the mask.
        let outcome = envelope_outcome(prev_current, new_current);
        if outcome.pend_pendsv {
            // Record the switch endpoints for PendSV and request it. The
            // outgoing task is the one that was running; PendSV saves its
            // live frame, restores the incoming. -1 ↔ valid transitions are
            // handled by PendSV's OUTGOING_TID sentinel check.
            kernel::OUTGOING_TID = outcome.outgoing;
            kernel::CURRENT_TID = outcome.incoming;
            cortex_m::peripheral::SCB::set_pendsv();
        }
    }
}

// ---------------------------------------------------------------------------
// §5.5 — Real-context syscall / ISR front-ends (PCDN-003).
//
// Each runs the DirectCallBasepri envelope (SOS-00 PCDN-SOS-00-002 / SOS-04
// §6.5): mask BASEPRI to the kernel-aware level (0xA0) → run the *existing*
// `dispatch_event` macrostep for the corresponding model event → unmask
// (0x00) → pend PendSV iff `current` changed (the switch happens on PendSV
// exit, SOS-04 §6.4). No kernel logic is duplicated and no model semantics
// are added: the only additions are the BASEPRI bracket and the PendSV pend,
// both pure port-layer (INV-S-EMBED-1). The pend predicate + yield hint are
// factored into the host-tested [`envelope_outcome`].
// ---------------------------------------------------------------------------

/// Kernel-aware BASEPRI mask level (SOS-04 §6.5 / SOS-00 §6.2): masks every
/// interrupt at or below `*_from_isr` priority (`0xA0`) — including SysTick
/// (`0xC0`) and PendSV (`0xE0`) — so the macrostep runs atomically against
/// the live `KERNEL_STATE`. `0x00` lifts the mask.
#[cfg(target_arch = "arm")]
const KERNEL_BASEPRI: u8 = 0xA0;

/// Run one model `event` through the macrostep inside the DirectCallBasepri
/// envelope and request a context switch iff `current` changed.
///
/// Shared by every real-context syscall/ISR front-end below: it brackets the
/// unchanged [`dispatch`] (→ `dispatch_event`) with a BASEPRI raise/lower
/// (DSB/ISB ordered per SOS-04 §6.5), reads `current` straddling the
/// macrostep, and — via the pure [`envelope_outcome`] — records the
/// outgoing/incoming TIDs and pends PendSV when they differ. Returns the
/// [`EnvelopeOutcome`] so the ISR `give` path can surface the yield hint.
///
/// # Safety
/// Caller MUST ensure `kernel::init()` has run. From task context the BASEPRI
/// raise makes the macrostep atomic against `*_from_isr` / SysTick; from ISR
/// context (already at `≥ 0xA0`) the raise is a benign no-op-or-raise.
#[cfg(target_arch = "arm")]
unsafe fn run_envelope(event: &Event) -> EnvelopeOutcome {
    // --- mask BASEPRI to the kernel-aware level (enter the envelope) ---
    cortex_m::register::basepri::write(KERNEL_BASEPRI);
    cortex_m::asm::dsb();
    cortex_m::asm::isb();

    let prev_current: i32 = {
        let cell = &*kernel::KERNEL_STATE.0.get();
        match cell.as_ref() {
            Some(dm) => dm.current as i32,
            None => {
                // Nothing to drive; lift the mask and bail.
                cortex_m::asm::dsb();
                cortex_m::asm::isb();
                cortex_m::register::basepri::write(0x00);
                return envelope_outcome(0, 0);
            }
        }
    };

    // The unchanged macrostep (INV-S-EMBED-1/2).
    dispatch(event);

    let new_current: i32 = {
        let cell = &*kernel::KERNEL_STATE.0.get();
        match cell.as_ref() {
            Some(dm) => dm.current as i32,
            None => prev_current,
        }
    };

    let outcome = envelope_outcome(prev_current, new_current);

    // --- unmask BASEPRI (exit the envelope) ---
    cortex_m::asm::dsb();
    cortex_m::asm::isb();
    cortex_m::register::basepri::write(0x00);

    // Pend PendSV iff `current` changed; the actual save/restore happens on
    // PendSV exit (SOS-04 §6.4) once BASEPRI is below 0xE0 (just lifted).
    if outcome.pend_pendsv {
        kernel::OUTGOING_TID = outcome.outgoing;
        kernel::CURRENT_TID = outcome.incoming;
        cortex_m::peripheral::SCB::set_pendsv();
    }

    outcome
}

/// Take a semaphore, blocking the **calling task** if it is unavailable
/// (§5.5). Dispatches the existing `sem.take{sid, timeout}` model event under
/// the DirectCallBasepri envelope; `timeout == -1` blocks forever, `0` is
/// no-wait, `> 0` is a tick deadline (the model's `script_sys_idle_sem_take_0`
/// owns all of this — no duplication here).
///
/// If the sem is unavailable and a wait is requested, the macrostep blocks the
/// caller (`block_current` → `BlkSem`) and `sched.run` promotes the next task
/// to `current`; the envelope then pends PendSV so the caller is switched away
/// and resumes only when a `sem_give` / `sem_give_from_isr` unblocks it
/// (SOS-04 §6.4). If the sem is available, no block / no switch occurs.
///
/// # Safety
/// MUST be called from **task context** (a running task — `dm.current >= 0`).
/// `sem.take` reads `dm.current` to identify the blocker; calling it from ISR
/// context (where the interrupted task, not the kernel, owns `current`) is a
/// precondition violation (the model returns `BadState` if `current < 0`).
/// `kernel::init()` MUST have run and the sem MUST have been created.
#[cfg(target_arch = "arm")]
pub fn sem_take(sid: u8, timeout: i32) {
    // SAFETY: task-context single-entry to the envelope; see fn doc.
    unsafe {
        let event = Event {
            name: EventName::SemTake,
            data: EventData::SemOp {
                sid: sid as i16,
                timeout: timeout as i64,
            },
            from_tid: None,
        };
        let _ = run_envelope(&event);
    }
}

/// Delay the **calling task** for `ticks` SysTick periods (§5.5). Dispatches
/// the existing `task.delay{ticks}` model event under the envelope; the
/// macrostep blocks the caller (`block_current` → `Delay`, deadline
/// `tick_count + ticks`) and `sched.run` selects the next task, so the
/// envelope pends PendSV and the caller yields. It is woken when
/// [`on_sys_tick`] advances `tick_count` past the deadline.
///
/// `ticks == 0` is a plain yield (the model raises `resched` without blocking).
///
/// # Safety
/// MUST be called from **task context**. `kernel::init()` MUST have run.
#[cfg(target_arch = "arm")]
pub fn task_delay(ticks: u32) {
    // SAFETY: task-context single-entry to the envelope; see fn doc.
    unsafe {
        let event = Event {
            name: EventName::TaskDelay,
            data: EventData::TaskDelay {
                ticks: ticks as i64,
            },
            from_tid: None,
        };
        let _ = run_envelope(&event);
    }
}

/// Give a semaphore from **ISR context** (§5.5). Dispatches the existing
/// `sem.give_from_isr{sid}` model event under the envelope; if a task was
/// waiting on the sem the macrostep unblocks it and `sched.run` may promote it
/// to `current`. PendSV is pended iff `current` changed.
///
/// **Returns the yield hint** — `true` iff a higher-priority task was made
/// ready (i.e. `current` changed across the macrostep). This is the SOS mirror
/// of the analyzer's `AudioSemaphore::give_from_isr() -> bool`: the ISR uses it
/// to decide whether a `portYIELD_FROM_ISR`-equivalent is warranted. Because
/// the envelope already pends PendSV on the same predicate, the hint is
/// advisory for the caller; the switch is requested regardless.
///
/// # Safety
/// MUST be called from **ISR context** (a kernel-aware IRQ at `≥ 0xA0`,
/// SOS-00 §6.1 — e.g. the host's HSEM doorbell ISR). `kernel::init()` MUST
/// have run. `sem.give_from_isr` does not consult `current`, so it is safe
/// when no task is running.
#[cfg(target_arch = "arm")]
pub fn sem_give_from_isr(sid: u8) -> bool {
    // SAFETY: ISR-context single-entry to the envelope; see fn doc.
    unsafe {
        let event = Event {
            name: EventName::SemGiveFromIsr,
            data: EventData::SemOp {
                sid: sid as i16,
                timeout: 0, // ignored by sem.give_from_isr
            },
            from_tid: None,
        };
        run_envelope(&event).pend_pendsv
    }
}

// ---------------------------------------------------------------------------
// Host unit tests — the PURE frame-layout math (PCDN-002) + envelope
// decision (PCDN-003).
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use crate::kernel::TASK_STACK_BYTES;

    // A fake task entry for address-taking in tests (host target). It is
    // never called; only its address is compared.
    extern "C" fn fake_entry() -> ! {
        loop {}
    }

    #[test]
    fn primed_frame_fields() {
        // Pretend stack region: base 0x2000_0000, 2 KiB (the real
        // TASK_STACK_BYTES). Use a fabricated entry address with bit0
        // clear so we can assert the Thumb bit is OR'd in.
        let base: u32 = 0x2000_0000;
        let entry_addr: u32 = 0x0800_1234; // bit0 clear
        let exit_addr: u32 = task_exit_trap as *const () as usize as u32;

        let p = compute_primed_frame(base, TASK_STACK_BYTES, entry_addr, exit_addr);

        // xPSR: Thumb bit only.
        assert_eq!(p.frame[7], 0x0100_0000, "xPSR must have only the T bit");
        assert_eq!(p.frame[7], INITIAL_XPSR);

        // PC = entry | 1 (Thumb interworking).
        assert_eq!(p.frame[6], entry_addr | 1, "PC must be entry with Thumb bit");

        // LR = task_exit_trap | 1.
        assert_eq!(p.frame[5], exit_addr | 1, "LR must be task_exit_trap addr (Thumb)");

        // R0..R3 and R12 zeroed (PCDN-002 R0 = 0).
        assert_eq!(p.frame[0], 0, "R0 must be 0");
        assert_eq!(p.frame[1], 0, "R1 must be 0");
        assert_eq!(p.frame[2], 0, "R2 must be 0");
        assert_eq!(p.frame[3], 0, "R3 must be 0");
        assert_eq!(p.frame[4], 0, "R12 must be 0");
    }

    #[test]
    fn psp_alignment_and_position() {
        let base: u32 = 0x2000_0000;
        let p = compute_primed_frame(base, TASK_STACK_BYTES, 0x0800_0000, 0x0800_0010);

        // PSP must be 8-byte aligned (AAPCS / ARM ARM B1.5.7).
        assert_eq!(p.psp & 0x7, 0, "PSP must be 8-byte aligned");

        // PSP points just below the aligned top by exactly one basic frame.
        let raw_top = base + TASK_STACK_BYTES as u32;
        let aligned_top = raw_top & !0x7u32;
        assert_eq!(
            p.psp,
            aligned_top - BASIC_FRAME_BYTES as u32,
            "PSP must be one basic frame below the aligned stack top"
        );

        // The whole frame fits within the region.
        assert!(p.psp >= base, "frame must stay inside the stack region");
        assert!(
            p.psp + BASIC_FRAME_BYTES as u32 <= raw_top,
            "frame top must not exceed the region"
        );
    }

    #[test]
    fn unaligned_top_is_rounded_down() {
        // A region whose top is NOT 8-byte aligned must still yield an
        // 8-byte-aligned PSP (round the top DOWN).
        let base: u32 = 0x2000_0004; // base+size will be misaligned
        let size: usize = 100; // top = 0x2000_0068 → already &!7 = 0x68
        // Pick a size that makes the raw top deliberately misaligned:
        let size2: usize = 102; // top = 0x2000_006A, &!7 = 0x68
        let _ = size;
        let p = compute_primed_frame(base, size2, 0x0800_0000, 0x0800_0010);
        assert_eq!(p.psp & 0x7, 0, "PSP must be 8-byte aligned even for a misaligned top");
        let raw_top = base + size2 as u32; // 0x2000_006A
        let aligned_top = raw_top & !0x7u32; // 0x2000_0068
        assert_eq!(p.psp, aligned_top - BASIC_FRAME_BYTES as u32);
    }

    // ----- PCDN-003 envelope decision (pure) -----

    #[test]
    fn envelope_no_switch_when_current_unchanged() {
        // sem available / give with no waiter / take that succeeds: current
        // does not move → no PendSV, yield hint false.
        let o = envelope_outcome(2, 2);
        assert!(!o.pend_pendsv, "unchanged current must not pend PendSV");
    }

    #[test]
    fn envelope_switch_when_current_changes() {
        // A higher-prio task unblocked and was promoted to current: pend
        // PendSV, record outgoing/incoming TIDs.
        let o = envelope_outcome(0, 1);
        assert!(o.pend_pendsv, "changed current must pend PendSV");
        assert_eq!(o.outgoing, 0, "outgoing is the pre-macrostep current");
        assert_eq!(o.incoming, 1, "incoming is the post-macrostep current");
    }

    #[test]
    fn envelope_yield_hint_equals_pend_predicate() {
        // sem_give_from_isr returns `pend_pendsv` as the yield hint: the two
        // are the SAME predicate by construction (see EnvelopeOutcome doc).
        for prev in -1i32..4 {
            for new in -1i32..4 {
                let o = envelope_outcome(prev, new);
                assert_eq!(
                    o.pend_pendsv,
                    new != prev,
                    "pend/yield-hint must be exactly (current changed)"
                );
            }
        }
    }

    #[test]
    fn envelope_blocking_take_switches_away() {
        // A task that blocks on sem.take: macrostep blocks the caller and
        // promotes the next task; current 1 -> 0 (idle) say → switch away.
        let o = envelope_outcome(1, 0);
        assert!(o.pend_pendsv);
        assert_eq!(o.outgoing, 1);
        assert_eq!(o.incoming, 0);
    }

    #[test]
    fn entry_address_round_trips_via_real_fn() {
        // Take a real fn pointer; the stored PC must equal addr|1.
        let entry = fake_entry as extern "C" fn() -> !;
        let entry_addr = entry as *const () as usize as u32;
        let p = compute_primed_frame(0x2000_0000, TASK_STACK_BYTES, entry_addr, 0);
        assert_eq!(p.frame[6], entry_addr | 1);
    }
}
