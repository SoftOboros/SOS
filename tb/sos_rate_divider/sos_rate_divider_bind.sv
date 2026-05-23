// =============================================================================
// sos_rate_divider_bind.sv  --  SVA bind directive for sos_rate_divider.
//
// @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.11 + §4 source-of-truth map
//   ("Per-primitive SVA bind file"); bind directives live under
//   `tb/<primitive>/<primitive>_bind.sv` (the assertion module sits at
//   `rtl/<primitive>/<primitive>_sva.sv`).
//
//   Per PCDN-A-bind-form resolved 2026-05-23 (§15 third entry): module-type
//   bind, not per-instance, so the assertion module attaches to every
//   instance of `sos_rate_divider` in the elaborated design.  Verilator-
//   compatible.
//
// Cited invariants:
//   INV-SOS-A, INV-SOS-B, INV-SOS-E, INV-SOS-H            (SOS-07 §6)
//   INV-S-HDL-1, INV-S-HDL-4, INV-S-HDL-5                 (SOS-08 §7)
//   INV-S-HDL-A-1, INV-S-HDL-A-5                          (SOS-08-A §7)
//
// The bind directive forwards both generics (DIVISOR + INITIAL_COUNTER) so
// the assertion module's static-width and spacing computations agree with
// the DUT's parameter overrides (INV-S-HDL-A-3 byte-identical-wrapper
// principle).
// =============================================================================

`default_nettype none

bind sos_rate_divider sos_rate_divider_sva #(
    .DIVISOR         (DIVISOR),
    .INITIAL_COUNTER (INITIAL_COUNTER)
) u_sva (
    .clk      (clk),
    .rst      (rst),
    .tick_in  (tick_in),
    .tick_out (tick_out),
    .counter  (counter)
);

`default_nettype wire
