// =============================================================================
// sos_periodic_task.sv  --  L1 service: per-task periodic activation with
//                           overrun detection (portable SV-2017).
//
// @spec docs/concepts/SOS-08-B-CONCEPTS.md §6.4 (sos_periodic_task contract)
//   + §5.1 (FreeRTOS / POSIX vocabulary mirror), §5.2 (L1-composes-L0-without-
//   modification), §5.3 (vendor-IP override pass-through; N/A here -- the
//   inner sos_rate_divider is portable-only), §5.4 (service-level SVA binding
//   default).  Per the 2026-05-23 §15 ratification entry (PCDN walkthrough).
//
//   Per PCDN-SOS-08-B-004 resolution (RESOLVED, recommendation accepted):
//   ONE global `sos_tick_gen` per system; per-task `sos_rate_divider` for
//   sub-rates.  This service represents ONE periodic task.  The global
//   `sos_tick_gen` is shared at the system level and is NOT instantiated
//   here; this service consumes the global `base_tick` and divides it
//   per-task via a single internal `sos_rate_divider`.
//
// @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.8 (`sos_tick_gen` -- by-reference
//   only; not instantiated here) + §6.11 (`sos_rate_divider` -- instantiated
//   internally).  Per the 2026-05-23 wave-2 §15 amendments:
//     * §6.8 PCDN-A-tick-prose-collapse: the global tick generator's
//       observability is a modulo counter, not a monotonic 32-bit tick count
//       (the prompt's draft `tick_count[31:0]` port is WITHDRAWN at the L1
//       boundary; this service mirrors the L0 collapse by exposing
//       `divider_counter` -- the inner `sos_rate_divider.counter` -- as the
//       only observability port, width $clog2(DIVISOR) minimum 1).
//     * §6.11 PCDN-A-rate-prose-collapse: compile-time `DIVISOR` +
//       `INITIAL_COUNTER` generics; no runtime ratio.  These generics are
//       passed through to the inner `sos_rate_divider`.
//
// Cited invariants (this service does not redefine them):
//   INV-SOS-A   chart-as-source                       (SOS-07 §6)
//   INV-SOS-B   vectors-as-deliverable                (SOS-07 §6)
//   INV-SOS-E   explicit AuthorityRelationship        (SOS-07 §6)
//   INV-SOS-G   verified-codegen position             (SOS-07 §6)
//   INV-SOS-H   vector-to-chart traceability         (SOS-07 §6)
//   INV-S-HDL-1 handshake-compatible ports            (SOS-08 §7; pulse form)
//   INV-S-HDL-2 static-allocation discipline          (SOS-08 §7)
//   INV-S-HDL-3 cross-domain isolation                (SOS-08 §7; N/A single-clk)
//   INV-S-HDL-4 cooperative-only at v1                (SOS-08 §7)
//   INV-S-HDL-5 vector-to-chart traceability (HDL)    (SOS-08 §7)
//   INV-S-HDL-B-1 vocabulary mirror discipline        (SOS-08-B §7)
//   INV-S-HDL-B-2 L0 non-modification                 (SOS-08-B §7)
//   INV-S-HDL-B-3 service-level SVA on every L1       (SOS-08-B §7)
//   INV-S-HDL-B-4 vendor-IP pass-through              (SOS-08-B §7; N/A)
//   INV-S-HDL-B-5 chart-vocabulary failure rendering  (SOS-08-B §7)
//
// Behavioural contract (§6.4):
//   See the matching VHDL file header for the full prose contract.  Summary:
//     * `base_tick` is a 1-cycle pulse from the system-wide `sos_tick_gen`
//       (NOT instantiated here -- shared global per PCDN-SOS-08-B-004).
//     * Inner `sos_rate_divider` divides `base_tick` by `DIVISOR`, phase
//       offset `INITIAL_COUNTER`, producing internal `task_tick`.
//     * On each `task_tick`, the FSM emits `task_enable` one cycle later
//       (SVA-PT-2).
//     * If `task_busy` is high at the cycle of a subsequent `task_tick`,
//       `overrun_fault` latches high one cycle later and stays high until
//       reset (sticky, SVA-PT-3).  Default SVA-PT-4 disposition: under
//       `overrun_fault == 1`, `task_enable` continues to pulse on each
//       task_tick; the chart-side FSM observes both signals.
//
// FSM encoding: one-hot (3 FFs) per INV-S-HDL-A-4 / SOS-08-A §5.2 extended
// to L1.  States: ST_IDLE / ST_RUNNING / ST_OVERRUN.  See VHDL header for
// the full state-transition narrative.
//
// Resource cost:
//   $clog2(DIVISOR) FFs (inner rate divider counter)
//   + 3 FFs (one-hot FSM state)
//   + 1 FF (registered task_enable pulse)
//   + 1 FF (sticky overrun_fault).
// =============================================================================

`default_nettype none

module sos_periodic_task #(
    // Mandatory: no default per INV-S-HDL-B-2 via INV-S-HDL-A-5 pass-through.
    // DIVISOR >= 1; DIVISOR = 0 forbidden by the inner sos_rate_divider.
    parameter int DIVISOR,
    // Mandatory: no default.  0 <= INITIAL_COUNTER < DIVISOR.
    parameter int INITIAL_COUNTER
) (
    input  wire                                                       clk,
    input  wire                                                       rst,           // sync active-high

    // Upstream 1-cycle tick from the system-level sos_tick_gen.
    input  wire                                                       base_tick,

    // Task activation (1-cycle pulse, registered: one cycle after task_tick).
    output wire                                                       task_enable,

    // Worker status (level).
    input  wire                                                       task_busy,

    // Sticky overrun fault (level; cleared only by reset).
    output wire                                                       overrun_fault,

    // Observability: inner rate-divider counter (modulo, width
    // $clog2(DIVISOR), minimum 1 bit).  Per §6.8 prose-collapse.
    output wire [((DIVISOR > 1) ? $clog2(DIVISOR) : 1) - 1 : 0]        divider_counter
);

  // FSM state encoding (one-hot).
  localparam logic [2:0] ST_IDLE    = 3'b001;
  localparam logic [2:0] ST_RUNNING = 3'b010;
  localparam logic [2:0] ST_OVERRUN = 3'b100;

  // ---------------------------------------------------------------------------
  // Inner sos_rate_divider: divides base_tick by DIVISOR, producing task_tick.
  // DIVISOR + INITIAL_COUNTER passed through verbatim.
  // ---------------------------------------------------------------------------
  wire task_tick;

  sos_rate_divider #(
      .DIVISOR         (DIVISOR),
      .INITIAL_COUNTER (INITIAL_COUNTER)
  ) u_div (
      .clk      (clk),
      .rst      (rst),
      .tick_in  (base_tick),
      .tick_out (task_tick),
      .counter  (divider_counter)
  );

  // ---------------------------------------------------------------------------
  // FSM state + registered task_enable + sticky overrun.
  // ---------------------------------------------------------------------------
  reg [2:0] state_q;
  reg       task_enable_q;
  reg       overrun_q;

  always_ff @(posedge clk) begin
    if (rst) begin
      state_q       <= ST_IDLE;
      task_enable_q <= 1'b0;
      overrun_q     <= 1'b0;
    end else begin
      // Default: task_enable returns low next cycle (pulse).
      task_enable_q <= 1'b0;

      unique case (state_q)
        ST_IDLE: begin
          if (task_tick) begin
            state_q       <= ST_RUNNING;
            task_enable_q <= 1'b1;
          end
        end

        ST_RUNNING: begin
          if (task_tick) begin
            task_enable_q <= 1'b1;  // SVA-PT-4 default: pulses continue.
            if (task_busy) begin
              state_q   <= ST_OVERRUN;
              overrun_q <= 1'b1;
            end
          end
        end

        ST_OVERRUN: begin
          // Sticky fault.  Pulses continue; overrun_q held.
          if (task_tick) begin
            task_enable_q <= 1'b1;
          end
        end

        default: begin
          // Defensive: any non-one-hot state reverts to ST_IDLE.  overrun_q
          // is a separate register and is NOT cleared by this branch -- only
          // synchronous reset clears overrun_q (SVA-PT-3 stickiness).
          state_q <= ST_IDLE;
        end
      endcase
    end
  end

  // Output drivers (registered).
  assign task_enable   = task_enable_q;
  assign overrun_fault = overrun_q;

endmodule : sos_periodic_task

`default_nettype wire
