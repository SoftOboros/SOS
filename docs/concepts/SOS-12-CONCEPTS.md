# SOS-12 — Recursive chart dispatch (charts-dispatching-charts)

**Status:** 🟢 **ratified 2026-05-23**. All 6 PCDNs walked; resolutions recorded at the end of §15.

**Depends on:** [SOS-07][sos-07] (cross-phase invariants, especially [INV-SOS-F][inv-sos-f]); [SOS-11][sos-11] (the `extract_region_to_subchart` / `inline_subchart` tool surface).

**Blocks:** none directly; unblocks the legibility-as-discipline lint rule on [SOS-01][sos-01] and the cocotb / SVA per-sub-chart vector emission shape on [SOS-08-D][roadmap-08d].

> 🛑 **NO CODE.** Formal model, contract surface, bound-composition algebra, CSP citation, per-sub-chart vector emission contract, legibility-discipline integration, frozen enums, AuthorityRelationship row. Implementation lands as a follow-up commit per the spec-before-code discipline.

## 0. Authority policy

SOS-12 concretises [INV-SOS-F][inv-sos-f] from [`SOS-07-CONCEPTS.md`][sos-07] §6 — *"Joint reachability across hierarchically-composed charts MUST be computed as per-layer × independence axes, NOT as the Cartesian product. Orthogonal regions (SCXML `<parallel>`) are the natural independence axes; sequential composition uses contract-matching at the dispatch boundary."* INV-SOS-F is the load-bearing invariant; this doc translates it into a formal model of chart-as-sub-chart, a contract surface for the dispatch boundary, a bound-composition algebra with CSP lineage cited, and a legibility-discipline integration with the [SOS-11][sos-11] tool surface.

[sos-07]: ./SOS-07-CONCEPTS.md
[sos-11]: ./SOS-11-CONCEPTS.md
[sos-01]: ./SOS-01-CONCEPTS.md
[sos-03]: ./SOS-03-CONCEPTS.md
[roadmap]: ./SOS-ROADMAP-07-PLUS.md
[roadmap-08d]: ./SOS-ROADMAP-07-PLUS.md#sos-08--hdl-backend-synthesizable-vhdl--verilog
[inv-sos-a]: ./SOS-07-CONCEPTS.md#inv-sos-a--chart-as-source
[inv-sos-b]: ./SOS-07-CONCEPTS.md#inv-sos-b--vectors-as-deliverable-at-every-layer
[inv-sos-c]: ./SOS-07-CONCEPTS.md#inv-sos-c--mcp-as-sole-modification-surface
[inv-sos-d]: ./SOS-07-CONCEPTS.md#inv-sos-d--istate-authoring-scxml-canonical
[inv-sos-e]: ./SOS-07-CONCEPTS.md#inv-sos-e--explicit-authorityrelationship
[inv-sos-f]: ./SOS-07-CONCEPTS.md#inv-sos-f--bound-composition
[inv-sos-g]: ./SOS-07-CONCEPTS.md#inv-sos-g--verified-codegen-position
[inv-sos-h]: ./SOS-07-CONCEPTS.md#inv-sos-h--vector-to-chart-traceability
[sos-07-matrix]: ./SOS-07-CONCEPTS.md#7-standards-integration-matrix

Per the parent CLAUDE.md "Spec-Before-Code Planning Discipline":

- **Normative** sections: §3 glossary, §4 source-of-truth map, §5 frozen decisions (contract declaration shape, dispatch semantics), §6 bound-composition algebra, §7 per-sub-chart vector emission, §8 protocol-stack worked example, §9 SOS-11 integration (legibility threshold), §10 frozen enumerations, §11 standards integration (CSP row), §12 reconciliation, §13 acceptance.
- **Informative** sections: §1 purpose, §2 problem statement, §14 non-goals, §15 change log.
- All keywords MUST, MUST NOT, SHALL, SHOULD, SHOULD NOT, MAY are interpreted per RFC 2119 / RFC 8174 when capitalised.

SOS-12 does NOT own the MCP tool surface (`extract_region_to_subchart` / `inline_subchart` live in [SOS-11 §5.1][sos-11-tools]); SOS-12 does NOT own the bounded-reachability algorithm ([SOS-03][sos-03] owns it; SOS-12 extends the framework for per-sub-chart emission); SOS-12 does NOT own the per-chart invariant grammar (chart authors do). SOS-12 owns the **formal model + contract surface + composition algebra** that makes the SOS-11 tools semantically complete.

[sos-11-tools]: ./SOS-11-CONCEPTS.md#51-primitive-operations--specification-required

## 1. Purpose

Establish:

1. The **formal model** of chart-as-sub-chart — a chart whose states are sub-charts, whose transitions reference sub-chart contracts, and whose bounded reachability composes per-layer. The parent chart treats each sub-chart as an atomic transition with the declared contract; the sub-chart treats its environment as the declared contract matched from above. SCXML's existing `<state>` (with a sub-chart reference) is the surface; SOS-12 ratifies the dispatch-into / contract-match semantic.

2. The **per-sub-chart contract declaration** — events-in, events-out, declared invariants, datamodel boundary. The contract is what the parent verifies against, and the contract is what the sub-chart's environment is assumed to satisfy. Contract-mismatch is a compile-time, lint, or runtime failure depending on PCDN-SOS-12-006 resolution.

3. The **bound-composition algebra** — the concrete algorithm that turns INV-SOS-F's "per-layer × independence axes, NOT Cartesian" claim into an algorithm vector emitters and reachability checkers run. CSP (Communicating Sequential Processes; Hoare 1978 + ISO/IEC 13568) is named as the lineage per [EOQ-007-ROADMAP][roadmap-eoq7].

4. The **per-sub-chart vector emission contract** — every sub-chart ships its own bounded-reachability vector set, sized to its own reachable states. Per [INV-SOS-B][inv-sos-b], the parent chart's vectors test the contract at the dispatch boundary (constant-size); the sub-chart's vectors test internal behavior (sub-chart-sized); neither replays the other.

5. The **legibility-as-discipline integration with [SOS-11][sos-11]** — when a chart hits a project-configured legibility threshold (recommend: 15 peer states at one level per PCDN-SOS-12-003), [SOS-11 §5.1][sos-11-tools] `add_state` fails the lint pass; the only available structural-add operation becomes `extract_region_to_subchart`. The discipline becomes a property the tooling enforces, per [INV-SOS-C][inv-sos-c].

[roadmap-eoq7]: ./SOS-ROADMAP-07-PLUS.md#8-open-questions-eoq-nnn-roadmap

Without SOS-12:

- The methodology stalls at the toy-chart scale. Real systems have 200+ states; a single flat chart at 200 states is illegible at every review. The methodology's legibility-as-source claim regresses at scale.
- [INV-SOS-F][inv-sos-f] is normative but operationally vague — phase docs cite "per-layer × independence axes" but no algorithm exists to compute it. Vector emitters fall back to the Cartesian product and the methodology silently regresses to model-checking's classic blowup.
- [SOS-11][sos-11]'s `extract_region_to_subchart` and `inline_subchart` are tool names without contract semantics. The MCP tool surface ships at the syntactic layer; the semantic layer (what does the extracted region's contract look like? when is `inline_subchart` admissible?) is open.
- The protocol-stack motivating example (HTTP parser; see §8) has no canonical realization in the methodology. The "switch-on-tag with named handlers" pattern stays in developer heads instead of becoming an artifact.

## 2. Problem statement

**Current state (as of 2026-05-23, immediately post-SOS-11 draft):**

- [SOS-07][sos-07] is ratified. INV-SOS-A through H are normative. INV-SOS-F names per-layer × independence-axes bound composition but defers the algebraic detail explicitly to this phase doc.
- [SOS-11][sos-11] is drafted (🟡). The `extract_region_to_subchart` and `inline_subchart` primitives in [§5.1][sos-11-tools] reference SOS-12 forward-cited; their tool-surface shape lands at SOS-11 but their contract semantics land here.
- [SOS-03][sos-03] is ratified. The vector framework operates on a single chart at v1; per-sub-chart emission is an extension this doc specifies but SOS-03 already accommodates via INV-S-CONF-9 (schema versioning) + INV-S-CONF-11 (independence from chart SHA, generalising to "independence from parent-chart SHA when sub-chart SHA differs").
- [EOQ-007-ROADMAP][roadmap-eoq7] resolved with explicit CSP citation: "INV-SOS-F's per-layer × independence axis bound composition is named relative to CSP. CSP is the lineage Handel-C / occam-π came from; the citation makes formal-methods readers' mapping straightforward + acknowledges the prior art SOS extends rather than rediscovers. SOS-specific algebra (with bounded-vector emission as a first-class operation) is named in SOS-12."

**The pressure that motivates SOS-12:**

Three pressures compound:

1. **Every successful formalism wins by adopting an existing decomposition pattern.** Statecharts have had Harel's hierarchy + orthogonal regions since 1987; what they lacked at the spec-before-code level was bounded-vector emission that composes per-layer. SOS-12 is the phase where the methodology adopts that pattern as a first-class contract rather than an SCXML structural happenstance.

2. **The protocol-stack motivating example forces the contract surface to materialise.** A 200-state flat chart for HTTP is illegible; a 12-state dispatch chart factoring into per-method sub-charts (GET/POST/PUT/DELETE) — each of which factors into per-handler charts — is legible at every level. The protocol structure already exists in production code as switch-on-tag with named handlers; SOS-12 lifts it from "in the developer's head" to "the artifact."

3. **Without per-layer vector emission, the chart's verification scales as the Cartesian product.** A 12-state dispatch chart × 8-state per-method × 5-state per-handler = 480 effective states if naïvely flattened; the joint reachability is much larger. The methodology's verification cost regresses to model-checking's classic blowup. Per-layer × independence-axes composition (INV-SOS-F) is the structural answer; SOS-12 makes it the operational answer.

**Why this is the right time:**

- [SOS-07][sos-07] ratification means INV-SOS-F is normative; SOS-12 is the phase where the algebra lands.
- [SOS-11][sos-11] is co-drafting today; the two phases are co-designed. SOS-11 ships the tools; SOS-12 ratifies their contract algebra. Neither phase ratifies without the other.
- [SOS-03][sos-03]'s vector framework is stable; the per-sub-chart extension is composition, not new construction.

## 3. Canonical glossary

Reserved SOS-12 vocabulary. Capitalised use in SOS-12+ docs MUST refer to the defined meaning. Cross-doc terms cite their owner per the parent CLAUDE.md "Definitions — reference vs. restatement" convention.

| Term | Definition |
|---|---|
| **Sub-chart** | A chart that is dispatched-into by another chart (the *parent*). The sub-chart is itself a fully-formed SCXML document with its own root state, its own datamodel, its own event vocabulary, its own per-chart invariants, and (per [INV-SOS-B][inv-sos-b]) its own bounded-reachability vector set. The sub-chart MAY itself dispatch into further sub-charts (recursive); the recursion depth bound is PCDN-SOS-12-005. |
| **Parent chart** | A chart that dispatches into one or more sub-charts. From the parent's perspective each sub-chart appears as a single state whose entry/exit is governed by the sub-chart's declared contract. The parent does NOT see the sub-chart's internal states; it sees the contract. |
| **Sub-chart contract** | The four-tuple declared by every sub-chart: `(events_in, events_out, invariants, datamodel_boundary)`. The contract is the load-bearing artifact at the dispatch boundary — the parent verifies against it, the sub-chart's environment is assumed to satisfy it. Shape ratified at §5.1. |
| **Events-in** | The subset of the parent's event vocabulary that the parent routes into the sub-chart. The sub-chart treats events-in as its external-event vocabulary; the parent treats events-in as the set of events it MAY send to the dispatched state. |
| **Events-out** | The subset of events the sub-chart raises that the parent observes. The parent treats events-out as events that exit the dispatched state; the sub-chart treats events-out as the set of events it MAY raise to its environment. |
| **Datamodel boundary** | The declaration of which datamodel fields the sub-chart reads (and which the environment writes), and which the sub-chart writes (and which the environment reads). Shape ratified at PCDN-SOS-12-002. |
| **Dispatch boundary** | The interface between a parent chart's dispatched state and the sub-chart it dispatches into. The dispatch boundary is where contract-matching happens; per [INV-SOS-F][inv-sos-f] it is the natural seam at which composition becomes "per-layer", not "Cartesian product." |
| **Contract-matching** | The check, performed at sub-chart instantiation (compile time, lint time, or runtime per PCDN-SOS-12-006), that the parent's events-in routing covers the sub-chart's declared events-in, that the parent's expected events-out cover the sub-chart's declared events-out, that the parent's invariants imply the sub-chart's declared environmental invariants, and that the datamodel boundary is honoured. Mismatch shape per §5.3. |
| **Sub-chart reference** | The syntactic surface by which a parent chart names a sub-chart. PCDN-SOS-12-001 resolves whether this is SCXML's existing `<state src="other.scxml"/>` mechanism or a SOS-specific `<dispatch ref="..."/>` annotation. |
| **Per-layer bound** | The bounded-reachability vector count of one chart in isolation, treating its dispatched sub-charts as opaque states governed by their declared contracts. The parent's per-layer bound is constant in the sub-charts' internal state-count; the sub-chart's per-layer bound is constant in the parent's state-count. |
| **Independence axis** | Per [INV-SOS-F][inv-sos-f], an SCXML `<parallel>` child region. Joint reachability across independence axes IS Cartesian (per-region × per-region), but each region's per-layer bound is enumerated individually before the product. The distinction matters: 2 regions × 100 states each is 200 individual-bound enumeration + 10,000 joint enumeration if the joint enumeration is required; if independence holds (no cross-region datamodel writes), the 10,000 is not required. |
| **Legibility threshold** | The project-configured maximum peer-state count at any one level of a chart before the lint requires structural factoring. Default at v1 per PCDN-SOS-12-003. The threshold is a [SOS-01][sos-01] lint rule whose enforcement makes the discipline operational. |
| **Dispatch-tree** | The DAG of charts in a chart-family, rooted at the top-level chart, with edges pointing from each parent chart to each sub-chart it dispatches. The dispatch-tree is finite (bounded by PCDN-SOS-12-005) and acyclic by construction (mutual recursion between charts is rejected at contract-match time). |

## 4. Source-of-truth map

| Concept | Authority |
|---|---|
| MCP tool names `extract_region_to_subchart` / `inline_subchart` | [SOS-11 §5.1][sos-11-tools] |
| Sub-chart reference syntax (`<state src/>` or `<dispatch ref/>`) | **this doc** (§5.1) once PCDN-SOS-12-001 resolved |
| Sub-chart contract four-tuple shape | **this doc** (§5.1) |
| Datamodel boundary declaration form | **this doc** (§5.2) once PCDN-SOS-12-002 resolved |
| Contract-matching semantics + failure mode | **this doc** (§5.3) once PCDN-SOS-12-006 resolved |
| Bound-composition algebra | **this doc** (§6), citing CSP (Hoare 1978 + ISO/IEC 13568) |
| Per-sub-chart vector emission contract | **this doc** (§7), composing [SOS-03][sos-03] |
| Legibility threshold default + enforcement seam | **this doc** (§9), composing [SOS-01][sos-01] + [SOS-11][sos-11] |
| Cross-phase invariants INV-SOS-A through H | [SOS-07 §6][sos-07-inv] |
| SCXML 1.0 `<state src/>` semantics | W3C Recommendation 2015 (upstream) |
| CSP semantics | Hoare 1978 + ISO/IEC 13568:1996 (upstream) |

[sos-07-inv]: ./SOS-07-CONCEPTS.md#6-cross-phase-invariants--inv-sos-a-through-h

## 5. Frozen decisions

### 5.1 Sub-chart contract shape

Every sub-chart MUST declare a contract. The contract is a four-tuple:

```
SubChartContract {
    events_in:           [<event-name>, ...],
    events_out:          [<event-name>, ...],
    invariants:          {
        maintained_by_subchart:    [<invariant-id>, ...],
        assumed_of_environment:    [<invariant-id>, ...],
    },
    datamodel_boundary:  {
        reads:        [<field-name>, ...],
        writes:       [<field-name>, ...],
        env_writes:   [<field-name>, ...],
        env_reads:    [<field-name>, ...],
    },
}
```

Per-field requirements:

- **`events_in`** — Closed set. The sub-chart's `<datamodel>` and transitions MAY reference only events in this set (treated as the sub-chart's `ExternalEventName` vocabulary per [SOS-01 §5.3][sos-01]). Events the sub-chart raises internally (`<raise>`) are not part of events-in.
- **`events_out`** — Closed set. Every event the sub-chart raises that exits the dispatched state via `<send>` to the parent MUST appear in this set. Events raised internally that resolve inside the sub-chart are not part of events-out.
- **`invariants.maintained_by_subchart`** — Per-chart invariants the sub-chart's bounded-reachability analysis verifies. The parent chart's verification treats these as discharged.
- **`invariants.assumed_of_environment`** — Per-chart invariants the sub-chart assumes its environment satisfies. The parent chart's verification MUST prove these hold at the dispatch boundary.
- **`datamodel_boundary`** — Shape resolved at PCDN-SOS-12-002.

PCDN-SOS-12-001 resolves whether the contract is declared inline in the sub-chart's SCXML payload (under a SOS-specific `other_attributes` extension per [INV-SOS-D][inv-sos-d]) or in a sibling `*.contract.scjson` file alongside `*.scxml`. Default recommendation: **inline in SCXML** under a `<sos:contract>` extension element — keeps the chart and its contract co-located, round-trips through scjson, no new file-naming convention.

PCDN-SOS-12-004 resolves the contract-syntax detail (extension element name; field name forms; embedding under `<datamodel>` vs at chart root). Default recommendation: a single `<sos:contract>` element directly under the chart's root `<scxml>`, with four sub-elements (`<events-in>`, `<events-out>`, `<invariants>`, `<datamodel-boundary>`) each containing the per-field structure above.

### 5.2 Datamodel boundary declaration

The `datamodel_boundary` field of the contract is a four-set declaration: what the sub-chart reads, what the sub-chart writes, what the environment writes, what the environment reads. PCDN-SOS-12-002 resolves the granularity:

- **(a)** **Per-field**, declared at the field level in the sub-chart's contract.
- **(b)** **Per-sub-chart**, declared as a blanket "this sub-chart reads/writes the following set" without per-field detail.

Default recommendation: **(a) per-field**. Per-field declarations cost more to author but make the dispatch-boundary check tractable: contract-matching reduces to set-membership tests over the parent's datamodel. Per-sub-chart blanket declarations leave the dispatch-boundary check at "trust the developer" — admissible at v1 but regrows the documentation-drift failure mode the methodology exists to prevent.

The four-set algebra:

- A field MAY appear in `reads` and `env_writes` (the sub-chart consumes a value the environment produces). This is the canonical inbound-data case.
- A field MAY appear in `writes` and `env_reads` (the sub-chart produces a value the environment consumes). This is the canonical outbound-data case.
- A field MAY appear in `reads` and `writes` (the sub-chart reads and writes — but only if the field does NOT appear in `env_writes` or `env_reads`; otherwise it is a concurrent-access pattern requiring an SCXML `<parallel>` synchronisation primitive declared at SOS-12 v2).
- A field appearing in `env_writes` and `env_reads` only (not `reads` or `writes`) is a parent-private field invisible to this sub-chart; declaring it in the contract is redundant but not erroneous.

### 5.3 Dispatch semantics + contract-matching

When a parent chart's transition targets a dispatched state, the sub-chart is instantiated. Instantiation semantics:

- **(a) Contract-match check.** The parent's routing context (what events it can send the sub-chart, what events it expects out, which invariants it maintains, which datamodel fields it grants read/write access to) is compared against the sub-chart's declared contract. Mismatch is a failure per PCDN-SOS-12-006.
- **(b) Datamodel scope.** The sub-chart's `<datamodel>` is private to the sub-chart at v1 (no field references from the parent into the sub-chart's `<datamodel>` and vice versa). Inter-chart communication is exclusively via events (events-in / events-out) and via the declared `datamodel_boundary` fields, which live in the **parent's** datamodel and are referenced by name from the sub-chart's contract.
- **(c) Event routing.** Events the parent fires that match `events_in` are routed into the sub-chart's external-event queue. Events the sub-chart raises that match `events_out` exit the dispatched state and are observed by the parent. Events not in either set are sub-chart-internal and do not cross the boundary.
- **(d) Recursive instantiation.** The sub-chart MAY itself contain dispatched states. The instantiation algorithm recurses; PCDN-SOS-12-005 caps the recursion depth.

Contract-mismatch shape — PCDN-SOS-12-006 resolves whether mismatch is:

- **(a) Compile-time error.** The chart family fails to compile if any contract is unmatched. Strongest guarantee; rejects half-developed chart families until contracts are filled in.
- **(b) Lint warning.** The chart family compiles; the [SOS-01][sos-01] lint pass reports mismatch as a lint rule. Permits incremental development; charts can be partially-contracted and still emit code.
- **(c) Runtime check.** Mismatch is detected at sub-chart instantiation at runtime; raises a chart-vocabulary diagnostic per [INV-SOS-H][inv-sos-h]. Weakest guarantee; admissible only when the dispatch-tree is dynamic (e.g. an orchestrator chart in [SOS-10][roadmap] that instantiates sub-charts based on runtime configuration).

Default recommendation: **(b) lint warning at v1**, with (a) compile-time error as a future tightening once chart-family authoring is established. (c) is reserved for [SOS-10][roadmap] orchestrator charts where dispatch is data-driven.

## 6. Bound-composition algebra

This section concretises [INV-SOS-F][inv-sos-f] as an algorithm. The algorithm operates on a dispatch-tree (per §3) and emits per-chart vector sets (per §7).

### 6.1 Per-layer bound

For a single chart `C` with no dispatched sub-charts and no `<parallel>` regions:

> `bound(C) = |reachable_states(C)|`

i.e. the bounded-reachability vector count is the count of reachable states under the chart's event vocabulary. This is the [SOS-03][sos-03] v1 case unchanged.

### 6.2 `<parallel>` regions (independence axes)

For a chart `C` with `<parallel>` regions `R_1, ..., R_n`, where each region's transitions and datamodel-writes are independent of every other region (no cross-region event routing, no shared datamodel writes):

> `bound(C) = sum_i |reachable_states(R_i)|` (per-region enumeration)
> `joint_states(C) = prod_i |reachable_states(R_i)|` (joint Cartesian — declared, but not exhaustively enumerated)

The per-region enumeration is sufficient for per-layer vector emission per [INV-SOS-B][inv-sos-b]; the joint Cartesian is declared as an upper bound but not exhaustively enumerated UNLESS a per-chart invariant explicitly spans regions (in which case the joint product IS required for that invariant's verification, and the chart author has knowingly opted into Cartesian cost).

### 6.3 Sequential composition (dispatch)

For a parent chart `P` that dispatches into sub-charts `S_1, ..., S_m`:

> `bound(P) = |reachable_states(P)|` (treating each `S_i` as an opaque state per its contract)
> `bound(S_i) = ` per the recursive application of this algebra to `S_i`
> `bound(family(P)) = bound(P) + sum_i bound(S_i)` (sum, NOT product)

The sum-not-product is the load-bearing claim of CSP-inspired composition: contract-matching at the dispatch boundary lets each layer enumerate independently. The parent's bound is constant in the sub-charts' internal state count; the sub-charts' bound is constant in the parent's state count; the joint cost is additive.

### 6.4 CSP citation (per EOQ-007-ROADMAP)

The model SOS-12 ratifies is recognisable as a **CSP-extended formalism**: sub-charts are CSP **processes**; events-in / events-out are CSP **channels**; contract-matching at the dispatch boundary is CSP **channel synchronisation**. SOS extends CSP with bounded-vector emission as a first-class operation — the chart's vector set IS the process's externally-visible behaviour, enumerated.

Lineage acknowledged:

- **CSP (Communicating Sequential Processes)** — Hoare 1978; formalised as ISO/IEC 13568:1996. The foundational algebra. SOS-12 is `compose` per [INV-SOS-E][inv-sos-e]; SOS does not author CSP, SOS uses CSP terms in its own bound-composition reasoning.
- **Handel-C / occam-π** — earlier CSP-inspired languages that compiled to FPGAs / parallel hardware. SOS-12's HDL backend ([SOS-08][roadmap-08d]) is in their lineage.
- **Statecharts (Harel 1987)** — hierarchical states + orthogonal regions are the structural pattern SOS-12 inherits via SCXML. Statecharts provide the structure; CSP provides the composition algebra.

What SOS-12 adds beyond the CSP lineage:

- **Bounded-vector emission as a first-class operation.** CSP traces are infinite in general; SOS bounds them per [SOS-03][sos-03] and emits the exhaustive bounded trace set as the verification contract.
- **Per-layer × independence-axes composition as the default**, with the joint Cartesian as an explicit opt-in when invariants span layers.
- **Chart-vocabulary failure messages per [INV-SOS-H][inv-sos-h].** A vector violation names the chart/sub-chart/state/transition that produced it; CSP traces conventionally do not carry this metadata.

### 6.5 Recursive depth bound

Per PCDN-SOS-12-005, the recursion depth of dispatched sub-charts is bounded. Default recommendation: **8 levels**. Rationale: 8 levels covers every realistic protocol decomposition (the HTTP example in §8 is 3 levels; OAuth/OIDC + transport + framing is rarely more than 6); deeper recursion is almost always accidental cycle through the `inline_subchart` → `extract_region_to_subchart` round-trip; capping at 8 catches the bug at lint time without constraining legitimate use. The cap is an [SOS-01][sos-01] lint rule; chart families MAY override the cap via project-level configuration.

## 7. Per-sub-chart vector emission

[INV-SOS-B][inv-sos-b] mandates bounded-vector emission "at every layer". This section specifies what that means operationally for a dispatch-tree.

### 7.1 Per-chart vector sets

For each chart in the dispatch-tree (parent or sub-chart), the [SOS-03][sos-03] vector framework emits a vector set sized to that chart's per-layer bound (§6.1). The vector set tests:

- Every reachable state's entry / exit / transition behaviour.
- Every declared invariant the chart maintains (per `invariants.maintained_by_subchart` in §5.1).
- Every event-vocabulary event's effect.

Per [INV-SOS-H][inv-sos-h], each vector carries metadata naming the chart (by SHA-pinned identity) it tests. A failing vector's diagnostic names: `chart=<chart-id>`, `state=<state-id>`, `transition=<transition-id>`, `invariant=<invariant-id>` — never the joint state across the dispatch-tree.

### 7.2 Boundary vectors

For each dispatch boundary (parent ↔ sub-chart edge), the parent chart emits **boundary vectors** that test:

- Every event in `events_in` produces the parent-observable behaviour the contract declares (parent sends event; sub-chart, treated as opaque, behaves as if its contract is the spec).
- Every event in `events_out` is observed by the parent in the contract-declared sequence.
- The `datamodel_boundary` reads/writes happen in the contract-declared order.
- The `invariants.assumed_of_environment` are proved at the moment of dispatch.

Boundary vectors are constant-size (one per declared event-in, one per declared event-out, one per declared datamodel-boundary field) — they do NOT depend on the sub-chart's internal state count. This is what makes the methodology scale: at any layer, the vector cost is the layer's local state count plus the dispatch-boundary count, not the joint Cartesian.

### 7.3 No replay across layers

A parent chart's vector MUST NOT enumerate the sub-chart's internal states. A sub-chart's vector MUST NOT enumerate the parent's internal states. Each layer's vectors are local-bound, with the contract serving as the abstraction at the boundary.

This is the operational realisation of INV-SOS-F. Replay-across-layers is forbidden by [INV-S-DISP-1] (§10); a vector emitter that violates it is non-conforming.

### 7.4 Conformance level extension

[SOS-03][sos-03]'s three conformance grades (`SmokePass`, `FullSuitePass`, `FullSuitePassWithDiversity`) extend per dispatch-tree:

- A `FullSuitePass` claim for a chart family means every chart in the dispatch-tree passes its per-layer vector set AND every dispatch boundary passes its boundary vector set.
- A `SmokePass` claim is per-chart unchanged: each chart's `Smoke` vectors pass.
- The chart-family-level grade is the minimum grade across all charts in the dispatch-tree (a family's `FullSuitePass` requires every sub-chart at `FullSuitePass`).

The grade is recorded in chart-family metadata; per-chart §15 entries cite the family's grade at the time of the claim.

## 8. Protocol-stack worked example

This section walks the canonical concrete case: an HTTP-parser dispatch chart family. The example clarifies §3 glossary and §5–6 frozen decisions concretely. The HTTP family is illustrative; SOS-12 does NOT ship a canonical HTTP chart at v1.

### 8.1 Top-level dispatch chart `http_top.scxml`

States (8): `idle`, `awaiting_request_line`, `dispatching_get`, `dispatching_post`, `dispatching_put`, `dispatching_delete`, `dispatching_unknown_method`, `responding`.

Events-in (external): `tcp.bytes_received`, `tcp.connection_closed`, `timer.request_timeout`.
Events-out (external): `tcp.send_response`, `tcp.close_connection`.

The chart routes incoming bytes through `awaiting_request_line` to parse the HTTP method; the parsed method drives the transition into `dispatching_<METHOD>`. Each `dispatching_<METHOD>` state is a dispatched state pointing at a per-method sub-chart.

### 8.2 Per-method sub-charts

Four sub-charts at this layer: `http_get.scxml`, `http_post.scxml`, `http_put.scxml`, `http_delete.scxml`. Each declares a contract:

```
<sos:contract>
  <events-in>
    <event>tcp.bytes_received</event>
    <event>timer.body_timeout</event>
  </events-in>
  <events-out>
    <event>method.complete</event>
    <event>method.error</event>
  </events-out>
  <invariants>
    <maintained-by-subchart>INV-GET-1-headers-bounded</maintained-by-subchart>
    <maintained-by-subchart>INV-GET-2-body-absent</maintained-by-subchart>
    <assumed-of-environment>INV-HTTP-1-request-line-parsed</assumed-of-environment>
  </invariants>
  <datamodel-boundary>
    <reads>parsed_method</reads>
    <reads>parsed_uri</reads>
    <writes>response_status</writes>
    <writes>response_headers</writes>
  </datamodel-boundary>
</sos:contract>
```

States per method-sub-chart range from 5 (GET — header parse + dispatch) to 15 (POST — header parse + length-validated body + chunked transfer). The per-method sub-chart's contract abstracts the parser's internal state from the top-level dispatch.

### 8.3 Per-handler sub-charts

Within each per-method sub-chart, individual route handlers MAY themselves be sub-charts. A `GET /api/v1/users/{id}` handler dispatched out of `http_get.scxml` declares its own contract (events-in: `route.matched`, `database.fetched`, `database.error`; events-out: `handler.complete`, `handler.error`; datamodel-boundary: reads `parsed_uri`, writes `response_body`).

### 8.4 Bound composition for the family

Per §6.3:

- `bound(http_top) = 8`
- `bound(http_get) = 5`, `bound(http_post) = 15`, `bound(http_put) = 12`, `bound(http_delete) = 7`
- per-handler sub-charts ≈ 5–20 each
- `bound(family)` = sum across all charts in the dispatch-tree ≈ 100–200 vectors

A naïve flat chart for HTTP is well over 200 states; a Cartesian-product flattening of the same protocol family is ~10^6 joint states. The per-layer-sum bound is 2-to-3 orders of magnitude smaller than the joint product, AND legible at every individual chart.

### 8.5 Legibility-as-discipline check

Every chart in the family stays under the 15-peer-state default threshold (§9). The `http_post` chart at 15 states sits exactly at the threshold; the [SOS-01][sos-01] lint warns the author that adding a 16th peer state will fail lint until the author factors via `extract_region_to_subchart`. The discipline catches scope-creep at lint time, before review.

## 9. SOS-11 integration — legibility-as-discipline

SOS-12's legibility threshold is the seam where the methodology stops being "a thing the developer remembers to do" and becomes "a thing the tooling enforces." Per [INV-SOS-C][inv-sos-c], MCP is the sole modification surface; per [INV-SOS-A][inv-sos-a], the chart is the sole upstream spec. SOS-12 closes the loop: the tooling refuses to grow charts past the threshold, and the only available factoring operation is the SOS-11 `extract_region_to_subchart`.

### 9.1 Threshold default + enforcement

PCDN-SOS-12-003 resolves the default. Recommendation: **15 peer states at one level**. Rationale: empirically, a chart legible on a single 4K viewer screen sits at 12–18 peer states with their transitions visible; 15 is the median. Smaller thresholds (10) force premature factoring and produce many shallow sub-charts; larger thresholds (20+) regress to "this chart is too big to review at a glance."

Threshold registration policy: **Specification Required**. Projects MAY override the threshold per their context via a `chart-family.toml` `legibility_threshold` field; the override is recorded in the chart-family metadata and surfaces in every chart-family's `SmokePass` / `FullSuitePass` audit trail.

### 9.2 [SOS-11][sos-11] tool-surface behaviour at the threshold

When a chart hits the legibility threshold, the [SOS-11 §5.1][sos-11-tools] tool surface's behaviour shifts:

- `add_state` returns `LintFailure` (per [SOS-11 §7][sos-11-failure]) with diagnosis "chart `<id>` is at the legibility threshold; structural-add operations require `extract_region_to_subchart` first."
- `extract_region_to_subchart` remains available; its result includes a vector_delta naming the boundary vectors emitted at the new dispatch boundary.
- `inline_subchart` is admissible only if the parent chart's post-inline state count would be below the threshold; otherwise it returns `LintFailure` with diagnosis "inlining would exceed the legibility threshold."

[sos-11-failure]: ./SOS-11-CONCEPTS.md#7-failure-model

### 9.3 The discipline loop

The discipline loop closes:

- The chart starts small. The developer adds states via `add_state`. The chart grows.
- The chart hits the threshold. `add_state` fails. The developer either accepts the chart is large enough OR factors out a region.
- The developer calls `extract_region_to_subchart`. The new sub-chart inherits the events-in / events-out / invariants the developer declares as the contract. The parent chart shrinks by the extracted region's state count.
- The developer continues `add_state` calls on the (smaller) parent or on the (new) sub-chart, each of which is again subject to the threshold.
- The chart family grows as a dispatch-tree of legible-at-every-level charts.

The methodology scales by construction. The developer's intent (large protocol, complex orchestration) is preserved; the artifact is legible; the verification cost stays sum-not-product per §6.

## 10. Frozen enumerations from SOS-12

SOS-12 freezes the following enumerations.

### 10.1 SOS-12-local invariants

| Id | Statement |
|---|---|
| **INV-S-DISP-1 — No replay across layers** | A vector emitter MUST NOT enumerate a sub-chart's internal states from a parent chart's vector set, or vice versa. Each layer's vectors are local-bound per §7.3. |
| **INV-S-DISP-2 — Contract-matching is mandatory** | Every dispatch boundary MUST have a contract-match check (compile-time, lint, or runtime per PCDN-SOS-12-006). A chart family without contract-match checks is non-conforming. |
| **INV-S-DISP-3 — Dispatch-tree acyclicity** | The dispatch-tree MUST be a DAG. Mutual recursion (chart A dispatches B; B dispatches A) is rejected at contract-match time; self-recursion (A dispatches itself) is rejected at the same gate. Bounded recursion depth per PCDN-SOS-12-005 reasserts this at the lint surface. |
| **INV-S-DISP-4 — Sub-chart datamodel privacy** | The sub-chart's `<datamodel>` is private to the sub-chart. Inter-chart data flow happens only via events-in / events-out (transient) and via the parent's datamodel fields declared in `datamodel_boundary` (durable). Cross-chart `<datamodel>` field references are rejected at lint time. |
| **INV-S-DISP-5 — Per-layer vector count is local** | The vector count for any chart in a dispatch-tree depends only on that chart's per-layer bound (§6.1, §6.2) and the count of its dispatch boundaries (§7.2); it does NOT depend on the sub-chart's internal state count. This is the operational realisation of [INV-SOS-F][inv-sos-f] at the vector-emission surface. |

Registration policy for §10.1: **Standards Action**. Adding or modifying an `INV-S-DISP-*` invariant requires a §15 amendment to this doc and cross-phase review.

### 10.2 Legibility threshold

Single integer; default **15** per PCDN-SOS-12-003. Registration policy: **Specification Required** (projects override via `chart-family.toml`; the default lives in this doc and changes via §15 amendment).

### 10.3 Recursion depth bound

Single integer; default **8** per PCDN-SOS-12-005. Registration policy: **Specification Required** (same shape as §10.2).

### 10.4 Contract-mismatch failure-mode enum

`{ CompileTimeError, LintWarning, RuntimeCheck }` per PCDN-SOS-12-006. Default at v1: `LintWarning`. Registration policy: **Specification Required** (projects MAY tighten to `CompileTimeError` per chart-family).

## 11. Standards integration matrix (additions to SOS-07 §7)

Per [INV-SOS-E][inv-sos-e]. SOS-12 adds one row to the matrix declared at [SOS-07 §7][sos-07-matrix]:

| Concept | Upstream authority | Local relationship | Phase that declares it | Mutation rights |
|---|---|---|---|---|
| CSP (Communicating Sequential Processes) | Hoare 1978; ISO/IEC 13568:1996 | **compose** (sub-charts are CSP processes; events-in / events-out are CSP channels; contract-matching at dispatch is CSP channel synchronisation; SOS extends CSP with bounded-vector emission as a first-class operation) | **this doc** (§6.4) | none — citation only; SOS does not modify CSP |

SCXML 1.0 (already declared `mirror` at [SOS-07 §7][sos-07-matrix]) extends in scope: SOS-12 uses `<state>` (with PCDN-SOS-12-001-resolved sub-chart-reference syntax) and `<send>` / `<raise>` for event routing across the dispatch boundary. Within the W3C-defined SCXML grammar; no SCXML extension.

## 12. Reconciliation decisions vs adjacent repo primitives

### vs. [SOS-07 §6 INV-SOS-F][inv-sos-f]

INV-SOS-F is the parent invariant; SOS-12 `derives` it (operationally concretises it into the §6 bound-composition algebra). The two are mutually consistent; SOS-12 does not amend INV-SOS-F's statement, it ratifies the algorithm INV-SOS-F's narrative pointed at.

### vs. [SOS-11 §5.1][sos-11-tools] `extract_region_to_subchart` / `inline_subchart`

SOS-11 ships the tool surface; SOS-12 ratifies the contract algebra. The two phases are co-designed:

- A `extract_region_to_subchart` call's `vector_delta` ([SOS-11 §6][sos-11-result]) field is computed per §7.2 boundary-vector emission.
- An `inline_subchart` call's admissibility check ([SOS-11 §5.1][sos-11-tools]) consults this doc's §5.3 contract-matching to verify the sub-chart's declared invariants hold in the inlined context.
- The `LintFailure` returned at the legibility threshold ([SOS-11 §7][sos-11-failure]) cites §9.2 of this doc.

[sos-11-result]: ./SOS-11-CONCEPTS.md#6-tool-call-result-contract

### vs. [SOS-03][sos-03] vector framework

SOS-03's `Vector` struct + `expected_trace` field per [INV-S-CONF-1][sos-03-inv1] applies per-chart in a dispatch-tree. SOS-12 `composes` SOS-03 by extending the framework with the per-sub-chart vector set + boundary-vector set per §7. The SOS-03 schema versioning (`INV-S-CONF-9`) accommodates: the boundary-vector subtype lands as a §15 amendment on SOS-03 once SOS-12 ratifies.

[sos-03-inv1]: ./SOS-03-CONCEPTS.md

### vs. [SOS-01][sos-01] lint

SOS-12 declares two new lint rules (legibility threshold per §9, recursion depth bound per §6.5, contract-mismatch per §5.3 if PCDN-SOS-12-006 resolves `LintWarning`). The rules land as §15 amendments on [SOS-01][sos-01]; SOS-12 does NOT extend the lint runner, SOS-12 invokes lint as the enforcement surface.

### vs. Statecharts (Harel 1987) + SCXML 1.0 (W3C 2015)

SOS-12 inherits hierarchical states + orthogonal regions from Statecharts; SOS-12 inherits `<state src>` (PCDN-SOS-12-001 dependent) + `<parallel>` + `<send>` / `<raise>` from SCXML. Neither extends the parent formalism's grammar; SOS-12 attaches the sub-chart contract via a SOS-specific `other_attributes`-channel extension element per [INV-SOS-D][inv-sos-d]. Round-trips through scjson cleanly.

### vs. CSP (Hoare 1978)

SOS-12 cites CSP as the lineage per §6.4. SOS extends CSP with bounded-vector emission, per-layer × independence-axes default composition, and chart-vocabulary failure messages. Relationship per §11 is `compose`; no mutation rights on CSP.

### vs. parent CLAUDE.md "Spec-Before-Code Planning Discipline"

SOS-12 IS spec-before-code applied to chart decomposition: the dispatch contract is the spec, the per-layer vectors are the verification, the SOS-11 tools are the modification surface. The relationship is `compose` — SOS-12 composes the discipline at the chart-decomposition layer.

## 13. Acceptance checklist

A conforming SOS-12 ratification satisfies all of:

- (a) Sub-chart contract four-tuple shape in §5.1 frozen.
- (b) Datamodel boundary declaration form in §5.2 frozen per PCDN-SOS-12-002 resolution.
- (c) Dispatch semantics + contract-matching failure mode in §5.3 frozen per PCDN-SOS-12-006 resolution.
- (d) Bound-composition algebra in §6 specified; CSP citation in §6.4 explicit; recursion depth cap in §6.5 frozen per PCDN-SOS-12-005 resolution.
- (e) Per-sub-chart vector emission contract in §7 specified; `INV-S-DISP-1` (no replay across layers) frozen as Standards Action.
- (f) Protocol-stack worked example in §8 lands as a normative example clarifying §3 glossary + §5–6 frozen decisions.
- (g) [SOS-11][sos-11] legibility-discipline integration in §9 specified; threshold default in §9.1 frozen per PCDN-SOS-12-003 resolution; `add_state` / `extract_region_to_subchart` / `inline_subchart` behaviour at threshold in §9.2 specified.
- (h) `INV-S-DISP-1` through `INV-S-DISP-5` frozen as Standards Action enumeration; registration policy documented.
- (i) Sub-chart reference syntax in §5.1 frozen per PCDN-SOS-12-001 resolution; contract-syntax detail per PCDN-SOS-12-004 resolution.
- (j) AuthorityRelationship row for CSP added to [SOS-07 §7][sos-07-matrix] via §11 (this doc declares the row; SOS-07 §7 amends to absorb at SOS-12 ratification per [INV-SOS-E][inv-sos-e]).
- (k) Every cited [INV-SOS-A through H][sos-07-inv] invariant relates to SOS-12 either by `derive`, `compose`, or `mirror` per [INV-SOS-E][inv-sos-e]; relationships enumerated in §13.1 below.
- (l) PCDN-SOS-12-001 through PCDN-SOS-12-006 (§15) each ratified with a chosen value before status flips to 🟢.

### 13.1 Cited invariants

How each [INV-SOS-*][sos-07-inv] invariant relates to SOS-12:

| Invariant | Relationship |
|---|---|
| INV-SOS-A (Chart-as-source) | `mirror`. The dispatch-tree is composed of charts; each chart is the source per INV-SOS-A. SOS-12 does not extend the invariant; SOS-12 applies it at the family scale. |
| INV-SOS-B (Vectors-as-deliverable) | `derive`. §7 specifies per-sub-chart + boundary vector emission as the operational realisation of "vectors-as-deliverable at every layer." |
| INV-SOS-C (MCP as sole modification surface) | `compose`. §9.2's legibility-threshold enforcement is what makes the SOS-11 tool surface enforce the discipline. The two phases compose to realise INV-SOS-C at the chart-decomposition scale. |
| INV-SOS-D (iState authoring, SCXML canonical) | `mirror`. Sub-charts are SCXML on disk; their contracts are SCXML extensions; both round-trip through scjson per INV-SOS-D. |
| INV-SOS-E (Explicit AuthorityRelationship) | `mirror`. §11 declares the CSP row per the enum. |
| INV-SOS-F (Bound composition) | `derive`. §6 is the algorithm INV-SOS-F's narrative pointed at. SOS-12's load-bearing reason for existence. |
| INV-SOS-G (Verified-codegen position) | `compose`. The bounded-vector emission per §7 is the discharge-evidence each codegen target's omissions cite per INV-SOS-G. The per-layer bound makes the cite tractable; SOS-13's Rust-side measurements will exercise this. |
| INV-SOS-H (Vector-to-chart traceability) | `derive`. §7.1 mandates per-chart identity in every vector's metadata; §7.2 mandates per-boundary identity in boundary vectors; both render in chart vocabulary per INV-SOS-H. |

## 14. Non-goals

This phase does NOT:

- Author the implementation of `extract_region_to_subchart` / `inline_subchart`. [SOS-11][sos-11] ships the tool surface; the implementation lands as a follow-up commit citing SOS-11 + SOS-12 ratifications.
- Define the per-chart invariant grammar. Per-chart invariants are authored at chart-creation time; their grammar is per-project. SOS-12 specifies the contract-declaration shape (`maintained_by_subchart` / `assumed_of_environment`) but does NOT specify the invariant expression language.
- Define dynamic-dispatch sub-chart instantiation. PCDN-SOS-12-006's `RuntimeCheck` resolution leaves room for [SOS-10][roadmap] orchestrator charts to instantiate sub-charts based on runtime configuration; SOS-12 does NOT specify the dynamic-instantiation surface, that lives in [SOS-10][roadmap].
- Specify cross-region datamodel synchronisation for `<parallel>` regions that share datamodel writes. v1 declares such cases require Cartesian-product enumeration; the `<sync>` primitive for explicit cross-region synchronisation is deferred to a future SOS-12 amendment.
- Modify any code in `tools/sos-codegen/`, `sim/sos-sim/`, `conformance/`, `ports/m7-rust/`, `ports/m7-c/`. SOS-12 is a documentation phase; implementation lands as a follow-up per spec-before-code discipline.
- Author a canonical HTTP chart family. §8 is an illustrative worked example, not a shipped chart. Projects authoring HTTP-parser charts derive from §8; SOS does not ship `http_*.scxml`.
- Specify per-language code-generation patterns for dispatched states. The Rust codegen ([SOS-04][sos-04-link]) and C codegen ([SOS-05][sos-05-link]) absorb the dispatch model in their own §15 amendments at the time they pick up SOS-12-aware codegen; SOS-12 does NOT prescribe the per-target lowering.

[sos-04-link]: ./SOS-ROADMAP-07-PLUS.md
[sos-05-link]: ./SOS-ROADMAP-07-PLUS.md

## 15. Change log

### 2026-05-23 — Drafted (Ira)

Initial draft authored against [SOS-07][sos-07] ratification + [SOS-11][sos-11] co-drafting + [`SOS-ROADMAP-07-PLUS.md`][roadmap] §4 SOS-12 informative scope sketch + EOQ-007-ROADMAP CSP-citation resolution.

**PCDNs raised (§-binding):**

- **PCDN-SOS-12-001 — Sub-chart reference syntax.** §5.1. Options: (a) SCXML's existing `<state src="other.scxml"/>` mechanism (W3C-blessed but rarely-implemented in SCXML engines); (b) a SOS-specific `<dispatch ref="..."/>` extension element under `other_attributes` (SOS-owned; round-trips through scjson per INV-SOS-D; not a standard SCXML element); (c) `<state>` with a `<sos:dispatch>` child element (hybrid — uses standard `<state>` but a SOS extension for the sub-chart reference). Default recommendation: **(c)** — `<state>` is W3C-standard, `<sos:dispatch>` is a SOS-owned extension carrying the sub-chart reference path. Preserves SCXML round-trip semantics; survives engines that don't implement `<state src/>`.

- **PCDN-SOS-12-002 — Datamodel boundary declaration granularity.** §5.2. Options: (a) per-field (each datamodel field declared in `reads` / `writes` / `env_writes` / `env_reads` lists explicitly); (b) per-sub-chart blanket ("this sub-chart reads/writes the following set" without per-field detail). Default recommendation: **(a) per-field** — keeps the contract-matching check tractable; declares the dispatch-boundary precisely; preserves the auditable surface the methodology depends on.

- **PCDN-SOS-12-003 — Legibility threshold default.** §9.1, §10.2. Options: (a) 10 peer states at one level (tight; forces shallow factoring); (b) 15 peer states at one level (recommended; matches empirical chart-viewer screen-size median); (c) 20 peer states at one level (loose; large charts admissible); (d) no default — project-configurable from day one with the lint rule disabled until configured. Default recommendation: **(b) 15**. Projects override via `chart-family.toml`; the override is recorded in chart-family metadata.

- **PCDN-SOS-12-004 — Sub-chart contract syntax detail.** §5.1. Options: (a) a single `<sos:contract>` element at chart root with four sub-elements (`<events-in>`, `<events-out>`, `<invariants>`, `<datamodel-boundary>`) — current draft shape; (b) a sibling `*.contract.scjson` file alongside `*.scxml` with the contract in a separate file; (c) inline in the SCXML `<datamodel>` element via SOS-specific extension attributes. Default recommendation: **(a) single `<sos:contract>` element at chart root** — co-located with the chart, round-trips through scjson, no new file convention, no `<datamodel>` overload.

- **PCDN-SOS-12-005 — Recursion depth bound.** §6.5, §10.3. Options: (a) unbounded; (b) capped at 8 (recommended); (c) capped at 16. Default recommendation: **(b) 8**. Covers every realistic protocol decomposition; catches accidental cycles at lint time; projects MAY override per chart-family.

- **PCDN-SOS-12-006 — Contract-mismatch handling.** §5.3, §10.4. Options: (a) compile-time error (strongest; rejects half-developed chart families until contracts are filled in); (b) lint warning (incremental development; charts compile, lint reports mismatch); (c) runtime check (weakest; reserved for [SOS-10][roadmap] orchestrator charts where dispatch is data-driven). Default recommendation: **(b) lint warning at v1**. (a) reserved as a future tightening; (c) reserved for SOS-10.

Status: 🟡 **drafted, awaiting PCDN walkthrough.** Ratifies to 🟢 once each PCDN above has a chosen value and the corresponding section is updated. [SOS-11][sos-11] is co-dependent — `extract_region_to_subchart` / `inline_subchart` tool semantics need SOS-12's contract algebra before they are operationally complete; the two phases ratify together.

### 2026-05-23 — Ratified (Ira)

All 6 PCDNs walked and resolved:

| PCDN | Resolution |
|---|---|
| **001 — Sub-chart reference syntax** | ✅ **`<sos:dispatch ref="..."/>`** custom element under the `xmlns:sos="https://softoboros.com/sos/1.0"` namespace established by SOS-09 PCDN-001. Explicit dispatch semantic, distinct from SCXML's external-state reference (which has ambiguous semantics in popular implementations). |
| **002 — Datamodel boundary declaration** | ✅ **Per-sub-chart `<sos:contract reads="..." writes="..."/>`** with explicit field lists. Implicit propagation only for `kind` enums covered by the parent's vocabulary. Per-field annotation gets noisy at scale; per-sub-chart with explicit reads/writes matches CSP's channel-explicit-interface convention. |
| **003 — Legibility threshold default** | ✅ **15 peer states default, project-overridable** via `--legibility-threshold N` flag and chart-level `<sos:legibility max="N"/>` annotation. 15 sits in the cognitive-load sweet spot for graphical review; teams in deep-domain charts can tighten. |
| **004 — Sub-chart contract syntax detail** | ✅ **Inline in sub-chart's SCXML** — root-level `<sos:contract>` element. Keeps each sub-chart self-describing in one artifact rather than fragmenting the spec across `.scxml` + `.contract.scjson` files. |
| **005 — Recursive depth limit** | ✅ **Capped at 8** with `--max-depth N` override. Anti-infinite-recursion guard; 8 covers any practical hierarchy with margin (protocol stacks typically 3-4 levels deep). |
| **006 — Contract-mismatch handling** | ✅ **Compile-time error**. Chart compiler refuses to emit code if a `<sos:dispatch>` references a sub-chart whose contract doesn't match the parent's expectations. Matches INV-SOS-G's verified-codegen discipline; runtime checks would defeat the verified-codegen story. |

Status: 🟢 **ratified**. SOS-12 implementation work (extending `tools/sos-codegen/` with the `<sos:dispatch>` walker + per-layer bound-composition + contract-matching verifier) unblocked. SOS-11's MCP tool surface adds `extract_region_to_subchart` and `inline_subchart` operations that emit SOS-12-shape `<sos:dispatch>` references on extraction.

### 2026-05-27 — SOS12A1: dispatch+contract parser landed (Ira)

Wave-1A of the SOS-12 implementation fan-out: `tools/sos-codegen/sos12_annotations.py` + `tools/sos-codegen/tests/test_sos12_annotations.py` (27 tests, all passing). The module reads a scjson 0.4.0 chart AST and emits a typed `DispatchInventory` covering:

- Every `<sos:dispatch ref="…"/>` element (PCDN-001 ratified shape; frozen attribute set `{"ref"}`; unknown attrs rejected per Standards Action).
- Every chart-root `<sos:contract>` element (PCDN-004 inline-in-SCXML shape) with `reads`/`writes` attributes (PCDN-002 per-sub-chart explicit-field-lists) plus `<sos:events-in>` / `<sos:events-out>` / `<sos:invariants>` sub-elements.
- Depth-cap enforcement (PCDN-005 / §6.5 / INV-S-DISP-5 — default 8, project-overridable via `max_depth` keyword).
- INV-S-DISP-3 acyclicity check at the parser layer (self-dispatch and cycle-via-loader caught with chart-author-friendly diagnostic).

The parser stops at parsing + structural validation. Bound-composition (Wave-1B / §6 algebra) and contract-matching (Wave-2 / §5.3 + INV-S-DISP-2) are scoped to subsequent waves; extension-point hooks are documented at the foot of the module.

### 2026-05-27 — SOS12C1: boundary-vector emitter landed (Ira)

Wave-1 implementation slice — the per-dispatch-edge boundary-vector emitter ships at `tools/sos-codegen/sos12_boundary_vectors.py` with 16 pytest tests at `tools/sos-codegen/tests/test_sos12_boundary_vectors.py`. The emitter realises §7.2 (boundary-vector emission) end-to-end:

- Constant-size vector set per edge: `|events_in| + |events_out| + |invariants_maintained| + |invariants_assumed|` records, NO replay across layers (INV-S-DISP-1 honoured by construction — no sub-chart-internal state references).
- INV-SOS-H metadata block (`chart_path` / `trigger` / `expected` / `originating_invariant`) on every vector.
- Sum-not-product realised at the tree-emitter surface (`emit_dispatch_tree_boundary_vectors`) per §6.3 INV-SOS-F.
- PCDN-SOS-12-006 contract-mismatch handling: compile-time error via `BoundaryVectorError` with `pcdn="PCDN-SOS-12-006"` and `invariant="INV-S-DISP-2"`.
- Vector-id shape `sos12-boundary-<parent>-<child>-NNNN` (4-digit zero-padded seq) mirrors SOS-09-F's `MV-<UUID>-<family>-<seq>` traceability convention.
- JSONL writer (`write_boundary_vectors_jsonl`) emits one record per line per SOS-03 §6 wire-format.

Wave-2 integration boundary: the local `SubChartContract` / `DispatchEdge` input dataclasses are placeholders for the ratified `sos12_annotations` walker outputs (sibling Wave-1 agent's deliverable). The constructor surface is stable; Wave-2 wiring is a constructor-level adapter.

### 2026-05-27 — SOS12B1: bound-composition algorithm landed (Ira)

Wave-1B fan-out: `tools/sos-codegen/sos12_bound.py` + `tools/sos-codegen/tests/test_sos12_bound.py` implement the §6.1-§6.4 bound-composition algebra as a pure-function module. Per-layer SUM (not Cartesian product) per INV-SOS-F + §6.3; SCXML `<parallel>`-style independence axes surface separately from sequential composition per §6.2 / §6.4; INV-S-DISP-5 (per-layer vector count is local) verified by property test. DAG enforcement per INV-S-DISP-3 (self + mutual + n-cycle rejection). Recursion depth cap default 8 per §6.5 + PCDN-SOS-12-005, project-overridable. Worked-example test pins §8.4 HTTP family bounds (47 for the 5-chart top + per-method-only family). 25 tests passing.

Wave-2 integrator wires the Wave-1A `DispatchInventory` (annotation parser) output into this module's `BoundInputs` shape; the integration boundary is documented in the module's top-of-file docstring.

### 2026-05-27 — SOS12I1: contract-matching verifier landed (Ira)

Wave-2 fan-out: `tools/sos-codegen/sos12_contract_match.py` + `tools/sos-codegen/tests/test_sos12_contract_match.py` (25 tests, all passing) implement the §5.3 contract-matching algebra as a PCDN-SOS-12-006 compile-time gate. Per INV-S-DISP-2 every dispatch boundary now has a callable contract-match check; the verifier is the operational artifact that makes "contract-matching is mandatory" a compile-time property rather than aspirational prose.

The module exposes:

- `verify_contract_match(edge: DispatchContractEdge) -> None` — pure-function single-edge check; raises `ContractMismatchError` (carrying `pcdn="PCDN-SOS-12-006"`, `invariant="INV-S-DISP-2"`, frozen `clause` enum, `missing`/`extra` sets, INV-SOS-H `chart_path`) on the first failing clause.
- `verify_inventory(inventory, *, edge_provider=simple_edge_provider) -> None` — depth-first walker over the Wave-1A `DispatchInventory` tree; first-failure halts traversal with the failing edge's chart_path naming the exact dispatch site.
- `simple_edge_provider` — reference adapter deriving per-dispatch parent expectation from the parent chart's own `<sos:contract>` (the §5.2 four-set algebra applied at the chart level; adequate for single-dispatch charts, documented limitation for multi-dispatch).

Six §5.3 clauses verified: `events_in`, `events_out`, `invariants_assumed`, `reads`, `writes` as strict set-membership checks against parent-side expectations; `invariants_maintained` as a documented v1 no-op pending invariant-grammar ratification (§14 non-goal). Clause enum is Standards Action — adding a clause needs §15 amendment.

Wave-3 extension points reserved at the module foot: Wave-3 J (`extract_region_to_subchart`) wires this verifier as the discharge gate after extraction; Wave-3 K (`inline_subchart`) calls it in reverse before allowing inline. Both consumers operate on `DispatchContractEdge` records the SOS-11 MCP tool already has materialised, so no inventory walk is needed at the tool-call boundary.

Spec ambiguity resolved by interpretation: §5.2 does not pin write-before-read ordering precisely (it states the four-set algebra but defers structural enforcement to the parent's reachability analysis). The v1 verifier checks set-membership only (`child.reads ⊆ parent.writes_before_dispatch`; `child.writes ⊆ parent.reads_after_dispatch`); the ordering check is delegated to the parent's per-layer reachability vectors (SOS-03 §6.1) plus the SOS-12 §7.2 boundary vectors at dispatch entry. Documented in `_check_reads` / `_check_writes` docstrings.

### 2026-05-27 — Boundary-vector `kind` field plural/singular convention (ERRATA-005) (Ira)

**Originating drift.** The SOS-03 §15 vector-framework extension landed in commit `cdc7f85` ("SOS03-09/12-W2O: §15 vector-framework extensions (Membrane + Boundary categories)") documented two distinct shapes for the boundary-vector subtype vocabulary — the SOS-12 §5.1 contract-field names in plural form (`events_in`, `events_out`, `invariants_maintained`, `invariants_assumed`) and the per-record `kind` field emitted by [`tools/sos-codegen/sos12_boundary_vectors.py`](../../tools/sos-codegen/sos12_boundary_vectors.py) in MIXED form (plural for events: `events_in` at line 323, `events_out` at line 371; singular for invariants: `invariant_maintained` at line 422, `invariant_assumed` at line 454). The SOS-03 §15 "Implementation note on plural-vs-singular" paragraph names both shapes as normative and explains the per-record-vs-class-of-vectors split, but the SOS-12 doc itself did not previously codify the convention. ERRATA-005 records the drift; this amendment closes it inside SOS-12's own surface.

**Resolution — convention (normative).** The plural/singular split is **intentional** and grounded in cardinality semantics:

- **Contract-field names are plural** — they name SETS of events or invariants. The four contract-field names per [§5.1 sub-chart contract shape](#51-sub-chart-contract-shape) are `events_in`, `events_out`, `invariants.maintained_by_subchart`, `invariants.assumed_of_environment`; the §7.2 boundary-vector class-of-vectors names collapse the latter two to `invariants_maintained` and `invariants_assumed` for symmetry with the event-side names. All four are **plural** because each names a set.
- **Per-record `kind` field values follow cardinality**:
  - **Events**: per-record `kind` is **plural** (`events_in`, `events_out`) — each emitted record covers exactly one event drawn from its named set, but the `kind` value names the SET the event was drawn from, not the singular event. This matches the emitter's vector-id construction (one record per event in the set) where the cardinality information lives in the per-record `trigger` field, not in `kind`.
  - **Invariants**: per-record `kind` is **singular** (`invariant_maintained`, `invariant_assumed`) — each emitted record covers exactly one invariant, and the `kind` value names the per-record invariant directly. This matches the emitter's vector construction where the `originating_invariant` metadata field carries the specific invariant id.

The split is grandfathered from the SOS12C1 emitter's 2026-05-27 implementation; the v1 emitter is the source of truth for the as-built shape, and this amendment ratifies that shape rather than re-mapping it. Future SOS-12 / SOS-03 amendments MAY collapse to a single form (all-plural or all-singular) if downstream readers report confusion; v1 keeps the as-built mixed shape.

**Frozen-enumeration registration policy.** The four boundary-vector subtype names (`events_in`, `events_out`, `invariants_maintained`, `invariants_assumed` at the §7.2 class-of-vectors level) remain **Standards Action** per the SOS-03 §15 W2O amendment's "frozen-enumeration registration policy for the four boundary-vector subtype set: Standards Action" clause. The per-record `kind` field values (plural events, singular invariants) are derived from the §7.2 subtypes by the emitter; changing the per-record shape is a co-amendment to BOTH this §15 entry AND the SOS-03 §15 W2O Part B subtype table.

**No spec text in §7.2 is modified by this amendment.** §7.2's enumeration of the boundary-vector classes remains as authored (four bullet points, plural names). This amendment adds the convention explicitly so that future implementers reading §7.2 + the emitter side-by-side do not misread the plural-vs-singular mismatch as drift.

**Cross-references.**

- ERRATA log entry: [ERRATA-005](./ERRATA.md#errata-005--sos-12-boundary-vector-kind-field-pluralsingular-drift) — names the drift and pins it to discovery commit `cdc7f85`.
- SOS-03 §15 W2O amendment Part B (commit `cdc7f85`) — the "Implementation note on plural-vs-singular" paragraph + the four-subtype table where the `kind`-field column names the as-emitted shape. This amendment ratifies the convention in SOS-12's own surface; SOS-03's table remains the cross-phase reference.
- Emitter pins: `tools/sos-codegen/sos12_boundary_vectors.py` lines 323 (`events_in`), 371 (`events_out`), 422 (`invariant_maintained`), 454 (`invariant_assumed`) — the canonical per-record `kind` values.
- Contract-field shape: [§5.1 sub-chart contract shape](#51-sub-chart-contract-shape) — the four plural contract-field names this amendment ratifies as the §7.2 class-of-vectors names.

Status: 🟢 **ratified**. The plural/singular convention is now codified inside SOS-12; the SOS12C1 emitter's as-built shape is canonical; no implementation change is owed.

### 2026-05-27 — SOS12L1: legibility + depth-cap lint landed (Ira)

Wave-3 SOS-12 implementation fan-out, slice L. The two SOS-12 frozen thresholds now have a chart-validation-time lint surface at [`tools/sos-codegen/sos12_lint.py`](../../tools/sos-codegen/sos12_lint.py), exposing two pure-function rules with `LintDiagnostic` records as output:

- `check_dispatch_depth(chart_path, *, max_depth=DEFAULT_MAX_DEPTH, loader=None)` — implements **SCXML-LINT-DISP-1** per [§6.5 + §10.3 + PCDN-SOS-12-005](#65-recursive-depth-bound). Rejects any chart whose `<sos:dispatch>` recursion exceeds the configured cap (default 8). The lint rule wraps the existing [`sos12_annotations.parse_dispatch_annotations`](../../tools/sos-codegen/sos12_annotations.py) depth-walk and translates its §6.5 `Sos12AnnotationError` into a chart-author-facing diagnostic.

- `check_legibility(chart_path, *, legibility_threshold=DEFAULT_LEGIBILITY_THRESHOLD, loader=None)` — implements **SCXML-LINT-DISP-2** per [§9 + §10.2 + PCDN-SOS-12-003](#9-sos-11-integration--legibility-as-discipline). Counts peer states (the union of `<state>` + `<parallel>` immediate children) at each level of the chart and rejects any level whose count exceeds the configured threshold (default 15). The diagnostic message **recommends `extract_region_to_subchart`** (the [SOS-11 §5.1](./SOS-11-CONCEPTS.md) MCP tool) per the [§9.2 tool-surface behaviour clause](#92-sos-11-tool-surface-behaviour-at-the-threshold) — this is the operational realisation of [§9](#9-sos-11-integration--legibility-as-discipline)'s "discipline becomes a property the tooling enforces" intent.

**Rule-id registration.** Both rules are registered in the SOS-01 [`LintRuleId`](./SOS-01-CONCEPTS.md#55-lintruleid--standards-action) namespace under the `SCXML-LINT-DISP-N` category-prefix series. The series was **reserved** by the [SOS-01 §15 SOS01-09-W2N amendment (commit `4f33c1e`)](./SOS-01-CONCEPTS.md) — see the "Future SOS-12 lint family (informative)" paragraph that pre-allocated the namespace shape; the reservation has now been filled by the co-landed [SOS-01 §15 SCXML-LINT-DISP-{1,2} amendment (this Wave-3L commit)](./SOS-01-CONCEPTS.md) that registers the two rule ids in the catalog. Per the category-prefix-convention precedent established by the `SCXML-LINT-CH-N` family, the implementation lives in `tools/sos-codegen/` next to the semantics owner module (not in a shared lint runner).

**Defaults source-of-truth.** The `DEFAULT_MAX_DEPTH = 8` and `DEFAULT_LEGIBILITY_THRESHOLD = 15` constants in `sos12_lint.py` mirror the ratified PCDN values; both rules accept project-level overrides via the keyword argument surface (mirroring the [§9.1](#91-threshold-default--enforcement) / [§6.5](#65-recursive-depth-bound) chart-family override path).

**Runtime safety net retained.** [`tools/sos-codegen/sos12_bound.py`](../../tools/sos-codegen/sos12_bound.py) (Wave-1B `SOS12B1`) independently enforces the same depth cap inside the bound-composition algorithm at vector-emission time. The two checks coexist intentionally: SCXML-LINT-DISP-1 catches the bug earlier at chart-validation time (with a chart-author-facing diagnostic naming the offending dispatch site), while `sos12_bound.py` provides a deeper safety net at the codegen pipeline's vector-emission stage. The lint rule does NOT modify or supersede `sos12_bound.py`; the bound module stays as the downstream backstop.

**Test count.** [`tools/sos-codegen/tests/test_sos12_lint.py`](../../tools/sos-codegen/tests/test_sos12_lint.py) ships 21 tests, all passing:

- 1 frozen-defaults sanity test.
- 7 SCXML-LINT-DISP-1 tests (depth 7 pass; depth 8 at-cap pass; depth 9 fail; custom `max_depth=4` with depth 5 fail; custom `max_depth=4` with depth 4 pass; no-dispatches pass; missing-chart-path `FileNotFoundError`).
- 9 SCXML-LINT-DISP-2 tests (15 peers at threshold pass; 16 peers fail; message cites §9 + PCDN-SOS-12-003; nested 16-peer breach at depth 3 names the correct location; custom `legibility_threshold=5` with 6 peers fail; custom threshold with 5 peers pass; threshold=0 `ValueError`; two breaching levels yield two diagnostics; `<parallel>` regions counted as peers).
- 4 fixture-driven integration tests (skip cleanly when scjson is unavailable): existing 8-deep fixture passes; existing 9-deep overflow fixture fails; single-level dispatch fixture passes legibility; the `extract_region_to_subchart` recommendation appears verbatim in the legibility-breach diagnostic per the §9.2 normative requirement.

Regression sweep across all `tools/sos-codegen/tests/test_sos12_*.py` (114 tests including the 93 from prior Wave-1A/1B/1C/2 landings + the 21 new tests) is clean.

**Spec-text resolution on `<parallel>` peer-counting (informative).** §9.1 does not explicitly nail down what "peer states at one level" means in a chart containing `<parallel>` regions. The implementation interprets a `<parallel>` element's region children as peer states OF EACH OTHER (i.e. a `<parallel>` with 16 region children breaches the threshold at the parallel's own level), AND each region's own children are counted at the next level down (a region with 16 child states breaches at that region's level). This matches the "legible-at-every-individual-level" intuition of §9 — a `<parallel>` with too many regions is just as hard to read as a `<state>` with too many children. If a future chart-author reading suggests the parallel's regions should NOT count as peers (because they execute concurrently and are intuitively "parallel slices" rather than "alternatives"), a §15 amendment would refine the counting policy; the v1 lint codifies the conservative interpretation that catches the visual-clutter failure mode.

**Cross-references.**

- [SOS-01 §15 (2026-05-27 SCXML-LINT-DISP-{1,2})](./SOS-01-CONCEPTS.md) — the reciprocating SOS-01 amendment that registers the two rule ids in the `LintRuleId` namespace.
- [SOS-01 §15 (2026-05-27 SOS01-09-W2N)](./SOS-01-CONCEPTS.md) — the originating reservation of the `SCXML-LINT-DISP-N` category-prefix series.
- [§6.5 — recursive depth bound](#65-recursive-depth-bound) + [§10.3](#103-recursion-depth-bound) + PCDN-SOS-12-005 — depth-cap default.
- [§9 — SOS-11 integration — legibility-as-discipline](#9-sos-11-integration--legibility-as-discipline) + [§9.2](#92-sos-11-tool-surface-behaviour-at-the-threshold) + [§10.2](#102-legibility-threshold) + PCDN-SOS-12-003 — legibility threshold default + tool-surface behaviour.
- [`tools/sos-codegen/sos12_bound.py`](../../tools/sos-codegen/sos12_bound.py) — the downstream safety-net depth-cap check (Wave-1B SOS12B1).
- [`tools/sos-codegen/sos12_annotations.py`](../../tools/sos-codegen/sos12_annotations.py) — the dispatch-tree walker SCXML-LINT-DISP-1 consumes.

Status: 🟢 **ratified**. The two frozen SOS-12 thresholds now have callable lint surfaces; the SOS-11 `extract_region_to_subchart` MCP tool is named in every SCXML-LINT-DISP-2 diagnostic per §9.2; no further implementation work is owed for the two ratified thresholds at v1. SOS-12 stays 🟢 ratified.

### 2026-05-27 — SOS12U7: §8.4 HTTP worked-example chart landed (Ira)

The §8.4 HTTP-family worked example is now an on-disk SCXML chart family at [`tools/sos-codegen/tests/fixtures/sos_12/http/`](../../tools/sos-codegen/tests/fixtures/sos_12/http/). The fixture set materialises what Wave-1B's [`test_sos12_section_8_4_http_worked_example_bounds`](../../tools/sos-codegen/tests/test_sos12_bound.py) pinned synthetically: the 5-chart family (1 top + 4 per-method) whose `composed_bound` is exactly **47** under §6.3 sum-not-product composition.

**Fixture family.** Five SCXML files materialise the §8.1–§8.5 narrative:

- [`http_top.scxml`](../../tools/sos-codegen/tests/fixtures/sos_12/http/http_top.scxml) — 8 reachable states per §8.1 (`idle`, `awaiting_request_line`, `dispatching_get`, `dispatching_post`, `dispatching_put`, `dispatching_delete`, `dispatching_unknown_method`, `responding`). Four states carry `<sos:dispatch>` elements pointing at the per-method sub-charts; `dispatching_unknown_method` is a no-op pass-through per §8.1.
- [`http_get.scxml`](../../tools/sos-codegen/tests/fixtures/sos_12/http/http_get.scxml) — 5 reachable states matching `bound(http_get) = 5` per §8.4.
- [`http_post.scxml`](../../tools/sos-codegen/tests/fixtures/sos_12/http/http_post.scxml) — 15 reachable states matching `bound(http_post) = 15` per §8.4. Sits **exactly at** the §9.1 / PCDN-SOS-12-003 default legibility threshold per the §8.5 narrative ("a 16th peer state will fail lint until the author factors via `extract_region_to_subchart`"). The 15-state count is the load-bearing case for SCXML-LINT-DISP-2's `peer_count > threshold` breach predicate (`>`, not `≥`) — the fixture proves the boundary case admits cleanly.
- [`http_put.scxml`](../../tools/sos-codegen/tests/fixtures/sos_12/http/http_put.scxml) — 12 reachable states matching `bound(http_put) = 12` per §8.4.
- [`http_delete.scxml`](../../tools/sos-codegen/tests/fixtures/sos_12/http/http_delete.scxml) — 7 reachable states matching `bound(http_delete) = 7` per §8.4.

Each per-method sub-chart declares a root-level `<sos:contract>` per PCDN-SOS-12-004 with `reads` / `writes` attributes per PCDN-SOS-12-002 and the three sub-elements (events-in / events-out / invariants) per §5.1. Per §8.3 the per-handler decomposition is **deferred** at v1 — the 47-vector pin specifically covers the 5-chart top + per-method shape.

**Integration test.** [`tools/sos-codegen/tests/test_sos12_http_worked_example.py`](../../tools/sos-codegen/tests/test_sos12_http_worked_example.py) threads the chart family end-to-end through every ratified SOS-12 module:

1. **Annotations parsing** ([`sos12_annotations.parse_dispatch_annotations`](../../tools/sos-codegen/sos12_annotations.py)) — verifies the 4-dispatch top-level + 4 depth-1 sub-inventories each carrying a parsed contract.
2. **Bound composition** ([`sos12_bound.compose_bound`](../../tools/sos-codegen/sos12_bound.py)) — verifies `composed_bound == 47` and 4 single-member None-axis independence axes, matching the Wave-1B pin exactly.
3. **Boundary-vector emission** ([`sos12_boundary_vectors.emit_dispatch_tree_boundary_vectors`](../../tools/sos-codegen/sos12_boundary_vectors.py)) — verifies the per-§7.2 sum-across-edges yields 31 boundary vectors (GET 6 + POST 9 + PUT 9 + DELETE 7 — each per-edge count being the constant `|events_in| + |events_out| + |invariants_maintained| + |invariants_assumed|`) and that every vector carries an INV-SOS-H `chart_path` metadata pointing at the originating dispatch edge.
4. **Contract matching** ([`sos12_contract_match.verify_inventory`](../../tools/sos-codegen/sos12_contract_match.py)) — verifies all 4 parent → child contract pairs pass `verify_contract_match` under a custom per-dispatch `edge_provider` (the default `simple_edge_provider` is inadequate for a multi-dispatch parent per its own docstring; the custom provider derives parent-side expectations from each child's contract as the minimal-conforming shape).
5. **Lint** ([`sos12_lint.check_dispatch_depth`](../../tools/sos-codegen/sos12_lint.py) + `check_legibility`) — both at default thresholds pass: depth-1 ≤ 8 cap; every chart ≤ 15 peers (http_post at exactly 15 admits per the `>` breach predicate).

**Adapter shape.** `DispatchInventory` (Wave-1A) and `BoundInputs` (Wave-1B) are different data shapes; this test ships an inline private helper `_inventory_to_bound_inputs` (≈30 LOC) that walks the inventory and counts top-level `<state>` peer children per chart. The HTTP fixtures are intentionally flat (no nested `<state>`) so peer-count equals reachable-state count; a future Wave-5 may lift this adapter into a shared integration module if a second consumer materialises. A similar inline `_inventory_to_boundary_edges` adapts the inventory to `sos12_boundary_vectors.DispatchEdge` records, and a `_per_dispatch_edge_provider` plays the same role for contract-match — keeping the multi-dispatch case correct without coupling it to the v1 `simple_edge_provider`.

**Spec ambiguity surfaced.** §8.1 narrates 8 top-level states but does not name which states own dispatches. The fixture interpretation (4 of the 5 `dispatching_<METHOD>` states own dispatches; `dispatching_unknown_method` is a no-op pass-through) matches Wave-1B's pin of 4 single-member independence axes; no §15 amendment is needed.

**Test count.** 8 new tests in `test_sos12_http_worked_example.py` all passing; regression sweep across `tools/sos-codegen/tests/test_sos12_*.py` clean at **122 tests** (114 from prior landings + 8 new). The §8.4 worked example is now a verified-end-to-end fixture, not an informative narrative pin.

**Cross-references.**

- [§8.1](#81-top-level-dispatch-chart-http_topscxml) / [§8.2](#82-per-method-sub-charts) / [§8.4](#84-bound-composition-for-the-family) / [§8.5](#85-legibility-as-discipline-check) — the informative HTTP narrative the fixture materialises.
- [`tools/sos-codegen/tests/test_sos12_bound.py::test_sos12_section_8_4_http_worked_example_bounds`](../../tools/sos-codegen/tests/test_sos12_bound.py) — Wave-1B's synthetic 47-vector pin; this fixture is the on-disk SCXML companion.
- [`tools/sos-codegen/sos12_annotations.py`](../../tools/sos-codegen/sos12_annotations.py) (Wave-1A SOS12A1) — annotation parser.
- [`tools/sos-codegen/sos12_bound.py`](../../tools/sos-codegen/sos12_bound.py) (Wave-1B SOS12B1) — bound-composition algebra.
- [`tools/sos-codegen/sos12_boundary_vectors.py`](../../tools/sos-codegen/sos12_boundary_vectors.py) (Wave-1C SOS12C1) — boundary-vector emitter.
- [`tools/sos-codegen/sos12_contract_match.py`](../../tools/sos-codegen/sos12_contract_match.py) (Wave-2 SOS12I1) — contract-matching verifier.
- [`tools/sos-codegen/sos12_lint.py`](../../tools/sos-codegen/sos12_lint.py) (Wave-3L SOS12L1) — depth + legibility lint.

Status: 🟢 **ratified**. The §8.4 worked example has graduated from narrative-only to verified-on-disk fixture; SOS-12 stays 🟢 ratified.

### 2026-05-27 — SOS12B-PCDN-008: parallel-region peer-counting configurable

Wave-5 SOS-12 ratification, slice B. Multi-PCDN session on 2026-05-27 surfaced an ambiguity in the SCXML-LINT-DISP-2 spec text first noted by the Wave-3L SOS12L1 §15 entry above ("Spec-text resolution on `<parallel>` peer-counting (informative)" paragraph): §9.1 does not nail down whether a `<parallel>` element's region children should count as peer states at the parallel's own level. The Wave-3L implementation chose the conservative interpretation (count them — strict mode), and that choice has now been **ratified as the default** alongside an opt-out for chart families whose regions are intuitively concurrent slices rather than alternatives.

**User ratification (2026-05-27).** Option (c) — configurable per project via rule keyword. The user's reasoning: the strict default catches the visual-clutter failure mode the original PCDN-SOS-12-003 walkthrough was aimed at, AND a non-trivial class of chart families (those whose `<parallel>` regions encode concurrent slices rather than alternative branches) reads the count differently and SHOULD have a clean opt-out. A single global mode would either silently regress one of the two reading communities or force them to mutate the threshold to a contrived value.

**Kwarg surface.** [`tools/sos-codegen/sos12_lint.py`](../../tools/sos-codegen/sos12_lint.py) `check_legibility` now accepts:

```
check_legibility(chart_path, *,
    legibility_threshold: int = DEFAULT_LEGIBILITY_THRESHOLD,
    count_parallel_regions: bool = True,
    loader: Callable[[Path], dict] | None = None,
) -> list[LintDiagnostic]
```

- **`count_parallel_regions=True`** (default, strict). The Wave-3L semantics. A `<parallel>` with N region children breaches the threshold at the parallel's OWN level when N > `legibility_threshold` (each region is a peer state of every other region). Behaviour-preserving — no existing caller observes a regression.
- **`count_parallel_regions=False`** (liberal). The `<parallel>`'s region children do NOT count as peers at the parallel's own level; the threshold check is skipped for the parallel itself. The `<parallel>` ITSELF still counts as one peer at its parent's level (this is unchanged — a parent with 16 `<parallel>` children still breaches). Each region's own children are counted at the next level down regardless of mode — the opt-out applies AT the parallel's level, not below it.

**Disambiguation: what "peer" means under `count_parallel_regions=False`.** "Peer states at a level" still means the union of immediate `<state>` + `<parallel>` children of the level's owner node, but the threshold-breach predicate is gated: when the level's owner is a `<parallel>` and the kwarg is `False`, the predicate evaluation is skipped at that level only. The recursive descent into each region (each region IS itself a `<state>`) still happens, and within a region the strict-mode rules apply unmodified. The opt-out narrows what triggers a diagnostic; it does NOT redefine "peer state" anywhere in the chart tree.

**Frozen-enumeration policy.** **Specification Required** for the keyword's existence and default per the SOS-12 §10 registration-policy convention (this matches the policy already in force for the `legibility_threshold` integer kwarg). Changing the default flip would silently re-classify every existing caller and is prohibited without a §15 amendment. **Standards Action** for adding a third counting mode (e.g. a hypothetical `"weighted"` mode that counts regions at a discount factor, or a `"region_count_at_parent_level"` mode that hoists region peers up one level) — a third mode encodes an additional invariant interpretation across phases and the §15 ratification cycle is the right place to debate it.

**Tests added.** [`tools/sos-codegen/tests/test_sos12_lint.py`](../../tools/sos-codegen/tests/test_sos12_lint.py) ships four new tests covering the kwarg surface:

- `test_disp2_count_parallel_regions_default_is_strict` — asserts the keyword exists, is keyword-only, and defaults to `True` (the Specification-Required default).
- `test_disp2_liberal_mode_admits_parallel_with_16_regions` — a `<parallel>` with 16 region children passes under `count_parallel_regions=False`.
- `test_disp2_strict_mode_rejects_parallel_with_16_regions` — the same shape fails under the strict default (both implicit and explicit `count_parallel_regions=True`).
- `test_disp2_liberal_mode_still_rejects_alternatives_inside_region` — a region carrying 16 `<state>` alternatives still breaches at the region's level under liberal mode (the opt-out applies AT the parallel, not below it).

Test count climbs from 21 → 25 in `test_sos12_lint.py`; the regression sweep across `tools/sos-codegen/tests/test_sos12_*.py` + `tools/sos-codegen/tests/test_sos11_*.py` remains clean at 263 tests.

**Reciprocating SOS-01 amendment.** [SOS-01 §15 (2026-05-27 SCXML-LINT-DISP-2 kwarg amendment)](./SOS-01-CONCEPTS.md) records the new kwarg surface in the SOS-01 lint catalog. SOS-12 stays the semantics owner; SOS-01 records the implementation-pin update.

**Cross-references.**

- [SOS-12 §15 (2026-05-27 SOS12L1)](#2026-05-27--sos12l1-legibility--depth-cap-lint-landed-ira) — the originating Wave-3L lint landing whose "Spec-text resolution on `<parallel>` peer-counting" paragraph surfaced the ambiguity this amendment resolves.
- [SOS-12 §9 — SOS-11 integration — legibility-as-discipline](#9-sos-11-integration--legibility-as-discipline) + [§9.1](#91-threshold-default--enforcement) + [§10.2](#102-legibility-threshold) — the threshold's normative authority chain (default unchanged).
- [SOS-01 §15 (2026-05-27 SCXML-LINT-DISP-2 kwarg amendment)](./SOS-01-CONCEPTS.md) — the reciprocating SOS-01 catalog update.
- [`tools/sos-codegen/sos12_lint.py`](../../tools/sos-codegen/sos12_lint.py) `check_legibility` — the implementation pin.

Status: 🟢 **ratified**. The kwarg surface lands behaviour-preserving (default `True`); chart families that want the liberal interpretation opt in per call. SOS-12 stays 🟢 ratified.
