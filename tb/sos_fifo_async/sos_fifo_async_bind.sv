// ----------------------------------------------------------------------------
// sos_fifo_async_bind.sv
//
// @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.1 (SVA bind file)
//       docs/concepts/SOS-08-A-CONCEPTS.md §4   (source-of-truth map row:
//                                                bind directive owned by tb/)
//       docs/concepts/SOS-08-A-CONCEPTS.md §15  (2026-05-23 ratification +
//                                                impl wave-1 PCDN amendments)
//       PCDN-A-bind-form          resolved 2026-05-23 — module-type bind
//                                  across all SOS-08-A primitives. Attaches
//                                  the assertion module to every elaborated
//                                  sos_fifo_async instance design-wide.
//                                  Verilator-compatible (per-instance bind
//                                  has uneven Verilator support).
//       PCDN-A-fifo-READ_LATENCY  resolved 2026-05-23 — bind forwards
//                                  READ_LATENCY to the SVA module
//       PCDN-A-fifo-RESET_MEM     resolved 2026-05-23 — bind forwards
//                                  RESET_MEM to the SVA module
//
// Cross-phase / sub-phase / per-primitive invariants cited:
//   INV-SOS-A..H, INV-S-HDL-1..5, INV-S-HDL-A-1..5
//
// Module-type bind: `bind sos_fifo_async sos_fifo_async_sva u_sva (.*);`
// attaches sos_fifo_async_sva to every elaborated sos_fifo_async instance,
// without per-instance wiring. Parameters DEPTH/WIDTH/READ_LATENCY/RESET_MEM/
// SYNC_STAGES are forwarded so per-mode property generates compile correctly.
// ----------------------------------------------------------------------------

`default_nettype none

bind sos_fifo_async sos_fifo_async_sva #(
    .DEPTH        (DEPTH),
    .WIDTH        (WIDTH),
    .READ_LATENCY (READ_LATENCY),
    .RESET_MEM    (RESET_MEM),
    .SYNC_STAGES  (SYNC_STAGES)
) u_sva (
    // Write (producer) domain.
    .wr_clk         (wr_clk),
    .wr_rst         (wr_rst),

    .s_axis_tdata   (s_axis_tdata),
    .s_axis_tvalid  (s_axis_tvalid),
    .s_axis_tready  (s_axis_tready),

    .wr_full        (wr_full),
    .wr_count       (wr_count),

    // Read (consumer) domain.
    .rd_clk         (rd_clk),
    .rd_rst         (rd_rst),

    .m_axis_tdata   (m_axis_tdata),
    .m_axis_tvalid  (m_axis_tvalid),
    .m_axis_tready  (m_axis_tready),

    .rd_empty       (rd_empty),
    .rd_count       (rd_count)
);

`default_nettype wire
