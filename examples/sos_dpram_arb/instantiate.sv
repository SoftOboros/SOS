// ----------------------------------------------------------------------------
// examples/sos_dpram_arb/instantiate.sv
//
// @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.7 (instantiation example)
//       docs/concepts/SOS-08-A-CONCEPTS.md §15 (2026-05-23 amendments —
//                                              READ_LATENCY + RESET_MEM
//                                              pattern inherited from
//                                              PCDN-A-fifo-* on sos_fifo_sync)
//       INV-S-HDL-A-3  vendor-shim wrapper is byte-identical
//       INV-S-HDL-A-5  mandatory parameters, no defaults
//       INV-S-HDL-3    cross-domain isolation (MODE=DUAL_CLOCK only)
//
// Two example bindings are shown:
//   * u_dpram_single — MODE="SINGLE_CLOCK", DEPTH=64, WIDTH=32,
//                      READ_LATENCY=0, RESET_MEM=0.
//                      Single-clock dual-port RAM with combinational reads.
//   * u_dpram_dual   — MODE="DUAL_CLOCK",   DEPTH=64, WIDTH=32,
//                      READ_LATENCY=1, RESET_MEM=1.
//                      Dual-clock CDC variant with registered reads and
//                      mem zeroed on reset. MTBF.md sign-off REQUIRED at
//                      deployment time per SOS-08-A §12 (f).
// ----------------------------------------------------------------------------

`default_nettype none

module sos_dpram_arb_example (
    input  wire        clk,
    input  wire        rst,
    input  wire        clk_a,
    input  wire        rst_a,
    input  wire        clk_b,
    input  wire        rst_b,

    // SINGLE_CLOCK instance ports.
    input  wire [5:0]  sc_port_a_addr,
    input  wire [31:0] sc_port_a_wdata,
    input  wire        sc_port_a_we,
    input  wire        sc_port_a_re,
    output wire [31:0] sc_port_a_rdata,
    output wire        sc_port_a_full,
    output wire        sc_port_a_ready,

    input  wire [5:0]  sc_port_b_addr,
    input  wire [31:0] sc_port_b_wdata,
    input  wire        sc_port_b_we,
    input  wire        sc_port_b_re,
    output wire [31:0] sc_port_b_rdata,
    output wire        sc_port_b_full,
    output wire        sc_port_b_ready,

    // DUAL_CLOCK instance ports.
    input  wire [5:0]  dc_port_a_addr,
    input  wire [31:0] dc_port_a_wdata,
    input  wire        dc_port_a_we,
    input  wire        dc_port_a_re,
    output wire [31:0] dc_port_a_rdata,
    output wire        dc_port_a_full,
    output wire        dc_port_a_ready,

    input  wire [5:0]  dc_port_b_addr,
    input  wire [31:0] dc_port_b_wdata,
    input  wire        dc_port_b_we,
    input  wire        dc_port_b_re,
    output wire [31:0] dc_port_b_rdata,
    output wire        dc_port_b_full,
    output wire        dc_port_b_ready
);

    // Example A: SINGLE_CLOCK — both ports share `clk`. MTBF treatment N/A.
    sos_dpram_arb #(
        // INV-S-HDL-A-5: every parameter supplied explicitly (no defaults).
        .DEPTH        (64),
        .WIDTH        (32),
        .MODE         ("SINGLE_CLOCK"),
        .READ_LATENCY (0),         // FWFT
        .RESET_MEM    (1'b0)       // legacy: mem not reset
    ) u_dpram_single (
        .clk          (clk),
        .rst          (rst),
        .clk_a        (clk),       // tied; unused in SINGLE_CLOCK
        .rst_a        (rst),
        .clk_b        (clk),
        .rst_b        (rst),

        .port_a_addr  (sc_port_a_addr),
        .port_a_wdata (sc_port_a_wdata),
        .port_a_we    (sc_port_a_we),
        .port_a_re    (sc_port_a_re),
        .port_a_rdata (sc_port_a_rdata),
        .port_a_full  (sc_port_a_full),
        .port_a_ready (sc_port_a_ready),

        .port_b_addr  (sc_port_b_addr),
        .port_b_wdata (sc_port_b_wdata),
        .port_b_we    (sc_port_b_we),
        .port_b_re    (sc_port_b_re),
        .port_b_rdata (sc_port_b_rdata),
        .port_b_full  (sc_port_b_full),
        .port_b_ready (sc_port_b_ready)
    );

    // Example B: DUAL_CLOCK — port A on clk_a/rst_a, port B on clk_b/rst_b.
    // MTBF.md sign-off REQUIRED at deployment time (SOS-08-A §12 (f)).
    sos_dpram_arb #(
        .DEPTH        (64),
        .WIDTH        (32),
        .MODE         ("DUAL_CLOCK"),
        .READ_LATENCY (1),         // registered read on each port
        .RESET_MEM    (1'b1)       // strict: mem zeroed on reset
    ) u_dpram_dual (
        .clk          (clk_a),     // tied to clk_a; unused in DUAL_CLOCK
        .rst          (rst_a),
        .clk_a        (clk_a),
        .rst_a        (rst_a),
        .clk_b        (clk_b),
        .rst_b        (rst_b),

        .port_a_addr  (dc_port_a_addr),
        .port_a_wdata (dc_port_a_wdata),
        .port_a_we    (dc_port_a_we),
        .port_a_re    (dc_port_a_re),
        .port_a_rdata (dc_port_a_rdata),
        .port_a_full  (dc_port_a_full),
        .port_a_ready (dc_port_a_ready),

        .port_b_addr  (dc_port_b_addr),
        .port_b_wdata (dc_port_b_wdata),
        .port_b_we    (dc_port_b_we),
        .port_b_re    (dc_port_b_re),
        .port_b_rdata (dc_port_b_rdata),
        .port_b_full  (dc_port_b_full),
        .port_b_ready (dc_port_b_ready)
    );

endmodule

`default_nettype wire
