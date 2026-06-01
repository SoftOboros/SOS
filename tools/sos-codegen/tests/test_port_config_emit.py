"""Tests for SOS-04-A ``port_config`` parsing and Rust/C emission."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from port_config_emit import (  # noqa: E402
    DEFAULT_STACK_REGION,
    PortConfigBounds,
    PortConfigEmitError,
    PortConfigError,
    emit_c_port_config,
    emit_rust_port_config,
    parse_port_config_from_chart,
    read_port_config_manifest,
    write_port_config_manifest,
)


SOS_NS = "https://softoboros.com/sos/1.0"
TASK_CONFIG_QN = f"{{{SOS_NS}}}task_config"
TASK_QN = f"{{{SOS_NS}}}task"
SEM_QN = f"{{{SOS_NS}}}sem"
QUEUE_QN = f"{{{SOS_NS}}}queue"


DAA_WORKED_EXAMPLE_DSL = """
port_config {
  tick_hz: 1000
  kernel_stack_words: 1024
  tasks: [
    { id: 0, prio: 0, stack_words: 128,  stack_region: ".task_stacks",     entry: "idle_task"   },  // idle
    { id: 1, prio: 1, stack_words: 2048, stack_region: ".sos_task_stacks", entry: "render_task" },
    { id: 2, prio: 4, stack_words: 512,  stack_region: ".sos_task_stacks", entry: "audio_task"  },
  ]
  sems:    [ { id: 0, max: 1, initial: 0 } ]
  queues:  [ ]
}
"""


def _wrap_other_attrs(payload: dict) -> dict:
    return {"other_attributes": json.dumps(payload)}


def _chart_with_task_config(task_config: dict, *, bounds: dict | None = None) -> dict:
    constants = {
        "MAX_TASKS": "8",
        "MAX_PRIO": "8",
        "MAX_SEMS": "8",
        "MAX_QUEUES": "4",
    }
    if bounds:
        constants.update(bounds)
    return {
        "version": 1.0,
        "datamodel_attribute": "ecmascript",
        "datamodel": [
            {
                "data": [
                    {"id": key, "expr": value}
                    for key, value in constants.items()
                ]
            }
        ],
        "other_element": [task_config],
    }


def _worked_example_chart() -> dict:
    return _chart_with_task_config(
        {"qname": TASK_CONFIG_QN, "text": DAA_WORKED_EXAMPLE_DSL}
    )


def _attr_child_chart(*, task_prio: str = "1", omit_region: bool = False) -> dict:
    task_attrs = {
        "id": "1",
        "prio": task_prio,
        "stack_words": "512",
        "entry": "worker_task",
    }
    if not omit_region:
        task_attrs["stack_region"] = DEFAULT_STACK_REGION
    return _chart_with_task_config(
        {
            "qname": TASK_CONFIG_QN,
            "attributes": {"tick_hz": "1000", "kernel_stack_words": "1024"},
            "children": [
                {
                    "qname": TASK_QN,
                    "attributes": {
                        "id": "0",
                        "prio": "0",
                        "stack_words": "128",
                        "entry": "idle_task",
                    },
                },
                {"qname": TASK_QN, "attributes": task_attrs},
                {"qname": SEM_QN, "attributes": {"id": "0", "max": "1", "initial": "0"}},
                {"qname": QUEUE_QN, "attributes": {"id": "0", "cap": "4"}},
            ],
        }
    )


def test_daa_08_worked_example_lowers_through_rust_and_c_emitters():
    config = parse_port_config_from_chart(_worked_example_chart())

    assert config.tick_hz == 1000
    assert config.kernel_stack_words == 1024
    assert [(t.id, t.prio, t.stack_words, t.stack_region, t.entry) for t in config.tasks] == [
        (0, 0, 128, ".task_stacks", "idle_task"),
        (1, 1, 2048, ".sos_task_stacks", "render_task"),
        (2, 4, 512, ".sos_task_stacks", "audio_task"),
    ]
    assert [(s.id, s.max, s.initial) for s in config.sems] == [(0, 1, 0)]
    assert config.queues == ()

    regions = {".task_stacks", ".sos_task_stacks"}
    rust = emit_rust_port_config(config, available_stack_regions=regions)
    c = emit_c_port_config(config, available_stack_regions=regions)

    assert 'pub const SOS_TICK_HZ: u32 = 1000u32;' in rust
    assert '#[link_section = ".task_stacks"]' in rust
    assert rust.count('#[link_section = ".sos_task_stacks"]') == 2
    assert "pub static mut SOS_TASK_1_STACK: [u32; 2048]" in rust
    assert "pub static mut SOS_TASK_2_STACK: [u32; 512]" in rust
    assert "boot.task_create(1u8, 1u8, render_task, sos_task_1_stack_top());" in rust
    assert "boot.task_create(2u8, 4u8, audio_task, sos_task_2_stack_top());" in rust
    assert "boot.sem_create(0u8, 1u32, 0u32);" in rust

    assert "#define SOS_TICK_HZ (1000u)" in c
    assert '__attribute__((section(".task_stacks")))' in c
    assert c.count('__attribute__((section(".sos_task_stacks")))') == 2
    assert "static uint32_t SOS_TASK_1_STACK[2048u];" in c
    assert "static uint32_t SOS_TASK_2_STACK[512u];" in c
    assert "task_create(1u, 1u, render_task, sos_task_1_stack_top());" in c
    assert "task_create(2u, 4u, audio_task, sos_task_2_stack_top());" in c
    assert "sem_create(0u, 1u, 0u);" in c


def test_default_stack_region_is_backward_compatible_section_spelling():
    config = parse_port_config_from_chart(_attr_child_chart(omit_region=True))

    assert [task.stack_region for task in config.tasks] == [
        DEFAULT_STACK_REGION,
        DEFAULT_STACK_REGION,
    ]

    rust = emit_rust_port_config(config)
    c = emit_c_port_config(config)

    assert rust.count('#[link_section = ".task_stacks"]') == 2
    assert ".sos_task_stacks" not in rust
    assert c.count('__attribute__((section(".task_stacks")))') == 2
    assert ".sos_task_stacks" not in c


def test_missing_linker_region_is_a_hard_emit_error():
    config = parse_port_config_from_chart(_worked_example_chart())

    with pytest.raises(PortConfigEmitError, match=r"missing linker stack region"):
        emit_rust_port_config(config, available_stack_regions={".task_stacks"})

    with pytest.raises(PortConfigEmitError, match=r"\.sos_task_stacks"):
        emit_c_port_config(config, available_stack_regions={".task_stacks"})


def test_constraint_violation_prio_must_be_less_than_max_prio():
    chart = _attr_child_chart(task_prio="8")

    with pytest.raises(PortConfigError, match=r"prio < MAX_PRIO"):
        parse_port_config_from_chart(
            chart,
            bounds=PortConfigBounds(max_tasks=8, max_prio=8, max_sems=8, max_queues=4),
        )


def test_lowered_manifest_round_trips_as_generated_intermediate(tmp_path: Path):
    config = parse_port_config_from_chart(_worked_example_chart())
    manifest = tmp_path / "port_config.generated.json"

    write_port_config_manifest(config, manifest)
    loaded = read_port_config_manifest(manifest)

    assert loaded == config
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["tasks"][1]["stack_region"] == ".sos_task_stacks"
