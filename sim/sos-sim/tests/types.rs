//! Smoke test — confirm the crate compiles and the headline types are
//! constructible. Cannot construct a [`Datamodel`] yet because its
//! constructor body is `unimplemented!()`; this test only verifies that
//! the type names resolve through the public API.

use sos_sim::{Config, Datamodel};

#[test]
fn types_compile() {
    let _cfg = Config {
        max_tasks: 8,
        max_prio: 8,
        max_sems: 8,
        max_queues: 4,
        q_depth: 16,
        tick_hz: 1000,
    };
    // Cannot construct Datamodel yet (new is unimplemented!); just verify
    // the type names resolve.
    let _phantom: Option<Datamodel> = None;
}
