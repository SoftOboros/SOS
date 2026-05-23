# SOS-08-F — UVM sequences only (stimulus plug-in for customer-owned UVM environments)

**Status:** 🟢 **ratified 2026-05-23** (see §15).

## 0. Authority policy

This phase doc is the **UVM-sequence emission** sub-phase under the SOS-08 umbrella (`SOS-08-CONCEPTS.md`, ratified 2026-05-23). The umbrella's §6 SOS-08-F row and EOQ-003-ROADMAP resolution name the strategic positioning load-bearing in this doc: **SOS does NOT emit full UVM testbenches at v1. Only UVM-compatible sequences (stimulus portion); customer wraps in their own UVM scaffolding. 10% of engineering for 80% of adoption value.** This sub-phase takes that framing as input and produces the concrete sequence-emission contract.

Per the parent CLAUDE.md "Spec-Before-Code Planning Discipline / Phase document shape":

- **Normative** sections of this doc: §3 glossary, §4 source-of-truth map, §5 frozen decisions (scope discipline, sequence-item ABI, UVM version target, no-SVA-binding stance), §6 sequence-emission contract, §7 cross-sub-phase invariants (INV-S-HDL-F-*), §8 standards integration matrix additions, §12 acceptance checklist.
- **Informative** sections: §1 purpose, §2 problem statement, §11 non-goals, §15 change log.
- All keywords MUST, MUST NOT, SHALL, SHOULD, SHOULD NOT, MAY are interpreted per RFC 2119 / RFC 8174 when capitalised.

This doc cites:

- `SOS-07-CONCEPTS.md` §6 for cross-phase invariants `INV-SOS-A` through `INV-SOS-H` — neither set is re-derived;
- `SOS-07-CONCEPTS.md` §7 for the AuthorityRelationship matrix — UVM appears in that matrix as **derive** (this is the load-bearing position for SOS-08-F);
- `SOS-08-CONCEPTS.md` §7 for cross-sub-phase invariants `INV-S-HDL-1` through `INV-S-HDL-5`;
- `SOS-08-D-CONCEPTS.md` (sibling sub-phase, forthcoming) for the cocotb + SVA primary vector path;
- `SOS-08-E-CONCEPTS.md` (sibling sub-phase, forthcoming) for the SystemVerilog testbench LCD path.

The sibling sub-phases (SOS-08-D, SOS-08-E) emit SVA bind files alongside their primary test artifacts; SOS-08-F deliberately does NOT. The rationale is normative to this doc (§5.4).

## 1. Purpose

To freeze the UVM-sequence emission contract: which UVM classes the codegen emits, which it does NOT emit, what the customer integration surface looks like, and how chart-vocabulary traceability per INV-SOS-H and INV-S-HDL-5 survives the boundary into the customer's UVM environment.

The strategic positioning — **10% of engineering for 80% of adoption value** — is the load-bearing claim. Authoring a full UVM testbench emitter (env, scoreboard, agent hierarchy, factory registrations, test classes, sequencer/driver pairs per interface) is a multi-quarter undertaking with shallow per-customer reuse: every enterprise UVM shop has house conventions on env structure, factory overrides, configuration databases, and reporting that fight a generic emitter. Sequences are the **stimulus** layer that lives above all of that house variation — every UVM env has a sequencer accepting `uvm_sequence_item` transactions, regardless of whose env it is. Emit the stimulus; let the customer integrate it into whatever scaffolding they already own.

That positioning is the doc's reason for existence; §5 freezes the decisions that make it executable.

## 2. Problem statement

Three observations from the SOS-08 umbrella and the broader HDL-flow landscape converge on this sub-phase:

1. **UVM is the dominant verification methodology in enterprise HDL.** Per the SOS-07 §7 AuthorityRelationship matrix, UVM (Accellera) is the upstream authority; SOS's relationship is **derive** (consume the grammar, produce conformant artifacts, do not own the grammar). Customers using UVM are committed to their existing env, scoreboard, and reporting infrastructure; a SOS-generated full env would require the customer to abandon or duplicate what they already have.

2. **Sequences are the universal stimulus interface across UVM environments.** Every UVM env has a sequencer; every sequencer accepts `uvm_sequence_item` transactions; every sequence-level test invokes `start_sequence` against a sequencer. The sequence layer is the **only** UVM layer that is invariant across enterprise house conventions. Authoring a sequence emitter is the maximum-reuse, minimum-customer-disruption integration point.

3. **The full-UVM emitter would re-derive every adjacent sub-phase's work.** SOS-08-D emits cocotb tests + SVA bind files. SOS-08-E emits a class-based SystemVerilog testbench + the same SVA bind files. Both already exercise the chart's bounded-reachability vectors and emit chart-vocabulary assertion failures per INV-SOS-H. A full SOS-08-F UVM testbench would duplicate that work in UVM dialect — same vectors, same assertions, different scaffolding language. The 10/80 framing rejects that duplication: emit only the layer customers cannot trivially author themselves (sequences from chart vectors), and let SVA / scoreboard / reporting come from the customer's existing env (SOS-08-D and SOS-08-E ship the SVA artifacts; SOS-08-F plugs into the customer's existing assertion-handling).

The combination — UVM is dominant; sequences are the invariant interface; full-env emission would duplicate adjacent sub-phases — drives the scope discipline frozen in §5.1.

## 3. Canonical glossary

Terms normative within SOS-08-F+. Authority relationships per §8.

| Term | Definition |
|---|---|
| **UVM sequence** | A `uvm_sequence` subclass whose `body()` task generates `uvm_sequence_item` instances and sends them to a sequencer via `start_item` / `finish_item`. As defined by Accellera UVM 1.2 (IEEE 1800.2-2017); used without modification per AuthorityRelationship=derive. SOS-08-F emits one `uvm_sequence` subclass per chart event family. |
| **`uvm_sequence_item`** | A UVM transaction class extending `uvm_sequence_item`, conveying one stimulus event to a sequencer. As defined by Accellera UVM; used without modification. SOS-08-F emits the baseline `sos_seq_item` class (§6.2) extending this; customer drivers consume `sos_seq_item` instances. |
| **chart event family** | A namespaced group of chart events sharing a transaction shape, e.g. `task.*` (task lifecycle), `sem.*` (semaphore operations), `queue.*` (queue operations), `timer.*` (timer operations), `event.*` (event-flag operations). SOS-08-F emits one `uvm_sequence` subclass per family. Family enumeration is **PCDN-SOS-08-F-002** at draft. |
| **stimulus plug-in** | The integration surface between SOS-emitted sequences and the customer's UVM environment. Customer owns the sequencer, driver, env, scoreboard, factory registrations, and test classes; SOS owns the sequences + the baseline `sos_seq_item` transaction. The customer's driver translates `sos_seq_item` into DUT-pin-level signal activity in whatever protocol the customer's design uses. |
| **customer-owned UVM environment** | The complete UVM scaffolding (env, agent, sequencer, driver, monitor, scoreboard, factory) that the customer authors and maintains. SOS-08-F does NOT emit any of this; the customer's env imports SOS's sequence library + `sos_seq_item` and connects the sequences to its sequencer per §6.5. |
| **bounded-reachability vector IR** | The chart's bounded-reachability output in canonical JSONL form per SOS-08 PCDN-009 resolution (one event per line; chart-vocabulary metadata per INV-S-HDL-5). The SOS-08-F sequence emitter consumes the same vector IR that SOS-08-D and SOS-08-E consume; the three emitters produce different scaffolding around the same underlying stimulus sequence. |
| **chart-vocabulary failure message** | A UVM `uvm_error` / `uvm_fatal` / `uvm_warning` call whose message string names the chart state, transition, or invariant that the violation pertains to, per INV-SOS-H. The customer's scoreboard catches the message; the message itself is in chart vocabulary, not RTL-signal vocabulary. |
| **UVM version target** | The Accellera UVM revision SOS-08-F sequences are authored against. Per **PCDN-SOS-08-F-001** at draft, recommended UVM 1.2 (IEEE 1800.2-2017) with forward compatibility to UVM 2.0 (IEEE 1800.2-2020). |

## 4. Source-of-truth map

For every concept this sub-phase touches, **exactly one** location is the canonical authority.

| Concept | Authority |
|---|---|
| UVM grammar (`uvm_sequence`, `uvm_sequence_item`, `uvm_object_utils`, `uvm_error`, `start_item`, `finish_item`, `body()`) | Accellera UVM 1.2 / IEEE 1800.2-2017 (external; AuthorityRelationship=derive per SOS-07 §7) |
| Strategic positioning (sequences-only, 10/80 framing) | `SOS-08-CONCEPTS.md` §6 (umbrella, **mirror** here); EOQ-003-ROADMAP resolution carries forward |
| Chart event family enumeration | **this doc** (§6.1, **pending PCDN-SOS-08-F-002**) |
| Baseline `sos_seq_item` transaction class shape | **this doc** (§6.2, **pending PCDN-SOS-08-F-003**) |
| Per-family `uvm_sequence` subclass shape | **this doc** (§6.3) |
| Customer-integration contract (import + connect surface) | **this doc** (§6.5) |
| Chart-vocabulary failure-message format | **this doc** (§6.6); concretizes INV-SOS-H + INV-S-HDL-5 for the UVM target |
| Bounded-reachability vector IR (JSONL) | `SOS-08-CONCEPTS.md` PCDN-009 resolution; sibling to SOS-08-D + SOS-08-E consumers |
| `uvm_object_utils` registration policy | **this doc** (§5.5, **pending PCDN-SOS-08-F-004**) |
| Pre/post-sequence hook policy | **this doc** (§5.6, **pending PCDN-SOS-08-F-005**) |
| Sequence-library packaging (per-family `.sv` vs single package) | **this doc** (§5.7, **pending PCDN-SOS-08-F-006**) |
| SVA bind files | Sibling SOS-08-D + SOS-08-E (NOT this doc; see §5.4) |
| Cross-phase invariants INV-SOS-A through H | `SOS-07-CONCEPTS.md` §6 (cited, not redefined) |
| Cross-sub-phase invariants INV-S-HDL-1 through 5 | `SOS-08-CONCEPTS.md` §7 (cited, not redefined) |
| Per-sub-phase invariants INV-S-HDL-F-* | **this doc** (§7) |

## 5. Frozen decisions

### 5.1 Scope discipline — sequences only

SOS-08-F emits **UVM sequences only**. Concretely, SOS-08-F MUST NOT emit:

- `uvm_env` subclasses or environment hierarchies of any depth;
- `uvm_scoreboard` subclasses or scoreboard infrastructure;
- `uvm_agent`, `uvm_sequencer`, or `uvm_driver` subclasses (the customer's existing classes consume SOS's `sos_seq_item`);
- `uvm_monitor` subclasses or analysis ports;
- `uvm_test` subclasses or top-level test orchestration;
- Factory registrations beyond the baseline `sos_seq_item` and per-family sequence classes (per PCDN-SOS-08-F-004 resolution);
- `uvm_config_db` writes or env-configuration glue;
- Per-DUT-pin signal-level driver logic — the customer's driver translates `sos_seq_item` to pin-level activity.

SOS-08-F MUST emit:

- One `uvm_sequence` subclass per chart event family (§6.3);
- The baseline `sos_seq_item` transaction class (§6.2);
- A sequence-library packaging artifact (§5.7) so the customer's env can import the sequences via a single `import sos_uvm_seq_pkg::*;`-style line.

The 10/80 framing is the **strategic positioning** these inclusions and exclusions exist to serve. Erosion of the exclusion list (e.g. "we should add a scoreboard, customers always want a scoreboard") rejects the framing and requires a §15 amendment to this doc + cross-phase review.

Frozen-enumeration registration policy: **Standards Action** (modifying the inclusion/exclusion list reorganises the customer-integration contract; cross-phase review needed).

### 5.2 UVM version target

Per **PCDN-SOS-08-F-001** at draft (recommendation: UVM 1.2 (IEEE 1800.2-2017) as the primary target with forward-compatibility to UVM 2.0 (Accellera UVM 2.0 / IEEE 1800.2-2020)). The two versions share the `uvm_sequence` / `uvm_sequence_item` / `uvm_object_utils` / `uvm_error` grammar SOS-08-F depends on; sequences authored to the UVM 1.2 grammar run on UVM 2.0 without modification (forward-compatible).

UVM 1.2 is named primary for these reasons:

- IEEE 1800.2-2017 is the broader deployed base in production enterprise environments at v1 timescale.
- Accellera UVM 1.2 reference implementation is freely available; UVM 2.0 reference is newer with less production-deployment depth.
- UVM 2.0's additions (resource sharing, improved factory mechanics) do not affect the sequences-only emission scope.

Frozen-enumeration registration policy: **Standards Action**.

### 5.3 Baseline `sos_seq_item` shape — universal vs per-family

Per **PCDN-SOS-08-F-003** at draft, the baseline `sos_seq_item` transaction class shape is one of:

- (a) **Universal**: one `sos_seq_item` class with a discriminated `event_family : sos_event_family_e` field and a `payload : sos_event_payload_u` union (or rand-controlled struct) holding family-specific data. Customer's driver branches on `event_family`.
- (b) **Per-family**: one transaction class per family (`sos_task_seq_item`, `sos_sem_seq_item`, `sos_queue_seq_item`, ...) each extending `uvm_sequence_item` directly. Customer's driver handles each transaction type explicitly via UVM polymorphism.

**Recommendation**: (a) universal. The customer's driver gets a single transaction type to integrate; the discriminated-union payload tracks chart events 1:1. Per-family classes increase the sequence-library surface area without reducing the customer's integration cost (the customer still has to register N driver implementations). The universal form is the minimum-customer-touch shape.

Frozen-enumeration registration policy: **Standards Action**.

### 5.4 No SVA-binding in this sub-phase

SOS-08-F does NOT emit SVA bind files. The sibling sub-phases SOS-08-D (cocotb path) and SOS-08-E (SystemVerilog testbench path) both emit SVA bind files alongside their primary test artifacts; those bind files concretize the chart's invariants as SystemVerilog `assert property` constructs that any UVM env can bind concurrently with its own assertion strategy.

The customer's UVM env already has whichever assertion strategy they use (in-line SVA, assertion-based agent, scoreboard-driven property checking). SOS-08-F does NOT impose a binding mechanism — that would force the customer to reconcile SOS-emitted assertions with their existing strategy, which is exactly the kind of house-variation friction the 10/80 framing rejects.

Customers wanting SOS-emitted SVA take it from SOS-08-D or SOS-08-E's emission output (same bind files; both sibling sub-phases produce them). The bind files are sub-phase-independent — they describe chart-invariant properties, not test-scaffolding-specific assertions.

Frozen-enumeration registration policy: **Standards Action**.

### 5.5 `uvm_object_utils` registration

Per **PCDN-SOS-08-F-004** at draft (recommendation: SOS-generated, in the sequence-library package). The `\`uvm_object_utils(sos_<family>_sequence)` and `\`uvm_object_utils(sos_seq_item)` macros are emitted by SOS-08-F as part of the per-family sequence class and the baseline `sos_seq_item` class respectively. Customer does NOT register SOS classes with the factory; the SOS-emitted package registers them. Customer MAY override via standard UVM factory override mechanics (`set_type_override_by_type`) at env-build time if they want a customized sequence subclass — the standard UVM extension point.

Frozen-enumeration registration policy: **Specification Required** (registration mechanic is plumbing, not architecture).

### 5.6 Pre/post-sequence hooks

Per **PCDN-SOS-08-F-005** at draft (recommendation: emit empty virtual hooks for customer override, NOT require subclass override). The emitted per-family `uvm_sequence` subclass exposes:

```systemverilog
virtual task pre_body();
  // Customer override point. Default: no-op.
endtask

virtual task post_body();
  // Customer override point. Default: no-op.
endtask
```

Customer may override via standard UVM extension (subclass the SOS sequence and override `pre_body` / `post_body`). The default no-op behaviour means out-of-the-box SOS sequences run without any customer subclassing — the minimum-friction integration path. Customers needing per-sequence setup (waiting for env quiescence, configuring DUT state, snapshotting scoreboard expectations) override at the standard UVM extension point.

Frozen-enumeration registration policy: **Specification Required**.

### 5.7 Sequence-library packaging

Per **PCDN-SOS-08-F-006** at draft (recommendation: one consolidated SystemVerilog package `sos_uvm_seq_pkg` containing all per-family sequence classes and the baseline `sos_seq_item`, emitted as a single `.sv` file).

The customer imports the package once:

```systemverilog
import sos_uvm_seq_pkg::*;
```

and gets the full SOS sequence library + transaction type in scope. Per-family `.sv` files would force the customer to maintain a per-family import list that grows whenever the chart adds a new event family — a churn surface SOS-08-F should not impose on customers.

Frozen-enumeration registration policy: **Specification Required** (packaging mechanic is plumbing).

## 6. Sequence-emission contract

The codegen tool's UVM-emit path produces three artifacts per chart compilation:

1. **`sos_uvm_seq_pkg.sv`** — the consolidated sequence-library package (per §5.7).
2. **`sos_uvm_seq_pkg.svh`** — header file with type-defs and enums (`sos_event_family_e`, etc.) the customer's driver imports.
3. **`sos_uvm_integration_example.sv`** — informative example showing how a customer connects the SOS sequence library to their existing sequencer. Not normative; documentation artifact only.

The artifacts emit one-for-one with the chart's bounded-reachability vector IR (JSONL per SOS-08 PCDN-009); regenerating from the same chart produces byte-identical artifacts.

### 6.1 Chart event family enumeration

Per **PCDN-SOS-08-F-002** at draft, the v1 chart event families are:

| Family | Chart event prefix | Typical transactions |
|---|---|---|
| `task` | `task.*` | `task.create`, `task.delete`, `task.suspend`, `task.resume`, `task.yield`, `task.set_priority` |
| `sem` | `sem.*` | `sem.create`, `sem.delete`, `sem.take`, `sem.give`, `sem.take_from_isr`, `sem.give_from_isr` |
| `queue` | `queue.*` | `queue.create`, `queue.delete`, `queue.send`, `queue.receive`, `queue.send_from_isr`, `queue.receive_from_isr` |
| `timer` | `timer.*` | `timer.create`, `timer.start`, `timer.stop`, `timer.reset`, `timer.expire` |
| `event` | `event.*` | `event.create`, `event.set`, `event.clear`, `event.wait` |
| `tick` | `tick.*` | `tick.advance`, `tick.set_rate` |

This enumeration mirrors the FreeRTOS / POSIX vocabulary used by SOS-08-B services and the chart-side syscall surface. Adding a new family (e.g. `mutex.*` if a chart introduces a non-binary mutex distinct from `sem.*`) is a §15 amendment to this doc.

Frozen-enumeration registration policy: **Standards Action**.

### 6.2 Baseline `sos_seq_item` transaction class

Per §5.3 resolution (recommendation: universal discriminated union), the baseline `sos_seq_item` shape is:

```systemverilog
typedef enum {
  SOS_FAMILY_TASK,
  SOS_FAMILY_SEM,
  SOS_FAMILY_QUEUE,
  SOS_FAMILY_TIMER,
  SOS_FAMILY_EVENT,
  SOS_FAMILY_TICK
} sos_event_family_e;

class sos_seq_item extends uvm_sequence_item;
  rand sos_event_family_e family;
  rand int                 event_id;       // chart-vocabulary event index within family
  rand bit [63:0]          payload_data;   // family-specific payload (one slot per chart event-data field)
  rand string              chart_state;    // chart-state name where this transaction originates
  rand int                 transition_id;  // chart transition that produced this transaction
  rand int                 invariant_id;   // optional chart invariant tag (0 if unused)

  `uvm_object_utils_begin(sos_seq_item)
    `uvm_field_enum(sos_event_family_e, family, UVM_ALL_ON)
    `uvm_field_int(event_id, UVM_ALL_ON)
    `uvm_field_int(payload_data, UVM_ALL_ON)
    `uvm_field_string(chart_state, UVM_ALL_ON)
    `uvm_field_int(transition_id, UVM_ALL_ON)
    `uvm_field_int(invariant_id, UVM_ALL_ON)
  `uvm_object_utils_end

  function new(string name = "sos_seq_item");
    super.new(name);
  endfunction
endclass
```

The `chart_state` / `transition_id` / `invariant_id` fields carry chart-vocabulary metadata per INV-S-HDL-5 — the customer's scoreboard or assertion handler retrieves these from any caught `sos_seq_item` to produce chart-vocabulary failure messages per §6.6.

The `payload_data` field is 64 bits at v1 — sufficient for every event in the chart event family enumeration (§6.1). The shape may extend to a per-family payload struct at a future amendment if a chart event needs richer payload (e.g. queue message bodies > 64 bits).

### 6.3 Per-family `uvm_sequence` subclass shape

For each chart event family per §6.1, the codegen tool emits one `uvm_sequence` subclass following this template:

```systemverilog
class sos_<family>_sequence extends uvm_sequence #(sos_seq_item);

  `uvm_object_utils(sos_<family>_sequence)

  // Vector IR consumed at sequence construction; one chart-vector per sequence run.
  protected string vector_path;

  function new(string name = "sos_<family>_sequence");
    super.new(name);
  endfunction

  virtual task pre_body();
    // Customer override point. Default: no-op.
  endtask

  virtual task body();
    sos_seq_item tx;
    sos_chart_event_e events[$];  // populated from vector IR
    int i;
    load_vector_ir(vector_path, events);
    foreach (events[i]) begin
      tx = sos_seq_item::type_id::create($sformatf("tx_%0d", i));
      start_item(tx);
      assert(tx.randomize() with {
        family       == SOS_FAMILY_<FAMILY>;
        event_id     == events[i].event_id;
        payload_data == events[i].payload_data;
        chart_state  == events[i].chart_state;
        transition_id == events[i].transition_id;
        invariant_id == events[i].invariant_id;
      });
      finish_item(tx);
    end
  endtask

  virtual task post_body();
    // Customer override point. Default: no-op.
  endtask

endclass
```

The `body()` task is the load-bearing emission: it iterates the chart's bounded-reachability vector for this family and produces one `sos_seq_item` per event. The customer's sequencer receives the items; the customer's driver translates them to DUT-pin activity.

### 6.4 Vector IR consumption

SOS-08-F sequences consume the same JSONL vector IR per SOS-08 PCDN-009 resolution that SOS-08-D and SOS-08-E consume. The IR shape is one event per line:

```jsonl
{"family":"sem","event":"sem.take","sem_id":0,"chart_state":"task_a.waiting_sem","transition":"T42","invariant":"I7"}
{"family":"sem","event":"sem.give","sem_id":0,"chart_state":"task_b.holding_sem","transition":"T43","invariant":"I7"}
```

The per-family sequence's `load_vector_ir(path, events)` task reads the file, filters to lines matching the family, and populates the local `events[$]` queue. The reuse of the same IR across SOS-08-D, SOS-08-E, and SOS-08-F is INV-S-HDL-5's load-bearing benefit: one bounded-reachability output drives three emission paths, and chart-vocabulary metadata travels with each event into every artifact.

### 6.5 Customer-integration contract

The customer's UVM environment integrates the SOS sequence library through these specific extension points:

1. **Package import**: `import sos_uvm_seq_pkg::*;` (per §5.7) brings every per-family sequence class and the baseline `sos_seq_item` into scope.

2. **Sequencer typedef**: customer declares their sequencer as `uvm_sequencer #(sos_seq_item)`, parameterized on the SOS transaction type. The sequencer's class itself is customer-owned.

3. **Driver implementation**: customer authors a `uvm_driver #(sos_seq_item)` subclass whose `run_phase` task fetches `sos_seq_item` instances via `seq_item_port.get_next_item(tx)` and translates each item's `(family, event_id, payload_data)` into DUT-pin-level signal activity in whatever protocol the DUT uses. The driver branches on `tx.family` (or polymorphism if per-family transactions are chosen at PCDN-SOS-08-F-003 resolution).

4. **Sequence start**: at test runtime, the customer's test class instantiates the appropriate SOS sequence (e.g. `sos_sem_sequence seq = sos_sem_sequence::type_id::create("seq");`), assigns the vector IR path (`seq.vector_path = "vectors/sem_chart_bound.jsonl";`), and starts the sequence against the sequencer (`seq.start(env.agent.sequencer);`).

5. **Failure handling**: customer's scoreboard or assertion-handler subscribes to driver / monitor analysis ports as usual; any caught `sos_seq_item` retains its `chart_state` / `transition_id` / `invariant_id` fields, which the customer surfaces in their failure-message formatting (per §6.6).

The five steps are the **entire** customer-side integration surface. Steps 1, 2, and 4 are typically one-line additions to an existing UVM env; step 3 is the only step requiring driver authoring proportional to chart event complexity, and it is the irreducible work of translating chart vocabulary to DUT-pin protocol — exactly the work the customer's existing infrastructure already encapsulates for their other test sources.

### 6.6 Chart-vocabulary failure-message format

Per INV-SOS-H and INV-S-HDL-5, SOS-emitted failure messages render in chart vocabulary. When a SOS-generated sequence detects an expectation violation (via UVM's reporting API), the message MUST include:

- The chart state at which the violation occurred (`tx.chart_state`);
- The transition ID that produced the violating event (`tx.transition_id`);
- The invariant ID, if any, that was violated (`tx.invariant_id`);
- The chart event family and event ID (`tx.family`, `tx.event_id`).

The standard SOS sequence emits failure messages via `uvm_error` / `uvm_fatal` (the customer's scoreboard, monitor, or assertion handler catches these); the message string shape is:

```
[SOS-SEQ] state=task_b.holding_sem transition=T43 invariant=I7 family=sem event=sem.give: <details>
```

Customers MAY override the format via UVM's `set_message_action` mechanics; the SOS-emitted base message guarantees chart vocabulary is present regardless of override. The customer's failure-reporting infrastructure (HTML test reports, JUnit XML emission, CI summary lines) consumes the same message body and surfaces chart vocabulary to the developer reading the test report. This closes the "verification artifact is in chart vocabulary" loop per INV-SOS-H + INV-S-HDL-5.

## 7. Per-sub-phase invariants

In addition to the cross-phase invariants INV-SOS-A through H (from SOS-07) and the cross-sub-phase invariants INV-S-HDL-1 through 5 (from SOS-08), the following invariants are normative within SOS-08-F:

- **INV-S-HDL-F-1 — Sequences only.** SOS-08-F MUST NOT emit any UVM class outside the per-family sequence subclasses and the baseline `sos_seq_item` transaction class. The exclusion list in §5.1 is exhaustive; expanding it requires a §15 amendment. The 10/80 framing is the load-bearing strategic position; this invariant is its mechanical statement.

- **INV-S-HDL-F-2 — Customer owns env, scoreboard, driver, factory.** The customer's UVM environment provides the sequencer, driver, agent, env, scoreboard, monitor, and test classes. SOS-08-F's contract surface is the five-point integration in §6.5; touching any UVM facility beyond that contract would erode the strategic position frozen in INV-S-HDL-F-1.

- **INV-S-HDL-F-3 — Chart-vocabulary traceability survives the UVM boundary.** Every `sos_seq_item` instance MUST carry `chart_state`, `transition_id`, and `invariant_id` fields. SOS-08-F sequences MUST populate these fields from the vector IR per §6.4. Customer failure-reporting MUST be able to surface chart vocabulary per §6.6. Concretizes INV-S-HDL-5 (vector-to-chart traceability for HDL) for the UVM target.

- **INV-S-HDL-F-4 — No SVA emission.** SOS-08-F MUST NOT emit SVA bind files. The sibling SOS-08-D and SOS-08-E sub-phases own SVA emission; the customer's UVM env binds SOS's chart-derived properties from those sibling emissions, not from this sub-phase. Mixing assertion emission into the sequence-only sub-phase would re-introduce the house-variation friction the 10/80 framing avoids.

- **INV-S-HDL-F-5 — UVM version compatibility.** SOS-08-F sequences MUST run on UVM 1.2 (IEEE 1800.2-2017) and UVM 2.0 (IEEE 1800.2-2020). The forward-compatibility guarantee means a customer migrating from UVM 1.2 to UVM 2.0 does NOT need to regenerate SOS sequences; the same emitted `.sv` artifacts run on both. The emitter MUST NOT use UVM features introduced in UVM 2.0 (e.g. UVM 2.0-only resource APIs) that would break the UVM 1.2 path.

## 8. Standards integration matrix additions

This sub-phase consumes the UVM row already declared in SOS-07 §7 and SOS-08 §8 with relationship **derive**. No additions; SOS-08-F is the per-sub-phase application of that derive relationship.

(For completeness: the UVM row in SOS-07 §7 reads "UVM | Accellera | **derive** (sequences only at v1; not full env) | SOS-08-F (forthcoming) | none". This sub-phase is the ratification of that row.)

## 9. Non-goals

This sub-phase does NOT:

- Emit a `uvm_env`, `uvm_agent`, `uvm_scoreboard`, `uvm_test`, `uvm_monitor`, `uvm_driver`, or `uvm_sequencer` subclass. Customer owns those per §5.1 + INV-S-HDL-F-2.
- Emit SVA bind files. Sibling SOS-08-D + SOS-08-E own SVA emission per §5.4 + INV-S-HDL-F-4.
- Emit factory overrides beyond the baseline `sos_seq_item` and per-family sequence registrations. Customer authors any further factory mechanics per their house conventions.
- Provide a UVM-side scoreboard or analysis-port hookup. The customer's existing infrastructure handles this; SOS provides the chart-vocabulary metadata on each transaction.
- Support pyuvm at v1. pyuvm overlay on cocotb is the SOS-08-D path's potential future extension (umbrella PCDN-004 recommendation); SOS-08-F at v1 is pure SystemVerilog UVM.
- Emit constrained-random stimulus beyond the vector IR. The chart's bounded-reachability produces the stimulus set; UVM `randomize() with` constraints in §6.3 are mechanical bindings of the vector IR's values, not stimulus generation in their own right.
- Target UVM-AMS or UVM-MS extensions. Pure-digital UVM only at v1.

## 10. Reconciliation decisions vs adjacent repo primitives

### vs. SOS-08 umbrella §6 (sub-phase scope)

The umbrella's §6 SOS-08-F row reads: "Stimulus emission for plug-in into the customer's existing UVM environment. SOS does NOT emit full UVM testbenches at v1 (per EOQ-003). The customer wraps the SOS sequences in their own UVM scaffolding (sequencer, driver, environment, test classes). 10% of engineering cost for 80% of adoption value." This doc concretizes that scope into the per-family sequence emission contract (§6) and the customer-integration surface (§6.5). Mutually consistent; this doc adds the depth the umbrella table did not carry.

### vs. SOS-08-D (sibling, forthcoming) cocotb + SVA path

SOS-08-D is the **primary** vector path per umbrella §5.4 / EOQ-003. SOS-08-D consumes the same JSONL vector IR (§6.4) and emits cocotb Python coroutines + SVA bind files. SOS-08-F consumes the same IR and emits UVM sequences. The two sub-phases are file-disjoint (different output artefacts) and feature-disjoint (cocotb vs UVM scaffolding); they share only the upstream IR + the chart-vocabulary metadata convention from INV-S-HDL-5. A customer using both gets cocotb-driven open-source-simulator coverage AND UVM-driven enterprise-simulator coverage from the same chart, without duplicate vector authoring.

### vs. SOS-08-E (sibling, forthcoming) SystemVerilog testbench path

SOS-08-E is the **LCD** (lowest-common-denominator) class-based SystemVerilog testbench path. SOS-08-E emits a self-contained class-based testbench + SVA bind files that any commercial simulator (Questa, Riviera, VCS, Xcelium) runs without UVM dependency. SOS-08-F's UVM-sequence emission complements SOS-08-E for customers whose env IS UVM-based; the two paths are alternatives a customer chooses based on their existing infrastructure (UVM shop → SOS-08-F; non-UVM SystemVerilog shop → SOS-08-E). The SVA bind files SOS-08-E emits are byte-identical to SOS-08-D's bind files (both sibling sub-phases share the SVA emission machinery).

### vs. SOS-07 §7 AuthorityRelationship matrix — UVM = derive

SOS-07 §7 declares UVM as **derive** with mutation rights "none — emit conformant subset". SOS-08-F is the concrete per-sub-phase application of that derive position: the sub-phase consumes the UVM grammar (`uvm_sequence`, `uvm_sequence_item`, `uvm_object_utils`, `uvm_error`), produces conformant `.sv` output, does NOT extend the UVM grammar, does NOT register custom UVM types beyond the baseline `sos_seq_item` + per-family sequence subclasses, and treats the customer's UVM env as upstream consumer per the derive relationship's contract. INV-S-HDL-F-2 is the mechanical statement of this derive boundary at the per-sub-phase level.

### vs. INV-S-HDL-5 (vector-to-chart traceability for HDL)

INV-S-HDL-F-3 concretizes INV-S-HDL-5 for the UVM target: the chart-vocabulary fields (`chart_state`, `transition_id`, `invariant_id`) on `sos_seq_item` are the mechanical realisation of "vector-to-chart traceability". SOS-08-D realises the same invariant via cocotb-side Python metadata + SVA property names; SOS-08-E realises it via testbench-class assertion messages. Three sibling realisations of one cross-sub-phase invariant; this sub-phase's realisation is `sos_seq_item` field population per §6.4.

## 11. Pending Concept Decision Notices (PCDNs)

These open questions move this doc from 🟡 drafted to 🟢 ratified. PCDN identifiers are stable per parent CLAUDE.md "Errata Open Question" naming.

- **PCDN-SOS-08-F-001 — UVM version commitment.** Three options: (a) UVM 1.2 only (IEEE 1800.2-2017; broadest deployed base); (b) UVM 2.0 only (Accellera 2.0 / IEEE 1800.2-2020; forward-looking); (c) both with forward-compatibility (UVM 1.2 grammar + UVM 2.0 verification). **Recommendation**: (c) both via forward-compatibility — author to the UVM 1.2 grammar subset that runs unchanged on UVM 2.0. Captures the largest customer base; keeps emitter complexity low (one grammar, two runtime targets).

- **PCDN-SOS-08-F-002 — Chart event family enumeration.** §6.1 names six families (`task`, `sem`, `queue`, `timer`, `event`, `tick`). Are these the v1 set? Should `mutex` be added (distinct from `sem` for non-binary mutexes)? Should `task` split into lifecycle vs scheduling (`task_lifecycle`, `task_sched`)? **Recommendation**: six families per §6.1 at v1; matches the chart-side syscall surface in SOS-08-B; expansion via §15 amendment if the chart introduces new families.

- **PCDN-SOS-08-F-003 — Sequence-item field layout.** §5.3 names two options: (a) universal `sos_seq_item` with discriminated union; (b) per-family transaction classes (`sos_task_seq_item`, `sos_sem_seq_item`, ...). **Recommendation**: (a) universal, per §5.3 rationale (single transaction type for the customer's driver; per-family classes don't reduce customer integration cost). Per-family classes would shift the customer cost into N driver-registration touches, multiplying the integration surface area.

- **PCDN-SOS-08-F-004 — `uvm_object_utils` registration.** Customer registers SOS classes with the factory, or SOS-emitted package registers them? **Recommendation**: SOS-generated, in the consolidated sequence-library package (§5.5). Customer's standard UVM factory-override mechanics (`set_type_override_by_type`) remain available for customization; default-on registration means out-of-the-box use without customer touch.

- **PCDN-SOS-08-F-005 — Pre/post-sequence hook policy.** Emit empty virtual hooks for customer override (current §5.6 recommendation), or require customer to subclass + override? **Recommendation**: empty virtual hooks. Lowest-friction integration; standard UVM extension point preserved. Required-subclass-and-override would force customer authoring on every sequence use.

- **PCDN-SOS-08-F-006 — Sequence-library packaging.** One `.sv` per event family (six files), or one consolidated package (one file)? **Recommendation**: one consolidated package `sos_uvm_seq_pkg` per §5.7. Single import line for the customer; no per-family churn surface when the chart adds a new family (the package regenerates; the import line is unchanged).

## 12. Acceptance checklist

A conforming SOS-08-F ratification satisfies:

- (a) ⏸ PCDN-SOS-08-F-001 through 006 resolved (§11).
- (b) ⏸ The codegen tool gains a UVM-sequence-emit path producing `sos_uvm_seq_pkg.sv` + `sos_uvm_seq_pkg.svh` + `sos_uvm_integration_example.sv` from a chart's bounded-reachability vector IR.
- (c) ⏸ Each chart event family per §6.1 has its `uvm_sequence` subclass emission tested against a sample chart (recommended: the bootstrap kernel chart `rtos_kernel.scxml` is the v1 emission target).
- (d) ⏸ The baseline `sos_seq_item` transaction class emits per §6.2 with all six chart-vocabulary metadata fields populated correctly from the vector IR.
- (e) ⏸ A worked-example customer integration (the `sos_uvm_integration_example.sv` artifact) is authored and runs end-to-end on a reference UVM 1.2 simulator (recommended: an open-source UVM-supporting flow such as Verilator + uvm-python sequence-runner, or a vendor evaluation simulator).
- (f) ⏸ Chart-vocabulary failure-message format per §6.6 verified on at least one injected violation in the worked example (manual mutation of a chart vector produces a UVM error with chart vocabulary present).
- (g) ⏸ INV-S-HDL-F-1 through 5 satisfied: no UVM class beyond sequences + `sos_seq_item`; no SVA emission; chart-vocabulary fields populated; UVM 1.2 grammar only; runs on UVM 2.0 unchanged.
- (h) ⏸ Cross-phase invariants INV-SOS-A through H cited correctly in the emitted package's docstring header (typically via a `// @spec` comment block referencing this doc + SOS-07).
- (i) ⏸ Cross-sub-phase invariants INV-S-HDL-1 through 5 cited correctly in the emitted package's docstring header (INV-S-HDL-5 explicitly on `sos_seq_item`'s metadata fields).
- (j) ⏸ Sibling SOS-08-D + SOS-08-E sub-phases reference SOS-08-F in their respective §10 reconciliation sections (the three sub-phases collectively cover the three vector-emission paths the umbrella names).

(a) is the ratification gate; (b)-(j) are implementation gates that flip from ⏸ to ✅ as the implementation lands.

A conforming SOS-08-F *without* (e) — i.e. the emitter is authored but no end-to-end customer-side example runs at ratification time — satisfies (a)-(d) and (g)-(i). This second-tier conformance level reflects the realistic v1 landing: the emitter ships, the example is informative, and full customer-side validation happens at customer integration time (per the 10/80 framing — the customer owns the env, so end-to-end validation is partly customer-side regardless).

## 13. Files cited

| Path | Role |
|---|---|
| `docs/concepts/SOS-08-CONCEPTS.md` | Umbrella; this sub-phase's parent. |
| `docs/concepts/SOS-07-CONCEPTS.md` | Cross-phase invariants INV-SOS-A through H; AuthorityRelationship matrix (UVM = derive); cited not redefined. |
| `docs/concepts/SOS-08-D-CONCEPTS.md` | Sibling sub-phase (forthcoming) — cocotb + SVA primary vector path; owns SVA bind file emission. |
| `docs/concepts/SOS-08-E-CONCEPTS.md` | Sibling sub-phase (forthcoming) — SystemVerilog class-based testbench LCD path; also emits SVA bind files. |
| `docs/concepts/SOS-08-A-CONCEPTS.md` | L0 primitive library; the per-primitive contracts the chart compiler's L0 emission step uses (orthogonal to this sub-phase but cited for chart-bound vector IR consumer continuity). |
| `docs/concepts/SOS-ROADMAP-07-PLUS.md` | Informative roadmap; EOQ-003-ROADMAP resolution is the source of the 10/80 framing. |
| `rtos_kernel.scxml` | Bootstrap kernel chart; recommended v1 emission target for SOS-08-F worked example. |
| `tools/sos-codegen/` | Codegen tool; gains UVM-sequence-emit path (per (b)). |
| Forthcoming `tools/sos-codegen/emit/uvm/` | UVM-emit subdirectory housing the per-family templates. |
| Forthcoming `examples/uvm_integration/` | Worked-example customer integration directory (per (e)). |
| Parent `CLAUDE.md` | Spec-Before-Code Planning Discipline; Phase document shape. |

## 14. Unblocks

This sub-phase's ratification (after PCDN walkthrough) unblocks:

- The codegen tool's UVM-sequence-emit implementation work (acceptance gate (b)).
- Customer-side UVM integration for chart-driven stimulus, against any existing UVM env at UVM 1.2 or UVM 2.0.
- The "SOS sequences plug into our existing UVM env" customer-adoption story — the 10/80 framing's marketing-claim form.
- Future sub-phase SOS-08-F-A (potential pyuvm extension) if a customer requests pyuvm-compatible emission per umbrella PCDN-004 follow-on.

This sub-phase does NOT unblock SOS-09 (membrane), SOS-10 (multi-language orchestrator), SOS-11 (MCP-mediated chart editing), or SOS-12 (recursive chart dispatch); those depend on SOS-08-A / SOS-08-B / SOS-08-C ratifications, not SOS-08-F.

## 15. Change log

### 2026-05-23 — Initial draft (Ira)

- Authored `SOS-08-F-CONCEPTS.md` as the UVM-sequence-emission sub-phase under the SOS-08 umbrella.
- §3 canonical glossary: terms `UVM sequence`, `uvm_sequence_item`, `chart event family`, `stimulus plug-in`, `customer-owned UVM environment`, `bounded-reachability vector IR`, `chart-vocabulary failure message`, `UVM version target`.
- §4 source-of-truth map: per-concept canonical authority; SVA emission deliberately routed to sibling SOS-08-D / SOS-08-E.
- §5 frozen decisions: scope discipline (sequences only, eight-item exclusion list); UVM version target (1.2 primary, 2.0 forward-compatible); universal `sos_seq_item` shape; no SVA-binding in this sub-phase; `uvm_object_utils` registration policy; pre/post-sequence hook policy; one-consolidated-package sequence library.
- §6 sequence-emission contract: chart event family enumeration (six families: task, sem, queue, timer, event, tick); baseline `sos_seq_item` transaction class with discriminated-union payload + chart-vocabulary metadata; per-family `uvm_sequence` subclass template; vector IR consumption; five-step customer-integration contract; chart-vocabulary failure-message format.
- §7 per-sub-phase invariants INV-S-HDL-F-1 through 5: sequences only; customer owns env/scoreboard/driver/factory; chart-vocabulary traceability survives UVM boundary; no SVA emission; UVM version compatibility.
- §8 standards integration matrix additions: none (consumes SOS-07 §7 UVM=derive row; SOS-08-F is the per-sub-phase application).
- §10 reconciliation vs SOS-08 umbrella §6, SOS-08-D + SOS-08-E sibling sub-phases, SOS-07 §7 AuthorityRelationship matrix, and INV-S-HDL-5.
- §11 six PCDNs raised covering UVM version commitment, chart event family enumeration, sequence-item field layout, factory registration, hook policy, packaging.
- §12 acceptance checklist: gates (a)-(j); reduced conformance level without (e) end-to-end example.

Status: 🟡 **drafted**, awaiting PCDN walkthrough.

### 2026-05-23 — Ratified after PCDN walkthrough (Ira)

All six PCDNs from §11 resolved with recommendations accepted.

- **PCDN-SOS-08-F-001 → RESOLVED**: UVM version commitment is **UVM 1.2 grammar + UVM 2.0 forward-compatibility**. Emitter authors to the UVM 1.2 subset that runs unchanged on UVM 2.0. Captures the largest customer base; one grammar, two runtime targets.
- **PCDN-SOS-08-F-002 → RESOLVED**: chart event families at v1 are the **six** named in §6.1 (`task`, `sem`, `queue`, `timer`, `event`, `tick`). Matches the chart-side syscall surface in SOS-08-B. Expansion via §15 amendment.
- **PCDN-SOS-08-F-003 → RESOLVED**: sequence-item field layout is the **universal `sos_seq_item`** with discriminated union (per §5.3). Per-family classes would multiply the customer driver-registration touch points.
- **PCDN-SOS-08-F-004 → RESOLVED**: `uvm_object_utils` factory registration is **SOS-generated**, in the consolidated sequence-library package per §5.5. Out-of-the-box use without customer touch; customer's `set_type_override_by_type` mechanics remain available.
- **PCDN-SOS-08-F-005 → RESOLVED**: pre/post-sequence hook policy is **empty virtual hooks**. Lowest-friction integration; standard UVM extension point preserved.
- **PCDN-SOS-08-F-006 → RESOLVED**: sequence-library packaging is **one consolidated `sos_uvm_seq_pkg`** per §5.7. Single import line for the customer; no per-family churn when the chart adds a new family.

**§5 / INV amendments**:
- §5 frozen-decisions extended with the six resolutions above by reference.
- INV-S-HDL-F-4 (UVM 1.2 grammar only) wording extended: "emitted code uses only UVM 1.2 grammar constructs verified to run unchanged on UVM 2.0; a per-release smoke run validates the cross-runtime invariant".

**Status**: 🟢 **ratified**. Implementation of the UVM-sequence-emit path in `tools/sos-codegen/` is now unblocked. SOS-08-F composes with SOS-08-D + SOS-08-E (via shared vector-IR boundary); the "10% engineering / 80% adoption value" framing from §0 holds — the customer owns the UVM env, scoreboard, driver, factory; SOS owns only the sequence-emit path.
