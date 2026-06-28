//! Hand-rolled JSONL trace writer for the SOS-04 M7 Rust port (PCDN-SOS-04-008).
//!
//! ## What this crate is
//!
//! SOS-02 §7 fixes the on-wire trace format byte-for-byte. The firmware
//! must emit records that are byte-identical to what `sos-sim` produces
//! via `serde_json::to_writer` on its `TraceRecord` struct (INV-S-PORT-9).
//! PCDN-SOS-04-008 ratified a hand-rolled writer over `serde-json-core`
//! to make the byte-stability property enforceable at the writer level
//! rather than at the mercy of a derive-macro's version drift. PCDN-SOS-04-018
//! sibling-mandated that the writer be covered by a host-side test crate
//! (`sos-m7-rust-tests`) with byte-exact unit tests.
//!
//! This crate is the result of those two PCDNs: a small, dependency-free,
//! `no_std` library that emits one [SOS-02 §7] `TraceRecord` per call into
//! a caller-provided byte buffer.
//!
//! ## Architecture split
//!
//! The firmware crate (`sos-m7-rust`) is `#![no_std]` *and* depends on
//! `cortex-m` / `cortex-m-rt`; the latter use `#[entry]` / `#[exception]`
//! attribute macros that fail to compile when the host test crate tries
//! to import them on a non-`thumb` target. To let the writer be tested
//! on the host without dragging in the embedded panic / runtime crates,
//! the writer's logic lives here (no `cortex-m` dep, no `cortex-m-rt`
//! dep, no `panic_halt` dep) and the firmware crate's `trace.rs` is a
//! thin adapter that constructs a [`TraceInput`] from its own
//! `kernel::Datamodel` and delegates to [`write_record_from_input`].
//!
//! The host test crate (`sos-m7-rust-tests`) depends on this crate
//! directly, builds [`TraceInput`] values to match every interesting
//! `Datamodel` state, and asserts byte-for-byte equality against
//! `serde_json::to_string(&sos_sim::TraceRecord{...})`.
//!
//! ## Buffer sizing guideline
//!
//! For the canonical SOS-04 dimensional defaults (`MAX_TASKS=8`,
//! `MAX_PRIO=8`, `MAX_SEMS=8`, `MAX_QUEUES=4`, `Q_DEPTH=16`), the
//! boot-baseline record is ~700 bytes. A 2 KiB scratch buffer in
//! `transport.rs` is sufficient for any seed-vector record (worst-case
//! growth: every sem/queue valid with a full waiter list — bounded by
//! `MAX_TASKS` task ids in each list — and a full queue buffer at
//! `Q_DEPTH` 64-bit payloads).
//!
//! ## Output discipline
//!
//! Per SOS-02 §7 the writer emits:
//! - No whitespace between tokens.
//! - Field order matches §7.1 verbatim.
//! - `null` / `true` / `false` literals are lower-case.
//! - Numbers are `core::fmt::Display`-equivalent (decimal integers, no
//!   trailing `.0`, no leading `+`, no exponent).
//! - `Msg::Null` → `null`, `Msg::Int(n)` → bare integer, `Msg::ReturnCode(rc)`
//!   → `{"rc":<i8>}` per SOS-00 §5.6 Amendment 004 on-wire form.
//! - Each `Sem` / `Queue` slot encodes short-form `{"valid":false}` when
//!   invalid and long-form `{"valid":true,...}` when valid (§7.2).
//! - A trailing `\n` framing byte terminates the record (§6.5 JSONL
//!   discipline) and is included in the returned byte count.

#![no_std]
#![warn(missing_docs)]

type WriteResult = Result<(), ()>;

// ============================================================================
// Trace-input types — pure-data mirror of the trace-relevant `Datamodel`
// subset. The firmware crate converts its `kernel::Datamodel` into one
// of these; the host test crate constructs them directly.
// ============================================================================

/// On-wire discriminants for `TaskState` per SOS-00 §5.1. Re-declared
/// here so the trace crate is independent of `sos-m7-rust::kernel`.
/// Discriminants MUST match `sos_sim::datamodel::TaskState` exactly
/// (INV-S-PORT-9).
#[derive(Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum TaskState {
    /// `ST_DORMANT`.
    Dormant = 0,
    /// `ST_READY`.
    Ready = 1,
    /// `ST_RUNNING`.
    Running = 2,
    /// `ST_DELAY`.
    Delay = 3,
    /// `ST_BLK_SEM`.
    BlkSem = 4,
    /// `ST_BLK_QS`.
    BlkQs = 5,
    /// `ST_BLK_QR`.
    BlkQr = 6,
    /// `ST_SUSPEND`.
    Suspend = 7,
}

/// On-wire discriminants for `ReturnCode` per SOS-00 §5.2. Mirrors
/// `sos_sim::datamodel::ReturnCode` byte-for-byte.
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

/// `TaskId` — the chart uses `-1` as the "none" sentinel; SOS-02 §7.2
/// widens to `i32` on the wire. The in-memory type is `i16`.
pub type TaskId = i16;

/// On-wire form of `tcb[i].msg` per SOS-00 §5.6 Amendment 004.
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Msg {
    /// `null` on the wire.
    Null,
    /// Bare signed integer on the wire.
    Int(i64),
    /// `{"rc":<i8>}` object on the wire.
    ReturnCode(ReturnCode),
}

/// One TCB snapshot — the trace-relevant subset of `kernel::Tcb`.
#[derive(Clone, Copy)]
pub struct TcbView {
    /// `tcb[i].id` (widened to `i32` on the wire).
    pub id: TaskId,
    /// `tcb[i].prio` (`u8`, unsigned on the wire).
    pub prio: u8,
    /// `tcb[i].state`.
    pub state: TaskState,
    /// `tcb[i].deadline` (signed integer on the wire).
    pub deadline: i64,
    /// `tcb[i].blk_obj` (widened to `i32` on the wire).
    pub blk_obj: i16,
    /// `tcb[i].msg`.
    pub msg: Msg,
}

/// One semaphore snapshot — `valid==false` collapses to `{"valid":false}`
/// short form on the wire (`waiters` ignored when invalid).
#[derive(Clone, Copy)]
pub struct SemView<'a> {
    /// `sems[s].valid`.
    pub valid: bool,
    /// `sems[s].count`.
    pub count: u32,
    /// `sems[s].max`.
    pub max: u32,
    /// `sems[s].waiters` — task ids in FIFO order. Borrowed slice so the
    /// firmware-side `heapless::Vec` and the host-side `Vec` both fit.
    pub waiters: &'a [TaskId],
}

/// One queue snapshot — symmetric to [`SemView`]; `valid==false`
/// collapses to short form.
#[derive(Clone, Copy)]
pub struct QueueView<'a> {
    /// `queues[q].valid`.
    pub valid: bool,
    /// `queues[q].cap` (capacity ceiling).
    pub cap: u32,
    /// `queues[q].count` (current depth).
    pub count: u32,
    /// `queues[q].buf` — staged payloads in FIFO order.
    pub buf: &'a [i64],
    /// `queues[q].sendw` — blocked senders.
    pub sendw: &'a [TaskId],
    /// `queues[q].recvw` — blocked receivers.
    pub recvw: &'a [TaskId],
}

/// One ready-queue view — task ids at one priority band, FIFO order.
pub type ReadyView<'a> = &'a [TaskId];

/// The trace-relevant subset of `kernel::Datamodel`. All slices have the
/// caller's lifetime; the writer never holds onto them past the
/// [`write_record_from_input`] call.
///
/// Field order mirrors SOS-02 §7.1 for documentary clarity, but the
/// writer does not rely on it — the JSON emission order is the writer's
/// responsibility.
#[derive(Clone, Copy)]
pub struct TraceInput<'a> {
    /// `dm.current` (`-1` when no task runs).
    pub current: TaskId,
    /// `dm.tick_count`.
    pub tick_count: i64,
    /// `dm.rc`.
    pub rc: ReturnCode,
    /// One [`TcbView`] per TCB slot.
    pub tcb: &'a [TcbView],
    /// One ready-queue slice per priority band.
    pub ready: &'a [ReadyView<'a>],
    /// One [`SemView`] per semaphore slot.
    pub sems: &'a [SemView<'a>],
    /// One [`QueueView`] per queue slot.
    pub queues: &'a [QueueView<'a>],
    /// `dm.irq_nest`.
    pub irq_nest: u32,
    /// `dm.sched_lock`.
    pub sched_lock: u32,
    /// `dm.pend_ticks`.
    pub pend_ticks: u32,
}

// ============================================================================
// Writer
// ============================================================================

/// Internal write buffer wrapper. Tracks the write cursor; returns
/// an error once the caller-supplied buffer is full so the rest of
/// the writer short-circuits via `?` propagation.
struct Writer<'a> {
    buf: &'a mut [u8],
    pos: usize,
    /// `true` once an attempted write would have overflowed `buf`. The
    /// writer keeps `pos` clamped to `buf.len()` so the returned count
    /// is the buffer's capacity (i.e. the truncation point), per the
    /// PCDN-SOS-04-008 dispatch contract.
    overflowed: bool,
}

impl<'a> Writer<'a> {
    fn new(buf: &'a mut [u8]) -> Self {
        Writer {
            buf,
            pos: 0,
            overflowed: false,
        }
    }

    fn push_bytes(&mut self, src: &[u8]) -> WriteResult {
        let remaining = self.buf.len() - self.pos;
        if src.len() > remaining {
            // Best-effort: copy what we can so the returned `pos` is
            // exactly the buffer length on overflow.
            self.buf[self.pos..].copy_from_slice(&src[..remaining]);
            self.pos = self.buf.len();
            self.overflowed = true;
            return Err(());
        }
        self.buf[self.pos..self.pos + src.len()].copy_from_slice(src);
        self.pos += src.len();
        Ok(())
    }

    fn write_str(&mut self, s: &str) -> WriteResult {
        self.push_bytes(s.as_bytes())
    }

    fn write_u64(&mut self, mut n: u64) -> WriteResult {
        let mut digits = [0u8; 20];
        let mut pos = digits.len();

        if n == 0 {
            return self.push_bytes(b"0");
        }

        while n > 0 {
            pos -= 1;
            digits[pos] = b'0' + (n % 10) as u8;
            n /= 10;
        }

        self.push_bytes(&digits[pos..])
    }

    fn write_i64(&mut self, n: i64) -> WriteResult {
        if n < 0 {
            self.push_bytes(b"-")?;
            let magnitude = if n == i64::MIN {
                1u64 << 63
            } else {
                (-n) as u64
            };
            self.write_u64(magnitude)
        } else {
            self.write_u64(n as u64)
        }
    }
}

/// Emit one `TraceRecord` (per SOS-02 §7.1) into `buf` from a borrowed
/// [`TraceInput`] view of the datamodel. Returns the number of bytes
/// written including the trailing `\n` framing byte.
///
/// If `buf` is too small to hold the record, the writer truncates at
/// the buffer length and returns `buf.len()` — no panic, no UB; the
/// caller is responsible for sizing the scratch buffer (see the module
/// docstring's buffer-sizing guideline). The trailing `\n` is part of
/// the record body in the byte count; an overrun before the `\n` means
/// the record on the wire is malformed and the caller MUST detect this
/// via `return_value < expected_minimum` rather than parsing the
/// truncated bytes.
pub fn write_record_from_input(
    buf: &mut [u8],
    input: &TraceInput<'_>,
    after_input_idx: i64,
) -> usize {
    let mut w = Writer::new(buf);
    // SOS-02 §7.1 field order: after_input_idx, current, tick_count,
    // rc, tcb, ready, sems, queues, irq_nest, sched_lock, pend_ticks.
    // Errors are swallowed — on overflow the writer's `pos` is clamped
    // and the function returns the truncation point.
    let _ = emit_record(&mut w, input, after_input_idx);
    // JSONL framing — exactly one LF at the end of each record. We try
    // to write it even after a content-overrun so callers that compare
    // partial records still see the framing byte if there's room; if
    // the buffer is entirely full, this push_bytes returns Err and pos
    // stays at the clamped buffer length.
    let _ = w.push_bytes(b"\n");
    w.pos
}

fn emit_record(w: &mut Writer<'_>, input: &TraceInput<'_>, after_input_idx: i64) -> WriteResult {
    w.write_str("{\"after_input_idx\":")?;
    w.write_i64(after_input_idx)?;

    w.write_str(",\"current\":")?;
    // SOS-02 §7.2 wire-widening: `TaskId` (i16) → i32 on the wire.
    // `core::fmt::Display` on i32 / i16 emits the same digits for any
    // i16 value, so the cast is byte-equivalent.
    w.write_i64(input.current as i64)?;

    w.write_str(",\"tick_count\":")?;
    w.write_i64(input.tick_count)?;

    w.write_str(",\"rc\":")?;
    w.write_i64(input.rc as i8 as i64)?;

    w.write_str(",\"tcb\":[")?;
    for (i, tcb) in input.tcb.iter().enumerate() {
        if i > 0 {
            w.write_str(",")?;
        }
        emit_tcb(w, tcb)?;
    }
    w.write_str("]")?;

    w.write_str(",\"ready\":[")?;
    for (p, ready_p) in input.ready.iter().enumerate() {
        if p > 0 {
            w.write_str(",")?;
        }
        emit_id_array(w, ready_p)?;
    }
    w.write_str("]")?;

    w.write_str(",\"sems\":[")?;
    for (i, sem) in input.sems.iter().enumerate() {
        if i > 0 {
            w.write_str(",")?;
        }
        emit_sem(w, sem)?;
    }
    w.write_str("]")?;

    w.write_str(",\"queues\":[")?;
    for (i, q) in input.queues.iter().enumerate() {
        if i > 0 {
            w.write_str(",")?;
        }
        emit_queue(w, q)?;
    }
    w.write_str("]")?;

    w.write_str(",\"irq_nest\":")?;
    w.write_u64(input.irq_nest as u64)?;

    w.write_str(",\"sched_lock\":")?;
    w.write_u64(input.sched_lock as u64)?;

    w.write_str(",\"pend_ticks\":")?;
    w.write_u64(input.pend_ticks as u64)?;

    w.write_str("}")?;
    Ok(())
}

fn emit_tcb(w: &mut Writer<'_>, tcb: &TcbView) -> WriteResult {
    // Field order: id, prio, state, deadline, blk_obj, msg. Mirrors
    // SOS-02 §7.2 + the `sos_sim::TcbSnapshot` struct declaration order.
    w.write_str("{\"id\":")?;
    w.write_i64(tcb.id as i64)?;

    w.write_str(",\"prio\":")?;
    w.write_u64(tcb.prio as u64)?;

    w.write_str(",\"state\":")?;
    w.write_u64(tcb.state as u8 as u64)?;

    w.write_str(",\"deadline\":")?;
    w.write_i64(tcb.deadline)?;

    w.write_str(",\"blk_obj\":")?;
    w.write_i64(tcb.blk_obj as i64)?;

    w.write_str(",\"msg\":")?;
    emit_msg(w, &tcb.msg)?;

    w.write_str("}")?;
    Ok(())
}

fn emit_msg(w: &mut Writer<'_>, msg: &Msg) -> WriteResult {
    match msg {
        Msg::Null => w.write_str("null"),
        Msg::Int(n) => w.write_i64(*n),
        Msg::ReturnCode(rc) => {
            w.write_str("{\"rc\":")?;
            w.write_i64(*rc as i8 as i64)?;
            w.write_str("}")?;
            Ok(())
        }
    }
}

fn emit_id_array(w: &mut Writer<'_>, ids: &[TaskId]) -> WriteResult {
    w.write_str("[")?;
    for (i, id) in ids.iter().enumerate() {
        if i > 0 {
            w.write_str(",")?;
        }
        // SOS-02 §7.2: each entry widens to i32 on the wire.
        w.write_i64(*id as i64)?;
    }
    w.write_str("]")?;
    Ok(())
}

fn emit_i64_array(w: &mut Writer<'_>, vals: &[i64]) -> WriteResult {
    w.write_str("[")?;
    for (i, v) in vals.iter().enumerate() {
        if i > 0 {
            w.write_str(",")?;
        }
        w.write_i64(*v)?;
    }
    w.write_str("]")?;
    Ok(())
}

fn emit_sem(w: &mut Writer<'_>, sem: &SemView<'_>) -> WriteResult {
    if !sem.valid {
        // Short form per SOS-02 §7.2 + SOS-03 PCDN-007.
        return w.write_str("{\"valid\":false}");
    }
    // Long form: valid, count, max, waiters. Matches the
    // `sos_sim::SemSnapshot::Valid` struct's field declaration order
    // (and therefore `serde_json`'s emission order).
    w.write_str("{\"valid\":true,\"count\":")?;
    w.write_u64(sem.count as u64)?;
    w.write_str(",\"max\":")?;
    w.write_u64(sem.max as u64)?;
    w.write_str(",\"waiters\":")?;
    emit_id_array(w, sem.waiters)?;
    w.write_str("}")?;
    Ok(())
}

fn emit_queue(w: &mut Writer<'_>, q: &QueueView<'_>) -> WriteResult {
    if !q.valid {
        return w.write_str("{\"valid\":false}");
    }
    // Long form: valid, cap, count, buf, sendw, recvw. Matches the
    // `sos_sim::QueueSnapshot::Valid` field declaration order.
    w.write_str("{\"valid\":true,\"cap\":")?;
    w.write_u64(q.cap as u64)?;
    w.write_str(",\"count\":")?;
    w.write_u64(q.count as u64)?;
    w.write_str(",\"buf\":")?;
    emit_i64_array(w, q.buf)?;
    w.write_str(",\"sendw\":")?;
    emit_id_array(w, q.sendw)?;
    w.write_str(",\"recvw\":")?;
    emit_id_array(w, q.recvw)?;
    w.write_str("}")?;
    Ok(())
}
