# SOS Chart Inventory — Pre-Implementation Audit for PCDN-SOS-08-C-007

## §0 Header

- **Status**: 🟢 wave-1 inventory complete 2026-05-25
- **Purpose**: Pre-implementation audit for PCDN-SOS-08-C-007 (per-`<param>`
  sub-bus extension to the SOS-08-C wave-3-e port shape). PCDN-SOS-08-C-007
  was ratified 2026-05-25 with an addendum requesting a chart-inventory +
  vector-migration audit BEFORE the per-`<param>` walker work lands, so the
  implementer knows up-front which fixtures and generated artifacts will need
  byte-identity preservation versus rewrites.
- **Audit scope**: this subrepo only (`streamz/submodules/SOS/`). Parent
  softoboros repo + sibling streamz subrepos are out of scope; the dispatcher
  will run separate inventories for those if needed.
- **Audit kind**: read-only (no chart edits, no vector edits).
- **Authoring agent**: claude-opus-4-7 (1M context), dispatched on
  `sos-wt-inv-task` worktree from `webslinger@83c9aba`.

## §1 Scope

The audit covers every artifact under this checkout that could plausibly bind
to PCDN-SOS-08-C-007 territory:

- All `.scxml` files in the working tree.
- All inline-XML chart fixtures embedded as Python string literals in test
  modules under `tools/sos-codegen/tests/`.
- All generated test vector files (`.json` / `.jsonl`) under `examples/`,
  `conformance/`, `tools/sos-codegen/tests/fixtures/`, and
  `tools/sos-codegen/viewers/tests/fixtures/`.

**Out of scope** (by dispatch directive):

- Parent softoboros repo at `/Users/iraabbott/softoboros/`.
- Sibling streamz subrepos (`disco-analyzer/`, etc.).
- Generated artifacts under `.git/`, `target/`, `node_modules/`.
- Walker source code (`tools/sos-codegen/transliterate_*.py`) — referenced by
  citation only; not edited.

## §2 Methodology

The inventory was performed with the following systematic passes:

1. **`.scxml` discovery**: `find . -name "*.scxml" -not -path "./.git/*"`.
   Nine artifacts located (one root chart + eight test fixtures).
2. **Inline-XML fixture discovery**: `grep -l '<scxml\\|</scxml>'
   tools/sos-codegen/tests/*.py` returned zero hits. Cross-checked with
   `grep -c '<scxml\\|<state\\|<transition'`; the only matches were
   commentary text or error-message format strings, not literal SCXML
   payloads. **Finding**: SOS test modules construct chart-IR via Python
   dicts (e.g. `_simple_chart()` in `test_transliterate_hdl_sv.py`), not by
   embedding XML strings. The chart-IR dicts are downstream of the SCXML
   parser and live in the walker's intermediate representation — they are
   NOT chart artifacts for inventory purposes (the walker re-tests the
   parser, not the chart vocabulary).
3. **Generated vector discovery**: `find . -name "*.json" -o -name "*.jsonl"`
   filtered to exclude `.git/`, `node_modules/`, `target/`, and tool-config
   files (`CMakePresets.json` etc.). Six smoke conformance vectors, two UVM
   integration vectors, one codegen test-fixture vector, two viewer-fixture
   annotation streams catalogued.
4. **Payload-bearing-event classification per chart**:
   - Count of `<send ...>` elements (always with their `<param>` children).
   - Count of `<raise ...>` elements + which carry `<param>` children.
   - Count of `<assign expr="event.<EV>.value"/>` references (the wave-3-e
     captures the C-007 extension preserves as byte-identity aliases).
   - Count of `<assign expr="event.<EV>.<non-value>"/>` references (the
     wave-3-f-future-A REJECTED form per `_EVENT_PAYLOAD_RE` at
     `tools/sos-codegen/transliterate_hdl_sv.py:1251` — these CANNOT exist
     in committed fixtures because the walker rejects them at codegen time,
     but I searched anyway).
   - Count of `_event.data.<X>` ECMAScript-side references (the SCXML-spec
     standard payload-capture mechanism, distinct from the C-007 chart-IR
     `event.<EV>.value` form).
5. **Migration classification**: for each chart with non-zero payload usage,
   determine which forms migrate cleanly under C-007 versus which need
   rewrites.

### Classification rules

| Pattern | C-007 disposition |
|---|---|
| `<raise event="X"/>` with no `<param>` | unchanged (no `_send_data` port; no `_recv_data` port) |
| `<raise event="X"><param name="value" expr="..."/></raise>` | C-007 emits both `event_X_recv_data` (legacy alias) AND `event_X_recv_data_value` (new) |
| `<raise event="X"><param name="foo" expr="..."/></raise>` | C-007 emits `event_X_recv_data_foo`; legacy `event_X_recv_data` may also be aliased to the first `<param>` for compat (TBD by implementer; see §5) |
| `<assign expr="event.X.value"/>` | preserved byte-identity under C-007 |
| `<assign expr="event.X.foo"/>` with declared `<param name="foo">` | newly accepted under C-007 (today: rejected) |
| `_event.data.foo` (ECMAScript) | unchanged — this is the SCXML datamodel-runtime path, not the HDL emit surface; C-007 does not touch the simulator path |

## §3 Chart artifact catalogue

| # | Path | Kind | Description | LOC |
|---|---|---|---|---|
| 1 | `rtos_kernel.scxml` | root chart | Minimal preemptive priority-based RTOS kernel: 4 orthogonal parallel regions (scheduler, tick_service, syscalls, protection); ECMAScript datamodel; syscall ABI via `_event.data` payloads. The reference chart that the SOS-03 conformance vectors stimulate. | 580 |
| 2 | `tools/sos-codegen/tests/fixtures/single_region_simple.scxml` | test fixture | SOS-08-C wave-1 golden fixture: 4 states (IDLE→ACTIVE→DONE→ERROR), unguarded transitions, no datamodel. Used as wave-1 minimum-viable-chart and as the chart anchor for `single_region_simple_vector.json`. | 49 |
| 3 | `tools/sos-codegen/tests/fixtures/single_region_with_datamodel.scxml` | test fixture | SOS-08-C wave-1 datamodel fixture: `counter` + `flag` datamodel signals with `<assign>` actions in `<onentry>` and on transition. No payload-bearing events. | 61 |
| 4 | `tools/sos-codegen/tests/fixtures/single_guarded_transition.scxml` | test fixture | SOS-08-C wave-2 fixture: two transitions out of `idle`, first guarded with `counter > 0`, second unguarded default. Datamodel: single `counter` i32-default. | 64 |
| 5 | `tools/sos-codegen/tests/fixtures/multiple_guarded_transitions.scxml` | test fixture | SOS-08-C wave-2 fixture: three guarded transitions in document-order priority (`a == 1`, `b > 5`, `c != 0`); exercises SOS-08-C §5.2 mux. | 71 |
| 6 | `tools/sos-codegen/tests/fixtures/depth_9_guard.scxml` | test fixture | SOS-08-C wave-2 fixture: guard with nine chained `&&` operators (depth 9) — over the PCDN-SOS-08-C-004 budget of 8. Exists to drive the over-budget rejection test. | 51 |
| 7 | `tools/sos-codegen/tests/fixtures/parallel_two_regions.scxml` | test fixture | SOS-08-C wave-2 fixture: `<parallel>` with two orthogonal regions (`region_a`, `region_b`); separate event triggers `go_a` / `go_b`. No datamodel; no cross-domain. | 71 |
| 8 | `tools/sos-codegen/tests/fixtures/parallel_with_cross_domain.scxml` | test fixture | SOS-08-C wave-2 fixture: two regions in different clock domains (`clk_main` / `clk_fast`) via `<sos:region clock="..."/>` annotation; cross-domain `shared_flag` boolean datamodel signal. Drives PCDN-SOS-08-C-002 retain-synchronisers test. | 93 |
| 9 | `tools/sos-codegen/tests/fixtures/discharged_bounds_chart.scxml` | test fixture | SOS-13 fixture: chart with `<sos:discharged check="bounds"/>` on one state, paired with an `<onentry>` script doing a bounds-checked index access. Drives the verified-strip post-pass. | 45 |

**Inline-XML fixtures in Python test modules**: zero. Confirmed by
`grep -l '<scxml\\|</scxml>' tools/sos-codegen/tests/*.py` returning empty.
Chart-IR dicts built by `_simple_chart()` and siblings in
`test_transliterate_hdl_sv.py` are post-parser walker inputs, not SCXML
artifacts.

**Total chart artifacts catalogued**: 9.

## §4 Payload-bearing event analysis

| # | Chart | `<send>` | `<raise>` total | `<raise>` w/ `<param>` | `event.<EV>.value` | `event.<EV>.<non-value>` | `_event.data.<X>` |
|---|---|---|---|---|---|---|---|
| 1 | `rtos_kernel.scxml` | 0 | 15 | **0** | 0 | 0 | 11 |
| 2 | `single_region_simple.scxml` | 0 | 0 | 0 | 0 | 0 | 0 |
| 3 | `single_region_with_datamodel.scxml` | 0 | 0 | 0 | 0 | 0 | 0 |
| 4 | `single_guarded_transition.scxml` | 0 | 0 | 0 | 0 | 0 | 0 |
| 5 | `multiple_guarded_transitions.scxml` | 0 | 0 | 0 | 0 | 0 | 0 |
| 6 | `depth_9_guard.scxml` | 0 | 0 | 0 | 0 | 0 | 0 |
| 7 | `parallel_two_regions.scxml` | 0 | 0 | 0 | 0 | 0 | 0 |
| 8 | `parallel_with_cross_domain.scxml` | 0 | 0 | 0 | 0 | 0 | 0 |
| 9 | `discharged_bounds_chart.scxml` | 0 | 0 | 0 | 0 | 0 | 0 |
| | **Totals** | **0** | **15** | **0** | **0** | **0** | **11** |

**Methodology cross-check**:

- Walker rejection patterns (`_EVENT_PAYLOAD_RE` at
  `tools/sos-codegen/transliterate_hdl_sv.py:1251` and the corresponding
  VHDL emitter) reject `<assign expr="event.<EV>.<custom>"/>` at codegen
  time. Therefore no committed fixture CAN carry the rejected form without
  the relevant walker test failing. The audit confirms this: zero
  `<non-value>` references.
- `rtos_kernel.scxml` uses the SCXML-spec ECMAScript payload-capture form
  `_event.data.<X>` in 11 transition script bodies (see lines 272, 291,
  310, 331, 348, 362, 383, 403, 422, 437, 466, 504). This is the
  SCXML-runtime payload-binding mechanism — it is **NOT** the HDL emit
  surface that C-007 modifies. `_event.data.*` references are interpreted
  by the chart's `datamodel="ecmascript"` runtime in the SOS-03 simulator
  pipeline; they do not flow through the `event.<EV>.value` regex the
  HDL walker uses.
- `rtos_kernel.scxml`'s 15 `<raise>` elements raise control-plane events
  (`kernel.boot.done`, `sched.run`) with NO `<param>` children. They do
  not exercise the C-007 surface.

**Finding**: **no committed chart fixture in this subrepo exercises the
HDL-emit payload-bearing-event surface that PCDN-SOS-08-C-007 extends.**
The chart-IR-level payload tests live in `test_transliterate_hdl_sv.py`
(and the VHDL equivalent), which inject payload-bearing events through
Python dicts at the chart-IR layer downstream of the SCXML parser. Those
tests are not chart artifacts in the inventory sense — they are walker
unit tests whose inputs are not SCXML files.

## §5 Migration manifest

**No charts in this subrepo require migration under PCDN-SOS-08-C-007.**

Rationale: §4 shows zero `<raise>` or `<send>` elements with `<param>`
children, zero `<assign expr="event.<EV>.value"/>` references, and zero
`<assign expr="event.<EV>.<custom>"/>` references across all nine
committed chart artifacts. The C-007 extension therefore has no
chart-side migration debt in this subrepo's committed `.scxml` corpus.

**Implication for the implementer**:

- The PCDN-SOS-08-C-007 implementation PR can add per-`<param>` sub-bus
  emission to the wave-3-e port shape without touching any committed
  `.scxml` file in this subrepo.
- New tests for the per-`<param>` semantics should follow the existing
  `test_transliterate_hdl_sv.py` pattern (chart-IR dicts), not introduce
  new `.scxml` fixtures.
- If the implementer DOES want a `.scxml` round-trip test for C-007
  (parser → walker → emitter), that fixture will be net-new and should
  follow the §3 fixture-file shape: a single-region or two-region chart
  with one or two `<raise>` elements carrying `<param>` children, paired
  with `<assign expr="event.<EV>.value"/>` and (post-C-007)
  `<assign expr="event.<EV>.<custom>"/>` capture sites.

**Byte-identity preservation policy for legacy `event.<EV>.value`**:

PCDN-SOS-08-C-007 explicitly states the legacy unnamed `_recv_data` bus is
preserved as a byte-identity alias for charts that use only
`event.<EV>.value`. Since this subrepo has zero such existing references
in committed fixtures, the implementer can choose either path without
breaking any in-repo chart:

- **Path A (alias preservation)**: keep `event_<EV>_recv_data` AS-IS for
  every single-`<param>` event, AND additionally emit
  `event_<EV>_recv_data_value`. Two ports drive the same wire. Pros:
  zero downstream churn; the SOS-08-C-CONCEPTS §6.5 reference design
  example continues to work verbatim. Cons: doubled port count for
  payload-bearing events.
- **Path B (explicit-name only)**: drop the unnamed `_recv_data` for
  payload-bearing events; emit only `_recv_data_value` (or whatever
  `<param>` name). Pros: cleaner port semantics; one port name per
  payload field. Cons: every downstream consumer of `_recv_data` would
  need to migrate.

**Recommendation**: Path A. The byte-identity alias is the PCDN's
explicit recommendation; preserving it costs only one extra `assign`
statement per payload-bearing event in the emitted RTL, and saves a
breaking change to every downstream wave (SOS-08-D / E / F / G) that
consumes wave-3-e's port shape.

## §6 Generated test vector inventory

| # | Path | Related chart | Cites event by name? | Carries `payload.value`? | C-007 migration relevance |
|---|---|---|---|---|---|
| 1 | `conformance/vectors/smoke/0001-two-tasks-same-prio-alternate-via-yield.json` | `rtos_kernel.scxml` | yes (`task.create`, `task.yield`) | no — uses SCXML-spec `data: {id, prio}` form | none (simulator path; C-007 doesn't touch SOS-03 vector schema) |
| 2 | `conformance/vectors/smoke/0002-higher-prio-preempts-on-sem-give.json` | `rtos_kernel.scxml` | yes (`task.create`, `sem.create`, `sem.take`, `sem.give`) | no (same as above) | none |
| 3 | `conformance/vectors/smoke/0003-task-delay-tick-storm.json` | `rtos_kernel.scxml` | yes (`task.create`, `task.delay`, `sys.tick`) | no | none |
| 4 | `conformance/vectors/smoke/0004-queue-full-empty-rejection.json` | `rtos_kernel.scxml` | yes (`task.create`, `queue.create`, `queue.send`, `queue.receive`) | no | none |
| 5 | `conformance/vectors/smoke/0005-crit-defers-ticks.json` | `rtos_kernel.scxml` | yes (`crit.enter`, `sys.tick`, `crit.exit`) | no | none |
| 6 | `conformance/vectors/smoke/0006-sched-suspend-defers-unblock.json` | `rtos_kernel.scxml` | yes (`sched.suspend`, `sched.resume`) | no | none |
| 7 | `examples/uvm_integration/vectors/sem_chart_bound.jsonl` | rtos_kernel (semaphore subset) | yes (encoded as `event_id` int) | `payload_data` field is per-record but is the queue/sem-id, not an event.value | review pending: §6.1 below |
| 8 | `examples/uvm_integration/vectors/sem_chart_violation.jsonl` | rtos_kernel (semaphore subset) | yes (encoded as `event_id` int) | same as #7 | review pending: §6.1 below |
| 9 | `tools/sos-codegen/tests/fixtures/single_region_simple_vector.json` | `single_region_simple.scxml` | yes (`go`, `finish`, `reset`) | no — vector schema has `dut_port`, `signal_width`, no payload field | none (SOS-08-D primary-vector-path schema; C-007 is wave-3-e, upstream) |
| 10 | `tools/sos-codegen/viewers/tests/fixtures/example_annotations.jsonl` | synthetic (no chart file) | yes (transition_ids `t_idle_to_arming`, ...) | no — annotation schema for SOS-08-G GUI viewer | none |
| 11 | `tools/sos-codegen/viewers/tests/fixtures/example_with_vector_source.jsonl` | synthetic (no chart file) | yes (same as #10) | no | none |

**Total vectors catalogued**: 11.

### §6.1 UVM vector payload_data semantics

Records in `sem_chart_bound.jsonl` and `sem_chart_violation.jsonl` carry
a field named `payload_data` (e.g. `{"event_id":0,"payload_data":0,...}`).
This audit confirms — by inspecting the related rtos_kernel.scxml event
ABI (sem.create's `_event.data: { id, initial, max }`) — that
`payload_data` in these vectors encodes the **semaphore id**, NOT a
free-form payload routed through the wave-3-e `_recv_data` bus.

The UVM vector is a SOS-03 simulator-side trace, not a wave-3-e port-shape
trace. C-007 does not change its schema. **No migration required.**
If/when SOS-08-C wave-3-e (`<param>`-bearing `<raise>`) is ever exercised
by a UVM-targeted chart, that chart's UVM vector schema will need a new
field corresponding to `_recv_data_<param>`; this is out of scope for
PCDN-SOS-08-C-007 (it is a SOS-08-D / -E / -F / -G concern that depends
on C-007 landing first).

### §6.2 Schema-extension considerations

`tools/sos-codegen/tests/fixtures/single_region_simple_vector.json` (the
SOS-08-D primary-vector-path fixture) uses a schema with `dut_port` /
`signal_width` per step but has **no per-`<param>` field**. If a future
SOS-08-D vector targets a payload-bearing event, the schema will need
augmentation. This is a downstream-of-C-007 concern, flagged for the
next phase but not part of this audit.

## §7 Summary statistics

- **Total chart artifacts**: 9 (`.scxml` files; zero inline-XML fixtures).
- **Total `<raise>` / `<send>` elements with `<param>` children**: **0**.
- **Total `<assign expr="event.<EV>.value"/>` references**: **0**.
- **Total `<assign expr="event.<EV>.<custom>"/>` references**: **0**.
- **Total `_event.data.<X>` references**: 11 (all in `rtos_kernel.scxml`;
  SCXML-runtime path; out of scope for C-007).
- **Total migration-affected references (HDL-emit surface)**: **0**.
- **Estimated migration LOC for committed fixtures**: **0**.
- **Estimated test-suite additions for C-007 validation**: 6–10 new chart-IR
  tests in `test_transliterate_hdl_sv.py` and `test_transliterate_hdl_vhdl.py`
  exercising per-`<param>` sub-bus emission, alias preservation, and
  `event.<EV>.<custom>` capture acceptance. Estimate based on the existing
  `TestWave3ePayloadRouting` test class size (7 tests) at v1.
- **Total generated vectors catalogued**: 11.
- **Vectors requiring schema migration under C-007**: **0**.

## §8 Migration sequencing recommendation

Given §5's finding that **no committed chart needs migration**, the
sequencing for the C-007 implementation simplifies considerably:

1. **Walker change first**: implement per-`<param>` sub-bus emission in
   `transliterate_hdl_sv.py` and `transliterate_hdl_vhdl.py`. Land alongside
   new chart-IR tests in `test_transliterate_hdl_sv.py` /
   `test_transliterate_hdl_vhdl.py` (estimate 6–10 net new tests).
2. **Removal of the wave-3-f-future-A rejection**: drop the rejection branch
   in `_EVENT_PAYLOAD_RE` handling (currently raises with the
   "Multi-`<param>` event payload composition" diagnostic at
   `transliterate_hdl_sv.py:1308`). The rejection becomes acceptance for the
   `event.<EV>.<custom>` form once the per-`<param>` bus exists.
3. **Byte-identity alias for `_recv_data`**: keep emitting the unnamed
   `event_<EV>_recv_data` port for events with at least one `<param>`,
   driven by the same wire as `event_<EV>_recv_data_value`. This preserves
   SOS-08-C-CONCEPTS §6.5 reference design + wave-3-e regression-guard
   tests as written.
4. **Regression suite**: re-run the full
   `tools/sos-codegen/tests/test_transliterate_hdl_sv.py` and
   `test_transliterate_hdl_vhdl.py` suites; all existing tests should pass
   unmodified because their charts use only the `event.<EV>.value` form
   (which the alias preserves byte-identical).
5. **No `.scxml` fixture edits in the PCDN-SOS-08-C-007 PR**: any new
   `.scxml` fixture that exercises C-007 should be a SEPARATE follow-up PR
   to keep the diff legible. If included in the same PR, place it under
   `tools/sos-codegen/tests/fixtures/` with a header citing PCDN-SOS-08-C-007
   and the §4 acceptance test it drives.
6. **§15 amendment**: PCDN-SOS-08-C-007's resolution will require a §15
   entry in `docs/concepts/SOS-08-C-CONCEPTS.md` ratifying the
   per-`<param>` port-shape extension and the byte-identity alias rule.

## §9 Out-of-scope items (noted for future phases)

The audit surfaced a small number of items adjacent to C-007 territory but
not addressed by this PCDN:

- **Clock-domain payload routing (PCDN-SOS-08-D-008 territory)**:
  `parallel_with_cross_domain.scxml` exercises the cross-domain
  `shared_flag` boolean, but does NOT carry a `<param>`. If a future chart
  combines cross-domain transitions WITH per-`<param>` payload buses, the
  CDC-synchroniser surface needs to wrap the per-`<param>` sub-bus(es),
  not just the legacy unnamed bus. This is a D-008 / C-007 intersection
  not currently covered by any committed fixture.
- **Cross-region event-value capture (SOS-08-C-CONCEPTS §6.5 carry-forward,
  also gated by C-007)**: when a region's `<onentry>` references an event
  consumed by a different region, the wave-3-f walker today raises
  `UnsupportedChartError`. Per-`<param>` extension will need to address
  whether cross-region capture is unblocked by C-007 (the channel's
  per-`<param>` `_recv_data_<custom>` is conceptually exposable to
  additional consumers) or remains a future amendment. Out of scope for
  this audit; flagged for the C-007 implementer.
- **C-008 shared-datamodel HDL wiring**: PCDN-SOS-08-C-008 (also filed at
  `f0284fc`) covers the shared-datamodel signal surface across regions.
  None of the committed charts exercise shared-datamodel signals beyond
  the `shared_flag` cross-domain boolean in
  `parallel_with_cross_domain.scxml`, which is already accepted at v1.
  C-008 has its own audit scope; this inventory does not address it.
- **rtos_kernel.scxml is HDL-emit-incompatible at v1**: the chart's heavy
  use of `<script>` ECMAScript bodies (datamodel="ecmascript", inline
  `<![CDATA[ ... ]]>` JavaScript) means it cannot be emitted to RTL via
  the wave-3-{a..f} walker — the walker rejects ECMAScript-subset
  expressions outside the small accepted set. C-007 does not change this.
  rtos_kernel.scxml's role is as the simulator-side reference for SOS-03
  conformance vectors, not as a wave-3-e codegen target.
- **`_event.data.<X>` is an SCXML-runtime mechanism**: the 11 references
  in `rtos_kernel.scxml` are ECMAScript-side payload captures interpreted
  by the SOS-03 simulator's datamodel engine. They are syntactically
  unrelated to the chart-IR `event.<EV>.value` form that the HDL walker
  rewrites. C-007 does not touch the simulator path; this inventory notes
  the distinction so future readers do not conflate the two surfaces.

## §10 Change log

- **2026-05-25** — wave-1 inventory complete (claude-opus-4-7 dispatched
  agent). Audit performed against `webslinger@83c9aba` on worktree branch
  `sos-wt-inv-task`. Total 9 chart artifacts catalogued, 11 generated
  vectors catalogued; finding: zero committed chart fixtures exercise the
  HDL-emit payload-bearing-event surface that PCDN-SOS-08-C-007 extends,
  so no migration debt exists in this subrepo's chart corpus. The C-007
  implementer can land the walker change without touching any committed
  `.scxml` file; new tests should follow the chart-IR pattern in
  `test_transliterate_hdl_sv.py`. Byte-identity alias preservation
  (Path A in §5) recommended.
