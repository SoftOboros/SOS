// =============================================================================
// sos_tick_gen.sv  --  L0 periodic rate generator (portable SystemVerilog-2017)
//
// @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.8
//   Per 2026-05-23 ratification (§15) + 2026-05-23 impl wave-1 PCDN
//   amendments (§15 third entry): periodic-tick generator emitting a 1-cycle
//   `tick` pulse every `PERIOD_CYCLES` cycles.  Parameters UPPER_CASE
//   (PCDN-A-001).  Synchronous active-high reset (PCDN-A-003,
//   INV-S-HDL-A-1).  Mandatory PERIOD_CYCLES and INITIAL_PHASE parameters
//   carry no defaults (PCDN-A-004, INV-S-HDL-A-5; the sole INV-S-HDL-A-5
//   default-exception is `GRANT_LATENCY_CYCLES` on `sos_arbiter_rr`, not
//   applicable here).  No internal FSM (counter + comparator only) so
//   INV-S-HDL-A-4 one-hot default is trivially satisfied.
//
//   Spec §6.8 baseline names ports {clk, rst, enable, tick,
//   tick_count[31:0]}.  This implementation specialises the observability
//   port to a modulo `counter` (bare port, width = $clog2(PERIOD_CYCLES))
//   per the wave-1 task contract: a modulo-counter is the witness the §6.8
//   SVA properties actually need, and downstream rate-dividers consume the
//   modulo value not a monotonic counter.  The full 32-bit monotonic
//   counter from the §6.8 draft is dropped.
//
//   `tick` is a bare control output (degenerate req with implicit
//   immediate ack per §10 reconciliation); `enable` is a bare control
//   input.  No handshake-paired `tick_ack` port — consumers free-run.
//
// Cited invariants (this primitive does not redefine them):
//   INV-SOS-A  chart-as-source                     (SOS-07 §6)
//   INV-SOS-B  vectors-as-deliverable              (SOS-07 §6)
//   INV-SOS-E  explicit AuthorityRelationship      (SOS-07 §6)
//   INV-SOS-G  verified-codegen position           (SOS-07 §6)
//   INV-SOS-H  vector-to-chart traceability        (SOS-07 §6)
//   INV-S-HDL-1 handshake-compatible ports         (SOS-08 §7; degenerate raw-pulse)
//   INV-S-HDL-2 static-allocation discipline       (SOS-08 §7)
//   INV-S-HDL-3 cross-domain isolation             (SOS-08 §7; N/A, single-domain)
//   INV-S-HDL-4 cooperative-only at v1             (SOS-08 §7)
//   INV-S-HDL-5 vector-to-chart traceability (HDL) (SOS-08 §7)
//   INV-S-HDL-A-1 uniform sync active-high reset   (SOS-08-A §7)
//   INV-S-HDL-A-2 handshake associativity          (SOS-08-A §7; trivial)
//   INV-S-HDL-A-3 vendor-shim byte-identical wrap  (SOS-08-A §7; portable-only)
//   INV-S-HDL-A-4 one-hot internal FSM by default  (SOS-08-A §7; no FSM)
//   INV-S-HDL-A-5 mandatory parameters, no default (SOS-08-A §7)
//
// Behavioural contract:
//   A free-running modulo-PERIOD_CYCLES counter advances each clock while
//   `enable = 1`.  When the counter reaches `PERIOD_CYCLES - 1`, the
//   combinational `tick` output is asserted for that single cycle, and the
//   counter wraps to 0 on the next rising edge.  When `enable = 0`, the
//   counter HOLDS its current value (it does NOT reset mid-period) and
//   `tick` is forced low.  Reasserting `enable` resumes counting from the
//   held value, preserving phase relative to other tick generators that
//   were not paused.
//
//   Synchronous active-high reset clears the counter to INITIAL_PHASE.
//   The caller MUST satisfy 0 <= INITIAL_PHASE < PERIOD_CYCLES or the
//   elaboration-time check below fires.
//
// Resource cost:  $clog2(PERIOD_CYCLES) counter FFs, one comparator, one
//   AND gate for the enable mask.  No FSM, no synchronizer, no memory.
// =============================================================================

`default_nettype none

module sos_tick_gen #(
    // Mandatory parameter: no default per INV-S-HDL-A-5.  Period in `clk`
    // cycles; tick fires every PERIOD_CYCLES-th cycle.  Minimum value is 2.
    parameter int PERIOD_CYCLES,
    // Mandatory parameter: no default per INV-S-HDL-A-5.  Initial counter
    // value at reset; allows multi-instance phase stagger.  MUST satisfy
    // 0 <= INITIAL_PHASE < PERIOD_CYCLES (enforced by the initial-block
    // check below).
    parameter int INITIAL_PHASE
) (
    input  wire                              clk,
    input  wire                              rst,     // sync active-high
    input  wire                              enable,
    output wire                              tick,
    // Observability: current value of the modulo counter, range
    // [0, PERIOD_CYCLES - 1].  Width = $clog2(PERIOD_CYCLES).
    output wire [$clog2(PERIOD_CYCLES)-1:0]  counter
);

  // Elaboration-time validation.
  initial begin
    if (!(PERIOD_CYCLES >= 2)) begin
      $fatal(1, "sos_tick_gen: SOS-08-A §6.8 requires PERIOD_CYCLES >= 2; got %0d",
             PERIOD_CYCLES);
    end
    if (!(INITIAL_PHASE >= 0 && INITIAL_PHASE < PERIOD_CYCLES)) begin
      $fatal(1, "sos_tick_gen: SOS-08-A §6.8 requires 0 <= INITIAL_PHASE < PERIOD_CYCLES; got INITIAL_PHASE=%0d PERIOD_CYCLES=%0d",
             INITIAL_PHASE, PERIOD_CYCLES);
    end
  end

  localparam int CNT_W = $clog2(PERIOD_CYCLES);

  // ---------------------------------------------------------------------------
  // Modulo counter; holds INITIAL_PHASE at reset.
  // ---------------------------------------------------------------------------
  reg [CNT_W-1:0] counter_q;

  // ---------------------------------------------------------------------------
  // Combinational tick: counter == PERIOD_CYCLES - 1 AND enable.
  //
  // The enable AND-gate at the output is load-bearing: even if `enable`
  // drops while counter_q happens to be parked at PERIOD_CYCLES-1, the
  // consumer must never see a tick during the disabled window.
  // ---------------------------------------------------------------------------
  wire at_terminal = (counter_q == CNT_W'(PERIOD_CYCLES - 1));
  assign tick    = at_terminal & enable;
  assign counter = counter_q;

  // ---------------------------------------------------------------------------
  // Sequential update of the modulo counter.
  //   rst=1            -> counter <= INITIAL_PHASE
  //   rst=0, enable=1  -> counter <= (counter + 1) mod PERIOD_CYCLES
  //   rst=0, enable=0  -> counter holds (no increment, no reset)
  // ---------------------------------------------------------------------------
  always_ff @(posedge clk) begin
    if (rst) begin
      counter_q <= CNT_W'(INITIAL_PHASE);
    end else if (enable) begin
      if (counter_q == CNT_W'(PERIOD_CYCLES - 1)) begin
        counter_q <= '0;
      end else begin
        counter_q <= counter_q + 1'b1;
      end
    end
    // enable = 0 : counter holds.
  end

endmodule : sos_tick_gen

`default_nettype wire
