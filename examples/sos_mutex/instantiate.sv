//------------------------------------------------------------------------------
// instantiate.sv - sos_mutex instantiation example (N_CLIENTS = 4)
//
// @spec        docs/concepts/SOS-08-A-CONCEPTS.md §6.5 ("Instantiation example")
// @parent      docs/concepts/SOS-08-CONCEPTS.md §6
// @grandparent docs/concepts/SOS-07-CONCEPTS.md §6 (INV-SOS-A..H)
//
// Invariants cited: INV-SOS-A..H, INV-S-HDL-1..5, INV-S-HDL-A-1..5.
//
// Minimal chart-emitted top-level showing how a 4-client mutex is wired:
// four request bits in, four grant bits out, plus the lock-status outputs.
//------------------------------------------------------------------------------

`default_nettype none

module sos_mutex_example (
    input  wire       clk,
    input  wire       rst,
    input  wire [3:0] req,
    output wire [3:0] ack,
    output wire       locked,
    output wire [2:0] holder_id   // $clog2(4+1) = 3
);

    sos_mutex #(
        .N_CLIENTS (4)
    ) u_mutex (
        .clk       (clk),
        .rst       (rst),
        .req       (req),
        .ack       (ack),
        .locked    (locked),
        .holder_id (holder_id)
    );

endmodule

`default_nettype wire
