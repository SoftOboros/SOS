# SOS-08 wave-3 conformance review

**Status:** 🟢 **wave-3 audit complete 2026-05-25.** 5 of 7 acceptance gates satisfied; same two gates remain ⏸ as wave-1 / wave-2 (gate (e) bench validation, gate (g) numerical readings). Wave-3 closes every remaining sub-phase wave-future carry-forward at the SOS-08 family level — there is no software-tractable backlog left at the SOS-08 scope — but does not move the two deferred umbrella gates, both still co-gated on a single Lattice ECP5 bench session.

**Document type:** Informative audit. This doc walks the [SOS-08 umbrella][sos-08] §12 acceptance checklist against the wave-3 surface at `webslinger` SHA `fb621ed`. It does NOT declare new normative content — every claim cites the artifact (concept-doc §15 entry, source file, or test suite) that establishes it. Sibling of [`SOS-08-WAVE1-CONFORMANCE.md`][wave1] (frozen as of 2026-05-23, 302/302 tests) and [`SOS-08-WAVE2-CONFORMANCE.md`][wave2] (frozen as of 2026-05-25, 912/912 tests). This doc covers waves 2b through 7 (PCDN ratification + implementation + cleanup) plus the PCDN-SOS-09-001 amendment that landed between `c2aa1cf` and `fb621ed`.

**Purpose:** Provide a single agent-readable + reviewer-readable snapshot of the SOS-08 family's wave-3 status so the umbrella's conformance position is unambiguous without re-walking eight separate sub-phase docs plus the SOS-09 amendment. The "spec-to-silicon" article narrative depends on knowing which gates flipped, which carry-forwards closed, and which remain open at the wave-3 close.

[sos-08]: ./SOS-08-CONCEPTS.md
[sos-08-a]: ./SOS-08-A-CONCEPTS.md
[sos-08-b]: ./SOS-08-B-CONCEPTS.md
[sos-08-c]: ./SOS-08-C-CONCEPTS.md
[sos-08-d]: ./SOS-08-D-CONCEPTS.md
[sos-08-e]: ./SOS-08-E-CONCEPTS.md
[sos-08-f]: ./SOS-08-F-CONCEPTS.md
[sos-08-g]: ./SOS-08-G-CONCEPTS.md
[sos-08-h]: ./SOS-08-H-CONCEPTS.md
[sos-09]: ./SOS-09-CONCEPTS.md
[sos-06]: ./SOS-06-CONCEPTS.md
[sos-07]: ./SOS-07-CONCEPTS.md
[wave1]: ./SOS-08-WAVE1-CONFORMANCE.md
[wave2]: ./SOS-08-WAVE2-CONFORMANCE.md

## 0. Status banner

🟢 **wave-3 conformance audit complete 2026-05-25.** 5 of 7 umbrella gates ✅ (same five as wave-1 / wave-2: (a), (b), (c), (d), (f)). Two gates ⏸: (e) ECP5 bench validation, (g) SOS-06 §15 numerical readings. Wave-3 lands +346 tests cumulatively (912 → 1258), ratifies and implements all three wave-2 carry-forward PCDNs (D-008, C-007, C-008), lands a wave-7 coherence cleanup (W7CLN — fixtures, fallbacks, shared-signal RHS hardening) that removes obsolete soft-fallbacks from the D + E walkers, and amends PCDN-SOS-09-001 from the original xmlns-namespace resolution to the `other_attributes` extension surface. The SOS-08 family has no remaining software-tractable wave-future carry-forward at the sub-phase scope.

## 1. Purpose

Audit the umbrella §12 acceptance checklist against the `webslinger` source tree at SHA `fb621ed`. Informative, not normative — the canonical normative content lives in each sub-phase's `-CONCEPTS.md` §15 change log and (for the SOS-09 amendment) in [SOS-09 §16][sos-09].

This doc supersedes nothing in [`SOS-08-WAVE2-CONFORMANCE.md`][wave2] — wave-2 is frozen as the wave-2 audit. This doc covers wave-2b through wave-7 inclusive: PCDN-D-008 / C-007 / C-008 filing + ratification + implementation, the wave-7 coherence cleanup, and the PCDN-SOS-09-001 amendment. The numbering follows the wave-3 audit perspective: from wave-2 close (912/912) to wave-3 close (1258/1258).

## 2. Scope — commits landed since wave-2 close

The 14 commits below landed on `webslinger` between wave-2 close (`c2aa1cf`, 2026-05-25) and this audit (`fb621ed`, 2026-05-25). Listed in chronological order (oldest first). Note: the dispatch prompt anticipated 15 commits; the actual range carries 14 — the wave-2 audit commit (`82a49af`) is itself inside this range because the wave-2 audit was authored AFTER the wave-2 work landed but BEFORE the wave-3 work began. The discrepancy is informative-only; the audit still covers everything between `c2aa1cf` (wave-2 work close) and `fb621ed` (wave-3 close).

| SHA | Subject | Sub-phase | LOC (ins/del) | Test delta |
|---|---|---|---|---|
| `cb3001c` | SOS08D008 — file PCDN-SOS-08-D-008 + pin compound traversal order | SOS-08-D wave-3 PCDN-filing | +338 / 0 | doc-assertion |
| `83c9aba` | SOS08D4cf — align compound traversal order to alphabetic spec text | SOS-08-D wave-3 compound-order fix | +135 / −6 | walker fix |
| `82a49af` | SOS08W2 — wave-2 conformance audit + SOS-08-E `$display`→`$error` verb pin | meta + SOS-08-E §15 amendment | +627 / 0 | +20 (wave-2 audit module) |
| `a396c67` | SOS08C78b — file PCDN-SOS-08-C-007 + C-008 + boolean-literal §15 widening | SOS-08-C wave-3 PCDN-filing | +379 / 0 | doc-assertion |
| `5d25063` | SOS08D008R — ratify PCDN-SOS-08-D-008 (`<sos:clock_domains>` formalised) | SOS-08-D wave-3 ratification | +583 / 0 | doc-assertion |
| `e6f84f5` | SOS08C78R — ratify PCDN-SOS-08-C-007 + C-008 with addenda | SOS-08-C wave-3 ratification | +589 / −2 | doc-assertion |
| `b193cf0` | SOS08ED008X — cross-reference PCDN-SOS-08-D-008 ratification in SOS-08-E §15 | SOS-08-E wave-3 cross-ref | +296 / 0 | doc-assertion |
| `93de5f5` | SOSINV1 — chart-inventory + vector-migration audit for PCDN-SOS-08-C-007 | meta + chart-fixture audit | +633 / 0 | inventory |
| `3566eb1` | SOS08D008I — implement `<sos:clock_domains>` walker D-side + shared helper | SOS-08-D wave-3 implementation | +1501 / −29 | +N1 |
| `df890f2` | SOS08C007I — per-`<param>` sub-bus emit + suffix routing (HDL walkers) | SOS-08-C wave-3 implementation | +1593 / −133 | +N2 |
| `192a189` | SOS08CE008I — E walker consumes shared `_clock_domains` helper (wave-7b) | SOS-08-E wave-7b implementation | +759 / −105 | +N3 |
| `37d0145` | SOS08C008I — implement PCDN-SOS-08-C-008 shared-signal HDL wiring | SOS-08-C wave-3 implementation | +1645 / 0 | +N4 |
| `3ea7526` | SOS09001A — land PCDN-SOS-09-001 amendment (channel annotations on `other_attributes`) | SOS-09 amendment | +671 / −9 | +N5 |
| `fb621ed` | SOS7CLN — wave-7 coherence cleanup (fixtures, fallbacks, shared-RHS hardening) | SOS-08-C/D/E cleanup | +1067 / −207 | +12 |

**Cumulative:** ~10,856 lines inserted, ~491 lines deleted, ~+346 net new tests. The wave-3 surface is dominated by ratification + implementation of the three wave-2 carry-forward PCDNs (cb3001c → 37d0145), followed by the SOS-09 amendment and the wave-7 coherence cleanup. The per-commit test deltas (`+N1..+N5`) are not enumerated individually here — the cumulative move from 912 to 1258 (+346) is verified by `cd tools/sos-codegen && pytest -q` against this audit's commit.

## 3. Per-gate audit — umbrella §12 acceptance checklist

The umbrella's seven gates are quoted from [SOS-08-CONCEPTS.md §12][sos-08]:

### Gate (a) — PCDNs resolved

> *"PCDN-SOS-08-001 through 011 resolved."*

- **Wave-2 status:** ✅ (per [wave-2 audit][wave2] §3).
- **Wave-3 status:** ✅ unchanged. The 11 umbrella PCDNs remain resolved. Wave-3 ratified the three wave-2-surfaced sub-phase PCDNs (PCDN-SOS-08-D-008, PCDN-SOS-08-C-007, PCDN-SOS-08-C-008 — see §6) which are filed and ratified at the sub-phase scope. They do NOT reopen umbrella PCDN-001..011.

### Gate (b) — Sub-phase concept docs

> *"Each sub-phase SOS-08-A through SOS-08-H has its own concept doc drafted and ratified."*

- **Wave-2 status:** ✅ unchanged from wave-1.
- **Wave-3 status:** ✅ unchanged. All eight sub-phase docs still carry `Status: 🟢 ratified` headers; wave-3 §15 entries extend the change logs without rotating ratification status. PCDN-SOS-08-D-008 ratification (`5d25063`) formalises `<sos:clock_domains>` as a chart-top vocabulary element; PCDN-SOS-08-C-007 + C-008 ratification (`e6f84f5`) formalises per-`<param>` sub-bus naming and shared-datamodel HDL wiring. Wave-7 coherence cleanup (`fb621ed`) tightens existing normative content without re-rotating ratification.

### Gate (c) — L0 primitive surface

> *"At least one L0 primitive (recommended: `sos_fifo_async`) is implemented as portable RTL + cocotb tests + SVA properties as a worked-example exercise of the SOS-08-A contract."*

- **Wave-2 status:** ✅✅ over-satisfied (16 primitives: 11 L0 + 5 L1).
- **Wave-3 status:** ✅✅ unchanged. Wave-3 added no new primitives; primitive surface is at saturation for the SOS-08-A wave-1 contract. The PCDN-SOS-08-C-008 shared-signal HDL wiring (`37d0145`) exercises the existing chart-top wrapper boundary — it doesn't author a new primitive. The wave-7 cleanup's "literal-zero degradation removed for VHDL ident RHS" fix routes through `data_<ident>` chart-top ports — same primitive surface.

### Gate (d) — Codegen HDL-emit path

> *"The codegen tool gains an HDL-emit path; chart → VHDL + SystemVerilog emission tested on at least one chart."*

- **Wave-2 status:** ✅ extended (302 → 912 tests, +610).
- **Wave-3 status:** ✅ extended further. The codegen surface now additionally spans:
    - SOS-08-D `<sos:clock_domains>` walker (`3566eb1`) — formal multi-clock declaration vocabulary; `kind="rising"` REQUIRED per wave-7a §15.
    - SOS-08-C per-`<param>` sub-bus emit + suffix routing (`df890f2`) — wave-3-f-future-B FULL implementation (multi-`<param>` per-index semantics).
    - SOS-08-C shared-signal HDL wiring (`37d0145`) — chart-side counterpart to wave-4-future-shared.
    - SOS-08-E shared `_clock_domains` helper consumption (`192a189`) — wave-7b cross-walker consolidation.
    - Wave-7 coherence cleanup (`fb621ed`) — fixture updates to make `kind=` explicit, removal of E walker's `_backfill_implicit_kind` soft-fallback, removal of D walker's pre-7a parseability-probe fallback, hardening of shared-signal writer RHS to formal same-region-only.
- Test count moves 912 → 1258 (+346). Walker surface has no remaining open carry-forwards at the sub-phase scope.

### Gate (e) — ECP5 bench validation

> *"Bench validation: on a Lattice ECP5 dev board (per PCDN-SOS-08-006), the worked-example chart synthesizes via Yosys+nextpnr, places + routes, and passes its cocotb tests against the generated bitstream's behaviour as observed via a simulator (Verilator)."*

- **Wave-2 status:** ⏸ deferred.
- **Wave-3 status:** ⏸ **unchanged.** No bench-session artifacts landed under `docs/experiments/` between wave-2 close and 2026-05-25 wave-3 close. The ECP5 board is bounded by the parent-repo bench-authorization protocol; the session has not been authorized in this window. Wave-3 work is entirely software-tractable.

### Gate (f) — Cross-phase invariants citation

> *"Cross-phase invariants INV-SOS-A through H cited correctly in each sub-phase doc."*

- **Wave-2 status:** ✅ strengthened (UVM 1.2 + 2.0 single-source scoreboard).
- **Wave-3 status:** ✅ strengthened further. Every wave-3 §15 ratification entry re-cites the cross-phase invariants it touches. The PCDN-SOS-08-D-008 ratification cites INV-SOS-A (codegen authority), INV-SOS-C (vector-traceable HDL), and INV-S-HDL-3 (cross-domain isolation). The PCDN-SOS-08-C-007 + C-008 ratification cites INV-S-HDL-1 (handshake-compatible ports — per-`<param>` sub-buses preserve the ready/valid topology) and INV-S-HDL-2 (static allocation — sub-bus emit is fully static, no dynamic indexing). The wave-7 cleanup citation chain reinforces INV-S-HDL-1 (shared-signal writer RHS topology) and INV-S-HDL-2 (literal-zero degradation removed — no dynamic fallback). See §4.

### Gate (g) — SOS-06 §15 amendment

> *"SOS-06 §15 amendment co-landed extending the seven metrics to HDL targets."*

- **Wave-2 status:** ✅ paper / ⏸ numbers.
- **Wave-3 status:** ✅ paper / ⏸ numbers — **unchanged.** Numerical readings remain co-gated on the gate (e) bench session. The paper translation (`AreaFootprint` / `StaticAllocationFootprint` / `MacrostepClockCount` / `BuildTime`) is in place; first data points await ECP5 bench. The wave-3 surface adds two emit forms (`<sos:clock_domains>` and shared-signal HDL) that will produce additional area + macrostep readings once gate (e) lands.

### Summary

| Gate | Wave-1 | Wave-2 | Wave-3 | Movement (W2 → W3) |
|---|---|---|---|---|
| (a) | ✅ | ✅ | ✅ | unchanged (3 sub-phase PCDNs ratified at sub-phase scope) |
| (b) | ✅ | ✅ | ✅ | unchanged (PCDN ratifications extend §15s, no re-rotation) |
| (c) | ✅✅ | ✅✅ | ✅✅ | unchanged |
| (d) | ✅ | ✅ | ✅ | extended (codegen surface +346 tests; no open carry-forwards) |
| (e) | ⏸ | ⏸ | ⏸ | unchanged (bench not yet authorized) |
| (f) | ✅ | ✅ | ✅ | strengthened further (PCDN ratifications + cleanup re-cite invariants) |
| (g) | ✅ paper / ⏸ numbers | ✅ paper / ⏸ numbers | ✅ paper / ⏸ numbers | unchanged (co-gated on (e)) |

## 4. Cross-sub-phase invariants — INV-S-HDL-1..5 re-audit

The umbrella's five cross-sub-phase invariants (§7) hold across the wave-3 surface. Wave-3 introduced new emission forms that touch each, and each is preserved:

| Invariant | Wave-3 satisfaction |
|---|---|
| **INV-S-HDL-1** — handshake-compatible ports (req/ack OR ready/valid) | SOS-08-C per-`<param>` sub-bus emit (`df890f2`) preserves the existing event-port ready/valid topology, adding per-index suffix routing without altering the handshake shape — see [SOS-08-C][sos-08-c] §15 PCDN-007 ratification entry. SOS-08-C shared-signal HDL wiring (`37d0145`) routes shared signals through the chart-top wrapper without touching event-port handshakes. Wave-7 cleanup (`fb621ed`) formalises same-region-only writer RHS — cross-region writes raise `UnsupportedChartError`, preserving the invariant by construction. |
| **INV-S-HDL-2** — static allocation, no dynamic in any emission | SOS-08-D `<sos:clock_domains>` walker (`3566eb1`) emits only static clock declarations — no dynamic dispatch. SOS-08-C per-`<param>` sub-buses (`df890f2`) use fixed-index suffix routing — fully static, no dynamic indexing. Wave-7 cleanup (`fb621ed`) removes the VHDL walker's literal-zero degradation for ident RHS — owner-region ident RHS now lowers correctly via the chart-top wrapper's `data_<ident>` port without dynamic fallback. Audit verified: grep for `malloc` / `new` outside of constructor-style use returns nothing in the wave-3 emission set. |
| **INV-S-HDL-3** — cross-domain isolation via `sos_synchronizer` / `sos_fifo_async` | SOS-08-D `<sos:clock_domains>` walker (`3566eb1`) formalises chart-top clock declarations consumed by both D + E walkers (via the shared helper `_collect_chart_clock_decls`, wave-7b consolidation in `192a189`). Cross-domain boundaries continue to instantiate `sos_synchronizer` per the SOS-08-C §6.10 multi-clock contract. The wave-7 cleanup raises a `ClockDomainsParseError → UnsupportedChartError` at the parse boundary if `kind=` is missing — failing closed rather than substituting an implicit default. |
| **INV-S-HDL-4** — cooperative-only at v1 (per EOQ-008) | SOS-08-H freeze unchanged. No wave-3 entry introduces preemption; SCXML-LINT-H-1 still rejects `<state preemptive="true">` at chart-compile time. |
| **INV-S-HDL-5** — vector-to-chart traceability for HDL | Preserved across wave-3: SOS-08-C per-`<param>` sub-bus emit (`df890f2`) preserves chart-vocabulary suffix in the emitted signal names (e.g. `evt_foo_param_x_data`, `evt_foo_param_y_data`) — chart-vocab fields survive the wave-3-f-future-B FULL implementation. The shared-signal HDL wiring (`37d0145`) names the `data_<ident>` chart-top port with the chart-declared datamodel identifier — chart-vocab preserved end-to-end. The SOS-09-001 amendment (`3ea7526`) ensures `other_attributes` channel annotations preserve their `sos:`-prefixed STRING keys through the round-trip, preserving chart-vocabulary on the channel-annotation surface as well. |

### New / extended invariants surfaced in wave-3

- **INV-S-HDL-C-2 cross-region writer RHS** — strengthened. The wave-7 cleanup (`fb621ed`) formalises that `<sos:shared_signal>` writer RHS expressions MUST reference only same-region datamodel idents. Cross-region writes raise `UnsupportedChartError` with the canonical `SOS-08-C wave-future-shared-xreg-rhs:` prefix in both D + E walkers. The constraint was previously implicit (the VHDL walker's literal-zero degradation made it work by accident); wave-7 cleanup makes it explicit and consistent across SV + VHDL. See [SOS-08-C][sos-08-c] §15 wave-7 cleanup entry.
- **INV-S-HDL-D-clock-decl** (new) — wave-3 surface adds the requirement that `<sos:clock_domains>` declarations carry `kind="rising"` (or `falling`) explicitly. The wave-7 cleanup removes the E walker's `_backfill_implicit_kind` soft-reading and the D walker's pre-7a parseability-probe fallback; missing `kind=` propagates as `UnsupportedChartError` rather than silently substituting an implicit default. See [SOS-08-D][sos-08-d] §15 PCDN-008 ratification + wave-7a `kind=` REQUIRED amendment.

**Audit conclusion:** All five cross-sub-phase invariants hold across the wave-3 surface; INV-S-HDL-C-2 (cross-region writer RHS) and INV-S-HDL-D-clock-decl (explicit `kind=`) are operationally strengthened by the wave-7 cleanup. No invariant is reopened or weakened.

## 5. Carry-forward closures by sub-phase

The table below summarises which wave-future carry-forwards closed in wave-3, which remain open at the sub-phase scope, and which are upstream-gated. **Headline:** the SOS-08 family has zero remaining software-tractable wave-future carry-forwards at the sub-phase scope after wave-3.

| Sub-phase | Closed in wave-3 | Remains open | Upstream-gated |
|---|---|---|---|
| **SOS-08-A** | — (no carry-forwards from wave-2) | — | — |
| **SOS-08-B** | — | — | — |
| **SOS-08-C** | wave-3-f-future-B FULL implementation (per-`<param>` sub-buses, `df890f2` — closes PCDN-SOS-08-C-007 carry-forward); shared-datamodel HDL chart-side wiring (`37d0145` — closes PCDN-SOS-08-C-008 carry-forward); wave-7 cleanup hardens same-region-only shared-signal writer RHS (`fb621ed`) | None at the sub-phase wave-future scope | — |
| **SOS-08-D** | `<sos:clock_domains>` walker D-side + shared helper (`3566eb1` — closes PCDN-SOS-08-D-008 carry-forward); compound traversal alphabetic-spec alignment (`83c9aba`); wave-7 cleanup removes pre-7a parseability-probe fallback (`fb621ed`) | None at the sub-phase wave-future scope | — |
| **SOS-08-E** | `$display`→`$error` walker-emit verb pin (`82a49af`); cross-reference of PCDN-SOS-08-D-008 ratification in §15 (`b193cf0`); shared `_clock_domains` helper consumption (`192a189` — wave-7b cross-walker consolidation); wave-7 cleanup fixtures updated + `_backfill_implicit_kind` removed (`fb621ed`) | None at the sub-phase wave-future scope | — |
| **SOS-08-F** | — (no wave-3 sub-phase work) | pyuvm overlay (potential SOS-08-F-A) | gated on customer demand per PCDN-SOS-08-004 |
| **SOS-08-G** | — (no wave-3 sub-phase work) | (f.2) GUI host-wiring implementation | gated on GTKWave keyaction-from-plugin API + Surfer plugin-host link-back API |
| **SOS-08-H** | — | — | — |

**Headline:** sub-phases C, D, E closed every remaining wave-future carry-forward in wave-3 via PCDN ratification + implementation pairs (D-008, C-007, C-008). F and G have only upstream-gated items remaining (customer demand for F; viewer-host API for G). A, B, H have no carry-forwards. The wave-7 coherence cleanup tightened normative content across C, D, E without surfacing new carry-forwards. The SOS-08 family is now in a "no software-tractable backlog" state at the sub-phase scope; future SOS-08 work is gated on the bench session (gate (e) + (g)) or upstream APIs (F-A, G f.2).

## 6. PCDNs filed during wave-3 review

Wave-3 ratified the three sub-phase PCDNs surfaced during wave-2 review and amended one umbrella-scope PCDN that lives in the SOS-09 sibling phase:

- **PCDN-SOS-08-D-008** — `<sos:clock_domains>` element formalised at chart-top.
  - **Filed** `cb3001c` (compound traversal-order pin + PCDN docket entry).
  - **Ratified** `5d25063` (full §6 + §15 entry on SOS-08-D).
  - **Implemented** `3566eb1` (walker D-side + shared `_collect_chart_clock_decls` helper).
  - **Cross-referenced** in SOS-08-E §15 (`b193cf0`).
  - **Wave-7b consumption** in SOS-08-E walker (`192a189`).
- **PCDN-SOS-08-C-007** — per-`<param>` sub-bus naming + suffix-routing semantics (closes wave-3-f-future-B FULL implementation gate).
  - **Filed + ratified** in same window: `a396c67` (filing + boolean-literal §15 widening addendum), `e6f84f5` (ratification).
  - **Pre-ratification chart-inventory audit** `93de5f5` to verify migration cost across existing chart fixtures.
  - **Implemented** `df890f2` (per-`<param>` sub-bus emit + suffix routing in both HDL walkers).
- **PCDN-SOS-08-C-008** — shared-datamodel HDL wiring across regions (closes wave-4-future-shared chart-side counterpart).
  - **Filed + ratified** in same window: `a396c67` (filing), `e6f84f5` (ratification).
  - **Implemented** `37d0145` (chart-side compilation of `<datamodel>` shared across regions via chart-top wrapper).
  - **Hardened** `fb621ed` (wave-7 cleanup: same-region-only writer RHS enforced; cross-region writes raise `UnsupportedChartError`).
- **PCDN-SOS-09-001 amendment** — SOS-09 channel annotations move from a custom XML namespace (`xmlns:sos`) to iState's `other_attributes` extension surface with a `sos:` STRING prefix inside the JSON.
  - **Amended** `3ea7526` (full re-ratification at [SOS-09 §16][sos-09]). Original PCDN-001 marked 🟡 superseded; institutional memory preserved in the §16 row.
  - **Scope:** SOS-09 channel ANNOTATIONS only. Preserves SOS-08-D / -E namespaced ELEMENT vocabulary (`<sos:cross_invariant>`, `<sos:clock_domains>`, `<sos:shared_signal>`) — those are new elements, separately ratified, outside this amendment's scope.

All three SOS-08 sub-phase PCDNs traversed the full file → ratify → implement cycle within wave-3. The SOS-09-001 amendment is filed + ratified; implementation work has not begun (SOS-09 implementation is a wave-4 candidate, see §8).

## 7. Test count migration

| Audit milestone | Cumulative pass | New tests this wave | Source |
|---|---|---|---|
| Wave-1 close (2026-05-23) | **302 / 302** | — | [wave-1 audit][wave1] §2 |
| Wave-2 close (2026-05-25) | **912 / 912** | +610 cumulative | [wave-2 audit][wave2] §7 |
| Wave-2b (W2 audit + PCDN filings) | ~932 / ~932 | +20 (W2 audit module) | `82a49af`, `cb3001c`, `a396c67` |
| Wave-3 ratifications (D-008 + C-007/008) | ~975 / ~975 | doc-assertion modules | `5d25063`, `e6f84f5`, `b193cf0`, `93de5f5` |
| Wave-3 implementations | ~1234 / ~1234 | walker + integration tests | `3566eb1`, `df890f2`, `192a189`, `37d0145` |
| Wave-3 SOS-09-001 amendment | ~1246 / ~1246 | +N5 amendment-assertion module | `3ea7526` |
| Wave-7 coherence cleanup (W3 close) | **1258 / 1258** | +12 cleanup-coherence | `fb621ed` |

**Note on counts:** the per-commit deltas above are approximate intermediate snapshots; the audit point of truth is `cd tools/sos-codegen && pytest -q` at `fb621ed` → **1258 passed, 1 skipped** (verified 2026-05-25). Net cumulative since wave-2 close: **+346 tests**. Net cumulative since wave-1 close: **+956 tests** (302 → 1258).

## 8. Wave-4 candidate list

After wave-3, the SOS-08 family has no remaining software-tractable carry-forwards at the sub-phase scope. The wave-4 candidate list is dominated by **SOS-09 sub-phase concept doc drafts** (foundational concept work that does not block on bench) plus the persistent gate (e) / (g) bench items and upstream-gated F/G follow-ons:

- **SOS-09 sub-phase concept docs (SOS-09-A through SOS-09-G — seven docs)** — foundational concept-doc drafting for the membrane phase. PCDN-SOS-09-001 is now amended + ratified; the next gating step is drafting the per-sub-phase concept docs (SOS-09-A channel-annotation contract, -B membrane vocabulary, etc.). No code lands in wave-4 sub-phase drafting; concept-doc shape only. Sequential — these are typically the orchestrator's serial-dispatch surface in front of any parallel wave-5 implementation.
- **SOS-09 implementation** — gated on the seven SOS-09 sub-phase concept docs ratifying. Implementation reads channel annotations from `other_attributes` with `sos:`-prefixed keys per the PCDN-SOS-09-001 amendment.
- **SOS-08-F-A pyuvm overlay** — Python-uvm-compatible sequence emission for the cocotb path. Still gated on customer demand per PCDN-SOS-08-004.
- **SOS-08-G (f.2) GUI keyaction / auto-binding host implementation** — still gated on upstream Surfer plugin-host link-back API stability + GTKWave keyaction-from-plugin API exposure.
- **Gate (e) bench validation on Lattice ECP5** — still ⏸. Requires dedicated bench session per the parent-repo bench-authorization protocol.
- **Gate (g) SOS-06 §15 numerical readings** — still ⏸. Co-lands with gate (e).
- **Status-marker hygiene on §14 PCDN entries across SOS-08-A/B/C/D/E/F/G/H** — informative cleanup pass. The §14 PCDN registers across the eight sub-phase docs use a mix of 🟢 / 🟡 / ⚪ / no-marker conventions inherited from each sub-phase's pre-ratification draft history. A wave-4 cleanup pass would normalise these to the shared status-legend convention used in `ERRATA.md`. Non-blocking; informative only.

The SOS-09 sub-phase concept docs are the **next gating items** for the SOS-08 / SOS-09 axis taken together. Without them, no SOS-09 implementation can land; SOS-09 implementation is a load-bearing prerequisite for the membrane-aware integration narrative of the spec-to-silicon article.

## 9. Authority-boundary table updates surfaced in wave-3

Wave-3 §15 entries introduce / extend the following `AuthorityRelationship` matrix rows (recorded for cross-walker traceability per the [parent CLAUDE.md][sos-08] "Standards integration: authority boundary declarations" discipline):

| Standard / concept | Relationship | Sub-phase that surfaced it | Notes |
|---|---|---|---|
| `<sos:clock_domains>` element vocabulary (chart-top shape + identity model) | `own` | SOS-08-D (`5d25063`, `3566eb1`) | This repo authors the `<sos:clock_domains>` element grammar — `kind=` REQUIRED (post-wave-7a), `domain` / `name` attributes, alphabetic compound-order semantics. Full mutation rights gated by Standards Action on SOS-08-D §15. |
| `<sos:shared_signal>` element vocabulary (naming + ownership-by-region) | `own` | SOS-08-C (`e6f84f5`, `37d0145`, `fb621ed`) | This repo authors the `<sos:shared_signal>` element grammar — `owner_region` attribute, same-region-only writer RHS constraint (wave-7 cleanup), `data_<ident>` chart-top port naming. Full mutation rights gated by Standards Action on SOS-08-C §15. |
| Per-`<param>` sub-bus naming convention | `own` + `compose` | SOS-08-C (`e6f84f5`, `df890f2`) | The per-`<param>` sub-bus naming convention (`evt_<event>_<param>_data` / `_<param>_valid` / `_<param>_ready`) is owned by this repo; it composes over the existing SCXML `<param>` element shape (an upstream W3C SCXML element). The composition contract is recorded in [SOS-08-C][sos-08-c] §15 PCDN-007 ratification. |
| SOS-09 channel annotations on `other_attributes` | `compose` | SOS-09 (`3ea7526`) | SOS-09 composes over the upstream iState `other_attributes` extension surface — SOS-semantic channel-annotation keys (`sos:kind`, `sos:dir`, `sos:mutex`, etc.) attach as STRING-prefixed keys inside `other_attributes` rather than as XML-namespace-declared attributes. The iState `other_attributes` shape is upstream-owned; SOS adds a `sos:` STRING-prefix convention on top of it. Mirrors the existing `position_x` / `position_y` precedent. |
| ECMA-262 boolean-literal subset | `derive` (extension) | SOS-08-C (`a396c67`) | Wave-3 widens the ECMA-262 derive to cover boolean-literal handling (`true` / `false`) in `<assign>` expressions per the PCDN-007 filing addendum. Mutation rights stay upstream; the walker is preflight-only. |
| IEEE 1800-2017 §16.13 multi-clocked assertions | `derive` | SOS-08-D (`3566eb1`) | The `<sos:clock_domains>` walker emits multi-clocked SVA assertions per IEEE 1800-2017 §16.13. Mutation rights stay upstream; the walker derives clock-specific assertion construction from the IEEE grammar. |
| IEEE 1800-2017 §20.10.3 `$error` severity | `derive` | SOS-08-E (`82a49af`) | The `$display`→`$error` verb-change normative pin derives the simulator-severity contract from IEEE 1800-2017 §20.10.3. Recorded as a wave-2-close §15 amendment on SOS-08-E that landed inside the wave-3 commit range. |

No matrix row was promoted from `mirror` / `derive` to `own` *implicitly*; the new `own` rows (`<sos:clock_domains>`, `<sos:shared_signal>`) reflect this repo authoring new elements with explicit Standards Action ratification through SOS-08-D / -C PCDN ratification. The SOS-09 row (`compose` over `other_attributes`) is the load-bearing example of the SOS-09-001 amendment — the original "namespace own" position was retracted because composing over an existing iState extension surface preserves the scjson round-trip without forcing a new XML namespace into the chart-author surface.

## 10. Change log

### 2026-05-25 — wave-3 conformance audit complete (Ira)

- Authored this doc as the consolidated wave-3 conformance status snapshot for the SOS-08 family.
- Umbrella §12 gates audited against wave-3 surface at `webslinger` SHA `fb621ed`; 5 of 7 satisfied (a, b, c, d, f); 2 deferred unchanged from wave-1 / wave-2 (e — bench validation; g — first numerical readings).
- 14 commits between `c2aa1cf` (wave-2 work close) and `fb621ed` (wave-3 close) catalogued with SHA, subject, sub-phase, LOC delta. Note: dispatch anticipated 15 commits; actual range is 14 because the wave-2 audit commit (`82a49af`) sits inside this range rather than being adjacent to it. Coverage is complete from wave-2 work close to wave-3 close.
- Cross-sub-phase invariants INV-S-HDL-1..5 re-audited; all 5 hold; INV-S-HDL-C-2 (cross-region writer RHS) operationally strengthened by the wave-7 cleanup; new wave-3-surface invariant INV-S-HDL-D-clock-decl (explicit `kind=`) added via PCDN-D-008 ratification + wave-7a `kind=` REQUIRED amendment.
- Carry-forward closures tabulated per sub-phase; C, D, E closed every remaining wave-future carry-forward via PCDN ratification + implementation pairs (D-008, C-007, C-008). F and G have only upstream-gated items remaining. A, B, H have no carry-forwards. The SOS-08 family is in a "no software-tractable backlog" state at the sub-phase scope.
- Three sub-phase PCDNs traversed file → ratify → implement within wave-3 (D-008, C-007, C-008); SOS-09-001 amended in parallel (channel annotations move to `other_attributes`).
- Test count migration: 912 → 1258 (+346 cumulative across wave-3). Verified by `cd tools/sos-codegen && pytest -q` at `fb621ed`.
- Wave-4 candidate list consolidated. Next gating items: **SOS-09 sub-phase concept doc drafts (SOS-09-A through SOS-09-G — seven docs)** for the foundational concept work, followed by SOS-09 implementation. Persistent gate (e) / (g) bench items + upstream-gated F-A / G f.2 items remain. Informative status-marker hygiene cleanup on §14 PCDN entries surfaced as a non-blocking wave-4 cleanup pass.
- Authority-boundary table updates: `<sos:clock_domains>` and `<sos:shared_signal>` element vocabularies promoted to `own` via PCDN-D-008 and PCDN-C-008 ratification; per-`<param>` sub-bus naming convention recorded as `own` + `compose` over the upstream SCXML `<param>` element; SOS-09 channel annotations recorded as `compose` over iState `other_attributes`; ECMA-262 boolean-literal subset `derive` extension via PCDN-C-007 addendum; IEEE 1800-2017 §16.13 multi-clocked assertions `derive` via PCDN-D-008 implementation; IEEE 1800-2017 §20.10.3 `$error` severity `derive` via SOS-08-E verb-change pin.

Status: 🟢 **wave-3 conformance audit complete.** Wave-4 work proceeds against the SOS-09 sub-phase concept-doc drafting queue + the persistent gate (e)/(g) bench session + upstream-gated F-A / G f.2 items.
