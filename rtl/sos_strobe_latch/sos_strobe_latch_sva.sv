//------------------------------------------------------------------------------
// sos_strobe_latch_sva.sv - SVA assertion module for sos_strobe_latch
//
// @spec        docs/concepts/SOS-08-A-CONCEPTS.md §6.10 (SVA properties)
// @parent      docs/concepts/SOS-08-CONCEPTS.md §6 (L0 set), §7 (INV-S-HDL-1..5)
// @grandparent docs/concepts/SOS-07-CONCEPTS.md §6 (INV-SOS-A..H)
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
// Properties (per §6.10 + same-cycle-arbitration semantic from task brief):
//   - every_strobe_latched   : strobe in IDLE -> next-cycle latched=1.
//                              (§6.10 SVA: `strobe |-> ##1 level`; refined
//                              with the "in IDLE" antecedent so the
//                              re-strobe-while-latched case from §6.10
//                              `no_double_latch` is the dual claim.)
//   - every_ack_clears       : ack in LATCHED -> next-cycle latched=0.
//                              (§6.10 SVA: `ack && level |-> ##1 !level`.)
//   - latched_holds_no_ack   : latched=1 && !ack -> next-cycle latched=1.
//                              (Latched holds while no ack. INV-S-HDL-A-2
//                              level-stability for the level-held output.)
//   - no_double_latch        : strobe in LATCHED with no ack is absorbed
//                              (§6.10 SVA: `strobe && level |-> ##1 level`).
//   - ack_wins_same_cycle    : strobe && ack in LATCHED -> next-cycle
//                              latched=0 (ack wins; strobe is dropped, per
//                              canonical "ack-wins-on-same-cycle from
//                              LATCHED" semantic in task brief).
//   - reset_clears_latched   : during rst, latched=0.
//   - state_one_hot          : the registered FSM state is one-hot
//                              (INV-S-HDL-A-4). Exposed via
//                              `latched_state_q` as the boolean reduction;
//                              the one-hot internal `state` is not part of
//                              the port surface, so this is the visible
//                              consistency check.
//------------------------------------------------------------------------------

`default_nettype none

module sos_strobe_latch_sva (
    input wire clk,
    input wire rst,
    input wire strobe,
    input wire ack,
    input wire latched,
    input wire latched_state_q
);

    // ----- every_strobe_latched ----------------------------------------------
    // Per §6.10: strobe in IDLE (latched=0) -> next cycle latched=1.
    // (The strobe-in-LATCHED case is covered by no_double_latch below.)
    property p_every_strobe_latched;
        @(posedge clk) disable iff (rst)
            (strobe && !latched) |-> ##1 latched;
    endproperty
    a_every_strobe_latched:
        assert property (p_every_strobe_latched)
        else $error("sos_strobe_latch: strobe in IDLE did not latch next cycle");

    // ----- every_ack_clears --------------------------------------------------
    // Per §6.10: ack while latched=1 -> next cycle latched=0.
    // The ack-wins-on-same-cycle semantic is a strengthening of this property:
    // even with a concurrent strobe, ack still wins from LATCHED.
    property p_every_ack_clears;
        @(posedge clk) disable iff (rst)
            (ack && latched) |-> ##1 !latched;
    endproperty
    a_every_ack_clears:
        assert property (p_every_ack_clears)
        else $error("sos_strobe_latch: ack while latched did not clear next cycle");

    // ----- latched_holds_no_ack ----------------------------------------------
    // While latched=1 and no ack, latched stays 1 next cycle.
    // (Level-held output stability; complements no_double_latch.)
    property p_latched_holds_no_ack;
        @(posedge clk) disable iff (rst)
            (latched && !ack) |-> ##1 latched;
    endproperty
    a_latched_holds_no_ack:
        assert property (p_latched_holds_no_ack)
        else $error("sos_strobe_latch: latched dropped without ack");

    // ----- no_double_latch ---------------------------------------------------
    // Per §6.10: strobe while latched and no ack is absorbed -- latched
    // remains high (no counter increment, no spurious transition).
    property p_no_double_latch;
        @(posedge clk) disable iff (rst)
            (strobe && latched && !ack) |-> ##1 latched;
    endproperty
    a_no_double_latch:
        assert property (p_no_double_latch)
        else $error("sos_strobe_latch: re-strobe-while-latched did not absorb");

    // ----- ack_wins_same_cycle -----------------------------------------------
    // Canonical "ack-wins-on-same-cycle from LATCHED" semantic (task brief).
    // strobe + ack simultaneously from LATCHED -> ack wins; next cycle
    // latched=0. The same-cycle strobe is dropped.
    property p_ack_wins_same_cycle;
        @(posedge clk) disable iff (rst)
            (strobe && ack && latched) |-> ##1 !latched;
    endproperty
    a_ack_wins_same_cycle:
        assert property (p_ack_wins_same_cycle)
        else $error("sos_strobe_latch: same-cycle strobe+ack from LATCHED did not clear");

    // ----- reset_clears_latched ----------------------------------------------
    // During reset, latched is held at zero (sync active-high).
    property p_reset_clears_latched;
        @(posedge clk) rst |-> ##1 !latched;
    endproperty
    a_reset_clears_latched:
        assert property (p_reset_clears_latched)
        else $error("sos_strobe_latch: reset did not clear latched");

    // ----- state_one_hot (visible-reduction form) ----------------------------
    // The registered observability port latched_state_q must equal latched
    // combinationally (they share the FSM-state decoder). This is the visible
    // surface witnessing INV-S-HDL-A-4 one-hot encoding without exposing the
    // internal one-hot vector.
    property p_state_consistent;
        @(posedge clk) disable iff (rst)
            latched_state_q == latched;
    endproperty
    a_state_consistent:
        assert property (p_state_consistent)
        else $error("sos_strobe_latch: latched_state_q != latched (FSM state inconsistent)");

endmodule

`default_nettype wire
