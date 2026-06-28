//! Hand-compiled `<script>` bodies — port-side mirror of
//! `sim/sos-sim/src/scripts.rs`.
//!
//! See SOS-02 §6.3 (script-name table) and PCDN-SOS-00-005 → (b)
//! (hand-compilation as the v1 bootstrap). Each transition's `<script>`
//! block from `rtos_kernel.scxml` is translated 1:1 into a
//! `script_<state>_<event>_<index>` free function below. Helpers from the
//! chart's top-level `<script>` block (lines 77-165) are realised as
//! `impl Datamodel { ... }` methods.
//!
//! The transpilation follows SOS-02 §6.3 mapping rules; see each fn's
//! doc-comment for the `.scxml` line range it mirrors.
//!
//! Adaptations vs. sim's scripts.rs:
//!   * `heapless::Vec<_, N>` instead of `Vec` (fixed-capacity). `.push()`
//!     returns `Result`; the chart invariants (MAX_TASKS, MAX_SEMS, etc.)
//!     guarantee no overflow but the type system requires explicit
//!     handling — we use `.ok()` for fire-and-forget and return
//!     `ScriptError::*Full` from the rare paths where overflow would
//!     indicate an invariant violation.
//!   * Event payloads are typed via [`EventData`] (no runtime JSON
//!     extraction). Wrong-variant payloads surface as
//!     [`ScriptError::WrongDataVariant`].
//!   * No `SimError` — firmware uses the local [`ScriptError`] enum.
//!   * No `ScriptProvider` trait — single implementation, top-level
//!     [`dispatch_event`] free function does the matching.

use heapless::Vec as HVec;

use crate::event::{Event, EventData, EventName};
use crate::kernel::{Datamodel, Msg, ReturnCode, TaskId, TaskState, MAX_PRIO, MAX_TASKS, Q_DEPTH};

// ---------------------------------------------------------------------------
// Error type — port-side replacement for `SimError`.
// ---------------------------------------------------------------------------

/// Errors a hand-compiled script body MAY surface to its dispatcher.
///
/// These represent conditions that the chart's invariants make impossible
/// in a well-formed event stream; if they fire, the caller has either
/// supplied a payload of the wrong shape (parser bug) or violated a
/// dimensional bound (vector-generation bug). The dispatcher converts them
/// to trace records per SOS-02 §7.x.
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum ScriptError {
    /// The [`EventData`] variant attached to the [`Event`] did not match
    /// the variant expected for the [`EventName`].
    WrongDataVariant,
    /// `TaskId` argument out of range for `[0, MAX_TASKS)`.
    InvalidTaskId,
    /// Semaphore id out of range for `[0, MAX_SEMS)`.
    InvalidSemId,
    /// Queue id out of range for `[0, MAX_QUEUES)`.
    InvalidQueueId,
    /// Attempted to push to a per-priority READY queue at capacity. The
    /// chart's invariants make this impossible (at most MAX_TASKS distinct
    /// tids exist).
    ReadyQueueFull,
    /// Attempted to push to a waiter list at capacity. Same invariant
    /// reasoning as [`Self::ReadyQueueFull`].
    WaiterListFull,
    /// Attempted to push to a queue buffer at capacity beyond `cap`. The
    /// chart's `count < cap` precondition makes this impossible.
    QueueBufferFull,
    /// Script body reached a branch whose precondition the chart proves
    /// unreachable (e.g. `sem.take` blocking with `current < 0`).
    BadState,
}

// ---------------------------------------------------------------------------
// Helper methods on Datamodel — translation of the chart's HELPERS block
// (rtos_kernel.scxml lines 77-165). Mirrors sim's impl block 1:1 with
// heapless-aware `.push().ok()` and bounded-capacity overflow checks.
// ---------------------------------------------------------------------------

/// Discriminator for the three waiter lists the chart maintains.
#[derive(Copy, Clone)]
enum WaiterList {
    SemWaiters,
    QueueSendW,
    QueueRecvW,
}

impl Datamodel {
    /// Translates `ready_push` (rtos_kernel.scxml lines 86-89).
    ///
    /// Push `tid` onto the tail of its priority queue and mark READY.
    /// Returns `Err(ReadyQueueFull)` if the per-priority queue is at
    /// `MAX_TASKS` capacity — chart-invariant unreachable.
    pub(crate) fn ready_push(&mut self, tid: TaskId) -> Result<(), ScriptError> {
        let p = self.tcb[tid as usize].prio as usize;
        self.ready[p]
            .push(tid)
            .map_err(|_| ScriptError::ReadyQueueFull)?;
        self.tcb[tid as usize].state = TaskState::Ready;
        Ok(())
    }

    /// Translates `ready_remove` (rtos_kernel.scxml lines 92-96).
    ///
    /// Remove `tid` from its priority queue (no-op if absent).
    pub(crate) fn ready_remove(&mut self, tid: TaskId) {
        let p = self.tcb[tid as usize].prio as usize;
        if let Some(idx) = self.ready[p].iter().position(|&v| v == tid) {
            // heapless::Vec::remove(idx) returns the element; we discard.
            self.ready[p].remove(idx);
        }
    }

    /// Translates `ready_pop_highest` (rtos_kernel.scxml lines 99-104).
    ///
    /// Pop highest-priority ready task (FIFO within priority); returns
    /// `-1` if no task is ready.
    pub(crate) fn ready_pop_highest(&mut self) -> TaskId {
        let mut p = self.max_prio as isize - 1;
        while p >= 0 {
            if !self.ready[p as usize].is_empty() {
                return self.ready[p as usize].remove(0);
            }
            p -= 1;
        }
        -1
    }

    /// Translates `waiters_insert` (rtos_kernel.scxml lines 108-113).
    ///
    /// Insert `tid` into the named waiter list ordered by priority
    /// descending, FIFO within priority. Returns `Err(WaiterListFull)`
    /// if the list is at capacity — chart-invariant unreachable.
    fn waiters_insert(
        &mut self,
        kind: WaiterList,
        obj: usize,
        tid: TaskId,
    ) -> Result<(), ScriptError> {
        let p = self.tcb[tid as usize].prio;
        let mut i: usize = 0;
        loop {
            let arr = self.waiter_arr(kind, obj);
            if i >= arr.len() {
                break;
            }
            let head = arr[i];
            if self.tcb[head as usize].prio < p {
                break;
            }
            i += 1;
        }
        let lst = self.waiter_arr_mut(kind, obj);
        lst.insert(i, tid).map_err(|_| ScriptError::WaiterListFull)
    }

    /// Translates `block_current` (rtos_kernel.scxml lines 117-123).
    pub(crate) fn block_current(&mut self, state: TaskState, obj_id: i16, deadline: i64) {
        let cur = self.current as usize;
        self.tcb[cur].state = state;
        self.tcb[cur].blk_obj = obj_id;
        self.tcb[cur].deadline = deadline;
        self.current = -1;
        self.resched = true;
    }

    /// Translates `unblock` (rtos_kernel.scxml lines 126-131).
    ///
    /// Move `tid` back to READY, clear block info, request reschedule.
    /// Surfaces ready-push overflow per [`Self::ready_push`].
    pub(crate) fn unblock(&mut self, tid: TaskId) -> Result<(), ScriptError> {
        self.tcb[tid as usize].deadline = 0;
        self.tcb[tid as usize].blk_obj = -1;
        self.ready_push(tid)?;
        self.resched = true;
        Ok(())
    }

    /// Translates `waiter_cancel` (rtos_kernel.scxml lines 135-145).
    ///
    /// Cancel `tid`'s waiter slot when timing out; the list is inferred
    /// from the task's blocked state.
    pub(crate) fn waiter_cancel(&mut self, tid: TaskId) {
        let state = self.tcb[tid as usize].state;
        let obj = self.tcb[tid as usize].blk_obj;
        if obj < 0 {
            return;
        }
        let obj = obj as usize;
        match state {
            TaskState::BlkSem => {
                if let Some(s) = self.sems.get_mut(obj) {
                    if let Some(i) = s.waiters.iter().position(|&v| v == tid) {
                        s.waiters.remove(i);
                    }
                }
            }
            TaskState::BlkQs => {
                if let Some(q) = self.queues.get_mut(obj) {
                    if let Some(i) = q.sendw.iter().position(|&v| v == tid) {
                        q.sendw.remove(i);
                    }
                }
            }
            TaskState::BlkQr => {
                if let Some(q) = self.queues.get_mut(obj) {
                    if let Some(i) = q.recvw.iter().position(|&v| v == tid) {
                        q.recvw.remove(i);
                    }
                }
            }
            _ => {}
        }
    }

    /// Translates `pick_next` (rtos_kernel.scxml lines 149-163).
    ///
    /// Scheduler step: if a higher-priority READY task exists, switch.
    /// Round-robin within priority: re-queue current at tail before pop.
    pub(crate) fn pick_next(&mut self) -> Result<(), ScriptError> {
        if self.current >= 0 {
            let cur = self.current as usize;
            if self.tcb[cur].state == TaskState::Running {
                self.tcb[cur].state = TaskState::Ready;
                let p = self.tcb[cur].prio as usize;
                let id = self.tcb[cur].id;
                self.ready[p]
                    .push(id)
                    .map_err(|_| ScriptError::ReadyQueueFull)?;
            }
        }
        let n = self.ready_pop_highest();
        if n >= 0 {
            self.tcb[n as usize].state = TaskState::Running;
            self.current = n;
        } else {
            self.current = -1;
        }
        self.resched = false;
        Ok(())
    }

    // -- helper-of-helpers: typed view into one of the three waiter lists --

    fn waiter_arr(&self, kind: WaiterList, obj: usize) -> &[TaskId] {
        match kind {
            WaiterList::SemWaiters => &self.sems[obj].waiters,
            WaiterList::QueueSendW => &self.queues[obj].sendw,
            WaiterList::QueueRecvW => &self.queues[obj].recvw,
        }
    }

    fn waiter_arr_mut(&mut self, kind: WaiterList, obj: usize) -> &mut HVec<TaskId, MAX_TASKS> {
        match kind {
            WaiterList::SemWaiters => &mut self.sems[obj].waiters,
            WaiterList::QueueSendW => &mut self.queues[obj].sendw,
            WaiterList::QueueRecvW => &mut self.queues[obj].recvw,
        }
    }
}

// ---------------------------------------------------------------------------
// Transition script bodies. Order follows the .scxml document order.
// ---------------------------------------------------------------------------

/// Translates rtos_kernel.scxml lines 172-192 (boot onentry).
///
/// Mirrors the chart's `<boot>/<onentry>` block. The firmware's
/// `kernel::init()` already performs the boot-equivalent state setup
/// (pool zero-init + idle promotion); the dispatcher never invokes this
/// function. Provided for parity / future-use only.
pub fn script_boot_onentry_0(dm: &mut Datamodel, _ev: &Event) -> Result<(), ScriptError> {
    // readyq_init(): one empty FIFO per priority. (Re-)zero in case the
    // caller is using this for explicit re-init.
    for i in 0..MAX_PRIO {
        dm.ready[i].clear();
    }

    // Allocate TCB pool; idle reserved at prio 0.
    for i in 0..MAX_TASKS {
        dm.tcb[i] = crate::kernel::Tcb {
            id: i as TaskId,
            prio: 0,
            state: TaskState::Dormant,
            deadline: 0,
            blk_obj: -1,
            msg: Msg::Null,
        };
    }
    dm.tcb[0].prio = 0;
    dm.ready_push(0)?;

    // Sem and queue pools as invalid descriptors.
    for s in dm.sems.iter_mut() {
        s.valid = false;
        s.count = 0;
        s.max = 0;
        s.waiters.clear();
    }
    for q in dm.queues.iter_mut() {
        q.valid = false;
        q.buf.clear();
        q.cap = 0;
        q.count = 0;
        q.sendw.clear();
        q.recvw.clear();
    }

    // Bring idle to RUNNING.
    dm.pick_next()
}

/// Translates rtos_kernel.scxml lines 210-212 (sched_idle / sched.run).
///
/// `<transition event="sched.run" cond="sched_lock == 0">` — only the
/// cond-true arm carries a script; the harness owns predicate dispatch.
pub fn script_sched_idle_sched_run_0(dm: &mut Datamodel, _ev: &Event) -> Result<(), ScriptError> {
    dm.pick_next()
}

/// Translates rtos_kernel.scxml lines 225-252 (tick_idle / sys.tick).
pub fn script_tick_idle_sys_tick_0(dm: &mut Datamodel, _ev: &Event) -> Result<(), ScriptError> {
    if dm.irq_nest > 0 || dm.sched_lock > 0 {
        // Cannot mutate ready queue safely; defer.
        dm.pend_ticks += 1;
    } else {
        dm.tick_count += 1;
        let n = dm.max_tasks;
        for i in 0..n {
            let (state, deadline) = {
                let t = &dm.tcb[i];
                (t.state, t.deadline)
            };

            // Pure delay expiration
            if state == TaskState::Delay && deadline <= dm.tick_count {
                dm.tcb[i].msg = Msg::ReturnCode(ReturnCode::Ok);
                dm.unblock(i as TaskId)?;
                continue;
            }
            // Timeout on a blocked-with-deadline task
            let is_blocked = matches!(
                state,
                TaskState::BlkSem | TaskState::BlkQs | TaskState::BlkQr
            );
            if is_blocked && deadline > 0 && deadline <= dm.tick_count {
                dm.waiter_cancel(i as TaskId);
                dm.tcb[i].msg = Msg::ReturnCode(ReturnCode::Timeout);
                dm.unblock(i as TaskId)?;
            }
        }
    }
    Ok(())
}

/// Translates rtos_kernel.scxml lines 270-286 (transition event="task.create").
pub fn script_sys_idle_task_create_0(dm: &mut Datamodel, ev: &Event) -> Result<(), ScriptError> {
    let (id, prio) = match ev.data {
        EventData::TaskCreate { id, prio } => (id, prio),
        _ => return Err(ScriptError::WrongDataVariant),
    };
    let idx = id as usize;
    if id < 0 || idx >= dm.tcb.len() {
        dm.rc = ReturnCode::Inval;
        return Ok(());
    }
    if dm.tcb[idx].state != TaskState::Dormant {
        dm.rc = ReturnCode::Inval;
    } else {
        dm.tcb[idx].prio = prio;
        dm.tcb[idx].deadline = 0;
        dm.tcb[idx].blk_obj = -1;
        dm.tcb[idx].msg = Msg::Null;
        dm.ready_push(id)?;
        dm.resched = true;
        dm.rc = ReturnCode::Ok;
    }
    Ok(())
}

/// Translates rtos_kernel.scxml lines 289-300 (transition event="task.delay").
pub fn script_sys_idle_task_delay_0(dm: &mut Datamodel, ev: &Event) -> Result<(), ScriptError> {
    let ticks = match ev.data {
        EventData::TaskDelay { ticks } => ticks,
        _ => return Err(ScriptError::WrongDataVariant),
    };
    if ticks > 0 {
        dm.block_current(TaskState::Delay, -1, dm.tick_count + ticks);
    } else {
        dm.resched = true;
    }
    dm.rc = ReturnCode::Ok;
    Ok(())
}

/// Translates rtos_kernel.scxml lines 302-305 (transition event="task.yield").
pub fn script_sys_idle_task_yield_0(dm: &mut Datamodel, _ev: &Event) -> Result<(), ScriptError> {
    dm.resched = true;
    dm.rc = ReturnCode::Ok;
    Ok(())
}

/// Translates rtos_kernel.scxml lines 308-326 (transition event="task.suspend").
pub fn script_sys_idle_task_suspend_0(dm: &mut Datamodel, ev: &Event) -> Result<(), ScriptError> {
    let id = match ev.data {
        EventData::TaskId { id } => id,
        _ => return Err(ScriptError::WrongDataVariant),
    };
    let idx = id as usize;
    if id < 0 || idx >= dm.tcb.len() {
        dm.rc = ReturnCode::Inval;
        return Ok(());
    }
    let s = dm.tcb[idx].state;
    if s == TaskState::Ready {
        dm.ready_remove(id);
        dm.tcb[idx].state = TaskState::Suspend;
        dm.rc = ReturnCode::Ok;
    } else if s == TaskState::Running {
        dm.tcb[idx].state = TaskState::Suspend;
        dm.current = -1;
        dm.resched = true;
        dm.rc = ReturnCode::Ok;
    } else {
        // suspend of blocked task not modeled
        dm.rc = ReturnCode::Inval;
    }
    Ok(())
}

/// Translates rtos_kernel.scxml lines 329-341 (transition event="task.resume").
pub fn script_sys_idle_task_resume_0(dm: &mut Datamodel, ev: &Event) -> Result<(), ScriptError> {
    let id = match ev.data {
        EventData::TaskId { id } => id,
        _ => return Err(ScriptError::WrongDataVariant),
    };
    let idx = id as usize;
    if id < 0 || idx >= dm.tcb.len() {
        dm.rc = ReturnCode::Inval;
        return Ok(());
    }
    if dm.tcb[idx].state == TaskState::Suspend {
        dm.ready_push(id)?;
        dm.resched = true;
        dm.rc = ReturnCode::Ok;
    } else {
        dm.rc = ReturnCode::Inval;
    }
    Ok(())
}

/// Translates rtos_kernel.scxml lines 346-356 (transition event="sem.create").
pub fn script_sys_idle_sem_create_0(dm: &mut Datamodel, ev: &Event) -> Result<(), ScriptError> {
    let (id, initial, max) = match ev.data {
        EventData::SemCreate { id, initial, max } => (id, initial, max),
        _ => return Err(ScriptError::WrongDataVariant),
    };
    let idx = id as usize;
    if id < 0 || idx >= dm.sems.len() {
        dm.rc = ReturnCode::Inval;
        return Ok(());
    }
    let s = &mut dm.sems[idx];
    s.valid = true;
    s.count = initial;
    s.max = max;
    s.waiters.clear();
    dm.rc = ReturnCode::Ok;
    Ok(())
}

/// Translates rtos_kernel.scxml lines 360-378 (transition event="sem.take").
pub fn script_sys_idle_sem_take_0(dm: &mut Datamodel, ev: &Event) -> Result<(), ScriptError> {
    let (sid, timeout) = match ev.data {
        EventData::SemOp { sid, timeout } => (sid, timeout),
        _ => return Err(ScriptError::WrongDataVariant),
    };
    let idx = sid as usize;
    if sid < 0 || idx >= dm.sems.len() || !dm.sems[idx].valid {
        dm.rc = ReturnCode::Inval;
        return Ok(());
    }
    if dm.sems[idx].count > 0 {
        dm.sems[idx].count -= 1;
        dm.rc = ReturnCode::Ok;
    } else if timeout == 0 {
        dm.rc = ReturnCode::Timeout;
    } else {
        let dl = if timeout < 0 {
            0
        } else {
            dm.tick_count + timeout
        };
        let cur = dm.current;
        if cur < 0 {
            return Err(ScriptError::BadState);
        }
        dm.waiters_insert(WaiterList::SemWaiters, idx, cur)?;
        dm.block_current(TaskState::BlkSem, sid, dl);
        // Final result delivered via tcb[current].msg at unblock.
        dm.rc = ReturnCode::Ok;
    }
    Ok(())
}

/// Translates rtos_kernel.scxml lines 381-398 (transition event="sem.give").
pub fn script_sys_idle_sem_give_0(dm: &mut Datamodel, ev: &Event) -> Result<(), ScriptError> {
    let sid = match ev.data {
        EventData::SemOp { sid, .. } => sid,
        _ => return Err(ScriptError::WrongDataVariant),
    };
    let idx = sid as usize;
    if sid < 0 || idx >= dm.sems.len() || !dm.sems[idx].valid {
        dm.rc = ReturnCode::Inval;
        return Ok(());
    }
    if !dm.sems[idx].waiters.is_empty() {
        let w = dm.sems[idx].waiters.remove(0);
        dm.tcb[w as usize].msg = Msg::ReturnCode(ReturnCode::Ok);
        dm.unblock(w)?;
        dm.rc = ReturnCode::Ok;
    } else if dm.sems[idx].count < dm.sems[idx].max {
        dm.sems[idx].count += 1;
        dm.rc = ReturnCode::Ok;
    } else {
        dm.rc = ReturnCode::Full;
    }
    Ok(())
}

/// Translates rtos_kernel.scxml lines 401-415 (transition event="sem.give_from_isr").
pub fn script_sys_idle_sem_give_from_isr_0(
    dm: &mut Datamodel,
    ev: &Event,
) -> Result<(), ScriptError> {
    let sid = match ev.data {
        EventData::SemOp { sid, .. } => sid,
        _ => return Err(ScriptError::WrongDataVariant),
    };
    let idx = sid as usize;
    if sid < 0 || idx >= dm.sems.len() {
        return Ok(());
    }
    if dm.sems[idx].valid {
        if !dm.sems[idx].waiters.is_empty() {
            let w = dm.sems[idx].waiters.remove(0);
            dm.tcb[w as usize].msg = Msg::ReturnCode(ReturnCode::Ok);
            dm.unblock(w)?;
        } else if dm.sems[idx].count < dm.sems[idx].max {
            dm.sems[idx].count += 1;
        }
    }
    Ok(())
}

/// Translates rtos_kernel.scxml lines 420-432 (transition event="queue.create").
pub fn script_sys_idle_queue_create_0(dm: &mut Datamodel, ev: &Event) -> Result<(), ScriptError> {
    let (id, cap) = match ev.data {
        EventData::QueueCreate { id, cap } => (id, cap),
        _ => return Err(ScriptError::WrongDataVariant),
    };
    let idx = id as usize;
    if id < 0 || idx >= dm.queues.len() {
        dm.rc = ReturnCode::Inval;
        return Ok(());
    }
    // Defensive: cap is bounded by Q_DEPTH (the buf's heapless capacity).
    if (cap as usize) > Q_DEPTH {
        dm.rc = ReturnCode::Inval;
        return Ok(());
    }
    let q = &mut dm.queues[idx];
    q.valid = true;
    q.cap = cap;
    q.buf.clear();
    q.count = 0;
    q.sendw.clear();
    q.recvw.clear();
    dm.rc = ReturnCode::Ok;
    Ok(())
}

/// Translates rtos_kernel.scxml lines 435-461 (transition event="queue.send").
pub fn script_sys_idle_queue_send_0(dm: &mut Datamodel, ev: &Event) -> Result<(), ScriptError> {
    let (qid, msg, timeout) = match ev.data {
        EventData::QueueSend { qid, msg, timeout } => (qid, msg, timeout),
        _ => return Err(ScriptError::WrongDataVariant),
    };
    let idx = qid as usize;
    if qid < 0 || idx >= dm.queues.len() || !dm.queues[idx].valid {
        dm.rc = ReturnCode::Inval;
        return Ok(());
    }
    if !dm.queues[idx].recvw.is_empty() {
        // Direct handoff: skip buffer
        let w = dm.queues[idx].recvw.remove(0);
        dm.tcb[w as usize].msg = Msg::Int(msg);
        dm.unblock(w)?;
        dm.rc = ReturnCode::Ok;
    } else if dm.queues[idx].count < dm.queues[idx].cap {
        dm.queues[idx]
            .buf
            .push(msg)
            .map_err(|_| ScriptError::QueueBufferFull)?;
        dm.queues[idx].count += 1;
        dm.rc = ReturnCode::Ok;
    } else if timeout == 0 {
        dm.rc = ReturnCode::Full;
    } else {
        let dl = if timeout < 0 {
            0
        } else {
            dm.tick_count + timeout
        };
        let cur = dm.current;
        if cur < 0 {
            return Err(ScriptError::BadState);
        }
        // Pending payload deposited on the current task's msg slot.
        dm.tcb[cur as usize].msg = Msg::Int(msg);
        dm.waiters_insert(WaiterList::QueueSendW, idx, cur)?;
        dm.block_current(TaskState::BlkQs, qid, dl);
        dm.rc = ReturnCode::Ok;
    }
    Ok(())
}

/// Translates rtos_kernel.scxml lines 464-499 (transition event="queue.receive").
pub fn script_sys_idle_queue_receive_0(dm: &mut Datamodel, ev: &Event) -> Result<(), ScriptError> {
    let (qid, timeout) = match ev.data {
        EventData::QueueReceive { qid, timeout } => (qid, timeout),
        _ => return Err(ScriptError::WrongDataVariant),
    };
    let idx = qid as usize;
    if qid < 0 || idx >= dm.queues.len() || !dm.queues[idx].valid {
        dm.rc = ReturnCode::Inval;
        return Ok(());
    }
    if dm.queues[idx].count > 0 {
        let m = dm.queues[idx].buf.remove(0);
        dm.queues[idx].count -= 1;
        let cur = dm.current;
        if cur < 0 {
            return Err(ScriptError::BadState);
        }
        dm.tcb[cur as usize].msg = Msg::Int(m);
        // Pull from blocked sender if any (buffered case).
        if !dm.queues[idx].sendw.is_empty() {
            let w = dm.queues[idx].sendw.remove(0);
            // Recover the sender's pending payload from its msg slot.
            let pending = match dm.tcb[w as usize].msg {
                Msg::Int(v) => v,
                _ => return Err(ScriptError::BadState),
            };
            dm.queues[idx]
                .buf
                .push(pending)
                .map_err(|_| ScriptError::QueueBufferFull)?;
            dm.queues[idx].count += 1;
            dm.tcb[w as usize].msg = Msg::ReturnCode(ReturnCode::Ok);
            dm.unblock(w)?;
        }
        dm.rc = ReturnCode::Ok;
    } else if !dm.queues[idx].sendw.is_empty() {
        // Zero-capacity or contended path: direct handoff.
        let w = dm.queues[idx].sendw.remove(0);
        let cur = dm.current;
        if cur < 0 {
            return Err(ScriptError::BadState);
        }
        let pending = match dm.tcb[w as usize].msg {
            Msg::Int(v) => v,
            _ => return Err(ScriptError::BadState),
        };
        dm.tcb[cur as usize].msg = Msg::Int(pending);
        dm.tcb[w as usize].msg = Msg::ReturnCode(ReturnCode::Ok);
        dm.unblock(w)?;
        dm.rc = ReturnCode::Ok;
    } else if timeout == 0 {
        dm.rc = ReturnCode::Empty;
    } else {
        let dl = if timeout < 0 {
            0
        } else {
            dm.tick_count + timeout
        };
        let cur = dm.current;
        if cur < 0 {
            return Err(ScriptError::BadState);
        }
        dm.waiters_insert(WaiterList::QueueRecvW, idx, cur)?;
        dm.block_current(TaskState::BlkQr, qid, dl);
        dm.rc = ReturnCode::Ok;
    }
    Ok(())
}

/// Translates rtos_kernel.scxml lines 502-518 (transition event="queue.send_from_isr").
pub fn script_sys_idle_queue_send_from_isr_0(
    dm: &mut Datamodel,
    ev: &Event,
) -> Result<(), ScriptError> {
    let (qid, msg) = match ev.data {
        EventData::QueueSend { qid, msg, .. } => (qid, msg),
        _ => return Err(ScriptError::WrongDataVariant),
    };
    let idx = qid as usize;
    if qid < 0 || idx >= dm.queues.len() {
        return Ok(());
    }
    if dm.queues[idx].valid {
        if !dm.queues[idx].recvw.is_empty() {
            let w = dm.queues[idx].recvw.remove(0);
            dm.tcb[w as usize].msg = Msg::Int(msg);
            dm.unblock(w)?;
        } else if dm.queues[idx].count < dm.queues[idx].cap {
            dm.queues[idx]
                .buf
                .push(msg)
                .map_err(|_| ScriptError::QueueBufferFull)?;
            dm.queues[idx].count += 1;
        }
    }
    Ok(())
}

/// Translates rtos_kernel.scxml lines 532-534 (transition event="crit.enter").
pub fn script_prot_idle_crit_enter_0(dm: &mut Datamodel, _ev: &Event) -> Result<(), ScriptError> {
    dm.irq_nest += 1;
    Ok(())
}

/// Translates rtos_kernel.scxml lines 536-541 (transition event="crit.exit").
pub fn script_prot_idle_crit_exit_0(dm: &mut Datamodel, _ev: &Event) -> Result<(), ScriptError> {
    if dm.irq_nest > 0 {
        dm.irq_nest -= 1;
    }
    Ok(())
}

/// Translates rtos_kernel.scxml lines 543-545 (transition event="sched.suspend").
pub fn script_prot_idle_sched_suspend_0(
    dm: &mut Datamodel,
    _ev: &Event,
) -> Result<(), ScriptError> {
    dm.sched_lock += 1;
    Ok(())
}

/// Translates rtos_kernel.scxml lines 547-573 (transition event="sched.resume").
///
/// Catch-up tick replay loop. When `sched_lock` reaches zero and ticks
/// were deferred, flush them: replay deadline checks for each pending
/// tick, expiring delays and timing out blocked waiters per the chart's
/// nested loop.
pub fn script_prot_idle_sched_resume_0(dm: &mut Datamodel, _ev: &Event) -> Result<(), ScriptError> {
    if dm.sched_lock > 0 {
        dm.sched_lock -= 1;
    }
    if dm.sched_lock == 0 && dm.pend_ticks > 0 {
        while dm.pend_ticks > 0 {
            dm.pend_ticks -= 1;
            dm.tick_count += 1;
            let n = dm.max_tasks;
            for i in 0..n {
                let (state, deadline) = {
                    let t = &dm.tcb[i];
                    (t.state, t.deadline)
                };
                if state == TaskState::Delay && deadline <= dm.tick_count {
                    dm.tcb[i].msg = Msg::ReturnCode(ReturnCode::Ok);
                    dm.unblock(i as TaskId)?;
                } else {
                    let is_blocked = matches!(
                        state,
                        TaskState::BlkSem | TaskState::BlkQs | TaskState::BlkQr
                    );
                    if is_blocked && deadline > 0 && deadline <= dm.tick_count {
                        dm.waiter_cancel(i as TaskId);
                        dm.tcb[i].msg = Msg::ReturnCode(ReturnCode::Timeout);
                        dm.unblock(i as TaskId)?;
                    }
                }
            }
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Dispatcher — typed name → script-body table.
//
// Mirrors sim's `HandCompiledScripts::run_script` but the firmware doesn't
// take a string key. The dispatcher pattern-matches on [`EventName`] and
// runs the corresponding `script_*` body. Per SOS-04 §6.5 macrostep
// semantics, if a state-mutating script sets `dm.resched = true`, the
// dispatcher then runs `script_sched_idle_sched_run_0` to perform the
// scheduler microstep — keeping parity with sim's harness which raises
// `sched.run` after each state-mutating transition.
// ---------------------------------------------------------------------------

/// Dispatch one [`Event`] against `dm`. Runs the per-event script body
/// and, if it requests a reschedule, runs the scheduler microstep
/// (mirroring sim's macrostep semantics).
///
/// Returns `Ok(())` on success; surface-level errors (wrong payload
/// variant, capacity exhaustion against a chart invariant) come back as
/// [`ScriptError`]. The dispatcher does NOT swallow them — the caller
/// (transport / mode loop) is responsible for emitting the corresponding
/// trace record and deciding whether to continue.
pub fn dispatch_event(dm: &mut Datamodel, event: &Event) -> Result<(), ScriptError> {
    match event.name {
        EventName::TaskCreate => script_sys_idle_task_create_0(dm, event)?,
        EventName::TaskDelay => script_sys_idle_task_delay_0(dm, event)?,
        EventName::TaskYield => script_sys_idle_task_yield_0(dm, event)?,
        EventName::TaskSuspend => script_sys_idle_task_suspend_0(dm, event)?,
        EventName::TaskResume => script_sys_idle_task_resume_0(dm, event)?,
        EventName::SemCreate => script_sys_idle_sem_create_0(dm, event)?,
        EventName::SemTake => script_sys_idle_sem_take_0(dm, event)?,
        EventName::SemGive => script_sys_idle_sem_give_0(dm, event)?,
        EventName::SemGiveFromIsr => script_sys_idle_sem_give_from_isr_0(dm, event)?,
        EventName::QueueCreate => script_sys_idle_queue_create_0(dm, event)?,
        EventName::QueueSend => script_sys_idle_queue_send_0(dm, event)?,
        EventName::QueueReceive => script_sys_idle_queue_receive_0(dm, event)?,
        EventName::QueueSendFromIsr => script_sys_idle_queue_send_from_isr_0(dm, event)?,
        EventName::SysTick => script_tick_idle_sys_tick_0(dm, event)?,
        EventName::CritEnter => script_prot_idle_crit_enter_0(dm, event)?,
        EventName::CritExit => script_prot_idle_crit_exit_0(dm, event)?,
        EventName::SchedSuspend => script_prot_idle_sched_suspend_0(dm, event)?,
        EventName::SchedResume => script_prot_idle_sched_resume_0(dm, event)?,
    }

    // Macrostep: if the per-event script raised `resched`, run the
    // scheduler microstep now. Mirrors the chart's `<raise event="sched.run"/>`
    // pattern at the end of every state-mutating transition; sim's harness
    // performs the same dispatch after every external-event step.
    if dm.resched {
        script_sched_idle_sched_run_0(dm, event)?;
    }

    Ok(())
}
