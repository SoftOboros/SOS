//! `sos-conformance` — SOS conformance vector suite harness library.
//!
//! Public surface for the harness binary and any future downstream
//! consumers (e.g. a vector-mining tool). Ratified by
//! [SOS-03](../../docs/concepts/SOS-03-CONCEPTS.md); this skeleton lands
//! the type set and module structure. Function bodies land in subsequent
//! commits per the spec-before-code discipline.
//!
//! See SOS-03 §5 (frozen enums), §6 (vector file format), §7 (harness
//! behaviour), §9 (invariants).

#![deny(rust_2018_idioms)]
#![warn(missing_docs)]

pub mod diff;
pub mod filter;
pub mod harness;
pub mod port;
pub mod vector_file;

pub use crate::diff::{structural_diff_traces, DiffRecord, DiffSeverity};
pub use crate::filter::Filter;
pub use crate::harness::{Harness, HarnessReport, VectorOutcome};
pub use crate::port::{InProcessPort, Port, SubprocessPort};
pub use crate::vector_file::{VectorCategory, VectorFile, VectorOrigin};
