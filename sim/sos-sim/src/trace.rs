//! Trace types and JSONL wire format. See SOS-02 §7 for the canonical
//! field order and typed-value encoding.

use std::io::{self, Write};

use serde::{Deserialize, Serialize};

use crate::datamodel::{Datamodel, Msg, Queue, Sem, TaskId, TaskState, Tcb};

/// An ordered sequence of [`TraceRecord`]s. Owns the on-disk
/// serialisation per SOS-02 §7.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct Trace {
    /// Records in emission order (boot baseline first, then one per
    /// external event in `Vector.input` index order).
    pub records: Vec<TraceRecord>,
}

impl Trace {
    /// Snapshot the observable subset of `dm` per SOS-02 §5.4 and §7.1.
    /// `after_input_idx = -1` denotes the boot-baseline record. Invalid
    /// sem/queue slots encode as `{"valid": false}` short-form per
    /// SOS-02 §7.2.
    pub fn snapshot(dm: &Datamodel, after_input_idx: i64) -> TraceRecord {
        let tcb: Vec<TcbSnapshot> = dm.tcb.iter().map(TcbSnapshot::from_tcb).collect();

        // ready[p] inner numbers are task-ids; SOS-02 §7.2 types them as
        // (signed) numbers — i32 is the canonical width on the wire.
        let ready: Vec<Vec<i32>> = dm
            .ready
            .iter()
            .map(|q| q.iter().map(|tid| *tid as i32).collect())
            .collect();

        let sems: Vec<SemSnapshot> = dm.sems.iter().map(SemSnapshot::from_sem).collect();
        let queues: Vec<QueueSnapshot> = dm.queues.iter().map(QueueSnapshot::from_queue).collect();

        TraceRecord {
            after_input_idx,
            current: dm.current as i32,
            tick_count: dm.tick_count,
            rc: i8::from(dm.rc) as i32,
            tcb,
            ready,
            sems,
            queues,
            irq_nest: dm.irq_nest as i32,
            sched_lock: dm.sched_lock as i32,
            pend_ticks: dm.pend_ticks as i32,
        }
    }

    /// Write every record as a JSON Lines stream (one record per line,
    /// LF terminator, UTF-8). INV-S-SIM-7: no buffering past quiescence —
    /// callers that supply a buffered writer are responsible for flushing
    /// at macrostep boundaries; the in-memory path emits the whole buffer
    /// here and flushes once at the end.
    ///
    /// The serializer writes `\n` line terminators only (never `\r\n`) per
    /// SOS-02 §6.5 (host-OS-portable determinism budget).
    pub fn write_jsonl<W: Write>(&self, w: &mut W) -> std::io::Result<()> {
        for rec in &self.records {
            serde_json::to_writer(&mut *w, rec).map_err(io::Error::from)?;
            w.write_all(b"\n")?;
        }
        w.flush()?;
        Ok(())
    }
}

/// One observable-state snapshot at a macrostep boundary. Field order
/// matches SOS-02 §7.1 exactly; `serde_json` preserves struct field order
/// when serialising with the `Serialize` derive.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TraceRecord {
    /// Position in `Vector.input` (`-1` for the boot-baseline record).
    pub after_input_idx: i64,
    /// `dm.current` at quiescence (`-1` when no task runs).
    pub current: i32,
    /// `dm.tick_count`.
    pub tick_count: i64,
    /// `dm.rc` (integer per SOS-00 §5.2).
    pub rc: i32,
    /// `dm.tcb[i]` snapshots, one entry per `i in [0, MAX_TASKS)`.
    pub tcb: Vec<TcbSnapshot>,
    /// `dm.ready[p]` snapshots, one entry per `p in [0, MAX_PRIO)`.
    pub ready: Vec<Vec<i32>>,
    /// `dm.sems[s]` snapshots; `valid==false` slots encode as
    /// `{"valid": false}` only.
    pub sems: Vec<SemSnapshot>,
    /// `dm.queues[q]` snapshots; symmetric to `sems`.
    pub queues: Vec<QueueSnapshot>,
    /// `dm.irq_nest`.
    pub irq_nest: i32,
    /// `dm.sched_lock`.
    pub sched_lock: i32,
    /// `dm.pend_ticks`.
    pub pend_ticks: i32,
}

/// One TCB snapshot. Field order matches SOS-02 §7.2.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TcbSnapshot {
    /// `tcb[i].id` — matches the slot index.
    pub id: TaskId,
    /// `tcb[i].prio`.
    pub prio: u8,
    /// `tcb[i].state` (integer per SOS-00 §5.1).
    pub state: TaskState,
    /// `tcb[i].deadline`.
    pub deadline: i64,
    /// `tcb[i].blk_obj` (`-1` when not blocked).
    pub blk_obj: i16,
    /// `tcb[i].msg`, encoded per SOS-02 §7.2.
    pub msg: Msg,
}

impl TcbSnapshot {
    /// Project a [`Tcb`] into its on-wire snapshot form. Pure copy — the
    /// observable subset is the whole TCB at v1 (SOS-00 §7.2).
    pub fn from_tcb(tcb: &Tcb) -> Self {
        TcbSnapshot {
            id: tcb.id,
            prio: tcb.prio,
            state: tcb.state,
            deadline: tcb.deadline,
            blk_obj: tcb.blk_obj,
            msg: tcb.msg.clone(),
        }
    }
}

/// One semaphore snapshot. `valid==false` slots encode as `{"valid": false}`
/// only per SOS-02 §7.2.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum SemSnapshot {
    /// Allocated slot — full record.
    Valid {
        /// Always `true` on the wire.
        valid: bool,
        /// Current count.
        count: u32,
        /// Maximum count (ceiling).
        max: u32,
        /// FIFO of blocked task ids.
        waiters: Vec<TaskId>,
    },
    /// Unallocated slot — `{"valid": false}` short form.
    Invalid {
        /// Always `false` on the wire.
        valid: bool,
    },
}

impl SemSnapshot {
    /// Project a [`Sem`] into its on-wire snapshot form. Invalid slots
    /// collapse to the `{"valid": false}` short form per SOS-02 §7.2.
    pub fn from_sem(sem: &Sem) -> Self {
        if sem.valid {
            SemSnapshot::Valid {
                valid: true,
                count: sem.count,
                max: sem.max,
                waiters: sem.waiters.clone(),
            }
        } else {
            SemSnapshot::Invalid { valid: false }
        }
    }
}

/// One queue snapshot. Symmetric to [`SemSnapshot`] per SOS-02 §7.2.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum QueueSnapshot {
    /// Allocated slot — full record.
    Valid {
        /// Always `true` on the wire.
        valid: bool,
        /// Capacity ceiling.
        cap: u32,
        /// Current count.
        count: u32,
        /// FIFO buffer of staged payloads.
        buf: Vec<i64>,
        /// FIFO of blocked senders.
        sendw: Vec<TaskId>,
        /// FIFO of blocked receivers.
        recvw: Vec<TaskId>,
    },
    /// Unallocated slot — `{"valid": false}` short form.
    Invalid {
        /// Always `false` on the wire.
        valid: bool,
    },
}

impl QueueSnapshot {
    /// Project a [`Queue`] into its on-wire snapshot form. Invalid slots
    /// collapse to `{"valid": false}` per SOS-02 §7.2.
    pub fn from_queue(q: &Queue) -> Self {
        if q.valid {
            QueueSnapshot::Valid {
                valid: true,
                cap: q.cap,
                count: q.count,
                buf: q.buf.clone(),
                sendw: q.sendw.clone(),
                recvw: q.recvw.clone(),
            }
        } else {
            QueueSnapshot::Invalid { valid: false }
        }
    }
}
