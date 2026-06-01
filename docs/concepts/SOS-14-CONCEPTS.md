# SOS-14 — AMP Shared-Memory + HSEM Doorbell Medium

**Status:** 🟢 **Ratified 2026-06-01** (owner: Ira). All four PCDNs resolved (§15);
INV-S-AMP-1..5 (§8) and the §5 enums + `<sos:doorbell>` annotation are binding. Prerequisite
**SOS-00 Amendment 006** (the §11 AMP-medium admission) landed first in its own commit, per
PCDN-SOS-14-004. **Proposed by the sibling disco-analyzer DAA-08 initiative** (cross-pollination
per SOS-00 §10 explicit-citation rule); the motivating consumer's requirements (REQ-SOS-6/8) are
cited in §2, and the abstraction generalizes beyond that one product — SOS owns it. Implementation
(the AMP-medium emitter + port doorbell binding, §14) lands as follow-up commits.

## 0. Authority policy

This doc is the single normative source for the **AMP medium**: the above-kernel abstraction that
binds **one SOS kernel instance running on one core** to a **bare-metal sibling core** over shared
memory, with a hardware-semaphore (HSEM) **doorbell** as the inter-core interrupt source. It does
not redocument the kernel (SOS-00 owns that) nor the orchestrator medium taxonomy (SOS-10 owns
that); it **extends** the SOS-10 `shared-memory` medium to the baremetal cross-core case and
**composes** SOS-09 membrane/MPU primitives.

The authority split:

| Concern | Owner | SOS-14 relationship |
|---|---|---|
| Kernel scheduling, `*_from_isr` admissibility (INV-S3), M7 NVIC band (INV-S9) | SOS-00 | Consumed unchanged; the doorbell is a standard kernel-aware ISR source |
| Medium taxonomy (`in-process`/`shared-memory`/`mmio`/`network`), `<sos:medium>` annotation, wire-format-derived rule | SOS-10 §6.2 | **Extended**: SOS-14 specifies the baremetal cross-core realisation of `shared-memory` + a `doorbell` sub-annotation |
| Core-affinity / region placement / MPU emission | SOS-09-A / SOS-09-G | **Composed**: the shared region + its non-cacheable + per-core access attributes are SOS-09 emissions |
| The HSEM peripheral contract (atomic 1-of-N lock/unlock, per-core IRQ) | ARM/ST hardware (curated subset, §6) | `derive` — SOS curates the primitive subset it depends on; it does not crawl the RM |
| The AMP medium abstraction itself | This doc | `own` |

**Crawl boundary (INV-S1).** SOS-14 does **not** crawl the sibling disco-analyzer tree nor the
STM32H747 RM0399 / Cortex-M7 ARM. The HSEM primitive subset SOS depends on is curated in §6; the
motivating product's requirements are cited abstractly in §2 from DAA-08's published requirements
registry, not by reading DAA source.

## 1. Purpose

1. Define the **AMP pair** topology: one SOS kernel (the *managed core*) + one bare-metal sibling
   (the *foreign core*), coupled by a shared-memory medium and an HSEM doorbell — **without** making
   SOS an SMP kernel (INV-S14 preserved; §7).
2. Specify the **doorbell** as the baremetal binding of an inter-core event onto the SOS
   `*_from_isr` family, and the **shared region** as the baremetal realisation of SOS-10's
   `shared-memory` medium.
3. Amend SOS-00 §11 to distinguish the still-non-goal "SMP kernel / inter-kernel scheduling" from
   the newly-in-scope "AMP medium binding one SOS kernel to a bare-metal sibling core" (§7).

## 2. Problem statement

**Motivating consumer (cited, not crawled).** The sibling disco-analyzer initiative DAA-08
re-hosts a dual-core audio analyzer's managed core on SOS while the foreign core stays bare-metal.
Its requirements registry places two needs on SOS (DAA-08 §7):

- **REQ-SOS-6** — express the cross-core contract (a shared-memory mailbox/pool + a hardware-
  semaphore doorbell) as an SOS-provided typed medium, so the product need not hand-roll it.
- **REQ-SOS-8** — reconcile the dual-core path with INV-S14 / §11 without forcing SOS into SMP.

**Gap in current SOS.** SOS-10 §6.2 specifies the `shared-memory` medium for *Linux* (`mmap` +
futex) and *RTOS* (native message queue), but not for the **baremetal cross-core AMP** case: two
physical cores, asymmetric (one SOS, one bare-metal), no shared OS, coordinating through a window
of shared physical memory and a hardware-semaphore interrupt. SOS-00 §11 lists "dual-core /
inter-core IPC" as a non-goal, and "inter-port communication" as out of scope — phrased for the
SMP / two-independent-kernel case, not the AMP-medium case. The abstraction is missing, not
forbidden in principle.

**Why it generalizes.** AMP-with-a-bare-metal-sibling is a common deeply-embedded shape
(application core + real-time/IO core: STM32H7 CM7+CM4, i.MX A+M, RP2040 dual-core, etc.). A
declared SOS medium for it makes the SOS methodology cover the class, not one board.

## 3. Glossary

| Term | Definition | Owner relationship |
|---|---|---|
| **AMP pair** | A managed core (runs one SOS kernel) plus a foreign core (bare-metal), sharing a memory window and an HSEM doorbell. Exactly one SOS kernel in the pair. | own (SOS-14) |
| **Managed core** | The core hosting the SOS `rtos_kernel.scxml` instance. | own |
| **Foreign core** | The sibling core. Bare-metal; not an SOS kernel; SOS makes no scheduling claim over it. | own |
| **Doorbell** | A hardware-semaphore channel used as a one-bit inter-core interrupt. The foreign core releases it; the managed core's HSEM ISR fires and converts the signal to a kernel `*_from_isr` action. Payload travels in the shared region, never in the doorbell. | own (binds SOS-00 `*_from_isr` + HW HSEM) |
| **Shared region** | A named, statically-sized, non-cacheable memory window mapped into both cores' address spaces. Carries the medium's ring(s)/mailbox(es). Placed + protected via SOS-09. | compose (SOS-09) |
| **AMP medium** | The `shared-memory` medium (SOS-10) specialized to the AMP pair: shared region + doorbell + the producer/consumer protocol. | extend (SOS-10) |

## 4. Source-of-truth map / AuthorityRelationship rows

Rows added to the SOS-07 §7 matrix (Concept | Upstream authority | Relationship | Declaring phase | Mutation rights):

| Concept | Upstream authority | Relationship | Declaring phase | Mutation rights |
|---|---|---|---|---|
| `shared-memory` medium (baremetal AMP realisation) | SOS-10 §6.2 | **extend** — adds the baremetal cross-core realisation + `doorbell` sub-annotation atop SOS-10's medium | SOS-14 §6 | extends SOS-10; SOS-10 stays canonical for the enum |
| HSEM (hardware semaphore: atomic lock/unlock, per-core IRQ, optional key/process-id) | ARMv8/ARMv7-M SoC integration; ST HSEM IP (curated §6) | **derive** — curated primitive subset; no upstream mutation | SOS-14 §6 | none — citation only |
| Inter-core memory ordering (release/acquire across cores, non-cacheable window) | ARM memory model (curated §6) | **derive** | SOS-14 §6 | none |
| Shared-region placement + per-core access + non-cacheable attribute | SOS-09-A / SOS-09-G | **compose** | SOS-14 §6.4 | none — SOS-09 owns emission |

## 5. Frozen enums (proposed; registration policies)

### 5.1 `DoorbellDirection` — Standards Action

`FOREIGN_TO_MANAGED` (foreign core rings; managed core's ISR → `*_from_isr`) and
`MANAGED_TO_FOREIGN` (managed core rings; foreign core wakes from its own idle, e.g. WFE). Adding a
value requires a §15 amendment + `.scxml`/annotation update + medium-emitter update. **Reserved
(not legal yet):** `BIDIRECTIONAL_PAIRED` (a matched ring pair) — deferred until a consumer needs it.

### 5.2 `<sos:doorbell>` annotation surface — Specification Required

A sub-annotation of `<sos:medium kind="shared-memory" amp="true">` declaring: the doorbell channel
id, its `DoorbellDirection`, the kernel action it lowers to on the managed core
(`sem.give_from_isr{sid}` | `queue.send_from_isr{qid}`), and the shared-region symbol it pairs with.
Adding a lowering target requires a phase-owner walkthrough update; no §15 amendment.

### 5.3 `AmpMediumKind` extension note

SOS-14 does **not** add a value to SOS-10's 4-value medium enum (`in-process`/`shared-memory`/
`mmio`/`network`). The AMP case is `shared-memory` with `amp="true"` + a `doorbell`. This keeps
SOS-10's enum frozen and SOS-14 as an *extension*, not a *fork* (INV-S10).

## 6. The AMP medium design

### 6.1 Topology

```
   ┌──────────── managed core ────────────┐        ┌──── foreign core ────┐
   │  one SOS kernel (rtos_kernel.scxml)   │        │  bare-metal          │
   │  HSEM ISR (NVIC ≥0xA0, INV-S9)        │◄──┐    │  releases doorbell   │
   │    └─ sem.give_from_isr / queue.send_ │   │    │  writes shared ring  │
   │       from_isr  (INV-S3 admissible)   │   │    │                      │
   └───────────────────┬───────────────────┘   │    └──────────┬───────────┘
                        │  shared region (non-cacheable window) │
                        └───────────────────────────────────────┘
                          HSEM doorbell = inter-core IRQ source
```

### 6.2 The doorbell

A doorbell is a hardware-semaphore channel treated as a single-bit interrupt:

- The **foreign core** writes its payload into the shared region (release ordering), then performs
  the HSEM **release** that raises the managed core's HSEM IRQ.
- The **managed core's HSEM ISR** runs at a kernel-aware NVIC priority (≥ `0xA0`, INV-S9), clears
  the channel, and performs exactly one admissible `*_from_isr` action (INV-S3): `sem.give_from_isr`
  (the common case — wake one task) or `queue.send_from_isr` (hand a pointer/index to a task).
- The HSEM carries **no payload**; it is purely the wakeup edge. All data is in the shared region.

This is the load-bearing reconciliation: from the kernel's view nothing new exists — the doorbell
is "any kernel-aware NVIC IRQ" per SOS-00 §6.1, already admissible. SOS-14 only standardizes the
*binding* (which HW edge → which kernel `*_from_isr`) and its annotation.

### 6.3 The shared region & ordering

- A statically-sized, named window (`MAX_AMP_REGION_BYTES`, build constant), mapped at the same
  physical address into both cores. Realised as one or more SOS-10 `shared-memory` rings/mailboxes.
- **Non-cacheable** on both cores (so no cross-core cache-maintenance is required); SOS-09 emits the
  attribute. Producers publish with release ordering, consumers read with acquire ordering; the
  doorbell edge provides the wake, the ordering provides the visibility.
- The wire format is **derived, not authored** (SOS-10 INV-S-ORCH-4): the ring layout follows from
  the `(event-type, medium)` pair + the chart payload, exactly as for the other SOS-10 media.

### 6.4 Placement, protection, MPU (composed from SOS-09)

The shared region's placement (named linker section / physical address), its non-cacheable
attribute, and its per-core access rights (e.g. the managed core's consumer context gets read-only
where appropriate — the observation-membrane pattern) are declared as SOS-09 core-affinity /
protection-zone annotations and lowered by SOS-09-G MPU emission. SOS-14 composes that surface; it
does not re-specify MPU emission.

### 6.5 Per-medium failure taxonomy (extends SOS-10 INV-S-ORCH-5)

The AMP medium's failure modes: **lost doorbell** (foreign rings while the channel is already
pending — the medium MUST be edge-coalescing-safe: the consumer drains all fresh ring entries on
each wake, so one ISR can service multiple publishes), **fall-behind** (producer overruns the ring —
the medium declares a drop policy, e.g. drop-newest, surfaced in telemetry), and **mis-ordering
across the window** (prevented by the release/acquire + non-cacheable discipline of §6.3).

## 7. Reconciliation with SOS-00 §10/§11 (the INV-S14 amendment)

**INV-S14 is preserved unchanged**: the managed core hosts exactly one statechart. The foreign core
is **not** an SOS kernel — SOS makes no scheduling claim over it — so there is no second instance,
no SMP, no inter-kernel scheduling.

**Proposed SOS-00 §11 amendment** (replaces the single "SMP / core affinity" non-goal line):

> - **SMP / inter-kernel scheduling.** One statechart per port (INV-S14); SOS does not schedule
>   across cores, and two SOS kernels do not coordinate at the kernel level. This stays a non-goal.
> - **AMP medium (newly in scope, SOS-14).** Binding *one* SOS kernel (managed core) to a
>   *bare-metal* sibling (foreign core) via the SOS-10 `shared-memory` medium + an HSEM doorbell is
>   in scope as an **above-kernel medium**. The foreign core is not an SOS kernel; the doorbell is a
>   standard kernel-aware `*_from_isr` source (SOS-00 §6.1, INV-S3). INV-S14 is not relaxed.

The corresponding SOS-00 §10 cross-pollination note records that DAA-08 (sibling) is the motivating
consumer, cited per the explicit-citation rule, with no FreeRTOS/DAA source crawled.

## 8. Invariants (proposed)

- **INV-S-AMP-1 — One SOS kernel per AMP pair.** The managed core runs exactly one
  `rtos_kernel.scxml`; the foreign core runs no SOS kernel. (Refines, does not relax, INV-S14.)
- **INV-S-AMP-2 — Doorbell carries no payload.** An HSEM doorbell conveys only the wakeup edge; all
  data crosses in the shared region. The managed-core ISR performs exactly one admissible
  `*_from_isr` action per drained edge (INV-S3).
- **INV-S-AMP-3 — Shared region non-cacheable + ordered.** The shared region is non-cacheable on
  both cores; visibility is established by release/acquire, not cache maintenance.
- **INV-S-AMP-4 — Edge-coalescing-safe consumer.** A single doorbell ISR MUST correctly service
  every fresh ring entry (≥1), so a coalesced edge loses no published item.
- **INV-S-AMP-5 — Medium not kernel.** The AMP medium lives above the kernel; the `.scxml` names no
  HSEM, no core, no physical address (INV-S15 preserved). The binding lives in the medium emitter +
  the port.

## 11. Non-goals

- **CM4/foreign-core-on-SOS.** A second SOS kernel on the foreign core is out of scope (that is the
  SMP/inter-kernel case, still a non-goal). If a consumer later wants it, that is a separate phase.
- **Cache-coherent shared regions.** SOS-14 v1 requires a non-cacheable window; cache-maintenance-
  based sharing is deferred.
- **More than two cores / >1 foreign core per managed kernel.** v1 is a pair.
- **Generic IPC bus.** SOS-14 is the shared-memory+doorbell shape, not a general message bus
  (that's SOS-10 `network`).

## 12. Acceptance (ratification gates — to be completed before §15 ratified entry)

- (a) §5 enums + the `<sos:doorbell>` annotation surface frozen with registration policies.
- (b) §6 specifies the doorbell→`*_from_isr` binding, the shared-region ordering discipline, and
  the SOS-09 composition for placement/protection — with the wire-format-derived rule inherited.
- (c) §7 lands the SOS-00 §11 amendment text (SMP-non-goal vs AMP-medium-in-scope) and the §10
  cross-pollination citation; INV-S14 confirmed preserved.
- (d) §8 invariants INV-S-AMP-1..5 ratified.
- (e) all PCDN-SOS-14-NNN resolved (§ change log).
- (f) a conformance-vector plan: the AMP medium's producer/consumer protocol expressed as
  SOS-03-schema vectors runnable on `sim/sos-sim` (the doorbell modelled as a `*_from_isr` event
  source), per INV-S-AMP-4.

## 13. Files cited

SOS: `SOS-00-CONCEPTS.md §6.1/§9 (INV-S3/S9/S14/S15)/§10/§11`, `SOS-10-CONCEPTS.md §6.2/§6.4
(INV-S-ORCH-3/4/5)`, `SOS-09-A-CONCEPTS.md` (core-affinity / protection annotation),
`SOS-09-G-CONCEPTS.md` (MPU emission), `SOS-04-CONCEPTS.md` (FAM-04-A configurable stacks),
`SOS-07-CONCEPTS.md §7` (AuthorityRelationship matrix), `rtos_kernel.scxml` (`*_from_isr` family).
Cross-initiative (cited, not crawled): disco-analyzer `DAA-08-CONCEPTS.md §7` (REQ-SOS-6/8), §10.

## 14. Unblocks

- The AMP-medium emitter in `tools/sos-codegen/` (extends `shared_memory_emit.py` with the
  baremetal+doorbell realisation).
- The SOS-04 / SOS-05 port binding for an HSEM doorbell ISR → `sem.give_from_isr`.
- DAA-08's REQ-SOS-6/8 verification (DAA-08 gate G-B2): the analyzer's cross-core path runs through
  this medium instead of a hand-rolled contract.

## 15. Change log

- **2026-06-01 (ratification)** — SOS-14 **ratified** by owner (Ira). All four PCDNs resolved:
  - **PCDN-SOS-14-001 (doorbell→kernel-action lowering set):** resolved = **both** `sem.give_from_isr`
    *and* `queue.send_from_isr` are valid lowering targets (§5.2). A doorbell declares which one it
    lowers to. Rationale: the motivating consumer's parity path uses the semaphore wake; the
    pointer/index-handoff path uses the queue; the general medium supports both.
  - **PCDN-SOS-14-002 (shared-region first-class shapes):** resolved = **both** a single ring *and*
    a mailbox + refcounted-pool are first-class shared-region shapes (§6.3). Rationale: a real AMP
    consumer needs the latest-value mailbox *and* a multi-slot refcounted pool (the disco analyzer's
    audio mailbox + LineIn block pool are the worked example); restricting to one ring would force
    hand-rolling the other.
  - **PCDN-SOS-14-003 (fall-behind drop policy):** resolved = **drop-newest is the default**,
    per-channel-overridable (drop-oldest | block also selectable). Rationale: drop-newest matches the
    established consumer fall-behind behaviour (DAA-03-INV-D17) and is the safe default for a
    latest-value mailbox; the choice is declared on the channel, surfaced in telemetry (§6.5).
  - **PCDN-SOS-14-004 (§11 amendment placement):** resolved = the SOS-00 §11 amendment lands
    **first, in its own commit** (SOS-00 §15 Amendment 006, 2026-06-01), which SOS-14 then cites.
    Done — Amendment 006 preceded this ratification.

  INV-S-AMP-1..5, the §5 enums (`DoorbellDirection` Standards Action; `<sos:doorbell>` Specification
  Required), the §6 design, and the §7 reconciliation (INV-S14 preserved) are binding. Implementation
  (§14 emitter + port binding) is now unblocked.
- **2026-06-01 (drafting)** — SOS-14 drafted on branch `daa08-amp-proposals`, **proposed by the
  sibling DAA-08 initiative** (REQ-SOS-6/8). Defines the AMP pair (managed SOS core + bare-metal
  foreign core), the HSEM **doorbell** as a baremetal binding onto the SOS `*_from_isr` family
  (already admissible per SOS-00 §6.1/INV-S3 — the kernel gains nothing new), and the **shared
  region** as the baremetal realisation of SOS-10's `shared-memory` medium (extension, not a new
  medium-enum value — INV-S10 honoured). §7 proposes the SOS-00 §11 amendment distinguishing
  "SMP / inter-kernel scheduling" (stays non-goal) from "AMP medium" (newly in scope), with
  **INV-S14 preserved unchanged**. §8 proposes INV-S-AMP-1..5.
