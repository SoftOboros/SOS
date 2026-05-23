# CMakeLists.txt — SOS-05 M7 C reference port.
#
# Per SOS-05-CONCEPTS.md §6.1 (project layout), §6.9 (linker script),
# §8 (build flags + artifact map) and §15 ratification (PCDN-SOS-05-001
# → CMake ≥ 3.20). Skeleton commit: declares the firmware ELF target,
# binds the linker script, post-build emits .bin + .size. The static-
# analysis target lands in phase 2 when src/* bodies are non-trivial.

cmake_minimum_required(VERSION 3.20)

# Per PCDN-SOS-05-004 → C11 with strict (no GNU extensions in the
# project source — though startup.S uses GNU-as syntax, which is the
# assembler's convention, not the C compiler's).
project(sos-m7-c LANGUAGES C ASM)
set(CMAKE_C_STANDARD          11)
set(CMAKE_C_STANDARD_REQUIRED ON)

# Export compile_commands.json so clang LSPs (clangd, IDE plug-ins) pick up
# include paths and language standard. Without this, opening any src/*.c
# in an editor produces "file not found" errors for sos/types.h etc., even
# though `cmake --preset m7-c` configure succeeds.
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
set(CMAKE_C_EXTENSIONS        OFF)

set(SOS_M7_C_SRC
    src/main.c
    src/kernel.c
    src/scripts.c
    src/handlers.c
    src/transport.c
    src/disco_bsp.c
    src/trace.c
    src/json_parser.c
    src/startup.S
)

add_executable(sos-m7-c ${SOS_M7_C_SRC})

target_include_directories(sos-m7-c PRIVATE include)

# Per SOS-05 §6.9 — linker script binds memory regions + section
# placement. Map file is produced alongside the ELF for PR-time size
# review.
set(SOS_M7_C_LINKER_SCRIPT "${CMAKE_CURRENT_SOURCE_DIR}/linker.ld")
target_link_options(sos-m7-c PRIVATE
    -T${SOS_M7_C_LINKER_SCRIPT}
    -Wl,-Map=$<TARGET_FILE:sos-m7-c>.map
)
set_target_properties(sos-m7-c PROPERTIES
    SUFFIX ".elf"
    LINK_DEPENDS ${SOS_M7_C_LINKER_SCRIPT}
)

# Post-build: emit .bin (for st-flash / probe-rs raw flashing) and
# print section sizes per SOS-05 §8 artifact map.
add_custom_command(TARGET sos-m7-c POST_BUILD
    COMMAND ${CMAKE_OBJCOPY} -O binary
            $<TARGET_FILE:sos-m7-c>
            $<TARGET_FILE_DIR:sos-m7-c>/sos-m7-c.bin
    COMMAND ${CMAKE_SIZE} $<TARGET_FILE:sos-m7-c>
    VERBATIM
)

# Per PCDN-SOS-05-005 → clang-tidy with project-local `.clang-tidy`.
# Only attached if clang-tidy is on PATH so the skeleton configure step
# doesn't fail on machines that lack it.
find_program(CLANG_TIDY_BIN clang-tidy)
if(CLANG_TIDY_BIN)
    set_target_properties(sos-m7-c PROPERTIES
        C_CLANG_TIDY "${CLANG_TIDY_BIN}"
    )
endif()
