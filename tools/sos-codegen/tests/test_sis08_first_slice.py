"""SIS-08B first-slice artifact regression tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

_TOOLS_DIR = Path(__file__).resolve().parents[1]
_SOS_ROOT = _TOOLS_DIR.parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from loader import load_chart  # noqa: E402
from sis08_first_slice import emit_first_slice  # noqa: E402
from sos09_annotations import parse_chart_annotations  # noqa: E402


CHART = _SOS_ROOT / "charts" / "sis08_first_slice" / "sis08_first_slice.scxml"
ARTIFACT_DIR = CHART.parent


def test_chart_declares_first_slice_channel_set() -> None:
    ast = load_chart(CHART)
    annotations = parse_chart_annotations(ast.raw_scjson)
    names = [ch.name for ch in annotations.channels]
    assert names == [
        "fifo_data",
        "fifo_status",
        "fifo_control",
        "mailbox_notify",
        "credit_budget",
    ]
    kinds = {ch.name: ch.kind for ch in annotations.channels}
    assert kinds == {
        "fifo_data": "queue",
        "fifo_status": "status",
        "fifo_control": "command",
        "mailbox_notify": "status",
        "credit_budget": "shared",
    }


def test_committed_artifacts_are_regenerated_byte_for_byte(tmp_path: Path) -> None:
    out_dir = tmp_path / "sis08_first_slice"
    emit_first_slice(chart=CHART, out_dir=out_dir)
    relative_paths = [
        "sis08_first_slice.svd",
        "sis08_first_slice_mpu.c",
        "sis08_first_slice_mpu.rs",
        "sis08_first_slice_mpu_background.txt",
        "sis08_first_slice_manifest.json",
        "vectors/sis08_first_slice/.uuid-cache.json",
        "vectors/sis08_first_slice/conftest.py",
        "vectors/sis08_first_slice/plans.json",
        "vectors/sis08_first_slice/test_atomicity.py",
        "vectors/sis08_first_slice/test_clear_on_read.py",
        "vectors/sis08_first_slice/test_initial_value.py",
        "vectors/sis08_first_slice/test_protection.py",
        "vectors/sis08_first_slice/test_side_effect.py",
        "vectors/sis08_first_slice/test_write_then_read.py",
    ]
    for rel in relative_paths:
        assert (out_dir / rel).read_text(encoding="utf-8") == (
            ARTIFACT_DIR / rel
        ).read_text(encoding="utf-8")


def test_svd_has_fifo_mailbox_and_credit_registers() -> None:
    root = ET.fromstring((ARTIFACT_DIR / "sis08_first_slice.svd").read_text())
    registers = root.findall("./peripherals/peripheral/registers/register")
    names = [reg.find("name").text for reg in registers]
    assert names == [
        "fifo_data",
        "fifo_status",
        "fifo_control",
        "mailbox_notify",
        "credit_budget",
    ]
    fifo_status = registers[1]
    mailbox_notify = registers[3]
    assert fifo_status.find("readAction").text == "clear"
    assert mailbox_notify.find("readAction").text == "clear"


def test_manifest_is_streamz_membraneref_ready() -> None:
    manifest = json.loads(
        (ARTIFACT_DIR / "sis08_first_slice_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["id"] == "sis08-first-slice-membrane"
    assert manifest["placement"] == "hardware-block"
    assert manifest["backend"] == "hdl-sos"
    assert manifest["descriptor"]["path"] == (
        "charts/sis08_first_slice/sis08_first_slice.svd"
    )
    assert manifest["descriptor"]["contentHash"].startswith("sha256:")
    assert manifest["rtlIntegrationBench"] == {
        "makefile": "tb/sis08_first_slice/Makefile",
        "test": "tb/sis08_first_slice/test_sis08_first_slice.py",
        "top": "tb/sis08_first_slice/sis08_first_slice_top.sv",
    }
    assert {ch["name"] for ch in manifest["channels"]} == {
        "fifo_data",
        "fifo_status",
        "fifo_control",
        "mailbox_notify",
        "credit_budget",
    }


def test_vector_plan_covers_required_membrane_families() -> None:
    plans = json.loads(
        (ARTIFACT_DIR / "vectors" / "sis08_first_slice" / "plans.json").read_text(
            encoding="utf-8"
        )
    )["plans"]
    families = {fam for plan in plans for fam in plan["families"]}
    assert families == {
        "atomicity",
        "clear_on_read",
        "initial_value",
        "protection",
        "side_effect",
        "write_then_read",
    }
