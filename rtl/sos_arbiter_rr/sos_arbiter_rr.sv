// =============================================================================
// sos_arbiter_rr.sv  --  L0 round-robin arbiter (portable SystemVerilog-2017)
//
// @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.3
//   Per 2026-05-23 ratification (§15): control primitive, bare req/grant
//   (PCDN-A-002 ratified resolution applied to arbiters per task scope).
//   Parameters UPPER_CASE (PCDN-A-001).  Synchronous active-high reset
//   (PCDN-A-003, INV-S-HDL-A-1).  Mandatory N_REQS, no default (PCDN-A-004,
//   INV-S-HDL-A-5).  One-hot internal pointer (INV-S-HDL-A-4, SOS-08
//   PCDN-002 ratified one-hot at v1).
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
//   INV-S-HDL-A-5 mandatory parameters, no default (SOS-08-A §7)
//
// Behavioural contract:
//   The pointer is a one-hot vector naming the *next* round-robin priority
//   anchor.  On any given cycle, the arbiter scans requesters starting at
//   the pointer position, wrapping modulo N_REQS, and grants the first
//   asserted requester it finds.  At most one bit of `grant` is asserted
//   per cycle.  On a grant, the pointer advances one slot past the winner,
//   ensuring a starvation bound of N_REQS cycles per continuously-asserted
//   requester.
//
// Fairness bound:  any requester continuously asserted is granted within
// N_REQS cycles of contention.
// =============================================================================

`default_nettype none

module sos_arbiter_rr #(
    // Mandatory parameter: no default per INV-S-HDL-A-5.
    // Tools that require a default treat the explicit override as the only
    // legal use; omission causes elaboration to fail because the local
    // parameter ID_W derives from it.
    parameter int N_REQS
) (
    input  wire                                       clk,
    input  wire                                       rst,           // sync active-high
    input  wire [N_REQS-1:0]                          req,
    output reg  [N_REQS-1:0]                          grant,
    // Observability: id of the most recent winner.  Width = $clog2(N_REQS+1).
    // Value N_REQS encodes "no winner yet" (held at reset).
    output reg  [$clog2(N_REQS + 1)-1:0]              last_winner_id
);

  // Width of the winner-id field, including the sentinel.
  localparam int ID_W      = $clog2(N_REQS + 1);
  localparam [ID_W-1:0] NO_WINNER = ID_W'(N_REQS);

  // One-hot reset value for `pointer`: only bit 0 set.  Computed via an
  // arithmetic literal so the form is identical for N_REQS == 1 (yields
  // a single-bit `1`) and N_REQS > 1 (yields `'b0...01`).
  localparam [N_REQS-1:0] POINTER_RESET = { {(N_REQS){1'b0}} } | 1;

  // ---------------------------------------------------------------------------
  // One-hot pointer (INV-S-HDL-A-4).  pointer[i] = 1 means requester i holds
  // the highest priority this cycle.  Reset value = pointer[0] = 1.
  // ---------------------------------------------------------------------------
  reg  [N_REQS-1:0] pointer;

  // ---------------------------------------------------------------------------
  // Combinational arbitration: build a priority mask from the pointer, find
  // the lowest-set bit of (req & mask); fall back to lowest-set bit of req
  // for the wrap-around path.
  // ---------------------------------------------------------------------------
  reg  [N_REQS-1:0] mask_high;
  reg  [N_REQS-1:0] req_high;
  reg  [N_REQS-1:0] grant_high;
  reg  [N_REQS-1:0] grant_low;
  reg  [N_REQS-1:0] grant_next;

  // Priority mask: from the asserted bit of one-hot `pointer` upward (toward
  // MSB) is 1; bits below are 0.
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
    req_high = req & mask_high;
  end

  // Lowest-set-bit -> one-hot.  Iterate from low to high; first hit wins.
  always_comb begin
    automatic logic seen = 1'b0;
    grant_high = '0;
    for (int i = 0; i < N_REQS; i++) begin
      if (!seen && req_high[i]) begin
        grant_high[i] = 1'b1;
        seen          = 1'b1;
      end
    end
  end

  always_comb begin
    automatic logic seen = 1'b0;
    grant_low = '0;
    for (int i = 0; i < N_REQS; i++) begin
      if (!seen && req[i]) begin
        grant_low[i] = 1'b1;
        seen         = 1'b1;
      end
    end
  end

  always_comb begin
    grant_next = (|req_high) ? grant_high : grant_low;
  end

  // ---------------------------------------------------------------------------
  // Sequential update of pointer + observability registers.
  // ---------------------------------------------------------------------------
  always_ff @(posedge clk) begin
    if (rst) begin
      pointer        <= POINTER_RESET;
      grant          <= '0;
      last_winner_id <= NO_WINNER;
    end else begin
      grant <= grant_next;

      if (|grant_next) begin
        // Winner index from one-hot grant_next; assemble the new pointer
        // value in a local before issuing a single NBA so we never rely
        // on partial-update + full-vector composition semantics.
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
      // If no grant this cycle, pointer is held (INV-S-HDL-A-4: pointer
      // advances exactly once per grant, never spuriously).
    end
  end

endmodule : sos_arbiter_rr

`default_nettype wire
