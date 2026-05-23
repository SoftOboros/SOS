// =============================================================================
// sos_event_group_bind.sv  --  Service-level SVA bind directive for
//                              sos_event_group
//
// @spec        docs/concepts/SOS-08-B-CONCEPTS.md §6.2 ("SVA bind file"
//                + §5.4 service-level SVA binding default + §7 INV-S-HDL-B-3)
// @parent      docs/concepts/SOS-08-CONCEPTS.md §6 (L1 set), §7 (INV-S-HDL-1..5)
// @grandparent docs/concepts/SOS-07-CONCEPTS.md §6 (INV-SOS-A..H)
// @l0          docs/concepts/SOS-08-A-CONCEPTS.md §6.10 (sos_strobe_latch)
//                + §15 wave-1 PCDN-A-bind-form (module-type bind).
//
// Cited invariants:
//   INV-SOS-A..H, INV-S-HDL-1..5, INV-S-HDL-A-1..5, INV-S-HDL-B-1..5.
//
// Per PCDN-A-bind-form resolved 2026-05-23 (§15 wave-1 entry of SOS-08-A):
// module-type bind.  This attaches sos_event_group_sva to every elaboration
// instance of sos_event_group across the design.  Per §5.4 + PCDN-SOS-08-007
// resolution (full-bind default), service-level SVA binds attach to every
// instance; module-type bind is the wave-1-ratified Verilator-compatible
// mechanism for that.
//
// The bind carries N_BITS through so the assertion module elaborates against
// the same generic the DUT was instantiated with.  Per the SOS-08-A wave-1
// SVA-bind discipline, this file lives under tb/<service>/<service>_bind.sv
// and is compiled alongside the cocotb testbench; the assertion module lives
// under rtl/<service>/<service>_sva.sv.
// =============================================================================

`default_nettype none

bind sos_event_group sos_event_group_sva #(
    .N_BITS (N_BITS)
) u_sos_event_group_sva (
    .clk        (clk),
    .rst        (rst),
    .set_req    (set_req),
    .set_mask   (set_mask),
    .clear_req  (clear_req),
    .clear_mask (clear_mask),
    .wait_mask  (wait_mask),
    .wait_mode  (wait_mode),
    .wait_match (wait_match),
    .bits       (bits)
);

`default_nettype wire
