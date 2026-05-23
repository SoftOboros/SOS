//------------------------------------------------------------------------------
// sos_mutex_bind.sv - SVA bind directive for sos_mutex
//
// @spec       docs/concepts/SOS-08-A-CONCEPTS.md §6.5
// @parent     docs/concepts/SOS-08-CONCEPTS.md §6, §7 (INV-S-HDL-1..5)
// @grandparent docs/concepts/SOS-07-CONCEPTS.md §6 (INV-SOS-A..H)
//
// Invariants cited (not re-derived):
//   INV-SOS-A..H, INV-S-HDL-1..5, INV-S-HDL-A-1..5.
//
// Attaches sos_mutex_sva (rtl/sos_mutex/sos_mutex_sva.sv) to every elaboration
// instance of sos_mutex without modifying the primitive's source. Per
// SOS-08-A §4 (source-of-truth map), the bind file is the per-primitive
// assertion attachment point.
//
// Usage:
//   * Compile this file alongside the testbench. The `bind` keyword applies
//     globally to every sos_mutex instance in the elaboration.
//   * Parameters (N_CLIENTS) flow through unchanged.
//------------------------------------------------------------------------------

`default_nettype none

bind sos_mutex sos_mutex_sva #(
    .N_CLIENTS (N_CLIENTS)
) u_sos_mutex_sva (
    .clk       (clk),
    .rst       (rst),
    .req       (req),
    .ack       (ack),
    .locked    (locked),
    .holder_id (holder_id)
);

`default_nettype wire
