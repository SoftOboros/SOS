// ----------------------------------------------------------------------------
// examples/sos_fifo_sync/instantiate.sv
//
// @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.2 (instantiation example)
//       INV-S-HDL-A-3  vendor-shim wrapper is byte-identical
//       INV-S-HDL-A-5  mandatory parameters, no defaults
//
// Minimal instantiation of sos_fifo_sync. Shows parameter passing and the
// AXI-Stream-naming port map ratified by PCDN-SOS-08-A-002 (§15 2026-05-23).
// The chart-emitted top-level (SOS-08-C) produces instantiations of this
// shape automatically.
// ----------------------------------------------------------------------------

`default_nettype none

module sos_fifo_sync_example (
    input  wire        clk,
    input  wire        rst,

    input  wire [31:0] in_data,
    input  wire        in_valid,
    output wire        in_ready,

    output wire [31:0] out_data,
    output wire        out_valid,
    input  wire        out_ready
);

    wire        full_q;
    wire        empty_q;
    wire [4:0]  count_q;  // $clog2(16+1) = 5

    sos_fifo_sync #(
        // INV-S-HDL-A-5: both parameters supplied explicitly.
        .DEPTH (16),
        .WIDTH (32)
    ) u_fifo (
        .clk            (clk),
        .rst            (rst),

        .s_axis_tdata   (in_data),
        .s_axis_tvalid  (in_valid),
        .s_axis_tready  (in_ready),

        .m_axis_tdata   (out_data),
        .m_axis_tvalid  (out_valid),
        .m_axis_tready  (out_ready),

        .full           (full_q),
        .empty          (empty_q),
        .count          (count_q)
    );

endmodule

`default_nettype wire
