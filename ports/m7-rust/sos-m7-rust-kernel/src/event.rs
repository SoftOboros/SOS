//! Event / EventName / EventData types for the M7 Rust firmware port.
//!
//! Mirrors `sim/sos-sim/src/event.rs` 1:1 on `EventName` (the 18 external
//! event variants admitted by `rtos_kernel.scxml` per SOS-01 §5.3) and
//! replaces the runtime-typed `serde_json::Value` data field with a
//! fixed-shape [`EventData`] enum so the firmware can dispatch without a
//! JSON-Value parser at runtime.
//!
//! The JSON parser that produces [`Event`] instances from raw UART input
//! lives in `transport.rs` (deferred to wave 8); this module defines the
//! type surface that parser will populate.
//!
//! Wire-form correspondence (SOS-01 §5.3) is preserved structurally: each
//! [`EventName`] variant pairs with the [`EventData`] variant carrying the
//! same payload shape the chart's transition body destructures. The
//! mapping is enforced by convention here and validated by the dispatcher
//! in `scripts::dispatch_event` (wrong-variant payloads surface as
//! `ScriptError::WrongDataVariant`).
//!
//! Internal events (`kernel.boot.done`, `sched.run` per SOS-01 §5.6) are
//! NOT modelled here — the firmware's dispatcher runs the scheduler
//! microstep inline after every state-mutating script, mirroring sim's
//! macrostep semantics.

use crate::kernel::TaskId;

/// External event names — mirrors SOS-01 §5.3 `ExternalEventName` (18
/// variants at HEAD). One variant per syscall the chart admits.
///
/// The wire-form discriminant (`task.create`, `sem.give_from_isr`, etc.)
/// lives on the parser side (wave 8 `transport.rs`); this enum is the
/// in-firmware representation only.
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum EventName {
    /// `task.create` — pairs with [`EventData::TaskCreate`].
    TaskCreate,
    /// `task.delay` — pairs with [`EventData::TaskDelay`].
    TaskDelay,
    /// `task.yield` — pairs with [`EventData::None`].
    TaskYield,
    /// `task.suspend` — pairs with [`EventData::TaskId`].
    TaskSuspend,
    /// `task.resume` — pairs with [`EventData::TaskId`].
    TaskResume,
    /// `sem.create` — pairs with [`EventData::SemCreate`].
    SemCreate,
    /// `sem.take` — pairs with [`EventData::SemOp`] (`sid`, `timeout`).
    SemTake,
    /// `sem.give` — pairs with [`EventData::SemOp`] (`sid`; `timeout` ignored).
    SemGive,
    /// `sem.give_from_isr` — pairs with [`EventData::SemOp`] (`sid`;
    /// `timeout` ignored). ISR-context.
    SemGiveFromIsr,
    /// `queue.create` — pairs with [`EventData::QueueCreate`].
    QueueCreate,
    /// `queue.send` — pairs with [`EventData::QueueSend`].
    QueueSend,
    /// `queue.receive` — pairs with [`EventData::QueueReceive`].
    QueueReceive,
    /// `queue.send_from_isr` — pairs with [`EventData::QueueSend`]
    /// (`timeout` ignored). ISR-context.
    QueueSendFromIsr,
    /// `sys.tick` — pairs with [`EventData::None`]. ISR-context.
    SysTick,
    /// `crit.enter` — pairs with [`EventData::None`].
    CritEnter,
    /// `crit.exit` — pairs with [`EventData::None`].
    CritExit,
    /// `sched.suspend` — pairs with [`EventData::None`].
    SchedSuspend,
    /// `sched.resume` — pairs with [`EventData::None`].
    SchedResume,
}

/// Typed event payload. One variant per syscall family that carries data.
/// Variants are sized for the chart's actual payloads (no over-provisioning).
///
/// The variant choice is dictated by the SCXML transition body's
/// destructuring shape:
///   * Events with no payload (`task.yield`, `sys.tick`, `crit.*`,
///     `sched.*`) use [`Self::None`].
///   * Events sharing a payload shape (e.g. `task.suspend` + `task.resume`
///     both take `{ id }`) share a variant.
///   * Events with unique payload shapes get their own variant.
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum EventData {
    /// No payload. Used by `task.yield`, `sys.tick`, `crit.enter`,
    /// `crit.exit`, `sched.suspend`, `sched.resume`.
    None,
    /// `task.create` — `{ id, prio }`.
    TaskCreate {
        /// Slot index of the TCB to activate.
        id: TaskId,
        /// Priority band (`0..MAX_PRIO`).
        prio: u8,
    },
    /// `task.delay` — `{ ticks }`.
    TaskDelay {
        /// Tick count (positive blocks; non-positive yields).
        ticks: i64,
    },
    /// `task.suspend` — `{ id }`. Also used by `task.resume`.
    TaskId {
        /// Target TCB slot.
        id: TaskId,
    },
    /// `sem.create` — `{ id, initial, max }`.
    SemCreate {
        /// Slot index of the sem descriptor.
        id: i16,
        /// Initial count.
        initial: u32,
        /// Maximum count (ceiling).
        max: u32,
    },
    /// `sem.take` — `{ sid, timeout }`. Also used by `sem.give` (timeout
    /// ignored) and `sem.give_from_isr` (timeout ignored).
    SemOp {
        /// Semaphore id.
        sid: i16,
        /// Timeout in ticks. `0` = no-wait, `< 0` = forever, `> 0` = ticks.
        timeout: i64,
    },
    /// `queue.create` — `{ id, cap }`.
    QueueCreate {
        /// Slot index of the queue descriptor.
        id: i16,
        /// Capacity ceiling.
        cap: u32,
    },
    /// `queue.send` — `{ qid, msg, timeout }`. Also used by
    /// `queue.send_from_isr` (timeout ignored).
    QueueSend {
        /// Queue id.
        qid: i16,
        /// Payload to enqueue.
        msg: i64,
        /// Timeout in ticks. `0` = no-wait, `< 0` = forever, `> 0` = ticks.
        /// Ignored for `queue.send_from_isr`.
        timeout: i64,
    },
    /// `queue.receive` — `{ qid, timeout }`.
    QueueReceive {
        /// Queue id.
        qid: i16,
        /// Timeout in ticks. `0` = no-wait, `< 0` = forever, `> 0` = ticks.
        timeout: i64,
    },
}

/// Full event = name + typed payload + optional `from_tid` injection.
///
/// Per SOS-00 §7.1: when a vector has `from_tid: <int>`, the harness sets
/// `current = from_tid` before dispatching. `None` for ISR-context events
/// (`sys.tick`, `*_from_isr`) where `current` is not consulted by the
/// transition body.
#[derive(Clone, Copy, PartialEq, Eq)]
pub struct Event {
    /// Event name (SOS-01 §5.3 `ExternalEventName`).
    pub name: EventName,
    /// Typed payload. The `name → data` pairing is documented per-variant
    /// on [`EventName`]; mismatches surface at dispatch as
    /// `ScriptError::WrongDataVariant`.
    pub data: EventData,
    /// Issuer task id; `None` for ISR-context events.
    pub from_tid: Option<TaskId>,
}

impl Event {
    /// Convenience constructor for `sys.tick` events. ISR-context, no
    /// payload, no `from_tid`.
    pub const fn sys_tick() -> Self {
        Event {
            name: EventName::SysTick,
            data: EventData::None,
            from_tid: None,
        }
    }

    /// Convenience constructor for `task.yield` events.
    pub const fn task_yield(from_tid: TaskId) -> Self {
        Event {
            name: EventName::TaskYield,
            data: EventData::None,
            from_tid: Some(from_tid),
        }
    }

    /// Convenience constructor for `crit.enter`.
    pub const fn crit_enter(from_tid: TaskId) -> Self {
        Event {
            name: EventName::CritEnter,
            data: EventData::None,
            from_tid: Some(from_tid),
        }
    }

    /// Convenience constructor for `crit.exit`.
    pub const fn crit_exit(from_tid: TaskId) -> Self {
        Event {
            name: EventName::CritExit,
            data: EventData::None,
            from_tid: Some(from_tid),
        }
    }

    /// Convenience constructor for `sched.suspend`.
    pub const fn sched_suspend(from_tid: TaskId) -> Self {
        Event {
            name: EventName::SchedSuspend,
            data: EventData::None,
            from_tid: Some(from_tid),
        }
    }

    /// Convenience constructor for `sched.resume`.
    pub const fn sched_resume(from_tid: TaskId) -> Self {
        Event {
            name: EventName::SchedResume,
            data: EventData::None,
            from_tid: Some(from_tid),
        }
    }
}
