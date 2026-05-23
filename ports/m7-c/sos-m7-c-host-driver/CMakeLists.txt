# sos-m7-c-host-driver — host-side adapter binary for the SOS-05 M7 C
# reference port. The C analog of sos-m7-rust-host-driver.
#
# Contract (per SOS-05 §7.1 / SOS-04 §7 inheritance):
#   - Read a wrapped vector JSON from stdin.
#   - Open --port <tty>; write the JSON verbatim (newline-terminated) to
#     UART TX at the configured baud (PCDN-SOS-05-007: 921600 8N1).
#   - Stream \n-terminated JSONL lines from UART RX onto stdout.
#   - Filter the {"__sos_done":true} done sentinel
#     (PCDN-SOS-05-005 / INV-S-PORT-12); never emit it on stdout.
#   - Bail after PCDN-SOS-05-014 (30 s default) wall-clock timeout.
#
# HOST-only: compiles for the operator's Mac/Linux workstation. NOT
# cross-compiled for ARM. No kernel logic links here.

cmake_minimum_required(VERSION 3.20)
project(sos-m7-c-host-driver
    VERSION 0.1.0
    DESCRIPTION "Host-side UART adapter bridging sos-conformance stdin/stdout to the SOS-05 M7 C firmware."
    LANGUAGES C
)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

# Enable compile_commands.json so clang LSPs pick up include paths.
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

add_executable(sos-m7-c-host-driver src/main.c)

# Feature-test macros.
#  - _POSIX_C_SOURCE=200809L: getopt_long, sigaction, etc. on glibc/musl.
#  - _DEFAULT_SOURCE         : exposes BSD-ish extensions (cfmakeraw,
#                              CRTSCTS) on glibc; benign elsewhere.
#  - _DARWIN_C_SOURCE        : on macOS, restores cfmakeraw + Bxxxx
#                              extended bauds when _POSIX_C_SOURCE is
#                              set (else <termios.h> hides them).
target_compile_definitions(sos-m7-c-host-driver PRIVATE
    _POSIX_C_SOURCE=200809L
    _DEFAULT_SOURCE
)
if(APPLE)
    target_compile_definitions(sos-m7-c-host-driver PRIVATE _DARWIN_C_SOURCE)
endif()

target_compile_options(sos-m7-c-host-driver PRIVATE
    -Wall -Wextra -Wpedantic -Werror
    -Wstrict-prototypes -Wmissing-prototypes
    -Wshadow -Wpointer-arith -Wcast-align
)

# On macOS the IOKitLib framework is needed for some serial-port queries
# (not required for basic termios; the adapter does not link IOKit).
