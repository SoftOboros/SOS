// ----------------------------------------------------------------------------
// SIS-08B first hardware slice integration top.
//
// Composes the C1 RTL primitives named by SIS-08A:
//   - sos_fifo_sync        (memory-mapped FIFO DATA/STATUS/CONTROL surface)
//   - sos_mailbox          (register-backed notification surface)
//   - sos_credit_counter   (first simple bandwidth / arbitration budget)
//
// The SOS-09-A chart in charts/sis08_first_slice owns the descriptor surface;
// this module is the cocotb DUT that proves the selected RTL primitives can
// be driven together in the first pure-sim slice.
// ----------------------------------------------------------------------------

`default_nettype none

module sis08_first_slice_top (
    input  wire        clk,
    input  wire        rst,

    input  wire [31:0] fifo_s_tdata,
    input  wire        fifo_s_tvalid,
    output wire        fifo_s_tready,
    output wire [31:0] fifo_m_tdata,
    output wire        fifo_m_tvalid,
    input  wire        fifo_m_tready,
    output wire        fifo_full,
    output wire        fifo_empty,
    output wire [2:0]  fifo_count,

    input  wire [31:0] mailbox_s_tdata,
    input  wire        mailbox_s_tprio,
    input  wire        mailbox_s_tvalid,
    output wire        mailbox_s_tready,
    output wire [31:0] mailbox_m_tdata,
    output wire        mailbox_m_tprio,
    output wire        mailbox_m_tvalid,
    input  wire        mailbox_m_tready,
    output wire        mailbox_irq_non_empty,

    input  wire        credit_acquire_req,
    output wire        credit_acquire_ack,
    input  wire        credit_release_req,
    output wire [2:0]  credit_credits
);

    sos_fifo_sync #(
        .DEPTH(4),
        .WIDTH(32),
        .READ_LATENCY(0),
        .RESET_MEM(1)
    ) u_fifo (
        .clk(clk),
        .rst(rst),
        .s_axis_tdata(fifo_s_tdata),
        .s_axis_tvalid(fifo_s_tvalid),
        .s_axis_tready(fifo_s_tready),
        .m_axis_tdata(fifo_m_tdata),
        .m_axis_tvalid(fifo_m_tvalid),
        .m_axis_tready(fifo_m_tready),
        .full(fifo_full),
        .empty(fifo_empty),
        .count(fifo_count)
    );

    sos_mailbox #(
        .NUM_PRIO(2),
        .DEPTH(4),
        .WIDTH(32),
        .READ_LATENCY(0),
        .RESET_MEM(1),
        .AGING_ENABLE(0),
        .AGING_THRESHOLD(8),
        .GRANT_LATENCY_CYCLES(1)
    ) u_mailbox (
        .clk(clk),
        .rst(rst),
        .s_axis_tdata(mailbox_s_tdata),
        .s_axis_tprio(mailbox_s_tprio),
        .s_axis_tvalid(mailbox_s_tvalid),
        .s_axis_tready(mailbox_s_tready),
        .m_axis_tdata(mailbox_m_tdata),
        .m_axis_tprio(mailbox_m_tprio),
        .m_axis_tvalid(mailbox_m_tvalid),
        .m_axis_tready(mailbox_m_tready),
        .irq_non_empty(mailbox_irq_non_empty)
    );

    sos_credit_counter #(
        .INIT_CREDITS(2),
        .MAX_CREDITS(4)
    ) u_credit (
        .clk(clk),
        .rst(rst),
        .acquire_req(credit_acquire_req),
        .acquire_ack(credit_acquire_ack),
        .release_req(credit_release_req),
        .credits(credit_credits)
    );

endmodule

`default_nettype wire
