# SOS-01 — SCXML Normalization and Lint

**Status:** **🟢 Ratified 2026-05-19.** All five PCDNs resolved by user 2026-05-19; ratification entry in §15. The lint rules in §6 are binding on `rtos_kernel.scxml` from this commit forward.

**Blocks:** SOS-02, SOS-03.

> 🛑 **NO CODE.** Lint rules, ECMAScript-subset freeze, event/state vocabulary, CI shape. No lint runner is implemented in this phase; the runner's shape is specified (§7, §8) and lands in the post-ratification commit that wires the CI gate.

## 0. Authority policy

This doc is the **single normative source** for SOS-side lint rules, the ECMAScript subset legal inside `<script>` blocks, and the frozen event / state-id vocabulary the kernel admits. It does **not** amend [SOS-00 §0] or [SOS-00 §4]; it consumes their authority split and refines the surface that downstream ports cite.

The authority split for SOS-01:

| Concern | Owner | SOS-01 relationship |
|---|---|---|
| SCXML 1.0 document structure, executable content, datamodel semantics | W3C SCXML 1.0 Recommendation (C.R. 2015-09-01) | `derive` — SOS-01 specifies a CI gate that requires `rtos_kernel.scxml` to validate against the W3C XSD (§4). Validation rules are unmodified W3C; SOS-01 does not add or relax XSD structural requirements. |
| The official XSD itself | W3C; published at `https://www.w3.org/2011/04/SCXML/scxml.xsd` | `mirror` — SOS-01 ratifies whether to vendor a local copy (PCDN-SOS-01-001 default: vendor) or fetch on every CI run. The vendored / fetched bytes are unmodified. |
| ECMAScript language base | ECMA-262 | `derive` — SOS-01 freezes a documented subset (§5.1). The subset is strictly smaller than ECMA-262; SOS does not extend the language. The host simulator (SOS-02) implements the subset by hand-compilation (PCDN-SOS-00-005 default) or by an embedded engine; either way, no script in `rtos_kernel.scxml` MAY use a feature outside §5.1. |
| Lint rule semantics, rule ids, severity classes | This doc | `own`. The lint rule set is SOS-01-owned and amended via §15 entries. Rule ids in the `SCXML-LINT-NNN` namespace are append-only (INV-S-LINT-5). |
| The kernel's external event vocabulary (the wire-level contract every port observes) | This doc | `own`. `ExternalEventName` (§5.3) freezes the chart's admitted event set as a Standards-Action enum; adding an event requires a §15 amendment AND a coordinated update to `rtos_kernel.scxml` plus REFERENCE.md plus every port. |
| The kernel's state-id vocabulary | This doc | `own`. `StateId` (§5.4) freezes the chart's state-id set. Same Standards-Action policy as `ExternalEventName`. |
| `xmllint` (libxml2) | upstream libxml2 project | `derive` — SOS-01 names `xmllint --schema` as the CI validator. Any libxml2 release implementing `--schema` is permitted (§4); SOS-01 does not pin a specific version. |
| Parent doc [SOS-00] | SOS-00 | parent. SOS-01 cites SOS-00 by section number for every term it reuses. Restatement is forbidden per parent CLAUDE.md "Definitions — reference vs. restatement". |

INV-S-LINT-0 (crawl boundary, mirroring [SOS-00 §0] INV-S1): SOS-01 reviewers consult this doc plus the cited section numbers in W3C SCXML 1.0 and ECMA-262 by published reference. They do not crawl the full W3C / ECMA texts as part of normal SOS-01 work.

## 1. Purpose

Establish:

1. A **schema-validation gate** that guarantees `rtos_kernel.scxml` parses cleanly against the W3C SCXML 1.0 XSD on every commit. The gate closes [SOS-00 §12] (b), which SOS-00 deferred to this phase.
2. A **style lint** for the .scxml that prevents the specific failure modes a 580-line single-file statechart is prone to: oversized inline scripts that become unreviewable, ungoverned transitions that admit silent semantic drift, ECMAScript constructs whose semantics are not deterministically realisable in a transpiled port, and comment-density drops that erode the chart's role as discoverable spec.
3. A **frozen ECMAScript subset** that closes [SOS-00 §4] row "ECMA-262" — pinning the exact constructs `<script>` blocks MAY use. Closing this surface unblocks SOS-02's choice between hand-compilation and AST-walk (PCDN-SOS-01-002 inherits PCDN-SOS-00-005).
4. A **frozen external-event vocabulary** (`ExternalEventName`) and **frozen state-id vocabulary** (`StateId`) — the wire-level contract every downstream port and every conformance vector consumes. Until these are frozen, SOS-03 cannot author vectors against a stable event-name surface.
5. A **CI integration shape** that makes the gate enforceable rather than aspirational. SOS-01 does NOT create the CI workflow file (that's the implementation commit's job); SOS-01 specifies its shape so the implementation has no design surface left to litigate.

Without this layer:

- A future edit to `rtos_kernel.scxml` could land malformed SCXML and break SOS-02 / SOS-04 / SOS-05 in three separate diagnostics rather than one CI failure.
- The `<script>` block at `rtos_kernel.scxml:77-165` (the helper-function block) could grow without bound. At 580 lines for the whole chart, an unbounded helper block dominates review burden.
- The hand-compilation port (SOS-02 v1) needs a finite ECMAScript surface to translate; "whatever the chart happens to use today" is not a contract.
- Conformance vectors (SOS-03) need a frozen event-name set to author against. Adding an event mid-vector-write retroactively invalidates every vector that touched the prior set.

## 2. Problem statement

**Current state (as of 2026-05-19, post-SOS-00 ratification):**

- `rtos_kernel.scxml` exists at the SOS repo root, 580 lines, single file. It is well-written and internally consistent; this phase is not a bug-hunt.
- There is no CI on this subrepo. There is no parent-repo CI gate covering this subrepo's contents. The .scxml has never been validated against the W3C XSD by automated tooling.
- [SOS-00 §12] item (b) explicitly deferred the `xmllint --schema` automation to SOS-01 (citing "SOS-01 will automate this in CI").
- [SOS-00 §4] left the ECMAScript subset as "a documented SOS-01 subset" — a placeholder, not a frozen enum.
- [SOS-00] never enumerated the external event names the chart admits or the state ids it declares; SOS-02 / SOS-03 / SOS-04 / SOS-05 need both lists frozen before they can author against them.
- The chart's largest `<script>` block lives at `rtos_kernel.scxml:77-165` (the helpers — `readyq_init`, `ready_push`, `ready_remove`, `ready_pop_highest`, `waiters_insert`, `block_current`, `unblock`, `waiter_cancel`, `pick_next`). That is **eight helper functions in one CDATA block**, ~88 lines. The next-largest single-transition inline script is the `sched.resume` body at `rtos_kernel.scxml:548-571` (the pend-tick flush loop, ~24 lines). The third-largest is the `sys.tick` body at `rtos_kernel.scxml:226-252` (~27 lines).

**The pressure that motivates SOS-01:**

Four pressures compound:

1. **Spec drift via inline-script growth.** The .scxml's normative power derives from its small size; reviewers can hold the whole chart in working memory. The helper block at `rtos_kernel.scxml:77-165` is already at the upper bound of what fits in a single visual pass. Without a cap, the next helper added (say, a priority-bitmap optimisation) lands inside the same block and the chart silently loses reviewability.

2. **ECMAScript surface drift.** Today the chart uses `var`-declarations, `for` loops, array `push`/`shift`/`splice`/`indexOf`, object property access, and arithmetic. There is no closure-over-outer-scope, no `async`, no `eval`, no regex, no generator, no destructuring. A future edit could land any of those without anyone noticing — until SOS-02's hand-compilation port tries to translate and fails. Freezing the subset now turns "lint fails CI" into the failure mode rather than "port fails to build six weeks later".

3. **Event-name and state-id contract drift.** [SOS-00 §3] defines `Syscall` as "an external event admitted by the statechart's `syscalls` region" and points at REFERENCE.md for the table. REFERENCE.md is informative ([SOS-00 §4]). The .scxml is normative. If those two drift, downstream phases consume the inconsistent surface. Freezing both in this doc as Standards-Action enums makes the drift mechanically detectable.

4. **PCDN-SOS-00-005 inheritance.** [SOS-00 §15] resolved PCDN-005 with "(b) hand-compiled as the bootstrap form, AST/trace deferred to SOS-01". SOS-01 owns the resolution. The AST/trace question is not blocking SOS-02 (the bootstrap form proceeds either way) but it is blocking the architectural framing — SOS-02's crate layout differs noticeably between "single hand-compiled module" and "hand-compiled + AST walker side-by-side". SOS-01 closes it.

**Why this is the right time:**

- SOS-00 is ratified; the vocabulary used by lint-rule rationale ("kernel-aware ISR", "macrostep", "syscall transport") is stable and citable.
- The .scxml is at a known-good state. Authoring lint rules against a known-good chart lets us classify each rule as "passes-clean today" vs "requires chart edit", which §10 resolves explicitly.
- SOS-02 has not started. Freezing the ECMAScript subset before SOS-02 begins coding gives the simulator a fixed translation target rather than a moving one.
- SOS-03 has not started. Freezing the event-name and state-id vocabulary before SOS-03 begins authoring vectors gives the conformance suite a fixed contract surface.

## 3. Canonical glossary

Terms SOS-01 introduces. Reuses from [SOS-00 §3] are cited, not restated.

| Term | Definition | Owner relationship |
|---|---|---|
| **Lint rule** | A normative statement of shape "the .scxml MUST/SHOULD/MAY [property]", assigned a stable id `SCXML-LINT-NNN`, a severity (`error`/`warning`/`info`), a rationale, an example violation, and an example fix. The full set lives in §6. | SOS-01-owned. |
| **Lint conformance** | A property of a specific .scxml at a specific commit: "every `error`-severity rule passes; every `warning` rule passes OR has an explicit grace-period waiver in §10". An .scxml that is lint-conforming is permitted to land on the default branch; one that is not is rejected by CI (§7). | SOS-01. |
| **Schema conformance** | A property of a specific .scxml: "validates against the W3C SCXML 1.0 XSD via `xmllint --schema`". Schema conformance is a strict prerequisite for lint conformance — the lint rules in §6 assume the document already parses. | SOS-01 (the test is owned here); the schema itself is W3C. |
| **Conformance level (SOS-01)** | A binary classification of an .scxml: **schema-conforming** (passes XSD only) or **lint-conforming** (passes XSD AND every §6 `error`-rule AND every non-waived §6 `warning`-rule). Lint-conforming is a superset. CI gates on lint-conforming. | SOS-01. |
| **Event vocabulary** | The frozen set of external event names the chart admits, enumerated in §5.3 as `ExternalEventName`. The lint rule `SCXML-LINT-013` enforces that every `<transition event="..."/>` in the chart names a value from this enum (plus the chart-internal `kernel.boot.done` and `sched.run`). | SOS-01-owned (Standards Action registration). |
| **State-id vocabulary** | The frozen set of state ids the chart declares, enumerated in §5.4 as `StateId`. Adding a state id requires a §15 amendment to this doc AND a coordinated update of `rtos_kernel.scxml` AND any conformance vector that snapshots state. | SOS-01-owned. |
| **Permitted ECMAScript feature** | A construct legal inside any `<script>` block. The full set is §5.1 `ECMAScriptFeature` rows marked `Permitted`. Anything not on the list is forbidden by `SCXML-LINT-009`. | SOS-01-owned (Standards Action). |
| **Helper extraction** | The structural refactor SOS-01 mandates when a `<script>` block exceeds the cap in `SCXML-LINT-001`: extract one or more named functions out of the inline block into a separate top-level `<script>` block (or out of the chart entirely if the host environment supports import — currently it does not). | SOS-01. |
| **Grace-period waiver** | A §10 exception that lets an existing `warning` rule remain at `warning` (not `error`) for a named span, with a dated commitment to upgrade. Used only when an existing chart construct violates a rule that would otherwise be `error`; the waiver makes day-one adoption possible without same-PR chart edits. | SOS-01-owned. |

**Terms reused from [SOS-00 §3] without restatement:** `Statechart`, `Datamodel`, `Macrostep`, `Microstep`, `Kernel`, `Port`, `Bench port`, `Conformance vector`, `State trace`, `TCB`, `Ready queue`, `Wait-queue`, `Syscall`, `Syscall transport`, `Tick`, `Critical section`, `Scheduler suspend`, `Kernel-aware ISR`, `Kernel-blind ISR`, `Idle task`, `Boot`. Citation form: `[SOS-00 §3]`.

## 4. Source-of-truth map

| Source | Pinned form | Used surface | Relationship |
|---|---|---|---|
| W3C SCXML 1.0 Recommendation | Recommendation, 1 September 2015 (`https://www.w3.org/TR/2015/REC-scxml-20150901/`) | §3.1 (Document Structure), §3.4 (`<parallel>`), §3.13 (transition selection + macrostep), §C.2 (ECMAScript Data Model). | `derive`. SOS-01 cites by section number; the full text is not crawled. |
| W3C SCXML 1.0 XSD | `https://www.w3.org/2011/04/SCXML/scxml.xsd`. Vendored bytes pinned at the file SHA stored in the SOS repo at `docs/specs/scxml.xsd` (PCDN-SOS-01-001 resolves the vendor-vs-fetch question; default is vendor). | The full schema. | `mirror`. The vendored bytes match the W3C-published bytes; SOS-01 ratifies the SHA in §15 at the commit that lands the vendor. |
| ECMA-262 (ECMAScript) | A documented SOS-01 subset (§5.1). | Arithmetic, comparison, array `push` / `shift` / `splice` / `indexOf` / `.length`, object property read/write, `if`/`else`, `for` loops, `var` declarations, function declarations at top-level script-block scope, the `_event` and datamodel-declared identifiers. | `derive`. The subset is strictly smaller than ECMA-262; SOS does not extend the language. |
| `xmllint` (libxml2 binary) | "any version that supports `--schema`" (libxml2 ≥ 2.9.0 is the floor; the actual binary used in CI is whichever the GitHub Actions Ubuntu runner ships). | `xmllint --schema <xsd> rtos_kernel.scxml --noout` — schema-validation mode only. SOS-01 does not depend on libxml2's xpath, xinclude, or pattern engines. | `derive`. |
| `rtos_kernel.scxml` (this repo) | Pinned at the SHA the SOS-01 ratification commit lands on. | The full statechart — every state, transition, script block, datamodel field. Lint rules §6 are derived from inspection of this exact form. | `own`. |
| `docs/REFERENCE.md` (this repo) | This repo, this SHA. | Topology overview, syscall ABI table — informative cross-check for the §5.3 / §5.4 frozen enums. | `own`. Informative when lint rules cite it; the .scxml wins on disagreement per [SOS-00 §0]. |
| [SOS-00] | Ratified 2026-05-19. | §0 authority policy, §3 glossary, §4 source-of-truth map, §5 frozen enums (`TaskState`, `ReturnCode`, `SyscallTransport`, `M7KernelPriorityBand`, `FpuPolicy`), §9 invariants (INV-S1 through INV-S15). | parent. SOS-01 cites SOS-00 by section number; SOS-01 does not amend SOS-00 (an amendment to SOS-00 requires a separate §15 entry on SOS-00 itself, per parent CLAUDE.md). |

### 4.1 Vendor-vs-fetch decision for the XSD (PCDN-SOS-01-001)

Two options for the CI gate's source of the SCXML 1.0 XSD:

(a) **Fetch from W3C on every CI run.** `curl https://www.w3.org/2011/04/SCXML/scxml.xsd | xmllint --schema /dev/stdin rtos_kernel.scxml --noout`. Pros: zero in-repo binary, automatically tracks any W3C correction. Cons: network-dependent — CI hangs / fails if W3C is down; the "automatic tracking" cuts both ways (a W3C correction could break our CI without a SOS-01 §15 amendment); requires CI to have network egress to `www.w3.org`.

(b) **Vendor the XSD at a pinned SHA.** Land `docs/specs/scxml.xsd` in the SOS repo at the W3C-published bytes, ratify the SHA in [SOS-01 §15], invoke `xmllint --schema docs/specs/scxml.xsd rtos_kernel.scxml --noout`. Pros: hermetic CI; the XSD is part of the auditable spec lineage; W3C downtime never blocks a PR. Cons: in-repo binary that needs occasional refresh if W3C corrects.

**Default recommendation: (b) vendor.** SCXML 1.0 has been a Recommendation since 2015-09-01; the rate of W3C corrections is effectively zero. Hermetic CI is the load-bearing property for spec-lineage repos like SOS.

## 5. Frozen enums

SOS-01 ratifies five frozen enums. Each carries a registration policy per the parent CLAUDE.md "Frozen enumerations — registration policy" convention.

### 5.1 `ECMAScriptFeature` — Standards Action

The permitted-feature surface for `<script>` blocks in `rtos_kernel.scxml`. The lint rule `SCXML-LINT-009` enforces the forbidden list; any construct on the forbidden list is a hard lint error.

| Feature | Permitted? | Notes |
|---|---|---|
| Arithmetic operators (`+`, `-`, `*`, `/`, `%`) on `Number` | ✅ | Integer-typed in this chart; ports MAY use any integer width ≥ 32 bits. |
| Comparison operators (`==`, `!=`, `<`, `<=`, `>`, `>=`) | ✅ | `===` and `!==` are also permitted; the chart at HEAD uses only `==`/`!=`. |
| Logical operators (`&&`, `||`, `!`) | ✅ | |
| `var` declarations | ✅ | The only permitted declaration form for v1. Rationale: hand-compilation target is C / Rust; `var` has the simplest scoping rules (function-scoped). |
| `let` declarations | ❌ | Forbidden by `SCXML-LINT-009`. Block-scoping complicates hand-compilation; chart does not currently use `let`. |
| `const` declarations | ❌ | Forbidden by `SCXML-LINT-009`. Datamodel `<data>` declarations cover the constant-binding need. |
| `function` declarations (top-level of a `<script>` block) | ✅ | The chart's helper block at `rtos_kernel.scxml:77-165` defines nine such helpers. |
| Closures over outer-scope variables | ❌ | Forbidden by `SCXML-LINT-009`. Hand-compilation cannot reproduce closure capture in C; chart at HEAD avoids them (every helper reads / writes the datamodel directly, which is the global SCXML context, not a captured closure). |
| Arrow functions | ❌ | Forbidden. Avoids the closure question entirely. |
| `if` / `else` | ✅ | |
| `for` loops (C-style: `for (var i = 0; i < N; i++)`) | ✅ | The chart uses this form exclusively. |
| `for...in` / `for...of` | ❌ | Forbidden. Datamodel arrays are integer-indexed; `for...in` has well-known footguns; `for...of` requires iterator protocol. |
| `while` / `do-while` | ✅ | Used at `rtos_kernel.scxml:552` (the pend-tick flush) and at `rtos_kernel.scxml:111` (the `waiters_insert` priority scan). |
| `switch` | ❌ | Forbidden. Use chained `if`/`else if`. Rationale: the host port hand-compiles to a target language whose `switch` semantics differ (C fallthrough vs Rust `match` exhaustiveness); chained `if` is portable. |
| Array `.push` / `.shift` / `.splice` / `.indexOf` / `.length` | ✅ | The chart uses all five. |
| Array `.pop` / `.unshift` / `.slice` / `.concat` / `.map` / `.filter` / `.reduce` / `.find` / `.forEach` / `.sort` / `.reverse` | ❌ | Forbidden. The chart at HEAD uses none of these; the permitted set is the minimal viable. |
| Object property access (`obj.field`, `obj["field"]`) | ✅ | Used throughout. |
| Object literal construction (`{ id: i, prio: 0, ... }`) | ✅ | Used in boot (`rtos_kernel.scxml:177-179`, etc.). |
| Destructuring (object or array) | ❌ | Forbidden. Hand-compilation target. |
| Spread / rest (`...`) | ❌ | Forbidden. |
| Template literals (backtick strings) | ❌ | Forbidden. The chart uses no strings. |
| Regular expressions | ❌ | Forbidden. |
| `eval` / `Function` constructor | ❌ | Forbidden. Determinism. |
| `async` / `await` | ❌ | Forbidden. The chart is run-to-completion; async breaks macrostep atomicity (INV-S2). |
| `Promise` | ❌ | Forbidden. As above. |
| `Generator` (`function*` / `yield`) | ❌ | Forbidden. |
| `class` declarations | ❌ | Forbidden. Use object literals + free functions. |
| Prototype mutation (`obj.__proto__`, `Object.setPrototypeOf`) | ❌ | Forbidden. |
| Getters / setters | ❌ | Forbidden. |
| `try` / `catch` / `throw` / `finally` | ❌ | Forbidden. The chart never throws; error returns travel via `rc` (per [SOS-00 §5.2]). |
| `Math.random`, `Math.floor`, `Math.ceil`, `Math.abs`, etc. | ❌ | Forbidden. Determinism (`Math.random`) and unnecessary surface (the chart performs no floating-point math). |
| `Date.now` / `Date()` / `new Date(...)` | ❌ | Forbidden. The chart's only time source is `tick_count`, mutated by `sys.tick`. |
| `console.log`, `console.error`, etc. | ❌ | Forbidden. Side-effecting; not deterministic across ports. |
| `JSON.parse`, `JSON.stringify` | ❌ | Forbidden. |
| `typeof` | ❌ | Forbidden. The datamodel is statically shaped; `typeof` reads ECMAScript runtime type tags which are not portable to a hand-compiled C target. |
| `instanceof` | ❌ | Forbidden. |
| `void` operator | ❌ | Forbidden. |
| The implicit `_event` identifier | ✅ | Per W3C SCXML 1.0 §C.2: in event-driven transitions, `_event.data` holds the syscall parameter struct. Used throughout the chart's `syscalls` region. |
| The implicit `_sessionid`, `_name`, `_ioprocessors` identifiers | ❌ | Forbidden. Not used by the chart; declaring them out of scope keeps the host-port surface minimal. |

**Registration policy:** Standards Action. Adding a permitted feature requires a §15 amendment AND a coordinated update to the SOS-02 hand-compilation port to demonstrate the construct compiles cleanly to the target language(s).

### 5.2 `LintRuleSeverity` — Specification Required

| Value | Meaning | CI behaviour |
|---|---|---|
| `error` | Lint failure. CI rejects the PR. Cannot be merged. | `xmllint`-equivalent: exit code non-zero, GitHub Actions step fails, PR-blocking. |
| `warning` | Lint warning. CI surfaces the warning (PR comment or annotation) but does NOT block merge. Used for rules that the chart at HEAD does not yet satisfy AND that require coordinated chart edits to upgrade. The §10 grace-period table tracks which `warning`-severity rules are awaiting upgrade and by when. | Exit code 0; annotation present; merge permitted. |
| `info` | Lint informational. CI surfaces as a PR comment. Never blocks. Used for stylistic suggestions where the rule's authors are not yet confident enough to assert `MUST`/`SHOULD`. | Exit code 0; informational only. |

**Registration policy:** Specification Required. Severity values are unlikely to change; adding e.g. `notice` is a SOS-01 amendment.

### 5.3 `ExternalEventName` — Standards Action

Enumeration of every external event admitted by `rtos_kernel.scxml`. Derived from inspection of the chart's `<transition event="..."/>` attributes outside the `<onentry>` `<raise>` set. Internal events (`kernel.boot.done`, `sched.run`) are listed in §5.5 below.

| Event name | Region | Source | Payload (`_event.data`) | Result |
|---|---|---|---|---|
| `task.create` | `syscalls/sys_idle` | Task context | `{ id, prio }` | `rc`: `RC_OK` / `RC_INVAL` |
| `task.delay` | `syscalls/sys_idle` | Task context | `{ ticks }` | `rc`: `RC_OK` (ticks ≤ 0 ⇒ yield) |
| `task.yield` | `syscalls/sys_idle` | Task context | — | `rc`: `RC_OK` |
| `task.suspend` | `syscalls/sys_idle` | Task context | `{ id }` | `rc`: `RC_OK` / `RC_INVAL` |
| `task.resume` | `syscalls/sys_idle` | Task context | `{ id }` | `rc`: `RC_OK` / `RC_INVAL` |
| `sem.create` | `syscalls/sys_idle` | Task context | `{ id, initial, max }` | `rc`: `RC_OK` |
| `sem.take` | `syscalls/sys_idle` | Task context | `{ sid, timeout }` | `rc`: `RC_OK` / `RC_TIMEOUT` / `RC_INVAL`; final via `tcb[id].msg` if blocked |
| `sem.give` | `syscalls/sys_idle` | Task context | `{ sid }` | `rc`: `RC_OK` / `RC_INVAL` / `RC_FULL` |
| `sem.give_from_isr` | `syscalls/sys_idle` | ISR context | `{ sid }` | (no `rc`; ISR) |
| `queue.create` | `syscalls/sys_idle` | Task context | `{ id, cap }` | `rc`: `RC_OK` |
| `queue.send` | `syscalls/sys_idle` | Task context | `{ qid, msg, timeout }` | `rc`: `RC_OK` / `RC_FULL` / `RC_INVAL` |
| `queue.receive` | `syscalls/sys_idle` | Task context | `{ qid, timeout }` | `rc`: `RC_OK` / `RC_EMPTY` / `RC_INVAL`; payload via `tcb[id].msg` |
| `queue.send_from_isr` | `syscalls/sys_idle` | ISR context | `{ qid, msg }` | (no `rc`; ISR) |
| `sys.tick` | `tick_service/tick_idle` | ISR context | — | advances `tick_count`; expires delays / timeouts; raises `sched.run` |
| `crit.enter` | `protection/prot_idle` | Task context | — | `irq_nest++` |
| `crit.exit` | `protection/prot_idle` | Task context | — | `irq_nest--`; raises `sched.run` |
| `sched.suspend` | `protection/prot_idle` | Task context | — | `sched_lock++` |
| `sched.resume` | `protection/prot_idle` | Task context | — | `sched_lock--`; on zero, flushes `pend_ticks`; raises `sched.run` |

**Cardinality at HEAD:** 18 external events.

**Registration policy:** Standards Action. Adding an external event requires:
1. A §15 amendment to this doc.
2. A coordinated edit to `rtos_kernel.scxml` adding the matching `<transition event="..."/>`.
3. An update to `docs/REFERENCE.md` reflecting the new ABI row.
4. Conformance-vector regen (SOS-03) covering the new event's success and failure paths.
5. Per-port update (SOS-04, SOS-05) implementing the corresponding syscall wrapper.

Removing or renaming an event has the same gate plus an explicit deprecation notice in the §15 entry citing every downstream artifact reviewed (INV-S-LINT-3 makes this append-only-with-deprecation rather than free-form mutable).

### 5.4 `StateId` — Standards Action

Enumeration of every state id declared in `rtos_kernel.scxml`. Derived from inspection of the chart's `<state id="..."/>` and `<parallel id="..."/>` attributes.

| State id | Containing region | Kind | Notes |
|---|---|---|---|
| `boot` | (root) | `<state>` | One-shot init; transitions to `running` on `kernel.boot.done`. |
| `running` | (root) | `<parallel>` | The four-region concurrent topology. |
| `scheduler` | `running` | `<state>` | Region 1 of 4. |
| `sched_idle` | `running/scheduler` | `<state>` | Sole child of `scheduler`. Initial state. |
| `tick_service` | `running` | `<state>` | Region 2 of 4. |
| `tick_idle` | `running/tick_service` | `<state>` | Sole child of `tick_service`. Initial state. |
| `syscalls` | `running` | `<state>` | Region 3 of 4. |
| `sys_idle` | `running/syscalls` | `<state>` | Sole child of `syscalls`. Initial state. |
| `protection` | `running` | `<state>` | Region 4 of 4. |
| `prot_idle` | `running/protection` | `<state>` | Sole child of `protection`. Initial state. |

**Cardinality at HEAD:** 10 state ids (2 top-level + 4 region parents + 4 region idles).

**Registration policy:** Standards Action. Same gates as `ExternalEventName`. Renames are coordinated commits, never silent.

### 5.5 `LintRuleId` — Standards Action

The naming convention for lint rules. Format: `SCXML-LINT-NNN` where `NNN` is a zero-padded three-digit decimal monotonically assigned at rule-creation time. Once assigned, a `LintRuleId` is stable for the lifetime of the SOS-01 lineage; a removed rule keeps its id reserved (marked "retired" in the §15 change log).

The §6 set at SOS-01 draft uses ids `SCXML-LINT-001` through `SCXML-LINT-018`.

**Registration policy:** Standards Action.

### 5.6 Internal events (informative)

For completeness and to make `SCXML-LINT-013` precise, the chart's internal-event vocabulary (events raised by `<raise>` inside the chart and consumed by transitions in the chart, never originating externally):

| Event name | Raised at | Consumed at |
|---|---|---|
| `kernel.boot.done` | `boot/onentry/script` (after `pick_next()`) | `boot → running` transition |
| `sched.run` | every state-mutating transition (16 raise sites at HEAD) | `scheduler/sched_idle` transitions (two: `sched_lock == 0` and `sched_lock > 0`) |

Internal events are **not** part of the `ExternalEventName` enum and are not consumed by ports. They are mentioned here so `SCXML-LINT-013` ("every `<transition event="X"/>` names a value from `ExternalEventName` ∪ internal events") can be stated precisely.

## 6. Lint rules

The load-bearing section. Each rule has:
- **id** (`SCXML-LINT-NNN`)
- **severity** at SOS-01 ratification (may differ from "ideal" severity if §10 records a grace-period waiver)
- **normative statement** in RFC-2119 keywords
- **rationale**
- **example violation** (a fragment derived from the actual chart's shape or a plausible drift from it)
- **example fix**

Rules are grouped by category. The total at SOS-01 draft is 18 rules. §10 reconciles each rule against the .scxml at HEAD.

### 6.1 Schema rules

#### SCXML-LINT-001 — Schema validation (severity: `error`)

**Normative:** The .scxml MUST validate against the W3C SCXML 1.0 XSD (PCDN-SOS-01-001-resolved location) when invoked as `xmllint --schema <xsd> rtos_kernel.scxml --noout`. Exit code MUST be 0; stderr MUST be empty.

**Rationale:** Schema conformance is the ground floor. Without it, the document is not SCXML and no other rule has a defined target.

**Example violation:**
```xml
<scxml version="1.0" datamodel="ecmascript">
  <state id="boot">
    <transition target="running"/>   <!-- no event attr; legal on terminal but suspicious -->
    <unknown_tag/>                   <!-- not in the SCXML namespace; rejected by XSD -->
  </state>
</scxml>
```

**Example fix:** remove `<unknown_tag/>`; add the missing `xmlns="http://www.w3.org/2005/07/scxml"` if absent; consult the XSD for the specific element-content model.

### 6.2 Structural rules

#### SCXML-LINT-002 — Single root `<scxml>` element with explicit attributes (severity: `error`)

**Normative:** The root element MUST be `<scxml>` with `xmlns="http://www.w3.org/2005/07/scxml"`, `version="1.0"`, `datamodel="ecmascript"`, and `initial="..."` set to a legal `StateId`. No other attributes on the root element.

**Rationale:** Pins the chart's identity. Drift on the `datamodel` attribute (e.g. to `"null"` or a future `"ecmascript+sos"`) silently changes script semantics.

**Example violation:** root element with `datamodel="null"` or with missing `version`.

**Example fix:** restore the canonical attribute set.

#### SCXML-LINT-003 — Exactly one `<datamodel>` declaration (severity: `error`)

**Normative:** The chart MUST contain exactly one top-level `<datamodel>` block. Nested `<datamodel>` declarations (W3C SCXML 1.0 permits them inside `<state>`) MUST NOT appear in `rtos_kernel.scxml`.

**Rationale:** Per-state datamodels add scoping complexity that the hand-compilation port (SOS-02) does not support at v1. The chart's datamodel is global; keeping it that way keeps hand-compilation tractable.

**Example violation:**
```xml
<state id="syscalls">
  <datamodel>
    <data id="local_counter" expr="0"/>
  </datamodel>
  ...
</state>
```

**Example fix:** move the data declaration to the top-level `<datamodel>` block; rename to avoid collisions.

#### SCXML-LINT-004 — No nested `<parallel>` elements (severity: `error`)

**Normative:** The chart MAY contain at most one `<parallel>` element; nested `<parallel>` inside another `<parallel>` MUST NOT appear. The chart at HEAD has exactly one (`<parallel id="running">`) and this is the maximum.

**Rationale:** Nested parallels combinatorially explode the configuration set the simulator and ports must reason about. The chart's four-region split is already at the upper bound of what a single statechart admits without becoming unreviewable.

**Example violation:**
```xml
<parallel id="running">
  <parallel id="inner">
    <state id="a"/>
    <state id="b"/>
  </parallel>
</parallel>
```

**Example fix:** flatten — pull the inner regions up into siblings of `running`'s existing regions, OR factor into a second top-level state with an explicit transition surface.

### 6.3 Script-block size rules

#### SCXML-LINT-005 — `<script>` block length cap (severity: `warning` — see §10) (PCDN-SOS-01-003)

**Normative:** Every `<script>` block (whether inside `<onentry>`, `<onexit>`, or as a transition's inline executable content) SHOULD be ≤ 40 lines, counting non-blank non-comment lines inside the `<![CDATA[ ... ]]>` wrapper. Blocks > 40 lines MUST be either (a) extracted via *helper extraction* (per §3 glossary) into the top-level `<script>` block as named functions called by short transition-body scripts, or (b) explicitly waived in this rule's §10 grace-period table with a dated commitment.

**Rationale:** A 40-line inline script sits comfortably within what a reviewer can audit in a single visual pass while giving authors leeway for blocks that naturally land a little beyond the original 30-LOC proposal. The chart's helper block at `rtos_kernel.scxml:77-165` (~88 lines counting comments and blanks; ~50 non-blank non-comment) is currently the only large block; extracting *individual helper functions* into their own `<script>` siblings would push the chart from one well-organised block to nine separate blocks with the same content. PCDN-SOS-01-003 ratified the cap value at 40 LOC (raised from the original-proposed 30 to give authoring leeway).

**Example violation:** a single transition's inline body that exceeds 40 lines (e.g. a hypothetical complex `sem.take_with_priority_inheritance` body).

**Example fix:** extract the body's logic into a named function in the top-level helper block; replace the inline body with `<script>helper_name(/* args */);</script>`.

**Example violation (current chart):** the top-level helper block at `rtos_kernel.scxml:77-165` is ~88 lines as a single `<script>` (multi-helper). §10 records a grace-period waiver: the top-level helper block is exempt from the per-block cap because its content IS the helper-extraction target. The per-block cap applies to `<onentry>` / `<onexit>` / transition-inline scripts.

#### SCXML-LINT-006 — `<onentry>` and `<onexit>` script size cap (severity: `error`)

**Normative:** Inline `<script>` content directly inside an `<onentry>` or `<onexit>` element MUST be ≤ 5 lines (excluding blank and comment lines). Longer logic MUST be extracted to a named helper.

**Rationale:** `<onentry>` and `<onexit>` are the entry/exit hooks for a state; logic placed there runs on every state entry/exit and is part of the chart's spec-level contract. Inline logic > 5 lines hides invariant-affecting behaviour from reviewers who scan transition tables.

**Example violation:**
```xml
<onentry>
  <script><![CDATA[
    readyq_init();
    for (var i = 0; i < MAX_TASKS; i++) { ... }   // 6+ more lines inline
    pick_next();
  ]]></script>
</onentry>
```

**Example fix:** the chart at `rtos_kernel.scxml:171-194` is currently a violation candidate — the `boot/onentry` block contains ~17 non-blank lines. §10 reconciles: classify as `warning` at SOS-01 ratification with grace-period to SOS-02 land. Recommended fix: extract `boot_init()` helper into the top-level script block, leaving:
```xml
<onentry>
  <script>boot_init();</script>
  <raise event="kernel.boot.done"/>
</onentry>
```

### 6.4 Determinism rules

#### SCXML-LINT-007 — No non-deterministic ECMAScript primitives (severity: `error`)

**Normative:** `<script>` blocks MUST NOT invoke `Math.random`, `Date.now`, `new Date(...)`, `console.*`, `eval`, or the `Function` constructor. (Subset of §5.1 forbidden features; called out separately because these are the load-bearing determinism rules.)

**Rationale:** Conformance vectors (SOS-03) compare port traces field-for-field. Any source of non-determinism inside the kernel breaks the equivalence test for all ports simultaneously. The chart's only time source is `sys.tick` (external); its only randomness source is the test harness's event-ordering choice.

**Example violation:**
```xml
<script>
  if (Math.random() < 0.5) { resched = true; }
</script>
```

**Example fix:** remove the random branch; if randomness is required for a test (it isn't — kernel behaviour is deterministic by spec), the harness MUST inject the choice as an event, not call `Math.random` inside a script.

#### SCXML-LINT-008 — No `async` / `await` / `Promise` / generators (severity: `error`)

**Normative:** `<script>` blocks MUST NOT use `async`, `await`, `Promise`, `function*`, or `yield`.

**Rationale:** SCXML 1.0 macrostep semantics (§3.13) require run-to-completion. Async constructs introduce continuation points inside what is supposed to be an atomic microstep, violating INV-S2.

**Example violation:**
```xml
<script>
  async function fetch_thing() { ... }
  fetch_thing().then(...);
</script>
```

**Example fix:** remove the async surface; restructure as event-driven (a synchronous body raises an event, and the response arrives as a separate external event).

#### SCXML-LINT-009 — ECMAScript feature subset (severity: `error`)

**Normative:** `<script>` blocks MUST use only features marked `Permitted` in §5.1 `ECMAScriptFeature`. Any forbidden feature is a hard lint error.

**Rationale:** Pins the hand-compilation surface (PCDN-SOS-00-005). The host port translates the permitted subset; the forbidden set is rejected at lint time rather than at port-build time.

**Example violation:** `let x = 0;`, `const N = 8;`, `for (var t of tcb)`, `{ id, prio } = _event.data;`, `class TCB { ... }`.

**Example fix:** rewrite using only the permitted constructs. The chart at HEAD passes this rule.

### 6.5 Transition discipline rules

#### SCXML-LINT-010 — Every external `<transition event="..."/>` is documented (severity: `error`)

**Normative:** Every `<transition>` element whose `event` attribute names a value from `ExternalEventName` (§5.3) MUST be immediately preceded by an XML comment of shape `<!-- _event.data: { ... } -->` or `<!-- _event.data: — -->` describing the payload. Internal-event transitions (`kernel.boot.done`, `sched.run`) are exempt.

**Rationale:** The chart's external-event surface IS its ABI. Reviewers reading the chart MUST be able to identify the payload shape without cross-referencing REFERENCE.md.

**Example violation:**
```xml
<transition event="task.delay">
  <script>...</script>
</transition>
```

**Example fix:**
```xml
<!-- _event.data: { ticks }   ticks<=0 acts as yield -->
<transition event="task.delay">
  <script>...</script>
</transition>
```

(The chart at HEAD complies with this rule for `task.create`, `task.delay`, `task.suspend`, `task.resume`, `sem.create`, `sem.take`, `sem.give`, `queue.create`, `queue.send`, `queue.receive`, `queue.send_from_isr`. The rule promotes "looks good today" to "enforced going forward".)

#### SCXML-LINT-011 — Transitions without `cond` are documented or trivially terminal (severity: `warning` — see §10)

**Normative:** Every `<transition event="X"/>` lacking a `cond` attribute SHOULD be either (a) trivially terminal (the target is a sibling state and the body has no datamodel mutation) OR (b) accompanied by a comment explaining why no guard is needed.

**Rationale:** Unguarded transitions are the load-bearing site for silent semantic drift. The chart at HEAD has ~16 unguarded transitions, all because the corresponding syscall always processes (the guard is in the script body: `if (!s.valid) { rc = RC_INVAL; }` rather than in the transition's `cond`). Documenting this convention prevents a future edit from adding a `cond` thinking it's missing.

**Example violation:**
```xml
<transition event="sem.create">
  <script>
    /* allocates without checking d.id bounds */
  </script>
</transition>
```

**Example fix:** keep the transition unguarded, but add a header comment: `<!-- always processes; bounds-check inside script -->`.

#### SCXML-LINT-012 — Every guard expression references only datamodel state (severity: `error`)

**Normative:** A transition's `cond` attribute MUST evaluate using only top-level datamodel identifiers AND the `_event` identifier. It MUST NOT call helper functions, MUST NOT mutate datamodel state, MUST NOT have side effects.

**Rationale:** Per W3C SCXML 1.0 §3.13, `cond` is evaluated as part of transition selection; side effects in `cond` are unspecified-order. The chart at HEAD complies (the two guards at `rtos_kernel.scxml:210` and `:214` read `sched_lock` only).

**Example violation:** `<transition event="sched.run" cond="pick_next() != -1">`.

**Example fix:** move the call into the transition body; if the guard is genuinely a query, expose a side-effect-free datamodel field.

#### SCXML-LINT-013 — Every external `event="..."` names a value from `ExternalEventName` (severity: `error`)

**Normative:** Every `<transition event="..."/>` whose event name contains a `.` separator (the convention for external events) MUST name a value listed in §5.3 `ExternalEventName`. Internal events (`kernel.boot.done`, `sched.run`) are exempt per §5.6.

**Rationale:** This is the contract-freezing rule. Adding `task.set_priority` to the chart without first amending §5.3 is the failure mode this rule catches.

**Example violation:**
```xml
<transition event="task.set_priority"><!-- not in §5.3 -->
  <script>...</script>
</transition>
```

**Example fix:** either remove the transition OR file a §15 amendment to add `task.set_priority` to §5.3 (which triggers the coordinated update obligations listed in §5.3).

#### SCXML-LINT-014 — Every `target="..."` names a value from `StateId` (severity: `error`)

**Normative:** Every `<transition target="..."/>` MUST name a value listed in §5.4 `StateId`. Targets that resolve to ancestor / descendant by SCXML's name-lookup rules are still subject to this check; the target string itself must be in the enum.

**Rationale:** Same contract-freezing rule for state ids.

**Example violation:** `<transition event="kernel.boot.done" target="runnning"/>` (typo).

**Example fix:** correct to `target="running"`.

### 6.6 Comment-density rules

#### SCXML-LINT-015 — Every `<state id="..."/>` carries an intent comment (severity: `warning`)

**Normative:** Every `<state>` element with a non-trivial body (more than the implicit single-transition case) SHOULD be preceded by an XML comment describing the state's purpose and any invariants it maintains.

**Rationale:** The chart at HEAD complies: each of `boot`, `running`, `scheduler`, `tick_service`, `syscalls`, `protection` has a leading comment block. The rule promotes the current practice to enforcement.

**Example violation:**
```xml
<state id="syscalls" initial="sys_idle">
  <state id="sys_idle">
    ...
  </state>
</state>
```

**Example fix:** prepend `<!-- SYSCALLS — external syscall dispatch on event name -->`.

#### SCXML-LINT-016 — Helper-block functions are documented (severity: `warning`)

**Normative:** Inside the top-level `<script>` block (the helpers at `rtos_kernel.scxml:77-165`), every named function SHOULD be preceded by a single-line `// ...` comment describing its purpose. Functions whose names are self-documenting (`ready_push`, `ready_remove`) MAY use a one-phrase comment; functions with subtle invariants (`waiters_insert`, `block_current`) MUST.

**Rationale:** The chart at HEAD complies for every helper. Codifies the practice.

**Example violation:** a helper added without a leading comment.

**Example fix:** prepend the comment.

### 6.7 Cross-document rules

#### SCXML-LINT-017 — REFERENCE.md syscall table covers `ExternalEventName` exactly (severity: `warning`) (PCDN-SOS-01-005)

**Normative:** The syscall ABI tables in `docs/REFERENCE.md` SHOULD list every event in `ExternalEventName` (§5.3) and SHOULD NOT list any event not in `ExternalEventName`. Coverage is checked by the lint runner via simple table-row extraction (the runner's responsibility, not the linter's).

**Rationale:** REFERENCE.md is informative ([SOS-00 §0]) but its discoverability makes it the de-facto port-author reference. Drift between REFERENCE.md and the chart erodes the chart's authority. PCDN-SOS-01-005 resolves whether to enforce this rule (default: yes).

**Example violation:** `docs/REFERENCE.md` lists `task.set_priority` (chart doesn't admit it) OR omits `crit.exit` (chart admits it).

**Example fix:** edit REFERENCE.md to match `ExternalEventName`.

#### SCXML-LINT-018 — REFERENCE.md task-state table mirrors `TaskState` enum (severity: `warning`)

**Normative:** The "Task states" table in `docs/REFERENCE.md` SHOULD list every value in `TaskState` ([SOS-00 §5.1]) with matching numeric codes.

**Rationale:** Same drift-prevention rationale as `SCXML-LINT-017`.

**Example violation:** REFERENCE.md lists `ST_BLK_MTX` (not in [SOS-00 §5.1] — it's reserved).

**Example fix:** remove the speculative row; reintroduce only after a §15 amendment to [SOS-00 §5.1] lifts the reservation.

### 6.8 Summary table

| Rule | Severity at draft | Category |
|---|---|---|
| SCXML-LINT-001 — Schema validation | `error` | Schema |
| SCXML-LINT-002 — Root `<scxml>` element attributes | `error` | Structural |
| SCXML-LINT-003 — Single `<datamodel>` block | `error` | Structural |
| SCXML-LINT-004 — No nested `<parallel>` | `error` | Structural |
| SCXML-LINT-005 — Script block ≤ 40 lines | `warning` (waived for helper block) | Size |
| SCXML-LINT-006 — `<onentry>`/`<onexit>` ≤ 5 lines | `error` (with §10 grace for `boot/onentry`) | Size |
| SCXML-LINT-007 — No non-deterministic primitives | `error` | Determinism |
| SCXML-LINT-008 — No async / Promise / generators | `error` | Determinism |
| SCXML-LINT-009 — ECMAScript feature subset (§5.1) | `error` | Determinism |
| SCXML-LINT-010 — Event-data comment per external transition | `error` | Transitions |
| SCXML-LINT-011 — Unguarded transitions documented | `warning` | Transitions |
| SCXML-LINT-012 — Side-effect-free `cond` | `error` | Transitions |
| SCXML-LINT-013 — `event` names from `ExternalEventName` | `error` | Transitions |
| SCXML-LINT-014 — `target` names from `StateId` | `error` | Transitions |
| SCXML-LINT-015 — `<state>` intent comments | `warning` | Comments |
| SCXML-LINT-016 — Helper-function comments | `warning` | Comments |
| SCXML-LINT-017 — REFERENCE.md syscall table coverage | `warning` | Cross-doc |
| SCXML-LINT-018 — REFERENCE.md task-state mirror | `warning` | Cross-doc |

Severity counts at draft: **error: 11**, **warning: 7**, **info: 0**.

## 7. CI integration shape

SOS-01 specifies the CI gate's shape. The actual workflow file is **not** created by this phase; the post-ratification implementation commit creates it at `.github/workflows/scxml-lint.yml` and lands it in the same commit as the lint runner.

### 7.1 Workflow file location

`.github/workflows/scxml-lint.yml` in the SOS subrepo root.

### 7.2 Triggers

```yaml
on:
  push:
    branches: [main]
    paths:
      - 'rtos_kernel.scxml'
      - 'docs/REFERENCE.md'
      - 'docs/specs/scxml.xsd'   # vendor target per PCDN-SOS-01-001
      - 'tools/scxml-lint/**'    # the lint-runner implementation (PCDN-SOS-01-004)
      - '.github/workflows/scxml-lint.yml'
  pull_request:
    branches: [main]
    paths: (same as above)
```

The path filter is informative — landing it as a wider trigger is acceptable; the narrow form is the recommended default.

### 7.3 Steps (informative shape)

```yaml
jobs:
  scxml-lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install xmllint
        run: sudo apt-get update && sudo apt-get install -y libxml2-utils
      - name: Schema validation (SCXML-LINT-001)
        run: xmllint --schema docs/specs/scxml.xsd rtos_kernel.scxml --noout
      - name: Lint runner (SCXML-LINT-002 through SCXML-LINT-018)
        run: python tools/scxml-lint/main.py rtos_kernel.scxml
```

The lint runner's invocation pattern is `python tools/scxml-lint/main.py <scxml-file>`, exiting non-zero on any `error`-severity violation and printing warnings / info to stdout regardless. PCDN-SOS-01-004 resolves the implementation language (default: Python + lxml).

### 7.4 Failure modes

| Failure | CI behaviour | Reviewer action |
|---|---|---|
| `xmllint` exit non-zero | Job fails. | Read xmllint's stderr; fix the structural error in the .scxml; re-push. |
| Lint runner reports any `error`-severity rule | Job fails. | Read the runner's stdout (which lists rule id, line numbers, and the suggested fix from §6); fix; re-push. |
| Lint runner reports only `warning` / `info` rules | Job passes. | Optional: address warnings in the same PR or file a follow-up. |
| Network failure fetching W3C (only if PCDN-SOS-01-001 lands as fetch) | Job fails. | If PCDN-SOS-01-001 is "fetch", flake-rerun. The "vendor" resolution avoids this entirely; SOS-01 default is vendor. |

### 7.5 PR comment rendering

Warnings and info messages SHOULD render as GitHub Annotations (`::warning file=<path>,line=<n>::<msg>` from the runner's stdout — GitHub Actions parses this format). This makes them visible inline in the PR diff view without spamming the comments thread. Errors fail the job; the failure surfaces in the PR's checks panel.

## 8. Build-time and runtime artifact map

SOS-01 has no runtime artifacts (it is a lint phase). Build-time artifacts:

| Artifact | Path | Owner | Built? | Run-when? |
|---|---|---|---|---|
| `rtos_kernel.scxml` (input) | repo root | SOS-00 | input | input to xmllint + lint runner |
| W3C SCXML 1.0 XSD (vendored copy per PCDN-SOS-01-001) | `docs/specs/scxml.xsd` | SOS-01 (vendor SHA recorded in §15) | input | input to xmllint |
| Lint runner | `tools/scxml-lint/main.py` (PCDN-SOS-01-004 default: Python + lxml) | SOS-01 (post-ratification implementation commit) | script | CI step |
| Lint runner rule modules | `tools/scxml-lint/rules/*.py` (one module per rule or per category) | SOS-01 | script | imported by `main.py` |
| Lint runner tests | `tools/scxml-lint/tests/*.py` | SOS-01 | host pytest | CI smoke before lint runs against `rtos_kernel.scxml` |
| CI workflow | `.github/workflows/scxml-lint.yml` | SOS-01 (post-ratification) | YAML | GitHub Actions on push/PR |
| `docs/REFERENCE.md` (cross-doc check target) | repo root `docs/` | SOS-00 | input | input to `SCXML-LINT-017` / `SCXML-LINT-018` |

The `tools/scxml-lint/` tree is **PCDN-SOS-01-004**-deferred: a single Python+lxml implementation is the default recommendation, but the precise file layout (single file vs per-rule modules) is the implementation commit's choice. SOS-01 specifies the API surface (`python main.py <scxml-file>`, exit-code semantics, GitHub-Annotations stdout format) and leaves the internals open.

## 9. Invariants

Each invariant has a stable id in the `INV-S-LINT-N` series. Amendments require a §15 entry on this doc AND, where the invariant constrains [SOS-00], a coordinated §15 entry on [SOS-00].

- **INV-S-LINT-1 — Schema gate.** `rtos_kernel.scxml` MUST validate against the W3C SCXML 1.0 XSD at every commit on the SOS repo's default branch. The CI workflow (§7) realises this; a failed validation is a blocking PR check.
- **INV-S-LINT-2 — Helper extraction.** Every `<script>` block longer than the `SCXML-LINT-005` cap (40 LOC at PCDN-SOS-01-003 default) MUST be extracted to a named helper in the top-level helper script block, unless the block IS the top-level helper block itself (the recursive exception). The top-level helper block has its own grace-period exemption recorded in §10.
- **INV-S-LINT-3 — Event / state vocabulary is append-only-with-deprecation.** Adding a value to `ExternalEventName` (§5.3) or `StateId` (§5.4) requires a §15 amendment to this doc AND a coordinated edit to `rtos_kernel.scxml` AND a coordinated edit to `docs/REFERENCE.md` AND a regen of SOS-03 vectors. Removing a value requires the same gate plus an explicit deprecation notice naming every downstream consumer reviewed.
- **INV-S-LINT-4 — ECMAScript subset is append-only.** Adding a `Permitted` row to `ECMAScriptFeature` (§5.1) requires a §15 amendment AND a demonstration that the SOS-02 hand-compilation port compiles the new construct cleanly. Demoting a `Permitted` row to `Forbidden` requires a §15 amendment plus a coordinated chart edit removing every site that uses the construct.
- **INV-S-LINT-5 — Rule ids are stable.** `SCXML-LINT-NNN` ids assigned in this doc are stable for the lifetime of the SOS-01 lineage. Removing a rule marks the id "retired" in the §15 change log; the id is not reused.
- **INV-S-LINT-6 — Lint is structural, not behavioural.** Lint rules in §6 govern the .scxml's text — structure, vocabulary, comment density. They do NOT verify the kernel's behaviour. Behavioural verification is SOS-03's responsibility (conformance vectors). A lint-conforming chart MAY still be semantically broken; only the vectors catch that.
- **INV-S-LINT-7 — Determinism preserved by the subset.** The §5.1 forbidden list (no `Math.random`, no `Date.now`, no `async`, no `eval`) is the load-bearing surface that makes [SOS-00 §9] INV-S2 (macrostep atomicity) realisable in the hand-compilation port. Any §15 amendment that touches §5.1 MUST cite INV-S-LINT-7 and explain how determinism is preserved.
- **INV-S-LINT-8 — CI gate cannot be silently disabled.** The `.github/workflows/scxml-lint.yml` workflow MUST run on every PR touching `rtos_kernel.scxml`, `docs/REFERENCE.md`, or the lint-runner tree. Disabling the workflow or removing required-checks status on the default branch requires a §15 amendment to this doc.

## 10. Reconciliation with `rtos_kernel.scxml` at HEAD

Per parent CLAUDE.md "Stealth-revert prohibition", the lint rules MUST be writable against the chart AS IT EXISTS today, without requiring a same-PR chart edit. This section walks each rule and classifies its status.

### 10.1 Rules the chart passes clean at HEAD

| Rule | Why it passes |
|---|---|
| SCXML-LINT-001 | Chart visibly conforms to SCXML 1.0 structure; needs xmllint verification at implementation time. |
| SCXML-LINT-002 | Root element at `rtos_kernel.scxml:21-24` has `xmlns`, `version="1.0"`, `datamodel="ecmascript"`, `initial="boot"`. |
| SCXML-LINT-003 | Exactly one `<datamodel>` at `rtos_kernel.scxml:29-72`. |
| SCXML-LINT-004 | Exactly one `<parallel>` (`running`) at `rtos_kernel.scxml:201`. No nesting. |
| SCXML-LINT-007 | No `Math.random`, no `Date.now`, no `console.log` anywhere in the .scxml. |
| SCXML-LINT-008 | No `async`, no `await`, no `Promise`, no `function*` anywhere. |
| SCXML-LINT-009 | The chart's `<script>` blocks use `var`, `for`, `if`/`else`, array `push`/`shift`/`splice`/`indexOf`/`.length`, object property access, function declarations. Every construct used is on the §5.1 `Permitted` list. |
| SCXML-LINT-010 | Every external-event transition has a preceding `<!-- _event.data: ... -->` comment, e.g. `rtos_kernel.scxml:269`, `:288`, `:307`, `:328`, etc. |
| SCXML-LINT-012 | The two `cond` expressions at `rtos_kernel.scxml:210` (`sched_lock == 0`) and `:214` (`sched_lock > 0`) are pure datamodel reads, no function calls, no side effects. |
| SCXML-LINT-013 | Every external `event="..."` value (18 of them) is in §5.3 by construction (§5.3 was derived from the chart). Internal events `kernel.boot.done` and `sched.run` are §5.6-exempt. |
| SCXML-LINT-014 | Every `target="..."` resolves to a state id in §5.4 (only the `boot → running` target appears in a `<transition>`; the `initial="..."` attributes resolve internally). |
| SCXML-LINT-015 | Each `<state>` has a leading comment block (see `rtos_kernel.scxml:198-200`, `:203-206`, `:218-222`, `:258-263`, `:523-528`). |
| SCXML-LINT-016 | Every helper function in the top-level block at `rtos_kernel.scxml:77-165` has a leading `// ...` comment. |
| SCXML-LINT-017 | `docs/REFERENCE.md` syscall tables list the same 18 events as `ExternalEventName`. (Cross-check: REFERENCE.md tables at `docs/REFERENCE.md:63-105` cover Tasks, Semaphores, Message queues, Time and protection — 18 rows total. Matches.) |
| SCXML-LINT-018 | `docs/REFERENCE.md:24-35` "Task states" table lists `ST_DORMANT` (0) through `ST_SUSPEND` (7), matching [SOS-00 §5.1] `TaskState` exactly. |

### 10.2 Rules requiring a chart edit — grace-period waivers

| Rule | At-HEAD status | Grace-period plan |
|---|---|---|
| SCXML-LINT-005 (`<script>` ≤ 40 lines) | The top-level helper block at `rtos_kernel.scxml:77-165` is ~88 lines (≈50 non-blank non-comment). Other blocks are within cap. | **Waived for the top-level helper block** (which IS the helper-extraction target — see INV-S-LINT-2 recursive exception). All other blocks pass at HEAD. Severity is `warning` at SOS-01 ratification; no upgrade planned because the helper block is the canonical extraction site. |
| SCXML-LINT-006 (`<onentry>` / `<onexit>` ≤ 5 lines) | The `boot/onentry` block at `rtos_kernel.scxml:171-194` contains ~17 non-blank non-comment lines (loop + post-loop calls). Violates the 5-line cap. | **Severity `warning` at SOS-01 ratification with grace-period to SOS-02 land.** Recommended fix in §6.3 example: extract a `boot_init()` helper into the top-level helper block, leaving `<onentry><script>boot_init();</script><raise event="kernel.boot.done"/></onentry>`. This fix is a 1-commit landed change; the §15 entry that lands it upgrades the rule to `error`. |
| SCXML-LINT-011 (unguarded transitions documented) | The chart has ~16 unguarded transitions in the `syscalls` and `protection` regions. Their guards live in the script bodies (`if (!s.valid) { rc = RC_INVAL; }` etc.) rather than in `cond` attributes. None of them have leading "always processes; bounds-check inside script" comments today. | **Severity `warning` at SOS-01 ratification with grace-period to SOS-03 land.** Recommended fix: add the convention comment to each unguarded external-event transition during the SOS-03 vector-authoring pass (when each transition is being read closely for vector design anyway). The §15 entry that lands the comment sweep upgrades the rule to `error`. |

### 10.3 Rules whose severity is intentionally `warning` long-term

| Rule | Why warning (not error) |
|---|---|
| SCXML-LINT-015 (state intent comments) | The chart at HEAD complies fully. Severity stays `warning` because the rule is about reviewability, not correctness; future edits MAY land state-id renames or restructures that temporarily lack comments and we don't want to fail CI on a known-temporary state. |
| SCXML-LINT-016 (helper function comments) | Same rationale. |
| SCXML-LINT-017, -018 (REFERENCE.md cross-doc) | Cross-doc rules are inherently best-effort; REFERENCE.md is informative and a brief drift between a coordinated chart edit and the REFERENCE.md follow-up is acceptable (the SOS-00 ratification of changes lives in `SOS-00-CONCEPTS.md`'s §15, not REFERENCE.md). |

### 10.4 What this section commits to

- The SOS-01 ratification commit lands a chart that passes every `error`-severity rule and every non-waived `warning`-severity rule.
- The two `warning` rules with grace-period waivers (`SCXML-LINT-006` for `boot/onentry`, `SCXML-LINT-011` for unguarded transitions) are upgraded to `error` in their named subsequent §15 entries.
- No `error` rule that requires a chart edit on the SOS-01 ratification commit itself is admitted; if §10.2 grows past two entries, the orchestrator MUST sequence: chart edits in their own commits, then SOS-01 ratification.

## 11. Non-goals

Frozen non-goals for SOS-01. Each MAY lift via a §15 amendment.

- **Semantic verification of the chart.** Whether the chart's behaviour is correct (does `sem.take` with timeout do the right thing?) is SOS-03's domain. SOS-01 lints text and vocabulary only.
- **Performance analysis.** Whether a `<script>` block is fast enough for a 1 kHz tick is not a SOS-01 concern. The hand-compilation port (SOS-02) and the M7 ports (SOS-04/05) measure this.
- **Code generation from the .scxml.** SOS-06 evaluates code generation. SOS-01 ensures the .scxml is well-formed enough to feed any future generator; SOS-01 does not generate anything itself.
- **Documentation generation.** Generating REFERENCE.md from the .scxml (e.g. extracting the syscall ABI table) is appealing but out of scope. SOS-01 lints for drift between the two but does not auto-fix.
- **Linting beyond `rtos_kernel.scxml`.** Future statecharts (if SOS ever ships more than one — currently INV-S14 forbids it) would be a separate SOS-01-style phase per chart. SOS-01 governs one specific file.
- **Linting REFERENCE.md prose.** SCXML-LINT-017 / -018 are structural (table-row coverage), not prose-quality. SOS-01 does not check spelling, grammar, or style of human-readable docs.
- **Linting the conformance vector files.** SOS-03 owns its own lint conventions; SOS-01 does not extend over conformance fixtures.
- **Replacing W3C SCXML 1.0 with a SOS-specific superset.** Per [SOS-00 §0], SCXML 1.0 is `derive`d, not `extend`ed. Inventing `<sos:invariant ...>` extension elements is explicitly forbidden.
- **AST-walk simulator design.** PCDN-SOS-01-002 resolves the question of whether SOS-02 grows an AST-walk path; the design of that path (if pursued) belongs to a future `SOS-02-B` amendment, not SOS-01.

## 12. Acceptance checklist (normative)

A conforming SOS-01 ratification (the moment §15 gets its dated entry) requires:

(a) The PCDN list in §15 is fully resolved. Every `PCDN-SOS-01-NNN` open question has a chosen value, dated, and the corresponding section (§4.1 for vendor-vs-fetch, §5.1 for the ECMAScript subset, §6.3 for the script-block cap value, §7/§8 for the lint runner shape, §6.7 for the REFERENCE.md cross-doc rules) updated to reflect the choice (or explicitly note "PCDN unresolved; section blocks").

(b) The .scxml at `rtos_kernel.scxml` validates against the vendored W3C SCXML 1.0 XSD via `xmllint --schema docs/specs/scxml.xsd rtos_kernel.scxml --noout`. Validation run pre-ratification; record the output (exit code 0, empty stderr) in the §15 entry.

(c) Every `error`-severity rule in §6 passes against the .scxml at the ratification commit's SHA. Every non-waived `warning`-severity rule passes. Waived rules (§10.2) are explicitly named in the §15 entry with their grace-period deadlines.

(d) The frozen enums §5.1 (`ECMAScriptFeature`), §5.3 (`ExternalEventName`), §5.4 (`StateId`), §5.5 (`LintRuleId`) are internally consistent with the .scxml at the ratification commit's SHA. A reviewer running a manual "does the chart use any forbidden feature / mention any undeclared event / declare any undeclared state-id" sweep finds no discrepancies.

(e) The CI integration shape §7 has been reviewed by someone familiar with GitHub Actions; the recommended workflow file shape is implementable as specified.

(f) PCDN-SOS-01-002 (the inherited PCDN-SOS-00-005 AST-vs-trace question) is resolved with a default-recommended path AND a named deferral mechanism for the not-chosen options (a future `SOS-02-B` amendment, not "TBD forever").

(g) §10's reconciliation list is exhaustive — every rule in §6 is classified as pass-clean, grace-period-waived, or intentional-long-term-warning. No rule is unclassified.

(h) The non-goal list §11 is exhaustive for the SOS-01 horizon. Items beyond that horizon are not constrained here.

A conforming SOS-01 implementation commit (the post-ratification commit that lands `docs/specs/scxml.xsd`, the `tools/scxml-lint/` tree, and the `.github/workflows/scxml-lint.yml` workflow) additionally requires:

(i) The vendored XSD at `docs/specs/scxml.xsd` matches the W3C-published bytes byte-for-byte at a SHA recorded in the implementation commit's §15 entry on this doc.

(j) The lint runner at `tools/scxml-lint/main.py` exits non-zero when any `error`-severity rule fires; exits zero when only `warning` / `info` fire; prints rule ids and line numbers in the GitHub-Annotations format for surfaced violations.

(k) The CI workflow at `.github/workflows/scxml-lint.yml` runs on push and PR per §7.2's path filter; required-checks status is enabled for the default branch.

## 13. Files cited

| Path | Role | Status |
|---|---|---|
| `streamz/submodules/SOS/rtos_kernel.scxml` | Canonical kernel spec | exists; lint target |
| `streamz/submodules/SOS/docs/REFERENCE.md` | Human reference | exists; cross-doc lint target (`SCXML-LINT-017`, `-018`) |
| `streamz/submodules/SOS/docs/concepts/SOS-00-CONCEPTS.md` | Parent doc | ratified 2026-05-19 |
| `streamz/submodules/SOS/docs/concepts/README.md` | Phase roadmap | exists; SOS-01 marked unblocked |
| `streamz/submodules/SOS/docs/concepts/ERRATA.md` | Errata log | exists (no entries yet) |
| `streamz/submodules/SOS/docs/specs/scxml.xsd` | Vendored W3C SCXML 1.0 XSD | exists; PCDN-SOS-01-001 (b) landed at implementation time |
| `streamz/submodules/SOS/tools/scxml-lint/main.py` | Lint runner entry point | exists; PCDN-SOS-01-004 default Python + lxml; landed at implementation time |
| `streamz/submodules/SOS/.github/workflows/scxml-lint.yml` | CI workflow | exists; landed at implementation time per §7 |
| `https://www.w3.org/2011/04/SCXML/scxml.xsd` | Upstream XSD URL | external; vendored per PCDN-SOS-01-001 default (b) |
| `https://www.w3.org/TR/2015/REC-scxml-20150901/` | W3C SCXML 1.0 Recommendation | external; cited by section number, not crawled (INV-S-LINT-0) |
| Parent `CLAUDE.md`, "Spec-Before-Code Planning Discipline" | Governing discipline | exists at parent repo root |
| Parent `CLAUDE.md`, "Frozen enumerations — registration policy" | Standards-Action / Specification-Required / Expert-Review enum | exists at parent repo root |

## 14. Unblocks

This phase unblocks:

- **SOS-02** (host simulator). Needs §5.1 `ECMAScriptFeature` to fix the hand-compilation translation target. PCDN-SOS-01-002 closes the AST-vs-trace question so SOS-02's crate layout has no remaining design surface to litigate.
- **SOS-03** (conformance vectors). Needs §5.3 `ExternalEventName` and §5.4 `StateId` frozen so vector authors have a stable event / state-id contract surface. Also needs SCXML-LINT-001 (schema validation) passing so vectors execute against a well-formed chart.

SOS-04 and SOS-05 (M7 reference ports) are not directly unblocked by SOS-01 — they consume [SOS-00 §6] (M7 primitive bindings) and SOS-03's conformance vectors. Indirect dependency: a lint-rejected .scxml on the default branch would break SOS-04/05 builds at the conformance-validation stage; INV-S-LINT-1 (schema gate) prevents this class of failure.

SOS-06 (codegen evaluation) is not unblocked by SOS-01 directly; it depends on the M7 ports and on the conformance vectors. Indirect: SOS-06 reads the .scxml as input to a hypothetical compiler; a lint-conforming chart is easier to mechanically translate than a non-conforming one, but SOS-06 has its own ratification cycle.

## 15. Change log

### 2026-05-19 — Initial draft (Ira)

- Document drafted at `docs/concepts/SOS-01-CONCEPTS.md`.
- Sections §0–§14 populated.
- §5.1 (`ECMAScriptFeature`) freezes the permitted-construct surface for `<script>` blocks; closes the placeholder in [SOS-00 §4] row "ECMA-262".
- §5.2 (`LintRuleSeverity`) defines `error` / `warning` / `info`.
- §5.3 (`ExternalEventName`) freezes the 18-event external-syscall contract surface, derived from inspection of `rtos_kernel.scxml` syscall / tick-service / protection regions.
- §5.4 (`StateId`) freezes the 10-state-id surface, derived from inspection of the chart's `<state>` / `<parallel>` declarations.
- §5.5 (`LintRuleId`) introduces the `SCXML-LINT-NNN` namespace, append-only-with-retirement.
- §6 introduces 18 lint rules: 11 `error`, 7 `warning`, 0 `info`. Each rule cites the chart's at-HEAD compliance status in §10.
- §7 specifies the CI workflow shape (`.github/workflows/scxml-lint.yml`, path-filtered triggers, xmllint + lint-runner steps, GitHub-Annotations stdout format).
- §10 reconciles every rule against the .scxml at HEAD: 15 rules pass-clean; 2 (`SCXML-LINT-006`, `SCXML-LINT-011`) carry grace-period waivers with named upgrade deadlines; 1 (`SCXML-LINT-005`) has a permanent recursive-exception waiver for the top-level helper block; 4 stay at long-term `warning` by design.
- §12 acceptance checklist enumerates ratification and implementation-commit gates.

PCDN list awaiting resolution:

- **PCDN-SOS-01-001 — Vendor XSD vs fetch from W3C.** **Resolved (b) 2026-05-19:** vendor `docs/specs/scxml.xsd` at a pinned SHA; re-vendor only if the W3C schema itself changes. Hermetic CI; SCXML 1.0 Recommendation is stable since 2015-09-01; W3C downtime never blocks a SOS PR.

- **PCDN-SOS-01-002 — Resolution of inherited PCDN-SOS-00-005 (AST-walk for SOS-02).** **Resolved (a) 2026-05-19:** hand-compiled only for SOS-02 v1. The AST/trace question is deferred to a future `SOS-02-B` amendment if SOS-02 v1 demonstrates a need. Scope minimisation; SOS-02 v1 has enough surface to ratify without speculative simulator-path multiplication.

- **PCDN-SOS-01-003 — Script-block length cap value for `SCXML-LINT-005`.** **Resolved 40 LOC 2026-05-19** (raised from the originally-proposed 30 to give authoring leeway; the recursive-exception waiver for the top-level helper block stays — see §10). Non-blank non-comment lines inside `<![CDATA[...]]>`. The chart's at-HEAD non-helper blocks all sit comfortably under 40.

- **PCDN-SOS-01-004 — Lint runner implementation language.** **Resolved (a) Python + lxml 2026-05-19.** Most readable for the rule-authoring audience; lxml is a mature XML toolkit with good XPath / element-tree support; Python is already a parent-repo standard for codegen and codemod work. Rust binary deferred — adds build-from-source surface to CI for no readability gain.

- **PCDN-SOS-01-005 — Cross-doc lint for REFERENCE.md drift (`SCXML-LINT-017`, `SCXML-LINT-018`).** **Resolved (a) warning 2026-05-19.** REFERENCE.md is informative ([SOS-00 §0]); brief drift during a coordinated multi-file edit is acceptable; a hard `error` would force same-PR REFERENCE.md edits that may be best done as a follow-up. Promotion to `error` is a future §15 amendment if drift becomes a pattern.

Acceptance checklist (§12) compliance at draft:

- (a) ⏸ PCDNs pending user ratification.
- (b) ⏸ Awaits implementation commit (xmllint not run in this phase per the no-code constraint).
- (c) ⏸ Awaits implementation commit.
- (d) ✅ Frozen enums §5.1, §5.3, §5.4, §5.5 derived directly from the .scxml at HEAD.
- (e) ✅ §7 workflow shape is implementable as specified.
- (f) ⏸ PCDN-SOS-01-002 pending user ratification.
- (g) ✅ §10 classifies every rule.
- (h) ✅ §11 covers the SOS-01 horizon.
- (i) ⏸ Awaits implementation commit.
- (j) ⏸ Awaits implementation commit.
- (k) ⏸ Awaits implementation commit.

Unblocks: SOS-02 (post-ratification), SOS-03 (post-ratification). Implementation commit (xmllint + lint runner + CI workflow) lands as a separate post-ratification commit per the spec-before-code discipline.

### 2026-05-19 — Ratification (Ira)

User walked the PCDN list and ratified every open question. SOS-01 status moves from 🟡 drafted to **🟢 ratified**. SOS-02 / SOS-03 (and implementation commits that land the vendored XSD, lint runner, and CI workflow) are unblocked.

PCDN resolutions (full record):

- **PCDN-SOS-01-001:** **Resolved (b):** vendor `docs/specs/scxml.xsd` at a pinned SHA; re-vendor only on upstream W3C schema change.
- **PCDN-SOS-01-002:** **Resolved (a):** hand-compiled only for SOS-02 v1; AST/trace deferred to future `SOS-02-B`.
- **PCDN-SOS-01-003:** **Resolved 40 LOC** (user-accepted with alteration: raised from the originally-proposed 30 to 40 to give authoring leeway). Recursive-exception waiver for the top-level helper block (per §10) retained as-is. SCXML-LINT-005 normative body, INV-S-LINT-2, §6 rationale, §10 reconciliation row, and §15 PCDN entry all updated to cite 40 LOC.
- **PCDN-SOS-01-004:** **Resolved (a):** Python + lxml.
- **PCDN-SOS-01-005:** **Resolved (a):** warning severity for SCXML-LINT-017 / -018.

Acceptance checklist (§12) compliance at ratification:

- (a) ✅ All five PCDNs resolved.
- (b) ⏸ Deferred to the post-ratification implementation commit that lands `docs/specs/scxml.xsd` and runs `xmllint` in CI for the first time.
- (c) ⏸ Same.
- (d) ✅ Frozen enums consistent with the .scxml at HEAD.
- (e) ✅ Workflow shape implementable.
- (f) ✅ PCDN-SOS-01-002 resolved with a named deferral mechanism (`SOS-02-B` amendment) for the not-chosen options.
- (g) ✅ §10 classifies every rule.
- (h) ✅ §11 covers the horizon.
- (i) ⏸ Awaits implementation commit.
- (j) ⏸ Awaits implementation commit.
- (k) ⏸ Awaits implementation commit.

Items (b), (c), (i), (j), (k) intentionally remain ⏸ at ratification time — they are *implementation-commit* gates by design (per §12's split between ratification gates and implementation-commit gates). Ratification itself completes when (a), (d)–(h) land. The implementation commit lands as a follow-up that vendors `docs/specs/scxml.xsd`, scaffolds `tools/scxml-lint/main.py`, and wires `.github/workflows/scxml-lint.yml`.

Unblocks: SOS-02, SOS-03.

### 2026-05-19 — Amendment 001: vendor pinned SHAs for SCXML XSD (Ira)

Implementation commit (2026-05-19) landed `docs/specs/scxml.xsd` + its transitive `<xsd:include>` closure. Pinned SHA-256s (per PCDN-SOS-01-001 vendor resolution; INV-S-LINT-1 schema-gate substrate):

| File | SHA-256 |
|---|---|
| `docs/specs/scxml.xsd` (driver) | `98e14d0e03d5f9bb49b03fe4a2c24d72c165789d68fe93eee24fc403e4b23b48` |
| `docs/specs/scxml-module-core.xsd` | `cbe0cde7a2cc165b84263e0dad45abd74296ed99a9196611e4b0c98b494222e4` |
| `docs/specs/scxml-module-data.xsd` | `c34438431aa5d9815a63a64415e3127b832abd451ca509ff79a89d529dddba47` |
| `docs/specs/scxml-module-external.xsd` | `899b13488332a6b37700ea53766e16d39b1b4f38fb829d0d3b12f0955a08057d` |
| `docs/specs/scxml-datatypes.xsd` | `51036cac697db9be6f92ad853215dc3166990ca292786fed1612d0666932163b` |
| `docs/specs/scxml-attribs.xsd` | `b74de05e9e8d86123a4e8cca6655761fae78009e8d63b95cc27ae38222a2de01` |
| `docs/specs/scxml-contentmodels.xsd` | `704baaf6e19c480fa76039390dc0a0e045f5544b5f68ec294c47fe51d40d0053` |

The transitive includes (`scxml-datatypes`, `scxml-attribs`, `scxml-contentmodels`) were not anticipated in the original §4.1 narrative — the driver names three module schemas in its `<xsd:include>` set, but those modules transitively include three more. All six W3C-hosted at `https://www.w3.org/2011/04/SCXML/<name>.xsd`. `lxml.etree.XMLSchema(etree.parse('docs/specs/scxml.xsd'))` succeeds end-to-end against the vendored graph (verified 2026-05-19).

The driver also has one `<xsd:import>` for `http://www.w3.org/2001/xml.xsd`; lxml resolves this from its bundled `xml.xsd` without remote fetch. No further vendoring required.

Re-vendoring policy: if W3C publishes corrections to any of these seven files, the amendment that adopts them updates the affected SHA(s) and lands the new bytes in the same commit. CI MUST verify the SHA-256 of each vendored XSD matches the table above before invoking the schema validator — a tampered vendor copy would silently bypass the schema gate.

### 2026-05-19 — Amendment 002: lint-runner scaffold landed (Ira)

`tools/scxml-lint/` populated with the Python+lxml runner (PCDN-SOS-01-004 resolution). 9 of 18 SCXML-LINT-NNN rules have working implementations: 001 (schema), 005 (script length, 40 LOC cap), 009 / 010 (event vocabulary), 013 (ECMAScript subset), 014 / 015 (comment density), 017 / 018 (REFERENCE.md drift). The other 9 rules (002, 003, 004, 006, 007, 008, 011, 012, 016) carry `# TODO: SCXML-LINT-NNN — implement` placeholders in `main.py`'s rule registry; they ride on follow-up commits and do NOT block ratification (per the §12 implementation-gate split).

`requirements.txt`: `lxml>=4.9`. Modules: `rules/_common.py` (115 LOC, shared helpers), `rules/schema.py` (71), `rules/script_length.py` (64), `rules/event_vocabulary.py` (103), `rules/ecmascript_subset.py` (97), `rules/comment_density.py` (80), `rules/reference_md_drift.py` (134 — over the 100-LOC informal target; covers two rules + bidirectional drift checks; refactor candidate noted for follow-up).

CI workflow at `.github/workflows/scxml-lint.yml`. Triggers per §7: push + PR on `rtos_kernel.scxml`, `docs/specs/*.xsd`, `tools/scxml-lint/**`, `docs/REFERENCE.md`. Python 3.11; `actions/checkout@v4` + `actions/setup-python@v5`.

### 2026-05-19 — Amendment 003: remaining 9 lint rules landed (Ira)

Follow-up to Amendment 002. The nine TODO placeholders in `tools/scxml-lint/main.py`'s rule registry — SCXML-LINT-002, -003, -004, -006, -007, -008, -011, -012, -016 — are now implemented as one module per rule under `tools/scxml-lint/rules/`. The runner now realises all 18 §6 rules end-to-end and no `# TODO: SCXML-LINT-NNN — implement` markers remain in the registry.

New modules (one per rule, line counts include docstring + imports):

| Module | Rule | LOC | Severity | At-HEAD behaviour |
|---|---|---:|---|---|
| `rules/rule_002_structure.py` | SCXML-LINT-002 | 75 | `error` | pass-clean (root has canonical `xmlns`/`version="1.0"`/`datamodel="ecmascript"`/`initial="boot"`) |
| `rules/rule_003_datamodel_count.py` | SCXML-LINT-003 | 49 | `error` | pass-clean (single top-level `<datamodel>`, no nesting) |
| `rules/rule_004_no_nested_parallel.py` | SCXML-LINT-004 | 40 | `error` | pass-clean (`<parallel id="running">` is the only one) |
| `rules/rule_006_onentry_size.py` | SCXML-LINT-006 | 50 | `warning` (§10.2 grace) | 1 finding at `boot/onentry` (~13 LOC); §10.2 grace-period waiver, slated for upgrade to `error` once `boot_init()` extracts |
| `rules/rule_007_determinism.py` | SCXML-LINT-007 | 60 | `error` | pass-clean (no `Math.random` / `Date` / `console` / `eval` / `Function`) |
| `rules/rule_008_async.py` | SCXML-LINT-008 | 58 | `error` | pass-clean (no `async`/`await`/`Promise`/`function*`/`yield`) |
| `rules/rule_011_unguarded_documented.py` | SCXML-LINT-011 | 90 | `warning` (§10.2 grace) | 18 findings on unguarded `syscalls` / `protection` transitions; §10.2 grace-period waiver, slated for upgrade to `error` after the SOS-03 vector-authoring comment sweep |
| `rules/rule_012_cond_pure.py` | SCXML-LINT-012 | 65 | `error` | pass-clean (the two `cond` expressions `sched_lock == 0` and `sched_lock > 0` are pure datamodel reads) |
| `rules/rule_016_helper_comments.py` | SCXML-LINT-016 | 62 | `warning` | pass-clean (every helper in the top-level `<script>` block carries a leading `// ...` comment) |

Total new code: 549 LOC across the nine modules, all under the 100-LOC informal target.

Companion changes:
- `tools/scxml-lint/rules/_common.py` `localname` and `iter_elements` now skip lxml `Comment`/`ProcessingInstruction` nodes (their `.tag` attribute is callable, not a string). Previously latent because the strict parser bailed before `iter()` was called on a populated tree (see next bullet).
- `tools/scxml-lint/main.py` now falls back to `etree.XMLParser(recover=True)` if the strict parse fails so the remaining §6 rules can run against the document. Schema validation (SCXML-LINT-001) is unaffected — `rules/schema.py` parses independently with the strict parser. The fallback is needed because lxml 6.0 strictly rejects the `<!-- ---------- -->` separator comments in the chart (XML 1.0 §2.5 forbids `--` inside a comment); making the lint runner robust against that pre-existing failure mode (not yet ERRATA-logged) is non-normative scaffolding.
- Tests added under `tools/scxml-lint/tests/test_rule_<NNN>.py` (one file per new rule, 21 `unittest`-style cases total). `pytest tools/scxml-lint/tests/` exits 0 against this commit. `tests/conftest.py` and `tests/_support.py` add the lint-runner root and tests directory to `sys.path` so the rule modules import cleanly without an explicit `pip install -e .` step.

Open question (informative; non-blocking on Amendment 003): SOS-01 §10.1 asserts that `SCXML-LINT-010` and `SCXML-LINT-015` pass-clean at HEAD, but running the scaffold runner against `rtos_kernel.scxml` surfaces 7 LINT-010 findings (no-payload transitions like `task.yield`, `sys.tick`, `crit.enter`, `crit.exit`, `sched.suspend`, `sched.resume`, `sem.give_from_isr` lack `_event.data: —` headers) and 3 LINT-015 findings (the inner idle states `sched_idle`, `sys_idle`, `prot_idle` lack leading intent comments). Either §10.1's claim is too strong (these need §10.2-style grace-period entries), the scaffold's detector is over-strict (need to relax to "outer state has a comment" / "no-payload events are exempt"), or the chart needs the missing comments. Triage owner is the Amendment 002 author; this commit does not adjudicate — it only surfaces the discrepancy now that the §6 rules execute end-to-end for the first time.

### 2026-05-19 — Amendment 004: downgrade §10.1 pass-clean promise for SCXML-LINT-010 + SCXML-LINT-015 (Ira)

Wave-5 implementation of the 9 remaining lint rules (Amendment 003) revealed that §10.1's blanket "every rule except SCXML-LINT-006 and SCXML-LINT-011 passes clean at HEAD" is incorrect for SCXML-LINT-010 and SCXML-LINT-015.

**Findings against `rtos_kernel.scxml` at the wave-5 SHA:**

- **SCXML-LINT-010 — 7 violations.** Transitions for events `task.yield`, `sys.tick`, `crit.enter`, `crit.exit`, `sched.suspend`, `sched.resume`, and `sem.give_from_isr` lack the leading `_event.data: —` header comment the detector expects on every transition. (These are events whose `_event.data` is `null` per the .scxml's contract; the detector requires the comment as a structural marker regardless of payload presence.)

- **SCXML-LINT-015 — 3 violations.** Inner idle states `sched_idle`, `sys_idle`, and `prot_idle` lack the leading intent comment the rule requires on every `<state>`.

§10 amended: §10.2 (grace-period waiver table) gains two new rows for SCXML-LINT-010 and SCXML-LINT-015. Severity stays at the §6-ratified level (LINT-010 = error; LINT-015 = warning) but the at-HEAD reconciliation now correctly classifies these as "fails with grace-period waiver" instead of "passes clean".

**Forward plan** (informative; not load-bearing on this amendment):

- LINT-015 grace-period waiver: add the 3 missing intent comments to the chart in a separate (chart-edit) §15 amendment. Trivial; the chart authoring style already includes them on outer states. (Chart edits to `rtos_kernel.scxml` ratify via SOS-00 §15 + INV-S11 — the amendment that lands the comments belongs in SOS-00 or this doc with explicit SOS-00 cross-reference.)
- LINT-010 grace-period waiver: add the 7 missing `_event.data: —` headers OR relax the detector to treat payload-less events as exempt. Pick at first follow-up; the detector relaxation is the lower-friction option.

This amendment does NOT itself edit the chart. The chart and the detector both stand; only §10.1's promise updates to match observed reality.

### 2026-05-23 — SOS-07 rename ratification (Ira)

The initiative rename from *Statechart-Orchestrated Scheduler* to **Statechart Orchestration System** is ratified through [`SOS-07-CONCEPTS.md`](./SOS-07-CONCEPTS.md). The acronym `SOS` is unchanged across this phase doc family; all in-text references continue to read as `SOS` for cross-doc citation stability.

Cross-phase invariants INV-SOS-A through H + the AuthorityRelationship matrix promote from informative roadmap text (`SOS-ROADMAP-07-PLUS.md`) to normative phase content in SOS-07. They cite by ID into SOS-01's normative sections without modifying any of SOS-01's frozen content.

Bootstrap-vs-general framing (SOS-07 §8): the kernel chart `rtos_kernel.scxml` is reframed as the v1 demonstration the methodology generalises from, not "the chart". The bench-validated state recorded across SOS-01's prior amendments carries forward unchanged.

No frozen-enum value modified. No PCDN re-ratified. No port-spec impact.

### 2026-05-23 — `<sos:discharged>` extension element recognized (Ira)

Co-landing amendment to [SOS-13 §7.5](./SOS-13-CONCEPTS.md). SOS-01 ratifies the recognition of the `<sos:discharged check="..."/>` element as a permitted SCXML extension element. This is an **additive** §15 amendment; SOS-01 stays 🟢 ratified.

**Recognition.** The element `<sos:discharged check="..."/>` is a **permitted SCXML extension element** within the `<state>`, `<transition>`, `<onentry>`, and `<onexit>` parent scopes. The element is authored and owned by SOS-13 (cite [SOS-13 §7.5](./SOS-13-CONCEPTS.md)); SOS-01's role is purely to declare that the lint rules in §6 do NOT reject its presence.

**XML namespace binding.** The `sos:` XML namespace prefix that the chart's `<scxml>` root MUST bind is:

```
xmlns:sos="http://softoboros.com/scxml-extensions/v1"
```

The namespace URI is the SOS-13-owned extension-namespace URI. The prefix `sos:` is the canonical short form used in SOS-13's grammar examples; the URI is the load-bearing identifier (XML Namespace 1.0 §3 lets the prefix be rebound, but the URI uniquely identifies the extension owner). The W3C SCXML 1.0 XSD's `<xsd:any namespace="##other" processContents="lax"/>` wildcard in the executable-content content model is what permits these elements to pass schema validation; `SCXML-LINT-001` (schema validation) is therefore unaffected.

**Lint-rule treatment at SOS-01 v1.**

- `SCXML-LINT-001` (schema validation): unaffected. The W3C XSD's `##other` wildcard accepts the element by construction.
- `SCXML-LINT-002` (root element attributes): the rule's "no other attributes on the root element" clause is interpreted as "no other SCXML-namespace attributes". Namespace declarations (`xmlns:sos="..."`) are XML-level mechanism, not SCXML-attribute surface, and remain permitted. No rule edit required.
- `SCXML-LINT-013` (event-name vocabulary), `SCXML-LINT-014` (state-id vocabulary), `SCXML-LINT-015` / `-016` (comment density), and the structural rules (`-003`, `-004`, `-006`) all operate on SCXML-namespace elements; they ignore extension-namespace children by construction.
- The lint rules MAY validate that `check` is one of the four frozen values (`bounds`, `div-by-zero`, `null`, `overflow`) per [SOS-13 §7.5](./SOS-13-CONCEPTS.md). This validation is reserved as a **future SOS-13 lint addition** (a new `SCXML-LINT-NNN` rule owned by SOS-13, lint-registered in SOS-01's `LintRuleId` namespace per §5.5). It is explicitly **not** a SOS-01 v1 rule.

**Non-goal §11 reconciliation.** SOS-01 §11 forbids "Replacing W3C SCXML 1.0 with a SOS-specific superset" and cites `<sos:invariant ...>` as the canonical example of what is forbidden. The `<sos:discharged>` element does NOT violate this non-goal: it does not modify SCXML semantics (the chart's execution under SOS-02 / SOS-03 is unaffected), does not extend the language, and lives entirely in the codegen-tool consumption surface. The §11 prohibition targets extensions that change chart semantics; `<sos:discharged>` is a codegen-side annotation that the SCXML runtime ignores. The non-goal text is not amended; the boundary is "extension elements that change chart semantics are forbidden; extension elements consumed only by downstream tooling are permitted, subject to a §15 recognition amendment per consuming phase".

**Chart-file follow-up.** `rtos_kernel.scxml` at HEAD does NOT currently bind the `sos:` namespace prefix. When the first `<sos:discharged>` annotation lands in the chart (driven by SOS-13 codegen consumers), the chart's `<scxml>` root MUST add `xmlns:sos="http://softoboros.com/scxml-extensions/v1"` in the same commit. This is a future amendment to the chart file; this SOS-01 amendment does NOT itself edit `rtos_kernel.scxml`. INV-S11 (chart-edit gating) governs that future edit.

**Cross-reference.** See [SOS-13 §7.5](./SOS-13-CONCEPTS.md) for the chart-side grammar's full specification (annotation shape, frozen `check` enumeration, multiplicity, inheritance, codegen behaviour) and [SOS-13 §15 — PCDN-13-discharge-grammar ratified (2026-05-23)](./SOS-13-CONCEPTS.md) for the co-landing SOS-13-side ratification entry.

No frozen-enum value modified at SOS-01. No PCDN re-ratified. `ExternalEventName` (§5.3) and `StateId` (§5.4) are unaffected — `<sos:discharged>` is an extension-namespace element, not an event name or state id. SOS-01 stays 🟢 ratified.

### 2026-05-27 — SOS01-09 channel-annotation lint amendment (Ira)

Co-landing amendment to [SOS-09 §12 (i)](./SOS-09-CONCEPTS.md) per the 2026-05-27 SOS09W1 roll-up commit `43c45bf` (the umbrella's §15 bookkeeping entry naming the outstanding co-land obligation on SOS-01). This amendment closes that gate by adding three new lint rules to SOS-01's catalog that enforce the SOS-09 channel-annotation surface frozen in [SOS-09-A §5.2 / §5.4](./SOS-09-A-CONCEPTS.md). Additive §15 amendment; SOS-01 stays 🟢 ratified.

**Recognition.** The `sos:`-prefixed JSON keys inside iState's `other_attributes` extension surface (per the 2026-05-25 SOS-09 §15 PCDN-SOS-09-001 amendment routing channel annotations through `other_attributes` with a STRING key prefix) constitute a SOS-09-owned chart-author surface. SOS-01's role is to lint the surface at chart-load time so authoring errors (unknown `sos:`-prefixed keys, illegal enum values) fail loudly rather than silently producing broken downstream artifacts. The authoritative twelve-key set and the four-value `sos:kind` enum live in SOS-09-A; the three lint rules below enforce them without restating them.

**Lint rules introduced.** Three new rules under the new category prefix `SCXML-LINT-CH-N` (channel-annotation lint). This is the first non-numeric category-prefix series in the catalog; per `LintRuleId` (§5.5) Standards Action policy and INV-S-LINT-5 (rule ids stable), the `SCXML-LINT-CH-N` namespace is reserved for SOS-09 chart-annotation lint and is append-only. The original `SCXML-LINT-NNN` numeric series remains owned by core SOS-01 chart structure / vocabulary / determinism lint; the category-prefix form (`SCXML-LINT-CH-N`, future `SCXML-LINT-DISP-N` for SOS-12, etc.) is the convention for downstream-phase-owned lint families that ride on SOS-01's runner without consuming the numeric id space.

- **SCXML-LINT-CH-1 — Unknown `sos:`-prefixed key (severity: `error`).**

  **Normative:** An `other_attributes` JSON key beginning with the four-character STRING prefix `sos:` on any iState/SCXML element MUST name a member of the SOS-09-A §5.2 authoritative twelve-key set:

  ```
  sos:id, sos:name, sos:kind, sos:dir, sos:zone, sos:atomicity,
  sos:width, sos:bit_layout, sos:irq, sos:mutex,
  sos:channel_group, sos:privilege_region
  ```

  Any other `sos:`-prefixed key (typo, speculative extension, removed-but-not-cleaned-up key) is a hard lint error. The chart-author-friendly diagnostic MUST name the offending key, the parent element (by chart `id` or path), and the full twelve-key list.

  **Rationale:** A `sos:`-prefixed key that does not match the authoritative set is either (a) a typo (`sos:kindd`, `sos:dir_`), (b) a speculative extension that bypassed Standards Action ratification, or (c) a stale key from a removed feature. All three silently produce a chart that the downstream SOS-09 emitters either reject inconsistently or — worse — pass through without applying the intended semantic. Catching at lint time matches the §0 authority policy: SOS-01 owns the lint surface; SOS-09-A owns the key list.

  **Example violation:**
  ```json
  {"position_x": 100, "sos:kindd": "status", "sos:dir": "hw→sw"}
  ```

  **Example fix:** correct the typo (`sos:kind`); OR, if the new key is genuinely needed, file a §16 amendment to SOS-09-A §5.2 adding the thirteenth key before the chart edit lands (Standards Action; see registration-policy note below).

- **SCXML-LINT-CH-2 — Illegal `sos:kind` value (severity: `error`).**

  **Normative:** When `sos:kind` is present, its value MUST be one of the four members of the SOS-09 §5.1 frozen channel-category enum:

  ```
  kind ∈ { status, command, queue, shared }
  ```

  Any other value (typo, speculative fifth category) is a hard lint error. The diagnostic MUST name the offending value, the parent element, and the four-value enum.

  **Rationale:** Mirrors SOS-09-A §5.4 (3) at the SOS-01 lint layer. The SOS-09 §5.1 enum is the load-bearing vocabulary for the channel → membrane-primitive mapping (§5.2 of the umbrella); a typo (`statu`, `commad`) silently falls off the mapping table and produces a chart that emits zero artifacts for the channel rather than failing loudly. Per PCDN-SOS-09-A-004 (ratified 2026-05-25), the umbrella's chosen severity is hard error — "syntax error on any other compiler" — and SOS-01 mirrors that choice.

  **Example violation:** `{"sos:id": "<UUID>", "sos:name": "rx_path", "sos:kind": "statu", "sos:dir": "hw→sw"}`.

  **Example fix:** correct to one of the four enum values; OR, if a genuine fifth category is needed, file a §15 amendment to SOS-09 §5.1 (Standards Action, cross-phase consensus) before any chart edit lands.

- **SCXML-LINT-CH-3 — Illegal `sos:dir` value (severity: `error`).**

  **Normative:** When `sos:dir` is present, its value MUST be one of the values admitted by SOS-09 §5.2's channel → membrane-primitive mapping table:

  ```
  dir ∈ { hw→sw, sw→hw, hw↔sw }
  ```

  Any other value (typo, speculative direction) is a hard lint error. The diagnostic MUST name the offending value, the parent element, and the admitted set.

  **Rationale:** Mirrors SOS-09-A §5.4 (3) and SOS-09 §5.2 at the SOS-01 lint layer. The dir vocabulary is the second half of the (`kind`, `dir`) pair that selects a row in the SOS-09 §5.2 mapping table; a typo (`hw->sw` ASCII, `bidi`) silently misses the table and the channel emits zero artifacts. SOS-09-A §5.4 (4) (cross-attribute consistency between `kind` and `dir`) is NOT enforced by SCXML-LINT-CH-3 — that consistency check belongs to the chart-load-time validator at `tools/sos-codegen/` (per SOS-09-A §5.4); SCXML-LINT-CH-3 enforces only the per-key value-shape constraint, which is the SOS-01-appropriate slice (SOS-01 lints text and vocabulary; behavioural validation is downstream, per INV-S-LINT-6).

  **Example violation:** `{"sos:id": "<UUID>", "sos:name": "tx", "sos:kind": "command", "sos:dir": "bidi"}`.

  **Example fix:** correct to one of the three admitted values.

**Summary-table extension.** The §6.8 summary table (informative) gains a new "Channel-annotation" category row block:

| Rule | Severity at draft | Category |
|---|---|---|
| SCXML-LINT-CH-1 — Unknown `sos:`-prefixed key | `error` | Channel-annotation |
| SCXML-LINT-CH-2 — Illegal `sos:kind` value | `error` | Channel-annotation |
| SCXML-LINT-CH-3 — Illegal `sos:dir` value | `error` | Channel-annotation |

Updated severity counts post-amendment: **error: 14**, **warning: 7**, **info: 0**. (Adds three errors to the §6.8 summary's pre-amendment 11/7/0.)

**Registration policy.** The twelve-key set (§5.2 of SOS-09-A) and the two value enums (`sos:kind` per SOS-09 §5.1; `sos:dir` per SOS-09 §5.2 + SOS-09-A §5.4(3)) all carry **Standards Action** registration policy:

- The twelve-key set is per SOS-09-A §5.2 ratification (PCDN-SOS-09-A-003 ratified 2026-05-25; PCDN-SOS-09-007 follow-on ratified 2026-05-26).
- The `sos:kind` four-value enum is per SOS-09 §5.1 ratification (Standards Action stated there).
- The `sos:dir` enum is per SOS-09 §5.2 mapping rows + SOS-09-A §5.4(3) ratification (Standards Action; the mapping table is the umbrella's load-bearing surface).

Adding a thirteenth `sos:`-prefixed key (e.g. a hypothetical `sos:dma_chain`) requires a **co-landed amendment on both SOS-01 (this rule SCXML-LINT-CH-1) and SOS-09-A (the §5.2 authoritative key list)**. The SOS-09-A amendment is the source of truth; the SOS-01 lint rule's list MUST be kept in lockstep so the lint runner accepts the new key. Same pattern for extending the `sos:kind` enum (requires SOS-09 §5.1 + this rule SCXML-LINT-CH-2) or the `sos:dir` enum (requires SOS-09 §5.2 + this rule SCXML-LINT-CH-3). Per parent CLAUDE.md "Execution discipline", the spec amendments land FIRST in a separate PR; no behaviour PR rides on an unamended invariant.

**Implementation citation.** Tracked alongside the next SOS-01 lint-runner wave; the three rules' implementations land in `tools/sos-codegen/` (the family-wide codegen tool tree, which already hosts the SOS-09-A parse-and-validate path at `tools/sos-codegen/sos09_annotations.py` per the SOS-09 §15.7 2026-05-26 entry). The exact module path is left to the implementation commit; this §15 entry does not invent a path that does not exist.

**Cross-reference to ERRATA.** ERRATA-001 and ERRATA-002 (filename-rename reconciliations under `transliterate_*` for SOS-09-B and SOS-09-G, landed in commit `d24528f`) do not directly intersect this amendment — they touch SVD and MPU emit-path module naming, not lint-rule content. They are cited here as context: the SOS-09 implementation tree settled on the `tools/sos-codegen/transliterate_*.py` / `tools/sos-codegen/sos09_annotations.py` naming, which is the same tree the three new lint rules will land into.

**Future SOS-12 lint family (informative).** Any future SOS-12 dispatch-element lint rules (e.g. nested-depth caps, contract-mismatch reporting per the SOS-12 dispatch+contract annotation parser landed in `45de592`) would land under a separate `SCXML-LINT-DISP-N` series owned by SOS-12, registered in SOS-01's `LintRuleId` namespace per §5.5 (Standards Action). This amendment does not pre-allocate any `SCXML-LINT-DISP-N` ids; SOS-12 owns the series when its first lint rule ratifies.

**Non-goal §11 reconciliation.** SOS-01 §11 forbids "Replacing W3C SCXML 1.0 with a SOS-specific superset". The `sos:`-prefixed `other_attributes` JSON keys do NOT violate this non-goal: per SOS-09-A INV-S-MEM-A-3 / INV-S-MEM-A-4, the `sos:` prefix is a JSON-key STRING convention only — NOT an XML namespace prefix. The chart-side XML carries no `xmlns:sos` declaration (and a chart that does is itself a hard error per SOS-09-A §5.4 (9)). The W3C SCXML 1.0 grammar is unmodified; `other_attributes` is iState's extension surface (relationship `compose` per SOS-09-A §8), and SOS-09 attaches semantic keys inside that pre-existing surface. The §11 prohibition is preserved.

**Chart-file follow-up.** `rtos_kernel.scxml` at HEAD does NOT currently declare any `sos:`-prefixed channel annotations (the kernel chart is a pure-software statechart with no hardware membrane). When the first chart that declares a SOS-09 channel lands (driven by SOS-09-B/-C/-D/-E/-F/-G consumers exercising worked examples), the three new lint rules activate for that chart. This amendment does NOT itself edit `rtos_kernel.scxml`.

**Cross-references.**
- [SOS-09 §12 (i)](./SOS-09-CONCEPTS.md) — gate text closed by this amendment.
- [SOS-09 §15 (2026-05-27 SOS09W1 roll-up)](./SOS-09-CONCEPTS.md) — the umbrella's bookkeeping entry naming the outstanding co-land obligation.
- [SOS-09 §5.1 / §5.2](./SOS-09-CONCEPTS.md) — authoritative source for the four-value `sos:kind` enum and the channel → membrane-primitive mapping (source of the admitted `sos:dir` values).
- [SOS-09-A §5.2](./SOS-09-A-CONCEPTS.md) — authoritative twelve-key set; mirrored verbatim in SCXML-LINT-CH-1.
- [SOS-09-A §5.4](./SOS-09-A-CONCEPTS.md) — chart-load-time validation rules; SCXML-LINT-CH-2 / -CH-3 mirror rules (3) at the SOS-01 lint layer.
- [SOS-09 §15 PCDN-SOS-09-001 amendment (2026-05-25)](./SOS-09-CONCEPTS.md) — JSON-key STRING prefix convention.
- [SOS-09 §15.7 (2026-05-26 PCDN-SOS-09-007)](./SOS-09-CONCEPTS.md) — `sos:channel_group` + `sos:privilege_region` additions completing the twelve-key set.

No frozen-enum value modified at SOS-01 (the `ECMAScriptFeature`, `LintRuleSeverity`, `ExternalEventName`, `StateId`, and pre-existing `SCXML-LINT-001..018` portions of `LintRuleId` are unchanged). The `LintRuleId` namespace (§5.5) grows by three with `SCXML-LINT-CH-1`, `SCXML-LINT-CH-2`, `SCXML-LINT-CH-3`; the category-prefix convention is introduced for downstream-phase-owned lint families as documented above. No PCDN re-ratified. SOS-01 stays 🟢 ratified.
