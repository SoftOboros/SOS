//------------------------------------------------------------------------------
// sos_strobe_latch.sv - L0 primitive: pulse-to-level + ack
//
// @spec        docs/concepts/SOS-08-A-CONCEPTS.md §6.10
// @parent      docs/concepts/SOS-08-CONCEPTS.md §6 (L0 set), §7 (INV-S-HDL-1..5)
// @grandparent docs/concepts/SOS-07-CONCEPTS.md §6 (INV-SOS-A..H)
//
// Invariants cited (not re-derived):
//   INV-SOS-A  chart-as-source                  (SOS-07 §6)
//   INV-SOS-B  vectors-as-deliverable           (SOS-07 §6)
//   INV-SOS-C  MCP as sole modification surface (SOS-07 §6)
//   INV-SOS-D  iState authoring, SCXML canon.   (SOS-07 §6)
//   INV-SOS-E  explicit AuthorityRelationship   (SOS-07 §6)
//   INV-SOS-F  bound composition                (SOS-07 §6)
//   INV-SOS-G  verified-codegen position        (SOS-07 §6)
//   INV-SOS-H  vector-to-chart traceability     (SOS-07 §6)
//
//   INV-S-HDL-1  handshake-compatible ports    (SOS-08 §7)
//   INV-S-HDL-2  static-allocation discipline  (SOS-08 §7)
//   INV-S-HDL-3  cross-domain isolation        (SOS-08 §7) — N/A: single domain.
//                Cross-domain strobe latching composes a sos_synchronizer on
//                the `strobe` input UPSTREAM of this primitive's boundary
//                (per §6.10 MTBF treatment).
//   INV-S-HDL-4  cooperative-only at v1         (SOS-08 §7)
//   INV-S-HDL-5  vector-to-chart traceability   (SOS-08 §7)
//
//   INV-S-HDL-A-1 uniform reset semantics       (SOS-08-A §7) — sync active-high
//   INV-S-HDL-A-2 handshake associativity       (SOS-08-A §7)
//   INV-S-HDL-A-3 vendor-shim byte-identical    (SOS-08-A §7) — portable-only
//   INV-S-HDL-A-4 one-hot internal FSM default  (SOS-08-A §7) — IDLE/LATCHED one-hot
//   INV-S-HDL-A-5 mandatory params no defaults  (SOS-08-A §7) — VACUOUSLY SATISFIED
//                 (no user-facing parameters on this primitive; see note below)
//
// Per PCDN-A-002 resolution (§15 2026-05-23): control-only primitives use bare
// `strobe` / `ack` / `latched` (not AXI-Stream prefixed). This primitive sits
// in the pulse-bearing class (§10 reconciliation), but its OUTPUT `latched` is
// LEVEL-HELD rather than a single-cycle pulse — see "hybrid handshake" note.
//
// HYBRID HANDSHAKE PATTERN (per PCDN-A-mutex-ack precedent, §15 2026-05-23 entry
// "Impl wave-1 PCDN amendments"):
//   sos_strobe_latch combines the two §5.1 control-handshake variants:
//     * `strobe` (in)   -- PULSE-BASED (1-cycle pulse) per §5.1(a). Producer
//                          emits a one-shot event; consumer is the latch.
//     * `latched` (out) -- LEVEL-HELD per §5.1(b). The latched-state output
//                          is asserted for every cycle between strobe-capture
//                          and ack, mirroring sos_mutex `ack[i]`'s
//                          ownership-tracking shape.
//     * `ack` (in)      -- PULSE-BASED (1-cycle pulse) per §5.1(a). Consumer
//                          acknowledges the latched event and clears the state.
//   The §6.10 contract literal "pulse-to-level + ack" describes exactly this
//   shape: strobe (pulse) -> latched (level) -> ack (pulse).
//
// INV-S-HDL-A-5 VACUOUSLY-SATISFIED NOTE:
//   The invariant requires "mandatory parameters have no defaults"; this
//   primitive has NO user-facing parameters (no DEPTH, no WIDTH, no count).
//   The set of mandatory-parameters-without-defaults is empty, and the
//   universal-quantification "all mandatory parameters have no default" is
//   vacuously true. No parameter is added solely to give the invariant
//   something to apply to; the right answer is "the primitive is
//   parameterless, the invariant is satisfied by emptiness".
//
//   Should a future deployment need a `RESET_VALUE` parameter (default IDLE)
//   to allow latched-on-reset behaviour, that would be a §15 amendment to
//   §6.10 (Standards Action per §5.2/§5.1 enum policy). Flagged as an open
//   question in the implementer's report.
//
// Byte-equivalent semantics to sos_strobe_latch.vhd; see that file's header
// for the full behavioural description and same-cycle arbitration rationale.
//------------------------------------------------------------------------------

`default_nettype none

module sos_strobe_latch (
    input  wire  clk,
    input  wire  rst,              // sync active-high (INV-S-HDL-A-1)
    input  wire  strobe,           // 1-cycle pulse from producer
    input  wire  ack,              // 1-cycle pulse from consumer
    output wire  latched,          // level: high while latched, low while IDLE
    output wire  latched_state_q   // observability: registered FSM state
);

    // --------------------------------------------------------------------
    // Internal one-hot FSM (per INV-S-HDL-A-4).
    //   state[0] = IDLE     -> latched = 0
    //   state[1] = LATCHED  -> latched = 1
    //
    // Even though there are only two states, the explicit one-hot encoding
    // mirrors sos_mutex's IDLE/HELD shape and keeps the synthesis-tool
    // one-hot optimisation discipline uniform across the L0 library
    // (INV-S-HDL-A-4 default + SOS-08 PCDN-002 ratified one-hot at v1).
    // --------------------------------------------------------------------
    localparam logic [1:0] ST_IDLE    = 2'b01;
    localparam logic [1:0] ST_LATCHED = 2'b10;

    reg [1:0] state;

    // ------------------------------------------------------------------
    // Sequential: one-hot IDLE <-> LATCHED FSM
    //
    // Same-cycle strobe + ack arbitration (canonical "ack-wins-on-same-cycle
    // from LATCHED" semantic): the LATCHED-branch checks `ack` first and
    // transitions to IDLE if asserted, regardless of `strobe`. The strobe is
    // dropped in that case. From IDLE, `strobe` drives the capture and `ack`
    // is a no-op (there is no latched state to clear).
    // ------------------------------------------------------------------
    always_ff @(posedge clk) begin
        if (rst) begin
            state <= ST_IDLE;
        end else begin
            unique case (state)
                ST_IDLE: begin
                    // IDLE: strobe captures; ack is a no-op.
                    if (strobe) begin
                        state <= ST_LATCHED;
                    end
                    // If strobe AND ack arrive same-cycle from IDLE:
                    // strobe wins (latches the event); ack is no-op
                    // (no latched state present to clear).
                end

                ST_LATCHED: begin
                    // LATCHED: ack clears regardless of strobe
                    // (canonical "ack-wins-on-same-cycle" — task brief).
                    // Re-strobe absorbed (no double-latch).
                    if (ack) begin
                        state <= ST_IDLE;
                    end
                end

                default: begin
                    // Illegal one-hot; recover to IDLE.
                    state <= ST_IDLE;
                end
            endcase
        end
    end

    // ------------------------------------------------------------------
    // Combinational outputs
    // ------------------------------------------------------------------
    assign latched         = (state == ST_LATCHED);
    assign latched_state_q = (state == ST_LATCHED);

endmodule

`default_nettype wire
