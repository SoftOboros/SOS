r"""SCXML chart → UVM sequence emitter (SOS-08-F).

Wave-1 scaffold per ``SOS-08-F-CONCEPTS.md`` §6 (sequence-emission
contract) and §15 (2026-05-23 ratification). Emits a sequences-only
artifact set per the 10/80 framing — the customer owns env, agent,
sequencer, driver, monitor, scoreboard, test classes; SOS owns only
the sequence library + baseline transaction class.

@spec  SOS-08-F-CONCEPTS.md §5.1 (scope discipline — sequences only;
       eight-item exclusion list)
@spec  SOS-08-F-CONCEPTS.md §5.2 (UVM 1.2 grammar + UVM 2.0 forward-
       compatibility)
@spec  SOS-08-F-CONCEPTS.md §5.3 (universal ``sos_seq_item`` with
       discriminated-union payload)
@spec  SOS-08-F-CONCEPTS.md §5.4 (no SVA emission — sibling SOS-08-D
       + SOS-08-E own that artifact)
@spec  SOS-08-F-CONCEPTS.md §5.5 (`uvm_object_utils` registration is
       SOS-emitted in the consolidated package)
@spec  SOS-08-F-CONCEPTS.md §5.6 (empty virtual pre_body / post_body
       hooks for customer override)
@spec  SOS-08-F-CONCEPTS.md §5.7 (one consolidated SystemVerilog
       package — ``sos_uvm_seq_pkg``)
@spec  SOS-08-F-CONCEPTS.md §6.1 (six chart event families)
@spec  SOS-08-F-CONCEPTS.md §6.2 (baseline ``sos_seq_item`` shape)
@spec  SOS-08-F-CONCEPTS.md §6.3 (per-family sequence subclass shape)
@spec  SOS-08-F-CONCEPTS.md §6.5 (customer-integration contract —
       five extension points)
@spec  SOS-08-F-CONCEPTS.md §6.6 (chart-vocabulary failure-message
       format)
@spec  SOS-08-F-CONCEPTS.md §7 INV-S-HDL-F-1 (sequences only — no
       env / agent / sequencer / driver / monitor / scoreboard /
       test / config_db emission)
@spec  SOS-08-F-CONCEPTS.md §7 INV-S-HDL-F-2 (customer owns env,
       scoreboard, driver, factory)
@spec  SOS-08-F-CONCEPTS.md §7 INV-S-HDL-F-3 (chart-vocabulary
       traceability survives the UVM boundary — every sos_seq_item
       carries chart_state / transition_id / invariant_id)
@spec  SOS-08-F-CONCEPTS.md §7 INV-S-HDL-F-4 (no SVA emission)
@spec  SOS-08-F-CONCEPTS.md §7 INV-S-HDL-F-5 (UVM version
       compatibility — UVM 1.2 grammar runs unchanged on UVM 2.0)
@spec  SOS-07-CONCEPTS.md  §7 AuthorityRelationship matrix — UVM is
       **derive** (consume grammar, do not own it); INV-SOS-A..H cited
@spec  SOS-08-CONCEPTS.md  §7 INV-S-HDL-1..5 (cited; INV-S-HDL-5 =
       vector-to-chart traceability for HDL, load-bearing for
       sos_seq_item chart-vocabulary fields)

# Wave-1 scope

* Single artifact set per chart (six per-family classes + one
  baseline transaction class + integration example), all under
  ``uvm/<chart>/``:
    - ``uvm/<chart>/sos_uvm_seq_pkg.sv``  — consolidated package per
      §5.7; baseline ``sos_seq_item`` + six per-family ``uvm_sequence``
      subclasses + ``sos_event_family_e`` enum.
    - ``uvm/<chart>/sos_uvm_seq_pkg.svh`` — header file with typedef
      + enum exports for customer-driver consumption.
    - ``uvm/<chart>/sos_uvm_integration_example.sv`` — informative
      five-step worked example per §6.5.

* The six chart event families per PCDN-SOS-08-F-002 resolved 2026-
  05-23 (`task`, `sem`, `queue`, `timer`, `event`, `tick`).

* JSONL vector IR consumption is a wave-1 stub task — the per-family
  sequence's ``body()`` provides the ``load_vector_ir(path, events)``
  shape but the parse logic is a wave-2 deliverable alongside
  SOS-08-E's full SOS-03 schema parser. Wave-1 satisfies acceptance
  gates (a)-(d) + (g)-(i); gate (e) end-to-end customer-side run is
  the second-tier conformance level the spec already documents.

* Parallel charts are accepted (SOS-08-F is chart-agnostic — the
  vector IR is the same regardless of chart parallelism; the sequence
  library is the same library; the customer's driver routes events
  to DUT pins regardless of which chart region produced them).

# Integration contract

The codegen tool's CLI dispatcher invokes::

    from transliterate_hdl_uvm_seq import render_target
    files = render_target(chart_ir, config)

``chart_ir`` is the raw scjson dict (``ChartAst.raw_scjson``). Output
is a ``dict[filename, source]`` mapping output filename (relative
path embedding the ``uvm/<chart>/`` prefix) to emitted file source.

# Invariant audit at emit time

Emitted text is post-pass scanned for INV-S-HDL-F-1 / -3 / -4 forbidden
constructs:
  - INV-S-HDL-F-1: ``uvm_env`` / ``uvm_agent`` / ``uvm_sequencer`` /
    ``uvm_driver`` / ``uvm_monitor`` / ``uvm_scoreboard`` /
    ``uvm_test`` / ``uvm_config_db`` extends-declarations.
  - INV-S-HDL-F-3: every ``sos_seq_item`` field set documents
    ``chart_state``, ``transition_id``, ``invariant_id``.
  - INV-S-HDL-F-4: no ``assert property`` or ``bind`` directive.
Any hit raises ``InvariantAuditError`` — signals an internal walker
bug, not a chart-author error.

# Failure-message format (INV-S-HDL-F-3 + §6.6)

The integration example demonstrates the chart-vocabulary failure-
message format::

    [SOS-SEQ] state=task_b.holding_sem transition=T43 invariant=I7
              family=sem event=sem.give: <details>

The customer's scoreboard / monitor / assertion handler emits this
shape via ``uvm_error`` / ``uvm_fatal`` calls; chart vocabulary is
guaranteed present regardless of any per-customer formatter override.
"""

from __future__ import annotations

import re
from typing import Any


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class InvariantAuditError(RuntimeError):
    """Emitted text violated INV-S-HDL-F-1 / -3 / -4 at the audit pass."""


class UnsupportedChartError(Exception):
    """Raised when chart shape is outside wave-1 scope.

    SOS-08-F is chart-agnostic at wave-1 (the vector IR is the same
    regardless of chart structure), so this exception is reserved for
    input-validation failures (e.g. chart_ir is not a dict).
    """


# ---------------------------------------------------------------------------
# Chart event families (PCDN-SOS-08-F-002 resolved — six families)
# ---------------------------------------------------------------------------


CHART_EVENT_FAMILIES: tuple[str, ...] = (
    "task",
    "sem",
    "queue",
    "timer",
    "event",
    "tick",
)
"""The six chart event families frozen at SOS-08-F §6.1 +
PCDN-SOS-08-F-002 resolution 2026-05-23. Each family gets one
``uvm_sequence`` subclass per §6.3."""


# ---------------------------------------------------------------------------
# Identifier sanitization (mirrors transliterate_sva_bind)
# ---------------------------------------------------------------------------


def _sanitize_sv_identifier(name: str) -> str:
    """Lower-case + swap non-alphanumerics to underscore."""
    out = re.sub(r"[^A-Za-z0-9_]", "_", name.strip()).strip("_").lower()
    if not out:
        return "chart"
    if out[0].isdigit():
        out = f"_{out}"
    return out


def _normalise_chart_name(chart_name: str | None) -> str:
    return _sanitize_sv_identifier(chart_name or "chart")


# ---------------------------------------------------------------------------
# Header block (cited spec references)
# ---------------------------------------------------------------------------


_SV_HEADER_PREFIX = """// SPDX-License-Identifier: MIT
// SOS-08-F wave-1 emitted artifact — DO NOT EDIT BY HAND.
//
// Generated by ``tools/sos-codegen/transliterate_hdl_uvm_seq.py``.
//
// Spec references (per SOS-08-F §12 (h)+(i) acceptance gates):
//   * SOS-08-F-CONCEPTS.md §5..§7  (emission contract + invariants)
//   * SOS-07-CONCEPTS.md   §6      (INV-SOS-A..H cross-phase
//                                    invariants)
//   * SOS-07-CONCEPTS.md   §7      (AuthorityRelationship matrix —
//                                    UVM is `derive`)
//   * SOS-08-CONCEPTS.md   §7      (INV-S-HDL-1..5 cross-sub-phase
//                                    invariants; INV-S-HDL-5 = chart-
//                                    vocabulary traceability —
//                                    load-bearing on sos_seq_item
//                                    metadata fields below)
//
// Invariants upheld by this artifact:
//   * INV-S-HDL-F-1: sequences only (no env / agent / sequencer /
//                     driver / monitor / scoreboard / test /
//                     config_db emission).
//   * INV-S-HDL-F-2: customer owns env, scoreboard, driver, factory.
//   * INV-S-HDL-F-3: every sos_seq_item carries chart_state /
//                     transition_id / invariant_id chart-vocabulary
//                     metadata.
//   * INV-S-HDL-F-4: no SVA emission (no `assert property`, no
//                     `bind`); SVA is sibling SOS-08-D + SOS-08-E.
//   * INV-S-HDL-F-5: UVM 1.2 grammar only; runs unchanged on UVM 2.0.
//
"""


# ---------------------------------------------------------------------------
# Per-file emitters
# ---------------------------------------------------------------------------


def _emit_per_family_sequence(family: str) -> str:
    """Emit one ``sos_<family>_sequence`` class per PCDN-G-002 family.

    Per §6.3 template + §5.6 (empty virtual hooks) + §5.5 (uvm_object_utils
    registration is in-package). The body() task consumes the chart's
    vector IR via load_vector_ir() and produces one sos_seq_item per
    chart event in the family.
    """
    cls = f"sos_{family}_sequence"
    fam_upper = family.upper()
    return f"""  // -------------------------------------------------------------------------
  // {cls} — per-family stimulus sequence (family={family})
  // -------------------------------------------------------------------------
  //
  // Emits one sos_seq_item per chart event in the `{family}` family
  // (per SOS-08-F §6.1 + §6.3). The customer's sequencer accepts the
  // sos_seq_item; the customer's driver translates each item's
  // (family, event_id, payload_data) into DUT-pin-level activity per
  // §6.5 customer-integration contract.
  class {cls} extends uvm_sequence #(sos_seq_item);

    `uvm_object_utils({cls})

    // Vector IR path — set by customer test before start():
    //   seq.vector_path = "vectors/{family}_chart_bound.jsonl";
    string vector_path;

    function new(string name = "{cls}");
      super.new(name);
    endfunction

    // Customer override point per §5.6 + PCDN-SOS-08-F-005. Default:
    // no-op. Customer subclasses {cls} + overrides pre_body to inject
    // env quiescence waits / DUT preconditioning / scoreboard
    // snapshot logic.
    virtual task pre_body();
    endtask

    virtual task body();
      sos_chart_event_s events[$];
      sos_seq_item tx;
      int i;
      // Wave-1: load_vector_ir is a stub the customer's env wires to
      // its chart vector source. Wave-2 ships the full SOS-03 JSONL
      // parser (co-deferred with SOS-08-E's full vector-schema
      // consumer per the SOS-08-F §15 wave-1 entry).
      load_vector_ir(vector_path, events);
      foreach (events[i]) begin
        tx = sos_seq_item::type_id::create($sformatf("tx_%0d", i));
        start_item(tx);
        tx.family        = SOS_FAMILY_{fam_upper};
        tx.event_id      = events[i].event_id;
        tx.payload_data  = events[i].payload_data;
        tx.chart_state   = events[i].chart_state;
        tx.transition_id = events[i].transition_id;
        tx.invariant_id  = events[i].invariant_id;
        finish_item(tx);
      end
    endtask

    // Customer override point per §5.6 + PCDN-SOS-08-F-005. Default:
    // no-op. Customer subclasses {cls} + overrides post_body to drain
    // scoreboard expectations / cycle quiescence / DUT teardown.
    virtual task post_body();
    endtask

    // Wave-2 (2026-05-24 §15) — JSONL vector-IR parser landed.
    // Calls the package-level shared sos_load_chart_event_jsonl task
    // which implements the strict JSONL row schema defined in
    // SOS-08-F §6.4. Customer MAY override this task at the sequence
    // subclass level to drive sequences from a non-JSONL source
    // (in-memory test-author-provided event list, alternative chart
    // export, regression harness feed) — per §6.5 customer-
    // integration contract.
    virtual task load_vector_ir(string path, ref sos_chart_event_s events[$]);
      events.delete();
      sos_load_chart_event_jsonl(path, events);
    endtask

  endclass : {cls}
"""


def _emit_jsonl_parser() -> str:
    """Emit the package-level ``sos_parse_chart_event_jsonl`` function +
    ``sos_load_chart_event_jsonl`` task per SOS-08-F §6.4 wave-2.

    Implements the load-bearing JSONL vector-IR parser. Each line of the
    vector-IR file is one chart event; the parser populates a queue of
    ``sos_chart_event_s`` rows that the per-family sequence's ``body()``
    iterates. Strict row schema per the wave-2 §15 amendment:

        {"event_id":<int>,"payload_data":<int>,"chart_state":"<str>",
         "transition_id":<int>,"invariant_id":<int>}

    No whitespace inside the object (other than within the quoted
    chart_state string). Lines that don't match the schema are skipped
    with a UVM warning citing the offending line — chart-vocabulary
    failure rendering per INV-S-HDL-B-5 / INV-S-HDL-F-3.

    SV-side parsing uses ``$sscanf`` with the ``%[^"]`` set specifier
    to extract the quoted ``chart_state`` value cleanly. Numeric fields
    use ``%d`` (decimal). For 64-bit payload values, callers MAY emit
    them as hex in the chart compiler and use ``%h`` — at v1 we
    standardise on decimal for cross-toolchain portability (Verilator
    + VCS + Questa all accept decimal width-aware ``%d``).
    """
    return r"""  // -------------------------------------------------------------------------
  // sos_parse_chart_event_jsonl + sos_load_chart_event_jsonl —
  // SOS-08-F §6.4 wave-2 vector-IR JSONL parser
  // -------------------------------------------------------------------------
  //
  // Per the SOS-08-F §15 2026-05-24 wave-2 amendment, the chart's
  // bounded-reachability output is canonical JSONL per SOS-08
  // PCDN-009. Each line is one chart event; the row schema is:
  //
  //   {"event_id":<int>,"payload_data":<int>,"chart_state":"<str>",
  //    "transition_id":<int>,"invariant_id":<int>}
  //
  // No whitespace inside the JSON object. The chart_state value is
  // quoted; other values are bare decimal integers. Lines that don't
  // match are skipped with a UVM warning citing the offending text.
  //
  // The parser is package-level (NOT a sequence-class method) so any
  // per-family sequence's load_vector_ir() can invoke it without
  // duplicating the format-string contract.

  // Parse one JSONL line into an sos_chart_event_s. Returns 1 on
  // success, 0 on parse error (caller should skip the line).
  function automatic int sos_parse_chart_event_jsonl(
      input  string line,
      output sos_chart_event_s evt
  );
    int rc;
    int unsigned ev_id;
    longint unsigned payload;
    int unsigned tr_id;
    int unsigned inv_id;
    string chart_state_buf;
    rc = $sscanf(line,
      "{\"event_id\":%d,\"payload_data\":%d,\"chart_state\":\"%[^\"]\",\"transition_id\":%d,\"invariant_id\":%d}",
      ev_id, payload, chart_state_buf, tr_id, inv_id);
    if (rc != 5) begin
      return 0;
    end
    evt.event_id      = ev_id;
    evt.payload_data  = payload;
    evt.chart_state   = chart_state_buf;
    evt.transition_id = tr_id;
    evt.invariant_id  = inv_id;
    return 1;
  endfunction

  // Read a chart-vocabulary JSONL file from `path`, append each parsed
  // row to `events`. Empty / blank lines are skipped silently;
  // malformed lines emit a UVM warning and are skipped.
  //
  // The shared task is invoked by each per-family sequence's
  // `load_vector_ir` override. Customer-authored vector sources MAY
  // bypass the JSONL parser entirely by overriding `load_vector_ir`
  // at the sequence subclass level (per §6.5 customer-integration
  // contract).
  task automatic sos_load_chart_event_jsonl(
      input  string path,
      ref    sos_chart_event_s events[$]
  );
    int fh;
    string line;
    sos_chart_event_s evt;
    int parsed;
    int line_no;
    line_no = 0;
    fh = $fopen(path, "r");
    if (fh == 0) begin
      `uvm_warning("SOS-08-F",
        $sformatf("sos_load_chart_event_jsonl: cannot open '%s'", path))
      return;
    end
    while (!$feof(fh)) begin
      void'($fgets(line, fh));
      line_no++;
      // Skip empty / whitespace-only lines.
      if (line.len() < 2) continue;
      // Strip trailing newline if present ($fgets retains it).
      if (line.getc(line.len() - 1) == "\n")
        line = line.substr(0, line.len() - 2);
      if (line.len() == 0) continue;
      parsed = sos_parse_chart_event_jsonl(line, evt);
      if (parsed) begin
        events.push_back(evt);
      end else begin
        `uvm_warning("SOS-08-F",
          $sformatf("sos_load_chart_event_jsonl: skipping malformed line %0d: %s",
            line_no, line))
      end
    end
    $fclose(fh);
  endtask
"""


def _emit_baseline_seq_item() -> str:
    """Emit the universal sos_seq_item baseline transaction class
    (PCDN-SOS-08-F-003 resolved — universal discriminated union)."""
    return """  // -------------------------------------------------------------------------
  // sos_event_family_e — discriminated-union tag per §5.3 + §6.2
  // -------------------------------------------------------------------------
  typedef enum {
    SOS_FAMILY_TASK,
    SOS_FAMILY_SEM,
    SOS_FAMILY_QUEUE,
    SOS_FAMILY_TIMER,
    SOS_FAMILY_EVENT,
    SOS_FAMILY_TICK
  } sos_event_family_e;

  // -------------------------------------------------------------------------
  // sos_chart_event_s — vector-IR row shape (consumed by sequence body())
  // -------------------------------------------------------------------------
  //
  // Per SOS-08-F §6.4 the per-family sequence's body() iterates a queue
  // of `sos_chart_event_s` rows loaded from the chart's bounded-
  // reachability JSONL. The fields below mirror the JSONL keys 1:1.
  typedef struct {
    int    event_id;       // chart-vocabulary event index within family
    bit [63:0] payload_data;
    string chart_state;    // chart-state name where this event originates
    int    transition_id;  // chart transition that produced this event
    int    invariant_id;   // optional chart invariant tag (0 if unused)
  } sos_chart_event_s;

  // -------------------------------------------------------------------------
  // sos_seq_item — baseline UVM transaction class (per §6.2)
  // -------------------------------------------------------------------------
  //
  // INV-S-HDL-F-3 (chart-vocabulary traceability survives UVM boundary):
  // every sos_seq_item carries chart_state / transition_id /
  // invariant_id — populated by the per-family sequence's body() task,
  // surfaced by the customer's scoreboard / monitor / assertion handler
  // in the chart-vocabulary failure-message format per §6.6.
  class sos_seq_item extends uvm_sequence_item;

    rand sos_event_family_e family;
    rand int                event_id;
    rand bit [63:0]         payload_data;
    rand string             chart_state;
    rand int                transition_id;
    rand int                invariant_id;

    `uvm_object_utils_begin(sos_seq_item)
      `uvm_field_enum(sos_event_family_e, family, UVM_ALL_ON)
      `uvm_field_int(event_id, UVM_ALL_ON)
      `uvm_field_int(payload_data, UVM_ALL_ON)
      `uvm_field_string(chart_state, UVM_ALL_ON)
      `uvm_field_int(transition_id, UVM_ALL_ON)
      `uvm_field_int(invariant_id, UVM_ALL_ON)
    `uvm_object_utils_end

    function new(string name = "sos_seq_item");
      super.new(name);
    endfunction

  endclass : sos_seq_item
"""


def _emit_package(chart_name: str) -> str:
    """Emit the consolidated sos_uvm_seq_pkg.sv per §5.7.

    Single SystemVerilog package containing the discriminated-union enum,
    the chart-event struct, the baseline sos_seq_item, and one per-
    family sequence subclass for each of the six families.
    """
    families = "\n".join(_emit_per_family_sequence(f)
                         for f in CHART_EVENT_FAMILIES)
    return _SV_HEADER_PREFIX + f"""//
// SystemVerilog package: sos_uvm_seq_pkg
//
// Per SOS-08-F §5.7 + PCDN-SOS-08-F-006: one consolidated package
// containing every per-family sequence subclass + the baseline
// transaction class. Customer imports with a single line:
//
//     import sos_uvm_seq_pkg::*;
//
// Per §5.5 + PCDN-SOS-08-F-004 the `uvm_object_utils` factory
// registrations live inside the package; customer does NOT need to
// register SOS classes manually. Customer MAY override via standard
// UVM `set_type_override_by_type` mechanics.
//
// Chart that authored this package: {chart_name}
//
package sos_uvm_seq_pkg;

  import uvm_pkg::*;
  `include "uvm_macros.svh"

{_emit_baseline_seq_item()}
{_emit_jsonl_parser()}
{families}
endpackage : sos_uvm_seq_pkg
"""


def _emit_header(chart_name: str) -> str:
    """Emit sos_uvm_seq_pkg.svh — typedef + enum exports for customer-driver
    consumption. The customer's driver `\\`include`s the header to get
    the discriminated-union type without pulling in the full sequence
    library."""
    return _SV_HEADER_PREFIX + f"""//
// Header file: sos_uvm_seq_pkg.svh
//
// Provides typedef + enum exports for customers whose driver
// implementation needs the discriminated-union types without
// importing the full sequence library (e.g. drivers compiled
// separately from sequences). Most customers import the package
// directly; this header exists for split-compilation environments.
//
// Chart: {chart_name}
//
`ifndef SOS_UVM_SEQ_PKG_SVH
`define SOS_UVM_SEQ_PKG_SVH

  // Discriminated-union family tag per §5.3 + §6.2.
  typedef enum {{
    SOS_FAMILY_TASK,
    SOS_FAMILY_SEM,
    SOS_FAMILY_QUEUE,
    SOS_FAMILY_TIMER,
    SOS_FAMILY_EVENT,
    SOS_FAMILY_TICK
  }} sos_event_family_e;

  // Vector-IR row shape consumed by per-family sequences per §6.4.
  typedef struct {{
    int        event_id;
    bit [63:0] payload_data;
    string     chart_state;
    int        transition_id;
    int        invariant_id;
  }} sos_chart_event_s;

`endif // SOS_UVM_SEQ_PKG_SVH
"""


def _emit_integration_example(chart_name: str) -> str:
    """Emit sos_uvm_integration_example.sv — informative worked example
    per §6.5 five-step customer-integration contract. Demonstrates how
    a customer wires SOS sequences into their existing UVM env. Not
    part of any test artifact — documentation only."""
    return _SV_HEADER_PREFIX + f"""//
// Integration example: sos_uvm_integration_example.sv
//
// INFORMATIVE — this file is not part of the customer's compiled test
// scaffolding. It documents the five-step customer-integration contract
// from SOS-08-F §6.5 in working code form:
//
//   1. Package import (one line).
//   2. Sequencer typedef (one line).
//   3. Driver implementation (customer-owned; signal-level activity).
//   4. Sequence start (test class wires vector path + invokes start()).
//   5. Failure handling (scoreboard / monitor catches chart vocabulary).
//
// Customer adapts the shape below to their house env / driver / test
// conventions. The five extension points are the entire integration
// surface (per §6.5); everything outside those points is customer-
// owned per INV-S-HDL-F-2.
//
// Chart: {chart_name}
//

// 1. Package import.
import sos_uvm_seq_pkg::*;

// 2. Sequencer typedef. Customer instantiates this in their env.
typedef uvm_sequencer #(sos_seq_item) example_sequencer_t;

// 3. Driver. Customer-owned. The driver below is a SKELETON — the
//    customer fills in the DUT-pin-level signal activity per their
//    house protocol. Per INV-S-HDL-F-2 the driver class lives in the
//    customer's repository, not in SOS.
class example_driver extends uvm_driver #(sos_seq_item);
  `uvm_component_utils(example_driver)

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  virtual task run_phase(uvm_phase phase);
    sos_seq_item tx;
    forever begin
      seq_item_port.get_next_item(tx);
      // INFORMATIVE: branch on tx.family and translate to DUT pins.
      case (tx.family)
        SOS_FAMILY_TASK:  /* customer: drive task syscall pins */ ;
        SOS_FAMILY_SEM:   /* customer: drive semaphore pins  */ ;
        SOS_FAMILY_QUEUE: /* customer: drive queue pins      */ ;
        SOS_FAMILY_TIMER: /* customer: drive timer pins      */ ;
        SOS_FAMILY_EVENT: /* customer: drive event pins      */ ;
        SOS_FAMILY_TICK:  /* customer: advance simulated tick*/ ;
        default: `uvm_error(get_full_name(),
                            $sformatf("[SOS-SEQ] state=%s transition=%0d invariant=%0d family=%s event=%0d: unknown family",
                                      tx.chart_state, tx.transition_id,
                                      tx.invariant_id, tx.family.name(),
                                      tx.event_id))
      endcase
      seq_item_port.item_done();
    end
  endtask

endclass : example_driver

// 4. Test class. Customer authors this. Selects which SOS sequence to
//    run, wires the chart's vector-IR path, starts the sequence
//    against the env's sequencer.
class example_test extends uvm_test;
  `uvm_component_utils(example_test)

  example_sequencer_t sequencer;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  virtual task run_phase(uvm_phase phase);
    sos_sem_sequence seq;
    phase.raise_objection(this);
    seq = sos_sem_sequence::type_id::create("seq");
    // Customer wires the chart's bounded-reachability JSONL path here.
    seq.vector_path = "vectors/sem_chart_bound.jsonl";
    seq.start(sequencer);
    phase.drop_objection(this);
  endtask

endclass : example_test

// 5. Failure handling — customer's scoreboard / monitor catches
//    `sos_seq_item` instances via analysis ports. Each item retains
//    its chart_state / transition_id / invariant_id; customer's
//    failure-formatting surface uses those fields per §6.6:
//
//       [SOS-SEQ] state=<tx.chart_state> transition=<tx.transition_id>
//                 invariant=<tx.invariant_id> family=<tx.family>
//                 event=<tx.event_id>: <customer-detail>
//
//    This satisfies INV-SOS-H + INV-S-HDL-5 + INV-S-HDL-F-3 — chart
//    vocabulary survives the UVM boundary.
"""


# ---------------------------------------------------------------------------
# Invariant audit (INV-S-HDL-F-1 / -3 / -4)
# ---------------------------------------------------------------------------


_INV_F1_FORBIDDEN_BASE_CLASSES: tuple[str, ...] = (
    # Per INV-S-HDL-F-1 / §5.1 exclusion list. The walker MUST NOT
    # emit any class extending any of these base classes. The
    # `uvm_sequence`, `uvm_sequence_item`, and `uvm_object_utils`
    # forms are allowed (they ARE what SOS-08-F emits).
    "uvm_env",
    "uvm_agent",
    "uvm_sequencer",
    "uvm_driver",
    "uvm_monitor",
    "uvm_scoreboard",
    "uvm_test",
)

_INV_F1_FORBIDDEN_CALLS: tuple[str, ...] = (
    # uvm_config_db writes are explicitly forbidden in the emitted
    # sequence library per §5.1 (env configuration is customer-owned).
    "uvm_config_db",
)

_INV_F4_PATTERNS: tuple[tuple[str, str], ...] = (
    # INV-S-HDL-F-4: no SVA emission.
    (r"\bassert\s+property\b", "inline assert property"),
    (r"^\s*bind\s+\w+", "SystemVerilog bind directive"),
)


def _audit_emitted_file(filename: str, source: str) -> list[str]:
    """Scan ``source`` for INV-S-HDL-F-1 / -3 / -4 violations.

    The integration example file (sos_uvm_integration_example.sv) is
    INFORMATIVE per §6 — it deliberately authors a `uvm_driver`
    subclass to demonstrate the customer-side shape. Its purpose is to
    show what the customer authors, not what SOS emits as a normative
    artifact. Per the spec it is documentation, not a test artifact;
    the audit accepts the demonstrative `uvm_driver` / `uvm_test`
    subclass inside the example file but flags any of the forbidden
    base classes anywhere else.

    Returns the list of human-readable violations (empty if clean).
    """
    is_example = filename.endswith("sos_uvm_integration_example.sv")
    violations: list[str] = []

    # Strip line comments to avoid false positives on spec-prose
    # mentions like "// INV-S-HDL-F-1: no uvm_env emission".
    scanned = re.sub(r"//.*$", "", source, flags=re.MULTILINE)

    if not is_example:
        for base in _INV_F1_FORBIDDEN_BASE_CLASSES:
            # Match `extends <base>` (whitespace-tolerant).
            if re.search(rf"\bextends\s+{re.escape(base)}\b", scanned):
                violations.append(
                    f"INV-S-HDL-F-1 violation: `extends {base}`"
                )
        for call in _INV_F1_FORBIDDEN_CALLS:
            if re.search(rf"\b{re.escape(call)}\s*[#:]", scanned):
                violations.append(
                    f"INV-S-HDL-F-1 violation: {call}::"
                )

    for pat, label in _INV_F4_PATTERNS:
        if re.search(pat, scanned, flags=re.MULTILINE):
            violations.append(f"INV-S-HDL-F-4 violation: {label}")

    return violations


def _audit_metadata_fields(package_source: str) -> list[str]:
    """INV-S-HDL-F-3: the sos_seq_item baseline MUST carry the three
    chart-vocabulary metadata fields. Scan the package source for the
    field declarations."""
    required_fields = ("chart_state", "transition_id", "invariant_id")
    violations: list[str] = []
    for field in required_fields:
        if field not in package_source:
            violations.append(
                f"INV-S-HDL-F-3 violation: sos_seq_item missing "
                f"chart-vocabulary field `{field}`"
            )
    return violations


def _audit_all(files: dict[str, str]) -> None:
    """Run the audit across emitted files; raise on any violation."""
    accumulated: list[str] = []
    for filename, source in files.items():
        hits = _audit_emitted_file(filename, source)
        if hits:
            accumulated.append(f"{filename}: " + "; ".join(hits))

    # INV-S-HDL-F-3 metadata-field check on the package file.
    pkg_keys = [k for k in files if k.endswith("sos_uvm_seq_pkg.sv")]
    if pkg_keys:
        meta_hits = _audit_metadata_fields(files[pkg_keys[0]])
        if meta_hits:
            accumulated.append(f"{pkg_keys[0]}: " + "; ".join(meta_hits))

    if accumulated:
        raise InvariantAuditError(
            "SOS-08-F wave-1 invariant audit failed:\n  "
            + "\n  ".join(accumulated)
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def render_target(chart_ir: Any, config: Any = None) -> dict[str, str]:
    """Emit the SOS-08-F wave-1 UVM sequence artifact set for a chart.

    Wave-1 contract:
      * Single artifact set per chart — three files under
        ``uvm/<chart>/``:
          - ``sos_uvm_seq_pkg.sv``  (consolidated SV package: baseline
            ``sos_seq_item`` + six per-family ``uvm_sequence``
            subclasses + ``sos_event_family_e`` enum +
            ``sos_chart_event_s`` struct)
          - ``sos_uvm_seq_pkg.svh`` (header with typedefs/enums for
            split-compilation drivers)
          - ``sos_uvm_integration_example.sv`` (informative worked
            example of the §6.5 five-step customer integration)

    Args:
        chart_ir: raw scjson dict (``ChartAst.raw_scjson``). Used for
            chart-name extraction; SOS-08-F is chart-agnostic in the
            emission shape (the same library serves any chart).
        config: optional dict / dataclass. Wave-1 consumes:
            - ``chart_name`` (str): chart identifier for the
              ``uvm/<chart>/`` directory prefix.

    Returns:
        dict mapping output filename to emitted file source.

    Raises:
        UnsupportedChartError when ``chart_ir`` is not a dict.
        InvariantAuditError when the emitted text violates
        INV-S-HDL-F-1 / -3 / -4 (signals an internal walker bug).
    """
    if not isinstance(chart_ir, dict):
        raise UnsupportedChartError(
            "SOS-08-F wave-1 render_target expects the raw scjson dict, "
            f"not {type(chart_ir).__name__}. The main.py dispatcher "
            "needs to pass the parsed scjson AST "
            "(ChartAst.raw_scjson)."
        )

    if isinstance(config, dict):
        chart_name = config.get("chart_name") or "chart"
    else:
        chart_name = getattr(config, "chart_name", None) or "chart"

    base = _normalise_chart_name(chart_name)
    files: dict[str, str] = {
        f"uvm/{base}/sos_uvm_seq_pkg.sv":  _emit_package(chart_name),
        f"uvm/{base}/sos_uvm_seq_pkg.svh": _emit_header(chart_name),
        f"uvm/{base}/sos_uvm_integration_example.sv":
            _emit_integration_example(chart_name),
    }
    _audit_all(files)
    return files


# ---------------------------------------------------------------------------
# Public helpers used by tests
# ---------------------------------------------------------------------------


def sequence_class_name(family: str) -> str:
    """``sos_<family>_sequence`` — per-family sequence class name."""
    return f"sos_{family}_sequence"


def package_name() -> str:
    """``sos_uvm_seq_pkg`` — the consolidated package name (§5.7)."""
    return "sos_uvm_seq_pkg"


# ---------------------------------------------------------------------------
# Dev / debug entry
# ---------------------------------------------------------------------------


if __name__ == "__main__":  # pragma: no cover
    import sys
    from pathlib import Path

    here = Path(__file__).resolve().parent
    sys.path.insert(0, str(here))
    from loader import load_chart  # noqa: E402

    chart_path = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        here.parent.parent / "rtos_kernel.scxml"
    )
    ast = load_chart(chart_path)
    out = render_target(ast.raw_scjson, {"chart_name": chart_path.stem})
    for fname, content in out.items():
        sys.stdout.write(f"=== {fname} ===\n{content}\n")
