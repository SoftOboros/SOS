// =============================================================================
// sos_rate_divider.sv  --  L0 programmable rate divider (portable SV-2017)
//
// @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.11
//   Per 2026-05-23 ratification (§15 initial entry) and the 2026-05-23
//   continuation-amendment PCDN walkthrough (§15 second + third 2026-05-23
//   entries): control primitive, tick-style 1-cycle-pulse i/o (PCDN-A-002
//   degenerate-pulse form for rate primitives -- §10 reconciliation row),
//   parameters UPPER_CASE (PCDN-A-001), synchronous active-high reset
//   (PCDN-A-003, INV-S-HDL-A-1).  INV-S-HDL-A-4 (one-hot internal FSM) is
//   N/A here -- the counter is a binary counter, not an FSM.
//
//   Per task scope (2026-05-23 walkthrough amendments folded against §6.11):
//     * The divider is **tick-driven**: the internal counter advances on
//       each asserted `tick_in`, not on every `clk` edge.  When `tick_in`
//       is idle, the counter holds.  Natural composition with an upstream
//       `sos_tick_gen` (§6.8).
//     * `DIVISOR` is a **mandatory** parameter (INV-S-HDL-A-5) with the
//       static-elaboration constraint `DIVISOR >= 1`.  `DIVISOR = 0` is
//       **forbidden** (rather than degenerate "no ticks ever") so the
//       counter range invariant `[0, DIVISOR-1]` stays well-defined; a
//       chart that wants "no ticks" gates `tick_in` instead.
//     * `INITIAL_COUNTER` is a **mandatory** parameter (INV-S-HDL-A-5) with
//       constraint `0 <= INITIAL_COUNTER < DIVISOR`.  Allows N parallel
//       instances to be staggered in phase off a shared `tick_in`.
//     * Degenerate case `DIVISOR = 1`: every `tick_in` pulse produces a
//       `tick_out` pulse the same cycle (passthrough).
//     * `counter` is exposed as an observability port (width
//       `$clog2(DIVISOR)` minimum 1) carrying the current counter value.
//
// Cited invariants (this primitive does not redefine them):
//   INV-SOS-A   chart-as-source                     (SOS-07 §6)
//   INV-SOS-B   vectors-as-deliverable              (SOS-07 §6)
//   INV-SOS-E   explicit AuthorityRelationship      (SOS-07 §6)
//   INV-SOS-G   verified-codegen position           (SOS-07 §6)
//   INV-SOS-H   vector-to-chart traceability        (SOS-07 §6)
//   INV-S-HDL-1 handshake-compatible ports          (SOS-08 §7; pulse form)
//   INV-S-HDL-2 static-allocation discipline        (SOS-08 §7)
//   INV-S-HDL-3 cross-domain isolation              (SOS-08 §7; N/A)
//   INV-S-HDL-4 cooperative-only at v1              (SOS-08 §7)
//   INV-S-HDL-5 vector-to-chart traceability (HDL)  (SOS-08 §7)
//   INV-S-HDL-A-1 uniform sync active-high reset    (SOS-08-A §7)
//   INV-S-HDL-A-2 handshake associativity           (SOS-08-A §7)
//   INV-S-HDL-A-3 vendor-shim byte-identical wrap   (SOS-08-A §7; portable-only)
//   INV-S-HDL-A-4 one-hot internal FSM by default   (SOS-08-A §7; N/A counter)
//   INV-S-HDL-A-5 mandatory parameters, no default  (SOS-08-A §7)
//
// Behavioural contract:
//   counter starts at INITIAL_COUNTER on reset.  On every cycle that
//   `tick_in` is asserted:
//     * If counter == DIVISOR-1, `tick_out` pulses for one cycle and
//       counter is loaded with 0.
//     * Otherwise, counter increments by 1 and `tick_out` stays low.
//   When `tick_in` is low, `tick_out` is low and counter is held.
//
// Resource cost:
//   $clog2(DIVISOR) counter FFs + a single comparator + a 1-bit AND.
// =============================================================================

`default_nettype none

module sos_rate_divider #(
    // Mandatory: no default per INV-S-HDL-A-5.  DIVISOR >= 1; DIVISOR = 0
    // is forbidden (header behavioural contract note).
    parameter int DIVISOR,
    // Mandatory: no default per INV-S-HDL-A-5.  0 <= INITIAL_COUNTER < DIVISOR.
    parameter int INITIAL_COUNTER
) (
    input  wire                                       clk,
    input  wire                                       rst,       // sync active-high
    input  wire                                       tick_in,
    output wire                                       tick_out,
    // Observability: current counter value, width = $clog2(DIVISOR), at
    // least 1 bit so DIVISOR=1 still has a well-formed port.
    output wire [((DIVISOR > 1) ? $clog2(DIVISOR) : 1) - 1 : 0] counter
);

  // Elaboration-time validation of the parameter bounds.
  // Per PCDN-A-004 / INV-S-HDL-A-5 + the §6.11 contract notes.
  initial begin
    if (!(DIVISOR >= 1)) begin
      $fatal(1, "sos_rate_divider: SOS-08-A §6.11 requires DIVISOR >= 1; got %0d",
             DIVISOR);
    end
    if (!(INITIAL_COUNTER >= 0 && INITIAL_COUNTER < DIVISOR)) begin
      $fatal(1, "sos_rate_divider: SOS-08-A §6.11 requires 0 <= INITIAL_COUNTER < DIVISOR; got INITIAL_COUNTER=%0d DIVISOR=%0d",
             INITIAL_COUNTER, DIVISOR);
    end
  end

  // Counter width.  Minimum 1 bit so DIVISOR = 1 still elaborates with a
  // legal port (the bit is permanently 0).
  localparam int CNT_W = (DIVISOR > 1) ? $clog2(DIVISOR) : 1;

  // ---------------------------------------------------------------------------
  // Counter register (tick-driven).
  // ---------------------------------------------------------------------------
  reg  [CNT_W-1:0] counter_q;

  // Threshold comparator.  For DIVISOR=1 this is `counter_q == 0`, which is
  // permanently true after reset (INITIAL_COUNTER must be 0 in that case)
  // and re-asserted by the `tick_in && at_limit -> 0` reload branch, giving
  // the passthrough degenerate case.
  wire at_limit = (counter_q == CNT_W'(DIVISOR - 1));

  // Combinational tick_out: a qualifying tick_in arrives and the counter is
  // at the divide threshold.
  assign tick_out = tick_in & at_limit;

  // ---------------------------------------------------------------------------
  // Sequential counter update.
  // ---------------------------------------------------------------------------
  always_ff @(posedge clk) begin
    if (rst) begin
      counter_q <= CNT_W'(INITIAL_COUNTER);
    end else if (tick_in) begin
      if (at_limit) begin
        counter_q <= '0;
      end else begin
        counter_q <= counter_q + CNT_W'(1);
      end
    end
    // tick_in = 0 -> counter holds.
  end

  assign counter = counter_q;

endmodule : sos_rate_divider

`default_nettype wire
