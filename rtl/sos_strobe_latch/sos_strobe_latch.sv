//------------------------------------------------------------------------------
// sos_strobe_latch.sv - L0 primitive: pulse-to-level + ack + depth-1 shadow
//
// @spec        docs/concepts/SOS-08-A-CONCEPTS.md §6.10
// @parent      docs/concepts/SOS-08-CONCEPTS.md §6 (L0 set), §7 (INV-S-HDL-1..5)
// @grandparent docs/concepts/SOS-07-CONCEPTS.md §6 (INV-SOS-A..H)
//
// PCDN-A-strobe-pending-shadow resolved 2026-05-23 (§15): the primitive
// carries a depth-1 `pending_strobe` shadow register so that a strobe arriving
// same-cycle with ack-from-LATCHED is captured rather than dropped. The FSM
// expands from a 2-state (IDLE / LATCHED) one-hot to a 3-state one-hot
// (IDLE / LATCHED / LATCHED_PENDING), and a new observability port
// `pending_q` exposes the shadow bit.
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
//   INV-S-HDL-A-4 one-hot internal FSM default  (SOS-08-A §7) — 3-state one-hot
//                 (IDLE / LATCHED / LATCHED_PENDING). The shadow register is
//                 encoded INTO the FSM state, not as a separate flip-flop, so
//                 the one-hot encoding remains the sole state representation.
//                 SUPERSEDES the prior "IDLE/LATCHED 2-state one-hot" reading.
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
//     * `strobe` (in)    -- PULSE-BASED (1-cycle pulse) per §5.1(a). Producer
//                           emits a one-shot event; consumer is the latch.
//     * `latched` (out)  -- LEVEL-HELD per §5.1(b). The latched-state output
//                           is asserted for every cycle between strobe-capture
//                           and ack, mirroring sos_mutex `ack[i]`'s
//                           ownership-tracking shape.
//     * `ack` (in)       -- PULSE-BASED (1-cycle pulse) per §5.1(a). Consumer
//                           acknowledges the latched event and clears the state.
//     * `pending_q` (out)-- LEVEL-HELD observability of the depth-1 shadow.
//   The §6.10 contract literal "pulse-to-level + ack" describes exactly this
//   shape: strobe (pulse) -> latched (level) -> ack (pulse), with the shadow
//   bridging the same-cycle race from LATCHED.
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
//   §6.10 (Standards Action per §5.2/§5.1 enum policy). Likewise, any
//   widening of the shadow depth beyond 1 is a §15 amendment.
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
    output wire  pending_q,        // level: high while shadow holds a pending strobe
    output wire  latched_state_q   // observability: registered FSM latched state
);

    // --------------------------------------------------------------------
    // Internal one-hot FSM (per INV-S-HDL-A-4).
    //   state[0] = IDLE             -> latched = 0, pending_q = 0
    //   state[1] = LATCHED          -> latched = 1, pending_q = 0
    //   state[2] = LATCHED_PENDING  -> latched = 1, pending_q = 1
    //
    // The shadow strobe is encoded as a distinct FSM state rather than a
    // separate register so that the one-hot encoding is the SOLE state
    // representation. The 4th codepoint (IDLE_WITH_PENDING) is unreachable
    // — a strobe in IDLE always promotes to LATCHED, never to PENDING.
    // --------------------------------------------------------------------
    localparam logic [2:0] ST_IDLE            = 3'b001;
    localparam logic [2:0] ST_LATCHED         = 3'b010;
    localparam logic [2:0] ST_LATCHED_PENDING = 3'b100;

    reg [2:0] state;

    // ------------------------------------------------------------------
    // Sequential: one-hot IDLE / LATCHED / LATCHED_PENDING FSM
    //
    // Same-cycle strobe + ack arbitration (refined ack-wins-from-LATCHED
    // with depth-1 shadow): in the LATCHED branch, ack consumes the live
    // event while a concurrent strobe captures into the shadow; the net
    // next-state is LATCHED (shadow promotes to live on the same edge).
    // In the LATCHED_PENDING branch, ack consumes the live event and
    // promotes the shadow; an additional strobe is dropped.
    // ------------------------------------------------------------------
    always_ff @(posedge clk) begin
        if (rst) begin
            state <= ST_IDLE;
        end else begin
            unique case (state)
                ST_IDLE: begin
                    // IDLE: strobe captures into LATCHED; ack is a no-op.
                    // Concurrent strobe+ack from IDLE: strobe wins.
                    if (strobe) begin
                        state <= ST_LATCHED;
                    end
                end

                ST_LATCHED: begin
                    // LATCHED + ack + strobe -> LATCHED  (consume live;
                    //   shadow captures strobe; shadow immediately
                    //   promotes to live -> stay in LATCHED.)
                    // LATCHED + ack          -> IDLE
                    // LATCHED + strobe       -> LATCHED_PENDING
                    // LATCHED (neither)      -> LATCHED
                    if (ack && strobe) begin
                        state <= ST_LATCHED;
                    end else if (ack) begin
                        state <= ST_IDLE;
                    end else if (strobe) begin
                        state <= ST_LATCHED_PENDING;
                    end
                end

                ST_LATCHED_PENDING: begin
                    // LATCHED_PENDING + ack  -> LATCHED (live consumed;
                    //   shadow promotes to live). Any concurrent strobe
                    //   is dropped (depth-1 saturated).
                    // LATCHED_PENDING + strobe (no ack) -> LATCHED_PENDING
                    //   (additional strobe dropped).
                    // LATCHED_PENDING (neither) -> LATCHED_PENDING
                    if (ack) begin
                        state <= ST_LATCHED;
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
    assign latched         = (state == ST_LATCHED) || (state == ST_LATCHED_PENDING);
    assign latched_state_q = (state == ST_LATCHED) || (state == ST_LATCHED_PENDING);
    assign pending_q       = (state == ST_LATCHED_PENDING);

endmodule

`default_nettype wire
