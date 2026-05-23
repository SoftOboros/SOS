//------------------------------------------------------------------------------
// sos_credit_counter.sv - L0 primitive: distributed semaphore (resource credits)
//
// @spec        docs/concepts/SOS-08-A-CONCEPTS.md §6.6
// @amendments  docs/concepts/SOS-08-A-CONCEPTS.md §15 (2026-05-23 entries):
//              - PCDN-A-002: control-only primitives use bare `req`/`ack`.
//              - PCDN-A-mutex-ack: this primitive uses the **pulse** variant
//                of §5.1's control-handshake (one-shot per acquire attempt).
//                Counter-stateful but NOT ownership-tracking, so pulse-based
//                ack is the canonical shape — `acquire_ack` is a 1-cycle
//                pulse on the cycle the acquire succeeds; if `credits == 0`
//                when `acquire_req` fires the ack stays low and the
//                requester must retry next cycle.
//              - PCDN-A-bind-form: module-type bind in companion
//                `sos_credit_counter_bind.sv`.
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
//   INV-S-HDL-1  handshake-compatible ports     (SOS-08 §7)
//   INV-S-HDL-2  static-allocation discipline   (SOS-08 §7)
//   INV-S-HDL-3  cross-domain isolation         (SOS-08 §7) — N/A: single domain
//   INV-S-HDL-4  cooperative-only at v1         (SOS-08 §7)
//   INV-S-HDL-5  vector-to-chart traceability   (SOS-08 §7)
//
//   INV-S-HDL-A-1 uniform reset semantics       (SOS-08-A §7) — sync active-high
//   INV-S-HDL-A-2 handshake associativity       (SOS-08-A §7)
//   INV-S-HDL-A-3 vendor-shim byte-identical    (SOS-08-A §7) — portable-only here
//   INV-S-HDL-A-4 one-hot internal FSM default  (SOS-08-A §7) — N/A: pure counter
//   INV-S-HDL-A-5 mandatory params no defaults  (SOS-08-A §7)
//                  — both INIT_CREDITS and MAX_CREDITS have NO defaults.
//
// Byte-equivalent semantics to sos_credit_counter.vhd; see that file's header
// for the full behavioural description.
//
// Static elaboration-time check: INIT_CREDITS <= MAX_CREDITS (enforced by an
// `initial` block `$fatal`; the VHDL companion has the matching concurrent
// assertion as the binding gate for VHDL-flow synthesis).
//------------------------------------------------------------------------------

`default_nettype none

module sos_credit_counter #(
    // Mandatory; no default per INV-S-HDL-A-5.
    parameter int INIT_CREDITS                            /* no default */,
    // Mandatory; no default per INV-S-HDL-A-5.
    parameter int MAX_CREDITS                             /* no default */,
    // Derived width: enough bits to encode {0..MAX_CREDITS}. Not user-exposed
    // per §6.6 interface signature; the credits port width follows.
    localparam int CW = $clog2(MAX_CREDITS + 1)
) (
    input  wire             clk,
    input  wire             rst,            // sync active-high
    input  wire             acquire_req,    // 1-cycle pulse
    output wire             acquire_ack,    // 1-cycle pulse on success
    input  wire             release_req,    // 1-cycle pulse
    output wire [CW-1:0]    credits         // observability
);

    // ------------------------------------------------------------------
    // Elaboration-time static assertions.
    //   * MAX_CREDITS >= 1 enforced by the `parameter int MAX_CREDITS`
    //     positive-domain expectation in VHDL; here we add the runtime
    //     check explicitly for SV-flow synthesis.
    //   * INIT_CREDITS <= MAX_CREDITS enforced explicitly.
    // ------------------------------------------------------------------
    initial begin
        if (MAX_CREDITS < 1) begin
            $fatal(1,
                "sos_credit_counter: MAX_CREDITS must be >= 1; got %0d",
                MAX_CREDITS);
        end
        if (INIT_CREDITS < 0) begin
            $fatal(1,
                "sos_credit_counter: INIT_CREDITS must be >= 0; got %0d",
                INIT_CREDITS);
        end
        if (INIT_CREDITS > MAX_CREDITS) begin
            $fatal(1,
                "sos_credit_counter: INIT_CREDITS (%0d) must be <= MAX_CREDITS (%0d)",
                INIT_CREDITS, MAX_CREDITS);
        end
    end

    // ------------------------------------------------------------------
    // State: the credit pool itself. A pure counter (no internal FSM), so
    // INV-S-HDL-A-4 (one-hot internal FSM default) does not apply.
    // ------------------------------------------------------------------
    reg [CW-1:0] credits_r;

    // Combinational ack: pulse high when acquire requested and credits > 0.
    wire acquire_ok = acquire_req & (|credits_r);

    // Same-cycle release gate: only when credits < MAX_CREDITS (silent drop
    // at the bound — chart compiler enforces correctness per INV-SOS-G).
    wire release_ok = release_req & (credits_r < CW'(MAX_CREDITS));

    // ------------------------------------------------------------------
    // Sequential counter update.
    //
    //   credits_r_next = credits_r
    //                  + (release_ok ? 1 : 0)
    //                  - (acquire_ok ? 1 : 0);
    //
    // Both gates evaluated on credits_r (pre-update). Same-cycle
    // acquire+release is net-neutral as documented above.
    // ------------------------------------------------------------------
    always_ff @(posedge clk) begin
        if (rst) begin
            credits_r <= CW'(INIT_CREDITS);
        end else begin
            unique case ({release_ok, acquire_ok})
                2'b00: credits_r <= credits_r;
                2'b01: credits_r <= credits_r - CW'(1);
                2'b10: credits_r <= credits_r + CW'(1);
                2'b11: credits_r <= credits_r;          // net-neutral
                default: credits_r <= credits_r;
            endcase
        end
    end

    // ------------------------------------------------------------------
    // Outputs
    // ------------------------------------------------------------------
    assign acquire_ack = acquire_ok;
    assign credits     = credits_r;

endmodule

`default_nettype wire
