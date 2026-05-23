// =============================================================================
// sos_arbiter_priority_bind.sv  --  SVA bind directive for sos_arbiter_priority.
//
// @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.4 + §4 source-of-truth map
//   ("Per-primitive SVA bind file"); bind directives live under
//   `tb/<primitive>/<primitive>_bind.sv` (the assertion module sits at
//   `rtl/<primitive>/<primitive>_sva.sv`).
//
//   Module-type bind form per PCDN-A-bind-form ratified 2026-05-23
//   (second §15 entry): `bind <module> <sva-module> u_sva (.*);`-style,
//   attaching the assertion module to every instance of the primitive
//   across the design.  Verilator-compatible.
//
// Cited invariants:
//   INV-SOS-A, INV-SOS-B, INV-SOS-E, INV-SOS-H            (SOS-07 §6)
//   INV-S-HDL-1, INV-S-HDL-4, INV-S-HDL-5                 (SOS-08 §7)
//   INV-S-HDL-A-1, INV-S-HDL-A-4, INV-S-HDL-A-5           (SOS-08-A §7)
//
// The bind directive attaches `sos_arbiter_priority_sva` as a child of
// every instance of `sos_arbiter_priority` in the elaborated design, with
// the parent instance's internal `pointer` signal hooked into the
// assertion module's observability port.  No modification to the
// primitive's RTL is required (INV-S-HDL-A-3 byte-identical-wrapper
// principle).
// =============================================================================

`default_nettype none

bind sos_arbiter_priority sos_arbiter_priority_sva #(
    .N_REQS               (N_REQS),
    .PRIORITY_BITS        (PRIORITY_BITS),
    .AGING_ENABLE         (AGING_ENABLE),
    .AGING_THRESHOLD      (AGING_THRESHOLD),
    // Forward the latency parameter so the assertion module widens the
    // `eventually_granted` bound to match (PCDN-A-arbiter-GRANT_LATENCY_CYCLES
    // resolved 2026-05-23, extended to this primitive).
    .GRANT_LATENCY_CYCLES (GRANT_LATENCY_CYCLES)
) u_sva (
    .clk             (clk),
    .rst             (rst),
    .req             (req),
    .priority_in     (priority_in),
    .grant           (grant),
    .last_winner_id  (last_winner_id),
    .pointer         (pointer)
);

`default_nettype wire
