# SOS-09 — Hardware/software membrane (register handoff + protection)

**Status:** 🟢 **ratified 2026-05-23**. All 6 PCDNs walked; resolutions recorded in §15.

## 0. Authority policy

This phase doc ratifies the contract for the **hardware/software membrane**: the boundary between a software side (C/Rust on a CPU) and a hardware side (FPGA fabric or ASIC) where, by industry default, a register-map PDF is the integration contract — and where, by industry default, that PDF drifts. SOS-09 inverts the failure mode: the register map is a *build output* derived from chart annotations, not a documentation file maintained alongside drift-prone code.

Per the Spec-Before-Code Planning Discipline (parent CLAUDE.md):

- **Normative** sections of this doc: §3 glossary, §4 source-of-truth map, §5 frozen decisions, §6 sub-phase scope, §7 cross-sub-phase invariants, §8 standards integration matrix additions, §12 acceptance checklist.
- **Informative** sections: §1 purpose, §2 problem statement, §11 non-goals, §15 change log.

All keywords MUST, MUST NOT, SHALL, SHOULD, SHOULD NOT, MAY are interpreted per RFC 2119 / RFC 8174 when capitalised.

This doc cites `SOS-07-CONCEPTS.md` §6 for the cross-phase invariants INV-SOS-A through H and §7 for the AuthorityRelationship matrix; it does not re-derive them. It cites `SOS-08-CONCEPTS.md` §6 for the L0 primitive library and §7 for the SOS-08 cross-sub-phase invariants (INV-S-HDL-1 through 5); it does not re-derive those either.

## 1. Purpose

To take the bench-validated Statechart Orchestration System methodology (`CanonicalReplacement` verdict on both M7 ports per `SOS-06-CONCEPTS.md` §5.2 (d)) and the synthesizable HDL backend (`SOS-08-CONCEPTS.md`) and apply them to the surface that historically eats the most engineering time per square millimeter of silicon: the **register-map membrane** between firmware and fabric.

The unlock SOS-09 makes concrete: when a chart declares a hardware/software channel, the codegen emits the software-side accessor, the hardware-side register-file RTL, the register-map artifact (CMSIS-SVD primary; SystemRDL secondary), and the membrane vectors that test the read/write pairing across the boundary — all from one source, all consistent by construction.

## 2. Problem statement

The "register-map PDF that lies" is the canonical hardware/software co-design failure mode. The shape:

1. **Tape-out plus six months.** The driver team has tweaked the firmware to work around silicon erratum E1; the RTL team has tweaked the silicon to work around firmware erratum F1; the register-map PDF is wrong on both sides. Nobody noticed until the next bring-up team tried to write against the PDF.

2. **The register map is the contract.** Drivers consume it; verification testbenches consume it; debug tools consume it. When the PDF lies, every downstream artifact is wrong in the same way.

3. **Source-of-truth is a doc maintained out-of-band.** The Word/PDF file lives next to the code rather than upstream of it. Nothing in the build catches a drift; nothing in CI fails on a divergence between firmware constants and silicon register decode.

4. **Every co-design team re-derives the same primitives.** Status registers, command registers, IRQ-on-change, ring buffers in DPRAM, mutex-protected shared regions. The vocabulary is universal; the implementation is hand-rolled per project; the bugs are project-local restatements of bugs solved twenty times elsewhere.

5. **Protection adds another spec axis.** Per-register MPU configuration, per-register secure-zone gating, per-register privilege levels — these live in yet another doc (or, more commonly, in a tangle of `#define`s no human has audited end-to-end).

SOS-09 makes all five symptoms the same symptom of one disease — the absence of a build pipeline rooted in a single chart-level spec — and prescribes one cure: derive every artifact (SW accessor, HW RTL, register-map XML, MPU table, vector suite) from the chart annotation. The PDF cannot lie because the PDF is generated. The driver cannot mismatch the silicon because both come from the same chart edit. The membrane vectors cannot become stale because they are emitted at the same build step as the artifacts they verify.

Per INV-SOS-A (chart-as-source), this is the only sustainable position; per INV-SOS-B (vectors-as-deliverable), the membrane vectors are the integration contract; per INV-SOS-H (vector-to-chart traceability), every failure renders in chart vocabulary.

## 3. Canonical glossary

Terms normative within SOS-09+. Authority relationships per §8.

| Term | Definition |
|---|---|
| **membrane** | The boundary between a software side (CPU running C or Rust) and a hardware side (FPGA fabric or ASIC). The membrane carries status (HW → SW), commands (SW → HW), queues (bidirectional), and shared mutable state (mutex-protected). SOS-09 is the contract for how the chart declares membrane traffic and how the emitter realises it. |
| **channel** | A typed flow of information across the membrane. Declared as a chart annotation; realised as the four-tuple `{SW accessor, HW RTL, register-map entry, membrane vectors}`. Channel category is one of `{status, command, queue, shared}` (the frozen enum of §5.1). |
| **channel category** | One of `status` / `command` / `queue` / `shared`. Each maps to a fixed membrane-primitive realisation (§5.2). |
| **status channel** | `kind="status" dir="hw→sw"`. HW writes; SW reads. Realised as a HW output register + `sos_strobe_latch` (SOS-08-A §6) producing an IRQ on change. |
| **command channel** | `kind="command" dir="sw→hw"`. SW writes; HW reads + acts. Realised as a HW input register + req/ack handshake (bare; no FIFO). |
| **queue channel** | `kind="queue" dir="hw↔sw"`. Bidirectional message stream. Realised as `sos_dpram_arb` + `sos_message_channel` (SOS-08-A / B) with an IRQ on non-empty. |
| **shared channel** | `kind="shared" dir="hw↔sw"`. Mutex-protected typed region. Realised as `sos_mutex` (SOS-08-A) over a `sos_dpram_arb` region; atomicity guaranteed by the mutex. |
| **register-map artifact** | The on-disk register-map description in a vendor-neutral standard format. Primary: CMSIS-SVD XML. Secondary: SystemRDL. Both emitted from the same chart annotation; both treated as build outputs, not tracked source. |
| **membrane vector** | A vector (per SOS-03 / SOS-08-D vocabulary) that exercises a single register's read/write pairing across the boundary. The set of membrane vectors for a chart is the integration contract per INV-SOS-B. |
| **protection zone** | A per-channel access-control declaration: which CPU privilege level (privileged / unprivileged), which security zone (per PCDN-SOS-09-006), and which MPU region may read/write each register. The chart declares; the emitter realises across MPU configuration, register-decode logic, and the register-map artifact's access bits. |
| **atomicity class** | A per-register declaration of read-modify-write semantics: `atomic` (single-register, hardware-guaranteed) or `mutex-required` (multi-register state machine; requires `sos_mutex` protection). Inferred from `kind` by default; overridable per PCDN-SOS-09-002. |
| **side-effect-on-write** | A register property: writing the register triggers a HW action beyond the value update (clear an IRQ pending bit, fire a command, swap a buffer). Declared in the chart; emitted as a synthesizable HW side-effect output + a SW HAL annotation that the access must be a full-register write. |
| **clear-on-read** | A register property: reading the register clears it (or clears specific bits). Declared in the chart; emitted as HW decode + a SW HAL annotation that the access is destructive. |

## 4. Source-of-truth map

| Concept | Authority |
|---|---|
| Channel-annotation chart-attribute set | **this doc** (§5.1 frozen enum; §6 sub-phase scope) |
| Channel → membrane-primitive mapping | **this doc** (§5.2); cited primitives ratify in SOS-08-A |
| Atomicity class semantics | **this doc** (§5.3) |
| Protection zone enumeration | **this doc** (§5.4) pending PCDN-SOS-09-006 |
| CMSIS-SVD synthesizable subset | ARM CMSIS-SVD 1.3.x schema (external); locally **derived** per §8 |
| SystemRDL synthesizable subset | Accellera SystemRDL 2.0 (external); locally **derived** per §8 |
| C HAL header emission shape | **this doc** (§6 SOS-09-C); aligned with svd2rust C-bindings idiom |
| Rust HAL trait shape | **this doc** (§6 SOS-09-D); aligned with svd2rust + chiptool RegisterBlock idiom |
| HDL register-file RTL | **this doc** (§6 SOS-09-E); composed of SOS-08-A primitives + new `sos_regfile` template |
| Membrane vector framework | **this doc** (§6 SOS-09-F); extends SOS-03 / SOS-08-D vector emission |
| MPU configuration tables | **this doc** (§6 SOS-09-G); aligned with ARMv7-M MPU per SOS-00 §6 |
| Cross-sub-phase invariants | **this doc** (§7) |
| Cross-phase invariants INV-SOS-A through H | `SOS-07-CONCEPTS.md` §6 (referenced, not redefined) |
| SOS-08 cross-sub-phase invariants INV-S-HDL-1 through 5 | `SOS-08-CONCEPTS.md` §7 (referenced, not redefined) |
| L0 primitive contracts | `SOS-08-CONCEPTS.md` §6 SOS-08-A (referenced, not redefined) |
| L1 service composition | `SOS-08-CONCEPTS.md` §6 SOS-08-B (referenced, not redefined) |

## 5. Frozen decisions

### 5.1 Channel-category enumeration

A chart channel annotation declares a channel via iState's `other_attributes` extension surface (per PCDN-SOS-09-001 amended resolution; see §15 2026-05-25 entry); the SOS-semantic keys use the `sos:` string prefix within the `other_attributes` JSON (e.g. `{"sos:kind": "status", "sos:dir": "hw→sw"}`). `kind` is one of the four values:

```
kind ∈ { status, command, queue, shared }
```

This enumeration is frozen. Adding a fifth category requires a §15 amendment and cross-phase review.

Frozen-enumeration registration policy: **Standards Action** (per parent CLAUDE.md; the enum encodes the membrane's complete vocabulary, so amendments need cross-phase consensus).

### 5.2 Channel → membrane-primitive mapping

The mapping between a channel category and its realisation is frozen:

| Chart annotation (`kind` / `dir`) | SW accessor | HW RTL | Membrane primitive (SOS-08-A) |
|---|---|---|---|
| `status` / `hw→sw` | RO register + IRQ-on-change | HW output register + strobe | `sos_strobe_latch` |
| `command` / `sw→hw` | WO register; write triggers HW action | HW input register + req/ack | bare req/ack (no SOS-08-A primitive needed beyond `sos_synchronizer` for clock crossing) |
| `queue` / `hw↔sw` | DPRAM ring buffer + IRQ on non-empty | DMA descriptor + IRQ strobe | `sos_dpram_arb` + `sos_message_channel` |
| `shared` / `hw↔sw` | Typed atomic region behind `with_lock(|state| ...)` HAL idiom | `sos_mutex` over a `sos_dpram_arb` region | `sos_mutex` |

The mapping is exhaustive: a chart channel annotation that does not fit one of the four rows is a chart authoring error caught by SOS-01 lint (extension lands at SOS-01 §15 amendment when this phase ratifies).

Frozen-enumeration registration policy: **Standards Action** for the mapping rows (adding a fifth row or rewiring an existing row both require cross-phase amendment).

### 5.3 Atomicity class semantics

A register's atomicity class is one of:

```
atomicity ∈ { atomic, mutex-required }
```

- **`atomic`** — single-register read, or single-register write with at-most-one side effect, hardware-guaranteed by single-cycle bus access. The compiler emits no software synchronisation.
- **`mutex-required`** — multi-register state machine transitions, or composite state where reads of register A imply consistent reads of register B. The compiler emits `sos_mutex` claim/release around the access on both sides of the membrane.

Default inference rule (subject to PCDN-SOS-09-002): channels of `kind="status"` / `kind="command"` default to `atomic`; channels of `kind="queue"` default to `atomic` per individual head/tail register (with the queue protocol itself supplying multi-register consistency); channels of `kind="shared"` default to `mutex-required`.

Frozen-enumeration registration policy: **Standards Action**.

### 5.4 Protection-zone enumeration (subject to PCDN-SOS-09-006)

v1 enumeration:

```
zone ∈ { privileged, unprivileged }
```

This pair matches the ARMv7-M MPU's privilege axis (per SOS-00 §6). Per PCDN-SOS-09-006, the enumeration MAY extend to a four-zone TrustZone-style model `{ secure-privileged, secure-unprivileged, non-secure-privileged, non-secure-unprivileged }`; the v1 enumeration is the strict subset usable on every ARMv7-M target including the SOS bench substrate (the disco-analyzer board, per SOS-00 §6).

Frozen-enumeration registration policy: **Standards Action**.

### 5.5 Register-map artifact priority

Per EOQ-005-ROADMAP resolution: **CMSIS-SVD primary** (widest tool ecosystem; every Cortex-M debug tool consumes SVD; `svd2rust` / `chiptool` already in the Rust ecosystem; matches v1 Cortex-M target per SOS-07 §7). **SystemRDL secondary** (non-Cortex-M targets; semantically richer register designs). Custom JSON declined.

Both artifacts emit from the same chart annotation; both are build outputs in `build/`, not tracked source. The CMSIS-SVD is canonical for downstream consumers on Cortex-M targets; the SystemRDL is canonical for non-Cortex-M and for any consumer needing the richer semantic surface (e.g. register-array indexed access patterns).

Frozen-enumeration registration policy: **Specification Required** (adding a tertiary format — IP-XACT, vendor-specific — is a phase-owner walkthrough update, not a §15 amendment).

## 6. Sub-phase scope (informative summary; each sub-phase ratifies in its own doc)

### SOS-09-A — Chart annotation surface

The chart-annotation attribute schema for SOS-09 channels, attached to existing iState/SCXML elements via the `other_attributes` extension surface (per PCDN-SOS-09-001 amended resolution; see §15 2026-05-25 entry). Allowed parent contexts (`<region>`, `<state>`, `<parallel>`). Permitted SOS-semantic keys (each prefixed `sos:` inside the `other_attributes` JSON): `sos:id` (required, unique within chart), `sos:kind` (required, per §5.1), `sos:dir` (required, per the kind/dir pairs of §5.2), `sos:zone` (optional, default `privileged`; per §5.4), `sos:atomicity` (optional, default inferred per §5.3), `sos:width` (optional, default 32; the register width in bits), `sos:bit_layout` (optional reference to a layout block elsewhere in the chart).

PCDN-SOS-09-001 was originally resolved 2026-05-23 in favour of a custom XML namespace; that resolution was retracted and re-ratified 2026-05-25 in favour of the `other_attributes` extension surface. The `sos:` prefix on attribute keys is a STRING prefix WITHIN the `other_attributes` JSON, NOT an XML namespace prefix — no `xmlns:sos` declaration is registered or expected in chart-author-facing XML for SOS-09 channel annotations.

Ratifies as `SOS-09-A-CONCEPTS.md`.

### SOS-09-B — CMSIS-SVD emission (primary)

The codegen path producing valid CMSIS-SVD XML from the chart annotations. Schema: CMSIS-SVD 1.3.x. Emission scope: per-channel register entries; per-register access type (`read-only` / `write-only` / `read-write`); per-register side-effect modeling via `<modifiedWriteValues>` (clear / set / toggle); IRQ table from `kind="status"` channels with `dir="hw→sw"` and SOS-09 `irq` annotation.

Authority relationship: **derive** (per SOS-07 §7 row; SOS-09 emits valid SVD, ARM owns the schema). Membrane vectors test the SVD by round-tripping through `svd2rust` (Rust HAL emission is one of the consumers, so the SVD must satisfy `svd2rust`'s schema strictness).

Ratifies as `SOS-09-B-CONCEPTS.md`.

### SOS-09-C — C HAL header emission

The codegen path producing C accessor headers. Form: `#define` constants for register addresses; struct overlays for typed access with `volatile` qualifiers on every field; per-register accessor macros that respect the chart-declared side-effect semantics (e.g. a `clear-on-read` register's SW macro is named `*_consume_*` rather than `*_read_*` to make the destructiveness syntactically visible).

The struct overlay layout is derived from the CMSIS-SVD emission (SOS-09-B is upstream). The headers compile under `-Wall -Wextra -Wpedantic -std=c11`.

Ratifies as `SOS-09-C-CONCEPTS.md`.

### SOS-09-D — Rust HAL trait emission

The codegen path producing Rust HAL traits aligned with the svd2rust / chiptool RegisterBlock idiom. A `RegisterBlock` struct provides typed access; per-register newtype wrappers carry the chart-declared semantics in the type system (e.g. a `ClearOnRead<u32>` wrapper whose `read` method consumes `self`, making double-read a compile error).

Per INV-SOS-G, registers proven by chart-bounds analysis to be in a known state can emit `*_unchecked` accessors with a comment naming the discharging invariant.

Ratifies as `SOS-09-D-CONCEPTS.md`.

### SOS-09-E — HDL register-file RTL

The codegen path producing synthesizable VHDL-2008 + SystemVerilog-2017 register-file RTL. Composes SOS-08-A primitives:

- `status` channels → output register + `sos_strobe_latch`.
- `command` channels → input register + req/ack (bare; `sos_synchronizer` if cross-domain).
- `queue` channels → `sos_dpram_arb` instance + `sos_message_channel` wrapper.
- `shared` channels → `sos_dpram_arb` + `sos_mutex` instance.

A new template module `sos_regfile` (introduced by this sub-phase) wraps the per-channel realisations behind a single AXI4-Lite (or APB at user option) bus interface. Per INV-S-HDL-1, every interface is handshake-compatible.

Per INV-S-MEM-3 (§7 of this doc), every register decode line that gates a side-effect MUST gate exactly the chart-declared zone(s); cross-zone access generates a `sos_strobe_latch`-driven access-violation event back to the SW side.

Ratifies as `SOS-09-E-CONCEPTS.md`.

### SOS-09-F — Membrane vectors

Extension of the SOS-03 vector framework (per SOS-03 §15 amendment co-landing) and the SOS-08-D cocotb framework for HDL targets. For every chart-declared register, the membrane vector suite tests:

1. **Initial-value read** — read the register; assert the chart-declared reset value.
2. **Write-then-read** — write a value (constrained to the field-width and any chart-declared legal-value set); read; assert the value matches (modulo declared side effects).
3. **Side-effect-on-write** — write a value; assert the chart-declared HW-side action fired (visible via a status register, an IRQ count, or a queue depth change).
4. **Clear-on-read** — read; assert chart-declared bits cleared; assert second read returns the cleared value.
5. **Atomicity** — under chart-declared concurrent producers (HW and SW writing simultaneously where the chart permits), assert no torn read; for `mutex-required` registers, assert mutex serialises access.
6. **Protection** — write from a non-permitted zone; assert the access is rejected and the SW side sees the chart-declared exception path fire.

Per INV-SOS-H, every vector failure renders in chart vocabulary: *"channel `auth.command` in protection zone `privileged` rejected an unprivileged write from chart state `init.unauthed.attempt`"*.

Per PCDN-SOS-09-005, the v1 co-simulation framework is **cocotb-with-Python-CPU-stub** (the cocotb test drives both the SW side as a Python stub model of register writes/reads and the HW side as instantiated RTL). Cycle-accurate ISS integration (linking a real Cortex-M ISS into the cocotb test) is deferred indefinitely as its own potential future sub-phase.

Ratifies as `SOS-09-F-CONCEPTS.md`.

### SOS-09-G — MPU configuration emission

The codegen path producing the ARMv7-M MPU configuration tables from chart-declared protection zones. Output: a C array of MPU region descriptors and a Rust constant of the same; both consumed at startup by the SW-side runtime to install per-channel access control.

Per PCDN-SOS-09-006, v1 scope is the ARMv7-M MPU privileged/unprivileged axis. TrustZone (Cortex-M33 / M55 / M85) is a future extension when those targets enter the SOS bench substrate.

Ratifies as `SOS-09-G-CONCEPTS.md`.

## 7. Cross-sub-phase invariants — INV-S-MEM-1 through 6

In addition to the cross-phase invariants INV-SOS-A through H (from SOS-07) and the SOS-08 cross-sub-phase invariants INV-S-HDL-1 through 5, the following invariants are normative across SOS-09's sub-phases:

- **INV-S-MEM-1 — Single-source register definition.** Every register that appears in any SOS-09 artifact (CMSIS-SVD XML, SystemRDL XML, C HAL header, Rust HAL trait, HDL register-file RTL, MPU table, membrane vector) MUST originate from a single chart annotation. Hand-edits to any emitted artifact are prohibited by process and rejected by build (the codegen tool refuses to emit if a tracked artifact in the source tree is detected outside `build/`).

- **INV-S-MEM-2 — Register-map artifact is a build output.** The CMSIS-SVD XML and SystemRDL XML SHALL live under `build/` (or equivalent generated-artifact tree), not in tracked source. Per INV-SOS-A (chart-as-source), the chart is canonical; the artifacts are derived.

- **INV-S-MEM-3 — Protection is end-to-end.** A chart-declared protection zone on a channel MUST be enforced on BOTH sides: the SW side via MPU configuration (SOS-09-G), the HW side via register-decode logic (SOS-09-E). A protection-zone declaration MUST NOT emit one side without the other; the codegen rejects the chart if asked to.

- **INV-S-MEM-4 — Side-effect declarations are mandatory for non-trivial writes.** A register whose write triggers any HW action beyond the value update MUST declare the side effect in the chart. The codegen emits the side-effect wiring on the HW side AND the access-discipline annotation on the SW side. Undeclared side effects are a chart authoring error caught by SOS-01 lint.

- **INV-S-MEM-5 — Atomicity claims are auditable.** Every register declared `atomicity="atomic"` MUST be a single hardware register that can be read or written in a single bus cycle (a chart-level assertion enforced by SOS-09-E's decode-logic emission). Every register declared `atomicity="mutex-required"` MUST have the mutex region declared in the chart and instantiated by SOS-09-E. The verification proof obligation is the chart-bounds analysis; runtime checks MAY be elided per INV-SOS-G with citation.

- **INV-S-MEM-6 — Membrane vectors are part of the integration contract.** Per INV-SOS-B, the membrane vectors emitted by SOS-09-F ship with the IP as the integration contract. A downstream consumer of the SOS-09 register-file RTL gets the vector suite alongside; running the vectors against the consumer's instantiation IS the integration test. Per INV-SOS-H, vector failures cite the chart state/transition/invariant.

## 8. Standards integration matrix additions

The following rows EXTEND the SOS-07 §7 matrix:

| Concept | Upstream authority | Local relationship | Phase that declares it | Mutation rights |
|---|---|---|---|---|
| CMSIS-SVD 1.3.x schema | ARM (vendor-neutral; CMSIS) | **derive** (emit conformant XML; primary register-map format) | SOS-09-B | none — schema is upstream |
| SystemRDL 2.0 | Accellera | **derive** (emit conformant XML; secondary register-map format) | SOS-09-B | none — schema is upstream |
| svd2rust | open project (Rust embedded WG) | **derive** (consumes SVD; SOS-09-D emission is svd2rust-style by convention) | SOS-09-D | none — svd2rust idiom is upstream |
| chiptool | open project | **derive** (alternative SVD consumer; SOS-09-D may target either) | SOS-09-D | same |
| ARMv7-M MPU (per SOS-00 §6) | local distillation from ARM ARM | **mirror** (SOS-09-G uses the SOS-00 §6 subset) | SOS-09-G | none — SOS-00 §6 IS the local authority |
| AXI4-Lite (per SOS-09-E bus interface) | AMBA (ARM, vendor-neutral) | **derive** (emit conformant slave interface) | SOS-09-E | none — bus spec is upstream |
| APB (alternative bus interface) | AMBA | **derive** | SOS-09-E | same |
| iState `other_attributes` extension surface (per PCDN-SOS-09-001 amended 2026-05-25) | iState project | **compose** (SOS-09 attaches channel-annotation keys with `sos:` string prefix inside the `other_attributes` JSON; iState owns the surface) | SOS-09-A | iState owns the extension surface; SOS preserves via scjson round-trip per INV-SOS-D |
| SOS-09 channel-annotation key convention (`sos:`-prefixed keys inside `other_attributes`) | this doc | **own** (SOS authors the key-prefix convention and the four-attribute set `kind` / `dir` / `mutex` / `protection-zone`) | SOS-09-A | SOS owns; NO XML namespace URL is registered — the `sos:` prefix is a JSON-key string prefix, not an XML namespace prefix |

Per INV-SOS-E, the row addition policy is the same as SOS-07 §7: **Specification Required** for adding new rows (phase-owner walkthrough), **Standards Action** for modifying an existing row's relationship value.

## 9. Frozen enumerations recap

This phase freezes the following enumerations (each declared in §5 with its registration policy):

- §5.1 Channel category — `{ status, command, queue, shared }` — **Standards Action**.
- §5.2 Channel → membrane-primitive mapping (the four rows) — **Standards Action**.
- §5.3 Atomicity class — `{ atomic, mutex-required }` — **Standards Action**.
- §5.4 Protection zone — `{ privileged, unprivileged }` (v1; PCDN-SOS-09-006 may extend) — **Standards Action**.
- §5.5 Register-map artifact priority — CMSIS-SVD primary, SystemRDL secondary — **Specification Required**.

Plus:

- §7 Cross-sub-phase invariants — `{ INV-S-MEM-1, INV-S-MEM-2, INV-S-MEM-3, INV-S-MEM-4, INV-S-MEM-5, INV-S-MEM-6 }` — **Standards Action**.

## 10. Reconciliation decisions vs adjacent repo primitives

### vs. SOS-08-A (L0 primitive library)

SOS-09 **composes** SOS-08-A primitives; it does not introduce a new primitive layer. The four channel-category realisations (§5.2) map to existing primitives. The one new template module — `sos_regfile`, the per-channel realisation wrapped behind a bus interface — is a *composition template*, not a primitive; it lives in the SOS-09-E sub-phase output, not in SOS-08-A's primitive catalogue.

### vs. SOS-08-B (L1 service composition)

`sos_message_channel` (SOS-08-B) is the realisation of `kind="queue"` channels. No re-derivation; SOS-09 picks the existing service.

### vs. SOS-04 (M7 Rust port) and SOS-05 (M7 C port)

The SW-side accessors emitted by SOS-09-C / SOS-09-D are *compatible with* but do not *replace* the existing SOS-04 / SOS-05 register-access patterns (e.g. `cortex-m`'s `Peripherals::steal()`, direct volatile access via `core::ptr::read_volatile`). SOS-04's existing pattern is `mirror` against the upstream `cortex-m` crate; SOS-09's emission is `derive` from a chart annotation. The two coexist: SOS-04's pattern owns CPU-internal peripheral access (NVIC, SCB, SysTick, MPU configuration registers themselves); SOS-09's emission owns chart-declared external membrane access.

A SOS-04 §15 amendment co-lands when SOS-09 ratifies, recording the boundary: SOS-09 emissions are layered atop SOS-04's runtime; they do not redefine it.

### vs. SOS-03 (vector framework)

SOS-09-F is a vector-shape extension. SOS-03 §15 amendment co-lands when SOS-09-F ratifies, adding the six membrane-vector shapes (initial-value-read, write-then-read, side-effect, clear-on-read, atomicity, protection) to the framework's catalog. The vector IR (per SOS-08-D PCDN-008 resolution) is reused without modification.

### vs. INV-SOS-A (chart-as-source)

INV-S-MEM-1 (single-source register definition) is the membrane-scoped specialisation of INV-SOS-A. INV-S-MEM-2 (register-map artifact is a build output) is the artifact-specific specialisation. Both **mirror** INV-SOS-A without modification of the parent invariant.

### vs. INV-SOS-G (verified-codegen position)

INV-S-MEM-5's atomicity-claim auditability **mirrors** INV-SOS-G: runtime atomicity checks MAY be elided when the chart-bounds analysis discharges the obligation, with citation. The HDL-side analog (synth-tool optimisation around `assume false` proven-impossible decode paths) is left as a SOS-09-E follow-on, parallel to the SOS-13 Rust-side mechanism.

### vs. INV-SOS-H (vector-to-chart traceability)

INV-S-MEM-6 (membrane vectors are integration contract) **adapts** INV-SOS-H: every membrane-vector failure renders in chart vocabulary, naming the register, the channel, the zone, and the chart state/transition that motivated the vector.

## 11. Non-goals

This phase does NOT:

- Define a new bus protocol. AXI4-Lite and APB (per SOS-09-E) are upstream specs SOS emits against; SOS does not author a custom bus.
- Replace `svd2rust` or `chiptool`. SOS-09-D emits in the svd2rust-style idiom by convention so existing Rust embedded tooling consumes the output, but the Rust HAL trait emission lives inside the SOS codegen, not as a fork of svd2rust.
- Target non-ARM CPUs at v1. The MPU configuration emission (SOS-09-G) is ARMv7-M-specific; the C / Rust HAL emissions (SOS-09-C / D) are portable but their integration with the rest of the SOS-04 / SOS-05 runtime presumes Cortex-M. RISC-V / Cortex-R / other targets are future extensions.
- Emit SoC-level integration (clock trees, reset distribution, IO pin assignment, board-specific instantiations). Per SOS-08 §11 / PCDN-SOS-08-011, top-level wrapper generation is a SOS-08 follow-on; SOS-09 emits the register-file IP block, not the SoC.
- Verify hardware metastability in the formal model. Per INV-S-HDL-3 (from SOS-08-CONCEPTS.md §7), `sos_synchronizer` flops are excluded from the formal proof; MTBF calculation handles that path separately.
- Define a debugger-side artifact format beyond CMSIS-SVD. The on-chip debugger consumes the SVD via standard tools; SOS-09 does not author a new debug-side protocol.

## 12. Acceptance checklist

A conforming SOS-09 umbrella ratification satisfies:

- (a) ⏸ PCDN-SOS-09-001 through 006 resolved.
- (b) ⏸ Each sub-phase SOS-09-A through SOS-09-G has its own concept doc drafted and ratified.
- (c) ⏸ At least one chart channel (recommended: a `kind="status"` channel) emits all six artifacts (CMSIS-SVD entry, SystemRDL entry, C HAL header, Rust HAL trait, HDL register-file RTL, membrane vector set) as a worked example.
- (d) ⏸ The SVD output passes `svd2rust` round-trip and the generated Rust HAL trait compiles under `cargo check --target thumbv7em-none-eabihf`.
- (e) ⏸ The HDL register-file RTL synthesizes via Yosys + nextpnr (per SOS-08 PCDN-008 / EOQ-004 Lattice ECP5 target) and passes the membrane-vector cocotb tests against the simulated bitstream.
- (f) ⏸ Cross-phase invariants INV-SOS-A through H cited correctly in each sub-phase doc; cross-sub-phase invariants INV-S-MEM-1 through 6 cited correctly per sub-phase.
- (g) ⏸ SOS-03 §15 amendment co-landed extending the vector framework to the six membrane-vector shapes.
- (h) ⏸ SOS-04 §15 amendment co-landed recording the SOS-09 emission / SOS-04 runtime boundary.
- (i) ⏸ SOS-01 §15 amendment co-landed adding the channel-annotation lint rules (chart-error on missing `kind`, `dir`, or unmappable `kind`/`dir` pair per §5.2).

(j) and onward are implementation gates that ratify when the sub-phase landings happen.

## 13. Files cited

| Path | Role |
|---|---|
| `docs/concepts/SOS-07-CONCEPTS.md` | Cross-phase invariants INV-SOS-A through H; AuthorityRelationship matrix. Cited but not redefined. |
| `docs/concepts/SOS-08-CONCEPTS.md` | HDL backend umbrella; L0 primitive library and INV-S-HDL-1 through 5. Cited but not redefined. |
| `docs/concepts/SOS-ROADMAP-07-PLUS.md` | Informative roadmap; the EOQ-005 (CMSIS-SVD primary) and EOQ-004 (Lattice SoC) resolutions this phase consumes. |
| `docs/concepts/SOS-00-CONCEPTS.md` | M7 primitive contract; §6 owns the ARMv7-M MPU subset that SOS-09-G mirrors. |
| `docs/concepts/SOS-03-CONCEPTS.md` | Vector framework; SOS-09-F extends via §15 amendment. |
| `docs/concepts/SOS-04-CONCEPTS.md` | M7 Rust port; §15 amendment records the SOS-09 / SOS-04 boundary. |
| `docs/concepts/SOS-06-CONCEPTS.md` | Codegen evaluation; the seven metrics extend to membrane-vector emissions naturally. |
| `rtos_kernel.scxml` | Bootstrap kernel chart; candidate site for the worked-example channel (a kernel-internal HW timer or NVIC IRQ exposure). |
| `tools/sos-codegen/` | Codegen tool; gains SOS-09 emit paths. |
| Parent `CLAUDE.md` | Spec-Before-Code Planning Discipline. |

## 14. Unblocks

This phase's umbrella ratification (after PCDN resolution) unblocks:

- **SOS-09-A through SOS-09-G sub-phase concept-doc cycles**, each independently.
- **SOS-10** (multi-language orchestrator) — depends on SOS-09 for the HW↔SW edges across the orchestrator's per-piece boundaries per the SOS-ROADMAP-07-PLUS dependency graph.
- The "PDF cannot lie because the PDF is generated" claim made concrete as a build artifact.
- The first end-to-end chart-driven SoC bring-up demo: chart → CMSIS-SVD + Rust HAL + HDL register file + membrane vectors → Yosys+nextpnr ECP5 bitstream → cocotb-validated round-trip, with the chart as the single source.

## 15. Pending Concept Decision Notices (PCDNs)

These are the open questions whose resolution moves this doc from 🟡 drafted to 🟢 ratified.

- **PCDN-SOS-09-001 — Channel-annotation XML namespace.** Custom XML namespace (`xmlns:sos="https://softoboros.com/sos/1.0"`) vs leveraging the iState `other_attributes` extension surface (per INV-SOS-D). **Recommendation**: leverage `other_attributes` at v1 — preserves the scjson round-trip path that EOQ-008 resolution depends on; keeps SOS off the namespace-registration hook; matches the existing iState `position_x`/`position_y` precedent. A future migration to a registered custom namespace stays available if iState's tooling outgrows `other_attributes`. **Status: 🟢 amended 2026-05-25 — original 2026-05-23 resolution (custom `xmlns:sos="https://softoboros.com/sos/1.0"`) retracted; see the change-log amendment entry below for the re-ratified `other_attributes` resolution.**

- **PCDN-SOS-09-002 — Per-channel atomicity declaration: implicit by `kind`, or explicit annotation?** §5.3 default-inference rule covers the four `kind` values cleanly, but composite registers (a `status` channel whose bits aggregate multiple HW events that need a single coherent read) need explicit override. **Recommendation**: implicit default per §5.3; explicit `sos:atomicity` key (within the host element's `other_attributes`, per PCDN-SOS-09-001 amended 2026-05-25) overrides. The override is rare enough that requiring it everywhere is friction; the default-inference rule is correct for the common case.

- **PCDN-SOS-09-003 — Register layout (bit ordering, padding, reserved-bit policy): chart-driven or per-target derived?** A `kind="status"` channel with 13 bits of meaningful payload on a 32-bit-wide register needs a bit layout. Options: (a) chart declares the full bit layout via a `<bit_layout>` sub-element; (b) chart declares the bit fields and the codegen derives padding + reserved bits per-target ABI. **Recommendation**: option (b) — chart declares semantic fields, codegen handles the rest. Per-target overrides (e.g. for ABI compatibility with an existing register that SOS-09 is replacing) opt in via an explicit `<padding>` directive. Reserved bits MUST read-as-zero / write-as-zero per default ARMv7-M discipline.

- **PCDN-SOS-09-004 — IRQ-line assignment policy.** A `kind="status"` channel with `dir="hw→sw"` and an `irq` annotation needs an NVIC line. Options: (a) chart declares the physical IRQ number (couples chart to target); (b) chart declares a logical IRQ name; emitter maps to physical NVIC line via per-target table. **Recommendation**: option (b) — preserves chart portability across targets; per-target IRQ-mapping table lives alongside the linker-script and `memory.x` artifacts in the SOS-04 / SOS-05 per-port surface. The chart says `irq="hw_event_ready"`; the per-target table says `hw_event_ready = 73`.

- **PCDN-SOS-09-005 — Membrane vector co-simulation framework.** Options: (a) cocotb-with-Python-CPU-stub at v1 (the SW side is a Python stub model of register writes/reads; the HW side is RTL); (b) cycle-accurate ISS integration (link a real Cortex-M ISS into the cocotb test) deferred. **Recommendation**: option (a) at v1. The Python stub model is sufficient for the membrane contract (read/write pairing, side effects, atomicity under chart-permitted concurrency, protection rejection). Cycle-accurate ISS integration is a future enhancement when the chart-bounds analysis demands cycle-level claims (e.g. an `<sos:timing>` annotation declaring "write-to-status-update latency ≤ N cycles").

- **PCDN-SOS-09-006 — Protection-zone enumeration: v1 ARMv7-M privileged/unprivileged or full TrustZone-style four-zone model?** §5.4 enumerates `{ privileged, unprivileged }` at v1. Options: (a) keep v1 strict (privilege axis only); (b) introduce four zones now `{ secure-privileged, secure-unprivileged, non-secure-privileged, non-secure-unprivileged }` for forward compatibility with Cortex-M33+ targets. **Recommendation**: option (a) at v1 — strict subset matches the SOS bench substrate (the disco-analyzer's STM32H747I-DISCO is Cortex-M7, no TrustZone). The four-zone model lands when a Cortex-M33+ target enters the SOS bench surface; the enumeration extension is a §15 amendment to §5.4 + propagation through SOS-09-G's MPU emission. Per §5.4 frozen-enumeration registration policy (Standards Action), this extension is gated correctly.

## 16. Change log

### 2026-05-23 — Initial draft (Ira)

- Authored `SOS-09-CONCEPTS.md` as the umbrella concept doc for the hardware/software membrane.
- Frozen decisions §5: channel-category enum `{status, command, queue, shared}` (§5.1); channel → membrane-primitive mapping (§5.2); atomicity class `{atomic, mutex-required}` (§5.3); protection zone `{privileged, unprivileged}` at v1 (§5.4 per PCDN-SOS-09-006); CMSIS-SVD primary + SystemRDL secondary per EOQ-005-ROADMAP (§5.5).
- Sub-phase scope §6 sketches SOS-09-A (chart annotation surface), SOS-09-B (CMSIS-SVD), SOS-09-C (C HAL), SOS-09-D (Rust HAL), SOS-09-E (HDL register-file RTL), SOS-09-F (membrane vectors), SOS-09-G (MPU configuration).
- Cross-sub-phase invariants §7: INV-S-MEM-1 through 6 (single-source register definition; register-map-as-build-output; end-to-end protection; mandatory side-effect declaration; auditable atomicity; vectors-as-integration-contract).
- Standards integration matrix §8: adds 9 rows to SOS-07 §7 (CMSIS-SVD, SystemRDL, svd2rust, chiptool, ARMv7-M MPU subset, AXI4-Lite, APB, iState `other_attributes` extension, plus the SOS-09 channel-annotation key convention per PCDN-001 as originally drafted; row content was superseded 2026-05-25 — see amendment entry below).
- Reconciliation §10: composes SOS-08-A primitives without re-derivation; SOS-04 / SOS-05 register-access pattern stays for CPU-internal peripherals; SOS-03 vector framework extends to six membrane-vector shapes via §15 amendment.
- Six PCDNs raised covering the umbrella-level decisions that need user input before sub-phase work begins.

Status: 🟡 **drafted**, awaiting PCDN walkthrough.

### 2026-05-23 — Ratified (Ira)

All 6 PCDNs walked and resolved:

| PCDN | Resolution |
|---|---|
| **001 — Channel-annotation XML namespace** | ✅ **Custom `xmlns:sos="https://softoboros.com/sos/1.0"`** namespace for SOS-specific channel attributes (`kind`, `dir`, `mutex`, `protection-zone`). Cleaner separation from W3C SCXML reserved attributes; iState position attributes stay on `other_attributes` per the existing pattern. — **🟡 superseded 2026-05-25; see PCDN-SOS-09-001 amendment entry below** |
| **002 — Per-channel atomicity declaration** | ✅ **Implicit by `kind` value** with explicit override available. `kind="status"` / `"command"` are single-register atomic; `kind="queue"` is non-atomic (DPRAM access via mutex); `kind="shared"` requires explicit `mutex` attribute. Override via `atomicity="explicit"`. Reduces chart noise. |
| **003 — Register layout policy** | ✅ **Per-target derived** at v1 (CMSIS-SVD's natural shape). Chart declares semantic fields (name, width, access, side-effect); emitter assigns physical bits per target ABI. Decouples chart from physical layout; target-specific concerns stay with target emitters. |
| **004 — IRQ-line assignment** | ✅ **Logical IRQ → per-target NVIC table mapping**. Chart declares logical IRQ name (e.g. `irq="hw_data_ready"`); per-target table (e.g. STM32H747 SVD) maps to physical NVIC line. Multiple targets share a chart by remapping the table. |
| **005 — Membrane co-sim framework** | ✅ **cocotb + Python CPU-stub at v1**. Lightweight; co-sims the HDL side against a Python model of the CPU side's accessor calls. Sufficient for membrane register-pair verification; aligns with SOS-08-D's cocotb-first priority. Cycle-accurate ISS (QEMU/Renode) deferred to a future phase. |
| **006 — Protection-zone enumeration** | ✅ **Privileged / unprivileged at v1**. Two-zone model matches typical Cortex-M MPU. ARMv8-M TrustZone 4-zone deferred to a future phase if a customer requires it. |

Status: 🟢 **ratified**. SOS-09 implementation work (extending `tools/sos-codegen/` with the channel-annotation emit path → CMSIS-SVD + HAL accessors + RTL register file + membrane vectors) unblocked. The SOS-08-A/B primitive + service layers gate the SOS-09 RTL-emit path; both SOS-08-A and SOS-09 implementation can proceed in parallel since the SOS-08-A library is consumed but not modified by SOS-09.

### 2026-05-25 — PCDN-SOS-09-001 amendment — channel annotations on `other_attributes` (retraction + re-ratification)

**Status: 🟢 amended 2026-05-25 — supersedes the 2026-05-23 PCDN-SOS-09-001 resolution.**

**Retraction.** The 2026-05-23 PCDN-SOS-09-001 resolution that chose a custom XML namespace (`xmlns:sos="https://softoboros.com/sos/1.0"`) for SOS-specific channel attributes is hereby retracted. The two-tier convention (iState position attributes via `other_attributes`, SOS-semantic channel attributes via a registered `xmlns:sos`) is no longer the SOS-09 standard. The namespace URL `https://softoboros.com/sos/1.0` is **NOT registered** by SOS for SOS-09 channel annotations; any future PCDN that proposes a custom XML namespace for SOS-09 channel annotations is a new ratification round.

**Amended resolution.** All SOS-09 channel annotations — the four-attribute set `kind`, `dir`, `mutex`, `protection-zone`, plus any future SOS-09-semantic channel attributes — attach via iState's `other_attributes` extension surface, consistent with the existing iState convention for `position_x`, `position_y`, and related layout attributes. The annotation key uses a `sos:` STRING prefix WITHIN the `other_attributes` JSON, NOT an XML namespace prefix. Example shape (illustrative, not generated XML):

```
<state id="rx_path" other_attributes='{"sos:kind": "status", "sos:dir": "hw→sw", "sos:mutex": "ch_mtx", "sos:protection-zone": "privileged", "position_x": "120", "position_y": "240"}'>
  ...
</state>
```

The `sos:` prefix is purely a JSON-key string convention SOS-09 owns; the surrounding XML carries NO `xmlns:sos` declaration. iState layout keys (`position_x`, `position_y`, etc.) and SOS-semantic keys (`sos:kind`, `sos:dir`, etc.) coexist in the same `other_attributes` JSON map; readers distinguish them by the `sos:` prefix on keys.

**Rationale** (quoting and confirming the original 2026-05-23 staging-recommendation):

- Preserves the scjson round-trip path that EOQ-008 resolution depends on. A registered custom XML namespace would have required scjson schema work upstream; staying inside `other_attributes` keeps SOS-09 implementable without iState changes.
- Keeps SOS off the XML-namespace-registration hook. No URL is registered, claimed, or implied to be served; the namespace URL `https://softoboros.com/sos/1.0` is not a working namespace declaration anywhere in chart-author-facing XML or generated artifacts.
- Matches the existing iState `position_x` / `position_y` precedent. Chart authors already attach layout annotations via `other_attributes`; SOS-09 channel annotations follow the same surface, reducing convention sprawl.
- Single extension surface (`other_attributes`) for ALL chart-author-attached annotation, layout AND semantic. The element-vs-attribute distinction stays clean: attributes attach to existing iState/SCXML elements via `other_attributes`; new elements (SOS-08-D / -E vocabulary) live in their own namespace-or-not contracts.

**Scope clarification (MUST).** This amendment applies to **SOS-09 channel ANNOTATIONS only** — attributes attached to existing iState/SCXML elements (`<region>`, `<state>`, `<parallel>`) via the `other_attributes` extension surface. It MUST NOT be read as amending SOS-08-D's or SOS-08-E's namespaced ELEMENT vocabulary: `<sos:cross_invariant>`, `<sos:state_ref>`, `<sos:and>`, `<sos:or>`, `<sos:not>`, `<sos:implies>`, `<sos:raw_property>`, `<sos:sampling_clock>`, `<sos:shared_signal>`, `<sos:shared_signal_ref>`, `<sos:clock_domains>`, `<sos:clock>`, `<sos:cdc_boundary>`, `<sos:channel>` (as a NEW ELEMENT in SOS-08-D / -E vocabulary) — those are new XML elements introduced and ratified in their own phases (SOS-08-D and SOS-08-E), each carrying its own emit machinery and authority, and remain outside the scope of this amendment. The element-vs-attribute distinction is preserved: attributes-on-existing-elements use `other_attributes`; new-elements use their phase-owned vocabulary. If a future PCDN proposes consolidating SOS-08-D / -E's element vocabulary into `other_attributes` (or vice versa), that PCDN MUST be a separate ratification round.

**Implementation impact.** SOS-09 implementation has not begun. No code retraction is needed; this is a spec-text amendment only. When the SOS-09 emit path is implemented (future wave), it MUST read channel annotations from `other_attributes`, treating `sos:`-prefixed keys (e.g. `sos:kind`, `sos:dir`, `sos:mutex`, `sos:protection-zone`) as SOS-semantic and other keys (`position_x`, `position_y`, etc.) as iState-layout-or-other. No `xmlns:sos` declaration appears in chart-author-facing XML, in generated artifacts (CMSIS-SVD, SystemRDL, C HAL, Rust HAL, HDL RTL, MPU table, membrane vectors), or in normative XML examples within concept docs for SOS-09.

**Update obligation.** Any prior text in `SOS-09-CONCEPTS.md` (§3 glossary, §6 sub-phase scope, §8 standards-integration matrix, §15 PCDN-SOS-09-001 entry, the §16 2026-05-23 ratification entry's PCDN-001 row, or any XML example) that referenced `xmlns:sos`, the URL `https://softoboros.com/sos/1.0`, or the two-tier convention has been updated to the amended `other_attributes` language in this same commit. The §15 PCDN-SOS-09-001 entry carries a 🟢 amended status marker; the §16 2026-05-23 ratification row's PCDN-001 cell carries a 🟡 superseded marker — original resolution text is preserved as institutional memory per the spec-before-code discipline (resolved entries stay in the log).

**Authority.** Per SOS-07 §7 AuthorityRelationship vocabulary: the SOS-09 channel-annotation key convention (the `sos:` string-prefix on keys inside `other_attributes`) is `own` — SOS authors the prefix-convention and the four-attribute set. The relationship to iState's `other_attributes` extension surface is `compose` — SOS-09 uses iState's surface; iState owns the surface. NO XML namespace URL is registered or claimed by SOS-09; the `sos:` prefix is a JSON-key string prefix, not an XML namespace prefix.

**Frozen-enumeration registration policy.** The four-attribute set (`kind`, `dir`, `mutex`, `protection-zone`) declared by this amendment is **Standards Action**: adding a fifth SOS-semantic channel-annotation key requires a §16 amendment to this doc and a ratification session. The `sos:` prefix convention itself is also Standards Action — changing the prefix string is a cross-phase contract change.

**Tracking.** Supersedes the 2026-05-23 PCDN-SOS-09-001 resolution (which remains in the §16 2026-05-23 ratification table, marked 🟡 superseded). Cross-references: PCDN-SOS-09-001 entry in §15 (status marker added); §3 channel/membrane glossary terms (unchanged by this amendment — the channel category enum and primitive mappings of §5 are unaffected). Test coverage: `tools/sos-codegen/tests/test_sos_09_pcdn_001_amendment.py`.
