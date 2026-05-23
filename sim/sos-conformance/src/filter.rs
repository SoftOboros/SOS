//! `--filter <GLOB>` matcher — wraps `globset` per SOS-03 §7.5 and
//! PCDN-SOS-03-006.
//!
//! Glob semantics match `globset`'s defaults: `*` matches any sequence of
//! characters except `/`; `**` matches across path separators; `?`, `[…]`,
//! `{a,b}` per the standard glob grammar (SOS-03 §7.5 examples).

use globset::{GlobBuilder, GlobSet, GlobSetBuilder};

/// Compiled glob filter applied to vector paths relative to `--suite`.
pub struct Filter {
    /// The compiled `globset` matcher (multi-pattern; comma-separated
    /// patterns are split before compilation).
    pub matcher: GlobSet,
    /// Whether any patterns are present — when empty, [`Filter::matches`]
    /// matches everything (SOS-03 §7.5 default).
    pub empty: bool,
}

impl Filter {
    /// Compile a single glob string. Comma-separated patterns are split
    /// and OR-ed into a `GlobSet`. Invalid globs surface as
    /// `anyhow::Error` and yield exit code 1 in the harness.
    pub fn from_pattern(s: &str) -> anyhow::Result<Self> {
        let mut builder = GlobSetBuilder::new();
        let mut count = 0usize;
        for raw in s.split(',') {
            let pat = raw.trim();
            if pat.is_empty() {
                continue;
            }
            let g = GlobBuilder::new(pat)
                .literal_separator(false)
                .build()
                .map_err(|e| anyhow::anyhow!("invalid glob pattern {pat:?}: {e}"))?;
            builder.add(g);
            count += 1;
        }
        let set = builder
            .build()
            .map_err(|e| anyhow::anyhow!("failed to build globset: {e}"))?;
        Ok(Filter {
            matcher: set,
            empty: count == 0,
        })
    }

    /// Test whether a relative vector path (e.g. `smoke/0001-...json`)
    /// matches the compiled filter. An empty filter matches everything
    /// per SOS-03 §7.5.
    pub fn matches(&self, path: &str) -> bool {
        if self.empty {
            return true;
        }
        self.matcher.is_match(path)
    }
}
