// sos-m7-rust build script.
//
// Standard cortex-m-rt pattern: copies the crate's `memory.x` into the
// cargo `OUT_DIR` so the linker (driven by cortex-m-rt's `link.x`) can
// pick it up via the `-L` search path. See cortex-m-rt 0.7 documentation
// and SOS-04-CONCEPTS.md §8 (build artifact map).

use std::env;
use std::fs::File;
use std::io::Write;
use std::path::PathBuf;

fn main() {
    let out = &PathBuf::from(env::var_os("OUT_DIR").unwrap());
    File::create(out.join("memory.x"))
        .unwrap()
        .write_all(include_bytes!("memory.x"))
        .unwrap();
    println!("cargo:rustc-link-search={}", out.display());

    // Emit the cortex-m-rt linker-script directive via build.rs rather
    // than `.cargo/config.toml` rustflags. The parent softoboros workspace
    // sets `RUSTFLAGS` in its user-level `~/.cargo/config.toml [env]`
    // table to inject coverage instrumentation for host crates; cargo
    // treats a SET `RUSTFLAGS` env var (even when empty, as in the
    // canonical `RUSTFLAGS="" cargo build ...` invocation per
    // SOS-04-CONCEPTS.md §8) as fully overriding ALL `[target.*]`
    // rustflags from every config file in the hierarchy — including
    // the crate-local and workspace-root configs that ship `-Tlink.x`.
    // The resulting ELF lacks `.text`/`.bss`/`.data`/`.vector_table` (a
    // `.comment` + `.ARM.attributes`-only artifact). `cargo:rustc-link-arg`
    // bypasses the RUSTFLAGS path entirely and lands the directive on
    // the linker invocation regardless of env state. See cortex-m-rt
    // 0.7's `link.x` documentation.
    println!("cargo:rustc-link-arg=-Tlink.x");

    println!("cargo:rerun-if-changed=memory.x");
    println!("cargo:rerun-if-changed=build.rs");
}
