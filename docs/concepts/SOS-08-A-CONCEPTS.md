# SOS-08-A — L0 primitive library (per-primitive contracts)

**Status:** 🟡 **drafted 2026-05-23**. Awaiting PCDN walkthrough.

## 0. Authority policy

This phase doc is the **per-primitive contract** sub-phase under the SOS-08 umbrella (`SOS-08-CONCEPTS.md`, ratified 2026-05-23). The umbrella names ten L0 primitives in §6 and freezes the cross-sub-phase decisions (dialect targets, vendor-IP override pattern, handshake-port shape, MTBF treatment, cocotb+SVA paths, vector-IR canonical format). This doc takes those decisions as load-bearing input and produces one contract row per primitive.

Per the parent CLAUDE.md "Spec-Before-Code Planning Discipline / Phase document shape":

- **Normative** sections of this doc: §3 glossary, §4 source-of-truth map, §5 frozen decisions (per-primitive interface shape; one-hot internal FSM encoding), §6 per-primitive contracts, §7 cross-primitive invariants (INV-S-HDL-A-*), §8 standards integration matrix additions, §12 acceptance checklist.
- **Informative** sections: §1 purpose, §2 problem statement, §11 non-goals, §15 change log.
- All keywords MUST, MUST NOT, SHALL, SHOULD, SHOULD NOT, MAY are interpreted per RFC 2119 / RFC 8174 when capitalised.

This doc cites SOS-07 §6 for the cross-phase invariants `INV-SOS-A` through `INV-SOS-H`, and SOS-08 §7 for the cross-sub-phase invariants `INV-S-HDL-1` through `INV-S-HDL-5`. Neither set is re-derived.

The umbrella's eleventh primitive — `sos_fifo_sync` — was added to the L0 list at SOS-08 §6 (single-clock-domain message queue). This sub-phase documents all eleven.

## 1. Purpose

To freeze the per-primitive interface shape, behavioural contract, SVA properties, vendor-IP shim parameter, MTBF treatment (where applicable), and per-target instantiation example for each of the eleven L0 primitives the SOS-08 umbrella names. Without this freeze the SOS-08-B service composition cannot author against a stable port surface; the SOS-08-C chart→FSM emitter cannot generate L0 instantiations; the SOS-08-D cocotb + SVA emitter cannot bind properties against a stable port name set. SOS-08-A is the contract surface every later SOS-08 sub-phase consumes.

## 2. Problem statement

Per SOS-08 §2, every project re-derives the L0 set; the asymmetry between "RTOS has primitives" and "HDL re-derives primitives" is exactly what the kernel-shaped methodology is supposed to close. Three concrete pressures inside the umbrella's ten-primitive list motivate this per-primitive freeze:

1. **Composition pressure.** SOS-08-B services compose L0s; without a fixed port name set the service contracts cannot be written. Example: `sos_mailbox = sos_fifo_sync | sos_fifo_async + handshake` — "handshake" has to mean the same port names whichever FIFO variant is selected. INV-S-HDL-1 (handshake-compatible ports) is the umbrella-level statement; this doc is the per-primitive enumeration.

2. **Synchronizer-isolation pressure.** INV-S-HDL-3 excludes `sos_synchronizer` from the formal model. Every other primitive's verification claim depends on knowing exactly which signal crossings need an `sos_synchronizer` and which do not; the per-primitive contracts make that pattern explicit at the contract surface, not at the implementation choice.

3. **Vendor-IP shim consistency pressure.** SOS-08 §5.3 freezes "portable RTL default; vendor shim via `-Dvendor=*` build flag". For each primitive we must state which vendors have shims and which are portable-only — and the wrapper interface MUST be byte-identical across all vendor paths so chart-emitted code does not know which path it gets.

## 3. Canonical glossary

Terms normative within SOS-08-A+. Authority relationships per §8.

| Term | Definition |
|---|---|
| **L0 primitive** | One of the eleven modules enumerated in §6. As defined in SOS-08 §3 ("Layer 0 (L0) primitives"); used without modification. The eleven members are `sos_fifo_async`, `sos_fifo_sync`, `sos_arbiter_rr`, `sos_arbiter_priority`, `sos_mutex`, `sos_credit_counter`, `sos_dpram_arb`, `sos_tick_gen`, `sos_synchronizer`, `sos_strobe_latch`, `sos_rate_divider`. |
| **portable RTL** | The default implementation path; synthesizable VHDL-2008 + SystemVerilog-2017 using only generic constructs (no vendor primitives, no IP-block instantiations). As defined in SOS-08 §5.3; used without modification. |
| **vendor-IP shim** | A parameterized wrapper around a vendor's optimised IP, with byte-identical interface to the portable-RTL path. Selected at build time via `-Dvendor=<xilinx|intel|lattice|portable>`. As defined in SOS-08 §5.3; used without modification. |
| **handshake-port shape** | The ready/valid pair on data-bearing channels and req/ack pair on control channels, ratified by SOS-08 PCDN-001 and INV-S-HDL-1. Both forms expose the canonical "producer asserts valid, consumer asserts ready, transfer occurs the cycle both are high" semantics (ready/valid) or "requester pulses req, responder pulses ack" (req/ack). |
| **SVA bind file** | A SystemVerilog `bind` directive that attaches an assertion module to a primitive instance without modifying the primitive's source. As defined in SOS-08 §6 (SOS-08-D row); per-primitive SVA bind files are owned by this doc's source-of-truth map (§4). |
| **MTBF treatment** | The synchronizer-MTBF calculation that takes the place of formal verification for the metastability path. Required for any primitive crossing clock domains. Excluded from formal scope per INV-S-HDL-3. The calculation is per-primitive (depends on synchronizer depth, target clock frequency, target FF metastability characteristic) and SHALL be recorded in the primitive's docstring. |
| **per-target instantiation example** | A 1-3-line VHDL or SystemVerilog snippet showing how a chart-emitted top-level instantiates the primitive with parameterized ports. Lives in the per-primitive `examples/` directory (see §4). |
| **internal FSM** | Any state-machine internal to the primitive (e.g. `sos_arbiter_priority`'s aging-cycle state). Distinct from chart-emitted FSMs (SOS-08-C's L2 territory). Encoded one-hot by default per §5.2. |

## 4. Source-of-truth map

For every concept this sub-phase touches, **exactly one** location is the canonical authority.

| Concept | Authority |
|---|---|
| L0 set membership | `SOS-08-CONCEPTS.md` §6 (umbrella, **mirror** here) |
| Per-primitive interface shape | **this doc** (§6) |
| Per-primitive SVA properties | **this doc** (§6); RTL bind files live at `rtl/<primitive>/<primitive>_sva.sv` |
| Per-primitive portable VHDL source | `rtl/<primitive>/<primitive>.vhd` |
| Per-primitive portable SV source | `rtl/<primitive>/<primitive>.sv` |
| Per-primitive vendor-IP shim sources | `rtl/<primitive>/vendor_<vendor>.sv` (one file per supported vendor) |
| Per-primitive cocotb testbench | `tb/<primitive>/test_<primitive>.py` |
| Per-primitive SVA bind file | `rtl/<primitive>/<primitive>_sva.sv` (assertion module) + `tb/<primitive>/<primitive>_bind.sv` (bind directive) |
| Per-primitive MTBF justification | `rtl/<primitive>/MTBF.md` (only for CDC-crossing primitives; see §6.1 + §6.9) |
| Per-primitive instantiation example | `examples/<primitive>/instantiate.{vhd,sv}` |
| Parameter naming convention | **this doc** (§5.1, **pending PCDN-A-001**) |
| Port-prefix convention | **this doc** (§5.1, **pending PCDN-A-002**) |
| Reset polarity | **this doc** (§5.1, **pending PCDN-A-003**) |
| Default depth/width per primitive | **this doc** (§5.1, **pending PCDN-A-004**) |
| Internal FSM encoding | **this doc** (§5.2, default mirrors SOS-08 PCDN-002 one-hot) |
| MTBF assertion mechanism | **this doc** (§5.3, **pending PCDN-A-006**) |
| Cocotb test-bench shape (one file per primitive vs shared harness) | **this doc** (§5.4, **pending PCDN-A-007**) |
| Cross-phase invariants INV-SOS-A through H | `SOS-07-CONCEPTS.md` §6 (cited, not redefined) |
| Cross-sub-phase invariants INV-S-HDL-1 through 5 | `SOS-08-CONCEPTS.md` §7 (cited, not redefined) |
| Per-primitive cross-primitive invariants INV-S-HDL-A-* | **this doc** (§7) |

## 5. Frozen decisions

### 5.1 Interface shape conventions

Per SOS-08 PCDN-001 (ratified): **ready/valid** for data-bearing channels; **req/ack** for control-only handshakes. This sub-phase concretizes that ratification with the following conventions, marked pending where PCDN walkthrough is needed:

| Aspect | Convention | Status |
|---|---|---|
| Handshake direction (data) | producer drives `valid`; consumer drives `ready`; transfer on `valid && ready` | frozen (mirrors AXI-Stream) |
| Handshake direction (control) | requester drives `req` (1-cycle pulse); responder drives `ack` (1-cycle pulse) | frozen |
| Parameter naming convention | `UPPER_CASE` (VHDL convention; SV generics follow suit for cross-language consistency) | **PCDN-SOS-08-A-001** |
| Port-name prefix convention | bare `data_*` / `ready` / `valid` / `req` / `ack` on portable-RTL faces; AXI-Stream-compatible `m_axis_*` / `s_axis_*` aliases optional on data-bearing primitives | **PCDN-SOS-08-A-002** |
| Reset polarity | synchronous active-high (`rst`); release synchronous-to-clock | **PCDN-SOS-08-A-003** |
| Per-primitive default depth/width | depth/width are **mandatory** parameters with no defaults; build-time parameter omission MUST emit a synth error | **PCDN-SOS-08-A-004** |

Frozen-enumeration registration policy for the interface-shape set: **Standards Action** (modifying the convention requires a §15 amendment here; touches the cross-sub-phase composition surface per INV-S-HDL-1).

### 5.2 Internal FSM encoding

Per SOS-08 PCDN-002 (ratified one-hot at v1 for chart-emitted FSMs): internal FSMs inside L0 primitives — e.g. `sos_arbiter_priority`'s aging-cycle state, `sos_mutex`'s lock/unlock state — SHALL also default to one-hot encoding. Per-primitive override via a `STATE_ENCODING` parameter is **PCDN-SOS-08-A-005**.

Frozen-enumeration registration policy: **Standards Action**.

### 5.3 MTBF assertion mechanism

For primitives crossing clock domains (`sos_fifo_async`, `sos_synchronizer`), per INV-S-HDL-3 the synchronizer flops are excluded from the formal model and verified separately via MTBF calculation. The mechanism for recording the MTBF claim — `assert property` with cover targeting a synthesis-tool-specific path constraint, or external sign-off in the build manifest — is **PCDN-SOS-08-A-006**.

Frozen-enumeration registration policy: **Standards Action**.

### 5.4 Cocotb testbench shape

Per SOS-08 PCDN-004 (ratified cocotb-classic at v1): per-primitive cocotb tests are mandatory. Whether each primitive gets one Python file with its own harness, or a shared harness with per-primitive test functions, is **PCDN-SOS-08-A-007**.

Frozen-enumeration registration policy: **Specification Required** (one-file-vs-shared is a phase-local mechanic; flipping it later is cheap).

## 6. Per-primitive contracts

Each subsection follows the same shape: interface signature → behavioural contract → SVA properties → vendor-IP shim parameter → MTBF treatment (if applicable) → per-target instantiation example.

Port lists use placeholder names per the conventions pending in PCDN-A-002; final names freeze at PCDN resolution. The contract surface (which ports exist, what they do, which assertions ride them) is normative now; the spelling is normative at ratification.

### 6.1 `sos_fifo_async` — cross-clock-domain message queue

**Interface signature.**

Parameters: `DEPTH` (power of 2, ≥ 4), `WIDTH` (≥ 1), `SYNC_STAGES` (≥ 2, default 2).

Ports (write side, `wclk` domain): `wclk`, `wrst`, `wdata[WIDTH-1:0]` (in), `wvalid` (in), `wready` (out), `wfull` (out, status).
Ports (read side, `rclk` domain): `rclk`, `rrst`, `rdata[WIDTH-1:0]` (out), `rvalid` (out), `rready` (in), `rempty` (out, status).

**Behavioural contract.** Gray-coded read + write pointers cross between `wclk` and `rclk` domains via `SYNC_STAGES`-deep flop synchronizers. Write transfer occurs when `wvalid && wready`; read transfer when `rvalid && rready`. `wfull` and `rempty` are status outputs derived from the local-domain view of the synchronized pointer; both are conservative (`wfull` may stay asserted one extra `wclk` after a far-side read; `rempty` may stay asserted one extra `rclk` after a near-side write).

**SVA properties** (bind file `sos_fifo_async_sva.sv`):

- `no_overflow`: `assert property (@(posedge wclk) disable iff (wrst) wvalid && !wready |-> !$past(wfull, 1) || $stable(wdata))` — no write attempted past full without a stall.
- `no_underflow`: `assert property (@(posedge rclk) disable iff (rrst) rvalid && !rready |-> !$past(rempty, 1))` — no read attempted past empty.
- `ordering_preserved`: cocotb-checked at the testbench level (SVA cannot easily express FIFO ordering across CDC); each in-flight token is tagged at write and the read side asserts monotonic tag delivery.
- `pointer_monotonicity`: `assert property (@(posedge wclk) $rose(wvalid && wready) |-> wptr_next == (wptr + 1))` and dual for read side.

**Vendor-IP shim parameter.** `-Dvendor=xilinx` → `xpm_fifo_async`; `-Dvendor=intel` → `dcfifo`; `-Dvendor=lattice` → `generic_fifo_dc`; `-Dvendor=portable` → bundled portable RTL. All four shim the same wrapper interface.

**MTBF treatment.** Per INV-S-HDL-3: the `SYNC_STAGES`-deep flop chain on each pointer is excluded from the formal model; MTBF recorded at `rtl/sos_fifo_async/MTBF.md` with the formula `MTBF = exp(t_resolution / τ) / (f_clk × f_data × T₀)` parameterized by target clock frequency and target-FF metastability characteristic. The chart compiler's bound analysis treats the synchronizer's near-side output as an oracle per INV-S-HDL-3 — downstream code consumes only the synchronized signal.

**Instantiation example** (chart-emitted SV top-level):
```systemverilog
sos_fifo_async #(.DEPTH(16), .WIDTH(32), .SYNC_STAGES(2)) u_evt_fifo (
    .wclk(clk_a), .wrst(rst_a), .wdata(evt_a), .wvalid(evt_a_valid), .wready(evt_a_ready), .wfull(),
    .rclk(clk_b), .rrst(rst_b), .rdata(evt_b), .rvalid(evt_b_valid), .rready(evt_b_ready), .rempty()
);
```

### 6.2 `sos_fifo_sync` — single-clock-domain message queue

**Interface signature.**

Parameters: `DEPTH` (≥ 2), `WIDTH` (≥ 1).

Ports: `clk`, `rst`, `wdata[WIDTH-1:0]` (in), `wvalid` (in), `wready` (out), `rdata[WIDTH-1:0]` (out), `rvalid` (out), `rready` (in), `full` (out), `empty` (out).

**Behavioural contract.** Single-domain FIFO with the same handshake-port shape as `sos_fifo_async` minus the `w*`/`r*` domain split. `full` and `empty` are exact (no synchronizer skew). Implementation MAY be register-file (small `DEPTH`) or BRAM-backed (`DEPTH ≥ 32`); the choice is a portable-RTL implementation detail, not a contract decision.

**SVA properties** (bind file `sos_fifo_sync_sva.sv`):

- `no_overflow`: `assert property (@(posedge clk) disable iff (rst) wvalid && full |-> !wready)`.
- `no_underflow`: `assert property (@(posedge clk) disable iff (rst) rready && empty |-> !rvalid)`.
- `count_invariant`: `assert property (@(posedge clk) count <= DEPTH)`.

**Vendor-IP shim parameter.** `-Dvendor=xilinx` → `xpm_fifo_sync`; `-Dvendor=intel` → `scfifo`; `-Dvendor=lattice` → `generic_fifo_sync`; `-Dvendor=portable` → bundled.

**MTBF treatment.** N/A (single domain).

### 6.3 `sos_arbiter_rr` — round-robin arbiter

**Interface signature.**

Parameters: `N_REQUESTERS` (≥ 2), `N_GRANTS` (≥ 1, ≤ `N_REQUESTERS`).

Ports: `clk`, `rst`, `req[N_REQUESTERS-1:0]` (in), `grant[N_REQUESTERS-1:0]` (out, one-hot per slot), `grant_valid[N_GRANTS-1:0]` (out).

**Behavioural contract.** A rotating pointer advances each clock cycle that any `req[i]` is asserted; the next `N_GRANTS` asserted requesters starting from the pointer are granted. Fairness bound: every requester continuously asserted is granted within `N_REQUESTERS` cycles (the round-robin period).

**SVA properties** (bind file `sos_arbiter_rr_sva.sv`):

- `eventually_granted`: `assert property (@(posedge clk) disable iff (rst) req[i] |-> ##[1:N_REQUESTERS] grant[i])` — bounded liveness per requester, for each `i ∈ [0, N_REQUESTERS)`.
- `no_concurrent_double_grant`: `assert property (@(posedge clk) $countones(grant) <= N_GRANTS)`.
- `grant_implies_req`: `assert property (@(posedge clk) grant[i] |-> req[i])` — no spurious grants.

**Vendor-IP shim parameter.** Portable-RTL-only (arbiters are typically not vendor-IP-shimmed; the portable form synthesizes well across all backends).

**MTBF treatment.** N/A (single domain).

### 6.4 `sos_arbiter_priority` — priority arbiter with optional aging

**Interface signature.**

Parameters: `N_REQUESTERS` (≥ 2), `AGING_BITS` (≥ 0; `0` disables aging), `AGING_THRESHOLD` (≥ 1; only used when `AGING_BITS > 0`).

Ports: `clk`, `rst`, `req[N_REQUESTERS-1:0]` (in), `priority[N_REQUESTERS*PRIO_W-1:0]` (in, per-slot priority; `PRIO_W = $clog2(N_REQUESTERS)`), `grant[N_REQUESTERS-1:0]` (out, one-hot).

**Behavioural contract.** Highest-priority asserted requester wins each cycle. When `AGING_BITS > 0`, each unserved requester's effective priority increments by one per cycle (saturating at `AGING_BITS`-wide max); once a requester's age reaches `AGING_THRESHOLD`, it is treated as max-priority. Internal FSM is the aging-cycle counter, one-hot encoded per §5.2.

**SVA properties** (bind file `sos_arbiter_priority_sva.sv`):

- `highest_prio_wins`: `assert property (@(posedge clk) disable iff (rst || AGING_BITS > 0) req[i] && (priority[i] == max(req & priority)) |-> grant[i])` — when aging disabled, top priority always wins.
- `bounded_starvation`: `assert property (@(posedge clk) disable iff (rst || AGING_BITS == 0) req[i] |-> ##[1:AGING_THRESHOLD * N_REQUESTERS] grant[i])` — when aging enabled, every requester granted within an aging-bounded window.
- `no_concurrent_double_grant`: `assert property (@(posedge clk) $countones(grant) <= 1)`.

**Vendor-IP shim parameter.** Portable-RTL-only.

**MTBF treatment.** N/A.

### 6.5 `sos_mutex` — 1-bit lock register + arbiter

**Interface signature.**

Parameters: `N_REQUESTERS` (≥ 2), `ARBITER_MODE` (enum: `RR` | `PRIO`).

Ports: `clk`, `rst`, `acquire_req[N_REQUESTERS-1:0]` (in), `acquire_ack[N_REQUESTERS-1:0]` (out), `release_req[N_REQUESTERS-1:0]` (in), `release_ack[N_REQUESTERS-1:0]` (out), `holder_id[$clog2(N_REQUESTERS+1)-1:0]` (out; `N_REQUESTERS` means "unheld").

**Behavioural contract.** Built atop `sos_arbiter_rr` or `sos_arbiter_priority` per `ARBITER_MODE`. Acquire is granted only when the lock is free; release is granted only to the current holder. Lock register is 1 bit + `$clog2(N_REQUESTERS)` bits of holder identity.

**SVA properties** (bind file `sos_mutex_sva.sv`):

- `mutual_exclusion`: `assert property (@(posedge clk) $countones(acquire_ack) <= 1 && (holder_id != N_REQUESTERS) -> acquire_ack == 0)` — at most one holder.
- `no_deadlock_under_chart_bound`: `assert property (@(posedge clk) disable iff (rst) acquire_req[i] |-> ##[1:CHART_BOUND] (acquire_ack[i] || !acquire_req[i]))` — chart-derived `CHART_BOUND` parameter discharges this; verified by chart bound-analysis per INV-SOS-G.
- `release_only_by_holder`: `assert property (@(posedge clk) release_ack[i] |-> holder_id == i)`.

**Vendor-IP shim parameter.** Portable-RTL-only.

**MTBF treatment.** N/A (single domain; CDC use composes a `sos_synchronizer` outside `sos_mutex`'s boundary).

### 6.6 `sos_credit_counter` — distributed semaphore

**Interface signature.**

Parameters: `MAX_CREDITS` (≥ 1), `WIDTH` (= `$clog2(MAX_CREDITS+1)`).

Ports: `clk`, `rst`, `consume_req` (in), `consume_ack` (out), `replenish_req` (in), `replenish_ack` (out), `count[WIDTH-1:0]` (out, status), `empty` (out), `full` (out).

**Behavioural contract.** Counter increments on `replenish_req && replenish_ack` and decrements on `consume_req && consume_ack`. Consume is acked only when `count > 0`; replenish only when `count < MAX_CREDITS`. Consume + replenish at the same cycle are sequenced (replenish first, then consume) so the cycle is net-neutral when the counter would otherwise overflow.

**SVA properties** (bind file `sos_credit_counter_sva.sv`):

- `count_nonneg`: `assert property (@(posedge clk) count >= 0)`.
- `count_bounded`: `assert property (@(posedge clk) count <= MAX_CREDITS)`.
- `consume_drains`: `assert property (@(posedge clk) consume_req && consume_ack |-> ##1 count == ($past(count) - 1 + (replenish_ack ? 1 : 0)))`.

**Vendor-IP shim parameter.** Portable-RTL-only.

**MTBF treatment.** N/A.

### 6.7 `sos_dpram_arb` — dual-port RAM + arbiter

**Interface signature.**

Parameters: `DEPTH` (power of 2, ≥ 4), `WIDTH` (≥ 1), `ARB_MODE` (enum: `RR` | `PRIO`).

Ports (port A): `clk_a`, `rst_a`, `addr_a[$clog2(DEPTH)-1:0]` (in), `wdata_a[WIDTH-1:0]` (in), `we_a` (in), `rdata_a[WIDTH-1:0]` (out), `req_a` (in), `ack_a` (out).
Ports (port B): same, swapped suffix.

**Behavioural contract.** Two-port BRAM (per vendor) or LUT-RAM (for small `DEPTH`); read-during-write hazards on the same address are arbitrated via the embedded `sos_arbiter_rr` / `sos_arbiter_priority`. The losing port's access stalls one cycle; the winning port observes the write. Single-clock variant of this primitive uses one `clk`; dual-clock variant uses `clk_a` and `clk_b` (which composes a `sos_synchronizer` internally on the arbiter's request signals — making this primitive a CDC-crossing one in dual-clock mode).

**SVA properties** (bind file `sos_dpram_arb_sva.sv`):

- `no_same_addr_rw_hazard`: `assert property (@(posedge clk_a) we_a && req_b && (addr_a == addr_b) |-> ack_a ^ ack_b)` — exactly one port served when both target the same address.
- `arbitration_fairness`: inherited from underlying arbiter (`sos_arbiter_rr` `eventually_granted` or `sos_arbiter_priority` `bounded_starvation`).

**Vendor-IP shim parameter.** `-Dvendor=xilinx` → `xpm_memory_tdpram`; `-Dvendor=intel` → `altdpram`; `-Dvendor=lattice` → `EBR_DP`; `-Dvendor=portable` → register-file portable RTL (only viable for small `DEPTH`).

**MTBF treatment.** Dual-clock mode only: composes a `sos_synchronizer` on cross-port handshake signals; MTBF inherits per INV-S-HDL-3 from the embedded synchronizer's MTBF document.

### 6.8 `sos_tick_gen` — periodic rate generator

**Interface signature.**

Parameters: `PERIOD_CYCLES` (≥ 2; in `clk` cycles).

Ports: `clk`, `rst`, `enable` (in), `tick` (out, 1-cycle pulse every `PERIOD_CYCLES`), `tick_count[31:0]` (out, monotonic counter).

**Behavioural contract.** A free-running counter that emits a 1-cycle `tick` pulse every `PERIOD_CYCLES`. When `enable` deasserts, the counter pauses (counter value retained, no ticks emitted); reasserting `enable` resumes from the paused count. One per system per SOS-08 §6 — multiple instances are an antipattern (they may drift; downstream rate dividers off a single source are the correct shape).

**SVA properties** (bind file `sos_tick_gen_sva.sv`):

- `period_stable`: `assert property (@(posedge clk) disable iff (rst || !enable) $rose(tick) |-> ##PERIOD_CYCLES $rose(tick))` — period is exactly `PERIOD_CYCLES` (no glitches).
- `tick_is_pulse`: `assert property (@(posedge clk) tick |-> ##1 !tick)` — tick is always 1-cycle wide.

**Vendor-IP shim parameter.** Portable-RTL-only.

**MTBF treatment.** N/A.

### 6.9 `sos_synchronizer` — N-FF synchronizer

**Interface signature.**

Parameters: `STAGES` (≥ 2, default 2), `WIDTH` (≥ 1).

Ports: `clk_dst`, `rst_dst`, `d_src[WIDTH-1:0]` (in, from source domain — must be Gray-coded or 1-bit), `d_dst[WIDTH-1:0]` (out, in destination domain).

**Behavioural contract.** `STAGES` flip-flops in series on `clk_dst`, no combinational logic between them. The source-domain signal is sampled into the first flop; the destination domain consumes only the output of the last flop. Synthesis attributes (`ASYNC_REG = TRUE` on Xilinx; `altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED"` on Intel; `syn_preserve = 1` on Lattice) are emitted by the vendor-IP shim path. Multi-bit `WIDTH > 1` is allowed only when the caller guarantees Gray coding upstream; this is documented in the docstring but NOT enforced in the contract (caller's responsibility).

**SVA properties.** Per INV-S-HDL-3, `sos_synchronizer` is **excluded from the formal model**. No SVA properties are emitted for the synchronizer flops themselves. The verification claim is via the MTBF calculation, not assertion.

A single "boundary" assertion IS emitted to enforce that downstream code consumes only `d_dst`, not `d_src`:

- `dst_only_consumed`: a lint-level check (NOT an SVA `assert property`) that no other module in the synthesized design references `d_src` from the destination domain. Enforced by the build wrapper (SOS-08-A's part of the build wrapper SOS-08 §6 names).

**Vendor-IP shim parameter.** `-Dvendor=xilinx` → `xpm_cdc_single` / `xpm_cdc_gray`; `-Dvendor=intel` → `altera_std_synchronizer`; `-Dvendor=lattice` → portable RTL with `syn_preserve`; `-Dvendor=portable` → bundled `STAGES`-deep flop chain with synthesis attributes.

**MTBF treatment.** Mandatory per INV-S-HDL-3. The MTBF document at `rtl/sos_synchronizer/MTBF.md` records the formula, the parameter sweep over `STAGES` (typical values 2, 3, 4 with the expected MTBF jump per added stage), and the target-clock-frequency annotation the build wrapper consumes.

### 6.10 `sos_strobe_latch` — pulse-to-level + ack

**Interface signature.**

Parameters: (none — single-bit primitive).

Ports: `clk`, `rst`, `strobe` (in, 1-cycle pulse), `ack` (in, 1-cycle pulse), `level` (out, latched signal).

**Behavioural contract.** `level` goes high on `strobe && !level` and stays high until `ack` is observed. Concurrent `strobe + ack` cycles clear `level` (ack wins); concurrent re-strobe before `ack` is observed is absorbed (no double-latching). Event-flag primitive — `sos_event_group` (SOS-08-B) composes N of these.

**SVA properties** (bind file `sos_strobe_latch_sva.sv`):

- `every_strobe_latched`: `assert property (@(posedge clk) disable iff (rst) strobe |-> ##1 level)`.
- `every_ack_clears`: `assert property (@(posedge clk) disable iff (rst) ack && level |-> ##1 !level)`.
- `no_double_latch`: `assert property (@(posedge clk) disable iff (rst) strobe && level |-> ##1 level)` — re-strobing while latched is a no-op, not a counter increment.

**Vendor-IP shim parameter.** Portable-RTL-only.

**MTBF treatment.** N/A (single domain). Cross-domain strobe latching composes `sos_synchronizer` upstream.

### 6.11 `sos_rate_divider` — programmable rate divider

**Interface signature.**

Parameters: `MAX_RATIO` (≥ 2).

Ports: `clk`, `rst`, `tick_in` (in, 1-cycle pulse), `ratio[$clog2(MAX_RATIO+1)-1:0]` (in, divider value; `0` disables output), `tick_out` (out, 1-cycle pulse every `ratio` of `tick_in`).

**Behavioural contract.** A counter increments on each `tick_in`; when it reaches `ratio`, `tick_out` pulses for one cycle and the counter resets. `ratio` MAY change at runtime (the divider observes the new value on the next cycle); the in-flight count is preserved across the change. `ratio == 0` disables `tick_out` entirely (no pulses).

**SVA properties** (bind file `sos_rate_divider_sva.sv`):

- `ratio_stable`: `assert property (@(posedge clk) disable iff (rst || $changed(ratio)) $rose(tick_out) |-> ##ratio $rose(tick_out))` — under stable `ratio`, output period equals input period × `ratio`.
- `tick_out_is_pulse`: `assert property (@(posedge clk) tick_out |-> ##1 !tick_out)`.
- `zero_disables`: `assert property (@(posedge clk) ratio == 0 |-> !tick_out)`.

**Vendor-IP shim parameter.** Portable-RTL-only.

**MTBF treatment.** N/A.

## 7. Cross-primitive invariants

In addition to the cross-phase invariants INV-SOS-A through H and the cross-sub-phase invariants INV-S-HDL-1 through 5 (cited but not redefined), the following invariants are normative across the SOS-08-A L0 library:

- **INV-S-HDL-A-1 — Reset semantics are uniform.** Every L0 primitive's reset (`rst`, `wrst`, `rrst`, `rst_a`, `rst_b`, `rst_dst`) is **synchronous active-high** with synchronous release (subject to PCDN-A-003 ratification). Asynchronous resets are prohibited in L0; CDC-crossing reset distribution is the caller's responsibility (typically a `sos_synchronizer` on the deassert edge).

- **INV-S-HDL-A-2 — Handshake-port composition is associative.** Two L0 primitives connected via the ready/valid pair compose into a third object whose external behaviour is still a ready/valid handshake. This is the load-bearing property SOS-08-B's service composition depends on. Concretizes INV-S-HDL-1 (handshake-compatible ports) at the per-primitive level: no L0 primitive MAY add side-channel ports (out-of-band valid bypass, peek-without-consume) that break associativity.

- **INV-S-HDL-A-3 — Vendor-IP shim wrapper is byte-identical.** For each primitive supporting vendor-IP shims, the portable-RTL path and every vendor shim path MUST expose the same port list, the same parameter names, and the same default values. Build-time selection (`-Dvendor=*`) changes only the implementation underneath; chart-emitted instantiations are unchanged. Required for SOS-08-C's emitter to produce vendor-agnostic instantiation code.

- **INV-S-HDL-A-4 — One-hot internal FSM by default.** Internal FSMs inside L0 primitives default to one-hot encoding (mirrors SOS-08 PCDN-002 for chart-emitted FSMs); per-primitive override via `STATE_ENCODING` parameter (pending PCDN-A-005). The default ensures synthesis-tool optimisations stay consistent between L0 and chart-emitted FSMs.

- **INV-S-HDL-A-5 — Mandatory parameters have no defaults.** Per §5.1 (subject to PCDN-A-004), depth/width/count parameters that determine resource cost have no defaults; omitting them at instantiation MUST emit a synth error. Defaults on resource-determining parameters silently invite the wrong area/timing trade-off; explicit instantiation is the contract.

## 8. Standards integration matrix additions

This sub-phase does not introduce new external standards; it consumes the rows already declared in SOS-07 §7 and SOS-08 §8. No additions.

(For completeness: the vendor-IP families AMD/Xilinx UNIMACRO, Intel/Altera megafunctions, and Lattice generic primitives are already declared in SOS-08 §8 with relationship `compose`. The `xpm_*`, `altera_*`, and Lattice primitives used in this sub-phase's vendor-IP shims are instances of those rows.)

## 9. Non-goals

This sub-phase does NOT:

- Author the L1 service compositions (`sos_mailbox`, `sos_event_group`, `sos_resource_pool`, `sos_periodic_task`, `sos_message_channel`) — that's SOS-08-B.
- Author the chart → FSM emission contract — that's SOS-08-C.
- Author the cocotb / SVA emission machinery — that's SOS-08-D (the cocotb tests and SVA bind files this doc names are the *artifacts*; the *emitter* that produces them is SOS-08-D).
- Author the SystemVerilog testbench, UVM sequence, or waveform-annotation paths — those are SOS-08-E, F, G respectively.
- Bench-validate any primitive against the Lattice ECP5 dev board — that's the SOS-08 §12 (e) gate, satisfied at SOS-08-A implementation rather than ratification.
- Add a twelfth L0 primitive. The umbrella's set of eleven (§3) is frozen; new primitives require a §15 amendment to SOS-08-CONCEPTS.md (umbrella registration policy: Standards Action).

## 10. Reconciliation decisions vs adjacent repo primitives

### vs. SOS-08 umbrella §6 (sub-phase scope sketch)

The umbrella names ten primitives in §6 + `sos_fifo_sync` introduced inline (eleven total in the table). This doc enumerates all eleven. The umbrella's per-primitive purpose blurbs (§6 SOS-08-A table) and this doc's per-primitive interface signatures are mutually consistent; this doc adds depth that the umbrella table did not carry.

### vs. SOS-08 PCDN-001 resolution (handshake mix)

The umbrella's PCDN-001 resolution names the mix (ready/valid for data; req/ack for control). This doc applies that resolution per primitive: data-bearing FIFOs (`sos_fifo_async`, `sos_fifo_sync`, `sos_dpram_arb`) use ready/valid; control-bearing arbiters (`sos_arbiter_rr`, `sos_arbiter_priority`, `sos_mutex`, `sos_credit_counter`) use req/ack; pulse-bearing primitives (`sos_strobe_latch`, `sos_tick_gen`, `sos_rate_divider`) use raw pulses (which are a degenerate req with implicit immediate ack — the consumer either samples or doesn't).

### vs. SOS-08 PCDN-002 resolution (one-hot at v1)

The umbrella's PCDN-002 ratifies one-hot encoding for chart-emitted FSMs. This doc extends that default to L0-primitive-internal FSMs (§5.2, INV-S-HDL-A-4) — a friendly extension, not a re-ratification.

### vs. SOS-08-B (forthcoming) service composition

`sos_mailbox` will compose `sos_fifo_sync` or `sos_fifo_async`; `sos_event_group` will compose N × `sos_strobe_latch` + `sos_arbiter_rr`; `sos_resource_pool` will compose a free-list-FIFO discipline over a static pool. The composition contracts in SOS-08-B depend on the per-primitive contracts ratified here. Authoring SOS-08-B before SOS-08-A would mean composing against an unfrozen surface; this sub-phase is the prerequisite.

## 11. Pending Concept Decision Notices (PCDNs)

These open questions move this doc from 🟡 drafted to 🟢 ratified. The PCDN-A-* identifiers are stable per parent CLAUDE.md "Errata Open Question" naming (these are PCDNs at the concepts-doc level, not ERRATA EOQs; the analogous shape applies).

- **PCDN-SOS-08-A-001 — Parameter naming convention.** `UPPER_CASE` (VHDL convention + idiomatic SV generic style; consistent across both dialects) or `lower_case` (modern SystemVerilog house style; less consistent with VHDL)? **Recommendation**: `UPPER_CASE` for cross-dialect consistency — SOS-08 ships both VHDL and SV; consistent parameter spelling reduces friction at the chart-emitter level.

- **PCDN-SOS-08-A-002 — Port-name prefix convention.** AXI-Stream-compatible prefixes (`m_axis_tdata` / `s_axis_tready` / `s_axis_tvalid`) on data-bearing primitives, or bare names (`data` / `ready` / `valid`)? Bare names are simpler; AXI prefixes give plug-and-play compatibility with existing AXI infrastructure. **Recommendation**: bare names on the L0 primitive faces (clean composition with non-AXI consumers); a thin AXI-Stream aliasing wrapper (`sos_fifo_async_axis`, `sos_fifo_sync_axis`) layered on top for the data-bearing primitives where AXI compatibility is wanted. Keeps the L0 surface narrow.

- **PCDN-SOS-08-A-003 — Reset polarity.** Synchronous active-high, synchronous active-low, or asynchronous (active-low typical)? **Recommendation**: synchronous active-high with synchronous release. Synchronous reset eliminates the recovery/removal-time analysis burden; active-high matches the modern open-source-synth (Yosys) idiom and the FreeRTOS-side convention in disco-analyzer. INV-S-HDL-A-1 frozen at this choice; asynchronous reset distribution is the caller's responsibility (typically `sos_synchronizer` on the deassert edge).

- **PCDN-SOS-08-A-004 — Per-primitive default depth/width.** Should `sos_fifo_async` default `DEPTH=16` and `WIDTH=32` (saves typing for the common case)? Or are all resource-determining parameters mandatory (forces explicit area trade-off)? **Recommendation**: mandatory, no defaults (INV-S-HDL-A-5). The cost of typing one extra parameter is trivial; the cost of a silently-defaulted FIFO with the wrong depth is a re-route. Defaults invite mistakes that surface only at synth time.

- **PCDN-SOS-08-A-005 — Internal FSM encoding override.** Per-primitive `STATE_ENCODING` parameter (`ONE_HOT` | `BINARY` | `GRAY`)? Or is one-hot frozen (no per-primitive override)? **Recommendation**: parameter exists, defaults to `ONE_HOT` per §5.2 / INV-S-HDL-A-4; binary override available for ASIC-flow opt-in (matches SOS-08 PCDN-002's chart-emitted FSM convention).

- **PCDN-SOS-08-A-006 — MTBF assertion mechanism.** For `sos_fifo_async` and `sos_synchronizer`, the MTBF claim is mandatory but not formally verifiable. Mechanisms: (a) `assert property` with cover-only-can't-prove against a synthesis-tool-specific path constraint; (b) external sign-off in the build manifest (a `MTBF.md` file the build wrapper checks for existence + structural validity); (c) both. **Recommendation**: (b) external sign-off in `rtl/<primitive>/MTBF.md` with build-wrapper structural validation (file exists, contains required fields: formula, target frequency, target-FF τ value, computed MTBF, sign-off date). Cleaner than mixing prove-vs-cover SVA semantics for a claim that is fundamentally physical.

- **PCDN-SOS-08-A-007 — Cocotb test-bench shape.** One Python file per primitive (`tb/<primitive>/test_<primitive>.py`), or a shared harness with per-primitive test functions (`tb/test_l0.py` with `test_fifo_async()`, `test_fifo_sync()`, ...)? **Recommendation**: one file per primitive. Keeps the per-primitive concerns isolated; matches the per-primitive source-of-truth-map layout (§4); each primitive's tests run independently in CI; failure attribution is unambiguous. Shared-harness pattern can be revisited at SOS-08-D ratification if test-emission code reuse becomes a pain point.

## 12. Acceptance checklist

A conforming SOS-08-A ratification satisfies:

- (a) ⏸ PCDN-SOS-08-A-001 through 007 resolved (§11).
- (b) ⏸ Each of the eleven primitives (§6.1 through §6.11) has its portable-RTL source authored in both VHDL-2008 (`rtl/<primitive>/<primitive>.vhd`) and SystemVerilog-2017 (`rtl/<primitive>/<primitive>.sv`).
- (c) ⏸ Each primitive's vendor-IP shim sources (`rtl/<primitive>/vendor_<vendor>.sv`) authored for the vendors named in its §6 entry (none for portable-only primitives; xilinx/intel/lattice for FIFOs and DPRAM; xilinx/intel/lattice for the synchronizer).
- (d) ⏸ Each primitive's cocotb testbench (`tb/<primitive>/test_<primitive>.py`) authored and passing against the portable-RTL path on at least Icarus Verilog + Verilator simulators.
- (e) ⏸ Each primitive's SVA bind file (`rtl/<primitive>/<primitive>_sva.sv` + `tb/<primitive>/<primitive>_bind.sv`) authored and bound during cocotb runs; all named assertions pass.
- (f) ⏸ For the CDC-crossing primitives (`sos_fifo_async`, `sos_synchronizer`, `sos_dpram_arb` dual-clock mode), `MTBF.md` authored per PCDN-A-006 resolution.
- (g) ⏸ Per-primitive instantiation example (`examples/<primitive>/instantiate.{vhd,sv}`) authored.
- (h) ⏸ Each primitive's portable-RTL path synthesizes via Yosys (SV) and GHDL synth + Yosys (VHDL) against a Lattice ECP5 target without errors (SOS-08 PCDN-006 + SOS-08 §12 (e) prerequisite).
- (i) ⏸ Cross-phase invariants INV-SOS-A through H cited correctly in each primitive's docstring (typically via a `@spec` comment block referencing this doc + SOS-07).
- (j) ⏸ Cross-sub-phase invariants INV-S-HDL-1 through 5 cited correctly per primitive (INV-S-HDL-3 explicitly on `sos_fifo_async` and `sos_synchronizer`).
- (k) ⏸ Cross-primitive invariants INV-S-HDL-A-1 through 5 satisfied (verified by build wrapper).

(a) is the ratification gate; (b)-(k) are implementation gates that flip from ⏸ to ✅ as the implementation lands.

A conforming SOS-08-A *without* `sos_dpram_arb` in dual-clock mode (single-clock-only `sos_dpram_arb`) satisfies (a)-(e), (g)-(k) and a reduced (f). This second-tier conformance level supports the Lattice ECP5 first-target story without the dual-clock DPRAM complexity, deferring dual-clock DPRAM to a later sub-phase amendment.

## 13. Files cited

| Path | Role |
|---|---|
| `docs/concepts/SOS-08-CONCEPTS.md` | Umbrella; this sub-phase's parent. |
| `docs/concepts/SOS-07-CONCEPTS.md` | Cross-phase invariants INV-SOS-A through H; cited not redefined. |
| `docs/concepts/SOS-ROADMAP-07-PLUS.md` | Informative roadmap. |
| `rtl/<primitive>/<primitive>.{vhd,sv}` | Per-primitive portable-RTL sources (forthcoming). |
| `rtl/<primitive>/vendor_<vendor>.sv` | Per-primitive vendor-IP shim sources (forthcoming). |
| `rtl/<primitive>/<primitive>_sva.sv` | Per-primitive SVA assertion modules (forthcoming). |
| `rtl/<primitive>/MTBF.md` | Per-primitive MTBF sign-off (CDC-crossing primitives only; forthcoming). |
| `tb/<primitive>/test_<primitive>.py` | Per-primitive cocotb testbench (forthcoming). |
| `tb/<primitive>/<primitive>_bind.sv` | Per-primitive SVA `bind` directive (forthcoming). |
| `examples/<primitive>/instantiate.{vhd,sv}` | Per-primitive instantiation example (forthcoming). |
| Parent `CLAUDE.md` | Spec-Before-Code Planning Discipline; Phase document shape. |

## 14. Unblocks

This sub-phase's ratification (after PCDN walkthrough) unblocks:

- **SOS-08-B** (L1 service composition) — depends on the per-primitive port surface frozen here.
- **SOS-08-C** (chart → FSM emission) — depends on the L0 instantiation contracts frozen here for the chart compiler's emit step.
- **SOS-08-D / E / F** (cocotb / SV testbench / UVM sequence emission) — depends on per-primitive SVA bind file shapes.
- **SOS-09** (hardware/software membrane) — depends on at least SOS-08-A + SOS-08-B existing (umbrella §14).

## 15. Change log

### 2026-05-23 — Initial draft (Ira)

- Authored `SOS-08-A-CONCEPTS.md` as the per-primitive contract sub-phase under the SOS-08 umbrella.
- §3 canonical glossary: terms `L0 primitive`, `portable RTL`, `vendor-IP shim`, `handshake-port shape`, `SVA bind file`, `MTBF treatment`, `per-target instantiation example`, `internal FSM`.
- §4 source-of-truth map: per-primitive RTL / testbench / bind / MTBF / example file paths.
- §5 frozen decisions: handshake-port direction (ready/valid producer-drives-valid; req/ack 1-cycle-pulses); internal FSM encoding defaults one-hot per SOS-08 PCDN-002 extension; mandatory-no-default convention for resource-determining parameters.
- §6 per-primitive contracts: eleven primitives covered (`sos_fifo_async`, `sos_fifo_sync`, `sos_arbiter_rr`, `sos_arbiter_priority`, `sos_mutex`, `sos_credit_counter`, `sos_dpram_arb`, `sos_tick_gen`, `sos_synchronizer`, `sos_strobe_latch`, `sos_rate_divider`) — interface signature, behavioural contract, SVA properties, vendor-IP shim parameter, MTBF treatment, instantiation example.
- §7 cross-primitive invariants INV-S-HDL-A-1 through 5: uniform reset semantics, handshake associativity, vendor-shim byte-identical wrapper, one-hot internal FSM default, mandatory-parameter-no-default.
- §8 standards integration matrix additions: none (consumes SOS-07 §7 + SOS-08 §8 unchanged).
- §10 reconciliation vs SOS-08 umbrella §6 + PCDN-001 + PCDN-002, and vs forthcoming SOS-08-B.
- §11 seven PCDNs raised covering naming, port prefixes, reset polarity, parameter defaults, FSM encoding override, MTBF mechanism, cocotb shape.
- §12 acceptance checklist: gates (a)-(k); reduced conformance level for single-clock-only `sos_dpram_arb`.

Status: 🟡 **drafted**, awaiting PCDN walkthrough.
