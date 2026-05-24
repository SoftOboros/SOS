// ----------------------------------------------------------------------------
// sos_message_channel_async_bind.sv
//
// @spec docs/concepts/SOS-08-B-CONCEPTS.md §6.5 (service-level SVA bind,
//             async variant)
//       docs/concepts/SOS-08-B-CONCEPTS.md §5.4 (service-level SVA binding
//             default — per umbrella PCDN-SOS-08-007: full bind by default)
//       docs/concepts/SOS-08-B-CONCEPTS.md §7  (INV-S-HDL-B-3 — every L1
//             service ships with a service-level SVA bind file binding to
//             every instance)
//       docs/concepts/SOS-08-B-CONCEPTS.md §15 — 2026-05-24 amendment
//             ratifying the async sibling variant.
//
// Cross-phase / sub-phase / service / primitive invariants cited:
//   INV-SOS-A..H, INV-S-HDL-1..5, INV-S-HDL-B-1..5, INV-S-HDL-A-1..5
//
// Binds sos_message_channel_async_sva to every elaborated
// sos_message_channel_async instance during cocotb simulation. The bind is
// hierarchy-blind (`bind sos_message_channel_async`) so any number of DUT
// instances in a testbench pick up the assertion module without per-
// instance wiring.
//
// The inner sos_fifo_async's own bind (sos_fifo_async_bind.sv) attaches
// concurrently — both bound modules contribute their respective property
// sets to the same DUT instance.
// ----------------------------------------------------------------------------

`default_nettype none

bind sos_message_channel_async sos_message_channel_async_sva #(
    .EVENT_ID_WIDTH (EVENT_ID_WIDTH),
    .PAYLOAD_WIDTH  (PAYLOAD_WIDTH),
    .DEPTH          (DEPTH),
    .READ_LATENCY   (READ_LATENCY),
    .RESET_MEM      (RESET_MEM),
    .SYNC_STAGES    (SYNC_STAGES)
) u_sva (
    .wr_clk           (wr_clk),
    .wr_rst           (wr_rst),
    .s_axis_tdata     (s_axis_tdata),
    .s_axis_tevent_id (s_axis_tevent_id),
    .s_axis_tpayload  (s_axis_tpayload),
    .s_axis_tvalid    (s_axis_tvalid),
    .s_axis_tready    (s_axis_tready),
    .wr_full          (wr_full),
    .wr_count         (wr_count),

    .rd_clk           (rd_clk),
    .rd_rst           (rd_rst),
    .m_axis_tdata     (m_axis_tdata),
    .m_axis_tevent_id (m_axis_tevent_id),
    .m_axis_tpayload  (m_axis_tpayload),
    .m_axis_tvalid    (m_axis_tvalid),
    .m_axis_tready    (m_axis_tready),
    .rd_empty         (rd_empty),
    .rd_count         (rd_count)
);

`default_nettype wire
