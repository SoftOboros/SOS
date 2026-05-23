// =============================================================================
// instantiate.sv  --  sos_event_group instantiation example (N_BITS=32)
//
// @spec        docs/concepts/SOS-08-B-CONCEPTS.md §6.2 ("Instantiation example"
//                via the per-service contract pattern + §15 ratification
//                entry where PCDN-SOS-08-B-002 ratifies N_BITS default 32)
// @parent      docs/concepts/SOS-08-CONCEPTS.md §6 (L1 set), §7 (INV-S-HDL-1..5)
// @grandparent docs/concepts/SOS-07-CONCEPTS.md §6 (INV-SOS-A..H)
// @l0          docs/concepts/SOS-08-A-CONCEPTS.md §6.10 (sos_strobe_latch)
//                + §15 wave-2 (PCDN-A-strobe-pending-shadow).
//
// Cited invariants: INV-SOS-A..H, INV-S-HDL-1..5, INV-S-HDL-A-1..5,
//                   INV-S-HDL-B-1..5.
//
// Per PCDN-SOS-08-B-002 (§15 2026-05-23): N_BITS=32 is the recommended /
// ratified default (matches the chart datamodel i32 word width).  This
// example exercises the default directly; charts wanting a smaller event
// group instantiate sos_event_group with #(.N_BITS(K)).
//
// Hybrid handshake (per §6.2 + PCDN-A-strobe-pending-shadow):
//   chart-side event.set    -> set_req (1-cycle pulse) + set_mask
//   chart-side event.wait   -> wait_mask + wait_mode + wait_match (level)
//   chart-side event.peek   -> bits[] (combinational level output)
//   chart-side event.clear  -> clear_req (1-cycle pulse) + clear_mask
// =============================================================================

`default_nettype none

module sos_event_group_example (
    input  wire        clk,
    input  wire        rst,
    input  wire        set_req,
    input  wire [31:0] set_mask,
    input  wire        clear_req,
    input  wire [31:0] clear_mask,
    input  wire [31:0] wait_mask,
    input  wire        wait_mode,
    output wire        wait_match,
    output wire [31:0] bits
);

    sos_event_group #(
        .N_BITS (32)
    ) u_event_group (
        .clk        (clk),
        .rst        (rst),
        .set_req    (set_req),
        .set_mask   (set_mask),
        .clear_req  (clear_req),
        .clear_mask (clear_mask),
        .wait_mask  (wait_mask),
        .wait_mode  (wait_mode),
        .wait_match (wait_match),
        .bits       (bits)
    );

endmodule

`default_nettype wire
