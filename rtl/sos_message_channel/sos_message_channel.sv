// ----------------------------------------------------------------------------
// sos_message_channel.sv
//
// @spec docs/concepts/SOS-08-B-CONCEPTS.md §6.5 (sos_message_channel contract)
//       docs/concepts/SOS-08-B-CONCEPTS.md §5  (frozen decisions)
//       docs/concepts/SOS-08-B-CONCEPTS.md §7  (cross-service invariants)
//       docs/concepts/SOS-08-B-CONCEPTS.md §15 — PCDN-SOS-08-B-005 resolved
//             2026-05-23: chart-derived metadata struct (one packed-struct
//             variant per ExternalEventName ID, encoded as a tagged union
//             {event_id, packed_payload_variant}). The L1 service itself is
//             structurally uniform; the per-event packed-struct variant
//             interpretation is SOS-08-C's responsibility — this L1 module
//             treats `payload` as opaque bits at the SOS-08-B layer.
//       docs/concepts/SOS-08-A-CONCEPTS.md §6.2 (composed sos_fifo_sync L0)
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
//   INV-S-HDL-1  handshake-compatible ports
//   INV-S-HDL-2  static-allocation discipline
//   INV-S-HDL-3  cross-domain isolation (N/A — this L1 service is the single-
//                clock variant; the async / CDC variant remains a future
//                amendment per §6.5 spec sketch + PCDN-005 §15 amendment)
//   INV-S-HDL-4  cooperative-only at v1
//   INV-S-HDL-5  vector-to-chart traceability for HDL
//
// Cross-service invariants (SOS-08-B §7, cited):
//   INV-S-HDL-B-1  vocabulary mirror discipline (send / receive verbs)
//   INV-S-HDL-B-2  L0 non-modification (sos_fifo_sync accepted as-is)
//   INV-S-HDL-B-3  service-level SVA on every L1 instance
//   INV-S-HDL-B-4  vendor-IP pass-through (inherited from sos_fifo_sync)
//   INV-S-HDL-B-5  chart-vocabulary failure rendering
//
// Cross-primitive invariants (SOS-08-A §7, cited):
//   INV-S-HDL-A-1  uniform sync active-high reset + AXI-Stream port naming
//   INV-S-HDL-A-2  handshake-port composition is associative
//   INV-S-HDL-A-3  vendor-IP shim wrapper is byte-identical
//   INV-S-HDL-A-4  one-hot internal FSM by default
//   INV-S-HDL-A-5  mandatory parameters have no defaults
//
// L1 service: chart-event-shape-aware message channel. Composes ONE
// sos_fifo_sync carrying messages of shape {event_id, packed_payload}.
//
// Per PCDN-SOS-08-B-005 (§15 2026-05-23, user-chosen variant): the
// packed_payload variant is **chart-emitted** at compile time by SOS-08-C as
// a tagged union — one packed-struct variant per ExternalEventName ID. The
// L1 service module itself remains structurally uniform: it carries
// {event_id, opaque_payload[PAYLOAD_WIDTH-1:0]} through a single
// sos_fifo_sync. The per-event interpretation is SOS-08-C's responsibility,
// NOT this module's.
//
// Ports follow the AXI-Stream convention with an additional sideband
// decomposition: the chart-emitted producer / consumer may drive either the
// packed `s_axis_tdata` / `m_axis_tdata` bus OR the decomposed
// `s_axis_tevent_id` + `s_axis_tpayload` sideband (and the consumer side
// receives the same on both representations). The internal mapping is:
//   tdata = { event_id, payload }   (event_id in the high bits, payload low)
// This pack/unpack is a wire-only contract; the underlying sos_fifo_sync
// sees a single WIDTH = EVENT_ID_WIDTH + PAYLOAD_WIDTH bus.
// ----------------------------------------------------------------------------

`default_nettype none

module sos_message_channel #(
    // INV-S-HDL-A-5: mandatory parameters, no defaults.
    // EVENT_ID_WIDTH — bounded by the chart's `ExternalEventName` enum
    // cardinality (typically 8..12 bits). Chart-emission (SOS-08-C) selects
    // the width to fit the active enum.
    parameter int EVENT_ID_WIDTH,
    // PAYLOAD_WIDTH — the max chart-event payload width across all variants
    // of the tagged-union ExternalEventName. Set at chart-compile time by
    // SOS-08-C. The L1 service treats these bits as opaque.
    parameter int PAYLOAD_WIDTH,
    // DEPTH / READ_LATENCY / RESET_MEM — forwarded verbatim to the inner
    // sos_fifo_sync (no default per INV-S-HDL-A-5).
    parameter int DEPTH,
    parameter int READ_LATENCY,
    parameter bit RESET_MEM,
    // Derived width — not user-facing.
    parameter int TDATA_WIDTH = EVENT_ID_WIDTH + PAYLOAD_WIDTH,
    parameter int CNT_W       = $clog2(DEPTH + 1)
) (
    // Clock + sync active-high reset (INV-S-HDL-A-1).
    input  wire                          clk,
    input  wire                          rst,

    // Slave AXI-Stream ingress (producer → service).
    // Producer MAY drive either:
    //   (a) packed `s_axis_tdata = { event_id, payload }`, or
    //   (b) the sideband `s_axis_tevent_id` + `s_axis_tpayload`.
    // The chart-emitted producer wrapper (SOS-08-C) picks one and ties the
    // other off; both must agree on cycles where tvalid is asserted.
    input  wire [TDATA_WIDTH-1:0]        s_axis_tdata,
    input  wire [EVENT_ID_WIDTH-1:0]     s_axis_tevent_id,
    input  wire [PAYLOAD_WIDTH-1:0]      s_axis_tpayload,
    input  wire                          s_axis_tvalid,
    output wire                          s_axis_tready,

    // Master AXI-Stream egress (service → consumer).
    // Both the packed `m_axis_tdata` and the decomposed sideband
    // (`m_axis_tevent_id`, `m_axis_tpayload`) are driven by the same FIFO
    // output word; the consumer MAY read whichever representation is
    // convenient for the chart-emitted decode glue.
    output wire [TDATA_WIDTH-1:0]        m_axis_tdata,
    output wire [EVENT_ID_WIDTH-1:0]     m_axis_tevent_id,
    output wire [PAYLOAD_WIDTH-1:0]      m_axis_tpayload,
    output wire                          m_axis_tvalid,
    input  wire                          m_axis_tready,

    // Observability outputs from the underlying sos_fifo_sync.
    output wire                          full,
    output wire                          empty,
    output wire [CNT_W-1:0]              count
);

    // ------------------------------------------------------------------------
    // Producer-side pack: form the inner sos_fifo_sync tdata bus from either
    // the packed or the sideband producer representation.
    //
    // PCDN-005 leaves the choice of representation to SOS-08-C's chart
    // emitter; this module accepts both. The convention is "OR-combine":
    // whichever representation the producer chose, the other is driven to
    // zero. The internal mapping places event_id in the high bits, payload
    // in the low bits (canonical {tag, value} for tagged-union encoding).
    //
    // Note for SOS-08-C: a strict chart-emitter SHOULD pick exactly one
    // representation per instance and tie the other off explicitly. The
    // OR-combine here exists for ease of integration; it is NOT a
    // recommendation to drive both representations simultaneously.
    // ------------------------------------------------------------------------
    wire [TDATA_WIDTH-1:0] fifo_in_tdata;
    assign fifo_in_tdata =
        s_axis_tdata | { s_axis_tevent_id, s_axis_tpayload };

    // ------------------------------------------------------------------------
    // Consumer-side unpack: split the inner sos_fifo_sync tdata into the
    // decomposed sideband for the chart-emitted decoder, and forward the
    // packed bus verbatim for the packed-representation consumer.
    // ------------------------------------------------------------------------
    wire [TDATA_WIDTH-1:0] fifo_out_tdata;
    assign m_axis_tdata     = fifo_out_tdata;
    assign m_axis_tevent_id = fifo_out_tdata[TDATA_WIDTH-1 -: EVENT_ID_WIDTH];
    assign m_axis_tpayload  = fifo_out_tdata[PAYLOAD_WIDTH-1:0];

    // ------------------------------------------------------------------------
    // L0 composition (INV-S-HDL-B-2 — no L0 modification): a single
    // sos_fifo_sync carries the {event_id, payload} packed word. The L1
    // service inherits all five sos_fifo_sync SVA properties (no_overflow,
    // no_underflow, count_invariant, reset_clears, reset_clears_mem when
    // RESET_MEM=1) transparently — they cover the FIFO-level handshake and
    // the per-bus stability claim. The L1-level claims layered on top
    // (atomic pack/unpack, event_id+payload preserved across the
    // send/receive boundary) are asserted in sos_message_channel_sva.sv.
    // ------------------------------------------------------------------------
    sos_fifo_sync #(
        .DEPTH        (DEPTH),
        .WIDTH        (TDATA_WIDTH),
        .READ_LATENCY (READ_LATENCY),
        .RESET_MEM    (RESET_MEM)
    ) u_fifo (
        .clk            (clk),
        .rst            (rst),

        .s_axis_tdata   (fifo_in_tdata),
        .s_axis_tvalid  (s_axis_tvalid),
        .s_axis_tready  (s_axis_tready),

        .m_axis_tdata   (fifo_out_tdata),
        .m_axis_tvalid  (m_axis_tvalid),
        .m_axis_tready  (m_axis_tready),

        .full           (full),
        .empty          (empty),
        .count          (count)
    );

endmodule

`default_nettype wire
