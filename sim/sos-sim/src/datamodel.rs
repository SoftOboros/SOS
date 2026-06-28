//! SOS kernel datamodel — mirror of every `<data id="...">` in
//! `rtos_kernel.scxml`.
//!
//! See SOS-02 §6.1 (module layout) and SOS-00 §5.1 / §5.2 / §5.6 for the
//! frozen enums re-exported below. The struct field order here matches the
//! SOS-02 §7.1 trace serialisation order so that `serde_json` emits records
//! in the canonical sequence.

use serde::de::{self, MapAccess, Visitor};
use serde::ser::SerializeMap;
use serde::{Deserialize, Deserializer, Serialize, Serializer};

use crate::vector::Config;

/// Task identifier. The chart uses `-1` as the "none" sentinel for fields
/// like `current` or `blk_obj`; ports realise this as a signed type.
pub type TaskId = i16;

/// The full mutable kernel state. One `Datamodel` per `Simulator` instance.
///
/// Field order mirrors the SOS-02 §7.1 trace serialisation order so that
/// `serde_json`'s `Serialize` derive (used by the `Trace` writer) emits
/// canonical bytes. See SOS-02 §6.1 and the parent `<data id="...">`
/// declarations in `rtos_kernel.scxml`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Datamodel {
    /// `MAX_TASKS` (SOS-00 §7.1 vector config). Sized once at construction.
    pub max_tasks: usize,
    /// `MAX_PRIO`. Sized once at construction.
    pub max_prio: usize,
    /// `MAX_SEMS`. Sized once at construction.
    pub max_sems: usize,
    /// `MAX_QUEUES`. Sized once at construction.
    pub max_queues: usize,
    /// `Q_DEPTH` — per-queue buffer capacity ceiling.
    pub q_depth: usize,
    /// `tcb[i]` for `i in [0, MAX_TASKS)`. Per chart datamodel.
    pub tcb: Vec<Tcb>,
    /// `ready[p][..]` — per-priority FIFO of ready task ids.
    pub ready: Vec<Vec<TaskId>>,
    /// `current` — the running task id (`-1` when no task is running).
    pub current: TaskId,
    /// `tick_count` — monotonic tick counter.
    pub tick_count: i64,
    /// `rc` — last syscall return code.
    pub rc: ReturnCode,
    /// `irq_nest` — `crit.enter`/`crit.exit` depth.
    pub irq_nest: u32,
    /// `sched_lock` — `sched.suspend`/`sched.resume` depth.
    pub sched_lock: u32,
    /// `pend_ticks` — deferred tick count accumulated while
    /// `irq_nest > 0` or `sched_lock > 0`.
    pub pend_ticks: u32,
    /// `sems[s]` for `s in [0, MAX_SEMS)`.
    pub sems: Vec<Sem>,
    /// `queues[q]` for `q in [0, MAX_QUEUES)`.
    pub queues: Vec<Queue>,
    /// `resched` — internal flag raised by state-mutating transitions to
    /// request a `sched.run` microstep.
    pub resched: bool,
}

impl Datamodel {
    /// Construct a fresh datamodel sized per `config`. Mirrors the chart's
    /// `<boot>` macrostep (rtos_kernel.scxml lines ~170-196): allocates the
    /// TCB / sem / queue pools, parks idle in `ready[0]`, then promotes
    /// idle to `ST_RUNNING` (the static result of the boot-time
    /// `pick_next()` call — at boot only task 0 is ready).
    pub fn new(config: &Config) -> Self {
        // TCB pool: every slot dormant at construction; idle becomes
        // RUNNING below after we mirror the chart's pick_next().
        let mut tcb: Vec<Tcb> = (0..config.max_tasks)
            .map(|i| Tcb {
                id: i as TaskId,
                prio: 0,
                state: TaskState::Dormant,
                deadline: 0,
                blk_obj: -1,
                msg: Msg::Null,
            })
            .collect();

        // Empty FIFOs per priority band.
        let ready: Vec<Vec<TaskId>> = (0..config.max_prio).map(|_| Vec::new()).collect();

        // Mirror the chart's <boot>:
        //   ready_push(0); pick_next();
        // At boot only task 0 is ready, so pick_next() pops it from
        // ready[0] and assigns current = 0, transitioning idle to
        // RUNNING. We encode that static result directly.
        if !tcb.is_empty() {
            tcb[0].state = TaskState::Running;
        }

        let sems: Vec<Sem> = (0..config.max_sems)
            .map(|_| Sem {
                valid: false,
                count: 0,
                max: 0,
                waiters: Vec::new(),
            })
            .collect();

        let queues: Vec<Queue> = (0..config.max_queues)
            .map(|_| Queue {
                valid: false,
                buf: Vec::new(),
                cap: 0,
                count: 0,
                sendw: Vec::new(),
                recvw: Vec::new(),
            })
            .collect();

        Datamodel {
            max_tasks: config.max_tasks,
            max_prio: config.max_prio,
            max_sems: config.max_sems,
            max_queues: config.max_queues,
            q_depth: config.q_depth,
            tcb,
            ready,
            current: 0,
            tick_count: 0,
            rc: ReturnCode::Ok,
            irq_nest: 0,
            sched_lock: 0,
            pend_ticks: 0,
            sems,
            queues,
            resched: false,
        }
    }
}

/// One Task Control Block. Mirrors `tcb[i]` in the chart per SOS-00 §3.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Tcb {
    /// Task id — matches the slot index `i`.
    pub id: TaskId,
    /// Priority (`0..MAX_PRIO`). Lower is lower (chart convention).
    pub prio: u8,
    /// Lifecycle state.
    pub state: TaskState,
    /// Tick-deadline used by `task.delay` and `*` timeouts.
    pub deadline: i64,
    /// Blocked-object index when `state` is `BlkSem` / `BlkQs` / `BlkQr`;
    /// `-1` otherwise. Constrained by SOS-00 INV-S6.
    pub blk_obj: i16,
    /// Polymorphic message slot per SOS-00 §5.6.
    pub msg: Msg,
}

/// Task lifecycle state. Discriminants match SOS-00 §5.1 exactly; the
/// integer values land on the wire per SOS-02 §7.2.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[repr(u8)]
#[serde(into = "u8", try_from = "u8")]
pub enum TaskState {
    /// `ST_DORMANT` — TCB slot unused.
    Dormant = 0,
    /// `ST_READY` — in a `ready[prio]` queue, eligible to run.
    Ready = 1,
    /// `ST_RUNNING` — `current == id`, removed from `ready[]`.
    Running = 2,
    /// `ST_DELAY` — time-blocked, on no waiter list.
    Delay = 3,
    /// `ST_BLK_SEM` — on `sems[blk_obj].waiters`.
    BlkSem = 4,
    /// `ST_BLK_QS` — on `queues[blk_obj].sendw`, msg pending.
    BlkQs = 5,
    /// `ST_BLK_QR` — on `queues[blk_obj].recvw`.
    BlkQr = 6,
    /// `ST_SUSPEND` — off all lists, awaits explicit resume.
    Suspend = 7,
}

impl From<TaskState> for u8 {
    fn from(s: TaskState) -> u8 {
        s as u8
    }
}

impl TryFrom<u8> for TaskState {
    type Error = String;
    fn try_from(v: u8) -> Result<Self, Self::Error> {
        match v {
            0 => Ok(TaskState::Dormant),
            1 => Ok(TaskState::Ready),
            2 => Ok(TaskState::Running),
            3 => Ok(TaskState::Delay),
            4 => Ok(TaskState::BlkSem),
            5 => Ok(TaskState::BlkQs),
            6 => Ok(TaskState::BlkQr),
            7 => Ok(TaskState::Suspend),
            other => Err(format!("invalid TaskState discriminant: {other}")),
        }
    }
}

/// Syscall return code. Discriminants match SOS-00 §5.2 exactly; integer
/// values land on the wire per SOS-02 §7.2.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[repr(i8)]
#[serde(into = "i8", try_from = "i8")]
pub enum ReturnCode {
    /// `RC_OK` — success.
    Ok = 0,
    /// `RC_TIMEOUT` — wait expired.
    Timeout = -1,
    /// `RC_FULL` — queue or semaphore at capacity.
    Full = -2,
    /// `RC_EMPTY` — queue empty on poll.
    Empty = -3,
    /// `RC_INVAL` — invalid argument (bad object id, bad state).
    Inval = -4,
}

impl From<ReturnCode> for i8 {
    fn from(r: ReturnCode) -> i8 {
        r as i8
    }
}

impl TryFrom<i8> for ReturnCode {
    type Error = String;
    fn try_from(v: i8) -> Result<Self, Self::Error> {
        match v {
            0 => Ok(ReturnCode::Ok),
            -1 => Ok(ReturnCode::Timeout),
            -2 => Ok(ReturnCode::Full),
            -3 => Ok(ReturnCode::Empty),
            -4 => Ok(ReturnCode::Inval),
            other => Err(format!("invalid ReturnCode discriminant: {other}")),
        }
    }
}

/// Polymorphic value carried in `tcb[i].msg`. Per SOS-00 §5.6 + SOS-02
/// §6.3.1. Wire form per SOS-00 §5.6 Amendment 004 (ratified 2026-05-19):
///
/// | Variant | JSON wire form |
/// |---|---|
/// | `Null` | `null` |
/// | `Int(N)` | bare signed integer `N` |
/// | `ReturnCode(rc)` | tagged object `{"rc": <i8>}` |
///
/// The on-wire discriminator object form for `ReturnCode` is load-bearing:
/// it preserves the chart's distinction between "queue payload that happens
/// to equal 0" (`Msg::Int(0)`) and "return code `RC_OK`"
/// (`Msg::ReturnCode(Ok)` → `{"rc": 0}`). A naive `#[serde(untagged)]`
/// derive collapses the latter to bare `0`, which is the bug this custom
/// (de)serialiser exists to prevent. See SOS-00 §15 Amendment 004 + SOS-02
/// §7.2 row `tcb[i].msg`.
#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub enum Msg {
    /// No staged message. JSON `null`.
    #[default]
    Null,
    /// Integer payload (queue message or arbitrary cookie). JSON number.
    Int(i64),
    /// Final return code deposited at unblock. JSON `{"rc": <i8>}` per
    /// SOS-00 §5.6 Amendment 004.
    ReturnCode(ReturnCode),
}

impl Serialize for Msg {
    fn serialize<S>(&self, s: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        match self {
            // `null` on the wire — `serialize_none` is the canonical
            // serde-side primitive for that.
            Msg::Null => s.serialize_none(),
            // Bare signed integer on the wire.
            Msg::Int(n) => s.serialize_i64(*n),
            // Tagged object `{"rc": <i8>}` — single-key map per SOS-00
            // §5.6 Amendment 004 wire form.
            Msg::ReturnCode(rc) => {
                let mut m = s.serialize_map(Some(1))?;
                m.serialize_entry("rc", &(*rc as i8))?;
                m.end()
            }
        }
    }
}

impl<'de> Deserialize<'de> for Msg {
    fn deserialize<D>(d: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        struct MsgVisitor;

        impl<'de> Visitor<'de> for MsgVisitor {
            type Value = Msg;

            fn expecting(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
                f.write_str("null, a signed integer, or an object `{\"rc\": <i8>}`")
            }

            fn visit_unit<E>(self) -> Result<Self::Value, E>
            where
                E: de::Error,
            {
                Ok(Msg::Null)
            }

            fn visit_none<E>(self) -> Result<Self::Value, E>
            where
                E: de::Error,
            {
                Ok(Msg::Null)
            }

            fn visit_some<D>(self, d: D) -> Result<Self::Value, D::Error>
            where
                D: Deserializer<'de>,
            {
                d.deserialize_any(MsgVisitor)
            }

            fn visit_i64<E>(self, v: i64) -> Result<Self::Value, E>
            where
                E: de::Error,
            {
                Ok(Msg::Int(v))
            }

            fn visit_u64<E>(self, v: u64) -> Result<Self::Value, E>
            where
                E: de::Error,
            {
                if v <= i64::MAX as u64 {
                    Ok(Msg::Int(v as i64))
                } else {
                    Err(E::custom(format!("Msg::Int payload {v} exceeds i64::MAX")))
                }
            }

            fn visit_i32<E>(self, v: i32) -> Result<Self::Value, E>
            where
                E: de::Error,
            {
                Ok(Msg::Int(v as i64))
            }

            fn visit_u32<E>(self, v: u32) -> Result<Self::Value, E>
            where
                E: de::Error,
            {
                Ok(Msg::Int(v as i64))
            }

            fn visit_map<A>(self, mut map: A) -> Result<Self::Value, A::Error>
            where
                A: MapAccess<'de>,
            {
                // Expect exactly one key, "rc", whose value is an i8.
                let key: Option<String> = map.next_key()?;
                let key = key.ok_or_else(|| {
                    de::Error::custom("expected object `{\"rc\": <i8>}`, got empty map")
                })?;
                if key != "rc" {
                    return Err(de::Error::custom(format!(
                        "expected object key \"rc\", got {key:?}"
                    )));
                }
                let v: i8 = map.next_value()?;
                let rc = ReturnCode::try_from(v).map_err(de::Error::custom)?;
                // Reject trailing keys.
                if let Some(extra) = map.next_key::<String>()? {
                    return Err(de::Error::custom(format!(
                        "unexpected extra key {extra:?} in Msg::ReturnCode object"
                    )));
                }
                Ok(Msg::ReturnCode(rc))
            }
        }

        d.deserialize_any(MsgVisitor)
    }
}

/// One semaphore descriptor. Mirrors `sems[s]` in the chart.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Sem {
    /// `true` once `sem.create` has populated the slot.
    pub valid: bool,
    /// Current count.
    pub count: u32,
    /// Maximum count (ceiling).
    pub max: u32,
    /// FIFO of blocked task ids per SOS-00 INV-S8.
    pub waiters: Vec<TaskId>,
}

/// One queue descriptor. Mirrors `queues[q]` in the chart.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Queue {
    /// `true` once `queue.create` has populated the slot.
    pub valid: bool,
    /// FIFO buffer of staged payloads.
    pub buf: Vec<i64>,
    /// Capacity ceiling (`≤ Q_DEPTH`).
    pub cap: u32,
    /// Current count (`buf.len()` as a `u32`).
    pub count: u32,
    /// FIFO of senders blocked on `count == cap`.
    pub sendw: Vec<TaskId>,
    /// FIFO of receivers blocked on `count == 0`.
    pub recvw: Vec<TaskId>,
}
