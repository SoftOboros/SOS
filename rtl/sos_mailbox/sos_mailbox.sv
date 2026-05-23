// =============================================================================
// sos_mailbox.sv  --  L1 service: priority-tiered message mailbox
//                    (portable SystemVerilog-2017)
//
// @spec docs/concepts/SOS-08-B-CONCEPTS.md §6.1 (sos_mailbox contract)
//       docs/concepts/SOS-08-B-CONCEPTS.md §5  (frozen decisions inherited)
//       docs/concepts/SOS-08-B-CONCEPTS.md §7  (cross-service invariants
//                                              INV-S-HDL-B-1..5)
//       docs/concepts/SOS-08-B-CONCEPTS.md §15 2026-05-23 ratification entry
//                                              (PCDN-SOS-08-B-001 resolved
//                                              NUM_PRIO default 8;
//                                              PCDN-SOS-08-B-006 resolved
//                                              level-sensitive irq_non_empty)
//       docs/concepts/SOS-08-A-CONCEPTS.md §6.2 (sos_fifo_sync L0 contract;
//                                                composed by instantiation)
//       docs/concepts/SOS-08-A-CONCEPTS.md §6.4 (sos_arbiter_priority L0
//                                                contract; composed by
//                                                instantiation)
//       docs/concepts/SOS-08-A-CONCEPTS.md §15  2026-05-23 wave-1 entry
//                                              (READ_LATENCY / RESET_MEM /
//                                              GRANT_LATENCY_CYCLES generics)
//       docs/concepts/SOS-07-CONCEPTS.md   §6  (cross-phase invariants
//                                              INV-SOS-A..H)
//       docs/concepts/SOS-08-CONCEPTS.md   §7  (cross-sub-phase invariants
//                                              INV-S-HDL-1..5)
//
// Cross-phase invariants (cited, not redefined):
//   INV-SOS-A  chart-as-source
//   INV-SOS-B  vectors-as-deliverable at every layer
//   INV-SOS-C  MCP as sole modification surface
//   INV-SOS-D  iState authoring, SCXML canonical
//   INV-SOS-E  explicit AuthorityRelationship
//   INV-SOS-F  bound composition
//   INV-SOS-G  verified-codegen position
//   INV-SOS-H  vector-to-chart traceability
//
// Cross-sub-phase invariants (SOS-08 §7, cited):
//   INV-S-HDL-1  handshake-compatible ports
//   INV-S-HDL-2  static-allocation discipline
//   INV-S-HDL-3  cross-domain isolation (N/A — single-clock variant)
//   INV-S-HDL-4  cooperative-only at v1
//   INV-S-HDL-5  vector-to-chart traceability for HDL
//
// L1 cross-service invariants (SOS-08-B §7, cited):
//   INV-S-HDL-B-1  vocabulary mirror discipline (post/take/irq are the
//                  FreeRTOS / POSIX-shaped verb set)
//   INV-S-HDL-B-2  L0 non-modification (this module composes sos_fifo_sync +
//                  sos_arbiter_priority by instantiation; no L0 reach-around)
//   INV-S-HDL-B-3  service-level SVA on every L1 instance (provided by
//                  sos_mailbox_sva.sv via tb/sos_mailbox/sos_mailbox_bind.sv)
//   INV-S-HDL-B-4  vendor-IP pass-through (this module inherits the
//                  sos_fifo_sync vendor-IP shim selection transparently)
//   INV-S-HDL-B-5  chart-vocabulary failure rendering (per the bind file)
//
// L0 primitive contracts consumed (by instantiation, per INV-S-HDL-B-2):
//   sos_fifo_sync       (SOS-08-A §6.2)
//   sos_arbiter_priority (SOS-08-A §6.4)
//
// Behavioural summary (per SOS-08-B §6.1):
//   * Producer side is a Slave AXI-Stream surface with an additional
//     s_axis_tprio sideband selecting which of NUM_PRIO parallel FIFO lanes
//     receives the message.
//   * Consumer side is a Master AXI-Stream surface with an additional
//     m_axis_tprio sideband reporting which lane was drained.
//   * NUM_PRIO × sos_fifo_sync (one per lane) hold messages; one
//     sos_arbiter_priority arbitrates across lane ~empty signals using
//     a static priority field (higher lane index = higher priority).
//   * irq_non_empty is level-sensitive (PCDN-SOS-08-B-006): high while any
//     lane FIFO is non-empty.
//
// Design notes (NOT spec re-derivation; flagged for the agent report):
//   * Lane priority convention: higher s_axis_tprio value selects a
//     higher-priority lane. The arbiter's priority_in input is populated
//     with the lane index as priority value, so lane k has priority k.
//     This matches the canonical "higher value wins" of
//     sos_arbiter_priority (§6.4 design choices).
//   * Spec §6.1 prints the sideband width as [$clog2(NUM_PRIO):0] (one bit
//     wider than the canonical -1:0 form). The task brief explicitly fixes
//     [$clog2(NUM_PRIO)-1:0]; this file follows the task brief. AMBIGUITY
//     flagged for the agent report; should fold into the spec at the next
//     §15 walkthrough.
//   * Edge case NUM_PRIO == 1: $clog2(1) == 0, so the sideband width
//     collapses to 0 bits. We clamp to 1 bit via the PRIO_W_EFF localparam
//     so the port shape stays valid in the degenerate single-lane case.
//   * Single-clock-domain only at this implementation. The §6.1 contract
//     mentions a CROSS_CLK generic for sos_fifo_async substitution; the
//     task brief scopes this implementation to the L0 sos_fifo_sync compose
//     only. Cross-clock variant is a future extension.
// =============================================================================

`default_nettype none

module sos_mailbox #(
    // Per PCDN-SOS-08-B-001 (resolved 2026-05-23): default 8 priority lanes,
    // matching the chart's MAX_PRIO. The ONLY default on this module surface
    // -- mirrors the INV-S-HDL-A-5 named-exception convention from SOS-08-A.
    parameter int NUM_PRIO              = 8,

    // Mandatory: no default (INV-S-HDL-A-5, inherited from sos_fifo_sync §6.2).
    parameter int DEPTH,
    parameter int WIDTH,
    parameter int READ_LATENCY,
    parameter bit RESET_MEM,

    // Mandatory: no default (INV-S-HDL-A-5, inherited from sos_arbiter_priority
    // §6.4).
    parameter int AGING_ENABLE,
    parameter int AGING_THRESHOLD,

    // PCDN-A-arbiter-GRANT_LATENCY_CYCLES named-exception default
    // (inherited from sos_arbiter_priority §6.4 surface).
    parameter int GRANT_LATENCY_CYCLES  = 1,

    // Derived: effective priority-sideband width.  Clamped to >=1 so the
    // NUM_PRIO=1 degenerate case still carries a 1-bit sideband.
    parameter int PRIO_W_EFF = (NUM_PRIO <= 1) ? 1 : $clog2(NUM_PRIO),
    // Derived: fill-count observability width for each underlying FIFO.
    parameter int CNT_W      = $clog2(DEPTH + 1)
) (
    // Clock + sync active-high reset (INV-S-HDL-A-1 / PCDN-A-003).
    input  wire                        clk,
    input  wire                        rst,

    // Slave AXI-Stream ingress (producer drives, mailbox accepts).
    // s_axis_tprio selects which priority lane the message lands in.
    input  wire [WIDTH-1:0]            s_axis_tdata,
    input  wire [PRIO_W_EFF-1:0]       s_axis_tprio,
    input  wire                        s_axis_tvalid,
    output wire                        s_axis_tready,

    // Master AXI-Stream egress (mailbox presents, consumer accepts).
    // m_axis_tprio reports which priority lane produced the egress.
    output wire [WIDTH-1:0]            m_axis_tdata,
    output wire [PRIO_W_EFF-1:0]       m_axis_tprio,
    output wire                        m_axis_tvalid,
    input  wire                        m_axis_tready,

    // Level-sensitive IRQ per PCDN-SOS-08-B-006: high while any lane
    // non-empty.
    output wire                        irq_non_empty
);

  // ---------------------------------------------------------------------------
  // Elaboration-time validation.
  // ---------------------------------------------------------------------------
  initial begin
    if (NUM_PRIO < 1) begin
      $fatal(1, "sos_mailbox: NUM_PRIO must be >= 1; got %0d", NUM_PRIO);
    end
    if (DEPTH < 1) begin
      $fatal(1, "sos_mailbox: DEPTH must be >= 1; got %0d", DEPTH);
    end
    if (WIDTH < 1) begin
      $fatal(1, "sos_mailbox: WIDTH must be >= 1; got %0d", WIDTH);
    end
  end

  // ---------------------------------------------------------------------------
  // Per-lane FIFO surfaces.  One sos_fifo_sync per lane (INV-S-HDL-B-2).
  // ---------------------------------------------------------------------------
  // Per-lane decoded ingress handshake.  Only the targeted lane sees tvalid;
  // the producer's tready is the targeted lane's tready (one cycle behind
  // the decode -- registered or combinational depending on the FIFO's own
  // ready path, which is combinational off full_q in sos_fifo_sync.sv).
  wire [NUM_PRIO-1:0]            lane_s_tvalid;
  wire [NUM_PRIO-1:0]            lane_s_tready;
  wire [NUM_PRIO-1:0]            lane_full;
  wire [NUM_PRIO-1:0]            lane_empty;
  wire [NUM_PRIO-1:0][WIDTH-1:0] lane_m_tdata;
  wire [NUM_PRIO-1:0]            lane_m_tvalid;
  wire [NUM_PRIO-1:0]            lane_m_tready;
  wire [NUM_PRIO-1:0][CNT_W-1:0] lane_count;

  genvar gi;
  generate
    for (gi = 0; gi < NUM_PRIO; gi++) begin : g_lane
      // Ingress decode: only lane == s_axis_tprio sees a valid.
      assign lane_s_tvalid[gi] =
          s_axis_tvalid && (s_axis_tprio == PRIO_W_EFF'(gi));

      sos_fifo_sync #(
          .DEPTH        (DEPTH),
          .WIDTH        (WIDTH),
          .READ_LATENCY (READ_LATENCY),
          .RESET_MEM    (RESET_MEM)
      ) u_lane (
          .clk            (clk),
          .rst            (rst),

          .s_axis_tdata   (s_axis_tdata),
          .s_axis_tvalid  (lane_s_tvalid[gi]),
          .s_axis_tready  (lane_s_tready[gi]),

          .m_axis_tdata   (lane_m_tdata[gi]),
          .m_axis_tvalid  (lane_m_tvalid[gi]),
          .m_axis_tready  (lane_m_tready[gi]),

          .full           (lane_full[gi]),
          .empty          (lane_empty[gi]),
          .count          (lane_count[gi])
      );
    end
  endgenerate

  // Producer-side tready is the targeted lane's tready.  If the producer
  // asserts s_axis_tvalid with an out-of-range tprio (>= NUM_PRIO), the
  // ingress decode drives no lane_s_tvalid bit, and we present tready=0
  // (the producer stalls until it corrects the sideband).  An out-of-range
  // s_axis_tprio is a defence-in-depth case -- the chart compiler is
  // expected to clamp it at SOS-08-C emission time; the SVA module catches
  // it at runtime.  This mirrors the spec §6.1 RC_INVAL slot, encoded
  // here as a stalled handshake rather than the doc's two-bit rc bus
  // (omitted from the task brief's surface).
  reg [NUM_PRIO-1:0] s_tprio_one_hot;
  always_comb begin
    s_tprio_one_hot = '0;
    for (int i = 0; i < NUM_PRIO; i++) begin
      if (PRIO_W_EFF'(i) == s_axis_tprio) begin
        s_tprio_one_hot[i] = 1'b1;
      end
    end
  end
  assign s_axis_tready =
      (|s_tprio_one_hot) ? |(s_tprio_one_hot & lane_s_tready) : 1'b0;

  // ---------------------------------------------------------------------------
  // sos_arbiter_priority over per-lane ~empty signals.
  //
  // Lane k presents req=1 to the arbiter while it has data to drain (i.e.
  // !lane_empty[k] AND lane_m_tvalid[k]; the two are equivalent under the
  // sos_fifo_sync contract -- tvalid is ~empty per §6.2 -- but we use
  // lane_m_tvalid as the canonical "has-data" handle so the consumer
  // handshake is verbatim from the L0 surface).
  //
  // Priority value for lane k is k itself (higher index = higher priority).
  // The arbiter's "higher value wins" convention (§6.4) makes lane NUM_PRIO-1
  // the top-priority lane.
  //
  // PRIORITY_BITS sized to fit (NUM_PRIO-1).  Clamped to >=1.
  // ---------------------------------------------------------------------------
  localparam int PBITS = (NUM_PRIO <= 1) ? 1 : $clog2(NUM_PRIO);

  wire [NUM_PRIO-1:0]            arb_req;
  wire [NUM_PRIO*PBITS-1:0]      arb_priority_in;
  wire [NUM_PRIO-1:0]            arb_grant;
  wire [$clog2(NUM_PRIO + 1)-1:0] arb_last_winner_id;

  generate
    for (gi = 0; gi < NUM_PRIO; gi++) begin : g_arb_in
      assign arb_req[gi] = lane_m_tvalid[gi];
      assign arb_priority_in[(gi+1)*PBITS - 1 -: PBITS] = PBITS'(gi);
    end
  endgenerate

  // ---------------------------------------------------------------------------
  // Single-lane degenerate case: arbiter requires N_REQS >= 2.  When
  // NUM_PRIO == 1 we bypass the arbiter and wire the lane straight through.
  // ---------------------------------------------------------------------------
  generate
    if (NUM_PRIO == 1) begin : g_single_lane
      assign arb_grant          = lane_m_tvalid;
      assign arb_last_winner_id = '0;
    end else begin : g_multi_lane
      sos_arbiter_priority #(
          .N_REQS               (NUM_PRIO),
          .PRIORITY_BITS        (PBITS),
          .AGING_ENABLE         (AGING_ENABLE),
          .AGING_THRESHOLD      (AGING_THRESHOLD),
          .GRANT_LATENCY_CYCLES (GRANT_LATENCY_CYCLES)
      ) u_arb (
          .clk             (clk),
          .rst             (rst),
          .req             (arb_req),
          .priority_in     (arb_priority_in),
          .grant           (arb_grant),
          .last_winner_id  (arb_last_winner_id)
      );
    end
  endgenerate

  // ---------------------------------------------------------------------------
  // Egress mux: route the granted lane's tdata + tvalid to the consumer
  // surface, gate the consumer's tready back to the granted lane only.
  // The granted lane's m_axis_tprio reports its index.
  //
  // Mux selection follows the one-hot grant bus (sos_arbiter_priority §6.4
  // guarantees $countones(grant) <= 1 per cycle).
  // ---------------------------------------------------------------------------
  reg [WIDTH-1:0]      egress_data;
  reg [PRIO_W_EFF-1:0] egress_prio;
  reg                  egress_valid;
  always_comb begin
    egress_data  = '0;
    egress_prio  = '0;
    egress_valid = 1'b0;
    for (int i = 0; i < NUM_PRIO; i++) begin
      if (arb_grant[i]) begin
        egress_data  = lane_m_tdata[i];
        egress_prio  = PRIO_W_EFF'(i);
        egress_valid = lane_m_tvalid[i];
      end
    end
  end

  assign m_axis_tdata  = egress_data;
  assign m_axis_tprio  = egress_prio;
  assign m_axis_tvalid = egress_valid;

  generate
    for (gi = 0; gi < NUM_PRIO; gi++) begin : g_egress_ready
      // tready propagates only to the granted lane; un-granted lanes see 0.
      assign lane_m_tready[gi] = arb_grant[gi] && m_axis_tready;
    end
  endgenerate

  // ---------------------------------------------------------------------------
  // Level-sensitive irq_non_empty (PCDN-SOS-08-B-006).
  //
  // High while any lane FIFO holds data, i.e. == |(~lane_empty).
  // ---------------------------------------------------------------------------
  assign irq_non_empty = |(~lane_empty);

endmodule : sos_mailbox

`default_nettype wire
