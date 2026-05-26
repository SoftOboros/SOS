# SOS-09-C — C HAL header emission

**Status:** 🟢 **RATIFIED 2026-05-26**

## 0. Authority policy

This phase doc is the **C HAL header emission** sub-phase under the SOS-09 umbrella (`SOS-09-CONCEPTS.md`, ratified 2026-05-23, with PCDN-SOS-09-001 amended 2026-05-25). The umbrella's §6 names this sub-phase as the codegen path producing C accessor headers from chart annotations; its §5 freezes the cross-sub-phase decisions (channel-category enum, channel → membrane-primitive mapping, atomicity class semantics, protection-zone enumeration, register-map artifact priority) which SOS-09-C consumes without re-derivation.

Per the parent CLAUDE.md "Spec-Before-Code Planning Discipline / Phase document shape":

- **Normative** sections of this doc: §3 glossary, §4 source-of-truth map, §5 frozen decisions (accessor-macro naming convention; `volatile` qualifier policy; side-effect annotation form; header layout; compile-time constants; MPU-region symbol export), §6 invariants (INV-S-MEM-C-1 through INV-S-MEM-C-5), §7 enumeration policies, §12 acceptance checklist.
- **Informative** sections: §1 purpose, §2 problem statement, §10 reconciliation, §11 non-goals, §15 pending PCDNs (filed open), §16 change log.
- All keywords MUST, MUST NOT, SHALL, SHOULD, SHOULD NOT, MAY are interpreted per RFC 2119 / RFC 8174 when capitalised.

This doc cites SOS-07 §6 for the cross-phase invariants `INV-SOS-A` through `INV-SOS-H`, SOS-09 §7 for the cross-sub-phase invariants `INV-S-MEM-1` through `INV-S-MEM-6`, SOS-09-A §5 for the chart annotation surface (`sos:id`, `sos:name`, `sos:kind`, `sos:dir`, `sos:zone`, etc.), SOS-09-B §5 for the CMSIS-SVD emission contract that SOS-09-C derives its struct overlay layouts from, and SOS-09-G §5.3 for the MPU-region descriptor shape that SOS-09-C exports symbol declarations for. None of these sets is re-derived here.

Per PCDN-SOS-09-001 amended 2026-05-25, chart annotations are read from iState's `other_attributes` extension surface via `sos:`-prefixed JSON keys. SOS-09-C's emit path MUST honour this convention; the `sos:` prefix is a JSON-key string prefix, not an XML namespace prefix. Per SOS-09-A §5.2 (PCDN-SOS-09-A-003 ratification), the SV-identifier-shaped `sos:name` is the emission-facing handle (used in macro symbols); `sos:id` is the RFC 4122 UUID identity-only handle (not used directly in macro symbols).

## 1. Purpose

To freeze the C HAL header emission contract: how the codegen produces typed, side-effect-aware, MPU-aware C accessor headers from the same chart annotations that drive SOS-09-B's CMSIS-SVD emission and SOS-09-G's MPU table emission. Each emitted header carries `#define` register-address constants, `volatile`-qualified struct overlays for typed access, side-effect-discriminated accessor macros / inline functions (`*_read_*`, `*_write_*`, `*_consume_*`, `*_fire_*`, `*_claim_*`, `*_release_*`), compile-time field shift/mask constants, and `extern` MPU-region symbol declarations consumable by `sos_mpu_install()` (per SOS-09-G §5.5).

Without this freeze, two emission implementations could disagree on accessor naming (one emits `READ_FOO`, another `foo_read`), volatile placement (struct typedef vs per-access cast), side-effect discrimination (one emits `read_irq_status`, another `consume_irq_status` for the same chart-declared `sos:clear_on_read="true"` channel), or MPU symbol export (one exports `sos_mpu_<channel>_region`, another exports nothing and forces SOS-09-G to re-emit its own). Downstream consumers (firmware drivers, SOS-04 / SOS-05 runtime, lint passes) cannot author against an unstable C HAL shape.

## 2. Problem statement

The umbrella §2 names the "register-map PDF that lies" as the canonical hardware/software co-design failure mode and prescribes deriving every artifact from the chart annotation. The CMSIS-SVD artifact (SOS-09-B) is one downstream realisation; the C HAL header is the other half of the SW side. Three concrete failure patterns in hand-rolled C HAL headers motivate this sub-phase's freeze:

1. **Drift between the register-map and the access macros.** A driver team that hand-rolls `#define REG_FOO (*(volatile uint32_t *)0x40001000)` against a register-map PDF (the failure mode of §2 of the umbrella) carries the PDF's drift forward into every `.c` file that includes the header. When the silicon team renumbers the register, the PDF is updated; the header is not; the driver silently writes to the wrong address. The SOS-09-C emission cure: the header is derived from the same chart annotation that drives the SVD and the RTL — `#define REG_FOO 0x40001000` is emitted; chart-authors edit the chart; the header regenerates; drift is impossible by construction.

2. **Missing `volatile` qualifiers.** Hand-rolled register-map headers chronically miss `volatile` qualifiers on bit-field struct overlays. The compiler then re-orders, coalesces, or elides reads / writes the silicon side observes as side-effect triggers — and the bug is a memory model bug, not a logic bug, so it doesn't appear in unit tests. The SOS-09-C cure: every struct-overlay field is `volatile`-qualified at the typedef level (§5.2); the emitter cannot omit it because it's a property of the type itself, not the per-access cast.

3. **Missing side-effect documentation.** A `clear-on-read` register accessed via plain `r = REG_IRQ_STATUS` looks identical at the call site to a `read-only` register accessed the same way — yet one mutates HW state and the other does not. Reviewers cannot distinguish the two without consulting the register-map PDF (which lies, per §2 of the umbrella). The SOS-09-C cure: side-effect-bearing accessors are emitted with discriminating names (`SOS_C_<channel>_consume_status` rather than `SOS_C_<channel>_read_status`); the call site syntactically encodes the side effect; reviewers read the discipline without leaving the source file.

4. **Missing access-control coupling between MPU and HAL.** Hand-rolled HAL headers know nothing about which channels are privileged-zone-only; the MPU configuration table is a separate `#define` tangle in startup code; the two drift apart silently. The SOS-09-C cure: the HAL header carries `extern const sos_mpu_region_t sos_mpu_<channel>_region;` declarations for every chart-declared protection-zone channel (per PCDN-SOS-09-G-001 / G-002 ratification), so `sos_mpu_install()` (per SOS-09-G §5.5) consumes the same chart-declared zones the HAL caller observes.

SOS-09-C makes all four symptoms the same symptom of one disease — the absence of a chart-rooted emit pipeline for the C side — and prescribes one cure: emit the header from the chart annotation; deny by construction the cases where drift, missing volatile, undocumented side effects, or MPU/HAL decoupling can occur.

## 3. Canonical glossary

Terms normative within SOS-09-C+. Authority relationships per §8. (Section §8 is intentionally compact for this sub-phase — most concepts mirror SOS-09-B's matrix; see §4 source-of-truth map for the per-concept owner.)

| Term | Definition |
|---|---|
| **register block** | The C `struct` typedef emitted per chart channel-group (per §5.4), with one `volatile`-qualified field per chart channel in the group. The struct's layout mirrors the SVD `<peripheral>`'s `<addressOffset>` chain; field types are sized by `sos:width`. As composed from SOS-09-B's emission. |
| **accessor macro family** | The set of `SOS_C_<channel>_<op>` macros / `static inline` functions emitted per chart channel. `op ∈ {read, write, consume, fire, claim, release}` per §5.1; the subset emitted depends on the channel's `sos:kind` + `sos:dir` + side-effect annotations per §5.3. |
| **side-effect-bearing accessor** | An accessor whose call invokes silicon-side action beyond the value update. The two emit shapes are `*_consume_*` (read-and-clear; `clear-on-read` semantics) and `*_fire_*` (write-and-trigger; `side-effect-on-write` or `command`-`kind` semantics). Per INV-S-MEM-C-2 / INV-S-MEM-C-3, side-effect-bearing accessors are NEVER named `*_read_*` or `*_write_*`. |
| **claim/release accessor** | The pair `SOS_C_<channel>_claim` / `SOS_C_<channel>_release`, emitted only for channels with `sos:kind="shared"`. Wraps `sos_mutex` claim / release (SOS-08-A) around the channel access. Per §5.1, `claim` / `release` are reserved for shared-kind channels. |
| **umbrella header** | The single `sos_<chart>.h` header that transitively includes every per-group sub-header (per §5.4 and PCDN-SOS-09-C-004 default recommendation). Chart authors / driver authors include the umbrella; the umbrella pulls in the per-group headers. |
| **per-group sub-header** | One header per chart channel-group, named `sos_<chart>__<group>.h`. The group is the `<state>`-or-`<region>` ancestor scope of the channels (per SOS-09-A §5.1 parent-context rules; per SOS-09-B §5.2 peripheral grouping). |
| **field shift / mask constant** | A `static const unsigned` (per §5.5) declared for every chart-declared semantic bit field on a register. Allows type-safe overflow checking and `-Wpedantic` clean output (vs preprocessor `#define` constants which lose type). |
| **MPU-region symbol** | An `extern const sos_mpu_region_t sos_mpu_<channel>_region;` declaration emitted into the per-group header for every chart channel with a `sos:zone` annotation. The corresponding definition lives in `<chart>_mpu.c` (per SOS-09-G §5.3). Consumed by `sos_mpu_install()` step 4 per SOS-09-G §5.5. |
| **deterministic-from-`sos:name`** | The property that two charts with the same set of `sos:name` values (regardless of `sos:id` UUID values) produce link-time-identical accessor symbols. Per INV-S-MEM-C-5; the property that makes the C HAL contract stable across chart-author UUID-regeneration events. |

## 4. Source-of-truth map

For every concept this sub-phase touches, **exactly one** location is the canonical authority.

| Concept | Upstream authority | Local relationship | Owner |
|---|---|---|---|
| Channel-category enum (`status` / `command` / `queue` / `shared`) | `SOS-09-CONCEPTS.md` §5.1 | **mirror** | umbrella |
| Channel → membrane-primitive mapping | `SOS-09-CONCEPTS.md` §5.2 | **mirror** | umbrella |
| Atomicity class enum | `SOS-09-CONCEPTS.md` §5.3 | **mirror** | umbrella |
| Protection zone enum | `SOS-09-CONCEPTS.md` §5.4 | **mirror** | umbrella |
| Chart annotation parsing (`sos:`-prefixed keys in `other_attributes`) | `SOS-09-A-CONCEPTS.md` §5 | **mirror** | SOS-09-A |
| `sos:name` → emission symbol mapping | `SOS-09-A-CONCEPTS.md` §5.2 (PCDN-SOS-09-A-003 ratification) | **mirror** | SOS-09-A |
| Register `<addressOffset>` chain (struct layout source) | `SOS-09-B-CONCEPTS.md` §5.3 | **compose** | SOS-09-B |
| Side-effect annotation source (`sos:side_effect`, `sos:clear_on_read`) | `SOS-09-B-CONCEPTS.md` §5.4 + SOS-09-A §5.2 | **mirror** | SOS-09-A + SOS-09-B |
| C accessor macro / inline-function naming convention | **this doc** (§5.1) | **own** | this doc |
| `volatile` qualifier placement policy | **this doc** (§5.2) | **own** | this doc |
| Side-effect annotation form in emitted C (`*_consume_*`, `*_fire_*`) | **this doc** (§5.3) | **own** | this doc |
| Header layout (umbrella + per-group; transitive include) | **this doc** (§5.4) | **own** | this doc |
| Compile-time constant emission policy (`#define` vs `static const`) | **this doc** (§5.5) | **own** | this doc |
| MPU-region symbol export shape | **this doc** (§5.6); definition lives in SOS-09-G | **derive** (consumes SOS-09-G's `sos_mpu_region_t`) | this doc + SOS-09-G |
| `gcc -Wall -Wextra -Wpedantic -std=c11` toolchain gate | **this doc** (§12) | **derive** (gcc owns the option semantics) | this doc |
| `sos_mpu_region_t` C type | `SOS-09-G-CONCEPTS.md` §5.3 | **mirror** | SOS-09-G |
| `sos_mpu_install()` runtime hook | `SOS-09-G-CONCEPTS.md` §5.5 | **mirror** | SOS-09-G |
| Cross-sub-phase invariants INV-S-MEM-C-1 through 5 | **this doc** (§6) | **own** | this doc |
| Cross-sub-phase invariants INV-S-MEM-1 through 6 | `SOS-09-CONCEPTS.md` §7 | cited not redefined | umbrella |
| Cross-phase invariants INV-SOS-A through H | `SOS-07-CONCEPTS.md` §6 | cited not redefined | SOS-07 |
| Existing `tools/sos-codegen/transliterate_c.py` (ECMAScript→C transliterator) | `transliterate_c.py` (SOS-04/SOS-05 scripts) | **adapt** (the existing module owns chart-script→C; SOS-09-C HAL emit lives in a new sibling module `tools/sos-codegen/c_hal_emit.py` to keep the SOS-04/05 scripts surface disjoint) | this doc |

## 5. Frozen decisions

### 5.1 Accessor-macro naming convention

Every accessor emitted by SOS-09-C follows the form:

```
SOS_C_<channel>_<op>
```

where `<channel>` is the chart-declared `sos:name` (an SV identifier per SOS-09-A §5.2 PCDN-SOS-09-A-003 ratification), `_` is the literal underscore separator, and `<op>` is one of the six operation strings:

```
op ∈ { read, write, consume, fire, claim, release }
```

The subset emitted for a given channel is determined by the channel's `sos:kind` + `sos:dir` + side-effect annotations per the table:

| chart `sos:kind` | chart `sos:dir` | side-effect? | Emitted ops |
|---|---|---|---|
| `status` | `hw→sw` | (none) | `read` |
| `status` | `hw→sw` | `sos:clear_on_read="true"` | `consume` (NOT `read`) |
| `command` | `sw→hw` | (default for command kind) | `fire` (NOT `write`) |
| `queue` | `hw↔sw` | — | `read`, `write` |
| `shared` | `hw↔sw` | — | `read`, `write`, `claim`, `release` |

**Reservation rules** (per INV-S-MEM-C-3):
- `claim` and `release` are RESERVED for `sos:kind="shared"`. Emitting them on any other kind is a chart authoring error caught by SOS-09-C's lint.
- `fire` is RESERVED for `sos:kind="command"` OR for any kind+dir channel with `sos:side_effect` declared on the write path.
- `consume` is RESERVED for any read-bearing kind whose register declares `sos:clear_on_read="true"` (typically `sos:kind="status"`).
- Plain `read` MUST NOT be emitted alongside `consume` for the same channel; plain `write` MUST NOT be emitted alongside `fire`. The discrimination is total — the emitter picks exactly one read-shape per channel and exactly one write-shape (when applicable) per channel.

Per PCDN-SOS-09-C-005, the recommended emission shape for these accessors is `static inline` C11 functions (typed, debuggable) rather than preprocessor `#define` macros; both forms are syntactically `SOS_C_<channel>_<op>` so the call-site shape is identical. The PCDN walkthrough may amend the inline-vs-define choice without changing the naming convention itself.

Frozen-enumeration registration policy: **Standards Action**. Adding a seventh `<op>` value (e.g. a hypothetical `peek` for non-side-effect reads of a side-effect-bearing register) requires a §16 amendment and cross-phase review. The `<op>` enumeration encodes the cross-phase contract between C HAL callers and the chart-declared side-effect surface; modifying it silently breaks every caller.

### 5.2 `volatile` qualifier policy

Every register field accessed through a SOS-09-C-emitted struct overlay MUST be `volatile`-qualified at the **typedef level**, not at the per-access cast. The struct field types are declared:

```c
typedef struct {
    volatile uint32_t foo;       /* sos:width=32 channel "foo" */
    volatile uint16_t bar;       /* sos:width=16 channel "bar" */
    volatile uint8_t  baz_lo;    /* low byte of split-width channel "baz" */
    volatile uint8_t  baz_hi;    /* high byte */
    /* ... */
} sos_<chart>__<group>_regs_t;
```

Per PCDN-SOS-09-C-002, the recommended placement is per-field on the typedef (above); the alternative — per-access cast `*(volatile uint32_t *)&block->foo` — is rejected at v1 because:

1. It distributes the `volatile` discipline across every call site, where omissions are silent.
2. It complicates lint enforcement (a missing cast is invisible without analyzing every access).
3. It defeats the type-safety the typedef provides for struct-member access.

The bit-field types declared inside accessor inline functions (per §5.1, PCDN-SOS-09-C-005) MUST be declared `volatile <unsigned type>` (e.g. `volatile uint32_t`) and accessed via memcpy-style helpers when strict-aliasing concerns arise:

```c
static inline uint32_t SOS_C_<channel>_read(void) {
    volatile uint32_t *p = &sos_<chart>__<group>_regs.<channel>;
    uint32_t v;
    /* memcpy form to satisfy strict-aliasing for any caller's
       reinterpretation; the volatile load is preserved. */
    v = *p;
    return v;
}
```

For multi-word channels (`sos:width > 32` on a 32-bit target), the emitter MUST emit a sequence of `volatile uint32_t` loads / stores with the chart-declared word order (default: little-endian, per ARMv7-M convention); the access is NOT atomic across the multi-word sequence (per `sos:atomicity` umbrella default-inference rule §5.3 — multi-register atomicity is `mutex-required`, which causes the emitter to emit `claim` / `release` around the access via the `shared` kind).

Frozen-enumeration registration policy: **Standards Action**. The `volatile` placement policy is a cross-phase contract — the SOS-09-D Rust HAL emission must observe the analogous discipline (per SOS-09-D's own §5 when ratified), and lint passes consume the structural property. Demoting per-field volatile to per-access volatile would silently invalidate every C-side caller's memory-model assumption.

### 5.3 Side-effect annotation form

Side-effect annotations declared in the chart per SOS-09-B §5.4 (the `sos:side_effect="<value>"` key with values per the §5.3 mapping table — `clear`, `set`, `oneToClear`, `zeroToClear`, `oneToSet`, `zeroToSet`, `toggle`, `modify`) and the `sos:clear_on_read="true"` key (from SOS-09-A) map to the SOS-09-C accessor naming as follows:

| Chart annotation | SOS-09-C emitted accessor name |
|---|---|
| `sos:clear_on_read="true"` on a `kind="status"` channel | `SOS_C_<channel>_consume` (NOT `read`) |
| `sos:side_effect="<any non-modify value>"` on the write path | `SOS_C_<channel>_fire` (NOT `write`) |
| `kind="command"` with default `command`-kind side effect | `SOS_C_<channel>_fire` (NOT `write`) |
| `kind="shared"` channel access | `SOS_C_<channel>_claim` / `SOS_C_<channel>_release` wrapping the `read` / `write` |

The discrimination is normative — the emitter MUST select the discriminating name (`consume` / `fire` / `claim` / `release`) when the chart declares the corresponding side effect; the call site syntactically encodes the side-effect discipline. A chart that declares `sos:clear_on_read="true"` on a channel and a SOS-09-C emit that produces `SOS_C_<channel>_read` for that channel is a SOS-09-C bug, caught by INV-S-MEM-C-2.

The `*_consume_*` accessor returns the value read (per PCDN-SOS-09-C-003 recommendation); callers MAY discard the return value but the value is materialised so the read-and-clear semantics are visible. The `*_fire_*` accessor returns `void`; the write has no read-back semantics for the caller.

The `*_claim_*` accessor returns a token (opaque `sos_lock_t` or equivalent per SOS-08-A's `sos_mutex` contract) the caller passes to `*_release_*`. Calling `*_release_*` without a prior matching `*_claim_*` is undefined behaviour at v1; lint MAY catch this in a future pass.

Frozen-enumeration registration policy: **Standards Action**. The side-effect-to-accessor-name mapping is the contract surface between chart-author intent and C-call-site discipline. Silent retargeting (e.g. emitting `read` for a `clear_on_read` channel) breaks INV-S-MEM-C-2 and is the precise failure mode this sub-phase exists to prevent.

### 5.4 Header layout

SOS-09-C emits headers in a two-tier layout:

- **Umbrella header**: `sos_<chart>.h` — one per chart. Includes every per-group sub-header transitively (per PCDN-SOS-09-C-004 default recommendation). Chart-author / driver-author includes the umbrella header to access every channel in the chart.

- **Per-group sub-header**: `sos_<chart>__<group>.h` — one per chart channel-group. The `<group>` token is the sanitized `sos:name` of the `<state>`-or-`<region>` ancestor scope that bounds the channels (per SOS-09-A §5.1 parent-context rules and SOS-09-B §5.2 peripheral grouping). The sub-header carries:
  1. `#define` constants for register base addresses.
  2. The `sos_<chart>__<group>_regs_t` struct typedef (per §5.2) with `volatile`-qualified fields.
  3. `static const unsigned` field shift / mask constants (per §5.5).
  4. `static inline` (or `#define`, per PCDN-SOS-09-C-005) accessor functions / macros (per §5.1).
  5. `extern const sos_mpu_region_t sos_mpu_<channel>_region;` declarations for every channel in the group with a `sos:zone` annotation (per §5.6).

Header guards use the form `SOS_<CHART>__<GROUP>_H` (all uppercase, double-underscore between chart and group); the umbrella uses `SOS_<CHART>_H`.

Per PCDN-SOS-09-C-004, the umbrella header transitively includes every per-group sub-header by default; chart-authors who need finer include control opt in by including a per-group sub-header directly. Include-time minimality is the lesser concern vs chart-author ergonomics (a chart with N groups would otherwise require N explicit includes at every call site).

Frozen-enumeration registration policy: **Specification Required**. The layout convention is local to this sub-phase's contract surface; adopting a single-flat-header form (vs the two-tier umbrella + per-group form) is a phase-owner walkthrough update, not a §16 amendment.

### 5.5 Compile-time constants

Register address constants are emitted as preprocessor `#define`s:

```c
#define SOS_C_<channel>_ADDR  0x40001000u
```

The `u` suffix is mandatory (forces unsigned arithmetic; avoids `-Wpedantic` warnings on unsigned-to-pointer casts).

Register field shift / mask constants are emitted as `static const unsigned`:

```c
static const unsigned SOS_C_<channel>_<field>_SHIFT = 4u;
static const unsigned SOS_C_<channel>_<field>_MASK  = 0x0Fu;
```

The `static const unsigned` form (vs `#define`) is chosen because:

1. The type is enforced (overflow / narrowing produces a warning under `-Wconversion`).
2. The names appear in debugger symbol tables (DWARF emits `static const` even with `-O2`).
3. The `-Wpedantic` clean-output gate (per INV-S-MEM-C-4) flags untyped preprocessor constants in certain expression contexts; `static const` avoids this entire class.

The cost is a minor link-time bloat (typically one byte per `static const` per translation unit pre-link-time-folding); modern linkers fold identical `static const` definitions across TUs. The trade is judged acceptable per PCDN-SOS-09-C-005's broader "typed accessor" preference.

Per channel, the emitter MAY also emit a `static const uintptr_t SOS_C_<channel>_BASE` to allow type-safe pointer arithmetic; the `#define`-form `SOS_C_<channel>_ADDR` remains for preprocessor uses (e.g. `#if SOS_C_<channel>_ADDR == 0x...`).

Frozen-enumeration registration policy: **Specification Required**. The `#define`-vs-`static const` choice is a per-emission-target decision; a future target whose tooling is hostile to `static const` (e.g. an obscure embedded compiler) MAY require a per-target opt-out, ratified as a phase-owner walkthrough.

### 5.6 MPU-region symbol export

For every chart channel with a `sos:zone` annotation (per SOS-09-A §5.2; per umbrella §5.4 protection-zone enum at v1 `{ privileged, unprivileged }`), SOS-09-C emits an `extern` declaration into the per-group header:

```c
extern const sos_mpu_region_t sos_mpu_<channel>_region;
```

The `sos_mpu_region_t` C type is owned by SOS-09-G §5.3 (`base_addr`, `size_log2`, `attr`, `perm`, `srd`, `region_num` fields); SOS-09-C does NOT redeclare the type. The umbrella header MUST `#include "sos_mpu.h"` (the SOS-09-G-emitted header) before any per-group sub-header that exports MPU-region symbols, so the `sos_mpu_region_t` type is in scope at every consumer site.

The corresponding definitions of `sos_mpu_<channel>_region` live in SOS-09-G's emitted `<chart>_mpu.c`; SOS-09-C only declares them. The single point of definition is SOS-09-G's `sos_mpu_table[]` (per SOS-09-G §5.3) — each `sos_mpu_<channel>_region` definition is a per-channel symbol pointer into `sos_mpu_table[]`, or equivalently a per-channel `const sos_mpu_region_t` definition that is also a row in `sos_mpu_table[]`. Per PCDN-SOS-09-G-001 / G-002 alignment, `sos_mpu_install()` step 4 reads chart-declared `sos:mpu_attr` per channel; SOS-09-C's job is to make the chart-declared per-channel `sos_mpu_region_t` reachable from caller code that wants to introspect a specific channel's MPU configuration (e.g. debug logging, runtime test).

Frozen-enumeration registration policy: **Specification Required**. The export shape (per-channel `extern` declaration vs alternative shapes — global array indexing, accessor function) is local to the C HAL contract. A future amendment that consolidates the per-channel `extern`s into a single `sos_mpu_table_ref(channel_id)` accessor function is a phase-owner walkthrough update, not a §16 amendment.

## 6. Cross-sub-phase invariants — INV-S-MEM-C-1 through INV-S-MEM-C-5

In addition to the cross-phase invariants INV-SOS-A through H (from SOS-07) and the SOS-09 cross-sub-phase invariants INV-S-MEM-1 through 6 (cited but not redefined), the following invariants are normative across SOS-09-C:

- **INV-S-MEM-C-1 — Every register field is accessed only through emitted accessors.** Raw pointer dereferencing on a register address (e.g. `*((volatile uint32_t *)0x40001000) = 1u`) is a chart-author / driver-author error caught by `-Wpedantic` + a SOS-09-C lint pass that flags pointer-cast expressions against any address in the chart-declared register set. The accessor surface IS the API; bypassing it bypasses the side-effect discipline (§5.3) and the MPU coupling (§5.6).

- **INV-S-MEM-C-2 — `clear-on-read` registers are NEVER accessed via plain `read_*`.** A chart channel with `sos:clear_on_read="true"` MUST emit `SOS_C_<channel>_consume` (not `_read`). The discrimination is total per §5.3. A double-consume (two `consume` calls on the same channel where the chart-author intent was one read) is caught by SOS-09-C lint at v2; at v1 the discrimination is at the accessor-name level only.

- **INV-S-MEM-C-3 — `command`-`kind` channels emit only `fire` / `claim` / `release` accessors, never `read`.** Per §5.1 reservation rules: `kind="command"` channels are write-only (per SOS-09 §5.2 channel → membrane-primitive mapping); the emitter MUST NOT emit `SOS_C_<channel>_read` for them. Symmetrically, `kind="status"` channels with `dir="hw→sw"` MUST NOT emit `SOS_C_<channel>_write` / `_fire`; the channel direction restricts the operation surface.

- **INV-S-MEM-C-4 — Every emitted header is `gcc -Wall -Wextra -Wpedantic -std=c11` clean.** Per the umbrella §6 SOS-09-C description ("The headers compile under `-Wall -Wextra -Wpedantic -std=c11`") and per the cross-toolchain conformance gate of acceptance gate (f). A header that emits a warning under these flags is a SOS-09-C bug; the implementation phase's CI gate enforces this. Toolchain version: `gcc` ≥ 10.x or `clang` ≥ 12.x (both support C11 cleanly).

- **INV-S-MEM-C-5 — Accessor symbol names are deterministic from `sos:name` (NOT `sos:id`).** Two charts producing the same `sos:name` set produce link-time-identical accessor symbols. The `sos:id` UUID (per SOS-09-A §5.2 PCDN-SOS-09-A-003 ratification) is identity-only; regenerating `sos:id` values across chart-author UUID-regeneration events MUST NOT change the C HAL symbol surface, because the C HAL surface is what drivers link against and is therefore the stable cross-edit ABI. This mirrors the analogous principle in SOS-09-B's `<register><name>` field (which also derives from `sos:name`, per SOS-09-B §5.3).

Frozen-enumeration registration policy: **Standards Action** (each invariant touches a load-bearing cross-phase contract surface; later relaxation requires a §16 amendment).

## 7. Enumeration policies — registration policy catalog

Per parent CLAUDE.md "Frozen enumerations — registration policy", every frozen enum declared in §5 carries an explicit registration policy. Catalog:

| §5.x | Enum / decision | Registration policy |
|---|---|---|
| §5.1 | Accessor-macro `<op>` enum `{ read, write, consume, fire, claim, release }` | Standards Action |
| §5.2 | `volatile` qualifier policy (per-field on typedef) | Standards Action |
| §5.3 | Side-effect annotation form (chart-annotation → accessor-name discrimination) | Standards Action |
| §5.4 | Header layout (umbrella + per-group; transitive include) | Specification Required |
| §5.5 | Compile-time constant emission policy (`#define` for addresses; `static const` for shifts/masks) | Specification Required |
| §5.6 | MPU-region symbol export shape (per-channel `extern`) | Specification Required |
| §6 | INV-S-MEM-C-1 through INV-S-MEM-C-5 invariants | Standards Action |

The Standards Action enumerations encode cross-phase contracts (accessor naming surface seen by drivers / lint passes; volatile discipline relied on by the compiler; side-effect discrimination relied on by reviewers; INV-S-MEM-C-* invariants relied on by every downstream consumer). The Specification Required enumerations are phase-local mechanics (header file layout convention, constant-emission form, MPU-symbol export shape) where a phase-owner walkthrough suffices for amendments.

## 8. Standards integration matrix additions

This sub-phase EXTENDS the SOS-07 §7 and SOS-09 §8 matrices. Most rows mirror the umbrella's matrix (CMSIS-SVD 1.3.x via SOS-09-B; chart annotation surface via SOS-09-A); the SOS-09-C-specific additions are:

| Concept | Upstream authority | Local relationship | Phase that declares it | Mutation rights |
|---|---|---|---|---|
| C11 language spec (ISO/IEC 9899:2011) | ISO/IEC | **derive** (SOS-09-C-emitted headers conform to C11; the standard owns the language) | this doc | none — ISO owns |
| `gcc -Wall -Wextra -Wpedantic -std=c11` toolchain gate | GNU project (gcc ≥ 10) | **derive** (the toolchain owns the warning semantics; SOS-09-C emits headers that pass without modifying gcc) | this doc | none — gcc owns |
| `clang -Wall -Wextra -Wpedantic -std=c11` toolchain gate | LLVM project (clang ≥ 12) | **derive** (equivalent gate; both toolchains required for cross-compiler validation) | this doc | none — clang owns |
| SOS-09-A chart annotation surface (`sos:name`, `sos:id`, `sos:kind`, `sos:dir`, `sos:zone`, `sos:width`, `sos:clear_on_read`, `sos:side_effect`) | this repo, SOS-09-A | **mirror** (SOS-09-C reads the annotations without modification) | this doc | SOS-09-A owns |
| SOS-09-B CMSIS-SVD register `<addressOffset>` chain | this repo, SOS-09-B | **compose** (SOS-09-C derives struct overlay field layout from B's address offsets; B's emission is upstream) | this doc | SOS-09-B owns |
| SOS-09-G `sos_mpu_region_t` C type | this repo, SOS-09-G | **mirror** (SOS-09-C exports `extern` declarations of values of this type; the type itself is SOS-09-G's) | this doc | SOS-09-G owns |
| SOS-09-G `sos_mpu_install()` runtime hook | this repo, SOS-09-G | **mirror** (SOS-09-C's MPU-symbol exports feed step 4 of `sos_mpu_install()`'s install loop; the hook itself is SOS-09-G's) | this doc | SOS-09-G owns |
| CMSIS-Core register-base-address conventions | ARM (CMSIS 5.9.0+) | **mirror** (SOS-09-C's `#define` shape mirrors the CMSIS-Core `*_BASE` / `*_ADDR` convention; ARM owns the convention) | this doc | none — CMSIS-Core owns |

Per INV-SOS-E, the row addition policy mirrors SOS-07 §7 and SOS-09 §8: **Specification Required** for adding new rows (phase-owner walkthrough), **Standards Action** for modifying an existing row's relationship value.

## 9. (Reserved — emission-walker contract; lives in implementation phase)

The per-walker emission shape (which iState walker visits which annotation, how SOS-09-B's address-offset assignment is consumed for struct layout, how the per-group sub-header is named and laid out on disk under `build/`) is the implementation phase's territory — out of scope for this concepts doc. The contract surface is normative in §5 and §6; the walker that satisfies it is informative until the implementation phase lands.

The forthcoming implementation lives at `tools/sos-codegen/c_hal_emit.py` (NEW — kept disjoint from the existing `transliterate_c.py` which owns the SOS-04 / SOS-05 ECMAScript→C transliterator surface for chart-script bodies).

## 10. Reconciliation decisions vs adjacent repo primitives

### vs. existing `tools/sos-codegen/transliterate_c.py`

The existing `transliterate_c.py` (mirror of `transliterate_rust.py`) is the SOS-04 / SOS-05 chart-script → C transliterator: it consumes the constrained ECMAScript subset that chart authors use inside `<onentry>` / `<onexit>` / `<transition>` script bodies and emits matching C code. It is NOT a register-map HAL emitter.

SOS-09-C's HAL emit path lives in a NEW sibling module `tools/sos-codegen/c_hal_emit.py` (forthcoming). The two modules consume different chart sub-surfaces (`transliterate_c.py` reads SCXML `<script>` bodies; `c_hal_emit.py` reads `other_attributes` `sos:`-prefixed keys per SOS-09-A) and emit different artifacts (`transliterate_c.py` emits `ports/m7-c/sos-m7-c/src/scripts.c`; `c_hal_emit.py` emits `build/c_hal/sos_<chart>.h` plus per-group sub-headers).

Reconciliation: `transliterate_c.py` is the **adapt** relationship in §4 — SOS-09-C reuses neither its parsing nor its emission logic; the two modules coexist as sibling tools under the same `tools/sos-codegen/` umbrella. No code is shared between them at v1; if a future refactor pulls out a common C-emission helper, that lives in a new shared module (e.g. `tools/sos-codegen/c_common.py`), with both modules consuming it.

### vs. SOS-09-A (chart annotation surface)

SOS-09-A is **upstream** of SOS-09-C. SOS-09-C reads `sos:`-prefixed keys from `other_attributes` per PCDN-SOS-09-001 amended 2026-05-25. The four required keys (`sos:id`, `sos:name`, `sos:kind`, `sos:dir`) plus the optional keys (`sos:zone`, `sos:width`, `sos:atomicity`, `sos:irq`, `sos:mutex`, `sos:bit_layout`) plus the SOS-09-B-specific keys (`sos:peripheral`, `sos:reset_value`, `sos:side_effect`, `sos:clear_on_read`, `sos:field_access`) plus the SOS-09-G-specific keys (`sos:mpu_attr`, chart-root `sos:mpu_background`) are the consumed surface. Per SOS-09-A's PCDN-SOS-09-A-003 ratification, `sos:name` (SV-identifier-shaped) is the symbol root SOS-09-C uses; `sos:id` (UUID) is identity-only.

### vs. SOS-09-B (CMSIS-SVD emission)

SOS-09-B is **upstream** of SOS-09-C. SOS-09-C's struct overlay layouts derive from SOS-09-B's `<register><addressOffset>` chain; SOS-09-C's `#define` register addresses derive from SOS-09-B's `<baseAddress>` + `<addressOffset>`. The two emit paths SHARE the chart annotation surface (per SOS-09-A) and SHARE the address-assignment policy (per SOS-09-B §5.3 PCDN-SOS-09-B-003 ratification — dense 4-byte alignment at v1). SOS-09-C does NOT re-derive offsets; it consumes them via SOS-09-B's emitted SVD (or equivalently via the in-memory chart model SOS-09-B operates on).

### vs. SOS-09-D (Rust HAL emission)

SOS-09-D is the **sibling** Rust HAL emitter. Per the umbrella §6 description, SOS-09-D aligns with svd2rust / chiptool RegisterBlock idiom. SOS-09-C and SOS-09-D consume the same chart annotation surface and produce parallel SW-side HALs in two languages; the two MUST agree on the channel-naming convention (both use `sos:name` as the symbol root per INV-S-MEM-C-5's Rust analog) and on the side-effect discrimination (Rust HAL emits e.g. `ClearOnRead<u32>` newtype wrappers; C HAL emits `*_consume_*` accessors — different syntactic forms, identical semantic discipline).

Reconciliation: SOS-09-C and SOS-09-D are file-disjoint emit paths (different source modules, different output trees: `build/c_hal/` vs `build/rust_hal/` or equivalent). Both consume SOS-09-A annotations and SOS-09-B offsets; neither modifies the other. Where the chart-author-facing semantic discipline overlaps (e.g. both must distinguish `consume` from `read`), the umbrella §5.3 side-effect specification is the shared authority; SOS-09-C and SOS-09-D each describe how that semantic discipline surfaces in their respective language idiom.

### vs. SOS-09-E (HDL register-file RTL)

SOS-09-E emits the HW-side register-file RTL; SOS-09-C emits the SW-side accessor headers. The two paths share the chart-declared register set per INV-S-MEM-1 (single-source register definition). They do NOT share emit code or output trees. SOS-09-C and SOS-09-E are file-disjoint; both consume SOS-09-A and SOS-09-B as upstream; both ratify independently.

### vs. SOS-09-F (membrane vectors)

SOS-09-F authors the cocotb-based co-sim membrane-vector framework. SOS-09-C-emitted headers are NOT consumed by SOS-09-F directly; the membrane vectors consume the SVD (per SOS-09-B) and the chart annotation (per SOS-09-A) and drive the SW side via a Python CPU-stub model (per umbrella PCDN-SOS-09-005). The C HAL is the production driver-author surface, not the test harness surface. Reconciliation: SOS-09-F and SOS-09-C are independent consumers of SOS-09-A + SOS-09-B; they do not directly couple at v1.

### vs. SOS-09-G (MPU configuration emission)

SOS-09-G owns the `sos_mpu_region_t` type and the `sos_mpu_install()` runtime hook. SOS-09-C exports `extern` declarations of `sos_mpu_<channel>_region` symbols (per §5.6) that SOS-09-G's emitted `sos_mpu_table[]` is populated from. The two paths share the chart-declared `sos:zone` annotation surface; SOS-09-C emits the per-channel symbol declarations consumed by `sos_mpu_install()` step 4 (per SOS-09-G §5.5, which reads chart-declared `sos:mpu_attr` per channel).

Reconciliation: SOS-09-C's MPU-symbol export is a **derive** relationship on top of SOS-09-G's owned `sos_mpu_region_t` type. The single point of definition is SOS-09-G's `sos_mpu_table[]`; SOS-09-C's declarations are pointers / references into that table. No type re-derivation; no definition duplication.

### vs. SOS-08-C / SOS-08-D test fixtures

Search at draft time: the existing `tools/sos-codegen/tests/fixtures/` directory contains chart fixtures (`.scxml`, `.json`) used by SOS-08-C/D and the various transliterator tests. **No pre-existing C HAL header fixtures** (`.h` files emitted from charts) exist; SOS-09-C's chart-driven emit will produce the first such artifacts in this repo when the emit path lands.

Should future work want to validate the SOS-09-C emitter against an externally-authored reference (e.g. STM32H747's vendor-published HAL headers as a structural reference), the externally-authored headers SHOULD live under `tools/sos-codegen/tests/fixtures/external_c_hal/` with a `README.md` declaring their provenance and the relationship axis (per SOS-07 §7 AuthorityRelationship) of `mirror` (read-only, not modified). They would not be normative inputs to the emitter — only test references.

### vs. SOS-08-WAVE3 conformance audit

SOS-08-WAVE3 ratified the cross-cutting doc-assertion module pattern (which `test_sos_09_b_concepts_doc.py` and `test_sos_09_g_concepts_doc.py` follow). SOS-09-C's per-doc test (`test_sos_09_c_concepts_doc.py`) follows the same pattern: pytest fixtures slicing the doc by section, per-§ assertions on required content, the `concepts_text` module-scope fixture for the doc body. No conformance-audit-specific work is required at the concepts-doc tier; the implementation phase (when `c_hal_emit.py` lands) will add the corresponding emit-path conformance assertions.

## 11. Non-goals

This sub-phase does NOT:

- **Author a full C runtime.** The SOS-04 / SOS-05 runtime (per their respective concept docs) owns CPU-internal peripheral access (NVIC, SCB, SysTick, MPU configuration registers themselves), startup code, linker scripts, and exception handlers. SOS-09-C emits the chart-declared external membrane HAL only.

- **Adopt MISRA-C.** MISRA-C is a specific safety-critical-coding subset of C with constraints (no recursion, no dynamic allocation, restricted control-flow, etc.) that go beyond the `-Wpedantic` cleanness gate of §6 INV-S-MEM-C-4. v1 SOS-09-C targets `-Wall -Wextra -Wpedantic -std=c11` clean; a future profile (e.g. SOS-09-C-MISRA when a safety-critical SOC enters the SOS bench substrate) MAY narrow the emission to MISRA-C-compliant headers, ratified as its own sub-phase.

- **Author dynamic-allocation primitives.** The C HAL emitted by SOS-09-C is all `static const` data + `static inline` (or `#define`) accessors; no allocation occurs. Charts requiring dynamic state at the C side use SOS-04 / SOS-05 mechanisms (e.g. statically-allocated `sos_datamodel` per `transliterate_c.py`), not SOS-09-C.

- **Author multithreading primitives on non-FreeRTOS targets at v1.** The `claim` / `release` accessors for `kind="shared"` channels wrap SOS-08-A's `sos_mutex`, which on the SOS bench substrate (Cortex-M7 disco-analyzer) composes with FreeRTOS via the SOS-04 runtime. Charts targeting a non-FreeRTOS C runtime (e.g. bare-metal scheduling under SOS-05) inherit SOS-05's mutex realisation; the C HAL surface is identical (the accessor names are deterministic per INV-S-MEM-C-5), only the runtime under the accessor changes.

- **Author Rust HAL emission.** That's SOS-09-D, which is a file-disjoint sibling sub-phase. The two language emissions are parallel, not nested.

- **Author the CMSIS-SVD emission.** That's SOS-09-B (upstream); SOS-09-C consumes B's emission for struct overlay layout.

- **Author the HDL register-file RTL.** That's SOS-09-E (sibling); SOS-09-C and SOS-09-E share the chart-declared register set as the single-source-of-truth but emit to different output trees.

- **Author the MPU configuration table itself.** That's SOS-09-G (sibling); SOS-09-C only declares `extern` references to SOS-09-G's per-channel `sos_mpu_<channel>_region` symbols.

- **Author membrane vector emission.** That's SOS-09-F (sibling); the C HAL is the production driver-author surface, not the test-harness surface.

- **Pin a specific C compiler version beyond gcc ≥ 10.x / clang ≥ 12.x.** The toolchain version range is the minimum to support C11 cleanly under `-Wpedantic`; specific patch-version pinning is operational, not normative.

## 12. Acceptance checklist

A conforming SOS-09-C ratification satisfies:

- (a) ⏸ PCDN-SOS-09-C-001 through 005 resolved (§15).
- (b) ⏸ The SOS-09-C concepts doc exists at `docs/concepts/SOS-09-C-CONCEPTS.md` with §0–§16 section presence and the per-§ normative content of §5 and §6.
- (c) ⏸ The forthcoming `tools/sos-codegen/c_hal_emit.py` emission walker exists and produces at least one chart channel's worth of C HAL header content covering: a `#define`-form register address; a `volatile`-qualified struct overlay typedef; at least one accessor of each emitted `<op>` shape applicable to the channel's kind (per §5.1); at least one `static const unsigned` field-shift constant.
- (d) ⏸ Accessor naming follows the `SOS_C_<channel>_<op>` convention deterministically from `sos:name` (per INV-S-MEM-C-5).
- (e) ⏸ `volatile` qualifier appears on every struct-overlay field (per §5.2 / INV-S-MEM-C-2 indirect).
- (f) ⏸ Side-effect-bearing accessors use `*_consume_*` / `*_fire_*` discriminating names per §5.3 (NOT plain `read` / `write`); a chart channel with `sos:clear_on_read="true"` emits `consume` and NOT `read` (per INV-S-MEM-C-2).
- (g) ⏸ The emitted headers pass `gcc -Wall -Wextra -Wpedantic -std=c11` AND `clang -Wall -Wextra -Wpedantic -std=c11` with exit 0 (per INV-S-MEM-C-4).
- (h) ⏸ For every chart channel with `sos:zone` annotation, an `extern const sos_mpu_region_t sos_mpu_<channel>_region;` declaration is emitted (per §5.6).
- (i) ⏸ Deterministic-from-`sos:name`: two emit runs against charts differing only in `sos:id` UUID values produce byte-identical accessor-symbol output (per INV-S-MEM-C-5).
- (j) ⏸ Cross-phase invariants INV-SOS-A through H cited correctly in the SOS-09-C emit-path source; cross-sub-phase invariants INV-S-MEM-1 through 6 cited correctly per sub-phase; INV-S-MEM-C-1 through 5 declared in this doc's §6.

(a) and (b) are the ratification gates; (c)–(j) are implementation gates that flip from ⏸ to ✅ as the implementation lands.

A conforming SOS-09-C ratification *without* the MPU symbol export (i.e. charts whose every channel has `sos:zone="unprivileged"` or omits `sos:zone` entirely and relies on the background region per SOS-09-G PCDN-SOS-09-G-002) satisfies (a)–(g) and (i)–(j) with reduced (h). This second-tier conformance level supports first-target ECP5 bring-up demos that exercise only the plain HAL surface, deferring protection-zone coverage to subsequent bring-up rounds.

## 13. Files cited

| Path | Role |
|---|---|
| `docs/concepts/SOS-09-CONCEPTS.md` | Umbrella; this sub-phase's parent. |
| `docs/concepts/SOS-09-A-CONCEPTS.md` | Chart annotation surface; SOS-09-C reads `sos:`-prefixed keys from there. |
| `docs/concepts/SOS-09-B-CONCEPTS.md` | CMSIS-SVD emission; SOS-09-C derives struct overlay layout from B's `<addressOffset>` chain. |
| `docs/concepts/SOS-09-D-CONCEPTS.md` | Rust HAL emission; sibling sub-phase. |
| `docs/concepts/SOS-09-E-CONCEPTS.md` | HDL register-file RTL; sibling sub-phase. |
| `docs/concepts/SOS-09-F-CONCEPTS.md` | Membrane vectors; sibling sub-phase. |
| `docs/concepts/SOS-09-G-CONCEPTS.md` | MPU configuration emission; SOS-09-C exports `extern` declarations of `sos_mpu_<channel>_region` symbols whose definitions live in G. |
| `docs/concepts/SOS-07-CONCEPTS.md` | Cross-phase invariants INV-SOS-A through H; AuthorityRelationship matrix. Cited, not redefined. |
| `docs/concepts/SOS-08-A-CONCEPTS.md` | `sos_mutex` primitive consumed by `claim` / `release` accessors. |
| `docs/concepts/SOS-08-WAVE3-CONFORMANCE.md` | Wave-3 conformance audit; the per-doc-assertion test pattern this sub-phase's test mirrors. |
| `docs/concepts/SOS-04-CONCEPTS.md` | M7 Rust port; CPU-internal peripheral access boundary (out of SOS-09-C scope). |
| `docs/concepts/SOS-05-CONCEPTS.md` | M7 C port; the `-std=c11` + `-Wall -Wextra -Wpedantic -Werror` discipline precedent. |
| `tools/sos-codegen/transliterate_c.py` | Existing ECMAScript→C transliterator (SOS-04 / SOS-05 chart-script bodies); file-disjoint from SOS-09-C. |
| `tools/sos-codegen/c_hal_emit.py` | Forthcoming SOS-09-C emit-path module; NEW sibling of `transliterate_c.py`. |
| `tools/sos-codegen/tests/test_sos_09_c_concepts_doc.py` | Per-doc-assertion test module. |
| `build/c_hal/sos_<chart>.h` | Forthcoming emitted umbrella header (per INV-S-MEM-2 lives under `build/`, not tracked source). |
| `build/c_hal/sos_<chart>__<group>.h` | Forthcoming emitted per-group sub-header. |
| Parent `CLAUDE.md` | Spec-Before-Code Planning Discipline; Phase document shape. |

## 14. Unblocks

This sub-phase's ratification (after PCDN walkthrough) unblocks:

- **SOS-09 umbrella acceptance gate (c)** — a chart channel emits the C HAL header alongside the SVD, Rust HAL, RTL, MPU table, and membrane vectors as the worked-example six-artifact emission.
- **SOS-09-D Rust HAL emission** — the side-effect-discrimination convention (`consume` / `fire` / `claim` / `release`) freezes at the SOS-09-C tier; SOS-09-D ratifies its language-specific analog (newtype wrappers) against the same chart-annotation surface.
- **Firmware driver authoring** against chart-declared register surfaces; drivers gain a stable, side-effect-aware, MPU-aware C API without re-deriving headers from register-map PDFs.
- **SOS-04 / SOS-05 port integration** — the runtime gains a single chart-rooted source for membrane-register access, replacing per-port hand-rolled register-access patterns for chart-declared channels (per §10 vs SOS-04 reconciliation).
- **The first end-to-end chart-driven SoC bring-up demo on the C side** — chart → CMSIS-SVD + C HAL headers → driver compiled with `gcc -std=c11 -Wpedantic` → bench-validated against the RTL emission via the membrane vectors.
- The "driver cannot drift from register-map" claim made concrete: the C HAL header is the same chart edit away from regeneration as the SVD, the RTL, and the MPU table.

## 15. Pending Concept Decision Notices (PCDNs)

These open questions move this doc from 🟡 drafted to 🟢 ratified. PCDN-SOS-09-C-* identifiers are stable per parent CLAUDE.md "Errata Open Question" naming convention (analogous shape applies — these are PCDNs at the concepts-doc level).

- **PCDN-SOS-09-C-001 — Bitfield struct overlays: C bitfields or explicit shift-and-mask macros?** 🟢 **RATIFIED 2026-05-26 — accepted option (b)** explicit shift-and-mask. Options: (a) C bitfields (compiler-dependent layout — gcc and clang agree on ARM ABI but the C11 standard leaves the layout implementation-defined per ISO/IEC 9899:2011 §6.7.2.1); (b) explicit shift-and-mask via `static const unsigned` constants + `static inline` accessor functions reading / writing the parent register word (per §5.5 emission policy; UB-free; portable across every conforming C11 compiler). **Recommendation**: option (b) explicit shift-and-mask. The compiler-dependent layout of C bitfields is a long-standing portability hazard; explicit shift-and-mask emission is the SOS-08 HDL discipline mirror (the RTL emission per SOS-09-E uses explicit bit-slice notation, never compiler-inferred packing). Frozen-enumeration registration policy: Standards Action — the bit-field emission shape is part of the cross-phase C HAL contract (drivers / lint passes assume the explicit form).

- **PCDN-SOS-09-C-002 — `volatile` qualifier placement: per-field on the struct typedef, or per-access cast?** 🟢 **RATIFIED 2026-05-26 — accepted option (a)** per-field `volatile` on the struct typedef. Options: (a) per-field on the typedef (e.g. `volatile uint32_t foo;` in the struct definition); (b) per-access cast (e.g. `*(volatile uint32_t *)&block->foo`). **Recommendation**: option (a) per-field on the typedef. The per-field form distributes the `volatile` discipline at the type level (where omission is a compile error on the type definition itself); the per-access form distributes it across every call site (where omission is silent). The per-field form is also what CMSIS-Core uses; SOS-09-C mirrors that convention. Frozen-enumeration registration policy: Standards Action — the placement policy is a cross-phase memory-model contract; demoting to per-access invalidates the memory-model assumption every caller makes.

- **PCDN-SOS-09-C-003 — Return semantics for `*_consume_*` accessors: return the cleared value or `void`?** 🟢 **RATIFIED 2026-05-26 — accepted option (a)** return the cleared value. Options: (a) return the cleared value (typical use case — driver reads IRQ status, clears it as a side effect, branches on the read value); (b) return `void` (the read-and-clear is a pure side-effect operation; the caller who wants the value reads first via a separate non-clearing accessor). **Recommendation**: option (a) return the cleared value. The vast majority of `clear-on-read` register use cases need the value (IRQ status registers, condition flags, error counters); forcing the caller to do an additional non-clearing read defeats the optimization and adds round-trip cycles on the bus. Frozen-enumeration registration policy: Specification Required — the return-shape choice is local to the C HAL contract; if a future safety-critical profile (e.g. MISRA-C variant) requires `void` returns, that profile MAY override locally.

- **PCDN-SOS-09-C-004 — Umbrella header: transitive include of all sub-headers, or explicit per-group include?** 🟢 **RATIFIED 2026-05-26 — accepted option (a)** umbrella transitive include. Options: (a) transitive include — the umbrella `sos_<chart>.h` `#include`s every per-group sub-header (chart-authors / driver-authors include only the umbrella; include-time overhead is the cost); (b) no transitive include — the umbrella declares only chart-wide constants (chart version hash, base addresses table); each driver `#include`s the per-group sub-header it needs explicitly (finer include control; chart-author authoring burden). **Recommendation**: option (a) transitive include. Chart-author ergonomics (a single `#include "sos_<chart>.h"` covers the chart) outweighs include-time minimality on a chart with N groups; modern C compilers fold `#ifndef` header guards efficiently, so the include-time cost is dominated by the time to open each file (small for charts with < 100 groups). Frozen-enumeration registration policy: Specification Required — the header layout convention is local to this sub-phase; a future migration to per-group-only includes MAY happen as a phase-owner walkthrough update.

- **PCDN-SOS-09-C-005 — Accessor emission form: `static inline` C11 functions, or preprocessor `#define` macros?** 🟢 **RATIFIED 2026-05-26 — accepted option (a)** `static inline` C11 functions. Options: (a) `static inline` functions (typed; debugger-visible; respects `-Wconversion`; requires C11 `-std=c11` mode); (b) preprocessor `#define` macros (untyped; not debugger-visible; works in pre-C99 compilers; requires per-macro `do { ... } while (0)` wrapping for statement-form macros). **Recommendation**: option (a) `static inline`. The C11 `-std=c11` mode is already the ratified toolchain gate per §6 INV-S-MEM-C-4; the typed form catches narrowing / overflow at the accessor boundary (where preprocessor macros silently pass through); the debugger-visibility is the load-bearing operational property for bench bring-up. The `static inline` form also composes cleanly with the per-field `volatile` typedef per §5.2 — the inline function dereferences the `volatile`-qualified struct field, so the memory-model discipline is preserved at the call site without per-access casts. Frozen-enumeration registration policy: Specification Required — the emission form is local to this sub-phase's contract surface; a future obscure-toolchain target MAY opt into the `#define` form, ratified as a phase-owner walkthrough.

## 16. Change log

### 2026-05-26 — Ratified (Ira)

All five PCDNs ratified in the 2026-05-26 walkthrough session; status banner promoted from 🟡 DRAFT to 🟢 RATIFIED 2026-05-26.

- **PCDN-SOS-09-C-001** — 🟢 RATIFIED 2026-05-26 — accepted option (b) explicit shift-and-mask. The compiler-dependent layout of C bitfields is a long-standing portability hazard; explicit shift-and-mask emission mirrors the SOS-09-E HDL discipline (explicit bit-slice notation, never compiler-inferred packing).
- **PCDN-SOS-09-C-002** — 🟢 RATIFIED 2026-05-26 — accepted option (a) per-field `volatile` on the struct typedef. The per-field form distributes the `volatile` discipline at the type level (where omission is a compile error on the type definition itself); per-access cast distributes it across every call site where omission is silent. CMSIS-Core convention.
- **PCDN-SOS-09-C-003** — 🟢 RATIFIED 2026-05-26 — accepted option (a) return the cleared value. The vast majority of `clear-on-read` register use cases need the value (IRQ status registers, condition flags, error counters); forcing a separate non-clearing read defeats the optimization and adds bus round-trips.
- **PCDN-SOS-09-C-004** — 🟢 RATIFIED 2026-05-26 — accepted option (a) umbrella transitive include. Chart-author ergonomics (a single `#include "sos_<chart>.h"` covers the chart) outweighs include-time minimality; modern C compilers fold `#ifndef` header guards efficiently.
- **PCDN-SOS-09-C-005** — 🟢 RATIFIED 2026-05-26 — accepted option (a) `static inline` C11 functions. The C11 `-std=c11` mode is already the ratified toolchain gate per §6 INV-S-MEM-C-4; the typed form catches narrowing / overflow at the accessor boundary; debugger-visibility is the load-bearing operational property for bench bring-up.

All five accepted as recommended; structural translation regime — no spec amendments triggered. No §5 / §6 normative-content edits required; the recommendations were already encoded in the draft's frozen-decisions text as the load-bearing recommendation per PCDN.

### 2026-05-26 — Initial draft (Ira)

- Authored `SOS-09-C-CONCEPTS.md` as the C HAL header emission sub-phase under the SOS-09 umbrella.
- §3 canonical glossary: terms `register block`, `accessor macro family`, `side-effect-bearing accessor`, `claim/release accessor`, `umbrella header`, `per-group sub-header`, `field shift / mask constant`, `MPU-region symbol`, `deterministic-from-sos:name`.
- §4 source-of-truth map: chart annotation surface (mirror from SOS-09-A); register `<addressOffset>` chain (compose from SOS-09-B); side-effect annotation source (mirror from SOS-09-A + SOS-09-B); accessor naming convention + volatile policy + side-effect annotation form + header layout + compile-time constants + MPU-region symbol export (this doc, own); MPU types (mirror from SOS-09-G); existing `transliterate_c.py` (adapt — sibling tool, no code share).
- §5 frozen decisions: accessor-macro naming `SOS_C_<channel>_<op>` with `op ∈ {read, write, consume, fire, claim, release}` (§5.1); per-field volatile on struct typedef (§5.2); side-effect → `*_consume_*` / `*_fire_*` accessor-name discrimination (§5.3); umbrella + per-group two-tier header layout with transitive include (§5.4); `#define` for addresses + `static const unsigned` for shifts/masks (§5.5); per-channel `extern const sos_mpu_region_t sos_mpu_<channel>_region;` declarations (§5.6).
- §6 cross-sub-phase invariants INV-S-MEM-C-1 through INV-S-MEM-C-5: every register field accessed only through emitted accessors; `clear-on-read` registers never accessed via plain `read_*`; `command`-`kind` channels emit only `fire`/`claim`/`release` not `read`; every emitted header is `gcc -Wall -Wextra -Wpedantic -std=c11` clean; accessor symbol names deterministic from `sos:name` not `sos:id`.
- §7 enumeration policies catalog mapping each §5 / §6 decision to Standards Action or Specification Required per parent CLAUDE.md registration-policy discipline.
- §8 standards integration matrix additions: C11 (ISO/IEC 9899:2011) derive; gcc and clang `-Wpedantic` derive; SOS-09-A mirror; SOS-09-B compose; SOS-09-G `sos_mpu_region_t` + `sos_mpu_install()` mirror; CMSIS-Core register-base-address conventions mirror.
- §10 reconciliation vs existing `transliterate_c.py` (adapt — file-disjoint sibling tool), SOS-09-A / B / D / E / F / G sub-phases, SOS-08-C/D test fixtures (none found), SOS-08-WAVE3 conformance audit pattern.
- §11 non-goals: no full C runtime; no MISRA-C v1; no dynamic allocation; no non-FreeRTOS multithreading v1; no Rust / SVD / RTL / MPU / vector emission (siblings).
- §12 acceptance checklist gates (a)–(j) with reduced conformance level for charts without `sos:zone` annotations.
- §15 five PCDNs raised: bitfield struct overlays (C bitfields vs explicit shift-and-mask); volatile qualifier placement (per-field on typedef vs per-access cast); `*_consume_*` return semantics (cleared value vs void); umbrella transitive include vs explicit per-group; `static inline` C11 functions vs preprocessor `#define` macros.

Status: 🟡 **DRAFT 2026-05-26 — awaiting PCDN walkthrough** (initial draft entry retained for institutional memory; superseded by the 🟢 RATIFIED 2026-05-26 entry above).
