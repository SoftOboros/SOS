# SOS-09-A — Chart annotation surface

**Status:** 🟢 **ratified 2026-05-25** (all four PCDNs walked; see §16 ratification entry).

## 0. Authority policy

This phase doc is the **chart annotation surface** sub-phase under the SOS-09 umbrella (`SOS-09-CONCEPTS.md`, ratified 2026-05-23; PCDN-SOS-09-001 amended 2026-05-25). The umbrella names seven sub-phases (A–G) in §6 and freezes the cross-sub-phase decisions (channel-category enum `{status, command, queue, shared}` per §5.1; channel → membrane-primitive mapping per §5.2; atomicity class enum per §5.3; protection-zone enum per §5.4; CMSIS-SVD primary + SystemRDL secondary per §5.5). This doc takes those decisions as load-bearing input and produces the chart-attribute schema — how chart authors declare a SOS-09 channel by attaching SOS-semantic keys to existing iState/SCXML elements via iState's `other_attributes` extension surface.

Per the parent CLAUDE.md "Spec-Before-Code Planning Discipline / Phase document shape":

- **Normative** sections of this doc: §3 glossary, §4 source-of-truth map, §5 frozen decisions (allowed parent contexts; permitted attribute keys; parsing rule; validation rules), §7 cross-sub-phase invariants (INV-S-MEM-A-*), §8 standards integration matrix additions, §12 acceptance checklist.
- **Informative** sections: §1 purpose, §2 problem statement, §6 sub-phase scope (N/A — this IS a sub-phase), §11 non-goals, §15 pending PCDNs, §16 change log.
- All keywords MUST, MUST NOT, SHALL, SHOULD, SHOULD NOT, MAY are interpreted per RFC 2119 / RFC 8174 when capitalised.

This doc cites SOS-07 §6 for the cross-phase invariants `INV-SOS-A` through `INV-SOS-H`, SOS-08 §7 for the cross-sub-phase invariants `INV-S-HDL-1` through `INV-S-HDL-5`, and SOS-09 §7 for the cross-sub-phase invariants `INV-S-MEM-1` through `INV-S-MEM-6`. None of these sets is re-derived here.

## 1. Purpose

To freeze the chart-author-facing surface for declaring SOS-09 channels: which existing iState/SCXML elements MAY carry channel annotations, which `sos:`-prefixed keys are permitted inside `other_attributes`, what each key means, which combinations are legal, and how the chart loader parses and validates them. Without this freeze the downstream SOS-09 sub-phases (SOS-09-B CMSIS-SVD emission, SOS-09-C C HAL emission, SOS-09-D Rust HAL emission, SOS-09-E HDL register-file RTL, SOS-09-F membrane vectors, SOS-09-G MPU configuration) cannot author against a stable input surface; SOS-09-A IS the input contract every later SOS-09 sub-phase consumes.

This sub-phase is the foundational membrane-vocabulary freeze. Once it ratifies, chart authors have a stable annotation grammar; once the implementation lands, the codegen has a stable read surface.

## 2. Problem statement

Per SOS-09 §2, the canonical hardware/software co-design failure mode is the "register-map PDF that lies": a register map maintained as documentation out-of-band drifts from the firmware and the silicon, and every downstream artifact inherits the drift. SOS-09's cure is to derive every artifact (SW accessor, HW RTL, register-map XML, MPU table, vector suite) from the chart annotation. For that cure to work, the chart annotation itself MUST be a stable, parseable, validatable surface that every emitter consumes identically.

Three concrete pressures inside the SOS-09 umbrella motivate this sub-phase's freeze:

1. **Annotation surface pressure.** The umbrella's §5.1 channel-category enum and §5.2 channel→primitive mapping are normative, but the umbrella does not pin down *how* a chart author attaches that information to a concrete iState/SCXML element. PCDN-SOS-09-001 was resolved 2026-05-23 in favour of a custom XML namespace, then amended 2026-05-25 in favour of `other_attributes` with a `sos:` STRING key prefix (per SOS-09 §15 amendment entry). This sub-phase concretizes the amended resolution: which parent contexts, which keys, which validation rules.

2. **Parser-and-validator pressure.** The downstream emitters (SOS-09-B through SOS-09-G) MUST read the same annotation surface the same way. Without a frozen parsing rule (extract `sos:`-prefixed keys from `other_attributes` JSON; surface as SOS-semantic) and a frozen validator (required keys per `kind`; enum-value validity; cross-attribute consistency), each downstream emitter would re-derive parsing — exactly the kind of silent fork the spec-before-code discipline prohibits.

3. **Authoring-error pressure.** Chart authors will make mistakes: typo `kind="statu"`, attach `sos:irq` to a `kind="command"` channel, omit `sos:dir`, repeat `sos:id` across two parents. The validator MUST catch every such mistake at chart-load time with an actionable error message; silent acceptance produces a chart that emits four broken artifacts (SVD wrong, HAL wrong, RTL wrong, vectors wrong) before anyone notices.

## 3. Canonical glossary

Terms normative within SOS-09-A+. Authority relationships per §8.

| Term | Definition |
|---|---|
| **chart annotation** | A SOS-09 channel declaration attached to an existing iState/SCXML element via `other_attributes`. As defined in SOS-09 §3 ("channel"); used without modification. The annotation is the four-tuple input that the downstream SOS-09 emitters consume. |
| **annotation parent context** | An iState/SCXML element on which a SOS-09 channel annotation MAY be carried. Owned by this doc (§5.1); restricted to `<region>`, `<state>`, `<parallel>`. Other iState elements (e.g. `<transition>`, `<datamodel>`, `<scxml>` root) are NOT permitted parent contexts in v1. |
| **`other_attributes` extension surface** | iState's JSON-shaped extension attribute on existing iState/SCXML elements. As defined in iState's element schema; used without modification. PCDN-SOS-09-001 amendment (2026-05-25) routed all SOS-09 channel annotations through this surface. |
| **`sos:` key prefix** | The four-character STRING prefix on JSON keys inside `other_attributes` that distinguishes SOS-semantic keys (e.g. `sos:kind`, `sos:dir`) from iState-layout-or-other keys (e.g. `position_x`, `position_y`). NOT an XML namespace prefix; no `xmlns:sos` declaration is registered or expected. Owned by SOS per SOS-09 §8 "SOS-09 channel-annotation key convention" row (relationship: `own`). |
| **required attribute key** | A `sos:`-prefixed key whose presence is mandatory for a valid SOS-09 channel annotation. Per §5.2 (post-2026-05-25 ratification): `sos:id`, `sos:name`, `sos:kind`, `sos:dir`. |
| **optional attribute key** | A `sos:`-prefixed key whose absence is permitted; a default value or inference rule supplies the semantic content when omitted. Per §5.2: `sos:zone`, `sos:atomicity`, `sos:width`, `sos:bit_layout`, `sos:irq`, `sos:mutex`. |
| **kind-gated attribute key** | An optional `sos:`-prefixed key whose validity depends on the value of `sos:kind`. Per §5.2: `sos:irq` (valid only when `kind="status"` and `dir="hw→sw"`); `sos:mutex` (valid only when `kind="shared"`). |
| **chart-load-time validation** | Validation performed when the chart is parsed, before any SOS-09 emit step runs. All §5.4 validation rules MUST be enforced at chart-load time; downstream emitters MAY assume the annotation set has already been validated. |
| **SV identifier** | A token matching the regular expression `[a-zA-Z_][a-zA-Z0-9_]*`. As defined in IEEE 1800-2017 §5.6 ("identifiers"); used without modification. `sos:name` values (the emission-facing handle, per PCDN-SOS-09-A-003 ratification 2026-05-25) MUST be SV identifiers to round-trip through both the CMSIS-SVD `name` field and the SystemVerilog HDL register-file emission without further escaping. |
| **UUID (RFC 4122)** | A 128-bit identifier in canonical hyphenated form: 8-4-4-4-12 hex digits separated by hyphens. As defined in IETF RFC 4122 §3; used without modification. Per PCDN-SOS-09-A-003 ratification 2026-05-25, `sos:id` values MUST be RFC 4122 canonical hyphenated UUIDs — the cross-doc source-of-uniqueness-truth for identity. |

## 4. Source-of-truth map

For every concept this sub-phase touches, **exactly one** location is the canonical authority.

| Concept | Authority |
|---|---|
| Channel-category enum (`status` / `command` / `queue` / `shared`) | `SOS-09-CONCEPTS.md` §5.1 (umbrella, **mirror** here; see §8) |
| Channel → membrane-primitive mapping | `SOS-09-CONCEPTS.md` §5.2 (umbrella, **mirror** here; see §8) |
| Atomicity class enum (`atomic` / `mutex-required`) and default-inference rule | `SOS-09-CONCEPTS.md` §5.3 (umbrella, **mirror** here; see §8) |
| Protection zone enum (`privileged` / `unprivileged`) | `SOS-09-CONCEPTS.md` §5.4 (umbrella, **mirror** here; see §8) |
| iState `other_attributes` extension surface | iState project (external; relationship `compose` per §8) |
| `sos:` key prefix convention | **this doc** (§5.2) — SOS owns the prefix-convention per SOS-09 §8 |
| Allowed annotation parent contexts | **this doc** (§5.1) |
| Permitted `sos:`-prefixed key set | **this doc** (§5.2) |
| Parsing rule | **this doc** (§5.3) |
| Validation rules | **this doc** (§5.4) |
| Cross-sub-phase invariants INV-S-MEM-1 through 6 | `SOS-09-CONCEPTS.md` §7 (cited not redefined) |
| Cross-phase invariants INV-SOS-A through H | `SOS-07-CONCEPTS.md` §6 (cited not redefined) |
| Per-sub-phase chart-annotation-surface invariants INV-S-MEM-A-* | **this doc** (§7) |
| `sos:bit_layout` block schema | **this doc** (§5.2) — PCDN-SOS-09-A-001 ratified 2026-05-25; inline `other_attributes` JSON map; tuple `(field-name / start-bit / width / access / side-effect / reset-value)` |
| Chart-include `sos:id` collision policy | **this doc** (§5 / §10) — PCDN-SOS-09-A-002 ratified 2026-05-25; namespaced compose with inner-scope-hides-outer-scope semantics. Outstanding implementation prerequisite: scjson chart-include support (track as a SOS-09 prerequisite; see §16 ratification entry follow-up note) |
| Multi-`<state>` annotation identity / name policy | **this doc** (§5.2 + §5.4) — PCDN-SOS-09-A-003 ratified 2026-05-25; `sos:id` is RFC 4122 UUID (identity-only); `sos:name` is SV-identifier (emission-facing) and unique within composed scope path |
| Validation-severity policy (enum-value typos) | **this doc** (§5.4 rule 3) — PCDN-SOS-09-A-004 ratified 2026-05-25; hard error by default ("syntax error on any other compiler") |

## 5. Frozen decisions

### 5.1 Allowed annotation parent contexts

A SOS-09 channel annotation MAY attach via `other_attributes` to any of the following iState/SCXML elements (per SOS-09 §6 "SOS-09-A — Chart annotation surface"):

```
parent ∈ { <region>, <state>, <parallel> }
```

Other iState/SCXML elements (`<transition>`, `<datamodel>`, `<data>`, `<onentry>`, `<onexit>`, `<scxml>` root, `<initial>`, `<history>`, `<final>`, `<invoke>`, `<send>`, `<raise>`, `<log>`, `<assign>`, `<if>` / `<elseif>` / `<else>`, `<foreach>`, `<param>`, `<content>`, `<donedata>`) are NOT permitted parent contexts in v1. A `sos:`-prefixed key on a non-permitted parent is a chart authoring error caught by §5.4 validation.

Rationale: `<region>`, `<state>`, and `<parallel>` are the structural carriers of chart membrane scope — a channel's lifetime is the lifetime of the enclosing state. Transitions and actions are events, not scopes; they have no membrane meaning. The `<scxml>` root carries chart-wide annotation (chart name, version) but no per-channel scope, so it is also excluded.

Frozen-enumeration registration policy: **Standards Action** (extending the parent context set changes the chart-author surface; cross-phase ratification needed).

### 5.2 Permitted `sos:`-prefixed key set

A SOS-09 channel annotation is the set of `sos:`-prefixed keys inside the `other_attributes` JSON map on a single permitted parent context. The **twelve** permitted keys are (per PCDN-SOS-09-A-003 ratification 2026-05-25 — `sos:id` shape changed from SV-identifier to UUID, and `sos:name` added as a new required key; and per the **PCDN-SOS-09-007 follow-on amendment 2026-05-26** — `sos:channel_group` and `sos:privilege_region` added as optional axes per the umbrella's "channel-group as two axes" resolution; see §15 entry dated 2026-05-26):

| Key | Required? | Type | Allowed values |
|---|---|---|---|
| `sos:id` | required | UUID (RFC 4122, canonical hyphenated form) | 8-4-4-4-12 hex digits with hyphens (e.g. `550e8400-e29b-41d4-a716-446655440000`); unique within chart per §5.4 (1); identity-only handle |
| `sos:name` | required | SV identifier (string) | `[a-zA-Z_][a-zA-Z0-9_]*`; unique within the composed scope path (per PCDN-SOS-09-A-002 namespaced compose). Used as the emitted name in SVD register, RTL signal, and C macro emission |
| `sos:kind` | required | enum (string) | `status` / `command` / `queue` / `shared` (mirrors SOS-09 §5.1) |
| `sos:dir` | required | enum (string) | depends on `sos:kind`: `status` → `hw→sw`; `command` → `sw→hw`; `queue` → `sw→hw` / `hw→sw` / `hw↔sw`; `shared` → `hw↔sw` (mirrors SOS-09 §5.2; word `bidirectional` retracted as synonym per 2026-05-27 ERRATA-004) |
| `sos:zone` | optional | enum (string) | `privileged` / `unprivileged` (mirrors SOS-09 §5.4); default `privileged` |
| `sos:atomicity` | optional | enum (string) | `explicit` / `implicit`; default `implicit` (apply SOS-09 §5.3 inference rule per `kind`) |
| `sos:width` | optional | integer | `1` ≤ width ≤ `64`; default `32` |
| `sos:bit_layout` | optional | inline JSON block | per PCDN-SOS-09-A-001 ratification 2026-05-25: an inline `other_attributes` JSON map declaring the layout. Block schema is the tuple `(field-name / start-bit / width / access / side-effect / reset-value)` per field |
| `sos:irq` | optional | string | logical IRQ name (mapped per-target by SOS-09-B emitter per SOS-09 PCDN-004); only valid when `sos:kind="status"` AND `sos:dir="hw→sw"` |
| `sos:mutex` | optional | string | mutex name (instantiated as a `sos_mutex` per SOS-08-A §6.5; SOS-09 §5.3); only valid when `sos:kind="shared"` |
| `sos:channel_group` | optional | SV identifier (string) | `[a-zA-Z_][a-zA-Z0-9_]*`; names the Rust borrow scope / shared `RegisterBlock` boundary the channel belongs to (SOS-09-D consumer). Default-from-inheritance: when absent, the channel inherits from the enclosing parallel/compound state's `sos:channel_group` declaration, or `"default"` if no ancestor declares. Inheritance is consumer-side (SOS-09-D) — the parser surfaces raw `Optional[str]`. Origin: PCDN-SOS-09-007 ratification 2026-05-26 ("channel-group as two axes"). |
| `sos:privilege_region` | optional | SV identifier (string) | `[a-zA-Z_][a-zA-Z0-9_]*`; names the HDL MPU privilege region / access-violation aggregation domain the channel belongs to (SOS-09-E consumer). Default-from-inheritance: when absent, the channel inherits from the enclosing parallel/compound state's `sos:privilege_region` declaration, or `"default"` if no ancestor declares. Inheritance is consumer-side (SOS-09-E) — the parser surfaces raw `Optional[str]`. Origin: PCDN-SOS-09-007 ratification 2026-05-26 ("channel-group as two axes"). |

**Identity vs name split (per PCDN-SOS-09-A-003 ratification 2026-05-25).** `sos:id` is the cross-doc source-of-uniqueness-truth: a UUID per RFC 4122 in canonical hyphenated form. The UUID is identity-only; downstream emitters MUST NOT use it as an emitted symbol name. `sos:name` is the human-readable / emission-facing handle: SV-identifier-shaped, unique within the composed scope path (NOT chart-wide — two charts MAY independently declare `sos:name="rx_path"`; the composed path differentiates them as e.g. `<outer>.<inner>.rx_path` in the final emit). The composed-name hierarchy provides emission uniqueness; the UUID owns identity.

The `sos:kind` enum values (`status`, `command`, `queue`, `shared`) are **mirrored** from SOS-09 §5.1 without modification; this sub-phase does NOT introduce additional kind values. Per SOS-09 §5.1 frozen-enumeration registration policy (Standards Action), extending the kind set requires a §16 amendment to `SOS-09-CONCEPTS.md`, not to this doc.

The twelve-key set above is frozen at v1 (per ratifications of PCDN-SOS-09-A-001 / -003 and the PCDN-SOS-09-007 follow-on amendment 2026-05-26). Adding a thirteenth permitted SOS-semantic key requires a §16 amendment to this doc (Standards Action — see below).

Frozen-enumeration registration policy: **Standards Action** for the twelve-key set (extending the set changes the chart-author surface and the downstream emitter contract).

### 5.3 Parsing rule

The SOS-09-A walker reads `other_attributes` JSON on each parent element of `<region>`, `<state>`, or `<parallel>` (per §5.1). For each JSON key in the map:

1. If the key begins with the four-character string `sos:`, surface the key (with prefix) and value as a SOS-semantic channel-annotation attribute.
2. Otherwise, treat the key as an iState-layout-or-other attribute (e.g. `position_x`, `position_y`); SOS-09-A does NOT process it.

The walker MUST NOT register an XML namespace `xmlns:sos` (or any other URL) for the `sos:` prefix. Per the PCDN-SOS-09-001 amendment of 2026-05-25 (SOS-09 §16), the prefix is purely a JSON-key STRING convention; the surrounding XML carries NO namespace declaration for SOS-09 channel annotations.

Per INV-SOS-D (scjson round-trip), `other_attributes` JSON round-trips through scjson without loss; the `sos:`-prefixed keys ride the same path.

### 5.4 Validation rules

The chart loader MUST enforce the following validation rules at chart-load time. Each rule MUST emit an actionable error message naming the offending parent element (by chart `id` or path), the offending key (if applicable), and the rule violated. The default severity is hard error (subject to PCDN-SOS-09-A-004).

**(1) Unique `sos:id` within chart.** No two SOS-09 channel annotations within a single chart MAY share a `sos:id` value. Per PCDN-SOS-09-A-003 ratification 2026-05-25, same-`sos:id` on two parent elements is a hard error (with the error message naming both parent elements and the offending UUID).

**(2) Required attributes present.** For every parent context carrying any `sos:`-prefixed key, the four required keys (`sos:id`, `sos:name`, `sos:kind`, `sos:dir`) MUST be present. Missing `sos:id`, `sos:name`, `sos:kind`, or `sos:dir` is a hard error.

**(3) Enum value validity.** The `sos:kind` value MUST be one of `status` / `command` / `queue` / `shared`. The `sos:dir` value MUST be one of `hw→sw` / `sw→hw` / `hw↔sw` (per [SOS-09 §5.2](./SOS-09-CONCEPTS.md#52-channel--membrane-primitive-mapping) as canonical; the word `bidirectional` is retracted as a synonym per the 2026-05-27 §16 ERRATA-004 amendment). The `sos:zone` value (if present) MUST be one of `privileged` / `unprivileged`. The `sos:atomicity` value (if present) MUST be one of `explicit` / `implicit`. Typos (e.g. `kind="statu"`) MUST be caught at this rule; per PCDN-SOS-09-A-004 ratification 2026-05-25, the severity is hard error by default ("syntax error on any other compiler" — silent acceptance is prohibited).

**(4) Cross-attribute consistency for `kind`/`dir`.** The `sos:dir` value MUST be valid for the declared `sos:kind` per the table in §5.2 (`status` → `hw→sw`; `command` → `sw→hw`; `queue` → any of the three; `shared` → `hw↔sw`). A `status` channel with `dir="sw→hw"` is a hard error.

**(5) Kind-gated attribute validity.** `sos:irq` MUST appear only when `sos:kind="status"` AND `sos:dir="hw→sw"`; appearance under any other `kind`/`dir` combination is a hard error. `sos:mutex` MUST appear only when `sos:kind="shared"`; appearance under any other `kind` is a hard error.

**(6) Width range.** When `sos:width` is present, its integer value MUST satisfy `1 ≤ width ≤ 64`. Values outside this range are a hard error. Non-integer string values (e.g. `"thirty-two"`) are also a hard error.

**(7) `sos:id` token shape.** Per PCDN-SOS-09-A-003 ratification 2026-05-25, the `sos:id` value MUST be a UUID in RFC 4122 canonical hyphenated form (8-4-4-4-12 hex digits with hyphens, lowercase or uppercase per RFC 4122 §3, e.g. `550e8400-e29b-41d4-a716-446655440000`). Values that do not match the RFC 4122 canonical hyphenated pattern are a hard error. The `sos:name` value (NOT `sos:id`) MUST be an SV identifier (per §3 glossary); a `sos:name` containing `-`, `.`, whitespace, or starting with a digit is a hard error.

**(8) Parent context validity.** A parent element carrying any `sos:`-prefixed key MUST be one of `<region>`, `<state>`, or `<parallel>` (per §5.1). A `sos:`-prefixed key on any other element is a hard error.

**(9) XML namespace prohibition.** The chart MUST NOT carry an `xmlns:sos="..."` declaration on `<scxml>` or any descendant element. Per the PCDN-SOS-09-001 amendment of 2026-05-25, the `sos:` prefix is a JSON-key string convention only; an XML namespace declaration is a chart authoring error and a hard error at chart-load time. The recommended error message: "`xmlns:sos` declaration not permitted: SOS-09 channel annotations use `other_attributes` keys with a `sos:` string prefix, not an XML namespace; remove the `xmlns:sos` declaration and place the `sos:`-prefixed keys inside `other_attributes` JSON on the parent element."

Frozen-enumeration registration policy for the validation-rule set: **Standards Action** (the set of rules is the chart-load-time validator's complete contract; modifying it affects every downstream emitter's read assumptions).

## 6. Sub-phase scope

— (Not applicable. This doc IS a sub-phase of the SOS-09 umbrella; the umbrella's §6 owns sub-phase scope.)

## 7. Cross-sub-phase invariants — INV-S-MEM-A-1 through 7

In addition to the cross-phase invariants INV-SOS-A through H (SOS-07 §6), the SOS-08 cross-sub-phase invariants INV-S-HDL-1 through 5 (SOS-08 §7), and the SOS-09 cross-sub-phase invariants INV-S-MEM-1 through 6 (SOS-09 §7) — all cited but not redefined — the following invariants are normative across the SOS-09-A chart-annotation surface:

- **INV-S-MEM-A-1 — Unique `sos:id` within chart.** Every SOS-09 channel within a single chart is uniquely identified by its `sos:id` value (an RFC 4122 UUID per PCDN-SOS-09-A-003 ratification 2026-05-25). Per §5.4 (1), duplicate `sos:id` is a hard error at chart-load time. Specializes INV-S-MEM-1 (single-source register definition) to the chart-annotation surface: the `sos:id` UUID IS the channel's chart-level identity handle. The emission-facing handle is `sos:name` (SV-identifier, unique within composed scope path), used by every emitted artifact (CMSIS-SVD register name, HAL accessor name, RTL register-file entry name, MPU table row, membrane vector). The UUID owns identity; the composed-name hierarchy provides emission uniqueness.

- **INV-S-MEM-A-2 — Required attributes validated at chart-load time.** Per §5.4 (2), the four required keys (`sos:id`, `sos:name`, `sos:kind`, `sos:dir` — post-PCDN-SOS-09-A-003 ratification 2026-05-25) MUST be present on every SOS-09 channel annotation; missing keys raise an actionable error before any SOS-09 emit step runs. Downstream emitters (SOS-09-B through SOS-09-G) MAY assume the required-attribute set is complete; they MUST NOT re-implement presence checks.

- **INV-S-MEM-A-3 — `sos:`-prefixed keys are NEVER reinterpreted as XML namespace declarations.** The `sos:` prefix is a JSON-key STRING prefix inside `other_attributes`, not an XML namespace prefix. The SOS-09-A walker and every downstream emitter MUST treat `sos:`-prefixed keys as ordinary JSON keys; under no circumstance is a SOS-semantic key surfaced via `xmlns:sos` URL resolution. Per the PCDN-SOS-09-001 amendment of 2026-05-25 (SOS-09 §16), the namespace URL `https://softoboros.com/sos/1.0` is NOT registered, claimed, or implied.

- **INV-S-MEM-A-4 — `xmlns:sos` declarations in chart-author XML are errors.** Per §5.4 (9), a chart that declares `xmlns:sos="..."` on `<scxml>` or any descendant element is rejected at chart-load time. Specializes INV-S-MEM-A-3 to the chart-author-facing failure mode: the validator catches the mistake before any emitter runs, with an actionable error message naming the offending element and recommending the corrective edit.

- **INV-S-MEM-A-5 — Cross-attribute consistency rejects illegal `kind`/`dir` pairs.** Per §5.4 (4), the `sos:dir` value MUST be valid for the declared `sos:kind` per the §5.2 table. A `status` channel with `dir="sw→hw"`, a `command` channel with `dir="hw↔sw"`, or a `shared` channel with `dir="hw→sw"` is a hard error. This invariant guarantees that the channel→membrane-primitive mapping (SOS-09 §5.2) always lands on a defined row.

- **INV-S-MEM-A-6 — Kind-gated attributes are kind-gated.** Per §5.4 (5), `sos:irq` MUST appear only on `kind="status"` with `dir="hw→sw"`; `sos:mutex` MUST appear only on `kind="shared"`. Misplaced kind-gated attributes are hard errors. This invariant guarantees that the downstream emitters can rely on the presence of `sos:irq` implying an interrupt-emitting status channel and the presence of `sos:mutex` implying a mutex-protected shared region.

- **INV-S-MEM-A-7 — Parent-context restriction is enforced.** Per §5.4 (8), `sos:`-prefixed keys appear only on `<region>`, `<state>`, or `<parallel>` elements. SOS-09-A annotations on `<transition>`, `<datamodel>`, `<scxml>`, or any other iState/SCXML element are hard errors. This invariant scopes channel-lifetime semantics to structural carriers, not to events or chart-wide declarations.

## 8. Standards integration matrix additions

The following rows EXTEND the SOS-07 §7 matrix and the SOS-09 §8 row set:

| Concept | Upstream authority | Local relationship | Phase that declares it | Mutation rights |
|---|---|---|---|---|
| iState `other_attributes` extension surface | iState project | **compose** (SOS-09-A attaches `sos:`-prefixed JSON keys; iState owns the surface) | SOS-09-A | iState owns the extension surface; SOS preserves the JSON round-trip per INV-SOS-D |
| SOS-09 §5.1 channel `kind` enum (`status` / `command` / `queue` / `shared`) | `SOS-09-CONCEPTS.md` §5.1 (umbrella) | **mirror** (no extension at this sub-phase) | SOS-09-A | none — extending the enum requires a §16 amendment to the umbrella, not to this doc |
| SOS-09 §5.2 channel → membrane-primitive mapping | `SOS-09-CONCEPTS.md` §5.2 (umbrella) | **mirror** | SOS-09-A | none — same as above |
| SOS-09 §5.3 atomicity-class enum (`atomic` / `mutex-required`) | `SOS-09-CONCEPTS.md` §5.3 (umbrella) | **mirror** | SOS-09-A | none — same as above |
| SOS-09 §5.4 protection-zone enum (`privileged` / `unprivileged`) | `SOS-09-CONCEPTS.md` §5.4 (umbrella) | **mirror** | SOS-09-A | none — extension to four-zone TrustZone-style enum is gated by SOS-09 PCDN-006 |
| W3C SCXML element vocabulary (`<state>`, `<parallel>`, `<region>`) | W3C (SCXML 1.0) | **mirror** (SOS-09-A attaches annotations to existing W3C-defined elements without redefining them) | SOS-09-A | none — W3C owns the element vocabulary |
| IEEE 1800-2017 §5.6 identifier shape (for `sos:id` value space) | IEEE | **mirror** (SV identifiers are the round-trip-safe shape for both CMSIS-SVD `name` fields and HDL register-file names) | SOS-09-A | none |

Per INV-SOS-E, the row addition policy is the same as SOS-07 §7: **Specification Required** for adding new rows (phase-owner walkthrough), **Standards Action** for modifying an existing row's relationship value.

## 9. Frozen enumerations recap

This sub-phase freezes the following enumerations (each declared in §5 with its registration policy):

- §5.1 Allowed annotation parent contexts — `{ <region>, <state>, <parallel> }` — **Standards Action**.
- §5.2 Permitted `sos:`-prefixed key set — `{ sos:id, sos:name, sos:kind, sos:dir, sos:zone, sos:atomicity, sos:width, sos:bit_layout, sos:irq, sos:mutex, sos:channel_group, sos:privilege_region }` (twelve keys, post-PCDN-SOS-09-007 follow-on amendment 2026-05-26; previously ten keys post-PCDN-SOS-09-A-003 ratification 2026-05-25) — **Standards Action**.
- §5.2 Per-key allowed-value sets (`kind`, `dir`, `zone`, `atomicity`) — **mirror** from SOS-09 §5.1 / §5.2 / §5.3 / §5.4 (no local mutation rights).
- §5.4 Validation-rule set (nine rules) — **Standards Action**.

Plus:

- §7 Cross-sub-phase chart-annotation-surface invariants — `{ INV-S-MEM-A-1 ... INV-S-MEM-A-7 }` — **Standards Action**.

## 10. Reconciliation decisions vs adjacent repo primitives

### vs. SOS-09 umbrella §6 (sub-phase scope sketch)

The umbrella's §6 "SOS-09-A — Chart annotation surface" entry sketches the same surface this doc concretizes: allowed parent contexts `<region>` / `<state>` / `<parallel>`, the `sos:`-key set, the PCDN-SOS-09-001 amendment that routed annotations through `other_attributes`. This doc adds the validation-rule depth that the umbrella sketch did not carry. The umbrella and this doc are mutually consistent; no conflict.

### vs. SOS-09 §5.1 / §5.2 / §5.3 / §5.4 (umbrella frozen enums)

This sub-phase **mirrors** the umbrella's channel-category enum, channel→primitive mapping, atomicity-class enum, and protection-zone enum without modification. Per §8, the mutation rights row for each is "none — extending the enum requires a §16 amendment to the umbrella, not to this doc." A future PCDN that proposes extending any of these enums MUST file against `SOS-09-CONCEPTS.md` directly; this doc adopts the resolution.

### vs. SOS-09 §16 2026-05-25 PCDN-SOS-09-001 amendment

The amendment is the load-bearing input to this sub-phase. Per the amendment, SOS-09 channel annotations attach via `other_attributes` with a `sos:` STRING key prefix; no `xmlns:sos` declaration is registered or expected. INV-S-MEM-A-3 and INV-S-MEM-A-4 enforce the amendment's wording in invariant form; §5.4 (9) operationalizes it as a hard-error validation rule. This doc does NOT re-ratify the amendment; it consumes it.

### vs. SOS-08-D / SOS-08-E namespaced element vocabulary

Per the PCDN-SOS-09-001 amendment scope clause: SOS-08-D's and SOS-08-E's namespaced ELEMENT vocabulary (`<sos:cross_invariant>`, `<sos:state_ref>`, `<sos:shared_signal>`, `<sos:clock_domains>`, `<sos:channel>` as a NEW element in SOS-08-D / -E vocabulary, etc.) is OUTSIDE the scope of this sub-phase. SOS-09-A governs `sos:`-prefixed JSON keys inside `other_attributes` on existing elements; it does NOT govern new XML elements with namespaced tags. The element-vs-attribute distinction is preserved.

### vs. iState `other_attributes` precedent (`position_x`, `position_y`)

iState already attaches layout annotations (`position_x`, `position_y`) via `other_attributes`. SOS-09-A adds SOS-semantic annotations to the same JSON map. Both coexist; the `sos:` prefix on SOS-09-A keys distinguishes them from iState layout keys. The parsing rule (§5.3) explicitly partitions the key set: `sos:`-prefixed keys are SOS-semantic; non-`sos:`-prefixed keys are iState-layout-or-other.

### vs. SOS-04 / SOS-05 register-access pattern

SOS-09-A is upstream of SOS-09-C / SOS-09-D HAL emission, which is in turn distinct from SOS-04 / SOS-05's existing register-access pattern (`cortex-m::Peripherals::steal()`, direct `core::ptr::read_volatile`). Per SOS-09 §10, the two coexist. This sub-phase does not interact with SOS-04 / SOS-05 directly; the boundary is recorded in the SOS-04 §15 amendment co-landing with the umbrella ratification.

## 11. Non-goals

This sub-phase does NOT:

- Author the CMSIS-SVD emit path (that's SOS-09-B).
- Author the C HAL emit path (that's SOS-09-C).
- Author the Rust HAL emit path (that's SOS-09-D).
- Author the HDL register-file RTL emit path (that's SOS-09-E).
- Author the membrane-vector emit path (that's SOS-09-F).
- Author the MPU-configuration emit path (that's SOS-09-G).
- Extend the SOS-09 §5.1 channel-category enum or the §5.2 channel→primitive mapping. Per §8, both are **mirrored** without modification; extensions require a §16 amendment to `SOS-09-CONCEPTS.md`.
- Specify the `sos:bit_layout` block schema (inline vs external; layout-block element shape). Deferred to PCDN-SOS-09-A-001.
- Specify chart-include semantics (whether SOS supports `<sos:include>`-style chart composition, and if so how `sos:id` namespaces interact). Deferred to PCDN-SOS-09-A-002.
- Specify multi-`<state>` annotation policy (same `sos:id` on two parent elements — one channel with scope union, two channels, or an error). Deferred to PCDN-SOS-09-A-003; at v1 pending resolution, duplicate `sos:id` is a hard error per §5.4 (1).
- Specify validation severity policy (hard error vs warning on enum-value typos). Deferred to PCDN-SOS-09-A-004; at v1 pending resolution, the default severity is hard error per §5.4 (3).
- Register an XML namespace URL for the `sos:` prefix. Per INV-S-MEM-A-3 and INV-S-MEM-A-4, the prefix is purely a JSON-key string convention; no URL is registered, claimed, or implied.

## 12. Acceptance checklist

A conforming SOS-09-A ratification satisfies:

- (a) ⏸ PCDN-SOS-09-A-001 through 004 resolved (§15).
- (b) ⏸ The chart loader implements §5.3 parsing rule: `sos:`-prefixed keys surfaced as SOS-semantic; non-`sos:`-prefixed keys pass through as iState-layout-or-other.
- (c) ⏸ The chart loader implements §5.4 validation rules (1)–(9); each emits an actionable error message naming the offending parent element, key, and rule violated.
- (d) ⏸ A worked-example chart with at least one channel per kind (`status`, `command`, `queue`, `shared`) parses, validates, and round-trips through scjson without loss (per INV-SOS-D).
- (e) ⏸ A chart-authoring-error test suite covers every §5.4 validation-rule failure mode: missing required attribute, enum-value typo, cross-attribute inconsistency, kind-gated attribute misplacement, width out of range, malformed `sos:id`, parent-context violation, `xmlns:sos` declaration.
- (f) ⏸ Cross-phase invariants INV-SOS-A through H cited correctly; cross-sub-phase invariants INV-S-MEM-1 through 6 cited correctly; cross-sub-phase chart-annotation-surface invariants INV-S-MEM-A-1 through 7 satisfied by the implementation.
- (g) ⏸ SOS-01 §15 amendment co-lands adding the channel-annotation lint rules per the umbrella's §12 (i) gate, citing this sub-phase as the rule source.
- (h) ⏸ Downstream sub-phase docs (SOS-09-B through SOS-09-G) cite this sub-phase as their input contract; no downstream sub-phase re-implements §5.3 parsing or §5.4 validation.

(a) is the ratification gate; (b)–(h) are implementation gates that flip from ⏸ to ✅ as the implementation lands.

A conforming SOS-09-A *without* a resolved PCDN-SOS-09-A-001 (i.e. without the `sos:bit_layout` block schema) satisfies (a)–(d) and a reduced (e)/(f)/(h) — charts using `sos:bit_layout` are rejected with a "feature deferred" error message, and downstream emitters (SOS-09-B / -C / -D / -E) emit a default bit layout per the SOS-09 §15 PCDN-SOS-09-003 resolution (per-target derived). This second-tier conformance level supports the SOS-09 umbrella worked-example acceptance gate without the bit-layout complexity, deferring custom bit layouts to a later sub-phase amendment.

## 13. Files cited

| Path | Role |
|---|---|
| `docs/concepts/SOS-09-CONCEPTS.md` | Umbrella; this sub-phase's parent. §5.1 / §5.2 / §5.3 / §5.4 frozen enums mirrored here; §7 INV-S-MEM-1 through 6 cited; §16 PCDN-SOS-09-001 amendment of 2026-05-25 is load-bearing input. |
| `docs/concepts/SOS-07-CONCEPTS.md` | Cross-phase invariants INV-SOS-A through H; cited not redefined. |
| `docs/concepts/SOS-08-CONCEPTS.md` | HDL backend umbrella; INV-S-HDL-1 through 5 cited not redefined; L0 primitives `sos_mutex`, `sos_strobe_latch`, `sos_dpram_arb` referenced in §5.2 mirror. |
| `docs/concepts/SOS-ROADMAP-07-PLUS.md` | Informative roadmap. |
| `docs/concepts/SOS-01-CONCEPTS.md` | Chart-lint surface; §12 (g) gate names the SOS-01 §15 amendment that adds the channel-annotation lint rules. |
| `docs/concepts/SOS-03-CONCEPTS.md` | Vector framework; cited indirectly via SOS-09-F (membrane vectors). |
| `docs/concepts/SOS-04-CONCEPTS.md` | M7 Rust port; cited indirectly via the SOS-09 / SOS-04 boundary. |
| `tools/sos-codegen/` | Codegen tool; gains SOS-09-A parse-and-validate path when implementation lands. |
| Parent `CLAUDE.md` | Spec-Before-Code Planning Discipline. |

## 14. Unblocks

This sub-phase's ratification (after PCDN walkthrough) unblocks:

- **SOS-09-B** (CMSIS-SVD emission) — depends on the frozen annotation surface as input.
- **SOS-09-C** (C HAL header emission) — same.
- **SOS-09-D** (Rust HAL trait emission) — same.
- **SOS-09-E** (HDL register-file RTL) — same.
- **SOS-09-F** (membrane vectors) — same.
- **SOS-09-G** (MPU configuration emission) — same.
- The worked-example chart annotation that satisfies SOS-09 umbrella §12 (c) (one channel emits all six artifacts).
- The SOS-01 §15 amendment that adds the chart-annotation lint rules (SOS-09 umbrella §12 (i)).

## 15. Pending Concept Decision Notices (PCDNs)

These are the open questions whose resolution moves this doc from 🟡 drafted to 🟢 ratified. PCDN-SOS-09-A-* identifiers are stable per parent CLAUDE.md "Errata Open Question" naming (these are PCDNs at the concepts-doc level; the analogous shape applies).

- **PCDN-SOS-09-A-001 — `sos:bit_layout` reference shape (inline vs external block; layout block schema).** 🟢 **ratified 2026-05-25 — see §16 ratification entry below.** The `sos:bit_layout` key (per §5.2) references a layout block by `sos:id`; this PCDN specifies the layout block itself. Options: (a) inline — the layout is declared as another `other_attributes` JSON map on the same parent or a sibling parent, identified by its own `sos:id`; (b) external — the layout is declared in a separate `<sos:bit_layout>` element (which would, per §10 reconciliation, fall under SOS-08-D / -E namespaced-element scope, not SOS-09-A); (c) both. **Recommendation**: option (a) inline at v1 — keeps the surface inside `other_attributes`; defers the namespaced-element question to the next ratification round. The layout block schema (field-name / start-bit / width / access / side-effect / reset-value tuple) is itself a sub-PCDN landing with the resolution. Registration policy: **Standards Action** (the layout-block schema is part of the chart-author surface).

- **PCDN-SOS-09-A-002 — `sos:id` collision policy for chart inclusion.** 🟢 **ratified 2026-05-25 — see §16 ratification entry below.** If SOS supports chart-include (e.g. `<sos:include>`-style chart composition), what happens when two included charts both declare `sos:id="rx_path"`? Options: (a) hard error at include-resolution time; (b) outer scope wins, inner is shadowed; (c) namespaced compose (`{outer_id}.{inner_id}`); (d) chart-include not supported at v1 (forward-compat-only). **Investigation needed**: whether iState supports chart-include in any form today; if not, the PCDN is forward-compat-only and the resolution is (d) at v1. **Recommendation**: (d) at v1 — if chart-include lands later, a new PCDN against this doc names the collision policy. Registration policy: **Standards Action**.

- **PCDN-SOS-09-A-003 — Multi-`<state>` annotation policy (same `sos:id` on two parent elements).** 🟢 **ratified 2026-05-25 — see §16 ratification entry below.** When a chart annotates the SAME `sos:id` on two different parent elements (e.g. `<state id="rx">` and `<state id="tx">` both carry `other_attributes='{"sos:id": "ch_a", ...}'`), is that (a) two channels (illegal — duplicate `sos:id` per §5.4 (1)); (b) one channel with scope union of the two parents; (c) an error caught by §5.4 (1) with a more-specific error message; (d) one channel scoped to the nearest common ancestor in the SCXML hierarchy. **Recommendation**: (c) — hard error, with the error message naming both parent elements and the `sos:id` value. The "scope union" semantic ((b) or (d)) is appealing on first read but creates ambiguity for downstream emitters (which parent's `<onentry>` activates the channel?). One-channel-one-parent is the simpler rule. Registration policy: **Standards Action**.

- **PCDN-SOS-09-A-004 — Validation severity policy: hard error vs warning on enum-value typos.** 🟢 **ratified 2026-05-25 — see §16 ratification entry below.** §5.4 (3) catches `kind="statu"` (typo of `status`); is the default severity hard error or warning? Options: (a) hard error — chart-load fails; chart author MUST fix before any SOS-09 emit step runs; (b) warning — chart loads with the invalid annotation discarded; emit proceeds with reduced output; (c) mode-gated — hard error in CI, warning in interactive iState authoring. **Recommendation**: (a) hard error by default. Silent acceptance of typos produces a chart that emits broken artifacts; the cost of typing the correct enum value is trivial. The mode-gated form ((c)) is appealing but adds configuration surface for a marginal case. Registration policy: **Specification Required** (severity policy is local to chart-load validation; flipping it later is cheaper than flipping a chart-author-surface decision).

## 16. Change log

### 2026-05-25 — Initial draft (Ira)

- Authored `SOS-09-A-CONCEPTS.md` as the chart-annotation-surface sub-phase under the SOS-09 umbrella.
- §3 canonical glossary: terms `chart annotation`, `annotation parent context`, `other_attributes extension surface`, `sos: key prefix`, `required attribute key`, `optional attribute key`, `kind-gated attribute key`, `chart-load-time validation`, `SV identifier`.
- §4 source-of-truth map: per-concept authority (umbrella for shared enums; this doc for parsing/validation/key-set).
- §5 frozen decisions: allowed parent contexts `{<region>, <state>, <parallel>}` (§5.1); nine permitted `sos:`-prefixed keys with required/optional/kind-gated classification (§5.2); JSON-key-prefix parsing rule with explicit no-XML-namespace clause (§5.3); nine validation rules with hard-error-default severity (§5.4).
- §7 cross-sub-phase chart-annotation-surface invariants INV-S-MEM-A-1 through 7: unique `sos:id`, required-attribute presence, no-XML-namespace reinterpretation, `xmlns:sos` declarations as chart-load-time errors, cross-attribute kind/dir consistency, kind-gated attribute validity, parent-context restriction.
- §8 standards integration matrix additions: 7 rows — iState `other_attributes` (`compose`), SOS-09 §5.1/§5.2/§5.3/§5.4 enums (`mirror` from umbrella), W3C SCXML element vocabulary (`mirror`), IEEE 1800-2017 §5.6 SV identifier (`mirror`).
- §10 reconciliation: vs SOS-09 umbrella; vs SOS-09 §5 frozen enums (mirror, no local mutation); vs SOS-09 §16 PCDN-001 amendment; vs SOS-08-D / -E namespaced-element scope (out-of-scope here); vs iState `other_attributes` precedent (`position_x`, `position_y`); vs SOS-04 / SOS-05 register-access pattern.
- §11 non-goals: explicit deferral of downstream emit paths, of §5.1 / §5.2 enum extensions (umbrella owns), of `sos:bit_layout` block schema (PCDN-A-001), of chart-include semantics (PCDN-A-002), of multi-`<state>` annotation policy (PCDN-A-003), of validation severity policy (PCDN-A-004), and of XML namespace registration (forbidden by INV-S-MEM-A-3 / INV-S-MEM-A-4).
- §12 acceptance checklist: gates (a)–(h); reduced conformance level without `sos:bit_layout`.
- §15 four PCDNs raised covering bit-layout reference shape, chart-include collision policy, multi-`<state>` annotation policy, and validation severity policy.

Status: 🟡 **drafted**, awaiting PCDN walkthrough.

### 2026-05-25 — Ratified (Ira)

All four PCDNs walked and resolved in a ratification session 2026-05-25:

| PCDN | Resolution | Registration policy |
|---|---|---|
| **PCDN-SOS-09-A-001 — `sos:bit_layout` reference shape** | ✅ Option (a) inline `other_attributes` JSON map at v1. Layout block schema lands with this ratification: tuple `(field-name / start-bit / width / access / side-effect / reset-value)` per field. | Standards Action |
| **PCDN-SOS-09-A-002 — `sos:id` collision policy for chart inclusion** | ✅ Option (c) namespaced compose with **(b)-style reverse semantics: inner scope hides outer scope** (programming-language locals-shadow-globals pattern). When chart A includes chart B and both declare a channel with `sos:id="<X>"`, the inner (B's) declaration is the active resolution within B's scope. Both declarations remain accessible via explicit qualification: `<outer_chart>.<channel>` vs `<inner_chart>.<channel>`. Bare reference (no prefix) resolves to the innermost scope's declaration. | Standards Action |
| **PCDN-SOS-09-A-003 — Multi-`<state>` annotation / identity vs name** | ✅ Hard error on duplicate `sos:id` (no scope-union semantic). **`sos:id` shape changes from SV-identifier to UUID (RFC 4122 canonical hyphenated form)** to serve as cross-doc source-of-uniqueness-truth. **New required key `sos:name`** added (SV-identifier shape; unique within composed scope path per the A-002 namespaced compose rule, NOT chart-wide). The UUID owns identity; the composed-name hierarchy provides emission uniqueness (used by SVD register name, RTL signal name, C macro name). | Standards Action |
| **PCDN-SOS-09-A-004 — Validation severity policy** | ✅ Option (a) hard error by default ("syntax error on any other compiler" — user's exact framing). Silent acceptance of enum-value typos is prohibited. | Specification Required |

**Outstanding follow-up (PCDN-SOS-09-A-002, not blocking ratification).** Chart-include is referenced by the user as already supported via `<send>` semantics in scjson. A brief scan of `ops/packer/submodules/scjson/` did NOT find chart-include or cross-chart `<send target=...>` patterns in the scjson Python or docs surface at this ratification time. If scjson truly lacks chart-include support today, this PCDN's resolution becomes operative only once chart-include lands in scjson (or in iState's chart-authoring surface). Track as a SOS-09 implementation prerequisite — file a scjson issue if chart-include is needed before SOS-09-A implementation begins. Cite this §16 entry from the SOS-09 implementation start.

**Spec amendments landing with this ratification.**

- **§5.2 ten-key set.** The permitted `sos:`-prefixed key set grows from nine to ten with the addition of `sos:name`. The required-attribute count grows from three to four (`sos:id`, `sos:name`, `sos:kind`, `sos:dir`). `sos:id` is now RFC 4122 UUID-shaped (was SV-identifier); `sos:name` is the SV-identifier-shaped emission-facing handle.
- **§5.4 validation rules.** Rule (2) updated to require four keys (added `sos:name`). Rule (7) updated to demand RFC 4122 UUID shape on `sos:id` and SV-identifier shape on `sos:name`. Rule (3) confirmed hard error by default per PCDN-SOS-09-A-004.
- **§3 glossary.** New entry for "UUID (RFC 4122)". SV-identifier entry updated to point at `sos:name` (not `sos:id`).
- **§5.2 `sos:bit_layout`.** Clarified to declare an inline `other_attributes` JSON map per PCDN-SOS-09-A-001; layout block schema is the tuple `(field-name / start-bit / width / access / side-effect / reset-value)`.
- **§4 source-of-truth map.** Deferred rows for the four PCDNs replaced with their ratified outcomes.
- **§7 INV-S-MEM-A-1 / INV-S-MEM-A-2.** Updated to cite the identity/name split (UUID vs SV-identifier) and the four-required-key set.
- **§9 frozen enumerations recap.** Key-set listing updated to enumerate the ten keys.

**New chart-level annotation keys introduced.** `sos:name` (required, SV-identifier, unique within composed scope path).

Status: 🟢 **ratified**. SOS-09-A's chart-annotation surface is now stable; downstream sub-phases (SOS-09-B, SOS-09-C, SOS-09-D, SOS-09-E, SOS-09-F, SOS-09-G) MAY proceed against the frozen key-set and validation rules. The SOS-09 implementation work (chart-loader parse + validate; emitter inputs) is unblocked, subject to the PCDN-SOS-09-A-002 implementation prerequisite noted above.

### 2026-05-26 — §5.2 ten-key → twelve-key expansion (PCDN-SOS-09-007 follow-on) (Ira)

**Originating decision.** The SOS-09 umbrella ratified umbrella-level PCDN-SOS-09-007 as option (b) "channel-group as two axes" — the underlying need (Rust borrow scope boundaries) and the underlying need (HDL MPU access-violation aggregation domains) are two semantically distinct axes that the chart MUST be able to declare independently. The umbrella's `SOS-09-CONCEPTS.md` §15.7 (dated 2026-05-26) captures the ratification and names the two new keys; this entry operationalises that decision in SOS-09-A's chart-annotation surface.

Per the parent `CLAUDE.md` "Spec-Before-Code Planning Discipline / Execution discipline" clause: "Touching a frozen enum value or an invariant requires a §15 amendment **first**, in a separate PR. No behaviour PR rides on an unamended invariant." This entry is that amendment-first PR; downstream SOS-09-D (Rust HAL emission) and SOS-09-E (HDL register-file RTL) implementation work dispatches against the amended twelve-key set.

**Spec amendments landing with this entry.**

- **§5.2 ten-key set → twelve-key set.** The permitted `sos:`-prefixed key set grows from ten to twelve with the addition of two new OPTIONAL channel-annotation keys:
  - **`sos:channel_group`** — SV identifier (string); names the Rust borrow scope / shared `RegisterBlock` boundary the channel belongs to (SOS-09-D consumer). Default-from-inheritance: when absent, inherits from the enclosing parallel/compound state's `sos:channel_group` declaration, or `"default"` if no ancestor declares. Inheritance walk is a consumer-side concern (SOS-09-D); the parser surfaces raw `Optional[str]`.
  - **`sos:privilege_region`** — SV identifier (string); names the HDL MPU privilege region / access-violation aggregation domain the channel belongs to (SOS-09-E consumer). Default-from-inheritance: when absent, inherits from the enclosing parallel/compound state's `sos:privilege_region` declaration, or `"default"` if no ancestor declares. Inheritance walk is a consumer-side concern (SOS-09-E); the parser surfaces raw `Optional[str]`.
  - Both keys are **OPTIONAL** on a channel; both keys MUST validate as SV identifiers per §5.4(7) when present (the same identifier shape that already governs `sos:name` — both will round-trip into emitted Rust module / HDL signal names downstream).
- **§5.4 validation rules.** Rule (7) implicitly extends to validate `sos:channel_group` and `sos:privilege_region` as SV identifiers when present. No new numbered rule is added; the existing SV-identifier validator already covers the new keys' value-shape requirement.
- **§9 frozen enumerations recap.** Key-set listing updated to enumerate the twelve keys.
- **Required-key count unchanged.** The four required keys remain `sos:id`, `sos:name`, `sos:kind`, `sos:dir`. The new keys are both OPTIONAL; absence triggers the inheritance walk (consumer-side).
- **Inheritance walk explicitly NOT implemented by the parser.** The parser (`tools/sos-codegen/sos09_annotations.py`) surfaces both keys as `Optional[str]`. The consumer (SOS-09-D for Rust borrow scope, SOS-09-E for HDL MPU region) walks the SCXML ancestor chain to resolve `None` to the inherited value (or `"default"` fallback). This split keeps the parser stateless and the inheritance semantic in one place per consumer.

**Implementing commits.**

- This commit (`SOS09A-AMEND: extend §5.2 to twelve-key set (PCDN-SOS-09-007 follow-on)`) — amends `docs/concepts/SOS-09-A-CONCEPTS.md` §5.2 / §9 and lands the parser + test extensions in `tools/sos-codegen/sos09_annotations.py` and `tools/sos-codegen/tests/test_sos09_annotations.py`.

**Cross-references.**

- Umbrella ratification: `SOS-09-CONCEPTS.md` §15.7 (dated 2026-05-26) — the originating ratification of PCDN-SOS-09-007.
- Spec-before-code discipline: parent `CLAUDE.md` "Execution discipline" — amendment-first PR pattern.
- Downstream consumers: SOS-09-D (Rust borrow scope / shared `RegisterBlock`), SOS-09-E (HDL MPU privilege region / access-violation aggregation). Both consumers walk inheritance on the parser-surfaced `Optional[str]`; neither re-implements key parsing.

Status: 🟢 **ratified**. The twelve-key set is now stable. SOS-09-D and SOS-09-E implementation work proceeds against the amended set.

### 2026-05-27 — §5.4(3) `sos:dir` vocabulary alignment with SOS-09 §5.2 (ERRATA-004) (Ira)

**Originating drift.** The SOS-09-W2N lint-amendment commit `4f33c1e` ("SOS01-09-W2N: §15 channel-annotation lint amendment") landed SCXML-LINT-CH-3 on SOS-01 §15, which quotes the `sos:dir` enum verbatim from [SOS-09 umbrella §5.2](./SOS-09-CONCEPTS.md#52-channel--membrane-primitive-mapping) — the arrow form `{hw→sw, sw→hw, hw↔sw}`. This authoring choice surfaced a pre-existing vocabulary drift inside the SOS-09 family: this doc's §5.4 rule (3) enumerated `sos:dir` as `{hw→sw, sw→hw, bidirectional}` (word form for the third value), while the umbrella §5.2 mapping table and §3 glossary both use the arrow form `{hw→sw, sw→hw, hw↔sw}`. Both enumerations carry three values; only the third differs (`hw↔sw` vs `bidirectional`). The drift is recorded under [ERRATA-004](./ERRATA.md#errata-004--sosdir-value-vocabulary-inconsistent-across-sos-09-family).

**Resolution.** [SOS-09 umbrella §5.2](./SOS-09-CONCEPTS.md#52-channel--membrane-primitive-mapping) is the canonical source for the `sos:dir` value vocabulary; this doc is the chart-authoring-facing restatement and MUST mirror the umbrella verbatim. The word `bidirectional` is hereby **retracted** as a synonym for `hw↔sw` and MUST NOT appear in chart-author-facing tooling, lint diagnostics, parser error messages, or downstream emitter contracts. SCXML-LINT-CH-3 (already landed in SOS-01 §15 per commit `4f33c1e`) is correct as authored; no SOS-01 amendment is owed.

**Spec amendment landing with this entry.** §5.4 validation rule (3) is amended to enumerate the `sos:dir` value vocabulary verbatim from SOS-09 §5.2:

> The `sos:dir` value MUST be one of `hw→sw` / `sw→hw` / `hw↔sw` (per [SOS-09 §5.2](./SOS-09-CONCEPTS.md#52-channel--membrane-primitive-mapping); the word `bidirectional` is retracted as a synonym per the 2026-05-27 ERRATA-004 amendment).

The other §5.4 rules are unchanged. The `sos:kind`, `sos:zone`, and `sos:atomicity` enums named in rule (3) are unaffected.

**Frozen-enumeration registration policy.** The `sos:dir` enum's mutation rights remain with the SOS-09 umbrella §5.2 (Standards Action per the umbrella's §5.2 registration-policy clause). This sub-phase's amendments to the surface-level restatement do NOT confer mutation rights; future changes to the value set ratify at the umbrella, not here.

**Cross-references.**

- ERRATA log entry: [ERRATA-004](./ERRATA.md#errata-004--sosdir-value-vocabulary-inconsistent-across-sos-09-family) — names the drift and pins it to commit `4f33c1e` as the discovery commit.
- Umbrella canonical source: [SOS-09 §5.2](./SOS-09-CONCEPTS.md#52-channel--membrane-primitive-mapping) — three-row mapping table whose dir-column values are the canonical `{hw→sw, sw→hw, hw↔sw}` enum.
- Umbrella §3 glossary entries for `queue channel` and `shared channel` — both use `dir="hw↔sw"`, corroborating §5.2 as canonical.
- SOS-01 §15 SCXML-LINT-CH-3 amendment (commit `4f33c1e`) — quotes the canonical arrow form; unaffected by this amendment.

Status: 🟢 **ratified**. The §5.4(3) enumeration now mirrors SOS-09 §5.2 verbatim; `bidirectional` is retracted as a synonym across the SOS-09-A surface.

### 2026-05-28 — ERRATA-004 follow-up: validator migration-window backstop removed (Ira)

**Closure of the migration window.** The 2026-05-27 ERRATA-004 amendment retracted `bidirectional` as a synonym for `hw↔sw` in the §5.4(3) chart-author-facing rule text. The validator implementation at `tools/sos-codegen/sos09_annotations.py` carved out a one-release migration window during which both spellings remained accepted in `ALLOWED_DIRS` and the `_KIND_DIR_MATRIX` rows for `queue` and `shared`, so dependent charts could complete their migration without a simultaneous validator-and-chart edit collision. That window has now closed.

**Chart-family migration landed.** SOS submodule commit `9682b35` ("ERRATA-004 sweep: bidirectional → hw↔sw across both chart families") migrated `charts/sis08_first_slice/sis08_first_slice.scxml` and `charts/sis08d_c2_membrane/sis08d_c2_membrane.scxml` to the canonical `hw↔sw` spelling. Both chart families' vector pytest suites pass against the narrowed validator (22/22 + 28/28 = 50/50).

**Validator narrowing landed with this entry.** `ALLOWED_DIRS` is now `frozenset({"hw→sw", "sw→hw", "hw↔sw"})`; `_KIND_DIR_MATRIX["queue"] = frozenset({"hw→sw", "sw→hw", "hw↔sw"})`; `_KIND_DIR_MATRIX["shared"] = frozenset({"hw↔sw"})`. The migration-window backstop is removed; `bidirectional` is now a hard `Sos09AnnotationError` at the validator layer with the §5.4(3) diagnostic `sos:dir value 'bidirectional' not in allowed set ['hw→sw', 'hw↔sw', 'sw→hw']`, mirroring §5.4(3) rule prose verbatim.

**Frozen-enumeration registration policy reaffirmed.** Re-introducing `bidirectional` as a synonym would now require a §15 amendment to SOS-09 umbrella §5.2 (Standards Action per the umbrella's registration-policy clause). This sub-phase carries no mutation rights for the `sos:dir` enum.

**Cross-references.**

- ERRATA-004 entry's 2026-05-28 closure subsection ("Chart-family migration + validator narrowing closure") — names the chart commit, the validator narrowing, and the downstream test-suite sweep that the closure unblocks.
- Chart-migration commit: `9682b35` (SOS submodule webslinger).
- Validator narrowing commit: this entry's landing commit.

Status: 🟢 **closed**. The §5.4(3) prose and the validator implementation are now fully aligned; the migration-window backstop is gone.

### 2026-05-28 — §15 amendment: `mmio-peripheral` placement value introduced (Path B per parent EOQ-002-ERRATA-002) (Ira)

**Originating finding.** The 2026-05-28 SIS-08D C2-D bench round on STM32H747I-DISCO (parent commit `817224f2`) surfaced that the C2-A chart manifest declared `placement: "sram-membrane"` with `baseAddress: 0x40010000`, but on STM32H747 silicon that address is the APB2 TIM1 advanced control timer base per RM0399 Table 8 — not SRAM. The chart's *semantic surface* (a shared region with command/status/transfer channels) is correct, but the *target access mechanism* is memory-mapped IO, not memory-backed SRAM. On a future FPGA-backed target the same membrane is realized as a custom-peripheral MMIO region; on STM32H747 the bench target lands the membrane in APB2 peripheral space. The "sram-membrane" tag was a placement-mechanism mislabel from a logical-layout decision that didn't account for the H747 physical memory map. The user ratified Path B in response to EOQ-002-ERRATA-002 (parent-side `docs/todo/streamz/statechart-orchestration/ERRATA.md`) on 2026-05-28 with the rationale: "MMIO to FPGA later is the whole point."

**Resolution — Standards Action amendment to the `placement` vocabulary.** The SOS-09-A spec previously did not enumerate `placement` values explicitly; the field was tag-only metadata set by individual chart emitters (`hardware-block` for SIS-08B `sis08_first_slice`; `sram-membrane` for SIS-08D C2-A `sis08d_c2_membrane`). This amendment introduces a third placement value — **`mmio-peripheral`** — naming the access-mechanism category for membranes whose target realization is a memory-mapped IO region (custom FPGA peripheral, MCU peripheral-bus space, or any access surface where the bus accesses the region as device memory with side-effecting reads/writes rather than as RAM). The `placement` field thus names the *access mechanism* on a target, not the *semantic surface* of the chart.

**Three placement values are now defined under SOS-09-A authority** (each future chart's emitter MUST declare exactly one):

- **`hardware-block`** — the membrane is realized as a discrete hardware block on the target (e.g., a synthesized HDL module accessed by name in the SOS-08 lowering pipeline). SIS-08B `sis08_first_slice` is the reference.
- **`sram-membrane`** — the membrane lives in a memory-backed SRAM region the bus accesses as RAM (no side-effecting reads/writes; aligned to the target's SRAM bank layout). Reserved for charts whose target has a real shared SRAM bank at the chosen base address; **C2-A no longer uses this value** under Path B.
- **`mmio-peripheral`** — the membrane lives in a memory-mapped IO region (peripheral-bus space on an MCU, custom-peripheral space on an FPGA-backed target). The bus accesses the region as device memory; reads/writes have target-defined side effects. SIS-08D C2-A is the reference.

**Registration policy.** **Standards Action per the SOS-09 umbrella's frozen-enumeration registration-policy clause** (inherited from `docs/concepts/SOS-09-CONCEPTS.md` §15 — Standards Action protects load-bearing vocabulary that crosses sub-phase boundaries). Adding a fourth placement value (e.g., a future `network-membrane` for remote-accessed surfaces) requires another §15 amendment to this doc. Demotion to Specification Required would require an umbrella §15 amendment first.

**Chart-side impact (C2-A only at amendment time):**

- `tools/sos-codegen/sis08d_c2_membrane.py` line 151: `"placement": "sram-membrane"` → `"placement": "mmio-peripheral"` (with a docstring citing this amendment + EOQ-002-ERRATA-002).
- `charts/sis08d_c2_membrane/sis08d_c2_membrane_manifest.json` line 72: regenerated by the emitter — new chartHash `sha256:75adb781...` (was `sha256:d64c2849...`).
- `charts/sis08d_c2_membrane/vectors/sis08d_c2_membrane/test_c2a_membrane_contract.py` line 330: assertion updated to `manifest["placement"] == "mmio-peripheral"`.
- The C2-A `.scxml` prose framing ("SRAM-membrane proof", channel name `SRAM_WINDOW`, etc.) is **unchanged** — it describes the chart's semantic surface (shared region with `kind=shared` channel + `mutex=sram_window_lock` atomicity), which is independent of the access-mechanism tag. The semantic intent stays the same; only the access-mechanism declaration shifts.

**SIS-08B impact: none.** `sis08_first_slice` continues to declare `placement: "hardware-block"`. The pre-existing value is unaffected by this amendment.

**Validator impact: none in this commit.** The SOS validator (`tools/sos-codegen/sos09_annotations.py`) currently does not enforce placement values — the field is tag-only metadata that chart emitters set without enum gating. A follow-on tick MAY tighten the validator to enforce the three-value enum, with the same Standards Action registration policy. This amendment establishes the spec-side vocabulary; validator enforcement is non-blocking.

**Verification.** Chart-family pytest pass after re-emit: 28/28 `sis08d_c2_membrane` (asserts `placement == "mmio-peripheral"`), 22/22 `sis08_first_slice` (asserts `placement == "hardware-block"` unchanged). The 2026-05-28 SIS-08D §16 entry on the parent side reciprocates this amendment with a status flip on ERRATA-002 from ⚪ (deviation pending ratification) to 🟢 (resolved per Path B).

**Cross-references.**

- Parent-side ERRATA-002 entry at `docs/todo/streamz/statechart-orchestration/ERRATA.md` — symptom, root cause, three-path resolution prescription, EOQ-002-ERRATA-002.
- Parent-side bench-round entry at `docs/todo/streamz/statechart-orchestration/TODO-SIS-08D-C2-IMPLEMENTATION-PLAN.md` §16, commit `817224f2` — the bench evidence that surfaced this.
- SIS-08D §16 (post-amendment) — records the Path B ratification and the SOS pin bump capturing this amendment.

Status: 🟢 **ratified**. The `placement` vocabulary is now a three-value enum under SOS-09-A Standards Action protection; the C2-A manifest re-declares to `mmio-peripheral` and reflects the chart's MMIO-to-FPGA access-mechanism intent.
