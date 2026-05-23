//! Wire-form regression test for `datamodel::Msg`.
//!
//! Codifies the SOS-00 §5.6 Amendment 004 (ratified 2026-05-19) on-wire
//! discriminator form so future refactors of the `Msg` (de)serialiser
//! cannot silently re-introduce the bare-integer collapse of
//! `Msg::ReturnCode(Ok)` → `0` that pre-fix `#[serde(untagged)]` produced.
//!
//! | Variant | Wire form (per Amendment 004) |
//! |---|---|
//! | `Msg::Null` | `null` |
//! | `Msg::Int(n)` | bare signed integer `n` |
//! | `Msg::ReturnCode(rc)` | tagged object `{"rc": <i8>}` |
//!
//! The load-bearing property: `Msg::Int(0)` and `Msg::ReturnCode(Ok)` MUST
//! be structurally distinguishable on the wire (`0` vs `{"rc":0}`). The
//! SOS-04 firmware writer asserts this in
//! `ports/m7-rust/sos-m7-rust-tests/tests/json_writer.rs::msg_returncode_byte_equal`;
//! this test is the sim-side mirror.

use sos_sim::datamodel::{Msg, ReturnCode};

#[test]
fn msg_wire_form_matches_spec() {
    // Forward — sim emits the spec form, byte-for-byte.
    assert_eq!(serde_json::to_string(&Msg::Null).unwrap(), "null");
    assert_eq!(serde_json::to_string(&Msg::Int(42)).unwrap(), "42");
    assert_eq!(serde_json::to_string(&Msg::Int(0)).unwrap(), "0");
    assert_eq!(
        serde_json::to_string(&Msg::ReturnCode(ReturnCode::Ok)).unwrap(),
        "{\"rc\":0}"
    );
    assert_eq!(
        serde_json::to_string(&Msg::ReturnCode(ReturnCode::Timeout)).unwrap(),
        "{\"rc\":-1}"
    );
}

#[test]
fn msg_wire_form_round_trip() {
    // Reverse — every spec-form value parses back to the matching variant.
    let cases = [
        ("null", Msg::Null),
        ("42", Msg::Int(42)),
        ("0", Msg::Int(0)),
        ("-7", Msg::Int(-7)),
        ("{\"rc\":0}", Msg::ReturnCode(ReturnCode::Ok)),
        ("{\"rc\":-1}", Msg::ReturnCode(ReturnCode::Timeout)),
        ("{\"rc\":-2}", Msg::ReturnCode(ReturnCode::Full)),
        ("{\"rc\":-3}", Msg::ReturnCode(ReturnCode::Empty)),
        ("{\"rc\":-4}", Msg::ReturnCode(ReturnCode::Inval)),
    ];
    for (json, expected) in &cases {
        let parsed: Msg =
            serde_json::from_str(json).unwrap_or_else(|e| panic!("parse {json:?}: {e}"));
        assert_eq!(&parsed, expected, "round-trip mismatch for {json}");
        // And the re-serialised bytes match the input exactly.
        let reser = serde_json::to_string(&parsed).unwrap();
        assert_eq!(&reser, json, "re-serialise mismatch for {json}");
    }
}

#[test]
fn msg_int_zero_vs_rc_ok_are_distinguishable() {
    // The load-bearing distinction Amendment 004 was ratified to preserve:
    // `Msg::Int(0)` (a queue payload that happens to equal zero) MUST NOT
    // collapse to the same bytes as `Msg::ReturnCode(Ok)` (success unblock).
    let int_zero = serde_json::to_string(&Msg::Int(0)).unwrap();
    let rc_ok = serde_json::to_string(&Msg::ReturnCode(ReturnCode::Ok)).unwrap();
    assert_eq!(int_zero, "0");
    assert_eq!(rc_ok, "{\"rc\":0}");
    assert_ne!(
        int_zero, rc_ok,
        "Msg::Int(0) and Msg::ReturnCode(Ok) must produce structurally-distinct bytes"
    );
}
