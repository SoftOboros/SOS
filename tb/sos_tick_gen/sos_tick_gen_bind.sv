// =============================================================================
// sos_tick_gen_bind.sv  --  SVA bind directive for sos_tick_gen.
//
// @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.8 + §4 source-of-truth map
//   ("Per-primitive SVA bind file"); bind directives live under
//   `tb/<primitive>/<primitive>_bind.sv` (the assertion module sits at
//   `rtl/<primitive>/<primitive>_sva.sv`).
//
//   Bind form: module-type bind (PCDN-A-bind-form resolved 2026-05-23 — the
//   directive attaches `sos_tick_gen_sva` as a child of EVERY instance of
//   `sos_tick_gen` in the elaborated design, not per-instance.  Verilator
//   has uneven per-instance bind support; module-type is the frozen form
//   across the L0 set.).
//
// Cited invariants:
//   INV-SOS-A, INV-SOS-B, INV-SOS-E, INV-SOS-H            (SOS-07 §6)
//   INV-S-HDL-1, INV-S-HDL-4, INV-S-HDL-5                 (SOS-08 §7)
//   INV-S-HDL-A-1, INV-S-HDL-A-4, INV-S-HDL-A-5           (SOS-08-A §7)
//
// No modification to the primitive's RTL is required (INV-S-HDL-A-3
// byte-identical-wrapper principle).
// =============================================================================

`default_nettype none

bind sos_tick_gen sos_tick_gen_sva #(
    .PERIOD_CYCLES (PERIOD_CYCLES),
    .INITIAL_PHASE (INITIAL_PHASE)
) u_sva (
    .clk     (clk),
    .rst     (rst),
    .enable  (enable),
    .tick    (tick),
    .counter (counter)
);

`default_nettype wire
