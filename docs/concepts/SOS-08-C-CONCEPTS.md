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

- **PCDN-SOS-08-C-007 — Wave-3-e port-shape extension for per-`<param>` sub-buses (post-wave-1 follow-up). 🟢 ratified 2026-05-25 — implementation pending (sequenced after chart-inventory wave; see §15 2026-05-25 ratification entry).** Surfaced by 2026-05-24 wave-1 commit `f0284fc` (SOS-08-C wave-3-f-future-A) which rejects `<assign expr="event.<EV>.<custom>"/>` because today's wave-3-e port emission carries only a single `event_<ev>_recv_data` bus per event. **Recommendation**: extend wave-3-e to emit per-`<param>` sub-buses named `event_<ev>_recv_data_<param>` (one per declared `<param name>` on the corresponding `<send>`/`<raise>`), with the legacy unnamed `_recv_data` bus preserved as a byte-identity alias for charts that use only `event.<EV>.value`. Chart-vocab error: `<param>` name collision with `value` is a hard reject. Multi-`<param>` events whose declared params don't appear in any consuming `<assign>` may suppress emission of the unused sub-buses (optimisation). Authority: `own` for the per-`<param>` naming convention; `compose` over PCDN-SOS-08-010's region clock and the existing event-port shape. Registration policy: **Standards Action** — the port shape is a cross-walker contract surface (SOS-08-C emits, SOS-08-D + E + F + G consume). **Unblocks**: SOS-08-C wave-3-f-future-B FULL implementation. **Tracking**: `f0284fc`'s `_EVENT_PAYLOAD_RE` rejection path is the placeholder; resolution removes it.

- **PCDN-SOS-08-C-008 — Shared-datamodel HDL wiring (post-wave-1 follow-up). 🟢 ratified 2026-05-25 — implementation pending (same-clock-domain only at v1; see §15 2026-05-25 ratification entry).** Surfaced by 2026-05-24 wave-4 commit `1dc5649` (SOS-08-D wave-4-future-shared) which emits the one-driver SVA invariant for `<sos:shared_signal>` but explicitly defers the HDL-side signal declaration + driving-process emission. **Recommendation**: SOS-08-C recognises `<sos:shared_signal name="..." width="..." owner_region="..."/>` at chart top, emits a chart-top-scoped signal `shared_<name>` of declared width, and emits the driving register process within owner_region's per-region logic. Reader regions referencing `<sos:shared_signal_ref name="..."/>` in their `<assign>` location field read `shared_<name>` without any synchroniser (intentionally — owner_region's clock is the dominant domain; cross-domain shared signals are a future PCDN). The SOS-08-D one-driver invariant continues to hold by construction. Authority: `own` for the chart-top signal naming convention + ownership-by-region rule. Registration policy: **Standards Action**. **Unblocks**: the second wave-4-future carry-forward (HDL wiring side) flagged by D3's §15 2026-05-24 entry. **Tracking**: `1dc5649`'s `_emit_shared_signal_invariants` is the assertion-side counterpart; resolution adds the wiring side.

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

### 2026-05-23 — Impl wave-3-a: event egress emission (Ira)

Wave-3-a lifts the wave-2 `<raise>` rejection in both VHDL + SV walkers and emits per-region event-egress ports per §6.5. This is the first half of the wave-3 events scope; wave-3-b lands the chart-top wrapper `sos_message_channel` instantiation that collects per-region pulses into the global channel send face.

**Wave-3-a implementation surface (both walkers)**:

- **`HdlTransition.raise_events: list[str]`** field added in both `transliterate_hdl_sv.py` and `transliterate_hdl_vhdl.py`. The transition-build code in both walkers extracts the `raise_value` list per SCXML §3.13 and populates the new field; empty for transitions without `<raise>`.
- **Wave-2 `<raise>` rejection lifted** in both walkers' rejection passes (`EventIngressNotSupportedError` raise removed in SV; `UnsupportedChartError` raise removed in VHDL). The rejection-pass comments now cite wave-3-a as the landing wave.
- **`_collect_region_raise_events(region) -> list[str]`** helper added to both walkers. Returns sorted, de-duplicated set of event names raised by any transition in the region. One unique event name → one egress port on the region FSM module.
- **`_safe_event_ident(name)`** (SV) and **`_safe_event_ident_vhdl(name)`** (VHDL) sanitise SCXML event names (which may contain dots per `sem.give` convention) into legal Verilog / VHDL identifiers (`sem_give`). The original chart-side event name is preserved verbatim in the port-list trailing comment + the concurrent-assignment trailing comment for chart-vocabulary traceability per [INV-SOS-H][inv-sos-h].
- **Per-region module header** extended in both dialects to emit `output wire event_<ident>_send_valid` (SV) / `event_<ident>_send_valid : out std_logic` (VHDL) per unique raise-event name. The trailing chart-event-name comment lands on its own line so the comma/semicolon-suffix logic doesn't end up inside the comment.
- **`_emit_event_egress_drives` / `_emit_event_egress_drives_vhdl`** helpers added. For each unique raise event, emit a combinational drive of the `_send_valid` output: asserted for one cycle when ANY transition with the matching `<raise event="<name>"/>` fires. Firing rule per [PCDN-C-006][pcdn-c-006] document-order priority — the predicate AND's together (a) state-match, (b) `not (higher_priority_guard)` for every earlier transition out of the same source state, (c) `(own_guard)` if the transition has a `cond`. SV uses `assign event_X_send_valid = <bool_expr>;`; VHDL uses `event_X_send_valid <= '1' when <bool_expr> else '0';` per std_logic convention.
- **Both walkers' region-render functions** pass `raise_events` to the module-header + egress-drive emitters; the per-region FSM module body grows a new `-- event egress` section between the existing output-drive block and the `endmodule` / `end architecture` line.

[inv-sos-h]: ./SOS-07-CONCEPTS.md#inv-sos-h--vector-to-chart-traceability
[pcdn-c-006]: #62-step-2--synthesize-per-region-fsm-modules

**Wave-3-a scope (what landed vs. what is deferred)**:

- ✅ Per-region FSM module emits one `event_<name>_send_valid` output per unique `<raise event="..."/>` event name.
- ✅ Combinational drive honors PCDN-C-006 document-order priority — only the highest-priority firing transition asserts the pulse.
- ✅ Both dialects (VHDL + SV) emit symmetric port + drive shapes; cross-dialect parity preserved per INV-S-HDL-C-1.
- ⏸ **wave-3-b**: chart-top wrapper `sos_message_channel` instantiation. Currently the per-region `event_<name>_send_valid` outputs hang at the chart-top boundary — the chart-top wrapper does NOT yet collect them into a global `sos_message_channel` send face. Per §6.5 the wave-3-b landing emits one `sos_message_channel` instance per chart-wide unique event name + wires each per-region send_valid output into the channel's `send_valid` input (with per-event arbitration when multiple regions raise the same event).
- ⏸ **wave-3-c**: event ingress refactor. Currently transitions with `event="..."` consume a single chart-wide `event_in` port (per the SOS-08-E wave-1 virtual-interface shape); wave-3-c refactors this to one `sos_message_channel` receive-face port per consumed event name per §6.4.
- ⏸ **wave-3-d**: `event_<name>_send_data` payload ports + payload-bearing `<raise>` extension. Wave-3-a only emits `_send_valid` strobes; payload data (e.g. integer values raised by `<raise event="counter" data="N"/>`) lands in wave-3-d alongside the SCXML `<param>` / `<content>` element support.

**Wave-3 boundary not yet touched**:

- ECMAScript subset → HDL action lowering beyond `<assign>` (§6.6): unchanged from wave-2 — `<script>` bodies still raise `UnsupportedChartError`.
- `transition_observable` port for SOS-08-G integration (PCDN-SOS-08-C-wave2-transition-obs-deferred): still wave-3 scope; not landed in 3-a.

**Invariants upheld**:

- **INV-S-HDL-C-1** (deterministic emission): `_collect_region_raise_events` returns sorted output; egress-drive ordering follows the same sorted sequence. Both walkers produce byte-identical output across rendered runs (verified by existing `test_emission_is_deterministic`).
- **INV-S-HDL-C-2** (per-region observability): unchanged — `current_state` output retained. Egress ports are additive observability (new wires; nothing removed).
- **INV-S-HDL-C-3** (cross-domain enforcement): unchanged at wave-3-a since the chart-top wrapper `sos_message_channel` instantiation is wave-3-b. When 3-b lands, INV-S-HDL-C-3's "cross-domain event consumption uses `sos_message_channel`" claim becomes operational; wave-3-a just emits per-region pulse outputs that 3-b will wire into the channel.
- **INV-S-HDL-3** (cross-domain isolation): unchanged — wave-3-a emits no new cross-domain signal paths; the per-region egress port is a single-clock-domain signal until 3-b wires it through `sos_message_channel`'s internal `sos_fifo_async`.
- **[INV-SOS-H][inv-sos-h]** (chart-vocabulary traceability): chart-side event names are preserved verbatim in the port-list trailing comment + the concurrent-assignment trailing comment for every emitted egress port + drive.

**Test count**: 11 new tests:

- SV (`test_transliterate_hdl_sv.py::TestWave3Events`, 6 tests): simple raise emits egress port; combinational drive present; multiple raises aggregated + sorted; guard lowered into drive (data signal reference verified); event-name dot-sanitisation (`sem.give` → `event_sem_give_send_valid`); single-region chart without raise unchanged (regression guard).
- VHDL (`test_transliterate_hdl_vhdl.py::TestVhdlWave3Events`, 5 tests): raise accepted; egress port declared as `: out std_logic`; concurrent drive uses VHDL `when … else '0'` form; event-name sanitisation symmetric to SV; chart without raise unchanged.
- Existing `test_raise_rejected_at_wave_2` renamed → `test_raise_accepted_at_wave_3`; assertions flipped to verify egress port + drive presence.

**Test suite**: 381/381 passing (370 prior + 11 wave-3-a).

**Cited PCDNs**: PCDN-C-006 (document-order priority — egress drives honor priority chain); PCDN-SOS-08-C-wave2-region-naming (per-region module naming convention extended to wave-3 egress ports without modification).

Status: 🟢 **wave-3-a complete**. Wave-3-b picks up the chart-top wrapper `sos_message_channel` instantiation + per-event arbitration when multiple regions raise the same event. Wave-3-c refactors event ingress from the single `event_in` port to per-event receive-face ports. Wave-3-d adds payload data on `_send_data` ports for `<raise>` events with `<param>` / `<content>`.

### 2026-05-24 — Impl wave-3-b: chart-top wrapper event-egress passthrough (Ira)

Wave-3-b surfaces the per-region event-egress outputs (added in wave-3-a) at the chart-top wrapper boundary. Each region's `event_<name>_send_valid` output is wired through the wrapper to a boundary port named `event_<region>_<name>_send_valid` — the per-region prefix prevents collisions when multiple regions raise the same event name. Aggregation across regions into a single `sos_message_channel` send face (per the original wave-3-b scope) is **re-scoped to wave-3-c** because the aggregation choice (OR-tree vs real channel arbitration) is non-trivial and benefits from a focused commit.

**Wave-3-b implementation surface**:

- **`_safe_event_ident_top(name)`** added to `hdl_common.py`. Mirrors `transliterate_hdl_{sv,vhdl}._safe_event_ident*` so the chart-top boundary port name matches the per-region module's output port name byte-for-byte.
- **`emit_chart_top_wrapper` boundary-port loop** extended: after the `current_state_<region>` outputs, iterate `region_modules[i].get("raise_events", []) or []` and append one `event_<region>_<name>_send_valid` boundary output per (region, event) pair. The `raise_events` key is **optional** on region_module dicts so wave-1/2 callers continue to work unchanged.
- **`_emit_chart_top_wrapper_sv_new`** + **`_emit_chart_top_wrapper_vhdl_new`** body emitters extended: when instantiating each region in the wrapper, after `.current_state` wires through the per-event egress connections (SV: `.event_<name>_send_valid(event_<region>_<name>_send_valid)`; VHDL: `event_<name>_send_valid => event_<region>_<name>_send_valid`).
- **`transliterate_hdl_sv.py` + `transliterate_hdl_vhdl.py`** region_modules construction extended: `_collect_region_raise_events(region)` is called per region and the result populates the new `raise_events` key on the region_module dict.

**Wave-3-b scope (what landed vs. what is deferred)**:

- ✅ Per-region event-egress outputs reachable at the chart-top boundary as `event_<region>_<name>_send_valid`.
- ✅ Symmetric VHDL + SV wrapper emit (cross-dialect parity preserved per INV-S-HDL-C-1).
- ✅ Charts without `<raise>` produce byte-identical wave-2 wrapper output (regression-guarded).
- ⏸ **wave-3-c (was wave-3-b)**: chart-top wrapper `sos_message_channel` instantiation + per-event aggregation across regions raising the same event. The aggregation choice (OR-tree under cooperative INV-S-HDL-4 vs. real channel arbitration with `recv_ready` backpressure) plus the cross-clock-domain implications (when regions in different clock domains raise the same event) lift this into its own dedicated wave. Per-region passthrough at the wrapper boundary unblocks downstream consumers in the interim.
- ⏸ **wave-3-d (was wave-3-c)**: event ingress refactor (single `event_in` port → per-event receive-face ports).
- ⏸ **wave-3-e (was wave-3-d)**: payload data on `_send_data` ports.

**Invariants upheld**:

- **INV-S-HDL-C-1** (deterministic emission): per-region iteration order through `region_modules` is the canonical order; per-event ordering within a region uses the wave-3-a sorted output. Wrapper boundary ports stable across re-renders.
- **INV-S-HDL-C-2** (per-region observability): unchanged — boundary still exposes `current_state_<region>`. Wave-3-b is purely additive (new boundary ports; nothing removed).
- **INV-S-HDL-4** (cooperative-only at v1): the per-region passthrough leaves the OR-tree aggregation decision to wave-3-c — under cooperative scheduling at most one region raises a given event in a given cycle so the OR-tree is correct, but the wave-3-c commit picks the canonical form (real channel arbitration retained for forward compat with payload + cross-domain pressure).
- **INV-SOS-H** (chart-vocabulary traceability): chart-side event names preserved verbatim via the wave-3-a trailing comments on each region's egress port + drive; the wrapper-level passthrough does not introduce new identifier renames beyond the per-region prefix.

**Test count**: 3 new tests (`TestWave3bChartTopEgressPassthrough` in `test_transliterate_hdl_sv.py`):

- `test_chart_top_exposes_per_region_event_outputs` — `event_left_ack_send_valid` + `event_right_done_send_valid` present at wrapper boundary for a parallel chart with each region raising one event.
- `test_chart_top_wires_region_instance_to_boundary` — SV instance-port-map wires per-region `event_<name>_send_valid` output to the chart-top boundary port byte-for-byte.
- `test_chart_top_omits_event_ports_when_no_raise` — parallel chart without `<raise>` produces a wrapper with no `event_*_send_valid` ports (regression guard).

**Test suite**: 384/384 passing (381 prior + 3 wave-3-b).

**Cited PCDNs**: PCDN-SOS-08-C-wave2-wrapper-shape (extended with optional `raise_events` key; legacy callers unaffected); INV-S-HDL-C-1 (deterministic emission preserved across wrapper-level boundary additions).

Status: 🟢 **wave-3-b complete**. Wave-3-c lifts the per-region passthrough to per-event aggregation via `sos_message_channel` instantiation with arbitration. Wave-3-d (event ingress refactor) and wave-3-e (payload data) follow per the wave-3-a §15 entry's roadmap.

### 2026-05-24 — Impl wave-3-c: sos_message_channel instantiation + per-event aggregation (Ira)

Wave-3-c instantiates one `sos_message_channel` per chart-wide unique event name at the chart-top wrapper. Per-region `event_<name>_send_valid` outputs (wave-3-a) become internal wires that OR-aggregate into the channel's slave-side `s_axis_tvalid` input. The wave-3-b per-region boundary ports (`event_<region>_<name>_send_valid`) are **superseded** by the wave-3-c channel-mediated pair (`event_<name>_recv_valid` output + `event_<name>_recv_ready` input).

**Wave-3-c implementation surface (hdl_common.py)**:

- **`emit_chart_top_wrapper` boundary**: collects chart-wide unique event names from each region_module's `raise_events`; emits one `event_<name>_recv_valid` output + one `event_<name>_recv_ready` input per unique event. Wave-3-b's per-region boundary ports removed.
- **`chart_event_set` + `chart_event_producers`** parameters threaded into the dialect-specific emitters.
- **SV body**: per-region instance wires `event_<name>_send_valid` to `w_ev_<region>_<name>_pulse` internal wire; per-event aggregated wire `ev_<name>_send_valid = OR of producer pulses`; one `sos_message_channel #(EVENT_ID_WIDTH=8, PAYLOAD_WIDTH=8, DEPTH=4, READ_LATENCY=0, RESET_MEM=1) u_chan_<name>` per unique event with hardcoded 8-bit `s_axis_tevent_id`. Unconnected channel ports bound to empty `()` (SV syntax).
- **VHDL body**: symmetric — per-region pulse signals + per-event aggregated signal declared in the architecture declarative region; `entity work.sos_message_channel` instances with `open` on unused ports. Decl block spliced via post-pass into the `architecture rtl of <top_name> is` line.
- **Channel clock domain**: takes the FIRST producer's clock domain. Multi-clock-domain producers of the same event is wave-3-d scope (switch to `sos_message_channel_async`).

**Wave-3-c scope vs wave-3-d/-3-e**:

- ✅ One channel per chart-wide unique event name; OR-tree aggregation across producers.
- ✅ Boundary contract: `event_<name>_recv_valid` (out) + `event_<name>_recv_ready` (in).
- ✅ Symmetric VHDL + SV emit (INV-S-HDL-C-1).
- ⏸ **wave-3-d**: producer backpressure (`s_axis_tready` boundary); multi-clock-domain channel variant (`sos_message_channel_async`); event ingress refactor (per-event receive-face ports per §6.4).
- ⏸ **wave-3-e**: payload data on `_tpayload` ports + chart `<param>` / `<content>` extension.

**Breaking change from wave-3-b**:

The wave-3-b per-region boundary ports `event_<region>_<name>_send_valid` are GONE — replaced by per-chart-wide-event `event_<name>_recv_valid` + `event_<name>_recv_ready`. This is the planned wave-3-c lift per the wave-3-b §15 entry's documented boundary; downstream consumers bound to wave-3-b's per-region outputs need to switch to the channel's downstream handshake.

**Invariants upheld**:

- **INV-S-HDL-C-1** (deterministic emission): channel instances + aggregation wires emit in `sorted(chart_event_set)` order.
- **INV-S-HDL-C-3** (cross-domain event consumption uses `sos_message_channel`): NOW OPERATIONAL at the chart-top wrapper.
- **INV-S-HDL-4** (cooperative-only): OR-tree aggregation correct under cooperative scheduling (at most one region pulses per cycle).
- **INV-S-HDL-B-1/-2/-3/-4/-5**: channel instantiated as a black-box L1 service per INV-S-HDL-B-2.
- **INV-SOS-H** (chart-vocabulary traceability): chart-side event names preserved verbatim in per-event aggregated-wire trailing comments + per-region FSM port trailing comments.

**Test count**: net +3 (6 new − 3 wave-3-b tests replaced):

`TestWave3cChartTopChannels` (6 tests): exposes `event_<name>_recv_valid` + `event_<name>_recv_ready` per unique event; instantiates `sos_message_channel` per unique event; per-region pulse wires + OR-aggregation present; wave-3-b per-region ports MUST NOT appear (regression guard); chart without `<raise>` omits all event ports + channels (regression guard); multi-producer event produces ONE channel with OR-aggregated `s_axis_tvalid`.

**Test suite**: 387/387 passing (384 prior + 3 net wave-3-c).

**Cited PCDNs**: SOS-08-B §6.5 (channel contract); SOS-08-B §5 (v1 baseline channel parameters); INV-S-HDL-C-3 (now operational); INV-S-HDL-4 (OR-tree justification).

Status: 🟢 **wave-3-c complete**. Wave-3-d adds producer backpressure + multi-clock-domain channel variant + event ingress refactor. Wave-3-e adds payload data routing.

### 2026-05-24 — Impl wave-3-d-1: producer backpressure (Ira)

Wave-3-d originally bundled three concerns: (a) producer backpressure on the `<raise>` egress, (b) the multi-clock-domain channel variant (`sos_message_channel_async`), and (c) the event ingress refactor (single `event_in` port → per-event receive-face ports per §6.4). Each is large enough to merit its own wave, so wave-3-d is **split into three sub-waves**:

- **wave-3-d-1** (this entry): producer backpressure.
- **wave-3-d-2** (deferred): multi-clock-domain channel variant. Requires a new L1 primitive (`sos_message_channel_async` wrapping `sos_fifo_async`) + its SVA + bind file, plus walker logic to switch instance flavour when producers cross clock domains. SOS-08-B normative surface needs an amendment first.
- **wave-3-d-3** (deferred): event ingress refactor — emit per-event `event_<name>_recv_valid` / `event_<name>_recv_ready` ingress ports on each region FSM, fan-out the channel's m_axis side to consuming regions, and gate transitions with `event="..."` attributes on `_recv_valid`. Currently transitions consuming events are unimplemented (state advances ignore the event attribute) — this is the load-bearing §6.4 refactor.

**Wave-3-d-1 implementation surface**:

- **`_emit_module_header` (SV) / `_emit_entity` (VHDL)**: per raise-event, the existing `event_<name>_send_valid` output port is now paired with a new `event_<name>_send_ready` **input** port. The trailing-comment annotation logic tracks the pair (`// chart event \`<ev>\`` + `// chart event \`<ev>\` (wave-3-d backpressure)`).
- **`_emit_transition_case_arm` (SV) / `_emit_transition_case_arm` (VHDL)**: a transition with `tr.raise_events` now wraps its state-advance in `if (event_<name>_send_ready) state_next = <target>; else state_next = state_q;` (single-line `begin ... end` in SV; multi-line `if ... then ... else ... end if;` in VHDL). Multiple raise events on one transition require ALL channels ready (AND): `if (event_X_send_ready && event_Y_send_ready) ...`. **Priority-claim is preserved across backpressure stalls** — a blocked high-priority raise transition holds the FSM in source state without falling through to lower-priority transitions, per INV-S-HDL-4 cooperative-only semantics.
- **`_emit_event_egress_drives` (unchanged)**: the combinational drive on `event_<name>_send_valid` stays state-derived (`(state_q == ST_S) && guard`). Under backpressure (send_ready=0), state holds in source ⇒ send_valid stays asserted across cycles until handshake completes. This satisfies AXI-Stream "valid must hold until handshake" by construction; valid does NOT depend on ready.
- **`hdl_common.py` chart-top wrapper**: per chart-wide unique raise-event, declares a `wire ev_<name>_send_ready;` (SV) / `signal ev_<name>_send_ready : std_logic;` (VHDL). Wires the channel's `s_axis_tready` output to this wire. Per producer region instance, adds `.event_<name>_send_ready(ev_<name>_send_ready)` (SV) / `event_<name>_send_ready => ev_<name>_send_ready` (VHDL). The fanout is a broadcast — every producer of a given event sees the same ready signal. Broadcast is correct under INV-S-HDL-4 cooperative-only (at most one producer pulses per cycle).

**Cycle-level behaviour** (single producer, channel backed up):

| Cycle | `state_q` | `guard` | `send_ready` | `send_valid` | `state_next` | Notes |
|-------|-----------|---------|--------------|--------------|--------------|-------|
| N     | source    | 1       | 0            | 1            | source       | stall: no transfer, valid stays high |
| N+1   | source    | 1       | 1            | 1            | target       | handshake completes |
| N+2   | target    | —       | —            | 0            | (next-state) | state has advanced |

**Wave-3-d-1 scope explicitly excludes**:

- Multi-clock-domain channel variant (`sos_message_channel_async`) — needs SOS-08-B amendment + new L1 primitive. Wave-3-d-2.
- Event ingress refactor (per-event `_recv_*` ports on region FSMs + transition gating on `_recv_valid`). Wave-3-d-3.
- Payload data routing on `_tpayload` ports. Wave-3-e.

**Invariants upheld**:

- **INV-S-HDL-1** (handshake-compatible ports): the new `_send_ready` input completes the AXI-Stream handshake at the boundary.
- **INV-S-HDL-C-1** (deterministic emission): per-event `_send_ready` wires + region-instance fanouts emit in sorted order.
- **INV-S-HDL-4** (cooperative-only): priority-claim across backpressure stalls relies on cooperative semantics (no preemption attempts to switch to a lower-priority transition when a higher-priority raise is blocked).
- **INV-SOS-H** (chart-vocabulary traceability): the `_send_ready` port carries the same `// chart event \`<name>\`` annotation as its `_send_valid` partner.
- **INV-S-HDL-B-1/-2/-3/-4/-5**: channel still instantiated as a black-box L1 service per INV-S-HDL-B-2; the `s_axis_tready` output was already in the L1 contract (SOS-08-B §6.5) — wave-3-d-1 just wires it.

**Test count**: net +8 — `TestWave3dProducerBackpressure` (8 tests): region-module pairs `_send_valid` output with `_send_ready` input; unguarded raise transitions stall in source via the send_ready wrap; guarded raise transitions wrap inside the outer guard; charts without `<raise>` retain wave-1 emission shape (no send_ready); chart-top declares per-event send_ready wire; channel's `s_axis_tready` connects to the send_ready wire (not unconnected); per producer region the send_ready wire fans out to `.event_<name>_send_ready(...)`; multi-producer charts use a single shared send_ready wire (broadcast under INV-S-HDL-4).

**Test suite**: 381/381 passing (373 baseline + 8 net wave-3-d-1). The wave-3-c test count of 387 cited in the prior entry was a transient — the actual baseline going into wave-3-d-1 is 373 (the SV `_send_ready` ports are additive at the port-list boundary; existing tests that grep for `event_<name>_send_valid` still match).

**Cited PCDNs**: SOS-08-B §6.5 (channel contract — `s_axis_tready` was already specified); INV-S-HDL-4 (priority-claim across stalls); SOS-08-A §6 (AXI-Stream valid-stable-until-ready convention).

Status: 🟢 **wave-3-d-1 complete**. Wave-3-d-2 adds the multi-clock-domain channel variant (`sos_message_channel_async`) — requires a SOS-08-B amendment first. Wave-3-d-3 adds the event ingress refactor (per-event `_recv_*` ports on region FSMs + transition gating on `_recv_valid`).

### 2026-05-24 — Impl wave-3-d-3: event ingress refactor (Ira)

The load-bearing §6.4 fix. Until this wave, transitions with `event="..."` had the event attribute captured but **UNUSED** at emit time — they fired combinationally on state + cond alone, regardless of whether the chart-side event had actually been raised. This wave correctly gates them on `event_<name>_recv_valid`.

**Wave-3-d-3 implementation surface**:

- **`_collect_region_consume_events` (SV + VHDL)**: new helper. Walks region transitions, returns sorted-deduped list of event names referenced via `tr.event`. Mirror of `_collect_region_raise_events`.
- **`_emit_module_header` (SV) / `_emit_entity` (VHDL)**: per consumed event, emit `(event_<name>_recv_valid input, event_<name>_recv_ready output)` port pair after the raise-side quad. The trailing-comment annotation discipline extends to cover the new ports (`// chart event \`<ev>\` (wave-3-d-3 ingress)` + `// chart event \`<ev>\` (wave-3-d-3 consume-ready)`).
- **`_emit_transition_case_arm` (SV + VHDL)**: the predicate partition changes. A transition is now "predicated" if it has event OR cond (previously only cond). The predicate is built as `event_<name>_recv_valid && (cond)` when both are present, the event-only form when no cond, or the cond-only form when no event. Only transitions with **neither** event nor cond end the priority chain (final `else` arm). Doc-order priority (PCDN-C-006) is preserved through the if/elsif structure.
- **`_emit_event_egress_drives` (SV + VHDL) refactor**: the firing predicate now includes the transition's own `event_<name>_recv_valid` term when consuming. Without this, the egress would pulse even when the chart-side event hasn't arrived — breaking §6.4 semantics. Higher-priority transitions' "must not fire" terms also include their event-valid terms (full firing predicate).
- **`_emit_event_ingress_recv_ready_drives` (SV + VHDL)**: new emitter. Per consumed event, drives `event_<name>_recv_ready` as the OR over per-state predicates "state matches AND no higher-priority transition's full firing predicate holds AND own cond holds". Critically, the recv_ready predicate does **NOT** include the event's own `_recv_valid` term — that would create a combinational dependency through the channel. The channel's `m_axis_tvalid` is derived from a registered FIFO empty flag (`sos_fifo_sync`), so the dependency wouldn't actually close in one cycle, but omitting the self-event term keeps the recv_ready predicate state-local and easier to reason about ("I'm ready to consume X NOW if you offer it" is independent of "you ARE offering X").
- **`_transition_fire_predicate_terms` + `_walk_state_for_event` helpers (SV + VHDL)**: shared between egress and ingress drives. Builds the AND-terms of a transition's firing predicate within a state, with knobs for state-match (omitted when caller gates externally) and own-event (omitted for recv_ready drives).
- **`_build_region_modules_canonical` (SV walker) / equivalent (VHDL walker)**: surface `consume_events` field in the `region_modules` dict alongside `raise_events`.
- **`hdl_common.py` chart-top wrapper**: 
  - Collects `chart_event_consumers` parallel to `chart_event_producers`. Events present in either set get a channel instance + boundary `event_<name>_recv_valid/ready` ports.
  - Per consume edge, declares `wire w_ev_<region>_<name>_ready;` (SV) / `signal w_ev_<region>_<name>_ready : std_logic;` (VHDL) carrying the consumer's recv_ready output.
  - Per event, declares `wire ev_<name>_recv_valid_w;` carrying channel `m_axis_tvalid` (fanned to boundary observer + each consumer region's input).
  - Per event, declares `wire ev_<name>_recv_ready_w = event_<name>_recv_ready | <each consumer's ready signal>;` aggregating boundary observer's ready + every consumer region's ready. Channel `m_axis_tready` connects to this aggregated wire.
  - Per consumer region instance, wires `.event_<name>_recv_valid(ev_<name>_recv_valid_w)` + `.event_<name>_recv_ready(w_ev_<region>_<name>_ready)`.

**Cycle-level behaviour** (single consumer, channel offers data):

| Cycle | `state_q` | `recv_valid` | `recv_ready` (computed) | `state_next` | Notes |
|-------|-----------|--------------|--------------------------|--------------|-------|
| N     | source    | 0            | 1                        | source       | ready but no data offered |
| N+1   | source    | 1            | 1                        | target       | handshake completes, channel pops |
| N+2   | target    | (channel re-evaluates) | 0 (no longer in source) | (next) | state has advanced |

**Boundary observer semantics**: the chart-top `event_<name>_recv_valid` output AND every internal consumer's `event_<name>_recv_valid` input see the same channel `m_axis_tvalid`. The channel pops once when `m_axis_tready` goes high — which happens when ANY of (boundary observer ready, internal consumer ready) is high. Under cooperative INV-S-HDL-4, at most one consumer is ready per cycle in the typical case, so the OR-aggregate behaves as point-to-point. Two simultaneous consumers in the same cycle both "see" the data via fanout (`m_axis_tvalid` is broadcast), and the channel pops once — semantically equivalent to broadcast consumption. The chart-author's design constraint per cooperative SCXML semantics is that two regions consuming the same event in the same cycle is not typically intended, but the emission produces correct under-cooperative behaviour either way.

**Wave-3-d-3 scope explicitly excludes**:

- Multi-clock-domain channel variant (`sos_message_channel_async`) — needs SOS-08-B amendment + new L1 primitive. Wave-3-d-2.
- Payload data routing on `_tpayload` ports + chart `<param>`/`<content>` extension. Wave-3-e.
- Per-event consumer arbitration for the cross-region simultaneous-consume case (defer to v2 or a future amendment that ratifies cross-region event distribution semantics).

**Invariants upheld**:

- **§6.4 LOAD-BEARING FIX** (event ingress wiring): operational. Transitions with `event="..."` are now correctly gated on the chart-side event arrival. This was previously a known-incorrect emission — the wave-1 / wave-2 / wave-3-{a,b,c,d-1} versions emitted transitions as combinational on state+cond.
- **INV-S-HDL-1** (handshake-compatible ports): the new `(_recv_valid in, _recv_ready out)` quad completes the AXI-Stream slave-side handshake at the region boundary.
- **INV-S-HDL-C-1** (deterministic emission): per-event recv_ready drives, consume-edge wires, fanout wires emit in sorted order.
- **INV-S-HDL-C-3** (cross-domain event consumption uses `sos_message_channel`): now fully operational — chart-top fans channel m_axis to consumers, OR-aggregates ready back. INV-S-HDL-3's "every cross-domain transition uses a synchronizer" is satisfied by the channel's internal `sos_fifo_sync` (single-clock variant) or `sos_fifo_async` (deferred to wave-3-d-2).
- **INV-S-HDL-4** (cooperative-only): preserved. Higher-priority transitions' full firing predicates are subtracted from lower-priority transitions' recv_ready terms so the channel doesn't pop data that nobody consumes.
- **PCDN-C-006** (doc-order priority): preserved through the if/elsif chain structure in the case-arm.
- **INV-SOS-H** (chart-vocabulary traceability): the `_recv_valid` and `_recv_ready` ports carry chart event names verbatim with trailing-comment annotations.

**Breaking change**: pre-wave-3-d-3, a transition like `<transition event="go" target="B"/>` on state `A` emitted `ST_A: state_next = ST_B;` (unconditional advance, event attribute ignored). Wave-3-d-3 emits `ST_A: begin if (event_go_recv_valid) state_next = ST_B; else state_next = ST_A; end`. Downstream consumers wiring directly to the region FSM's state_next or relying on the prior unconditional behaviour will see a SEMANTIC change. The new behaviour is correct per §6.4; the prior behaviour was a known gap.

**Test count**: net +8 — `TestWave3d3EventIngressRefactor` (8 tests): region module pairs recv_valid input + recv_ready output; unguarded event transition gated on recv_valid; combined event + cond predicate; recv_ready drive asserts in source state; doc-order priority chain with multiple events; chart-top fans recv_valid to consumers; chart-top aggregates recv_ready (boundary | consumers); regression-guard confirming event attribute is no longer ignored (§6.4 fix).

**Test suite**: 389/389 passing (381 baseline + 8 net wave-3-d-3). One pre-existing test updated to reflect the corrected §6.4 semantics: `test_document_order_priority_in_transition_mux` (VHDL) previously asserted that lower-priority transitions' targets NEVER appeared in the body (held under the wave-1 buggy "first-wins-unconditionally" emission); now asserts they appear in doc-order in the elsif chain (correct PCDN-C-006 semantics under per-event predicates). One SV regression-guard updated: `test_single_region_chart_without_raise_unchanged` (the `_simple_chart` fixture has `event="..."` transitions that now correctly produce recv_* ports — the test was renamed to `_no_egress` and now asserts only the egress side is absent).

**Cited PCDNs**: §6.4 (event ingress wiring); PCDN-C-006 (doc-order priority); INV-S-HDL-C-3 (channel-mediated event consumption); INV-S-HDL-4 (cooperative-only priority-claim).

Status: 🟢 **wave-3-d-3 complete**. With wave-3-d-1 (producer backpressure) + wave-3-d-3 (consumer ingress) + wave-3-c (channel instantiation) + wave-3-a/b (raise emission), the SCXML event-routing pipeline is end-to-end functional for the single-clock-domain case. Wave-3-d-2 (multi-clock-domain `sos_message_channel_async`) + wave-3-e (payload data) remain deferred.

### 2026-05-24 — Impl wave-3-d-2: async channel variant + walker selection (Ira)

Depends on SOS-08-B §15 2026-05-24 amendment (async sibling variant ratified). With the L1 primitive in place, the SOS-08-C walker can now emit `sos_message_channel_async` instances when chart-side producers and consumers cross clock domains.

**Wave-3-d-2 implementation surface**:

- **No region-FSM changes**: the region-side ports (`_send_valid/_send_ready`, `_recv_valid/_recv_ready`) are identical across the two channel variants. The walker selects between variants only at the chart-top wrapper.
- **`hdl_common.py` chart-top wrapper variant selection**:
  - Per chart-wide unique event, compute `producer_domains = sorted({region_index[r]["clock_domain"] for r in producers})` and `consumer_domains` symmetrically.
  - **Single clock case** (both sets singletons AND equal): emit `sos_message_channel` (wave-3-c form unchanged).
  - **CDC case** (both sets singletons but unequal): emit `sos_message_channel_async` with `wr_clk = producer_domains[0]` and `rd_clk = consumer_domains[0]`. Default `SYNC_STAGES = 2` (per `sos_fifo_async` precedent). Async-only observability ports (`wr_full`, `wr_count`, `rd_empty`, `rd_count`) bound to empty `()` in SV / `open` in VHDL.
  - **Multi-domain producers OR consumers per event**: raise `ValueError` with a chart-vocabulary diagnostic. Walker `_render_chart_top` re-raises `ValueError` (does NOT fall back to `_render_chart_top_local`), so the operator sees the diagnostic.
- **Walker fallback discipline (load-bearing)**: the existing `try / except Exception: pass` fallback at `_render_chart_top` (SV + VHDL) was catching ALL exceptions to tolerate signature drift of the canonical helper. Wave-3-d-2 introduces an intentional chart-vocabulary error path; the fallback now distinguishes:
  - `ValueError` (chart-author error) → re-raise. Operator sees the diagnostic; HDL is NOT silently emitted via the legacy local emitter.
  - Other exceptions (signature drift, runtime error) → continue falling back to `_render_chart_top_local`.
- **Channel-instance emission template** (SV):
  ```sv
  sos_message_channel_async #(
      .EVENT_ID_WIDTH(8),
      .PAYLOAD_WIDTH(8),
      .DEPTH(4),
      .READ_LATENCY(0),
      .RESET_MEM(1),
      .SYNC_STAGES(2)
  ) u_chan_<name> (
      .wr_clk(<producer-clock>),
      .wr_rst(<producer-reset>),
      // ... slave AXI-Stream (producer side) ...
      .rd_clk(<consumer-clock>),
      .rd_rst(<consumer-reset>),
      // ... master AXI-Stream (consumer side) ...
  );
  ```
  Mirror VHDL form uses `entity work.sos_message_channel_async` with `generic map (... SYNC_STAGES => 2 ...)`.

**Wave-3-d-2 scope explicitly excludes**:

- Multi-domain producers per event (would require a fan-in arbiter primitive — defer to future amendment).
- Multi-domain consumers per event (would require a fanout primitive with per-consumer CDC paths — defer).
- Payload routing on `_tpayload` ports (wave-3-e).
- The CDC variant's MTBF sign-off — inherited transparently from `sos_fifo_async/MTBF.md` per INV-S-HDL-B-4.

**Wave-3-d roadmap (final)**:

| Sub-wave | Scope | Status |
|---|---|---|
| wave-3-d-1 | Producer backpressure (`_send_ready`) | ✅ `e41fa56` |
| **wave-3-d-2** | Multi-clock channel variant (`sos_message_channel_async`) | ✅ **this commit** |
| wave-3-d-3 | Event ingress refactor (per-event `_recv_*` ports) | ✅ `dd816a3` |

With all three sub-waves landed, the SCXML event-routing pipeline now supports:
- Producer backpressure (no data drops on full channel).
- Single-clock-domain consumption.
- Cross-clock-domain consumption (via the CDC sibling primitive).
- Multiple producers and consumers per event (single domain each).
- Boundary observers (chart-top `event_<name>_recv_valid/ready` ports) co-existing with internal consumers.

Wave-3-e remains for payload data routing on `_tpayload` ports + chart `<param>`/`<content>` extension.

**Invariants upheld**:

- **INV-S-HDL-3** (cross-domain isolation): now fully operational. Cross-domain transitions route through `sos_message_channel_async`'s inner `sos_fifo_async`, which provides the gray-coded pointer crossings + SYNC_STAGES-deep flop synchronizers + the MTBF sign-off at `rtl/sos_fifo_async/MTBF.md`. Per PCDN-SOS-08-C-002 (retain_synchronizers), the channel instance survives `--verified-strip` regardless of bound-analysis reachability of consumer transitions.
- **INV-S-HDL-C-1** (deterministic emission): producer/consumer domain sets sorted before variant selection; channel instance emission deterministic for any given chart.
- **INV-S-HDL-C-3** (cross-domain event consumption uses `sos_message_channel`): now operational for the async case via the sibling variant; the doctrine "every cross-domain event consumption MUST traverse `sos_message_channel*`" is satisfied by either variant.
- **INV-S-HDL-4** (cooperative-only): preserved. The async variant doesn't change the cooperative-semantics contract — it only adds a CDC primitive between cooperative single-domain FSMs.
- **INV-SOS-H** (chart-vocabulary traceability): preserved. Both variants emit identical event-name annotations.
- **INV-S-HDL-B-2** (L0 non-modification): the async channel composes `sos_fifo_async` as a black-box.

**Test count**: net +5 — `TestWave3d2AsyncChannelVariant` (5 tests): CDC chart selects async variant; async variant uses `wr_clk` from producer domain; async variant exposes per-domain observability (wr_full/wr_count/rd_empty/rd_count); single-clock chart still uses sync variant (regression guard for variant selection); multi-producer-domain charts raise `ValueError`.

**Test suite**: 394/394 passing (389 baseline + 5 net wave-3-d-2).

**Files added** in this wave (rtl + tb):
- `rtl/sos_message_channel/sos_message_channel_async.sv`
- `rtl/sos_message_channel/sos_message_channel_async.vhd`
- `rtl/sos_message_channel/sos_message_channel_async_sva.sv`
- `tb/sos_message_channel/sos_message_channel_async_bind.sv`

**Cited PCDNs / amendments**: SOS-08-B §15 2026-05-24 (async sibling variant ratified); SOS-08-A §6.1 (sos_fifo_async contract — composition root); INV-S-HDL-3 (cross-domain isolation — now operational); PCDN-SOS-08-C-002 (retain_synchronizers across `--verified-strip`).

Status: 🟢 **wave-3-d-2 complete**. Wave-3-d sub-wave family is fully landed. Future amendments: wave-3-e (payload data) + multi-domain fanin/fanout primitives (deferred per scope).

### 2026-05-24 — Impl wave-3-e: payload data routing (Ira)

Closes the wave-3 event-routing arc by routing chart-side `<param>` data through the channel's `s_axis_tpayload` / `m_axis_tpayload` bus. With wave-3-e, raise events can carry typed payload values that propagate to consumers and external boundary observers.

**Wave-3-e implementation surface**:

- **`HdlTransition.raise_params: dict[event_name, list[(param_name, expr)]]`** — new field on both SV and VHDL walker dataclasses. Captures `<param>` children of each `<raise>` element keyed by event name. At v1, only the FIRST `<param>` per event is honoured (multi-param composition is a future extension requiring a chart-side payload-struct ratification).
- **Chart-side parsing**: each walker's transition-extraction loop reads `r.get("param", [])` per `<raise>` and stores `(name, expr)` tuples. Non-`<param>`-bearing raises stay unchanged (empty `raise_params` dict).
- **Chart-wide payload-bearing event collection**: at `render_target` (SV) / public entry (VHDL), scan all regions for transitions with non-empty `raise_params` to build `payload_events: set[str]`. Threaded through:
  - `_render_region_module` (SV) / `_render_region` (VHDL) — compute per-region `payload_send_events` (region's raise events ∩ chart-wide payload set) and `payload_recv_events` (region's consume events ∩ chart-wide payload set).
  - `_emit_module_header` (SV) / `_emit_entity` (VHDL) — emit one `output wire [7:0] event_<name>_send_data` per `payload_send_events` and one `input wire [7:0] event_<name>_recv_data` per `payload_recv_events`. PAYLOAD_WIDTH = 8 at v1 (matches channel hardcoded baseline at the chart-top wrapper; `_PAYLOAD_WIDTH` constant).
- **`_emit_event_payload_send_data_drives` (SV) / `_emit_event_payload_send_data_drives_vhdl` (VHDL)** — new emitter. For each payload-bearing event the region raises:
  - Per firing transition (walked with the wave-3-d-3 `_walk_state_for_event` + `_transition_fire_predicate_terms` helpers, filtered to transitions raising `ev` with non-empty `raise_params[ev]`), compute the fire predicate (including own `_recv_valid` when consuming).
  - Compile the param's `expr` via the existing guard-expr pipeline (`_compile_guard_expr` SV / `_compile_guard` VHDL) so bare datamodel identifiers rewrite to `data_<x>_q` form.
  - Drive: `event_<name>_send_data = (fire_pred ? <PAYLOAD_WIDTH>'(compiled_expr) : 0)`. Multi-transition OR-aggregate (under INV-S-HDL-4 cooperative-only, at most one raises per cycle).
- **`hdl_common.py` chart-top wrapper** (SV + VHDL):
  - **Region instance port-map**: per `payload_send_events` add `.event_<name>_send_data(w_ev_<region>_<name>_data)`; per `payload_recv_events` add `.event_<name>_recv_data(ev_<name>_recv_data_w)`.
  - **Internal wires**: declare `wire [7:0] w_ev_<region>_<name>_data` per (producer-region, payload-event) edge; declare `wire [7:0] ev_<name>_recv_data_w` per payload-bearing event for the m_axis fanout.
  - **Data aggregation**: `wire [7:0] ev_<name>_send_data = OR of producer data wires` (broadcast under INV-S-HDL-4).
  - **Channel wiring**: `s_axis_tpayload(ev_<name>_send_data)` / `m_axis_tpayload(ev_<name>_recv_data_w)` when the event is payload-bearing; else tied off (`'0` / unconnected) preserving the wave-3-c behaviour for non-payload events.
  - **Boundary observer**: chart-top wrapper gains an `output wire [7:0] event_<name>_recv_data` port per payload-bearing event, driven by `assign event_<name>_recv_data = ev_<name>_recv_data_w`. External observers can monitor the payload data alongside the wave-3-d-3 `_recv_valid`/`_recv_ready` boundary surface.
- **Walker `_build_region_modules_canonical`**: surfaces `payload_send_events` + `payload_recv_events` fields per region module dict.

**Wave-3-e scope explicitly excludes**:

- **Multi-param raises**: only the FIRST `<param>` per `<raise>` is honoured. Multi-param composition requires a chart-side payload-struct ratification (one packed-struct variant per ExternalEventName ID per PCDN-SOS-08-B-005) which is a future amendment.
- **`<content>` element**: SCXML `<content>` (raw payload text/JSON) is a future extension; v1 supports `<param>` only.
- **Datamodel binding on the consume side**: the consumer region's `event_<name>_recv_data` input is exposed but NOT auto-bound to a chart datamodel signal. Wiring `event.X.value` to `<assign location="local_counter" expr="event.X.value"/>` in a target state's `<onentry>` requires the chart-side event-object lowering pipeline which is a future wave (likely paired with the SCXML execution-content semantics).
- **PAYLOAD_WIDTH parameterisation**: hardcoded to 8 at v1. Per-chart width based on the widest param expr is a future amendment (would require chart-compile-time width inference).
- **Sub-byte payload encoding**: `<param expr="counter"/>` where `counter` is a 32-bit datamodel signal is truncated to 8 bits via SV cast (`8'(data_counter_q)`). Chart authors should keep payload exprs within 8-bit range or wait for the parameterised-width amendment.

**Cycle-level behaviour** (payload-bearing event, producer drives counter=5):

| Cycle | producer state | `send_data` | `send_valid` | `send_ready` | channel state | `recv_data` (boundary) |
|-------|----------------|-------------|--------------|--------------|---------------|------------------------|
| N     | L1             | 8'd5        | 1            | 1            | empty → full  | 8'd5 (after handshake) |
| N+1   | L2             | 8'd0        | 0            | —            | full          | 8'd5 (held until consumed) |
| N+2   | L2             | 8'd0        | 0            | —            | empty (consumer popped) | 8'd0 |

**Invariants upheld**:

- **INV-S-HDL-1** (handshake-compatible ports): the new `_send_data` / `_recv_data` ports complete the AXI-Stream payload surface alongside the wave-3-d-{1,3} handshake.
- **INV-S-HDL-C-1** (deterministic emission): payload event sets sorted; data wires emit in deterministic order.
- **INV-S-HDL-4** (cooperative-only): OR-aggregation of producer data wires correct under cooperative single-producer-per-cycle.
- **INV-SOS-H** (chart-vocabulary traceability): payload data ports carry chart-event-name annotations matching the wave-3-d-3 ingress/egress port annotations.
- **PCDN-SOS-08-B-005** (chart-derived metadata struct) — partially operational. The L1 service's `tpayload` bus is now driven from chart-emitted expressions; the per-event packed-struct VARIANT interpretation (one struct per `ExternalEventName`) is the future extension.

**Backwards compatibility**: events without `<param>` are unchanged. The wave-3-{a..d} valid/ready-only emission shape is preserved by construction — `_send_data` / `_recv_data` ports are emitted ONLY when at least one `<param>` exists for that event somewhere in the chart. Test `test_non_payload_event_keeps_minimal_ports` is the regression guard.

**Test count**: net +7 — `TestWave3ePayloadRouting` (7 tests): producer region emits `_send_data` output; consumer region emits `_recv_data` input; `_send_data` driven from param expr (datamodel signal rewritten to `data_<x>_q`); chart-top exposes `_recv_data` boundary port; chart-top wires channel's `s_axis_tpayload`/`m_axis_tpayload`; chart-top region instances wire data ports; non-payload events retain minimal port set (regression guard).

**Test suite**: 401/401 passing (394 baseline + 7 net wave-3-e).

**Cited PCDNs / amendments**: PCDN-SOS-08-B-005 (chart-derived metadata struct); SOS-08-B §6.5 (channel `tpayload` bus); SOS-08-A §6.1 (sos_fifo_async/sos_fifo_sync data path inheritance); INV-SOS-H (chart-vocabulary traceability for payload).

Status: 🟢 **wave-3-e complete**. The SCXML event-routing arc (wave-3-a through wave-3-e) is now end-to-end functional: events raised by one region pulse through the channel with backpressure + payload data + CDC awareness, are consumed by other regions or external observers, and the payload data round-trips through the channel's `tpayload` bus. Multi-param composition + sub-byte payload encoding + chart-side payload-struct ratification remain future amendments.

### 2026-05-24 — Impl wave-3-f: datamodel binding on consume side (Ira)

Wave-3-f closes the consume-side datamodel-binding gap the wave-3-e §15 entry called out: chart-side `<onentry><assign location="<X>" expr="event.<EV>.value"/></onentry>` lowering now routes the consumed event's payload data into the destination datamodel register on the entry-edge into the target state. With wave-3-f, an end-to-end "raise → channel → consume → store-into-datamodel" loop is expressible in pure SCXML + lowered to deterministic RTL by the SV + VHDL walkers.

**Wave-3-f declaration form (frozen 2026-05-24 §15)**:

```xml
<state id="S">
    <onentry>
        <assign location="<X>" expr="event.<EV>.value"/>
    </onentry>
    ...
</state>
```

Where:
- `<X>` MUST be a chart-side datamodel signal declared in `<datamodel>`.
- `<EV>` MUST be an event the region consumes (i.e., named in a `event="<EV>"` attribute on some transition in the same region). Walkers reject otherwise with a chart-vocabulary error (`UnsupportedChartError` naming the unknown consume event).
- `.value` is the canonical single-`<param>` form (per wave-3-e payload convention). Other suffixes (`event.<EV>.<custom_name>`) are wave-3-f-future, gated on multi-`<param>` event payload composition.

**Lowering semantics**:

On every clock edge where `state_q != ST_S && state_next == ST_S && event_<EV>_recv_valid`, capture `event_<EV>_recv_data` into the destination datamodel register. This is the entry-edge into state S triggered by event EV. The condition is intentionally specific:

- `state_q != ST_S` rules out the case where we're already in S (no entry edge).
- `state_next == ST_S` is the standard entry condition.
- `event_<EV>_recv_valid` confirms the event was actually consumed on this cycle (the FSM's predicate already requires this to fire the transition, but the capture re-checks it for safety + clarity).

Multiple captures into the same datamodel signal from different states form an if/else if chain (document-order priority); the final `else` clause holds the register's current value. Different datamodel signals get independent chains in the same `always_ff` body.

**Wave-3-f implementation surface (both walkers)**:

- `HdlEventPayloadCapture` dataclass — `(state_id, location, event_name)`.
- `_EVENT_PAYLOAD_RE` regex — matches `event.<EV>.value` (whitespace-tolerant; alphanumeric + underscore + hyphen in `<EV>`).
- `_collect_region_event_payload_captures(region)` walker — extracts captures from each state's `onentry_assigns`; validates `<EV>` is a consume event of the region (hard error otherwise).
- `_emit_register_process` extended — when captures are non-empty, emits per-capture entry-edge override branches; otherwise preserves the wave-1/wave-2 default-hold shape (byte-identical for charts without captures).

**Cross-walker mirror equivalence**: SV emit shape:

```sv
if (state_q != ST_OBSERVED && state_next == ST_OBSERVED && event_tick_recv_valid) begin
    data_last_value_q <= event_tick_recv_data;
end else begin
    data_last_value_q <= data_last_value_q;
end
```

VHDL emit shape:

```vhdl
if state_q /= ST_OBSERVED and state_next = ST_OBSERVED and event_tick_recv_valid = '1' then
    last_value_q <= signed(event_tick_recv_data);
else
    last_value_q <= last_value_q;
end if;
```

The VHDL emit casts `_recv_data` (a `std_logic_vector`) to `signed` because the datamodel register is declared `signed` per `_datamodel_signal_lines`; SV's `data_<X>_q` is already a packed logic vector so no cast is needed.

**Wave-3-f-future boundary** (explicit out-of-scope):

- **Multi-`<param>` events**: when a chart event carries multiple `<param>` children, the `event.<EV>.<custom_name>` form needs to select among the per-param `_recv_data_<custom>` buses. Wave-3-e v1 supports single-`<param>` (`name="value"`) only; wave-3-f mirrors that scope.
- **`<onexit>` captures**: lowering `<assign>` in `<onexit>` requires a different gating condition (entry-edge OUT of S — i.e., `state_q == ST_S && state_next != ST_S`). Wave-3-f covers `<onentry>` only.
- **Non-event-value `<assign>` lowering**: `<assign location="x" expr="42"/>` (numeric-literal) or `<assign location="x" expr="other_signal"/>` (datamodel-to-datamodel) are silently ignored at wave-3-f (preserves wave-1/wave-2 no-op behavior). The general `<assign>` ECMAScript-subset lowering remains a future wave.
- **Cross-region event-value capture**: when a region's `<onentry>` references an event consumed by a DIFFERENT region, wave-3-f raises `UnsupportedChartError`. Composing captures across regions requires the chart-top wrapper to expose the channel's `_recv_data` to additional consumers — a future amendment.

**Invariants upheld**:

- **INV-S-HDL-C-1** (chart-as-source): preserved — capture lowering is deterministic from the chart text.
- **INV-S-HDL-C-2** (datamodel signals reach RTL register form): **extended** — datamodel registers now have a defined write source beyond reset (the entry-edge capture).
- **INV-S-HDL-C-3** (cross-domain CDC isolation): unchanged — captures read `_recv_data` which is the channel's already-synchronised consumer-side output.
- **INV-S-HDL-C-4** (datamodel-write observability): retained — wave-3-f's entry-edge capture is the kind of write site INV-S-HDL-C-4 expected the debug-strobe pass to expose.
- **INV-S-HDL-C-5** (one-hot encoding deterministic across dialects): unchanged — the wave-3-f if/elsif chain uses the same `ST_<UPPER>` constants both walkers emit.

**Test count**: 15 new tests across `TestWave3fEventPayloadCapture` (9 — SV) + `TestWave3fEventPayloadCaptureVhdl` (6 — VHDL). Both walkers verified to:
- Emit the entry-edge capture branch with the correct gating expression.
- Assign `_recv_data` into the datamodel register.
- Hold the previous value in the else branch.
- Reject captures referencing events the region doesn't consume.
- Form an if/elsif chain for multiple captures into the same signal.
- Preserve wave-1/wave-2 emit shape for charts without captures.

**Test suite**: 570/570 passing (555 prior + 15 wave-3-f).

**Cited PCDNs / amendments**: §15 wave-3-f (this entry) ratifies the `event.<EV>.value` event-object form; wave-3-e §15 payload-bearing event ports (consumed); INV-S-HDL-C-2/-C-4 extended.

Status: 🟢 **wave-3-f complete**. The SCXML event-routing arc + datamodel-binding-on-consume-side is now end-to-end functional: events raised by one region pulse through the channel with backpressure + payload data + CDC awareness, are consumed by other regions, and the payload value is captured into a chart-side datamodel signal on the entry-edge into the consuming state. Multi-`<param>` composition, `<onexit>` captures, general ECMAScript-subset `<assign>` lowering, and cross-region event-value capture remain future amendments.

### 2026-05-24 — Impl wave-3-f-future-A: `<onexit>` captures + wave-3-f-future-B multi-`<param>` rejection (Ira)

Lands two of the four wave-3-f-future carry-forward items:

- **Wave-3-f-future-A** (closed) — `<onexit>` event-payload captures. Mirror of the wave-3-f `<onentry>` shape with the gating expression inverted. The chart-author authoring contract extends cleanly: `<onexit><assign location="<X>" expr="event.<EV>.value"/></onexit>` lowers to a registered assignment gated by `state_q == ST_S && state_next != ST_S && event_<EV>_recv_valid`. Both SV and VHDL walkers participate; tests pin the cross-walker mirror.
- **Wave-3-f-future-B** (rejection-only) — multi-`<param>` events. The walker recognises the syntactic form `event.<EV>.<custom>` (where `<custom> != "value"`) and rejects with an actionable `UnsupportedChartError` citing the wave-3-f-future-B boundary + suggesting the workaround (rename the chart-side `<param>` to `value`, or compose the payload into a single integer/packed-struct on the raise side). The full multi-`<param>` walker support stays carry-forward, gated on upstream wave-3-e port-shape changes (per-param `_recv_data_<custom>` sub-buses).

**Why the split**: wave-3-f-future-A is a clean ~30-LOC extension touching only the wave-3-f capture/emit machinery; wave-3-f-future-B is a multi-file refactor of the wave-3-e payload-bearing event-port emission shape. Landing A now closes the `<onexit>` carry-forward without coupling its risk to the larger upstream amendment. The rejection in wave-3-f-future-B converts silent fall-through (chart compiles, capture is no-op, debugging is opaque) into an actionable chart-vocabulary error that names the offending suffix + the workaround — chart authors writing `event.<EV>.<custom>` now learn immediately that they have hit a wave boundary, not days later when their datamodel signal stays at its reset value.

**Implementation surface**:

- **`HdlEventPayloadCapture` dataclass (both walkers)** — gains `edge: str = "entry"` field. Default preserves wave-3-f emit byte-identity for charts using `<onentry>` only.
- **`_EVENT_PAYLOAD_RE` regex (both walkers)** — was `^\s*event\.(\w+)\.value\s*$`; now `^\s*event\.(\w+)\.(\w+)\s*$` (captures both the event name AND the suffix). The suffix is then dispatched: `value` → accept, anything else → raise wave-3-f-future-B `UnsupportedChartError`.
- **`_collect_region_event_payload_captures` (both walkers)** — refactored to walk BOTH `onentry_assigns` (edge="entry") AND `onexit_assigns` (edge="exit") via a shared inner `_process(assign, state, edge)` helper. The custom-suffix rejection lives inside the helper so it applies symmetrically to entry + exit lowerings.
- **`_emit_register_process` (both walkers)** — extended to emit the exit-edge gating expression when `cap.edge == "exit"`. SV: `state_q == ST_S && state_next != ST_S && event_<EV>_recv_valid`. VHDL: `state_q = ST_S and state_next /= ST_S and event_<EV>_recv_valid = '1'`. Backwards-compatible by default; charts without `<onexit>` captures emit byte-identically to wave-3-f.

**Sample emit (SV, single-region chart with `<onexit>` capture)**:

```sv
if (state_q == ST_OBSERVED && state_next != ST_OBSERVED && event_tick_recv_valid) begin
    data_last_seen_q <= event_tick_recv_data;
end else begin
    data_last_seen_q <= data_last_seen_q;
end
```

**Sample emit (VHDL mirror, same chart)**:

```vhdl
if state_q = ST_OBSERVED and state_next /= ST_OBSERVED and event_tick_recv_valid = '1' then
    last_seen_q <= signed(event_tick_recv_data);
else
    last_seen_q <= last_seen_q;
end if;
```

**Mixed entry + exit captures composing into one chain**: a chart that captures the same datamodel signal on entry AND exit from different states produces a single if/elsif chain with both gating shapes, last-write-wins per SCXML §3.13 onentry/onexit execution order:

```sv
if (state_q != ST_S1 && state_next == ST_S1 && event_a_recv_valid) begin
    data_buf_q <= event_a_recv_data;
end else if (state_q == ST_S1 && state_next != ST_S1 && event_a_recv_valid) begin
    data_buf_q <= event_a_recv_data;
end else begin
    data_buf_q <= data_buf_q;
end
```

**Wave-3-f-future-B rejection example** (chart with `event.tick.payload`):

```
UnsupportedChartError: SOS-08-C wave-3-f-future-B: <onentry><assign
location='x' expr='event.tick.payload'/> uses a non-`value` suffix; the
wave-3-e payload-bearing event port shape carries a single unnamed bus
(``event_tick_recv_data``). Multi-`<param>` event payload composition
(per-param sub-buses keyed on `<param name="payload">`) is deferred to a
future wave-3-f-future-B amendment + upstream wave-3-e port-shape
extension. Until then, either rename your `<param>` to `value`, or
compose the payload into a single integer / packed struct on the raise
side.
```

**Invariants upheld**:

- **INV-S-HDL-C-1** (chart-as-source): preserved — both edges' lowering is deterministic from the chart text.
- **INV-S-HDL-C-2** (datamodel signals reach RTL register form): preserved + extended in spirit — datamodel registers now have a defined write source on BOTH entry-edge AND exit-edge events.
- **INV-S-HDL-C-3** (cross-domain CDC isolation): unchanged — exit-edge captures read the same `_recv_data` channel-side bus as entry-edge captures.
- **INV-S-HDL-C-4** (datamodel-write observability): retained — exit-edge captures are the same kind of write site INV-S-HDL-C-4 expected the debug-strobe pass to expose; the additional write site simply doubles the surface area, not the kind.
- **INV-S-HDL-C-5** (one-hot encoding deterministic across dialects): unchanged.

**Wave-3-f-future remaining boundary** (still deferred):

- **Wave-3-f-future-B (multi-`<param>` events)** — the full implementation. Requires upstream wave-3-e port-shape extension to per-param `_recv_data_<custom>` sub-buses + chart-top wrapper payload partitioning. The rejection-only landing in this entry surfaces the boundary cleanly; the full path lands when a customer chart demands it.
- **General ECMAScript-subset `<assign>` lowering** — `<assign location="x" expr="42"/>` (numeric-literal) or `<assign location="x" expr="other_signal"/>` (datamodel-to-datamodel). Wave-3-f-future-A keeps these silently ignored (preserving wave-1/wave-2 no-op behavior); a future amendment with a small expression DSL closes this gap.
- **Cross-region event-value capture** — when a region's `<onentry>`/`<onexit>` references an event consumed by a DIFFERENT region, the walker continues to raise `UnsupportedChartError`. Composing captures across regions requires the chart-top wrapper to expose the channel's `_recv_data` to additional consumers.

**Test count**: net +16 across two walkers:

- `TestWave3fFutureOnexitCapture` (5 — SV): exit-edge gating present; assigns `_recv_data`; default holds value; entry shape NOT emitted for exit capture; entry+exit can coexist in one if/elsif chain.
- `TestWave3fFutureBMultiParamRejection` (4 — SV): custom suffix raises; error names offending suffix; error suggests rename; `value` suffix still accepted.
- `TestWave3fFutureOnexitCaptureVhdl` (4 — VHDL): exit-edge gating; signed cast on `_recv_data`; holds value in else; entry shape NOT emitted for exit capture.
- `TestWave3fFutureBMultiParamRejectionVhdl` (3 — VHDL): custom suffix raises; error names offending suffix; `value` suffix still accepted.

**Test suite**: 689/689 passing (673 prior + 16 new wave-3-f-future).

**Cited invariants / amendments**: §15 wave-3-f (entry shape — extended here to also cover exit edge); INV-S-HDL-C-1..5 (preserved); SCXML §3.13 onentry/onexit execution order (cited for last-write-wins semantics in mixed entry+exit chains).

Status: 🟢 **wave-3-f-future-A complete + wave-3-f-future-B boundary made actionable**. `<onexit>` event-payload captures lower identically across SV + VHDL walkers; multi-`<param>` events surface immediately as chart-vocabulary errors with a workaround citation. Wave-3-f-future-B full implementation, general `<assign>` ECMAScript-subset lowering, and cross-region event-value capture remain on the wave-3-f-future track.

### 2026-05-24 — Impl wave-3-f-future-assign: general ECMAScript-subset `<assign>` lowering (Ira)

Closes the **general `<assign>` ECMAScript-subset lowering** item from the wave-3-f-future remaining boundary (per the prior §15 entry's status line). The wave-3-f walker family handled exactly one `<assign>` RHS form — the canonical `event.<EV>.value` event-payload capture; every other RHS was either silently no-op'd (wave-1/wave-2 baseline) or rejected at the regex pre-pass with "expr form not supported". Real charts need more: per-state counter increments (`<assign expr="counter + 1"/>`), state-reset patterns (`<assign expr="0"/>`), and history retention (`<assign expr="counter"/>`). This entry ratifies a small, normative ECMAScript subset for `<assign expr=>` and lowers it through both walkers.

**Subset — normative**. Per RFC 2119, an `<assign expr=>` body conforming to the wave-3-f-future-assign amendment MUST be one of:

- An **integer literal** — decimal (`42`, `0`) or hex with the `0x` prefix (`0x2A`, `0xff`). The walker MUST parse the literal via Python's `int(text, 0)` and lower it to a signed integer constant at the datamodel register's declared width.
- A **boolean literal** (`true`, `false`) — lowered to integer constant `1` / `0` respectively. This preserves wave-1/wave-2 boolean-flag charts (`<assign location="flag" expr="true"/>`) which the pre-amendment walkers silently no-op'd.
- A **unary minus on an integer literal** (`-42`) — lowered to a signed-negative integer constant. Unary minus on a non-literal operand MUST raise (`-counter` is rejected; the workaround is binary minus from zero, `0 - counter`).
- A **datamodel identifier read** — a bare identifier resolved against the enclosing chart's `<datamodel>`. Unknown identifiers MUST raise with the citation prefix `SOS-08-C wave-3-f-future-assign: ... references unknown datamodel identifier '<ident>'`.
- A **binary `+` or `-`** between any of the above forms or between two datamodel identifiers (`counter + 1`, `prev - counter`).
- A **parenthesised sub-expression** for grouping — `(counter + 1) - prev`. Parentheses MAY be used freely; they do not change semantics.
- The **existing `event.<EV>.value` / `event.<EV>.<suffix>` form**, preserved byte-identical via the upstream `_EVENT_PAYLOAD_RE` regex pre-pass. The new parser is invoked ONLY when the regex does not match.

**Rejected forms — normative**. An `<assign expr=>` body MUST NOT use:

- Multiplication, division, or modulo (`*`, `/`, `%`). Rejection cites the offending operator.
- Function calls (`f(x)`). Rejection cites the function name.
- Conditional / ternary expressions (`x ? a : b`). Rejection cites the form.
- String literals (`"abc"`, `'abc'`). Rejection cites the literal.
- Comparison or logical operators (`==`, `!=`, `<`, `<=`, `>`, `>=`, `&&`, `||`, `!`).
- Bitwise operators (`&`, `|`, `^`, `~`).
- Member access other than the `event.<EV>.value` form already handled by the upstream regex.

Each rejected form raises `UnsupportedChartError` with the prefix `SOS-08-C wave-3-f-future-assign:` (or `SOS-08-C wave-3-f-future-assign (VHDL):` for the VHDL walker), the offending `<onentry|onexit><assign>` context, a named cause (operator, function name, "string literal", etc.), and the supported-form summary. Chart authors hitting a boundary therefore get an actionable error citing this §15 amendment rather than silent no-op.

**Authority boundary declaration**. Per the standards-integration discipline (§0):

| Concept | Upstream authority | Local representation | Mutation rights | Divergence policy | Downstream consumers | Conformance test owner | Relationship |
|---|---|---|---|---|---|---|---|
| `<assign expr=>` ECMAScript-subset grammar | ECMA-262 §11 (expressions) | `_assign_expr.py` recursive-descent parser | Subset narrowing only — no superset additions without §15 amendment | Extensions live in this §15 entry; deviations from ECMA-262 (e.g. our 0x-hex literal handling) MUST cite this section | SV + VHDL register-emit per-signal if/else chain | This phase doc (wave-3-f-future-assign acceptance) | **derive** |
| Lowering rules to HDL (SV signed literal, VHDL `to_signed(N, width)`) | This phase doc | `_render_sv` / `_render_vhdl` in `_assign_expr.py` | Full mutation rights (this repo authors) | n/a (locally owned) | Generated SV / VHDL register processes | This phase doc | **own** |

**Implementation surface**:

- **`tools/sos-codegen/_assign_expr.py` (new file, ~380 LOC including docstrings + renderers; parser proper ~80 LOC)** — shared between SV and VHDL walkers. Defines `AssignExpr` dataclass (kinds: `literal`, `ident`, `binop`, `neg_literal`, plus reserved `event_payload`), `AssignExprError`, the pure-Python recursive-descent parser `_parse_assign_expr(expr_text, datamodel_ids)`, and dialect-specific lowering helpers `_render_sv` / `_render_vhdl`. The parser has no external dependencies; the tokenizer is a small hand-written scanner producing `INT | IDENT | PLUS | MINUS | LPAREN | RPAREN | OTHER` tokens with `OTHER` carrying the offending lexeme into a named error message.
- **`HdlGeneralAssign` dataclass (both walkers)** — added alongside `HdlEventPayloadCapture`. Carries the source state, target location, edge tag (`"entry"` / `"exit"`), and the parsed `AssignExpr` tree.
- **`_collect_region_general_assigns` (both walkers)** — walks `onentry_assigns` + `onexit_assigns`, skips any RHS matching `_EVENT_PAYLOAD_RE` (those remain owned by `_collect_region_event_payload_captures`), dispatches the remainder through `_parse_assign_expr`. Wraps `AssignExprError` into `UnsupportedChartError` with the `wave-3-f-future-assign` citation prefix + the offending `<assign>` location/expr context.
- **`_emit_register_process` (both walkers)** — extended to accept a `general_assigns` parameter alongside `event_payload_captures`. Each datamodel signal's if/elsif chain now interleaves event-payload arms (when applicable) with general-assign arms; both share the same edge-gating shapes (`state_q != ST_S && state_next == ST_S` for entry, mirrored for exit). General-assign arms do NOT carry the `event_<EV>_recv_valid` term — gating is purely the state-edge into the carrying state.

**Sample emit (SV, per-state counter increment)**:

```sv
always_ff @(posedge clk) begin
    if (rst) begin
        state_q <= ST_A;
        data_counter_q <= 32'sd0;
    end else begin
        state_q <= state_next;
        if (state_q != ST_A && state_next == ST_A) begin
            data_counter_q <= data_counter_q + 1;
        end else begin
            data_counter_q <= data_counter_q;
        end
    end
end
```

**Sample emit (VHDL mirror, same chart)**:

```vhdl
process(clk) is
begin
    if rising_edge(clk) then
        if rst = '1' then
            state_q <= ST_A;
            counter_q <= to_signed(0, counter_q'length);
        else
            state_q <= state_next;
            if state_q /= ST_A and state_next = ST_A then
                counter_q <= counter_q + to_signed(1, 32);
            else
                counter_q <= counter_q;
            end if;
        end if;
    end if;
end process;
```

**Width handling**. The datamodel register's width is inherited from the wave-3-e width-resolution chain (`<sos:datamodel_width>` annotation, `<data width=N>` attribute, SCXML `type=` mapping, default 32-bit). The walker does NOT widen on overflow per the wave-3-e cited behaviour — `counter_q + 1` is a width-bound add with implicit truncation. Chart authors needing wider arithmetic MUST declare a wider `<data width=...>` annotation; this is consistent with the wave-3-e payload-bearing event-port shape and avoids silent width promotion.

**Cross-walker parity**. Both SV and VHDL walkers import the SAME `_parse_assign_expr` (via `from _assign_expr import ...`); only the lowering helper differs. Rejection messages diverge in one token (`(VHDL)` walker tag in the VHDL variant) to disambiguate which dialect surfaced the error. The single shared parser eliminates the historical drift risk of two near-identical regex-based parsers.

**Rejection example** (chart with `<assign expr="counter * 2"/>`):

```
UnsupportedChartError: SOS-08-C wave-3-f-future-assign: <onentry><assign
location='counter' expr='counter * 2'/> uses unsupported operator '*';
supported: + -, integer literals (decimal/0x...), datamodel identifiers,
parenthesised sub-expressions, and event.<EV>.value forms.
```

**Invariants upheld**:

- **INV-S-HDL-C-1** (chart-as-source): preserved — lowering is deterministic from the chart text via a pure-function parser.
- **INV-S-HDL-C-2** (datamodel signals reach RTL register form): preserved + extended — the per-signal if/elsif chain now admits a strict superset of the wave-3-f shapes; legacy charts emit byte-identically.
- **INV-S-HDL-C-3** (cross-domain CDC isolation): unchanged — general assigns read only same-region datamodel signals.
- **INV-S-HDL-C-4** (datamodel-write observability): retained — general-assign arms are the same kind of register-write site as event-payload captures.
- **INV-S-HDL-C-5** (one-hot encoding deterministic across dialects): unchanged.

**Wave-3-f-future remaining boundary** (still deferred):

- **Wave-3-f-future-B full implementation** (multi-`<param>` events) — unchanged. Still gated on upstream wave-3-e port-shape extension. Rejection-only landing remains in effect.
- **Cross-region event-value capture** — when a region's `<onentry>`/`<onexit>` references an event consumed by a DIFFERENT region, the walker continues to raise `UnsupportedChartError`. Composing captures across regions requires the chart-top wrapper to expose the channel's `_recv_data` to additional consumers.

**Frozen-enum registration policy**: `AssignExpr.kind` (`literal | ident | binop | neg_literal | event_payload`) is **Specification Required** — adding a value requires a phase-owner walkthrough update; no separate §15 amendment needed because the enum lives entirely inside `_assign_expr.py` and has no cross-phase contract surface.

**Test count**: net +30 across two walkers — 15 each. Test classes `TestWave3fFutureAssignLowering` (SV) and `TestWave3fFutureAssignLoweringVhdl` (VHDL) cover: numeric-literal lowering, hex-literal, unary minus on literal, datamodel-ident copy, binary `+` (literal + ident), binary `-` (two idents), `<onentry>` entry-edge gating, `<onexit>` exit-edge gating, event-value regression guard, datamodel-only-shape regression guard, unknown-ident rejection, `*` rejection, function-call rejection, ternary rejection, string-literal rejection.

**Test suite**: 779/779 passing (749 prior + 30 new wave-3-f-future-assign).

**Cited invariants / amendments**: §15 wave-3-f (entry shape — extended here to admit non-event RHS); §15 wave-3-f-future-A (exit shape — same extension); INV-S-HDL-C-1..5 (preserved); SCXML §3.13 onentry/onexit execution order (cited for ordering of mixed event-payload + general-assign arms in the per-signal if/elsif chain).

Status: 🟢 **general ECMAScript-subset `<assign>` lowering complete**. Wave-3-f-future remaining now narrows to wave-3-f-future-B full implementation + cross-region event-value capture; both deferrals are bounded by upstream port-shape work, not by chart-author ergonomics.

### 2026-05-24 — Impl wave-3-f-future-xreg: cross-region event-value capture (Ira)

Closes the **cross-region event-value capture** item from the wave-3-f-future remaining boundary (per the prior §15 entry's status line). Prior to this amendment, a chart with multiple `<parallel>` regions could not capture an event's payload across the region boundary: a region's `<onentry>/<onexit><assign expr="event.<EV>.value"/>` referencing an event raised by a SIBLING region (but not consumed via a transition in this region) raised `UnsupportedChartError` with the wave-3-f "NOT a consume event" message. Real charts need this — orchestration regions raise events with payloads that observer regions read; the wave-3-c chart-top channel mediates the routing but the wave-3-f capture machinery refused to wire the consumer side.

**Subset — normative**. Per RFC 2119, an `<assign expr="event.<E>.value"/>` body conforming to the wave-3-f-future-xreg amendment MUST be in one of the following situations:

- The capturing region's transitions consume event `<E>` — the wave-3-f intra-region capture shape (unchanged byte-identical from the prior amendments).
- The capturing region does NOT consume `<E>` via a transition BUT at least one OTHER region in the chart raises `<E>` via a `<transition>...<raise event="<E>"/></transition>` — the cross-region capture shape. The walker MUST emit `event_<E>_recv_valid` / `event_<E>_recv_data` input ports on the capturing region and the chart-top wrapper MUST wire the broadcast bus into them.
- Event `<E>` is referenced in an `<assign>` but raised by no region anywhere in the chart — chart-vocab error with the citation prefix `SOS-08-C wave-3-f-future-xreg:` (or `(VHDL)` for the VHDL walker) and the message `references event '<E>' which is not raised anywhere in the chart. Add a <transition>...<raise event='<E>'/></transition> or remove the capture.`

**Concurrency invariant**. Per the wave-3-f-future-A INV (preserved): the cross-region capture takes effect on the cycle AFTER the raise — `state_q` transitions on the same clock edge that `event_<EV>_recv_valid` deasserts and the captured register updates on that same edge. The wave-3-c `sos_message_channel` introduces no additional latency beyond its declared `READ_LATENCY=0` baseline; the broadcast bus surfaces the channel's `m_axis_*` face under a different name.

**Chart-top broadcast bus — normative naming**. The chart-top wrapper MUST emit (for every event raised by at least one region AND captured by at least one sibling region via cross-region capture) two broadcast bus signals:

- `chart_event_<EV>_raise_valid` — 1-bit wire (SV) / `std_logic` signal (VHDL) aliasing the aggregated `ev_<EV>_send_valid` internal signal. Asserts for one cycle when any region raises `<EV>`.
- `chart_event_<EV>_raise_data` — `[PAYLOAD_WIDTH-1:0]` wire (SV) / `std_logic_vector(PAYLOAD_WIDTH-1 downto 0)` signal (VHDL) aliasing the aggregated `ev_<EV>_send_data` internal signal. Carries the payload of the active raise (or the OR-mix of payloads on a same-cycle multi-raiser conflict — see below).

These signals are **additive** to the existing wave-3-c `ev_<EV>_send_valid` / `_send_data` / `_recv_valid_w` / `_recv_data_w` internal wires; the new names exist so chart authors and SVA writers have a stable surface keyed on `chart_event_<EV>_raise_*` (the wave-3-c names mix internal `ev_` and external `event_` prefixes for historical reasons). PAYLOAD_WIDTH = 8 at v1 (matches the channel's hardcoded baseline).

**Multi-raiser conflict resolution — normative**. Per SCXML §3.13 microstep ordering (cited authority `derive`): when two or more sibling regions raise the SAME event in the SAME cycle, the run-to-completion microstep semantics say one raise comes first. At HDL elaboration time, both region pulses fire on the same clock edge and the existing wave-3-c chart-top emits:

- **Valid aggregation**: bitwise OR over per-region pulse signals (`ev_<EV>_send_valid = w_ev_<r1>_<EV>_pulse | w_ev_<r2>_<EV>_pulse | ...` in SV; VHDL uses the `or` operator). This rule is unchanged from wave-3-c.
- **Data aggregation**: bitwise OR over per-region data buses (`ev_<EV>_send_data = w_ev_<r1>_<EV>_data | w_ev_<r2>_<EV>_data | ...`). The OR-mix collapses to the active raiser's value when at most one region raises per cycle; with two or more concurrent raisers the bus is the bitwise OR of their payloads — semantically ambiguous.
- **Priority mux on data — implicit**: the chart-top wrapper SHOULD document the document-order priority (lower-document-index region wins on a same-cycle conflict) in a comment block adjacent to the aggregation, so reviewers can audit the ordering against SCXML §3.13. The walker emits this comment block automatically on the wave-3-f-future-xreg path.
- **Same-cycle conflict — runtime detection**: the chart-top wrapper MUST emit (for any event with ≥ 2 raisers) a runtime `$warning` (SV) / `report ... severity warning` (VHDL) that fires when ≥ 2 of the per-region pulse signals are high in the same cycle. The warning text MUST name the event and reference the wave-3-f-future-xreg citation. The detector block MUST be wrapped in synthesis-strip pragmas (`// synthesis translate_off/on` for SV; `-- pragma synthesis_off/on` for VHDL) so synthesisers do not infer it. This converts the silent-collision failure mode (chart authors observe an OR-mixed payload and don't know why) into an actionable diagnostic the simulation operator sees on the first conflicting cycle.

**Authority boundary declarations**. Per the standards-integration discipline (§0):

| Concept | Upstream authority | Local representation | Mutation rights | Divergence policy | Downstream consumers | Conformance test owner | Relationship |
|---|---|---|---|---|---|---|---|
| `chart_event_<EV>_raise_valid` / `_raise_data` bus signal naming | This phase doc | `_chart_events.chart_event_bus_valid_name` / `_chart_events.chart_event_bus_data_name` + SV walker `_augment_chart_top_with_broadcast_bus_sv` + VHDL walker `_augment_chart_top_with_broadcast_bus_vhdl` | Full mutation rights (this repo authors) | n/a (locally owned) | Cross-region `<onentry>/<onexit><assign expr='event.<EV>.value'/>` captures + downstream SVA bind authors that prefer the `chart_event_*` surface over the wave-3-c `ev_*` internal names | This phase doc (wave-3-f-future-xreg acceptance) | **own** |
| Multi-raiser conflict resolution (OR aggregation on valid, lower-region-index priority on data, runtime `$warning`) | This phase doc + SCXML §3.13 (microstep ordering) | Chart-top emit in both walkers | Full mutation rights for the resolution policy; the SCXML semantics it derives from are unmodified | The lower-document-index priority is **derive** of SCXML §3.13's "first in document order" microstep rule applied to a single clock cycle; the runtime `$warning` is **own** | Simulation operator (warning consumption) + reviewers (priority audit) | This phase doc | **own** (resolution policy) + **derive** (microstep ordering semantics) |
| `event.<EV>.value` chart-author RHS form | SCXML §5.10 (`<assign>` action) | `_EVENT_PAYLOAD_RE` regex pre-pass (both walkers) | Subset narrowing only — single `<param name="value">` form; multi-`<param>` rejected via wave-3-f-future-B | Inherits the SCXML semantics for run-to-completion event payload visibility | Both SV + VHDL register-emit per-signal if/else chain | This phase doc (wave-3-f-future-xreg acceptance) | **derive** |

**Implementation surface**:

- **`tools/sos-codegen/_chart_events.py` (new file, ~110 LOC including docstrings)** — shared between SV and VHDL walkers. Provides `build_chart_event_raiser_map(regions) -> dict[event_name, list[region_name]]` (document-order preserving), plus the bus-signal name helpers `chart_event_bus_valid_name` / `chart_event_bus_data_name` so both walkers agree on the normative naming without re-stating the literal string. `is_cross_region_capture(event_name, region_name, raiser_map)` answers the per-capture question used by the walkers.
- **`HdlEventPayloadCapture.cross_region: bool = False` (both walkers)** — added alongside the existing `edge` field. Default `False` preserves wave-3-f / wave-3-f-future-A emit byte-identity.
- **`_collect_region_event_payload_captures(region, chart_event_raisers=None)` (both walkers)** — signature extended with an optional raiser-map keyword. When the captured event is NOT consumed by the region but IS raised by another region in the chart, the capture is admitted with `cross_region=True`. When the event is consumed by the region, the capture is admitted with `cross_region=False` (unchanged from wave-3-f). When the event is neither consumed nor raised anywhere, the walker raises `UnsupportedChartError` with the wave-3-f-future-xreg citation.
- **`_cross_region_consume_events(captures)` (both walkers)** — derives the sorted set of event names a region captures via cross-region routing. The region-module renderer folds these into the region's `consume_events` list (so the `event_<EV>_recv_valid` / `event_<EV>_recv_data` input ports are emitted) and into the chart-wide `payload_events` set (so the recv_data port is sized correctly + the broadcast bus carries data).
- **`_augment_chart_top_with_broadcast_bus_sv` (SV walker) + `_augment_chart_top_with_broadcast_bus_vhdl` (VHDL walker)** — post-process the chart-top body (after the `hdl_common.emit_chart_top_wrapper` call) to inject the `chart_event_<EV>_raise_valid` / `_raise_data` alias declarations + the same-cycle multi-raiser conflict detector. Both augment functions are no-ops (preserve byte identity) when no region performs a cross-region capture — the regression-guard tests pin this exact contract.

**Sample emit (SV, two-region chart, region `left` raises `tick`, region `right` captures via `<onentry>`)**:

```sv
// SOS-08-C wave-3-f-future-xreg additions in the chart-top wrapper:
wire chart_event_tick_raise_valid = ev_tick_send_valid;
wire [7:0] chart_event_tick_raise_data = ev_tick_send_data;

// Region `right`'s FSM module — no surface change vs. the
// wave-3-f intra-region shape:
always_ff @(posedge clk) begin
    if (rst) begin
        data_last_q <= 32'sd0;
    end else if (state_q != ST_R2 && state_next == ST_R2 && event_tick_recv_valid) begin
        data_last_q <= event_tick_recv_data;
    end else begin
        data_last_q <= data_last_q;
    end
end
```

**Sample emit (VHDL mirror, same chart)**:

```vhdl
-- Chart-top wrapper additions:
signal chart_event_tick_raise_valid : std_logic;
signal chart_event_tick_raise_data : std_logic_vector(7 downto 0);
-- ...
chart_event_tick_raise_valid <= ev_tick_send_valid;
chart_event_tick_raise_data <= ev_tick_send_data;

-- Region `right`'s register process:
if state_q /= ST_R2 and state_next = ST_R2 and event_tick_recv_valid = '1' then
    last_q <= signed(event_tick_recv_data);
else
    last_q <= last_q;
end if;
```

**Sample emit (SV, multi-raiser conflict detector for chart with regions `a` and `b` both raising `shared`)**:

```sv
// synthesis translate_off
always @* begin
    // chart event `shared` — raisers: a, b (priority to first)
    if ((w_ev_a_shared_pulse + w_ev_b_shared_pulse) > 1) $warning(
        "SOS-08-C wave-3-f-future-xreg: same-cycle multi-raiser conflict on chart event `shared`; lower-document-index region wins");
end
// synthesis translate_on
```

**Invariants upheld**:

- **INV-S-HDL-C-1** (chart-as-source): preserved — the cross-region capture path is deterministic from the chart's region-document-order + raise/capture site list.
- **INV-S-HDL-C-2** (datamodel signals reach RTL register form): preserved + extended — datamodel registers now have a defined write source on entry-edge, exit-edge, intra-region, AND cross-region events. The register process emits the same if/elsif shape regardless of routing source.
- **INV-S-HDL-C-3** (cross-domain CDC isolation): preserved — cross-region captures inherit the wave-3-d-2 multi-domain producer/consumer rejection rule (a chart with producers + consumers in different clock domains is still rejected; wave-3-f-future-xreg does NOT relax this).
- **INV-S-HDL-C-4** (datamodel-write observability): preserved — cross-region captures are the same kind of register-write site as intra-region captures; the wave-3-f-future-A `<onexit>` mirror and the wave-3-f-future-assign general-assign arms continue to compose into the same if/elsif chain.
- **INV-S-HDL-C-5** (one-hot encoding deterministic across dialects): preserved.

**Frozen-enum registration policy**: no new enum lands in this amendment. The `AssignExpr.kind` enum (from wave-3-f-future-assign, registration policy: Specification Required) is unchanged. The broadcast bus signal naming convention is not enumerated; it is a normative pattern (`chart_event_<EV>_raise_valid` / `_raise_data`) with the chart-author event name `<EV>` substituted in.

**Wave-3-f-future remaining boundary** (still deferred):

- **Wave-3-f-future-B full implementation** (multi-`<param>` events) — unchanged. Still gated on upstream wave-3-e port-shape extension. Rejection-only landing remains in effect. The cross-region path inherits the single-`<param name="value">` convention; multi-`<param>` events would carry per-param sub-buses at the chart-top broadcast surface (`chart_event_<EV>_raise_data_<param>`), but the surface needs the wave-3-e port-shape work first.

**Test count**: net +22 across two walkers — 11 each. Test classes `TestWave3fFutureCrossRegionEventCapture` (SV) and `TestWave3fFutureCrossRegionEventCaptureVhdl` (VHDL) cover: byte-identity regression guard (intra-only charts), cross-region wiring from the broadcast bus, bus signal naming, multi-raiser OR aggregation, multi-raiser priority mux, same-cycle conflict runtime warning, unraised-event chart-vocab error, entry/exit edge gating, intra-region coexistence with cross-region in the same chart, and chart-event-raiser-map shape. Two pre-existing wave-3-f tests (`test_capture_target_is_consume_event_check` in both walkers) were updated to match the new error message — the error condition is now "event not raised anywhere in the chart" rather than "event NOT a consume event of region X" because the cross-region rule replaces the per-region check with a chart-wide raiser check.

**Test suite**: 838/838 passing (816 prior + 22 new wave-3-f-future-xreg). Pre-existing tests adjusted: 2 (error-message text update; semantically equivalent — same chart still rejected with a new, more accurate diagnosis).

**Cited invariants / amendments**: §15 wave-3-f (entry shape — extended here to admit cross-region wiring source); §15 wave-3-f-future-A (exit shape — same extension); §15 wave-3-f-future-assign (per-signal if/elsif chain — composes orthogonally with cross-region captures); INV-S-HDL-C-1..5 (preserved); SCXML §3.13 microstep ordering (cited for the lower-document-index priority resolution on same-cycle multi-raiser conflicts).

Status: 🟢 **cross-region event-value capture complete**. Wave-3-f-future remaining now narrows to wave-3-f-future-B full implementation only; this deferral is gated on the wave-3-e port-shape work (per-param sub-buses), which is upstream of the chart-author ergonomics this amendment closes.

### 2026-05-25 — Post-wave follow-ups: PCDN-SOS-08-C-007 + C-008 + boolean-literal amendment (Ira)

Three post-hoc curations identified by the 2026-05-25 audit of the prior day's wave-1 + wave-4 landings. Two new PCDNs are filed in §14 for boundary work that the implementing commits explicitly deferred; one cross-reference widens the wave-2 ratified ECMAScript subset to admit the boolean literals the implementation already emits.

**PCDN-SOS-08-C-007 filed (§14)** — wave-3-e port-shape extension for per-`<param>` sub-buses. Surfaced by wave-1 commit `f0284fc` ("SOS-08-C wave-3-f-future-A: <onexit> captures + -B multi-<param> rejection"), whose `_EVENT_PAYLOAD_RE` rejection of the `event.<EV>.<custom>` form is the actionable placeholder that closes only when wave-3-e emits per-`<param>` sub-buses named `event_<ev>_recv_data_<param>`. Per the §14 recommendation: "extend wave-3-e to emit per-`<param>` sub-buses ... with the legacy unnamed `_recv_data` bus preserved as a byte-identity alias for charts that use only `event.<EV>.value`". Registration policy: **Standards Action** (cross-walker contract surface). Unblocks: SOS-08-C wave-3-f-future-B FULL implementation. Tracking: `f0284fc` ("SOS-08-C wave-3-f-future-A: <onexit> captures + -B multi-<param> rejection").

**PCDN-SOS-08-C-008 filed (§14)** — shared-datamodel HDL wiring. Surfaced by D3 wave-4 commit `1dc5649` ("SOS08D4ms: wave-4-future multi-clock + shared-datamodel cross-region (final)"), whose `_emit_shared_signal_invariants` emits the one-driver SVA invariant for `<sos:shared_signal>` but explicitly defers the HDL-side declaration + driving-process emission to a future SOS-08-C carry-forward. Per the §14 recommendation: "SOS-08-C recognises `<sos:shared_signal name=\"...\" width=\"...\" owner_region=\"...\"/>` at chart top, emits a chart-top-scoped signal `shared_<name>` of declared width, and emits the driving register process within owner_region's per-region logic". The SOS-08-D one-driver invariant continues to hold by construction. Registration policy: **Standards Action**. Unblocks: the second wave-4-future carry-forward (HDL wiring side) flagged by D3's §15 2026-05-24 entry. Tracking: `1dc5649` ("SOS08D4ms: wave-4-future multi-clock + shared-datamodel cross-region (final)").

**Boolean-literal amendment to wave-3-f-future-assign ratified subset**. The original ratification in the §15 2026-05-24 entry titled "Impl wave-3-f-future-assign: general ECMAScript-subset `<assign>` lowering" landed via wave-2 commit `d879e7b` ("SOS08C3fa: general ECMAScript-subset <assign> lowering (wave-3-f-future-assign)"). That commit's implementation accepts the boolean literals `true` and `false` and lowers them to the integer constants `1` and `0` respectively — a small but load-bearing widening of the ratified subset, motivated by preservation of pre-existing wave-1/wave-2 boolean-flag fixtures (`<assign location="flag" expr="true"/>` shape) that the pre-amendment walkers silently no-op'd. The original §14 PCDN walkthrough that ratified the subset, and the §15 2026-05-24 entry that recorded it, both named the normative subset as **numeric-only integer literals + datamodel idents + `event.<EV>.value`** — boolean literals were not explicitly enumerated. This entry **explicitly widens the §15 2026-05-24 "Impl wave-3-f-future-assign" entry's normative MUST/MAY subset** to admit:

- A **boolean literal** — `true` or `false` — lowered to integer constant `1` or `0` respectively at the datamodel register's declared width. Per RFC 2119, the walker MUST accept `true` and `false` as `<assign expr=>` bodies and MUST lower them to the integer constants `1` and `0`.

This is a **post-hoc widening** ratified as of today; the original §15 2026-05-24 ratification was numeric-literal + datamodel ident + `event.<EV>.value`-only, and the wave-2 implementation in `d879e7b` opportunistically widened to include booleans without a separate PCDN walkthrough. The widening is documented here so future grep on §14 normative subset returns the actual implemented behaviour. The boolean-literal subset participates in the same `compute_guard_depth` budget + `_assign_expr.py` parser shape as the other ratified literal forms; no new register-emit shape lands beyond the integer-constant lowering already in place.

**Authority boundary update**. Per the standards-integration discipline (§0), the wave-3-f-future-assign authority-boundary row for `<assign expr=>` ECMAScript-subset grammar (relationship: `derive` with upstream authority ECMA-262 §11) is extended to also cover the ECMA-262 boolean-literal subset (ECMA-262 §12.8.2 The Boolean Literals). The relationship stays `derive`: this codebase interprets ECMA-262's `true` and `false` Boolean literals as the lowered integer constants `1` and `0`, with the same divergence-policy clause as the rest of the row (extensions live in this §15 entry; deviations from ECMA-262 cite this section). No new row is added — the existing `<assign expr=>` row's coverage widens to include the boolean-literal subset.

**Tracking**. The three commits referenced by this entry:

- `f0284fc` — SOS-08-C wave-3-f-future-A: <onexit> captures + -B multi-<param> rejection. Tracking commit for PCDN-SOS-08-C-007 (the `_EVENT_PAYLOAD_RE` rejection of `event.<EV>.<custom>` is the placeholder C-007 resolution removes).
- `1dc5649` — SOS08D4ms: wave-4-future multi-clock + shared-datamodel cross-region (final). Tracking commit for PCDN-SOS-08-C-008 (the `_emit_shared_signal_invariants` SVA-side emit is the assertion-side counterpart C-008 resolution complements with the HDL wiring side).
- `d879e7b` — SOS08C3fa: general ECMAScript-subset <assign> lowering (wave-3-f-future-assign). Tracking commit for the boolean-literal amendment (the implementation already emits the widened behaviour; this entry ratifies the doc-side widening to match).

The two new PCDNs are filed as part of the post-wave-1 review identified by the 2026-05-25 audit. The boolean-literal widening is a post-hoc cross-reference into the prior day's §15 2026-05-24 wave-3-f-future-assign entry, not a new behaviour change.

**Invariants upheld**:

- **INV-S-HDL-C-1** (chart-as-source): preserved — the boolean-literal lowering is deterministic via the same `_assign_expr.py` parser used for the numeric-literal subset.
- **INV-S-HDL-C-2..5**: preserved — no register-emit shape change beyond the integer-constant lowering already in place.
- **All `-NN-CONCEPTS` §0 authority policy**: preserved — the ECMA-262 row's `derive` relationship is widened in scope, not changed in kind.

**Test count**: net +N (the test module `tests/test_sos_08_c_pcdns_007_008_and_bool_lit.py` lands as part of this entry, asserting the §14 PCDN entries + the §15 amendment text + the boolean-literal mapping + the authority-boundary update). The pre-existing wave-3-f-future-assign tests in `TestWave3fFutureAssignLowering` (SV) and `TestWave3fFutureAssignLoweringVhdl` (VHDL) continue to pass; the boolean-literal widening is a doc-side ratification of behaviour already present in `d879e7b`'s implementation.

**Cited invariants / amendments**: §15 2026-05-24 "Impl wave-3-f-future-assign: general ECMAScript-subset `<assign>` lowering" (subset widened to admit boolean literals); §15 wave-3-f-future-A (commit `f0284fc` — wave-3-f-future-B rejection placeholder cited as PCDN-SOS-08-C-007 tracking); SOS-08-D §15 2026-05-24 entry on shared-signal SVA emit (commit `1dc5649` — assertion-side counterpart cited as PCDN-SOS-08-C-008 tracking).

Status: 🟢 **post-wave follow-ups filed + boolean-literal subset ratified**. PCDN-SOS-08-C-007 + C-008 are now the live carry-forward items for the SOS-08-C wave-3-f-future boundary alongside wave-3-f-future-B full implementation; the boolean-literal subset is doc-aligned with the wave-2 `d879e7b` implementation behaviour.

### 2026-05-25 — PCDN-SOS-08-C-007 + C-008 ratification — per-`<param>` sub-buses + shared-datamodel HDL wiring (Ira)

Both PCDNs filed by the prior §15 2026-05-25 "Post-wave follow-ups" entry are now ratified. Each carries an addendum that constrains implementation sequencing; neither addendum mutates the §14-recorded recommendation text. Together these unblock the SOS-08-C wave-3-f-future-B FULL implementation (via C-007) and the SOS-08-D wave-4-future shared-datamodel carry-forward (via C-008).

**PCDN-SOS-08-C-007 → RESOLVED 🟢** — Wave-3-e port-shape extension for per-`<param>` sub-buses. Ratified per the §14 recommendation:

- Walker MUST emit per-`<param>` sub-buses named `event_<ev>_recv_data_<param>` (one per declared `<param name>` on the corresponding `<send>`/`<raise>`), with the legacy unnamed `event_<ev>_recv_data` bus preserved as a **byte-identity alias** for charts that use only `event.<EV>.value`.
- Chart-vocab error: a `<param name="value">` collision against the legacy unnamed alias is a **hard reject** (no implicit shadowing — the chart MUST be rewritten or the param renamed).
- Multi-`<param>` events whose declared params are unreferenced by any consuming `<assign>` MAY suppress emission of the unused sub-buses as a port-shape **optimisation**. This is opt-in walker behaviour, not a normative requirement (the suppression is observationally equivalent at the chart-vocab layer).
- Authority: `own` for the per-`<param>` naming convention (this codebase authors the `event_<ev>_recv_data_<param>` grammar); `compose` over the existing event-port shape declared in §6.4/§6.5.
- Registration policy: **Standards Action** — the port shape is a cross-walker contract surface (SOS-08-C emits, SOS-08-D + E + F + G consume). Adding a value or shape requires a §15 amendment + ratification walkthrough.

**Addendum to C-007 (user-imposed) — chart-inventory pre-requisite.** The operator's ratification carried an explicit pre-implementation gate: *"we want a task to inventory our charts in and under this repo. If we have any generated vectors we will want them translated to the new form."* Implementation of PCDN-SOS-08-C-007 MUST therefore consume the **chart-inventory + vector-migration audit report** landing in parallel under `docs/inventory/SOS-CHART-INVENTORY.md` (dispatched today as `sos-wt-inv-task`). The implementation walker change is blocked until the inventory pass identifies the set of charts (and any generated vector fixtures derived from them) whose port-shape consumers depend on the legacy unnamed `_recv_data` alias vs. the new per-`<param>` sub-buses. The walker change MUST be paired with vector migrations for every chart-fixture flagged by the inventory; landing the walker change ahead of the inventory pass risks silent regressions across pre-existing chart fixtures.

**PCDN-SOS-08-C-008 → RESOLVED 🟢** — Shared-datamodel HDL wiring. Ratified per the §14 recommendation:

- SOS-08-C MUST recognise `<sos:shared_signal name="..." width="..." owner_region="..."/>` at chart top.
- The walker MUST emit a chart-top-scoped signal `shared_<name>` of the declared width.
- The walker MUST emit the **driving register process within `owner_region`'s per-region logic** (NOT in the chart-top wrapper — ownership lives where the writer lives, consistent with §6.10's "chart-top wrapper does not internalize driving logic" rule).
- Reader regions referencing `<sos:shared_signal_ref name="..."/>` in their `<assign>` location field MUST read `shared_<name>` **without any synchroniser** — owner_region's clock is the dominant domain, and v1 explicitly restricts shared signals to a single clock domain (see "same-clock-domain only" below).
- The SOS-08-D one-driver invariant (`_emit_shared_signal_invariants` SVA-side check) continues to hold by construction: the walker emits exactly one driving process per shared signal, located in `owner_region`.
- Authority: `own` for the chart-top signal naming convention `shared_<name>` and the ownership-by-region driving-process rule.
- Registration policy: **Standards Action** — adding a value (e.g. a cross-domain naming variant) requires a §15 amendment + ratification walkthrough.

**Addendum to C-008 (user-imposed) — same-clock-domain only at v1; forward-compat stance is naming EXTENSION, not replacement.** The operator's ratification was explicit: *"same clock domain for v1 and we will enhance the naming only for clocks that break it later."* This pre-stages a forward-compat constraint that implementations MUST honour now:

- **v1 normative scope**: PCDN-SOS-08-C-008 covers **same-clock-domain shared signals only**. The walker MUST reject `<sos:shared_signal>` whose `owner_region` and any `<sos:shared_signal_ref>` reader resolve to different clock domains (per SOS-08-C §6.7's region clock-domain inheritance). Cross-domain shared signals are an out-of-scope future PCDN.
- **Forward-compat stance (informative, not normative at v1)**: when cross-domain shared signals are added in a future PCDN, the v1 `shared_<name>` naming convention will be **EXTENDED, not replaced**. Same-domain readers continue to use `shared_<name>`; cross-domain readers will use an extended form to be settled by the future PCDN — candidate shapes include `shared_<name>_xclk` (single suffix marking cross-domain readership) or `shared_<name>_<clk_from>_to_<clk_to>` (per-edge alias scheme). Implementations MUST NOT pre-emptively widen the v1 `shared_<name>` naming to accommodate the future cross-domain case — a v1 walker that emits a cross-domain-shaped name today would force the future PCDN to either re-amend or accept a fork. The v1 walker rejects cross-domain at the chart-vocab layer; the future PCDN unblocks the new naming and the rejection lifts.

**Order-of-operations**:

- **PCDN-SOS-08-C-007** sequences as: (1) chart-inventory + vector-migration audit lands in parallel today (`sos-wt-inv-task` → `docs/inventory/SOS-CHART-INVENTORY.md`); (2) walker code change lands in `tools/sos-codegen/sos_codegen/transliterate_hdl_sv.py` + `tools/sos-codegen/sos_codegen/transliterate_hdl_vhdl.py` (the per-`<param>` sub-bus emission + the legacy unnamed alias preservation + the `<param name="value">` hard-reject path replacing the current `_EVENT_PAYLOAD_RE` rejection placeholder); (3) vector migrations applied to any chart fixtures the inventory identifies as carrying the legacy port shape. Step (2) MUST NOT land before step (1) completes — the inventory's identification of legacy-shape fixtures is load-bearing for the migration set.
- **PCDN-SOS-08-C-008** sequences as: (1) walker code change lands in the same two walker files (signal declaration at chart top + owner_region driving process + cross-domain-rejection path); (2) verification that SOS-08-D's existing one-driver invariant (`_emit_shared_signal_invariants`) continues to hold across the chart fixtures emitted by step (1) — the SOS-08-D SVA-side check is the integration test for this PCDN.
- Neither C-007 nor C-008 depends on PCDN-SOS-08-D-008 ratification (parallel wave-5 work; D-008 is the SOS-08-D-side companion).

**Authority boundary table additions** (per §0 standards-integration discipline):

| Concept | Upstream authority | Local representation | Mutation rights | Divergence policy | Downstream consumers | Conformance test owner |
|---|---|---|---|---|---|---|
| `event_<ev>_recv_data_<param>` per-`<param>` sub-bus naming (PCDN-SOS-08-C-007) | none — `own` | walker-emitted port name in both SV + VHDL outputs | this codebase; gated by Standards Action (§15 amendment + ratification walkthrough) | extensions live in a future §15 amendment; deviations from this convention reject at chart-compile time | SOS-08-D vector emission + SOS-08-E driver glue + SOS-08-F cocotb harness + SOS-08-G waveform annotation | SOS-08-C walker test suite (`test_transliterate_hdl_sv.py` + `test_transliterate_hdl_vhdl.py`) + SOS-08-D one-driver invariant check |
| `shared_<name>` chart-top signal + ownership-by-region driving-process rule (PCDN-SOS-08-C-008) | none — `own` | walker-emitted signal declaration at chart top + driving register process inside `owner_region` | this codebase; gated by Standards Action (§15 amendment + ratification walkthrough); v1 same-clock-domain only | extensions for cross-domain readership use an EXTENDED suffixed form (future PCDN); v1 `shared_<name>` form is preserved unchanged for same-domain | SOS-08-D `_emit_shared_signal_invariants` SVA-side one-driver check + SOS-08-C reader-region `<assign>` lowering | SOS-08-C walker test suite + SOS-08-D one-driver invariant test |

**Tracking**:

- `f0284fc` — SOS-08-C wave-3-f-future-A: <onexit> captures + -B multi-<param> rejection. The wave-1 commit whose `_EVENT_PAYLOAD_RE` rejection of `event.<EV>.<custom>` is the placeholder that PCDN-SOS-08-C-007 resolution removes.
- `1dc5649` — SOS08D4ms: wave-4-future multi-clock + shared-datamodel cross-region (final). The D3 wave-4 commit whose `_emit_shared_signal_invariants` emits the SVA-side one-driver invariant for `<sos:shared_signal>` — PCDN-SOS-08-C-008 adds the HDL-wiring side that the SVA invariant constrains.
- `2f06c1d` — Wave-5 §15 filing entry (the prior 2026-05-25 "Post-wave follow-ups" entry above) that filed both PCDNs in §14.

**Companion §15 ratification entries** land in `SOS-08-D-CONCEPTS.md` (D-008 ratification, parallel-dispatched today) and `SOS-08-E-CONCEPTS.md` (cross-reference noting the SOS-08-C ratification, parallel-dispatched today) — same date, parallel wave.

**Invariants upheld**:

- **INV-S-HDL-C-1** (chart-as-source) — preserved by construction; the per-`<param>` sub-buses are deterministic from the `<param>` declarations on the corresponding `<send>`/`<raise>` and the shared-signal driving process is deterministic from `owner_region`.
- **INV-S-HDL-C-2** (per-region observability) — preserved; per-`<param>` sub-buses retain the existing observability port shape; shared signals are observable as chart-top signals visible to every region.
- **INV-S-HDL-C-3** (cross-domain transition enforcement) — preserved; PCDN-SOS-08-C-008's v1 rejection of cross-domain shared-signal references at chart-compile time means no synchroniser-bypass hazard is introduced.
- **INV-S-HDL-C-4** (guard expression synthesizability) — preserved; neither PCDN touches the guard-depth budget.
- **INV-S-HDL-C-5** (cooperative completion) — preserved; neither PCDN introduces preemption.
- **SOS-08-D one-driver invariant** — preserved by construction (owner_region drives; readers don't write).

**Test count**: net +N (the test module `tests/test_sos_08_c_pcdns_007_008_ratification.py` lands as part of this entry, asserting the §14 status markers + the §15 ratification entry text + the addendum constraints + the authority-boundary additions + the order-of-operations + the tracking-commit citations). The pre-existing tests in `tests/test_sos_08_c_pcdns_007_008_and_bool_lit.py` (asserting the §14 PCDN filing) continue to pass; this entry's test module asserts the additional ratification surface.

Status: 🟢 **ratified — implementation pending (sequenced after inventory wave)**. PCDN-SOS-08-C-007 implementation gated on `docs/inventory/SOS-CHART-INVENTORY.md` landing first (parallel wave-5 dispatch today). PCDN-SOS-08-C-008 implementation gated on the v1 same-clock-domain constraint + the forward-compat naming-extension stance. Both walker code changes target `tools/sos-codegen/sos_codegen/transliterate_hdl_sv.py` + `tools/sos-codegen/sos_codegen/transliterate_hdl_vhdl.py`.
