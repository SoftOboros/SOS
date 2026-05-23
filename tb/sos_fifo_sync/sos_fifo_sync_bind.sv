// ----------------------------------------------------------------------------
// sos_fifo_sync_bind.sv
//
// @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.2 (SVA bind file)
//       docs/concepts/SOS-08-A-CONCEPTS.md §4   (source-of-truth map row:
//                                                bind directive owned by tb/)
//
// Cross-phase / sub-phase / per-primitive invariants cited:
//   INV-SOS-A..H, INV-S-HDL-1..5, INV-S-HDL-A-1..5
//
// Binds sos_fifo_sync_sva to every elaborated sos_fifo_sync instance during
// cocotb simulation. The bind is hierarchy-blind (`bind sos_fifo_sync`) so any
// number of DUT instances in a testbench pick up the assertion module without
// per-instance wiring.
// ----------------------------------------------------------------------------

`default_nettype none

bind sos_fifo_sync sos_fifo_sync_sva #(
    .DEPTH(DEPTH),
    .WIDTH(WIDTH)
) u_sva (
    .clk            (clk),
    .rst            (rst),

    .s_axis_tdata   (s_axis_tdata),
    .s_axis_tvalid  (s_axis_tvalid),
    .s_axis_tready  (s_axis_tready),

    .m_axis_tdata   (m_axis_tdata),
    .m_axis_tvalid  (m_axis_tvalid),
    .m_axis_tready  (m_axis_tready),

    .full           (full),
    .empty          (empty),
    .count          (count)
);

`default_nettype wire
