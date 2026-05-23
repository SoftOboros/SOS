//------------------------------------------------------------------------------
// sos_strobe_latch_sva.sv - SVA assertion module for sos_strobe_latch
//
// @spec        docs/concepts/SOS-08-A-CONCEPTS.md §6.10 (SVA properties)
// @parent      docs/concepts/SOS-08-CONCEPTS.md §6 (L0 set), §7 (INV-S-HDL-1..5)
// @grandparent docs/concepts/SOS-07-CONCEPTS.md §6 (INV-SOS-A..H)
//
// PCDN-A-strobe-pending-shadow resolved 2026-05-23 (§15): the assertion set is
// refined to reflect the 3-state FSM (IDLE / LATCHED / LATCHED_PENDING) and
// the depth-1 shadow register exposed via `pending_q`. The "ack-wins from
// LATCHED drops the strobe" claim is RETIRED; replaced by the shadow-capture
// properties below.
//
// Invariants cited (not re-derived):
//   INV-SOS-A..H        (SOS-07 §6)
//   INV-S-HDL-1..5      (SOS-08 §7)
//   INV-S-HDL-A-1..5    (SOS-08-A §7)
//
// Per PCDN-A-bind-form resolved 2026-05-23 (§15): module-type bind form is
// used; the bind directive in tb/sos_strobe_latch/sos_strobe_latch_bind.sv
// attaches this assertion module to every elaboration instance of
// sos_strobe_latch across the design.
//
// Properties (per §6.10 + PCDN-A-strobe-pending-shadow semantic):
//   - p_strobe_latched_in_idle        : strobe in IDLE -> next-cycle latched=1.
//   - p_ack_clears_in_latched_no_pending
//                                     : ack in LATCHED (pending_q=0) with no
//                                       concurrent strobe -> next-cycle
//                                       latched=0 (state -> IDLE).
//   - p_ack_clears_in_latched_pending : ack in LATCHED_PENDING -> next-cycle
//                                       state == LATCHED (shadow consumed;
//                                       latched stays 1, pending_q drops).
//   - p_strobe_in_latched_captures    : strobe in LATCHED with no ack ->
//                                       next-cycle state == LATCHED_PENDING.
//   - p_strobe_in_latched_pending_dropped
//                                     : strobe in LATCHED_PENDING with no ack
//                                       -> state unchanged (depth-1 saturated).
//   - p_pending_q_consistent          : pending_q == 1 IFF state == LATCHED_PENDING.
//                                       Stated on the visible reduction:
//                                       pending_q -> latched (every cycle
//                                       pending_q=1 has latched=1).
//   - p_latched_holds_no_ack          : latched=1 && !ack -> next-cycle latched=1.
//   - p_reset_clears                  : during rst, latched=0 and pending_q=0.
//   - p_state_consistent              : latched_state_q == latched
//                                       (observability mirror).
//------------------------------------------------------------------------------

`default_nettype none

module sos_strobe_latch_sva (
    input wire clk,
    input wire rst,
    input wire strobe,
    input wire ack,
    input wire latched,
    input wire pending_q,
    input wire latched_state_q
);

    // ----- p_strobe_latched_in_idle -----------------------------------------
    // Per §6.10: strobe in IDLE (latched=0) -> next cycle latched=1.
    // (Unchanged from the pre-shadow version; the IDLE-side semantics did not
    // change under PCDN-A-strobe-pending-shadow.)
    property p_strobe_latched_in_idle;
        @(posedge clk) disable iff (rst)
            (strobe && !latched) |-> ##1 latched;
    endproperty
    a_strobe_latched_in_idle:
        assert property (p_strobe_latched_in_idle)
        else $error("sos_strobe_latch: strobe in IDLE did not latch next cycle");

    // ----- p_ack_clears_in_latched_no_pending -------------------------------
    // ack in LATCHED with no concurrent strobe and no shadow -> next IDLE
    // (latched=0). Mirrors the prior every_ack_clears property, narrowed to
    // the !pending_q && !strobe antecedent so that the shadow / same-cycle
    // strobe cases are covered by the dedicated properties below.
    property p_ack_clears_in_latched_no_pending;
        @(posedge clk) disable iff (rst)
            (ack && latched && !pending_q && !strobe) |-> ##1 !latched;
    endproperty
    a_ack_clears_in_latched_no_pending:
        assert property (p_ack_clears_in_latched_no_pending)
        else $error("sos_strobe_latch: ack in LATCHED (no pending, no strobe) did not clear next cycle");

    // ----- p_ack_clears_in_latched_pending ----------------------------------
    // ack in LATCHED_PENDING -> next cycle state is LATCHED (latched stays 1,
    // pending_q drops to 0). The shadow is consumed and promoted to live.
    // Note: a concurrent strobe is dropped (depth-1 saturated); state still
    // transitions to LATCHED, so this property covers both
    // (ack && pending_q && !strobe) and (ack && pending_q && strobe).
    property p_ack_clears_in_latched_pending;
        @(posedge clk) disable iff (rst)
            (ack && pending_q) |-> ##1 (latched && !pending_q);
    endproperty
    a_ack_clears_in_latched_pending:
        assert property (p_ack_clears_in_latched_pending)
        else $error("sos_strobe_latch: ack in LATCHED_PENDING did not promote shadow to live");

    // ----- p_strobe_in_latched_captures -------------------------------------
    // NEW under PCDN-A-strobe-pending-shadow: strobe in LATCHED (no ack, no
    // pre-existing shadow) is captured into the shadow -> next cycle state
    // is LATCHED_PENDING (latched stays 1, pending_q rises to 1).
    property p_strobe_in_latched_captures;
        @(posedge clk) disable iff (rst)
            (strobe && latched && !pending_q && !ack) |-> ##1 (latched && pending_q);
    endproperty
    a_strobe_in_latched_captures:
        assert property (p_strobe_in_latched_captures)
        else $error("sos_strobe_latch: strobe in LATCHED did not capture into shadow");

    // ----- p_strobe_in_latched_pending_dropped ------------------------------
    // NEW under PCDN-A-strobe-pending-shadow: strobe in LATCHED_PENDING with
    // no ack -> state unchanged (latched=1, pending_q=1). Depth-1 shadow is
    // saturated; additional strobes are dropped.
    property p_strobe_in_latched_pending_dropped;
        @(posedge clk) disable iff (rst)
            (strobe && latched && pending_q && !ack) |-> ##1 (latched && pending_q);
    endproperty
    a_strobe_in_latched_pending_dropped:
        assert property (p_strobe_in_latched_pending_dropped)
        else $error("sos_strobe_latch: strobe in LATCHED_PENDING did not stay in LATCHED_PENDING");

    // ----- p_pending_q_consistent -------------------------------------------
    // NEW under PCDN-A-strobe-pending-shadow: pending_q=1 implies latched=1
    // (the shadow only exists while latched). Combinational; no ##1 delay.
    // The IFF claim "pending_q=1 iff state == LATCHED_PENDING" is by
    // construction in the RTL (single-source FSM-state decoder); the visible
    // assertion is the necessary-condition direction.
    property p_pending_q_consistent;
        @(posedge clk) disable iff (rst)
            pending_q |-> latched;
    endproperty
    a_pending_q_consistent:
        assert property (p_pending_q_consistent)
        else $error("sos_strobe_latch: pending_q=1 with latched=0 (impossible state)");

    // ----- p_latched_holds_no_ack -------------------------------------------
    // While latched=1 and no ack, latched stays 1 next cycle.
    // (Level-held output stability; also covers the strobe-in-LATCHED case
    // since that transitions to LATCHED_PENDING which is still latched=1.)
    property p_latched_holds_no_ack;
        @(posedge clk) disable iff (rst)
            (latched && !ack) |-> ##1 latched;
    endproperty
    a_latched_holds_no_ack:
        assert property (p_latched_holds_no_ack)
        else $error("sos_strobe_latch: latched dropped without ack");

    // ----- p_reset_clears ---------------------------------------------------
    // During reset, latched and pending_q are both held at zero.
    property p_reset_clears_latched;
        @(posedge clk) rst |-> ##1 !latched;
    endproperty
    a_reset_clears_latched:
        assert property (p_reset_clears_latched)
        else $error("sos_strobe_latch: reset did not clear latched");

    property p_reset_clears_pending;
        @(posedge clk) rst |-> ##1 !pending_q;
    endproperty
    a_reset_clears_pending:
        assert property (p_reset_clears_pending)
        else $error("sos_strobe_latch: reset did not clear pending_q");

    // ----- p_state_consistent -----------------------------------------------
    // The registered observability port latched_state_q must equal latched
    // combinationally (they share the FSM-state decoder).
    property p_state_consistent;
        @(posedge clk) disable iff (rst)
            latched_state_q == latched;
    endproperty
    a_state_consistent:
        assert property (p_state_consistent)
        else $error("sos_strobe_latch: latched_state_q != latched (FSM state inconsistent)");

endmodule

`default_nettype wire
