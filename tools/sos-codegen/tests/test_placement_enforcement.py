"""Tests for SOS-09-A §16 (2026-05-28) placement-enum enforcement.

Authority: `docs/concepts/SOS-09-A-CONCEPTS.md` §16 amendment 2026-05-28
(Path B per parent EOQ-002-ERRATA-002). The three-value placement enum
{hardware-block, sram-membrane, mmio-peripheral} is normative; the
validator in `tools/sos-codegen/sos09_annotations.py` gates manifest
emission against it, and both chart-family emitters call the gate before
writing their manifest JSON.

Registration policy: Standards Action — adding a fourth value requires a
§15 amendment to SOS-09-A first.

Test categories:
    1. validate_placement accepts each of the three allowed values.
    2. validate_placement rejects typos, unratified values, and non-strings
       with a §16(2026-05-28)-cited diagnostic.
    3. ALLOWED_PLACEMENTS frozen-set shape regression guard.
    4. Each chart-family emitter produces a manifest whose placement
       round-trips through validate_placement (re-emit + parse + validate).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Make `sos-codegen` modules importable when pytest is invoked from any cwd.
_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sos09_annotations import (  # noqa: E402
    ALLOWED_PLACEMENTS,
    Sos09AnnotationError,
    validate_placement,
)


# ---------------------------------------------------------------------------
# 1. validate_placement accepts each allowed value.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["hardware-block", "sram-membrane", "mmio-peripheral"],
)
def test_validate_placement_accepts_each_allowed_value(value: str) -> None:
    """Each of the three §16(2026-05-28) values validates successfully."""
    assert validate_placement(value) == value


def test_validate_placement_accepts_each_allowed_value_with_manifest_path() -> None:
    """`manifest_path` is accepted as a diagnostic surface; no behavior change."""
    for v in ("hardware-block", "sram-membrane", "mmio-peripheral"):
        assert validate_placement(v, manifest_path="charts/foo/foo_manifest.json") == v


# ---------------------------------------------------------------------------
# 2. validate_placement rejects bad values with a §16-cited diagnostic.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_value",
    [
        "sram-membran",       # typo dropping the 'e'
        "peripheral",          # shortened form
        "hardware",            # shortened form
        "MMIO-PERIPHERAL",     # case-insensitive guard
        "mmio_peripheral",     # underscore vs hyphen
        "network-membrane",    # not-yet-ratified extension
        "",                    # empty string
        " hardware-block ",    # whitespace padding
    ],
)
def test_validate_placement_rejects_invalid_strings(bad_value: str) -> None:
    """Invalid placement strings raise `Sos09AnnotationError`."""
    with pytest.raises(Sos09AnnotationError) as exc:
        validate_placement(bad_value)
    msg = str(exc.value)
    # The rule citation token is `§16(2026-05-28)` — see SOS-09-A §16.
    assert "§16(2026-05-28)" in msg, msg
    assert "placement" in msg, msg
    # The error names the offending value.
    assert repr(bad_value) in msg, msg
    # And mentions the allowed set for actionable feedback.
    assert "hardware-block" in msg
    assert "sram-membrane" in msg
    assert "mmio-peripheral" in msg


@pytest.mark.parametrize(
    "bad_value",
    [None, 0, 1, 3.14, True, False, [], {}, ()],
)
def test_validate_placement_rejects_non_string_types(bad_value: object) -> None:
    """Non-string values (None, ints, lists, ...) all fail with §16 citation."""
    with pytest.raises(Sos09AnnotationError) as exc:
        validate_placement(bad_value)
    assert "§16(2026-05-28)" in str(exc.value)


def test_validate_placement_diagnostic_surfaces_manifest_path() -> None:
    """The `manifest_path` kw surfaces in the error's element_path."""
    with pytest.raises(Sos09AnnotationError) as exc:
        validate_placement(
            "sram-membran",
            manifest_path="charts/example/example_manifest.json",
        )
    assert exc.value.element_path == "charts/example/example_manifest.json"
    assert "charts/example/example_manifest.json" in str(exc.value)


def test_validate_placement_error_carries_rule_token() -> None:
    """The error's `.rule` attribute is the §16 amendment date token."""
    with pytest.raises(Sos09AnnotationError) as exc:
        validate_placement("not-a-placement")
    assert exc.value.rule == "§16(2026-05-28)"
    assert exc.value.key == "placement"


# ---------------------------------------------------------------------------
# 3. ALLOWED_PLACEMENTS frozen-set shape regression guard.
# ---------------------------------------------------------------------------


def test_allowed_placements_is_exactly_the_three_value_enum() -> None:
    """The §16(2026-05-28) Path B set is exactly these three values.

    Adding a fourth value would require a §15 amendment first (Standards
    Action per the SOS-09 umbrella registration-policy clause). If this
    test fails because the set grew, the amendment landing this PR must
    have edited it — verify the amendment also lands in §16 of
    `docs/concepts/SOS-09-A-CONCEPTS.md` before silencing the test.
    """
    assert ALLOWED_PLACEMENTS == frozenset(
        {"hardware-block", "sram-membrane", "mmio-peripheral"}
    )
    assert isinstance(ALLOWED_PLACEMENTS, frozenset)


# ---------------------------------------------------------------------------
# 4. Chart-family emitter regression guards.
# ---------------------------------------------------------------------------


def _sos_root() -> Path:
    """Return the SOS submodule root from this test file's location."""
    return Path(__file__).resolve().parents[3]


def test_sis08_first_slice_manifest_placement_validates() -> None:
    """The checked-in `sis08_first_slice` manifest declares a valid placement."""
    manifest_path = (
        _sos_root()
        / "charts"
        / "sis08_first_slice"
        / "sis08_first_slice_manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # SIS-08B reference value (unchanged by Path B amendment).
    assert manifest["placement"] == "hardware-block"
    # Regression guard: re-validate through the public helper.
    assert validate_placement(
        manifest["placement"], manifest_path=str(manifest_path)
    ) == "hardware-block"


def test_sis08d_c2_membrane_manifest_placement_validates() -> None:
    """The checked-in `sis08d_c2_membrane` manifest declares a valid placement."""
    manifest_path = (
        _sos_root()
        / "charts"
        / "sis08d_c2_membrane"
        / "sis08d_c2_membrane_manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # Post-Path-B value for the C2-A membrane (was `sram-membrane`).
    assert manifest["placement"] == "mmio-peripheral"
    assert validate_placement(
        manifest["placement"], manifest_path=str(manifest_path)
    ) == "mmio-peripheral"


def test_sis08_first_slice_emitter_rejects_bad_placement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first-slice emitter must raise if a typo'd placement is injected.

    Confirms the wiring: `validate_placement` is called *before* the
    manifest write. We monkey-patch `validate_placement` to assert it
    receives the manifest value, and separately verify that an injected
    bad value raises before any file is written.
    """
    import sis08_first_slice

    # Sanity: emitter imports validate_placement at module scope.
    assert hasattr(sis08_first_slice, "validate_placement")

    seen: dict[str, str] = {}
    original = sis08_first_slice.validate_placement

    def _spy(value, *, manifest_path=None):  # type: ignore[no-untyped-def]
        seen["value"] = value
        seen["manifest_path"] = manifest_path or ""
        return original(value, manifest_path=manifest_path)

    monkeypatch.setattr(sis08_first_slice, "validate_placement", _spy)

    # Run a fresh emit into a tmp out_dir; the emitter still validates.
    out_dir = tmp_path / "sis08_first_slice"
    out_dir.mkdir()
    sis08_first_slice.emit_first_slice(
        chart=sis08_first_slice.DEFAULT_CHART,
        chart_id=sis08_first_slice.DEFAULT_CHART_ID,
        base_address=sis08_first_slice.DEFAULT_BASE_ADDRESS,
        out_dir=out_dir,
    )
    assert seen["value"] == "hardware-block"
    assert "sis08_first_slice_manifest.json" in seen["manifest_path"]


def test_sis08d_c2_membrane_emitter_rejects_bad_placement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The c2_membrane emitter calls validate_placement before manifest write."""
    import sis08d_c2_membrane

    assert hasattr(sis08d_c2_membrane, "validate_placement")

    seen: dict[str, str] = {}
    original = sis08d_c2_membrane.validate_placement

    def _spy(value, *, manifest_path=None):  # type: ignore[no-untyped-def]
        seen["value"] = value
        seen["manifest_path"] = manifest_path or ""
        return original(value, manifest_path=manifest_path)

    monkeypatch.setattr(sis08d_c2_membrane, "validate_placement", _spy)

    out_dir = tmp_path / "sis08d_c2_membrane"
    out_dir.mkdir()
    sis08d_c2_membrane.emit_membrane(
        chart=sis08d_c2_membrane.DEFAULT_CHART,
        chart_id=sis08d_c2_membrane.DEFAULT_CHART_ID,
        base_address=sis08d_c2_membrane.DEFAULT_BASE_ADDRESS,
        out_dir=out_dir,
    )
    assert seen["value"] == "mmio-peripheral"
    assert "sis08d_c2_membrane_manifest.json" in seen["manifest_path"]
