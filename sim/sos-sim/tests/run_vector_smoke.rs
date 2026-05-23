//! End-to-end smoke test for `Simulator::run_vector` — constructs an
//! inline single-event `Vector` (a `task.create`), runs it through the
//! reference simulator, and asserts both the trace shape (boot baseline
//! plus one after-input-0 record) and the post-quiescence `current`
//! value (the newly-created higher-priority task preempts idle).

use serde_json::json;
use sos_sim::{Config, Event, EventName, HandCompiledScripts, Simulator, Vector};

#[test]
fn run_vector_single_task_create() {
    let vector = Vector {
        name: "smoke-task-create".to_string(),
        config: Config {
            max_tasks: 8,
            max_prio: 8,
            max_sems: 8,
            max_queues: 4,
            q_depth: 16,
            tick_hz: 1000,
        },
        input: vec![Event {
            name: EventName::TaskCreate,
            data: json!({"id": 1, "prio": 3}),
            from_tid: None,
        }],
    };

    let mut sim = Simulator::new(vector.config, HandCompiledScripts::new());
    let trace = sim
        .run_vector(&vector)
        .expect("vector with one task.create event must run to completion");

    // SOS-02 §6.4: one boot-baseline record + one record per external
    // event in the vector. Single-event vector → two records.
    assert_eq!(
        trace.records.len(),
        2,
        "expected 2 trace records (boot baseline + after-input-0)"
    );

    let baseline = &trace.records[0];
    assert_eq!(baseline.after_input_idx, -1, "baseline.after_input_idx");
    assert_eq!(baseline.current, 0, "baseline.current — idle running at boot");

    let after_create = &trace.records[1];
    assert_eq!(
        after_create.after_input_idx, 0,
        "after-input-0.after_input_idx"
    );
    // After macrostep quiescence: scheduler ran (resched was set by
    // task.create) and picked the higher-priority task (1 at prio 3)
    // over idle (0 at prio 0).
    assert_eq!(
        after_create.current, 1,
        "after task.create + sched, task 1 should preempt idle"
    );
}
