# SOS-03 — Conformance Vector Suite: Schema, Suite, and Harness

**Status:** **🟢 Ratified 2026-05-19.** All seven PCDNs resolved by user 2026-05-19; ratification entry in §15. SOS-04 (M7 Rust port) and SOS-05 (M7 C port) are unblocked; implementation commits (sos-conformance harness scaffold + seed vector fixtures) land as follow-ups per the spec-before-code discipline.

**Blocks:** SOS-04, SOS-05, SOS-06.

> 🛑 **NO CODE.** Vocabulary, vector file format, suite layout, harness behaviour, conformance levels, expansion policy. No vector fixtures, no harness binary, no Rust crate scaffold. The implementation commit lands the vendored seed vectors and the `sos-conformance` crate skeleton after ratification per the spec-before-code discipline.

## 0. Authority policy

SOS-03 owns:

- The **vector file format** — JSON schema, naming convention, directory layout, field-encoding rules.
- The **canonical vector suite** — the actual fixtures committed to the repo at `conformance/vectors/<category>/`, plus the registration policy that governs how new vectors enter and how old ones retire.
- The **conformance harness behaviour** — the Rust binary `sos-conformance`'s CLI shape, exit-code semantics, output format, port-binary contract, and diff-comparison policy.
- The **conformance grading** — what "passes" the suite means at each conformance level, and how partial-suite passes are reported.
- The **vector expansion policy** — Standards-Action / Specification-Required / Expert-Review registration policies per category; the per-PR review obligations a vector author meets; the §15 amendment shape when invariants near the vector format itself change.

SOS-03 does **NOT** own:

- The **kernel behaviour** — [SOS-00] owns it; the chart is the source. The harness compares port traces against `sos-sim`'s output; if the chart's behaviour is wrong, SOS-00 §15 amends it, not SOS-03.
- The **observable subset** of the datamodel — [SOS-00 §7.2] owns it; [SOS-02 §5.4] re-exports it. SOS-03 vectors carry whatever `sos-sim` emits; SOS-03 cannot add a field that `TraceRecord` does not contain.
- The **trace wire format** — [SOS-02 §7] owns the byte-exact JSONL encoding rules and field order. SOS-03 *embeds* trace records inside vector files but does not amend the on-stream representation.
- The **event vocabulary and state-id vocabulary** — [SOS-01 §5.3] (`ExternalEventName`) and [SOS-01 §5.4] (`StateId`) own them. Vectors construct inputs only from `ExternalEventName`; the lint runner (SOS-01) is the canonical surface that rejects vectors naming undeclared events.
- The **simulator implementation** — [SOS-02] owns `sos-sim`. SOS-03 consumes it as a library (`use sos_sim::{Simulator, Vector, Trace};`) but does not modify it.
- The **per-port adaptation** — [SOS-04] (M7 Rust) and [SOS-05] (M7 C) each own their port binary's CLI; SOS-03 specifies the port-binary contract (stdin = vector input; stdout = trace stream) and forbids any other inter-process surface.

The authority split:

| Concern | Owner | SOS-03 relationship |
|---|---|---|
| Kernel behaviour (statechart, datamodel, syscall ABI) | [SOS-00] / `rtos_kernel.scxml` | `derive`. Vectors EXERCISE; vectors do not amend. |
| Frozen enums (`TaskState`, `ReturnCode`, `M7KernelPriorityBand`, `FpuPolicy`, `Msg`) | [SOS-00 §5] | `mirror`. Vectors serialise these values per [SOS-02 §7.2] encoding rules; SOS-03 does not extend. |
| Event vocabulary (`ExternalEventName`) and state-id vocabulary (`StateId`) | [SOS-01 §5.3, §5.4] | `derive`. Vector authors construct inputs from `ExternalEventName` only; SOS-01's lint runner cross-checks at vector-validation time. |
| Trace wire format (JSONL, field order, typed-value encoding) | [SOS-02 §7] | `mirror`. SOS-03 embeds `TraceRecord`s in vector files; the on-wire representation a port emits is byte-identical to [SOS-02 §7]. |
| Reference simulator `sos-sim` | [SOS-02] | `derive`. SOS-03 consumes `sos-sim` as a library to generate `expected_trace` and as the default `--port` backend. |
| Conformance harness binary `sos-conformance` | this doc | `own`. CLI, exit codes, output format, port-binary contract. |
| Vector schema, vector fixtures, suite layout | this doc | `own`. |
| `serde_json` (Rust crate) | upstream `serde_json` | `mirror`. Pinned to current 1.x; no SOS-03-side fork. Recommended floor `1.0.108`. |
| `globset` (Rust crate, for `--filter`) | upstream `globset` | `mirror`. Pinned to current 0.4.x; PCDN-SOS-03-006 ratifies the dependency. |
| Per-port adaptation (M7 Rust, M7 C) | [SOS-04], [SOS-05] | `derive` (port-binary contract). |

INV-S-CONF-0 (crawl boundary, inherited from [SOS-00 §0] INV-S1 and reasserted): SOS-03 reviewers consult this doc plus the cited section numbers in [SOS-00], [SOS-01], and [SOS-02] by published reference. The `serde_json` source tree, the `globset` source tree, and the full W3C SCXML 1.0 Recommendation are not routine crawl targets.

## 1. Purpose

Establish:

1. The **vector file format** — a JSON schema sufficient for vector authors to write fixtures without re-litigating field ordering, file naming, payload encoding, or directory placement on every PR. Vectors are JSON because [SOS-02 §7] already commits to JSON / JSONL for the trace wire format; reusing the encoder is load-bearing for INV-S-CONF-1.

2. The **canonical suite layout** — `conformance/vectors/<category>/<NNNN>-<slug>.json` where `<category>` is one of the five `VectorCategory` values, `NNNN` is a stable zero-padded sequential id, and `<slug>` is a mechanically-derived kebab-case form of the vector's `name` field. The layout makes vector discovery deterministic for both humans (`ls conformance/vectors/smoke/`) and machines (the harness's `--filter` glob applies directly to relative paths).

3. The **conformance harness's behaviour** — `sos-conformance run --suite <dir> [--port <bin>] [--filter <glob>]` runs every (filter-matching) vector in the suite directory, drives the named port binary by piping the vector input to stdin and reading its trace on stdout, diffs the result against the vector's `expected_trace`, and reports pass/fail per vector plus a suite-level summary. Exit code 0 iff all pass; non-zero per the [§7.2] table.

4. The **conformance levels** — three normative grades: `SmokePass` (all `Smoke`-category vectors pass), `FullSuitePass` (all `Smoke` + `Boundary` + `Stress` + `Regression` pass), `FullSuitePassWithDiversity` (full suite + every `Diversity` vector passes). A claim "port X passes SOS-03 v1.0" without a grade qualifier means `FullSuitePass`; the qualifier is mandatory in port-side spec docs (SOS-04 §15, SOS-05 §15).

5. The **expansion policy** — who can add a vector, when (PR-level vs §15 amendment), what review obligations the author meets, when a vector retires, and where retired vectors live. Vector quality is the inward-facing institutional memory of the kernel's behaviour; the policy prevents the suite from drifting away from the spec it is supposed to verify.

Without this layer:

- SOS-04 and SOS-05 have no concrete "this is what passing looks like" target. Port equivalence reduces to "trace looks similar" — opinion-driven, not spec-driven.
- The reference simulator `sos-sim` (SOS-02) has no test corpus. A regression in `sos-sim` would only be caught at port-build time, where the failure would be misattributed to the port.
- Vector authors with no schema would each invent their own field layout, payload encoding, and directory naming. The harness would need ad-hoc parsers per fixture; integration would be quadratic.
- "We pass the suite" would be ambiguous — does it mean smoke vectors? Boundary vectors? Mined regressions? The grading enum forces precision.

## 2. Problem statement

**Current state (as of 2026-05-19, immediately post-SOS-02 ratification):**

- [SOS-00] is ratified. §7 frames the vector shape informally: a JSON object with `name`, `config`, `input`, `expected_trace` fields. §7.4 lists six seed vectors from `docs/REFERENCE.md` § "Testing surface".
- [SOS-01] is ratified. §5.3 freezes the 18-event `ExternalEventName` enum; §5.4 freezes the 10-state `StateId` enum. Vectors construct inputs only from these.
- [SOS-02] is ratified. §6 specifies the `sos-sim` host simulator's architecture; §7 specifies the JSONL trace wire format (field order, typed-value encoding, the `Msg` discriminator policy, the `valid: false` short-form for sems / queues). §10 declares "SOS-03 (conformance vectors, future). Consumer. Imports `sos-sim` as a library; uses `Simulator::run_to_completion` to generate canonical traces; emits each as the `expected_trace` half of a fixture."
- There is no `conformance/` tree in the subrepo. There are no vector fixtures. There is no harness binary. The seed list in [SOS-00 §7.4] has not been instantiated.
- The parent `Cargo.toml` workspace at `streamz/submodules/SOS/Cargo.toml` (per [SOS-02] PCDN-005 → standalone) will exist post-SOS-02 implementation; SOS-03 plans to add `sim/sos-conformance/` as a second workspace member alongside `sim/sos-sim/`.

**The pressure that motivates SOS-03:**

Three pressures compound:

1. **Without ratified vectors, port equivalence is opinion.** SOS-04 (M7 Rust) and SOS-05 (M7 C) both ratify their own port code, but the *contract* that says "these two ports are equivalent" is the conformance suite. Without it, two ports can disagree on a corner case (queue direct-handoff with multiple waiters; timeout-exactly-at-tick semantics; sched.suspend deferring a pending unblock) and each port author can argue their reading is correct. The suite is the tie-breaker — and it ties to `sos-sim`'s output, not to any port's.

2. **Without expansion policy, vector quality drifts.** Vectors are seductively easy to add (every PR finds "one more case worth testing") and that's exactly how the suite stops being a *spec* and becomes an *appetite*. The categories in §5.1 (`Smoke` / `Boundary` / `Stress` / `Regression` / `Diversity`) carry different registration policies precisely so that the load-bearing surface (Smoke) is hard to mutate while the institutional-memory surface (Regression) is easy to grow.

3. **Without grading, "we pass" is ambiguous.** A port that runs the 12 seed-derived vectors and skips the 80 boundary vectors does pass *something*, but conflating that with full-suite pass is a category error. The three-level grading (`SmokePass`, `FullSuitePass`, `FullSuitePassWithDiversity`) gives reviewers a precise term. The grade is part of every port's §15 entry when it claims conformance.

**Why this is the right time:**

- [SOS-00] is ratified — the observable subset, frozen enums, and the `Msg` polymorphism story are stable enough to anchor expected-trace encoding.
- [SOS-01] is ratified — the 18 external events and 10 state ids are frozen; vector authors have a closed vocabulary.
- [SOS-02] is ratified — `sos-sim` exists as a spec (and is about to exist as an implementation). The trace format SOS-03 consumes is locked.
- The six seed vectors in [SOS-00 §7.4] are already enumerated in informal form. Lifting them into ratified fixtures is the cleanest small-batch first run; the policy that ratifies them ratifies the surface for everything else.

## 3. Canonical glossary

Terms SOS-03 introduces. Reuses from [SOS-00 §3], [SOS-01 §3], and [SOS-02 §3] are cited, not restated.

| Term | Definition | Owner |
|---|---|---|
| **Vector** | A unit of conformance — pairs an input event sequence with the `expected_trace` that sequence produces under `sos-sim`. The on-disk JSON form is the **vector fixture**; the in-memory Rust deserialisation is the `Vector` struct (per [SOS-02 §6.1]). Vectors are the *contract* every port satisfies (INV-S-CONF-1). | SOS-03. |
| **Vector fixture** | The on-disk JSON file at `conformance/vectors/<category>/<NNNN>-<slug>.json` that encodes one vector. The file's bytes are the canonical form; in-memory representations (Rust, eventually maybe Python) deserialise to this canonical form via the schema in §6.2. | SOS-03. |
| **Expected trace** | The `expected_trace` field of a vector. An ordered sequence of `TraceRecord`s (per [SOS-02 §5.4] `ObservableField` and [SOS-02 §7.1] field order). Generated by running `sos-sim` over the vector's `input` and capturing every emitted record. Manually-authored expected traces are forbidden (INV-S-CONF-3). | SOS-03 (the field); SOS-02 (the record format). |
| **Conformance harness** | The Rust binary `sos-conformance` (at `sim/sos-conformance/`, post-ratification). Drives a port through a suite of vectors and reports per-vector pass / fail plus a suite-level summary. The harness's own behaviour is normative (§7); the harness's implementation is non-normative (delivered by the implementation commit). | SOS-03. |
| **Port binary** | An executable that consumes a vector's `input` on stdin and emits a trace on stdout, in the format specified by [SOS-02 §7]. The harness invokes the port binary; the harness itself does not link the port's library. The default `--port` is `sos-sim`; SOS-04 ships an M7-Rust port binary; SOS-05 ships an M7-C port binary. | SOS-03 (contract); per-port phase (implementation). |
| **Port-binary contract** | The CLI / stdio surface a port binary MUST satisfy to be invoked by `sos-conformance`. Detailed in §7.6: read one JSON vector on stdin (entire document; no streaming); emit one trace record per line on stdout (JSONL per [SOS-02 §7]); exit code 0 on success, non-zero on internal error. | SOS-03. |
| **Diff record** | One element of a diff report — a structured description of where a port's trace deviated from the vector's `expected_trace`. Carries `vector_id`, `record_index`, `field_path`, `expected`, `actual`, and `severity` (one of `DiffSeverity`). | SOS-03. |
| **Conformance level** | A grade. One of `SmokePass`, `FullSuitePass`, `FullSuitePassWithDiversity` (the §5.2 `ConformanceLevel` enum). The grade is the precise term port-side spec docs use when claiming conformance; "passes SOS-03 v1.0" without a grade means `FullSuitePass`. | SOS-03. |
| **Diversity vector** | A vector in the `Diversity` category (§5.1). Diversity vectors stress corner cases that emerge from cross-port comparison (e.g. a queue scenario that exposes a port's optimisation hazard rather than a kernel-spec violation). Diversity vectors are advisory — `FullSuitePass` is independent of them; `FullSuitePassWithDiversity` includes them. | SOS-03. |
| **Regression vector** | A vector in the `Regression` category (§5.1). Each regression vector traces to a specific resolved ERRATA entry on this or a sibling phase. The vector's `description` field names the ERRATA id; the vector exists so the same bug cannot regress unnoticed. | SOS-03. |
| **Vector category** | One of `Smoke` / `Boundary` / `Stress` / `Regression` / `Diversity`. Each category has its own registration policy (§5.1) and its own subdirectory under `conformance/vectors/`. Category determines what gates ratify a vector add: Smoke is Standards Action (§15 amendment); the others are Specification Required (PR-level review). | SOS-03. |
| **Suite SHA** | The git SHA of the SOS subrepo at the moment a conformance claim is made. The `expected_trace` fields in the suite are generated by a specific `sos-sim` build at the Suite SHA; a port that claims `FullSuitePass` at Suite SHA `abc1234` is making a precisely-pinned claim. Suite SHA migration (regen of expected traces against a new `sos-sim`) is a §15 amendment per INV-S-CONF-6. | SOS-03. |
| **Vector origin** | The provenance of a vector — `Seed` (one of the six from [SOS-00 §7.4]), `Authored` (hand-authored by a phase reviewer), `RegressionMined` (auto-generated from a fixed ERRATA entry). The `VectorOrigin` enum (§5.4) carries this; the value lives in the vector fixture's `origin` field. | SOS-03. |

**Terms reused from earlier phases (cited, not restated):** `Statechart`, `Datamodel`, `Macrostep`, `Kernel`, `Port`, `Bench port`, `TCB`, `Ready queue`, `Wait-queue`, `Syscall`, `Tick`, `Critical section`, `Scheduler suspend`, `Idle task`, `Boot` (from [SOS-00 §3]); `ExternalEventName`, `StateId`, `Permitted ECMAScript feature` (from [SOS-01 §3]); `Simulator`, `Trace`, `TraceRecord`, `Macrostep boundary`, `Quiescence`, `Step harness`, `Event injection`, `Determinism budget`, `ScriptProvider`, `Script name` (from [SOS-02 §3]).

## 4. Source-of-truth map

| Source | Pinned form | Used surface | Relationship |
|---|---|---|---|
| `rtos_kernel.scxml` | Pinned at the Suite SHA per §15 (suite regen on chart change) | Indirectly — via `sos-sim`'s output. Vectors do not parse the .scxml; the harness does not read it. | `derive` (transitive through `sos-sim`). |
| [SOS-00 §5] frozen enums (`TaskState`, `ReturnCode`, `M7KernelPriorityBand`, `FpuPolicy`, `Msg`) | Ratified 2026-05-19 (Amendment 003) | `TaskState` and `ReturnCode` integer codes appear in `expected_trace` records per [SOS-02 §7.2]. `Msg` polymorphism is encoded via the discriminator object form (`null` / number / `{"rc": <int>}`). | `mirror`. |
| [SOS-00 §7.2] observable-state subset | Ratified 2026-05-19 (Amendment 002) | The exact field set every `expected_trace` record carries. | `mirror`. SOS-03 vector files cannot add a field; they cannot omit one (with the `valid: false` short-form exception from [SOS-02 §7.2]). |
| [SOS-01 §5.3] `ExternalEventName` (18 events) | Ratified 2026-05-19 | The closed set every vector's `input` array names. | `derive`. The harness's pre-flight vector-validation rejects unknown event names with exit code 1 (parse error). |
| [SOS-01 §5.4] `StateId` (10 states) | Ratified 2026-05-19 | Not directly serialised by vectors (state-ids appear in the chart, not in traces — `TaskState` integers appear instead). Indirectly relevant when authors describe a vector's intent in the `description` field. | `derive`. |
| [SOS-02 §6.1] module layout | Ratified 2026-05-19 | The harness imports `Simulator`, `Vector`, `Trace`, `TraceRecord`, `Config`, `Event` from `sos_sim`. | `mirror`. |
| [SOS-02 §7] trace wire format | Ratified 2026-05-19 | JSONL on stream; JSON array of records inside vector files (§6.5). Field order per [SOS-02 §7.1] is the canonical order; the harness's deserialiser does not reorder. | `mirror`. |
| [SOS-02 §9] simulator invariants (`INV-S-SIM-1` byte-determinism; `INV-S-SIM-6` trace-at-quiescence; `INV-S-SIM-9` faithful enum re-export) | Ratified 2026-05-19 | INV-S-SIM-1 is the load-bearing reason `expected_trace` regen yields stable bytes; INV-S-CONF-2 below depends on it. | `mirror`. |
| `serde` (Rust crate) | `serde = "1"` (current 1.x; floor `1.0.193`) | `Serialize` and `Deserialize` derives for `Vector`, `DiffRecord`, `SuiteSummary`. | `mirror`. Same dependency as `sos-sim` ([SOS-02 §4]). |
| `serde_json` (Rust crate) | `serde_json = "1"` (current 1.x; floor `1.0.108`) | Vector loader; diff-report serialiser when `--format json` is requested. **Important:** the diff implementation does NOT use `serde_json::Value::eq` — that derives from `BTreeMap` ordering, which works, but the harness uses a hand-rolled structural comparison instead (§6.5) for fine-grained `field_path` reporting. | `mirror`. |
| `clap` (Rust crate) | `clap = "4"` with `derive` feature | The `sos-conformance` CLI argument parser. Same crate `sos-sim` uses ([SOS-02 §4]); no new transitive dependency at the workspace level. | `mirror`. |
| `globset` (Rust crate) | `globset = "0.4"` (current 0.4.x) | `--filter <glob>` matching against relative vector paths (`smoke/0001-*.json`, `**/queue*`, etc.). PCDN-SOS-03-006 ratifies the dependency. Alternative considered: hand-rolled glob (rejected — `globset` is small, mature, and already the de-facto standard in the Rust ecosystem). | `mirror`. |
| `anyhow` (Rust crate) | `anyhow = "1"` | Error propagation in the CLI binary. Used in `bin/sos-conformance.rs` only; the library API uses concrete error types (per [SOS-02 §4]'s pattern). | `mirror`. |

**Negative listing:**

- SOS-03 MUST NOT depend on a JSON-diff library (`assert-json-diff`, `json-patch`, etc.). The harness's diff is hand-rolled (§6.5); the load-bearing reason is determinism — JSON-diff libraries vary in their handling of array-element ordering, object-key ordering, and numeric-precision policies. PCDN-SOS-03-001 ratifies this.
- SOS-03 MUST NOT depend on a property-testing crate (`proptest`, `quickcheck`). Vectors are concrete fixtures, not generators. The non-goal in §11 is explicit; INV-S-CONF-10 reasserts.
- SOS-03 MUST NOT depend on a fuzzing crate (`libfuzzer-sys`, `afl.rs`). Fuzzing is a future phase if ratified; SOS-03 has no such surface.
- SOS-03 MUST NOT depend on the disco-analyzer subrepo's crates or on the vendored FreeRTOS-Kernel (INV-S10 inheritance).
- SOS-03 MUST NOT depend on a YAML / TOML parser. The vector file format is JSON exclusively (PCDN-SOS-03-002).

## 5. Frozen enums

SOS-03 ratifies four frozen enums. Each carries a registration policy per the parent CLAUDE.md "Frozen enumerations — registration policy" convention.

### 5.1 `VectorCategory` — Standards Action

The category a vector belongs to. The on-disk directory `conformance/vectors/<category>/` is named with the lowercase form (`smoke`, `boundary`, etc.).

| Name | Meaning | Registration policy for *vector adds in this category* |
|---|---|---|
| `Smoke` | A core-surface vector. Exercises a single primitive end-to-end with minimal staging. The six seed vectors from [SOS-00 §7.4] all map to `Smoke`. Smoke is the floor of the suite; a port that fails any Smoke vector is not even close to conformant. | **Standards Action** — adding a Smoke vector requires a §15 amendment to this doc. The high gate is deliberate; the Smoke set is the closed minimal core that defines `SmokePass`. |
| `Boundary` | An edge-case vector — exercises behaviour at the boundary of a primitive's contract. Examples: timeout exactly at tick_count; queue at capacity with a sender at higher priority than the head receiver; sched.suspend with pend_ticks exactly at MAX_TASKS - 1; sem.give to an empty waiter list at sem.max. | **Specification Required** — adding requires a PR with at least one phase-reviewer approval citing the §6.2 schema fields and the §7.5 expansion-policy checklist. No §15 amendment. |
| `Stress` | A volume vector — exercises behaviour under repeated, interleaved, or scaled-up event sequences. Examples: 1000 alternating `task.yield` cycles between two tasks; queue send / receive interleavings across all four queue slots; multi-priority preemption storms. The bound is bounded — Stress vectors do not exceed the chart's static limits (`MAX_TASKS=8`, `MAX_PRIO=8`, `MAX_SEMS=8`, `MAX_QUEUES=4`, `Q_DEPTH=16`). | **Specification Required**. Same PR-level gate as `Boundary`. |
| `Regression` | A vector mined from a resolved ERRATA entry. The vector's `description` field MUST cite the ERRATA id (e.g. "ERRATA-007 — queue.send direct-handoff misorders sendw on equal-priority"). Each Regression vector exists to prevent re-regression. | **Specification Required**. The PR author MUST also update the ERRATA entry's "Verification" section to cite the vector's id. |
| `Diversity` | A vector that exposes a port-specific corner case (an optimisation hazard, a calling-convention difference, a memory-model subtlety) rather than a kernel-spec violation. Diversity vectors are advisory — they are not part of `FullSuitePass`; they are part of `FullSuitePassWithDiversity`. Examples: a vector that runs the same scenario through both `task.yield`-driven and `sys.tick`-driven preemption to expose whether a port special-cases one path. | **Expert Review** — phase-owner MAY add with a PR-level note. The lowest gate because Diversity vectors do not gate the primary conformance level; their absence does not block any port. |

**Registration policy (the enum itself):** Standards Action. Adding a *category* (e.g. `Performance`, `Fuzz`, `Property`) requires a §15 amendment to this doc, a new subdirectory under `conformance/vectors/`, and a coordinated update to the §5.2 `ConformanceLevel` enum if the new category alters what "full suite" means.

### 5.2 `ConformanceLevel` — Standards Action

The grade a port earns. Used in port-side spec docs (SOS-04 §15, SOS-05 §15) when claiming conformance.

| Name | Meaning | Required vector pass set |
|---|---|---|
| `SmokePass` | Port passes every vector in `conformance/vectors/smoke/`. The minimum useful conformance signal — a `SmokePass` port has a working scheduler, working semaphores, working queues, working tick handling, working critical sections. | All `Smoke`. |
| `FullSuitePass` | Port passes every vector in `Smoke`, `Boundary`, `Stress`, and `Regression`. The default conformance claim for a v1 port (SOS-04, SOS-05). | All `Smoke` ∪ `Boundary` ∪ `Stress` ∪ `Regression`. |
| `FullSuitePassWithDiversity` | Port passes `FullSuitePass` AND every vector in `Diversity`. The highest claim; a port that earns this has demonstrably matched `sos-sim` on every cross-port corner case in the suite. | All five categories. |

**Default for unqualified claims.** A port that claims "passes SOS-03 v1.0" without a grade qualifier is making the `FullSuitePass` claim. Port-side spec docs SHOULD use the explicit grade ("passes SOS-03 v1.0 at `FullSuitePass`") to keep cross-doc citations unambiguous.

**Registration policy:** Standards Action. Adding a grade (e.g. `BoundaryOnly`, `SmokePlusRegression`) requires a §15 amendment. Removing a grade requires a coordinated update to every port-side §15 entry that cited it.

### 5.3 `DiffSeverity` — Specification Required

The severity of a single diff record reported by the harness.

| Name | Meaning |
|---|---|
| `exact` | The port's trace record matches the expected record byte-for-byte. (Used only in `--format json` output to distinguish "checked-and-matched" from "unchecked".) Not a failure mode. |
| `bytes_differ` | The port's record and the expected record have the same structure (same field set, same array lengths) but at least one value differs. The diff report carries the specific `field_path` and the `expected` / `actual` values. The most common failure mode. |
| `record_count_mismatch` | The port emitted fewer or more records than expected. The diff report carries the expected count and the actual count; if the port emitted fewer, the missing-tail records' indices are listed. |
| `parse_error` | The port's stdout could not be parsed as JSONL. The diff report carries the line number, the byte offset, and the `serde_json` error message. Almost always indicates a port-side bug (mid-record panic; binary garbage in the stream); rarely a vector-side bug (corrupted `expected_trace`). |

**Registration policy:** Specification Required. New severity values are unlikely; `parse_error` and `record_count_mismatch` already cover the structural-failure modes, `bytes_differ` covers the value-failure mode, `exact` is the non-failure baseline.

### 5.4 `VectorOrigin` — Specification Required

The provenance of a vector. Stored in the fixture's `origin` field.

| Name | Meaning |
|---|---|
| `Seed` | One of the six seed vectors derived from [SOS-00 §7.4]. Their `name` fields follow the seed-list shape ("two-tasks-same-prio-alternate-via-yield", etc.). Seed vectors are part of `Smoke` (the seed-to-category mapping in §6.6); the `origin` discriminator distinguishes them from later-authored Smoke vectors. |
| `Authored` | Hand-authored by a phase reviewer. The default value for any vector that is neither a seed nor a regression-mined fixture. Most `Boundary`, `Stress`, and `Diversity` vectors carry this. |
| `RegressionMined` | Auto-generated from a resolved ERRATA entry by a future regression-vector miner (the reserved §7.4 expansion slot). All `Regression`-category vectors carry this once the miner ships; in the interim, `Regression`-category vectors carry `Authored` and a `description` that cites the ERRATA id (informally — the field is not parsed by the harness). |

**Registration policy:** Specification Required. Adding a value (e.g. `Fuzz`, `Property`) tracks the corresponding `VectorCategory` addition.

## 6. Vector file format

This section is **load-bearing**. It is what a vector author reads when sitting down to write a fixture. It is what a reviewer reads to gate a PR that adds a vector.

### 6.1 Directory layout

The full layout under the SOS subrepo root:

```
conformance/
├── vectors/
│   ├── smoke/
│   │   ├── 0001-two-tasks-same-prio-alternate-via-yield.json
│   │   ├── 0002-higher-prio-preempts-on-sem-give.json
│   │   ├── 0003-task-delay-then-tick-storm-monotonic-wake.json
│   │   ├── 0004-queue-full-empty-rejection-vs-block-timeout.json
│   │   ├── 0005-crit-enter-ticks-then-exit-catch-up.json
│   │   └── 0006-sched-suspend-defers-high-prio-unblock.json
│   ├── boundary/
│   │   ├── 0001-...
│   │   └── ...
│   ├── stress/
│   │   ├── 0001-...
│   │   └── ...
│   ├── regression/
│   │   ├── 0001-...
│   │   └── ...
│   ├── diversity/
│   │   ├── 0001-...
│   │   └── ...
│   └── retired/
│       └── (retired vectors per INV-S-CONF-6)
└── README.md          (informative — vector-author onboarding; lints at PR time per SOS-01)
```

The `conformance/` tree lives at the SOS subrepo root (sibling of `sim/`, `docs/`, and `rtos_kernel.scxml`). `conformance/README.md` is informative — it carries the vector-author onboarding text, links back to this doc, and lists the six seed vectors with one-line descriptions. The README is not parsed by the harness.

**The `retired/` subtree.** Vectors that retire (per INV-S-CONF-6) move into `conformance/vectors/retired/<original-category>/<original-NNNN>-<slug>.json`. The harness does NOT include `retired/` in its default suite scan; `--include-retired` is reserved as a future flag (not implemented at v1).

**Per-category sequential ids.** Each category has its own zero-padded sequential id namespace. `smoke/0001-...` and `boundary/0001-...` are distinct vectors. Ids are assigned manually by the author at PR time (PCDN-SOS-03-005); collisions are caught at PR review.

### 6.2 JSON schema (informal but precise)

The top-level JSON object of a vector fixture. Every field is required unless marked *optional*.

```json
{
  "name": "two-tasks-same-prio-alternate-via-yield",
  "description": "Two tasks at the same priority alternate via task.yield. Verifies round-robin tie-breaking inside pick_next() and the FIFO-within-priority ready-queue discipline.",
  "category": "Smoke",
  "origin": "Seed",
  "tags": ["scheduler", "yield", "round-robin"],
  "config": {
    "max_tasks": 8,
    "max_prio": 8,
    "max_sems": 8,
    "max_queues": 4,
    "q_depth": 16,
    "tick_hz": 1000
  },
  "input": [
    { "event": "task.create", "data": { "id": 1, "prio": 3 }, "from_tid": null },
    { "event": "task.create", "data": { "id": 2, "prio": 3 }, "from_tid": null },
    { "event": "task.yield",  "data": null, "from_tid": 1 },
    { "event": "task.yield",  "data": null, "from_tid": 2 }
  ],
  "expected_trace": [
    { "after_input_idx": -1, "current": 0, "tick_count": 0, "rc": 0, "tcb": [...], "ready": [[],[],[],[],[],[],[],[]], "sems": [...], "queues": [...], "irq_nest": 0, "sched_lock": 0, "pend_ticks": 0 },
    { "after_input_idx":  0, "current": 1, "tick_count": 0, "rc": 0, "tcb": [...], "ready": [[0],[],[],[],[],[],[],[]], "sems": [...], "queues": [...], "irq_nest": 0, "sched_lock": 0, "pend_ticks": 0 },
    { "after_input_idx":  1, "current": 1, "tick_count": 0, "rc": 0, "tcb": [...], "ready": [[0],[],[],[2],[],[],[],[]], "sems": [...], "queues": [...], "irq_nest": 0, "sched_lock": 0, "pend_ticks": 0 },
    { "after_input_idx":  2, "current": 2, "tick_count": 0, "rc": 0, "tcb": [...], "ready": [[0],[],[],[1],[],[],[],[]], "sems": [...], "queues": [...], "irq_nest": 0, "sched_lock": 0, "pend_ticks": 0 },
    { "after_input_idx":  3, "current": 1, "tick_count": 0, "rc": 0, "tcb": [...], "ready": [[0],[],[],[2],[],[],[],[]], "sems": [...], "queues": [...], "irq_nest": 0, "sched_lock": 0, "pend_ticks": 0 }
  ]
}
```

Field-by-field specification:

| Field | Type | Required? | Description |
|---|---|---|---|
| `name` | string | required | Human-readable name of the vector. Kebab-case, lowercase ASCII letters / digits / hyphens. MUST be unique within the file's category subtree (the file slug derives from this — §6.3). Recommended max length 64 chars. |
| `description` | string | required | One-paragraph human-readable description. Names the primitives exercised, the invariants checked, and (for `Regression`) the ERRATA id traced. No max length, but SHOULD fit comfortably on a terminal screen (~6 lines). |
| `category` | string | required | One of the `VectorCategory` values (§5.1): `"Smoke"`, `"Boundary"`, `"Stress"`, `"Regression"`, `"Diversity"`. The string is serialised in PascalCase to match the Rust enum's variant names; the on-disk directory name is the lowercase form (`"Smoke"` → `smoke/`). The harness verifies category-vs-directory consistency at load time; mismatch is a parse error (exit code 1). |
| `origin` | string | required | One of the `VectorOrigin` values (§5.4): `"Seed"`, `"Authored"`, `"RegressionMined"`. PascalCase. |
| `tags` | array of strings | required (MAY be empty) | Free-form classification tags. Used by `--filter` (informal) and by the suite-summary report (which groups by tags). Examples: `["scheduler", "yield"]`, `["queue", "direct-handoff", "boundary"]`. No central registry — tags are author-chosen; consistency emerges via PR review. |
| `config` | object | required | The kernel configuration constants this vector runs against. Mirrors the chart's `<datamodel>` config block ([SOS-00 §7.1]). All six sub-fields are required; their values determine the sizes of `tcb`, `ready`, `sems`, `queues` arrays in `expected_trace`. |
| `config.max_tasks` | integer | required | The `MAX_TASKS` value at the simulator. Range `[1, 64]` at v1; vectors at HEAD use `8` to match the chart's at-HEAD default. |
| `config.max_prio` | integer | required | `MAX_PRIO`. Range `[1, 32]`. |
| `config.max_sems` | integer | required | `MAX_SEMS`. Range `[0, 64]`. |
| `config.max_queues` | integer | required | `MAX_QUEUES`. Range `[0, 16]`. |
| `config.q_depth` | integer | required | `Q_DEPTH`. Range `[1, 128]`. |
| `config.tick_hz` | integer | required | `tick_hz` (informational at v1 — `sys.tick` events are explicit in `input`, not auto-generated; `tick_hz` is recorded for documentation symmetry with the .scxml's `SOS_TICK_HZ`). Range `[1, 1_000_000]`. |
| `input` | array of objects | required | The sequence of external events to dispatch. Each element has the shape `{ event, data, from_tid }`. Empty arrays are permitted (a vector with only the boot-baseline record is technically a valid vector — useful as a smoke test that the boot macrostep runs at all). |
| `input[i].event` | string | required | One of the `ExternalEventName` values from [SOS-01 §5.3]. The harness's pre-flight validation rejects unknown event names (exit code 1, `parse_error`-like). |
| `input[i].data` | object or null | required | The `_event.data` payload. Shape per [SOS-01 §5.3]'s "Payload" column. `null` for events without payload (`task.yield`, `crit.enter`, `crit.exit`, `sched.suspend`, `sched.resume`, `sys.tick`). |
| `input[i].from_tid` | integer or null | required | Per [SOS-00 §7.1]: the task id whose context "issued" this syscall. The harness sets `dm.current = from_tid` before dispatching; if `null`, `dm.current` is left untouched (ISR-context events: `sys.tick`, `sem.give_from_isr`, `queue.send_from_isr`). See §6.4. |
| `expected_trace` | array of objects | required | The sequence of `TraceRecord`s `sos-sim` emits when run over `input` with `config`. The first record is the boot baseline (`after_input_idx: -1`); subsequent records correspond to each `input[i]` at indices `i = 0, 1, ...`. Length is always `len(input) + 1`. |
| `expected_trace[k]` | object | required | One `TraceRecord` per [SOS-02 §5.4] and [SOS-02 §7.1]. Field order in the on-disk JSON file is canonical per [SOS-02 §7.1]. |

**Schema validation.** A vector file fails to load when:
- Any required field is missing or has the wrong type.
- `name` is not kebab-case lowercase ASCII.
- `category` is not one of the five enum values.
- `category` mismatches the parent directory's name.
- `origin` is not one of the three enum values.
- `config.max_*` values are outside their declared ranges.
- `input[i].event` is not in `ExternalEventName`.
- `expected_trace[k].after_input_idx` is not `-1` (for `k == 0`) or `k - 1` (for `k > 0`).
- `len(expected_trace) != len(input) + 1`.

The harness reports each failure with a `field_path` and exits code 1. No automatic correction — vectors are hand-authored (or miner-generated) artifacts; silent fixes erode the auditable spec lineage.

### 6.3 Vector naming convention

The `name` field is the author-chosen human-readable identifier. The on-disk file slug is **mechanically derived** from `name`:

1. Lowercase the name.
2. Replace any character not in `[a-z0-9-]` with a hyphen.
3. Collapse runs of consecutive hyphens to a single hyphen.
4. Trim leading and trailing hyphens.

The result is the slug. The full filename is `<NNNN>-<slug>.json` where `<NNNN>` is the four-digit zero-padded sequential id (PCDN-SOS-03-005 → manual assignment).

Examples:

| `name` field | Derived slug | Full filename (assuming id 0007) |
|---|---|---|
| `two-tasks-same-prio-alternate-via-yield` | `two-tasks-same-prio-alternate-via-yield` | `0007-two-tasks-same-prio-alternate-via-yield.json` |
| `Higher Prio Preempts on sem.give` | `higher-prio-preempts-on-sem-give` | `0007-higher-prio-preempts-on-sem-give.json` |
| `queue.send_from_isr at full` | `queue-send-from-isr-at-full` | `0007-queue-send-from-isr-at-full.json` |

The harness verifies at load time that the filename's slug-portion equals the derived slug of `name`. Mismatch is a parse error.

**Why mechanical derivation.** Authors think in human-readable names; reviewers grep for primitive verbs; tooling sorts by id. The mechanical mapping makes all three view the same file system tree without ambiguity. Renaming `name` *requires* renaming the file (and §15 amendment if the category is `Smoke`, per INV-S-CONF-5).

### 6.4 `from_tid` semantics

Per [SOS-00 §7.1], `from_tid` models "task X issued this syscall". The harness's dispatch protocol:

1. Read `input[i]`.
2. If `input[i].from_tid` is not `null`, set `dm.current = input[i].from_tid` *before* invoking the event's transition body.
3. If `input[i].from_tid` is `null`, leave `dm.current` at whatever value it currently holds (either `-1` post-block, or the previously-set task id).
4. Dispatch the event.
5. Run the macrostep to quiescence.
6. Emit a `TraceRecord` with `after_input_idx = i`.

The `from_tid` injection is **port-side as well as harness-side**. SOS-04 and SOS-05's port binaries MUST read the same `from_tid` field and apply the same pre-dispatch assignment. Failure to do so is a port defect (INV-S-CONF-1 byte-equality violation), not a vector defect.

**ISR-context events.** `sys.tick`, `sem.give_from_isr`, and `queue.send_from_isr` MUST carry `from_tid: null`. The harness's pre-flight validation rejects ISR-context events with non-null `from_tid` (parse error). The reverse — a task-context event with `from_tid: null` — is *permitted* (the simulator dispatches against whatever `current` value is in force) but SHOULD be avoided by vector authors as a clarity / readability issue.

### 6.5 Diff comparison policy

Two surfaces with two different policies.

**On-disk vector file vs. on-disk vector file (the schema check).** When the harness loads a vector file, comparison against the schema is **structural** — field order in the source JSON does not matter; whitespace does not matter; round-tripping through `serde_json` is lossy with respect to formatting and the harness accepts that.

**Port stdout (the JSONL stream) vs. vector's `expected_trace`.** The harness's diff is **structural per record**, NOT byte-exact at the stream level. The reasoning:

- Byte-exact at the stream level (concatenate `expected_trace` as JSONL, compare to port stdout as bytes) is what [SOS-02 §7] guarantees for `sos-sim`'s own output. But the *vector file* embeds `expected_trace` as a JSON array, not as raw JSONL, so a byte-level comparison would require re-serialising the array to JSONL and that re-serialisation is sensitive to `serde_json` version drift.
- Structural per record (parse port stdout as JSONL, parse expected as a JSON array, compare record-by-record structurally) is both more diagnostic (the diff report can pinpoint the `field_path` that differs) and more stable (a `serde_json` minor-version bump that changes float formatting does not break vectors — and integers are exact regardless, which is the only numeric type in the trace).

The structural comparison rules:

1. Compare `len(expected) == len(actual)`. If not, emit a `DiffSeverity::record_count_mismatch` diff and continue with the shorter prefix.
2. For each record index `k`, compare `expected[k]` and `actual[k]` field-by-field per [SOS-02 §5.4] `ObservableField` order. The harness walks the canonical order; it does not iterate `serde_json::Value`'s object keys.
3. Scalar fields (`after_input_idx`, `current`, `tick_count`, `rc`, `irq_nest`, `sched_lock`, `pend_ticks`) compare with `==` on integers.
4. The `tcb` array compares element-by-element. Each `TcbSnapshot` compares field-by-field: `id`, `prio`, `state`, `deadline`, `blk_obj`, then `msg`. The `msg` field uses the [SOS-02 §7.2] encoding (`null` / number / `{"rc": <int>}`) — a structural match on the encoded form, not on a recovered discriminator.
5. The `ready` array compares as a nested array of integers — outer length equals `max_prio`; inner sequences compare element-by-element.
6. The `sems` array compares element-by-element. The `{"valid": false}` short form ([SOS-02 §7.2]) is the canonical form for invalid slots; the harness rejects expanded `{"valid": false, "count": 0, ...}` forms as parse errors (a future-proofing rule — see PCDN-SOS-03-007).
7. The `queues` array compares symmetrically to `sems`.

Any mismatched field emits one `DiffRecord` per leaf mismatch. The harness does NOT stop at the first diff per record — full per-record diff reports are more diagnostic.

PCDN-SOS-03-001 ratifies this structural-comparison choice; the alternative considered (byte-exact at the stream level with a re-serialisation step) was rejected because the re-serialisation introduces `serde_json` version coupling that erodes vector portability.

### 6.6 The seed suite

[SOS-00 §7.4] enumerates six seed vectors derived from `docs/REFERENCE.md` § "Testing surface". SOS-03 ratifies the seed-to-category mapping:

| Seed (from [SOS-00 §7.4]) | `category` | `name` (canonical) | File path |
|---|---|---|---|
| 1. Two tasks at the same priority alternating via `task.yield`. | `Smoke` | `two-tasks-same-prio-alternate-via-yield` | `conformance/vectors/smoke/0001-two-tasks-same-prio-alternate-via-yield.json` |
| 2. Higher-priority task preempts on `sem.give`. | `Smoke` | `higher-prio-preempts-on-sem-give` | `conformance/vectors/smoke/0002-higher-prio-preempts-on-sem-give.json` |
| 3. `task.delay` followed by `sys.tick` storms shows monotonic wake-up. | `Smoke` | `task-delay-then-tick-storm-monotonic-wake` | `conformance/vectors/smoke/0003-task-delay-then-tick-storm-monotonic-wake.json` |
| 4. Queue FULL / EMPTY rejection vs. blocking with timeout. | `Smoke` | `queue-full-empty-rejection-vs-block-timeout` | `conformance/vectors/smoke/0004-queue-full-empty-rejection-vs-block-timeout.json` |
| 5. `crit.enter` + `sys.tick × N` + `crit.exit` produces N catch-up ticks and at most one reschedule. | `Smoke` | `crit-enter-ticks-then-exit-catch-up` | `conformance/vectors/smoke/0005-crit-enter-ticks-then-exit-catch-up.json` |
| 6. `sched.suspend` deferring a high-priority unblock until `sched.resume`. | `Smoke` | `sched-suspend-defers-high-prio-unblock` | `conformance/vectors/smoke/0006-sched-suspend-defers-high-prio-unblock.json` |

All six map to `Smoke`, `origin: "Seed"`. Their ids `0001`–`0006` are reserved at SOS-03 ratification; the implementation commit lands the six fixtures.

The Smoke category is **not** closed at six. Future Smoke vectors (e.g. `0007-sem-give-from-isr-wakes-blocked-taker`) ratify via §15 amendment per INV-S-CONF-5; the seed set is just the initial population.

## 7. Conformance harness behaviour

The harness binary is `sos-conformance`. It lives at `sim/sos-conformance/` as a second workspace member alongside `sim/sos-sim/` ([SOS-02 §6.1] layout); PCDN-SOS-03-004 ratifies the location.

### 7.1 CLI shape

```
sos-conformance run --suite <DIR> [--port <BIN>] [--filter <GLOB>] [--format <FORMAT>] [--out <PATH>]
sos-conformance --version
sos-conformance --help
```

Arguments:

| Flag | Type | Default | Meaning |
|---|---|---|---|
| `--suite <DIR>` | path (required) | — | Path to the suite root, typically `conformance/vectors/`. The harness scans this directory recursively for `*.json` files, excluding any `retired/` subtree. |
| `--port <BIN>` | path (optional) | `sos-sim` (resolved from `PATH` or from the workspace's `target/release/`) | The port binary to test. The harness invokes it per §7.6. When the default is in effect, the harness essentially tests `sos-sim` against itself — a degenerate but useful invocation (every vector trivially passes; verifies the suite is internally consistent). |
| `--filter <GLOB>` | string (optional) | `**/*.json` (match everything) | A glob pattern matched against vector paths *relative to* the `--suite` root. Examples: `smoke/*`, `**/queue*`, `boundary/**`, `regression/0007-*`. `globset` semantics (§7.5). |
| `--format <FORMAT>` | one of `human`, `json` (optional) | `human` | Output format. `human` is multi-line per-failure with summary at the end. `json` is a single JSON document for CI consumption (§7.3). |
| `--out <PATH>` | path (optional) | stdout | Where the report is written. `-` (or omitted) writes to stdout. |

The binary MUST NOT consult environment variables for behaviour (mirrors [SOS-02 §6.5] `INV-S-SIM-2` at the harness surface). It MUST NOT open files other than the suite tree (input) and the `--out` path (output). It MAY consult `PATH` to resolve `--port` when given a bare command name; once resolved, the absolute path is logged in the report's preamble (so the report is reproducible even if `PATH` changes).

### 7.2 Exit codes

| Code | Meaning |
|---|---|
| `0` | All matched vectors passed. |
| `1` | Setup / parse error: a vector file is malformed, the suite directory does not exist, `--filter` is an invalid glob, the schema check fails for any vector. The harness exits before running any vector. |
| `2` | At least one vector failed (any combination of `bytes_differ`, `record_count_mismatch`, `parse_error` from the port). The report enumerates which. |
| `3` | The port binary is missing, not executable, or fails to start (e.g. cannot be exec'd). Distinct from `2` because a missing binary is an operator error, not a port defect. |
| `4` | I/O error reading the suite or writing the report. |
| `5` | Reserved. |

The harness MUST exit with the most-severe applicable code. If setup fails (any vector unparseable), exit `1` and report only the setup failures — do not attempt to run any port. If the port is unrunnable, exit `3` and report the resolution path attempted.

### 7.3 Output format

`--format human` (default):

```
SOS-CONFORMANCE — suite: conformance/vectors/  port: ./target/release/sos-sim
Filter: **/*.json
Vectors scanned: 32
Vectors run:     32 (28 pass, 4 fail)

FAIL  smoke/0004-queue-full-empty-rejection-vs-block-timeout
      Record 7: tcb[2].state — expected 5 (ST_BLK_QS), actual 4 (ST_BLK_SEM)
      Record 7: tcb[2].blk_obj — expected 0, actual 1

FAIL  boundary/0011-queue-direct-handoff-at-capacity
      Record count mismatch — expected 12, actual 11
      Tail records missing: [11]

...

By category:
  smoke:      5 pass /  6 total  ( 1 fail)
  boundary:  14 pass / 15 total  ( 1 fail)
  stress:     7 pass /  8 total  ( 1 fail)
  regression: 2 pass /  3 total  ( 1 fail)
  diversity:  0 pass /  0 total  ( 0 fail)

Conformance: NOT FullSuitePass.
```

`--format json` (CI consumption):

```json
{
  "schema_version": 1,
  "suite_root": "conformance/vectors/",
  "port_binary": "/abs/path/to/sos-sim",
  "filter": "**/*.json",
  "vectors_scanned": 32,
  "vectors_run": 32,
  "vectors_passed": 28,
  "vectors_failed": 4,
  "by_category": {
    "smoke":      { "pass": 5, "total": 6, "fail_ids": [4] },
    "boundary":   { "pass": 14, "total": 15, "fail_ids": [11] },
    "stress":     { "pass": 7, "total": 8, "fail_ids": [3] },
    "regression": { "pass": 2, "total": 3, "fail_ids": [1] },
    "diversity":  { "pass": 0, "total": 0, "fail_ids": [] }
  },
  "failures": [
    {
      "vector": "smoke/0004-queue-full-empty-rejection-vs-block-timeout",
      "diffs": [
        { "record_index": 7, "field_path": "tcb[2].state", "severity": "bytes_differ", "expected": 5, "actual": 4 },
        { "record_index": 7, "field_path": "tcb[2].blk_obj", "severity": "bytes_differ", "expected": 0, "actual": 1 }
      ]
    }
  ],
  "conformance_level_achieved": "SmokePartial",
  "highest_full_pass_level": null
}
```

The `conformance_level_achieved` is a textual rollup — `FullSuitePassWithDiversity` / `FullSuitePass` / `SmokePass` / `SmokePartial` (less than full Smoke) / `Empty` (no vectors matched the filter). `highest_full_pass_level` is the highest §5.2 grade fully achieved (one of the three enum values, or `null` if even `SmokePass` fails).

The JSON schema version is `1`. Bumping is a §15 amendment.

### 7.4 Vector expansion / mining (reserved slot)

A future `SOS-03-B` amendment may add a **regression-vector miner** — a tool that:

1. Reads `docs/concepts/ERRATA.md`.
2. For each resolved entry that names a reproducer (a minimal event sequence), generates a `Regression`-category vector that fixes the input and freezes the expected trace under the current `sos-sim`.
3. Files a PR with the new vector and the cross-reference to the ERRATA entry.

The miner is **not implemented at v1**. The spec slot exists so the eventual implementation has a known design surface (input: ERRATA.md; output: `conformance/vectors/regression/`; gates: Specification Required per `VectorCategory::Regression`'s policy). Until the miner ships, `Regression` vectors are hand-authored with `origin: "Authored"` and a `description` citing the ERRATA id.

### 7.5 Filter syntax

The `--filter <GLOB>` argument uses `globset` semantics on the relative vector path (relative to `--suite`). Specifically:

- `*` matches any sequence of characters except `/`.
- `**` matches any sequence of characters including `/` (zero or more path components).
- `?` matches any single character except `/`.
- `[abc]` matches any character in the set.
- `[!abc]` matches any character not in the set.
- `{a,b,c}` matches any of the alternatives.

Examples:

| Glob | Matches |
|---|---|
| `smoke/*` | Every `*.json` directly in `smoke/`. |
| `**/queue*` | Every vector whose filename begins with `queue` at any depth. |
| `boundary/**` | Every vector under `boundary/` (recursive — though `boundary/` itself is flat at v1). |
| `regression/0007-*` | Specific regression vector by id prefix. |
| `{smoke,regression}/*` | Smoke and Regression vectors. |

The default `**/*.json` matches every JSON file under `--suite` (excluding `retired/`).

**A glob that does not match any vector** is NOT an error — the harness reports `vectors_scanned: N, vectors_run: 0` and exits `0`. The reasoning: a CI job that filters by tag (e.g. "only run queue vectors on this branch") should not fail when the branch has no matching vectors.

### 7.6 Port-binary contract

A port binary is invoked with no arguments (`exec(port_bin)` — the port reads its work from stdin). The harness:

1. Spawns the port binary as a child process.
2. Writes one vector's `input` to the child's stdin as a complete JSON document (an array). Closes stdin.
3. Reads the child's stdout to EOF. Each line is one JSON-encoded `TraceRecord` per [SOS-02 §7].
4. Waits for the child to exit. The exit code is logged but does NOT affect the harness's exit code; only the diff result does. (A port that exits non-zero AND produces an exactly-matching trace is conformant — a wedge case, but the spec is clear: trace equality is the contract.)
5. Diffs the parsed records against the vector's `expected_trace` per §6.5.
6. Continues to the next vector (or exits if filter exhausted).

The port binary MUST:

- Read the vector input as a single JSON document on stdin. The input is an array of event objects, NOT a wrapped object; the `name`, `description`, `config`, etc. are stripped by the harness before stdin is written.
- Wait — actually, the input is a *wrapped* object containing `config` and `input` (the vector's input array), because the port needs `config` to size its internal arrays. Specifically the harness writes `{"config": {...}, "input": [...]}` to stdin. The wrapped form is the **port input format**.
- Emit one JSONL record per macrostep boundary on stdout, in the order [SOS-02 §6.4] specifies (boot baseline first, then one per input event).
- Flush stdout between records ([SOS-02] INV-S-SIM-7).
- Exit cleanly (any exit code; harness ignores it for conformance purposes).

The port binary MUST NOT:

- Print anything to stdout that is not a JSONL trace record. Stderr is free-form; the harness captures it for diagnostic reporting but does not parse it.
- Open files other than stdin/stdout (no `--out`-style flag; the harness owns the I/O boundary).
- Read environment variables for behaviour (mirrors INV-S-SIM-2 at the port surface; non-conforming ports MAY do so but should not depend on it).
- Spawn subprocesses, listen on sockets, or perform network I/O.

The default port `sos-sim` satisfies this contract via its `sos-sim run --vector -` invocation; the harness invokes `sos-sim run --vector -` when the default is in effect (the `--vector -` reads from stdin per [SOS-02 §6.6]). M7 ports satisfy the contract by running the same surface on the bench-side host that talks to the disco-analyzer (probe-rs RTT stream, or post-run SRAM dump assembly — the per-port phase doc decides the bench-side adapter; the harness just sees a binary that reads stdin and writes stdout).

## 8. Build-time and runtime artifact map

| Artifact | Path (relative to subrepo root) | Build-time? | Runtime? | Notes |
|---|---|---|---|---|
| Workspace `Cargo.toml` | `Cargo.toml` | input | n/a | Pre-existing post-[SOS-02] PCDN-005. SOS-03 adds `sim/sos-conformance/` as a workspace member. |
| `sos-conformance` crate | `sim/sos-conformance/` | n/a | host binary | The harness. Standalone Rust crate. |
| `sos-conformance` library | `sim/sos-conformance/src/lib.rs` | output | linked into bin + downstream consumers (e.g. a future fuzzing tool) |
| `sos-conformance` CLI | `sim/sos-conformance/src/bin/sos-conformance.rs` → `target/release/sos-conformance` | output | runtime | The host-runnable binary. |
| Suite root | `conformance/vectors/` | input | input | The vector tree per §6.1. |
| Per-category subtrees | `conformance/vectors/<category>/` | input | input | Five at v1: `smoke/`, `boundary/`, `stress/`, `regression/`, `diversity/`. Empty subtrees are permitted (an empty `diversity/` directory is the v1 default). |
| Retired-vector subtree | `conformance/vectors/retired/` | input | n/a | Reserved per INV-S-CONF-6. Empty at v1. |
| Suite-author README | `conformance/README.md` | input | n/a | Informative onboarding; SOS-01 lints for cross-doc drift if a future rule expands to cover it (currently SOS-01 lints only `docs/REFERENCE.md`). |
| Unit tests (harness internals) | `sim/sos-conformance/tests/` | n/a | `cargo test -p sos-conformance` | Smoke tests for the diff implementation, the loader, the filter parser. NOT the vector suite; the suite is the integration test surface. |

The vector files are **hand-authored (or miner-generated) inputs**, never build-time outputs. INV-S-CONF-3 forbids regen at build time: the author runs `sos-sim` once, captures the trace, commits it to the vector file, and the file is canonical from then on. Regen against a new `sos-sim` build is a §15 amendment per INV-S-CONF-6.

Build commands (host, no cross-compile):

```
# Build the harness
cargo build -p sos-conformance
cargo build --release -p sos-conformance

# Run against the default port (sos-sim, degenerate case)
cargo run --release -p sos-conformance -- run --suite conformance/vectors/

# Run against a non-default port
./target/release/sos-conformance run --suite conformance/vectors/ \
    --port ./target/m7-rust-port/sos-m7-rust-host-driver

# Run a filtered subset
./target/release/sos-conformance run --suite conformance/vectors/ --filter 'smoke/*'

# CI consumption
./target/release/sos-conformance run --suite conformance/vectors/ --format json --out /tmp/report.json
```

## 9. Invariants

Each invariant carries a stable id in the `INV-S-CONF-N` series. Amendments require a §15 entry on this doc.

- **INV-S-CONF-1 — Byte-identical trace contract.** A conforming port MUST produce a trace that compares **structurally equal** (per the §6.5 record-by-record comparison) to the vector's `expected_trace` for every vector in the suite at the suite's pinned Suite SHA. "Byte-identical" in the spirit of [SOS-02] INV-S-SIM-1 holds for `sos-sim`'s own output; the harness relaxes byte-level equality at the JSONL framing boundary (whitespace, ordering of `valid: false` short form) but holds it at the record-field-value level. Trace divergence is a port defect, never a spec defect (mirrors [SOS-00] INV-S13 at the suite surface).

- **INV-S-CONF-2 — Deterministic replay.** Running `sos-conformance` twice on the same `(suite, port_binary, filter)` triple MUST yield the same exit code AND the same diff record set in the same order. (The harness MAY differ on absolute timestamps in human-readable output; the JSON output MUST be byte-identical across runs.) This invariant derives from [SOS-02] INV-S-SIM-1 (when the port IS `sos-sim`) and from the conformance contract (when the port is anything else).

- **INV-S-CONF-3 — `expected_trace` is generated by `sos-sim`.** The `expected_trace` field of every vector in the suite MUST have been generated by running `sos-sim` over the vector's `input`. Manually-authored or hand-edited expected traces are **forbidden**. The verification step at vector-add PR time is: regenerate the trace from the vector's `input` using the current `sos-sim`, byte-compare against the file's `expected_trace`, reject the PR on diff. (The verification is a tool the implementation commit lands; SOS-03 spec just declares the obligation.)

- **INV-S-CONF-4 — Stable ids.** A vector's id (the zero-padded sequential prefix in its filename) is stable for the lifetime of the vector. Renaming the slug part is **allowed** (e.g. renaming for clarity); renaming the id is **not** (it would break ERRATA cross-references and port-side §15 entries). Retiring a vector (moving to `retired/`) preserves the id; the retired-tree filename is `retired/<category>/<NNNN>-<original-slug>.json`.

- **INV-S-CONF-5 — `Smoke` adds require §15 amendment.** Adding a vector to `conformance/vectors/smoke/` requires a §15 amendment to this doc (Standards Action per §5.1). Other categories accept vectors via PR-level review (Specification Required) or PR-level note (Expert Review for Diversity). The asymmetric gate is deliberate: the Smoke set is the closed minimal core that defines `SmokePass`; mutations to it change the meaning of every port's `SmokePass` claim.

- **INV-S-CONF-6 — Retirement requires §15 amendment.** Moving any vector to `retired/` (whatever its category) requires a §15 amendment on this doc citing the retirement rationale, the resolving commit, and any port-side §15 entries that previously cited the vector. Retired vectors stay in-tree (under `retired/`) as archaeological reference; the harness's default scan excludes them.

- **INV-S-CONF-7 — Sequential, not parallel, port execution.** The harness MUST run vectors against the port binary **sequentially**. Parallel execution is forbidden because a port that has external side-effects (a port that writes to a debug log, a port that talks to a bench fixture) may have its observable state corrupted by overlap. Sequential execution is the safe default that does not assume the port is side-effect-free. (Performance is a non-goal; the suite is small enough that wall-clock matters for nobody at v1.)

- **INV-S-CONF-8 — No suite-time regeneration.** The harness MUST NOT regenerate `expected_trace` on the fly. If a port's output disagrees with `expected_trace`, the harness reports a diff; it does not silently re-record the expected trace against the failing port's output. Regen is a §15 amendment per INV-S-CONF-6, executed by a separate operator-driven tool (not the harness), against `sos-sim` only.

- **INV-S-CONF-9 — Schema versioning.** The vector JSON schema is versioned by this doc's §15 entries. Field additions / removals require a §15 amendment AND a coordinated update to every vector in the suite. Pre-amendment vectors that are not updated retire under INV-S-CONF-6.

- **INV-S-CONF-10 — Concrete fixtures, not generators.** The conformance surface is **concrete vectors**. Property-based generators, fuzz harnesses, model-checked specifications are explicit non-goals (§11). Vectors are auditable artifacts authors and reviewers read with their eyes; generators are a separate (future) surface.

- **INV-S-CONF-11 — Independence from chart SHA.** A vector's `expected_trace` is pinned to the `sos-sim` build that generated it; that `sos-sim` build is pinned to a chart SHA at compile time per [SOS-02] INV-S-SIM-8. The Suite SHA recorded in this doc's §15 entries IS the chart SHA at which the suite was last regenerated. A chart change that does not regenerate vectors creates an inconsistent suite — INV-S-CONF-3 verification will catch it at the next vector-add PR. The chart-edit + vector-regen + §15 amendment is one coordinated commit (mirrors [SOS-00] INV-S11 at the suite surface).

- **INV-S-CONF-12 — Filter glob does not gate exit code.** A `--filter` that matches zero vectors exits `0` with `vectors_run: 0`. The harness does not interpret "no vectors matched" as a failure. Rationale: CI jobs that filter by tag and have no matching vectors today should not pre-emptively fail; the absence-of-matching-vectors is data, not error.

## 10. Reconciliation with adjacent primitives

| Primitive | Relationship to SOS-03 |
|---|---|
| `streamz-exec` (parent `softoboros.com` Tokio-hosted runtime) | Not a consumer. `sos-conformance` is a host binary; it is not orchestrated by `streamz-exec`. |
| `sos-sim` ([SOS-02]) | Library dependency. `sos-conformance` `use`s `sos_sim::{Simulator, Vector, Trace, TraceRecord, Config, Event}`. The harness's default `--port` invokes the `sos-sim` binary in a separate process (so the harness's port-binary code path is exercised even in the degenerate self-test case). |
| `cargo test` per-crate unit tests | Adjacent, NOT replaced. `cargo test -p sos-sim` runs the simulator's smoke tests ([SOS-02 §8] tests/). `cargo test -p sos-conformance` runs the harness's diff-implementation and loader tests. Neither runs the conformance suite — that is `sos-conformance run --suite conformance/vectors/`. The two surfaces are deliberately separate; conflating them would make `cargo test` either slow (running the full suite) or incomplete (skipping the suite). |
| `cortex-m` / `cortex-m-rt` crates | Not a dependency (INV-S-SIM-4 inheritance). The harness is host-only. M7 ports are downstream consumers of the harness, not dependencies of it. |
| FreeRTOS-Kernel at `disco-analyzer/analyzer-rtos/` | Not a dependency (INV-S10 inheritance). |
| `serde` / `serde_json` / `clap` / `anyhow` / `globset` | Mirror dependencies. Pinned in workspace `Cargo.lock`; no SOS-03-side forks. |
| SOS-04 (M7 Rust port, future) | Consumer. SOS-04's port binary satisfies the §7.6 port-binary contract; SOS-04's `cargo test` does NOT run the conformance suite (the harness runs it, on host, against the cross-compiled SOS-04 port binary). SOS-04 §15 cites the `ConformanceLevel` it achieves. |
| SOS-05 (M7 C port, future) | Consumer. Symmetric to SOS-04. |
| SOS-06 (codegen evaluation, future) | Consumer. The codegen output produces a port binary that satisfies §7.6; the harness compares its output against `sos-sim`. SOS-06's decision (codegen-canonical vs codegen-historical) hinges on the `ConformanceLevel` achieved. |
| Fuzzing / property-based testing | Not the same surface. SOS-03 vectors are concrete fixtures (INV-S-CONF-10). A future fuzzing phase would author its own non-overlapping surface (§11 non-goal). |
| Performance benchmarking | Not the same surface. The harness measures conformance (functional equivalence), not throughput. A future perf phase is a separate non-overlapping surface (§11 non-goal). |
| Coverage tracking | Not the same surface at v1. Whether the vector suite covers every chart transition / every script statement is an open question; coverage tooling is a §11 non-goal at v1 and a candidate for a `SOS-03-C` amendment if the question becomes pressing. |

`sos-conformance` is a **host-only Rust binary** that consumes vector fixtures and a port binary, producing a pass / fail report. It is not a runtime kernel surface, not a build-time codegen tool, not a test runner in the `cargo test` sense.

## 11. Non-goals

Frozen non-goals for SOS-03 v1. Each MAY lift via a §15 amendment.

- **Fuzzing.** Property-based generators (`proptest`, `quickcheck`) and grammar-aware fuzzers (`libfuzzer-sys`, `afl.rs`) are explicit non-goals. The conformance surface is concrete vectors (INV-S-CONF-10). A future `SOS-03-F` amendment may ratify a fuzzing surface that is *adjacent* to the suite, not a replacement for it.
- **Property-based testing.** Same surface as fuzzing — a generator that produces "any vector satisfying property P". v1 conformance is hand-authored fixtures. Future amendment if the suite grows past ~200 vectors and human authoring becomes the bottleneck.
- **Performance benchmarking.** Wall-clock latency, throughput, cycles-per-syscall are out of scope. The suite verifies functional equivalence; performance is a separate surface owned by per-port phases or a future `SOS-PERF-NN` initiative.
- **Coverage tracking.** Whether the suite covers every transition, every branch in every script body, every datamodel field permutation — these are valuable questions but not load-bearing for v1. Coverage tooling integration ratifies in a future amendment if the question becomes operative.
- **Multi-port simultaneous comparison.** The harness runs one port at a time (INV-S-CONF-7). A future "compare two ports against each other" surface (rather than each-vs-`sos-sim`) is a §15 amendment candidate; v1 always uses `sos-sim` as the reference.
- **Vector minimisation / shrinking.** When a port fails on a 200-event vector, a "find the minimal input prefix that still fails" tool is appealing — but it requires re-running the port many times and v1 vectors are small enough that shrinking is unnecessary. Future amendment if vector size grows.
- **Vector composition.** The ability to "concatenate vector A and vector B and verify the combined trace" is appealing for stress-suite construction — but at v1 we author the stress vector explicitly. Composition is a future authoring-time tool, not a runtime feature.
- **Interactive vector debugging.** Step-through, record-by-record inspection, pause-on-first-diff is appealing but is the territory of a separate downstream tool (a debugger that uses the harness's library API), not the v1 binary.
- **Cross-version expected-trace migration.** When `sos-sim` changes its trace format in a non-backward-compatible way, every vector regenerates. There is no migration story for old vector files; the §15 amendment that authorises the format change also authorises full suite regen.
- **Vector localisation.** Vectors are English-named. There is no plan to localise.
- **Vector graphical visualisation.** A state-diagram replay viewer that animates the trace is appealing — but it is a separate downstream tool, not bounded by this phase.
- **Web-based suite browser.** Same as above.
- **Integration with external test runners.** The harness has its own CLI; integration with `bazel test`, `nextest`, etc. is the downstream consumer's job.
- **JSON-Schema validation as a separate phase.** The schema in §6.2 is informal-but-precise English prose; producing a machine-readable JSON Schema document is appealing for IDE tooling but is a future amendment, not v1.

## 12. Acceptance checklist (normative)

### 12.1 Ratification gates

A conforming SOS-03 ratification (the §15 dated entry that flips this doc to 🟢) requires:

(a) All PCDN-SOS-03-NNN open questions in §15 are resolved. Every PCDN has a chosen value, a date, and the corresponding §4 / §5 / §6 / §7 sections updated to reflect the choice.

(b) §3 glossary, §4 source-of-truth map, §5 frozen enums, §6 vector file format, §7 harness behaviour, §9 invariants are internally consistent. A reviewer can answer "what does X mean" by reading at most one section. No vocabulary defined in [SOS-00 §3] / [SOS-01 §3] / [SOS-02 §3] is silently restated here.

(c) §6.2 schema covers every field that appears in §6.6's seed-suite example. A reviewer can §6.2-walk the §6.6 file shape and check every required field is documented.

(d) §6.4 `from_tid` semantics are consistent with [SOS-00 §7.1]. A reviewer can cross-check this doc's §6.4 against [SOS-00 §7.1] and find no contradiction.

(e) §6.5 diff-comparison policy walks every field in [SOS-02 §5.4] `ObservableField`. No field is named in [SOS-02 §5.4] that this doc's §6.5 fails to specify.

(f) §6.6 seed-suite mapping covers exactly the six seeds from [SOS-00 §7.4]. A reviewer can cross-check the seed list and find every seed mapped to exactly one entry in §6.6.

(g) §9 INV-S-CONF-N invariants are pairwise non-contradictory with [SOS-00 §9] INV-S-N invariants and [SOS-02 §9] INV-S-SIM-N invariants. Any INV-S-CONF that *relaxes* a parent invariant (none anticipated at v1) MUST cite the parent invariant and the scope of the relaxation.

(h) §10 reconciliation list covers every adjacent primitive a reviewer might confuse SOS-03 with.

(i) §11 non-goal list is exhaustive for the SOS-03 v1 horizon.

### 12.2 Implementation-commit gates

A conforming `sos-conformance` implementation (a `cargo build -p sos-conformance` plus the vendored seed-suite fixtures) additionally requires:

(j) The `sim/sos-conformance/Cargo.toml` declares dependencies pinned per §4: `serde`, `serde_json`, `clap`, `anyhow`, `globset`, and `sos-sim` (library, path = "../sos-sim").

(k) The binary `sos-conformance --version` prints a version matching the `Cargo.toml` `version` field and the Suite SHA recorded in this doc's §15 at the implementation-commit time.

(l) `cargo test -p sos-conformance` passes on Linux x86_64 and macOS arm64 at the pinned MSRV (inherits [SOS-02] PCDN-004 → `1.75`).

(m) Six seed-vector fixtures land at `conformance/vectors/smoke/0001-...` through `0006-...`, each generated by `sos-sim` per INV-S-CONF-3.

(n) `sos-conformance run --suite conformance/vectors/ --port target/release/sos-sim` exits `0` with `6 pass / 6 total` against the seed suite.

(o) The binary returns exit code 1 on a malformed vector (a synthetic broken fixture in `tests/fixtures/`), exit code 2 on a port that emits a tampered trace (a synthetic divergent port binary in `tests/fixtures/`), exit code 3 on a `--port` path that does not exist, exit code 4 on a `--out` path that is unwritable.

## 13. Files cited

| Path | Role | Status |
|---|---|---|
| `streamz/submodules/SOS/rtos_kernel.scxml` | Canonical kernel spec; pinned at the Suite SHA per §15 | exists |
| `streamz/submodules/SOS/docs/REFERENCE.md` | Informative chart mirror; the seed-vector list is derived from § "Testing surface" | exists |
| `streamz/submodules/SOS/docs/concepts/SOS-00-CONCEPTS.md` | Parent concepts doc; §5 frozen enums, §7 observable-state subset, §7.1 vector shape example, §7.4 seed-vector list, §9 invariants | exists (🟢 ratified 2026-05-19) |
| `streamz/submodules/SOS/docs/concepts/SOS-01-CONCEPTS.md` | Sibling phase; §5.3 ExternalEventName, §5.4 StateId | exists (🟢 ratified 2026-05-19) |
| `streamz/submodules/SOS/docs/concepts/SOS-02-CONCEPTS.md` | Sibling phase; §5.4 ObservableField, §6.1 module layout, §6.3 Msg representation, §7 trace serialisation format, §9 simulator invariants | exists (🟢 ratified 2026-05-19) |
| `streamz/submodules/SOS/docs/concepts/README.md` | Initiative index; SOS-03 listed as 🔴 not started until this doc ratifies | exists |
| `streamz/submodules/SOS/docs/concepts/ERRATA.md` | Errata log; Regression-category vectors cite ERRATA ids | exists (skeleton, no entries) |
| `streamz/submodules/SOS/AGENTS.md` | Subrepo contributor guidance | exists |
| `streamz/submodules/SOS/CLAUDE.md` | Subrepo agent runbook | exists |
| `streamz/submodules/SOS/sim/sos-sim/` | Reference simulator crate (consumed as library) | does not yet exist (lands at SOS-02 implementation commit) |
| `streamz/submodules/SOS/sim/sos-conformance/` | Harness crate root (post-ratification) | does not yet exist |
| `streamz/submodules/SOS/sim/sos-conformance/Cargo.toml` | Crate manifest (post-ratification) | does not yet exist |
| `streamz/submodules/SOS/sim/sos-conformance/src/lib.rs` | Library entry point (post-ratification) | does not yet exist |
| `streamz/submodules/SOS/sim/sos-conformance/src/bin/sos-conformance.rs` | CLI binary (post-ratification) | does not yet exist |
| `streamz/submodules/SOS/conformance/vectors/smoke/0001-...` through `0006-...` | The seed-vector fixtures (post-ratification implementation commit) | does not yet exist |
| `streamz/submodules/SOS/conformance/vectors/{boundary,stress,regression,diversity,retired}/` | Category subdirectories (post-ratification, may be empty at v1 land) | does not yet exist |
| `streamz/submodules/SOS/conformance/README.md` | Vector-author onboarding (post-ratification, informative) | does not yet exist |
| Parent CLAUDE.md, "Spec-Before-Code Planning Discipline" | Governing discipline | exists at parent root |
| Parent CLAUDE.md, "Frozen enumerations — registration policy" | Registration-policy convention used by §5 enums | exists at parent root |
| Parent CLAUDE.md, "Per-initiative ERRATA.md" | Errata convention; Regression vectors cite ERRATA ids per §5.1 | exists at parent root |
| W3C SCXML 1.0 Recommendation §3.13 (Macrosteps) | Macrostep semantics, inherited via [SOS-02 §6.2] | external, cited |
| RFC 7464 / JSONL convention | Trace + diff-report wire format | external, cited |
| RFC 8259 (JSON) | Vector + report wire format | external, cited |

## 14. Unblocks

SOS-03 ratification unblocks:

- **SOS-04 (M7 Rust port).** With a ratified vector suite and harness, SOS-04 has a concrete target: produce a port binary that the harness drives to `FullSuitePass` against the v1 suite. The port binary's stdin / stdout contract (§7.6) lets the bench-side host adapter live entirely outside the M7 firmware — the firmware emits trace records on RTT or to SRAM; the host-side driver concatenates them as JSONL and pipes through the port-binary contract.
- **SOS-05 (M7 C port).** Symmetric to SOS-04.
- **SOS-06 (codegen evaluation).** The codegen tool produces a port binary; the harness compares against `sos-sim`. SOS-06's canonical-or-historical decision turns on the conformance level the generated port achieves.

SOS-03 does NOT unblock further SOS-01 / SOS-02 work directly; those phases are ratified independently. The suite is downstream of both: it consumes [SOS-01]'s event-name freeze and [SOS-02]'s trace-format freeze.

The implementation commit (sos-conformance crate scaffold + six seed-vector fixtures + cross-doc README) is independently and immediately dispatchable in parallel with SOS-04 / SOS-05 drafting (file-disjoint: SOS-03 implementation writes `sim/sos-conformance/**` and `conformance/vectors/**`; SOS-04 / SOS-05 drafting writes only their own concepts docs).

## 15. Change log

### 2026-05-19 — Initial draft (Ira)

- Document drafted at `docs/concepts/SOS-03-CONCEPTS.md`. Sections §0–§14 populated.
- §5.1 (`VectorCategory`) introduces five categories with split Standards-Action / Specification-Required / Expert-Review registration policies.
- §5.2 (`ConformanceLevel`) introduces three grades: `SmokePass`, `FullSuitePass`, `FullSuitePassWithDiversity`. The default-when-unqualified is `FullSuitePass`.
- §5.3 (`DiffSeverity`) introduces four severities: `exact`, `bytes_differ`, `record_count_mismatch`, `parse_error`.
- §5.4 (`VectorOrigin`) introduces three origins: `Seed`, `Authored`, `RegressionMined`.
- §6 (vector file format) is the load-bearing section: directory layout, JSON schema, naming convention, `from_tid` semantics, structural diff policy, seed-suite mapping.
- §7 (harness behaviour) ratifies the CLI shape, exit codes, output format (`human` + `json`), filter glob semantics, port-binary contract.
- §9 introduces twelve INV-S-CONF-N invariants, pairwise checked against [SOS-00 §9] and [SOS-02 §9].
- §10 reconciliation explicitly disclaims `streamz-exec`, `cortex-m`, FreeRTOS, fuzzing, property-based testing, performance benchmarking, coverage tracking.

PCDN list awaiting resolution:

- **PCDN-SOS-03-001 — Diff comparison policy: byte-exact JSONL stream vs. structural JSON-tree comparison.** **Resolved structural per record 2026-05-19.** The vector file embeds `expected_trace` as a JSON array (not raw JSONL), so byte-exact at the stream level would require a re-serialisation step that introduces `serde_json` version coupling. Structural per record is more diagnostic (precise `field_path` reporting), more stable across `serde_json` minor bumps, and equivalent in coverage (integers compare byte-identically regardless of representation). The §6.5 spec ratifies structural; PCDN-001 confirms.

- **PCDN-SOS-03-002 — Vector file format: JSON vs YAML vs TOML.** **Resolved JSON 2026-05-19.** Round-trippability with the [SOS-02 §7] trace format is load-bearing; `expected_trace` is a JSON array of `TraceRecord` objects, so the vector container being JSON lets the trace embed without translation. YAML would require yaml-to-json round-tripping (and YAML's ambiguous-scalar semantics — `no` parsed as boolean false, etc. — is exactly the kind of footgun a spec-lineage repo avoids). TOML lacks deep-nested-array ergonomics for `expected_trace`. JSON is verbose but unambiguous; the verbosity is acceptable for hand-authored fixtures.

- **PCDN-SOS-03-003 — `expected_trace` generation policy: committed-by-author vs build-time-generated.** **Resolved committed-by-author 2026-05-19** (user-noted load-bearing reason: "auditable vectors are important" — vector files must show the human exactly what CI is comparing against). A vector author runs `sos-sim` once, pipes the output into the vector file (a tool that lands at SOS-03 implementation time makes this a one-liner), and commits the result. INV-S-CONF-3 enforces that the committed expected trace must round-trip against the current `sos-sim` at PR time — a CI gate the SOS-03 implementation commit lands alongside the harness. The alternative (regenerate at build time) makes vectors non-auditable (the file's content is not what the human committed) and tightly couples the vector to whatever `sos-sim` build the CI runner happened to pick up.

- **PCDN-SOS-03-004 — Harness binary location: same workspace as `sos-sim` vs separate crate.** **Resolved same workspace, separate crate 2026-05-19.** `sim/sos-conformance/` lives next to `sim/sos-sim/` in the SOS subrepo's Cargo workspace (per [SOS-02] PCDN-005 → standalone workspace at subrepo root). The crates are independent (each has its own `Cargo.toml`, `src/`, `tests/`); the workspace shares `Cargo.lock` and `target/` only. The alternative (a single `sos-sim` crate that vends both the simulator binary and the conformance binary) collapses the API boundary between "kernel reference implementation" and "test tool"; SOS-02 INV-S-SIM-4 (host-only target) plus this doc's INV-S-CONF-7 (sequential port execution) are different invariant surfaces and benefit from crate-level separation.

- **PCDN-SOS-03-005 — Vector ID allocation: manual sequential vs auto-generated.** **Resolved manual sequential 2026-05-19.** Authors pick the next free zero-padded id per category at PR time; reviewers verify uniqueness via `ls conformance/vectors/<category>/`. The alternative (auto-generation by a tool at vector-add time) creates a worse failure mode — two concurrent PRs both pick `0007`, the merge-conflict is silent if the tool runs at land-time vs PR-time. Manual id allocation surfaces collisions at PR-review time (a reviewer rejects the second of two simultaneous `0007`s and the second author re-ids to `0008`). The administrative cost is low; the safety property is high.

- **PCDN-SOS-03-006 — `globset` dependency for `--filter`.** **Resolved `globset = "0.4"` 2026-05-19.** Glob matching is small but easy to get wrong (especially `**` semantics); using a mature crate avoids hand-rolled bugs. The transitive dependency footprint is small (`globset` pulls in `regex-syntax` and `aho-corasick`, both already common in the Rust ecosystem and built once at workspace level). Alternative considered: hand-rolled glob limited to `*`, `**`, `?` — rejected because the savings (one fewer dependency) are dwarfed by the risk of subtle glob bugs.

- **PCDN-SOS-03-007 — `valid: false` short-form policy in vector files.** **Resolved short form canonical 2026-05-19.** When a sem or queue slot is invalid, the vector file's `expected_trace` carries `{"valid": false}` only, without `count`, `max`, `waiters`, etc. — matching [SOS-02 §7.2]. The harness rejects expanded forms (`{"valid": false, "count": 0, ...}`) as parse errors. Rationale: forward-compatibility — the expanded form would over-specify the inner-fields' default values, making future amendments to the default-values impossible without invalidating every vector. The short form encodes "this slot is invalid and we don't care about its inner state".

Acceptance checklist (§12) compliance at draft:

- (a) ⏸ PCDNs pending user ratification.
- (b) ✅ Glossary, source-of-truth map, frozen enums, vector file format, harness behaviour, invariants internally consistent.
- (c) ✅ §6.2 schema covers every field appearing in §6.6's seed-suite example.
- (d) ✅ §6.4 `from_tid` semantics consistent with [SOS-00 §7.1].
- (e) ✅ §6.5 diff-comparison policy walks every field in [SOS-02 §5.4].
- (f) ✅ §6.6 seed-suite mapping covers exactly the six seeds from [SOS-00 §7.4].
- (g) ✅ INV-S-CONF-N invariants pairwise non-contradictory with [SOS-00 §9] and [SOS-02 §9].
- (h) ✅ §10 reconciliation covers `streamz-exec`, `cortex-m`, FreeRTOS, fuzzing, property-based testing, performance, coverage, sibling SOS phases.
- (i) ✅ Non-goal list bounded to v1 horizon.
- (j)–(o) ⏸ Implementation-commit gates by design — they ratify when the follow-up commit lands `sim/sos-conformance/` and `conformance/vectors/smoke/0001-...0006-...`.

Status: 🟡 drafted; awaiting user PCDN walk-through and ratification before SOS-04 and SOS-05 begin.

### 2026-05-19 — Ratification (Ira)

User walked the PCDN list and ratified every open question. SOS-03 status moves from 🟡 drafted to **🟢 ratified**. SOS-04 / SOS-05 unblocked; SOS-03 implementation (sos-conformance harness scaffold + seed vector fixtures + structural-diff CI gate) rides on a follow-up commit.

Consolidated resolutions:

- **PCDN-001:** structural per record (more diagnostic; stable across `serde_json` minor bumps).
- **PCDN-002:** JSON (round-trippability with SOS-02 §7 trace format; avoids YAML scalar-ambiguity footguns).
- **PCDN-003:** committed-by-author (user emphasised: vectors must be auditable — the committed bytes are what CI compares against).
- **PCDN-004:** same workspace, separate crate (`sim/sos-conformance/`).
- **PCDN-005:** manual sequential vector ID allocation (collisions surface at PR-review time, not at land-time).
- **PCDN-006:** `globset = "0.4"` (mature glob library beats hand-rolled).
- **PCDN-007:** short form canonical for `{"valid": false}` (forward-compat for default-value evolution).

Acceptance checklist (§12) compliance at ratification:

- (a)–(i) ✅ Ratification gates met.
- (j)–(o) ⏸ Implementation-commit gates by design — they ratify when the follow-up commit lands `sim/sos-conformance/`, the 6 seed vector fixtures, and the CI workflow extension that runs the harness on every PR.

Unblocks: SOS-04, SOS-05, SOS-06. The SOS-03 implementation commit is independently dispatchable in parallel with SOS-04 / SOS-05 drafting (file-disjoint).

### 2026-05-19 — Amendment 001: ratify snake_case as canonical JSON form (Ira)

SOS-03 implementation scaffold drafting surfaced a contradiction: §6.2 narrative described `VectorCategory` and `VectorOrigin` JSON forms as PascalCase (`"category": "Smoke"`, `"origin": "Seed"`), but the seed vector fixture (`conformance/vectors/smoke/0001-...json`) committed at implementation time uses snake_case (`"category": "smoke"`, `"origin": "seed"`), and the `sos-conformance` crate's `#[derive(Deserialize)] enum VectorCategory` carries `#[serde(rename_all = "snake_case")]`.

**Resolved snake_case 2026-05-19** (user-ratified) — matches the as-built fixtures, matches the Rust deserialiser, and matches the directory naming convention (`conformance/vectors/smoke/...`, not `conformance/vectors/Smoke/...`). §6.2 is amended: all enum-valued fields in vector files use snake_case for the JSON form (lowercase mapping of the Rust variant — `Smoke → "smoke"`, `Boundary → "boundary"`, `Stress → "stress"`, `Regression → "regression"`, `Diversity → "diversity"`; `Seed → "seed"`, `Authored → "authored"`, `RegressionMined → "regression_mined"`). The PascalCase wording in the original §6.2 draft is superseded.

The directory naming convention is unchanged (lowercase per category — already aligned). No fixture rewrites needed; the as-built seed vector is canonical. No code changes needed; the `#[serde(rename_all = "snake_case")]` derive is already correct.

### 2026-05-19 — Amendment 002: ratify port-binary stdin wire contract (Ira)

Wave 7's SOS-04 host-adapter agent (B) surfaced a three-way drift between SOS-03 §7.6, SOS-04 §6.2.1, and the as-implemented `sim/sos-conformance/src/port.rs::SubprocessPort::execute_vector`:

- §7.6 documents the port-binary stdin contract as `{"config": ..., "input": [...]}` — no `name`, no `expected_trace`, no metadata.
- SOS-04 §6.2.1 says the firmware's on-device JSON parser bails on the `name` field as a parse error.
- The harness implementation was sending the full `VectorFile` shape (`name`, `description`, `category`, `origin`, `tags`, `config`, `input`, `expected_trace`) on stdin — drifting from BOTH spec docs.

The three docs disagree about whether `name` belongs on the wire.

**Resolved: harness aligns with §7.6 and SOS-04 §6.2.1 — `name` is stripped at the harness layer.** Port-binary stdin carries ONLY `{"config": ..., "input": [...]}`. Other VectorFile metadata (`name`, `description`, `category`, `origin`, `tags`, `expected_trace`) lives in the vector file on the host side and is consumed by the harness for diff-reporting purposes, NOT transmitted to the port binary.

Rationale: the port-binary contract is a minimal "execute this kernel input sequence and emit the traces" interface. Vector metadata is a host-side concern. Keeping the wire format minimal (a) simplifies the firmware-side JSON parser surface, (b) eliminates the firmware-vs-harness drift class that surfaces only at integration time, and (c) matches what `sos-m7-rust-host-driver` (the byte-pass-through adapter) does — it forwards whatever the harness sends, so harness simplicity propagates downstream.

The wave-8 fix at `sim/sos-conformance/src/port.rs` introduces a dedicated `#[derive(Serialize)] struct PortBinaryInput<'a> { config: &'a Config, input: &'a [Event] }` that serialises ONLY the two fields the contract names. The existing `VectorFile` deserialiser remains untouched — `name`/`description`/etc. continue to populate from JSON for harness-side diff-reporting.

§7.6 unchanged (it was already correct); this amendment ratifies that the harness implementation NOW MATCHES §7.6's text. Future port-binary contract expansions ratify via §15 amendment naming the additional fields.

### 2026-05-23 — SOS-07 rename ratification (Ira)

The initiative rename from *Statechart-Orchestrated Scheduler* to **Statechart Orchestration System** is ratified through [`SOS-07-CONCEPTS.md`](./SOS-07-CONCEPTS.md). The acronym `SOS` is unchanged across this phase doc family; all in-text references continue to read as `SOS` for cross-doc citation stability.

Cross-phase invariants INV-SOS-A through H + the AuthorityRelationship matrix promote from informative roadmap text (`SOS-ROADMAP-07-PLUS.md`) to normative phase content in SOS-07. They cite by ID into SOS-03's normative sections without modifying any of SOS-03's frozen content.

Bootstrap-vs-general framing (SOS-07 §8): the kernel chart `rtos_kernel.scxml` is reframed as the v1 demonstration the methodology generalises from, not "the chart". The bench-validated state recorded across SOS-03's prior amendments carries forward unchanged.

No frozen-enum value modified. No PCDN re-ratified. No port-spec impact.
