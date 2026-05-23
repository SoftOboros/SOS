# SOS-08-H — Cooperative-only scheduling (v1 ratification of an explicit non-feature)

**Status:** 🟢 **ratified 2026-05-23** (see §15).

## 0. Authority policy

This phase doc is the **dedicated non-feature ratification** sub-phase under the SOS-08 umbrella (`SOS-08-CONCEPTS.md`, ratified 2026-05-23). The umbrella's §5.2 freezes "v1 HDL emission is cooperative only" and INV-S-HDL-4 names the invariant; SOS-08-H is where the design rationale, the constraints that flow from the choice, and the v2 trigger criteria land.

By design SOS-08-H is the **shortest** of the SOS-08 sub-phase docs. Its job is to ratify a deliberate non-feature — preemption is out of scope at v1 — and to record enough rationale that the choice is reviewable later without a second history-archaeology pass. Every load-bearing section is here; nothing else is.

Per the parent CLAUDE.md "Spec-Before-Code Planning Discipline / Phase document shape":

- **Normative** sections of this doc: §3 glossary, §4 source-of-truth map, §5 frozen non-feature, §6 design-space rationale (the "why we did not pick preemption" argument), §7 chart-author + codegen-tool obligations, §9 v2 trigger criteria, §10 reconciliation, §12 acceptance checklist.
- **Informative** sections: §1 purpose, §2 problem statement, §11 non-goals, §15 change log.
- All keywords MUST, MUST NOT, SHALL, SHOULD, SHOULD NOT, MAY, RECOMMENDED are interpreted per RFC 2119 / RFC 8174 when capitalised.

This doc cites SOS-07 §6 cross-phase invariants and SOS-08 §7 cross-sub-phase invariants (specifically INV-S-HDL-4). Neither set is re-derived. EOQ-008-ROADMAP resolution (`SOS-ROADMAP-07-PLUS.md` §6) is the upstream ratification that this sub-phase concretizes.

## 1. Purpose

To ratify, as a named phase deliverable, the explicit non-feature that v1 SOS HDL emission has **no preemption**, and to record:

1. The rationale — why the three available preemption-in-HDL implementation paths each fail the v1 adoption story.
2. The constraints this non-feature imposes on chart authors and on SOS-08-C's chart→FSM emitter.
3. The escape hatches that remain available *without* preemption (cooperative `task.yield`, orthogonal regions, interrupt-driven event-source ingestion).
4. The v2 trigger criteria — at what concrete user case the question reopens.

Without this sub-phase doc, the cooperative-only choice lives only as a one-line freeze in SOS-08 §5.2 plus an invariant name; the design rationale and the chart-author discipline checklist have nowhere to land. The downstream phases (SOS-08-C emitter, SOS-08-D/E vector emitters, SOS-13 verified-strip) need a citable source for the cooperative-only obligation. This is that source.

## 2. Problem statement

Three observations motivate ratifying cooperative-only as its own normative deliverable rather than leaving it as a one-line freeze in the umbrella:

1. **Preemption is a design-space, not a feature.** The three architectural paths (shadow register files; chart-annotated save-points; hardware-interrupt-driven context switch) have radically different cost surfaces — area, complexity, timing-budget-fragility — and a different chart-author-facing contract surface each. Choosing "not preemption" without saying which preemption was rejected leaves the rationale opaque to future reviewers and to any v2 reopening.

2. **The non-feature has downstream consequences that need citation handles.** SOS-08-C's emitter MUST NOT emit save/restore logic; SOS-08-D's cocotb tests MUST NOT assume preemption semantics; chart authors targeting HDL MUST design within cooperative-only RTC bounds. Each of those obligations needs a normative source to cite; without this doc they would cite SOS-08 §5.2 ("frozen, see umbrella") which has no rationale to back the citation.

3. **The v2 reopening question is real.** Sub-microsecond interrupt handling in safety-critical paths *is* a genuine use case; SOS deferring it indefinitely is not the same as SOS claiming it does not exist. The trigger criteria — at what user case the question reopens — are themselves a load-bearing ratification, because absent them a v2 reopening becomes a renegotiation of the whole rejection rationale rather than a triggered amendment.

## 3. Canonical glossary

Terms normative within SOS-08-H+. Authority relationships per SOS-08 §8 and SOS-07 §7.

| Term | Definition |
|---|---|
| **Cooperative-only scheduling** | As defined in `SOS-08-CONCEPTS.md` §3 (Layer-0 glossary, "cooperative-only scheduling"); used without modification. The v1 HDL emission discipline: FSMs run to completion within a single chart macrostep; there is no save/restore mechanism; the next macrostep begins only after the current macrostep quiesces. |
| **Preemption** | An external event (typically an interrupt, but generally any higher-priority transition) causes an in-progress FSM transition body to halt mid-execution, the in-flight context to be saved, and a different transition body to run; the original transition body resumes from its save-point afterward. **Owned by SOS-08-H; does not exist in repo yet** — SOS today does not emit any preemption mechanism at any target. |
| **Macrostep** | One SCXML semantic step: process queued events, fire enabled transitions in document order, run on-entry/on-exit and transition bodies, reach quiescence. As used in SCXML 1.0 §3.13; this doc references that definition unmodified. |
| **Run-to-completion (RTC)** | The SCXML semantic that a macrostep is atomic from the chart-author's perspective: no other event interleaves with the in-progress macrostep. SCXML enforces this naturally; SOS-08-H's cooperative-only ratification at v1 means the HDL emission preserves this without machinery (no preemption == no need to save/restore). |
| **Shadow register file** | A duplicate of every FSM state register, kept "in reserve" so a preempting transition can save the current register state in one cycle and the preempted transition can restore it in one cycle. N-level preemption needs N shadow register files. Area cost: ~N× the FSM state register area. |
| **Chart-annotated save-point** | A chart-author-declared point inside a transition body at which the transition body MAY be interrupted; the chart compiler emits explicit save/restore logic at that point, with chart-authored semantics for which subset of the chart's internal state is preserved. Complexity cost: the chart author must reason about preemption semantics. |
| **Hardware-interrupt-driven context switch** | The CPU-style preemption analog: an external interrupt signal causes the FSM scheduler to swap which FSM is "running" (in the sense of advancing its state register). Requires a scheduler microarchitecture distinct from the per-region one-FSM-per-region model SOS-08-C is otherwise free to emit. Timing-budget cost: a cycle-accurate interrupt latency budget that must hold across synthesis, place-and-route, and silicon variation. |
| **`task.yield`** | A cooperative chart event the FSM emits to signal "I am at a clean RTC boundary; another FSM may run now". NOT a preemption mechanism: the yield is the FSM saying so itself, not an external force. The chart author owns the yield placement. |
| **v2 trigger** | A concrete user case (named in §9) the satisfaction of which reopens the cooperative-only ratification for amendment. Absent a v2 trigger, this ratification is the source of truth indefinitely. |

## 4. Source-of-truth map

| Concept | Authority |
|---|---|
| Cooperative-only scheduling (definition) | `SOS-08-CONCEPTS.md` §3 (umbrella, **mirror** here) |
| INV-S-HDL-4 (cooperative-only at v1) | `SOS-08-CONCEPTS.md` §7 (umbrella, cited not redefined) |
| EOQ-008-ROADMAP resolution | `SOS-ROADMAP-07-PLUS.md` §6 (informative source; this doc concretizes the resolution as a normative phase deliverable) |
| Macrostep + run-to-completion semantics | W3C SCXML 1.0 §3.13 (**mirror** — cited, not redefined) |
| Preemption design-space rationale | **this doc** (§6) |
| Chart-author obligations under cooperative-only | **this doc** (§7.1) |
| Codegen-tool obligations under cooperative-only | **this doc** (§7.2) |
| Escape-hatches available without preemption | **this doc** (§7.3) |
| v2 trigger criteria | **this doc** (§9) |
| Cross-phase invariants INV-SOS-A through H | `SOS-07-CONCEPTS.md` §6 (cited, not redefined) |
| Cross-sub-phase invariants INV-S-HDL-1 through 5 | `SOS-08-CONCEPTS.md` §7 (cited, not redefined) |

## 5. Frozen non-feature

**v1 SOS HDL emission has no preemption mechanism.**

Concretely:

- (a) The SOS-08-A L0 primitive library has no preemption-supporting primitive (no shadow-register-file primitive, no context-switch arbiter).
- (b) The SOS-08-B L1 service library exposes no preemption-supporting service (no "preempt this task" verb).
- (c) The SOS-08-C chart→FSM emitter MUST NOT emit save/restore logic for any chart region.
- (d) The SOS-08-D / E / F vector emitters MUST NOT assume preemption semantics (no test asserts "after preemption, the preempted task resumes from its save-point").
- (e) Chart regions targeting HDL emission MUST be cooperatively designable: every transition body completes within one macrostep boundary; no in-transition yielding via a preemption mechanism.

The frozen non-feature is INV-S-HDL-4 (SOS-08 §7). This doc records the rationale + obligations; SOS-08 §7 records the invariant name.

Frozen-enumeration registration policy: **Standards Action**. Re-opening the cooperative-only ratification requires a §15 amendment to this doc + a coordinated §15 amendment to the SOS-08 umbrella's INV-S-HDL-4 + a v2 trigger satisfaction per §9.

## 6. Design-space rationale (the "why we did not pick preemption" argument)

Three preemption-in-HDL implementation paths are technically available; each fails the v1 adoption story for a distinct reason.

### 6.1 Shadow register files (area-expensive)

A shadow register file is a duplicate of every FSM state register. N-level preemption (the FSM can be preempted N deep before returning to its outermost transition body) requires N shadow files. Area cost scales as ~N× the FSM state register area.

For the Lattice ECP5 first-target (per SOS-08 PCDN-006 resolution + EOQ-004-ROADMAP), a moderate chart's FSM state-register area is already a meaningful fraction of the device's flip-flop budget; doubling or tripling it for preemption capability that no v1 chart needs is the wrong trade-off. ASIC tape-out targets have the area headroom but no v1 ASIC target is on the roadmap.

The deeper objection: shadow register files make sense when the preempted-and-resumed task is the common case. For SOS's RTOS-on-HDL story, transition bodies are short (chart-author-discipline keeps them so; SOS-12's legibility-as-discipline integration reinforces this); preemption is the rare case. Paying N× area for a rare case inverts the cost/benefit.

### 6.2 Chart-annotated save-points (complexity-expensive)

A chart-annotated save-point lets the chart author declare `<state preemptible="true" save="x,y,z"/>` (hypothetical syntax) at points where the transition body MAY be interrupted. The chart compiler emits explicit save/restore logic for the named state subset; everything else stays in whatever register the synthesis tool chose.

This path's cost is **author complexity**, not silicon. The chart author now reasons about:

- Which subsets of chart-internal state survive preemption.
- Which transition bodies are atomic and which are preemptible.
- The interaction between preemption and SCXML's run-to-completion semantic (does an RTC boundary inside an `<onentry>` count as preemptible?).
- The verification claim's expanded surface (every save-point doubles the reachable state graph the bound analysis must traverse).

SOS's chart-as-spec story depends on the chart staying legible at the spec-review level. Adding preemption annotations couples chart design to scheduling discipline in a way that erodes that legibility. The chart author should not be reasoning about preemption to specify behaviour; if they want preemption semantics, they want them expressed in chart vocabulary (events, parallel regions, priorities) — not in save-point annotations on top of an unchanged chart.

The deeper objection: chart-annotated save-points are an admission that the chart's natural semantics (RTC) and the implementation's chosen scheduling (preemptive) disagree, and the chart author bridges the disagreement by hand. SOS exists precisely to avoid that kind of hand-bridging.

### 6.3 Hardware-interrupt-driven context switch (timing-expensive)

The CPU-style preemption analog: an external interrupt signal causes the FSM scheduler to swap which FSM advances its state register. This requires:

- A scheduler microarchitecture distinct from the per-region one-FSM-per-region model SOS-08-C emits today (which has no scheduler at all — every region runs in parallel, in its own spatial replication).
- A cycle-accurate interrupt latency budget — from interrupt assertion to first cycle of the preempting FSM's transition body — that must hold across synthesis tool, place-and-route variability, and silicon process/voltage/temperature variation.
- A formal verification claim about the interrupt latency that survives the synthesis flow. The bound analysis the chart compiler runs today is at the cycle-count level; extending it to "and the preempting FSM is running its first transition body cycle within ≤ K cycles of the interrupt edge for all PVT corners" is a different verification problem.

This is the path that genuine sub-microsecond-interrupt safety-critical work uses today (typically as hand-authored RTL with formal sign-off on the latency claim). It is real engineering; it is not v1 SOS engineering. The bench-validated `CanonicalReplacement` verdict (SOS-04 + SOS-05 on the Cortex-M7 bench board) does not exercise this path; the codegen tool has no machinery for it; the cocotb + open-source-synth stack (per EOQ-003 + EOQ-004) does not in general support cycle-accurate timing claims of this form.

The deeper objection: hardware-interrupt-driven preemption is a scheduler-microarchitecture problem dressed up as a chart-emission problem. SOS-08 emits per-region FSMs and L1 services that compose them; it does not emit schedulers. Reframing the question as "do we add a scheduler emit path?" surfaces what the change actually is. v2 may answer yes; v1 answers no.

### 6.4 Why cooperative-only is sufficient at v1

The bootstrap kernel chart (`rtos_kernel.scxml`) is cooperative-only. It earned `CanonicalReplacement` on both the Rust and C target ports per SOS-06 §15 Amendment 005. The Cortex-M7 bench validation exercised the cooperative scheduling discipline against a non-trivial RTOS workload (task creation, semaphore + queue IPC, periodic tick, idle task). Cooperative-only is empirically sufficient for the v1 demonstration target.

Past v1, the methodology's reframing as "Statechart Orchestration System" (SOS-07) makes the v1 adoption story about *charts other than the kernel*. Application charts (per SOS-12 recursive-dispatch precedent) tend to be more cooperatively-designable than the kernel chart was, because application work naturally has more RTC boundaries (an event-driven application's transitions are short by nature). The cooperative-only choice that was sufficient for the kernel chart should be more-than-sufficient for the application charts SOS-07's broadened charter targets.

## 7. Obligations + escape hatches

### 7.1 Chart-author obligations

A chart targeting HDL emission via SOS-08 MUST satisfy the following at v1:

- (a) Every transition body completes within one macrostep boundary. The chart author does NOT have a mechanism to yield mid-transition.
- (b) The chart author MAY use `task.yield` events to signal RTC boundaries between cooperative tasks. These are NOT preemption; they are explicit chart-author-emitted yields.
- (c) The chart author MAY use SCXML `<parallel>` orthogonal regions to express concurrency that does not need preemption — each region runs independently in its own spatial replication on the hardware side.
- (d) The chart author MUST NOT use a hypothetical `preemptible="true"` annotation. The SOS chart validator at v1 SHALL reject such annotations (the PCDN-001 question is whether the rejection is a hard error or a warn-and-ignore — see §8).

A chart that violates (a) — i.e. a chart whose transition bodies cannot complete within one macrostep boundary — is not HDL-emittable at v1 under cooperative-only. The chart author must factor the long transition into multiple shorter transitions linked by cooperative chart events, or accept that the chart targets only software (Rust/C) where a runtime can multiplex.

A chart-author discipline checklist — "what makes a chart cooperatively designable" — is a candidate for a future style guide. PCDN-002 asks whether to document the checklist here or punt; this doc's recommendation is to punt to a future style guide once SOS-08-C lands and concrete examples of "cooperatively-difficult" chart shapes accumulate.

### 7.2 Codegen-tool obligations

The SOS codegen tool (today: `tools/sos-codegen/` per SOS-08 §13) MUST satisfy the following at v1 for the HDL emit path:

- (a) The SOS-08-C chart→FSM emitter MUST NOT emit save/restore logic for any chart region.
- (b) The bound-analysis pass MUST verify every transition body completes within one macrostep boundary BEFORE code generation proceeds. A transition body that cannot be bounded under cooperative-only is a codegen error (the chart needs factoring before HDL emission can proceed).
- (c) The chart validator MUST reject (or warn-and-ignore — pending PCDN-001) any preemption-related chart annotation. See §8 for the PCDN.
- (d) The SOS-08-D / E / F vector emitters MUST NOT emit tests that assume preemption semantics.
- (e) Every SOS-08 deliverable's docstring SHOULD carry a one-line note "v1 cooperative-only per INV-S-HDL-4" so a downstream reader sees the obligation without having to walk the spec.

### 7.3 Escape hatches (what cooperative-only does NOT preclude)

The cooperative-only ratification at v1 still permits:

- **Cooperative yielding via `task.yield`.** The chart author emits an explicit yield event at an RTC boundary; the hardware scheduler (such as it is — per-region with no preemption) advances to the next ready task. This is not preemption; it is the FSM declaring its own boundary.
- **Multiple parallel orthogonal regions** (per SCXML `<parallel>`). Orthogonal regions coexist by spatial replication on the hardware side, not by preemption. Each region runs in its own FSM on its own flip-flops; they do not preempt each other because they do not share an execution context to begin with. INV-SOS-F (bound composition: per-layer × independence axes) is the verification model for this.
- **Interrupt-driven event-source ingestion.** A hardware timer fires a `sys.tick` event; a UART receiver fires a `uart.rx_byte` event. These are event-delivery mechanisms, not preemption. The receiving FSM picks the event up at its next RTC boundary; the interrupt does not force a context switch mid-transition.
- **Future SOS-08-* preemption phase.** A future phase ratifying a preemption mechanism is not precluded by this doc; it is *conditional on* §9's v2 trigger criteria being satisfied.

The distinction the chart author MUST keep clear: preemption is "an external force interrupts my transition body mid-execution"; everything in §7.3 is "I, the FSM author, declare a boundary".

## 8. Pending Concept Decision Notices (PCDNs)

These open questions move this doc from 🟡 drafted to 🟢 ratified. PCDN identifier shape per parent CLAUDE.md.

- **PCDN-SOS-08-H-001 — Hard reject vs warn-and-ignore for preemption annotations at v1.** When a chart contains a hypothetical `preemptible="true"` annotation (or any future preemption-related markup), should the SOS chart validator hard-reject (error, refuse to emit) or warn-and-ignore (emit cooperative code, log a warning)? **Recommendation**: hard-reject at v1. A silent warn-and-ignore invites chart authors to author against semantics SOS does not implement, then debug "why did my preemption not work?" against an emitter that silently dropped it. The hard-reject surfaces the discrepancy at chart-validation time, not at runtime. The cost of a hard-reject is small — the chart author edits two lines; the cost of a silent demotion is large — the chart author debugs phantom semantics.

- **PCDN-SOS-08-H-002 — Chart-author discipline checklist: in-doc vs punt to future style guide.** Should this doc carry an enumerated checklist of "what makes a chart cooperatively designable" (transition-body length heuristics, RTC-boundary placement guidance, anti-patterns to avoid), or punt the checklist to a future SOS style guide? **Recommendation**: punt to a future style guide. SOS-08-C is the implementation phase where concrete "cooperatively-difficult" chart shapes will surface; until that data accumulates, an in-doc checklist would be speculative. This doc names the existence of the checklist (§7.1 last paragraph) and the criterion for authoring it (concrete pain emerges); the checklist's contents land at a SOS style-guide phase or as a SOS-08-C §15 amendment.

- **PCDN-SOS-08-H-003 — v2 trigger criteria: what concrete user case reopens cooperative-only.** §9 names the criteria. The PCDN is whether the recommended criteria are the right ones. **Recommendation**: §9's three criteria (paying customer; safety-critical / hard-real-time profile; the genuine sub-microsecond-interrupt use case naturally) are jointly sufficient. Any single criterion alone is suggestive but not triggering; all three together are the threshold. Walking the PCDN at ratification should validate that the threshold is neither too permissive (every "would be nice" reopens it) nor too restrictive (the threshold is unreachable in practice).

- **PCDN-SOS-08-H-004 — Cross-language consistency: does the C / Rust verified-strip profile (SOS-13) get a similar cooperative-only ratification?** SOS-13 targets verified-strip on the Rust port (and by extension the C port). The chart's cooperative-only design is enforced at the chart level (per §7); SOS-13's verified-strip emission inherits that automatically. The question is whether SOS-13's concept doc should also carry an explicit INV-S-RUST-N cooperative-only invariant (mirroring INV-S-HDL-4 on the HDL side) for symmetry, or whether the chart-level invariant is sufficient. **Recommendation**: chart-level is sufficient; SOS-13 cites INV-S-HDL-4 + this doc as the source. The cooperative-only discipline is a chart-side property; it propagates to every target without per-target restatement. Adding INV-S-RUST-N would be re-derivation, which the Spec-Before-Code discipline (parent CLAUDE.md "Definitions — reference vs restatement") prohibits. SOS-13's §10 reconciliation can name the citation.

## 9. v2 trigger criteria

The cooperative-only ratification at v1 stands indefinitely. It reopens — i.e. a future SOS-08-* or v2 phase MAY ratify a preemption mechanism — only when ALL of the following are satisfied:

- (a) **A paying customer asks for it.** Speculative "we might need preemption someday" does not reopen the question. A concrete customer-funded engagement that requires preemption to ship does.
- (b) **The customer's profile is safety-critical or hard-real-time.** Specifically: sub-microsecond interrupt-handling requirements in a path where the existing cooperative discipline is structurally insufficient (the chart cannot be factored to satisfy the latency budget under cooperative semantics). General-purpose "we want preemption because that's how RTOSes work" does not satisfy this criterion.
- (c) **The customer accepts the design-space trade-off.** Specifically: the customer commits to one of the three implementation paths (shadow register files; chart-annotated save-points; hardware-interrupt-driven context switch) and to the area / complexity / timing-budget cost that path entails. The customer does NOT get to ask for "preemption without the cost".

Satisfaction of all three criteria is itself a phase-doc ratification event: a future SOS-08-* concept doc (call it SOS-08-I — "preemption mechanism") authors the per-path contract surface, raises its own PCDNs, and lands as its own normative ratification. This doc's §15 records the satisfaction as an amendment + a cross-reference to the SOS-08-I doc.

Until all three criteria are satisfied, cooperative-only at v1 is the source of truth; v2 work targeting preemption proceeds via the same Spec-Before-Code discipline (parent CLAUDE.md), not via in-tree experimentation.

## 10. Reconciliation decisions vs adjacent repo primitives

### vs. SOS-08 umbrella §5.2

The umbrella freezes cooperative-only at the umbrella level; this doc records the rationale + obligations. Read together: SOS-08 §5.2 is the citation handle for downstream phases ("cooperative-only per SOS-08 §5.2"); SOS-08-H is the source the citation resolves to.

### vs. SOS-08 umbrella INV-S-HDL-4

INV-S-HDL-4 ("cooperative-only at v1") is the cross-sub-phase invariant; this doc is the invariant's normative source. Phase docs SOS-08-A through SOS-08-G (and SOS-09, SOS-13) cite INV-S-HDL-4 by name without re-deriving the rationale.

### vs. SOS-04 / SOS-05 chart-side syscall ABI

The chart-side syscall ABI (SOS-04 §5.3, SOS-05 §5.3) is target-agnostic: `sem.take` / `queue.send` / `task.create` mean the same thing on the M7 software side and the HDL side. Cooperative-only at v1 does not change the syscall ABI; it changes the *target* surface. A chart that is cooperatively designable runs on M7 and on HDL identically; a chart that is NOT cooperatively designable runs on M7 (the M7 ports multiplex; their scheduling is run-time-mediated) but does not emit to HDL (the HDL target has no multiplexer to provide).

### vs. SOS-13 verified-strip

SOS-13's verified-strip profile targets the Rust port (and by extension the C port). Cooperative-only at v1 is a chart-side discipline; it propagates to every target. SOS-13 inherits the cooperative-only obligation from the chart, not from this doc; the citation chain is chart → INV-S-HDL-4 (or chart-level cooperative-only) → SOS-13's emission. Per PCDN-004 recommendation, SOS-13 does NOT carry a separate INV-S-RUST-N restatement.

### vs. SCXML 1.0 run-to-completion semantic

SCXML 1.0 §3.13 defines macrostep RTC: a macrostep is atomic from the chart-author's perspective. Cooperative-only at v1 preserves this naturally — without preemption, the macrostep IS atomic, full stop. The reconciliation is that cooperative-only is the laziest possible faithful realisation of SCXML's RTC; preemption would be the implementation choice that needed extra machinery to preserve RTC. SOS chose the path with less machinery, which is also the path that aligns most directly with SCXML's authoring assumptions.

## 11. Non-goals

This sub-phase does NOT:

- Specify any preemption mechanism. The point is to ratify the *absence* of one.
- Specify the chart-author style guide for cooperative design. Punt per PCDN-002; the style guide lands at a later phase or as a SOS-08-C §15 amendment when concrete pain accumulates.
- Specify the v2 SOS-08-I preemption phase. v2 is only reachable after §9's trigger criteria are satisfied; designing it speculatively now would be the kind of "can of worms" opening the cooperative-only ratification was meant to avoid.
- Constrain SOS-08-D / E / F vector-emission shape beyond "no preemption tests". The positive shape of vector emission is owned by those phases; this doc only forbids one shape.
- Address scheduling on the software-side ports (M7 Rust, M7 C). The software ports have their own scheduling story (cooperative tasks + interrupt-driven event sources, validated at the bench); this doc is HDL-target-specific.

## 12. Acceptance checklist

A conforming SOS-08-H ratification satisfies:

- (a) ⏸ PCDN-SOS-08-H-001 through 004 resolved (§8).
- (b) ⏸ §5's five concrete obligations (5(a)-(e)) cited correctly in the downstream sub-phase docs (SOS-08-A, SOS-08-B, SOS-08-C, SOS-08-D, SOS-08-E, SOS-08-F) — each cites this doc + INV-S-HDL-4 once.
- (c) ⏸ §9's v2 trigger criteria validated (PCDN-003 walkthrough) and recorded as the threshold under which the cooperative-only ratification reopens.
- (d) ⏸ SOS-13's concept doc §10 reconciliation names INV-S-HDL-4 + this doc as the source for cooperative-only at the Rust target, per PCDN-004 recommendation.
- (e) ⏸ Cross-phase invariants INV-SOS-A through H cited correctly in this doc (done in §0 + §4).
- (f) ⏸ Cross-sub-phase invariant INV-S-HDL-4 cited correctly in this doc (done in §0 + §4 + §5).

This sub-phase has no implementation gates beyond ratification. The "implementation" of a frozen non-feature is the *absence* of code; the acceptance gates are documentation citation + downstream coherence.

## 13. Files cited

| Path | Role |
|---|---|
| `docs/concepts/SOS-08-CONCEPTS.md` | Umbrella; freezes cooperative-only in §5.2; INV-S-HDL-4 in §7. |
| `docs/concepts/SOS-07-CONCEPTS.md` | Cross-phase invariants INV-SOS-A through H; cited not redefined. |
| `docs/concepts/SOS-ROADMAP-07-PLUS.md` | Informative roadmap; §6 EOQ-008-ROADMAP resolution is the upstream ratification this doc concretizes; §4 SOS-08-H scope sketch is consistent with this doc's normative content. |
| `docs/concepts/SOS-06-CONCEPTS.md` | Bench validation evidence — `rtos_kernel.scxml` reached `CanonicalReplacement` on both Rust and C ports per §15 Amendment 005. |
| `docs/concepts/SOS-13-CONCEPTS.md` | Verified-strip Rust profile; this doc's §10 reconciliation names the citation chain. |
| `rtos_kernel.scxml` | Bootstrap kernel chart; cooperative-only by design, the empirical sufficiency demonstration. |
| W3C SCXML 1.0 §3.13 (external) | Macrostep + run-to-completion semantics; cited as the upstream authority. |
| Parent `CLAUDE.md` | Spec-Before-Code Planning Discipline; Phase document shape; PCDN identifier convention. |

## 14. Unblocks

This sub-phase's ratification (after PCDN walkthrough) unblocks:

- **SOS-08-C** (chart→FSM emission) — the cooperative-only obligation on the emitter (§7.2) is the contract surface SOS-08-C operates under. Without this doc, SOS-08-C's emitter has no normative source to cite for "no save/restore logic".
- **SOS-08-D / E / F** (vector emitters) — the "no preemption tests" obligation (§5(d)) is the contract surface those emitters operate under.
- **SOS-13** (verified-strip Rust) — the citation chain (chart-level cooperative-only → SOS-13 emission) lands cleanly per §10 reconciliation + PCDN-004 recommendation.

## 15. Change log

### 2026-05-23 — Initial draft (Ira)

- Authored `SOS-08-H-CONCEPTS.md` as the dedicated non-feature ratification sub-phase under the SOS-08 umbrella, per the umbrella §5.2 promise that "rationale recorded in detail at SOS-08-H-CONCEPTS.md when that sub-phase ratifies".
- §3 canonical glossary: terms `Cooperative-only scheduling` (mirror from SOS-08 §3), `Preemption` (owned by this doc; does not exist in repo), `Macrostep` + `Run-to-completion (RTC)` (mirror from SCXML 1.0 §3.13), `Shadow register file` / `Chart-annotated save-point` / `Hardware-interrupt-driven context switch` (the three preemption-in-HDL paths rejected at v1), `task.yield` + `v2 trigger`.
- §5 frozen non-feature: five concrete obligations (5(a)-(e)) enumerating what cooperative-only forbids across the SOS-08-A through F sub-phases.
- §6 design-space rationale: three subsections walking why each of the three preemption-in-HDL paths fails the v1 adoption story (area-expensive shadow register files; complexity-expensive chart-annotated save-points; timing-expensive hardware-interrupt-driven context switch). §6.4 records the bench-validation evidence that cooperative-only is empirically sufficient for non-trivial RTOS workloads.
- §7 chart-author + codegen-tool obligations + escape hatches (cooperative `task.yield`; parallel orthogonal regions; interrupt-driven event-source ingestion).
- §8 four PCDNs: hard-reject vs warn-and-ignore for preemption annotations; in-doc vs punt chart-author discipline checklist; v2 trigger criteria validation; cross-language consistency to SOS-13.
- §9 v2 trigger criteria: three jointly-sufficient conditions (paying customer; safety-critical hard-real-time profile; design-space-trade-off acceptance).
- §10 reconciliation vs SOS-08 umbrella §5.2 + INV-S-HDL-4 + SOS-04/05 syscall ABI + SOS-13 verified-strip + SCXML 1.0 §3.13.
- §12 acceptance checklist: documentation-only gates (no implementation gates — ratifying a non-feature has no code deliverable).

Status: 🟡 **drafted**, awaiting PCDN walkthrough.

### 2026-05-23 — Ratified after PCDN walkthrough (Ira)

All four PCDNs from §8 resolved with recommendations accepted.

- **PCDN-SOS-08-H-001 → RESOLVED**: SOS chart validator **hard-rejects** preemption-related annotations at v1. Silent warn-and-ignore would invite chart authors to author against semantics SOS does not implement, then debug phantom semantics against an emitter that silently dropped the markup. Hard-reject surfaces the discrepancy at chart-validation time; the chart author edits two lines.
- **PCDN-SOS-08-H-002 → RESOLVED**: chart-author discipline checklist is **punted to a future style guide**. SOS-08-C implementation is the phase where concrete cooperatively-difficult chart shapes will surface; the checklist's contents land at a SOS style-guide phase or as a SOS-08-C §15 amendment when pain data accumulates.
- **PCDN-SOS-08-H-003 → RESOLVED**: v2 trigger criteria are the **three named in §9** (paying customer + safety-critical / hard-real-time profile + design-trade-off acceptance), jointly sufficient. Any single criterion alone is suggestive but not triggering; all three together are the threshold.
- **PCDN-SOS-08-H-004 → RESOLVED**: cross-language consistency — **chart-level invariant is sufficient**; SOS-13 cites INV-S-HDL-4 + this doc as the source. Cooperative-only is a chart-side property that propagates to every target without per-target restatement. Adding INV-S-RUST-N would violate parent CLAUDE.md "Definitions — reference vs restatement". SOS-13's §10 reconciliation names the citation.

**§5 amendments**:
- §5 frozen non-feature extended: SOS chart validator hard-rejects any `preemptible="*"`, `priority-preempt="*"`, or hypothetical `<sos:preempt>` markup with a chart-vocabulary error message per INV-S-HDL-5; the validator lint rule is `SCXML-LINT-H-1` (lands as SOS-01 §15 amendment co-landing with SOS-08-H implementation).

**Status**: 🟢 **ratified**. Cooperative-only at v1 is now the canonical non-feature. SOS-08-A / SOS-08-B / SOS-08-C / SOS-08-D / SOS-08-E / SOS-08-F all reference SOS-08-H + INV-S-HDL-4 as the source of cooperative-only discipline. SOS-13 §10 reconciliation cites SOS-08-H + INV-S-HDL-4 (co-landing trivial §15 amendment to SOS-13).
