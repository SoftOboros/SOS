//! Byte-equality tests for the SOS-04 M7 Rust port's hand-rolled JSONL
//! trace writer (PCDN-SOS-04-008 + PCDN-SOS-04-018).
//!
//! Each test builds a [`sos_sim::TraceRecord`] (the reference shape) via
//! `serde_json::to_string` to produce the canonical bytes, then builds
//! an equivalent [`sos_m7_rust_trace::TraceInput`] and asserts the
//! firmware writer's output matches byte-for-byte. The firmware writer's
//! adapter layer (`sos_m7_rust::trace::write_record`) is a one-page
//! `Datamodel` → `TraceInput` translation that is exercised end-to-end
//! on the bench by the SOS-03 conformance harness; here we exercise the
//! load-bearing layer (the hand-rolled bytes) directly.

use sos_m7_rust_trace::{
    write_record_from_input, Msg as TMsg, QueueView, ReturnCode as TRc, SemView,
    TaskState as TSt, TcbView, TraceInput,
};
use sos_sim::{
    datamodel::{Msg as SMsg, ReturnCode as SRc, TaskState as SSt},
    trace::{QueueSnapshot, SemSnapshot, TcbSnapshot, TraceRecord},
};

// ---------------------------------------------------------------------------
// Sizing — matches SOS-04 `kernel.rs` defaults and the conformance vector's
// `config` block.
// ---------------------------------------------------------------------------

const MAX_TASKS: usize = 8;
const MAX_PRIO: usize = 8;
const MAX_SEMS: usize = 8;
const MAX_QUEUES: usize = 4;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Construct the reference bytes by serialising `rec` via `serde_json`
/// and appending the JSONL framing newline. This matches what `sos-sim`
/// produces in `Trace::write_jsonl` per `sim/sos-sim/src/trace.rs`.
fn serde_ref(rec: &TraceRecord) -> Vec<u8> {
    let mut s = serde_json::to_string(rec).expect("serde_json::to_string");
    s.push('\n');
    s.into_bytes()
}

/// Call the firmware writer into a generously-sized buffer and return
/// the bytes actually written.
fn fw_bytes(input: &TraceInput<'_>, after_input_idx: i64) -> Vec<u8> {
    let mut buf = [0u8; 4096];
    let n = write_record_from_input(&mut buf, input, after_input_idx);
    buf[..n].to_vec()
}

/// Render a byte slice that's expected to be UTF-8 JSON; falls back to
/// hex for the assertion message if it isn't valid UTF-8.
fn render(b: &[u8]) -> String {
    match core::str::from_utf8(b) {
        Ok(s) => s.to_string(),
        Err(_) => format!("(non-utf8) {:02x?}", b),
    }
}

/// Build a TaskState round-trip view: the firmware enum and the
/// reference enum must carry the same integer discriminant.
fn task_state_pair(t: TSt) -> SSt {
    match t {
        TSt::Dormant => SSt::Dormant,
        TSt::Ready => SSt::Ready,
        TSt::Running => SSt::Running,
        TSt::Delay => SSt::Delay,
        TSt::BlkSem => SSt::BlkSem,
        TSt::BlkQs => SSt::BlkQs,
        TSt::BlkQr => SSt::BlkQr,
        TSt::Suspend => SSt::Suspend,
    }
}

fn rc_pair(t: TRc) -> SRc {
    match t {
        TRc::Ok => SRc::Ok,
        TRc::Timeout => SRc::Timeout,
        TRc::Full => SRc::Full,
        TRc::Empty => SRc::Empty,
        TRc::Inval => SRc::Inval,
    }
}

fn msg_pair(m: TMsg) -> SMsg {
    match m {
        TMsg::Null => SMsg::Null,
        TMsg::Int(n) => SMsg::Int(n),
        TMsg::ReturnCode(rc) => SMsg::ReturnCode(rc_pair(rc)),
    }
}

/// Build a `(reference TraceRecord, firmware bytes)` pair for the
/// boot-baseline shape: idle (TCB[0]) is RUNNING, every other TCB is
/// DORMANT, every sem/queue invalid, every ready FIFO empty.
fn boot_baseline_tcbs_firmware() -> [TcbView; MAX_TASKS] {
    let mut tcbs = [TcbView {
        id: 0,
        prio: 0,
        state: TSt::Dormant,
        deadline: 0,
        blk_obj: -1,
        msg: TMsg::Null,
    }; MAX_TASKS];
    for i in 0..MAX_TASKS {
        tcbs[i].id = i as i16;
    }
    tcbs[0].state = TSt::Running;
    tcbs
}

fn boot_baseline_tcbs_reference() -> Vec<TcbSnapshot> {
    let firmware = boot_baseline_tcbs_firmware();
    firmware
        .iter()
        .map(|t| TcbSnapshot {
            id: t.id,
            prio: t.prio,
            state: task_state_pair(t.state),
            deadline: t.deadline,
            blk_obj: t.blk_obj,
            msg: msg_pair(t.msg),
        })
        .collect()
}

fn invalid_sems_reference() -> Vec<SemSnapshot> {
    (0..MAX_SEMS)
        .map(|_| SemSnapshot::Invalid { valid: false })
        .collect()
}

fn invalid_queues_reference() -> Vec<QueueSnapshot> {
    (0..MAX_QUEUES)
        .map(|_| QueueSnapshot::Invalid { valid: false })
        .collect()
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[test]
fn boot_baseline_byte_equal() {
    // ----- Firmware-side input -----
    let tcbs_fw = boot_baseline_tcbs_firmware();
    let ready_fw: [&[i16]; MAX_PRIO] = [&[]; MAX_PRIO];
    let sems_fw: [SemView<'_>; MAX_SEMS] = [SemView {
        valid: false,
        count: 0,
        max: 0,
        waiters: &[],
    }; MAX_SEMS];
    let queues_fw: [QueueView<'_>; MAX_QUEUES] = [QueueView {
        valid: false,
        cap: 0,
        count: 0,
        buf: &[],
        sendw: &[],
        recvw: &[],
    }; MAX_QUEUES];

    let input = TraceInput {
        current: 0,
        tick_count: 0,
        rc: TRc::Ok,
        tcb: &tcbs_fw,
        ready: &ready_fw,
        sems: &sems_fw,
        queues: &queues_fw,
        irq_nest: 0,
        sched_lock: 0,
        pend_ticks: 0,
    };

    let got = fw_bytes(&input, -1);

    // ----- Reference TraceRecord -----
    let ready: Vec<Vec<i32>> = (0..MAX_PRIO).map(|_| Vec::new()).collect();
    let rec = TraceRecord {
        after_input_idx: -1,
        current: 0,
        tick_count: 0,
        rc: i8::from(SRc::Ok) as i32,
        tcb: boot_baseline_tcbs_reference(),
        ready,
        sems: invalid_sems_reference(),
        queues: invalid_queues_reference(),
        irq_nest: 0,
        sched_lock: 0,
        pend_ticks: 0,
    };
    let want = serde_ref(&rec);

    assert_eq!(
        got,
        want,
        "boot_baseline mismatch:\n  firmware: {}\n  serde:    {}",
        render(&got),
        render(&want)
    );
}

#[test]
fn after_task_create_byte_equal() {
    // Shape after the smoke vector's first event (`task.create id=1
    // prio=3`). Per `pick_next()` the higher-priority new task preempts
    // idle: TCB[1] → RUNNING at prio 3; TCB[0] → READY at prio 0;
    // ready[0] = [0]; ready[3] = []. (Matches `sos-sim`'s post-event
    // behaviour for this vector; the conformance fixture's record at
    // index 0 expresses the same state.)
    let mut tcbs_fw = boot_baseline_tcbs_firmware();
    tcbs_fw[0].state = TSt::Ready;
    tcbs_fw[1].state = TSt::Running;
    tcbs_fw[1].prio = 3;

    let r0: &[i16] = &[0];
    let empty: &[i16] = &[];
    let ready_fw: [&[i16]; MAX_PRIO] = [r0, empty, empty, empty, empty, empty, empty, empty];

    let sems_fw: [SemView<'_>; MAX_SEMS] = [SemView {
        valid: false,
        count: 0,
        max: 0,
        waiters: &[],
    }; MAX_SEMS];
    let queues_fw: [QueueView<'_>; MAX_QUEUES] = [QueueView {
        valid: false,
        cap: 0,
        count: 0,
        buf: &[],
        sendw: &[],
        recvw: &[],
    }; MAX_QUEUES];

    let input = TraceInput {
        current: 1,
        tick_count: 0,
        rc: TRc::Ok,
        tcb: &tcbs_fw,
        ready: &ready_fw,
        sems: &sems_fw,
        queues: &queues_fw,
        irq_nest: 0,
        sched_lock: 0,
        pend_ticks: 0,
    };

    let got = fw_bytes(&input, 0);

    let mut tcbs_ref = boot_baseline_tcbs_reference();
    tcbs_ref[0].state = SSt::Ready;
    tcbs_ref[1].state = SSt::Running;
    tcbs_ref[1].prio = 3;

    let mut ready: Vec<Vec<i32>> = (0..MAX_PRIO).map(|_| Vec::new()).collect();
    ready[0].push(0);

    let rec = TraceRecord {
        after_input_idx: 0,
        current: 1,
        tick_count: 0,
        rc: i8::from(SRc::Ok) as i32,
        tcb: tcbs_ref,
        ready,
        sems: invalid_sems_reference(),
        queues: invalid_queues_reference(),
        irq_nest: 0,
        sched_lock: 0,
        pend_ticks: 0,
    };
    let want = serde_ref(&rec);

    assert_eq!(
        got,
        want,
        "after_task_create mismatch:\n  firmware: {}\n  serde:    {}",
        render(&got),
        render(&want)
    );
}

#[test]
fn msg_int_byte_equal() {
    // TCB[2] has `Msg::Int(42)`. Wire form is `"msg":42` — bare integer,
    // NOT `{"int":42}` or any tagged object form.
    let mut tcbs_fw = boot_baseline_tcbs_firmware();
    tcbs_fw[2].msg = TMsg::Int(42);

    let ready_fw: [&[i16]; MAX_PRIO] = [&[]; MAX_PRIO];
    let sems_fw: [SemView<'_>; MAX_SEMS] = [SemView {
        valid: false,
        count: 0,
        max: 0,
        waiters: &[],
    }; MAX_SEMS];
    let queues_fw: [QueueView<'_>; MAX_QUEUES] = [QueueView {
        valid: false,
        cap: 0,
        count: 0,
        buf: &[],
        sendw: &[],
        recvw: &[],
    }; MAX_QUEUES];

    let input = TraceInput {
        current: 0,
        tick_count: 0,
        rc: TRc::Ok,
        tcb: &tcbs_fw,
        ready: &ready_fw,
        sems: &sems_fw,
        queues: &queues_fw,
        irq_nest: 0,
        sched_lock: 0,
        pend_ticks: 0,
    };

    let got = fw_bytes(&input, -1);
    let s = core::str::from_utf8(&got).expect("utf8");
    assert!(
        s.contains(r#""msg":42"#),
        "expected bare-integer Msg::Int wire form; got: {}",
        s
    );

    let mut tcbs_ref = boot_baseline_tcbs_reference();
    tcbs_ref[2].msg = SMsg::Int(42);
    let rec = TraceRecord {
        after_input_idx: -1,
        current: 0,
        tick_count: 0,
        rc: i8::from(SRc::Ok) as i32,
        tcb: tcbs_ref,
        ready: (0..MAX_PRIO).map(|_| Vec::new()).collect(),
        sems: invalid_sems_reference(),
        queues: invalid_queues_reference(),
        irq_nest: 0,
        sched_lock: 0,
        pend_ticks: 0,
    };
    let want = serde_ref(&rec);
    assert_eq!(got, want, "Msg::Int byte mismatch");
}

#[test]
fn msg_returncode_byte_equal() {
    // TCB[3] has `Msg::ReturnCode(RC_OK)`. Per SOS-00 §5.6 Amendment 004
    // the on-wire form is `{"rc":0}`, NOT `0` (which would alias
    // `Msg::Int(0)` and make the variants ambiguous on the wire).
    //
    // Both sides (firmware writer + `sos-sim`'s custom `Msg` Serialize
    // impl per `sim/sos-sim/src/datamodel.rs`) emit the spec form, so
    // the byte-equality check is direct — no patching workaround. The
    // sim-side regression is locked in by
    // `sim/sos-sim/tests/msg_serialisation.rs`.
    let mut tcbs_fw = boot_baseline_tcbs_firmware();
    tcbs_fw[3].msg = TMsg::ReturnCode(TRc::Ok);

    let ready_fw: [&[i16]; MAX_PRIO] = [&[]; MAX_PRIO];
    let sems_fw: [SemView<'_>; MAX_SEMS] = [SemView {
        valid: false,
        count: 0,
        max: 0,
        waiters: &[],
    }; MAX_SEMS];
    let queues_fw: [QueueView<'_>; MAX_QUEUES] = [QueueView {
        valid: false,
        cap: 0,
        count: 0,
        buf: &[],
        sendw: &[],
        recvw: &[],
    }; MAX_QUEUES];

    let input = TraceInput {
        current: 0,
        tick_count: 0,
        rc: TRc::Ok,
        tcb: &tcbs_fw,
        ready: &ready_fw,
        sems: &sems_fw,
        queues: &queues_fw,
        irq_nest: 0,
        sched_lock: 0,
        pend_ticks: 0,
    };

    let got = fw_bytes(&input, -1);
    let s = core::str::from_utf8(&got).expect("utf8");
    assert!(
        s.contains(r#""msg":{"rc":0}"#),
        "expected {{\"rc\":0}} Msg::ReturnCode wire form per SOS-00 §5.6 Amendment 004; got: {}",
        s
    );

    // Direct byte-equality against the sos-sim serde reference now that
    // sos-sim emits the spec form natively. Any future regression on
    // either side (firmware writer drift OR sim Serialize-impl drift)
    // surfaces here as a byte mismatch.
    let mut tcbs_ref = boot_baseline_tcbs_reference();
    tcbs_ref[3].msg = SMsg::ReturnCode(SRc::Ok);
    let rec = TraceRecord {
        after_input_idx: -1,
        current: 0,
        tick_count: 0,
        rc: i8::from(SRc::Ok) as i32,
        tcb: tcbs_ref,
        ready: (0..MAX_PRIO).map(|_| Vec::new()).collect(),
        sems: invalid_sems_reference(),
        queues: invalid_queues_reference(),
        irq_nest: 0,
        sched_lock: 0,
        pend_ticks: 0,
    };
    let want = serde_ref(&rec);
    assert_eq!(
        got,
        want,
        "Msg::ReturnCode byte mismatch (spec form):\n  firmware: {}\n  serde:    {}",
        render(&got),
        render(&want)
    );
}

#[test]
fn sem_full_form_byte_equal() {
    // sems[0] valid with count=2, max=8, waiters=[4, 5]. Verifies the
    // long-form `{"valid":true,"count":...,...}` shape; SOS-02 §7.2 +
    // sos_sim::SemSnapshot::Valid field order.
    let tcbs_fw = boot_baseline_tcbs_firmware();
    let ready_fw: [&[i16]; MAX_PRIO] = [&[]; MAX_PRIO];

    let waiters_fw: &[i16] = &[4, 5];
    let mut sems_fw: [SemView<'_>; MAX_SEMS] = [SemView {
        valid: false,
        count: 0,
        max: 0,
        waiters: &[],
    }; MAX_SEMS];
    sems_fw[0] = SemView {
        valid: true,
        count: 2,
        max: 8,
        waiters: waiters_fw,
    };

    let queues_fw: [QueueView<'_>; MAX_QUEUES] = [QueueView {
        valid: false,
        cap: 0,
        count: 0,
        buf: &[],
        sendw: &[],
        recvw: &[],
    }; MAX_QUEUES];

    let input = TraceInput {
        current: 0,
        tick_count: 0,
        rc: TRc::Ok,
        tcb: &tcbs_fw,
        ready: &ready_fw,
        sems: &sems_fw,
        queues: &queues_fw,
        irq_nest: 0,
        sched_lock: 0,
        pend_ticks: 0,
    };
    let got = fw_bytes(&input, -1);

    let mut sems_ref = invalid_sems_reference();
    sems_ref[0] = SemSnapshot::Valid {
        valid: true,
        count: 2,
        max: 8,
        waiters: vec![4, 5],
    };
    let rec = TraceRecord {
        after_input_idx: -1,
        current: 0,
        tick_count: 0,
        rc: i8::from(SRc::Ok) as i32,
        tcb: boot_baseline_tcbs_reference(),
        ready: (0..MAX_PRIO).map(|_| Vec::new()).collect(),
        sems: sems_ref,
        queues: invalid_queues_reference(),
        irq_nest: 0,
        sched_lock: 0,
        pend_ticks: 0,
    };
    let want = serde_ref(&rec);
    assert_eq!(
        got,
        want,
        "sem full-form mismatch:\n  firmware: {}\n  serde:    {}",
        render(&got),
        render(&want)
    );
}

#[test]
fn queue_short_form_byte_equal() {
    // Every queue invalid. Wire fragment: `"queues":[{"valid":false},
    // {"valid":false},{"valid":false},{"valid":false}]`.
    let tcbs_fw = boot_baseline_tcbs_firmware();
    let ready_fw: [&[i16]; MAX_PRIO] = [&[]; MAX_PRIO];
    let sems_fw: [SemView<'_>; MAX_SEMS] = [SemView {
        valid: false,
        count: 0,
        max: 0,
        waiters: &[],
    }; MAX_SEMS];
    let queues_fw: [QueueView<'_>; MAX_QUEUES] = [QueueView {
        valid: false,
        cap: 0,
        count: 0,
        buf: &[],
        sendw: &[],
        recvw: &[],
    }; MAX_QUEUES];

    let input = TraceInput {
        current: 0,
        tick_count: 0,
        rc: TRc::Ok,
        tcb: &tcbs_fw,
        ready: &ready_fw,
        sems: &sems_fw,
        queues: &queues_fw,
        irq_nest: 0,
        sched_lock: 0,
        pend_ticks: 0,
    };
    let got = fw_bytes(&input, -1);
    let s = core::str::from_utf8(&got).expect("utf8");
    assert!(
        s.contains(r#""queues":[{"valid":false},{"valid":false},{"valid":false},{"valid":false}]"#),
        "expected four invalid queue short-form entries; got: {}",
        s
    );

    let rec = TraceRecord {
        after_input_idx: -1,
        current: 0,
        tick_count: 0,
        rc: i8::from(SRc::Ok) as i32,
        tcb: boot_baseline_tcbs_reference(),
        ready: (0..MAX_PRIO).map(|_| Vec::new()).collect(),
        sems: invalid_sems_reference(),
        queues: invalid_queues_reference(),
        irq_nest: 0,
        sched_lock: 0,
        pend_ticks: 0,
    };
    let want = serde_ref(&rec);
    assert_eq!(got, want, "queue short-form full-record mismatch");
}

#[test]
fn negative_after_input_idx() {
    // The boot-baseline record has `after_input_idx = -1`. Verifies the
    // signed integer is emitted as `-1` (not `4294967295` or
    // similar truncation), and the field is the first key in the object.
    let tcbs_fw = boot_baseline_tcbs_firmware();
    let ready_fw: [&[i16]; MAX_PRIO] = [&[]; MAX_PRIO];
    let sems_fw: [SemView<'_>; MAX_SEMS] = [SemView {
        valid: false,
        count: 0,
        max: 0,
        waiters: &[],
    }; MAX_SEMS];
    let queues_fw: [QueueView<'_>; MAX_QUEUES] = [QueueView {
        valid: false,
        cap: 0,
        count: 0,
        buf: &[],
        sendw: &[],
        recvw: &[],
    }; MAX_QUEUES];

    let input = TraceInput {
        current: 0,
        tick_count: 0,
        rc: TRc::Ok,
        tcb: &tcbs_fw,
        ready: &ready_fw,
        sems: &sems_fw,
        queues: &queues_fw,
        irq_nest: 0,
        sched_lock: 0,
        pend_ticks: 0,
    };
    let got = fw_bytes(&input, -1);
    let s = core::str::from_utf8(&got).expect("utf8");
    assert!(
        s.starts_with(r#"{"after_input_idx":-1,"#),
        "after_input_idx not first or not -1; got prefix: {}",
        &s[..s.len().min(40)]
    );
}

#[test]
fn buffer_overrun_returns_partial() {
    // Pass a 32-byte buffer to a writer whose minimum record size is
    // hundreds of bytes. The writer must return a count <= 32, must NOT
    // panic, and must NOT corrupt memory past the buffer.
    let tcbs_fw = boot_baseline_tcbs_firmware();
    let ready_fw: [&[i16]; MAX_PRIO] = [&[]; MAX_PRIO];
    let sems_fw: [SemView<'_>; MAX_SEMS] = [SemView {
        valid: false,
        count: 0,
        max: 0,
        waiters: &[],
    }; MAX_SEMS];
    let queues_fw: [QueueView<'_>; MAX_QUEUES] = [QueueView {
        valid: false,
        cap: 0,
        count: 0,
        buf: &[],
        sendw: &[],
        recvw: &[],
    }; MAX_QUEUES];

    let input = TraceInput {
        current: 0,
        tick_count: 0,
        rc: TRc::Ok,
        tcb: &tcbs_fw,
        ready: &ready_fw,
        sems: &sems_fw,
        queues: &queues_fw,
        irq_nest: 0,
        sched_lock: 0,
        pend_ticks: 0,
    };

    let mut buf = [0u8; 32];
    let n = write_record_from_input(&mut buf, &input, -1);
    assert!(n <= 32, "writer claimed {n} bytes into a 32-byte buffer");
    // The first 32 bytes of the boot-baseline record start with the
    // canonical prefix; we can verify the partial write is well-formed
    // up to the truncation point.
    let prefix = &buf[..n];
    let s = core::str::from_utf8(prefix).expect("partial bytes are valid UTF-8");
    assert!(
        s.starts_with(r#"{"after_input_idx":-1"#),
        "partial bytes did not carry the canonical prefix: {}",
        s
    );
}
