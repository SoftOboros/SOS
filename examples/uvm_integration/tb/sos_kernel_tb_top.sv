// SPDX-License-Identifier: MIT
//
// SOS-08-F wave-2 acceptance gate (e) — top-level testbench module
//
// Instantiates the synthetic DUT, the interface bundle, and the UVM
// env. `run_test` selects the test class from a +UVM_TESTNAME plusarg
// (defaulting to sos_kernel_test) per standard UVM mechanics.
//
// INFORMATIVE per §6.5 — top-level customer scaffolding. The flow is
// the §6.5 five-step contract running against a real synthetic DUT:
//
//   step 1 (import sos_uvm_seq_pkg::*;) — done in agent / env / test.
//   step 2 (sequencer typedef)           — in sos_kernel_agent.sv.
//   step 3 (driver implementation)        — sos_kernel_driver in agent.
//   step 4 (sequence start)               — sos_kernel_test.run_phase.
//   step 5 (failure handling)             — sos_kernel_scoreboard.sv
//                                            chart-vocab `uvm_error`.
//
// Spec invariants exercised end-to-end:
//   INV-S-HDL-F-1 — only the SOS-emitted package contains sequences;
//                    customer's classes are env/agent/sbd/test.
//   INV-S-HDL-F-2 — env, scoreboard, driver, factory all customer-owned.
//   INV-S-HDL-F-3 — chart vocabulary survives into scoreboard `uvm_error`
//                    string per §6.6.
//   INV-S-HDL-F-4 — no `assert property`, no `bind` directive anywhere
//                    in the example tree (SVA is sibling SOS-08-D/E).
//   INV-S-HDL-F-5 — testbench compiles against UVM 1.2 and UVM 2.0
//                    (forward-compat).
//

`include "uvm_macros.svh"

import uvm_pkg::*;
import sos_uvm_seq_pkg::*;

module sos_kernel_tb_top;

  // 100 MHz reference clock.
  bit clk = 1'b0;
  always #5ns clk = ~clk;

  sos_kernel_if vif(clk);

  sos_kernel_dut #(.NUM_SEMS(2)) dut (
    .clk           (clk),
    .rst_n         (vif.rst_n),
    .req_valid     (vif.req_valid),
    .req_ready     (vif.req_ready),
    .req_family    (vif.req_family),
    .req_event_id  (vif.req_event_id),
    .req_payload   (vif.req_payload),
    .resp_valid    (vif.resp_valid),
    .resp_ok       (vif.resp_ok),
    .resp_event_id (vif.resp_event_id),
    .resp_family   (vif.resp_family)
  );

  initial begin
    uvm_config_db #(virtual sos_kernel_if)::set(null, "uvm_test_top.env.agent.driver",  "vif", vif);
    uvm_config_db #(virtual sos_kernel_if)::set(null, "uvm_test_top.env.agent.monitor", "vif", vif);
    run_test("sos_kernel_test");
  end

endmodule : sos_kernel_tb_top
