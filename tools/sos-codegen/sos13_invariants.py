"""SOS-13 `INV-S-CHART-N` invariants series generator.

Per [SOS-13-CONCEPTS.md §8 + §8.1]
(../../docs/concepts/SOS-13-CONCEPTS.md) — the invariant-citation format
defines `INV-S-CHART-N` as the namespace owned by the codegen tool for
**chart-derived** invariants (distinct from `INV-S<N>` cross-port
invariants in SOS-00 and `INV-S-PORT-N` port-level invariants in
SOS-04). §8.1 prescribes the chart-derived series live in a generated
`invariants.rs` Rust source fragment with a companion human-readable
`INVARIANTS.md` mirror; the audit file (§7.4) cross-references entries
by id.

This module is the generator for those two artifacts plus a third in-
memory artifact: the *discharge registry*, mapping each
`<sos:discharged check="…"/>` site (per [SOS-13 §7.5]) back to the
`INV-S-CHART-N` it discharges. The registry is the bridge between the
chart-side `<sos:discharged>` annotations (§7.5 frozen grammar) and the
chart-derived invariant numbering — it gives the future
`transliterate_rust.py` `--profile verified-strip` SAFETY-comment
generator a stable lookup from a discharge site to the cite-string to
embed.

Concretizes [INV-SOS-G](../../docs/concepts/SOS-07-CONCEPTS.md): every
chart-derived invariant carries its originating chart path so the
SAFETY comment emitted later can cite both the invariant id AND the
chart site that proves it — eliminating silent strips by construction.

## Authority boundary

- The `<sos:discharged>` element grammar (`check` attribute, the frozen
  four-value enumeration `bounds | div-by-zero | null | overflow`) is
  ratified in SOS-13 §7.5 and MUST NOT be invented or extended by this
  module. We accept only those four values.
- The `INV-S-CHART-N` id format is ratified in SOS-13 §8.1; this module
  owns the per-build numbering (1-based, monotonic in the order
  invariants are declared by the bounds-analysis pass).
- The Rust source-comment shape (`// SAFETY: <id> — <rationale> (proved
  at <chart-site>).`) is ratified in SOS-13 §8; this module's
  `invariants.rs` carries the rationale text via the `cite()` lookup.

## Public surface

    BoundsAnalysisInput      — minimum chart-derived input fields.
    InvariantSpec            — one chart-derived invariant record.
    DischargeAnnotation      — one `<sos:discharged>` site record.
    InvariantsArtifacts      — (rust_source, markdown, registry) bundle.
    generate_invariants(...) — pure function: input → artifacts.

## Integration note — `BoundsAnalysisInput` shape

The bounds-analysis pass that produces `BoundsAnalysisInput` is the
SOS-02 host simulator's bounded-reachability layer + the SOS-03 vector
schema. Neither phase has stabilised the in-memory IR shape this
generator consumes; pending that stabilisation, this module defines
`BoundsAnalysisInput` as a small dataclass with the minimum fields the
artifact generation needs:

  * `chart_id`        — opaque identifier for the chart (e.g. its sha
                        or a filename stem); recorded in the audit
                        cross-reference but does not affect output
                        beyond the header comment.
  * `invariants`      — sequence of `InvariantSpec` rows. The order
                        determines the `INV-S-CHART-N` numbering — the
                        bounds-analysis pass is responsible for emitting
                        invariants in a stable order across runs (so the
                        ids do not churn build-to-build for unchanged
                        charts).
  * `discharges`      — sequence of `DischargeAnnotation` rows. Each
                        names the chart state where a `<sos:discharged>`
                        annotation was parsed and the `check` value.

When the SOS-02 / SOS-03 in-memory IR stabilises, the bridge from that
IR to this dataclass lives in a SOS-02/SOS-03 integration commit; this
module's surface does not change.

## Frozen enum

`RECOGNIZED_CHECKS` mirrors SOS-13 §7.5's frozen four-value
enumeration. Adding a value requires a Standards Action §15 amendment
to SOS-13 §7.5 first, then a coordinated update to this constant
(matching the policy already applied at `transliterate_rust.py`'s
`RECOGNIZED_DISCHARGES`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence


# -----------------------------------------------------------------
# Frozen enumeration — SOS-13 §7.5
# -----------------------------------------------------------------

# The four `<sos:discharged check="…"/>` values ratified at SOS-13 v1.
# Mirrored from `transliterate_rust.py`'s `RECOGNIZED_DISCHARGES`;
# kept duplicated here so this module is import-cycle-free and can be
# consumed by Wave-3 callers that import only this module.
RECOGNIZED_CHECKS: frozenset[str] = frozenset(
    {"bounds", "div-by-zero", "null", "overflow"}
)


# Map a `check` value to the VS-OP family it discharges, per the §7.5
# table. `div-by-zero` and `overflow` map to the deferred arithmetic
# VS-OP slot (no `VS-OP-N` id is assigned yet per §7.2); we record the
# discharge intent now so chart authoring can stabilise ahead of the
# arithmetic-intrinsic amendment.
CHECK_TO_VS_OPS: dict[str, tuple[str, ...]] = {
    "bounds": ("VS-OP-1",),
    "null": ("VS-OP-2", "VS-OP-3"),
    "div-by-zero": (),  # deferred arithmetic VS-OP
    "overflow": (),     # deferred arithmetic VS-OP
}


# Valid status values for an `InvariantSpec`. See module docstring for
# semantics.
VALID_STATUSES: frozenset[str] = frozenset(
    {"derived", "declared", "discharged"}
)


# -----------------------------------------------------------------
# Input dataclasses
# -----------------------------------------------------------------


@dataclass(frozen=True)
class InvariantSpec:
    """One chart-derived invariant.

    Attributes:
        text:        Human-readable invariant statement (≤ 100 chars
                     recommended; SOS-13 §8 names the rationale field as
                     "one-line"). Embedded as the Rust constant's value
                     and the markdown row's "Text" cell.
        chart_site:  Chart location where the invariant is established
                     or maintained — `<state-or-transition-id>.<onentry
                     |onexit|guard>` form per SOS-13 §8.
        status:      One of `derived | declared | discharged`. `derived`
                     is the default — the invariant came out of the
                     bounds-analysis pass automatically. `declared` is
                     used when the chart author hand-asserted it.
                     `discharged` is reserved for the runtime
                     cross-reference: an invariant marked `discharged`
                     here is one that a `<sos:discharged>` annotation
                     refers to.
        bound_evidence:  Optional free-form note describing how the
                         bounds analysis discharges the invariant (e.g.
                         "tid is bounded by ready-queue scan, i ∈ [0,
                         MAX_TASKS)"). Mirrors the §7.4 audit-entry
                         `bound_evidence` field.
    """

    text: str
    chart_site: str
    status: str = "derived"
    bound_evidence: str = ""

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUSES:
            raise ValueError(
                f"InvariantSpec.status must be one of "
                f"{sorted(VALID_STATUSES)}; got {self.status!r}"
            )
        if not self.text.strip():
            raise ValueError("InvariantSpec.text MUST NOT be empty")
        if not self.chart_site.strip():
            raise ValueError("InvariantSpec.chart_site MUST NOT be empty")


@dataclass(frozen=True)
class DischargeAnnotation:
    """One `<sos:discharged check="…"/>` site parsed from the chart.

    Attributes:
        chart_state:  The state-id that hosts the annotation (or the
                      transition's owning state per §7.5 inheritance).
        check:        The discharge value — MUST be in
                      `RECOGNIZED_CHECKS`.
        discharges_invariant:
                      The `INV-S-CHART-N` id this annotation discharges.
                      Optional at input time — the generator MAY fill it
                      in by matching the chart_state against invariants
                      whose chart_site shares the same state-id prefix.
                      If specified explicitly, the generator records it
                      verbatim (the bounds-analysis pass may have richer
                      knowledge than a prefix match).
    """

    chart_state: str
    check: str
    discharges_invariant: str = ""

    def __post_init__(self) -> None:
        if self.check not in RECOGNIZED_CHECKS:
            raise ValueError(
                f"DischargeAnnotation.check must be one of "
                f"{sorted(RECOGNIZED_CHECKS)} (SOS-13 §7.5 frozen "
                f"enumeration); got {self.check!r}"
            )
        if not self.chart_state.strip():
            raise ValueError(
                "DischargeAnnotation.chart_state MUST NOT be empty"
            )


@dataclass(frozen=True)
class BoundsAnalysisInput:
    """Minimum input shape for `generate_invariants`.

    Pending the SOS-02 / SOS-03 IR stabilisation, this dataclass is the
    contract surface — bounds-analysis producers populate it; the
    generator consumes it.

    Attributes:
        chart_id:    Opaque identifier for the chart (filename stem,
                     content sha, etc.). Recorded in the artifact header
                     but does not influence numbering.
        invariants:  Stable-ordered sequence of `InvariantSpec` rows.
                     Order determines the `INV-S-CHART-N` ids (1-based,
                     monotonic).
        discharges:  Sequence of `DischargeAnnotation` rows from the
                     `<sos:discharged>` scan of the chart.
    """

    chart_id: str = ""
    invariants: tuple[InvariantSpec, ...] = ()
    discharges: tuple[DischargeAnnotation, ...] = ()

    @classmethod
    def from_lists(
        cls,
        chart_id: str = "",
        invariants: Iterable[InvariantSpec] | None = None,
        discharges: Iterable[DischargeAnnotation] | None = None,
    ) -> "BoundsAnalysisInput":
        """Convenience factory accepting any iterables; freezes them
        into tuples for the frozen dataclass."""
        return cls(
            chart_id=chart_id,
            invariants=tuple(invariants or ()),
            discharges=tuple(discharges or ()),
        )


# -----------------------------------------------------------------
# Output dataclass
# -----------------------------------------------------------------


@dataclass(frozen=True)
class InvariantsArtifacts:
    """The triple `generate_invariants` returns.

    Attributes:
        rust_source:  Contents of `invariants.rs` (the generated Rust
                      module). Includes:
                        * One `pub const INV_S_CHART_N: &str = "…";` per
                          invariant.
                        * A `pub fn cite(id: &str) -> &'static str`
                          dispatch returning the invariant text (or the
                          empty string for an unknown id — Wave-3 should
                          NOT panic here, since `verified-strip`'s whole
                          point is to remove panic surfaces).
        markdown:     Contents of `INVARIANTS.md` (human-readable
                      mirror) — one section per invariant with the id,
                      text, originating chart-site, and status.
        registry:     `dict[str, list[str]]` mapping each
                      `<sos:discharged>` site's owning chart-state to
                      the list of `INV-S-CHART-N` ids it discharges.
                      The key shape is `<state>:<check>` so a single
                      state declaring multiple checks produces multiple
                      registry entries.
    """

    rust_source: str
    markdown: str
    registry: dict[str, list[str]]


# -----------------------------------------------------------------
# Generator
# -----------------------------------------------------------------


def _invariant_id(idx: int) -> str:
    """1-based numbering per SOS-13 §8.1 (`INV-S-CHART-1`,
    `INV-S-CHART-2`, …)."""
    if idx < 1:
        raise ValueError("INV-S-CHART-N id index must be 1-based")
    return f"INV-S-CHART-{idx}"


def _invariant_const_name(idx: int) -> str:
    """Rust const name for the `INV-S-CHART-N` constant. The leading
    `INV_S_CHART_` prefix matches the documented format; the Rust
    convention SCREAMING_SNAKE_CASE is preserved."""
    return f"INV_S_CHART_{idx}"


def _escape_rust_string(s: str) -> str:
    """Escape `s` for inclusion in a Rust `&str` literal between double
    quotes. Handles `\\`, `"`, and bare control bytes; leaves printable
    non-ASCII alone (Rust source is UTF-8)."""
    out = []
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20:
            out.append(f"\\x{ord(ch):02x}")
        else:
            out.append(ch)
    return "".join(out)


def _emit_rust_header(chart_id: str, count: int) -> str:
    """Top-of-file doc comment for `invariants.rs`."""
    parts = [
        "// SOS-13 chart-derived invariant series — generated.",
        "//",
        "// This file is generated by `tools/sos-codegen/sos13_invariants.py`",
        "// from the chart's bounds-analysis output. Do NOT edit by hand;",
        "// re-run the codegen against an updated chart instead.",
        "//",
        "// Authority: SOS-13-CONCEPTS.md §8 (invariant-citation format),",
        "// §8.1 (the `INV-S-CHART-N` series convention), and",
        "// SOS-07-CONCEPTS.md INV-SOS-G (verified-codegen position).",
        "//",
    ]
    if chart_id:
        parts.append(f"// Chart: {chart_id}")
    parts.append(f"// Invariant count: {count}")
    parts.append("")
    parts.append("#![allow(dead_code, non_upper_case_globals)]")
    parts.append("")
    return "\n".join(parts)


def _emit_rust_const(idx: int, spec: InvariantSpec) -> str:
    """Single `pub const INV_S_CHART_<idx>` declaration with a
    documentation comment describing the chart-site origin + status."""
    name = _invariant_const_name(idx)
    iid = _invariant_id(idx)
    lines = [
        f"/// {iid}  (status: {spec.status})",
        f"/// Chart site: {spec.chart_site}",
    ]
    if spec.bound_evidence:
        lines.append(f"/// Bound evidence: {spec.bound_evidence}")
    lines.append(
        f'pub const {name}: &str = "{_escape_rust_string(spec.text)}";'
    )
    return "\n".join(lines)


def _emit_rust_cite_fn(specs: Sequence[InvariantSpec]) -> str:
    """`pub fn cite(id: &str) -> &'static str` returning the invariant
    text for a known `INV-S-CHART-N` id, or `""` for an unknown id.

    Wave-3's SAFETY-comment generator uses this for runtime lookup of
    the rationale text when emitting `unsafe { ... }` blocks. The empty-
    string default is intentional: panicking inside the lookup would
    re-introduce a panic surface exactly where `verified-strip`'s job is
    to remove them.
    """
    lines = [
        "/// Look up the human-readable text for an `INV-S-CHART-N` id.",
        "///",
        "/// Returns the empty string for an unknown id. Callers under",
        "/// `--profile verified-strip` MUST NOT panic on lookup failure",
        "/// (per SOS-13 §8 — citing-format integrity is a soft fail at",
        "/// the SAFETY-comment surface, not a runtime panic).",
        "pub fn cite(id: &str) -> &'static str {",
        "    match id {",
    ]
    for i, _spec in enumerate(specs, start=1):
        iid = _invariant_id(i)
        name = _invariant_const_name(i)
        lines.append(f'        "{iid}" => {name},')
    lines.append('        _ => "",')
    lines.append("    }")
    lines.append("}")
    return "\n".join(lines)


def _emit_rust_source(input_: BoundsAnalysisInput) -> str:
    """Top-level Rust source assembler."""
    specs = input_.invariants
    header = _emit_rust_header(input_.chart_id, len(specs))
    if not specs:
        # Empty-suite case — still emit the cite() function so the
        # Wave-3 transliterator can compile against a known surface.
        return (
            header
            + _emit_rust_cite_fn(())
            + "\n"
        )
    blocks = [_emit_rust_const(i, s) for i, s in enumerate(specs, start=1)]
    body = "\n\n".join(blocks)
    cite_fn = _emit_rust_cite_fn(specs)
    return header + body + "\n\n" + cite_fn + "\n"


def _emit_markdown_header(chart_id: str, count: int) -> str:
    """Top of `INVARIANTS.md`."""
    lines = [
        "# `INV-S-CHART-N` series — generated",
        "",
        "Per [SOS-13-CONCEPTS.md §8.1]"
        "(../docs/concepts/SOS-13-CONCEPTS.md), this file is the human-",
        "readable mirror of `invariants.rs`. The codegen tool emits both",
        "from the chart's bounds-analysis output; do NOT edit by hand.",
        "",
        "Authority: [SOS-07 INV-SOS-G]"
        "(../docs/concepts/SOS-07-CONCEPTS.md) — the verified-codegen",
        "position — and [SOS-13 §8](../docs/concepts/SOS-13-CONCEPTS.md)",
        "for the invariant-citation format.",
        "",
    ]
    if chart_id:
        lines.append(f"- **Chart:** `{chart_id}`")
    lines.append(f"- **Invariant count:** {count}")
    lines.append("")
    return "\n".join(lines)


def _emit_markdown_invariant(idx: int, spec: InvariantSpec) -> str:
    """One `## INV-S-CHART-N` section in the markdown mirror."""
    iid = _invariant_id(idx)
    lines = [
        f"## {iid}",
        "",
        f"- **Text:** {spec.text}",
        f"- **Chart site:** `{spec.chart_site}`",
        f"- **Status:** `{spec.status}`",
    ]
    if spec.bound_evidence:
        lines.append(f"- **Bound evidence:** {spec.bound_evidence}")
    lines.append("")
    return "\n".join(lines)


def _emit_markdown_registry(registry: dict[str, list[str]]) -> str:
    """Trailing `## Discharge registry` section listing every
    `<sos:discharged>` site's invariant mapping."""
    if not registry:
        return (
            "## Discharge registry\n\n"
            "_No `<sos:discharged>` annotations parsed from the chart._\n"
        )
    lines = [
        "## Discharge registry",
        "",
        "Each row records a `<sos:discharged check=\"…\"/>` annotation "
        "(SOS-13 §7.5)",
        "and the `INV-S-CHART-N` invariant(s) it discharges.",
        "",
        "| Chart state | Check | Discharges |",
        "|---|---|---|",
    ]
    for key in sorted(registry.keys()):
        state, _, check = key.partition(":")
        invs = ", ".join(registry[key]) if registry[key] else "_(none)_"
        lines.append(f"| `{state}` | `{check}` | {invs} |")
    lines.append("")
    return "\n".join(lines)


def _emit_markdown(input_: BoundsAnalysisInput, registry: dict[str, list[str]]) -> str:
    """Top-level markdown assembler."""
    specs = input_.invariants
    header = _emit_markdown_header(input_.chart_id, len(specs))
    if not specs:
        return header + "_No chart-derived invariants for this build._\n\n" + \
            _emit_markdown_registry(registry)
    body_parts = [_emit_markdown_invariant(i, s) for i, s in enumerate(specs, start=1)]
    return header + "\n".join(body_parts) + "\n" + _emit_markdown_registry(registry)


def _build_registry(
    input_: BoundsAnalysisInput,
) -> dict[str, list[str]]:
    """Build the `<state>:<check>` → `[INV-S-CHART-N, ...]` mapping.

    Match policy:
      1. If a `DischargeAnnotation` carries `discharges_invariant`
         explicitly (set by the bounds-analysis pass when it knows the
         binding precisely), trust that string verbatim.
      2. Otherwise, fall back to a chart-site prefix match: any
         `InvariantSpec` whose `chart_site` starts with
         `<chart_state>.` is considered discharged by the annotation.

    The fallback is conservative — if the bounds analysis cannot bind
    the discharge precisely, the registry MAY map a single discharge to
    multiple invariants. That is acceptable: it never under-counts (the
    `verified-strip` audit log can still cross-reference), and the
    explicit `discharges_invariant` path lets a richer producer narrow
    it later.
    """
    specs = input_.invariants
    # Pre-build a `state → [INV-S-CHART-N, ...]` index for fallback
    # matching. The state prefix is the slice of chart_site before the
    # first `.` (`sched_dispatch.onentry` → `sched_dispatch`).
    state_to_invs: dict[str, list[str]] = {}
    for i, spec in enumerate(specs, start=1):
        state = spec.chart_site.split(".", 1)[0]
        state_to_invs.setdefault(state, []).append(_invariant_id(i))

    registry: dict[str, list[str]] = {}
    for ann in input_.discharges:
        key = f"{ann.chart_state}:{ann.check}"
        if ann.discharges_invariant:
            registry.setdefault(key, []).append(ann.discharges_invariant)
        else:
            matches = state_to_invs.get(ann.chart_state, [])
            # Deduplicate while preserving order in case multiple
            # discharges map to the same state.
            existing = registry.setdefault(key, [])
            for iid in matches:
                if iid not in existing:
                    existing.append(iid)
            # Even with no matches we still record the key so the
            # registry surfaces orphan discharges to the reviewer.
            if not matches and key not in registry:
                registry[key] = []
    return registry


def generate_invariants(
    bounds_input: BoundsAnalysisInput,
) -> InvariantsArtifacts:
    """Pure function: bounds-analysis → (rust_source, markdown, registry).

    No I/O — caller writes the artifacts to disk. This separation lets
    the same function back the codegen CLI and the unit-test suite.
    """
    if not isinstance(bounds_input, BoundsAnalysisInput):
        raise TypeError(
            "generate_invariants() expects a BoundsAnalysisInput; got "
            f"{type(bounds_input).__name__}"
        )
    registry = _build_registry(bounds_input)
    return InvariantsArtifacts(
        rust_source=_emit_rust_source(bounds_input),
        markdown=_emit_markdown(bounds_input, registry),
        registry=registry,
    )


__all__ = [
    "BoundsAnalysisInput",
    "DischargeAnnotation",
    "InvariantSpec",
    "InvariantsArtifacts",
    "RECOGNIZED_CHECKS",
    "CHECK_TO_VS_OPS",
    "VALID_STATUSES",
    "generate_invariants",
]
