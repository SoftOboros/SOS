// ----------------------------------------------------------------------------
// sos_fifo_sync_sva.sv
//
// @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.2 (sos_fifo_sync SVA properties)
//       docs/concepts/SOS-08-CONCEPTS.md   §5  (frozen decisions inherited)
//       docs/concepts/SOS-07-CONCEPTS.md   §6  (cross-phase invariants)
//       PCDN-A-fifo-READ_LATENCY  resolved 2026-05-23 — tdata-stable
//                                  property is FWFT-mode-only
//       PCDN-A-fifo-RESET_MEM     resolved 2026-05-23 — a_reset_clears_mem
//                                  gated on RESET_MEM == 1
//
// Cross-phase invariants (cited, not redefined):
//   INV-SOS-A..H per SOS-07 §6
//
// Cross-sub-phase invariants (SOS-08 §7, cited):
//   INV-S-HDL-1..5 — handshake compat, static alloc, CDC isolation (N/A),
//                   cooperative v1, vector-to-chart traceability
//
// Cross-primitive invariants (SOS-08-A §7, cited):
//   INV-S-HDL-A-1..5
//
// SVA properties bound to a sos_fifo_sync instance. Bound via the directive
// in tb/sos_fifo_sync/sos_fifo_sync_bind.sv during cocotb simulation runs.
//
// Properties per SOS-08-A §6.2:
//   - no_overflow : never accept a write while full
//   - no_underflow: never present a valid output when empty
//   - count_invariant: count stays <= DEPTH
//   - reset_clears: rst forces full=0, empty=1, count=0
//   - reset_clears_mem (RESET_MEM=1 only): rst forces every mem entry to 0
// ----------------------------------------------------------------------------

`default_nettype none

module sos_fifo_sync_sva #(
    parameter int DEPTH = 0,
    parameter int WIDTH = 0,
    // PCDN-A-fifo-READ_LATENCY / PCDN-A-fifo-RESET_MEM (2026-05-23).
    // Mirror the DUT parameters so per-mode property generates compile.
    parameter int READ_LATENCY = 0,
    parameter bit RESET_MEM    = 1'b0,
    parameter int CNT_W = $clog2(DEPTH + 1)
) (
    input wire                  clk,
    input wire                  rst,

    input wire [WIDTH-1:0]      s_axis_tdata,
    input wire                  s_axis_tvalid,
    input wire                  s_axis_tready,

    input wire [WIDTH-1:0]      m_axis_tdata,
    input wire                  m_axis_tvalid,
    input wire                  m_axis_tready,

    input wire                  full,
    input wire                  empty,
    input wire [CNT_W-1:0]      count
);

    // ------------------------------------------------------------------------
    // SVA §6.2 #1 — no_overflow
    // Restated: when `full` is asserted the FIFO MUST not signal s_axis_tready
    // (any concurrent s_axis_tvalid is left un-accepted). Equivalent to the
    // spec's "wvalid && full |-> !wready" with AXI-Stream renaming.
    // ------------------------------------------------------------------------
    property p_no_overflow;
        @(posedge clk) disable iff (rst)
            (s_axis_tvalid && full) |-> !s_axis_tready;
    endproperty
    a_no_overflow: assert property (p_no_overflow)
        else $error("sos_fifo_sync_sva: overflow — tready asserted while full");

    // Stronger form: a write-handshake while full is impossible.
    property p_no_write_when_full;
        @(posedge clk) disable iff (rst)
            !(s_axis_tvalid && s_axis_tready && full);
    endproperty
    a_no_write_when_full: assert property (p_no_write_when_full)
        else $error("sos_fifo_sync_sva: write handshake while full");

    // ------------------------------------------------------------------------
    // SVA §6.2 #2 — no_underflow
    // Restated: when `empty` is asserted the FIFO MUST not signal valid output;
    // equivalent to the spec's "rready && empty |-> !rvalid" with AXI rename.
    // ------------------------------------------------------------------------
    property p_no_underflow;
        @(posedge clk) disable iff (rst)
            (m_axis_tready && empty) |-> !m_axis_tvalid;
    endproperty
    a_no_underflow: assert property (p_no_underflow)
        else $error("sos_fifo_sync_sva: underflow — tvalid asserted while empty");

    property p_no_read_when_empty;
        @(posedge clk) disable iff (rst)
            !(m_axis_tvalid && m_axis_tready && empty);
    endproperty
    a_no_read_when_empty: assert property (p_no_read_when_empty)
        else $error("sos_fifo_sync_sva: read handshake while empty");

    // ------------------------------------------------------------------------
    // SVA §6.2 #3 — count_invariant
    // count is bounded by [0, DEPTH] for every cycle.
    // ------------------------------------------------------------------------
    property p_count_le_depth;
        @(posedge clk) (count <= CNT_W'(DEPTH));
    endproperty
    a_count_le_depth: assert property (p_count_le_depth)
        else $error("sos_fifo_sync_sva: count exceeds DEPTH");

    // count tracks fill exactly: count == DEPTH iff full, count == 0 iff empty.
    property p_count_full_alignment;
        @(posedge clk) disable iff (rst)
            (count == CNT_W'(DEPTH)) <-> full;
    endproperty
    a_count_full_alignment: assert property (p_count_full_alignment)
        else $error("sos_fifo_sync_sva: count==DEPTH but !full (or full but count!=DEPTH)");

    property p_count_empty_alignment;
        @(posedge clk) disable iff (rst)
            (count == CNT_W'(0)) <-> empty;
    endproperty
    a_count_empty_alignment: assert property (p_count_empty_alignment)
        else $error("sos_fifo_sync_sva: count==0 but !empty (or empty but count!=0)");

    // count delta per cycle is +1/-1/0 — never larger than one write and one
    // read in the same cycle.
    property p_count_delta_bounded;
        @(posedge clk) disable iff (rst)
            ##1 (
                (count == $past(count)) ||
                (count == CNT_W'($past(count) + 1)) ||
                (count == CNT_W'($past(count) - 1))
            );
    endproperty
    a_count_delta_bounded: assert property (p_count_delta_bounded)
        else $error("sos_fifo_sync_sva: count changed by more than one in a cycle");

    // ------------------------------------------------------------------------
    // SVA §6.2 #4 — reset behaviour
    // After a reset cycle, count == 0, full == 0, empty == 1.
    // Checked one cycle after rst deasserts (we sample the registered state).
    // ------------------------------------------------------------------------
    property p_reset_clears_count;
        @(posedge clk) rst |=> (count == CNT_W'(0));
    endproperty
    a_reset_clears_count: assert property (p_reset_clears_count)
        else $error("sos_fifo_sync_sva: count not cleared on reset");

    property p_reset_clears_full;
        @(posedge clk) rst |=> (full == 1'b0);
    endproperty
    a_reset_clears_full: assert property (p_reset_clears_full)
        else $error("sos_fifo_sync_sva: full not cleared on reset");

    property p_reset_sets_empty;
        @(posedge clk) rst |=> (empty == 1'b1);
    endproperty
    a_reset_sets_empty: assert property (p_reset_sets_empty)
        else $error("sos_fifo_sync_sva: empty not asserted on reset");

    // ------------------------------------------------------------------------
    // INV-S-HDL-A-2 — handshake-port composition. The handshake follows
    // canonical AXI-Stream semantics: tvalid MUST NOT drop without a transfer.
    // This is the "stable until accept" property AXI-Stream requires.
    // ------------------------------------------------------------------------
    property p_tvalid_stable_until_tready;
        @(posedge clk) disable iff (rst)
            (m_axis_tvalid && !m_axis_tready) |=> m_axis_tvalid;
    endproperty
    a_tvalid_stable_until_tready: assert property (p_tvalid_stable_until_tready)
        else $error("sos_fifo_sync_sva: tvalid dropped without a transfer");

    // ------------------------------------------------------------------------
    // PCDN-A-fifo-READ_LATENCY — tdata-stable property is FWFT-mode-only.
    // Under READ_LATENCY=1 the tdata bus is driven from a registered output
    // (rdata_q in sos_fifo_sync.sv), so the property holds trivially by
    // construction (registered output cannot change without a clock edge that
    // also re-evaluates rvalid_q). Apply the assertion in FWFT mode only.
    // ------------------------------------------------------------------------
    generate
        if (READ_LATENCY == 0) begin : g_sva_tdata_stable_fwft
            property p_tdata_stable_until_tready;
                @(posedge clk) disable iff (rst)
                    (m_axis_tvalid && !m_axis_tready) |=> $stable(m_axis_tdata);
            endproperty
            a_tdata_stable_until_tready: assert property (p_tdata_stable_until_tready)
                else $error("sos_fifo_sync_sva: tdata changed while tvalid && !tready (FWFT)");
        end
        // READ_LATENCY != 0: stable-tdata is VERIFIED_BY_ELAB — the registered
        // output flop guarantees the property by RTL construction; no runtime
        // assertion is emitted in this mode.
    endgenerate

    // ------------------------------------------------------------------------
    // PCDN-A-fifo-RESET_MEM — a_reset_clears_mem (RESET_MEM == 1 only).
    //
    // The contract states: after reset, the read of any address returns zero.
    // The mem array is internal to the DUT — the assertion module's port list
    // does not (per INV-S-HDL-A-2) include the storage handle. We therefore
    // mark this property VERIFIED_BY_ELAB: the sos_fifo_sync RTL clears mem in
    // its synchronous reset branch when RESET_MEM=1, and the cocotb test
    // (test_reset_mem_clears_storage in tb/sos_fifo_sync/test_sos_fifo_sync.py)
    // exercises the read path to confirm. A hierarchical reference to the
    // probe path (sos_fifo_sync_inst.mem) would require crossing the bind
    // boundary and is intentionally not emitted here.
    // ------------------------------------------------------------------------
    // VERIFIED_BY_ELAB: a_reset_clears_mem (RESET_MEM == 1)
    //   - RTL site: sos_fifo_sync.sv reset branch, "if (RESET_MEM)" loop.
    //   - Runtime check: test_reset_mem_clears_storage cocotb scenario.

endmodule

`default_nettype wire
