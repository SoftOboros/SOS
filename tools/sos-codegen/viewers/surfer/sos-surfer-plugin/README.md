# sos-surfer-plugin — SOS-08-G Surfer overlay plugin (wave-3c)

WebAssembly plugin for the [Surfer](https://surfer-project.org/) waveform
viewer that renders [SOS-08-G](../../../../docs/concepts/SOS-08-G-CONCEPTS.md)
annotation-overlay (`.annotations.jsonl`) files as chart-state markers +
per-chart_path overlay tracks + invariant-fire highlights on the
waveform timeline.

This crate is the **wave-3c** GUI-integration deliverable. Wave-1 / wave-2
shipped CLI scaffolds (`sos_surfer_ext.py`) that produce Surfer
command-scripts a user could load manually. Wave-3c lands the
in-process plugin so Surfer auto-discovers the overlay and installs
the badges as the user scrubs the timeline.

## Status

🟢 **Source scaffold landed 2026-05-24 (wave-3c).** Host-target
unit tests pass; the actual `.wasm` artifact requires the
`wasm32-unknown-unknown` Rust target + Surfer plugin SDK at build
time (see [Build](#build)). The Surfer plugin-API is itself evolving;
the manifest's `surfer-api = ">=0.3.0, <0.5.0"` compatibility window
will tighten as the upstream SDK stabilises.

## Build

### Host-target check (no WASM toolchain required)

```sh
cd tools/sos-codegen/viewers/surfer/sos-surfer-plugin
cargo check
RUSTFLAGS="" cargo test     # see RUSTFLAGS note below
```

This validates the source structure + runs the unit tests against the
host target — useful for CI without needing the WASM toolchain.

> **RUSTFLAGS note**: contributors who have shell-level `RUSTFLAGS`
> targeting embedded boards (e.g. `-Clink-arg=-fuse-ld=mold` as
> documented in the parent CLAUDE.md) MUST clear the env var for
> host-target `cargo test` on macOS. The mold linker is Linux-only;
> macOS `cc` rejects the flag. The crate's `.cargo/config.toml`
> declares empty per-target rustflags, but shell `RUSTFLAGS` env
> overrides Cargo config so the explicit `RUSTFLAGS=""` is required.

### Surfer plugin artifact (release WASM)

```sh
rustup target add wasm32-unknown-unknown
cd tools/sos-codegen/viewers/surfer/sos-surfer-plugin
cargo build --release --target wasm32-unknown-unknown --features wasm
```

Output artifact:

```
target/wasm32-unknown-unknown/release/sos_surfer_plugin.wasm
```

## Install

Surfer discovers plugins under `~/.config/surfer/plugins/<plugin-name>/`
(Linux/macOS) or `%APPDATA%\surfer\plugins\<plugin-name>\` (Windows).
Copy the build artifact + `surfer-plugin.toml` into a directory under
that path:

```sh
mkdir -p ~/.config/surfer/plugins/sos-surfer-plugin
cp target/wasm32-unknown-unknown/release/sos_surfer_plugin.wasm \
   surfer-plugin.toml \
   ~/.config/surfer/plugins/sos-surfer-plugin/
```

Restart Surfer; the plugin should appear in `Plugins → SOS-08-G` and
auto-load when a waveform with a co-located `.annotations.jsonl`
overlay is opened.

## How it works

1. Surfer's plugin host loads the WASM artifact and reads the
   `surfer-plugin.toml` manifest.
2. When the user opens a waveform file, the host calls the plugin's
   `discover_waveform_paths` entry point with the loaded waveform's
   path; the plugin scans the same directory for `.annotations.jsonl`
   files whose `_meta.waveform_prefix` matches (per SOS-08-G §6 (a)
   co-locate semantics, wave-3b amendment).
3. For each matching overlay, the host calls `render_overlay`; the
   plugin parses the JSONL records, validates the schema header per
   INV-S-HDL-G-3, and returns a `Vec<SurferCommand>` the host
   consumes to install markers + overlay tracks + invariant-fire
   highlights.

## SOS-08-G §6 conformance gates

| Gate | Description | Status |
|------|-------------|--------|
| (a) MUST | Co-locate overlay via `_meta.waveform_prefix` | ✅ wave-3c |
| (b) MUST | Schema-version-aware | ✅ wave-3c (`parse_overlay`) |
| (c) MUST | Per-record render (Marker per record) | ✅ wave-3c |
| (d) SHOULD | Chart-path navigation (overlay tracks) | ✅ wave-3c |
| (e) SHOULD | Invariant-fire highlighting | ✅ wave-3c |
| (f) SHOULD | Vector-citation drill-down | ⏸ wave-3c-future (Surfer link-back API) |

## Source layout

```
sos-surfer-plugin/
├── Cargo.toml             — crate manifest (host check + WASM build)
├── surfer-plugin.toml     — Surfer plugin-host manifest
├── README.md              — this file
└── src/
    └── lib.rs             — plugin implementation
```

## License

MIT (matches the SOS repo root licence).
