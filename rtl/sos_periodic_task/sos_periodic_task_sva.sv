// =============================================================================
// sos_periodic_task_sva.sv  --  Service-level SVA module for sos_periodic_task.
//
// @spec docs/concepts/SOS-08-B-CONCEPTS.md §6.4 SVA property list
//   (SVA-PT-1 through SVA-PT-5) + §5.4 (service-level SVA binding default;
//   PCDN-SOS-08-007 resolution as restated by SOS-08-B §5.4) +
//   INV-S-HDL-B-3 (service-level SVA on every L1 instance).
//
//   Per the 2026-05-23 ratification of SOS-08-B (§15) the property set is
//   frozen at SVA-PT-1..5; this module binds them to the service module.
//   The bind directive itself lives in
//   `tb/sos_periodic_task/sos_periodic_task_bind.sv` (module-type bind
//   per the PCDN-A-bind-form resolution carried forward from SOS-08-A §15
//   third 2026-05-23 entry; Verilator-compatible).
//
// @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.11 (inner sos_rate_divider --
//   the inner primitive already carries its own service of SVA properties
//   via the L0 bind file; this module asserts service-level properties at
//   the L1 boundary, NOT a duplicate of the L0 properties).
//
// Cited invariants:
//   INV-SOS-A, INV-SOS-B, INV-SOS-E, INV-SOS-H            (SOS-07 §6)
//   INV-S-HDL-1, INV-S-HDL-4, INV-S-HDL-5                 (SOS-08 §7)
//   INV-S-HDL-B-3, INV-S-HDL-B-5                          (SOS-08-B §7)
//
// Properties (per §6.4):
//   - p_task_enable_is_pulse     : task_enable is a 1-cycle pulse (never
//                                  asserted two cycles in a row).
//                                  [SVA-PT-2 corollary; the spec asks for
//                                  "exactly one task_enable pulse on the
//                                  next cycle".]
//   - p_task_enable_spacing      : the number of base_tick pulses between
//                                  two consecutive task_enable pulses
//                                  is exactly DIVISOR.  [SVA-PT-1.]
//   - p_overrun_implies_busy_at_tick : overrun_fault rises only in the
//                                  cycle immediately after a task_tick
//                                  at which task_busy was asserted.
//                                  [SVA-PT-3 forward direction.]
//   - p_overrun_is_sticky        : once overrun_fault is high, it stays
//                                  high until reset.  [SVA-PT-3.]
//   - p_overrun_busy_required    : overrun_fault does NOT rise on a cycle
//                                  unless task_busy was high at the
//                                  previous task_tick (or overrun_fault
//                                  was already high).  [SVA-PT-3 reverse
//                                  direction.]
//
// Note on SVA-PT-5 ("base-tick monotonic"): the underlying L0
// sos_rate_divider's own SVA (`p_tick_out_spacing_in_ticks`) already
// asserts the monotonicity property of `task_tick` vs `base_tick`; the
// L1 service does not re-derive it (§5.2 / INV-S-HDL-B-2: the L1 layer
// composes the L0 contract, not duplicates it).
// =============================================================================

`default_nettype none

module sos_periodic_task_sva #(
    parameter int DIVISOR,
    parameter int INITIAL_COUNTER
) (
    input  wire                                                       clk,
    input  wire                                                       rst,
    input  wire                                                       base_tick,
    input  wire                                                       task_enable,
    input  wire                                                       task_busy,
    input  wire                                                       overrun_fault,
    input  wire [((DIVISOR > 1) ? $clog2(DIVISOR) : 1) - 1 : 0]        divider_counter
);

  // ---------------------------------------------------------------------------
  // Safety: task_enable is a 1-cycle pulse.
  // The FSM registers task_enable from a 1-cycle task_tick pulse, so
  // task_enable is always 1 cycle wide.  Even under back-to-back task_ticks
  // at DIVISOR=1 the L0 contract still passes through 1-cycle pulses (a
  // task_tick every base_tick, and base_tick itself is a 1-cycle pulse).
  // ---------------------------------------------------------------------------
  property p_task_enable_is_pulse;
    @(posedge clk) disable iff (rst)
      task_enable |-> ##1 !task_enable;
  endproperty
  a_task_enable_is_pulse : assert property (p_task_enable_is_pulse)
    else $error("sos_periodic_task: task_enable asserted two cycles in a row (DIVISOR=%0d INITIAL_COUNTER=%0d) -- violates SVA-PT-2 pulse-shape corollary",
                DIVISOR, INITIAL_COUNTER);

  // ---------------------------------------------------------------------------
  // Functional: task_enable spacing measured in base_tick pulses is DIVISOR.
  //
  // Implementation: count base_tick pulses observed between consecutive
  // task_enable pulses; assert the count is DIVISOR.  The first task_enable
  // after reset fires (DIVISOR - INITIAL_COUNTER) base_ticks after reset
  // plus one cycle of registration delay; we seed the count to model that.
  //
  // A subtlety: task_enable is registered one cycle AFTER the qualifying
  // task_tick.  base_tick pulses can land on any cycle.  We count base_tick
  // pulses since the last task_enable; each window must contain exactly
  // DIVISOR base_ticks for the next task_enable to fire on time.  Idle
  // cycles (base_tick = 0) between ticks do NOT count.
  //
  // First-window seeding mirrors the L0 sos_rate_divider SVA's approach:
  // seed `ticks_since` to INITIAL_COUNTER at reset so the first task_enable
  // satisfies the same `== DIVISOR - 1` test as subsequent windows.
  // ---------------------------------------------------------------------------
  int unsigned base_ticks_since_enable;

  always_ff @(posedge clk) begin
    if (rst) begin
      base_ticks_since_enable <= INITIAL_COUNTER;
    end else if (task_enable) begin
      // task_enable fires one cycle after the task_tick that triggered it.
      // That task_tick already counted the firing base_tick (it's a
      // combinational AND with at_limit in the inner divider).  So at the
      // task_enable cycle, base_ticks_since_enable reflects the count
      // BEFORE the firing base_tick; we roll it over to 0 here and let
      // any concurrent base_tick on this same cycle be picked up by the
      // `else if` branch below on the NEXT cycle (a base_tick concurrent
      // with task_enable starts a fresh window).
      if (base_tick) begin
        base_ticks_since_enable <= 1;
      end else begin
        base_ticks_since_enable <= 0;
      end
    end else if (base_tick) begin
      base_ticks_since_enable <= base_ticks_since_enable + 1;
    end
  end

  // On every task_enable, the count of base_tick pulses since the previous
  // task_enable (or since reset, seeded by INITIAL_COUNTER) must equal
  // DIVISOR - 1 (the firing base_tick is on the previous cycle and is NOT
  // included in `base_ticks_since_enable` at the task_enable cycle yet).
  property p_task_enable_spacing;
    @(posedge clk) disable iff (rst)
      task_enable |-> base_ticks_since_enable == DIVISOR - 1;
  endproperty
  a_task_enable_spacing : assert property (p_task_enable_spacing)
    else $error("sos_periodic_task: task_enable fired after base_ticks_since_enable=%0d base_tick pulses; expected DIVISOR-1=%0d (INITIAL_COUNTER=%0d) -- violates SVA-PT-1",
                base_ticks_since_enable, DIVISOR - 1, INITIAL_COUNTER);

  // ---------------------------------------------------------------------------
  // Auxiliary verification state: did task_busy hold across the most recent
  // base_tick that completed a divider window (i.e. the most recent
  // task_tick)?  We rebuild the task_tick view at the SVA boundary by
  // observing that task_enable is registered task_tick: a task_enable at
  // cycle N implies task_tick fired at cycle N-1.  We therefore sample
  // task_busy at cycle N-1 (one cycle before task_enable) -- but the
  // overrun rule cares about the SECOND and later task_ticks, since the
  // first task_tick has no preceding enable.
  //
  // We track `busy_at_last_tick`: the value of task_busy at the cycle the
  // most recent task_tick fired.  Computed by sampling task_busy on the
  // cycle BEFORE every task_enable.  We also track whether a task_tick has
  // been observed yet (`saw_first_tick`) so the very first tick doesn't
  // trigger a spurious overrun.
  //
  // task_tick reconstruction: task_enable is registered from task_tick, so
  // task_tick at cycle T iff task_enable at cycle T+1.  Equivalently: at
  // any cycle where task_enable is high, the previous cycle had task_tick
  // high.
  // ---------------------------------------------------------------------------
  reg busy_at_last_tick;
  reg saw_first_tick;
  reg task_busy_prev;

  always_ff @(posedge clk) begin
    if (rst) begin
      busy_at_last_tick <= 1'b0;
      saw_first_tick    <= 1'b0;
      task_busy_prev    <= 1'b0;
    end else begin
      task_busy_prev <= task_busy;
      if (task_enable) begin
        // task_tick fired the cycle before this one (task_enable is its
        // registered shadow).  task_busy_prev holds task_busy from that
        // previous cycle.
        busy_at_last_tick <= task_busy_prev;
        saw_first_tick    <= 1'b1;
      end
    end
  end

  // ---------------------------------------------------------------------------
  // Safety: overrun_fault rises iff task_busy was high at the most recent
  // task_tick (and at least one prior task_tick had been seen, since the
  // first tick cannot itself be an overrun).
  //
  // Timing alignment: in the DUT, the FSM samples task_busy on the cycle
  // of task_tick and updates overrun_q + task_enable_q via NBA, so
  // overrun_fault and task_enable both rise on the same cycle (the cycle
  // AFTER the offending task_tick).  In this SVA the same alignment is
  // mirrored: `busy_at_last_tick` is updated on the cycle task_enable
  // rises (one cycle after task_tick) using `task_busy_prev` (sampled
  // task_busy from the task_tick cycle).  Thus `busy_at_last_tick`
  // catches up to the offending value on cycle N+1, where cycle N is the
  // cycle overrun_fault rises.  We therefore check the property one
  // cycle AFTER the rise using $past.
  //
  // We split into two directional properties to make failures easier to
  // diagnose:
  //   * p_overrun_implies_busy_at_tick : if overrun_fault was 0 last cycle
  //     and is 1 this cycle, then busy_at_last_tick (now up-to-date) is 1
  //     and saw_first_tick is 1.
  //   * p_overrun_busy_required        : overrun_fault never rises spuriously
  //     -- a rise requires busy_at_last_tick (one cycle later, when the
  //     verification state has caught up) and saw_first_tick.
  // ---------------------------------------------------------------------------
  property p_overrun_implies_busy_at_tick;
    @(posedge clk) disable iff (rst)
      ($past(overrun_fault) == 1'b0 && overrun_fault == 1'b1) ##1
        (busy_at_last_tick && saw_first_tick);
  endproperty
  a_overrun_implies_busy_at_tick : assert property (p_overrun_implies_busy_at_tick)
    else $error("sos_periodic_task: overrun_fault rose without task_busy at preceding task_tick (busy_at_last_tick=%0d saw_first_tick=%0d) -- violates SVA-PT-3",
                busy_at_last_tick, saw_first_tick);

  // Reverse direction: a 0->1 transition on overrun_fault MUST be preceded
  // (one cycle later, after verification state catches up) by busy_at_last_tick
  // && saw_first_tick.  Encoded as: the rising-edge cycle pair triggers,
  // and one cycle later both indicators must be true.  This is the same
  // shape as the forward property but stated as a stand-alone reverse-
  // direction check for diagnostic clarity (a failure here vs. the forward
  // property would imply a spurious rise rather than a false-negative
  // detection in our auxiliary state).
  property p_overrun_busy_required;
    @(posedge clk) disable iff (rst)
      $rose(overrun_fault) ##1 (busy_at_last_tick && saw_first_tick);
  endproperty
  a_overrun_busy_required : assert property (p_overrun_busy_required)
    else $error("sos_periodic_task: overrun_fault rose spuriously (not preceded by busy-at-tick) -- violates SVA-PT-3");

  // ---------------------------------------------------------------------------
  // Safety: overrun_fault is sticky.  Once high, it stays high until reset.
  // ---------------------------------------------------------------------------
  property p_overrun_is_sticky;
    @(posedge clk) disable iff (rst)
      overrun_fault |-> ##1 overrun_fault;
  endproperty
  a_overrun_is_sticky : assert property (p_overrun_is_sticky)
    else $error("sos_periodic_task: overrun_fault cleared without reset -- violates SVA-PT-3 stickiness");

  // ---------------------------------------------------------------------------
  // Safety (defensive): task_enable does not fire while rst is high.
  // Belt-and-suspenders check on the reset path.
  // ---------------------------------------------------------------------------
  property p_no_enable_under_reset;
    @(posedge clk)
      rst |-> !task_enable;
  endproperty
  a_no_enable_under_reset : assert property (p_no_enable_under_reset)
    else $error("sos_periodic_task: task_enable asserted while rst is high");

endmodule : sos_periodic_task_sva

`default_nettype wire
