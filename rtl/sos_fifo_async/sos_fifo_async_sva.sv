// ----------------------------------------------------------------------------
// sos_fifo_async_sva.sv
//
// @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.1 (sos_fifo_async SVA properties)
//       docs/concepts/SOS-08-A-CONCEPTS.md §15  (2026-05-23 ratification +
//                                                impl wave-1 PCDN amendments)
//       docs/concepts/SOS-08-CONCEPTS.md   §5  (frozen decisions inherited)
//       docs/concepts/SOS-07-CONCEPTS.md   §6  (cross-phase invariants)
//       PCDN-A-fifo-READ_LATENCY  resolved 2026-05-23 — tdata-stable
//                                  property is FWFT-mode-only
//       PCDN-A-fifo-RESET_MEM     resolved 2026-05-23 — a_reset_clears_mem
//                                  gated on RESET_MEM == 1; VERIFIED_BY_ELAB
//       PCDN-A-bind-form          resolved 2026-05-23 — module-type bind
//
// Cross-phase invariants (cited, not redefined):
//   INV-SOS-A..H per SOS-07 §6
//
// Cross-sub-phase invariants (SOS-08 §7, cited):
//   INV-S-HDL-1..5 — handshake compat, static alloc, CDC isolation
//                   (INV-S-HDL-3 applies; synchronizer-flop chains are
//                   excluded from formal proof, see MTBF.md), cooperative
//                   v1, vector-to-chart traceability.
//
// Cross-primitive invariants (SOS-08-A §7, cited):
//   INV-S-HDL-A-1..5
//
// SVA properties bound to a sos_fifo_async instance. Bound via the directive
// in tb/sos_fifo_async/sos_fifo_async_bind.sv (module-type bind per
// PCDN-A-bind-form) during cocotb simulation runs.
//
// Properties per SOS-08-A §6.1:
//   Write-side (wr_clk domain):
//     - no_overflow         : never accept a write while full
//     - no_write_when_full  : strict — handshake forbidden when full
//     - wr_ptr_monotonic    : gray code differs by exactly one bit per inc
//     - reset_clears_full   : wr_rst forces wr_full=0
//     - reset_clears_wcount : wr_rst forces wr_count=0
//   Read-side (rd_clk domain):
//     - no_underflow        : never present valid output when empty
//     - no_read_when_empty  : strict — handshake forbidden when empty
//     - rd_ptr_monotonic    : gray code differs by exactly one bit per inc
//     - reset_sets_empty    : rd_rst forces rd_empty=1
//     - reset_clears_rcount : rd_rst forces rd_count=0
//     - tvalid_stable       : AXI-Stream rule — tvalid held until accept
//     - tdata_stable (FWFT only)
//
// INV-S-HDL-3 carve-out: the SYNC_STAGES-deep flop chains that carry
// gray-coded pointers across clock domains are NOT asserted formally.
// MTBF.md is the canonical sign-off for that path.
//
// FIFO ordering is checked at the cocotb level (across-CDC ordering
// claims do not fit cleanly inside an SVA module bound to one of the two
// clocks — the testbench uses an in-flight reference deque instead).
// ----------------------------------------------------------------------------

`default_nettype none

module sos_fifo_async_sva #(
    parameter int DEPTH        = 0,
    parameter int WIDTH        = 0,
    // PCDN-A-fifo-READ_LATENCY / PCDN-A-fifo-RESET_MEM (2026-05-23).
    parameter int READ_LATENCY = 0,
    parameter bit RESET_MEM    = 1'b0,
    parameter int SYNC_STAGES  = 2,
    parameter int CNT_W        = $clog2(DEPTH + 1),
    parameter int PTR_W        = (DEPTH <= 1) ? 1 : $clog2(DEPTH),
    parameter int GPTR_W       = PTR_W + 1
) (
    // -- Write (producer) domain --------------------------------------
    input wire                  wr_clk,
    input wire                  wr_rst,

    input wire [WIDTH-1:0]      s_axis_tdata,
    input wire                  s_axis_tvalid,
    input wire                  s_axis_tready,

    input wire                  wr_full,
    input wire [CNT_W-1:0]      wr_count,

    // -- Read (consumer) domain ---------------------------------------
    input wire                  rd_clk,
    input wire                  rd_rst,

    input wire [WIDTH-1:0]      m_axis_tdata,
    input wire                  m_axis_tvalid,
    input wire                  m_axis_tready,

    input wire                  rd_empty,
    input wire [CNT_W-1:0]      rd_count
);

    // ====================================================================
    // Write-side properties (wr_clk).
    // ====================================================================

    // ------------------------------------------------------------------------
    // §6.1 #1 — no_overflow. tready MUST not fire while full.
    // ------------------------------------------------------------------------
    property p_no_overflow;
        @(posedge wr_clk) disable iff (wr_rst)
            (s_axis_tvalid && wr_full) |-> !s_axis_tready;
    endproperty
    a_no_overflow: assert property (p_no_overflow)
        else $error("sos_fifo_async_sva: overflow — tready asserted while wr_full");

    property p_no_write_when_full;
        @(posedge wr_clk) disable iff (wr_rst)
            !(s_axis_tvalid && s_axis_tready && wr_full);
    endproperty
    a_no_write_when_full: assert property (p_no_write_when_full)
        else $error("sos_fifo_async_sva: write handshake while wr_full");

    // ------------------------------------------------------------------------
    // §6.1 #4 — pointer_monotonicity (write side).
    // Gray-code increments mean exactly one bit toggles per increment.
    // This is VERIFIED_BY_ELAB — see note at the bottom of this file. The
    // gray pointer is internal to the DUT; the assertion module's port list
    // (per INV-S-HDL-A-2) does not include it. The RTL construction
    // (`bin_to_gray(b) = b ^ (b >> 1)` on a monotonic binary counter)
    // guarantees the one-bit-per-increment property by elaboration.
    // ------------------------------------------------------------------------

    // ------------------------------------------------------------------------
    // Reset clears wr-side observability.
    // ------------------------------------------------------------------------
    property p_wr_reset_clears_full;
        @(posedge wr_clk) wr_rst |=> (wr_full == 1'b0);
    endproperty
    a_wr_reset_clears_full: assert property (p_wr_reset_clears_full)
        else $error("sos_fifo_async_sva: wr_full not cleared on wr_rst");

    property p_wr_reset_clears_wcount;
        @(posedge wr_clk) wr_rst |=> (wr_count == CNT_W'(0));
    endproperty
    a_wr_reset_clears_wcount: assert property (p_wr_reset_clears_wcount)
        else $error("sos_fifo_async_sva: wr_count not cleared on wr_rst");

    // ------------------------------------------------------------------------
    // wr_count bounded by [0, DEPTH].
    // ------------------------------------------------------------------------
    property p_wr_count_le_depth;
        @(posedge wr_clk) (wr_count <= CNT_W'(DEPTH));
    endproperty
    a_wr_count_le_depth: assert property (p_wr_count_le_depth)
        else $error("sos_fifo_async_sva: wr_count exceeds DEPTH");

    // ------------------------------------------------------------------------
    // AXI-Stream rule — tvalid stable on the write side input. INV-S-HDL-A-2
    // composition-associativity requires that producers honor the canonical
    // AXI-Stream rule: tvalid MUST NOT drop without a transfer.
    //
    // NOTE: this property checks the *producer* contract (the agent driving
    // s_axis_tvalid). Since the FIFO is the *consumer* of the slave-side
    // AXI-Stream port, this is a "your producer is well-behaved" check —
    // not an obligation the FIFO itself satisfies. We emit it as an
    // ASSUMPTION on the cocotb stimulus, so violations point at the test
    // harness rather than the DUT.
    // ------------------------------------------------------------------------
    property p_s_tvalid_stable_until_tready;
        @(posedge wr_clk) disable iff (wr_rst)
            (s_axis_tvalid && !s_axis_tready) |=> s_axis_tvalid;
    endproperty
    a_s_tvalid_stable_until_tready: assume property (p_s_tvalid_stable_until_tready)
        else $error("sos_fifo_async_sva: producer dropped s_axis_tvalid without a transfer");

    // ====================================================================
    // Read-side properties (rd_clk).
    // ====================================================================

    // ------------------------------------------------------------------------
    // §6.1 #2 — no_underflow.
    // ------------------------------------------------------------------------
    property p_no_underflow;
        @(posedge rd_clk) disable iff (rd_rst)
            (m_axis_tready && rd_empty) |-> !m_axis_tvalid;
    endproperty
    a_no_underflow: assert property (p_no_underflow)
        else $error("sos_fifo_async_sva: underflow — tvalid asserted while rd_empty");

    property p_no_read_when_empty;
        @(posedge rd_clk) disable iff (rd_rst)
            !(m_axis_tvalid && m_axis_tready && rd_empty);
    endproperty
    a_no_read_when_empty: assert property (p_no_read_when_empty)
        else $error("sos_fifo_async_sva: read handshake while rd_empty");

    // ------------------------------------------------------------------------
    // Reset clears rd-side observability.
    // ------------------------------------------------------------------------
    property p_rd_reset_sets_empty;
        @(posedge rd_clk) rd_rst |=> (rd_empty == 1'b1);
    endproperty
    a_rd_reset_sets_empty: assert property (p_rd_reset_sets_empty)
        else $error("sos_fifo_async_sva: rd_empty not asserted on rd_rst");

    property p_rd_reset_clears_rcount;
        @(posedge rd_clk) rd_rst |=> (rd_count == CNT_W'(0));
    endproperty
    a_rd_reset_clears_rcount: assert property (p_rd_reset_clears_rcount)
        else $error("sos_fifo_async_sva: rd_count not cleared on rd_rst");

    // ------------------------------------------------------------------------
    // rd_count bounded by [0, DEPTH].
    // ------------------------------------------------------------------------
    property p_rd_count_le_depth;
        @(posedge rd_clk) (rd_count <= CNT_W'(DEPTH));
    endproperty
    a_rd_count_le_depth: assert property (p_rd_count_le_depth)
        else $error("sos_fifo_async_sva: rd_count exceeds DEPTH");

    // ------------------------------------------------------------------------
    // AXI-Stream rule — tvalid MUST NOT drop without a transfer. This IS the
    // FIFO's contract on the master-side egress (we own m_axis_tvalid).
    // ------------------------------------------------------------------------
    property p_m_tvalid_stable_until_tready;
        @(posedge rd_clk) disable iff (rd_rst)
            (m_axis_tvalid && !m_axis_tready) |=> m_axis_tvalid;
    endproperty
    a_m_tvalid_stable_until_tready: assert property (p_m_tvalid_stable_until_tready)
        else $error("sos_fifo_async_sva: m_axis_tvalid dropped without a transfer");

    // ------------------------------------------------------------------------
    // PCDN-A-fifo-READ_LATENCY — tdata-stable is FWFT-mode-only.
    //
    // Under READ_LATENCY=1 the m_axis_tdata bus is driven from a registered
    // output (rdata_q in sos_fifo_async.sv); the property holds trivially by
    // construction (registered output cannot change without a clock edge
    // that also re-evaluates rd_empty_q).
    // ------------------------------------------------------------------------
    generate
        if (READ_LATENCY == 0) begin : g_sva_tdata_stable_fwft
            property p_m_tdata_stable_until_tready;
                @(posedge rd_clk) disable iff (rd_rst)
                    (m_axis_tvalid && !m_axis_tready) |=> $stable(m_axis_tdata);
            endproperty
            a_m_tdata_stable_until_tready: assert property (p_m_tdata_stable_until_tready)
                else $error("sos_fifo_async_sva: m_axis_tdata changed while tvalid && !tready (FWFT)");
        end
        // READ_LATENCY != 0: stable-tdata is VERIFIED_BY_ELAB — the
        // registered output flop guarantees the property by RTL construction;
        // no runtime assertion is emitted in this mode.
    endgenerate

    // ====================================================================
    // VERIFIED_BY_ELAB notes.
    // ====================================================================
    //
    // a_wr_gray_one_bit_per_inc  (pointer_monotonicity, write side)
    //   RTL site: sos_fifo_async.{vhd,sv} bin_to_gray() function — the
    //   gray code of a unit-step binary counter changes exactly one bit
    //   per step by definition (b ^ (b >> 1)). Property is structural.
    //
    // a_rd_gray_one_bit_per_inc  (pointer_monotonicity, read side)
    //   Same mechanism, applied to rd_ptr.
    //
    // a_reset_clears_mem  (RESET_MEM == 1)
    //   RTL site: sos_fifo_async.sv wr_rst branch, "if (RESET_MEM)" loop.
    //   Mem is internal to the DUT; the assertion module's port list does
    //   not (per INV-S-HDL-A-2) include the storage handle. Runtime check
    //   deferred to test_reset_clears_storage in
    //   tb/sos_fifo_async/test_sos_fifo_async.py.
    //
    // CDC ordering / round-trip ordering
    //   Cross-clock ordering claims do not fit cleanly inside an SVA
    //   module bound to one of the two clocks. The cocotb testbench
    //   uses an in-flight reference deque to verify FIFO ordering across
    //   the CDC boundary instead.

endmodule

`default_nettype wire
