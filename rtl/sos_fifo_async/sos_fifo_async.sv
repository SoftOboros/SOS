// ----------------------------------------------------------------------------
// sos_fifo_async.sv
//
// @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.1 (sos_fifo_async contract)
//       docs/concepts/SOS-08-A-CONCEPTS.md §15  (2026-05-23 ratification +
//                                                impl wave-1 PCDN amendments)
//       docs/concepts/SOS-08-CONCEPTS.md   §5  (frozen decisions inherited)
//       docs/concepts/SOS-07-CONCEPTS.md   §6  (cross-phase invariants)
//       PCDN-A-fifo-READ_LATENCY  resolved 2026-05-23 — adds READ_LATENCY
//                                  generic (0 = FWFT, 1 = registered read),
//                                  inherited pattern from sos_fifo_sync.
//       PCDN-A-fifo-RESET_MEM     resolved 2026-05-23 — adds RESET_MEM
//                                  generic (0 = legacy, 1 = clear mem),
//                                  inherited pattern from sos_fifo_sync.
//       PCDN-A-bind-form          resolved 2026-05-23 — module-type bind.
//
// Cross-phase invariants (cited, not redefined):
//   INV-SOS-A  chart-as-source
//   INV-SOS-B  vectors-as-deliverable at every layer
//   INV-SOS-C  bootstrap-vs-general framing
//   INV-SOS-D  verified-codegen position
//   INV-SOS-E  authority relationships
//   INV-SOS-F  iState authoring surface
//   INV-SOS-G  bounded-reachability discharge
//   INV-SOS-H  vector-to-chart traceability
//
// Cross-sub-phase invariants (SOS-08 §7, cited):
//   INV-S-HDL-1  handshake-compatible ports
//   INV-S-HDL-2  static-allocation discipline
//   INV-S-HDL-3  cross-domain isolation — applies; synchronizer flop chains
//                are excluded from formal proof. MTBF sign-off at MTBF.md.
//   INV-S-HDL-4  cooperative-only at v1
//   INV-S-HDL-5  vector-to-chart traceability for HDL
//
// Cross-primitive invariants (SOS-08-A §7, cited):
//   INV-S-HDL-A-1  uniform sync active-high reset + AXI-Stream port naming
//                  (per-side: wr_rst sync-to-wr_clk; rd_rst sync-to-rd_clk)
//   INV-S-HDL-A-2  handshake-port composition is associative
//   INV-S-HDL-A-3  vendor-IP shim wrapper is byte-identical
//   INV-S-HDL-A-4  one-hot internal FSM by default (no internal FSM here)
//   INV-S-HDL-A-5  mandatory parameters have no defaults (SYNC_STAGES is
//                  the documented exception — default 2, well-trodden)
//
// Cross-clock-domain FIFO. Portable SystemVerilog-2017 RTL. Two clock
// domains (wr_clk producer side, rd_clk consumer side); gray-coded pointer
// crossings, SYNC_STAGES-deep flop synchronizers. Byte-equivalent semantics
// to the VHDL sibling in sos_fifo_async.vhd.
// ----------------------------------------------------------------------------

`default_nettype none

module sos_fifo_async #(
    // INV-S-HDL-A-5: mandatory parameters, no defaults.
    //   DEPTH MUST be a power of two (gray-coded wraparound exploited).
    parameter int DEPTH,
    parameter int WIDTH,
    // PCDN-A-fifo-READ_LATENCY (2026-05-23): 0 = FWFT; 1 = registered read.
    parameter int READ_LATENCY,
    // PCDN-A-fifo-RESET_MEM (2026-05-23): 0 = mem retained; 1 = mem cleared
    // on wr_rst (writer owns the storage).
    parameter bit RESET_MEM,
    // SYNC_STAGES is the canonical CDC depth — default 2 is the
    // well-trodden value. Larger (3, 4) raises MTBF for high-frequency
    // / tight-budget designs. Build wrappers MUST re-sign-off MTBF.md
    // when overriding SYNC_STAGES > 2 or targeting a different process.
    parameter int SYNC_STAGES = 2,
    // Derived widths — not user-facing.
    //   PTR_W : index width for storage [0 .. DEPTH-1].
    //   GPTR_W: gray pointer carries one extra MSB (PTR_W+1 bits) so the
    //           full-vs-empty disambiguation works after wraparound.
    //   CNT_W : count width [0 .. DEPTH] inclusive.
    parameter int PTR_W  = (DEPTH <= 1) ? 1 : $clog2(DEPTH),
    parameter int GPTR_W = PTR_W + 1,
    parameter int CNT_W  = $clog2(DEPTH + 1)
) (
    // -- Write (producer) domain --------------------------------------
    // INV-S-HDL-A-1: sync active-high reset.
    input  wire                  wr_clk,
    input  wire                  wr_rst,

    // Slave AXI-Stream ingress (producer drives, FIFO accepts).
    input  wire [WIDTH-1:0]      s_axis_tdata,
    input  wire                  s_axis_tvalid,
    output wire                  s_axis_tready,

    // Write-side observability (bare names — not handshake-faced).
    output wire                  wr_full,
    output wire [CNT_W-1:0]      wr_count,

    // -- Read (consumer) domain ---------------------------------------
    input  wire                  rd_clk,
    input  wire                  rd_rst,

    // Master AXI-Stream egress (FIFO presents, consumer accepts).
    output wire [WIDTH-1:0]      m_axis_tdata,
    output wire                  m_axis_tvalid,
    input  wire                  m_axis_tready,

    // Read-side observability.
    output wire                  rd_empty,
    output wire [CNT_W-1:0]      rd_count
);

    // Storage. Inferred LUT-RAM for small DEPTH, BRAM for large. The mem
    // array is clocked on wr_clk (the writer owns the storage; the reader
    // does a combinational mem[rd_ptr] or latches via rdata_q).
    logic [WIDTH-1:0] mem [0:DEPTH-1];

    // Binary pointers (GPTR_W bits each — PTR_W+1 so the extra MSB
    // distinguishes full from empty after gray-coding).
    logic [GPTR_W-1:0] wr_ptr_bin;
    logic [GPTR_W-1:0] rd_ptr_bin;

    // Gray-coded pointers, registered in their own domain.
    logic [GPTR_W-1:0] wr_ptr_gray;
    logic [GPTR_W-1:0] rd_ptr_gray;

    // Synchronizer chains. SYNC_STAGES deep on each crossing.
    logic [GPTR_W-1:0] wr_ptr_gray_sync [1:SYNC_STAGES];
    logic [GPTR_W-1:0] rd_ptr_gray_sync [1:SYNC_STAGES];

    // Far-side pointers in the local domain (deepest sync stage output).
    wire [GPTR_W-1:0] wr_ptr_gray_at_rd = wr_ptr_gray_sync[SYNC_STAGES];
    wire [GPTR_W-1:0] rd_ptr_gray_at_wr = rd_ptr_gray_sync[SYNC_STAGES];

    // Status flops, owned by their local domain.
    logic              wr_full_q;
    logic              rd_empty_q;
    logic [CNT_W-1:0]  wr_count_q;
    logic [CNT_W-1:0]  rd_count_q;

    // Registered-read holding register (READ_LATENCY=1 only).
    logic [WIDTH-1:0]  rdata_q;

    // ------------------------------------------------------------------
    // Gray <-> binary helpers (combinational). Gray-to-binary is an
    // XOR-prefix reduction; binary-to-gray is b ^ (b >> 1).
    // ------------------------------------------------------------------
    function automatic logic [GPTR_W-1:0] bin_to_gray(input logic [GPTR_W-1:0] b);
        return b ^ (b >> 1);
    endfunction

    function automatic logic [GPTR_W-1:0] gray_to_bin(input logic [GPTR_W-1:0] g);
        logic [GPTR_W-1:0] b;
        b[GPTR_W-1] = g[GPTR_W-1];
        for (int i = GPTR_W - 2; i >= 0; i--) begin
            b[i] = b[i+1] ^ g[i];
        end
        return b;
    endfunction

    // Full detection: next gray write-pointer matches the synced
    // gray read-pointer with the TOP TWO bits inverted and the rest equal.
    function automatic logic would_be_full(
        input logic [GPTR_W-1:0] w_next,
        input logic [GPTR_W-1:0] r_sync
    );
        return (w_next[GPTR_W-1]   != r_sync[GPTR_W-1])   &&
               (w_next[GPTR_W-2]   != r_sync[GPTR_W-2])   &&
               (w_next[GPTR_W-3:0] == r_sync[GPTR_W-3:0]);
    endfunction

    // ------------------------------------------------------------------
    // Synchronizer chains. INV-S-HDL-3 excludes these from formal proof;
    // MTBF sign-off lives at rtl/sos_fifo_async/MTBF.md.
    // ------------------------------------------------------------------
    // wr_ptr_gray → rd_clk domain.
    always_ff @(posedge rd_clk) begin
        if (rd_rst) begin
            for (int i = 1; i <= SYNC_STAGES; i++) begin
                wr_ptr_gray_sync[i] <= '0;
            end
        end else begin
            wr_ptr_gray_sync[1] <= wr_ptr_gray;
            for (int i = 2; i <= SYNC_STAGES; i++) begin
                wr_ptr_gray_sync[i] <= wr_ptr_gray_sync[i-1];
            end
        end
    end

    // rd_ptr_gray → wr_clk domain.
    always_ff @(posedge wr_clk) begin
        if (wr_rst) begin
            for (int i = 1; i <= SYNC_STAGES; i++) begin
                rd_ptr_gray_sync[i] <= '0;
            end
        end else begin
            rd_ptr_gray_sync[1] <= rd_ptr_gray;
            for (int i = 2; i <= SYNC_STAGES; i++) begin
                rd_ptr_gray_sync[i] <= rd_ptr_gray_sync[i-1];
            end
        end
    end

    // ------------------------------------------------------------------
    // Handshake decode.
    // ------------------------------------------------------------------
    wire do_write = s_axis_tvalid & ~wr_full_q;
    wire do_read  = m_axis_tready & ~rd_empty_q;

    assign s_axis_tready = ~wr_full_q;

    // ------------------------------------------------------------------
    // Read path — selected by READ_LATENCY (mirrors sos_fifo_sync).
    //   READ_LATENCY = 0: FWFT — m_axis_tdata = mem[rd_ptr] combinationally.
    //   READ_LATENCY = 1: Registered — m_axis_tdata = rdata_q (latched on
    //                     handshake; popped value visible cycle AFTER).
    // ------------------------------------------------------------------
    generate
        if (READ_LATENCY == 0) begin : g_read_fwft
            assign m_axis_tvalid = ~rd_empty_q;
            assign m_axis_tdata  = rd_empty_q
                ? '0
                : mem[rd_ptr_bin[PTR_W-1:0]];
        end else begin : g_read_reg
            assign m_axis_tvalid = ~rd_empty_q;
            assign m_axis_tdata  = rdata_q;
        end
    endgenerate

    // ------------------------------------------------------------------
    // Write-side state — owned by wr_clk. Uses rd_ptr_gray_at_wr (the
    // synchronized far-side read pointer) for full detection.
    // ------------------------------------------------------------------
    always_ff @(posedge wr_clk) begin
        if (wr_rst) begin
            wr_ptr_bin  <= '0;
            wr_ptr_gray <= '0;
            wr_full_q   <= 1'b0;
            wr_count_q  <= '0;
            if (RESET_MEM) begin
                for (int i = 0; i < DEPTH; i++) begin
                    mem[i] <= '0;
                end
            end
        end else begin
            logic [GPTR_W-1:0] next_wr_bin;
            logic [GPTR_W-1:0] next_wr_gray;
            logic [GPTR_W-1:0] rd_bin_sync;
            logic [GPTR_W:0]   fill_w;

            next_wr_bin = wr_ptr_bin;
            if (do_write) begin
                mem[wr_ptr_bin[PTR_W-1:0]] <= s_axis_tdata;
                next_wr_bin = wr_ptr_bin + 1'b1;
            end
            next_wr_gray = bin_to_gray(next_wr_bin);

            wr_ptr_bin  <= next_wr_bin;
            wr_ptr_gray <= next_wr_gray;

            // Full when the would-be next write pointer collides (gray
            // top-two-bits-inverted + rest-equal) with the synced read
            // pointer.
            wr_full_q <= would_be_full(next_wr_gray, rd_ptr_gray_at_wr);

            // Conservative producer-side count.
            rd_bin_sync = gray_to_bin(rd_ptr_gray_at_wr);
            fill_w = {1'b0, next_wr_bin} - {1'b0, rd_bin_sync};
            wr_count_q <= fill_w[CNT_W-1:0];
        end
    end

    // ------------------------------------------------------------------
    // Read-side state — owned by rd_clk. Uses wr_ptr_gray_at_rd for
    // empty detection.
    // ------------------------------------------------------------------
    always_ff @(posedge rd_clk) begin
        if (rd_rst) begin
            rd_ptr_bin  <= '0;
            rd_ptr_gray <= '0;
            rd_empty_q  <= 1'b1;
            rd_count_q  <= '0;
            rdata_q     <= '0;
        end else begin
            logic [GPTR_W-1:0] next_rd_bin;
            logic [GPTR_W-1:0] next_rd_gray;
            logic [GPTR_W-1:0] wr_bin_sync;
            logic [GPTR_W:0]   fill_r;

            next_rd_bin = rd_ptr_bin;
            if (do_read) begin
                next_rd_bin = rd_ptr_bin + 1'b1;
                if (READ_LATENCY != 0) begin
                    rdata_q <= mem[rd_ptr_bin[PTR_W-1:0]];
                end
            end
            next_rd_gray = bin_to_gray(next_rd_bin);

            rd_ptr_bin  <= next_rd_bin;
            rd_ptr_gray <= next_rd_gray;

            // Empty when the would-be next read gray pointer equals the
            // synced write gray pointer in ALL bits.
            rd_empty_q <= (next_rd_gray == wr_ptr_gray_at_rd);

            // Conservative consumer-side count.
            wr_bin_sync = gray_to_bin(wr_ptr_gray_at_rd);
            fill_r = {1'b0, wr_bin_sync} - {1'b0, next_rd_bin};
            rd_count_q <= fill_r[CNT_W-1:0];
        end
    end

    // ------------------------------------------------------------------
    // Outputs.
    // ------------------------------------------------------------------
    assign wr_full  = wr_full_q;
    assign rd_empty = rd_empty_q;
    assign wr_count = wr_count_q;
    assign rd_count = rd_count_q;

endmodule

`default_nettype wire
