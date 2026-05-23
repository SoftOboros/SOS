# scxml-lint

The SOS-01 lint runner for `rtos_kernel.scxml`. Specified by
[`docs/concepts/SOS-01-CONCEPTS.md`](../../docs/concepts/SOS-01-CONCEPTS.md)
§6 / §7 / §8.

## Quick start

From the SOS subrepo root:

```bash
pip install -r tools/scxml-lint/requirements.txt
python tools/scxml-lint/main.py rtos_kernel.scxml
```

Exit codes (per SOS-01 §7.2):

| Exit | Meaning |
|---:|---|
| `0` | No `error`-severity findings. Warnings / info MAY be present on stdout. |
| `1` | One or more `error`-severity findings. CI rejects the PR. |
| `2` | Invocation or IO error (missing file, missing `lxml`). |

Output is GitHub Actions workflow annotations (`::error file=...,line=N::msg`,
`::warning ...`, `::notice ...` for info). One annotation per finding.

## Layout

```
tools/scxml-lint/
├── main.py                      # entry point + rule registry
├── requirements.txt             # lxml>=4.9
├── README.md                    # this file
└── rules/
    ├── __init__.py              # package marker
    ├── _common.py               # Finding dataclass, helpers
    ├── schema.py                # SCXML-LINT-001 (W3C XSD)
    ├── script_length.py         # SCXML-LINT-005 (<= 40 LOC cap)
    ├── ecmascript_subset.py     # SCXML-LINT-009 (forbidden constructs)
    ├── event_vocabulary.py      # SCXML-LINT-013 / -014 (ExternalEventName / StateId)
    ├── comment_density.py       # SCXML-LINT-010 / -015 (transition / state comments)
    └── reference_md_drift.py    # SCXML-LINT-017 / -018 (REFERENCE.md drift)
```

## Implemented vs TODO rules

This commit implements the load-bearing 7 rule modules
(SCXML-LINT-001, -005, -009, -010, -013, -014, -015, -017, -018 — nine
rule ids across seven modules). The remaining rule ids in the §6 set
(SCXML-LINT-002, -003, -004, -006, -007, -008, -011, -012, -016) are
listed as `TODO` entries in `main.py`'s rule registry and emit no
findings until implemented.

See [SOS-01-CONCEPTS.md §6](../../docs/concepts/SOS-01-CONCEPTS.md) for
the normative rule definitions and [§10](../../docs/concepts/SOS-01-CONCEPTS.md)
for the grace-period waivers each rule carries against the chart at HEAD.

## Adding a new rule

1. Reserve an `SCXML-LINT-NNN` id in SOS-01 §5.5 (`LintRuleId`) via a
   §15 amendment. Ids are append-only-with-retirement.
2. Create `rules/<rule>.py` exposing `check(tree, scxml_path) -> list[Finding]`
   (or `check(scxml_path, ...) -> list[Finding]` for non-tree-driven rules).
3. Register the call in `main.py`'s `run()`.
4. Add the new rule's TODO line to `main.py`'s docstring removed and the
   implementation noted in this README's "Implemented" list.

## Dependencies

Only `lxml>=4.9`. No other external deps. The runner targets Python 3.11
(matching the GitHub Actions runner in
[`.github/workflows/scxml-lint.yml`](../../.github/workflows/scxml-lint.yml))
but should run on 3.9+.
