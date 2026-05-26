# SOS-09-D — Rust HAL trait emission

**Status:** 🟢 **RATIFIED 2026-05-26.**

## 0. Authority policy

This phase doc is the **Rust HAL trait emission** sub-phase under the SOS-09 umbrella (`SOS-09-CONCEPTS.md`, ratified 2026-05-23, amended 2026-05-25 for PCDN-SOS-09-001). The umbrella's §5.5 freezes the artifact priority as **CMSIS-SVD primary, SystemRDL secondary**, and the umbrella's §6 names this sub-phase as the codegen path producing Rust HAL traits + newtype wrappers + `RegisterBlock` structs from chart annotations + the validated CMSIS-SVD artifact emitted by SOS-09-B. SOS-09-D consumes the umbrella's frozen decisions and the upstream SOS-09-A annotation surface + SOS-09-B SVD artifact as load-bearing input.

Per the parent CLAUDE.md "Spec-Before-Code Planning Discipline / Phase document shape":

- **Normative** sections of this doc: §3 glossary, §4 source-of-truth map, §5 frozen decisions, §6 invariants (INV-S-MEM-D-*), §7 enumeration policies, §8 standards integration matrix additions, §9 acceptance gates, §12 acceptance checklist.
- **Informative** sections: §1 purpose, §2 problem statement, §10 reconciliation, §11 non-goals, §13 files cited, §14 unblocks, §15 PCDNs (filed open), §16 change log.
- All keywords MUST, MUST NOT, SHALL, SHOULD, SHOULD NOT, MAY are interpreted per RFC 2119 / RFC 8174 when capitalised.

This doc cites `SOS-07-CONCEPTS.md` §6 for the cross-phase invariants INV-SOS-A through H and §7 for the AuthorityRelationship matrix; it does not re-derive them. It cites `SOS-09-CONCEPTS.md` §5 for the frozen channel-category enum, §5.2 for the channel → membrane-primitive mapping, §5.5 for the artifact priority, §7 for the cross-sub-phase invariants INV-S-MEM-1 through 6, and §8 for the standards integration matrix rows naming `svd2rust` and `chiptool` as upstream-ecosystem comparands. It cites `SOS-09-A-CONCEPTS.md` §5 for the canonical 10-key `sos:`-prefixed annotation surface (notably `sos:id` as the RFC 4122 UUID identity handle and `sos:name` as the SV-identifier emission handle, per PCDN-SOS-09-A-003 ratification 2026-05-25). It cites `SOS-09-B-CONCEPTS.md` §5 for the CMSIS-SVD 1.3.x schema pin and the access-mapping derivation table that SOS-09-D round-trips through `svd2rust --strict`. It cites `SOS-09-G-CONCEPTS.md` §5.5 for the `sos_mpu_install()` runtime hook shape, which SOS-09-D's MPU-region constant export feeds (per PCDN-SOS-09-G-001 / G-002 alignment).

Per PCDN-SOS-09-001 amended 2026-05-25, chart channel annotations are read from iState's `other_attributes` extension surface using `sos:`-prefixed string keys WITHIN the `other_attributes` JSON. This is a JSON-key string prefix, NOT an XML namespace prefix. SOS-09-D's emission consumes the SOS-09-B-validated SVD (which already honours this convention) and MUST NOT introduce any `xmlns:sos` declaration into the emitted Rust crate. Emitted Rust symbol names derive from `sos:name` per INV-S-MEM-D-6; `sos:id` (the UUID) appears only in `// SAFETY:` discharge comments and doc-comment attribution, never as a Rust identifier.

The relevant upstream-ecosystem patterns are **`svd2rust`** (Rust Embedded WG; the canonical SVD→Rust toolchain producing `RegisterBlock` structs + accessor methods + read/write proxy types) and **`chiptool`** (Embassy-adjacent; a modern alternative with first-class async + type-state register accessors). SOS-09-D emits in the svd2rust-compatible shape by design, so a chart author MAY pipe the SOS-09-B-emitted SVD through external `svd2rust` and obtain a structurally-similar crate; SOS-09-D's value-add over raw svd2rust output is the chart-annotation-driven newtype wrapper family (§5.2), the type-state pattern for `kind="shared"` channels (§5.3), and the MPU-region constant export (§5.6) that downstream `sos_mpu_install()` consumes.

## 1. Purpose

To freeze the Rust HAL trait emission contract: the `RegisterBlock` struct shape and address-layout policy, the newtype wrapper family carrying chart-declared semantics in the type system, the type-state pattern that compile-time-enforces `kind="shared"` channel claim/release, the `#![no_std]` + optional `alloc` policy that lets the emitted crate target bare-metal `cortex-m` + RTIC/embassy environments, the `*_unchecked` accessor emission policy (per INV-SOS-G chart-bounds discharge), and the MPU-region constant export that feeds the Rust-side `sos_mpu_install()` runtime hook ratified in SOS-09-G.

Without this freeze, the Rust HAL emit path cannot produce a stable artifact: every emission would re-litigate which inner cell type holds the volatile field (`vcell::VolatileCell` vs `cortex_m::interrupt::Mutex` vs raw `core::cell::UnsafeCell`), which newtype carries clear-on-read semantics, whether `Shared<T>::claim()` returns an `Option` / `Result` / panicking accessor, and whether the emitted crate transitively depends on the `cortex-m` crate or stays target-agnostic. Downstream consumers (SOS-09-F membrane vectors in Rust; SOS-09-G's `sos_mpu_install()` linking the emitted MPU constants; SOS-04 M7 Rust port's runtime that hosts the chart-emitted accessors) cannot author against an unstable Rust HAL shape.

## 2. Problem statement

The umbrella's §2 names the "register-map PDF that lies" as the canonical hardware/software co-design failure mode and prescribes "derive every artifact from the chart annotation". The CMSIS-SVD artifact (SOS-09-B) is the documentary register map; the Rust HAL emission (this sub-phase) is the *typed access surface* a Rust driver actually calls. Four concrete failure patterns inside the Rust-HAL surface motivate this sub-phase's freeze:

1. **Double-clear-on-read.** A register with read-clears-bits semantics, accessed via raw `core::ptr::read_volatile`, is silently re-cleared on every read. The first read returns "what was pending"; the second read returns 0 even though the chart's intent was "consume once". Without a newtype that consumes `self` on read, the compiler cannot catch double-read as the bug it is. This pattern bit disco-analyzer's IRQ-pending readback (bench-9p..9u: `feedback_b1_left_codec_wedged` and adjacent telemetry showed read-as-side-effect ambiguity wedging diagnosis).

2. **Accidental command/status mismatch.** A `kind="status"` channel exposes `read()`; a `kind="command"` channel exposes `fire(value)`. With raw pointer access both are `volatile_read` / `volatile_write` at the call site, and the compiler cannot distinguish "I wrote to a status register" (a no-op or a buggy clear) from "I wrote to a command register" (the intended HW trigger). The newtype family (§5.2) emits `Status<T>` with only `read()`/`notified()` and `Command<T>` with only `fire(value)` — the two are not assignment-compatible, and a driver author cannot accidentally use one where the other was intended.

3. **Unsynchronised access to shared channels.** A `kind="shared"` channel is a mutex-protected typed region (per umbrella §5.2). With raw pointer access, "claim the mutex, read the region, release the mutex" is three call-site steps any of which a driver author MAY skip. The type-state pattern (§5.3) makes the typed region accessible *only* through a `Claimed<'_, T>` Drop-guard returned by `claim()`; the borrow checker rejects any path that touches the region without holding the guard. The mutex/claim contract becomes compile-time-enforced.

4. **`unsafe` lint-noise erodes safety review.** A bare-metal Rust crate that wraps every register access in `unsafe { volatile_read(...) }` blocks accumulates so much `unsafe` that reviewers stop reading the SAFETY comments. The newtype family confines `unsafe` to the emitted accessor implementations (auditable once at codegen) and exposes a fully-safe surface to drivers (only the explicitly-marked `*_unchecked` accessors, per INV-SOS-G chart-bounds discharge per §5.5, carry visible `unsafe`). The signal-to-noise ratio of remaining `unsafe` is reviewable.

INV-SOS-G's verified-codegen position (the chart-bounds analysis may discharge runtime safety obligations) is the mechanism that justifies emitting `*_unchecked` accessors: the safety obligation is dispatched to the chart, named in the SAFETY comment, and the runtime check is elided. Without a stable Rust HAL shape, the discharge claim cannot be audited at the call site — which violates INV-SOS-G's auditability requirement.

## 3. Canonical glossary

Terms NEW within SOS-09-D. Terms `channel`, `kind`, `dir`, `status`, `command`, `queue`, `shared`, `atomicity`, `protection zone`, `side-effect-on-write`, `clear-on-read` cite `SOS-09-CONCEPTS.md` §3 (used without modification). Terms `CMSIS-SVD`, `SVD register`, `SVD field`, `SVD access`, `svd2rust strict mode` cite `SOS-09-B-CONCEPTS.md` §3 (used without modification). Terms `sos:id`, `sos:name`, `required attribute key`, `SV identifier` cite `SOS-09-A-CONCEPTS.md` §3 (used without modification).

Authority relationships per §8.

| Term | Definition |
|---|---|
| **`RegisterBlock`** | A `#[repr(C)]` struct emitted by SOS-09-D, with one field per chart-declared register in the peripheral group. Field types are SOS-09-D newtype wrappers (§5.2) parameterised by the inner cell type (per PCDN-SOS-09-D-001). Address layout matches the SVD-emitted `<addressOffset>` chain bit-for-bit per INV-S-MEM-D-5. The svd2rust-compatible idiom (relationship: `derive` per §8) — a Rust driver imports `peripheral::RegisterBlock` and accesses registers as `block.<sos:name>.read()` / `block.<sos:name>.fire(value)` / etc. |
| **newtype wrapper** | A zero-sized or `#[repr(transparent)]` Rust type that wraps a `vcell::VolatileCell<T>` (or equivalent — see PCDN-SOS-09-D-001) and exposes a chart-semantics-specific accessor API. The family is `Status<T>`, `Command<T>`, `Queue<T>`, `Shared<T>`, `ClearOnRead<T>`, `FireOnWrite<T>` (§5.2). Each wrapper enforces its chart-declared access discipline in the type system: a `Status<T>` has no `fire`, a `Command<T>` has no `read`, a `ClearOnRead<T>::read` consumes `self`. |
| **type-state pattern** | The compile-time idiom in which a value's type encodes its lifecycle state, so the borrow checker enforces correct sequencing. Owned by SOS-09-D for the `Shared<T>` channel realisation (§5.3): `Shared<T>::claim()` returns `Claimed<'_, T>`; the typed region is accessible only through methods on `Claimed`; releasing the mutex happens in `Claimed::drop`. The driver cannot access the region without claiming, and cannot forget to release. |
| **`ClearOnRead<T>`** | The newtype wrapper for registers carrying chart-declared `sos:clear_on_read` semantics. `ClearOnRead<T>::read(self) -> T` consumes `self`; a second read is a compile error, not a lint warning. The wrapper is `#[must_use]` to make ignored reads a compile-time diagnostic. Owned by SOS-09-D; does not exist in the repo yet. |
| **`FireOnWrite<T>`** | The newtype wrapper for command-class channels with chart-declared "write triggers HW action beyond value update" semantics. `FireOnWrite<T>::fire(&mut self, value: T)` is the only public mutator; there is no `read`. Owned by SOS-09-D; does not exist in the repo yet. |
| **`Status<T>`** | The newtype wrapper for `kind="status"` `dir="hw→sw"` channels. Read-only by construction (`fn read(&self) -> T`); offers `fn notified(&self) -> bool` for IRQ-watching channels with `sos:irq`. Owned by SOS-09-D. |
| **`Command<T>`** | The newtype wrapper for `kind="command"` `dir="sw→hw"` channels. Write-only by construction (`fn fire(&mut self, value: T)`); no `read` accessor. Owned by SOS-09-D. |
| **`Queue<T>`** | The newtype wrapper for `kind="queue"` `dir="hw↔sw"` channels. Exposes `push` / `pop` over the DPRAM-backed ring (per umbrella §5.2 channel-to-primitive mapping). Owned by SOS-09-D. |
| **`Shared<T>`** | The newtype wrapper for `kind="shared"` `dir="hw↔sw"` channels. Exposes `claim()` returning a `Claimed<'_, T>` Drop-guard (per §5.3 type-state pattern); the inner typed region is accessible only through the guard. Owned by SOS-09-D. |
| **`Claimed<'_, T>`** | The Drop-guard returned by `Shared<T>::claim()`; carries the typed region as `&'_ mut T` (or `&'_ T` per the chart-declared `dir`). Releases the underlying `sos_mutex` in `Drop`. Owned by SOS-09-D. |
| **`ContentionError`** | The error type returned by `Shared<T>::claim()` when the mutex is held elsewhere. Default shape (per PCDN-SOS-09-D-003 recommendation): `enum ContentionError { LockHeldElsewhere }`. Owned by SOS-09-D. |
| **claim/release token type** | Alternative name for `Claimed<'_, T>`; emphasises the token nature of the value (its existence IS the claim; its drop IS the release). |
| **`*_unchecked` accessor** | An accessor variant emitted on a `Status` / `Command` / `Queue` / `Shared` newtype when chart-bounds analysis (per INV-SOS-G) proves a known-state invariant. The `*_unchecked` form is `unsafe fn` (per PCDN-SOS-09-D-005); the `// SAFETY:` comment names the discharging chart invariant. Owned by SOS-09-D. |
| **`#![no_std]` policy** | The emitted HAL crate is `#![no_std]` by default; references no `std::` symbols. Optional `alloc` is gated behind a Cargo feature `alloc` for environments with a global allocator (e.g. `rtic-monotonics` setups). Owned by SOS-09-D (§5.4). |
| **MPU-region constant export** | A `pub const SOS_MPU_<CHANNEL_UPPER>_REGION: sos_mpu_region_t = ...;` Rust declaration emitted alongside the `RegisterBlock`, consumed by SOS-09-G's `sos_mpu_install()` runtime hook. One constant per chart channel with a chart-declared `sos:zone` / `sos:mpu_attr`. Owned by SOS-09-D (§5.6); the `sos_mpu_region_t` type is defined in `SOS-09-G-CONCEPTS.md` §5.3 (used without modification). |
| **target-agnostic mode** | The emission mode (gated by absence of the `cortex_m` Cargo feature per PCDN-SOS-09-D-004) producing a Rust crate with no `cortex-m` crate dependency. Useful for host-side tests, dual-target (Cortex-M + RISC-V) HAL emission, and Miri-based verification of `Shared<T>` type-state logic. Owned by SOS-09-D. |

## 4. Source-of-truth map

| Concept | Authority | Local relationship |
|---|---|---|
| Rust HAL emission template | **this doc** (§5) | **own** — SOS-09-D authors the emission shape; svd2rust is a comparand, not the owner. |
| `RegisterBlock` struct shape (`#[repr(C)]`, `vcell::VolatileCell<T>` fields, address layout from SVD `<addressOffset>`) | **this doc** (§5.1) | **own** — SOS-09-D emits this; svd2rust-compatible by convention. |
| Newtype wrapper family (`Status` / `Command` / `Queue` / `Shared` / `ClearOnRead` / `FireOnWrite`) | **this doc** (§5.2) | **own** — SOS-09-D authors the family; the semantics derive from chart-annotation vocabulary that umbrella §5.1 owns. |
| Type-state pattern for `kind="shared"` (`Shared<T>` / `Claimed<'_, T>` / `ContentionError`) | **this doc** (§5.3) | **own** — SOS-09-D authors the pattern; the chart-level `shared` channel realisation cites umbrella §5.2. |
| `#![no_std]` + optional `alloc` policy | **this doc** (§5.4) | **own** — SOS-09-D authors the Cargo feature shape; the `alloc` crate is upstream Rust stdlib. |
| `*_unchecked` accessor emission policy (chart-bounds discharge per INV-SOS-G) | **this doc** (§5.5) | **own** — SOS-09-D authors the emission rule; INV-SOS-G is the discharging invariant SOS-07 owns. |
| MPU-region constant export shape (`pub const SOS_MPU_<CHANNEL>_REGION: sos_mpu_region_t = ...;`) | **this doc** (§5.6) | **own** — SOS-09-D authors the export; `sos_mpu_region_t` is SOS-09-G's authority. |
| `vcell::VolatileCell<T>` inner cell type | open project (`vcell` crate; Rust Embedded WG) | **derive** — SOS-09-D emits fields of this type; svd2rust convention. |
| `cortex-m` crate dependency (gated behind `cortex_m` Cargo feature, per PCDN-SOS-09-D-004) | open project (Rust Embedded WG) | **derive** — when the feature is on, SOS-09-D emits code that uses `cortex_m::interrupt` primitives. |
| `svd2rust` upstream behavior (RegisterBlock shape, accessor method idiom) | open project (Rust Embedded WG) | **derive** — SOS-09-D's emission is svd2rust-compatible so external svd2rust may be substituted by a chart author. |
| `chiptool` upstream behavior (alternative SVD→Rust toolchain; Embassy-adjacent) | open project (Embassy WG) | **derive** — SOS-09-D's emission is structurally compatible with `chiptool`-style consumption; relationship documented in §10. |
| Chart `other_attributes` annotation schema | `SOS-09-A-CONCEPTS.md` §5 | **mirror** — SOS-09-D reads `sos:`-prefixed keys per PCDN-SOS-09-001 amended 2026-05-25; SOS-09-A owns the schema. |
| Channel category enum (`kind ∈ {status, command, queue, shared}`) | `SOS-09-CONCEPTS.md` §5.1 | **mirror** — drives the newtype-wrapper-family choice in §5.2. |
| Channel → membrane-primitive mapping | `SOS-09-CONCEPTS.md` §5.2 | **mirror**. |
| CMSIS-SVD 1.3.x schema + access-mapping table | `SOS-09-B-CONCEPTS.md` §5.3 | **mirror** — SOS-09-D consumes the validated SVD via `svd2rust --strict`. |
| `sos_mpu_region_t` type + `sos_mpu_install()` hook | `SOS-09-G-CONCEPTS.md` §5.3, §5.5 | **mirror** — SOS-09-D emits `pub const SOS_MPU_<CHANNEL>_REGION: sos_mpu_region_t = ...;` declarations consumed by `sos_mpu_install()`. |
| Cross-sub-phase invariants INV-S-MEM-1 through 6 | `SOS-09-CONCEPTS.md` §7 | cited, not redefined. |
| Cross-phase invariants INV-SOS-A through H | `SOS-07-CONCEPTS.md` §6 | cited, not redefined. |
| Rust HAL emission walker script | `tools/sos-codegen/transliterate_rust.py` (existing; extended for SOS-09-D) | local; SOS-09-D owns the SOS-09-channel-emit subset of this walker. |
| Emitted Rust HAL crate (per chart) | `build/rust-hal/<chart_id>/` (forthcoming) | local; per INV-S-MEM-2 lives under `build/`, not tracked source. |

## 5. Frozen decisions

### 5.1 `RegisterBlock` shape

One `#[repr(C)]` struct per peripheral group (the same channel-grouping policy SOS-09-B's `<peripheral>` emission uses; per SOS-09-B PCDN-SOS-09-B-002 ratified 2026-05-25, the chart-author `sos:peripheral` hint takes precedence with parent-state-hierarchy fallback). The struct carries one field per chart-declared channel in the group; the field type is the SOS-09-D newtype wrapper (§5.2) that matches the channel's `sos:kind`. The inner cell type that the wrapper holds is `vcell::VolatileCell<T>` by default (per PCDN-SOS-09-D-001 recommendation, matching the svd2rust convention).

Address layout MUST match the SVD-emitted `<addressOffset>` chain bit-for-bit (per INV-S-MEM-D-5). The emitter emits each field with explicit `#[repr(C)]` ordering and inserts padding `_reservedN: [u8; N]` fields where SVD-declared offsets imply gaps. The `RegisterBlock` is `#[non_exhaustive]` to allow chart edits to add channels without breaking external consumers (the chart's content-hash version per SOS-09-B §5.2 `<version>` element provides the audit trail).

A driver obtains a `&'static RegisterBlock` via the per-target `Peripheral::ptr()` accessor (svd2rust-compatible idiom). The `Peripheral::ptr()` accessor is `unsafe` (it discharges the assumption that the SVD `<baseAddress>` matches the silicon); the chart-bounds analysis cannot reach into per-target SoC integration to discharge that, so the `unsafe` stays at the boundary.

Example sketch (informative — not normative; the normative emission shape is the codegen template at `tools/sos-codegen/transliterate_rust.py`):

```rust
#[repr(C)]
#[non_exhaustive]
pub struct RegisterBlock {
    pub status_irq: Status<u32>,
    _reserved0: [u8; 4],
    pub cmd_start: Command<u32>,
    pub shared_buf: Shared<SharedBuf>,
}
```

Frozen-enumeration registration policy: **Standards Action** (the struct shape encodes the SVD-to-Rust contract surface; downstream `svd2rust` interop depends on it).

### 5.2 Newtype wrapper family

The emitter SHALL emit each chart channel through one of the following six newtype wrappers, selected by the channel's `sos:kind` and the optional `sos:clear_on_read` / `sos:side_effect` annotations:

| Chart annotation | Emitted wrapper | Surface methods | Notes |
|---|---|---|---|
| `kind="status"` (no `sos:clear_on_read`) | `Status<T>` | `read(&self) -> T`, `notified(&self) -> bool` (when `sos:irq` present) | RO; safe `read`. |
| `kind="status"` + `sos:clear_on_read="true"` | `ClearOnRead<T>` | `read(self) -> T` (consumes `self`) | Double-read is a compile error, not a lint warning (per INV-S-MEM-D-2). `#[must_use]`. |
| `kind="command"` (no `sos:side_effect`) | `Command<T>` | `fire(&mut self, value: T)` | WO; no `read` accessor (per INV-S-MEM-D-3). |
| `kind="command"` + `sos:side_effect` non-trivial | `FireOnWrite<T>` | `fire(&mut self, value: T)` | WO; carries the chart-declared side-effect annotation in a doc-comment. |
| `kind="queue"` | `Queue<T>` | `push(&mut self, value: T) -> Result<(), QueueFull>`, `pop(&mut self) -> Option<T>`, `len(&self) -> usize` | DPRAM-backed ring; matches umbrella §5.2 primitive mapping. |
| `kind="shared"` | `Shared<T>` | `claim(&mut self) -> Result<Claimed<'_, T>, ContentionError>`, `try_claim(&mut self) -> Option<Claimed<'_, T>>` | Type-state pattern per §5.3. |

Each wrapper is `#[repr(transparent)]` over `vcell::VolatileCell<T>` (or the inner cell type per PCDN-SOS-09-D-001), so the field layout in `RegisterBlock` matches the SVD-emitted address layout bit-for-bit. The wrappers are emitted into a per-crate `pub mod prelude { use ... }` so a driver can `use my_chart_hal::prelude::*;` and obtain the type names without paying attention to which sub-module they live in.

`Queue<T>` and `Shared<T>` MAY be richer than the bare wrapper would suggest — the queue carries the DPRAM ring's head/tail register pair (two underlying `RegisterBlock` fields) wrapped behind the single `Queue` accessor; the shared region carries the `sos_mutex` register pair similarly. The emitter assembles the composite accessor from multiple physical register slots per the umbrella §5.2 primitive mapping. The chart sees ONE channel; the SVD sees the composite registers; the Rust HAL sees ONE wrapper.

Frozen-enumeration registration policy: **Standards Action** (the family encodes the cross-phase contract between chart annotations and Rust type-system semantics; adding a seventh wrapper or rewiring an existing wrapper both require cross-phase amendment).

### 5.3 Type-state pattern for `kind="shared"`

A `kind="shared"` channel is realised as a `Shared<T>` newtype wrapper exposing only:

```rust
impl<T> Shared<T> {
    pub fn claim(&mut self) -> Result<Claimed<'_, T>, ContentionError> { /* ... */ }
    pub fn try_claim(&mut self) -> Option<Claimed<'_, T>> { /* ... */ }
}
```

The typed region `T` is accessible ONLY through methods on the `Claimed<'_, T>` Drop-guard:

```rust
pub struct Claimed<'a, T> { /* opaque; carries &'a mut Shared<T> + held-lock token */ }

impl<'a, T> Claimed<'a, T> {
    pub fn read(&self) -> T where T: Copy { /* ... */ }
    pub fn write(&mut self, value: T) { /* ... */ }
    pub fn modify<F: FnOnce(&mut T)>(&mut self, f: F) { /* ... */ }
}

impl<'a, T> Drop for Claimed<'a, T> {
    fn drop(&mut self) { /* release underlying sos_mutex */ }
}
```

The borrow checker enforces:

- **No access without claim.** The typed region is not reachable from `Shared<T>` directly; the only path is `claim()` → `Claimed` → methods on `Claimed`.
- **No double-claim.** `claim()` takes `&mut self`; the borrow checker prevents a second `claim()` while the first `Claimed` is live.
- **No forgotten release.** `Claimed::drop` runs at end of scope; the driver cannot leak the mutex by forgetting an explicit `release()` call.

`ContentionError` is the error type returned when the underlying `sos_mutex` is held by the HW side at `claim()` time. Per PCDN-SOS-09-D-003 recommendation, the default shape is:

```rust
pub enum ContentionError {
    LockHeldElsewhere,
}
```

A `try_claim` variant exists for non-blocking access patterns; it returns `Option<Claimed<'_, T>>` (`None` on contention).

The type-state pattern compile-time-enforces the umbrella §5.2 `shared` channel realisation contract ("typed atomic region behind `with_lock(|state| ...)` HAL idiom"). The chart's `kind="shared"` annotation IS the request for this pattern.

Frozen-enumeration registration policy: **Standards Action** (the type-state shape is the cross-phase contract for shared-channel realisation; alternative patterns — `with_lock(closure)` instead of `Claimed` guard, panic-on-contention instead of `Result`, etc. — would change the chart-author-visible API and require cross-phase amendment).

### 5.4 `#![no_std]` + optional `alloc` policy

The emitted Rust HAL crate carries `#![no_std]` at the crate root by default. The emitter MUST NOT reference any `std::` symbol; all dependencies (e.g. `core::`, `vcell::`, optional `cortex_m::`) are no-std-compatible.

An optional Cargo feature `alloc` gates code paths that require a global allocator. The feature surface, per recommendation:

- **`alloc` off (default).** The crate compiles `#![no_std]` without an allocator; every emitted symbol resolves under `cargo check --no-default-features --target thumbv7em-none-eabihf` (per INV-S-MEM-D-4). Bare-metal RTIC / embassy / direct-cortex-m drivers consume this mode.
- **`alloc` on.** The crate uses `extern crate alloc;` and MAY emit `Box<dyn Fn(...)>`-style callback registration APIs, `Vec<u8>`-backed queue helpers, and other allocator-dependent conveniences. Environments with `linked_list_allocator` / `embedded-alloc` / `talc` / similar enable this for ergonomic improvements.

The `alloc` feature MUST NOT change the `RegisterBlock` layout, the newtype wrapper family, or the type-state pattern of §5.3. It adds APIs only; it never modifies the no-default-features surface.

Frozen-enumeration registration policy: **Specification Required** (the feature shape is local to SOS-09-D's contract surface; adding a third feature flag — `embassy` for first-class async, say — is a phase-owner walkthrough update, not a §15 amendment).

### 5.5 `*_unchecked` accessor emission policy (chart-bounds discharge per INV-SOS-G)

For each chart channel where the chart-bounds analysis (per INV-SOS-G) can prove a known-state invariant (e.g. "this status register is provably non-zero after the chart-declared init sequence completes"), the codegen MAY emit a `*_unchecked` accessor variant alongside the safe accessor. The `*_unchecked` accessor:

- Is `unsafe fn` (per PCDN-SOS-09-D-005 recommendation). The discharging invariant lives in the chart (build-time provable), but the function still violates the type-state safety net (it bypasses, e.g., `ClearOnRead<T>::read` consuming `self`); the caller MUST assert that the chart-level invariant is satisfied at the call site.
- Carries a `// SAFETY:` doc-comment naming the discharging chart invariant by `sos:id` UUID + chart state path. Example:

```rust
/// SAFETY: discharged by chart invariant `b9a2d3f4-...` (channel `status_ready`
/// is provably non-zero in chart state `init.complete`).
pub unsafe fn read_unchecked(&self) -> u32 { /* ... */ }
```

- Is emitted ONLY when the chart-bounds analysis successfully proves the discharge. The emitter MUST NOT emit `*_unchecked` accessors speculatively; absent proof, the safe accessor is the only path.
- Is accompanied by a `// @spec` reference to the umbrella §7 INV-SOS-G text, so a reviewer can chase the discharge chain.

Frozen-enumeration registration policy: **Specification Required** (the discharge-emission policy is local to SOS-09-D; adding new discharge categories — e.g. discharging atomicity claims separately from value-range claims — is a phase-owner walkthrough update).

### 5.6 MPU-region constant export

For each chart channel carrying a `sos:zone` annotation (per SOS-09-A §5.2) and/or a `sos:mpu_attr` annotation (per SOS-09-G PCDN-SOS-09-G-003 ratified 2026-05-25), SOS-09-D emits a `pub const SOS_MPU_<CHANNEL_UPPER>_REGION: sos_mpu_region_t = ...;` Rust declaration alongside the `RegisterBlock`. The constant carries the chart-declared `base_addr` / `size` / `attr` / `perm` per SOS-09-G §5.2 derivation rules.

The `sos_mpu_region_t` type is defined in `SOS-09-G-CONCEPTS.md` §5.3 and emitted by SOS-09-G's Rust-side artifact. SOS-09-D imports the type and emits the per-channel constant values; the constants are consumed by SOS-09-G's `sos_mpu_install()` step 4 (which reads the chart-declared `sos:mpu_attr` per channel and writes the corresponding MPU region descriptor).

`<CHANNEL_UPPER>` is derived from the channel's `sos:name` (NOT `sos:id`) via SCREAMING_SNAKE_CASE conversion (e.g. `sos:name="status_ready"` → `SOS_MPU_STATUS_READY_REGION`). Per INV-S-MEM-D-6, the conversion is deterministic; two charts producing the same `sos:name` set produce structurally-identical const names.

A chart channel with no `sos:zone` and no `sos:mpu_attr` does NOT contribute an MPU-region constant export. The default-region policy (per SOS-09-G §5.2 / PCDN-SOS-09-G-001) covers such channels via the background region; per-channel constants are emitted only when the chart explicitly declares per-channel protection.

Frozen-enumeration registration policy: **Specification Required** (the constant-name shape is local to SOS-09-D's Rust-side contract surface; the `sos_mpu_region_t` shape is SOS-09-G's authority).

## 6. Invariants — INV-S-MEM-D-1 through INV-S-MEM-D-6

In addition to the cross-phase invariants INV-SOS-A through H (from SOS-07) and the SOS-09 cross-sub-phase invariants INV-S-MEM-1 through 6 (from SOS-09 §7), the following invariants are normative within SOS-09-D:

- **INV-S-MEM-D-1 — Newtype-wrapper-only register access.** Every register field MUST be accessed through one of the §5.2 newtype wrappers (`Status<T>` / `Command<T>` / `Queue<T>` / `Shared<T>` / `ClearOnRead<T>` / `FireOnWrite<T>`). Raw `core::ptr::read_volatile` / `core::ptr::write_volatile` calls inside the emitted HAL crate are an emitter error (caught by the SOS-09-D walker's lint pass). The only `unsafe` register access lives inside the newtype wrapper implementations themselves and inside `*_unchecked` accessors (per §5.5); driver-facing code is fully safe modulo `*_unchecked`. (Specialises INV-SOS-G's verified-codegen position to the Rust HAL surface: the chart-bounds analysis discharges the only `unsafe` that reaches driver code.)

- **INV-S-MEM-D-2 — `ClearOnRead<T>::read` consumes `self`.** Per §5.2, the `ClearOnRead<T>` wrapper's `read` method takes `self` by value, not `&self`. A driver authoring `let x = reg.read(); let y = reg.read();` produces a compile error ("use of moved value: `reg`"), NOT a runtime double-clear and NOT a lint warning. Double-read becomes structurally impossible. (Closes the bench-9p..9u failure mode named in §2.1.)

- **INV-S-MEM-D-3 — `Command<T>` exposes only `fire` / `claim` / `release`, never `read`.** Per §5.2, the `Command<T>` newtype's API surface MUST NOT contain a `read` method. Driver code that attempts `cmd_reg.read()` produces a compile error ("no method named `read` found for type `Command<u32>`"). Status reads on a command register become structurally impossible. (Closes the bench-pattern command/status mismatch named in §2.2.)

- **INV-S-MEM-D-4 — Emitted crates `cargo check` clean on thumbv7em-none-eabihf.** Every emitted Rust HAL crate MUST pass `cargo check --no-default-features --target thumbv7em-none-eabihf` (the SOS-08 PCDN-006 target). This is the bare-metal-cortex-m default mode (per §5.4); the check verifies both `#![no_std]` cleanliness and the absence of architecture-specific symbols outside the `cortex_m` Cargo feature. The strict mode `cargo check --no-default-features --target thumbv7em-none-eabihf -- -D warnings` is the recommended CI flag.

- **INV-S-MEM-D-5 — `RegisterBlock` field offsets match SVD `<addressOffset>` bit-for-bit.** Per §5.1, the `#[repr(C)]` field-and-padding layout of the emitted `RegisterBlock` MUST match the SVD-emitted `<addressOffset>` chain bit-for-bit. Mismatch (e.g. emitted field offset 0x14 vs SVD `<addressOffset>0x10`) is a build-stop, NOT a runtime check; the codegen verifies the layout via a `core::mem::offset_of!` assertion macro emitted into the crate. (Specialises INV-S-MEM-B-4 emission-determinism to the Rust-side surface: the SVD and the Rust crate emit from the same chart input, so identity is auditable at build time.)

- **INV-S-MEM-D-6 — Accessor + type names deterministic from `sos:name`.** Per SOS-09-A §5 (PCDN-SOS-09-A-003 ratification 2026-05-25), `sos:name` is the SV-identifier emission handle; `sos:id` (UUID) is identity-only and MUST NOT appear in emitted Rust symbol names. The mapping `sos:name → <field_name>` (snake_case for fields, PascalCase for type names, SCREAMING_SNAKE_CASE for MPU-region constants) is deterministic. Two charts that produce the same `sos:name` set produce structurally-identical Rust modules (modulo the `<version>` content-hash in doc-comments). The UUID `sos:id` appears only in (a) `// SAFETY:` discharge comments naming chart invariants (per §5.5) and (b) the crate-level doc comment recording the source chart's identity for audit. (Specialises INV-SOS-G's auditability requirement to the Rust HAL surface; mirrors SOS-09-B INV-S-MEM-B-4 emission-determinism.)

## 7. Enumeration policies

The frozen enumerations of §5 carry the following registration policies (catalog format mirroring SOS-09 umbrella §9 + SOS-09-B §5):

| § | Enumeration / decision | Registration policy |
|---|---|---|
| §5.1 | `RegisterBlock` struct shape (`#[repr(C)]`, `vcell::VolatileCell<T>` fields, SVD-derived address layout, `#[non_exhaustive]`) | **Standards Action** |
| §5.2 | Newtype wrapper family — `Status<T>` / `Command<T>` / `Queue<T>` / `Shared<T>` / `ClearOnRead<T>` / `FireOnWrite<T>` | **Standards Action** |
| §5.3 | Type-state pattern for `kind="shared"` — `Shared<T>::claim() -> Result<Claimed<'_, T>, ContentionError>` + `Claimed::drop` releases | **Standards Action** |
| §5.4 | `#![no_std]` + optional `alloc` policy | **Specification Required** |
| §5.5 | `*_unchecked` accessor emission policy (chart-bounds discharge per INV-SOS-G) | **Specification Required** |
| §5.6 | MPU-region constant export shape (`pub const SOS_MPU_<CHANNEL>_REGION: sos_mpu_region_t = ...;`) | **Specification Required** |

## 8. Standards integration matrix additions

This sub-phase EXTENDS the SOS-09 §8 matrix. SOS-09-D uses the SOS-09 umbrella rows for `svd2rust` (**derive**) and `chiptool` (**derive**) without modification AND adds the following SOS-09-D-specific clarifications:

| Concept | Upstream authority | Local relationship | Phase that declares it | Mutation rights |
|---|---|---|---|---|
| `svd2rust` upstream behavior (RegisterBlock shape, accessor method idiom, strict-mode behaviour) | open project (Rust Embedded WG) | **derive** — SOS-09-D's emission is svd2rust-compatible by convention; chart authors MAY substitute external `svd2rust` against the SOS-09-B-emitted SVD and obtain a structurally-similar crate | this doc | none — svd2rust idiom is upstream |
| `chiptool` upstream behavior (alternative SVD→Rust toolchain; Embassy-adjacent) | open project (Embassy WG) | **derive** — SOS-09-D's emission is structurally compatible with `chiptool`-style consumption (the type-state pattern of §5.3 is inspired by `chiptool`'s async accessor surface, adapted to the SOS-09 `kind="shared"` realisation) | this doc | none — `chiptool` idiom is upstream |
| `vcell::VolatileCell<T>` crate | open project (Rust Embedded WG; `vcell` crate) | **derive** — SOS-09-D emits fields of this type; the volatile-cell idiom is upstream | this doc | none — `vcell` API is upstream |
| `cortex-m` crate (gated behind `cortex_m` Cargo feature) | open project (Rust Embedded WG) | **derive** — when the `cortex_m` feature is on, SOS-09-D emits code referencing `cortex_m::interrupt::Mutex` and adjacent primitives | this doc | none — `cortex-m` API is upstream |
| SOS-09 channel-annotation key convention (`sos:`-prefixed keys inside `other_attributes`) | `SOS-09-CONCEPTS.md` §8; `SOS-09-A-CONCEPTS.md` §5 | **mirror** — SOS-09-D reads `sos:`-prefixed keys per PCDN-SOS-09-001 amended 2026-05-25; SOS-09-A owns the schema | this doc | none |
| SOS-09 umbrella §5.1 channel-kind enum (`{status, command, queue, shared}`) | `SOS-09-CONCEPTS.md` §5.1 | **mirror** — SOS-09-D consumes the enum as the newtype-wrapper-family selection key (§5.2) | this doc | none |
| SOS-09-B CMSIS-SVD emission contract (`<access>` mapping, `<addressOffset>` chain) | `SOS-09-B-CONCEPTS.md` §5.3 | **mirror** — SOS-09-D consumes the validated SVD via `svd2rust --strict`; SOS-09-B owns the SVD shape | this doc | none |
| SOS-09-G `sos_mpu_region_t` type + `sos_mpu_install()` hook | `SOS-09-G-CONCEPTS.md` §5.3, §5.5 | **mirror** — SOS-09-D emits `pub const SOS_MPU_<CHANNEL>_REGION: sos_mpu_region_t = ...;` declarations consumed by `sos_mpu_install()`; SOS-09-G owns the type | this doc | none |

Per INV-SOS-E, the row addition policy mirrors SOS-07 §7 and SOS-09 §8: **Specification Required** for adding new rows (phase-owner walkthrough); **Standards Action** for modifying an existing row's relationship value.

## 9. Acceptance gates

The SOS-09-D emit path's acceptance gates are:

- (a) **`RegisterBlock` layout gate** — Every emitted `RegisterBlock` is `#[repr(C)]` with field offsets matching the SVD-emitted `<addressOffset>` chain bit-for-bit. Verified by emitted `core::mem::offset_of!`-based assertion macro (per INV-S-MEM-D-5).
- (b) **Newtype family completeness gate** — Every chart channel surfaces as exactly one newtype wrapper from the §5.2 family (`Status` / `Command` / `Queue` / `Shared` / `ClearOnRead` / `FireOnWrite`). The wrapper selection is deterministic from `sos:kind` + `sos:clear_on_read` + `sos:side_effect`.
- (c) **Type-state-for-shared gate** — Every `kind="shared"` channel emits a `Shared<T>` wrapper whose typed region `T` is unreachable except through `Claimed<'_, T>`. Verified by a synthetic "negative compile" test (the emitted crate ships a `tests/compile-fail/` test that attempts `shared.write(value)` without `claim()` and expects rustc to reject).
- (d) **`cargo check` clean gate** — Every emitted crate passes `cargo check --no-default-features --target thumbv7em-none-eabihf` (per INV-S-MEM-D-4). The strict CI variant uses `-- -D warnings`.
- (e) **`*_unchecked` discharge gate** — Every emitted `*_unchecked` accessor carries a `// SAFETY:` comment naming the discharging chart invariant by `sos:id` UUID + chart state path (per §5.5). Verified by a grep-pass over the emitted crate.
- (f) **MPU-region constant export gate** — Every chart channel with a `sos:zone` and/or `sos:mpu_attr` annotation emits a `pub const SOS_MPU_<CHANNEL>_REGION: sos_mpu_region_t = ...;` declaration. The const-name conversion (`sos:name` → SCREAMING_SNAKE_CASE) is deterministic per INV-S-MEM-D-6.
- (g) **Determinism gate** — Two consecutive emit runs on the same (chart, target) produce byte-identical Rust crate output (modulo `<version>` content-hash variation that traces to chart edits). Mirrors INV-S-MEM-B-4 / INV-SOS-G at the Rust-side surface.
- (h) **`svd2rust` parity gate (informative)** — A chart whose SOS-09-B-emitted SVD is piped through external `svd2rust --strict` produces a Rust crate that compiles AND whose `RegisterBlock` field offsets match the SOS-09-D-emitted crate. This is an informative gate (the external `svd2rust` is not the canonical emitter; SOS-09-D is) but its passing demonstrates the svd2rust-compatibility claim of §0.
- (i) **`sos:name`-determinism gate** — Two charts with the same `sos:name` set produce structurally-identical Rust modules (modulo doc-comment content-hash). Verified by a fixture pair (two charts differing only in `sos:id` UUIDs but sharing `sos:name` values) emitting byte-identical Rust source modulo the documented variation surface.

A conforming SOS-09-D implementation satisfies (a)–(g) and (i). Gate (h) is informative — its passing strengthens the svd2rust-compatibility claim but its failing does not block ratification (SOS-09-D is the canonical Rust emitter; external svd2rust is a comparand).

## 10. Reconciliation decisions vs adjacent repo primitives

### vs. `svd2rust` (canonical comparand)

`svd2rust` is the Rust Embedded WG's canonical SVD→Rust toolchain; it consumes CMSIS-SVD and emits a `#[repr(C)] struct RegisterBlock` with accessor methods using read/write/modify proxy types. SOS-09-D's emission shape is **svd2rust-compatible by design**: the same SVD passing SOS-09-B's strict gate (per SOS-09-B §5.6 / INV-S-MEM-B-3) MAY be piped through external `svd2rust` and produce a structurally-similar crate. The value-add SOS-09-D provides over raw `svd2rust` output is:

1. **Chart-annotation-driven newtype semantics.** `svd2rust` emits read/write proxies from SVD `<access>` alone; SOS-09-D emits `Status` / `Command` / `ClearOnRead` / `FireOnWrite` / `Queue` / `Shared` from the chart's `sos:kind` + `sos:clear_on_read` + `sos:side_effect` + composite-primitive resolution. The SVD's `<access>` is a coarse axis (`read-only` / `write-only` / `read-write`); the chart's `sos:kind` is the fine axis the type system can enforce.

2. **Type-state pattern for `kind="shared"`.** `svd2rust` has no concept of a chart-level `shared` channel; an SVD `read-write` register with no annotation gets a `read()` + `write()` proxy. SOS-09-D's `Shared<T>` / `Claimed<'_, T>` / `ContentionError` pattern (per §5.3) compile-time-enforces the mutex contract that the chart's `kind="shared"` annotation requested.

3. **MPU-region constant export.** `svd2rust` has no concept of per-register MPU configuration. SOS-09-D emits `pub const SOS_MPU_<CHANNEL>_REGION: sos_mpu_region_t = ...;` declarations consumed by SOS-09-G's `sos_mpu_install()` (per §5.6).

A chart author who values pure svd2rust compatibility MAY substitute external `svd2rust` for SOS-09-D's emission and lose only the chart-annotation-driven type-system enforcement. The SVD round-trip works either way; the type safety is the SOS-09-D-specific surface.

### vs. `chiptool` (Embassy-adjacent alternative)

`chiptool` is an Embassy-WG-adjacent alternative to `svd2rust`, offering first-class async accessors + type-state register accessors + richer field-access patterns. SOS-09-D's type-state pattern for `kind="shared"` (per §5.3) is **inspired by** `chiptool`'s async accessor surface, adapted to the SOS-09 `kind="shared"` realisation. The two are structurally compatible: a chart author MAY emit through SOS-09-D, take the output crate, and integrate it into an Embassy-based driver without friction. SOS-09-D does not author `chiptool`-style async accessors at v1; first-class async support is a future extension when an Embassy-target chart enters the SOS bench substrate.

### vs. `tools/sos-codegen/transliterate_rust.py` (existing walker)

The Rust transliteration walker at `tools/sos-codegen/transliterate_rust.py` exists in the repo as the SOS-codegen Rust emit path (extended for SOS-08 SystemVerilog parallel emission). SOS-09-D extends this walker with the SOS-09-channel-emit subset: a new pass over chart channels (the same channels SOS-09-B's SVD-emit walker consumes) producing the `RegisterBlock` + newtype-wrapper-family + type-state-for-shared + MPU-region-constant emission. The two passes share a chart-load step; the SOS-09-D pass adds the chart-bounds analysis pass for `*_unchecked` discharge (per §5.5). The existing transliteration patterns (state-machine emission, datamodel emission) are unchanged; SOS-09-D is an additive surface.

### vs. SOS-09-A (chart annotation surface)

SOS-09-D **consumes** SOS-09-A's annotation schema. The ten-key permitted set (`sos:id`, `sos:name`, `sos:kind`, `sos:dir`, `sos:zone`, `sos:atomicity`, `sos:width`, `sos:bit_layout`, `sos:irq`, `sos:mutex`) ratified at SOS-09-A is read from `other_attributes` JSON. SOS-09-D does NOT extend the attribute set; new SOS-semantic keys are SOS-09-A's authority. The SOS-09-D-specific reads are: `sos:id` (only in `// SAFETY:` discharge comments + crate doc-comment, per INV-S-MEM-D-6), `sos:name` (the emission-facing handle for every Rust symbol), `sos:kind` (newtype-wrapper-family selection per §5.2), `sos:dir` (passed through to SOS-09-B's SVD `<access>` derivation, consumed transitively), `sos:zone` + `sos:mpu_attr` (MPU-region constant export per §5.6), `sos:width` (passed through to the register-width type parameter `T`), `sos:irq` (gates `Status<T>::notified` accessor emission), `sos:clear_on_read` + `sos:side_effect` (selects `ClearOnRead<T>` / `FireOnWrite<T>` wrappers per §5.2).

### vs. SOS-09-B (CMSIS-SVD emission)

SOS-09-D is **downstream** of SOS-09-B. The SVD-emit gate (per SOS-09-B §5.6 / INV-S-MEM-B-3 — `xmllint --schema` + `svd2rust --strict`) is the load-bearing input to SOS-09-D: the chart must produce a strict-svd2rust-passing SVD before SOS-09-D's Rust emission is meaningful. SOS-09-D's `RegisterBlock` address layout derives from the SVD's `<addressOffset>` chain bit-for-bit (per INV-S-MEM-D-5); the access mapping derives from SVD `<access>` (via SOS-09-B §5.3); the side-effect annotations derive from SVD `<modifiedWriteValues>` + `<readAction>` (via SOS-09-B §5.4). SOS-09-D does NOT re-implement chart parsing; the SVD IS the chart-derived contract surface SOS-09-D consumes.

### vs. SOS-09-C (C HAL emission)

SOS-09-D and SOS-09-C are **sibling** sub-phases — both consume the SOS-09-B-validated SVD and produce a typed accessor surface (Rust vs C). The two emit paths share no source code (Rust's type system carries semantics C cannot express, and C's preprocessor patterns carry conventions Rust does not need), but they share a chart input and produce structurally-isomorphic register-access APIs. A SOS-09-D `Status<T>::read()` corresponds to a SOS-09-C `XXX_get_status()` macro / function; a SOS-09-D `Command<T>::fire(value)` corresponds to a SOS-09-C `XXX_fire_cmd(value)` macro; etc. The naming convention mapping (Rust `<sos:name>::method()` vs C `<XXX_SOS_NAME>_<verb>()`) is a SOS-09-C concern.

### vs. SOS-09-E (HDL register-file RTL)

SOS-09-D and SOS-09-E are **sibling** sub-phases — both consume chart annotations (transitively, via the SOS-09-B-validated SVD for SOS-09-D; directly for SOS-09-E) and produce an integration artifact (Rust HAL vs HDL register-file RTL). SOS-09-D consumes the SVD's `<addressOffset>` chain that SOS-09-E's bus-decode logic MUST match (per SOS-09-B INV-S-MEM-B-4 / SOS-09-E TBD). A chart change that re-numbers `<addressOffset>` MUST propagate to both sides; the SOS-09-B-emitted SVD is the common source.

### vs. SOS-09-F (membrane vectors)

SOS-09-F's membrane-vector framework reads the SOS-09-B-emitted SVD to enumerate the register set under test (per SOS-09-B §10 reconciliation). When the membrane-vector framework's host-side driver is itself Rust (the Embassy-target case), the SOS-09-D-emitted HAL crate IS the driver-side accessor surface SOS-09-F invokes. The six vector shapes (initial-value-read, write-then-read, side-effect-on-write, clear-on-read, atomicity, protection — per SOS-09 umbrella §6 SOS-09-F enumeration) consume the corresponding SOS-09-D newtype methods: `Status<T>::read()` for initial-value-read, `Command<T>::fire()` then `Status<T>::read()` for side-effect-on-write, `ClearOnRead<T>::read()` for clear-on-read, `Shared<T>::claim()` for atomicity, etc. SOS-09-D's emission is what makes the SOS-09-F vectors callable at the Rust call site.

### vs. SOS-09-G (MPU configuration)

SOS-09-D **feeds** SOS-09-G's `sos_mpu_install()` runtime hook. Per SOS-09-G §5.5 step 4, the hook reads chart-declared `sos:mpu_attr` per channel and writes the corresponding MPU region descriptor. SOS-09-D emits the per-channel constants (`pub const SOS_MPU_<CHANNEL>_REGION: sos_mpu_region_t = ...;` per §5.6) that step 4 reads. The `sos_mpu_region_t` type is owned by SOS-09-G (per §5.3); SOS-09-D imports and emits values, never the type definition itself. A chart edit that adds a channel with `sos:zone` propagates to a new const declaration via SOS-09-D; SOS-09-G's `sos_mpu_install()` picks it up at build time via the const-import.

### vs. SOS-04 (M7 Rust port)

SOS-04 is the M7 Rust port that hosts the chart-emitted accessors. Per SOS-09 §10 (reconciliation vs SOS-04), the boundary is: SOS-04's existing pattern (cortex-m's `Peripherals::steal()`, direct volatile access via `core::ptr::read_volatile`) owns CPU-internal peripheral access (NVIC, SCB, SysTick, MPU configuration registers themselves); SOS-09-D's emission owns chart-declared external membrane access. The two coexist within the same Rust crate; SOS-04's surface is the runtime, SOS-09-D's emission is the chart-driven accessor layer atop. SOS-09 already promised a SOS-04 §15 amendment co-landing when SOS-09 ratifies; SOS-09-D's ratification does not re-litigate that amendment.

### vs. PCDN-SOS-09-001 amended 2026-05-25

The amendment that routes channel annotations through `other_attributes` (vs the originally-resolved `xmlns:sos` namespace) is a load-bearing input to SOS-09-D's read path. SOS-09-D MUST NOT emit any `xmlns:sos` declaration into the Rust crate output (the emitted crate carries Rust attributes per the standard `#[...]` syntax, not XML-namespace-bearing constructs). SOS-09-D MUST read `sos:`-prefixed keys from `other_attributes` JSON (transitively, via SOS-09-B-emitted SVD that carries the chart-derived register data); reading from XML namespace prefixes would be reading a surface that PCDN-SOS-09-001 amended 2026-05-25 explicitly retracted.

## 11. Non-goals

This sub-phase does NOT:

- **Author a runtime.** SOS-09-D emits an accessor layer; it does NOT author a task scheduler, an interrupt dispatcher, a heap allocator, or any other runtime primitive. The emitted crate is `#![no_std]` and host-runtime-agnostic; the consumer's runtime (SOS-04 M7 Rust port, RTIC, Embassy, bare-metal `cortex-m-rt`) brings the runtime.
- **Depend on `tokio`.** `tokio` is a `std`-targeting async runtime; SOS-09-D's `#![no_std]` policy (per §5.4) forbids it. Async accessor support (a chiptool-style surface) is deferred to a future extension when Embassy enters the bench substrate.
- **Author a generic register-abstraction library.** SOS-09-D's newtype wrappers are emitted from chart annotations; the library is per-chart, not a generic register-access crate. (Existing crates like `register-rs` / `tock-registers` / `volatile-register` are upstream comparands SOS-09-D's emission is structurally compatible with, but SOS-09-D does not author a competing generic library.)
- **Target v1 platforms beyond bare-metal `cortex-m` + RTIC/embassy.** The `cortex_m` Cargo feature (per PCDN-SOS-09-D-004) gates the cortex-m-crate-bearing path; the no-feature path is target-agnostic but its v1 verification surface is `cargo check --target thumbv7em-none-eabihf` only. RISC-V (`riscv` crate) and Cortex-R targets are future extensions.
- **Replace `svd2rust` or `chiptool`.** SOS-09-D emits in a svd2rust-compatible shape (per §10 reconciliation) so external `svd2rust` MAY substitute against the SOS-09-B-emitted SVD; SOS-09-D's value is the chart-annotation-driven newtype semantics, not a fork of the upstream toolchain.
- **Emit drivers.** SOS-09-D emits the typed accessor surface; the driver code (sequencing of register accesses to perform a HW task) is hand-authored by the consumer. A future SOS phase MAY emit driver scaffolds from chart-state transitions; that is not SOS-09-D's scope.
- **Author the MPU table type.** Per §5.6, SOS-09-D emits per-channel MPU-region constants of type `sos_mpu_region_t`; the type itself is SOS-09-G's authority. SOS-09-D imports and uses; it never defines.
- **Register a Cargo namespace or publish to crates.io.** Emitted crates live under `build/rust-hal/<chart_id>/` per INV-S-MEM-2. Publication to crates.io is a downstream consumer concern (e.g. a customer integrating the chart-emitted HAL into their proprietary firmware); SOS-09-D's emit path is build-output-only.

## 12. Acceptance checklist

A conforming SOS-09-D ratification satisfies:

- (a) ✅ PCDN-SOS-09-D-001 through 005 resolved (§15) (2026-05-26).
- (b) ✅ The SOS-09-D walker presence — `tools/sos-codegen/transliterate_rust.py` carries the SOS-09-D-channel-emit subset and emits `RegisterBlock` + newtype family + type-state-for-shared + MPU constants per §5 (SOS09D1 implementation, 2026-05-26). Public entry points: `emit_rust_hal()`, `emit_rust_hal_from_chart()`, `write_rust_hal_crate()`.
- (c) ✅ The `RegisterBlock` layout gate (§9 (a)) is verified for the worked-example chart `tools/sos-codegen/tests/fixtures/sos_09_d/worked_example.scxml`. The emitter additionally injects `const _SOS_09_D_LAYOUT_ASSERTIONS: () = { assert!(core::mem::offset_of!(RegisterBlock, …) == 0x…usize, …); };` into every emitted `src/lib.rs` so drift becomes a build-stop (INV-S-MEM-D-5). The pytest case `TestGateC_LayoutMatchesSVD::test_layout_matches_svd_emit` cross-checks the HAL offsets against the SVD `<addressOffset>` chain emitted by `transliterate_svd.emit_svd`.
- (d) ✅ The newtype family completeness gate (§9 (b)) is verified by `TestGateD_NewtypeFamilyCompleteness`: the worked-example chart exercises all four `sos:kind` values (`status`, `command`, `queue`, `shared`) plus both side-effect/clear-on-read variants (`ClearOnRead<T>` from `rx_status`, `FireOnWrite<T>` from `tx_command`).
- (e) ✅ The type-state-for-shared gate (§9 (c)) is verified structurally by `TestGateE_TypeStateForShared`: the emitted prelude exposes `Shared<T>::claim()` / `try_claim()` as the only public methods on `Shared<T>`, and `Claimed<'_, T>` is the sole reachable typed-region surface (with `Drop`). The structural assertion is load-bearing for the borrow-checker rejection — a driver writing `shared.write(value)` without `claim()` produces "no method `write` found for type `Shared<u32>`", which IS the compile-fail outcome §9 (c) names. A `trybuild`-style explicit compile-fail crate is documented as a follow-up bench-validation artifact when SOS-09-D first reaches ECP5 bring-up.
- (f) ✅ The `cargo check` clean gate (§9 (d)) is verified by `TestGateF_CargoCheck::test_cargo_check_clean` when `cargo` is on PATH; the test runs `cargo check --no-default-features --target thumbv7em-none-eabihf` against the emitted worked-example crate. SKIP with reason when `cargo` is absent (INV-S-MEM-D-4 deferred to CI / dev environments).
- (g) ✅ The `*_unchecked` discharge gate (§9 (e)) is verified by `TestGateG_UncheckedDischarge`: the emitter generates `pub unsafe fn <channel>_read_unchecked(...) -> T` for every `kind="status"` channel with a codegen-emitted `// SAFETY: discharged by chart invariant <sos:id> ... INV-SOS-G ...` rollup. Per the user clarification of 2026-05-26 ("SAFETY is coherent, but we will want to roll this up in generation"), v1 emits a TODO-style placeholder citing INV-SOS-G + the channel's `sos:id`; the chart-bounds analyzer integration is a paired follow-up per the analyzer/annotation-semantics versioned-pair discipline (see parent CLAUDE.md / orchestrator memory chart-semantics-versioned-pair). A chart with no `kind="status"` channel falls under the §12 second-tier reduced-conformance form documented in the paragraph below; the emitter writes a "reduced conformance" marker into the emitted `lib.rs`.
- (h) ✅ The MPU-region constant export gate (§9 (f)) is verified by `TestGateH_MPUConstantExport`: the emitter generates `pub const SOS_MPU_<CHANNEL>_REGION: sos_mpu_region_t = sos_mpu_region_t { base_addr: 0x…, size: N, attr: M, perm: P };` for every channel with an explicit `sos:zone` (non-default) or `sos:mpu_attr`. Worked-example coverage: `shared_block` (zone=`unprivileged`) and `plain_status` (mpu_attr=`device_ngnrne`).
- (i) ✅ The `sos:name`-determinism gate (§9 (i)) is verified by `TestGateI_NameDeterminism`: the fixture pair `worked_example.scxml` + `worked_example_alt_ids.scxml` differ only in `sos:id` UUIDs. After stripping the documented UUID-bearing surface (the `// SAFETY:` comments and per-channel doc comments), the two emitted `lib.rs` files are byte-identical. Two-run determinism (same input → byte-identical output) is verified independently by `test_two_runs_byte_identical`.
- (j) ✅ Cross-sub-phase invariants INV-S-MEM-D-1 through 6 cited correctly in the SOS-09-D emit-path source (the SOS-09-D block in `transliterate_rust.py` cites every D-* invariant in its preamble). Verified by `TestGatesJK_InvariantCitation::test_emit_path_cites_invariants`.
- (k) ✅ SOS-09 umbrella INV-S-MEM-1 through 6 satisfied: the emitted crate is a build output (lives under `build/rust-hal/<chart_id>/` per INV-S-MEM-2 — the `write_rust_hal_crate` helper writes there); single-source per INV-S-MEM-1 (the chart is the only authoritative input); determinism per INV-SOS-G mirrors here as INV-S-MEM-D-5 (offset_of! asserts) and INV-S-MEM-D-6 (name derivation from `sos:name` only, with `sos:id` confined to the documented variation surface).

(a) was the ratification gate; (b)–(k) flipped from ⏸ to ✅ when the SOS09D1 implementation landed (2026-05-26). Gate (f) carries a CI-environment dependency: when `cargo` is not on PATH the pytest case skips with reason; the emit + structural gates (b)–(e) + (g)–(k) cover the static-verification surface end-to-end without `cargo`.

A conforming SOS-09-D implementation *without `*_unchecked` chart-bounds discharge* (i.e. charts whose bounds analysis cannot discharge any safety obligations) satisfies (a)–(f) and (h)–(k) with a reduced (g): the worked-example documents the absence of `*_unchecked` accessors as expected. This second-tier conformance level supports first-target ECP5 bring-up demos that exercise only the safe accessor surface, deferring chart-bounds discharge to subsequent bring-up rounds.

## 13. Files cited

| Path | Role |
|---|---|
| `docs/concepts/SOS-09-CONCEPTS.md` | Umbrella; this sub-phase's parent. Cited for §5.1 channel-kind enum, §5.2 channel-to-primitive mapping, §5.5 artifact priority, §7 cross-sub-phase invariants, §8 standards integration matrix. |
| `docs/concepts/SOS-07-CONCEPTS.md` | Cross-phase invariants INV-SOS-A through H; AuthorityRelationship matrix. Cited, not redefined. |
| `docs/concepts/SOS-09-A-CONCEPTS.md` | Chart annotation surface (RATIFIED 2026-05-25). SOS-09-D consumes the 10-key annotation set + PCDN-SOS-09-A-003 `sos:id` UUID / `sos:name` SV-identifier split. |
| `docs/concepts/SOS-09-B-CONCEPTS.md` | CMSIS-SVD emission (RATIFIED 2026-05-25). SOS-09-D consumes the validated SVD via `svd2rust --strict`; address layout per `<addressOffset>` chain. |
| `docs/concepts/SOS-09-C-CONCEPTS.md` | C HAL emission; sibling to SOS-09-D (same chart input, different language target). |
| `docs/concepts/SOS-09-E-CONCEPTS.md` | HDL register-file RTL; sibling. |
| `docs/concepts/SOS-09-F-CONCEPTS.md` | Membrane vectors; downstream consumer of SOS-09-D's accessor surface when the membrane-vector driver is Rust. |
| `docs/concepts/SOS-09-G-CONCEPTS.md` | MPU configuration (RATIFIED 2026-05-25). SOS-09-D emits `pub const SOS_MPU_<CHANNEL>_REGION: sos_mpu_region_t = ...;` declarations consumed by `sos_mpu_install()` step 4. |
| `docs/concepts/SOS-04-CONCEPTS.md` | M7 Rust port; hosts the SOS-09-D-emitted accessor layer atop SOS-04's runtime. |
| `docs/concepts/SOS-08-A-CONCEPTS.md` | Precedent shape for per-sub-phase concept doc layout. |
| `tools/sos-codegen/` | Codegen tool root. |
| `tools/sos-codegen/transliterate_rust.py` | Existing Rust transliteration walker; SOS-09-D extends with the channel-emit subset. |
| `build/rust-hal/<chart_id>/` | Emitted Rust HAL crate (forthcoming; per INV-S-MEM-2 lives under `build/`, not tracked source). |
| Parent `CLAUDE.md` | Spec-Before-Code Planning Discipline; Phase document shape. |

## 14. Unblocks

This sub-phase's ratification (after PCDN walkthrough) unblocks:

- **SOS-09-F membrane vectors in Rust.** When the membrane-vector framework's host-side driver is Rust (the Embassy-target case), the SOS-09-D-emitted HAL crate IS the driver-side accessor surface SOS-09-F invokes. Without the Rust HAL shape frozen, SOS-09-F cannot author Rust-side vector emission.
- **SOS-04 M7 Rust port chart-driven external-peripheral access.** SOS-04 currently uses hand-rolled `Peripherals::steal()` patterns for CPU-internal peripheral access; SOS-09-D's emission gives SOS-04 a chart-driven path for external-peripheral access without re-deriving the volatile-register surface.
- **Downstream consumer scenarios** — every Cortex-M target hosting a SOS-emitted chart can now consume the chart's external-peripheral surface as a typed Rust HAL crate. Embassy-based async drivers, RTIC-based bare-metal drivers, direct-`cortex-m-rt` drivers all benefit.
- **The "PDF cannot lie because the PDF is generated" claim made concrete at the Rust call site.** A Rust driver authored against the emitted HAL crate cannot accidentally clear-on-read twice, cannot accidentally read a command register, cannot accidentally access a shared region without claiming the mutex — the chart-annotation-driven type system enforces each property at compile time.
- **First end-to-end chart-driven SoC bring-up demo (Rust-driver leg).** With SOS-09-D ratified, the umbrella's worked-example (per SOS-09 §12 (c) — at least one chart channel emits all six artifacts) gets a Rust-driver-callable surface, completing the Rust-side leg of the chart → SVD + Rust HAL + HDL register file + membrane vectors → bitstream → cocotb-validated round-trip story.

## 15. Pending Concept Decision Notices (PCDNs)

These open questions move this doc from 🟡 DRAFT to 🟢 ratified. PCDN-SOS-09-D-* identifiers are stable per parent CLAUDE.md "Errata Open Question" naming convention (analogous shape applies — these are PCDNs at the concepts-doc level).

- **PCDN-SOS-09-D-001 — `vcell::VolatileCell<T>` vs `cortex_m::interrupt::Mutex` for inner field type.** 🟢 **RATIFIED 2026-05-26 — accepted option (a)** `vcell::VolatileCell<T>` as the universal inner field type. **User clarification (2026-05-26 walkthrough):** "we have a discipline of the upper blocks enclosing them to use the borrow checker for ownership." The inner field type is `vcell::VolatileCell<T>` per option (a); ownership and aliasing across registers are enforced by the borrow checker at the `RegisterBlock` enclosing scope — one `RegisterBlock` per peripheral, and exclusive write access requires `&mut RegisterBlock` (which the borrow checker rejects any aliasing of). This reinforces INV-S-MEM-D-1 (every register field accessed only through emitted accessors) and INV-S-MEM-D-5 (`RegisterBlock` layout matches SVD bit-for-bit) — both are already-frozen invariants the clarification REINFORCES rather than amends. No §5 / §6 / §7 normative-content edit triggered. Options: (a) `vcell::VolatileCell<T>` (svd2rust convention; `#[repr(transparent)]` over `UnsafeCell<T>`; no interrupt-disable semantics — atomicity is the consumer's responsibility); (b) `cortex_m::interrupt::Mutex<RefCell<T>>` (heavier; interrupt-free critical section on every access; couples the emitted crate to the `cortex-m` crate even without the gate of PCDN-SOS-09-D-004); (c) per-channel choice driven by `sos:atomicity` annotation (`atomic` → vcell; `mutex-required` → interrupt::Mutex). **Recommendation**: option (a) `vcell::VolatileCell<T>` as the universal inner type — matches svd2rust convention; keeps the no-`cortex-m`-feature mode of PCDN-SOS-09-D-004 viable; `mutex-required` channels get their mutex via the SOS-09-G-emitted `sos_mutex` primitive (per umbrella §5.2), not via Rust's `cortex_m::interrupt::Mutex`. The Rust-side critical-section discipline lives at the consumer's runtime layer (RTIC's `Mutex` trait, embassy's executor, etc.), not in the SOS-emitted HAL.

- **PCDN-SOS-09-D-002 — Trait vs struct naming convention.** 🟢 **RATIFIED 2026-05-26 — accepted option (a)** accessor methods on `RegisterBlock` struct (no per-register traits). Options: (a) follow svd2rust convention — `pub struct RegisterBlock { ... }` with accessor methods directly on the struct (no per-register `trait`s); (b) introduce a per-register `trait` (e.g. `trait StatusRegister { fn read(&self) -> u32; }`) to make register-type sets explicit in the type system; (c) hybrid — `RegisterBlock` struct + a per-`sos:kind` trait family (`trait StatusChannel`, `trait CommandChannel`, etc.) so generic driver code can write `fn poll<S: StatusChannel>(s: &S) -> bool`. **Recommendation**: option (a) — accessor methods on the `RegisterBlock` struct, NOT per-register traits. Per-register traits inflate the type surface without buying compile-time guarantees the §5.2 newtype family doesn't already provide; per-`sos:kind` traits (option c) MAY be added as a future extension if generic driver code patterns emerge, but at v1 the concrete newtype wrappers (`Status<T>`, `Command<T>`, etc.) are the type-system surface. The svd2rust precedent argues strongly for option (a).

- **PCDN-SOS-09-D-003 — `Shared<T>::claim()` contention error type.** 🟢 **RATIFIED 2026-05-26 — accepted option (b)** `#[non_exhaustive] enum ContentionError { LockHeldElsewhere }`. Options: (a) `()` (unit type; the only failure mode is contention, so the discriminant value is uninformative); (b) custom enum `enum ContentionError { LockHeldElsewhere }` (room to grow to additional failure modes — `MutexCorrupted`, `TimeoutExpired`, etc. — without an API break); (c) generic over a user-supplied error type (`Shared<T, E>::claim() -> Result<Claimed<'_, T>, E>` with the chart declaring the error type) — most flexible, most complex. **Recommendation**: option (b) `enum ContentionError { LockHeldElsewhere }`. The unit-type option (a) loses the ability to pattern-match meaningfully; the generic option (c) adds a type parameter the chart author has to manage without clear v1 benefit. The single-variant enum is the standard Rust idiom for "one failure mode now, room to grow"; pattern-match-exhaustive code patterns degrade gracefully when a second variant is added (the `#[non_exhaustive]` attribute on `ContentionError` keeps the surface upgradable).

- **PCDN-SOS-09-D-004 — `cortex-m` crate dependency policy.** 🟢 **RATIFIED 2026-05-26 — accepted option (b)** `cortex_m` Cargo feature gated; default-on, opt-out via `--no-default-features` for host-tests / Miri. Options: (a) emitted crates unconditionally depend on `cortex-m` (simplest; couples the HAL surface to ARM Cortex-M only); (b) `cortex-m` crate is gated behind a Cargo feature `cortex_m`; absence of the feature produces a target-agnostic crate (most flexible; harder to test; the `cortex_m`-feature-bearing code path needs separate verification); (c) per-target conditional compilation (no Cargo feature; `#[cfg(target_arch = "arm")]` blocks scattered through the emit) — finer-grained but error-prone. **Recommendation**: option (b) — `cortex-m` gated behind the `cortex_m` Cargo feature. Provides a target-agnostic mode for host-side tests, dual-target HAL emission (Cortex-M + RISC-V), and Miri-based verification of `Shared<T>` type-state logic (Miri doesn't support `cortex-m`'s inline assembly). Default Cargo features SHOULD include `cortex_m` (the v1 target is bare-metal Cortex-M; absence of the feature is the unusual case); `--no-default-features` opt-out for host-tests + Miri.

- **PCDN-SOS-09-D-005 — `*_unchecked` accessor `unsafe fn` annotation.** 🟢 **RATIFIED 2026-05-26 — accepted option (a)** `unsafe fn` for `*_unchecked` accessors. **User clarification (2026-05-26 walkthrough):** "SAFETY is coherent, but we will want to roll this up in generation." The codegen emits the `// SAFETY:` comment text naming the discharging invariant (per §5.5); the caller's matching `// SAFETY:` is still required at the call site for reviewer evidence (the two-side discipline is preserved). The "roll up in generation" clarification covers the emitter-side SAFETY-comment text: it is canonical at codegen time, named by the discharging chart invariant (`sos:id` UUID + chart state path), and reviewers consult the emitted text once per accessor rather than re-deriving it per call site. **TCB dual-role note:** this PCDN's ratification elevates the chart-bounds analyzer to two simultaneous trust roles — (i) TCB for chart-bounds proofs generally (the existing role established by INV-SOS-G); (ii) TCB for Rust-emission `unsafe`-review across the whole emitted HAL surface (the new role from this PCDN — every `unsafe fn _unchecked` in the emitted crate roots its safety case in the chart-bounds analyzer's discharge). Downstream safety-case authors MUST cite the chart-bounds analyzer's revision SHA on every Rust HAL safety case; per the analyzer/annotation-semantics versioned-pair discipline, the analyzer and `SOS-09-A-CONCEPTS.md` rev together (a chart-bounds analyzer build cites the annotation-semantics spec revision it was built against; an annotation-semantics spec amendment requires a paired analyzer build before any new `unsafe`-emission lands). Options: (a) emit `*_unchecked` accessors as **`unsafe fn`** even though the chart-invariant discharges the safety obligation (the discharging invariant lives in the chart, build-time provable, but the function still violates the type-state safety net — e.g. bypassing `ClearOnRead<T>::read` consuming `self` — so the caller MUST assert chart-level invariant satisfaction at the call site); (b) emit `*_unchecked` accessors as **safe `fn`** since the chart-bounds analysis discharges the obligation (cleaner driver code; relies on the chart-bounds analysis being trustworthy without per-call-site review); (c) feature-gate the `*_unchecked` accessors behind a Cargo feature `unchecked_accessors` so consumers opt in (avoids accidental use; couples chart-bounds-discharged code to a feature flag). **Recommendation**: option (a) — `unsafe fn`. The discharging invariant being build-time provable does not eliminate the call-site assertion that the chart's preconditions are satisfied at the dynamic call point (e.g. a driver MAY call the `*_unchecked` accessor from a state the chart-bounds analysis did NOT discharge); the `unsafe` annotation forces the caller to acknowledge that responsibility with a `// SAFETY:` comment of their own naming the chart state they believe themselves to be in. The `// SAFETY:` comment in the emitted accessor (per §5.5) tells the caller what to check; the caller's matching `// SAFETY:` comment at the call site tells the reviewer what was checked. This pattern is the standard Rust-Embedded WG idiom (see `cortex-m`'s `Peripherals::steal()` for the precedent).

## 16. Change log

### 2026-05-26 — Ratified (Ira)

All five PCDNs ratified in the 2026-05-26 walkthrough session; status banner promoted from 🟡 DRAFT to 🟢 RATIFIED 2026-05-26.

- **PCDN-SOS-09-D-001** — 🟢 RATIFIED 2026-05-26 — accepted option (a) `vcell::VolatileCell<T>` as the universal inner field type (matches svd2rust convention; keeps PCDN-SOS-09-D-004's no-`cortex-m`-feature mode viable). **Borrow-checker enclosing-scope clarification (user 2026-05-26):** "we have a discipline of the upper blocks enclosing them to use the borrow checker for ownership." Ownership and aliasing across registers are enforced by the borrow checker at the `RegisterBlock` enclosing scope — one `RegisterBlock` per peripheral; exclusive write access requires `&mut RegisterBlock`. The clarification REINFORCES INV-S-MEM-D-1 (newtype-wrapper-only register access) and INV-S-MEM-D-5 (`RegisterBlock` layout matches SVD bit-for-bit). No §5 / §6 / §7 normative-content edit triggered.
- **PCDN-SOS-09-D-002** — 🟢 RATIFIED 2026-05-26 — accepted option (a) accessor methods on `RegisterBlock` struct (no per-register traits). Per-register traits inflate the type surface without buying compile-time guarantees the §5.2 newtype wrapper family does not already provide; the svd2rust precedent argues strongly for option (a).
- **PCDN-SOS-09-D-003** — 🟢 RATIFIED 2026-05-26 — accepted option (b) `#[non_exhaustive] enum ContentionError { LockHeldElsewhere }`. Single-variant enum is the standard Rust idiom for "one failure mode now, room to grow"; `#[non_exhaustive]` keeps the surface upgradable across phase amendments without breaking exhaustive-match patterns at call sites.
- **PCDN-SOS-09-D-004** — 🟢 RATIFIED 2026-05-26 — accepted option (b) `cortex_m` Cargo feature gated, default-on, opt-out via `--no-default-features` for host-tests and Miri. Provides target-agnostic mode for host-side tests, dual-target HAL emission (Cortex-M + RISC-V), and Miri-based verification of `Shared<T>` type-state logic.
- **PCDN-SOS-09-D-005** — 🟢 RATIFIED 2026-05-26 — accepted option (a) `unsafe fn` for `*_unchecked` accessors. **SAFETY-rollup clarification (user 2026-05-26):** "SAFETY is coherent, but we will want to roll this up in generation." The codegen emits the `// SAFETY:` comment text (canonical at codegen time, named by the discharging chart invariant per §5.5); the caller's matching `// SAFETY:` at the call site is still required for reviewer evidence. The two-side discipline is preserved; "rolling up in generation" refers to the emitter-side text being canonical and reviewer-consultable once per accessor rather than re-derived per call site. **TCB dual-role note:** this PCDN's ratification elevates the chart-bounds analyzer to two simultaneous trust roles — (i) TCB for chart-bounds proofs generally (INV-SOS-G existing role); (ii) TCB for Rust-emission `unsafe`-review across the whole emitted HAL surface (new role from this PCDN). Downstream safety-case authors MUST cite the chart-bounds analyzer's revision SHA on every Rust HAL safety case. Per the analyzer/annotation-semantics versioned-pair discipline, the analyzer and `SOS-09-A-CONCEPTS.md` rev together: a chart-bounds analyzer build cites the annotation-semantics spec revision it was built against; an annotation-semantics spec amendment requires a paired analyzer build before any new `unsafe`-emission lands.

**Authority cross-reference:** the SAFETY-comment vocabulary cited in §5.5 (`// SAFETY: discharged by chart invariant <sos:id> ...`) and reinforced by this ratification draws its discharging-invariant vocabulary from `SOS-09-A-CONCEPTS.md` (annotation surface — the `sos:id` UUID handle, the chart state path naming, the annotation-semantics governing what counts as a discharged claim). SOS-09-A is the authority for the annotation surface SOS-09-D's `// SAFETY:` comments cite; analyzer-side discharge proofs trace through SOS-09-A's vocabulary to the chart's normative annotations.

**scjson impact:** no scjson changes required for this ratification; `other_attributes` JSON preservation (the SCXML-↔-JSON round-trip discipline established for SOS-09-A) already covers the annotation surface SOS-09-D consumes. The PCDN ratifications expand the §15 + §16 narrative only; the §5 normative-content text remains as-drafted (each recommendation was already encoded as the load-bearing frozen decision).

### 2026-05-26 — SOS09D1 implementation (orchestrator-dispatched)

Implementation of the Rust HAL channel-emit subset landed under commit subject `SOS09D1: extend transliterate_rust.py with HAL emit subset (gates b-k)`. The change is additive — the existing transliteration walker (state-machine emission, datamodel emission, SOS-13 verified-strip post-pass) is unchanged; the SOS-09-D subset is appended as a new emit-path bound to the `ChartAnnotations` input contract.

- **Walker presence (gate b):** new `emit_rust_hal(annotations, *, crate_name, base_address=0x40000000)` returns a file map (`Cargo.toml` + `src/lib.rs`); `emit_rust_hal_from_chart()` is the loader-bound convenience wrapper paralleling `transliterate_svd.emit_svd_from_chart()`; `write_rust_hal_crate()` materialises the map under `output_dir` (the runtime layer points it at `build/rust-hal/<chart_id>/` per INV-S-MEM-2).
- **Layout (gate c) — INV-S-MEM-D-5:** local helper `_hal_channel_size_bytes` mirrors `transliterate_svd._channel_size_bytes` 4-byte-aligned arithmetic. Emitted `src/lib.rs` ships a `const _SOS_09_D_LAYOUT_ASSERTIONS: () = { assert!(core::mem::offset_of!(RegisterBlock, …) == 0x…usize, …); };` block so layout drift becomes a build-stop, not a runtime check. The pytest case `TestGateC_LayoutMatchesSVD::test_layout_matches_svd_emit` cross-checks the emitted HAL offsets against the SVD `<addressOffset>` chain that `transliterate_svd.emit_svd` produces from the same `ChartAnnotations`.
- **Newtype family (gate d) — §5.2:** `_select_wrapper` deterministically maps `(sos:kind, side_effect, clear_on_read)` to the six wrappers (`Status` / `Command` / `Queue` / `Shared` / `ClearOnRead` / `FireOnWrite`). The `_RUST_HAL_PRELUDE` constant carries every wrapper's `#[repr(transparent)]` definition over `vcell::VolatileCell<T>` plus `ContentionError` + `Claimed<'_, T>` (PCDN-D-003 (b)).
- **Type-state (gate e) — §5.3:** the prelude exposes `Shared<T>::claim() -> Result<Claimed<'_, T>, ContentionError>` + `try_claim() -> Option<Claimed<'_, T>>` AND ONLY THESE TWO public methods on `Shared<T>`; the typed region is reachable only through methods on `Claimed<'_, T>` (whose `Drop` releases the underlying `sos_mutex`). The structural shape is the compile-fail guarantee: a driver writing `shared.write(value)` without `claim()` produces "no method `write` found for type `Shared<u32>`".
- **`cargo check` (gate f) — INV-S-MEM-D-4:** the emitted crate's `Cargo.toml` carries `default = ["cortex_m"]` (PCDN-D-004 (b)), `vcell = "0.1"`, and `cortex-m = { version = "0.7", optional = true }`. The pytest case runs `cargo check --no-default-features --target thumbv7em-none-eabihf` against the emitted worked-example crate; SKIP with reason when `cargo` is not on PATH.
- **`*_unchecked` discharge (gate g) — §5.5 + PCDN-D-005 (a):** `_emit_unchecked_variants` walks the channel list and emits `pub unsafe fn <channel>_read_unchecked(reg: &Status<T>) -> T` (or `consume_unchecked` for `ClearOnRead`) for every `kind="status"` channel. The `// SAFETY:` comment names `INV-SOS-G` + the channel's `sos:id` per the user-clarified codegen-rollup discipline. The chart-bounds analyzer is NOT yet wired in (v1 emits a TODO-style rollup); per the analyzer/annotation-semantics versioned-pair discipline, the analyzer's first integration revs alongside this doc + `SOS-09-A-CONCEPTS.md` (see parent CLAUDE.md / orchestrator memory chart-semantics-versioned-pair). Charts with no status channel emit the §12 second-tier "reduced conformance" marker.
- **MPU constants (gate h) — §5.6:** `_emit_mpu_constants` emits `pub const SOS_MPU_<CHANNEL>_REGION: sos_mpu_region_t = sos_mpu_region_t { base_addr: 0x…, size: N, attr: M, perm: P };` for every channel with explicit `sos:zone` (non-default) or `sos:mpu_attr`. A local `sos_mpu_region_t` mirror is emitted so the crate compiles standalone; the runtime-integration crate replaces it with the SOS-09-G-emitted type via the canonical import path.
- **Determinism (gate i) — INV-S-MEM-D-6:** all helpers derive names from `sos:name` only; `sos:id` is confined to the per-channel doc comment + the `// SAFETY:` rollup text (the documented variation surface). `TestGateI_NameDeterminism` proves two-run byte-identical emission AND that two charts differing only in `sos:id` UUIDs produce byte-identical `lib.rs` modulo the documented UUID-bearing surface.
- **Test surface:** new `tools/sos-codegen/tests/test_rust_hal_emit.py` adds 45 tests covering gates (b)–(k). New fixture pair `tools/sos-codegen/tests/fixtures/sos_09_d/worked_example.scxml` + `worked_example_alt_ids.scxml` exercises every newtype wrapper + MPU export path + name-determinism gate.
- **§12 acceptance gates flipped:** (b)–(k) flipped from ⏸ to ✅. Gate (f) carries the CI-environment dependency on `cargo`; the structural gates (b)–(e) + (g)–(k) cover the static-verification surface end-to-end without `cargo`.

**Authority cross-reference (chart-bounds analyzer versioned pair).** The SAFETY-rollup text the emitter ships in v1 cites `INV-SOS-G` + the channel's `sos:id` as a placeholder; the chart-bounds analyzer that would replace the placeholder with an analyzer-discharged invariant name is paired with this doc + `SOS-09-A-CONCEPTS.md` per the analyzer/annotation-semantics versioned-pair discipline (see parent CLAUDE.md / orchestrator memory chart-semantics-versioned-pair). Any subsequent edit to the §5.5 SAFETY-rollup grammar MUST rev this doc and the analyzer together; a SOS-09-A annotation-semantics amendment MUST be followed by a paired analyzer build before any new `unsafe`-emission landing edits this emitter.

**scjson impact:** none. The emitter consumes the SOS-09-A `ChartAnnotations` model directly; the chart-load step is the shared one with SOS-09-B's SVD emitter and the existing transliterate-rust walker, so the SCXML-↔-JSON round-trip surface is unchanged.

(awaiting ratification round — superseded by the 🟢 RATIFIED 2026-05-26 entry above; placeholder retained for institutional memory)
