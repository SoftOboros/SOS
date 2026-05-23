# MTBF.md — `sos_fifo_async`

> **Spec**: `docs/concepts/SOS-08-A-CONCEPTS.md` §6.1 (MTBF treatment paragraph)
> **PCDN**: `PCDN-SOS-08-A-006` (resolved 2026-05-23) — external sign-off in
> `rtl/<primitive>/MTBF.md` with build-wrapper structural validation. No SVA
> `assert`/`cover` for the MTBF claim; the assertion lives here, the build
> wrapper checks the required fields exist.
> **Invariants cited**: INV-SOS-A..H, INV-S-HDL-1..5 (INV-S-HDL-3 specifically
> excludes the synchronizer flop chains from formal scope), INV-S-HDL-A-1..5.

This file is the structural-validation manifest the build wrapper reads to
confirm `sos_fifo_async` carries a current MTBF sign-off. The five required
fields per PCDN-A-006 resolution are: **formula**, **target frequency**,
**target-FF τ value**, **computed MTBF**, **sign-off date**. They appear as
top-level second-level headings (`##`) below; the build wrapper parses by
heading text.

## Formula

The canonical metastability MTBF formula for a `STAGES`-deep synchronizer is:

```
MTBF = exp(t_resolution / tau) / (f_clk * f_data * T0)
```

where:

- `tau` is the target flip-flop's metastability characteristic (the
  exponential resolution time constant of the receiving FF, set by the
  master-slave latch topology + process node).
- `T0` is the metastability aperture (the window width within which a
  setup-violation at the FF input produces a metastable output; a
  process-specific constant).
- `f_clk` is the *receiving-domain* clock frequency (rd_clk for the
  `wr_ptr_gray → rd_clk` chain; wr_clk for the `rd_ptr_gray → wr_clk`
  chain).
- `f_data` is the rate at which the source-domain bus toggles. For
  gray-coded pointers in a FIFO, this is bounded by the source-domain
  clock — every transfer pulse changes exactly one bit.
- `t_resolution = (STAGES − 1) * T_clk_dst − T_setup_dst` is the time
  budget available for metastability resolution after the first
  synchronizer stage; each added stage adds one full destination
  clock period to the budget.

Each added `SYNC_STAGES` raises MTBF by approximately `exp(T_clk_dst / tau)`
— a multi-order-of-magnitude jump per stage for typical FPGA flops where
`tau` is in the 30–150 ps range and `T_clk_dst` is in the 4–10 ns range.

## Target frequency

Assumed worst-case for the SOS-08-A first-target story (ECP5-class Lattice
FPGAs, the SOS-08 §12 (e) bench target):

```
f_clk_wr (assumed worst case)  = 250 MHz   (T_clk = 4.0 ns)
f_clk_rd (assumed worst case)  = 250 MHz   (T_clk = 4.0 ns)
```

The 250 MHz figure is the upper bound for the ECP5 fabric clock at typical
LUT utilization; production deployments at lower clock rates inherit the
same or better MTBF. Build wrappers targeting a *higher* frequency MUST
re-sign-off this document with the new assumption.

## Target-FF τ value

Assumed representative for ECP5-class LUT flops:

```
tau = 100 ps   (representative)
T0  = 5 ps     (representative; metastability aperture)
T_setup_dst = 0.5 ns  (representative; receiving-FF setup time)
```

These are **representative figures only**. The Lattice ECP5 datasheet does
not publish formal τ / T0 numbers (vendor-specific tooling computes
synchronizer MTBF internally); the values above are the order-of-magnitude
estimates used industry-wide for 28 nm / 22 nm class LUT-FF nodes.

A production sign-off targeting an ECP5 deployment with hard MTBF
requirements MUST replace these with vendor-published or measurement-derived
numbers and re-evaluate the computed MTBF below.

## Computed MTBF

With the values above and `SYNC_STAGES = 2` (default):

```
t_resolution = (2 - 1) * 4.0 ns - 0.5 ns = 3.5 ns

exponent     = t_resolution / tau
             = 3.5e-9 / 100e-12
             = 35

MTBF         = exp(35) / (f_clk * f_data * T0)
             = 1.586e15 / (250e6 * 250e6 * 5e-12)
             = 1.586e15 / 3.125e5
             ≈ 5.08e9 seconds
             ≈ 161 years
```

With `SYNC_STAGES = 3`:

```
t_resolution = (3 - 1) * 4.0 ns - 0.5 ns = 7.5 ns
exponent     = 7.5e-9 / 100e-12 = 75
MTBF         = exp(75) / 3.125e5
             ≈ 3.73e32 / 3.125e5
             ≈ 1.19e27 seconds
             ≈ practically infinite — effectively zero-failure
```

The `SYNC_STAGES = 2` result (≈ 161 years per direction) is comfortable for
the first-target ECP5 bench deployment. Build wrappers that target faster
destination clocks, tighter τ, or environments where a 161-year MTBF is
insufficient (medical, automotive, aerospace) MUST raise `SYNC_STAGES` to
3 or 4 and re-sign-off this document with the updated computation.

The synchronizer chain is excluded from formal scope per **INV-S-HDL-3**;
the MTBF claim above IS the verification artefact. Downstream code
consumes only the synchronized signal (the deepest stage's output) — the
chart compiler's bound analysis treats the synchronizer's near-side output
as an oracle per the same invariant.

## Sign-off date

```
Signed-off: 2026-05-23
Signed-off-by: SOS-08-A wave-1 implementation (placeholder)
SYNC_STAGES at sign-off: 2 (default)
Target: ECP5-class Lattice FPGA, worst-case 250 MHz both clocks
```

**Re-sign-off REQUIRED when**:

- The build wrapper sets `SYNC_STAGES > 2`.
- The build wrapper targets a destination clock frequency above 250 MHz.
- The build wrapper targets a different process node (Xilinx 7-series,
  Intel Cyclone, ASIC) — the τ / T0 numbers above are ECP5-representative
  only.
- The downstream consumer's MTBF requirement exceeds the 161-year
  computed figure (the SYNC_STAGES=2 default is fine for ECP5 first-target;
  safety-critical deployments need SYNC_STAGES≥3 with their own sign-off).

Build-wrapper validation MUST emit a hard error if any of the five
required headings above (Formula, Target frequency, Target-FF τ value,
Computed MTBF, Sign-off date) is missing or empty, and a soft warning if
this file has not been touched in over 12 months (signalling potential
stale sign-off).
