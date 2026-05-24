r"""SCXML chart → SystemVerilog testbench emitter (SOS-08-E).

Wave-1 scaffold per ``SOS-08-E-CONCEPTS.md`` §6 (emission contract) and
§15 (2026-05-23 ratification). Emits a class-based, self-checking,
constrained-random-free, UVM-free SV testbench per chart region. Wave-1
covers single-region charts; the per-region split for parallel charts is
wave-2 work.

@spec  SOS-08-E-CONCEPTS.md §5.1 (class-based, self-checking, no
       constrained-random, no UVM)
@spec  SOS-08-E-CONCEPTS.md §5.2 (SVA bind file mirror — byte-identical
       to SOS-08-D's emit; this module imports SOS-08-D's
       ``transliterate_sva_bind.render_target`` and re-keys the
       resulting filenames under the SV testbench directory)
@spec  SOS-08-E-CONCEPTS.md §5.3 (target simulator set — Questa,
       Riviera, VCS, Xcelium, Verilator)
@spec  SOS-08-E-CONCEPTS.md §5.4 (JSONL trace consumption via
       ``$fopen`` / ``$fgets``; JSON invariants delivered as bound SVA
       properties so the SV testbench does not parse them directly)
@spec  SOS-08-E-CONCEPTS.md §5.5 (chart-vocabulary failure messages)
@spec  SOS-08-E-CONCEPTS.md §6.1 (stimulus driver class contract)
@spec  SOS-08-E-CONCEPTS.md §6.2 (response checker class contract)
@spec  SOS-08-E-CONCEPTS.md §6.3 (top-level testbench module contract)
@spec  SOS-08-E-CONCEPTS.md §6.4 (build wrapper contract)
@spec  SOS-08-E-CONCEPTS.md §7 INV-S-HDL-E-1 (no constrained-random)
@spec  SOS-08-E-CONCEPTS.md §7 INV-S-HDL-E-2 (no UVM imports)
@spec  SOS-08-E-CONCEPTS.md §7 INV-S-HDL-E-3 (SVA only via bind files;
       no inline `assert property` in driver/checker/testbench)
@spec  SOS-08-E-CONCEPTS.md §7 INV-S-HDL-E-4 (chart-vocabulary failure
       messages)
@spec  SOS-08-E-CONCEPTS.md §7 INV-S-HDL-E-5 (per-simulator build
       wrapper — wave-1 ships Verilator Makefile + Questa/Riviera .do
       reference; VCS/Xcelium wrappers wave-2)
@spec  SOS-08-E-CONCEPTS.md §7 INV-S-HDL-E-6 (Verilator-subset
       compliance declared not assumed — emitted SV uses classes +
       virtual interfaces + file I/O which Verilator supports; SVA
       properties live in the bind file SOS-08-D owns)
@spec  SOS-07-CONCEPTS.md INV-SOS-A..H (cross-phase invariants — cited)
@spec  SOS-08-CONCEPTS.md INV-S-HDL-1..5 (cross-sub-phase invariants —
       cited; INV-S-HDL-5 = chart-vocabulary failure messages,
       load-bearing for `[FAIL]` prefix here)

# Wave-1 scope

* Single-region chart → eight files (all under ``tb/sv/<chart>/``):
    - ``tb/sv/<chart>/tb_<chart>.sv`` — top-level testbench module.
    - ``tb/sv/<chart>/sos_driver_<chart>.sv`` — stimulus driver class.
    - ``tb/sv/<chart>/sos_checker_<chart>.sv`` — response checker class.
    - ``tb/sv/<chart>/dut_if_<chart>.sv`` — virtual interface.
    - ``tb/sv/<chart>/<chart>_fsm_sva.sv`` — SVA assertion module
      (byte-identical to SOS-08-D emit; re-keyed under the SV testbench
      directory).
    - ``tb/sv/<chart>/<chart>_fsm_bind.sv`` — SVA bind directive
      (byte-identical to SOS-08-D emit).
    - ``tb/sv/<chart>/run_verilator.mk`` — Verilator build wrapper
      (the open-source-runnable wrapper; full CI verification target).
    - ``tb/sv/<chart>/run.do`` — Questa/Riviera build wrapper (the
      commercial-reference wrapper; smoke-tested but not full CI).

* Parallel charts are REJECTED at wave-1 with ``UnsupportedChartError``;
  per-region testbench split is wave-2 alongside the per-region SVA
  bind already deferred at SOS-08-D wave-1.

* VCS ``Makefile.sv``, Xcelium ``run_xrun.sh``, and the layered
  driver/checker hierarchy variant (PCDN-SOS-08-E-001 layered opt-in)
  are wave-2 scope; wave-1 ships the flat shape per the resolved
  recommendation.

# Integration contract

The codegen tool's CLI dispatcher invokes::

    from transliterate_hdl_sv_tb import render_target
    files = render_target(chart_ir, config)

``chart_ir`` is the raw scjson dict (``ChartAst.raw_scjson`` from the
loader). Output is a ``dict[filename, source]`` mapping output filename
(relative path, embedding the ``tb/sv/<chart>/`` prefix) to emitted file
source. The dispatcher writes each entry under the project's emit root.

# Invariant audit at emit time

Emitted text is post-pass scanned for INV-S-HDL-E-1..3 forbidden
constructs (``randomize``, ``constraint`` block opener, ``rand`` /
``randc`` property keyword, ``import uvm_pkg``, ``\`uvm_``, inline
``assert property`` in non-bind files). Any hit raises
``InvariantAuditError`` — the walker's contract is that emitted output
is conforming by construction, and the audit is belt-and-suspenders.

# Failure-message format (INV-S-HDL-E-4 + §5.5)

The response checker emits failures in chart vocabulary::

    [FAIL] vector V<n>: chart `<chart>` region `<region>` produced
           expected `<expected>` at cycle <cycle>; observed `<observed>`.

The format mirrors SOS-08-D's cocotb checker; INV-SOS-H + INV-S-HDL-5
+ INV-S-HDL-E-4 are upheld by the chart-vocabulary `[FAIL]` prefix and
the named chart region.
"""

from __future__ import annotations

import re
from typing import Any

# Reuse the SVA bind walker — same artifact, byte-identical per §5.2.
from transliterate_sva_bind import (  # noqa: E402
    UnsupportedChartError,
    render_target as _render_sva_bind,
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class InvariantAuditError(RuntimeError):
    """Emitted text violated INV-S-HDL-E-1..3 at the post-emit audit pass.

    The walker's contract is that emitted output is conforming by
    construction; this exception signals an internal bug, not a chart-
    author error.
    """


# ---------------------------------------------------------------------------
# Identifier sanitization (mirrors transliterate_sva_bind)
# ---------------------------------------------------------------------------


_SV_RESERVED: frozenset[str] = frozenset({
    "alias", "always", "always_comb", "always_ff", "always_latch", "and",
    "assert", "assign", "assume", "automatic", "before", "begin", "bind",
    "bins", "binsof", "bit", "break", "buf", "bufif0", "bufif1", "byte",
    "case", "casex", "casez", "cell", "chandle", "class", "clocking", "cmos",
    "config", "const", "constraint", "context", "continue", "cover",
    "covergroup", "coverpoint", "cross", "deassign", "default", "defparam",
    "design", "disable", "dist", "do", "edge", "else", "end", "endcase",
    "endclass", "endclocking", "endconfig", "endfunction", "endgenerate",
    "endgroup", "endinterface", "endmodule", "endpackage", "endprimitive",
    "endprogram", "endproperty", "endspecify", "endsequence", "endtable",
    "endtask", "enum", "event", "expect", "export", "extends", "extern",
    "final", "first_match", "for", "force", "foreach", "forever", "fork",
    "forkjoin", "function", "generate", "genvar", "highz0", "highz1", "if",
    "iff", "ifnone", "ignore_bins", "illegal_bins", "import", "incdir",
    "include", "initial", "inout", "input", "inside", "instance", "int",
    "integer", "interface", "intersect", "join", "join_any", "join_none",
    "large", "liblist", "library", "local", "localparam", "logic", "longint",
    "macromodule", "matches", "medium", "modport", "module", "nand",
    "negedge", "new", "nmos", "nor", "noshowcancelled", "not", "notif0",
    "notif1", "null", "or", "output", "package", "packed", "parameter",
    "pmos", "posedge", "primitive", "priority", "program", "property",
    "protected", "pull0", "pull1", "pulldown", "pullup",
    "pulsestyle_ondetect", "pulsestyle_onevent", "pure", "rand", "randc",
    "randcase", "randsequence", "rcmos", "real", "realtime", "ref", "reg",
    "release", "repeat", "return", "rnmos", "rpmos", "rtran", "rtranif0",
    "rtranif1", "scalared", "sequence", "shortint", "shortreal",
    "showcancelled", "signed", "small", "solve", "specify", "specparam",
    "static", "string", "strong0", "strong1", "struct", "super", "supply0",
    "supply1", "table", "tagged", "task", "this", "throughout", "time",
    "timeprecision", "timeunit", "tran", "tranif0", "tranif1", "tri", "tri0",
    "tri1", "triand", "trior", "trireg", "type", "typedef", "union",
    "unique", "unsigned", "use", "uwire", "var", "vectored", "virtual",
    "void", "wait", "wait_order", "wand", "weak0", "weak1", "while",
    "wildcard", "wire", "with", "within", "wor", "xnor", "xor",
})


def _sanitize_sv_identifier(name: str) -> str:
    """Lower-case, swap non-alphanumerics to underscore, and ward off
    SV reserved words by suffix.

    Mirrors ``transliterate_sva_bind._sanitize_sv_identifier`` so the SV
    testbench module names and the SVA bind module names collide on the
    same canonical form when they reference each other.
    """
    out = re.sub(r"[^A-Za-z0-9_]", "_", name.strip()).strip("_").lower()
    if not out:
        return "chart"
    if out[0].isdigit():
        out = f"_{out}"
    if out in _SV_RESERVED:
        out = f"{out}_id"
    return out


def _normalise_chart_name(chart_name: str | None) -> str:
    base = chart_name or "chart"
    return _sanitize_sv_identifier(base)


# ---------------------------------------------------------------------------
# Chart introspection (single-region wave-1)
# ---------------------------------------------------------------------------


def _chart_has_parallel(chart_ir: dict[str, Any]) -> bool:
    """Detect a top-level ``<parallel>`` region; wave-1 rejects these."""
    parallels = chart_ir.get("parallel") or []
    if parallels:
        return True
    for st in chart_ir.get("state") or []:
        if (st.get("parallel") or []):
            return True
    return False


def _collect_state_ids(chart_ir: dict[str, Any]) -> list[str]:
    """Walk ``<state>`` nodes in document order; return their IDs."""
    ids: list[str] = []
    for st in chart_ir.get("state") or []:
        sid = st.get("id")
        if isinstance(sid, str) and sid:
            ids.append(sid)
        # Recurse — nested states should appear after their parent in
        # document order for predictable encoding.
        for child in st.get("state") or []:
            csid = child.get("id")
            if isinstance(csid, str) and csid:
                ids.append(csid)
    return ids


def _collect_initial_state(chart_ir: dict[str, Any]) -> str | None:
    """The chart's ``initial`` attribute; falls back to the first state."""
    init = chart_ir.get("initial")
    if isinstance(init, str) and init:
        return init
    states = _collect_state_ids(chart_ir)
    return states[0] if states else None


# ---------------------------------------------------------------------------
# Module + class name conventions
# ---------------------------------------------------------------------------


def tb_module_name(chart_name: str) -> str:
    """``tb_<chart>`` — top-level testbench module name."""
    return f"tb_{_normalise_chart_name(chart_name)}"


def driver_class_name(chart_name: str) -> str:
    """``sos_driver_<chart>`` — stimulus driver class name."""
    return f"sos_driver_{_normalise_chart_name(chart_name)}"


def checker_class_name(chart_name: str) -> str:
    """``sos_checker_<chart>`` — response checker class name."""
    return f"sos_checker_{_normalise_chart_name(chart_name)}"


def virtual_if_name(chart_name: str) -> str:
    """``dut_if_<chart>`` — virtual interface name."""
    return f"dut_if_{_normalise_chart_name(chart_name)}"


def dut_module_name(chart_name: str) -> str:
    """``<chart>_fsm`` — DUT module name (chart-emitted FSM).

    Mirrors ``transliterate_sva_bind.dut_module_name`` so the testbench
    instantiates the same DUT module the SVA bind file binds to.
    """
    return f"{_normalise_chart_name(chart_name)}_fsm"


# ---------------------------------------------------------------------------
# Per-file emitters
# ---------------------------------------------------------------------------


_HEADER_PREFIX = """// SPDX-License-Identifier: MIT
// SOS-08-E wave-1 emitted artifact — DO NOT EDIT BY HAND.
//
// Generated by ``tools/sos-codegen/transliterate_hdl_sv_tb.py``.
//
// Spec references:
//   * SOS-08-E-CONCEPTS.md §5..§7 (emission contract + invariants)
//   * SOS-08-D-CONCEPTS.md  (SVA bind file artifact — byte-identical
//                             mirror per SOS-08-E §5.2)
//   * SOS-07-CONCEPTS.md   §6 INV-SOS-A..H (cross-phase invariants)
//   * SOS-08-CONCEPTS.md   §7 INV-S-HDL-1..5 (cross-sub-phase
//                            invariants; INV-S-HDL-5 = chart-vocabulary
//                            failure messages — load-bearing here)
//
// Invariants upheld by this artifact:
//   * INV-S-HDL-E-1: no `randomize` / `constraint` / `rand` / `randc`.
//   * INV-S-HDL-E-2: no UVM imports or macros.
//   * INV-S-HDL-E-3: no inline `assert property` (all SVA via bind).
//   * INV-S-HDL-E-4: failure messages in chart vocabulary.
//
"""


def _emit_virtual_interface(chart_name: str) -> str:
    """``dut_if_<chart>.sv`` — virtual interface for driver/checker.

    Wave-1: ports are ``clk``, ``rst``, ``current_state`` (DUT state
    output observable to the checker), plus a single ``event_in``
    placeholder input wide enough to carry the chart's stimulus events.
    Per PCDN-SOS-08-E-001 (flat shape) the interface is intentionally
    minimal; wave-2 widens it once the chart-event-port shape ratifies
    in SOS-08-C wave-3 events.
    """
    iface = virtual_if_name(chart_name)
    return _HEADER_PREFIX + f"""//
// Virtual interface for the {chart_name} chart testbench.
//
// The driver class drives ``clk_en``, ``rst``, and ``event_in``; the
// checker class observes ``current_state`` (the DUT's chart-FSM state
// output). All routing goes through this interface so driver/checker
// classes do not couple to the DUT module directly.

`ifndef DUT_IF_{chart_name.upper().replace('-', '_')}_SV
`define DUT_IF_{chart_name.upper().replace('-', '_')}_SV

interface {iface} #(
    parameter int N_STATES = 1,
    parameter int EVENT_W  = 8
) (
    input  logic clk
);

    // Drives (set by driver).
    logic                rst;
    logic                clk_en;
    logic [EVENT_W-1:0]  event_in;

    // Observables (read by checker).
    logic [N_STATES-1:0] current_state;

    // Driver modport — drives stimulus.
    modport driver_mp (
        output rst,
        output clk_en,
        output event_in,
        input  current_state,
        input  clk
    );

    // Checker modport — observes responses only.
    modport checker_mp (
        input  rst,
        input  clk_en,
        input  event_in,
        input  current_state,
        input  clk
    );

endinterface

`endif // DUT_IF_{chart_name.upper().replace('-', '_')}_SV
"""


def _emit_driver_class(chart_name: str) -> str:
    """``sos_driver_<chart>.sv`` — stimulus driver class.

    Consumes the JSONL trace file via ``$fopen`` + ``$fgets``, decodes
    each line's event-poke map, drives ``vif.event_in``, and waits the
    prescribed number of clock cycles between events. Per §6.1 the
    driver SHALL NOT inspect DUT outputs.
    """
    cls = driver_class_name(chart_name)
    iface = virtual_if_name(chart_name)
    return _HEADER_PREFIX + f"""//
// Stimulus driver class for the {chart_name} chart testbench.
//
// Reads JSONL trace events from ``trace_path`` and drives them onto
// the virtual interface. Per SOS-08-E §6.1 + INV-S-HDL-E-1 the driver
// is constrained-random-free — all stimulus comes from the trace file,
// which is the chart's bounded-reachability vector replay.
//
// Per INV-S-HDL-E-3 the driver does NOT inline any ``assert property``;
// property checking lives exclusively in the bound SVA module.

class {cls};

    virtual {iface}.driver_mp vif;
    string                    trace_path;
    int                       vector_idx;

    function new(virtual {iface}.driver_mp vif, string trace_path);
        this.vif        = vif;
        this.trace_path = trace_path;
        this.vector_idx = 0;
    endfunction

    // Top-level run — opens the trace file, replays each event.
    task run();
        int    fh;
        string line;
        int    rc;

        fh = $fopen(trace_path, "r");
        if (fh == 0) begin
            $display("[FATAL] sos_driver: cannot open trace `%s`",
                     trace_path);
            $finish(2);
        end

        // Pre-test reset assertion (chart-FSM convention).
        vif.rst     = 1'b1;
        vif.clk_en  = 1'b0;
        vif.event_in = '0;
        repeat (4) @(posedge vif.clk);
        vif.rst    = 1'b0;
        vif.clk_en = 1'b1;
        @(posedge vif.clk);

        while (!$feof(fh)) begin
            rc = $fgets(line, fh);
            if (rc == 0) break;
            // SOS-08-E §5.4: JSONL trace; one event per line. Wave-1
            // accepts a minimal `{{"event": <int>, "cycles": <int>}}`
            // shape — full SOS-03 vector schema parse lands in wave-2.
            drive_one_event(line);
        end

        $fclose(fh);

        // Settle period — wave-1 fixed at 8 cycles; PCDN-SOS-08-E-???
        // (wave-2) configurable settle.
        repeat (8) @(posedge vif.clk);
    endtask

    // Per-event drive — wave-1 stub form. Decodes the minimal JSONL
    // shape; wave-2 swaps in a full JSON-Lines parser per §5.4.
    task drive_one_event(string line);
        int event_code;
        int cycles_wait;
        int idx;
        int parsed;

        event_code  = 0;
        cycles_wait = 1;

        // Extract `"event": N` and `"cycles": N` from the line. Wave-1
        // uses simple substring matching; INV-S-HDL-E-1 forbids
        // randomize() so we cannot use SystemVerilog's class-based
        // randomization helpers — manual parse is the LCD path.
        parsed = parse_int_field(line, "event", event_code);
        parsed = parse_int_field(line, "cycles", cycles_wait);
        if (cycles_wait <= 0) cycles_wait = 1;

        vif.event_in = event_code[7:0];
        @(posedge vif.clk);
        vif.event_in = '0;
        repeat (cycles_wait - 1) @(posedge vif.clk);

        vector_idx = vector_idx + 1;
        $display("[DRIVE] V%0d: event=%0d cycles=%0d  // chart=`{chart_name}`",
                 vector_idx, event_code, cycles_wait);
    endtask

    // Tiny JSON-Lines integer-field extractor — wave-1 LCD form.
    // Returns 1 on hit, 0 on miss. Wave-2 swaps in a full JSON parser.
    function int parse_int_field(string line, string key,
                                 inout int value);
        int klen;
        int slen;
        int i;
        int j;
        int sign;
        byte ch;
        int  hit;
        int  acc;
        slen = line.len();
        klen = key.len();
        hit  = 0;
        // Find `"<key>"` in the line.
        for (i = 0; i + klen + 2 <= slen; i++) begin
            if (line.getc(i) == "\\"") begin
                // Compare key.
                hit = 1;
                for (j = 0; j < klen; j++) begin
                    if (line.getc(i + 1 + j) != key.getc(j)) begin
                        hit = 0;
                        break;
                    end
                end
                if (hit && line.getc(i + 1 + klen) == "\\"") begin
                    // Skip whitespace + colon.
                    j = i + 2 + klen;
                    while (j < slen &&
                          (line.getc(j) == " " || line.getc(j) == ":" ||
                           line.getc(j) == 9)) j++;
                    sign = 1;
                    if (j < slen && line.getc(j) == "-") begin
                        sign = -1;
                        j++;
                    end
                    acc = 0;
                    while (j < slen &&
                          line.getc(j) >= "0" && line.getc(j) <= "9") begin
                        ch = line.getc(j);
                        acc = acc * 10 + (ch - 8'h30);
                        j++;
                    end
                    value = sign * acc;
                    return 1;
                end
                hit = 0;
            end
        end
        return 0;
    endfunction

endclass
"""


def _emit_checker_class(chart_name: str) -> str:
    """``sos_checker_<chart>.sv`` — response checker class.

    Observes the DUT's ``current_state`` through the virtual interface
    and compares against the trace's ``expected_state`` field. Failures
    render in chart vocabulary per §5.5 + INV-S-HDL-E-4.
    """
    cls = checker_class_name(chart_name)
    iface = virtual_if_name(chart_name)
    return _HEADER_PREFIX + f"""//
// Response checker class for the {chart_name} chart testbench.
//
// Observes the DUT's ``current_state`` output via the virtual interface
// and compares against ``expected_state`` from the trace JSONL. Per
// SOS-08-E §5.5 + INV-S-HDL-E-4 every failure renders in chart
// vocabulary with the failing vector index, chart region, and
// observed-vs-expected values.
//
// Per INV-S-HDL-E-3 the checker does NOT inline any ``assert property``;
// property checking is in the SOS-08-D-emitted SVA bind file.

class {cls};

    virtual {iface}.checker_mp vif;
    string                     trace_path;
    int                        fail_count;
    int                        vector_idx;

    function new(virtual {iface}.checker_mp vif, string trace_path);
        this.vif        = vif;
        this.trace_path = trace_path;
        this.fail_count = 0;
        this.vector_idx = 0;
    endfunction

    task run();
        int    fh;
        string line;
        int    rc;
        int    expected_state;
        int    cycles_wait;
        int    parsed;

        fh = $fopen(trace_path, "r");
        if (fh == 0) begin
            $display("[FATAL] {cls}: cannot open trace `%s`",
                     trace_path);
            $finish(2);
        end

        // Wait for reset deassertion (driver handles reset; checker
        // starts comparing once clk_en is high).
        @(posedge vif.clk_en);
        @(posedge vif.clk);

        while (!$feof(fh)) begin
            rc = $fgets(line, fh);
            if (rc == 0) break;

            expected_state = -1;
            cycles_wait    = 1;
            parsed = parse_int_field(line, "expected_state",
                                     expected_state);
            parsed = parse_int_field(line, "cycles", cycles_wait);
            if (cycles_wait <= 0) cycles_wait = 1;

            // Wait the prescribed cycles before sampling.
            repeat (cycles_wait) @(posedge vif.clk);

            vector_idx = vector_idx + 1;

            if (expected_state >= 0) begin
                if (vif.current_state != expected_state[vif.current_state'left:0]) begin
                    fail_count = fail_count + 1;
                    // INV-S-HDL-E-4: chart-vocabulary failure message.
                    $display(
                        "[FAIL] vector V%0d: chart `{chart_name}` produced expected_state=%0d at cycle %0t; observed current_state=%0b.",
                        vector_idx, expected_state, $time,
                        vif.current_state
                    );
                end
            end
        end

        $fclose(fh);
    endtask

    function int get_fail_count();
        return fail_count;
    endfunction

    // Same minimal JSON-Lines integer-field extractor as the driver.
    function int parse_int_field(string line, string key,
                                 inout int value);
        int klen;
        int slen;
        int i;
        int j;
        int sign;
        byte ch;
        int  hit;
        int  acc;
        slen = line.len();
        klen = key.len();
        hit  = 0;
        for (i = 0; i + klen + 2 <= slen; i++) begin
            if (line.getc(i) == "\\"") begin
                hit = 1;
                for (j = 0; j < klen; j++) begin
                    if (line.getc(i + 1 + j) != key.getc(j)) begin
                        hit = 0;
                        break;
                    end
                end
                if (hit && line.getc(i + 1 + klen) == "\\"") begin
                    j = i + 2 + klen;
                    while (j < slen &&
                          (line.getc(j) == " " || line.getc(j) == ":" ||
                           line.getc(j) == 9)) j++;
                    sign = 1;
                    if (j < slen && line.getc(j) == "-") begin
                        sign = -1;
                        j++;
                    end
                    acc = 0;
                    while (j < slen &&
                          line.getc(j) >= "0" && line.getc(j) <= "9") begin
                        ch = line.getc(j);
                        acc = acc * 10 + (ch - 8'h30);
                        j++;
                    end
                    value = sign * acc;
                    return 1;
                end
                hit = 0;
            end
        end
        return 0;
    endfunction

endclass
"""


def _emit_top_module(chart_name: str, n_states: int) -> str:
    """``tb_<chart>.sv`` — top-level testbench module.

    Instantiates the DUT (``<chart>_fsm``), the virtual interface, the
    driver, the checker, drives clock, forks driver + checker, and
    emits the final [PASS]/[FAIL] summary line per §6.3.
    """
    top = tb_module_name(chart_name)
    dut = dut_module_name(chart_name)
    drv = driver_class_name(chart_name)
    chk = checker_class_name(chart_name)
    iface = virtual_if_name(chart_name)
    base = _normalise_chart_name(chart_name)
    return _HEADER_PREFIX + f"""//
// Top-level testbench module for the {chart_name} chart.
//
// Per SOS-08-E §6.3:
//   1. Instantiates the DUT (``{dut}``).
//   2. Instantiates the virtual interface (``{iface}``).
//   3. Drives clock and reset (reset is driver-owned per the modport).
//   4. Instantiates driver + checker classes.
//   5. Fork-join runs them concurrently.
//   6. On driver completion + settle: emits ``[PASS]`` or ``[FAIL]``
//      and calls ``$finish``.
//
// The SVA bind file (``{base}_fsm_bind.sv``) is `include-d so its
// ``bind`` directive attaches the assertion module to the DUT instance.

`timescale 1ns/1ps

`include "dut_if_{base}.sv"
`include "sos_driver_{base}.sv"
`include "sos_checker_{base}.sv"

module {top};

    localparam int N_STATES   = {max(n_states, 1)};
    localparam int CLK_PERIOD = 10;  // 100 MHz wave-1 default.

    logic clk;
    initial clk = 1'b0;
    always #(CLK_PERIOD/2) clk = ~clk;

    {iface} #(.N_STATES(N_STATES), .EVENT_W(8)) vif (.clk(clk));

    // Reset comes from the driver modport; here we just expose the
    // chart-FSM observables for the checker.
    logic                rst_q;
    logic                clk_en_q;
    logic [7:0]          event_in_q;
    logic [N_STATES-1:0] current_state_q;

    always_comb begin
        rst_q      = vif.rst;
        clk_en_q   = vif.clk_en;
        event_in_q = vif.event_in;
        vif.current_state = current_state_q;
    end

    {dut} #(.N_STATES(N_STATES)) dut_i (
        .clk           (clk),
        .rst           (rst_q),
        .clk_en        (clk_en_q),
        .event_in      (event_in_q),
        .current_state (current_state_q)
    );

    {drv} driver;
    {chk} checker;

    initial begin
        string trace_path;
        trace_path = "vectors/{base}.jsonl";

        // SOS-08-E §5.4 + §6.1: driver consumes the JSONL trace.
        driver  = new(vif.driver_mp,  trace_path);
        checker = new(vif.checker_mp, trace_path);

        fork
            driver.run();
            checker.run();
        join

        // Summary — chart-vocabulary per INV-S-HDL-E-4.
        if (checker.get_fail_count() == 0) begin
            $display("[PASS] chart `{chart_name}` testbench: all vectors green.");
            $finish(0);
        end else begin
            $display("[FAIL count=%0d] chart `{chart_name}` testbench.",
                     checker.get_fail_count());
            $finish(1);
        end
    end

endmodule
"""


def _emit_verilator_makefile(chart_name: str) -> str:
    """``run_verilator.mk`` — Verilator build wrapper.

    Per §6.4 + INV-S-HDL-E-5 + PCDN-SOS-08-E-005. Wave-1 ships this
    wrapper as the open-source-runnable verification target; the
    commercial wrappers (Questa, VCS, Xcelium, Riviera) are wave-2
    enrichment scope.
    """
    base = _normalise_chart_name(chart_name)
    top = tb_module_name(chart_name)
    return f"""# SPDX-License-Identifier: MIT
# SOS-08-E wave-1 emitted artifact — DO NOT EDIT BY HAND.
#
# Verilator build wrapper for the {chart_name} chart testbench.
#
# Per SOS-08-E §5.3 + §6.4 + INV-S-HDL-E-5 + INV-S-HDL-E-6:
#   * Verilator is the open-source-runnable target.
#   * --assert enables the SVA subset Verilator supports.
#   * Unsupported SVA constructs (eventually, broad ##[a:b]) emit a
#     deferred-failure stub per INV-S-HDL-E-6; commercial simulators
#     run the full property set.

TOP := {top}

# Source files in dependency order: vif -> classes -> top + bind.
SOURCES := \\
    dut_if_{base}.sv \\
    sos_driver_{base}.sv \\
    sos_checker_{base}.sv \\
    {base}_fsm_sva.sv \\
    {base}_fsm_bind.sv \\
    tb_{base}.sv

# DUT module — chart-emitted FSM. The chart-FSM module is generated by
# the SOS-08-C walker (transliterate_hdl_sv.py) and lands at the
# project's chart-FSM emit path; this Makefile assumes the file is
# made available alongside the testbench at run time.
DUT_SOURCE ?= {base}_fsm.sv

VERILATOR ?= verilator
VFLAGS    := --binary --assert --timing -Wall -Wno-fatal \\
             --top-module $(TOP)

.PHONY: all run clean

all: run

run:
\t$(VERILATOR) $(VFLAGS) $(DUT_SOURCE) $(SOURCES)
\t./obj_dir/V$(TOP)

clean:
\trm -rf obj_dir
"""


def _emit_questa_do(chart_name: str) -> str:
    """``run.do`` — Questa-specific build wrapper.

    Per PCDN-SOS-08-E-005 (resolved 2026-05-23) separate wrappers per
    simulator. Wave-2 split this from the shared Questa/Riviera form
    (wave-1) — Riviera now has its own ``run_riviera.tcl`` wrapper
    with Riviera-specific `asim` / `arun` idioms.
    """
    base = _normalise_chart_name(chart_name)
    top = tb_module_name(chart_name)
    return f"""# SOS-08-E wave-2 emitted artifact — DO NOT EDIT BY HAND.
#
# Questa build wrapper for the {chart_name} chart testbench.
#
# Per SOS-08-E §5.3 + §6.4 + PCDN-SOS-08-E-005 separate wrappers per
# simulator (wave-2 split this from the shared Questa/Riviera form).

# Usage:
#   vsim -c -do run.do                 # batch mode
#   vsim    -do "run.do; run -all"     # GUI mode

vlib work
vmap work work

vlog -sv \\
    dut_if_{base}.sv \\
    sos_driver_{base}.sv \\
    sos_checker_{base}.sv \\
    {base}_fsm_sva.sv \\
    {base}_fsm_bind.sv \\
    tb_{base}.sv \\
    {base}_fsm.sv

vsim -c -voptargs="+acc" -assertdebug work.{top}
run -all
quit -code 0
"""


def _emit_vcs_makefile(chart_name: str) -> str:
    """``Makefile.sv`` — Synopsys VCS build wrapper.

    Per PCDN-SOS-08-E-005 separate wrappers per simulator. VCS uses
    `vcs` (compile) + `./simv` (run) with `+define`-style command-line
    flags rather than do-file conventions. The `-sverilog -assert
    enable_diag` flag-set is the canonical SVA-aware VCS invocation.
    """
    base = _normalise_chart_name(chart_name)
    top = tb_module_name(chart_name)
    return f"""# SOS-08-E wave-2 emitted artifact — DO NOT EDIT BY HAND.
#
# Synopsys VCS build wrapper for the {chart_name} chart testbench.
#
# Per SOS-08-E §5.3 + §6.4 + PCDN-SOS-08-E-005 separate wrappers per
# simulator.
#
# Usage:
#   make -f Makefile.sv          # compile + run
#   make -f Makefile.sv compile  # compile only
#   make -f Makefile.sv clean

TOP := {top}

SOURCES := \\
    dut_if_{base}.sv \\
    sos_driver_{base}.sv \\
    sos_checker_{base}.sv \\
    {base}_fsm_sva.sv \\
    {base}_fsm_bind.sv \\
    tb_{base}.sv \\
    {base}_fsm.sv

VCS       ?= vcs
VCS_FLAGS := -sverilog \\
             -assert enable_diag \\
             -timescale=1ns/1ps \\
             -full64 \\
             -debug_access+all \\
             -kdb \\
             -top $(TOP)

.PHONY: all compile run clean

all: run

compile: simv

simv: $(SOURCES)
\t$(VCS) $(VCS_FLAGS) $(SOURCES) -o simv

run: simv
\t./simv -ucli -do "run; quit"

clean:
\trm -rf simv simv.daidir csrc ucli.key DVEfiles inter.vpd
"""


def _emit_xcelium_argfile(chart_name: str) -> str:
    """``run_xrun.sh`` — Cadence Xcelium build wrapper.

    Per PCDN-SOS-08-E-005 separate wrappers per simulator. Xcelium's
    `xrun` accepts SystemVerilog sources directly on the command line
    along with `-sv -assert` flags; the wrapper is a shell script that
    invokes `xrun` with a deterministic flag order.
    """
    base = _normalise_chart_name(chart_name)
    top = tb_module_name(chart_name)
    return f"""#!/usr/bin/env bash
# SOS-08-E wave-2 emitted artifact — DO NOT EDIT BY HAND.
#
# Cadence Xcelium build wrapper for the {chart_name} chart testbench.
#
# Per SOS-08-E §5.3 + §6.4 + PCDN-SOS-08-E-005 separate wrappers per
# simulator.
#
# Usage:
#   ./run_xrun.sh                # compile + run with default flags
#   ./run_xrun.sh -gui           # open SimVision after elaboration
#
# Honors XRUN env var override for custom Xcelium installs.

set -euo pipefail

XRUN=${{XRUN:-xrun}}
TOP={top}

SOURCES=(
    dut_if_{base}.sv
    sos_driver_{base}.sv
    sos_checker_{base}.sv
    {base}_fsm_sva.sv
    {base}_fsm_bind.sv
    tb_{base}.sv
    {base}_fsm.sv
)

# Common Xcelium SVA-aware flag set.
XRUN_FLAGS=(
    -sv
    -access +rwc
    -assert
    -assertinitvar
    -timescale 1ns/1ps
    -top "$TOP"
)

if [[ "${{1:-}}" == "-gui" ]]; then
    XRUN_FLAGS+=(-gui)
    shift
fi

"$XRUN" "${{XRUN_FLAGS[@]}}" "${{SOURCES[@]}}" "$@"
"""


def _emit_riviera_tcl(chart_name: str) -> str:
    """``run_riviera.tcl`` — Aldec Riviera-PRO build wrapper.

    Per PCDN-SOS-08-E-005 separate wrappers per simulator. Riviera's
    Tcl uses `alog` (compile) + `asim` (elaborate + run) rather than
    Questa's `vlog`/`vsim`. The flag set diverges enough from Questa's
    that wave-2 splits them into separate wrapper files (wave-1's
    shared `.do` covered both at LCD-level only).
    """
    base = _normalise_chart_name(chart_name)
    top = tb_module_name(chart_name)
    return f"""# SOS-08-E wave-2 emitted artifact — DO NOT EDIT BY HAND.
#
# Aldec Riviera-PRO build wrapper for the {chart_name} chart testbench.
#
# Per SOS-08-E §5.3 + §6.4 + PCDN-SOS-08-E-005 separate wrappers per
# simulator (wave-2 split this from the shared Questa/Riviera `.do`).
#
# Usage:
#   vsim -c -do run_riviera.tcl         # batch mode (Riviera-PRO ships vsim as a wrapper)
#   alib + amap + alog + asim invocation below for the full Riviera flow

alib work
amap work work

alog -sv2k17 \\
    dut_if_{base}.sv \\
    sos_driver_{base}.sv \\
    sos_checker_{base}.sv \\
    {base}_fsm_sva.sv \\
    {base}_fsm_bind.sv \\
    tb_{base}.sv \\
    {base}_fsm.sv

asim -t 1ps +access+rw +sv_seed=1 work.{top}
run -all
exit
"""


# ---------------------------------------------------------------------------
# Invariant audit
# ---------------------------------------------------------------------------


_INV_E1_PATTERNS: tuple[tuple[str, str], ...] = (
    # INV-S-HDL-E-1: no constrained-random.
    (r"\brandomize\s*\(", "randomize() call"),
    (r"\bconstraint\s+\w+\s*\{", "constraint block"),
    (r"^\s*rand\s+\w", "`rand` property declaration"),
    (r"^\s*randc\s+\w", "`randc` property declaration"),
)

_INV_E2_PATTERNS: tuple[tuple[str, str], ...] = (
    # INV-S-HDL-E-2: no UVM imports / macros.
    (r"\bimport\s+uvm_pkg\s*::", "import uvm_pkg"),
    (r"`uvm_\w+", "`uvm_* macro"),
)

_INV_E3_PATTERNS: tuple[tuple[str, str], ...] = (
    # INV-S-HDL-E-3: no inline `assert property` in non-bind files.
    (r"\bassert\s+property\b", "inline assert property"),
)


def _audit_emitted_file(filename: str, source: str) -> list[str]:
    """Scan ``source`` for INV-S-HDL-E-1/2/3 forbidden constructs.

    SVA bind files are exempt from INV-S-HDL-E-3 — properties live
    there by design. Driver/checker/top/vif/build-wrappers are not.
    Returns the list of human-readable violations (empty if clean).
    """
    is_bind_file = filename.endswith("_sva.sv") or filename.endswith("_bind.sv")
    is_makefile = filename.endswith(".mk") or filename.endswith(".do")
    violations: list[str] = []

    # Strip comments for pattern matching to avoid false positives on
    # spec-prose mentions like "// INV-S-HDL-E-1: no `randomize` ...".
    # Wave-1 strips ``//`` line comments and ``# ...`` Makefile comments;
    # ``/* */`` block comments are not used in emitted output.
    if is_makefile:
        scanned = re.sub(r"#.*$", "", source, flags=re.MULTILINE)
    else:
        scanned = re.sub(r"//.*$", "", source, flags=re.MULTILINE)

    for pat, label in _INV_E1_PATTERNS:
        if re.search(pat, scanned, flags=re.MULTILINE):
            violations.append(f"INV-S-HDL-E-1 violation: {label}")
    for pat, label in _INV_E2_PATTERNS:
        if re.search(pat, scanned, flags=re.MULTILINE):
            violations.append(f"INV-S-HDL-E-2 violation: {label}")
    if not is_bind_file:
        for pat, label in _INV_E3_PATTERNS:
            if re.search(pat, scanned, flags=re.MULTILINE):
                violations.append(f"INV-S-HDL-E-3 violation: {label}")
    return violations


def _audit_all(files: dict[str, str]) -> None:
    """Run the invariant audit across all emitted files; raise on any hit."""
    accumulated: list[str] = []
    for filename, source in files.items():
        hits = _audit_emitted_file(filename, source)
        if hits:
            accumulated.append(
                f"{filename}: " + "; ".join(hits)
            )
    if accumulated:
        raise InvariantAuditError(
            "SOS-08-E wave-1 invariant audit failed:\n  "
            + "\n  ".join(accumulated)
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def render_target(chart_ir: Any, config: Any = None) -> dict[str, str]:
    """Emit the SOS-08-E wave-1 SV testbench artifact set for a chart.

    Wave-1 contract:
      * Single-region chart → eight files under ``tb/sv/<chart>/``:
          - ``tb_<chart>.sv``
          - ``sos_driver_<chart>.sv``
          - ``sos_checker_<chart>.sv``
          - ``dut_if_<chart>.sv``
          - ``<chart>_fsm_sva.sv`` (byte-identical to SOS-08-D emit)
          - ``<chart>_fsm_bind.sv`` (byte-identical to SOS-08-D emit)
          - ``run_verilator.mk``
          - ``run.do`` (Questa / Riviera reference)
      * Parallel charts raise ``UnsupportedChartError`` with a wave-2
        citation per §15.

    Args:
        chart_ir: raw scjson dict (``ChartAst.raw_scjson``).
        config: optional dict / dataclass. Wave-1 consumes:
            - ``chart_name`` (str): chart identifier; module-name base.
            - ``guard_depth_budget`` (int): forwarded to the SVA bind
              walker (PCDN-C-004 budget override).

    Returns:
        dict mapping output filename (relative path embedding the
        ``tb/sv/<chart>/`` prefix) to emitted file source.

    Raises:
        UnsupportedChartError when the chart names a feature outside
        wave-1 scope (parallel regions; non-dict chart_ir).
        InvariantAuditError when the emitted text violates
        INV-S-HDL-E-1..3 (signals an internal walker bug, not chart-
        author error).
    """
    if not isinstance(chart_ir, dict):
        raise UnsupportedChartError(
            "SOS-08-E wave-1 render_target expects the raw scjson dict, "
            f"not {type(chart_ir).__name__}. The main.py dispatcher "
            "needs to pass the parsed scjson AST "
            "(ChartAst.raw_scjson)."
        )

    if isinstance(config, dict):
        chart_name = config.get("chart_name") or "chart"
    else:
        chart_name = getattr(config, "chart_name", None) or "chart"

    if _chart_has_parallel(chart_ir):
        raise UnsupportedChartError(
            "SOS-08-E wave-1 rejects parallel charts; per-region "
            "testbench split is wave-2 scope (see SOS-08-E-CONCEPTS.md "
            "§15 wave-1 entry)."
        )

    base = _normalise_chart_name(chart_name)
    states = _collect_state_ids(chart_ir)
    n_states = max(len(states), 1)

    # Emit the testbench-specific files.
    files: dict[str, str] = {
        f"tb/sv/{base}/dut_if_{base}.sv": _emit_virtual_interface(chart_name),
        f"tb/sv/{base}/sos_driver_{base}.sv": _emit_driver_class(chart_name),
        f"tb/sv/{base}/sos_checker_{base}.sv": _emit_checker_class(chart_name),
        f"tb/sv/{base}/tb_{base}.sv": _emit_top_module(chart_name, n_states),
        f"tb/sv/{base}/run_verilator.mk": _emit_verilator_makefile(chart_name),
        f"tb/sv/{base}/run.do": _emit_questa_do(chart_name),
        # SOS-08-E wave-2 (2026-05-23 §15): close PCDN-E-005 by shipping
        # the remaining three of five simulator wrappers.
        f"tb/sv/{base}/Makefile.sv": _emit_vcs_makefile(chart_name),
        f"tb/sv/{base}/run_xrun.sh": _emit_xcelium_argfile(chart_name),
        f"tb/sv/{base}/run_riviera.tcl": _emit_riviera_tcl(chart_name),
    }

    # Mirror the SOS-08-D SVA bind file artifact, byte-identical, but
    # re-keyed under the SV testbench directory per §5.2 + §6.
    sva_files = _render_sva_bind(chart_ir, config)
    for sva_filename, sva_source in sva_files.items():
        # SOS-08-D emits under ``tests/<chart>/``; SOS-08-E places the
        # same files under ``tb/sv/<chart>/`` so the build wrappers can
        # `include them by relative path. The content is byte-identical.
        leaf = sva_filename.rsplit("/", 1)[-1]
        files[f"tb/sv/{base}/{leaf}"] = sva_source

    # Belt-and-suspenders: scan every emitted file for INV-S-HDL-E-1..3
    # violations before returning. Walker contract is by-construction
    # conformance.
    _audit_all(files)

    return files


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
