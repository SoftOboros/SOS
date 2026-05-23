// =============================================================================
// examples/sos_tick_gen/instantiate.sv
//
// Minimal SystemVerilog-2017 instantiation example for `sos_tick_gen` with
// PERIOD_CYCLES = 100 and INITIAL_PHASE = 0.
//
// @spec docs/concepts/SOS-08-A-CONCEPTS.md §4 source-of-truth map
//   (`examples/<primitive>/instantiate.{vhd,sv}`), §6.8 contract,
//   §12 (g) instantiation-example gate.
//
// Cited invariants:
//   INV-SOS-A, INV-SOS-E                              (SOS-07 §6)
//   INV-S-HDL-1, INV-S-HDL-5                          (SOS-08 §7)
//   INV-S-HDL-A-1, INV-S-HDL-A-3, INV-S-HDL-A-4,      (SOS-08-A §7)
//   INV-S-HDL-A-5
//
// The instantiation is illustrative only; it shows the mandatory parameter
// overrides (PERIOD_CYCLES = 100, INITIAL_PHASE = 0; no defaults per
// INV-S-HDL-A-5), the canonical port set with the modulo `counter`
// observability port (wave-1 amendment, see RTL header), and the
// synchronous active-high reset wiring (INV-S-HDL-A-1).
// =============================================================================

`default_nettype none

module sos_tick_gen_inst100 (
    input  wire        clk,
    input  wire        rst,
    input  wire        enable,
    output wire        tick,
    // $clog2(100) = 7 bits for the modulo counter.
    output wire [6:0]  counter
);

  // Mandatory parameter overrides; no defaults per INV-S-HDL-A-5.
  sos_tick_gen #(
      .PERIOD_CYCLES (100),
      .INITIAL_PHASE (0)
  ) u_tg (
      .clk     (clk),
      .rst     (rst),
      .enable  (enable),
      .tick    (tick),
      .counter (counter)
  );

endmodule : sos_tick_gen_inst100

`default_nettype wire
