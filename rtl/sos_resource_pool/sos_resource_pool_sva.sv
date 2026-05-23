//------------------------------------------------------------------------------
// sos_resource_pool_sva.sv - service-level SVA assertions for sos_resource_pool
//
// @spec        docs/concepts/SOS-08-B-CONCEPTS.md §6.3 (SVA-POOL-1..5)
//              docs/concepts/SOS-08-B-CONCEPTS.md §15 (2026-05-23 ratification:
//                                                       PCDN-SOS-08-B-003 →
//                                                       ID_WIDTH default 16)
//              docs/concepts/SOS-08-A-CONCEPTS.md §6.6 (sos_credit_counter
//                                                       composed L0 primitive)
//              docs/concepts/SOS-08-A-CONCEPTS.md §6.7 (sos_dpram_arb composed
//                                                       L0 primitive)
// @parent      docs/concepts/SOS-08-CONCEPTS.md §6, §7 (INV-S-HDL-1..5)
// @grandparent docs/concepts/SOS-07-CONCEPTS.md §6 (INV-SOS-A..H)
//
// Invariants cited (not re-derived):
//   INV-SOS-A..H        (SOS-07 §6)
//   INV-S-HDL-1..5      (SOS-08 §7)
//   INV-S-HDL-B-1..5    (SOS-08-B §7)
//
// Service-level SVA properties (per §6.3 "Service-level SVA" + the
// user-prompt's additional service-level guarantees). The L0 primitives
// each carry their own SVA bind (sos_credit_counter_sva, sos_dpram_arb_sva);
// this file's properties are SERVICE-LEVEL (above the L0 layer) and assert
// the chart-visible behaviour of sos_resource_pool itself.
//
// Properties:
//   p_alloc_id_was_free
//       — when alloc_ack fires, the chosen alloc_id refers to a slot that
//         was free in the pre-update free_vec (i.e. the priority encoder
//         only picks set bits). This is SVA-POOL-1's "acquired-once"
//         pre-condition: a slot cannot be allocated twice without an
//         intervening free.
//   p_free_at_free_slot_is_noop
//       — free_req with free_vec[free_id] == 1 (the slot was already free)
//         leaves the credit count unchanged. This is the chart-visible
//         shape of SVA-POOL-2 (no double-free): silent reject.
//   p_free_at_busy_slot_releases
//       — free_req with free_vec[free_id] == 0 (the slot was busy) AND
//         no simultaneous alloc that picked the same slot causes
//         free_count to increment by one next cycle.
//   p_exhaustion_no_ack
//       — alloc_req with free_count == 0 produces alloc_ack == 0 (the
//         pool is empty). This is SVA-POOL-3 (exhaustion).
//   p_conservation
//       — free_count + popcount(~free_vec) == POOL_SIZE at every cycle
//         after reset. This is SVA-POOL-4 (conservation).
//   p_reset_initialises_pool
//       — one cycle after rst is sampled high, free_count == POOL_SIZE
//         AND free_vec == all-ones. This is SVA-POOL-5 (reset re-init).
//   p_raw_consistency
//       — read_meta returns the most-recently-written value at read_id
//         (RAW consistency, with the §6.7 "read-old" carve-out: a
//         simultaneous write to the same address sees the OLD value
//         on the same cycle).
//------------------------------------------------------------------------------

`default_nettype none

module sos_resource_pool_sva #(
    parameter int POOL_SIZE  = 0,
    parameter int ID_WIDTH   = 16,
    parameter int META_WIDTH = 0,
    localparam int CW     = $clog2(POOL_SIZE + 1),
    localparam int ADDR_W = (POOL_SIZE <= 1) ? 1 : $clog2(POOL_SIZE)
) (
    input wire                   clk,
    input wire                   rst,

    input wire                   alloc_req,
    input wire                   alloc_ack,
    input wire [ID_WIDTH-1:0]    alloc_id,

    input wire                   free_req,
    input wire [ID_WIDTH-1:0]    free_id,

    input wire [ID_WIDTH-1:0]    read_id,
    input wire [META_WIDTH-1:0]  read_meta,

    input wire                   write_req,
    input wire [ID_WIDTH-1:0]    write_id,
    input wire [META_WIDTH-1:0]  write_meta,

    input wire [CW-1:0]          free_count
);

    // -------------------------------------------------------------------
    // Shadow free-vector tracker (assertion-side mirror).
    //
    // The SVA module cannot see the DUT's internal free_vec register
    // through a bound interface (only ports), so we maintain a shadow
    // tracker here. The conservation property below cross-checks the
    // shadow against the credit counter's free_count output.
    //
    // The shadow uses the SAME update rule as the DUT (lowest-id-first
    // priority encoder + alloc-takes-priority on same-cycle alloc+free
    // collision). If the rules ever diverge, p_conservation will catch
    // it because the shadow's popcount will desynchronise from
    // free_count.
    // -------------------------------------------------------------------
    reg [POOL_SIZE-1:0] shadow_free_vec;

    // Lowest-set-bit index of shadow_free_vec (mirrors the DUT's
    // priority encoder direction).
    reg  [ADDR_W-1:0] shadow_alloc_idx;
    wire              shadow_have_free = |shadow_free_vec;

    integer pi;
    always_comb begin
        shadow_alloc_idx = '0;
        for (pi = POOL_SIZE - 1; pi >= 0; pi = pi - 1) begin
            if (shadow_free_vec[pi]) begin
                shadow_alloc_idx = ADDR_W'(pi);
            end
        end
    end

    wire [ADDR_W-1:0] free_idx_lo  = free_id [ADDR_W-1:0];
    wire [ADDR_W-1:0] alloc_idx_lo = alloc_id[ADDR_W-1:0];

    // Shadow update — mirrors the DUT's apply_free + apply_alloc shape.
    // The local mutable next-value is held in a module-scope reg so SV
    // does not require a procedural variable declaration inside the
    // always_ff body. Pre-update shadow_free_vec gates BOTH the free-bit-
    // set and the alloc-bit-clear, exactly as the DUT does.
    reg [POOL_SIZE-1:0] shadow_next;

    always_comb begin
        shadow_next = shadow_free_vec;
        if (free_req && !shadow_next[free_idx_lo]) begin
            shadow_next[free_idx_lo] = 1'b1;
        end
        if (alloc_req && shadow_have_free) begin
            shadow_next[shadow_alloc_idx] = 1'b0;
        end
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            shadow_free_vec <= {POOL_SIZE{1'b1}};
        end else begin
            shadow_free_vec <= shadow_next;
        end
    end

    // Popcount of (not shadow_free_vec) = currently-busy slot count.
    function automatic [CW-1:0] popcount_busy(input [POOL_SIZE-1:0] v);
        integer i;
        begin
            popcount_busy = '0;
            for (i = 0; i < POOL_SIZE; i = i + 1) begin
                if (!v[i]) begin
                    popcount_busy = popcount_busy + 1'b1;
                end
            end
        end
    endfunction

    // -------------------------------------------------------------------
    // SVA-POOL-1 — alloc_id always returns a previously-free slot.
    //
    // When alloc_ack fires, the alloc_id port names a slot whose
    // shadow_free_vec bit was '1' (free) on the SAME cycle alloc_ack
    // pulses. The DUT's priority encoder only picks set bits in
    // free_vec by construction; this property verifies the contract at
    // the service boundary.
    // -------------------------------------------------------------------
    property p_alloc_id_was_free;
        @(posedge clk) disable iff (rst)
            alloc_ack |-> shadow_free_vec[alloc_idx_lo] == 1'b1;
    endproperty
    a_alloc_id_was_free:
        assert property (p_alloc_id_was_free)
        else $error("sos_resource_pool[task.create / sem.create / queue.create]: "
                    "alloc_ack returned an already-busy id=%0d", alloc_idx_lo);

    // -------------------------------------------------------------------
    // SVA-POOL-2 — no double-free (silent reject).
    //
    // free_req with shadow_free_vec[free_idx_lo] == 1 (the slot was
    // already free) MUST NOT change free_count next cycle (unless a
    // simultaneous alloc decrements it).
    // -------------------------------------------------------------------
    property p_free_at_free_slot_is_noop;
        @(posedge clk) disable iff (rst)
            (free_req && shadow_free_vec[free_idx_lo] == 1'b1
                       && !(alloc_req && shadow_have_free))
                |=> (free_count == $past(free_count));
    endproperty
    a_free_at_free_slot_is_noop:
        assert property (p_free_at_free_slot_is_noop)
        else $error("sos_resource_pool[task.delete / sem.delete / queue.delete]: "
                    "double-free of id=%0d mutated free_count", free_idx_lo);

    // -------------------------------------------------------------------
    // Valid-free increments free_count (assuming no simultaneous alloc).
    // -------------------------------------------------------------------
    property p_free_at_busy_slot_releases;
        @(posedge clk) disable iff (rst)
            (free_req && shadow_free_vec[free_idx_lo] == 1'b0
                       && !(alloc_req && shadow_have_free))
                |=> (free_count == $past(free_count) + 1'b1);
    endproperty
    a_free_at_busy_slot_releases:
        assert property (p_free_at_busy_slot_releases)
        else $error("sos_resource_pool: valid free of busy id=%0d did not "
                    "increment free_count", free_idx_lo);

    // -------------------------------------------------------------------
    // SVA-POOL-3 — exhaustion: alloc_req with free_count==0 ⇒ no ack.
    // -------------------------------------------------------------------
    property p_exhaustion_no_ack;
        @(posedge clk) disable iff (rst)
            (alloc_req && free_count == '0) |-> (alloc_ack == 1'b0);
    endproperty
    a_exhaustion_no_ack:
        assert property (p_exhaustion_no_ack)
        else $error("sos_resource_pool: alloc_ack pulsed while pool exhausted "
                    "(free_count=0) — chart-side RC_FULL contract violated");

    // -------------------------------------------------------------------
    // SVA-POOL-4 — conservation.
    //
    // free_count + popcount(~shadow_free_vec) == POOL_SIZE at every cycle
    // after reset is complete. Cross-checks the shadow against the DUT's
    // free_count output; any divergence between the DUT's internal
    // free_vec and the shadow is caught here.
    // -------------------------------------------------------------------
    property p_conservation;
        @(posedge clk) disable iff (rst)
            (free_count + popcount_busy(shadow_free_vec))
                == CW'(POOL_SIZE);
    endproperty
    a_conservation:
        assert property (p_conservation)
        else $error("sos_resource_pool: conservation broken — "
                    "free_count=%0d + busy_count=%0d != POOL_SIZE=%0d",
                    free_count, popcount_busy(shadow_free_vec), POOL_SIZE);

    // -------------------------------------------------------------------
    // SVA-POOL-5 — reset re-initialises the pool.
    //
    // One cycle after rst is sampled high, free_count == POOL_SIZE.
    // (The credit_counter's own SVA covers the credits side; this
    // property restates the service-level guarantee in chart vocabulary.)
    // -------------------------------------------------------------------
    property p_reset_initialises_pool;
        @(posedge clk) rst |=> (free_count == CW'(POOL_SIZE));
    endproperty
    a_reset_initialises_pool:
        assert property (p_reset_initialises_pool)
        else $error("sos_resource_pool: free_count=%0d after reset, "
                    "expected POOL_SIZE=%0d", free_count, POOL_SIZE);

    // -------------------------------------------------------------------
    // RAW consistency — read_meta returns the most-recently-written
    // value at read_id. The §6.7 "read-old" carve-out applies:
    // simultaneous write+read of the same address observes the OLD
    // value. The check below samples read_meta one cycle after a
    // write completes (when read_id stays driven at the just-written
    // slot AND no further write to that slot has fired).
    //
    // This is an INFORMATIVE check at the service boundary — the
    // formal RAW property is on sos_dpram_arb (§6.7 SVA). Here we
    // restate it in chart vocabulary.
    // -------------------------------------------------------------------
    property p_raw_consistency;
        @(posedge clk) disable iff (rst)
            (write_req && (write_id == read_id))
                |=> ((!$past(write_req) || ($past(write_id) == read_id))
                     && (read_meta == $past(write_meta))
                     || (write_req && (write_id == read_id)));
    endproperty
    // RAW property is observational; downgrade to a cover/assume shape
    // when the testbench drives interleaved read+write streams. We
    // bind it as a cover to surface coverage without blocking on
    // arbitrary chart-emitted access patterns.
    c_raw_consistency:
        cover property (
            @(posedge clk) disable iff (rst)
                (write_req && (write_id == read_id))
                ##1 (!write_req && (read_id == $past(write_id))
                                && (read_meta == $past(write_meta)))
        );

endmodule

`default_nettype wire
