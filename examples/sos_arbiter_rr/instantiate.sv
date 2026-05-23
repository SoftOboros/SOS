// =============================================================================
// examples/sos_arbiter_rr/instantiate.sv
//
// Minimal SystemVerilog-2017 instantiation example for `sos_arbiter_rr`
// with N_REQS = 4.
//
// @spec docs/concepts/SOS-08-A-CONCEPTS.md §4 source-of-truth map
//   (`examples/<primitive>/instantiate.{vhd,sv}`), §6.3 contract,
//   §12 (g) instantiation-example gate.
//
// Cited invariants:
//   INV-SOS-A, INV-SOS-E                              (SOS-07 §6)
//   INV-S-HDL-1, INV-S-HDL-5                          (SOS-08 §7)
//   INV-S-HDL-A-1, INV-S-HDL-A-3, INV-S-HDL-A-4,      (SOS-08-A §7)
//   INV-S-HDL-A-5
//
// The instantiation is illustrative only; it shows the parameter override
// (N_REQS = 4, no default per INV-S-HDL-A-5), the canonical port set, and
// the synchronous active-high reset wiring (INV-S-HDL-A-1).
// =============================================================================

`default_nettype none

module sos_arbiter_rr_inst4 (
    input  wire        clk,
    input  wire        rst,
    input  wire [3:0]  req,
    output wire [3:0]  grant,
    output wire [2:0]  last_winner_id  // $clog2(4+1) = 3
);

  sos_arbiter_rr #(
      .N_REQS (4)
  ) u_rr (
      .clk             (clk),
      .rst             (rst),
      .req             (req),
      .grant           (grant),
      .last_winner_id  (last_winner_id)
  );

endmodule : sos_arbiter_rr_inst4

`default_nettype wire
