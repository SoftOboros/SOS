//! Smoke test for `Event::parse` — three SOS-01 §5.3 events covering a
//! payloaded user event, a no-payload ISR-context event, and a
//! payloaded ISR-context event.

use sos_sim::{Event, EventName};

#[test]
fn event_parse_task_create() {
    let ev = Event::parse(
        r#"{"event":"task.create","data":{"id":1,"prio":3},"from_tid":0}"#,
    )
    .expect("task.create must parse");
    assert_eq!(ev.name, EventName::TaskCreate);
    assert_eq!(ev.from_tid, Some(0));
    assert_eq!(ev.data["id"].as_i64(), Some(1));
    assert_eq!(ev.data["prio"].as_i64(), Some(3));
}

#[test]
fn event_parse_sys_tick_no_payload() {
    let ev = Event::parse(r#"{"event":"sys.tick","data":null,"from_tid":null}"#)
        .expect("sys.tick must parse");
    assert_eq!(ev.name, EventName::SysTick);
    assert!(ev.data.is_null());
    assert_eq!(ev.from_tid, None);
}

#[test]
fn event_parse_sem_give_from_isr() {
    let ev = Event::parse(r#"{"event":"sem.give_from_isr","data":{"sid":2}}"#)
        .expect("sem.give_from_isr must parse");
    assert_eq!(ev.name, EventName::SemGiveFromIsr);
    assert_eq!(ev.data["sid"].as_i64(), Some(2));
    // from_tid defaults to None on ISR-context events with the field
    // omitted entirely.
    assert_eq!(ev.from_tid, None);
}
