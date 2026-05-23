# MTBF sign-off — `sos_synchronizer`

> **THE canonical CDC primitive MTBF document for SOS-08-A.** Every other CDC
> sub-primitive that names `sos_synchronizer` in its composition path
> (`sos_fifo_async`, `sos_dpram_arb` dual-clock mode) inherits this calculation
> for its synchronizer-FF chains per INV-S-HDL-3 (cross-domain isolation
> excluded from formal model — MTBF claim is physical and lives here).

@spec [`docs/concepts/SOS-08-A-CONCEPTS.md`](../../docs/concepts/SOS-08-A-CONCEPTS.md)
§5.3, §6.9, §15 (2026-05-23 PCDN-A-006 resolution).

## Status

| Field | Value |
|---|---|
| Sign-off status | **PENDING** — placeholder MTBF computed for the worked example below; final sign-off after target-FPGA τ measurement |
| Sign-off date | _TBD_ (insert ISO-8601 date when target-FPGA τ value is measured / vendor-curve-cited) |
| Sign-off owner | _TBD_ (initiative phase owner countersigns) |

The build wrapper checks for the existence of this file and the structural
presence of the **Formula**, **Target frequency**, **Target-FF τ**,
**Computed MTBF**, and **Sign-off date** sections (PCDN-A-006 structural
validation). The wrapper does NOT verify the numeric correctness of the
calculation — that is the sign-off owner's responsibility.

## Formula

The metastability MTBF for an N-stage synchronizer chain is

```
MTBF  =  e^( T · F_clk · F_data · τ )  /  ( F_clk · F_data · T0 )
```

following Stoll & Storey (and the Veendrick / Kleeman canonical form), where

- **T**         = resolution time budget available per stage (s).
                  For an N-stage synchronizer at clock period `T_clk = 1/F_clk`,
                  `T` is the per-stage portion of the metastability resolution
                  window: `T ≈ (STAGES - 1) · T_clk - t_setup - t_clk_to_q`.
                  For a 2-stage chain at 250 MHz: `T_clk = 4 ns`, conservative
                  `t_setup + t_clk_to_q ≈ 0.4 ns` → `T ≈ 3.6 ns`.
                  For a 3-stage chain: `T ≈ 2 · T_clk − overhead ≈ 7.6 ns`.
- **F_clk**     = destination-domain clock frequency (Hz).
- **F_data**    = source-domain data transition rate (Hz).  Conservative
                  upper bound: assume `F_data = F_src_clk / 2` (one transition
                  per source-domain cycle).
- **τ** (tau)   = target-FF metastability resolution time constant (s).
                  Process-node and vendor specific.  Typical published values:
                    * Xilinx 7-series / UltraScale: τ ≈ 30–100 ps
                    * Intel Cyclone V / Stratix 10: τ ≈ 50–150 ps
                    * Lattice ECP5 (SOS-08-A first target):
                      τ ≈ 100 ps (worked example below — vendor τ table not
                      published in datasheet; this is a representative
                      value, NOT a vendor guarantee)
- **T0**        = metastability window aperture time (s).  Conservative value
                  for 28 nm / 40 nm FPGAs: `T0 ≈ 1 ps`.

This is the Stoll/Storey form; it gives a result in **seconds-per-event**
which divides into the elapsed simulation time per "expected metastability
event escaping the chain."  Conventional engineering practice quotes the
inverse `1 / MTBF` as the failure rate and the `MTBF` itself in years.

## Worked example — Lattice ECP5 (SOS-08-A first target)

| Parameter | Value | Source |
|---|---|---|
| `STAGES`    | 2                              | `instantiate.sv` u_sync_1bit |
| `F_clk`     | 250 MHz (`T_clk = 4 ns`)       | SOS-08-A first-target deployment frequency budget |
| `F_data`    | 125 MHz (one transition per source-domain cycle, source-clk also at 250 MHz) | conservative upper bound |
| `T`         | 3.6 ns                         | `1 · T_clk - 0.4 ns` setup/clk-to-q overhead |
| **τ**       | **100 ps**                     | representative ECP5 value; vendor curve NOT cited (see caveats) |
| `T0`        | 1 ps                           | conservative 40-nm-class aperture |

Substituting:

```
T / τ                  = 3.6e-9 / 100e-12       = 36
e^(T/τ)                = e^36                   ≈ 4.31e15
F_clk · F_data · T0    = 250e6 · 125e6 · 1e-12  = 3.125e7
MTBF (STAGES = 2)      = 4.31e15 / 3.125e7      ≈ 1.38e8 s
                       ≈ 4.37 years
```

For the 3-stage chain (`u_sync_data` example):

```
T (3-stage)            = 2 · T_clk - 0.4 ns      = 7.6 ns
T / τ                  = 7.6e-9 / 100e-12        = 76
e^(T/τ)                = e^76                    ≈ 1.02e33
MTBF (STAGES = 3)      = 1.02e33 / 3.125e7       ≈ 3.27e25 s
                       ≈ 1.04e18 years
```

Going from 2 stages to 3 stages multiplies the per-stage exponent by 2
(approximately — the overhead term is the same regardless of stage count),
producing the classic "each added stage raises MTBF by orders of magnitude"
result that motivates the §6.9 multi-stage default of 2 + opt-in 3 for
high-reliability paths.

## Parameter sweep — STAGES ∈ {2, 3, 4}

| `STAGES` | T (ns)  | T/τ | e^(T/τ)   | MTBF (s) at 250 MHz / τ=100 ps | MTBF (yr)        |
|---|---|---|---|---|---|
| 2        | 3.6     | 36  | 4.31e15   | 1.38e8                          | **4.4 yr**       |
| 3        | 7.6     | 76  | 1.02e33   | 3.27e25                         | **1.0e18 yr**    |
| 4        | 11.6    | 116 | 2.40e50   | 7.68e42                         | **2.4e35 yr**    |

The "knee" between 2 and 3 stages is the source of the per-stage MTBF
exponential.  For the SOS-08-A first-target deployment (ECP5, 250 MHz):

- `STAGES = 2` is **adequate** for most internal CDC paths (4-year MTBF is
  below the age-of-universe but well above any reasonable reliability
  budget for a development board).
- `STAGES = 3` is the **recommended** choice for production deployments
  where the cumulative MTBF across many concurrent synchronizers matters.
- `STAGES = 4` is only justified at extreme F_clk × F_data products or
  where the FPGA's τ is very fast (sub-50 ps).

## Target frequency

The MTBF figures above are quoted at **F_clk = 250 MHz** (the SOS-08-A
first-target ECP5 system clock).  The MTBF scales with F_clk × F_data in
the denominator and with `e^(T)` in the numerator where `T` scales
inversely with F_clk — so doubling F_clk reduces MTBF by approximately
the ratio `e^(T_old/τ) / e^(T_new/τ) × (F_clk_new/F_clk_old)`.  For a
quick-look table:

| F_clk    | STAGES = 2 MTBF (yr) | STAGES = 3 MTBF (yr) |
|---|---|---|
| 100 MHz  | 1.4e12               | 1.0e29               |
| 250 MHz  | 4.4                  | 1.0e18               |
| 500 MHz  | 9.0e-9 (≈ 0.3 µs)    | 6.2e9                |

At 500 MHz the 2-stage chain MTBF collapses to sub-microsecond — STAGES = 3
or higher is mandatory there.  The build wrapper SHOULD warn on
`STAGES = 2 && F_clk >= 400 MHz`; that warning is a build-system task
(SOS-08-A's part of SOS-08 §6 build wrapper) not a primitive-level
elaboration check.

## Target-FF τ

**τ = 100 ps** is used in the worked example above as a representative
value for ECP5-class flip-flops (28 nm FD-SOI / 40 nm bulk-CMOS process
nodes typical of mid-2020s low-cost FPGAs).  Vendor-published τ curves
are not consistently available; published values vary from 30 ps (high-
end UltraScale+ at nominal Vdd) to 150 ps (lower-cost ECP5 / MAX 10 at
worst-case PVT).  The sign-off owner SHOULD cite a specific τ source
(vendor app-note, characterized silicon measurement, or third-party
metastability study) when this file moves from PENDING to SIGNED-OFF.

## Computed MTBF

Per the worked example above:

- **STAGES = 2 @ 250 MHz, τ = 100 ps**: MTBF ≈ **4.4 years**.
- **STAGES = 3 @ 250 MHz, τ = 100 ps**: MTBF ≈ **1.0 × 10^18 years**.

## Caveats

These figures are representative engineering estimates, not vendor-specific
guarantees.

1. **τ is process- and PVT-dependent.**  The 100 ps value used above is a
   reasonable mid-point but real silicon at a real corner can be 2–3x
   faster (better MTBF) or 2–3x slower (worse MTBF).  Production sign-off
   MUST cite a τ source.

2. **T0 is an estimate.**  Published T0 values for modern FPGAs are scarce.
   1 ps is a conservative round figure; the actual aperture is typically
   sub-picosecond on advanced processes (which makes MTBF *better* than
   the calculation above).

3. **Per-stage overhead matters at high F_clk.**  The `t_setup + t_clk_to_q`
   subtraction from each clock period is non-negligible above ~500 MHz.
   The 0.4 ns conservative value used above is fine at 250 MHz; recompute
   T for high-frequency deployments.

4. **F_data assumes maximum activity.**  Real source-domain signals often
   transition far less than every cycle.  Using `F_data = F_src_clk / 2`
   is the conservative upper bound; the calculation can be refined per
   primitive instance if the source-domain activity profile is known.

5. **The synthesis-tool synchronizer attributes** (`ASYNC_REG`,
   `altera_attribute SYNCHRONIZER_IDENTIFICATION FORCED`, `syn_preserve`)
   in `sos_synchronizer.{sv,vhd}` are NECESSARY for the calculated MTBF
   to apply.  Without them, the synthesis tool MAY retime / merge stages
   and silently destroy the metastability resolution window.  The build
   wrapper SHOULD lint for the presence of these attributes on every
   SOS-08-A synchronizer instance; that lint is a build-system task
   (PCDN-A-006 sign-off file existence + structural validation is the
   primitive-level gate).

## Sign-off

| Field | Value |
|---|---|
| Sign-off status | **PENDING** |
| Sign-off date   | _TBD — ISO-8601_ |
| Sign-off owner  | _TBD — initiative phase owner_ |
| τ source        | _TBD — vendor app-note / silicon-measured / third-party study citation_ |

When this file is signed off, replace the "PENDING" line with the resolution
status, fill in the date, owner, and τ source fields above, and add a §15
amendment entry to `docs/concepts/SOS-08-A-CONCEPTS.md` citing the
resolution.
