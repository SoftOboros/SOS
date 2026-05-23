//------------------------------------------------------------------------------
// sos_resource_pool.sv - L1 service: chart-tracked resource pool
//
// @spec        docs/concepts/SOS-08-B-CONCEPTS.md §6.3 (sos_resource_pool
//                                                       interface + behavioural
//                                                       contract + service-level
//                                                       SVA)
//              docs/concepts/SOS-08-B-CONCEPTS.md §15 (2026-05-23 ratification:
//                                                       PCDN-SOS-08-B-003 →
//                                                       ID_WIDTH parameterised
//                                                       with default 16,
//                                                       matching chart's
//                                                       task_id.)
//              docs/concepts/SOS-08-A-CONCEPTS.md §6.6 (sos_credit_counter L0
//                                                       primitive composed here)
//              docs/concepts/SOS-08-A-CONCEPTS.md §6.7 (sos_dpram_arb L0
//                                                       primitive composed here)
// @parent      docs/concepts/SOS-08-CONCEPTS.md §6 (L1 service set), §7
//                                                  (INV-S-HDL-1..5)
// @grandparent docs/concepts/SOS-07-CONCEPTS.md §6 (INV-SOS-A..H)
//
// Invariants cited (not re-derived):
//   INV-SOS-A..H        (SOS-07 §6)
//   INV-S-HDL-1..5      (SOS-08 §7)
//   INV-S-HDL-B-1..5    (SOS-08-B §7)
//
// Byte-equivalent semantics to sos_resource_pool.vhd; see that file's header
// for the full behavioural description, the same-cycle alloc + free
// resolution rule, and the priority-encoder direction (lowest-id-first).
//
// Static elaboration-time checks (matches L0 primitives via $fatal in an
// `initial` block):
//   * POOL_SIZE  >= 1
//   * META_WIDTH >= 1
//   * ID_WIDTH   >= $clog2(POOL_SIZE)
//------------------------------------------------------------------------------

`default_nettype none

module sos_resource_pool #(
    // Mandatory; no default per INV-S-HDL-A-5 (composed-by-extension at L1).
    parameter int POOL_SIZE                              /* no default */,
    // Default 16 per PCDN-SOS-08-B-003 resolution (matches chart's task_id
    // width). Per-pool override at chart-emission time.
    parameter int ID_WIDTH   = 16,
    // Mandatory; no default.
    parameter int META_WIDTH                             /* no default */,
    // Derived widths — not user-facing.
    localparam int CW     = $clog2(POOL_SIZE + 1),
    localparam int ADDR_W = (POOL_SIZE <= 1) ? 1 : $clog2(POOL_SIZE)
) (
    input  wire                       clk,
    input  wire                       rst,            // sync active-high

    // alloc side: pulse req in, pulse ack + id out.
    input  wire                       alloc_req,      // 1-cycle pulse
    output wire                       alloc_ack,      // 1-cycle pulse on success
    output wire [ID_WIDTH-1:0]        alloc_id,       // valid only when alloc_ack=1

    // free side: pulse req in, id in.
    input  wire                       free_req,       // 1-cycle pulse
    input  wire [ID_WIDTH-1:0]        free_id,

    // read side: FWFT (combinational) read by id.
    input  wire [ID_WIDTH-1:0]        read_id,
    output wire [META_WIDTH-1:0]      read_meta,

    // write side: pulse req in, id + meta in.
    input  wire                       write_req,      // 1-cycle pulse
    input  wire [ID_WIDTH-1:0]        write_id,
    input  wire [META_WIDTH-1:0]      write_meta,

    // observability: count of currently-free slots.
    output wire [CW-1:0]              free_count
);

    // ------------------------------------------------------------------
    // Elaboration-time static assertions.
    // ------------------------------------------------------------------
    initial begin
        if (POOL_SIZE < 1) begin
            $fatal(1,
                "sos_resource_pool: POOL_SIZE must be >= 1; got %0d",
                POOL_SIZE);
        end
        if (META_WIDTH < 1) begin
            $fatal(1,
                "sos_resource_pool: META_WIDTH must be >= 1; got %0d",
                META_WIDTH);
        end
        if (ID_WIDTH < ADDR_W) begin
            $fatal(1,
                "sos_resource_pool: ID_WIDTH (%0d) must be >= clog2(POOL_SIZE)=%0d",
                ID_WIDTH, ADDR_W);
        end
    end

    // ------------------------------------------------------------------
    // Inner credit counter handshake signals.
    // ------------------------------------------------------------------
    wire             cc_acquire_ack;
    wire [CW-1:0]    cc_credits;
    wire             cc_acquire_req;
    wire             cc_release_req;

    // ------------------------------------------------------------------
    // Free-vector tracker. 1 = slot free; 0 = slot busy (allocated).
    // Reset value = all-ones (every slot free) — matches credit_counter
    // INIT_CREDITS = POOL_SIZE. SVA-POOL-4 conservation:
    // popcount(free_vec) == cc_credits at every cycle after reset.
    // ------------------------------------------------------------------
    reg [POOL_SIZE-1:0] free_vec;

    // ------------------------------------------------------------------
    // Lowest-set-bit priority encoder over free_vec. The chosen-bit
    // direction is lowest-id-first (rationale documented in the VHDL
    // sibling's header).
    // ------------------------------------------------------------------
    wire             have_free = |free_vec;
    reg  [ADDR_W-1:0] alloc_idx;

    integer pi;
    always_comb begin
        alloc_idx = '0;
        for (pi = POOL_SIZE - 1; pi >= 0; pi = pi - 1) begin
            if (free_vec[pi]) begin
                alloc_idx = ADDR_W'(pi);
            end
        end
        // The loop assigns from high → low, so the LAST write wins and
        // we end up with the lowest-set-bit index. Functionally equivalent
        // to the "find first set" semantics of the VHDL companion's
        // forward-found-and-break loop.
    end

    // ------------------------------------------------------------------
    // Index conversions. Chart-emitted code keeps ID_WIDTH-wide handles
    // at the L1 boundary; the inner DPRAM and free-vec are ADDR_W-wide.
    // High bits of *_id are ignored — chart compiler enforces correctness
    // (INV-SOS-G).
    // ------------------------------------------------------------------
    wire [ADDR_W-1:0] free_idx  = free_id[ADDR_W-1:0];
    wire [ADDR_W-1:0] write_idx = write_id[ADDR_W-1:0];
    wire [ADDR_W-1:0] read_idx  = read_id[ADDR_W-1:0];

    // ------------------------------------------------------------------
    // Credit counter composition.
    //   INIT_CREDITS = POOL_SIZE, MAX_CREDITS = POOL_SIZE.
    //   acquire_req fires when alloc_req && have_free.
    //   release_req fires when free_req && (free_vec[free_idx] == 0)
    //               — i.e. when the freed slot is currently busy. Double-
    //                  free silently dropped per SVA-POOL-2.
    // ------------------------------------------------------------------
    assign cc_acquire_req = alloc_req & have_free;
    assign cc_release_req = free_req  & ~free_vec[free_idx];

    sos_credit_counter #(
        .INIT_CREDITS (POOL_SIZE),
        .MAX_CREDITS  (POOL_SIZE)
    ) u_credit (
        .clk         (clk),
        .rst         (rst),
        .acquire_req (cc_acquire_req),
        .acquire_ack (cc_acquire_ack),
        .release_req (cc_release_req),
        .credits     (cc_credits)
    );

    // ------------------------------------------------------------------
    // DPRAM composition. SINGLE_CLOCK, READ_LATENCY=0 (FWFT), RESET_MEM=0.
    // SYNC_STAGES uses the default of 2 (unused in SINGLE_CLOCK but part
    // of the surface).
    //
    // port_a: write + read driven by this service.
    //   - port_a_addr = write_idx on write cycles, read_idx otherwise.
    //   - port_a_we   = write_req.
    //   - port_a_re   = 1 (FWFT — read always observes mem[port_a_addr]).
    //
    // port_b: tied off in v1.
    // ------------------------------------------------------------------
    wire [ADDR_W-1:0]    dpa_addr  = write_req ? write_idx : read_idx;
    wire [META_WIDTH-1:0] dpa_wdata = write_meta;
    wire                 dpa_we    = write_req;
    wire                 dpa_re    = 1'b1;
    wire [META_WIDTH-1:0] dpa_rdata;
    wire                 dpa_full;
    wire                 dpa_ready;

    wire [META_WIDTH-1:0] dpb_rdata;
    wire                 dpb_full;
    wire                 dpb_ready;

    sos_dpram_arb #(
        .DEPTH        (POOL_SIZE),
        .WIDTH        (META_WIDTH),
        .MODE         ("SINGLE_CLOCK"),
        .READ_LATENCY (0),                  // FWFT
        .RESET_MEM    (1'b0),               // retained — chart inits on boot
        .SYNC_STAGES  (2)                   // unused in SINGLE_CLOCK
    ) u_dpram (
        .clk          (clk),
        .rst          (rst),
        .clk_a        (clk),                // tied; unused in SINGLE_CLOCK
        .rst_a        (rst),
        .clk_b        (clk),
        .rst_b        (rst),

        .port_a_addr  (dpa_addr),
        .port_a_wdata (dpa_wdata),
        .port_a_we    (dpa_we),
        .port_a_re    (dpa_re),
        .port_a_rdata (dpa_rdata),
        .port_a_full  (dpa_full),
        .port_a_ready (dpa_ready),

        .port_b_addr  ({ADDR_W{1'b0}}),
        .port_b_wdata ({META_WIDTH{1'b0}}),
        .port_b_we    (1'b0),               // v1: port B reserved
        .port_b_re    (1'b0),
        .port_b_rdata (dpb_rdata),
        .port_b_full  (dpb_full),
        .port_b_ready (dpb_ready)
    );

    // ------------------------------------------------------------------
    // free_vec update.
    //
    // Pre-update free_vec gates both the alloc-bit-clear and the free-
    // bit-set, mirroring sos_credit_counter's "pre-update credits for
    // both gates" shape. Same-cycle alloc + free on the same id resolves
    // to bit=0 (busy) because alloc takes priority — see VHDL header.
    // ------------------------------------------------------------------
    always_ff @(posedge clk) begin
        if (rst) begin
            free_vec <= {POOL_SIZE{1'b1}};  // all slots free at reset
        end else begin
            // Local mutable next-value computed off pre-update free_vec.
            // Free first (set the bit) — only when the slot is currently
            // busy. Double-free is silently dropped.
            // Alloc second (clear the bit) — overrides any same-cycle
            // free-of-the-just-allocated-slot when free_id == alloc_id.
            // Implemented as a single non-blocking assignment over a
            // computed value to keep the inferred logic flat.
            free_vec <= apply_alloc(apply_free(free_vec, free_req,
                                               free_idx),
                                    alloc_req, have_free, alloc_idx);
        end
    end

    // Pure functions to keep the body legible. SV does not allow these
    // to be declared local to an always_ff so they live at module scope.
    function automatic [POOL_SIZE-1:0] apply_free(
        input [POOL_SIZE-1:0] vec,
        input                 do_free,
        input [ADDR_W-1:0]    idx
    );
        apply_free = vec;
        if (do_free && !vec[idx]) begin
            apply_free[idx] = 1'b1;
        end
    endfunction

    function automatic [POOL_SIZE-1:0] apply_alloc(
        input [POOL_SIZE-1:0] vec,
        input                 do_alloc,
        input                 have,
        input [ADDR_W-1:0]    idx
    );
        apply_alloc = vec;
        if (do_alloc && have) begin
            apply_alloc[idx] = 1'b0;
        end
    endfunction

    // ------------------------------------------------------------------
    // Outputs.
    // ------------------------------------------------------------------
    assign alloc_ack  = cc_acquire_ack;
    // Zero-extend ADDR_W → ID_WIDTH (ID_WIDTH >= ADDR_W per elab check).
    // Use ID_WIDTH'() cast — handles ID_WIDTH == ADDR_W (no extension) and
    // ID_WIDTH > ADDR_W (zero-fill the upper bits) uniformly.
    assign alloc_id   = ID_WIDTH'(alloc_idx);
    assign read_meta  = dpa_rdata;
    assign free_count = cc_credits;

endmodule

`default_nettype wire
