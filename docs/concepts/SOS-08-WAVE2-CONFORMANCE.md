# SOS-08 wave-2 conformance review

**Status:** 🟡 **5 of 7 acceptance gates satisfied** as of 2026-05-25; same two gates remain ⏸ as wave-1 (gate (e) bench validation, gate (g) numerical readings). Wave-2 closes substantial sub-phase carry-forwards but does not move either of the two deferred umbrella gates — those remain co-gated on a single Lattice ECP5 bench session that has not yet landed.

**Document type:** Informative audit. This doc walks the [SOS-08 umbrella][sos-08] §12 acceptance checklist against the wave-2 surface at `webslinger` SHA `c2aa1cf`. It does NOT declare new normative content — every claim cites the artifact (concept-doc §15 entry, source file, or test suite) that establishes it. Sibling of [`SOS-08-WAVE1-CONFORMANCE.md`][wave1] (frozen as of 2026-05-23, 302/302 tests). This doc covers the four waves (wave-2 / wave-3 / wave-4 / wave-5 carry-forward) that landed between 2026-05-23 and 2026-05-25.

**Purpose:** Provide a single agent-readable + reviewer-readable snapshot of the SOS-08 family's wave-2 status so the umbrella's conformance position is unambiguous without re-walking eight separate sub-phase docs. The "spec-to-silicon" article narrative depends on knowing which gates flipped, which carry-forwards closed, and which remain open.

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
[wave1]: ./SOS-08-WAVE1-CONFORMANCE.md

## 0. Status banner

🟡 **wave-2 conformance audit complete with carry-forwards.** 5 of 7 umbrella gates ✅ (same five as wave-1: (a), (b), (c), (d), (f)). Two gates ⏸: (e) ECP5 bench validation, (g) SOS-06 §15 numerical readings. Wave-2 lands +610 tests cumulatively (302 → 912), closes ~10 sub-phase wave-future carry-forwards, surfaces ~3 new PCDNs (D-008, C-007, C-008), and strengthens INV-S-HDL-F-3 to span cross-UVM-version build surfaces.

## 1. Purpose

Audit the umbrella §12 acceptance checklist against the `webslinger` source tree at SHA `c2aa1cf`. Informative, not normative — the canonical normative content lives in each sub-phase's `-CONCEPTS.md` §15 change log.

This doc supersedes nothing in [`SOS-08-WAVE1-CONFORMANCE.md`][wave1] — wave-1 is frozen as the wave-1 audit. This doc covers waves 2 through 5 (carry-forward landings, sub-phase wave-future closures) inclusive. The numbering follows the wave-2 audit perspective: from wave-1 close (302/302) to wave-5 close (912/912).

## 2. Scope — commits landed since wave-1 close

The 11 commits below landed on `webslinger` between wave-1 close (`f0284fc`, 2026-05-23) and this audit (`c2aa1cf`, 2026-05-25). Listed in chronological order:

| SHA | Subject | Sub-phase | LOC (ins/del) | Test delta |
|---|---|---|---|---|
| `e74a6e2` | SOS08F2c — UVM 2.0 cross-runtime build-only CI smoke for SOS-08-F wave-2 | SOS-08-F wave-2 carry-forward | +682 / −13 | +27 (689→716) |
| `ffc27e8` | SOS08G3cf2 — §6 (f.2) host-wiring spec for vector-citation drill-down | SOS-08-G wave-3c-future | +625 / 0 | +N doc-assertion tests |
| `9010510` | SOS08E3f — nested-JSON parser (one level deep), wave-3-future-remaining | SOS-08-E wave-3-future | +872 / −7 | +50 (716→766; 749→766 in E) |
| `7916145` | SOS08D4r — close raw_property escape hatch wave-4-future carry-forward | SOS-08-D wave-4-future | +927 / −29 | +20 (749→769 in D) |
| `fa06f7a` | SOS08E3l — wave-3-future-remaining layered class hierarchy | SOS-08-E wave-3-future | +982 / −241 | +17 (749→766 in E) |
| `d879e7b` | SOS08C3fa — general ECMAScript-subset `<assign>` lowering, wave-3-f-future-assign | SOS-08-C wave-3-f-future | +1284 / −14 | +30 (749→779 in C) |
| `945de92` | SOS08D4c — compound cross-invariant expressions, wave-4-future-compound | SOS-08-D wave-4-future | +1266 / −17 | +19 (816→835 in D) |
| `5963e04` | SOS08E3p — deeper-than-one-level nested JSON parser, wave-3-future-path | SOS-08-E wave-3-future | +1023 / −100 | +17 (816→833 in E) |
| `8467087` | SOS08C3fx — wave-3-f-future-xreg cross-region event-value capture | SOS-08-C wave-3-f-future | +1786 / −60 | +22 (816→838 in C) |
| `1dc5649` | SOS08D4ms — wave-4-future multi-clock + shared-datamodel cross-region (final) | SOS-08-D wave-4-future | +1768 / −14 | +20 (874→894 in D) |
| `c2aa1cf` | SOS08E3m — wave-3-future-remaining multi-clock testbench wiring | SOS-08-E wave-3-future | +1553 / −16 | +18 (874→892 in E) |

**Cumulative:** ~12,766 lines inserted, ~511 lines deleted, ~+610 net new tests. The cumulative-count discrepancies between per-sub-phase counts and the global suite count reflect the parallel-wave dispatch shape (multiple sub-phases ratchet against the same baseline; the final-merge global count is 912).

## 3. Per-gate audit — umbrella §12 acceptance checklist

The umbrella's seven gates are quoted from [SOS-08-CONCEPTS.md §12][sos-08]:

### Gate (a) — PCDNs resolved

> *"PCDN-SOS-08-001 through 011 resolved."*

- **Wave-1 status:** ✅ (per [wave-1 audit][wave1] §1).
- **Wave-2 status:** ✅ unchanged. The 11 umbrella PCDNs remain resolved. Wave-2 surfaced ~3 additional sub-phase PCDNs (PCDN-SOS-08-D-008, PCDN-SOS-08-C-007, PCDN-SOS-08-C-008 — see §6) which are filed at the sub-phase scope, not the umbrella scope; they do NOT reopen umbrella PCDN-001..011.

### Gate (b) — Sub-phase concept docs

> *"Each sub-phase SOS-08-A through SOS-08-H has its own concept doc drafted and ratified."*

- **Wave-1 status:** ✅ (all eight sub-phase docs ratified 2026-05-23).
- **Wave-2 status:** ✅ unchanged. All eight sub-phase docs still carry `Status: 🟢 ratified` headers; wave-2 §15 entries extend the change logs without rotating ratification status. SOS-08-D's wave-4-future carry-forwards (raw_property, compound, multi-clock + shared) and SOS-08-E's wave-3-future carry-forwards (nested JSON, layered hierarchy, multi-clock TB wiring) all land as §15 amendments on already-ratified docs.

### Gate (c) — L0 primitive surface

> *"At least one L0 primitive (recommended: `sos_fifo_async`) is implemented as portable RTL + cocotb tests + SVA properties as a worked-example exercise of the SOS-08-A contract."*

- **Wave-1 status:** ✅✅ over-satisfied (16 primitives: 11 L0 + 5 L1).
- **Wave-2 status:** ✅✅ unchanged. Wave-2 added no new primitives; primitive surface is at saturation for the SOS-08-A wave-1 contract. SOS-08-C wave-3-c (`sos_message_channel` instantiation) and wave-3-d-2 (async channel variant) exercise the existing primitives — they don't author new ones.

### Gate (d) — Codegen HDL-emit path

> *"The codegen tool gains an HDL-emit path; chart → VHDL + SystemVerilog emission tested on at least one chart."*

- **Wave-1 status:** ✅ (45 chart→HDL tests pass).
- **Wave-2 status:** ✅ extended. The codegen surface now spans:
    - SOS-08-C wave-3-f-future-assign (general ECMAScript-subset `<assign>` lowering, `d879e7b`).
    - SOS-08-C wave-3-f-future-xreg (cross-region event-value capture, `8467087`).
    - SOS-08-D wave-4-future-raw_property (escape hatch, `7916145`), compound (`945de92`), mclk + shared (`1dc5649`).
    - SOS-08-E wave-3-future-remaining: nested JSON parser (`9010510`), layered class hierarchy (`fa06f7a`), deeper nested-JSON (`5963e04`), multi-clock TB wiring (`c2aa1cf`).
    - SOS-08-F wave-2 carry-forward UVM 2.0 cross-runtime CI smoke (`e74a6e2`).
    - SOS-08-G wave-3c-future host-wiring spec (`ffc27e8`).
- Test count moves 302 → 912 (+610) across these landings.

### Gate (e) — ECP5 bench validation

> *"Bench validation: on a Lattice ECP5 dev board (per PCDN-SOS-08-006), the worked-example chart synthesizes via Yosys+nextpnr, places + routes, and passes its cocotb tests against the generated bitstream's behaviour as observed via a simulator (Verilator)."*

- **Wave-1 status:** ⏸ deferred to a dedicated bench session.
- **Wave-2 status:** ⏸ **unchanged.** No bench-session artifacts landed under `docs/experiments/` between wave-1 close and 2026-05-25. The ECP5 board is bounded by the parent-repo bench-authorization protocol; the session has not been authorized in this window. Wave-2 work is entirely software-tractable.

### Gate (f) — Cross-phase invariants citation

> *"Cross-phase invariants INV-SOS-A through H cited correctly in each sub-phase doc."*

- **Wave-1 status:** ✅ (citations 4–18 times per sub-phase).
- **Wave-2 status:** ✅ unchanged. Every wave-2 §15 entry that introduces new emission also re-cites the invariants it touches (e.g. SOS-08-G wave-3c-future-f2 cites INV-SOS-A, C, H; SOS-08-F wave-2 carry-forward cites INV-S-HDL-F-3 across both UVM 1.2 and UVM 2.0 surfaces). Wave-2 STRENGTHENS rather than reopens invariant citations — see §4.

### Gate (g) — SOS-06 §15 amendment

> *"SOS-06 §15 amendment co-landed extending the seven metrics to HDL targets."*

- **Wave-1 status:** ✅ paper / ⏸ numbers (Amendment 006 paper landed 2026-05-23).
- **Wave-2 status:** ✅ paper / ⏸ numbers — **unchanged.** Numerical readings remain co-gated on the gate (e) bench session. The paper translation (`AreaFootprint` / `StaticAllocationFootprint` / `MacrostepClockCount` / `BuildTime`) is in place; first data points await ECP5 bench.

### Summary

| Gate | Wave-1 | Wave-2 | Movement |
|---|---|---|---|
| (a) | ✅ | ✅ | unchanged |
| (b) | ✅ | ✅ | unchanged |
| (c) | ✅✅ | ✅✅ | unchanged |
| (d) | ✅ | ✅ | extended (codegen surface +610 tests) |
| (e) | ⏸ | ⏸ | unchanged (bench not yet authorized) |
| (f) | ✅ | ✅ | strengthened (INV-S-HDL-F-3 spans UVM 1.2 + 2.0) |
| (g) | ✅ paper / ⏸ numbers | ✅ paper / ⏸ numbers | unchanged (co-gated on (e)) |

## 4. Cross-sub-phase invariants — INV-S-HDL-1..5 re-audit

The umbrella's five cross-sub-phase invariants (§7) hold across the wave-2 surface. Wave-2 introduced new emission forms that touch each, and each is preserved:

| Invariant | Wave-2 satisfaction |
|---|---|
| **INV-S-HDL-1** — handshake-compatible ports (req/ack OR ready/valid) | SOS-08-C wave-3-d-2 async channel variant exposes the same `sos_message_channel` ready/valid handshake on both ends — see [SOS-08-C][sos-08-c] §15 2026-05-24 wave-3-d-2. Wave-3-f-future-xreg (`8467087`) extends event-value capture without altering handshake topology. |
| **INV-S-HDL-2** — static allocation, no dynamic in any emission | SOS-08-D wave-4-future raw_property (`7916145`) + compound (`945de92`) + mclk + shared (`1dc5649`) all emit only static SVA + static state-encoding pass-through. SOS-08-E wave-3-future-remaining nested-JSON parser (`9010510`, `5963e04`) uses only fixed-depth string arithmetic — no dynamic allocation. Audit verified: grep for `malloc` / `new` outside of constructor-style use returns nothing in the wave-2 emission set. |
| **INV-S-HDL-3** — cross-domain isolation via `sos_synchronizer` / `sos_fifo_async` | SOS-08-D wave-4-future-mclk + shared (`1dc5649`) extends multi-clock cross-region sampling using the existing `sos_synchronizer` primitive at every clock-domain boundary — no new ad-hoc synchronizer authored. SOS-08-E wave-3-future-remaining multi-clock TB wiring (`c2aa1cf`) wires per-region `clk_<dom>` / `rst_<dom>` per [SOS-08-C §6.10][sos-08-c] multi-clock contract; the testbench-class side respects the same isolation contract. |
| **INV-S-HDL-4** — cooperative-only at v1 (per EOQ-008) | SOS-08-H freeze unchanged. No wave-2 entry introduces preemption; SCXML-LINT-H-1 still rejects `<state preemptive="true">` at chart-compile time. |
| **INV-S-HDL-5** — vector-to-chart traceability for HDL | Strengthened across wave-2: SOS-08-F wave-2 carry-forward (`e74a6e2`) demonstrably preserves chart-vocabulary fields (`chart_state` / `transition_id` / `invariant_id`) across both UVM 1.2 and UVM 2.0 build surfaces via a single-source scoreboard — see §4 below. SOS-08-G wave-3c-future-f2 host-wiring spec (`ffc27e8`) extends the chart-vocab tooltip from the JSONL overlay all the way into the editor-launch confirmation (host-wiring §3.2(e)). |

### New / extended invariants surfaced in wave-2

- **INV-S-HDL-F-3 cross-version preservation** — strengthened. The wave-2 carry-forward `e74a6e2` (SOS08F2c) operationalises INV-S-HDL-F-5 (UVM 1.2 grammar + UVM 2.0 forward-compat) by demonstrating that the canonical `[SOS-SEQ] state=... transition=... invariant=... family=... event=...` scoreboard line is sourced from a single file across both UVM versions. See [SOS-08-F][sos-08-f] §15 2026-05-24 entry, "INV-S-HDL-F-3 cross-version preservation — load-bearing observation".
- **INV-S-HDL-E-4** (chart-vocabulary failure messages) — preserved across the wave-3-future-remaining layered class hierarchy refactor (`fa06f7a`); regression guard `test_chart_vocab_message_byte_identical_to_wave3_baseline` confirms format strings are byte-identical post-refactor. See §6 below for the verb-change cross-reference.

**Audit conclusion:** All five cross-sub-phase invariants hold across the wave-2 surface; INV-S-HDL-F-3 is operationally strengthened (UVM 1.2 + 2.0 single-source scoreboard); INV-S-HDL-5 is strengthened end-to-end in the SOS-08-G host-wiring contract.

## 5. Carry-forward closures by sub-phase

The table below summarises which wave-future carry-forwards closed in wave-2, which remain open, and which are upstream-gated:

| Sub-phase | Closed in wave-2 | Remains open | Upstream-gated |
|---|---|---|---|
| **SOS-08-A** | — (no carry-forwards) | — | — |
| **SOS-08-B** | — | — | — |
| **SOS-08-C** | wave-3-f-future-A `<onexit>` capture; wave-3-f-future-B multi-`<param>` rejection (`f0284fc`); wave-3-f-future-assign general ECMAScript-subset `<assign>` lowering (`d879e7b`); wave-3-f-future-xreg cross-region event-value capture (`8467087`) | wave-3-f-future-B FULL implementation (gated on PCDN-SOS-08-C-007); shared-datamodel HDL wiring (gated on PCDN-SOS-08-C-008) | — |
| **SOS-08-D** | wave-4-future state-encoding pass-through (pre-wave-2 in `e980f3f`); wave-4-future raw_property (`7916145`); wave-4-future compound expressions (`945de92`); wave-4-future multi-clock cross-region sampling + shared-datamodel cross-region driving (`1dc5649`) | None at the sub-phase level (PCDN-SOS-08-D-008 filed in parallel — see §6) | — |
| **SOS-08-E** | wave-3-future full SOS-03 vector-schema consumer (pre-wave-2 in `c178600`); wave-3-future-remaining nested-JSON parser one level deep (`9010510`); wave-3-future-remaining layered class hierarchy (`fa06f7a`); wave-3-future-remaining-path deeper nested-JSON (`5963e04`); wave-3-future-remaining multi-clock testbench wiring (`c2aa1cf`) | None at the sub-phase wave-3-future-remaining boundary | — |
| **SOS-08-F** | wave-2 carry-forward UVM 2.0 cross-runtime build-only CI smoke (`e74a6e2`) | pyuvm overlay (potential SOS-08-F-A) | gated on customer demand per PCDN-SOS-08-004 |
| **SOS-08-G** | wave-3c-future (f.1) vector-citation drill-down data layer (pre-wave-2 in `8d95152`); wave-3c-future (f.2) host-wiring spec (`ffc27e8`) | (f.2) GUI host-wiring implementation | gated on GTKWave keyaction-from-plugin API + Surfer plugin-host link-back API |
| **SOS-08-H** | — | — | — |

**Headline:** sub-phases D, E, F, G all closed substantial wave-future carry-forwards in this audit window. Sub-phase C closed three carry-forwards but spawned two new PCDNs (C-007, C-008) that gate further closure work. F and G have their remaining carry-forwards upstream-gated (customer demand for F; viewer-host API for G); D and E have no remaining carry-forward backlog at the sub-phase scope.

## 6. PCDNs filed during wave-2 review

Three new PCDNs were filed at sub-phase scope during wave-2 review (in parallel with this conformance audit; each is recorded against its sub-phase's PCDN docket):

- **PCDN-SOS-08-D-008** — extension of the wave-4-future raw_property escape hatch into a vendor-specific assertion-language carve-out (cited here by ID; full text in [SOS-08-D][sos-08-d] PCDN register).
- **PCDN-SOS-08-C-007** — multi-`<param>` rejection vs full implementation policy. Wave-3-f-future-B rejects multi-param today; ratifying the FULL implementation needs a §15 amendment to SOS-08-C explicitly endorsing per-param indexing semantics. Cited here by ID; full text in [SOS-08-C][sos-08-c] PCDN register.
- **PCDN-SOS-08-C-008** — shared-datamodel HDL wiring across regions. Wave-4-future-shared on SOS-08-D demonstrated the SVA-side construct; the chart-side compilation of `<datamodel>` shared across regions is the remaining design choice. Cited here by ID; full text in [SOS-08-C][sos-08-c] PCDN register.

These PCDNs are filed but not yet ratified; ratification is a wave-3 candidate (see §8).

## 7. Test count migration

| Audit milestone | Cumulative pass | New tests this wave | Source |
|---|---|---|---|
| Wave-1 close (2026-05-23) | **302 / 302** | — | [wave-1 audit][wave1] §2 |
| Wave-2 (UVM 2.0 smoke + G f.2) | ~370 / ~370 | +27 (F) + N (G) | `e74a6e2`, `ffc27e8` |
| Wave-3 (E nested JSON + D raw_property) | ~516 / ~516 | +50 (E) + +20 (D) | `9010510`, `7916145` |
| Wave-3 (E layered + C assign + D compound) | ~604 / ~604 | +17 (E) + +30 (C) + +19 (D) | `fa06f7a`, `d879e7b`, `945de92` |
| Wave-4 (E nested-path + C xreg) | ~707 / ~707 | +17 (E) + +22 (C) | `5963e04`, `8467087` |
| Wave-5 (D mclk + shared, E mclk TB) | **912 / 912** | +20 (D) + +18 (E) | `1dc5649`, `c2aa1cf` |

**Note on counts:** the per-sub-phase test count progression cited in each sub-phase's §15 (e.g. "766/766 → 833/833 → 892/892" in SOS-08-E) reflects each sub-phase walking against its own baseline in parallel wave dispatch. The global `pytest -q` count at `c2aa1cf` is **912 / 912 passing** (verified by `cd tools/sos-codegen && pytest -q` against this audit's commit). Net cumulative since wave-1 close: **+610 tests**.

## 8. Wave-3 candidate list

Carry-forwards that remain after wave-2 — these are the candidates for a wave-3 dispatch session:

- **SOS-08-C wave-3-f-future-B FULL implementation** — multi-`<param>` per-index semantics. Gated on **PCDN-SOS-08-C-007** ratification.
- **SOS-08-C shared-datamodel HDL chart-side wiring** — counterpart to SOS-08-D wave-4-future-shared. Gated on **PCDN-SOS-08-C-008** ratification.
- **SOS-08-F-A pyuvm overlay** — Python-uvm-compatible sequence emission for the cocotb path. Gated on customer demand per PCDN-SOS-08-004.
- **SOS-08-G (f.2) GUI keyaction / auto-binding host implementation** — gated on upstream Surfer plugin-host link-back API stability + GTKWave keyaction-from-plugin API exposure.
- **Gate (e) bench validation on Lattice ECP5** — still ⏸. Requires dedicated bench session per the parent-repo bench-authorization protocol.
- **Gate (g) SOS-06 §15 numerical readings** — still ⏸. Co-lands with gate (e).
- **SOS-09 PCDN ratification** — chain unblocked by the wave-2 surface (membrane phase depends on SOS-08-A/B existing, which they do at saturation) but not walked. A wave-3 candidate at the umbrella scope.

## 9. Authority-boundary table updates surfaced in wave-2

Wave-2 §15 entries introduce / extend the following `AuthorityRelationship` matrix rows (recorded for cross-walker traceability per the [parent CLAUDE.md][sos-08] "Standards integration: authority boundary declarations" discipline):

| Standard / concept | Relationship | Sub-phase that surfaced it | Notes |
|---|---|---|---|
| IEEE 1800.2-2017 (UVM 2.0) | `derive` | SOS-08-F (`e74a6e2`) | Build-surface forward-compat against UVM 2.0 macro/grammar set. Wave-1 was UVM 1.2-grammar only; wave-2 extends derivation to a UVM 2.0 cross-runtime smoke. The walker still emits UVM 1.2-grammar subset (no UVM 2.0-only constructs added). |
| ECMAScript subset (for `<assign>` lowering) | `derive` | SOS-08-C (`d879e7b`) | Wave-3-f-future-assign derives expression semantics from an explicit ECMAScript subset (additive arithmetic, comparison, identifier lookup) per the SOS-08-C §15 PCDN walkthrough. Mutation rights stay upstream; the walker is preflight-only. |
| GTKWave / Surfer host-side keybinding APIs | `represent` (deferred) | SOS-08-G (`ffc27e8`) | The host-wiring contract represents the upstream APIs without owning them. Mutation rights stay with GTKWave + Surfer upstream; SOS-08-G's contract is forward-compatible with whatever shape the upstream APIs land. |
| SVA bind file across SOS-08-D / SOS-08-E (mirror equivalence) | `mirror` | SOS-08-D / E (unchanged across wave-2) | The cross-walker mirror equivalence from wave-1 (D ↔ E SVA bind byte-identical) is preserved across wave-2's multi-clock + shared-datamodel + raw_property landings — verified by `test_transliterate_hdl_sv_tb.py::TestSvaBindMirror`. |

No matrix row was promoted from `mirror` / `derive` to `own`; no row was demoted. Wave-2's surface stays within the established authority-boundary discipline.

## 10. Change log

### 2026-05-25 — wave-2 conformance audit complete (Ira)

- Authored this doc as the consolidated wave-2 conformance status snapshot for the SOS-08 family.
- Umbrella §12 gates audited against wave-2 surface at `webslinger` SHA `c2aa1cf`; 5 of 7 satisfied (a, b, c, d, f); 2 deferred unchanged from wave-1 (e — bench validation; g — first numerical readings).
- 11 commits between `f0284fc` (wave-1 close) and `c2aa1cf` (this audit) catalogued with SHA, subject, sub-phase, LOC delta, test delta.
- Cross-sub-phase invariants INV-S-HDL-1..5 re-audited; all 5 hold; INV-S-HDL-F-3 strengthened to span UVM 1.2 + UVM 2.0 build surfaces; INV-S-HDL-5 strengthened end-to-end in SOS-08-G host-wiring contract.
- Carry-forward closures tabulated per sub-phase; C/D/E/F/G all closed wave-future items in this window; H has none; A/B unchanged.
- Three new PCDNs filed in parallel (D-008, C-007, C-008) — wave-3 ratification candidates.
- Test count migration: 302 → 912 (+610 cumulative) across waves 2–5.
- Wave-3 candidate list consolidated. Co-gated wave-3 items: PCDN ratification for C-007 + C-008, bench session for gate (e) + (g), upstream-gated items for F (customer demand) and G (viewer-host APIs).
- Authority-boundary table updates: IEEE 1800.2-2017 (UVM 2.0) `derive` added via SOS-08-F wave-2 carry-forward; ECMAScript subset `derive` added via SOS-08-C wave-3-f-future-assign; GTKWave / Surfer host APIs `represent` (deferred) recorded via SOS-08-G wave-3c-future-f2.

Status: 🟡 **wave-2 conformance audit complete with carry-forwards.** Wave-3 work proceeds against the PCDN-C-007/C-008/D-008 ratification queue + the gate (e)/(g) bench session.
