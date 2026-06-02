# SOS — Errata Log

Living, in-repo log of accepted issues, execution deviations, and pre-existing infrastructure bugs surfaced during SOS development. Inbound bug reports use GitHub Issues as the triage queue; once triaged-and-accepted, the canonical record moves here.

Entries are permanent. Resolved entries stay as institutional memory; mark status, do not delete.

## Status legend

- 🟢 resolved — fix landed; verification cited
- 🟡 diagnosed — root cause known; fix scope agreed
- 🔴 open — undiagnosed
- ⚪ deviation-pending-ratification — execution diverged from ratified spec; awaiting §15 amendment

## Open questions (EOQ)

Open questions tied to errata entries appear here for at-a-glance visibility. Format: `EOQ-NNN-ERRATA-MMM`. See parent CLAUDE.md "EOQ identifiers" for the rule.

*(none open — ERRATA-001 through ERRATA-008 all resolved. EOQ-001-ERRATA-008 resolved
2026-06-02 via path (a) integer-only formatting + `--gc-sections`; see ERRATA-008.)*

## Status of this log

ERRATA is now actively used. SOS-00 ratified 2026-05-19; every subsequent phase (SOS-04 through SOS-13, including the SOS-08 / SOS-09 sub-phase families) carries its own §15 / §16 amendment surface. ERRATA accumulates the deviations and pre-existing bugs that need cross-session memory — execution drift discovered after ratification, stealth renames between concepts-doc cites and as-built filenames, and implicit invariants made explicit during cleanup waves. Per parent CLAUDE.md "stealth-revert prohibition": revert-shaped behaviour changes file an ERRATA entry FIRST in their own commit; this log is the institutional record those entries live in.

## Entry index

| ID | Status | Title | First seen | Owning phase |
|---|---|---|---|---|
| ERRATA-001 | 🟢 | SOS-09-B implementation cite mismatch (stealth rename `svd_emit.py` → `transliterate_svd.py`) | 2026-05-27 | SOS-09-B |
| ERRATA-002 | 🟢 | SOS-09-G implementation cite mismatch (stealth rename `mpu_emit.py` → `transliterate_mpu.py`) + missing SOS09G1 §16 entry | 2026-05-27 | SOS-09-G |
| ERRATA-003 | 🟢 | wave-7 same-region-only writer RHS constraint hardened from implicit to explicit | 2026-05-25 | SOS-08-C |
| ERRATA-004 | 🟢 | `sos:dir` value vocabulary inconsistent across SOS-09 family (`bidirectional` retracted in favour of `hw↔sw`) | 2026-05-27 | SOS-09-A |
| ERRATA-005 | 🟢 | SOS-12 boundary-vector `kind` field plural/singular convention codified (plural for events, singular for invariants) | 2026-05-27 | SOS-12 |
| ERRATA-006 | 🟢 | `VectorCategory.Boundary` name collision (SOS-03 legacy edge-case vs SOS-12 dispatch-boundary) — overload is intentional at v1, disambiguated by directory + subtype | 2026-05-27 | SOS-03 |
| ERRATA-007 | 🟢 | SOS-09-G MPU install-function name drift (`sos_mpu_install` vs `apply_mpu_config`) reconciled to canonical `apply_mpu_config()` | 2026-05-27 | SOS-09-G |
| ERRATA-008 | 🟢 | SOS-04 m7-rust port overflows 1 MiB FLASH (.text ≈ 1.44 MB) — float/u128 `core::fmt` + PAC `Debug` bloat from the JSON trace/parser layer; workspace `[profile.release]` also missing | 2026-06-02 | SOS-04 |

## ERRATA-001 — SOS-09-B implementation cite mismatch (stealth rename)

**Status:** 🟢 resolved
**First seen:** 2026-05-27 (HEAD at first sighting: `38d1ed9`)
**Owning phase:** SOS-09-B

### Symptom

`docs/concepts/SOS-09-B-CONCEPTS.md:328-330` (under §13 Files cited) lists three paths that do not exist in the tree:

- `tools/sos-codegen/svd_emit.py` — does not exist; actual SVD emitter lives at `tools/sos-codegen/transliterate_svd.py` (function `emit_svd()` at line 193, `emit_svd_from_chart()` at line 336).
- `tools/sos-codegen/svd_validate.py` — does not exist; no validator wrapper script has landed.
- `tools/sos-codegen/schemas/CMSIS-SVD-1.3.xsd` — does not exist; no `schemas/` directory has been created.

The same `svd_emit.py` cite appears in §13 row 1 ("Codegen tool; SOS-09-B emit path lives under `tools/sos-codegen/svd_emit.py` (forthcoming)") and the `svd_validate.py` cite appears both in §13 and in §4 (source-of-truth map row "SVD validator wrapper script").

### Root cause

SOS-09-B work landed as commit `b0b69c7` ("SOS09B1: implement CMSIS-SVD emitter (SOS-09-B foundation)") under the SOS-09-B umbrella; the chosen filename diverged from the §13 forecast (`svd_emit.py` → `transliterate_svd.py`) to align with the sibling family convention (`transliterate_c.py`, `transliterate_rust.py`, `transliterate_hdl_*.py`, `transliterate_cocotb.py`). No `SOS09B1` §16 implementation entry was filed at landing time to record the rename. The validator wrapper + XSD bundling work was not undertaken; the validation gate cited in §5.6 / §9 (a) / §9 (b) is therefore deferred surface, not landed surface.

### Fix

§16 amendment landing in the same commit as this errata entry, dated 2026-05-27, header "Implementation-cite reconciliation (ERRATA-001)". The amendment:

- Updates §13's first `tools/sos-codegen/` row from `svd_emit.py (forthcoming)` to `transliterate_svd.py (landed b0b69c7)`.
- Annotates the `svd_validate.py` and `schemas/CMSIS-SVD-1.3.xsd` rows as 🟡 deferred follow-ups with a cross-ref to this errata.
- Cross-cites ERRATA-001.

### Verification

`ls tools/sos-codegen/transliterate_svd.py` returns the file; `git log --oneline --all -- tools/sos-codegen/transliterate_svd.py` shows `b0b69c7` as the landing commit. `ls tools/sos-codegen/schemas` returns "No such file or directory" — confirms the deferred-follow-up annotation matches reality.

### Tracking

- `docs/concepts/SOS-09-B-CONCEPTS.md` §16 dated 2026-05-27 cross-cites this entry.
- Landing commit: `b0b69c7` (`SOS09B1: implement CMSIS-SVD emitter (SOS-09-B foundation)`).
- Deferred follow-ups: validator wrapper + XSD bundling remain unscheduled; the §5.6 validation gate is currently spec-only.

## ERRATA-002 — SOS-09-G implementation cite mismatch (stealth rename) + missing SOS09G1 §16 entry

**Status:** 🟢 resolved
**First seen:** 2026-05-27 (HEAD at first sighting: `38d1ed9`)
**Owning phase:** SOS-09-G

### Symptom

`docs/concepts/SOS-09-G-CONCEPTS.md:367` (under the 2026-05-25 ratification §16 entry) states "Implementation work on `tools/sos-codegen/mpu_emit.py` is unblocked." The path `tools/sos-codegen/mpu_emit.py` does not exist. The actual MPU emitter shipped as `tools/sos-codegen/transliterate_mpu.py` (commit `1759cb1`, "SOS09G1: implement MPU configuration emitter (SOS-09-G foundation)") with tests at `tools/sos-codegen/tests/test_transliterate_mpu.py`. No SOS09G1 §16 entry was filed at landing time recording either the rename or the implementation arrival.

### Root cause

Parallel to ERRATA-001: the SOS-09-G implementation landed under the family-wide `transliterate_*` filename convention (`transliterate_mpu.py`) rather than the `mpu_emit.py` forecast in the original 2026-05-25 ratification text. The §16 entry that would have recorded both the chosen filename and the implementation landing was never filed.

### Fix

§16 amendment landing in the same commit as this errata entry, dated 2026-05-27, header "SOS09G1 implementation entry + cite reconciliation (ERRATA-002)". The amendment:

- Records the SOS09G1 implementation landing as commit `1759cb1`, naming `tools/sos-codegen/transliterate_mpu.py` as the as-built path.
- Names the test module `tools/sos-codegen/tests/test_transliterate_mpu.py`.
- Supersedes the 2026-05-25 ratification §16 entry's closing line ("Implementation work on `tools/sos-codegen/mpu_emit.py` is unblocked") with a forward reference to the implementation entry.
- Cross-cites ERRATA-002.

### Verification

`ls tools/sos-codegen/transliterate_mpu.py` returns the file; `git log --oneline --all -- tools/sos-codegen/transliterate_mpu.py` shows `1759cb1` as the landing commit. `ls tools/sos-codegen/tests/test_transliterate_mpu.py` returns the test module.

### Tracking

- `docs/concepts/SOS-09-G-CONCEPTS.md` §16 dated 2026-05-27 cross-cites this entry.
- Landing commit: `1759cb1` (`SOS09G1: implement MPU configuration emitter (SOS-09-G foundation)`).

## ERRATA-003 — wave-7 same-region-only writer RHS constraint hardened from implicit to explicit (institutional memory)

**Status:** 🟢 resolved
**First seen:** 2026-05-25 (discovered during wave-3 conformance audit)
**Owning phase:** SOS-08-C

### Symptom

In the wave-1 and wave-2 emitter for chart-derived VHDL, writer-action RHS expressions evaluated against signals from the writer's own clock-region worked — but the constraint that the RHS MUST reference only same-region sources was an implicit property of the emitter, not an explicit guard. The VHDL walker's literal-zero degradation (when an RHS reduced to a constant in the writer's region context) coincidentally made literal cross-region RHS work, masking the underlying invariant. Wave-3's conformance audit (`docs/audits/wave-3/` §4) caught this: the emitter was passing tests by accident, not by design, and a chart that wrote `regA <= regB` where `regA` was in clock domain A and `regB` was in clock domain B would emit VHDL whose simulation behaviour was undefined.

### Root cause

The wave-1/2 chart→FSM emitter implicitly bound RHS expression evaluation context to the writer's region (because the walker recursed from the writer's state node and looked up signal sources via the local symbol table). Cross-region references could resolve to the wrong region's snapshot if the lookup happened to find a matching name in a non-local scope. The invariant "writer RHS references only same-region signals" was never written down; it was an emergent property of the walker's traversal order.

### Fix

Commit `fb621ed` ("SOS7CLN: wave-7 coherence cleanup — fixtures, fallbacks, shared-RHS") makes the constraint explicit: the walker now validates that every RHS signal reference resolves to the writer's own region, and raises a clear chart-authoring error when a cross-region reference is encountered. The implicit-success path is replaced with an explicit guard; tests that previously passed by accident now either pass by design (RHS is genuinely same-region) or fail loudly (chart needs a cross-region synchronizer per SOS-08 §7).

### Verification

Wave-3 conformance audit §4 documents the closure. The wave-3 test suite passes 1258 tests against the post-`fb621ed` tree; no test was deleted to accommodate the guard — the guard caught zero false-positives in the existing fixture set, confirming the constraint was always satisfied in-practice but was previously unenforced.

### Tracking

- Wave-7 cleanup commit: `fb621ed`.
- Wave-3 audit cross-reference: `docs/audits/wave-3/` §4 (closure documented there).
- This entry exists so future readers of `fb621ed` understand the change was a deliberate hardening of an implicit invariant into an explicit guard, not a side-effect of unrelated fixture/fallback work bundled into the same commit.

## ERRATA-004 — `sos:dir` value vocabulary inconsistent across SOS-09 family

**Status:** 🟢 resolved
**First seen:** 2026-05-27 (HEAD at first sighting: `038ed2d`)
**Owning phase:** SOS-09-A

### Symptom

Two ratified SOS-09-family documents enumerated the `sos:dir` value vocabulary differently:

- `docs/concepts/SOS-09-CONCEPTS.md` §5.2 channel → membrane-primitive mapping table — arrow form `{hw→sw, sw→hw, hw↔sw}` (three rows; third row uses `hw↔sw`). The §3 glossary entries for `queue channel` (`SOS-09-CONCEPTS.md:53`) and `shared channel` (`SOS-09-CONCEPTS.md:54`) corroborate the arrow form (`dir="hw↔sw"`).
- `docs/concepts/SOS-09-A-CONCEPTS.md` §5.4 rule (3) (`SOS-09-A-CONCEPTS.md:138`) — word form `{hw→sw, sw→hw, bidirectional}` (three values; third value uses `bidirectional`).

Both enumerations carry three values; only the third differs (`hw↔sw` vs `bidirectional`). The drift was surfaced by commit `4f33c1e` ("SOS01-09-W2N: §15 channel-annotation lint amendment (closes SOS-09 gate (i))") while authoring SCXML-LINT-CH-3 on SOS-01 §15 — the lint rule quotes the `sos:dir` enum verbatim from SOS-09 §5.2 (arrow form), inheriting the umbrella as canonical and surfacing the SOS-09-A restatement as the drifted copy.

### Root cause

SOS-09-A §5.4 was drafted in parallel with the umbrella SOS-09 §5.2 ratification (both ratified 2026-05-25 per `SOS-09-A-CONCEPTS.md:321` and the SOS-09 umbrella §15.5 entry). The drafter rendered the third `sos:dir` value in word form (`bidirectional`) as a natural-language clarification of the `hw↔sw` arrow shape, intending the two as synonyms. The intent was not documented; the synonym shape leaked into the validation-rule text where it became indistinguishable from a third-value enum drift. No PCDN was filed, no §16 amendment recorded the choice, and the umbrella's §5.2 canonical form was not re-cited in SOS-09-A §5.4.

### Fix

This errata commit + the SOS-09-A §16 amendment that co-lands:

- Adds a dated entry to `docs/concepts/SOS-09-A-CONCEPTS.md` §16 (dated 2026-05-27, header "§5.4(3) `sos:dir` vocabulary alignment with SOS-09 §5.2 (ERRATA-004)") that:
  - Retracts the word `bidirectional` as a synonym for `hw↔sw` across the SOS-09-A chart-annotation surface.
  - Amends §5.4 rule (3) to enumerate the `sos:dir` value vocabulary verbatim from SOS-09 §5.2 (arrow form `{hw→sw, sw→hw, hw↔sw}`).
  - Affirms SOS-09 umbrella §5.2 as canonical for the value vocabulary; the SOS-09-A restatement is the chart-author-facing mirror and carries no mutation rights.
  - Cross-cites this ERRATA entry + commit `4f33c1e` as the discovery commit.
- SCXML-LINT-CH-3 (already landed on SOS-01 §15 per commit `4f33c1e`) is correct as authored; no SOS-01 amendment is owed.

### Verification

`grep -n 'bidirectional' docs/concepts/SOS-09-A-CONCEPTS.md` returns zero hits in `§5.4` rule-(3) prose (the word may remain as a historical artifact in §16 ratification narrative pointing at this errata; the chart-author-facing rule text no longer carries it). `grep -n 'hw↔sw\|bidirectional' docs/concepts/SOS-09-A-CONCEPTS.md docs/concepts/SOS-09-CONCEPTS.md` shows the arrow form (`hw↔sw`) in both files as the chart-author-facing enum value. The SCXML-LINT-CH-3 rule text (in `docs/concepts/SOS-01-CONCEPTS.md` §15, commit `4f33c1e`) still quotes the arrow form unchanged.

### Tracking

- `docs/concepts/SOS-09-A-CONCEPTS.md` §16 dated 2026-05-27 ("§5.4(3) `sos:dir` vocabulary alignment with SOS-09 §5.2 (ERRATA-004)") cross-cites this entry.
- Discovery commit: `4f33c1e` ("SOS01-09-W2N: §15 channel-annotation lint amendment (closes SOS-09 gate (i))") — the SCXML-LINT-CH-3 authoring surfaced the drift by quoting umbrella §5.2 verbatim.
- Umbrella canonical source: `docs/concepts/SOS-09-CONCEPTS.md` §5.2 — the three-row mapping table whose dir-column carries `{hw→sw, sw→hw, hw↔sw}` as the canonical value set.
- This entry is filed and resolved at intake; no follow-up work owed.

### 2026-05-28 — Chart-family migration + validator narrowing closure

The 2026-05-27 ratification carved out a one-release migration window during which the SOS-09-A validator (`tools/sos-codegen/sos09_annotations.py`) accepted both `hw↔sw` and `bidirectional` in `ALLOWED_DIRS` / `_KIND_DIR_MATRIX`, so dependent charts could land their migration commits without simultaneous validator + chart edits. That window has now closed:

- **Chart migration** — SOS submodule commit `9682b35` ("ERRATA-004 sweep: bidirectional → hw↔sw across both chart families") migrated `charts/sis08_first_slice/sis08_first_slice.scxml` and `charts/sis08d_c2_membrane/sis08d_c2_membrane.scxml` to the canonical `hw↔sw` spelling. Verification: `grep -rn 'bidirectional' charts/sis08_first_slice/ charts/sis08d_c2_membrane/` returns zero hits.
- **Validator narrowing** — this errata follow-up commit removes the migration-window backstop from `tools/sos-codegen/sos09_annotations.py`. `ALLOWED_DIRS` is now `frozenset({"hw→sw", "sw→hw", "hw↔sw"})` and `_KIND_DIR_MATRIX` no longer admits `bidirectional` for either `queue` or `shared`. The validator now hard-errors on `bidirectional` with the §5.4(3) diagnostic `sos:dir value 'bidirectional' not in allowed set ['hw→sw', 'hw↔sw', 'sw→hw']`, mirroring §5.4(3) rule prose verbatim.
- **Chart-family pytest** — `python3 -m pytest charts/sis08_first_slice/vectors/sis08_first_slice/` (22/22) and `python3 -m pytest charts/sis08d_c2_membrane/vectors/sis08d_c2_membrane/` (28/28) both pass against the narrowed validator. Narrowing is a no-op for the post-migration chart families by construction.
- **Downstream test-suite migration** — `tools/sos-codegen/tests/test_sos09_annotations.py` plus several emitter test fixtures (`test_rust_hal_emit.py`, `test_transliterate_svd.py`, `test_c_hal_emit.py`, `test_regfile_emit.py`, `test_transliterate_mpu.py`, `test_mmio_emit.py`, `tests/fixtures/sos09_mpu_chart.scxml`) still construct fixtures with `dir="bidirectional"`. Those tests will fail against the narrowed validator and require a follow-up sweep to retarget every `bidirectional` literal to `hw↔sw`. The `mmio_emit.py` `_DIR_BIDIRECTIONAL` constant and `transliterate_regfile.py` per-channel docstrings carry the legacy spelling too. None of those surfaces are in the SOS-09-A validator's scope; they are downstream consumers that the ERRATA-004 closure unblocks. Status of this errata entry remains 🟢: the SOS-09-A surface (validator + §5.4(3) prose) is fully aligned with SOS-09 umbrella §5.2; the downstream sweep is a tracked follow-up, not a re-opening of this errata.

Status: 🟢 (unchanged — this is closure of the migration-window backstop, not a new errata).

## ERRATA-005 — SOS-12 boundary-vector `kind` field plural/singular drift

**Status:** 🟢 resolved
**First seen:** 2026-05-27 (HEAD at first sighting: `038ed2d`)
**Owning phase:** SOS-12

### Symptom

The SOS-12 boundary-vector subtype vocabulary appeared in two shapes across the just-ratified SOS-03 §15 vector-framework extension (commit `cdc7f85`, "SOS03-09/12-W2O: §15 vector-framework extensions (Membrane + Boundary categories)"):

- `docs/concepts/SOS-12-CONCEPTS.md` §5.1 sub-chart contract shape — contract-field names in plural form: `events_in`, `events_out`, `invariants.maintained_by_subchart`, `invariants.assumed_of_environment` (`SOS-12-CONCEPTS.md:135-139`); §7.2 boundary-vector class-of-vectors names collapse the latter two to `invariants_maintained` / `invariants_assumed` for symmetry with the event-side plural names.
- `tools/sos-codegen/sos12_boundary_vectors.py` emitter — per-record `kind` field values in MIXED form: plural for events (`events_in` at line 323, `events_out` at line 371) and singular for invariants (`invariant_maintained` at line 422, `invariant_assumed` at line 454).

The SOS-03 §15 W2O amendment ratified BOTH shapes as normative with an "Implementation note on plural-vs-singular" paragraph explaining the per-record-vs-class-of-vectors split, but the SOS-12 doc itself did not previously codify the convention; a reader landing on §7.2 + the emitter side-by-side could misread the plural-vs-singular mismatch as drift.

The orchestrator brief that motivated this entry initially described all four per-record `kind` values as singular (`event_in`, `event_out`, `invariant_maintained`, `invariant_assumed`); the as-built emitter actually emits MIXED form (plural for events, singular for invariants). The convention codified by this entry reflects the as-built emitter, not the initial brief, per the SOS-03 §15 W2O Part B subtype table at `docs/concepts/SOS-03-CONCEPTS.md:980-986` (which already documents the mixed-form shape correctly).

### Root cause

The SOS12C1 emitter (commit landing per the [2026-05-27 SOS12C1 §15 entry on SOS-12](./SOS-12-CONCEPTS.md#change-log)) authored the per-record `kind` field values with cardinality-sensitive shapes: plural for events (because each emitted record covers one event drawn from the named SET, with the `kind` value naming the set the event was drawn from) and singular for invariants (because each emitted record covers one invariant directly, with the `kind` value naming the per-record invariant). The cardinality-rationale was implicit in the emitter implementation but was not documented in SOS-12 §7.2 prose; the SOS-03 §15 W2O amendment caught the as-built shape and documented it, but the convention's home doc (SOS-12) did not yet carry the codification.

### Fix

This errata commit + the SOS-12 §15 amendment that co-lands:

- Adds a dated entry to `docs/concepts/SOS-12-CONCEPTS.md` §15 (dated 2026-05-27, header "Boundary-vector `kind` field plural/singular convention (ERRATA-005)") that:
  - Codifies the plural/singular convention: contract-field names are plural (they name SETS); per-record `kind` values follow cardinality (plural for events; singular for invariants).
  - Affirms the as-built SOS12C1 emitter as the source of truth for the per-record shape; no implementation change is owed.
  - Cross-cites the SOS-03 §15 W2O amendment Part B (commit `cdc7f85`), the emitter line numbers, and this errata entry.
  - Reaffirms the four §7.2 subtype names (`events_in`, `events_out`, `invariants_maintained`, `invariants_assumed`) as Standards Action per the SOS-03 §15 W2O Part B clause.
- No SOS-12 §7.2 prose is modified; the amendment adds the convention rather than rewriting the subtype enumeration.
- The SOS-03 §15 W2O amendment (commit `cdc7f85`) remains the cross-phase reference for the subtype + `kind`-field table; SOS-12 §15 now carries the convention's home-doc codification.

### Verification

`grep -n '"kind":' tools/sos-codegen/sos12_boundary_vectors.py` returns the four lines (323, 371, 422, 454) emitting `events_in`, `events_out`, `invariant_maintained`, `invariant_assumed` — confirming the as-built shape this entry ratifies. The SOS-12 §15 amendment's "convention (normative)" paragraph names plural events + singular invariants, matching the emitter; the SOS-03 §15 W2O Part B subtype table (`docs/concepts/SOS-03-CONCEPTS.md:980-986`) remains internally consistent.

### Tracking

- `docs/concepts/SOS-12-CONCEPTS.md` §15 dated 2026-05-27 ("Boundary-vector `kind` field plural/singular convention (ERRATA-005)") cross-cites this entry.
- Discovery commit: `cdc7f85` ("SOS03-09/12-W2O: §15 vector-framework extensions (Membrane + Boundary categories)") — the SOS-03 §15 amendment that documented both shapes as normative without yet codifying the convention in SOS-12's own surface.
- Emitter pins: `tools/sos-codegen/sos12_boundary_vectors.py` lines 323 (`events_in`), 371 (`events_out`), 422 (`invariant_maintained`), 454 (`invariant_assumed`) — the canonical per-record `kind` values.
- Cross-phase reference: `docs/concepts/SOS-03-CONCEPTS.md` §15 W2O Part B subtype table — the §7.2-derived class-of-vectors names + the as-emitted `kind`-field column.
- This entry is filed and resolved at intake; no follow-up work owed.

## ERRATA-006 — `VectorCategory.Boundary` name collision (SOS-03 legacy edge-case vs SOS-12 dispatch-boundary)

**Status:** 🟢 resolved
**First seen:** 2026-05-27 (HEAD at first sighting: `038ed2d`)
**Owning phase:** SOS-03

### Symptom

The `VectorCategory` enum at `docs/concepts/SOS-03-CONCEPTS.md` §5.1 carries a single value named `Boundary` that covers two distinct surfaces:

- **Legacy surface (pre-Wave-2O):** edge-case-of-a-primitive's-contract vectors per the original SOS-03 §5.1 enum. On-disk subdirectory: `conformance/vectors/boundary/`.
- **SOS-12 dispatch-boundary surface (Wave-2O):** per-dispatch-edge boundary vectors emitted by `tools/sos-codegen/sos12_boundary_vectors.py` per [SOS-12 §7.2](./SOS-12-CONCEPTS.md#72-boundary-vectors). Per the [2026-05-27 SOS-03 §15 W2O amendment Part B](./SOS-03-CONCEPTS.md#change-log) (commit `cdc7f85`), the emitter writes `"category": "Boundary"` verbatim, and the on-disk subdirectory is `conformance/vectors/boundary/sos12/<parent_chart_id>/<child_chart_id>/<NNNN>-<subtype>.json` to keep the directory tree distinguishable from the legacy `boundary/` subdirectory.

The two surfaces collide on the literal string `"Boundary"` at the enum-value layer; the SOS-03 §15 W2O amendment Part B's "legacy-name disambiguation note" + the directory-disambiguation rule (`boundary/` legacy vs `boundary/sos12/` dispatch) + the per-record `subtype` field (`events_in` / `events_out` / `invariants_maintained` / `invariants_assumed` for SOS-12 dispatch-boundary, all distinct from any SOS-03 legacy `Boundary` subtype) together make the surfaces distinguishable at read time, but a reader who lands on a `category: Boundary` record without checking either the directory layer or the `subtype` field cannot tell which surface produced it.

### Root cause

When the SOS12C1 emitter (Wave-1C) chose `"category": "Boundary"` as the literal string for its emitted records, the §5.1 enum already carried a value named `Boundary` (legacy edge-case surface). The Wave-2O SOS-03 §15 amendment had three resolution options:

- (a) Rename the SOS-12 dispatch-boundary surface's enum value to `DispatchBoundary` (and update the SOS12C1 emitter's literal-string output to match) — surfaces the distinction at the enum layer but requires an emitter-code change AND a downstream `.json` fixture migration if any fixtures had landed.
- (b) Rename the SOS-03 legacy edge-case surface's enum value to (e.g.) `PrimitiveBoundary` — surfaces the distinction at the enum layer but breaks every existing reference to the legacy `Boundary` value across the SOS-03 / SOS-08 / SOS-09 corpus.
- (c) Overload the existing `Boundary` value to cover both surfaces, disambiguated at (i) the on-disk directory layer (`boundary/` legacy vs `boundary/sos12/` dispatch) and (ii) the per-record `subtype` field (whose values are partitioned: SOS-12 dispatch-boundary subtypes are `{events_in, events_out, invariants_maintained, invariants_assumed}`, all distinct from any SOS-03 legacy `Boundary` subtype).

Wave-2O chose option (c) — the disambiguation works structurally and avoids both the emitter-code change and the corpus-wide rename. The choice is documented in the §15 W2O amendment's "legacy-name disambiguation note" + the Part B sub-section. This errata exists to record the collision is KNOWN and INTENTIONAL, not accidental, and to give a future reader confused by a `category: Boundary` record a single in-tree authority to consult.

### Fix

ERRATA-only resolution per the spec-before-code "ERRATA-only resolution" pattern (no spec text changed → no §15 amendment owed). The SOS-03 §15 W2O amendment (commit `cdc7f85`) already carries the legacy-name disambiguation note + the Part B sub-section; no further §15 amendment is owed at v1.

A future rename — promoting option (a) (rename SOS-12 dispatch-boundary surface to `DispatchBoundary`) or option (b) (rename SOS-03 legacy surface to `PrimitiveBoundary` or similar) — is left as a future amendment IF reviewer confusion emerges in practice. Both renames are §15 amendments at landing time; both require a co-amendment on the consumer side (option (a) on SOS-12; option (b) on the legacy-Boundary fixture authors).

### Verification

`grep -n 'category.*Boundary\|"Boundary"' tools/sos-codegen/sos12_boundary_vectors.py` confirms the emitter writes `"category": "Boundary"` verbatim. `docs/concepts/SOS-03-CONCEPTS.md` §5.1 + §15 W2O Part B together carry the canonical disambiguation: directory + `subtype` field. A reader who lands on a `category: Boundary` record can disambiguate by (i) the containing directory (`boundary/` legacy vs `boundary/sos12/` dispatch) OR (ii) the per-record `subtype` field (SOS-12 dispatch values are the four `events_in` / `events_out` / `invariants_maintained` / `invariants_assumed`; legacy values are anything else).

### Tracking

- SOS-03 §15 W2O amendment (commit `cdc7f85`, "SOS03-09/12-W2O: §15 vector-framework extensions (Membrane + Boundary categories)") — already documents the legacy-name disambiguation note + the Part B sub-section. No further §15 amendment is owed for ERRATA-006 at v1.
- SOS-12 §7.2 boundary-vector emission + the SOS12C1 emitter at `tools/sos-codegen/sos12_boundary_vectors.py` — the consumers that write `"category": "Boundary"` verbatim, whose behaviour this errata ratifies as intentional under option (c).
- Future amendment trigger: reviewer confusion in practice. If a reader files an issue or asks on a PR review which `Boundary` surface a record belongs to, that signal motivates promoting one of options (a) or (b) into a §15 amendment. Until then, the option-(c) overload + directory + `subtype` disambiguation stands.
- This entry is filed and resolved at intake; ERRATA-only form per the spec-before-code "no spec text changed → no §15 amendment owed" pattern. No co-amendment on SOS-03 §15 is owed by this entry; the existing W2O amendment carries the disambiguation.

## ERRATA-007 — SOS-09-G MPU install-function name drift (`sos_mpu_install` vs `apply_mpu_config`)

**Status:** 🟢 resolved
**First seen:** 2026-05-27 (HEAD at first sighting: `1180910` — the PCDN-SOS-09-G-005 ratification commit that explicitly noted the drift and deferred the §5.5 prose reconciliation)
**Owning phase:** SOS-09-G

### Symptom

Two ratified SOS-family documents named the MPU install entry point inconsistently:

- `docs/concepts/SOS-09-G-CONCEPTS.md` §5.5 + §3 glossary + §4 source-of-truth map + §5.3 C / Rust function declarations + §7 INV-S-MEM-G-3 invariant + §9 acceptance gate (c) — `sos_mpu_install()` (pre-2026-05-27 prose surface).
- `docs/concepts/SOS-04-CONCEPTS.md` §15 four-artifact boundary set table (the SOS-09-G row at `SOS-04-CONCEPTS.md:1282`, landed Wave-2P commit `38699f4`) + the 2026-05-27 cross-reference entry "PCDN-SOS-09-G-005 ratified (apply_mpu_config timing owned by SOS-04)" (landed Wave-5C commit `1180910`) + the PCDN-SOS-09-G-005 ratification question itself (commit `d9263a1`) — `apply_mpu_config()`.

The two identifiers refer to the same function — the MPU runtime install hook emitted alongside `sos_mpu_table` per [SOS-09-G §5.5]. The PCDN-SOS-09-G-005 ratification entry on the SOS-09-G side (`SOS-09-G-CONCEPTS.md:410`) explicitly acknowledged the drift and deferred §5.5 prose reconciliation as a future minor amendment ("Reconciling §5.5's identifier prose to match the boundary-set identifier is a future minor amendment (no behaviour change) and is NOT in scope for this PCDN ratification"). A future SOS-04 implementation wave wiring `apply_mpu_config()` at the SOS-04-owned call site per the ratified contract would have had to choose at the code level which name to honor, with the spec text giving no clear single answer.

### Root cause

SOS-09-G §5.5 was authored before the SOS-04 §15 four-artifact boundary set table; the two surfaces evolved independently. The SOS-09-G §5.5 prose picked `sos_mpu_install()` as a SOS-family-prefixed install-hook identifier (consistent with `sos_mpu_table` / `sos_mpu_region_t` siblings in the same section). The SOS-04 §15 Wave-2P amendment authored the boundary-set table row referring to the same function as `apply_mpu_config()` — an action-verb-prefix form better suited to the boundary-contract narrative (SOS-04's runtime "applies" the SOS-09-G-emitted "config" at boot time). PCDN-SOS-09-G-005's ratification question used the Wave-2P boundary-set name (`apply_mpu_config()`) without flagging the §5.5 inconsistency; the ratification commit (`1180910`) carried the drift forward, with the PCDN-005 SOS-09-G §16 entry explicitly noting it as a known deferral.

### Fix

This commit reconciles the spec text to the single canonical identifier `apply_mpu_config()`. Resolution path:

- **Canonical name picked:** `apply_mpu_config()`. Three commits (one Wave-2P, two Wave-5C) already pin this name at the cross-boundary contract surface; the non-canonical `sos_mpu_install()` identifier appeared only in SOS-09-G §5.5 prose + the surrounding glossary / declaration / invariant / gate surfaces that mirror §5.5's choice. The path of least drift is updating the SOS-09-G normative surface to match what SOS-04 §15 already pins.
- **`docs/concepts/SOS-09-G-CONCEPTS.md`** — §16 dated 2026-05-27 entry "ERRATA-007 resolution: canonical MPU install function name" lands with this commit, citing this errata and recording the canonical-name pick. §3 glossary entry (line 52) renamed; §3 glossary backreference (line 51) updated; §4 source-of-truth map row (line 69) renamed; §5.3 C `void` declaration (line 138) renamed; §5.3 Rust `pub fn` declaration (line 154) renamed; §5.5 section title (line 174) + introducing sentence (line 178) + idempotency sentence (line 187) renamed; §7 INV-S-MEM-G-3 invariant statement (line 216) renamed; §9 acceptance gate (c) test-scaffolding cite (line 245) renamed. Historical §16 entries dated before 2026-05-27 are NOT modified — they remain as institutional memory of how the drift accumulated (per parent CLAUDE.md "stealth-revert prohibition" + this log's "entries are permanent" doctrine).
- **`docs/concepts/SOS-04-CONCEPTS.md`** — §15 dated 2026-05-27 entry "Cross-reference: ERRATA-007 settles MPU install function name" lands with this commit, confirming `apply_mpu_config()` as the canonical name and citing this errata + the co-landing SOS-09-G §16 entry. The four-artifact boundary set table itself (row at line 1282) is unchanged — it already carried the canonical name.

### Verification

`grep -n "sos_mpu_install\|apply_mpu_config" docs/concepts/SOS-09-G-CONCEPTS.md docs/concepts/SOS-04-CONCEPTS.md docs/concepts/ERRATA.md` — pre-commit: SOS-09-G had 17 `sos_mpu_install` + 10 `apply_mpu_config`; SOS-04 had 0 `sos_mpu_install` + 4 `apply_mpu_config`; ERRATA had 0 / 0. Post-commit: SOS-09-G's non-historical prose (§3 / §4 / §5.3 / §5.5 / §7 / §9) carries only `apply_mpu_config()`; remaining `sos_mpu_install()` occurrences are confined to (i) the §3 glossary entry's parenthetical pointing at this errata + flagging that historical §16 entries retain the earlier identifier, and (ii) the §13 files-cited recap inside the 2026-05-25 §16 "Initial draft (Ira)" entry + the §16 "Ratified (Ira)" entry + the §16 SOS09G1 / PCDN-SOS-09-G-005 entries (all historical institutional memory, dated before this errata, unchanged per the "entries are permanent" doctrine). SOS-04 grew one new `apply_mpu_config` occurrence (the new §15 cross-reference entry).

### Tracking

- `docs/concepts/SOS-09-G-CONCEPTS.md` §16 dated 2026-05-27 ("ERRATA-007 resolution: canonical MPU install function name") cross-cites this entry.
- `docs/concepts/SOS-04-CONCEPTS.md` §15 dated 2026-05-27 ("Cross-reference: ERRATA-007 settles MPU install function name") cross-cites this entry.
- PCDN-SOS-09-G-005 ratification commit: `d9263a1` (the ratification commit that adopted `apply_mpu_config()` in the ownership-split text).
- Wave-2P SOS04-09 runtime-boundary amendment commit: `38699f4` (the SOS-04 §15 commit that introduced `apply_mpu_config()` in the four-artifact boundary set table).
- Wave-5C cross-reference commit: `1180910` (the SOS-04 §15 + SOS-09-G §16 PCDN-005 cross-reference pair; the SOS-09-G side explicitly deferred this errata's reconciliation as a future minor amendment).
- This entry is filed and resolved at intake. The actual emitted Rust + C function names in `tools/sos-codegen/transliterate_mpu.py` MAY differ from the canonical spec name — that's a separate code-doc drift outside the scope of this errata, to be reconciled in a future implementation-side rename commit (no SOS-09-G or SOS-04 §16 / §15 amendment owed by such a future commit; only this errata's cite is needed).
- ERRATA-002 cross-reference: ERRATA-002 (filename rename context, commit `d24528f`) handles the SIBLING drift of the implementation filename (`mpu_emit.py` → `transliterate_mpu.py`). ERRATA-007 handles the function-NAME drift at the spec layer; the two are independent and resolved separately.

## ERRATA-008 — SOS-04 m7-rust port overflows 1 MiB FLASH (float/u128 fmt + PAC Debug bloat)

**Status:** 🟢 resolved (2026-06-02)
**First seen:** 2026-06-02 (HEAD at first sighting: `32f719f`)
**Owning phase:** SOS-04

### Symptom

The canonical SOS-04 build command (`SOS-04-CONCEPTS.md §8`):

```
cargo build --target thumbv7em-none-eabihf --release -p sos-m7-rust
```

fails at link with a FLASH-overflow cascade:

```
rust-lld: error: section '.text' will not fit in region 'FLASH': overflowed by 393076 bytes
rust-lld: error: section '.rodata' ... '.data' ... '.gnu.sgstubs' will not fit in region 'FLASH' ...
```

Linking against a temporarily-enlarged FLASH region and measuring with `llvm-size -A` shows
the real section breakdown (the `.data`/`.gnu.sgstubs` overflows in the error are *cascade
artifacts* — once `.text` runs past the FLASH end every later section is reported as
overflowing too):

| section | size | note |
|---|---|---|
| `.text` | **1,440,988 B (≈1.44 MB)** | overflows the 1 MiB (1024K) `FLASH` region in `memory.x:15` |
| `.rodata` | 108,260 B | |
| `.data` | 1,496 B | tiny — NOT the problem (matches the historical 62 KB May-22 skeleton ELF) |
| `.bss` | 21,364 B | |

`llvm-nm --print-size --size-sort` names the dominant `.text` contributors:

- `core::fmt::num::exp_u128` — **32,110 B** (single largest symbol)
- `core::num::flt2dec` dragon/grisu float-formatting (`format_shortest`, `format_exact`, `grisu`) — several KB each
- `core::num::dec2flt` float *parsing* (`parse_number`, `POWER_OF_FIVE_128` table ≈10 KB)
- `<stm32h7::stm32h747cm7::Interrupt as core::fmt::Debug>::fmt` — PAC enum `Debug` impl
- `sos_m7_rust::json_parser::{parse_event_data, resolve_event_name}` — the reachability root

Independent of build profile: default-`release` `.text` = 1,403,804 B; the spec
`[profile.release]` (`lto="fat"`, `opt-level="s"`, `panic="abort"`, `codegen-units=1`) =
1,440,988 B. LTO cannot strip it because the formatting code is genuinely reachable from the
JSON parser/trace layer.

### Root cause

Two independent defects, one latent:

1. **Float/u128 `core::fmt` + PAC `Debug` reachable from the firmware image.** The on-device
   JSON trace writer (PCDN-SOS-04-008/018) + `json_parser` pull in `core::num::flt2dec`,
   `core::num::dec2flt`, `core::fmt::num::exp_u128`, and the PAC `Interrupt` `Debug` impl. The
   SOS trace/event payloads are integer-only (`Tcb` fields are `i16`/`u8`/`i64`, SOS-04
   Amendment 001), so float formatting/parsing and 128-bit fmt are not semantically required —
   they are dragged in by generic `core::fmt`/number-parse paths and stray `{:?}`/`{}` uses.
   This was **latent**: bench bring-up (SOS-04 §15 baud-mismatch amendment, SOS-05 §15) flashed
   the **SOS-05 C port**, never the SOS-04 Rust port at full size, so the overflow went
   undiscovered. The historical 62 KB ELF predates the JSON/conformance machinery landing.

2. **Workspace `[profile.release]` missing.** `SOS-04-CONCEPTS.md §6.1` specifies
   `lto="fat"`, `opt-level="s"`, `codegen-units=1`, `panic="abort"`, and the `sos-m7-rust`
   crate `Cargo.toml` comment states these "belong at the workspace root" (cargo ignores
   `[profile.*]` in non-root workspace members). They were never landed in the root
   `Cargo.toml`. This alone does NOT cause the overflow (defect 1 dominates) but means the
   canonical build never ran with the intended size profile.

### Fix

- **Defect 2 (landed with this errata):** add `[profile.release]` (`lto="fat"`,
  `codegen-units=1`, `opt-level="s"`, `panic="abort"`) to the workspace root `Cargo.toml`.
  Necessary-not-sufficient; commit `<this commit>`.
- **Defect 1 (proposed; owner decision required — EOQ-001-ERRATA-008):** candidate paths —
  (a) **integer-only formatting audit** of `json_parser.rs` / `trace.rs` / `transport.rs`:
  replace any float/`u128`/`{:?}`-on-PAC formatting with integer (`itoa`-style) writers; MUST
  preserve the SOS-02 §7 trace wire format and SOS-03 INV-S-CONF-1 byte-equality (verify
  against `conformance/` vectors); expected to bring `.text` well under 1 MiB. (b)
  **feature-gate** the JSON conformance layer so it compiles only into the host
  `sos-m7-rust-tests` crate, not the flashable bin. (c) **enlarge the FLASH map** (dual-bank
  2 MiB) — revisits PCDN-SOS-04-012, least preferred (masks the bloat). Recommended: (a),
  falling back to (b) for any formatting genuinely needed only in conformance mode.

### Resolution (2026-06-02, path (a) integer-only formatting + dead-strip)

Defect 1 fixed by two complementary changes (no PAC removal, no wire-format change):

1. **Reachability cleanup** (`ports/m7-rust/sos-m7-rust-trace/src/lib.rs`,
   `src/{json_parser,main,disco_bsp,event,kernel,scripts}.rs`): the trace writer no longer
   uses `core::fmt::Write` (hand-rolled byte/integer emission via a `Result<(),()>` writer);
   firmware-side `#[derive(Debug)]` and `unwrap`/`expect`/`panic`-with-Debug sites replaced
   with `match`/park/error-return paths. This removes the reachability roots that pulled in
   the PAC `Debug` impls and the float/u128 `core::fmt` machinery.
2. **`--gc-sections`** (`ports/m7-rust/sos-m7-rust/build.rs` emits
   `cargo:rustc-link-arg=--gc-sections`): the linker dead-strips the now-unreachable PAC
   `Debug` + residual `core::fmt` float/u128 code.

The `stm32h7` PAC is retained and all peripheral register access is unchanged. A first
remediation attempt that removed the PAC and hand-rolled raw MMIO was rejected (out of scope;
spec §4-pinned dependency + bench-regression risk) and fully reverted.

### Verification

- Defect 2: `grep -A6 '\[profile.release\]' Cargo.toml` shows the block.
- Defect 1: `env -u RUSTFLAGS -u CARGO_ENCODED_RUSTFLAGS cargo build --target
  thumbv7em-none-eabihf --release -p sos-m7-rust` **links** within real 1024K FLASH.
  Section sizes (`llvm-size -A`): `.vector_table 664 + .text 64,704 + .rodata 13,736 +
  .data 1,496 = 80,600 B` resident (was `.text ≈ 1.44 MB`). PAC retained
  (`grep stm32h7 …/Cargo.toml`). Byte-equality / conformance preserved:
  `cargo test -p sos-m7-rust-tests` → 8 passed; `cargo test -p sos-conformance` → 6 passed;
  `cargo run --release -p sos-conformance -- run --suite conformance/vectors/` → 6/6 PASS.
- On-target bench verification (actual flash + UART trace) remains future work under DAA-08-C
  (this errata closes the build/size/host-conformance surface only).

### Diagnostic note (build-artifact footgun, not a code defect)

During remediation a stale `device.x` left in the firmware crate's cargo `OUT_DIR` (first on
the linker search path) shadowed the PAC-emitted `stm32h747cm7/device.x`, producing spurious
`rust-lld: undefined symbol: WWDG1/PVD_PVM/RCC/…` (`__INTERRUPTS`) link errors that masquerade
as a missing-vector-table bug. A clean checkout / `cargo clean -p sos-m7-rust` does not exhibit
it. No code change is owed for this; recorded here so a future session does not chase a
phantom "the Rust port never linked" defect.

### Tracking

- Surfaced during **DAA-08** cross-repo verification (the sibling disco-analyzer initiative;
  REQ-SOS-1 had assumed SOS-04 "exists" and is flashable). DAA-08-B depends on a flashable
  SOS-04 Rust port; this errata is on that critical path.
- `SOS-04-CONCEPTS.md §15` SHOULD carry a dated entry citing ERRATA-008 (the §6.1 profile now
  landed at the workspace root; the bloat remediation tracked here).
- Note (environment, not a SOS defect): the dev host's inherited `RUSTFLAGS`
  (`-Clink-arg=-fuse-ld=mold`) also breaks this cross-compile (`rust-lld: unknown argument
  '-fuse-ld=mold'`) and clobbers the crate-local target rustflags; build with `RUSTFLAGS`
  unset. Not part of this errata's fix scope.

## How to add an entry

1. File the issue on GitHub first. Capture symptom, reproducer, suspected scope.
2. Triage. If accepted, allocate the next sequential `ERRATA-NNN` id.
3. Add a row to the index above and a section below in this file, following the entry shape:

```
## ERRATA-NNN — <one-line title>

**Status:** 🔴 open / 🟡 diagnosed / 🟢 resolved / ⚪ deviation-pending-ratification
**First seen:** YYYY-MM-DD (HEAD at first sighting: <SHA>)
**Owning phase:** SOS-NN[-letter]

### Symptom
…pinned to HEAD at first-seen time with path:line citations…

### Root cause
…or "not yet diagnosed" if 🔴…

### Fix
…resolving commit SHA if landed; proposed location + minimal diff sketch otherwise…

### Verification
…how the fix was verified; "n/a" if not yet fixed…

### Tracking
…related phase docs, §15 entries that cite this errata…
```

4. If the entry is a stealth-revert candidate (a behaviour change walking back ratified-and-implemented content), follow the parent CLAUDE.md stealth-revert protocol: file the ERRATA entry FIRST in its own commit (status ⚪), THEN land the behaviour change citing the ERRATA id, THEN flip status.

5. If the entry intersects a §15 amendment, the phase doc's §15 entry SHOULD cite `ERRATA-NNN`, and this entry's **Tracking** field SHOULD reciprocate.
