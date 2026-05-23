// =============================================================================
// examples/sos_synchronizer/instantiate.sv
//
// Minimal SystemVerilog-2017 instantiation example for `sos_synchronizer`,
// THE canonical CDC primitive in the SOS-08-A L0 catalogue.  Two instances:
//   * u_sync_1bit  -- WIDTH = 1, STAGES = 2 (canonical 2-FF synchronizer)
//   * u_sync_data  -- WIDTH = 32, STAGES = 3 (multi-bit Gray-coded bus,
//                                              extra stage for higher MTBF)
//
// @spec docs/concepts/SOS-08-A-CONCEPTS.md §4 source-of-truth map
//   (`examples/<primitive>/instantiate.{vhd,sv}`), §6.9 contract,
//   §12 (g) instantiation-example gate.
//
// Cited invariants:
//   INV-SOS-A, INV-SOS-E                              (SOS-07 §6)
//   INV-S-HDL-1, INV-S-HDL-3, INV-S-HDL-5             (SOS-08 §7)
//   INV-S-HDL-A-1, INV-S-HDL-A-3, INV-S-HDL-A-5       (SOS-08-A §7)
//
// The instantiation is illustrative only; it shows the parameter override
// (STAGES and WIDTH both mandatory per INV-S-HDL-A-5, no default), the
// canonical port set, and the synchronous active-high `rst_dst` wiring
// (INV-S-HDL-A-1).
//
// Note: the `d_src` input on each instance is, by construction, from a
// clock domain different to `clk_dst`.  In this example wrapper both
// instances share the same `clk_dst` (the destination domain); the
// source-domain timing is implicit (no `clk_src` port on the primitive —
// see §6.9 + the primitive's header docstring).
// =============================================================================

`default_nettype none

module sos_synchronizer_example (
    input  wire         clk_dst,
    input  wire         rst_dst,

    // Single-bit cross (e.g. async strobe, reset deassert edge, etc.).
    // Caller responsibility: drive `flag_src` from any source-domain
    // timeline; the synchronizer brings it into `clk_dst` domain.
    input  wire         flag_src,
    output wire         flag_dst,

    // 32-bit Gray-coded bus (e.g. cross-domain FIFO pointer, status word
    // the caller has Gray-coded upstream).  Multi-bit synchronizer use
    // requires Gray coding per §6.9; the primitive does not enforce it.
    input  wire [31:0]  bus_src,
    output wire [31:0]  bus_dst
);

  // Canonical 2-FF synchronizer for a single-bit async signal.  This is
  // the most common use of the primitive — every `sos_*` primitive that
  // composes a CDC reset or strobe path instantiates one of these.
  sos_synchronizer #(
      .STAGES (2),
      .WIDTH  (1)
  ) u_sync_1bit (
      .clk_dst (clk_dst),
      .rst_dst (rst_dst),
      .d_src   (flag_src),
      .d_dst   (flag_dst)
  );

  // 3-stage synchronizer for a Gray-coded 32-bit bus.  An extra stage
  // raises the MTBF by orders of magnitude (see MTBF.md) at the cost of
  // one additional destination-domain clock of latency.  Use the 3-stage
  // shape when the target clock frequency × data activity rate × the
  // 2-stage MTBF falls below the project's reliability budget.
  sos_synchronizer #(
      .STAGES (3),
      .WIDTH  (32)
  ) u_sync_data (
      .clk_dst (clk_dst),
      .rst_dst (rst_dst),
      .d_src   (bus_src),
      .d_dst   (bus_dst)
  );

endmodule : sos_synchronizer_example

`default_nettype wire
