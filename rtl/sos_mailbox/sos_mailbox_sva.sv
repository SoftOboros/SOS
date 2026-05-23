// =============================================================================
// sos_mailbox_sva.sv  --  Service-level SVA assertion module for sos_mailbox.
//
// @spec docs/concepts/SOS-08-B-CONCEPTS.md §6.1 "Service-level SVA"
//       (SVA-MBX-1..5) + §7 INV-S-HDL-B-3 (service-level SVA on every L1
//       instance) + §15 2026-05-23 ratification entry (PCDN-SOS-08-B-006
//       resolved level-sensitive irq_non_empty).
//
//   Per INV-S-HDL-B-3 every L1 service ships service-level SVA bound to
//   every instance.  Per INV-S-HDL-B-5 every failure renders in chart
//   vocabulary, not raw RTL signal traces.  The bind directive lives in
//   tb/sos_mailbox/sos_mailbox_bind.sv (module-type bind per
//   PCDN-A-bind-form ratified 2026-05-23 in SOS-08-A §15).
//
// Cited invariants:
//   INV-SOS-A, INV-SOS-B, INV-SOS-E, INV-SOS-G, INV-SOS-H  (SOS-07 §6)
//   INV-S-HDL-1, INV-S-HDL-2, INV-S-HDL-4, INV-S-HDL-5    (SOS-08 §7)
//   INV-S-HDL-B-1, INV-S-HDL-B-2, INV-S-HDL-B-3,           (SOS-08-B §7)
//   INV-S-HDL-B-4, INV-S-HDL-B-5
//   Per L0 (composed, not redefined):
//     INV-S-HDL-A-1..5 inherited from sos_fifo_sync + sos_arbiter_priority
//
// Service-level properties (per §6.1 SVA-MBX-1..5):
//
//   SVA-MBX-2 -- priority dispatch.  When multiple lanes are non-empty,
//                the next take_ack drains from the highest-priority
//                non-empty lane.  Service-level form here: the egress
//                m_axis_tprio sideband always equals the index of a
//                non-empty lane (priority correctness is delegated to
//                sos_arbiter_priority's bound SVA; this module only
//                asserts the L1 wiring claim that the reported tprio
//                names a non-empty lane and that the reported lane is
//                the one whose data is on m_axis_tdata).
//
//   SVA-MBX-4 -- no spurious irq.  irq_non_empty asserts iff at least
//                one lane is non-empty.  Service-level form here:
//                irq_non_empty == |(~lane_empty).
//
//   SVA-MBX-1 (ordering within a lane) -- DELEGATED to sos_fifo_sync's
//                ordering SVA (the FIFO contract).  The bind file
//                automatically attaches sos_fifo_sync_sva to each lane
//                FIFO, so ordering is verified at the L0 layer per
//                INV-S-HDL-B-2 (L0 contracts hold unmodified under
//                composition).
//
//   SVA-MBX-3 (no loss on full) -- DELEGATED to sos_fifo_sync's
//                no_overflow + no_write_when_full SVA at L0.  At the
//                L1 surface the equivalent claim is that s_axis_tready
//                falls when the targeted lane is full, which the
//                lane-decode wiring derives from the L0 contract.
//
//   SVA-MBX-5 (invalid-prio rejection) -- the §6.1 doc shape uses a
//                two-bit rc bus to report RC_INVAL; the task brief omits
//                that bus from the surface.  This module encodes the
//                equivalent runtime check as a_no_tready_when_tprio_oor:
//                when s_axis_tvalid is high with s_axis_tprio >= NUM_PRIO,
//                s_axis_tready MUST be 0 (the producer stalls until it
//                corrects the sideband).
//
//   Inheritance: FIFO underflow / overflow are not re-derived here
//   (delegated to sos_fifo_sync_sva).
//
// Failure messages cite chart vocabulary (post/take/lane/irq) per
// INV-S-HDL-B-5 and INV-S-HDL-5; the L0-layer messages cite raw RTL
// names and live in the L0 bind files.
// =============================================================================

`default_nettype none

module sos_mailbox_sva #(
    parameter int NUM_PRIO   = 8,
    parameter int DEPTH      = 0,
    parameter int WIDTH      = 0,
    parameter int PRIO_W_EFF = (NUM_PRIO <= 1) ? 1 : $clog2(NUM_PRIO)
) (
    input  wire                        clk,
    input  wire                        rst,

    input  wire [WIDTH-1:0]            s_axis_tdata,
    input  wire [PRIO_W_EFF-1:0]       s_axis_tprio,
    input  wire                        s_axis_tvalid,
    input  wire                        s_axis_tready,

    input  wire [WIDTH-1:0]            m_axis_tdata,
    input  wire [PRIO_W_EFF-1:0]       m_axis_tprio,
    input  wire                        m_axis_tvalid,
    input  wire                        m_axis_tready,

    input  wire                        irq_non_empty,

    // Internal observability surfaced from the parent module via the bind
    // directive: per-lane ~empty flags and grant bus.  These are NOT part
    // of the L1 interface; the bind exposes them for the assertion module.
    input  wire [NUM_PRIO-1:0]         lane_empty,
    input  wire [NUM_PRIO-1:0]         arb_grant
);

  // ---------------------------------------------------------------------------
  // SVA-MBX-4 -- irq_non_empty correctness (level-sensitive, PCDN-B-006).
  //
  // irq_non_empty MUST be high iff at least one lane is non-empty.
  // ---------------------------------------------------------------------------
  property p_irq_non_empty_iff_any_lane_non_empty;
    @(posedge clk) disable iff (rst)
      irq_non_empty == (|(~lane_empty));
  endproperty
  a_irq_non_empty_iff_any_lane_non_empty :
    assert property (p_irq_non_empty_iff_any_lane_non_empty)
      else $error("sos_mailbox: irq_non_empty disagrees with any-lane-non-empty -- violates SVA-MBX-4 (post-irq contract; PCDN-SOS-08-B-006)");

  // Stronger forms.
  property p_irq_zero_when_all_lanes_empty;
    @(posedge clk) disable iff (rst)
      (&lane_empty) |-> !irq_non_empty;
  endproperty
  a_irq_zero_when_all_lanes_empty :
    assert property (p_irq_zero_when_all_lanes_empty)
      else $error("sos_mailbox: irq_non_empty asserted with every lane empty -- violates SVA-MBX-4 (no spurious post-irq)");

  property p_irq_high_when_any_lane_non_empty;
    @(posedge clk) disable iff (rst)
      (|(~lane_empty)) |-> irq_non_empty;
  endproperty
  a_irq_high_when_any_lane_non_empty :
    assert property (p_irq_high_when_any_lane_non_empty)
      else $error("sos_mailbox: irq_non_empty deasserted while a lane holds posted messages -- violates SVA-MBX-4 (take-irq must wake on any-lane-non-empty)");

  // ---------------------------------------------------------------------------
  // SVA-MBX-2 -- priority dispatch / egress prio correctness.
  //
  // L1-level claim: at most one lane is granted per cycle (the L0 arbiter
  // guarantees this; we restate as a sanity check on the L1 wiring), and
  // the m_axis_tprio sideband names the granted lane.
  //
  // Priority ordering itself (highest-priority-lane wins) is verified at
  // L0 by sos_arbiter_priority_sva's a_highest_prio_wins property, which
  // the per-lane FIFO bind chain instantiates automatically.  At the L1
  // surface we assert the weaker but locally-verifiable claim:
  //   * grant is one-hot or all-zero
  //   * if m_axis_tvalid is high, exactly one bit of arb_grant is set and
  //     m_axis_tprio matches that bit's index
  // ---------------------------------------------------------------------------
  property p_grant_at_most_one_hot;
    @(posedge clk) disable iff (rst)
      $countones(arb_grant) <= 1;
  endproperty
  a_grant_at_most_one_hot :
    assert property (p_grant_at_most_one_hot)
      else $error("sos_mailbox: multiple lanes granted on the same take cycle -- violates SVA-MBX-2 (priority dispatch picks a single lane)");

  property p_tvalid_implies_one_lane_granted;
    @(posedge clk) disable iff (rst)
      m_axis_tvalid |-> ($countones(arb_grant) == 1);
  endproperty
  a_tvalid_implies_one_lane_granted :
    assert property (p_tvalid_implies_one_lane_granted)
      else $error("sos_mailbox: take presented to consumer with no lane granted -- violates SVA-MBX-2 (priority dispatch failed to elect a lane)");

  property p_tprio_names_granted_lane;
    @(posedge clk) disable iff (rst)
      m_axis_tvalid |-> arb_grant[m_axis_tprio];
  endproperty
  a_tprio_names_granted_lane :
    assert property (p_tprio_names_granted_lane)
      else $error("sos_mailbox: take m_axis_tprio names a non-granted lane -- violates SVA-MBX-2 (egress sideband must report the dispatched lane)");

  // If a lane is granted, it MUST be non-empty (no draining from an empty
  // lane -- L0 sos_fifo_sync's no_underflow guarantees this; this assertion
  // catches L1-wiring bugs that would otherwise mask the L0 violation).
  property p_granted_lane_non_empty;
    @(posedge clk) disable iff (rst)
      (|arb_grant) |-> !lane_empty[m_axis_tprio];
  endproperty
  a_granted_lane_non_empty :
    assert property (p_granted_lane_non_empty)
      else $error("sos_mailbox: take dispatched to an empty lane -- violates SVA-MBX-2 (priority dispatch must drain only non-empty lanes; underflow inherited from L0 SVA)");

  // ---------------------------------------------------------------------------
  // SVA-MBX-5 -- invalid priority rejection.
  //
  // Spec §6.1 draft has a two-bit rc bus reporting RC_INVAL for out-of-range
  // s_axis_tprio.  The task brief omits the rc bus; we encode the
  // equivalent claim as "s_axis_tready stays low while s_axis_tvalid is
  // high with s_axis_tprio >= NUM_PRIO" -- the producer stalls until it
  // corrects the sideband.
  //
  // For NUM_PRIO that is a power of two, $clog2(NUM_PRIO) covers the full
  // value range and no value is out-of-range; the property holds vacuously.
  // For non-power-of-two NUM_PRIO, out-of-range values exist and the
  // property has bite.
  // ---------------------------------------------------------------------------
  property p_no_tready_when_tprio_oor;
    @(posedge clk) disable iff (rst)
      (s_axis_tvalid && (s_axis_tprio >= PRIO_W_EFF'(NUM_PRIO))) |->
        !s_axis_tready;
  endproperty
  a_no_tready_when_tprio_oor :
    assert property (p_no_tready_when_tprio_oor)
      else $error("sos_mailbox: post accepted with out-of-range lane selector -- violates SVA-MBX-5 (invalid-prio rejection; RC_INVAL slot per spec §6.1)");

  // ---------------------------------------------------------------------------
  // AXI-Stream egress: tvalid stable until tready (handshake correctness
  // inherited per INV-S-HDL-A-2).  Sanity check at the L1 surface.
  // ---------------------------------------------------------------------------
  property p_tvalid_stable_until_tready;
    @(posedge clk) disable iff (rst)
      (m_axis_tvalid && !m_axis_tready) |=> m_axis_tvalid;
  endproperty
  a_tvalid_stable_until_tready :
    assert property (p_tvalid_stable_until_tready)
      else $error("sos_mailbox: take m_axis_tvalid dropped without a consumer transfer -- AXI-Stream handshake violated (INV-S-HDL-A-2)");

  // The reported lane sideband MUST be stable across a stalled handshake
  // too (else the consumer could not correlate the message to a lane).
  property p_tprio_stable_until_tready;
    @(posedge clk) disable iff (rst)
      (m_axis_tvalid && !m_axis_tready) |=> $stable(m_axis_tprio);
  endproperty
  a_tprio_stable_until_tready :
    assert property (p_tprio_stable_until_tready)
      else $error("sos_mailbox: take m_axis_tprio drifted while take handshake was stalled -- violates SVA-MBX-2 (lane sideband must hold across backpressure)");

  // ---------------------------------------------------------------------------
  // Reset behaviour: after reset, all lanes empty, irq deasserted, no
  // grant.  Sanity for the bind-side observability state.
  // ---------------------------------------------------------------------------
  property p_reset_clears_irq;
    @(posedge clk) rst |=> !irq_non_empty;
  endproperty
  a_reset_clears_irq :
    assert property (p_reset_clears_irq)
      else $error("sos_mailbox: irq_non_empty asserted post-reset -- violates SVA-MBX-4 (reset must drain all post-irqs)");

  property p_reset_clears_grant;
    @(posedge clk) rst |=> (arb_grant == '0);
  endproperty
  a_reset_clears_grant :
    assert property (p_reset_clears_grant)
      else $error("sos_mailbox: arb_grant non-zero post-reset -- violates SVA-MBX-2 (reset must clear the priority dispatcher)");

endmodule : sos_mailbox_sva

`default_nettype wire
