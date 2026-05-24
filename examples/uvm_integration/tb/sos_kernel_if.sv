// SPDX-License-Identifier: MIT
//
// SOS-08-F wave-2 acceptance gate (e) — DUT interface
//
// Customer-side SystemVerilog interface bundling the synthetic DUT's
// request / response signals. The customer's driver drives the request
// side; the customer's monitor samples the response side; both connect
// to the env's analysis ports.
//
// INFORMATIVE per §6.5 — this is the customer-owned signal-level
// boundary the SOS integration contract wraps around. SOS does NOT emit
// this interface.
//

`default_nettype none

interface sos_kernel_if(input wire clk);
  logic        rst_n;

  logic        req_valid;
  logic        req_ready;
  logic [2:0]  req_family;
  logic [7:0]  req_event_id;
  logic [63:0] req_payload;

  logic        resp_valid;
  logic        resp_ok;
  logic [7:0]  resp_event_id;
  logic [2:0]  resp_family;

  // Master clocking block — driver point of view.
  clocking drv_cb @(posedge clk);
    output rst_n;
    output req_valid;
    output req_family;
    output req_event_id;
    output req_payload;
    input  req_ready;
    input  resp_valid;
    input  resp_ok;
    input  resp_event_id;
    input  resp_family;
  endclocking

  // Monitor clocking block — sampling point of view.
  clocking mon_cb @(posedge clk);
    input rst_n;
    input req_valid;
    input req_ready;
    input req_family;
    input req_event_id;
    input req_payload;
    input resp_valid;
    input resp_ok;
    input resp_event_id;
    input resp_family;
  endclocking

  modport DRV(clocking drv_cb);
  modport MON(clocking mon_cb);
endinterface : sos_kernel_if

`default_nettype wire
