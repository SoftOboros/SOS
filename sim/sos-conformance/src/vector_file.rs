//! Vector file types — the on-disk JSON fixture shape per SOS-03 §6.2.
//!
//! See SOS-03 §5.1 (`VectorCategory`), §5.4 (`VectorOrigin`), §6.2 (the
//! JSON schema this module mirrors).

use std::path::Path;

use serde::{Deserialize, Serialize};

/// One vector fixture — the deserialised form of a
/// `conformance/vectors/<category>/<NNNN>-<slug>.json` file. Mirrors the
/// SOS-03 §6.2 schema exactly. `expected_trace` is committed-by-author
/// per PCDN-SOS-03-003 (auditable vectors); the harness compares against
/// these bytes without regenerating.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub struct VectorFile {
    /// Human-readable kebab-case vector name (SOS-03 §6.2 / §6.3).
    pub name: String,
    /// One-paragraph human-readable description (SOS-03 §6.2).
    pub description: String,
    /// Category subtree the vector lives under (SOS-03 §5.1).
    pub category: VectorCategory,
    /// Provenance discriminator (SOS-03 §5.4).
    pub origin: VectorOrigin,
    /// Free-form classification tags (SOS-03 §6.2).
    pub tags: Vec<String>,
    /// Kernel-sizing config block (SOS-00 §7.1 mirror; SOS-02 `Config`).
    pub config: sos_sim::Config,
    /// Ordered external events to dispatch (SOS-01 §5.3 vocabulary).
    pub input: Vec<sos_sim::Event>,
    /// `sos-sim`-generated trace bytes; `len(expected_trace) ==
    /// len(input) + 1` per SOS-03 §6.2.
    pub expected_trace: Vec<sos_sim::TraceRecord>,
}

impl VectorFile {
    /// Load and validate a vector fixture from `p`. Schema mismatches
    /// surface as `anyhow::Error` per SOS-03 §6.2 validation rules.
    pub fn from_path(p: &Path) -> anyhow::Result<Self> {
        let bytes = std::fs::read_to_string(p)
            .map_err(|e| anyhow::anyhow!("failed to read vector file {}: {e}", p.display()))?;
        let parsed: VectorFile = serde_json::from_str(&bytes)
            .map_err(|e| anyhow::anyhow!("failed to parse vector {}: {e}", p.display()))?;
        Ok(parsed)
    }

    /// Extract the zero-padded sequential id prefix from a filename per
    /// SOS-03 §6.3. Returns `None` when the filename does not match
    /// `NNNN-<slug>.json`.
    pub fn vector_id_from_filename(p: &Path) -> Option<u32> {
        let stem = p.file_stem()?.to_str()?;
        let (id_part, rest) = stem.split_once('-')?;
        if rest.is_empty() {
            return None;
        }
        if id_part.is_empty() || id_part.len() > 10 {
            return None;
        }
        if !id_part.chars().all(|c| c.is_ascii_digit()) {
            return None;
        }
        id_part.parse::<u32>().ok()
    }
}

/// Vector category — five-value frozen enum per SOS-03 §5.1
/// (Standards Action; adding a value requires a §15 amendment).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum VectorCategory {
    /// Core-surface vector; defines `SmokePass` (SOS-03 §5.1, §5.2).
    Smoke,
    /// Edge-case vector at a primitive's contract boundary (SOS-03 §5.1).
    Boundary,
    /// Volume vector exercising repeated / interleaved sequences
    /// (SOS-03 §5.1).
    Stress,
    /// Vector mined from a resolved ERRATA entry (SOS-03 §5.1).
    Regression,
    /// Vector exposing a port-specific corner case rather than a
    /// kernel-spec violation (SOS-03 §5.1).
    Diversity,
}

/// Vector provenance — three-value frozen enum per SOS-03 §5.4
/// (Specification Required).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum VectorOrigin {
    /// One of the six seed vectors derived from SOS-00 §7.4.
    Seed,
    /// Hand-authored by a phase reviewer.
    Authored,
    /// Auto-generated from a resolved ERRATA entry by the reserved
    /// regression-vector miner (SOS-03 §7.4).
    RegressionMined,
}
