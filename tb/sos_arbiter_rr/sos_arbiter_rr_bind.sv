// =============================================================================
// sos_arbiter_rr_bind.sv  --  SVA bind directive for sos_arbiter_rr.
//
// @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.3 + §4 source-of-truth map
//   ("Per-primitive SVA bind file"); bind directives live under
//   `tb/<primitive>/<primitive>_bind.sv` (the assertion module sits at
//   `rtl/<primitive>/<primitive>_sva.sv`).
//
// Cited invariants:
//   INV-SOS-A, INV-SOS-B, INV-SOS-E, INV-SOS-H            (SOS-07 §6)
//   INV-S-HDL-1, INV-S-HDL-4, INV-S-HDL-5                 (SOS-08 §7)
//   INV-S-HDL-A-1, INV-S-HDL-A-4, INV-S-HDL-A-5           (SOS-08-A §7)
//
// The bind directive attaches `sos_arbiter_rr_sva` as a child of every
// instance of `sos_arbiter_rr` in the elaborated design, with the parent
// instance's internal `pointer` signal hooked into the assertion module's
// observability port.  No modification to the primitive's RTL is required
// (INV-S-HDL-A-3 byte-identical-wrapper principle).
// =============================================================================

`default_nettype none

bind sos_arbiter_rr sos_arbiter_rr_sva #(
    .N_REQS (N_REQS)
) u_sva (
    .clk             (clk),
    .rst             (rst),
    .req             (req),
    .grant           (grant),
    .last_winner_id  (last_winner_id),
    .pointer         (pointer)
);

`default_nettype wire
