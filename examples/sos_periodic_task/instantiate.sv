// =============================================================================
// examples/sos_periodic_task/instantiate.sv
//
// Minimal SystemVerilog-2017 instantiation example for `sos_periodic_task`
// with DIVISOR = 10 and INITIAL_COUNTER = 0 (canonical "fire every 10
// base_ticks with no phase offset" configuration -- the simplest
// non-passthrough periodic-task instance).
//
// @spec docs/concepts/SOS-08-B-CONCEPTS.md §6.4 (sos_periodic_task contract),
//   §5.4 (service-level SVA binding default), §12 (acceptance checklist;
//   instantiation-example gate).  Per the 2026-05-23 §15 ratification entry.
//   Per PCDN-SOS-08-B-004 resolution: this example does NOT instantiate the
//   global `sos_tick_gen` -- the assumption is that the enclosing system
//   instantiates one global tick generator whose `tick` output feeds the
//   `base_tick` input of every `sos_periodic_task` in the design.  This
//   example exposes `base_tick` at the wrapper boundary for the system
//   integrator to wire up.
//
// @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.8 (`sos_tick_gen` -- referenced
//   only; not instantiated here) + §6.11 (`sos_rate_divider` -- composed
//   inside `sos_periodic_task`, not directly instantiated here).
//
// Cited invariants:
//   INV-SOS-A, INV-SOS-E                              (SOS-07 §6)
//   INV-S-HDL-1, INV-S-HDL-5                          (SOS-08 §7)
//   INV-S-HDL-B-1, INV-S-HDL-B-2, INV-S-HDL-B-3       (SOS-08-B §7)
//
// The instantiation is illustrative only; it shows the parameter override
// (DIVISOR = 10 + INITIAL_COUNTER = 0, both mandatory at the L1 boundary
// per INV-S-HDL-A-5 pass-through), the canonical port set, the tick-style
// 1-cycle pulse i/o, and the synchronous active-high reset wiring.
// =============================================================================

`default_nettype none

module sos_periodic_task_inst10 (
    input  wire        clk,
    input  wire        rst,

    // Upstream tick from the system-level sos_tick_gen.
    input  wire        base_tick,

    // Task activation (1-cycle pulse).
    output wire        task_enable,

    // Worker status (level).
    input  wire        task_busy,

    // Sticky overrun fault (level).
    output wire        overrun_fault,

    // Observability: inner rate-divider counter, $clog2(10) = 4 bits.
    output wire [3:0]  divider_counter
);

  sos_periodic_task #(
      .DIVISOR         (10),
      .INITIAL_COUNTER (0)
  ) u_periodic_task_10 (
      .clk             (clk),
      .rst             (rst),
      .base_tick       (base_tick),
      .task_enable     (task_enable),
      .task_busy       (task_busy),
      .overrun_fault   (overrun_fault),
      .divider_counter (divider_counter)
  );

endmodule : sos_periodic_task_inst10

`default_nettype wire
