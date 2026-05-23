# sos_dpram_arb — MTBF sign-off

@spec docs/concepts/SOS-08-A-CONCEPTS.md §6.7 (sos_dpram_arb contract;
       MTBF treatment row)
      docs/concepts/SOS-08-A-CONCEPTS.md §12 (acceptance checklist gate (f);
       reduced conformance level for single-clock-only deployments)
      docs/concepts/SOS-08-A-CONCEPTS.md §15 (PCDN-A-006 — external MTBF
       sign-off; required fields enumerated below)
      docs/concepts/SOS-08-CONCEPTS.md   §7  (INV-S-HDL-3 — CDC isolation)
      docs/concepts/SOS-07-CONCEPTS.md   §6  (INV-SOS-A..H)

Cross-primitive invariants cited:
  INV-S-HDL-A-1..5 (per SOS-08-A §7).

## 1. Applicability

This MTBF sign-off applies to deployments instantiating `sos_dpram_arb` with
`MODE = "DUAL_CLOCK"`. Single-clock deployments (`MODE = "SINGLE_CLOCK"`)
are MTBF-N/A — no cross-domain sample crossing exists. Per the SOS-08-A
§12 acceptance checklist note, a conforming deployment without dual-clock
`sos_dpram_arb` satisfies the (a)-(e), (g)-(k) gates and a **reduced (f)**;
i.e. without MODE=DUAL_CLOCK this file is **informative only**.

## 2. Synchroniser shape

The DUAL_CLOCK branch of `sos_dpram_arb` composes a `STAGES = 2`-deep
flop chain that synchronises:

- `port_b_addr` (gray-coded, `ADDR_W = ceil(log2(DEPTH))` bits wide), from
  `clk_b` into `clk_a`.
- `port_b_we` (1-bit qualifier), from `clk_b` into `clk_a`.

Total cross-domain flop set: `ADDR_W + 1` synchroniser chains, each with
two flops on the `clk_a` side. The vendor-IP shim path applies the
target-specific synthesis attribute:

- Xilinx: `(* ASYNC_REG = "TRUE" *)`
- Intel:  `(* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED" *)`
- Lattice: `(* syn_preserve = 1 *)`

The portable-RTL path emits all three attributes (vendors ignore foreign
attributes), letting a downstream synth pick whichever applies.

## 3. MTBF formula

Per INV-S-HDL-3 the synchroniser flops are excluded from the formal model.
The verification claim is via the standard metastability MTBF formula
(Gabe Knight / Stephen Kleeman / canonical CDC-MTBF references):

```
            exp(t_resolution / τ)
MTBF =  ───────────────────────────
            f_clk × f_data × T₀
```

Where:

| Symbol | Meaning |
|---|---|
| `MTBF` | Mean time between failure (seconds) for a single synchroniser chain. |
| `t_resolution` | Time available for a metastable flip-flop to resolve. For a 2-stage chain this is `1/f_clk - t_setup - t_clk_to_q`, conservatively `0.5 × T_clk` for back-of-envelope estimates. |
| `τ` | Target-FF metastability characteristic time constant. ECP5 (Lattice 40 nm class): **τ ≈ 100 ps**. Xilinx 7-series / UltraScale+: **τ ≈ 30 – 50 ps**. Intel Cyclone V / Stratix 10: **τ ≈ 40 – 80 ps**. |
| `f_clk` | Destination clock frequency (Hz). Worked example below uses **250 MHz**. |
| `f_data` | Average rate of source-domain transitions (Hz). Conservative bound: equal to source-clock frequency — every cycle is a potential transition. |
| `T₀` | Metastability window (FF input-to-clock setup violation window). Typical: 10 – 100 ps. Worked example uses **30 ps**. |

The full MTBF for an N-bit gray-coded address sync is computed as a
product of independent single-bit MTBFs (each bit's metastable resolution
must succeed); the dominant term is the shortest of the individual
chains. Since all chains share the same flop characteristic and clock,
the aggregate MTBF for the `ADDR_W + 1`-bit synchroniser bus is:

```
MTBF_aggregate = MTBF_per_bit / (ADDR_W + 1)
```

(linear union bound — pessimistic; the true aggregate is the harmonic
mean of independent failure rates, which is bounded by the per-bit value
divided by N.)

## 4. Worked example — Lattice ECP5 target, 250 MHz, DEPTH=64

| Parameter | Value |
|---|---|
| Target FPGA | Lattice ECP5 (UM5G-85F class) |
| `f_clk` (clk_a domain) | 250 MHz → `T_clk = 4 ns` |
| `f_data` (clk_b domain) | 250 MHz (worst case — equal clock) |
| `τ` (per-FF) | 100 ps |
| `T₀` (per-FF) | 30 ps |
| `t_resolution` (2-stage chain) | 2 ns (one full `T_clk` minus setup/clk-to-q margin) |
| `ADDR_W` | `ceil(log2(64)) = 6` |
| Sync chains | 6 (addr) + 1 (we) = 7 |

Computation:

```
exp(t_resolution / τ) = exp(2e-9 / 100e-12) = exp(20) ≈ 4.85e8
f_clk × f_data × T₀  = 250e6 × 250e6 × 30e-12 ≈ 1.875e6

MTBF_per_bit ≈ 4.85e8 / 1.875e6 s ≈ 258 s
```

That single-bit MTBF is **insufficient** for production silicon — 258
seconds is roughly four minutes. For the aggregate (7-chain) sync bus the
union-bound aggregate is ~37 s; clearly inadequate.

This worked example reveals that **a 2-stage synchroniser on a 250 MHz
clock with ECP5-class τ is not enough** for safe DPRAM CDC. Standard
fixes (in increasing order of cost):

1. **STAGES = 3** → `exp(3 ns / 100 ps) = exp(30) ≈ 1.07e13`, MTBF_per_bit
   ≈ 5.7e6 s ≈ 66 days; aggregate ≈ 9 days. Still marginal for safety-
   critical.
2. **STAGES = 4** → `exp(4 ns / 100 ps) = exp(40) ≈ 2.35e17`, MTBF_per_bit
   ≈ 1.25e11 s ≈ 3,970 years; aggregate ≈ 567 years. Production-safe.
3. **Lower `f_clk` to 100 MHz** with `STAGES = 3` → `T_clk = 10 ns`,
   `t_resolution = 8 ns`, `exp(8 ns / 100 ps) = exp(80)` ≈ 5.5e34;
   astronomically safe.

**Recommendation for the first ECP5 deployment**: use **`STAGES = 3`** at
a target `f_clk` of **100 MHz** for the dual-clock DPRAM. For higher
clocks (≥ 200 MHz), elevate to **`STAGES = 4`**. The current portable
RTL hard-codes `STAGES = 2`; a future amendment to this primitive will
introduce a `SYNC_STAGES` generic (mirroring `sos_fifo_async`) for
configurability. Until then, the dual-clock variant of `sos_dpram_arb`
SHOULD be deployed only at clocks where the 2-stage chain achieves
MTBF ≥ 10¹⁰ s (≈ 317 years) per bit — practically `f_clk ≤ 50 MHz`
on ECP5-class τ.

## 5. Sign-off

| Field | Value |
|---|---|
| Formula | `MTBF = exp(t_resolution / τ) / (f_clk × f_data × T₀)` (§3) |
| Target frequency | TBD per deployment (worked example: 250 MHz; recommended ≤ 50 MHz at STAGES=2 on ECP5) |
| Target-FF τ | 100 ps (ECP5-class) |
| Computed MTBF (per bit) | TBD per deployment |
| Computed MTBF (aggregate) | TBD per deployment (union bound: per-bit / (ADDR_W + 1)) |
| Sign-off date | _placeholder — fill in at deployment time_ |
| Sign-off engineer | _placeholder_ |
| Deployment context | _placeholder — e.g. "disco-analyzer bench-CDC, clk_a=audio, clk_b=display, f_clk_a=49.152 MHz, DEPTH=32, STAGES=2"_ |

A deployment using `MODE = "DUAL_CLOCK"` is **non-conforming** under
SOS-08-A §12 (f) until this sign-off block is filled in with the actual
target-deployment numbers and signed by a responsible engineer. The
build wrapper (SOS-08-D) MUST refuse to elaborate a `MODE = "DUAL_CLOCK"`
instance whose enclosing project does not include this file with the
sign-off fields populated.

## 6. Change log

### 2026-05-23 — Initial draft (Ira / impl wave-1)

- Authored `MTBF.md` for `sos_dpram_arb`.
- §2 documents the gray-code address + we synchroniser shape.
- §3 records the canonical MTBF formula and the per-vendor τ / T₀ ranges.
- §4 worked example for Lattice ECP5 at 250 MHz / DEPTH=64 with explicit
  conclusion that STAGES=2 is insufficient; recommends STAGES=3 at ≤100 MHz
  or STAGES=4 above.
- §5 sign-off block left as placeholder — to be filled per deployment per
  PCDN-A-006 (external sign-off, build-wrapper structural validation).

Status: **draft — applies to MODE=DUAL_CLOCK deployments only**.
