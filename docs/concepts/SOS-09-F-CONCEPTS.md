# SOS-09-F — Membrane vectors

**Status:** 🟢 **RATIFIED 2026-05-26**.

## 0. Authority policy

This phase doc is the **membrane vectors** sub-phase under the SOS-09 umbrella (`SOS-09-CONCEPTS.md`, ratified 2026-05-23 with PCDN-SOS-09-001 amended 2026-05-25). The umbrella names seven sub-phases in §6; SOS-09-F is the integration-contract vector suite that exercises each chart-declared register across the hardware/software membrane. The umbrella's §5 freezes the channel-category enum (`{status, command, queue, shared}`), the channel → membrane-primitive mapping, the atomicity-class enum, and the protection-zone enum; this doc takes those decisions as load-bearing input and produces the per-emission contract for the membrane-vector suite.

Per the parent CLAUDE.md "Spec-Before-Code Planning Discipline / Phase document shape":

- **Normative** sections of this doc: §3 glossary, §4 source-of-truth map, §5 frozen decisions (vector family enumeration; vector adapter shape; traceability key format; co-simulation harness; vector report format; failure-rendering vocabulary; atomicity vector), §6 invariants (INV-S-MEM-F-1 through INV-S-MEM-F-6), §7 enumeration policies, §8 standards integration matrix additions, §12 acceptance checklist.
- **Informative** sections: §1 purpose, §2 problem statement, §10 reconciliation, §11 non-goals, §13 files cited, §14 unblocks, §15 PCDNs (filed open), §16 ratification log.
- All keywords MUST, MUST NOT, SHALL, SHOULD, SHOULD NOT, MAY are interpreted per RFC 2119 / RFC 8174 when capitalised.

This doc cites `SOS-07-CONCEPTS.md` §6 for the cross-phase invariants INV-SOS-A through H and §7 for the AuthorityRelationship matrix; it does not re-derive them. INV-SOS-B (vectors-as-deliverable) and INV-SOS-H (vector-to-chart traceability) are the load-bearing cross-phase invariants for this sub-phase. It cites `SOS-03-CONCEPTS.md` for the base vector framework (SOS-09-F EXTENDS without re-deriving) and `SOS-08-D-CONCEPTS.md` for the cocotb framework for HDL targets (SOS-09-F EXTENDS via the membrane-vector adapter layer). It cites `SOS-09-A-CONCEPTS.md` for the chart annotation surface and the `sos:id` / `sos:name` identity/name split (per PCDN-SOS-09-A-003 ratification 2026-05-25), `SOS-09-B-CONCEPTS.md` for the CMSIS-SVD round-trip surface, and `SOS-09-G-CONCEPTS.md` for the MPU configuration that protection vectors install before running.

Per PCDN-SOS-09-005 (ratified at the umbrella 2026-05-23), the v1 co-simulation harness is **cocotb with a Python CPU stub**; cycle-accurate ISS integration is deferred indefinitely.

## 1. Purpose

To freeze the membrane-vector emission contract: which vector families a chart channel produces by `sos:kind`, the per-vector adapter shape, the traceability key that ties every emitted vector back to its originating chart channel by UUID, the co-simulation harness the vectors run against, the JUnit XML report shape consumers (CI, downstream consumers of the SOS-09 IP block) parse, the failure-message vocabulary that renders chart-side rather than register-address-side, and the concurrent-stimulus model for atomicity vectors. The output is the chart-driven integration-contract test suite that ships with every SOS-09-emitted IP block — running the vectors against a consumer's instantiation IS the integration test per INV-SOS-B.

Without this freeze, the membrane-vector emission path cannot produce a stable artifact: every emission would re-litigate which vector families apply per channel kind, which adapter primitives the vectors call, which harness drives the cocotb test, and how failures render. Downstream consumers of the SOS-09 register-file RTL would receive vectors whose failure messages name raw bus addresses instead of chart states — exactly the failure mode INV-SOS-H prohibits.

## 2. Problem statement

Per SOS-09 §2, the canonical hardware/software co-design failure mode is the "register-map PDF that lies": a register map maintained as documentation drifts from firmware and silicon, and every downstream artifact inherits the drift. The membrane-vector suite is the integration-contract enforcement that catches the drift in CI before it reaches the bench. Five concrete failure patterns motivate this sub-phase's freeze:

1. **Untested clear-on-read.** A `status` channel declares `sos:clear_on_read="true"` in the chart; the SVD emits `<readAction>clear</readAction>`; the HDL register-file decode latches but does not clear; the C HAL macro is named `*_consume_*` but the underlying read is non-destructive. Without a clear-on-read vector that performs (read → assert bits cleared → second read → assert returns cleared value), the drift between chart and silicon is silent until a driver writer accidentally double-reads in production.

2. **Untested side-effect-on-write.** A `command` channel declares `sos:side_effect="oneToClear"`; the SVD round-trip carries `<modifiedWriteValues>oneToClear</modifiedWriteValues>`; the HDL register-file gates the write on the bit pattern but the chart-declared HW-side action (an IRQ clear, a queue depth decrement, a strobe pulse) never fires. Without a side-effect vector that stimulates the write AND observes the chart-declared HW-side action via the corresponding status channel / IRQ count / queue depth change, the chart-vs-silicon drift is silent.

3. **Untested zone violation.** A `shared` channel declares `sos:zone="privileged"`; SOS-09-G emits the MPU table; SOS-09-E emits the per-channel register-decode gate. A protection vector that writes from an unprivileged context MUST observe BOTH the rejection AND the access-violation event surfaced by SOS-09-E's per-channel-group strobe-latch (per INV-S-MEM-E-5). A "silently rejected" outcome — where the write is rejected but no event surfaces — is the worst failure mode SOS-09 is supposed to prevent (silent acceptance of an attempt that should have been logged).

4. **Untested atomicity.** A `kind="shared"` channel is declared `atomicity="mutex-required"`; the chart-bounds analysis discharges the obligation; runtime atomicity checks MAY be elided per INV-SOS-G. Without an atomicity vector that launches concurrent HW-side and SW-side producers under cocotb's coroutine model, asserts no torn read, AND asserts `sos_mutex` serialises access (observable via the mutex claim count vs successful-access count), the chart-bounds discharge is unverified — the elision is on paper only.

5. **Vectors that drift away from chart annotations.** A vector authored by hand against the SVD names register addresses, bit field positions, and IRQ numbers. When the chart adds a new channel between two existing ones, the dense address-offset policy (SOS-09-B §5.3 per PCDN-SOS-09-B-003) shifts every downstream register's `<addressOffset>` — and every hand-authored vector becomes wrong by exactly one register width. The chart-driven emission with UUID-rooted traceability per PCDN-SOS-09-A-003 ratification is what keeps the vector surface stable under chart edits: a chart rename of `sos:name` does NOT invalidate vector identity; only an explicit `sos:id` regeneration does.

SOS-09-F makes the five symptoms the same symptom of one disease — vectors that are not emitted alongside the artifacts they verify — and prescribes one cure: emit every vector at the same codegen step that emits the SVD, the C HAL, the Rust HAL, the HDL register file, and the MPU table; tag each vector with the UUID of its originating chart channel; render every failure in chart vocabulary citing the UUID.

## 3. Canonical glossary

Terms normative within SOS-09-F+. Authority relationships per §8.

| Term | Definition |
|---|---|
| **membrane vector** | A SOS-03-style test vector (per `SOS-03-CONCEPTS.md` base vector framework, **adapted** per §8) that exercises a single register's read/write/side-effect/clear/atomicity/protection contract across the hardware/software membrane. Set of membrane vectors for a chart IS the integration contract per INV-SOS-B. Owned by SOS-09-F; extends SOS-03's vocabulary via the SOS-03 §15 amendment co-landing with SOS-09 umbrella ratification. |
| **vector family** | One of the six normative families: `{ initial_value, write_then_read, side_effect, clear_on_read, atomicity, protection }`. Each family corresponds to one of the six bullet shapes named in SOS-09 §6 SOS-09-F summary. The per-channel vector count is the cross-product of (chart-declared register set) × (families applicable by `kind`). Owned by this doc (§5.1). |
| **vector adapter** | The Python class subclassing `MembraneVector` that realises one membrane vector. Carries four methods — `setup(harness)`, `stimulate(harness)`, `observe(harness)`, `assert_invariants(harness)` — that the harness invokes in sequence. The adapter binds to the harness (cocotb-with-Python-CPU-stub at v1; future harnesses are PCDN-gated). Owned by this doc (§5.2). |
| **chart traceability key** | The stable identifier `MV-<chart-sos-id-UUID>-<family>-<seq>` on every emitted vector. Per PCDN-SOS-09-A-003's UUID resolution, the UUID-rooted identifier means a chart rename of `sos:name` does NOT invalidate vector identity (renames preserve traceability; only `sos:id` regenerations break the chain, and those are explicit edits). Owned by this doc (§5.3). |
| **co-simulation harness** | The Python-driven test driver that instantiates the HDL register-file RTL via cocotb AND runs the Python CPU stub against it through the vector adapter's `bus.read(addr)` / `bus.write(addr, value)` / `wait_irq(timeout)` primitives. Per PCDN-SOS-09-005 (ratified at the umbrella), v1 harness is cocotb with Python CPU stub. Future harnesses (real-hardware loopback, cycle-accurate ISS) are PCDN-gated. Owned by this doc (§5.4). |
| **Python CPU stub** | The Python-side model of CPU register accesses inside the cocotb test. Provides `bus.read(addr) → value`, `bus.write(addr, value) → None`, `wait_irq(timeout_ns) → irq_name`, and (for the atomicity family) `concurrent_writer(coro) → handle`. The stub is deterministic given a seed AND the cocotb simulation clock; it is NOT a cycle-accurate ISS. Owned by this doc (§5.4). |
| **JUnit XML report** | The per-run report shape — JUnit-XML — that the harness produces for CI consumption. Each `<testcase>` carries the chart traceability key as its `name` attribute and the chart-vocabulary failure message in the `<failure>` text. Per PCDN-SOS-09-F-005's pytest-native-output recommendation, cocotb's existing pytest collector emits the shape. Owned by this doc (§5.5). |
| **chart vocabulary** | The vocabulary of chart annotations — channel `sos:name`, channel `kind`, channel `zone`, chart state names, chart transition names — that failure messages MUST use instead of raw bus addresses or bit positions. Per INV-SOS-H. As defined in SOS-07 §6 INV-SOS-H description; used without modification. |
| **access-violation event** | The chart-declared status channel that SOS-09-E emits for cross-zone access attempts (per SOS-09 umbrella §6 SOS-09-E description; specialised by INV-S-MEM-E-5 in SOS-09-E's own concept doc when ratified). Protection vectors that succeed (i.e. the channel rejected the unauthorised access) MUST observe this event firing; a "rejected silently" outcome is a test failure. As defined in SOS-09-E §5 (sibling sub-phase, ratification in flight); **mirror** here. |

## 4. Source-of-truth map

For every concept this sub-phase touches, **exactly one** location is the canonical authority.

| Concept | Authority | Authority relationship (per SOS-07 §7) |
|---|---|---|
| Vector family enumeration (the six families) | **this doc** (§5.1) | `own` |
| Vector adapter shape (`MembraneVector` base class; four-method protocol) | **this doc** (§5.2) | `own` |
| Traceability key format (`MV-<UUID>-<family>-<seq>`) | **this doc** (§5.3) | `own` |
| Co-simulation harness (cocotb + Python CPU stub at v1) | **this doc** (§5.4); cocotb is upstream (`derive`); Python CPU stub is `own` | `compose` (cocotb + own stub) |
| Chart-to-vector emission walker | **this doc** (§5.4 / §5.5); reads SOS-09-A annotation surface and SOS-09-B SVD | `own` (walker); `mirror` (input surfaces) |
| Vector report format (JUnit XML, pytest-native) | **this doc** (§5.5); pytest emits the canonical shape (`derive`) | `derive` |
| Failure-rendering vocabulary | **this doc** (§5.6) | `own` |
| Atomicity vector (concurrent-stimulus model) | **this doc** (§5.7) | `own` |
| Base vector framework (SOS-03) | `SOS-03-CONCEPTS.md` | `adapt` — SOS-03 owns the base; SOS-09-F adds the six membrane-vector families via SOS-03 §15 amendment |
| cocotb HDL test framework | `SOS-08-D-CONCEPTS.md` (local extension surface); cocotb upstream | `derive` (upstream); `compose` (this doc's adapter wraps SOS-08-D's harness) |
| `sos:id` / `sos:name` identity / name split | `SOS-09-A-CONCEPTS.md` §5.2 (per PCDN-SOS-09-A-003 ratification 2026-05-25) | `mirror` |
| CMSIS-SVD register surface (the enumeration source) | `SOS-09-B-CONCEPTS.md` | `mirror` (vectors enumerate from SVD output) |
| MPU configuration installed before protection vectors | `SOS-09-G-CONCEPTS.md` `sos_mpu_install()` | `compose` (protection vector calls `sos_mpu_install` before running) |
| SOS-09-E access-violation event surface (`INV-S-MEM-E-5`) | `SOS-09-E-CONCEPTS.md` (sibling; ratification in flight) | `mirror` (protection vector observes the event) |
| Cross-sub-phase invariants INV-S-MEM-1 through 6 | `SOS-09-CONCEPTS.md` §7 | cited, not redefined |
| Cross-phase invariants INV-SOS-A through H (esp. INV-SOS-B, INV-SOS-H) | `SOS-07-CONCEPTS.md` §6 | cited, not redefined |
| Per-sub-phase invariants INV-S-MEM-F-1 through 6 | **this doc** (§6) | `own` |

## 5. Frozen decisions

### 5.1 Vector family enumeration

A SOS-09-F vector is one of six families:

```
vector_family ∈ {
    initial_value,
    write_then_read,
    side_effect,
    clear_on_read,
    atomicity,
    protection,
}
```

This enumeration is the cross-product axis with the chart-declared register set. The per-channel vector count is the cross-product `(chart-declared register set) × (families applicable by channel kind)`:

| Channel `kind` | Applicable families |
|---|---|
| `status` | `initial_value`, `clear_on_read` (when `sos:clear_on_read="true"`), `protection` (when `sos:zone="privileged"`), `atomicity` (when `atomicity="mutex-required"`) |
| `command` | `initial_value`, `write_then_read`, `side_effect` (when `sos:side_effect=` is set), `protection`, `atomicity` |
| `queue` | `initial_value`, `write_then_read`, `side_effect` (queue depth changes), `protection`, `atomicity` |
| `shared` | `initial_value`, `write_then_read`, `clear_on_read` (when applicable), `side_effect` (when applicable), `atomicity` (default `mutex-required`), `protection` |

Per INV-S-MEM-F-1, every chart-declared channel produces ≥1 vector of every family applicable to its `kind`. A channel that fails to emit a required vector is a codegen error, not a warning.

The six-family enumeration is frozen. Adding a seventh family requires a §16 amendment to this doc and cross-phase review.

Frozen-enumeration registration policy: **Standards Action** (the enumeration encodes the integration-contract surface; cross-phase amendments require ratification because SOS-03 §15 mirrors the families).

### 5.2 Vector adapter shape

Each emitted vector is a Python class subclassing the abstract base `MembraneVector`:

```python
class MembraneVector(abc.ABC):
    """Base class for SOS-09-F membrane vectors."""

    trace_key: str            # MV-<UUID>-<family>-<seq>
    channel_id: str           # the UUID from sos:id
    channel_name: str         # the SV-identifier from sos:name
    channel_kind: str         # status | command | queue | shared
    channel_zone: str         # privileged | unprivileged
    family: str               # one of the six §5.1 families

    @abc.abstractmethod
    def setup(self, harness) -> None: ...

    @abc.abstractmethod
    def stimulate(self, harness) -> None: ...

    @abc.abstractmethod
    def observe(self, harness) -> Any: ...

    @abc.abstractmethod
    def assert_invariants(self, harness) -> None: ...
```

The harness binds to one of three forms:

1. **cocotb instantiating the RTL with a Python CPU stub (v1, ratified at the umbrella per PCDN-SOS-09-005)** — the harness instantiates the HDL register-file RTL via cocotb and runs the Python CPU stub against it via `harness.bus.read(addr)` / `harness.bus.write(addr, value)` / `harness.wait_irq(timeout)`.
2. **Real-hardware-loopback adapter (deferred future harness)** — the harness drives a physical board (e.g. the disco-analyzer at `streamz/submodules/disco-analyzer/`) and the Python adapter calls JTAG / probe-rs commands; deferred until a bench-substrate harness lands.
3. **Python CPU stub running against the RTL via cocotb (the v1 specialisation of (1))** — identical to (1) at v1; the distinction matters when (2) lands and the harness type-axis grows.

The harness `setup(...)` phase MAY install the MPU configuration via SOS-09-G's `sos_mpu_install()` runtime hook before any vector runs (this is mandatory for the protection family per §5.7 and INV-S-MEM-F-5).

Frozen-enumeration registration policy: **Standards Action** for the four-method protocol (adding a fifth method or removing one breaks every emitted adapter); **Specification Required** for the harness-binding form set (adding harness type #2 is a phase-owner walkthrough update; see §5.4 for the harness policy).

### 5.3 Traceability key format

Every emitted vector carries a stable identifier:

```
trace_key = "MV-" + <chart-sos-id-UUID> + "-" + <family> + "-" + <seq>
```

where:

- `<chart-sos-id-UUID>` is the RFC 4122 canonical hyphenated UUID per PCDN-SOS-09-A-003 ratification 2026-05-25 (e.g. `550e8400-e29b-41d4-a716-446655440000`). This is the identity-only handle from SOS-09-A's `sos:id` chart annotation.
- `<family>` is one of the six §5.1 family names verbatim.
- `<seq>` is a monotonically increasing per-channel-per-family integer assigned by the walker (e.g. when a channel produces multiple `write_then_read` vectors covering different legal-value sets).

The UUID-rooted identifier means:

- A chart rename of `sos:name` (the human-readable / emission-facing handle, per SOS-09-A's identity/name split) does NOT invalidate vector identity. Renames preserve traceability; the emitted SVD register name, RTL signal name, and C macro name all change, but the vector's `trace_key` stays bit-identical because `sos:id` is unchanged.
- Only `sos:id` regenerations break the chain. Per PCDN-SOS-09-F-004 (default: explicit `--regen-id` flag), UUID changes are rare and require operator opt-in.
- The chart-trace UUID is the dereferenceable handle: tooling can map `<chart-sos-id-UUID>` back to the originating chart and state, render the channel's full chart-vocabulary context (chart state, transition, invariant), and surface that in failure messages per §5.6.

Per INV-S-MEM-F-3, vector identifiers are stable under `sos:name` rename (UUID-rooted).

Frozen-enumeration registration policy: **Standards Action** (the key format is the cross-phase traceability contract; any change retroactively invalidates every emitted vector's history).

### 5.4 Co-simulation harness

Per PCDN-SOS-09-005 (ratified at the umbrella 2026-05-23), the v1 co-simulation harness is **cocotb with a Python CPU stub**. The Python CPU stub provides the following primitives that the vector adapter calls via the harness:

- **`harness.bus.read(addr) -> value`** — issue a single-register read at the chart-declared address; returns the value the HDL register-file RTL drives onto the bus.
- **`harness.bus.write(addr, value) -> None`** — issue a single-register write at the chart-declared address with the supplied value.
- **`harness.wait_irq(timeout_ns) -> irq_name`** — block (under cocotb's coroutine yield) until an IRQ line asserts; return the chart-declared logical IRQ name (per SOS-09 PCDN-004 logical-IRQ mapping). Raises `TimeoutError` on `timeout_ns` expiry.
- **`harness.concurrent_writer(coro) -> handle`** — spawn a cocotb coroutine that runs concurrently with the calling vector's stimulus, returning a handle for later `await handle`. Used by the atomicity family per §5.7.
- **`harness.install_mpu()`** — call SOS-09-G's `sos_mpu_install()` runtime hook (via the Python CPU stub's loopback to the SW side) to install the chart-declared MPU configuration before protection vectors run.
- **`harness.set_zone(zone)`** — switch the Python CPU stub's current privilege zone between `privileged` and `unprivileged`; subsequent `harness.bus.read/write` calls run under the named zone. Used by the protection family per §5.7.
- **`harness.seed(seed_value)`** — deterministic seed for any randomised stimulus (per PCDN-SOS-09-F-001 default: chart-UUID-derived deterministic seed).

The harness state is deterministic per INV-S-MEM-F-6: chart annotation + seed produce bit-identical traces across replays.

Cycle-accurate ISS integration (linking a real Cortex-M ISS into the cocotb test) is deferred indefinitely per the umbrella's PCDN-SOS-09-005 ratification. Real-hardware-loopback (a bench-substrate harness driving a physical board) is also deferred; the v1 cocotb harness is sufficient for the membrane contract (read/write pairing, side effects, atomicity under chart-permitted concurrency, protection rejection).

Frozen-enumeration registration policy: **Specification Required** for adding harness #2 (real-hardware-loopback) or harness #3 (cycle-accurate ISS) — these are phase-owner walkthrough updates, not §16 amendments. The four-primitive set of the Python CPU stub (`read`, `write`, `wait_irq`, `concurrent_writer`) is **Standards Action** — removing a primitive breaks every emitted adapter.

### 5.5 Vector report format

The harness emits a JUnit-XML report for CI consumption. Each `<testcase>` element carries:

- `name` attribute — the chart traceability key per §5.3 (`MV-<UUID>-<family>-<seq>`).
- `classname` attribute — the chart's emitted name path: `<chart_id>.<peripheral>.<channel_name>` (where `<channel_name>` is the SV-identifier-shaped `sos:name`, per SOS-09-A's identity/name split).
- `time` attribute — wall-clock duration of the cocotb simulation step for this vector.

Failure cases emit a child `<failure>` element with:

- `type` attribute — one of `WriteThenReadMismatch`, `SideEffectNotObserved`, `ClearOnReadNotCleared`, `AtomicityTornRead`, `AtomicityMutexNotSerialised`, `ProtectionAccessAccepted`, `ProtectionEventNotObserved`, `InitialValueMismatch`. The set is **Specification Required**; adding a failure type is a phase-owner update.
- text content — the chart-vocabulary failure message per §5.6.

Per PCDN-SOS-09-F-005's recommendation, the JUnit XML schema variant is **cocotb's native pytest output** (cocotb already emits this; CI consumers already parse it). The Jenkins-XUnit and Surefire variants are rejected at v1 to avoid a separate schema-translation layer.

The report MUST be deterministic per (chart, harness, seed) — chart trace keys appear in stable lexicographic order; `time` attributes are the only environment-dependent field, and CI consumers MUST NOT diff on `time`.

Per INV-S-MEM-F-4, vectors emit a JUnit XML report; CI parses it; failures block merge.

Frozen-enumeration registration policy: **Specification Required** (the report shape lives at the CI-consumer boundary; tightening or loosening the failure-type set is a phase-owner walkthrough update, not a §16 amendment).

### 5.6 Failure-rendering vocabulary

Every `assert_invariants` failure renders a message of shape:

```
"channel <sos:name> [kind=<kind>, zone=<zone>] failed <family> vector at <stimulus>: expected <X>, got <Y>; chart trace: <sos:id-UUID>"
```

where:

- `<sos:name>` is the chart-declared SV-identifier-shaped channel name (per SOS-09-A §5.2; emission-facing handle).
- `<kind>` is one of `status` / `command` / `queue` / `shared` (per SOS-09 §5.1).
- `<zone>` is one of `privileged` / `unprivileged` (per SOS-09 §5.4).
- `<family>` is one of the six §5.1 family names.
- `<stimulus>` is the human-readable rendering of the chart-vocabulary stimulus that triggered the failure (e.g. `"write of 0xDEADBEEF to control register from unprivileged context"`).
- `<X>` and `<Y>` are the expected and observed values, rendered in chart vocabulary where possible (e.g. `"IRQ line hw_data_ready asserted"` rather than `"NVIC bit 73 set"`).
- `<sos:id-UUID>` is the chart's `sos:id` UUID. The chart-trace UUID is mandatory — every failure message MUST carry it. Tooling MAY dereference the UUID back to the originating chart and state to render full context.

Example failure messages:

- `"channel rx_status [kind=status, zone=privileged] failed clear_on_read vector at second read after consume: expected 0x00000000, got 0xDEADBEEF; chart trace: 550e8400-e29b-41d4-a716-446655440000"`
- `"channel auth_command [kind=command, zone=privileged] failed protection vector at write of 0x1 from unprivileged context: expected access-violation event, got silent rejection; chart trace: 6ba7b810-9dad-11d1-80b4-00c04fd430c8"`
- `"channel shared_state [kind=shared, zone=privileged] failed atomicity vector at concurrent SW write + HW write: expected mutex_claim_count=2, got mutex_claim_count=1; chart trace: 6ba7b811-9dad-11d1-80b4-00c04fd430c8"`

Per INV-S-MEM-F-2, every vector failure message names a chart `sos:name` and a `sos:id` UUID; raw-address-only failures are an emitter error.

Per INV-SOS-H (vector-to-chart traceability, SOS-07 §6), the failure-rendering vocabulary is the chart-side, not the wire-side. This freeze operationalises INV-SOS-H for the membrane-vector surface.

Frozen-enumeration registration policy: **Standards Action** (the message shape is the cross-phase chart-trace contract; loosening it allows raw-address-only failures, which INV-S-MEM-F-2 prohibits).

### 5.7 Atomicity vector — concurrent-stimulus model

For `mutex-required` registers (per SOS-09 §5.3 atomicity-class enum), the atomicity vector exercises concurrent producers across the membrane:

1. **Setup.** The vector adapter's `setup` installs the chart-declared MPU configuration (via SOS-09-G's `sos_mpu_install`) and primes the chart's mutex region (the `sos_mutex` instance from SOS-08-A §6 emitted by SOS-09-E).
2. **Concurrent stimulus.** Per PCDN-SOS-09-F-002's recommendation (default: cocotb coroutine pair, idiomatic for the framework), the harness launches two cocotb coroutines via `harness.concurrent_writer(...)`:
   - **HW-side coroutine** — drives the chart-declared HW-side stimulus (e.g. a queue-depth change, a status-register update, a side-effect-on-write trigger).
   - **SW-side coroutine** — drives the chart-declared SW-side stimulus via `harness.bus.write(addr, value)` from the Python CPU stub.
   - Both coroutines start at the same cocotb simulation tick (within ±1 clock cycle of each other) to maximise the race window.
3. **Observation.** The vector adapter's `observe` reads the register pair (the protected state + the chart-declared status surface) and queries the `sos_mutex` instance for `mutex_claim_count` and `successful_access_count`. The harness exposes these via `harness.mutex_claim_count(mutex_name)` and `harness.successful_access_count(mutex_name)`.
4. **Assertions.** The vector adapter's `assert_invariants` asserts:
   - **No torn read.** The observed value is one of the two complete values written (either fully HW-side's value or fully SW-side's value); no bit-interleaved mixture.
   - **Mutex serialisation.** `mutex_claim_count == 2` (both sides claimed) AND `successful_access_count == 2` (both sides eventually succeeded; the mutex did not deadlock or starve).

The alternative concurrent-stimulus model (explicit two-process model with a separate process spawn per stimulus side) is rejected at v1 per PCDN-SOS-09-F-002 — cocotb's coroutine pair is the idiomatic shape and avoids a process-management layer the harness does not otherwise need.

Frozen-enumeration registration policy: **Standards Action** (the concurrent-stimulus model is the load-bearing definition of "atomicity vector"; flipping to two-process would change what the vector tests).

## 6. Cross-sub-phase invariants — INV-S-MEM-F-1 through INV-S-MEM-F-6

In addition to the cross-phase invariants INV-SOS-A through H (from SOS-07 §6) and the SOS-09 cross-sub-phase invariants INV-S-MEM-1 through 6 (from SOS-09 §7), the following invariants are normative within SOS-09-F:

- **INV-S-MEM-F-1 — Every chart-declared channel produces ≥1 vector of every family applicable to its `kind`.** The chart-to-vector emission walker enumerates the chart's `sos:`-prefixed channel annotations (per SOS-09-A) and, for each, emits the cross-product `(channel × applicable families)` of vectors per the §5.1 table. A channel that fails to emit a required vector is a codegen error, not a warning. Per INV-SOS-B (vectors-as-deliverable), the vector suite IS the integration contract — silent dropping is the worst failure mode this sub-phase prevents.

- **INV-S-MEM-F-2 — Every vector failure message names a chart `sos:name` AND a `sos:id` UUID.** Raw-address-only failure messages are an emitter error caught at vector-emission time (the emitter validates the failure-message template against the §5.6 shape). Per INV-SOS-H, vector failures cite the chart state / transition / invariant; this invariant is the SOS-09-F operationalisation. A failure message that says `"register 0x40004000 returned 0xDEADBEEF when 0x00000000 was expected"` is an emitter bug; the correct shape is `"channel rx_status [kind=status, zone=privileged] failed initial_value vector at reset read: expected 0x00000000, got 0xDEADBEEF; chart trace: <uuid>"`.

- **INV-S-MEM-F-3 — Vector identifiers are stable under `sos:name` rename (UUID-rooted).** Per §5.3, the traceability key is rooted in `sos:id` UUID, not in `sos:name`. A chart edit that renames `sos:name="rx_status"` to `sos:name="receive_status"` updates the emitted SVD register name, the RTL signal name, and the C macro — but the vector's `trace_key` stays bit-identical. CI's vector history (pass/fail flake tracking) survives chart renames. Per PCDN-SOS-09-F-004 (default: explicit `--regen-id` flag), UUID regenerations are rare and require explicit operator opt-in.

- **INV-S-MEM-F-4 — Vectors emit a JUnit XML report; CI parses it; failures block merge.** The §5.5 report shape is the load-bearing CI-consumer contract. A vector that runs but does not emit a `<testcase>` entry is an emitter bug. The report MUST be parseable by every consumer of the canonical pytest-XUnit shape (per PCDN-SOS-09-F-005). Failures MUST block merge in CI; the SOS-09-emitted IP block ships with the vector suite as the integration contract, and a failing vector means the IP block does not satisfy its own contract.

- **INV-S-MEM-F-5 — Protection vectors that succeed (i.e. the channel rejected the unauthorised access) MUST observe the access-violation event surfaced by SOS-09-E's per-channel-group strobe-latch (`INV-S-MEM-E-5`).** A "rejected silently" outcome — where the write is rejected but no event surfaces — is a test failure, not a pass. Per PCDN-SOS-09-F-003 (default: fatal error), silent rejection is the worst failure mode SOS-09's end-to-end protection is supposed to prevent — silent acceptance of an attempt that should have been logged for SW-side audit. The protection vector's `assert_invariants` MUST assert BOTH: (a) the write was rejected (the protected state was not modified), AND (b) the access-violation event fired (observed via `harness.wait_irq(...)` against the per-channel-group strobe-latch).

- **INV-S-MEM-F-6 — Co-simulation harness state is deterministic from the chart annotation + the vector seed; replays produce bit-identical traces.** Per PCDN-SOS-09-F-001's recommendation (chart-UUID-derived deterministic seed), the same chart + same vector + same seed produce bit-identical cocotb simulation traces across CI nodes, across operator workstations, across years. Non-determinism (system clock dependency, environment-dependent state, map-iteration-order variance) is prohibited. This mirrors INV-SOS-G (verified-codegen position) at the vector-emission level: the emission is a pure function of (chart, target, seed).

## 7. Enumeration policies recap

This sub-phase freezes the following enumerations (each declared in §5 with its registration policy):

| Section | Frozen enumeration | Registration policy |
|---|---|---|
| §5.1 | Vector family set `{ initial_value, write_then_read, side_effect, clear_on_read, atomicity, protection }` | **Standards Action** |
| §5.1 | Family → channel-kind applicability table | **Standards Action** |
| §5.2 | `MembraneVector` four-method protocol `{setup, stimulate, observe, assert_invariants}` | **Standards Action** |
| §5.2 | Harness-binding form set `{cocotb+stub, real-hw-loopback (deferred), ISS (deferred)}` | **Specification Required** |
| §5.3 | Traceability key shape `MV-<UUID>-<family>-<seq>` | **Standards Action** |
| §5.4 | Python CPU stub primitive set `{read, write, wait_irq, concurrent_writer, install_mpu, set_zone, seed}` | **Standards Action** for the first four; **Specification Required** for the latter three (chart-mode primitives) |
| §5.5 | JUnit XML report shape (`<testcase>` attributes; `<failure>` types) | **Specification Required** |
| §5.6 | Failure-message vocabulary shape | **Standards Action** |
| §5.7 | Atomicity concurrent-stimulus model (cocotb coroutine pair) | **Standards Action** |
| §6 | INV-S-MEM-F-1 through INV-S-MEM-F-6 | **Standards Action** |

## 8. Standards integration matrix additions

This sub-phase EXTENDS the SOS-07 §7 matrix and the SOS-09 §8 row set. SOS-09-F uses the existing rows without modification AND adds the following SOS-09-F-specific clarifications:

| Concept | Upstream authority | Local relationship | Phase that declares it | Mutation rights |
|---|---|---|---|---|
| cocotb (Coroutine-based COsimulation TestBench) | open project (Potential Ventures) | **derive** — SOS-09-F emits Python adapters that the cocotb test loader collects; cocotb's coroutine model and bus-transaction primitives are upstream. The Python CPU stub composes with cocotb's existing simulator hooks. | this doc | none — cocotb is upstream |
| pytest collector (cocotb's pytest plugin) | open project (pytest + cocotb) | **derive** — SOS-09-F's JUnit XML report shape is whatever cocotb's existing pytest collector emits. Adopting a non-pytest collector is a §16 amendment. | this doc | none — pytest emits the canonical shape |
| JUnit XML (cocotb pytest-native variant) | open project (Surefire / Jenkins-XUnit lineage; pytest emits the canonical shape) | **derive** — SOS-09-F emits the variant pytest produces; CI consumers parse it via standard tooling. | this doc | none — schema is upstream |
| SOS-03 base vector framework | `SOS-03-CONCEPTS.md` (local; SOS authors) | **adapt** — SOS-09-F adds the six membrane-vector families to SOS-03's vocabulary via the SOS-03 §15 amendment co-landing with SOS-09 umbrella ratification. The vector IR (per SOS-08-D PCDN-008 resolution) is reused without modification. | this doc + SOS-03 §15 amendment | SOS-03 owns the base framework; SOS-09-F extends via amendment |
| SOS-08-D cocotb framework for HDL targets | `SOS-08-D-CONCEPTS.md` (local; SOS authors) | **compose** — SOS-09-F's harness wraps SOS-08-D's cocotb-test entry points with the membrane-vector adapter layer. SOS-08-D owns the cocotb-test scaffolding; SOS-09-F owns the membrane-vector specialisation. | this doc | SOS-08-D owns the base scaffolding; SOS-09-F composes |
| SOS-09-A chart annotation surface | `SOS-09-A-CONCEPTS.md` (sibling; ratified 2026-05-25) | **mirror** — SOS-09-F reads the chart's `sos:`-prefixed JSON keys (`sos:id`, `sos:name`, `sos:kind`, `sos:zone`, `sos:atomicity`, etc.) from `other_attributes` per PCDN-SOS-09-001 amended 2026-05-25. | this doc | SOS-09-A owns the annotation schema; SOS-09-F consumes |
| SOS-09-B CMSIS-SVD register surface | `SOS-09-B-CONCEPTS.md` (sibling; ratified 2026-05-25) | **mirror** — SOS-09-F enumerates the register set under test by reading the SVD emitted by SOS-09-B. The CMSIS-SVD round-trip per `INV-S-MEM-B-5` is exercised by the side-effect family vectors. | this doc | SOS-09-B owns the SVD shape; SOS-09-F consumes |
| SOS-09-E access-violation event (`INV-S-MEM-E-5`) | `SOS-09-E-CONCEPTS.md` (sibling; ratification in flight) | **mirror** — SOS-09-F's protection-family vectors observe the per-channel-group strobe-latch the SOS-09-E HDL register-file emits on cross-zone access attempts. | this doc | SOS-09-E owns the event surface; SOS-09-F observes |
| SOS-09-G MPU configuration `sos_mpu_install()` | `SOS-09-G-CONCEPTS.md` (sibling; ratified 2026-05-25) | **compose** — SOS-09-F's protection-family vectors call SOS-09-G's `sos_mpu_install` runtime hook during the harness `setup` phase, before the protection stimulus runs. | this doc | SOS-09-G owns the runtime hook; SOS-09-F invokes |
| RFC 4122 UUID canonical hyphenated form | IETF | **mirror** — SOS-09-F's traceability key embeds the RFC 4122 UUID per SOS-09-A's `sos:id` shape. | this doc | none — RFC 4122 is upstream |

Per INV-SOS-E, the row addition policy mirrors SOS-07 §7 and SOS-09 §8: **Specification Required** for adding new rows (phase-owner walkthrough); **Standards Action** for modifying an existing row's relationship value.

## 9. Frozen enumerations recap

(Subsumed into §7 above — the per-section registration-policy table is the canonical recap. This §9 entry is preserved for shape consistency with the SOS-09-A / SOS-09-B precedents but is informative-only.)

## 10. Reconciliation decisions vs adjacent repo primitives

### vs. SOS-03 base vector framework

SOS-03 is the base vector framework; SOS-09-F is a vector-shape extension. The SOS-03 §15 amendment co-lands with the SOS-09 umbrella ratification, adding the six membrane-vector families to the framework's catalog per the umbrella's §10 reconciliation row. The vector IR (per SOS-08-D PCDN-008 resolution) is reused without modification. SOS-09-F does NOT redefine SOS-03's base vector contract; it adapts (per §8 relationship `adapt`) by adding the membrane-vector subclass set.

### vs. SOS-08-D cocotb framework for HDL targets

SOS-08-D owns the cocotb-test scaffolding for HDL targets — the test loader, the simulator interface, the bus-transaction primitives. SOS-09-F composes with SOS-08-D by wrapping the cocotb-test entry points with the `MembraneVector` adapter layer. The Python CPU stub is a SOS-09-F primitive that runs inside SOS-08-D's cocotb test harness. There is no fork or duplication; the relationship is `compose` per §8.

### vs. SOS-09-A chart annotation surface

SOS-09-F **consumes** SOS-09-A's annotation schema as input. The walker reads `sos:id`, `sos:name`, `sos:kind`, `sos:dir`, `sos:zone`, `sos:atomicity`, `sos:irq`, `sos:mutex`, `sos:side_effect`, `sos:clear_on_read` from `other_attributes` JSON per PCDN-SOS-09-001 amended 2026-05-25. SOS-09-F does NOT extend the attribute set; new SOS-semantic keys are SOS-09-A's authority. The identity/name split per PCDN-SOS-09-A-003 ratification 2026-05-25 is load-bearing: the traceability key per §5.3 uses `sos:id` (UUID) as the stability anchor, while the failure-message vocabulary per §5.6 uses `sos:name` (SV-identifier) as the chart-vocabulary surface.

### vs. SOS-09-B CMSIS-SVD register surface

SOS-09-F is **downstream** of SOS-09-B. The vector framework reads the SOS-09-B-emitted SVD to enumerate the register set under test. The six vector shapes consume the corresponding SVD elements: `<resetValue>` (initial-value family), `<access>` (write-then-read family applicability), `<modifiedWriteValues>` (side-effect family), `<readAction>` (clear-on-read family), and (for protection) the per-register access bits derived from chart `sos:zone`. SOS-09-B's INV-S-MEM-B-5 (side-effect round-trip) is the property SOS-09-F's side-effect vector exercises.

### vs. SOS-09-E HDL register-file RTL

SOS-09-E emits the synthesizable HDL register-file RTL that the cocotb harness instantiates. SOS-09-F's vectors stimulate the RTL via cocotb's bus-transaction primitives. SOS-09-E's `INV-S-MEM-E-5` (per-channel-group access-violation strobe-latch) is the event surface SOS-09-F's protection vectors observe per INV-S-MEM-F-5. Both paths derive from the same chart channel set per INV-S-MEM-1 (single-source register definition); the cocotb test runs the SVD-described register interface against the RTL-emitted bus-decode logic — they agree by construction because both come from the chart.

### vs. SOS-09-G MPU configuration

SOS-09-G's `sos_mpu_install()` runtime hook is called during the harness `setup` phase before protection vectors run. The cocotb test loops the Python CPU stub back through the SW-side runtime, which programs the MPU regions emitted by SOS-09-G. The protection vector then runs with the MPU enabled; the access-violation event surface (SOS-09-E) fires when the protection vector stimulates an unprivileged write. The trio — SOS-09-E (HW gate) + SOS-09-G (SW MPU install) + SOS-09-F (vector that observes both) — closes INV-S-MEM-3 (protection is end-to-end).

### vs. existing `tools/sos-codegen/` test fixtures

Search at draft time: no `vectors/*.py` or `*.junit.xml` membrane-vector artifacts exist under `tools/sos-codegen/`. The fixture directory `tools/sos-codegen/tests/fixtures/` contains chart fixtures (`.scxml` and `.json`) but no membrane-vector artifacts. Therefore, there are no pre-existing hand-rolled vectors to reconcile against; SOS-09-F's chart-driven emission is the sole authority for membrane-vector artifacts when the emit path lands.

Future paths the SOS-09-F implementation will create (forthcoming, not present at this draft):

- `tools/sos-codegen/vectors_emit.py` — the chart-to-vector emission walker (reads SOS-09-A annotations + SOS-09-B SVD; emits Python adapter files).
- `tools/sos-codegen/vectors/base.py` — the `MembraneVector` base class + the six family subclasses.
- `tools/sos-codegen/vectors/harness.py` — the cocotb-with-Python-CPU-stub harness implementation.
- `build/vectors/<chart_id>/test_*.py` — emitted vector adapter files (per INV-S-MEM-2 lives under `build/`, not tracked source).
- `build/vectors/<chart_id>/junit.xml` — emitted JUnit XML report (per INV-S-MEM-2, build output).

### vs. PCDN-SOS-09-001 amended 2026-05-25

The amendment that routes channel annotations through `other_attributes` (vs the originally-resolved `xmlns:sos` namespace) is a load-bearing input to SOS-09-F's read path. SOS-09-F MUST read `sos:`-prefixed keys from `other_attributes` JSON; reading from XML namespace prefixes would be reading a surface that PCDN-SOS-09-001 amended 2026-05-25 explicitly retracted. SOS-09-F emits no `xmlns:sos` declaration into any artifact — vector adapter files, JUnit XML reports, and the Python CPU stub all use `sos:`-prefixed JSON keys (or, in Python, plain attribute names like `channel_kind`).

## 11. Non-goals

This sub-phase does NOT:

- **Author a full hardware-in-the-loop (HIL) framework at v1.** Real-hardware-loopback adapters (the bench-substrate harness driving a physical board like the disco-analyzer) are deferred until a bench-substrate harness lands as its own phase. v1 ships the cocotb-with-Python-CPU-stub harness only.
- **Integrate a cycle-accurate ISS at v1.** Per umbrella PCDN-SOS-09-005, cycle-accurate ISS integration (linking a real Cortex-M ISS into the cocotb test) is deferred indefinitely. The Python CPU stub is sufficient for the membrane contract (read/write pairing, side effects, atomicity under chart-permitted concurrency, protection rejection).
- **Cover timing-closure verification.** Static timing analysis (`Fmax`, setup/hold margin) is the synthesis tool's job, not the membrane-vector suite's. SOS-09-F vectors run against the cocotb-simulated HDL, which has no notion of physical timing; the cocotb simulation is functionally-accurate, not timing-accurate.
- **Author SOS-03's base vector framework.** That's `SOS-03-CONCEPTS.md`. SOS-09-F adapts (per §8) by adding the six membrane-vector families via the SOS-03 §15 amendment co-landing.
- **Author SOS-08-D's cocotb HDL test scaffolding.** That's `SOS-08-D-CONCEPTS.md`. SOS-09-F composes (per §8) by wrapping SOS-08-D's cocotb-test entry points.
- **Author the chart annotation surface, the CMSIS-SVD emitter, the C/Rust HAL emitters, the HDL register-file emitter, or the MPU configuration emitter.** Those are SOS-09-A, SOS-09-B, SOS-09-C/D, SOS-09-E, and SOS-09-G respectively. SOS-09-F consumes their outputs.
- **Verify hardware metastability.** Per INV-S-HDL-3 (from SOS-08 §7), `sos_synchronizer` flops are excluded from formal verification; MTBF handles that path. SOS-09-F vectors do not exercise cross-domain timing.
- **Register an XML namespace URL.** Per PCDN-SOS-09-001 amended 2026-05-25, no `xmlns:sos` URL is registered or claimed; `sos:` is a JSON-key string prefix.

## 12. Acceptance checklist

A conforming SOS-09-F ratification satisfies:

- (a) ✅ The SOS-09-F concepts doc is present at `docs/concepts/SOS-09-F-CONCEPTS.md` with the §0..§16 section shape per the parent CLAUDE.md "Phase document shape".
- (b) ✅ PCDN-SOS-09-F-001 through 005 resolved (§15) — ratified 2026-05-26.
- (c) ✅ The chart-to-vector emission walker is present at `tools/sos-codegen/vectors_emit.py` and enumerates the chart's `sos:`-prefixed channel annotations via SOS-09-A's read surface (`plan_chart` / `plan_channel`).
- (d) ✅ Vector family coverage per kind: for each channel kind (`status`, `command`, `queue`, `shared`), the emitter produces at least one vector of every family applicable per the §5.1 table (mirrored in `vectors.base.FAMILIES_BY_KIND` + per-channel-attribute gating in `vectors_emit._applicable_families`).
- (e) ✅ The emitted vector identifier matches the §5.3 traceability-key format `MV-<UUID>-<family>-<seq>` with the UUID being the chart-declared `sos:id` (RFC 4122 canonical hyphenated form per PCDN-SOS-09-A-003 ratification 2026-05-25). Asserted in `tests/test_vectors_emit.py::TestGateETraceKeyFormat`.
- (f) ✅ Harness type-1 (cocotb with Python CPU stub) is implemented at `tools/sos-codegen/vectors/harness.py` and exposes the seven primitives of §5.4 (`bus.read`, `bus.write`, `wait_irq`, `concurrent_writer`, `install_mpu`, `set_zone`, `seed`).
- (g) ✅ The harness emits a JUnit XML report at `build/vectors/<chart_id>/junit.xml` (per INV-S-MEM-2, build output) consumable by the canonical pytest-XUnit shape per PCDN-SOS-09-F-005. Emitted by `vectors_emit.run_vectors`.
- (h) ✅ Failure-message vocabulary matches the §5.6 shape: every failure names channel `sos:name`, channel `kind`, channel `zone`, family, stimulus, expected, observed, and the `sos:id` UUID. Raw-address-only failures are an emitter error per INV-S-MEM-F-2 (`vectors.base.render_failure_message` refuses empty `channel_name`, non-UUID `channel_id`, and empty `stimulus`).
- (i) ⏸ Protection-vector access-violation observation: every protection vector that succeeds (channel rejected the unauthorised access) observes the SOS-09-E per-channel-group strobe-latch firing (INV-S-MEM-F-5; INV-S-MEM-E-5). Silent rejection is a test failure per PCDN-SOS-09-F-003. **Wave-1 status:** the harness's in-process strobe-latch counter (`PythonCpuStubHarness.access_violation_count`) satisfies the invariant against the Python-stub path; the cocotb-path check moves to reading the per-channel-group HDL strobe-latch from `sos_regfile.{vhd,sv}.j2` once SOS-09-E is cherry-picked. The TODO marker in `vectors/harness.py` cites SOS-09-E delivery. Gate flips ✅ on SOS-09-E template cherry-pick.

(a) is the doc-presence gate; (b) is the ratification gate; (c)–(i) are implementation gates that flip from ⏸ to ✅ as the implementation lands.

A conforming SOS-09-F *without* the atomicity family (i.e. charts with no `mutex-required` channels) satisfies (a)–(h) with reduced coverage at (d). This second-tier conformance level supports first-target ECP5 bring-up demos that exercise only the plain register surface, deferring atomicity coverage to subsequent rounds.

## 13. Files cited

| Path | Role |
|---|---|
| `docs/concepts/SOS-09-CONCEPTS.md` | Umbrella; this sub-phase's parent. §5 frozen enums consumed; §6 SOS-09-F summary informative; §7 INV-S-MEM-1 through 6 cited; PCDN-SOS-09-005 (cocotb + Python CPU stub) load-bearing input. |
| `docs/concepts/SOS-07-CONCEPTS.md` | Cross-phase invariants INV-SOS-A through H; AuthorityRelationship matrix. INV-SOS-B and INV-SOS-H load-bearing for this sub-phase. Cited not redefined. |
| `docs/concepts/SOS-09-A-CONCEPTS.md` | Chart annotation surface; SOS-09-F consumes `sos:`-prefixed JSON keys from `other_attributes`. The `sos:id` / `sos:name` identity/name split per PCDN-SOS-09-A-003 ratification 2026-05-25 is load-bearing. |
| `docs/concepts/SOS-09-B-CONCEPTS.md` | CMSIS-SVD emission; SOS-09-F enumerates the register set under test by reading the SVD. INV-S-MEM-B-5 (side-effect round-trip) is exercised here. |
| `docs/concepts/SOS-09-E-CONCEPTS.md` | HDL register-file RTL (sibling; ratification in flight). INV-S-MEM-E-5 (per-channel-group access-violation strobe-latch) is the event surface protection vectors observe per INV-S-MEM-F-5. |
| `docs/concepts/SOS-09-G-CONCEPTS.md` | MPU configuration emission; `sos_mpu_install()` runtime hook is called during the harness `setup` phase before protection vectors run. |
| `docs/concepts/SOS-03-CONCEPTS.md` | Base vector framework; SOS-09-F adapts via SOS-03 §15 amendment co-landing with SOS-09 umbrella ratification. |
| `docs/concepts/SOS-08-D-CONCEPTS.md` | cocotb framework for HDL targets; SOS-09-F composes by wrapping SOS-08-D's cocotb-test entry points with the membrane-vector adapter layer. |
| `tools/sos-codegen/` | Codegen tool; SOS-09-F emit path lives under `tools/sos-codegen/vectors_emit.py` + `tools/sos-codegen/vectors/` (forthcoming). |
| `tools/sos-codegen/tests/test_sos_09_f_concepts_doc.py` | Concepts-doc structural assertion suite for this sub-phase. |
| `build/vectors/<chart_id>/` | Emitted vector adapter directory (forthcoming; per INV-S-MEM-2 lives under `build/`, not tracked source). |
| Parent `CLAUDE.md` | Spec-Before-Code Planning Discipline; Phase document shape. |

## 14. Unblocks

This sub-phase's ratification (after PCDN walkthrough) unblocks:

- **The SOS-09 integration loop closure.** Membrane vectors are the integration-contract enforcement that ties together SOS-09-A (chart annotation), SOS-09-B (CMSIS-SVD), SOS-09-C/D (C/Rust HAL), SOS-09-E (HDL register-file RTL), and SOS-09-G (MPU configuration). Without SOS-09-F, the umbrella's INV-SOS-B (vectors-as-deliverable) is unenforceable.
- **SOS bench validation runs.** A chart annotated with SOS-09 channels can ship to the bench (cocotb-simulated at v1; real-hardware-loopback in a future phase) with the vector suite as the integration test.
- **The first end-to-end chart-driven SoC bring-up demo.** Per SOS-09 §14, the demo is chart → CMSIS-SVD + Rust HAL + HDL register file + membrane vectors → Yosys+nextpnr ECP5 bitstream → cocotb-validated round-trip, with the chart as the single source. SOS-09-F is the cocotb-validated round-trip half.
- **CI gating on chart-driven IP blocks.** The JUnit XML report (§5.5) plugs into the standard CI consumer; failures block merge per INV-S-MEM-F-4.
- **The SOS-03 §15 amendment** that adds the six membrane-vector families to the base vector framework's catalog (umbrella §12 (g) gate).

## 15. Pending Concept Decision Notices (PCDNs)

These open questions move this doc from 🟡 drafted to 🟢 ratified. PCDN-SOS-09-F-* identifiers are stable per parent CLAUDE.md "Errata Open Question" naming convention (analogous shape applies — these are PCDNs at the concepts-doc level).

- **PCDN-SOS-09-F-001 — Vector seed source: chart UUID-derived deterministic seed vs `PYTEST_SEED` env var.** 🟢 **RATIFIED 2026-05-26 — accepted option (a) chart-UUID-derived deterministic seed.** Options: (a) chart-UUID-derived deterministic seed — the seed is a hash of the chart's `sos:id` UUID plus the vector family plus the `<seq>`; (b) `PYTEST_SEED` env var — the operator sets the seed via env; (c) hybrid — chart-UUID-derived default; `PYTEST_SEED` env var override. **Recommendation**: option (a) chart-UUID-derived deterministic seed at v1. Determinism across CI nodes and operator workstations is the load-bearing property (per INV-S-MEM-F-6); env-var-driven seeds break determinism the moment two CI nodes have different env. The hybrid (c) is appealing but adds a divergence path that bug-hunting eventually exploits. Per the umbrella's INV-SOS-G (verified-codegen position), determinism is the contract; the chart-UUID-derived seed makes it bit-identical-by-construction. Registration policy: **Specification Required** (the seed source is a phase-local mechanic; flipping it later is cheap).

- **PCDN-SOS-09-F-002 — Concurrent-stimulus model for atomicity: cocotb coroutine pair vs explicit two-process model.** 🟢 **RATIFIED 2026-05-26 — accepted option (a) cocotb coroutine pair.** Options: (a) cocotb coroutine pair — the HW-side and SW-side stimuli are two cocotb coroutines that run concurrently under cocotb's scheduler; (b) explicit two-process model — the HW-side and SW-side run as separate OS processes with a synchronization barrier. **Recommendation**: option (a) cocotb coroutine pair at v1. Idiomatic for the framework; avoids a process-management layer the harness does not otherwise need; cocotb's coroutine scheduler is deterministic given a seed (per PCDN-SOS-09-F-001). The two-process model would require a wire-level synchronization primitive between processes — adding it for the atomicity family only is over-engineering. Registration policy: **Standards Action** (the concurrent-stimulus model is the load-bearing definition of "atomicity vector"; flipping to two-process would change what the vector tests).

- **PCDN-SOS-09-F-003 — Protection-vector failure when the access ISN'T rejected: fatal error vs warning.** 🟢 **RATIFIED 2026-05-26 — accepted option (a) fatal error on un-rejected protection-vector access.** Options: (a) fatal error — silent acceptance of an unauthorised access is the worst failure mode SOS-09 prevents; (b) warning — chart-author can knowingly omit zone enforcement (e.g. during early bring-up); (c) mode-gated — fatal in CI, warning in interactive vector authoring. **Recommendation**: option (a) fatal error at v1. Silent acceptance of unauthorised access is the worst failure mode SOS-09's end-to-end protection is supposed to prevent (per INV-S-MEM-3). The "rejected silently" outcome is what makes a register-map PDF lie — the audit trail is missing. The mode-gated form (c) is appealing for early bring-up but adds a configuration surface that a future operator inevitably leaves on "warning" by accident. Registration policy: **Standards Action** (the policy encodes the protection-vector's pass/fail definition; flipping it changes what "passing" means).

- **PCDN-SOS-09-F-004 — Vector regeneration policy on `sos:id` change: auto-regenerate vs require explicit `--regen-id` flag.** 🟢 **RATIFIED 2026-05-26 — accepted option (b) explicit `--regen-id` flag.** Options: (a) auto-regenerate — when the chart's `sos:id` UUID changes (e.g. the chart author edits the UUID directly), the emitter auto-updates the traceability keys on every emitted vector; (b) require explicit `--regen-id` flag — UUID changes are gated behind a CLI flag, requiring operator opt-in. **Recommendation**: option (b) explicit `--regen-id` flag at v1. UUID changes are rare (operators rarely edit UUIDs directly; the more common case is `sos:name` rename, which preserves UUID and traceability per INV-S-MEM-F-3). Accidental UUID regeneration breaks vector lineage (CI vector history loses continuity); requiring opt-in catches accidental cases. The `--regen-id` flag emits a build-time log line naming every channel whose `sos:id` changed. Registration policy: **Specification Required** (the gating is a phase-local mechanic).

- **PCDN-SOS-09-F-005 — JUnit XML schema variant: Jenkins-XUnit vs Surefire vs cocotb's native pytest output.** 🟢 **RATIFIED 2026-05-26 — accepted option (a) cocotb's native pytest-XUnit output.** Options: (a) cocotb's native pytest output — cocotb already emits the canonical pytest-XUnit shape; CI consumers (Jenkins, GitLab CI, GitHub Actions test reporter) already parse it; (b) Jenkins-XUnit — slight variant with additional Jenkins-specific attributes; (c) Surefire — Maven/Java lineage; widest historical compatibility but oldest schema. **Recommendation**: option (a) cocotb's native pytest output at v1. Lowest implementation cost; cocotb emits it without an additional schema-translation layer; CI consumers already parse it. The Jenkins-XUnit and Surefire variants would require a translation layer that has no other purpose in the SOS-09-F path. Registration policy: **Specification Required** (the schema variant is a CI-boundary mechanic; flipping it later is cheap if a downstream consumer demands a specific variant).

## 16. Ratification log

### 2026-05-26 — SOS09F1 implementation (Claude / Ira)

Membrane-vector emitter implementation landed under commit subject
`SOS09F1: implement membrane vectors emitter (gates c-i)`. Files added:

- `tools/sos-codegen/vectors_emit.py` — chart-to-vector emission walker + CLI (`--regen-id` flag per PCDN-SOS-09-F-004; chart-UUID-derived deterministic seed per PCDN-SOS-09-F-001; pytest-XUnit JUnit XML per PCDN-SOS-09-F-005).
- `tools/sos-codegen/vectors/__init__.py` — package exports.
- `tools/sos-codegen/vectors/base.py` — `VectorFamily` (six-family Standards-Action enum), `FAMILIES_BY_KIND` (§5.1 table), `MembraneVector` (four-method protocol), `VectorStep`, `ChannelVectorPlan`, `trace_key` (§5.3), `derive_seed` (PCDN-SOS-09-F-001), `render_failure_message` (§5.6 vocabulary; refuses raw-address-only messages per INV-S-MEM-F-2).
- `tools/sos-codegen/vectors/harness.py` — `PythonCpuStubHarness` exposing the seven §5.4 primitives (`bus.read`, `bus.write`, `wait_irq`, `concurrent_writer`, `install_mpu`, `set_zone`, `seed`); mutex serialisation surface for the atomicity family; per-channel-group access-violation strobe-latch surface (TODO marker references SOS-09-E delivery for the cocotb-path strobe-latch read).
- `tools/sos-codegen/vectors/families/{initial_value,write_then_read,side_effect,clear_on_read,atomicity,protection}.py` — six `MembraneVector` subclasses; each exports `generate(plan, seq) -> list[VectorStep]` per §5.2 + `vector_class`.
- `tools/sos-codegen/tests/test_vectors_emit.py` — 48 tests covering gates (c)–(i): emission walker (c), family-per-kind coverage (d), trace-key shape (e), seven primitives (f), JUnit XML emission (g), failure-vocabulary shape including deliberate-failure capture (h), protection-vector strobe-latch observation (i — gated on Python-stub path pending SOS-09-E HDL template).
- `tools/sos-codegen/tests/fixtures/sos_09_f/sos09f_worked_example.scxml` — chart fixture covering all six families across the four channel kinds.

§12 gate status post-implementation:

- (a) ✅ — concepts doc present, §0..§16 shape.
- (b) ✅ — five PCDNs ratified 2026-05-26.
- (c) ✅ — `vectors_emit.plan_chart` walks SOS-09-A annotations.
- (d) ✅ — `FAMILIES_BY_KIND` + per-attribute gating produces every applicable family per the §5.1 table.
- (e) ✅ — `trace_key` formatter + emitted JUnit testcase names match the `MV-<UUID>-<family>-<seq>` regex.
- (f) ✅ — `PythonCpuStubHarness` exposes the seven §5.4 primitives.
- (g) ✅ — `run_vectors` emits `build/vectors/<chart_id>/junit.xml` per pytest-XUnit shape.
- (h) ✅ — `render_failure_message` refuses raw-address-only messages and emits the §5.6 chart-vocabulary shape; deliberate-failure capture in tests confirms the regex match.
- (i) ⏸ — protection vector observes the access-violation event AND the strobe-latch delta via the Python-stub path; the cocotb-path bridge to `sos_regfile.{vhd,sv}.j2` strobe-latch register is pending SOS-09-E HDL template cherry-pick (TODO marker at `vectors/harness.py:access_violation_count`).

INV-S-MEM-F-1 through F-6 all satisfied against the Python-stub path; F-5's HDL-path binding is the remaining work item for the cocotb cherry-pick.

### 2026-05-26 — Ratified (Ira + Claude walkthrough)

PCDN walkthrough completed; all five PCDNs accepted as recommended. SOS-09-F adopts the **structural-translation regime** (chart-driven membrane-vector emission with UUID-rooted traceability, cocotb + Python CPU stub harness, pytest-native JUnit XML output).

| PCDN | Resolution |
|---|---|
| PCDN-SOS-09-F-001 | 🟢 RATIFIED — option (a) chart-UUID-derived deterministic seed (determinism across CI nodes per INV-S-MEM-F-6; rejects env-var divergence path). |
| PCDN-SOS-09-F-002 | 🟢 RATIFIED — option (a) cocotb coroutine pair for atomicity concurrent stimulus (idiomatic; avoids extra process-management layer). |
| PCDN-SOS-09-F-003 | 🟢 RATIFIED — option (a) fatal error on un-rejected protection-vector access (silent acceptance is the worst failure SOS-09 prevents per INV-S-MEM-3). |
| PCDN-SOS-09-F-004 | 🟢 RATIFIED — option (b) explicit `--regen-id` flag (UUID changes are rare; opt-in catches accidental vector-lineage breaks). |
| PCDN-SOS-09-F-005 | 🟢 RATIFIED — option (a) cocotb's native pytest-XUnit output (lowest impl cost; CI consumers already parse). |

All five resolutions accepted-as-recommended; no PCDN amended. Status flipped to 🟢 RATIFIED 2026-05-26.

### 2026-05-26 — Initial draft (Claude / Ira)

- Authored `SOS-09-F-CONCEPTS.md` as the membrane-vectors sub-phase under the SOS-09 umbrella.
- §3 canonical glossary: terms `membrane vector` (adapt from SOS-03), `vector family` (the six-family enum), `vector adapter`, `chart traceability key`, `co-simulation harness`, `Python CPU stub`, `JUnit XML report`, `chart vocabulary` (mirror INV-SOS-H), `access-violation event` (mirror SOS-09-E `INV-S-MEM-E-5`).
- §4 source-of-truth map: per-concept authority with explicit AuthorityRelationship tagging.
- §5 frozen decisions:
  - §5.1 vector family enumeration (`{initial_value, write_then_read, side_effect, clear_on_read, atomicity, protection}`) — Standards Action.
  - §5.2 vector adapter shape (`MembraneVector` four-method protocol) — Standards Action.
  - §5.3 traceability key format (`MV-<UUID>-<family>-<seq>`) — Standards Action.
  - §5.4 co-simulation harness (cocotb with Python CPU stub per umbrella PCDN-SOS-09-005) — Specification Required for harness extensions; Standards Action for stub primitive set.
  - §5.5 vector report format (JUnit XML, pytest-native per PCDN-SOS-09-F-005) — Specification Required.
  - §5.6 failure-rendering vocabulary (chart `sos:name` + UUID mandatory) — Standards Action.
  - §5.7 atomicity vector (cocotb coroutine pair per PCDN-SOS-09-F-002) — Standards Action.
- §6 cross-sub-phase invariants INV-S-MEM-F-1 through 6: family coverage; chart-vocabulary failures; UUID-rooted traceability; JUnit report; protection-event observation; harness determinism.
- §7 enumeration policies recap table.
- §8 standards integration matrix additions: cocotb (`derive`), pytest collector (`derive`), JUnit XML (`derive`), SOS-03 (`adapt`), SOS-08-D (`compose`), SOS-09-A (`mirror`), SOS-09-B (`mirror`), SOS-09-E (`mirror`), SOS-09-G (`compose`), RFC 4122 UUID (`mirror`).
- §10 reconciliation vs SOS-03, SOS-08-D, SOS-09-A/B/E/G; vs existing fixtures (none found); vs PCDN-SOS-09-001 amendment.
- §11 non-goals: no HIL framework at v1; no ISS at v1; no timing-closure verification; no re-derivation of SOS-03 / SOS-08-D; no SOS-09-A/B/C/D/E/G emit paths; no XML namespace registration.
- §12 acceptance checklist gates (a)–(i) with reduced conformance level for charts without `mutex-required` channels.
- §15 five PCDNs raised covering seed source, atomicity concurrent-stimulus model, protection-rejection severity, UUID regeneration policy, and JUnit schema variant.

Status: 🟢 **RATIFIED 2026-05-26**.
