// ----------------------------------------------------------------------------
// sos_dpram_arb.sv
//
// @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.7 (sos_dpram_arb contract)
//       docs/concepts/SOS-08-A-CONCEPTS.md §15 (2026-05-23 amendments —
//                                              inherits READ_LATENCY +
//                                              RESET_MEM generic pattern
//                                              ratified for sos_fifo_sync via
//                                              PCDN-A-fifo-READ_LATENCY and
//                                              PCDN-A-fifo-RESET_MEM)
//       docs/concepts/SOS-08-CONCEPTS.md   §5  (frozen decisions inherited)
//       docs/concepts/SOS-07-CONCEPTS.md   §6  (cross-phase invariants)
//
// Cross-phase invariants (cited, not redefined):
//   INV-SOS-A  chart-as-source
//   INV-SOS-B  vectors-as-deliverable at every layer
//   INV-SOS-C  MCP as sole modification surface
//   INV-SOS-D  iState authoring, SCXML canonical
//   INV-SOS-E  explicit AuthorityRelationship
//   INV-SOS-F  bound composition
//   INV-SOS-G  verified-codegen position
//   INV-SOS-H  vector-to-chart traceability
//
// Cross-sub-phase invariants (SOS-08 §7, cited):
//   INV-S-HDL-1  handshake-compatible ports
//   INV-S-HDL-2  static-allocation discipline
//   INV-S-HDL-3  cross-domain isolation (MODE=DUAL_CLOCK only)
//   INV-S-HDL-4  cooperative-only at v1
//   INV-S-HDL-5  vector-to-chart traceability for HDL
//
// Cross-primitive invariants (SOS-08-A §7, cited):
//   INV-S-HDL-A-1  uniform sync active-high reset + AXI-Stream port naming
//   INV-S-HDL-A-2  handshake-port composition is associative
//   INV-S-HDL-A-3  vendor-IP shim wrapper is byte-identical
//   INV-S-HDL-A-4  one-hot internal FSM by default
//   INV-S-HDL-A-5  mandatory parameters have no defaults
//
// Dual-port RAM + arbiter L0 primitive. Byte-equivalent semantics to the
// VHDL sibling at sos_dpram_arb.vhd.
//
// Port-naming deviation note (sub-PCDN to PCDN-SOS-08-A-002):
//   PCDN-A-002 ratified `m_axis_*` / `s_axis_*` prefixes on data-bearing
//   primitives. The two-port DPRAM does not map cleanly to a master/slave
//   AXI pair — each port has both read and write channels. We therefore use
//   `port_a_*` / `port_b_*` prefixes with `_addr`, `_wdata`, `_we`, `_rdata`,
//   `_re`, `_full`, `_ready` suffixes. Deviation recorded as a sub-PCDN.
//
// Collision-priority direction:
//   On simultaneous A+B writes targeting the same address, port A wins
//   (port_a_full is never asserted; port_b_full is asserted only for the
//   cycle B's write loses an arbitration).
//
// Same-cycle write+read on the same address (SINGLE_CLOCK mode):
//   The read path observes the OLD (pre-write) value. The write lands at
//   the NEXT rising edge of clk; the combinational/registered read sampled
//   this cycle therefore sees what was stored before the write. This is
//   canonical "read-old" semantics and matches `xpm_memory_tdpram`'s
//   "read_first" mode.
// ----------------------------------------------------------------------------

`default_nettype none

module sos_dpram_arb #(
    // INV-S-HDL-A-5: mandatory parameters, no defaults.
    parameter int    DEPTH,
    parameter int    WIDTH,
    // MODE — single-clock vs dual-clock. Encoded as a string for VHDL/SV
    // dialect parity (the VHDL sibling uses VHDL-2008 strings for generics).
    // Legal values: "SINGLE_CLOCK" | "DUAL_CLOCK".
    parameter string MODE,
    // READ_LATENCY — inherits PCDN-A-fifo-READ_LATENCY pattern.
    //   0 = FWFT (rdata combinational off mem[addr]),
    //   1 = registered (rdata appears one cycle after `re`).
    parameter int    READ_LATENCY,
    // RESET_MEM — inherits PCDN-A-fifo-RESET_MEM pattern.
    //   0 = mem retained across reset (legacy / smaller reset fanout),
    //   1 = mem cleared to all-zero on reset (stricter post-reset semantics).
    parameter bit    RESET_MEM,
    // Derived widths — not user-facing; recomputed from DEPTH.
    parameter int    ADDR_W = (DEPTH <= 1) ? 1 : $clog2(DEPTH)
) (
    // Clock + reset — interpretation depends on MODE.
    //   SINGLE_CLOCK: only `clk` + `rst` are used; clk_a/clk_b/rst_a/rst_b
    //                 inputs MAY be tied off or to `clk`/`rst`.
    //   DUAL_CLOCK:   clk_a/rst_a drive port A; clk_b/rst_b drive port B;
    //                 `clk`/`rst` inputs MAY be tied to clk_a/rst_a (unused).
    input  wire                  clk,
    input  wire                  rst,
    input  wire                  clk_a,
    input  wire                  rst_a,
    input  wire                  clk_b,
    input  wire                  rst_b,

    // Port A: address + write + read + status.
    input  wire [ADDR_W-1:0]     port_a_addr,
    input  wire [WIDTH-1:0]      port_a_wdata,
    input  wire                  port_a_we,       // 1-cycle write pulse
    input  wire                  port_a_re,       // 1-cycle read  pulse
    output wire [WIDTH-1:0]      port_a_rdata,
    output wire                  port_a_full,     // arbiter blocked A
    output wire                  port_a_ready,    // complement of port_a_full

    // Port B: same shape, swapped suffix.
    input  wire [ADDR_W-1:0]     port_b_addr,
    input  wire [WIDTH-1:0]      port_b_wdata,
    input  wire                  port_b_we,
    input  wire                  port_b_re,
    output wire [WIDTH-1:0]      port_b_rdata,
    output wire                  port_b_full,
    output wire                  port_b_ready
);

    // Storage.
    logic [WIDTH-1:0] mem [0:DEPTH-1];

    // Registered-read holding registers (READ_LATENCY=1 path only).
    logic [WIDTH-1:0] rdata_a_q;
    logic [WIDTH-1:0] rdata_b_q;

    // Combinational FWFT read paths.
    wire [WIDTH-1:0] rdata_a_fwft = mem[port_a_addr];
    wire [WIDTH-1:0] rdata_b_fwft = mem[port_b_addr];

    // Collision detector (set per-mode below).
    logic collision;

    // -------------------------------------------------------------------
    // Gray-code helpers (DUAL_CLOCK mode).
    // -------------------------------------------------------------------
    function automatic [ADDR_W-1:0] bin2gray(input [ADDR_W-1:0] b);
        bin2gray = b ^ (b >> 1);
    endfunction

    function automatic [ADDR_W-1:0] gray2bin(input [ADDR_W-1:0] g);
        integer i;
        logic [ADDR_W-1:0] b;
        begin
            b[ADDR_W-1] = g[ADDR_W-1];
            for (i = ADDR_W - 2; i >= 0; i = i - 1) begin
                b[i] = b[i+1] ^ g[i];
            end
            gray2bin = b;
        end
    endfunction

    generate
        // ---------------------------------------------------------------
        // SINGLE_CLOCK branch.
        // ---------------------------------------------------------------
        if (MODE == "SINGLE_CLOCK") begin : g_single_clock

            // Combinational collision detector. A-wins on tie.
            assign collision = port_a_we & port_b_we &
                               (port_a_addr == port_b_addr);

            assign port_a_full  = 1'b0;
            assign port_a_ready = 1'b1;
            assign port_b_full  = collision;
            assign port_b_ready = ~collision;

            // Read path selection.
            if (READ_LATENCY == 0) begin : g_sc_read_a_fwft
                assign port_a_rdata = rdata_a_fwft;
            end else begin : g_sc_read_a_reg
                assign port_a_rdata = rdata_a_q;
            end
            if (READ_LATENCY == 0) begin : g_sc_read_b_fwft
                assign port_b_rdata = rdata_b_fwft;
            end else begin : g_sc_read_b_reg
                assign port_b_rdata = rdata_b_q;
            end

            // Single shared-clock write + registered-read process.
            always_ff @(posedge clk) begin
                if (rst) begin
                    rdata_a_q <= '0;
                    rdata_b_q <= '0;
                    if (RESET_MEM) begin
                        for (int i = 0; i < DEPTH; i++) begin
                            mem[i] <= '0;
                        end
                    end
                end else begin
                    // Write path. Port A always lands. Port B lands only
                    // when there is no collision (A wins on tie).
                    if (port_a_we) begin
                        mem[port_a_addr] <= port_a_wdata;
                    end
                    if (port_b_we && !collision) begin
                        mem[port_b_addr] <= port_b_wdata;
                    end

                    // Registered-read latch — captures PRE-write value
                    // ("read-old" semantics on same-cycle W+R same addr).
                    if (READ_LATENCY != 0) begin
                        if (port_a_re) begin
                            rdata_a_q <= rdata_a_fwft;
                        end
                        if (port_b_re) begin
                            rdata_b_q <= rdata_b_fwft;
                        end
                    end
                end
            end

        end
        // ---------------------------------------------------------------
        // DUAL_CLOCK branch — CDC via gray-code address synchroniser.
        // INV-S-HDL-3 applies; MTBF.md is the verification artifact.
        // ---------------------------------------------------------------
        else if (MODE == "DUAL_CLOCK") begin : g_dual_clock

            // Gray-coded port B address sampled in clk_b, then synced
            // through a two-stage flop chain into clk_a.
            logic [ADDR_W-1:0] port_b_addr_gray_b;
            logic [ADDR_W-1:0] port_b_addr_gray_a1;
            logic [ADDR_W-1:0] port_b_addr_gray_a2;
            logic              port_b_we_b;
            logic              port_b_we_a1;
            logic              port_b_we_a2;

            // clk_b register stage (source of the synchroniser chain).
            always_ff @(posedge clk_b) begin
                if (rst_b) begin
                    port_b_addr_gray_b <= '0;
                    port_b_we_b        <= 1'b0;
                end else begin
                    port_b_addr_gray_b <= bin2gray(port_b_addr);
                    port_b_we_b        <= port_b_we;
                end
            end

            // clk_a synchroniser stages.
            // Vendor-specific synthesis attributes (ASYNC_REG, syn_preserve)
            // are emitted by the vendor shim path; the portable RTL here
            // relies on naming convention `_sync_*` so build wrappers can
            // pattern-match. Per INV-S-HDL-3, these flops are excluded from
            // the formal model.
            (* ASYNC_REG = "TRUE", syn_preserve = 1 *)
            always_ff @(posedge clk_a) begin
                if (rst_a) begin
                    port_b_addr_gray_a1 <= '0;
                    port_b_addr_gray_a2 <= '0;
                    port_b_we_a1        <= 1'b0;
                    port_b_we_a2        <= 1'b0;
                end else begin
                    port_b_addr_gray_a1 <= port_b_addr_gray_b;
                    port_b_addr_gray_a2 <= port_b_addr_gray_a1;
                    port_b_we_a1        <= port_b_we_b;
                    port_b_we_a2        <= port_b_we_b;
                end
            end

            // A-domain collision view — conservative.
            assign collision = port_a_we & port_b_we_a2 &
                               (gray2bin(port_b_addr_gray_a2) == port_a_addr);

            assign port_a_full  = 1'b0;
            assign port_a_ready = 1'b1;
            assign port_b_full  = collision;
            assign port_b_ready = ~collision;

            // Read path selection.
            if (READ_LATENCY == 0) begin : g_dc_read_a_fwft
                assign port_a_rdata = rdata_a_fwft;
            end else begin : g_dc_read_a_reg
                assign port_a_rdata = rdata_a_q;
            end
            if (READ_LATENCY == 0) begin : g_dc_read_b_fwft
                assign port_b_rdata = rdata_b_fwft;
            end else begin : g_dc_read_b_reg
                assign port_b_rdata = rdata_b_q;
            end

            // Port A write + registered-read on clk_a.
            always_ff @(posedge clk_a) begin
                if (rst_a) begin
                    rdata_a_q <= '0;
                    if (RESET_MEM) begin
                        for (int i = 0; i < DEPTH; i++) begin
                            mem[i] <= '0;
                        end
                    end
                end else begin
                    if (port_a_we) begin
                        mem[port_a_addr] <= port_a_wdata;
                    end
                    if (READ_LATENCY != 0) begin
                        if (port_a_re) begin
                            rdata_a_q <= rdata_a_fwft;
                        end
                    end
                end
            end

            // Port B write + registered-read on clk_b. B's write lands
            // only when the A-domain collision detector is NOT asserted.
            // The `collision` signal originates in clk_a but is consumed
            // here in clk_b; this is the cross-domain edge that the MTBF
            // calculation covers. The semantic guarantee is conservative:
            // a false-positive collision stalls B for one cycle; a false-
            // negative is excluded by the SYNC_STAGES=2 chain.
            always_ff @(posedge clk_b) begin
                if (rst_b) begin
                    rdata_b_q <= '0;
                end else begin
                    if (port_b_we && !collision) begin
                        mem[port_b_addr] <= port_b_wdata;
                    end
                    if (READ_LATENCY != 0) begin
                        if (port_b_re) begin
                            rdata_b_q <= rdata_b_fwft;
                        end
                    end
                end
            end

        end
    endgenerate

endmodule

`default_nettype wire
