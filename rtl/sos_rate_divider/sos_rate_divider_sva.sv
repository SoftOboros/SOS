// =============================================================================
// sos_rate_divider_sva.sv  --  SVA assertion module for sos_rate_divider.
//
// @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.11 SVA property list
//   Bound on this primitive after 2026-05-23 §15 ratification (initial entry)
//   and the 2026-05-23 continuation-amendment PCDN walkthrough: a tick-driven
//   rate divider with bare `tick_in` / `tick_out` pulses, mandatory DIVISOR
//   and INITIAL_COUNTER generics, sync active-high reset, exposed `counter`.
//   See `sos_rate_divider.sv` header for the full invariant list this module
//   rides.
//
//   Per PCDN-A-bind-form resolved 2026-05-23 (§15 third entry): SVA binds
//   across all SOS-08-A primitives are **module-type** bind directives
//   (Verilator-compatible).  The bind directive lives in
//   `tb/sos_rate_divider/sos_rate_divider_bind.sv`; this file is the
//   assertion module the bind directive instantiates.
//
// Cited invariants:
//   INV-SOS-A, INV-SOS-B, INV-SOS-E, INV-SOS-G, INV-SOS-H  (SOS-07 §6)
//   INV-S-HDL-1, INV-S-HDL-2, INV-S-HDL-4, INV-S-HDL-5    (SOS-08 §7)
//   INV-S-HDL-A-1, INV-S-HDL-A-2, INV-S-HDL-A-3,          (SOS-08-A §7)
//   INV-S-HDL-A-4 (N/A counter), INV-S-HDL-A-5
//
// Properties (per §6.11 + task scope):
//   - tick_out_is_pulse      : tick_out is 1-cycle wide (never two
//                              consecutive high cycles unless tick_in
//                              is also continuously high AND DIVISOR=1).
//   - counter_in_range       : counter is always in [0, DIVISOR-1].
//   - counter_resets_to_init : at reset deassertion edge, counter ==
//                              INITIAL_COUNTER.
//   - passthrough_when_divisor_1 : when DIVISOR=1, tick_out == tick_in
//                              every cycle.
//   - tick_out_implies_tick_in : tick_out can only fire on cycles where
//                              tick_in is high.
//   - tick_out_spacing_in_ticks : the number of `tick_in` pulses observed
//                              between two consecutive `tick_out` pulses
//                              is exactly DIVISOR.  This is the
//                              `ratio_stable` property reformulated to
//                              count tick_in pulses (the divider's natural
//                              metric) rather than clock cycles.
//
// Bind target: `sos_rate_divider`.  The assertion module sits as a child of
// the primitive instance; the dotted reference `counter` (and the local
// `counter_q` view of it) resolves via the bind-supplied port.
// =============================================================================

`default_nettype none

module sos_rate_divider_sva #(
    parameter int DIVISOR,
    parameter int INITIAL_COUNTER
) (
    input  wire                                                       clk,
    input  wire                                                       rst,
    input  wire                                                       tick_in,
    input  wire                                                       tick_out,
    input  wire [((DIVISOR > 1) ? $clog2(DIVISOR) : 1) - 1 : 0]        counter
);

  localparam int CNT_W = (DIVISOR > 1) ? $clog2(DIVISOR) : 1;

  // ---------------------------------------------------------------------------
  // Safety: tick_out is a 1-cycle pulse measured against `tick_in` activity.
  //
  // Strict "1-cycle wide" framing: if tick_out is high this cycle and
  // tick_in is still high the next cycle, then tick_out MUST be low next
  // cycle UNLESS DIVISOR=1 (where every tick_in passes through).  The
  // condition is encoded as: tick_out && !DIVISOR_IS_ONE -> ##1 !tick_out
  // (gated on `tick_in` activity isn't strictly necessary because counter
  // resets to 0 on the firing cycle, so a back-to-back tick_in pulse cannot
  // satisfy `at_limit` again until DIVISOR-1 more tick_in pulses arrive).
  // ---------------------------------------------------------------------------
  generate
    if (DIVISOR == 1) begin : g_pulse_d1
      // DIVISOR=1: tick_out passthrough; the "1-cycle pulse" claim degenerates
      // to "tick_out tracks tick_in exactly", checked by passthrough property.
      // No additional assertion needed here.
    end else begin : g_pulse_dn
      property p_tick_out_is_pulse;
        @(posedge clk) disable iff (rst)
          tick_out |-> ##1 !tick_out;
      endproperty
      a_tick_out_is_pulse : assert property (p_tick_out_is_pulse)
        else $error("sos_rate_divider: tick_out asserted two cycles in a row (DIVISOR=%0d)", DIVISOR);
    end
  endgenerate

  // ---------------------------------------------------------------------------
  // Safety: tick_out implies tick_in this same cycle.  (tick_out is
  // combinational `tick_in & at_limit`.)
  // ---------------------------------------------------------------------------
  property p_tick_out_implies_tick_in;
    @(posedge clk) disable iff (rst)
      tick_out |-> tick_in;
  endproperty
  a_tick_out_implies_tick_in : assert property (p_tick_out_implies_tick_in)
    else $error("sos_rate_divider: tick_out asserted without tick_in");

  // ---------------------------------------------------------------------------
  // Safety: counter is always in [0, DIVISOR-1].
  // ---------------------------------------------------------------------------
  property p_counter_in_range;
    @(posedge clk) disable iff (rst)
      counter <= CNT_W'(DIVISOR - 1);
  endproperty
  a_counter_in_range : assert property (p_counter_in_range)
    else $error("sos_rate_divider: counter=%0d exceeds DIVISOR-1=%0d", counter, DIVISOR - 1);

  // ---------------------------------------------------------------------------
  // Safety: reset restores counter to INITIAL_COUNTER.
  //
  // Checked by sampling on the first edge after rst deasserts.  Encoded via
  // `$fell(rst)` so the assertion fires on the cycle reset is removed.
  // ---------------------------------------------------------------------------
  property p_reset_restores_counter;
    @(posedge clk)
      $fell(rst) |-> counter == CNT_W'(INITIAL_COUNTER);
  endproperty
  a_reset_restores_counter : assert property (p_reset_restores_counter)
    else $error("sos_rate_divider: post-reset counter=%0d expected INITIAL_COUNTER=%0d",
                counter, INITIAL_COUNTER);

  // ---------------------------------------------------------------------------
  // Functional: passthrough when DIVISOR=1.
  // ---------------------------------------------------------------------------
  generate
    if (DIVISOR == 1) begin : g_passthrough
      property p_passthrough;
        @(posedge clk) disable iff (rst)
          tick_out == tick_in;
      endproperty
      a_passthrough : assert property (p_passthrough)
        else $error("sos_rate_divider: DIVISOR=1 passthrough violated (tick_in=%0d tick_out=%0d)",
                    tick_in, tick_out);
    end
  endgenerate

  // ---------------------------------------------------------------------------
  // Functional: tick_out spacing measured in tick_in pulses is DIVISOR.
  //
  // Implementation: count `tick_in` pulses between consecutive `tick_out`
  // pulses; assert the count is DIVISOR.  Auxiliary counter `ticks_since`
  // is a verification-only state (not synthesizable; lives in the SVA
  // module).
  //
  // First-window special-case: the very first tick_out after reset fires
  // after only (DIVISOR - INITIAL_COUNTER) tick_in pulses, because the
  // counter starts at INITIAL_COUNTER rather than 0.  We model this by
  // seeding `ticks_since` to INITIAL_COUNTER at reset so the assertion
  // `ticks_since == DIVISOR - 1` holds on the first tick_out too.  After
  // the first tick_out fires the counter reloads to 0 and ticks_since
  // resets, so subsequent windows are full DIVISOR-pulse intervals.
  // ---------------------------------------------------------------------------
  int unsigned ticks_since;

  always_ff @(posedge clk) begin
    if (rst) begin
      ticks_since <= INITIAL_COUNTER;
    end else if (tick_out) begin
      // Just fired; reset the count for the next interval.  Since tick_out
      // implies tick_in this cycle, the firing tick_in IS the last tick_in
      // of the current window; ticks_since rolls over to 0 here.
      ticks_since <= 0;
    end else if (tick_in) begin
      ticks_since <= ticks_since + 1;
    end
  end

  // On every tick_out, the count of tick_in pulses since the previous
  // tick_out (or since reset, seeded by INITIAL_COUNTER) plus 1 for the
  // firing tick_in must equal DIVISOR.  ticks_since counts tick_in pulses
  // observed AFTER the last tick_out (not including the firing tick_in),
  // so the test is `ticks_since == DIVISOR - 1` on the firing cycle for
  // every window including the first.
  property p_tick_out_spacing_in_ticks;
    @(posedge clk) disable iff (rst)
      tick_out |-> ticks_since == DIVISOR - 1;
  endproperty
  a_tick_out_spacing_in_ticks : assert property (p_tick_out_spacing_in_ticks)
    else $error("sos_rate_divider: tick_out fired after ticks_since=%0d tick_in pulses; expected DIVISOR-1=%0d",
                ticks_since, DIVISOR - 1);

endmodule : sos_rate_divider_sva

`default_nettype wire
