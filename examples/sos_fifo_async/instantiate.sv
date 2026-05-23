// ----------------------------------------------------------------------------
// examples/sos_fifo_async/instantiate.sv
//
// @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.1 (instantiation example)
//       docs/concepts/SOS-08-A-CONCEPTS.md §15  (2026-05-23 ratification +
//                                                impl wave-1 PCDN amendments)
//       INV-S-HDL-A-1  sync active-high reset per side + AXI-Stream naming
//       INV-S-HDL-A-3  vendor-shim wrapper is byte-identical
//       INV-S-HDL-A-5  mandatory parameters, no defaults (SYNC_STAGES is
//                      the documented exception, default 2)
//       PCDN-A-fifo-READ_LATENCY  resolved 2026-05-23 — READ_LATENCY param
//       PCDN-A-fifo-RESET_MEM     resolved 2026-05-23 — RESET_MEM param
//
// Minimal instantiation of sos_fifo_async. Shows two independent clock
// domains (clk_a producer, clk_b consumer) with their own resets, the
// AXI-Stream-naming port map ratified by PCDN-SOS-08-A-002, and the
// SOS-08-A §6.1 canonical shape (DEPTH=16, WIDTH=32, READ_LATENCY=0,
// RESET_MEM=0, SYNC_STAGES=2 — the well-trodden CDC value).
//
// The chart-emitted top-level (SOS-08-C) produces instantiations of this
// shape automatically.
// ----------------------------------------------------------------------------

`default_nettype none

module sos_fifo_async_example (
    // Producer (write) domain.
    input  wire        clk_a,
    input  wire        rst_a,
    input  wire [31:0] in_data,
    input  wire        in_valid,
    output wire        in_ready,
    output wire        a_full,

    // Consumer (read) domain.
    input  wire        clk_b,
    input  wire        rst_b,
    output wire [31:0] out_data,
    output wire        out_valid,
    input  wire        out_ready,
    output wire        b_empty
);

    // Width of the per-side count = $clog2(16+1) = 5.
    wire [4:0] count_a;
    wire [4:0] count_b;

    // SOS-08-A §6.1 canonical instantiation. Every parameter supplied
    // explicitly per INV-S-HDL-A-5; SYNC_STAGES is the documented exception
    // (default 2) but spelled out here for clarity at the build wrapper.
    sos_fifo_async #(
        .DEPTH        (16),
        .WIDTH        (32),
        .READ_LATENCY (0),       // FWFT
        .RESET_MEM    (1'b0),    // legacy: mem not reset
        .SYNC_STAGES  (2)        // well-trodden CDC depth — see MTBF.md
    ) u_evt_fifo (
        // Write (producer) domain.
        .wr_clk         (clk_a),
        .wr_rst         (rst_a),

        .s_axis_tdata   (in_data),
        .s_axis_tvalid  (in_valid),
        .s_axis_tready  (in_ready),

        .wr_full        (a_full),
        .wr_count       (count_a),

        // Read (consumer) domain.
        .rd_clk         (clk_b),
        .rd_rst         (rst_b),

        .m_axis_tdata   (out_data),
        .m_axis_tvalid  (out_valid),
        .m_axis_tready  (out_ready),

        .rd_empty       (b_empty),
        .rd_count       (count_b)
    );

endmodule

`default_nettype wire
