# SOS-08 wave-1 conformance review

**Status:** 🟢 **5 of 7 acceptance gates satisfied** as of 2026-05-23. Two gates deferred with explicit reasons (§3).

**Document type:** Informative audit. This doc reviews the wave-1 implementation surface against the [SOS-08 umbrella][sos-08] §12 acceptance checklist. It does NOT declare new normative content — every claim cites the artifact (concept doc, source file, or test suite) that establishes it.

**Purpose:** Provide a single agent-readable + reviewer-readable snapshot of the SOS-08 family's wave-1 status so the umbrella's conformance position is unambiguous without re-walking eight separate sub-phase docs. The article's "spec-to-silicon" claim depends on knowing exactly which gates are satisfied and which are deferred.

[sos-08]: ./SOS-08-CONCEPTS.md
[sos-08-a]: ./SOS-08-A-CONCEPTS.md
[sos-08-b]: ./SOS-08-B-CONCEPTS.md
[sos-08-c]: ./SOS-08-C-CONCEPTS.md
[sos-08-d]: ./SOS-08-D-CONCEPTS.md
[sos-08-e]: ./SOS-08-E-CONCEPTS.md
[sos-08-f]: ./SOS-08-F-CONCEPTS.md
[sos-08-g]: ./SOS-08-G-CONCEPTS.md
[sos-08-h]: ./SOS-08-H-CONCEPTS.md
[sos-06]: ./SOS-06-CONCEPTS.md
[sos-07]: ./SOS-07-CONCEPTS.md

## 1. Executive summary

| Gate | Status | Evidence |
|---|---|---|
| **(a)** PCDN-SOS-08-001..011 resolved | ✅ | [SOS-08][sos-08] §15 2026-05-23 ratification entry |
| **(b)** Each sub-phase A–H has concept doc drafted + ratified | ✅ | All eight [SOS-08-A][sos-08-a] through [SOS-08-H][sos-08-h] carry `Status: 🟢 ratified 2026-05-23` |
| **(c)** ≥1 L0 primitive: portable RTL + cocotb + SVA | ✅✅ over-satisfied | All 11 L0 + 5 L1 primitives have `rtl/<primitive>/` (`.sv` + `.vhd` + `_sva.sv`) + `tb/<primitive>/` (cocotb test + bind file) |
| **(d)** Codegen tool HDL-emit path tested on ≥1 chart | ✅ | 45 chart→HDL tests pass (`tools/sos-codegen/tests/test_transliterate_hdl_{vhdl,sv}.py`) |
| **(e)** Bench validation on Lattice ECP5 dev board | ⏸ | No FPGA-bench landing yet; deferred to a dedicated bench session — see §3 |
| **(f)** INV-SOS-A..H cited in each sub-phase doc | ✅ | All eight sub-phase docs cite the invariants 4–18 times each |
| **(g)** SOS-06 §15 amendment extending 7 metrics to HDL | ✅ paper / ⏸ numbers | [SOS-06][sos-06] §15 Amendment 006 lands the paper translation (2026-05-23); numerical readings wait for gate (e) bench session per §3 |

**Conformance position:** SOS-08 umbrella satisfies first-tier conformance for everything that can be verified from the wave-1 source tree. Gate (e) is the remaining hardware-landing gate (Lattice ECP5 bench session); gate (g) is now half-flipped (✅ paper translation; ⏸ numerical readings from gate (e) session). Nothing in the wave-1 surface itself is non-conforming.

## 2. Sub-phase wave-1 surface (one-line status per sub-phase)

| Sub-phase | Wave-1 surface | Concept doc | Implementation files | Tests |
|---|---|---|---|---|
| **SOS-08-A** | 11 L0 + 5 L1 primitives in portable VHDL + SV + SVA | [SOS-08-A][sos-08-a] wave-2 ratified | `rtl/sos_*/` (16 primitives) | `tb/sos_*/` cocotb suites |
| **SOS-08-B** | L1 service composition vocabulary (mailbox, event_group, resource_pool, periodic_task, message_channel) | [SOS-08-B][sos-08-b] wave-1 ratified | (composes SOS-08-A primitives) | covered via L0 tests + chart-emit tests |
| **SOS-08-C** | chart→FSM emission (VHDL + SV) with guards, parallel regions, chart-top wrapper, cross-domain synchronizers | [SOS-08-C][sos-08-c] wave-2 + wave-3 polish | `tools/sos-codegen/transliterate_hdl_{vhdl,sv}.py` + `hdl_common.py` | 45 tests in `test_transliterate_hdl_{vhdl,sv}.py` |
| **SOS-08-D** | cocotb test + SVA bind file emission with §15 PCDN walkthrough | [SOS-08-D][sos-08-d] wave-1 + PCDN walkthrough | `tools/sos-codegen/transliterate_cocotb.py` + `transliterate_sva_bind.py` | full SOS-08-D test suites + `--target sos-08-d` CLI |
| **SOS-08-E** | class-based SV testbench LCD path with audit-by-construction INV-S-HDL-E-1..6 | [SOS-08-E][sos-08-e] wave-1 ratified | `tools/sos-codegen/transliterate_hdl_sv_tb.py` | 60 tests in `test_transliterate_hdl_sv_tb.py` |
| **SOS-08-F** | UVM-sequences-only emission with 10/80 framing — 6 per-family sequences + universal `sos_seq_item` | [SOS-08-F][sos-08-f] wave-1 ratified | `tools/sos-codegen/transliterate_hdl_uvm_seq.py` | 78 tests in `test_transliterate_hdl_uvm_seq.py` |
| **SOS-08-G** | waveform annotation overlay + GTKWave + Surfer viewer extensions with §15 PCDN walkthrough | [SOS-08-G][sos-08-g] wave-1 + PCDN walkthrough | `transliterate_cocotb.py` AnnotationWriter + `tools/sos-codegen/viewers/{gtkwave,surfer}/` | 31 walker tests + 30 viewer tests |
| **SOS-08-H** | cooperative-only at v1 + SCXML-LINT-H-1 preemption hard-reject lint | [SOS-08-H][sos-08-h] wave-1 ratified | lint rule integrated in chart-compile pipeline | covered via chart-compile lint tests |

**Total codegen + viewer test pass count:** 302/302 (see [`tools/sos-codegen/tests/`](../../tools/sos-codegen/tests/) + [`tools/sos-codegen/viewers/tests/`](../../tools/sos-codegen/viewers/tests/)).

## 3. Deferred gates — explicit reasons

### Gate (e) — Bench validation on Lattice ECP5

The umbrella's (e) gate requires running the worked-example chart through Yosys + nextpnr on a Lattice ECP5 dev board, with the cocotb tests confirming the placed-and-routed bitstream's behaviour matches the simulator.

**Why deferred:** The wave-1 surface is software-tractable. Bench validation is a single coordinated session with hardware in hand and is bounded by the parent-repo bench-authorization rule ([`feedback_no_speculative_board_reset`](../../../streamz/submodules/SOS/../../CLAUDE.md) — note that the ECP5 dev board is a separate physical resource from the disco-analyzer board the parent rule references; the principle of per-round authorization extends to any bench-managed FPGA).

**Wave-2 landing plan:** Dedicated bench session per the umbrella §12 (e) wording — `sos_fifo_async` as the L0 primitive (per [SOS-08-A][sos-08-a] §12 (e) recommendation) + the worked-example chart sub-factored from `rtos_kernel.scxml`. The session produces (1) Yosys synthesis log, (2) nextpnr place + route log + timing report, (3) bitstream load confirmation, (4) cocotb-against-bitstream-via-Verilator-cosim pass/fail. All four artifacts land under `docs/experiments/` per the experiment-doc convention.

### Gate (g) — SOS-06 §15 amendment extending 7 metrics to HDL

**Paper landing: ✅ as of 2026-05-23.** [SOS-06][sos-06] §15 **Amendment 006** authored — the seven-metric translation table is frozen:

- `BinarySize.text` → **`AreaFootprint`** (LUTs + FFs + BRAM blocks; LUT count is the primary verdict axis; vendor-tool report parsing per chosen target part).
- `RamFootprint.bss` → **`StaticAllocationFootprint`** (register + BRAM-block count; exhaustive per INV-S-HDL-2 — no heap analog).
- `MacrostepCycleCount` → **`MacrostepClockCount`** (simulator clock cycles between event entry and chart quiescence; same 100-run median methodology).
- `BuildTime` → **unchanged metric name**; measurement procedure becomes synth + place + route wall-clock against the target part (Yosys+nextpnr open-source path or vendor tool).
- `FunctionalConformance`, `SourceLineCount`, `Auditability` → unchanged metric names; per-target-shaped measurement procedures.

**`EvaluationMetric` enum frozen values are unchanged.** Same 1.5x / 2x verdict thresholds across the three `Concern`-severity metrics. Specification-Required registration policy applies to adding a sixth HDL-side metric.

**Numerical readings: ⏸ wave-2 bench session.** The paper translation unblocks the gate (e) Lattice ECP5 bench session — that session reports the first numbers against the extended metric set; this amendment defines what's being measured. Gate (g) is now half-flipped: ✅ paper, ⏸ first data point.

## 4. Cross-sub-phase invariant audit — INV-S-HDL-1..5

The umbrella [SOS-08][sos-08] §7 freezes five cross-sub-phase invariants. The wave-1 surface satisfies all five:

| Invariant | Wave-1 satisfaction |
|---|---|
| **INV-S-HDL-1** — handshake-compatible ports (req/ack OR ready/valid) | SOS-08-A L0 + L1 primitives expose AXI-Stream ready/valid for data-bearing channels and req/ack for control-only handshakes per [PCDN-SOS-08-001 resolution][sos-08] §15. SOS-08-C wraps them at chart-FSM boundaries; SOS-08-D/E/F consume them. |
| **INV-S-HDL-2** — static allocation, no dynamic in any emission | All RTL primitives use static pools / FIFOs; no `malloc`-equivalent constructs in any emitted VHDL/SV. The SVA bind files and SV testbench classes use only static buffers. Audit: grep `dynamic` in `rtl/` returns nothing relevant. |
| **INV-S-HDL-3** — cross-domain isolation via `sos_synchronizer` / `sos_fifo_async` | `rtl/sos_synchronizer/` and `rtl/sos_fifo_async/` exist with MTBF sign-off in their respective `MTBF.md` files. [SOS-08-C][sos-08-c] wave-3 micro added `<sos:region clock="..."/>` element-form annotation so chart authors declare clock-domain crossings; the walker emits synchronizers automatically at region boundaries. |
| **INV-S-HDL-4** — cooperative-only at v1 (per EOQ-008) | [SOS-08-H][sos-08-h] freezes the cooperative-only stance and ratifies SCXML-LINT-H-1, the preemption hard-reject chart-compile lint. Charts that declare `<state preemptive="true">` (or equivalent) reject at compile time. |
| **INV-S-HDL-5** — vector-to-chart traceability for HDL (every artifact carries chart-vocabulary metadata) | SOS-08-D cocotb test + SVA bind emit `chart_state` / `transition_id` in failure messages and SVA `else $fatal(1, ...)` clauses. SOS-08-E checker class emits `[FAIL] vector V<n>: chart `<chart>`` chart-vocabulary messages (verified by `TestCheckerClass.test_failure_message_is_chart_vocabulary`). SOS-08-F `sos_seq_item` carries `chart_state` / `transition_id` / `invariant_id` (audit-by-construction via `_audit_metadata_fields` — verified by `TestInvariants.test_inv_f3_metadata_fields_present`). SOS-08-G annotation records carry the same six normative fields per §5.2 (verified by `TestAnnotationSchema`). |

**Audit conclusion:** All five cross-sub-phase invariants hold across the wave-1 surface. Each is verified by either by-construction audit (E, F, G) or by sub-phase concept-doc compliance review (A, B, C, D, H).

## 5. Cross-walker mirror equivalence

The umbrella's design has SOS-08-D and SOS-08-E share the SVA bind file artifact byte-for-byte (per [SOS-08-E][sos-08-e] §5.2 + INV-S-HDL-D-4). This is verified by:

- `tools/sos-codegen/tests/test_transliterate_hdl_sv_tb.py::TestSvaBindMirror::test_sva_module_content_matches_sos_08_d`
- `tools/sos-codegen/tests/test_transliterate_hdl_sv_tb.py::TestSvaBindMirror::test_bind_directive_matches_sos_08_d`

Both tests render the same chart through both walkers and compare emitted file content byte-for-byte. The wave-1 surface upholds this equivalence — the "one chart, three emission paths" claim from the umbrella §5.4 is operational.

## 6. By-construction audit summary

Three sub-phase walkers (SOS-08-E, SOS-08-F, SOS-08-G implicitly via schema header) run an explicit `_audit_all` pass over every emitted file before returning. The audit functions enforce per-sub-phase invariants by construction:

| Walker | Audited invariants | Audit function |
|---|---|---|
| `transliterate_hdl_sv_tb.py` | INV-S-HDL-E-1 (no `randomize`/`constraint`/`rand`/`randc`), INV-S-HDL-E-2 (no UVM imports/macros), INV-S-HDL-E-3 (no inline `assert property` outside bind files) | `_audit_all` raises `InvariantAuditError` on hit |
| `transliterate_hdl_uvm_seq.py` | INV-S-HDL-F-1 (no `extends uvm_env/agent/sequencer/driver/monitor/scoreboard/test`, no `uvm_config_db`), INV-S-HDL-F-3 (`sos_seq_item` chart-vocab fields present), INV-S-HDL-F-4 (no `assert property`, no `bind`) | `_audit_all` raises `InvariantAuditError` on hit |
| `transliterate_cocotb.py` AnnotationWriter | INV-S-HDL-G-3 (schema-version header at line 0) — enforced by writer's `__init__` writing the header before yielding the constructor | schema header check in viewer extensions on read |

The audit-by-construction discipline means that for these sub-phases, a future regression in walker code emits text that fails the audit immediately at codegen time — not at downstream test compile time or simulation time. The discipline costs ~30 lines of audit code per walker and recovers correctness signal that would otherwise sit downstream where it's expensive to diagnose.

## 7. PCDN walkthrough completion

Wave-1 surfaced two additional PCDN sets beyond the umbrella's 11 PCDNs:

### SOS-08-D wave-1 PCDNs (8 resolutions)

All eight resolved during the SOS-08-D wave-1 PCDN walkthrough — see [SOS-08-D][sos-08-d] §15 amendments dated 2026-05-23. Covered: file layout (`tests/<chart>/` prefix), SVA input port name canonicalization (`state_q` → `current_state`), unified `--target sos-08-d` CLI form, vector schema extension (`steps[]` with `{index, inputs, expected_state, transition_id}`).

### SOS-08-G wave-1 PCDNs (5 resolutions)

All five resolved during the SOS-08-G wave-1 PCDN walkthrough — see [SOS-08-G][sos-08-g] §15 amendments dated 2026-05-23. The load-bearing one was PCDN-G-wave1-001 (schema header canonicalization: hybrid `_meta`-wrapped + namespaced `sos-08-g/annotations` + `chart_path_max_depth: 8`); the other four (per-cycle density actual impl, filename-prefix coordination by construction, nested-chart `chart_path` walking, SVA bind-file `invariant_id` integration) deferred to wave-2 with documented reasons.

### Sub-phase ratification PCDNs

Each sub-phase concept doc ratified 2026-05-23 with all its own PCDNs resolved:

- [SOS-08-A][sos-08-a] PCDN-SOS-08-A-001..N — all resolved.
- [SOS-08-B][sos-08-b] PCDN-SOS-08-B-001..N — all resolved.
- [SOS-08-C][sos-08-c] PCDN-SOS-08-C-001..006 — all resolved (one-hot encoding default, guard-depth budget 8, document-order priority lint, chart-annotation-wins, `<sos:region clock="..."/>` element form).
- [SOS-08-D][sos-08-d] PCDN-SOS-08-D-001..007 + wave-1 walkthrough PCDNs — all resolved.
- [SOS-08-E][sos-08-e] PCDN-SOS-08-E-001..005 — all resolved (flat class hierarchy, Verilator-subset compliance via deferred-failure stubs, coverage deferred, per-region testbench shape, separate simulator wrappers).
- [SOS-08-F][sos-08-f] PCDN-SOS-08-F-001..006 — all resolved (UVM 1.2 + forward-compat to 2.0, six families, universal `sos_seq_item`, in-package factory registration, empty hooks, one consolidated package).
- [SOS-08-G][sos-08-g] PCDN-SOS-08-G-001..007 + wave-1 walkthrough — all resolved.
- [SOS-08-H][sos-08-h] PCDN-SOS-08-H-001..N — all resolved (SCXML-LINT-H-1 hard reject, cooperative scope, etc.).

**Total PCDNs resolved at wave-1:** 11 (umbrella) + 8 (D walkthrough) + 5 (G walkthrough) + the per-sub-phase ratification PCDNs ≈ **40+ across the SOS-08 family**.

## 8. Wave-2 candidates — consolidated list

Each sub-phase's §15 wave-1 entry documents its own wave-2 boundary; this is a consolidated view to make the umbrella's wave-2 planning surface single-readable.

| Source | Wave-2 candidate |
|---|---|
| [SOS-08-D][sos-08-d] | Parallel chart support (per-region SVA bind shape + cocotb test wrapping); `post_results.py` JUnit emission |
| [SOS-08-E][sos-08-e] | VCS `Makefile.sv` + Xcelium `run_xrun.sh` + Riviera `.tcl` build wrappers (3 of 5 simulators); parallel-chart support (co-deferred with D); full SOS-03 vector-schema consumer; cross-path equivalence test with D; layered class hierarchy opt-in; Verilator deferred-failure stubs |
| [SOS-08-F][sos-08-f] | Full SOS-03 JSONL vector-IR parser (replaces `load_vector_ir` stub; co-deferred with E); gate (e) end-to-end UVM 1.2 worked example; gate (f) injected-violation chart-vocab check; UVM 2.0 cross-runtime smoke test; pyuvm overlay (potential SOS-08-F-A) |
| [SOS-08-G][sos-08-g] | Full GUI integration (GTKWave Python API + Surfer plugin API); per-cycle density actual implementation; nested-chart `chart_path` walking; SVA bind-file `invariant_id` integration; cycle-to-time multiplier resolution |
| Umbrella gate (e) | Bench validation on Lattice ECP5 dev board (Yosys + nextpnr + cocotb-against-bitstream) — see §3 |
| Umbrella gate (g) | SOS-06 §15 amendment extending 7 metrics to HDL — see §3 |
| [SOS-08-C][sos-08-c] wave-3 events | Event ingress/egress via `sos_message_channel` chart-side compilation |

**Co-deferral note:** "Full SOS-03 vector-schema consumer" appears as a wave-2 candidate in both SOS-08-E and SOS-08-F. The wave-2 implementation authors the parser once (as a reusable SV utility module) and reuses it in both sub-phases; this is the natural co-landing pair.

## 9. Spec-Before-Code discipline conformance

The SOS-08 family's wave-1 surface conforms to the parent-repo CLAUDE.md "Spec-Before-Code Planning Discipline":

- **Every behaviour change preceded by a ratified terms doc.** Every wave-1 implementation commit cites the ratifying §15 entry of its sub-phase concept doc. The PCDN-walkthrough → §15-amendment-first pattern was followed for both SOS-08-D and SOS-08-G wave-1 walkthroughs.
- **Phase document shape (§0..§15) maintained across all 8 sub-phases.** The numbering convention, normative-vs-informative section split, RFC-2119 keyword usage, frozen-enumeration registration policies, and §15 change log discipline all hold across the family.
- **Conformance targets named.** Each sub-phase's §12 acceptance checklist names conformance levels (e.g. SOS-08-F "second-tier conformance without (e)" — explicitly documented).
- **AuthorityRelationship matrix entries with mutation rights.** The umbrella §8 + each sub-phase's §8 carries the matrix rows for the standards they consume; all relationships are explicit (`derive` for UVM, VHDL-2008, SV-2017, IEEE 1364-2005 VCD, GTKWave's FST; `represent` for the four commercial-viewer extension APIs; `own` for the SOS-08-G annotation overlay schema).
- **ERRATA log discipline.** SOS-08 family has not yet produced ratified-then-implemented content that required a stealth-revert errata entry. The discipline is in place if needed (per the parent CLAUDE.md "Stealth-revert prohibition" — the family's first such event will land an ERRATA entry FIRST per the documented procedure).

## 10. What this review does NOT cover

The umbrella's `SOS-09` (membrane), `SOS-10` (multi-language orchestrator), `SOS-11` (MCP-mediated chart editing), `SOS-12` (recursive chart dispatch), and `SOS-13` (verified-strip profile) are not part of SOS-08. They have their own concept docs + acceptance gates. SOS-08's gate satisfactions do NOT imply readiness for these adjacent phases.

The article's "spec-to-silicon" narrative spans SOS-07 (cross-phase invariants), SOS-08 (HDL family), SOS-09 (membrane), SOS-11 (MCP), and SOS-12 (recursive dispatch). This review covers only the SOS-08 leg.

## 11. References

| Doc | Used for |
|---|---|
| [`SOS-08-CONCEPTS.md`][sos-08] | Umbrella acceptance checklist §12 + INV-S-HDL-1..5 §7 |
| [`SOS-08-A-CONCEPTS.md`][sos-08-a] through [`SOS-08-H-CONCEPTS.md`][sos-08-h] | Per-sub-phase wave-1 ratification + §15 wave-1 implementation entries |
| [`SOS-07-CONCEPTS.md`][sos-07] | Cross-phase invariants INV-SOS-A..H (cited by every sub-phase doc) |
| [`SOS-06-CONCEPTS.md`][sos-06] | 7-metric framework awaiting HDL extension (gate (g)) |
| `tools/sos-codegen/` | All walkers + audit functions + integration tests |
| `tools/sos-codegen/tests/` + `tools/sos-codegen/viewers/tests/` | 302/302 wave-1 test surface |
| `rtl/sos_*/` (16 primitives) | L0 + L1 portable VHDL/SV + SVA assertion modules |
| `tb/sos_*/` (16 primitive testbenches) | Cocotb tests + module-type SVA bind files |

## 12. Change log

### 2026-05-23 — Initial wave-1 conformance review (Ira)

- Authored this doc as the consolidated wave-1 conformance status snapshot for the SOS-08 family.
- Umbrella §12 gates audited; 5 of 7 satisfied (a, b, c, d, f); 2 deferred with documented reasons (e — bench validation; g — SOS-06 §15 amendment).
- Cross-sub-phase invariants INV-S-HDL-1..5 verified across the wave-1 surface; all 5 satisfied.
- Cross-walker mirror equivalence (SOS-08-D ↔ SOS-08-E SVA bind file byte-identical) verified by test.
- By-construction audit summary documented for SOS-08-E, SOS-08-F, SOS-08-G.
- 40+ PCDNs resolved across the family (11 umbrella + 8 D-walkthrough + 5 G-walkthrough + ratification PCDNs across A–H).
- Wave-2 candidate list consolidated across all sub-phases.

Status: 🟢 **wave-1 conformance review complete**. Wave-2 work proceeds against an unambiguous spec / impl baseline.

### 2026-05-23 — Gate (g) paper flip via SOS-06 §15 Amendment 006 (Ira)

- [SOS-06][sos-06] §15 Amendment 006 lands the HDL-target metric extension: `AreaFootprint` (was `BinarySize`); `StaticAllocationFootprint` (was `RamFootprint`); `MacrostepClockCount` (was `MacrostepCycleCount`); `BuildTime` (synth+P&R wall-clock); `FunctionalConformance` / `SourceLineCount` / `Auditability` per-target-shaped procedures.
- `EvaluationMetric` frozen enum values unchanged; 1.5x / 2x verdict thresholds unchanged; HDL extension is Specification-Required registration.
- Executive-summary gate matrix: gate (g) row updated to `✅ paper / ⏸ numbers` — the paper translation is ratified; the first numerical readings land at the gate (e) bench session.
- §3 deferred-gates entry for gate (g) rewritten to record the paper landing + the per-metric translation choices; deferral text reduced to "wave-2 bench session for first data point".
- Conformance position updated: 5 of 7 gates fully ✅; gate (g) half-flipped; gate (e) remains ⏸.
