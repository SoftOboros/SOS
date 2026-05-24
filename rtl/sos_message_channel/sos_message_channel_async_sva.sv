// ----------------------------------------------------------------------------
// sos_message_channel_async_sva.sv
//
// @spec docs/concepts/SOS-08-B-CONCEPTS.md §6.5 (service-level SVA props,
//             CDC variant)
//       docs/concepts/SOS-08-B-CONCEPTS.md §7  (INV-S-HDL-B-3 — every L1
//             service ships with a service-level SVA bind file)
//       docs/concepts/SOS-08-B-CONCEPTS.md §15 — 2026-05-24 amendment
//             ratifying the async sibling variant.
//       docs/concepts/SOS-08-A-CONCEPTS.md §6.1 (L0 SVA inherited via bind;
//             sos_fifo_async_sva covers the CDC pointer-crossing properties)
//
// Cross-phase / sub-phase / service / primitive invariants cited:
//   INV-SOS-A..H, INV-S-HDL-1..5, INV-S-HDL-B-1..5, INV-S-HDL-A-1..5
//
// Service-level SVA module for sos_message_channel_async. Bound via the
// bind directive in
// tb/sos_message_channel/sos_message_channel_async_bind.sv during cocotb
// simulation runs. Sibling of sos_message_channel_sva but split across
// the two clock domains: producer-side properties clocked on wr_clk;
// consumer-side properties clocked on rd_clk. The inner sos_fifo_async's
// own SVA (sos_fifo_async_sva) covers the CDC handshake atomicity and
// gray-code wraparound properties.
//
// Per PCDN-005 and INV-S-HDL-B-5, SVA-MSGCH-4 (event_id within
// ExternalEventName enum) is NOT asserted here — that property requires
// chart-vocabulary knowledge which the L1 service is by design ignorant of.
// ----------------------------------------------------------------------------

`default_nettype none

module sos_message_channel_async_sva #(
    parameter int EVENT_ID_WIDTH = 0,
    parameter int PAYLOAD_WIDTH  = 0,
    parameter int DEPTH          = 0,
    parameter int READ_LATENCY   = 0,
    parameter bit RESET_MEM      = 1'b0,
    parameter int SYNC_STAGES    = 2,
    parameter int TDATA_WIDTH    = EVENT_ID_WIDTH + PAYLOAD_WIDTH,
    parameter int CNT_W          = $clog2(DEPTH + 1)
) (
    // Write (producer) domain.
    input wire                          wr_clk,
    input wire                          wr_rst,
    input wire [TDATA_WIDTH-1:0]        s_axis_tdata,
    input wire [EVENT_ID_WIDTH-1:0]     s_axis_tevent_id,
    input wire [PAYLOAD_WIDTH-1:0]      s_axis_tpayload,
    input wire                          s_axis_tvalid,
    input wire                          s_axis_tready,
    input wire                          wr_full,
    input wire [CNT_W-1:0]              wr_count,

    // Read (consumer) domain.
    input wire                          rd_clk,
    input wire                          rd_rst,
    input wire [TDATA_WIDTH-1:0]        m_axis_tdata,
    input wire [EVENT_ID_WIDTH-1:0]     m_axis_tevent_id,
    input wire [PAYLOAD_WIDTH-1:0]      m_axis_tpayload,
    input wire                          m_axis_tvalid,
    input wire                          m_axis_tready,
    input wire                          rd_empty,
    input wire [CNT_W-1:0]              rd_count
);

    // ------------------------------------------------------------------------
    // SVA §6.5 #1 — pack/unpack consistency on the MASTER side
    // (consumer domain).
    //
    // The L1 service guarantees the sideband mirrors the packed bus on the
    // master side. Combinational equality (no clock-edge delay) because the
    // unpack is a continuous assignment in the wrapper.
    // ------------------------------------------------------------------------
    property p_master_pack_consistency;
        @(posedge rd_clk) disable iff (rd_rst)
            m_axis_tvalid |->
                (m_axis_tdata ==
                    { m_axis_tevent_id, m_axis_tpayload });
    endproperty
    a_master_pack_consistency: assert property (p_master_pack_consistency)
        else $error("sos_message_channel_async_sva: master tdata != {tevent_id, tpayload}");

    // ------------------------------------------------------------------------
    // SVA §6.5 #2 — handshake stability on the slave side (producer domain).
    //
    // AXI-Stream: once s_axis_tvalid is asserted, neither tvalid nor the
    // data lanes (tdata + sideband) may change until the FIFO accepts the
    // transfer (s_axis_tready). Clocked on wr_clk (the producer domain).
    // ------------------------------------------------------------------------
    property p_slave_tvalid_stable;
        @(posedge wr_clk) disable iff (wr_rst)
            (s_axis_tvalid && !s_axis_tready) |=> s_axis_tvalid;
    endproperty
    a_slave_tvalid_stable: assert property (p_slave_tvalid_stable)
        else $error("sos_message_channel_async_sva: slave tvalid dropped without accept");

    property p_slave_event_id_stable;
        @(posedge wr_clk) disable iff (wr_rst)
            (s_axis_tvalid && !s_axis_tready) |=> $stable(s_axis_tevent_id);
    endproperty
    a_slave_event_id_stable: assert property (p_slave_event_id_stable)
        else $error("sos_message_channel_async_sva: slave tevent_id changed while waiting tready");

    property p_slave_payload_stable;
        @(posedge wr_clk) disable iff (wr_rst)
            (s_axis_tvalid && !s_axis_tready) |=> $stable(s_axis_tpayload);
    endproperty
    a_slave_payload_stable: assert property (p_slave_payload_stable)
        else $error("sos_message_channel_async_sva: slave tpayload changed while waiting tready");

    // ------------------------------------------------------------------------
    // SVA §6.5 #3 — master-side data stability (FWFT mode only).
    //
    // Mirrors sos_fifo_async_sva's master-side tdata stability for the
    // sideband. In READ_LATENCY=1 (registered) mode the property holds by
    // RTL construction.
    // ------------------------------------------------------------------------
    generate
        if (READ_LATENCY == 0) begin : g_sva_master_sideband_stable_fwft
            property p_master_event_id_stable;
                @(posedge rd_clk) disable iff (rd_rst)
                    (m_axis_tvalid && !m_axis_tready) |=>
                        $stable(m_axis_tevent_id);
            endproperty
            a_master_event_id_stable: assert property (p_master_event_id_stable)
                else $error("sos_message_channel_async_sva: master tevent_id changed while !tready (FWFT)");

            property p_master_payload_stable;
                @(posedge rd_clk) disable iff (rd_rst)
                    (m_axis_tvalid && !m_axis_tready) |=>
                        $stable(m_axis_tpayload);
            endproperty
            a_master_payload_stable: assert property (p_master_payload_stable)
                else $error("sos_message_channel_async_sva: master tpayload changed while !tready (FWFT)");
        end
        // READ_LATENCY != 0: registered output, property holds by
        // construction — VERIFIED_BY_ELAB.
    endgenerate

    // ------------------------------------------------------------------------
    // SVA §6.5 #4 — reset clears the channel (per-domain).
    //
    // The CDC variant resets each side independently. wr_rst clears wr_full
    // + wr_count on its domain; rd_rst clears rd_empty (asserts it) +
    // rd_count on its domain. Restated here so failure-message rendering
    // cites sos_message_channel_async vocabulary.
    // ------------------------------------------------------------------------
    property p_wr_reset_clears_count;
        @(posedge wr_clk) wr_rst |=> (wr_count == CNT_W'(0));
    endproperty
    a_wr_reset_clears_count: assert property (p_wr_reset_clears_count)
        else $error("sos_message_channel_async_sva: wr_count not cleared on wr_rst");

    property p_wr_reset_clears_full;
        @(posedge wr_clk) wr_rst |=> (wr_full == 1'b0);
    endproperty
    a_wr_reset_clears_full: assert property (p_wr_reset_clears_full)
        else $error("sos_message_channel_async_sva: wr_full not cleared on wr_rst");

    property p_rd_reset_sets_empty;
        @(posedge rd_clk) rd_rst |=> (rd_empty == 1'b1);
    endproperty
    a_rd_reset_sets_empty: assert property (p_rd_reset_sets_empty)
        else $error("sos_message_channel_async_sva: rd_empty not asserted on rd_rst");

    property p_rd_reset_clears_count;
        @(posedge rd_clk) rd_rst |=> (rd_count == CNT_W'(0));
    endproperty
    a_rd_reset_clears_count: assert property (p_rd_reset_clears_count)
        else $error("sos_message_channel_async_sva: rd_count not cleared on rd_rst");

    // ------------------------------------------------------------------------
    // SVA §6.5 #5 — no-loss-on-full (CDC form).
    //
    // The handshake check is on the wr-clocked side. If the producer
    // attempts a transfer while the FIFO reports wr_full, the FIFO MUST
    // NOT accept (tready must be low — sos_fifo_async_sva asserts this).
    // ------------------------------------------------------------------------
    property p_no_send_when_full;
        @(posedge wr_clk) disable iff (wr_rst)
            !(s_axis_tvalid && s_axis_tready && wr_full);
    endproperty
    a_no_send_when_full: assert property (p_no_send_when_full)
        else $error("sos_message_channel_async_sva: send handshake while wr_full");

    // ------------------------------------------------------------------------
    // VERIFIED_BY_ELAB notes (no runtime assertions emitted):
    //
    //   - SVA-MSGCH-1 (CDC atomicity): inherited from sos_fifo_async — the
    //     CDC handshake delivers the packed word as a single FIFO entry,
    //     so {event_id, payload} arrives atomically by L0 construction.
    //
    //   - SVA-MSGCH-2 (ordering preserved across CDC): inherited from
    //     sos_fifo_async's FIFO-ordering construction + bound SVA
    //     `p_count_delta_bounded` per domain.
    //
    //   - SVA-MSGCH-4 (event_id within ExternalEventName enum): NOT a
    //     SOS-08-B obligation per PCDN-005. SOS-08-C MAY layer a wrapping
    //     SVA module that asserts enum membership.
    //
    //   - SVA-MSGCH-5 (bounded latency): informative, not formally proved.
    //     The CDC handshake's worst-case latency is documented per
    //     sos_fifo_async/MTBF.md.
    // ------------------------------------------------------------------------

endmodule

`default_nettype wire
