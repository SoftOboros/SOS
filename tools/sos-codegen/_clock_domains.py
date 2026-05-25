"""SOS-08-D wave-7a (2026-05-25 §15) — `<sos:clock_domains>` parser
+ alias-resolution helper.

Shared between ``transliterate_sva_bind.py`` (D-side walker, this wave)
and ``transliterate_hdl_sv_tb.py`` (E-side walker, wave-7b).  Per the
spec-before-code discipline (see SOS-08-D §15 2026-05-25 ratification
entry ``PCDN-SOS-08-D-008 ratification``), the chart-vocab element
``<sos:clock_domains>`` carries one or more ``<sos:clock>`` declarations
with the source × kind orthogonal identity model.

Authority boundary (per the SOS-08-D §0 declaration):
  * ``<sos:clock>`` element shape (``name=``, ``source=``, ``kind=``,
    ``period_ns=``, ``duty_cycle=``, ``phase_ns=``) — relationship
    **own** (this repo authors the convention).
  * Source × kind orthogonal identity model + alphabetic-first
    canonical-name rule — relationship **own** (this repo authors).
  * Kind enum (``rising``, ``falling`` at v1; reserved future values
    ``both``/``quadrature_pair``/``three_phase``/``waltz``) —
    registration policy **Standards Action** per SOS-08-D §15.
  * Sampling-clock kind inheritance from the referenced
    ``<sos:clock>`` — relationship **own**.

Public API consumed by both walkers:

  * ``ClockDecl`` dataclass — frozen, hashable; one per
    ``<sos:clock>`` element.
  * ``parse_clock_domains(chart_xml) -> dict[str, ClockDecl]`` — chart-
    level entry point. Returns ``{name: ClockDecl}``.  Absent block
    yields the implicit default clock (``clk``/``chart_root``/``rising``).
  * ``canonical_name_for_pair(source, kind, clock_map)`` — alphabetic-
    first name among aliases sharing ``(source, kind)``.
  * ``resolve_alias(name, clock_map) -> (canonical_name, source, kind)``.
  * ``pair_of(name, clock_map) -> (source, kind)``.
  * ``validate_kind(kind)`` — raises ``UnsupportedClockKindError`` for
    reserved future kinds; no-op for supported kinds.
  * ``implicit_default_clock()`` — the implicit default ``ClockDecl``.

Backward-compatibility (MUST, per §15): charts without
``<sos:clock_domains>`` block produce the implicit default clock map
``{"clk": ClockDecl(name="clk", source="chart_root", kind="rising",
period_ns=10.0, duty_cycle=0.5, phase_ns=0.0)}``.  Wave-1 charts emit
byte-identical under this contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Kind enum (Standards Action per SOS-08-D §15 2026-05-25 ratification).
# ---------------------------------------------------------------------------

KIND_RISING = "rising"
KIND_FALLING = "falling"

#: Kinds the walker emits today.  ``rising`` → ``@(posedge clk)``;
#: ``falling`` → ``@(negedge clk)``.
SUPPORTED_KINDS: frozenset[str] = frozenset({KIND_RISING, KIND_FALLING})

#: Kinds reserved by §15 for future PCDNs (DDR / quadrature / three-
#: phase / waltz arbitrary-meter).  Parsing a chart that declares one
#: of these raises ``UnsupportedClockKindError``.
RESERVED_KINDS: frozenset[str] = frozenset({
    "both",
    "quadrature_pair",
    "three_phase",
    "waltz",
})


# ---------------------------------------------------------------------------
# Error surface.
# ---------------------------------------------------------------------------


class UnsupportedClockKindError(Exception):
    """Raised when a chart declares a ``<sos:clock kind="...">`` value
    that is reserved by SOS-08-D §15 but not yet supported at v1.

    The error message carries the canonical prefix
    ``SOS-08-D wave-future-clkkind:`` so downstream consumers can match
    against the wave/phase doc that owns the feature gate.
    """


class ClockDomainsParseError(Exception):
    """Raised on intrinsically malformed ``<sos:clock_domains>`` /
    ``<sos:clock>`` elements (missing required attributes, etc.).

    Distinct from ``UnsupportedClockKindError`` so callers can
    distinguish "chart is shaped wrong" from "chart declares a feature
    we don't ship yet".
    """


# ---------------------------------------------------------------------------
# ClockDecl dataclass — one per <sos:clock>.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClockDecl:
    """One ``<sos:clock>`` declaration.

    Fields mirror the §15 ratified element shape:

      * ``name``     — required ``name=`` attribute (SV identifier;
        the canonical handle a region/sampling-clock/cdc-boundary uses
        to reference this clock).
      * ``source``   — optional ``source=`` attribute (opaque chart-
        vocab string ID).  Defaults to ``name`` when omitted, per
        SOS-08-D §15 Q1 (b).
      * ``kind``     — required ``kind=`` attribute; one of
        ``SUPPORTED_KINDS``.  Raises ``UnsupportedClockKindError`` at
        parse time for ``RESERVED_KINDS`` values.
      * ``period_ns``  — optional ``period_ns=`` attribute (float).
        Default 10.0 ns (= 100 MHz nominal) per §15.
      * ``duty_cycle`` — optional ``duty_cycle=`` attribute (float in
        ``[0.0, 1.0]``).  Default 0.5.
      * ``phase_ns``   — optional ``phase_ns=`` attribute (float).
        Default 0.0 ns.  v2-staged: v1 walker parses + stores but emit
        ignores; v2+ quadrature/three-phase support reads phase
        relationships from pairs of declarations sharing a source.

    The class is ``frozen=True`` so instances are hashable + safe to
    use as dict keys for downstream pair-keyed maps.
    """

    name: str
    source: str
    kind: str
    period_ns: float = 10.0
    duty_cycle: float = 0.5
    phase_ns: float = 0.0


# ---------------------------------------------------------------------------
# Defaults.
# ---------------------------------------------------------------------------


#: Implicit default clock name when no ``<sos:clock_domains>`` block is
#: declared.  Matches the pre-wave-7a wave-1 default clock identifier.
_DEFAULT_CLOCK_NAME = "clk"

#: Implicit default source when ``<sos:clock_domains>`` is absent.  Per
#: §15 2026-05-25, charts without the block get
#: ``source="chart_root"`` so the implicit default never aliases with
#: any user-declared clock (whose default source is the clock's own
#: ``name=``).
_DEFAULT_CLOCK_SOURCE = "chart_root"


def implicit_default_clock() -> ClockDecl:
    """Return the implicit default ``ClockDecl`` used when a chart
    omits ``<sos:clock_domains>``.

    Per SOS-08-D §15 2026-05-25 "Backwards-compat (MUST)": charts
    without ``<sos:clock_domains>`` get an implicit
    ``name="clk", source="chart_root", kind="rising"`` clock.  All
    timing fields take their dataclass defaults.
    """
    return ClockDecl(
        name=_DEFAULT_CLOCK_NAME,
        source=_DEFAULT_CLOCK_SOURCE,
        kind=KIND_RISING,
    )


# ---------------------------------------------------------------------------
# Kind validation.
# ---------------------------------------------------------------------------


def validate_kind(kind: str) -> None:
    """Validate a ``kind=`` attribute value against the v1 enum.

    Raises:
        ``UnsupportedClockKindError`` for any value in
        ``RESERVED_KINDS`` (DDR / quadrature / three-phase / waltz —
        reserved by §15 but not yet supported) OR for any value
        outside ``SUPPORTED_KINDS ∪ RESERVED_KINDS`` (unknown enum
        value entirely).  No-op for ``SUPPORTED_KINDS``.

    The error message carries the canonical
    ``SOS-08-D wave-future-clkkind:`` prefix so downstream consumers
    can match against the spec section owning the feature gate.
    """
    if kind in SUPPORTED_KINDS:
        return
    if kind in RESERVED_KINDS:
        raise UnsupportedClockKindError(
            f"SOS-08-D wave-future-clkkind: kind {kind!r} is reserved "
            f"but not yet supported at v1. Supported kinds: "
            f"{sorted(SUPPORTED_KINDS)}. Reserved-future kinds: "
            f"{sorted(RESERVED_KINDS)} — adding requires a §15 "
            f"amendment to SOS-08-D-CONCEPTS.md per Standards Action."
        )
    raise UnsupportedClockKindError(
        f"SOS-08-D wave-future-clkkind: kind {kind!r} is not a "
        f"declared enum value. Supported kinds: "
        f"{sorted(SUPPORTED_KINDS)}. Reserved-future kinds: "
        f"{sorted(RESERVED_KINDS)}."
    )


# ---------------------------------------------------------------------------
# Float-attribute parsing — tolerant of either ``float`` or ``str``
# values from the loader (scjson loaders vary on attribute typing).
# ---------------------------------------------------------------------------


def _coerce_float(
    raw: Any, attr_name: str, default: float, clock_name: str
) -> float:
    """Coerce a ``<sos:clock>`` numeric attribute to ``float``.

    Accepts numeric (``int``/``float``) values verbatim; accepts
    string values via ``float()`` parsing.  Returns ``default`` when
    the attribute is missing (None) entirely.  Raises
    ``ClockDomainsParseError`` on values that can't be parsed.
    """
    if raw is None:
        return default
    if isinstance(raw, bool):
        # bool is a subclass of int — exclude it explicitly to avoid
        # ``True`` parsing as 1.0 and ``False`` as 0.0.
        raise ClockDomainsParseError(
            f"SOS-08-D wave-7a: <sos:clock name={clock_name!r}> "
            f"`{attr_name}` MUST be a float; got bool {raw!r}."
        )
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        try:
            return float(raw)
        except ValueError:
            raise ClockDomainsParseError(
                f"SOS-08-D wave-7a: <sos:clock name={clock_name!r}> "
                f"`{attr_name}` MUST be a float; got {raw!r}."
            ) from None
    raise ClockDomainsParseError(
        f"SOS-08-D wave-7a: <sos:clock name={clock_name!r}> "
        f"`{attr_name}` MUST be a float; got {type(raw).__name__}."
    )


# ---------------------------------------------------------------------------
# Chart-IR access — tolerant of the two scjson-loader conventions.
# ---------------------------------------------------------------------------


def _extract_clock_domains_block(chart_xml: Any) -> dict[str, Any] | None:
    """Look up the ``<sos:clock_domains>`` element in the chart-IR
    dict, accepting either the SCXML-namespaced (``sos:clock_domains``)
    or the bare (``clock_domains``) key — both forms are produced by
    the project's scjson loaders depending on namespace-stripping
    options.

    Returns the inner dict (the element's child + attribute payload),
    or ``None`` if no block is declared.

    Tolerates the loader's single-vs-list shape: an element with one
    child may surface as a bare dict while multi-child elements
    surface as a list; callers normalise that at the per-``<sos:clock>``
    level.
    """
    if not isinstance(chart_xml, dict):
        return None
    block = chart_xml.get("sos:clock_domains")
    if block is None:
        block = chart_xml.get("clock_domains")
    if block is None:
        return None
    # The loader may produce a list of `<sos:clock_domains>` blocks
    # (e.g. when the chart-author writes more than one — at v1 this is
    # discouraged but tolerated; later blocks merge into the same map).
    if isinstance(block, list):
        merged: dict[str, Any] = {}
        for entry in block:
            if isinstance(entry, dict):
                # Concatenate child lists across blocks.
                for k, v in entry.items():
                    if k in merged:
                        existing = merged[k]
                        if not isinstance(existing, list):
                            existing = [existing]
                        if isinstance(v, list):
                            existing.extend(v)
                        else:
                            existing.append(v)
                        merged[k] = existing
                    else:
                        merged[k] = v
        return merged if merged else None
    if isinstance(block, dict):
        return block
    return None


def _extract_clock_children(
    block: dict[str, Any],
) -> list[dict[str, Any]]:
    """Walk a ``<sos:clock_domains>`` payload dict for its
    ``<sos:clock>`` children.  Accepts either the SCXML-namespaced
    (``sos:clock``) or the bare (``clock``) key, and normalises the
    single-vs-list shape into a list.
    """
    raw = block.get("sos:clock")
    if raw is None:
        raw = block.get("clock")
    if raw is None:
        return []
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        return [c for c in raw if isinstance(c, dict)]
    return []


# ---------------------------------------------------------------------------
# Main parser.
# ---------------------------------------------------------------------------


def parse_clock_domains(chart_xml: Any) -> dict[str, ClockDecl]:
    """Parse the chart's ``<sos:clock_domains>`` block into a
    ``{name: ClockDecl}`` map.

    Args:
        chart_xml: the chart-IR dict (the raw scjson ``ChartAst.raw_scjson``
            shape — same shape consumed by ``render_target``).  May be
            ``None`` or any non-dict value; both yield the implicit
            default clock map.

    Returns:
        Ordered ``{name: ClockDecl}`` map.  Order matches source-
        document order of ``<sos:clock>`` children, modulo the implicit
        default-clock injection rule:

          * Block absent → ``{"clk": implicit_default_clock()}``.
          * Block present → one entry per ``<sos:clock>`` child; no
            implicit default is added (the author owns the clock list).

    Raises:
        ``UnsupportedClockKindError`` for any ``<sos:clock kind="...">``
        value in ``RESERVED_KINDS`` or outside the v1 enum.
        ``ClockDomainsParseError`` for missing/malformed required
        attributes (``name=``, ``kind=``) or unparseable numeric
        attributes.
    """
    block = _extract_clock_domains_block(chart_xml)
    if block is None:
        default = implicit_default_clock()
        return {default.name: default}

    children = _extract_clock_children(block)
    if not children:
        # An empty <sos:clock_domains/> block is treated like the
        # block being absent — defensive: chart authors who write the
        # element but no children still get a working default rather
        # than a chart-vocab error.  This mirrors the §15 backwards-
        # compat rule "Wave-1 charts emit byte-identical" — a chart
        # with only the opening/closing tags has no semantic clock
        # declarations.
        default = implicit_default_clock()
        return {default.name: default}

    out: dict[str, ClockDecl] = {}
    for child in children:
        name = child.get("name")
        if not (isinstance(name, str) and name.strip()):
            raise ClockDomainsParseError(
                "SOS-08-D wave-7a: <sos:clock> MUST carry a non-empty "
                "`name` attribute (the SV identifier other chart-vocab "
                "elements reference). Got: name="
                f"{name!r}."
            )
        name = name.strip()

        kind = child.get("kind")
        if not (isinstance(kind, str) and kind.strip()):
            raise ClockDomainsParseError(
                f"SOS-08-D wave-7a: <sos:clock name={name!r}> MUST "
                f"carry a non-empty `kind` attribute. Supported: "
                f"{sorted(SUPPORTED_KINDS)}."
            )
        kind = kind.strip()
        # Standards-Action enum validation.
        validate_kind(kind)

        source_raw = child.get("source")
        if isinstance(source_raw, str) and source_raw.strip():
            source = source_raw.strip()
        else:
            # Per §15 Q1 (b): absence means ``source = name``.
            source = name

        period_ns = _coerce_float(
            child.get("period_ns"), "period_ns", 10.0, name,
        )
        duty_cycle = _coerce_float(
            child.get("duty_cycle"), "duty_cycle", 0.5, name,
        )
        phase_ns = _coerce_float(
            child.get("phase_ns"), "phase_ns", 0.0, name,
        )

        if name in out:
            # Duplicate ``name=`` within one block is unambiguously a
            # chart-author error — a single `<sos:clock>` cannot be
            # declared twice under the same identifier.  Aliases use
            # distinct names with shared (source, kind) instead.
            raise ClockDomainsParseError(
                f"SOS-08-D wave-7a: <sos:clock_domains> declares "
                f"duplicate clock name {name!r}. Each <sos:clock> MUST "
                f"have a unique name; aliases share (source, kind) "
                f"under distinct names."
            )

        out[name] = ClockDecl(
            name=name,
            source=source,
            kind=kind,
            period_ns=period_ns,
            duty_cycle=duty_cycle,
            phase_ns=phase_ns,
        )

    return out


# ---------------------------------------------------------------------------
# Alias resolution.
# ---------------------------------------------------------------------------


def pair_of(name: str, clock_map: dict[str, ClockDecl]) -> tuple[str, str]:
    """Return the ``(source, kind)`` identity pair for ``name``.

    Raises ``KeyError`` if ``name`` is not declared in ``clock_map``.
    """
    decl = clock_map[name]
    return (decl.source, decl.kind)


def canonical_name_for_pair(
    source: str,
    kind: str,
    clock_map: dict[str, ClockDecl],
) -> str:
    """Return the alphabetic-first ``name=`` among all ``<sos:clock>``
    declarations sharing the ``(source, kind)`` identity pair.

    Per SOS-08-D §15 2026-05-25 Q3 (a) ratification: aliases —
    multiple ``<sos:clock>`` declarations with the same resolved
    ``(source, kind)`` pair — collapse to a single domain whose
    canonical name is the alphabetic-first across the alias set.

    Raises:
        ``KeyError`` if no clock in ``clock_map`` carries the
        requested ``(source, kind)``.
    """
    matches = [
        decl.name
        for decl in clock_map.values()
        if decl.source == source and decl.kind == kind
    ]
    if not matches:
        raise KeyError(
            f"No <sos:clock> in clock_map carries (source={source!r}, "
            f"kind={kind!r}). Declared pairs: "
            f"{sorted({(d.source, d.kind) for d in clock_map.values()})}."
        )
    return sorted(matches)[0]


def resolve_alias(
    name: str,
    clock_map: dict[str, ClockDecl],
) -> tuple[str, str, str]:
    """Resolve a clock reference to ``(canonical_name, source, kind)``.

    Given any user-facing clock name (which may itself be an alias),
    return the canonical-name triple per the alphabetic-first rule.

    Raises:
        ``KeyError`` if ``name`` is not declared in ``clock_map``.
    """
    if name not in clock_map:
        raise KeyError(
            f"Clock name {name!r} is not declared. Declared names: "
            f"{sorted(clock_map.keys())}."
        )
    decl = clock_map[name]
    canonical = canonical_name_for_pair(decl.source, decl.kind, clock_map)
    return (canonical, decl.source, decl.kind)
