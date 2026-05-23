//! Vector input — the on-disk fixture shape consumed by the simulator.
//! See SOS-00 §7.1 for the canonical shape and SOS-02 §6.6 for the CLI
//! discipline that loads it.

use serde::{Deserialize, Serialize};

use crate::error::SimError;
use crate::event::Event;

/// One conformance vector. The `expected_trace` half is owned by SOS-03
/// and intentionally omitted from this v1 type — `sos-sim` consumes only
/// the `input` half and produces the trace itself.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Vector {
    /// Vector name (used in diagnostics; not on the trace wire).
    pub name: String,
    /// Per-vector kernel sizing.
    pub config: Config,
    /// Ordered external events; index `i` matches `after_input_idx`.
    pub input: Vec<Event>,
}

impl Vector {
    /// Parse a vector from its JSON form. Extra top-level fields (notably
    /// SOS-03's `expected_trace`, which the conformance harness consumes)
    /// are tolerated and ignored — sos-sim consumes only the `input` half
    /// and produces the trace itself.
    pub fn from_json(s: &str) -> Result<Self, SimError> {
        serde_json::from_str::<Vector>(s).map_err(|e| {
            SimError::VectorParse(format!("vector JSON did not parse: {e}"))
        })
    }
}

/// Per-vector kernel sizing. Mirrors SOS-00 §7.1's `config` block. Fields
/// are declared in the canonical wire order.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct Config {
    /// `MAX_TASKS` — TCB slot count.
    pub max_tasks: usize,
    /// `MAX_PRIO` — priority band count.
    pub max_prio: usize,
    /// `MAX_SEMS` — semaphore descriptor count.
    pub max_sems: usize,
    /// `MAX_QUEUES` — queue descriptor count.
    pub max_queues: usize,
    /// `Q_DEPTH` — per-queue buffer capacity ceiling.
    pub q_depth: usize,
    /// `SOS_TICK_HZ` — informative on the host simulator; M7 ports use it
    /// to size SysTick.
    pub tick_hz: u32,
}
