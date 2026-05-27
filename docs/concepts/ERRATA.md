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

*(none open — ERRATA-001, -002, -003 all resolved at intake.)*

## Status of this log

ERRATA is now actively used. SOS-00 ratified 2026-05-19; every subsequent phase (SOS-04 through SOS-13, including the SOS-08 / SOS-09 sub-phase families) carries its own §15 / §16 amendment surface. ERRATA accumulates the deviations and pre-existing bugs that need cross-session memory — execution drift discovered after ratification, stealth renames between concepts-doc cites and as-built filenames, and implicit invariants made explicit during cleanup waves. Per parent CLAUDE.md "stealth-revert prohibition": revert-shaped behaviour changes file an ERRATA entry FIRST in their own commit; this log is the institutional record those entries live in.

## Entry index

| ID | Status | Title | First seen | Owning phase |
|---|---|---|---|---|
| ERRATA-001 | 🟢 | SOS-09-B implementation cite mismatch (stealth rename `svd_emit.py` → `transliterate_svd.py`) | 2026-05-27 | SOS-09-B |
| ERRATA-002 | 🟢 | SOS-09-G implementation cite mismatch (stealth rename `mpu_emit.py` → `transliterate_mpu.py`) + missing SOS09G1 §16 entry | 2026-05-27 | SOS-09-G |
| ERRATA-003 | 🟢 | wave-7 same-region-only writer RHS constraint hardened from implicit to explicit | 2026-05-25 | SOS-08-C |

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
