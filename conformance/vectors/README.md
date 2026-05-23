# `conformance/vectors/`

Conformance vector suite ratified by
[SOS-03](../../docs/concepts/SOS-03-CONCEPTS.md).

## Layout

```
vectors/
├── smoke/        — core-surface vectors (SOS-03 §5.1)
├── boundary/     — edge-case vectors (SOS-03 §5.1)
├── stress/       — volume / interleaving vectors (SOS-03 §5.1)
├── regression/   — vectors mined from resolved ERRATA entries (SOS-03 §5.1)
├── diversity/    — port-specific corner-case vectors (SOS-03 §5.1)
└── retired/      — retired vectors per INV-S-CONF-6 (default scan excludes)
```

Each category subtree numbers its vectors with its own zero-padded
sequential id namespace: `smoke/0001-...` and `boundary/0001-...` are
distinct vectors. The full filename is `<NNNN>-<slug>.json` where
`<slug>` is mechanically derived from the fixture's `name` field per
SOS-03 §6.3.

## Adding a vector

The registration policy depends on the category (SOS-03 §5.1):

- **Smoke** — **Standards Action**. Adding requires a §15 amendment to
  `SOS-03-CONCEPTS.md`.
- **Boundary**, **Stress**, **Regression** — **Specification Required**.
  PR-level review citing SOS-03 §6.2 (schema) and §7.5
  (expansion-policy checklist). No §15 amendment.
- **Diversity** — **Expert Review**. Phase-owner MAY add with a PR-level
  note.

The vector file format (JSON schema, naming convention, `from_tid`
semantics, diff-comparison policy, seed-suite mapping) lives in
[SOS-03 §6](../../docs/concepts/SOS-03-CONCEPTS.md#6-vector-file-format).
The `expected_trace` half is **committed-by-author** per PCDN-SOS-03-003
— the author runs `sos-sim` once over the input and commits the result;
INV-S-CONF-3 forbids manual hand-authoring.

## See also

- [`SOS-03-CONCEPTS.md`](../../docs/concepts/SOS-03-CONCEPTS.md) §5
  (frozen enums), §6 (vector file format), §7 (harness behaviour),
  §9 (invariants).
- [`SOS-00-CONCEPTS.md`](../../docs/concepts/SOS-00-CONCEPTS.md) §7.4
  (seed-vector list).
- [`SOS-01-CONCEPTS.md`](../../docs/concepts/SOS-01-CONCEPTS.md) §5.3
  (`ExternalEventName` — the closed event vocabulary `input` arrays draw
  from).
