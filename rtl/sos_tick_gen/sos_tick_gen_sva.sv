// =============================================================================
// sos_tick_gen_sva.sv  --  SVA assertion module for sos_tick_gen.
//
// @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.8 SVA property list
//   Bound on this primitive after 2026-05-23 §15 ratification: a control
//   primitive named `sos_tick_gen` with bare `enable`/`tick` ports + a
//   modulo `counter` observability port (wave-1 amendment), mandatory
//   PERIOD_CYCLES + INITIAL_PHASE generics, sync active-high reset, no
//   internal FSM.  See `sos_tick_gen.sv` header for the full invariant
//   list this module rides.
//
//   Bind form: module-type bind, per PCDN-A-bind-form resolved
//   2026-05-23 (the bind directive attaches this SVA module to every
//   `sos_tick_gen` instance in the elaborated design; the directive
//   lives in `tb/sos_tick_gen/sos_tick_gen_bind.sv`).
//
// Cited invariants:
//   INV-SOS-A, INV-SOS-B, INV-SOS-E, INV-SOS-G, INV-SOS-H  (SOS-07 §6)
//   INV-S-HDL-1, INV-S-HDL-2, INV-S-HDL-4, INV-S-HDL-5    (SOS-08 §7)
//   INV-S-HDL-A-1, INV-S-HDL-A-2, INV-S-HDL-A-3,          (SOS-08-A §7)
//   INV-S-HDL-A-4, INV-S-HDL-A-5
//
// Properties (per §6.8 + task scope):
//   - tick_is_pulse         : tick |-> ##1 !tick                       (safety)
//                             1-cycle pulse width; never two consecutive
//                             cycles of tick.
//   - period_stable         : enable held && $rose(tick)
//                                |-> ##PERIOD_CYCLES $rose(tick)       (liveness)
//                             Spacing between consecutive tick rises is
//                             exactly PERIOD_CYCLES cycles while enable
//                             remains continuously asserted.
//   - disabled_implies_no_tick : !enable |-> !tick                     (safety)
//   - reset_restores_phase  : $past(rst) && !rst
//                                |-> counter == INITIAL_PHASE && !tick (safety)
//   - counter_in_range      : counter <= PERIOD_CYCLES - 1             (safety)
//
// Bind target: `sos_tick_gen`.  The bind directive lives in
// `tb/sos_tick_gen/sos_tick_gen_bind.sv`; this file is the assertion
// module that the bind directive instantiates.
// =============================================================================

`default_nettype none

module sos_tick_gen_sva #(
    parameter int PERIOD_CYCLES,
    parameter int INITIAL_PHASE
) (
    input  wire                              clk,
    input  wire                              rst,
    input  wire                              enable,
    input  wire                              tick,
    input  wire [$clog2(PERIOD_CYCLES)-1:0]  counter
);

  // ---------------------------------------------------------------------------
  // Safety: tick is always a 1-cycle pulse.  The DUT computes tick from
  // (counter == PERIOD_CYCLES - 1) & enable; the counter wraps to 0 on the
  // very next edge, so even with enable held high the comparator can match
  // for at most one consecutive cycle.  This property guards against
  // regressions that widen the pulse (e.g. flipping the wrap arithmetic or
  // gating tick on (counter >= PERIOD_CYCLES - 1)).
  // ---------------------------------------------------------------------------
  property p_tick_is_pulse;
    @(posedge clk) disable iff (rst)
      tick |-> ##1 !tick;
  endproperty
  a_tick_is_pulse : assert property (p_tick_is_pulse)
    else $error("sos_tick_gen: tick held for >1 cycle (counter=%0d)", counter);

  // ---------------------------------------------------------------------------
  // Liveness: under continuous enable, consecutive tick rises are exactly
  // PERIOD_CYCLES cycles apart.  The `enable held` precondition is enforced
  // via a sampled-everywhere conjunction; the property fails only if the
  // generator drifts off cadence while still enabled.
  //
  // The check is scoped to runs where `enable` was high on this rise AND
  // remains high through the entire PERIOD_CYCLES window — pauses
  // legitimately shift the next tick out per the §6.8 hold-on-disable
  // semantics, so we exempt those by predication.
  // ---------------------------------------------------------------------------
  property p_period_stable;
    @(posedge clk) disable iff (rst)
      ($rose(tick) && enable) |->
        // No tick for the next (PERIOD_CYCLES - 1) cycles while enable
        // remains high; tick rises on the PERIOD_CYCLES-th cycle.
        (enable throughout (!tick [*PERIOD_CYCLES-1])) ##1 tick;
  endproperty
  a_period_stable : assert property (p_period_stable)
    else $error("sos_tick_gen: period spacing not PERIOD_CYCLES=%0d", PERIOD_CYCLES);

  // ---------------------------------------------------------------------------
  // Safety: when enable is low, tick MUST be low (the enable AND-gate at
  // the output forces this even if the counter is parked at the terminal
  // value).
  // ---------------------------------------------------------------------------
  property p_disabled_implies_no_tick;
    @(posedge clk) disable iff (rst)
      !enable |-> !tick;
  endproperty
  a_disabled_implies_no_tick : assert property (p_disabled_implies_no_tick)
    else $error("sos_tick_gen: tick asserted while enable=0 (counter=%0d)",
                counter);

  // ---------------------------------------------------------------------------
  // Safety: the cycle AFTER reset deasserts, counter MUST equal INITIAL_PHASE
  // and tick MUST be low.  Encoded as: on a falling edge of rst, the
  // current-cycle counter is at INITIAL_PHASE.  The sequential update in
  // the DUT sets counter <- INITIAL_PHASE while rst=1, so the first
  // !rst cycle observes that value before any increment.
  // ---------------------------------------------------------------------------
  property p_reset_restores_phase;
    @(posedge clk)
      ($fell(rst)) |-> (counter == INITIAL_PHASE) && !tick;
  endproperty
  a_reset_restores_phase : assert property (p_reset_restores_phase)
    else $error("sos_tick_gen: reset did not restore counter=INITIAL_PHASE (counter=%0d, expected=%0d)",
                counter, INITIAL_PHASE);

  // ---------------------------------------------------------------------------
  // Safety: counter range invariant.  The combinational tick + wrap means
  // counter takes values in [0, PERIOD_CYCLES - 1] exclusively.
  // ---------------------------------------------------------------------------
  property p_counter_in_range;
    @(posedge clk) disable iff (rst)
      counter <= PERIOD_CYCLES - 1;
  endproperty
  a_counter_in_range : assert property (p_counter_in_range)
    else $error("sos_tick_gen: counter=%0d out of range [0, %0d]",
                counter, PERIOD_CYCLES - 1);

endmodule : sos_tick_gen_sva

`default_nettype wire
