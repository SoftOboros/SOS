// =============================================================================
// examples/sos_rate_divider/instantiate.sv
//
// Minimal SystemVerilog-2017 instantiation example for `sos_rate_divider`
// with DIVISOR = 10 and INITIAL_COUNTER = 0 (the canonical "divide by 10
// starting at the natural phase" configuration).
//
// @spec docs/concepts/SOS-08-A-CONCEPTS.md §4 source-of-truth map
//   (`examples/<primitive>/instantiate.{vhd,sv}`), §6.11 contract,
//   §12 (g) instantiation-example gate.
//   Per 2026-05-23 ratification (§15) and the 2026-05-23 continuation-
//   amendment PCDN walkthrough.
//
// Cited invariants:
//   INV-SOS-A, INV-SOS-E                              (SOS-07 §6)
//   INV-S-HDL-1, INV-S-HDL-5                          (SOS-08 §7)
//   INV-S-HDL-A-1, INV-S-HDL-A-3, INV-S-HDL-A-5       (SOS-08-A §7)
//
// The instantiation is illustrative only; it shows the parameter override
// (DIVISOR = 10 + INITIAL_COUNTER = 0, both mandatory per INV-S-HDL-A-5),
// the canonical port set, the tick-style 1-cycle pulse i/o, and the
// synchronous active-high reset wiring (INV-S-HDL-A-1).
// =============================================================================

`default_nettype none

module sos_rate_divider_inst10 (
    input  wire        clk,
    input  wire        rst,
    input  wire        tick_in,
    output wire        tick_out,
    output wire [3:0]  counter      // $clog2(10) = 4
);

  sos_rate_divider #(
      .DIVISOR         (10),
      .INITIAL_COUNTER (0)
  ) u_div_10 (
      .clk      (clk),
      .rst      (rst),
      .tick_in  (tick_in),
      .tick_out (tick_out),
      .counter  (counter)
  );

endmodule : sos_rate_divider_inst10

`default_nettype wire
