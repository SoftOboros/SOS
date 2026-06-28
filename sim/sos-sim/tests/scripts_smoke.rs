//! End-to-end smoke test for `HandCompiledScripts::run_script` — confirms
//! the dispatch table reaches `script_sys_idle_task_create_0` (aka
//! `script_task_create`) and that the hand-compiled body faithfully
//! mirrors the chart's `task.create` transition (rtos_kernel.scxml
//! lines 270-286).

use serde_json::json;
use sos_sim::{
    Config, Datamodel, Event, EventName, HandCompiledScripts, ReturnCode, ScriptProvider, TaskState,
};

#[test]
fn task_create_smoke() {
    let cfg = Config {
        max_tasks: 8,
        max_prio: 8,
        max_sems: 8,
        max_queues: 4,
        q_depth: 16,
        tick_hz: 1000,
    };
    let mut dm = Datamodel::new(&cfg);

    let ev = Event {
        name: EventName::TaskCreate,
        data: json!({"id": 1, "prio": 3}),
        from_tid: None,
    };

    let provider = HandCompiledScripts::new();
    provider
        .run_script("script_task_create", &mut dm, &ev)
        .expect("hand-compiled task.create body must dispatch and run");

    // Per the chart: task 1 becomes READY at prio 3, lands in ready[3],
    // and the syscall returns RC_OK.
    assert_eq!(dm.tcb[1].prio, 3, "tcb[1].prio");
    assert_eq!(dm.tcb[1].state, TaskState::Ready, "tcb[1].state");
    assert!(
        dm.ready[3].contains(&1),
        "ready[3] should contain task id 1; got {:?}",
        dm.ready[3]
    );
    assert_eq!(dm.rc, ReturnCode::Ok, "dm.rc");
    assert!(dm.resched, "task.create should request a reschedule");
}
