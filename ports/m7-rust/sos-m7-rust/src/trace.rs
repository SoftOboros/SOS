//! On-device JSONL trace writer (PCDN-SOS-04-008 hand-rolled).
//!
//! ## Role
//!
//! Per SOS-04-CONCEPTS.md §6.2 (TraceRecord emission cadence) and
//! INV-S-PORT-9 (byte-equal trace), the firmware emits records in
//! SOS-02 §7 wire format byte-for-byte identical to `sos-sim`'s
//! `serde_json` output. PCDN-SOS-04-008 ratified a hand-rolled writer
//! over `serde-json-core`; PCDN-SOS-04-018 sibling-mandated that the
//! writer be covered by byte-exact unit tests in a host crate.
//!
//! The writer's pure logic lives in the sibling `sos-m7-rust-trace`
//! crate (no `cortex-m` / `cortex-m-rt` deps; host-testable). This
//! module is a thin adapter that constructs a [`TraceInput`] view of
//! the port-local [`Datamodel`] and delegates.
//!
//! ## Buffer sizing
//!
//! For the canonical dimensional defaults (`MAX_TASKS=8`, `MAX_PRIO=8`,
//! `MAX_SEMS=8`, `MAX_QUEUES=4`, `Q_DEPTH=16`), the boot-baseline record
//! is ~700 bytes. The 2 KiB scratch buffer in `transport.rs` is
//! sufficient for any seed-vector record (worst-case growth: every
//! sem/queue valid with a full waiter list bounded by `MAX_TASKS`, plus
//! a full queue buffer at `Q_DEPTH` 64-bit payloads).

use sos_m7_rust_trace::{
    write_record_from_input, Msg as TMsg, QueueView, ReturnCode as TRc, SemView, TaskState as TSt,
    TcbView, TraceInput,
};

use crate::kernel::{Datamodel, Msg, ReturnCode, TaskState, TaskId, MAX_PRIO, MAX_SEMS, MAX_QUEUES, MAX_TASKS};

/// Serialise one `TraceRecord` (boot baseline or post-macrostep) into
/// `buf` and return the number of bytes written. The bytes are exactly
/// the SOS-02 §7.1 JSONL record (terminating `\n` included).
///
/// `after_input_idx` is the `-1` boot baseline or the index of the
/// just-consumed event from the wrapped vector input.
///
/// Pure delegation to `sos_m7_rust_trace::write_record_from_input`
/// after building the borrowed view. The view borrows from `dm` for
/// the duration of this call; the writer never holds onto the borrow.
#[allow(dead_code)]
pub fn write_record(buf: &mut [u8], dm: &Datamodel, after_input_idx: i64) -> usize {
    // Build the TCB array. Each `TcbView` is `Copy` so we can stage it
    // in a fixed-size array on the stack without an allocator.
    let mut tcb_arr: [TcbView; MAX_TASKS] = [TcbView {
        id: 0,
        prio: 0,
        state: TSt::Dormant,
        deadline: 0,
        blk_obj: -1,
        msg: TMsg::Null,
    }; MAX_TASKS];
    for i in 0..MAX_TASKS {
        let t = &dm.tcb[i];
        tcb_arr[i] = TcbView {
            id: t.id,
            prio: t.prio,
            state: convert_state(t.state),
            deadline: t.deadline,
            blk_obj: t.blk_obj,
            msg: convert_msg(t.msg),
        };
    }

    // Ready queues: one `&[TaskId]` per priority band. `heapless::Vec`
    // derefs to `[T]` so `.as_slice()` is a borrowed view.
    let mut ready_arr: [&[TaskId]; MAX_PRIO] = [&[]; MAX_PRIO];
    for p in 0..MAX_PRIO {
        ready_arr[p] = dm.ready[p].as_slice();
    }

    // Sems / queues: borrow waiter / buffer slices from the datamodel.
    let mut sems_arr: [SemView<'_>; MAX_SEMS] = [SemView {
        valid: false,
        count: 0,
        max: 0,
        waiters: &[],
    }; MAX_SEMS];
    for i in 0..MAX_SEMS {
        let s = &dm.sems[i];
        sems_arr[i] = SemView {
            valid: s.valid,
            count: s.count,
            max: s.max,
            waiters: s.waiters.as_slice(),
        };
    }

    let mut queues_arr: [QueueView<'_>; MAX_QUEUES] = [QueueView {
        valid: false,
        cap: 0,
        count: 0,
        buf: &[],
        sendw: &[],
        recvw: &[],
    }; MAX_QUEUES];
    for i in 0..MAX_QUEUES {
        let q = &dm.queues[i];
        queues_arr[i] = QueueView {
            valid: q.valid,
            cap: q.cap,
            count: q.count,
            buf: q.buf.as_slice(),
            sendw: q.sendw.as_slice(),
            recvw: q.recvw.as_slice(),
        };
    }

    let input = TraceInput {
        current: dm.current,
        tick_count: dm.tick_count,
        rc: convert_rc(dm.rc),
        tcb: &tcb_arr,
        ready: &ready_arr,
        sems: &sems_arr,
        queues: &queues_arr,
        irq_nest: dm.irq_nest,
        sched_lock: dm.sched_lock,
        pend_ticks: dm.pend_ticks,
    };
    write_record_from_input(buf, &input, after_input_idx)
}

fn convert_state(s: TaskState) -> TSt {
    match s {
        TaskState::Dormant => TSt::Dormant,
        TaskState::Ready => TSt::Ready,
        TaskState::Running => TSt::Running,
        TaskState::Delay => TSt::Delay,
        TaskState::BlkSem => TSt::BlkSem,
        TaskState::BlkQs => TSt::BlkQs,
        TaskState::BlkQr => TSt::BlkQr,
        TaskState::Suspend => TSt::Suspend,
    }
}

fn convert_rc(rc: ReturnCode) -> TRc {
    match rc {
        ReturnCode::Ok => TRc::Ok,
        ReturnCode::Timeout => TRc::Timeout,
        ReturnCode::Full => TRc::Full,
        ReturnCode::Empty => TRc::Empty,
        ReturnCode::Inval => TRc::Inval,
    }
}

fn convert_msg(m: Msg) -> TMsg {
    match m {
        Msg::Null => TMsg::Null,
        Msg::Int(n) => TMsg::Int(n),
        Msg::ReturnCode(rc) => TMsg::ReturnCode(convert_rc(rc)),
    }
}
