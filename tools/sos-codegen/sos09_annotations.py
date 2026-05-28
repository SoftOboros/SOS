"""SOS-09-A chart annotation parser + validator.

Reads the loader's `ChartAst.raw_scjson` shape (or any scjson-derived dict)
and extracts every `sos:`-prefixed key from each parent element's
`other_attributes` JSON map, building a typed, validated annotation model
that the downstream SOS-09-B / -C / -D / -E / -F / -G emitters consume.

This module IS the input contract every later SOS-09 sub-phase reads. It
implements §5.3 (parsing rule) and §5.4 (validation rules 1-9) of
`docs/concepts/SOS-09-A-CONCEPTS.md`, ratified 2026-05-25, with the
PCDN-SOS-09-007 follow-on amendment 2026-05-26 that extends §5.2 from
ten keys to twelve keys (added `sos:channel_group` and
`sos:privilege_region`).

Authority: `docs/concepts/SOS-09-A-CONCEPTS.md` (this sub-phase, normative);
`docs/concepts/SOS-09-CONCEPTS.md` (umbrella; §5.1-§5.4 enums mirrored);
`docs/concepts/SOS-09-G-CONCEPTS.md` (§5.5 `sos:mpu_background` chart-root,
§5.2 per-channel `sos:mpu_attr`).

Public surface:
    parse_chart_annotations(chart_ast: dict) -> ChartAnnotations
    Sos09AnnotationError

Invariants enforced (per §7 of SOS-09-A-CONCEPTS.md):
    INV-S-MEM-A-1  unique sos:id within chart
    INV-S-MEM-A-2  required keys present (sos:id, sos:name, sos:kind, sos:dir)
    INV-S-MEM-A-3  sos: prefix is a JSON-key STRING, not an XML namespace
    INV-S-MEM-A-4  xmlns:sos declarations are chart-load errors (loader-level)
    INV-S-MEM-A-5  kind/dir pair is one of the §5.2 table rows
    INV-S-MEM-A-6  sos:irq only on kind=status+dir=hw->sw; sos:mutex only on shared
    INV-S-MEM-A-7  sos:-prefixed keys appear only on <state> and <parallel>
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Frozen enums (mirrors from umbrella per §8; do NOT extend without amendment)
# ---------------------------------------------------------------------------

# Per umbrella §5.1 ratified 2026-05-23.
ALLOWED_KINDS: frozenset[str] = frozenset({"status", "command", "queue", "shared"})

# Per umbrella §5.2 channel->primitive mapping (the dir values themselves).
# 2026-05-28 ERRATA-004 closure: `bidirectional` retracted as a synonym for
# `hw↔sw`; canonical SOS-09 §5.2 spelling is the arrow form. The migration
# window backstop that briefly accepted the legacy spelling has been removed
# now that both chart families (sis08_first_slice, sis08d_c2_membrane) have
# completed the migration to `hw↔sw` (SOS submodule commit 9682b35).
# `bidirectional` is now a hard §5.4(3) error at the validator layer,
# mirroring §5.4(3) rule prose verbatim.
ALLOWED_DIRS: frozenset[str] = frozenset({"hw→sw", "sw→hw", "hw↔sw"})

# Per umbrella §5.4.
ALLOWED_ZONES: frozenset[str] = frozenset({"privileged", "unprivileged"})

# §5.2: stored atomicity values; the spec text uses `explicit`/`implicit` as
# the user-facing metavalues, but the dataclass holds the resolved class
# (`atomic` / `mutex-required` per umbrella §5.3). We accept all four input
# tokens and resolve. Any other value is a §5.4 (3) hard error.
_ATOMICITY_INPUT_TOKENS: frozenset[str] = frozenset(
    {"atomic", "mutex-required", "implicit", "explicit"}
)
_ATOMICITY_RESOLVED: frozenset[str] = frozenset({"atomic", "mutex-required"})

# Per umbrella §5.2 (kind -> permitted dirs table). Per ERRATA-004 closure
# (2026-05-28) `bidirectional` has been retracted as a synonym for `hw↔sw`
# and is no longer accepted; the migration-window backstop is removed now
# that both chart families have completed the migration. Adding the legacy
# spelling back would require a §15 amendment to SOS-09 §5.2 (Standards
# Action per the umbrella's registration-policy clause).
_KIND_DIR_MATRIX: dict[str, frozenset[str]] = {
    "status": frozenset({"hw→sw"}),
    "command": frozenset({"sw→hw"}),
    "queue": frozenset({"hw→sw", "sw→hw", "hw↔sw"}),
    "shared": frozenset({"hw↔sw"}),
}

# Per SOS-09-G §5.2 / PCDN-G-003.
ALLOWED_MPU_ATTRS: frozenset[str] = frozenset(
    {"cacheable", "non_cacheable", "device_ngnrne", "device_ngnre"}
)

# Per SOS-09-G §5.5 / PCDN-G-002.
ALLOWED_MPU_BACKGROUNDS: frozenset[str] = frozenset({"kernel_default", "strict"})
DEFAULT_MPU_BACKGROUND: str = "kernel_default"

# Per SOS-09-A §16 amendment 2026-05-28 (Path B per parent EOQ-002-ERRATA-002):
# the three-value placement enum names the *access mechanism* on a target for
# a SOS-09-A chart's emitted manifest. Each chart's emitter MUST declare
# exactly one value; the enforcement gate lives in `validate_placement` below
# and is wired into every chart-family emitter before manifest write.
#
# Registration policy: **Standards Action** (inherited from SOS-09 umbrella
# frozen-enumeration registration-policy clause; the placement vocabulary
# crosses sub-phase boundaries — SOS-09-A emitters, SOS-09-D Rust HAL,
# SOS-09-E HDL register-file all consume it). Adding a fourth placement
# value (e.g. a future `network-membrane` for remote-accessed surfaces)
# requires another §15 amendment to `docs/concepts/SOS-09-A-CONCEPTS.md`
# *first*, with the same Standards Action discipline. Demotion to
# Specification Required would itself require an umbrella §15 amendment.
ALLOWED_PLACEMENTS: frozenset[str] = frozenset(
    {"hardware-block", "sram-membrane", "mmio-peripheral"}
)

# Per PCDN-SOS-09-A-001 ratification.
ALLOWED_BIT_FIELD_ACCESS: frozenset[str] = frozenset({"RW", "RO", "WO", "reserved"})
ALLOWED_BIT_FIELD_SIDE_EFFECTS: frozenset[str] = frozenset(
    {"clear-on-read", "side-effect-on-write"}
)

# §5.2: the twelve permitted SOS-09-A keys (post-PCDN-SOS-09-007 follow-on
# amendment 2026-05-26: added `sos:channel_group` and `sos:privilege_region`).
PERMITTED_SOS_KEYS: frozenset[str] = frozenset(
    {
        "sos:id",
        "sos:name",
        "sos:kind",
        "sos:dir",
        "sos:zone",
        "sos:atomicity",
        "sos:width",
        "sos:bit_layout",
        "sos:irq",
        "sos:mutex",
        "sos:channel_group",
        "sos:privilege_region",
    }
)

# Per-element permitted keys outside the SOS-09-A ten-key set but accepted by
# downstream sub-phases (parsed and surfaced, not validated by this module's
# core rules). SOS-09-G §5.2 adds `sos:mpu_attr` as a per-channel override.
PERMITTED_SOS_EXTENDED_KEYS: frozenset[str] = frozenset({"sos:mpu_attr"})

# Per SOS-09-G §5.5: chart-root annotation key.
CHART_ROOT_KEYS: frozenset[str] = frozenset({"sos:mpu_background"})

# IEEE 1800-2017 §5.6 identifier shape — the SV identifier the §3 glossary
# names as the round-trip-safe shape for both CMSIS-SVD `name` and HDL
# register-file emission. Cited not redefined.
_SV_IDENTIFIER_RE: re.Pattern[str] = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# RFC 4122 canonical hyphenated UUID (8-4-4-4-12 hex, case-insensitive).
_UUID_RE: re.Pattern[str] = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

# Parent contexts allowed by §5.1. iState <region> compiles down to a child
# of <parallel> in SCXML; scjson reports them as `state`/`parallel` keys.
_PARENT_CONTEXT_KEYS: tuple[str, ...] = ("state", "parallel")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class Sos09AnnotationError(Exception):
    """Raised on annotation parse/validation failures.

    Carries an `element_path` (best-effort dotted SCXML id path naming the
    offending parent context) and a `rule` token naming which §5.4 rule
    fired, for downstream error-reporting tooling.
    """

    def __init__(
        self,
        message: str,
        *,
        element_path: Optional[str] = None,
        rule: Optional[str] = None,
        key: Optional[str] = None,
    ) -> None:
        self.element_path = element_path
        self.rule = rule
        self.key = key
        prefix_parts: list[str] = []
        if rule:
            prefix_parts.append(f"[{rule}]")
        if element_path:
            prefix_parts.append(f"at <{element_path}>")
        if key:
            prefix_parts.append(f"key={key!r}")
        prefix = " ".join(prefix_parts)
        super().__init__(f"{prefix}: {message}" if prefix else message)


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BitField:
    """One bit-field inside a `sos:bit_layout`.

    Per PCDN-SOS-09-A-001: tuple
    (field-name / start-bit / width / access / side-effect / reset-value).
    """

    name: str
    start_bit: int
    width: int
    access: str
    side_effect: Optional[str] = None
    reset_value: int = 0


@dataclass(frozen=True)
class BitLayout:
    """Inline `sos:bit_layout` block (PCDN-SOS-09-A-001 inline schema).

    Stored as a tuple to keep the dataclass frozen-hashable per the task
    prompt's public surface.
    """

    fields: tuple[BitField, ...]


@dataclass(frozen=True)
class ChannelAnnotation:
    """A single SOS-09 channel declaration extracted from a chart parent.

    Per SOS-09-A §5.2 twelve-key set (PCDN-SOS-09-007 follow-on amendment
    2026-05-26 — added `sos:channel_group` and `sos:privilege_region`). The
    four required keys (`sos:id`, `sos:name`, `sos:kind`, `sos:dir`)
    populate the first four fields; optional keys populate the rest with
    default inference per §5.2 / umbrella §5.3. The new `channel_group` /
    `privilege_region` fields surface raw `Optional[str]`; the inheritance
    walk (defaulting absence to the enclosing parallel/compound state's
    declared value, or `"default"` if no ancestor declares) is a CONSUMER
    concern — SOS-09-D (Rust HAL emission) and SOS-09-E (HDL register-file
    RTL) implement it, not this parser.
    """

    id: str  # sos:id - RFC 4122 UUID (canonical hyphenated form)
    name: str  # sos:name - SV identifier
    kind: str  # one of {"status", "command", "queue", "shared"}
    dir: str  # one of {"hw->sw", "sw->hw", "hw<->sw"} per §5.2 (using ASCII arrows internally; spec uses Unicode arrows: hw->sw == hw→sw)
    zone: str = "privileged"
    atomicity: str = "atomic"  # resolved class per umbrella §5.3
    width: int = 32
    bit_layout: Optional[BitLayout] = None
    irq: Optional[str] = None
    mutex: Optional[str] = None
    mpu_attr: Optional[str] = None  # SOS-09-G §5.2 per-channel override
    # PCDN-SOS-09-007 follow-on amendment 2026-05-26: channel-group as two
    # axes. `channel_group` names the Rust borrow scope / shared
    # `RegisterBlock` boundary; `privilege_region` names the HDL MPU
    # privilege region / access-violation aggregation domain. Both
    # OPTIONAL on a channel; absence surfaces as None here (consumer
    # walks the SCXML ancestor chain for the inheritance default, or
    # falls back to `"default"`).
    channel_group: Optional[str] = None
    privilege_region: Optional[str] = None
    # Best-effort dotted path to the SCXML parent (state id chain); useful
    # for error reporting and downstream "composed scope path" naming.
    element_path: str = ""
    # Forward-compat: any `sos:`-prefixed key not in the recognised set is
    # surfaced here. Reserved for future SOS-09-* keys; this module does NOT
    # validate the values.
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChartAnnotations:
    """All SOS-09 channels in a chart plus chart-root annotations.

    `channels` is ordered by document-order traversal of the chart (state
    tree depth-first, parallel before state at each level). `mpu_background`
    is the SOS-09-G §5.5 chart-root key; default `kernel_default`.
    """

    channels: tuple[ChannelAnnotation, ...]
    mpu_background: str = DEFAULT_MPU_BACKGROUND


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_other_attributes(node: dict[str, Any]) -> dict[str, Any]:
    """Return the parsed `other_attributes` JSON map for a scjson node, or {}.

    scjson 0.3.6 surfaces SCXML `other_attributes` as:
        node["other_attributes"]["other_attributes"] -> JSON string

    We parse the inner string into a Python dict. If the value is already a
    dict (some scjson versions / future shapes), pass it through.
    """
    oa = node.get("other_attributes")
    if oa is None:
        return {}
    if isinstance(oa, str):
        # Some shape variants surface the JSON string directly.
        raw = oa
    elif isinstance(oa, dict):
        # scjson 0.3.6 shape: {"other_attributes": "<JSON string>"}.
        inner = oa.get("other_attributes")
        if isinstance(inner, str):
            raw = inner
        elif isinstance(inner, dict):
            return inner
        elif inner is None:
            # scjson MAY surface a flat dict directly when no SCXML-namespace
            # collision occurs.
            return {k: v for k, v in oa.items() if k != "other_attributes"} or {}
        else:
            return {}
    else:
        return {}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise Sos09AnnotationError(
            f"malformed other_attributes JSON: {exc}",
            rule="parse",
        ) from exc
    if not isinstance(parsed, dict):
        raise Sos09AnnotationError(
            "other_attributes JSON must be an object",
            rule="parse",
        )
    return parsed


def _sos_keys(attrs: dict[str, Any]) -> dict[str, Any]:
    """§5.3 parsing rule: partition `sos:`-prefixed keys."""
    return {k: v for k, v in attrs.items() if isinstance(k, str) and k.startswith("sos:")}


def _validate_uuid(value: Any, *, element_path: str) -> str:
    if not isinstance(value, str) or not _UUID_RE.match(value):
        raise Sos09AnnotationError(
            f"sos:id must be an RFC 4122 canonical hyphenated UUID; got {value!r}",
            element_path=element_path,
            rule="§5.4(7)",
            key="sos:id",
        )
    return value


def _validate_sv_identifier(value: Any, *, element_path: str, key: str) -> str:
    if not isinstance(value, str) or not _SV_IDENTIFIER_RE.match(value):
        raise Sos09AnnotationError(
            f"{key} must be an SV identifier ([A-Za-z_][A-Za-z0-9_]*); got {value!r}",
            element_path=element_path,
            rule="§5.4(7)",
            key=key,
        )
    return value


def _validate_enum(
    value: Any,
    allowed: frozenset[str],
    *,
    element_path: str,
    key: str,
) -> str:
    if value not in allowed:
        raise Sos09AnnotationError(
            f"{key} value {value!r} not in allowed set {sorted(allowed)}",
            element_path=element_path,
            rule="§5.4(3)",
            key=key,
        )
    return value  # type: ignore[return-value]


def _resolve_atomicity(token: Optional[Any], kind: str, *, element_path: str) -> str:
    """Resolve a `sos:atomicity` input token to the final class per umbrella §5.3.

    Input tokens accepted:
        - missing/None        -> kind-inferred
        - "implicit"          -> kind-inferred (same as missing)
        - "explicit"          -> kind-inferred (spec text; explicit form
                                 without an override value means "I asserted
                                 the kind-default explicitly")
        - "atomic"            -> "atomic"
        - "mutex-required"    -> "mutex-required"
        - anything else       -> §5.4(3) hard error
    """
    if token is None:
        return _kind_inferred_atomicity(kind)
    if not isinstance(token, str) or token not in _ATOMICITY_INPUT_TOKENS:
        raise Sos09AnnotationError(
            f"sos:atomicity value {token!r} not in allowed set "
            f"{sorted(_ATOMICITY_INPUT_TOKENS)}",
            element_path=element_path,
            rule="§5.4(3)",
            key="sos:atomicity",
        )
    if token in _ATOMICITY_RESOLVED:
        return token
    # implicit / explicit -> kind-default
    return _kind_inferred_atomicity(kind)


def _kind_inferred_atomicity(kind: str) -> str:
    """Umbrella §5.3 default inference: status/command/queue -> atomic; shared -> mutex-required."""
    if kind == "shared":
        return "mutex-required"
    return "atomic"


def _validate_width(value: Any, *, element_path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        # JSON booleans subclass int; reject explicitly. Also reject strings
        # like "thirty-two" per §5.4(6).
        try:
            iv = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise Sos09AnnotationError(
                f"sos:width must be an integer; got {value!r}",
                element_path=element_path,
                rule="§5.4(6)",
                key="sos:width",
            ) from exc
        # If a string parsed cleanly (e.g. "32"), accept — chart authors may
        # serialize as string inside JSON-string-of-JSON layers.
        value = iv
    if not (1 <= value <= 64):
        raise Sos09AnnotationError(
            f"sos:width must satisfy 1 <= width <= 64; got {value}",
            element_path=element_path,
            rule="§5.4(6)",
            key="sos:width",
        )
    return value


def _parse_bit_layout(raw: Any, *, element_path: str, width: int) -> BitLayout:
    """Parse `sos:bit_layout` per PCDN-SOS-09-A-001 inline schema.

    Expected shape:
        {"fields": [
            {"name": "...", "start_bit": N, "width": M, "access": "RW",
             "side_effect": null|"clear-on-read"|"side-effect-on-write",
             "reset_value": 0},
            ...
        ]}

    Field-overlap and exceeds-width checks raise Sos09AnnotationError.
    """
    if not isinstance(raw, dict):
        raise Sos09AnnotationError(
            "sos:bit_layout must be a JSON object",
            element_path=element_path,
            rule="§5.4(3)",
            key="sos:bit_layout",
        )
    fields_raw = raw.get("fields")
    if not isinstance(fields_raw, list):
        raise Sos09AnnotationError(
            "sos:bit_layout must contain a `fields` list",
            element_path=element_path,
            rule="§5.4(3)",
            key="sos:bit_layout",
        )

    parsed_fields: list[BitField] = []
    occupied: list[tuple[int, int, str]] = []  # (start, end_exclusive, name)
    for idx, fr in enumerate(fields_raw):
        if not isinstance(fr, dict):
            raise Sos09AnnotationError(
                f"sos:bit_layout.fields[{idx}] must be an object",
                element_path=element_path,
                rule="§5.4(3)",
                key="sos:bit_layout",
            )
        name = fr.get("name")
        start_bit = fr.get("start_bit")
        f_width = fr.get("width")
        access = fr.get("access")
        side_effect = fr.get("side_effect")
        reset_value = fr.get("reset_value", 0)

        if not isinstance(name, str) or not _SV_IDENTIFIER_RE.match(name):
            raise Sos09AnnotationError(
                f"sos:bit_layout.fields[{idx}].name must be an SV identifier; got {name!r}",
                element_path=element_path,
                rule="§5.4(7)",
                key="sos:bit_layout",
            )
        if not isinstance(start_bit, int) or isinstance(start_bit, bool) or start_bit < 0:
            raise Sos09AnnotationError(
                f"sos:bit_layout.fields[{idx}].start_bit must be a non-negative integer; got {start_bit!r}",
                element_path=element_path,
                rule="§5.4(6)",
                key="sos:bit_layout",
            )
        if not isinstance(f_width, int) or isinstance(f_width, bool) or f_width < 1:
            raise Sos09AnnotationError(
                f"sos:bit_layout.fields[{idx}].width must be a positive integer; got {f_width!r}",
                element_path=element_path,
                rule="§5.4(6)",
                key="sos:bit_layout",
            )
        if access not in ALLOWED_BIT_FIELD_ACCESS:
            raise Sos09AnnotationError(
                f"sos:bit_layout.fields[{idx}].access must be one of "
                f"{sorted(ALLOWED_BIT_FIELD_ACCESS)}; got {access!r}",
                element_path=element_path,
                rule="§5.4(3)",
                key="sos:bit_layout",
            )
        if side_effect is not None and side_effect not in ALLOWED_BIT_FIELD_SIDE_EFFECTS:
            raise Sos09AnnotationError(
                f"sos:bit_layout.fields[{idx}].side_effect must be one of "
                f"{sorted(ALLOWED_BIT_FIELD_SIDE_EFFECTS)} or null; got {side_effect!r}",
                element_path=element_path,
                rule="§5.4(3)",
                key="sos:bit_layout",
            )
        if not isinstance(reset_value, int) or isinstance(reset_value, bool):
            raise Sos09AnnotationError(
                f"sos:bit_layout.fields[{idx}].reset_value must be an integer; got {reset_value!r}",
                element_path=element_path,
                rule="§5.4(6)",
                key="sos:bit_layout",
            )

        end_excl = start_bit + f_width
        if end_excl > width:
            raise Sos09AnnotationError(
                f"sos:bit_layout.fields[{idx}] ({name!r}) extends beyond sos:width={width}: "
                f"start_bit={start_bit} + width={f_width} = {end_excl}",
                element_path=element_path,
                rule="§5.4(6)",
                key="sos:bit_layout",
            )
        # Overlap check.
        for (os, oe, oname) in occupied:
            if start_bit < oe and end_excl > os:
                raise Sos09AnnotationError(
                    f"sos:bit_layout.fields[{idx}] ({name!r}, "
                    f"bits {start_bit}..{end_excl - 1}) overlaps "
                    f"with {oname!r} (bits {os}..{oe - 1})",
                    element_path=element_path,
                    rule="§5.4(6)",
                    key="sos:bit_layout",
                )
        occupied.append((start_bit, end_excl, name))

        parsed_fields.append(
            BitField(
                name=name,
                start_bit=start_bit,
                width=f_width,
                access=access,
                side_effect=side_effect,
                reset_value=reset_value,
            )
        )

    return BitLayout(fields=tuple(parsed_fields))


def _build_channel(
    sos_attrs: dict[str, Any],
    *,
    element_path: str,
) -> ChannelAnnotation:
    """Validate the sos:* keys on one parent element and construct a
    ChannelAnnotation. Raises Sos09AnnotationError on any violation."""

    # §5.4(2) required-key presence.
    required = ("sos:id", "sos:name", "sos:kind", "sos:dir")
    missing = [k for k in required if k not in sos_attrs]
    if missing:
        raise Sos09AnnotationError(
            f"missing required SOS-09-A key(s): {missing}",
            element_path=element_path,
            rule="§5.4(2)",
            key=missing[0],
        )

    # Unknown sos: keys outside the ten-key set + permitted extended keys
    # (sos:mpu_attr from SOS-09-G) are surfaced via `extras` rather than
    # rejected — this preserves forward-compat with downstream sub-phases
    # that own their own keys. Strictly-unknown keys ("sos:totally_made_up")
    # surface in extras too; this module does NOT validate them. The SOS-09-A
    # core validation rules (§5.4) only mandate validity of the ten-key set.
    extras: dict[str, Any] = {}
    for k, v in sos_attrs.items():
        if k in PERMITTED_SOS_KEYS:
            continue
        if k in PERMITTED_SOS_EXTENDED_KEYS:
            continue
        extras[k] = v

    # §5.4(7) sos:id RFC 4122 UUID.
    channel_id = _validate_uuid(sos_attrs["sos:id"], element_path=element_path)

    # §5.4(7) sos:name SV identifier.
    channel_name = _validate_sv_identifier(
        sos_attrs["sos:name"], element_path=element_path, key="sos:name"
    )

    # §5.4(3) enum validity for kind.
    kind = _validate_enum(
        sos_attrs["sos:kind"], ALLOWED_KINDS,
        element_path=element_path, key="sos:kind",
    )

    # §5.4(3) enum validity for dir.
    dir_val = _validate_enum(
        sos_attrs["sos:dir"], ALLOWED_DIRS,
        element_path=element_path, key="sos:dir",
    )

    # §5.4(4) cross-attribute kind/dir consistency.
    if dir_val not in _KIND_DIR_MATRIX[kind]:
        raise Sos09AnnotationError(
            f"sos:dir={dir_val!r} not valid for sos:kind={kind!r}; "
            f"per §5.2 table allowed dirs are {sorted(_KIND_DIR_MATRIX[kind])}",
            element_path=element_path,
            rule="§5.4(4)",
            key="sos:dir",
        )

    # §5.4(3) sos:zone enum.
    zone = sos_attrs.get("sos:zone", "privileged")
    if "sos:zone" in sos_attrs:
        zone = _validate_enum(
            sos_attrs["sos:zone"], ALLOWED_ZONES,
            element_path=element_path, key="sos:zone",
        )

    # §5.4(6) sos:width range. Default 32 per §5.2.
    width_val: int = 32
    if "sos:width" in sos_attrs:
        width_val = _validate_width(sos_attrs["sos:width"], element_path=element_path)

    # §5.3 atomicity resolution (umbrella §5.3 default-inference rule).
    atomicity = _resolve_atomicity(
        sos_attrs.get("sos:atomicity"), kind, element_path=element_path,
    )

    # §5.4(5) kind-gated attribute validity.
    irq = sos_attrs.get("sos:irq")
    if irq is not None:
        if not (kind == "status" and dir_val == "hw→sw"):
            raise Sos09AnnotationError(
                f"sos:irq is valid only when sos:kind='status' AND sos:dir='hw→sw'; "
                f"this channel has kind={kind!r}, dir={dir_val!r}",
                element_path=element_path,
                rule="§5.4(5)",
                key="sos:irq",
            )
        if not isinstance(irq, str) or not irq:
            raise Sos09AnnotationError(
                f"sos:irq must be a non-empty string; got {irq!r}",
                element_path=element_path,
                rule="§5.4(3)",
                key="sos:irq",
            )

    mutex = sos_attrs.get("sos:mutex")
    if mutex is not None:
        if kind != "shared":
            raise Sos09AnnotationError(
                f"sos:mutex is valid only when sos:kind='shared'; "
                f"this channel has kind={kind!r}",
                element_path=element_path,
                rule="§5.4(5)",
                key="sos:mutex",
            )
        if not isinstance(mutex, str) or not mutex:
            raise Sos09AnnotationError(
                f"sos:mutex must be a non-empty string; got {mutex!r}",
                element_path=element_path,
                rule="§5.4(3)",
                key="sos:mutex",
            )

    # SOS-09-G §5.2 per-channel sos:mpu_attr override.
    mpu_attr = sos_attrs.get("sos:mpu_attr")
    if mpu_attr is not None:
        if not isinstance(mpu_attr, str) or mpu_attr not in ALLOWED_MPU_ATTRS:
            raise Sos09AnnotationError(
                f"sos:mpu_attr value {mpu_attr!r} not in allowed set "
                f"{sorted(ALLOWED_MPU_ATTRS)}",
                element_path=element_path,
                rule="§5.4(3)",
                key="sos:mpu_attr",
            )

    # PCDN-SOS-09-A-001 sos:bit_layout (inline). Width must be known first.
    bit_layout: Optional[BitLayout] = None
    if "sos:bit_layout" in sos_attrs:
        bit_layout = _parse_bit_layout(
            sos_attrs["sos:bit_layout"],
            element_path=element_path,
            width=width_val,
        )

    # PCDN-SOS-09-007 follow-on amendment 2026-05-26: `sos:channel_group`
    # and `sos:privilege_region`. Both OPTIONAL on a channel; absence
    # surfaces as None (inheritance walk is a consumer-side concern).
    # When present, both MUST be SV identifiers per §5.4(7) — they emit as
    # Rust module / RTL signal names downstream.
    channel_group: Optional[str] = None
    if "sos:channel_group" in sos_attrs:
        channel_group = _validate_sv_identifier(
            sos_attrs["sos:channel_group"],
            element_path=element_path,
            key="sos:channel_group",
        )

    privilege_region: Optional[str] = None
    if "sos:privilege_region" in sos_attrs:
        privilege_region = _validate_sv_identifier(
            sos_attrs["sos:privilege_region"],
            element_path=element_path,
            key="sos:privilege_region",
        )

    return ChannelAnnotation(
        id=channel_id,
        name=channel_name,
        kind=kind,
        dir=dir_val,
        zone=zone,
        atomicity=atomicity,
        width=width_val,
        bit_layout=bit_layout,
        irq=irq,
        mutex=mutex,
        mpu_attr=mpu_attr,
        channel_group=channel_group,
        privilege_region=privilege_region,
        element_path=element_path,
        extras=extras,
    )


def _walk_chart(
    node: dict[str, Any],
    *,
    parent_path: str,
    channels_out: list[ChannelAnnotation],
) -> None:
    """Depth-first walk of the scjson chart, emitting one ChannelAnnotation
    per parent element that carries any `sos:`-prefixed key in
    other_attributes."""

    for parent_key in _PARENT_CONTEXT_KEYS:
        children = node.get(parent_key, []) or []
        if not isinstance(children, list):
            continue
        for child in children:
            if not isinstance(child, dict):
                continue
            child_id = child.get("id") or "<anonymous>"
            element_path = f"{parent_path}.{child_id}" if parent_path else child_id

            attrs = _extract_other_attributes(child)
            sos_attrs = _sos_keys(attrs)
            if sos_attrs:
                channel = _build_channel(sos_attrs, element_path=element_path)
                channels_out.append(channel)

            # Recurse — channels can nest.
            _walk_chart(child, parent_path=element_path, channels_out=channels_out)


def _check_disallowed_sos_on_non_parent(
    node: dict[str, Any],
    *,
    parent_path: str,
) -> None:
    """§5.4(8) parent-context validity: `sos:`-prefixed keys on iState/SCXML
    elements outside {<state>, <parallel>} are a hard error. Walks every
    sub-element key that scjson surfaces and rejects any `sos:` annotation
    found outside the allowed parent contexts.

    The chart root <scxml> is allowed to carry `sos:mpu_background` (per
    SOS-09-G §5.5) and NOTHING ELSE from the SOS-09-A key set; that case is
    handled separately by the caller.
    """
    disallowed_keys = (
        "transition", "datamodel", "onentry", "onexit", "initial",
        "history", "final", "invoke", "send", "raise_value", "log",
        "assign", "if_value", "foreach", "data", "donedata", "content",
        "param",
    )
    for k in disallowed_keys:
        children = node.get(k, []) or []
        if not isinstance(children, list):
            continue
        for child in children:
            if not isinstance(child, dict):
                continue
            attrs = _extract_other_attributes(child)
            sos_attrs = _sos_keys(attrs)
            if sos_attrs:
                # Build an actionable error.
                offending = sorted(sos_attrs.keys())
                raise Sos09AnnotationError(
                    f"`sos:`-prefixed keys are not permitted on <{k}> elements "
                    f"(§5.1 allowed parents: <state>, <parallel>, <region>); "
                    f"found keys: {offending}",
                    element_path=parent_path or "<scxml>",
                    rule="§5.4(8)",
                )

    # Recurse into structural carriers — channels declared on <state>/<parallel>
    # contained in any of these elements should ALSO be checked further down.
    for parent_key in _PARENT_CONTEXT_KEYS:
        children = node.get(parent_key, []) or []
        if not isinstance(children, list):
            continue
        for child in children:
            if not isinstance(child, dict):
                continue
            child_id = child.get("id") or "<anonymous>"
            new_path = f"{parent_path}.{child_id}" if parent_path else child_id
            _check_disallowed_sos_on_non_parent(child, parent_path=new_path)


def _parse_chart_root_annotations(root: dict[str, Any]) -> str:
    """Extract `sos:mpu_background` from the chart root <scxml> element.

    Per SOS-09-G §5.5: optional; default `kernel_default`. Validated against
    the two-value enum {kernel_default, strict}. Any other `sos:`-prefixed
    key on the chart root is rejected as a §5.4(8)-class error: the chart
    root is NOT a permitted SOS-09-A annotation parent context.
    """
    attrs = _extract_other_attributes(root)
    sos_attrs = _sos_keys(attrs)

    # Allow only the SOS-09-G chart-root key set.
    illegal = [k for k in sos_attrs if k not in CHART_ROOT_KEYS]
    if illegal:
        raise Sos09AnnotationError(
            f"chart root <scxml> may only carry chart-root SOS keys "
            f"({sorted(CHART_ROOT_KEYS)}); found illegal key(s): {sorted(illegal)}",
            element_path="<scxml>",
            rule="§5.4(8)",
        )

    mpu_background = sos_attrs.get("sos:mpu_background", DEFAULT_MPU_BACKGROUND)
    if mpu_background not in ALLOWED_MPU_BACKGROUNDS:
        raise Sos09AnnotationError(
            f"sos:mpu_background value {mpu_background!r} not in allowed set "
            f"{sorted(ALLOWED_MPU_BACKGROUNDS)}",
            element_path="<scxml>",
            rule="§5.4(3)",
            key="sos:mpu_background",
        )
    return mpu_background


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_placement(
    placement: Any,
    *,
    manifest_path: Optional[str] = None,
) -> str:
    """Validate a manifest `placement` value against `ALLOWED_PLACEMENTS`.

    Per SOS-09-A §16 amendment 2026-05-28 (Path B per parent EOQ-002-ERRATA-002),
    the three-value enum `{hardware-block, sram-membrane, mmio-peripheral}` is
    normative. Chart-family emitters MUST call this helper before writing
    their manifest JSON so that a typo or an unratified extension is caught
    at emit-time rather than surviving as silent manifest mythology.

    The rule citation token is `§16(2026-05-28)`, naming the amendment date
    that introduced the third placement value and made the enum normative.
    Adding a fourth value requires a fresh §15 amendment to SOS-09-A under
    the inherited Standards Action registration policy — see the
    `ALLOWED_PLACEMENTS` docstring near the top of this module.

    `manifest_path` (optional) surfaces in the error's `element_path` for
    diagnostic clarity; emitters SHOULD pass the chart-id or the relative
    manifest path.
    """
    if not isinstance(placement, str) or placement not in ALLOWED_PLACEMENTS:
        raise Sos09AnnotationError(
            f"manifest placement value {placement!r} not in allowed set "
            f"{sorted(ALLOWED_PLACEMENTS)}",
            rule="§16(2026-05-28)",
            key="placement",
            element_path=manifest_path,
        )
    return placement


def parse_chart_annotations(chart_ast: dict) -> ChartAnnotations:
    """Walk the scjson chart AST and produce a typed annotation model.

    `chart_ast` is the dict surfaced by `loader.load_chart(...).raw_scjson`
    (or any equivalent scjson-shape dict). The root represents the <scxml>
    element; its `state` / `parallel` children are recursively walked.

    Raises Sos09AnnotationError on any §5.4 (1)-(9) validation rule
    violation. The first violation encountered is raised; subsequent
    violations are not aggregated (chart-author errors are typically
    addressed one at a time).
    """
    if not isinstance(chart_ast, dict):
        raise Sos09AnnotationError(
            f"chart_ast must be a dict; got {type(chart_ast).__name__}",
            rule="parse",
        )

    # §5.4(8) check: reject sos:-prefixed keys on non-permitted parents
    # before doing the legal walk. (Done first so the error names the
    # specific offending element type.)
    _check_disallowed_sos_on_non_parent(chart_ast, parent_path="")

    # Chart-root <scxml> annotations: only `sos:mpu_background` permitted.
    mpu_background = _parse_chart_root_annotations(chart_ast)

    # Collect channels from <state>/<parallel> tree.
    channels: list[ChannelAnnotation] = []
    _walk_chart(chart_ast, parent_path="", channels_out=channels)

    # §5.4(1) unique sos:id within chart.
    seen_ids: dict[str, str] = {}  # sos:id -> first element_path
    for ch in channels:
        if ch.id in seen_ids:
            raise Sos09AnnotationError(
                f"duplicate sos:id={ch.id!r} on elements "
                f"<{seen_ids[ch.id]}> and <{ch.element_path}>",
                element_path=ch.element_path,
                rule="§5.4(1)",
                key="sos:id",
            )
        seen_ids[ch.id] = ch.element_path

    # INV-S-MEM-A-1 / PCDN-SOS-09-A-003: sos:name must be unique within the
    # composed scope path. At v1 chart-only scope (no chart-include yet —
    # see PCDN-SOS-09-A-002 outstanding follow-up), the composed scope path
    # collapses to chart-level. Duplicate sos:name within one chart is an
    # error.
    seen_names: dict[str, str] = {}
    for ch in channels:
        if ch.name in seen_names:
            raise Sos09AnnotationError(
                f"duplicate sos:name={ch.name!r} on elements "
                f"<{seen_names[ch.name]}> and <{ch.element_path}>; "
                f"sos:name must be unique within the composed scope path",
                element_path=ch.element_path,
                rule="§5.4(1)",
                key="sos:name",
            )
        seen_names[ch.name] = ch.element_path

    return ChartAnnotations(
        channels=tuple(channels),
        mpu_background=mpu_background,
    )


__all__ = [
    "BitField",
    "BitLayout",
    "ChannelAnnotation",
    "ChartAnnotations",
    "Sos09AnnotationError",
    "parse_chart_annotations",
    "validate_placement",
    # Frozen enums exported for downstream emitters that want to mirror them.
    "ALLOWED_KINDS",
    "ALLOWED_DIRS",
    "ALLOWED_ZONES",
    "ALLOWED_MPU_ATTRS",
    "ALLOWED_MPU_BACKGROUNDS",
    "ALLOWED_PLACEMENTS",
    "ALLOWED_BIT_FIELD_ACCESS",
    "ALLOWED_BIT_FIELD_SIDE_EFFECTS",
    "PERMITTED_SOS_KEYS",
    "CHART_ROOT_KEYS",
    "DEFAULT_MPU_BACKGROUND",
]
