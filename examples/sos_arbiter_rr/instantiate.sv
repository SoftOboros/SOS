// =============================================================================
// examples/sos_arbiter_rr/instantiate.sv
//
// Minimal SystemVerilog-2017 instantiation example for `sos_arbiter_rr`
// with N_REQS = 4.  Demonstrates both supported `GRANT_LATENCY_CYCLES`
// shapes:
//   * u_rr_lat1 -- registered grant (canonical v1 form; latency = 1).
//   * u_rr_lat0 -- combinational grant forward (opt-in v0 form; latency = 0).
//
// @spec docs/concepts/SOS-08-A-CONCEPTS.md §4 source-of-truth map
//   (`examples/<primitive>/instantiate.{vhd,sv}`), §6.3 contract,
//   §12 (g) instantiation-example gate.
//   Per PCDN-A-arbiter-GRANT_LATENCY_CYCLES resolved 2026-05-23.
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
    output wire [3:0]  grant_lat1,
    output wire [2:0]  last_winner_id_lat1,  // $clog2(4+1) = 3
    output wire [3:0]  grant_lat0,
    output wire [2:0]  last_winner_id_lat0
);

  // Canonical v1 shape: registered grant, 1-cycle latency.  The default
  // is shown explicitly here for documentation parity with u_rr_lat0.
  sos_arbiter_rr #(
      .N_REQS               (4),
      .GRANT_LATENCY_CYCLES (1)
  ) u_rr_lat1 (
      .clk             (clk),
      .rst             (rst),
      .req             (req),
      .grant           (grant_lat1),
      .last_winner_id  (last_winner_id_lat1)
  );

  // Opt-in v0 shape: combinational grant forward, same-cycle latency.
  sos_arbiter_rr #(
      .N_REQS               (4),
      .GRANT_LATENCY_CYCLES (0)
  ) u_rr_lat0 (
      .clk             (clk),
      .rst             (rst),
      .req             (req),
      .grant           (grant_lat0),
      .last_winner_id  (last_winner_id_lat0)
  );

endmodule : sos_arbiter_rr_inst4

`default_nettype wire
