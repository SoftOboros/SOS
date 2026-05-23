//! Smoke test for `Vector::from_json` — parses an inline SOS-00 §7.1
//! shape and asserts the headline fields. The `expected_trace` field is
//! present in the source JSON (SOS-03 vectors carry it) and must be
//! silently ignored by sos-sim's loader.

use sos_sim::{EventName, Vector};

const SAMPLE: &str = r#"{
  "name": "two-tasks-same-prio-alternate-via-yield",
  "config": {
    "max_tasks": 8,
    "max_prio":  8,
    "max_sems":  8,
    "max_queues": 4,
    "q_depth":   16,
    "tick_hz":   1000
  },
  "input": [
    { "event": "task.create", "data": { "id": 1, "prio": 3 } },
    { "event": "task.yield",  "data": null, "from_tid": 1 }
  ],
  "expected_trace": [
    { "after_input_idx": 0, "current": 0 }
  ]
}"#;

#[test]
fn vector_from_json_parses_canonical_shape() {
    let v = Vector::from_json(SAMPLE).expect("vector must parse");
    assert_eq!(v.name, "two-tasks-same-prio-alternate-via-yield");
    assert_eq!(v.config.max_tasks, 8);
    assert_eq!(v.config.max_prio, 8);
    assert_eq!(v.config.q_depth, 16);
    assert_eq!(v.config.tick_hz, 1000);
    assert_eq!(v.input.len(), 2);
    assert_eq!(v.input[0].name, EventName::TaskCreate);
    assert_eq!(v.input[1].name, EventName::TaskYield);
    assert_eq!(v.input[1].from_tid, Some(1));
}
