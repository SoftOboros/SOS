// =============================================================================
// examples/sos_arbiter_priority/instantiate.sv
//
// Minimal SystemVerilog-2017 instantiation example for `sos_arbiter_priority`
// with N_REQS = 4 and PRIORITY_BITS = 3.  Two instances:
//   * u_strict -- AGING_ENABLE = 0; strict priority (low-priority requesters
//                 MAY starve under continuous high-priority contention).
//   * u_aging  -- AGING_ENABLE = 1, AGING_THRESHOLD = 128; starved requesters
//                 are promoted after 128 cycles.
//
// Both use the canonical registered grant shape (GRANT_LATENCY_CYCLES = 1).
//
// @spec docs/concepts/SOS-08-A-CONCEPTS.md §4 source-of-truth map
//   (`examples/<primitive>/instantiate.{vhd,sv}`), §6.4 contract,
//   §12 (g) instantiation-example gate.
//   Per PCDN-A-arbiter-GRANT_LATENCY_CYCLES resolved 2026-05-23,
//   extended to this primitive per task brief.
//
// Cited invariants:
//   INV-SOS-A, INV-SOS-E                              (SOS-07 §6)
//   INV-S-HDL-1, INV-S-HDL-5                          (SOS-08 §7)
//   INV-S-HDL-A-1, INV-S-HDL-A-3, INV-S-HDL-A-4,      (SOS-08-A §7)
//   INV-S-HDL-A-5
//
// The instantiation is illustrative only; it shows mandatory parameter
// overrides (INV-S-HDL-A-5), the canonical port set with the flat
// `priority_in` bus, and synchronous active-high reset wiring
// (INV-S-HDL-A-1).
// =============================================================================

`default_nettype none

module sos_arbiter_priority_inst4 (
    input  wire        clk,
    input  wire        rst,
    input  wire [3:0]  req,
    // Flat 4 * 3 = 12-bit priority vector.  Slot i at bits [(i+1)*3-1 : i*3].
    input  wire [11:0] priority_in,
    output wire [3:0]  grant_strict,
    output wire [2:0]  last_winner_id_strict,   // $clog2(4+1) = 3
    output wire [3:0]  grant_aging,
    output wire [2:0]  last_winner_id_aging
);

  // Strict priority: AGING_ENABLE = 0.  AGING_THRESHOLD must still be a valid
  // positive integer (mandatory generic), but its value does not influence
  // arbitration under strict mode.
  sos_arbiter_priority #(
      .N_REQS               (4),
      .PRIORITY_BITS        (3),
      .AGING_ENABLE         (0),
      .AGING_THRESHOLD      (1),
      .GRANT_LATENCY_CYCLES (1)
  ) u_strict (
      .clk             (clk),
      .rst             (rst),
      .req             (req),
      .priority_in     (priority_in),
      .grant           (grant_strict),
      .last_winner_id  (last_winner_id_strict)
  );

  // Aging-enabled: starved requesters promote after AGING_THRESHOLD cycles.
  sos_arbiter_priority #(
      .N_REQS               (4),
      .PRIORITY_BITS        (3),
      .AGING_ENABLE         (1),
      .AGING_THRESHOLD      (128),
      .GRANT_LATENCY_CYCLES (1)
  ) u_aging (
      .clk             (clk),
      .rst             (rst),
      .req             (req),
      .priority_in     (priority_in),
      .grant           (grant_aging),
      .last_winner_id  (last_winner_id_aging)
  );

endmodule : sos_arbiter_priority_inst4

`default_nettype wire
