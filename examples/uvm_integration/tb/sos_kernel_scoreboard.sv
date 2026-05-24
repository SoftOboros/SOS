// SPDX-License-Identifier: MIT
//
// SOS-08-F wave-2 acceptance gate (e) — customer-side scoreboard
//
// Pairs driver-published request transactions (carrying SOS chart-
// vocabulary metadata) with monitor-published response transactions
// (carrying DUT bus state). Emits chart-vocabulary failure messages
// per §6.6 when:
//   * a sem.take is attempted on an already-held sem (kernel returns
//     resp_ok=0 — scoreboard surfaces the violation in chart vocab);
//   * a sem.give is attempted on a non-held sem (same);
//   * any other resp_ok=0 case (delegated to chart vocab as well);
//   * the request/response counts diverge by end of simulation.
//
// INFORMATIVE per §6.5 — customer-side scoreboard. SOS-08-F does NOT
// emit scoreboards (INV-S-HDL-F-1 / -2); this file demonstrates how the
// chart vocabulary survives into the customer's failure-reporting per
// INV-SOS-H + INV-S-HDL-5 + INV-S-HDL-F-3.
//
// The "[SOS-SEQ] state=... transition=... invariant=... family=...
// event=..." string format is the load-bearing §6.6 contract: any
// customer infrastructure that catches a `uvm_error` from this file
// gets chart vocabulary in the message body.
//

`include "uvm_macros.svh"

import uvm_pkg::*;
import sos_uvm_seq_pkg::*;

// Analysis subscriber for the request side — buffers pending requests.
class sos_kernel_req_sub extends uvm_subscriber #(sos_kernel_obs_item);
  `uvm_component_utils(sos_kernel_req_sub)

  sos_kernel_obs_item q[$];

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  virtual function void write(sos_kernel_obs_item t);
    q.push_back(t);
  endfunction
endclass : sos_kernel_req_sub

// Analysis subscriber for the response side — pairs against the
// front of the request queue when a response arrives.
class sos_kernel_resp_sub extends uvm_subscriber #(sos_kernel_obs_item);
  `uvm_component_utils(sos_kernel_resp_sub)

  sos_kernel_req_sub req_sub;
  int unsigned pairs_ok;
  int unsigned pairs_fail;

  function new(string name, uvm_component parent);
    super.new(name, parent);
    pairs_ok   = 0;
    pairs_fail = 0;
  endfunction

  virtual function void write(sos_kernel_obs_item t);
    sos_kernel_obs_item req;
    if (req_sub.q.size() == 0) begin
      `uvm_error("SBD",
        $sformatf("[SOS-SEQ] state=<unknown> transition=0 invariant=0 family=%s event=%0d: response with no matching request",
          t.family.name(), t.event_id))
      pairs_fail++;
      return;
    end
    req = req_sub.q.pop_front();
    if (req.family != t.family || req.event_id != t.event_id) begin
      `uvm_error("SBD",
        $sformatf("[SOS-SEQ] state=%s transition=%0d invariant=%0d family=%s event=%0d: response family/event mismatch (saw family=%s event=%0d)",
          req.chart_state, req.transition_id, req.invariant_id,
          req.family.name(), req.event_id,
          t.family.name(), t.event_id))
      pairs_fail++;
      return;
    end
    if (!t.resp_ok) begin
      // Chart-vocabulary failure-message format per §6.6 / INV-S-HDL-F-3.
      `uvm_error("SBD",
        $sformatf("[SOS-SEQ] state=%s transition=%0d invariant=%0d family=%s event=%0d: kernel rejected syscall (resp_ok=0)",
          req.chart_state, req.transition_id, req.invariant_id,
          req.family.name(), req.event_id))
      pairs_fail++;
    end else begin
      pairs_ok++;
    end
  endfunction
endclass : sos_kernel_resp_sub

// Composite scoreboard owning both subscribers.
class sos_kernel_scoreboard extends uvm_scoreboard;
  `uvm_component_utils(sos_kernel_scoreboard)

  sos_kernel_req_sub  req_sub;
  sos_kernel_resp_sub resp_sub;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    req_sub  = sos_kernel_req_sub::type_id::create("req_sub",   this);
    resp_sub = sos_kernel_resp_sub::type_id::create("resp_sub", this);
    resp_sub.req_sub = req_sub;
  endfunction

  function void report_phase(uvm_phase phase);
    super.report_phase(phase);
    `uvm_info("SBD",
      $sformatf("scoreboard summary: pairs_ok=%0d pairs_fail=%0d unmatched_req=%0d",
        resp_sub.pairs_ok, resp_sub.pairs_fail, req_sub.q.size()),
      UVM_LOW)
    if (req_sub.q.size() != 0)
      `uvm_warning("SBD",
        $sformatf("%0d request(s) had no matching response at end-of-test",
          req_sub.q.size()))
  endfunction
endclass : sos_kernel_scoreboard
