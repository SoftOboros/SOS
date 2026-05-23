//------------------------------------------------------------------------------
// instantiate.sv - sos_strobe_latch instantiation example (parameterless)
//
// @spec        docs/concepts/SOS-08-A-CONCEPTS.md §6.10 ("Instantiation example")
// @parent      docs/concepts/SOS-08-CONCEPTS.md §6
// @grandparent docs/concepts/SOS-07-CONCEPTS.md §6 (INV-SOS-A..H)
//
// Invariants cited: INV-SOS-A..H, INV-S-HDL-1..5, INV-S-HDL-A-1..5.
//
// Single-instance instantiation. sos_strobe_latch has NO user-facing
// parameters — see the primitive's header for the INV-S-HDL-A-5
// vacuously-satisfied rationale. The example documents the
// lack-of-parameterization explicitly: there is no #(...) parameter
// override clause because the primitive accepts none.
//
// If a future deployment wires a `RESET_VALUE` generic (default IDLE) to
// allow latched-on-reset behaviour, this example becomes the natural
// migration test bed — but adding such a generic is a §15 amendment to
// SOS-08-A §6.10 (Standards Action).
//
// Hybrid handshake (per §15 2026-05-23 amendments):
//   producer drives `strobe` as a 1-cycle pulse;
//   consumer observes `latched` as a level-held signal;
//   consumer drives `ack` as a 1-cycle pulse to clear.
//------------------------------------------------------------------------------

`default_nettype none

module sos_strobe_latch_example (
    input  wire clk,
    input  wire rst,
    input  wire strobe,
    input  wire ack,
    output wire latched,
    output wire latched_state_q
);

    // No parameter override clause — the primitive has no user-facing
    // parameters (INV-S-HDL-A-5 vacuously satisfied).
    sos_strobe_latch u_strobe_latch (
        .clk             (clk),
        .rst             (rst),
        .strobe          (strobe),
        .ack             (ack),
        .latched         (latched),
        .latched_state_q (latched_state_q)
    );

endmodule

`default_nettype wire
