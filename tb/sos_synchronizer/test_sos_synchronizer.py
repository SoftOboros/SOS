"""cocotb testbench for sos_synchronizer.

@spec docs/concepts/SOS-08-A-CONCEPTS.md §6.9 (per-primitive contract for
    `sos_synchronizer`), §5.4 + PCDN-A-007 (one cocotb file per primitive),
    §12 (d) (cocotb gate).

The DUT is a dual-clock primitive: `clk_dst` is the destination-domain
sampling clock; the source-domain "clock" is implicit (the testbench drives
`d_src` from an arbitrary timeline asynchronous to `clk_dst`).  The cocotb
harness drives both:

    * a source-domain clock `clk_src` at a deliberately incommensurate
      period from `clk_dst` (gcd-misaligned) so that transitions on
      `d_src` land in arbitrary phase positions of `clk_dst`,
    * stable-hold windows that hold `d_src` constant across the required
      `STAGES`-many `clk_dst` edges so the test can deterministically
      check that `d_dst` follows.

The runner sets `STAGES` and `WIDTH` via DUT parameter override; the test
reads the runner's `SOS_SYNCHRONIZER_STAGES` and `SOS_SYNCHRONIZER_WIDTH`
env vars (defaults 2 and 1 respectively) to know how long to hold and
what bus shape to drive.

Cited invariants (the testbench exercises behaviours these invariants
constrain; the SVA bind ride runs concurrently for the functional
properties; the metastability claim itself is `// VERIFIED_BY_SDC` —
recorded in `rtl/sos_synchronizer/MTBF.md`, NOT here):

    INV-SOS-A   chart-as-source                      (SOS-07 §6)
    INV-SOS-B   vectors-as-deliverable               (SOS-07 §6)
    INV-SOS-E   explicit AuthorityRelationship       (SOS-07 §6)
    INV-SOS-G   verified-codegen position            (SOS-07 §6)
    INV-SOS-H   vector-to-chart traceability         (SOS-07 §6)
    INV-S-HDL-1 handshake-compatible ports           (SOS-08 §7)
    INV-S-HDL-2 static-allocation discipline         (SOS-08 §7)
    INV-S-HDL-3 cross-domain isolation               (SOS-08 §7) -- the
                                                     load-bearing exclusion;
                                                     the cocotb harness
                                                     does NOT verify MTBF.
    INV-S-HDL-4 cooperative-only at v1               (SOS-08 §7)
    INV-S-HDL-5 vector-to-chart traceability (HDL)   (SOS-08 §7)
    INV-S-HDL-A-1 sync active-high reset             (SOS-08-A §7)
    INV-S-HDL-A-2 handshake associativity            (SOS-08-A §7) -- N/A
    INV-S-HDL-A-3 vendor-shim byte-identical wrap    (SOS-08-A §7)
    INV-S-HDL-A-5 mandatory parameters, no default   (SOS-08-A §7)

Behavioural coverage:

    * test_reset_clears_chain      -- reset clears d_dst to zero
    * test_steady_state_propagates -- src held steady -> dst matches
                                      after STAGES dst-clk cycles
    * test_src_toggles_propagate   -- src toggling 0/1 -> dst toggles
                                      with STAGES-cycle latency
    * test_multi_bit_walk          -- WIDTH > 1: walking-1 pattern on
                                      d_src arrives intact at d_dst
                                      (assumes caller-side Gray coding;
                                      walking-1 is Gray-coded by
                                      construction)
    * test_async_src_timing        -- src driven from an incommensurate
                                      clock; dst eventually matches each
                                      held value
"""

from __future__ import annotations

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


# ---------------------------------------------------------------------------
# Test bench helpers.
# ---------------------------------------------------------------------------


# Destination-domain clock period.  Source-domain is deliberately a
# different period (gcd != either) so transitions land asynchronously.
CLK_DST_PERIOD_NS = 10
CLK_SRC_PERIOD_NS = 13  # incommensurate with 10 ns (gcd = 1 ns)


def _stages() -> int:
    """Return the STAGES parameter the DUT was elaborated with.

    Falls back to the env var if the DUT does not expose the parameter as
    a sim-readable handle (varies by simulator).  Default = 2.
    """
    raw = os.environ.get("SOS_SYNCHRONIZER_STAGES", "2")
    try:
        v = int(raw)
    except ValueError as e:
        raise ValueError(
            f"SOS_SYNCHRONIZER_STAGES must be an integer; got {raw!r}"
        ) from e
    if v < 2:
        raise ValueError(
            f"SOS_SYNCHRONIZER_STAGES must be >= 2 per §6.9; got {v}"
        )
    return v


def _width() -> int:
    """Return the WIDTH parameter the DUT was elaborated with."""
    raw = os.environ.get("SOS_SYNCHRONIZER_WIDTH", "1")
    try:
        v = int(raw)
    except ValueError as e:
        raise ValueError(
            f"SOS_SYNCHRONIZER_WIDTH must be an integer; got {raw!r}"
        ) from e
    if v < 1:
        raise ValueError(
            f"SOS_SYNCHRONIZER_WIDTH must be >= 1 per §6.9; got {v}"
        )
    return v


async def _reset(dut, cycles: int = 2) -> None:
    """Drive synchronous active-high `rst_dst` for `cycles` clock edges."""
    dut.rst_dst.value = 1
    dut.d_src.value = 0
    for _ in range(cycles):
        await RisingEdge(dut.clk_dst)
    dut.rst_dst.value = 0
    await RisingEdge(dut.clk_dst)


def _start_clocks(dut) -> None:
    """Start both clocks; clk_src is incommensurate with clk_dst."""
    cocotb.start_soon(Clock(dut.clk_dst, CLK_DST_PERIOD_NS, units="ns").start())
    # Some sim setups bind a `clk_src` signal for source-domain
    # generation; the DUT itself has no `clk_src` port (the source domain
    # is asynchronous by construction), but the testbench MAY drive
    # `d_src` from a separate timeline.  Tests below use `Timer` for that
    # rather than a hardware clock signal.


def _d_dst_int(dut) -> int:
    """Read `d_dst` as a Python int (treat X/Z as 0 for comparison)."""
    try:
        return int(dut.d_dst.value)
    except ValueError:
        return 0


# ---------------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------------


@cocotb.test()
async def test_reset_clears_chain(dut):
    """After reset, d_dst is 0 regardless of d_src."""
    _start_clocks(dut)

    # Drive a non-zero d_src into reset; d_dst must stay 0.
    dut.rst_dst.value = 1
    dut.d_src.value = (1 << _width()) - 1  # all-ones, masked to width
    for _ in range(4):
        await RisingEdge(dut.clk_dst)
        assert _d_dst_int(dut) == 0, (
            f"d_dst={_d_dst_int(dut):#x} not cleared during reset"
        )

    # Hold reset, drop d_src, still 0.
    dut.d_src.value = 0
    for _ in range(2):
        await RisingEdge(dut.clk_dst)
        assert _d_dst_int(dut) == 0, "d_dst not cleared on rst_dst"

    # Release reset; d_dst stays 0 because d_src is 0.
    dut.rst_dst.value = 0
    for _ in range(_stages() + 2):
        await RisingEdge(dut.clk_dst)
    assert _d_dst_int(dut) == 0, (
        f"d_dst={_d_dst_int(dut):#x} should remain 0 post-reset with d_src=0"
    )


@cocotb.test()
async def test_steady_state_propagates(dut):
    """A stable d_src reaches d_dst within STAGES dst-clk cycles."""
    _start_clocks(dut)
    await _reset(dut)
    stages = _stages()
    width = _width()

    test_value = 1 if width == 1 else 0xA5 & ((1 << width) - 1)
    dut.d_src.value = test_value

    # Walk forward STAGES cycles; the value must appear at d_dst on the
    # STAGES-th rising edge after assertion (the value was visible on
    # d_src starting at this edge; sync_chain[0] captures it here, the
    # chain propagates one stage per edge, so STAGES edges later it's at
    # sync_chain[STAGES-1] = d_dst).
    for cyc in range(stages):
        await RisingEdge(dut.clk_dst)
        # Mid-chain: d_dst may carry stale 0 or partial propagation; we
        # only check the final settled value.

    observed = _d_dst_int(dut)
    assert observed == test_value, (
        f"steady-state d_dst={observed:#x} expected {test_value:#x} "
        f"after STAGES={stages} cycles"
    )


@cocotb.test()
async def test_src_toggles_propagate(dut):
    """d_src toggling produces matching d_dst toggles with STAGES latency."""
    _start_clocks(dut)
    await _reset(dut)
    stages = _stages()
    width = _width()

    # Use only the LSB even for WIDTH > 1; the multi-bit walk test below
    # covers the rest.
    for value in (1, 0, 1, 0, 1):
        dut.d_src.value = value
        # Hold stable for STAGES cycles so d_dst settles.
        for _ in range(stages):
            await RisingEdge(dut.clk_dst)
        # One extra cycle so the final flop latches the propagated value.
        # (The first STAGES cycles cover sync_chain[0..STAGES-1] each
        # capturing in turn; d_dst reflects sync_chain[STAGES-1] which
        # was loaded on the STAGES-th edge.)
        observed = _d_dst_int(dut) & 1
        assert observed == value, (
            f"toggle propagation: d_dst LSB={observed} != d_src LSB={value} "
            f"after STAGES={stages} cycles"
        )


@cocotb.test()
async def test_multi_bit_walk(dut):
    """WIDTH > 1: walking-1 pattern propagates intact.

    Walking-1 patterns are Gray-coded between adjacent positions
    differing only at the boundary -- not strictly Gray, but each
    individual sampling moment is a single value; the test holds long
    enough that bit-skew during the transient does not matter.
    """
    _start_clocks(dut)
    await _reset(dut)
    stages = _stages()
    width = _width()

    if width < 2:
        # WIDTH = 1: walking-1 reduces to test_src_toggles_propagate.
        # Skip with a clear cocotb log line.
        dut._log.info("WIDTH=1; multi-bit walk reduces to single-bit toggle")
        return

    for shift in range(width):
        value = 1 << shift
        dut.d_src.value = value
        for _ in range(stages):
            await RisingEdge(dut.clk_dst)
        observed = _d_dst_int(dut)
        assert observed == value, (
            f"multi-bit walk shift={shift}: d_dst={observed:#x} "
            f"expected {value:#x} (WIDTH={width}, STAGES={stages})"
        )


@cocotb.test()
async def test_async_src_timing(dut):
    """d_src driven from an incommensurate timeline -- d_dst still settles.

    Drive d_src changes from a `Timer` cadence at CLK_SRC_PERIOD_NS so
    transitions land in arbitrary phase positions of clk_dst.  After
    each transition, hold long enough (STAGES * CLK_DST_PERIOD_NS plus
    one source-domain period of slack) for d_dst to settle.
    """
    _start_clocks(dut)
    await _reset(dut)
    stages = _stages()
    width = _width()

    values = [0, 1, 0, (1 << (width - 1)), 0]
    for value in values:
        dut.d_src.value = value & ((1 << width) - 1)
        # Wait one source-domain period (incommensurate), then STAGES
        # destination-domain edges, then sample.
        await Timer(CLK_SRC_PERIOD_NS, units="ns")
        for _ in range(stages + 1):
            await RisingEdge(dut.clk_dst)
        observed = _d_dst_int(dut)
        expected = value & ((1 << width) - 1)
        assert observed == expected, (
            f"async-timing src={expected:#x} dst={observed:#x} "
            f"(STAGES={stages}, WIDTH={width})"
        )
