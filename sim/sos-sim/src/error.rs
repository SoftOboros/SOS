//! Concrete error type for the simulator library API. The CLI binary
//! uses `anyhow::Result` over the top of this type; the library surface
//! stays `Result<_, SimError>` for consumers that want structured
//! diagnostics.

use std::fmt;
use std::io;

/// Errors surfaced from the simulator library API.
#[derive(Debug)]
pub enum SimError {
    /// The vector JSON failed to parse or referenced an undeclared event.
    VectorParse(String),
    /// A runtime invariant violation surfaced from a script body or the
    /// macrostep harness. Carries the invariant id and a snapshot.
    Runtime(String),
    /// A filesystem I/O error reading the vector or writing the trace.
    Io(io::Error),
    /// A `serde_json` error not otherwise classified.
    Json(serde_json::Error),
}

impl fmt::Display for SimError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            SimError::VectorParse(msg) => write!(f, "vector parse error: {msg}"),
            SimError::Runtime(msg) => write!(f, "simulator runtime error: {msg}"),
            SimError::Io(err) => write!(f, "I/O error: {err}"),
            SimError::Json(err) => write!(f, "JSON error: {err}"),
        }
    }
}

impl std::error::Error for SimError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            SimError::Io(err) => Some(err),
            SimError::Json(err) => Some(err),
            SimError::VectorParse(_) | SimError::Runtime(_) => None,
        }
    }
}

impl From<io::Error> for SimError {
    fn from(err: io::Error) -> Self {
        SimError::Io(err)
    }
}

impl From<serde_json::Error> for SimError {
    fn from(err: serde_json::Error) -> Self {
        SimError::Json(err)
    }
}
