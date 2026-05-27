# SOS-11 — MCP-mediated chart editing

**Status:** 🟢 **ratified 2026-05-23**. All 6 PCDNs walked; resolutions recorded at the end of §15.

**Peers:** [SOS-12][sos-12] (recursive chart dispatch — ratified 2026-05-23 alongside this doc). The `extract_region_to_subchart` / `inline_subchart` tools are catalogued here; their contract algebra (declared events-in / events-out, per-layer bound composition, legibility-discipline integration) is owned by SOS-12. The two phases were co-designed and co-ratified.

[sos-12]: ./SOS-12-CONCEPTS.md

> 🛑 **NO CODE.** Tool surface, result contract, failure modes, history-as-commits convention, viewer contract, permission scoping, frozen tool-name enumerations, AuthorityRelationship for MCP wire. The MCP host plumbing (iState's tool-catalogue server) is not authored by this doc — SOS-11 specifies the tool surface; iState hosts it.

## 0. Authority policy

SOS-11 concretises [INV-SOS-C][inv-sos-c] from [`SOS-07-CONCEPTS.md`][sos-07] §6 — *"Human-and-agent chart edits flow through MCP tools that operate on the chart's semantic structure, never on raw SCXML text. The graphical viewer renders diffs in the same notation the developer authors."* INV-SOS-C is the load-bearing invariant; this doc translates it into a frozen tool surface, a result contract, a failure model, and a chart-history convention.

[inv-sos-c]: ./SOS-07-CONCEPTS.md#inv-sos-c--mcp-as-sole-modification-surface
[sos-07]: ./SOS-07-CONCEPTS.md

Per the parent CLAUDE.md "Spec-Before-Code Planning Discipline":

- **Normative** sections: §3 glossary, §4 source-of-truth map, §5 frozen tool-name enumerations, §6 result contract, §7 failure model, §8 chart-history convention, §9 viewer contract, §10 agent permission scoping, §11 reconciliation, §12 acceptance.
- **Informative** sections: §1 purpose, §2 problem statement, §14 non-goals, §15 change log.
- All keywords MUST, MUST NOT, SHALL, SHOULD, SHOULD NOT, MAY are interpreted per RFC 2119 / RFC 8174 when capitalised.

SOS-11 does NOT own MCP wire-format semantics ([SOS-07 §7][sos-07-matrix] declares MCP `adapt`); it does NOT own the graphical viewer (iState owns it); it does NOT own the chart's storage substrate (the chart's git repo is the substrate, owned by whichever project hosts the chart). SOS-11 owns the **tool surface contract** that connects all three.

[sos-07-matrix]: ./SOS-07-CONCEPTS.md#7-standards-integration-matrix

## 1. Purpose

Establish:

1. The **MCP tool surface** that makes the chart the sole modification surface as a process matter, not just as an architectural matter. Tools are algebraic over the chart's semantic structure (states, transitions, regions, datamodel entries, event vocabulary) — never syntactic over raw SCXML text.
2. The **result contract** — what every tool call returns, so that an agent's response to the developer is "here's the chart diff, here's the vector diff, here's the validation status, here's the chart-vocabulary summary".
3. The **failure model** — what happens when a tool call would violate an [INV-SOS-A through H][sos-07-inv] invariant. Validation runs BEFORE commit; failures return error + diagnosis in chart vocabulary (per [INV-SOS-H][inv-sos-h]); no partial application.
4. The **chart-history-as-git convention** — every accepted tool call produces one git commit on the chart's repo, with the tool name + chart diff + vector diff as the commit's message + patch. Generated code (Rust / C / VHDL / Verilog) is NOT tracked in the chart's repo (per [INV-SOS-C][inv-sos-c] + [INV-SOS-A][inv-sos-a]); it is a build output.
5. The **viewer contract** — what the iState-side graphical viewer MUST render so that the developer's review surface is legible at chart-level, not at SCXML-text level. SOS-11 does not author the viewer; SOS-11 specifies what the viewer must render.
6. The **agent permission scoping** — which tools an agent calls without explicit user approval, which tools require approval, which tools require a graphical-diff preview in addition to approval. The discipline is what keeps the agent useful without making it dangerous.

[sos-07-inv]: ./SOS-07-CONCEPTS.md#6-cross-phase-invariants--inv-sos-a-through-h
[inv-sos-a]: ./SOS-07-CONCEPTS.md#inv-sos-a--chart-as-source
[inv-sos-h]: ./SOS-07-CONCEPTS.md#inv-sos-h--vector-to-chart-traceability

Without SOS-11:

- Chart edits land as raw-SCXML-text diffs in pull requests; the same chart-level change appears as five textually-incompatible diffs across five reviewers, because text-level edits don't normalise. The chart-as-source story regresses at the review surface.
- Agents that modify charts have no shared vocabulary with the validation stack; an LLM proposes a transition addition by editing text, the lint catches the malformed SCXML, the agent's repair attempt regresses adjacent state IDs by accident. The class of failure CLAUDE.md's "spec-before-code" discipline exists to prevent.
- The graphical viewer (iState's authoring surface) and the wire-level edit channel (LLM text manipulation) drift apart. INV-SOS-C names the constraint; this phase is where it lands.

## 2. Problem statement

**Current state (as of 2026-05-23, immediately post-SOS-07 ratification):**

- [SOS-07][sos-07] is ratified. INV-SOS-A through H + AuthorityRelationship matrix are normative. INV-SOS-C names MCP as the sole modification surface but does not specify a tool surface.
- [`SOS-ROADMAP-07-PLUS.md`][roadmap] §4 SOS-11 informative scope sketch + EOQ-006-ROADMAP resolution ("both layers shipped") name primitives + higher-intent operations as the v1 deliverable but leave the per-tool inventory, the result contract, the failure model, and the chart-history convention unspecified.
- iState hosts MCP tools today (`mcp__softoboros__istate_*` per parent CLAUDE.md "MCP Integration" section). The existing tool surface is document-level (`istate_create_document`, `istate_update_document`, `istate_get_xml`); it operates on the chart's XML payload as a string, not on the chart's semantic structure. The SOS-11 tool surface is a strictly stronger contract.
- scjson round-trip (per [INV-SOS-D][inv-sos-d]) is the existing oracle that proves iState↔SCXML extraction is lossless. SOS-11 leans on scjson to validate post-edit chart shape before commit.
- Bounded-reachability analysis (per [INV-SOS-B][inv-sos-b]) produces vector sets per chart; SOS-11 inherits this and emits the *delta* vector set as part of every tool-call result.

[roadmap]: ./SOS-ROADMAP-07-PLUS.md
[inv-sos-d]: ./SOS-07-CONCEPTS.md#inv-sos-d--istate-authoring-scxml-canonical
[inv-sos-b]: ./SOS-07-CONCEPTS.md#inv-sos-b--vectors-as-deliverable-at-every-layer

**The pressure that motivates SOS-11:**

Three pressures compound:

1. **The chart-as-source claim only holds at the *modification* surface if edits go through chart-aware tools.** A chart that round-trips through scjson cleanly, validates against the lint, and produces bounded vectors — but is *edited* as raw SCXML text — still suffers the documentation-drift failure mode INV-SOS-A is meant to prevent. The drift moves to the editor's keystrokes instead of the prose-around-the-chart, but it is the same drift.
2. **Agents need a tool surface they cannot abuse.** LLMs editing XML by text produce malformed XML at a low but nonzero rate. LLMs invoking `add_state(parent="syscalls", id="task.create", entry_script="...")` produce structurally-valid edits or a clear error; the failure mode shifts from "syntactically broken" to "semantically rejected with a chart-vocabulary diagnostic". The latter is recoverable; the former is not.
3. **The graphical viewer needs a semantic-level diff to render.** Text diffs of SCXML are unreadable at the chart level — adding one transition can produce 30 lines of XML reordering. Tool-call-derived diffs are at the level the developer thinks at: *"transition T42 added; subchart `auth.connecting` gains state `retrying`; vector set grew by 4 traces"*. The viewer's job is to render that; the tool surface's job is to produce it.

**Why this is the right time:**

- SOS-07 ratification means INV-SOS-C is normative; SOS-11 is the phase where it lands operationally.
- iState's existing document-level MCP tools are a working substrate to extend; the SOS-11 tools land *alongside* the document-level tools and become the preferred surface for chart edits.
- scjson + lint + bounded-reachability are already in place per SOS-01 / SOS-02 / SOS-03 / SOS-06-A; SOS-11's validation pipeline is composition, not new construction.

## 3. Canonical glossary

Reserved SOS-11 vocabulary. Capitalised use in SOS-11+ docs MUST refer to the defined meaning. Cross-doc terms cite their owner per the parent CLAUDE.md "Definitions — reference vs. restatement" convention.

| Term | Definition |
|---|---|
| **MCP tool surface** | The set of named operations an MCP client (an agent, the iState UI, a CLI) can invoke to mutate the chart. Frozen at §5; primitives in §5.1, higher-intent operations in §5.2. As defined in [SOS-07 §7 row "MCP"][sos-07-matrix]; this doc concretises the SOS-side surface. |
| **Primitive operation** | A tool whose effect is a single algebraic step on the chart's semantic structure — one state added/removed, one transition added/removed, one region nested/unnested, one event added to the vocabulary, one datamodel entry added. Primitives compose; higher-intent operations decompose into primitive sequences. |
| **Higher-intent operation** | A tool whose effect is a named recurring chart-edit pattern (e.g. "add an event handler for state X" = add an event to the vocabulary + add a transition from X firing on the event). Decomposes into a primitive sequence at evaluation time; the agent picks either layer per request. Resolved as EOQ-006-ROADMAP. |
| **Tool-call result** | The structured value every MCP tool returns. Always carries the four-tuple `(scxml_diff, vector_delta, summary, validation)`; shape ratifies at §6. |
| **scxml_diff** | A unified-diff-style or structured-diff representation of the chart's SCXML payload before and after the tool call. Authoritative for the chart-history-as-git convention (§8). |
| **vector_delta** | The change to the bounded-reachability vector set induced by the tool call: vectors added, vectors removed, vectors whose trace changed. Shape resolved at PCDN-SOS-11-002. |
| **summary** | A natural-language description, in chart vocabulary (per [INV-SOS-H][inv-sos-h]), of what the tool call did at the level a developer thinks at: *"added state `retrying` to subchart `auth.connecting`; added transition from `connecting` to `retrying` on event `tcp.refused`."* Authoritative for the viewer's chart-level diff render. |
| **validation** | The four-axis pass/fail report on the post-edit chart: (a) scjson round-trip clean; (b) lint passes ([SOS-01][sos-01]); (c) bounded-reachability converges ([SOS-03][sos-03]); (d) every cited invariant ([INV-SOS-*][sos-07-inv] + per-chart invariants) holds. Failure mode in §7. |
| **chart's git repo** | The git repository hosting the chart's SCXML file (and only that, per §8). Distinct from the parent project's repo (which hosts code, build scripts, generated artifacts). SOS-11 mandates a 1:1 commit:tool-call ratio on this repo. |
| **graphical viewer** | The iState-side browser-based UI that renders the chart's before/after state at chart-level semantics. Owned by iState; SOS-11 specifies the contract the viewer satisfies (§9). |
| **agent permission level** | The three-rank classification (read-only / structure-preserving-edit / structure-changing-edit) per §10. Determines whether a tool call proceeds without approval, with text approval, or with text approval + graphical-diff preview. |

[sos-01]: ./SOS-01-CONCEPTS.md
[sos-03]: ./SOS-03-CONCEPTS.md

## 4. Source-of-truth map

| Concept | Authority |
|---|---|
| MCP wire format | Anthropic-led MCP spec (external; declared `adapt` at [SOS-07 §7][sos-07-matrix]) |
| iState document-level MCP tools (`istate_create_document`, `istate_get_xml`, etc.) | iState project (external) |
| scjson AST shape (post-edit validation pivot) | scjson project (external) |
| Frozen tool-name vocabulary (primitives + higher-intent) | **this doc** (§5) |
| Tool-call result tuple shape `(scxml_diff, vector_delta, summary, validation)` | **this doc** (§6) |
| Pre-commit validation pipeline (scjson round-trip + lint + bound + invariant check) | **this doc** (§7), composing [SOS-01][sos-01] + [SOS-03][sos-03] |
| Chart-history-as-git convention | **this doc** (§8) |
| Graphical-viewer rendering contract | **this doc** (§9), with the viewer itself owned by iState |
| Agent permission scoping | **this doc** (§10) |
| Cross-phase invariants INV-SOS-A through H | [SOS-07 §6][sos-07-inv] |

## 5. Frozen tool-name enumerations

SOS-11 freezes **two** enumerations: the primitive-operation tool-name set (§5.1) and the higher-intent operation tool-name set (§5.2). Both ship at v1 per EOQ-006-ROADMAP resolution.

### 5.1 Primitive operations — Specification Required

Algebraic operations on the chart's semantic structure. Each operation has one well-defined effect; failure to apply leaves the chart unchanged (§7).

| Tool name | Effect |
|---|---|
| `add_state` | Add a state to a named parent state (or to the chart root if parent is the document). Parameters: `parent`, `id`, optional `entry_script`, optional `initial`. |
| `remove_state` | Remove a state by id. Fails if any transition targets it (caller must remove transitions first). |
| `rename_state` | Rename a state by id; rewrites all transition targets that referenced the old id. Atomic. |
| `add_transition` | Add a transition. Parameters: `source` (state id), `target` (state id), optional `event` (must be in the chart's event vocabulary or added in the same call), optional `cond` (ECMAScript-subset expression), optional `executable_content`. |
| `remove_transition` | Remove a transition by `(source, target, event)` triple. Fails if the triple is ambiguous. |
| `nest_region` | Wrap a set of sibling states inside a new `<state>` or `<parallel>` parent. Parameters: `child_ids`, `new_parent_id`, `kind` ∈ {`compound`, `parallel`}. |
| `unnest_region` | Inverse of `nest_region`: replace a parent state with its children promoted to siblings. Fails if the parent has entry/exit scripts that would be lost. |
| `extract_region_to_subchart` | Lift a region into its own SCXML document with a declared contract (events-in, events-out, invariants). Replaces the region in the parent chart with a single state that dispatches to the subchart. Per [SOS-12][sos-12] formal model (ratified 2026-05-23); SOS-11 ships the tool, SOS-12 owns the contract algebra. |
| `inline_subchart` | Inverse of `extract_region_to_subchart`. Replaces a dispatching state with the subchart's body inlined. Fails if the subchart's declared invariants are not provable in the inlined context. |
| `add_event_to_vocabulary` | Add an external event name to the chart's frozen event vocabulary (per [SOS-01 §5][sos-01]). Fails if the name collides. |
| `remove_event_from_vocabulary` | Remove an event name. Fails if any transition references it. |
| `add_datamodel_entry` | Add a `<data>` element to the chart's `<datamodel>`. Parameters: `id`, `type`, optional `expr`. |
| `remove_datamodel_entry` | Remove a `<data>` element. Fails if any script references it. |
| `update_datamodel_entry` | Modify a `<data>` element's type or initial-value expression. Atomic; fails if the type change is incompatible with existing references. |
| `add_invariant` | Attach an invariant to a state or transition (in the per-chart invariant vocabulary feeding [INV-SOS-B][inv-sos-b] bound analysis). |
| `remove_invariant` | Detach an invariant. |

Registration policy for §5.1: **Specification Required**. Adding a new primitive requires a §15 amendment to this doc — primitives are the algebraic basis; expanding the basis is a phase-owner decision but not a cross-phase contract change.

[sos-01]: ./SOS-01-CONCEPTS.md

### 5.2 Higher-intent operations — Specification Required

Named recurring chart-edit patterns. Each decomposes into a deterministic sequence of §5.1 primitives at evaluation time. The agent picks layer per request: primitives for fine-grained edits, higher-intent for ergonomic common cases.

| Tool name | Decomposes into |
|---|---|
| `add_event_handler_for_state` | `add_event_to_vocabulary` (if new) + `add_transition(source=state, target=…, event=…, executable_content=…)`. |
| `extract_orthogonal_region` | `nest_region(kind=parallel)` + `add_state` for each declared region body. |
| `factor_dispatch` | `extract_region_to_subchart` + `add_event_to_vocabulary` for each declared event-out + insert a `<send>` in the parent for each declared event-in. The protocol-stack motivating example from [roadmap §4 SOS-12][roadmap]; co-designed with [SOS-12][sos-12] (ratified 2026-05-23, doc at `docs/concepts/SOS-12-CONCEPTS.md`). |
| `replace_transition_target` | `remove_transition` + `add_transition` with new target. Atomic. |
| `split_state` | `add_state` + `add_transition` (entry from original state) + (optionally) re-target a subset of incoming/outgoing transitions to the new state. Parameter: which transitions split. |
| `merge_states` | `rename_state` (deduplicate ids) + `remove_state` of the now-empty merged state. Fails if entry/exit scripts cannot be unified. |
| `add_timeout_to_state` | `add_event_to_vocabulary("timeout.<state>")` (if new) + `add_transition(source=state, target=…, event=timeout.<state>)` + `add_datamodel_entry` if a deadline field is required. |
| `wrap_in_critical_section` | Pattern from the kernel chart: `add_transition(source=outer, target=crit.entered)` + corresponding exit transition. |

Registration policy for §5.2: **Specification Required**. The higher-intent vocabulary is the layer where ergonomic patterns surface; it grows by phase-owner walkthrough as new common patterns become apparent.

## 6. Tool-call result contract

Every SOS-11 tool call MUST return a four-tuple. Shape:

```
ToolCallResult {
    scxml_diff:    <diff-of-chart's-SCXML-before-and-after>,
    vector_delta:  <delta-on-bounded-reachability-vector-set>,
    summary:       <chart-vocabulary natural-language string>,
    validation:    <four-axis pass/fail report>,
}
```

Per-field requirements:

- **`scxml_diff`** — A unified-diff-style or structured-diff representation. Authoritative for the §8 chart-history convention; the diff is the patch the corresponding git commit applies. Shape MAY be a unified diff (`---`/`+++` text), a structured JSON diff (the scjson AST before/after), or both; PCDN-SOS-11-006 resolves the canonical form.

- **`vector_delta`** — The change to the bounded-reachability vector set. PCDN-SOS-11-002 resolves the exact representation: full vectors (verbose, exhaustive) versus summary (e.g. "+4 vectors, -2 vectors, 1 trace changed"). Either choice MUST preserve [INV-SOS-H][inv-sos-h] traceability — each vector delta entry names the chart state/transition/invariant that produced it.

- **`summary`** — A short natural-language description in chart vocabulary. Per [INV-SOS-H][inv-sos-h]: *"added state `retrying` to subchart `auth.connecting`; bound grew by 4 traces"* not *"inserted XML element at line 42"*. The viewer (§9) renders this verbatim as the chart-level diff title.

- **`validation`** — Four-axis pass/fail:
  - `(a) scjson_round_trip`: post-edit chart round-trips through scjson without loss.
  - `(b) lint`: post-edit chart passes [SOS-01][sos-01] lint.
  - `(c) bound_converges`: bounded-reachability analysis terminates within the declared bound.
  - `(d) invariants_hold`: every cited invariant (INV-SOS-A through H + per-chart) holds against the post-edit chart.

Validation runs BEFORE the chart is committed (§7). All four axes MUST pass for the tool call to succeed; any axis failure rolls back the edit and returns an error result (§7).

PCDN-SOS-11-003 resolves whether the lint pass (axis (b)) is mandatory before commit or optional via an explicit `--allow-lint-failure` flag. Default recommendation: mandatory; charts with lint-failures are not commit-able.

## 7. Failure model

A tool call that violates an invariant or fails any validation axis (§6) returns an **error result** of shape:

```
ToolCallError {
    code:          <enum value from FailureCode>,
    diagnosis:     <chart-vocabulary natural-language string>,
    failed_axis:   <which validation axis failed, if applicable>,
    chart_unchanged: true,  // always; failures are atomic
}
```

`FailureCode` is a **Standards Action**-registered frozen enum:

| Code | Meaning |
|---|---|
| `InvariantViolation` | A cited invariant (INV-SOS-*) would not hold after the edit. `diagnosis` names the invariant. |
| `LintFailure` | Post-edit chart fails [SOS-01][sos-01] lint. `diagnosis` names the lint rule. |
| `BoundExceeded` | Bounded-reachability analysis exceeded the chart's declared bound. `diagnosis` names which state/region drove the explosion. |
| `RoundTripFailure` | scjson round-trip lost information. `diagnosis` names the field/attribute that did not round-trip. |
| `ArgumentInvalid` | The tool's input arguments are malformed or reference non-existent chart elements. `diagnosis` names which argument. |
| `AmbiguousReference` | A primitive's identifier resolved to multiple chart elements (e.g. `remove_transition` with a triple that matches two transitions). `diagnosis` enumerates the candidates. |
| `Conflict` | Concurrent-edit conflict: the chart's HEAD moved between read and write. Resolution policy at PCDN-SOS-11-005. |
| `PermissionDenied` | Caller lacks the agent permission level required by §10 for this tool. |

Failures are **atomic**: the chart's state is rolled back to pre-call. No partial application — a higher-intent operation that decomposes into 4 primitives and fails on primitive 3 rolls back primitives 1 and 2. The chart's git HEAD does NOT advance on failure (§8).

Diagnoses MUST render in chart vocabulary per [INV-SOS-H][inv-sos-h]. *"Transition T42 in subchart `auth.connecting` would violate INV-S7 (ready-queue monotonicity)"* — not *"line 142 column 23: assertion failed"*.

## 8. Chart-history-as-git convention

Every accepted SOS-11 tool call produces **exactly one** git commit on the chart's git repo. The commit's structure is:

- **Commit subject (line 1):** the tool name + a short summary in chart vocabulary. Example: `add_state: retrying in subchart auth.connecting`.
- **Commit body:** the §6 `summary` field verbatim, followed by a `vector_delta:` block summarising the bound impact.
- **Commit patch:** the §6 `scxml_diff` field as the patch the commit applies.
- **Commit author:** resolved at PCDN-SOS-11-004 (agent identity vs human-via-agent identity).

The chart's git repo tracks **only** the SCXML file(s) and any chart-side metadata SOS-11 explicitly mandates (e.g. a `chart.toml` declaring the chart's bound, invariants, dispatched subcharts). Generated code (Rust, C, VHDL, Verilog) is NOT tracked in the chart's repo — it is a build output of the per-port codegen tooling (per [INV-SOS-A][inv-sos-a] + [INV-SOS-C][inv-sos-c]). A chart's repo `ls` produces a small, legible set of artifacts; the parent project's repo holds the generated downstream.

Rationale: the chart's history IS the chart's spec evolution. Reading `git log` on the chart's repo is reading the chart's design log in tool-call-named granularity. A reviewer browsing six months of commits sees *"add_state: retrying / extract_region_to_subchart: auth.connecting → auth.scxml / add_event_to_vocabulary: tcp.refused"* not *"updated rtos_kernel.scxml (43 lines changed)"*.

PCDN-SOS-11-005 resolves the concurrent-edit policy: serialize (first-writer-wins, second writer must re-fetch and reapply) versus merge (3-way merge at the SCXML AST level). Default recommendation: serialize at v1; merging SCXML ASTs is a semantically-rich operation deferred to a future amendment.

## 9. Graphical viewer rendering contract

SOS-11 does NOT author the graphical viewer; iState owns it ([INV-SOS-D][inv-sos-d]). SOS-11 specifies what the viewer MUST render to satisfy the developer's review surface:

A conforming viewer MUST render, for every committed tool call:

- **(a) Before/after chart diff at semantic level.** States added/removed/renamed; transitions added/removed/re-targeted; regions nested/unnested; events added/removed from the vocabulary; datamodel entries added/removed/updated. NOT a raw text diff of the SCXML payload.
- **(b) Vector delta summary in chart vocabulary.** Per the §6 `vector_delta` field; rendered as *"+4 traces (3 enter `retrying`, 1 timeout from `connecting`); -2 traces (no longer reach `connecting.failed`)"*.
- **(c) Validation status.** All four axes (§6 (a)-(d)) with pass/fail icons.
- **(d) Tool-call name + arguments.** The exact primitive or higher-intent call that produced the change, so the reviewer can reproduce or revert it.
- **(e) Diagnostic when failing.** When the viewer is loaded against a failed tool call (e.g. an agent's attempted edit that was rejected), render the §7 diagnosis in the same chart-vocabulary form.

A conforming viewer MAY ALSO render:

- The raw SCXML text diff (for debugging; opt-in, not the default view).
- The full pre/post vector set as a downloadable artifact.
- A "what-if" sandbox that previews additional tool calls without committing.

The viewer is the **developer's chart-history-and-review surface**. The text-diff view is a legacy debugging surface; the chart-level view is the default. This is the operational realisation of [INV-SOS-C][inv-sos-c]'s "the graphical viewer renders diffs in the same notation the developer authors."

## 10. Agent permission scoping

Three-rank classification. Each tool's rank is fixed by this section.

### 10.1 Read-only — always allowed

These tools never modify the chart. An agent calls them without explicit user approval:

- `query_state(id)` — returns the state's structure.
- `query_transitions(source?, target?, event?)` — returns matching transitions.
- `query_vectors(filter?)` — returns the chart's current bounded-reachability vector set or a filtered subset.
- `query_invariants(state?)` — returns the invariants attached to a state/transition.
- `query_event_vocabulary()` — returns the chart's frozen event names.

### 10.2 Structure-preserving edits — text approval required

These edit chart content but do NOT change the chart's reachability structure:

- `add_event_to_vocabulary` (new name; reachability unchanged until a transition references it).
- `add_datamodel_entry`, `update_datamodel_entry` (when type-compatible).
- `add_invariant` (additive only — narrows the chart's behaviour space, does not expand it).
- `rename_state` (alpha-equivalent transformation).

Agent MUST present the proposed call to the user; user approves with a text-level review of the §6 `summary`. No graphical-diff preview required.

### 10.3 Structure-changing edits — text approval + graphical-diff preview required

These change the chart's reachability structure:

- `add_state`, `remove_state`.
- `add_transition`, `remove_transition`, `replace_transition_target`.
- `nest_region`, `unnest_region`.
- `extract_region_to_subchart`, `inline_subchart`.
- `remove_event_from_vocabulary`, `remove_datamodel_entry`, `remove_invariant`.
- `update_datamodel_entry` when type-incompatible.
- All §5.2 higher-intent operations (each decomposes into structure-changing primitives).

Agent MUST present (i) the proposed call, (ii) the §6 `summary`, (iii) a viewer-rendered graphical-diff preview (per §9 (a)-(d)) of what the chart looks like before vs after. User approves only after reviewing the graphical preview.

The discipline is the bright line between *agent suggests, user reviews* (the supported workflow) and *agent edits, user discovers later* (the failure mode this phase exists to prevent).

## 11. Reconciliation decisions vs adjacent repo primitives

### vs. iState document-level MCP tools (`istate_create_document`, `istate_get_xml`, `istate_update_document`)

SOS-11 tools land **alongside** iState's document-level tools, not as replacements. iState's existing tools operate at document granularity (whole-chart upload/download); SOS-11 tools operate at semantic-structure granularity (one state, one transition, one region). The two layers coexist:

- iState document tools: import/export, project management, whole-chart workflows.
- SOS-11 tools: in-place chart edits with validation + history + diff rendering.

A SOS-11 tool call internally MAY use iState's `istate_get_xml` to fetch the current chart, apply the semantic edit, and `istate_update_document` to persist (with validation in between). The relationship is `compose` — SOS-11 composes iState's substrate tools to provide a higher-level surface.

### vs. [SOS-01][sos-01] lint

Lint is the pre-commit validation pass (axis (b) of §6). SOS-11 does NOT extend the lint rules; SOS-11 invokes lint as a validator. New lint rules (e.g. legibility-threshold enforcement per SOS-12) land in SOS-01 §15 amendments and are picked up here automatically.

### vs. [SOS-03][sos-03] conformance vectors

SOS-03 owns the conformance vector framework. SOS-11's §6 `vector_delta` field is computed by running the SOS-03 bounded-reachability pipeline against the post-edit chart and diffing the result against the pre-edit set. SOS-11 does NOT author vectors; SOS-11 reports the delta SOS-03 produces.

### vs. [SOS-12][sos-12] recursive dispatch

`extract_region_to_subchart` and `inline_subchart` are the operational handles for SOS-12's chart-as-subchart model. SOS-11 ships the tools; SOS-12 owns the contract algebra (declared events-in, events-out, declared invariants, per-layer bound composition). The two phases were co-designed and co-ratified (both 🟢 2026-05-23): SOS-11 cannot land `extract_region_to_subchart` without a contract surface to extract into; SOS-12 cannot land its contract algebra without a tool to invoke it through. Implementation of the two subchart handlers themselves is gated on SOS-12 implementation work (see §15 2026-05-27 entry).

### vs. [SOS-07 §7][sos-07-matrix] MCP `adapt` row

SOS-11 declares the SOS-side **tool surface**; MCP wire-format semantics remain `adapt` per SOS-07. The relationship is: MCP wire is upstream verbatim; the SOS-11 tools-as-names + arguments-as-schemas live in the local namespace; the MCP host (iState's tool-catalogue server) translates between the wire and the local namespace. No SOS-side modification of MCP wire format.

### vs. parent CLAUDE.md "Spec-Before-Code Planning Discipline"

SOS-11 IS spec-before-code applied to chart edits: every chart change rides a tool call that has a name, a validation gate, and a commit. The relationship is `compose` — SOS-11 composes the parent discipline at one level lower (tool-call granularity instead of phase-document granularity).

## 12. Acceptance checklist

A conforming SOS-11 ratification satisfies all of:

- (a) Tool-name primitives in §5.1 frozen (Specification Required registration).
- (b) Tool-name higher-intent operations in §5.2 frozen (Specification Required registration), each with a declared decomposition into §5.1 primitives.
- (c) Tool-call result tuple in §6 specified; all four axes (`scxml_diff`, `vector_delta`, `summary`, `validation`) defined.
- (d) Failure model in §7 specified; `FailureCode` enum frozen as **Standards Action**; failure-atomicity guarantee documented.
- (e) Chart-history-as-git convention in §8 specified; 1:1 commit-to-tool-call ratio mandated; generated-code exclusion documented (per [INV-SOS-A][inv-sos-a] + [INV-SOS-C][inv-sos-c]).
- (f) Graphical-viewer contract in §9 specified; MUST-render set (a)-(e) enumerated; MAY-render set documented as opt-in.
- (g) Agent-permission-scoping in §10 specified; three ranks (read-only / structure-preserving / structure-changing) frozen; each §5.1 + §5.2 tool assigned a rank.
- (h) Every cited [INV-SOS-A through H][sos-07-inv] invariant relates to SOS-11 either by `derive` (the tool surface implements the invariant operationally) or `compose` (the tool surface composes the invariant with another phase's surface) per [INV-SOS-E][inv-sos-e]; relationships enumerated in §13 below.
- (i) AuthorityRelationship row(s) added for MCP wire (already declared `adapt` in [SOS-07 §7][sos-07-matrix]); SOS-11-side relationship documented in §11 above.
- (j) PCDN-SOS-11-001 through PCDN-SOS-11-006 (§15) each ratified with a chosen value before status flips to 🟢.

[inv-sos-e]: ./SOS-07-CONCEPTS.md#inv-sos-e--explicit-authorityrelationship

## 13. Cited invariants

How each [INV-SOS-*][sos-07-inv] invariant relates to SOS-11:

| Invariant | Relationship |
|---|---|
| INV-SOS-A (Chart-as-source) | `derive`. The tool surface IS the modification path; raw-SCXML-text edits are prohibited at the process layer that SOS-11 instantiates. |
| INV-SOS-B (Vectors-as-deliverable) | `compose`. SOS-11's `vector_delta` field is the SOS-03 vector set's delta; SOS-11 reports the delta SOS-03 produces. |
| INV-SOS-C (MCP as sole modification surface) | `derive`. This phase IS the operational realisation of INV-SOS-C. The tool surface in §5 + the failure-rollback semantics in §7 + the chart-history convention in §8 are the three legs of INV-SOS-C made concrete. |
| INV-SOS-D (iState authoring, SCXML canonical) | `compose`. SOS-11 tools edit through iState; SCXML on disk in the chart's git repo (§8) is canonical. |
| INV-SOS-E (Explicit AuthorityRelationship) | `mirror`. SOS-11's §11 reconciliation table enumerates relationships per the enum. |
| INV-SOS-F (Bound composition) | `compose`. `extract_region_to_subchart` is the operational handle; the algebra lives in SOS-12. |
| INV-SOS-G (Verified-codegen position) | `compose`. SOS-11 does not affect codegen; tool-call commits trigger downstream regeneration in the parent project's repo. |
| INV-SOS-H (Vector-to-chart traceability) | `derive`. Every §6 `summary` and §7 `diagnosis` MUST render in chart vocabulary; this is the operational realisation of INV-SOS-H at the modification surface. |

## 14. Non-goals

This phase does NOT:

- Author the MCP host plumbing. iState hosts the SOS-11 tools as part of its tool catalogue; the SDK / wire-translation / authentication / rate-limiting layers are iState's concern.
- Author the graphical viewer. §9 specifies the contract; iState authors the implementation.
- Define the bounded-reachability algorithm. [SOS-03][sos-03] owns it; SOS-11 invokes it.
- Define the SOS-01 lint rules. [SOS-01][sos-01] owns them; SOS-11 invokes lint as a validator.
- Define the chart's per-chart invariant vocabulary. Per-chart invariants are authored at chart-creation time; SOS-11 adds/removes them via `add_invariant` / `remove_invariant` primitives but does NOT define the invariant grammar.
- Modify any code in `tools/sos-codegen/`, `ports/m7-rust/`, `ports/m7-c/`, `sim/sos-sim/`, or `conformance/vectors/`. SOS-11 is a documentation phase; implementation lands as a follow-up commit per spec-before-code discipline.
- Define a v2 multi-host / multi-author concurrent edit protocol. Per PCDN-SOS-11-005 default recommendation, v1 is serialize-only.

## 15. Change log

### 2026-05-23 — Drafted (Ira)

Initial draft authored against [SOS-07][sos-07] ratification + [`SOS-ROADMAP-07-PLUS.md`][roadmap] §4 SOS-11 informative scope sketch + EOQ-006-ROADMAP "both layers shipped" resolution.

**PCDNs raised (§-binding):**

- **PCDN-SOS-11-001 — Higher-intent tool naming convention.** Two recurring shapes appear in §5.2: verb-object (`add_event_handler_for_state`, `extract_orthogonal_region`, `wrap_in_critical_section`) versus object-verb (`state_split`, `state_merge`, `transition_retarget`). Current draft uses verb-object throughout for English readability. Resolution: ratify verb-object as the canonical convention (current draft) or pick a hybrid. Defaults to **verb-object** unless user objects.

- **PCDN-SOS-11-002 — `vector_delta` representation.** §6 leaves the exact shape unresolved. Options: (a) full pre+post vector sets (verbose, exhaustive, large for big charts), (b) summary-only ("+4 vectors, -2 vectors, 1 trace changed", with named state/transition citations per INV-SOS-H), (c) both (full set as downloadable artifact, summary in the result tuple). Default recommendation: **(c)** — summary in the result, full set on demand. Open to user choice.

- **PCDN-SOS-11-003 — Lint pass mandatory before commit.** §6 axis (b). Options: (a) mandatory (no `--allow-lint-failure` flag; lint-failing charts not commit-able), (b) optional via explicit flag (advanced workflows where temporary lint-failures are acceptable mid-refactor). Default recommendation: **(a) mandatory**.

- **PCDN-SOS-11-004 — Commit author attribution.** §8 leaves this unresolved. Options: (a) agent identity ("`Co-Authored-By: claude <agent@…>`"), (b) human-via-agent ("user authored via Claude Code; commit author = user, co-author = agent"), (c) configurable per agent invocation. Default recommendation: **(b)** — preserves human authorship for accountability; agent attribution via `Co-Authored-By`.

- **PCDN-SOS-11-005 — Concurrent-edit policy.** §8 + §7 `Conflict` failure code. Options: (a) serialize (first-writer-wins; second writer must re-fetch and reapply), (b) merge (3-way merge at the scjson AST level). Default recommendation: **(a) serialize at v1**; merge deferred to a future amendment.

- **PCDN-SOS-11-006 — Canonical `scxml_diff` representation.** §6. Options: (a) unified-diff text (`---`/`+++` of the SCXML payload), (b) structured AST diff (scjson-before / scjson-after JSON), (c) both. Default recommendation: **(c) both** — unified diff for git patches (§8), structured AST diff for the viewer's chart-level render (§9).

Status: 🟡 **drafted, awaiting PCDN walkthrough.** Ratifies to 🟢 once each PCDN above has a chosen value and the corresponding section is updated. SOS-12 (recursive chart dispatch) is partially co-dependent — `extract_region_to_subchart` / `inline_subchart` tool semantics need SOS-12's contract algebra before they are operationally complete; SOS-11 may ratify with these two tools marked as "shipped with SOS-12 contract semantics" forward-cited.

### 2026-05-23 — Ratified (Ira)

All 6 PCDNs walked and resolved:

| PCDN | Resolution |
|---|---|
| **001 — Higher-intent tool naming** | ✅ **verb-object** (`add_event_handler_for_state`, `extract_orthogonal_region`). Reads as imperative actions; matches the existing primitive vocabulary. |
| **002 — Vector-delta representation in result** | ✅ **Both**: summary embedded in tool-call result; full delta retrievable via a separate `get_vector_delta(call_id)` tool call. Default summary keeps responses small; full delta available for review without bloating the common path. |
| **003 — Lint pass before commit** | ✅ **Mandatory** — failed lint blocks the commit; user resolves before re-trying. Chart stays always-clean; cost is iteration speed during intentional broken-state drafting. |
| **004 — Commit author attribution** | ✅ **Configurable, default `human-via-agent`**. Commit reads "Ira (via agent X)". Defaults preserve human-visible authorship in chart history; agent-only mode is opt-in for autonomous batches. |
| **005 — Concurrent edits policy** | ✅ **Serialize at v1** — single-writer model; concurrent edits sequence through the MCP server. Multi-writer (CRDT-like) is a future-phase decision; the simple semantics carry v1 single-developer + small-team workflows. |
| **006 — `scxml_diff` representation in result** | ✅ **Both**: structured AST as canonical (machine-readable); unified-diff rendered from it on demand for human review. One canonical form underneath; two presentation surfaces. |

Status: 🟢 **ratified**. SOS-11 implementation work (MCP tool catalogue at `tools/sos-codegen/mcp-tools/` or a sibling location; the algebraic-tool-surface implementation; graphical viewer contract handoff to iState) unblocked.

### 2026-05-27 — Wave-1 MCP tool surface implementation landed

First wave of SOS-11 implementation commits landed under `tools/sos-codegen/sos11_mcp/`. Six commits stamp the §5 / §6 / §7 / §8 / §10 contract surfaces; subchart handlers + the full validation composer remain open (dependency edges to SOS-12 noted below).

**Landed** (🟢):

| Commit | Subject | Spec deliverable | Module |
|---|---|---|---|
| `ff7fc80` | SOS11-CATALOG: implement MCP tool catalog | §5.1 + §5.2 tool catalogue (frozen primitive + higher-intent names, permission ranks from §10) | `tools/sos-codegen/sos11_mcp/tool_catalog.py` |
| `0b7d474` | SOS11-CONTRACTS: implement MCP result contracts | §6 four-tuple result shape + §7 `FailureCode` enum types | `tools/sos-codegen/sos11_mcp/contracts.py` |
| `1df4961` | SOS11-QUERY: implement read-only chart queries | §10.1 read-only tool handlers (`query_state`, `query_transitions`, `query_vectors`, `query_invariants`, `query_event_vocabulary`) | `tools/sos-codegen/sos11_mcp/chart_query.py` |
| `e5682d4` | SOS11-PERMISSIONS: implement MCP approval gates | §10 three-rank classifier + approval-required predicates | `tools/sos-codegen/sos11_mcp/permissions.py` |
| `9f171db` | SOS11-DIFF: implement SCXML diff helpers | §6 `scxml_diff` field — structured AST diff + unified-diff renderer (per PCDN-SOS-11-006 "both") | `tools/sos-codegen/sos11_mcp/diffs.py` |
| `8d1b182` | SOS11-HISTORY: implement chart commit metadata helpers | §8 chart-history-as-git convention — commit-subject / body / author shape (per PCDN-SOS-11-004 default `human-via-agent`) | `tools/sos-codegen/sos11_mcp/history.py` |

**Still open** (🔴 — not landed by these six commits):

- **`extract_region_to_subchart` + `inline_subchart` handler implementations.** Registered in `tool_catalog.py` (lines 43-44, 89) but no executable handlers exist. Gated on [SOS-12][sos-12] implementation (its contract-algebra parser, then the per-layer bound composition machinery). SOS-12 is ratified (🟢 2026-05-23) but its implementation has not yet landed; these two tools cannot be made functional without it.
- **`validation.py` composer.** §6 axes (a)-(d) are typed in `contracts.py` as `ValidationReport` but no module wires scjson round-trip + SOS-01 lint + SOS-03 bound + invariant-check into a single pre-commit pipeline. Composer must enforce the failure-atomicity guarantee from §7 (chart rolls back on any axis failure).
- **`vector_delta` computation.** §6 `vector_delta` field is typed but not populated; the computation wires to SOS-03's vector module. Per PCDN-SOS-11-002 resolution, the result-tuple carries a summary and a separate `get_vector_delta(call_id)` tool returns the full delta. Neither path is implemented yet.

**Cross-cite to SOS-12.** SOS-12 (🟢 ratified 2026-05-23, doc at `docs/concepts/SOS-12-CONCEPTS.md`) is the peer phase whose implementation gates the two subchart-handler tools above. The implementation dependency runs SOS-11 → SOS-12 for those two tools only; the rest of the §5.1 / §5.2 surface is independent of SOS-12 and the wave-1 commits cover the §10.1 read-only band end-to-end.

**Invariants touched.** The six wave-1 commits exercise INV-SOS-C (`derive` — the tool surface is the modification path; `chart_query.py` + `permissions.py` are the read-side; `tool_catalog.py` is the registry binding all writes through named tools) and INV-SOS-H (`derive` — `diffs.py` + `history.py` carry chart-vocabulary summaries into commit subjects / bodies). No invariant relationships changed; no §13 row required restating.
