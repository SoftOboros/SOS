"""Tests for ``in_process_emit.py`` — SOS-10A in-process medium emitter.

Authority: ``docs/concepts/SOS-10-CONCEPTS.md`` §6.1 (ratified
2026-05-23). Input contract is owned by SOS-10-ANNOT
(``sos10_annotations.py``); this test module is a *consumer* of that
contract and uses scjson-shape dicts mirroring
``test_sos10_annotations.py``.

Covers:
    - happy path: 3-piece chart with rust↔rust + rust↔c in-process
      transitions emits Rust + C dispatch tables + FFI bridge.
    - event-id determinism: same `sos:id` → identical event_ids;
      different `sos:id` → different event_ids.
    - non-in-process transitions (kind="shared-memory") are SKIPPED.
    - emitted C compiles clean with `gcc -Wall -Wextra -Wpedantic
      -std=c11` (skipped when gcc not on PATH).
    - emitted Rust parses via `cargo check` against a minimal
      `Cargo.toml` (skipped when cargo not on PATH).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from in_process_emit import (  # noqa: E402
    EmittedEvent,
    emit_in_process,
    emit_in_process_from_chart,
)
from sos10_annotations import (  # noqa: E402
    parse_orchestrator_annotations,
)


# ---------------------------------------------------------------------------
# scjson-shape builders (mirror test_sos10_annotations.py)
# ---------------------------------------------------------------------------

SOS_NS = "https://softoboros.com/sos/1.0"
MEDIUM_QN = f"{{{SOS_NS}}}medium"
TRANSPORT_QN = f"{{{SOS_NS}}}transport"
TIMEOUT_QN = f"{{{SOS_NS}}}timeout"
IDEMPOTENT_QN = f"{{{SOS_NS}}}idempotent"


def _wrap_other_attrs(payload: dict) -> dict:
    return {"other_attributes": json.dumps(payload)}


def _medium_element(kind: str, *, transport: str | None = None) -> dict:
    children: list[dict] = []
    if transport is not None:
        children.append(
            {"qname": TRANSPORT_QN, "text": "", "attributes": {"name": transport}}
        )
    node: dict = {"qname": MEDIUM_QN, "text": "", "attributes": {"kind": kind}}
    if children:
        node["children"] = children
    return node


def _transition(event: str, target: str, *, medium: dict) -> dict:
    return {"event": event, "target": [target], "other_element": [medium]}


def _piece(
    state_id: str,
    *,
    lang: str,
    transitions: list[dict] | None = None,
) -> dict:
    node: dict = {
        "id": state_id,
        "other_attributes": _wrap_other_attrs({"sos:lang": lang}),
    }
    if transitions is not None:
        node["transition"] = transitions
    return node


def _chart(pieces: list[dict]) -> dict:
    return {
        "state": pieces,
        "version": 1.0,
        "datamodel_attribute": "ecmascript",
        "initial": [pieces[0]["id"]] if pieces else [],
    }


# Stable test chart-id UUIDs (no collisions with sos_09 / sos_10 fixtures).
CHART_ID_A: str = "ee000000-0000-4000-8000-000000000010"
CHART_ID_B: str = "ee000000-0000-4000-8000-0000000000ff"


# ---------------------------------------------------------------------------
# Happy-path
# ---------------------------------------------------------------------------


def _three_piece_chart() -> dict:
    return _chart(
        [
            _piece(
                "alpha",
                lang="rust",
                transitions=[
                    _transition(
                        "evt.alpha_to_beta",
                        "beta",
                        medium=_medium_element("in-process"),
                    ),
                    _transition(
                        "evt.alpha_to_gamma",
                        "gamma",
                        medium=_medium_element("in-process"),
                    ),
                ],
            ),
            _piece(
                "beta",
                lang="rust",
                transitions=[
                    # Non-in-process — emitter MUST skip.
                    _transition(
                        "evt.beta_to_gamma",
                        "gamma",
                        medium=_medium_element("shared-memory"),
                    ),
                ],
            ),
            _piece(
                "gamma",
                lang="c",
                transitions=[
                    _transition(
                        "evt.gamma_to_alpha",
                        "alpha",
                        medium=_medium_element("in-process"),
                    ),
                ],
            ),
        ]
    )


def test_happy_path_emits_rust_and_c_dispatch():
    """3-piece chart with rust↔rust + rust↔c in-process transitions
    emits Rust + C dispatch tables plus the FFI bridge."""
    annotations = parse_orchestrator_annotations(_three_piece_chart())
    out = emit_in_process(annotations, chart_sos_id=CHART_ID_A)

    # Rust pieces alpha + beta → .rs files.
    assert "alpha_dispatch.rs" in out
    assert "beta_dispatch.rs" in out
    # C piece gamma → .h + .c.
    assert "gamma_dispatch.h" in out
    assert "gamma_dispatch.c" in out
    # rust↔c boundary present → FFI bridge.
    assert "ffi_bridge.rs" in out


def test_emitted_files_carry_spec_block():
    """Every emitted file SHOULD cite SOS-10 §6.1 + INV-S-ORCH-1/-2/-4
    + INV-SOS-A + the chart sos:id."""
    annotations = parse_orchestrator_annotations(_three_piece_chart())
    out = emit_in_process(annotations, chart_sos_id=CHART_ID_A)
    for fname, text in out.items():
        assert "SOS-10-CONCEPTS §6.1" in text, fname
        assert "INV-S-ORCH-1" in text, fname
        assert "INV-S-ORCH-2" in text, fname
        assert "INV-S-ORCH-4" in text, fname
        assert "INV-SOS-A" in text, fname
        assert CHART_ID_A in text, fname


def test_emitted_files_handler_registration():
    """The Rust alpha dispatch table MUST register the gamma→alpha event
    (alpha is its target); the C gamma dispatch MUST register the two
    events alpha→gamma (gamma is target). The non-in-process beta→gamma
    transition MUST NOT appear anywhere."""
    annotations = parse_orchestrator_annotations(_three_piece_chart())
    out = emit_in_process(annotations, chart_sos_id=CHART_ID_A)

    alpha_rs = out["alpha_dispatch.rs"]
    assert "evt.gamma_to_alpha" in alpha_rs
    # alpha sends but doesn't receive evt.alpha_to_beta/gamma; those names
    # should not show as handler stubs in alpha_rs.
    assert "evt.alpha_to_beta" not in alpha_rs
    assert "evt.alpha_to_gamma" not in alpha_rs

    gamma_c = out["gamma_dispatch.c"]
    gamma_h = out["gamma_dispatch.h"]
    assert "evt.alpha_to_gamma" in gamma_c
    assert "evt.alpha_to_gamma" in gamma_h
    # The skipped shared-memory beta→gamma transition is NOT in gamma.
    assert "evt.beta_to_gamma" not in gamma_c
    assert "evt.beta_to_gamma" not in gamma_h


def test_non_inprocess_transitions_skipped():
    """A chart whose only transitions are non-in-process emits no files."""
    chart = _chart(
        [
            _piece(
                "alpha",
                lang="rust",
                transitions=[
                    _transition(
                        "evt", "beta", medium=_medium_element("shared-memory"),
                    )
                ],
            ),
            _piece("beta", lang="rust"),
        ]
    )
    annotations = parse_orchestrator_annotations(chart)
    out = emit_in_process(annotations, chart_sos_id=CHART_ID_A)
    assert out == {}


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_event_id_determinism_same_sos_id():
    """Two emit runs against the same chart + sos:id produce identical
    event-id assignments AND byte-identical file text."""
    annotations = parse_orchestrator_annotations(_three_piece_chart())
    out_a = emit_in_process(annotations, chart_sos_id=CHART_ID_A)
    out_b = emit_in_process(annotations, chart_sos_id=CHART_ID_A)
    assert out_a == out_b


def test_event_id_differs_across_sos_id():
    """Two charts identical except for `sos:id` produce DIFFERENT event_ids."""
    annotations = parse_orchestrator_annotations(_three_piece_chart())
    out_a = emit_in_process(annotations, chart_sos_id=CHART_ID_A)
    out_b = emit_in_process(annotations, chart_sos_id=CHART_ID_B)

    # Extract event-id hex literals from the gamma dispatch (which has
    # the most events registered). Both files have the same set of event
    # names but the u32 hex literals must differ.
    def _hexes(text: str) -> set[str]:
        # Capture only the 8-hex-digit body, dropping the language-specific
        # suffix (`u`/`u32`) so cross-language comparisons line up.
        return set(re.findall(r"0x([0-9a-f]{8})", text))

    a_hex = _hexes(out_a["gamma_dispatch.c"])
    b_hex = _hexes(out_b["gamma_dispatch.c"])
    assert a_hex
    assert a_hex.isdisjoint(b_hex), (
        f"event-ids overlapped across sos:id values: {a_hex & b_hex!r}"
    )


def test_event_id_is_u32_range():
    """Every emitted hex literal MUST fit in u32."""
    annotations = parse_orchestrator_annotations(_three_piece_chart())
    out = emit_in_process(annotations, chart_sos_id=CHART_ID_A)
    for text in out.values():
        for body in re.findall(r"0x([0-9a-f]{8})", text):
            val = int(body, 16)
            assert 0 <= val <= 0xFFFFFFFF


# ---------------------------------------------------------------------------
# Disk-write surface
# ---------------------------------------------------------------------------


def test_output_dir_persisted(tmp_path):
    """When `output_dir` is provided, every emitted file is written."""
    annotations = parse_orchestrator_annotations(_three_piece_chart())
    out = emit_in_process(
        annotations, chart_sos_id=CHART_ID_A, output_dir=tmp_path
    )
    for fname in out:
        assert (tmp_path / fname).read_text(encoding="utf-8") == out[fname]


# ---------------------------------------------------------------------------
# C compile gate
# ---------------------------------------------------------------------------


def test_emitted_c_compiles_clean(tmp_path):
    """Emitted C must compile clean with `gcc -Wall -Wextra -Wpedantic -std=c11`.

    Skipped when no `gcc` (or `cc` fallback) is on PATH.
    """
    compiler = shutil.which("gcc") or shutil.which("cc") or shutil.which("clang")
    if compiler is None:
        pytest.skip("no C compiler on PATH (gcc/cc/clang)")

    annotations = parse_orchestrator_annotations(_three_piece_chart())
    out = emit_in_process(
        annotations, chart_sos_id=CHART_ID_A, output_dir=tmp_path
    )
    # Compile gamma_dispatch.c (the only C piece).
    obj = tmp_path / "gamma_dispatch.o"
    res = subprocess.run(
        [
            compiler,
            "-Wall", "-Wextra", "-Wpedantic", "-std=c11",
            "-c", str(tmp_path / "gamma_dispatch.c"),
            "-o", str(obj),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, (
        f"compile failed:\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}\n"
        f"source:\n{(tmp_path / 'gamma_dispatch.c').read_text()}\n"
        f"header:\n{(tmp_path / 'gamma_dispatch.h').read_text()}"
    )
    # No diagnostics on stderr — `-Werror` is too strict for the weak
    # symbol guard, but a clean compile should print nothing.
    assert res.stderr.strip() == "", f"unexpected diagnostics:\n{res.stderr}"
    assert obj.exists()


# ---------------------------------------------------------------------------
# Rust syntax gate
# ---------------------------------------------------------------------------


_MIN_CARGO_TOML = """\
[package]
name = "sos10_inproc_check"
version = "0.0.0"
edition = "2021"

[lib]
path = "lib.rs"

[profile.dev]
overflow-checks = false
"""


def test_emitted_rust_parses_via_cargo(tmp_path):
    """Emitted Rust must parse cleanly via `cargo check`.

    Skipped when no `cargo` is on PATH.
    """
    cargo = shutil.which("cargo")
    if cargo is None:
        pytest.skip("cargo not on PATH")

    annotations = parse_orchestrator_annotations(_three_piece_chart())
    out = emit_in_process(annotations, chart_sos_id=CHART_ID_A)

    # Build a minimal one-package crate where lib.rs glues each emitted
    # .rs into one module hierarchy.
    crate_dir = tmp_path / "sos10_inproc_check"
    crate_dir.mkdir()
    (crate_dir / "Cargo.toml").write_text(_MIN_CARGO_TOML, encoding="utf-8")

    rust_files = [f for f in out if f.endswith(".rs")]
    lib_lines: list[str] = [
        "#![allow(non_snake_case)]",
        "#![allow(non_camel_case_types)]",
        "#![allow(dead_code)]",
    ]
    for fname in rust_files:
        # Each emitted file is self-contained; expose as its own module
        # so duplicate top-level item names (DISPATCH_TABLE, etc.) do
        # not collide.
        modname = fname.rsplit(".", 1)[0]
        (crate_dir / fname).write_text(out[fname], encoding="utf-8")
        lib_lines.append(f'#[path = "{fname}"] pub mod {modname};')
    (crate_dir / "lib.rs").write_text(
        "\n".join(lib_lines) + "\n", encoding="utf-8"
    )

    res = subprocess.run(
        [cargo, "check", "--quiet", "--offline"],
        cwd=crate_dir,
        capture_output=True,
        text=True,
        check=False,
        env={
            **__import__("os").environ,
            "RUSTFLAGS": "",
            "CARGO_NET_OFFLINE": "true",
        },
    )
    # Offline mode may fail if the local cargo cache lacks the empty
    # crate's std reference; fall back to non-offline (which will use
    # network if available, but our crate has no deps).
    if res.returncode != 0 and "offline" in (res.stderr + res.stdout).lower():
        res = subprocess.run(
            [cargo, "check", "--quiet"],
            cwd=crate_dir,
            capture_output=True,
            text=True,
            check=False,
            env={**__import__("os").environ, "RUSTFLAGS": ""},
        )
    if res.returncode != 0 and (
        "no such subcommand" in res.stderr.lower()
        or "could not find" in res.stderr.lower()
    ):
        pytest.skip(f"cargo check unavailable: {res.stderr.strip()[:200]}")
    assert res.returncode == 0, (
        f"cargo check failed:\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}"
    )


# ---------------------------------------------------------------------------
# `emit_in_process_from_chart` — end-to-end via the fixture
# ---------------------------------------------------------------------------


_FIXTURE = (
    _TOOLS_DIR / "tests" / "fixtures" / "sos_10_inproc"
    / "orchestrator_2piece_inproc.scxml"
)


def test_emit_from_chart_uses_root_sos_id(tmp_path):
    """`emit_in_process_from_chart` MUST default `chart_sos_id` from the
    root scxml's `sos:id` attribute and emit a non-empty file set."""
    if not _FIXTURE.exists():
        pytest.skip(f"fixture missing: {_FIXTURE}")
    if shutil.which("scjson") is None:
        pytest.skip("scjson CLI not on PATH")
    out = emit_in_process_from_chart(_FIXTURE, output_dir=tmp_path)
    assert "alpha_dispatch.rs" in out
    assert "gamma_dispatch.h" in out
    assert "gamma_dispatch.c" in out
    # Fixture's root sos:id token must surface in the spec block.
    fixture_id = "ee000000-0000-4000-8000-000000000010"
    for fname, text in out.items():
        assert fixture_id in text, fname


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------


def test_empty_chart_sos_id_rejected():
    """Empty `chart_sos_id` is a chart-author error — emitter rejects."""
    annotations = parse_orchestrator_annotations(_three_piece_chart())
    with pytest.raises(ValueError):
        emit_in_process(annotations, chart_sos_id="")


def test_unsupported_lang_rejected():
    """Pieces with `sos:lang` outside {rust, c} on an in-process edge raise."""
    chart = _chart(
        [
            _piece(
                "alpha",
                lang="rust",
                transitions=[
                    _transition(
                        "evt", "beta", medium=_medium_element("in-process"),
                    )
                ],
            ),
            _piece("beta", lang="python"),
        ]
    )
    annotations = parse_orchestrator_annotations(chart)
    with pytest.raises(ValueError) as exc_info:
        emit_in_process(annotations, chart_sos_id=CHART_ID_A)
    assert "python" in str(exc_info.value).lower() or "rust" in str(exc_info.value).lower()
