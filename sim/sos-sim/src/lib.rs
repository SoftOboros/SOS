//! `sos-sim` — SOS host simulator library.
//!
//! Reference implementation of `rtos_kernel.scxml` as ratified by
//! [SOS-02](../../docs/concepts/SOS-02-CONCEPTS.md). This skeleton lands the
//! module layout, public API surface, and frozen type set. Function bodies
//! land in subsequent commits per the spec-before-code discipline.
//!
//! See SOS-02 §6.1 for the module layout and §6 for the architecture this
//! crate realises.

#![deny(rust_2018_idioms)]
#![warn(missing_docs)]

pub mod datamodel;
pub mod error;
pub mod event;
pub mod script_provider;
pub mod scripts;
pub mod simulator;
pub mod trace;
pub mod vector;

pub use crate::datamodel::{Datamodel, Msg, Queue, ReturnCode, Sem, TaskId, TaskState, Tcb};
pub use crate::error::SimError;
pub use crate::event::{Event, EventName};
pub use crate::script_provider::ScriptProvider;
pub use crate::scripts::HandCompiledScripts;
pub use crate::simulator::Simulator;
pub use crate::trace::{Trace, TraceRecord};
pub use crate::vector::{Config, Vector};
