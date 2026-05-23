//! External-event vocabulary admitted by the simulator. Mirrors SOS-01 §5.3
//! `ExternalEventName` (18 events at HEAD) plus the `_event.data` payload
//! discipline from SOS-00 §7.1.

use serde::{Deserialize, Serialize};

use crate::datamodel::TaskId;
use crate::error::SimError;

/// One external event admitted by `rtos_kernel.scxml`. Variants mirror
/// SOS-01 §5.3 `ExternalEventName`; the `#[serde(rename = "...")]`
/// annotation carries the dotted wire form so JSON round-trips faithfully.
///
/// Internal events (`kernel.boot.done`, `sched.run` per SOS-01 §5.6) are
/// NOT modelled here — they are queued / drained by the simulator's
/// macrostep harness and never appear in `Vector.input`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum EventName {
    /// `task.create` — `{ id, prio }`.
    #[serde(rename = "task.create")]
    TaskCreate,
    /// `task.delay` — `{ ticks }`.
    #[serde(rename = "task.delay")]
    TaskDelay,
    /// `task.yield` — no payload.
    #[serde(rename = "task.yield")]
    TaskYield,
    /// `task.suspend` — `{ id }`.
    #[serde(rename = "task.suspend")]
    TaskSuspend,
    /// `task.resume` — `{ id }`.
    #[serde(rename = "task.resume")]
    TaskResume,
    /// `sem.create` — `{ id, initial, max }`.
    #[serde(rename = "sem.create")]
    SemCreate,
    /// `sem.take` — `{ sid, timeout }`.
    #[serde(rename = "sem.take")]
    SemTake,
    /// `sem.give` — `{ sid }`.
    #[serde(rename = "sem.give")]
    SemGive,
    /// `sem.give_from_isr` — `{ sid }`. ISR-context.
    #[serde(rename = "sem.give_from_isr")]
    SemGiveFromIsr,
    /// `queue.create` — `{ id, cap }`.
    #[serde(rename = "queue.create")]
    QueueCreate,
    /// `queue.send` — `{ qid, msg, timeout }`.
    #[serde(rename = "queue.send")]
    QueueSend,
    /// `queue.receive` — `{ qid, timeout }`.
    #[serde(rename = "queue.receive")]
    QueueReceive,
    /// `queue.send_from_isr` — `{ qid, msg }`. ISR-context.
    #[serde(rename = "queue.send_from_isr")]
    QueueSendFromIsr,
    /// `sys.tick` — no payload. ISR-context.
    #[serde(rename = "sys.tick")]
    SysTick,
    /// `crit.enter` — no payload.
    #[serde(rename = "crit.enter")]
    CritEnter,
    /// `crit.exit` — no payload.
    #[serde(rename = "crit.exit")]
    CritExit,
    /// `sched.suspend` — no payload.
    #[serde(rename = "sched.suspend")]
    SchedSuspend,
    /// `sched.resume` — no payload.
    #[serde(rename = "sched.resume")]
    SchedResume,
}

/// One external event with payload. Mirrors the per-event row of SOS-00
/// §7.1 vector input: a name, a JSON payload (`_event.data`), and an
/// optional `from_tid` (the issuer's task id; `None` for ISR-context
/// events).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Event {
    /// Event name (SOS-01 §5.3 `ExternalEventName`).
    #[serde(rename = "event")]
    pub name: EventName,
    /// Event payload — opaque JSON; transition bodies destructure it
    /// per the per-event payload contract in SOS-01 §5.3.
    #[serde(default)]
    pub data: serde_json::Value,
    /// Issuer task id; `None` for ISR-originated events.
    #[serde(default, rename = "from_tid")]
    pub from_tid: Option<TaskId>,
}

impl Event {
    /// Parse one event from its JSON form. Strict — unknown event names
    /// (i.e. those not in SOS-01 §5.3 `ExternalEventName`) surface as
    /// `SimError::VectorParse` because serde rejects unknown
    /// `#[serde(rename = "...")]` discriminants.
    pub fn parse(json: &str) -> Result<Self, SimError> {
        serde_json::from_str::<Event>(json).map_err(|e| {
            SimError::VectorParse(format!("event JSON did not parse: {e}"))
        })
    }
}
