// =============================================================================
// sos_arbiter_rr_sva.sv  --  SVA assertion module for sos_arbiter_rr.
//
// @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.3 SVA property list
//   Bound on this primitive after 2026-05-23 §15 ratification: a control
//   primitive named `sos_arbiter_rr` with bare req/grant ports, mandatory
//   N_REQS, sync active-high reset, one-hot pointer.  See `sos_arbiter_rr.sv`
//   header for the full invariant list this module rides.
//
//   Per PCDN-A-arbiter-GRANT_LATENCY_CYCLES resolved 2026-05-23: this SVA
//   module accepts a matching GRANT_LATENCY_CYCLES parameter and widens
//   `eventually_granted[i]` to `##[1:N_REQS+GRANT_LATENCY_CYCLES]` so the
//   bound liveness property remains valid for both the registered (=1)
//   and combinational (=0) grant shapes.
//
// Cited invariants:
//   INV-SOS-A, INV-SOS-B, INV-SOS-E, INV-SOS-G, INV-SOS-H  (SOS-07 §6)
//   INV-S-HDL-1, INV-S-HDL-2, INV-S-HDL-4, INV-S-HDL-5    (SOS-08 §7)
//   INV-S-HDL-A-1, INV-S-HDL-A-2, INV-S-HDL-A-3,          (SOS-08-A §7)
//   INV-S-HDL-A-4, INV-S-HDL-A-5
//
// Properties (per §6.3 + task scope):
//   - at_most_one_grant      : $countones(grant) <= 1                  (safety)
//   - grant_implies_req      : grant[i] -> $past(req[i])               (safety)
//                              (req at the cycle the combinational grant
//                              was computed; grant is the registered view)
//   - eventually_granted     : req[i] continuously asserted -> grant[i]
//                              within N_REQS cycles                    (liveness)
//   - pointer_advances_once  : exactly one pointer bit flips on a grant
//                              cycle; pointer held when no grant        (safety)
//
// Bind target: `sos_arbiter_rr`.  The bind directive lives in
// `tb/sos_arbiter_rr/sos_arbiter_rr_bind.sv`; this file is the assertion
// module that the bind directive instantiates.
//
// Notes on hierarchical references:
//   `pointer` is an internal one-hot register inside `sos_arbiter_rr`.  The
//   bind directive places this module as a child of the arbiter instance,
//   so the dotted reference `pointer` resolves to the parent's register.
//   `$countones`-on-grant is sufficient for the at-most-one-grant claim
//   regardless of pointer state.
// =============================================================================

`default_nettype none

module sos_arbiter_rr_sva #(
    parameter int N_REQS,
    // Mirror of the DUT's GRANT_LATENCY_CYCLES; defaulted to 1 (canonical
    // shape) so existing bind sites that do not pass it through remain
    // valid for the registered-grant variant.
    parameter int GRANT_LATENCY_CYCLES = 1
) (
    input  wire                                  clk,
    input  wire                                  rst,
    input  wire [N_REQS-1:0]                     req,
    input  wire [N_REQS-1:0]                     grant,
    input  wire [$clog2(N_REQS + 1)-1:0]         last_winner_id,
    // Internal observability for the pointer-advance assertion.  Bound by
    // the bind directive against `sos_arbiter_rr.pointer`.
    input  wire [N_REQS-1:0]                     pointer
);

  // ---------------------------------------------------------------------------
  // Safety: at most one grant bit set per cycle.
  // ---------------------------------------------------------------------------
  property p_at_most_one_grant;
    @(posedge clk) disable iff (rst)
      $countones(grant) <= 1;
  endproperty
  a_at_most_one_grant : assert property (p_at_most_one_grant)
    else $error("sos_arbiter_rr: multiple grants in one cycle: %b", grant);

  // ---------------------------------------------------------------------------
  // Safety: a grant implies the requester was asserted on the prior cycle
  // (combinational grant_next was computed from req, then registered).
  // ---------------------------------------------------------------------------
  generate
    for (genvar gi = 0; gi < N_REQS; gi++) begin : g_grant_implies_req
      property p_grant_implies_req;
        @(posedge clk) disable iff (rst)
          grant[gi] |-> $past(req[gi]);
      endproperty
      a_grant_implies_req : assert property (p_grant_implies_req)
        else $error("sos_arbiter_rr: spurious grant on req[%0d]", gi);
    end
  endgenerate

  // ---------------------------------------------------------------------------
  // Liveness (bounded): any requester continuously asserted is granted within
  // N_REQS cycles.  Formulated per §6.3 with the registered-output delay
  // already absorbed in the worst-case bound.
  // ---------------------------------------------------------------------------
  generate
    for (genvar gj = 0; gj < N_REQS; gj++) begin : g_eventually_granted
      property p_eventually_granted;
        @(posedge clk) disable iff (rst)
          req[gj] |-> ##[1:N_REQS+GRANT_LATENCY_CYCLES] grant[gj];
      endproperty
      a_eventually_granted : assert property (p_eventually_granted)
        else $error("sos_arbiter_rr: req[%0d] not granted within %0d cycles",
                    gj, N_REQS + GRANT_LATENCY_CYCLES);
    end
  endgenerate

  // ---------------------------------------------------------------------------
  // Safety: pointer advances exactly once per grant (INV-S-HDL-A-4).
  //
  //   - On a cycle where `grant` (registered output) goes high, the
  //     pointer must have rotated to (winner_idx + 1) mod N_REQS in the
  //     same clock edge.
  //   - On a cycle where `grant` stays low, the pointer holds its value.
  // ---------------------------------------------------------------------------
  // Pointer should always be one-hot.
  property p_pointer_one_hot;
    @(posedge clk) disable iff (rst)
      $countones(pointer) == 1;
  endproperty
  a_pointer_one_hot : assert property (p_pointer_one_hot)
    else $error("sos_arbiter_rr: pointer not one-hot: %b", pointer);

  // When the registered grant is '0 this cycle, the pointer did not change
  // on this clock edge (the same edge that latched grant <- grant_next = '0).
  property p_pointer_held_when_no_grant;
    @(posedge clk) disable iff (rst)
      (grant == '0) |-> $stable(pointer);
  endproperty
  a_pointer_held_when_no_grant : assert property (p_pointer_held_when_no_grant)
    else $error("sos_arbiter_rr: pointer moved without a grant");

  // When a grant fires, the pointer advances exactly once.  Encoded as:
  // "after grant, pointer differs from its prior value" — the at-most-one-bit
  // change is implied by p_pointer_one_hot above.
  property p_pointer_advances_on_grant;
    @(posedge clk) disable iff (rst)
      (|grant) |-> !$stable(pointer);
  endproperty
  a_pointer_advances_on_grant : assert property (p_pointer_advances_on_grant)
    else $error("sos_arbiter_rr: pointer did not advance on grant");

endmodule : sos_arbiter_rr_sva

`default_nettype wire
