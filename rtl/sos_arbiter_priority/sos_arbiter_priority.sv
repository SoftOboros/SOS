// =============================================================================
// sos_arbiter_priority.sv  --  L0 priority arbiter with optional aging
//                              (portable SystemVerilog-2017)
//
// @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.4
//   Per 2026-05-23 initial-draft + ratification (§15 first entry) +
//   impl-wave-1 PCDN amendments (§15 second 2026-05-23 entry).
//
//   Control primitive, bare req/grant naming (PCDN-A-002 ratified for
//   control primitives; arbiters are control primitives per §10).
//   Parameters UPPER_CASE (PCDN-A-001).  Synchronous active-high reset
//   (PCDN-A-003, INV-S-HDL-A-1).  Resource-determining generics are
//   mandatory with no default (PCDN-A-004, INV-S-HDL-A-5).  One-hot
//   internal pointer (INV-S-HDL-A-4, SOS-08 PCDN-002 ratified one-hot
//   at v1).
//
//   GRANT_LATENCY_CYCLES parameter mirrors the sos_arbiter_rr resolution
//   of PCDN-A-arbiter-GRANT_LATENCY_CYCLES (§15 second 2026-05-23 entry).
//   The PCDN text names sos_arbiter_rr specifically; per the task brief
//   this primitive extends the same parameter/default to sos_arbiter_priority
//   for parity across the arbiter family.  Flagged as a §15 amendment
//   extension that the spec doc SHOULD absorb at the next walkthrough.
//
// Cited invariants (this primitive does not redefine them):
//   INV-SOS-A  chart-as-source                     (SOS-07 §6)
//   INV-SOS-B  vectors-as-deliverable              (SOS-07 §6)
//   INV-SOS-E  explicit AuthorityRelationship      (SOS-07 §6)
//   INV-SOS-G  verified-codegen position           (SOS-07 §6)
//   INV-SOS-H  vector-to-chart traceability        (SOS-07 §6)
//   INV-S-HDL-1 handshake-compatible ports         (SOS-08 §7)
//   INV-S-HDL-2 static-allocation discipline       (SOS-08 §7)
//   INV-S-HDL-3 cross-domain isolation             (SOS-08 §7; N/A single-domain)
//   INV-S-HDL-4 cooperative-only at v1             (SOS-08 §7)
//   INV-S-HDL-5 vector-to-chart traceability (HDL) (SOS-08 §7)
//   INV-S-HDL-A-1 uniform sync active-high reset   (SOS-08-A §7)
//   INV-S-HDL-A-2 handshake associativity          (SOS-08-A §7)
//   INV-S-HDL-A-3 vendor-shim byte-identical wrap  (SOS-08-A §7; portable-only)
//   INV-S-HDL-A-4 one-hot internal FSM by default  (SOS-08-A §7)
//   INV-S-HDL-A-5 mandatory parameters, no default (SOS-08-A §7;
//                  named exception for GRANT_LATENCY_CYCLES extended to
//                  this primitive)
//
// Design choices made by this implementation (flagged in the agent report):
//   * Priority direction: HIGHER value wins.
//   * Tie within a priority lane: SHARED round-robin pointer scanning the
//     requester index space (one pointer for the whole arbiter, not a
//     per-lane pointer).
//   * Aging: per-requester unsigned counter, saturating at AGING_THRESHOLD;
//     incremented while req[i] is asserted and not granted; reset on grant
//     or deassertion.  When counter reaches AGING_THRESHOLD the requester's
//     effective priority is promoted by prepending an "aged_flag" MSB,
//     guaranteeing it outranks every non-promoted requester regardless of
//     base priority.
//
// Behavioural contract (per §6.4):
//   eff_prio[i] = { aged_flag[i], priority[i] }  with width PRIORITY_BITS+1.
//   max_prio = max over { eff_prio[i] | req[i] }.
//   top_req[i] = req[i] && (eff_prio[i] == max_prio).
//   The shared round-robin pointer selects one bit of top_req as the winner.
//   At most one grant per cycle.
//
// Fairness bound (AGING_ENABLE = 1):
//   Every continuously-asserted requester is granted within
//   AGING_THRESHOLD + N_REQS cycles.
// =============================================================================

`default_nettype none

module sos_arbiter_priority #(
    // Mandatory: no default per INV-S-HDL-A-5.
    parameter int N_REQS,
    // Mandatory: no default.  Width of the per-requester priority field.
    parameter int PRIORITY_BITS,
    // Mandatory: no default.  1 = aging enabled; 0 = strict priority.
    parameter int AGING_ENABLE,
    // Mandatory: no default.  Counter threshold in clk cycles.  Must be >= 1.
    parameter int AGING_THRESHOLD,
    // See sos_arbiter_rr.  Default 1 (canonical registered shape); 0 opts in
    // to combinational grant forward.  Named exception to INV-S-HDL-A-5 per
    // the second 2026-05-23 §15 entry, extended to this primitive per task brief.
    parameter int GRANT_LATENCY_CYCLES = 1
) (
    input  wire                                       clk,
    input  wire                                       rst,           // sync active-high
    input  wire [N_REQS-1:0]                          req,
    // Flat per-requester priority field.  Slot i occupies bits
    // [(i+1)*PRIORITY_BITS - 1 : i*PRIORITY_BITS].  Higher value = higher priority.
    input  wire [N_REQS*PRIORITY_BITS-1:0]            priority_in,
    output wire [N_REQS-1:0]                          grant,
    // Observability: id of the most recent winner.  Width = $clog2(N_REQS+1).
    // Value N_REQS encodes "no winner yet" (held at reset).
    output reg  [$clog2(N_REQS + 1)-1:0]              last_winner_id
);

  // ---------------------------------------------------------------------------
  // Elaboration-time validation.
  // ---------------------------------------------------------------------------
  initial begin
    if (!(GRANT_LATENCY_CYCLES == 0 || GRANT_LATENCY_CYCLES == 1)) begin
      $fatal(1, "sos_arbiter_priority: SOS-08-A §6.4 supports GRANT_LATENCY_CYCLES in {0, 1} at v1; got %0d",
             GRANT_LATENCY_CYCLES);
    end
    if (!(AGING_ENABLE == 0 || AGING_ENABLE == 1)) begin
      $fatal(1, "sos_arbiter_priority: AGING_ENABLE must be 0 or 1; got %0d",
             AGING_ENABLE);
    end
    if (AGING_THRESHOLD < 1) begin
      $fatal(1, "sos_arbiter_priority: AGING_THRESHOLD must be >= 1; got %0d",
             AGING_THRESHOLD);
    end
    if (PRIORITY_BITS < 1) begin
      $fatal(1, "sos_arbiter_priority: PRIORITY_BITS must be >= 1; got %0d",
             PRIORITY_BITS);
    end
    if (N_REQS < 2) begin
      $fatal(1, "sos_arbiter_priority: N_REQS must be >= 2; got %0d", N_REQS);
    end
  end

  // ---------------------------------------------------------------------------
  // Derived widths.
  // ---------------------------------------------------------------------------
  localparam int ID_W      = $clog2(N_REQS + 1);
  localparam [ID_W-1:0] NO_WINNER = ID_W'(N_REQS);

  // Aging counter must hold the value AGING_THRESHOLD.
  localparam int AGE_W = (AGING_THRESHOLD <= 1) ? 1 : $clog2(AGING_THRESHOLD + 1);

  // Effective priority width: base + 1 MSB for the aged_flag.
  localparam int EFF_W = PRIORITY_BITS + 1;

  // One-hot reset value for `pointer`: only bit 0 set.
  localparam [N_REQS-1:0] POINTER_RESET = { {(N_REQS){1'b0}} } | 1;

  // ---------------------------------------------------------------------------
  // One-hot pointer (INV-S-HDL-A-4).  pointer[i] = 1 means requester i is
  // the round-robin scan anchor for tie-breaking this cycle.
  // ---------------------------------------------------------------------------
  reg  [N_REQS-1:0] pointer;
  reg  [N_REQS-1:0] grant_q;

  // Aging counter per requester (saturating at AGING_THRESHOLD).
  reg  [AGE_W-1:0]  age_q [0:N_REQS-1];

  // ---------------------------------------------------------------------------
  // Effective priority computation.
  // ---------------------------------------------------------------------------
  wire [PRIORITY_BITS-1:0] base_prio [0:N_REQS-1];
  wire                     aged_flag [0:N_REQS-1];
  wire [EFF_W-1:0]         eff_prio  [0:N_REQS-1];

  generate
    for (genvar gi = 0; gi < N_REQS; gi++) begin : g_eff
      assign base_prio[gi] = priority_in[(gi+1)*PRIORITY_BITS - 1 -: PRIORITY_BITS];
      assign aged_flag[gi] = (AGING_ENABLE == 1) &&
                             (age_q[gi] >= AGE_W'(AGING_THRESHOLD));
      assign eff_prio[gi]  = { aged_flag[gi], base_prio[gi] };
    end
  endgenerate

  // ---------------------------------------------------------------------------
  // Max effective priority over the asserted set.
  // ---------------------------------------------------------------------------
  reg  [EFF_W-1:0] max_prio;
  always_comb begin
    max_prio = '0;
    for (int i = 0; i < N_REQS; i++) begin
      if (req[i] && eff_prio[i] > max_prio) begin
        max_prio = eff_prio[i];
      end
    end
  end

  // ---------------------------------------------------------------------------
  // top_req[i] = req[i] && (eff_prio[i] == max_prio).
  // When req == 0, max_prio = 0 and top_req is all-zero (req gates the AND).
  // ---------------------------------------------------------------------------
  reg  [N_REQS-1:0] top_req;
  always_comb begin
    top_req = '0;
    for (int i = 0; i < N_REQS; i++) begin
      if (req[i] && eff_prio[i] == max_prio) begin
        top_req[i] = 1'b1;
      end
    end
  end

  // ---------------------------------------------------------------------------
  // Round-robin tie-break across the top-priority slice (shared pointer).
  // Identical pattern to sos_arbiter_rr.
  // ---------------------------------------------------------------------------
  reg  [N_REQS-1:0] mask_high;
  reg  [N_REQS-1:0] top_high;
  reg  [N_REQS-1:0] grant_high;
  reg  [N_REQS-1:0] grant_low;
  reg  [N_REQS-1:0] grant_next;

  always_comb begin
    automatic logic started = 1'b0;
    mask_high = '0;
    for (int i = 0; i < N_REQS; i++) begin
      if (started || pointer[i]) begin
        mask_high[i] = 1'b1;
        started      = 1'b1;
      end
    end
  end

  always_comb begin
    top_high = top_req & mask_high;
  end

  always_comb begin
    automatic logic seen = 1'b0;
    grant_high = '0;
    for (int i = 0; i < N_REQS; i++) begin
      if (!seen && top_high[i]) begin
        grant_high[i] = 1'b1;
        seen          = 1'b1;
      end
    end
  end

  always_comb begin
    automatic logic seen = 1'b0;
    grant_low = '0;
    for (int i = 0; i < N_REQS; i++) begin
      if (!seen && top_req[i]) begin
        grant_low[i] = 1'b1;
        seen         = 1'b1;
      end
    end
  end

  always_comb begin
    grant_next = (|top_high) ? grant_high : grant_low;
  end

  // ---------------------------------------------------------------------------
  // Sequential update: pointer + aging counters + observability registers.
  // ---------------------------------------------------------------------------
  always_ff @(posedge clk) begin
    if (rst) begin
      pointer        <= POINTER_RESET;
      grant_q        <= '0;
      last_winner_id <= NO_WINNER;
      for (int i = 0; i < N_REQS; i++) begin
        age_q[i] <= '0;
      end
    end else begin
      grant_q <= grant_next;

      if (|grant_next) begin
        automatic int unsigned winner_idx = 0;
        automatic logic [N_REQS-1:0] pointer_next = '0;
        for (int i = 0; i < N_REQS; i++) begin
          if (grant_next[i]) begin
            winner_idx = i;
          end
        end
        for (int j = 0; j < N_REQS; j++) begin
          pointer_next[j] = ((winner_idx + 1) % N_REQS == j) ? 1'b1 : 1'b0;
        end
        last_winner_id <= ID_W'(winner_idx);
        pointer        <= pointer_next;
      end
      // Pointer held when no grant (INV-S-HDL-A-4).

      // Aging counter update.
      for (int i = 0; i < N_REQS; i++) begin
        if (grant_next[i]) begin
          age_q[i] <= '0;
        end else if (req[i]) begin
          if (age_q[i] < AGE_W'(AGING_THRESHOLD)) begin
            age_q[i] <= age_q[i] + AGE_W'(1);
          end
          // Else saturate: hold value at AGING_THRESHOLD.
        end else begin
          age_q[i] <= '0;
        end
      end
    end
  end

  // ---------------------------------------------------------------------------
  // Grant output selector.
  // ---------------------------------------------------------------------------
  generate
    if (GRANT_LATENCY_CYCLES == 1) begin : g_grant_reg
      assign grant = grant_q;
    end else begin : g_grant_comb
      assign grant = grant_next;
    end
  endgenerate

endmodule : sos_arbiter_priority

`default_nettype wire
