// ----------------------------------------------------------------------------
// examples/sos_fifo_sync/instantiate.sv
//
// @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.2 (instantiation example)
//       INV-S-HDL-A-3  vendor-shim wrapper is byte-identical
//       INV-S-HDL-A-5  mandatory parameters, no defaults
//       PCDN-A-fifo-READ_LATENCY  resolved 2026-05-23 — READ_LATENCY param
//       PCDN-A-fifo-RESET_MEM     resolved 2026-05-23 — RESET_MEM param
//
// Minimal instantiation of sos_fifo_sync. Shows parameter passing and the
// AXI-Stream-naming port map ratified by PCDN-SOS-08-A-002 (§15 2026-05-23).
// The chart-emitted top-level (SOS-08-C) produces instantiations of this
// shape automatically.
//
// Two example bindings are shown:
//   * u_fifo_fwft   — DEPTH=16, WIDTH=32, READ_LATENCY=0, RESET_MEM=0.
//                     Legacy / smallest-area shape; m_axis_tdata is FWFT.
//   * u_fifo_reg    — DEPTH=16, WIDTH=32, READ_LATENCY=1, RESET_MEM=1.
//                     Registered read output; storage cleared on reset.
// ----------------------------------------------------------------------------

`default_nettype none

module sos_fifo_sync_example (
    input  wire        clk,
    input  wire        rst,

    // FWFT / no-RESET_MEM channel.
    input  wire [31:0] in_data_a,
    input  wire        in_valid_a,
    output wire        in_ready_a,

    output wire [31:0] out_data_a,
    output wire        out_valid_a,
    input  wire        out_ready_a,

    // Registered-read / RESET_MEM channel.
    input  wire [31:0] in_data_b,
    input  wire        in_valid_b,
    output wire        in_ready_b,

    output wire [31:0] out_data_b,
    output wire        out_valid_b,
    input  wire        out_ready_b
);

    wire        full_a;
    wire        empty_a;
    wire [4:0]  count_a;  // $clog2(16+1) = 5

    wire        full_b;
    wire        empty_b;
    wire [4:0]  count_b;

    // Example A: legacy FWFT, mem retained across reset.
    sos_fifo_sync #(
        // INV-S-HDL-A-5: every parameter supplied explicitly (no defaults).
        .DEPTH        (16),
        .WIDTH        (32),
        .READ_LATENCY (0),       // FWFT
        .RESET_MEM    (1'b0)     // legacy: mem not reset
    ) u_fifo_fwft (
        .clk            (clk),
        .rst            (rst),

        .s_axis_tdata   (in_data_a),
        .s_axis_tvalid  (in_valid_a),
        .s_axis_tready  (in_ready_a),

        .m_axis_tdata   (out_data_a),
        .m_axis_tvalid  (out_valid_a),
        .m_axis_tready  (out_ready_a),

        .full           (full_a),
        .empty          (empty_a),
        .count          (count_a)
    );

    // Example B: registered-read output, mem cleared on reset.
    sos_fifo_sync #(
        .DEPTH        (16),
        .WIDTH        (32),
        .READ_LATENCY (1),       // one-cycle registered read latency
        .RESET_MEM    (1'b1)     // strict: mem zeroed on reset
    ) u_fifo_reg (
        .clk            (clk),
        .rst            (rst),

        .s_axis_tdata   (in_data_b),
        .s_axis_tvalid  (in_valid_b),
        .s_axis_tready  (in_ready_b),

        .m_axis_tdata   (out_data_b),
        .m_axis_tvalid  (out_valid_b),
        .m_axis_tready  (out_ready_b),

        .full           (full_b),
        .empty          (empty_b),
        .count          (count_b)
    );

endmodule

`default_nettype wire
