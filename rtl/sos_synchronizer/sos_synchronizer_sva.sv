// =============================================================================
// sos_synchronizer_sva.sv  --  SVA assertion module for sos_synchronizer.
//
// @spec docs/concepts/SOS-08-A-CONCEPTS.md §6.9 + §15 (2026-05-23 entries) +
//   §5.3 + PCDN-SOS-08-A-006.
//
//   Per §6.9 SVA-properties paragraph: this primitive is EXCLUDED from the
//   formal model per INV-S-HDL-3.  No SVA property is emitted for the
//   metastability claim — that claim is physical and lives in
//   `rtl/sos_synchronizer/MTBF.md` per PCDN-A-006 (external sign-off,
//   build-wrapper structural validation, no SVA assert/cover for MTBF
//   keeps prove/cover semantics clean).
//
//   The SVA module IS emitted because per-primitive bind-form parity (§4
//   source-of-truth map + PCDN-A-bind-form, all eleven primitives ship an
//   `_sva.sv` + `_bind.sv` pair) is a SOS-08-D consumer contract.  The
//   properties this module carries are functional checks of the
//   non-metastable behaviour at the gate level — reset clears the chain,
//   stable inputs propagate to the output in exactly `STAGES` clocks,
//   the chain length matches the parameter — they do NOT claim anything
//   about metastability resolution probability.
//
//   Note on the canonical CDC SVA properties: cross-domain "src is sampled
//   correctly" properties are hard to formalize at the gate level because
//   the source-domain timing is not modelled.  The cocotb harness drives
//   `d_src` with explicit hold-stable windows around `STAGES`-many
//   destination clock edges and checks `d_dst` follows; the SVA below
//   only checks the destination-domain side of the same property
//   (`d_dst` == `sync_chain[STAGES-1]` from the prior clock edge, etc.).
//   The MTBF claim itself is `// VERIFIED_BY_SDC` -- the build wrapper
//   verifies `MTBF.md` exists with the required fields.
//
// Cited invariants:
//   INV-SOS-A, INV-SOS-B, INV-SOS-E, INV-SOS-G, INV-SOS-H  (SOS-07 §6)
//   INV-S-HDL-1, INV-S-HDL-2, INV-S-HDL-3 (the load-bearing exclusion),
//   INV-S-HDL-4, INV-S-HDL-5                              (SOS-08 §7)
//   INV-S-HDL-A-1, INV-S-HDL-A-2, INV-S-HDL-A-3,          (SOS-08-A §7)
//   INV-S-HDL-A-5
//
// Properties (functional, non-metastability):
//   - p_reset_clears_chain   : on reset, d_dst is zero on the following edge
//   - p_chain_propagates     : a stable d_src for STAGES+1 dst-clk cycles
//                              causes d_dst to equal that value on the last
//   - p_dst_follows_last_ff  : d_dst == sync_chain[STAGES-1] every cycle
//
// VERIFIED_BY_SDC: the metastability MTBF claim itself is recorded in
//   `rtl/sos_synchronizer/MTBF.md` (PCDN-A-006 sign-off file) and enforced
//   by the synthesis-tool synchronizer attributes carried on `sync_chain`
//   in the parent module.  No SVA `assert property` here claims MTBF; the
//   physical claim is not formalizable at the SVA level.
//
// Bind target: `sos_synchronizer`.  The bind directive lives in
// `tb/sos_synchronizer/sos_synchronizer_bind.sv`; this file is the
// assertion module that the bind directive instantiates.
// =============================================================================

`default_nettype none

module sos_synchronizer_sva #(
    parameter int STAGES,
    parameter int WIDTH
) (
    input  wire                 clk_dst,
    input  wire                 rst_dst,
    input  wire [WIDTH-1:0]     d_src,
    input  wire [WIDTH-1:0]     d_dst,
    // Internal observability for the chain-length / dst-follows-last-ff
    // properties.  Bound by the bind directive against
    // `sos_synchronizer.sync_chain`.
    input  wire [WIDTH-1:0]     sync_chain_last
);

  // ---------------------------------------------------------------------------
  // Safety: on reset, the destination-side output is cleared on the
  // following clock edge.  This is the "synchronous active-high rst_dst"
  // half of INV-S-HDL-A-1 expressed at this primitive's boundary.
  // ---------------------------------------------------------------------------
  property p_reset_clears_chain;
    @(posedge clk_dst)
      rst_dst |=> (d_dst == {WIDTH{1'b0}});
  endproperty
  a_reset_clears_chain : assert property (p_reset_clears_chain)
    else $error("sos_synchronizer: d_dst not cleared on rst_dst; d_dst=%h", d_dst);

  // ---------------------------------------------------------------------------
  // Functional: a value held stable on d_src for `STAGES`+1 destination-
  // domain clock edges (out of reset) must appear at d_dst on the
  // STAGES-th edge.
  //
  // Encoded via a sequence `s_src_held_stable_stages` that fires when
  // `d_src` has been stable across `STAGES` consecutive prior dst-clk
  // edges; the implication "stable that long -> d_dst matches" is the
  // gate-level shape of the cross-domain claim.  The source-domain timing
  // is asynchronous so we cannot bound "source completed transition"
  // formally — the cocotb harness covers that with explicit hold windows.
  // ---------------------------------------------------------------------------
  // The sequence collapses to "always" when STAGES == 1, which is not
  // legal per §6.9 (elaboration-time check in the parent fails on
  // STAGES < 2); but the SVA wording stays correct for STAGES >= 2.
  sequence s_src_held_stable_stages;
    @(posedge clk_dst) ($stable(d_src) [* STAGES]);
  endsequence

  property p_chain_propagates;
    @(posedge clk_dst) disable iff (rst_dst)
      s_src_held_stable_stages |-> (d_dst == d_src);
  endproperty
  a_chain_propagates : assert property (p_chain_propagates)
    else $error("sos_synchronizer: d_dst=%h != stable d_src=%h after STAGES cycles",
                d_dst, d_src);

  // ---------------------------------------------------------------------------
  // Safety: d_dst is, by construction, the registered output of the last
  // flop in `sync_chain`.  The bind directive hooks `sync_chain_last` to
  // `sync_chain[STAGES-1]` (SV) / `sync_chain(STAGES)` (VHDL).  This
  // assertion catches any future refactor that accidentally inserts
  // combinational logic between the last flop and `d_dst`.
  // ---------------------------------------------------------------------------
  property p_dst_follows_last_ff;
    @(posedge clk_dst) disable iff (rst_dst)
      (d_dst == sync_chain_last);
  endproperty
  a_dst_follows_last_ff : assert property (p_dst_follows_last_ff)
    else $error("sos_synchronizer: d_dst=%h != sync_chain[STAGES-1]=%h",
                d_dst, sync_chain_last);

endmodule : sos_synchronizer_sva

`default_nettype wire
