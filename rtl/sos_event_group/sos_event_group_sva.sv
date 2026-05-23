// =============================================================================
// sos_event_group_sva.sv  --  Service-level SVA assertion module for
//                             sos_event_group (portable SystemVerilog-2017)
//
// @spec        docs/concepts/SOS-08-B-CONCEPTS.md §6.2 (SVA-EVG-1..5)
//                + §7 cross-service invariants
//                + §15 ratification entry (PCDN-SOS-08-B-002 -> N_BITS=32).
// @parent      docs/concepts/SOS-08-CONCEPTS.md §6 (L1 set), §7 (INV-S-HDL-1..5)
// @grandparent docs/concepts/SOS-07-CONCEPTS.md §6 (INV-SOS-A..H)
// @l0          docs/concepts/SOS-08-A-CONCEPTS.md §6.10 (sos_strobe_latch)
//                + §15 wave-2 amendments.
//
// Cited invariants:
//   INV-SOS-A..H        (SOS-07 §6)
//   INV-S-HDL-1..5      (SOS-08 §7)
//   INV-S-HDL-A-1..5    (SOS-08-A §7) -- L0 invariants hold per strobe_latch
//                       SVA bind (separate module-type bind, see SOS-08-A).
//   INV-S-HDL-B-1..5    (SOS-08-B §7) -- service-level invariants this
//                       assertion module exists to enforce.
//
// Per PCDN-A-bind-form resolved 2026-05-23 (§15 wave-1 entry of SOS-08-A):
// module-type bind is used; the bind directive in
// tb/sos_event_group/sos_event_group_bind.sv attaches this module to every
// elaboration instance of sos_event_group.  Per §5.4 + PCDN-SOS-08-007
// resolution of the SOS-08 umbrella, service-level SVA binds default to
// "bind every instance" -- exactly what module-type bind delivers.
//
// Service-level properties (per §6.2 SVA-EVG-1..5):
//
//   a_set_eventually_latches    (SVA-EVG-1): set_req && set_mask[i] in a
//                               cycle where the bit is clear -> bits[i]==1
//                               on the next cycle, AND stays 1 until a
//                               corresponding clear (covered by
//                               a_bit_holds_until_clear).  Stated per-bit
//                               via a generate-for loop.
//   a_wait_any_match            (SVA-EVG-2): wait_mode==0 with the masked
//                               bits non-zero -> wait_match==1 same cycle.
//   a_wait_any_nomatch          (SVA-EVG-2 contrapositive): wait_mode==0
//                               with masked bits zero -> wait_match==0.
//   a_wait_all_match            (SVA-EVG-3): wait_mode==1 with masked bits
//                               == wait_mask -> wait_match==1.
//   a_wait_all_nomatch          (SVA-EVG-3 contrapositive): wait_mode==1
//                               with masked bits != wait_mask -> wait_match==0.
//   a_clear_drops_bit           (per-bit; complements SVA-EVG-1 via the L0
//                               primitive's ack-clears-LATCHED semantic):
//                               clear_req && clear_mask[i] in a cycle where
//                               the bit is set AND no concurrent set on bit i
//                               -> bits[i]==0 next cycle.  (The same-cycle
//                               set+clear shadow-promote case is governed by
//                               a_bit_holds_under_concurrent_set_clear.)
//   a_bit_holds_until_clear     (per-bit, level stability): bits[i]==1 and
//                               !(clear_req && clear_mask[i]) -> bits[i]==1
//                               on the next cycle.  Inherits from L0
//                               p_latched_holds_no_ack via composition.
//   a_reset_clears_all          (per-bit, SVA-EVG analog for reset): under
//                               rst, bits[i]==0 next cycle.  Inherits from
//                               L0 p_reset_clears_latched.
//   a_probe_non_disturbance     (SVA-EVG-5): bits[] reading is combinational
//                               and never modifies internal state.  Stated as
//                               a stability property: if no set/clear/reset,
//                               bits[] does not change.
//   a_bit_holds_under_concurrent_set_clear (design-choice flag):
//                               bits[i]==1 with same-cycle set_mask[i] and
//                               clear_mask[i] both pulsed -> bits[i]==1 next
//                               cycle (shadow-promote semantic of L0
//                               strobe_latch).  Documents the simultaneous
//                               set+clear outcome flagged in the RTL header.
// =============================================================================

`default_nettype none

module sos_event_group_sva #(
    parameter int N_BITS = 32
) (
    input wire                  clk,
    input wire                  rst,
    input wire                  set_req,
    input wire [N_BITS-1:0]     set_mask,
    input wire                  clear_req,
    input wire [N_BITS-1:0]     clear_mask,
    input wire [N_BITS-1:0]     wait_mask,
    input wire                  wait_mode,
    input wire                  wait_match,
    input wire [N_BITS-1:0]     bits
);

  // ---------------------------------------------------------------------------
  // Wait-side correctness (combinational; SVA-EVG-2 / SVA-EVG-3).
  // ---------------------------------------------------------------------------
  wire [N_BITS-1:0] masked = bits & wait_mask;

  property p_wait_any_match;
    @(posedge clk) disable iff (rst)
        (wait_mode == 1'b0 && (|masked)) |-> (wait_match == 1'b1);
  endproperty
  a_wait_any_match:
    assert property (p_wait_any_match)
    else $error("sos_event_group: wait-any with non-empty (bits & wait_mask) did not assert wait_match -- violates SVA-EVG-2");

  property p_wait_any_nomatch;
    @(posedge clk) disable iff (rst)
        (wait_mode == 1'b0 && (masked == {N_BITS{1'b0}})) |-> (wait_match == 1'b0);
  endproperty
  a_wait_any_nomatch:
    assert property (p_wait_any_nomatch)
    else $error("sos_event_group: wait-any with empty (bits & wait_mask) asserted wait_match -- violates SVA-EVG-2");

  property p_wait_all_match;
    @(posedge clk) disable iff (rst)
        (wait_mode == 1'b1 && (masked == wait_mask)) |-> (wait_match == 1'b1);
  endproperty
  a_wait_all_match:
    assert property (p_wait_all_match)
    else $error("sos_event_group: wait-all with full mask satisfied did not assert wait_match -- violates SVA-EVG-3");

  property p_wait_all_nomatch;
    @(posedge clk) disable iff (rst)
        (wait_mode == 1'b1 && (masked != wait_mask)) |-> (wait_match == 1'b0);
  endproperty
  a_wait_all_nomatch:
    assert property (p_wait_all_nomatch)
    else $error("sos_event_group: wait-all with mask not fully satisfied asserted wait_match -- violates SVA-EVG-3");

  // ---------------------------------------------------------------------------
  // Per-bit set / clear / hold / reset (SVA-EVG-1 + composed from L0 strobe).
  // ---------------------------------------------------------------------------
  genvar gi;
  generate
    for (gi = 0; gi < N_BITS; gi = gi + 1) begin : g_bit_props

      // ----- a_set_eventually_latches (SVA-EVG-1) ---------------------------
      // strobe-eventually-latched, per-bit, mirroring L0 p_strobe_latched_in_idle.
      // Antecedent narrows to "bit is clear AND set_req && set_mask[i]" so the
      // already-set case (which is governed by hold + shadow-promote properties)
      // is covered by the appropriate dedicated property.
      property p_set_eventually_latches;
        @(posedge clk) disable iff (rst)
            (set_req && set_mask[gi] && !bits[gi]) |-> ##1 bits[gi];
      endproperty
      a_set_eventually_latches:
        assert property (p_set_eventually_latches)
        else $error($sformatf("sos_event_group: set on bit %0d did not latch next cycle -- violates SVA-EVG-1", gi));

      // ----- a_clear_drops_bit ----------------------------------------------
      // clear_req && clear_mask[i] on a set bit with NO same-cycle set on the
      // same bit -> bits[i]=0 next cycle.  Same-cycle set+clear on the same
      // bit is governed by a_bit_holds_under_concurrent_set_clear below.
      property p_clear_drops_bit;
        @(posedge clk) disable iff (rst)
            (clear_req && clear_mask[gi] && bits[gi] && !(set_req && set_mask[gi]))
                |-> ##1 !bits[gi];
      endproperty
      a_clear_drops_bit:
        assert property (p_clear_drops_bit)
        else $error($sformatf("sos_event_group: clear on bit %0d did not drop next cycle", gi));

      // ----- a_bit_holds_until_clear ----------------------------------------
      // Level stability: a set bit stays set in the absence of a clearing edge.
      // Inherited from L0 p_latched_holds_no_ack (sos_strobe_latch SVA).
      property p_bit_holds_until_clear;
        @(posedge clk) disable iff (rst)
            (bits[gi] && !(clear_req && clear_mask[gi])) |-> ##1 bits[gi];
      endproperty
      a_bit_holds_until_clear:
        assert property (p_bit_holds_until_clear)
        else $error($sformatf("sos_event_group: bit %0d dropped without a clearing edge -- violates level-held output stability", gi));

      // ----- a_reset_clears_all ---------------------------------------------
      // Under rst, every bit is cleared on the next cycle.  Mirrors
      // L0 p_reset_clears_latched per strobe_latch.
      property p_reset_clears;
        @(posedge clk) rst |-> ##1 !bits[gi];
      endproperty
      a_reset_clears_all:
        assert property (p_reset_clears)
        else $error($sformatf("sos_event_group: reset did not clear bit %0d", gi));

      // ----- a_bit_holds_under_concurrent_set_clear -------------------------
      // Design-choice property: same-cycle set+clear on a SET bit -> stays set
      // (shadow-promote semantic; see RTL header).  Flagged in the agent
      // report and documented here so any future change to the simultaneous-
      // edge resolution surfaces as an SVA failure rather than a silent
      // regression.
      property p_bit_holds_under_concurrent_set_clear;
        @(posedge clk) disable iff (rst)
            (bits[gi] && set_req && set_mask[gi] && clear_req && clear_mask[gi])
                |-> ##1 bits[gi];
      endproperty
      a_bit_holds_under_concurrent_set_clear:
        assert property (p_bit_holds_under_concurrent_set_clear)
        else $error($sformatf("sos_event_group: simultaneous set+clear on set bit %0d did not preserve via shadow-promote", gi));

    end
  endgenerate

  // ---------------------------------------------------------------------------
  // Probe non-disturbance (SVA-EVG-5): reading bits[] does not modify state.
  // Operationalised as: in the absence of any set/clear/reset edge, bits[] is
  // stable cycle-to-cycle.  Stronger than "probe is non-destructive" but
  // implied by it; SVA's vocabulary is happier with a stability claim.
  // ---------------------------------------------------------------------------
  property p_probe_non_disturbance;
    @(posedge clk) disable iff (rst)
        (!set_req && !clear_req) |-> ##1 $stable(bits);
  endproperty
  a_probe_non_disturbance:
    assert property (p_probe_non_disturbance)
    else $error("sos_event_group: bits[] changed without set_req or clear_req -- violates SVA-EVG-5 (probe non-disturbance)");

endmodule

`default_nettype wire
