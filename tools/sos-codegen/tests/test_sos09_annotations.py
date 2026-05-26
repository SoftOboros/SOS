"""Tests for `sos09_annotations.py` — SOS-09-A chart annotation parser.

Authority: `docs/concepts/SOS-09-A-CONCEPTS.md` (ratified 2026-05-25).
Covers §5.3 parsing rule, §5.4 validation rules (1)-(9), and the umbrella
§5.3 atomicity-class default-inference rule.
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

from loader import load_chart  # noqa: E402
from sos09_annotations import (  # noqa: E402
    ALLOWED_DIRS,
    ALLOWED_KINDS,
    ALLOWED_MPU_ATTRS,
    ALLOWED_MPU_BACKGROUNDS,
    ALLOWED_ZONES,
    BitField,
    BitLayout,
    ChannelAnnotation,
    ChartAnnotations,
    DEFAULT_MPU_BACKGROUND,
    Sos09AnnotationError,
    parse_chart_annotations,
)

# Stable test UUIDs (RFC 4122 v4 form). Hard-coded so tests are deterministic.
UUID_A = "550e8400-e29b-41d4-a716-446655440000"
UUID_B = "550e8400-e29b-41d4-a716-446655440001"
UUID_C = "550e8400-e29b-41d4-a716-446655440002"
UUID_D = "550e8400-e29b-41d4-a716-446655440003"
UUID_E = "550e8400-e29b-41d4-a716-446655440004"


# ---------------------------------------------------------------------------
# Helpers for building scjson-shaped chart dicts directly (faster than
# round-tripping through scjson for every negative case).
# ---------------------------------------------------------------------------


def _wrap_other_attrs(payload: dict) -> dict:
    """Build the scjson-0.3.6 shape: outer dict with inner JSON string."""
    return {"other_attributes": json.dumps(payload)}


def _state(state_id: str, sos_attrs: dict | None = None, **extra) -> dict:
    node: dict = {"id": state_id}
    if sos_attrs is not None:
        node["other_attributes"] = _wrap_other_attrs(sos_attrs)
    node.update(extra)
    return node


def _parallel(par_id: str, sos_attrs: dict | None, children: list[dict]) -> dict:
    node: dict = {"id": par_id, "state": children}
    if sos_attrs is not None:
        node["other_attributes"] = _wrap_other_attrs(sos_attrs)
    return node


def _chart(states: list[dict], root_attrs: dict | None = None,
           parallels: list[dict] | None = None) -> dict:
    chart: dict = {
        "state": states,
        "version": 1.0,
        "datamodel_attribute": "ecmascript",
    }
    if parallels is not None:
        chart["parallel"] = parallels
    if root_attrs is not None:
        chart["other_attributes"] = _wrap_other_attrs(root_attrs)
    return chart


def _minimal_status(uuid: str = UUID_A, name: str = "ch") -> dict:
    return {
        "sos:id": uuid,
        "sos:name": name,
        "sos:kind": "status",
        "sos:dir": "hw→sw",
    }


def _minimal_command(uuid: str = UUID_B, name: str = "cmd") -> dict:
    return {
        "sos:id": uuid,
        "sos:name": name,
        "sos:kind": "command",
        "sos:dir": "sw→hw",
    }


def _minimal_shared(uuid: str = UUID_C, name: str = "shr") -> dict:
    return {
        "sos:id": uuid,
        "sos:name": name,
        "sos:kind": "shared",
        "sos:dir": "bidirectional",
    }


def _minimal_queue(uuid: str = UUID_D, name: str = "q") -> dict:
    return {
        "sos:id": uuid,
        "sos:name": name,
        "sos:kind": "queue",
        "sos:dir": "bidirectional",
    }


# ---------------------------------------------------------------------------
# Smoke / round-trip
# ---------------------------------------------------------------------------


def test_smoke_chart_round_trip_via_scjson():
    """Round-trip: load smoke fixture through scjson + loader, parse annotations."""
    fixture = _TOOLS_DIR / "tests" / "fixtures" / "sos09_smoke_chart.scxml"
    ast = load_chart(fixture)
    anns = parse_chart_annotations(ast.raw_scjson)
    assert isinstance(anns, ChartAnnotations)
    assert len(anns.channels) == 4
    assert anns.mpu_background == "strict"


def test_smoke_chart_kinds_and_dirs_resolved():
    fixture = _TOOLS_DIR / "tests" / "fixtures" / "sos09_smoke_chart.scxml"
    ast = load_chart(fixture)
    anns = parse_chart_annotations(ast.raw_scjson)
    by_name = {c.name: c for c in anns.channels}
    assert set(by_name) == {"rx_status", "tx_command", "io_queue", "shared_block"}
    assert by_name["rx_status"].kind == "status"
    assert by_name["rx_status"].dir == "hw→sw"
    assert by_name["tx_command"].kind == "command"
    assert by_name["tx_command"].dir == "sw→hw"
    assert by_name["io_queue"].kind == "queue"
    assert by_name["io_queue"].dir == "bidirectional"
    assert by_name["shared_block"].kind == "shared"
    assert by_name["shared_block"].dir == "bidirectional"


def test_smoke_chart_status_has_irq_and_bit_layout():
    fixture = _TOOLS_DIR / "tests" / "fixtures" / "sos09_smoke_chart.scxml"
    ast = load_chart(fixture)
    anns = parse_chart_annotations(ast.raw_scjson)
    rx = next(c for c in anns.channels if c.name == "rx_status")
    assert rx.irq == "rx_irq"
    assert rx.bit_layout is not None
    assert len(rx.bit_layout.fields) == 3
    assert rx.bit_layout.fields[0].name == "ready"
    assert rx.bit_layout.fields[0].access == "RO"
    assert rx.bit_layout.fields[0].side_effect == "clear-on-read"


def test_smoke_chart_shared_has_mutex_and_mpu_attr():
    fixture = _TOOLS_DIR / "tests" / "fixtures" / "sos09_smoke_chart.scxml"
    ast = load_chart(fixture)
    anns = parse_chart_annotations(ast.raw_scjson)
    sh = next(c for c in anns.channels if c.name == "shared_block")
    assert sh.mutex == "shared_lock"
    assert sh.mpu_attr == "cacheable"
    assert sh.atomicity == "mutex-required"


# ---------------------------------------------------------------------------
# Positive cases — chart-dict shape directly
# ---------------------------------------------------------------------------


def test_minimal_status_channel_parses():
    chart = _chart([_state("S1", _minimal_status())])
    anns = parse_chart_annotations(chart)
    assert len(anns.channels) == 1
    ch = anns.channels[0]
    assert ch.id == UUID_A
    assert ch.name == "ch"
    assert ch.kind == "status"
    assert ch.dir == "hw→sw"
    assert ch.zone == "privileged"  # default
    assert ch.width == 32  # default
    assert ch.atomicity == "atomic"  # status default per umbrella §5.3
    assert ch.bit_layout is None
    assert ch.irq is None
    assert ch.mutex is None
    assert ch.mpu_attr is None
    assert ch.extras == {}


def test_minimal_command_channel_atomicity_atomic():
    chart = _chart([_state("S1", _minimal_command())])
    anns = parse_chart_annotations(chart)
    assert anns.channels[0].atomicity == "atomic"


def test_minimal_queue_channel_atomicity_atomic():
    chart = _chart([_state("S1", _minimal_queue())])
    anns = parse_chart_annotations(chart)
    assert anns.channels[0].atomicity == "atomic"


def test_minimal_shared_channel_atomicity_mutex_required():
    """Umbrella §5.3 default-inference: shared -> mutex-required."""
    chart = _chart([_state("S1", _minimal_shared())])
    anns = parse_chart_annotations(chart)
    assert anns.channels[0].atomicity == "mutex-required"


def test_atomicity_explicit_token_yields_kind_default():
    """`sos:atomicity="explicit"` is a metavalue; resolves to kind-default."""
    attrs = {**_minimal_status(), "sos:atomicity": "explicit"}
    chart = _chart([_state("S1", attrs)])
    assert parse_chart_annotations(chart).channels[0].atomicity == "atomic"


def test_atomicity_implicit_token_yields_kind_default():
    attrs = {**_minimal_shared(), "sos:atomicity": "implicit"}
    chart = _chart([_state("S1", attrs)])
    assert parse_chart_annotations(chart).channels[0].atomicity == "mutex-required"


def test_atomicity_atomic_override():
    attrs = {**_minimal_shared(), "sos:atomicity": "atomic"}
    chart = _chart([_state("S1", attrs)])
    assert parse_chart_annotations(chart).channels[0].atomicity == "atomic"


def test_atomicity_mutex_required_override():
    attrs = {**_minimal_status(), "sos:atomicity": "mutex-required"}
    chart = _chart([_state("S1", attrs)])
    assert parse_chart_annotations(chart).channels[0].atomicity == "mutex-required"


def test_zone_default_privileged():
    chart = _chart([_state("S1", _minimal_status())])
    assert parse_chart_annotations(chart).channels[0].zone == "privileged"


def test_zone_unprivileged_override():
    attrs = {**_minimal_status(), "sos:zone": "unprivileged"}
    chart = _chart([_state("S1", attrs)])
    assert parse_chart_annotations(chart).channels[0].zone == "unprivileged"


def test_width_default_32():
    chart = _chart([_state("S1", _minimal_status())])
    assert parse_chart_annotations(chart).channels[0].width == 32


def test_width_explicit_16():
    attrs = {**_minimal_status(), "sos:width": 16}
    chart = _chart([_state("S1", attrs)])
    assert parse_chart_annotations(chart).channels[0].width == 16


def test_mpu_background_default_kernel_default():
    chart = _chart([_state("S1", _minimal_status())])
    assert parse_chart_annotations(chart).mpu_background == "kernel_default"


def test_mpu_background_strict_override():
    chart = _chart(
        [_state("S1", _minimal_status())],
        root_attrs={"sos:mpu_background": "strict"},
    )
    assert parse_chart_annotations(chart).mpu_background == "strict"


def test_mpu_attr_preserved_on_channel():
    attrs = {**_minimal_shared(), "sos:mpu_attr": "non_cacheable"}
    chart = _chart([_state("S1", attrs)])
    assert parse_chart_annotations(chart).channels[0].mpu_attr == "non_cacheable"


def test_irq_only_on_status_hw_to_sw():
    attrs = {**_minimal_status(), "sos:irq": "rx_irq"}
    chart = _chart([_state("S1", attrs)])
    assert parse_chart_annotations(chart).channels[0].irq == "rx_irq"


def test_mutex_only_on_shared():
    attrs = {**_minimal_shared(), "sos:mutex": "shared_lock"}
    chart = _chart([_state("S1", attrs)])
    assert parse_chart_annotations(chart).channels[0].mutex == "shared_lock"


def test_parallel_carries_channel():
    chart = _chart(
        states=[],
        parallels=[_parallel("P1", _minimal_queue(), children=[])],
    )
    anns = parse_chart_annotations(chart)
    assert len(anns.channels) == 1
    assert anns.channels[0].name == "q"
    assert anns.channels[0].element_path == "P1"


def test_nested_state_carries_channel():
    """A channel declared on a deeply-nested <state> is collected."""
    inner = _state("INNER", _minimal_status(name="inner_ch"))
    outer = {
        "id": "OUTER",
        "state": [inner],
    }
    chart = _chart([outer])
    anns = parse_chart_annotations(chart)
    assert len(anns.channels) == 1
    assert anns.channels[0].name == "inner_ch"
    assert anns.channels[0].element_path == "OUTER.INNER"


def test_extras_forward_compat():
    """Unknown sos:-prefixed keys surface in `extras` rather than rejecting."""
    attrs = {**_minimal_status(), "sos:future_key_for_phase_z": "value"}
    chart = _chart([_state("S1", attrs)])
    ch = parse_chart_annotations(chart).channels[0]
    assert ch.extras == {"sos:future_key_for_phase_z": "value"}


def test_non_sos_keys_ignored():
    """iState layout keys (`position_x`) pass through without affecting parse."""
    attrs = {"position_x": 100, "position_y": 200, **_minimal_status()}
    chart = _chart([_state("S1", attrs)])
    anns = parse_chart_annotations(chart)
    assert len(anns.channels) == 1
    assert anns.channels[0].extras == {}


def test_chart_with_no_annotations_yields_empty_channels():
    chart = _chart([{"id": "S1"}])
    anns = parse_chart_annotations(chart)
    assert anns.channels == ()
    assert anns.mpu_background == DEFAULT_MPU_BACKGROUND


# ---------------------------------------------------------------------------
# Negative cases — §5.4 validation rules
# ---------------------------------------------------------------------------


def test_missing_sos_id_raises():
    attrs = _minimal_status()
    del attrs["sos:id"]
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(2\\)"):
        parse_chart_annotations(chart)


def test_missing_sos_name_raises():
    attrs = _minimal_status()
    del attrs["sos:name"]
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(2\\)"):
        parse_chart_annotations(chart)


def test_missing_sos_kind_raises():
    attrs = _minimal_status()
    del attrs["sos:kind"]
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(2\\)"):
        parse_chart_annotations(chart)


def test_missing_sos_dir_raises():
    attrs = _minimal_status()
    del attrs["sos:dir"]
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(2\\)"):
        parse_chart_annotations(chart)


def test_bad_uuid_raises():
    attrs = {**_minimal_status(), "sos:id": "not-a-uuid"}
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(7\\)"):
        parse_chart_annotations(chart)


def test_uuid_wrong_segment_lengths_raises():
    attrs = {**_minimal_status(), "sos:id": "550e8400-e29b-41d4-a716-44665544000"}  # 11 in tail
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(7\\)"):
        parse_chart_annotations(chart)


def test_name_not_sv_identifier_dash_raises():
    attrs = {**_minimal_status(), "sos:name": "rx-path"}
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(7\\)"):
        parse_chart_annotations(chart)


def test_name_not_sv_identifier_dot_raises():
    attrs = {**_minimal_status(), "sos:name": "rx.path"}
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(7\\)"):
        parse_chart_annotations(chart)


def test_name_starting_with_digit_raises():
    attrs = {**_minimal_status(), "sos:name": "1path"}
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(7\\)"):
        parse_chart_annotations(chart)


def test_name_with_whitespace_raises():
    attrs = {**_minimal_status(), "sos:name": "rx path"}
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(7\\)"):
        parse_chart_annotations(chart)


def test_kind_typo_raises():
    attrs = {**_minimal_status(), "sos:kind": "statu"}
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(3\\)"):
        parse_chart_annotations(chart)


def test_dir_typo_raises():
    attrs = {**_minimal_status(), "sos:dir": "hw->sw"}  # ASCII, not Unicode arrow
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(3\\)"):
        parse_chart_annotations(chart)


def test_status_with_sw_to_hw_dir_raises():
    """§5.4(4) kind/dir matrix — status MUST be hw->sw."""
    attrs = {**_minimal_status(), "sos:dir": "sw→hw"}
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(4\\)"):
        parse_chart_annotations(chart)


def test_command_with_bidirectional_dir_raises():
    attrs = {**_minimal_command(), "sos:dir": "bidirectional"}
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(4\\)"):
        parse_chart_annotations(chart)


def test_shared_with_hw_to_sw_dir_raises():
    attrs = {**_minimal_shared(), "sos:dir": "hw→sw"}
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(4\\)"):
        parse_chart_annotations(chart)


def test_duplicate_sos_id_raises():
    """INV-S-MEM-A-1 / §5.4(1) unique sos:id within chart."""
    a = _state("S1", _minimal_status(uuid=UUID_A, name="a"))
    b = _state("S2", _minimal_command(uuid=UUID_A, name="b"))  # same UUID
    chart = _chart([a, b])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(1\\)"):
        parse_chart_annotations(chart)


def test_duplicate_sos_name_raises():
    """INV-S-MEM-A-1 / PCDN-SOS-09-A-003: sos:name uniqueness within composed scope."""
    a = _state("S1", _minimal_status(uuid=UUID_A, name="dup"))
    b = _state("S2", _minimal_command(uuid=UUID_B, name="dup"))
    chart = _chart([a, b])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(1\\)"):
        parse_chart_annotations(chart)


def test_zone_typo_raises():
    attrs = {**_minimal_status(), "sos:zone": "privledged"}
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(3\\)"):
        parse_chart_annotations(chart)


def test_atomicity_garbage_raises():
    attrs = {**_minimal_status(), "sos:atomicity": "maybe"}
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(3\\)"):
        parse_chart_annotations(chart)


def test_width_too_large_raises():
    attrs = {**_minimal_status(), "sos:width": 65}
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(6\\)"):
        parse_chart_annotations(chart)


def test_width_zero_raises():
    attrs = {**_minimal_status(), "sos:width": 0}
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(6\\)"):
        parse_chart_annotations(chart)


def test_width_negative_raises():
    attrs = {**_minimal_status(), "sos:width": -1}
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(6\\)"):
        parse_chart_annotations(chart)


def test_width_non_integer_string_raises():
    attrs = {**_minimal_status(), "sos:width": "thirty-two"}
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(6\\)"):
        parse_chart_annotations(chart)


def test_irq_on_command_kind_raises():
    """§5.4(5) sos:irq only on kind=status+dir=hw->sw."""
    attrs = {**_minimal_command(), "sos:irq": "evt"}
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(5\\)"):
        parse_chart_annotations(chart)


def test_irq_on_queue_kind_raises():
    attrs = {**_minimal_queue(), "sos:irq": "evt"}
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(5\\)"):
        parse_chart_annotations(chart)


def test_mutex_on_status_kind_raises():
    """§5.4(5) sos:mutex only on kind=shared."""
    attrs = {**_minimal_status(), "sos:mutex": "lock"}
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(5\\)"):
        parse_chart_annotations(chart)


def test_mutex_on_queue_kind_raises():
    attrs = {**_minimal_queue(), "sos:mutex": "lock"}
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(5\\)"):
        parse_chart_annotations(chart)


def test_bit_layout_overlap_raises():
    layout = {
        "fields": [
            {"name": "a", "start_bit": 0, "width": 4, "access": "RW"},
            {"name": "b", "start_bit": 2, "width": 4, "access": "RW"},  # overlaps a
        ]
    }
    attrs = {**_minimal_status(), "sos:bit_layout": layout}
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError, match="overlap"):
        parse_chart_annotations(chart)


def test_bit_layout_exceeds_width_raises():
    layout = {
        "fields": [
            {"name": "a", "start_bit": 30, "width": 8, "access": "RW"},  # 30+8=38 > 32
        ]
    }
    attrs = {**_minimal_status(), "sos:bit_layout": layout}
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError, match="extends beyond"):
        parse_chart_annotations(chart)


def test_bit_layout_bad_access_raises():
    layout = {
        "fields": [
            {"name": "a", "start_bit": 0, "width": 4, "access": "WRX"},
        ]
    }
    attrs = {**_minimal_status(), "sos:bit_layout": layout}
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(3\\)"):
        parse_chart_annotations(chart)


def test_bit_layout_field_name_not_sv_identifier_raises():
    layout = {
        "fields": [
            {"name": "bad-name", "start_bit": 0, "width": 4, "access": "RW"},
        ]
    }
    attrs = {**_minimal_status(), "sos:bit_layout": layout}
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(7\\)"):
        parse_chart_annotations(chart)


def test_bit_layout_bad_side_effect_raises():
    layout = {
        "fields": [
            {"name": "a", "start_bit": 0, "width": 4, "access": "RW",
             "side_effect": "fire-the-missiles"},
        ]
    }
    attrs = {**_minimal_status(), "sos:bit_layout": layout}
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(3\\)"):
        parse_chart_annotations(chart)


def test_bit_layout_fields_must_be_list():
    layout = {"fields": "not-a-list"}
    attrs = {**_minimal_status(), "sos:bit_layout": layout}
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(3\\)"):
        parse_chart_annotations(chart)


def test_mpu_attr_bad_value_raises():
    attrs = {**_minimal_shared(), "sos:mpu_attr": "supercharge"}
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(3\\)"):
        parse_chart_annotations(chart)


def test_mpu_background_typo_raises():
    chart = _chart(
        [_state("S1", _minimal_status())],
        root_attrs={"sos:mpu_background": "stricked"},
    )
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(3\\)"):
        parse_chart_annotations(chart)


def test_sos_key_on_chart_root_other_than_mpu_background_raises():
    chart = _chart(
        [_state("S1", _minimal_status())],
        root_attrs={"sos:id": UUID_A, "sos:name": "x"},
    )
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(8\\)"):
        parse_chart_annotations(chart)


def test_sos_key_on_transition_raises():
    """§5.4(8) parent-context validity — sos: keys on <transition> are illegal."""
    state = {
        "id": "S1",
        "transition": [{
            "event": "go",
            "target": ["S2"],
            "other_attributes": _wrap_other_attrs(_minimal_status())["other_attributes"]
                if False else _wrap_other_attrs(_minimal_status()),
        }],
    }
    chart = _chart([state, {"id": "S2"}])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(8\\)"):
        parse_chart_annotations(chart)


def test_sos_key_on_onentry_raises():
    state = {
        "id": "S1",
        "onentry": [{
            "other_attributes": _wrap_other_attrs(_minimal_status()),
        }],
    }
    chart = _chart([state])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(8\\)"):
        parse_chart_annotations(chart)


def test_malformed_other_attributes_json_raises():
    """A non-JSON value in the inner other_attributes string is a parse error."""
    chart = _chart([{"id": "S1", "other_attributes": {"other_attributes": "not json"}}])
    with pytest.raises(Sos09AnnotationError, match="malformed"):
        parse_chart_annotations(chart)


def test_other_attributes_not_object_raises():
    """The inner JSON must parse to an object, not e.g. an array."""
    chart = _chart([{"id": "S1", "other_attributes": {"other_attributes": "[1, 2, 3]"}}])
    with pytest.raises(Sos09AnnotationError, match="must be an object"):
        parse_chart_annotations(chart)


def test_parse_input_must_be_dict():
    with pytest.raises(Sos09AnnotationError):
        parse_chart_annotations("not a dict")  # type: ignore[arg-type]


def test_irq_empty_string_raises():
    attrs = {**_minimal_status(), "sos:irq": ""}
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError):
        parse_chart_annotations(chart)


def test_error_carries_element_path_and_rule():
    attrs = {**_minimal_status(), "sos:kind": "statu"}
    chart = _chart([_state("STATE_X", attrs)])
    with pytest.raises(Sos09AnnotationError) as exc:
        parse_chart_annotations(chart)
    assert exc.value.element_path == "STATE_X"
    assert exc.value.rule == "§5.4(3)"
    assert exc.value.key == "sos:kind"


# ---------------------------------------------------------------------------
# PCDN-SOS-09-007 follow-on amendment 2026-05-26: §5.2 ten-key -> twelve-key
# (added sos:channel_group + sos:privilege_region; both optional, both
# SV-identifier-shaped; the inheritance walk is a consumer concern, NOT
# implemented in this parser — absence surfaces as None).
# ---------------------------------------------------------------------------


def test_channel_group_and_privilege_region_present_parse():
    """Happy path: both new keys present with valid SV-identifiers parse."""
    attrs = {
        **_minimal_status(),
        "sos:channel_group": "rx_group",
        "sos:privilege_region": "kernel_region",
    }
    chart = _chart([_state("S1", attrs)])
    anns = parse_chart_annotations(chart)
    assert len(anns.channels) == 1
    ch = anns.channels[0]
    assert ch.channel_group == "rx_group"
    assert ch.privilege_region == "kernel_region"


def test_channel_group_and_privilege_region_absent_yields_none():
    """Happy path: both keys absent -> both fields are None.

    The inheritance walk (default-from-enclosing-parallel/compound-state
    declaration; ultimate fallback `"default"`) is a consumer-side concern
    per PCDN-SOS-09-007. The parser surfaces raw Optional[str].
    """
    chart = _chart([_state("S1", _minimal_status())])
    anns = parse_chart_annotations(chart)
    assert len(anns.channels) == 1
    ch = anns.channels[0]
    assert ch.channel_group is None
    assert ch.privilege_region is None


def test_channel_group_invalid_sv_identifier_raises():
    """Error path: sos:channel_group with invalid SV-identifier shape -> §5.4(7)."""
    attrs = {**_minimal_status(), "sos:channel_group": "rx-group"}  # hyphen illegal
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(7\\)") as exc:
        parse_chart_annotations(chart)
    assert exc.value.key == "sos:channel_group"


def test_privilege_region_invalid_sv_identifier_raises():
    """Error path: sos:privilege_region with invalid SV-identifier shape -> §5.4(7)."""
    attrs = {**_minimal_status(), "sos:privilege_region": "1bad"}  # leading digit
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(7\\)") as exc:
        parse_chart_annotations(chart)
    assert exc.value.key == "sos:privilege_region"


def test_channel_group_dot_in_identifier_raises():
    """Error path: dot is not allowed in SV-identifier (sos:channel_group)."""
    attrs = {**_minimal_status(), "sos:channel_group": "rx.group"}
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(7\\)"):
        parse_chart_annotations(chart)


def test_privilege_region_whitespace_raises():
    """Error path: whitespace in SV-identifier (sos:privilege_region)."""
    attrs = {**_minimal_status(), "sos:privilege_region": "kernel region"}
    chart = _chart([_state("S1", attrs)])
    with pytest.raises(Sos09AnnotationError, match="§5.4\\(7\\)"):
        parse_chart_annotations(chart)


def test_only_channel_group_present_privilege_region_none():
    """One key present, the other absent — both surface independently."""
    attrs = {**_minimal_status(), "sos:channel_group": "rx_group"}
    chart = _chart([_state("S1", attrs)])
    ch = parse_chart_annotations(chart).channels[0]
    assert ch.channel_group == "rx_group"
    assert ch.privilege_region is None
