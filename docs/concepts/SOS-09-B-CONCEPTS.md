# SOS-09-B — CMSIS-SVD emission (primary register-map artifact)

**Status:** 🟢 **ratified 2026-05-25** — all five PCDNs walked; see §16 ratification entry.

## 0. Authority policy

This phase doc is the **CMSIS-SVD emission** sub-phase under the SOS-09 umbrella (`SOS-09-CONCEPTS.md`, ratified 2026-05-23, amended 2026-05-25 for PCDN-SOS-09-001). The umbrella's §5.5 freezes the artifact priority as **CMSIS-SVD primary, SystemRDL secondary**, and the umbrella's §6 names this sub-phase as the codegen path producing valid CMSIS-SVD XML from chart annotations. SOS-09-B takes the umbrella's frozen decisions as load-bearing input and produces the per-emission contract surface for the CMSIS-SVD artifact.

Per the parent CLAUDE.md "Spec-Before-Code Planning Discipline / Phase document shape":

- **Normative** sections of this doc: §3 glossary, §4 source-of-truth map, §5 frozen decisions, §7 cross-sub-phase invariants (INV-S-MEM-B-*), §8 standards integration matrix additions, §9 acceptance gates, §12 acceptance checklist.
- **Informative** sections: §1 purpose, §2 problem statement, §6 (intentionally N/A — see below), §10 reconciliation, §11 non-goals, §15 PCDNs (filed open), §16 change log.
- All keywords MUST, MUST NOT, SHALL, SHOULD, SHOULD NOT, MAY are interpreted per RFC 2119 / RFC 8174 when capitalised.

This doc cites `SOS-07-CONCEPTS.md` §6 for the cross-phase invariants INV-SOS-A through H and §7 for the AuthorityRelationship matrix; it does not re-derive them. It cites `SOS-09-CONCEPTS.md` §5 for the frozen channel enum, §5.2 for the channel → membrane-primitive mapping, §5.5 for the artifact priority, and §7 for the cross-sub-phase invariants INV-S-MEM-1 through 6.

Per PCDN-SOS-09-001 amended 2026-05-25, chart channel annotations are read from iState's `other_attributes` extension surface using `sos:`-prefixed string keys WITHIN the `other_attributes` JSON. This is a JSON-key string prefix, NOT an XML namespace prefix. SOS-09-B's emit path MUST honour this convention when reading the chart and MUST NOT emit any `xmlns:sos` declaration into the CMSIS-SVD output.

## 1. Purpose

To freeze the CMSIS-SVD XML emission contract: which CMSIS-SVD schema version SOS-09-B emits against, which downstream consumer's strictness mode is the conformance gate, the top-level XML structure (one `<device>` per chart), the per-channel `<register>` shape, the access-derivation rules from chart `sos:kind` + `sos:dir`, the bit-field emission policy, the IRQ-table emission policy, and the validation gate that distinguishes "syntactically valid SVD" from "SVD that downstream tooling actually consumes".

Without this freeze, the CMSIS-SVD emit path cannot produce a stable artifact: every emission would re-litigate which optional XML elements appear, which access values map to which chart `sos:kind` / `sos:dir` pairs, and which strictness mode the SVD is meant to pass. Downstream consumers (SOS-09-C C HAL, SOS-09-D Rust HAL, SOS-09-F membrane vectors) cannot author against an unstable SVD shape.

## 2. Problem statement

The umbrella's §2 names the "register-map PDF that lies" as the canonical hardware/software co-design failure mode and prescribes "derive every artifact from the chart annotation". CMSIS-SVD is the primary register-map artifact (per §5.5). Three concrete pressures inside the CMSIS-SVD emission path motivate this sub-phase's freeze:

1. **Schema-version drift.** CMSIS-SVD has evolved from 1.0 through 1.3.x with subtle changes to the `<modifiedWriteValues>`, `<readAction>`, and `<protection>` elements. An emitter that targets "current CMSIS-SVD" without pinning a version produces XML that consumers fail to parse at random. SOS-09-B MUST pin a single schema version per release.

2. **Downstream consumer strictness drift.** The CMSIS-SVD schema is permissive; downstream consumers are not. `svd2rust` in particular has a `--strict` mode that rejects SVD documents the schema accepts (e.g. registers with overlapping bit fields, registers with `addressOffset` past the peripheral's `<size>`). An SVD that passes `xmllint` and fails `svd2rust --strict` is a broken artifact for the SOS-09-D Rust HAL consumer. The conformance gate is the strict consumer, not the permissive schema.

3. **Access-mapping ambiguity from chart vocabulary.** Chart `sos:kind` + `sos:dir` annotations are SOS-semantic; CMSIS-SVD `<access>` is `read-only` / `write-only` / `read-write` / `writeOnce` / `read-writeOnce`. Without a fixed mapping rule, two emit-path implementations could disagree on whether a `kind="queue"` / `dir="hw↔sw"` channel emits `read-write` or two separate registers (read-only head + write-only tail). The mapping freeze is what makes the emission deterministic per INV-SOS-G.

## 3. Canonical glossary

Terms normative within SOS-09-B+. Authority relationships per §8.

| Term | Definition |
|---|---|
| **CMSIS-SVD** | The CMSIS System View Description schema, version 1.3.x. ARM-owned XML format for describing memory-mapped peripherals. As defined by ARM in the CMSIS-SVD specification; SOS-09-B emits conformant XML (relationship: `derive` per §8). |
| **SVD device** | The top-level `<device>` element of a CMSIS-SVD document. SOS-09-B emits one `<device>` per chart; multi-chart projects emit one SVD file per chart. |
| **SVD peripheral** | A `<peripheral>` element under `<device>/<peripherals>`. SOS-09-B emits one `<peripheral>` per chart-declared channel group; channels group by the chart-author-declared `sos:peripheral` attribute (default fallback: parent-state hierarchy, per PCDN-SOS-09-B-002). |
| **SVD register** | A `<register>` element under `<peripheral>/<registers>`. SOS-09-B emits one `<register>` per chart channel. |
| **SVD field** | A `<field>` element under `<register>/<fields>`. SOS-09-B emits one `<field>` per chart-declared semantic field on the channel (per umbrella PCDN-SOS-09-003 ratification: chart declares semantic fields, codegen assigns physical bits per target ABI). |
| **SVD access** | The `<access>` child of `<register>` (or `<field>`). One of `read-only` / `write-only` / `read-write` / `writeOnce` / `read-writeOnce`. SOS-09-B derives this from chart `sos:kind` + `sos:dir` per the §5.3 mapping table. |
| **modifiedWriteValues** | The CMSIS-SVD `<modifiedWriteValues>` child element of `<register>`, encoding side-effect-on-write semantics: `oneToClear`, `oneToSet`, `oneToToggle`, `zeroToClear`, `zeroToSet`, `zeroToToggle`, `clear`, `set`, `modify`. SOS-09-B emits this from chart-declared side-effect annotations (the specific annotation source is **PCDN-SOS-09-B-001**, recommended chart-attribute on the channel). |
| **readAction** | The CMSIS-SVD `<readAction>` child element, encoding clear-on-read / set-on-read / modify-on-read semantics. SOS-09-B emits this from chart-declared `sos:clear_on_read` (or equivalent) annotation. |
| **svd2rust strict mode** | The `svd2rust --strict` invocation mode that rejects SVD documents with overlapping fields, unaligned register offsets, or invalid access combinations. The SOS-09-B conformance gate (per §5.6 and INV-S-MEM-B-3). |
| **IRQ table** | The `<peripheral>/<interrupt>` block enumerating NVIC interrupts owned by the peripheral. Each entry has `<name>` and `<value>` (NVIC line number). SOS-09-B emits one entry per chart channel with `kind="status"` + `dir="hw→sw"` + `sos:irq=<name>`; the NVIC line number resolves via per-target table per umbrella PCDN-SOS-09-004 ratification. |
| **register-map artifact** | The on-disk CMSIS-SVD XML file produced by SOS-09-B. Lives under `build/` per INV-S-MEM-2; not tracked source. |

## 4. Source-of-truth map

| Concept | Authority |
|---|---|
| CMSIS-SVD schema (version, element vocabulary, attribute set) | ARM CMSIS-SVD 1.3.x XSD (external); locally **derive** per §8. |
| SVD schema version pin | **this doc** (§5.1). |
| Conformance gate consumer (svd2rust strict) | **this doc** (§5.6). |
| Top-level SVD structure (one `<device>` per chart) | **this doc** (§5.2). |
| Per-channel `<register>` shape | **this doc** (§5.3). |
| Access mapping (chart `sos:kind`+`sos:dir` → SVD `<access>`) | **this doc** (§5.3 mapping table, normative). |
| Side-effect mapping (chart annotation → `<modifiedWriteValues>`) | **this doc** (§5.4) **pending PCDN-SOS-09-B-001**. |
| Bit-field emission (semantic fields → physical bits per target ABI) | **this doc** (§5.5); mirrors umbrella PCDN-SOS-09-003 ratification. |
| IRQ-table emission policy | **this doc** (§5.5); mirrors umbrella PCDN-SOS-09-004 ratification. |
| Channel grouping into peripherals | **this doc** (§5.2) **pending PCDN-SOS-09-B-002**. |
| Address-offset assignment policy | **this doc** (§5.3) **pending PCDN-SOS-09-B-003**. |
| Validation gate (xmllint + svd2rust strict) | **this doc** (§5.6) **pending PCDN-SOS-09-B-004**. |
| SystemRDL secondary emission relationship | **this doc** (§10) **pending PCDN-SOS-09-B-005**. |
| Chart `other_attributes` annotation schema | `SOS-09-A-CONCEPTS.md` (when ratified); read per PCDN-SOS-09-001 amended 2026-05-25 (**mirror** consumption). |
| Channel category enum (`kind ∈ {status,command,queue,shared}`) | `SOS-09-CONCEPTS.md` §5.1 (**mirror**). |
| Channel → membrane-primitive mapping | `SOS-09-CONCEPTS.md` §5.2 (**mirror**). |
| Cross-sub-phase invariants INV-S-MEM-1 through 6 | `SOS-09-CONCEPTS.md` §7 (cited, not redefined). |
| Cross-phase invariants INV-SOS-A through H | `SOS-07-CONCEPTS.md` §6 (cited, not redefined). |
| Per-channel SVD register XML emitted artifact | `build/svd/<chart_id>.svd` (forthcoming; this doc owns the path convention). |
| SVD validator wrapper script | `tools/sos-codegen/svd_validate.py` (forthcoming). |

## 5. Frozen decisions

### 5.1 SVD schema version pin

**CMSIS-SVD 1.3.x** is the emitted schema version. The minor-version `x` accepts the latest publicly-available patch of CMSIS-SVD 1.3 at SOS-09-B implementation time, provided it passes the conformance gate of §5.6. Future schema migrations (1.4, 2.0) require a §16 amendment to this doc and a re-validation of every downstream consumer in §8.

The XML preamble emitted by SOS-09-B SHALL begin:

```xml
<?xml version="1.0" encoding="utf-8"?>
<device schemaVersion="1.3" xmlns:xs="http://www.w3.org/2001/XMLSchema-instance"
        xs:noNamespaceSchemaLocation="CMSIS-SVD.xsd">
  ...
</device>
```

Frozen-enumeration registration policy: **Standards Action** (schema-version pin encodes a downstream-consumer contract).

### 5.2 Top-level structure

One `<device>` element per chart. The `<device>` carries:

- `<name>` — the chart's `chart_id` (sanitized to CMSIS-SVD's `xs:Name` pattern: alphanumeric + underscore, leading letter).
- `<version>` — the chart's content-hash, truncated to 12 hex chars, prefixed `c` (e.g. `c1a2b3c4d5e6`).
- `<description>` — chart's `<sos:description>` if present, else a fallback `"SOS-09-B generated from chart <chart_id>"`.
- `<addressUnitBits>` — `8` (byte-addressed; CMSIS-SVD canonical).
- `<width>` — the chart-default register width per `sos:width` umbrella default (32).
- `<peripherals>` — one or more `<peripheral>` children.

One `<peripheral>` per **channel group**. A channel group is one of:

1. **Explicit grouping** — channels sharing a chart-author-declared `sos:peripheral="<name>"` attribute.
2. **Implicit grouping** — channels under a common parent state (per PCDN-SOS-09-B-002, the v1 default fallback when `sos:peripheral` is absent).

Each `<peripheral>` carries `<name>`, `<baseAddress>` (assigned per-target by the emitter), `<addressBlock>`, `<registers>`, and optionally `<interrupt>` blocks (§5.5).

Frozen-enumeration registration policy: **Standards Action** for the top-level structural skeleton; **Specification Required** for the grouping fallback rule (subject to PCDN-SOS-09-B-002 refinement).

### 5.3 Per-register emission

One `<register>` per SOS-09 channel. Each `<register>` carries:

- **`<name>`** — sanitized `sos:id` (the chart's stable channel identifier).
- **`<description>`** — chart-declared `<sos:description>` if present; else fallback.
- **`<addressOffset>`** — auto-assigned by the emitter. The chart declares semantic offset ordering via the order of channels within the parent state / `sos:peripheral` group; the target ABI dictates the physical offset (PCDN-SOS-09-B-003 governs dense vs spaced policy). The default emission policy is **dense, no padding, 4-byte-aligned for 32-bit registers, 8-byte-aligned for 64-bit registers**.
- **`<size>`** — derived from `sos:width` (default 32).
- **`<access>`** — derived from chart `sos:kind` + `sos:dir` per the following normative mapping:

  | chart `sos:kind` | chart `sos:dir` | SVD `<access>` |
  |---|---|---|
  | `status` | `hw→sw` | `read-only` |
  | `command` | `sw→hw` | `write-only` |
  | `queue` | `hw↔sw` (bidirectional) | `read-write` |
  | `shared` | `hw↔sw` (bidirectional) | `read-write` |

  At v1, there is **no chart-author override** for the access mapping — the chart's `sos:kind` + `sos:dir` determines `<access>` deterministically. INV-S-MEM-B-2 enforces this.

- **`<resetValue>`** — chart-declared reset value (typically `0x00000000` unless overridden by `sos:reset_value`).
- **`<resetMask>`** — `0xFFFFFFFF` for full-width registers (all bits affected by reset); narrower for partial-width registers per `sos:width`.
- **`<modifiedWriteValues>`** — emitted when the chart declares a side effect on write (the annotation source is PCDN-SOS-09-B-001; the mapping from chart side-effect tag to SVD value is normative below).
- **`<readAction>`** — emitted when the chart declares a side effect on read (e.g. `sos:clear_on_read="true"` → `<readAction>clear</readAction>`).
- **`<fields>`** — one or more `<field>` children (§5.5).

**Side-effect → modifiedWriteValues normative mapping** (per PCDN-SOS-09-B-001 recommendation):

| chart side-effect annotation | SVD `<modifiedWriteValues>` value |
|---|---|
| `sos:side_effect="clear"` | `clear` |
| `sos:side_effect="set"` | `set` |
| `sos:side_effect="toggle"` | `modify` (CMSIS-SVD has no atomic-toggle value; chart-declared toggle composes as modify) |
| `sos:side_effect="oneToClear"` | `oneToClear` |
| `sos:side_effect="zeroToClear"` | `zeroToClear` |
| `sos:side_effect="oneToSet"` | `oneToSet` |
| `sos:side_effect="zeroToSet"` | `zeroToSet` |
| `sos:side_effect="modify"` | `modify` |

Frozen-enumeration registration policy: **Standards Action** (the access-mapping table encodes the cross-phase contract surface; modifying it would silently retarget SOS-09-C and SOS-09-D consumers).

### 5.4 Side-effect-on-write annotation source

Per PCDN-SOS-09-B-001 recommendation: side-effect annotations live as **chart attributes on the channel element**, attached via the host element's `other_attributes` JSON with the `sos:side_effect="<value>"` key. The value is one of the eight strings enumerated in the §5.3 mapping table.

The alternative considered — chart sub-element `<sos:side_effect>` — is rejected at v1 for two reasons: (a) `other_attributes` already carries the other channel metadata per PCDN-SOS-09-001 amended 2026-05-25, so a sub-element would split the channel's metadata across two surfaces, and (b) side-effects are per-register-write properties, not per-register sub-objects, so attribute is the natural shape.

PCDN-SOS-09-B-001 is filed open (§15) pending walkthrough; the recommended resolution is reflected in §5.3's mapping table.

Frozen-enumeration registration policy: **Specification Required** (the attribute-vs-element shape is local to this sub-phase's contract surface; if PCDN walkthrough rejects the attribute form, this rule re-ratifies as a sub-element form).

### 5.5 Bit-field and IRQ-table emission

**Bit fields.** Per umbrella PCDN-SOS-09-003 (ratified 2026-05-23): the chart declares **semantic fields** (each with a name, description, and access); the emitter assigns **physical bits** per target ABI. Each `<register>` contains a `<fields>` block with one `<field>` per semantic field. Each `<field>` carries:

- `<name>` — sanitized chart-declared field name.
- `<description>` — chart-declared description.
- `<lsb>` and `<msb>` — physical bit positions assigned by the emitter per target ABI; together they define the bit range.
- `<access>` — defaults to the parent `<register>`'s `<access>`; overrideable by chart-declared `sos:field_access` per-field annotation.

Reserved bits read-as-zero / write-as-zero per default ARMv7-M discipline (per umbrella PCDN-SOS-09-003). SOS-09-B does NOT emit `<field>` entries for reserved bit ranges; the gaps in `<lsb>`/`<msb>` coverage carry the reserved semantic implicitly. (This matches the canonical CMSIS-SVD idiom — explicit reserved fields are optional.)

**IRQ table.** Per umbrella PCDN-SOS-09-004 (ratified 2026-05-23): each chart channel with `sos:kind="status"` + `sos:dir="hw→sw"` + `sos:irq="<logical_name>"` contributes one `<interrupt>` entry to the enclosing `<peripheral>`. The entry carries:

- `<name>` — the chart's logical IRQ name.
- `<description>` — chart-declared description.
- `<value>` — the physical NVIC line number, resolved via the per-target IRQ-mapping table (lives alongside the linker-script + `memory.x` artifacts in the SOS-04 / SOS-05 per-port surface).

A chart channel without `sos:irq` does NOT contribute an `<interrupt>` entry (channels MAY be status-bearing without owning an NVIC line — e.g. polled-only status channels).

Frozen-enumeration registration policy: **Standards Action** (both bit-field policy and IRQ-table policy mirror umbrella ratifications).

### 5.6 Validation gate

Every SVD document SOS-09-B emits MUST pass:

1. **`xmllint --schema CMSIS-SVD.xsd <file>.svd`** — XML schema conformance against the pinned CMSIS-SVD 1.3.x XSD (the XSD ships with the build wrapper under `tools/sos-codegen/schemas/CMSIS-SVD-1.3.xsd`).
2. **`svd2rust --strict --input <file>.svd`** — strict-mode round-trip through the canonical Rust HAL consumer. Failure of the strict mode is a build failure, not a warning.

The validation gate is enforced in the SOS-09-B emit step (per INV-S-MEM-B-3). PCDN-SOS-09-B-004 governs whether strict mode is forced unconditionally or opt-in during early bring-up; the recommended resolution (forced strict default; opt-out flag for chart-author convenience during early bring-up) is reflected here.

The cocotb-harness gate (per SOS-08-D-style emission) consumes the validated SVD and round-trips it through the SOS-09-F membrane vector framework; a chart that emits SVD passing both gates above AND the cocotb harness is the conformance triple.

Frozen-enumeration registration policy: **Specification Required** (validator versions move; the gate-shape is normative but specific tool versions are operational, not normative).

## 6. Sub-phase scope (intentionally N/A)

SOS-09-B is a **leaf sub-phase** under the SOS-09 umbrella; it has no further sub-phases of its own. The umbrella's §6 SOS-09-B row IS the informative summary; this doc IS the normative artifact. No §6 enumeration is required.

This section is preserved (marked N/A) for shape-consistency with the precedent SOS-08-A doc layout, where §6 is the per-primitive contract table. SOS-09-B has no analogous enumeration of sub-units; the emission contract is fully specified by §5.

## 7. Cross-sub-phase invariants — INV-S-MEM-B-1 through 6

In addition to the cross-phase invariants INV-SOS-A through H (from SOS-07) and the SOS-09 cross-sub-phase invariants INV-S-MEM-1 through 6 (from SOS-09 §7), the following invariants are normative within SOS-09-B:

- **INV-S-MEM-B-1 — Every chart channel surfaces in exactly one `<register>`.** Every chart channel annotation that satisfies the umbrella §5.2 channel → membrane-primitive mapping MUST surface as exactly one `<register>` element in the emitted SVD. No channel is dropped; no channel is duplicated. Channels that fail SOS-01 lint (missing `kind`, missing `dir`, unmappable pair) are not emitted but the codegen MUST fail with a chart authoring error rather than silently skip.

- **INV-S-MEM-B-2 — SVD `<access>` is deterministic from chart `sos:kind` + `sos:dir`.** The §5.3 mapping table is the only path from chart vocabulary to SVD `<access>`. There is no chart-author override at v1. Two emit runs on the same chart against the same target produce identical `<access>` values bit-for-bit. (Subsumed by the stricter INV-S-MEM-B-4 below; restated here for emphasis on the access surface specifically.)

- **INV-S-MEM-B-3 — SVD documents pass the validation gate as a release condition.** Every SVD artifact under `build/svd/` MUST pass `xmllint --schema` and `svd2rust --strict` (per §5.6). The SOS-08-D-style cocotb harness consumes the validated SVD; a chart whose SVD fails the gate cannot ratify SOS-09-B's acceptance gate (§9).

- **INV-S-MEM-B-4 — Emission is deterministic per (chart, target).** Same chart + same target IRQ table + same target ABI → identical SVD bit-for-bit. This mirrors INV-SOS-G (verified-codegen position) at the SVD artifact level: emission is a pure function of (chart, target). Non-determinism (timestamps in XML comments, ordering of map iteration, etc.) is prohibited.

- **INV-S-MEM-B-5 — Side-effect declarations round-trip through SVD.** A chart-declared side effect (per §5.4) MUST emit the corresponding `<modifiedWriteValues>` (or `<readAction>`) element on the target `<register>`. The SOS-09-F membrane-vector framework reads the emitted SVD and discharges the side-effect vector against the chart-declared annotation; round-trip mismatches between chart and SVD are caught at the vector stage.

- **INV-S-MEM-B-6 — IRQ entries are append-only per peripheral.** Within a single `<peripheral>` block, `<interrupt>` entries appear in chart-declaration order (the order channels with `sos:irq` annotations appear in the chart). Reordering IRQ entries across chart edits (e.g. inserting a new channel between two existing IRQ-carrying channels) MUST NOT renumber the NVIC values of existing channels — the NVIC values come from the per-target table (umbrella PCDN-SOS-09-004), and the table is the renumbering authority. SVD-level ordering is documentary; NVIC numbering is target-level.

## 8. Standards integration matrix additions

This sub-phase EXTENDS the SOS-09 §8 matrix (which already declared CMSIS-SVD 1.3.x and `svd2rust` as `derive`). SOS-09-B uses those rows without modification AND adds the following SOS-09-B-specific clarifications:

| Concept | Upstream authority | Local relationship | Phase that declares it | Mutation rights |
|---|---|---|---|---|
| CMSIS-SVD 1.3.x XSD | ARM (CMSIS) | **derive** — SOS-09-B emits XML conforming to the pinned 1.3.x XSD; schema migration to 1.4 / 2.0 requires §16 amendment | this doc | none — schema is upstream |
| `svd2rust --strict` mode | open project (Rust embedded WG) | **derive** — SOS-09-B's emitted SVD MUST pass strict mode; SOS-09-D consumes the SVD via `svd2rust` | this doc | none — strict-mode behaviour is upstream |
| `xmllint` schema validator | open project (libxml2) | **derive** — SOS-09-B's validation gate uses `xmllint --schema`; libxml2 owns the validator | this doc | none |
| SOS-09 chart `other_attributes` annotation schema | iState project + SOS-09-A | **mirror** — SOS-09-B reads `sos:`-prefixed keys per PCDN-SOS-09-001 amended 2026-05-25; SOS-09-A owns the schema | this doc | SOS-09-A owns; SOS-09-B consumes |
| SOS-09 umbrella §5.1 channel-kind enum (`{status, command, queue, shared}`) | `SOS-09-CONCEPTS.md` §5.1 | **mirror** — SOS-09-B consumes the enum as the access-mapping table key (§5.3); the enum's frozen-enumeration policy (Standards Action) carries through | this doc | none |
| SOS-09 umbrella §5.2 channel → membrane-primitive mapping | `SOS-09-CONCEPTS.md` §5.2 | **mirror** — SOS-09-B's channel-presence-in-SVD is gated by the umbrella's mapping (a channel that doesn't satisfy a row is rejected by SOS-01 lint upstream) | this doc | none |

Per INV-SOS-E, the row addition policy mirrors SOS-07 §7 and SOS-09 §8: **Specification Required** for adding new rows (phase-owner walkthrough); **Standards Action** for modifying an existing row's relationship value.

## 9. Acceptance gates (cocotb harness scope)

The SOS-09-B emit path's acceptance gates are:

- (a) **Schema validation gate** — Every SVD artifact `build/svd/<chart_id>.svd` passes `xmllint --schema tools/sos-codegen/schemas/CMSIS-SVD-1.3.xsd <file>.svd` with exit 0.
- (b) **Strict-consumer gate** — Every SVD artifact passes `svd2rust --strict --input <file>.svd --output-dir <tmp>` with exit 0 and the generated Rust crate compiles under `cargo check --target thumbv7em-none-eabihf` (the SOS-08 PCDN-006 target).
- (c) **Round-trip determinism gate** — Two consecutive emit runs on the same (chart, target) produce byte-identical SVD output (no timestamps, no environment-dependent metadata, no map-iteration-order variance).
- (d) **Coverage gate** — Every chart channel declared in the chart's `other_attributes` with valid `sos:kind` + `sos:dir` surfaces as exactly one `<register>`; the count matches.
- (e) **Side-effect round-trip gate** — For every chart channel with a `sos:side_effect="<value>"` annotation, the emitted SVD `<register>` has the corresponding `<modifiedWriteValues>` (or `<readAction>` for `sos:clear_on_read`) child element with the §5.4 normative mapping.
- (f) **IRQ-table coverage gate** — For every chart channel with `sos:kind="status"` + `sos:dir="hw→sw"` + `sos:irq`, the emitted SVD `<peripheral>/<interrupt>` block carries an entry with name/value matching the chart annotation + per-target NVIC table.

A conforming SOS-09-B implementation satisfies (a)–(f). A conforming implementation without (e) and (f) — i.e. charts with no side-effect or IRQ-bearing channels — satisfies a reduced (a)–(d) conformance level.

## 10. Reconciliation decisions vs adjacent repo primitives

### vs. existing `tools/sos-codegen/` test fixtures

Search at draft time: **no `.svd` files** exist under `tools/sos-codegen/` (verified by `find tools/sos-codegen -name "*.svd"`). The fixture directory `tools/sos-codegen/tests/fixtures/` contains only `.scxml` and `.json` chart fixtures, no register-map artifacts. Therefore, there are no pre-existing hand-rolled SVD test vectors to reconcile against; SOS-09-B's chart-driven emission is the sole authority for SVD artifacts in this repo when the emit path lands.

Should future work want to validate the SOS-09-B emitter against externally-authored SVDs (e.g. STM32H747's vendor-published SVD as a structural reference), the externally-authored SVDs SHOULD live under `tools/sos-codegen/tests/fixtures/external_svd/` with a `README.md` declaring their provenance and the relationship axis (per SOS-07 §7 AuthorityRelationship) of `mirror` (read-only, not modified) — they would not be normative inputs to the emitter, only test references.

### vs. SOS-09-A (chart annotation surface)

SOS-09-B **consumes** SOS-09-A's annotation schema. The four-attribute set `sos:kind`, `sos:dir`, `sos:mutex`, `sos:protection-zone` ratified at the umbrella level (per PCDN-SOS-09-001 amended 2026-05-25) is read from `other_attributes` JSON. SOS-09-B does NOT extend the attribute set; new SOS-semantic keys are SOS-09-A's authority. The SOS-09-B-specific reads are: `sos:id`, `sos:kind`, `sos:dir`, `sos:width`, `sos:reset_value`, `sos:reset_mask`, `sos:irq`, `sos:side_effect`, `sos:clear_on_read`, `sos:peripheral`, `sos:field_access`. Of these, the channel-classifying triplet (`sos:id`, `sos:kind`, `sos:dir`) is umbrella-frozen; the rest are SOS-09-B-specific and subject to PCDN-SOS-09-B-001 / -002 walkthrough resolution.

### vs. SOS-09-C / SOS-09-D (C HAL and Rust HAL emission)

SOS-09-B is **upstream** of SOS-09-C and SOS-09-D. Both downstream sub-phases consume the validated SVD as their input contract. The C HAL emitter derives struct overlay layouts from the SVD `<peripheral>/<registers>/<addressOffset>` chain; the Rust HAL emitter uses `svd2rust` directly against the validated SVD. SOS-09-B's strict-consumer gate (§5.6 / INV-S-MEM-B-3) is what makes the downstream emit paths viable; without it, the C / Rust paths would be authoring against an underspecified SVD.

### vs. SOS-09-E (HDL register-file RTL)

SOS-09-E composes SOS-08-A primitives to realise the HW-side register-file RTL; SOS-09-B emits the documentary artifact that describes the same register file from the SW-side viewpoint. Both paths derive from the same chart channel set per INV-S-MEM-1 (single-source register definition). The address-offset assignment policy frozen here (§5.3, subject to PCDN-SOS-09-B-003) is the same policy SOS-09-E MUST observe when emitting the bus-decode logic — both sides see the same `<addressOffset>` values. INV-S-MEM-B-4 (deterministic per (chart, target)) is the property that makes this symmetric.

### vs. SOS-09-F (membrane vectors)

SOS-09-F's vector framework reads the SOS-09-B-emitted SVD to enumerate the register set under test. The six vector shapes (initial-value-read, write-then-read, side-effect-on-write, clear-on-read, atomicity, protection) consume the corresponding SVD elements: `<resetValue>`, `<access>`, `<modifiedWriteValues>`, `<readAction>`, the access mapping, and (for protection) `<peripheral>/<protection>` if the umbrella PCDN-SOS-09-006 protection-zone enumeration extends to require it. INV-S-MEM-B-5 (side-effect round-trip) is the property SOS-09-F's side-effect vector exercises.

### vs. PCDN-SOS-09-001 amended 2026-05-25

The amendment that routes channel annotations through `other_attributes` (vs the originally-resolved `xmlns:sos` namespace) is a load-bearing input to SOS-09-B's read path. SOS-09-B MUST NOT emit any `xmlns:sos` declaration into the CMSIS-SVD output (the SVD output carries the `xmlns:xs` schema-instance declaration per CMSIS-SVD canonical, not a SOS-specific namespace). SOS-09-B MUST read `sos:`-prefixed keys from `other_attributes` JSON; reading from XML namespace prefixes would be reading a surface that PCDN-SOS-09-001 amended 2026-05-25 explicitly retracted.

### vs. SystemRDL secondary emission (deferred)

Per umbrella §5.5: CMSIS-SVD is primary; SystemRDL is secondary. PCDN-SOS-09-B-005 asks whether SystemRDL emission is tracked here (folded into B as an emit option) or as a future sibling sub-phase. Recommendation: future sibling sub-phase (potentially `SOS-09-B2-SYSTEMRDL-CONCEPTS.md` or similar). The CMSIS-SVD path's complexity is enough on its own; conflating SystemRDL emission into B would dilute the conformance gate to whichever-format-is-loosest. Defer SystemRDL to its own sub-phase when a non-Cortex-M target enters the SOS bench substrate.

## 11. Non-goals

This sub-phase does NOT:

- **Author SystemRDL emission.** Per umbrella §5.5, SystemRDL is secondary; per PCDN-SOS-09-B-005 recommendation, SystemRDL emission is a future sibling sub-phase. SOS-09-B authors CMSIS-SVD only.
- **Author the C HAL emission.** That's SOS-09-C, which CONSUMES the SVD emitted here.
- **Author the Rust HAL emission.** That's SOS-09-D, which CONSUMES the SVD emitted here (via `svd2rust` strict mode per §5.6).
- **Author the HDL register-file RTL.** That's SOS-09-E. SOS-09-B emits the documentary register map; SOS-09-E emits the bus-decode logic.
- **Author membrane-vector emission.** That's SOS-09-F. SOS-09-B emits the SVD; SOS-09-F consumes it.
- **Author MPU table emission.** That's SOS-09-G. SOS-09-B emits documentary access bits in `<access>` elements; SOS-09-G emits the runtime MPU configuration.
- **Define a custom register-map format.** CMSIS-SVD 1.3.x IS the format. SOS-09-B emits against the upstream schema; no custom extension to the SVD vocabulary is introduced.
- **Register an XML namespace URL.** Per PCDN-SOS-09-001 amended 2026-05-25, NO `xmlns:sos` URL is registered or claimed; the `sos:` prefix on chart-side keys is a JSON-key string prefix, not an XML namespace prefix. The SVD output carries the CMSIS-SVD canonical XML schema-instance declaration ONLY.
- **Verify HDL metastability.** Per INV-S-HDL-3 (from SOS-08 §7), `sos_synchronizer` flops are excluded from formal verification; MTBF handles that path. SOS-09-B's documentary `<access>` mapping does not imply timing claims.

## 12. Acceptance checklist

A conforming SOS-09-B ratification satisfies:

- (a) ⏸ PCDN-SOS-09-B-001 through 005 resolved (§15).
- (b) ⏸ At least one chart channel emits a `<register>` element that passes the §9 (a) schema validation gate.
- (c) ⏸ The emitted SVD passes the §9 (b) `svd2rust --strict` gate against the SOS-08 PCDN-006 thumbv7em target.
- (d) ⏸ Round-trip determinism (§9 (c)) verified across two emit runs.
- (e) ⏸ Coverage (§9 (d)) verified: chart channel count = SVD `<register>` element count.
- (f) ⏸ Side-effect round-trip (§9 (e)) verified for at least one channel per `<modifiedWriteValues>` value (the eight rows of §5.3 mapping).
- (g) ⏸ IRQ-table (§9 (f)) verified for at least one channel with `sos:irq` annotation.
- (h) ⏸ Cross-sub-phase invariants INV-S-MEM-B-1 through 6 cited correctly in the SOS-09-B emit-path source.
- (i) ⏸ Cross-phase invariants INV-SOS-A through H cited per (a typically via `@spec` comment block referencing this doc + SOS-07 + SOS-09).
- (j) ⏸ SOS-09 umbrella INV-S-MEM-1 through 6 satisfied (the SVD is a build output per INV-S-MEM-2; single-source per INV-S-MEM-1; determinism per INV-SOS-G mirrors here as INV-S-MEM-B-4).

(a) is the ratification gate; (b)–(j) are implementation gates that flip from ⏸ to ✅ as the implementation lands.

A conforming SOS-09-B *without side-effect-bearing or IRQ-bearing channels* (i.e. charts consisting only of plain status/command/queue/shared channels) satisfies (a)–(e) and (h)–(j) with reduced (f) and (g). This second-tier conformance level supports first-target ECP5 bring-up demos that exercise only the plain register surface, deferring side-effect and IRQ coverage to subsequent bring-up rounds.

## 13. Files cited

| Path | Role |
|---|---|
| `docs/concepts/SOS-09-CONCEPTS.md` | Umbrella; this sub-phase's parent. |
| `docs/concepts/SOS-07-CONCEPTS.md` | Cross-phase invariants INV-SOS-A through H; AuthorityRelationship matrix. Cited, not redefined. |
| `docs/concepts/SOS-09-A-CONCEPTS.md` | Chart annotation surface; SOS-09-B consumes this when ratified. |
| `docs/concepts/SOS-09-C-CONCEPTS.md` | C HAL emission; downstream of SOS-09-B. |
| `docs/concepts/SOS-09-D-CONCEPTS.md` | Rust HAL emission; downstream of SOS-09-B via `svd2rust`. |
| `docs/concepts/SOS-09-E-CONCEPTS.md` | HDL register-file RTL; companion to SOS-09-B (same chart input, different output target). |
| `docs/concepts/SOS-09-F-CONCEPTS.md` | Membrane vectors; consumes SOS-09-B's SVD. |
| `docs/concepts/SOS-09-G-CONCEPTS.md` | MPU configuration emission; companion. |
| `docs/concepts/SOS-08-A-CONCEPTS.md` | Precedent shape for per-sub-phase concept doc layout. |
| `tools/sos-codegen/transliterate_svd.py` | Codegen tool; SOS-09-B emit path. Landed `b0b69c7` (SOS09B1) — see §16 2026-05-27 entry for the rename from the original `svd_emit.py` forecast (ERRATA-001). |
| `tools/sos-codegen/schemas/CMSIS-SVD-1.3.xsd` | 🟡 deferred — pinned CMSIS-SVD 1.3.x XSD (not yet bundled; §5.6 validation gate cites this path but no XSD has shipped). See ERRATA-001. |
| `tools/sos-codegen/svd_validate.py` | 🟡 deferred — validation gate wrapper (not yet authored; §5.6 / §9 (a) (b) cite this path but no wrapper has shipped). See ERRATA-001. |
| `build/svd/<chart_id>.svd` | Emitted SVD artifact (forthcoming; per INV-S-MEM-2 lives under `build/`, not tracked source). |
| Parent `CLAUDE.md` | Spec-Before-Code Planning Discipline; Phase document shape. |

## 14. Unblocks

This sub-phase's ratification (after PCDN walkthrough) unblocks:

- **SOS-09-C** (C HAL emission) — depends on the SVD shape frozen here as its struct overlay source.
- **SOS-09-D** (Rust HAL emission) — depends on the SVD passing `svd2rust --strict` per §5.6.
- **SOS-09-F** (membrane vectors) — depends on the SVD being the enumeration source for the per-register vector emission.
- **SOS-09-E** (HDL register-file RTL) — depends on the address-offset assignment policy (§5.3, PCDN-SOS-09-B-003) being the same between SVD and bus-decode logic.
- The "PDF cannot lie because the PDF is generated" claim made concrete as a CMSIS-SVD artifact that downstream Cortex-M debugging tools (Keil, STM32CubeIDE, OpenOCD, `probe-rs`) consume directly.

## 15. Pending Concept Decision Notices (PCDNs)

These open questions move this doc from 🟡 drafted to 🟢 ratified. PCDN-SOS-09-B-* identifiers are stable per parent CLAUDE.md "Errata Open Question" naming convention (analogous shape applies — these are PCDNs at the concepts-doc level).

- **PCDN-SOS-09-B-001 — Side-effect annotation source: chart-attribute or chart-element?** 🟢 **ratified 2026-05-25 — see §16 ratification entry below.** Options: (a) chart-attribute on the channel via `other_attributes` JSON with key `sos:side_effect="<value>"`; (b) chart sub-element `<sos:side_effect>...</sos:side_effect>` (would require expanding SOS-08-D / -E-style element vocabulary into SOS-09 territory). **Recommendation**: option (a) chart-attribute on the channel. Side-effects are per-register-write properties (atomic with the register's other metadata); `other_attributes` already carries the channel metadata per PCDN-SOS-09-001 amended 2026-05-25; splitting metadata across attribute + element surfaces increases convention sprawl. The §5.4 emission table reflects this recommendation.

- **PCDN-SOS-09-B-002 — Peripheral grouping: chart hint or auto-grouping?** 🟢 **ratified 2026-05-25 — see §16 ratification entry below.** Options: (a) chart hint via `sos:peripheral="<name>"` attribute takes precedence; auto-grouping by parent-state hierarchy is the fallback when the attribute is absent; (b) auto-grouping is the only path; chart-author cannot override; (c) chart hint is the only path; chart-author MUST declare `sos:peripheral` on every channel. **Recommendation**: option (a) — hint-takes-precedence with hierarchy fallback. Gives chart authors control where they want it, sensible defaults where they don't. Forces no extra annotation burden on the common case.

- **PCDN-SOS-09-B-003 — Address-offset assignment policy: dense or spaced?** 🟢 **ratified 2026-05-25 — see §16 ratification entry below.** Options: (a) dense (no padding between registers, 4-byte-aligned for 32-bit, 8-byte-aligned for 64-bit) at v1; alignment opt-in via per-target ABI table for targets requiring stricter alignment; (b) spaced 8-byte (every register on an 8-byte boundary regardless of width) — wastes address space but eases ABI compatibility across targets; (c) spaced 16-byte / 32-byte for cache-line alignment on targets with caches. **Recommendation**: option (a) dense at v1 with per-target alignment opt-in. ECP5 first-target has no cache; the SOS-04 / SOS-05 Cortex-M7 disco-analyzer substrate's MPU regions are coarse enough that register-level cache-line alignment is overkill. The opt-in table preserves the option to spaced/larger alignment without forcing it on the common case.

- **PCDN-SOS-09-B-004 — `svd2rust --strict` mode opt-in policy.** 🟢 **ratified 2026-05-25 — see §16 ratification entry below.** Options: (a) forced strict at all times (the strict gate is unconditional, no chart-author override); (b) strict default with per-chart `sos:svd2rust_strict="false"` opt-out for early bring-up; (c) opt-in (strict is off by default; chart-author must enable). **Recommendation**: option (b) — strict default with explicit opt-out. The strict gate is the load-bearing consumer-contract enforcement (per INV-S-MEM-B-3), so it MUST be on for production charts; an opt-out flag for early bring-up keeps the iteration loop fast when the chart has known-incomplete annotations. The opt-out flag carries a build warning naming the channels skipping strict validation.

- **PCDN-SOS-09-B-005 — SystemRDL secondary emission: track here or future sibling sub-phase?** 🟢 **ratified 2026-05-25 — see §16 ratification entry below.** Options: (a) future sibling sub-phase (e.g. `SOS-09-B2-SYSTEMRDL-CONCEPTS.md`) when a non-Cortex-M target enters the SOS bench substrate; (b) fold into SOS-09-B as a per-chart `sos:emit_systemrdl="true"` opt-in flag; (c) emit both unconditionally on every SOS-09-B run. **Recommendation**: option (a) future sibling sub-phase. The CMSIS-SVD path's complexity is sufficient on its own; conflating SystemRDL into B would dilute the conformance gate (strictness mode differs between consumers); and the SystemRDL consumer ecosystem (verilog-rdlc, OpenTitan's `peakrdl`) is non-Cortex-M-focused, so the trigger to add it is bench-substrate expansion, not SOS-09-B's first-target ratification.

## 16. Change log

### 2026-05-25 — Initial draft (Ira)

- Authored `SOS-09-B-CONCEPTS.md` as the CMSIS-SVD emission sub-phase under the SOS-09 umbrella.
- §3 canonical glossary: terms `CMSIS-SVD`, `SVD device`, `SVD peripheral`, `SVD register`, `SVD field`, `SVD access`, `modifiedWriteValues`, `readAction`, `svd2rust strict mode`, `IRQ table`, `register-map artifact`.
- §4 source-of-truth map: SVD schema pin, top-level structure, per-register shape, access mapping table, side-effect mapping, bit-field policy, IRQ-table policy, validation gate, grouping policy, address-offset policy, validation-gate policy.
- §5 frozen decisions: CMSIS-SVD 1.3.x schema pin (§5.1); top-level `<device>` per chart + `<peripheral>` per channel group (§5.2); per-register `<register>` shape with access mapping derived from chart `sos:kind` + `sos:dir` (§5.3 normative table); side-effect mapping table (§5.4); bit-field + IRQ-table emission (§5.5); validation gate `xmllint --schema` + `svd2rust --strict` (§5.6).
- §6 N/A (leaf sub-phase; the umbrella's §6 SOS-09-B row IS the informative summary; this doc IS the normative artifact).
- §7 cross-sub-phase invariants INV-S-MEM-B-1 through 6: every chart channel surfaces in one register; SVD access deterministic from chart kind/dir; validation gate as release condition; emission deterministic per (chart, target); side-effect round-trip; IRQ entries append-only per peripheral.
- §8 standards integration matrix additions: CMSIS-SVD 1.3.x XSD, `svd2rust --strict`, `xmllint`, SOS-09-A annotation schema (mirror), SOS-09 umbrella §5.1 / §5.2 (mirror).
- §9 acceptance gates (a)–(f) for the SOS-08-D-style cocotb harness scope.
- §10 reconciliation vs existing fixtures (none found), SOS-09-A annotation surface, SOS-09-C/D/E/F sub-phases, PCDN-SOS-09-001 amendment, SystemRDL secondary.
- §11 non-goals: no SystemRDL, no HAL emission, no HDL RTL, no vectors, no MPU, no custom format, no namespace URL registration.
- §12 acceptance checklist gates (a)–(j) with reduced conformance level for charts without side-effect or IRQ-bearing channels.
- §15 five PCDNs raised covering side-effect annotation source, peripheral grouping, address-offset policy, strict-mode opt-in, SystemRDL emission scope.

Status: 🟡 **drafted**, awaiting PCDN walkthrough.

### 2026-05-25 — Ratified (Ira)

All five PCDNs walked and resolved cleanly in a ratification session 2026-05-25. Each ratification accepted the §15 recommendation as-is — no amendment language was required.

| PCDN | Resolution | Registration policy |
|---|---|---|
| **PCDN-SOS-09-B-001 — Side-effect annotation source** | ✅ Option (a) — chart-attribute via `other_attributes` JSON with key `sos:side_effect="<value>"`. The §5.3 / §5.4 emission tables already reflect this resolution. | Standards Action |
| **PCDN-SOS-09-B-002 — Peripheral grouping** | ✅ Option (a) — chart hint `sos:peripheral="<name>"` takes precedence; auto-grouping by parent-state hierarchy is the fallback when the attribute is absent. | Standards Action |
| **PCDN-SOS-09-B-003 — Address-offset assignment policy** | ✅ Option (a) — dense at v1: no padding between registers, 4-byte-aligned for 32-bit registers, 8-byte-aligned for 64-bit registers. Per-target ABI table opt-in for stricter alignment. | Standards Action |
| **PCDN-SOS-09-B-004 — `svd2rust --strict` mode opt-in policy** | ✅ Option (b) — strict default with per-chart `sos:svd2rust_strict="false"` opt-out. Opt-out emits a build warning naming the channels skipping strict validation. | Specification Required |
| **PCDN-SOS-09-B-005 — SystemRDL secondary emission scope** | ✅ Option (a) — future sibling sub-phase (e.g. `SOS-09-B2-SYSTEMRDL-CONCEPTS.md`) when a non-Cortex-M target enters the SOS bench substrate. SOS-09-B at v1 authors CMSIS-SVD only. | Specification Required |

**No spec amendments required** beyond the PCDN status markers in §15. Every recommendation in the original §15 was ratified as-is; the §5 frozen-decisions surface (schema pin, top-level structure, per-register emission, side-effect mapping, bit-field/IRQ-table emission, validation gate) is unchanged. The §15 entries now carry 🟢 ratified markers; the recommendation language inside each PCDN body is preserved as institutional context.

Status: 🟢 **ratified**. SOS-09-B's CMSIS-SVD emission contract is stable. Downstream sub-phases (SOS-09-C C HAL, SOS-09-D Rust HAL, SOS-09-E HDL register-file RTL, SOS-09-F membrane vectors, SOS-09-G MPU configuration) MAY proceed against the frozen SVD shape. Implementation of `tools/sos-codegen/svd_emit.py` is unblocked.

### 2026-05-27 — Implementation-cite reconciliation (ERRATA-001)

The 2026-05-25 ratification forecast §13's emit-path file as `tools/sos-codegen/svd_emit.py`. The SOS09B1 implementation (commit `b0b69c7`, "SOS09B1: implement CMSIS-SVD emitter (SOS-09-B foundation)") shipped as `tools/sos-codegen/transliterate_svd.py` to align with the sibling family convention (`transliterate_c.py`, `transliterate_rust.py`, `transliterate_hdl_*.py`, `transliterate_cocotb.py`). The rename was not recorded in §16 at landing time; this entry reconciles the cite.

§13 amendment (this entry):

- Row `tools/sos-codegen/svd_emit.py (forthcoming)` → `tools/sos-codegen/transliterate_svd.py` (landed `b0b69c7`).
- Rows `tools/sos-codegen/svd_validate.py` and `tools/sos-codegen/schemas/CMSIS-SVD-1.3.xsd` re-annotated as 🟡 deferred — neither has landed. The §5.6 validation gate ("`xmllint --schema CMSIS-SVD.xsd <file>.svd`" plus "`svd2rust --strict --input <file>.svd`") and the §9 (a) (b) acceptance gates that cite these paths remain spec-only until the deferred follow-ups land. Public emit surface is unaffected — `transliterate_svd.py` produces conformant CMSIS-SVD 1.3 XML; only the in-tree gate wrapper is missing.

No §5 frozen decision changes. No invariant amendment. The §5.6 validation gate's wire-level contract (`xmllint` + `svd2rust --strict`) remains normative; the bundling of the XSD and the convenience wrapper script are deferred operational surface, not a spec retraction.

Cross-cite: `docs/concepts/ERRATA.md` ERRATA-001 cross-cites this entry.
