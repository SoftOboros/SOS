// =============================================================================
// sos_synchronizer_bind.sv  --  SVA bind directive for sos_synchronizer.
//
// @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.9 + §4 source-of-truth map
//   ("Per-primitive SVA bind file"); bind directives live under
//   `tb/<primitive>/<primitive>_bind.sv` (the assertion module sits at
//   `rtl/<primitive>/<primitive>_sva.sv`).  PCDN-A-bind-form resolved
//   2026-05-23: **module-type bind** form across all SOS-08-A primitives
//   (Verilator-compatible; SOS-08-D's emitter MUST emit this form).
//
// Cited invariants:
//   INV-SOS-A, INV-SOS-B, INV-SOS-E, INV-SOS-H            (SOS-07 §6)
//   INV-S-HDL-1, INV-S-HDL-3, INV-S-HDL-4, INV-S-HDL-5   (SOS-08 §7)
//   INV-S-HDL-A-1, INV-S-HDL-A-3, INV-S-HDL-A-5          (SOS-08-A §7)
//
// The bind directive attaches `sos_synchronizer_sva` as a child of every
// instance of `sos_synchronizer` in the elaborated design, with the
// parent instance's internal `sync_chain[STAGES-1]` signal hooked into
// the assertion module's `sync_chain_last` port.  No modification to
// the primitive's RTL is required (INV-S-HDL-A-3 byte-identical-wrapper
// principle).
//
// Note on INV-S-HDL-3: this primitive IS the cross-domain isolation
// primitive.  The bind module's assertions are functional / structural
// only — none of them claim anything about metastability resolution.
// The MTBF claim lives at `rtl/sos_synchronizer/MTBF.md` per PCDN-A-006.
// =============================================================================

`default_nettype none

bind sos_synchronizer sos_synchronizer_sva #(
    .STAGES (STAGES),
    .WIDTH  (WIDTH)
) u_sva (
    .clk_dst         (clk_dst),
    .rst_dst         (rst_dst),
    .d_src           (d_src),
    .d_dst           (d_dst),
    // Last stage of the synchronizer chain.  In the SV module the array
    // is declared `reg [WIDTH-1:0] sync_chain [0:STAGES-1]`, so the last
    // stage is `sync_chain[STAGES-1]`.  The VHDL companion uses a 1-based
    // array `sync_chain(STAGES)`; cross-language bind sites use the SV
    // index form (the SV bind directive only attaches to SV elaboration
    // paths anyway).
    .sync_chain_last (sync_chain[STAGES-1])
);

`default_nettype wire
