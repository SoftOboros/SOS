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

*(none yet — SOS-00 is still in draft, so all open items live as PCDN-SOS-00-NNN in `SOS-00-CONCEPTS.md` §15 staging, not here. Errata begins accumulating once SOS-00 ratifies.)*

## Entry index

| ID | Status | Title | First seen | Owning phase |
|---|---|---|---|---|
| *(none yet)* | | | | |

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
