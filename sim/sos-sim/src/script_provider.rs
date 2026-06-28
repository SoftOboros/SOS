//! The `ScriptProvider` trait — the one pluggable abstraction in
//! `sos-sim`. See SOS-02 §6.7. v1 has exactly one implementation:
//! [`crate::HandCompiledScripts`] (INV-S-SIM-5).

use crate::datamodel::Datamodel;
use crate::error::SimError;
use crate::event::Event;

/// The pluggable `<script>`-execution surface. Implementations dispatch
/// from a canonical script-name (see SOS-02 §6.3) to a body that mutates
/// the datamodel and reads the event payload.
///
/// Implementations MUST NOT raise events, perform I/O, or read the
/// system clock. They MUST be pure functions of `(dm, ev)`.
pub trait ScriptProvider {
    /// Dispatch to the script body named `name`. Returns `Ok(())` on
    /// successful execution, or [`SimError::Runtime`] / similar for an
    /// invariant violation surfaced from inside the body.
    fn run_script(&self, name: &str, dm: &mut Datamodel, ev: &Event) -> Result<(), SimError>;
}
