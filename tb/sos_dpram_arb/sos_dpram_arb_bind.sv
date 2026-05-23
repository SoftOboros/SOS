// ----------------------------------------------------------------------------
// sos_dpram_arb_bind.sv
//
// @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.7 (SVA bind file)
//       docs/concepts/SOS-08-A-CONCEPTS.md §4   (source-of-truth map row:
//                                                bind directive owned by tb/)
//       docs/concepts/SOS-08-A-CONCEPTS.md §15 (PCDN-A-bind-form ratified
//                                              2026-05-23 — module-type bind)
//       PCDN-A-dpram-SYNC_STAGES resolved 2026-05-23 — forwards SYNC_STAGES
//                                              parameter from the DUT
//                                              instance into the bound SVA
//                                              module so the eventually-
//                                              settled cover sequence
//                                              scales with the DUT's
//                                              synchroniser depth.
//
// Cross-phase / sub-phase / per-primitive invariants cited:
//   INV-SOS-A..H, INV-S-HDL-1..5, INV-S-HDL-A-1..5
//
// Binds sos_dpram_arb_sva to every elaborated sos_dpram_arb instance during
// cocotb simulation. Module-type bind per PCDN-A-bind-form — Verilator-
// compatible across all SOS-08-A primitives.
// ----------------------------------------------------------------------------

`default_nettype none

bind sos_dpram_arb sos_dpram_arb_sva #(
    .DEPTH        (DEPTH),
    .WIDTH        (WIDTH),
    .MODE         (MODE),
    .READ_LATENCY (READ_LATENCY),
    .RESET_MEM    (RESET_MEM),
    .SYNC_STAGES  (SYNC_STAGES)
) u_sva (
    .clk            (clk),
    .rst            (rst),
    .clk_a          (clk_a),
    .rst_a          (rst_a),
    .clk_b          (clk_b),
    .rst_b          (rst_b),

    .port_a_addr    (port_a_addr),
    .port_a_wdata   (port_a_wdata),
    .port_a_we      (port_a_we),
    .port_a_re      (port_a_re),
    .port_a_rdata   (port_a_rdata),
    .port_a_full    (port_a_full),
    .port_a_ready   (port_a_ready),

    .port_b_addr    (port_b_addr),
    .port_b_wdata   (port_b_wdata),
    .port_b_we      (port_b_we),
    .port_b_re      (port_b_re),
    .port_b_rdata   (port_b_rdata),
    .port_b_full    (port_b_full),
    .port_b_ready   (port_b_ready)
);

`default_nettype wire
