"""SOS-04-A port_config parser plus Rust/C static-allocation emitters.

Authority: docs/concepts/SOS-04-A-PORT-CONFIG-SURFACE.md, ratified
2026-06-01. The chart-level ``<sos:task_config>`` annotation is the
authoritative carrier; the JSON manifest helpers below are generated
lowered intermediates only.

Public surface:
    parse_port_config_from_chart(chart_ast, bounds=None) -> PortConfig
    parse_port_config_payload(payload, bounds=None) -> PortConfig
    read_port_config_manifest(path, bounds=None) -> PortConfig
    write_port_config_manifest(config, path) -> Path
    emit_rust_port_config(config, available_stack_regions=...) -> str
    emit_c_port_config(config, available_stack_regions=...) -> str
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


SOS_NS = "https://softoboros.com/sos/1.0"
DEFAULT_TICK_HZ = 1000
DEFAULT_KERNEL_STACK_WORDS = 1024
DEFAULT_STACK_REGION = ".task_stacks"
DEFAULT_AVAILABLE_STACK_REGIONS = frozenset({DEFAULT_STACK_REGION})

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RUST_EXTERN_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECTION_RE = re.compile(r"^[A-Za-z0-9_.$-]+$")
_DSL_TOKEN_RE = re.compile(
    r'"(?:\\.|[^"\\])*"'
    r"|[{}\[\]:,]"
    r"|-?(?:0[xX][0-9a-fA-F]+|[0-9]+)"
    r"|[A-Za-z_.][A-Za-z0-9_./$-]*"
)


class PortConfigError(ValueError):
    """Raised when the SOS-04-A port_config surface is malformed."""


class PortConfigEmitError(PortConfigError):
    """Raised when a valid port_config cannot be emitted for a port."""


@dataclass(frozen=True)
class PortConfigBounds:
    """SOS-00 pool bounds consumed by SOS-04-A validation."""

    max_tasks: int = 8
    max_prio: int = 8
    max_sems: int = 8
    max_queues: int = 4


@dataclass(frozen=True)
class PortConfigTask:
    id: int
    prio: int
    stack_words: int
    entry: str
    stack_region: str = DEFAULT_STACK_REGION

    def as_manifest_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "prio": self.prio,
            "stack_words": self.stack_words,
            "stack_region": self.stack_region,
            "entry": self.entry,
        }


@dataclass(frozen=True)
class PortConfigSem:
    id: int
    max: int
    initial: int

    def as_manifest_dict(self) -> dict[str, Any]:
        return {"id": self.id, "max": self.max, "initial": self.initial}


@dataclass(frozen=True)
class PortConfigQueue:
    id: int
    cap: int

    def as_manifest_dict(self) -> dict[str, Any]:
        return {"id": self.id, "cap": self.cap}


@dataclass(frozen=True)
class PortConfig:
    tick_hz: int
    kernel_stack_words: int
    tasks: tuple[PortConfigTask, ...]
    sems: tuple[PortConfigSem, ...]
    queues: tuple[PortConfigQueue, ...]

    def as_manifest_dict(self) -> dict[str, Any]:
        return {
            "tick_hz": self.tick_hz,
            "kernel_stack_words": self.kernel_stack_words,
            "tasks": [task.as_manifest_dict() for task in self.tasks],
            "sems": [sem.as_manifest_dict() for sem in self.sems],
            "queues": [queue.as_manifest_dict() for queue in self.queues],
        }


# ---------------------------------------------------------------------------
# Carrier parsing
# ---------------------------------------------------------------------------


def parse_port_config_from_chart(
    chart_ast: dict[str, Any],
    *,
    bounds: Optional[PortConfigBounds] = None,
) -> PortConfig:
    """Extract and validate the root ``<sos:task_config>`` annotation.

    The scjson convention used elsewhere in this tree preserves foreign
    namespace elements under ``other_element``. For testability and future
    scjson shape drift, this accepts the same element shape at the root
    or as the root object itself.
    """
    if _is_element_named(chart_ast, "task_config"):
        return parse_port_config_element(chart_ast, bounds=bounds)

    root_attrs = _extract_other_attributes(chart_ast)
    if "sos:task_config" in root_attrs:
        return parse_port_config_payload(
            root_attrs["sos:task_config"],
            bounds=bounds or bounds_from_chart_datamodel(chart_ast),
            source="sos:task_config",
        )

    task_config_elements = [
        el
        for el in _iter_other_elements(chart_ast)
        if _is_element_named(el, "task_config")
    ]
    if not task_config_elements:
        raise PortConfigError(
            "chart is missing authoritative <sos:task_config> annotation"
        )
    if len(task_config_elements) > 1:
        raise PortConfigError(
            f"chart carries {len(task_config_elements)} <sos:task_config> "
            "annotations; exactly one is permitted"
        )
    return parse_port_config_element(
        task_config_elements[0],
        bounds=bounds or bounds_from_chart_datamodel(chart_ast),
    )


def parse_port_config_element(
    element: dict[str, Any],
    *,
    bounds: Optional[PortConfigBounds] = None,
) -> PortConfig:
    """Parse one scjson-shaped ``<sos:task_config>`` element."""
    text = _element_text(element).strip()
    if text:
        payload = _parse_port_config_text(text)
        return parse_port_config_payload(payload, bounds=bounds, source="<sos:task_config>")

    attrs = _element_attributes(element)
    payload: dict[str, Any] = {}
    if "tick_hz" in attrs:
        payload["tick_hz"] = attrs["tick_hz"]
    if "kernel_stack_words" in attrs:
        payload["kernel_stack_words"] = attrs["kernel_stack_words"]

    tasks: list[dict[str, Any]] = []
    sems: list[dict[str, Any]] = []
    queues: list[dict[str, Any]] = []
    for child in _iter_other_elements(element):
        if _is_element_named(child, "task"):
            tasks.append(dict(_element_attributes(child)))
        elif _is_element_named(child, "sem"):
            sems.append(dict(_element_attributes(child)))
        elif _is_element_named(child, "queue"):
            queues.append(dict(_element_attributes(child)))
        elif _is_element_named(child, "tasks"):
            tasks.extend(_parse_collection_child(child, "task"))
        elif _is_element_named(child, "sems"):
            sems.extend(_parse_collection_child(child, "sem"))
        elif _is_element_named(child, "queues"):
            queues.extend(_parse_collection_child(child, "queue"))

    payload["tasks"] = tasks
    payload["sems"] = sems
    payload["queues"] = queues
    return parse_port_config_payload(payload, bounds=bounds, source="<sos:task_config>")


def parse_port_config_payload(
    payload: Any,
    *,
    bounds: Optional[PortConfigBounds] = None,
    source: str = "port_config",
) -> PortConfig:
    """Parse a carrier-independent SOS-04-A ``port_config`` payload."""
    if isinstance(payload, str):
        payload = _parse_port_config_text(payload)
    if not isinstance(payload, dict):
        raise PortConfigError(f"{source} must be an object; got {type(payload).__name__}")

    allowed = {"tick_hz", "kernel_stack_words", "tasks", "sems", "queues"}
    unknown = sorted(str(k) for k in payload.keys() if k not in allowed)
    if unknown:
        raise PortConfigError(
            f"{source} contains unknown key(s) {unknown}; SOS-04-A section 4.1 "
            "field set is frozen"
        )

    tick_hz = _int_field(payload, "tick_hz", default=DEFAULT_TICK_HZ, source=source)
    kernel_stack_words = _int_field(
        payload,
        "kernel_stack_words",
        default=DEFAULT_KERNEL_STACK_WORDS,
        source=source,
    )

    raw_tasks = payload.get("tasks", [])
    raw_sems = payload.get("sems", [])
    raw_queues = payload.get("queues", [])
    if not isinstance(raw_tasks, list):
        raise PortConfigError(f"{source}.tasks must be a list")
    if not isinstance(raw_sems, list):
        raise PortConfigError(f"{source}.sems must be a list")
    if not isinstance(raw_queues, list):
        raise PortConfigError(f"{source}.queues must be a list")

    config = PortConfig(
        tick_hz=tick_hz,
        kernel_stack_words=kernel_stack_words,
        tasks=tuple(_parse_task(row, idx, source=source) for idx, row in enumerate(raw_tasks)),
        sems=tuple(_parse_sem(row, idx, source=source) for idx, row in enumerate(raw_sems)),
        queues=tuple(
            _parse_queue(row, idx, source=source) for idx, row in enumerate(raw_queues)
        ),
    )
    validate_port_config(config, bounds=bounds or PortConfigBounds())
    return config


def _parse_task(row: Any, idx: int, *, source: str) -> PortConfigTask:
    if not isinstance(row, dict):
        raise PortConfigError(f"{source}.tasks[{idx}] must be an object")
    allowed = {"id", "prio", "stack_words", "stack_region", "entry"}
    unknown = sorted(str(k) for k in row.keys() if k not in allowed)
    if unknown:
        raise PortConfigError(f"{source}.tasks[{idx}] unknown key(s) {unknown}")
    if "entry" not in row:
        raise PortConfigError(f"{source}.tasks[{idx}].entry is required")
    return PortConfigTask(
        id=_int_field(row, "id", source=f"{source}.tasks[{idx}]"),
        prio=_int_field(row, "prio", source=f"{source}.tasks[{idx}]"),
        stack_words=_int_field(row, "stack_words", source=f"{source}.tasks[{idx}]"),
        stack_region=_str_field(
            row,
            "stack_region",
            default=DEFAULT_STACK_REGION,
            source=f"{source}.tasks[{idx}]",
        ),
        entry=_str_field(row, "entry", source=f"{source}.tasks[{idx}]"),
    )


def _parse_sem(row: Any, idx: int, *, source: str) -> PortConfigSem:
    if not isinstance(row, dict):
        raise PortConfigError(f"{source}.sems[{idx}] must be an object")
    allowed = {"id", "max", "initial"}
    unknown = sorted(str(k) for k in row.keys() if k not in allowed)
    if unknown:
        raise PortConfigError(f"{source}.sems[{idx}] unknown key(s) {unknown}")
    return PortConfigSem(
        id=_int_field(row, "id", source=f"{source}.sems[{idx}]"),
        max=_int_field(row, "max", source=f"{source}.sems[{idx}]"),
        initial=_int_field(row, "initial", source=f"{source}.sems[{idx}]"),
    )


def _parse_queue(row: Any, idx: int, *, source: str) -> PortConfigQueue:
    if not isinstance(row, dict):
        raise PortConfigError(f"{source}.queues[{idx}] must be an object")
    allowed = {"id", "cap"}
    unknown = sorted(str(k) for k in row.keys() if k not in allowed)
    if unknown:
        raise PortConfigError(f"{source}.queues[{idx}] unknown key(s) {unknown}")
    return PortConfigQueue(
        id=_int_field(row, "id", source=f"{source}.queues[{idx}]"),
        cap=_int_field(row, "cap", source=f"{source}.queues[{idx}]"),
    )


def validate_port_config(
    config: PortConfig,
    *,
    bounds: PortConfigBounds = PortConfigBounds(),
) -> None:
    """Enforce SOS-04-A section 4.2 constraints and basic schema sanity."""
    if config.tick_hz <= 0:
        raise PortConfigError(f"tick_hz must be positive; got {config.tick_hz}")
    if config.kernel_stack_words <= 0:
        raise PortConfigError(
            "kernel_stack_words must be positive; "
            f"got {config.kernel_stack_words}"
        )
    if len(config.tasks) > bounds.max_tasks:
        raise PortConfigError(
            f"tasks.len() <= MAX_TASKS violated: {len(config.tasks)} > "
            f"{bounds.max_tasks}"
        )
    if len(config.sems) > bounds.max_sems:
        raise PortConfigError(
            f"sems.len() <= MAX_SEMS violated: {len(config.sems)} > "
            f"{bounds.max_sems}"
        )
    if len(config.queues) > bounds.max_queues:
        raise PortConfigError(
            f"queues.len() <= MAX_QUEUES violated: {len(config.queues)} > "
            f"{bounds.max_queues}"
        )

    task_ids: set[int] = set()
    for task in config.tasks:
        if task.id in task_ids:
            raise PortConfigError(f"duplicate task id {task.id}")
        task_ids.add(task.id)
        _validate_pool_id(task.id, "task id", "MAX_TASKS", bounds.max_tasks)
        _validate_u8(task.id, f"task id {task.id}")
        _validate_u8(task.prio, f"task {task.id} prio {task.prio}")
        if task.prio >= bounds.max_prio:
            raise PortConfigError(
                f"prio < MAX_PRIO violated for task id {task.id}: "
                f"{task.prio} >= {bounds.max_prio}"
            )
        if task.id == 0 and task.prio != 0:
            raise PortConfigError(
                "task id 0 is reserved for idle and must use prio 0 "
                f"when explicitly supplied; got prio {task.prio}"
            )
        if task.prio == 0 and task.id != 0:
            raise PortConfigError(
                "prio 0 is reserved for idle task id 0; "
                f"task id {task.id} requested prio 0"
            )
        if task.stack_words <= 0:
            raise PortConfigError(
                f"task id {task.id} stack_words must be positive; "
                f"got {task.stack_words}"
            )
        _validate_entry_symbol(task.entry, task_id=task.id)
        _validate_stack_region(task.stack_region, task_id=task.id)

    sem_ids: set[int] = set()
    for sem in config.sems:
        if sem.id in sem_ids:
            raise PortConfigError(f"duplicate sem id {sem.id}")
        sem_ids.add(sem.id)
        _validate_pool_id(sem.id, "sem id", "MAX_SEMS", bounds.max_sems)
        _validate_u8(sem.id, f"sem id {sem.id}")
        if sem.max <= 0:
            raise PortConfigError(f"sem id {sem.id} max must be positive")
        if sem.initial < 0:
            raise PortConfigError(f"sem id {sem.id} initial must be non-negative")
        if sem.initial > sem.max:
            raise PortConfigError(
                f"sem id {sem.id} initial must be <= max; "
                f"{sem.initial} > {sem.max}"
            )

    queue_ids: set[int] = set()
    for queue in config.queues:
        if queue.id in queue_ids:
            raise PortConfigError(f"duplicate queue id {queue.id}")
        queue_ids.add(queue.id)
        _validate_pool_id(queue.id, "queue id", "MAX_QUEUES", bounds.max_queues)
        _validate_u8(queue.id, f"queue id {queue.id}")
        if queue.cap <= 0:
            raise PortConfigError(f"queue id {queue.id} cap must be positive")


def _validate_pool_id(value: int, label: str, bound_name: str, bound: int) -> None:
    if value < 0:
        raise PortConfigError(f"{label} must be non-negative; got {value}")
    if value >= bound:
        raise PortConfigError(f"{label} must be < {bound_name}; got {value} >= {bound}")


def _validate_u8(value: int, label: str) -> None:
    if not (0 <= value <= 255):
        raise PortConfigError(f"{label} must fit u8; got {value}")


def _validate_entry_symbol(value: str, *, task_id: int) -> None:
    if not _IDENT_RE.match(value):
        raise PortConfigError(
            f"task id {task_id} entry must be a C/Rust identifier; got {value!r}"
        )


def _validate_stack_region(value: str, *, task_id: int) -> None:
    if not value:
        raise PortConfigError(f"task id {task_id} stack_region must be non-empty")
    if any(ch.isspace() or ch in {'"', "'"} for ch in value):
        raise PortConfigError(
            f"task id {task_id} stack_region contains whitespace/quotes: {value!r}"
        )
    if value.startswith("."):
        tail = value[1:]
    else:
        tail = value
    if not tail or not _SECTION_RE.match(tail):
        raise PortConfigError(
            f"task id {task_id} stack_region is not a linker-section symbol: "
            f"{value!r}"
        )


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------


def read_port_config_manifest(
    path: Path,
    *,
    bounds: Optional[PortConfigBounds] = None,
) -> PortConfig:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return parse_port_config_payload(payload, bounds=bounds, source=str(path))


def write_port_config_manifest(config: PortConfig, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(config.as_manifest_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# Emitters
# ---------------------------------------------------------------------------


def emit_rust_port_config(
    config: PortConfig,
    *,
    available_stack_regions: Iterable[str] = DEFAULT_AVAILABLE_STACK_REGIONS,
) -> str:
    """Emit a Rust fragment with per-task stack statics and create calls."""
    _validate_available_stack_regions(config, available_stack_regions)

    lines: list[str] = [
        "// Generated by tools/sos-codegen/port_config_emit.py.",
        "// Authority: SOS-04-A section 4.3.",
        "#![allow(dead_code)]",
        "",
        f"pub const SOS_TICK_HZ: u32 = {config.tick_hz}u32;",
        f"pub const KERNEL_STACK_WORDS: usize = {config.kernel_stack_words}usize;",
        "",
        '#[link_section = ".kernel_stack"]',
        "pub static mut KERNEL_STACK: [u32; KERNEL_STACK_WORDS] = "
        "[0u32; KERNEL_STACK_WORDS];",
        "",
        "pub trait SosPortConfigCreate {",
        "    unsafe fn task_create(",
        "        &mut self,",
        "        id: u8,",
        "        prio: u8,",
        "        entry: unsafe extern \"C\" fn(),",
        "        psp: u32,",
        "    );",
        "    unsafe fn sem_create(&mut self, id: u8, max: u32, initial: u32);",
        "    unsafe fn queue_create(&mut self, id: u8, cap: u32);",
        "}",
        "",
    ]

    entries = _unique_in_order(task.entry for task in config.tasks)
    if entries:
        lines.append("extern \"C\" {")
        for entry in entries:
            lines.append(f"    pub fn {entry}();")
        lines.append("}")
        lines.append("")

    for task in config.tasks:
        lines.extend(
            [
                f'#[link_section = "{task.stack_region}"]',
                f"pub static mut {_rust_stack_symbol(task)}: [u32; "
                f"{task.stack_words}] = [0u32; {task.stack_words}];",
                "",
                "#[inline(always)]",
                f"pub unsafe fn {_rust_stack_top_fn(task)}() -> u32 {{",
                f"    core::ptr::addr_of_mut!({_rust_stack_symbol(task)})",
                f"        .cast::<u32>()",
                f"        .add({task.stack_words}) as u32",
                "}",
                "",
            ]
        )

    lines.extend(
        [
            "#[inline(always)]",
            "pub unsafe fn sos_port_config_apply_mpu() {",
            "    // SOS-04-A section 4.4: no protection annotations are present;",
            "    // SOS-09-G owns MPU emission when that annotation surface exists.",
            "}",
            "",
            "pub unsafe fn sos_port_config_create<B: SosPortConfigCreate>(boot: &mut B) {",
        ]
    )
    for task in config.tasks:
        lines.extend(
            [
                f"    // task.create{{id: {task.id}, prio: {task.prio}, "
                f"entry: {task.entry}}}",
                f"    boot.task_create({task.id}u8, {task.prio}u8, "
                f"{task.entry}, {_rust_stack_top_fn(task)}());",
            ]
        )
    for sem in config.sems:
        lines.extend(
            [
                f"    // sem.create{{id: {sem.id}, max: {sem.max}, "
                f"initial: {sem.initial}}}",
                f"    boot.sem_create({sem.id}u8, {sem.max}u32, {sem.initial}u32);",
            ]
        )
    for queue in config.queues:
        lines.extend(
            [
                f"    // queue.create{{id: {queue.id}, cap: {queue.cap}}}",
                f"    boot.queue_create({queue.id}u8, {queue.cap}u32);",
            ]
        )
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def emit_c_port_config(
    config: PortConfig,
    *,
    available_stack_regions: Iterable[str] = DEFAULT_AVAILABLE_STACK_REGIONS,
) -> str:
    """Emit a C11 fragment with per-task stack statics and create calls."""
    _validate_available_stack_regions(config, available_stack_regions)

    lines: list[str] = [
        "/* Generated by tools/sos-codegen/port_config_emit.py.",
        " * Authority: SOS-04-A section 4.3. */",
        "#include <stdint.h>",
        "#include <stddef.h>",
        "",
        f"#define SOS_TICK_HZ ({config.tick_hz}u)",
        f"#define SOS_KERNEL_STACK_WORDS ({config.kernel_stack_words}u)",
        "",
        "typedef void (*sos_task_entry_t)(void);",
        "",
    ]
    for entry in _unique_in_order(task.entry for task in config.tasks):
        lines.append(f"extern void {entry}(void);")
    if config.tasks:
        lines.append("")
    lines.extend(
        [
            "extern void task_create(uint8_t id, uint8_t prio, "
            "sos_task_entry_t entry, uintptr_t psp);",
            "extern void sem_create(uint8_t id, uint32_t max, uint32_t initial);",
            "extern void queue_create(uint8_t id, uint32_t cap);",
            "",
            '__attribute__((section(".kernel_stack")))',
            "static uint32_t SOS_KERNEL_STACK[SOS_KERNEL_STACK_WORDS];",
            "",
        ]
    )

    for task in config.tasks:
        lines.extend(
            [
                f'__attribute__((section("{task.stack_region}")))',
                f"static uint32_t {_c_stack_symbol(task)}[{task.stack_words}u];",
                "",
                f"static inline uintptr_t {_c_stack_top_fn(task)}(void)",
                "{",
                f"    return (uintptr_t)&{_c_stack_symbol(task)}[{task.stack_words}u];",
                "}",
                "",
            ]
        )

    lines.extend(
        [
            "static inline void sos_port_config_apply_mpu(void)",
            "{",
            "    /* SOS-04-A section 4.4: absent protection annotations emit no MPU setup. */",
            "}",
            "",
            "void sos_port_config_create(void)",
            "{",
        ]
    )
    for task in config.tasks:
        lines.extend(
            [
                f"    /* task.create{{id: {task.id}, prio: {task.prio}, "
                f"entry: {task.entry}}} */",
                f"    task_create({task.id}u, {task.prio}u, {task.entry}, "
                f"{_c_stack_top_fn(task)}());",
            ]
        )
    for sem in config.sems:
        lines.extend(
            [
                f"    /* sem.create{{id: {sem.id}, max: {sem.max}, "
                f"initial: {sem.initial}}} */",
                f"    sem_create({sem.id}u, {sem.max}u, {sem.initial}u);",
            ]
        )
    for queue in config.queues:
        lines.extend(
            [
                f"    /* queue.create{{id: {queue.id}, cap: {queue.cap}}} */",
                f"    queue_create({queue.id}u, {queue.cap}u);",
            ]
        )
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def _validate_available_stack_regions(
    config: PortConfig,
    available_stack_regions: Iterable[str],
) -> None:
    available = set(available_stack_regions)
    missing = sorted({task.stack_region for task in config.tasks} - available)
    if missing:
        detail = []
        for region in missing:
            ids = [str(task.id) for task in config.tasks if task.stack_region == region]
            detail.append(f"{region} (task id(s): {', '.join(ids)})")
        raise PortConfigEmitError(
            "missing linker stack region(s): "
            + "; ".join(detail)
            + ". Provide the region in the port linker script before emission."
        )


def _rust_stack_symbol(task: PortConfigTask) -> str:
    return f"SOS_TASK_{task.id}_STACK"


def _rust_stack_top_fn(task: PortConfigTask) -> str:
    return f"sos_task_{task.id}_stack_top"


def _c_stack_symbol(task: PortConfigTask) -> str:
    return f"SOS_TASK_{task.id}_STACK"


def _c_stack_top_fn(task: PortConfigTask) -> str:
    return f"sos_task_{task.id}_stack_top"


def _unique_in_order(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


# ---------------------------------------------------------------------------
# Linker section helper
# ---------------------------------------------------------------------------


def read_linker_sections(path: Path) -> set[str]:
    """Best-effort extraction of output/input section names from a linker file."""
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    out: set[str] = set()
    for match in re.finditer(r"^\s*(\.[A-Za-z0-9_.$-]+)\b", text, flags=re.M):
        out.add(match.group(1))
    for match in re.finditer(r"\*\((\.[A-Za-z0-9_.$-]+)\)", text):
        out.add(match.group(1))
    return out


# ---------------------------------------------------------------------------
# Bounds extraction from chart datamodel
# ---------------------------------------------------------------------------


def bounds_from_chart_datamodel(chart_ast: dict[str, Any]) -> PortConfigBounds:
    values = {
        "MAX_TASKS": 8,
        "MAX_PRIO": 8,
        "MAX_SEMS": 8,
        "MAX_QUEUES": 4,
    }
    dm = chart_ast.get("datamodel")
    entries: list[dict[str, Any]] = []
    if isinstance(dm, list):
        for item in dm:
            if isinstance(item, dict):
                data = item.get("data", [])
                if isinstance(data, list):
                    entries.extend(d for d in data if isinstance(d, dict))
    elif isinstance(dm, dict):
        data = dm.get("data", [])
        if isinstance(data, list):
            entries.extend(d for d in data if isinstance(d, dict))
    for entry in entries:
        key = entry.get("id")
        if key not in values:
            continue
        try:
            values[key] = _parse_int_token(entry.get("expr"), f"datamodel.{key}")
        except PortConfigError:
            continue
    return PortConfigBounds(
        max_tasks=values["MAX_TASKS"],
        max_prio=values["MAX_PRIO"],
        max_sems=values["MAX_SEMS"],
        max_queues=values["MAX_QUEUES"],
    )


# ---------------------------------------------------------------------------
# scjson shape helpers
# ---------------------------------------------------------------------------


def _extract_other_attributes(node: dict[str, Any]) -> dict[str, Any]:
    oa = node.get("other_attributes")
    if oa is None:
        return {}
    if isinstance(oa, str):
        raw = oa
    elif isinstance(oa, dict):
        inner = oa.get("other_attributes")
        if isinstance(inner, str):
            raw = inner
        elif isinstance(inner, dict):
            return inner
        elif inner is None:
            return {k: v for k, v in oa.items() if k != "other_attributes"} or {}
        else:
            return {}
    else:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PortConfigError(f"malformed other_attributes JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise PortConfigError("other_attributes JSON must be an object")
    return parsed


def _iter_other_elements(node: dict[str, Any]) -> list[dict[str, Any]]:
    elements: list[dict[str, Any]] = []
    for key in ("other_element", "children"):
        raw = node.get(key) or []
        if isinstance(raw, list):
            elements.extend(el for el in raw if isinstance(el, dict))
    return elements


def _element_attributes(element: dict[str, Any]) -> dict[str, Any]:
    attrs = element.get("attributes") or {}
    if not isinstance(attrs, dict):
        raise PortConfigError("<sos:task_config> child attributes must be an object")
    return attrs


def _element_text(element: dict[str, Any]) -> str:
    text = element.get("text")
    if isinstance(text, str):
        return text
    content = element.get("content")
    if isinstance(content, list):
        return "\n".join(str(part) for part in content)
    return ""


def _is_element_named(element: dict[str, Any], local_name: str) -> bool:
    qname = element.get("qname")
    if isinstance(qname, str) and _qname_local_name(qname) == local_name:
        return True
    name = element.get("name")
    return isinstance(name, str) and _qname_local_name(name) == local_name


def _qname_local_name(qname: str) -> str:
    if qname.startswith("{") and "}" in qname:
        return qname.split("}", 1)[1]
    if ":" in qname:
        return qname.rsplit(":", 1)[1]
    return qname


def _parse_collection_child(parent: dict[str, Any], child_name: str) -> list[dict[str, Any]]:
    text = _element_text(parent).strip()
    if text:
        parsed = _parse_port_config_text(text)
        if isinstance(parsed, list):
            return parsed
        raise PortConfigError(f"<sos:{child_name}s> text must parse as a list")
    return [
        dict(_element_attributes(child))
        for child in _iter_other_elements(parent)
        if _is_element_named(child, child_name)
    ]


# ---------------------------------------------------------------------------
# Scalar and DSL parsing
# ---------------------------------------------------------------------------


def _parse_port_config_text(text: str) -> Any:
    stripped = text.strip()
    if not stripped:
        raise PortConfigError("empty port_config text")
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise PortConfigError(f"malformed port_config JSON: {exc}") from exc
    parser = _DslParser(stripped)
    return parser.parse()


def _int_field(
    obj: dict[str, Any],
    key: str,
    *,
    source: str,
    default: Optional[int] = None,
) -> int:
    if key not in obj:
        if default is not None:
            return default
        raise PortConfigError(f"{source}.{key} is required")
    return _parse_int_token(obj[key], f"{source}.{key}")


def _str_field(
    obj: dict[str, Any],
    key: str,
    *,
    source: str,
    default: Optional[str] = None,
) -> str:
    if key not in obj or obj[key] is None:
        if default is not None:
            return default
        raise PortConfigError(f"{source}.{key} is required")
    value = obj[key]
    if not isinstance(value, str):
        raise PortConfigError(f"{source}.{key} must be a string/symbol; got {value!r}")
    if not value:
        raise PortConfigError(f"{source}.{key} must be non-empty")
    return value


def _parse_int_token(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise PortConfigError(f"{label} must be an integer; got bool {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError as exc:
            raise PortConfigError(f"{label} must be an integer; got {value!r}") from exc
    raise PortConfigError(
        f"{label} must be an integer; got {value!r} "
        f"(type={type(value).__name__})"
    )


def _strip_dsl_comments(text: str) -> str:
    out: list[str] = []
    i = 0
    in_string = False
    escaped = False
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and nxt == "/":
            while i < len(text) and text[i] != "\n":
                i += 1
            if i < len(text):
                out.append("\n")
                i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


class _DslParser:
    """Small parser for the spec's worked-example ``port_config { ... }`` form."""

    def __init__(self, text: str) -> None:
        self.text = _strip_dsl_comments(text)
        self.tokens = self._tokenize(self.text)
        self.pos = 0

    def parse(self) -> Any:
        if self._peek() == "port_config":
            self._pop()
        value = self._parse_value()
        if self._peek() is not None:
            raise PortConfigError(f"unexpected trailing token {self._peek()!r}")
        return value

    def _tokenize(self, text: str) -> list[str]:
        tokens: list[str] = []
        pos = 0
        for match in _DSL_TOKEN_RE.finditer(text):
            gap = text[pos:match.start()]
            if gap.strip():
                raise PortConfigError(f"unexpected token text {gap!r}")
            tokens.append(match.group(0))
            pos = match.end()
        tail = text[pos:]
        if tail.strip():
            raise PortConfigError(f"unexpected token text {tail!r}")
        return tokens

    def _parse_value(self) -> Any:
        tok = self._peek()
        if tok is None:
            raise PortConfigError("unexpected end of port_config DSL")
        if tok == "{":
            return self._parse_object()
        if tok == "[":
            return self._parse_array()
        if tok.startswith('"'):
            self._pop()
            return json.loads(tok)
        if _looks_int(tok):
            self._pop()
            return int(tok, 0)
        self._pop()
        return tok

    def _parse_object(self) -> dict[str, Any]:
        self._expect("{")
        out: dict[str, Any] = {}
        while self._peek() != "}":
            tok = self._peek()
            if tok is None:
                raise PortConfigError("unterminated object in port_config DSL")
            if tok in {"{", "}", "[", "]", ":", ","}:
                raise PortConfigError(f"expected object key, got {tok!r}")
            key = self._parse_value()
            if not isinstance(key, str):
                raise PortConfigError(f"object key must be a symbol/string; got {key!r}")
            if key in out:
                raise PortConfigError(f"duplicate object key {key!r}")
            self._expect(":")
            out[key] = self._parse_value()
            if self._peek() == ",":
                self._pop()
        self._expect("}")
        return out

    def _parse_array(self) -> list[Any]:
        self._expect("[")
        out: list[Any] = []
        while self._peek() != "]":
            if self._peek() is None:
                raise PortConfigError("unterminated array in port_config DSL")
            out.append(self._parse_value())
            if self._peek() == ",":
                self._pop()
        self._expect("]")
        return out

    def _peek(self) -> Optional[str]:
        if self.pos >= len(self.tokens):
            return None
        return self.tokens[self.pos]

    def _pop(self) -> str:
        tok = self._peek()
        if tok is None:
            raise PortConfigError("unexpected end of port_config DSL")
        self.pos += 1
        return tok

    def _expect(self, token: str) -> None:
        got = self._pop()
        if got != token:
            raise PortConfigError(f"expected {token!r}, got {got!r}")


def _looks_int(token: str) -> bool:
    return bool(re.match(r"^-?(?:0[xX][0-9a-fA-F]+|[0-9]+)$", token))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Emit SOS-04-A port_config Rust/C fragments from a chart."
    )
    parser.add_argument("chart", type=Path, help="path to the chart .scxml")
    parser.add_argument("--target", choices=("rust", "c", "both"), required=True)
    parser.add_argument("--out", type=Path, help="output path for rust or c target")
    parser.add_argument("--out-rust", type=Path, help="Rust output path for --target=both")
    parser.add_argument("--out-c", type=Path, help="C output path for --target=both")
    parser.add_argument(
        "--manifest-out",
        type=Path,
        help="optional generated lowered manifest JSON output path",
    )
    parser.add_argument(
        "--linker-section",
        action="append",
        default=[],
        help=(
            "available linker section; repeatable. Defaults to .task_stacks "
            "when neither --linker-section nor --linker-script is supplied"
        ),
    )
    parser.add_argument(
        "--linker-script",
        type=Path,
        action="append",
        default=[],
        help="linker script to scan for available section names; repeatable",
    )
    args = parser.parse_args(argv)

    if args.target in {"rust", "c"} and args.out is None:
        parser.error("--target rust|c requires --out")
    if args.target == "both" and (args.out_rust is None or args.out_c is None):
        parser.error("--target both requires --out-rust and --out-c")

    tools_dir = Path(__file__).resolve().parent
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))
    from loader import load_chart  # noqa: E402

    ast = load_chart(args.chart).raw_scjson or {}
    config = parse_port_config_from_chart(ast)
    if args.manifest_out is not None:
        write_port_config_manifest(config, args.manifest_out)

    sections = set(args.linker_section)
    for linker_script in args.linker_script:
        sections.update(read_linker_sections(linker_script))
    if not sections:
        sections = set(DEFAULT_AVAILABLE_STACK_REGIONS)

    if args.target == "rust":
        args.out.write_text(
            emit_rust_port_config(config, available_stack_regions=sections),
            encoding="utf-8",
        )
    elif args.target == "c":
        args.out.write_text(
            emit_c_port_config(config, available_stack_regions=sections),
            encoding="utf-8",
        )
    else:
        args.out_rust.write_text(
            emit_rust_port_config(config, available_stack_regions=sections),
            encoding="utf-8",
        )
        args.out_c.write_text(
            emit_c_port_config(config, available_stack_regions=sections),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
