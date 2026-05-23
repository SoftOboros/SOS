// =============================================================================
// examples/sos_mailbox/instantiate.sv
//
// Minimal SystemVerilog-2017 instantiation example for sos_mailbox.
//
// Parameters per the task brief:
//   NUM_PRIO              = 8
//   DEPTH                 = 16
//   WIDTH                 = 32
//   READ_LATENCY          = 0  (FWFT)
//   RESET_MEM             = 0  (legacy: mem retained across reset)
//   AGING_ENABLE          = 1  (starved low lanes promote)
//   AGING_THRESHOLD       = 128
//   GRANT_LATENCY_CYCLES  = 1  (canonical registered grant)
//
// @spec docs/concepts/SOS-08-B-CONCEPTS.md §6.1 (instantiation surface)
//       docs/concepts/SOS-08-B-CONCEPTS.md §15  (2026-05-23 ratification:
//                                               PCDN-SOS-08-B-001 NUM_PRIO
//                                               default 8; PCDN-SOS-08-B-006
//                                               level-sensitive irq_non_empty)
//       docs/concepts/SOS-08-A-CONCEPTS.md §6.2, §6.4 (composed L0 contracts)
//
// Cited invariants:
//   INV-SOS-A, INV-SOS-E                                  (SOS-07 §6)
//   INV-S-HDL-1, INV-S-HDL-4, INV-S-HDL-5                 (SOS-08 §7)
//   INV-S-HDL-A-1, INV-S-HDL-A-3, INV-S-HDL-A-4,          (SOS-08-A §7)
//   INV-S-HDL-A-5
//   INV-S-HDL-B-1, INV-S-HDL-B-2, INV-S-HDL-B-3,          (SOS-08-B §7)
//   INV-S-HDL-B-4, INV-S-HDL-B-5
//
// $clog2(8) = 3 so s_axis_tprio / m_axis_tprio are 3-bit sidebands.
// $clog2(16+1) = 5 (lane-level count width; not exposed at the L1 surface
// but the FIFOs report it internally per the composed L0 contract).
// =============================================================================

`default_nettype none

module sos_mailbox_example (
    input  wire        clk,
    input  wire        rst,

    // Producer surface.
    input  wire [31:0] in_msg,
    input  wire [2:0]  in_prio,         // $clog2(8) = 3
    input  wire        in_valid,
    output wire        in_ready,

    // Consumer surface.
    output wire [31:0] out_msg,
    output wire [2:0]  out_prio,
    output wire        out_valid,
    input  wire        out_ready,

    // Level-sensitive IRQ.
    output wire        irq
);

  sos_mailbox #(
      // Per PCDN-SOS-08-B-001: default NUM_PRIO = 8 (matches chart MAX_PRIO).
      .NUM_PRIO             (8),
      // INV-S-HDL-A-5: every other generic supplied explicitly (no defaults).
      .DEPTH                (16),
      .WIDTH                (32),
      .READ_LATENCY         (0),
      .RESET_MEM            (1'b0),
      .AGING_ENABLE         (1),
      .AGING_THRESHOLD      (128),
      .GRANT_LATENCY_CYCLES (1)
  ) u_mailbox (
      .clk            (clk),
      .rst            (rst),

      .s_axis_tdata   (in_msg),
      .s_axis_tprio   (in_prio),
      .s_axis_tvalid  (in_valid),
      .s_axis_tready  (in_ready),

      .m_axis_tdata   (out_msg),
      .m_axis_tprio   (out_prio),
      .m_axis_tvalid  (out_valid),
      .m_axis_tready  (out_ready),

      .irq_non_empty  (irq)
  );

endmodule : sos_mailbox_example

`default_nettype wire
