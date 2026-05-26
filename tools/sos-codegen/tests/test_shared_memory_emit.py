"""Tests for `shared_memory_emit.py` — SOS-10-B `shared-memory` emitter.

Authority: `docs/concepts/SOS-10-CONCEPTS.md` §6.2 (ratified 2026-05-23).
Covers:

  * Happy path — 2-piece chart, one shared-memory transition emits the
    shared C header + a rust producer + a c consumer (mixed-language).
  * Ring-capacity override propagates from `MediumAnnotation.extras`
    into the emitted header constants.
  * Default ring capacity (256) when chart omits override.
  * Mixed-language pairing (rust producer + c consumer) emits correct
    artifacts on both sides.
  * Determinism — two emit runs against the same chart produce
    byte-identical output.
  * C-compile check — `gcc -Wall -Wextra -Wpedantic -std=c11` on the
    emitted header (skipped if gcc / clang missing).
  * Fixture-driven end-to-end through scjson.

Per SOS-10-B v1 the supported languages are `rust` and `c`; other
`sos:lang` values surface a deliberate `.UNSUPPORTED` marker, not a
raise.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Make `sos-codegen` modules importable regardless of pytest cwd.
_TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from loader import load_chart  # noqa: E402
from shared_memory_emit import (  # noqa: E402
    DEFAULT_RING_CAPACITY,
    SharedMemoryEmitError,
    emit_shared_memory,
    extract_ring_capacity,
)
from sos10_annotations import (  # noqa: E402
    CrossPieceTransitionAnnotation,
    MediumAnnotation,
    OrchestratorAnnotations,
    PieceAnnotation,
    parse_orchestrator_annotations,
)


# ---------------------------------------------------------------------------
# Annotation builders (in-process; sidesteps scjson for the unit tests).
# ---------------------------------------------------------------------------


def _piece(state_id: str, lang: str) -> PieceAnnotation:
    return PieceAnnotation(state_id=state_id, lang=lang)


def _shmem_transition(
    src: str,
    dst: str,
    *,
    event: str = "evt.frame",
    ring_capacity: int | None = None,
    rtos: str | None = None,
    timeout: int | None = None,
) -> CrossPieceTransitionAnnotation:
    extras: dict[str, object] = {}
    if ring_capacity is not None:
        extras["ring_capacity"] = ring_capacity
    if rtos is not None:
        extras["rtos"] = rtos
    medium = MediumAnnotation(
        kind="shared-memory",
        transport=None,
        timeout=timeout,
        idempotent=None,
        extras=extras,
    )
    return CrossPieceTransitionAnnotation(
        source_state_id=src,
        target_state_id=dst,
        event=event,
        medium=medium,
        idempotent=None,
        extras={},
    )


def _annotations(
    pieces: list[PieceAnnotation],
    transitions: list[CrossPieceTransitionAnnotation],
) -> OrchestratorAnnotations:
    return OrchestratorAnnotations(pieces=pieces, transitions=transitions)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_happy_path_emits_shared_header_and_per_lang_sources():
    """2-piece chart, one shared-memory transition → shared header +
    rust producer (source piece) + c consumer (target piece)."""
    ann = _annotations(
        pieces=[_piece("producer", "rust"), _piece("consumer", "c")],
        transitions=[_shmem_transition("producer", "consumer")],
    )

    files = emit_shared_memory(ann, chart_id="happy_chart")

    # Exactly one pairing → three emitted artifacts.
    assert "producer_to_consumer_ring.h" in files
    assert "producer_to_consumer_ring_producer.rs" in files
    assert "producer_to_consumer_ring_consumer.c" in files
    assert len(files) == 3

    header = files["producer_to_consumer_ring.h"]
    # @spec banner + invariant citations.
    assert "SOS-10-CONCEPTS.md §6.2" in header
    assert "INV-S-ORCH-1" in header and "INV-S-ORCH-4" in header
    assert "INV-S-ORCH-5" in header
    assert "INV-SOS-A" in header
    # POSIX SHM name + ring-buffer descriptor + atomic head/tail.
    assert '"/sos_producer_consumer_ring"' in header
    assert "atomic_uint_fast32_t head" in header
    assert "atomic_uint_fast32_t tail" in header
    assert "typedef struct producer_to_consumer_ring_s" in header
    # Default capacity.
    assert (
        f"SOS_PRODUCER_CONSUMER_RING_CAPACITY {DEFAULT_RING_CAPACITY}u"
        in header
    )

    rust_prod = files["producer_to_consumer_ring_producer.rs"]
    assert "pub struct ProducerHandle" in rust_prod
    assert "pub fn try_send" in rust_prod
    assert 'feature = "posix_shm"' in rust_prod
    assert f"pub const RING_CAPACITY: usize = {DEFAULT_RING_CAPACITY};" in rust_prod
    # @spec banner present.
    assert "SOS-10-CONCEPTS.md §6.2" in rust_prod

    c_cons = files["producer_to_consumer_ring_consumer.c"]
    assert "sos_producer_consumer_try_recv" in c_cons
    assert "atomic_load_explicit" in c_cons
    assert "memory_order_acquire" in c_cons
    assert "memory_order_release" in c_cons
    assert "SOS-10-CONCEPTS.md §6.2" in c_cons


# ---------------------------------------------------------------------------
# Ring-capacity override propagation
# ---------------------------------------------------------------------------


def test_ring_capacity_override_propagates_into_header():
    """`extras["ring_capacity"]=512` propagates to header capacity macro."""
    ann = _annotations(
        pieces=[_piece("alpha", "rust"), _piece("beta", "c")],
        transitions=[_shmem_transition("alpha", "beta", ring_capacity=512)],
    )
    files = emit_shared_memory(ann, chart_id="cap_chart")
    header = files["alpha_to_beta_ring.h"]
    assert "SOS_ALPHA_BETA_RING_CAPACITY 512u" in header
    rust_prod = files["alpha_to_beta_ring_producer.rs"]
    assert "pub const RING_CAPACITY: usize = 512;" in rust_prod
    c_cons = files["alpha_to_beta_ring_consumer.c"]
    # C side reads capacity via header macro; no inline literal in the
    # consumer source. Still check the @spec banner records the value.
    assert "@ring_slots 512" in c_cons


def test_ring_capacity_accepts_string_form():
    """The override coerces decimal strings (parser may surface str)."""
    ann = _annotations(
        pieces=[_piece("a", "rust"), _piece("b", "c")],
        transitions=[
            CrossPieceTransitionAnnotation(
                source_state_id="a",
                target_state_id="b",
                event="evt",
                medium=MediumAnnotation(
                    kind="shared-memory",
                    extras={"ring_capacity": "1024"},
                ),
            )
        ],
    )
    files = emit_shared_memory(ann, chart_id="str_cap_chart")
    assert "SOS_A_B_RING_CAPACITY 1024u" in files["a_to_b_ring.h"]


def test_ring_capacity_rejects_non_positive():
    """Capacity <= 0 raises SharedMemoryEmitError (chart-author error)."""
    with pytest.raises(SharedMemoryEmitError):
        extract_ring_capacity(
            MediumAnnotation(kind="shared-memory", extras={"ring_capacity": 0})
        )
    with pytest.raises(SharedMemoryEmitError):
        extract_ring_capacity(
            MediumAnnotation(kind="shared-memory", extras={"ring_capacity": -1})
        )


def test_ring_capacity_rejects_garbage():
    """Non-int / bool / non-decimal-string capacities raise."""
    with pytest.raises(SharedMemoryEmitError):
        extract_ring_capacity(
            MediumAnnotation(kind="shared-memory", extras={"ring_capacity": True})
        )
    with pytest.raises(SharedMemoryEmitError):
        extract_ring_capacity(
            MediumAnnotation(
                kind="shared-memory", extras={"ring_capacity": "not-a-number"}
            )
        )


def test_ring_capacity_default_when_absent():
    """No override → DEFAULT_RING_CAPACITY (256)."""
    assert (
        extract_ring_capacity(MediumAnnotation(kind="shared-memory"))
        == DEFAULT_RING_CAPACITY
    )
    assert DEFAULT_RING_CAPACITY == 256


# ---------------------------------------------------------------------------
# Mixed-language pairings
# ---------------------------------------------------------------------------


def test_mixed_language_rust_producer_c_consumer():
    """rust source + c target → rust producer + c consumer per pairing."""
    ann = _annotations(
        pieces=[_piece("rs_piece", "rust"), _piece("c_piece", "c")],
        transitions=[_shmem_transition("rs_piece", "c_piece")],
    )
    files = emit_shared_memory(ann, chart_id="mix_chart")
    assert "rs_piece_to_c_piece_ring_producer.rs" in files
    assert "rs_piece_to_c_piece_ring_consumer.c" in files
    assert "rs_piece_to_c_piece_ring.h" in files


def test_mixed_language_c_producer_rust_consumer():
    """c source + rust target → c producer + rust consumer per pairing."""
    ann = _annotations(
        pieces=[_piece("c_piece", "c"), _piece("rs_piece", "rust")],
        transitions=[_shmem_transition("c_piece", "rs_piece")],
    )
    files = emit_shared_memory(ann, chart_id="mix_chart_2")
    assert "c_piece_to_rs_piece_ring_producer.c" in files
    assert "c_piece_to_rs_piece_ring_consumer.rs" in files


def test_unsupported_lang_emits_marker_not_raises():
    """sos:lang values other than rust/c surface a marker; no raise."""
    ann = _annotations(
        pieces=[_piece("a", "rust"), _piece("b", "python")],
        transitions=[_shmem_transition("a", "b")],
    )
    files = emit_shared_memory(ann, chart_id="unsup_chart")
    # rust producer side present...
    assert "a_to_b_ring_producer.rs" in files
    # ...python consumer surfaces a marker file instead of a .py source.
    marker = [k for k in files if k.endswith(".UNSUPPORTED")]
    assert len(marker) == 1
    assert "python" in marker[0]
    assert "consumer" in marker[0]


def test_both_rust_emits_two_rust_files_plus_header():
    """rust → rust pairings still emit the shared C header (wire-format
    source of truth per INV-S-ORCH-4)."""
    ann = _annotations(
        pieces=[_piece("p1", "rust"), _piece("p2", "rust")],
        transitions=[_shmem_transition("p1", "p2")],
    )
    files = emit_shared_memory(ann, chart_id="rr_chart")
    assert "p1_to_p2_ring.h" in files
    assert "p1_to_p2_ring_producer.rs" in files
    assert "p1_to_p2_ring_consumer.rs" in files


# ---------------------------------------------------------------------------
# Skipping non-shared-memory transitions
# ---------------------------------------------------------------------------


def test_emitter_skips_non_shared_memory_transitions():
    """Transitions with other media (in-process, mmio, network) are
    silently skipped — siblings own them."""
    ann = _annotations(
        pieces=[_piece("a", "rust"), _piece("b", "c"), _piece("g", "rust")],
        transitions=[
            CrossPieceTransitionAnnotation(
                source_state_id="a",
                target_state_id="b",
                event="evt.x",
                medium=MediumAnnotation(kind="in-process"),
            ),
            _shmem_transition("b", "g"),
        ],
    )
    files = emit_shared_memory(ann, chart_id="skip_chart")
    # Only the (b -> g) pairing emits.
    assert all(k.startswith("b_to_g_ring") for k in files)


# ---------------------------------------------------------------------------
# Multi-transition emission
# ---------------------------------------------------------------------------


def test_multiple_shared_memory_transitions_emit_disjoint_artifacts():
    """Two shared-memory transitions emit two artifact sets, no overlap."""
    ann = _annotations(
        pieces=[
            _piece("a", "rust"),
            _piece("b", "c"),
            _piece("c_piece", "rust"),
        ],
        transitions=[
            _shmem_transition("a", "b", ring_capacity=128),
            _shmem_transition("b", "c_piece", ring_capacity=64),
        ],
    )
    files = emit_shared_memory(ann, chart_id="multi_chart")
    # Each pairing emits header + producer + consumer.
    assert "a_to_b_ring.h" in files
    assert "b_to_c_piece_ring.h" in files
    # Capacity differs between rings.
    assert "SOS_A_B_RING_CAPACITY 128u" in files["a_to_b_ring.h"]
    assert (
        "SOS_B_C_PIECE_RING_CAPACITY 64u"
        in files["b_to_c_piece_ring.h"]
    )


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_emit_is_deterministic_byte_identical():
    """Two emit runs over the same annotations produce identical bytes."""
    ann = _annotations(
        pieces=[_piece("alpha", "rust"), _piece("beta", "c")],
        transitions=[_shmem_transition("alpha", "beta", ring_capacity=512)],
    )
    run_a = emit_shared_memory(ann, chart_id="det_chart")
    run_b = emit_shared_memory(ann, chart_id="det_chart")
    assert run_a == run_b
    assert json.dumps(run_a, sort_keys=True) == json.dumps(
        run_b, sort_keys=True
    )


# ---------------------------------------------------------------------------
# Disk write
# ---------------------------------------------------------------------------


def test_emit_writes_files_when_output_dir_given(tmp_path: Path):
    """Passing `output_dir=` writes each emitted file under
    `<output_dir>/shared_memory/<chart_id>/`."""
    ann = _annotations(
        pieces=[_piece("a", "rust"), _piece("b", "c")],
        transitions=[_shmem_transition("a", "b")],
    )
    files = emit_shared_memory(ann, chart_id="disk_chart", output_dir=tmp_path)
    out_root = tmp_path / "shared_memory" / "disk_chart"
    assert out_root.is_dir()
    for rel, body in files.items():
        target = out_root / rel
        assert target.exists()
        assert target.read_text(encoding="utf-8") == body


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------


def test_invalid_chart_id_raises():
    ann = _annotations(pieces=[_piece("a", "rust")], transitions=[])
    with pytest.raises(SharedMemoryEmitError):
        emit_shared_memory(ann, chart_id="")


def test_missing_piece_lookup_raises():
    """A transition referencing a piece not in `annotations.pieces` raises.

    Belt-and-braces — the SOS-10-A parser validates this already, but
    the emitter is defensive against direct annotation construction."""
    ann = _annotations(
        pieces=[_piece("a", "rust")],  # 'b' deliberately omitted
        transitions=[_shmem_transition("a", "b")],
    )
    with pytest.raises(SharedMemoryEmitError):
        emit_shared_memory(ann, chart_id="bad_chart")


# ---------------------------------------------------------------------------
# RTOS hint surface
# ---------------------------------------------------------------------------


def test_rtos_freertos_hint_renders_todo_block():
    """`extras["rtos"]="freertos"` surfaces a TODO(SOS-10-rtos) block
    in every emitted artifact (header + producer + consumer)."""
    ann = _annotations(
        pieces=[_piece("a", "rust"), _piece("b", "c")],
        transitions=[_shmem_transition("a", "b", rtos="freertos")],
    )
    files = emit_shared_memory(ann, chart_id="rtos_chart")
    for name, body in files.items():
        assert "TODO(SOS-10-rtos)" in body, name
        assert "xQueueSend" in body, name


def test_rtos_unknown_hint_does_not_render_todo():
    """Unknown rtos value silently no-ops; no TODO block emitted."""
    ann = _annotations(
        pieces=[_piece("a", "rust"), _piece("b", "c")],
        transitions=[_shmem_transition("a", "b", rtos="unknown_rtos")],
    )
    files = emit_shared_memory(ann, chart_id="rtos_chart_2")
    for body in files.values():
        assert "TODO(SOS-10-rtos)" not in body


# ---------------------------------------------------------------------------
# C-compile smoke
# ---------------------------------------------------------------------------


def _have_c_compiler() -> str | None:
    for cc in ("cc", "gcc", "clang"):
        path = shutil.which(cc)
        if path:
            return path
    return None


def test_emitted_header_compiles_with_c11(tmp_path: Path):
    """`gcc -Wall -Wextra -Wpedantic -std=c11` cleanly accepts the header."""
    cc = _have_c_compiler()
    if cc is None:
        pytest.skip("no C compiler available on PATH")

    ann = _annotations(
        pieces=[_piece("alpha", "rust"), _piece("beta", "c")],
        transitions=[_shmem_transition("alpha", "beta", ring_capacity=256)],
    )
    files = emit_shared_memory(ann, chart_id="cc_chart", output_dir=tmp_path)

    header_dir = tmp_path / "shared_memory" / "cc_chart"
    # Trivial TU that includes the header and uses the descriptor type.
    tu = header_dir / "use_ring.c"
    tu.write_text(
        '#include "alpha_to_beta_ring.h"\n'
        "int main(void) {\n"
        "    alpha_to_beta_ring_t r;\n"
        "    atomic_store_explicit(&r.head, 0u, memory_order_release);\n"
        "    atomic_store_explicit(&r.tail, 0u, memory_order_release);\n"
        "    r.capacity = SOS_ALPHA_BETA_RING_CAPACITY;\n"
        "    (void)r.slots[0].name_id;\n"
        "    (void)SOS_ALPHA_BETA_SHM_NAME;\n"
        "    return 0;\n"
        "}\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            cc,
            "-Wall",
            "-Wextra",
            "-Wpedantic",
            "-std=c11",
            "-c",
            str(tu),
            "-o",
            str(header_dir / "use_ring.o"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"C compile failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_emitted_c_producer_compiles_with_c11(tmp_path: Path):
    """Producer .c TU compiles under C11."""
    cc = _have_c_compiler()
    if cc is None:
        pytest.skip("no C compiler available on PATH")

    ann = _annotations(
        pieces=[_piece("alpha", "c"), _piece("beta", "c")],
        transitions=[_shmem_transition("alpha", "beta")],
    )
    emit_shared_memory(ann, chart_id="cc2", output_dir=tmp_path)

    out_root = tmp_path / "shared_memory" / "cc2"
    result = subprocess.run(
        [
            cc,
            "-Wall",
            "-Wextra",
            "-Wpedantic",
            "-std=c11",
            "-c",
            str(out_root / "alpha_to_beta_ring_producer.c"),
            "-o",
            str(out_root / "alpha_to_beta_ring_producer.o"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"C compile failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_emitted_c_consumer_compiles_with_c11(tmp_path: Path):
    """Consumer .c TU compiles under C11."""
    cc = _have_c_compiler()
    if cc is None:
        pytest.skip("no C compiler available on PATH")

    ann = _annotations(
        pieces=[_piece("alpha", "c"), _piece("beta", "c")],
        transitions=[_shmem_transition("alpha", "beta")],
    )
    emit_shared_memory(ann, chart_id="cc3", output_dir=tmp_path)

    out_root = tmp_path / "shared_memory" / "cc3"
    result = subprocess.run(
        [
            cc,
            "-Wall",
            "-Wextra",
            "-Wpedantic",
            "-std=c11",
            "-c",
            str(out_root / "alpha_to_beta_ring_consumer.c"),
            "-o",
            str(out_root / "alpha_to_beta_ring_consumer.o"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"C compile failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# Fixture-driven end-to-end
# ---------------------------------------------------------------------------


_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "sos_10_shmem"
    / "orchestrator_2piece_shmem.scxml"
)


def test_fixture_two_piece_shmem_emits_full_artifact_set():
    """End-to-end: scjson the 2-piece fixture, parse SOS-10 annotations,
    emit the shared-memory artifacts, verify the rust producer + c
    consumer + 512-slot ring-capacity override propagate."""
    ast = load_chart(_FIXTURE).raw_scjson
    annotations = parse_orchestrator_annotations(ast)
    files = emit_shared_memory(annotations, chart_id="fx_chart")

    assert "producer_to_consumer_ring.h" in files
    assert "producer_to_consumer_ring_producer.rs" in files
    assert "producer_to_consumer_ring_consumer.c" in files

    header = files["producer_to_consumer_ring.h"]
    # Chart-declared override (512) propagated.
    assert "SOS_PRODUCER_CONSUMER_RING_CAPACITY 512u" in header
    # Banner present.
    assert "INV-S-ORCH-1" in header


def test_fixture_emit_is_deterministic_across_runs():
    """Fixture-driven emit is byte-identical across two runs."""
    ast = load_chart(_FIXTURE).raw_scjson
    annotations = parse_orchestrator_annotations(ast)
    a = emit_shared_memory(annotations, chart_id="fx_chart")
    b = emit_shared_memory(annotations, chart_id="fx_chart")
    assert a == b


# ---------------------------------------------------------------------------
# Symbol-name and identifier-sanity checks
# ---------------------------------------------------------------------------


_C_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def test_emitted_header_macros_are_valid_c_identifiers():
    """Every `#define` macro name in the emitted header is a valid C
    identifier."""
    ann = _annotations(
        pieces=[_piece("alpha", "rust"), _piece("beta", "c")],
        transitions=[_shmem_transition("alpha", "beta")],
    )
    files = emit_shared_memory(ann, chart_id="ident_chart")
    header = files["alpha_to_beta_ring.h"]
    for match in re.finditer(r"^#define\s+(\S+)", header, re.MULTILINE):
        name = match.group(1)
        assert _C_IDENT_RE.match(name), f"bad macro name: {name!r}"
