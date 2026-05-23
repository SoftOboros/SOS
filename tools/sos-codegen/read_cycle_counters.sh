#!/bin/sh
# read_cycle_counters.sh — bench-side post-mortem cycle-count readout.
#
# Reads the `MACROSTEP_CYCLES_*` + `MACROSTEP_COUNT` counters from DTCM
# via probe-rs after a conformance run, then prints the mean cycles
# per macrostep. Mirrors the layout in ports/m7-rust/sos-m7-rust/src/
# main.rs (Rust) and ports/m7-c/sos-m7-c/src/main.c (C).
#
# Usage:
#   tools/sos-codegen/read_cycle_counters.sh rust
#   tools/sos-codegen/read_cycle_counters.sh c
#
# The Rust addresses are determined post-link via:
#   arm-none-eabi-nm target/.../sos-m7-rust | grep MACROSTEP
# The C addresses are determined the same way:
#   arm-none-eabi-nm ports/m7-c/sos-m7-c/build/m7-c/sos-m7-c.elf | grep sos_macrostep

set -e
TARGET="${1:-rust}"

case "$TARGET" in
    rust)
        ELF="target/thumbv7em-none-eabihf/release/sos-m7-rust"
        if [ ! -f "$ELF" ]; then
            echo "ERROR: $ELF not built" >&2
            exit 1
        fi
        # Discover addresses from the ELF symbol table.
        ADDR_COUNT=$(arm-none-eabi-nm "$ELF" | grep "MACROSTEP_COUNT" | awk '{print "0x"$1}')
        ADDR_LO=$(arm-none-eabi-nm "$ELF" | grep "MACROSTEP_CYCLES_LO" | awk '{print "0x"$1}')
        ADDR_HI=$(arm-none-eabi-nm "$ELF" | grep "MACROSTEP_CYCLES_HI" | awk '{print "0x"$1}')
        ;;
    c)
        ELF="ports/m7-c/sos-m7-c/build/m7-c/sos-m7-c.elf"
        if [ ! -f "$ELF" ]; then
            echo "ERROR: $ELF not built" >&2
            exit 1
        fi
        ADDR_COUNT=$(arm-none-eabi-nm "$ELF" | grep "sos_macrostep_count$" | awk '{print "0x"$1}')
        ADDR_LO=$(arm-none-eabi-nm "$ELF" | grep "sos_macrostep_cycles_lo$" | awk '{print "0x"$1}')
        ADDR_HI=$(arm-none-eabi-nm "$ELF" | grep "sos_macrostep_cycles_hi$" | awk '{print "0x"$1}')
        ;;
    *)
        echo "Usage: $0 {rust|c}" >&2
        exit 2
        ;;
esac

echo "TARGET=$TARGET"
echo "  count @ $ADDR_COUNT"
echo "  lo    @ $ADDR_LO"
echo "  hi    @ $ADDR_HI"

# Read each counter as a single u32.
COUNT_HEX=$(probe-rs read --chip STM32H747XIHx --core 0 b32 "$ADDR_COUNT" 1 2>/dev/null | tr -d '\n ')
LO_HEX=$(probe-rs read --chip STM32H747XIHx --core 0 b32 "$ADDR_LO" 1 2>/dev/null | tr -d '\n ')
HI_HEX=$(probe-rs read --chip STM32H747XIHx --core 0 b32 "$ADDR_HI" 1 2>/dev/null | tr -d '\n ')

COUNT_DEC=$(printf "%d\n" "0x$COUNT_HEX")
LO_DEC=$(printf "%d\n" "0x$LO_HEX")
HI_DEC=$(printf "%d\n" "0x$HI_HEX")

# Combine 64-bit total via shell arithmetic.
TOTAL=$(( (HI_DEC << 32) | LO_DEC ))

if [ "$COUNT_DEC" -gt 0 ]; then
    MEAN=$(( TOTAL / COUNT_DEC ))
else
    MEAN=0
fi

echo ""
echo "count = $COUNT_DEC dispatches"
echo "total = $TOTAL cycles"
echo "mean  = $MEAN cycles/macrostep"
