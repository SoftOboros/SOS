// SPDX-License-Identifier: MIT
//
// SOS-08-F wave-2 acceptance gate (e) — customer-side UVM env
//
// Composes the agent + scoreboard and wires their analysis ports. The
// customer-side env is the binding layer between SOS-emitted sequences
// (running on the agent's sequencer) and the customer's failure
// reporting (scoreboard's chart-vocabulary `uvm_error` emission).
//
// INFORMATIVE per §6.5 — customer-side scaffolding. Per INV-S-HDL-F-2
// SOS does NOT emit the env; this file shows the minimal shape.
//

`include "uvm_macros.svh"

import uvm_pkg::*;
import sos_uvm_seq_pkg::*;

class sos_kernel_env extends uvm_env;
  `uvm_component_utils(sos_kernel_env)

  sos_kernel_agent      agent;
  sos_kernel_scoreboard sbd;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    agent = sos_kernel_agent::type_id::create("agent",     this);
    sbd   = sos_kernel_scoreboard::type_id::create("sbd",  this);
  endfunction

  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    agent.req_ap.connect(sbd.req_sub.analysis_export);
    agent.resp_ap.connect(sbd.resp_sub.analysis_export);
  endfunction
endclass : sos_kernel_env
