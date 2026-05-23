//------------------------------------------------------------------------------
// sos_credit_counter_bind.sv - SVA bind directive for sos_credit_counter
//
// @spec        docs/concepts/SOS-08-A-CONCEPTS.md §6.6
// @amendments  docs/concepts/SOS-08-A-CONCEPTS.md §15 (2026-05-23 entries):
//              - PCDN-A-bind-form: module-type bind across all SOS-08-A
//                primitives. SOS-08-D's emitter MUST emit this form.
// @parent      docs/concepts/SOS-08-CONCEPTS.md §6, §7 (INV-S-HDL-1..5)
// @grandparent docs/concepts/SOS-07-CONCEPTS.md §6 (INV-SOS-A..H)
//
// Invariants cited (not re-derived):
//   INV-SOS-A..H, INV-S-HDL-1..5, INV-S-HDL-A-1..5.
//
// Module-type bind: attaches sos_credit_counter_sva to every elaboration
// instance of sos_credit_counter across the design without modifying the
// primitive's source. Per SOS-08-A §4 (source-of-truth map) the bind file is
// the per-primitive assertion attachment point; per §15 PCDN-A-bind-form
// (2026-05-23) the directive form is module-type (Verilator-compatible).
//
// Usage:
//   * Compile alongside the testbench. The `bind` keyword applies globally
//     to every sos_credit_counter instance in the elaboration.
//   * Parameters (INIT_CREDITS, MAX_CREDITS) flow through unchanged.
//------------------------------------------------------------------------------

`default_nettype none

bind sos_credit_counter sos_credit_counter_sva #(
    .INIT_CREDITS (INIT_CREDITS),
    .MAX_CREDITS  (MAX_CREDITS)
) u_sos_credit_counter_sva (
    .clk         (clk),
    .rst         (rst),
    .acquire_req (acquire_req),
    .acquire_ack (acquire_ack),
    .release_req (release_req),
    .credits     (credits)
);

`default_nettype wire
