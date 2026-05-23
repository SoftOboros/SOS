// =============================================================================
// sos_event_group.sv  --  L1 service: FreeRTOS-style event-bit group
//                         (portable SystemVerilog-2017)
//
// @spec        docs/concepts/SOS-08-B-CONCEPTS.md §6.2 (sos_event_group)
//                + §5 frozen decisions, §7 cross-service invariants,
//                + §15 ratification entry (PCDN-SOS-08-B-002 -> N_BITS=32).
// @parent      docs/concepts/SOS-08-CONCEPTS.md §6 (L1 set), §7 (INV-S-HDL-1..5)
// @grandparent docs/concepts/SOS-07-CONCEPTS.md §6 (INV-SOS-A..H)
// @l0          docs/concepts/SOS-08-A-CONCEPTS.md §6.10 (sos_strobe_latch)
//                + §15 wave-2 amendments (PCDN-A-strobe-pending-shadow ->
//                  3-state FSM IDLE/LATCHED/LATCHED_PENDING + pending_q port).
//
// Composition recipe (per §6.2):
//   N_BITS x sos_strobe_latch instantiated in a generate-for loop, one per
//   event-bit.  Each strobe_latch's `strobe` input is driven by
//   (set_req && set_mask[i]); its `ack` input is driven by
//   (clear_req && clear_mask[i]).  The `latched` output of strobe_latch[i]
//   becomes bits[i].  Wait-side combinational logic ANDs `bits` against
//   `wait_mask` and reduces via OR (any-of) or via equality-to-mask (all-of)
//   to produce wait_match.
//
// Cited invariants (this service does not re-derive them):
//   INV-SOS-A    chart-as-source                  (SOS-07 §6)
//   INV-SOS-B    vectors-as-deliverable           (SOS-07 §6)
//   INV-SOS-C    MCP as sole modification surface (SOS-07 §6)
//   INV-SOS-D    iState authoring, SCXML canonical(SOS-07 §6)
//   INV-SOS-E    explicit AuthorityRelationship   (SOS-07 §6)
//   INV-SOS-F    bound composition                (SOS-07 §6)
//   INV-SOS-G    verified-codegen position        (SOS-07 §6)
//   INV-SOS-H    vector-to-chart traceability     (SOS-07 §6)
//
//   INV-S-HDL-1  handshake-compatible ports       (SOS-08 §7)
//   INV-S-HDL-2  static-allocation discipline     (SOS-08 §7) -- N_BITS fixed
//                at elaboration; no dynamic allocation.
//   INV-S-HDL-3  cross-domain isolation           (SOS-08 §7) -- N/A: single
//                clock domain; cross-domain composes sos_synchronizer upstream.
//   INV-S-HDL-4  cooperative-only at v1           (SOS-08 §7)
//   INV-S-HDL-5  vector-to-chart traceability     (SOS-08 §7)
//
//   INV-S-HDL-B-1 Vocabulary mirror discipline    (SOS-08-B §7) --
//                 set / wait / peek / clear -> FreeRTOS xEventGroup* + POSIX
//                 signals per §6.2 behavioural contract.
//   INV-S-HDL-B-2 L0 non-modification             (SOS-08-B §7) -- this
//                 service ONLY instantiates sos_strobe_latch via the
//                 ratified port set; it does NOT reach inside the primitive.
//   INV-S-HDL-B-3 Service-level SVA on every inst (SOS-08-B §7) -- bind file
//                 at tb/sos_event_group/sos_event_group_bind.sv attaches the
//                 service-level SVA module to every elaborated instance.
//   INV-S-HDL-B-4 Vendor-IP pass-through          (SOS-08-B §7) -- vacuously
//                 satisfied; sos_strobe_latch is portable-RTL-only per §6.2.
//   INV-S-HDL-B-5 Chart-vocabulary failure render (SOS-08-B §7)
//
//   (L0 invariants inherited through the strobe_latch instances:)
//   INV-S-HDL-A-1 uniform sync active-high reset  (SOS-08-A §7) -- this
//                 service uses sync active-high `rst` and routes it to every
//                 sub-instance's `rst` port unchanged.
//   INV-S-HDL-A-2 handshake associativity         (SOS-08-A §7)
//   INV-S-HDL-A-3 vendor-shim byte-identical      (SOS-08-A §7; portable-only)
//   INV-S-HDL-A-4 one-hot internal FSM by default (SOS-08-A §7) -- the L1
//                 service has no FSM state of its own; per-bit FSM lives in
//                 each strobe_latch (3-state one-hot per §15 wave-2).
//   INV-S-HDL-A-5 mandatory parameters, no default(SOS-08-A §7) -- N_BITS
//                 is a service-level parameter; per PCDN-SOS-08-B-002
//                 resolution (§15 2026-05-23), it carries a default of 32
//                 (the chart's i32 datamodel word width).  This default is
//                 SERVICE-LEVEL (SOS-08-B layer), not an L0 exception to
//                 INV-S-HDL-A-5 which governs L0 primitives.
//
// Design choices flagged in the agent report (no spec text re-derived here):
//   * Simultaneous set + clear on the same bit (same cycle):
//       CLEAR WINS.  Rationale: the per-bit sos_strobe_latch behaviour on
//       LATCHED + ack + strobe is the wave-1 ack-wins / wave-2 shadow-promote
//       resolution (see §15 wave-2 PCDN-A-strobe-pending-shadow).  When the
//       bit was already set (LATCHED), a same-cycle (set_req && set_mask[i])
//       captures into the shadow while (clear_req && clear_mask[i]) consumes
//       the live event; the shadow then promotes -> the bit STAYS SET next
//       cycle.  When the bit was clear (IDLE), set captures and the bit
//       transitions to set next cycle, because the L0 primitive's
//       IDLE-side semantic is "strobe wins; ack is a no-op".
//       The visible service-level rule is thus:
//         - bit was clear, same-cycle set+clear -> bit becomes set next cycle
//           (matches L0 IDLE+strobe+ack semantic).
//         - bit was set, same-cycle set+clear   -> bit stays set next cycle
//           (matches L0 LATCHED+strobe+ack with shadow-promote).
//       Both cases preserve the underlying strobe (no event loss); the
//       "clear wins" framing applies to the *clearing edge* of the live
//       LATCHED event, not to the simultaneously-arriving new set.  The
//       chart-side software analog (FreeRTOS xEventGroupClearBits called
//       in the same critical section as xEventGroupSetBits) does NOT
//       define a deterministic outcome; SOS pins it to the L0 primitive's
//       shadow-promote semantic, which preserves both events without
//       requiring two cycles.  Flagged for §15 ratification at the
//       SOS-08-B walkthrough.
//
//   * pending_q exposure at the service level:
//       NOT EXPOSED.  Rationale: the chart-side `event.peek` verb (§6.2
//       behavioural contract) requests the current LIVE bit-vector; the
//       per-bit pending_strobe shadow is an implementation detail of how
//       a same-cycle race is resolved internally.  Exposing pending_bits
//       at the service interface would force every chart consumer to
//       reason about the L0 primitive's wave-2 3-state FSM, which
//       violates the spirit of L1 hiding L0 implementation choices
//       (per §5.2 "L1 composes L0 without modifying L0 behaviour" and the
//       INV-S-HDL-B-2 boundary discipline).  Internal observability is
//       preserved via the per-instance SVA bind on the inner
//       strobe_latches; external observability is bits[N_BITS-1:0] only.
//       Flagged for §15 ratification at the SOS-08-B walkthrough.
// =============================================================================

`default_nettype none

module sos_event_group #(
    // Per PCDN-SOS-08-B-002 resolution (§15 2026-05-23): N_BITS parameterised
    // with default 32 (chart datamodel i32 width).  Service-level parameter;
    // per-region override via chart annotation.
    parameter int N_BITS = 32
) (
    input  wire                  clk,
    input  wire                  rst,            // sync active-high (INV-S-HDL-A-1)
    // set side: 1-cycle pulse + per-bit mask
    input  wire                  set_req,
    input  wire [N_BITS-1:0]     set_mask,
    // clear side: 1-cycle pulse + per-bit mask
    input  wire                  clear_req,
    input  wire [N_BITS-1:0]     clear_mask,
    // wait side: level-output predicate on current bits
    input  wire [N_BITS-1:0]     wait_mask,
    input  wire                  wait_mode,      // 0 = any-of, 1 = all-of
    output wire                  wait_match,
    // observability: current bit-vector
    output wire [N_BITS-1:0]     bits
);

  // ---------------------------------------------------------------------------
  // Elaboration-time validation
  // ---------------------------------------------------------------------------
  initial begin
    if (N_BITS < 1) begin
      $fatal(1, "sos_event_group: SOS-08-B §6.2 requires N_BITS >= 1; got %0d",
             N_BITS);
    end
  end

  // ---------------------------------------------------------------------------
  // Generate one sos_strobe_latch per event bit (per §6.2 L0 composition).
  // Each bit's strobe is driven by (set_req && set_mask[i]); each bit's ack
  // is driven by (clear_req && clear_mask[i]).  The L1 service ONLY wires
  // ratified L0 ports (clk, rst, strobe, ack, latched, pending_q,
  // latched_state_q) per INV-S-HDL-B-2.
  // ---------------------------------------------------------------------------
  wire [N_BITS-1:0] bit_strobe;
  wire [N_BITS-1:0] bit_ack;
  wire [N_BITS-1:0] bit_latched;
  wire [N_BITS-1:0] bit_pending;       // L0 observability; not exposed at L1.
  wire [N_BITS-1:0] bit_state_q;       // L0 observability; not exposed at L1.

  genvar gi;
  generate
    for (gi = 0; gi < N_BITS; gi = gi + 1) begin : g_bits
      assign bit_strobe[gi] = set_req   & set_mask[gi];
      assign bit_ack[gi]    = clear_req & clear_mask[gi];

      sos_strobe_latch u_bit (
        .clk             (clk),
        .rst             (rst),
        .strobe          (bit_strobe[gi]),
        .ack             (bit_ack[gi]),
        .latched         (bit_latched[gi]),
        .pending_q       (bit_pending[gi]),
        .latched_state_q (bit_state_q[gi])
      );
    end
  endgenerate

  // ---------------------------------------------------------------------------
  // bits[] is the live latched vector (per §6.2 "current_bits == latched").
  // pending and state_q remain internal to honour the L1-hides-L0 discipline
  // (see header rationale).  They are still observable via the per-bit
  // sos_strobe_latch SVA bind (module-type bind attaches at every instance).
  // ---------------------------------------------------------------------------
  assign bits = bit_latched;

  // ---------------------------------------------------------------------------
  // Wait-side combinational predicate (§6.2 SVA-EVG-2 / SVA-EVG-3).
  //   * any-of (wait_mode = 0): match iff (bits & wait_mask) != 0
  //   * all-of (wait_mode = 1): match iff (bits & wait_mask) == wait_mask
  // wait_match tracks the current state of `bits` (level output, no latching).
  // Per §6.2, the wait-side is single-consumer at v1; multi-consumer wait
  // would land via a service-level §15 amendment instantiating sos_arbiter_rr.
  // ---------------------------------------------------------------------------
  wire [N_BITS-1:0] masked_bits;
  assign masked_bits = bits & wait_mask;

  wire match_any = |masked_bits;
  wire match_all = (masked_bits == wait_mask);

  assign wait_match = wait_mode ? match_all : match_any;

  // (unused internal signals -- silence lint warnings; pending/state_q are
  //  intentionally not exposed at the service boundary; see header rationale.)
  // verilator lint_off UNUSED
  wire _unused_pending = |bit_pending;
  wire _unused_state_q = |bit_state_q;
  // verilator lint_on UNUSED

endmodule

`default_nettype wire
