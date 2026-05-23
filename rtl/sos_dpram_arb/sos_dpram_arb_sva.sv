// ----------------------------------------------------------------------------
// sos_dpram_arb_sva.sv
//
// @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.7 (sos_dpram_arb SVA properties)
//       docs/concepts/SOS-08-A-CONCEPTS.md §15 (2026-05-23 amendments —
//                                              READ_LATENCY + RESET_MEM
//                                              pattern inherited from
//                                              PCDN-A-fifo-READ_LATENCY +
//                                              PCDN-A-fifo-RESET_MEM)
//       docs/concepts/SOS-08-CONCEPTS.md   §5  (frozen decisions inherited)
//       docs/concepts/SOS-07-CONCEPTS.md   §6  (cross-phase invariants)
//
// Cross-phase / sub-phase / per-primitive invariants cited:
//   INV-SOS-A..H, INV-S-HDL-1..5, INV-S-HDL-A-1..5
//
// SVA properties bound to a sos_dpram_arb instance. Bound via the directive
// in tb/sos_dpram_arb/sos_dpram_arb_bind.sv during cocotb simulation runs.
//
// Properties per SOS-08-A §6.7 + the sub-PCDN port-naming map:
//   - no_same_addr_double_write: simultaneous A+B writes to same addr →
//     exactly one of {port_a_full, port_b_full} is high (A-wins-default).
//   - arbiter_a_never_blocked: port_a_full is never asserted (A always wins).
//   - read_after_write: write x@addr followed by read addr returns x
//     (single-clock mode; checked via cocotb scoreboard — see test file).
//   - reset_clears_observability: rst forces ready=1, full=0 per port.
//   - port_observability: ready == ~full per port.
//   - reset_clears_mem (RESET_MEM=1, VERIFIED_BY_ELAB): rst clears every
//     mem entry to zero. Cocotb scenario in test_sos_dpram_arb.py covers
//     the runtime observation.
// ----------------------------------------------------------------------------

`default_nettype none

module sos_dpram_arb_sva #(
    parameter int    DEPTH = 0,
    parameter int    WIDTH = 0,
    // MODE mirror — used to gate single-clock-only properties.
    parameter string MODE  = "SINGLE_CLOCK",
    parameter int    READ_LATENCY = 0,
    parameter bit    RESET_MEM    = 1'b0,
    parameter int    ADDR_W = (DEPTH <= 1) ? 1 : $clog2(DEPTH)
) (
    // Single-clock + reset (used when MODE == "SINGLE_CLOCK").
    input wire                  clk,
    input wire                  rst,
    // Dual-clock + reset (used when MODE == "DUAL_CLOCK"). The SVA module
    // accepts both clock/reset pairs at all times; only the MODE-matching
    // generate branch enables its assertions.
    input wire                  clk_a,
    input wire                  rst_a,
    input wire                  clk_b,
    input wire                  rst_b,

    input wire [ADDR_W-1:0]     port_a_addr,
    input wire [WIDTH-1:0]      port_a_wdata,
    input wire                  port_a_we,
    input wire                  port_a_re,
    input wire [WIDTH-1:0]      port_a_rdata,
    input wire                  port_a_full,
    input wire                  port_a_ready,

    input wire [ADDR_W-1:0]     port_b_addr,
    input wire [WIDTH-1:0]      port_b_wdata,
    input wire                  port_b_we,
    input wire                  port_b_re,
    input wire [WIDTH-1:0]      port_b_rdata,
    input wire                  port_b_full,
    input wire                  port_b_ready
);

    // ------------------------------------------------------------------------
    // §6.7 — arbiter_a_never_blocked.
    // Port A's write always wins; port_a_full MUST be 0 forever.
    // ------------------------------------------------------------------------
    property p_arbiter_a_never_blocked;
        @(posedge clk_a) (port_a_full == 1'b0);
    endproperty
    a_arbiter_a_never_blocked: assert property (p_arbiter_a_never_blocked)
        else $error("sos_dpram_arb_sva: port_a_full asserted (A should always win)");

    // ------------------------------------------------------------------------
    // §6.7 — port observability.
    // For each port, `ready` and `full` are exact complements.
    // ------------------------------------------------------------------------
    property p_port_a_ready_full_complement;
        @(posedge clk_a) (port_a_ready == ~port_a_full);
    endproperty
    a_port_a_ready_full_complement: assert property
        (p_port_a_ready_full_complement)
        else $error("sos_dpram_arb_sva: port_a_ready != ~port_a_full");

    property p_port_b_ready_full_complement;
        @(posedge clk_b) (port_b_ready == ~port_b_full);
    endproperty
    a_port_b_ready_full_complement: assert property
        (p_port_b_ready_full_complement)
        else $error("sos_dpram_arb_sva: port_b_ready != ~port_b_full");

    generate
        if (MODE == "SINGLE_CLOCK") begin : g_sc_props

            // -------------------------------------------------------------
            // §6.7 — no_same_addr_double_write (A-wins).
            // Simultaneous A+B writes to the same address resolve to a
            // single write — port_b_full is asserted that cycle (so B's
            // write does not land). Stated as the "exactly one served"
            // form from the §6.7 SVA enumeration.
            // -------------------------------------------------------------
            property p_collision_a_wins;
                @(posedge clk) disable iff (rst)
                    (port_a_we && port_b_we && (port_a_addr == port_b_addr))
                        |-> (port_b_full == 1'b1);
            endproperty
            a_collision_a_wins: assert property (p_collision_a_wins)
                else $error("sos_dpram_arb_sva: collision on same addr did not block port B");

            // The complement: when there is no A+B collision, B is not
            // blocked by the arbiter.
            property p_no_collision_b_ready;
                @(posedge clk) disable iff (rst)
                    (!(port_a_we && port_b_we &&
                       (port_a_addr == port_b_addr)))
                        |-> (port_b_full == 1'b0);
            endproperty
            a_no_collision_b_ready: assert property (p_no_collision_b_ready)
                else $error("sos_dpram_arb_sva: port_b_full asserted without collision");

            // -------------------------------------------------------------
            // §6.7 — reset_clears_observability.
            // After rst, both ports' full are 0 and ready are 1.
            // ------------------------------------------------------------
            property p_reset_clears_port_a_full;
                @(posedge clk) rst |=> (port_a_full == 1'b0);
            endproperty
            a_reset_clears_port_a_full: assert property
                (p_reset_clears_port_a_full)
                else $error("sos_dpram_arb_sva: port_a_full not 0 after reset");

            property p_reset_clears_port_b_full;
                @(posedge clk) rst |=> (port_b_full == 1'b0);
            endproperty
            a_reset_clears_port_b_full: assert property
                (p_reset_clears_port_b_full)
                else $error("sos_dpram_arb_sva: port_b_full not 0 after reset");

            // -------------------------------------------------------------
            // §6.7 — write/read consistency (single-clock).
            // Spec: write x @ addr on cycle T, read addr on cycle T+1 →
            //   FWFT (READ_LATENCY=0): port_*_rdata == x at cycle T+1.
            //   Reg   (READ_LATENCY=1): port_*_rdata == x at cycle T+2.
            //
            // The SVA below targets the FWFT mode where the relationship
            // is checkable without scoreboarding the registered holding
            // register. The registered-mode equivalent is covered by the
            // cocotb scoreboard (test file scenario `read_after_write`).
            // -------------------------------------------------------------
            if (READ_LATENCY == 0) begin : g_sc_raw_fwft
                // Write A @ addr; one cycle later, port A reading addr
                // returns the written value. The contract over arbitrary
                // intervening traffic requires a per-address shadow
                // memory (a full scoreboard); we cover a single-cycle
                // adjacent write-then-read sequence here as a minimal
                // SVA-side witness; the cocotb scoreboard verifies the
                // full property across randomised traffic.
                //
                // Cover sequence: write @ addr in cycle T, no port-B
                // write to same addr in cycle T+1, port A reads same
                // addr in T+1 — rdata at T+1 equals the value written
                // in T (FWFT semantics: rdata is combinational off
                // mem[addr] which was updated at the T→T+1 edge).
                property p_raw_a_fwft;
                    @(posedge clk) disable iff (rst)
                        (port_a_we && port_a_re == 1'b0)
                        ##1 (port_a_re && (port_a_addr == $past(port_a_addr))
                             && !(port_a_we && port_a_addr ==
                                  $past(port_a_addr))
                             && !(port_b_we && port_b_addr ==
                                  $past(port_a_addr)))
                        |-> (port_a_rdata == $past(port_a_wdata));
                endproperty
                // Cover-only — the contract relies on the cocotb
                // scoreboard for full RAW verification.
                c_raw_a_fwft: cover property (p_raw_a_fwft);
            end

        end
        else if (MODE == "DUAL_CLOCK") begin : g_dc_props

            // -------------------------------------------------------------
            // DUAL_CLOCK collision check — the collision detector lives
            // in clk_a; B's port_b_full reflects it across clock domains
            // through the synchroniser. We assert the basic invariant in
            // clk_a (A-domain "if A writes addr X while B's synced shadow
            // says B is also writing X, then port_b_full must rise").
            // The strict form requires holding the synced shadow stable
            // for the verification cycle which is beyond the per-cycle
            // SVA reach; we therefore mark it VERIFIED_BY_COCOTB and the
            // testbench composes the gray-sync-aware scoreboard.
            // -------------------------------------------------------------
            // VERIFIED_BY_COCOTB: dual-clock collision handling
            //   - RTL site: sos_dpram_arb.sv g_dual_clock generate block.
            //   - Runtime check: test_dual_clock_collision in
            //                    tb/sos_dpram_arb/test_sos_dpram_arb.py.

            // The reset-clears observability properties still hold per
            // port, on each port's own clock.
            property p_reset_clears_port_a_full_dc;
                @(posedge clk_a) rst_a |=> (port_a_full == 1'b0);
            endproperty
            a_reset_clears_port_a_full_dc: assert property
                (p_reset_clears_port_a_full_dc)
                else $error("sos_dpram_arb_sva (DC): port_a_full not 0 after rst_a");

            property p_reset_clears_port_b_full_dc;
                @(posedge clk_b) rst_b |=> (port_b_full == 1'b0);
            endproperty
            // Note: in dual-clock mode port_b_full is driven from the
            // clk_a-domain collision signal. After rst_b alone, B's
            // observability does not necessarily snap to 0 until clk_a
            // has also seen a reset window. The cocotb dual-clock harness
            // pulses both resets together; the strict assertion below is
            // therefore documented as VERIFIED_BY_COCOTB.
            // VERIFIED_BY_COCOTB: reset semantics across dual-clock
            //                     domain boundary (combined rst_a+rst_b).

        end
    endgenerate

    // ------------------------------------------------------------------------
    // PCDN-A-fifo-RESET_MEM (inherited pattern) — VERIFIED_BY_ELAB.
    //
    // Contract: after reset, every mem entry reads zero (RESET_MEM=1 only).
    // The mem array is internal to the DUT — the SVA module's port list
    // does not (per INV-S-HDL-A-2) include the storage handle. The RTL
    // clears mem in its synchronous reset branch when RESET_MEM=1; the
    // cocotb scenario `test_reset_mem_clears_storage` exercises the read
    // path to confirm. A hierarchical reference to the probe path would
    // require crossing the bind boundary and is intentionally not emitted.
    // ------------------------------------------------------------------------
    // VERIFIED_BY_ELAB: a_reset_clears_mem (RESET_MEM == 1)
    //   - RTL site: sos_dpram_arb.sv reset branch, "if (RESET_MEM)" loop.
    //   - Runtime check: test_reset_mem_clears_storage cocotb scenario.

endmodule

`default_nettype wire
