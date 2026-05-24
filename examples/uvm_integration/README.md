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
* **UVM 2.0 cross-runtime smoke**: ⏸ separate CI job carry-forward.
* **pyuvm overlay (SOS-08-F-A)**: ⏸ deferred, gated on customer demand.
