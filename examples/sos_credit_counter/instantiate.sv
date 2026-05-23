//------------------------------------------------------------------------------
// instantiate.sv - sos_credit_counter instantiation example
//                  (INIT_CREDITS=4, MAX_CREDITS=8)
//
// @spec        docs/concepts/SOS-08-A-CONCEPTS.md §6.6 ("Instantiation example")
// @parent      docs/concepts/SOS-08-CONCEPTS.md §6
// @grandparent docs/concepts/SOS-07-CONCEPTS.md §6 (INV-SOS-A..H)
//
// Invariants cited: INV-SOS-A..H, INV-S-HDL-1..5, INV-S-HDL-A-1..5.
//
// Minimal chart-emitted top-level showing how a credit pool initialised to 4
// with a ceiling of 8 is wired: one acquire-pulse in, one ack-pulse out, one
// release-pulse in, and a `credits` observability port (width
// $clog2(8+1) = 4).
//------------------------------------------------------------------------------

`default_nettype none

module sos_credit_counter_example (
    input  wire       clk,
    input  wire       rst,
    input  wire       acquire_req,
    output wire       acquire_ack,
    input  wire       release_req,
    output wire [3:0] credits      // $clog2(8+1) = 4
);

    sos_credit_counter #(
        .INIT_CREDITS (4),
        .MAX_CREDITS  (8)
    ) u_credit (
        .clk         (clk),
        .rst         (rst),
        .acquire_req (acquire_req),
        .acquire_ack (acquire_ack),
        .release_req (release_req),
        .credits     (credits)
    );

endmodule

`default_nettype wire
