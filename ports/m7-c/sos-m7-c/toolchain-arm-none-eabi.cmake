# toolchain-arm-none-eabi.cmake — SOS-05 M7 C port toolchain.
#
# Per SOS-05-CONCEPTS.md §8 (build flags) and PCDN-SOS-05-006
# (`arm-none-eabi-gcc 13.2.Rel1`). Loaded via CMakePresets.json's
# `toolchainFile` field. Skeleton commit: bench-target flags only;
# host-test cross-toolchains land in a follow-up if/when host-side
# spot-checks become normative (§6.1 tests/host/ is non-normative at v1).

set(CMAKE_SYSTEM_NAME      Generic)
set(CMAKE_SYSTEM_PROCESSOR ARM)

# PCDN-SOS-05-006 → arm-none-eabi-gcc 13.2.Rel1. The pinned ARM-official
# install lives at ~/.local/opt/arm-gnu-toolchain-13.2.Rel1-darwin-arm64-
# arm-none-eabi/. If the SOS_M7_C_TOOLCHAIN_ROOT cache var is set we use
# that explicit prefix; otherwise we look on PATH (where the user's host
# default arm-none-eabi-gcc may be a different version — that path falls
# back to the ratification-commit gate §12.2 (k) for version policing).
if(NOT DEFINED SOS_M7_C_TOOLCHAIN_ROOT)
    set(SOS_M7_C_TOOLCHAIN_ROOT "$ENV{HOME}/.local/opt/arm-gnu-toolchain-13.2.Rel1-darwin-arm64-arm-none-eabi" CACHE PATH "Pinned arm-none-eabi toolchain prefix (PCDN-SOS-05-006)")
endif()

if(EXISTS "${SOS_M7_C_TOOLCHAIN_ROOT}/bin/arm-none-eabi-gcc")
    set(CMAKE_C_COMPILER   "${SOS_M7_C_TOOLCHAIN_ROOT}/bin/arm-none-eabi-gcc")
    set(CMAKE_ASM_COMPILER "${SOS_M7_C_TOOLCHAIN_ROOT}/bin/arm-none-eabi-gcc")
    set(CMAKE_OBJCOPY      "${SOS_M7_C_TOOLCHAIN_ROOT}/bin/arm-none-eabi-objcopy" CACHE FILEPATH "objcopy")
    set(CMAKE_SIZE         "${SOS_M7_C_TOOLCHAIN_ROOT}/bin/arm-none-eabi-size"    CACHE FILEPATH "size")
else()
    # Fall back to PATH; --version check at first compile-time policing.
    set(CMAKE_C_COMPILER   arm-none-eabi-gcc)
    set(CMAKE_ASM_COMPILER arm-none-eabi-gcc)
    set(CMAKE_OBJCOPY      arm-none-eabi-objcopy CACHE FILEPATH "objcopy")
    set(CMAKE_SIZE         arm-none-eabi-size    CACHE FILEPATH "size")
endif()

# Skip the host-OS test-compile: target produces no host-runnable
# executable. Trust the toolchain by declaration; the actual link
# happens at build time and fails noisily there if anything is wrong.
set(CMAKE_C_COMPILER_WORKS   1)
set(CMAKE_ASM_COMPILER_WORKS 1)
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)

# Common architecture flags (SOS-05 §8). FPU is fpv5-d16 hard ABI; -mcpu
# pins to Cortex-M7 for codegen. Per PCDN-SOS-05-006 the GCC version is
# the build-side surface that pins behaviour; flags pin architecture.
set(SOS_M7_C_ARCH_FLAGS "-mcpu=cortex-m7 -mthumb -mfpu=fpv5-d16 -mfloat-abi=hard")

set(CMAKE_C_FLAGS_INIT
    "${SOS_M7_C_ARCH_FLAGS} \
     -ffunction-sections -fdata-sections \
     -fno-common \
     -Wall -Wextra -Wpedantic -Werror \
     -Wstrict-prototypes -Wmissing-prototypes \
     -Wshadow -Wpointer-arith -Wcast-align \
     -Wno-unused-parameter"
)
set(CMAKE_ASM_FLAGS_INIT "${SOS_M7_C_ARCH_FLAGS}")

# Per SOS-05 §8: -nostartfiles (the port supplies Reset_Handler),
# --gc-sections + map output. PCDN-SOS-05-002 ratified picolibc, but
# ARM's 13.2.Rel1 tarball ships with newlib (not picolibc); we use
# --specs=nano.specs + --specs=nosys.specs as the v1 substitute so the
# pinned toolchain builds out of the box. Migrating to picolibc is a
# follow-up amendment once the user vendors picolibc separately or
# rebuilds the toolchain with picolibc included.
set(CMAKE_EXE_LINKER_FLAGS_INIT
    "${SOS_M7_C_ARCH_FLAGS} \
     -nostartfiles \
     --specs=nano.specs \
     --specs=nosys.specs \
     -Wl,--gc-sections"
)

# Debug build inherits architecture flags; only opt-level / debug
# symbols differ. The presets file selects build type.
set(CMAKE_C_FLAGS_RELEASE_INIT "-Os -g3")
set(CMAKE_C_FLAGS_DEBUG_INIT   "-Og -g3")
