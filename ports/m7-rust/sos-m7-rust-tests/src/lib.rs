//! Host-side byte-equality tests for the SOS-04 M7 Rust port's
//! hand-rolled JSONL trace writer. Per PCDN-SOS-04-018 the tests live
//! in this sibling host crate rather than `#[cfg(test)]` inside the
//! firmware crate so `cargo test` does not need to fight `cortex-m-rt`'s
//! attribute macros.
//!
//! The crate itself is intentionally empty — every test fixture lives
//! under `tests/`. See `tests/json_writer.rs`.
