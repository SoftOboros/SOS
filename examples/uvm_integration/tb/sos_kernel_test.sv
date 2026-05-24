// SPDX-License-Identifier: MIT
//
// SOS-08-F wave-2 acceptance gate (e) — customer-side test class
//
// Implements §6.5 step 4 — the customer's test class instantiates the
// SOS-emitted `sos_sem_sequence`, assigns the chart's bounded-
// reachability JSONL path to `vector_path`, and starts the sequence
// against the agent's sequencer.
//
// The chart-vector path is plusarg-driven so the same testbench binary
// runs the golden vector (passes) and the mutated violation vector
// (acceptance gate (f) — produces a `uvm_error` containing chart
// vocabulary).
//
// INFORMATIVE per §6.5 — customer-side test scaffolding. INV-S-HDL-F-2:
// SOS does NOT emit this; the test class is customer-authored.
//

`include "uvm_macros.svh"

import uvm_pkg::*;
import sos_uvm_seq_pkg::*;

class sos_kernel_test extends uvm_test;
  `uvm_component_utils(sos_kernel_test)

  sos_kernel_env env;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    env = sos_kernel_env::type_id::create("env", this);
  endfunction

  virtual task run_phase(uvm_phase phase);
    sos_sem_sequence seq;
    string vpath;

    phase.raise_objection(this);

    // Default vector path; overridden by +VECTOR_PATH=<path> plusarg.
    vpath = "vectors/sem_chart_bound.jsonl";
    void'($value$plusargs("VECTOR_PATH=%s", vpath));
    `uvm_info("TEST",
      $sformatf("starting SOS sem sequence with vector_path='%s'", vpath),
      UVM_LOW)

    seq = sos_sem_sequence::type_id::create("seq");
    seq.vector_path = vpath;
    seq.start(env.agent.sequencer);

    // Drain a few cycles so the last response can reach the scoreboard.
    #100ns;
    phase.drop_objection(this);
  endtask
endclass : sos_kernel_test
