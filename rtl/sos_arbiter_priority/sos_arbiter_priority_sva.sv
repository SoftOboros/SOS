// =============================================================================
// sos_arbiter_priority_sva.sv  --  SVA assertion module for sos_arbiter_priority.
//
// @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.4 SVA property list
//   Bound on this primitive after 2026-05-23 §15 initial-draft +
//   ratification + impl-wave-1 PCDN amendments.  See
//   `sos_arbiter_priority.sv` header for the full invariant list this
//   module rides.
//
//   Per PCDN-A-arbiter-GRANT_LATENCY_CYCLES resolved 2026-05-23 (second
//   §15 entry) — extended to this primitive per task brief: this SVA
//   module accepts a matching GRANT_LATENCY_CYCLES parameter and widens
//   the `eventually_granted` / `bounded_starvation` window to
//   `##[1:AGING_THRESHOLD + N_REQS + GRANT_LATENCY_CYCLES]` so the
//   bounded-liveness property remains valid for both the registered (=1)
//   and combinational (=0) grant shapes.
//
// Cited invariants:
//   INV-SOS-A, INV-SOS-B, INV-SOS-E, INV-SOS-G, INV-SOS-H  (SOS-07 §6)
//   INV-S-HDL-1, INV-S-HDL-2, INV-S-HDL-4, INV-S-HDL-5    (SOS-08 §7)
//   INV-S-HDL-A-1, INV-S-HDL-A-2, INV-S-HDL-A-3,          (SOS-08-A §7)
//   INV-S-HDL-A-4, INV-S-HDL-A-5
//
// Properties (per §6.4 + task scope):
//
//   Safety (always assert):
//     - at_most_one_grant       : $countones(grant) <= 1
//     - grant_implies_req       : grant[i] -> $past(req[i])
//                                 ($past for registered grant; the
//                                 combinational variant collapses the
//                                 cycle and the SVA module is
//                                 parameterised on GRANT_LATENCY_CYCLES
//                                 to bypass the $past for that case.)
//     - pointer_one_hot         : $countones(pointer) == 1
//     - pointer_held_when_idle  : (grant == 0) -> $stable(pointer)
//     - pointer_advances_on_grant : (|grant) -> !$stable(pointer)
//
//   Priority correctness:
//     - highest_prio_wins_strict :
//         when AGING_ENABLE = 0, the winning requester's effective
//         priority (== base priority) is the maximum over all asserted
//         requesters' base priorities.  Encoded as a per-i implication.
//
//   Aging fairness (liveness, bounded):
//     - eventually_granted :
//         under AGING_ENABLE = 1, a continuously-asserted requester is
//         granted within AGING_THRESHOLD + N_REQS + GRANT_LATENCY_CYCLES
//         cycles.  Under AGING_ENABLE = 0 the property is unconditionally
//         disabled (strict priority intentionally permits starvation of
//         the low-priority lane).
//
// Bind target: `sos_arbiter_priority`.  The bind directive lives in
// `tb/sos_arbiter_priority/sos_arbiter_priority_bind.sv`; this file is the
// assertion module that the bind directive instantiates.
//
// Notes on hierarchical references:
//   `pointer` is an internal one-hot register inside `sos_arbiter_priority`.
//   The bind directive places this module as a child of the arbiter
//   instance, so the dotted reference resolves to the parent's register.
// =============================================================================

`default_nettype none

module sos_arbiter_priority_sva #(
    parameter int N_REQS,
    parameter int PRIORITY_BITS,
    parameter int AGING_ENABLE,
    parameter int AGING_THRESHOLD,
    // Mirror of the DUT's GRANT_LATENCY_CYCLES; defaulted to 1 (canonical
    // shape) so bind sites that do not pass it through still produce a
    // sensible bound for the registered-grant variant.
    parameter int GRANT_LATENCY_CYCLES = 1
) (
    input  wire                                  clk,
    input  wire                                  rst,
    input  wire [N_REQS-1:0]                     req,
    input  wire [N_REQS*PRIORITY_BITS-1:0]       priority_in,
    input  wire [N_REQS-1:0]                     grant,
    input  wire [$clog2(N_REQS + 1)-1:0]         last_winner_id,
    // Internal observability for the pointer-advance + one-hot assertions.
    input  wire [N_REQS-1:0]                     pointer
);

  // Liveness bound for the aging path.  When AGING_ENABLE = 1, a
  // continuously-asserted requester takes at most AGING_THRESHOLD cycles
  // to reach the promoted state, then at most N_REQS cycles for the
  // round-robin tie-break window, plus one cycle of register latency on
  // the canonical shape.
  localparam int LIVENESS_BOUND = AGING_THRESHOLD + N_REQS + GRANT_LATENCY_CYCLES;

  // ---------------------------------------------------------------------------
  // Safety: at most one grant per cycle.
  // ---------------------------------------------------------------------------
  property p_at_most_one_grant;
    @(posedge clk) disable iff (rst)
      $countones(grant) <= 1;
  endproperty
  a_at_most_one_grant : assert property (p_at_most_one_grant)
    else $error("sos_arbiter_priority: multiple grants in one cycle: %b", grant);

  // ---------------------------------------------------------------------------
  // Safety: grant implies the requester was asserted on the prior cycle for
  // the registered shape, or on the same cycle for the combinational shape.
  // ---------------------------------------------------------------------------
  generate
    for (genvar gi = 0; gi < N_REQS; gi++) begin : g_grant_implies_req
      if (GRANT_LATENCY_CYCLES == 1) begin : g_reg
        property p_grant_implies_req_reg;
          @(posedge clk) disable iff (rst)
            grant[gi] |-> $past(req[gi]);
        endproperty
        a_grant_implies_req_reg : assert property (p_grant_implies_req_reg)
          else $error("sos_arbiter_priority: spurious grant on req[%0d] (registered)", gi);
      end else begin : g_comb
        property p_grant_implies_req_comb;
          @(posedge clk) disable iff (rst)
            grant[gi] |-> req[gi];
        endproperty
        a_grant_implies_req_comb : assert property (p_grant_implies_req_comb)
          else $error("sos_arbiter_priority: spurious grant on req[%0d] (comb)", gi);
      end
    end
  endgenerate

  // ---------------------------------------------------------------------------
  // Safety: pointer is always one-hot.
  // ---------------------------------------------------------------------------
  property p_pointer_one_hot;
    @(posedge clk) disable iff (rst)
      $countones(pointer) == 1;
  endproperty
  a_pointer_one_hot : assert property (p_pointer_one_hot)
    else $error("sos_arbiter_priority: pointer not one-hot: %b", pointer);

  // ---------------------------------------------------------------------------
  // Safety: pointer held when no grant; advances on grant.
  // ---------------------------------------------------------------------------
  property p_pointer_held_when_no_grant;
    @(posedge clk) disable iff (rst)
      (grant == '0) |-> $stable(pointer);
  endproperty
  a_pointer_held_when_no_grant : assert property (p_pointer_held_when_no_grant)
    else $error("sos_arbiter_priority: pointer moved without a grant");

  property p_pointer_advances_on_grant;
    @(posedge clk) disable iff (rst)
      (|grant) |-> !$stable(pointer);
  endproperty
  a_pointer_advances_on_grant : assert property (p_pointer_advances_on_grant)
    else $error("sos_arbiter_priority: pointer did not advance on grant");

  // ---------------------------------------------------------------------------
  // Priority correctness (strict / aging-disabled path).
  //
  // When AGING_ENABLE = 0, the winning requester must hold the maximum base
  // priority over the asserted set in the same cycle the grant was decided.
  // For the registered shape the decision cycle is one edge earlier, so we
  // use $past on req/priority_in.  For the combinational shape we compare
  // against same-cycle req/priority_in.
  // ---------------------------------------------------------------------------
  function automatic logic [PRIORITY_BITS-1:0] slot_prio (
      input logic [N_REQS*PRIORITY_BITS-1:0] flat,
      input int                              slot
  );
    return flat[slot*PRIORITY_BITS +: PRIORITY_BITS];
  endfunction

  function automatic logic [PRIORITY_BITS-1:0] max_asserted_prio (
      input logic [N_REQS-1:0]               req_v,
      input logic [N_REQS*PRIORITY_BITS-1:0] flat
  );
    logic [PRIORITY_BITS-1:0] m;
    m = '0;
    for (int i = 0; i < N_REQS; i++) begin
      if (req_v[i] && flat[i*PRIORITY_BITS +: PRIORITY_BITS] > m) begin
        m = flat[i*PRIORITY_BITS +: PRIORITY_BITS];
      end
    end
    return m;
  endfunction

  generate
    if (AGING_ENABLE == 0) begin : g_strict_prio
      for (genvar gj = 0; gj < N_REQS; gj++) begin : g_per_winner
        if (GRANT_LATENCY_CYCLES == 1) begin : g_reg
          property p_highest_prio_wins;
            @(posedge clk) disable iff (rst)
              grant[gj] |->
                $past(slot_prio(priority_in, gj)) ==
                $past(max_asserted_prio(req, priority_in));
          endproperty
          a_highest_prio_wins : assert property (p_highest_prio_wins)
            else $error("sos_arbiter_priority: grant[%0d] won but is not top-priority (strict)", gj);
        end else begin : g_comb
          property p_highest_prio_wins;
            @(posedge clk) disable iff (rst)
              grant[gj] |->
                slot_prio(priority_in, gj) == max_asserted_prio(req, priority_in);
          endproperty
          a_highest_prio_wins : assert property (p_highest_prio_wins)
            else $error("sos_arbiter_priority: grant[%0d] won but is not top-priority (strict)", gj);
        end
      end
    end
  endgenerate

  // ---------------------------------------------------------------------------
  // Aging fairness (liveness, bounded).
  //
  // Active only when AGING_ENABLE = 1.  Disabled when aging is off because
  // strict priority intentionally allows the low-priority lane to starve.
  // ---------------------------------------------------------------------------
  generate
    if (AGING_ENABLE == 1) begin : g_aging_liveness
      for (genvar gk = 0; gk < N_REQS; gk++) begin : g_eventually
        property p_eventually_granted;
          @(posedge clk) disable iff (rst)
            req[gk] |-> ##[1:LIVENESS_BOUND] grant[gk];
        endproperty
        a_eventually_granted : assert property (p_eventually_granted)
          else $error("sos_arbiter_priority: req[%0d] not granted within %0d cycles (aging)",
                      gk, LIVENESS_BOUND);
      end
    end
  endgenerate

endmodule : sos_arbiter_priority_sva

`default_nettype wire
