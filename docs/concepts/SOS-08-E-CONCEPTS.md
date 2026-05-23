# SOS-08-E — SystemVerilog testbench + SVA bind file emission

**Status:** 🟢 **ratified 2026-05-23** (see §15).

## 0. Authority policy

This phase doc ratifies the **SystemVerilog testbench** emission path under the SOS-08 umbrella (`SOS-08-CONCEPTS.md`, ratified 2026-05-23). The umbrella's §6 frames SOS-08-E as the **LCD path**: class-based, self-checking, constrained-random-free, no UVM dependency. The umbrella's §5.4 (vector emission priority per EOQ-003-ROADMAP) names SOS-08-E **second** in the emit priority — after SOS-08-D (cocotb + SVA, the **primary** path) and before SOS-08-F (UVM sequences).

This doc is SOS-08-D's sibling. The two share an artifact family — the SVA bind files — and differ only in the stimulus + checker driver. SOS-08-D's path uses Python coroutines + open-source simulators; SOS-08-E's path uses SystemVerilog classes + commercial simulators. The SVA bind files emitted by either path are **byte-identical**.

Per the parent CLAUDE.md "Spec-Before-Code Planning Discipline / Phase document shape":

- **Normative** sections of this doc: §3 glossary, §4 source-of-truth map, §5 frozen decisions, §6 emission contract, §7 cross-sub-phase invariants (INV-S-HDL-E-*), §8 standards integration matrix additions, §12 acceptance checklist.
- **Informative** sections: §1 purpose, §2 problem statement, §11 non-goals, §15 change log.
- All keywords MUST, MUST NOT, SHALL, SHOULD, SHOULD NOT, MAY, RECOMMENDED are interpreted per RFC 2119 / RFC 8174 when capitalised.

This doc cites SOS-07 §6 for `INV-SOS-A` through `INV-SOS-H` and SOS-08 §7 for `INV-S-HDL-1` through `INV-S-HDL-5`. Neither set is re-derived. The SVA bind files are owned by SOS-08-D; this doc cites them as a shared artifact and does NOT re-author their emission contract.

## 1. Purpose

To freeze the SystemVerilog testbench emission contract — the **lowest-common-denominator** path that runs on every commercial simulator (Questa, Riviera, VCS, Xcelium) plus Verilator (open-source, for the SV subset it supports), with zero UVM dependency and zero constrained-random infrastructure. The path exists because:

1. **Adoption surface.** Many shops have a Questa or VCS licence and a "no-Python-in-verification" policy. cocotb is unavailable to them; UVM is overweight or politically out-of-bounds. A class-based self-checking SV testbench is the universally-accepted shape that survives both constraints.

2. **LCD coverage.** Every SV-2017-compliant simulator runs class-based code; the subset SOS-08-E uses works on Verilator with `--assert` for the SVA bind side. The path is the "boring" form that just works — chosen for portability, not for any particular simulator's strength.

3. **SVA bind file reuse.** The chart's bounded-reachability vectors + invariants → SVA properties path is the same artifact SOS-08-D emits. SOS-08-E composes the same bind file with a different driver. Authoring SOS-08-E does not duplicate the assertion authoring; it composes the existing one.

The SOS-08-D doc is the primary path; SOS-08-E is the alternative for environments where SOS-08-D's open-source-Python stack does not fit.

## 2. Problem statement

Five concrete pressures motivate the SOS-08-E sub-phase as a standalone deliverable rather than a "Python-isn't-available" footnote on SOS-08-D:

1. **Commercial-simulator-only environments are still a majority case** in funded ASIC and FPGA-product shops. Refusing them as users on Python-stack grounds excludes the population SOS-08 most needs as early adopters (per umbrella §2: "enterprise shops have their own environments they want to keep using").

2. **No-UVM constraint is real.** Enterprise shops with UVM expertise have UVM testbenches; enterprise shops without it have *intentionally* no-UVM policies (greenfield projects, IP teams who own discrete IP, small ASIC shops). SOS-08-F (UVM sequences) addresses the former. SOS-08-E addresses the latter — the class-based-but-no-UVM gap.

3. **Constrained-random-free is the chart's verification claim.** The bounded-reachability vectors are exhaustive within the bound; constrained random would dilute that claim into a statistical confidence interval. INV-SOS-B (vectors-as-deliverable) demands exhaustive emission — `randomize()` + `constraint` blocks would contradict the verification position. The SV testbench replays the exhaustive vector set; it does not generate stimulus.

4. **Class-based shape is required for self-checking response without inline assertions.** Inline `assert property` inside a testbench module mixes the driver/checker concern with the testbench scaffolding. A class-based driver + checker keeps the SVA bind files as the *only* property-bearing artifact, mirroring SOS-08-D's separation of stimulus (Python) from properties (SVA).

5. **Simulator-build invocation differs per tool.** Questa's `vsim` + `vlog`, Riviera's `vsim` + `alog`, VCS's `vcs` + `+define`, Xcelium's `xrun`, and Verilator's `verilator --binary` each want a different build wrapper. The emission contract MUST cover the wrapper script(s) too — otherwise the user authors them, which immediately drifts.

## 3. Canonical glossary

Terms normative within SOS-08-E+. Authority relationships per §8.

| Term | Definition |
|---|---|
| **SV testbench** | A SystemVerilog-2017 testbench composed of a top-level module + a stimulus driver class + a response checker class + one or more SVA bind files. Synthesizable-subset-irrelevant — testbenches are simulation-only artifacts. |
| **Stimulus driver class** | A SystemVerilog class that consumes the chart's bounded-reachability vector IR (JSONL traces per SOS-08 PCDN-009) and drives DUT input signals through a parameterized virtual interface. One driver class per chart region. |
| **Response checker class** | A SystemVerilog class that observes DUT output signals through the same parameterized virtual interface and compares against the vector IR's `expected` field (per SOS-03 §7.1). Reports failures in chart vocabulary per INV-SOS-H + INV-S-HDL-5. |
| **SVA bind file** | A SystemVerilog `bind` directive attaching an assertion module to a DUT module instance. **Owned by SOS-08-D**; SOS-08-E composes the same file. As defined in SOS-08-A §3 and SOS-08 §6 (SOS-08-D row); used without modification. |
| **Build wrapper** | The simulator-specific script (`run.do` for Questa/Riviera; `Makefile.sv` for VCS; `xrun_args.f` for Xcelium; `verilator_run.sh` for Verilator) that invokes `vlog` + `vsim` (or vendor equivalent) against the generated testbench. One wrapper per supported simulator. |
| **Per-vector test** | A standalone testbench invocation that replays exactly one vector trace. Failure attribution is unambiguous (the offending vector is the only one in flight). |
| **Per-region test** | A testbench that replays all vectors for one chart region in sequence, with a checker reset between traces. Lower compile cost but coarser failure attribution. |
| **Class hierarchy depth** | The number of levels in the driver/checker class hierarchy. "Flat" = 1 driver class + 1 checker class. "Layered" = additional intermediate abstractions (stimulus generator, scoreboard, transaction abstraction). PCDN-SOS-08-E-001. |

## 4. Source-of-truth map

For every concept this sub-phase touches, **exactly one** location is the canonical authority.

| Concept | Authority |
|---|---|
| SV testbench top-level module shape | **this doc** §6 |
| Stimulus driver class contract | **this doc** §6.1 |
| Response checker class contract | **this doc** §6.2 |
| SVA bind file artifacts | `SOS-08-D-CONCEPTS.md` (forthcoming sibling; **mirror** here — same files) |
| Vector IR consumption shape | `SOS-08-CONCEPTS.md` PCDN-009 resolution (JSONL traces + JSON invariants); SOS-03 §7.1 vector schema |
| Per-vector vs per-region testbench shape | **this doc** §5 + §6 (**PCDN-SOS-08-E-004**) |
| Build wrapper sources (per simulator) | `tb/sv/run_<simulator>.{do,tcl,sh}` + `tb/sv/Makefile.sv` (forthcoming) |
| Failure-message format | **this doc** §6.3 (mirrors SOS-08-D contract) |
| Class hierarchy depth | **this doc** §5.1 (**PCDN-SOS-08-E-001**) |
| Verilator-subset compliance declaration | **this doc** §5.2 (**PCDN-SOS-08-E-002**) |
| Coverage emission (`covergroup` blocks) | **this doc** §5.3 (**PCDN-SOS-08-E-003**) |
| Simulator-specific build script structure | **this doc** §5.5 (**PCDN-SOS-08-E-005**) |
| Cross-phase invariants INV-SOS-A through H | `SOS-07-CONCEPTS.md` §6 (cited, not redefined) |
| Cross-sub-phase invariants INV-S-HDL-1 through 5 | `SOS-08-CONCEPTS.md` §7 (cited, not redefined) |
| Cross-sub-phase invariants INV-S-HDL-E-* | **this doc** §7 |

## 5. Frozen decisions

### 5.1 Class-based, self-checking, constrained-random-free, no UVM

Per umbrella §6 (SOS-08-E framing): the SV testbench SHALL be **class-based**, **self-checking**, **constrained-random-free**, and **UVM-free**. Concretely:

- **Class-based.** The stimulus driver and response checker are SystemVerilog classes (`class sos_driver`, `class sos_checker`), not bare procedural code in the testbench `initial` block.
- **Self-checking.** The checker class compares observed signal values against expected values from the vector IR and emits pass/fail in chart vocabulary. No external scoreboard tool, no waveform post-processing required.
- **Constrained-random-free.** No `randomize()` calls, no `constraint` blocks, no `rand` / `randc` class properties. Stimulus is exhaustive vector replay per INV-SOS-B; randomisation would dilute the verification claim.
- **No UVM dependency.** No `import uvm_pkg::*`, no `uvm_*` base classes, no UVM macros (`` `uvm_object_utils ``, etc.), no UVM factory. UVM-targeted emission lives at SOS-08-F.
- **No `program` blocks.** Program blocks are a UVM-era construct with subtle scheduling semantics; class-based testbenches in module scope are sufficient and more portable.
- **`assert property` only via `bind` files.** No inline assertions in the testbench module or in driver/checker classes. Properties live exclusively in the SVA bind file (SOS-08-D-owned).

Frozen-enumeration registration policy: **Standards Action** (modifying any bullet requires a §15 amendment here + cross-phase review with SOS-08-D and SOS-08-F to confirm scope boundaries remain coherent).

### 5.2 SVA bind file mirror

Per umbrella §5.4 and SOS-08-D's authority over SVA emission: SOS-08-E SHALL emit the **same** SVA bind files as SOS-08-D. The chart's invariants compile to `bind` directives that travel with both the cocotb test and the SV testbench. The bind files are simulator-agnostic; whichever stimulus driver runs (Python coroutine or SV class), the assertion machinery is identical.

The chart-vocabulary failure-message text in the bind file's `$error(...)` / `$display(...)` calls is identical in both paths. INV-SOS-H + INV-S-HDL-5 are satisfied by the bind file's property authoring; SOS-08-E inherits that satisfaction.

Frozen-enumeration registration policy: **Standards Action**.

### 5.3 Target simulator set

Per umbrella §6 (SOS-08-E framing) and §1 above, the supported commercial simulators are **Questa**, **Riviera**, **VCS**, and **Xcelium**. The supported open-source simulator is **Verilator** with `--assert` for the SVA subset Verilator supports. SOS-08-E SHALL emit a build wrapper for each.

Verilator's supported SV subset is narrower than the commercial simulators' — in particular, Verilator's SVA support is limited to a subset of `assert property` (no `eventually`, limited `##[a:b]` ranges, no `disable iff` in some versions). The SVA bind files SHOULD stay within the Verilator-supported subset where feasible; properties that require constructs outside the subset are emitted only in the commercial-simulator path.

Frozen-enumeration registration policy: **Specification Required** (adding a sixth simulator requires a phase-owner walkthrough; removing one requires §15 amendment).

### 5.4 Vector IR consumption format

Per umbrella PCDN-009 resolution: **JSONL** for traces (one event per line), **JSON** for invariants. The stimulus driver class consumes the JSONL trace file via SystemVerilog file I/O (`$fopen` + `$fgets` + a hand-rolled JSON-Lines parser, or a precompiled simulator-agnostic parser library bundled with the testbench). The driver does NOT consume the JSON invariants file directly — invariants are compiled to SVA properties in the bind file (SOS-08-D's emission step), so the SV testbench sees them only as bound assertions.

Frozen-enumeration registration policy: **Standards Action**.

### 5.5 Failure-message format

Per INV-SOS-H + INV-S-HDL-5 and SOS-08-D's failure-message contract: every checker class failure SHALL render in chart vocabulary, naming the chart state, transition, or invariant that produced the offending vector. Raw RTL signal traces MAY be emitted alongside the chart-vocabulary message (as debug supplement), but MUST NOT replace it. The format is byte-identical to SOS-08-D's failure-message format (PCDN-resolved at SOS-08-D ratification).

Example failure message shape (informative):

```
[FAIL] vector V47: chart `auth.connecting` transition `T12 (idle→handshaking)` produced
       expected output `handshake_ack=1` at cycle 142; observed `handshake_ack=0`.
       Bound invariant: `INV-AUTH-3 (handshake_ack monotonic until reset)`.
```

Frozen-enumeration registration policy: **Standards Action**.

## 6. Emission contract

The codegen tool emits the following artifacts per chart region (or per chart, depending on PCDN-SOS-08-E-004 resolution):

| Artifact | Path | Role |
|---|---|---|
| Top-level testbench module | `tb/sv/<region>/tb_<region>.sv` | Instantiates DUT, virtual interface, driver, checker; runs the test. |
| Stimulus driver class | `tb/sv/<region>/sos_driver_<region>.sv` | Consumes JSONL trace, drives DUT inputs through virtual interface. |
| Response checker class | `tb/sv/<region>/sos_checker_<region>.sv` | Observes DUT outputs, compares against expected, reports failures in chart vocabulary. |
| Virtual interface | `tb/sv/<region>/dut_if_<region>.sv` | Parameterized by DUT port shape; driver + checker route through it. |
| SVA bind file | `tb/sv/<region>/<region>_sva_bind.sv` | **Mirror of SOS-08-D's bind file**; binds property module to DUT instance. |
| JSONL vector trace | `tb/sv/<region>/vectors/<region>.jsonl` | Bounded-reachability traces (chart-emitted, consumed by driver). |
| Questa/Riviera build wrapper | `tb/sv/<region>/run.do` | `vlog` + `vsim` invocation; compiles all SV files and runs. |
| VCS build wrapper | `tb/sv/<region>/Makefile.sv` | `vcs` + `simv` invocation. |
| Xcelium build wrapper | `tb/sv/<region>/run_xrun.sh` | `xrun` invocation with `-sv` + `-assert` flags. |
| Verilator build wrapper | `tb/sv/<region>/run_verilator.sh` | `verilator --binary --assert -Wall` invocation. |

### 6.1 Stimulus driver class contract

```systemverilog
class sos_driver_<region>;
    virtual dut_if_<region> vif;
    string trace_path;

    function new(virtual dut_if_<region> vif, string trace_path);
        this.vif = vif;
        this.trace_path = trace_path;
    endfunction

    task run();
        // Open trace_path, parse JSONL line by line.
        // For each line: decode the event object's port-poke map;
        // drive vif signals; wait the prescribed number of clock cycles.
        // Emit a chart-vocabulary log line per event.
    endtask
endclass
```

Behavioural contract:

- The driver SHALL drive only DUT input signals through `vif`. It SHALL NOT inspect DUT outputs (that is the checker's role).
- The driver SHALL log every consumed vector event in chart vocabulary (`[DRIVE] vector V<n>: applying event <chart-event-name> at cycle <n>`).
- The driver SHALL terminate normally when the trace file is exhausted; the testbench top-level then waits a configurable settle period before declaring the run complete.
- The driver MUST NOT call `randomize()`, instantiate `rand` properties, or use `constraint` blocks.

### 6.2 Response checker class contract

```systemverilog
class sos_checker_<region>;
    virtual dut_if_<region> vif;
    string trace_path;
    int fail_count;

    function new(virtual dut_if_<region> vif, string trace_path);
        this.vif = vif;
        this.trace_path = trace_path;
        this.fail_count = 0;
    endfunction

    task run();
        // Open trace_path, parse JSONL line by line.
        // For each line: at the prescribed observation cycle,
        // sample vif outputs and compare against the event's "expected" field.
        // On mismatch: increment fail_count, emit chart-vocabulary $error.
    endtask

    function int get_fail_count();
        return fail_count;
    endfunction
endclass
```

Behavioural contract:

- The checker SHALL observe DUT output signals through `vif`. It SHALL NOT drive any DUT input signals.
- Failure messages SHALL render in chart vocabulary per §5.5.
- The checker SHALL maintain a `fail_count` accessible to the testbench top-level, which uses it as the test's exit status.
- The checker MUST NOT use `assert property` inline; all property checking lives in the SVA bind file.

### 6.3 Top-level testbench module contract

The top-level module:
1. Instantiates the DUT.
2. Instantiates the virtual interface.
3. Drives clock and reset.
4. Instantiates the driver and checker classes (typically inside an `initial` block: `driver = new(vif, "vectors/<region>.jsonl"); checker = new(vif, "vectors/<region>.jsonl");`).
5. `fork ... join` runs driver and checker concurrently.
6. On driver completion + settle period: emits a summary line (`[PASS]` or `[FAIL count=N]`) and calls `$finish`.

The SVA bind file is referenced via `` `include `` or via simulator-specific include path; the bind directive binds property modules to the DUT instance.

### 6.4 Build wrapper contract

Each build wrapper SHALL:
- Compile every `.sv` file in the testbench directory in dependency order (vif → classes → top-level → bind).
- Enable SVA assertions in the simulator (`-assert` family of flags).
- Set the working directory so `tb/sv/<region>/vectors/<region>.jsonl` is reachable by relative path from the simulation invocation.
- Exit with status 0 on `[PASS]`, non-zero on `[FAIL count>0]` or compile error.

Wrappers SHOULD support a `--gui` option (Questa/Riviera/VCS GUI mode) for interactive debugging.

## 7. Cross-sub-phase invariants

In addition to INV-SOS-A through H (cited from SOS-07) and INV-S-HDL-1 through 5 (cited from SOS-08), the following invariants are normative within SOS-08-E:

- **INV-S-HDL-E-1 — No constrained-random in emitted testbenches.** The codegen tool SHALL NOT emit `randomize()`, `constraint`, `rand`, or `randc` constructs into any SOS-08-E artifact. INV-SOS-B (vectors-as-deliverable) is the load-bearing reason — exhaustive vector replay is the verification claim; randomisation would dilute it.

- **INV-S-HDL-E-2 — No UVM imports.** The codegen tool SHALL NOT emit `import uvm_pkg::*`, ` `uvm_*` macros, or any reference to UVM base classes. UVM-targeted emission lives at SOS-08-F. Touching this invariant requires a §15 amendment here AND at SOS-08-F (the boundary between E and F is what makes both targets coherent).

- **INV-S-HDL-E-3 — SVA properties only via `bind` files.** Inline `assert property` (and `assume`, `cover`) in testbench modules or driver/checker classes is prohibited. All property authoring lives in the SVA bind file owned by SOS-08-D. This makes the SOS-08-D and SOS-08-E paths verifiably equivalent at the property layer; differences are scoped to stimulus + scoreboard.

- **INV-S-HDL-E-4 — Chart-vocabulary failure messages.** Every checker class `$error` and every SVA bind file `$error` SHALL include the chart state, transition, or invariant identifier that named the failing claim. Raw signal-level messages MAY appear as debug supplement but MUST NOT stand alone. Concretizes INV-SOS-H + INV-S-HDL-5 for the SV testbench target.

- **INV-S-HDL-E-5 — Build wrapper per supported simulator.** For each simulator named in §5.3, the codegen tool SHALL emit a build wrapper. Adding a simulator without its wrapper is a partial-deliverable defect, not a feature.

- **INV-S-HDL-E-6 — Verilator-subset compliance is declared, not assumed.** Per PCDN-SOS-08-E-002 resolution, the codegen tool SHALL document which SV-2017 features its emitted testbench uses. Features outside Verilator's supported subset MAY be used (the commercial-simulator path is the primary target); when used, the Verilator wrapper SHALL emit a deferred-failure stub rather than silently break.

## 8. Standards integration matrix additions

This sub-phase does not introduce new external standards beyond those already declared in SOS-08 §8 and SOS-07 §7. The following commercial simulator vendors are consumed as **derive** relationships (SOS uses the simulator; the simulator's command-line interface is upstream):

| Concept | Upstream authority | Local relationship | Phase that declares it | Mutation rights |
|---|---|---|---|---|
| Questa (Siemens EDA) | Siemens (commercial) | **derive** (emit build wrapper) | SOS-08-E (this doc) | none |
| Riviera-PRO (Aldec) | Aldec (commercial) | **derive** | SOS-08-E | none |
| VCS (Synopsys) | Synopsys (commercial) | **derive** | SOS-08-E | none |
| Xcelium (Cadence) | Cadence (commercial) | **derive** | SOS-08-E | none |
| Verilator | open project (Veripool / CHIPS Alliance) | **derive** (already declared in SOS-08 §8 with cocotb-context; this row narrows to the `--binary --assert` SV-testbench-runner context) | SOS-08 / SOS-08-E | none |

The SystemVerilog-2017 synthesizable-subset row (already in SOS-08 §8) does NOT apply to SOS-08-E — testbenches are simulation-only, and SOS-08-E intentionally uses non-synthesizable constructs (classes, virtual interfaces, file I/O). The applicable upstream is the SV-2017 LRM's verification subset, which is already covered by the broader SV-2017 row.

## 9. Non-goals

This sub-phase does NOT:

- Emit UVM-based testbenches. Per umbrella §6 (SOS-08-F) and INV-S-HDL-E-2. UVM sequences (stimulus-only) are SOS-08-F.
- Emit cocotb tests. That is SOS-08-D's territory.
- Author the SVA bind files themselves. SOS-08-D owns the bind-file emission contract; SOS-08-E mirrors it.
- Replace the chart's bounded-reachability vector emission. Vectors are emitted by the chart-side compiler; SOS-08-E consumes them.
- Support pre-SV-2017 dialects (Verilog-2005, Verilog-2001). Per umbrella §5.1 and EOQ-002.
- Implement constrained-random stimulus (per INV-S-HDL-E-1). The verification claim is exhaustive replay, not statistical coverage.
- Emit waveform files. SOS-08-G owns the waveform + annotation path.
- Bench-validate against an FPGA. SV testbench simulation runs in software; the FPGA bench-validation gate (umbrella §12 (e)) is satisfied at SOS-08-A implementation, not here.

## 10. Reconciliation decisions vs adjacent repo primitives

### vs. SOS-08-D (sibling, primary path)

SOS-08-D and SOS-08-E **share** the SVA bind file artifact byte-for-byte; they **differ** only in the stimulus driver + response checker. SOS-08-D's driver is a Python coroutine running under cocotb; SOS-08-E's driver is a SystemVerilog class. Both consume the same JSONL vector trace; both emit the same chart-vocabulary failure-message format. The codegen tool produces both paths from the same chart IR — no IR duplication, no separate authoring step.

Per umbrella §5.4 priority: SOS-08-D is **primary** (open-source-sim path, broader adoption surface); SOS-08-E is the **LCD alternative** for commercial-simulator-only environments.

### vs. SOS-08-F (UVM sequences)

SOS-08-F emits UVM-compatible **sequences** (stimulus only) that plug into a customer's existing UVM environment. SOS-08-F does NOT emit testbenches; the customer provides the env, sequencer, driver wrapping, scoreboard. SOS-08-E emits a **complete** testbench in non-UVM form.

The boundary: a shop with a UVM environment uses SOS-08-F sequences as stimulus inside their env. A shop without UVM (or with a no-UVM policy) uses the SOS-08-E testbench directly. Both paths consume the same vector IR; the SVA bind files travel with whichever path the shop runs.

### vs. SOS-08-A L0 primitive cocotb tests

SOS-08-A §6 names per-primitive cocotb tests as the primary L0 verification surface. SOS-08-E does NOT re-emit per-L0-primitive SV testbenches at v1 — the L0 primitives are infrastructure, not chart-emitted, and their verification is owned by SOS-08-A. SOS-08-E's emission is **chart-emitted-region scope**: for each chart region (L2 FSM), one SV testbench.

A future amendment MAY extend SOS-08-E to per-L0 SV testbenches if a commercial-only shop demands it; that amendment is out of scope here.

### vs. SOS-03 vector schema

The JSONL trace format SOS-08-E consumes is the same conformance-vector format SOS-03 ratifies. SOS-08-E's driver does NOT re-derive the schema; it consumes SOS-03's canonical form via the JSONL parser. The `expected` field per SOS-03 §7.1 is the response checker's source of truth.

## 11. Pending Concept Decision Notices (PCDNs)

These open questions move this doc from 🟡 drafted to 🟢 ratified.

- **PCDN-SOS-08-E-001 — Class hierarchy depth.** Flat (one driver + one checker per region) or layered (intermediate stimulus generator / scoreboard / transaction abstractions)? Flat is simpler to emit and debug; layered tracks more closely with house-style enterprise verification practices. **Recommendation**: **flat at v1**. The class hierarchy depth is a refactoring concern that can be revisited once the v1 emission lands; introducing intermediate layers prematurely complicates the codegen for benefit that depends on user-side conventions. Layered emission is a SOS-08-E follow-on if a customer requests it.

- **PCDN-SOS-08-E-002 — Verilator-subset compliance.** Declare an explicit SV-2017 feature subset the emitted testbench restricts itself to (so Verilator runs everything), or rely on Verilator's documented subset (so Verilator runs what it can and falls back to deferred-failure stubs for the rest)? **Recommendation**: **rely on Verilator's documented subset** + INV-S-HDL-E-6 (deferred-failure stub for unsupported features). Pinning the codegen to a hand-curated subset would lag Verilator's evolving capability; the deferred-failure-stub pattern keeps Verilator usable for the cases it supports without blocking the commercial-simulator path on Verilator's limits.

- **PCDN-SOS-08-E-003 — Coverage emission.** Emit `covergroup` blocks alongside the testbench (functional coverage), or defer coverage to a future phase? `covergroup` is supported by all four commercial simulators + Verilator's `--coverage` flag. **Recommendation**: **defer to a future phase** (SOS-08-E follow-on or a dedicated SOS-08 sub-phase). Coverage adds emission complexity and the bounded-reachability verification claim already provides exhaustive coverage within the bound — `covergroup`-based functional coverage adds value only when stimulus is not exhaustive, which is exactly what SOS-08-E does NOT do.

- **PCDN-SOS-08-E-004 — Per-vector or per-region testbench shape.** One testbench file per vector trace (unambiguous failure attribution, higher compile cost) or one testbench per chart region covering all that region's vectors (lower compile cost, coarser attribution)? **Recommendation**: **per-region at v1** with checker reset between traces. Compile cost dominates for FPGA-scale designs; per-vector emission can be revisited if a debugging-attribution pain point emerges. The chart-vocabulary failure message in the checker class includes the vector ID, so attribution is recoverable even in per-region shape.

- **PCDN-SOS-08-E-005 — Simulator-specific build script structure.** Emit a separate `.do` / `.tcl` / `Makefile` / `.sh` per simulator (explicit per-tool wrapper; the LCD-path-honest form) or one unified `Makefile`-based wrapper with simulator-selection variables (`make sim=questa`, `make sim=vcs`, etc.)? **Recommendation**: **separate wrappers** per simulator. Each commercial simulator has its own idioms (Questa's `do` file convention, VCS's `vcs` flag conventions, Xcelium's `irun` argument files); a unified wrapper either lowest-common-denominators all of them into awkward shape, or grows simulator-conditional logic that's harder to maintain than four small scripts. The codegen tool emits all wrappers; the user runs whichever they have a licence for.

## 12. Acceptance checklist

A conforming SOS-08-E ratification satisfies:

- (a) ⏸ PCDN-SOS-08-E-001 through 005 resolved (§11).
- (b) ⏸ The codegen tool emits, per chart region, the artifacts named in §6 table: top-level testbench, driver class, checker class, virtual interface, SVA bind file (mirrored from SOS-08-D), JSONL vector trace.
- (c) ⏸ Build wrappers emitted per simulator named in §5.3 (Questa, Riviera, VCS, Xcelium, Verilator).
- (d) ⏸ Cross-phase invariants INV-SOS-A through H cited in each emitted testbench's header comment.
- (e) ⏸ Cross-sub-phase invariants INV-S-HDL-1 through 5 cited per artifact (INV-S-HDL-1 on driver/checker port surface; INV-S-HDL-5 on failure-message format).
- (f) ⏸ Cross-sub-phase invariants INV-S-HDL-E-1 through 6 satisfied (verified by codegen lints + a "no-randomize / no-UVM / no-inline-assert" emission audit).
- (g) ⏸ At least one chart region's SV testbench runs successfully on **two** commercial simulators (any two of Questa/Riviera/VCS/Xcelium — environment-dependent which two the developer has access to) and on Verilator (for the supported-subset properties).
- (h) ⏸ The same chart region's SV testbench produces byte-identical pass/fail verdict as the SOS-08-D cocotb testbench for the same vector set. Cross-path equivalence is the load-bearing claim of the dual-emission design.

(a) is the ratification gate; (b)-(h) are implementation gates that flip from ⏸ to ✅ as the implementation lands.

A conforming SOS-08-E **without** Verilator support (commercial-only deployment) satisfies (a)-(f) and (h), with (g) reduced to "two commercial simulators." This second-tier conformance level supports shops with no open-source-tool footprint.

## 13. Files cited

| Path | Role |
|---|---|
| `docs/concepts/SOS-08-CONCEPTS.md` | Umbrella; this sub-phase's parent. |
| `docs/concepts/SOS-08-A-CONCEPTS.md` | L0 primitive contracts; cited as the per-primitive cocotb test owner. |
| `docs/concepts/SOS-08-B-CONCEPTS.md` | L1 service composition; cited as the chart-author-facing verb set. |
| `docs/concepts/SOS-08-D-CONCEPTS.md` | Sibling primary path (cocotb + SVA); owns the SVA bind file artifact this doc mirrors. |
| `docs/concepts/SOS-07-CONCEPTS.md` | Cross-phase invariants INV-SOS-A through H; cited not redefined. |
| `docs/concepts/SOS-03-CONCEPTS.md` | Vector schema (`expected` field per §7.1); JSONL trace consumer contract. |
| `docs/concepts/SOS-ROADMAP-07-PLUS.md` | Informative roadmap; EOQ-003 resolution (vector emission priority). |
| `tb/sv/<region>/tb_<region>.sv` | Per-region SV testbench top-level (forthcoming). |
| `tb/sv/<region>/sos_driver_<region>.sv` | Stimulus driver class (forthcoming). |
| `tb/sv/<region>/sos_checker_<region>.sv` | Response checker class (forthcoming). |
| `tb/sv/<region>/dut_if_<region>.sv` | Virtual interface (forthcoming). |
| `tb/sv/<region>/<region>_sva_bind.sv` | SVA bind file (SOS-08-D-owned, mirrored here; forthcoming). |
| `tb/sv/<region>/vectors/<region>.jsonl` | Bounded-reachability vector trace (chart-emitted; forthcoming). |
| `tb/sv/<region>/run.do` | Questa/Riviera build wrapper (forthcoming). |
| `tb/sv/<region>/Makefile.sv` | VCS build wrapper (forthcoming). |
| `tb/sv/<region>/run_xrun.sh` | Xcelium build wrapper (forthcoming). |
| `tb/sv/<region>/run_verilator.sh` | Verilator build wrapper (forthcoming). |
| Parent `CLAUDE.md` | Spec-Before-Code Planning Discipline; Phase document shape. |

## 14. Unblocks

This sub-phase's ratification (after PCDN walkthrough) unblocks:

- **The codegen tool's SV emission path** — depends on the testbench artifact contract frozen here.
- **The umbrella's §12 (b) gate** — each sub-phase's concept doc ratified is a prerequisite for the umbrella's full conformance.
- **Customer adoption from commercial-simulator-only shops** — the existence of a documented LCD path is what makes the conversation tractable.

This sub-phase does NOT block:

- **SOS-08-D ratification** — SOS-08-D and SOS-08-E are sibling sub-phases that ratify independently. The SVA bind file contract is SOS-08-D's authority; SOS-08-E mirrors it once ratified.
- **SOS-08-F (UVM sequences)** — SOS-08-F is its own sub-phase with its own ratification cycle.

## 15. Change log

### 2026-05-23 — Initial draft (Ira)

- Authored `SOS-08-E-CONCEPTS.md` as the SystemVerilog testbench + SVA bind file emission sub-phase under the SOS-08 umbrella.
- §3 canonical glossary: terms `SV testbench`, `stimulus driver class`, `response checker class`, `SVA bind file` (mirror from SOS-08-D), `build wrapper`, `per-vector test`, `per-region test`, `class hierarchy depth`.
- §4 source-of-truth map: per-region testbench artifacts at `tb/sv/<region>/`; SVA bind files mirror SOS-08-D.
- §5 frozen decisions: class-based, self-checking, constrained-random-free, UVM-free (umbrella §6 framing); SVA bind file mirror with SOS-08-D; target simulator set (Questa, Riviera, VCS, Xcelium, Verilator); JSONL vector IR consumption; chart-vocabulary failure-message format.
- §6 emission contract: artifact table per chart region; stimulus driver class contract; response checker class contract; top-level testbench module contract; build wrapper contract.
- §7 cross-sub-phase invariants INV-S-HDL-E-1 through 6: no constrained-random; no UVM imports; SVA only via `bind`; chart-vocabulary failure messages; per-simulator build wrapper; Verilator-subset compliance declared not assumed.
- §8 standards integration matrix additions: four commercial-simulator vendors (Questa, Riviera, VCS, Xcelium) declared as `derive` relationships; Verilator row narrowed from SOS-08 §8's cocotb-context entry.
- §10 reconciliation vs SOS-08-D (sibling, primary path; shared SVA bind files), SOS-08-F (UVM sequences boundary), SOS-08-A (L0 primitive tests scope), and SOS-03 (vector schema reuse).
- §11 five PCDNs raised covering class hierarchy depth, Verilator-subset compliance, coverage emission, per-vector vs per-region shape, and simulator-specific build script structure.
- §12 acceptance checklist: gates (a)-(h); reduced conformance level for commercial-only-no-Verilator deployments.

Status: 🟡 **drafted**, awaiting PCDN walkthrough.

### 2026-05-23 — Ratified after PCDN walkthrough (Ira)

All five PCDNs from §11 resolved with recommendations accepted.

- **PCDN-SOS-08-E-001 → RESOLVED**: class hierarchy depth is **flat** at v1 (one driver + one checker per region). Layered emission is a SOS-08-E follow-on if a customer requests it.
- **PCDN-SOS-08-E-002 → RESOLVED**: Verilator-subset compliance — rely on Verilator's documented subset plus INV-S-HDL-E-6 deferred-failure stubs for unsupported features. Avoids pinning the codegen to a hand-curated subset that would lag Verilator's evolving capability.
- **PCDN-SOS-08-E-003 → RESOLVED**: coverage emission **deferred** to a future phase. Bounded-reachability verification already provides exhaustive coverage within the bound.
- **PCDN-SOS-08-E-004 → RESOLVED**: per-region testbench shape at v1 (one testbench file per chart region covering that region's vectors). Compile cost dominates at FPGA-scale; checker-class chart-vocabulary failure message preserves vector-level attribution.
- **PCDN-SOS-08-E-005 → RESOLVED**: separate simulator-specific wrappers per simulator (Questa `.do`, VCS `.sh`, Xcelium `irun` argument file, Riviera `.tcl`, Verilator `Makefile`). Codegen tool emits all wrappers; user runs whichever simulator they have a licence for.

**§5 / INV amendments**:
- §5 frozen-decisions extended with the five resolutions above by reference.
- INV-S-HDL-E-6 (Verilator-subset compliance declared not assumed) wording extended: "the testbench-emit path detects unsupported SV-2017 features and emits deferred-failure stubs with chart-vocabulary failure messages per INV-S-HDL-5; commercial simulators run the full path unchanged".
- INV-S-HDL-E-5 (per-simulator build wrapper) wording extended: "five wrappers emitted per chart region: Questa `.do`, VCS `.sh`, Xcelium argument file, Riviera `.tcl`, Verilator `Makefile`".

**Status**: 🟢 **ratified**. Implementation of the SV testbench emission path in `tools/sos-codegen/` is now unblocked. SOS-08-E composes with SOS-08-D (cocotb path) via the shared vector-IR boundary frozen in SOS-08-D ratification; SVA bind files are mirrored byte-identical from SOS-08-D per §4 source-of-truth.
