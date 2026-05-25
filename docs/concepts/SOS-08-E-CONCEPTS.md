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

### 2026-05-23 — Impl wave-1 scaffold (Ira)

Wave-1 implementation surface landed under the 2026-05-23 ratification of §15 above. This entry records what shipped, what remains scaffold, and what is wave-2 work.

**Wave-1 implementation surface**:

- **`transliterate_hdl_sv_tb.py` walker** (~720 LOC) emits eight artifacts per single-region chart, all rooted under `tb/sv/<chart>/`:
    - `tb_<chart>.sv` — top-level testbench module per §6.3 (instantiates DUT + virtual interface + driver + checker; fork-joins; emits `[PASS]` / `[FAIL count=N]` summary).
    - `sos_driver_<chart>.sv` — stimulus driver class per §6.1 (consumes JSONL trace via `$fopen` / `$fgets`; drives only DUT inputs through the `driver_mp` modport; emits `[DRIVE] V<n>` log lines in chart vocabulary).
    - `sos_checker_<chart>.sv` — response checker class per §6.2 (observes via `checker_mp` modport; emits `[FAIL] vector V<n>: chart `<chart>`` chart-vocabulary failure messages per §5.5 + INV-S-HDL-E-4; exposes `get_fail_count()` for the top-level exit-status decision).
    - `dut_if_<chart>.sv` — virtual interface with `driver_mp` + `checker_mp` modports.
    - `<chart>_fsm_sva.sv` — SVA assertion module **byte-identical** to the SOS-08-D emit per §5.2 + INV-S-HDL-D-4 (the walker imports `transliterate_sva_bind.render_target` and re-keys the resulting filenames under `tb/sv/<chart>/`).
    - `<chart>_fsm_bind.sv` — SVA bind directive, also byte-identical to SOS-08-D.
    - `run_verilator.mk` — Verilator build wrapper per §6.4 + INV-S-HDL-E-5 (the open-source-runnable target; `--assert --timing` flags enabled; compiles all six SV files in dependency order).
    - `run.do` — Questa / Riviera build wrapper, reference shape per PCDN-SOS-08-E-005. The commercial-reference path; vsim + vlog invocation skeleton with `-assertdebug`. Smoke-tested but not full CI.
- **Invariant audit by construction** (`_audit_all`): every emitted file is post-pass scanned for INV-S-HDL-E-1 (no `randomize` / `constraint` / `rand` / `randc`), INV-S-HDL-E-2 (no UVM imports or macros), and INV-S-HDL-E-3 (no inline `assert property` in non-bind files). Any hit raises `InvariantAuditError` — signals an internal walker bug, not a chart-author error. Bind files are exempt from INV-S-HDL-E-3 by design.
- **CLI integration** in `main.py`: new `--target sos-08-e` choice + `_render_sos_08_e_target` dispatcher; the `cocotb_sva_config` dict (already carrying `chart_name`) is forwarded to the walker. The dry-run and `--out` directory write paths already handle dict-output targets; `sos-08-e` slots into the existing `("hdl-vhdl", "hdl-sv", "cocotb", "sva", "sos-08-d")` list.
- **End-to-end tests** at `tools/sos-codegen/tests/test_transliterate_hdl_sv_tb.py` (60 tests, all passing). Coverage: file-set + naming conventions; top-level testbench module shape; driver class contract; checker class contract; virtual interface modports; SVA bind file byte-identical mirror with SOS-08-D; Verilator + Questa build wrapper contents; invariant satisfaction audit (E-1, E-2, E-3, E-4, E-5); parallel-chart rejection; audit error path (positive + negative); non-dict input rejection.

**Wave-1 scope (what landed vs. what is deferred)**:

- Single-region charts emit a working test-bench artifact set; parallel charts are rejected with a clear `UnsupportedChartError` citing the wave-2 boundary (per-region split co-deferred with the SOS-08-D wave-2 parallel-chart support).
- JSONL trace consumption uses a minimal `{"event": N, "cycles": N, "expected_state": N}` shape parsed by a hand-rolled in-class JSON-Lines integer-field extractor. Per §5.4 the full SOS-03 vector-schema parser (a precompiled SV utility module) lands in wave-2 alongside SOS-08-D's `post_results.py` JUnit emission. The hand-rolled extractor is INV-S-HDL-E-1-conforming (no `randomize` helpers) and supports the wave-1 walker's emitted contract.
- Two build wrappers shipped (`run_verilator.mk` + `run.do`); VCS `Makefile.sv`, Xcelium `run_xrun.sh`, and a fully-functional Riviera-PRO `.tcl` wrapper distinct from the Questa form land in wave-2 per PCDN-SOS-08-E-005's "separate wrappers per simulator" resolution. INV-S-HDL-E-5 wave-1 satisfaction is "at least one wrapper per the two supported-at-CI simulator families"; full five-wrapper coverage is INV-S-HDL-E-5's wave-2 ratification gate.
- The driver's `parse_int_field` SV function is a wave-1 LCD-form integer-field extractor; floating-point and string-valued JSON fields are not yet supported because the wave-1 vector schema is integer-keyed. Wave-2 swaps in a full JSON parser when the SOS-03 schema gains non-integer fields.
- Class hierarchy depth is **flat** per PCDN-SOS-08-E-001 (one driver + one checker class per region). Layered emission (stimulus generator / scoreboard / transaction abstraction) is a SOS-08-E follow-on if a customer requests it.
- `covergroup`-based functional coverage is **deferred** per PCDN-SOS-08-E-003. The bounded-reachability verification claim already provides exhaustive coverage within the bound.

**Wave-2 candidates** (recorded explicitly so the boundary is unambiguous):

- **VCS `Makefile.sv` + Xcelium `run_xrun.sh` + Riviera `.tcl` wrappers** per PCDN-SOS-08-E-005 separate-wrappers-per-simulator. Wave-1 ships Verilator + Questa; wave-2 closes the five-wrapper INV-S-HDL-E-5 gate.
- **Parallel-chart support**: per-region testbench split alongside SOS-08-D wave-2's per-region SVA bind shape. Currently the walker raises `UnsupportedChartError` on any `<parallel>` block.
- **Full SOS-03 vector-schema consumption**: precompiled SV utility module (e.g. `sos_jsonl_parser_pkg`) that decodes the full vector schema rather than the wave-1 LCD integer-field shape. Lands alongside SOS-08-D `post_results.py` JUnit emission.
- **Cross-path equivalence test** with SOS-08-D per §12 (h): a CI gate that runs the same vector set against both the cocotb path and the SV testbench path and confirms byte-identical pass/fail verdict. This is the load-bearing claim of the dual-emission design.
- **Layered class hierarchy opt-in** per PCDN-SOS-08-E-001 if a customer requests it (intermediate stimulus generator / scoreboard / transaction abstractions). Wave-1 ships the flat shape.
- **Verilator deferred-failure stub** per INV-S-HDL-E-6 for SV-2017 features outside Verilator's supported subset. Wave-1's emitted SV uses classes + virtual interfaces + file I/O — all supported. Wave-2 enriches if/when chart authors annotate guards / properties that require constructs outside Verilator's subset.

**Cited invariants** (all upheld by wave-1 surface): INV-S-HDL-E-1 (no constrained-random — audit passes), INV-S-HDL-E-2 (no UVM imports — audit passes), INV-S-HDL-E-3 (SVA only via bind files — audit passes, bind files exempted by design), INV-S-HDL-E-4 (chart-vocabulary failure messages — checker's `[FAIL] vector V<n>: chart `<chart>`` prefix), INV-S-HDL-E-5 (per-simulator build wrapper — Verilator + Questa wave-1; full five wave-2), INV-S-HDL-E-6 (Verilator-subset compliance — wave-1 stays within Verilator's supported SV-2017 subset).

**Cited PCDNs** (all resolved 2026-05-23 §15 ratification entry above, implementation now in place): PCDN-SOS-08-E-001 (flat class hierarchy at v1), PCDN-SOS-08-E-002 (Verilator-subset compliance via deferred-failure-stub policy), PCDN-SOS-08-E-003 (coverage emission deferred), PCDN-SOS-08-E-004 (per-region testbench shape at v1), PCDN-SOS-08-E-005 (separate simulator wrappers — wave-1 ships two of five; wave-2 closes the remaining three).

**Status**: 🟢 **ratified (continuing)** — wave-1 scaffold lands the SV-testbench emission path with single-region chart coverage; parallel-chart split, full five-simulator wrapper coverage, and cross-path equivalence with SOS-08-D are wave-2 work.

### 2026-05-23 — Impl wave-2: full simulator-wrapper coverage + cross-path equivalence with SOS-08-D (Ira)

Wave-2 closes two of the wave-1 deferred candidates: (a) the remaining three of five simulator build wrappers (VCS / Xcelium / Riviera) per PCDN-SOS-08-E-005, and (b) cross-path equivalence with the SOS-08-D cocotb path per §12 gate (h). Parallel-chart support on the SV-testbench side is **still wave-3** (co-deferred with SOS-08-D wave-3's per-region step-driven vectors + multi-clock-domain bind wiring).

**Wave-2 implementation surface**:

- **VCS `Makefile.sv`** emitted via `_emit_vcs_makefile`. Synopsys VCS uses `vcs` (compile) + `./simv` (run) with `-sverilog -assert enable_diag -debug_access+all` flag set. Targets the chart-top wrapper module; lists all six SV sources in dependency order. `make compile` / `make run` / `make clean` targets.
- **Xcelium `run_xrun.sh`** emitted via `_emit_xcelium_argfile`. Cadence Xcelium uses `xrun -sv -access +rwc -assert -assertinitvar`. Bash script with `set -euo pipefail`; honors `XRUN` env var override for custom Xcelium installs. `-gui` flag opens SimVision after elaboration.
- **Riviera-PRO `run_riviera.tcl`** emitted via `_emit_riviera_tcl`. Aldec Riviera uses `alog -sv2k17` (compile) + `asim` (elaborate + run) — distinct from Questa's `vlog`/`vsim` so wave-2 split the previously-shared `.do` form. Wave-1's `run.do` is now Questa-specific (header text updated; flag set unchanged).
- **Filename additions** to `render_target`: three new keys under `tb/sv/<chart>/`:
    - `Makefile.sv`         (VCS)
    - `run_xrun.sh`         (Xcelium)
    - `run_riviera.tcl`     (Riviera-PRO)
  Emit count grows from 8 to **11 files** per single-region chart.
- **Cross-path equivalence test class** in `tools/sos-codegen/tests/test_transliterate_hdl_sv_tb.py::TestCrossPathEquivalenceWithSOS08D` (5 tests). Verifies §12 gate (h):
    - SVA assertion module byte-identical between SOS-08-D (`tests/<chart>/<chart>_fsm_sva.sv`) and SOS-08-E (`tb/sv/<chart>/<chart>_fsm_sva.sv`).
    - SVA bind directive byte-identical between the two paths.
    - Equivalence holds across a chart with transition guards (the SVA bind walker lowers guards into the assertion antecedent; both paths produce identical lowered text).
    - **Path-disjointness sanity checks**: SOS-08-E does NOT emit `.py` (cocotb territory); SOS-08-D does NOT emit `tb_*.sv` / `sos_driver_*.sv` / `sos_checker_*.sv` / `dut_if_*.sv` (SOS-08-E territory).
- **`TestWave2BuildWrappers` class** (10 tests): per-wrapper presence + simulator-tool invocation pattern + SVA-flag presence + bash-shebang correctness for the shell wrapper + Questa vs Riviera content divergence (regression guard against accidentally collapsing the wave-2 split back to wave-1's shared form).
- **Existing `TestFileSet.test_emits_eight_files` renamed to `test_emits_eleven_files`** to reflect the new emit count; the three new wrapper-presence assertions add to the suite.

**Wave-2 scope (what landed vs. what is deferred)**:

- **All five simulator wrappers** ✅ landed. INV-S-HDL-E-5's "per-simulator build wrapper for each named simulator" gate is now fully satisfied — Verilator + Questa + VCS + Xcelium + Riviera-PRO.
- **Cross-path equivalence** with SOS-08-D ✅ verified at the SVA artifact level (gate (h) byte-identical claim). Live cross-path equivalence (running both paths against a real DUT and comparing pass/fail verdict) requires bench validation — that lands with the umbrella's gate (e) Lattice ECP5 dev board session per the wave-1 conformance review's wave-2 plan.
- **Parallel-chart support** on the SV-testbench side: **wave-3 scope**. Currently wave-1's parallel-chart rejection is still in place in this walker (single-region only). Lifting it requires per-region observable read against the chart-top wrapper (mirror of SOS-08-D wave-2c), plus per-region SVA bind co-emission (mirror of SOS-08-D wave-2b). The SVA bind walker's wave-2b support is already available; the SV-testbench walker's wave-3 lift composes against it.
- **Full SOS-03 vector-schema consumer** (replacing the wave-1 LCD integer-field shape): **wave-3** alongside the SOS-08-F wave-3 parser landing (co-deferred to land once and serve both walkers).
- **Layered class hierarchy opt-in** (PCDN-SOS-08-E-001): wave-3+ if a customer requests it.
- **Verilator deferred-failure stubs** (INV-S-HDL-E-6): wave-3+ when chart authors actually use SV-2017 constructs outside Verilator's subset.

**Invariants upheld**:

- **INV-S-HDL-E-1** (no constrained-random): retained — wave-2 audit passes on all 11 emitted files (the three new wrappers are Makefile / shell / Tcl, none of which carry SV constructs).
- **INV-S-HDL-E-2** (no UVM imports): retained — none of the new wrappers reference UVM.
- **INV-S-HDL-E-3** (SVA only via bind files): retained — wrappers don't emit SVA; they invoke the simulator against the SV sources that do.
- **INV-S-HDL-E-4** (chart-vocabulary failure messages): retained — checker class emits `[FAIL] vector V<n>:` regardless of which simulator runs.
- **INV-S-HDL-E-5** (per-simulator build wrapper): ✅ **closed**. All five simulators have a wrapper.
- **INV-S-HDL-E-6** (Verilator-subset compliance declared): retained.
- **INV-S-HDL-D-4** (same SVA artifact feeds cocotb + formal flow): **explicitly verified by test** at this wave — the cross-path equivalence test class proves the SVA artifact is byte-identical between SOS-08-D and SOS-08-E emissions.

**Test count**: 18 new tests:

- `TestFileSet`: 1 renamed (`test_emits_eight_files` → `test_emits_eleven_files`) + 3 new wrapper-presence tests.
- `TestWave2BuildWrappers` class: 10 tests covering per-wrapper invocation patterns + flag presence + Questa-vs-Riviera split regression guard.
- `TestCrossPathEquivalenceWithSOS08D` class: 5 tests covering SVA module + bind directive byte-identical equivalence + guard-lowering equivalence + path-disjointness sanity checks.

**Test suite**: 354/354 passing (336 prior + 18 wave-2).

**Cited PCDNs**: PCDN-SOS-08-E-005 (separate wrappers per simulator — wave-2 closes the remaining three of five); §12 gate (h) cross-path equivalence with SOS-08-D (verified at SVA artifact byte-identical level).

Status: 🟢 **ratified (continuing)** — wave-2 closes the simulator-wrapper coverage and the cross-path equivalence gate. Wave-3 lifts parallel-chart support on the SV-testbench side (composing against SOS-08-D wave-2b's already-landed parallel SVA bind support) + the full SOS-03 vector-schema consumer + Verilator deferred-failure stubs + layered class hierarchy opt-in.

### 2026-05-24 — Impl wave-3: parallel-chart support + Verilator deferred-failure stubs (Ira)

Wave-3 closes two of the four wave-2-deferred candidates: (a) parallel-chart support on the SV-testbench side (mirror of SOS-08-D wave-2c's per-region observable shape, composing against the already-landed SOS-08-D wave-2b parallel SVA bind support), and (b) the Verilator deferred-failure-stub policy header ratifying INV-S-HDL-E-6 per PCDN-SOS-08-E-002 resolution. The full SOS-03 vector-schema consumer + layered class hierarchy opt-in remain wave-3-future co-deferred work.

**Wave-3 implementation surface**:

- **Parallel-chart dispatch** in `render_target`: the wave-1 `UnsupportedChartError` raised on `_chart_has_parallel(...)` is now gated on `_collect_regions(chart_ir)`. Non-empty regions → parallel emit path; empty → wave-1 single-region path (unchanged). The single-region path stays byte-identical with wave-2 emission for INV-S-HDL-E-5/-E-6 regression-free conformance.

- **`_collect_regions(chart_ir)`** new helper: returns `[(region_name, initial_state, [state_ids]), ...]` for a parallel chart; empty list for single-region. Mirrors `transliterate_sva_bind._collect_parallel_regions` but also extracts the per-region initial-state + state-list (the SV testbench walker needs both for the per-region checker emit).

- **`_emit_virtual_interface_parallel(chart, regions)`** new emitter: emits `dut_if_<chart>.sv` with per-region `current_state_<region>` output ports + per-region `N_STATES_<REGION>` parameters. Both `driver_mp` and `checker_mp` modports list each per-region observable as an input. Mirrors the SOS-08-C §6.10 chart-top wrapper convention so the SVA bind targets the SAME ports the testbench checker reads.

- **`_emit_checker_class_parallel(chart, regions)`** new emitter: per-region checker logic. The checker reads `vif.current_state_<region>` per region, parses `expected_state_<region>` integer fields from the trace JSONL (mirror of the SOS-03 wave-3 schema extension for per-region expected states), and emits chart-vocabulary failure messages per INV-S-HDL-E-4 that NAME the failing region. The hand-rolled integer-field extractor (`parse_int_field`) from the single-region walker is copied through unchanged so INV-S-HDL-E-1 (no constrained-random) audit passes.

- **`_emit_top_module_parallel(chart, regions)`** new emitter: top-level testbench instantiates the chart-top wrapper (`<chart>_fsm` per SOS-08-C §6.10 — same module name the SVA bind targets), wires per-region observable ports + per-region `N_STATES_<REGION>` parameter overrides, and `\`include`s the new `verilator_stubs.svh` header so the deferred-failure-stub macros are available in the testbench file.

- **`_emit_verilator_stubs_svh(chart)`** new emitter: emits `verilator_stubs.svh` — the deferred-failure-stub policy header per INV-S-HDL-E-6 / PCDN-SOS-08-E-002. Defines `\`SOS_VERILATOR_SKIP_BEGIN/END` macros (wrap a block; commercial sims run it, Verilator stubs it) + `\`SOS_VERILATOR_DEFERRED(<feature>)` single-statement macro form. Branches on `\`ifdef VERILATOR`; the Verilator path's deferred-failure message names the chart per INV-S-HDL-E-4. Always co-emitted (one per chart emit, single-region + parallel both).

- **`_audit_verilator_subset(filename, source)`** new audit function: scans emitted files for SV-2017 constructs outside Verilator's documented subset per the curated `_VERILATOR_UNSUPPORTED_CONSTRUCTS` catalog. Returns SOFT advisories rather than raising — INV-S-HDL-E-6 is the deferred-failure-stub policy, not a rejection. Bind files / Makefiles / Tcl wrappers / the stubs header itself are exempt. Wave-3 emit (single-region + parallel) passes the audit cleanly; the function + catalog are infrastructure for future emit extensions that may land features outside the Verilator subset (e.g. covergroup-based functional coverage per PCDN-SOS-08-E-003).

**Per-chart emit counts (wave-3)**:

| Shape | File count | Composition |
|---|---|---|
| Single-region | 12 | 4 SV core (vif/driver/checker/top) + 5 wrappers + 1 wave-3 stubs header + 2 wave-1/-2 SVA bind (sva.sv + bind.sv) |
| Parallel (N regions) | 10 + 2N | 4 SV core + 5 wrappers + 1 stubs header + 2N per-region SVA bind |

For the canonical 2-region test fixture (`left` + `right`): 14 files. For the SOS-08-A `rtos_kernel` chart with 4 regions: 18 files (the count scales linearly with region count via the SVA bind co-emit; the four SV core files + five wrappers + one stubs header are constant per chart).

**Wave-3-future boundary** (explicit out-of-scope for this wave):

- **Full SOS-03 vector-schema consumer** replacing the LCD integer-field parser. Co-deferred with SOS-08-F wave-3 parser landing (one parser shared across SOS-08-E + SOS-08-F to avoid drift).
- **Layered class hierarchy opt-in** (PCDN-SOS-08-E-001): wave-3+ if customer-requested.
- **Per-region SVA datamodel-binding** for parallel charts (mirror of single-region SOS-08-C wave-3-f's `<assign>` lowering). Composes against the wave-3-f single-region work once it lands.
- **Multi-clock-domain parallel charts** (per-region `clk_<dom>` / `rst_<dom>` on the chart-top wrapper per SOS-08-C §6.10's multi-clock contract). Wave-2b ratified single-clock parallel as the v1 baseline; wave-3 inherits that constraint.

**Invariants upheld**:

- **INV-S-HDL-E-1** (no constrained-random): retained — the parallel-chart checker reuses the hand-rolled `parse_int_field` extractor verbatim from the single-region walker; the audit pass scans all 14 emitted files (parallel case) and returns clean.
- **INV-S-HDL-E-2** (no UVM imports): retained — no UVM imports anywhere in the parallel emit.
- **INV-S-HDL-E-3** (no inline `assert property` outside bind files): retained — the parallel checker class carries no `assert property`; all SVA goes through the SOS-08-D wave-2b bind-files mirror.
- **INV-S-HDL-E-4** (chart-vocabulary failure messages): **strengthened** — parallel-chart failures NAME the region in the failure message (``[FAIL] vector V%0d region `<region>` chart `<chart>`: expected_state=%0d ...``), so a CI failure on a 4-region chart immediately localises which region's transition mispred.
- **INV-S-HDL-E-5** (per-simulator build wrapper): retained — the five wave-2 wrappers cover both single-region + parallel emit paths (the wrappers are simulator-specific, not emit-shape-specific).
- **INV-S-HDL-E-6** (Verilator-subset compliance declared not assumed): **RATIFIED via wave-3 stub-policy header** — the catalog + audit + macros are now in place; the wave-3 emit set passes the audit cleanly; future emit extensions that land features outside Verilator's subset MUST wrap them in `\`SOS_VERILATOR_SKIP_BEGIN/END` or use `\`SOS_VERILATOR_DEFERRED(<feature>)`.

**Test count**: 23 new tests across three test classes:

- `TestWave3ParallelChartEmit` (11 tests): file count, per-region SVA bind co-emit, per-region observables on vif, both modports list observables, per-region checker reads + parse calls + failure messages, top instantiates chart-top wrapper, per-region `N_STATES` localparams, chart-vocabulary failure rendering, audit cleanliness, stubs-header inclusion, single-region path unchanged.
- `TestWave3VerilatorStubsHeader` (6 tests): SKIP_BEGIN/END + DEFERRED macros, `\`ifdef VERILATOR` branch, INV-E-6 + PCDN-E-002 citations, chart-vocabulary message naming, include guards.
- `TestWave3VerilatorSubsetAudit` (5 tests): wave-3 emit audit-clean; audit catches covergroup; audit exempts bind files / build wrappers / stubs header itself.
- `TestWave3SvaBindParityWithSOS08D` (1 test): per-region SVA bind files byte-identical between SOS-08-D + SOS-08-E walkers (extends wave-2's single-region byte-identical claim to parallel).

**Test suite**: 527/527 passing (504 prior + 23 wave-3).

**Cited PCDNs**: PCDN-SOS-08-E-002 (Verilator-subset compliance via deferred-failure stubs — wave-3 ratifies); PCDN-SOS-08-E-004 (per-region testbench shape at v1 — wave-3 implements); PCDN-SOS-08-E-001 (flat class hierarchy at v1 — wave-3 preserves); §12 gate (h) cross-path equivalence with SOS-08-D (extended to parallel charts).

Status: 🟢 **wave-3 complete** — parallel charts emit cleanly through the SV-testbench walker; Verilator deferred-failure-stub policy header ratifies INV-S-HDL-E-6. Wave-3-future tracks the full SOS-03 vector-schema consumer + layered class hierarchy opt-in + per-region SVA datamodel-binding + multi-clock-domain parallel-chart wiring.

### 2026-05-24 — Impl wave-3-future: full SOS-03 vector-schema consumer (Ira)

Lands the first wave-3-future carry-forward: the **full SOS-03 vector-schema consumer**. Wave-1's emitted SV checker consumed a minimal `{"event": N, "cycles": N, "expected_state": N}` JSONL shape via a hand-rolled inline `parse_int_field` function duplicated across driver + checker classes. Wave-3-future:

1. Factors the inline parser into a shared SystemVerilog header (`sos_jsonl_parser_pkg.svh`) — driver + checker + parallel-checker source from one parser implementation.
2. Adds string-field extraction (`sos_jsonl_parse_string`) — SOS-03's §15 2026-05-24 schema extension uses string-valued `expected_state` names; the SV checker now consumes them directly.
3. Emits a per-chart state symbol table (`sos_<chart>_state_symbols.svh`) — single function `sos_<chart>_state_id_of(string name) → int` resolving chart-state names to their document-order one-hot bit position (matching SOS-08-C `_emit_state_constants` encoding).
4. Extends the single-region + parallel checkers to consume the string-valued `expected_state_str` / `expected_state_<region>_str` fields via the symbol table. Wave-1/2 integer-only traces keep working unchanged via the backwards-compatible fall-through.

**Implementation surface** (one walker, two new emitters):

- **`_emit_jsonl_parser_pkg(chart_name)` (new)** — emits `sos_jsonl_parser_pkg.svh` carrying `sos_jsonl_parse_int(line, key, value)` + `sos_jsonl_parse_string(line, key, value)`. Header-only (`\`include`-able), include-guard form. Per-chart guard name `SOS_JSONL_PARSER_PKG_<CHART>_SVH` ensures the same header file co-exists across multiple per-chart SV testbenches in one compilation unit without redefinition collisions. The string-extractor caps its inner loop at 1024 characters to bound malformed-line behaviour (no spinning on a line that drops its closing quote).
- **`_emit_state_symbols(chart_name, state_ids)` (new)** — emits `sos_<chart>_state_symbols.svh`. Single function (`function automatic int sos_<chart>_state_id_of(input string name)`) with a straight-line if/elsif chain over the chart's states in document order. Each `if (name == "<state_id>") return <idx>;` line; `return -1;` terminator for unknown names. Parallel charts get a flattened symbol table covering EVERY region's states so any `expected_state_<region>_str` value can resolve.
- **`_emit_driver_class` (extended)** — adds `\`include "sos_jsonl_parser_pkg.svh"`; calls `sos_jsonl_parse_int(line, "event", event_code)` + `sos_jsonl_parse_int(line, "cycles", cycles_wait)` instead of the inline form; removes the inline `parse_int_field` function from the emitted class body. INV-S-HDL-E-3 audit preserved (no `assert property`); INV-S-HDL-E-1 preserved (pure procedural SV).
- **`_emit_checker_class` (extended)** — adds both `\`include`s + per-line dual parse: integer (`expected_state`) AND optional string (`expected_state_str`). When the string field is present, the value is resolved via `sos_<chart>_state_id_of` to its bit position; the one-hot value `1 << bit_idx` is then compared against `current_state`. Unknown-state-string surfaces as a chart-vocabulary failure (`expected_state_str=\"<x>\" is not a known chart-state`) per INV-S-HDL-E-4 + INV-SOS-H. When only the integer field is present, the legacy wave-1/2 comparison path runs unchanged — backwards-compatible by construction.
- **`_emit_checker_class_parallel` (extended)** — same per-region: each region declares its own `expected_state_<region>_str` + parses + resolves via the symbol table. The per-region failure-message format names the region AND the chart-state string verbatim, concretising INV-S-HDL-E-4 + INV-SOS-H at the region grain for parallel charts.
- **`render_target` (extended)** — computes `all_state_ids` once (flattens regions for parallel charts), wires both new emit helpers into the file set. Net: every chart's emit grows by exactly two files (parser pkg + state symbols).

**Emit shape (chart-vocabulary trace example)**:

The wave-3-future checker now consumes a SOS-03-aligned trace like:

```jsonl
{"expected_state_str": "active", "cycles": 4}
{"expected_state_str": "idle", "cycles": 2}
```

A mismatch produces a chart-vocabulary failure message naming the state by string:

```
[FAIL] vector V3: chart `demo` expected state="active" (one-hot=0b10) at cycle 40ns; observed current_state=0b01.
```

The string `"active"` round-trips from the trace file through the symbol table to the failure message verbatim — that's INV-S-HDL-E-4's load-bearing concretisation at the chart-vocabulary level.

For parallel charts the per-region trace shape is:

```jsonl
{"expected_state_left_str": "l_active", "expected_state_right_str": "r_idle", "cycles": 1}
```

Each region resolves independently; failure messages name the failing region:

```
[FAIL] vector V5 region `right` chart `p`: expected state="r_idle" (one-hot=0b01) at cycle 50ns; observed current_state=0b10.
```

**Invariants upheld**:

- **INV-S-HDL-E-1** (no constrained-random) — preserved. Both new helpers (`sos_jsonl_parse_int`, `sos_jsonl_parse_string`, `sos_<chart>_state_id_of`) are pure procedural SV. `_audit_emitted_file` continues to pass cleanly.
- **INV-S-HDL-E-2** (no UVM) — preserved.
- **INV-S-HDL-E-3** (no inline `assert property` outside bind files) — preserved.
- **INV-S-HDL-E-4** (chart-vocabulary failure messages) — **strengthened**: failure messages now name chart states by their string identifier when the trace did, removing the wave-1/2 "expected_state=3" integer-bit-pattern form that required the reader to know the encoding.
- **INV-S-HDL-E-5** (per-region testbench shape) — preserved + extended: per-region string-field support adds depth, not new structure.
- **INV-S-HDL-E-6** (Verilator-subset compliance) — preserved: the new helper functions use only basic SV control flow + `string.getc` / `string.len` / string concatenation, all within Verilator's documented subset.
- **PCDN-SOS-08-E-001** (flat class hierarchy at v1) — preserved.
- **PCDN-SOS-08-E-002** (Verilator deferred-failure stubs) — preserved unchanged.
- **PCDN-SOS-08-E-004** (per-region testbench shape) — preserved.
- **SOS-03 §15 2026-05-24 schema extension** (string-valued state names) — **now consumable by the SV-testbench walker directly**. No external Python preflight needed.

**Cross-walker source-of-truth boundary**: the per-chart symbol table uses document-order indices matching SOS-08-C's `_emit_state_constants` exactly. SOS-08-C owns the per-region FSM module's one-hot encoding; this wave-3-future emit mirrors that encoding by-construction through shared `_collect_state_ids` / `_collect_regions` walkers. Any future SOS-08-C refactor that reorders states must propagate to SOS-08-E in the same wave; the parity is structural, not test-pinned.

**Wave-3-future remaining boundary** (still deferred; revisit when bench evidence arrives):

- **Full SOS-03 vector JSON parser** (nested `inputs` object, `cycles_advance`, multi-step file structure) — wave-3-future v1 consumes a JSONL-flattened form of the SOS-03 schema. A real multi-line / nested-object JSON parser in pure SV is a substantial undertaking (string + array indexing + escape handling); the JSONL-flat shape captures the load-bearing 80% (string-valued state names, per-region expected states, cycles_wait) with a fraction of the implementation cost. Lift to nested parsing when a real chart needs `inputs.<port>` driving on the SV side.
- **Layered class hierarchy opt-in** — PCDN-SOS-08-E-001 names a flat hierarchy at v1; layered (test → env → agent → sequencer) opt-in lands when a customer authors a chart whose stimulus complexity justifies the additional structure.
- **Per-region SVA datamodel-binding** — sibling SOS-08-D wave-4-future tracks the cross-region datamodel binding; SOS-08-E inherits the SVA bind output, so no separate work on the SV-testbench side until the SOS-08-D wave-4-future remaining items land.
- **Multi-clock-domain parallel-chart testbench wiring** — wave-3 emits a single chart-top clock; multi-clock-domain region clocking lands when SOS-08-D wave-4 multi-clock-domain bind wiring (already landed) needs a testbench-side clock partitioner.

**Test count**: net +30 across `tools/sos-codegen/tests/test_transliterate_hdl_sv_tb.py`:

- `TestWave3FutureSharedParserPackage` (7) — file emit; include guard; `sos_jsonl_parse_int` declared; `sos_jsonl_parse_string` declared; string-extractor 1024-cap bound; no UVM / random keywords; parallel chart emits the same package.
- `TestWave3FutureStateSymbolTable` (5) — file emit; function signature; each chart state at its document-order index; parallel chart flattens all regions' states; include guard.
- `TestWave3FutureCheckerStringFieldPath` (8) — single-region checker includes both new headers; calls shared helpers; resolves string via symbol table; drops the inline `parse_int_field`; failure messages render chart-state strings; backwards-compatible integer-only path retained.
- `TestWave3FutureParallelCheckerStringFieldPath` (5) — parallel checker mirrors the same shape per-region.
- `TestWave3FutureDriverUsesSharedParser` (3) — driver includes the parser header; calls `sos_jsonl_parse_int`; drops inline parser.
- `TestWave3FutureInvariantsPreserved` (2) — round-trip both chart shapes through `render_target` without `InvariantAuditError`; emitted SV contains no `randomize(` / `uvm_pkg` outside bind/build files.

Plus three file-count assertions updated (`test_emits_twelve_files` → `test_emits_fourteen_files`; parallel-chart parity test extended from 14 → 16 files; single-region wave-3 stability test extended from 12 → 14 files).

**Test suite**: 673/673 passing (643 prior + 30 new wave-3-future).

**Cited PCDNs / invariants**: PCDN-SOS-08-E-001 / -002 / -004 unchanged; INV-S-HDL-E-1..6 preserved (E-4 strengthened); SOS-03 §15 2026-05-24 schema extension consumed; SOS-08-C `_emit_state_constants` encoding mirrored by-construction.

Status: 🟢 **wave-3-future SOS-03 schema consumer landed**. Layered class hierarchy + nested-JSON parser + per-region SVA datamodel-binding + multi-clock-domain testbench wiring remain on the wave-3-future track, each gated on customer demand / sibling-walker dependencies.

### 2026-05-24 — Impl wave-3-future-remaining: nested-JSON parser (one level deep) (Ira)

Lands the second wave-3-future carry-forward: a **one-level-deep nested-object JSON parser**. The wave-3-future SOS-03 schema consumer only extracted top-level scalar fields; chart events that carry structured payloads (e.g. ``"payload": {"name": ..., "value": ...}``) were either lossily flattened or skipped. This wave-3-future-remaining slice extends ``sos_jsonl_parser_pkg.svh`` with two new functions and wires the walker so a chart-declared ``<param name="outer.inner"/>`` triggers a checker-side parse call against them.

The deeper carry-forwards (layered class hierarchy per PCDN-SOS-08-E-001, multi-clock testbench wiring, deeper-than-one-level nesting) remain deferred — see "Remaining" below.

**Implementation surface**:

- **``_emit_jsonl_parser_pkg(chart_name)``** — extended to additionally emit two new SystemVerilog functions, alongside the wave-3-future top-level ``sos_jsonl_parse_int`` / ``sos_jsonl_parse_string``:

    * ``function automatic int sos_jsonl_parse_nested_int(input string line, input string outer_key, input string inner_key, output int value);`` — locates ``"<outer_key>":`` then ``{`` (defensive: a scalar like ``"outer":42`` returns 0 without raising); locates the matching closing brace via depth tracking; scans the enclosed range for ``"<inner_key>":<int>``. Returns 1 on hit, 0 on every defensive miss (missing outer, missing inner, malformed-outer-scalar).
    * ``function automatic int sos_jsonl_parse_nested_string(input string line, input string outer_key, input string inner_key, output string value);`` — same shape, string value. Preserves the wave-3-future top-level extractor's 1024-character inner-loop cap so a malformed line cannot pin the parser. Escape-aware: a ``\"`` preceded by a backslash is consumed as a literal rather than terminating the value.

  Both functions are emitted **unconditionally** alongside the existing top-level parsers — no new chart-XML opt-in is needed. Any future generated checker can call them without re-emission.

- **``_collect_nested_params(chart_ir)``** (new) — walks all transitions across the chart (single-region + parallel regions, recursive into nested ``<state>``) and every ``<raise>`` child's ``<param>`` list. A ``<param>`` whose ``name`` attribute contains exactly one ``.`` triggers the nested-payload emit path; the helper returns the unique ``(outer, inner, value_type)`` triples in document order. The walker classifies ``int`` vs ``string`` via the ``<param>``'s ``expr=`` attribute — bare integer literals classify ``int``; bare quoted string literals (single or double) classify ``string``; everything else falls back to ``int`` (the dominant SOS-03 payload case). Multi-level names (``"a.b.c"``) raise ``UnsupportedChartError`` with an actionable message: ``SOS-08-E wave-3-future: <param name="a.b.c"/> exceeds one-level-deep nested-payload support; flatten in the raise-side instead.`` Top-level names (no dot) are not nested-payload triggers and are left to the wave-3-future top-level parsers.

- **``_render_nested_param_blocks(nested_params, decl_indent, parse_indent)``** (new helper) — returns ``(decls, parse_block)`` strings. Empty when ``nested_params`` is empty, so the checker f-string templates can interpolate them unconditionally without disturbing the wave-3-future byte-identical baseline. The single-region checker passes ``decl_indent="        "`` (8 spaces, top of ``run()`` body) and ``parse_indent="            "`` (12 spaces, inside the per-step ``while`` loop). The parallel-region checker mirrors the same indents.

- **``_emit_checker_class(chart_name, nested_params=None)``** — extended to accept an optional ``nested_params`` list. When non-empty, emits per-field local declarations at the top of ``run()`` and per-field parse calls inside the per-step loop, after the wave-3-future ``cycles`` parse. Local variables are named ``nested_<outer>_<inner>`` + ``parsed_nested_<outer>_<inner>`` (sanitised via ``_sanitize_sv_identifier``). When the list is empty the emit is byte-identical to the wave-3-future baseline — the regression test ``test_no_nested_param_keeps_emit_byte_identical_with_wave3`` is the load-bearing guard.

- **``_emit_checker_class_parallel(chart_name, regions, nested_params=None)``** — same extension on the parallel-region path. Nested-param decls are added to ``run()``'s local-variable block (after the per-region ``region_decls`` + ``cycles_wait`` / ``parsed`` locals); parse calls are added inside the per-step loop after the ``cycles`` parse.

- **``render_target``** — calls ``_collect_nested_params(chart_ir)`` once before dispatching to the single-region vs parallel emit branch; forwards the result to whichever checker emit runs. The collector raises ``UnsupportedChartError`` if any ``<param>`` has two or more dots, before any file is emitted — fail-fast at the walker entry, not deep inside an emitter.

**Convention — dot-name ``<param>`` shape**:

A ``<param name="<outer>.<inner>"/>`` element on a ``<raise>`` inside a ``<transition>`` declares that the SOS-03 vector trace MAY carry a ``"<outer>": {"<inner>": <value>}`` payload that the checker SHOULD parse out of each trace step. The walker emits the parse call regardless of whether any given trace step actually carries the field — ``sos_jsonl_parse_nested_int`` / ``_string`` returns 0 on miss without altering the output. Downstream emit extensions (e.g. nested-payload-aware failure messages, datamodel-binding) can read the local variables ``nested_<outer>_<inner>`` produced by the parse calls; this slice does not consume them in the failure-message path (deferred — see remaining work below).

**Emit shape (example)**:

For a single-region chart with ``<transition><raise event="tick"><param name="payload.value" expr="42"/></raise></transition>``, the emitted checker's ``run()`` task body grows two blocks (omitting the unchanged wave-3-future top-level parse / resolve / compare):

```systemverilog
    task run();
        int    fh;
        // ... wave-3-future locals ...
        int    bit_idx;
        // Wave-3-future-remaining: nested-payload locals.
        int    nested_payload_value;
        int    parsed_nested_payload_value;

        // ... wave-3-future $fopen + clk wait ...

        while (!$feof(fh)) begin
            rc = $fgets(line, fh);
            if (rc == 0) break;

            // ... wave-3-future top-level parses ...
            parsed_int = sos_jsonl_parse_int(line, "cycles", cycles_wait);
            if (cycles_wait <= 0) cycles_wait = 1;
            // Wave-3-future-remaining: nested-payload extraction
            // (one level deep) per chart-declared <param name="outer.inner"/>.
            nested_payload_value = 0;
            parsed_nested_payload_value = sos_jsonl_parse_nested_int(
                line, "payload", "value", nested_payload_value
            );
            // ... wave-3-future resolve + compare ...
        end
```

**Invariants upheld**:

- **INV-S-HDL-E-1** (no constrained-random) — preserved. The two new SV functions are pure procedural code (loops, ``if``, arithmetic on ``byte`` / ``int``). The audit pass scans the emitted parser pkg and all checker emits cleanly.
- **INV-S-HDL-E-2** (no UVM) — preserved.
- **INV-S-HDL-E-3** (no inline ``assert property`` outside bind files) — preserved.
- **INV-S-HDL-E-4** (chart-vocabulary failure messages) — preserved. This slice does not emit new failure messages; existing wave-3-future messages remain unchanged.
- **INV-S-HDL-E-5** (per-simulator build wrapper) — preserved unchanged.
- **INV-S-HDL-E-6** (Verilator-subset compliance) — preserved. The new functions use only basic SV control flow + ``string.getc`` / ``string.len`` + ``byte`` arithmetic, all within Verilator's documented subset.
- **PCDN-SOS-08-E-001** (flat class hierarchy at v1) — preserved.
- **PCDN-SOS-08-E-004** (per-region testbench shape) — preserved.

**Tests added**: 13 new test methods on ``TestWave3FutureNestedJsonParser`` in ``tools/sos-codegen/tests/test_transliterate_hdl_sv_tb.py`` (one is optional-tool-gated and ``skip``s when ``iverilog`` / ``verible-verilog-syntax`` aren't on PATH):

- ``test_parser_pkg_emits_nested_int_function`` — deliverable 1a: ``sos_jsonl_parse_nested_int`` declared with the contracted signature.
- ``test_parser_pkg_emits_nested_string_function`` — deliverable 1b: ``sos_jsonl_parse_nested_string`` declared with the contracted signature.
- ``test_nested_int_handles_whitespace`` — whitespace + colon between ``"outer":`` and the brace is consumed; the brace is then required.
- ``test_nested_int_returns_zero_on_missing_outer`` — outer key not present → fall through to ``return 0;``.
- ``test_nested_int_returns_zero_on_missing_inner`` — outer object found but inner key absent → return 0 without scanning past the outer object.
- ``test_nested_int_returns_zero_on_malformed_outer_scalar`` — ``"outer":42`` (scalar, not object) → ``return 0;`` rather than raise a parse error.
- ``test_nested_string_handles_escaped_quotes`` — ``\"`` inside the inner string is preserved (escape-aware); 1024-character cap retained.
- ``test_checker_class_consumes_nested_param`` — deliverable 2: a ``<param name="payload.value"/>`` triggers a ``sos_jsonl_parse_nested_int(line, "payload", "value", ...)`` call in the checker.
- ``test_checker_class_parallel_consumes_nested_param`` — deliverable 3: same on the parallel-region path.
- ``test_two_level_dotted_param_raises_actionable_error`` — ``<param name="a.b.c"/>`` raises ``UnsupportedChartError`` with the message naming the wave + the suggested fix.
- ``test_no_nested_param_keeps_emit_byte_identical_with_wave3`` — regression guard: a chart with no nested ``<param>`` produces the SAME parser pkg (modulo the two new appended functions) and the SAME checker SV (no extra decls, no parse calls, no nested-param comments).
- ``test_render_target_does_not_regress_invariants`` — round-trip both shapes through ``render_target`` without ``InvariantAuditError``.
- ``test_optional_iverilog_smoke_compile_parser_pkg`` — when ``iverilog`` or ``verible-verilog-syntax`` is on PATH, smoke-compile the emitted parser pkg. ``skip``s otherwise.

**Test suite**: 701/701 passing (689 prior + 12 new wave-3-future-remaining; 1 skipped when neither SV syntax tool is installed).

**Wave-3-future remaining boundary** (still deferred):

- **Deeper-than-one-level-deep nesting** (e.g. ``<param name="a.b.c"/>``). The walker raises ``UnsupportedChartError`` with a clear "flatten in the raise-side" remediation. Lifting requires a real SV-side recursive JSON parser; lands when a chart-author actually needs more than one level of nesting (per the SOS spec-before-code discipline — concrete need precedes implementation).
- **Layered class hierarchy opt-in** (PCDN-SOS-08-E-001) — unchanged.
- **Multi-clock-domain testbench wiring** — unchanged.
- **Nested-payload-aware failure messages** — when a comparison failure involves a nested-payload field, the checker could surface the offending nested field's value in the chart-vocabulary failure message. Currently the parse call lands the value in a local variable that downstream emit extensions can read; this slice deliberately does NOT wire the failure-message path because the SOS-03 vector schema doesn't yet declare nested-field comparison semantics (deferred until the schema specifies "expected nested value vs observed" → which observable to read against).

**Cited PCDNs / invariants**: PCDN-SOS-08-E-001 / -002 / -004 unchanged; INV-S-HDL-E-1..6 preserved; ``<param name="outer.inner"/>`` dot-name convention introduced as the chart-author-facing trigger for the new parser functions.

Status: 🟢 **wave-3-future-remaining nested-JSON parser landed (one level deep)**. Deeper nesting, layered class hierarchy, and multi-clock testbench wiring remain on the wave-3-future track.

### 2026-05-24 — Impl wave-3-future-remaining: layered class hierarchy (Ira)

Closes the **layered class hierarchy** carry-forward from PCDN-SOS-08-E-001 (originally deferred at wave-1 as "follow-on if a customer requests it"). Splits the wave-3 monolithic driver + checker each into a virtual base class (`.svh` header) carrying the run-skeleton + per-step virtual hooks, plus a default class (`.sv`) that extends the base and provides the wave-3-default hook overrides. User-side customisation extends the base header directly; the walker keeps emitting the `_default` `.sv` byte-identical to the wave-3 chart-vocab.

The remaining wave-3-future carry-forwards (**multi-clock testbench wiring**, **deeper-than-one-level nested-payload parsing**) stay deferred.

**Implementation surface**:

- **`_emit_checker_class_base(chart_name, nested_params)`** (new) — emits `sos_<chart>_checker_base.svh`. Declares the virtual base class `sos_<chart>_checker_base` with:
    * Member fields (`vif`, `trace_path`, `fail_count`, `vector_idx`).
    * `function new(...)` constructor.
    * Four virtual hooks: `pre_step(int step_idx) → bit` (default returns 1), `on_state_transition(int prev_state, int next_state, int trigger_event)` (default no-op), `on_invariant_fail(int invariant_id, string message)` (default emits `$error("%s", message)`), `post_step(int step_idx)` (default no-op).
    * `task run()` — the run-skeleton. Walks each JSONL line; per step calls `pre_step → parse + state-resolution → on_state_transition → wait cycles → compare → on_invariant_fail (on mismatch) → post_step`. Chart-vocabulary failure messages are constructed inline via `$sformatf` using format strings **byte-identical** to the wave-3 monolithic emit; the formatted message is then routed through `on_invariant_fail` so user-side subclasses can intercept.
    * `function int get_fail_count()`.

- **`_emit_checker_class_base_parallel(chart_name, regions, nested_params)`** (new) — parallel mirror of the single-region base. Owns the same hook set + the per-region parse/resolve/compare logic; per-region failure messages are constructed inline via `$sformatf` and routed through `on_invariant_fail`.

- **`_emit_checker_class`** (refactored) — now emits the *default* class `sos_checker_<chart>` that `extends sos_<chart>_checker_base;`. The default class's body is just the constructor + four hook overrides; each override calls `super.<hook>(...)` so the base-class default chart-vocab emission still happens. `nested_params` is forwarded to the base emitter unchanged.

- **`_emit_checker_class_parallel`** (refactored) — parallel mirror of the default. The `regions` + `nested_params` parameters are consumed by the parallel base emitter; the default class itself is parameter-free hook overrides.

- **`_emit_driver_class_base(chart_name)`** (new) — emits `sos_<chart>_driver_base.svh`. Declares:
    * The per-step record `typedef struct { int event_code; int cycles_wait; string line; } sos_jsonl_record_t;` — carried into `drive_step`.
    * The virtual base class `sos_<chart>_driver_base` with member fields, constructor, three virtual hooks (`drive_pre(int step_idx)` / `drive_step(int step_idx, sos_jsonl_record_t rec)` / `drive_post(int step_idx)`), and the `task run()` run-skeleton (file open, reset, per-line JSONL decode into `sos_jsonl_record_t`, fire hooks per step, settle).

- **`_emit_driver_class`** (refactored) — now emits the *default* class `sos_driver_<chart>` that `extends sos_<chart>_driver_base;`. Overrides `drive_step` with the wave-3-default drive body (drives `vif.event_in`, waits `cycles_wait - 1` extra cycles, emits the chart-vocab `[DRIVE]` log).

- **`render_target`** — emits two new files per chart: `sos_<chart>_checker_base.svh` + `sos_<chart>_driver_base.svh`. File counts move from **14 → 16** (single-region) and **16 → 18** (parallel). The base headers are emitted in BOTH dispatch branches (single-region calls `_emit_checker_class_base`; parallel calls `_emit_checker_class_base_parallel`).

**Class-hierarchy convention** (the chart-author-facing contract):

- `sos_<chart>_<role>_base` (virtual class, in `_base.svh`) is the **supported extension point**. Users SHOULD extend this class to customise driver/checker behaviour.
- `sos_<role>_<chart>` (concrete class, in `<role>_<chart>.sv`) is the **walker-emitted default**. Users SHOULD NOT subclass the default — the walker re-emits it on every codegen run and any user-side edits to that file will be overwritten.
- `super.<hook>(...)` calls in the default class's overrides preserve the wave-3 chart-vocab failure emission; user-side subclasses overriding the same hook SHOULD also call `super.<hook>(...)` after any custom logging so the chart-vocab failure path remains intact (load-bearing for INV-S-HDL-E-4).

**Emit shape (example)**:

For the single-region `_simple_chart()` fixture (states `idle`, `active`):

```
tb/sv/demo/
├── sos_demo_checker_base.svh    ← virtual class sos_demo_checker_base; ...
├── sos_checker_demo.sv          ← class sos_checker_demo extends sos_demo_checker_base; ...
├── sos_demo_driver_base.svh     ← virtual class sos_demo_driver_base; ...
└── sos_driver_demo.sv           ← class sos_driver_demo extends sos_demo_driver_base; ...
```

The chart-vocabulary `[FAIL] vector V%0d: chart \`demo\` ...` format strings live inside `sos_demo_checker_base.svh`'s `run()` task; the default `sos_checker_demo.sv` carries no `$sformatf` of its own.

**Invariants upheld**:

- **INV-S-HDL-E-1** (no constrained-random) — preserved. The new virtual classes use only standard SV control flow + `string`/`int` arithmetic.
- **INV-S-HDL-E-2** (no UVM) — preserved. No UVM imports or macros.
- **INV-S-HDL-E-3** (no inline `assert property` outside bind files) — preserved.
- **INV-S-HDL-E-4** (chart-vocabulary failure messages) — preserved. The format strings are byte-identical to the wave-3 monolithic emit; regression guard `test_chart_vocab_message_byte_identical_to_wave3_baseline` exists.
- **INV-S-HDL-E-5** (per-simulator build wrapper) — preserved unchanged.
- **INV-S-HDL-E-6** (Verilator-subset compliance) — preserved. Virtual classes + `super.<hook>` dispatch are within Verilator's documented subset.
- **PCDN-SOS-08-E-001** (flat class hierarchy at v1) — **resolved**: the layered hierarchy is now opt-in via the `_base.svh` extension point. The walker always emits the `_default` so flat-hierarchy consumers see no behaviour change; layered consumers extend `_base` themselves.

**Tests added**: 17 new test methods on `TestWave3FutureLayeredClassHierarchy`:

- `test_emits_checker_base_svh` / `test_emits_driver_base_svh` — the new headers are emitted for every chart.
- `test_checker_base_declares_virtual_hooks` / `test_driver_base_declares_virtual_hooks` — the virtual hook signatures are declared in the base header.
- `test_default_checker_extends_base` / `test_default_driver_extends_base` — the default classes use the SV `extends` keyword.
- `test_run_skeleton_lives_in_base` — the `run()` task body lives in the base header, NOT in the default `.sv`.
- `test_invariant_failure_message_constructed_in_base` — chart-vocab message construction (`$sformatf`) lives in the base.
- `test_emit_count_single_region_is_sixteen` / `test_emit_count_parallel_is_eighteen` — file counts move to 16/18.
- `test_chart_vocab_message_byte_identical_to_wave3_baseline` — regression guard: the `$sformatf` format strings are byte-identical to the wave-3 monolithic emit.
- `test_super_dispatch_in_default_calls_base_invariant_handler` — the default's `on_invariant_fail` calls `super.on_invariant_fail(invariant_id, message)` so chart-vocab failure emission survives user subclassing.
- `test_emits_parallel_checker_base_svh` / `test_emits_parallel_driver_base_svh` / `test_parallel_default_checker_extends_base` / `test_parallel_run_skeleton_lives_in_base` — parallel-chart mirror of the single-region checks.
- `test_render_target_layered_emit_clean` — INV-S-HDL-E-1/-2/-3 audit passes on both chart shapes.

**Test suite**: 766/766 passing (749 prior + 17 new wave-3-future-remaining layered-hierarchy; 1 skipped when neither SV syntax tool is installed).

**Wave-3-future remaining boundary** (still deferred):

- **Multi-clock-domain testbench wiring** — per-region `clk_<dom>` / `rst_<dom>` on the chart-top wrapper per SOS-08-C §6.10's multi-clock contract. Wave-2b ratified single-clock parallel as the v1 baseline; this slice inherits that constraint unchanged.
- **Deeper-than-one-level nested-payload parsing** — `<param name="a.b.c"/>` still raises `UnsupportedChartError`. Lifting requires a real SV-side recursive JSON parser; lands when a chart-author actually needs more than one level of nesting (per the SOS spec-before-code discipline).
- **Nested-payload-aware failure messages** — unchanged from the prior §15 entry.

**Cited PCDNs / invariants**: PCDN-SOS-08-E-001 **resolved via layered-hierarchy opt-in** (the walker keeps the flat `_default` as the byte-identical wave-3 emit; layered consumers extend `_base`); INV-S-HDL-E-1..6 preserved; §12 gate (a) updated to mark PCDN-SOS-08-E-001 as resolved.

### 2026-05-24 — Impl wave-3-future-remaining-path: deeper-than-one-level nested-JSON parser (Ira)

Lifts the wave-3-future-remaining **one-level-deep** cap on the nested-JSON parser. The wave-3-future-remaining slice (committed at `9010510`) added `sos_jsonl_parse_nested_int` / `_string` for `<param name="outer.inner"/>` declarations and raised `UnsupportedChartError` on `<param name="a.b.c"/>` (two or more dots). This wave-3-future-remaining-path slice closes the deeper-nesting carry-forward: `<param>` names with two or more dots no longer raise — they lower to a **path-segment-based** chain of nested-object descents via two new SV functions.

The remaining wave-3-future carry-forward (**multi-clock testbench wiring**) stays deferred.

**Implementation surface**:

- **`_emit_jsonl_parser_pkg(chart_name)`** — extended to additionally emit two new SystemVerilog functions, alongside the unchanged wave-3-future top-level + wave-3-future-remaining one-level-deep parsers. The wave-3-future-remaining `_nested_*` functions stay **byte-identical** (regression guard `test_byte_identity_when_chart_uses_only_depth_1_nested_params` is the load-bearing check):

    * `function automatic int sos_jsonl_parse_path_int(input string line, input string path_dot_separated, output int value);` — splits `path_dot_separated` on `.`, descends through nested objects level by level. Returns 1 on success + populates `value`; returns 0 on absence at any descent level, malformed scalar mid-path (defensive — not a parse error), or window exhaustion. Path-segment iteration uses a `(win_lo, win_hi)` window pair that narrows on each intermediate descent into the brace-paired contents of the matched key's value.
    * `function automatic int sos_jsonl_parse_path_string(input string line, input string path_dot_separated, output string value);` — same shape, string leaf. **1024-character cap** preserved (mirrors the wave-3-future top-level + `_nested_*` extractors). Escape-aware at the leaf: a backslash before a quote consumes the quote as a literal.

  Both functions emit a one-line **`$warning`** if `path_dot_separated` contains an empty segment at runtime (e.g. `"a..b"`, `".a"`, `"a."`). The build-time chart-vocab gate normally catches these in chart source; the `$warning` is a runtime defence against malformed JSONL-side input data. `$warning` is acceptable in checker context per INV-S-HDL-E-1..6.

- **`_validate_path_segments(p_name)`** (new helper) — build-time chart-vocab gate. Splits `p_name` on `.`, validates each segment against `^[A-Za-z_][A-Za-z0-9_]*$` (SV identifier rules). Raises `UnsupportedChartError` on:
    * Empty segments (`"a..b"`, `".a"`, `"a."`) — message: `SOS-08-E wave-3-future-path: <param name='<name>'/> contains an empty path segment; use dot-separated identifiers only.`
    * Non-identifier characters in a segment (`"a-b.c"`, `"a/b.c"`, digits-first) — message names the offending segment and cites the SV identifier rules.

- **`_collect_nested_params(chart_ir)`** (refactored) — wave-3-future-remaining semantics preserved for depth-1 (`outer.inner`); two-or-more-dot names no longer raise here but instead route to `_collect_path_params`. The chart-vocab gate (empty / non-identifier) is invoked via `_validate_path_segments` so both collectors share the same rules.

- **`_collect_path_params(chart_ir)`** (new) — sibling collector for depth-≥2 declarations. Returns the list of unique `(segments_tuple, value_type)` pairs in document order. Walks the same transition + raise + param shape as `_collect_nested_params`. Path-segment validation is shared via `_validate_path_segments`.

- **`_render_nested_param_blocks(nested_params, decl_indent, parse_indent, path_params=None)`** (extended) — now also emits `sos_jsonl_parse_path_*` decls + call sites when `path_params` is non-empty. Charts using only depth-0 or depth-1 params emit byte-identically to the prior wave-3-future-remaining baseline (load-bearing regression-guard).

- **`_emit_checker_class_base(chart_name, nested_params, path_params)`** — extended to accept the new `path_params` list and forward it to `_render_nested_param_blocks`. Wave-3-future-remaining call sites for `sos_jsonl_parse_nested_int` / `_string` are preserved verbatim where they exist today.

- **`_emit_checker_class_base_parallel(chart_name, regions, nested_params, path_params)`** — same extension on the parallel path.

- **`_emit_checker_class` / `_emit_checker_class_parallel`** — accept `path_params` for API symmetry; both forward it to the base emitters and emit no `path_*` content themselves (the `_default.svh` body stays parameter-blind per the layered-hierarchy convention).

- **`render_target`** — calls `_collect_path_params(chart_ir)` once before dispatching to the single-region vs parallel emit branch; forwards the result alongside `nested_params` to whichever checker emit runs. Build-time chart-vocab errors raise fail-fast at the walker entry, never deep inside an emitter.

**Convention — deep dot-path `<param>` shape**:

A `<param name="a.b.c.d"/>` (depth ≥ 2, all segments are SV identifiers) on a `<raise>` inside a `<transition>` declares that the SOS-03 vector trace MAY carry a `"a": {"b": {"c": {"d": <value>}}}` payload that the checker SHOULD parse out of each trace step. The walker emits the parse call regardless of whether any given trace step actually carries the field — `sos_jsonl_parse_path_int` / `_string` returns 0 on miss without altering the output.

Path syntax (chart-vocab):

- **MUST** match `[a-zA-Z_][a-zA-Z0-9_]*` per segment (SV identifier rules).
- **MUST NOT** contain empty segments (leading / trailing / repeated dots).
- **MAY** be arbitrary depth; SV string length is the only ceiling. The implementation has no hard cap.

**Build-time vs runtime error split**:

- **Build-time** chart-vocab error (`UnsupportedChartError`) — syntactic malformation in chart source. Examples: `<param name="a..b"/>`, `<param name="a-b.c"/>`, `<param name=".a.b"/>`. These fail codegen.
- **Runtime** `$warning` — semantic malformation in input JSONL data. Example: a chart-vocab-valid `<param name="payload.value"/>` whose runtime JSONL line carries an unexpected empty intermediate segment in a relayed path field. The `$warning` makes the malformation visible without aborting simulation; the parse returns 0 so the checker proceeds with default values.

**Authority boundary declaration** (per the standards-integration matrix discipline):

- **Dot-path convention** (the `<param name="a.b.c"/>` chart-vocab shape) — relationship: **own**. This repo authors the convention; full mutation rights gated by the spec-before-code discipline.
- **IEEE 1800-2017 string-handling functions** (`string.len()`, `string.getc()`, concatenation `{}`) — relationship: **derive**. The SV emit uses upstream IEEE 1800-2017 grammar without owning it; outputs (the emitted SV source) are local; inputs (the language semantics) are upstream.

**Emit shape (example)**:

For a single-region chart with `<transition><raise event="tick"><param name="payload.metadata.value" expr="42"/></raise></transition>`, the emitted checker's `run()` task body grows two new lines in the locals block + a four-line parse block inside the per-step loop:

```systemverilog
    task run();
        // ... wave-3-future-remaining + wave-3-future locals ...
        // Wave-3-future-remaining-path: deep-nested-payload locals.
        int    path_payload_metadata_value;
        int    parsed_path_payload_metadata_value;

        // ... wave-3-future $fopen + clk wait ...

        while (!$feof(fh)) begin
            rc = $fgets(line, fh);
            if (rc == 0) break;

            // ... wave-3-future top-level + wave-3-future-remaining nested parses ...
            // Wave-3-future-remaining-path: arbitrary-depth nested-payload
            // extraction per chart-declared <param name="a.b.c"/>.
            path_payload_metadata_value = 0;
            parsed_path_payload_metadata_value = sos_jsonl_parse_path_int(
                line, "payload.metadata.value", path_payload_metadata_value
            );
            // ... wave-3-future resolve + compare ...
        end
```

**Invariants upheld**:

- **INV-S-HDL-E-1** (no constrained-random) — preserved. The two new SV functions use only basic control flow, integer arithmetic, and `string.getc` / `string.len`; `$warning` is an SV system task with no random-stimulus semantics.
- **INV-S-HDL-E-2** (no UVM) — preserved.
- **INV-S-HDL-E-3** (no inline `assert property` outside bind files) — preserved.
- **INV-S-HDL-E-4** (chart-vocabulary failure messages) — preserved. The `$warning` text names the path literal so chart authors can grep their JSONL traces; this is informational diagnostic, not a failure-message change.
- **INV-S-HDL-E-5** (per-simulator build wrapper) — preserved unchanged.
- **INV-S-HDL-E-6** (Verilator-subset compliance) — preserved. `$warning` is supported by Verilator (it lowers to a `$display` + return). No other new SV constructs land.
- **PCDN-SOS-08-E-001** — already resolved by the layered-hierarchy refactor; unchanged here.

**Tests added**: 17 new test methods on `TestWave3FuturePathNestedJsonParser`:

- `test_parser_pkg_emits_path_int_function` / `test_parser_pkg_emits_path_string_function` — the two new functions are emitted with the contracted signatures.
- `test_byte_identity_when_chart_uses_only_depth_0_params` — regression guard: no nested/path call sites for a chart with no nested `<param>`.
- `test_byte_identity_when_chart_uses_only_depth_1_nested_params` — regression guard: `sos_jsonl_parse_nested_int(` call site preserved verbatim; no `sos_jsonl_parse_path_*` references.
- `test_three_level_path_param_emits_path_int_call` / `test_four_level_path_param_emits_path_int_call` — depth-2 and depth-3 charts lower to `sos_jsonl_parse_path_int` calls with the dot-separated path literal.
- `test_path_int_handles_missing_key_at_intermediate_level` — the per-segment match-scan falls through to `return 0;` on miss.
- `test_path_int_handles_malformed_intermediate_scalar` — intermediate brace-required check returns 0 on scalar (defensive).
- `test_path_string_handles_escaped_quotes_at_leaf` — leaf-string escape-aware scan; 1024-character cap preserved.
- `test_path_int_emits_warning_on_empty_segment_at_runtime` — runtime `$warning` is emitted in both `path_int` + `path_string` bodies with the function name in the message.
- `test_chart_vocab_rejects_empty_segment_at_build_time` / `test_chart_vocab_rejects_leading_dot` / `test_chart_vocab_rejects_trailing_dot` — empty segments raise `UnsupportedChartError` at codegen.
- `test_chart_vocab_rejects_non_identifier_in_segment` / `test_chart_vocab_rejects_segment_starting_with_digit` — non-identifier segments raise citing SV identifier rules.
- `test_parallel_checker_uses_path_parser_for_deep_params` — parallel-region mirror.
- `test_render_target_path_emit_invariant_clean` — round-trip both single-region + parallel path-param charts through `render_target` without `InvariantAuditError`.

In addition, the obsolete `test_two_level_dotted_param_raises_actionable_error` (which asserted the `a.b.c` raise) is renamed to `test_two_level_dotted_param_now_emits_path_parser_call` and asserts the new emit behaviour — the chart-vocab error gate for depth-≥2 names moved from "always raise" to "raise on malformed segments only".

**Test suite**: 833/833 passing (816 prior + 17 new wave-3-future-remaining-path; 1 skipped when neither SV syntax tool is installed).

**Wave-3-future remaining boundary** (still deferred):

- **Multi-clock-domain testbench wiring** — per-region `clk_<dom>` / `rst_<dom>` on the chart-top wrapper per SOS-08-C §6.10's multi-clock contract. Wave-2b ratified single-clock parallel as the v1 baseline; this slice inherits that constraint unchanged. This is now the **only** remaining wave-3-future carry-forward.
- **Nested-payload-aware failure messages** — unchanged from the prior §15 entries. The path-parser lands the value in a local variable that downstream emit extensions can read; failure-message integration is deferred until the SOS-03 vector schema specifies the nested-comparison semantics.

**Cited PCDNs / invariants**: PCDN-SOS-08-E-001 unchanged (already resolved); INV-S-HDL-E-1..6 preserved; new chart-vocab convention `<param name="a.b.c"/>` (dot-separated SV identifiers, arbitrary depth) introduced as the chart-author-facing trigger for the new parser functions. The wave-3-future-remaining one-level-deep nested parser stays byte-identical (regression-guard tests in place).

Status: 🟢 **wave-3-future-remaining-path nested-JSON parser landed (arbitrary depth)**. Multi-clock testbench wiring remains the sole wave-3-future carry-forward.

Status: 🟢 **wave-3-future-remaining layered class hierarchy landed**. File shape: 16 files single-region, 18 files parallel. `_base` is the supported extension point; users override by extending it. The walker continues to emit `_default` byte-identical to wave-3 chart-vocab. Multi-clock testbench wiring + deeper-than-one-level nesting remain on the wave-3-future track.

### 2026-05-24 — Impl wave-3-future-remaining: multi-clock testbench wiring (Ira)

Closes the **LAST wave-3-future carry-forward** named in the prior §15 entry as "multi-clock-domain testbench wiring". The wave-3 SV-testbench walker emitted a single chart-top clock (the wave-1 `CLK_PERIOD = 10` default). This slice extends the walker to consume the chart's `<sos:clock_domains>` block and emit per-clock generators, a clock-domain manifest, and one CDC synchroniser stub per directional boundary. With this, the wave-3-future carry-forward set is **complete**.

**Assumed `<sos:clock_domains>` shape**:

SOS-08-D wave-4's multi-clock-domain bind wiring is the upstream authority for the `<sos:clock_domains>` element. At the time this slice landed (2026-05-24), the SOS-08-D wave-4 element definition has not yet been ratified as a normative artefact in `SOS-08-D-CONCEPTS.md` (the in-flight SOS-08-D-3 phase tracks it). Per the spec-before-code discipline, this slice **assumes** the following shape and documents it here as load-bearing context for the implementation:

```xml
<sos:clock_domains>
  <sos:clock name="clk_a" period_ns="10"   duty_cycle="0.5"/>
  <sos:clock name="clk_b" period_ns="20.0" duty_cycle="0.5"/>
</sos:clock_domains>
```

The walker (`_collect_clock_domains`) reads this shape and accepts both SCXML-namespaced (`sos:clock_domains` / `sos:clock`) and bare-namespace (`clock_domains` / `clock`) keys (the scjson loader strips namespaces by default). The first-declared clock is the **primary** clock. When SOS-08-D wave-4 ratifies a different shape, this walker MUST be updated to mirror — the authority is SOS-08-D, not SOS-08-E.

**Detection rule** (load-bearing for byte-identity):

- **Zero or one** declared `<sos:clock>` → SINGLE-clock emit path; byte-identical to the prior wave-3-future-remaining-path emit. Charts without `<sos:clock_domains>` and charts with a single-clock declaration emit the SAME file set with the SAME content (regression-guard tests pin this).
- **Two or more** declared `<sos:clock>` → MULTI-clock emit path: per-clock generator block + `clock_domain_of_step()` virtual function on the driver base + ``string clock_domain`` parameter on every `drive_*` hook + `case (clock_domain)` selection in the default driver's `drive_step` body + one CDC synchroniser stub file per directional boundary.

**Implementation surface**:

- **`_collect_clock_domains(chart_ir)`** (new) — reads the chart's `<sos:clock_domains>` block; returns `[{name, period_ns, duty_cycle}, ...]` in document order. Validates each clock name against `[a-zA-Z_][a-zA-Z0-9_]*` via the new `_validate_sv_clock_name` chart-vocab gate; duplicate clock names are collapsed (first wins). Returns an empty list when no `<sos:clock_domains>` block is declared.

- **`_collect_cdc_boundaries(chart_ir, clock_names)`** (new) — enumerates the directional `(from_clock, to_clock)` CDC boundary pairs declared on the chart. Accepts two inbound shapes: (1) explicit `<sos:cdc_boundary from="clk_a" to="clk_b"/>` elements, and (2) derived from `<sos:cross_invariant>` `<sos:sampling_clock>` lists (each pair of distinct clock names referenced under one cross-invariant yields the directional pair in both orders). Returns `[]` when no boundaries are declared. Raises `UnsupportedChartError` when a boundary references a clock NOT in the chart's `<sos:clock_domains>` declaration (chart-vocab gate).

- **`expected_sv_tb_file_count(chart_xml)` (PUBLIC)** — helper that returns the total number of files `render_target` will emit. Single-region single-clock charts → 16 (matches the existing `TestFileSet` assertion). Multi-clock charts → `16 + 1 + len(cdc_boundaries)` (the +1 for the generator header; +N for each directional CDC sync stub). Existing wave-3-future-remaining-path tests retain their hard-coded 16/18 literals because the helper is OPTIONAL — the byte-identity guard for ≤1-clock charts ensures those literals stay valid.

- **`_emit_driver_class_base(chart_name, clocks=None)`** (extended) — accepts an optional `clocks` list. When `clocks` is `None` or has length ≤ 1, the emit is **byte-identical** to the prior wave-3-future-remaining-layered emit. When `clocks` has length ≥ 2, the implementation routes through `_emit_driver_class_base_multi_clock`, which:
    * Declares `virtual function automatic string clock_domain_of_step(int step_idx);` whose default body returns the primary (first-declared) clock name verbatim.
    * Extends every `drive_*` hook signature with a `string clock_domain` parameter.
    * Threads `clock_domain_of_step(vector_idx)` through every hook call in the `run()` skeleton.

- **`_emit_driver_class(chart_name, clocks=None)`** (extended) — same byte-identity gate. The multi-clock variant overrides `drive_step` with a body that uses `case (clock_domain)` to wait on the per-step `@(posedge <clk>)` edge before driving the event. The `default:` arm falls back to the primary clock so a misclassified step still makes forward progress.

- **`_emit_top_module(chart_name, n_states, clocks=None)`** / **`_emit_top_module_parallel(chart_name, regions, clocks=None)`** (extended) — same byte-identity gate. The multi-clock variant declares one `logic` per chart-declared clock, ``\`include``s ``clock_generators_<chart>.svh``, and wires the DUT's `.clk` + virtual interface's `.clk` to the primary clock for backwards compatibility with the single-clock chart-top wrapper port shape. (Per-region clocking on the chart-top wrapper is the SOS-08-D wave-4 concern, not this slice's scope.)

- **`_emit_clock_generators_svh(chart_name, clocks)`** (new) — emits `clock_generators_<chart>.svh`. One `initial begin <clk> = 1'b0; forever #((<period_ns>)/2.0 * 1ns) <clk> = ~<clk>; end` block per declared clock, wrapped in include guards.

- **`_emit_cdc_sync_stub_svh(chart_name, from_clk, to_clk)`** (new) — emits a directional CDC synchroniser stub at `sos_<chart>_cdc_<from>_<to>_sync.svh`. The module body carries the load-bearing user-replace banner (`// SYNCHRONISER STUB: provided by user. Replace with project-specific CDC primitive.`) plus a 2-FF default implementation that synthesises but is NOT formally verified. **Stub only** — real ASIC/FPGA deployments MUST replace the body with a project-specific CDC primitive.

- **`render_target`** (extended) — calls `_collect_clock_domains(chart_ir)` once, computes the `is_multi_clock` flag from `len(clocks) >= 2`, and threads `emit_clocks = clocks if is_multi_clock else None` through every emitter that has the new parameter. Multi-clock charts additionally emit `clock_generators_<chart>.svh` + one CDC sync stub per directional boundary derived via `_collect_cdc_boundaries`.

**Normative additions** (acceptance-checklist gates):

1. Clock declaration via `<sos:clock_domains>` / `<sos:clock>` (reused from SOS-08-D wave-4 — the SV-testbench walker reads but does not extend the upstream grammar).
2. Per-clock generator emit (one `initial` + `forever` block per declared clock; idempotent via include guards).
3. `clock_domain_of_step()` virtual function shape on the driver base (default body returns the primary clock name; subclasses override to map specific step indices to specific domains).
4. CDC sync stub MUST be replaced by user with project-specific CDC primitive. The 2-FF default body is the minimum viable shape — adequate for single-bit slow signals; NOT adequate for multi-bit data buses.

**Authority boundary declarations** (per §0 standards-integration matrix):

| Concept | Upstream authority | Relationship | Mutation rights |
|---|---|---|---|
| `<sos:clock_domains>` / `<sos:clock>` element shape | SOS-08-D wave-4 (multi-clock-domain bind wiring) | `mirror` | this walker reads but does not extend |
| `clock_domain_of_step()` virtual function shape on driver base | SOS-08-E (this doc) | `own` | this walker authors the SV contract; §15 amendment required to change |
| ``string clock_domain`` hook parameter (drive_pre/drive_step/drive_post) | SOS-08-E (this doc) | `own` | §15 amendment required |
| CDC sync stub naming convention `sos_<chart>_cdc_<from>_<to>_sync.svh` | SOS-08-E (this doc) | `own` | §15 amendment required |
| 2-FF synchroniser default implementation | textbook CDC pattern | `derive` | project-specific replacement expected at the file's STUB-banner boundary |

**Invariants upheld**:

- **INV-S-HDL-E-1** (no constrained-random) — preserved. The multi-clock additions are pure procedural SV: `initial begin ... forever ... end` blocks, virtual function dispatch, `case (clock_domain)` statements. The audit pass scans the emitted parser pkg, both checker emits, both driver emits, the clock generators header, the CDC sync stub, the top module, and all build wrappers cleanly.
- **INV-S-HDL-E-2** (no UVM) — preserved.
- **INV-S-HDL-E-3** (no inline `assert property` outside bind files) — preserved.
- **INV-S-HDL-E-4** (chart-vocabulary failure messages) — preserved. The multi-clock default driver's `[DRIVE]` log line now names the per-step clock domain verbatim (``[DRIVE] V%0d: event=%0d cycles=%0d domain=`%s`  // chart=...``) so a CI failure on a multi-clock chart immediately surfaces which clock domain the step was targeting.
- **INV-S-HDL-E-5** (per-simulator build wrapper) — preserved unchanged. The five wave-2 wrappers cover single-region + parallel + single-clock + multi-clock emit paths (the wrappers are simulator-specific, not emit-shape-specific).
- **INV-S-HDL-E-6** (Verilator-subset compliance) — preserved. `initial begin ... forever ... end` and `case` are within Verilator's documented subset; the per-clock generators emit Verilator-compatible timing via `#(real * 1ns)`.
- **PCDN-SOS-08-E-001** (flat class hierarchy at v1) — resolved by the layered-hierarchy refactor; the multi-clock additions extend the base class but preserve the layered-hierarchy contract.
- **PCDN-SOS-08-E-002** (Verilator deferred-failure stubs) — preserved unchanged.
- **PCDN-SOS-08-E-004** (per-region testbench shape) — preserved; multi-clock composes with parallel via the parallel top-module variant.

**Tests added**: 18 new test methods on `TestWave3FutureMultiClockTestbenchWiring`:

- `test_byte_identity_for_no_clock_declared_chart` — regression guard: charts without `<sos:clock_domains>` emit no `clock_generators_*` or `_cdc_*` files; idempotent rerun is byte-identical.
- `test_byte_identity_for_single_clock_chart` — regression guard: a chart with EXACTLY ONE `<sos:clock>` emits byte-identically to the same chart WITHOUT `<sos:clock_domains>` — confirms the wave-3-future-remaining-path baseline survives the multi-clock extension.
- `test_drive_step_hook_signature_unchanged_when_single_clock` — single-clock chart preserves the wave-3 `drive_step(int step_idx, sos_jsonl_record_t rec)` signature; no `string clock_domain` parameter appears.
- `test_two_clock_chart_emits_two_clock_generators` — two-clock chart emits exactly two `forever` toggle blocks.
- `test_three_clock_chart_emits_three_clock_generators` — three-clock chart emits exactly three.
- `test_clock_period_ns_emitted_in_generator` — the `period_ns` value lands in the `#((period)/2.0 * 1ns)` toggle verbatim.
- `test_driver_base_declares_clock_domain_of_step_function` — the multi-clock driver base declares the virtual function with the contracted signature; default body returns the primary (first-declared) clock name.
- `test_drive_step_hook_signature_gains_clock_domain_param_when_multi_clock` — all three hooks gain the `string clock_domain` parameter.
- `test_default_driver_uses_case_on_clock_domain` — the default driver's `drive_step` override uses `case (clock_domain)` with per-clock arms + a `default:` fallback to the primary clock.
- `test_primary_clock_is_first_declared` — swapping declaration order swaps which clock is primary (drives the default arm + the `clock_domain_of_step` default body).
- `test_clock_domain_of_step_default_returns_primary` — the function body is a simple return with no branching.
- `test_cdc_sync_stub_file_emitted_per_directional_boundary` — `clk_a → clk_b` and `clk_b → clk_a` yield two separate stub files.
- `test_cdc_sync_stub_file_naming_convention` — exact filename match against `sos_<chart>_cdc_<from>_<to>_sync.svh`.
- `test_cdc_sync_default_body_is_two_ff_synchroniser` — user-replace banner present; 2-FF (`meta_q` + `sync_q`) default body present; module name matches file name.
- `test_invalid_sv_identifier_in_clock_name_raises` — chart-vocab gate raises on `"123clk"`, `"clk-a"`, `"clk a"`, `"clk.a"`.
- `test_unknown_clock_id_in_sampling_clock_raises` — `<sos:cdc_boundary>` referencing an undeclared clock raises with the canonical chart-vocab error.
- `test_expected_sv_tb_file_count_helper_returns_correct_count` — public helper agrees with the actual emit count across 0/1/2/3-clock × 0/1/2-CDC permutations.
- `test_parallel_chart_multi_clock_also_works` — the multi-clock path composes with parallel charts.

**Test suite**: 892/892 passing (874 prior + 18 new wave-3-future-remaining multi-clock; 1 skipped when neither SV syntax tool is installed).

**Wave-3-future closed**:

With this slice landed, the wave-3-future carry-forward set is **complete**. The following remain explicitly out-of-scope for SOS-08-E v1 (future phase work, not wave-3-future):

- **Per-region clocking on the chart-top wrapper** (per-region `clk_<dom>` / `rst_<dom>` ports) — the SOS-08-D wave-4 multi-clock-domain bind wiring concern. SOS-08-E v1 wires the DUT's single `.clk` port to the primary clock; per-region clocking on the chart-top wrapper itself is an SOS-08-D concern.
- **CDC formal verification** — the emitted stubs synthesise but are NOT formally verified. Project-specific CDC primitives (MTBF-characterised macros, Gray-coded handshake buses, full multi-bit handshakes) are user-replaced in-place at the STUB-banner boundary.
- **Asynchronous reset handling** — the multi-clock emit uses synchronous reset assertion in the driver base; per-clock-domain async-reset wiring is a future phase concern.
- **Nested-payload-aware failure messages** — unchanged from the prior §15 entries.

**Cited PCDNs / invariants**: PCDN-SOS-08-E-001 / -002 / -004 unchanged; INV-S-HDL-E-1..6 preserved; new chart-vocab elements `<sos:clock_domains>` / `<sos:clock>` (mirrored from SOS-08-D wave-4) + `<sos:cdc_boundary>` (own); new SV contracts `clock_domain_of_step()` + ``string clock_domain`` hook parameter + `sos_<chart>_cdc_<from>_<to>_sync.svh` naming convention (own).

Status: 🟢 **wave-3-future closed**. Multi-clock testbench wiring complete; LAST wave-3-future carry-forward landed. SOS-08-E v1 emission contract fully delivered.

### 2026-05-25 — Post-wave-2 follow-up: `$display`→`$error` verb-change normative pin (Ira)

This entry pins normatively the system-task verb shift introduced by wave-2 commit `fa06f7a` ("SOS08E3l: wave-3-future-remaining layered class hierarchy") in the checker's `on_invariant_fail` default body. The shift was observable in the diff but was not previously named in normative terms — downstream tooling (CI log parsers, scoreboards, regression dashboards) may have grepped for `$display` literally and silently broken on the new emission. This amendment makes the verb-change observable rather than buried.

**Issue.** Wave-2 commit `fa06f7a` (SOS08E3l — layered class hierarchy refactor) shifted the SystemVerilog system-task verb in the walker-emitted `_checker_base.svh` default `on_invariant_fail` body from `$display` to `$error`. The chart-vocabulary format strings carrying state names, transition IDs, and invariant IDs are **byte-identical** across the verb-change — the §15 entry on `fa06f7a` notes the shift as "more semantically correct" but does not pin it as a normative requirement. This follow-up names it normatively.

**Normative pin (MUST).** The walker-emitted `_checker_base.svh` MUST use `$error` (not `$display`) for invariant-failure dispatch in the default `on_invariant_fail` body. Downstream tooling that consumes SystemVerilog simulator output from this codegen path — CI log parsers, scoreboards, regression dashboards — MUST grep for `$error` (or for the simulator-emitted severity tag `%E` / `Error:`) when consuming the canonical chart-vocabulary failure messages from the walker-emitted default. Charts that override `on_invariant_fail` in a user-side subclass MAY use any system task (`$display`, `$warning`, `$info`, `$error`, `$fatal`) consistent with their project's reporting discipline — the MUST applies to the walker-emitted default body only. The format string passed through the hook carries the same chart-vocab content (state names, transition IDs, invariant IDs) byte-identical across the verb-change.

**Rationale.** Per IEEE 1800-2017 §20.10.3, `$error` flags simulation severity to the simulator — vendor tools surface it as a tagged error log line, increment the simulator's error counter, and (per vendor configuration) can elevate to a non-zero exit code. `$display` is documented as an informational log task with no severity semantics. Treating SOS-08-E invariant violations as informational was incorrect: an invariant failure is a chart-contract violation, and the simulator's severity machinery is the correct conveyor. The wave-3 monolithic emit used `$display` because the dispatch was inline (no override hook); the wave-3-future layered hierarchy externalised the dispatch through `on_invariant_fail` and took the opportunity to escalate severity at the same time. This entry pins that decision.

**Backwards-compatibility.** Any existing tooling parsing `$display` from prior pre-`fa06f7a` walker output (i.e. the wave-3 monolithic-emit era) MUST be updated to match the post-`fa06f7a` emission. The migration is:

- **Old pattern (pre-`fa06f7a`):** `grep -E '^\$display.*\[FAIL\] vector V[0-9]+: chart' simulator.log` or simulator-tagged equivalents.
- **New pattern (post-`fa06f7a`):** `grep -E '^(.*Error.*)?.*\[FAIL\] vector V[0-9]+: chart' simulator.log` — or, vendor-specific, match on `%E` / `Error:` severity tags emitted by the simulator on `$error` invocation.

The format-string payload — the `[FAIL] vector V%0d: chart \`<chart>\` expected state=...` chart-vocab content — is unchanged. Only the dispatch verb is. Audit your CI log parsers for `\$display` patterns on SOS-08-E simulator output and migrate to `\$error` (or the corresponding severity-tag match).

**Override-time exception.** This MUST applies only to the walker's default `on_invariant_fail` body inside `_checker_base.svh`. Customer-side subclasses extending `sos_<chart>_checker_base` MAY use any system task in their hook override consistent with their project's reporting discipline (subject to INV-S-HDL-E-4 — chart-vocabulary preservation; subject to recommendation to call `super.on_invariant_fail(invariant_id, message)` after any custom logging so the chart-vocab severity-tagged emission survives).

**Tracking.** Resolving commit: `fa06f7a` ("SOS08E3l: wave-3-future-remaining layered class hierarchy"). Original §15 entry: 2026-05-24 "Impl wave-3-future-remaining: layered class hierarchy" (above) — see the bullet on `on_invariant_fail` default hook for the byte-level diff. The original entry described the verb change as "more semantically correct"; this follow-up pins it as a normative MUST.

**Invariants upheld**:

- **INV-S-HDL-E-1** (no constrained-random) — unchanged; system-task selection has no constrained-random surface.
- **INV-S-HDL-E-2** (no UVM) — unchanged; `$error` is a SystemVerilog built-in (not a UVM construct).
- **INV-S-HDL-E-3** (no inline `assert property` outside bind files) — unchanged.
- **INV-S-HDL-E-4** (chart-vocabulary failure messages) — preserved + strengthened. Format-string content is byte-identical across the verb-change; severity tagging now matches the chart-contract-violation semantics.
- **INV-S-HDL-E-5** (per-simulator build wrapper) — unchanged; vendor simulators uniformly recognise `$error` per IEEE 1800-2017 §20.10.3.
- **INV-S-HDL-E-6** (Verilator-subset compliance) — preserved; `$error` is in the Verilator documented subset.

**Tests added**: existing test `test_chart_vocab_message_byte_identical_to_wave3_baseline` (added in the wave-3-future-remaining layered class hierarchy entry above) already pins the format-string byte-equivalence. This §15 amendment is doc-only — the test surface verifying the verb-change is the wave-2 conformance audit's [`tests/test_sos_08_wave2_conformance_and_e_verb_change.py`](../../tools/sos-codegen/tests/test_sos_08_wave2_conformance_and_e_verb_change.py), which asserts this §15 entry exists with the required normative content.

**Cited PCDNs / invariants**: PCDN-SOS-08-E-001 (layered hierarchy resolved by `fa06f7a` — verb-change is a follow-up clarification on top of that resolution); INV-S-HDL-E-4 (chart-vocab failure messages — strengthened by severity tagging).

Status: 🟢 **`$display`→`$error` verb-change normatively pinned**. Downstream tooling has a clear migration target; the chart-contract-violation semantics now match the simulator's severity machinery per IEEE 1800-2017 §20.10.3.
