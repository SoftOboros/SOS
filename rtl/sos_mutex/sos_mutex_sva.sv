//------------------------------------------------------------------------------
// sos_mutex_sva.sv - SVA assertion module for sos_mutex
//
// @spec       docs/concepts/SOS-08-A-CONCEPTS.md §6.5 (SVA properties)
// @parent     docs/concepts/SOS-08-CONCEPTS.md §6 (L0 set), §7 (INV-S-HDL-1..5)
// @grandparent docs/concepts/SOS-07-CONCEPTS.md §6 (INV-SOS-A..H)
//
// Invariants cited (not re-derived):
//   INV-SOS-A..H        (SOS-07 §6)
//   INV-S-HDL-1..5      (SOS-08 §7)
//   INV-S-HDL-A-1..5    (SOS-08-A §7)
//
// Properties (per §6.5):
//   mutual_exclusion        — at most one ack[i] = 1 at any cycle.
//   grant_implies_req       — ack[i] only when req[i] was high last cycle (or held).
//   release_only_by_holder  — holder_id matches the asserted ack slot.
//   fairness_rr             — a continuously-asserted req[i] is acked within
//                             N_CLIENTS cycles (round-robin bound).
//   locked_consistent       — locked == 1 iff some ack bit is set.
//   no_grant_under_reset    — ack is zero during reset (sync active-high).
//------------------------------------------------------------------------------

`default_nettype none

module sos_mutex_sva #(
    parameter int N_CLIENTS,
    localparam int HID_W = $clog2(N_CLIENTS + 1)
) (
    input wire                 clk,
    input wire                 rst,
    input wire [N_CLIENTS-1:0] req,
    input wire [N_CLIENTS-1:0] ack,
    input wire                 locked,
    input wire [HID_W-1:0]     holder_id
);

    // ----- mutual_exclusion --------------------------------------------------
    // At any cycle, at most one ack bit is asserted.
    property p_mutual_exclusion;
        @(posedge clk) disable iff (rst)
            $countones(ack) <= 1;
    endproperty
    a_mutual_exclusion:
        assert property (p_mutual_exclusion)
        else $error("sos_mutex: mutual_exclusion violated, ack=%b", ack);

    // ----- grant_implies_req -------------------------------------------------
    // ack[i] high implies req[i] was high on the prior cycle.
    // (The acquire arbitration sees `req` in cycle N and grants in cycle N+1.)
    generate
        for (genvar gi = 0; gi < N_CLIENTS; gi++) begin : g_grant_implies_req
            property p_gir;
                @(posedge clk) disable iff (rst)
                    ack[gi] |-> $past(req[gi], 1);
            endproperty
            a_grant_implies_req:
                assert property (p_gir)
                else $error("sos_mutex: ack[%0d] without prior req[%0d]", gi, gi);
        end
    endgenerate

    // ----- release_only_by_holder --------------------------------------------
    // Whenever ack[i] is set, holder_id == i.
    generate
        for (genvar gi = 0; gi < N_CLIENTS; gi++) begin : g_release_only_by_holder
            property p_robh;
                @(posedge clk) disable iff (rst)
                    ack[gi] |-> (holder_id == HID_W'(gi));
            endproperty
            a_release_only_by_holder:
                assert property (p_robh)
                else $error("sos_mutex: ack[%0d] but holder_id=%0d", gi, holder_id);
        end
    endgenerate

    // ----- locked_consistent -------------------------------------------------
    // `locked` is high iff exactly one ack bit is set.
    property p_locked_consistent;
        @(posedge clk) disable iff (rst)
            locked == ($countones(ack) == 1);
    endproperty
    a_locked_consistent:
        assert property (p_locked_consistent)
        else $error("sos_mutex: locked=%b but ack=%b", locked, ack);

    // ----- no_grant_under_reset ----------------------------------------------
    // During reset, no ack bit is set.
    property p_no_grant_under_reset;
        @(posedge clk) rst |-> (ack == '0);
    endproperty
    a_no_grant_under_reset:
        assert property (p_no_grant_under_reset)
        else $error("sos_mutex: ack=%b asserted during reset", ack);

    // ----- fairness_rr -------------------------------------------------------
    // A continuously-asserted req[i] is granted (ack[i] high) within
    // N_CLIENTS cycles. The round-robin pointer guarantees this bound: even
    // if every other client also requests, the rotation reaches i in at most
    // N_CLIENTS-1 grant-resolutions; since each grant takes 1 cycle to resolve
    // when Free, and at most 1 cycle is spent in Held before the holder may
    // release (under the chart bound; verified by chart bound-analysis per
    // INV-SOS-G), this is the bounded liveness property.
    //
    // We express the SVA-checkable subset: req[i] held continuously implies
    // ack[i] within N_CLIENTS cycles, given the holder releases each cycle.
    // The unbounded-hold case is dispatched to the chart bound (CHART_BOUND)
    // per SOS-08-A §6.5; this assertion checks the arbiter-fairness bound.
    generate
        for (genvar gi = 0; gi < N_CLIENTS; gi++) begin : g_fairness_rr
            property p_fairness;
                @(posedge clk) disable iff (rst)
                    (req[gi] && !ack[gi]) |-> ##[1:N_CLIENTS] ack[gi] || !req[gi];
            endproperty
            a_fairness_rr:
                assert property (p_fairness)
                else $error("sos_mutex: req[%0d] not granted within N_CLIENTS cycles", gi);
        end
    endgenerate

endmodule

`default_nettype wire
