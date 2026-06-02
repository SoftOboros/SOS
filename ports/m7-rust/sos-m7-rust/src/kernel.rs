//! Kernel state + transliterated chart bodies (skeleton).
//!
//! Per SOS-04-CONCEPTS.md §6.3 (static allocations) and §6.5–§6.7
//! (critical sections / SysTick / syscall wrappers). The on-device
//! `Datamodel` mirrors the field set of `sim/sos-sim/src/datamodel.rs`
//! so the trace serialisation lands byte-for-byte identical (INV-S-PORT-9).
//!
//! Skeleton commit: types + dimensional constants only. `init()` is
//! `unimplemented!()`; the implementation phase fills in pool zeroing,
//! idle promotion, and NVIC priority programming.

use core::cell::UnsafeCell;

// -----------------------------------------------------------------------
// Dimensional constants — match the chart's at-HEAD defaults and the
// PCDN-SOS-04-006 ratified stack sizes.
// -----------------------------------------------------------------------

/// `MAX_TASKS` (SOS-00 §7.1 vector config + chart `<data id="MAX_TASKS">`).
pub const MAX_TASKS: usize = 8;
/// `MAX_PRIO` — priority bands; 8 levels per chart default.
pub const MAX_PRIO: usize = 8;
/// `MAX_SEMS`.
pub const MAX_SEMS: usize = 8;
/// `MAX_QUEUES`.
pub const MAX_QUEUES: usize = 4;
/// `Q_DEPTH` — per-queue buffer ceiling.
pub const Q_DEPTH: usize = 16;

/// SysTick interrupt rate in Hz per SOS-00 §6.6 + PCDN-SOS-04-013. The
/// firmware locks SysTick to 1 kHz at boot (LOAD = 399_999 at 400 MHz
/// CM7 sysclk; see `disco_bsp::init_systick`). Exposed as a kernel-level
/// constant so the vector-header validation in `main.rs` has a canonical
/// reference (SOS-04 §15 Amendment 006).
pub const SOS_TICK_HZ: u32 = 1_000;

/// MSP backing-store size (PCDN-SOS-04-006). 4 KiB at the top of DTCM
/// via `_stack_start` in `memory.x`; the symbol is declared here for
/// the implementation phase to materialise an actual `.kernel_stack`
/// section.
pub const KERNEL_STACK_BYTES: usize = 4 * 1024;

/// Per-task PSP region size (PCDN-SOS-04-006). 2 KiB × MAX_TASKS = 16
/// KiB pool, sized comfortably for D1 AXI-SRAM.
pub const TASK_STACK_BYTES: usize = 2 * 1024;

// FAM-04-A registers that these become tunable in a future amendment.

// -----------------------------------------------------------------------
// Frozen enums — discriminants match SOS-00 §5.1 / §5.2 exactly so the
// trace bytes are identical to sos-sim's. INV-S-PORT-9.
// -----------------------------------------------------------------------

/// Task lifecycle state. Mirrors `sim::datamodel::TaskState`.
#[derive(Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum TaskState {
    /// `ST_DORMANT` — TCB slot unused.
    Dormant = 0,
    /// `ST_READY` — in a `ready[prio]` queue.
    Ready = 1,
    /// `ST_RUNNING` — `current == id`.
    Running = 2,
    /// `ST_DELAY` — time-blocked.
    Delay = 3,
    /// `ST_BLK_SEM` — on `sems[blk_obj].waiters`.
    BlkSem = 4,
    /// `ST_BLK_QS` — on `queues[blk_obj].sendw`.
    BlkQs = 5,
    /// `ST_BLK_QR` — on `queues[blk_obj].recvw`.
    BlkQr = 6,
    /// `ST_SUSPEND` — off all lists.
    Suspend = 7,
}

/// Syscall return code. Mirrors `sim::datamodel::ReturnCode`.
#[derive(Clone, Copy, PartialEq, Eq)]
#[repr(i8)]
pub enum ReturnCode {
    /// `RC_OK`.
    Ok = 0,
    /// `RC_TIMEOUT`.
    Timeout = -1,
    /// `RC_FULL`.
    Full = -2,
    /// `RC_EMPTY`.
    Empty = -3,
    /// `RC_INVAL`.
    Inval = -4,
}

/// Task identifier. Chart uses `-1` as the "none" sentinel; ports
/// realise as a signed type.
pub type TaskId = i16;

/// Polymorphic value carried in `tcb[i].msg`. Per SOS-00 §5.6 and
/// SOS-02 §6.3.1; wire encoding per SOS-02 §7.2 lives in `trace.rs`.
/// Mirrors `sim::datamodel::Msg`.
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Msg {
    /// No staged message. JSON `null`.
    Null,
    /// Integer payload. JSON number.
    Int(i64),
    /// Final return code deposited at unblock. JSON `{"rc": <int>}`.
    ReturnCode(ReturnCode),
}

impl Default for Msg {
    fn default() -> Self {
        Msg::Null
    }
}

// -----------------------------------------------------------------------
// FAM-04-D (SOS-04 §15 Amendment 002): PSP backing-store side-table.
//
// `Tcb` deliberately does NOT carry the saved-frame backing store —
// putting it inside `Tcb` would drift the on-device trace shape from
// `sos-sim`'s and break INV-S-PORT-9 (byte-equal trace). The three
// arrays below are the parallel side-table:
//
//   * `TASK_STACKS`       — the per-task PSP stack region (live frame
//                           while the task is RUNNING).
//   * `TASK_PSPS`         — the saved PSP value (top of saved hardware
//                           frame) for each task when it is NOT running.
//   * `TASK_SAVED_FRAMES` — the OS-saved callee-registers (R4-R11 and,
//                           when applicable, S16-S31) for each task
//                           when it is NOT running. Hardware-saved
//                           R0-R3 / R12 / LR / PC / xPSR (+ S0-S15 +
//                           FPSCR + padding for the extended frame) live
//                           on the PSP at `TASK_PSPS[id]`, not here.
//
// None of these are observable in the trace (per SOS-00 §7.2); they
// are pure port-side state.
// -----------------------------------------------------------------------

/// Saved-frame backing store for one task. Sized for the FPU-extended
/// frame (worst case); `had_fp_frame` discriminates whether the optional
/// S16-S31 slice carries meaningful data.
///
/// Per SOS-00 §6.4 + SOS-04 §6.4 + INV-S-PORT-3: PendSV inspects
/// `EXC_RETURN[4]` on entry, stores the OS-saved callee-registers here,
/// and uses `had_fp_frame` on restore to decide whether to reload
/// S16-S31. The discriminator lives adjacent to the registers so PendSV
/// can flip it without a separate memory access.
#[repr(C)]
pub struct SavedFrame {
    /// R4-R11 callee-saved registers.
    pub regs: [u32; 8],
    /// S16-S31 callee-saved FPU registers. Only meaningful when
    /// `had_fp_frame == true`; otherwise zeroed and ignored on restore.
    pub fp_regs: [u32; 16],
    /// Discriminator: was the most-recent save an extended FPU frame?
    /// Mirrors `EXC_RETURN[4] == 0` at the moment of save (PendSV writes
    /// `true` when the outgoing frame is the extended 26-word form).
    pub had_fp_frame: bool,
}

impl SavedFrame {
    /// Boot-baseline value: all registers zero, no FPU frame recorded.
    /// `const` so the static initializers below can use it directly.
    pub const fn new() -> Self {
        Self {
            regs: [0u32; 8],
            fp_regs: [0u32; 16],
            had_fp_frame: false,
        }
    }
}

// PendSV asm body in `handlers.rs` hardcodes the SavedFrame slot stride as
// `movs r2, #100` and computes per-slot addresses as `base + tid * 100`. Any
// future field added to SavedFrame that shifts its size silently breaks the
// asm. This static assert catches the divergence at compile time.
//
// If `SavedFrame` ever genuinely needs to grow, update BOTH this assert AND
// the `#100` literal in `handlers.rs::PendSV()` (and the `.byte 96` offset
// for the had_fp_frame field if its position shifts).
const _: () = assert!(
    core::mem::size_of::<SavedFrame>() == 100,
    "SavedFrame size drifted from 100; PendSV asm needs update — see handlers.rs"
);

/// One task stack region per TCB, allocated at link time in D1 AXI-SRAM
/// (`.task_stacks` section per `memory.x`). PCDN-SOS-04-006 ratifies
/// `TASK_STACK_BYTES = 2 KiB` per slot.
///
/// `StackRegion` is `repr(C, align(8))` so the top of each stack is
/// 8-byte aligned per ARMv7-M AAPCS / ARM ARM B1.5.7 (stack alignment
/// at exception entry requires 8-byte alignment).
#[repr(C, align(8))]
pub struct StackRegion(pub [u8; TASK_STACK_BYTES]);

/// Per-task PSP stack regions. The live exception frame for the RUNNING
/// task lives on this stack; the saved exception frame for a non-running
/// task lives at `TASK_PSPS[id]..TASK_PSPS[id]+frame_size` within this
/// region.
///
/// Allocated in `.task_stacks` (D1 AXI-SRAM) per `memory.x`. While
/// `memory.x` does not yet carve out a dedicated section, cortex-m-rt's
/// default layout places `static mut` arrays into `.bss` (DTCM); the
/// stacks fit at 2 KiB × 8 = 16 KiB. A dedicated section can be added
/// later without touching this declaration.
pub static mut TASK_STACKS: [StackRegion; MAX_TASKS] =
    [const { StackRegion([0u8; TASK_STACK_BYTES]) }; MAX_TASKS];

/// PSP value (top of saved hardware frame) for each task when NOT
/// running. Indexed by `TaskId`. While a task is RUNNING, its entry is
/// stale; PendSV overwrites it on the next context switch out.
///
/// On entry to the first PendSV for a given task slot (i.e. an
/// activation transitioning the task from DORMANT → RUNNING via the
/// first context switch), the entry is expected to be pre-populated by
/// `kernel::init()` with a synthetic exception frame at the top of the
/// task's PSP stack region. Tasks that are DORMANT for the entire boot
/// trace (the v1 reference doesn't exercise `task.create` post-boot for
/// every slot) have `TASK_PSPS[id] = 0`; PendSV never targets them.
pub static mut TASK_PSPS: [u32; MAX_TASKS] = [0u32; MAX_TASKS];

/// Saved-frame side table. Indexed by `TaskId`. Populated by PendSV on
/// context-switch-out; consumed by PendSV on context-switch-in.
///
/// `static mut` rather than `UnsafeCell` because the access pattern is
/// the PendSV inline-asm body, which addresses these arrays by absolute
/// linker symbol — interior-mutability primitives add no soundness over
/// the `unsafe` block that already brackets every PendSV write.
pub static mut TASK_SAVED_FRAMES: [SavedFrame; MAX_TASKS] =
    [const { SavedFrame::new() }; MAX_TASKS];

/// Outgoing TID at the moment PendSV is pended. The `DirectCallBasepri`
/// syscall path stashes the old `current` here BEFORE updating
/// `Datamodel.current` to the new id, then pends PendSV. PendSV reads
/// `OUTGOING_TID` to know which TCB slot's saved-frame to write.
///
/// `i32` rather than `TaskId` (`i16`) so the PendSV asm can load a full
/// word without sign-extension fuss. `-1` is the boot-path sentinel
/// meaning "no outgoing task" — PendSV skips the save side when it
/// reads this value.
#[no_mangle]
pub static mut OUTGOING_TID: i32 = -1;

/// Incoming TID at the moment PendSV runs. Set by the syscall path
/// after the scheduler picks the next task; PendSV reads this to know
/// which TCB slot to restore from.
///
/// `i32` for the same reason as `OUTGOING_TID`. Initialised to `0` so
/// PendSV's first-ever invocation targets the idle task (TCB[0]).
#[no_mangle]
pub static mut CURRENT_TID: i32 = 0;

// -----------------------------------------------------------------------
// Datamodel records — field set mirrors sim/sos-sim/src/datamodel.rs.
// -----------------------------------------------------------------------

/// One Task Control Block. Mirrors `sim::datamodel::Tcb`. Skeleton
/// commit retains the kernel-side fields only; the saved-frame backing
/// store + PSP pointer the §6.4 PendSV body needs lands in the
/// implementation phase.
#[derive(Clone, Copy)]
pub struct Tcb {
    pub id: TaskId,
    pub prio: u8,
    pub state: TaskState,
    pub deadline: i64,
    pub blk_obj: i16,
    pub msg: Msg,
}

/// One semaphore descriptor. Mirrors `sim::datamodel::Sem`.
#[derive(Clone)]
pub struct Sem {
    pub valid: bool,
    pub count: u32,
    pub max: u32,
    /// Per SOS-00 INV-S8: priority-descending, FIFO-within-priority.
    pub waiters: heapless::Vec<TaskId, MAX_TASKS>,
}

/// One queue descriptor. Mirrors `sim::datamodel::Queue`.
#[derive(Clone)]
pub struct Queue {
    pub valid: bool,
    pub buf: heapless::Vec<i64, Q_DEPTH>,
    pub cap: u32,
    pub count: u32,
    pub sendw: heapless::Vec<TaskId, MAX_TASKS>,
    pub recvw: heapless::Vec<TaskId, MAX_TASKS>,
}

/// The full mutable kernel state. One per port binary. Field set
/// mirrors `sim::datamodel::Datamodel`; field order matches SOS-02 §7.1
/// trace serialisation order so the hand-rolled writer in
/// `trace::write_record` lands the bytes the harness expects.
#[derive(Clone)]
pub struct Datamodel {
    pub max_tasks: usize,
    pub max_prio: usize,
    pub max_sems: usize,
    pub max_queues: usize,
    pub q_depth: usize,
    pub tcb: [Tcb; MAX_TASKS],
    /// `ready[p]` — per-priority FIFO of READY task ids.
    pub ready: [heapless::Vec<TaskId, MAX_TASKS>; MAX_PRIO],
    /// Running task id (`-1` when no task is running).
    pub current: TaskId,
    pub tick_count: i64,
    pub rc: ReturnCode,
    pub irq_nest: u32,
    pub sched_lock: u32,
    pub pend_ticks: u32,
    pub sems: [Sem; MAX_SEMS],
    pub queues: [Queue; MAX_QUEUES],
    /// Internal flag raised by state-mutating transitions to request a
    /// `sched.run` microstep.
    pub resched: bool,
}

// -----------------------------------------------------------------------
// Static-mutable kernel state (PCDN-SOS-04-011 → UnsafeCell pattern).
//
// `KernelStateWrapper` is a thin newtype around `UnsafeCell<Datamodel>`
// that carries an explicit `unsafe impl Sync` — required because the
// `static` storage class is `Sync`-constrained, and `UnsafeCell` is not
// `Sync` by default. The trust marker is the BASEPRI-raise critical
// section in `critical::crit_enter` (lands in the implementation phase
// per §6.7); every mutation of `KERNEL_STATE` happens under it.
// -----------------------------------------------------------------------

#[doc(hidden)]
pub struct KernelStateWrapper(pub(crate) UnsafeCell<Option<Datamodel>>);

// Safety: All access to the inner `Datamodel` is gated by the BASEPRI
// raise/lower wrappers per SOS-04 §6.7 and SOS-00 §6.5. The wrapper is
// `Sync` in the same sense `cortex_m::interrupt::Mutex` is.
unsafe impl Sync for KernelStateWrapper {}

/// The single kernel state cell. `None` until `init()` populates it.
///
/// The implementation phase MAY replace `Option<Datamodel>` with a
/// `MaybeUninit<Datamodel>` + a `BOOT_DONE` sentinel if benchmarking
/// shows the option discriminant cost matters; v1 keeps `Option` for
/// the trust-marker clarity PCDN-SOS-04-011 calls out.
pub static KERNEL_STATE: KernelStateWrapper = KernelStateWrapper(UnsafeCell::new(None));

// -----------------------------------------------------------------------
// Initialisation — skeleton.
// -----------------------------------------------------------------------

/// Initialise the kernel state per SOS-04 §6.8 step 5: zero
/// `TCB_POOL` / `READY_POOL` / `SEM_POOL` / `QUEUE_POOL`, materialise
/// the idle task (TCB[0]) and enqueue it on `READY_POOL[0]`, set the
/// scalar `Datamodel` fields to their boot-baseline values.
///
/// Phase 2 implementation: NVIC priority programming for PendSV /
/// SysTick is handled in `disco_bsp::init_nvic_priorities()`; the
/// `*_from_isr` priority for USART1 is programmed in
/// `transport::start()`. This function focuses on the `Datamodel` pools.
///
/// At end of `init()`, `current = -1` (no task running yet); idle is
/// READY at priority 0. The macrostep loop / first context switch lands
/// in phase 3 — phase 2 leaves `main()` falling into `wfi`.
pub fn init() {
    // SAFETY: `KERNEL_STATE` is the single `UnsafeCell<Option<Datamodel>>`
    // declared above. `init()` is the single writer at boot before any
    // interrupt that touches the kernel state is enabled (SysTick is
    // configured in `disco_bsp::init()` but the kernel-aware path that
    // reads `KERNEL_STATE` does not run until phase 3 lands the
    // SysTick body). No concurrent access exists at this point.
    let cell: &mut Option<Datamodel> = unsafe { &mut *KERNEL_STATE.0.get() };

    // Build the boot-baseline Datamodel in place.
    let mut dm = Datamodel {
        max_tasks: MAX_TASKS,
        max_prio: MAX_PRIO,
        max_sems: MAX_SEMS,
        max_queues: MAX_QUEUES,
        q_depth: Q_DEPTH,
        tcb: [Tcb {
            id: 0,
            prio: 0,
            state: TaskState::Dormant,
            deadline: 0,
            blk_obj: -1,
            msg: Msg::Null,
        }; MAX_TASKS],
        ready: [const { heapless::Vec::new() }; MAX_PRIO],
        // Amendment 010 (re-applied 2026-05-21 after EOQ-004 PendSV fix):
        // idle promoted to RUNNING at boot per chart `<boot>` `pick_next()`
        // semantics; matches sim's `Datamodel::new`. Earlier HardFault was
        // resolved by removing unconditional SysTick→PendSV pend in
        // handlers.rs.
        current: 0,
        tick_count: 0,
        rc: ReturnCode::Ok,
        irq_nest: 0,
        sched_lock: 0,
        pend_ticks: 0,
        sems: core::array::from_fn(|_| Sem {
            valid: false,
            count: 0,
            max: 0,
            waiters: heapless::Vec::new(),
        }),
        queues: core::array::from_fn(|_| Queue {
            valid: false,
            buf: heapless::Vec::new(),
            cap: 0,
            count: 0,
            sendw: heapless::Vec::new(),
            recvw: heapless::Vec::new(),
        }),
        resched: false,
    };

    // Assign each TCB its slot id; READY_POOL is already cleared by the
    // `heapless::Vec::new()` initializer above.
    for i in 0..MAX_TASKS {
        dm.tcb[i].id = i as TaskId;
    }

    // Idle (TCB[0]) → Running at boot, current=0, ready[] empty.
    // Amendment 010 re-applied per EOQ-004 PendSV fix.
    dm.tcb[0].state = TaskState::Running;
    dm.tcb[0].prio = 0;

    *cell = Some(dm);

    // -------------------------------------------------------------------
    // FAM-04-D side-table initialisation.
    //
    // For every TCB slot, pre-stage `TASK_PSPS[i]` to point at the top
    // of `TASK_STACKS[i]` minus one standard hardware frame (8 words =
    // 32 bytes). This guarantees PendSV's restore path always reads
    // valid memory even if the first context switch targets a task that
    // has not yet had a frame synthesised by `task.create`. Tasks that
    // remain DORMANT for the entire trace are never targeted by PendSV
    // (the scheduler in `pick_next` ignores DORMANT slots), so the
    // pre-staged frame is benign.
    //
    // `TASK_SAVED_FRAMES[i]` is zeroed by the static initialiser
    // (`SavedFrame::new()`); no per-slot init is required here.
    //
    // SAFETY: `init()` is the single writer at boot before any
    // exception that touches the side-table is enabled.
    // -------------------------------------------------------------------
    for i in 0..MAX_TASKS {
        // SAFETY: addressing into the static stack pool via raw pointers
        // is sound at boot — no concurrent access exists, and the
        // resulting address lies within the slot's allocated region.
        // `addr_of!` avoids creating a shared reference to the `static
        // mut TASK_STACKS` (the Rust 2024 static_mut_refs lint).
        let stack_top = unsafe {
            let base = core::ptr::addr_of!(TASK_STACKS) as *const StackRegion;
            let slot = base.add(i) as *const u8;
            slot.add(TASK_STACK_BYTES) as u32
        };
        // Reserve 32 bytes (one standard hardware frame: R0-R3, R12,
        // LR, PC, xPSR — 8 words) at the top of the stack. PendSV's
        // restore-side `ldmia` will read from here; a task that is
        // never activated leaves these eight words zero (harmless —
        // a real activation overwrites them via `task.create`).
        let psp = stack_top.saturating_sub(32);
        // SAFETY: `TASK_PSPS` is the FAM-04-D side-table; `init()` is
        // the sole writer at boot.
        unsafe {
            TASK_PSPS[i] = psp;
        }
    }
}
