//! Embeddable host-app library API — construction + tick subset.
//!
//! Per `docs/concepts/SOS-04-B-EMBEDDABLE-KERNEL.md`:
//!   * §5.2 PCDN-SOS-04-B-002 (ratified 2026-06-03) — task entry ABI is
//!     `extern "C" fn() -> !`; at create time the kernel primes a basic
//!     Cortex-M exception-return frame at the top of the task's PSP region
//!     (`xPSR = 0x0100_0000`, `PC = entry`, `LR = task_exit_trap`,
//!     `R0..R3/R12 = 0`, 8-byte aligned) and sets `TASK_PSPS[id]`.
//!   * §5.5 — the frozen `no_std` library API. **This module (wave 2)
//!     implements the CONSTRUCTION + TICK subset only:** [`create_sem`],
//!     [`create_task`], [`start_scheduler`], [`on_sys_tick`].
//!     The task-context / ISR-context syscall front-ends
//!     (`sem_take`, `task_delay`, `sem_give_from_isr`) are PCDN-003 and
//!     land in wave 3 — they are **deliberately absent here**.
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

        if new_current != prev_current {
            // Record the switch endpoints for PendSV and request it. The
            // outgoing task is the one that was running; PendSV saves its
            // live frame, restores the incoming. -1 ↔ valid transitions are
            // handled by PendSV's OUTGOING_TID sentinel check.
            kernel::OUTGOING_TID = prev_current;
            kernel::CURRENT_TID = new_current;
            cortex_m::peripheral::SCB::set_pendsv();
        }
    }
}

// ---------------------------------------------------------------------------
// Host unit tests — the PURE frame-layout math (PCDN-002).
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

    #[test]
    fn entry_address_round_trips_via_real_fn() {
        // Take a real fn pointer; the stored PC must equal addr|1.
        let entry = fake_entry as extern "C" fn() -> !;
        let entry_addr = entry as *const () as usize as u32;
        let p = compute_primed_frame(0x2000_0000, TASK_STACK_BYTES, entry_addr, 0);
        assert_eq!(p.frame[6], entry_addr | 1);
    }
}
