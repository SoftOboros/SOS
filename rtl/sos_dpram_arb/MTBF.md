# sos_dpram_arb — MTBF sign-off

@spec docs/concepts/SOS-08-A-CONCEPTS.md §6.7 (sos_dpram_arb contract;
       MTBF treatment row)
      docs/concepts/SOS-08-A-CONCEPTS.md §12 (acceptance checklist gate (f);
       reduced conformance level for single-clock-only deployments)
      docs/concepts/SOS-08-A-CONCEPTS.md §15 (PCDN-A-006 — external MTBF
       sign-off; required fields enumerated below)
      PCDN-A-dpram-SYNC_STAGES resolved 2026-05-23 — adds the `SYNC_STAGES`
       generic to `sos_dpram_arb` (mandatory-with-default 2, CDC-primitive
       named exception to INV-S-HDL-A-5). §4 below sweeps SYNC_STAGES ∈
       {2, 3, 4} at 250 MHz / τ=100 ps and lifts the previous "future
       generic recommended" note to a normative MUST clause for
       deployments at f_clk ≥ 250 MHz on ECP5-class targets.
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

The DUAL_CLOCK branch of `sos_dpram_arb` composes a `SYNC_STAGES`-deep
flop chain (PCDN-A-dpram-SYNC_STAGES resolved 2026-05-23; default 2 per
the CDC-primitive named exception to INV-S-HDL-A-5) that synchronises:

- `port_b_addr` (gray-coded, `ADDR_W = ceil(log2(DEPTH))` bits wide), from
  `clk_b` into `clk_a`.
- `port_b_we` (1-bit qualifier), from `clk_b` into `clk_a`.

Total cross-domain flop set: `ADDR_W + 1` synchroniser chains, each with
`SYNC_STAGES` flops on the `clk_a` side. The portable RTL declares all
three vendor synthesis attributes simultaneously on the chain signals
(`async_reg`, `altera_attribute` SYNCHRONIZER_IDENTIFICATION FORCED, and
`syn_preserve`/`syn_keep`); each synthesis tool picks the attribute it
recognizes and silently ignores the others. The vendor-IP shim path may
additionally apply the target-specific synthesis attribute:

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
| `ADDR_W` | `ceil(log2(64)) = 6` |
| Sync chains | 6 (addr) + 1 (we) = 7 |

`t_resolution` scales with `SYNC_STAGES`: `(SYNC_STAGES - 1) × T_clk +
0.5 × T_clk = (SYNC_STAGES - 0.5) × T_clk`. With `T_clk = 4 ns` and the
conservative half-period margin on the final stage, the per-stage budget
is approximately `SYNC_STAGES × T_clk` ns minus a `0.5 × T_clk` setup
allowance. The aggregate denominator `f_clk × f_data × T₀ ≈ 1.875e6`
(Hz·s) is the same across the sweep.

### 4.1. SYNC_STAGES sweep at 250 MHz / τ=100 ps

| `SYNC_STAGES` | `t_resolution` | `exp(t_resolution / τ)` | `MTBF_per_bit` | `MTBF_aggregate` (÷7) | Verdict |
|---|---|---|---|---|---|
| **2** (default) | 2 ns | `exp(20)` ≈ 4.85e8 | ≈ 258 s | ≈ 37 s | **Inadequate** — 4 minutes per bit; aggregate ~37 s. NOT for production at this frequency. |
| **3** | 3 ns | `exp(30)` ≈ 1.07e13 | ≈ 5.7e6 s (≈ 66 days) | ≈ 8.1e5 s (≈ 9 days) | **Safety threshold met** at the per-bit level; aggregate ~9 days. Acceptable for non-life-critical safety-critical deployments. |
| **4** | 4 ns | `exp(40)` ≈ 2.35e17 | ≈ 1.25e11 s (≈ 3,970 years) | ≈ 1.79e10 s (≈ 567 years) | **Production-safe** for any deployment class. The recommended SYNC_STAGES for life-critical / aerospace / medical contexts. |

### 4.2. Alternative — lower clock with SYNC_STAGES=3

Reducing `f_clk` to 100 MHz with `SYNC_STAGES = 3` → `T_clk = 10 ns`,
`t_resolution = 8 ns`, `exp(8 ns / 100 ps) = exp(80)` ≈ 5.5e34. Per-bit
MTBF is astronomically large; aggregate is also astronomical. Use this
shape when the clock-rate budget allows it.

### 4.3. Normative deployment rules

- **MUST** — deployments with `MODE = "DUAL_CLOCK"` and `f_clk ≥ 250 MHz`
  set `SYNC_STAGES ≥ 3` (see §4.1; SYNC_STAGES=2 is inadequate at
  250 MHz on ECP5-class τ).
- **SHOULD** — deployments targeting life-critical / safety-critical
  contexts set `SYNC_STAGES = 4` regardless of clock rate.
- **MAY** — deployments at `f_clk ≤ 50 MHz` on ECP5-class τ accept the
  default `SYNC_STAGES = 2` (the per-bit MTBF at 50 MHz / SYNC_STAGES=2
  comfortably exceeds 10¹⁰ s).

Per PCDN-A-dpram-SYNC_STAGES resolved 2026-05-23, `SYNC_STAGES` is now a
DUT-surface generic (mandatory-with-default-2 per the CDC-primitive
named exception extended to INV-S-HDL-A-5 this wave); the previous
"future amendment will introduce a SYNC_STAGES generic" note has been
withdrawn. Examples/instantiate.{vhd,sv} document the
`u_dpram_safety_critical` shape (SYNC_STAGES=3) explicitly.

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

### 2026-05-23 — PCDN-A-dpram-SYNC_STAGES amendment (Ira / impl wave-2)

- §2 reworded to refer to the `SYNC_STAGES` generic rather than a hard-
  coded `STAGES = 2`; added the per-vendor synthesis-attribute note now
  that the portable RTL declares all three attribute families directly on
  the synchroniser chain signals.
- §4 worked example re-organised into a `SYNC_STAGES ∈ {2, 3, 4}` sweep
  table (§4.1) at 250 MHz / τ=100 ps / DEPTH=64, plus a lower-frequency
  alternative (§4.2) at 100 MHz / SYNC_STAGES=3.
- §4.3 normative deployment rules added: MUST `SYNC_STAGES ≥ 3` at
  `f_clk ≥ 250 MHz` on ECP5-class τ; SHOULD `SYNC_STAGES = 4` for
  life-critical contexts; MAY accept the default `SYNC_STAGES = 2` only
  when `f_clk ≤ 50 MHz` on ECP5-class τ.
- Withdrew the prior "future SYNC_STAGES generic recommended" note (the
  generic landed this wave per PCDN-A-dpram-SYNC_STAGES).

Status: **draft — applies to MODE=DUAL_CLOCK deployments only**.
