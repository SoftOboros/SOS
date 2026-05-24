// SPDX-License-Identifier: MIT
//
// SOS-08-F wave-2 acceptance gate (e) — synthetic DUT
//
// Customer-side synthetic DUT for the end-to-end UVM 1.2 worked example.
// Models a minimal kernel-style syscall responder: each request carries a
// (family, event_id, payload_data) tuple; the DUT acknowledges every
// request and returns a one-cycle response.
//
// This file is INFORMATIVE — not part of the SOS-emitted artifact set.
// It exists purely to demonstrate the customer-side scaffolding the
// SOS-08-F integration contract (§6.5) wraps around. Per INV-S-HDL-F-2
// the DUT lives in the customer's tree, not SOS's.
//
// The DUT semantics are deliberately minimal:
//   * Every (req_valid && req_ready) cycle latches the request.
//   * Responses are issued one cycle later (resp_valid pulses high).
//   * resp_ok = 1 unless the kernel detects a known-bad combination
//     (used by the scoreboard's expected-error path).
//
// The "kernel" maintains tiny state for two semaphores (sem_id 0..1) so
// that sem.take / sem.give sequences exercise meaningful FSM transitions;
// other families are accepted but treated as opaque syscall successes.
//

`default_nettype none

module sos_kernel_dut #(
    parameter int unsigned NUM_SEMS = 2
) (
    input  wire                clk,
    input  wire                rst_n,

    // Request channel (customer's driver -> DUT).
    input  wire                req_valid,
    output wire                req_ready,
    input  wire [2:0]          req_family,    // mirrors sos_event_family_e
    input  wire [7:0]          req_event_id,
    input  wire [63:0]         req_payload,

    // Response channel (DUT -> customer's monitor).
    output reg                 resp_valid,
    output reg                 resp_ok,
    output reg  [7:0]          resp_event_id,
    output reg  [2:0]          resp_family
);

  // Family encoding matches sos_event_family_e in sos_uvm_seq_pkg.svh.
  localparam logic [2:0] FAMILY_TASK  = 3'd0;
  localparam logic [2:0] FAMILY_SEM   = 3'd1;
  localparam logic [2:0] FAMILY_QUEUE = 3'd2;
  localparam logic [2:0] FAMILY_TIMER = 3'd3;
  localparam logic [2:0] FAMILY_EVENT = 3'd4;
  localparam logic [2:0] FAMILY_TICK  = 3'd5;

  // sem.* event_id encoding the test expects.
  localparam logic [7:0] SEM_CREATE = 8'd0;
  localparam logic [7:0] SEM_DELETE = 8'd1;
  localparam logic [7:0] SEM_TAKE   = 8'd2;
  localparam logic [7:0] SEM_GIVE   = 8'd3;

  // Always ready (1-deep request, response is registered).
  assign req_ready = 1'b1;

  // Tiny semaphore state: held[i] = 1 if sem i is currently taken.
  reg held_q [NUM_SEMS];
  integer k;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      resp_valid    <= 1'b0;
      resp_ok       <= 1'b0;
      resp_event_id <= 8'd0;
      resp_family   <= 3'd0;
      for (k = 0; k < NUM_SEMS; k = k + 1)
        held_q[k] <= 1'b0;
    end else begin
      resp_valid <= req_valid;
      if (req_valid) begin
        resp_event_id <= req_event_id;
        resp_family   <= req_family;
        // Default ok unless a known-bad sem op fires.
        resp_ok <= 1'b1;
        if (req_family == FAMILY_SEM) begin
          case (req_event_id)
            SEM_TAKE: begin
              if (req_payload[31:0] < NUM_SEMS) begin
                if (held_q[req_payload[31:0]])
                  resp_ok <= 1'b0; // double-take — kernel-detected error.
                else
                  held_q[req_payload[31:0]] <= 1'b1;
              end
            end
            SEM_GIVE: begin
              if (req_payload[31:0] < NUM_SEMS) begin
                if (!held_q[req_payload[31:0]])
                  resp_ok <= 1'b0; // give-without-take.
                else
                  held_q[req_payload[31:0]] <= 1'b0;
              end
            end
            default: ; // create / delete: acknowledge as ok.
          endcase
        end
      end
    end
  end

endmodule : sos_kernel_dut

`default_nettype wire
