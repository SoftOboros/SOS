// =============================================================================
// sos_mailbox_bind.sv  --  Service-level SVA bind directive for sos_mailbox.
//
// @spec docs/concepts/SOS-08-B-CONCEPTS.md §6.1 (SVA bind file)
//       docs/concepts/SOS-08-B-CONCEPTS.md §5.4 (service-level SVA binding
//                                                default: full bind on every
//                                                instance)
//       docs/concepts/SOS-08-B-CONCEPTS.md §7   (INV-S-HDL-B-3)
//       docs/concepts/SOS-08-A-CONCEPTS.md §15  (PCDN-A-bind-form ratified
//                                                2026-05-23: module-type
//                                                bind, Verilator-compatible)
//
// Cited invariants:
//   INV-SOS-A, INV-SOS-B, INV-SOS-E, INV-SOS-H            (SOS-07 §6)
//   INV-S-HDL-1, INV-S-HDL-4, INV-S-HDL-5                 (SOS-08 §7)
//   INV-S-HDL-A-1, INV-S-HDL-A-4, INV-S-HDL-A-5           (SOS-08-A §7)
//   INV-S-HDL-B-1, INV-S-HDL-B-2, INV-S-HDL-B-3,          (SOS-08-B §7)
//   INV-S-HDL-B-5
//
// Module-type bind per PCDN-A-bind-form (2026-05-23 §15 SOS-08-A entry):
// `bind <module> <sva-module> u_sva (.*);`-style attaches the assertion
// module to every elaborated instance of sos_mailbox across the design.
//
// Internal observability: the SVA module needs the per-lane ~empty bus
// and the arbiter grant bus, which are internal nets inside the parent
// sos_mailbox module body.  The bind directive places the SVA as a child
// of every sos_mailbox instance, so the dotted references resolve to the
// parent's signals (same pattern as sos_arbiter_priority_bind.sv routing
// the parent's `pointer` signal into the L0 SVA module).
//
// L0 SVA chains: sos_fifo_sync_sva is bound to every sos_fifo_sync
// instance and sos_arbiter_priority_sva is bound to every
// sos_arbiter_priority instance via their own bind files
// (tb/sos_fifo_sync/sos_fifo_sync_bind.sv +
//  tb/sos_arbiter_priority/sos_arbiter_priority_bind.sv).  Composing the
// L1 from those L0 modules means the L0 SVA chain attaches automatically
// to the lanes -- ordering, no-overflow, no-underflow, priority
// correctness, and arbiter fairness are all verified at the L0 layer
// without re-derivation here (INV-S-HDL-B-2).
// =============================================================================

`default_nettype none

bind sos_mailbox sos_mailbox_sva #(
    .NUM_PRIO   (NUM_PRIO),
    .DEPTH      (DEPTH),
    .WIDTH      (WIDTH),
    .PRIO_W_EFF (PRIO_W_EFF)
) u_sva (
    .clk            (clk),
    .rst            (rst),

    .s_axis_tdata   (s_axis_tdata),
    .s_axis_tprio   (s_axis_tprio),
    .s_axis_tvalid  (s_axis_tvalid),
    .s_axis_tready  (s_axis_tready),

    .m_axis_tdata   (m_axis_tdata),
    .m_axis_tprio   (m_axis_tprio),
    .m_axis_tvalid  (m_axis_tvalid),
    .m_axis_tready  (m_axis_tready),

    .irq_non_empty  (irq_non_empty),

    // Internal observability nets surfaced from the parent module body.
    .lane_empty     (lane_empty),
    .arb_grant      (arb_grant)
);

`default_nettype wire
