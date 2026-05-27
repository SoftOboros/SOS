# sos-codegen

SOS-06-A reference codegen tool. Consumes `rtos_kernel.scxml` and emits the
chart-driven `scripts.rs` and `scripts.c` source trees that the M7 ports
embed.

Specified by [`docs/concepts/SOS-06-CONCEPTS.md`](../../docs/concepts/SOS-06-CONCEPTS.md)
(normative methodology) and [`docs/concepts/SOS-06-A-EVALUATION.md`](../../docs/concepts/SOS-06-A-EVALUATION.md)
(ratified toolchain choice — scjson + Jinja2 templates, with iState as the
upstream SCXML generation surface).

## Quick start

From the SOS subrepo root:

```bash
pip install -r tools/sos-codegen/requirements.txt
python tools/sos-codegen/main.py --target rust --out ports/m7-rust/sos-m7-rust/src/scripts.rs
python tools/sos-codegen/main.py --target c    --out ports/m7-c/sos-m7-c/src/scripts.c
```

Or emit both in one invocation:

```bash
python tools/sos-codegen/main.py --target both --out-rust ports/m7-rust/sos-m7-rust/src/scripts.rs --out-c ports/m7-c/sos-m7-c/src/scripts.c
```

SOS-13 adds the Rust-only verified-strip profile:

```bash
python tools/sos-codegen/main.py --target rust --profile verified-strip --out ports/m7-rust/sos-m7-rust/src/scripts.rs --verified-audit verified-strip-audit.jsonl
```

When `--profile` is omitted, the tool defaults to `dev-keep`.

## Pipeline

```
iState document          ← chart-author edits land here (future)
  ↓ istate_get_xml
rtos_kernel.scxml        ← canonical artifact (SOS-00 INV-S1)
  ↓ lxml load + AST normalisation (or scjson convert; see §Implementation)
scjson-shaped AST (dict)
  ↓ Jinja2 templates
ports/m7-rust/.../scripts.rs   ← byte-equivalent to bench-validated hand-written
ports/m7-c/.../scripts.c       ← byte-equivalent to bench-validated hand-written
```

## Implementation note (v1)

The v1 tool uses an in-process lxml-based loader that produces a
scjson-shaped AST dict (matching the conventions the upstream scjson family
uses). This avoids a hard dependency on the scjson submodule at first-run
time. A future amendment migrates the loader to a `scjson convert` shell-out
once scjson is wired into the SOS build properly.

## Exit codes

| Exit | Meaning |
|---:|---|
| `0` | Successful emission. |
| `1` | Chart load / parse error. |
| `2` | Template render error. |
| `3` | Invocation / IO error (missing file, missing dep). |
