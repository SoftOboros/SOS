# SOS-08-D — cocotb + SVA bind file emission (PRIMARY vector path)

**Status:** 🟢 **ratified 2026-05-23** (see §15).

## 0. Authority policy

This phase doc ratifies the **primary vector emission path** for the SOS HDL backend: a cocotb (cocotb-classic at v1, per SOS-08 PCDN-004) Python testbench co-emitted with a SystemVerilog Assertions (SVA) `bind` file. The pair is generated side-by-side from one bounded-reachability vector IR; both artifacts run concurrently against the device under test (DUT).

The umbrella `SOS-08-CONCEPTS.md` §5.4 ratified the four-emitter priority order (D → E → F → G); §6 sketched the SOS-08-D scope; PCDN-007 ratified "full SVA bind by default". This doc takes those ratifications as load-bearing input and produces the per-test emission contract: file layout, vector-IR consumption, simulator targets, pass/fail semantics, failure-message format, and CI integration.

Per the parent CLAUDE.md "Spec-Before-Code Planning Discipline / Phase document shape":

- **Normative** sections of this doc: §3 glossary, §4 source-of-truth map, §5 frozen decisions, §6 per-artifact contracts, §7 cross-artifact invariants (INV-S-HDL-D-*), §8 standards integration matrix additions, §12 acceptance checklist.
- **Informative** sections: §1 purpose, §2 problem statement, §11 non-goals, §15 change log.
- All keywords MUST, MUST NOT, SHALL, SHOULD, SHOULD NOT, MAY, RECOMMENDED are interpreted per RFC 2119 / RFC 8174 when capitalised.

This doc cites SOS-07 §6 invariants (INV-SOS-A through H), SOS-08 §7 invariants (INV-S-HDL-1 through 5), SOS-08-A §7 invariants (INV-S-HDL-A-1 through 5), and SOS-08-B §7 invariants (INV-S-HDL-B-1 through 5). None of the cited sets is re-derived.

SOS-08-D is the **PRIMARY** vector path per EOQ-003: cocotb-classic + Icarus/Verilator/GHDL on the open-source path; the SVA bind file shipped in the same emitted directory feeds the same-artifact formal-flow path (SymbiYosys / JasperGold) without re-emission.

## 1. Purpose

To freeze the emission contract for the cocotb testbench + SVA bind file pair so the SOS-08 codegen tool's HDL-emit step can produce vector + property artifacts that:

1. Drive RTL signals directly from the chart's bounded-reachability vector IR (one vector → one cocotb test function, one event per JSONL line per PCDN-009 / SOS-03 §7.1).
2. Bind SVA properties to the DUT instance covering every chart invariant in scope of the test (full bind by default per SOS-08 PCDN-007).
3. Run against open-source simulators (Icarus Verilog, Verilator, GHDL) with no paid-tool dependency — the load-bearing "napkin-to-silicon" claim survives unfunded teams (per EOQ-004-ROADMAP).
4. Produce CI-consumable pass/fail results (JUnit XML, gated by PCDN-SOS-08-D-002) where every failure renders in chart vocabulary per INV-SOS-H / INV-S-HDL-5 — never raw RTL signals alone.
5. Ship the SVA bind file as a reusable artifact: the formal-flow path (SymbiYosys / JasperGold) consumes it directly without re-authoring.

Without this freeze, the SOS-08-A L0 primitive testbenches (per SOS-08-A §12 (d)), the SOS-08-B L1 service-level testbenches (per SOS-08-B §12 (g)), and the SOS-08-C chart→FSM emitter's per-region vector tests have no common emitter contract — each would re-derive directory layout, vector-IR consumption, simulator invocation, and failure-message format. SOS-08-D is the unifying contract.

## 2. Problem statement

Four pressures motivate ratifying the cocotb + SVA emission contract as its own sub-phase rather than rolling it into SOS-08-A/B/C:

1. **One IR, two artifact families.** The chart's bounded-reachability analysis produces traces (event sequences, one per JSONL line) and invariants (structured property definitions, JSON). cocotb tests consume the traces; SVA properties encode the invariants. The dual emission is one transformation with two outputs; specifying it once at SOS-08-D avoids re-deriving it at A/B/C.

2. **Simulator-target matrix is cross-cutting.** L0 primitives (SOS-08-A), L1 services (SOS-08-B), and L2 chart-emitted FSMs (SOS-08-C) all run against the same simulator set (Icarus/Verilator/GHDL). The simulator-invocation conventions, dependency-pinning, and Makefile shape live at this sub-phase to avoid divergence.

3. **Formal-flow consumes the same SVA artifact, NOT a re-emission.** The umbrella's §5.4 priority order frames the formal path as "no separate emitter; same artifact, two consumers". Specifying the bind-file shape such that SymbiYosys + JasperGold ingest it unchanged is a one-time contract decision; locking it here prevents the SVA shape from being subtly tuned for cocotb-only consumption.

4. **Chart-vocabulary failure rendering is non-trivial.** A cocotb assertion fires and produces a Python stack trace; an SVA `bind` property fires and produces a `$display` with cycle + signal values. Neither is chart vocabulary by default. The emission contract MUST package both flows so the failure surfaces at the chart layer per INV-SOS-H. Designing this once is the only way it stays consistent across A/B/C deliverables.

## 3. Canonical glossary

Terms normative within SOS-08-D+. Authority relationships per §8.

| Term | Definition |
|---|---|
| **vector IR** | The on-disk canonical form of the chart's bounded-reachability output. Per SOS-08 PCDN-009: JSONL for traces (one event per line, schema extending SOS-03 §7.1), JSON for invariants (structured property definitions). Both are schema-validated by the codegen tool before emission. |
| **emitted test directory** | The per-DUT directory containing the cocotb testbench, SVA bind file, simulator-build artifacts (Makefile / `pytest` runner), and a `README.md` recording chart-side traceability metadata. As defined in §4; layout in §6.1. |
| **cocotb test function** | A Python coroutine decorated with `@cocotb.test()` that consumes one vector trace (one JSONL file) and drives the DUT accordingly. Per PCDN-D-003, one cocotb test function per vector (the default; chart-region-grouping is opt-in). |
| **SVA assertion module** | A SystemVerilog module containing `property` + `assert property` blocks for one DUT's chart-derived invariants. Lives at `<dut>_sva.sv` per SOS-08-A §4 / SOS-08-B §4. |
| **SVA bind directive** | A SystemVerilog `bind <dut_module> <assertion_module> u_assertions ( ... )` directive that attaches the assertion module to every instance of the DUT module. Lives at `<dut>_bind.sv` per SOS-08-A §4 / SOS-08-B §4. |
| **chart-vocabulary failure message** | A failure render of the form `"transition T42 in subchart auth.connecting expected event Q at cycle C, observed event Q' — violates INV-X"`. Names the chart artifact whose contract was violated; NEVER renders raw RTL signal traces alone. Per INV-SOS-H, INV-S-HDL-5, INV-S-HDL-B-5. |
| **JUnit XML report** | The CI-consumable per-test pass/fail / duration / failure-message format consumed by every major CI system. The cocotb runner emits one report file per test directory. PCDN-D-002 ratifies JUnit-XML vs cocotb's native `results.xml`. |
| **simulator backend** | One of `icarus`, `verilator`, `ghdl` — the open-source simulator used to drive the DUT. PCDN-D-001 ratifies the default. |
| **bound-analysis metadata** | The per-vector + per-invariant JSON object recording chart state names, transition IDs, invariant IDs, and chart-source file + line that the emitter copies into the cocotb test docstring + SVA property comment, so failures surface in chart vocabulary. |

## 4. Source-of-truth map

| Concept | Authority |
|---|---|
| Vector IR canonical form (JSONL traces; JSON invariants) | `SOS-08-CONCEPTS.md` §5.4 / PCDN-009 (umbrella); **mirror** here |
| L0 primitive contracts (per-primitive ports, SVA properties) | `SOS-08-A-CONCEPTS.md` (cited, not redefined) |
| L1 service contracts (per-service ports, SVA properties) | `SOS-08-B-CONCEPTS.md` (cited, not redefined) |
| L2 chart→FSM emission shape | `SOS-08-C-CONCEPTS.md` (forthcoming) |
| Per-DUT cocotb test directory layout | **this doc** §6.1 |
| Per-vector cocotb test function shape | **this doc** §6.2 |
| Per-DUT SVA bind file shape | **this doc** §6.3 |
| Simulator-invocation conventions (Makefile / `pytest`) | **this doc** §6.4 |
| Pass/fail contract | **this doc** §6.5 |
| Chart-vocabulary failure-message rendering | **this doc** §6.6 |
| CI integration / JUnit XML | **this doc** §6.7 (subject to PCDN-D-002) |
| Default open-source simulator | **this doc** §5.1 (subject to PCDN-D-001) |
| Vector-IR → cocotb driver translation rules | **this doc** §5.2 |
| Cocotb / Python version pinning | **this doc** §5.3 (subject to PCDN-D-005) |
| Cross-phase invariants INV-SOS-A through H | `SOS-07-CONCEPTS.md` §6 (cited, not redefined) |
| Cross-sub-phase invariants INV-S-HDL-1 through 5 | `SOS-08-CONCEPTS.md` §7 (cited, not redefined) |
| Cross-primitive invariants INV-S-HDL-A-1 through 5 | `SOS-08-A-CONCEPTS.md` §7 (cited, not redefined) |
| Cross-service invariants INV-S-HDL-B-1 through 5 | `SOS-08-B-CONCEPTS.md` §7 (cited, not redefined) |
| Cross-artifact invariants INV-S-HDL-D-1 through 6 | **this doc** §7 |

## 5. Frozen decisions

### 5.1 Default open-source simulator

Per SOS-08 §5.4 (cocotb-first) + EOQ-004-ROADMAP (open-source-synth-flow story), the cocotb backend default is **subject to PCDN-SOS-08-D-001**. Recommendation in §11: **Verilator** as the default for SV+mixed designs (compiles fastest for the wave-1 worked-example scale; bench-validated at SOS-08 §12 (e) against the ECP5 target); **Icarus Verilog** for pure-SV smoke + VHDL-co-simulation cases via cocotb's `iverilog` flow; **GHDL** for VHDL-pure DUTs. All three are mandatory simulator targets for SOS-08-A §12 (d) per-primitive testbenches.

Frozen-enumeration registration policy for the simulator set `{ icarus, verilator, ghdl }`: **Standards Action** (adding a fourth simulator — e.g. cvc, Surfer's eventual sim mode — requires §15 amendment here).

### 5.2 Vector-IR → cocotb driver translation rules

For each event in a vector trace (JSONL line per PCDN-009 / SOS-03 §7.1):

1. The event's `name` field names the chart event (`sem.take`, `queue.send`, `task.create`, etc.).
2. The event's `from_tid` (per SOS-03 §6.4) plus chart-side datamodel state become the cocotb-driver context — which port of the DUT receives the stimulus, and which port is sampled for the expected response.
3. The event's `expected_trace` slice names the cycle range within which the response signal MUST satisfy the chart-declared invariant; the cocotb test asserts the response within that range.
4. The L1 verb set from SOS-08-B §6 (`post` / `take` / `set` / `wait` / `acquire` / `release` / `send` / `receive`) maps to a cocotb `ReadyValidDriver` / `ReqAckDriver` interaction on the canonical handshake-port shape per INV-S-HDL-1.
5. Translation is one-to-one: one vector trace JSONL line → one cocotb await-and-assert step. Vector ordering is preserved; no reordering at emission.

Frozen-enumeration registration policy: **Standards Action**.

### 5.3 cocotb-classic at v1; Python 3.10+

Per SOS-08 PCDN-004 (ratified): **cocotb-classic at v1**. pyuvm is deferred to a SOS-08-F follow-on if a customer requests it. Python interpreter version is **subject to PCDN-SOS-08-D-005**; recommendation: minimum **Python 3.10** (matches cocotb 1.9+ baseline; aligns with the `disco-analyzer` and `streamz` Python pinning).

Frozen-enumeration registration policy for `{cocotb-classic at v1}`: **Standards Action** (mirrors SOS-08 PCDN-004).

### 5.4 Full SVA bind by default

Per SOS-08 PCDN-007 (ratified): every cocotb test SHALL bind every chart invariant in scope of the DUT, regardless of whether the test's vector exercises every state. Per-test scoping is opt-in via a `--scoped-bind` emitter flag for performance-critical regression runs only; the default emission is full coverage.

Frozen-enumeration registration policy: **Standards Action**.

### 5.5 Per-vector test isolation

Per PCDN-SOS-08-D-003 (recommendation: one cocotb test function per vector). The default emission produces N cocotb test functions for N vectors in the chart's bounded-reachability output; each is independently runnable, independently reportable in JUnit XML, and independently bisectable on failure. Chart-region-grouping (one test function per chart region driving all of that region's vectors) is opt-in via a `--group-by-region` emitter flag for compactness at the cost of attribution granularity.

Frozen-enumeration registration policy: **Specification Required** (one-per-vector-vs-grouped is a phase-local mechanic; flipping it later is cheap).

### 5.6 SVA bind file placement

Per PCDN-SOS-08-D-004 (recommendation: per-DUT bind file co-located with the cocotb test directory). One `<dut>_bind.sv` per DUT lives in the emitted test directory at `<dut>_bind.sv`; the assertion module itself lives at the RTL source layer (`rtl/<scope>/<dut>_sva.sv` per SOS-08-A §4 / SOS-08-B §4). The bind directive imports the assertion module by name; the test directory contains the binding glue, not the assertion bodies.

Frozen-enumeration registration policy: **Standards Action**.

## 6. Per-artifact contracts

### 6.1 Emitted test directory layout

Each DUT (one L0 primitive, one L1 service, or one chart-emitted L2 region) emits one test directory:

```
tests/<scope>/<dut>/
  test_<dut>.py             # cocotb testbench (one @cocotb.test per vector)
  <dut>_bind.sv             # SVA bind directive importing <dut>_sva.sv
  vectors/                  # one JSONL file per vector, named test_<NNNN>_<chart-region>.jsonl
    test_0001_seed.jsonl
    test_0002_boundary.jsonl
    ...
  invariants.json           # structured invariant definitions consumed by the SVA emitter
  Makefile                  # cocotb-classic Makefile (icarus / verilator / ghdl targets)
  pytest.ini                # pytest runner config (PCDN-D-002 alternative path)
  README.md                 # chart-side traceability metadata (chart file, region, invariants)
  build/                    # simulator outputs (transient; gitignored)
```

Per SOS-08-A §4: `<dut>_sva.sv` (the assertion module bodies) lives at `rtl/<scope>/<dut>_sva.sv`. The bind directive in this directory references that assertion module by name; the assertion bodies are NOT duplicated here.

### 6.2 Per-vector cocotb test function shape

For each vector `test_<NNNN>_<chart-region>.jsonl` in `vectors/`, the emitter generates one `@cocotb.test()` Python coroutine in `test_<dut>.py`:

```python
@cocotb.test()
async def test_0001_seed(dut):
    """
    Chart-side traceability metadata (per INV-SOS-H, INV-S-HDL-5):
      Chart file:    rtos_kernel.scxml
      Region:        scheduler
      Vectors origin: Seed (one of the six SOS-00 §7.4 fixtures)
      Invariants in scope: INV-S-HDL-A-2 (handshake associativity),
                           INV-S-HDL-B-3 (service-level SVA bind),
                           SVA-MBX-1 (per-lane ordering)
    """
    await _reset_dut(dut)
    vector = load_jsonl("vectors/test_0001_seed.jsonl")
    for event in vector:
        await _drive_event(dut, event)
        await _check_expected(dut, event, chart_state=event["chart_state"])
```

Helper functions `_reset_dut`, `_drive_event`, `_check_expected`, and `load_jsonl` live in `<scope>/_cocotb_helpers.py` (shared per-scope to avoid duplication; per PCDN-A-007 / PCDN-D-006 each DUT gets one `test_<dut>.py` file).

Per §5.5, one cocotb test function per vector is the default. Test names mirror the vector filename (`test_<NNNN>_<chart-region>`) so JUnit XML attribution is unambiguous.

### 6.3 Per-DUT SVA bind file shape

The `<dut>_bind.sv` file binds the assertion module (`<dut>_sva.sv`) to every instance of the DUT:

```systemverilog
// Generated by SOS-08-D codegen — do not hand-edit (INV-SOS-A)
// Chart-side traceability: chart=rtos_kernel.scxml region=scheduler
// Invariants bound: SVA-MBX-1, SVA-MBX-2, SVA-MBX-3, SVA-MBX-4, SVA-MBX-5
//                    INV-S-HDL-A-2, INV-S-HDL-B-3
bind sos_mailbox sos_mailbox_sva u_sva (
    .clk_p(clk_p), .rst_p(rst_p),
    .clk_c(clk_c), .rst_c(rst_c),
    .post_valid(post_valid), .post_ready(post_ready), .post_prio(post_prio),
    .post_msg(post_msg), .post_rc(post_rc),
    .take_req(take_req), .take_ack(take_ack), .take_msg(take_msg),
    .take_prio(take_prio), .irq_non_empty(irq_non_empty)
);
```

The bind directive routes every port of the DUT into the assertion module by name; the assertion module references chart-derived invariants by their stable ID per SOS-08-A §6 / SOS-08-B §6.

For DUTs whose vendor-IP shim variant differs in internal signal exposure (per SOS-08-A §5.3 / INV-S-HDL-A-3), the bind file MUST reference only the wrapper-interface ports — assertions on internal vendor-IP signals are prohibited (the byte-identical wrapper interface is the only binding surface that survives the `-Dvendor=*` selection).

### 6.4 Simulator-invocation conventions

The emitted Makefile follows the cocotb-classic standard `cocotb-config --makefiles` boilerplate, with three named targets (one per simulator backend per §5.1):

```makefile
SIM ?= verilator
TOPLEVEL_LANG = verilog
TOPLEVEL = sos_mailbox
MODULE = test_sos_mailbox
VERILOG_SOURCES = $(PWD)/../../../rtl/services/sos_mailbox.sv \
                  $(PWD)/../../../rtl/services/sos_mailbox_sva.sv \
                  $(PWD)/sos_mailbox_bind.sv
EXTRA_ARGS += --trace --trace-structs   # verilator default; conditional per SIM
include $(shell cocotb-config --makefiles)/Makefile.sim
```

The Makefile targets are `make sim SIM=verilator`, `make sim SIM=icarus`, `make sim SIM=ghdl` (the last only when the DUT is VHDL or a mixed-language test). Per SOS-08-A §12 (d), every L0 primitive testbench MUST pass on at least Icarus + Verilator; VHDL-pure primitives MUST additionally pass on GHDL.

Alternative `pytest` runner: `pytest.ini` configures a `pytest`-driven invocation via the `cocotb-test` package (subject to PCDN-D-002 / D-007); identical test attribution, identical simulator selection, different orchestrator.

### 6.5 Pass/fail contract

A cocotb test PASSES iff **all** of the following hold:

1. Every vector-driven cycle produces RTL signal values matching the vector's `expected_trace` (per SOS-03 §6.5 field-by-field comparison rules, extended to RTL signals per the SOS-03 §15 amendment co-landing with SOS-08-D ratification).
2. Every SVA `bind` property in `<dut>_bind.sv` NEVER fires its `assert property (...)` violation across the test's cycle range.
3. The cocotb test function completes without raising any exception.
4. The simulator exits with status code 0.

A cocotb test FAILS iff any of (1)-(4) does not hold. Test result emitted as JUnit XML per §6.7 (subject to PCDN-D-002), with one `<testcase>` element per `@cocotb.test()` function and one `<failure>` element per failing assertion / property.

A cocotb test ERRORS iff the test infrastructure itself fails (vector JSONL parse error, missing RTL source, simulator crash, bind directive references a non-existent assertion module). Errors are distinct from failures in JUnit-XML output per §6.7.

### 6.6 Chart-vocabulary failure-message rendering (INV-S-HDL-D-5)

Per INV-SOS-H / INV-S-HDL-5 / INV-S-HDL-B-5, every failure message SHALL render in chart vocabulary, NEVER as raw RTL signal traces alone. The emitter generates two failure-formatter helpers:

**Cocotb-side helper** (used by `_check_expected`):

```python
def _format_failure(event, observed, chart_state, transition_id, invariant_id):
    return (
        f"chart={CHART_FILE} region={CHART_REGION} "
        f"transition={transition_id} state={chart_state} "
        f"expected event={event['name']} at cycle={event['cycle']}, "
        f"observed={observed} — violates {invariant_id}"
    )
```

**SVA-side `$display` macro** (emitted into `<dut>_sva.sv` and invoked from each `assert property (...) else $display(...)`):

```systemverilog
`define SOS_FAIL(INV_ID, TRANSITION_ID, STATE) \
  $display("SOS-FAIL chart=%s region=%s transition=%s state=%s invariant=%s @ %t", \
    "rtos_kernel.scxml", "scheduler", `"TRANSITION_ID`", `"STATE`", `"INV_ID`", $time)
```

The emitted bind/assertion code MUST call `\`SOS_FAIL` (or its cocotb-side equivalent) on every property-violation `else` clause; the test post-processor (per §6.7) scrapes `SOS-FAIL` lines from simulator stdout and merges them into the JUnit XML `<failure>` payload. A failure that surfaces as only an RTL signal trace is a verification-emission bug per INV-S-HDL-D-5, not a passing test.

### 6.7 JUnit XML CI integration

The cocotb-classic runner natively writes `results.xml` (cocotb's xunit-like format). Per PCDN-SOS-08-D-002 (recommendation: emit JUnit XML directly via cocotb's `COCOTB_RESULTS_FILE` + a post-processor that rewrites cocotb's xunit shape into pure JUnit XML), every CI system (GitHub Actions, GitLab CI, Jenkins, Buildkite, CircleCI) consumes the result without per-system adapters.

The emitter generates a post-processor script `tests/<scope>/<dut>/post_results.py` that:

1. Reads `build/results.xml`.
2. Scrapes `SOS-FAIL ...` lines from `build/sim.log` (simulator stdout per §6.6).
3. Merges chart-vocabulary failure messages into each `<failure>` element.
4. Writes `build/junit.xml` in pure JUnit XML.

CI consumes `build/junit.xml`. The post-processor is per-DUT; the codegen tool generates it from a single Jinja template.

## 7. Cross-artifact invariants

In addition to INV-SOS-A through H (SOS-07), INV-S-HDL-1 through 5 (SOS-08), INV-S-HDL-A-1 through 5 (SOS-08-A), and INV-S-HDL-B-1 through 5 (SOS-08-B) — all cited, none re-derived — the following invariants are normative across SOS-08-D:

- **INV-S-HDL-D-1 — Dual artifact, one IR.** The cocotb testbench and the SVA bind file MUST be co-emitted from one bounded-reachability vector IR pass. Splitting the emission (cocotb today, SVA later) reintroduces drift between trace expectations and property expectations; the contract is single-pass dual-output. Concretizes INV-SOS-B (vectors-as-deliverable) for the HDL target.

- **INV-S-HDL-D-2 — Open-source-simulator coverage at v1.** Every emitted cocotb testbench MUST pass on at least Verilator + Icarus Verilog (for SV / mixed DUTs) or GHDL + Icarus Verilog (for VHDL-pure DUTs). A testbench that requires a paid simulator at v1 is a regression of the napkin-to-silicon adoption story (EOQ-004-ROADMAP).

- **INV-S-HDL-D-3 — Vector-IR is read-only at the emitter boundary.** The cocotb emitter MUST consume the JSONL vector IR without mutation; any per-emitter transformation (cycle-range expansion, datamodel-extraction, event-coalescing) MUST be expressed as a separate pre-emission pass with its own audit trail. Forbids silent vector-IR mutation at the emitter (the failure mode INV-SOS-A is designed to prevent at the chart layer; this is the emitter-layer analog).

- **INV-S-HDL-D-4 — Same SVA artifact feeds cocotb and formal flow.** The emitted `<dut>_sva.sv` + `<dut>_bind.sv` pair MUST be consumable by SymbiYosys + JasperGold WITHOUT re-emission or per-tool adaptation. A formal-flow consumer ingests the same bind file the cocotb test does. Tuning the SVA shape for cocotb-only consumption (e.g. using `cocotb` Python helpers in `$display` arguments) is prohibited.

- **INV-S-HDL-D-5 — Chart-vocabulary failure messages.** Every cocotb assertion failure AND every SVA property violation MUST render with chart-vocabulary metadata per §6.6 (chart file, region, transition ID, state ID, invariant ID). A failure that surfaces only RTL signal values is a verification-emission bug, not a passing test. Concretizes INV-SOS-H / INV-S-HDL-5 / INV-S-HDL-B-5 for the cocotb + SVA target.

- **INV-S-HDL-D-6 — Per-vector test isolation by default.** The default emission produces one `@cocotb.test()` function per vector; chart-region-grouping (one function per region driving all vectors) is opt-in (per §5.5). The default preserves CI attribution granularity: a failing vector names exactly one failing test in JUnit XML.

## 8. Standards integration matrix additions

The following rows EXTEND the SOS-07 §7 + SOS-08 §8 + SOS-08-A §8 + SOS-08-B §8 matrices.

| Concept | Upstream authority | Local relationship | Phase that declares it | Mutation rights |
|---|---|---|---|---|
| cocotb 1.x testbench API (`@cocotb.test`, `cocotb.start`, `RisingEdge`, `Timer`, drivers) | cocotb project (open) | **derive** | SOS-08-D | none — emit conformant Python |
| Icarus Verilog simulator | open project (Stephen Williams) | **derive** | SOS-08-D | none |
| Verilator simulator | open project (Veripool) | **derive** | SOS-08-D | none |
| GHDL VHDL simulator | open project | **derive** | SOS-08-D | none |
| SVA `bind` directive (IEEE 1800-2017 §23.11) | IEEE 1800-2017 | **derive** | SOS-08-D | none — emit conformant SV |
| JUnit XML (xunit family report format) | de facto (Ant/JUnit/Surefire) | **mirror** | SOS-08-D | none |
| Python 3.10+ | Python Software Foundation | **derive** (runtime for cocotb) | SOS-08-D | none |
| `cocotb-test` pytest plugin (alt runner per PCDN-D-007) | open project | **derive** | SOS-08-D | none |
| SymbiYosys formal flow | YosysHQ / open | **derive** (consumes SVA bind artifacts unchanged) | SOS-08-D | none |
| JasperGold formal flow | Cadence (proprietary) | **derive** (consumes SVA bind artifacts unchanged) | SOS-08-D | none — output-only relationship |

## 9. Frozen enumerations from SOS-08-D

This phase freezes three enumerations:

### 9.1 Simulator backend set

`{ icarus, verilator, ghdl }` per §5.1. Registration policy: **Standards Action**.

### 9.2 Test result classes

`{ PASS, FAIL, ERROR }` per §6.5 (and the cocotb-classic `SKIP` value carries forward for `@cocotb.test(skip=True)` markers). Registration policy: **Standards Action** (mirrors cocotb-classic's set).

### 9.3 Emitter-output-directory entries

Per §6.1: `{ test_<dut>.py, <dut>_bind.sv, vectors/, invariants.json, Makefile, pytest.ini, README.md, build/ }`. Registration policy: **Specification Required** (adding an entry like `wave_dump_config.yaml` is a phase-owner walkthrough; removing one requires §15 amendment).

## 10. Reconciliation decisions vs adjacent repo primitives

### vs. SOS-03 §7.1 conformance-vector schema

The cocotb emitter MUST consume vector traces in the SOS-03 §7.1 JSONL format extended for HDL targets. A SOS-03 §15 amendment co-lands with SOS-08-D ratification adding RTL-target fields (`cycle`, `dut_port`, `signal_width`, `chart_region`) to the per-event JSON shape; the existing software-target fields (`from_tid`, `tcb`, `ready`, `sems`, `queues`) stay unchanged and are simply unused by the HDL emitter. INV-S-HDL-D-3 forbids the emitter from mutating the IR; the SOS-03 extension is the canonical shape, not an emitter-local transformation.

### vs. SOS-08 §5.4 vector emission priority

SOS-08-D is the **primary** path per §5.4 (D → E → F → G). This doc ratifies the primary-path contract; SOS-08-E (SV testbench), SOS-08-F (UVM sequences), and SOS-08-G (waveform annotation) ratify their own contracts in their own sub-phase docs. SOS-08-E and SOS-08-F MAY share the same SVA bind file emission machinery as SOS-08-D (per INV-S-HDL-D-4: same SVA artifact, multiple consumers); SOS-08-G consumes a different IR (cycle-level signal traces, not chart vocabulary events).

### vs. SOS-08-A §6 + SOS-08-B §6 per-DUT testbench mentions

SOS-08-A §12 (d) and SOS-08-B §12 (g) name per-DUT cocotb testbenches as acceptance gates without specifying the testbench emission machinery. This doc IS that emission machinery. The per-DUT testbench files (`tests/<dut>/test_<dut>.py`, `tests/<dut>/<dut>_bind.sv`, `tests/<dut>/vectors/`) are the **artifacts** of this sub-phase's emitter; the emitter ITSELF lives in `tools/sos-codegen/hdl_emit/cocotb_sva.py` (forthcoming at implementation cycle).

### vs. INV-SOS-H (vector-to-chart traceability)

INV-S-HDL-D-5 concretizes INV-SOS-H for the cocotb + SVA target. Every cocotb failure AND every SVA property violation MUST surface chart vocabulary; the §6.6 formatter-helpers + post-processor are the load-bearing mechanism.

### vs. INV-SOS-A (chart-as-source)

INV-S-HDL-D-3 (vector-IR read-only at emitter boundary) is the emitter-layer analog of INV-SOS-A (chart-as-source at the upstream layer). Both forbid silent mutation of the upstream spec at the consumer boundary; INV-SOS-A at the chart-text layer, INV-S-HDL-D-3 at the vector-IR layer.

### vs. SOS-08-A PCDN-A-007 (cocotb test-bench shape)

SOS-08-A PCDN-A-007 recommends "one Python file per primitive". This doc's PCDN-D-006 echoes that recommendation at the SOS-08-D layer for primitives, services, and chart-emitted FSMs alike. Resolving PCDN-A-007 against the one-file-per-DUT shape would auto-resolve PCDN-D-006 in the same direction; the two are coordinated.

## 11. Non-goals

This phase does NOT:

- Author the L0 primitive RTL or SVA assertion module bodies. Those are SOS-08-A artifacts; SOS-08-D consumes them via the bind directive.
- Author the L1 service RTL or service-level SVA assertion module bodies. Those are SOS-08-B artifacts.
- Author the chart→FSM emission contract or per-region SVA invariants. Those are SOS-08-C artifacts.
- Author the SystemVerilog testbench shape, UVM sequence shape, or waveform-annotation shape. Those are SOS-08-E / -F / -G artifacts.
- Implement the codegen tool's HDL-emit pass. SOS-08-D ratifies the emission CONTRACT; `tools/sos-codegen/hdl_emit/cocotb_sva.py` is the implementation artifact landing at SOS-08-D implementation cycle (post-ratification).
- Bench-validate the emitted testbenches on the Lattice ECP5 worked example. That is SOS-08 §12 (e) — implementation-phase bench gate, not this concept doc.
- Resolve the SOS-03 §15 amendment that extends the vector schema to HDL targets. The amendment text is sketched in §10 reconciliation; the amendment itself co-lands with this doc's ratification as a separate edit to `SOS-03-CONCEPTS.md`.
- Specify the chart-derived metadata-extraction shape. That falls out of SOS-08-C's chart→FSM emission; SOS-08-D consumes whatever metadata SOS-08-C produces, via the bound-analysis-metadata field set named in §3 glossary.

## 12. Acceptance checklist

A conforming SOS-08-D ratification satisfies all of:

- (a) ⏸ PCDN-SOS-08-D-001 through 007 (§14) resolved with §15 amendment entries.
- (b) ⏸ Per-artifact contracts §6.1 through §6.7 ratified.
- (c) ⏸ Cross-artifact invariants INV-S-HDL-D-1 through 6 (§7) ratified.
- (d) ⏸ Standards integration matrix additions §8 ratified (10 rows).
- (e) ⏸ SOS-03 §15 amendment extending the vector schema to HDL targets co-landed.
- (f) ⏸ Per-DUT cocotb testbench files (`tests/<scope>/<dut>/test_<dut>.py`, `<dut>_bind.sv`, `vectors/`, `Makefile`, `README.md`) authored for at least one L0 primitive (recommended: `sos_fifo_async` per SOS-08 §12 (c)) — implementation-cycle gate, not ratification gate.
- (g) ⏸ Per-DUT cocotb test passes on at least Verilator + Icarus Verilog (INV-S-HDL-D-2) — implementation-cycle gate.
- (h) ⏸ Per-DUT SVA bind file consumed unchanged by SymbiYosys against the same DUT (INV-S-HDL-D-4) — implementation-cycle gate.
- (i) ⏸ Codegen-tool emit-path (`tools/sos-codegen/hdl_emit/cocotb_sva.py`) authored and unit-tested against the seed vectors from SOS-03 §6.6 — implementation-cycle gate.
- (j) ⏸ Bench-verifiable on the Lattice ECP5 worked-example target (per SOS-08 §12 (e)) — implementation-cycle gate, joint with SOS-08-A / -B implementation.

(a) is the ratification gate; (e) is the co-landing dependency; (b)-(d) flip from ⏸ to ✅ at ratification; (f)-(j) flip as the implementation lands.

A conforming SOS-08-D *without* GHDL coverage (cocotb tests pass on Verilator + Icarus only, no VHDL-pure DUT exercised at v1) satisfies (a)-(e), (g) with reduced scope (no `make sim SIM=ghdl` target required), (h)-(j). This second-tier conformance level supports the Lattice ECP5 first-target story (which uses SV-pure RTL by default) without forcing VHDL-pure testbenches at v1; VHDL-pure GHDL coverage is deferred to a SOS-08-D amendment if a VHDL-pure customer requests it.

## 13. Files cited

| Path | Role |
|---|---|
| `docs/concepts/SOS-08-CONCEPTS.md` | Umbrella; §5.4 vector emission priority + PCDN-007 full-bind + PCDN-009 vector-IR. |
| `docs/concepts/SOS-08-A-CONCEPTS.md` | Per-primitive SVA assertion module locations (`rtl/<primitive>/<primitive>_sva.sv`). |
| `docs/concepts/SOS-08-B-CONCEPTS.md` | Per-service SVA assertion module locations (`rtl/services/sos_<service>_sva.sv`); per-service cocotb test directories (`tests/services/sos_<service>/`). |
| `docs/concepts/SOS-08-C-CONCEPTS.md` | Future sub-phase; chart→FSM emission produces the per-region DUTs SOS-08-D testbenches consume. |
| `docs/concepts/SOS-08-E-CONCEPTS.md` | Future sub-phase; SV testbench emission shares this doc's SVA bind file artifacts per INV-S-HDL-D-4. |
| `docs/concepts/SOS-08-F-CONCEPTS.md` | Future sub-phase; UVM sequence emission shares this doc's SVA bind file artifacts. |
| `docs/concepts/SOS-08-G-CONCEPTS.md` | Future sub-phase; waveform + annotation emission consumes a separate IR (cycle-level signal traces). |
| `docs/concepts/SOS-07-CONCEPTS.md` | INV-SOS-A through H + AuthorityRelationship matrix. |
| `docs/concepts/SOS-03-CONCEPTS.md` | Conformance vector framework; §7.1 schema extended at SOS-08-D ratification via co-landing §15 amendment. |
| `docs/concepts/SOS-ROADMAP-07-PLUS.md` | Informative roadmap; EOQ-003 (cocotb primary) + EOQ-004 (open-source-synth) resolutions this doc realises. |
| `rtl/<primitive>/<primitive>_sva.sv` | Per-primitive assertion module bodies (consumed by `<dut>_bind.sv`). |
| `rtl/services/sos_<service>_sva.sv` | Per-service assertion module bodies. |
| `tests/<scope>/<dut>/` | Per-DUT emitted test directory (implementation-cycle artifact). |
| `tools/sos-codegen/hdl_emit/cocotb_sva.py` | Codegen tool's HDL-emit pass (implementation-cycle artifact). |
| Parent `CLAUDE.md` | Spec-Before-Code discipline; Phase document shape. |

## 14. Pending Concept Decision Notices (PCDNs)

These open questions move this doc from 🟡 drafted to 🟢 ratified.

- **PCDN-SOS-08-D-001 — Default open-source simulator on the cocotb path.** Verilator (fastest for SV-pure designs; bench-validated against ECP5; SV-only at v1 without `--timing`), Icarus Verilog (cocotb's traditional default; SV + VHDL co-sim friendliness; slower for large designs), or GHDL (VHDL-pure)? **Recommendation**: **Verilator** as `SIM ?=` default in the emitted Makefile (fastest iteration cycle for the wave-1 worked-example scale; matches the ECP5 SV-pure RTL path of SOS-08 §12 (e)); Icarus as the secondary target for SV+VHDL co-sim cases; GHDL mandatory only when the DUT is VHDL-pure. All three remain testbench acceptance targets per INV-S-HDL-D-2.

- **PCDN-SOS-08-D-002 — JUnit XML emission path: cocotb-native `results.xml` direct, post-processed JUnit XML, or both?** cocotb-classic's native `results.xml` is xunit-shaped but uses cocotb-specific element ordering that some CI systems mis-parse. **Recommendation**: emit cocotb's native `results.xml` AND post-process to pure JUnit XML at `build/junit.xml` via the §6.7 `post_results.py` helper; CI consumes `build/junit.xml`. Two files, zero CI-specific adapters needed.

- **PCDN-SOS-08-D-003 — Per-vector test isolation: one `@cocotb.test` per vector, OR one per chart region driving all vectors?** Per-vector gives unambiguous JUnit-XML attribution (a failing vector names exactly one failing test); per-region compresses to one test function per region (faster simulator-warmup overhead amortisation; harder to bisect). **Recommendation**: one cocotb test function per vector at v1 (preserves attribution granularity per INV-S-HDL-D-6); per-region grouping opt-in via `--group-by-region` emitter flag for performance-critical regression runs.

- **PCDN-SOS-08-D-004 — SVA bind file placement: per-DUT in test directory (`tests/<scope>/<dut>/<dut>_bind.sv`), OR one shared bind file across all tests (`tests/<scope>/all_binds.sv`)?** Per-DUT keeps the binding glue with the DUT-specific test; shared is more compact but harder to attribute. **Recommendation**: per-DUT bind file co-located with the cocotb test directory; assertion module bodies live at the RTL layer (`rtl/<scope>/<dut>_sva.sv`) per SOS-08-A / SOS-08-B; only the bind directive lives in the test directory.

- **PCDN-SOS-08-D-005 — Python interpreter minimum version.** cocotb 1.9 (current stable) requires Python 3.6+; cocotb's 2.0 alpha requires 3.10+. Choosing Python 3.10+ aligns with disco-analyzer / streamz / softoboros parent pinning (and the type-hint surface modern tooling expects); 3.6+ widens the install surface. **Recommendation**: **Python 3.10+** at v1 (matches parent-repo pinning, future-proofs against cocotb 2.x adoption when it stabilises); document the minimum in `tests/<scope>/<dut>/README.md`.

- **PCDN-SOS-08-D-006 — One cocotb file per DUT or shared harness.** SOS-08-A's PCDN-A-007 recommends one file per primitive. This sub-phase generalises that to all DUTs (primitives, services, chart-emitted FSMs). **Recommendation**: one `test_<dut>.py` per DUT, with shared helpers at `tests/<scope>/_cocotb_helpers.py`. Mirrors SOS-08-A PCDN-A-007; auto-resolves with that PCDN.

- **PCDN-SOS-08-D-007 — pytest runner alongside Makefile?** cocotb-classic ships a Makefile invocation path; `cocotb-test` overlays a `pytest` runner that some shops prefer (parallel test execution, richer fixtures, native CI integration). **Recommendation**: emit BOTH a `Makefile` (canonical cocotb-classic path) AND a `pytest.ini` driving `cocotb-test`. The two paths produce equivalent JUnit XML output; users opt in to either. Doubles the emitter's per-DUT output by a fixed handful of lines; cost is negligible compared to user-base-fragmentation cost if only one path ships.

## 15. Change log

### 2026-05-23 — Initial draft (Ira)

- Authored `SOS-08-D-CONCEPTS.md` as the per-sub-phase concept doc for cocotb + SVA bind file emission under the SOS-08 umbrella.
- Frozen decisions §5: default open-source simulator pending PCDN-D-001 (recommendation Verilator); vector-IR → cocotb driver translation rules; cocotb-classic + Python 3.10+; full SVA bind by default per SOS-08 PCDN-007; per-vector test isolation default; per-DUT SVA bind file placement.
- Per-artifact contracts §6.1 through §6.7: emitted test directory layout, per-vector cocotb test function shape, per-DUT SVA bind file shape, simulator-invocation conventions (Makefile + pytest alternative), pass/fail contract, chart-vocabulary failure-message rendering, JUnit XML CI integration.
- Cross-artifact invariants §7: INV-S-HDL-D-1 (dual artifact, one IR), INV-S-HDL-D-2 (open-source-simulator coverage at v1), INV-S-HDL-D-3 (vector-IR read-only at emitter boundary), INV-S-HDL-D-4 (same SVA artifact feeds cocotb and formal flow), INV-S-HDL-D-5 (chart-vocabulary failure messages), INV-S-HDL-D-6 (per-vector test isolation by default).
- Standards integration matrix §8 adds 10 rows (cocotb, Icarus, Verilator, GHDL, SVA bind directive, JUnit XML, Python 3.10+, cocotb-test, SymbiYosys, JasperGold).
- Reconciliation §10 names the relationship to SOS-03 (§15 amendment co-landing), SOS-08 §5.4, SOS-08-A / -B per-DUT testbench mentions, INV-SOS-H, INV-SOS-A, and SOS-08-A PCDN-A-007.
- 7 PCDNs raised covering default simulator, JUnit XML emission path, per-vector isolation default, SVA bind file placement, Python minimum version, one-file-per-DUT, and pytest-runner alongside Makefile.

Status: 🟡 **drafted**, awaiting PCDN walkthrough.

### 2026-05-23 — Ratified after PCDN walkthrough (Ira)

All seven PCDNs from §14 resolved with recommendations accepted.

- **PCDN-SOS-08-D-001 → RESOLVED**: default open-source simulator on the cocotb path is **Verilator** (`SIM ?= verilator` in the emitted Makefile). Icarus Verilog is the secondary target for SV + VHDL co-sim. GHDL is mandatory only for VHDL-pure DUTs. All three remain testbench acceptance targets per INV-S-HDL-D-2.
- **PCDN-SOS-08-D-002 → RESOLVED**: emit cocotb's native `results.xml` AND post-process to pure JUnit XML at `build/junit.xml` via `post_results.py`; CI consumes `build/junit.xml`. Two files, zero CI-specific adapters.
- **PCDN-SOS-08-D-003 → RESOLVED**: per-vector test isolation default — one `@cocotb.test` function per vector at v1 (unambiguous JUnit-XML attribution per INV-S-HDL-D-6); `--group-by-region` opt-in flag amortises simulator-warmup for regression runs.
- **PCDN-SOS-08-D-004 → RESOLVED**: SVA bind file per-DUT, co-located in the cocotb test directory (`tests/<scope>/<dut>/<dut>_bind.sv`); assertion module bodies live at the RTL layer (`rtl/<scope>/<dut>_sva.sv`) per SOS-08-A / SOS-08-B; only the bind directive lives in the test directory.
- **PCDN-SOS-08-D-005 → RESOLVED**: Python interpreter minimum version is **Python 3.10+** at v1 (matches parent-repo pinning, future-proofs against cocotb 2.x).
- **PCDN-SOS-08-D-006 → RESOLVED**: one `test_<dut>.py` per DUT, with shared helpers at `tests/<scope>/_cocotb_helpers.py`. Mirrors SOS-08-A PCDN-A-007.
- **PCDN-SOS-08-D-007 → RESOLVED**: emit **both** a `Makefile` (canonical cocotb-classic path) AND a `pytest.ini` driving `cocotb-test`. Two paths produce equivalent JUnit XML.

**§5 / INV amendments**:
- §5 frozen-decisions extended with the seven resolutions above by reference.
- INV-S-HDL-D-2 (open-source-simulator coverage) wording extended: "Verilator as primary, Icarus + GHDL as secondary targets; all three remain acceptance targets at v1".
- INV-S-HDL-D-6 (per-vector test isolation) wording extended: "default emission shape is one `@cocotb.test` per vector; `--group-by-region` opt-in available for regression-cycle amortisation".

**Coordinated co-landing**: SOS-03 §15 amendment extending the vector-IR schema to HDL targets lands alongside SOS-08-D implementation (per §10 reconciliation).

**Status**: 🟢 **ratified**. Implementation of the cocotb + SVA bind emission path in `tools/sos-codegen/` is now unblocked. SOS-08-E / SOS-08-F / SOS-08-G that share the vector-IR boundary with SOS-08-D have a frozen co-emission shape to reference.

### 2026-05-23 — Impl wave-1 PCDN amendments (Ira)

Wave-1 implementation of the cocotb + SVA walkers in `tools/sos-codegen/` surfaced eight sub-PCDN decision points whose shape was under-specified by the prior ratification entry. The wave-1 walker code makes one defensible call per point; this amendment ratifies those calls into the SOS-08-D normative surface so subsequent waves (and SOS-08-E / -F / -G consumers of the same emit-layout) reference a frozen contract.

**Sub-PCDN resolutions**:

- **PCDN-SOS-08-D-wave1-step-schema → RESOLVED**: vector `steps[]` schema is `{index, inputs, expected_state, transition_id}` per step — the wave-1 cocotb walker-tolerated shape. `index` is the step's sequential position (0-based). `inputs` is a `{port_name: value}` dict naming the DUT input ports driven on this step. `expected_state` is the chart-state ID the DUT is expected to settle into after this step. `transition_id` references the chart's transition list (the SCXML `<transition>` element that fires on this step). Co-landing SOS-03 §15 amendment ratifies this as a SOS-03 extension on the vector schema. Future RTL-target extensions (cycle, dut_port, signal_width, chart_region) layer on top non-breakingly.

- **PCDN-SOS-08-D-wave1-cli-unified → RESOLVED**: CLI offers BOTH the split `--target cocotb` / `--target sva` forms AND a unified `--target sos-08-d` that emits both artifacts in one invocation. The unified target dispatches through both walkers and merges the result dicts (which now share the `tests/<chart>/` prefix per PCDN-SOS-08-D-wave1-file-layout, so no key collision). Users pick split for iterative emit of one artifact (e.g. re-running just the cocotb half while iterating on the test driver); unified for fresh end-to-end emission.

- **PCDN-SOS-08-D-wave1-sva-port-name → RESOLVED**: the SVA assertion module's input port is named `current_state` (matching the DUT's output port name). The wave-1 walker initially used `state_q` (the DUT's internal register name); module-type bind connects external port to external port, so the SVA input MUST match the DUT output name verbatim. The bind directive emits as `.current_state(current_state)`.

- **PCDN-SOS-08-D-wave1-file-layout → RESOLVED**: BOTH cocotb and SVA walkers emit ALL filenames under the `tests/<chart>/` prefix. This unifies the wave-1 asymmetry (cocotb walker initially emitted flat into `tests/`, SVA walker prefixed into `tests/<chart>/`). `<chart>` is the lowercased + filesystem-sanitised chart name. main.py's intermediate-dir-creation logic is now uniform — handled by the prefix in both walkers' emit step, no per-walker branch.

**Agent-default ratifications** (decisions the wave-1 walkers made by default; promoting to normative):

- **INV-D numbering scheme**: per-transition assertions get monotonic IDs `INV-D-3`, `INV-D-4`, ..., `INV-D-N` in document order. INV-D-1 is the one-hot state-encoding assertion; INV-D-2 is the reset→initial-state assertion; INV-D-3 onwards are per-transition assertions. Each `assert property` has a unique `else $fatal(1, "SOS-08-D INV-D-N: ...")` clause so individual assertion failures are bisectable per INV-S-HDL-D-5.
- **Per-DUT directory case**: the chart name is lowercased + filesystem-sanitised for the directory name (`MyChart` → `tests/mychart/`). This matches both walkers' wave-1 implementation. Case-preserving directory names are NOT ratified; lowercased is canonical.
- **Scaffold vector naming convention**: `000-reset` is the canonical wave-1 scaffold vector ID (filename `vectors/000-reset.json`). Follows the SOS-03 §6.3 `<NNNN>-<slug>.json` shape with `0001` reserved as the first author-assigned id. The scaffold occupies the `000` 3-digit form for filesystem brevity (the leading-zero count is dropped from 4 to 3 for the scaffold-only slot).
- **post_results.py JUnit XML post-processor**: §6.7 names this artifact but it is DEFERRED to wave-2. Wave-1 emits cocotb-native `results.xml` (which most CI systems parse correctly); the post-processor refines that to pure JUnit XML at `build/junit.xml` (per PCDN-D-002). Deferred to wave-2 to keep wave-1 scaffold scope narrow.

**§-amendments by reference**:

- §6.1 (emit directory layout): unified `tests/<chart>/` prefix across both walkers per PCDN-SOS-08-D-wave1-file-layout.
- §6.2 (cocotb test shape): step schema pinned per PCDN-SOS-08-D-wave1-step-schema.
- §6.3 (SVA bind file shape): SVA module input port named `current_state` per PCDN-SOS-08-D-wave1-sva-port-name; INV-D numbering monotonic per the agent-default ratification above.
- §6.7 (JUnit XML emission): post_results.py deferred to wave-2; wave-1 emits cocotb-native `results.xml` only.
- CLI surface (informative): adds `--target sos-08-d` unified alongside the split `--target cocotb` / `--target sva` forms.

Status: 🟢 ratified (continuing) — impl wave-1 PCDN amendments fold the emit-layout + CLI surface + SVA port naming + vector step schema decisions into the SOS-08-D normative surface. Wave-2 candidates: parallel chart support, post_results.py emission, SVA bind file co-emission with the cocotb half (currently unified via --target sos-08-d), vector schema extension for full SOS-03 trace fidelity.

### 2026-05-23 — Impl wave-2a: post_results.py JUnit XML post-processor (Ira)

Wave-2a lands the §6.7 JUnit XML post-processor that wave-1 deferred. PCDN-D-002 is the load-bearing PCDN; the resolution at the 2026-05-23 ratification entry above named the artifact (`tests/<scope>/<dut>/post_results.py`) but the wave-1 walker scaffold deferred its emission. This entry records the wave-2a landing.

**Wave-2a implementation surface**:

- **`_emit_post_results_py` function** added to `transliterate_cocotb.py` (~150 LOC). Emits a per-chart `tests/<chart>/post_results.py` standalone Python 3.10+ script that:
    1. Reads `build/results.xml` (cocotb-classic native xunit-ish output).
    2. Scrapes `SOS-FAIL chart=<chart> region=<region> transition=<txid> state=<state> invariant=<invid> @ <time>` lines from `build/sim.log` per §6.6.
    3. Self-filters scraped lines by `chart=<this_chart>` for safety (a shared `build/` directory across charts cannot cross-contaminate).
    4. Merges each matching SOS-FAIL line into the corresponding `<failure>` element of the JUnit XML by appearance order; trailing extras append to the last failure block (rather than silently dropping).
    5. Writes `build/junit.xml` in pure JUnit XML form.

- **Standard-library only**. The post-processor imports only `re`, `sys`, `pathlib`, `xml.etree.ElementTree` — no cocotb / pytest runtime dependency at post-processing time. CI runs the script after the cocotb run finishes; the input files (`results.xml`, `sim.log`) are the cocotb run's artifacts.

- **Non-mutating with respect to cocotb's `results.xml`** per INV-S-HDL-D-3. The script reads `results.xml` but writes its output to a separate `junit.xml` path. The cocotb artifact remains the audit trail of what the runner produced; the post-processor's output is the CI-consumable artifact.

- **`render_target` wiring**: the new artifact slots into the existing emit dict between the `README.md` and the scaffold vector files. The output filename matches the §6.7 spec: `tests/<chart>/post_results.py`.

- **End-to-end test** at `tools/sos-codegen/tests/test_transliterate_cocotb.py::TestPostResultsEndToEnd` drives the emitted script against synthetic `results.xml` + `sim.log` inputs and verifies (a) chart-vocabulary message merge into JUnit `<failure>` element, (b) chart-name self-filtering at runtime, (c) non-zero exit code when `results.xml` missing, (d) clean run with zero `<failure>` elements, (e) handling of more SOS-FAIL lines than failure elements (appended to last failure).

**Invariants upheld**:

- **INV-SOS-H + INV-S-HDL-5 + INV-S-HDL-D-5** — chart vocabulary surfaces in every JUnit failure body: chart name, region, transition ID, state, invariant ID + time. CI consumers see the chart context alongside the cocotb assertion text.
- **INV-S-HDL-D-3** — the post-processor reads cocotb's `results.xml` but does not mutate it. The audit trail is preserved.
- **§5.3 Python 3.10+** — the emitted script targets the same runtime as the cocotb tests themselves.
- **§6.7 (3) chart-vocabulary merge contract** — every CI system that consumes JUnit XML now sees chart vocabulary in `<failure>` elements without per-system adapters.

**Cited PCDNs**: PCDN-SOS-08-D-002 (resolved 2026-05-23 §15 ratification; wave-2a impl now lands).

**Test count**: 13 new tests (1 modified existing emit-count assertion + 7 `TestPostResultsEmit` + 5 `TestPostResultsEndToEnd`). Suite total: 315/315 codegen + viewer tests passing.

Status: 🟢 ratified (continuing) — SOS-08-D wave-2a closes the post_results.py gate. Wave-2b is parallel-chart support in both the cocotb and SVA bind walkers (per-region SVA bind file shape; cocotb test against the chart-top wrapper).

### 2026-05-23 — Impl wave-2b: parallel-chart support in SVA bind walker (Ira)

Wave-2b lifts the wave-1 parallel-chart rejection in `transliterate_sva_bind.py`. Parallel charts now emit one SVA assertion module + one bind directive **per region**, with the bind directives targeting the SOS-08-C chart-top wrapper (`<chart>_fsm` per SOS-08-C §6.10) rather than the per-region FSM modules. This closes the SVA half of the wave-2 parallel-chart deliverable; the cocotb half lands as wave-2c.

**Wave-2b implementation surface (SVA bind side)**:

- **`_collect_parallel_regions(chart_ir)`** detects the top-level `<parallel>` element and returns the list of `(region_name, region_state_subtree)` pairs per SOS-08-C §6.1.
- **`_per_region_chart_name(chart_name, region_name)`** produces the `<chart>_region_<region>` base string passed into `_module_name` / `_sva_module_name`. The resulting per-region SVA module name is `<chart>_region_<region>_fsm_sva`, mirroring SOS-08-C wave-2's per-region FSM module naming.
- **`_emit_parallel_bind_directive`** emits a per-region bind that targets the chart-top wrapper module and wires its `current_state_<region>` output port (per SOS-08-C §6.10) to the SVA module's region-local `current_state` input.
- **`_render_parallel`** orchestrates per-region emission: for each region, splice the parent chart's datamodel onto the region's state-tree, run `_normalise_chart` through the existing single-region code path with the per-region pseudo-chart, emit per-region SVA + bind. Per-region INV-D-1 (one-hot), INV-D-2 (reset→initial-state), INV-D-3+ (per-transition) assertions all retained.
- **Filename convention**: parallel charts emit 2N files for N regions:
    - `tests/<chart>/<chart>_region_<region>_fsm_sva.sv`
    - `tests/<chart>/<chart>_region_<region>_fsm_bind.sv`
  per region.

**Wave-2b scope (what landed vs. what is deferred)**:

- **Single-clock-domain parallel charts** (no `<sos:region clock="..."/>` annotations) work end-to-end. Each per-region bind wires `.clk(clk), .rst(rst)`.
- **Multi-clock parallel charts** (where regions declare different clock domains via `<sos:region clock="..."/>`): wave-2b does NOT emit per-region `clk_<dom>` / `rst_<dom>` wiring on the bind directives. The chart-top wrapper's per-domain clocks exist (per SOS-08-C §6.10), but the bind file currently always wires `.clk(clk), .rst(rst)`. Multi-clock-domain binding is **wave-3 scope** (alongside the SOS-08-C clock-distribution contract's bind-side counterpart).
- **Chart-top `_top_sva.sv` for cross-region invariants** (e.g. CDC-handshake liveness): NOT emitted at wave-2b. Each region's SVA module is independent; cross-region properties (e.g. "if region A enters state X, region B must enter state Y within K cycles") are **wave-3 scope** when the chart-side cross-region invariant declaration form ratifies.
- **The cocotb half (parallel-chart test emit)** is **wave-2c scope**. The cocotb walker still raises `UnsupportedChartError` on parallel charts; lifting that rejection requires the per-region observable-port read pattern in the emitted `@cocotb.test()` body, plus the SOS-03 vector schema extension for per-region expected-state. Wave-2c lands both alongside the cocotb-side parallel scaffold.

**Wave-2c boundary (cocotb side)**:

- Lift parallel-chart rejection in `transliterate_cocotb.py` `_normalise_chart`.
- Build per-region state-id lists + initial-state per region, surfaced via the `CocotbChart` dataclass.
- Emit a scaffold test against the chart-top wrapper that reads `current_state_<region>` per region.
- SOS-03 schema extension: per-step expected state needs a `region` field for parallel charts.

**Invariants upheld** (wave-2b SVA bind side):

- **INV-S-HDL-D-1** (dual artifact, one IR): retained — both SVA module + bind file emit from one `render_target` invocation against one chart_ir.
- **INV-S-HDL-D-3** (vector-IR read-only at emitter): retained — `_render_parallel` does not mutate the input chart_ir; per-region pseudo-charts are freshly constructed dicts.
- **INV-S-HDL-D-4** (same SVA artifact feeds cocotb + formal flow): retained — the per-region SVA modules are bind-target-agnostic; SymbiYosys / JasperGold can consume them against the chart-top wrapper without per-tool adaptation.
- **INV-S-HDL-D-5** (chart-vocabulary failure messages): retained — each per-region SVA module's `$fatal` clauses carry the region's chart-state + invariant ID.
- **INV-S-HDL-3** (cross-domain isolation): the chart-top wrapper still uses `sos_synchronizer` / `sos_fifo_async` for cross-region signal crossings per SOS-08-C; SVA bind wave-2b does not introduce new CDC paths.

**Test count**: 10 new tests in `test_transliterate_sva_bind.py`:

- `test_parallel_charts_accepted_at_wave_2b` (replaces wave-1's `test_parallel_charts_rejected_at_v1`)
- `TestParallelChartEmit` class with 9 tests: per-region SVA module name; bind targets chart-top wrapper; per-region `current_state_<region>` wiring; single-clock-domain wiring; per-region INV-D-1/-2/-3 assertions present; wave-2b citation in header; **single-region chart unchanged** (regression guard).

**Test suite**: 325/325 passing (315 prior + 10 wave-2b SVA bind side).

**Cited PCDNs**: PCDN-D-004 wave-2 extension (per-DUT bind file co-located with the cocotb test directory — now per-region under the same `tests/<chart>/` prefix); SOS-08-C §6.10 chart-top wrapper module naming convention; SOS-08-C wave-2's per-region FSM module naming convention.

Status: 🟢 ratified (continuing) — SOS-08-D wave-2b SVA bind side closes the parallel-chart binding half. Wave-2c lifts the cocotb-side parallel-chart rejection + emits the chart-top-wrapper-targeted scaffold test. Wave-3 covers multi-clock-domain bind wiring + cross-region invariant SVA properties.

### 2026-05-23 — Impl wave-2c: cocotb parallel-chart support (Ira)

Wave-2c closes the cocotb half of the parallel-chart deliverable. The wave-1 parallel-chart rejection in `transliterate_cocotb.py._normalise_chart` is lifted; parallel charts now emit a parallel-aware test scaffold that reads each region's `current_state_<region>` output port (per SOS-08-C §6.10 chart-top wrapper convention) and asserts the region's initial-state entry after reset.

**Wave-2c implementation surface**:

- **`CocotbRegion` dataclass** added: carries `name`, `state_ids`, `initial_state` per region per SOS-08-C §6.10 chart-top wrapper convention.
- **`CocotbChart.regions: list[CocotbRegion]`** field added; populated by `_normalise_parallel_chart` for parallel charts; empty for single-region (wave-1 path unchanged).
- **`_normalise_parallel_chart` function** added: walks each region's state subtree, builds a `CocotbRegion` per `<state>` child of the top-level `<parallel>`, populates the aggregate `CocotbChart` with the union of regions' state ids and `has_parallel=True`. Region naming uses each region's `<state id>` attribute; missing region names raise `UnsupportedChartError`.
- **`_emit_helpers_py` extension**: emitted `_cocotb_helpers.py` now includes:
    - `_HAS_PARALLEL: bool` flag — `True` for parallel charts, `False` for single-region.
    - `_REGION_STATE_ENCODINGS: dict[str, dict[str, int]]` — per-region one-hot encoding map; one entry per region for parallel charts; empty for single-region.
    - `_REGION_INITIAL_STATES: dict[str, str]` — per-region initial-state map.
    - `assert_region_state(dut, region_name, expected_state_id, failure_ctx)` helper — looks up the per-region encoding, reads `dut.current_state_<region>` via `getattr`, asserts equality with chart-vocabulary failure message per INV-S-HDL-D-5.
- **`_emit_test_py` dispatch**: branches on `chart.has_parallel`; parallel charts dispatch to `_emit_parallel_test_function`, single-region charts continue through the wave-1 `_emit_one_test_function` path unchanged.
- **`_emit_parallel_test_function`**: emits one `@cocotb.test()` per vector for parallel charts. Test body applies reset, then asserts each region's initial-state entry via `assert_region_state(dut, <region>, <region_initial>, format_failure(vector))` and records a per-region SOS-08-G annotation overlay entry (with `region=<region>` per §5.2).
- **Test imports update**: emitted `test_<chart>_fsm.py` imports `assert_region_state` alongside `assert_state` from `_cocotb_helpers` so single-region tests retain the original helper and parallel-chart tests get the per-region variant.

**Wave-2c scope (what landed vs. what is deferred)**:

- **Reset + per-region initial-state-entry assertion** for parallel charts: ✅ landed. Every region's declared initial state is verified after reset deassertion via `assert_region_state`.
- **Per-region SOS-08-G annotation records** with `region=<region>` field set per §5.2: ✅ landed. The review surface sees one record per region per post-reset state-entry.
- **Per-region step-driven vector assertions** (where each step names the region whose `expected_state` is being asserted): **wave-3 scope**. Requires SOS-03 schema extension: `steps[].expected_states: {region: state}` shape (replacing the wave-1 single-region `steps[].expected_state` field for parallel charts). Wave-2c keeps the scaffold tight — reset + per-region initial-state-entry only.
- **Cross-region transition driving** (where one region's state change triggers another region's transition via shared datamodel signal): **wave-3 scope** alongside the SOS-08-C cross-region datamodel-signal-tracking pass.
- **DUT module name** in the parallel-chart test is the chart-top wrapper (`<chart>_fsm` per SOS-08-C §6.10), NOT a per-region FSM module. This matches the wave-2b SVA bind side decision (the bind directives target the chart-top wrapper); both halves of wave-2 thus address the same DUT instantiation surface in the customer's testbench.

**Invariants upheld**:

- **INV-S-HDL-D-3** (vector-IR read-only at emitter): retained — `_normalise_parallel_chart` does not mutate the input chart_ir; region state lists are freshly constructed.
- **INV-S-HDL-D-5** (chart-vocabulary failure messages): retained — `assert_region_state` emits failure messages naming the region, the expected state, the observed one-hot pattern, and the chart name. Per-region annotation records carry the region in their `region` field per SOS-08-G §5.2.
- **INV-S-HDL-D-6** (per-vector test isolation by default): retained — parallel charts emit one `@cocotb.test()` per vector (same as single-region); chart-region-grouping remains opt-in for wave-3.
- **INV-S-HDL-G-5** (generation co-located with `@cocotb.test()` body): retained — the per-region annotation writer is instantiated inside the test body, not as a post-process step.

**Test count**: 11 new tests:

- `test_parallel_charts_accepted_at_wave_2c` (replaces wave-1's `test_parallel_charts_rejected_at_v1`) — confirms the emit set is unchanged, both regions' `current_state_<region>` ports appear in the test body, helpers carry the per-region encoding maps, `_HAS_PARALLEL=True`.
- `TestParallelChartEmit` class with 10 tests: per-region encodings present; per-region initial states present; `assert_region_state` helper emitted; helpers + test module both parse; test imports `assert_region_state`; per-region initial-state assertions emit for each region; per-region annotation records with `region=<region>`; DUT module is chart-top wrapper; **single-region chart unchanged** (regression guard — `_HAS_PARALLEL=False`, existing test path unchanged).

**Test suite**: 336/336 passing (325 prior + 11 wave-2c).

**Cited PCDNs**: SOS-08-C §6.10 chart-top wrapper module naming + per-region `current_state_<region>` output port convention; SOS-08-G §5.2 annotation record `region` field; INV-S-HDL-D-3/-5/-6; INV-S-HDL-G-5.

**Wave-3 boundary** (consolidated across wave-2b + wave-2c):

- Per-region step-driven vectors via SOS-03 schema extension (`steps[].expected_states: {region: state}`).
- Multi-clock-domain parallel-chart bind wiring (per-domain `clk_<dom>` / `rst_<dom>` ports on chart-top wrapper).
- Cross-region invariant SVA properties (`<chart>_top_sva.sv` module with cross-region `assert property` clauses).
- Cross-region transition driving via shared datamodel signals (SOS-08-C cross-region tracking pass).

Status: 🟢 ratified (continuing) — SOS-08-D wave-2 parallel-chart support is now complete on both the SVA bind side (wave-2b) and the cocotb side (wave-2c). Wave-3 lifts the remaining scope to per-region step-driven vectors + multi-clock-domain bind wiring + cross-region invariant SVA properties.

### 2026-05-24 — Impl wave-3: per-region step-driven vectors (Ira)

Wave-2c's parallel-chart cocotb emission stopped at reset + per-region initial-state assertion. Wave-3 lands the load-bearing extension: the parallel-chart test body now walks `vector["steps"]` with per-region targeted `expected_states` assertions, driven by the SOS-03 §15 2026-05-24 schema extension co-landing with this commit.

**Wave-3 implementation surface**:

- **`_emit_parallel_test_function` extension**: the wave-2c reset + initial-state-per-region block is unchanged. Wave-3 adds, after that block:
  - A `for step_index, step in enumerate(vector.get("steps", []) or [])` loop iterating per-step records.
  - Per-step `inputs` driver: flat `{port: value}` map, identical convention to the single-region wave-1 emission.
  - Per-step `cycles_advance` (default 1): the test awaits `RisingEdge(dut.clk)` that many times before the step's assertions.
  - Per-step `expected_states: {region: state}`: for each `(region, state)` entry, emit `assert_region_state(dut, region, state, format_failure(vector, step))` plus a SOS-08-G annotation via `writer.record_transition(... region=region_name, vector_index=step_index, ...)`.
  - End-of-vector per-region terminal assertion loop: reads `vector["expected_terminal_states"]` (dict) with per-region fallback to each region's initial state via a `_region_initial` literal-dict embedded into the test body. One `assert_region_state` + annotation per region.
- **Region-initial map** (`_region_initial = {region: initial_state, ...}`): emitted once per parallel-test function so the terminal loop can resolve fallbacks without consulting the chart IR at runtime. Pure-Python literal; no walker callback.
- **Backwards compatibility**: a vector lacking `steps` and `expected_terminal_states` produces a test that:
  - Skips the step loop (empty `vector["steps"]` → loop body never runs).
  - In the terminal loop, every region asserts its declared initial state via the `_region_initial` fallback.
  - Net behaviour: reset + initial-state-per-region — identical to wave-2c minimal vector emission.

**Co-landing**: SOS-03-CONCEPTS.md §15 2026-05-24 entry extends the per-step record schema with `expected_states` (plural dict for parallel charts), `cycles_advance`, and top-level `expected_terminal_states`. The extension is additive — single-region vectors using `expected_state` (singular) continue unchanged.

**Wave-3 scope explicitly excludes** (carry-forward to future waves):

- **Multi-clock-domain bind wiring**: parallel charts on `<region clock="...">` distinct domains still emit the wave-2b per-region SVA bind targeting the chart-top wrapper, but the bind file uses a single `clk` / `rst` reference. Wave-4 lifts to per-domain `clk_<dom>` / `rst_<dom>` wiring to match the SOS-08-C wave-3 chart-top wrapper port shape.
- **Cross-region invariant SVA properties**: a `<chart>_top_sva.sv` module with cross-region `assert property` clauses (e.g. "left.L_TICKED reachable iff right.R_OBSERVED_TICK has been entered at least once") is a future amendment. Wave-3 emits per-region SVA only.
- **Cross-region transition driving via shared datamodel signals**: when two regions read/write the same chart datamodel signal, SOS-08-C's cross-region tracking pass synthesises a `sos_synchronizer` between them (per PCDN-SOS-08-C-002). The cocotb walker accepts these scenarios but does not yet drive shared-datamodel-mediated cross-region transitions via the step vector schema. Future amendment.

**Invariants upheld**:

- **INV-S-HDL-D-3** (vector-IR read-only at emitter boundary): the wave-3 walker consumes `vector["steps"]` verbatim. No mutation; the schema extension is canonical, not an emitter-local transformation.
- **INV-S-HDL-D-5** (chart-vocabulary failure messages): per-region `assert_region_state` carries `format_failure(vector, step)` so failures cite the chart-side vector + step context, NOT raw RTL signal traces. Same INV-SOS-H integration as wave-2c.
- **INV-S-HDL-D-6** (per-vector test attribution): one `@cocotb.test()` per vector preserved — wave-3 extends the test body, NOT the test-to-vector mapping. Per-region failures within a single test still attribute to one vector_id; the JUnit-XML rollup remains per-vector.
- **PCDN-SOS-08-D-003** (per-vector test isolation): unchanged. `--group-by-region` remains opt-in and is unaffected by wave-3 (the step walker is per-test).
- **INV-S-HDL-G-2** (annotation-per-transition): wave-3 emits one `writer.record_transition` per (step, region) pair in the step loop, plus one per region in the terminal loop. Annotation overlay is dense (matches the SOS-08-G review-surface contract).

**Backwards compatibility tests**: `test_walker_remains_backward_compatible` verifies that a wave-2c-style minimal vector (no `steps`, no `expected_terminal_states`) produces a test body that:
- Still parses cleanly (`ast.parse(test)` passes).
- Still emits the wave-2c initial-state-per-region assertions.
- Step loop is a no-op (`vector.get("steps", [])` returns `[]`).
- Terminal loop asserts each region's initial state via the embedded `_region_initial` map.

**Test count**: net +9 — `TestWave3PerRegionStepDrivenVectors` (9 tests): step walker loop emitted; step walker handles `inputs`; step walker honours `cycles_advance`; per-region `expected_states` assertion loop; per-step annotation per region; terminal-states dict reading; per-region terminal assertion loop; backwards compatibility (wave-2c minimal vector); `format_failure(vector, step)` per-step context.

**Test suite**: 423/423 passing (414 baseline + 9 net wave-3).

**Cited PCDNs / amendments**: SOS-03 §15 2026-05-24 (schema extension co-landing); PCDN-SOS-08-D-003 (per-vector test isolation — unchanged); INV-S-HDL-D-3 (vector-IR read-only — preserved); SOS-08-C §6.10 chart-top wrapper convention (per-region `current_state_<region>` port).

Status: 🟢 **wave-3 complete** for the per-region step-driven vector scope. Multi-clock-domain bind wiring + cross-region invariant SVA properties + shared-datamodel cross-region transitions remain wave-4+ work.

### 2026-05-24 — Impl wave-4: multi-clock-domain bind + cross-region invariants (Ira)

Wave-4 closes two of the three wave-3+ deferred items:

(a) **Multi-clock-domain bind wiring**: parallel charts whose regions declare `clock="<domain>"` attributes now emit per-region bind directives that wire to the chart-top wrapper's `clk_<dom>` / `rst_<dom>` ports per SOS-08-C wave-3 clock-distribution contract. Wave-2b's single-clock-domain assumption (`.clk(clk), .rst(rst)`) is preserved as the fallback when a region carries no `clock` annotation.

(b) **Cross-region invariant SVA properties**: ratifies the `<sos:cross_invariant>` declaration form + emits `<chart>_top_sva.sv` + `<chart>_top_bind.sv` when the chart carries one or more cross-invariants.

The third deferred item — shared-datamodel cross-region transition driving — remains wave-5+ work.

**Wave-4 declaration form (frozen 2026-05-24 §15)**:

```xml
<sos:cross_invariant id="INV-S-CHART-N"
                     antecedent="region.<name> == <state>"
                     consequent="region.<other> == <state>"
                     within="K" />
```

Semantics: on every clock edge where `antecedent` is true, the SVA property requires `consequent` to hold within `[1:K]` cycles. The walker lowers each declaration into a `property` + `assert property` clause in `<chart>_top_sva.sv` whose failure message renders in chart vocabulary per INV-S-HDL-D-5.

Frozen-enumeration registration policy for the declaration field set: **Standards Action** (modifying the field set is a cross-sub-phase contract change; requires §15 amendment + cross-walker review).

**Grammar restriction at v1**: antecedent and consequent restrict to `region.<name> == <state>` (single-region single-state comparison). Compound expressions (`region.A == X && region.B == Y`), negation (`!=`), and chained implications are wave-4-future. Chart authors who need arbitrary SVA can wait for a future `raw_property` escape hatch.

**Wave-4 implementation surface**:

- `_region_clock_domain(region_state)` new helper: extracts the `clock` attribute from a region's `<state>` element; returns `None` for regions without an annotation.
- `_emit_parallel_bind_directive` extended: accepts `clock_domain: str | None`; emits `.clk(clk_<dom>), .rst(rst_<dom>)` when non-None via `hdl_common.clk_port_name` / `rst_port_name`.
- `_collect_cross_invariants(chart_ir)` reads `<sos:cross_invariant>` entries; rejects malformed entries with chart-vocabulary errors.
- `_parse_region_state_expr` regex-parses `region.<name> == <state>`.
- `_CrossInvariant` dataclass — normalised representation.
- `_emit_cross_region_sva_module` emits `<chart>_top_sva.sv` with one `property` + `assert property` per invariant; `disable iff (rst)`; chart-vocabulary `$fatal` messages.
- `_emit_cross_region_bind_directive` emits `<chart>_top_bind.sv` targeting the chart-top wrapper.
- `_render_parallel` extended: passes per-region `clock_domain`; co-emits `_top_sva.sv` + `_top_bind.sv` when cross-invariants are present.

**Cross-region SVA sampling clock policy**: v1 uses the chart-top reference clock (`clk`) for cross-region property sampling regardless of per-region clock domains. Per INV-S-HDL-3 + SOS-08-C wave-3, cross-domain region observables are synchronised through `sos_synchronizer` before the chart-top wrapper exposes them — the sampled view on `clk` is well-defined.

**State-constant width**: v1 emits `localparam logic [N_STATES_<R>-1:0] ST_<STATE>` declarations inside `_top_sva`. The bit-position derivation is currently a placeholder returning 0 — the actual one-hot bit position is owned by SOS-08-C's per-region FSM emitter, and threading the encoding map through the cross-region SVA module is **wave-4-future**. The wave-4 v1 SVA module compiles + carries property shape + chart-vocabulary failure messages; bench validation of the actual state-comparison match against the per-region encoding is deferred.

**SV-testbench mirror**: SOS-08-E's `_render_sva_bind` call automatically picks up the wave-4 emit (multi-clock bind shape + `_top_sva.sv` + `_top_bind.sv`). No code change in the SV-testbench walker; the parallel-chart emit count grows from `10 + 2N` to `10 + 2N + 2` when the chart carries cross-invariants (still byte-identical with the SOS-08-D emit at the SVA artifact level).

**Wave-4-future boundary** (explicit out-of-scope):

- State-encoding pass-through into `_top_sva.sv` (currently bit-0 placeholder).
- Compound antecedent/consequent expressions (AND/OR/NOT/chained implications).
- `raw_property` escape hatch (chart authors writing arbitrary SVA).
- Per-property multi-clock cross-region sampling.
- Shared-datamodel cross-region transition driving (the third wave-3+ deferred item).

**Invariants upheld**:

- INV-S-HDL-D-1/-D-2/-D-3 retained unchanged.
- **INV-S-HDL-D-4 extended**: new `_top_sva.sv` is bind-attached so commercial-sim assertion engines + formal tools both consume it via the bind directive.
- **INV-S-HDL-D-5 preserved + extended**: cross-region `$fatal` messages name chart + invariant id + both regions + both states + `within`.
- INV-S-HDL-3 preserved — cross-region SVA reads already-synced observables.

**Test count**: 28 new tests across `TestWave4MultiClockBindWiring` (5) + `TestWave4CrossRegionInvariants` (14) + `TestWave4CrossInvariantValidation` (6) + `TestWave4SingleRegionUnchanged` (1). Wave-4 emit reaches the SOS-08-E SV-testbench walker through the existing mirror loop (verified via direct invocation).

**Test suite**: 555/555 passing (527 prior + 28 wave-4).

**Cited PCDNs / amendments**: §15 wave-4 (this entry) ratifies the `<sos:cross_invariant>` declaration form; SOS-08-C wave-3 clock-distribution contract (consumed for per-domain bind wiring); INV-S-HDL-D-4/-5 extended; PCDN-SOS-08-C-wave3-clk-naming-passthrough (consumed via `hdl_common.clk_port_name` / `rst_port_name`).

Status: 🟢 **wave-4 complete** for multi-clock-domain bind wiring + cross-region invariant declarations. Wave-4-future tracks state-encoding pass-through, compound cross-invariant expressions, `raw_property` escape hatch, multi-clock cross-region sampling, and shared-datamodel cross-region transition driving.

### 2026-05-24 — Impl wave-4-future: state-encoding pass-through (Ira)

Lands the first wave-4-future carry-forward: **state-encoding pass-through** from the per-region FSM emit (SOS-08-C) into `<chart>_top_sva.sv` (this phase). The wave-4 v1 emit declared each state constant via the placeholder `(N'(1) << 0)` — every state, every region collapsed to bit 0. The cross-region property's RHS `current_state_<region> == ST_<state>` therefore only fired when the antecedent region was in its first-document-order state, masking real cross-region violations behind a silent false-match. This entry closes that v1 boundary.

**Implementation surface** (one walker module, no external callers touched):

- `_build_region_state_indices(regions) → {region: {state_id: bit_idx}}` — new helper. Mirrors SOS-08-C's `_emit_state_constants` document-order traversal by walking each region subtree with `_walk_states_in_order` and assigning index 0..N-1 per state in first-encounter order. The two walkers share the same traversal helper so by-construction the bit indices align.
- `_validate_cross_invariant_state_refs(invariants, region_state_indices)` — new validation pass. Raises `UnsupportedChartError` with chart-vocabulary error (citing the cross-invariant id, the offending region/state name, and the role — antecedent vs consequent — plus the list of states the region actually declares) when an invariant references an unknown region or unknown state. Replaces the wave-4 v1 silent fall-through to bit 0.
- `_state_index_for(region, state, region_state_indices) → int` — new lookup helper. Returns the document-order bit position when the encoding map is provided; falls back to the wave-4 v1 placeholder behaviour (bit 0) when the map is `None` — preserves the legacy emit shape so internal `_emit_cross_invariant_state_constants` callers that have not yet been migrated remain valid.
- `_emit_cross_invariant_state_constants(invariants, region_state_indices=None)` — extended. When the map is provided, emits a per-constant comment naming the bit position (`bit <N> per SOS-08-C document-order encoding`) and the actual shifted value; when omitted, emits a `WAVE-4-V1 PLACEHOLDER — bit position is 0` comment and the legacy `(N'(1) << 0)` shift. The conditional preserves wave-4 v1 emit identity for any legacy direct caller while letting the wave-4-future render path produce by-construction-correct constants.
- `_emit_cross_region_sva_module(..., region_state_indices=None)` — extended. Threads the map through to `_emit_cross_invariant_state_constants`.
- `render_target` parallel-chart path — wires the new pieces together: builds `region_state_indices` via `_build_region_state_indices(regions)`, calls `_validate_cross_invariant_state_refs(cross_invariants, region_state_indices)` before emit (so a typo surfaces as a chart-author error, not a silently-mismatched bit position), passes the map into `_emit_cross_region_sva_module`. The wave-4 v1 `_state_index_placeholder` function is gone — superseded by `_state_index_for`.

**Sample emit change** (reference chart with regions `left` containing `[L1, L2]` and `right` containing `[R1, R2]`, cross-invariant referencing `region.left == L2 |-> region.right == R2`):

Before (wave-4 v1):
```
// State constant `ST_L2` for region `left` — matches SOS-08-C one-hot encoding.
`ifndef ST_L2_DEFINED
`define ST_L2_DEFINED
localparam logic [N_STATES_LEFT-1:0] ST_L2 = {N_STATES_LEFT{1'b0}} | (N_STATES_LEFT'(1) << 0);
`endif
```

After (wave-4-future):
```
// State constant `ST_L2` for region `left` — matches SOS-08-C one-hot encoding (bit 1 per SOS-08-C document-order encoding).
`ifndef ST_L2_DEFINED
`define ST_L2_DEFINED
localparam logic [N_STATES_LEFT-1:0] ST_L2 = {N_STATES_LEFT{1'b0}} | (N_STATES_LEFT'(1) << 1);
`endif
```

The shift literal advances from `0` to the state's actual document-order index. The comment explicitly names the bit position so a reviewer can audit the SVA module against SOS-08-C's per-region FSM emit by reading the comment alone — no cross-file inspection needed.

**Cross-encoding equivalence proof**: the test `TestWave4FutureEncodingPassthrough.test_state_constants_match_sos_08c_emit_exactly` invokes `transliterate_hdl_sv.one_hot_value(1, 2)` (the SOS-08-C helper) and verifies the wave-4-future SVA constant for an index-1 state in a 2-state region produces the same numeric value (`2'b10`). The two walkers' encoders converge by-construction through the shared `_walk_states_in_order` traversal — the test pins this for any future SOS-08-C refactor.

**Chart-author validation** (closes a wave-4 v1 cliff edge):

Wave-4 v1 silently accepted typos in cross-invariant region/state names — the chart compiled, the SVA module compiled, and the assertion appeared to be running, but the RHS state constant (always bit 0) made the property fire only against the region's first state regardless of what the chart author intended. Wave-4-future converts this silent failure into an actionable chart-vocabulary error:

```python
UnsupportedChartError: SOS-08-D wave-4-future: cross-invariant 'INV-S-CHART-BAD's
antecedent references state 'L99' in region 'left' which the region does not declare.
Known states in region 'left': ['L1', 'L2'].
```

The error message names: (a) the invariant id (the chart-author handle), (b) the role (antecedent vs consequent — disambiguates which side of the `|->` to fix), (c) the bad reference, (d) the known-good state list (so the chart author can correct without re-reading their chart). Concretizes INV-S-HDL-D-5 (chart-vocabulary failure messages) at the validation layer, not just the runtime assertion layer.

**Invariants upheld** (no §15 changes to invariants themselves; this entry concretizes the wave-4 v1 placeholder boundary):

- **INV-S-HDL-D-2** (one-hot, reset-initial state encoding) — wave-4-future emit MATCHES SOS-08-C's per-region FSM module emit by-construction via the shared traversal helper. The wave-4 v1 emit DID NOT match — the placeholder produced a constant that was structurally one-hot but bit-positionally wrong for any non-first state.
- **INV-S-HDL-D-3** (per-region FSM as the DUT for the per-region bind) — unchanged; the SVA module references region observables via the chart-top wrapper's port wiring, which already exposes the per-region one-hot encoding correctly.
- **INV-S-HDL-D-5** (chart-vocabulary failure messages) — extended in spirit to the validation layer: chart authors get actionable typo errors with chart vocabulary, not silently-broken assertions.
- **PCDN-SOS-08-C-state-encoding-mirror** (cross-walker encoding parity) — wave-4-future closes this open question by sharing the `_walk_states_in_order` traversal helper between SOS-08-C and SOS-08-D and pinning the equivalence via `test_state_constants_match_sos_08c_emit_exactly`.

**Backwards compatibility**: `_emit_cross_invariant_state_constants` and `_state_index_for` accept `region_state_indices=None` and produce the wave-4 v1 emit verbatim. Any external test or downstream tool that called the wave-4 v1 helper directly continues to receive the placeholder emit. The render path is the only caller that has been migrated; the helper-direct invocations stay legacy-correct. `TestWave4FutureBackwardsCompatibleEmit` (2 tests) pins both halves of this contract — the `None`-map call produces `WAVE-4-V1 PLACEHOLDER` comments + bit-0 shifts; the map-provided call produces real-encoding comments + correct shifts.

**Wave-4-future remaining**:

- **Compound cross-invariant expressions** (Boolean conjunctions / disjunctions across `region.X == STATE_A` terms). Currently the antecedent / consequent grammar accepts exactly one `region.<name> == <state>` clause; chart authors needing AND/OR semantics author multiple invariants. Lift to a small expression DSL when bench evidence shows a real need.
- **Multi-clock cross-region sampling** (sample the antecedent on its own clock and consequent on its own clock, with a synchronisation handoff between them). Currently wave-4 emit samples both observables on the chart-top reference clock per INV-S-HDL-3 (regions are synced through `sos_synchronizer` before the chart-top exposes them); cross-clock sampling primitives are a future amendment if a chart needs truly clock-asymmetric assertions.
- **`raw_property` escape hatch** for invariants too expressive for the wave-4 grammar — accept a literal SVA `property` body and bypass the structured emit path. Gated on chart-author demand.
- **Shared-datamodel cross-region transition driving** — extending cross_invariant antecedent / consequent grammar to reference datamodel signals (`data.<X> == <K>`) in addition to region states. Useful for invariants like "when the shared counter reaches K, region.Y must be in STATE_Z within W cycles".

**Test count**: net +17 across four new classes in `tools/sos-codegen/tests/test_transliterate_sva_bind.py`:

- `TestWave4FutureEncodingPassthrough` (6): bit position resolves correctly for L1 (bit 0), L2 (bit 1), R2 (bit 1); per-constant comment names the bit position; placeholder comment is gone; distinct states resolve to distinct bits; SVA encoding matches `transliterate_hdl_sv.one_hot_value` exactly.
- `TestWave4FutureValidation` (5): rejects unknown region; rejects unknown state in known region; error cites invariant id; error cites role; error lists known states.
- `TestWave4FutureHelperFunctions` (4): `_build_region_state_indices` document-order map; `_state_index_for` fallback for `None` map; `_state_index_for` returns mapped bit; unknown lookups return 0 (helper stays total — validation is the gate).
- `TestWave4FutureBackwardsCompatibleEmit` (2): legacy `None`-map call produces wave-4 v1 emit; map-provided call produces real-encoding emit.

**Test suite**: 572/572 passing (555 prior + 17 new wave-4-future). The wave-4 v1 cross-region test suite (`TestWave4CrossRegionInvariants`, `TestWave4CrossInvariantValidation`) is unchanged — wave-4 v1 callers continue to receive the v1 emit shape via the `None` fallback.

**Cited invariants / PCDNs**: INV-S-HDL-D-2 (state encoding parity — now achieved by construction); INV-S-HDL-D-5 (chart vocabulary — extended to validation diagnostics); PCDN-SOS-08-C-state-encoding-mirror (resolved by `_walk_states_in_order` sharing); SOS-08-C `_one_hot_value` (consumed indirectly through the shared traversal helper for the equivalence test).

Status: 🟢 **wave-4-future complete** for state-encoding pass-through + chart-author validation. Compound antecedent/consequent expressions, multi-clock cross-region sampling, `raw_property` escape hatch, and shared-datamodel cross-region transition driving remain on the wave-4-future track.
