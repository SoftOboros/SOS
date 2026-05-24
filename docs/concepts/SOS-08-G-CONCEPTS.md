# SOS-08-G — Waveform + transaction-level annotation emission (review artifact)

**Status:** 🟢 **ratified 2026-05-23** (see §15).

**Depends on:** [SOS-08][sos-08] (umbrella; vector emission priority §5.4), [SOS-08-D][sos-08-d] + [SOS-08-E][sos-08-e] (the generation points), [SOS-11][sos-11] (the chart-diff review surface this phase mirrors at hardware level), [SOS-07][sos-07] (INV-SOS-H load-bearing).

**Blocks:** none directly; unblocks the article's "agent edits chart, developer reviews both chart diff and waveform diff in one pass" demo.

> 🛑 **NO CODE.** Three-file output contract, JSON-Lines overlay schema, viewer-integration contract, generation-point integration with SOS-08-D/E, storage discipline, MCP-workflow integration. Implementation lands as a follow-up commit per spec-before-code discipline.

[sos-07]: ./SOS-07-CONCEPTS.md
[sos-08]: ./SOS-08-CONCEPTS.md
[sos-08-d]: ./SOS-08-CONCEPTS.md#sos-08-d--cocotb--sva-bind-files-primary
[sos-08-e]: ./SOS-08-CONCEPTS.md#sos-08-e--systemverilog-testbench--sva-bind-files
[sos-08-f]: ./SOS-08-CONCEPTS.md#sos-08-f--uvm-sequences-only
[sos-11]: ./SOS-11-CONCEPTS.md
[sos-12]: ./SOS-12-CONCEPTS.md
[sos-07-inv]: ./SOS-07-CONCEPTS.md#6-cross-phase-invariants--inv-sos-a-through-h
[inv-sos-a]: ./SOS-07-CONCEPTS.md#inv-sos-a--chart-as-source
[inv-sos-b]: ./SOS-07-CONCEPTS.md#inv-sos-b--vectors-as-deliverable-at-every-layer
[inv-sos-c]: ./SOS-07-CONCEPTS.md#inv-sos-c--mcp-as-sole-modification-surface
[inv-sos-h]: ./SOS-07-CONCEPTS.md#inv-sos-h--vector-to-chart-traceability
[roadmap]: ./SOS-ROADMAP-07-PLUS.md

## 0. Authority policy

This phase doc is the **per-sub-phase contract** for SOS-08-G under the [SOS-08][sos-08] umbrella (ratified 2026-05-23). The umbrella §5.4 freezes vector emission priority placing SOS-08-G fourth as the *review artifact* path (after SOS-08-D cocotb+SVA, SOS-08-E SV testbench+SVA, SOS-08-F UVM sequences). The umbrella §6 SOS-08-G row + EOQ-011-ROADMAP resolution name the three-file output contract: `.fst` + `.vcd` + JSON-Lines overlay (`{cycle, signal, chart_state, transition_id}`). This doc takes those decisions as load-bearing input and produces the per-phase contract: overlay schema, viewer integration, generation-point integration, storage discipline, MCP-workflow integration with [SOS-11][sos-11].

Per the parent CLAUDE.md "Spec-Before-Code Planning Discipline / Phase document shape":

- **Normative** sections: §3 glossary, §4 source-of-truth map, §5 frozen decisions (three-file output contract, overlay schema), §6 viewer integration contract, §7 cross-sub-phase invariants (INV-S-HDL-G-*), §8 standards integration matrix additions, §9 reconciliation vs adjacent sub-phases, §10 non-goals (informative — see below), §12 acceptance checklist.
- **Informative** sections: §1 purpose, §2 problem statement, §11 (not used), §14 non-goals overlap is here for convention, §15 change log.
- All keywords MUST, MUST NOT, SHALL, SHOULD, SHOULD NOT, MAY are interpreted per RFC 2119 / RFC 8174 when capitalised.

This doc cites [SOS-07 §6][sos-07-inv] for cross-phase invariants `INV-SOS-A` through `INV-SOS-H`, and [SOS-08 §7][sos-08] for cross-sub-phase invariants `INV-S-HDL-1` through `INV-S-HDL-5`. Neither set is re-derived. [INV-SOS-H][inv-sos-h] (vector-to-chart traceability) is the load-bearing cross-phase invariant; SOS-08-G is the operational realisation of INV-SOS-H at the *review surface* on the hardware side, as [SOS-11][sos-11] is its operational realisation at the *modification surface* on the chart side.

## 1. Purpose

To freeze the contract by which SOS-08-D's cocotb test runs and SOS-08-E's SystemVerilog testbench runs (and optionally SOS-08-F's UVM-sequence-driven runs) emit a **review artifact** comprising three coordinated files per test run:

1. A compact open-format waveform (`.fst`) consumed natively by GTKWave + Surfer.
2. A universally-compatible waveform (`.vcd`) consumed by every commercial simulator's waveform viewer.
3. A chart-vocabulary JSON-Lines overlay (`<test>.annotations.jsonl`) recording one row per chart-state transition observed during the test run, with chart-hierarchy path, region (within parallel blocks), invariant-fire IDs (when SVA-derived), and vector index citations.

The unlock SOS-08-G provides: when an agent modifies a chart via [SOS-11][sos-11] tools, the iState graphical viewer renders the **chart-level diff**; the developer can pull up the before/after **waveform diff** with chart-state badges overlaid on the timeline to verify the hardware behaviour matches the chart intent at the level the chart specifies. The chart diff + the waveform diff together are the review surface for one change. Without SOS-08-G, the chart-level diff is legible but the hardware-level diff is "30 lines of signal toggles" — the review loop is half-open.

## 2. Problem statement

Five observations from the SOS-08 umbrella + the SOS-11 MCP-workflow ratification converge on this sub-phase:

1. **Waveform viewers speak signals; charts speak states.** Every existing waveform viewer (GTKWave, Surfer, Riviera, Questa, VCS DVE) renders signal values vs time. None of them render chart-state names. A developer reviewing "does the synth match the spec" pattern-matches signal traces against the chart in their head — the cognitive cost is the dominant review tax in the article's "kernel-on-FPGA" demo if SOS-08-G does not land.

2. **The chart-diff review surface stops at the chart boundary.** [SOS-11 §9][sos-11] specifies the iState-side graphical viewer rendering the chart-level diff (states added/removed, transitions retargeted, invariants attached). That diff IS the review surface for an agent-mediated chart edit — at the spec layer. The hardware layer needs its own diff surface, in the same vocabulary, or the methodology's "spec-to-silicon" claim regresses to "spec-to-RTL-and-then-trust-it".

3. **Three viewer ecosystems share the same data model.** GTKWave (open, longstanding), Surfer (open, modern), and the commercial-tool family (Riviera, Questa, VCS, Xcelium) all consume waveform files. `.fst` is small + GTKWave/Surfer-native; `.vcd` is universal + ubiquitous; an external annotation overlay file lets viewer extensions render chart-state badges without modifying the waveform format itself. The three-file split is what makes the same `.annotations.jsonl` consumable by every viewer that the user opts in to extending.

4. **The annotation file is the chart-vocabulary bridge.** Per [INV-SOS-H][inv-sos-h] every artifact downstream of the chart MUST carry chart-vocabulary metadata. The `.annotations.jsonl` carries `(cycle, signal, chart_state, transition_id)` per row — every cycle's signal motion can be traced back to a chart state or transition. Failure to enforce this regresses the review surface to "RTL signal-level only" + breaks the cross-domain "spec is the source" claim.

5. **The annotation file naturally subsumes the SVA-fire log.** SOS-08-D + SOS-08-E emit SVA bind files that assert chart-derived invariants concurrently with the cocotb/SV testbench. Each SVA fire is a chart-vocabulary event (`INV-S-CHART-N fires at cycle K on signal P with chart-state Q`). The `.annotations.jsonl` row format extends naturally to carry invariant-fire records alongside chart-state-transition records, so the developer's single review file covers both observed transitions and assertion fires.

## 3. Canonical glossary

Reserved SOS-08-G vocabulary. Capitalised use in SOS-08-G+ docs MUST refer to the defined meaning. Cross-doc terms cite their owner per the parent CLAUDE.md "Definitions — reference vs. restatement" convention.

| Term | Definition |
|---|---|
| **review artifact** | The three coordinated files emitted per test run: `<test>.fst`, `<test>.vcd`, `<test>.annotations.jsonl`. Together they constitute the hardware-side review surface mirroring [SOS-11 §9][sos-11]'s chart-side review surface. As named in [SOS-08 §3][sos-08]; used without modification. |
| **`.fst` waveform** | Fastsignaltrace format; GTKWave + Surfer native; typically ~10% the size of equivalent `.vcd`. As defined by the GTKWave project (external upstream); SOS-08-G consumes the format, does not own it. |
| **`.vcd` waveform** | Value-change-dump format per IEEE 1364-2005 §18.3 (Verilog); universally-supported by every waveform viewer. As defined by IEEE 1364-2005 (external upstream); SOS-08-G emits conformant text, does not own the format. |
| **annotation overlay** | The `<test>.annotations.jsonl` file; one JSON object per line; one line per chart-vocabulary event observed during the test run. Schema frozen at §5.2. |
| **annotation record** | One line in the annotation overlay. Carries six normative fields per §5.2: `cycle`, `signal`, `chart_state`, `transition_id`, `chart_path`, `region`. Carries two optional fields: `invariant_id`, `vector_index`. |
| **chart-state transition** | A transition that fires within the chart during the test run, observed by the testbench (either via a chart-state probe signal exposed by the SOS-08-C emitter, or via direct testbench tracking). Each transition produces one annotation record. |
| **chart-path** | The chart-hierarchy path string for a state, of shape `/parent/child/grandchild` per [SOS-12][sos-12] recursive-dispatch vocabulary. Path separator: `/`. Sub-chart boundaries are crossed transparently (the path is rooted at the top-level chart). Max depth: PCDN-SOS-08-G-002. |
| **region** | The orthogonal-region identifier within an SCXML `<parallel>` block; per [SOS-12 §3][sos-12] independence-axis vocabulary. Null for transitions in non-parallel scope. |
| **invariant-fire record** | An annotation record where `invariant_id` is non-null; produced when an SVA assertion bound by SOS-08-D / SOS-08-E fires during the test run. The `invariant_id` is the chart-derived invariant ID (`INV-S-CHART-N`) per [INV-SOS-H][inv-sos-h]. |
| **vector index** | The integer position of the source vector in the chart's bounded-reachability vector set (per [INV-SOS-B][inv-sos-b]). Cited so the developer reviewing the waveform can navigate from "this transition fired at cycle 1234" to "vector #42 in the chart's vector set drove this transition". |
| **viewer extension** | A user-installed plugin or script (GTKWave plugin, Surfer extension, viewer-side TCL/Python script) that reads the annotation overlay and renders chart-state badges as a track on the waveform timeline. Distribution per PCDN-SOS-08-G-004. |
| **generation point** | The location in the SOS-08-D / SOS-08-E / SOS-08-F test run where the three review-artifact files are emitted. Per §5.4; SOS-08-G is *not* a separate phase that runs after the testbench — it is instrumentation *inside* the testbench. |

## 4. Source-of-truth map

For every concept this sub-phase touches, **exactly one** location is the canonical authority.

| Concept | Authority |
|---|---|
| Three-file review-artifact output contract | [SOS-08 §6][sos-08] SOS-08-G row (umbrella, **mirror** here) |
| Annotation overlay schema | **this doc** (§5.2) |
| `.fst` format | GTKWave project (external upstream; **derive**) |
| `.vcd` format | IEEE 1364-2005 §18.3 (external upstream; **derive**) |
| JSON-Lines line-delimited shape | ndjson.org / `application/x-ndjson` convention (external upstream; **mirror**) |
| Chart-path string format | [SOS-12][sos-12] (recursive-dispatch vocabulary; cited, **mirror** here) |
| Region identifier format | [SOS-12 §3][sos-12] (independence-axis vocabulary; cited, **mirror** here) |
| Invariant ID format `INV-S-CHART-N` | per-chart invariant vocabulary (chart author owns; SOS-08-G cites without modification) |
| Vector index format | [SOS-03][sos-03] vector framework (cited, **derive** here for the per-test subset) |
| Viewer extension distribution location | **this doc** (§5.5) once PCDN-SOS-08-G-004 resolved |
| Per-test vs consolidated-per-chart-region annotation file scope | **this doc** (§5.6) once PCDN-SOS-08-G-003 resolved |
| Per-cycle vs per-event annotation granularity | **this doc** (§5.7) once PCDN-SOS-08-G-005 resolved |
| Overlay schema version field | **this doc** (§5.2) once PCDN-SOS-08-G-001 resolved |
| MCP-workflow integration with [SOS-11][sos-11] | **this doc** (§9), composing [SOS-11 §9][sos-11] |
| Storage discipline (build output, not tracked source) | **this doc** (§5.8), per [INV-SOS-A][inv-sos-a] + [INV-SOS-C][inv-sos-c] |
| Cross-phase invariants INV-SOS-A through H | [SOS-07 §6][sos-07-inv] (cited, not redefined) |
| Cross-sub-phase invariants INV-S-HDL-1 through 5 | [SOS-08 §7][sos-08] (cited, not redefined) |
| Per-sub-phase cross-cutting invariants INV-S-HDL-G-* | **this doc** (§7) |

[sos-03]: ./SOS-03-CONCEPTS.md

## 5. Frozen decisions

### 5.1 Three-file output contract per test run

Per EOQ-011-ROADMAP resolution (carried forward via [SOS-08 §6 SOS-08-G][sos-08]), every test run that opts into review-artifact emission MUST produce exactly three coordinated files:

1. **`<test>.fst`** — fastsignaltrace format. Compact, GTKWave + Surfer native. Recommended for everyday developer use.
2. **`<test>.vcd`** — value-change-dump per IEEE 1364-2005 §18.3. Universal compatibility. Required for commercial-viewer interop.
3. **`<test>.annotations.jsonl`** — annotation overlay file. The chart-vocabulary bridge.

Filename prefix `<test>` is the testbench identifier (cocotb test name; SV testbench module name; UVM test class name). All three files share the prefix so the viewer integration can locate the overlay from the waveform's path.

Frozen-enumeration registration policy for the file-set: **Standards Action** (modifying the three-file contract requires §15 amendment + cross-sub-phase review with SOS-08-D + SOS-08-E).

### 5.2 Annotation overlay schema

The `<test>.annotations.jsonl` file is line-delimited JSON (one JSON object per line; no enclosing array; no trailing comma; UTF-8). The first line of every file MUST be a schema-version header record. Per PCDN-G-wave1-001 the canonical header shape is the `_meta`-envelope form:

```
{"_meta": {"schema": "sos-08-g/annotations", "version": "1.0", "chart_path_max_depth": 8}}
```

The `_meta` envelope segregates schema bookkeeping from data records (so JSONL stream-consumers can dispatch on `"_meta" in record`); the namespaced `sos-08-g/annotations` schema name reserves a path for cross-phase overlay families to coexist; the `chart_path_max_depth` field publishes the SOS-12 cap (mirrored per PCDN-G-002) so viewer extensions can size path-truncation hints without an out-of-band lookup. Conforming readers MAY accept the flat shape (`{"schema": ..., "version": ...}`) for backwards compatibility with v1-pre-canonicalization producers; conforming **emitters** MUST emit the `_meta` envelope form.

Every subsequent line is an **annotation record**. Six normative fields, two optional:

| Field | Type | Normative | Description |
|---|---|---|---|
| `cycle` | integer | normative | Cycle count on the testbench's master clock at which the event occurred. Per [INV-SOS-H][inv-sos-h] traceable to the chart-state transition the cycle corresponds to. |
| `signal` | string | normative | Fully-qualified HDL signal name (e.g. `dut.region_orchestrator.fsm_state`) whose change at `cycle` drove the chart-vocabulary event. Locates the event on the `.fst` / `.vcd` timeline. |
| `chart_state` | string | normative | The chart-state ID entered (or, for transitions, the destination state ID). Identifies *what* the hardware did at chart vocabulary level. |
| `transition_id` | string \| null | normative | The chart transition ID that fired. Null when the record is a state-enter that did not transit (e.g. initial-state entry, or a parallel-region simultaneous-enter). |
| `chart_path` | string | normative | The chart-hierarchy path per [SOS-12][sos-12], rooted at the top-level chart, separator `/`. Sub-chart boundaries are transparent. Example: `/orchestrator/syscalls/sem.take`. Max depth per PCDN-SOS-08-G-002. |
| `region` | string \| null | normative | The orthogonal-region identifier when the transition is inside an SCXML `<parallel>` block. Null for transitions in compound (non-parallel) scope. |
| `invariant_id` | string \| null | optional | The chart-derived invariant ID (`INV-S-CHART-N`) when this record corresponds to an SVA assertion fire. Null for chart-state transitions that did not fire an assertion. |
| `vector_index` | integer \| null | optional | The source vector index in the test's bounded-reachability vector set. Cites which vector drove this transition. Null when the test is not driven by a vector set (e.g. constrained-random testbench using SOS-08-E without an SOS-03 vector source). |

The two optional fields MAY be omitted from the JSON object (their absence is equivalent to `null`).

Frozen-enumeration registration policy for the field set: **Standards Action** (modifying the field set is a cross-sub-phase contract change; requires §15 amendment + viewer-extension contract review).

The schema version `1.0` is the v1 frozen value. Bumping the version is a §15 amendment.

### 5.3 Generation point: inside SOS-08-D / SOS-08-E / SOS-08-F test runs

SOS-08-G is NOT a separate phase that runs after the testbench. It is **instrumentation inside the testbench** that the SOS-08-D / SOS-08-E / (optionally) SOS-08-F emitters wire into their generated artifacts:

- The cocotb test (per [SOS-08-D][sos-08-d]) opens the `.fst` + `.vcd` simulator-side dump (Icarus `$dumpfile` / Verilator equivalent) and emits the `.annotations.jsonl` as the test coroutines observe chart-state changes.
- The SystemVerilog testbench (per [SOS-08-E][sos-08-e]) uses `$dumpfile` + `$dumpvars` for the waveforms and emits the overlay via SV file-I/O.
- The UVM sequence customer wrapper (per [SOS-08-F][sos-08-f]) optionally hooks into the customer's existing waveform-dump infrastructure; the overlay emission is the same.

The annotation overlay's chart-state observation source is the chart-state probe signal exposed by the SOS-08-C chart→FSM emitter (one probe per chart region, encoded so the testbench can decode the FSM's current state in chart vocabulary). The probe signal is part of SOS-08-C's emission contract; SOS-08-G consumes it.

Generation-point integration registration policy: **Specification Required** (adding a fourth generation source requires SOS-08-G phase-owner walkthrough; modifying the probe-signal protocol requires §15 amendment to SOS-08-C *and* this doc).

### 5.4 Viewer integration model

Three viewer integration paths are supported:

1. **GTKWave + Surfer extensions** — SOS publishes thin extensions or wrapper scripts that read `<test>.annotations.jsonl` and render chart-state badges as an overlay track on the waveform timeline. Distribution location per PCDN-SOS-08-G-004.
2. **Commercial viewers (Riviera, Questa, VCS DVE, Xcelium SimVision)** — SOS does NOT ship native plugins. The customer wraps the annotation overlay via the vendor's TCL/Python user-script extension API. The annotation overlay format is documented (§5.2) so customers can author their own hookup; SOS-08-G does not own the vendor hookup.
3. **Headless / CI artifact** — the annotation overlay is human-readable as JSON-Lines; CI may render a static HTML or text report directly from the file without any viewer at all.

The contract SOS-08-G owns is the **data**; the per-tool **rendering** is per the viewer's extension model.

### 5.5 Viewer-extension distribution

PCDN-SOS-08-G-004: where do the GTKWave / Surfer extensions live? Options:

- (a) Inside the SOS subrepo at `tools/sos-codegen/viewers/{gtkwave,surfer}/`.
- (b) As a separate downstream project (`sos-viewers` repo) released independently.
- (c) Both — sources upstream in the SOS subrepo; releases mirrored as a separate package.

Default recommendation: **(a) in-subrepo at `tools/sos-codegen/viewers/`**. The viewer extensions are tightly coupled to the §5.2 schema — when the schema bumps version they bump in lockstep. A separate repo introduces version-skew failure modes the methodology does not benefit from.

### 5.6 Per-test vs consolidated annotation file scope

PCDN-SOS-08-G-003: when a chart family (parent + sub-charts per [SOS-12][sos-12]) runs a coordinated test that exercises multiple charts in sequence, does the overlay produce one file per chart, one file per test run (covering all charts touched), or both? Options:

- (a) One `.annotations.jsonl` per test run, regardless of chart-family scope — the `chart_path` field disambiguates which chart each record came from.
- (b) One `.annotations.jsonl` per (test × chart) pair — multiple files per test run if multiple charts touched.
- (c) Both — per-test file as the default surface; per-chart split available via a post-process tool.

Default recommendation: **(a) one file per test run**. The `chart_path` field already carries per-chart provenance; splitting introduces filename coordination cost without buying review-surface legibility (the viewer extension can filter by `chart_path` cheaply).

### 5.7 Per-cycle vs per-event annotation granularity

PCDN-SOS-08-G-005: does the overlay emit a record every cycle (recording the current chart-state for every clock tick) or only on transition / invariant-fire events? Options:

- (a) Per-event — only transitions and invariant fires. Smallest file size; viewer extension interpolates "currently in state X" between transitions.
- (b) Per-cycle — every cycle's chart-state recorded. Largest file size; no interpolation needed.
- (c) Per-event default + per-cycle opt-in via `--annotation-density=cycle` flag.

Default recommendation: **(a) per-event** at v1. The cycle column is already present on every record; a viewer extension renders chart-state-vs-time by step-interpolating between consecutive event cycles. File size for a typical test run is in the low-MB range vs the tens-of-MB-to-GB range per-cycle would produce.

### 5.8 Storage discipline

Per [INV-SOS-A][inv-sos-a] (chart-as-source) + [INV-SOS-C][inv-sos-c] (MCP as sole modification surface): waveform files (`.fst`, `.vcd`) and the annotation overlay (`.annotations.jsonl`) are **build outputs**, NOT tracked source. They MUST NOT be committed to the chart's git repo. CI MAY upload them to artifact storage (S3, GitHub Actions artifacts, GitLab CI artifacts) for review; per-PR comment bots MAY surface links to them as part of the [SOS-11][sos-11] chart-diff review surface.

Mandatory `.gitignore` entries in the chart's repo: `*.fst`, `*.vcd`, `*.annotations.jsonl`, plus the conventional `build/` and `coverage/` directories the chart's codegen tool produces.

Frozen registration policy: **Standards Action** (any change to storage discipline touches every cross-phase invariant cited; requires §15 amendment + cross-phase review).

## 6. Viewer integration contract

A conforming viewer integration (GTKWave plugin, Surfer extension, commercial-viewer user script, or headless CI renderer) MUST satisfy:

- (a) **Co-locate** — given a waveform file path `<test>.fst` or `<test>.vcd`, locate `<test>.annotations.jsonl` in the same directory. If absent, the integration MAY render the waveform alone (no overlay) without error.
- (b) **Schema-version-aware** — read the first line, unwrap the `_meta` envelope (or accept the flat shape for backwards compatibility), and verify `schema == "sos-08-g/annotations"` and `version == "1.0"` (or a version the integration declares support for). Reject with a clear error if the schema is unknown.
- (c) **Per-record render** — for each annotation record, render a badge at `(cycle, signal)` on the waveform timeline carrying `chart_state` (and, when present, `transition_id` / `invariant_id` as secondary detail). Badges MUST be visually distinguishable from raw signal traces.
- (d) **Chart-path navigation** — when the chart-family has sub-charts ([SOS-12][sos-12]), the integration SHOULD provide a UI affordance to filter or scope by `chart_path` so the developer can focus on one sub-chart's transitions at a time.
- (e) **Invariant-fire highlighting** — records with `invariant_id` non-null SHOULD render with a distinct visual treatment (color, icon) so SVA fires stand out from ordinary chart-state transitions.
- (f) **Vector-citation drill-down** — when `vector_index` is non-null, the integration SHOULD provide a click-through that opens the corresponding vector definition (the SOS-03 vector framework owns the vector source-of-truth).

(d) through (f) are SHOULD not MUST because each viewer's extension API constrains what's feasible; (a) through (c) are MUST because they are the minimum to claim conformance.

## 7. Cross-sub-phase invariants — INV-S-HDL-G-*

In addition to the cross-phase invariants [INV-SOS-A through H][sos-07-inv] (from SOS-07) and cross-sub-phase invariants INV-S-HDL-1 through 5 (from SOS-08 §7), the following invariants are normative within SOS-08-G:

- **INV-S-HDL-G-1 — Three-file output coupling.** Every conforming test run that emits a review artifact MUST emit all three files (`.fst`, `.vcd`, `.annotations.jsonl`) coordinated by shared filename prefix. Emitting one or two of the three breaks the viewer-integration contract and is non-conformant.

- **INV-S-HDL-G-2 — Chart-vocabulary mandatory in overlay.** Every annotation record MUST carry the six normative fields per §5.2; `chart_state`, `transition_id`, `chart_path`, `region` together implement [INV-SOS-H][inv-sos-h]'s vector-to-chart-traceability claim at the review-surface layer. Emitting an overlay record without these fields regresses to RTL-signal-level review and is rejected by a conforming generation point.

- **INV-S-HDL-G-3 — Schema-version header required.** The overlay's first line MUST be the schema-version header record per §5.2. Files without the header are non-conformant. The version field is the mechanism by which viewer extensions detect schema evolution and refuse incompatible reads (per PCDN-SOS-08-G-001 resolution).

- **INV-S-HDL-G-4 — Build-output discipline.** Waveform files and annotation overlays are build outputs per §5.8. They MUST NOT appear in the chart's tracked git history. A pre-commit hook on the chart repo SHOULD enforce this; CI SHOULD reject commits that introduce tracked `.fst` / `.vcd` / `.annotations.jsonl` files.

- **INV-S-HDL-G-5 — Generation co-location with SOS-08-D / E / F.** The review artifact emission is instrumentation inside the testbench (per §5.3), not a separate post-process step. Decoupling the emission from the testbench breaks the chart-state probe-signal contract that SOS-08-C provides and is non-conformant.

- **INV-S-HDL-G-6 — Chart-diff + waveform-diff parity for MCP-workflow review.** Per §9, when [SOS-11][sos-11] surfaces a chart-level diff for an agent-mediated chart edit, the SOS-08-G review artifact generated from that edit's regenerated RTL test run MUST be available alongside the chart-level diff at the same review surface. The hardware-side review surface mirrors the chart-side review surface; absence of either regresses the methodology's end-to-end review-loop claim.

Frozen-enumeration registration policy for the INV-S-HDL-G-* set: **Standards Action**.

## 8. Standards integration matrix additions

The following rows EXTEND the [SOS-08 §8][sos-08] matrix:

| Concept | Upstream authority | Local relationship | Phase that declares it | Mutation rights |
|---|---|---|---|---|
| FST waveform format | GTKWave project (open) | **derive** (consume format; emit conformant text) | SOS-08-G | none |
| VCD waveform format | IEEE 1364-2005 §18.3 | **derive** | SOS-08-G | none — emit conformant text |
| JSON-Lines (`application/x-ndjson`) | ndjson.org convention (open) | **mirror** (line-delimited JSON, UTF-8) | SOS-08-G | none |
| Surfer waveform viewer | open project | **represent** | SOS-08-G | none |
| GTKWave waveform viewer | open project | **represent** | SOS-08-G | none |
| Riviera-PRO viewer extension API | Aldec (vendor) | **represent** (user-authored hookup) | SOS-08-G | none — customer owns hookup |
| Questa SimVision extension API | Siemens EDA (vendor) | **represent** | SOS-08-G | none |
| VCS DVE extension API | Synopsys (vendor) | **represent** | SOS-08-G | none |
| Xcelium SimVision extension API | Cadence (vendor) | **represent** | SOS-08-G | none |
| SOS-08-G annotation overlay schema | **own** | **own** (SOS-08-G authors; §5.2) | SOS-08-G | full; §15 amendment to bump version |

## 9. Reconciliation decisions vs adjacent sub-phases

### vs. [SOS-08-D][sos-08-d] (cocotb + SVA bind files, primary)

SOS-08-G's generation point lives inside the SOS-08-D cocotb test. The cocotb framework's `$dumpfile` / `$dumpvars` equivalents drive the waveform emission; cocotb coroutines observe chart-state probe signal changes and emit `.annotations.jsonl` rows via Python file-I/O. SVA bind-file fires (also emitted by SOS-08-D) produce `invariant_id`-carrying annotation records that share the file with chart-state-transition records — one overlay covers both observation channels. SOS-08-D owns the test scaffolding; SOS-08-G owns the overlay schema; the two compose at the cocotb test boundary.

### vs. [SOS-08-E][sos-08-e] (SystemVerilog testbench + SVA bind files)

Same shape as SOS-08-D but the host language is SystemVerilog. `$dumpfile` + `$dumpvars` drive the waveform; SV file-I/O (`$fopen` / `$fwrite`) drives the overlay. SVA fire records carry `invariant_id` in the same field shape. The SV testbench MAY include a tiny SV utility module (`sos_annotation_emitter`) the codegen tool generates as part of SOS-08-E; the module wraps the file-I/O so test authors do not re-derive the JSON-Lines formatting boilerplate.

### vs. [SOS-08-F][sos-08-f] (UVM sequences only)

SOS-08-F emits UVM-compatible sequences that plug into the customer's existing UVM environment. SOS-08-G's review-artifact emission from a UVM-driven run is optional — if the customer's environment already has its own waveform-dump and report infrastructure, the annotation overlay MAY be the only thing SOS-08-G adds. The overlay's chart-vocabulary records still carry [INV-SOS-H][inv-sos-h] traceability; the waveform emission is whatever the customer already runs.

### vs. [SOS-11][sos-11] (MCP-mediated chart editing)

This is the load-bearing reconciliation that motivates the sub-phase. SOS-11 specifies the chart-diff review surface for agent-mediated chart edits (per [SOS-11 §9][sos-11]): graphical viewer renders states added/removed, transitions retargeted, validation status, vector delta summary. SOS-08-G is the **hardware analog** of that surface: when the chart edit causes RTL regeneration and a re-run of the SOS-08-D / SOS-08-E tests, SOS-08-G's three-file review artifact lets the developer see the waveform-level diff in the same chart vocabulary.

The end-to-end review loop:

1. Agent invokes a [SOS-11][sos-11] tool (e.g. `add_state` in subchart `auth.connecting`).
2. SOS-11 commits the chart change with `scxml_diff`, `vector_delta`, `summary`, `validation`.
3. iState graphical viewer renders the chart-level diff (per [SOS-11 §9][sos-11]).
4. Downstream codegen regenerates RTL (per SOS-08-C) + testbench (per SOS-08-D + SOS-08-E).
5. CI re-runs the regenerated tests; each test emits a SOS-08-G review artifact (`.fst` + `.vcd` + `.annotations.jsonl`).
6. The developer reviews **both** surfaces at the same review pass: chart-level diff in the iState viewer + waveform-level diff in GTKWave/Surfer with chart-state badges.

This is INV-S-HDL-G-6 in operational form. Neither half of the review loop is complete without the other.

### vs. [SOS-12][sos-12] (recursive chart dispatch)

The `chart_path` field in §5.2 uses [SOS-12][sos-12]'s recursive-dispatch vocabulary directly: paths are rooted at the top-level chart and cross sub-chart boundaries transparently. PCDN-SOS-08-G-002 resolves the max-depth bound (proposed: mirror SOS-12's max dispatch-tree depth = 8). The `region` field uses [SOS-12 §3][sos-12]'s independence-axis vocabulary.

### vs. [SOS-03][sos-03] (conformance vectors)

The `vector_index` field cites the source vector's position in the SOS-03-emitted bounded-reachability vector set. SOS-08-G does NOT own vector emission; SOS-08-G only carries the integer index that drove a transition the testbench observed.

### vs. parent CLAUDE.md "Spec-Before-Code Planning Discipline"

SOS-08-G is spec-before-code applied to the hardware-side review surface: the annotation overlay schema is the spec; the viewer extensions consume the spec; viewer extensions cannot ship until the schema ratifies. The relationship is `compose` — SOS-08-G composes the parent discipline at the review-artifact layer.

## 10. Non-goals

This sub-phase does NOT:

- Author the GTKWave or Surfer viewers themselves. SOS-08-G specifies the overlay; the viewer projects own their renderers. SOS publishes thin extensions per §5.4 / §5.5 but does not fork the viewers.
- Author commercial-viewer plugins (Riviera, Questa, VCS DVE, Xcelium SimVision). Vendor-specific hookup is per-tool and customer-owned; SOS-08-G publishes the overlay format so customers can author hookup.
- Define the chart-state probe signal protocol. That is [SOS-08-C][sos-08]'s territory; SOS-08-G consumes the protocol.
- Define the SVA bind-file shape. That is [SOS-08-D][sos-08-d] and [SOS-08-E][sos-08-e]'s territory; SOS-08-G consumes the fires.
- Replace the SOS-11 chart-level review surface. The two surfaces are complementary, not alternatives.
- Define a versioned binary annotation format. JSON-Lines is the v1 form; a future amendment MAY add a binary form if file-size pressure materialises.

## 11. Pending Concept Decision Notices (PCDNs)

These are the open questions whose resolution moves this doc from 🟡 drafted to 🟢 ratified.

- **PCDN-SOS-08-G-001 — Overlay schema version detection mechanism.** §5.2 specifies the first line carries the schema-version header. Should the header live as the first record OR as a separate sidecar file (`<test>.annotations.schema.json`)? **Recommendation**: first-line header; single-file simplicity outweighs the schema-discovery flexibility a sidecar would offer. Viewer extensions read the first line cheaply.

- **PCDN-SOS-08-G-002 — Chart-path max depth.** §3 + §5.2 leave the max depth for `chart_path` unresolved. [SOS-12][sos-12] bounds dispatch-tree depth at 8. **Recommendation**: mirror SOS-12's max depth = 8 by reference; if SOS-12 amends, SOS-08-G picks up the change automatically. Explicit-vs-implicit-vs-configurable: implicit-by-reference to SOS-12.

- **PCDN-SOS-08-G-003 — Per-test vs consolidated annotation file scope.** §5.6. **Recommendation**: one `.annotations.jsonl` per test run; `chart_path` field disambiguates per-chart provenance.

- **PCDN-SOS-08-G-004 — Viewer-extension distribution location.** §5.5. **Recommendation**: in-subrepo at `tools/sos-codegen/viewers/{gtkwave,surfer}/`. Tight schema-coupling argues against a separate downstream project.

- **PCDN-SOS-08-G-005 — Per-cycle vs per-event annotation granularity.** §5.7. **Recommendation**: per-event default at v1; per-cycle opt-in via `--annotation-density=cycle` flag for high-bandwidth debug sessions.

- **PCDN-SOS-08-G-006 — Annotation-emit performance budget.** Should the testbench MUST flush `.annotations.jsonl` after every record, or buffer up to N records before flush? Per-record flush makes mid-run review possible but slows the testbench; buffered flush is faster but loses the tail on crash. **Recommendation**: buffered (line-buffered, flush at every newline) at v1; `--annotation-flush=record` opt-in for crash-debug scenarios.

- **PCDN-SOS-08-G-007 — Annotation-overlay sub-chart cross-reference shape.** When a transition fires in a sub-chart, does the annotation record cite the sub-chart's own vector-set's vector_index (sub-chart-local) or the parent-chart's vector_index that drove the dispatch boundary? **Recommendation**: cite the sub-chart-local index; rely on `chart_path` to disambiguate which sub-chart's vector set the index belongs to. Mirrors [INV-SOS-F][inv-sos-f]'s per-layer composition discipline.

## 12. Acceptance checklist

A conforming SOS-08-G ratification satisfies:

- (a) ⏸ PCDN-SOS-08-G-001 through 007 resolved.
- (b) ⏸ Annotation overlay schema in §5.2 frozen (Standards Action registration); schema version `1.0` ratified.
- (c) ⏸ Three-file output contract in §5.1 frozen (Standards Action registration); filename-prefix convention specified.
- (d) ⏸ Generation-point integration with [SOS-08-D][sos-08-d] + [SOS-08-E][sos-08-e] specified (§5.3); chart-state probe signal protocol cited.
- (e) ⏸ Viewer-integration contract in §6 specified; (a)-(c) MUST + (d)-(f) SHOULD requirements enumerated.
- (f) ⏸ Cross-sub-phase invariants INV-S-HDL-G-1 through 6 in §7 frozen.
- (g) ⏸ Standards integration matrix additions in §8 enumerated.
- (h) ⏸ Reconciliation §9 covers SOS-08-D, SOS-08-E, SOS-08-F, [SOS-11][sos-11], [SOS-12][sos-12], [SOS-03][sos-03].
- (i) ⏸ Storage discipline in §5.8 frozen; mandatory `.gitignore` entries listed; INV-S-HDL-G-4 cited.
- (j) ⏸ Worked example: at least one SOS-08-D-driven test emits a conforming three-file review artifact reviewed via a GTKWave extension shipped at `tools/sos-codegen/viewers/gtkwave/`. (Implementation gate; ratifies when SOS-08-D's first worked-example test lands.)

## 13. Files cited

| Path | Role |
|---|---|
| [`docs/concepts/SOS-07-CONCEPTS.md`](./SOS-07-CONCEPTS.md) | Cross-phase invariants (INV-SOS-A through H), AuthorityRelationship matrix. INV-SOS-H is load-bearing. |
| [`docs/concepts/SOS-08-CONCEPTS.md`](./SOS-08-CONCEPTS.md) | Umbrella; §5.4 vector emission priority + §6 SOS-08-G row; EOQ-011 resolution; INV-S-HDL-1 through 5. |
| [`docs/concepts/SOS-08-D-CONCEPTS.md`](./SOS-08-D-CONCEPTS.md) | cocotb + SVA bind file emitter; generation point (§5.3). *Forthcoming sub-phase doc; cited per [SOS-08 §6][sos-08].* |
| [`docs/concepts/SOS-08-E-CONCEPTS.md`](./SOS-08-E-CONCEPTS.md) | SystemVerilog testbench + SVA bind file emitter; generation point (§5.3). *Forthcoming sub-phase doc; cited per [SOS-08 §6][sos-08].* |
| [`docs/concepts/SOS-11-CONCEPTS.md`](./SOS-11-CONCEPTS.md) | MCP-mediated chart editing; chart-level review surface this phase mirrors at hardware level (§9). |
| [`docs/concepts/SOS-12-CONCEPTS.md`](./SOS-12-CONCEPTS.md) | Recursive chart dispatch; `chart_path` + `region` vocabulary (§5.2 + §3). |
| [`docs/concepts/SOS-03-CONCEPTS.md`](./SOS-03-CONCEPTS.md) | Vector framework; `vector_index` source-of-truth. |
| [`docs/concepts/SOS-ROADMAP-07-PLUS.md`](./SOS-ROADMAP-07-PLUS.md) | EOQ-011-ROADMAP resolution (informative). |
| Parent `CLAUDE.md` | Spec-Before-Code Planning Discipline; standards integration matrix conventions. |

## 14. Unblocks

This sub-phase's ratification (after PCDN resolution) unblocks:

- **The first GTKWave + Surfer viewer-extension implementation** at `tools/sos-codegen/viewers/`.
- **The end-to-end MCP-workflow review demo** ([SOS-11][sos-11] + SOS-08-G together): agent edits chart, both chart-diff and waveform-diff surface to the developer for one-pass review.
- **The article's "kernel-on-FPGA" demo's review-surface story**: napkin-to-silicon stays legible at every review.
- **SOS-08-D and SOS-08-E concept-doc ratifications** (the generation points need a stable annotation overlay schema to author against; they MAY ratify in parallel with this doc but their acceptance checklists cite §5.2 here).

## 15. Change log

### 2026-05-23 — Initial draft (Ira)

- Authored `SOS-08-G-CONCEPTS.md` as the per-sub-phase contract under the SOS-08 umbrella (ratified 2026-05-23).
- Frozen decisions §5: three-file output contract (`.fst` + `.vcd` + `.annotations.jsonl`) per EOQ-011-ROADMAP; annotation overlay schema v1.0 with six normative fields + two optional; generation-point integration inside [SOS-08-D][sos-08-d] / [SOS-08-E][sos-08-e] / [SOS-08-F][sos-08-f]; viewer-integration model (in-tree GTKWave/Surfer extensions; commercial viewers via user scripts; headless CI); storage discipline as build outputs per [INV-SOS-A][inv-sos-a] + [INV-SOS-C][inv-sos-c].
- Viewer integration contract §6: (a)-(c) MUST + (d)-(f) SHOULD; conformance level for extensions.
- Cross-sub-phase invariants §7: INV-S-HDL-G-1 through 6.
- Standards integration matrix §8: 10 rows added (FST, VCD, JSON-Lines, GTKWave, Surfer, four vendor viewer APIs, the SOS-08-G schema itself as `own`).
- Reconciliation §9: load-bearing reconciliation with [SOS-11][sos-11] (hardware-side mirror of chart-side review surface; INV-S-HDL-G-6 in operational form).
- 7 PCDNs raised: schema-version detection mechanism, chart-path max depth, per-test vs consolidated file scope, viewer-extension distribution, per-cycle vs per-event granularity, annotation-emit performance budget, sub-chart cross-reference shape.

Status: 🟡 **drafted**, awaiting PCDN walkthrough. Ratifies to 🟢 once each PCDN above has a chosen value and the corresponding section is updated.

### 2026-05-23 — Ratified after PCDN walkthrough (Ira)

All seven PCDNs from §11 resolved with recommendations accepted.

- **PCDN-SOS-08-G-001 → RESOLVED**: schema-version detection via **first-line header** record in the `.annotations.jsonl` file. Single-file simplicity beats sidecar-discovery flexibility. Viewer extensions read the first line cheaply.
- **PCDN-SOS-08-G-002 → RESOLVED**: `chart_path` max depth **mirrors SOS-12's depth-cap of 8** by reference; if SOS-12 amends, SOS-08-G picks up the change automatically. Implicit-by-reference.
- **PCDN-SOS-08-G-003 → RESOLVED**: annotation file scope is **one `.annotations.jsonl` per test run**; `chart_path` field disambiguates per-chart provenance within a single file.
- **PCDN-SOS-08-G-004 → RESOLVED**: viewer-extension distribution location is **in-subrepo** at `tools/sos-codegen/viewers/{gtkwave,surfer}/`. Tight schema-coupling argues against a separate downstream project.
- **PCDN-SOS-08-G-005 → RESOLVED**: annotation granularity is **per-event default** at v1; `--annotation-density=cycle` opt-in flag for high-bandwidth debug sessions.
- **PCDN-SOS-08-G-006 → RESOLVED**: emit performance policy is **line-buffered** (flush at every newline) at v1; `--annotation-flush=record` opt-in for crash-debug scenarios.
- **PCDN-SOS-08-G-007 → RESOLVED**: sub-chart cross-reference shape — cite the **sub-chart-local** `vector_index`; rely on `chart_path` to disambiguate which sub-chart's vector set the index belongs to. Mirrors INV-SOS-F per-layer composition discipline.

**§5 / INV amendments**:
- §5 frozen-decisions extended with the seven resolutions above by reference.
- Schema version 1.0 ratified per §12 (b); first-line header carries `{"_meta": {"schema": "sos-annotations", "version": "1.0", "chart_path_max_depth": 8}}` per PCDN-G-001 + PCDN-G-002 resolutions.
- INV-S-HDL-G-3 (schema-version header required) wording extended: "the header lives at line 0 of `.annotations.jsonl`; viewer extensions MUST validate the header before consuming records".
- INV-S-HDL-G-4 (build-output discipline) confirmed: `.annotations.jsonl`, `.fst`/`.vcd`, and `.transactions.jsonl` are build outputs (gitignored); `.gitignore` entries published per §5.8 + §12 (i).

**Status**: 🟢 **ratified**. Implementation of the waveform-annotation emit path in `tools/sos-codegen/` (and the GTKWave / Surfer viewer extensions) is now unblocked. SOS-08-D + SOS-08-E generation-point integration with chart-state probe signals is the load-bearing co-landing dependency (§12 (d)); the chart-state probe signal protocol is frozen at SOS-08-D / SOS-08-E ratification (also today).

### 2026-05-23 — Impl wave-1 scaffold (Ira)

Wave-1 implementation surface landed under the 2026-05-23 ratification of §15 above. This entry records what shipped, what remains scaffold, and what is wave-2 work.

**Wave-1 implementation surface**:

- **`AnnotationWriter` class** emitted into `_cocotb_helpers.py` by the cocotb walker. The class is template-emitted by `transliterate_cocotb.py` (the SOS-08-D primary cocotb walker, extended in wave-1 with the SOS-08-G annotation surface). Mandated by INV-S-HDL-G-2 (chart-vocabulary mandatory in overlay) and INV-S-HDL-G-5 (generation co-located with the @cocotb.test() body, not a post-process step).
- **`_SCHEMA_HEADER` first-line record** per PCDN-SOS-08-G-001 + PCDN-SOS-08-G-002: the writer emits `{"_meta": {"schema": "sos-annotations", "version": "1.0", "chart_path_max_depth": 8}}` as the first JSONL line of every `<test>.annotations.jsonl` overlay. INV-S-HDL-G-3 (schema-version header required) is upheld by construction — the writer's `__init__` writes the header before yielding the constructor.
- **Per-event default density** per PCDN-SOS-08-G-005: the emitted `@cocotb.test()` body instantiates `AnnotationWriter` at test start and calls `record_transition` per chart-state transition (initial-state entry, per-step transitions, terminal-state entry). Per-cycle granularity is honored via the `SOS_ANNOTATION_DENSITY` environment variable per PCDN-SOS-08-G-005; the `record_cycle` method on the writer is the cycle-density entry point.
- **`SOS_ANNOTATION_DENSITY` env-var opt-in** per PCDN-SOS-08-G-005: the `AnnotationWriter._DENSITY_ENV_VAR = "SOS_ANNOTATION_DENSITY"` constant is read at construction time; the public `density` attribute exposes the resolved value (`event` default; `cycle` opt-in) so test-side code can gate per-cycle record emission cheaply.
- **GTKWave + Surfer viewer extensions** at `tools/sos-codegen/viewers/{gtkwave,surfer}/` per PCDN-SOS-08-G-004. Each is a wave-1 CLI tool exposing `load_annotations`, `validate_schema_header`, `render_to_stdout`, and a vendor-specific emit (`to_gtkwave_tcl` for GTKWave; `to_surfer_commands` for Surfer). The CLI surface satisfies §6 (a)-(c) MUST conformance (co-locate, schema-version-aware, per-record render); §6 (d)-(f) SHOULD conformance (chart-path navigation, invariant-fire highlighting, vector-citation drill-down) is wave-2 work tied to each viewer's GUI extension API.
- **End-to-end integration test** at `tools/sos-codegen/tests/test_sos_08_g_integration.py` exercises the walker's emit + the viewer extensions' load in one round-trip. The test uses `pytest.importorskip` on the sibling modules so it skips gracefully when any of the three wave-1 deliverables (walker, GTKWave ext, Surfer ext) is mid-flight; all three landed on 2026-05-23 so the suite passes end-to-end.

**Wave-1 scope (what landed vs. what is deferred)**:

- Cocotb tests now emit `<test>.annotations.jsonl` at runtime per INV-S-HDL-G-5 (generation co-located with the test).
- `.fst` + `.vcd` waveform emission is via the simulator's `--trace` flag — the cocotb-classic Makefile passes `--trace --trace-structs` to Verilator (§5.1 three-file output contract assembled at the caller's invocation). Wave-2 may add cocotb-side helpers that bind the simulator's dump path to the writer's annotation path so callers do not re-derive the filename prefix coordination per INV-S-HDL-G-1.
- Per-cycle density implementation is a **stub at wave-1**: the env-var is read, the `density` attribute resolves, and the `record_cycle` method is available, but the emitted `@cocotb.test()` body does not yet instrument a per-`RisingEdge` cycle callback. Wave-2 instruments the actual clock callback so `SOS_ANNOTATION_DENSITY=cycle` produces a record per simulator clock tick.

**Wave-2 candidates** (recorded explicitly so the boundary is unambiguous):

- **Full GUI integration** for both viewer extensions: GTKWave's `gtkwave-extensions` Python API (markers added at runtime as the user scrubs the timeline) per §6 (d); Surfer's extension API per §6 (d). Wave-1 ships CLI tools that produce vendor-format scripts; wave-2 ships in-process plugins.
- **Per-cycle density actual implementation**: instrument the `RisingEdge(dut.clk)` callback in the emitted test body so `SOS_ANNOTATION_DENSITY=cycle` produces one record per simulator clock tick (currently the env-var is read but the per-cycle stream is not yet wired).
- **`chart_path` populated for nested charts**: wave-1 emits `chart_path=[chart_state]` (single-segment, top-level chart only). Wave-2 walks the SCXML hierarchy at emit time so sub-chart transitions carry the full `/parent/child/grandchild` path per [SOS-12][sos-12] recursive-dispatch vocabulary (capped at depth 8 per PCDN-SOS-08-G-002).
- **Wave-2 SVA bind-file annotation integration**: the SVA bind walker (sibling of `transliterate_cocotb.py`) emits assertion-fire events that the cocotb test body MAY consume and record via `record_transition(..., invariant_id="INV-S-CHART-N")`. Wave-2 wires the bind file's `$display` / `$fwrite` fire-events into the annotation writer so assertion failures get recorded with chart-state context per §5.2 + §9 (vs SOS-08-D).

**Cited invariants** (all upheld by wave-1 surface): INV-S-HDL-G-1 (three-file output coupling — the `.annotations.jsonl` shares the filename prefix with the simulator's `.fst` + `.vcd`), INV-S-HDL-G-2 (chart-vocabulary mandatory — every emitted record carries `cycle`, `signal`, `chart_state`, `transition_id`, `chart_path`, `region`), INV-S-HDL-G-3 (schema-version header required — first-line `_meta` record per writer construction), INV-S-HDL-G-4 (build-output discipline — README emits the `.gitignore` entries `*.fst`, `*.vcd`, `*.annotations.jsonl` per §5.8), INV-S-HDL-G-5 (generation co-location — writer instantiated inside the `@cocotb.test()` body), INV-S-HDL-G-6 (chart-diff + waveform-diff parity — the wave-1 review surface composes with [SOS-11][sos-11] once the iState chart-side diff lands; the hardware-side half is in place).

**Cited PCDNs** (all resolved 2026-05-23 §15 ratification entry above, implementation now in place): PCDN-SOS-08-G-001 (first-line header), PCDN-SOS-08-G-002 (`chart_path_max_depth=8` mirrored from SOS-12), PCDN-SOS-08-G-003 (one `.annotations.jsonl` per test run), PCDN-SOS-08-G-004 (in-subrepo viewer-extension location at `tools/sos-codegen/viewers/{gtkwave,surfer}/`), PCDN-SOS-08-G-005 (per-event default density; `SOS_ANNOTATION_DENSITY=cycle` opt-in), PCDN-SOS-08-G-006 (line-buffered flush via `open(..., buffering=1)`), PCDN-SOS-08-G-007 (sub-chart-local `vector_index`; `chart_path` disambiguates ownership).

**Status**: 🟢 **ratified (continuing)** — wave-1 scaffold lands the annotation-emission half of SOS-08-G; viewer integration scaffolds are CLI tools, full GUI integration in wave-2.

### 2026-05-23 — Wave-1 PCDN walkthrough (Ira)

The wave-1 scaffold implementation exposed five new PCDNs (PCDN-G-wave1-001 through 005). All five resolved with recommendations accepted.

- **PCDN-G-wave1-001 — Schema header shape canonicalization → RESOLVED**. §5.2 originally froze the flat shape `{"schema": "sos-08-g/annotations", "version": "1.0"}`; the wave-1 ratification §15 entry above + the wave-1 impl emitted the wrapped form `{"_meta": {"schema": "sos-annotations", "version": "1.0", "chart_path_max_depth": 8}}` with an un-namespaced schema name. The two diverged on three axes: envelope shape (`_meta`-wrapped vs flat), schema name (`sos-annotations` vs `sos-08-g/annotations`), and extra field (`chart_path_max_depth` carried vs absent). Resolution: **hybrid form** — `_meta`-wrapped envelope (segregates bookkeeping from data records; cleaner for JSONL stream-consumers), namespaced `sos-08-g/annotations` schema name (reserves path for cross-phase overlay families; matches §5.2's original discipline), `chart_path_max_depth: 8` retained (viewer extensions need it for path-truncation hints). §5.2 amended to publish the hybrid form as the canonical emitter contract; §6 (b) viewer-integration contract extended to unwrap `_meta` (or accept flat shape for backwards compatibility); INV-S-HDL-G-3 unchanged (header is still line-0). Code/viewer/test changes landed in the same commit as this amendment.

- **PCDN-G-wave1-002 — Per-cycle density actual implementation → DEFERRED to wave-2**. Wave-1 reads `SOS_ANNOTATION_DENSITY`, resolves the `density` attribute on `AnnotationWriter`, and exposes the `record_cycle` method on the writer; the `@cocotb.test()` body does NOT yet wire a per-`RisingEdge(dut.clk)` callback that invokes `record_cycle`. Reason for deferral: the cycle callback needs to discover `dut.clk` from the SOS-08-C chart→FSM port-naming convention (currently `clk_<domain>` per SOS-08-C wave-3 polish), and that requires threading the SOS-08-C port-name convention into the cocotb walker's emit. Wave-2 does the threading + the callback wire-up together. Wave-1 surface remains conforming because §5.7 freezes per-event as the default; per-cycle is opt-in.

- **PCDN-G-wave1-003 — Filename-prefix coordination by construction → DEFERRED to wave-2**. INV-S-HDL-G-1 (three-file output coupling) is currently caller-coordinated: the operator passes `--trace --trace-structs` to Verilator/Icarus separately from the cocotb test's `AnnotationWriter(test_name=...)` argument, and the matching filename prefix is by convention. Wave-2 emits a cocotb-classic Makefile fragment that binds the simulator's dump path to the writer's annotation path so prefix coordination is by construction. Wave-1 surface is conforming as long as the caller's invocation pattern preserves the prefix.

- **PCDN-G-wave1-004 — Nested-chart `chart_path` walking → DEFERRED to wave-2**. Wave-1 emits `chart_path=[chart_state]` (single-segment, top-level chart only). Wave-2 walks the SCXML hierarchy at emit time using `ChartAst.raw_scjson` (the field added to `ChartAst` in SOS-08-C wave-2) so sub-chart transitions carry the full `/parent/child/grandchild` path per [SOS-12][sos-12] recursive-dispatch vocabulary, capped at depth 8 per PCDN-G-002. INV-S-HDL-G-2 (chart-vocabulary mandatory) currently upheld by the single-segment form; nested-chart compositions ratifying §10's [SOS-12][sos-12] reconciliation need the walk.

- **PCDN-G-wave1-005 — SVA bind-file `invariant_id` integration → DEFERRED to wave-2**. The SVA bind walker (`transliterate_sva_bind.py`, sibling of `transliterate_cocotb.py`) emits SystemVerilog assertion bind files whose `$display` / `$fwrite` fire-events are currently written to simulator stderr. Wave-2 wires those fires into the cocotb test body's `AnnotationWriter` via a sideband sim-output file the cocotb test reads at teardown so each assertion fire records as an annotation record with `invariant_id="INV-S-CHART-N"` (per §5.2 optional-field shape + §9 vs SOS-08-D reconciliation). Wave-1 surface is conforming with `invariant_id=null` on every record; the field is optional per §5.2.

**§5.2 / §6 / INV amendments landed**:
- §5.2 frozen JSON example replaced with the hybrid form. New paragraph explains the rationale for the three axis decisions (envelope, schema name, extra field) and pins emitter MUST / reader MAY semantics.
- §6 (b) viewer-integration contract updated to unwrap `_meta` envelope before validating `schema` / `version`; backwards compatibility with the flat shape is permitted by reader implementations but not by emitters.
- INV-S-HDL-G-3 (schema-version header required) wording unchanged; the header is still line-0 of the overlay file; only the canonical record shape was canonicalized.

**Code / viewer / test changes landed in the same commit**:
- `tools/sos-codegen/transliterate_cocotb.py` — `_SCHEMA_HEADER` constant uses `sos-08-g/annotations` schema name.
- `tools/sos-codegen/viewers/gtkwave/sos_gtkwave_ext.py` — `SCHEMA_NAME = "sos-08-g/annotations"` (single source of truth re-exported to Surfer ext).
- `tools/sos-codegen/viewers/tests/fixtures/example_annotations.jsonl` — header line updated.
- `tools/sos-codegen/tests/test_transliterate_cocotb.py` + `tools/sos-codegen/tests/test_sos_08_g_integration.py` — assertions updated to expect `sos-08-g/annotations`.

**Status**: 🟢 **wave-1 PCDN walkthrough complete**. PCDN-G-wave1-001 closed in-tree; PCDN-G-wave1-002 through 005 are documented wave-2 boundary entries (each names its specific deferral reason). Wave-2 may now proceed against an unambiguous spec / impl baseline.

### 2026-05-23 — Impl wave-2: nested chart_path walking + SVA invariant_id merge (Ira)

Wave-2 closes two of the four wave-1 deferred candidates:

- **PCDN-G-wave1-004 (nested-chart `chart_path` walking)** → ✅ landed. The cocotb walker now walks the SCXML hierarchy at emit time and populates each annotation record's `chart_path` field with the full root-to-leaf path per SOS-12 recursive-dispatch vocabulary. Wave-1's single-segment `chart_path=[state_id]` form is replaced with `chart_path=[chart_name, parent_id, ..., state_id]` capped at depth 8 per PCDN-G-002.
- **PCDN-G-wave1-005 (SVA bind-file `invariant_id` integration)** → ✅ landed via a new per-chart `post_annotations.py` post-processor. The script reads `build/sim.log` for `SOS-FAIL chart=... region=... transition=... state=... invariant=... @ <time>` lines (per SOS-08-D §6.6 emit format) and appends one invariant-fire annotation record per matching line to each `<test>.annotations.jsonl` overlay in the build directory.

**Wave-3 deferred candidates** (the two that remain from wave-1):

- **PCDN-G-wave1-002 (per-cycle density actual implementation)**: instrument `RisingEdge(dut.clk)` callback in emitted test body. Wave-1 + wave-2 read `SOS_ANNOTATION_DENSITY` but the per-cycle callback wiring is wave-3.
- **PCDN-G-wave1-003 (filename-prefix coordination by construction)**: cocotb Makefile fragment that binds simulator's dump path to writer's annotation path. Currently caller-coordinated; wave-3 makes it by construction.

**Wave-3 GUI integration boundary** (explicitly out of scope at wave-2):

Wave-1 §15 named "full GUI integration" as a wave-2 candidate. Wave-2 does NOT land it. Reason: full GUI integration requires runtime plugins inside the viewer's process — GTKWave needs a TCL extension that loads at simulator-launch time and adds menu items + marker-track rendering; Surfer needs a Rust crate compiled to WebAssembly + a Surfer-side plugin manifest. Both require viewer-binary integration testing and toolchain-specific build infrastructure (TCL for GTKWave; Rust + wasm-pack + the Surfer plugin SDK for Surfer) that the wave-2 commit window cannot ship credibly. Wave-3 picks up GUI integration as a focused multi-commit family.

**Wave-2 implementation surface**:

- **`_build_chart_paths(chart_ir, chart_name)`** added to `transliterate_cocotb.py` (~50 LOC). Recursively walks the SCXML hierarchy yielding `{state_id: chart_path_list}` for every named state and every named `<parallel>` wrapper. The `<parallel>` wrapper's id is a hierarchy node (per SOS-12 — orthogonal regions sit under a named parallel container), so paths through parallel charts thread `chart → parallel_id → region_id → leaf_state`. Cap at `_CHART_PATH_MAX_DEPTH = 8` per PCDN-G-002 + the hybrid header's `chart_path_max_depth: 8` field.
- **`CocotbChart.chart_paths` field** added: `dict[str, list[str]]`, populated by `_build_chart_paths` from both single-region and parallel chart normalisation code paths.
- **`_emit_helpers_py` extension**: emits `_CHART_PATHS: dict[str, list[str]] = {...}` into the helpers module — a literal mapping of every state-id reachable in the chart to its walker-computed path. The test body looks it up at runtime via `_CHART_PATHS.get(state_id, [_CHART_NAME, state_id])`.
- **Test-body emit update**: every `writer.record_transition(..., chart_path=...)` call site in both `_emit_one_test_function` (single-region) and `_emit_parallel_test_function` (parallel) now uses `_CHART_PATHS.get(...)` lookup with the safe `[chart_name, state]` fallback shape, replacing wave-1's hard-coded `[state]` form.
- **`_emit_post_annotations_py(chart)`** added (~150 LOC). Per-chart standalone Python 3.10+ script wired into `render_target`'s output dict at `tests/<chart>/post_annotations.py`. The script:
    - Reads `build/sim.log`, scrapes `SOS-FAIL chart=<chart> ...` lines via regex matching the §6.6 macro emit format.
    - Self-filters by `chart=<this_chart>` (same pattern as wave-2a `post_results.py`) — a shared build directory across charts cannot cross-contaminate.
    - For each chart-matching fire builds one annotation record with `invariant_id` populated (plus `chart_state`, `transition_id`, `region`, `cycle` from the time stamp, `chart_path` defaulted to `[chart_name, state]` since the script does not have access to the emit-time `_CHART_PATHS` map).
    - Appends each record to every `<test>.annotations.jsonl` overlay it finds in `build/` — appends only, never rewrites the line-0 schema header per INV-S-HDL-G-3.
    - Standalone Python 3.10+, standard-library only (re, json, sys, pathlib). No cocotb / pytest dependency at post-processing time.

**Filename prefix convention**: `tests/<chart>/post_annotations.py` — co-located with `post_results.py` (wave-2a) under the same chart directory. Emit count per chart: 7 → 8 (added one).

**Invariants upheld**:

- **INV-S-HDL-G-2** (chart-vocabulary mandatory): retained — both the chart_path-enriched records (wave-2a path lookup) and the post-merged SVA-fire records carry the six normative fields per §5.2 (cycle, signal, chart_state, transition_id, chart_path, region) plus the optional `invariant_id` for fire records.
- **INV-S-HDL-G-3** (schema-version header at line 0): preserved by the append-only merge. The `post_annotations.py` script opens overlays in append mode (`"a"`) so the line-0 header is never rewritten.
- **INV-S-HDL-G-4** (build-output discipline): appended records live inside the per-test annotation file — itself a build output (gitignored per §5.8). No new tracked-source files introduced.
- **INV-S-HDL-G-6** (chart-diff + waveform-diff parity for MCP-workflow review): strengthened — the wave-2 chart_path nesting means a [SOS-11][sos-11] chart-diff that touches a deeply-nested sub-chart state now correlates with annotation records whose `chart_path` field names the same hierarchy path the chart-diff renders.
- **PCDN-G-002** (chart_path max depth = 8): enforced by `_CHART_PATH_MAX_DEPTH` constant + emit-time truncation. Tested via a 10-deep chart whose deepest state's path is capped at 8 segments.

**Test count**: 16 new tests:

- `TestNestedChartPathWalking` (7 tests): _CHART_PATHS emitted in helpers; root state path; nested state path (depth-2 + depth-3); test body uses `_CHART_PATHS.get(...)` lookup; path truncated at max depth via 10-deep fixture; parallel chart paths thread through `<parallel>` wrapper id + region.
- `TestPostAnnotationsEmit` (5 tests): file emitted; parses as Python; cites chart name + spec sections (`SOS-08-G`, `INV-S-HDL-G-2`, `INV-S-HDL-G-3`); standard-library only.
- `TestPostAnnotationsEndToEnd` (4 tests): drives the emitted script against synthetic build directories — appends SVA fire with `invariant_id` populated; self-filters by chart name (other-chart lines ignored); no-fires no-changes; schema header preserved at line 0 after merge (INV-S-HDL-G-3).

**Test suite**: 370/370 passing (354 prior + 16 wave-2).

**Cited PCDNs**: PCDN-G-wave1-004 (closed); PCDN-G-wave1-005 (closed); PCDN-G-002 (chart_path max depth = 8, enforced by walker); SOS-08-D §6.6 SOS-FAIL macro emit format (consumed by post_annotations.py); INV-S-HDL-G-2/-3/-4/-6.

Status: 🟢 **wave-2 complete** — nested chart_path walking + SVA invariant_id integration land cleanly. Wave-3 picks up the remaining two wave-1 deferred candidates (per-cycle density actual implementation + filename-prefix coordination by construction) plus full GUI integration (GTKWave TCL extension + Surfer Rust/WASM plugin) as a focused multi-commit family.

### 2026-05-24 — Impl wave-3a: per-cycle density actual implementation (Ira)

Wave-3a closes the first of the two wave-1 deferred candidates:

- **PCDN-G-wave1-002 (per-cycle density actual implementation)** → ✅ landed. The emitted `@cocotb.test()` body now spawns a per-`RisingEdge(dut.clk)` recorder coroutine when `writer.density == "cycle"` (i.e., the `SOS_ANNOTATION_DENSITY=cycle` env var is set). Each tick emits one `writer.record_cycle(...)` record naming the currently-active chart state, decoded from `dut.current_state` (or `dut.current_state_<region>` for parallel charts) via the embedded encoding map.

**Wave-3a implementation surface**:

- **`_per_cycle_record(dut, writer, region_name=None)`** — async coroutine emitted at module level in `test_<chart>_fsm.py` (right after `_apply_reset`). Inverts the encoding map (`_STATE_ENCODING` for single-region; `_REGION_STATE_ENCODINGS[region_name]` for parallel-region recorders), loops `await RisingEdge(dut.clk)`, reads the chart-state observable port, and emits one `writer.record_cycle()` per tick. Unknown one-hot values surface as a literal `<unknown:0bNN>` chart_state string so decode failures are visible at review-surface, never silently dropped.
- **Encoding-map import**: the emitted test module now imports `_STATE_ENCODING`, `_REGION_STATE_ENCODINGS`, `_CHART_NAME`, `_CHART_PATHS` from `_cocotb_helpers` so the coroutine can decode + path-lookup at runtime.
- **Spawn site — single-region** (`_emit_one_test_function`): `cocotb.start_soon(_per_cycle_record(dut, writer))` gated by `if writer.density == "cycle":` immediately after the `AnnotationWriter` is constructed.
- **Spawn site — parallel** (`_emit_parallel_test_function`): one `cocotb.start_soon(_per_cycle_record(dut, writer, region_name=_region_name))` per region (iterating `_REGION_STATE_ENCODINGS`), tagging each region's annotation stream with its own `region` field for per-region filtering at the review surface (SOS-08-G §6 (d)).

**Wave-3b remaining (the other wave-1 deferred candidate)**:

- **PCDN-G-wave1-003 (filename-prefix coordination by construction)**: cocotb Makefile fragment that binds the simulator's dump path to the writer's annotation path. Currently caller-coordinated; wave-3b makes it by construction.

**Wave-3c boundary (full GUI integration)**: GTKWave TCL extension + Surfer Rust/WASM plugin remain wave-3c as named in the wave-2 §15 entry. Wave-3a does NOT cross that boundary.

**Invariants upheld**:

- **INV-S-HDL-G-2** (chart-vocabulary mandatory): retained — per-cycle records carry the same six normative fields as per-event records (`cycle`, `signal`, `chart_state`, `chart_path`, `region`; `transition_id=None` per `record_cycle` shape per §5.2 — per-cycle records do not name a transition, they sample the current state).
- **INV-S-HDL-G-3** (schema-version header at line 0): preserved by `AnnotationWriter.__init__`; the recorder writes records AFTER the header has been emitted.
- **INV-S-HDL-G-5** (generation co-located with test body, not a post-process step): preserved — the recorder is spawned INSIDE the `@cocotb.test()` body, runs concurrently with the test coroutine, terminates implicitly at test teardown.
- **PCDN-G-005** (per-event default; cycle is opt-in): preserved — the spawn is gated by the writer's resolved density attribute, which defaults to `event`. The wave-1 `record_transition` call sites remain untouched, so the default-density emission shape is unchanged.
- **PCDN-G-006** (line-buffered flush): unchanged — `record_cycle` uses the same line-buffered file handle as `record_transition`, so every per-cycle record reaches disk on its trailing newline.

**Test count**: 14 new tests in `TestWave3aPerCycleDensity`:

- Coroutine emitted at module level + signature matches.
- Encoding-map imports present.
- Decode strategy: inverted-map dict comprehension.
- Unknown-value fallback to literal `<unknown:0bNN>` string.
- Records emitted via `writer.record_cycle` (not `record_transition`).
- Loop: `while True: await RisingEdge(dut.clk)`.
- Single-region spawn: `cocotb.start_soon(_per_cycle_record(dut, writer))` gated by density check.
- Single-region MUST NOT iterate region encoding map.
- Parallel: one spawn per region, gated by density check.
- Per-event default unchanged (`record_transition` still emitted).
- Single-region + parallel test modules still parse as valid Python.
- Wave-1 `_DENSITY_ENV_VAR` / `os.environ.get` gate on writer unchanged.
- Wave-1 `record_cycle` method on `AnnotationWriter` unchanged.

**Test suite**: 451/451 passing (437 prior + 14 wave-3a).

**Cited PCDNs**: PCDN-G-wave1-002 (closed); PCDN-G-005 (per-event default preserved); PCDN-G-006 (line-buffered flush preserved); INV-S-HDL-G-2/-3/-5.

Status: 🟢 **wave-3a complete** — per-cycle density opt-in is wired by construction. Wave-3b picks up filename-prefix coordination (the second deferred candidate); wave-3c picks up full GUI integration.
