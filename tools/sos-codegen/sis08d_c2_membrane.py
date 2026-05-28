#!/usr/bin/env python3
"""Emit the SIS-08D C2-A SRAM-membrane proof artifacts.

The chart under ``charts/sis08d_c2_membrane`` is the single input. This
script materializes the SOS-09-B CMSIS-SVD descriptor, the SOS-09-G MPU
tables, the SOS-09-F vector directory, and a deterministic manifest that
Streamz can reference through ``StatechartImpl.membraneRef``.

Mirrors ``sis08_first_slice.py`` (the SIS-08B precedent emitter) and
satisfies ``docs/todo/streamz/statechart-orchestration/TODO-SIS-08D-C2-IMPLEMENTATION-PLAN.md``
§3 work package C2-A and §4 membrane-contract requirements.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
SOS_ROOT = TOOLS_DIR.parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from loader import load_chart  # noqa: E402
from sos09_annotations import parse_chart_annotations  # noqa: E402
from transliterate_mpu import (  # noqa: E402
    derive_mpu_regions,
    emit_mpu_background_setting,
    emit_mpu_c,
    emit_mpu_rust,
)
from transliterate_svd import emit_svd  # noqa: E402
from vectors_emit import emit_vectors  # noqa: E402


DEFAULT_CHART = SOS_ROOT / "charts" / "sis08d_c2_membrane" / "sis08d_c2_membrane.scxml"
DEFAULT_OUT_DIR = DEFAULT_CHART.parent
DEFAULT_CHART_ID = "sis08d_c2_membrane"
# C2 SRAM-membrane base address: distinct from SIS-08B's 0x40000000 MMIO
# slice so the two membranes can coexist in a unified address space if a
# downstream consumer composes them. 0x40010000 is still in the FPGA-side
# peripheral window; the SRAM_WINDOW shared channel sits past the
# command/status/mailbox registers per SOS-09-B's address-offset policy.
DEFAULT_BASE_ADDRESS = 0x40010000


def _sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _write_text(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _patch_vector_conftest(chart_out: Path) -> None:
    """Adjust SOS-09-F's build-dir conftest for the checked-in chart layout."""
    conftest = chart_out / "conftest.py"
    if not conftest.exists():
        return
    body = conftest.read_text(encoding="utf-8")
    body = body.replace(
        "_SOS_ROOT = Path(__file__).resolve().parents[3]",
        "_SOS_ROOT = Path(__file__).resolve().parents[4]",
    )
    conftest.write_text(body, encoding="utf-8")


def _logical_artifact_path(name: str) -> str:
    """Return the checked-in logical path used in the descriptor manifest."""
    return str((DEFAULT_OUT_DIR / name).relative_to(SOS_ROOT))


def emit_membrane(
    *,
    chart: Path = DEFAULT_CHART,
    out_dir: Path = DEFAULT_OUT_DIR,
    chart_id: str = DEFAULT_CHART_ID,
    base_address: int = DEFAULT_BASE_ADDRESS,
) -> dict:
    ast = load_chart(chart)
    annotations = parse_chart_annotations(ast.raw_scjson)

    svd = emit_svd(
        annotations,
        device_name="Sis08dC2Membrane",
        base_address=base_address,
    )
    mpu_regions = derive_mpu_regions(annotations, base_address=base_address)
    mpu_c = emit_mpu_c(mpu_regions, table_name="sis08d_c2_membrane_mpu_regions")
    mpu_rust = emit_mpu_rust(
        mpu_regions, const_name="SIS08D_C2_MEMBRANE_MPU_REGIONS"
    )
    mpu_background = emit_mpu_background_setting(annotations)
    mpu_background_text = "\n".join(
        [mpu_background["c_define"], mpu_background["rust_const"]]
    )

    svd_path = out_dir / "sis08d_c2_membrane.svd"
    mpu_c_path = out_dir / "sis08d_c2_membrane_mpu.c"
    mpu_rs_path = out_dir / "sis08d_c2_membrane_mpu.rs"
    mpu_background_path = out_dir / "sis08d_c2_membrane_mpu_background.txt"
    vectors_base = out_dir / "vectors"

    _write_text(svd_path, svd)
    _write_text(mpu_c_path, mpu_c)
    _write_text(mpu_rs_path, mpu_rust)
    _write_text(mpu_background_path, mpu_background_text + "\n")

    vector_result = emit_vectors(
        annotations,
        chart_id=chart_id,
        out_dir=vectors_base,
        base_address=base_address,
    )
    chart_vector_dir = Path(vector_result["out_dir"])
    _patch_vector_conftest(chart_vector_dir)

    # junit.xml is run evidence, not a stable source artifact. The make target
    # regenerates it in-place as needed.
    junit_path = chart_vector_dir / "junit.xml"
    if junit_path.exists():
        junit_path.unlink()

    # Filter out pytest droppings + bytecode caches so the manifest stays
    # deterministic across re-runs after the vectors have been exercised.
    _CACHE_DIR_NAMES = {"__pycache__", ".pytest_cache"}

    def _is_stable(p: Path) -> bool:
        if not p.is_file() or p.name == "junit.xml":
            return False
        return not any(part in _CACHE_DIR_NAMES for part in p.parts)

    stable_vector_files = sorted(
        p for p in chart_vector_dir.rglob("*") if _is_stable(p)
    )
    manifest = {
        "id": "sis08d-c2-membrane",
        "version": "0.1.0",
        "chart": str(chart.relative_to(SOS_ROOT)),
        "chartHash": _sha256_file(chart),
        "baseAddress": f"0x{base_address:08X}",
        "backend": "hdl-sos",
        # 2026-05-28 Path B per EOQ-002-ERRATA-002: the chart's semantic
        # surface is a shared memory region with command/status/transfer
        # channels, but its target access mechanism is memory-mapped IO
        # (the C2-A baseAddress 0x40010000 lands on STM32H747's APB2
        # peripheral space; on a future FPGA-backed target the membrane
        # is a custom-peripheral MMIO region). `mmio-peripheral` names
        # the access mechanism explicitly per SOS-09-A §15 amendment.
        "placement": "mmio-peripheral",
        "descriptor": {
            "format": "cmsis-svd-1.3",
            "path": _logical_artifact_path("sis08d_c2_membrane.svd"),
            "contentHash": _sha256_text(svd),
        },
        "mpu": {
            "c": _logical_artifact_path("sis08d_c2_membrane_mpu.c"),
            "rust": _logical_artifact_path("sis08d_c2_membrane_mpu.rs"),
            "background": mpu_background,
        },
        "vectors": [
            {
                "path": _logical_artifact_path(
                    str(p.relative_to(chart_vector_dir.parent.parent))
                ),
                "contentHash": _sha256_file(p),
            }
            for p in stable_vector_files
        ],
        "channels": [
            {
                "id": ch.id,
                "name": ch.name,
                "kind": ch.kind,
                "dir": ch.dir,
                "zone": ch.zone,
                "width": ch.width,
                "irq": ch.irq,
                "mutex": ch.mutex,
            }
            for ch in annotations.channels
        ],
        "satisfies": [
            "SIS-08D §2 single SRAM-membrane proof",
            "SIS-08D §3 work package C2-A membrane contract",
            "SIS-08D §4 membrane-contract requirements (ownership, byte layout, command/status/transfer/notification)",
            "SIS-08D §5 step 1 interpreted-simulation evidence",
            "SIS-08C §7 second-hardware-slice selection rationale",
            "SIS-03 §4.10 mailbox notification semantics",
        ],
    }
    manifest_path = out_dir / "sis08d_c2_membrane_manifest.json"
    _write_text(
        manifest_path,
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    )
    return manifest


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--chart", type=Path, default=DEFAULT_CHART)
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    p.add_argument("--chart-id", default=DEFAULT_CHART_ID)
    p.add_argument(
        "--base-address",
        type=lambda s: int(s, 0),
        default=DEFAULT_BASE_ADDRESS,
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(argv) if argv is not None else sys.argv[1:])
    manifest = emit_membrane(
        chart=args.chart,
        out_dir=args.out_dir,
        chart_id=args.chart_id,
        base_address=args.base_address,
    )
    print(
        f"emitted {manifest['id']} with {len(manifest['channels'])} channels "
        f"to {args.out_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
