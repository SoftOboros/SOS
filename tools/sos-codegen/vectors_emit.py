"""SOS-09-F chart → membrane-vector emission walker.

Per ``docs/concepts/SOS-09-F-CONCEPTS.md`` §5.4 (ratified 2026-05-26):
walks a :class:`sos09_annotations.ChartAnnotations` model, enumerates
the register set under test (per SOS-09-A's read surface + SOS-09-B's
SVD address-offset policy), and emits a cocotb-compatible test
directory at ``build/vectors/<chart_id>/`` containing:

  - ``conftest.py``                       — invokes cocotb's pytest plugin
  - ``test_<family>.py`` per family       — one per vector family
  - ``.uuid-cache.json``                  — sos:id UUID cache (PCDN-F-004)
  - ``junit.xml`` (post-run; not at emit) — pytest-XUnit shape (PCDN-F-005)

The Python harness (``vectors.harness.PythonCpuStubHarness``) is the
v1 reference per PCDN-SOS-09-005 / PCDN-SOS-09-F-005. The emitted
``test_*.py`` files import from ``vectors.families.<family>`` and
exercise each channel's ``MembraneVector`` subclass against the
harness, then emit JUnit XML via pytest's native reporter.

Public surface:

    plan_channel(annotation: ChannelAnnotation, ...) -> ChannelVectorPlan
    plan_chart(annotations: ChartAnnotations, ...) -> list[ChannelVectorPlan]
    emit_vectors(annotations: ChartAnnotations, *, chart_id, out_dir, ...) -> dict
    run_vectors(chart_plans: list[ChannelVectorPlan], out_dir) -> str
        # Runs every plan's vectors against PythonCpuStubHarness and
        # emits JUnit XML at out_dir / "junit.xml". Returns the path.
    main(argv)                              — CLI entry point
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable, Optional

# Self-relative-ish import — this module lives at tools/sos-codegen/.
_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from sos09_annotations import (  # noqa: E402
    ChannelAnnotation,
    ChartAnnotations,
    parse_chart_annotations,
)
from vectors.base import (  # noqa: E402
    ChannelVectorPlan,
    EmissionError,
    FAMILIES_BY_KIND,
    VectorFamily,
    trace_key,
)
from vectors.families import FAMILY_REGISTRY  # noqa: E402
from vectors.harness import PythonCpuStubHarness  # noqa: E402


# ---------------------------------------------------------------------------
# Address-offset policy — mirrors SOS-09-B
# ---------------------------------------------------------------------------


def _channel_size_bytes(width_bits: int) -> int:
    """Bytes per channel rounded up to 4-byte alignment (SOS-09-B parity)."""
    if width_bits <= 0:
        raise ValueError(f"channel width must be positive; got {width_bits}")
    raw_bytes = (width_bits + 7) // 8
    return ((raw_bytes + 3) // 4) * 4


def _compute_addresses(
    annotations: ChartAnnotations, *, base_address: int = 0x40000000
) -> dict[str, int]:
    """Return ``{channel.id: absolute_address}`` mirroring SOS-09-B."""
    out: dict[str, int] = {}
    cursor = 0
    for ch in annotations.channels:
        out[ch.id] = base_address + cursor
        cursor += _channel_size_bytes(ch.width)
    return out


# ---------------------------------------------------------------------------
# Per-channel applicability — §5.1 with per-channel-attribute gating
# ---------------------------------------------------------------------------


def _channel_clear_on_read_present(ch: ChannelAnnotation) -> bool:
    """True iff any bit_layout field carries side_effect='clear-on-read'."""
    if ch.bit_layout is None:
        return False
    return any(
        f.side_effect == "clear-on-read" for f in ch.bit_layout.fields
    )


def _channel_side_effect_on_write_present(ch: ChannelAnnotation) -> bool:
    """True iff any bit_layout field carries side_effect='side-effect-on-write'."""
    if ch.bit_layout is None:
        return False
    return any(
        f.side_effect == "side-effect-on-write" for f in ch.bit_layout.fields
    )


def _applicable_families(ch: ChannelAnnotation) -> list[VectorFamily]:
    """Subset of FAMILIES_BY_KIND[kind] that applies to this channel.

    §5.1 table notes:
      - status ``clear_on_read`` only when chart declares clear-on-read bits
      - command ``side_effect`` only when chart declares side-effect bits
      - protection only when zone is privileged
      - atomicity only when channel kind is shared OR
        ``atomicity == 'mutex-required'``
    """
    base = FAMILIES_BY_KIND[ch.kind]
    out: list[VectorFamily] = []
    for fam in [
        VectorFamily.INITIAL_VALUE,
        VectorFamily.WRITE_THEN_READ,
        VectorFamily.SIDE_EFFECT,
        VectorFamily.CLEAR_ON_READ,
        VectorFamily.ATOMICITY,
        VectorFamily.PROTECTION,
    ]:
        if fam not in base:
            continue
        if fam is VectorFamily.CLEAR_ON_READ:
            # Only emit when the chart declares clear-on-read bits OR
            # the channel kind is shared and the chart leaves the family
            # applicable (per §5.1 row 4).
            if not _channel_clear_on_read_present(ch):
                continue
        elif fam is VectorFamily.SIDE_EFFECT:
            # Queue channels get the family for depth-change observation
            # (sos:irq path); command channels need an explicit
            # side-effect-on-write declaration.
            if ch.kind == "command" and not (
                _channel_side_effect_on_write_present(ch) or ch.irq is not None
            ):
                continue
        elif fam is VectorFamily.PROTECTION:
            # Only emit when privilege-gating is meaningful — i.e. zone
            # is privileged (else there's no "unprivileged" to reject).
            if ch.zone != "privileged":
                continue
        elif fam is VectorFamily.ATOMICITY:
            # §5.1: status / command / queue gated on
            # atomicity='mutex-required'; shared always.
            if ch.kind != "shared" and ch.atomicity != "mutex-required":
                continue
        out.append(fam)
    return out


# ---------------------------------------------------------------------------
# plan_channel + plan_chart
# ---------------------------------------------------------------------------


def plan_channel(
    annotation: ChannelAnnotation,
    *,
    address: int,
) -> ChannelVectorPlan:
    """Build a ChannelVectorPlan for one annotated channel."""
    plan = ChannelVectorPlan(
        channel_id=annotation.id,
        channel_name=annotation.name,
        channel_kind=annotation.kind,
        channel_zone=annotation.zone,
        channel_dir=annotation.dir,
        address=address,
        width_bits=annotation.width,
        irq=annotation.irq,
        mutex=annotation.mutex,
        privilege_region=annotation.privilege_region,
    )
    for fam in _applicable_families(annotation):
        mod = FAMILY_REGISTRY[fam]
        # v1: one vector per (channel, family). seq slot reserved for
        # future expansion (multi-value sweep, per-bit-field stimulus).
        steps = mod.generate(plan, seq=0)
        plan.family_vectors[fam] = [steps]
    if not plan.family_vectors:
        raise EmissionError(
            "channel produced zero applicable vector families "
            "(INV-S-MEM-F-1 violated)",
            invariant="INV-S-MEM-F-1",
            channel_name=annotation.name,
        )
    return plan


def plan_chart(
    annotations: ChartAnnotations,
    *,
    base_address: int = 0x40000000,
) -> list[ChannelVectorPlan]:
    """Build per-channel plans for every annotated channel in chart order."""
    addrs = _compute_addresses(annotations, base_address=base_address)
    return [plan_channel(ch, address=addrs[ch.id]) for ch in annotations.channels]


# ---------------------------------------------------------------------------
# Vector instantiation + JUnit XML emission
# ---------------------------------------------------------------------------


def _instantiate_vector(
    plan: ChannelVectorPlan, family: VectorFamily, seq: int = 0
):
    mod = FAMILY_REGISTRY[family]
    return mod.vector_class(plan=plan, seq=seq)


def run_vectors(
    chart_plans: list[ChannelVectorPlan],
    out_dir: Path,
    *,
    chart_id: str = "chart",
) -> Path:
    """Run every plan's vectors against ``PythonCpuStubHarness``; emit junit.xml.

    Per §5.5 + PCDN-SOS-09-F-005: pytest-XUnit shape. The cocotb-side
    path delegates to cocotb's own pytest collector; the Python-stub
    path emits the same shape directly here so the JUnit XML gate (g)
    is satisfied without requiring cocotb to be installed at emit time.

    Returns the path to the emitted ``junit.xml``.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    testsuite = ET.Element("testsuite")
    testsuite.set("name", f"sos09f.{chart_id}")
    case_count = 0
    failure_count = 0
    suite_t0 = time.time()
    for plan in chart_plans:
        for family, step_lists in plan.family_vectors.items():
            for seq, _ in enumerate(step_lists):
                tc = ET.SubElement(testsuite, "testcase")
                tc.set("name", trace_key(plan.channel_id, family, seq))
                tc.set(
                    "classname",
                    f"{chart_id}.sos09.{plan.channel_name}",
                )
                t0 = time.time()
                harness = PythonCpuStubHarness()
                # Stage the channel mailbox in the bus.
                harness.register_channel(
                    address=plan.address,
                    width_bits=plan.width_bits,
                )
                vec = _instantiate_vector(plan, family, seq)
                try:
                    vec.setup(harness)
                    vec.stimulate(harness)
                    vec.observe(harness)
                    vec.assert_invariants(harness)
                except AssertionError as exc:
                    failure_count += 1
                    fel = ET.SubElement(tc, "failure")
                    fel.set("type", _failure_type_for(family))
                    fel.text = str(exc)
                except Exception as exc:  # noqa: BLE001
                    failure_count += 1
                    fel = ET.SubElement(tc, "error")
                    fel.set("type", type(exc).__name__)
                    fel.text = str(exc)
                tc.set("time", f"{time.time() - t0:.6f}")
                case_count += 1
    testsuite.set("tests", str(case_count))
    testsuite.set("failures", str(failure_count))
    testsuite.set("errors", "0")
    testsuite.set("skipped", "0")
    testsuite.set("time", f"{time.time() - suite_t0:.6f}")

    junit_path = out_dir / "junit.xml"
    tree = ET.ElementTree(testsuite)
    # ET.tostring -> pretty
    raw = ET.tostring(testsuite, encoding="utf-8", xml_declaration=True)
    junit_path.write_bytes(raw)
    return junit_path


def _failure_type_for(family: VectorFamily) -> str:
    """Map a family to its §5.5 failure-type token."""
    return {
        VectorFamily.INITIAL_VALUE: "InitialValueMismatch",
        VectorFamily.WRITE_THEN_READ: "WriteThenReadMismatch",
        VectorFamily.SIDE_EFFECT: "SideEffectNotObserved",
        VectorFamily.CLEAR_ON_READ: "ClearOnReadNotCleared",
        VectorFamily.ATOMICITY: "AtomicityTornRead",
        VectorFamily.PROTECTION: "ProtectionEventNotObserved",
    }[family]


# ---------------------------------------------------------------------------
# Emit directory layout — conftest.py + test_<family>.py
# ---------------------------------------------------------------------------


_CONFTEST_TEMPLATE = '''"""SOS-09-F emitted cocotb conftest — pytest-XUnit collector.

Auto-generated by ``tools/sos-codegen/vectors_emit.py`` per
``docs/concepts/SOS-09-F-CONCEPTS.md`` §5.5 (ratified 2026-05-26).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the SOS codegen tools importable.
_SOS_ROOT = Path(__file__).resolve().parents[3]
_TOOLS = _SOS_ROOT / "tools" / "sos-codegen"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
'''


_TEST_FAMILY_TEMPLATE = '''"""SOS-09-F emitted vectors — family={family_name}.

Auto-generated by ``tools/sos-codegen/vectors_emit.py`` per
``docs/concepts/SOS-09-F-CONCEPTS.md`` (ratified 2026-05-26).

Chart-id: {chart_id}
Vectors:  {vector_count}
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vectors.base import ChannelVectorPlan, VectorFamily
from vectors.families.{family_name} import vector_class
from vectors.harness import PythonCpuStubHarness


_PLANS_JSON = Path(__file__).parent / "plans.json"


def _load_plans():
    raw = json.loads(_PLANS_JSON.read_text(encoding="utf-8"))
    plans = []
    for p in raw["plans"]:
        if "{family_name}" not in p["families"]:
            continue
        plan = ChannelVectorPlan(
            channel_id=p["channel_id"],
            channel_name=p["channel_name"],
            channel_kind=p["channel_kind"],
            channel_zone=p["channel_zone"],
            channel_dir=p["channel_dir"],
            address=p["address"],
            width_bits=p["width_bits"],
            irq=p.get("irq"),
            mutex=p.get("mutex"),
            privilege_region=p.get("privilege_region"),
        )
        plans.append(plan)
    return plans


@pytest.mark.parametrize("plan", _load_plans(), ids=lambda p: p.channel_name)
def test_{family_name}(plan):
    """Exercise the {family_name} vector for each annotated channel."""
    harness = PythonCpuStubHarness()
    harness.register_channel(
        address=plan.address,
        width_bits=plan.width_bits,
    )
    vec = vector_class(plan=plan, seq=0)
    vec.setup(harness)
    vec.stimulate(harness)
    vec.observe(harness)
    vec.assert_invariants(harness)
'''


def _serialise_plan(plan: ChannelVectorPlan) -> dict:
    return {
        "channel_id": plan.channel_id,
        "channel_name": plan.channel_name,
        "channel_kind": plan.channel_kind,
        "channel_zone": plan.channel_zone,
        "channel_dir": plan.channel_dir,
        "address": plan.address,
        "width_bits": plan.width_bits,
        "irq": plan.irq,
        "mutex": plan.mutex,
        "privilege_region": plan.privilege_region,
        "families": sorted(f.value for f in plan.family_vectors.keys()),
    }


def emit_vectors(
    annotations: ChartAnnotations,
    *,
    chart_id: str,
    out_dir: Path | str,
    base_address: int = 0x40000000,
    regen_id: bool = False,
    log_fn: Optional[callable] = None,
) -> dict:
    """Emit a vector test directory + UUID cache.

    Per §5.4 / PCDN-SOS-09-F-004: when ``regen_id`` is False, UUIDs
    are frozen at first emit (cached in
    ``out_dir / .uuid-cache.json``); when True, the cache is rewritten
    AND every channel whose UUID changed is logged via ``log_fn``.

    Returns a summary dict::

        {
            "chart_id": ...,
            "plans": [serialised plans],
            "files": {filename: contents},
            "uuid_changes": [(channel_name, old_id, new_id), ...],
            "junit_path": Path,
        }
    """
    out_dir = Path(out_dir)
    chart_out = out_dir / chart_id
    chart_out.mkdir(parents=True, exist_ok=True)
    log_fn = log_fn or (lambda msg: None)

    plans = plan_chart(annotations, base_address=base_address)

    # --- UUID cache (PCDN-SOS-09-F-004) -------------------------------
    cache_path = chart_out / ".uuid-cache.json"
    prior: dict[str, str] = {}
    if cache_path.exists():
        try:
            prior = json.loads(cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            prior = {}
    uuid_changes: list[tuple[str, str, str]] = []
    for plan in plans:
        cached = prior.get(plan.channel_name)
        if cached and cached != plan.channel_id:
            if not regen_id:
                raise EmissionError(
                    f"channel {plan.channel_name!r} sos:id changed from "
                    f"{cached!r} to {plan.channel_id!r}; "
                    "pass --regen-id to accept (PCDN-SOS-09-F-004)",
                    invariant="PCDN-SOS-09-F-004",
                    channel_name=plan.channel_name,
                )
            uuid_changes.append((plan.channel_name, cached, plan.channel_id))
            log_fn(
                f"[--regen-id] channel {plan.channel_name!r} sos:id "
                f"changed: {cached} -> {plan.channel_id}"
            )
    new_cache = {p.channel_name: p.channel_id for p in plans}
    cache_path.write_text(
        json.dumps(new_cache, indent=2, sort_keys=True), encoding="utf-8"
    )

    # --- emit conftest + per-family test files ------------------------
    files: dict[str, str] = {}
    files["conftest.py"] = _CONFTEST_TEMPLATE
    plans_json = {
        "chart_id": chart_id,
        "plans": [_serialise_plan(p) for p in plans],
    }
    files["plans.json"] = json.dumps(plans_json, indent=2, sort_keys=True)
    # Per-family test files (one per family that any channel uses).
    families_in_use: set[VectorFamily] = set()
    for plan in plans:
        families_in_use.update(plan.family_vectors.keys())
    for fam in sorted(families_in_use, key=lambda f: f.value):
        body = _TEST_FAMILY_TEMPLATE.format(
            family_name=fam.value,
            chart_id=chart_id,
            vector_count=sum(
                1 for p in plans if fam in p.family_vectors
            ),
        )
        files[f"test_{fam.value}.py"] = body

    for fname, body in files.items():
        (chart_out / fname).write_text(body, encoding="utf-8")

    # --- run vectors + emit junit.xml ---------------------------------
    junit_path = run_vectors(plans, chart_out, chart_id=chart_id)

    return {
        "chart_id": chart_id,
        "plans": [_serialise_plan(p) for p in plans],
        "files": files,
        "uuid_changes": uuid_changes,
        "junit_path": junit_path,
        "out_dir": chart_out,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Iterable[str] | None = None) -> int:
    """``python -m vectors_emit ...`` entry point.

    Usage::

        python vectors_emit.py CHART_SCXML \
            --chart-id my_chart \
            --out-dir build/vectors \
            [--regen-id] \
            [--base-address 0x40000000]
    """
    p = argparse.ArgumentParser(
        prog="vectors_emit",
        description=(
            "SOS-09-F membrane-vector emitter. Walks a chart's SOS-09-A "
            "annotations and emits the test directory at "
            "build/vectors/<chart-id>/ plus a junit.xml report."
        ),
    )
    p.add_argument("chart", type=Path, help="path to chart .scxml")
    p.add_argument("--chart-id", required=True, help="chart id (output subdir)")
    p.add_argument(
        "--out-dir",
        type=Path,
        default=Path("build/vectors"),
        help="output base directory (default: build/vectors)",
    )
    p.add_argument(
        "--base-address",
        type=lambda s: int(s, 0),
        default=0x40000000,
        help="peripheral base address (default: 0x40000000)",
    )
    p.add_argument(
        "--regen-id",
        action="store_true",
        help=(
            "accept sos:id UUID changes (PCDN-SOS-09-F-004). Logs every "
            "channel whose UUID changed."
        ),
    )
    args = p.parse_args(list(argv) if argv is not None else None)

    from loader import load_chart  # noqa: PLC0415

    ast = load_chart(args.chart)
    if ast.raw_scjson is None:
        print(
            f"loader returned no raw_scjson for {args.chart}",
            file=sys.stderr,
        )
        return 1
    annotations = parse_chart_annotations(ast.raw_scjson)
    result = emit_vectors(
        annotations,
        chart_id=args.chart_id,
        out_dir=args.out_dir,
        base_address=args.base_address,
        regen_id=args.regen_id,
        log_fn=lambda msg: print(msg, file=sys.stderr),
    )
    print(f"emitted {len(result['plans'])} plans to {result['out_dir']}")
    print(f"junit.xml -> {result['junit_path']}")
    if result["uuid_changes"]:
        print(
            f"{len(result['uuid_changes'])} sos:id UUID changes "
            "(--regen-id was set)"
        )
    return 0


__all__ = [
    "emit_vectors",
    "main",
    "plan_chart",
    "plan_channel",
    "run_vectors",
]


if __name__ == "__main__":
    sys.exit(main())
