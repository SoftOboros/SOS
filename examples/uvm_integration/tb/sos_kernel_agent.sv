// SPDX-License-Identifier: MIT
//
// SOS-08-F wave-2 acceptance gate (e) — customer-side UVM agent
//
// Bundles the sequencer (parameterized on the SOS sos_seq_item), the
// driver (customer-authored — translates SOS items to DUT pin activity
// per §6.5 step 3), and the monitor (samples the DUT bus and forwards
// observed transactions to the scoreboard analysis port).
//
// INFORMATIVE per §6.5 — entire file is customer-side scaffolding.
// SOS-08-F emits NONE of this; the SOS package only provides the
// sequences + sos_seq_item baseline that this agent's driver consumes.
//
// Per INV-S-HDL-F-2, env / agent / sequencer / driver / monitor /
// scoreboard / test classes are all customer-owned. This file
// demonstrates a minimal compliant shape — customers adapt to their
// house conventions.
//
// Spec invariant tie-ins:
//   * INV-S-HDL-F-2 — customer-owned agent (this file).
//   * INV-S-HDL-F-3 — driver propagates chart_state / transition_id /
//                     invariant_id into observed transactions; monitor
//                     reconstructs them on the response side.
//   * §6.6 chart-vocabulary failure format — driver emits the
//     "[SOS-SEQ] state=... transition=... invariant=..." string on any
//     unrecognised family.
//

`include "uvm_macros.svh"

import uvm_pkg::*;
import sos_uvm_seq_pkg::*;

// -------------------------------------------------------------------------
// Observed-transaction class — customer's monitor publishes one of these
// per DUT response. Carries chart-vocabulary metadata forward so the
// scoreboard's failure messages render in chart vocabulary (INV-SOS-H /
// INV-S-HDL-5 / INV-S-HDL-F-3).
// -------------------------------------------------------------------------
class sos_kernel_obs_item extends uvm_sequence_item;
  rand sos_event_family_e family;
  rand int                event_id;
  rand bit [63:0]         payload_data;
  rand string             chart_state;
  rand int                transition_id;
  rand int                invariant_id;
  rand bit                resp_ok;

  `uvm_object_utils_begin(sos_kernel_obs_item)
    `uvm_field_enum(sos_event_family_e, family, UVM_ALL_ON)
    `uvm_field_int(event_id, UVM_ALL_ON)
    `uvm_field_int(payload_data, UVM_ALL_ON)
    `uvm_field_string(chart_state, UVM_ALL_ON)
    `uvm_field_int(transition_id, UVM_ALL_ON)
    `uvm_field_int(invariant_id, UVM_ALL_ON)
    `uvm_field_int(resp_ok, UVM_ALL_ON)
  `uvm_object_utils_end

  function new(string name = "sos_kernel_obs_item");
    super.new(name);
  endfunction
endclass : sos_kernel_obs_item

// -------------------------------------------------------------------------
// Sequencer — typedef per §6.5 step 2. Single line.
// -------------------------------------------------------------------------
typedef uvm_sequencer #(sos_seq_item) sos_kernel_sequencer;

// -------------------------------------------------------------------------
// Driver — customer-authored per §6.5 step 3. Pulls sos_seq_item off
// the sequencer port, drives request bus, waits for DUT to accept.
// Forwards chart-vocabulary metadata to a parallel analysis port so the
// scoreboard can pair requests with responses.
// -------------------------------------------------------------------------
class sos_kernel_driver extends uvm_driver #(sos_seq_item);
  `uvm_component_utils(sos_kernel_driver)

  virtual sos_kernel_if vif;
  uvm_analysis_port #(sos_kernel_obs_item) req_ap;

  function new(string name, uvm_component parent);
    super.new(name, parent);
    req_ap = new("req_ap", this);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db #(virtual sos_kernel_if)::get(this, "", "vif", vif))
      `uvm_fatal("DRV", "virtual interface 'vif' not set")
  endfunction

  virtual task run_phase(uvm_phase phase);
    sos_seq_item tx;
    sos_kernel_obs_item obs;
    // Hold reset for a few cycles.
    vif.drv_cb.rst_n     <= 1'b0;
    vif.drv_cb.req_valid <= 1'b0;
    repeat (4) @(vif.drv_cb);
    vif.drv_cb.rst_n     <= 1'b1;

    forever begin
      seq_item_port.get_next_item(tx);
      // Drive one request cycle.
      vif.drv_cb.req_valid    <= 1'b1;
      vif.drv_cb.req_family   <= tx.family;
      vif.drv_cb.req_event_id <= tx.event_id[7:0];
      vif.drv_cb.req_payload  <= tx.payload_data;
      @(vif.drv_cb);
      vif.drv_cb.req_valid <= 1'b0;

      // Publish the requested transaction for the scoreboard to pair
      // with the upcoming response. Carries chart-vocabulary metadata.
      obs = sos_kernel_obs_item::type_id::create("obs");
      obs.family        = tx.family;
      obs.event_id      = tx.event_id;
      obs.payload_data  = tx.payload_data;
      obs.chart_state   = tx.chart_state;
      obs.transition_id = tx.transition_id;
      obs.invariant_id  = tx.invariant_id;
      obs.resp_ok       = 1'b1; // unknown until monitor sees the response.
      req_ap.write(obs);

      seq_item_port.item_done();
    end
  endtask
endclass : sos_kernel_driver

// -------------------------------------------------------------------------
// Monitor — samples the response bus and publishes observed responses.
// -------------------------------------------------------------------------
class sos_kernel_monitor extends uvm_monitor;
  `uvm_component_utils(sos_kernel_monitor)

  virtual sos_kernel_if vif;
  uvm_analysis_port #(sos_kernel_obs_item) resp_ap;

  function new(string name, uvm_component parent);
    super.new(name, parent);
    resp_ap = new("resp_ap", this);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db #(virtual sos_kernel_if)::get(this, "", "vif", vif))
      `uvm_fatal("MON", "virtual interface 'vif' not set")
  endfunction

  virtual task run_phase(uvm_phase phase);
    sos_kernel_obs_item obs;
    forever begin
      @(vif.mon_cb);
      if (vif.mon_cb.resp_valid) begin
        obs = sos_kernel_obs_item::type_id::create("obs");
        // Monitor cannot reconstruct chart vocabulary from pins alone;
        // the scoreboard pairs this with the driver's chart-vocabulary
        // analysis-port emission per transaction.
        obs.family   = sos_event_family_e'(vif.mon_cb.resp_family);
        obs.event_id = vif.mon_cb.resp_event_id;
        obs.resp_ok  = vif.mon_cb.resp_ok;
        obs.chart_state   = "<monitor>";
        obs.transition_id = 0;
        obs.invariant_id  = 0;
        resp_ap.write(obs);
      end
    end
  endtask
endclass : sos_kernel_monitor

// -------------------------------------------------------------------------
// Agent — composes sequencer + driver + monitor + their analysis ports.
// -------------------------------------------------------------------------
class sos_kernel_agent extends uvm_agent;
  `uvm_component_utils(sos_kernel_agent)

  sos_kernel_sequencer sequencer;
  sos_kernel_driver    driver;
  sos_kernel_monitor   monitor;

  uvm_analysis_port #(sos_kernel_obs_item) req_ap;
  uvm_analysis_port #(sos_kernel_obs_item) resp_ap;

  function new(string name, uvm_component parent);
    super.new(name, parent);
    req_ap  = new("req_ap",  this);
    resp_ap = new("resp_ap", this);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    sequencer = sos_kernel_sequencer::type_id::create("sequencer", this);
    driver    = sos_kernel_driver::type_id::create("driver",    this);
    monitor   = sos_kernel_monitor::type_id::create("monitor",   this);
  endfunction

  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    driver.seq_item_port.connect(sequencer.seq_item_export);
    driver.req_ap.connect(req_ap);
    monitor.resp_ap.connect(resp_ap);
  endfunction
endclass : sos_kernel_agent
