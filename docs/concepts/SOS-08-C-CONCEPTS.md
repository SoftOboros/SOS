# SOS-08-C — Chart → FSM emission (Layer-2 HDL backend)

**Status:** 🟢 **ratified 2026-05-23** (see §15).

## 0. Authority policy

This phase doc ratifies the **Layer-2 (L2) emission contract** under the SOS-08 umbrella (`SOS-08-CONCEPTS.md`, ratified 2026-05-23). The umbrella's §6 SOS-08-C row sketched chart → FSM compilation informatively; this doc takes the umbrella's frozen decisions (one-hot encoding at v1 per PCDN-002; `<region clock="domain_b"/>` annotation per PCDN-010; `--verified-strip` opt-in per PCDN-008; cooperative-only per PCDN-008 + SOS-08-H) and produces the operational emission algorithm.

The L0 primitive surface this doc consumes is owned by `SOS-08-A-CONCEPTS.md` §6; the L1 service surface this doc emits against is owned by `SOS-08-B-CONCEPTS.md` §6.1–6.5. Neither surface is re-derived here; SOS-08-C is the **client** of both.

Per parent CLAUDE.md "Spec-Before-Code Planning Discipline / Phase document shape":

- **Normative** sections: §3 glossary, §4 source-of-truth map, §5 frozen decisions, §6 the emission algorithm (load-bearing), §7 cross-emission invariants (INV-S-HDL-C-*), §10 reconciliation, §12 acceptance checklist.
- **Informative** sections: §1 purpose, §2 problem statement, §8 standards integration matrix (no additions), §11 non-goals, §15 change log.
- All keywords MUST, MUST NOT, SHALL, SHOULD, SHOULD NOT, MAY, RECOMMENDED are interpreted per RFC 2119 / RFC 8174 when capitalised.

This doc cites SOS-07 §6 (INV-SOS-A through H), SOS-08 §7 (INV-S-HDL-1 through 5), SOS-08-A §7 (INV-S-HDL-A-1 through 5), and SOS-08-B §7 (INV-S-HDL-B-1 through 5). None are re-derived.

## 1. Purpose

To take a ratified SCXML statechart (canonical artifact per INV-SOS-A) and produce a synthesizable VHDL-2008 / SystemVerilog-2017 implementation that:

1. Realises each chart **region** as one synthesizable FSM whose state register is encoded per SOS-08 PCDN-002 (one-hot default; per-region binary override via chart annotation).
2. Compiles `<transition>` guards from the SOS-01 §5.1 ECMAScript subset into synthesizable combinational `next_state` logic.
3. Wires chart event ingress / egress to SOS-08-B L1 `sos_message_channel` instances (per INV-S-HDL-3 + SOS-08-B §6.5).
4. Compiles chart `<data>` declarations to RTL signals (typed by chart constant or inferred from initial value); `<assign>` to combinational or registered assignments per chart semantics.
5. Honours per-region `<region clock="..."/>` annotations by instantiating `sos_synchronizer` or `sos_fifo_async` at every cross-domain transition (INV-S-HDL-3).
6. Supports `--verified-strip` opt-in: bound-analysis-eliminated branches emit `assume false` annotations the synth tool consumes to optimize state encoding + remove unreachable transitions (mirrors SOS-13's Rust mechanism).
7. Honours cooperative-only scheduling (INV-S-HDL-4; SOS-08-H): FSMs run to completion within one chart macrostep; no preemption / save-restore mechanism.

The chart is the spec; this phase is the bridge that turns one of the per-region trees of that spec into one of the per-region trees of synthesizable RTL, with every chart-vocabulary failure observable per INV-S-HDL-5.

## 2. Problem statement

Four pressures motivate ratifying L2 emission as its own sub-phase, separate from L0 / L1 / cocotb-emit:

1. **The L2 contract is what makes SOS-08 a "kernel" rather than a primitive library.** L0 + L1 alone is `dcfifo` + `xpm_fifo_sync` with house labels. The unlock the umbrella's §2 names ("statechart-driven HDL backend can be the kernel") is L2: chart regions become FSMs, and those FSMs compose against the L1 services using the same handshake-port shape every chart-side syscall lowers to. Ratifying L2 separately surfaces the emission contract for review independent of the primitive library.

2. **Multi-clock-domain handling is the load-bearing correctness claim.** A chart region annotated `<region clock="domain_b"/>` has different correctness obligations than a single-domain region — every transition crossing the annotation needs a `sos_synchronizer` or `sos_fifo_async` (INV-S-HDL-3). The emission algorithm has to enforce this at compile time; INV-S-HDL-C-3 (this doc, §7) is the formal claim.

3. **`--verified-strip` interaction with multi-clock-domain is non-trivial.** Per PCDN-SOS-08-C-002 (this doc), if the bound analysis declares a cross-domain transition unreachable, does the synchronizer get stripped along with the transition? The answer determines whether `--verified-strip` is a pure optimization or a verification-claim narrowing. The resolution affects every chart with both annotations.

4. **Guard-condition compilation needs an explicit upper bound.** SOS-01 §5.1's 12-feature ECMAScript subset is already small; synthesis tools translate combinational logic of bounded depth without protest. But unbounded chained `&&` / `||` / numeric expressions risk routing-congestion failure at place-and-route. Per PCDN-SOS-08-C-004, the emitter ought to publish a guard-depth budget that the chart linter enforces, or accept the synthesis-tool-determined cliff. Either resolution becomes a chart-author-facing contract.

## 3. Canonical glossary

Terms normative within SOS-08-C+. Authority relationships per §8.

| Term | Definition |
|---|---|
| **Region FSM** | One synthesizable FSM per SCXML region (a top-level state, OR an orthogonal child of `<parallel>`). One state register per region; state encoding per SOS-08 PCDN-002 (one-hot default) with per-region binary override via chart annotation. As defined in SOS-08 §3 "Layer 2 (L2) tasks"; **adapted**: this doc names the per-region FSM explicitly and freezes its encoding rules. |
| **Transition mux** | The combinational `next_state` logic for one region's FSM, encoded as a per-state mux whose select inputs are the chart-author-declared guard conditions and whose priority follows the chart's transition source order (top-to-bottom in the SCXML document). Frozen at §5.2. |
| **Guard expression** | A boolean expression of the SOS-01 §5.1 12-feature ECMAScript subset that compiles to combinational RTL. As defined in SOS-01 §5.1 "Permitted ECMAScript feature"; **adapted**: this doc names the synthesizable-RTL realisation rule per §5.3 + INV-S-HDL-C-4. |
| **Event ingress port** | The Layer-1 `sos_message_channel` receive face that drives a region FSM's transition triggers. Owned by SOS-08-B §6.5; this doc names how chart events map to instances. |
| **Event egress port** | The L1 `sos_message_channel` send face that a chart `<raise>` element targets. Owned by SOS-08-B §6.5; this doc names how `<raise>` lowers to a `send` invocation. |
| **Datamodel signal** | An RTL signal compiled from a chart `<data>` element. Typed by chart-side constant width or inferred from initial value per §5.4. |
| **Clock annotation** | An SCXML `<region clock="domain_b"/>` attribute or equivalent on `<state>` / `<parallel>` declaring which clock domain the region runs in. Owned by SOS-08 PCDN-010 resolution; **adapted** here with the default-clock rule per PCDN-SOS-08-C-001. |
| **Reset state** | The chart-emission-time designation of the FSM's `rst`-asserted state. As defined in SCXML's `initial` semantic; **adapted** per PCDN-SOS-08-C-003 with an explicit per-region `<reset>` annotation override mechanism. |
| **Verified-strip mode** | The `--verified-strip` codegen-tool flag that emits `assume false` annotations at bound-analysis-eliminated branches. Owned by SOS-08 PCDN-008 resolution; **adapted** here per §5.5 with the multi-clock-domain interaction rule. |
| **Cooperative completion** | The per-macrostep guarantee that every region FSM transitions reach a stable state within one tick. Owned by SOS-08 §5.2 + SOS-08-H; **mirrored** here at INV-S-HDL-C-5. |

## 4. Source-of-truth map

| Concept | Authority |
|---|---|
| L0 primitive contracts | `SOS-08-A-CONCEPTS.md` §6 (cited not redefined) |
| L1 service contracts | `SOS-08-B-CONCEPTS.md` §6.1–6.5 (cited not redefined) |
| Chart ECMAScript subset | `SOS-01-CONCEPTS.md` §5.1 (cited not redefined) |
| Chart external event vocabulary | `SOS-01-CONCEPTS.md` §5.3 (cited not redefined) |
| Chart state-id vocabulary | `SOS-01-CONCEPTS.md` §5.4 (cited not redefined) |
| Multi-clock-domain annotation shape | SOS-08 PCDN-010 (`<region clock="..."/>`); **mirrored** in §6.6 with per-region default rule |
| One-hot encoding default | SOS-08 PCDN-002 (this doc, §5.1) |
| Verified-strip flag | SOS-08 PCDN-008 (this doc, §5.5) |
| Cooperative-only scheduling | SOS-08 §5.2 + SOS-08-H (cited not redefined) |
| Region-FSM emission algorithm | **this doc** §6 |
| Per-region encoding override | **this doc** §5.1 + PCDN-SOS-08-C-005 |
| Reset-state default | **this doc** §5.6 + PCDN-SOS-08-C-003 |
| Guard-depth budget | **this doc** §5.3 + PCDN-SOS-08-C-004 |
| Verified-strip × multi-clock interaction | **this doc** §5.5 + PCDN-SOS-08-C-002 |
| Cross-phase invariants INV-SOS-A through H | `SOS-07-CONCEPTS.md` §6 |
| Cross-sub-phase invariants INV-S-HDL-1 through 5 | `SOS-08-CONCEPTS.md` §7 |
| L0 cross-primitive invariants INV-S-HDL-A-1 through 5 | `SOS-08-A-CONCEPTS.md` §7 |
| L1 cross-service invariants INV-S-HDL-B-1 through 5 | `SOS-08-B-CONCEPTS.md` §7 |
| L2 cross-emission invariants INV-S-HDL-C-1 through 5 | **this doc** §7 |

## 5. Frozen decisions

### 5.1 State register encoding default

Per SOS-08 PCDN-002 resolution: **one-hot at v1** for chart-emitted region FSMs. Per-region override via `<region encoding="binary"/>` (or `gray`) chart annotation. The annotation MAY appear on any region a chart author designates; the emitter MUST honor it without re-validating reachability claims.

Frozen-enumeration registration policy: **Standards Action** (modifying default requires SOS-08 §15 amendment; modifying override mechanism shape requires §15 amendment here).

### 5.2 Transition mux priority discipline

For each region, the emitter SHALL produce one combinational `next_state` mux per source state. The mux's case-arms enumerate the outgoing transitions of that state in **document order** (top-to-bottom as the transitions appear in the SCXML source). The first arm whose guard evaluates true wins; subsequent arms are not evaluated (priority-first matches SCXML semantics). Where no transition's guard is true, the mux output is the current state (no transition).

Document-order priority is the chart-author-visible contract; reordering transitions in the SCXML edits which transition wins on simultaneous-guard-true cycles. Lint rule `SCXML-LINT-C-1` (proposed in §11 as PCDN-SOS-08-C-006) warns when two transitions in the same source state could simultaneously be true under the chart's bounded reachability.

Frozen-enumeration registration policy: **Standards Action**.

### 5.3 Guard expression compilation

Per SOS-01 §5.1 + INV-S-LINT-4 (ECMAScript subset is append-only): the emitter compiles only constructs marked `Permitted` in `ECMAScriptFeature`. Compilation strategy:

| Construct | RTL realisation |
|---|---|
| Boolean operator (`&&`, `\|\|`, `!`) | Combinational gate |
| Equality / inequality (`==`, `!=`) on datamodel signals | Combinational comparator |
| Numeric comparison (`<`, `<=`, `>`, `>=`) | Synthesizable comparator (sign per chart datamodel type) |
| Datamodel access (`x`, `x.field`) | Direct signal reference (`<region>__data_x` signal) |
| Event-data access (`_event.data.foo`) | Reference to event-ingress channel's payload field at chart-compile-time slice |
| Function call to `In(state-id)` | Comparator against the named region's state register |
| Literal constant | Synthesizable constant |
| Compound (parenthesised) expression | Recursively compiled |

Guard-depth budget per PCDN-SOS-08-C-004.

Frozen-enumeration registration policy: **Standards Action** (matches SOS-01 §5.1's append-only policy via citation).

### 5.4 Datamodel signal typing

Per chart `<data>` element, the emitter compiles to one RTL signal:

- **Width**: explicit chart annotation (`<data id="x" width="8"/>`) → that width; else SOS-04 / SOS-05 datamodel-default width (`i32` ≅ 32 bits) → 32-bit signed signal.
- **Initial value**: from the chart `<data expr="..."/>` attribute, evaluated at chart-compile time (constant expression only); used as the FSM's reset value for that signal.
- **Mutability**: signals modified only by chart `<assign>` are emitted as registered (clocked) signals; signals appearing only on the right of `<assign>` are emitted as combinational wires.

Frozen-enumeration registration policy: **Specification Required** (width-mapping table is phase-local; flipping it is cheap).

### 5.5 Verified-strip flag

Per SOS-08 PCDN-008 resolution: opt-in via `--verified-strip` codegen-tool flag (parallel to SOS-13's Rust mechanism). Default emission preserves all transitions; `--verified-strip` emits `assume false` annotations on bound-analysis-eliminated branches, which the synth tool consumes to optimize state encoding + remove unreachable transitions.

Verified-strip × multi-clock interaction is **PCDN-SOS-08-C-002** (this doc); the resolution determines whether a synchronizer instance is stripped when the bound analysis declares its sole consumer transition unreachable.

Frozen-enumeration registration policy: **Standards Action** (cross-phase contract with SOS-13; mutating requires coordinated amendment).

### 5.6 Reset-state default

Per SCXML semantics: each region declares an `<initial>` state. The emitter compiles `<initial>` as the FSM's reset value (the state the state register holds while `rst == 1`). An explicit per-region `<reset>` annotation MAY override the SCXML `<initial>` for codegen purposes (use case: a chart whose `<initial>` is a transient bootstrap state that the FSM should NOT re-enter on warm reset). Resolution at PCDN-SOS-08-C-003.

Frozen-enumeration registration policy: **Standards Action**.

### 5.7 Cooperative-only emission

Per SOS-08 §5.2 + SOS-08-H + INV-S-HDL-4: no preemption mechanism. The emitter emits no save-restore registers, no priority-preemption arbitration on region-FSM state, no nested-interrupt unwind logic. Region FSMs run to completion within one macrostep; the macrostep boundary is the chart-side `sys.tick` event (driven by an upstream `sos_tick_gen` per SOS-08-B §6.4).

Frozen-enumeration registration policy: **Standards Action** (re-opening requires SOS-08-H §15 amendment + cross-phase review).

## 6. The emission algorithm

The codegen tool (rooted at `tools/sos-codegen/` per SOS-08 §13) gains an `hdl-emit` subcommand whose contract this section ratifies. Walked step-by-step with the chart on disk as input and `build/<chart>/{vhd,sv}/` as output.

### 6.1 Step 1 — Parse SCXML; build region tree

Input: chart SCXML at path `P`. The emitter parses `P` via the canonical scjson interchange (per SOS-00 §4) into the in-memory chart model. From the model, build the **region tree**: one root region per top-level state, plus one region per child of every `<parallel>`. Each region carries:

- A list of its states (the leaves of the region's SCXML state tree).
- A list of its outgoing transitions, with source state, target state, event-name, guard expression.
- Its declared clock domain (default `main`; override via `<region clock="..."/>`).
- Its encoding choice (default `one-hot`; override via `<region encoding="binary"/>` etc.).
- Its reset state (`<initial>` or `<reset>` override per §5.6).

Per INV-S-HDL-C-1, the region tree is finite and acyclic (sibling regions are independent per SCXML `<parallel>` semantics; nested regions form a tree).

### 6.2 Step 2 — Synthesize per-region FSM modules

For each region in the region tree, emit one synthesizable module:

- **State register**: width = `N` (one-hot, with `N` = state count) OR `ceil(log2(N))` (binary / Gray, with appropriate decoder).
- **Reset value**: encoded form of the reset state per §5.6.
- **Next-state logic**: one mux per source state, case-arms ordered per §5.2.
- **Output strobes**: one combinational output per chart `<raise>` or `<send>` element within the region's states/transitions; the strobe is asserted on the cycle the transition fires.

The module's port list is uniform per SOS-08 §3 "Layer 2 (L2) tasks":

```systemverilog
module sos_region_<region_id> #(
    parameter int DATA_WIDTH = 32   // datamodel signal width default; per-data override via local param
)(
    input  logic clk,
    input  logic rst,
    input  logic tick,                                // from upstream sos_tick_gen (cooperative-completion gate)
    // event ingress (one sos_message_channel receive face per chart-declared external event)
    input  logic evt_<ev>_valid,
    input  logic [EVENT_PAYLOAD_WIDTH-1:0] evt_<ev>_payload,
    output logic evt_<ev>_ready,
    // event egress (one sos_message_channel send face per chart-declared <raise> / <send>)
    output logic raise_<ev>_valid,
    output logic [EVENT_PAYLOAD_WIDTH-1:0] raise_<ev>_payload,
    input  logic raise_<ev>_ready,
    // datamodel signal exposure (read-only outward; write-port internal)
    output logic [DATA_WIDTH-1:0] data_<x>,
    // observability (for cocotb / SVA bind file consumption)
    output logic [STATE_WIDTH-1:0] state_observable,
    output logic                   transition_observable   // 1-cycle pulse on every fired transition
);
```

The `state_observable` + `transition_observable` ports satisfy INV-S-HDL-C-2 (every region FSM exposes its state for SVA / cocotb consumption; per INV-S-HDL-5 + INV-S-HDL-B-5).

### 6.3 Step 3 — Compile guard expressions

For each transition, compile the `cond="..."` attribute (if present) to combinational RTL per §5.3. The compiled expression becomes the case-arm's guard.

The compile target is intermediate-form: a Boolean expression over RTL signals (datamodel signals, event-ingress payload fields, `In(state-id)` evaluations). The emitter then materialises the expression as VHDL `when ... else ...` chains and SV `case`/`?:` chains, choosing the form that the dialect's synth tool optimizes best.

Per PCDN-SOS-08-C-004, the emitter MAY refuse to compile guards whose Boolean depth exceeds a configured budget (default: 8 operators chained; chart-side `SCXML-LINT-C-2` enforces the same budget at lint time so the failure surface is the chart, not the codegen tool).

### 6.4 Step 4 — Wire event ingress via L1 `sos_message_channel`

For each external event in `SOS-01 §5.3 ExternalEventName` that the region's transitions consume, emit one `sos_message_channel` receive-face port wired to the region's event-ingress mux.

The event-name → channel mapping is global per chart: one `sos_message_channel` instance per event name, with the chart-top-level wrapper instantiating each channel exactly once and distributing the receive face to every region that consumes the event. Per INV-S-HDL-C-3, cross-domain event consumption uses `sos_message_channel` (the cross-clock-domain L1 service) — the synchronizer is internal to the channel, satisfying INV-S-HDL-3 by construction.

The event-name-decode for transition-trigger purposes is a comparator on the channel's `recv_event_id` output against the chart-compile-time-fixed `ExternalEventName` index for the transition's `event="..."` attribute.

### 6.5 Step 5 — Wire event egress via L1 `sos_message_channel`

Chart `<raise event="ev"/>` elements lower to a `send_valid` pulse on the named channel's send-face port. Per the chart's `<send>` target attribute (SCXML semantics), the receiving region's clock domain is known at emission time; if the receiver is in a different clock domain than the sender, the underlying `sos_fifo_async` of `sos_message_channel` handles the CDC per INV-S-HDL-3 + SOS-08-B §6.5.

For `<send>` elements with `delay="..."` attributes: per umbrella PCDN-008 (cooperative-only), delayed sends are NOT supported at v1; the lint rule rejects them with chart-vocabulary guidance ("use a `sos_periodic_task` chart region per SOS-08-B §6.4 instead of `<send delay/>`").

### 6.6 Step 6 — Compile datamodel + `<assign>`

For each chart `<data>` element, emit one RTL signal per §5.4. For each `<assign>` element:

- **Inside an `<onentry>` / `<onexit>`** → emit a registered assignment in the FSM's clocked process: `if (next_state == <target>) data_<x> <= <expr>;`
- **Inside a transition `<assign>` child** → emit a registered assignment gated by the transition's firing strobe.
- **Inside a `<datamodel>` `<data expr="..."/>` initialiser** → emit as the reset value of the corresponding signal.

The RHS expression compiles via §5.3's rules.

Per INV-S-HDL-C-4, every datamodel-write site is observable: the codegen tool emits one debug strobe per `<assign>` site that the cocotb testbench MAY bind to (controlled by a per-region `DEBUG_OBSERVABILITY` parameter — defaults to enabled in cocotb-compiled flows, disabled in synth flows where the strobes are pruned by dead-code elimination).

### 6.7 Step 7 — Honor `<region clock="..."/>` annotation

For each region whose `clock` annotation differs from the parent's clock domain:

1. Emit the region FSM with its own `clk` / `rst` port wired to the named domain.
2. For every transition into the region from a parent-domain region, route the triggering event through a `sos_message_channel` (CDC-bearing) instantiated at the chart-top wrapper.
3. For every chart `<raise>` / `<send>` from the region to a parent-domain region, same.
4. Emit a one-line audit entry per cross-domain transition in `build/<chart>/cdc-audit.json`: `{transition_id, src_clock, dst_clock, channel_instance}`. The audit file is consumed by INV-S-HDL-3's verification step (every cross-domain signal has a synchronizer).

Default clock domain per PCDN-SOS-08-C-001: regions without an explicit `clock` annotation inherit the parent region's clock domain (recursively up to the root, which defaults to `main`). This rule mirrors HDL synthesis-tool defaults; explicit-only annotation would force every chart to annotate every region, which is verbose.

### 6.8 Step 8 — Honor `--verified-strip` (opt-in)

When the codegen tool is invoked with `--verified-strip`:

1. Run the bound-analysis pass (the same pass SOS-03 already runs for vector emission, extended for per-target emission).
2. For each transition the bound analysis declares unreachable, emit:
   - **VHDL**: a `-- pragma synthesis_off assume_false_<transition_id>` comment annotation that VHDL synth tools consume.
   - **SystemVerilog**: an `assume property (@(posedge clk) 1'b0);` annotation gated by the transition's state-and-guard predicate, that synth tools consume to optimize state encoding.
3. Per PCDN-SOS-08-C-002 resolution, the synchronizer instances on the stripped cross-domain transition's path are EITHER stripped (treating `--verified-strip` as a full prune) OR retained (treating `--verified-strip` as conservative — synchronizers stay because their MTBF claim doesn't depend on the chart's reachability). PCDN-SOS-08-C-002 picks one; the recommendation is **retain synchronizers** to keep MTBF claims independent of reachability (synthesis-tool gains from removed transitions; physical reliability stays intact).

`--verified-strip` MAY be combined with `--verified-strip-aggressive` (a future flag) for the strip-everything mode if a customer demands it.

### 6.9 Step 9 — Emit datamodel-shared module

For datamodel signals shared across regions, the codegen tool emits one **datamodel module** per chart that:

- Owns the shared signals as registered values.
- Exposes a read port to each region (one combinational output per signal).
- Owns the write arbiter (`sos_arbiter_priority` per INV-S-HDL-A-2's associative composition; arbiter mode set per chart annotation, default RR).

Write arbitration matters because two regions may `<assign>` the same datamodel field on the same cycle; the arbiter encodes the chart-author's intended priority. The lint warning `SCXML-LINT-C-3` (proposed) fires when two regions write the same field with no explicit priority annotation.

### 6.10 Step 10 — Emit chart-top wrapper

The codegen tool emits a chart-top wrapper instantiating:

- One `sos_tick_gen` per clock domain.
- One `sos_message_channel` per `ExternalEventName` × clock-domain pair the chart consumes.
- One `sos_region_<region_id>` per region in the region tree.
- The datamodel module per §6.9.
- IO ports: clock(s), reset(s), the chart's externally-facing events (the subset of `ExternalEventName` that maps to physical IO per the chart's `<send>` / `<datamodel>` declarations).

The wrapper is a generated artifact in `build/` per SOS-08 PCDN-011 resolution; per-board IO pin assignment is a board-specific file the user maintains.

### 6.11 Worked example sketch

Given a 4-state region with transitions on two events (`a.tick`, `a.done`), one shared datamodel signal `cycle_count` (i32), and the region annotated `<region clock="main"/>`:

```systemverilog
// region S_a — 4 states {IDLE, ACTIVE, DONE, ERROR}, one-hot encoding
module sos_region_a #(parameter int DATA_WIDTH = 32) (
    input  logic clk, rst, tick,
    input  logic evt_a_tick_valid, input  logic [63:0] evt_a_tick_payload, output logic evt_a_tick_ready,
    input  logic evt_a_done_valid, input  logic [63:0] evt_a_done_payload, output logic evt_a_done_ready,
    output logic raise_a_finished_valid, output logic [63:0] raise_a_finished_payload, input logic raise_a_finished_ready,
    output logic [31:0] data_cycle_count,
    output logic [3:0] state_observable, output logic transition_observable
);
  logic [3:0] state, next_state;
  always_ff @(posedge clk) if (rst) state <= 4'b0001 /* IDLE */; else state <= next_state;

  always_comb begin
    next_state = state;
    transition_observable = 1'b0;
    unique case (1'b1)
      state[0] /* IDLE */: if (evt_a_tick_valid) begin next_state = 4'b0010 /* ACTIVE */; transition_observable = 1'b1; end
      state[1] /* ACTIVE */: if (evt_a_done_valid) begin next_state = 4'b0100 /* DONE */; transition_observable = 1'b1; end
      state[2] /* DONE */: next_state = 4'b0001;
      state[3] /* ERROR */: ; // sink
    endcase
  end

  // cycle_count <- assigned on entry to ACTIVE
  always_ff @(posedge clk) if (rst) data_cycle_count <= 0; else if (next_state[1] && !state[1]) data_cycle_count <= data_cycle_count + 1;

  assign state_observable = state;
  assign evt_a_tick_ready = state[0];
  assign evt_a_done_ready = state[1];
  assign raise_a_finished_valid = state[1] && evt_a_done_valid;
  assign raise_a_finished_payload = '0;
endmodule
```

Sketch only; the canonical emission is rendered from the chart's regional tree per §6.1–6.10 in deterministic order so the same chart always produces the same RTL (INV-S-HDL-C-1).

## 7. Cross-emission invariants

In addition to INV-SOS-A through H (SOS-07), INV-S-HDL-1 through 5 (SOS-08), INV-S-HDL-A-1 through 5 (SOS-08-A), and INV-S-HDL-B-1 through 5 (SOS-08-B), the following invariants are normative within SOS-08-C:

- **INV-S-HDL-C-1 — Deterministic emission.** Given a fixed chart SCXML and a fixed set of codegen flags (`--verified-strip`, `--vendor=*`), the emitter SHALL produce byte-identical RTL output (modulo timestamps that the emitter MUST elide from the output by default). The region tree's traversal order is deterministic (depth-first, source-order at each node).

- **INV-S-HDL-C-2 — Per-region observability.** Every region FSM module emitted SHALL expose `state_observable` + `transition_observable` ports so SOS-08-D/E cocotb / SVA bind files can attach without requiring source modification. Concretises INV-S-HDL-5 (chart-vocabulary traceability) at the L2 contract.

- **INV-S-HDL-C-3 — Cross-domain transition enforcement.** Every transition whose source and target regions have different `clock` annotations SHALL pass through a `sos_message_channel` (or `sos_synchronizer` for direct signal-level crossings). The emitter MUST fail with a chart-vocabulary error if it cannot place such a synchronizer (e.g., the chart's annotation is malformed). Concretises INV-S-HDL-3 (cross-domain isolation) at the L2 emission contract.

- **INV-S-HDL-C-4 — Guard expression is synthesizable.** Every `cond` attribute in the chart MUST compile to combinational RTL within the bounded subset of SOS-01 §5.1. The emitter rejects any chart whose `cond` references a forbidden ECMAScript construct (deferring to `SCXML-LINT-009` which fires earlier in the pipeline). Concretises INV-S-LINT-4 (ECMAScript subset is append-only) at the codegen target.

- **INV-S-HDL-C-5 — Cooperative completion.** Every region FSM SHALL reach a stable state (no transition's guard true) within one macrostep tick. The chart's bounded-reachability analysis verifies this property at chart-compile time; the emitter does NOT emit a "safety net" preemption mechanism. Concretises INV-S-HDL-4 (cooperative-only) at the L2 contract.

## 8. Standards integration matrix additions

This sub-phase does not introduce new external standards; it consumes the rows already declared in SOS-07 §7, SOS-08 §8, SOS-08-A §8 (no additions), and SOS-08-B §8. No additions.

(For completeness: the SCXML W3C grammar, the SOS-01 §5.1 ECMAScript subset, and the synthesizable VHDL-2008 / SV-2017 subsets are all declared upstream; this sub-phase composes their derivation paths into a single emission pipeline without introducing new upstream authorities.)

## 9. Frozen enumerations from SOS-08-C

This phase freezes:

### 9.1 Encoding override values

`{ one_hot, binary, gray }` — the legal values of the `<region encoding="..."/>` annotation. `one_hot` is the default (per §5.1).

Registration policy: **Specification Required** (adding a value, e.g. `johnson`, is a phase-owner walkthrough update; modifying the default requires a §15 amendment here AND a SOS-08 §15 amendment).

### 9.2 Verified-strip mode synchronizer-retention policy

`{ retain_synchronizers, strip_synchronizers }` — the two possible PCDN-SOS-08-C-002 outcomes. Recommendation: `retain_synchronizers` (default).

Registration policy: **Standards Action** (mutating this affects MTBF-claim independence; cross-phase review required).

## 10. Reconciliation decisions vs adjacent repo primitives

### vs. SOS-08-A (L0 primitive surface)

This doc emits instances of L0 primitives via the L1 services (SOS-08-B) — NOT direct L0 instances inside region FSMs. The L1 layer is the chart-author-facing surface; the L2 emission is composed of L1 instances, not L0 ones. Direct L0 use would re-derive the L1 contract surface, breaking INV-S-HDL-B-2 (L0 non-modification at the L1 layer; the L2 layer mirrors that discipline).

### vs. SOS-08-B (L1 service surface)

Every event ingress / egress port emitted per §6.4 / §6.5 wires to an `sos_message_channel` instance (SOS-08-B §6.5). Every periodic-task region (a region with chart-side `<region periodic="..."/>` annotation, proposed) wires to an `sos_periodic_task` (SOS-08-B §6.4). Resource-pool acquire / release lowers to `sos_resource_pool` (SOS-08-B §6.3). Mailbox / event-group services are exposed when the chart explicitly references them (chart-side `<send target="mailbox-X"/>`). The L2 emitter is a **client** of every L1 service; SOS-08-B is the supplier-side contract.

### vs. SOS-01 §5.1 ECMAScript subset

Guard-expression compilation (§5.3 / §6.3) consumes the SOS-01 §5.1 subset as ratified, with no extensions. Adding a feature to §5.1 requires an INV-S-LINT-4 amendment in SOS-01 AND a §15 amendment here recording the new construct's RTL realisation rule. INV-S-HDL-C-4 enforces this at codegen time.

### vs. SOS-01 §5.3 `ExternalEventName`

Event-name-decode comparators (§6.4) consume the SOS-01 §5.3 stable index. Adding an event widens the message-channel `event_id` width when the enum exceeds the current `EVENT_ID_WIDTH`; per SOS-08-B §6.5, pruning is by deprecation, never by index reuse. INV-S-LINT-3 (SOS-01) is the upstream invariant.

### vs. SOS-12 (recursive chart dispatch)

Chart dispatch via SOS-12's `<dispatch ref="..."/>` (or `<state src="..."/>`) mechanism composes at the L2 layer: a parent chart's dispatch-target region is replaced at emission time by an instantiation of the sub-chart's L2 RTL. The L1 services connecting parent to sub-chart are the parent's `sos_message_channel` instances per the sub-chart's declared events-in / events-out contract. SOS-12's per-layer × independence-axes bound composition (INV-SOS-F) is honoured: the L2 emitter compiles each sub-chart's regions independently, and the chart-top wrapper composes them per the parent's dispatch declarations. The contract-matching check at chart-compile time ensures sub-chart events-in are covered by parent events-out (SOS-12 §5.3); the L2 emitter trusts the check has passed before emission.

### vs. SOS-13 (verified-codegen for Rust)

`--verified-strip` mirrors SOS-13's Rust mechanism (per SOS-08 PCDN-008): the bound-analysis pass is shared; the emission strategy differs (`assume false` annotations to synth tools vs Rust `unreachable!()` calls). Cross-target consistency means a chart compiled with `--verified-strip` for both Rust and HDL targets has the same pruned transitions on both sides of the membrane.

### vs. INV-SOS-G (verified-codegen position)

Per SOS-08 §10 reconciliation, the HDL analog of INV-SOS-G's verified-codegen position is the `--verified-strip` mechanism (§5.5). This doc ratifies the HDL realisation; SOS-13 ratifies the Rust realisation; both are concretisations of INV-SOS-G applied per-target.

## 11. Non-goals

This sub-phase does NOT:

- Author the L0 primitive contracts (SOS-08-A) or the L1 service contracts (SOS-08-B).
- Specify the cocotb test framework, the SVA bind-file format, the UVM-sequence emission, or the waveform-annotation format (SOS-08-D/E/F/G respectively).
- Specify the bounded-reachability algorithm; SOS-03 owns that, and this doc consumes the per-region reachability output via the codegen tool's existing pass.
- Add new lint rules to SOS-01 §5.5 `LintRuleId`. The `SCXML-LINT-C-*` rules proposed in §6 / §11 are forward-declared; landing them requires a SOS-01 §15 amendment.
- Replace SCXML's `<initial>` semantic; the `<reset>` override per §5.6 is an additive annotation, not a replacement.
- Emit preemption-supporting RTL (per INV-S-HDL-4 / INV-S-HDL-C-5 / SOS-08-H).
- Bench-validate the emitted RTL — that's the umbrella SOS-08 §12 (e) acceptance gate, satisfied at SOS-08-C implementation rather than ratification.

## 12. Acceptance checklist

A conforming SOS-08-C ratification satisfies:

- (a) ⏸ PCDN-SOS-08-C-001 through 006 (§14) resolved with §15 amendment entries.
- (b) ⏸ Emission algorithm §6.1–6.10 ratified as the operational contract.
- (c) ⏸ Cross-emission invariants INV-S-HDL-C-1 through 5 (§7) ratified.
- (d) ⏸ Standards integration matrix additions: none (§8 explicitly records this).
- (e) ⏸ Reconciliation §10 records the relationship to SOS-08-A, SOS-08-B, SOS-01 §5.1 / §5.3, SOS-12, SOS-13.
- (f) ⏸ Codegen tool gains an `hdl-emit` subcommand that takes SCXML in and emits VHDL + SV out per §6 (implementation gate, fires at the implementation PR).
- (g) ⏸ At least one chart region (recommended: a sub-region factored out of `rtos_kernel.scxml`) emits via `hdl-emit` and synthesizes via Yosys + GHDL synth + Yosys against the Lattice ECP5 target without errors (implementation gate; partial satisfaction of SOS-08 §12 (e)).
- (h) ⏸ The emitted region FSMs pass their cocotb tests (SOS-08-D's per-region test framework) and SVA bind files (SOS-08-D's bind layer); INV-S-HDL-C-2 verified.
- (i) ⏸ A multi-clock-domain worked example (one region with `<region clock="domain_b"/>`) exercises §6.7 and the `build/<chart>/cdc-audit.json` audit (implementation gate).
- (j) ⏸ A `--verified-strip` worked example exercises §6.8 (implementation gate); the synth tool measurably benefits (state-encoding bits reduced).

A conforming SOS-08-C *without* multi-clock-domain support (single-domain only) satisfies (a)-(h), (j); (i) is deferred. This second-tier conformance supports the Lattice ECP5 first-target story without the multi-clock-domain complexity, deferring CDC-bearing emission to a later sub-phase amendment.

## 13. Files cited

| Path | Role |
|---|---|
| `docs/concepts/SOS-08-CONCEPTS.md` | Umbrella; §5.1 dialects, §5.2 cooperative-only, §5.3 vendor-IP override, §6 SOS-08-C sketch, §7 INV-S-HDL-1 through 5, §15 PCDN-002/008/010 resolutions. |
| `docs/concepts/SOS-08-A-CONCEPTS.md` | L0 primitive surface; cited by primitive name. |
| `docs/concepts/SOS-08-B-CONCEPTS.md` | L1 service surface; this doc emits against §6.1–6.5. |
| `docs/concepts/SOS-07-CONCEPTS.md` | Cross-phase invariants INV-SOS-A through H; AuthorityRelationship matrix. |
| `docs/concepts/SOS-01-CONCEPTS.md` | §5.1 ECMAScript subset; §5.3 ExternalEventName; §5.4 StateId; INV-S-LINT-3 / INV-S-LINT-4. |
| `docs/concepts/SOS-03-CONCEPTS.md` | Bounded-reachability algorithm; the bound-analysis pass `--verified-strip` consumes. |
| `docs/concepts/SOS-12-CONCEPTS.md` | Recursive chart dispatch; composition rule §10 references. |
| `docs/concepts/SOS-13-CONCEPTS.md` | Verified-codegen for Rust; cross-target consistency for `--verified-strip`. |
| `rtos_kernel.scxml` | Bootstrap kernel chart; worked-example emission target candidate. |
| `tools/sos-codegen/` | Codegen tool; gains the `hdl-emit` subcommand per §6. |
| Parent `CLAUDE.md` | Spec-Before-Code Planning Discipline; Phase document shape. |

## 14. Pending Concept Decision Notices (PCDNs)

These open questions move this doc from 🟡 drafted to 🟢 ratified.

- **PCDN-SOS-08-C-001 — Per-region clock-domain default.** A region without an explicit `<region clock="..."/>` annotation: does it (a) **inherit the parent region's clock domain** (default `main` at root), or (b) **default explicitly to `main` regardless of parent**, or (c) **require explicit annotation** (no implicit default)? **Recommendation**: (a) inherit-from-parent, with root defaulting to `main`. Matches HDL synthesis-tool defaults; minimises chart-author annotation burden for the single-domain common case; surfaces the cross-domain transition exactly where the annotation appears.

- **PCDN-SOS-08-C-002 — Verified-strip × multi-clock interaction.** When `--verified-strip` declares a cross-domain transition unreachable, does the underlying `sos_synchronizer` / `sos_message_channel` instance get stripped along with the transition? Options: (a) **retain_synchronizers** (MTBF claim is independent of reachability; synthesis gains from removed transitions; physical reliability stays intact); (b) **strip_synchronizers** (maximum gate-count reduction; the MTBF claim narrows to "for reachable transitions only"). **Recommendation**: (a) retain_synchronizers. MTBF claims should not depend on chart reachability proofs — a downstream code change that re-enables the transition would silently re-create the CDC hazard without re-running MTBF analysis. Synchronizer retention costs ~10 flops per CDC path; trivial.

- **PCDN-SOS-08-C-003 — Reset-state default.** Use the SCXML `<initial>` state as the FSM reset state, OR require an explicit `<reset state="..."/>` annotation per region? **Recommendation**: SCXML `<initial>` is the default; per-region `<reset state="..."/>` annotation MAY override (use case: a chart whose `<initial>` is a transient bootstrap state that the FSM should NOT re-enter on warm reset; the chart author annotates the warm-reset target explicitly). Matches SCXML semantics for cold-boot; surfaces warm-reset semantics only when the chart cares.

- **PCDN-SOS-08-C-004 — Guard-condition combinational depth limit.** Should the emitter publish a chart-side guard-depth budget (default: 8 chained operators), enforce it via `SCXML-LINT-C-2`, and reject deeper guards at chart-compile time, OR accept whatever the chart's `cond` attribute names and let the synthesis-tool's place-and-route stage flag the routing-congestion failure? **Recommendation**: emitter publishes budget (default 8), lint rule enforces at chart-compile time, surfaces failure in chart vocabulary. The synth-tool-determined cliff is opaque to chart authors; a chart-level budget makes the failure observable at the chart layer per INV-S-HDL-5. The lint rule lands as `SCXML-LINT-C-2` (proposed; landing requires a SOS-01 §15 amendment).

- **PCDN-SOS-08-C-005 — Multi-target encoding override.** Should chart-side annotation control state encoding (one-hot for FPGA, binary for ASIC), or should the codegen tool's `--target=fpga|asic` flag override the chart annotation? **Recommendation**: chart annotation wins by default (the chart author knows the design's encoding intent); `--target=*` is a hint that the emitter consults only for unannotated regions. This preserves chart-author intent across builds and matches §5.1's per-region override mechanism.

- **PCDN-SOS-08-C-006 — Document-order priority lint rule.** Should the emitter emit a lint warning (`SCXML-LINT-C-1`) when two transitions in the same source state could simultaneously be true under the chart's bounded reachability — surfacing the priority dependence to the chart author? **Recommendation**: yes, lint warning. Document-order priority is invisible at SCXML's surface (no priority numbers); chart authors who reorder transitions for legibility risk silently inverting the priority. The lint warning makes the priority dependence explicit. Lands as `SCXML-LINT-C-1` (proposed; landing requires a SOS-01 §15 amendment).

## 15. Change log

### 2026-05-23 — Initial draft (Ira)

- Authored `SOS-08-C-CONCEPTS.md` as the L2 chart → FSM emission sub-phase concept doc under the SOS-08 umbrella.
- §3 glossary defines: region FSM, transition mux, guard expression, event ingress / egress port, datamodel signal, clock annotation, reset state, verified-strip mode, cooperative completion.
- §4 source-of-truth map: per-region emission contract, encoding override, reset-state default, guard-depth budget, verified-strip × multi-clock interaction; all five owned here. L0 / L1 surfaces, ECMAScript subset, event vocabulary cited not redefined.
- §5 frozen decisions: one-hot encoding default (mirrors SOS-08 PCDN-002); document-order priority discipline for transition muxes; SOS-01 §5.1 ECMAScript subset compilation rules; datamodel signal typing; verified-strip opt-in flag (mirrors SOS-08 PCDN-008); reset-state default; cooperative-only emission (mirrors SOS-08 §5.2 / SOS-08-H / INV-S-HDL-4).
- §6 emission algorithm: ten-step walk from SCXML parse to chart-top wrapper emission. Includes worked-example sketch (§6.11).
- §7 cross-emission invariants INV-S-HDL-C-1 through 5: deterministic emission; per-region observability; cross-domain transition enforcement; guard expression synthesizability; cooperative completion.
- §10 reconciliation against SOS-08-A (L0 consumed via L1, not directly), SOS-08-B (L1 instances are the emission target), SOS-01 §5.1 / §5.3 (ECMAScript subset + event vocabulary), SOS-12 (recursive dispatch composes at L2), SOS-13 (verified-strip cross-target consistency), INV-SOS-G (HDL analog).
- §14 6 PCDNs raised: per-region clock-domain default; verified-strip × multi-clock interaction; reset-state default; guard-depth budget; multi-target encoding override; document-order priority lint rule.

Status: 🟡 **drafted**, awaiting PCDN walkthrough.

### 2026-05-23 — Ratified after PCDN walkthrough (Ira)

All six PCDNs from §14 resolved with recommendations accepted.

- **PCDN-SOS-08-C-001 → RESOLVED**: per-region clock-domain default is **inherit-from-parent**, root defaulting to `main`. Minimises chart-author annotation burden for the single-domain common case; cross-domain transitions surface exactly at the `<region clock="...">` boundary.
- **PCDN-SOS-08-C-002 → RESOLVED**: `--verified-strip` interaction with multi-clock is **retain_synchronizers**. MTBF claims are independent of chart reachability; stripping synchronizers under reachability proofs would silently re-create CDC hazards when downstream code changes re-enable the transition.
- **PCDN-SOS-08-C-003 → RESOLVED**: reset-state default is the SCXML `<initial>` state; per-region `<reset state="..."/>` annotation MAY override (for warm-reset use cases where `<initial>` is a cold-boot bootstrap state).
- **PCDN-SOS-08-C-004 → RESOLVED**: emitter publishes a guard-condition combinational-depth budget (default 8 chained operators); `SCXML-LINT-C-2` enforces at chart-compile time; deeper guards rejected with chart-vocabulary failure message per INV-S-HDL-5. Lint rule lands as a SOS-01 §15 amendment co-landing with SOS-08-C implementation.
- **PCDN-SOS-08-C-005 → RESOLVED**: multi-target encoding override — chart annotation wins by default; `--target=fpga|asic` is a hint the emitter consults only for unannotated regions. Preserves chart-author intent across builds.
- **PCDN-SOS-08-C-006 → RESOLVED**: document-order priority lint rule `SCXML-LINT-C-1` emits a warning when two transitions in the same source state could simultaneously be true under bounded reachability. Surfaces the priority dependence to chart authors who reorder for legibility. Lands as a SOS-01 §15 amendment co-landing with SOS-08-C implementation.

**§5 / INV amendments**:
- §5 frozen-decisions extended with the six resolutions above by reference.
- INV-S-HDL-C-3 (cross-domain transition enforcement) wording extended: "every cross-domain transition retains its `sos_synchronizer` / `sos_message_channel` instance regardless of `--verified-strip` reachability (PCDN-C-002)".
- INV-S-HDL-C-4 (guard expression synthesizability) wording extended: "guard expressions are bounded at default depth 8 combinational operators (PCDN-C-004); `SCXML-LINT-C-2` enforces; chart-compile-time rejection with chart-vocabulary message per INV-S-HDL-5".

**Status**: 🟢 **ratified**. Implementation of the chart→FSM emission path in `tools/sos-codegen/` is now unblocked. SOS-08-D / SOS-08-E / SOS-08-F (vector emission) and SOS-08-G (waveform annotation) had cited SOS-08-C as the FSM emission source-of-truth; that surface is now frozen.

### 2026-05-23 — Impl wave-2 PCDN amendments (Ira)

Implementation wave-2 (hdl_common + VHDL/SV walker parallel-region + cross-domain support) raised 13 sub-PCDNs against the wave-1-ratified surface. Eight were resolved by the operator at walkthrough; five were ratified at their agent-default implementation. Wave-2 sub-PCDNs cover region naming convention, dialect signedness ports, chart-top wrapper shape, clock annotation grammar, guard identifier resolution, cross-domain reset distribution, deferred observability ports, deprecation shim retention, plus five agent-default ratifications. None of the wave-1 §5 frozen-decision rows are mutated; §6 + INV-S-HDL-C-* receive load-bearing wording extensions.

**User-resolved sub-PCDNs**:

- **PCDN-SOS-08-C-wave2-region-naming → RESOLVED**: per-region module file + module name convention is `<chart>_region_<name>_fsm.{vhd,sv}` with module/entity name `<chart>_region_<name>_fsm`. Extends the wave-1 single-region `<chart>_fsm` convention to parallel regions. Cross-dialect equivalence preserved (same module name in both VHDL and SV outputs). SOS-08-D codegen reads this convention when emitting per-region cocotb harnesses.
- **PCDN-SOS-08-C-wave2-vhdl-int-form → RESOLVED**: VHDL port form for `int` (32-bit) datamodel signals is `signed(31 downto 0)` from `ieee.numeric_std`. Cross-dialect: SV uses `logic signed [31:0]`. Both `numeric_std` and SV signed have direct arithmetic without casts; ports stay `signed(...)` (no `std_logic_vector` boundary conversion needed at the chart-top wrapper layer).
- **PCDN-SOS-08-C-wave2-wrapper-shape → RESOLVED**: `emit_chart_top_wrapper`'s `region_modules` shape ratified as `{name, module, clock_domain, datamodel_signals, state_width}` (the richer wave-2 walker shape). Helper reshaped to match; old `{name, clock, reset, ports}` shape retained as a `DeprecationWarning`-emitting alias for backwards compatibility with any in-flight wave-1 caller. VHDL walker call site updated; SV walker stays on local `_render_chart_top_local` until wave-3 refactor (parallel agent landing the code edit).
- **PCDN-SOS-08-C-wave2-clock-annotation → RESOLVED**: cross-domain clock annotation grammar is the **element form** `<sos:region clock="clk_x"/>` as a child of `<state>` (the state being annotated). Uses `xmlns:sos="http://softoboros.com/scxml-extensions/v1"` per SOS-01 §15 ratification (2026-05-23). Region annotation is a structural element, not an attribute, to allow forward-compatible nested annotations (timeouts, priority hints, etc.) without re-amending §6.7's annotation grammar each time.
- **PCDN-SOS-08-C-wave2-guard-idents → RESOLVED**: guard identifier-resolution convention: chart-id `<name>` is pre-rewritten by the walker to `data_<name>`; `hdl_common.emit_guard_expr` appends `_q` suffix; final register name is `data_<name>_q`. Walker owns the chart-to-register name mapping; helper owns the register suffix. Clear separation; both walkers honor the same final form so cross-dialect equivalence holds at the identifier-string level.
- **PCDN-SOS-08-C-wave2-reset-cdc → RESOLVED**: cross-domain reset distribution at the chart-top wrapper is the **caller's responsibility**. Wrapper exposes per-domain `rst_<dom>` ports; caller (chart instantiator) ensures each reset is properly synchronized to its respective clock domain. Smaller wrapper surface; aligns with the wave-1 "chart-top boundary is the user's wiring" convention. No `sos_reset_sync` instance is emitted inside the wrapper; if the user's instantiation context lacks per-domain reset synchronization, the user adds it externally (the audit file `cdc-audit.json` does NOT cover reset signals, only data-bearing transitions).
- **PCDN-SOS-08-C-wave2-transition-obs-deferred → RESOLVED**: `transition_observable` port emission for INV-S-HDL-C-2 full coverage is DEFERRED to wave-3. Current `current_state` (`state_observable`) observability satisfies the load-bearing observability requirement; `transition_observable` is needed by SOS-08-G waveform annotation but not by SOS-08-C functional emission. Added when SOS-08-G integration lands; INV-S-HDL-C-2 carries a "partial coverage" annotation in the interim (see invariant restatement below).
- **PCDN-SOS-08-C-wave2-mdtype-shim → RESOLVED**: `map_datamodel_type` 1-arg deprecation shim retained through wave-3 with `DeprecationWarning`. No current caller uses the 1-arg form; shim is dead code with explicit deprecation signal. Removal lands when wave-3 ratification confirms no external callers exist (low-cost defensive retention; the cost of a stray import-time crash on a wave-1 consumer outweighs the trivial maintenance cost of a no-op shim).

**Agent-default ratifications**:

1. **`compute_guard_depth` metric**: AST-based depth counting (`BoolOp` contributes N-1 to path; `Compare` contributes `len(ops)`; `UnaryOp`/`BinOp`/`Call` contribute 1; literals contribute 0). Matches `SCXML-LINT-C-2` sibling's convention. Regex fallback over `_GUARD_OPERATORS` for non-Python-parseable inputs (callers that already lowered to `&&`/`||` dialect form). Within `emit_guard_expr`, the depth-budget gate calls `compute_guard_depth` so the metric is internally consistent between lint and emit.
2. **`emit_signal_decl` SV double-`logic` heuristic**: `lstrip().startswith(("logic", "bit", "reg"))` check avoids emitting `logic logic [31:0] s;` when caller pre-renders `signal_type="logic [31:0]"`. SV-only heuristic; kept as a defensive cleanup. Wave-3 may formalize as a separate `emit_signal_decl_sv_typed` if drift emerges between callers that pre-render type prefixes and callers that don't.
3. **`HdlPort.kind` / `signed` fields retained but unconsumed**: kept on the dataclass for sibling-walker compatibility; `emit_port_decl` uses `width_expr` → `dialect_hint` → auto-render from `width`. If a sibling walker later needs `kind="signed"` to flip auto-render to `signed(W-1 downto 0)` / `logic signed [W-1:0]`, that requires an explicit §15 amendment + code path change; the field's current presence is dormant capacity, not a contract surface.
4. **Cross-domain synchronizer over-emission**: SV walker emits one `sos_synchronizer` per (signal × ordered region pair) where the signal is referenced on both sides; conservative (over-emits when chart authors only read in one direction). Safe per PCDN-C-002 (synchronizers are retained regardless of reachability); wave-3 will tighten once event-routing semantics land and the directional read/write classification becomes part of the walker's static-analysis output.
5. **`GuardNotSupportedError` / `ParallelNotSupportedError` retained as no-op subclasses**: wave-1 reject paths are no longer reached at wave-2 (both constructs now accepted); the symbols are kept as `HdlEmitError` subclasses so downstream importers don't break. Wave-3 may remove if no consumers surface; current cost is two empty-body class definitions.

**§-amendments to record by reference**:

- §6.1 (region tree construction) extended: parallel-child iteration semantics — each `<state>` child of `<parallel>` is one region (matches both walkers' wave-2 impl after the inline parallel-child-iteration fix in the SV walker).
- §6.7 (clock-domain inheritance) extended: `<sos:region clock="..."/>` element annotation under the `sos:` namespace ratified as the per-region clock-domain declaration grammar (replaces the wave-1 informative `<region clock="..."/>` attribute-form sketch; the element form is the normative grammar going forward).
- §6.10 (chart-top wrapper) extended: `region_modules` shape ratified as `{name, module, clock_domain, datamodel_signals, state_width}`; per-region cross-domain reset distribution is the caller's responsibility (wrapper does NOT internalize `sos_reset_sync` instances).
- INV-S-HDL-C-1 (deterministic emission) restated: both walkers produce byte-equivalent state-constant ordering for the same chart (cross-dialect equivalence test landed alongside this amendment as part of the integration test suite).
- INV-S-HDL-C-2 (per-region observability) partial coverage: `current_state` (`state_observable`) emitted at wave-2; `transition_observable` deferred to wave-3 per PCDN-SOS-08-C-wave2-transition-obs-deferred. Full coverage restored when SOS-08-G integration lands.
- INV-S-HDL-C-3 (cross-domain transition enforcement) reinforced: `sos_synchronizer` instantiation in the chart-top wrapper per PCDN-C-002; static analysis detects writer × reader × clock-domain triples and emits one synchronizer per cross-domain edge (SV walker over-emits conservatively per agent-default ratification #4 above).

**Status**: 🟢 **ratified (continuing)** — impl wave-2 PCDN amendments fold the guard / parallel / chart-top wrapper / cross-domain synchronizer design choices into the SOS-08-C normative surface. The wave-2 emit path now supports guards (with depth budget enforced at both lint and emit), parallel regions (one module per `<parallel>` child + chart-top wrapper), cross-domain synchronizers (PCDN-C-002), and port-width-from-signal-width polish. Wave-3 candidates: event ingress/egress via `sos_message_channel`, ECMAScript subset → HDL action lowering beyond `<assign>`, `<script>` bodies, `transition_observable` for SOS-08-G integration.
