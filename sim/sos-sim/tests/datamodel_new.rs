//! Smoke test for `Datamodel::new` — confirms the constructor mirrors
//! the `.scxml` `<boot>` block: idle is RUNNING, all other slots dormant,
//! sem/queue pools are sized + all invalid.

use sos_sim::{Config, Datamodel, ReturnCode, TaskState};

#[test]
fn datamodel_new_boot_baseline() {
    let cfg = Config {
        max_tasks: 4,
        max_prio: 3,
        max_sems: 2,
        max_queues: 2,
        q_depth: 8,
        tick_hz: 1000,
    };
    let dm = Datamodel::new(&cfg);

    assert_eq!(dm.max_tasks, 4);
    assert_eq!(dm.max_prio, 3);
    assert_eq!(dm.max_sems, 2);
    assert_eq!(dm.max_queues, 2);
    assert_eq!(dm.q_depth, 8);

    assert_eq!(dm.tcb.len(), 4);
    assert_eq!(dm.ready.len(), 3);
    for q in &dm.ready {
        assert!(q.is_empty());
    }

    // Task 0 (idle) was popped from ready[0] by the chart's boot
    // pick_next() and is now RUNNING.
    assert_eq!(dm.current, 0);
    assert_eq!(dm.tcb[0].state, TaskState::Running);
    assert_eq!(dm.tcb[0].id, 0);
    for slot in &dm.tcb[1..] {
        assert_eq!(slot.state, TaskState::Dormant);
        assert_eq!(slot.blk_obj, -1);
    }

    assert_eq!(dm.tick_count, 0);
    assert_eq!(dm.rc, ReturnCode::Ok);
    assert_eq!(dm.irq_nest, 0);
    assert_eq!(dm.sched_lock, 0);
    assert_eq!(dm.pend_ticks, 0);
    assert!(!dm.resched);

    assert_eq!(dm.sems.len(), 2);
    for s in &dm.sems {
        assert!(!s.valid);
    }
    assert_eq!(dm.queues.len(), 2);
    for q in &dm.queues {
        assert!(!q.valid);
    }
}
