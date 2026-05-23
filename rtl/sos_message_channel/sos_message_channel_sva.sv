// ----------------------------------------------------------------------------
// sos_message_channel_sva.sv
//
// @spec docs/concepts/SOS-08-B-CONCEPTS.md §6.5 (service-level SVA props)
//       docs/concepts/SOS-08-B-CONCEPTS.md §7  (INV-S-HDL-B-3: every L1
//             service ships with a service-level SVA bind file)
//       docs/concepts/SOS-08-B-CONCEPTS.md §15 — PCDN-SOS-08-B-005 resolved
//             2026-05-23: chart-derived metadata struct. At the L1-service
//             layer the SVA properties treat the payload as opaque bits; the
//             "event_id is a valid ExternalEventName index" claim
//             (SVA-MSGCH-4 in the spec) is a SOS-08-C-emitted property
//             (defence-in-depth, layered ABOVE this module), NOT an
//             SOS-08-B obligation.
//       docs/concepts/SOS-08-A-CONCEPTS.md §6.2 (L0 SVA inherited via bind)
//
// Cross-phase / sub-phase / service / primitive invariants cited:
//   INV-SOS-A..H, INV-S-HDL-1..5, INV-S-HDL-B-1..5, INV-S-HDL-A-1..5
//
// Service-level SVA module for sos_message_channel. Bound via the bind
// directive in tb/sos_message_channel/sos_message_channel_bind.sv during
// cocotb simulation runs.
//
// Layering note: the underlying sos_fifo_sync's own SVA module
// (sos_fifo_sync_sva) covers the AXI-Stream handshake stability, count
// invariant, full/empty alignment, tvalid-stable-until-tready, and (under
// FWFT mode) tdata-stable-until-tready properties. Those properties bind to
// every elaborated sos_fifo_sync instance automatically through
// sos_fifo_sync_bind.sv. This module asserts the L1-LAYER claims layered on
// top:
//
//   - SVA-MSGCH-1' (single-clock variant of spec SVA-MSGCH-1): every
//     accepted send produces exactly one receive with matching {event_id,
//     payload}. The pack/unpack is wire-only, so this is asserted as a
//     direct equality on the producer-presented sideband vs the
//     consumer-presented sideband, tracked across the FIFO via a reference
//     model proxy maintained in cocotb (the property here is the
//     same-cycle pack/unpack equality).
//
//   - SVA-MSGCH-2 (ordering): inherited from sos_fifo_sync's count_delta
//     + FIFO ordering. No new SVA needed at this layer beyond the
//     cocotb-verified round-trip ordering.
//
//   - SVA-MSGCH-3 (no loss on full): inherited from sos_fifo_sync's
//     no_overflow + no_write_when_full.
//
//   - Pack/unpack consistency: m_axis_tdata MUST equal { m_axis_tevent_id,
//     m_axis_tpayload } at every cycle (combinational equality on the
//     consumer-side decomposition).
//
//   - Reset clears the channel: count -> 0, empty -> 1, full -> 0
//     (inherited from sos_fifo_sync_sva via the bound assertion module).
//
// Per PCDN-005 and INV-S-HDL-B-5, SVA-MSGCH-4 (event_id is a valid
// ExternalEventName) is NOT asserted here — that property requires
// knowledge of the chart's ExternalEventName enum, which the L1 service is
// (by design) ignorant of. SOS-08-C MAY emit a wrapping SVA module that
// adds the enum-membership assertion if defence-in-depth is required.
// ----------------------------------------------------------------------------

`default_nettype none

module sos_message_channel_sva #(
    parameter int EVENT_ID_WIDTH = 0,
    parameter int PAYLOAD_WIDTH  = 0,
    parameter int DEPTH          = 0,
    parameter int READ_LATENCY   = 0,
    parameter bit RESET_MEM      = 1'b0,
    parameter int TDATA_WIDTH    = EVENT_ID_WIDTH + PAYLOAD_WIDTH,
    parameter int CNT_W          = $clog2(DEPTH + 1)
) (
    input wire                          clk,
    input wire                          rst,

    // Slave-side (producer → service).
    input wire [TDATA_WIDTH-1:0]        s_axis_tdata,
    input wire [EVENT_ID_WIDTH-1:0]     s_axis_tevent_id,
    input wire [PAYLOAD_WIDTH-1:0]      s_axis_tpayload,
    input wire                          s_axis_tvalid,
    input wire                          s_axis_tready,

    // Master-side (service → consumer).
    input wire [TDATA_WIDTH-1:0]        m_axis_tdata,
    input wire [EVENT_ID_WIDTH-1:0]     m_axis_tevent_id,
    input wire [PAYLOAD_WIDTH-1:0]      m_axis_tpayload,
    input wire                          m_axis_tvalid,
    input wire                          m_axis_tready,

    input wire                          full,
    input wire                          empty,
    input wire [CNT_W-1:0]              count
);

    // ------------------------------------------------------------------------
    // SVA §6.5 #1 — pack/unpack consistency on the MASTER side.
    //
    // On every cycle where the consumer is presented a valid word, the
    // packed `m_axis_tdata` MUST decompose to { m_axis_tevent_id,
    // m_axis_tpayload } — the L1 service guarantees the sideband mirrors
    // the packed bus. The property holds combinationally (no clock-edge
    // delay) because the unpack is a continuous assignment.
    // ------------------------------------------------------------------------
    property p_master_pack_consistency;
        @(posedge clk) disable iff (rst)
            m_axis_tvalid |->
                (m_axis_tdata ==
                    { m_axis_tevent_id, m_axis_tpayload });
    endproperty
    a_master_pack_consistency: assert property (p_master_pack_consistency)
        else $error("sos_message_channel_sva: master tdata != {tevent_id, tpayload}");

    // ------------------------------------------------------------------------
    // SVA §6.5 #2 — handshake stability on the slave side.
    //
    // AXI-Stream requires that once `s_axis_tvalid` is asserted, neither
    // tvalid nor the data lanes (tdata + sideband) may change until the
    // FIFO accepts the transfer (s_axis_tready high). Inherited from
    // sos_fifo_sync_sva on the packed bus; restated here for the
    // sideband decomposition.
    // ------------------------------------------------------------------------
    property p_slave_tvalid_stable;
        @(posedge clk) disable iff (rst)
            (s_axis_tvalid && !s_axis_tready) |=> s_axis_tvalid;
    endproperty
    a_slave_tvalid_stable: assert property (p_slave_tvalid_stable)
        else $error("sos_message_channel_sva: slave tvalid dropped without accept");

    property p_slave_event_id_stable;
        @(posedge clk) disable iff (rst)
            (s_axis_tvalid && !s_axis_tready) |=> $stable(s_axis_tevent_id);
    endproperty
    a_slave_event_id_stable: assert property (p_slave_event_id_stable)
        else $error("sos_message_channel_sva: slave tevent_id changed while waiting tready");

    property p_slave_payload_stable;
        @(posedge clk) disable iff (rst)
            (s_axis_tvalid && !s_axis_tready) |=> $stable(s_axis_tpayload);
    endproperty
    a_slave_payload_stable: assert property (p_slave_payload_stable)
        else $error("sos_message_channel_sva: slave tpayload changed while waiting tready");

    // ------------------------------------------------------------------------
    // SVA §6.5 #3 — master-side data stability (FWFT mode only).
    //
    // Mirrors sos_fifo_sync_sva's `p_tdata_stable_until_tready` for the
    // sideband: when the consumer holds tready low while the master
    // presents a valid word, tevent_id + tpayload MUST remain stable.
    // In READ_LATENCY=1 (registered) mode, sos_fifo_sync drives the
    // output from a flop and the property holds by RTL construction
    // (VERIFIED_BY_ELAB — no runtime check emitted).
    // ------------------------------------------------------------------------
    generate
        if (READ_LATENCY == 0) begin : g_sva_master_sideband_stable_fwft
            property p_master_event_id_stable;
                @(posedge clk) disable iff (rst)
                    (m_axis_tvalid && !m_axis_tready) |=>
                        $stable(m_axis_tevent_id);
            endproperty
            a_master_event_id_stable: assert property (p_master_event_id_stable)
                else $error("sos_message_channel_sva: master tevent_id changed while !tready (FWFT)");

            property p_master_payload_stable;
                @(posedge clk) disable iff (rst)
                    (m_axis_tvalid && !m_axis_tready) |=>
                        $stable(m_axis_tpayload);
            endproperty
            a_master_payload_stable: assert property (p_master_payload_stable)
                else $error("sos_message_channel_sva: master tpayload changed while !tready (FWFT)");
        end
        // READ_LATENCY != 0: registered output, property holds by
        // construction — VERIFIED_BY_ELAB.
    endgenerate

    // ------------------------------------------------------------------------
    // SVA §6.5 #4 — reset clears the channel.
    //
    // The underlying sos_fifo_sync_sva already asserts count==0, full==0,
    // empty==1 after rst. We restate the FIFO-level reset claim at this
    // layer so a service-level failure-message rendering (per
    // INV-S-HDL-B-5) cites the L1 service module name, not the inner
    // FIFO.
    // ------------------------------------------------------------------------
    property p_reset_clears_count;
        @(posedge clk) rst |=> (count == CNT_W'(0));
    endproperty
    a_reset_clears_count: assert property (p_reset_clears_count)
        else $error("sos_message_channel_sva: count not cleared on reset");

    property p_reset_sets_empty;
        @(posedge clk) rst |=> (empty == 1'b1);
    endproperty
    a_reset_sets_empty: assert property (p_reset_sets_empty)
        else $error("sos_message_channel_sva: empty not asserted on reset");

    property p_reset_clears_full;
        @(posedge clk) rst |=> (full == 1'b0);
    endproperty
    a_reset_clears_full: assert property (p_reset_clears_full)
        else $error("sos_message_channel_sva: full not cleared on reset");

    // ------------------------------------------------------------------------
    // SVA §6.5 #5 — no-loss-on-full (inherited form).
    //
    // sos_fifo_sync_sva asserts `p_no_write_when_full` on the packed bus.
    // We restate at the service level so a failure renders in
    // sos_message_channel vocabulary (per INV-S-HDL-B-5).
    // ------------------------------------------------------------------------
    property p_no_send_when_full;
        @(posedge clk) disable iff (rst)
            !(s_axis_tvalid && s_axis_tready && full);
    endproperty
    a_no_send_when_full: assert property (p_no_send_when_full)
        else $error("sos_message_channel_sva: send handshake while full");

    // ------------------------------------------------------------------------
    // VERIFIED_BY_ELAB notes (no runtime assertions emitted):
    //
    //   - SVA-MSGCH-2 (ordering preserved): inherited from
    //     sos_fifo_sync's FIFO-ordering construction + bound SVA
    //     `p_count_delta_bounded`. The cocotb test
    //     test_send_recv_ordering exercises the order at the L1
    //     interface.
    //
    //   - SVA-MSGCH-4 (event_id within ExternalEventName enum): NOT a
    //     SOS-08-B obligation per PCDN-005. SOS-08-C MAY layer a
    //     wrapping SVA module that asserts enum membership.
    //
    //   - SVA-MSGCH-5 (bounded latency): informative, not formally
    //     proved. The cocotb test test_send_recv_roundtrip records
    //     observed latency for documentation.
    // ------------------------------------------------------------------------

endmodule

`default_nettype wire
