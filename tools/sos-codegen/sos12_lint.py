"""SOS-12 chart-decomposition lint rules.

This module implements the **chart-validation-time lint surface** for the
two SOS-12 frozen thresholds:

- **SCXML-LINT-DISP-1 — dispatch-tree depth cap (error).** PCDN-SOS-12-005 /
  SOS-12-CONCEPTS.md §6.5 / §10.3. Walks the dispatch tree rooted at a
  given chart and rejects any chart whose maximum dispatch depth exceeds
  the configured cap. Default cap is `DEFAULT_MAX_DEPTH` (= 8) per
  PCDN-SOS-12-005 ratification. Projects MAY override per chart-family.
- **SCXML-LINT-DISP-2 — peer-state legibility threshold (error).**
  PCDN-SOS-12-003 / SOS-12-CONCEPTS.md §9 / §10.2. Counts peer states at
  each level of a chart and rejects any level whose peer-state count
  exceeds the configured threshold. Default threshold is
  `DEFAULT_LEGIBILITY_THRESHOLD` (= 15) per PCDN-SOS-12-003 ratification.
  The diagnostic's `message` MUST recommend `extract_region_to_subchart`
  (the SOS-11 §5.1 MCP tool) as the structural-add alternative — this is
  the operationalisation of SOS-12 §9 "the discipline becomes a property
  the tooling enforces".

Source-of-truth notes
---------------------

The DEPTH cap is ALSO enforced inside `tools/sos-codegen/sos12_bound.py`
at the bound-composition layer (Wave-1B). The lint rule SCXML-LINT-DISP-1
is a DIFFERENT entry point — a static-chart-only check that does NOT
require running the full bound-composition algorithm. The two checks
coexist intentionally:

- `sos12_bound.py` catches the same bug deeper in the pipeline at
  vector-emission time.
- `sos12_lint.py` (this module) catches it earlier at chart-validation
  time, with a diagnostic message scoped to the chart author rather than
  the vector emitter.

This module does NOT modify `sos12_bound.py`; the bound module stays a
downstream safety net.

Authority
---------

- `docs/concepts/SOS-12-CONCEPTS.md` §6.5 + §10.3 + PCDN-SOS-12-005 —
  recursion depth cap default 8.
- `docs/concepts/SOS-12-CONCEPTS.md` §9 + §10.2 + PCDN-SOS-12-003 —
  legibility threshold default 15 peer states.
- `docs/concepts/SOS-12-CONCEPTS.md` §9.2 — `extract_region_to_subchart`
  (SOS-11 §5.1) is the structural-add operation that SHOULD be invoked
  when the legibility threshold is reached.
- `docs/concepts/SOS-01-CONCEPTS.md` §5.5 / §15 (commit `4f33c1e`) —
  the `SCXML-LINT-DISP-N` category-prefix series reservation. SOS-01
  owns the `LintRuleId` namespace; this module fills the reservation.

Public surface
--------------

::

    check_dispatch_depth(chart_path: str | Path, *,
        max_depth: int = DEFAULT_MAX_DEPTH,
        loader: Callable[[Path], dict] | None = None,
    ) -> list[LintDiagnostic]

    check_legibility(chart_path: str | Path, *,
        legibility_threshold: int = DEFAULT_LEGIBILITY_THRESHOLD,
        loader: Callable[[Path], dict] | None = None,
    ) -> list[LintDiagnostic]

    LintDiagnostic — frozen dataclass; empty-list return means pass.

Each rule is a pure function over an scjson-shape chart dict (loaded via
the optional `loader` keyword or, by default, via `loader.load_chart`).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from sos12_annotations import (
    DEFAULT_MAX_DEPTH,
    Sos12AnnotationError,
    parse_dispatch_annotations,
)


# ---------------------------------------------------------------------------
# Frozen defaults — Specification Required registration policy per SOS-12
# §10.2 / §10.3. Projects MAY override per chart-family via the function
# keyword arguments (mirroring `chart-family.toml` overrides per §9.1 /
# §6.5).
# ---------------------------------------------------------------------------

# Per SOS-12-CONCEPTS §9.1 + §10.2 + PCDN-SOS-12-003 ratification.
DEFAULT_LEGIBILITY_THRESHOLD: int = 15

# Lint rule ids — SCXML-LINT-DISP-N series per SOS-01 §15 (commit
# `4f33c1e`) reservation. Standards Action: adding a value requires a
# §15 amendment to BOTH SOS-01 (the lint catalog) and SOS-12 (the
# semantics owner).
RULE_DISPATCH_DEPTH: str = "SCXML-LINT-DISP-1"
RULE_LEGIBILITY: str = "SCXML-LINT-DISP-2"


# ---------------------------------------------------------------------------
# Diagnostic dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LintDiagnostic:
    """One lint finding from a SOS-12 chart-validation rule.

    Shape mirrors the SOS-01 §6 lint-rule fields (id, severity, location,
    message). The `chart_path` field is the file the diagnostic pins to;
    `location` is a chart-author-readable identifier (a state id, a
    state-id path, or a chart filename) per INV-SOS-H (vector-to-chart
    traceability extended to lint diagnostics).

    `rule_id` is a `LintRuleId` per SOS-01 §5.5 (Standards Action); the
    DISP-N series is owned by SOS-12 per the reservation in SOS-01 §15
    commit `4f33c1e`.

    Severity is always "error" for both DISP-1 and DISP-2 — both rules
    enforce a frozen-threshold invariant whose breach is a hard
    correctness gate, not a stylistic suggestion.
    """

    rule_id: str
    severity: str
    chart_path: str
    location: str
    message: str


# ---------------------------------------------------------------------------
# scjson loader bridge
# ---------------------------------------------------------------------------


def _default_loader(path: Path) -> dict:
    """Default scjson loader for the lint surface.

    Lazy-imports `loader.load_chart` so this module remains importable in
    environments without scjson on PATH (e.g. unit tests that drive the
    rules with a synthetic loader for hermetic execution).
    """
    import importlib
    import sys as _sys

    here = Path(__file__).resolve().parent
    if str(here) not in _sys.path:
        _sys.path.insert(0, str(here))
    loader_mod = importlib.import_module("loader")
    ast_obj = loader_mod.load_chart(path)
    raw = ast_obj.raw_scjson
    if raw is None:
        raise RuntimeError(
            f"loader.load_chart({path}) returned no raw_scjson payload"
        )
    return raw


# ---------------------------------------------------------------------------
# SCXML-LINT-DISP-1 — dispatch-tree depth cap (§6.5 / PCDN-SOS-12-005)
# ---------------------------------------------------------------------------


def check_dispatch_depth(
    chart_path: str | Path,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
    loader: Optional[Callable[[Path], dict]] = None,
) -> list[LintDiagnostic]:
    """Run SCXML-LINT-DISP-1 against a chart and its dispatch tree.

    Walks the dispatch tree rooted at ``chart_path`` using the SOS-12
    annotation parser; rejects any chart whose maximum dispatch depth
    exceeds ``max_depth``. The default ``max_depth`` is the SOS-12 §6.5 /
    PCDN-SOS-12-005 ratified value (8); projects MAY override via the
    keyword argument (mirroring per-chart-family overrides per §10.3).

    Returns:
        ``list[LintDiagnostic]`` — empty list on pass, one diagnostic on
        first depth-cap breach. The annotation parser raises on the
        first overflow encountered (per its own §6.5 cap enforcement),
        so this function surfaces at most one diagnostic per chart.

    Raises:
        FileNotFoundError if ``chart_path`` does not exist.
        RuntimeError if scjson loading fails (re-raised from the loader).

    Note:
        The depth-cap is ALSO enforced inside ``sos12_bound.py`` (Wave-1B
        bound-composition module) at vector-emission time. This rule
        exists as the earlier, chart-author-facing entry point that does
        NOT require running the bound composition; the two checks
        coexist by design (see module docstring).
    """
    cp = Path(chart_path)
    if not cp.exists():
        raise FileNotFoundError(f"chart not found: {cp}")
    if loader is None:
        loader = _default_loader
    ast = loader(cp)

    diagnostics: list[LintDiagnostic] = []

    try:
        parse_dispatch_annotations(
            ast, chart_path=cp, max_depth=max_depth, loader=loader,
        )
    except Sos12AnnotationError as exc:
        # The parser surfaces the depth-cap overrun via the §6.5 rule
        # token. Translate to a lint diagnostic whose message stays in
        # chart-author vocabulary (per INV-SOS-H) and cites the spec
        # section, the configured cap, and the offending location.
        if exc.rule != "§6.5":
            # Any other parser error is propagated — it is not a
            # depth-cap finding for this lint rule, and pretending to
            # handle it would mask a different chart-author bug.
            raise
        location = exc.element_path or str(cp)
        diagnostics.append(
            LintDiagnostic(
                rule_id=RULE_DISPATCH_DEPTH,
                severity="error",
                chart_path=str(cp),
                location=location,
                message=(
                    f"[{RULE_DISPATCH_DEPTH}] chart {cp.name!r} dispatch-tree "
                    f"depth exceeds max_depth={max_depth} at {location}. "
                    f"SOS-12 §6.5 / PCDN-SOS-12-005 caps dispatch recursion "
                    f"at {DEFAULT_MAX_DEPTH} levels by default; projects MAY "
                    f"override per chart-family. The deeper the dispatch "
                    f"tree, the more likely it is an accidental cycle through "
                    f"the inline_subchart / extract_region_to_subchart "
                    f"round-trip (SOS-11 §5.1) rather than a deliberate "
                    f"protocol decomposition."
                ),
            )
        )

    return diagnostics


# ---------------------------------------------------------------------------
# SCXML-LINT-DISP-2 — peer-state legibility threshold (§9 / PCDN-SOS-12-003)
# ---------------------------------------------------------------------------


def _peer_children(node: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the immediate peer-state children of an scjson node.

    "Peer states" at a level means the union of `<state>` and `<parallel>`
    elements that share an immediate parent. The scjson shape carries
    these in two parallel lists; we concatenate so a node with three
    `<state>` and one `<parallel>` child reports four peers.

    Note on `<parallel>` regions: a `<parallel>` element's own children
    (the regions) are themselves peer states **at the next level down**,
    not at the parallel's parent's level. This function returns only the
    immediate children of the given node, so the recursive caller in
    `check_legibility` walks each `<parallel>` separately and counts its
    region children against the threshold at the parallel's own level.
    """
    children: list[dict[str, Any]] = []
    for kind in ("state", "parallel"):
        sub = node.get(kind) or []
        if isinstance(sub, list):
            for child in sub:
                if isinstance(child, dict):
                    children.append(child)
    return children


def _location_path(prefix: str, node_id: Optional[str], kind: str) -> str:
    """Build a chart-author-readable location string for a level.

    `prefix` is the dotted path of ancestor ids; `node_id` is the current
    node's id (None for the chart root); `kind` is "scxml"/"state"/
    "parallel" naming what kind of node owns the level.
    """
    if node_id is None:
        return f"<{kind}>"
    if prefix:
        return f"{prefix}.{node_id}"
    return node_id


def check_legibility(
    chart_path: str | Path,
    *,
    legibility_threshold: int = DEFAULT_LEGIBILITY_THRESHOLD,
    loader: Optional[Callable[[Path], dict]] = None,
) -> list[LintDiagnostic]:
    """Run SCXML-LINT-DISP-2 against a chart's peer-state inventory.

    Walks the chart tree and reports any level whose peer-state count
    exceeds ``legibility_threshold``. The default threshold is the
    SOS-12 §9.1 / PCDN-SOS-12-003 ratified value (15 peer states);
    projects MAY override via the keyword argument (mirroring
    per-chart-family overrides per §9.1 / §10.2).

    Each diagnostic's ``message`` MUST recommend
    ``extract_region_to_subchart`` (the SOS-11 §5.1 MCP tool) — this is
    the operationalisation of SOS-12 §9 ("discipline becomes a property
    the tooling enforces"). The recommendation is normative per the
    SOS-12 §9.2 tool-surface behaviour requirement.

    Returns:
        ``list[LintDiagnostic]`` — empty list on pass; one diagnostic
        per level that breaches the threshold (a chart with three
        offending levels yields three diagnostics, in document order).

    Raises:
        FileNotFoundError if ``chart_path`` does not exist.
        RuntimeError if scjson loading fails (re-raised from the loader).
        ValueError if ``legibility_threshold`` < 1.

    Counting semantics:
        Peer states at a level = immediate `<state>` + `<parallel>`
        children of the level's owner node. The chart root (`<scxml>`)
        owns the top-level peers; each `<state>` / `<parallel>` owns its
        own peers in turn. A `<parallel>` with N region children
        contributes N peers to its **own** level (each region is a peer
        state of the parallel's other regions). Each region's children
        are counted at the next level down via recursion.
    """
    if legibility_threshold < 1:
        raise ValueError(
            f"legibility_threshold must be ≥ 1, got {legibility_threshold}"
        )
    cp = Path(chart_path)
    if not cp.exists():
        raise FileNotFoundError(f"chart not found: {cp}")
    if loader is None:
        loader = _default_loader
    ast = loader(cp)

    diagnostics: list[LintDiagnostic] = []

    def _walk(node: dict[str, Any], prefix: str, node_id: Optional[str], kind: str) -> None:
        peers = _peer_children(node)
        peer_count = len(peers)
        if peer_count > legibility_threshold:
            location = _location_path(prefix, node_id, kind)
            diagnostics.append(
                LintDiagnostic(
                    rule_id=RULE_LEGIBILITY,
                    severity="error",
                    chart_path=str(cp),
                    location=location,
                    message=(
                        f"[{RULE_LEGIBILITY}] {location} has {peer_count} "
                        f"peer states at one level; SOS-12 §9 / "
                        f"PCDN-SOS-12-003 limit is {legibility_threshold}. "
                        f"Consider `extract_region_to_subchart` (SOS-11 §5.1) "
                        f"to split the level into a parent + sub-chart pair; "
                        f"the structural-add operation is the only admissible "
                        f"path past the threshold per SOS-12 §9.2."
                    ),
                )
            )
        next_prefix = _location_path(prefix, node_id, kind) if node_id else prefix
        for child in peers:
            child_id = child.get("id")
            # Decide whether the child is a parallel by checking which
            # list it came from. Re-derive cheaply: a node with regions
            # of its own (parallel) carries `state` children that are
            # the regions; we treat both kinds uniformly for recursion.
            child_kind = "parallel" if child.get("parallel") or child.get("state") else "state"
            # Distinguish kind for diagnostic location naming only when
            # the node is the chart root or anonymous; otherwise the id
            # is sufficient.
            _walk(child, next_prefix, str(child_id) if child_id else None, child_kind)

    _walk(ast, prefix="", node_id=None, kind="scxml")

    return diagnostics


__all__ = [
    "DEFAULT_LEGIBILITY_THRESHOLD",
    "DEFAULT_MAX_DEPTH",
    "LintDiagnostic",
    "RULE_DISPATCH_DEPTH",
    "RULE_LEGIBILITY",
    "check_dispatch_depth",
    "check_legibility",
]
