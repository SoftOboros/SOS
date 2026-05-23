//------------------------------------------------------------------------------
// sos_strobe_latch_bind.sv - SVA bind directive for sos_strobe_latch
//
// @spec        docs/concepts/SOS-08-A-CONCEPTS.md §6.10 + §4 source-of-truth map
// @parent      docs/concepts/SOS-08-CONCEPTS.md §6 (L0 set), §7 (INV-S-HDL-1..5)
// @grandparent docs/concepts/SOS-07-CONCEPTS.md §6 (INV-SOS-A..H)
//
// Invariants cited (not re-derived):
//   INV-SOS-A..H, INV-S-HDL-1..5, INV-S-HDL-A-1..5.
//
// Per PCDN-A-bind-form resolved 2026-05-23 (§15): module-type bind. Attaches
// sos_strobe_latch_sva (rtl/sos_strobe_latch/sos_strobe_latch_sva.sv) to
// every elaboration instance of sos_strobe_latch without modifying the
// primitive's source. Per SOS-08-A §4 (source-of-truth map), the bind file
// is the per-primitive assertion attachment point and lives under
// tb/<primitive>/<primitive>_bind.sv (the SVA module lives under
// rtl/<primitive>/<primitive>_sva.sv).
//
// The bind is parameter-free because the primitive itself is parameter-free
// (INV-S-HDL-A-5 vacuously satisfied — see sos_strobe_latch.sv header).
//
// Usage:
//   * Compile this file alongside the testbench. The `bind` keyword applies
//     globally to every sos_strobe_latch instance in the elaboration.
//------------------------------------------------------------------------------

`default_nettype none

bind sos_strobe_latch sos_strobe_latch_sva u_sos_strobe_latch_sva (
    .clk             (clk),
    .rst             (rst),
    .strobe          (strobe),
    .ack             (ack),
    .latched         (latched),
    .latched_state_q (latched_state_q)
);

`default_nettype wire
