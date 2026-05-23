// ----------------------------------------------------------------------------
// examples/sos_message_channel/instantiate.sv
//
// @spec docs/concepts/SOS-08-B-CONCEPTS.md §6.5 (instantiation example)
//       docs/concepts/SOS-08-B-CONCEPTS.md §15 — PCDN-SOS-08-B-005 resolved
//             2026-05-23: chart-derived metadata struct. This example shows
//             the structurally-uniform L1 instantiation; the per-event
//             packed-struct variant interpretation is SOS-08-C's
//             responsibility and not exercised here.
//       INV-S-HDL-A-3  vendor-shim wrapper is byte-identical
//       INV-S-HDL-A-5  mandatory parameters, no defaults
//       INV-S-HDL-B-2  L0 non-modification
//       INV-S-HDL-B-3  service-level SVA on every L1 instance
//
// Minimal instantiation of sos_message_channel showing parameter passing
// and the AXI-Stream + sideband port map. The chart-emitted top-level
// (SOS-08-C) produces instantiations of this shape automatically, plus the
// per-event packed-struct encode / decode glue around it.
//
// Parameters:
//   EVENT_ID_WIDTH = 10  (chart ExternalEventName index width)
//   PAYLOAD_WIDTH  = 128 (max chart-event payload width)
//   DEPTH          = 16
//   READ_LATENCY   = 0   (FWFT)
//   RESET_MEM      = 0   (legacy — mem retained across reset)
// ----------------------------------------------------------------------------

`default_nettype none

module sos_message_channel_example (
    input  wire         clk,
    input  wire         rst,

    // Producer-side ports. The chart-emitter (SOS-08-C) drives EITHER the
    // packed bus OR the decomposed sideband; the L1 service OR-combines
    // them. This example exposes both for completeness.
    input  wire [137:0]  in_tdata,        // 10 + 128 = 138 bits packed
    input  wire [9:0]    in_tevent_id,
    input  wire [127:0]  in_tpayload,
    input  wire          in_tvalid,
    output wire          in_tready,

    // Consumer-side ports.
    output wire [137:0]  out_tdata,
    output wire [9:0]    out_tevent_id,
    output wire [127:0]  out_tpayload,
    output wire          out_tvalid,
    input  wire          out_tready
);

    wire        full;
    wire        empty;
    wire [4:0]  count;  // $clog2(16+1) = 5

    sos_message_channel #(
        // INV-S-HDL-A-5: every parameter supplied explicitly (no defaults).
        .EVENT_ID_WIDTH (10),
        .PAYLOAD_WIDTH  (128),
        .DEPTH          (16),
        .READ_LATENCY   (0),       // FWFT
        .RESET_MEM      (1'b0)     // legacy: mem not reset
    ) u_msgch (
        .clk              (clk),
        .rst              (rst),

        .s_axis_tdata     (in_tdata),
        .s_axis_tevent_id (in_tevent_id),
        .s_axis_tpayload  (in_tpayload),
        .s_axis_tvalid    (in_tvalid),
        .s_axis_tready    (in_tready),

        .m_axis_tdata     (out_tdata),
        .m_axis_tevent_id (out_tevent_id),
        .m_axis_tpayload  (out_tpayload),
        .m_axis_tvalid    (out_tvalid),
        .m_axis_tready    (out_tready),

        .full             (full),
        .empty            (empty),
        .count            (count)
    );

endmodule

`default_nettype wire
