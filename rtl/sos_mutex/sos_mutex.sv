//------------------------------------------------------------------------------
// sos_mutex.sv - L0 primitive: 1-bit lock register + round-robin arbiter
//
// @spec       docs/concepts/SOS-08-A-CONCEPTS.md §6.5
// @parent     docs/concepts/SOS-08-CONCEPTS.md §6 (L0 set), §7 (INV-S-HDL-1..5)
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
//   INV-S-HDL-A-4 one-hot internal FSM default  (SOS-08-A §7)
//   INV-S-HDL-A-5 mandatory params no defaults  (SOS-08-A §7) — N_CLIENTS no default
//
// Per PCDN-A-002 resolution (§15 2026-05-23): control-only primitives use bare
// `req`/`ack` (not AXI-Stream prefixed). This is a control primitive.
//
// Per PCDN-A-mutex-N_CLIENTS-min resolved 2026-05-23: SOS-08-A §6.5 requires
// N_CLIENTS >= 2. A 1-client mutex is degenerate (the sole client always wins
// contention against the empty set, which collapses the round-robin contract
// to identity and erodes the "fairness bound across multiple requesters"
// claim). Enforced below by an elaboration-time $fatal in an `initial` block.
//
// Byte-equivalent semantics to sos_mutex.vhd; see that file's header for the
// full behavioural description.
//------------------------------------------------------------------------------

`default_nettype none

module sos_mutex #(
    // Number of requesting clients. Mandatory; no default per INV-S-HDL-A-5.
    // SystemVerilog has no clean way to refuse a default at elaboration; the
    // accompanying SVA module + lint config enforce explicit specification.
    parameter int N_CLIENTS                                  /* no default */,
    // Derived width: enough bits to encode {0..N_CLIENTS} (N_CLIENTS == unheld).
    localparam int HID_W = $clog2(N_CLIENTS + 1)
) (
    input  wire                  clk,
    input  wire                  rst,        // sync active-high
    input  wire [N_CLIENTS-1:0]  req,
    output reg  [N_CLIENTS-1:0]  ack,        // one-hot grant
    output wire                  locked,
    output wire [HID_W-1:0]      holder_id
);

    // --------------------------------------------------------------------
    // Internal one-hot FSM (per INV-S-HDL-A-4).
    //   state[0] = FREE
    //   state[1] = HELD
    // --------------------------------------------------------------------
    localparam logic [1:0] ST_FREE = 2'b01;
    localparam logic [1:0] ST_HELD = 2'b10;

    reg  [1:0]       state;
    reg  [HID_W-1:0] holder_r;
    reg  [HID_W-1:0] rr_ptr_r;

    // Sentinel "unheld" value.
    localparam logic [HID_W-1:0] NO_HOLDER = HID_W'(N_CLIENTS);

    // ------------------------------------------------------------------
    // Elaboration-time static assertion: N_CLIENTS >= 2.
    // Per PCDN-A-mutex-N_CLIENTS-min resolved 2026-05-23 (SOS-08-A §6.5).
    // Standard SV idiom: `initial` block fires at time 0 during simulation;
    // synthesis tools either honour the `$fatal` as an elab error or ignore
    // the initial block (in which case the VHDL companion's concurrent
    // assert remains the binding gate for VHDL-flow synthesis).
    // ------------------------------------------------------------------
    initial begin
        if (N_CLIENTS < 2) begin
            $fatal(1, "sos_mutex: SOS-08-A §6.5 requires N_CLIENTS >= 2; got %0d",
                   N_CLIENTS);
        end
    end

    // ------------------------------------------------------------------
    // Round-robin pick: lowest k in [0, N_CLIENTS) for which
    //   req[ (rr_ptr_r + k) % N_CLIENTS ] == 1.
    // Returns N_CLIENTS if no requester.
    // ------------------------------------------------------------------
    function automatic int rr_pick(
        input logic [N_CLIENTS-1:0] req_vec,
        input int                   start_idx
    );
        int idx;
        for (int k = 0; k < N_CLIENTS; k++) begin
            idx = (start_idx + k) % N_CLIENTS;
            if (req_vec[idx]) return idx;
        end
        return N_CLIENTS;
    endfunction

    // ------------------------------------------------------------------
    // Sequential FSM + holder + round-robin pointer
    // ------------------------------------------------------------------
    int picked;

    always_ff @(posedge clk) begin
        if (rst) begin
            state    <= ST_FREE;
            holder_r <= NO_HOLDER;
            rr_ptr_r <= '0;
        end else begin
            unique case (state)
                ST_FREE: begin
                    picked = rr_pick(req, int'(rr_ptr_r));
                    if (picked < N_CLIENTS) begin
                        state    <= ST_HELD;
                        holder_r <= HID_W'(picked);
                        rr_ptr_r <= HID_W'((picked + 1) % N_CLIENTS);
                    end
                end

                ST_HELD: begin
                    if (!req[holder_r]) begin
                        state    <= ST_FREE;
                        holder_r <= NO_HOLDER;
                        // rr_ptr_r already advanced at grant.
                    end
                end

                default: begin
                    // Illegal one-hot; recover.
                    state    <= ST_FREE;
                    holder_r <= NO_HOLDER;
                end
            endcase
        end
    end

    // ------------------------------------------------------------------
    // Combinational outputs
    // ------------------------------------------------------------------
    assign locked    = (state == ST_HELD);
    assign holder_id = holder_r;

    // One-hot ack: high for current holder while HELD; else zero.
    always_comb begin
        ack = '0;
        if (state == ST_HELD && holder_r < HID_W'(N_CLIENTS)) begin
            ack[holder_r] = 1'b1;
        end
    end

endmodule

`default_nettype wire
