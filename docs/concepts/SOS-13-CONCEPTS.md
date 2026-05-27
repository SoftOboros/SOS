# SOS-13 — Verified-codegen Rust position (`verified-strip` profile)

**Status:** 🟢 **ratified 2026-05-23**. All 5 PCDNs walked; resolutions recorded in §15.

## 0. Authority policy

This phase doc concretizes [INV-SOS-G](./SOS-07-CONCEPTS.md) — *the verified-codegen position* — for the Rust target. INV-SOS-G is the load-bearing cross-phase invariant; SOS-13 is its first concrete realisation. The phase generalises later (C in SOS-08, HDL in SOS-08-A onwards); the Rust phase is the v1 demonstration that the position is reachable.

Per the parent CLAUDE.md "Spec-Before-Code Planning Discipline":

- **Normative** sections of this doc: §3 glossary, §4 source-of-truth map, §5 frozen decisions, §6 the three-positions claim, §7 unchecked-operation catalogue, §8 invariant-citation format, §9 cross-target footprint, §10 reconciliation, §12 acceptance checklist, §15 change log.
- **Informative** sections: §1 purpose, §2 problem statement, §11 non-goals, §13 files cited, §14 unblocks, §16 PCDNs.
- All keywords MUST, MUST NOT, SHALL, SHOULD, SHOULD NOT, MAY are interpreted per RFC 2119 / RFC 8174 when capitalised.

This doc cites [SOS-07](./SOS-07-CONCEPTS.md) (INV-SOS-G, INV-SOS-B, INV-SOS-D), [SOS-06](./SOS-06-CONCEPTS.md) §15 Amendment 005 (the bench-validated baseline), [SOS-06-A-EVALUATION](./SOS-06-A-EVALUATION.md) Q5 (the invariant-violation-surface concern), and [SOS-04](./SOS-04-CONCEPTS.md) (the Rust port whose hand-written reference is the absolute floor).

## 1. Purpose

To define the `verified-strip` codegen profile that lets `tools/sos-codegen/` emit Rust source closing the 0–2 % gap to the hand-written reference, by replacing redundant runtime checks with unchecked operations whose discharging obligation is provably enforced at the chart-bounds-analysis layer. Every elimination is audit-trail-cited; no elimination is silent.

In short: SOS-13 ratifies how to make Rust codegen reach hand-written-Rust performance without losing the spec-as-source verification story.

## 2. Problem statement

Per [SOS-06](./SOS-06-CONCEPTS.md) §15 Amendment 005, the current codegen Rust output sits at:

| Metric | Hand-written Rust | Codegen Rust (`dev-keep`) | Δ |
|---|---|---|---|
| `BinarySize.text` | 39 188 B | 41 132 B | **+5.0 %** |
| `MacrostepCycleCount` (vector 0001) | 805 cyc | 902 cyc | **+12.0 %** |
| `FunctionalConformance` | 6/6 | 6/6 | — |
| `Auditability` (§6.2.7) | reference | 7/7 ✅ | — |

Both metrics sit inside the §5.2 (d) 1.5× gate, so the codegen output earns `CanonicalReplacement` per the SOS-06 verdict procedure. But the gap is removable.

Three observations drive this phase:

1. **The extra cycles are check overhead.** The v0 transliterator emits idiomatic safe Rust: `tasks[tid as usize]` (bounds-checked), `option.unwrap()` (panic on `None`), `match` arms with `_ => unreachable!()` (panic-string overhead). Profiling the ~+100 cycle delta against hand-written shows it accumulating in bounds-check returns and panic-payload setup the hand-written port deliberately omits.

2. **The hand-written port's elisions are not arbitrary.** Each elision corresponds to a chart-derived obligation that the hand-author proved at review time. For example: `tcb[tid].state = TaskState::Ready` skips a bounds check because `tid` is invariant-bounded by `0..MAX_TASKS` at every `script_*` entry, and the chart's bound analysis can certify this. The hand-author makes the proof in their head; the codegen tool can make it explicitly.

3. **[SOS-06-A-EVALUATION §6.2.7 Q5](./SOS-06-A-EVALUATION.md) — invariant-violation surfaces — is the audit gate.** Silent panics (`unwrap`, `unreachable!()`) erode the surface where invariant violations would otherwise show up at runtime. The fix is not to ignore them; the fix is to **prove they are unreachable** and **record the proof**. Under `verified-strip` the panic site disappears, AND the audit trail says why.

The phase's job is to make this transformation declarative + reviewable, never silent. INV-SOS-G is the binding rule; this doc operationalises it.

## 3. Canonical glossary

| Term | Definition |
|---|---|
| **default-unchecked position (C)** | The C target's default posture: indexed access is `arr[i]` with no runtime check; null-checks are programmer responsibility; arithmetic wraps silently. Performance ceiling is "raw machine"; the audit surface is "the developer remembered". |
| **default-safe position (Rust, dev-keep)** | The current Rust codegen posture under `dev-keep`: indexed access via `arr[i]` performs bounds-check; `Option::unwrap()` panics on `None`; `match` arms with `_ => unreachable!()` panic with a string. Performance ceiling is "safe Rust"; the audit surface is "the compiler enforces it". |
| **verified-strip position (Rust, this phase)** | The Rust codegen posture under `--profile verified-strip`: indexed access via `get_unchecked` where the chart's bound analysis discharges the bounds obligation; `unwrap_unchecked` where the chart's reachability analysis certifies `Some`/`Ok`; `unreachable_unchecked` at branches the bound analysis eliminated. Performance ceiling is "hand-written Rust"; the audit surface is "the chart's bound analysis proves it". |
| **discharging invariant** | A named invariant (in `INV-S-CHART-N` or `INV-S-PORT-N` form) whose enforcement at the chart layer makes the corresponding runtime check redundant. Every `unsafe` block emitted under `verified-strip` MUST cite at least one discharging invariant. |
| **chart site** | The point in the chart (`<state id>`, `<transition>`, `<onentry>`/`<onexit>` block) where the discharging invariant is established or maintained. The audit trail records this site so a reviewer can navigate from the unsafe block back to the chart proof. |
| **verified-strip-audit.json** | The per-build audit artifact (§7.4) listing every `unsafe` block emitted under `verified-strip`, the invariant cited, the chart site that discharges it, and bound-analysis evidence. Required artifact under this profile. |
| **`dev-keep` profile** | The default codegen profile — current behaviour. Preserves all safe-Rust runtime checks. Used during chart-authoring iteration, where panic-on-violation is the desired debugging posture. |

## 4. Source-of-truth map

| Concept | Authority |
|---|---|
| Verified-codegen position (cross-phase) | [SOS-07-CONCEPTS.md §6 INV-SOS-G](./SOS-07-CONCEPTS.md) |
| Rust target performance baseline | [SOS-06-CONCEPTS.md §15 Amendment 005](./SOS-06-CONCEPTS.md) |
| Auditability checklist (Q5) | [SOS-06-CONCEPTS.md §6.2.7](./SOS-06-CONCEPTS.md) + [SOS-06-A-EVALUATION.md](./SOS-06-A-EVALUATION.md) |
| Rust port idioms (hand-written reference) | [SOS-04-CONCEPTS.md](./SOS-04-CONCEPTS.md) |
| Chart-derived invariants (INV-S6/7/8/12) | [SOS-00-CONCEPTS.md §9](./SOS-00-CONCEPTS.md) |
| Unchecked-operation catalogue | **this doc** (§7) |
| Invariant-citation format | **this doc** (§8) |
| Profile selection mechanism | **this doc** (§5) |
| Audit-trail file format | **this doc** (§7.4) — pending PCDN-SOS-13-002 |

## 5. Frozen decisions

### 5.1 Profiles

The codegen tool freezes exactly two named profiles at SOS-13 v1:

- **`dev-keep`** — current default-safe-Rust idiom. Unchanged from Amendment 005 emission.
- **`verified-strip`** — emit unchecked operations against chart-discharged obligations per §7, with the audit trail artifact per §7.4.

Registration policy: **Standards Action**. Adding a profile (e.g. a hypothetical `strict-debug` that *adds* checks beyond `dev-keep`) requires a §15 amendment to this doc.

### 5.2 Default profile

The default profile is **`dev-keep`**, per PCDN-SOS-13-003 (recommended resolution). A `verified-strip` build is opt-in via `--profile verified-strip` on the codegen CLI. The chart-authoring iteration loop wants debug-friendly panics; the `verified-strip` profile is a release-build decision.

### 5.3 Profile selection mechanism

`tools/sos-codegen/main.py` gains a `--profile {dev-keep,verified-strip}` CLI flag, mutually exclusive across the two values, defaulting to `dev-keep`. The flag applies whole-port. Per-region overrides via chart annotation (`<region profile="dev-keep"/>`) MAY exist per PCDN-SOS-13-001; if ratified, a region annotated `dev-keep` retains safe-Rust idiom even under whole-port `--profile verified-strip`.

### 5.4 Profile applies to Rust target only at v1

The `verified-strip` profile is **Rust-specific**. `--target c --profile verified-strip` is rejected by the CLI at v1. The C analogue (`__builtin_unreachable()` + `__attribute__((nonnull))` + `restrict` annotations) is the subject of a future SOS-08 phase (named informatively in §9 below).

## 6. The three positions

This section is **normative** — it is the architectural claim SOS-13 makes about generated code in general, with the Rust target as v1 demonstration.

| Position | Default for | Trust statement | Audit surface |
|---|---|---|---|
| **default-unchecked** | C codegen, hand-written C | "Trust the developer" | Code review + static analyzers (cppcheck, clang-tidy). Invariant violations may produce undefined behaviour. |
| **default-safe** | Rust codegen (`dev-keep`), hand-written safe Rust | "Trust the compiler" | The Rust type system + runtime panics. Invariant violations produce panics with locatable messages. |
| **verified-strip** | Rust codegen (`verified-strip`); future C codegen via SOS-08 | "We proved the developer can't violate the contract" | `verified-strip-audit.json` + chart bound analysis. Invariant violations are unreachable by construction; the audit trail names which invariant + which chart site proves it. |

The verified-strip position is reachable **only by a generator with bounded reachability analysis**, and SOS owns one. Bound-analysis is the load-bearing primitive: it produces the per-chart-site obligations (per [INV-SOS-B](./SOS-07-CONCEPTS.md)) that discharge the runtime checks the codegen would otherwise emit.

The three positions are not a continuum. They are three distinct architectural commitments:

- C's position says runtime checks are the developer's responsibility, accepting undefined behaviour as the cost.
- Safe Rust's position says runtime checks are the language's responsibility, accepting performance overhead as the cost.
- Verified-strip's position says runtime checks are the *spec*'s responsibility, with the discharging invariant cited per-elimination, accepting an audit-trail-maintenance cost.

INV-SOS-G ratifies the existence of the third position. SOS-13 ratifies its first concrete realisation.

## 7. Unchecked-operation catalogue

This section is **normative**. The catalogue is a **frozen enumeration** with registration policy **Standards Action** — adding a new unchecked-op shape requires a §15 amendment to this doc.

### 7.1 Emitted under `verified-strip`

| Op id | Rust operation | Replaces (under `dev-keep`) | Discharging-obligation shape |
|---|---|---|---|
| **VS-OP-1** | `slice.get_unchecked(i)` / `slice.get_unchecked_mut(i)` | `slice[i]` (bounds-checked) | `i < slice.len()` proven by chart-derived bound on the index variable. |
| **VS-OP-2** | `option.unwrap_unchecked()` | `option.unwrap()` | `option == Some(_)` proven by the chart's pre-state / transition guard at the call site. |
| **VS-OP-3** | `result.unwrap_unchecked()` | `result.unwrap()` / `?` | `result == Ok(_)` proven by the chart's pre-state / call-site contract. |
| **VS-OP-4** | `core::hint::unreachable_unchecked()` | `unreachable!()` (panic-with-message) | The branch is not in the chart's reachable-state set per the bound analysis. |
| **VS-OP-5** | `heapless::Vec::into_inner()` or equivalent non-empty access | `vec.first().unwrap()` / `vec.pop().unwrap()` | The chart's wait-queue / ready-queue invariant (INV-S7 / INV-S8) certifies non-empty at the call site. |

VS-OP-1 through VS-OP-5 are the v1 catalogue. Every emitted `unsafe { ... }` block under `verified-strip` MUST correspond to exactly one VS-OP-* identifier, carried in the SAFETY comment per §8.

### 7.2 NOT emitted under `verified-strip`

- `unsafe` arithmetic intrinsics (`unchecked_add`, `unchecked_sub`, etc.) — chart bound analysis does not currently certify arithmetic non-overflow. Deferred to a future amendment.
- `transmute` and pointer-cast intrinsics — these require type-level proofs the chart layer does not produce.
- `core::ptr::*` unchecked operations — same.
- Any unchecked op against a non-chart-derived obligation (e.g. peripheral register-mapped memory access) — `dev-keep` emission stays unchanged for these.

The principle: `verified-strip` removes checks **only** where the chart's bound analysis is the discharging authority. The port's own `unsafe` blocks (e.g. PendSV register access in [SOS-04 §6.4](./SOS-04-CONCEPTS.md)) are untouched.

### 7.3 Eligibility analysis

Before emitting any VS-OP-* unsafe block, the codegen tool runs an eligibility analysis against the chart's bound-analysis IR (the same IR SOS-03 vectors derive from). The analysis answers, for each candidate site:

- *Is the index variable provably in-range at this site?* (VS-OP-1 eligibility.)
- *Is the option/result provably Some/Ok at this site?* (VS-OP-2/3 eligibility.)
- *Is the branch in the chart's reachable-state set?* (VS-OP-4 eligibility.)
- *Is the collection provably non-empty at this site?* (VS-OP-5 eligibility.)

If the answer is "yes" with a citable invariant, the site is eligible. If the answer is "no" or "unknown", the site emits the `dev-keep` form — even under `--profile verified-strip`. The default is "keep the check"; eligibility is the explicit upgrade path.

### 7.4 Audit-trail artifact

Per build under `--profile verified-strip`, the codegen tool emits `verified-strip-audit.json` (working name; PCDN-SOS-13-002 ratifies the file format). The artifact's shape:

```json
{
  "schema_version": 1,
  "chart_sha": "<rtos_kernel.scxml SHA at build time>",
  "toolchain_sha": "<sos-codegen SHA at build time>",
  "profile": "verified-strip",
  "eliminations": [
    {
      "site": "ports/m7-rust/src/handlers.rs:142",
      "op": "VS-OP-1",
      "discharging_invariants": ["INV-S-CHART-3"],
      "chart_site": "rtos_kernel.scxml#sys_yield/onentry",
      "bound_evidence": "tid is bounded by ready-queue scan, i ∈ [0, MAX_TASKS)",
      "safety_comment": "INV-S-CHART-3 — tid < MAX_TASKS at every script_* entry (proved at sys_yield.onentry's loop bound)."
    }
  ]
}
```

Reviewers point a tool at the audit file to verify each elimination matches a real chart-level proof. The audit-tool implementation is out of scope for SOS-13 (a follow-up phase or a SOS-06-B amendment); the artifact shape MUST be stable enough that the audit-tool can be written separately.

### 7.5 Chart-side discharge-annotation grammar (PCDN-13-discharge-grammar)

This section is **normative**. It ratifies the chart-side syntax by which a `rtos_kernel.scxml` author declares that a named safety check has been discharged for a scope's operations. The grammar's first consumer is the SOS-13 Rust codegen tool (`tools/sos-codegen/transliterate_rust.py`); SOS-01 recognises the element as a permitted SCXML extension via the co-landing [SOS-01 §15](./SOS-01-CONCEPTS.md) amendment.

**Annotation element.** `<sos:discharged check="{name}"/>`, carried as a child of a `<state>`, `<transition>`, `<onentry>`, or `<onexit>` block. The annotation declares that the chart author has discharged the safety check named by `check` for the operations in that scope.

**Frozen `check` value enumeration.** The four ratified `check` values at v1 are:

| `check` value | Discharges (VS-OP id) | Meaning |
|---|---|---|
| **`bounds`** | VS-OP-1 | Array/slice bounds check (the index variable is provably in-range at the scope's operations). |
| **`div-by-zero`** | (future VS-OP — arithmetic) | Integer division denominator is provably non-zero. Not currently in the §7.1 catalogue (per §7.2 arithmetic intrinsics are deferred); annotation accepted now so chart authoring can stabilise ahead of the arithmetic-intrinsic amendment. |
| **`null`** | VS-OP-2, VS-OP-3 | `Option::unwrap` / `Result::unwrap` is provably `Some` / `Ok`. |
| **`overflow`** | (future VS-OP — arithmetic) | Integer arithmetic is provably non-overflowing. Same deferred-VS-OP status as `div-by-zero`. |

The enumeration is **frozen at the four values**. Adding a `check` value requires a **Standards Action** §15 amendment per parent CLAUDE.md "Frozen enumerations — registration policy". The registration policy mirrors §7.1's VS-OP catalogue policy.

**Multiplicity.** Zero or more `<sos:discharged>` children MAY appear per parent scope. Each element names exactly one `check` value. A scope MAY declare all four checks discharged via four separate elements; aggregating multiple values into one element (e.g. `check="bounds,null"`) is NOT permitted at v1.

**Scope of effect.** The discharge applies only to the codegen artifact (`tools/sos-codegen/transliterate_rust.py` at v1). It does NOT modify chart semantics — SCXML execution under SOS-02 / SOS-03 conformance vectors is unaffected; bounded reachability proofs proceed as before. The chart author is asserting that the safety check is mechanically discharged at the source-level abstraction; codegen acts on the assertion only when `--profile verified-strip` is active.

**Codegen behaviour.** Per PCDN-13-001 through PCDN-13-005 (resolved in the prior 2026-05-23 ratification entry):

- With `--profile verified-strip` active (globally per §5.3, or per-region per PCDN-001's "both" resolution), each discharged operation is emitted with the unsafe-equivalent (per §7.1), the SAFETY comment (per §8) citing the discharging invariant, and a JSONL audit-log entry (per §7.4) recording the discharge.
- Without `--profile verified-strip`, the discharge is informative only. The audit log is not written; safe-default emission per `dev-keep` is unchanged. This matches §5.2's default-profile principle: `verified-strip` is opt-in.

**Inheritance.** A `<sos:discharged>` attached to a `<state>` applies to all operations in that state's `<onentry>`, `<onexit>`, and inline `<script>` blocks of transitions whose source is that state. Inheritance does NOT cross state boundaries — a discharge on a parent state does not propagate to child states (each child declares its own discharges if applicable).

**Authority.** The annotation is **read by the SOS-13 codegen tool only**. SOS-01 lint accepts it as a permitted extension element (per the co-landing [SOS-01 §15](./SOS-01-CONCEPTS.md) `<sos:discharged>` extension-element amendment). The W3C SCXML 1.0 XSD treats unknown-namespace elements as permitted via the `<xsd:any namespace="##other"/>` wildcard in the executable-content content model; schema validation per `SCXML-LINT-001` is therefore unaffected.

**Cross-references.**

- §5 (frozen decisions) — the `<sos:discharged>` grammar inherits §5's Standards-Action discipline for its `check` enumeration.
- §7 (VS-OP unchecked-operation catalogue) — each VS-OP maps to one `check` value per the table above. VS-OP-5 (heapless-vec non-empty access) discharges via the chart's wait-queue / ready-queue invariants and does not require an explicit `<sos:discharged>` since the discharging invariant is the structural INV-S7 / INV-S8 contract rather than a per-scope assertion.
- §8 (invariant-citation format) — every `unsafe` block emitted under a discharge MUST still carry the §8 SAFETY comment citing the discharging invariant id.
- [SOS-07 INV-SOS-G](./SOS-07-CONCEPTS.md) — the load-bearing invariant. The `<sos:discharged>` element makes the discharge **explicit at the chart layer**, preventing silent stripping by construction: codegen cannot emit an unchecked op without a corresponding chart-side annotation (or a structural invariant per VS-OP-5). The `<sos:discharged>` grammar is INV-SOS-G's chart-side enforcement mechanism.
- [SOS-01 §15 — `<sos:discharged>` extension element recognized](./SOS-01-CONCEPTS.md) — the co-landing lint-side recognition that prevents `SCXML-LINT-001` schema-validation failures and reserves the lint rules' validation of the `check` enumeration as a future SOS-13 lint addition.

## 8. Invariant-citation format

Every `unsafe { ... }` block emitted by the codegen under `--profile verified-strip` MUST carry a doc-comment immediately above the `unsafe` keyword of the shape:

```rust
// SAFETY: <invariant-id> — <one-line rationale> (proved at <chart-site>).
unsafe { ... }
```

Where:

- **`<invariant-id>`** is the discharging invariant. Format `INV-S-CHART-N` for chart-derived invariants (newly emitted by SOS-13 — see §8.1), `INV-S-PORT-N` for port-derived invariants per [SOS-04 §6.5](./SOS-04-CONCEPTS.md), or `INV-S<N>` for [SOS-00 §9](./SOS-00-CONCEPTS.md) cross-port invariants. Multiple invariants MAY be comma-separated.
- **`<one-line rationale>`** is a human-readable summary of the discharge (≤ 100 chars). Reviewers read this without consulting the audit file.
- **`<chart-site>`** is the chart location where the discharging invariant is established or maintained, in the form `<state-or-transition-id>.<onentry|onexit|guard>` (e.g. `sys_yield.onentry`, `sem_take.guard`).

Example emissions:

```rust
// SAFETY: INV-S-CHART-3 — tid < MAX_TASKS at every script_* entry (proved at boot.onentry's loop bound).
let tcb = unsafe { TCB_POOL.get_unchecked_mut(tid as usize) };

// SAFETY: INV-S7 — ready[p] is non-empty before pick_next dequeues (proved at sched_dispatch.guard).
let next = unsafe { READY_POOL[p].pop_front().unwrap_unchecked() };

// SAFETY: INV-S-CHART-12 — TaskState variants outside Ready/Running/Blocked are unreachable per chart bound (proved at sched_dispatch.onentry).
unsafe { core::hint::unreachable_unchecked() }
```

### 8.1 `INV-S-CHART-N` series

The codegen tool emits chart-derived invariants as a numbered series, `INV-S-CHART-1` through `INV-S-CHART-N`, into a generated `invariants.rs` (or `INVARIANTS.md` companion) per build. Each entry records the invariant text, the chart site that establishes it, and the bound-analysis evidence. The audit file (§7.4) cross-references these.

The `INV-S-CHART-N` namespace is **owned by the codegen tool**, distinct from `INV-S<N>` (SOS-00 cross-port) and `INV-S-PORT-N` (SOS-04 port-level). The boundary is intentional: chart-derived invariants are an artifact of the bound analysis, not a hand-authored spec section, so they live in the generated tree.

Registration policy for the citation-format shape: **Standards Action**. Changing the comment template (e.g. moving from `// SAFETY:` to a different prefix) requires a §15 amendment.

## 9. Target metrics and cross-target footprint

### 9.1 Target metrics for `verified-strip` Rust

| Metric | `dev-keep` (current) | `verified-strip` target | Hand-written Rust (floor) |
|---|---|---|---|
| `BinarySize.text` | 41 132 B | **≤ 39 500 B** (within +0–2 % of hand-written; -3.9 % vs dev-keep) | 39 188 B |
| `MacrostepCycleCount` (vector 0001) | 902 cyc | **≤ 820 cyc** (within +0–2 % of hand-written; -9 % vs dev-keep) | 805 cyc |
| `FunctionalConformance` | 6/6 ✅ | **6/6 required** (PCDN-SOS-13-005) | 6/6 |
| `Auditability` Q5 (silent-panic surface) | partial (panics are silent until they fire) | **closed** — panics are proven unreachable AND the proof is recorded in `verified-strip-audit.json` | reference |
| `Auditability` Q1–Q4, Q6, Q7 | 7/7 ✅ | **7/7 required** | reference |

The Q5 closure is the load-bearing user-facing claim of this phase. Under `dev-keep`, Q5 passes because the panic surface is visible (a panic at runtime localises the violation); under `verified-strip`, Q5 passes by a different mechanism — the panic surface is *removed*, and the audit trail proves the removal is sound. Both pass; neither claim is silent.

### 9.2 Cross-target footprint

`verified-strip` is Rust-specific at SOS-13 v1. The pattern generalises:

- **C target (future SOS phase).** The C analogue replaces `assert()` and explicit bounds checks with `__builtin_unreachable()` (at proven-unreachable branches), `__attribute__((nonnull))` on pointer parameters, and `restrict` on aliasing-prohibited pointers. The audit-trail format is the same (modulo a `target` field). Cross-target generalisation lives in a future phase doc — explicitly **not** SOS-13's scope.
- **HDL targets (SOS-08).** The HDL analogue maps to synthesis-tool unreachable-state pruning + SVA `assume` properties. The audit trail's role is the same: name the discharging invariant per pruning decision. Out of scope for SOS-13.

Per INV-SOS-G, all targets MAY participate in the verified-codegen position; SOS-13 is the v1 demonstration, not the only realisation. Future per-target phases extend the cross-target footprint without re-authoring the core architectural claim.

## 10. Reconciliation decisions vs adjacent repo primitives

### vs. [SOS-04 §6.5 INV-S-PORT-N](./SOS-04-CONCEPTS.md)

INV-S-PORT-* are port-authored invariants (e.g. INV-S-PORT-2 NVIC priority discipline). The `verified-strip` profile MAY cite them in SAFETY comments where the port's invariant discharges a codegen obligation. Citation is `mirror` — SOS-13 does not redefine the port invariants; it references them.

### vs. [SOS-00 §9 INV-S6 / INV-S7 / INV-S8 / INV-S12](./SOS-00-CONCEPTS.md)

The cross-port invariants (`blk_obj` integrity, ready-queue integrity, wait-queue ordering, static-only) are heavily exercised by `verified-strip` — most VS-OP-5 emissions cite INV-S7 or INV-S8. Citation relationship: `mirror`. SOS-13 does not amend any SOS-00 invariant; it references them at the SAFETY-comment surface.

### vs. [SOS-06 §6.2.7 Q5 Auditability](./SOS-06-CONCEPTS.md)

Q5 ("invariant-violation surfaces") under `dev-keep` is satisfied by visible panic surfaces. Under `verified-strip`, Q5 is satisfied by the audit-trail artifact + the SAFETY-comment surface. The §6.2.7 question's intent is preserved; the satisfaction mechanism is different. A SOS-06 §15 amendment SHOULD record this on `verified-strip` evaluation runs (per PCDN-SOS-13-005's bench-validation gate).

### vs. [SOS-07 INV-SOS-B](./SOS-07-CONCEPTS.md) (vectors-as-deliverable)

INV-SOS-B requires every emission to be backed by exhaustive vectors. `verified-strip` does not change the vector requirement — the same 6/6 SOS-03 vectors MUST pass on the `verified-strip` output before that build can be ratified (PCDN-SOS-13-005). Vectors are how the elimination's soundness is empirically confirmed; the audit trail is how the elimination's *reason* is documented. Both are required.

### vs. [SOS-07 INV-SOS-G](./SOS-07-CONCEPTS.md) (verified-codegen position)

SOS-13 **is** the Rust-target realisation of INV-SOS-G. The relationship is `compose`: INV-SOS-G owns the cross-phase position; SOS-13 composes the position into a Rust-specific emission profile + audit trail.

## 11. Non-goals

SOS-13 does NOT:

- Define the C-target verified-strip equivalent. That lives in a future SOS-08-* or SOS-13-B phase.
- Define the HDL-target verified-strip equivalent. That lives in SOS-08.
- Ratify a `verified-strip` build as the default profile. The default stays `dev-keep` (§5.2).
- Modify any [SOS-04](./SOS-04-CONCEPTS.md) / [SOS-05](./SOS-05-CONCEPTS.md) hand-written port content.
- Modify any [SOS-00 §9](./SOS-00-CONCEPTS.md) invariant content.
- Modify the [SOS-03](./SOS-03-CONCEPTS.md) conformance vector framework — `verified-strip` emissions MUST pass the same vectors.
- Re-author the [SOS-06 §6.2.7](./SOS-06-CONCEPTS.md) Auditability checklist. The Q5 satisfaction mechanism is documented in §10 above; the checklist itself is unchanged.
- Build the audit-trail review tooling. The artifact shape is ratified here; the tooling that consumes it is a future deliverable.

## 12. Acceptance checklist

A conforming SOS-13 ratification satisfies all of:

- (a) `tools/sos-codegen/main.py` accepts `--profile {dev-keep,verified-strip}` and defaults to `dev-keep`.
- (b) Under `--profile verified-strip`, the Rust target emits the unchecked-operation catalogue per §7.1 against eligibility analysis per §7.3.
- (c) Every emitted `unsafe { ... }` block under `verified-strip` carries a SAFETY comment per §8 citing at least one discharging invariant in `INV-S<N>` / `INV-S-CHART-N` / `INV-S-PORT-N` form.
- (d) Per-build `verified-strip-audit.json` artifact is emitted per §7.4 with `schema_version: 1` and one entry per emitted `unsafe` block.
- (e) Under `--profile verified-strip`, the Rust target passes 6/6 SOS-03 vectors on the bench (per PCDN-SOS-13-005 resolution).
- (f) `BinarySize.text` and `MacrostepCycleCount` measured on the bench under `verified-strip` satisfy the §9.1 targets (≤ +2 % of hand-written Rust).
- (g) [SOS-06 §15](./SOS-06-CONCEPTS.md) amendment records the `verified-strip` measurements alongside the existing `dev-keep` measurements, with both rows in the SOS-06 metric matrix.
- (h) `verified-strip` profile is rejected by the CLI for `--target c` at v1 (§5.4).
- (i) Q5 closure recorded in the SOS-06 §15 amendment: under `verified-strip`, the panic surface is proven unreachable + audit-trail-cited; under `dev-keep`, the surface is preserved.

## 13. Files cited

| Path | Role |
|---|---|
| [`docs/concepts/SOS-07-CONCEPTS.md`](./SOS-07-CONCEPTS.md) | INV-SOS-G (the load-bearing cross-phase invariant); INV-SOS-B (vectors-as-deliverable); INV-SOS-D (chart-as-source). |
| [`docs/concepts/SOS-06-CONCEPTS.md`](./SOS-06-CONCEPTS.md) | §6.2.7 Auditability checklist (Q5); §15 Amendment 005 (bench-validated baseline). |
| [`docs/concepts/SOS-06-A-EVALUATION.md`](./SOS-06-A-EVALUATION.md) | Q5 invariant-violation-surface concern (the user-facing audit gate). |
| [`docs/concepts/SOS-04-CONCEPTS.md`](./SOS-04-CONCEPTS.md) | Rust port idioms; hand-written reference port (the absolute floor). |
| [`docs/concepts/SOS-00-CONCEPTS.md`](./SOS-00-CONCEPTS.md) | §9 cross-port invariants (INV-S6/7/8/12); §6 M7 primitive contract. |
| `tools/sos-codegen/main.py` | CLI surface; gains `--profile` flag per §5.3. |
| `tools/sos-codegen/transliterate_rust.py` | Rust emission; gains `verified-strip` mode + eligibility analysis per §7.3. |
| `rtos_kernel.scxml` | The chart whose bound analysis discharges the obligations cited per §7. |

## 14. Unblocks

Ratification of this phase unblocks:

- Implementation PRs against `tools/sos-codegen/` per the acceptance checklist (§12 a–c, h).
- Audit-tool implementation against the `verified-strip-audit.json` artifact (§7.4).
- A [SOS-06 §15](./SOS-06-CONCEPTS.md) amendment recording bench-validated `verified-strip` measurements alongside `dev-keep`, satisfying §12 (g).
- A future C-target verified-codegen phase (informally named SOS-13-B or assigned a fresh number at authoring time).

## 15. Change log

### 2026-05-23 — Initial draft (Ira)

- Authored `SOS-13-CONCEPTS.md` per the Spec-Before-Code discipline.
- Concretized [INV-SOS-G](./SOS-07-CONCEPTS.md) for the Rust target.
- Defined the `dev-keep` / `verified-strip` profile split (§5).
- Ratified the unchecked-operation catalogue VS-OP-1 through VS-OP-5 (§7.1) as a frozen enumeration with Standards Action registration policy.
- Ratified the SAFETY-comment invariant-citation format (§8) + the `INV-S-CHART-N` series convention (§8.1).
- Named target metrics (§9.1): `BinarySize.text` ≤ 39 500 B, `MacrostepCycleCount` ≤ 820 cyc, Q5 closure via audit trail.
- Declared the cross-target footprint (§9.2): Rust at v1; C and HDL future phases.
- Raised five PCDNs (§16) gating ratification.

Status: 🟡 **drafted; awaiting PCDN walkthrough** before ratification.

## 16. Phase concepts decisions needed (PCDNs)

Five decisions gate ratification. Resolution shape mirrors the EOQ pattern used in [SOS-06-A-EVALUATION.md](./SOS-06-A-EVALUATION.md) §8.

### PCDN-SOS-13-001 — Profile selection granularity

**Question.** Does `--profile {dev-keep,verified-strip}` apply at whole-port granularity only, or do per-region chart annotations (`<region profile="dev-keep"/>`) override the whole-port profile?

**Options.**
- (a) **Whole-port only.** Simplest; one flag, one profile, one audit file. Per-region escape hatch deferred.
- (b) **Whole-port + per-region annotation override.** Allows a single high-risk region to stay on `dev-keep` while the rest of the port runs `verified-strip`. Audit-file shape gains a `region` field per entry.
- (c) **Per-region only, defaulting to `dev-keep` when unannotated.** Most expressive; loses the "one profile per build" simplicity.

**Recommendation.** (a) at v1. Add (b) when a concrete region surfaces that wants the escape hatch. Defer (c) until the use case is real.

**Resolves at.** This doc, before ratification.

### PCDN-SOS-13-002 — Audit-trail file format

**Question.** What serialisation format for `verified-strip-audit.json`?

**Options.**
- (a) **JSON.** Universal tooling; human-readable enough; well-supported by `serde_json` / `json.dumps()`.
- (b) **YAML.** More human-readable for hand-inspection; less universal tooling; ambiguity hazards.
- (c) **Markdown table.** Human-first; programmatic consumption requires a parser.
- (d) **JSON Lines.** One elimination per line; streamable for huge ports; less hierarchical than JSON.

**Recommendation.** (a) JSON. The `verified-strip-audit.json` working name in §7.4 already assumes this. The artifact is machine-first (a tool consumes it) with secondary human-readability; pretty-printed JSON satisfies both. The file extension establishes the format unambiguously.

**Resolves at.** This doc, before ratification.

### PCDN-SOS-13-003 — Default profile

**Question.** Which profile does `tools/sos-codegen/main.py` default to when `--profile` is omitted?

**Options.**
- (a) **`dev-keep` default.** Chart-authoring iteration is the dominant use case; a panicking build is the desired debugging posture; release builds explicitly opt in.
- (b) **`verified-strip` default.** Most builds are release builds; chart-authoring iteration opts in to `dev-keep`.
- (c) **No default; flag is required.** Forces the build script to commit to a profile per invocation.

**Recommendation.** (a) `dev-keep`. This matches the existing v0 emission behaviour (zero migration cost), preserves the audit surface for in-progress chart work, and treats `verified-strip` as an explicit release-build commitment.

**Resolves at.** This doc, before ratification.

### PCDN-SOS-13-004 — Interaction with `cfg!(debug_assertions)`

**Question.** Under `verified-strip`, are `debug_assert!()` macros retained or stripped?

**Options.**
- (a) **Retain `debug_assert!()` even under `verified-strip`.** Provides a defense-in-depth backup during development builds (`cargo build` without `--release`); release builds compile them out as usual via Rust's standard `cfg!(debug_assertions)` mechanism.
- (b) **Strip `debug_assert!()` under `verified-strip` regardless of `cfg!(debug_assertions)`.** Treats `verified-strip` as the strongest commitment: if the chart proves the obligation, even the development-build backup check is unnecessary.
- (c) **Configurable via a sub-flag** (e.g. `--profile verified-strip --keep-debug-assertions`).

**Recommendation.** (a). The standard Rust idiom is to retain `debug_assert!()` and let `cfg!(debug_assertions)` handle release-build elision. Overriding that idiom under `verified-strip` is surprising; using the standard mechanism is least-surprise. (b) erodes the safety net during chart-authoring iteration without clear gain.

**Resolves at.** This doc, before ratification.

### PCDN-SOS-13-005 — Bench-validation gate

**Question.** Must `verified-strip` pass 6/6 SOS-03 vectors on the bench before any `verified-strip` build is ratified?

**Options.**
- (a) **Yes, 6/6 required, no exceptions.** Matches the `dev-keep` ratification gate per [SOS-06 §5.2 (d)](./SOS-06-CONCEPTS.md).
- (b) **6/6 required at the codegen-tool ratification surface; per-chart-amendment runs allow ≤6/6 if the difference traces to a chart change rather than the profile.**
- (c) **≤6/6 acceptable under `verified-strip` if `dev-keep` on the same chart passes 6/6 (the profile is the only difference).** Lets ratification proceed even if a single VS-OP-* eligibility decision is wrong.

**Recommendation.** (a). The whole architectural claim of `verified-strip` is "we proved the developer can't violate the contract." Allowing a verified-strip build to ratify at <6/6 contradicts the claim. If a `verified-strip` run produces fewer passing vectors than `dev-keep`, that's empirical evidence that an eligibility decision was wrong, and the fix is to either narrow the eligibility OR the audit trail's discharge-claim. Either way, ratification waits.

**Resolves at.** This doc, before ratification.

## 16. Change log — Ratification

### 2026-05-23 — Ratified (Ira)

All 5 PCDNs walked and resolved:

| PCDN | Resolution |
|---|---|
| **001 — Profile granularity** | ✅ **Both**: whole-port `--profile {dev-keep,verified-strip}` flag + per-region chart annotation `<region profile="dev-keep"/>`. Maximum flexibility — supports keeping the active-authoring region in `dev-keep` while stripping the rest. |
| **002 — Audit-trail file format** | ✅ **JSONL** — one elimination per line. Diff-friendly; consistent with the existing conformance vector format; trivially scriptable. |
| **003 — Default profile** | ✅ **`dev-keep`** as default; `verified-strip` opt-in via `--profile verified-strip`. Principle of least surprise — verified-strip's panic-strip is irreversible per-build; default-safe Rust posture preserved for unsuspecting users. |
| **004 — `cfg!(debug_assertions)` interaction** | ✅ **Keep `debug_assert!()` under `verified-strip`** — `debug_assertions` is opt-in per Cargo profile; the two axes (debug vs verified-strip) are independent. `release+verified-strip` retains debug_assert eliminations only if the user separately opts out of debug_assertions via Cargo. |
| **005 — Bench-validation gate** | ✅ **Mandatory 6/6**: no `verified-strip` build is ratified without passing the SOS-03 conformance suite end-to-end. Hard gate prevents shipping unchecked code that hasn't run through the chart-derived proof. Cost is bench cycles per release; already part of SOS-04/05's gate. |

Status: 🟢 **ratified**. SOS-13 implementation work (extending `tools/sos-codegen/transliterate_rust.py` with the `--profile verified-strip` path + audit-trail JSONL emission) unblocked.

### 2026-05-23 — PCDN-13-discharge-grammar ratified (Ira)

User walked the chart-side discharge-annotation grammar in a follow-up PCDN session after the wave-1 implementation of `tools/sos-codegen/transliterate_rust.py` made the discharge surface concrete. The grammar is now §7.5; this entry records the ratification.

**Resolution summary.** The chart-side annotation element is `<sos:discharged check="{name}"/>`, carried as a child of `<state>`, `<transition>`, `<onentry>`, or `<onexit>`. The `check` value enumeration is **frozen at four values** at v1: `bounds` (VS-OP-1), `div-by-zero` (future arithmetic VS-OP), `null` (VS-OP-2 / VS-OP-3), and `overflow` (future arithmetic VS-OP). Registration policy is Standards Action — adding a `check` value requires a §15 amendment, matching §7.1's VS-OP catalogue policy. Multiplicity is zero-or-more per parent scope; each element names exactly one `check`. Inheritance is parent-scope-to-its-own-children only; cross-state propagation is forbidden. The annotation is **read by the SOS-13 codegen tool only**; chart semantics under SOS-02 / SOS-03 are unchanged. Codegen behaviour: under `--profile verified-strip`, each discharged operation emits an unsafe-equivalent + SAFETY comment + JSONL audit log entry; under `dev-keep`, the discharge is informative only.

**Authority boundary.** This entry ratifies SOS-13's ownership of the `<sos:discharged>` grammar (the codegen-side semantics, the `check` enumeration, the inheritance rules). The co-landing [SOS-01 §15 — `<sos:discharged>` extension element recognized](./SOS-01-CONCEPTS.md) amendment ratifies SOS-01's recognition of the element as a permitted SCXML extension and reserves future `check`-enum validation as a SOS-13 lint addition (not SOS-01 v1).

**INV-SOS-G enforcement.** §7.5's load-bearing role is making discharge **explicit at the chart layer**. Silent stripping is prevented by construction: codegen cannot emit an unchecked op without a corresponding chart-side `<sos:discharged>` annotation (or, for VS-OP-5, a structural INV-S7 / INV-S8 invariant). This closes a previously-implicit gap between INV-SOS-G's intent and the wave-1 codegen behaviour.

Status: 🟢 **ratified** (continuing). The wave-1 codegen implementation already uses the grammar; this entry brings the spec text into alignment with the implementation per the spec-before-code discipline (the grammar was implementation-led during the wave-1 PR; this §15 entry retroactively ratifies). No further code change required from this entry alone.

### 2026-05-27 — SOS13F1: `INV-S-CHART-N` invariants generator landed (Ira)

Wave-1 follow-on against §8.1. `tools/sos-codegen/sos13_invariants.py` is the pure-function generator that turns a chart's bounds-analysis output into the `INV-S-CHART-N` series artifacts:

- `invariants.rs` — Rust source fragment with one `pub const INV_S_CHART_<N>: &str = "<text>";` per chart-derived invariant, plus a `pub fn cite(id: &str) -> &'static str` dispatch returning the invariant text (or `""` for unknown ids; intentionally non-panicking per §8 — verified-strip's whole job is to remove panic surfaces, so the cite-lookup surface stays panic-free too).
- `INVARIANTS.md` — human-readable mirror with one `## INV-S-CHART-<N>` section per invariant carrying the text, originating chart-site, and status (`derived | declared | discharged`), plus a trailing `## Discharge registry` table cross-referencing each `<sos:discharged>` annotation (§7.5) to the invariant id it discharges.
- An in-memory registry (`dict[str, list[str]]` keyed by `<state>:<check>`) returned to the caller, used by the future `transliterate_rust.py` SAFETY-comment generator (Wave-3) to look up the cite-string for a given discharge site.

The generator's input shape (`BoundsAnalysisInput` dataclass with `chart_id`, `invariants: tuple[InvariantSpec, ...]`, `discharges: tuple[DischargeAnnotation, ...]`) is the minimum surface needed for artifact generation; the binding to SOS-02's host-simulator IR / SOS-03's vector schema is the subject of a follow-on SOS-02/SOS-03 integration commit. The `<sos:discharged>` `check` value enumeration is mirrored verbatim from §7.5's frozen four-value set (`bounds | div-by-zero | null | overflow`); the recognized-checks constant is duplicated in this module to keep it import-cycle-free.

INV-SOS-G traceability: every emitted invariant carries its originating chart site (e.g. `boot.onentry`, `sched_dispatch.guard`) so Wave-3 SAFETY comments can cite both the invariant id AND the chart site that proves it — closing the "silent strip" surface by construction.

Tests at `tools/sos-codegen/tests/test_sos13_invariants.py` (23 tests, all passing): frozen-enum guards, empty-input case, single/mixed invariant cases, explicit-vs-prefix discharge binding, orphan-discharge surface, markdown formatting, Rust source-level well-formedness (balanced braces, escaped quotes), and a `cargo check` round-trip that builds a scratch crate around the generated `invariants.rs` (skipped cleanly when cargo is missing from PATH).

Status: 🟢 **landed**. Wave-3 `transliterate_rust.py` hook to embed the cite-string into SAFETY comments is the next step; no behaviour change in the existing `verified-strip` post-pass from this commit alone.

### 2026-05-27 — SOS13E1: eligibility analysis wiring (Ira)

Wave-5 follow-on against §7.3 (eligibility analysis algorithm) and §12(b) acceptance gate ("Under `--profile verified-strip`, the Rust target emits the unchecked-operation catalogue per §7.1 against eligibility analysis per §7.3"). `tools/sos-codegen/sos13_eligibility.py` is the pure-function oracle that decides, per call site, whether a `VS-OP-*` strip MAY proceed given the chart's bounds-analysis IR.

**Public surface.** `check_eligibility(chart_bounds, vs_op, region_id=None) -> EligibilityVerdict`. The verdict carries `eligible: bool`, `discharging_invariant: str | None` (the `INV-S-CHART-N` or `INV-S7` / `INV-S8` id whose discharge justifies the strip, per INV-SOS-G), `reason: str` (chart-author-friendly explanation), and `vs_op: str` (mirrored from the call so callers threading verdicts can self-describe).

**Per-VS-OP eligibility rules.** Mapped per §7.1 and §7.5:

| `vs_op`   | Discharge source                                                                 | Eligibility rule (this module)                                                                                                       |
|-----------|----------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------|
| VS-OP-1   | `<sos:discharged check="bounds"/>`                                               | Region MUST carry the annotation AND a chart-derived InvariantSpec rooted at the region (explicit binding wins; prefix-match fallback). |
| VS-OP-2   | `<sos:discharged check="null"/>` (Option)                                        | Same shape as VS-OP-1 but `check="null"`.                                                                                            |
| VS-OP-3   | `<sos:discharged check="null"/>` (Result)                                        | Same shape as VS-OP-2 — §7.5 maps both into the `null → (VS-OP-2, VS-OP-3)` row.                                                     |
| VS-OP-4   | Structural reachability — §7.5 explicit carve-out from the discharge grammar      | Region MUST carry at least one chart-derived InvariantSpec rooted at it (the bounds analysis pruned the unreachable branch).        |
| VS-OP-5   | Structural INV-S7 / INV-S8 — §7.5 explicit carve-out                              | Region's invariant `bound_evidence` MUST cite `INV-S7` or `INV-S8`; discharging invariant is the cross-port id, not `INV-S-CHART-N`. |

The conservative default is "ineligible" — every unknown / partial signal refuses the strip per §7.3's "the default is 'keep the check'" principle. Orphan discharges (annotation present, no covering invariant) are refused with an `INV-SOS-G` reason; this closes a previously-implicit gap between the chart-annotation surface and the IR-derived discharge surface.

**Transliterate hook.** `tools/sos-codegen/transliterate_rust.py:apply_verified_strip(...)` gains an optional `bounds_input=None` parameter. When None (the default), behaviour is byte-identical to the wave-1 implementation — the wave-1 chart-annotation-scan path is the discharging authority. When supplied (as a `BoundsAnalysisInput`), the function consults `check_eligibility(...)` at the top of the bounds-strip path; an ineligible verdict refuses the strip (no audit entry written, safe-default emission survives); an eligible verdict embeds the verdict's `INV-S-CHART-N` id into the SAFETY comment per §8 (replacing the wave-1 generic `INV-SOS-G` placeholder). This is additive — wave-1 tests pass unchanged; the wave-5 integration tests pin the new behaviour. The hook is "opportunistic" by design — once the SOS-02 / SOS-03 IR pipeline wires `BoundsAnalysisInput` instances through the codegen CLI in a future wave, every site's SAFETY comment will carry a citable `INV-S-CHART-N` id without further refactor.

**Sister module.** [`tools/sos-codegen/sos13_invariants.py`](../../tools/sos-codegen/sos13_invariants.py) (wave-1E, §15 2026-05-27 SOS13F1 entry) is the upstream artefact generator. Both modules consume the same `BoundsAnalysisInput` dataclass and apply consistent INV-S-CHART-N numbering (`_invariant_id(i)`, 1-based, monotonic in chart-author-declared order). The two surfaces are intentionally factored into separate pure functions so the future SOS-02/SOS-03 integration commit binds the IR once for both.

**Spec deviations / partial wording.** The wave-5 task prompt named a hypothetical `VS-OP-5 = transmute_unchecked` catalogue entry; the ratified §7.1 catalogue lists VS-OP-5 as *non-empty heapless access* discharging via the structural INV-S7 / INV-S8 invariants. This module follows the ratified §7.1 + §7.5 wording. The prompt's "VS-OP-4 = `assume`" framing is reconciled the same way — §7.1 names VS-OP-4 as `core::hint::unreachable_unchecked()`, but both `assume(cond)` and `unreachable_unchecked()` discharge against the same reachability claim, so the module treats them as the same VS-OP. No spec amendment required; this entry records the alignment for reviewers comparing the prompt to the implementation.

**INV-SOS-G traceability.** The module is the codegen-side choke point that enforces INV-SOS-G's "no silent strip" rule from the IR. The two existing enforcement surfaces (the wave-1 chart-annotation scan in `apply_verified_strip`, and the §7.5 grammar's per-scope explicit annotation) gain a third independent confirmation: the IR-derived discharge must also exist. Future regressions are caught by either surface failing.

**Tests.** `tools/sos-codegen/tests/test_sos13_eligibility.py` — 33 tests, all passing. Coverage: frozen-VS-OP enumeration guard, unknown-vs_op raises, structural-VS-OP carve-out, `check`-to-vs_op mapping, per-VS-OP eligible / ineligible / missing-region / orphan-discharge / explicit-binding cases, `chart_bounds=None` short-circuit (parametrised across all five VS-OPs), `bound_evidence`-empty case for VS-OP-5, verdict-shape integrity (vs_op field, discharging_invariant non-None on eligible), TypeError on malformed input, and four integration tests pinning the `apply_verified_strip` hook behaviour (eligible verdict + IR-cited SAFETY comment, ineligible verdict + strip refusal, no-bounds-input preserves wave-1 emission, alignment between IR-layer and annotation-layer refusals). Regression: wave-1 `test_verified_strip.py` (13 tests) + wave-1E `test_sos13_invariants.py` (23 tests) — all passing.

**Files cited.** [`docs/concepts/SOS-13-CONCEPTS.md`](./SOS-13-CONCEPTS.md) §7.1, §7.3, §7.5, §8, §12(b); [`docs/concepts/SOS-07-CONCEPTS.md`](./SOS-07-CONCEPTS.md) INV-SOS-G; [`docs/concepts/SOS-00-CONCEPTS.md`](./SOS-00-CONCEPTS.md) §9 INV-S7 / INV-S8; sister module `tools/sos-codegen/sos13_invariants.py` (wave-1E SOS13F1 §15 entry above); hook site `tools/sos-codegen/transliterate_rust.py:apply_verified_strip` (gains optional `bounds_input` kwarg).

Status: 🟢 **landed**. §12(b) acceptance gate closure pending the SOS-02 / SOS-03 IR-to-codegen wiring that threads `BoundsAnalysisInput` instances through `main.py` to per-site `apply_verified_strip` calls; the eligibility module + hook are ready for that wiring without further refactor.
