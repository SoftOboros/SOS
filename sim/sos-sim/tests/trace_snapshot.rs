//! Smoke test for `Trace::snapshot` — builds the boot-baseline datamodel
//! and asserts the snapshot is the SOS-02 §7.3 canonical baseline shape.

use sos_sim::{Config, Datamodel, TaskState, Trace};
use sos_sim::trace::{QueueSnapshot, SemSnapshot};

#[test]
fn snapshot_boot_baseline() {
    let cfg = Config {
        max_tasks: 8,
        max_prio: 8,
        max_sems: 8,
        max_queues: 4,
        q_depth: 16,
        tick_hz: 1000,
    };
    let dm = Datamodel::new(&cfg);
    let rec = Trace::snapshot(&dm, -1);

    assert_eq!(rec.after_input_idx, -1);
    assert_eq!(rec.current, 0);
    assert_eq!(rec.tick_count, 0);
    assert_eq!(rec.rc, 0);
    assert_eq!(rec.irq_nest, 0);
    assert_eq!(rec.sched_lock, 0);
    assert_eq!(rec.pend_ticks, 0);

    assert_eq!(rec.tcb.len(), 8);
    assert_eq!(rec.tcb[0].state, TaskState::Running);
    assert_eq!(rec.tcb[0].id, 0);
    assert_eq!(rec.tcb[0].blk_obj, -1);
    for slot in &rec.tcb[1..] {
        assert_eq!(slot.state, TaskState::Dormant);
    }

    assert_eq!(rec.ready.len(), 8);
    for q in &rec.ready {
        assert!(q.is_empty());
    }

    assert_eq!(rec.sems.len(), 8);
    for s in &rec.sems {
        assert!(matches!(s, SemSnapshot::Invalid { valid: false }));
    }
    assert_eq!(rec.queues.len(), 4);
    for q in &rec.queues {
        assert!(matches!(q, QueueSnapshot::Invalid { valid: false }));
    }

    // Confirm the on-wire serialisation produces the SOS-02 §7.3
    // baseline byte sequence: invalid sems/queues collapse to the
    // `{"valid": false}` short form, and field order matches §7.1.
    let json = serde_json::to_string(&rec).expect("snapshot must serialise");
    assert!(json.starts_with(
        "{\"after_input_idx\":-1,\"current\":0,\"tick_count\":0,\"rc\":0,\"tcb\":["
    ));
    assert!(json.contains("\"sems\":[{\"valid\":false}"));
    assert!(json.contains("\"queues\":[{\"valid\":false}"));
    assert!(json.ends_with("\"irq_nest\":0,\"sched_lock\":0,\"pend_ticks\":0}"));
}
