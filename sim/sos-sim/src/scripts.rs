//! Hand-compiled `<script>` bodies. See SOS-02 §6.3 (script-name table)
//! and PCDN-SOS-00-005 → (b) (hand-compilation as the v1 bootstrap).
//!
//! Each transition's `<script>` block from `rtos_kernel.scxml` is
//! translated 1:1 into a `script_<state>_<event>_<index>` free function
//! below. Helpers from the chart's top-level `<script>` block (lines
//! 77-165) are realised as `impl Datamodel { ... }` methods, mirroring
//! SOS-02 §6.3 row 1 of the naming table.
//!
//! The transpilation follows SOS-02 §6.3 mapping rules; see each fn's
//! doc-comment for the `.scxml` line range it mirrors.

use serde_json::Value;

use crate::datamodel::{Datamodel, Msg, ReturnCode, TaskId, TaskState};
use crate::error::SimError;
use crate::event::{Event, EventName};
use crate::script_provider::ScriptProvider;

// ---------------------------------------------------------------------------
// Helper extractors for `_event.data` payloads.
// ---------------------------------------------------------------------------

/// Read a numeric field out of `ev.data` as `i64`. Returns a
/// `SimError::Runtime` if the field is missing or not numeric.
fn arg_i64(ev: &Event, key: &str) -> Result<i64, SimError> {
    ev.data
        .get(key)
        .and_then(Value::as_i64)
        .ok_or_else(|| SimError::Runtime(format!("missing/invalid i64 field: {key}")))
}

/// Read a numeric field out of `ev.data` as `usize`. Negative or missing
/// values are rejected.
fn arg_usize(ev: &Event, key: &str) -> Result<usize, SimError> {
    let v = arg_i64(ev, key)?;
    if v < 0 {
        Err(SimError::Runtime(format!(
            "field {key} must be non-negative (got {v})"
        )))
    } else {
        Ok(v as usize)
    }
}

/// Read a numeric field out of `ev.data` as `u8`. Used for `prio`.
fn arg_u8(ev: &Event, key: &str) -> Result<u8, SimError> {
    let v = arg_i64(ev, key)?;
    if !(0..=u8::MAX as i64).contains(&v) {
        Err(SimError::Runtime(format!(
            "field {key} must fit in u8 (got {v})"
        )))
    } else {
        Ok(v as u8)
    }
}

/// Read a numeric field out of `ev.data` as `u32`. Used for sem `initial`
/// and `max`, and queue `cap`.
fn arg_u32(ev: &Event, key: &str) -> Result<u32, SimError> {
    let v = arg_i64(ev, key)?;
    if !(0..=u32::MAX as i64).contains(&v) {
        Err(SimError::Runtime(format!(
            "field {key} must fit in u32 (got {v})"
        )))
    } else {
        Ok(v as u32)
    }
}

// ---------------------------------------------------------------------------
// Helper methods on Datamodel — translation of the chart's HELPERS block
// (rtos_kernel.scxml lines 77-165).
// ---------------------------------------------------------------------------

impl Datamodel {
    /// Translates `ready_push` (rtos_kernel.scxml lines 86-89).
    ///
    /// Push `tid` onto the tail of its priority queue and mark READY.
    fn ready_push(&mut self, tid: TaskId) {
        let p = self.tcb[tid as usize].prio as usize;
        self.ready[p].push(tid);
        self.tcb[tid as usize].state = TaskState::Ready;
    }

    /// Translates `ready_remove` (rtos_kernel.scxml lines 92-96).
    ///
    /// Remove `tid` from its priority queue (no-op if absent).
    fn ready_remove(&mut self, tid: TaskId) {
        let p = self.tcb[tid as usize].prio as usize;
        if let Some(idx) = self.ready[p].iter().position(|&v| v == tid) {
            self.ready[p].remove(idx);
        }
    }

    /// Translates `ready_pop_highest` (rtos_kernel.scxml lines 99-104).
    ///
    /// Pop highest-priority ready task (FIFO within priority); returns
    /// `-1` if no task is ready.
    fn ready_pop_highest(&mut self) -> TaskId {
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
    /// Insert `tid` into `arr` ordered by priority descending, FIFO
    /// within priority. The chart walks `arr` while
    /// `tcb[arr[i]].prio >= p` — we mirror that bound check faithfully.
    fn waiters_insert(&mut self, kind: WaiterList, obj: usize, tid: TaskId) {
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
        self.waiter_arr_mut(kind, obj).insert(i, tid);
    }

    /// Translates `block_current` (rtos_kernel.scxml lines 117-123).
    fn block_current(&mut self, state: TaskState, obj_id: i16, deadline: i64) {
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
    fn unblock(&mut self, tid: TaskId) {
        self.tcb[tid as usize].deadline = 0;
        self.tcb[tid as usize].blk_obj = -1;
        self.ready_push(tid);
        self.resched = true;
    }

    /// Translates `waiter_cancel` (rtos_kernel.scxml lines 135-145).
    ///
    /// Cancel `tid`'s waiter slot when timing out; the list is inferred
    /// from the task's blocked state.
    fn waiter_cancel(&mut self, tid: TaskId) {
        let state = self.tcb[tid as usize].state;
        let obj = self.tcb[tid as usize].blk_obj;
        if obj < 0 {
            return;
        }
        let obj = obj as usize;
        let lst: Option<&mut Vec<TaskId>> = match state {
            TaskState::BlkSem => self.sems.get_mut(obj).map(|s| &mut s.waiters),
            TaskState::BlkQs => self.queues.get_mut(obj).map(|q| &mut q.sendw),
            TaskState::BlkQr => self.queues.get_mut(obj).map(|q| &mut q.recvw),
            _ => None,
        };
        if let Some(lst) = lst {
            if let Some(i) = lst.iter().position(|&v| v == tid) {
                lst.remove(i);
            }
        }
    }

    /// Translates `pick_next` (rtos_kernel.scxml lines 149-163).
    ///
    /// Scheduler step: if a higher-priority READY task exists, switch.
    /// Round-robin within priority: re-queue current at tail before pop.
    fn pick_next(&mut self) {
        if self.current >= 0 {
            let cur = self.current as usize;
            if self.tcb[cur].state == TaskState::Running {
                self.tcb[cur].state = TaskState::Ready;
                let p = self.tcb[cur].prio as usize;
                let id = self.tcb[cur].id;
                self.ready[p].push(id);
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
    }

    // -- helper-of-helpers: typed view into one of the three waiter lists --

    fn waiter_arr(&self, kind: WaiterList, obj: usize) -> &[TaskId] {
        match kind {
            WaiterList::SemWaiters => &self.sems[obj].waiters,
            WaiterList::QueueSendW => &self.queues[obj].sendw,
            WaiterList::QueueRecvW => &self.queues[obj].recvw,
        }
    }

    fn waiter_arr_mut(&mut self, kind: WaiterList, obj: usize) -> &mut Vec<TaskId> {
        match kind {
            WaiterList::SemWaiters => &mut self.sems[obj].waiters,
            WaiterList::QueueSendW => &mut self.queues[obj].sendw,
            WaiterList::QueueRecvW => &mut self.queues[obj].recvw,
        }
    }
}

/// Discriminator for the three waiter lists the chart maintains.
#[derive(Copy, Clone, Debug)]
enum WaiterList {
    SemWaiters,
    QueueSendW,
    QueueRecvW,
}

// ---------------------------------------------------------------------------
// Transition script bodies. Order follows the .scxml document order.
// ---------------------------------------------------------------------------

/// Translates rtos_kernel.scxml lines 172-192 (boot onentry).
///
/// Mirrors the chart's `<boot>/<onentry>` block. Note: `Datamodel::new`
/// already pre-populates the pools and parks idle at RUNNING (it mirrors
/// the static result of the chart's `pick_next()` at boot). This script
/// is therefore an idempotent re-init: it zeroes `resched` and ensures
/// the same invariants hold if the caller invokes it explicitly.
pub fn script_boot_onentry_0(dm: &mut Datamodel, _ev: &Event) {
    // readyq_init(): one empty FIFO per priority.
    dm.ready.clear();
    for _ in 0..dm.max_prio {
        dm.ready.push(Vec::new());
    }

    // Allocate TCB pool; idle reserved at prio 0.
    dm.tcb.clear();
    for i in 0..dm.max_tasks {
        dm.tcb.push(crate::datamodel::Tcb {
            id: i as TaskId,
            prio: 0,
            state: TaskState::Dormant,
            deadline: 0,
            blk_obj: -1,
            msg: Msg::Null,
        });
    }
    dm.tcb[0].prio = 0;
    dm.ready_push(0);

    // Sem and queue pools as invalid descriptors.
    dm.sems.clear();
    for _ in 0..dm.max_sems {
        dm.sems.push(crate::datamodel::Sem {
            valid: false,
            count: 0,
            max: 0,
            waiters: Vec::new(),
        });
    }
    dm.queues.clear();
    for _ in 0..dm.max_queues {
        dm.queues.push(crate::datamodel::Queue {
            valid: false,
            buf: Vec::new(),
            cap: 0,
            count: 0,
            sendw: Vec::new(),
            recvw: Vec::new(),
        });
    }

    // Bring idle to RUNNING.
    dm.pick_next();
}

/// Translates rtos_kernel.scxml lines 210-212 (sched_idle / sched.run).
///
/// `<transition event="sched.run" cond="sched_lock == 0">` — only the
/// cond-true arm carries a script; the harness owns predicate dispatch.
pub fn script_sched_idle_sched_run_0(dm: &mut Datamodel, _ev: &Event) {
    dm.pick_next();
}

/// Translates rtos_kernel.scxml lines 225-252 (tick_idle / sys.tick).
pub fn script_tick_idle_sys_tick_0(dm: &mut Datamodel, _ev: &Event) {
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
                dm.unblock(i as TaskId);
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
                dm.unblock(i as TaskId);
            }
        }
    }
}

/// Translates rtos_kernel.scxml lines 270-286 (transition event="task.create").
pub fn script_sys_idle_task_create_0(dm: &mut Datamodel, ev: &Event) -> Result<(), SimError> {
    let id = arg_usize(ev, "id")?;
    let prio = arg_u8(ev, "prio")?;
    if id >= dm.tcb.len() {
        dm.rc = ReturnCode::Inval;
        return Ok(());
    }
    if dm.tcb[id].state != TaskState::Dormant {
        dm.rc = ReturnCode::Inval;
    } else {
        dm.tcb[id].prio = prio;
        dm.tcb[id].deadline = 0;
        dm.tcb[id].blk_obj = -1;
        dm.tcb[id].msg = Msg::Null;
        dm.ready_push(id as TaskId);
        dm.resched = true;
        dm.rc = ReturnCode::Ok;
    }
    Ok(())
}

/// Translates rtos_kernel.scxml lines 289-300 (transition event="task.delay").
pub fn script_sys_idle_task_delay_0(dm: &mut Datamodel, ev: &Event) -> Result<(), SimError> {
    let n = arg_i64(ev, "ticks")?;
    if n > 0 {
        dm.block_current(TaskState::Delay, -1, dm.tick_count + n);
    } else {
        dm.resched = true;
    }
    dm.rc = ReturnCode::Ok;
    Ok(())
}

/// Translates rtos_kernel.scxml lines 302-305 (transition event="task.yield").
pub fn script_sys_idle_task_yield_0(dm: &mut Datamodel, _ev: &Event) {
    dm.resched = true;
    dm.rc = ReturnCode::Ok;
}

/// Translates rtos_kernel.scxml lines 308-326 (transition event="task.suspend").
pub fn script_sys_idle_task_suspend_0(dm: &mut Datamodel, ev: &Event) -> Result<(), SimError> {
    let id = arg_usize(ev, "id")?;
    if id >= dm.tcb.len() {
        dm.rc = ReturnCode::Inval;
        return Ok(());
    }
    let s = dm.tcb[id].state;
    if s == TaskState::Ready {
        dm.ready_remove(id as TaskId);
        dm.tcb[id].state = TaskState::Suspend;
        dm.rc = ReturnCode::Ok;
    } else if s == TaskState::Running {
        dm.tcb[id].state = TaskState::Suspend;
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
pub fn script_sys_idle_task_resume_0(dm: &mut Datamodel, ev: &Event) -> Result<(), SimError> {
    let id = arg_usize(ev, "id")?;
    if id >= dm.tcb.len() {
        dm.rc = ReturnCode::Inval;
        return Ok(());
    }
    if dm.tcb[id].state == TaskState::Suspend {
        dm.ready_push(id as TaskId);
        dm.resched = true;
        dm.rc = ReturnCode::Ok;
    } else {
        dm.rc = ReturnCode::Inval;
    }
    Ok(())
}

/// Translates rtos_kernel.scxml lines 346-356 (transition event="sem.create").
pub fn script_sys_idle_sem_create_0(dm: &mut Datamodel, ev: &Event) -> Result<(), SimError> {
    let id = arg_usize(ev, "id")?;
    let initial = arg_u32(ev, "initial")?;
    let maxv = arg_u32(ev, "max")?;
    if id >= dm.sems.len() {
        dm.rc = ReturnCode::Inval;
        return Ok(());
    }
    let s = &mut dm.sems[id];
    s.valid = true;
    s.count = initial;
    s.max = maxv;
    s.waiters = Vec::new();
    dm.rc = ReturnCode::Ok;
    Ok(())
}

/// Translates rtos_kernel.scxml lines 360-378 (transition event="sem.take").
pub fn script_sys_idle_sem_take_0(dm: &mut Datamodel, ev: &Event) -> Result<(), SimError> {
    let sid = arg_usize(ev, "sid")?;
    let timeout = arg_i64(ev, "timeout")?;
    if sid >= dm.sems.len() || !dm.sems[sid].valid {
        dm.rc = ReturnCode::Inval;
        return Ok(());
    }
    if dm.sems[sid].count > 0 {
        dm.sems[sid].count -= 1;
        dm.rc = ReturnCode::Ok;
    } else if timeout == 0 {
        dm.rc = ReturnCode::Timeout;
    } else {
        let dl = if timeout < 0 { 0 } else { dm.tick_count + timeout };
        let cur = dm.current;
        if cur < 0 {
            return Err(SimError::Runtime(
                "sem.take with no current task".to_string(),
            ));
        }
        dm.waiters_insert(WaiterList::SemWaiters, sid, cur);
        dm.block_current(TaskState::BlkSem, sid as i16, dl);
        // Final result delivered via tcb[current].msg at unblock.
        dm.rc = ReturnCode::Ok;
    }
    Ok(())
}

/// Translates rtos_kernel.scxml lines 381-398 (transition event="sem.give").
pub fn script_sys_idle_sem_give_0(dm: &mut Datamodel, ev: &Event) -> Result<(), SimError> {
    let sid = arg_usize(ev, "sid")?;
    if sid >= dm.sems.len() || !dm.sems[sid].valid {
        dm.rc = ReturnCode::Inval;
        return Ok(());
    }
    if !dm.sems[sid].waiters.is_empty() {
        let w = dm.sems[sid].waiters.remove(0);
        dm.tcb[w as usize].msg = Msg::ReturnCode(ReturnCode::Ok);
        dm.unblock(w);
        dm.rc = ReturnCode::Ok;
    } else if dm.sems[sid].count < dm.sems[sid].max {
        dm.sems[sid].count += 1;
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
) -> Result<(), SimError> {
    let sid = arg_usize(ev, "sid")?;
    if sid >= dm.sems.len() {
        return Ok(());
    }
    if dm.sems[sid].valid {
        if !dm.sems[sid].waiters.is_empty() {
            let w = dm.sems[sid].waiters.remove(0);
            dm.tcb[w as usize].msg = Msg::ReturnCode(ReturnCode::Ok);
            dm.unblock(w);
        } else if dm.sems[sid].count < dm.sems[sid].max {
            dm.sems[sid].count += 1;
        }
    }
    Ok(())
}

/// Translates rtos_kernel.scxml lines 420-432 (transition event="queue.create").
pub fn script_sys_idle_queue_create_0(dm: &mut Datamodel, ev: &Event) -> Result<(), SimError> {
    let id = arg_usize(ev, "id")?;
    let cap = arg_u32(ev, "cap")?;
    if id >= dm.queues.len() {
        dm.rc = ReturnCode::Inval;
        return Ok(());
    }
    let q = &mut dm.queues[id];
    q.valid = true;
    q.cap = cap;
    q.buf = Vec::new();
    q.count = 0;
    q.sendw = Vec::new();
    q.recvw = Vec::new();
    dm.rc = ReturnCode::Ok;
    Ok(())
}

/// Translates rtos_kernel.scxml lines 435-461 (transition event="queue.send").
pub fn script_sys_idle_queue_send_0(dm: &mut Datamodel, ev: &Event) -> Result<(), SimError> {
    let qid = arg_usize(ev, "qid")?;
    let msg = arg_i64(ev, "msg")?;
    let timeout = arg_i64(ev, "timeout")?;
    if qid >= dm.queues.len() || !dm.queues[qid].valid {
        dm.rc = ReturnCode::Inval;
        return Ok(());
    }
    if !dm.queues[qid].recvw.is_empty() {
        // Direct handoff: skip buffer
        let w = dm.queues[qid].recvw.remove(0);
        dm.tcb[w as usize].msg = Msg::Int(msg);
        dm.unblock(w);
        dm.rc = ReturnCode::Ok;
    } else if dm.queues[qid].count < dm.queues[qid].cap {
        dm.queues[qid].buf.push(msg);
        dm.queues[qid].count += 1;
        dm.rc = ReturnCode::Ok;
    } else if timeout == 0 {
        dm.rc = ReturnCode::Full;
    } else {
        let dl = if timeout < 0 { 0 } else { dm.tick_count + timeout };
        let cur = dm.current;
        if cur < 0 {
            return Err(SimError::Runtime(
                "queue.send with no current task".to_string(),
            ));
        }
        // Pending payload deposited on the current task's msg slot.
        dm.tcb[cur as usize].msg = Msg::Int(msg);
        dm.waiters_insert(WaiterList::QueueSendW, qid, cur);
        dm.block_current(TaskState::BlkQs, qid as i16, dl);
        dm.rc = ReturnCode::Ok;
    }
    Ok(())
}

/// Translates rtos_kernel.scxml lines 464-499 (transition event="queue.receive").
pub fn script_sys_idle_queue_receive_0(dm: &mut Datamodel, ev: &Event) -> Result<(), SimError> {
    let qid = arg_usize(ev, "qid")?;
    let timeout = arg_i64(ev, "timeout")?;
    if qid >= dm.queues.len() || !dm.queues[qid].valid {
        dm.rc = ReturnCode::Inval;
        return Ok(());
    }
    if dm.queues[qid].count > 0 {
        let m = dm.queues[qid].buf.remove(0);
        dm.queues[qid].count -= 1;
        let cur = dm.current;
        if cur < 0 {
            return Err(SimError::Runtime(
                "queue.receive with no current task".to_string(),
            ));
        }
        dm.tcb[cur as usize].msg = Msg::Int(m);
        // Pull from blocked sender if any (buffered case).
        if !dm.queues[qid].sendw.is_empty() {
            let w = dm.queues[qid].sendw.remove(0);
            // Recover the sender's pending payload from its msg slot.
            let pending = match dm.tcb[w as usize].msg {
                Msg::Int(v) => v,
                _ => {
                    return Err(SimError::Runtime(
                        "queue.receive: blocked sender had no pending Msg::Int payload"
                            .to_string(),
                    ))
                }
            };
            dm.queues[qid].buf.push(pending);
            dm.queues[qid].count += 1;
            dm.tcb[w as usize].msg = Msg::ReturnCode(ReturnCode::Ok);
            dm.unblock(w);
        }
        dm.rc = ReturnCode::Ok;
    } else if !dm.queues[qid].sendw.is_empty() {
        // Zero-capacity or contended path: direct handoff.
        let w = dm.queues[qid].sendw.remove(0);
        let cur = dm.current;
        if cur < 0 {
            return Err(SimError::Runtime(
                "queue.receive (handoff) with no current task".to_string(),
            ));
        }
        let pending = match dm.tcb[w as usize].msg {
            Msg::Int(v) => v,
            _ => {
                return Err(SimError::Runtime(
                    "queue.receive: blocked sender had no pending Msg::Int payload".to_string(),
                ))
            }
        };
        dm.tcb[cur as usize].msg = Msg::Int(pending);
        dm.tcb[w as usize].msg = Msg::ReturnCode(ReturnCode::Ok);
        dm.unblock(w);
        dm.rc = ReturnCode::Ok;
    } else if timeout == 0 {
        dm.rc = ReturnCode::Empty;
    } else {
        let dl = if timeout < 0 { 0 } else { dm.tick_count + timeout };
        let cur = dm.current;
        if cur < 0 {
            return Err(SimError::Runtime(
                "queue.receive with no current task".to_string(),
            ));
        }
        dm.waiters_insert(WaiterList::QueueRecvW, qid, cur);
        dm.block_current(TaskState::BlkQr, qid as i16, dl);
        dm.rc = ReturnCode::Ok;
    }
    Ok(())
}

/// Translates rtos_kernel.scxml lines 502-518 (transition event="queue.send_from_isr").
pub fn script_sys_idle_queue_send_from_isr_0(
    dm: &mut Datamodel,
    ev: &Event,
) -> Result<(), SimError> {
    let qid = arg_usize(ev, "qid")?;
    let msg = arg_i64(ev, "msg")?;
    if qid >= dm.queues.len() {
        return Ok(());
    }
    if dm.queues[qid].valid {
        if !dm.queues[qid].recvw.is_empty() {
            let w = dm.queues[qid].recvw.remove(0);
            dm.tcb[w as usize].msg = Msg::Int(msg);
            dm.unblock(w);
        } else if dm.queues[qid].count < dm.queues[qid].cap {
            dm.queues[qid].buf.push(msg);
            dm.queues[qid].count += 1;
        }
    }
    Ok(())
}

/// Translates rtos_kernel.scxml lines 532-534 (transition event="crit.enter").
pub fn script_prot_idle_crit_enter_0(dm: &mut Datamodel, _ev: &Event) {
    dm.irq_nest += 1;
}

/// Translates rtos_kernel.scxml lines 536-541 (transition event="crit.exit").
pub fn script_prot_idle_crit_exit_0(dm: &mut Datamodel, _ev: &Event) {
    if dm.irq_nest > 0 {
        dm.irq_nest -= 1;
    }
}

/// Translates rtos_kernel.scxml lines 543-545 (transition event="sched.suspend").
pub fn script_prot_idle_sched_suspend_0(dm: &mut Datamodel, _ev: &Event) {
    dm.sched_lock += 1;
}

/// Translates rtos_kernel.scxml lines 547-573 (transition event="sched.resume").
///
/// Catch-up tick replay loop. When `sched_lock` reaches zero and ticks
/// were deferred, flush them: replay deadline checks for each pending
/// tick, expiring delays and timing out blocked waiters per the chart's
/// nested loop.
pub fn script_prot_idle_sched_resume_0(dm: &mut Datamodel, _ev: &Event) {
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
                    dm.unblock(i as TaskId);
                } else {
                    let is_blocked = matches!(
                        state,
                        TaskState::BlkSem | TaskState::BlkQs | TaskState::BlkQr
                    );
                    if is_blocked && deadline > 0 && deadline <= dm.tick_count {
                        dm.waiter_cancel(i as TaskId);
                        dm.tcb[i].msg = Msg::ReturnCode(ReturnCode::Timeout);
                        dm.unblock(i as TaskId);
                    }
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// ScriptProvider impl — canonical name dispatch.
// ---------------------------------------------------------------------------

/// The v1 reference `ScriptProvider` — a static dispatch table from
/// canonical script-name (per SOS-02 §6.3) to a hand-compiled Rust
/// function body. Zero-sized.
#[derive(Debug, Default, Clone, Copy)]
pub struct HandCompiledScripts;

impl HandCompiledScripts {
    /// Construct a fresh `HandCompiledScripts`. Equivalent to
    /// `HandCompiledScripts::default()`.
    pub fn new() -> Self {
        HandCompiledScripts
    }
}

/// Resolve a possibly-short script alias to the canonical SOS-02 §6.3
/// name. Used by the dispatcher so callers MAY use either form. The
/// canonical names always win — the alias table is additive and
/// covers the event-name suffix in case the harness wants a shorter key.
fn canonical_name(name: &str) -> &str {
    match name {
        // Short aliases mirroring the event-name without the state prefix.
        "script_boot_onentry" => "script_boot_onentry_0",
        "script_sched_run" => "script_sched_idle_sched_run_0",
        "script_sys_tick" => "script_tick_idle_sys_tick_0",
        "script_task_create" => "script_sys_idle_task_create_0",
        "script_task_delay" => "script_sys_idle_task_delay_0",
        "script_task_yield" => "script_sys_idle_task_yield_0",
        "script_task_suspend" => "script_sys_idle_task_suspend_0",
        "script_task_resume" => "script_sys_idle_task_resume_0",
        "script_sem_create" => "script_sys_idle_sem_create_0",
        "script_sem_take" => "script_sys_idle_sem_take_0",
        "script_sem_give" => "script_sys_idle_sem_give_0",
        "script_sem_give_from_isr" => "script_sys_idle_sem_give_from_isr_0",
        "script_queue_create" => "script_sys_idle_queue_create_0",
        "script_queue_send" => "script_sys_idle_queue_send_0",
        "script_queue_receive" => "script_sys_idle_queue_receive_0",
        "script_queue_send_from_isr" => "script_sys_idle_queue_send_from_isr_0",
        "script_crit_enter" => "script_prot_idle_crit_enter_0",
        "script_crit_exit" => "script_prot_idle_crit_exit_0",
        "script_sched_suspend" => "script_prot_idle_sched_suspend_0",
        "script_sched_resume" => "script_prot_idle_sched_resume_0",
        other => other,
    }
}

impl ScriptProvider for HandCompiledScripts {
    fn run_script(
        &self,
        name: &str,
        dm: &mut Datamodel,
        ev: &Event,
    ) -> Result<(), SimError> {
        match canonical_name(name) {
            "script_boot_onentry_0" => {
                script_boot_onentry_0(dm, ev);
                Ok(())
            }
            "script_sched_idle_sched_run_0" => {
                script_sched_idle_sched_run_0(dm, ev);
                Ok(())
            }
            "script_tick_idle_sys_tick_0" => {
                script_tick_idle_sys_tick_0(dm, ev);
                Ok(())
            }
            "script_sys_idle_task_create_0" => script_sys_idle_task_create_0(dm, ev),
            "script_sys_idle_task_delay_0" => script_sys_idle_task_delay_0(dm, ev),
            "script_sys_idle_task_yield_0" => {
                script_sys_idle_task_yield_0(dm, ev);
                Ok(())
            }
            "script_sys_idle_task_suspend_0" => script_sys_idle_task_suspend_0(dm, ev),
            "script_sys_idle_task_resume_0" => script_sys_idle_task_resume_0(dm, ev),
            "script_sys_idle_sem_create_0" => script_sys_idle_sem_create_0(dm, ev),
            "script_sys_idle_sem_take_0" => script_sys_idle_sem_take_0(dm, ev),
            "script_sys_idle_sem_give_0" => script_sys_idle_sem_give_0(dm, ev),
            "script_sys_idle_sem_give_from_isr_0" => {
                script_sys_idle_sem_give_from_isr_0(dm, ev)
            }
            "script_sys_idle_queue_create_0" => script_sys_idle_queue_create_0(dm, ev),
            "script_sys_idle_queue_send_0" => script_sys_idle_queue_send_0(dm, ev),
            "script_sys_idle_queue_receive_0" => script_sys_idle_queue_receive_0(dm, ev),
            "script_sys_idle_queue_send_from_isr_0" => {
                script_sys_idle_queue_send_from_isr_0(dm, ev)
            }
            "script_prot_idle_crit_enter_0" => {
                script_prot_idle_crit_enter_0(dm, ev);
                Ok(())
            }
            "script_prot_idle_crit_exit_0" => {
                script_prot_idle_crit_exit_0(dm, ev);
                Ok(())
            }
            "script_prot_idle_sched_suspend_0" => {
                script_prot_idle_sched_suspend_0(dm, ev);
                Ok(())
            }
            "script_prot_idle_sched_resume_0" => {
                script_prot_idle_sched_resume_0(dm, ev);
                Ok(())
            }
            other => Err(SimError::Runtime(format!("unknown script: {other}"))),
        }
    }
}

// Suppress dead_code warnings on `EventName` — it's part of the public
// API surface this module references for parity sanity but doesn't use
// directly in dispatch (the harness, not the scripts, owns name → event
// matching).
#[allow(dead_code)]
fn _event_name_referenced(_e: EventName) {}
