# SOS-09-G — MPU configuration emission

**Status:** 🟢 **ratified 2026-05-25** — all four PCDNs walked; see §16 ratification entry.

## 0. Authority policy

This phase doc is the **MPU configuration emission** sub-phase under the SOS-09 umbrella (`SOS-09-CONCEPTS.md`, ratified 2026-05-23 with PCDN-SOS-09-001 amended 2026-05-25). The umbrella names seven sub-phases in §6 and freezes the cross-sub-phase decisions (channel-category enum, channel → membrane-primitive mapping, atomicity-class semantics, protection-zone enumeration, register-map artifact priority). This doc takes those decisions as load-bearing input and produces the codegen contract for the ARMv7-M MPU configuration tables driven by chart-declared protection zones.

Per the parent CLAUDE.md "Spec-Before-Code Planning Discipline / Phase document shape":

- **Normative** sections of this doc: §3 glossary, §4 source-of-truth map, §5 frozen decisions (target MPU spec; region descriptor shape; emission outputs; sub-region disable bitmap policy; MPU enable invariant; validation gate), §7 cross-sub-phase invariants (INV-S-MEM-G-1 through INV-S-MEM-G-4), §8 standards integration matrix additions, §9 acceptance gates.
- **Informative** sections: §1 purpose, §2 problem statement, §11 non-goals, §16 change log.
- All keywords MUST, MUST NOT, SHALL, SHOULD, SHOULD NOT, MAY are interpreted per RFC 2119 / RFC 8174 when capitalised.

This doc cites SOS-07 §6 for the cross-phase invariants `INV-SOS-A` through `INV-SOS-H`, SOS-09 §7 for the cross-sub-phase invariants `INV-S-MEM-1` through `INV-S-MEM-6`, and SOS-00 §6 for the curated ARMv7-M primitive bindings. Neither set is re-derived.

Per PCDN-SOS-09-006 (ratified), v1 scope is the ARMv7-M privileged/unprivileged axis only; TrustZone (Cortex-M33 / M55 / M85) is a future extension. Per PCDN-SOS-09-001 amended 2026-05-25, chart annotations are read from the iState `other_attributes` extension surface via `sos:`-prefixed JSON keys — specifically `sos:zone` here.

## 1. Purpose

SOS-09-G is the codegen path producing ARMv7-M MPU configuration tables from chart-declared protection zones. Output: a C array of MPU region descriptors and a Rust constant of the same, both consumed at startup by the SW-side runtime to install per-channel access control.

Without this sub-phase, INV-S-MEM-3 (protection is end-to-end) is unenforceable: SOS-09-E emits the HW-side register-decode gate, but the SW-side MPU configuration that fences unprivileged code out of privileged-channel registers has no canonical emission path. The "PDF cannot lie because the PDF is generated" promise of the SOS-09 umbrella extends to the MPU table here: every entry in the emitted `sos_mpu_table` traces back to a chart channel's `sos:zone` annotation; every chart channel with `sos:zone="privileged"` has a fence on both sides.

## 2. Problem statement

Per SOS-09 §2, the canonical hardware/software co-design failure mode is the register-map PDF that lies. The MPU configuration table is the failure mode's sister artifact — a tangle of `#define`s in startup code (or, more commonly, a CubeMX-generated file the firmware team has hand-edited until it bears no relationship to the originating tool) that nobody has audited end-to-end against the register map it is supposed to fence.

Three concrete pressures inside the SOS-09 emission set motivate this sub-phase:

1. **End-to-end protection pressure.** INV-S-MEM-3 mandates that a chart-declared `privileged` zone be enforced on both sides. SOS-09-E emits the HW gate. Without SOS-09-G, the SW MPU configuration is either hand-rolled (drift), CubeMX-generated (out-of-band), or absent (the chart's protection annotation becomes documentation, not behaviour). The chart-as-source claim only holds if every annotation realises across every artifact.

2. **Per-target MPU surface pressure.** ARMv7-M MPU is not uniform across Cortex-M variants: Cortex-M3 and Cortex-M4 expose 8 MPU regions; Cortex-M7 exposes 16. Cortex-M0+ (when an MPU is present) typically exposes 8. The codegen MUST detect the target and emit the correct table size; mis-sizing produces silent over-protection (when fewer regions than expected are programmed) or a synth-time array bound failure (when more are emitted than the chip has).

3. **Region-shape exactness pressure.** ARMv7-M MPU regions are sized in powers of two (32 B minimum, 4 GB maximum). A chart-declared channel whose register footprint is 128 B at offset 0x100 cannot be fenced by a single 128 B region without padding the start offset — instead, the codegen MUST pick the smallest power-of-two enclosing region (here 256 B aligned to 0x100, or a 512 B region depending on alignment) AND set the 8-bit sub-region disable (SRD) field to mask off the bytes outside the channel footprint. Over-protection (emitting a 1 KB region when a 128 B channel is wanted) is forbidden per INV-S-MEM-G-2 because it leaks address-space layout information to the unprivileged side.

## 3. Canonical glossary

Terms normative within SOS-09-G+. Authority relationships per §8.

| Term | Definition |
|---|---|
| **MPU region descriptor** | A four-tuple `{base_addr, size, attr, perm}` describing one ARMv7-M MPU region. Encoded on hardware as a paired write to `MPU_RBAR` (Region Base Address Register; carries `base_addr` + region number) and `MPU_RASR` (Region Attribute and Size Register; carries `size`, `attr`, `perm`, SRD bitmap, and enable bit). As defined in ARM DDI 0403E.e B3.5; used without modification. |
| **base_addr** | The 32-byte-aligned starting address of an MPU region. For SOS-09-G emission, derived from SOS-09-B's chart-declared address-offset assignment for the channel (after padding to the region's power-of-two alignment). |
| **size** | Power-of-2 region size encoded as the `SIZE` field of `MPU_RASR` (5-bit `log2(size_in_bytes) - 1`; e.g. `0b00100`=32 B, `0b00111`=256 B, `0b11111`=4 GB). Smallest size enclosing the channel's register footprint, padded up. |
| **attr** | The memory attribute bits of `MPU_RASR` (`TEX[2:0]`, `S`, `C`, `B`). At v1, fixed to `Device-nGnRnE` (strongly-ordered, non-cacheable, non-shareable) — i.e. `TEX=0b000`, `S=0`, `C=0`, `B=0`. PCDN-SOS-09-G-003 covers v1 attribute selection. |
| **perm** | The access-permission bits (`AP[2:0]`) of `MPU_RASR`. Derived from the chart-declared `sos:zone`: `privileged` → `AP=0b001` (RW priv, no unpriv access); `unprivileged` → `AP=0b011` (RW full). PCDN-SOS-09-006 freezes the two-zone enumeration at v1. |
| **`sos:zone`** | A SOS-semantic JSON key inside the host element's `other_attributes` JSON, declaring the channel's protection zone. As defined in SOS-09 §5.4 and SOS-09-A §6 (per PCDN-SOS-09-001 amended 2026-05-25); used without modification. The key carries one of two values: `"privileged"` or `"unprivileged"`. |
| **sub-region disable bitmap (SRD)** | The 8-bit `SRD` field of `MPU_RASR` that disables individual one-eighth slices of the region. For SOS-09-G emission, set bits MUST disable sub-regions outside the channel footprint; clear bits MUST keep enabled the sub-regions inside the channel footprint. SRD is only meaningful for region sizes ≥ 256 B. As defined in ARM DDI 0403E.e B3.5.10; used without modification. |
| **BACKGROUND region** | The "default memory map" — when the MPU is enabled with the `PRIVDEFENA` bit of `MPU_CTRL` set, privileged-mode accesses to addresses not covered by any explicit region succeed using the architectural default attributes. Unprivileged accesses to such addresses always fault. As defined in ARM DDI 0403E.e B3.5.5; used without modification. PCDN-SOS-09-G-002 covers v1 background-region policy. |
| **`sos_mpu_table`** | The emitted artifact — a C array of `sos_mpu_region_t` and a parallel Rust constant `SOS_MPU_TABLE: [SosMpuRegion; N]`. Both are consumed by the runtime's `apply_mpu_config()` function. The table is the canonical record of every chart-declared protection-zone realisation. |
| **`apply_mpu_config()`** | The runtime hook emitted alongside the table; programs each region in `sos_mpu_table`, sets the `PRIVDEFENA` bit (per PCDN-SOS-09-G-002), and enables the MPU via `MPU_CTRL.ENABLE`. Idempotent per INV-S-MEM-G-3. (Name reconciled per ERRATA-007 2026-05-27 — historical §16 entries dated before 2026-05-27 retain the earlier `sos_mpu_install()` identifier.) |
| **access-violation event** | The chart-declared status channel that SOS-09-E emits for cross-zone access attempts (per SOS-09 §6 SOS-09-E description, INV-S-MEM-3). When the MPU faults on an unprivileged access to a privileged region, the SW-side handler routes the fault into the same chart-declared event channel, closing the SOS-09-F membrane-vector loop for protection. |
| **region budget** | The number of MPU regions on the target — 8 for Cortex-M3 / M4 / M0+, 16 for Cortex-M7. The codegen detects the target via the build configuration's `target_cpu` and sizes the emitted table accordingly. |

## 4. Source-of-truth map

For every concept this sub-phase touches, **exactly one** location is the canonical authority.

| Concept | Authority |
|---|---|
| Protection-zone enum | `SOS-09-CONCEPTS.md` §5.4 (umbrella, **mirror** here) |
| `sos:zone` chart annotation | `SOS-09-A-CONCEPTS.md` §6 (subordinate, **mirror** here) |
| Channel base address / footprint | `SOS-09-B-CONCEPTS.md` (SVD emission, **compose** here — SOS-09-G consumes B's address-offset assignment as input to region sizing) |
| Channel → membrane-primitive mapping | `SOS-09-CONCEPTS.md` §5.2 (cited not redefined; protection is orthogonal to category) |
| MPU region descriptor encoding | **this doc** (§5.2); ARM DDI 0403E.e B3.5 owns the wire-level grammar (**derive**) |
| Sub-region disable bitmap policy | **this doc** (§5.4) |
| Emission outputs (C array + Rust constant) | **this doc** (§5.3) |
| `apply_mpu_config()` shape | **this doc** (§5.5) |
| Cross-sub-phase invariants INV-S-MEM-G-1 through 4 | **this doc** (§7) |
| Cross-sub-phase invariants INV-S-MEM-1 through 6 | `SOS-09-CONCEPTS.md` §7 (cited, not redefined) |
| Cross-phase invariants INV-SOS-A through H | `SOS-07-CONCEPTS.md` §6 (cited, not redefined) |
| ARMv7-M MPU curated subset | `SOS-00-CONCEPTS.md` §6 (cited, not redefined) — the local distillation **mirror** of the ARM ARM that SOS reviewers consult; SOS-09-G consumes the same curated surface |
| `cortex-m` crate `cortex_m::peripheral::MPU` API | external — `cortex-m` v0.7.x; SOS-09-G emits code that calls `MPU::set_region` (or equivalent) (**mirror** per §8) |
| CMSIS-Core `MPU_RBAR` / `MPU_RASR` register encoding | external — CMSIS-Core 5.9.0+ (**mirror** per §8) |
| Validation cocotb framework | `SOS-09-F-CONCEPTS.md` (sister sub-phase; SOS-09-G emits the MPU table that the SOS-09-F protection-vector exercises) |

## 5. Frozen decisions

### 5.1 Target MPU spec

Per PCDN-SOS-09-006 (ratified at the umbrella): SOS-09-G v1 targets the **ARMv7-M MPU** (Cortex-M3 / M4 / M7 / M0+ when present). Specifically:

- **Cortex-M3, Cortex-M4, Cortex-M0+**: **8 MPU regions** (CMSIS `MPU_REGION_NUMBER` 0–7).
- **Cortex-M7**: **16 MPU regions** (CMSIS `MPU_REGION_NUMBER` 0–15).

The codegen detects the target via the build configuration's `target_cpu` and emits the correct table size per-target. Targets with fewer regions than the chart declares produce a hard error per PCDN-SOS-09-G-001 (recommendation: hard error at v1; merging contiguous same-perm regions is a follow-on optimisation).

TrustZone (Cortex-M33 / M55 / M85) is **out of scope** at v1 per PCDN-SOS-09-006 — the four-zone secure/non-secure × privileged/unprivileged model lands when a Cortex-M33+ target enters the SOS bench substrate.

Frozen-enumeration registration policy: **Standards Action** (per parent CLAUDE.md; adding a target widens the codegen's reach and requires cross-phase consensus).

### 5.2 Region descriptor shape

Each chart-declared channel maps to one MPU region descriptor tuple `{base_addr, size, attr, perm}`. Encoded on hardware as a paired write to `MPU_RBAR` + `MPU_RASR` (per ARM DDI 0403E.e B3.5).

- **`base_addr`**: derived from SOS-09-B's chart-declared address-offset assignment for the channel. MUST be aligned to the region `size` (architectural requirement; ARM ARM B3.5.7). If the channel's natural offset is not aligned, the codegen pads the region down to the next aligned boundary AND uses SRD per §5.4 to mask the unused sub-regions.
- **`size`**: smallest power of two enclosing the channel's register footprint, padded up to satisfy alignment. Encoded as `log2(size_in_bytes) - 1` in the `SIZE` field of `MPU_RASR` (5 bits). Minimum 32 B (`SIZE=0b00100`), maximum 4 GB (`SIZE=0b11111`).
- **`attr`**: Per PCDN-SOS-09-G-003 ratification 2026-05-25 (narrowed scope): the default attribute depends on the **portion** of the channel being covered.
  - The **register portion** of any channel (status / command / queue) → **`Device-nGnRnE`** (strongly-ordered, non-cacheable, non-shareable). Encoded as `TEX=0b000`, `S=0`, `C=0`, `B=0` in `MPU_RASR`.
  - The **shared-channel datamodel portion** (the DPRAM-backed shared memory belonging to a `kind="shared"` channel) → **`Normal Cacheable`** to allow the MPU-protected side to participate in normal cacheable operations on shared memory. Encoded as `TEX=0b001`, `S=1`, `C=1`, `B=1` (typical write-back / write-allocate; precise encoding lives in §5.4-adjacent emission code, mirrored from CMSIS-Core's `ARM_MPU_RASR_EX` helper macros).
  - **Non-shared SCXML datamodel stays OUTSIDE the MPU table** (covered by the background region per §5.5, PCDN-SOS-09-G-002 ratification).
  - **Chart-author override.** A `sos:mpu_attr` annotation on a channel via `other_attributes` overrides the default. Permitted values per PCDN-SOS-09-G-003 ratification 2026-05-25: `cacheable`, `non_cacheable`, `device_ngnrne`, `device_ngnre`. **Scope-inheritance semantics**: `sos:mpu_attr` declared on a parent element propagates to child shared-datamodel items; a child-element declaration overrides the parent.
- **`perm`**: derived from the chart-declared `sos:zone` per the following mapping (encoded as `AP[2:0]` in `MPU_RASR`, per ARM DDI 0403E.e B3.5.6 Table B3-15):
  - `sos:zone="privileged"` → `AP=0b001` (RW priv, no unpriv access — "Privileged Access only").
  - `sos:zone="unprivileged"` → `AP=0b011` (RW full — "Full Access").

The XN (Execute Never) bit MUST be set to 1 for all SOS-09-G-emitted regions covering register portions — register-mapped peripherals are not code. For shared-channel datamodel regions, XN MUST also be set to 1 — shared data is not code either. The TYPEEXT bit and the C/B/S sub-fields default to the `Device-nGnRnE` shape for register portions and to the `Normal Cacheable` shape for shared-datamodel portions per the attribute rules above.

**Coverage scope (PCDN-SOS-09-G-003 ratification 2026-05-25, narrowed).** The MPU table covers exactly two categories of regions:

1. **Register channels** — every SOS-09 channel with `kind ∈ {status, command, queue}`, plus the `shared` channel's chart-top register surface (the register portion of the shared channel — the doorbell / status / size registers, not the DPRAM payload).
2. **Shared-channel datamodel scopes** — M shared-datamodel regions, **one per `shared`-channel's datamodel scope** (NOT per-item; regions aggregate per the channel they belong to).

**Non-shared SCXML datamodel stays OUTSIDE the MPU table.** Items in the chart's `<datamodel>` that are NOT part of a `shared` channel are covered by the background region (per PCDN-SOS-09-G-002 ratification — `PRIVDEFENA=1` kernel-mode default).

Frozen-enumeration registration policy: **Standards Action**.

### 5.3 Emission outputs

For every chart-declared protection-zone realisation, SOS-09-G emits:

- **C array** in `<chart>_mpu.h` + `<chart>_mpu.c`:
  ```c
  typedef struct {
      uint32_t base_addr;
      uint32_t size_log2;    /* SIZE field value: log2(size_in_bytes) - 1 */
      uint32_t attr;         /* {TEX,S,C,B,XN} packed */
      uint32_t perm;         /* AP[2:0] */
      uint8_t  srd;          /* sub-region disable bitmap */
      uint8_t  region_num;   /* MPU_REGION_NUMBER */
      uint16_t _reserved;
  } sos_mpu_region_t;

  static const sos_mpu_region_t sos_mpu_table[] = { /* ... */ };
  static const size_t sos_mpu_table_len = N;

  void apply_mpu_config(void);
  ```

- **Rust constant** in `<chart>_mpu.rs`:
  ```rust
  pub struct SosMpuRegion {
      pub base_addr: u32,
      pub size_log2: u32,
      pub attr: u32,
      pub perm: u32,
      pub srd: u8,
      pub region_num: u8,
  }

  pub const SOS_MPU_TABLE: [SosMpuRegion; N] = [ /* ... */ ];

  pub fn apply_mpu_config();
  ```

Both files include CMSIS / `cortex-m`-crate-compatible accessors that the runtime can pass to `MPU::set_region()` (Rust) or `ARM_MPU_SetRegion()` (CMSIS-Core C) directly. The accessor wrappers compose `base_addr | (region_num << 0) | (1 << 4)` (the `VALID` bit) for `MPU_RBAR` and the `MPU_RASR` packed encoding from `size_log2`, `attr`, `perm`, and `srd`.

Frozen-enumeration registration policy: **Specification Required** (the output-file naming convention is a phase-local mechanic; widening the emission set — e.g. adding a SystemRDL-companion or a debugger-side annotation — is a phase-owner walkthrough update, not a §16 amendment).

### 5.4 Sub-region disable bitmap policy

ARMv7-M MPU regions of size ≥ 256 B carry an 8-bit `SRD` field that disables individual one-eighth slices. SOS-09-G's emitter MUST use SRD to keep region shapes exact-to-channel:

- Set SRD bits for sub-regions **outside** the channel's register footprint.
- Clear SRD bits for sub-regions **inside** the channel's register footprint.

This keeps the emitted region shape exact-to-channel rather than over-protecting. Over-protection is forbidden per INV-S-MEM-G-2 because the unprivileged side, by attempting reads/writes to the over-protected bytes, can infer which sub-regions are masked vs which are channel-mapped — leaking address-space layout information.

For region sizes < 256 B (the 32 B, 64 B, 128 B sizes), SRD is not architecturally meaningful (the field exists in `MPU_RASR` but has no effect for sub-256 B regions per ARM DDI 0403E.e B3.5.10). The emitter MUST emit SRD=0 for such regions and rely on the region size matching the channel footprint exactly (which forces base-address-alignment friction — the chart-author is responsible for SOS-09-B placement that respects 32 B / 64 B / 128 B natural alignment for sub-256 B channels).

Frozen-enumeration registration policy: **Standards Action**.

### 5.5 MPU enable invariant — `apply_mpu_config()` shape

**Chart-root annotation key (PCDN-SOS-09-G-002 ratification 2026-05-25).** The chart's root `<scxml>` element MAY carry a `sos:mpu_background` key in `other_attributes` with value `"kernel_default"` or `"strict"`. When absent, the default is `"kernel_default"` (background region enabled for privileged accesses; `PRIVDEFENA=1`). `"strict"` disables the background region (`PRIVDEFENA=0`) — every accessed address must lie in an explicit region. Per the user clarification at the ratification session, "secure by default" is an **iState user setting** (UI-level default that gets injected into new charts at create time), NOT a build-time codegen flag — codegen reads whatever the chart's `sos:mpu_background` says at codegen time; absent = `kernel_default`. No CodeBuild env var or `--mpu-background=...` codegen flag exists.

Emitted runtime hooks include an `apply_mpu_config()` function with the following behaviour:

1. Disable MPU (`MPU_CTRL.ENABLE = 0`) before reconfiguration.
2. For each row in `sos_mpu_table`: write `MPU_RBAR` with `base_addr | VALID=1 | REGION=region_num`; write `MPU_RASR` with the packed `{size_log2, attr, perm, srd, ENABLE=1}` encoding.
3. Disable any unused region slots (`MPU_RBAR` write with `REGION=k` and `MPU_RASR.ENABLE=0`) so that prior boot state cannot leak into an undeclared region.
4. Set `PRIVDEFENA` in `MPU_CTRL` according to the chart's `sos:mpu_background` value (per PCDN-SOS-09-G-002 ratification 2026-05-25): `kernel_default` (absent or explicit) → `PRIVDEFENA=1`; `strict` → `PRIVDEFENA=0`. Set `HFNMIENA=0` (MPU disabled for HardFault / NMI / FAULTMASK handlers) per ARM ARM default.
5. Set `MPU_CTRL.ENABLE = 1`.
6. Issue `DSB` then `ISB` to ensure the MPU is in effect before the next instruction fetch.

The hook is **idempotent**: calling `apply_mpu_config()` multiple times produces the same MPU register state (the second and subsequent calls overwrite identical values). INV-S-MEM-G-3 formalises this.

Frozen-enumeration registration policy: **Specification Required** (the install sequence is normative; tweaks to the disable-other-slots step or the barrier ordering are phase-local mechanics).

### 5.6 Validation gate

Per PCDN-SOS-09-005 (ratified at the umbrella): the v1 co-simulation framework is **cocotb-with-Python-CPU-stub**. SOS-09-G's validation gate, riding the same framework via SOS-09-F's membrane-vector emission:

- The cocotb test drives an unprivileged access from the SW-stub against a chart-declared `sos:zone="privileged"` region.
- The MPU table emitted by SOS-09-G is loaded into the SW-stub's region-decode model.
- The MPU fault path fires (the stub raises the chart-declared `MemManage` event); the chart-declared access-violation `<sos:status>` channel that SOS-09-E emits receives the fault notification.
- The cocotb test asserts the access-violation channel state, naming the chart channel and the originating chart state per INV-SOS-H.

This closes the SOS-09-F membrane vector loop for protection per umbrella §6. Acceptance gate (b) below.

Frozen-enumeration registration policy: **Standards Action**.

## 6. (Reserved — emission-walker contract; lives in implementation phase)

The per-walker emission shape (which iState walker visits which annotation, how SOS-09-B's address-offset assignment is consumed, how the SOS-09-F protection vector is paired with the table emission) is the implementation phase's territory — out of scope for this concepts doc. The contract surface is normative in §5; the walker that satisfies it is informative until the implementation phase lands.

## 7. Cross-sub-phase invariants — INV-S-MEM-G-1 through INV-S-MEM-G-4

In addition to the cross-phase invariants INV-SOS-A through H (from SOS-07) and the SOS-09 cross-sub-phase invariants INV-S-MEM-1 through 6 (cited but not redefined), the following invariants are normative across SOS-09-G:

- **INV-S-MEM-G-1 — Every privileged channel has an MPU region.** Every chart channel with `sos:zone="privileged"` MUST have an entry in `sos_mpu_table` whose `perm` denies unprivileged access (i.e. `AP=0b001`). Channels with `sos:zone="unprivileged"` MAY have an entry (for explicit `AP=0b011` declaration) or MAY rely on the background region (per PCDN-SOS-09-G-002); the chart-as-source claim only depends on the privileged side being fenced. Verified by SOS-09-F membrane vectors per acceptance gate (b).

- **INV-S-MEM-G-2 — Regions are sized exactly to the chart-declared channel footprint.** SOS-09-G's emitter MUST size each region to the smallest power-of-two enclosing the channel's register footprint AND use the SRD field per §5.4 to mask sub-regions outside the footprint. Over-protection (emitting a region larger than the channel needs, with SRD bits clear over the unused sub-regions) is **forbidden**: it leaks address-space layout information to the unprivileged side, since the unprivileged side can probe which bytes outside the channel are also fenced and infer the surrounding address-space shape.

- **INV-S-MEM-G-3 — `apply_mpu_config()` is idempotent.** Calling `apply_mpu_config()` multiple times produces the same MPU register state. Verified by acceptance gate (c) — the test scaffolding calls the hook twice and asserts register-state-equivalence.

- **INV-S-MEM-G-4 — Protection violations route to the chart-declared access-violation event.** The cocotb co-sim demonstrates that an unprivileged access to a privileged region fires the chart-declared access-violation event channel (the same `<sos:status>` channel that SOS-09-E emits for HW-side cross-zone access). This closes the SOS-09-F membrane vector for protection per umbrella §6. Verified by acceptance gate (b).

Frozen-enumeration registration policy: **Standards Action**.

## 8. Standards integration matrix additions

The following rows EXTEND the SOS-07 §7 and SOS-09 §8 matrices:

| Concept | Upstream authority | Local relationship | Phase that declares it | Mutation rights |
|---|---|---|---|---|
| ARMv7-M MPU spec (ARM DDI 0403E.e B3.5) | ARM (ARMv7-M Architecture Reference Manual) | **derive** (SOS-09-G emits MPU configurations valid per the ARM ARM; ARM owns the spec) | SOS-09-G | none — ARM ARM is upstream |
| CMSIS-Core `MPU_RBAR` / `MPU_RASR` register encoding | ARM (CMSIS 5.9.0+) | **mirror** (the wire-level encoding fields and bit positions are CMSIS-Core's; SOS-09-G emits the same values without divergence) | SOS-09-G | none — CMSIS encoding is upstream |
| `cortex-m` crate `cortex_m::peripheral::MPU` API | open project (Rust embedded WG; cortex-m v0.7.x) | **mirror** (Rust runtime side; SOS-09-G's emitted Rust calls into the upstream `MPU::set_region` shape without modification) | SOS-09-G | none — `cortex-m` API is upstream |
| SOS-09-A `sos:zone` annotation | this repo, SOS-09-A | **mirror** (consumed without modification; SOS-09-G reads the chart-declared zone from `other_attributes` JSON per PCDN-SOS-09-001 amended 2026-05-25) | SOS-09-G | none — SOS-09-A owns the annotation surface |
| SOS-09-B address-offset assignment | this repo, SOS-09-B | **compose** (SOS-09-G uses B's chart-declared offsets as input to region sizing; B's emission is upstream within SOS-09) | SOS-09-G | none — SOS-09-B owns the offsets |
| SOS-00 §6 ARMv7-M MPU curated subset | this repo, SOS-00 | **mirror** (the SOS-internal curated subset of the ARM ARM that SOS-09-G consumes; SOS-00 §6 IS the local authority per SOS-09 §8) | SOS-09-G | none — SOS-00 §6 is the curated upstream |

Per INV-SOS-E, the row addition policy is **Specification Required** for adding new rows (phase-owner walkthrough), **Standards Action** for modifying an existing row's relationship value.

## 9. Acceptance gates

A conforming SOS-09-G v1 ratification satisfies:

- **(a) Codegen output compiles.** The emitted C array + Rust constant emit pass `clang -Wall -Wextra -Wpedantic -std=c11` (C side) and `cargo check --target thumbv7em-none-eabihf` (Rust side) respectively. The Rust emission targets the `cortex-m` v0.7.x peripheral API; the C emission targets CMSIS-Core 5.9.0+.

- **(b) Cocotb membrane vector for protection violation passes.** Per PCDN-SOS-09-005's cocotb-with-Python-CPU-stub framework: an unprivileged-access vector against a chart-declared `sos:zone="privileged"` region routes through the emitted MPU table, fires the chart-declared access-violation event, and renders the failure in chart vocabulary per INV-SOS-H (`"channel <name> in zone privileged rejected an unprivileged access from chart state <state>"`).

- **(c) Idempotency demonstrated.** Test scaffolding calls `apply_mpu_config()` twice in sequence; asserts MPU register state (`MPU_RBAR`, `MPU_RASR`, `MPU_CTRL`) equivalence between the two post-call snapshots. Closes INV-S-MEM-G-3.

- **(d) Bench validation deferred.** At least one bench-validation on a target ARMv7-M MPU (Cortex-M7 on the disco-analyzer board per SOS-00 §6's bench-substrate citation) is **deferred to a follow-on** with bench access. Gate (d) is the "implementation-tier" gate; the spec-tier acceptance is (a)–(c).

(a)–(c) are the ratification gates; (d) is the implementation gate that flips from ⏸ to ✅ when bench access is available.

A conforming SOS-09-G ratification *without* bench validation satisfies (a)–(c); this second-tier conformance level is the expected ratification state at the next acceptance review.

## 10. Reconciliation decisions vs adjacent repo primitives

### vs. SOS-09 umbrella §5.4 (protection-zone enum)

SOS-09 §5.4 freezes `{ privileged, unprivileged }` at v1 per PCDN-SOS-09-006. SOS-09-G's `perm` derivation in §5.2 mirrors this enum: `privileged` → `AP=0b001`; `unprivileged` → `AP=0b011`. The two values are the AP encoding from ARM DDI 0403E.e B3.5.6 Table B3-15; SOS-09-G owns the mapping, but the underlying AP encoding is ARM's.

### vs. SOS-09 umbrella §6 SOS-09-E (HDL register-file RTL)

SOS-09-E emits the HW-side gate (register-decode logic that rejects cross-zone access at the bus interface). SOS-09-G emits the SW-side gate (MPU configuration that fences the unprivileged side from privileged-channel registers). INV-S-MEM-3 (protection is end-to-end) requires both to be present; SOS-09's codegen refuses to emit one without the other. Reconciliation: the two sub-phases share no code; they share the chart annotation (`sos:zone`) as the single source. INV-S-MEM-1 (single-source register definition) is satisfied.

### vs. SOS-09 umbrella §6 SOS-09-F (membrane vectors)

SOS-09-F authors the cocotb co-sim framework and the six membrane-vector shapes (initial-value-read, write-then-read, side-effect, clear-on-read, atomicity, protection). SOS-09-G's acceptance gate (b) consumes SOS-09-F's protection vector shape; the table emitted by SOS-09-G is the table the protection vector exercises. Reconciliation: SOS-09-F owns the vector framework; SOS-09-G is one consumer.

### vs. SOS-00 §6 (ARMv7-M MPU curated subset)

SOS-00 §6 owns the curated ARMv7-M MPU subset SOS reviewers consult (per INV-S1; the ARM ARM is not a regular crawl target). SOS-09-G consumes the same curated surface — the MPU register names, the AP encoding table, the SRD semantics — without re-deriving them. Reconciliation: SOS-00 is upstream; SOS-09-G is downstream within this repo. The `mirror` row in §8 records this.

### vs. INV-SOS-A (chart-as-source) + INV-S-MEM-1 (single-source register definition)

The MPU table is a build output: every entry traces back to a chart channel's `sos:zone`. INV-SOS-A (chart-as-source) and INV-S-MEM-1 (single-source register definition) are both **mirror** — SOS-09-G owns no new chart-source claim; it owns one new artifact emitted from the existing chart source.

## 11. Non-goals

This sub-phase does NOT:

- Target ARMv8-M MPU (Cortex-M23 / M33 / M55 / M85). The ARMv8-M MPU has a different region-descriptor encoding (no power-of-2-size restriction; explicit base/limit addresses) and a different protection model (secure / non-secure TrustZone partitioning). v1 stays ARMv7-M-only; v2 (when a Cortex-M33+ target enters the SOS bench substrate) lands as its own sub-phase.
- Target ARMv7-R MPU (Cortex-R). Different exception model, different cache integration. Out of scope.
- Author cache attribute overrides. The `attr` field is fixed to `Device-nGnRnE` at v1 per PCDN-SOS-09-G-003. Cacheable / write-back / shareable variants are deferred.
- Configure the MPU at runtime beyond the initial install. Dynamic region reprogramming (per-task MPU layouts, MPU-context-switch on PendSV) is a SOS-04 / SOS-05 runtime concern that may compose `sos_mpu_table` as one of several layouts, but the dynamic-layout machinery is not SOS-09-G's responsibility.
- Emit MPU configurations for memory regions outside the chart-declared channel set. SRAM, flash, DTCM, ITCM regions are owned by SOS-04 / SOS-05 startup code (linker-script-driven). SOS-09-G owns the chart-channel side only.
- Verify physical metastability in the formal model. Per INV-S-HDL-3 (from SOS-08 §7), `sos_synchronizer` flops are excluded from formal proof; SOS-09-G inherits this exclusion via the HW-side gate it pairs with.
- Add a third protection zone at v1. The `{ privileged, unprivileged }` enum is frozen at v1 per PCDN-SOS-09-006. Future TrustZone-style extensions are gated by SOS-09 §5.4's Standards Action policy.

## 12. (Reserved — implementation acceptance lives in §9.)

§12 is intentionally empty in this concepts doc; the implementation-acceptance gates live in §9. (The phase document shape per parent CLAUDE.md names §12 acceptance — SOS-09-G consolidates this into §9 because the gates are already in concrete-acceptance form. §12's intended slot is preserved as informative-reserved.)

## 13. Files cited

| Path | Role |
|---|---|
| `docs/concepts/SOS-09-CONCEPTS.md` | Umbrella; this sub-phase's parent. |
| `docs/concepts/SOS-09-A-CONCEPTS.md` | Chart annotation surface; SOS-09-G consumes the `sos:zone` annotation from there. |
| `docs/concepts/SOS-09-B-CONCEPTS.md` | CMSIS-SVD emission; SOS-09-G consumes B's address-offset assignment. |
| `docs/concepts/SOS-09-E-CONCEPTS.md` | HDL register-file RTL; sister sub-phase emitting the HW-side gate (protection end-to-end per INV-S-MEM-3). |
| `docs/concepts/SOS-09-F-CONCEPTS.md` | Membrane vectors; SOS-09-G's acceptance gate (b) rides SOS-09-F's protection-vector emission. |
| `docs/concepts/SOS-07-CONCEPTS.md` | Cross-phase invariants INV-SOS-A through H; cited not redefined. |
| `docs/concepts/SOS-00-CONCEPTS.md` | M7 primitive contract; §6 owns the ARMv7-M MPU curated subset SOS-09-G mirrors. |
| `tools/sos-codegen/tests/test_sos_09_g_concepts_doc.py` | Per-doc-assertion test module. |
| Parent `CLAUDE.md` | Spec-Before-Code Planning Discipline; Phase document shape. |

## 14. Unblocks

This sub-phase's ratification (after PCDN walkthrough) unblocks:

- **SOS-09 acceptance gate (b)** — chart channel with `sos:zone` annotation emits all six artifacts including the MPU table.
- **SOS-09-F acceptance gate** — the protection membrane vector has a concrete MPU-table consumer to exercise.
- **The first end-to-end chart-driven SoC bring-up demo** with protection — chart → CMSIS-SVD + Rust HAL + HDL register file + MPU table + membrane vectors → Yosys+nextpnr ECP5 bitstream + Cortex-M target, with the chart as the single source for both HW gate and SW MPU fence.
- **INV-S-MEM-3 (protection is end-to-end)** becomes enforceable in the codegen — without SOS-09-G, SOS-09's codegen would silently emit the HW-side gate alone, leaving the SW side unfenced.

## 15. Pending Concept Decision Notices (PCDNs)

These are the open questions whose resolution moves this doc from 🟡 drafted to 🟢 ratified. The PCDN-SOS-09-G-* identifiers are stable per parent CLAUDE.md "Errata Open Question" naming.

Frozen-enumeration registration policy for all four PCDNs below: **Standards Action** (each touches a load-bearing decision either on the cross-target axis or on the protection-end-to-end invariant; later relaxation requires a §16 amendment).

- **PCDN-SOS-09-G-001 — Region budget overflow policy.** 🟢 **ratified 2026-05-25 — see §16 ratification entry below.** If a chart declares more protected regions than the target MPU has, is the emit a hard error or does the codegen attempt to merge contiguous same-perm regions? **Note (per ratification 2026-05-25)**: the region count is (N register channels) + (M shared-datamodel scopes), NOT (N register channels + all SCXML datamodel items) — non-shared SCXML datamodel stays outside the MPU table (covered by the background region per PCDN-SOS-09-G-002). **Recommendation**: hard error at v1 with an explicit "increase target MPU or reduce protected-region count" message; merging is a follow-on optimisation. Rationale: silent merging breaks INV-S-MEM-G-2 (regions are sized exactly to the chart-declared channel footprint) because merged regions span addresses outside any single channel's footprint; the chart-author should make the merge intent explicit by combining channels rather than relying on the codegen to do it.

- **PCDN-SOS-09-G-002 — Background region policy.** 🟢 **ratified 2026-05-25 — see §16 ratification entry below.** Enable (`PRIVDEFENA=1` — kernel-mode access outside chart regions succeeds via the architectural default memory map) vs disable (`PRIVDEFENA=0` — strict; kernel must also map regions for every address it accesses, including SRAM / flash / peripherals not declared in the chart). **Recommendation**: kernel-mode default (`PRIVDEFENA=1`) when the chart doesn't specify; chart-root `other_attributes` switch `sos:mpu_background="kernel_default" | "strict"` allows explicit override. Per the ratification 2026-05-25, "secure by default" is an **iState user setting** (UI-level default that gets injected into new charts at create time), NOT a build-time codegen flag — codegen reads whatever the chart says. Rationale: kernel code is trusted by construction in the SOS model; chart-authors who want a sandboxed-kernel deployment opt-in via `sos:mpu_background="strict"`.

- **PCDN-SOS-09-G-003 — Memory attribute selection.** 🟢 **ratified 2026-05-25 — see §16 ratification entry below.** `Device-nGnRnE` (strongly-ordered) vs `Device-nGnRE` (no early write acknowledge but ordered) vs `Normal Non-cacheable` vs `Normal Cacheable`. **Narrowed scope (per ratification 2026-05-25 — "only shared get the datamodel treatment")**: register portions of any channel (status / command / queue, and the `shared` channel's chart-top register surface) → `Device-nGnRnE`; **`shared`-channel datamodel scopes** (the DPRAM-backed shared memory) → `Normal Cacheable` to allow the MPU-protected side to participate in normal cacheable operations on shared memory; non-shared SCXML datamodel stays outside the MPU table (covered by background region). **New chart-author override key**: `sos:mpu_attr` declared on a channel via `other_attributes`, valid values: `cacheable`, `non_cacheable`, `device_ngnrne`, `device_ngnre`. Override semantics: declared on a parent element propagates to child shared-datamodel items (scope inheritance); child-element declaration overrides parent. Region aggregation along shared seams: M shared-datamodel regions, one per `shared`-channel's datamodel scope (NOT per-item; aggregated by the channel they belong to).

- **PCDN-SOS-09-G-004 — Per-target attribute differences.** 🟢 **ratified 2026-05-25 — see §16 ratification entry below.** Cortex-M7 has additional memory attributes vs Cortex-M3 / M4 (cacheability, shareability, TEX[2:0] sub-types per ARM DDI 0403E.e B3.5.6 Table B3-13). Chart-author exposed (per-target attribute set) vs codegen-fixed (the per-portion defaults of G-003 work on all ARMv7-M targets uniformly)? **Recommendation**: codegen-fixed at v1. The full vendor-attribute-set chart-author exposure is a future "more general vendor support pass" — likely lands as part of broader vendor onboarding work (Cortex-M33+ TrustZone, custom Lattice attributes, etc.), not standalone. Rationale: the codegen-fixed defaults work on all ARMv7-M targets without per-target chart-author intervention; the chart stays target-agnostic per INV-S15 (SOS-00 §10).

## 16. Change log

### 2026-05-25 — Initial draft (Ira)

- Authored `SOS-09-G-CONCEPTS.md` as the MPU configuration emission sub-phase under the SOS-09 umbrella.
- §3 canonical glossary: terms `MPU region descriptor`, `base_addr`, `size`, `attr`, `perm`, `sos:zone`, `sub-region disable bitmap (SRD)`, `BACKGROUND region`, `sos_mpu_table`, `sos_mpu_install()`, `access-violation event`, `region budget`.
- §4 source-of-truth map: chart annotation surface (mirror from SOS-09-A); address-offset assignment (compose from SOS-09-B); MPU region descriptor encoding (derive from ARM ARM); emission outputs + install hook (this doc); validation cocotb framework (compose from SOS-09-F).
- §5 frozen decisions: ARMv7-M MPU target (8 regions M3/M4/M0+, 16 regions M7); region descriptor shape `{base_addr, size, attr, perm}` with `Device-nGnRnE` attribute and `AP=0b001` / `AP=0b011` permission encoding for `privileged` / `unprivileged`; C array + Rust constant emission shape; SRD bitmap policy (mask outside-footprint sub-regions; over-protection forbidden per INV-S-MEM-G-2); `sos_mpu_install()` idempotent install hook with `PRIVDEFENA=1`; cocotb-with-Python-CPU-stub validation gate.
- §7 cross-sub-phase invariants INV-S-MEM-G-1 through INV-S-MEM-G-4: every privileged channel has an MPU region with `AP=0b001`; regions are exact-to-footprint; `sos_mpu_install()` is idempotent; protection violations route to the chart-declared access-violation event.
- §8 standards integration matrix additions: ARMv7-M MPU spec (ARM DDI 0403E.e) — derive; CMSIS-Core MPU register encoding — mirror; `cortex-m` crate MPU API — mirror; `sos:zone` annotation — mirror; SOS-09-B address offsets — compose; SOS-00 §6 curated subset — mirror.
- §9 acceptance gates (a) codegen compiles under clang + cargo check; (b) cocotb protection vector passes; (c) idempotency demonstrated; (d) bench validation deferred.
- §10 reconciliation vs SOS-09 umbrella §5.4 / §6 SOS-09-E / SOS-09-F / SOS-00 §6 / INV-SOS-A.
- §15 four PCDNs raised: region budget overflow policy; background region policy; memory attribute selection; per-target attribute differences. All recommendations toward strict / safe defaults with explicit chart-override-or-future-amendment escape hatches.

Status: 🟡 **drafted**, awaiting PCDN walkthrough.

### 2026-05-25 — Ratified (Ira)

All four PCDNs walked and resolved in a ratification session 2026-05-25. PCDN-SOS-09-G-001, -002, and -003 carry amendment language; PCDN-SOS-09-G-004 ratified as-is.

| PCDN | Resolution | Registration policy |
|---|---|---|
| **PCDN-SOS-09-G-001 — Region budget overflow policy** | ✅ Hard error when region budget overflows; explicit "increase target MPU or reduce protected-region count" message. **Per the narrowed scope of G-003**: the region count is (N register channels) + (M shared-datamodel scopes), NOT (N register channels + all SCXML datamodel items). Non-shared SCXML datamodel stays outside the MPU table (covered by the background region per G-002). | Standards Action |
| **PCDN-SOS-09-G-002 — Background region policy** | ✅ Kernel-mode default (`PRIVDEFENA=1`) when the chart doesn't specify. **Chart-root `other_attributes` switch added**: `sos:mpu_background="kernel_default" | "strict"`. "Secure by default" becomes an **iState user setting** (UI-level default that gets injected into new charts at create time), NOT a build-time codegen flag — codegen reads whatever the chart's `sos:mpu_background` says at codegen time; absent = `kernel_default`. No CodeBuild env var, no `--mpu-background=...` codegen flag. | Standards Action |
| **PCDN-SOS-09-G-003 — Memory attribute selection** | ✅ Ratified with **NARROWED scope vs the original PCDN**. Registers (SOS-09 channels with `kind ∈ {status, command, queue}`, AND the `shared` channel's chart-top register surface) get `Device-nGnRnE`. **The `shared` channel's datamodel-aggregated region (the DPRAM-backed shared memory) gets `Normal Cacheable`** to allow the MPU-protected side to participate in normal cacheable operations on shared memory. **Non-shared SCXML datamodel stays OUTSIDE the MPU table** — covered by the background region (per G-002 default). **New chart-author override key**: `sos:mpu_attr` declared on a channel via `other_attributes`, valid values: `cacheable`, `non_cacheable`, `device_ngnrne`, `device_ngnre`. Override semantics: declared on a parent element propagates to child shared-datamodel items (scope inheritance); child-element declaration overrides parent. **Region aggregation along shared seams**: M shared-datamodel regions, one per `shared`-channel's datamodel scope (NOT per-item; aggregated by the channel they belong to). This narrowing was a key clarification — the user explicitly said "only shared get the datamodel treatment". | Standards Action |
| **PCDN-SOS-09-G-004 — Per-target attribute differences** | ✅ Codegen-fixed at v1. The full vendor-attribute-set chart-author exposure is a future "more general vendor support pass" — likely lands as part of broader vendor onboarding work (Cortex-M33+ TrustZone, custom Lattice attributes, etc.), not standalone. | Standards Action |

**New chart-level annotation keys introduced.**

- `sos:mpu_background` (chart-root only) — per PCDN-SOS-09-G-002 ratification. Values: `kernel_default` (default) / `strict`.
- `sos:mpu_attr` (per channel / per shared-datamodel item) — per PCDN-SOS-09-G-003 ratification. Values: `cacheable` / `non_cacheable` / `device_ngnrne` / `device_ngnre`. Scope-inheritance semantics.

**Spec amendments landing with this ratification.**

- **§5.2 attr derivation.** The `attr` rule split per portion: register portion → `Device-nGnRnE`; shared-channel datamodel portion → `Normal Cacheable`; non-shared SCXML datamodel → not in the MPU table. Chart-author `sos:mpu_attr` override added with scope-inheritance semantics.
- **§5.2 coverage scope.** New paragraph naming the two MPU-table categories (register channels + shared-channel datamodel scopes) and explicitly excluding non-shared SCXML datamodel.
- **§5.5 `sos:mpu_background` chart-root key.** New annotation key on the chart's root `<scxml>` element controlling `PRIVDEFENA`. Codegen reads the chart; no codegen flag. iState injects the user-preference default at chart-create time.
- **§5.5 `sos_mpu_install()` step 4.** Updated to read `sos:mpu_background` from the chart instead of hard-coding `PRIVDEFENA=1`.

Status: 🟢 **ratified**. SOS-09-G's MPU configuration emission contract is stable; the protection end-to-end claim (INV-S-MEM-3) is now codified across both the HW gate (SOS-09-E) and the SW MPU fence (this sub-phase). Implementation work on `tools/sos-codegen/mpu_emit.py` is unblocked.

### 2026-05-27 — SOS09G1 implementation entry + cite reconciliation (ERRATA-002)

The 2026-05-25 ratification entry's closing line forecast the implementation path as `tools/sos-codegen/mpu_emit.py`. The SOS09G1 implementation (commit `1759cb1`, "SOS09G1: implement MPU configuration emitter (SOS-09-G foundation)") shipped as `tools/sos-codegen/transliterate_mpu.py` to align with the sibling family convention (`transliterate_c.py`, `transliterate_rust.py`, `transliterate_hdl_*.py`, `transliterate_cocotb.py`, `transliterate_svd.py`). The rename — and the implementation landing itself — were not recorded in §16 at landing time; this entry reconciles both.

SOS09G1 as-built surface (commit `1759cb1`):

- `tools/sos-codegen/transliterate_mpu.py` — module API:
  - `MpuRegion` dataclass — language-agnostic region descriptor (`name`, `base_address`, `size_log2`, `attr`, `access`, `xn`, `enable`, `channel_id`, `srd`).
  - `derive_mpu_regions(annotations, *, base_address=0x40000000)` — walks `annotations.channels` in document order; computes per-channel `attr` (`device-nGnRnE` for register channels; `normal-wb-wa` for shared-datamodel scopes; `sos:mpu_attr` override per PCDN-SOS-09-G-003), `access` (zone → AP encoding per §5.2), and aligned addresses; runs the INV-S-MEM-G-2 / G-4 overlap check at the end.
  - `emit_mpu_c(regions, *, table_name)` — C source emission with `SOS_MPU_ATTR_*` / `SOS_MPU_AP_*` macro references; satisfies §5.3 C-array shape.
  - `emit_mpu_rust(regions, *, const_name)` — Rust module fragment with `MpuAttr` / `MpuAccess` enum references against a sibling `sos_mpu` crate; satisfies §5.3 Rust constant shape.
  - `emit_mpu_background_setting(annotations)` — translates `annotations.mpu_background` (`kernel_default` / `strict`) into paired C `#define` + Rust `pub const` for `PRIVDEFENA` per §5.5 `sos_mpu_install()` step 4.
- `tools/sos-codegen/tests/test_transliterate_mpu.py` — test module covering the derivation rules, the C/Rust emission shapes, the override semantics, and the overlap check.

§13 amendment (this entry):

- The original ratification line "Implementation work on `tools/sos-codegen/mpu_emit.py` is unblocked" is superseded. The as-built path is `tools/sos-codegen/transliterate_mpu.py` (landed `1759cb1`); the test module is `tools/sos-codegen/tests/test_transliterate_mpu.py`. The §13 Files-cited table did not previously enumerate `mpu_emit.py` (the only `tools/sos-codegen/` cite in §13 is the per-doc-assertion test module), so no row in §13 requires editing — the rename lives in the §16 narrative.

No §5 frozen decision changes. No invariant amendment. The §5.2 region descriptor shape, the §5.4 SRD policy, and the §5.5 install-hook step ordering remain normative; the implementation satisfies them.

Acceptance gate progression: §9 (a) "Codegen output compiles" — the C and Rust emissions are landed and exercised by `test_transliterate_mpu.py`; full `clang -Wall -Wextra -Wpedantic -std=c11` + `cargo check --target thumbv7em-none-eabihf` integration is deferred to the runtime-side composition phase. §9 (b) (c) (d) remain ⏸ pending the cocotb framework (SOS-09-F) and bench access.

Cross-cite: `docs/concepts/ERRATA.md` ERRATA-002 cross-cites this entry.

### 2026-05-27 — PCDN-SOS-09-G-005 ratification: apply_mpu_config() call-timing ownership

Ratified by Ira at the 2026-05-27 multi-PCDN session. **Option (a) chosen**: SOS-04 owns *when* `apply_mpu_config()` is invoked during the boot sequence; SOS-09-G owns *what* the MPU configuration table contains, the data shape of the table, and the body of the `apply_mpu_config()` function that applies the table to the MPU registers. This ratifies the read of the spec that was previously surfaced as an "Open boundary item" in [SOS-04 §15] amendment "2026-05-27 — SOS04-09 runtime-boundary amendment" (co-landed with the 2026-05-27 SOS09W1 umbrella roll-up commit `43c45bf`).

**Ownership split (normative).**

- **SOS-09-G OWNS** — the MPU configuration table (which regions, which permissions, which memory attributes per region) as ratified across PCDN-SOS-09-G-001 through -004; the body of `apply_mpu_config()` (the register-write sequence currently codified as `sos_mpu_install()` in §5.5 step ordering); the data shape of the emitted table; the `sos:mpu_background` chart-root key wiring for `PRIVDEFENA`.
- **SOS-04 OWNS** — the call site (*when* during boot `apply_mpu_config()` is invoked). The natural placement is post-clock-tree, pre-task-start; the precise sequencing is a SOS-04 runtime concern that the SOS-04 port spec resolves in the same amendment that wires MPU enforcement in.

**Cross-reference (co-authored in this commit).** [SOS-04 §15] amendment "2026-05-27 — Cross-reference: PCDN-SOS-09-G-005 ratified (apply_mpu_config timing owned by SOS-04)" records the SOS-04 side of this ownership split. The two entries cite each other bidirectionally — neither phase's surface shifts; both phases now read consistently on the boundary.

**AS-BUILT v1 acknowledgement.** Per the [SOS-04 §15] "2026-05-27 — SOS04-09 runtime-boundary amendment" (commit `38699f4` co-landed with `43c45bf`), the v1 firmware in `sos-m7-rust` does NOT yet call `apply_mpu_config()` — MPU enforcement is deferred to the future SOS-04-B production-hardening amendment per INV-S-PORT-8. This PCDN ratifies the *contract* for the boundary when MPU enforcement does wire in; the AS-BUILT v1 unprotected-runtime state is documented on the SOS-04 side and is unchanged by this ratification. No code change is required at v1; this is a spec-clarification ratification only.

**Frozen-enumeration registration policy: Standards Action** for the ownership boundary itself. Moving the timing surface into SOS-09-G — e.g. amending §5.5 to specify "`apply_mpu_config()` MUST be called as a boot-stage marker post-clock-tree and pre-task-start" — would require a §16 amendment to this doc AND a co-landing §15 amendment to SOS-04 narrowing or removing SOS-04's timing surface. The current split keeps each phase's authority narrow: SOS-09-G's normative surface stays scoped to emission shape + install-hook body; SOS-04's normative surface stays scoped to runtime sequencing.

**INV-SOS-E `compose` relationship confirmed.** Per [SOS-07 §7] AuthorityRelationship matrix, the SOS-09 → SOS-04 boundary is `compose`: SOS-04 composes SOS-09-emitted artifacts as inputs. This ratification confirms the relationship stays `compose` — neither phase claims ownership of the other's surface. SOS-09-G emits the table + the `apply_mpu_config()` body; SOS-04's runtime invokes the function at a runtime-determined boot stage. No upstream-vs-downstream ownership shift occurs; the table is upstream to the call site, and the call site is downstream of the table, in the natural emit-then-consume direction enumerated in the [SOS-04 §15] four-artifact boundary set.

**Cross-reference: ERRATA-002 (filename rename context).** ERRATA-002 (commit `d24528f`) reconciled the SOS-09-G implementation filename rename from the original `mpu_emit.py` forecast to the as-built `tools/sos-codegen/transliterate_mpu.py`. The naming context for `apply_mpu_config()` as the entry-point identifier — as used in the [SOS-04 §15] four-artifact boundary set table — supersedes the §5.5 prose identifier `sos_mpu_install()` for the cross-boundary contract surface; the two names refer to the same function. Reconciling §5.5's identifier prose to match the boundary-set identifier is a future minor amendment (no behaviour change) and is NOT in scope for this PCDN ratification.

No §5 frozen decision changes. No INV-S-MEM-G-N invariant amendment. The §5.5 install-hook step ordering remains normative and unchanged; this entry ratifies the boundary between SOS-09-G's normative surface (table shape + function body) and SOS-04's normative surface (call timing).

Status: 🟢 **PCDN-SOS-09-G-005 ratified**. The boundary contract for `apply_mpu_config()` is stable across SOS-04 and SOS-09-G.

### 2026-05-27 — ERRATA-007 resolution: canonical MPU install function name

Resolves ERRATA-007 (`docs/concepts/ERRATA.md` ERRATA-007 — "SOS-09-G MPU install-function name drift (`sos_mpu_install` vs `apply_mpu_config`)"). The two identifiers refer to the same function. The PCDN-SOS-09-G-005 ratification entry immediately above noted the drift and explicitly deferred §5.5 prose reconciliation as a future minor amendment; this entry IS that amendment.

**Canonical name picked: `apply_mpu_config()`.** Rationale (citation-chain settles it):

- [SOS-04 §15] four-artifact boundary set table (the SOS-09-G row at `docs/concepts/SOS-04-CONCEPTS.md:1282`) uses `apply_mpu_config()` (commit `38699f4`, Wave-2P SOS04-09 runtime-boundary amendment).
- PCDN-SOS-09-G-005's ratification question itself used `apply_mpu_config()` (commit `d9263a1`).
- [SOS-04 §15] 2026-05-27 cross-reference entry "PCDN-SOS-09-G-005 ratified (apply_mpu_config timing owned by SOS-04)" carries `apply_mpu_config()` forward (commit `1180910`).
- The PCDN-SOS-09-G-005 ratification entry above on this doc (commit `1180910`) uses `apply_mpu_config()` in every normative clause; the only `sos_mpu_install()` reference is the explicit naming-drift acknowledgement.

The non-canonical `sos_mpu_install()` identifier appeared only in §5.5 prose + the §3 glossary entry + the §5.3 C / Rust function declarations + the INV-S-MEM-G-3 invariant statement + the §9 (c) acceptance gate + the §13 files-cited recap of glossary terms. Three commits (one Wave-2P, two Wave-5C) already pin `apply_mpu_config()` as the cross-boundary identifier; the path of least drift is updating SOS-09-G's normative surface to match.

**Normative changes landing in this commit.**

- §3 glossary (`docs/concepts/SOS-09-G-CONCEPTS.md:51-52`) — rename the glossary entry; the entry text adds a parenthetical pointing at this errata + flagging that historical §16 entries dated before 2026-05-27 retain the earlier identifier.
- §4 source-of-truth map (`SOS-09-G-CONCEPTS.md:69`) — rename the row label.
- §5.3 emission outputs (`SOS-09-G-CONCEPTS.md:138, 154`) — rename the C `void` declaration and the Rust `pub fn` declaration.
- §5.5 section heading + prose (`SOS-09-G-CONCEPTS.md:174, 178, 187`) — rename the section title, the function-introducing sentence, and the idempotency sentence. The 6-step disable→write→disable-unused→PRIVDEFENA→enable→DSB-ISB sequence is unchanged; only the function identifier changes.
- §7 invariant INV-S-MEM-G-3 (`SOS-09-G-CONCEPTS.md:216`) — rename the function identifier in the invariant statement. The invariant content (idempotency demonstrated by twice-invoke equivalence) is unchanged.
- §9 acceptance gate (c) (`SOS-09-G-CONCEPTS.md:245`) — rename the function identifier in the test-scaffolding cite.
- §13 files-cited recap (`SOS-09-G-CONCEPTS.md:333, 335, 336`) — these lines are INSIDE the 2026-05-25 §16 "Initial draft (Ira)" historical entry and are NOT modified; they remain as institutional memory of the original glossary / frozen-decision / invariant naming at draft time. The recap is informative; the normative §3 / §5 / §7 surfaces above are what the codegen + runtime contracts read against.

**Historical §16 entries are NOT modified per parent CLAUDE.md "stealth-revert prohibition" + ERRATA.md "entries are permanent" doctrine.** The 2026-05-25 "Initial draft (Ira)", 2026-05-25 "Ratified (Ira)", 2026-05-27 "SOS09G1 implementation entry + cite reconciliation (ERRATA-002)", and 2026-05-27 "PCDN-SOS-09-G-005 ratification" entries all retain `sos_mpu_install()` exactly as they were written. They are institutional memory of how the drift accumulated and how it was identified; rewriting them would erase the very evidence ERRATA-007 records.

**Cross-reference (co-authored in this commit).** [SOS-04 §15] amendment "2026-05-27 — Cross-reference: ERRATA-007 settles MPU install function name" records the SOS-04 side; the entry confirms `apply_mpu_config()` as the canonical name across both phase docs and cites ERRATA-007 + this §16 entry.

**No behaviour change.** No code module is touched in this commit (the actual emitted Rust + C function names in `tools/sos-codegen/transliterate_mpu.py` MAY differ from the canonical spec name — that's a separate code-doc drift outside the scope of this errata, to be reconciled when the implementation-side rename lands). No frozen decision changes. No invariant content changes. The §5.5 install sequence (6 steps) is unchanged. The PCDN-SOS-09-G-005 ownership split (SOS-04 owns timing; SOS-09-G owns table + function body) is unchanged.

**Frozen-enumeration registration policy: Specification Required** — the function identifier is a phase-local mechanic; future renames are a phase-owner walkthrough update, not a Standards Action amendment (the cross-boundary contract is the function's existence + signature shape, both of which are unchanged).

**INV-SOS-A / INV-SOS-E unchanged.** The chart-as-source claim and the `compose` relationship between SOS-09-G and SOS-04 are unaffected by the spec-text rename; no upstream-vs-downstream ownership shift occurs.

Status: 🟢 **ERRATA-007 resolved**. The §5.5 normative surface and the SOS-04 §15 boundary-set table now agree on `apply_mpu_config()` as the canonical identifier.
