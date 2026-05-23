// =============================================================================
// sos_periodic_task_bind.sv  --  SVA bind directive for sos_periodic_task.
//
// @spec docs/concepts/SOS-08-B-CONCEPTS.md §5.4 (service-level SVA binding
//   default) + §6.4 (per-service SVA bind file location, mirroring
//   `rtl/services/sos_periodic_task_sva.sv` in the doc's vector emission
//   contract -- the on-disk reality of this repo is `rtl/sos_periodic_task/`
//   for the SVA module and `tb/sos_periodic_task/` for the bind file,
//   mirroring the SOS-08-A primitive layout for consistency).
//
//   Per PCDN-A-bind-form resolved 2026-05-23 (carried forward from SOS-08-A
//   §15 third entry; SOS-08-B inherits the same convention): module-type
//   bind, not per-instance, so the assertion module attaches to every
//   instance of `sos_periodic_task` in the elaborated design.  Verilator-
//   compatible.
//
// Cited invariants:
//   INV-SOS-A, INV-SOS-B, INV-SOS-E, INV-SOS-H            (SOS-07 §6)
//   INV-S-HDL-1, INV-S-HDL-4, INV-S-HDL-5                 (SOS-08 §7)
//   INV-S-HDL-B-3 (service-level SVA on every L1 instance) (SOS-08-B §7)
//
// The bind directive forwards both generics (DIVISOR + INITIAL_COUNTER) so
// the assertion module's width and spacing computations agree with the
// DUT's parameter overrides.
// =============================================================================

`default_nettype none

bind sos_periodic_task sos_periodic_task_sva #(
    .DIVISOR         (DIVISOR),
    .INITIAL_COUNTER (INITIAL_COUNTER)
) u_sva (
    .clk             (clk),
    .rst             (rst),
    .base_tick       (base_tick),
    .task_enable     (task_enable),
    .task_busy       (task_busy),
    .overrun_fault   (overrun_fault),
    .divider_counter (divider_counter)
);

`default_nettype wire
