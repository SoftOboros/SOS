//------------------------------------------------------------------------------
// sos_credit_counter_sva.sv - SVA assertion module for sos_credit_counter
//
// @spec        docs/concepts/SOS-08-A-CONCEPTS.md §6.6 (SVA properties)
// @amendments  docs/concepts/SOS-08-A-CONCEPTS.md §15 (2026-05-23 entries):
//              - PCDN-A-bind-form: module-type bind across all SOS-08-A SVA.
// @parent      docs/concepts/SOS-08-CONCEPTS.md §6 (L0 set), §7 (INV-S-HDL-1..5)
// @grandparent docs/concepts/SOS-07-CONCEPTS.md §6 (INV-SOS-A..H)
//
// Invariants cited (not re-derived):
//   INV-SOS-A..H        (SOS-07 §6)
//   INV-S-HDL-1..5      (SOS-08 §7)
//   INV-S-HDL-A-1..5    (SOS-08-A §7)
//
// Properties:
//   ack_implies_req_and_credits_pos
//                          — acquire_ack high implies acquire_req high
//                            (same cycle) AND credits > 0 (same cycle).
//   credits_bounded_above  — credits <= MAX_CREDITS always.
//   credits_bounded_below  — credits >= 0 always (trivially true for the
//                            unsigned encoding; included for documentation).
//   reset_restores_init    — on the cycle after rst is sampled high,
//                            credits == INIT_CREDITS.
//   release_at_max_no_op   — release_req fired while credits == MAX_CREDITS
//                            (and no simultaneous acquire) keeps credits
//                            unchanged on the next cycle.
//   acquire_decrements     — successful acquire without simultaneous release
//                            decrements credits by exactly 1.
//   release_increments     — release within bound and without simultaneous
//                            acquire increments credits by exactly 1.
//   same_cycle_net_neutral — simultaneous acquire_ack && release_req leaves
//                            credits unchanged (when release is in-bound).
//------------------------------------------------------------------------------

`default_nettype none

module sos_credit_counter_sva #(
    parameter int INIT_CREDITS,
    parameter int MAX_CREDITS,
    localparam int CW = $clog2(MAX_CREDITS + 1)
) (
    input wire             clk,
    input wire             rst,
    input wire             acquire_req,
    input wire             acquire_ack,
    input wire             release_req,
    input wire [CW-1:0]    credits
);

    // ---------------------------------------------------------------------
    // ack_implies_req_and_credits_pos
    // ---------------------------------------------------------------------
    property p_ack_implies_req;
        @(posedge clk) disable iff (rst)
            acquire_ack |-> (acquire_req && (credits > '0));
    endproperty
    a_ack_implies_req:
        assert property (p_ack_implies_req)
        else $error("sos_credit_counter: acquire_ack high without acquire_req or with credits=0");

    // ---------------------------------------------------------------------
    // credits_bounded_above
    // ---------------------------------------------------------------------
    property p_credits_le_max;
        @(posedge clk) disable iff (rst)
            credits <= CW'(MAX_CREDITS);
    endproperty
    a_credits_le_max:
        assert property (p_credits_le_max)
        else $error("sos_credit_counter: credits=%0d > MAX_CREDITS=%0d", credits, MAX_CREDITS);

    // ---------------------------------------------------------------------
    // credits_bounded_below — unsigned, but documented explicitly.
    // ---------------------------------------------------------------------
    property p_credits_ge_zero;
        @(posedge clk) disable iff (rst)
            credits >= '0;
    endproperty
    a_credits_ge_zero:
        assert property (p_credits_ge_zero)
        else $error("sos_credit_counter: credits=%0d underflowed below 0", credits);

    // ---------------------------------------------------------------------
    // reset_restores_init
    // After rst sampled high on a posedge, the next posedge sees credits ==
    // INIT_CREDITS. We check it the cycle after rst is observed.
    // ---------------------------------------------------------------------
    property p_reset_restores_init;
        @(posedge clk) rst |=> (credits == CW'(INIT_CREDITS));
    endproperty
    a_reset_restores_init:
        assert property (p_reset_restores_init)
        else $error("sos_credit_counter: credits=%0d after reset, expected INIT_CREDITS=%0d",
                    credits, INIT_CREDITS);

    // ---------------------------------------------------------------------
    // release_at_max_no_op
    // release_req while at MAX, no simultaneous successful acquire => credits stays at MAX.
    // ---------------------------------------------------------------------
    property p_release_at_max_no_op;
        @(posedge clk) disable iff (rst)
            (release_req && (credits == CW'(MAX_CREDITS)) && !acquire_ack)
                |=> (credits == CW'(MAX_CREDITS));
    endproperty
    a_release_at_max_no_op:
        assert property (p_release_at_max_no_op)
        else $error("sos_credit_counter: release at MAX_CREDITS mutated credits");

    // ---------------------------------------------------------------------
    // acquire_decrements
    // Successful acquire (acquire_ack high) without simultaneous in-bound
    // release => credits decrements by 1 next cycle.
    //
    // "in-bound" here = release_req && credits < MAX_CREDITS. If release_req
    // fires but credits == MAX_CREDITS, the release is silently dropped, and
    // a simultaneous acquire still nets -1.
    // ---------------------------------------------------------------------
    property p_acquire_decrements;
        @(posedge clk) disable iff (rst)
            (acquire_ack && !(release_req && (credits < CW'(MAX_CREDITS))))
                |=> (credits == $past(credits) - CW'(1));
    endproperty
    a_acquire_decrements:
        assert property (p_acquire_decrements)
        else $error("sos_credit_counter: acquire_ack did not decrement credits");

    // ---------------------------------------------------------------------
    // release_increments
    // In-bound release without simultaneous acquire => credits increments by 1.
    // ---------------------------------------------------------------------
    property p_release_increments;
        @(posedge clk) disable iff (rst)
            (release_req && (credits < CW'(MAX_CREDITS)) && !acquire_ack)
                |=> (credits == $past(credits) + CW'(1));
    endproperty
    a_release_increments:
        assert property (p_release_increments)
        else $error("sos_credit_counter: in-bound release did not increment credits");

    // ---------------------------------------------------------------------
    // same_cycle_net_neutral
    // Successful acquire AND in-bound release on the same cycle => no change.
    // ---------------------------------------------------------------------
    property p_same_cycle_net_neutral;
        @(posedge clk) disable iff (rst)
            (acquire_ack && release_req && (credits < CW'(MAX_CREDITS)))
                |=> (credits == $past(credits));
    endproperty
    a_same_cycle_net_neutral:
        assert property (p_same_cycle_net_neutral)
        else $error("sos_credit_counter: simultaneous acquire+release was not net-neutral");

endmodule

`default_nettype wire
