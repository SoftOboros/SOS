# SOS-09-E — HDL register-file RTL emission

**Status:** 🟡 **DRAFT 2026-05-26 — awaiting PCDN walkthrough**

## 0. Authority policy

This phase doc is the **HDL register-file RTL emission** sub-phase under the SOS-09 umbrella (`SOS-09-CONCEPTS.md`, ratified 2026-05-23, amended 2026-05-25 for PCDN-SOS-09-001). The umbrella's §5.2 freezes the channel → membrane-primitive mapping (status → `sos_strobe_latch`; command → bare req/ack + optional `sos_synchronizer`; queue → `sos_dpram_arb` + `sos_message_channel`; shared → `sos_dpram_arb` + `sos_mutex`), and the umbrella's §6 names this sub-phase as the codegen path producing synthesizable VHDL-2008 + SystemVerilog-2017 register-file RTL composed of SOS-08-A primitives behind a new top-level template module `sos_regfile`. SOS-09-E takes the umbrella's frozen decisions as load-bearing input and produces the per-emission contract for the silicon-side artifact.

Per the parent CLAUDE.md "Spec-Before-Code Planning Discipline / Phase document shape":

- **Normative** sections of this doc: §3 glossary, §4 source-of-truth map, §5 frozen decisions, §6 cross-sub-phase invariants (INV-S-MEM-E-*), §7 enumeration policy catalog, §8 standards integration matrix additions, §12 acceptance checklist.
- **Informative** sections: §1 purpose, §2 problem statement, §10 reconciliation, §11 non-goals, §15 PCDNs (filed open), §16 change log.
- All keywords MUST, MUST NOT, SHALL, SHOULD, SHOULD NOT, MAY, RECOMMENDED are interpreted per RFC 2119 / RFC 8174 when capitalised.

External-standard authority deferral:

- **VHDL-2008** — `IEEE Std 1076-2008` is the upstream language grammar; SOS-09-E emits conformant VHDL-2008 (relationship: `derive` per §8). No local VHDL dialect is introduced.
- **SystemVerilog-2017** — `IEEE Std 1800-2017` is the upstream language grammar; SOS-09-E emits the synthesizable subset (relationship: `derive` per §8). No local SV dialect is introduced.
- **AXI4-Lite / APB** — `ARM AMBA AXI4-Lite Specification` and `ARM AMBA 3 APB Protocol Specification` are the upstream bus grammars; SOS-09-E emits conformant slave interfaces against either (relationship: `derive` per §8). No custom bus protocol is introduced.

This doc cites `SOS-07-CONCEPTS.md` §6 for the cross-phase invariants `INV-SOS-A` through `INV-SOS-H` and §7 for the AuthorityRelationship matrix; it does not re-derive them. It cites `SOS-08-CONCEPTS.md` §6 for the L0 primitive library and §7 for the SOS-08 cross-sub-phase invariants (`INV-S-HDL-1` through `INV-S-HDL-5`); it does not re-derive those. It cites `SOS-09-CONCEPTS.md` §5 for the frozen channel enum and membrane-primitive mapping and §7 for the cross-sub-phase invariants `INV-S-MEM-1` through `INV-S-MEM-6`. It cites `SOS-09-A-CONCEPTS.md` for the chart-annotation attribute set (consumed) and `SOS-09-B-CONCEPTS.md` for the address-offset assignment that SOS-09-E mirrors at the bus-decode layer.

Per PCDN-SOS-09-001 amended 2026-05-25, chart channel annotations are read from iState's `other_attributes` extension surface using `sos:`-prefixed string keys WITHIN the `other_attributes` JSON. This is a JSON-key string prefix, NOT an XML namespace prefix. SOS-09-E's emit path MUST honour this convention when reading the chart; no `xmlns:sos` declaration appears in chart-author-facing XML, in the emitted VHDL/SV source, or in normative XML examples within this doc.

## 1. Purpose

To freeze the HDL register-file RTL emission contract: which bus interface enumeration is emitted; which SOS-08-A primitives compose into each channel-category realisation and how their ports wire up to the bus interface; how write-masks are synthesized from per-field declarations; how `clear-on-read` semantics gate on zone-decoded enable strobes; how access-violation events aggregate into the SW-side status channel; which language emission shapes (VHDL-2008 + SystemVerilog-2017) are co-emitted and pass identical membrane vectors; and which synthesis tools constitute the v1 target set.

Without this freeze, the HDL emit path cannot produce a stable artifact: every emission would re-litigate which bus the regfile wraps, how the per-channel primitives wire to that bus, and whether reserved bits or unauthorised zones produce silent corruption vs explicit events. Downstream consumers (SOS-09-F membrane vectors, SOS-09-G MPU configuration's SW-side fence, the consuming SoC team's bus-decode framework) cannot integrate against an underspecified register file.

## 2. Problem statement

The umbrella's §2 names the "register-map PDF that lies" as the canonical hardware/software co-design failure mode. SOS-09-E sits at the silicon side of that membrane — the place where the chart's channel annotations finally become gates. Five concrete pressures motivate the freeze in this sub-phase:

1. **Register-decode arithmetic errors.** A `<peripheral>` at base 0x4000_0000 with a `<register>` at offset 0x14 must decode at `addr == 0x4000_0014` and only there. Hand-rolled bus decoders routinely miscompute the comparator width, the address-strobe mask, or the alignment-check shift. The chart-as-source promise of SOS-09 (per INV-S-MEM-1) requires the decode arithmetic to be a pure function of the SOS-09-B address-offset assignment — never a per-implementer re-derivation.

2. **Missing write-mask on reserved bits.** A 32-bit register with 13 declared field bits and 19 reserved bits is routinely synthesized as a flat 32-bit flop bank. A write of `0xFFFF_FFFF` lands `1`s in all 19 reserved positions; a subsequent read returns `0xFFFF_FFFF`; a firmware engineer concludes the reserved bits are RW. Six months later silicon erratum E1 documents that bits [22:13] should have read 0. The write-mask must be synthesized from the field-level `RW`/`RO`/`WO`/`reserved` declarations, deterministically, never relying on author discipline.

3. **Missing read-clear gating.** A `clear-on-read` status register (e.g. an IRQ pending bit cleared by the firmware's `read` of the status word) must clear ONLY on a bus access that satisfies the zone decode AND the chart-declared `<readAction>` AND the register's per-channel valid strobe. Spurious reads from a debugger probing the wrong zone, or from a speculative bus master scanning the address space, MUST NOT clear the IRQ. Hand-rolled implementations routinely gate read-clear on `valid && read` alone, dropping IRQs whose pending bit clears under any read transaction.

4. **Zone violations that go undetected at synthesis time.** A chart declares `sos:zone="privileged"` on a channel; SOS-09-G emits the SW-side MPU fence; the HW-side regfile decode logic must independently reject an unprivileged bus transaction. If the HW decode treats `zone` as advisory (only the MPU enforces), a bus master that bypasses the MPU (DMA engine, secondary CPU, JTAG bus master) silently penetrates the register. INV-S-MEM-3 (protection is end-to-end) is violated. The HW side must enforce zone-match as a precondition for any register-decode line firing, AND emit a synth-time access-violation strobe when the precondition fails.

5. **Address-decode drift between SVD and RTL.** SOS-09-B emits the CMSIS-SVD with chart-declared offsets; SOS-09-E emits the RTL with bus-decoded offsets. If the two emit paths re-derive the offsets independently (different sort order, different alignment rule, different padding heuristic), the SVD and the RTL silently disagree. The driver and the silicon then disagree by exactly one register offset, and the next-shift team chases the bug for a week before noticing.

SOS-09-E prescribes one cure: a single `sos_regfile` template module, parameterised over bus type, that consumes the same chart-declared offset assignment SOS-09-B emits, synthesizes write-masks deterministically from field declarations, gates every side-effect on the (valid AND zone AND access-type) triple, and surfaces access violations as first-class chart events. Per INV-S-HDL-1, every bus interface emitted is handshake-compatible. Per INV-S-MEM-3, every protection-zone declaration on a channel is enforced on this side AND on the SOS-09-G side; the codegen rejects the chart if asked to emit one without the other.

## 3. Canonical glossary

Terms normative within SOS-09-E+. Authority relationships per §8. Terms also defined in the SOS-09 umbrella (`channel`, `kind`, `dir`, `status channel`, `command channel`, `queue channel`, `shared channel`, `protection zone`, `atomicity class`, `side-effect-on-write`, `clear-on-read`, `membrane vector`) are cited from `SOS-09-CONCEPTS.md` §3 and used without modification.

| Term | Definition |
|---|---|
| **`sos_regfile` template module** | The top-level HDL module emitted by SOS-09-E for each chart channel-group. One `sos_regfile` instance per peripheral (per SOS-09-B §5.2 grouping policy). Owned by this doc (§5.7); does not exist in the SOS-08-A primitive library. Parameterised over the bus-interface enumeration (per §5.1); instantiates per-channel realisation submodules (per §5.2). Emitted in both VHDL-2008 and SystemVerilog-2017 from the same chart input (per §5.6). |
| **register-decode line** | The combinational expression `(bus.valid && bus.addr == REG_OFFSET_n && zone_match_n && access_type_match_n)` that fires the per-register access strobe. One decode line per chart-declared register. Owned by this doc (§5.2); composed downstream into the per-channel primitive's `req`/`valid` input. |
| **write-mask** | A per-bit boolean array of width equal to the register width, derived from the chart-declared field-level access annotations (`RW`/`RO`/`WO`/`reserved`). For each bit: `1` if the bus may write that bit; `0` if the bit is read-only or reserved-write-discarded. Owned by this doc (§5.3); synthesized into the per-register flop bank's write-enable network. |
| **reserved-bit handling** | The policy governing bits declared `reserved` in the chart's field list: bus reads return `0` on reserved bit positions; bus writes to reserved bits are discarded (the write-mask bit is `0`). Owned by this doc (§5.3); aligns with default ARMv7-M discipline cited at SOS-09 umbrella §5.5 / PCDN-SOS-09-003. |
| **access-violation event** | A single-cycle strobe asserted by a register-decode line when `bus.valid && bus.addr == REG_OFFSET_n` matches AND `zone_match_n` is false (zone mismatch) OR `access_type_match_n` is false (e.g. write to a read-only register). Each strobe routes into a per-channel-group `sos_strobe_latch` (per §5.5) that surfaces as a chart-declared status channel back to the SW side. Owned by this doc (§5.5). |
| **zone-decode AND-gate** | The combinational gate `zone_match_n = (bus.zone_signal == CHART_DECLARED_ZONE_n)` that must be true for the register-decode line to fire on any side-effect-bearing access. Owned by this doc (§5.2); composed into every register-decode line per INV-S-MEM-E-3 / -E-4. The `bus.zone_signal` is provided by the bus master (AXI4-Lite's `AxPROT[0]` privilege bit; APB's `PPROT[0]` privilege bit) per the bus standard. |
| **bit-identical RTL emission** | The property that the VHDL-2008 and SystemVerilog-2017 emissions of the same chart input simulate identically — same input vector sequence, same output vector sequence, same per-cycle state. Verified by SOS-09-F membrane vectors run against both emissions and the SOS-08-E shared-RHS hardening (per `SOS-08-E-CONCEPTS.md`). Owned by this doc (§5.6); the bit-identity claim composes through SOS-08-E's wave-3 conformance entry. |
| **per-channel realisation submodule** | A per-channel HDL module instantiated inside `sos_regfile`, one per chart channel, parameterised over the channel's width/depth/atomicity. The submodule type is determined by `sos:kind` per the §5.2 table. Submodules are pure compositions of SOS-08-A primitives (`sos_strobe_latch`, `sos_dpram_arb`, `sos_mutex`, `sos_synchronizer`, `sos_message_channel`); no new primitive logic is introduced. Owned by this doc (§5.2). |

## 4. Source-of-truth map

For every concept this sub-phase touches, **exactly one** location is the canonical authority.

| Concept | Authority |
|---|---|
| Bus interface enumeration (`axi4lite` / `apb`) | **this doc** (§5.1) |
| `sos_regfile` template module shape | **this doc** (§5.7) |
| Per-channel realisation table (chart kind → submodule + primitive wiring) | **this doc** (§5.2); the upstream channel → membrane-primitive mapping is `SOS-09-CONCEPTS.md` §5.2 (**mirror**) |
| Register-decode line generation | **this doc** (§5.2) |
| Write-mask generation policy | **this doc** (§5.3) |
| Reserved-bit handling policy | **this doc** (§5.3) |
| Read-clear gating policy | **this doc** (§5.4) |
| Access-violation event aggregation | **this doc** (§5.5) |
| Language emission shape (VHDL-2008 + SV-2017) | **this doc** (§5.6) |
| Synthesis-tool target set | **this doc** (§5.6); each tool's behaviour is upstream (**derive**) |
| AXI4-Lite slave interface grammar | ARM AMBA AXI4-Lite Specification (external); locally **derive** per §8 |
| APB slave interface grammar | ARM AMBA 3 APB Protocol Specification (external); locally **derive** per §8 |
| VHDL-2008 language grammar | IEEE Std 1076-2008 (external); locally **derive** per §8 |
| SystemVerilog-2017 language grammar | IEEE Std 1800-2017 (external); locally **derive** per §8 |
| L0 primitive contracts (`sos_strobe_latch`, `sos_dpram_arb`, `sos_mutex`, `sos_synchronizer`, `sos_message_channel`) | `SOS-08-A-CONCEPTS.md` §6 (cited, **mirror**); `sos_message_channel` per `SOS-08-B-CONCEPTS.md` |
| Address-offset assignment (per-register offsets within a peripheral) | `SOS-09-B-CONCEPTS.md` §5.3 (cited, **mirror**); SOS-09-E uses byte-identical offsets to the SVD per INV-S-MEM-E-6 |
| Chart channel annotation source (`other_attributes` with `sos:`-prefixed keys) | `SOS-09-A-CONCEPTS.md` §5 (cited, **mirror**) |
| Channel category enum (`kind ∈ {status, command, queue, shared}`) | `SOS-09-CONCEPTS.md` §5.1 (cited, **mirror**) |
| Channel → membrane-primitive mapping (the four rows) | `SOS-09-CONCEPTS.md` §5.2 (cited, **mirror**) |
| Protection-zone enum (`{privileged, unprivileged}` at v1) | `SOS-09-CONCEPTS.md` §5.4 (cited, **mirror**); the v1 enum derives the bus-master privilege signal mapping |
| Clock-domain declaration (`<sos:clock_domains>`) | `SOS-08-D-CONCEPTS.md` (cited, **mirror**); SOS-09-E inserts `sos_synchronizer` when the bus and channel are in distinct domains, per `<sos:clock_domains>` declaration |
| Cross-sub-phase invariants `INV-S-MEM-1` through `INV-S-MEM-6` | `SOS-09-CONCEPTS.md` §7 (cited, not redefined) |
| Cross-phase invariants `INV-SOS-A` through `INV-SOS-H` | `SOS-07-CONCEPTS.md` §6 (cited, not redefined) |
| SOS-08 cross-sub-phase invariants `INV-S-HDL-1` through `INV-S-HDL-5` | `SOS-08-CONCEPTS.md` §7 (cited, not redefined) |
| Emitted RTL artifact | `build/rtl/<chart_id>/sos_regfile_<peripheral>.{vhd,sv}` (forthcoming; per INV-S-MEM-2 lives under `build/`, not tracked source) |

## 5. Frozen decisions

### 5.1 Bus interface enumeration

The v1 bus interface enumeration is:

```
bus ∈ { axi4lite, apb }
```

- **`axi4lite`** — AMBA AXI4-Lite slave interface. The v1 **default**. Five-channel handshake (AW, W, B, AR, R) per the AMBA AXI4-Lite specification. Address width 32; data width 32 (subject to PCDN-SOS-09-E-001 chart-author override hook).
- **`apb`** — AMBA 3 APB slave interface. Two-phase access (setup + access) per the AMBA 3 APB specification. Address width 32; data width 32.

Both implementations satisfy the SOS-08-A handshake-compatibility invariant `INV-S-HDL-1` (every interface is handshake-compatible). The choice between `axi4lite` and `apb` is per-`sos_regfile` instance, declared in the chart via the channel-group's `sos:bus` annotation (subject to PCDN-SOS-09-E-005 on whether one parameterised template or two distinct templates emit). The bus master's privilege signal (`AxPROT[0]` for AXI4-Lite; `PPROT[0]` for APB) is the source of the `bus.zone_signal` consumed by zone-decode AND-gates per §5.2.

Adding a third bus (AXI4-Full, AXI-Stream, custom proprietary bus) requires a §16 amendment to this section.

Frozen-enumeration registration policy: **Standards Action** (the bus enumeration encodes the SoC-level integration contract; widening it pulls in additional protocol-conformance obligations across SOS-09-F membrane vectors).

### 5.2 Per-channel realisation table

This section restates the SOS-09 umbrella §5.2 channel → membrane-primitive mapping AND adds the HDL-specific structural constraints (port set, signal wiring from the bus interface to the per-channel primitive).

| Chart annotation (`kind` / `dir`) | Per-channel realisation submodule | Composed SOS-08-A primitive(s) | Bus → primitive wiring |
|---|---|---|---|
| `status` / `hw→sw` | `sos_regfile_status_<n>` | `sos_strobe_latch` | HW asserts a `strobe_in` into `sos_strobe_latch.strobe_in`; the latch's `level_out` drives a read-only register flop. Bus read on the register's decode line returns `level_out`. If chart declares `clear-on-read`, the decode-line's `read_enable` AND zone-match AND `bus.valid` strobe feeds `sos_strobe_latch.ack_in`. |
| `command` / `sw→hw` | `sos_regfile_command_<n>` | bare req/ack flop bank + optional `sos_synchronizer` on `req` if cross-domain | Bus write on the decode line latches the data into a holding register; the holding register's value is presented to HW as `command_value`; the per-command `fire` strobe is registered (cadence per PCDN-SOS-09-E-006) to gate the HW side's `req` handshake. If `<sos:clock_domains>` declares the channel on a different domain than the bus, `sos_synchronizer` is inserted on `req` (depth per SOS-08-A §6.9). |
| `queue` / `hw↔sw` | `sos_regfile_queue_<n>` | `sos_dpram_arb` (single- or dual-clock per chart) + `sos_message_channel` (per SOS-08-B) | Bus writes into the queue's tail register decode to `sos_dpram_arb.port_b.write_addr / write_data` via the `sos_message_channel` push path; bus reads of the head register decode to the `sos_message_channel` pop path. A non-empty status bit surfaces back through a status decode line; an IRQ on non-empty composes a `sos_strobe_latch` per the §5.5 access-violation aggregation pattern. |
| `shared` / `hw↔sw` | `sos_regfile_shared_<n>` | `sos_dpram_arb` + `sos_mutex` | Bus accesses to the shared region first decode through the mutex: a claim register decode line drives `sos_mutex.req`; the mutex's `grant` qualifies subsequent reads/writes to the `sos_dpram_arb.port_b` address range. The mutex ID is the chart-declared `sos:mutex` annotation (per `SOS-09-A-CONCEPTS.md`). |

Every register-decode line is the combinational expression `bus.valid && (bus.addr & ADDR_MASK_n) == REG_OFFSET_n && zone_match_n && access_type_match_n`, where:

- `REG_OFFSET_n` is the byte offset emitted by SOS-09-B for the same register (per INV-S-MEM-E-6, byte-for-byte identical).
- `zone_match_n = (bus_privilege_signal == CHART_DECLARED_ZONE_n)`. For AXI4-Lite: `bus_privilege_signal = AxPROT[0]` (`0` = privileged, `1` = unprivileged) inverted to align with the chart's `sos:zone` value (`privileged` / `unprivileged`).
- `access_type_match_n` is true on a write decode if and only if the register is RW or WO; true on a read decode if and only if the register is RW or RO.

When any decode line's `valid && (addr & mask) == offset` fires but `zone_match` is false or `access_type_match` is false, an `access_violation_event` strobe is asserted (per §5.5).

The mapping is exhaustive: a chart channel annotation that does not fit one of the four rows is a chart authoring error caught upstream at SOS-01 lint (per SOS-09 umbrella §5.2). The submodule type and primitive wiring is frozen.

Frozen-enumeration registration policy: **Standards Action** (rewiring rows requires umbrella amendment AND a SOS-09-E §16 amendment; adding a new row is gated by the umbrella's Standards Action policy on the channel-category enumeration).

### 5.3 Write-mask policy

Every writable register has an explicit write-mask synthesized from the field-level `RW`/`RO`/`WO`/`reserved` declarations carried in the chart's `sos:bit_layout` (per `SOS-09-A-CONCEPTS.md` §5.2). For each bit position `b` in a register of width `W`:

- `write_mask[b] = 1` if the field containing bit `b` is declared `RW` or `WO`.
- `write_mask[b] = 0` if the field containing bit `b` is declared `RO` or `reserved`, or if bit `b` lies in a gap not covered by any declared field.

The per-bit write-enable network for the register's flop bank is `write_enable[b] = decode_write_strobe && write_mask[b]`. Writes to bits where `write_mask[b] == 0` are discarded — the flop's `D` input is gated to its current `Q`, preserving the prior value. Reads of reserved bits return `0` (the bit's `Q` is logically ANDed with a `read_mask[b]` of `0` on reserved positions; the `read_mask` is the dual of `write_mask` for the RO/reserved axis: `read_mask[b] = 1` if the field is `RW` or `RO`; `read_mask[b] = 0` if `WO` or `reserved`).

Read-as-zero / write-as-zero on reserved bits matches the default ARMv7-M discipline cited at the SOS-09 umbrella §5.5 / PCDN-SOS-09-003 ratification.

Frozen-enumeration registration policy: **Standards Action** (the write-mask policy encodes the cross-phase contract between the chart's field declarations and the silicon's bit-level behaviour; relaxing it would silently invert the reserved-bit semantics).

### 5.4 Read-clear gating

For registers with chart-declared `<readAction>` semantics (per SOS-09-B §5.3 mapping table; e.g. `sos:clear_on_read="true"` annotation), the read-clear strobe is gated by the conjunction:

```
clear_strobe_n = bus.valid
             AND (bus.addr & ADDR_MASK_n) == REG_OFFSET_n
             AND zone_match_n
             AND read_enable_n
```

— that is, the clear fires only when the bus access is valid AND addresses the specific register AND the chart-declared zone matches AND the access is a read. Spurious reads from non-matching zones do NOT clear the register (the zone-decode AND-gate gates the clear strobe along with the rest of the decode line, per §5.2). A bus master that bypasses the MPU (e.g. a DMA engine without secondary access controls) still does not clear an IRQ pending bit unless its `bus_privilege_signal` matches the chart-declared zone — INV-S-MEM-E-3 below.

For `clear-on-read` semantics composed on top of a `sos_strobe_latch` (the canonical `status` channel realisation per §5.2), the `clear_strobe_n` drives the latch's `ack_in` port — the SOS-08-A pulse-to-level + ack contract handles the clearing per `SOS-08-A-CONCEPTS.md` §6.10.

Frozen-enumeration registration policy: **Standards Action** (read-clear is the dominant IRQ-handling pattern; gating it on zone is the load-bearing security-side decision).

### 5.5 Access-violation event

Every register-decode line emits a single-cycle `access_violation_event_n` strobe when:

- `bus.valid && (bus.addr & ADDR_MASK_n) == REG_OFFSET_n` is true (the bus is addressing this register), AND
- Either `zone_match_n` is false (the bus master's privilege does not match the chart-declared zone), OR `access_type_match_n` is false (the bus is trying to write a read-only register, or read a write-only register).

All `access_violation_event_n` strobes within a single chart channel-group (one `sos_regfile` instance) are ORed together and fed into one `sos_strobe_latch` (per `SOS-08-A-CONCEPTS.md` §6.10). The latch's `level_out` surfaces as a chart-declared status channel back to the SW side — typically as a `kind="status"` / `dir="hw→sw"` channel with a chart-declared name like `<peripheral>_access_violation`. This is per PCDN-SOS-09-E-003 (default: one strobe-latch per chart channel-group, matching MPU region granularity per SOS-09-G §5.2).

The chart-declared access-violation channel is itself realised through SOS-09-E's `status` row (per §5.2) — the access-violation strobes are HW events surfacing as SW-readable status, and SOS-09-G's protection-vector acceptance gate (per `SOS-09-G-CONCEPTS.md` §9 (b)) consumes this channel as its end-to-end protection-failure observation point. INV-S-MEM-3 (protection is end-to-end) requires both sides to fence; the access-violation channel is the HW-side telemetry that proves the fence fired.

Frozen-enumeration registration policy: **Standards Action** (the access-violation event surface is the load-bearing security-telemetry channel; aggregation rules and channel-group binding are cross-phase contracts).

### 5.6 Language emission shape

SOS-09-E emits **both** VHDL-2008 and SystemVerilog-2017 from the same chart input. Both emissions:

- Pass identical membrane vectors (per SOS-09-F).
- Simulate to bit-identical waveforms on the same input vector sequence (per SOS-08-E shared-RHS hardening, cited at the wave-3 conformance entry — `SOS-08-WAVE3-CONFORMANCE.md`).
- Synthesize on the v1 synthesis-tool target set:
  - **Xilinx Vivado** — version 2024.1 or later. SystemVerilog-2017 synthesizable subset + VHDL-2008.
  - **Intel Quartus Pro** — version 23.x or later. Both languages.
  - **Yosys** — version 0.37 or later, open-source. SystemVerilog-2017 synthesizable subset (Yosys's VHDL frontend `ghdl-yosys-plugin` is required for VHDL emission consumption; the VHDL emission's portability to Yosys is verified through the plugin).

Adding a fourth synthesis target (Lattice Diamond, Microchip Libero, Cadence Genus, Synopsys DC) is a phase-owner walkthrough update (Specification Required policy below); each new target requires a re-verification of the synthesizable subset claim.

Per INV-S-HDL-2 (from SOS-08 §7), bit-identical RTL emission across language backends is a load-bearing claim for the SOS-08-D/E vector parity; SOS-09-E inherits this property via the SOS-08-E shared-RHS hardening pattern.

Frozen-enumeration registration policy: **Specification Required** (adding a fourth synthesis target is a phase-owner walkthrough update; widening past `VHDL-2008 + SystemVerilog-2017` to a third language is Standards Action under the SOS-08 HDL umbrella).

### 5.7 `sos_regfile` template module

A single top-level module is emitted **per chart channel-group** (per SOS-09-B §5.2 grouping policy — one `sos_regfile` instance per `<peripheral>`). The template is **generic/parameter-driven** for the bus type (per PCDN-SOS-09-E-005 default: single template, bus-type parameter; the parameter selects between AXI4-Lite and APB port sets at elaboration time).

The module's port set decomposes into:

1. **Clock + reset** — `clk`, `rst` (synchronous active-high reset per `SOS-08-A-CONCEPTS.md` INV-S-HDL-A-1).
2. **Bus slave port** — AXI4-Lite or APB slave interface ports, named per the AMBA standard (e.g. `s_axi_awvalid`, `s_axi_wdata`, ...; or `psel`, `pwrite`, `paddr`, `pwdata`, `prdata`, `pready`).
3. **Per-channel I/O** — one set of HW-side ports per chart channel (e.g. for a `status` channel, a `strobe_in` and the data-bus carrying the status word; for a `command` channel, the latched `command_value` and the `fire` strobe; for a `queue` channel, the `sos_message_channel` HW-side push/pop ports; for a `shared` channel, the `sos_dpram_arb.port_a` ports).
4. **Access-violation aggregate output** — a single `level_out` signal surfacing the OR-aggregated `sos_strobe_latch` for the channel group's access violations (per §5.5).

The module instantiates one per-channel realisation submodule per chart channel (per §5.2), wires the bus slave port through the register-decode logic into each submodule's bus-side input, and aggregates the access-violation strobes into the single channel-group strobe latch.

A new template module `sos_regfile` is introduced by this sub-phase. It is a **composition template**, NOT a new L0 primitive — it lives in the SOS-09-E sub-phase output (under `tools/sos-codegen/templates/sos_regfile.{vhd,sv}.j2` or equivalent), NOT in `SOS-08-A`'s primitive catalogue.

Frozen-enumeration registration policy: **Specification Required** (the template's port-set decomposition and instantiation pattern is phase-local; restructuring it is a phase-owner walkthrough update).

## 6. Cross-sub-phase invariants — INV-S-MEM-E-1 through INV-S-MEM-E-6

In addition to the cross-phase invariants `INV-SOS-A` through `INV-SOS-H` (from SOS-07), the SOS-08 cross-sub-phase invariants `INV-S-HDL-1` through `INV-S-HDL-5` (from SOS-08), and the SOS-09 cross-sub-phase invariants `INV-S-MEM-1` through `INV-S-MEM-6` (from SOS-09 §7), the following invariants are normative within SOS-09-E:

- **INV-S-MEM-E-1 — Every chart-declared register maps to exactly one decode line.** No register has two register-decode lines. Duplicate-address detection happens at codegen time (a chart that produces two registers at the same byte offset is rejected by the SOS-09-E emit step), NOT at synthesis time (where a duplicate address might produce silent priority-encoded behaviour or X-propagation). Verified by the §12 acceptance gate (a) duplicate-address detection scan.

- **INV-S-MEM-E-2 — Every writable register has a write-mask; writes to reserved bits are dropped, not propagated.** The write-mask is synthesized from the chart's field-level `RW`/`RO`/`WO`/`reserved` declarations per §5.3. Reserved-bit writes MUST be discarded at the flop level (the `D` input of the flop is gated to `Q`), not absorbed into the bit position and surfaced on later reads. Verified by the §12 acceptance gate (b) write-mask coverage vector.

- **INV-S-MEM-E-3 — `clear-on-read` registers are NEVER cleared by accesses from non-matching zones.** The read-clear strobe is gated on the zone-decode AND-gate per §5.4. A bus master with `bus_privilege_signal` not matching the chart-declared `sos:zone` cannot clear the register — the access generates an `access_violation_event` strobe (per §5.5) and the clear strobe stays low. Verified by the §12 acceptance gate (d) and by the SOS-09-F protection-vector cocotb test.

- **INV-S-MEM-E-4 — Access-violation events are deterministic.** Given the same bus transaction sequence applied to the same `sos_regfile` instance with the same zone signal, the per-cycle sequence of `access_violation_event_n` strobes is identical across runs. No timing variation, no metastability propagation into the violation event (the violation event is a combinational function of the decoded address, zone signal, and access type — all synchronous to the bus clock). Per INV-S-HDL-3 (from SOS-08 §7), any `sos_synchronizer` flops inserted for cross-domain channels are excluded from this determinism claim — their MTBF handles the cross-domain path; the access-violation strobe is gated on the bus-domain signals, which are deterministic.

- **INV-S-MEM-E-5 — Emitted VHDL and SystemVerilog are bit-identical at simulation.** The two language emissions of the same chart input produce identical input/output vector sequences and per-cycle state. Verified per the SOS-08-E shared-RHS hardening at the wave-3 conformance entry (`SOS-08-WAVE3-CONFORMANCE.md`); SOS-09-E's emit path inherits the conformance gate.

- **INV-S-MEM-E-6 — Register addresses in emitted RTL match SVD `<offset>` values byte-for-byte.** SOS-09-E consumes the SOS-09-B address-offset assignment as input (per the §4 source-of-truth row); the bus-decode logic compares against byte-identical `REG_OFFSET_n` constants. A drift between the SVD and the RTL is a build-stop, not a runtime drift — the SOS-09-E emitter verifies the offsets against the SOS-09-B emission at build time and refuses to emit if they differ. Verified by the §12 acceptance gate (h) SVD-offset match scan.

Frozen-enumeration registration policy: **Standards Action**.

## 7. Enumeration policy catalog

This section catalogues the §5 frozen-enumeration registration policies in a single table for review convenience. Each row mirrors the policy declaration inside the corresponding §5.x section; this section is the index, not the canonical declaration.

| § | Frozen enumeration | Registration policy |
|---|---|---|
| 5.1 | Bus interface enumeration (`axi4lite` / `apb`) | **Standards Action** |
| 5.2 | Per-channel realisation table (the four rows + structural wiring) | **Standards Action** |
| 5.3 | Write-mask policy (synthesized from `RW`/`RO`/`WO`/`reserved`) | **Standards Action** |
| 5.4 | Read-clear gating policy (zone-decode AND `read_enable`) | **Standards Action** |
| 5.5 | Access-violation event aggregation (one strobe-latch per channel-group) | **Standards Action** |
| 5.6 | Language emission shape (VHDL-2008 + SV-2017; synthesis-tool target set) | **Specification Required** |
| 5.7 | `sos_regfile` template module shape (single template, bus-type parameter) | **Specification Required** |
| 6   | Cross-sub-phase invariants `INV-S-MEM-E-1` through `INV-S-MEM-E-6` | **Standards Action** |

## 8. Standards integration matrix additions

The following rows EXTEND the SOS-07 §7 and SOS-09 §8 matrices:

| Concept | Upstream authority | Local relationship | Phase that declares it | Mutation rights |
|---|---|---|---|---|
| AMBA AXI4-Lite slave protocol | ARM (AMBA) | **derive** — SOS-09-E emits a conformant AXI4-Lite slave interface | this doc | none — protocol is upstream |
| AMBA 3 APB slave protocol | ARM (AMBA) | **derive** — SOS-09-E emits a conformant APB slave interface | this doc | none — protocol is upstream |
| IEEE Std 1076-2008 (VHDL-2008) | IEEE | **derive** — SOS-09-E emits VHDL-2008 from the synthesizable subset | this doc | none — language is upstream |
| IEEE Std 1800-2017 (SystemVerilog-2017) | IEEE | **derive** — SOS-09-E emits the SV-2017 synthesizable subset | this doc | none — language is upstream |
| Xilinx Vivado synthesis tool | Xilinx (commercial) | **derive** — SOS-09-E emission passes Vivado 2024.1+ synthesis | this doc | none — tool is upstream |
| Intel Quartus Pro synthesis tool | Intel (commercial) | **derive** — SOS-09-E emission passes Quartus Pro 23.x+ | this doc | none — tool is upstream |
| Yosys synthesis tool | open-source (YosysHQ) | **derive** — SOS-09-E SV emission passes Yosys 0.37+; VHDL via `ghdl-yosys-plugin` | this doc | none — tool is upstream |
| SOS-08-A `sos_strobe_latch` | this repo, SOS-08-A | **mirror** — composed without modification; one per `status` channel + one per channel-group access-violation aggregate | this doc | none — SOS-08-A owns the primitive |
| SOS-08-A `sos_dpram_arb` | this repo, SOS-08-A | **mirror** — composed without modification; one per `queue` and per `shared` channel | this doc | none — SOS-08-A owns the primitive |
| SOS-08-A `sos_mutex` | this repo, SOS-08-A | **mirror** — composed without modification; one per `shared` channel | this doc | none — SOS-08-A owns the primitive |
| SOS-08-A `sos_synchronizer` | this repo, SOS-08-A | **mirror** — composed when `<sos:clock_domains>` declares the bus and channel in distinct domains | this doc | none — SOS-08-A owns the primitive |
| SOS-08-B `sos_message_channel` | this repo, SOS-08-B | **mirror** — composed without modification; one per `queue` channel wrapping the `sos_dpram_arb` | this doc | none — SOS-08-B owns the service |
| SOS-09-A chart annotation schema | this repo, SOS-09-A | **mirror** — SOS-09-E reads `sos:`-prefixed keys per PCDN-SOS-09-001 amended 2026-05-25 | this doc | SOS-09-A owns; SOS-09-E consumes |
| SOS-09-B address-offset assignment | this repo, SOS-09-B | **compose** — SOS-09-E uses B's chart-declared offsets as input to bus-decode constants; B's offsets are byte-identical to the RTL offsets per INV-S-MEM-E-6 | this doc | none — SOS-09-B owns the offsets |
| `<sos:clock_domains>` element | this repo, SOS-08-D | **mirror** — SOS-09-E reads the declaration to decide `sos_synchronizer` insertion | this doc | none — SOS-08-D owns the element vocabulary |

Per `INV-SOS-E`, the row addition policy mirrors SOS-07 §7 / SOS-09 §8: **Specification Required** for adding new rows (phase-owner walkthrough); **Standards Action** for modifying an existing row's relationship value.

## 9. Acceptance gates

The SOS-09-E emit path's acceptance gates are:

- (a) **Duplicate-address detection.** SOS-09-E rejects a chart whose channel set produces two registers at the same byte offset. Closes INV-S-MEM-E-1.
- (b) **Write-mask coverage.** For every chart-declared field with access ∈ {`RO`, `reserved`}, an explicit cocotb test writes `0xFFFF_FFFF` to the register's offset and reads back; the test asserts the field bits return their original value (not `0xFFFF_FFFF`). Closes INV-S-MEM-E-2.
- (c) **Reserved-bit read-as-zero.** For every reserved bit gap, an explicit cocotb test reads the register and asserts the reserved bits return `0`. Closes part of INV-S-MEM-E-2.
- (d) **Zone-gated read-clear.** For every chart channel with `<readAction>` semantics, an explicit cocotb test issues a read from a non-matching zone (mismatched `AxPROT[0]` or `PPROT[0]`); asserts the register is NOT cleared AND the channel-group access-violation strobe is asserted. Closes INV-S-MEM-E-3.
- (e) **Access-violation determinism.** Same input bus transaction sequence applied twice produces identical access-violation strobe sequences. Closes INV-S-MEM-E-4.
- (f) **Language parity.** Both VHDL-2008 and SystemVerilog-2017 emissions pass the same membrane vector suite (per SOS-09-F) on the same chart input. Closes INV-S-MEM-E-5.
- (g) **Synthesis-tool coverage.** Both emissions synthesize without errors on Xilinx Vivado 2024.1+, Intel Quartus Pro 23.x+, and Yosys 0.37+ (VHDL via `ghdl-yosys-plugin`) for at least one example chart channel-group with at least one channel of each kind. Closes part of §5.6.
- (h) **SVD-offset match.** SOS-09-E's emit step verifies that every `REG_OFFSET_n` constant in the emitted RTL is byte-identical to the corresponding `<addressOffset>` value in the SOS-09-B-emitted SVD. Build-stop on mismatch. Closes INV-S-MEM-E-6.
- (i) **Bus-protocol conformance.** Both AXI4-Lite and APB emissions pass an AMBA conformance test (e.g. ARM's `axi-vip` or `apb-vip`, or an equivalent open-source AMBA checker) on a representative emission. Closes §5.1.

A conforming SOS-09-E implementation satisfies (a)–(i). A conforming implementation that emits only one bus type (AXI4-Lite default) satisfies (a)–(h) with reduced (i). A conforming implementation that emits only SystemVerilog (deferring VHDL parity to a follow-on) satisfies (a)–(e), (g) reduced, (h), and (i); (f) flips to ✅ when the VHDL emission lands.

## 10. Reconciliation decisions vs adjacent repo primitives

### vs. SOS-08-A (L0 primitive library)

SOS-09-E **composes** SOS-08-A primitives without modification. The per-channel realisation submodules of §5.2 are pure compositions: `sos_strobe_latch` for `status`; bare flop bank + optional `sos_synchronizer` for `command`; `sos_dpram_arb` + `sos_message_channel` for `queue`; `sos_dpram_arb` + `sos_mutex` for `shared`. No new L0 primitive is introduced. The new template module `sos_regfile` (per §5.7) is a *composition template* in this sub-phase's emission, not a new primitive in SOS-08-A's catalogue — it lives at `tools/sos-codegen/templates/sos_regfile.{vhd,sv}.j2`, not under `rtl/sos_<primitive>/`.

The SOS-08-A primitive's handshake-compatibility invariant (`INV-S-HDL-1` — every interface is handshake-compatible) carries through to the `sos_regfile` template: every bus interface emitted (AXI4-Lite or APB) is handshake-compatible by construction (both AMBA protocols are handshake protocols).

### vs. SOS-08-B (L1 service composition)

`sos_message_channel` (per `SOS-08-B-CONCEPTS.md`) is the realisation of `queue` channels — `sos_regfile_queue_<n>` instantiates one `sos_message_channel` per queue. No re-derivation; SOS-09-E picks the existing service.

### vs. SOS-08-C (shared-signal HDL wiring)

The `<sos:shared_signal>` and `<sos:shared_signal_ref>` element vocabulary (per `SOS-08-C-CONCEPTS.md`) is used internally to the `sos_regfile` template for wiring access-violation strobes from each decode line to the channel-group's aggregate `sos_strobe_latch` (per §5.5). The shared-signal naming convention provides the OR-aggregation seam that's stable across language emissions.

### vs. SOS-08-D (clock-domain declaration)

`<sos:clock_domains>` (per `SOS-08-D-CONCEPTS.md`) is the chart-side declaration of which logical clock domain hosts each channel and the bus. SOS-09-E reads the declaration and inserts a `sos_synchronizer` (per SOS-08-A §6.9) on the `command` channel's `req` signal when the channel's domain differs from the bus's domain. For `queue` channels using `sos_dpram_arb`'s dual-clock variant, the per-port-clock declaration drives the dual-clock instantiation. Charts that don't declare clock domains are rejected by SOS-01 lint upstream if cross-domain access is structurally implied.

### vs. SOS-08-E (VHDL walker) and SOS-08-F (SystemVerilog walker)

`tools/sos-codegen/transliterate_hdl_vhdl.py` and `transliterate_hdl_sv.py` are the existing HDL walker entry points (per the wave-3 conformance entry `SOS-08-WAVE3-CONFORMANCE.md`). SOS-09-E's emit path introduces a new template module `sos_regfile`; cited from this doc as the silicon-side entry point, NOT modified within this draft (the implementation phase modifies them). The two walkers consume the same chart input through the SOS-08-E shared-RHS hardening pattern (per wave-3 conformance) — the same right-hand-side expressions feed both walkers, ensuring INV-S-MEM-E-5 (bit-identical emission) by construction.

### vs. SOS-09-A (chart annotation surface)

SOS-09-E **consumes** SOS-09-A's annotation schema. The required keys (`sos:id`, `sos:name`, `sos:kind`, `sos:dir`) and the optional/kind-gated keys (`sos:zone`, `sos:width`, `sos:bit_layout`, `sos:irq`, `sos:mutex`) are read from `other_attributes` JSON. SOS-09-E does NOT extend the attribute set; new SOS-semantic keys are SOS-09-A's authority. SOS-09-E-specific extension hooks (per the §15 PCDNs — e.g. `sos:bus` for per-`sos_regfile` bus selection) are subject to SOS-09-A ratification when the PCDNs walk.

### vs. SOS-09-B (CMSIS-SVD emission)

SOS-09-E is the **silicon-side counterpart** of SOS-09-B. Both consume the same chart channel set per `INV-S-MEM-1` (single-source register definition). The address-offset assignment policy frozen at SOS-09-B §5.3 (PCDN-SOS-09-B-003 ratified — dense, 4-byte-aligned for 32-bit, 8-byte-aligned for 64-bit) is the same policy SOS-09-E's bus-decode logic observes when emitting the `REG_OFFSET_n` constants. INV-S-MEM-E-6 (RTL offsets match SVD `<addressOffset>` byte-for-byte) is the property that makes this symmetric AND build-time-checked.

### vs. SOS-09-G (MPU configuration emission)

SOS-09-E emits the HW-side gate (the zone-decode AND-gate per §5.2; the access-violation event per §5.5); SOS-09-G emits the SW-side fence (the MPU table that prevents the unprivileged CPU side from reaching the privileged channel's address). INV-S-MEM-3 (protection is end-to-end) requires both — the codegen rejects a chart that asks for one without the other. The two sub-phases share no code; they share the chart annotation (`sos:zone`) as the single source. The HW gate REJECTS out-of-zone bus accesses AT THE BUS INTERFACE (the decode line never fires); the SW MPU fence PREVENTS the unprivileged CPU from emitting the bus transaction in the first place; together they form the two-layer defence. The SOS-09-F protection membrane vector exercises both layers in the cocotb harness.

### vs. SOS-09-F (membrane vectors)

SOS-09-F's vector framework reads SOS-09-B's emitted SVD to enumerate the register set under test, and exercises the SOS-09-E-emitted RTL through cocotb (per PCDN-SOS-09-005 — cocotb-with-Python-CPU-stub at v1). The six vector shapes (initial-value-read, write-then-read, side-effect-on-write, clear-on-read, atomicity, protection) all run against the SOS-09-E RTL. INV-S-MEM-E-5 (bit-identical VHDL + SV) is the property that lets the same vector run against either language emission and produce the same observed waveform.

### vs. SOS-08-WAVE3-CONFORMANCE (shared-RHS hardening)

The wave-3 conformance entry (per `SOS-08-WAVE3-CONFORMANCE.md`) hardened the SOS-08-E (VHDL walker) and SOS-08-F (SystemVerilog walker) shared right-hand-side expression machinery so that the same Python expression tree feeds both language emissions. SOS-09-E inherits this shared-RHS path: every per-channel realisation submodule, every register-decode line, every write-mask expression, and every `sos_regfile` template instantiation use the wave-3 shared-RHS helpers to guarantee INV-S-MEM-E-5 by construction.

### vs. PCDN-SOS-09-001 amended 2026-05-25

The amendment that routes channel annotations through `other_attributes` (vs the originally-resolved `xmlns:sos` namespace) is a load-bearing input to SOS-09-E's read path. SOS-09-E MUST NOT emit any `xmlns:sos` declaration into the VHDL or SystemVerilog output (the emitted RTL is plain VHDL-2008 / SV-2017 source, carrying no XML at all). SOS-09-E MUST read `sos:`-prefixed keys from `other_attributes` JSON; reading from XML namespace prefixes would be reading a surface that PCDN-SOS-09-001 amended 2026-05-25 explicitly retracted.

### vs. INV-SOS-A (chart-as-source) + INV-S-MEM-1 (single-source register definition)

The emitted RTL is a build output: every `<register>` decode line traces back to a chart channel. INV-SOS-A (chart-as-source) and INV-S-MEM-1 (single-source register definition) are both **mirror** — SOS-09-E owns no new chart-source claim; it owns one new artifact emitted from the existing chart source.

## 11. Non-goals

This sub-phase does NOT:

- **Author a full SoC bus.** AXI4-Full burst, AXI4-Stream, AHB, custom proprietary buses are out of scope at v1. The two AMBA enumerated bus types (AXI4-Lite + APB) cover the slave-register-file integration surface; SoC-level bus interconnect is the consuming SoC team's responsibility.
- **Author a memory controller.** SOS-09-E emits register-file RTL — flop banks + decode + handshakes — NOT DRAM controllers, NOT cache controllers, NOT memory hierarchies. The `sos_dpram_arb` primitive composed for `queue` and `shared` channels is dual-port RAM (BRAM / LUT-RAM), not external memory.
- **Cover AXI4-Full burst at v1.** AXI4-Full burst protocol's outstanding-transaction tracking adds significant complexity to the decode-line gating (a burst may straddle multiple register offsets); this is deferred to a future sub-phase if the consuming SoC team demands burst-mode access to register banks. SOS-09-E v1 stays on the slave-register-file integration surface.
- **Cover AXI4-Stream channels for queues at v1.** The v1 `queue` channel realisation uses `sos_dpram_arb`'s native interface plus a status register for non-empty notification; AXI4-Stream's `tvalid`/`tready` handshake plus per-flit metadata is deferred to a future enhancement. The chart's `queue` channel produces a DPRAM-backed FIFO at v1; chart authors needing AXI-Stream-style streaming wait for the future extension.
- **Verify physical metastability in the formal model.** Per `INV-S-HDL-3` (from SOS-08 §7), `sos_synchronizer` flops are excluded from the formal proof; MTBF handles the cross-domain path. SOS-09-E's `sos_synchronizer` insertion (per §5.2 `command` row + §10 vs. SOS-08-D) inherits this exclusion.
- **Emit SoC-level integration glue.** Clock trees, reset distribution, IO pin assignment, board-specific instantiations, top-level wrapper generation — out of scope per SOS-08 §11 / PCDN-SOS-08-011. SOS-09-E emits the register-file IP block, not the SoC.
- **Define a debugger-side artifact format beyond CMSIS-SVD.** Debug consumers consume the SVD via standard tools; SOS-09-E does not author a new debug-side protocol. The HW-side debug observability is bus accesses (the same as the firmware path) plus the access-violation channel — both already enumerated in the chart.
- **Author dynamic register-file reconfiguration.** Runtime addition / removal of registers is out of scope; SOS-09-E's emission is a static elaboration-time decision based on the chart's channel set.
- **Replace the SOS-08-A primitive library.** SOS-09-E composes; it does not re-derive. Any change to a primitive's contract (e.g. `sos_strobe_latch`'s ack semantics) ratifies in SOS-08-A; SOS-09-E follows.

## 12. Acceptance checklist

A conforming SOS-09-E ratification satisfies:

- (a) ⏸ PCDN-SOS-09-E-001 through 006 resolved (§15).
- (b) ⏸ `sos_regfile` template module exists and accepts a bus-type parameter (per §5.7).
- (c) ⏸ Per-channel realisation table (§5.2) implemented for all four chart `kind` values (`status`, `command`, `queue`, `shared`).
- (d) ⏸ Write-mask policy (§5.3) verified by acceptance gate (b) coverage and gate (c) reserved-bit read-as-zero.
- (e) ⏸ Read-clear gating (§5.4) verified by acceptance gate (d) zone-gated read-clear.
- (f) ⏸ Access-violation event (§5.5) emits to a channel-group `sos_strobe_latch` and surfaces as a chart-declared status channel.
- (g) ⏸ Language parity (§5.6) verified — VHDL-2008 and SystemVerilog-2017 emissions pass the same membrane vector suite (acceptance gate (f)).
- (h) ⏸ SVD-offset match (INV-S-MEM-E-6) verified by acceptance gate (h) build-stop scan.
- (i) ⏸ Synthesis-tool coverage (§5.6) — emissions pass Xilinx Vivado 2024.1+, Intel Quartus Pro 23.x+, and Yosys 0.37+ for at least one representative chart channel-group (acceptance gate (g)).
- (j) ⏸ Cross-sub-phase invariants `INV-S-MEM-E-1` through `INV-S-MEM-E-6` cited correctly in the SOS-09-E emit-path source (typically via an `@spec` comment block).
- (k) ⏸ Cross-phase invariants `INV-SOS-A` through `INV-SOS-H` cited per `@spec` comment block referencing SOS-07.
- (l) ⏸ SOS-09 umbrella `INV-S-MEM-1` through `INV-S-MEM-6` satisfied (the RTL is a build output per INV-S-MEM-2; single-source per INV-S-MEM-1; protection end-to-end per INV-S-MEM-3 paired with SOS-09-G).

(a) is the ratification gate; (b)–(l) are implementation gates that flip from ⏸ to ✅ as the implementation lands.

A conforming SOS-09-E *without queue or shared channels* (i.e. charts consisting only of `status` and `command` channels — typical for first-target bring-up demos) satisfies (a)–(c) with the `queue` and `shared` rows of (c) skipped, plus (d)–(l). This second-tier conformance level supports first-target ECP5 bring-up demos that exercise only the simpler register surface, deferring queue + shared coverage to subsequent bring-up rounds.

## 13. Files cited

| Path | Role |
|---|---|
| `docs/concepts/SOS-09-CONCEPTS.md` | Umbrella; this sub-phase's parent. |
| `docs/concepts/SOS-09-A-CONCEPTS.md` | Chart annotation surface; SOS-09-E consumes `other_attributes` JSON with `sos:`-prefixed keys. |
| `docs/concepts/SOS-09-B-CONCEPTS.md` | CMSIS-SVD emission; SOS-09-E mirrors the address-offset assignment byte-for-byte per INV-S-MEM-E-6. |
| `docs/concepts/SOS-09-F-CONCEPTS.md` | Membrane vectors; consumes SOS-09-E's emitted RTL via cocotb. |
| `docs/concepts/SOS-09-G-CONCEPTS.md` | MPU configuration emission; sister sub-phase emitting the SW-side fence (protection end-to-end per INV-S-MEM-3). |
| `docs/concepts/SOS-08-CONCEPTS.md` | HDL backend umbrella; L0 primitive library and `INV-S-HDL-1` through `INV-S-HDL-5`. Cited, not redefined. |
| `docs/concepts/SOS-08-A-CONCEPTS.md` | L0 primitive contracts; `sos_strobe_latch`, `sos_dpram_arb`, `sos_mutex`, `sos_synchronizer` composed without modification. |
| `docs/concepts/SOS-08-B-CONCEPTS.md` | L1 service composition; `sos_message_channel` composed for `queue` channels. |
| `docs/concepts/SOS-08-C-CONCEPTS.md` | Shared-signal HDL wiring; the OR-aggregation seam for access-violation strobes. |
| `docs/concepts/SOS-08-D-CONCEPTS.md` | Clock-domain declaration; `<sos:clock_domains>` drives `sos_synchronizer` insertion. |
| `docs/concepts/SOS-08-E-CONCEPTS.md` | VHDL walker; consumed via the shared-RHS hardening to guarantee bit-identical emission. |
| `docs/concepts/SOS-08-F-CONCEPTS.md` | SystemVerilog walker; consumed alongside SOS-08-E for the second language emission. |
| `docs/concepts/SOS-08-WAVE3-CONFORMANCE.md` | Wave-3 conformance entry hardening shared-RHS; SOS-09-E inherits the bit-identical claim. |
| `docs/concepts/SOS-07-CONCEPTS.md` | Cross-phase invariants `INV-SOS-A` through `INV-SOS-H`; AuthorityRelationship matrix. Cited, not redefined. |
| `tools/sos-codegen/transliterate_hdl_vhdl.py` | Existing VHDL walker entry point; SOS-09-E's implementation phase extends with `sos_regfile` template emission. |
| `tools/sos-codegen/transliterate_hdl_sv.py` | Existing SystemVerilog walker entry point; SOS-09-E's implementation phase extends with `sos_regfile` template emission. |
| `tools/sos-codegen/templates/sos_regfile.{vhd,sv}.j2` | The new template module (forthcoming; per §5.7 lives in the codegen tool's template directory). |
| `tools/sos-codegen/tests/test_sos_09_e_concepts_doc.py` | Per-doc-assertion test module for this concept doc. |
| `build/rtl/<chart_id>/sos_regfile_<peripheral>.{vhd,sv}` | Emitted RTL artifact (forthcoming; per INV-S-MEM-2 lives under `build/`, not tracked source). |
| Parent `CLAUDE.md` | Spec-Before-Code Planning Discipline; Phase document shape. |

## 14. Unblocks

This sub-phase's ratification (after PCDN walkthrough) unblocks:

- **SOS-09-F** (membrane vectors) — the cocotb harness needs concrete SOS-09-E-emitted RTL to exercise; the six vector shapes (initial-value-read, write-then-read, side-effect-on-write, clear-on-read, atomicity, protection) all instantiate against the `sos_regfile` template.
- **SOS-09-G** (MPU configuration emission) — INV-S-MEM-3 (protection end-to-end) requires both sides; SOS-09-G's acceptance gate (b) protection vector consumes the SOS-09-E access-violation channel as its end-to-end protection-failure observation point.
- **SOS-09 acceptance gate (e)** — the HDL register-file RTL synthesizes via Yosys + nextpnr per SOS-08 PCDN-008 / EOQ-004 Lattice ECP5 target.
- **SOS-08 wave-N HDL conformance gates referencing SOS-09** — any wave-N entry that adds SOS-09-E-emitted register files to the conformance set (e.g. a wave-4 entry that extends the chart-conformance vector suite to register-file synthesis on ECP5) consumes SOS-09-E's contract surface.
- **The first end-to-end chart-driven SoC bring-up demo with a synthesizable register file** — chart → CMSIS-SVD + Rust HAL + HDL register file + MPU table + membrane vectors → Yosys+nextpnr ECP5 bitstream → cocotb-validated round-trip, with the chart as the single source for the silicon-side register file.

## 15. Pending Concept Decision Notices (PCDNs)

These open questions move this doc from 🟡 drafted to 🟢 ratified. PCDN-SOS-09-E-* identifiers are stable per parent CLAUDE.md "Errata Open Question" naming convention (analogous shape applies — these are PCDNs at the concepts-doc level).

- **PCDN-SOS-09-E-001 — Bus interface default: AXI4-Lite vs APB.** 🟡 **PENDING USER WALKTHROUGH 2026-05-26.** Options: (a) AXI4-Lite default (widely deployed; supported by every Xilinx/Intel/Lattice tool flow; the dominant register-file bus in modern SoCs); (b) APB default (simpler protocol; lower gate count; canonical for register-block use in lower-power SoCs). **Recommendation**: option (a) AXI4-Lite default. AXI4-Lite is the dominant register-file bus across the SoC ecosystem; APB stays available as an alternative for low-gate-count or legacy-integration cases via the chart's `sos:bus` annotation. The default chooses the path of widest tool support.

- **PCDN-SOS-09-E-002 — Reserved-bit handling: read as 0 vs read as last-write vs read as undefined.** 🟡 **PENDING USER WALKTHROUGH 2026-05-26.** Options: (a) read as 0 (canonical ARMv7-M discipline; matches SOS-09 umbrella §5.5 / PCDN-SOS-09-003 ratification); (b) read as last-write (reserved bits behave as a flat flop bank; writes propagate; reads return the prior write); (c) read as undefined (allow synthesizers to optimise the bits away; emission carries an `X` in simulation). **Recommendation**: option (a) read as 0. Matches ARMv7-M discipline (cited at SOS-09 umbrella §5.5); avoids the bench-time confusion where firmware engineers conclude reserved bits are RW because the silicon happened to behave that way; consistent with the §5.3 write-mask policy that already gates writes to reserved bits to discard.

- **PCDN-SOS-09-E-003 — Access-violation aggregation strategy: one strobe-latch per chart channel-group or one per register.** 🟡 **PENDING USER WALKTHROUGH 2026-05-26.** Options: (a) one strobe-latch per chart channel-group (one IRQ vector covers all violations within a `sos_regfile` instance; matches MPU region granularity per SOS-09-G §5.2); (b) one strobe-latch per register (per-register IRQ vector; finer-grained but consumes more SOS-08-A primitive instances and more NVIC lines); (c) hybrid (per channel-group by default; per-register override via `sos:violation_aggregate="per_register"` chart annotation). **Recommendation**: option (a) per channel-group. Matches MPU region granularity (SOS-09-G already operates on channel-group granularity); minimises NVIC vector consumption; the per-register granularity is recoverable from the bus transaction log if the consumer needs it. Option (c) hybrid is a future extension if a chart-author demands per-register isolation.

- **PCDN-SOS-09-E-004 — Clock-domain crossing default: assume single-domain unless `<sos:clock_domains>` declares otherwise, or always insert `sos_synchronizer`.** 🟡 **PENDING USER WALKTHROUGH 2026-05-26.** Options: (a) chart-declared (no implicit synchronizer; chart errors out at SOS-01 lint if domains are unspecified for cross-domain access); (b) always insert `sos_synchronizer` defensively (correct-by-construction but adds latency and gate cost on single-domain paths). **Recommendation**: option (a) chart-declared. The chart-as-source claim (per INV-SOS-A) requires explicit domain declaration when cross-domain access exists; defensive insertion hides latency cost from the chart author and contradicts the SOS-08-D contract that `<sos:clock_domains>` is the source of truth for domain assignments. SOS-01 lint catches missing declarations upstream of SOS-09-E.

- **PCDN-SOS-09-E-005 — `sos_regfile` template: single template (parameterised over bus type) or two templates (one per bus).** 🟡 **PENDING USER WALKTHROUGH 2026-05-26.** Options: (a) single template, bus-type parameter (elaboration-time selects between AXI4-Lite and APB port sets via a generic/parameter); (b) two distinct templates, one per bus (each template is simpler but the code duplication is significant — every per-channel realisation submodule must wire to both port sets). **Recommendation**: option (a) single template. The per-channel realisation submodules are identical between AXI4-Lite and APB (both are handshake protocols with valid+address+data+write-enable surfaces); the only difference is the bus-side port naming and the handshake-cycle count. A parameterised template avoids the duplication and keeps the bit-identical claim (INV-S-MEM-E-5) tractable. Option (b) would force two parallel maintenance surfaces with identical internal logic.

- **PCDN-SOS-09-E-006 — Write-side-effect timing: `command` writes' `fire` strobe is one bus cycle (combinational, decoded from valid+address+write) vs registered (one cycle later).** 🟡 **PENDING USER WALKTHROUGH 2026-05-26.** Options: (a) combinational (fire-on-decode; minimal latency but susceptible to glitches if the bus master de-asserts valid mid-decode); (b) registered (one cycle after decode; matches SOS-08-A `sos_strobe_latch`'s pulse-to-level cadence; more robust against bus glitches); (c) chart-author choice via `sos:fire_timing="combinational" | "registered"` annotation. **Recommendation**: option (b) registered. More robust against bus glitches (the registered cadence aligns with SOS-08-A `sos_strobe_latch`'s pulse-to-level + ack contract per `SOS-08-A-CONCEPTS.md` §6.10); the one-cycle latency is negligible at register-file access timescales; matches the SOS-08-A primitive library's idiom of latched events rather than combinational pulses.

## 16. Change log

### 2026-05-26 — Initial draft (Ira)

- Authored `SOS-09-E-CONCEPTS.md` as the HDL register-file RTL emission sub-phase under the SOS-09 umbrella.
- §3 canonical glossary: terms `sos_regfile` template module, register-decode line, write-mask, reserved-bit handling, access-violation event, zone-decode AND-gate, bit-identical RTL emission, per-channel realisation submodule.
- §4 source-of-truth map: bus interface enumeration; `sos_regfile` template shape; per-channel realisation table; register-decode generation; write-mask generation; reserved-bit handling; read-clear gating; access-violation event aggregation; language emission shape; synthesis-tool target set; AMBA AXI4-Lite + APB protocol authorities; IEEE Std 1076-2008 (VHDL) + 1800-2017 (SV) language authorities; L0 primitive contracts (mirror SOS-08-A); address-offset assignment (mirror SOS-09-B); chart annotation source (mirror SOS-09-A); `<sos:clock_domains>` (mirror SOS-08-D).
- §5 frozen decisions: §5.1 bus interface enum `{axi4lite, apb}` with AXI4-Lite default (Standards Action); §5.2 per-channel realisation table restating SOS-09 umbrella §5.2 with HDL-specific structural wiring (Standards Action); §5.3 write-mask policy synthesized from field-level `RW`/`RO`/`WO`/`reserved` (Standards Action); §5.4 read-clear gating on zone AND read_enable (Standards Action); §5.5 access-violation event aggregation into one strobe-latch per channel-group (Standards Action); §5.6 language emission shape VHDL-2008 + SV-2017 with synthesis-tool target set (Vivado 2024.1+, Quartus Pro 23.x+, Yosys 0.37+) (Specification Required); §5.7 `sos_regfile` template module shape with bus-type parameter (Specification Required).
- §6 cross-sub-phase invariants `INV-S-MEM-E-1` through `INV-S-MEM-E-6`: every register has exactly one decode line; every writable register has a write-mask; clear-on-read NEVER fires on non-matching-zone access; access-violation events deterministic; bit-identical VHDL/SV; RTL offsets match SVD `<offset>` byte-for-byte.
- §7 enumeration policy catalog table indexing §5.1-5.7 + §6 with Standards Action / Specification Required policies.
- §8 standards integration matrix additions: AMBA AXI4-Lite (derive), AMBA 3 APB (derive), IEEE Std 1076-2008 (derive), IEEE Std 1800-2017 (derive), Xilinx Vivado / Intel Quartus Pro / Yosys (derive); SOS-08-A primitives `sos_strobe_latch` / `sos_dpram_arb` / `sos_mutex` / `sos_synchronizer` (mirror); SOS-08-B `sos_message_channel` (mirror); SOS-09-A annotation schema (mirror); SOS-09-B address-offset assignment (compose); `<sos:clock_domains>` (mirror).
- §9 acceptance gates (a)–(i): duplicate-address detection; write-mask coverage; reserved-bit read-as-zero; zone-gated read-clear; access-violation determinism; language parity; synthesis-tool coverage; SVD-offset match; bus-protocol conformance.
- §10 reconciliation vs SOS-08-A (composes without modification), SOS-08-B (`sos_message_channel`), SOS-08-C (shared-signal wiring), SOS-08-D (clock domains drive synchronizer insertion), SOS-08-E (VHDL walker, shared-RHS path), SOS-08-F (SystemVerilog walker), SOS-08-WAVE3-CONFORMANCE (shared-RHS hardening), SOS-09-A (consumes annotation surface), SOS-09-B (silicon-side counterpart; mirrors offsets), SOS-09-F (membrane vectors exercise RTL), SOS-09-G (HW gate + SW MPU fence end-to-end), PCDN-SOS-09-001 amended (no `xmlns:sos` in RTL output).
- §11 non-goals: no full SoC bus / memory controller / AXI4-Full burst at v1 / AXI4-Stream queues at v1 / metastability formal proof / SoC-level integration glue / new debugger-side artifact format / dynamic register-file reconfiguration / SOS-08-A primitive library replacement.
- §12 acceptance checklist gates (a)–(l).
- §13 files cited including SOS-09 umbrella, SOS-09-A/B/F/G siblings, SOS-08-A/B/C/D/E/F primitives + walkers, SOS-08-WAVE3-CONFORMANCE, SOS-07 cross-phase invariants, existing HDL walker entry points, forthcoming template + emitted RTL artifact paths.
- §15 six PCDNs raised covering: bus default (AXI4-Lite); reserved-bit handling (read as 0); access-violation aggregation (per channel-group); clock-domain default (chart-declared); template structure (single parameterised); write-side-effect timing (registered).

Status: 🟡 **DRAFT 2026-05-26 — awaiting PCDN walkthrough**.
