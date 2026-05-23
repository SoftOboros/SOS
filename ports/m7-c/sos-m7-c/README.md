# sos-m7-c

The SOS-05 M7 C reference port. Cross-compiled with `arm-none-eabi-gcc`
and flashed to the CM7 core of the STM32H747I-DISCO board.

**Status:** skeleton (this commit). `cmake --preset m7-c -B build/m7-c`
configures cleanly. The build step (`cmake --build --preset m7-c`)
requires `arm-none-eabi-gcc 13.2.Rel1` per PCDN-SOS-05-006 and picolibc
per PCDN-SOS-05-002; both must be installed before the firmware link
succeeds. Kernel bodies, JSONL writer, transport implementation, the
PendSV asm, and the host-side adapter all land in subsequent phases.

## See also

- [`docs/concepts/SOS-05-CONCEPTS.md`](../../../docs/concepts/SOS-05-CONCEPTS.md) — ratified 2026-05-19; load-bearing spec for this port.
- [`docs/concepts/SOS-00-CONCEPTS.md`](../../../docs/concepts/SOS-00-CONCEPTS.md) — parent concepts; §6 is the M7 primitive contract this project realises.
- [`docs/concepts/SOS-02-CONCEPTS.md`](../../../docs/concepts/SOS-02-CONCEPTS.md) — §7 trace wire format the on-device writer matches byte-for-byte.
- [`ports/m7-rust/sos-m7-rust/`](../../m7-rust/sos-m7-rust/) — parallel-sibling Rust port (SOS-04). Same chart, same invariants, same conformance vectors.

## Required toolchain

| Tool | Version (pinned by) | Purpose |
| --- | --- | --- |
| `arm-none-eabi-gcc` | `13.2.Rel1` (PCDN-SOS-05-006) | Cross-compile firmware ELF |
| `arm-none-eabi-objcopy` / `arm-none-eabi-size` | matched to gcc release | Post-build `.bin` / size report |
| `picolibc` | toolchain-bundled or distro-packaged (PCDN-SOS-05-002) | libc surface (`memcpy`, `snprintf`, `_sbrk` stub) |
| `cmake` | `≥ 3.20` (PCDN-SOS-05-001) | Build system |
| `clang-tidy` | any recent release (PCDN-SOS-05-005) | Static analysis (optional at configure time; required for `--target tidy` builds at phase 2) |

## Build

```bash
# From this directory:
cmake --preset m7-c            # configures into build/m7-c/
cmake --build --preset m7-c    # cross-compiles firmware ELF

# Debug build (for in-bench probe-rs sessions)
cmake --preset m7-c-debug
cmake --build --preset m7-c-debug
```

The configure step (`cmake --preset m7-c`) succeeds without a working
`arm-none-eabi-gcc` installation — the toolchain file sets
`CMAKE_C_COMPILER_WORKS=1` to bypass the host-OS test-compile. The
build step itself requires the toolchain to be present and on `PATH`.

## Flash + run (bench-authorisation required)

Per the parent CLAUDE.md "Bench-hardware authorization" rule, flashing
the disco-analyzer board requires explicit per-round operator
authorisation:

```bash
probe-rs run --chip STM32H747XIHx --core 0 \
    build/m7-c/sos-m7-c.elf
```

## Implementation roadmap

1. **Skeleton (this commit).** CMakeLists + toolchain file + linker
   script + module-shell `.c` files with empty bodies + the ARMv7-M
   vector table in `src/startup.S`. CMake configure exits 0; build step
   needs the pinned toolchain to be installed.
2. **Kernel body + BSP.** `sos_bsp_init` (clock tree, GPIO AF for
   USART1, SCB priority grouping), `sos_kernel_init` (pool zero, NVIC
   priorities, SysTick), `transport.c` USART1 RX/TX bring-up,
   `SysTick_Handler` body, PendSV pend logic.
3. **JSONL writer + PendSV.** Hand-rolled `sos_trace_write_record`
   matching SOS-02 §7 field order byte-for-byte; naked-function PendSV
   body inspecting `EXC_RETURN[4]`; byte-stability unit tests in
   a host crate (parallel to SOS-04 PCDN-SOS-04-018).
4. **Host-side adapter + bench-run.** `sos-m7-c-host/` C adapter
   bridging the conformance harness's stdin/stdout to USART1; first
   bench run against the SOS-03 seed suite.

## Layout

```
ports/m7-c/sos-m7-c/
├── CMakeLists.txt
├── CMakePresets.json
├── toolchain-arm-none-eabi.cmake
├── linker.ld
├── .clang-tidy
├── include/
│   └── sos/
│       ├── bsp.h
│       ├── event.h
│       ├── kernel.h
│       ├── sos.h       # convenience umbrella (PCDN-SOS-05-003 mitigation)
│       ├── trace.h
│       └── types.h
└── src/
    ├── main.c
    ├── kernel.c
    ├── handlers.c
    ├── transport.c
    ├── disco_bsp.c
    ├── trace.c
    └── startup.S       # ARMv7-M vector table + Reset_Handler
```
