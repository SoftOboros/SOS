// ----------------------------------------------------------------------------
// sos_message_channel_async.sv
//
// @spec docs/concepts/SOS-08-B-CONCEPTS.md §6.5 (sos_message_channel contract;
//             the §6.5 interface signature documents the async/CDC form with
//             clk_tx / clk_rx ports — this module realises it)
//       docs/concepts/SOS-08-B-CONCEPTS.md §15 — 2026-05-24 amendment: TWO
//             sibling variants (`sos_message_channel` single-clock baseline +
//             `sos_message_channel_async` CDC variant). SOS-08-C selects
//             between them based on producer / consumer clock-domain
//             alignment.
//       docs/concepts/SOS-08-A-CONCEPTS.md §6.1 (composed sos_fifo_async L0)
//
// Cross-phase invariants (cited, not redefined):
//   INV-SOS-A  chart-as-source
//   INV-SOS-B  vectors-as-deliverable at every layer
//   INV-SOS-C  bootstrap-vs-general framing
//   INV-SOS-D  verified-codegen position
//   INV-SOS-E  authority relationships
//   INV-SOS-F  iState authoring surface
//   INV-SOS-G  bounded-reachability discharge
//   INV-SOS-H  vector-to-chart traceability
//
// Cross-sub-phase invariants (SOS-08 §7, cited):
//   INV-S-HDL-1  handshake-compatible ports (per-side; tx + rx)
//   INV-S-HDL-2  static-allocation discipline
//   INV-S-HDL-3  cross-domain isolation — APPLIES; the inner sos_fifo_async
//                handles all gray-code pointer crossings + SYNC_STAGES flop
//                synchronizers. MTBF sign-off at sos_fifo_async/MTBF.md
//                covers this module by composition (INV-S-HDL-B-4).
//   INV-S-HDL-4  cooperative-only at v1
//   INV-S-HDL-5  vector-to-chart traceability for HDL
//
// Cross-service invariants (SOS-08-B §7, cited):
//   INV-S-HDL-B-1  vocabulary mirror discipline (send / receive verbs)
//   INV-S-HDL-B-2  L0 non-modification (sos_fifo_async accepted as-is)
//   INV-S-HDL-B-3  service-level SVA on every L1 instance
//   INV-S-HDL-B-4  vendor-IP pass-through (inherited from sos_fifo_async)
//   INV-S-HDL-B-5  chart-vocabulary failure rendering
//
// Cross-primitive invariants (SOS-08-A §7, cited):
//   INV-S-HDL-A-1  uniform sync active-high reset + AXI-Stream port naming
//                  (per-side: wr_rst sync-to-wr_clk; rd_rst sync-to-rd_clk)
//   INV-S-HDL-A-2  handshake-port composition is associative
//   INV-S-HDL-A-3  vendor-IP shim wrapper is byte-identical
//   INV-S-HDL-A-4  one-hot internal FSM by default (no internal FSM here)
//   INV-S-HDL-A-5  mandatory parameters have no defaults (SYNC_STAGES is the
//                  documented exception — default 2, well-trodden)
//
// L1 service (CDC variant): chart-event-shape-aware message channel that
// crosses a clock-domain boundary. Composes ONE sos_fifo_async carrying
// messages of shape {event_id, packed_payload}. Naming convention parallels
// the SOS-08-B §6.5 interface signature: the spec uses clk_tx/clk_rx; we use
// the AXI-Stream-conventional wr_clk/rd_clk (matching the inner FIFO) to
// avoid mixing naming conventions across the L1↔L0 boundary. The
// chart-emitter (SOS-08-C) wires producer regions' clk to wr_clk and
// consumer regions' clk to rd_clk; PCDN-SOS-08-C-002 retain_synchronizers
// applies regardless of --verified-strip.
// ----------------------------------------------------------------------------

`default_nettype none

module sos_message_channel_async #(
    // INV-S-HDL-A-5: mandatory parameters, no defaults.
    parameter int EVENT_ID_WIDTH,
    parameter int PAYLOAD_WIDTH,
    // DEPTH MUST be a power of two AND >= 4 (inherited from sos_fifo_async's
    // gray-coded pointer constraint; elaboration-time $fatal otherwise).
    parameter int DEPTH,
    // READ_LATENCY: 0 = FWFT, 1 = registered. Forwarded to sos_fifo_async.
    parameter int READ_LATENCY,
    // RESET_MEM: 0 = mem retained on wr_rst; 1 = mem cleared. Per
    // sos_fifo_async's PCDN-A-fifo-RESET_MEM. RESET_MEM clears only on
    // wr_rst (writer owns the storage).
    parameter bit RESET_MEM,
    // SYNC_STAGES: CDC depth on the gray-code pointer crossings. Default
    // 2 is well-trodden; larger raises MTBF for higher-frequency designs.
    parameter int SYNC_STAGES = 2,
    // Derived widths — not user-facing.
    parameter int TDATA_WIDTH = EVENT_ID_WIDTH + PAYLOAD_WIDTH,
    parameter int CNT_W       = $clog2(DEPTH + 1)
) (
    // -- Write (producer) domain --------------------------------------
    // INV-S-HDL-A-1: sync active-high reset.
    input  wire                          wr_clk,
    input  wire                          wr_rst,

    // Slave AXI-Stream ingress (producer → service). Two parallel
    // representations; the chart-emitter (SOS-08-C) drives one and
    // ties the other off via OR-combine convention.
    input  wire [TDATA_WIDTH-1:0]        s_axis_tdata,
    input  wire [EVENT_ID_WIDTH-1:0]     s_axis_tevent_id,
    input  wire [PAYLOAD_WIDTH-1:0]      s_axis_tpayload,
    input  wire                          s_axis_tvalid,
    output wire                          s_axis_tready,

    // Write-side observability (bare names — not handshake-faced).
    output wire                          wr_full,
    output wire [CNT_W-1:0]              wr_count,

    // -- Read (consumer) domain ---------------------------------------
    input  wire                          rd_clk,
    input  wire                          rd_rst,

    // Master AXI-Stream egress (service → consumer). Both the packed bus
    // and the decomposed sideband are driven from the same FIFO output
    // word.
    output wire [TDATA_WIDTH-1:0]        m_axis_tdata,
    output wire [EVENT_ID_WIDTH-1:0]     m_axis_tevent_id,
    output wire [PAYLOAD_WIDTH-1:0]      m_axis_tpayload,
    output wire                          m_axis_tvalid,
    input  wire                          m_axis_tready,

    // Read-side observability.
    output wire                          rd_empty,
    output wire [CNT_W-1:0]              rd_count
);

    // ------------------------------------------------------------------------
    // Producer-side pack — identical convention to the sync sibling. The
    // OR-combine accepts either the packed-bus producer representation OR
    // the decomposed sideband; the chart-emitter ties off whichever it does
    // not drive. event_id occupies the high bits, payload the low bits
    // (canonical {tag, value} for tagged-union encoding).
    // ------------------------------------------------------------------------
    wire [TDATA_WIDTH-1:0] fifo_in_tdata;
    assign fifo_in_tdata =
        s_axis_tdata | { s_axis_tevent_id, s_axis_tpayload };

    // ------------------------------------------------------------------------
    // Consumer-side unpack — identical convention to the sync sibling.
    // ------------------------------------------------------------------------
    wire [TDATA_WIDTH-1:0] fifo_out_tdata;
    assign m_axis_tdata     = fifo_out_tdata;
    assign m_axis_tevent_id = fifo_out_tdata[TDATA_WIDTH-1 -: EVENT_ID_WIDTH];
    assign m_axis_tpayload  = fifo_out_tdata[PAYLOAD_WIDTH-1:0];

    // ------------------------------------------------------------------------
    // L0 composition (INV-S-HDL-B-2 — no L0 modification): a single
    // sos_fifo_async carries the {event_id, payload} packed word across the
    // wr_clk → rd_clk boundary. The L1 inherits the L0's CDC-handshake
    // properties transparently (gray-coded pointer crossings, SYNC_STAGES
    // flop synchronizers, atomic packed-word delivery). The L1-level claims
    // layered on top (chart-vocabulary failure rendering, pack/unpack
    // consistency at each side) live in sos_message_channel_async_sva.sv.
    // ------------------------------------------------------------------------
    sos_fifo_async #(
        .DEPTH        (DEPTH),
        .WIDTH        (TDATA_WIDTH),
        .READ_LATENCY (READ_LATENCY),
        .RESET_MEM    (RESET_MEM),
        .SYNC_STAGES  (SYNC_STAGES)
    ) u_fifo (
        .wr_clk         (wr_clk),
        .wr_rst         (wr_rst),
        .s_axis_tdata   (fifo_in_tdata),
        .s_axis_tvalid  (s_axis_tvalid),
        .s_axis_tready  (s_axis_tready),
        .wr_full        (wr_full),
        .wr_count       (wr_count),

        .rd_clk         (rd_clk),
        .rd_rst         (rd_rst),
        .m_axis_tdata   (fifo_out_tdata),
        .m_axis_tvalid  (m_axis_tvalid),
        .m_axis_tready  (m_axis_tready),
        .rd_empty       (rd_empty),
        .rd_count       (rd_count)
    );

endmodule

`default_nettype wire
