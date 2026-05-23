// ----------------------------------------------------------------------------
// sos_fifo_sync.sv
//
// @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.2 (sos_fifo_sync contract)
//       docs/concepts/SOS-08-CONCEPTS.md   §5  (frozen decisions inherited)
//       docs/concepts/SOS-07-CONCEPTS.md   §6  (cross-phase invariants)
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
//   INV-S-HDL-3  cross-domain isolation (N/A — single domain)
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
// Single-clock-domain FIFO. Portable SystemVerilog-2017 RTL. Byte-equivalent
// semantics to the VHDL sibling in sos_fifo_sync.vhd.
// ----------------------------------------------------------------------------

`default_nettype none

module sos_fifo_sync #(
    // INV-S-HDL-A-5: mandatory parameters, no defaults.
    parameter int DEPTH,
    parameter int WIDTH,
    // Derived widths — not user-facing; recomputed from DEPTH.
    parameter int PTR_W = (DEPTH <= 1) ? 1 : $clog2(DEPTH),
    parameter int CNT_W = $clog2(DEPTH + 1)
) (
    // Clock + sync active-high reset (INV-S-HDL-A-1 / PCDN-A-003).
    input  wire                  clk,
    input  wire                  rst,

    // Slave AXI-Stream ingress (producer drives, FIFO accepts).
    input  wire [WIDTH-1:0]      s_axis_tdata,
    input  wire                  s_axis_tvalid,
    output wire                  s_axis_tready,

    // Master AXI-Stream egress (FIFO presents, consumer accepts).
    output wire [WIDTH-1:0]      m_axis_tdata,
    output wire                  m_axis_tvalid,
    input  wire                  m_axis_tready,

    // Observability outputs (bare names — not handshake-faced).
    output wire                  full,
    output wire                  empty,
    output wire [CNT_W-1:0]      count
);

    // Storage. Register-file shape; synthesis infers LUT-RAM for small DEPTH
    // and BRAM for large DEPTH on most targets.
    logic [WIDTH-1:0] mem [0:DEPTH-1];

    logic [PTR_W-1:0] wr_ptr;
    logic [PTR_W-1:0] rd_ptr;
    logic [CNT_W-1:0] fill;

    logic full_q;
    logic empty_q;

    // Combinational handshake decode.
    wire do_write = s_axis_tvalid & ~full_q;
    wire do_read  = m_axis_tready & ~empty_q;

    assign s_axis_tready = ~full_q;
    assign m_axis_tvalid = ~empty_q;

    // FWFT-style: present mem[rd_ptr] combinationally so the consumer can
    // latch the data on the same cycle it asserts tready.
    assign m_axis_tdata  = empty_q ? '0 : mem[rd_ptr];

    // Pointer + fill update.
    always_ff @(posedge clk) begin
        if (rst) begin
            wr_ptr  <= '0;
            rd_ptr  <= '0;
            fill    <= '0;
            full_q  <= 1'b0;
            empty_q <= 1'b1;
            // mem contents intentionally not reset (saves area; INV-S-HDL-A-1
            // mandates reset for the state machine + observability, not the
            // storage array).
        end else begin
            logic [CNT_W-1:0] next_fill;
            next_fill = fill;

            if (do_write) begin
                mem[wr_ptr] <= s_axis_tdata;
                if (wr_ptr == PTR_W'(DEPTH - 1))
                    wr_ptr <= '0;
                else
                    wr_ptr <= wr_ptr + 1'b1;
                next_fill = next_fill + 1'b1;
            end

            if (do_read) begin
                if (rd_ptr == PTR_W'(DEPTH - 1))
                    rd_ptr <= '0;
                else
                    rd_ptr <= rd_ptr + 1'b1;
                next_fill = next_fill - 1'b1;
            end

            fill    <= next_fill;
            full_q  <= (next_fill == CNT_W'(DEPTH));
            empty_q <= (next_fill == '0);
        end
    end

    assign full  = full_q;
    assign empty = empty_q;
    assign count = fill;

endmodule

`default_nettype wire
