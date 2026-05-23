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
