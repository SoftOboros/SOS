//------------------------------------------------------------------------------
// sos_resource_pool_bind.sv - SVA bind directive for sos_resource_pool
//
// @spec        docs/concepts/SOS-08-B-CONCEPTS.md §6.3 (service-level SVA)
//              docs/concepts/SOS-08-B-CONCEPTS.md §7 (INV-S-HDL-B-3 — service-
//                                                     level SVA on every L1
//                                                     instance)
//              docs/concepts/SOS-08-B-CONCEPTS.md §15 (2026-05-23 ratification:
//                                                       PCDN-SOS-08-B-003 →
//                                                       ID_WIDTH default 16)
//              docs/concepts/SOS-08-A-CONCEPTS.md §15 (PCDN-A-bind-form ratified
//                                                      2026-05-23 — module-type
//                                                      bind across all SOS-08-A
//                                                      primitives; extended by
//                                                      INV-S-HDL-B-3 to L1
//                                                      services)
// @parent      docs/concepts/SOS-08-CONCEPTS.md §6, §7 (INV-S-HDL-1..5)
// @grandparent docs/concepts/SOS-07-CONCEPTS.md §6 (INV-SOS-A..H)
//
// Invariants cited:
//   INV-SOS-A..H, INV-S-HDL-1..5, INV-S-HDL-B-1..5.
//
// Module-type bind: attaches sos_resource_pool_sva to every elaboration
// instance of sos_resource_pool across the design without modifying the
// service module's source. Per SOS-08-B INV-S-HDL-B-3 the bind file is the
// per-service assertion attachment point; per SOS-08-A §15 PCDN-A-bind-form
// the directive form is module-type (Verilator-compatible).
//------------------------------------------------------------------------------

`default_nettype none

bind sos_resource_pool sos_resource_pool_sva #(
    .POOL_SIZE  (POOL_SIZE),
    .ID_WIDTH   (ID_WIDTH),
    .META_WIDTH (META_WIDTH)
) u_sos_resource_pool_sva (
    .clk        (clk),
    .rst        (rst),

    .alloc_req  (alloc_req),
    .alloc_ack  (alloc_ack),
    .alloc_id   (alloc_id),

    .free_req   (free_req),
    .free_id    (free_id),

    .read_id    (read_id),
    .read_meta  (read_meta),

    .write_req  (write_req),
    .write_id   (write_id),
    .write_meta (write_meta),

    .free_count (free_count)
);

`default_nettype wire
