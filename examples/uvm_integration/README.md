# SOS-08-F wave-2 acceptance gate (e) — end-to-end UVM 1.2 worked example

This directory is the worked example referenced by **SOS-08-F-CONCEPTS.md
§12 acceptance gate (e)** and the wave-2 carry-forward list in the
2026-05-24 §15 amendment.

It demonstrates the SOS-08-F **§6.5 five-step customer-integration
contract** running end-to-end against a synthetic DUT:

| Step | Spec ref | Location |
|------|----------|----------|
| 1. Package import | §6.5 step 1 | `import sos_uvm_seq_pkg::*;` in `tb/sos_kernel_agent.sv` (and env / test). |
| 2. Sequencer typedef | §6.5 step 2 | `tb/sos_kernel_agent.sv` — `typedef uvm_sequencer #(sos_seq_item) sos_kernel_sequencer;`. |
| 3. Driver implementation | §6.5 step 3 | `sos_kernel_driver` in `tb/sos_kernel_agent.sv` — translates `sos_seq_item` to DUT-pin activity on `sos_kernel_if`. |
| 4. Sequence start | §6.5 step 4 | `tb/sos_kernel_test.sv` `run_phase` — instantiates `sos_sem_sequence`, wires `vector_path`, calls `seq.start(env.agent.sequencer)`. |
| 5. Failure handling | §6.5 step 5 + §6.6 | `tb/sos_kernel_scoreboard.sv` — emits chart-vocabulary `uvm_error` strings in the canonical `[SOS-SEQ] state=... transition=... invariant=... family=... event=...` format. |

## Directory layout

```
examples/uvm_integration/
├── README.md
├── Makefile                              — build + run rules (Questa/VCS/Xcelium/Riviera)
├── rtl/
│   └── sos_kernel_dut.sv                 — synthetic kernel-style DUT
├── tb/
│   ├── sos_uvm_seq_pkg.sv                — sample copy of the SOS-emitted package
│   ├── sos_uvm_seq_pkg.svh               — sample copy of the SOS-emitted header
│   ├── sos_kernel_if.sv                  — interface (DUT pin bundle)
│   ├── sos_kernel_agent.sv               — customer sequencer + driver + monitor
│   ├── sos_kernel_scoreboard.sv          — customer scoreboard (chart-vocab errors)
│   ├── sos_kernel_env.sv                 — customer env
│   ├── sos_kernel_test.sv                — customer test class (wires vector path)
│   └── sos_kernel_tb_top.sv              — top-level tb module
└── vectors/
    ├── sem_chart_bound.jsonl             — golden bounded-reachability vector
    └── sem_chart_violation.jsonl         — mutated vector for acceptance gate (f)
```

The `tb/sos_uvm_seq_pkg.sv` + `tb/sos_uvm_seq_pkg.svh` files are
**sample copies** of the walker's output; the `make regen` rule
re-emits them from `rtos_kernel.scxml` so the worked example always
tracks the current walker output.

## Running

The Makefile is a recipe template — most enterprise UVM shops already
have site-specific simulator wrappers; the rules show the canonical
per-vendor command-line shape.

```
# Default simulator is Questa. Override with SIM=vcs / xcelium / riviera.
make regen
make SIM=questa sim-golden      # expect 0 UVM_ERROR
make SIM=questa sim-violation   # expect ≥1 UVM_ERROR with chart vocabulary
```

**Acceptance gate (e)** is satisfied by the artifact set being able to
elaborate and run on any UVM 1.2-capable simulator. No simulator is
bundled with the example; vendor binaries are customer-owned per
**INV-S-HDL-F-2**.

## Acceptance gate (f) — injected violation

`vectors/sem_chart_violation.jsonl` mutates the golden vector: it
attempts `sem.take(0)` twice without an intervening `sem.give(0)`. The
DUT's tiny kernel state detects the double-take and returns
`resp_ok = 0`; the scoreboard pairs the failing response with the
driver's chart-vocabulary metadata and emits:

```
UVM_ERROR ... [SOS-SEQ] state=task_c.illegal_double_take transition=99 invariant=42 family=SOS_FAMILY_SEM event=2: kernel rejected syscall (resp_ok=0)
```

The substring `state=task_c.illegal_double_take transition=99 invariant=42`
is the load-bearing proof of **INV-S-HDL-F-3** (chart-vocabulary
traceability survives the UVM boundary): the chart vocabulary the
sequence carried in `sos_seq_item` fields is rendered verbatim in the
customer's `uvm_error` message — without any SOS code crossing
INV-S-HDL-F-1's exclusion boundary.

## Invariants exercised by this worked example

| Invariant | Spec ref | How this example satisfies it |
|-----------|----------|-------------------------------|
| INV-S-HDL-F-1 | sequences only | Only `tb/sos_uvm_seq_pkg.sv` contains `uvm_sequence` subclasses; customer scaffolding (`env / agent / sbd / test`) lives outside the SOS-emitted package. |
| INV-S-HDL-F-2 | customer owns env/scoreboard/driver/factory | Every customer-side file (DUT, interface, agent, env, scoreboard, test, tb top) is under `examples/uvm_integration/` — separate from `tools/sos-codegen/` emission output. |
| INV-S-HDL-F-3 | chart vocab survives the boundary | Driver forwards `chart_state` / `transition_id` / `invariant_id` to the scoreboard via a parallel analysis port; scoreboard's `uvm_error` strings render these fields verbatim per §6.6. |
| INV-S-HDL-F-4 | no SVA in this sub-phase | `grep -r "assert property\|bind " examples/uvm_integration/` returns no hits. SVA is sibling SOS-08-D / SOS-08-E. |
| INV-S-HDL-F-5 | UVM 1.2 grammar + UVM 2.0 forward compat | The example uses only UVM 1.2 grammar (`uvm_sequence`, `uvm_sequence_item`, `uvm_test`, `uvm_env`, `uvm_agent`, `uvm_driver`, `uvm_monitor`, `uvm_scoreboard`, `uvm_subscriber`, `uvm_config_db`, `uvm_info`/`uvm_error`/`uvm_warning`/`uvm_fatal`) — runs unchanged on UVM 2.0 per the spec. |

## Spec citations

* `docs/concepts/SOS-08-F-CONCEPTS.md` §5.1 (scope discipline — sequences only).
* `docs/concepts/SOS-08-F-CONCEPTS.md` §6.1 (chart event families — sem.* used here).
* `docs/concepts/SOS-08-F-CONCEPTS.md` §6.4 (vector-IR row schema).
* `docs/concepts/SOS-08-F-CONCEPTS.md` §6.5 (five-step customer integration contract).
* `docs/concepts/SOS-08-F-CONCEPTS.md` §6.6 (chart-vocabulary failure-message format).
* `docs/concepts/SOS-08-F-CONCEPTS.md` §7 INV-S-HDL-F-1..5 (per-sub-phase invariants).
* `docs/concepts/SOS-08-F-CONCEPTS.md` §12 (e),(f) (acceptance gates this example closes).

## Status

* **(e) end-to-end worked example**: ✅ landed (this directory).
* **(f) injected-violation chart-vocabulary check**: ✅ landed (`vectors/sem_chart_violation.jsonl`).
* **UVM 2.0 cross-runtime smoke**: ✅ landed as a **build-only CI smoke** (see below). Live UVM-2.0 simulator runs remain customer-owned per INV-S-HDL-F-2.
* **pyuvm overlay (SOS-08-F-A)**: ⏸ deferred, gated on customer demand.

## UVM 2.0 cross-runtime smoke — declared scope

The 2026-05-24 wave-2 carry-forward (`SOS08F2c`) adds a CI smoke verifying
that the SOS-08-F **emitted package surface** (`tb/sos_uvm_seq_pkg.sv`)
and the customer scaffolding under `tb/` follow only the UVM-1.2-grammar
subset that is forward-compatible with **IEEE 1800.2-2017 (UVM 2.0)** per
**INV-S-HDL-F-5**. The CI smoke validates the build and tooling
surface, NOT a live simulator run.

**What the CI smoke validates** (`.github/workflows/sos-uvm-smoke.yml`):

1. SystemVerilog files under `examples/uvm_integration/` parse cleanly
   under Verilator's `--lint-only` pass (a UVM-version-agnostic parse
   check — Verilator does not run UVM, but it does parse the grammar).
2. The Python tooling test suite under `tools/sos-codegen/` passes,
   including the new `test_sos_08_f_wave_2_carry_forward.py` checks that
   pin the `UVM_VERSION` Makefile variable, the `sim-golden-uvm2` /
   `sim-violation-uvm2` targets, and the README's declared-scope text.
3. `make -n regen` is a syntactic dry-run of the regenerator — proves
   the rule wiring resolves under a fresh checkout.

**What the CI smoke does NOT validate** (gated on simulator availability —
customer-owned per **INV-S-HDL-F-2**):

* No vendor simulator (Questa / VCS / Xcelium / Riviera) is invoked in CI.
* No actual UVM-1.2 or UVM-2.0 runtime executes the sequence library —
  Verilator's UVM support is not sufficient to host the full
  `uvm_pkg` runtime, and the licensed simulators are not available in
  GitHub Actions.
* The `[SOS-SEQ] state=... transition=... invariant=... family=... event=...`
  scoreboard line (defined in `tb/sos_kernel_scoreboard.sv`) is verified
  to be **textually identical** across the UVM-1.2 and UVM-2.0
  build flows (same scoreboard source, same chart-vocabulary fields) —
  the chart-vocabulary preservation per **INV-S-HDL-F-3** is therefore
  the same string whether the customer runs UVM 1.2 or UVM 2.0.

**How a customer extends the smoke to a real run**: invoke
`make SIM=<vendor> sim-golden-uvm2` against a UVM-2.0-capable vendor
install with `UVM_HOME` pointing at the 2.0 library tree. The Makefile
recipes pass `-L uvm-2.0` / `-ntb_opts uvm-2.0` / `-uvmhome CDNS-2.0`
per simulator vendor convention; no source-code change is required.

### Canonical `[SOS-SEQ]` scoreboard line

The chart-vocabulary failure-message format per §6.6 is rendered by
`tb/sos_kernel_scoreboard.sv` as:

```
[SOS-SEQ] state=<chart_state> transition=<transition_id> invariant=<invariant_id> family=<sos_event_family_e_name> event=<event_id>: <message>
```

This string shape is **identical under UVM 1.2 and UVM 2.0** because
all `uvm_error` / `uvm_info` / `uvm_warning` reporting macros and
`$sformatf` are unchanged between the two versions (per the
INV-S-HDL-F-5 §15 amendment allow-list).
