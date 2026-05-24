# SOS-08-G viewer extensions

In-subrepo distribution location for the [SOS-08-G](../../../docs/concepts/SOS-08-G-CONCEPTS.md)
waveform-viewer extensions (per **PCDN-G-004** resolution, ratified
2026-05-23 §15).

Two viewer integrations are shipped:

| Viewer | Directory | Wave |
|--------|-----------|------|
| [GTKWave](./gtkwave/) | `gtkwave/` | wave-1 → wave-3c (loadable Tcl plugin) |
| [Surfer](./surfer/) | `surfer/` | wave-1 → wave-3c (WASM plugin scaffold) |

Both integrations honour the **SOS-08-G §6 viewer-integration contract**:

| Gate | GTKWave | Surfer |
|------|---------|--------|
| (a) MUST co-locate via `_meta.waveform_prefix` | ✅ | ✅ |
| (b) MUST schema-version-aware | ✅ | ✅ |
| (c) MUST per-record render | ✅ (named markers) | ✅ (WCP markers) |
| (d) SHOULD chart-path navigation | ✅ (comment tracks) | ✅ (overlay tracks) |
| (e) SHOULD invariant-fire highlighting | ✅ (`sos:invariants` track) | ✅ (`sos:invariants` track) |
| (f) SHOULD vector-citation drill-down | ⏸ wave-3c-future | ⏸ wave-3c-future |

Both viewers also expose a **standalone Python CLI** for previewing
overlays without the GUI binary installed (useful in CI):

```sh
# Preview from anywhere on PATH
python3 -m sos_gtkwave_ext  path/to/test.annotations.jsonl
python3 -m sos_surfer_ext   path/to/test.annotations.jsonl
```

## Discovery model (wave-3b)

When a viewer opens a waveform file, it discovers the matching
overlay via SOS-08-G §6 (a) co-locate semantics:

1. **Wave-3b primary**: Read each candidate's first-line `_meta`
   envelope; match by `waveform_prefix == <loaded_waveform_stem>`.
2. **Wave-1 fallback**: Match by exact filename
   `<loaded_waveform_stem>.annotations.jsonl`.

The wave-3b discovery model is **by construction** — the cocotb
Makefile's `SOS_WAVEFORM_PREFIX = $(MODULE)` propagates through the
simulator's dump filename + the `AnnotationWriter`'s `_meta` field so
viewers locate the waveform from any per-test overlay's metadata
without filesystem heuristics.

## Cross-viewer source-of-truth shared constants

`gtkwave/sos_gtkwave_ext.py` is the canonical Python module; the
Surfer Python CLI (`surfer/sos_surfer_ext.py`) re-exports the schema
constants + the `discover_waveform_paths` helper from the GTKWave
module so the two viewers cannot drift on schema vocabulary.

The Rust plugin (`surfer/sos-surfer-plugin/`) mirrors the same
constants (`SCHEMA_NAME`, `SCHEMA_VERSION`, `CHART_PATH_MAX_DEPTH`)
in `src/lib.rs`; the constants are kept in lockstep with the Python
modules by hand at schema-version bumps (a §15 amendment to
SOS-08-G-CONCEPTS.md is the gate).

## Per-viewer install

- [`gtkwave/README.md`](./gtkwave/README.md) — Tcl plugin install +
  CLI surface.
- [`surfer/sos-surfer-plugin/README.md`](./surfer/sos-surfer-plugin/README.md) —
  WASM plugin build + install.

## Spec citations

- [SOS-08-G-CONCEPTS.md §5.5](../../../docs/concepts/SOS-08-G-CONCEPTS.md) — PCDN-G-004 in-subrepo distribution.
- [SOS-08-G-CONCEPTS.md §6](../../../docs/concepts/SOS-08-G-CONCEPTS.md) — viewer integration contract.
- [SOS-08-G-CONCEPTS.md §15 wave-3c](../../../docs/concepts/SOS-08-G-CONCEPTS.md) — full GUI integration ratification (2026-05-24).
- INV-S-HDL-G-1 (three-file output coupling).
- INV-S-HDL-G-3 (schema-version header required at line 0).
- INV-S-HDL-G-6 (chart-diff + waveform-diff parity for MCP review).
